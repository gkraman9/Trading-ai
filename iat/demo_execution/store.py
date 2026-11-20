"""Private durable intent ledger. SQLite serializes admission across processes."""
from contextlib import contextmanager
from pathlib import Path
import json,sqlite3
from iat.demo_execution.policy import Blocked,need,digest
from iat.replay_dataset import strict_json

ACTIVE=('PREPARED','SUBMITTING','UNKNOWN','PARTIAL','OPEN')
STATES=set(ACTIVE)|{'REJECTED','CLOSED'}
TRANSITIONS={'PREPARED':{'SUBMITTING','UNKNOWN','REJECTED'},'SUBMITTING':{'UNKNOWN','REJECTED','OPEN','PARTIAL','CLOSED'},'UNKNOWN':{'UNKNOWN','REJECTED','OPEN','PARTIAL','CLOSED'},'OPEN':{'OPEN','UNKNOWN','PARTIAL','CLOSED'},'PARTIAL':{'PARTIAL','OPEN','UNKNOWN','CLOSED'},'CLOSED':{'CLOSED'},'REJECTED':{'REJECTED'}}


class Store:
    def __init__(self,root,config_sha256,*,create=False):
        self.root=Path(root);repo=Path(__file__).resolve().parents[2]
        need(not self.root.resolve().is_relative_to(repo) and not any(p.is_symlink() for p in (self.root,*self.root.parents)),'PRIVATE_STATE_PATH_REQUIRED')
        if create:
            need(not self.root.exists(),'STATE_ALREADY_EXISTS');self.root.mkdir(mode=0o700,parents=True,exist_ok=False)
        need(self.root.is_dir(),'STATE_MISSING');self.path=self.root/'rehearsal.sqlite3';self.config_sha256=config_sha256
        need(not any(p.is_symlink() for p in self.root.iterdir()),'STATE_PATH_UNSAFE')
        if create:
            with self.connection(create=True) as db:
                db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                db.execute('CREATE TABLE orders (id TEXT PRIMARY KEY,day TEXT NOT NULL,state TEXT NOT NULL,request TEXT NOT NULL,result TEXT)')
                db.execute('CREATE TABLE audit (seq INTEGER PRIMARY KEY,body TEXT NOT NULL,sha256 TEXT NOT NULL)')
                db.execute('INSERT INTO meta VALUES (?,?)',('config',config_sha256));db.execute('INSERT INTO meta VALUES (?,?)',('stop','1'))
                self.event(db,'INIT',None,dict(config_sha256=config_sha256,stop=True))
        self.verify()
    @contextmanager
    def connection(self,*,create=False):
        db=None
        try:
            need(create or self.path.is_file(),'STATE_MISSING')
            db=sqlite3.connect(str(self.path),timeout=1,isolation_level=None)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
            yield db;db.execute('COMMIT')
        except Blocked:
            if db is not None and db.in_transaction:db.execute('ROLLBACK')
            raise
        except Exception:
            if db is not None and db.in_transaction:db.execute('ROLLBACK')
            raise Blocked('STATE_OR_AUDIT_UNAVAILABLE') from None
        finally:
            if db is not None:db.close()
    def event(self,db,kind,order_id,data):
        last=db.execute('SELECT seq,sha256 FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        record=dict(scope='SYNTHETIC_REHEARSAL_ONLY',execution_allowed=False,orders_requested=0,seq=1 if last is None else last['seq']+1,previous_sha256=None if last is None else last['sha256'],event=kind,order_id=order_id,data=data)
        db.execute('INSERT INTO audit VALUES (?,?,?)',(record['seq'],json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False),digest(record)))
    def verify_db(self,db):
        need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','STATE_CORRUPT')
        need(dict(db.execute('SELECT key,value FROM meta').fetchall())=={'config':self.config_sha256,'stop':self.stop_value(db)},'STATE_CONFIG_MISMATCH')
        need(db.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0]==self.config_sha256,'STATE_CONFIG_MISMATCH')
        previous=None;count=0;orders={};stop=None
        for row in db.execute('SELECT * FROM audit ORDER BY seq'):
            record=strict_json(row['body']);count+=1
            need(record['seq']==count and row['seq']==count and record['previous_sha256']==previous and digest(record)==row['sha256'],'AUDIT_CORRUPT')
            need(record['scope']=='SYNTHETIC_REHEARSAL_ONLY' and record['execution_allowed'] is False and type(record['orders_requested']) is int and record['orders_requested']==0,'AUDIT_CORRUPT')
            previous=row['sha256'];kind=record['event'];data=record['data'];key=record['order_id']
            if kind=='INIT':
                need(count==1 and data=={'config_sha256':self.config_sha256,'stop':True},'AUDIT_CORRUPT');stop=True
            elif kind=='STOP':need(type(data['stop']) is bool,'AUDIT_CORRUPT');stop=data['stop']
            elif kind=='INTENT':
                need(key not in orders and data['state']=='PREPARED','AUDIT_CORRUPT');orders[key]=data
            elif kind=='STATE':
                need(key in orders and data['state'] in TRANSITIONS[orders[key]['state']],'AUDIT_CORRUPT');orders[key]={**orders[key],**data}
            elif kind not in ('REJECTION','DAY_BASELINE','LOSS_LIMIT_LATCH'):raise Blocked('AUDIT_CORRUPT')
        need(count>0 and stop is not None and self.stop_value(db)==('1' if stop else '0'),'AUDIT_CORRUPT')
        rows=db.execute('SELECT * FROM orders').fetchall();need({r['id'] for r in rows}==set(orders),'STATE_CORRUPT')
        for row in rows:
            expected=orders[row['id']]
            need(row['day']==expected['day'] and row['state']==expected['state'] and strict_json(row['request'])==expected['request'] and (strict_json(row['result']) if row['result'] else None)==expected.get('result'),'STATE_CORRUPT')
    def verify(self):
        with self.connection() as db:self.verify_db(db)
    @staticmethod
    def stop_value(db):
        row=db.execute("SELECT value FROM meta WHERE key='stop'").fetchone();need(row is not None and row[0] in ('0','1'),'STATE_CORRUPT');return row[0]
    def emergency_stop(self,*,reset=False,acknowledge=False):
        need(not reset or acknowledge is True,'RESET_ACKNOWLEDGEMENT_REQUIRED')
        with self.connection() as db:
            self.verify_db(db)
            if reset:need(db.execute('SELECT COUNT(*) FROM orders WHERE state IN (?,?,?,?,?)',ACTIVE).fetchone()[0]==0,'UNRESOLVED_ORDER_BLOCKS_RESET')
            db.execute("UPDATE meta SET value=? WHERE key='stop'",('0' if reset else '1',));self.event(db,'STOP',None,dict(stop=not reset))
    def latch_daily_loss(self,day):
        with self.connection() as db:
            self.verify_db(db);self.event(db,'LOSS_LIMIT_LATCH',None,dict(day=day))
            db.execute("UPDATE meta SET value='1' WHERE key='stop'");self.event(db,'STOP',None,dict(stop=True))
    def transition(self,order_id,state,result=None,*,stop=False):
        need(state in STATES,'STATE_INVALID')
        with self.connection() as db:
            self.verify_db(db);row=db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone();need(row is not None,'ORDER_UNKNOWN');need(state in TRANSITIONS[row['state']],'BROKER_STATE_CONTRADICTION')
            db.execute('UPDATE orders SET state=?,result=? WHERE id=?',(state,json.dumps(result,sort_keys=True,allow_nan=False) if result is not None else None,order_id))
            self.event(db,'STATE',order_id,dict(state=state,result=result))
            if stop:
                db.execute("UPDATE meta SET value='1' WHERE key='stop'");self.event(db,'STOP',None,dict(stop=True))
    def reject(self,code):
        with self.connection() as db:self.verify_db(db);self.event(db,'REJECTION',None,dict(reason_code=code))
