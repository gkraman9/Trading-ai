"""Bounded research facts for v3. No new detectors, scores or directional decisions."""
from datetime import datetime, timezone
from math import isfinite
from iat.intelligence.strategy_replay import digest
from iat.live_readable import event_label

SECTIONS=('summary','structure','price_action','levels','bullish','bearish','conflicts','wait','next')
TITLES=dict(zip(SECTIONS,('Current market situation','M1 versus M5','Price action','Important levels to watch',
    'Bullish research hypothesis','Bearish research hypothesis','Conflicting evidence','Why IAT is waiting','What IAT is watching next')))


def utc(value):
    at=datetime.fromisoformat(value)
    if at.tzinfo is None or at.utcoffset().total_seconds()!=0:raise ValueError('UTC required')
    return at


def catalog(snapshot,view,previous=None):
    """Only local text/values can be rendered. Model selects relevant facts and connections.

    A factual assertion is a typed immutable card, not model prose plus a citation.
    References alone cannot validate prose, direction, a price or event ordering.
    """
    obs=snapshot.get('observations',{});registry=obs.get('source_registry',{});evidence=obs.get('evidence',[])
    known=set(registry)|{e['id'] for e in evidence};cutoffs=snapshot['cutoffs']
    if len({e['id'] for e in evidence})!=len(evidence):raise ValueError('Duplicate evidence')
    if snapshot['feed_status']=='CONNECTED':
        acquired=utc(snapshot['acquired_at_utc'])
        for tf in ('M1','M5'):
            if utc(cutoffs[tf])>acquired:raise ValueError('Future cutoff')
        for item in [*registry.values(),*evidence]:
            tf=item['timeframe'];available=utc(item['available_at']);opened=utc(item['observed_at'])
            if tf not in cutoffs or opened>available or available>utc(cutoffs[tf]):raise ValueError('Evidence chronology')
            if not set(item.get('references',[]))<=known:raise ValueError('Unknown reference')
            if item.get('kind')=='CANDLE':
                b=item['ohlc'];values=[b[k] for k in ('open','high','low','close')]
                if any(type(v) not in (int,float) or not isfinite(v) or v<=0 for v in values) or b['low']>min(b['open'],b['close']) or b['high']<max(b['open'],b['close']) or b['low']>b['high']:raise ValueError('Malformed OHLC')
        for tf,f in view['structures'].items():
            if utc(f['closed_at'])!=utc(cutoffs[tf]):raise ValueError('Frame cutoff mismatch')
            for item in f['recent_events']+f['recent_swings']:
                if utc(item['confirmed_at'])>utc(cutoffs[tf]):raise ValueError('Unconfirmed event')
        for z in view['levels']:
            if z['origin_at'] and utc(z['origin_at'])>utc(cutoffs[z['timeframe']]):raise ValueError('Future level')
    cards=[];mandatory={s:[] for s in SECTIONS}
    def add(section,text,ids=(),*,tf=None,event=None,level=None,direction='NEUTRAL',kind='OBSERVATION',required=False):
        ids=sorted(set(ids))
        if not set(ids)<=known:raise ValueError('Unknown source reference')
        c=dict(section=section,text=text,evidence_ids=ids,timeframe=tf,event_type=event,
               level=level,direction=direction,kind=kind)
        c['fact_id']='fact:'+digest(c);cards.append(c)
        if required:mandatory[section].append(c['fact_id'])
    o=view['overview']
    add('summary',f"XAUUSD: {o['research_assessment']}. Formal regime: {o['market_regime']}. Descriptive observations are separate from session eligibility.",required=True)
    add('summary','Operational signal remains WAIT; execution is disabled. No research statement authorizes an order.',kind='SAFETY',required=True)
    for tf,f in view['structures'].items():
        add('structure',f['summary'],f['evidence_ids'],tf=tf,required=True)
        for p in f['recent_swings'][-2:]:
            add('price_action',f"{tf}: {p['description']} ({p['relation']}) at {p['price']}; confirmed {p['confirmed_at']}.",p['evidence_ids'],tf=tf)
        for e in f['recent_events'][-2:]:
            add('price_action',f"{tf}: {e['description']} at {e['level']}; confirmed {e['confirmed_at']}.",e['evidence_ids'],tf=tf,event=e['event_type'])
    add('structure',f"M1/M5 descriptive alignment: {o['alignment_label']}.",required=True)
    # Existing evidence only: no interpreted proximity/rejection/break derived from a live tick.
    for tf in ('M1','M5'):
        for category in ('CANDLE','MOMENTUM','VOLATILITY','LIQUIDITY','TRANSITION'):
            items=sorted((e for e in evidence if e['timeframe']==tf and e['category']==category),key=lambda e:(e['available_at'],e['id']))[-1:]
            for e in items:
                d=e['details'];name=d.get('name') or d.get('event_type') or d.get('regime') or d.get('kind') or category
                text=f"{tf}: {event_label(name)}; evidence direction {e['direction'].lower()}."
                add('price_action',text,[e['id'],*e.get('references',[])],tf=tf,event=d.get('event_type'),direction=e['direction'])
    levels=sorted((z for z in view['levels'] if z['status']!='INVALIDATED'),key=lambda z:(z['timeframe'],z['origin_at'] or '',z['id']),reverse=True)[:8]
    for z in levels:
        if not all(type(z[k]) in (int,float) and isfinite(z[k]) for k in ('lower','upper')) or z['lower']>z['upper']:raise ValueError('Invalid level')
        add('levels',f"{z['timeframe']} {z['kind']}: {z['lower']}–{z['upper']}; state {z['status']}. OHLC-derived proxy, not a forecast.",
            z['evidence_ids'],tf=z['timeframe'],level=dict(id=z['id'],lower=z['lower'],upper=z['upper']))
    for direction in ('BULLISH','BEARISH'):
        section=direction.lower();p=view['scenarios'][direction]
        add(section,p['summary'],kind='INTERPRETATION',direction=direction,required=True)
        for role,items in (('SUPPORT',p['supporting']),('OPPOSITION',p['contradictory'])):
            for e in items[:3]:
                add(section,role.title()+': '+e['text'],e['evidence_ids'],tf=e['timeframe'],direction=e['direction'],kind=role)
                if role=='OPPOSITION':add('conflicts',f"Against the {section} view: {e['text']}",e['evidence_ids'],tf=e['timeframe'],direction=e['direction'],kind=role)
        for condition in p['strengthening_conditions'][:2]:
            add(section,'Existing strengthening assumption: '+condition,kind='CONDITION',direction=direction)
        for condition in p['invalidation_conditions'][:2]:
            add(section,'Existing invalidation condition: '+condition,kind='INVALIDATION',direction=direction)
        if not p['strengthening_conditions'] and not p['invalidation_conditions']:
            add(section,'Formal confirmation and invalidation conditions are unavailable. Descriptive support is not an eligible directional hypothesis.',kind='UNCERTAINTY',required=True)
    for b in view['wait']['blockers']:
        add('wait',b['code']+': '+b['text'],kind='GATE',required=True)
    if 'BLOCKED_DATA_QUALITY' in snapshot.get('reason_codes',[]):
        add('wait','BLOCKED_DATA_QUALITY: Formal directional context is blocked; these observations are descriptive only.',kind='GATE',required=True)
    if not mandatory['wait']:add('wait',view['wait']['summary'],kind='GATE',required=True)
    for tf in ('M1','M5'):
        add('next',f"Reassess {tf} patterns, confirmed swings and structure only after the next eligible {tf} candle closes. A forming candle is not confirmation.",tf=tf,kind='CONDITIONAL',required=True)
    changes=[]
    if previous:
        for tf in ('M1','M5'):
            old=previous['structures'][tf];new=view['structures'][tf]
            if old['closed_at']!=new['closed_at']:changes.append(f"{tf} closed-candle cutoff advanced from {old['closed_at']} to {new['closed_at']}.")
            if old['state']!=new['state']:changes.append(f"{tf} confirmed structure changed from {old['state']} to {new['state']}.")
            prior={(e['event_type'],e['confirmed_at'],e['level']) for e in old['recent_events']}
            for e in new['recent_events']:
                if (e['event_type'],e['confirmed_at'],e['level']) not in prior:changes.append(f"New {tf} {e['description']}, confirmed {e['confirmed_at']}.")
        if previous['overview']['research_assessment']!=o['research_assessment']:changes.append('The deterministic research assessment changed; operational signal remains WAIT.')
        if previous['wait']!=view['wait']:changes.append('The deterministic WAIT reasons changed; inspect the current gates.')
    transition=snapshot.get('transition')
    if transition:
        add('summary','Existing scenario transition: '+transition['classification']+'.',kind='INTERPRETATION')
    for s in SECTIONS:
        if not any(c['section']==s for c in cards):add(s,'No supported '+TITLES[s].lower()+' observation is available.',kind='UNCERTAINTY',required=True)
    # Every directional panel keeps its opposing evidence visible, rather than model cherry-picking it away.
    for s in ('bullish','bearish','conflicts'):
        mandatory[s]=[c['fact_id'] for c in cards if c['section']==s]
    if len({c['fact_id'] for c in cards})!=len(cards) or any(sum(c['section']==s for c in cards)>32 for s in SECTIONS):raise ValueError('Duplicate or oversized fact catalog')
    packet=dict(commentary_version=3,symbol='XAUUSD',evidence_bundle_id=view['claims']['bundle_id'],
        cutoffs=cutoffs,cards=cards,required_fact_ids=mandatory,
        changes=changes or ['No prior comparable material observation is available.' if previous is None else 'No tracked structure or cutoff change.'],
        limitations=view['limitations'],scope='DESCRIPTIVE_ONLY_WHEN_SESSION_BLOCKED')
    if len(str(packet).encode())>96*1024:raise ValueError('Evidence packet too large')
    packet['bundle_id']=digest(packet)
    return packet


def schema():
    string={'type':'string'}
    item=dict(type='object',additionalProperties=False,required=['fact_id','evidence_ids','timeframe','event_type','level','direction'],properties={
        'fact_id':string,'evidence_ids':dict(type='array',items=string,maxItems=40),
        'timeframe':dict(type=['string','null'],enum=['M1','M5',None]),'event_type':dict(type=['string','null']),
        'level':dict(anyOf=[{'type':'null'},dict(type='object',additionalProperties=False,required=['id','lower','upper'],properties={'id':string,'lower':{'type':'number'},'upper':{'type':'number'}})]),
        'direction':dict(type='string',enum=['BULLISH','BEARISH','RANGING','NEUTRAL'])})
    return dict(type='object',additionalProperties=False,required=['version','bundle_id','sections'],properties={
        'version':dict(type='integer',enum=[3]),'bundle_id':string,
        'sections':dict(type='array',minItems=9,maxItems=9,items=dict(type='object',additionalProperties=False,required=['section','claims'],properties={
            'section':dict(type='string',enum=list(SECTIONS)),'claims':dict(type='array',minItems=1,maxItems=32,items=item)}))})


def validate(value,packet):
    """Validate values, chronology binding, references and coverage, never just citations."""
    def need(ok):
        if not ok:raise ValueError('AI_EVIDENCE_VALIDATION_FAILED')
    need(type(value) is dict and set(value)=={'version','bundle_id','sections'})
    need(type(value['version']) is int and value['version']==3 and value['bundle_id']==packet['bundle_id'])
    need(type(value['sections']) is list and len(value['sections'])==len(SECTIONS))
    by_id={c['fact_id']:c for c in packet['cards']};seen_sections=set();out=[]
    fields=('fact_id','evidence_ids','timeframe','event_type','level','direction')
    for section in value['sections']:
        need(type(section) is dict and set(section)=={'section','claims'})
        name=section['section'];need(isinstance(name,str) and name in SECTIONS and name not in seen_sections);seen_sections.add(name)
        need(type(section['claims']) is list and 1<=len(section['claims'])<=32);seen=set();rendered=[]
        for assertion in section['claims']:
            need(type(assertion) is dict and set(assertion)==set(fields))
            key=assertion['fact_id'];need(isinstance(key,str) and key in by_id and key not in seen);seen.add(key);fact=by_id[key]
            level=assertion['level']
            if level is not None:
                need(type(level) is dict and set(level)=={'id','lower','upper'} and isinstance(level['id'],str))
                need(all(type(level[k]) in (int,float) and isfinite(level[k]) for k in ('lower','upper')))
            need(fact['section']==name and all(assertion[k]==fact[k] for k in fields))
            rendered.append(dict(fact_id=key,text=fact['text'],kind=fact['kind'],evidence_ids=fact['evidence_ids']))
        need(set(packet['required_fact_ids'][name])<=seen)
        out.append(dict(section=name,title=TITLES[name],claims=rendered))
    need(seen_sections==set(SECTIONS));return out


def fallback(packet):
    return [dict(section=s,title=TITLES[s],claims=[dict(fact_id=c['fact_id'],text=c['text'],kind=c['kind'],evidence_ids=c['evidence_ids']) for c in packet['cards'] if c['section']==s]) for s in SECTIONS]
