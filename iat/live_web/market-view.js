/* Dedicated read-only presentation; no acquisition, execution or strategy endpoint. */
(() => {
  'use strict';
  const byId=id=>document.getElementById(id);
  const make=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const text=v=>v===null||v===undefined?'Unavailable':String(v);
  const number=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-US',{maximumFractionDigits:6,useGrouping:false}):'Unavailable';
  let interval=10000;
  function render(value){
    byId('mv-status').textContent=value.status;
    // Availability only: never call the offline SR/entry engine from live UI.
    byId('entry-research-state').textContent='BLOCKED';
    const entryReasons=byId('entry-research-reasons');entryReasons.replaceChildren();
    for(const reason of [...new Set(['ENTRY_SYNTHETIC_ONLY','ENTRY_LIVE_PROVENANCE_NOT_AUTHORIZED',...(value.reason_codes||[])])])entryReasons.append(make('li',reason));
    const q=value.quote||{},r=value.runtime||{},checks=r.demo_checks||{},cutoffs=value.cutoffs||{};
    const dl=byId('mv-runtime');dl.replaceChildren();
    for(const [label,v] of [
      ['Bid',number(q.bid)],['Ask',number(q.ask)],['Spread (broker points)',number(q.spread_points)],
      ['Broker point',number(q.broker_point)],['Quote age (current seconds)',number(q.age_seconds)],
      ['Quote provider timestamp',text(q.observed_at_utc)],['M1 closed through',text(cutoffs.M1)],['M5 closed through',text(cutoffs.M5)],
      ['Connected at last poll',text(checks.connected)],['DEMO verified at last poll',text(checks.demo_verified)],
      ['Terminal trading disabled',text(checks.terminal_trading_disabled)],['Python API trading disabled',text(checks.python_api_trading_disabled)],
      ['Processing latency (ms)',number(r.processing_ms)],['Closed-analysis cache',r.cache_hit?'Reused exact closed source':'Recomputed / unavailable'],
      ['Analytical computations / cache hits',`${text(r.analysis_computations)} / ${text(r.cache_hits)}`],
      ['Source fingerprint',text(r.closed_source_fingerprint)],['Observation snapshot',text(value.source_snapshot_id)],
      ['Operational signal',value.signal],['Execution allowed',text(value.execution_allowed)]]){
      dl.append(make('dt',label),make('dd',v));
    }
    const formal=byId('mv-formal');formal.replaceChildren();
    formal.append(make('p',`Typed formal context: ${text(value.formal_context?.status)}. V3 adapter: ${text(value.adapter?.status)}.`));
    const session=value.session||{},phase=session.permissions?.phase||session.phase||'UNKNOWN';
    formal.append(make('p',`Session: ${phase}; calendar: ${text(session.verification)}. Exness ${value.exness}; ${value.qualification}.`));
    formal.append(make('p','The current V3 adaptive contract does not authorize live provenance. Unavailable V3 fields are not reconstructed from descriptive observations.'));
    const reasons=byId('mv-reasons');reasons.replaceChildren();
    const codes=[...new Set(['READ_ONLY_SHADOW',...(value.reason_codes||[])])];
    for(const code of codes)reasons.append(make('li',code.replaceAll('_',' ')));
    byId('mv-strategy').textContent=`Support/resistance rejection: ${text(value.strategy?.validation_status)} · live ${text(value.strategy?.live_status)}. No strategy is run by this panel.`;
    const descriptive=byId('mv-descriptive');descriptive.replaceChildren();
    const frames=value.descriptive?.frames||{};
    if(!Object.keys(frames).length)descriptive.append(make('p','Current descriptive observations are unavailable. Previous evidence is withheld.'));
    for(const [tf,f] of Object.entries(frames)){
      const box=make('div','');box.className='structure-frame';box.append(make('h3',`${tf}: ${text(f.structure?.classification)}`));
      box.append(make('p',`Momentum: ${text(f.momentum?.regime)}; volatility: ${text(f.volatility?.regime)}.`));
      for(const [label,rows] of [['Confirmed swings / HH HL LH LL',f.swings],['BOS / CHoCH (report-scoped references)',f.events],['Candlestick patterns',f.patterns],['Support / resistance',f.support_resistance],['Supply / demand',f.supply_demand],['Liquidity pools',f.liquidity_pools],['Liquidity events',f.liquidity_events]]){
        const details=document.createElement('details');details.append(make('summary',`${label}: ${(rows||[]).length}`));details.append(make('pre',JSON.stringify(rows||[],null,2)));box.append(details);
      }
      descriptive.append(box);
    }
    if(value.descriptive){
      descriptive.append(make('p',`Directional agreement: ${text(value.descriptive.alignment?.classification)}. Original confluence remains descriptive where formal gates are unavailable.`));
      const detail=document.createElement('details');detail.append(make('summary','Original confluence and evidence references'));detail.append(make('pre',JSON.stringify({confluence:value.descriptive.confluence,evidence_ids:value.descriptive.evidence_ids},null,2)));descriptive.append(detail);
    }
    byId('mv-report').textContent=value.adapter?.report?JSON.stringify(value.adapter.report,null,2):'Unavailable';
  }
  function unavailable(){render({status:'UNAVAILABLE',formal_context:{status:'UNAVAILABLE'},adapter:{status:'UNAVAILABLE'},reason_codes:['DASHBOARD_REQUEST_UNAVAILABLE'],strategy:{validation_status:'SYNTHETIC_ONLY',live_status:'NOT_RUN'},signal:'WAIT',execution_allowed:false,exness:'BLOCKED',qualification:'DATA_NOT_QUALIFIED'});}
  async function refresh(){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
    try{const response=await fetch('/live/intelligence/v3/snapshot',{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('Unavailable');render(await response.json());}
    catch(error){unavailable();}
    finally{clearTimeout(timer);setTimeout(refresh,interval);}
  }
  fetch('/live/v1/settings',{cache:'no-store'}).then(r=>r.json()).then(s=>{if(Number.isInteger(s.refresh_seconds)&&s.refresh_seconds>=2&&s.refresh_seconds<=60)interval=s.refresh_seconds*1000;}).catch(()=>{}).finally(refresh);
})();
