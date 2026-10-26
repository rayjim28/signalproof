import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'checks.db'
        app.initialize()
    def tearDown(self):
        app.DB = self.old_db
        self.temp.cleanup()
    def test_empty_stats(self):
        data = app.get_data()
        self.assertIsNone(data['stats']['internet']['success_pct'])
        self.assertEqual(data['records'], [])
    def test_probe_records_separate_targets(self):
        with patch.object(app,'gateway_address',return_value='192.0.2.1'),\
             patch.object(app,'gateway_probe',return_value=(False,None,'ICMP blocked')),\
             patch.object(app,'internet_probe',return_value=(True,17.2,'TCP')):
            results=app.run_probes()
        self.assertCountEqual(
            [item['target'] for item in results],
            ['Gateway', 'Internet', 'Secondary']
        )
        stats=app.get_data()['stats']
        self.assertEqual(stats['internet']['success_pct'],100)
        self.assertEqual(stats['gateway']['success_pct'],0)
    def test_no_gateway_still_checks_internet(self):
        with patch.object(app,'gateway_address',return_value=None),\
             patch.object(app,'internet_probe',return_value=(False,None,'TCP')):
            app.run_probes()
        self.assertEqual(app.get_data()['stats']['internet']['failures'],1)
        self.assertEqual(app.get_data()['stats']['gateway']['total'],0)

if __name__=='__main__': unittest.main()
