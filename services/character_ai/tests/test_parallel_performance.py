"""Gate concurrency with events, not timing guesses or paid services."""
import asyncio
import uuid
from contextlib import aclosing
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Plan, CoreTimelinePlan, Request
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.profiles import assets
from services.character_ai.prompts import CORE_PLANNER, PERFORMER
from services.character_ai.provider import structured_messages
from services.character_ai.parallel_performance import PerformancePlan, performance_context, current_visuals, merge_visuals

class GatedProvider:
    def __init__(self):
        self.performance_started=asyncio.Event();self.release_visuals=asyncio.Event();self.release_audio=asyncio.Event()
        self.core_started=asyncio.Event();self.calls=[];self.closed=set();self.failure=False
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose)
        try:
            if purpose=='performance':
                self.performance_started.set()
                await self.release_visuals.wait()
                if self.failure:raise RuntimeError('optional task failed')
                choice=next(a for a in assets(char) if a['group']=='pose' and '坐' in a['label'] and a['speech_compatible'])
                return PerformancePlan(cues=[dict(group='pose',intent=choice['intent'])])
            assert purpose=='plan' and schema is CoreTimelinePlan
            self.core_started.set();await self.performance_started.wait()
            return Plan(response_focus='分享一个新的小想法',beats=[dict(beat_id='b1',dialogue=dict(text='好呀，我还想跟你分享一个小想法。',speech=dict(emotion='happy')),
                asides=[dict(text='我有些期待。',stage='middle')])])
        finally:self.closed.add(purpose)
    async def synthesize(self,*args):
        self.calls.append('tts')
        try:
            yield b'\x00\x01'*200
            await self.release_audio.wait()
        finally:self.closed.add('tts')

def setup(tmp_path):
    store=Store(tmp_path/'db');provider=GatedProvider()
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    char='anime-kipfel';store.put('voice','system',char,dict(approved=True,voice_id='fixture'))
    request=Request(request_id=uuid.uuid4(),character_id=char,text='坐下来和我聊聊吧。',timeline_reply=True,parallel_performance=True,
                    available_assets=[a['asset_id'] for a in assets(char)])
    return store,provider,engine,request

@pytest.mark.asyncio
async def test_core_and_tts_arrive_while_visual_generation_is_blocked(tmp_path):
    store,provider,engine,request=setup(tmp_path);events=[];original=None
    async with aclosing(engine.reply('u',request)) as stream:
        async for event in stream:
            events.append(event)
            if event['type']=='reply.narration.ready':
                assert not provider.release_visuals.is_set()
                original=event['script']
                assert any(p['kind']=='thought' for p in original['beats'][0]['parts'])
            if event['type']=='segment.audio.chunk':
                assert not provider.release_visuals.is_set()
                provider.release_visuals.set()
            if event['type']=='reply.visuals.updated':
                assert not provider.release_audio.is_set(), 'Visual delivery does not wait for audio completion'
                assert event['script']['text']==original['text']
                assert event['script']['beats'][0]['parts']==original['beats'][0]['parts']
                assert any(v['group']=='pose' for v in event['visuals'])
                provider.release_audio.set()
    kinds=[e['type'] for e in events]
    assert kinds.index('segment.audio.chunk')<kinds.index('reply.visuals.updated')<kinds.index('audio.completed')<kinds.index('reply.completed')
    assert provider.calls.count('plan')==provider.calls.count('performance')==provider.calls.count('tts')==1
    # Replaying an older delivery mode never bills or starts new workers.
    replay=[e async for e in engine.reply('u',request.model_copy(update={'parallel_performance':False}))]
    assert replay[0]['cached'] and replay[0]['script']['beats'][0]['visuals']!=original['beats'][0]['visuals']
    assert len(provider.calls)==3
    store.db.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('fail',[False,True])
async def test_missing_optional_output_cannot_fail_text_or_audio(tmp_path,fail):
    store,provider,engine,request=setup(tmp_path)
    engine.settings.performance_timeout_seconds=.03
    provider.release_audio.set()
    if fail:provider.failure=True;provider.release_visuals.set()
    events=[e async for e in engine.reply('u',request)]
    assert any(e['type']=='segment.audio.chunk' for e in events)
    assert events[-1]['type']=='reply.completed'
    assert not any(e['type'] in ('reply.error','reply.warning','reply.visuals.updated') for e in events)
    assert store.get('performance_review','u',request.character_id)['status']=='skipped'
    assert 'performance' in provider.closed
    store.db.close()

@pytest.mark.asyncio
async def test_disconnect_closes_audio_and_optional_worker_without_late_patch(tmp_path):
    store,provider,engine,request=setup(tmp_path)
    async with aclosing(engine.reply('u',request)) as stream:
        async for event in stream:
            if event['type']=='segment.audio.chunk':break
    assert {'plan','tts','performance'}<=provider.closed
    assert not list((tmp_path/'audio').glob('*.pcm'))
    assert store.db.execute('SELECT status FROM requests').fetchone()[0]=='completed'
    store.db.close()

@pytest.mark.asyncio
async def test_core_failure_cancels_the_still_waiting_visual_worker(tmp_path):
    store,provider,engine,request=setup(tmp_path);original=provider.structured
    async def fail(*args):
        if args[2]=='plan':
            await provider.performance_started.wait();raise RuntimeError('core failed')
        return await original(*args)
    provider.structured=fail
    with pytest.raises(RuntimeError,match='core failed'):
        _=[e async for e in engine.reply('u',request)]
    assert 'performance' in provider.closed and 'tts' not in provider.calls
    assert not store.history('u',request.character_id)
    store.db.close()

def test_core_prompt_does_not_contain_the_large_avatar_catalogue(tmp_path):
    store,provider,engine,request=setup(tmp_path);context=engine.context('u',request,persist=False)
    core=structured_messages('plan',CORE_PLANNER,context,CoreTimelinePlan)
    extra=structured_messages('performance',PERFORMER,performance_context(context),PerformancePlan)
    assert 'avatar_capability' not in core[0]['content']
    assert 'avatar_capability' in extra[-1]['content']
    assert '"cues"' not in core[0]['content']
    assert 'recent_response_focus' in core[0]['content']
    assert len(core[0]['content'])<8000
    store.db.close()

def test_late_same_group_cues_are_coalesced_to_current_phase():
    result=current_visuals([dict(group='ears',offset_ms=0,asset_id='a'),dict(group='ears',offset_ms=1200,asset_id='b'),
                           dict(group='ears',offset_ms=3600,asset_id='c'),dict(group='hands',offset_ms=0,asset_id='d')],2000)
    assert {v['asset_id'] for v in result}=={'b','c','d'}
    assert next(v for v in result if v['asset_id']=='c')['offset_ms']==1600

def test_late_ear_update_preserves_its_next_automatic_phase_and_other_groups():
    base=[dict(group='ears',offset_ms=0,asset_id='left'),dict(group='ears',offset_ms=2400,asset_id='wiggle'),
          dict(group='hands',offset_ms=2500,asset_id='wave')]
    extra=[dict(group='ears',offset_ms=0,asset_id='perk')]
    replay=merge_visuals(base,extra,1800)
    assert replay[0]==base[0]  # Already executed text/visual history remains true.
    assert base[2] in replay
    assert next(v['offset_ms'] for v in replay if v['asset_id']=='perk')==1800
    assert next(v['offset_ms'] for v in replay if v['asset_id']=='wiggle')==3000
    live=current_visuals([v for v in replay if v['group']=='ears'],1800)
    assert [(v['asset_id'],v['offset_ms']) for v in live]==[('perk',0),('wiggle',1200)]

@pytest.mark.asyncio
async def test_optional_patch_failure_does_not_interrupt_active_voice(tmp_path,monkeypatch):
    from services.character_ai import parallel_performance
    store,provider,engine,request=setup(tmp_path)
    def broken(*args,**kwargs):raise RuntimeError('optional resolver failed')
    monkeypatch.setattr(parallel_performance,'late_patch',broken)
    events=[]
    async for event in engine.reply('u',request):
        events.append(event)
        if event['type']=='segment.audio.chunk':
            provider.release_visuals.set();provider.release_audio.set()
    assert events[-1]['type']=='reply.completed'
    assert any(e['type']=='segment.audio.ready' for e in events)
    assert not any(e['type'] in ('reply.error','reply.warning') for e in events)
    assert store.get('performance_review','u',request.character_id)['status']=='patch_skipped'
    store.db.close()
