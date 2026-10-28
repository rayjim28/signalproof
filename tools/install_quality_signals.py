"""Safely install the Connection Quality panel without replacing existing files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply_one(source, old, new, label):
    if new in source:
        return source
    if old not in source:
        raise RuntimeError(f"Cannot find expected {label}; no project files were changed. Check your local version.")
    if source.count(old) != 1:
        raise RuntimeError(f"Expected one {label}, found {source.count(old)}; no files changed.")
    return source.replace(old, new, 1)


specs = {
    "app.py": [
        ("from performance import PerformanceRunner, create_table",
         "from performance import PerformanceRunner, create_table\nfrom quality_signals import summarize_quality", "Python import"),
        ('        history = incident_history(db, since)',
         '        history = incident_history(db, since)\n        quality = summarize_quality(db, since, settings)', "quality query"),
        ('        "records": records,',
         '        "records": records,\n        "quality": quality,', "API response"),
    ],
    "app.js": [
        ('function renderEvents(data) {', '''function renderQuality(data) {
  const quality = data.quality;
  if (!quality) return;
  $('quality-p95').textContent = quality.p95_ms == null ? '—' : `${number(quality.p95_ms)} ms`;
  $('quality-slow').textContent = String(quality.slow_checks);
  $('quality-spikes').textContent = quality.spike_threshold_ms == null ? '—' : String(quality.spike_count);
  $('quality-slow-caption').textContent = `Successful TCP checks ≥ ${quality.slow_threshold_ms} ms`;
  $('quality-spike-caption').textContent = quality.spike_threshold_ms == null
    ? 'Needs at least 5 timed checks for a baseline'
    : `At least ${number(quality.spike_threshold_ms)} ms · 2× median or slow threshold`;
  const list = $('quality-spike-list'); list.replaceChildren();
  if (!quality.recent_spikes.length) {
    const message = document.createElement('p');
    message.className = 'quality-empty';
    message.textContent = quality.spike_threshold_ms == null
      ? 'Collecting a baseline. Run diagnostics or leave the agent monitoring.'
      : 'No unusual TCP connection spikes detected in this period.';
    list.append(message);
  } else {
    for (const spike of quality.recent_spikes) {
      const item = document.createElement('div'); item.className = 'quality-spike';
      const when = document.createElement('time'); when.textContent = dateFor(spike.checked_at);
      const value = document.createElement('strong'); value.textContent = `${number(spike.latency_ms)} ms`;
      item.append(when,value); list.append(item);
    }
  }
}
function renderEvents(data) {''', 'quality renderer'),
        ('  renderAssessment(data);\n  chart(data);',
         '  renderAssessment(data);\n  renderQuality(data);\n  chart(data);', 'quality render call'),
    ],
    "index.html": [
        ('      <div class="analysis-layout">', '''      <section class="surface quality" id="quality" aria-label="Automatic connection quality evidence">
        <div class="section-top"><div><div class="section-kicker">AUTOMATIC / QUALITY EVIDENCE</div><h2>Connection quality</h2><p>Based on saved primary TCP checks, not download speed or game-server ping. Uses the selected time range.</p></div></div>
        <div class="quality-metrics">
          <div class="quality-metric"><span>95TH-PERCENTILE TCP CONNECT</span><strong id="quality-p95">—</strong><small>Higher-end connection setup time in this window</small></div>
          <div class="quality-metric"><span>SLOW CHECKS</span><strong id="quality-slow">—</strong><small id="quality-slow-caption">Using your slow-check setting</small></div>
          <div class="quality-metric"><span>LATENCY SPIKES</span><strong id="quality-spikes">—</strong><small id="quality-spike-caption">Needs a baseline of successful checks</small></div>
        </div>
        <div class="quality-trail"><div><div class="section-kicker">RECENT SPIKES</div><p>High TCP connect times are clues, not proof your ISP caused a problem.</p></div><div id="quality-spike-list" class="quality-spike-list"><p class="quality-empty">Collecting measurements…</p></div></div>
      </section>

      <div class="analysis-layout">''', 'quality dashboard section'),
    ],
    "styles.css": [
        ('/* Incident history and local settings */', '''/* Automatic quality evidence: measured TCP connect latency, not bandwidth or ICMP loss. */
.quality{margin-top:16px;padding:25px 27px;background:linear-gradient(145deg,#0e1d2e,#101e2e)}
.quality-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:20px 0}
.quality-metric{padding:18px;background:#0b1a2a;border:1px solid #2b4256;border-radius:8px;min-width:0}
.quality-metric span{display:block;color:#88a8bf;font:9px var(--mono);letter-spacing:.6px}
.quality-metric strong{display:block;color:#8ae4f3;font:600 27px var(--mono);margin:12px 0}
.quality-metric small{display:block;font-size:10px;line-height:1.6;color:#8fa7b8}
.quality-trail{display:grid;grid-template-columns:minmax(180px,.75fr) minmax(220px,1.5fr);gap:14px;border-top:1px solid #284154;padding-top:16px}
.quality-trail p{color:#90a9bd;font-size:11px;line-height:1.6}
.quality-spike-list{display:flex;flex-direction:column;gap:6px}
.quality-spike{display:flex;justify-content:space-between;gap:12px;padding:10px 12px;border:1px solid #324357;border-radius:5px;background:#112438;font:11px var(--mono)}
.quality-spike time{color:#a7bdd1}.quality-spike strong{color:#f6be8a}
.quality-empty{margin:0;padding:10px 0;color:#8fa7b8}
@media(max-width:750px){.quality{padding:20px 16px}.quality-metrics{grid-template-columns:1fr}.quality-trail{grid-template-columns:1fr}}

/* Incident history and local settings */''', 'quality styles'),
    ],
}


def main():
    if not (ROOT / "quality_signals.py").is_file():
        raise RuntimeError("Missing quality_signals.py. Extract the ZIP first.")
    changed = {}
    for filename, actions in specs.items():
        path = ROOT / filename
        original = path.read_text(encoding="utf-8")
        updated = original
        for old, new, label in actions:
            updated = apply_one(updated, old, new, label)
        changed[path] = updated
    for path, content in changed.items():
        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            print("Updated:", path.relative_to(ROOT))
    print("Connection Quality panel is installed. Run the tests before rebuilding.")


if __name__ == "__main__":
    main()
