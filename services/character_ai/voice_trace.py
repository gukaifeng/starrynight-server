"""Bounded, content-free voice timelines. Durations use a monotonic clock.

Each background preparation owns a separate trace; no process-wide stopwatch or
request text is recorded. Parallel spans overlap and must never be summed.
"""
import asyncio
from contextlib import contextmanager, aclosing
from contextvars import ContextVar
import time, uuid, functools, json

class WorkerClock:
    """Pure ASGI entry timestamp; does not buffer or wrap the response stream."""
    def __init__(self, app):self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http','websocket'):scope['voice_started']=time.monotonic()
        await self.app(scope,receive,send)

current = ContextVar('voice_trace', default=None)

def identity(value=None):
    try:return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):return str(uuid.uuid4())

class Trace:
    def __init__(self, store, owner, character, kind, trace_id=None, request_id='', gateway=None):
        self.store, self.owner, self.character = store, owner, character
        self.id, self.kind, self.request_id = identity(trace_id), kind, request_id
        self.started, self.created = time.monotonic(), time.time()
        self.spans, self.marks, self.flags = [], {}, {}
        self.status, self.closed, self.dropped = 'running', False, 0
        self.gateway = gateway or {}
    def ms(self):return round((time.monotonic()-self.started)*1000, 3)
    def mark(self, name, once=True):
        if not self.closed and (not once or name not in self.marks):self.marks[name]=self.ms()
    def span(self, name, start, end, **metadata):
        if self.closed:return
        if len(self.spans)<1024:self.spans.append(dict(name=name,start_ms=round(start,3),duration_ms=round(max(0,end-start),3),**metadata))
        else:self.dropped+=1
    def snapshot(self):
        return dict(schema_version=1,trace_id=self.id,kind=self.kind,request_id=self.request_id,
            character=self.character,created=self.created,status=self.status,total_ms=self.ms(),
            gateway=self.gateway,marks=self.marks.copy(),flags=self.flags.copy(),spans=self.spans.copy(),dropped_spans=self.dropped)
    def save(self, status='completed'):
        if self.closed:return
        self.status=status;data=self.snapshot();self.closed=True
        # Instrumentation must never turn a successfully generated reply into
        # an error. The trace table is separate from the billing ledger.
        try:
            with self.store.db:
                self.store.db.execute('INSERT OR REPLACE INTO voice_traces VALUES(?,?,?,?,?,?)',
                    (self.id,self.owner,self.character,self.kind,json.dumps(data,separators=(',',':')),self.created))
                self.store.db.execute('DELETE FROM voice_traces WHERE created<? OR rowid IN (SELECT rowid FROM voice_traces ORDER BY created DESC LIMIT -1 OFFSET 5000)',(time.time()-14*86400,))
        except Exception:pass
        return data

@contextmanager
def scope(trace):
    token=current.set(trace)
    try:yield trace
    finally:current.reset(token)

@contextmanager
def span(name, **metadata):
    trace=current.get();start=trace.ms() if trace else 0
    status='completed'
    try:yield
    except BaseException as error:
        status='cancelled' if isinstance(error,(asyncio.CancelledError,GeneratorExit)) else 'failed'
        raise
    finally:
        if trace:trace.span(name,start,trace.ms(),status=status,**metadata)

def mark(name):
    if trace:=current.get():trace.mark(name)

def flag(name,value):
    if trace:=current.get():trace.flags[name]=value

def http_events(purpose, **metadata):
    # HTTPcore's documented trace extension; discard info entirely, as it can
    # contain request headers, hostnames, credentials and response bodies.
    trace=current.get();pending={};requested=trace.ms() if trace else 0;dispatched=False
    async def callback(event, info):
        nonlocal dispatched
        if not trace or trace.closed:return
        name,_,state=event.rpartition('.')
        if state=='started':
            if not dispatched:
                trace.span('provider.'+purpose+'.dispatch_to_transport',requested,trace.ms(),**metadata)
                dispatched=True
            pending[name]=trace.ms()
        elif state in ('complete','failed') and name in pending:
            trace.span('provider.'+purpose+'.'+name,pending.pop(name),trace.ms(),status=state,**metadata)
    return {'trace':callback}

def timed(name):
    def decorate(function):
        @functools.wraps(function)
        async def call(*args,**kwargs):
            with span(name):return await function(*args,**kwargs)
        return call
    return decorate

async def source(trace, iterator):
    """Own context inside the producer task, including its cancellation path."""
    with scope(trace):
        trace.mark('producer_start')
        status='completed'
        try:
            async with aclosing(iterator):
                async for item in iterator:
                    kind=item.get('type','')
                    if item.get('message_id'):trace.flags['message_id']=item['message_id']
                    if item.get('script'):trace.flags['message_id']=item['script'].get('message_id','')
                    if kind=='reply.narration.ready':
                        trace.mark('text_ready')
                        for key in ('cached','prepared','preparation_inflight'):
                            if key in item:trace.flags[key]=item[key]
                    if kind=='segment.audio.chunk':trace.mark('first_audio_egress');trace.mark('last_audio_egress',False)
                    if kind in ('audio.error','reply.error'):status='failed'
                    yield {**item,'trace_id':trace.id,'server_at_ms':trace.ms()}
            data=trace.save(status)
            if data:yield dict(type='voice.trace',trace_id=trace.id,trace=data)
        except BaseException as error:
            trace.flags['error_type']=type(error).__name__
            trace.save('cancelled' if isinstance(error,(asyncio.CancelledError,GeneratorExit)) else 'failed')
            raise
