import asyncio,json,time,uuid
import pytest
from services.character_ai.schemas import Request,PreparationRequest,QuickReplyRequest,QuickReplyPlan,Plan
from services.character_ai.tests.test_reaction_pool import setup,Provider

async def until(condition):
    for _ in range(300):
        if condition():return
        await asyncio.sleep(.001)
    assert condition()

def entry_request(request):
    return PreparationRequest(**request.model_dump(exclude={'trigger'}),trigger='appLaunch',preparation_scope='entry')

@pytest.mark.asyncio
async def test_trigger_adopts_running_planner_without_a_second_generation(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);provider.block=asyncio.Event()
    entry=entry_request(request);pool.prepare('u',entry)
    await until(lambda:provider.calls.count('plan')==1)
    job=pool.find_job('u',request.character_id,pool.context_key('u',request),'app_launch')
    pool.active.clear() # Isolate handoff cost from the separately tested refill.
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='appLaunch',timeline_reply=True))
    async def collect():return [e async for e in engine.reply('u',actual)]
    pending=asyncio.create_task(collect())
    await until(lambda:job.claimed)
    assert provider.calls.count('plan')==1 and not pending.done()
    provider.block.set();events=await pending
    initial=next(e for e in events if e['type']=='reply.narration.ready')
    assert initial['prepared'] and initial['preparation_inflight']
    assert provider.calls.count('plan')==provider.calls.count('tts')==1
    assert len(store.history('u',request.character_id))==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_trigger_replays_first_pcm_then_streams_remaining_pcm_without_waiting_for_tts(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    gate=asyncio.Event();first=asyncio.Event()
    async def synthesize(*args):
        provider.calls.append('tts');yield b'\x00\x01'*200
        first.set();await gate.wait();yield b'\x02\x03'*200
    provider.synthesize=synthesize
    pool.prepare('u',entry_request(request));await first.wait();pool.active.clear()
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='appLaunch',timeline_reply=True))
    heard=asyncio.Event();events=[]
    async def collect():
        async for e in engine.reply('u',actual):
            events.append(e)
            if e['type']=='segment.audio.chunk':heard.set()
    pending=asyncio.create_task(collect());await asyncio.wait_for(heard.wait(),1)
    assert not gate.is_set() and not pending.done()
    assert len(store.history('u',request.character_id))==1
    gate.set();await pending
    assert len([e for e in events if e['type']=='segment.audio.chunk'])==2
    assert provider.calls.count('tts')==1
    await pool.close();store.db.close()

class ChoiceProvider(Provider):
    def __init__(self):super().__init__();self.inputs=[];self.answer_gate=None
    async def structured(self,owner,char,purpose,system,context,schema):
        if purpose=='suggestions':
            self.calls.append(purpose)
            return QuickReplyPlan(options=[dict(text='说说你的旅行愿望吧',likelihood=.3),
                dict(text='那你最喜欢哪种花呢',likelihood=.9),dict(text='给雨声配个旋律怎么样',likelihood=.6)])
        if purpose=='plan' and context.get('user_message'):
            self.calls.append(purpose);text=context['user_message'];self.inputs.append(text)
            if self.answer_gate:await self.answer_gate.wait()
            lines={'那你最喜欢哪种花呢':'我偏爱铃兰，细小的花朵像藏着一串清脆的声音。',
                '给雨声配个旋律怎么样':'咱们可以先打两下节拍，再用长长的音符把雨声接住。',
                '说说你的旅行愿望吧':'我想沿着海边走走，看看远处的船会往哪个方向去。'}
            return Plan(response_focus=text,beats=[dict(beat_id='b1',dialogue=dict(text=lines[text]))])
        return await super().structured(owner,char,purpose,system,context,schema)

def quick_setup(tmp_path):
    store,_,engine,pool,request=setup(tmp_path)
    provider=ChoiceProvider();engine.provider=provider
    source=str(uuid.uuid4());store.message(source,'u',request.character_id,'source','assistant',dict(text='我们可以聊花、雨声或者旅行，你想聊哪一个？',trigger='user_message'))
    body=QuickReplyRequest(**request.model_dump(),source_message_id=source)
    return store,provider,engine,pool,request,body

@pytest.mark.asyncio
@pytest.mark.parametrize('story',[False,True])
async def test_choices_rank_then_prepare_sequentially_publish_only_selected_pair(tmp_path,story):
    store,provider,engine,pool,request,body=quick_setup(tmp_path)
    if story:
        request.scene={'story_id':'rain-letter','story_revision':'1'}
        body.scene=dict(request.scene)
    pool.quick.prepare('u',body);await pool.quick.tasks[('u',request.character_id)]
    result=pool.quick.status('u',body);options=result['options']
    assert [o['likelihood'] for o in options]==[.9,.6,.3]
    assert provider.inputs==[o['text'] for o in options]
    assert len(store.history('u',request.character_id))==1
    assert not store.get('relationship','u',request.character_id)
    assert store.db.execute('SELECT count(*) FROM asset_usage').fetchone()[0]==0
    choice=options[1];before=len(provider.calls)
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='story' if story else 'user_message',text=choice['text'],quick_reply_id=uuid.UUID(choice['id']),timeline_reply=True))
    events=[e async for e in engine.reply('u',actual)]
    assert events[0]['prepared'] and len(provider.calls)==before
    history=store.history('u',request.character_id)
    assert [m['role'] for m in history]==['assistant','user','assistant']
    assert history[-2]['text']==choice['text'] and history[-1]['text']==events[0]['script']['text']
    assert not pool.quick.saved('u',body)
    assert not store.db.execute("SELECT id FROM reaction_drafts WHERE kind LIKE 'quick:%' AND status!='used'").fetchall()
    assert len(list((tmp_path/'audio').glob('*.pcm')))==1
    replay=[e async for e in engine.reply('u',actual)]
    assert replay[0]['cached'] and len(provider.calls)==before
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_lower_rank_selection_promotes_pending_branch_and_cancels_unused_work(tmp_path):
    store,provider,engine,pool,request,body=quick_setup(tmp_path);provider.answer_gate=asyncio.Event()
    pool.quick.prepare('u',body)
    await until(lambda:len(provider.inputs)==1)
    options=pool.quick.status('u',body)['options'];choice=options[2]
    actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='user_message',text=choice['text'],quick_reply_id=uuid.UUID(choice['id']),timeline_reply=True))
    async def collect():return [e async for e in engine.reply('u',actual)]
    pending=asyncio.create_task(collect())
    await until(lambda:choice['text'] in provider.inputs)
    assert provider.inputs==[options[0]['text'],choice['text']]
    assert len(store.history('u',request.character_id))==1
    provider.answer_gate.set();events=await pending
    initial=next(e for e in events if e['type']=='reply.narration.ready')
    assert initial['preparation_inflight']
    assert provider.inputs.count(choice['text'])==1
    assert len(store.history('u',request.character_id))==3
    assert not pool.quick.saved('u',body)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_stale_or_edited_choices_never_consume_a_mismatched_answer(tmp_path):
    store,provider,engine,pool,request,body=quick_setup(tmp_path)
    pool.quick.prepare('u',body);await pool.quick.tasks[('u',request.character_id)]
    choice=pool.quick.status('u',body)['options'][0]
    actual=request.model_copy(update=dict(trigger='user_message',text=choice['text']+'还有呢',quick_reply_id=uuid.UUID(choice['id'])))
    assert pool.claim('u',actual) is None
    actual.text=choice['text']
    assert not pool.quick.valid_choice('different-user',actual)
    store.message(str(uuid.uuid4()),'u',request.character_id,'new','user',dict(text='换个话题吧'))
    assert pool.claim('u',actual) is None
    await pool.close();store.db.close()
