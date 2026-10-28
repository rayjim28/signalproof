"""Local network monitoring and dashboard server."""

import csv
import html
import io
import json
import os
import platform
import re
import socket
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from performance import PerformanceRunner, create_table
from quality_signals import summarize_quality
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("SIGNALPROOF_DB", str(ROOT / "measurements.db")))
PORT = int(os.environ.get("SIGNALPROOF_PORT", "8765"))
DEFAULT_SETTINGS = {"interval_seconds": 20, "confirm_failures": 2, "recovery_successes": 2, "slow_connect_ms": 200}
SETTING_OPTIONS = {
    "interval_seconds": {10, 20, 30, 60, 120},
    "confirm_failures": {2, 3, 4, 5},
    "recovery_successes": {1, 2, 3, 4},
    "slow_connect_ms": {100, 200, 300, 500, 1000},
}
PERIODS = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
TARGETS = (("Internet", "1.1.1.1", 443), ("Secondary", "8.8.8.8", 443))
DB_LOCK = threading.Lock()
PROBE_LOCK = threading.Lock()
MONITOR_ACTIVE = threading.Event()
MONITOR_ACTIVE.set()
MONITOR_CHANGED = threading.Event()


@contextmanager
def connection():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


PERFORMANCE = PerformanceRunner(connection)

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT NOT NULL,
            target TEXT NOT NULL,
            online INTEGER NOT NULL,
            latency_ms REAL,
            detail TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_measurement_time ON measurements(checked_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,
            ended_at TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS monitor_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            failures INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            first_failure_at TEXT,
            open_incident_id INTEGER
        )""")
        db.execute("INSERT OR IGNORE INTO monitor_state(id) VALUES (1)")
        db.execute("""CREATE TABLE IF NOT EXISTS monitor_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            interval_seconds INTEGER NOT NULL DEFAULT 20,
            confirm_failures INTEGER NOT NULL DEFAULT 2,
            recovery_successes INTEGER NOT NULL DEFAULT 2,
            slow_connect_ms INTEGER NOT NULL DEFAULT 200
        )""")
        db.execute("INSERT OR IGNORE INTO monitor_settings(id) VALUES (1)")
        create_table(db)



def get_settings():
    with connection() as db:
        row = db.execute("SELECT * FROM monitor_settings WHERE id=1").fetchone()
    return {key: row[key] for key in DEFAULT_SETTINGS}


def update_settings(changes):
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Choose at least one setting to update.")
    if set(changes) - set(SETTING_OPTIONS):
        raise ValueError("Unknown monitoring setting.")
    for key, value in changes.items():
        if type(value) is not int or value not in SETTING_OPTIONS[key]:
            raise ValueError(f"Unsupported value for {key}.")

    # Don't change the incident counters in the middle of a measurement round.
    with PROBE_LOCK, DB_LOCK, connection() as db:
        before = db.execute("SELECT * FROM monitor_settings WHERE id=1").fetchone()
        values = {key: changes.get(key, before[key]) for key in DEFAULT_SETTINGS}
        db.execute("""UPDATE monitor_settings SET interval_seconds=?,confirm_failures=?,
                   recovery_successes=?,slow_connect_ms=? WHERE id=1""",
                   tuple(values.values()))
        if (before["confirm_failures"] != values["confirm_failures"] or
                before["recovery_successes"] != values["recovery_successes"]):
            # Keep an open incident, but start counting against the new rules.
            db.execute("""UPDATE monitor_state SET failures=0,successes=0,
                       first_failure_at=NULL WHERE id=1""")
    MONITOR_CHANGED.set()
    return values


def parse_time(value):
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def incident_history(db, since):
    now = datetime.now(timezone.utc)
    boundary = parse_time(since)
    rows = [dict(row) for row in db.execute(
        "SELECT id,started_at,confirmed_at,ended_at FROM incidents "
        "WHERE ended_at IS NULL OR ended_at >= ? ORDER BY started_at DESC, id DESC", (since,)
    )]
    summaries = []
    for item in rows:
        started = parse_time(item["started_at"])
        ended = parse_time(item["ended_at"]) if item["ended_at"] else now
        if started > now:
            continue
        duration = max(0, int((ended - started).total_seconds()))
        overlap = max(0, int((min(ended, now) - max(started, boundary)).total_seconds()))
        if overlap == 0 and item["ended_at"] and ended < boundary:
            continue
        summaries.append({**item, "duration_seconds": duration,
                          "window_seconds": overlap, "ongoing": item["ended_at"] is None})
    new = [item for item in summaries if parse_time(item["confirmed_at"]) >= boundary]
    return {
        "confirmed": len(new),
        "recovered": sum(1 for item in new if not item["ongoing"]),
        "ongoing": sum(1 for item in summaries if item["ongoing"]),
        "longest_seconds": max((item["duration_seconds"] for item in summaries if not item["ongoing"]), default=0),
        "observed_seconds": sum(item["window_seconds"] for item in summaries),
        "recent": summaries[:100],
    }

def gateway_address():
    try:
        if platform.system() == "Darwin":
            proc = subprocess.run(["route", "-n", "get", "default"], capture_output=True,
                                  text=True, timeout=2)
            found = re.search(r"^\s*gateway:\s*(\d+\.\d+\.\d+\.\d+)", proc.stdout, re.M)
            return found.group(1) if found else None
        if platform.system() == "Linux":
            with open("/proc/net/route", encoding="utf8") as routes:
                for line in routes.readlines()[1:]:
                    parts = line.split()
                    if len(parts) > 3 and parts[1] == "00000000" and (int(parts[3], 16) & 2):
                        return ".".join(str(n) for n in reversed(bytes.fromhex(parts[2])))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def gateway_probe(address):
    try:
        result = subprocess.run(["ping", "-c", "1", address], capture_output=True,
                                text=True, timeout=4)
        found = re.search(r"time[=<]([\d.]+)\s*ms", result.stdout)
        latency = round(float(found.group(1)), 1) if found else None
        return result.returncode == 0, latency, "ICMP echo to local gateway"
    except (OSError, subprocess.TimeoutExpired):
        return False, None, "Gateway ICMP request timed out or was unavailable"


def internet_probe(host="1.1.1.1", port=443):
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=3):
            elapsed = round((time.monotonic() - start) * 1000, 1)
            return True, elapsed, f"TCP connect to {host}:{port}"
    except OSError as error:
        return False, None, f"TCP connect to {host}:{port} failed ({type(error).__name__})"


def save_incident_state(db, checked_at, both_failed, settings=None):
    settings = settings or DEFAULT_SETTINGS
    state = db.execute("SELECT * FROM monitor_state WHERE id=1").fetchone()
    failures, successes = state["failures"], state["successes"]
    first, opened = state["first_failure_at"], state["open_incident_id"]
    if both_failed:
        failures += 1
        successes = 0
        first = first or checked_at
        if failures >= settings["confirm_failures"] and opened is None:
            cursor = db.execute(
                "INSERT INTO incidents(started_at,confirmed_at) VALUES (?,?)", (first, checked_at)
            )
            opened = cursor.lastrowid
    else:
        successes += 1
        failures = 0
        first = None
        if opened is not None and successes >= settings["recovery_successes"]:
            db.execute("UPDATE incidents SET ended_at=? WHERE id=?", (checked_at, opened))
            opened = None
    db.execute("""UPDATE monitor_state SET failures=?,successes=?,first_failure_at=?,
               open_incident_id=? WHERE id=1""", (failures, successes, first, opened))


def run_probes():
    # One round at a time keeps the incident counter consistent with the saved checks.
    with PROBE_LOCK:
        settings = get_settings()
        checks = []
        gateway = gateway_address()
        if gateway:
            checks.append(("Gateway", *gateway_probe(gateway)))
        for name, host, port in TARGETS:
            checks.append((name, *internet_probe(host, port)))
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results = {name: ok for name, ok, *_ in checks}
        both_failed = not results["Internet"] and not results["Secondary"]
        with DB_LOCK, connection() as db:
            db.executemany(
                "INSERT INTO measurements(checked_at,target,online,latency_ms,detail) VALUES(?,?,?,?,?)",
                [(stamp, name, int(ok), latency, detail) for name, ok, latency, detail in checks],
            )
            save_incident_state(db, stamp, both_failed, settings)
        return [{"target": name, "online": ok, "latency_ms": latency,
                 "detail": detail, "checked_at": stamp} for name, ok, latency, detail in checks]


def window_since(window):
    return (datetime.now(timezone.utc) - timedelta(hours=PERIODS.get(window, 6))).isoformat(timespec="seconds")


def diagnosis(stats, state, latest, gateway, settings=None):
    settings = settings or DEFAULT_SETTINGS
    primary = stats["internet"]["last"]
    secondary = stats["secondary"]["last"]
    if not primary:
        return {"level": "waiting", "title": "Waiting for measurements",
                "detail": "Keep the local monitor running to get a baseline.",
                "next_step": "Run a diagnostic to collect the first set of checks."}
    if not secondary:
        return {"level": "limited", "title": "Single-target history",
                "detail": "This period includes older readings collected before the second endpoint was added.",
                "next_step": "Run a diagnostic for a two-target comparison."}
    if not primary["online"] and not secondary["online"]:
        confirmed = state["open_incident_id"] is not None or state["failures"] >= settings["confirm_failures"]
        return {"level": "down" if confirmed else "warning",
                "title": "Repeated connection failures" if confirmed else "Connection failure detected",
                "detail": "Both external TCP targets failed. This is evidence of reachability problems, not proof of ISP fault.",
                "next_step": "Check the router, then compare results on another device. Keep monitoring for a recovery."}
    if not primary["online"] or not secondary["online"]:
        return {"level": "warning", "title": "Partial endpoint reachability",
                "detail": "One destination responded and the other did not. Your entire internet connection is not necessarily down.",
                "next_step": "Repeat the check and compare whether the same endpoint continues to fail."}
    if any(row["latency_ms"] is not None and row["latency_ms"] >= settings["slow_connect_ms"]
           for row in (primary, secondary)):
        return {"level": "warning", "title": "Slow TCP connection observed",
                "detail": f"At least one successful TCP connection took {settings['slow_connect_ms']} ms or longer.",
                "next_step": "Watch for repeated spikes and compare results at different times."}
    if gateway and not gateway["online"]:
        return {"level": "good", "title": "External endpoints reachable",
                "detail": "Both external TCP checks succeeded. The gateway did not answer ICMP; some routers ignore ping requests.",
                "next_step": "The gateway result alone is not evidence that your Wi-Fi is down."}
    return {"level": "good", "title": "External endpoints reachable",
            "detail": "Both monitored TCP destinations accepted the latest connections.",
            "next_step": "Keep the agent running to capture intermittent changes."}


def get_data(window="6h"):
    since = window_since(window)
    settings = get_settings()
    with connection() as db:
        history = incident_history(db, since)
        quality = summarize_quality(db, since, settings)
        records = [dict(row) for row in db.execute(
            "SELECT id,checked_at,target,online,latency_ms,detail FROM measurements "
            "WHERE checked_at>=? ORDER BY id DESC LIMIT 900", (since,)
        )]
        rows = db.execute(
            "SELECT target,COUNT(*) total,SUM(online) successful," 
            "SUM(CASE WHEN online=0 THEN 1 ELSE 0 END) failures," 
            "AVG(CASE WHEN online=1 THEN latency_ms END) avg_latency "
            "FROM measurements WHERE checked_at>=? GROUP BY target", (since,)
        ).fetchall()
        incidents = history["recent"]
        state = dict(db.execute("SELECT * FROM monitor_state WHERE id=1").fetchone())
    summaries = {row["target"]: row for row in rows}
    stats = {}
    for name in ("Internet", "Secondary", "Gateway"):
        row = summaries.get(name)
        total = row["total"] if row else 0
        last = next((item for item in records if item["target"] == name), None)
        stats[name.lower()] = {
            "total": total,
            "success_pct": round(100 * row["successful"] / total, 1) if total else None,
            "avg_latency_ms": round(row["avg_latency"], 1) if row and row["avg_latency"] is not None else None,
            "failures": row["failures"] if row else 0,
            "last": last,
        }
    latest = {item["target"]: item for item in reversed(records) if item["target"] in
              ("Internet", "Secondary", "Gateway")}
    return {
        "records": records,
        "quality": quality,
        "stats": stats,
        "diagnosis": diagnosis(stats, state, latest, latest.get("Gateway"), settings),
        "incidents": incidents,
        "incident_summary": {key: history[key] for key in ("confirmed", "recovered", "ongoing", "longest_seconds", "observed_seconds")},
        "pending_failures": state["failures"],
        "settings": settings,
        "interval_seconds": settings["interval_seconds"],
        "period": window if window in PERIODS else "6h",
        "monitoring": MONITOR_ACTIVE.is_set(),
        "gateway_address": gateway_address(),
        "platform": platform.system(),
        "limit_notice": "Chart and table show recent checks (up to 900 rows). Statistics and exports use the whole period.",
    }


def export_csv(window="6h"):
    with connection() as db:
        rows = db.execute(
            "SELECT checked_at,target,online,latency_ms,detail FROM measurements "
            "WHERE checked_at >= ? ORDER BY id DESC", (window_since(window),)
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp_utc", "target", "connected", "latency_ms", "method"])
        writer.writerows(rows)
    return output.getvalue()



def export_incidents_csv(window="6h"):
    with connection() as db:
        history = incident_history(db, window_since(window))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["first_failure_utc", "confirmed_utc", "recovered_utc", "status", "observed_span_seconds"])
    for incident in history["recent"]:
        writer.writerow([incident["started_at"], incident["confirmed_at"], incident["ended_at"] or "",
                         "ongoing" if incident["ongoing"] else "resolved", incident["duration_seconds"]])
    return output.getvalue()

def report_html(window="6h"):
    data = get_data(window)
    with connection() as db:
        recent = [dict(row) for row in db.execute(
            "SELECT checked_at,target,online,latency_ms,detail FROM measurements "
            "WHERE checked_at>=? ORDER BY id DESC LIMIT 24", (window_since(window),)
        )]
    escape = lambda value: html.escape(str(value if value is not None else "—"), quote=True)
    when = datetime.now(timezone.utc).strftime("%B %d, %Y · %H:%M UTC")
    primary = data["stats"]["internet"]
    other = data["stats"]["secondary"]
    diagnosis_data = data["diagnosis"]
    summary = data["incident_summary"]
    settings = data["settings"]
    manual_tests = PERFORMANCE.history(1)
    manual = manual_tests[0] if manual_tests else None
    counts = summary["confirmed"]
    closed = summary["recovered"]
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td></tr>".format(
            escape(row["checked_at"]), escape(row["target"]),
            "pass" if row["online"] else "fail", "Connected" if row["online"] else "Failed",
            escape(f'{row["latency_ms"]} ms' if row["latency_ms"] is not None else "—")
        ) for row in recent
    )
    def manual_metric(key, unit):
        return escape(f"{manual[key]} {unit}" if manual and manual[key] is not None else "Not measured")
    manual_summary = (
        "<h2>Most recent manual performance test</h2>"
        "<div class='section'><p><strong>Test date:</strong> "
        + escape(manual["started_at"] if manual else "No tests yet")
        + " · <strong>Target:</strong> " + escape(manual["target_label"] if manual else "—")
        + " · <strong>Status:</strong> " + escape(manual["status"] if manual else "—") + "</p>"
        + "<p><strong>Download:</strong> " + manual_metric("download_mbps", "Mbps")
        + " · <strong>Upload:</strong> " + manual_metric("upload_mbps", "Mbps")
        + " · <strong>ICMP latency:</strong> " + manual_metric("latency_ms", "ms")
        + " · <strong>Jitter:</strong> " + manual_metric("jitter_ms", "ms")
        + " · <strong>ICMP loss:</strong> " + manual_metric("packet_loss_pct", "%") + "</p>"
        + "<p class='caution'>" + escape(manual["notes"] if manual else "Speed tests run only when started manually.") + "</p></div>"
    )
    incident_rows = "".join(
        f'<tr><td>{escape(item["started_at"])}</td><td>{escape(item["confirmed_at"])}</td>'
        f'<td>{escape(item["ended_at"] or "Still open")}</td></tr>'
        for item in data["incidents"][:12]
    ) or '<tr><td colspan="3">No confirmed incidents in the selected history.</td></tr>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>SignalProof | Connection report</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {{font-family:Arial,Helvetica,sans-serif;color:#182632;background:#f3f6f8}}
*{{box-sizing:border-box}}body{{margin:0}}.wrap{{max-width:950px;margin:auto;padding:35px}}
header{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #1385a4;padding-bottom:19px}}
h1{{font-size:28px;margin:12px 0 4px}}h2{{font-size:16px;margin-top:32px}}.muted{{color:#647481;font-size:12px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:23px 0}}.card,.section{{background:white;border:1px solid #dce3e8;border-radius:9px;padding:19px}}.card b{{display:block;font-size:26px;margin-top:9px}}.card small{{color:#607481}}
.summary{{border-left:4px solid #1385a4;background:#e8f5f8;padding:14px 18px;line-height:1.6}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:10px;border-bottom:1px solid #dbe2e8;text-align:left}}th{{background:#eaf0f3}}.pass{{color:#146e56}}.fail{{color:#aa4633}}.caution{{color:#647481;line-height:1.6;font-size:12px}}.print{{background:#102b3a;color:#fff;border:0;padding:11px 18px;border-radius:6px;cursor:pointer}}
@media print{{:root{{background:#fff}}.wrap{{padding:0}}.print{{display:none}}.card,.section{{break-inside:avoid}}}}
</style></head><body><div class="wrap"><header><div><strong>SIGNALPROOF</strong><h1>Connection evidence report</h1><div class="muted">Last {escape(window)} · Generated {escape(when)}</div></div><button class="print" onclick="window.print()">Print / Save as PDF</button></header>
<div class="cards"><div class="card"><small>PRIMARY SUCCESS RATE</small><b>{escape(str(primary["success_pct"]) + "%" if primary["success_pct"] is not None else "—")}</b></div>
<div class="card"><small>PRIMARY AVERAGE TCP CONNECT</small><b>{escape(str(primary["avg_latency_ms"]) + " ms" if primary["avg_latency_ms"] is not None else "—")}</b></div>
<div class="card"><small>CONFIRMED INCIDENTS</small><b>{counts}</b><small>{closed} resolved in the selected history</small></div></div>
<div class="summary"><strong>Latest assessment: {escape(diagnosis_data["title"])}</strong><br>{escape(diagnosis_data["detail"])}<br><strong>Suggested check:</strong> {escape(diagnosis_data["next_step"])}</div>
<h2>What was measured</h2><p>Two external TCP destinations (1.1.1.1:443 and 8.8.8.8:443), plus the detected default gateway over ICMP where available. The configured interval is {settings["interval_seconds"]} seconds while this Mac is awake and the monitor is active.</p>
<p>Primary checks: {primary["total"]}. Secondary checks: {other["total"]}. Failed primary checks: {primary["failures"]}. Current rule: {settings["confirm_failures"]} consecutive failed rounds to confirm; {settings["recovery_successes"]} reachable rounds to resolve. Historical incidents may have used earlier settings.</p>
{manual_summary}
<h2>Incident analysis</h2><p>{summary["ongoing"]} ongoing · {summary["recovered"]} recovered in this period · Longest resolved span: {summary["longest_seconds"]} seconds · Combined observed incident spans within the selected period: {summary["observed_seconds"]} seconds. These are measurement-based spans, not verified outage durations.</p>
<h2>Confirmed incident history</h2><div class="section"><table><thead><tr><th>First failure (UTC)</th><th>Confirmed (UTC)</th><th>Recovered (UTC)</th></tr></thead><tbody>{incident_rows}</tbody></table></div>
<h2>Latest measurements</h2><div class="section"><table><thead><tr><th>Time (UTC)</th><th>Test</th><th>Result</th><th>TCP / ICMP time</th></tr></thead><tbody>{rows or '<tr><td colspan="4">No samples yet.</td></tr>'}</tbody></table></div>
<h2>Interpretation limits</h2><p class="caution">This report documents observed reachability checks, not verified ISP outages. Manual speed checks may use the macOS networkQuality test or limited HTTP transfers, and are not certified maximum speeds. The ICMP ping target is not a game server, so its latency is not exact in-game ping. TCP connect time is not ICMP ping or download speed. Gateways may block ICMP. A failure at one endpoint may be specific to that destination. Changing confirmation settings doesn't rewrite older incident records. Checks are missed while the device sleeps, the app is closed, or monitoring is paused. Success percentages are based on samples, not time-weighted uptime. For raw measurements, export the CSV from the dashboard.</p>
<div class="muted">SignalProof · Local network evidence · Report generated on this device</div></div></body></html>"""


def monitor():
    while True:
        if MONITOR_ACTIVE.is_set():
            try:
                run_probes()
            except Exception as error:
                print("Monitor error:", error, flush=True)
            MONITOR_CHANGED.wait(get_settings()["interval_seconds"])
        else:
            MONITOR_CHANGED.wait()
        MONITOR_CHANGED.clear()


class Handler(BaseHTTPRequestHandler):
    def output(self, data, status=200, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(data, bytes):
            data = (data if isinstance(data, str) else json.dumps(data)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_host(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        if not self.allowed_host():
            return self.output({"error": "Local requests only"}, status=403)
        url = urlparse(self.path)
        period = parse_qs(url.query).get("period", ["6h"])[0]
        if period not in PERIODS:
            period = "6h"
        if url.path == "/api/performance":
            return self.output(PERFORMANCE.status())
        if url.path == "/api/performance/export":
            return self.output(PERFORMANCE.csv(), content_type="text/csv; charset=utf-8",
                               headers={"Content-Disposition": 'attachment; filename="signalproof-performance.csv"'})
        if url.path == "/api/data":
            return self.output(get_data(period))
        if url.path == "/api/settings":
            return self.output(get_settings())
        if url.path == "/api/incidents/export":
            return self.output(export_incidents_csv(period), content_type="text/csv; charset=utf-8",
                               headers={"Content-Disposition": f'attachment; filename="signalproof-incidents-{period}.csv"'})
        if url.path == "/api/export":
            return self.output(export_csv(period), content_type="text/csv; charset=utf-8",
                               headers={"Content-Disposition": f'attachment; filename="signalproof-evidence-{period}.csv"'})
        if url.path == "/api/report":
            return self.output(report_html(period), content_type="text/html; charset=utf-8")
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        }
        if url.path in files:
            filename, mime = files[url.path]
            return self.output((ROOT / filename).read_bytes(), content_type=mime)
        return self.output({"error": "Not found"}, status=404)

    def do_POST(self):
        if not self.allowed_host():
            return self.output({"error": "Local requests only"}, status=403)
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.output({"error": "Origin not allowed"}, status=403)
        route = urlparse(self.path).path
        if route == "/api/performance/start":
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 128:
                    return self.output({"error": "Invalid request size"}, status=400)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Invalid request")
                test_id = PERFORMANCE.start(body.get("target"))
                if test_id is None:
                    return self.output({"error": "A performance test is already running."}, status=409)
                return self.output({"id": test_id, "status": "running"}, status=202)
            except (ValueError, TypeError) as error:
                return self.output({"error": str(error)}, status=400)
        if route == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1024:
                    return self.output({"error": "Invalid request size"}, status=400)
                changes = json.loads(self.rfile.read(length))
                settings = update_settings(changes)
                return self.output({"settings": settings})
            except (ValueError, TypeError) as error:
                return self.output({"error": str(error)}, status=400)
        if route == "/api/probe":
            return self.output({"checks": run_probes()})
        if route == "/api/monitor":
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                return self.output({"error": "Invalid Content-Length"}, status=400)
            if length < 0 or length > 128:
                return self.output({"error": "Invalid request"}, status=400)
            try:
                action = json.loads(self.rfile.read(length) or b"{}").get("action")
            except (ValueError, AttributeError):
                return self.output({"error": "Invalid JSON"}, status=400)
            if action == "pause":
                MONITOR_ACTIVE.clear()
            elif action == "resume":
                MONITOR_ACTIVE.set()
            else:
                return self.output({"error": "Unknown action"}, status=400)
            MONITOR_CHANGED.set()
            return self.output({"monitoring": MONITOR_ACTIVE.is_set()})
        return self.output({"error": "Not found"}, status=404)

    def log_message(self, fmt, *args):
        pass


def main():
    initialize()
    threading.Thread(target=monitor, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"SignalProof: http://127.0.0.1:{PORT}", flush=True)
    print("Local database:", DB, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
