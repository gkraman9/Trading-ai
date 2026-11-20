'use strict';
// Separate same-origin read-only channel; no execution controls or remote scripts.
async function refreshShadow(){
 const el=id=>document.getElementById(id),text=(id,value)=>{el(id).textContent=value??'Unavailable';};
 try{
  const response=await fetch('/live/shadow/v1/snapshot',{cache:'no-store'});if(!response.ok)throw new Error('unavailable');
  const r=await response.json();if(r.signal!=='WAIT'||r.execution_allowed!==false||r.orders_requested!==0)throw new Error('unsafe contract');
  text('shadow-status',`${r.label} · ${r.status}`);const facts=el('shadow-facts');facts.replaceChildren();
  const d=r.research||{},s=r.session||{},q=r.quote||{},o=d.observations?.context||{};
  for(const [name,value] of [['Source kind',r.source_kind],['Feed',r.feed_status],['Bid',q.bid],['Ask',q.ask],['Observed spread',q.spread],['Quote age (seconds)',r.quote_age_seconds],['M1 structure',o.m1_structure],['M5 structure',o.m5_structure],['Alignment',d.descriptive_direction],['Regime',d.market_regime?.directional],['Session eligibility',String(s.operational_eligible??false)],['Research candidate',r.research_candidate??d.candidate],['Operational signal','WAIT · execution disabled'],['Research candle cutoff',d.analysis_at],['Decision available at',d.available_at],['Last successful observation',r.last_successful_observation]]){
   const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value??'Unavailable';facts.append(dt,dd);
  }
  text('shadow-position',JSON.stringify(r.open_position??null,null,2));text('shadow-exits',JSON.stringify(r.closed_trades??[],null,2));
  text('shadow-metrics',JSON.stringify({performance:r.performance,completeness:r.data_completeness,qualified_performance_metrics:null},null,2));
  text('shadow-reasons',JSON.stringify({session:r.session,research:d.reason_codes,warnings:r.data_quality_warnings,rejections:r.performance?.rejections,reasons:r.reason_codes},null,2));
 }catch(error){text('shadow-status','Shadow data unavailable. WAIT; execution disabled.');for(const id of ['shadow-facts','shadow-position','shadow-exits','shadow-metrics','shadow-reasons'])el(id).textContent='Unavailable; stale simulation values withheld.';}
}
refreshShadow();setInterval(refreshShadow,2000);
