"""Add Phase 9 reports to the current SignalProof app without replacing its files."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

HTML = '''      <section class="surface report-center" id="report-center" aria-label="Outage evidence reports">
        <div class="section-top"><div><div class="section-kicker">05 / EVIDENCE REPORTS</div><h2>Outage evidence &amp; reports</h2><p>Generate a timestamped report from saved checks. All reporting dates are UTC.</p></div></div>
        <div class="report-controls">
          <label>Reporting range<select id="report-range"><option value="24h">Last 24 hours</option><option value="7d" selected>Last 7 days</option><option value="30d">Last 30 days</option><option value="custom">Custom dates</option></select></label>
          <label class="report-custom" hidden>Start date (UTC)<input type="date" id="report-start" /></label>
          <label class="report-custom" hidden>End date (UTC)<input type="date" id="report-end" /></label>
          <button id="report-refresh" class="button-report" type="button">Update summary</button>
        </div>
        <div class="report-cards" aria-live="polite">
          <div><small>CONFIRMED INCIDENTS</small><strong id="report-incidents">—</strong></div>
          <div><small>OBSERVED INCIDENT SPAN</small><strong id="report-duration">—</strong></div>
          <div><small>PRIMARY SUCCESS RATE</small><strong id="report-success">—</strong></div>
          <div><small>LATENCY SPIKES</small><strong id="report-spikes">—</strong></div>
        </div>
        <div id="report-message" class="report-message" role="status">Preparing local report…</div>
        <div class="report-buttons"><a id="report-pdf" class="button-primary" href="/api/reports/pdf?period=7d" download>Download PDF report</a><a id="report-csv" class="button-report" href="/api/reports/csv?period=7d" download>Download CSV evidence</a></div>
        <p class="history-note">Reports show recorded checks and confirmed incident windows, not continuously observed downtime or proof of ISP responsibility. Monitoring stays local.</p>
      </section>

'''
JS = r'''
// Phase 9: local report selection is independent of the telemetry chart window.
const reportRange = $('report-range');
const reportStart = $('report-start');
const reportEnd = $('report-end');
function reportQuery() {
  if (reportRange.value !== 'custom') return `period=${encodeURIComponent(reportRange.value)}`;
  if (!reportStart.value || !reportEnd.value) throw new Error('Choose both UTC dates.');
  if (reportStart.value > reportEnd.value) throw new Error('Start date must be before end date.');
  return `start=${encodeURIComponent(reportStart.value)}&end=${encodeURIComponent(reportEnd.value)}`;
}
async function refreshEvidenceReport() {
  const message = $('report-message');
  try {
    const query = reportQuery();
    const response = await fetch(`/api/reports/summary?${query}`, {cache:'no-store'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Report request failed');
    $('report-incidents').textContent = String(result.confirmed_incidents);
    $('report-duration').textContent = formatDuration(result.observed_span_seconds);
    $('report-success').textContent = result.success_rate_pct == null ? '—' : `${number(result.success_rate_pct)}%`;
    $('report-spikes').textContent = result.spike_count == null ? '—' : String(result.spike_count);
    $('report-pdf').href = `/api/reports/pdf?${query}`;
    $('report-csv').href = `/api/reports/csv?${query}`;
    $('report-pdf').removeAttribute('aria-disabled');
    $('report-csv').removeAttribute('aria-disabled');
    message.textContent = `${result.period} · ${result.primary_checks} primary checks · ${result.incidents_in_window} incidents overlap the range`;
  } catch (error) {
    message.textContent = `Report: ${error.message}`;
    $('report-pdf').removeAttribute('href');
    $('report-csv').removeAttribute('href');
    $('report-pdf').setAttribute('aria-disabled', 'true');
    $('report-csv').setAttribute('aria-disabled', 'true');
  }
}
function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total >= 3600) return `${(total / 3600).toFixed(1)} h`;
  if (total >= 60) return `${Math.round(total / 60)} min`;
  return `${total} sec`;
}
reportRange.addEventListener('change', () => {
  for (const el of document.querySelectorAll('.report-custom')) el.hidden = reportRange.value !== 'custom';
  if (reportRange.value !== 'custom') refreshEvidenceReport();
});
$('report-refresh').addEventListener('click', refreshEvidenceReport);
refreshEvidenceReport();
'''
CSS = '''
/* Phase 9: structured evidence reporting (existing layout unchanged). */
.report-center{padding:27px;margin:16px 0;background:linear-gradient(135deg,#0d1e30,#102339)}
.report-controls{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin:20px 0}
.report-controls label{display:grid;gap:7px;color:#91afc6;font:10px var(--mono)}
.report-controls select,.report-controls input{background:#102a40;color:#d7edfc;border:1px solid #36526a;border-radius:6px;padding:11px 12px;min-height:40px;color-scheme:dark}
.report-controls button{min-height:40px;cursor:pointer}
.report-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}
.report-cards>div{border:1px solid #31495f;background:#0b1a2b;border-radius:8px;padding:18px;min-width:0}
.report-cards small{display:block;font:9px var(--mono);color:#8facbe;letter-spacing:.6px;line-height:1.6}
.report-cards strong{display:block;color:#8ce7fa;font:600 26px var(--mono);margin-top:12px;overflow-wrap:anywhere}
.report-message{color:#93b0c5;font-size:11px;line-height:1.5;margin:12px 0}
.report-buttons{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:17px 0}
.report-buttons a{display:inline-flex;align-items:center;justify-content:center;padding:11px 17px;text-decoration:none;border-radius:6px;font-size:11px;font-weight:700}
.report-buttons a[aria-disabled=true]{opacity:.4;pointer-events:none}
@media(max-width:850px){.report-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.report-center{padding:20px 16px}.report-controls label{width:100%}.report-controls select,.report-controls input{width:100%}}
'''

def swap(text, anchor, replacement, label):
    if replacement in text: return text
    if text.count(anchor)!=1: raise RuntimeError(f'Cannot identify {label} uniquely. No source files changed.')
    return text.replace(anchor,replacement,1)

def main():
    for need in ('evidence_reports.py','app.py','app.js','index.html','styles.css','quality_signals.py'):
        if not (ROOT/need).exists(): raise RuntimeError(f'Missing {need}; install Phase 8 first.')
    app=(ROOT/'app.py').read_text()
    app=swap(app,'from quality_signals import summarize_quality', 'from quality_signals import summarize_quality\nfrom evidence_reports import bounds as report_bounds, summarize as summarize_report, public_summary, export_csv as report_csv, export_pdf as report_pdf', 'report imports')
    handler='''        if url.path.startswith("/api/reports/"):
            try:
                query = parse_qs(url.query)
                begin, until, label = report_bounds(query)
                with connection() as db:
                    settings_row = db.execute("SELECT slow_connect_ms FROM monitor_settings WHERE id=1").fetchone()
                    slow = settings_row["slow_connect_ms"] if settings_row else 200
                    result = summarize_report(db, begin, until, label, slow)
                if url.path == "/api/reports/summary":
                    return self.output(public_summary(result))
                if url.path == "/api/reports/csv":
                    return self.output(report_csv(result), content_type="text/csv; charset=utf-8",
                                       headers={"Content-Disposition": 'attachment; filename="signalproof-outage-evidence.csv"'})
                if url.path == "/api/reports/pdf":
                    return self.output(report_pdf(result), content_type="application/pdf",
                                       headers={"Content-Disposition": 'attachment; filename="signalproof-outage-evidence.pdf"'})
                return self.output({"error": "Not found"}, status=404)
            except ValueError as error:
                return self.output({"error": str(error)}, status=400)
'''
    app=swap(app,'        if url.path == "/api/performance":',handler+'        if url.path == "/api/performance":','report API routes')
    index=(ROOT/'index.html').read_text()
    index=swap(index,'      <section class="surface evidence" id="evidence">',HTML+'      <section class="surface evidence" id="evidence">','report panel')
    js=(ROOT/'app.js').read_text()
    if '// Phase 9: local report selection' not in js: js+='\n'+JS+'\n'
    css=(ROOT/'styles.css').read_text()
    if '/* Phase 9: structured evidence reporting' not in css: css+='\n'+CSS+'\n'
    updates={'app.py':app,'index.html':index,'app.js':js,'styles.css':css}
    for name,content in updates.items():
        path=ROOT/name
        if content != path.read_text():
            path.write_text(content)
            print('Updated',name)
    print('Phase 9 reports installed. Run tests, then rebuild the Mac application.')

if __name__ == '__main__':
    main()
