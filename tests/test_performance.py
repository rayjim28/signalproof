import csv
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import app
import performance
from performance import PerformanceRunner, create_table, parse_ping


class PerformanceTests(unittest.TestCase):
    def test_ping_output_parses_latency_jitter_and_loss(self):
        output = """64 bytes from 1.1.1.1: icmp_seq=0 ttl=58 time=10.1 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=14.1 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=58 time=12.1 ms
--- 1.1.1.1 ping statistics ---
10 packets transmitted, 3 packets received, 70.0% packet loss"""
        result = parse_ping(output)
        self.assertEqual(result['latency_ms'], 12.1)
        self.assertEqual(result['jitter_ms'], 3.0)
        self.assertEqual(result['packet_loss_pct'], 70)
        self.assertEqual(result['packets_received'], 3)

    def test_mac_ping_keeps_path_and_locale(self):
        from subprocess import CompletedProcess
        output = ("64 bytes from 9.9.9.9: icmp_seq=0 ttl=58 time=14.2 ms\n"
                  "--- 9.9.9.9 ping statistics ---\n"
                  "10 packets transmitted, 1 packets received, 90.0% packet loss")
        with patch('performance.shutil.which', return_value='/sbin/ping'), \
             patch('platform.system', return_value='Darwin'), \
             patch('performance.subprocess.run', return_value=CompletedProcess([], 1, output, '')) as run:
            result = performance.check_ping('9.9.9.9')
        self.assertEqual(result['packet_loss_pct'], 90)
        self.assertEqual(run.call_args.args[0][0], '/sbin/ping')
        self.assertIn('PATH', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_download_falls_back_on_http_403_and_caps_bytes(self):
        class Response:
            status = 200
            headers = {}
            def __init__(self):
                self.left = 16
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, n):
                amount = min(n, self.left)
                self.left -= amount
                return b'x' * amount
        calls = []
        def fake_open(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 403, 'Forbidden', {}, None)
            return Response()
        with patch('performance.platform.system', return_value='Linux'), \
        with patch('performance.DOWNLOAD_BYTES', 16), \
             patch('performance.urlopen', side_effect=fake_open):
            mbps, size, provider = performance.check_download()
        self.assertEqual(size, 16)
        self.assertTrue(mbps > 0)
        self.assertEqual(provider, 'Hetzner (fallback)')
        self.assertEqual(len(calls), 2)
        self.assertNotIn('&t=', calls[0])


    def test_native_mac_download_parses_mbps_without_json_unit_guessing(self):
        from subprocess import CompletedProcess
        with patch('performance.os.path.isfile', return_value=True), \
             patch('performance.subprocess.run', side_effect=[
                 CompletedProcess([], 0, '  -M max runtime\n', ''),
                 CompletedProcess([], 0, '==== SUMMARY ====\nDownlink capacity: 425.77 Mbps\n', '')
             ]) as run:
            mbps, count, source = performance.mac_download_test()
        self.assertEqual(mbps, 425.77)
        self.assertIsNone(count)
        self.assertEqual(source, 'Apple networkQuality')
        self.assertIn('-u', run.call_args.args[0])
        self.assertIn('-M', run.call_args.args[0])

    def test_mac_download_first_then_http_fallback(self):
        with patch('performance.platform.system', return_value='Darwin'), \
             patch('performance.mac_download_test', return_value=(88.2, None, 'Apple networkQuality')):
            self.assertEqual(performance.check_download(), (88.2, None, 'Apple networkQuality'))
        with patch('performance.platform.system', return_value='Darwin'), \
             patch('performance.mac_download_test', side_effect=RuntimeError('unavailable')), \
             patch('performance._download_from', return_value=(55, 1024, 'Cloudflare')) as do_http:
            result = performance.check_download()
        self.assertEqual(result[0], 55)
        self.assertEqual(do_http.call_count, 1)

    def test_native_download_reports_error_instead_of_fabricating_speed(self):
        from subprocess import CompletedProcess
        with patch('performance.os.path.isfile', return_value=True), \
             patch('performance.subprocess.run', side_effect=[
                 CompletedProcess([], 0, '', ''),
                 CompletedProcess([], 1, '', 'network unavailable')
             ]):
            with self.assertRaises(RuntimeError):
                performance.mac_download_test()

    def test_ping_without_replies_is_not_a_fake_latency(self):
        result = parse_ping("10 packets transmitted, 0 received, 100.0% packet loss")
        self.assertIsNone(result['latency_ms'])
        self.assertIsNone(result['jitter_ms'])
        self.assertEqual(result['packet_loss_pct'], 100)

    def test_manual_job_saves_results_and_blocks_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_db = app.DB
            app.DB = Path(tmp) / 'test.db'
            try:
                app.initialize()
                runner = PerformanceRunner(app.connection)
                def slow_ping(host):
                    time.sleep(.12)
                    return {'latency_ms': 20, 'jitter_ms': 2, 'packet_loss_pct': 0,
                            'packets_sent': 10, 'packets_received': 10}
                with patch('performance.check_ping', side_effect=slow_ping), \
                     patch('performance.check_download', return_value=(75.3, 12582912)), \
                     patch('performance.check_upload', return_value=(12.5, 3145728)):
                    job_id = runner.start('cloudflare')
                    self.assertIsInstance(job_id, int)
                    self.assertIsNone(runner.start('cloudflare'))
                    deadline = time.monotonic() + 4
                    while runner.status()['running'] and time.monotonic() < deadline:
                        time.sleep(.02)
                item = runner.history()[0]
                self.assertEqual(item['status'], 'complete')
                self.assertEqual(item['download_mbps'], 75.3)
                self.assertEqual(item['jitter_ms'], 2)
                self.assertEqual(len(list(csv.reader(io.StringIO(runner.csv())))), 2)
                self.assertRaises(ValueError, runner.start, 'localhost')
            finally:
                app.DB = old_db

    def test_partial_results_when_upload_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_db = app.DB
            app.DB = Path(tmp) / 'test.db'
            try:
                app.initialize()
                runner = PerformanceRunner(app.connection)
                with patch('performance.check_ping', return_value={'latency_ms': None, 'jitter_ms': None,
                            'packet_loss_pct': 100, 'packets_sent': 10, 'packets_received': 0}), \
                     patch('performance.check_download', return_value=(50, 12582912)), \
                     patch('performance.check_upload', side_effect=RuntimeError('blocked')):
                    runner.start('google')
                    deadline = time.monotonic() + 4
                    while runner.status()['running'] and time.monotonic() < deadline:
                        time.sleep(.02)
                item = runner.history()[0]
                self.assertEqual(item['status'], 'partial')
                self.assertEqual(item['packet_loss_pct'], 100)
                self.assertIsNone(item['upload_mbps'])
                self.assertIn('blocked', item['notes'])
            finally:
                app.DB = old_db


if __name__ == '__main__':
    unittest.main()
