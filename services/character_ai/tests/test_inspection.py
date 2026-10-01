import json,uuid
import httpx
import pytest
from services.character_ai.app import create_app
from services.character_ai.config import Settings
from services.character_ai.diagnostics import record_request
from services.character_ai.inspection import report
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.profiles import PROFILES
from services.character_ai.prompts import PLANNER,NARRATOR
from services.character_ai.provider import Provider,structured_messages,structured_payload
from services.character_ai.public_profiles import public_catalog
from services.character_ai.schemas import Plan,Request
from services.character_ai.storage import Store


def test_public_cards_are_a_separate_explicit_allowlist():
    for p in public_catalog()['characters']:
        assert set(p)=={'id','name','invitation','story','occupation','world','traits','likes','tone','dialogueLanguage','scenarios','profileRevision'}
        assert p['traits']==PROFILES[p['id']]['personality']['traits']
        assert p['story'] and p['likes']
        assert all(secret not in json.dumps(p,ensure_ascii=False) for secret in PROFILES[p['id']]['secrets'])


def test_complete_inspection_is_read_only_and_owner_scoped(tmp_path):
    settings=Settings(data_dir=tmp_path,api_key='MUST-NOT-LEAK-API',admin_token='MUST-NOT-LEAK-ADMIN',client_token='MUST-NOT-LEAK-CLIENT')
    store=Store(tmp_path/'db');char='anime-kipfel'
    store.put('inspection_requests','other',char,[{'payload':'OTHER-ACCOUNT-PRIVATE'}])
    store.put('inspection_requests','u','anime-mamehinata',[{'payload':'OTHER-ROLE-PRIVATE'}])
    request=Request(request_id=uuid.uuid4(),character_id=char,trigger='appLaunch',preferences={'nickname':'小星'},memories=[dict(id='m',text='我喜欢薄荷绿')],wants_audio=False)
    before=list(store.db.iterdump())
    result=report(settings,Orchestrator(settings,store,None),'u',request)
    sections={s['id']:s['content'] for s in result['sections']}
    assert json.loads(sections['persona'])==PROFILES[char]
    assert json.loads(sections['prompts'])['planner']==PLANNER
    assert json.loads(sections['prompts'])['narrator']==NARRATOR
    context=json.loads(sections['context'])
    assert context['memories'][0]['content']=='我喜欢薄荷绿'
    assert context['preferences']['nickname']=='小星'
    expected=structured_payload(settings,'plan',structured_messages('plan',PLANNER,context,Plan))
    assert json.loads(sections['payload'])==expected
    assert 'def grounded(' in sections['rules-director']
    assert 'def spoken_text(' in sections['rules-speech_text']
    content=json.dumps(result,ensure_ascii=False)
    for forbidden in ('MUST-NOT-LEAK-API','MUST-NOT-LEAK-ADMIN','MUST-NOT-LEAK-CLIENT','OTHER-ACCOUNT-PRIVATE','OTHER-ROLE-PRIVATE'):
        assert forbidden not in content
    assert list(store.db.iterdump())==before
    store.db.close()


@pytest.mark.asyncio
async def test_inspector_disabled_by_default_and_auth_required(tmp_path):
    settings=Settings(data_dir=tmp_path,client_token='test-token',paid_enabled=False)
    app=create_app(settings)
    body=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',wants_audio=False).model_dump(mode='json')
    headers={'Authorization':'Bearer test-token','X-Starry-Installation':str(uuid.uuid4()),'X-Starry-Account':'tester'}
    path='/v1/testing/characters/anime-kipfel/inspector'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post(path,json=body,headers=headers)).status_code==404
        settings.enable_test_inspector=True
        assert (await client.post(path,json=body)).status_code==401
        response=await client.post(path,json=body,headers=headers)
        assert response.status_code==200 and response.json()['character_id']=='anime-kipfel'
        assert (await client.post(path.replace('kipfel','mamehinata'),json=body,headers=headers)).status_code==400
        public=await client.get('/v1/characters/anime-kipfel/profile',headers=headers)
        assert public.status_code==200 and 'voice_prompt' not in public.json()
        parallel=await client.post(path,json=body,headers={**headers,'X-Starry-Reply-Mode':'timeline-v2','X-Starry-Performance-Mode':'parallel-v1'})
        sections={s['id']:s['content'] for s in parallel.json()['sections']}
        assert 'SpokenPlan' not in sections['payload']  # Private schema titles are compacted.
        assert '"cues"' not in json.loads(sections['payload'])['messages'][0]['content']
        assert 'performance-payload' in sections
    assert app.state.store.db.execute('SELECT count(*) FROM usage').fetchone()[0]==0
    await app.state.engine.provider.close();app.state.store.db.close()


@pytest.mark.asyncio
async def test_trace_contains_the_actual_request_and_never_headers(tmp_path):
    settings=Settings(data_dir=tmp_path,api_key='SECRET-AUTH-VALUE',enable_test_inspector=True)
    store=Store(tmp_path/'db');sent=[]
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"beats":[{"beat_id":"b","dialogue":{"text":"你好。"}}]}'}}]})
    provider=Provider(settings,store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    await provider.structured('u','anime-kipfel','plan',PLANNER,{'user_message':'你好'},Plan)
    trace=store.get('inspection_requests','u','anime-kipfel')
    assert trace[0]['payload']==sent[0]
    assert 'SECRET-AUTH-VALUE' not in json.dumps(trace)
    for i in range(14):record_request(settings,store,'u','anime-kipfel','plan',{'index':i})
    assert len(store.get('inspection_requests','u','anime-kipfel'))==12
    settings.enable_test_inspector=False
    before=list(store.db.iterdump());record_request(settings,store,'u','anime-kipfel','plan',{})
    assert list(store.db.iterdump())==before
    await provider.close();store.db.close()


def test_scene_previews_are_distinct_while_persona_is_shared(tmp_path):
    settings=Settings(data_dir=tmp_path,paid_enabled=False)
    store=Store(tmp_path/'db')
    engine=Orchestrator(settings,store,None)
    contexts=[];personas=[]
    for trigger in ('user_message','appLaunch','characterSwitch','idle'):
        request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',trigger=trigger,wants_audio=False)
        result=report(settings,engine,'scene-review',request)
        ids=[section['id'] for section in result['sections']]
        assert len(ids)==len(set(ids))
        sections={s['id']:s['content'] for s in result['sections']}
        contexts.append(sections['context']);personas.append(sections['persona'])
        assert sections['persona']!=sections['prompts']!=sections['context']
        assert json.loads(sections['client'])['trigger']==trigger
    assert len(set(contexts))==4
    assert len(set(personas))==1
    assert store.db.execute('SELECT count(*) FROM usage').fetchone()[0]==0
    store.db.close()
