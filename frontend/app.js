'use strict';

const $ = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const state = { period: '6h', filter: 'All', visibleRows: 12, data: null, busy: false, toastTimer: null };

const number = (value, digits = 1) => value == null || !Number.isFinite(Number(value))
  ? '—' : Number(value).toFixed(digits);
const dateFor = value => value ? new Date(value).toLocaleString(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit'
}) : '—';
const clockFor = value => value ? new Date(value).toLocaleTimeString(undefined, {
  hour: '2-digit', minute: '2-digit', second: '2-digit'
}) : '—';
function toast(message, isError = false) {
  const element = $('toast');
  element.textContent = message;
  element.className = 'toast' + (isError ? ' error' : '');
  element.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => element.hidden = true, 3800);
}
function updateClock() {
  $('clock').textContent = new Date().toLocaleTimeString(undefined, {hour12:false});
}
function setAgentStatus(active, error = false) {
  const pill = $('agent-pill');
  pill.className = 'agent-pill' + (error ? ' offline' : !active ? ' paused' : '');
  pill.innerHTML = '<span class="pill-dot"></span>' + (error ? ' AGENT UNREACHABLE' : active ? ' MONITORING' : ' PAUSED');
  $('rail-led').style.background = error ? '#ff9a72' : active ? '#66e7bd' : '#e4b36c';
  $('monitor-toggle').textContent = active ? 'Pause agent' : 'Resume agent';
  $('monitor-toggle').disabled = error;
}
function updateSummary(data) {
  const internet = data.stats.internet;
  const gateway = data.stats.gateway;
  const latest = internet.last;
  const backup = data.stats.secondary.last;
  const monitored = data.monitoring;
  setAgentStatus(monitored);
  $('success-rate').textContent = internet.success_pct == null ? '—' : number(internet.success_pct) + '%';
  $('average-latency').textContent = internet.avg_latency_ms == null ? '—' : number(internet.avg_latency_ms) + ' ms';
  $('failed-count').textContent = internet.total ? String(internet.failures) : '—';
  $('sample-count').textContent = internet.total ? `${internet.total.toLocaleString()} measured internet checks` : 'No internet checks yet';
  $('gateway-rate').textContent = gateway.success_pct == null ? '—' : number(gateway.success_pct) + '%';
  $('gateway-caption').textContent = !data.gateway_address ? 'No default gateway detected' : `ICMP echo / ${data.gateway_address}`;
  $('router-label').textContent = !data.gateway_address ? 'NOT DETECTED' : !gateway.last ? 'WAITING' : gateway.last.online ? 'RESPONDING' : 'NO ICMP REPLY';
  $('router-node').className = 'node-icon' + (!data.gateway_address ? ' muted' : gateway.last && !gateway.last.online ? ' alert' : '');
  const bothFailed = latest && backup && !latest.online && !backup.online;
  const partial = latest && backup && Boolean(latest.online) !== Boolean(backup.online);
  $('internet-node').className = 'node-icon' + (bothFailed ? ' alert' : partial ? ' muted' : '');
  const title = $('hero-state');
  if (!monitored) {
    title.className = 'stage-state paused';
    title.innerHTML = 'AGENT <span>PAUSED</span>';
    $('hero-desc').textContent = 'Scheduled checks are paused. You can still run a diagnostic manually.';
  } else if (!latest) {
    title.className = 'stage-state';
    title.innerHTML = 'COLLECTING <span>DATA</span>';
    $('hero-desc').textContent = 'Waiting for the first network measurements.';
  } else if (partial) {
    title.className = 'stage-state paused';
    title.innerHTML = 'PARTIAL <span>REACHABILITY</span>';
    $('hero-desc').textContent = 'Only one of the two external TCP destinations responded.';
  } else if (bothFailed) {
    title.className = 'stage-state bad';
    title.innerHTML = 'BOTH <span>CHECKS FAILED</span>';
    $('hero-desc').textContent = 'Neither monitored TCP destination responded to the latest round.';
  } else if (latest.online) {
    title.className = 'stage-state';
    title.innerHTML = backup ? 'ENDPOINTS <span>REACHABLE</span>' : 'PRIMARY <span>REACHABLE</span>';
    $('hero-desc').textContent = backup
      ? 'Both external TCP destinations responded on the latest checks.'
      : 'The latest primary TCP connection succeeded. Waiting for a second target.';
  } else {
    title.className = 'stage-state bad';
    title.innerHTML = 'PRIMARY <span>CHECK FAILED</span>';
    $('hero-desc').textContent = 'The primary endpoint did not respond. Run another check to compare destinations.';
  }
  $('last-check').textContent = dateFor(latest?.checked_at);
  $('live-ring').style.background = bothFailed ? '#ff9a72' : partial ? '#e4b36c' : monitored ? '#4bd8f7' : '#e4b36c';
  $('download').href = `/api/export?period=${encodeURIComponent(state.period)}`;
  $('report').href = `/api/report?period=${encodeURIComponent(state.period)}`;
  $('incidents-download').href = `/api/incidents/export?period=${encodeURIComponent(state.period)}`;
}
function makeSvg(name, attrs = {}, text = null) {
  const elem = document.createElementNS(svgNS, name);
  for (const [key, value] of Object.entries(attrs)) elem.setAttribute(key, String(value));
  if (text != null) elem.textContent = String(text);
  return elem;
}
function chart(data) {
  const element = $('latency-chart');
  element.replaceChildren();
  const all = data.records.filter(row => row.target === 'Internet').reverse();
  const points = all.slice(-180);
  $('chart-empty').hidden = !!points.length;
  $('chart-number').innerHTML = '— <span>ms</span>';
  $('range-start').textContent = dateFor(points[0]?.checked_at);
  $('range-end').textContent = dateFor(points[points.length - 1]?.checked_at);
  const latestGood = all.slice().reverse().find(row => row.online && row.latency_ms != null);
  if (latestGood) $('chart-number').innerHTML = `${number(latestGood.latency_ms)} <span>ms</span>`;
  if (!points.length) return;
  const left = 43, right = 748, top = 18, bottom = 234;
  const measurable = points.filter(row => row.online && row.latency_ms != null).map(row => Number(row.latency_ms));
  let max = measurable.length ? Math.max(30, ...measurable) : 100;
  max = Math.ceil(max * 1.15 / 10) * 10;
  for (let i = 0; i <= 4; i++) {
    const v = max * (4 - i) / 4;
    const y = top + (bottom - top) * i / 4;
    element.append(makeSvg('line', {x1:left,y1:y,x2:right,y2:y,stroke:'#284055','stroke-width':1,'stroke-dasharray':'3 6'}));
    element.append(makeSvg('text', {x:3,y:y+4,fill:'#7291a9','font-family':'ui-monospace,monospace','font-size':10}, number(v,0)));
  }
  const rawTimes = points.map((row) => Date.parse(row.checked_at));
  const first = rawTimes[0], last = rawTimes[rawTimes.length - 1];
  const x = (index) => Number.isFinite(first) && last > first
    ? left + (rawTimes[index] - first) / (last - first) * (right - left)
    : left + index / Math.max(1, points.length - 1) * (right - left);
  const y = (value) => bottom - Math.min(value, max) / max * (bottom - top);
  let segment = [];
  function flushSegment() {
    if (segment.length >= 2) {
      element.append(makeSvg('polyline', {points:segment.map(point => point.join(',')).join(' '),fill:'none',stroke:'#4bd8f7','stroke-width':2.8,'stroke-linecap':'round','stroke-linejoin':'round'}));
    } else if (segment.length === 1) {
      element.append(makeSvg('circle',{cx:segment[0][0],cy:segment[0][1],r:3.5,fill:'#4bd8f7'}));
    }
    segment = [];
  }
  points.forEach((row, index) => {
    const px = x(index);
    if (row.online && row.latency_ms != null) {
      segment.push([px,y(Number(row.latency_ms))]);
    } else {
      flushSegment();
      const dot = makeSvg('circle',{cx:px,cy:bottom,r:4.3,fill:'#ff9a72',stroke:'#111f2e','stroke-width':2});
      dot.append(makeSvg('title',{},`${dateFor(row.checked_at)} — Failed TCP check`));
      element.append(dot);
    }
  });
  flushSegment();
  const recent = points[points.length-1];
  if (recent.online && recent.latency_ms != null) {
    const dot = makeSvg('circle',{cx:x(points.length-1),cy:y(Number(recent.latency_ms)),r:4.5,fill:'#96ebfc',stroke:'#0d1929','stroke-width':2});
    dot.append(makeSvg('title',{},`${number(recent.latency_ms)} ms at ${dateFor(recent.checked_at)}`));
    element.append(dot);
  }
}
function renderAssessment(data) {
  const info = data.diagnosis;
  $('assessment').className = `assessment assessment-${info.level}`;
  $('assessment-title').textContent = info.title;
  $('assessment-detail').textContent = info.detail;
  $('assessment-next').textContent = info.next_step;
  const tests = [
    ['primary-status', data.stats.internet, 'PRIMARY / 1.1.1.1'],
    ['secondary-status', data.stats.secondary, 'SECONDARY / 8.8.8.8'],
  ];
  for (const [id, target, label] of tests) {
    const element = $(id);
    const last = target.last;
    element.textContent = `${label} — ${!last ? 'NO DATA' : last.online ? 'REACHABLE' : 'FAILED'}`;
    element.className = !last ? '' : last.online ? 'endpoint-ok' : 'endpoint-fail';
  }
}
function renderQuality(data) {
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
function renderEvents(data) {
  const found = [];
  for (const incident of data.incidents) {
    found.push({type:incident.ended_at ? 'good' : 'down',
      head:incident.ended_at ? 'Incident recovered' : 'Confirmed connection incident',
      desc:incident.ended_at
        ? `First failure: ${dateFor(incident.started_at)}. Both external targets were unreachable on consecutive checks, then connectivity returned.`
        : `Both TCP targets failed for ${data.settings.confirm_failures} consecutive rounds. Waiting for ${data.settings.recovery_successes} reachable rounds to close the incident.`,
      date:incident.ended_at || incident.confirmed_at});
  }
  if (!found.length && data.pending_failures > 0) {
    found.push({type:'down',head:`${data.pending_failures} failed round(s) observed`,
      desc:`Both endpoints are unreachable. ${data.settings.confirm_failures} consecutive failed rounds are required to confirm an incident.`,
      date:data.stats.internet.last?.checked_at});
  }
  $('event-count').textContent = `${data.incident_summary.confirmed} new`;
  $('incident-rule').textContent = `${data.settings.confirm_failures} failed rounds confirm an incident. ${data.settings.recovery_successes} reachable rounds close it.`;
  const list = $('event-list');
  list.replaceChildren();
  if (!found.length) {
    const empty = document.createElement('div'); empty.className = 'event-empty';
    empty.textContent = 'No confirmed incidents in this period. Monitoring continues.';
    list.append(empty); return;
  }
  for (const event of found.slice(0,5)) {
    const article = document.createElement('article'); article.className = `event-entry ${event.type}`;
    const rail = document.createElement('div'); rail.className = 'event-track';
    const dot=document.createElement('span');dot.className='event-point';rail.append(dot);
    const body=document.createElement('div');body.className='event-body';
    const title=document.createElement('strong');title.textContent=event.head;
    const desc=document.createElement('p');desc.textContent=event.desc;
    const when=document.createElement('time');when.textContent=dateFor(event.date);
    body.append(title,desc,when);article.append(rail,body);list.append(article);
  }
}
function duration(seconds) {
  if (seconds == null) return '—';
  const value = Math.max(0, Number(seconds));
  if (value < 60) return `${value} sec`;
  if (value < 3600) return `${Math.floor(value / 60)}m ${value % 60}s`;
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
}
function renderHistory(data) {
  const stats = data.incident_summary;
  $('history-confirmed').textContent = stats.confirmed;
  $('history-recovered').textContent = stats.recovered;
  $('history-longest').textContent = stats.longest_seconds ? duration(stats.longest_seconds) : '—';
  $('history-observed').textContent = stats.observed_seconds ? duration(stats.observed_seconds) : '—';
  const body = $('incident-rows'); body.replaceChildren();
  if (!data.incidents.length) {
    const row = document.createElement('tr'), cell = document.createElement('td');
    cell.colSpan = 4; cell.className = 'placeholder-cell';
    cell.textContent = 'No confirmed incidents in this time range.';
    row.append(cell); body.append(row); return;
  }
  for (const incident of data.incidents.slice(0, 10)) {
    const row = document.createElement('tr');
    [dateFor(incident.started_at), dateFor(incident.confirmed_at),
      incident.ongoing ? 'Ongoing' : `Recovered ${dateFor(incident.ended_at)}`,
      `${duration(incident.duration_seconds)}${incident.ongoing ? ' · running' : ''}`].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    });
    body.append(row);
  }
}
function renderEvidence(data) {
  const filtered = data.records.filter(row => state.filter === 'All' || row.target === state.filter);
  const rows = $('evidence-rows'); rows.replaceChildren();
  $('ledger-meta').textContent = `${filtered.length} visible results · 900 record display limit · ${state.period.toUpperCase()} window`;
  if (!filtered.length) {
    const row=document.createElement('tr'), cell=document.createElement('td');
    cell.colSpan=5;cell.className='placeholder-cell';cell.textContent='No measurements for this filter and time period.';
    row.append(cell);rows.append(row);
    $('ledger-showing').textContent='No records to display';
    $('rows-toggle').hidden=true;
    return;
  }
  $('ledger-showing').textContent = `Showing ${Math.min(filtered.length,state.visibleRows)} of ${filtered.length} available rows` ;
  const toggle=$('rows-toggle');
  toggle.hidden=filtered.length<=12;
  toggle.textContent=state.visibleRows>12?'Show fewer records':'Show more records';
  for (const record of filtered.slice(0,state.visibleRows)) {
    const row=document.createElement('tr');
    const values=[dateFor(record.checked_at),record.target,record.online?'Connected':'Failed',record.latency_ms==null?'—':`${number(record.latency_ms)} ms`,record.detail];
    values.forEach((value,index)=>{
      const cell=document.createElement('td');
      if(index===1)cell.className='target';
      if(index===2){const badge=document.createElement('span');badge.className='result'+(record.online?'':' bad');badge.textContent=value;cell.append(badge);}
      else cell.textContent=value;
      row.append(cell);
    });
    rows.append(row);
  }
}
function render(data) {
  state.data=data;
  updateSummary(data);
  renderAssessment(data);
  renderQuality(data);
  chart(data);
  renderEvents(data);
  renderHistory(data);
  renderEvidence(data);
}
async function refresh(silent=true) {
  try {
    const response=await fetch(`/api/data?period=${state.period}`,{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  }catch(err){setAgentStatus(false,true);if(!silent)toast('Cannot connect to local agent. Is app.py still running?',true);}
}
async function post(url,body) {
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  if(!response.ok){const err=await response.json().catch(()=>({}));throw new Error(err.error||`Request failed (${response.status})`);}
  return response.json();
}
const settingsDialog = $('settings-dialog');
const settingsFields = {
  interval_seconds: $('setting-interval'),
  confirm_failures: $('setting-failures'),
  recovery_successes: $('setting-recovery'),
  slow_connect_ms: $('setting-slow'),
};
$('open-settings').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/settings', {cache:'no-store'});
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const config = await response.json();
    Object.entries(settingsFields).forEach(([key,element]) => element.value = String(config[key]));
    settingsDialog.showModal();
  } catch (error) {toast(`Settings unavailable: ${error.message}`,true);}
});
$('close-settings').addEventListener('click', () => settingsDialog.close());
$('cancel-settings').addEventListener('click', () => settingsDialog.close());
$('settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('save-settings'); button.disabled = true;
  const settings = Object.fromEntries(Object.entries(settingsFields).map(([key,field]) => [key,Number(field.value)]));
  try {
    await post('/api/settings',settings);
    settingsDialog.close();
    await refresh();
    toast('Monitoring settings saved.');
  } catch (error) {toast(`Could not save: ${error.message}`,true);}
  finally {button.disabled = false;}
});
$('manual-check').addEventListener('click', async () => {
  if(state.busy)return;state.busy=true;
  const button=$('manual-check');button.disabled=true;button.querySelector('span').textContent='Checking network…';
  try {const result=await post('/api/probe');await refresh();toast(`${result.checks.length} fresh network check(s) saved.`);}
  catch(error){toast(`Diagnostic failed: ${error.message}`,true);}
  finally {state.busy=false;button.disabled=false;button.querySelector('span').textContent='Run diagnostic';}
});
$('monitor-toggle').addEventListener('click', async () => {
  if(!state.data)return;
  const action=state.data.monitoring?'pause':'resume';
  try {await post('/api/monitor',{action});await refresh();toast(action==='pause'?'Automatic checks paused.':'Automatic checks resumed.');}
  catch(error){toast(`Could not ${action} agent: ${error.message}`,true);}
});
for(const button of document.querySelectorAll('[data-period]')){
  button.addEventListener('click',()=>{
    state.period=button.dataset.period;
    document.querySelectorAll('[data-period]').forEach(item=>item.classList.toggle('selected',item===button));
    refresh(false);
  });
}
for(const button of document.querySelectorAll('[data-filter]')){
  button.addEventListener('click',()=>{
    state.filter=button.dataset.filter;
    state.visibleRows=12;
    document.querySelectorAll('[data-filter]').forEach(item=>item.classList.toggle('selected',item===button));
    if(state.data)renderEvidence(state.data);
  });
}
$('rows-toggle').addEventListener('click',()=>{
  state.visibleRows=state.visibleRows===12?40:12;
  if(state.data)renderEvidence(state.data);
});
for(const link of document.querySelectorAll('[data-nav]')){
  link.addEventListener('click',()=>{
    document.querySelectorAll('[data-nav]').forEach(item=>item.classList.toggle('active',item===link));
  });
}
updateClock();setInterval(updateClock,1000);refresh(false);setInterval(()=>refresh(),6000);

// Manual performance tests are separate from the agent's regular checks.
let performanceRunning = false;
async function refreshPerformance() {
  try {
    const response = await fetch('/api/performance', {cache:'no-store'});
    if (!response.ok) throw new Error('Performance history unavailable');
    const data = await response.json();
    const test = data.recent[0];
    const running = Boolean(data.running || test?.status === 'running');
    performanceRunning = running;
    $('start-performance').disabled = running;
    $('start-performance').textContent = running ? 'Test in progress…' : 'Run performance test';
    const progress = $('performance-progress');
    progress.className = 'performance-progress' + (running ? ' running' : test?.status !== 'complete' && test ? ' warning' : '');
    progress.textContent = running ? `${test?.phase || 'Preparing test'} · Please keep this page open.`
      : !test ? 'No performance tests yet. Run one when you want a measurement.'
      : test.status === 'complete' ? 'Test completed. Measurements saved locally.'
      : test.status === 'partial' ? 'Partial test — review the notes below.'
      : 'The test could not finish. Review the notes below.';
    const fmt = (field, unit = '') => test?.[field] == null ? '—' : `${number(test[field], field === 'packet_loss_pct' ? 0 : 1)}${unit}`;
    $('perf-download').textContent = fmt('download_mbps');
    $('perf-upload').textContent = fmt('upload_mbps');
    $('perf-ping').textContent = fmt('latency_ms');
    $('perf-jitter').textContent = fmt('jitter_ms');
    $('perf-loss').textContent = fmt('packet_loss_pct');
    $('perf-last-label').textContent = test ? `${dateFor(test.started_at)} · ${test.target_label} (${test.target})` : 'No recent test';
    $('perf-note').textContent = test?.notes || 'Manual tests only. The native Mac download check may transfer more data than the original quick test. ICMP is not actual game-server ping.';
    const tbody = $('performance-rows');tbody.replaceChildren();
    if (!data.recent.length) {
      const row = document.createElement('tr'), cell = document.createElement('td');
      cell.colSpan = 7;cell.className='placeholder-cell';cell.textContent='No manual tests recorded.';row.append(cell);tbody.append(row);
    }
    for (const entry of data.recent) {
      const row=document.createElement('tr');
      const readable = value => value == null ? '—' : number(value,1);
      [dateFor(entry.started_at),entry.target_label,readable(entry.download_mbps),readable(entry.upload_mbps),readable(entry.latency_ms),readable(entry.packet_loss_pct),entry.status].forEach(value => {
        const cell=document.createElement('td');cell.textContent=value;row.append(cell);
      });
      tbody.append(row);
    }
  } catch (error) {
    $('performance-progress').textContent = `Could not read performance data: ${error.message}`;
    $('performance-progress').className = 'performance-progress warning';
  }
}
$('start-performance').addEventListener('click', async () => {
  if (performanceRunning) return;
  $('start-performance').disabled = true;
  $('performance-progress').textContent = 'Starting manual test…';
  try {
    await post('/api/performance/start', {target:$('ping-target').value});
    toast('Manual performance test started.');
    await refreshPerformance();
  } catch (error) {
    toast(`Test failed to start: ${error.message}`, true);
    await refreshPerformance();
  }
});
refreshPerformance();
setInterval(refreshPerformance, 2500);


// The packaged desktop app keeps its local agent running independently of browser tabs.
// Show Quit only when served by that packaged app, not by python3 app.py or GitHub Pages.
const quitAppButton = $('quit-app');
async function discoverDesktopControls() {
  try {
    const response = await fetch('/api/desktop/status', {cache:'no-store'});
    if (response.ok && (await response.json()).desktop === true) {
      quitAppButton.hidden = false;
    }
  } catch (_) { /* The browser/demo version has no desktop-only controls. */ }
}
quitAppButton.addEventListener('click', async () => {
  if (!window.confirm('Quit SignalProof? Continuous monitoring will stop until you reopen the app.')) return;
  try {
    await post('/api/desktop/quit');
    quitAppButton.disabled = true;
    toast('SignalProof stopped. You can close this tab.');
  } catch (error) {
    toast(`Could not quit SignalProof: ${error.message}`, true);
  }
});
discoverDesktopControls();


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

