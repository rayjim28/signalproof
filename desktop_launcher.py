"""Start SignalProof from Finder and keep local monitoring under user control."""

import logging
import errno
import json
from contextlib import closing
import os
import signal
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlparse

APP_NAME = "SignalProof"
DATA_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
OLD_DB = Path.home() / "personal_projects" / "signalproof" / "measurements.db"
PORT = 8765


def prepare_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "launcher.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if "SIGNALPROOF_DB" not in os.environ:
        database = DATA_DIR / "measurements.db"
        if not database.exists() and OLD_DB.exists():
            # SQLite's backup API also handles a database with live WAL files.
            with closing(sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(database)) as destination:
                    source.backup(destination)
            logging.info("Copied existing history to Application Support")
        os.environ["SIGNALPROOF_DB"] = str(database)
    os.environ.setdefault("SIGNALPROOF_PORT", str(PORT))


def apple_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prompt(message, buttons=("Quit SignalProof", "Open Dashboard")):
    labels = ", ".join('"' + apple_string(value) + '"' for value in buttons)
    script = (
        f'button returned of (display dialog "{apple_string(message)}" '
        f'with title "SignalProof" buttons {{{labels}}} '
        f'default button "{apple_string(buttons[-1])}")'
    )
    proc = subprocess.run(
        ["/usr/bin/osascript", "-e", script], capture_output=True, text=True
    )
    if proc.returncode:
        logging.warning("Native prompt exited: %s", proc.stderr.strip())
        return buttons[0]
    return proc.stdout.strip()


def show_dashboard(port):
    """Bring the web dashboard forward without launching another local server."""
    subprocess.Popen(["/usr/bin/open", f"http://127.0.0.1:{port}/"])


def existing_desktop_agent(port, attempts=12):
    """Only reuse a port if it responds as the SignalProof desktop agent.

    A different local web server (including a developer run of app.py) must
    never be mistaken for the packaged desktop application. Brief retries
    allow a concurrently launched instance time to finish starting up.
    """
    url = f"http://127.0.0.1:{port}/api/desktop/status"
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            with urlopen(req, timeout=0.7) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status != 200 or "application/json" not in content_type.lower():
                    return False
                status = json.loads(response.read(512))
                return isinstance(status, dict) and status.get("desktop") is True
        except (OSError, ValueError, UnicodeError):
            # A second instance may be in the process of starting its HTTP server.
            if attempt + 1 < attempts:
                time.sleep(0.2)
    return False


def open_dashboard(port):
    url = f"http://127.0.0.1:{port}/"
    for _ in range(25):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    show_dashboard(port)
                    return
        except OSError:
            time.sleep(0.2)
    logging.warning("Dashboard did not respond at %s", url)
    prompt("SignalProof started, but the dashboard could not be opened. Check the launcher log.", ("Close",))


def make_desktop_handler(app, shutdown_requested):
    """Extend the localhost dashboard with a desktop-only, same-origin Quit action."""

    class DesktopHandler(app.Handler):
        def do_GET(self):
            if urlparse(self.path).path == "/api/desktop/status":
                if not self.allowed_host():
                    return self.output({"error": "Local requests only"}, status=403)
                return self.output({"desktop": True})
            return super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path == "/api/desktop/quit":
                if not self.allowed_host():
                    return self.output({"error": "Local requests only"}, status=403)
                # Require the dashboard's exact localhost origin and JSON content type,
                # so a third-party page cannot stop the agent with a simple form POST.
                expected_origin = f"http://{self.headers.get('Host', '')}"
                if (self.headers.get("Origin") != expected_origin or
                        self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"):
                    return self.output({"error": "Origin or content type not allowed"}, status=403)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if not 0 < length <= 128:
                    return self.output({"error": "Invalid request size"}, status=400)
                # Drain the small request body to keep the connection well behaved.
                self.rfile.read(length)
                self.output({"stopping": True})
                shutdown_requested.set()
                return
            return super().do_POST()

    return DesktopHandler


def run():
    prepare_storage()
    import app
    from http.server import ThreadingHTTPServer

    port = app.PORT
    stop_event = threading.Event()
    handler = make_desktop_handler(app, stop_event)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        # Reopening the app must not create a second monitoring agent or block
        # the user with a port error when SignalProof is already running.
        if exc.errno == errno.EADDRINUSE and existing_desktop_agent(port):
            logging.info("SignalProof is already running; reopening its dashboard")
            try:
                show_dashboard(port)
            except OSError as open_error:
                logging.error("Could not reopen existing dashboard: %s", open_error)
                prompt("SignalProof is running, but its dashboard could not be opened.", ("Close",))
            return
        logging.error("Could not start local server: %s", exc)
        prompt(
            f"Could not start SignalProof on port {port}. Another app may be using this port. Close it and try again.",
            ("Close",),
        )
        return

    worker = None
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        app.initialize()
        threading.Thread(target=app.monitor, daemon=True, name="monitor").start()
        worker = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard")
        worker.start()
        logging.info("SignalProof monitoring started on 127.0.0.1:%d", port)
        open_dashboard(port)
        # Unlike the old launcher, this does not display a Quit/Open dialog.
        # Browser tabs can close without stopping the monitoring service.
        # Quit from the desktop dashboard or from macOS to stop monitoring.
        stop_event.wait()
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        app.MONITOR_ACTIVE.clear()
        app.MONITOR_CHANGED.set()
        if worker is not None:
            server.shutdown()
            worker.join(timeout=3)
        server.server_close()
        logging.info("SignalProof stopped")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logging.exception("SignalProof could not start")
        try:
            prompt(f"SignalProof couldn't start: {str(exc)[:200]}. Check Library/Logs/SignalProof/launcher.log.", ("Close",))
        except OSError:
            pass
        raise
