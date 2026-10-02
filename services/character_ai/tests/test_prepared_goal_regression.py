import asyncio,base64,json,uuid
import pytest
from services.character_ai import goals
from services.character_ai.preparation_gate import PreparationGate
from services.character_ai.schemas import PreparationRequest,ModelInteraction
from services.character_ai.tests.test_reaction_pool import setup,ready
from services.character_ai.tests.test_prepared_handoff import quick_setup
from services.character_ai.tests.test_goals import snapshot

def attach(store,request,value):
    goals.attach(request,{'x-starry-goal-snapshot':base64.urlsafe_b64encode(json.dumps(value).encode()).decode(),'x-starry-account':str(uuid.uuid4())},store,'u')

@pytest.mark.asyncio
async def test_committed_progress_is_shared_by_refill_status_and_next_real_header(tmp_path,monkeypatch):
    store,provider,engine,pool,request=setup(tmp_path)
    old=snapshot();new={**old,'progress_version':3,'branches':{'bond':dict(familiarity=.2,trust=.3,affection=.1,task_progress=0,milestones=[])}}
    attach(store,request,old);goals.committed(store,'u',request,new)
    await ready(pool,request);pool.active.clear()
    incoming=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='model_shaken',interaction=ModelInteraction(kind='shake',intensity=.7),timeline_reply=True))
    attach(store,incoming,new)
    assert pool.context_key('u',incoming)==pool.context_key('u',request)
    count=len(provider.calls)
    async def commit(*args):return new
    monkeypatch.setattr(goals,'commit',commit)
    events=[e async for e in engine.reply('u',incoming)]
    assert events[0]['prepared'] and any(e['type']=='segment.audio.chunk' for e in events)
    assert len(provider.calls)==count
    # A slow older status response cannot roll back the authoritative snapshot.
    attach(store,incoming,old);assert goals.effective(store,'u',incoming)['progress_version']==3
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_next_entry_prediction_preserves_active_generation(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);provider.block=asyncio.Event()
    pool.prepare('u',request)
    await asyncio.sleep(.01)
    current=[j for j in pool.jobs.values() if j.request.character_id==request.character_id]
    next_role=PreparationRequest(**request.model_copy(update={'character_id':'anime-mamehinata','trigger':'characterSwitch'}).model_dump(),preparation_scope='entry')
    pool.prepare('u',next_role);await asyncio.sleep(.01)
    assert pool.active['u']==request.character_id
    assert all(not j.task.cancelling() for j in current)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_goal_headers_do_not_turn_ready_quick_answer_into_a_new_generation(tmp_path,monkeypatch):
    store,provider,engine,pool,request,body=quick_setup(tmp_path)
    value=snapshot();attach(store,request,value);attach(store,body,value)
    pool.quick.prepare('u',body);await pool.quick.tasks[('u',request.character_id)]
    choice=pool.quick.status('u',body)['options'][0]
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='user_message',text=choice['text'],quick_reply_id=uuid.UUID(choice['id']),timeline_reply=True))
    attach(store,actual,value);count=len(provider.calls)
    async def commit(*args):return {**value,'progress_version':1}
    monkeypatch.setattr(goals,'commit',commit)
    events=[e async for e in engine.reply('u',actual)]
    assert events[0]['prepared'] and len(provider.calls)==count
    assert store.get('goal_snapshot','u',request.character_id)['progress_version']==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_background_priority_and_cancelled_slots():
    gate=PreparationGate(1);release=asyncio.Event();order=[]
    async def work(name,priority,wait=False):
        async with gate.acquire(priority):
            order.append(name)
            if wait:await release.wait()
    first=asyncio.create_task(work('running',2,True));await asyncio.sleep(0)
    idle=asyncio.create_task(work('idle',3));entry=asyncio.create_task(work('entry',1));quick=asyncio.create_task(work('quick',0))
    cancelled=asyncio.create_task(work('cancelled',0));await asyncio.sleep(0);cancelled.cancel()
    await asyncio.gather(cancelled,return_exceptions=True);release.set()
    await asyncio.gather(first,idle,entry,quick)
    assert order==['running','quick','entry','idle'] and gate.used==0
