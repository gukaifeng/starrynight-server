import asyncio
import json
import uuid
from contextlib import aclosing

import httpx
import pytest
from fastapi import HTTPException

from services.character_ai.app import create_app
from services.character_ai.config import Settings
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.schemas import Plan, NarrationResult, Request
from services.character_ai.storage import Store
from services.character_ai.streams import TurnStreams


@pytest.mark.asyncio
@pytest.mark.parametrize('spec,send_failure', [('2.3',False),('2.4',False),('2.4',True)])
async def test_disconnect_releases_silent_upstream_immediately(spec,send_failure):
    slots=TurnStreams();closed=asyncio.Event();sent=asyncio.Event()
    async def upstream():
        try:
            yield {'type':'started'}
            await asyncio.Event().wait()  # No next write to detect disconnection.
        finally:
            await asyncio.sleep(0)  # Real asynchronous resource cleanup.
            closed.set()
    response=await slots.start('a','1',upstream)
    async def send(message):
        if message['type']=='http.response.body':
            sent.set()
            if send_failure:raise OSError('client disconnected')
    async def receive():
        await sent.wait()
        return {'type':'http.disconnect'}
    await asyncio.wait_for(response({'type':'http','asgi':{'spec_version':spec}},receive,send),1)
    assert closed.is_set() and not slots.active


@pytest.mark.asyncio
async def test_next_message_replaces_old_audio_without_waiting_or_cross_scope_cancel():
    slots=TurnStreams();closed=asyncio.Event();started=asyncio.Event()
    async def old():
        try:
            started.set()
            yield {'type':'audio'}
            await asyncio.Event().wait()
        finally:closed.set()
    first=await slots.start('owner:role','one',old)
    other=await slots.start('other:role','one',old)
    await started.wait()
    replacement=await asyncio.wait_for(slots.start('owner:role','two',old),1)
    assert closed.is_set() and first.job.task.done()
    assert not replacement.job.task.done() and not other.job.task.done()
    # A late old response cleanup cannot delete the new reservation.
    await first.job.close();slots.release('owner:role',first.job)
    assert slots.active['owner:role'][1] is replacement.job
    await slots.close();await asyncio.sleep(0)
    assert not slots.active


@pytest.mark.asyncio
async def test_duplicate_and_capacity_are_distinct_and_do_not_start_paid_work():
    slots=TurnStreams(capacity=1);called=[]
    async def old():
        called.append(1);await asyncio.Event().wait();yield {}
    response=await slots.start('a','one',old)
    await asyncio.sleep(0)
    with pytest.raises(HTTPException) as same:
        await slots.start('a','one',old)
    assert same.value.status_code==409 and same.value.detail=='TURN_IN_PROGRESS'
    with pytest.raises(HTTPException) as full:
        await slots.start('b','two',old)
    assert full.value.status_code==503 and full.value.detail=='SERVER_BUSY'
    assert called==[1]
    await response.job.close()


@pytest.mark.asyncio
async def test_cancel_before_producer_starts_releases_reservation():
    slots=TurnStreams();called=[]
    async def source():
        called.append(True);yield {'type':'started'}
    response=await slots.start('a','one',source)
    await response.job.close()
    assert not called and not slots.active


@pytest.mark.asyncio
async def test_disconnect_during_audio_closes_nested_provider_and_keeps_text(tmp_path):
    class AudioProvider(SlowProvider):
        def __init__(self):super().__init__();self.closed=asyncio.Event()
        async def synthesize(self,*args):
            try:
                yield b'\x00\x01'*100
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                self.closed.set()
    provider=AudioProvider();settings=Settings(data_dir=tmp_path,paid_enabled=False)
    store=Store(tmp_path/'test.sqlite3');engine=Orchestrator(settings,store,provider)
    store.put('voice','system','anime-kipfel',dict(approved=True,voice_id='test'))
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='你好',progressive_reply=True)
    async with aclosing(engine.reply('u',request)) as stream:
        async for item in stream:
            if item['type']=='segment.audio.chunk':
                await provider.narrating.wait()
                break
    assert provider.closed.is_set() and provider.cancelled
    assert not list((tmp_path/'audio').glob('*.pcm'))  # Partial audio isn't replayable.
    assert store.db.execute('SELECT status FROM requests').fetchone()[0]=='completed'
    assert store.history('u','anime-kipfel')[-1]['text']=='在呢。'
    store.db.close()


def test_normal_use_is_unlimited_but_metered_and_test_guard_remains(tmp_path):
    settings=Settings(data_dir=tmp_path,max_daily_calls=1,max_daily_tts_characters=1,max_daily_asr_seconds=1)
    store=Store(tmp_path/'test.sqlite3')
    for _ in range(70):store.reserve('plan','u','c',1,settings)
    store.reserve('tts','u','c',4000,settings);store.reserve('asr','u','c',200,settings)
    assert store.db.execute('SELECT count(*) FROM usage').fetchone()[0]==72
    settings.paid_enabled=False
    with pytest.raises(ValueError,match='PAID_CALLS_DISABLED'):store.reserve('plan','u','c',1,settings)
    settings.paid_enabled=True;settings.enforce_conversation_limits=True
    with pytest.raises(ValueError,match='DAILY_CALL_LIMIT'):store.reserve('plan','u','c',1,settings)
    store.db.close()


class SlowProvider:
    def __init__(self):
        self.narrating=asyncio.Event();self.release=asyncio.Event();self.cancelled=False;self.calls=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose)
        if purpose=='plan':return Plan.model_validate({'beats':[{'beat_id':'b1','dialogue':{'text':'在呢。'}}]})
        self.narrating.set()
        try:await self.release.wait()
        except asyncio.CancelledError:self.cancelled=True;raise
        return NarrationResult.model_validate({'narrations':[dict(beat_id='b1',mode='literary',text='短暂的停顿。',visual_grounding='none')]})
    async def synthesize(self,*args):
        self.calls.append('tts');yield b'\x00\x01'*100
    async def close(self):pass


@pytest.mark.asyncio
async def test_progressive_text_and_audio_do_not_wait_for_narration(tmp_path):
    settings=Settings(data_dir=tmp_path,paid_enabled=False)
    store=Store(tmp_path/'test.sqlite3');provider=SlowProvider();engine=Orchestrator(settings,store,provider)
    char='anime-kipfel';store.put('voice','system',char,dict(approved=True,voice_id='test'))
    request=Request(request_id=uuid.uuid4(),character_id=char,text='你好',progressive_reply=True)
    events=[]
    async with aclosing(engine.reply('owner',request)) as stream:
        async for item in stream:
            events.append(item)
            if item['type']=='reply.narration.ready':
                assert not provider.release.is_set() and item['script']['text']=='在呢。'
            if item['type']=='segment.audio.chunk':
                assert not provider.release.is_set()
                provider.release.set()
    assert [e['type'] for e in events].index('segment.audio.chunk')<[e['type'] for e in events].index('reply.script.updated')
    result=next(e['script'] for e in events if e['type']=='reply.script.updated')
    assert result['beats'][0]['narrations'] and len(store.history('owner',char))==2
    # Header negotiation must not change idempotency or add paid invocations.
    calls=provider.calls[:];request.progressive_reply=False
    replay=[e async for e in engine.reply('owner',request)]
    assert provider.calls==calls and replay[-1]['type']=='reply.completed'
    assert replay[0]['script']['beats'][0]['narrations']
    store.db.close()


@pytest.mark.asyncio
async def test_optional_narration_timeout_keeps_text_and_cancels_provider(tmp_path):
    settings=Settings(data_dir=tmp_path,paid_enabled=False,narration_timeout_seconds=.02)
    store=Store(tmp_path/'test.sqlite3');provider=SlowProvider();engine=Orchestrator(settings,store,provider)
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='你好',progressive_reply=True,wants_audio=False)
    events=await asyncio.wait_for(collect(engine.reply('u',request)),1)
    assert provider.cancelled and events[-1]['type']=='reply.completed'
    assert any(e.get('script',{}).get('text')=='在呢。' for e in events)
    assert not any(e['type']=='reply.error' for e in events)
    store.db.close()

@pytest.mark.asyncio
async def test_narration_arrives_while_tts_is_still_streaming_and_both_cancel(tmp_path):
    class StreamingProvider(SlowProvider):
        def __init__(self):super().__init__();self.audio_waiting=asyncio.Event();self.audio_cancelled=False
        async def synthesize(self,*args):
            yield b'\x00\x01'*100
            self.audio_waiting.set()
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:self.audio_cancelled=True;raise
    settings=Settings(data_dir=tmp_path,paid_enabled=False)
    store=Store(tmp_path/'test.sqlite3');provider=StreamingProvider();engine=Orchestrator(settings,store,provider)
    char='anime-kipfel';store.put('voice','system',char,dict(approved=True,voice_id='test'))
    request=Request(request_id=uuid.uuid4(),character_id=char,text='你好',progressive_reply=True)
    async with asyncio.timeout(2):
        async with aclosing(engine.reply('u',request)) as stream:
            async for item in stream:
                if item['type']=='segment.audio.chunk':provider.release.set()
                if item['type']=='reply.script.updated':
                    assert item['script']['beats'][0]['narrations']
                    await provider.audio_waiting.wait()
                    break
    assert provider.audio_cancelled
    assert len(store.history('u',char))==2
    store.db.close()


async def collect(source):return [event async for event in source]


@pytest.mark.asyncio
async def test_cancel_before_text_marks_request_interrupted_not_running(tmp_path):
    provider=SlowProvider();settings=Settings(data_dir=tmp_path,paid_enabled=False)
    store=Store(tmp_path/'test.sqlite3');engine=Orchestrator(settings,store,provider)
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='你好',wants_audio=False)
    task=asyncio.create_task(collect(engine.reply('u',request)))
    await provider.narrating.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    row=store.db.execute('SELECT status,result FROM requests').fetchone()
    assert row['status']=='interrupted' and row['result'] is None and provider.cancelled
    store.db.close()


@pytest.mark.asyncio
async def test_http_handoff_accepts_new_message_during_previous_narration(tmp_path):
    provider=SlowProvider();settings=Settings(data_dir=tmp_path,paid_enabled=False,client_token='test')
    app=create_app(settings,provider)
    headers={'Authorization':'Bearer test','X-Starry-Installation':str(uuid.uuid4()),'X-Starry-Account':'test'}
    char='anime-kipfel'
    def body():return Request(request_id=uuid.uuid4(),character_id=char,text='你好',wants_audio=False).model_dump(mode='json')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=asyncio.create_task(client.post('/v1/conversations/'+char+'/messages',headers=headers,json=body()))
        await asyncio.wait_for(provider.narrating.wait(),1)
        second=asyncio.create_task(client.post('/v1/conversations/'+char+'/messages',headers={**headers,'X-Starry-Reply-Mode':'progressive-v1'},json=body()))
        await asyncio.sleep(.02);provider.release.set()
        responses=await asyncio.wait_for(asyncio.gather(first,second),1)
    assert all(r.status_code==200 for r in responses) and provider.cancelled
    assert 'reply.completed' in responses[1].text and not app.state.turns.active
    assert list(app.state.store.db.execute("SELECT status FROM requests WHERE status='running'"))==[]
    app.state.store.db.close()
