'use strict';

// This page uses sample data only. Nothing here probes the visitor's device or network.
(() => {
  const now = Date.now();
  const minute = 60000;
  const hour = 60 * minute;
  let monitoring = true;
  const settings = { interval_seconds:20, confirm_failures:2, recovery_successes:2, slow_connect_ms:200 };
  const targets = [
    {name:'Internet', detail:'TCP / 1.1.1.1:443'},
    {name:'Secondary', detail:'TCP / 8.8.8.8:443'},
    {name:'Gateway', detail:'ICMP echo / sample gateway'}
  ];
  const measurements = [];
  let nextId = 1;
  const iso = ms => new Date(ms).toISOString();
  // Fixed sample incidents, with timestamp offsets relative to when the demo opens.
  const incidentSpecs = [
    {first:now - 31 * minute, seconds:88},
    {first:now - 195 * minute, seconds:142},
    {first:now - 2.4 * 24 * hour, seconds:236},
  ];
  const incidents = incidentSpecs.map((v,i) => ({
    id:i+1, started_at:iso(v.first),confirmed_at:iso(v.first+40*1000),
    ended_at:iso(v.first+v.seconds*1000),duration_seconds:v.seconds,
    window_seconds:v.seconds,ongoing:false
  }));
  function addRound(timestamp, index, bothDown=false) {
    targets.forEach((target,j) => {
      const localDrop = (index%73===0 && j===2);
      const down = bothDown && j<2 || localDrop;
      const base = j===0 ? 23 : j===1 ? 32 : 2.4;
      const jitter = (Math.sin(index*.83+j*1.97)+1)*6 + (index%11===0?9:0);
      measurements.push({
        id:nextId++, checked_at:iso(timestamp), target:target.name,
        online:down ? 0 : 1, latency_ms:down ? null : Math.round((base + jitter)*10)/10,
        detail:target.detail + (down?' · no response':'')
      });
    });
  }
  // Dense recent samples plus sparser older history; all are generated locally in JavaScript.
  for(let i=0;i<530;i++){
    const ageMinutes = i<80 ? i*3 : i<170 ? 240+(i-80)*30 : 2940+(i-170)*24;
    const t=now-ageMinutes*minute-10000;
    if(t<now-7*24*hour)break;
    const down = incidentSpecs.some(spec => t>=spec.first && t<spec.first+spec.seconds*1000);
    addRound(t,i,down);
  }
  // Insert explicit consecutive failures so the incident example is visible in chart and ledger.
  for (const spec of incidentSpecs) {
    addRound(spec.first,601,true);
    addRound(spec.first+20000,602,true);
    addRound(spec.first+spec.seconds*1000,603,false);
  }
  const exampleTests = [
    {at:now-36*minute,down:318.6,up:39.2,ping:19.3,jitter:3.7,loss:0,target:'1.1.1.1',target_label:'Cloudflare'},
    {at:now-198*minute,down:284.7,up:41.1,ping:23.1,jitter:6.4,loss:0,target:'8.8.8.8',target_label:'Google DNS'},
    {at:now-2*24*hour,down:197.2,up:35.9,ping:38.5,jitter:14.2,loss:10,target:'9.9.9.9',target_label:'Quad9'}
  ];
  const tests = exampleTests.map((v,i) => ({id:i+1, started_at:iso(v.at),
    status:'complete',phase:'complete',download_mbps:v.down,upload_mbps:v.up,
    latency_ms:v.ping,jitter_ms:v.jitter,packet_loss_pct:v.loss,
    target:v.target,target_label:v.target_label,
    notes:'Example values only. No real download, upload, or ping request was made.' }));
  const labelFor = name => ({cloudflare:['1.1.1.1','Cloudflare'],google:['8.8.8.8','Google DNS'],quad9:['9.9.9.9','Quad9']})[name]||['1.1.1.1','Cloudflare'];
  const boundary = period => now - ({'1h':hour,'6h':6*hour,'24h':24*hour,'7d':7*24*hour}[period]||6*hour);
  function summary(rows,name){
    const mine=rows.filter(x=>x.target===name);
    const successes=mine.filter(x=>x.online);
    return {total:mine.length,success_pct:mine.length?Math.round(successes.length/mine.length*1000)/10:null,
      avg_latency_ms:successes.length?Math.round(successes.reduce((s,r)=>s+r.latency_ms,0)/successes.length*10)/10:null,
      failures:mine.length-successes.length,last:mine[0]||null};
  }
  function getData(period){
    const rows=measurements.filter(x=>Date.parse(x.checked_at)>=boundary(period)).sort((a,b)=>Date.parse(b.checked_at)-Date.parse(a.checked_at)).slice(0,900);
    const full=measurements.filter(x=>Date.parse(x.checked_at)>=boundary(period));
    const activeIncidents=incidents.filter(x=>Date.parse(x.ended_at)>=boundary(period));
    const confirmed=activeIncidents.filter(x=>Date.parse(x.confirmed_at)>=boundary(period));
    const primary=summary(full,'Internet');
    const secondary=summary(full,'Secondary');
    const gateway=summary(full,'Gateway');
    return {
      records:rows,stats:{internet:{...primary,last:rows.find(x=>x.target==='Internet')||null},secondary:{...secondary,last:rows.find(x=>x.target==='Secondary')||null},gateway:{...gateway,last:rows.find(x=>x.target==='Gateway')||null}},
      diagnosis:{level:'good',title:'Sample endpoints reachable',detail:'The latest synthetic TCP checks were successful. This example demonstrates how the local agent presents its findings.',next_step:'Install the local Python agent to monitor your own connection and record real incidents.'},
      incidents:activeIncidents,incident_summary:{confirmed:confirmed.length,recovered:confirmed.length,ongoing:0,
        longest_seconds:Math.max(0,...activeIncidents.map(x=>x.duration_seconds)),
        observed_seconds:activeIncidents.reduce((sum,x)=>sum+x.window_seconds,0)},
      pending_failures:0,settings:{...settings},monitoring,gateway_address:'192.0.2.1',platform:'Demo',period,
      limit_notice:'Synthetic sample data. No real measurements from this visitor.'
    };
  }
  function getPerf(){return {running:false,recent:tests.slice().sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)).slice(0,10)};}
  function response(data,status=200){return Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));}
  const actualFetch=window.fetch.bind(window);
  window.fetch=(input,options={})=>{
    const inputUrl=typeof input==='string'?input:input.url;
    const url=new URL(inputUrl, window.location.href.startsWith("http") ? window.location.href : "https://signalproof.example/");
    if(!url.pathname.startsWith('/api/'))return actualFetch(input,options);
    const method=(options.method||'GET').toUpperCase();
    const period=url.searchParams.get('period')||'6h';
    if(method==='GET'){
      if(url.pathname==='/api/data')return response(getData(period));
      if(url.pathname==='/api/settings')return response({...settings});
      if(url.pathname==='/api/performance')return response(getPerf());
    }
    if(method==='POST'){
      let body={};try{body=JSON.parse(options.body||'{}');}catch {return response({error:'Invalid input'},400);}
      if(url.pathname==='/api/probe'){
        const t=Date.now();addRound(t,214,false);
        return response({checks:measurements.filter(x=>x.checked_at===iso(t))});
      }
      if(url.pathname==='/api/monitor'){
        monitoring=body.action==='resume';return response({monitoring});
      }
      if(url.pathname==='/api/settings'){
        for(const key of Object.keys(settings)){if(Number.isInteger(body[key]))settings[key]=body[key];}
        return response({settings:{...settings}});
      }
      if(url.pathname==='/api/performance/start'){
        const [target,target_label]=labelFor(body.target);
        const count=tests.length;
        tests.unshift({id:count+1,started_at:iso(Date.now()),status:'complete',phase:'complete',
          target,target_label,download_mbps:302.4,upload_mbps:40.2,latency_ms:21.4,
          jitter_ms:4.1,packet_loss_pct:0,notes:'SAMPLE RESULT ONLY — no speed test was run and no network measurements were taken.'});
        return response({id:count+1,status:'complete'},202);
      }
    }
    return response({error:'Not available in the public demo.'},404);
  };

  function csvCell(value){const s=String(value??'');return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
  function csv(columns,rows){return [columns, ...rows].map(row=>row.map(csvCell).join(',')).join('\r\n')+'\r\n';}
  function download(name,content,mime='text/csv'){
    const blob=new Blob([content],{type:mime+';charset=utf-8'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download=name;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const links=[
      ['download',()=>{const rows=getData(document.querySelector('[data-period].selected')?.dataset.period||'6h').records;
        download('signalproof-sample-measurements.csv',csv(['timestamp_utc','target','connected','latency_ms','method'],rows.map(r=>[r.checked_at,r.target,r.online,r.latency_ms,r.detail])));}],
      ['incidents-download',()=>download('signalproof-sample-incidents.csv',csv(['first_failure_utc','confirmed_utc','recovered_utc','status','observed_span_seconds'],incidents.map(i=>[i.started_at,i.confirmed_at,i.ended_at,'resolved',i.duration_seconds])))],
      ['report',()=>{
        const win=window.open('about:blank','_blank');
        if (win) win.opener=null;
        if(!win)return;
        const data=getData('6h');
        const esc=s=>String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const html=`<!doctype html><html><head><meta charset="utf-8"><title>SignalProof sample report</title><style>body{font:16px system-ui;margin:3rem auto;max-width:760px;line-height:1.6;color:#213448}h1{color:#0d5f76}table{border-collapse:collapse;width:100%}td,th{padding:.7rem;border-bottom:1px solid #ddd;text-align:left}small{color:#667}</style></head><body><h1>SignalProof · Sample evidence report</h1><p><strong>DEMO DATA ONLY.</strong> These records are synthetic and must not be used as evidence of real outages.</p><p>Primary success rate: ${esc(data.stats.internet.success_pct)}% · Average TCP connect: ${esc(data.stats.internet.avg_latency_ms)} ms</p><h2>Illustrative incidents</h2><table><thead><tr><th>Started</th><th>Recovered</th><th>Span</th></tr></thead><tbody>${data.incidents.map(i=>`<tr><td>${esc(new Date(i.started_at).toLocaleString())}</td><td>${esc(new Date(i.ended_at).toLocaleString())}</td><td>${esc(i.duration_seconds)} seconds</td></tr>`).join('')}</tbody></table><p><small>This report demonstrates formatting only; the local Python edition generates reports from actual checks.</small></p><button onclick="window.print()">Print / Save PDF</button></body></html>`;
        win.document.write(html);win.document.close();
      }],
      ['performance-export',()=>download('signalproof-sample-performance.csv',csv(['timestamp_utc','endpoint','download_mbps','upload_mbps','latency_ms','jitter_ms','packet_loss_pct'],tests.map(t=>[t.started_at,t.target_label,t.download_mbps,t.upload_mbps,t.latency_ms,t.jitter_ms,t.packet_loss_pct])))]
    ];
    const performanceLink=document.querySelector('a[href="/api/performance/export"]');
    if(performanceLink)performanceLink.id='performance-export';
    for(const [id,handle] of links){const element=document.getElementById(id);if(element)element.addEventListener('click',ev=>{ev.preventDefault();handle();});}
  });
})();
