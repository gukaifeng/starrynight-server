"""Synthetic speech only: quality recovery preserves billing and single-use PCM."""
import asyncio,uuid
import pytest
from services.character_ai import voice_trace as vt
from services.character_ai.schemas import Plan
from services.character_ai.provider import ProviderError,planner_data,streaming_payload
from services.character_ai.config import Settings
from services.character_ai.tests.test_reaction_pool import setup
from services.character_ai.tests.test_prepared_handoff import entry_request,until

OLD='今晚我们一起给那颗最亮的星星想个名字吧。'
NEW='如果用颜色来分辨星星，你会先留意金色还是银白色？'

def history(store,char):
    store.message('old','u',char,'old','assistant',dict(text=OLD))

@pytest.mark.asyncio
@pytest.mark.parametrize('prefixes',[1,2])
async def test_duplicate_lead_is_skipped_but_fresh_next_beat_streams_without_another_call(tmp_path,prefixes):
    store,provider,engine,pool,request=setup(tmp_path);history(store,request.character_id);calls=[]
    async def stream(*args):
        calls.append('stream')
        for _ in range(prefixes):yield dict(say=OLD)
        yield dict(say=NEW)
    provider.stream_beats=stream
    request=request.model_copy(update=dict(trigger='user_message',text='再聊聊星星',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    scripts=[e['script'] for e in events if e['type']=='reply.narration.ready']
    assert calls==['stream'] and [s['text'] for s in scripts]==[NEW]
    assert provider.calls.count('tts')==1 and 'plan' not in provider.calls
    assert [m['text'] for m in store.history('u',request.character_id)].count(OLD)==1
    assert store.history('u',request.character_id)[-1]['text']==NEW
    assert scripts[0]['beats'][0]['beat_id']=='b1'
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_nickname_only_duplicate_lead_does_not_discard_new_answer(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    store.message('old','u',request.character_id,'old','assistant',dict(text='哥哥～'))
    calls=[]
    async def stream(*args):
        calls.append('stream');yield dict(say='哥哥～');yield dict(say=NEW)
    provider.stream_beats=stream
    request=request.model_copy(update=dict(trigger='user_message',text='你觉得金色怎么样',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    assert calls==['stream'] and provider.calls.count('tts')==1
    assert [e['script']['text'] for e in events if e['type']=='reply.narration.ready']==[NEW]
    assert store.history('u',request.character_id)[-1]['text']==NEW
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_atomic_collision_before_first_delivery_never_exposes_an_uncommitted_beat(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);calls=[];publish=store.publish_reply
    collided='当前这句本来是新的，却恰好被另一角色抢先说了。'
    async def stream(*args):
        calls.append('stream');yield dict(say=collided if len(calls)==1 else NEW)
    first=True
    def collision(owner,char,rid,text,script,**kwargs):
        nonlocal first
        if first:
            first=False;store.message('race',owner,'another-role','race','assistant',dict(text=collided))
        return publish(owner,char,rid,text,script,**kwargs)
    provider.stream_beats=stream;store.publish_reply=collision
    request=request.model_copy(update=dict(trigger='user_message',text='聊聊星星',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    assert calls==['stream','stream'] and provider.calls.count('tts')==1
    assert all(e['script']['text']==NEW for e in events if e.get('script'))
    assert [m['text'] for m in store.history('u',request.character_id)]==['聊聊星星',NEW]
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_speculative_repeated_stream_uses_role_planner_and_ready_clip_is_free_to_consume(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);history(store,request.character_id);calls=[]
    async def stream(*args):calls.append('stream');yield dict(say=OLD)
    provider.stream_beats=stream
    entry=entry_request(request).model_copy(update=dict(timeline_reply=True,parallel_performance=True))
    pool.prepare('u',entry);await pool.tasks[('u',request.character_id)]
    assert calls==['stream'] and provider.calls.count('plan')==1
    assert pool.status('u',entry)['ready']['app_launch']==1
    clips=pool.clips('u',entry);assert len(clips)==1 and clips[0]['script']['text']!=OLD
    before=len(provider.calls);actual=entry.model_copy(update=dict(request_id=uuid.uuid4()))
    # A matching cached clip must not invoke any model or TTS for consumption.
    pool.active.clear()
    events=[e async for e in engine.reply('u',actual)]
    assert any(e.get('prepared') for e in events) and any(e['type']=='segment.audio.chunk' for e in events)
    assert len(provider.calls)==before
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_speculative_revisions_have_a_smaller_budget_and_leave_no_audio_or_transcript(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);history(store,request.character_id);calls=[]
    async def stream(*args):calls.append('stream');yield dict(say=OLD)
    structured=provider.structured
    async def role(owner,char,purpose,system,context,schema):
        if purpose!='plan':return await structured(owner,char,purpose,system,context,schema)
        calls.append('plan');return Plan(beats=[dict(beat_id='b1',dialogue=dict(text=OLD))])
    provider.stream_beats=stream;provider.structured=role
    entry=entry_request(request).model_copy(update=dict(timeline_reply=True,parallel_performance=True))
    pool.prepare('u',entry);await pool.tasks[('u',request.character_id)]
    assert calls==['stream','plan'] and 'tts' not in provider.calls
    assert not pool.clips('u',entry) and len(store.history('u',request.character_id))==1
    assert store.get('reaction_pool_review','u',request.character_id)['status']=='preparation_failed'
    await pool.close();store.db.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('trigger',['user_message','appLaunch','characterSwitch','model_shaken'])
async def test_three_known_quality_attempts_are_bounded_and_automatic_events_finish_quietly(tmp_path,trigger):
    from services.character_ai.schemas import ModelInteraction
    store,provider,engine,pool,request=setup(tmp_path);history(store,request.character_id);calls=[]
    async def stream(*args):calls.append('stream');yield dict(say=OLD)
    structured=provider.structured
    async def role(owner,char,purpose,system,context,schema):
        if purpose!='plan':return await structured(owner,char,purpose,system,context,schema)
        calls.append('plan');return Plan(beats=[dict(beat_id='b1',dialogue=dict(text=OLD))])
    provider.stream_beats=stream;provider.structured=role
    request=request.model_copy(update=dict(trigger=trigger,text='再聊聊星星' if trigger=='user_message' else '',
        interaction=ModelInteraction(kind='shake',intensity=.8) if trigger=='model_shaken' else None,
        timeline_reply=True,parallel_performance=True))
    events=[]
    if trigger=='user_message':
        with pytest.raises(ValueError,match='REPLY_UNAVAILABLE'):
            async for e in engine.reply('u',request):events.append(e)
    else:
        events=[e async for e in engine.reply('u',request)]
        assert events[-1]['type']=='reply.completed'
    assert calls==['stream','plan','plan']
    assert not any(e.get('script') for e in events) and 'tts' not in provider.calls
    assert len(store.history('u',request.character_id))==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_provider_failure_never_starts_a_billed_quality_retry(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);calls=[]
    async def stream(*args):
        calls.append('stream');raise ProviderError('PROVIDER_403_DENIED');yield
    provider.stream_beats=stream
    request=request.model_copy(update=dict(trigger='user_message',text='你好',timeline_reply=True,parallel_performance=True))
    with pytest.raises(ProviderError):_=[e async for e in engine.reply('u',request)]
    assert calls==['stream'] and 'plan' not in provider.calls and 'tts' not in provider.calls
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_accepted_speech_tail_failure_keeps_published_reply_without_a_second_generation(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);calls=[]
    async def stream(*args):
        calls.append('stream');yield dict(say=NEW);raise ProviderError('STREAM_INCOMPLETE')
    provider.stream_beats=stream
    request=request.model_copy(update=dict(trigger='user_message',text='聊聊颜色',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    assert calls==['stream'] and 'plan' not in provider.calls and provider.calls.count('tts')==1
    assert events[-1]['type']=='reply.completed' and store.history('u',request.character_id)[-1]['text']==NEW
    await pool.close();store.db.close()

def test_source_novelty_policy_is_retained_without_copying_old_speech_into_system():
    context=dict(recent_messages=[dict(role='assistant',text=OLD)],user_message='新问题',
        novelty_context=dict(instruction='保持有实质内容的新回应',previous_lines_to_avoid=[OLD]*3))
    data=planner_data(context);assert 'previous_lines_to_avoid' not in str(data)
    payload,_=streaming_payload(Settings(),context)
    assert '保持有实质内容的新回应' in payload['messages'][0]['content']
    assert OLD not in payload['messages'][0]['content']
    assert OLD in payload['messages'][1]['content']

@pytest.mark.asyncio
async def test_failed_trace_records_safe_domain_error_code_not_private_exception_text(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    async def fail(code):raise ValueError(code);yield
    for code in ('REPLY_UNAVAILABLE','private dialogue with spaces'):
        trace=vt.Trace(store,'u',request.character_id,'fixture')
        with pytest.raises(ValueError):_=[e async for e in vt.source(trace,fail(code))]
        assert trace.flags.get('error_code')==('REPLY_UNAVAILABLE' if code=='REPLY_UNAVAILABLE' else None)
    await pool.close();store.db.close()
