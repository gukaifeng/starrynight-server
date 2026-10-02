"""Real scheduling and strict wire checks, synthetic PCM; zero paid calls."""
import asyncio,json,uuid
import pytest
from services.character_ai.preparation_gate import PreparationGate
from services.character_ai.tests.test_prepared_handoff import entry_request,until
from services.character_ai.tests.test_reaction_pool import setup
from services.character_ai.provider import control_defaults,structured_messages
from services.character_ai.planner_wire import GoalSpokenPlan
from services.character_ai.schemas import CoreTimelinePlan,Plan,Beat
from services.character_ai.prompts import CORE_PLANNER
from services.character_ai.semantic_novelty import SemanticNovelty
from services.character_ai.config import Settings

@pytest.mark.asyncio
async def test_background_scenarios_leave_two_core_slots_for_quick_answers():
    gate=PreparationGate(4,quick_reserve=2);release=asyncio.Event();started=[]
    async def work(name,priority):
        async with gate.acquire(priority,key=name):
            started.append(name);await release.wait()
    tasks=[asyncio.create_task(work('scenario-'+str(i),2)) for i in range(6)]
    await until(lambda:len(started)==2)
    quick=[asyncio.create_task(work('quick-'+str(i),0)) for i in range(3)]
    await until(lambda:len(started)==4)
    assert started==['scenario-0','scenario-1','quick-0','quick-1']
    gate.promote('quick-2')
    await until(lambda:'quick-2' in started)
    assert gate.used==5 # Only one extra lane, for a real foreground selection.
    release.set();await asyncio.gather(*tasks,*quick)
    assert gate.used==gate.low_used==0 and not gate.entries

@pytest.mark.asyncio
async def test_cancelled_promoted_slot_is_released_exactly_once():
    gate=PreparationGate(1);release=asyncio.Event()
    async def work(key):
        async with gate.acquire(2,key=key):await release.wait()
    first=asyncio.create_task(work('first'));await asyncio.sleep(0)
    selected=asyncio.create_task(work('selected'));await asyncio.sleep(0)
    gate.promote('selected');await asyncio.sleep(0)
    assert gate.used==2 and gate.low_used==1
    selected.cancel();await asyncio.gather(selected,return_exceptions=True)
    assert gate.used==gate.low_used==1
    release.set();await first
    assert gate.used==gate.low_used==0

@pytest.mark.asyncio
async def test_complete_pcm_is_ready_and_slot_is_free_while_optional_visuals_wait(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    pool.slots=PreparationGate(1);visual_gate=asyncio.Event()
    original=provider.structured
    async def structured(*args):
        if args[2]=='plan':assert args[4]['speculative_generation'] is True
        if args[2]=='performance':await visual_gate.wait()
        return await original(*args)
    provider.structured=structured
    entry=entry_request(request);pool.prepare('u',entry)
    await until(lambda:bool(pool.rows('u',request.character_id,pool.context_key('u',entry),'app_launch')))
    job=next(j for j in pool.jobs.values() if j.kind=='app_launch')
    assert not job.done and pool.slots.used==0
    pool.active.clear()
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='appLaunch',timeline_reply=True))
    claim=pool.claim('u',actual)
    assert claim['audio_ready'] and claim['job'] is job
    output=pool.deliver('u',actual,engine.context('u',actual),claim)
    heard=False
    async for item in output:
        if item['type']=='reply.narration.ready':assert not item['preparation_inflight']
        if item['type']=='segment.audio.chunk':
            heard=True;visual_gate.set()
    assert heard and provider.calls.count('tts')==1
    await pool.close();store.db.close()

def test_missing_progress_controls_are_zero_not_another_role_generation():
    context=dict(trigger='user_message',user_message='Can we name the flower Starlight?',goal_context=dict(config_version=1))
    raw=json.dumps(dict(focus='naming a flower',beats=[dict(say='Hmm… Starlight fits it.',asides=[['I can picture the name.','after']])]))
    corrected,count=control_defaults(raw,GoalSpokenPlan,context)
    plan=GoalSpokenPlan.model_validate_json(corrected)
    assert count==5 and plan.goal_feedback.evidence==context['user_message']
    assert not any(getattr(plan.goal_feedback,k) for k in ('familiarity','trust','affection','task_progress'))
    assert plan.beats[0].say=='Hmm… Starlight fits it.'
    prompt=structured_messages('plan',CORE_PLANNER,context,CoreTimelinePlan)[0]['content']
    assert '"goal_feedback":{"familiarity":0' in prompt
    assert 'task_progress' in prompt and 'Schema中的字段' in prompt
    invalid=json.loads(raw);invalid['goal_feedback']=dict(familiarity=1,evidence='invented')
    corrected,_=control_defaults(json.dumps(invalid),GoalSpokenPlan,context)
    with pytest.raises(Exception):GoalSpokenPlan.model_validate_json(corrected)


def test_missing_evidence_cannot_turn_a_default_excerpt_into_progress():
    context=dict(user_message='Let us talk about flowers.')
    raw=dict(focus='flowers',beats=[dict(say='Hmm… which flower?',asides=[['I wonder which one.','after']])],
        goal_feedback=dict(familiarity=.02,affection=.03,milestone='date_agreed'))
    corrected,_=control_defaults(json.dumps(raw),GoalSpokenPlan,context)
    feedback=GoalSpokenPlan.model_validate_json(corrected).goal_feedback
    assert not any(getattr(feedback,key) for key in ('familiarity','trust','affection','task_progress'))
    assert feedback.milestone=='' and feedback.evidence==context['user_message']
    for invalid in (dict(familiarity=1),dict(unknown='ignored?')):
        raw['goal_feedback']=invalid
        corrected,count=control_defaults(json.dumps(raw),GoalSpokenPlan,context)
        assert count==0
        with pytest.raises(Exception):GoalSpokenPlan.model_validate_json(corrected)

@pytest.mark.asyncio
async def test_chinese_embedding_never_rejects_english_dialogue(tmp_path):
    store,_,_,pool,_=setup(tmp_path)
    semantic=SemanticNovelty(Settings(data_dir=tmp_path,semantic_novelty=True),store)
    def unexpected(*args):raise AssertionError('Chinese embedding invoked for English')
    semantic.embed=unexpected
    assert await semantic.match('u','Hmm… I would love to name the plant Starlight.') is None
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_repeated_optional_aside_does_not_regenerate_valid_dialogue(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    store.message('past','u',request.character_id,'past','assistant',dict(text='过去的不同话题。',beats=[dict(parts=[dict(kind='thought',text='我有点期待。')])]))
    calls=[]
    async def structured(*args):
        calls.append(args[2])
        return Plan(response_focus='new topic',beats=[Beat(beat_id='b1',dialogue=dict(text='你想先用哪种颜色画这幅画呢？'),asides=[dict(text='我有点期待。')])])
    provider.structured=structured
    request=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='user_message',text='画画吧',timeline_reply=True))
    events=[item async for item in engine.reply('u',request)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert calls==['plan']
    assert script['text']=='你想先用哪种颜色画这幅画呢？'
    assert all(p['text']!='我有点期待。' for p in script['beats'][0]['parts'])
    await pool.close();store.db.close()
