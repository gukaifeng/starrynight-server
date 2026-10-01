import asyncio,hashlib,hmac,json,time,uuid
import pytest,httpx
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Plan,Request,PreparationRequest,ModelInteraction
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.profiles import assets
from services.character_ai.parallel_performance import PerformancePlan
from services.character_ai.reaction_pool import ReactionPool,REACTIONS,SCENARIOS
from services.character_ai.speech_text import audio_key

# Test provider only. Production drafts always come from the paid AI provider.
LINES={
 'shake':['我的节奏全被打乱啦，这次换我出个谜题。','突然这么闹腾，是藏了什么好消息想告诉我？','等等，我要先抱住自己的小抱枕，才不被你逗笑。'],
 'pinch_in':['轻捏一下就想跑呀，我还没决定怎么反击呢。','偷偷捏我被抓到啦，罚你给恶作剧起个名字。','唔，你捏得我忍不住想笑，不能让你发现。'],
 'pinch_out':['扯了我的注意力就要负责，说说你的新念头吧。','又被轻扯一下，现在要认真挑件事情交给你做啦。','不许再扯了，我要把这笔账记在今天的玩笑本上。'],
 'first_meeting':['你好，我想认识你，可以告诉我怎么称呼你吗？','初次见面，愿意跟我分享一件你喜欢的小事吗？','我们从一个小问题开始吧，你更喜欢安静还是热闹？'],
 'app_launch':['你来了，我有个关于星星的奇怪想法想讲给你。','看见你打开这里，我就想跟你聊聊旅行的愿望。','我们换个角度想故事吧，如果能住在云上呢？'],
 'return':['又能接上话啦，你觉得雨声适不适合当节拍？','回来得巧，我想跟你商量一次想象中的野餐。','还有件小事想分享，我最在意故事结尾的余韵。'],
 'idle':['安静的时候我总想给窗边的小花起一个名字。','我忽然很好奇，你会怎样描述一片柔软的云？','要是风也会唱歌，我猜它会喜欢不一样的旋律。']}

class Provider:
    def __init__(self):self.calls=[];self.count={};self.block=None;self.closed=0
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose)
        if purpose=='performance':return PerformancePlan(cues=[])
        if self.block:
            try:await self.block.wait()
            finally:self.closed+=1
        kind=context.get('prepared_event_context',{}).get('kind') or context.get('interaction_context',{}).get('kind') or context['trigger']
        n=self.count.get(kind,0);self.count[kind]=n+1
        return Plan(response_focus=LINES[kind][n%3],beats=[dict(beat_id='b1',dialogue=dict(text=LINES[kind][n%3]),
            asides=[dict(text='我有点期待你的回应。',stage='middle')])],suggested_state_delta={'trust':.01},
            idle_decision='proactive_speech' if kind=='idle' else None)
    async def synthesize(self,*args):
        self.calls.append('tts');yield b'\x00\x01'*200
    async def close(self):pass

def setup(tmp_path,known=True):
    store=Store(tmp_path/'db');provider=Provider();engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    pool=ReactionPool(engine);engine.reactions=pool
    char='anime-kipfel';store.put('voice','system',char,dict(approved=True,voice_id='fixture'))
    if known:store.put('greetings','u',char,['这是以前发生过的测试问候。'])
    request=Request(request_id=uuid.uuid4(),character_id=char,trigger='idle',available_assets=[a['asset_id'] for a in assets(char)])
    return store,provider,engine,pool,request

async def ready(pool,request,owner='u'):
    pool.prepare(owner,request)
    await pool.tasks[(owner,request.character_id)]
    expected={kind:1 if kind in pool.eligible(owner,request) else 0 for kind in SCENARIOS}
    assert pool.status(owner,request)['ready']==expected

@pytest.mark.asyncio
async def test_prepare_has_no_history_state_memory_cooldown_or_asset_usage_side_effects(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    await ready(pool,request)
    assert provider.calls.count('plan')==provider.calls.count('tts')==6
    for table in ('messages','requests','memories','reply_novelty','asset_usage'):
        assert store.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table
    for kind in ('state','relationship','shake_reaction','response_focus','vocals'):
        assert store.get(kind,'u',request.character_id) is None
    # Repeated prepare is free, and server restart can reuse fully generated PCM.
    await ready(pool,request);assert len(provider.calls)==18
    await pool.close()
    restored=ReactionPool(engine)
    assert all(restored.status('u',request)['ready'][kind]==1 for kind in pool.eligible('u',request))
    store.db.close()

@pytest.mark.asyncio
async def test_real_trigger_publishes_once_in_place_uses_ready_audio_and_refills_one(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);await ready(pool,request)
    before=len(provider.calls)
    trigger=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='model_pinched',timeline_reply=True,
        interaction=ModelInteraction(kind='pinch_in',intensity=.7)))
    events=[e async for e in engine.reply('u',trigger)]
    assert events[0]['prepared'] and any(e['type']=='segment.audio.chunk' for e in events)
    assert len(store.history('u',request.character_id))==1
    assert store.history('u',request.character_id)[0]['text']==events[0]['script']['text']
    assert store.get('relationship','u',request.character_id)['trust']==pytest.approx(.11)
    assert store.db.execute('SELECT count(*) FROM asset_usage').fetchone()[0]>0
    await pool.tasks[('u',request.character_id)]
    assert pool.status('u',request)['ready']['pinch_in']==1 and len(provider.calls)==before+3
    count=len(provider.calls)
    replay=[e async for e in engine.reply('u',trigger)]
    assert replay[0]['cached'] and len(provider.calls)==count
    assert len(store.history('u',request.character_id))==1
    # Another kind is independent, but the real physical interaction cooldown remains shared.
    again=trigger.model_copy(update=dict(request_id=uuid.uuid4(),interaction=ModelInteraction(kind='pinch_out',intensity=.7)))
    cooldown=[e async for e in engine.reply('u',again)]
    assert len(cooldown)==1 and cooldown[0]['type']=='reply.completed'
    assert pool.status('u',request)['ready']['pinch_out']==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_failure_backoff_does_not_block_other_scenarios_immediate_refill(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    original=provider.structured
    async def with_failed_shake(owner,char,purpose,system,context,schema):
        if purpose=='plan' and context.get('prepared_event_context',{}).get('kind')=='shake':
            raise TimeoutError('test one unavailable scenario')
        return await original(owner,char,purpose,system,context,schema)
    provider.structured=with_failed_shake
    pool.prepare('u',request);await pool.tasks[('u',request.character_id)]
    assert pool.status('u',request)['ready']['shake']==0
    assert pool.status('u',request)['ready']['pinch_in']==1
    trigger=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger='model_pinched',timeline_reply=True,
        interaction=ModelInteraction(kind='pinch_in',intensity=.7)))
    events=[e async for e in engine.reply('u',trigger)]
    assert events[0]['prepared']
    await pool.tasks[('u',request.character_id)]
    assert provider.count['pinch_in']==2
    assert pool.status('u',request)['ready']['pinch_in']==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_context_voice_expiry_and_owner_isolation(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);await ready(pool,request)
    assert all(v==0 for v in pool.status('other',request)['ready'].values())
    changed=request.model_copy(update={'preferences':{'nickname':'新的称呼'}})
    assert all(v==0 for v in pool.status('u',changed)['ready'].values())
    changed=request.model_copy(update={'available_assets':[]})
    assert all(v==0 for v in pool.status('u',changed)['ready'].values())
    store.message(str(uuid.uuid4()),'u',request.character_id,'new','user',dict(text='现在换一个话题吧。'))
    assert all(v==0 for v in pool.status('u',request)['ready'].values())
    store.db.execute('DELETE FROM messages');store.db.commit()
    store.put('voice','system',request.character_id,dict(approved=True,voice_id='new-voice'))
    assert all(v==0 for v in pool.status('u',request)['ready'].values())
    store.put('voice','system',request.character_id,dict(approved=True,voice_id='fixture'))
    store.db.execute("UPDATE reaction_drafts SET expires=?",(time.time()-1,));store.db.commit()
    assert all(v==0 for v in pool.status('u',request)['ready'].values())
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_pause_cancels_children_and_old_lease_cannot_cancel_new_session(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);provider.block=asyncio.Event()
    pool.prepare('u',request)
    for _ in range(30):
        if provider.calls.count('plan')>=2:break
        await asyncio.sleep(0)
    newer=request.model_copy(update={'request_id':uuid.uuid4()});pool.prepare('u',newer)
    await pool.pause('u',request.character_id,lease=str(request.request_id))
    assert pool.status('u',newer)['preparing']
    await pool.pause('u',request.character_id,lease=str(newer.request_id))
    assert provider.closed==4 and not pool.status('u',newer)['preparing']
    assert not store.history('u',request.character_id)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_reaction_routes_are_authenticated_read_only_status_and_clear_unused_drafts(tmp_path):
    from services.character_ai.app import create_app
    provider=Provider();app=create_app(Settings(data_dir=tmp_path,client_token='fixture',paid_enabled=False,reaction_pool_size=0),provider)
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',trigger='idle')
    headers={'Authorization':'Bearer fixture','X-Starry-Installation':str(uuid.uuid4()),'X-Starry-Account':'tester'}
    path='/v1/conversations/anime-kipfel/reactions/'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post(path+'prepare',json=request.model_dump(mode='json'))).status_code==401
        status=await client.post(path+'status',json=request.model_dump(mode='json'),headers=headers)
        assert status.status_code==200 and status.json()['preparing'] is False and not provider.calls
        assert (await client.post(path.replace('kipfel','mamehinata')+'prepare',json=request.model_dump(mode='json'),headers=headers)).status_code==400
        prepared=await client.post(path+'prepare',json=request.model_dump(mode='json'),headers=headers)
        assert prepared.status_code==200
        await asyncio.sleep(0)
        assert (await client.post(path+'pause',json=request.model_dump(mode='json'),headers=headers)).status_code==200
        who=hmac.new(b'fixture',(headers['X-Starry-Installation']+'|tester').encode(),hashlib.sha256).hexdigest()
        script=dict(message_id=str(uuid.uuid4()),beats=[dict(beat_id='b1')])
        store=app.state.store;char=request.character_id
        store.put('voice','system',char,dict(approved=True,voice_id='fixture'))
        folder=tmp_path/'audio';folder.mkdir()
        pcm=folder/(audio_key(who,char,'fixture',script['message_id'],'b1')+'.pcm');pcm.write_bytes(b'\x00\x01')
        for account in (who,'another-account'):
            store.db.execute('INSERT INTO reaction_drafts VALUES(?,?,?,?,?,?,?,?,?)',
                (str(uuid.uuid4()),account,char,'idle','fixture','ready',json.dumps(dict(script=script,plan={})),time.time(),time.time()+100))
        store.db.commit()
        assert (await client.delete('/v1/conversations/anime-kipfel/messages',headers=headers)).status_code==200
        assert not pcm.exists()
        assert store.db.execute('SELECT owner FROM reaction_drafts').fetchall()[0]['owner']=='another-account'
    assert not provider.calls and not app.state.reactions.active
    await app.state.reactions.close();app.state.store.db.close()

@pytest.mark.asyncio
async def test_first_meeting_then_return_and_launch_are_distinct_and_used_only_at_entry(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path,known=False)
    entry=PreparationRequest(**request.model_dump(exclude={'trigger'}),trigger='characterSwitch',preparation_scope='entry')
    await ready(pool,entry)
    assert pool.status('u',entry)['ready']['first_meeting']==1
    assert not store.history('u',entry.character_id) and not store.get('greetings','u',entry.character_id)
    before=time.time()
    incoming=Request(**entry.model_dump(exclude={'preparation_scope','request_id','trigger'}),request_id=uuid.uuid4(),trigger='firstLaunch')
    incoming.timeline_reply=True
    events=[e async for e in engine.reply('u',incoming)]
    assert events[0]['prepared'] and events[0]['script']['trigger']=='firstLaunch'
    assert store.db.execute('SELECT min(created) FROM messages').fetchone()[0]>=before
    assert len(store.get('greetings','u',entry.character_id))==1
    await pool.tasks[('u',entry.character_id)]
    status=pool.status('u',request)['ready']
    assert status['first_meeting']==0 and status['app_launch']==status['return']==1
    for trigger,kind in [('characterSwitch','return'),('appLaunch','app_launch')]:
        actual=request.model_copy(update=dict(request_id=uuid.uuid4(),trigger=trigger,timeline_reply=True))
        events=[e async for e in engine.reply('u',actual)]
        assert events[0]['prepared'] and events[0]['script']['text'] in LINES[kind]
        await pool.tasks[('u',request.character_id)]
    assert len(store.history('u',request.character_id))==3
    assert len({m['text'] for m in store.history('u',request.character_id)})==3
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_foreground_preempts_speculation_without_touching_another_account(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path);provider.block=asyncio.Event()
    pool.prepare('u',request)
    for _ in range(30):
        if provider.calls.count('plan')>=2:break
        await asyncio.sleep(0)
    await pool.yield_to_reply('other')
    assert pool.status('u',request)['preparing']
    await pool.yield_to_reply('u')
    assert provider.closed==4 and not pool.status('u',request)['preparing']
    assert not store.history('u',request.character_id)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_idle_drafts_obey_real_silence_gate_and_follow_latest_user_turn(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    store.message('user-1','u',request.character_id,'user-1','user',dict(text='我们聊聊花吧。'))
    await ready(pool,request)
    store.put('proactive','u',request.character_id,dict(last=time.time(),unanswered=0))
    blocked=request.model_copy(update=dict(request_id=uuid.uuid4(),timeline_reply=True))
    assert [e['type'] async for e in engine.reply('u',blocked)]==['reply.completed']
    assert pool.status('u',request)['ready']['idle']==1
    store.put('proactive','u',request.character_id,dict(last=time.time()-180,unanswered=0))
    actual=blocked.model_copy(update={'request_id':uuid.uuid4()})
    events=[e async for e in engine.reply('u',actual)]
    assert events[0]['prepared'] and events[0]['script']['text'] in LINES['idle']
    assert [m['role'] for m in store.history('u',request.character_id)]==['user','assistant']
    assert store.get('proactive','u',request.character_id)['unanswered']==1
    await pool.tasks[('u',request.character_id)]
    assert pool.status('u',request)['ready']['idle']==1
    await pool.close();store.db.close()
