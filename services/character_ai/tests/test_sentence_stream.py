import asyncio,json,uuid
import pytest
from services.character_ai.tests.test_reaction_pool import setup
from services.character_ai.stream_wire import Objects,beat,feedback
from services.character_ai.tests.test_prepared_handoff import entry_request,until
from services.character_ai.schemas import PreparationRequest

def test_object_stream_handles_quotes_unicode_and_chunk_boundaries():
    parser=Objects();values=[]
    raw=json.dumps({'say':'Hmm… "a flower"?','asides':[['I am curious.','after']]},ensure_ascii=False)+'\n'+json.dumps({'focus':'naming'})
    for c in raw:values.extend(parser.feed(c))
    assert values[0]['say']=='Hmm… "a flower"?' and values[1]['focus']=='naming'
    assert not parser.started
    reordered=Objects(nested=True).feed('{"focus":"hello","beats":[{"say":"A new hello!"}]}')
    assert reordered[0]['say']=='A new hello!'
    parser=Objects(nested=True)
    prefix='{"beats":[{"say":"Hello?","asides":[["I wonder.","before"]]}'
    assert parser.feed(prefix)[0]['say']=='Hello?' and parser.started
    assert parser.feed('],"goal_feedback":{"evidence":"hello"}}')[0]['goal_feedback']['evidence']=='hello'
    b=beat(dict(say='你好，今天想聊什么？',asides=[['不合规','bad-stage']],state={'junk':1}),1)
    assert b.dialogue.text=='你好，今天想聊什么？' and not b.asides
    with pytest.raises(ValueError):beat(dict(say={'bad':'text'}),1)
    assert feedback(dict(affection=.03,evidence='invented'),'hello').affection==0

@pytest.mark.asyncio
async def test_first_audio_does_not_wait_for_second_sentence_or_metadata(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);tail=asyncio.Event();calls=[]
    async def source(*args):
        calls.append('stream')
        yield dict(say='你想一起为这颗星星想个名字吗？',mood='happy',asides=[['我很好奇你的答案。','before']])
        await tail.wait()
        yield dict(say='也许可以从你喜欢的颜色开始找灵感。',asides=[['我想听听你的偏好。','after']])
        yield dict(focus='name a star',goal_feedback=dict(evidence='取名字',affection=.01))
    provider.stream_beats=source
    req=request.model_copy(update=dict(request_id=uuid.uuid4(),text='取名字',trigger='user_message',timeline_reply=True,parallel_performance=True))
    events=[]
    async with asyncio.timeout(2):
        async for item in engine.reply('u',req):
            events.append(item)
            if item['type']=='segment.audio.chunk' and not tail.is_set():tail.set()
    assert tail.is_set() and calls==['stream']
    first=next(e for e in events if e['type']=='reply.narration.ready')
    final=next(e for e in events if e.get('core_complete'))
    assert len(first['script']['beats'])==1 and len(final['script']['beats'])==2
    assert first['script']['message_id']==final['script']['message_id']
    types=[e['type'] for e in events]
    assert types.index('reply.narration.ready')<types.index('segment.audio.started')
    assert store.history('u',req.character_id)[-1]['text']==final['script']['text']
    assert store.db.execute('select text from reply_novelty where message=?',(final['script']['message_id'],)).fetchone()[0]==final['script']['text']
    before=provider.calls[:]
    replay=[e async for e in engine.reply('u',req)]
    assert provider.calls==before and replay[0]['cached']
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_ready_clip_prefetch_is_private_context_bound_and_non_consuming(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    entry=entry_request(request);pool.prepare('u',entry)
    await until(lambda:any(j.done for j in pool.jobs.values()))
    request=PreparationRequest.model_validate(entry.model_dump(mode='json'))
    clips=pool.clips('u',request)
    assert clips and clips[0]['audio'][0]['data']
    assert not pool.clips('other',request)
    assert not pool.clips('u',request.model_copy(update=dict(preferences={'nickname':'different'})))
    cached=[c['id'] for c in clips]
    assert not pool.clips('u',request.model_copy(update=dict(cached_preparation_ids=cached)))
    assert all(r['status']=='ready' for r in pool.rows('u',request.character_id,pool.context_key('u',request)))
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_inflight_stream_commits_final_goal_feedback_once_after_early_audio(tmp_path,monkeypatch):
    from services.character_ai import goals
    store,provider,engine,pool,request=setup(tmp_path);tail=asyncio.Event();first=asyncio.Event();commits=[];initial=store.state('u',request.character_id)['happiness']
    async def source(*args):
        yield dict(say='要不要和我一起找一颗属于今晚的星星？')
        first.set();await tail.wait()
        yield dict(goal_feedback=dict(evidence='星星',affection=.02),focus='choose a star',state={'happiness':.04})
    async def commit(settings,req,plan):
        commits.append((plan.goal_feedback.affection,plan.response_focus));return {'version':1,'progress_version':1}
    monkeypatch.setattr(goals,'commit',commit);provider.stream_beats=source
    entry=entry_request(request).model_copy(update=dict(timeline_reply=True,parallel_performance=True))
    pool.prepare('u',entry);await first.wait();pool.active.clear()
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='appLaunch',text='星星',timeline_reply=True,parallel_performance=True))
    events=[]
    async with asyncio.timeout(2):
        async for e in engine.reply('u',actual):
            events.append(e)
            if e['type']=='segment.audio.chunk':
                assert not commits;tail.set()
    types=[e['type'] for e in events]
    assert types.index('reply.narration.ready')<types.index('segment.audio.started')
    assert commits==[(0.0,'choose a star')] # Event drafts cannot invent user progress.
    assert next(e for e in events if e.get('core_complete'))['script']['goal_state']['progress_version']==1
    assert store.state('u',request.character_id)['happiness']==pytest.approx(initial+.04,abs=1e-4)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_unpublished_copy_retries_with_private_correction_and_no_spoken_duplicate(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);calls=[]
    old='今晚我们一起给那颗最亮的星星想个名字吧。'
    store.message(str(uuid.uuid4()),'u',request.character_id,'old','assistant',dict(text=old))
    async def source(owner,char,context):
        calls.append(context)
        if len(calls)==1:yield dict(say=old)
        else:
            assert context['novelty_correction']['rejected_text']==old
            yield dict(say='如果用颜色来分辨星星，你会先留意金色还是银白色？')
    provider.stream_beats=source
    request=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='user_message',text='再聊聊星星',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    assert len(calls)==2
    assert all(e['script']['text']!=old for e in events if 'script' in e)
    assert len([e for e in events if e['type']=='reply.narration.ready'])==1
    assert '_stream_correction' not in request.model_dump()
    await pool.close();store.db.close()
