import asyncio, json, uuid
import pytest
from services.character_ai import voice_trace as vt
from services.character_ai.storage import Store

@pytest.mark.asyncio
async def test_parallel_contexts_and_content_free_http_events(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    async def run(owner):
        trace=vt.Trace(store,owner,'character','prepare:shake')
        with vt.scope(trace):
            callback=vt.http_events('tts',beat_id='b1')['trace']
            await callback('connection.start_tls.started',{'Authorization':'secret','text':'private dialogue'})
            await asyncio.sleep(.005)
            await callback('connection.start_tls.complete',{'request':'secret'})
            with vt.span('parallel.work'):await asyncio.sleep(.005)
            vt.mark('first_audio')
            return trace.save()
    a,b=await asyncio.gather(run('one'),run('two'))
    assert a['trace_id']!=b['trace_id']
    assert len(a['spans'])==len(b['spans'])==3
    assert a['marks']['first_audio']>=5
    serialized=json.dumps([a,b])
    assert 'secret' not in serialized and 'private dialogue' not in serialized
    assert vt.current.get() is None
    assert store.db.execute('SELECT count(*) FROM voice_traces').fetchone()[0]==2

@pytest.mark.asyncio
async def test_cancelled_stream_is_saved_without_fabricated_completion(tmp_path):
    store=Store(tmp_path/'state.sqlite3');trace=vt.Trace(store,'owner','character','reply')
    async def output():
        yield {'type':'segment.audio.chunk','data':'not stored'}
        await asyncio.sleep(100)
    first=[];ready=asyncio.Event()
    async def consume():
        async for item in vt.source(trace,output()):first.append(item);ready.set()
    pending=asyncio.create_task(consume());await ready.wait()
    assert first[0]['trace_id']==trace.id and first[0]['server_at_ms']>=0
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):await pending
    record=json.loads(store.db.execute('SELECT data FROM voice_traces WHERE id=?',(trace.id,)).fetchone()[0])
    assert record['status']=='cancelled' and 'first_audio_egress' in record['marks']
    assert 'not stored' not in json.dumps(record)

@pytest.mark.asyncio
async def test_trace_snapshot_correlates_and_counts_actual_wait(tmp_path):
    store=Store(tmp_path/'state.sqlite3');trace=vt.Trace(store,'owner','character','replay',str(uuid.uuid4()))
    async def output():
        with vt.span('audio.cache_read'):await asyncio.sleep(.015)
        yield {'type':'segment.audio.chunk','message_id':'message','data':'private pcm'}
        yield {'type':'segment.audio.ready'}
    items=[item async for item in vt.source(trace,output())]
    assert items[-1]['type']=='voice.trace'
    data=items[-1]['trace'];assert data['spans'][0]['duration_ms']>=10
    assert data['total_ms']>=data['marks']['first_audio_egress']
    assert data['flags']['message_id']=='message'
    for _ in range(1030):trace.spans.append({})
    # Same trace ID in another account must not overwrite the first account.
    other=vt.Trace(store,'other','character','reply',trace.id);other.save()
    assert store.db.execute('SELECT count(*) FROM voice_traces').fetchone()[0]==2
