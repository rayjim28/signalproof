"""Checks settings and incident history against a temporary database."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class SettingsHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = app.DB
        app.DB = Path(self.temp.name) / "measurements.db"
        app.initialize()

    def tearDown(self):
        app.DB = self.previous_db
        self.temp.cleanup()

    def round(self, online):
        with patch.object(app, "gateway_address", return_value=None), \
             patch.object(app, "internet_probe", return_value=(online, 20.0 if online else None, "test")):
            app.run_probes()

    def test_settings_persist_and_validate(self):
        self.assertEqual(app.get_settings()["interval_seconds"], 20)
        app.update_settings({"interval_seconds": 60, "slow_connect_ms": 300})
        self.assertEqual(app.get_settings()["interval_seconds"], 60)
        self.assertEqual(app.get_settings()["slow_connect_ms"], 300)
        with self.assertRaises(ValueError):
            app.update_settings({"interval_seconds": 1})
        with self.assertRaises(ValueError):
            app.update_settings({"confirm_failures": True})
        with self.assertRaises(ValueError):
            app.update_settings({"unexpected": 2})
        self.assertEqual(app.get_settings()["interval_seconds"], 60)
        app.initialize()
        self.assertEqual(app.get_settings()["interval_seconds"], 60)

    def test_configured_incident_thresholds(self):
        app.update_settings({"confirm_failures": 3, "recovery_successes": 3})
        self.round(False)
        self.round(False)
        self.assertEqual(app.get_data()["incident_summary"]["confirmed"], 0)
        self.round(False)
        self.assertEqual(app.get_data()["incident_summary"]["confirmed"], 1)
        self.round(True)
        self.round(True)
        self.assertTrue(app.get_data()["incidents"][0]["ongoing"])
        self.round(True)
        self.assertFalse(app.get_data()["incidents"][0]["ongoing"])

    def test_threshold_change_resets_pending_but_keeps_open_incident(self):
        self.round(False)
        app.update_settings({"confirm_failures": 4})
        self.assertEqual(app.get_data()["pending_failures"], 0)
        for _ in range(4):
            self.round(False)
        self.assertEqual(app.get_data()["incident_summary"]["ongoing"], 1)
        app.update_settings({"recovery_successes": 1})
        self.assertEqual(app.get_data()["incident_summary"]["ongoing"], 1)
        self.round(True)
        self.assertEqual(app.get_data()["incident_summary"]["ongoing"], 0)

    def test_incident_report_and_window_clip(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start = (now - timedelta(minutes=90)).isoformat()
        confirmed = (now - timedelta(minutes=89)).isoformat()
        end = (now - timedelta(minutes=25)).isoformat()
        with app.connection() as db:
            db.execute("INSERT INTO incidents(started_at,confirmed_at,ended_at) VALUES (?,?,?)",
                       (start, confirmed, end))
        data = app.get_data("1h")
        self.assertEqual(data["incident_summary"]["confirmed"], 0)
        self.assertEqual(data["incident_summary"]["observed_seconds"], 35 * 60)
        self.assertEqual(data["incident_summary"]["longest_seconds"], 65 * 60)
        self.assertIn("first_failure_utc", app.export_incidents_csv("1h"))
        self.assertIn("recovered", app.export_incidents_csv("1h"))
        self.assertIn("Incident analysis", app.report_html("1h"))

    def test_older_measurements_survive_migration(self):
        with app.connection() as db:
            db.execute("INSERT INTO measurements(checked_at,target,online,latency_ms,detail) "
                       "VALUES(?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), "Internet", 1, 31, "legacy"))
        app.initialize()
        with app.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM measurements WHERE detail='legacy'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
