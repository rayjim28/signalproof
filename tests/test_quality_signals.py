"""Tests for retrospective connection-quality summaries (no external network)."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quality_signals import summarize_quality


class QualitySignalsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE measurements (
            id INTEGER PRIMARY KEY, checked_at TEXT, target TEXT,
            online INTEGER, latency_ms REAL)""")
        self.settings = {"slow_connect_ms": 200}

    def tearDown(self):
        self.db.close()

    def insert(self, samples, target="Internet", date="2026-10-28T12:00:00+00:00"):
        for value in samples:
            self.db.execute("INSERT INTO measurements(checked_at,target,online,latency_ms) VALUES(?,?,?,?)",
                            (date, target, 0 if value is None else 1, value))

    def snapshot(self):
        return summarize_quality(self.db, "2026-10-27T00:00:00+00:00", self.settings)

    def test_empty_and_small_samples_do_not_claim_spikes(self):
        empty = self.snapshot()
        self.assertIsNone(empty["p95_ms"])
        self.assertIsNone(empty["baseline_median_ms"])
        self.insert([20, 300, None, 21])
        result = self.snapshot()
        self.assertEqual(result["slow_checks"], 1)
        self.assertEqual(result["failed_checks"], 1)
        self.assertEqual(result["spike_count"], 0)

    def test_real_spike_with_baseline(self):
        self.insert([20, 22, 23, 25, 28, 350])
        result = self.snapshot()
        self.assertEqual(result["spike_count"], 1)
        self.assertEqual(result["slow_checks"], 1)
        self.assertEqual(result["spike_threshold_ms"], 200)
        self.assertEqual(result["p95_ms"], 350)
        self.assertEqual(result["recent_spikes"][0]["latency_ms"], 350)

    def test_high_baseline_adjusts_spike_threshold(self):
        self.insert([220, 225, 230, 235, 240, 470])
        result = self.snapshot()
        self.assertEqual(result["spike_threshold_ms"], 465)
        self.assertEqual(result["spike_count"], 1)
        self.assertEqual(result["slow_checks"], 6)

    def test_filters_endpoint_and_time_and_caps_events(self):
        self.insert([600] * 6, target="Secondary")
        self.insert([800] * 6, date="2026-10-20T12:00:00+00:00")
        self.insert([20] * 10 + [300, 301, 302, 303, 304, 305])
        result = self.snapshot()
        self.assertEqual(result["total_checks"], 16)
        self.assertEqual(result["spike_count"], 6)
        self.assertEqual(len(result["recent_spikes"]), 5)
        self.assertEqual(result["recent_spikes"][0]["latency_ms"], 305)

    def test_local_api_includes_quality_without_migration(self):
        import tempfile
        import app
        from datetime import datetime, timezone
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app, "DB", Path(temp) / "measurements.db"):
                app.initialize()
                with app.connection() as db:
                    db.execute("INSERT INTO measurements(checked_at,target,online,latency_ms,detail) "
                               "VALUES(?,?,?,?,?)",
                               (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "Internet", 1, 25.0, "sample"))
                payload = app.get_data("1h")
                self.assertEqual(payload["quality"]["total_checks"], 1)
                self.assertEqual(payload["quality"]["p95_ms"], 25)
                self.assertEqual(payload["stats"]["internet"]["total"], 1)

    def test_failures_are_not_latency_spikes(self):
        self.insert([None, None, 21, 23, 24, 25, 26])
        result = self.snapshot()
        self.assertEqual(result["failed_checks"], 2)
        self.assertEqual(result["spike_count"], 0)
        self.assertEqual(result["successful_timed_checks"], 5)


if __name__ == "__main__":
    unittest.main()
