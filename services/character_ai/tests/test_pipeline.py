import asyncio, json, uuid
import httpx, pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Plan, Narration, NarrationResult, Request
from services.character_ai.director import Director, grounded
from services.character_ai.profiles import assets
from services.character_ai.provider import speech_input
from services.character_ai.provider import sse_events
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.asr import Transcript

@pytest.fixture
def setup(tmp_path):
    settings=Settings(data_dir=tmp_path,client_token='test-client',admin_token='test-admin',paid_enabled=False)
    return settings,Store(tmp_path/'test.sqlite3')

class FakeProvider:
    """Test-only transport double. Production has no mock/fallback switch."""
    def __init__(self):self.calls=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose)
        if purpose=='plan':
            return Plan.model_validate(dict(beats=[dict(beat_id='b1',dialogue=dict(text='听到了，我们慢慢聊。'),
                thought=dict(text='没有说出口的虚构心理',visibility='hidden'),performance=dict(expression_intent='soft_smile'))],
                suggested_state_delta={'closeness':.08,'trust':999,'injected':1}))
        return NarrationResult(narrations=[])
    async def synthesize(self,*args):
        self.calls.append('tts');yield b'\x01\x00'*2400
    async def close(self):pass

@pytest.mark.asyncio
async def test_pipeline_idempotency_and_scope(setup):
    settings,store=setup;provider=FakeProvider();engine=Orchestrator(settings,store,provider)
    char='anime-kipfel';store.put('voice','system',char,dict(voice_id='test',approved=True))
    request=Request(request_id=uuid.uuid4(),character_id=char,text='你好',available_assets=[a['asset_id'] for a in assets(char)])
    events=[e async for e in engine.reply('owner',request)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['beats'][0]['thought'] is None
    assert provider.calls==['plan','narration','tts']
    assert any(e['type']=='segment.audio.chunk' for e in events)
    before=provider.calls[:]
    replay=[e async for e in engine.reply('owner',request)]
    assert provider.calls==before and replay[-1]['type']=='reply.completed'
    assert len(store.history('owner',char))==2
    assert not store.history('other',char) and not store.history('owner','anime-mamehinata')
    relationship=store.get('relationship','owner',char)
    assert relationship['closeness']==pytest.approx(.13) and relationship['trust']==.1 and 'injected' not in relationship
    request.text='different'
    with pytest.raises(ValueError,match='REQUEST_ID_REUSED'):
        _=[e async for e in engine.reply('owner',request)]

def test_paid_guard_and_ambiguous_failures(setup):
    settings,store=setup
    with pytest.raises(ValueError,match='DISABLED'):store.reserve('plan','u','c',1,settings)
    settings.paid_enabled=True;settings.max_daily_calls=1;settings.enforce_conversation_limits=True
    job=store.reserve('plan','u','c',1,settings);store.usage(job,'interrupted_or_failed')
    with pytest.raises(ValueError,match='DAILY_CALL_LIMIT'):store.reserve('plan','u','c',1,settings)

def test_director_and_grounding(setup):
    _,store=setup;director=Director(store);char='anime-kipfel'
    allowed=[a['asset_id'] for a in assets(char)]
    assert director.resolve('u',char,'action','hug',.5,{}, {},allowed)==(None,'none')
    assert director.resolve('u',char,'expression','soft_smile',.5,{}, {},[])==(None,'none')
    face,level=director.resolve('u',char,'expression','soft_smile',.5,{}, {},allowed)
    resolved=[dict(beat_id='b',expression_asset=face,action_asset=None,grounding=level)]
    assert grounded(Narration(beat_id='b',mode='performed',text='她'+''.join(face['observable_effects'])+'。',visual_grounding='exact',evidence=face['observable_effects']),resolved)
    assert not grounded(Narration(beat_id='b',mode='performed',text='她走到你身边，伸手抱住你。',visual_grounding='exact',evidence=face['observable_effects']),resolved)
    assert not grounded(Narration(beat_id='b',mode='performed',text='笑了',visual_grounding='exact',evidence=['不存在的动作']),resolved)
    assert grounded(Narration(beat_id='b',mode='literary',text='短暂的停顿，让对话柔和下来。',visual_grounding='none'),resolved)
    assert not grounded(Narration(beat_id='b',mode='literary',text='午后三点半的暖光洒进面包房，她倚着窗台轻笑。',visual_grounding='none'),resolved)

def test_only_spoken_content_enters_tts():
    text,_=speech_input(dict(thought='secret',narrations=[dict(text='never speak this')],dialogue=dict(text='你好',speech=dict(emotion='neutral')),vocal_events=[dict(event='giggle')]))
    assert text=='[giggles]你好' and 'secret' not in text
    from services.character_ai.schemas import visible_thought, visible_text
    assert visible_thought('第一次正式问候，要让对方感受到温暖') is None
    assert visible_thought('我有点紧张，也有一点开心。')=='我有点紧张，也有一点开心。'
    assert visible_text('[excited][amazed][serious][empathetic]你好')=='你好'

def test_even_reviewed_appearance_facts_are_not_narrated(setup):
    from services.character_ai.profiles import PROFILES
    facts=PROFILES['anime-kipfel']['appearance_facts']
    resolved=[dict(beat_id='b',expression_asset=None,action_asset=None,grounding='none')]
    narration=Narration(beat_id='b',mode='literary',text=facts[0]+'。片刻停顿，话语轻柔。',visual_grounding='none',evidence=[facts[0]])
    assert not grounded(narration,resolved,facts)
    assert not grounded(narration,resolved,PROFILES['anime-mamehinata']['appearance_facts'])
    assert not grounded(narration.model_copy(update={'text':facts[0]+'，她走到你身边。'}),resolved,facts)
    assert not grounded(narration.model_copy(update={'text':'她有银色的长发。'}),resolved,facts)
    assert not grounded(narration.model_copy(update={'evidence':[]}),resolved,facts)
    assert not grounded(narration.model_copy(update={'text':'片刻停顿。'}),resolved,facts)
    assert grounded(narration.model_copy(update={'text':'片刻停顿，话语轻柔。','evidence':[]}),resolved,facts)

def test_appearance_is_removed_while_safe_conversational_pace_survives():
    from services.character_ai.director import grounded_excerpt
    facts=['她留着浅棕色的头发']
    resolved=[dict(beat_id='b1',expression_asset=None,action_asset=None,grounding='none')]
    original=Narration(beat_id='b1',mode='literary',text='她留着浅棕色的头发，在窗边透进来的光里显得特别柔和。',visual_grounding='none',evidence=facts)
    result=grounded_excerpt(original,resolved,facts)
    assert result is None
    rejected_prose=grounded_excerpt(original.model_copy(update={'text':'晨光穿过窗棂，浅棕发丝泛着暖意。'}),resolved,facts)
    assert rejected_prose is None
    safe=grounded_excerpt(original.model_copy(update={'text':'她留着浅棕色的头发。片刻停顿，话语轻柔。'}),resolved,facts)
    assert safe.text=='片刻停顿。话语轻柔。' and not safe.evidence
    assert grounded_excerpt(original.model_copy(update={'text':'她走到窗边，伸手抱住你。','evidence':[]}),resolved,facts) is None
    assert grounded_excerpt(original.model_copy(update={'mode':'performed'}),resolved,facts) is None
    assert grounded_excerpt(original.model_copy(update={'text':'她留着银白色的头发。','evidence':['她留着银白色的头发']}),resolved,facts) is None

@pytest.mark.asyncio
async def test_visible_thought_narration_dialogue_survive_storage_and_replay(setup):
    class LiteraryProvider(FakeProvider):
        async def structured(self,owner,char,purpose,system,context,schema):
            self.calls.append(purpose)
            if purpose=='plan':return Plan.model_validate(dict(beats=[dict(beat_id='b',thought=dict(text='我也想听听后面的故事。'),dialogue=dict(text='后来发生了什么？'))]))
            assert 'appearance_facts' not in context
            return NarrationResult(narrations=[Narration(beat_id='b',mode='literary',text='片刻停顿，话语轻柔。',visual_grounding='none',evidence=[])])
    settings,store=setup;provider=LiteraryProvider();engine=Orchestrator(settings,store,provider)
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='今天读了一本书',wants_audio=False,progressive_reply=True)
    events=[e async for e in engine.reply('u',request)]
    first=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    final=next(e['script'] for e in events if e['type']=='reply.script.updated')
    assert first['message_id']==final['message_id'] and len(store.history('u',request.character_id))==2
    assert final['beats'][0]['thought']=='我也想听听后面的故事。'
    assert final['beats'][0]['narrations'][0]['text']=='片刻停顿，话语轻柔。'
    assert final['text']=='后来发生了什么？'
    text,_=speech_input(final['beats'][0]);assert text=='后来发生了什么？'
    replay=[e async for e in engine.reply('u',request)]
    assert replay[0]['script']==final and provider.calls==['plan','narration']

def test_asr_partial_final_and_deduplication():
    transcript=Transcript()
    assert transcript.receive(dict(sentence_id=0,text='豆日',sentence_end=False))['type']=='asr.partial'
    assert transcript.receive(dict(sentence_id=0,text='豆日向',sentence_end=True))['text']=='豆日向'
    assert transcript.receive(dict(sentence_id=0,text='豆日向',sentence_end=True))['text']=='豆日向'
    assert transcript.receive(dict(sentence_id=1,text='你好',sentence_end=True))['text']=='豆日向你好'
    assert transcript.receive(dict(heartbeat=True)) is None

def test_model_localized_identifiers_are_canonical_without_paid_retry():
    plan=Plan.model_validate(dict(beats=[dict(beat_id='轻声回应',dialogue=dict(text='你好'))]))
    assert plan.beats[0].beat_id.startswith('beat_')
    assert plan.beats[0].dialogue.text=='你好'
    plan=Plan.model_validate(dict(beats=[dict(beat_id='b',thought='角色的小心思')]))
    assert plan.beats[0].thought.visibility=='visible'
    plan=Plan.model_validate(dict(beats=[dict(beat_id='b',dialogue=dict(text='你好',speech=dict(emotion='playful')))]))
    assert plan.beats[0].dialogue.speech.emotion=='happy'
    # Real provider output used the delivery name in both fields. Preserve the
    # intended playful delivery without spending another schema-repair request.
    plan=Plan.model_validate(dict(beats=[dict(beat_id='b',dialogue=dict(text='好呀',speech=dict(emotion='teasing',delivery='teasing')))]))
    assert plan.beats[0].dialogue.speech.emotion=='happy'
    assert plan.beats[0].dialogue.speech.delivery=='teasing'
    with pytest.raises(ValueError):
        Plan.model_validate(dict(beats=[dict(beat_id='b',dialogue=dict(text='你好',speech=dict(emotion='arbitrary_command')))]))

@pytest.mark.asyncio
async def test_multiline_stream_and_heartbeats():
    async def lines():
        for value in [': keepalive','event: result','data: {','data: "output": {"audio":{"data":"AAE="}}','data: }','','data: [DONE]','']:yield value
    values=[e async for e in sse_events(lines())]
    assert json.loads(values[0][1])['output']['audio']['data']=='AAE='
    assert values[1][1]=='[DONE]'

def test_budget_atomic_across_connections(setup):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    settings,store=setup;settings.paid_enabled=True;settings.max_daily_calls=1;settings.enforce_conversation_limits=True
    barrier=threading.Barrier(2)
    def reserve(_):
        second=Store(settings.data_dir/'test.sqlite3');barrier.wait()
        try:second.reserve('plan','u','c',1,settings);return 'admitted'
        except ValueError:return 'limited'
        finally:second.db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,range(2)))
    assert sorted(results)==['admitted','limited']

@pytest.mark.asyncio
async def test_auth_api_isolation_and_paid_disabled(setup):
    from services.character_ai.app import create_app
    settings,store=setup;provider=FakeProvider();app=create_app(settings,provider)
    headers={'Authorization':'Bearer test-client','X-Starry-Installation':str(uuid.uuid4()),'X-Starry-Account':'guest'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/health')).json()['revision']==5
        assert (await client.get('/v1/status')).status_code==401
        assert (await client.get('/v1/status',headers=headers)).status_code==200
        assert (await client.get('/v1/admin/usage',headers=headers)).status_code==401
        assert (await client.post('/v1/conversations/anime-kipfel/messages/'+str(uuid.uuid4())+'/audio',headers=headers)).status_code==404
        body=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='你好',wants_audio=False).model_dump(mode='json')
        response=await client.post('/v1/conversations/anime-mamehinata/messages',headers=headers,json=body)
        assert response.status_code==400 and not provider.calls
        response=await client.post('/v1/conversations/anime-kipfel/messages',headers=headers,json=body)
        assert response.status_code==200 and 'reply.completed' in response.text

@pytest.mark.asyncio
async def test_idle_without_user_costs_nothing(setup):
    settings,store=setup;provider=FakeProvider();engine=Orchestrator(settings,store,provider)
    req=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',trigger='idle')
    events=[e async for e in engine.reply('u',req)]
    assert not provider.calls and events[-1]['type']=='reply.completed'

@pytest.mark.asyncio
async def test_nested_plan_is_rejected_and_correction_is_bounded(setup):
    from services.character_ai.provider import Provider, ProviderError
    settings,store=setup;settings.paid_enabled=True
    malformed={'beats':[{'beat_id':'b1','dialogue':{'text':'结构检查','beats':[]}}]}
    attempts=[]
    def respond(request):
        attempts.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(malformed)}}],'usage':{'prompt_tokens':1,'completion_tokens':1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider=Provider(settings,store,client)
        with pytest.raises(ProviderError,match='STRUCTURE_INVALID'):
            await provider.structured('u','anime-mamehinata','plan','JSON',{},Plan)
    assert len(attempts)==2
    assert 'dialogue' in attempts[1]['messages'][-1]['content']
    assert store.db.execute('select count(*) from usage').fetchone()[0]==2
