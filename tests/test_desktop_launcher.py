import os
import errno
import sqlite3
import tempfile
import json
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_launcher as launcher


class LauncherTests(unittest.TestCase):
    def test_apple_string_escapes_quotes_and_slashes(self):
        self.assertEqual(launcher.apple_string('A "quote" \\ path'), 'A \\"quote\\" \\\\ path')

    def test_desktop_quit_requires_same_origin_and_json(self):
        import app
        stop = threading.Event()
        # Use a free port instead of touching the running user's localhost service.
        original_port = app.PORT
        with ThreadingHTTPServer(("127.0.0.1", 0), launcher.make_desktop_handler(app, stop)) as server:
            port = server.server_address[1]
            app.PORT = port
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f"http://127.0.0.1:{port}"
                with urlopen(base + "/api/desktop/status", timeout=2) as resp:
                    self.assertTrue(json.load(resp)["desktop"])
                blocked = Request(base + "/api/desktop/quit", data=b'{}', method="POST",
                                  headers={"Content-Type": "application/json", "Origin": "https://example.org"})
                with self.assertRaises(HTTPError) as denial:
                    urlopen(blocked, timeout=2)
                self.assertEqual(denial.exception.code, 403)
                self.assertFalse(stop.is_set())
                allowed = Request(base + "/api/desktop/quit", data=b'{}', method="POST",
                                  headers={"Content-Type": "application/json", "Origin": base})
                with urlopen(allowed, timeout=2) as resp:
                    self.assertTrue(json.load(resp)["stopping"])
                self.assertTrue(stop.wait(2))
            finally:
                server.shutdown()
                worker.join(timeout=3)
                app.PORT = original_port

    def test_existing_desktop_agent_reuses_only_our_local_service(self):
        import app
        stop = threading.Event()
        original_port = app.PORT
        with ThreadingHTTPServer(("127.0.0.1", 0), launcher.make_desktop_handler(app, stop)) as server:
            port = server.server_address[1]
            app.PORT = port
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                self.assertTrue(launcher.existing_desktop_agent(port, attempts=1))
                with patch.object(launcher, 'prepare_storage'), \
                     patch.object(launcher, 'show_dashboard') as show, \
                     patch.object(launcher, 'prompt') as prompt:
                    launcher.run()
                    show.assert_called_once_with(port)
                    prompt.assert_not_called()
            finally:
                server.shutdown()
                worker.join(timeout=3)
                app.PORT = original_port

    def test_other_local_server_never_reused_as_signalproof(self):
        import app
        class OtherServer(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"desktop":false}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass

        original_port = app.PORT
        with ThreadingHTTPServer(("127.0.0.1", 0), OtherServer) as server:
            port = server.server_address[1]
            app.PORT = port
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                self.assertFalse(launcher.existing_desktop_agent(port, attempts=1))
                with patch.object(launcher, 'prepare_storage'), \
                     patch.object(launcher, 'show_dashboard') as show, \
                     patch.object(launcher, 'prompt') as prompt:
                    launcher.run()
                    show.assert_not_called()
                    prompt.assert_called_once()
            finally:
                server.shutdown()
                worker.join(timeout=3)
                app.PORT = original_port

    def test_unrelated_bind_error_does_not_open_other_dashboard(self):
        import app
        with patch.object(launcher, 'prepare_storage'), \
             patch('http.server.ThreadingHTTPServer', side_effect=OSError(errno.EACCES, 'Denied')), \
             patch.object(launcher, 'existing_desktop_agent') as existing, \
             patch.object(launcher, 'show_dashboard') as show, \
             patch.object(launcher, 'prompt') as prompt:
            launcher.run()
            existing.assert_not_called()
            show.assert_not_called()
            prompt.assert_called_once()

    def test_prepare_storage_migrates_existing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / 'old.db'
            new_dir = root / 'Application Support' / 'SignalProof'
            with sqlite3.connect(old) as con:
                con.execute('CREATE TABLE measurements (value INTEGER)')
                con.execute('INSERT INTO measurements VALUES (42)')

            with patch.object(launcher, 'DATA_DIR', new_dir), \
                 patch.object(launcher, 'LOG_DIR', root / 'logs'), \
                 patch.object(launcher, 'OLD_DB', old), \
                 patch.dict(os.environ, {}, clear=True):
                launcher.prepare_storage()
                self.assertEqual(os.environ['SIGNALPROOF_DB'], str(new_dir / 'measurements.db'))
                with sqlite3.connect(new_dir / 'measurements.db') as con:
                    self.assertEqual(con.execute('SELECT value FROM measurements').fetchone()[0], 42)

    def test_prepare_storage_keeps_existing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / 'old.db'
            new_dir = root / 'SignalProof'
            new_dir.mkdir()
            with sqlite3.connect(old) as con:
                con.execute('CREATE TABLE notes (value INTEGER)')
                con.execute('INSERT INTO notes VALUES (5)')
            with sqlite3.connect(new_dir / 'measurements.db') as con:
                con.execute('CREATE TABLE notes (value INTEGER)')
                con.execute('INSERT INTO notes VALUES (9)')

            with patch.object(launcher, 'DATA_DIR', new_dir), \
                 patch.object(launcher, 'LOG_DIR', root / 'logs'), \
                 patch.object(launcher, 'OLD_DB', old), \
                 patch.dict(os.environ, {}, clear=True):
                launcher.prepare_storage()
                with sqlite3.connect(new_dir / 'measurements.db') as con:
                    self.assertEqual(con.execute('SELECT value FROM notes').fetchone()[0], 9)
