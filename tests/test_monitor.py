"""Checks for the local data and incident logic."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.folder.name) / 'measurements.db'
        app.initialize()

    def tearDown(self):
        app.DB = self.old_db
        self.folder.cleanup()

    def check_round(self, primary, secondary):
        def outcome(host, port):
            good = primary if host == '1.1.1.1' else secondary
            return good, 18.0 if good else None, 'test'
        with patch.object(app, 'gateway_address', return_value=None), \
             patch.object(app, 'internet_probe', side_effect=outcome):
            app.run_probes()

    def test_creates_schema_and_uses_two_targets(self):
        self.check_round(True, True)
        names = [row['target'] for row in app.get_data()['records']]
        self.assertEqual(set(names), {'Internet', 'Secondary'})

    def test_partial_failure_does_not_create_an_incident(self):
        self.check_round(False, True)
        self.check_round(False, True)
        self.assertEqual(app.get_data()['incidents'], [])
        self.assertEqual(app.get_data()['diagnosis']['level'], 'warning')

    def test_incident_needs_two_failures_and_two_recoveries(self):
        self.check_round(False, False)
        self.assertEqual(len(app.get_data()['incidents']), 0)
        self.check_round(False, False)
        incident = app.get_data()['incidents'][0]
        self.assertIsNone(incident['ended_at'])
        self.check_round(True, False)
        self.assertIsNone(app.get_data()['incidents'][0]['ended_at'])
        self.check_round(True, True)
        self.assertIsNotNone(app.get_data()['incidents'][0]['ended_at'])

    def test_can_open_again_after_recovery(self):
        for primary, secondary in [(False,False),(False,False),(True,True),(True,True),
                                   (False,False),(False,False)]:
            self.check_round(primary, secondary)
        incidents = app.get_data()['incidents']
        self.assertEqual(len(incidents), 2)
        self.assertIsNone(incidents[0]['ended_at'])

    def test_printable_report_and_csv(self):
        self.check_round(True, True)
        self.assertIn('Connection evidence report', app.report_html())
        self.assertIn('1.1.1.1:443', app.report_html())
        self.assertIn('Secondary', app.export_csv())

    def test_previous_database_history_is_kept(self):
        with app.connection() as db:
            db.execute("INSERT INTO measurements(checked_at,target,online,latency_ms,detail) "
                       "VALUES('2026-10-26T13:00:00+00:00','Internet',1,24.0,'old record')")
        app.initialize()
        with app.connection() as db:
            count = db.execute("SELECT COUNT(*) FROM measurements WHERE detail='old record'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
