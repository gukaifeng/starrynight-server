import json
import random
import uuid
import pytest
from services.character_ai import idle_presence
from services.character_ai.config import Settings
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.prompts import CORE_PLANNER
from services.character_ai.provider import structured_messages
from services.character_ai.parallel_performance import performance_context
from services.character_ai.reaction_pool import ReactionPool, event_task
from services.character_ai.schemas import Request, Plan
from services.character_ai.storage import Store


def setup(tmp_path,**values):
    store=Store(tmp_path/'db')
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,None)
    request=Request(request_id=uuid.uuid4(),character_id='anime-lime',trigger='idle',
                    wants_audio=False,timeline_reply=True,**values)
    return store,engine,request


def test_many_angles_rotate_only_when_spoken_and_are_owner_role_isolated(tmp_path,monkeypatch):
    rng=random.Random(44);monkeypatch.setattr(idle_presence.random,'choices',rng.choices)
    store,engine,request=setup(tmp_path)
    observed=set();family=None
    for i in range(150):
        before=list(store.db.iterdump())
        ctx=engine.context('a',request,persist=False)['idle_context']
        assert list(store.db.iterdump())==before  # Inspector/preparation cannot consume angles.
        angle=ctx['angle'];observed.add(angle['id'])
        assert angle['id'] not in ctx['recent_angles'][-4:]
        assert angle['family']!=family
        idle_presence.commit(store,'a',request.character_id,{'text':'fixture','idle_angle':angle['id']})
        family=angle['family']
    assert observed==set(idle_presence.BY_ID) and len(observed)==18
    assert engine.context('b',request,persist=False)['idle_context']['recent_angles']==[]
    other=request.model_copy(update={'character_id':'anime-kipfel'})
    assert engine.context('a',other,persist=False)['idle_context']['recent_angles']==[]
    assert 'English ONLY' in engine.context('a',request,persist=False)['language_contract']


def test_prepared_and_cold_share_rules_nickname_and_revision(tmp_path,monkeypatch):
    store,engine,request=setup(tmp_path,preferences={'nickname':'River','nicknameSource':'account'})
    context=engine.context('a',request,persist=False)
    assert context['preferences']['nickname']=='River'
    assert performance_context(context)['idle_context']['angle']==context['idle_context']['angle']
    assert idle_presence.TASK in event_task('idle')
    assert 'idle_context' in CORE_PLANNER and 'preferences.nickname' in CORE_PLANNER
    for prepared in (False,True):
        if prepared:context['prepared_event_context']={'kind':'idle','task':event_task('idle')}
        final_event=structured_messages('plan',CORE_PLANNER,context,Plan)[-1]['content']
        assert context['idle_context']['angle']['intention'] in final_event
        assert '不继续讲自己的背景故事' in final_event
    pool=ReactionPool(engine);old=pool.context_key('a',request)
    renamed=request.model_copy(update={'preferences':{'nickname':'Sky','nicknameSource':'character'}})
    assert pool.context_key('a',renamed)!=old
    monkeypatch.setattr(idle_presence,'REVISION','next-policy')
    assert pool.context_key('a',request)!=old


def test_busy_and_unanswered_turns_do_not_escalate_insecurity(tmp_path):
    store,engine,request=setup(tmp_path,recent_messages=[{'role':'user','text':'I am busy working.'}])
    for count in (0,1,2):
        store.put('proactive','a',request.character_id,{'unanswered':count})
        for _ in range(12):
            ctx=engine.context('a',request,persist=False)['idle_context']
            assert ctx['availability']=='busy'
            assert ctx['angle']['family'] in ('company','consideration')
    request.recent_messages=[]
    for _ in range(12):
        assert engine.context('a',request,persist=False)['idle_context']['angle']['family'] not in ('uncertainty','playful','warmth')


@pytest.mark.asyncio
async def test_explicit_quiet_request_never_calls_provider_or_prepares_idle(tmp_path):
    store,engine,request=setup(tmp_path,recent_messages=[{'role':'user','text':'我先忙一会，不要打扰我。'}])
    pool=ReactionPool(engine);engine.reactions=pool
    assert 'idle' not in pool.eligible('a',request)
    events=[e async for e in engine.reply('a',request)]
    assert [e['type'] for e in events]==['reply.completed']
    assert store.get('idle_presence','a',request.character_id) is None
    await pool.close()


@pytest.mark.asyncio
async def test_cached_idle_commits_the_generated_angle_not_the_trigger_selection(tmp_path):
    from services.character_ai.tests.test_reaction_pool import setup as pool_setup, ready
    store,provider,engine,pool,request=pool_setup(tmp_path)
    store.message(str(uuid.uuid4()),'u',request.character_id,'prior','user',dict(text='今天想随便聊聊。'))
    request=request.model_copy(update={'timeline_reply':True})
    await ready(pool,request)
    row=pool.rows('u',request.character_id,pool.context_key('u',request),'idle')[0]
    prepared=json.loads(row['data'])['script']
    assert store.get('idle_presence','u',request.character_id) is None
    before=len(provider.calls)
    events=[e async for e in engine.reply('u',request)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['message_id']==prepared['message_id']
    assert store.get('idle_presence','u',request.character_id)['recent_angles']==[prepared['idle_angle']]
    assert any(e['type']=='segment.audio.chunk' for e in events)
    await pool.tasks[('u',request.character_id)]
    assert len(provider.calls)==before+3  # Only one replacement: plan/performance/audio.
    replacement=json.loads(pool.rows('u',request.character_id,pool.context_key('u',request),'idle')[0]['data'])['script']
    assert replacement['idle_angle']!=prepared['idle_angle']
    await pool.close()


@pytest.mark.asyncio
async def test_live_idle_carries_intention_and_is_not_a_canned_line(tmp_path):
    store,engine,request=setup(tmp_path,recent_messages=[{'role':'user','text':'Let us talk about plants.'}])
    class Provider:
        async def structured(self,owner,char,purpose,system,context,schema):
            assert context['idle_context']['angle']['id'] in idle_presence.BY_ID
            return Plan(response_focus='The user’s current attention',idle_decision='proactive_speech',
                        beats=[dict(beat_id='b',dialogue={'text':'Has something caught your attention, or would you like a quiet moment?'})])
    engine.provider=Provider()
    events=[e async for e in engine.reply('a',request)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['idle_angle'] in idle_presence.BY_ID
    assert len(store.get('idle_presence','a',request.character_id)['recent_angles'])==1
