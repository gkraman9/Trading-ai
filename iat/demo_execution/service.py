"""Durable Stage-A automatic execution state machine, restricted to synthetic transports.

There is deliberately no MT5 order adapter. No flag or config file enables one.
"""
from decimal import Decimal
from dataclasses import asdict
import json
from iat.demo_execution.policy import Blocked,need,number,utc,digest,risk_request
from iat.demo_execution.store import ACTIVE


def report(status,code=None,order_id=None):
    return dict(version=1,mode='DEMO_EXECUTION_STAGE_A_REHEARSAL',status=status,reason_codes=[code] if code else [],
        order_id=order_id,signal='WAIT',execution_allowed=False,orders_requested=0,
        exness='BLOCKED',historical_validation='PENDING',historical_comparisons='NOT_RUN',profitability_tested=False)


class RehearsalService:
    def __init__(self,config,store,transport,*,opt_in=False):
        need(getattr(transport,'synthetic_only',None) is True,'REAL_TRANSPORT_NOT_IMPLEMENTED')
        self.config=config;self.store=store;self.transport=transport;self.opt_in=opt_in;self.failed=False
    def process(self,signal,now):
        key=None;submitted=False
        try:
            need(not self.failed,'SERVICE_FAILED_CLOSED');need(self.opt_in is True,'EXPLICIT_OPT_IN_REQUIRED')
            key=signal.identity(self.config.expected_account_fingerprint)
            with self.store.connection() as db:
                self.store.verify_db(db);need(self.store.stop_value(db)=='0','EMERGENCY_STOP')
                need(not any(json.loads(r[0])['data']['day']==utc(now).date().isoformat() for r in db.execute("SELECT body FROM audit WHERE json_extract(body,'$.event')='LOSS_LIMIT_LATCH'")),'DAY_LOSS_LATCHED')
                need(db.execute('SELECT 1 FROM orders WHERE id=?',(key,)).fetchone() is None,'DUPLICATE_SIGNAL')
                need(db.execute('SELECT COUNT(*) FROM orders WHERE state IN (?,?,?,?,?)',ACTIVE).fetchone()[0]==0,'UNRESOLVED_POSITION_OR_ORDER')
                snap=self.transport.snapshot(now);request,pnl,start=risk_request(self.config,signal,snap,now)
                day=utc(now).date().isoformat();ids={r[0] for r in db.execute('SELECT id FROM orders WHERE day=?',(day,))}|set(snap['opening_order_ids_today'])
                need(len(ids)<5,'DAILY_TRADE_LIMIT')
                # Persist baseline in the audit and reject revisions of starting equity/opening mark.
                baseline=dict(day=day,starting_equity=str(number(snap['starting_equity'])),opening_unrealized=str(number(snap['opening_unrealized'])))
                old=[json.loads(r[0])['data'] for r in db.execute("SELECT body FROM audit WHERE json_extract(body,'$.event')='DAY_BASELINE'") if json.loads(r[0])['data']['day']==day]
                need(not old or old[-1]==baseline,'DAY_BASELINE_REVISED')
                request['client_id']=key;request['config_sha256']=self.config.sha256
                checked=self.transport.order_check(request,expected_account=self.config.expected_account_fingerprint)
                need(checked['accepted'] is True,'BROKER_CHECK_REJECTED')
                need(checked['currency']==self.config.currency and checked['loss_bound_verified'] is True,'ORDER_RISK_UNVERIFIED')
                risk=number(checked['worst_case_loss']);need(risk>0 and pnl-risk>-start*Decimal('.01'),'PROJECTED_DAILY_LOSS_LIMIT')
                self.store.event(db,'DAY_BASELINE',None,baseline)
                db.execute('INSERT INTO orders VALUES (?,?,?,?,NULL)',(key,day,'PREPARED',json.dumps(request,sort_keys=True,allow_nan=False)))
                self.store.event(db,'INTENT',key,dict(state='PREPARED',day=day,request=request,result=None,signal_reference=asdict(signal),snapshot_sha256=digest(snap),qualification_scope='SYNTHETIC_TEST_ONLY'))
            # PREPARED is committed before a possible side effect. Never retry after uncertainty.
            with self.store.connection() as db:
                self.store.verify_db(db);need(self.store.stop_value(db)=='0','EMERGENCY_STOP')
                snap=self.transport.snapshot(now);fresh,_,_=risk_request(self.config,signal,snap,now)
                need(all(fresh[k]==request[k] for k in fresh),'MARKET_CHANGED_REQUALIFICATION_REQUIRED')
                db.execute("UPDATE orders SET state='SUBMITTING' WHERE id=?",(key,));self.store.event(db,'STATE',key,dict(state='SUBMITTING',result=None))
            try:
                # Synthetic transport contract atomically verifies account/limits/idempotency at submit.
                submitted=True
                result=self.transport.guarded_submit(request,expected_account=self.config.expected_account_fingerprint)
            except Exception:
                self.store.transition(key,'UNKNOWN',stop=True);return report('BLOCKED','SUBMISSION_UNCERTAIN',key)
            return self._settle(key,request,result)
        except Blocked as exc:
            try:
                if submitted:self.store.transition(key,'UNKNOWN',stop=True)
                elif exc.code=='DAILY_LOSS_LIMIT':self.store.latch_daily_loss(utc(now).date().isoformat())
                self.store.reject(exc.code)
            except Exception:self.failed=True;return report('BLOCKED','AUDIT_UNAVAILABLE',key)
            # A committed reservation remains a barrier, even if a subsequent pre-send check fails.
            return report('BLOCKED',exc.code,key)
        except Exception:
            self.failed=True
            try:self.store.emergency_stop()
            except Exception:pass
            return report('BLOCKED','UNEXPECTED_INPUT_OR_AUDIT_FAILURE',key)
    def _settle(self,key,request,result):
        need(type(result) is dict and set(result)=={'status','volume','price','sl','tp','broker_reference'},'BROKER_RESULT_UNVERIFIED')
        need(result['status'] in ('REJECTED','FILLED','PARTIAL','CLOSED'),'BROKER_RESULT_UNVERIFIED')
        if result['status']=='REJECTED':
            need(number(result['volume'])==0,'BROKER_RESULT_UNVERIFIED');self.store.transition(key,'REJECTED',result);return report('SIMULATED_REJECTED','BROKER_REJECTED',key)
        need(isinstance(result['broker_reference'],str) and result['broker_reference'],'BROKER_RESULT_UNVERIFIED')
        volume=number(result['volume']);need(0<volume<=Decimal('.01'),'BROKER_RESULT_UNVERIFIED')
        # Postfill discrepancies cannot be undone; latch stop, retain exposure, never top up or resend.
        point=number(self.transport.symbol_point())
        need(point>0,'BROKER_RESULT_UNVERIFIED')
        verified=(number(result['sl'])==number(request['sl']) and number(result['tp'])==number(request['tp'])
            and abs(number(result['price'])-number(request['price']))/point<=number(self.config.max_slippage_points))
        state='CLOSED' if result['status']=='CLOSED' and verified and volume==Decimal('.01') else 'OPEN' if result['status']=='FILLED' and verified and volume==Decimal('.01') else 'PARTIAL' if volume<Decimal('.01') or result['status']=='PARTIAL' else 'UNKNOWN'
        self.store.transition(key,state,result,stop=state in ('PARTIAL','UNKNOWN'))
        return report('SIMULATED_'+state,'FILL_REQUIRES_OPERATOR_RECONCILIATION' if state in ('PARTIAL','UNKNOWN') else None,key)
    def reconcile(self):
        """Exact client-ID history lookup; absence is not proof of non-execution."""
        results=[]
        try:
            self.store.verify()
            with self.store.connection() as db:rows=[dict(r) for r in db.execute('SELECT * FROM orders WHERE state IN (?,?,?,?,?)',ACTIVE)]
            for row in rows:
                known=self.transport.lookup(row['id'],expected_account=self.config.expected_account_fingerprint)
                if known is None:
                    self.store.transition(row['id'],'UNKNOWN',stop=True);results.append(report('BLOCKED','RECONCILIATION_UNCERTAIN',row['id']))
                else:results.append(self._settle(row['id'],json.loads(row['request']),known))
        except Exception:
            self.failed=True
            try:self.store.emergency_stop()
            except Exception:pass
            return [report('BLOCKED','RECONCILIATION_OR_AUDIT_FAILURE')]
        return results
