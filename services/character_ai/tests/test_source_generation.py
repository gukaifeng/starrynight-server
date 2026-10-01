"""Source prompts and invisible quality recovery; all test dialogue is synthetic."""
import uuid
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.provider import structured_messages,structured_payload,planner_data,ProviderError
from services.character_ai.prompts import PLANNER
from services.character_ai.schemas import Beat,Plan,TimelinePlan,Request

class SequenceProvider:
    def __init__(self,*answers):self.answers=iter(answers);self.calls=[];self.spoken=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(context)
        answer=next(self.answers)
        if isinstance(answer,Exception):raise answer
        return Plan(response_focus=answer,beats=[Beat(beat_id='b',dialogue=dict(text=answer),asides=[dict(text='我也很期待。')])])
    async def synthesize(self,owner,char,beat,voice):
        self.spoken.append(beat['dialogue']['text']);yield b'\x00\x01'*100

OLD='你画的小花很漂亮，花瓣上的颜色也很温柔。'
NEW='你会给画作起名字吗？我想知道你最先想到的那个词。'

def setup(tmp_path,*answers):
    store=Store(tmp_path/'db');char='anime-kipfel';provider=SequenceProvider(*answers)
    store.message('old','owner',char,'r','assistant',dict(text=OLD))
    store.put('voice','system',char,dict(approved=True,voice_id='fixture'))
    engine=Orchestrator(Settings(data_dir=tmp_path,enable_test_inspector=True),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=char,text='再聊聊画画',timeline_reply=True)
    return store,provider,engine,req

def test_first_generation_uses_official_chat_roles_and_no_fake_opening_or_duplicate_corpus():
    context=dict(character_profile=dict(name='角色'),trigger='user_message',user_message='我又想起画画了',
        recent_messages=[dict(role='user',text='我喜欢画花'),dict(role='assistant',text=OLD)],
        novelty_context=dict(previous_lines_to_avoid=[OLD]*3),greeting_context=dict(previous_lines_to_avoid=[OLD]),reply_format='timeline-v2')
    messages=structured_messages('plan',PLANNER,context,TimelinePlan)
    assert [(m['role'],m['content']) for m in messages[1:]]==[('user','我喜欢画花'),('assistant',OLD),('user','我又想起画画了')]
    assert OLD not in messages[0]['content']
    for attempt in (0,1):
        payload=structured_payload(Settings(),'plan',messages,attempt)
        if attempt==0:assert payload['presence_penalty']>0 and payload['temperature']>=.8
        else:assert payload['temperature']==.2, 'Schema repair prioritizes valid controls; novelty is checked afterwards'
        assert payload['model']=='qwen-plus-character' and payload['response_format']=={'type':'json_object'}
    context['user_message']='我喜欢画花'
    assert '已经问过1次' in structured_messages('plan',PLANNER,context,TimelinePlan)[0]['content']

@pytest.mark.parametrize('trigger',['appLaunch','firstLaunch','firstMeeting','characterSwitch','idle','model_shaken','model_pinched'])
def test_proactive_event_is_new_input_not_replayed_user_question(trigger):
    context=dict(trigger=trigger,user_message='',recent_messages=[dict(role='user',text='过去的问题'),dict(role='assistant',text='过去的回答')])
    messages=structured_messages('plan',PLANNER,context,TimelinePlan)
    assert messages[-1]['content'].startswith('<app_event>') and trigger in messages[-1]['content']
    assert '过去的问题' not in messages[-1]['content']

def test_compact_capabilities_retain_every_group_and_contextual_only_choices():
    group=dict(group='new.author.group',choices=[dict(intent='dance',meaning='舞步',automatic=False)]*2)
    data=planner_data(dict(avatar_capability=dict(groups=[group])))
    assert data['avatar_capability']['groups']==[dict(group='new.author.group',choices={'dance':dict(meaning='舞步',automatic=False)})]

@pytest.mark.asyncio
async def test_two_revisions_are_invisible_and_only_fresh_final_reply_is_stored_spoken_and_replayed(tmp_path):
    store,provider,engine,req=setup(tmp_path,OLD,OLD,NEW)
    events=[e async for e in engine.reply('owner',req)]
    scripts=[e['script'] for e in events if e['type']=='reply.narration.ready']
    assert [s['text'] for s in scripts]==[NEW] and provider.spoken==[NEW]
    assert len(provider.calls)==3 and not any(e['type'] in ('reply.error','reply.warning') for e in events)
    assert [m['text'] for m in store.history('owner',req.character_id)].count(OLD)==1
    assert store.get('response_focus','owner',req.character_id)==[NEW], 'Rejected drafts never become future content goals'
    next_context=engine.context('owner',req,persist=False)
    assert next_context['recent_response_focus']==[NEW]
    assert not store.get('response_focus','other',req.character_id)
    replay=[e async for e in engine.reply('owner',req)]
    assert replay[0]['cached'] and replay[0]['script']==scripts[0] and len(provider.calls)==3

@pytest.mark.asyncio
async def test_semantic_relatedness_alone_cannot_reject_a_distinct_revised_answer(tmp_path):
    store,provider,engine,req=setup(tmp_path,'我喜欢这幅画里安静的感觉。',NEW)
    async def same_topic(*args):return dict(reason='meaning',score=.68,text=OLD)
    engine.semantic.match=same_topic
    events=[e async for e in engine.reply('owner',req)]
    assert next(e['script']['text'] for e in events if e['type']=='reply.narration.ready')==NEW
    assert len(provider.calls)==2
    review=store.get('novelty_review','owner',req.character_id)
    assert review['accepted'] and review['attempts'][-1]['semantic_hint'] and not review['attempts'][-1]['duplicate']

@pytest.mark.asyncio
async def test_high_similarity_still_revises_after_first_hint(tmp_path):
    store,provider,engine,req=setup(tmp_path,'换几个字仍讲同一件事情。','依然在讲那同一件事情。',NEW)
    async def similar_until_new(owner,text,trigger):
        return None if text==NEW else dict(reason='meaning',score=.94,text=OLD)
    engine.semantic.match=similar_until_new
    events=[e async for e in engine.reply('owner',req)]
    assert len(provider.calls)==3 and provider.spoken==[NEW]
    assert not any(e['type']=='reply.error' for e in events)

@pytest.mark.asyncio
async def test_atomic_publication_collision_gets_fresh_generation_in_same_request(tmp_path):
    store,provider,engine,req=setup(tmp_path,'原本新生成的台词，此刻被另一个请求抢先发布。',NEW)
    publish=store.publish_reply;first=True
    def collide(owner,char,rid,text,script):
        nonlocal first
        if first:
            first=False
            store.message('race',owner,'another-role','race','assistant',dict(text=script['text']))
        return publish(owner,char,rid,text,script)
    store.publish_reply=collide
    events=[e async for e in engine.reply('owner',req)]
    assert [e['script']['text'] for e in events if e['type']=='reply.narration.ready']==[NEW]
    assert len(provider.calls)==2 and provider.spoken==[NEW]

@pytest.mark.asyncio
async def test_ambiguous_provider_failure_never_triggers_automatic_paid_retry(tmp_path):
    store,provider,engine,req=setup(tmp_path,ProviderError('CONNECTION_FAILED'),NEW)
    with pytest.raises(ProviderError):_=[e async for e in engine.reply('owner',req)]
    assert len(provider.calls)==1 and not provider.spoken
