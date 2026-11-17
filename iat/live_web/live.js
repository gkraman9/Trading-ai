'use strict';
let interval=10000;
const put=(id,value)=>{document.getElementById(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2);};
const panels=['source','confluence','m1','m5','alignment','zones','liquidity','momentum','scenarios','conditions','reasoning','limitations'];
function unavailable(message){put('price','—');put('quote-time','No validated quote');put('assessment','DATA_UNAVAILABLE');put('feed',message);put('model','UNAVAILABLE');for(const id of panels)put(id,'Unavailable');document.getElementById('chart').replaceChildren();}
function render(r){
 put('assessment',r.research_assessment);put('feed',r.feed_status+' · '+(r.analysis_scope||'No eligible snapshot'));put('model',r.ai_model.status);
 put('price',r.quote?String(r.quote.bid):'—');put('quote-time',r.quote?r.quote.observed_at_utc+' · Bid':'No validated quote');put('updated',r.acquired_at_utc||'—');
 put('source',{source:r.source,clock_basis:r.timestamp_basis,broker_wall_clock:r.broker_server_wall_clock,acquired_at_local:r.acquired_at_local,cutoffs:r.cutoffs,quote_age_seconds:r.quote?.age_seconds,candle_age_seconds:r.candle_age_seconds,acquisition_seconds:r.acquisition_seconds,forming:r.forming_candles});
 const obs=r.observations||{},frames=obs.frames||{},ctx=obs.context||{};
 for(const tf of ['M1','M5'])put(tf.toLowerCase(),frames[tf]?{direction:frames[tf].structure,confirmed_swings:frames[tf].confirmed_pivots,events:frames[tf].events,patterns:ctx[tf]?.patterns,missing_evidence:frames[tf].missing_evidence}:'Unavailable');
 put('alignment',obs.alignment||'Unavailable');put('confluence',obs.confluence||'Unavailable');
 put('zones',Object.fromEntries(Object.entries(ctx).map(([tf,f])=>[tf,{support_resistance:f.support_resistance,supply_demand:f.supply_demand}])));
 put('liquidity',Object.fromEntries(Object.entries(ctx).map(([tf,f])=>[tf,{pools:f.liquidity_pools,sweeps:f.liquidity_events}])));
 put('momentum',Object.fromEntries(Object.entries(ctx).map(([tf,f])=>[tf,{momentum:f.momentum,volatility:f.volatility}])));
 const hs=r.scenario.ranked_hypotheses;put('scenarios',hs.length?hs:'WAIT: no session-eligible scenario assessment. Descriptive observations cannot authorize a directional hypothesis.');
 put('conditions',hs.length?hs.map(h=>({scenario:h.hypothesis_type,confirmation_assumptions:h.assumptions,invalidation:h.invalidation_conditions})):r.scenario.abstention_reasons);
 put('reasoning',{explanation:r.reasoning,reason_codes:r.reason_codes,eligible_evidence:r.scenario.evidence_index,descriptive_evidence:obs.evidence,transition:r.transition?.classification});put('limitations',r.limitations.concat(r.scenario.limitations));
 const candles=Object.values(obs.source_registry||{}).filter(x=>x.kind==='CANDLE'&&x.timeframe==='M1').sort((a,b)=>a.available_at.localeCompare(b.available_at)).slice(-80);
 const chart=document.getElementById('chart');chart.replaceChildren();
 if(candles.length>1){const prices=candles.map(c=>c.ohlc.close),lo=Math.min(...prices),hi=Math.max(...prices),span=hi-lo;
 const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',prices.map((p,i)=>`${10+i*780/(prices.length-1)},${span===0?80:150-(p-lo)*140/span}`).join(' '));chart.appendChild(line);}
}
async function refresh(){const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000);try{const response=await fetch('/live/v1/snapshot',{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('Observer unavailable');render(await response.json());}catch(e){unavailable('Observer unavailable or refresh timed out; prior analysis withheld');}finally{clearTimeout(timeout);setTimeout(refresh,interval);}}
fetch('/live/v1/settings',{cache:'no-store'}).then(r=>r.json()).then(s=>{if(Number.isInteger(s.refresh_seconds)&&s.refresh_seconds>=2&&s.refresh_seconds<=60)interval=s.refresh_seconds*1000;}).catch(()=>{}).finally(refresh);
