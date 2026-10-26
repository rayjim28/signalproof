"""On-demand network performance checks. No bandwidth tests run on a timer."""

import csv
import io
import platform
import os
import shutil
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# These are public measurement endpoints, not game servers.
PING_TARGETS = {
    "cloudflare": ("Cloudflare", "1.1.1.1"),
    "google": ("Google DNS", "8.8.8.8"),
    "quad9": ("Quad9", "9.9.9.9"),
}
DOWNLOAD_BYTES = 12 * 1024 * 1024
UPLOAD_BYTES = 3 * 1024 * 1024
DOWNLOAD_URL = "https://speed.cloudflare.com/__down"
FALLBACK_DOWNLOAD_URL = "https://fsn1-speed.hetzner.com/100MB.bin"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
TIMEOUT_SECONDS = 18


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_ping(output, count=10):
    """Read macOS/Linux ping output and leave missing measurements unset."""
    latency = [float(n) for n in re.findall(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", output)]
    match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", output)
    loss = float(match.group(1)) if match else None
    # Average change between consecutive replies; this isn't game-engine jitter.
    jitter = statistics.mean(abs(b - a) for a, b in zip(latency, latency[1:])) if len(latency) > 1 else None
    return {
        "latency_ms": round(statistics.median(latency), 2) if latency else None,
        "jitter_ms": round(jitter, 2) if jitter is not None else None,
        "packet_loss_pct": loss,
        "packets_sent": count,
        "packets_received": len(latency),
    }


def check_ping(host):
    import platform
    timeout = "1000" if platform.system() == "Darwin" else "1"
    # On macOS ping is commonly in /sbin, which can be missing from a restricted PATH.
    ping = shutil.which("ping")
    if not ping:
        ping = next((path for path in ("/sbin/ping", "/bin/ping", "/usr/bin/ping")
                     if os.path.isfile(path) and os.access(path, os.X_OK)), None)
    if not ping:
        raise RuntimeError("The system ping command was not found.")

    command = [ping, "-n", "-c", "10", "-i", "0.25", "-W", timeout, host]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=17,
                                env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Ping timed out before completing ten requests.") from error
    except OSError as error:
        raise RuntimeError(f"Ping could not start: {error.strerror or error}.") from error

    output = result.stdout + "\n" + result.stderr
    parsed = parse_ping(output)
    if parsed["packet_loss_pct"] is None:
        # Make command failures distinguishable from packet loss.
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1][:160] if detail else "No ping statistics returned"
        raise RuntimeError(f"Could not read ping results: {reason}.")
    return parsed


def _download_from(address, provider):
    request = Request(address, headers={
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
    })
    start = time.perf_counter()
    count = 0
    # The backup file is 100 MB, but we close the stream after 12 MiB.
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        if response.headers.get("Content-Encoding", "identity").lower() not in ("identity", ""):
            raise RuntimeError("The server compressed the test data")
        while count < DOWNLOAD_BYTES:
            chunk = response.read(min(65536, DOWNLOAD_BYTES - count))
            if not chunk:
                break
            count += len(chunk)
    seconds = time.perf_counter() - start
    if count < DOWNLOAD_BYTES:
        raise RuntimeError(f"Download ended early ({count} of {DOWNLOAD_BYTES} bytes)")
    return round(8 * count / max(seconds, 0.00001) / 1_000_000, 2), count, provider


def mac_download_test():
    """Use the Mac's built-in download test instead of guessing at public file URLs."""
    program = "/usr/bin/networkQuality"
    if not os.path.isfile(program):
        program = shutil.which("networkQuality")
    if not program:
        raise RuntimeError("macOS networkQuality is not available on this Mac.")

    command = [program, "-u"]  # Download only. No upload test is started here.
    try:
        help_result = subprocess.run([program, "-h"], capture_output=True, text=True,
                                     timeout=5)
        help_text = help_result.stdout + help_result.stderr
        if "-M" in help_text:
            command.extend(["-M", "12"])
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=50, env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Apple's download test timed out.") from error
    except OSError as error:
        raise RuntimeError(f"Apple's download test could not start: {error}.") from error

    output = result.stdout + "\n" + result.stderr
    # Parse the displayed Mbps value so older/newer JSON throughput units don't matter.
    match = re.search(
        r"(?:Downlink|Download)\s+capacity\s*:\s*([\d,.]+)\s*([GMK]?bps)",
        output, re.IGNORECASE)
    if result.returncode != 0 or not match:
        detail = next((line.strip() for line in reversed(output.splitlines()) if line.strip()),
                      "No download reading returned")
        raise RuntimeError(f"Apple networkQuality: {detail[:180]}")
    scale = {"kbps": .001, "mbps": 1.0, "gbps": 1000.0}
    mbps = float(match.group(1).replace(",", "")) * scale[match.group(2).lower()]
    if mbps <= 0:
        raise RuntimeError("Apple networkQuality returned an invalid download speed.")
    return round(mbps, 2), None, "Apple networkQuality"


def check_download():
    # Prefer the native test on macOS; the HTTP endpoints stay as a fallback.
    failures = []
    if platform.system() == "Darwin":
        try:
            return mac_download_test()
        except (RuntimeError, OSError) as error:
            failures.append(f"macOS: {error}")

    # Public servers sometimes block automated downloads.
    sources = (
        (DOWNLOAD_URL + "?" + urlencode({"bytes": DOWNLOAD_BYTES}), "Cloudflare"),
        (FALLBACK_DOWNLOAD_URL, "Hetzner (fallback)"),
    )
    for address, provider in sources:
        try:
            return _download_from(address, provider)
        except (OSError, HTTPError, URLError, RuntimeError) as error:
            failures.append(f"{provider}: {error}")
    raise RuntimeError("; ".join(failures))


def check_upload():
    # Upload is explicitly started by the user and capped at 3 MiB.
    payload = b"\xA5" * UPLOAD_BYTES
    request = Request(UPLOAD_URL, data=payload, method="POST",
                      headers={"Content-Type": "application/octet-stream", "User-Agent": "SignalProof/0.5"})
    start = time.perf_counter()
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Upload endpoint returned HTTP {response.status}.")
        response.read(1024)
    seconds = time.perf_counter() - start
    return round(8 * UPLOAD_BYTES / seconds / 1_000_000, 2), UPLOAD_BYTES


def create_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS performance_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        phase TEXT NOT NULL,
        target TEXT NOT NULL,
        target_label TEXT NOT NULL,
        download_mbps REAL,
        upload_mbps REAL,
        latency_ms REAL,
        jitter_ms REAL,
        packet_loss_pct REAL,
        packets_sent INTEGER,
        packets_received INTEGER,
        downloaded_bytes INTEGER,
        uploaded_bytes INTEGER,
        notes TEXT NOT NULL DEFAULT ''
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_performance_started ON performance_tests(started_at)")


class PerformanceRunner:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory
        self.lock = threading.Lock()
        self.running_id = None

    def history(self, limit=8):
        with self.connection_factory() as db:
            rows = db.execute("SELECT * FROM performance_tests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def start(self, target):
        if target not in PING_TARGETS:
            raise ValueError("Select one of the available ping targets.")
        with self.lock:
            if self.running_id is not None:
                return None
            label, host = PING_TARGETS[target]
            with self.connection_factory() as db:
                cursor = db.execute("""INSERT INTO performance_tests
                    (started_at,status,phase,target,target_label) VALUES (?,?,?,?,?)""",
                    (now_utc(), "running", "Waiting to start", host, label))
                test_id = cursor.lastrowid
            self.running_id = test_id
        threading.Thread(target=self._run, args=(test_id, host), daemon=True).start()
        return test_id

    def _update(self, test_id, **changes):
        columns = ", ".join(f"{name}=?" for name in changes)
        with self.connection_factory() as db:
            db.execute(f"UPDATE performance_tests SET {columns} WHERE id=?", (*changes.values(), test_id))

    def _run(self, test_id, host):
        errors = []
        completed = 0
        try:
            self._update(test_id, phase="Measuring ping, jitter, and packet loss")
            try:
                self._update(test_id, **check_ping(host))
                completed += 1
            except (RuntimeError, OSError) as error:
                errors.append("Ping: " + str(error))
            self._update(test_id, phase="Measuring download speed")
            try:
                reading = check_download()
                mbps, size = reading[:2]
                provider = reading[2] if len(reading) > 2 else "Cloudflare"
                self._update(test_id, download_mbps=mbps, downloaded_bytes=size)
                if provider == "Apple networkQuality":
                    errors.append("Download used macOS networkQuality. Data usage is not capped to 12 MiB.")
                elif provider != "Cloudflare":
                    errors.append(f"Download used {provider} because Cloudflare was unavailable.")
                completed += 1
            except (RuntimeError, OSError, HTTPError, URLError, socket.timeout) as error:
                errors.append("Download: " + str(error))
            self._update(test_id, phase="Measuring upload (3 MiB)")
            try:
                mbps, size = check_upload()
                self._update(test_id, upload_mbps=mbps, uploaded_bytes=size)
                completed += 1
            except (RuntimeError, OSError, HTTPError, URLError, socket.timeout) as error:
                errors.append("Upload: " + str(error))
            status = "complete" if completed == 3 else "partial" if completed else "failed"
            self._update(test_id, finished_at=now_utc(), status=status,
                         phase="Finished", notes=" | ".join(errors))
        except Exception as error:
            self._update(test_id, finished_at=now_utc(), status="failed", phase="Finished",
                         notes=f"Unexpected test error: {type(error).__name__}: {error}")
        finally:
            with self.lock:
                if self.running_id == test_id:
                    self.running_id = None

    def status(self):
        return {"running": self.running_id is not None,
                "recent": self.history(12),
                "max_transfer_mb": None if platform.system() == "Darwin" else round((DOWNLOAD_BYTES + UPLOAD_BYTES) / 1_000_000, 1),
                "targets": {key: {"name": label, "ip": host} for key, (label, host) in PING_TARGETS.items()}}

    def csv(self):
        output = io.StringIO()
        writer = csv.writer(output)
        columns = ["started_at", "status", "target_label", "target", "download_mbps", "upload_mbps",
                   "latency_ms", "jitter_ms", "packet_loss_pct", "packets_sent", "packets_received", "notes"]
        writer.writerow(columns)
        with self.connection_factory() as db:
            for row in db.execute("SELECT * FROM performance_tests ORDER BY id DESC"):
                writer.writerow([row[column] for column in columns])
        return output.getvalue()
