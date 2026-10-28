import csv
import io
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from evidence_reports import bounds, summarize, public_summary, export_csv, export_pdf


class EvidenceReportsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE measurements(id INTEGER PRIMARY KEY,checked_at TEXT,target TEXT,online INTEGER,latency_ms REAL,detail TEXT);
            CREATE TABLE incidents(id INTEGER PRIMARY KEY,started_at TEXT,confirmed_at TEXT,ended_at TEXT);
        ''')
        self.now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        self.begin=self.now-timedelta(days=7)
        self.stamps=[self.begin+timedelta(minutes=i) for i in range(7)]
        for i,stamp in enumerate(self.stamps):
            self.db.execute('INSERT INTO measurements(checked_at,target,online,latency_ms,detail) VALUES(?,?,?,?,?)',
                            (stamp.isoformat(),'Internet',i!=2,12+i if i!=2 else None,'TCP connect'))
        a=self.begin+timedelta(hours=1)
        b=a+timedelta(minutes=5)
        c=b+timedelta(minutes=3)
        self.db.execute('INSERT INTO incidents(started_at,confirmed_at,ended_at) VALUES(?,?,?)',(a.isoformat(),b.isoformat(),c.isoformat()))
        self.db.commit()

    def tearDown(self): self.db.close()

    def test_periods_and_dates(self):
        for period in ('24h','7d','30d'):
            b,e,label=bounds({'period':[period]},self.now)
            self.assertLess(b,e)
        b,e,label=bounds({'start':['2026-10-26'],'end':['2026-10-27']},self.now)
        self.assertEqual((e-b).days,2)
        with self.assertRaises(ValueError):bounds({'start':['2026-10-01'],'end':['2026-10-28']},datetime(2026,10,1,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):bounds({'period':['javascript']},self.now)
        with self.assertRaises(ValueError):bounds({'start':['2026-01-01'],'end':['2026-10-27']},self.now)
        with self.assertRaises(ValueError):bounds({'start':['2026-10-27']},self.now)

    def test_summary_counts_and_incident_overlap(self):
        r=summarize(self.db,self.begin,self.now,'7 day test',15)
        self.assertEqual(r['primary_checks'],7)
        self.assertEqual(r['failed_primary_checks'],1)
        self.assertEqual(r['confirmed_incidents'],1)
        self.assertEqual(r['observed_span_seconds'],8*60)
        self.assertEqual(r['success_rate_pct'],85.7)
        self.assertEqual(r['slow_checks'],4)
        self.assertEqual(r['spike_count'],0)
        self.assertEqual(r['incidents'][0]['status'],'Recovered')
        self.assertNotIn('measurements',public_summary(r))

    def test_incident_clip_and_ongoing(self):
        a=self.begin-timedelta(hours=1)
        b=self.begin-timedelta(minutes=45)
        self.db.execute('INSERT INTO incidents(started_at,confirmed_at,ended_at) VALUES(?,?,NULL)',(a.isoformat(),b.isoformat()))
        self.db.commit()
        r=summarize(self.db,self.begin,self.now,'week')
        self.assertEqual(r['confirmed_incidents'],1)
        self.assertEqual(r['ongoing_incidents'],1)
        self.assertEqual(r['observed_span_seconds'],7*24*3600+8*60)

    def test_csv_and_pdf(self):
        r=summarize(self.db,self.begin,self.now,'week')
        csv_result=export_csv(r)
        rows=list(csv.reader(io.StringIO(csv_result)))
        self.assertIn('record_type',rows[0])
        self.assertEqual(sum(row[0]=='measurement' for row in rows[1:]),7)
        self.assertEqual(sum(row[0]=='incident' for row in rows[1:]),1)
        pdf=export_pdf(r)
        self.assertTrue(pdf.startswith(b'%PDF-1.4'))
        self.assertIn(b'startxref',pdf[-150:])
        self.assertGreater(len(pdf),1000)
        try:
            import fitz
        except ImportError:
            return
        doc=fitz.open(stream=pdf,filetype='pdf')
        self.assertGreaterEqual(doc.page_count,1)
        self.assertIn('NETWORK EVIDENCE REPORT',doc[0].get_text())
        doc.close()

if __name__=='__main__':unittest.main()
