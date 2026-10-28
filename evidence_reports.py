"""Phase 9 local evidence summaries, CSV, and dependency-free PDF exports.

All times UTC. Incident spans are bounded by recorded probe observations;
they do not prove full continuous downtime or an ISP-side cause.
"""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from math import ceil

PERIOD_DAYS = {'24h': 1, '7d': 7, '30d': 30}
MAX_DAYS = 90


def bounds(query, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    start_text = (query.get('start') or [''])[0]
    end_text = (query.get('end') or [''])[0]
    if start_text or end_text:
        if not start_text or not end_text:
            raise ValueError('Select both start and end dates (UTC).')
        try:
            start_date = date.fromisoformat(start_text)
            end_date = date.fromisoformat(end_text)
        except ValueError as exc:
            raise ValueError('Use YYYY-MM-DD for report dates.') from exc
        begin = datetime.combine(start_date, time.min, timezone.utc)
        until = min(now, datetime.combine(end_date + timedelta(days=1), time.min, timezone.utc))
        if begin >= until or until - begin > timedelta(days=MAX_DAYS, seconds=1):
            raise ValueError('Choose a past date range of at most 90 days.')
        period_label = f'{start_date.isoformat()} to {end_date.isoformat()} UTC'
    else:
        period = (query.get('period') or ['7d'])[0]
        if period not in PERIOD_DAYS:
            raise ValueError('Choose 24h, 7d, 30d, or custom dates.')
        begin = now - timedelta(days=PERIOD_DAYS[period])
        until = now
        period_label = {'24h': 'Past 24 hours', '7d': 'Past 7 days', '30d': 'Past 30 days'}[period]
    return begin, until, period_label


def _utc_parse(value):
    stamp=datetime.fromisoformat(value)
    return (stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc))


def summarize(db, begin, until, label, slow_threshold=200):
    start, end = begin.isoformat(), until.isoformat()
    primary = [dict(row) for row in db.execute(
        "SELECT checked_at,online,latency_ms,detail FROM measurements "
        "WHERE target='Internet' AND checked_at>=? AND checked_at<? ORDER BY checked_at ASC", (start,end))]
    measures = [dict(row) for row in db.execute(
        "SELECT checked_at,target,online,latency_ms,detail FROM measurements "
        "WHERE checked_at>=? AND checked_at<? ORDER BY checked_at ASC,id ASC", (start,end))]
    incidents = [dict(row) for row in db.execute(
        "SELECT started_at,confirmed_at,ended_at FROM incidents "
        "WHERE started_at<? AND (ended_at IS NULL OR ended_at>=?) "
        "ORDER BY started_at DESC,id DESC",(end,start))]
    events=[]
    for row in incidents:
        try:
            started=datetime.fromisoformat(row['started_at'])
            stopped=datetime.fromisoformat(row['ended_at']) if row['ended_at'] else until
            if started.tzinfo is None: started=started.replace(tzinfo=timezone.utc)
            if stopped.tzinfo is None: stopped=stopped.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError):
            continue
        overlap=max(0,round((min(stopped,until)-max(started,begin)).total_seconds()))
        if not overlap: continue
        events.append({**row,'observed_seconds':overlap,'status':'Ongoing' if not row['ended_at'] else 'Recovered'})
    timed=sorted(float(row['latency_ms']) for row in primary if row['online'] and row['latency_ms'] is not None)
    baseline=median(timed) if len(timed)>=5 else None
    spike_threshold=max(slow_threshold, 2*baseline) if baseline is not None else None
    return {
        'period':label, 'start_utc':start,'end_utc':end,
        'primary_checks':len(primary),
        'failed_primary_checks':sum(not row['online'] for row in primary),
        'success_rate_pct':round(100*sum(bool(row['online']) for row in primary)/len(primary),1) if primary else None,
        'confirmed_incidents':sum(begin <= _utc_parse(row['confirmed_at']) < until for row in events),
        'incidents_in_window':len(events),
        'ongoing_incidents':sum(row['status']=='Ongoing' for row in events),
        'observed_span_seconds':sum(row['observed_seconds'] for row in events),
        'slow_checks':sum(value >= slow_threshold for value in timed),
        'p95_ms':round(timed[max(0, ceil(len(timed)*.95)-1)],1) if timed else None,
        'spike_count':sum(value >= spike_threshold for value in timed) if spike_threshold is not None else None,
        'slow_threshold_ms':slow_threshold,
        'incidents':events,
        'measurements':measures,
        'generated_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'caution':'Observed incident spans are based on periodic checks. These are not proof of continuous downtime or ISP responsibility.',
    }


def public_summary(report):
    return {key:value for key,value in report.items() if key != 'measurements'}


def export_csv(report):
    output=io.StringIO(newline='')
    writer=csv.writer(output)
    writer.writerow(['record_type','timestamp_utc','target_or_metric','result','latency_or_duration','detail_or_recovery_utc'])
    for name in ('period','primary_checks','failed_primary_checks','success_rate_pct','confirmed_incidents','incidents_in_window','observed_span_seconds','slow_checks','spike_count','p95_ms'):
        writer.writerow(['summary',report['generated_utc'],name,report[name],'',''])
    for row in report['incidents']:
        writer.writerow(['incident',row['started_at'],'both TCP endpoints',row['status'],row['observed_seconds'],row['ended_at'] or 'Ongoing'])
    for row in report['measurements']:
        writer.writerow(['measurement',row['checked_at'],row['target'],'connected' if row['online'] else 'failed',row['latency_ms'] if row['latency_ms'] is not None else '',row['detail']])
    return output.getvalue()


def _pdf_date(value):
    if not value:
        return 'Not yet recorded'
    try:
        return _utc_parse(value).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError):
        return str(value)[:30]


def _pdf_escape(text):
    """Embed readable WinAnsi text while escaping PDF text operators."""
    value=str(text).replace('\u2014','-').replace('\u2013','-').replace('\u2022','-')
    value=value.encode('cp1252','replace').decode('latin1')
    return value.replace('\\','\\\\').replace('(','\\(').replace(')','\\)').replace('\r',' ').replace('\n',' ')


def export_pdf(report):
    """Generate a multipage text PDF using only Python's standard library."""
    pages=[]; lines=[]
    def add(text='',size=10, weight='regular'):
        nonlocal lines
        if len(lines)>=49:
            pages.append(lines);lines=[]
        lines.append((text,size,weight))
    add('SIGNALPROOF  /  NETWORK EVIDENCE REPORT',16,'bold')
    add(report['period'],12,'bold')
    add(f"UTC: {report['start_utc']} to {report['end_utc']}")
    add(f"Generated: {report['generated_utc']}")
    add('')
    add('RELIABILITY OVERVIEW',12,'bold')
    add(f"Primary TCP checks: {report['primary_checks']}    Failed: {report['failed_primary_checks']}")
    rate=report['success_rate_pct']
    add(f"Primary check success rate: {rate}%" if rate is not None else 'Primary check success rate: No observations')
    add(f"Incidents confirmed in period: {report['confirmed_incidents']}   Overlapping: {report['incidents_in_window']}")
    add(f"Ongoing incidents: {report['ongoing_incidents']}")
    add(f"Total observed incident span: {report['observed_span_seconds']} seconds")
    add(f"Slow TCP checks: {report['slow_checks']}    Latency spikes: {report['spike_count'] if report['spike_count'] is not None else 'Baseline unavailable'}")
    add(f"95th percentile TCP connect: {report['p95_ms']} ms" if report['p95_ms'] is not None else '95th percentile TCP connect: No observations')
    add('')
    add('INCIDENT TIMELINE (UTC)',12,'bold')
    if not report['incidents']:
        add('No confirmed incidents overlap this reporting period.')
    for row in report['incidents'][:100]:
        if len(lines) > 45:
            pages.append(lines)
            lines=[]
        add('Start: '+_pdf_date(row['started_at']),10,'bold')
        add('Confirmed: '+_pdf_date(row['confirmed_at'])+'  |  '+row['status'])
        add('Recovery: '+_pdf_date(row['ended_at'])+'  |  Observed: '+str(row['observed_seconds'])+' s')
        add('')
    if len(report['incidents'])>100:
        add(f"Only the most recent 100 of {len(report['incidents'])} incidents are listed; the CSV includes all.")
    add('')
    add('INTERPRETATION',12,'bold')
    add('Checks target TCP services on 1.1.1.1:443 and 8.8.8.8:443.')
    add('The report reflects locally recorded checks, not direct ISP instrumentation.')
    add('Observations between probes are unknown. Latency is not game ping.')
    add('A failure may arise from Wi-Fi, routing, endpoints, or the ISP.')
    pages.append(lines)
    objects=[]
    def obj(body):
        objects.append(body);return len(objects)
    catalog=obj(b'')
    pages_ref=obj(b'')
    font_regular=obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    font_bold=obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
    child_refs=[]
    for idx, items in enumerate(pages):
        cmds=['0.08 0.16 0.23 rg','0.08 0.16 0.23 RG']
        y=750
        for item,size,weight in items:
            font='F2' if weight=='bold' else 'F1'
            cmds.append(f'BT /{font} {size} Tf 48 {y} Td ({_pdf_escape(item)}) Tj ET')
            y-=19 if size>=12 else 14
        cmds += ['0.4 0.5 0.6 rg',f'BT /F1 8 Tf 48 28 Td (SignalProof - Local observations | Page {idx+1} of {len(pages)}) Tj ET']
        stream='\n'.join(cmds).encode('latin1')
        c=obj(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
        p=obj(f'<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> /Contents {c} 0 R >>'.encode())
        child_refs.append(p)
    objects[catalog-1]=f'<< /Type /Catalog /Pages {pages_ref} 0 R >>'.encode()
    objects[pages_ref-1]=(f'<< /Type /Pages /Count {len(child_refs)} /Kids ['+' '.join(f'{r} 0 R' for r in child_refs)+'] >>').encode()
    output=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets=[0]
    for index,body in enumerate(objects,1):
        offsets.append(len(output));output.extend(f'{index} 0 obj\n'.encode()+body+b'\nendobj\n')
    table_start=len(output)
    output.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(objects)+1} /Root {catalog} 0 R >>\nstartxref\n{table_start}\n%%EOF\n'.encode())
    return bytes(output)
