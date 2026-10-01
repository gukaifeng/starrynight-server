"""Small persistent local deployment; SQLite WAL, transactions, owner/role scope."""
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, json, time, math, hashlib
from .greetings import normalized
from .novelty import tokens
from . import novelty

def dump(value): return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def clamp(value): return min(1.,max(0.,value))

class Store:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db = sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS records(kind TEXT,owner TEXT,character TEXT,data TEXT,updated REAL,PRIMARY KEY(kind,owner,character));
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,owner TEXT,character TEXT,request TEXT,role TEXT,data TEXT,created REAL);
        CREATE INDEX IF NOT EXISTS messages_scope ON messages(owner,character,created);
        CREATE TABLE IF NOT EXISTS requests(owner TEXT,character TEXT,id TEXT,payload_hash TEXT,status TEXT,result TEXT,created REAL,PRIMARY KEY(owner,character,id));
        CREATE TABLE IF NOT EXISTS memories(id TEXT,owner TEXT,character TEXT,source TEXT,content TEXT,importance REAL,created REAL,recalled REAL,PRIMARY KEY(owner,character,id));
        CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY,kind TEXT,owner TEXT,character TEXT,reserved REAL,units REAL,status TEXT,metrics TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS asset_usage(id INTEGER PRIMARY KEY,owner TEXT,character TEXT,asset TEXT,kind TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS voice_design_jobs(id TEXT PRIMARY KEY,character TEXT,status TEXT,data TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS reply_novelty(message TEXT UNIQUE,owner TEXT,character TEXT,text TEXT,canonical TEXT,created REAL);
        CREATE INDEX IF NOT EXISTS reply_novelty_exact ON reply_novelty(owner,canonical);
        CREATE INDEX IF NOT EXISTS reply_novelty_recent ON reply_novelty(owner,created DESC);
        CREATE INDEX IF NOT EXISTS reply_novelty_role ON reply_novelty(owner,character,created DESC);
        CREATE VIRTUAL TABLE IF NOT EXISTS reply_novelty_search USING fts5(grams);
        CREATE TABLE IF NOT EXISTS reply_embeddings(message TEXT,model TEXT,vector BLOB,PRIMARY KEY(message,model));
        CREATE TABLE IF NOT EXISTS reaction_drafts(id TEXT PRIMARY KEY,owner TEXT,character TEXT,kind TEXT,context_key TEXT,status TEXT,data TEXT,created REAL,expires REAL);
        CREATE INDEX IF NOT EXISTS reaction_drafts_pool ON reaction_drafts(owner,character,context_key,kind,status,expires);
        CREATE TABLE IF NOT EXISTS quick_reply_sets(owner TEXT,character TEXT,source TEXT,context_key TEXT,data TEXT,expires REAL,PRIMARY KEY(owner,character));
        CREATE TABLE IF NOT EXISTS conversation_resets(owner TEXT,character TEXT,id TEXT,created REAL,version INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(owner,character,id));
        ''')
        if 'version' not in {row['name'] for row in self.db.execute('PRAGMA table_info(conversation_resets)')}:
            self.db.execute('ALTER TABLE conversation_resets ADD COLUMN version INTEGER NOT NULL DEFAULT 0')
        self.db.commit()
        if not self.get('migration','system','reply-novelty-v1'):
            with self.db:
                for row in self.db.execute("SELECT * FROM messages WHERE role='assistant'"):
                    self.index_reply(row['id'],row['owner'],row['character'],json.loads(row['data']).get('text',''),row['created'])
                self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',('migration','system','reply-novelty-v1','true',time.time()))

    def get(self,kind,owner,character,default=None):
        row=self.db.execute('SELECT data FROM records WHERE kind=? AND owner=? AND character=?',(kind,owner,character)).fetchone()
        return json.loads(row[0]) if row else default
    def put(self,kind,owner,character,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',(kind,owner,character,dump(value),time.time()))
    def approve_voice(self,character,job_id=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            active=self.get('voice','system',character)
            voice=self.get('voice_candidate','system',character) or active
            if not voice or not voice.get('voice_id'):raise ValueError('VOICE_NOT_READY')
            if active and active.get('approved') and active.get('job_id')!=voice.get('job_id') and not job_id:
                raise ValueError('VOICE_CANDIDATE_REQUIRED')
            if job_id and voice.get('job_id')!=job_id:raise ValueError('VOICE_CANDIDATE_CHANGED')
            if active and active.get('approved') and active.get('job_id')!=voice.get('job_id'):
                self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',
                    ('voice_history',active.get('job_id',active['voice_id']),character,dump(active),time.time()))
            voice={**voice,'approved':True}
            self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',('voice','system',character,dump(voice),time.time()))
            self.db.execute("DELETE FROM records WHERE kind='voice_candidate' AND owner='system' AND character=?",(character,))
            self.db.execute("UPDATE voice_design_jobs SET status='approved',data=? WHERE id=?",(dump(voice),voice.get('job_id')))
            return voice
    def history(self,owner,character,limit=12):
        rows=self.db.execute('SELECT role,data FROM messages WHERE owner=? AND character=? ORDER BY created DESC LIMIT ?',(owner,character,limit)).fetchall()
        return [dict(role=r['role'],text=json.loads(r['data']).get('text','')[:700]) for r in reversed(rows)]
    def message(self,id,owner,character,request,role,data):
        with self.db:
            now=time.time()
            inserted=self.db.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?)',(id,owner,character,request,role,dump(data),now)).rowcount
            if inserted and role=='assistant':self.index_reply(id,owner,character,data.get('text',''),now)
    def index_reply(self,id,owner,character,text,created):
        if not normalized(text):return
        cursor=self.db.execute('INSERT OR IGNORE INTO reply_novelty VALUES(?,?,?,?,?,?)',(id,owner,character,text,normalized(text),created))
        if cursor.rowcount:self.db.execute('INSERT INTO reply_novelty_search(rowid,grams) VALUES(?,?)',(cursor.lastrowid,tokens(text)))
    def clear_novelty(self,owner,character):
        self.db.execute('DELETE FROM reply_embeddings WHERE message IN (SELECT message FROM reply_novelty WHERE owner=? AND character=?)',(owner,character))
        self.db.execute('DELETE FROM reply_novelty_search WHERE rowid IN (SELECT rowid FROM reply_novelty WHERE owner=? AND character=?)',(owner,character))
        self.db.execute('DELETE FROM reply_novelty WHERE owner=? AND character=?',(owner,character))
    def publish_reply(self,owner,character,request,user_text,script,*,prepared_id=None,allow_preparing=False):
        # Serialize the final check and publication even if another worker/role
        # finishes while this one is awaiting its model. Index and transcript
        # commit together; a rejected candidate never becomes replayable.
        import uuid
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if prepared_id:
                statuses=('ready','preparing') if allow_preparing else ('ready','ready')
                changed=self.db.execute("UPDATE reaction_drafts SET status='used' WHERE id=? AND owner=? AND character=? AND status IN (?,?) AND expires>?",(prepared_id,owner,character,*statuses,time.time())).rowcount
                if changed!=1:raise ValueError('REACTION_ALREADY_USED')
            if novelty.match(self,owner,script['text']):raise ValueError('REPLY_REPEATED')
            now=time.time()
            if user_text:self.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),owner,character,request,'user',dump(dict(text=user_text)),now))
            self.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(script['message_id'],owner,character,request,'assistant',dump(script),now+.000001))
            self.index_reply(script['message_id'],owner,character,script['text'],now)
            if prepared_id:
                self.db.execute("UPDATE requests SET status='completed',result=? WHERE owner=? AND character=? AND id=?",(dump(script),owner,character,request))
    def request(self,owner,character,id,payload):
        digest=hashlib.sha256(dump(payload).encode()).hexdigest()
        row=self.db.execute('SELECT * FROM requests WHERE owner=? AND character=? AND id=?',(owner,character,id)).fetchone()
        if row:
            if row['payload_hash']!=digest: raise ValueError('REQUEST_ID_REUSED')
            if row['result']:return json.loads(row['result'])
            raise ValueError('REQUEST_INCOMPLETE') # never automatically repeat a possibly billed call
        with self.db:self.db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',(owner,character,id,digest,'running',None,time.time()))
        return None
    def complete(self,owner,character,id,result):
        with self.db:self.db.execute('UPDATE requests SET status=?,result=? WHERE owner=? AND character=? AND id=?',('completed',dump(result),owner,character,id))
    def enrich_reply(self,owner,character,id,result):
        with self.db:
            self.db.execute("UPDATE messages SET data=? WHERE id=? AND owner=? AND character=? AND role='assistant'",(dump(result),result['message_id'],owner,character))
            self.db.execute("UPDATE requests SET result=? WHERE owner=? AND character=? AND id=? AND status='completed'",(dump(result),owner,character,id))
    def sync_memories(self,owner,character,memories):
        with self.db:
            self.db.execute("DELETE FROM memories WHERE owner=? AND character=? AND source='manual'",(owner,character))
            for m in memories:self.db.execute('INSERT OR REPLACE INTO memories VALUES(?,?,?,?,?,?,?,?)',('manual:'+m.id,owner,character,'manual',m.text,.95,time.time(),0))
    def recall(self,owner,character,query,*,incoming=None,touch=True):
        rows=self.db.execute('SELECT * FROM memories WHERE owner=? AND character=?',(owner,character)).fetchall()
        if incoming is not None:
            rows=[r for r in rows if r['source']!='manual']+[dict(id='manual:'+m.id,source='manual',content=m.text,importance=.95,created=time.time()) for m in incoming]
        grams={query[i:i+2] for i in range(max(0,len(query)-1))}
        def score(r):
            overlap=sum(g in r['content'] for g in grams)/max(1,len(grams))
            return .65*overlap+.25*r['importance']+.1*math.exp(-(time.time()-r['created'])/2592000)
        chosen=sorted(rows,key=score,reverse=True)[:6]
        if touch:
            with self.db:
                for r in chosen:self.db.execute('UPDATE memories SET recalled=? WHERE owner=? AND character=? AND id=?',(time.time(),owner,character,r['id']))
        return [dict(type=r['source'],content=r['content']) for r in chosen]
    def state(self,owner,character):
        state=self.get('state',owner,character,dict(happiness=.45,sadness=.1,anger=0,anxiety=.1,loneliness=.1,energy=.65,boredom=.1,attention_to_user=.7,updated=time.time(),unanswered_proactive_count=0))
        dt=max(0,min(86400,time.time()-state.get('updated',time.time())))
        for key,base in [('happiness',.45),('sadness',.1),('anger',0),('anxiety',.1)]:
            state[key]=clamp(base+(state.get(key,base)-base)*math.exp(-dt/3600))
        state['boredom']=clamp(state.get('boredom',.1)+dt/7200)
        state['updated']=time.time()
        return state
    def reserve(self,kind,owner,character,units,settings):
        if not settings.paid_enabled: raise ValueError('PAID_CALLS_DISABLED')
        day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
        start=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()
        with self.db:
            # Admission and reservation must be atomic even if a maintenance
            # process runs alongside the single-worker gateway.
            self.db.execute('BEGIN IMMEDIATE')
            if settings.enforce_conversation_limits:
                used=self.db.execute("SELECT count(*) FROM usage WHERE created>=? AND status!='not_sent'",(start,)).fetchone()[0]
                if used>=settings.max_daily_calls:raise ValueError('DAILY_CALL_LIMIT')
            limit={'tts':settings.max_daily_tts_characters,'asr':settings.max_daily_asr_seconds,'voice_design':settings.max_voice_designs}.get(kind)
            if limit is not None and (kind=='voice_design' or settings.enforce_conversation_limits):
                since=0 if kind=='voice_design' else start
                count=self.db.execute('SELECT coalesce(sum(reserved),0) FROM usage WHERE kind=? AND created>=?',(kind,since)).fetchone()[0]
                if count+units>limit:raise ValueError('USAGE_LIMIT_'+kind.upper())
            return self.db.execute('INSERT INTO usage(kind,owner,character,reserved,units,status,metrics,created) VALUES(?,?,?,?,?,?,?,?)',(kind,owner,character,units,0,'reserved','{}',time.time())).lastrowid
    def interrupt(self,owner,character,id):
        with self.db:
            self.db.execute("UPDATE requests SET status='interrupted' WHERE owner=? AND character=? AND id=? AND result IS NULL",(owner,character,id))
    def usage(self,id,status,metrics=None,units=None):
        with self.db:
            self.db.execute('UPDATE usage SET status=?,metrics=?,units=coalesce(?,units) WHERE id=?',(status,dump(metrics or {}),units,id))
            if status in ('completed','not_sent') and units is not None:self.db.execute('UPDATE usage SET reserved=? WHERE id=?',(units,id))
