import asyncio
import hashlib
import hmac
import json
import uuid
import httpx
import pytest
from services.character_ai.app import create_app
from services.character_ai.config import Settings
from services.character_ai.provider import translation_payload,Provider,ProviderError
from services.character_ai.storage import Store

class Translator:
    calls = 0
    malformed = False
    async def translate_text(self, owner, character, text, target):
        self.calls += 1
        await asyncio.sleep(.01)
        return '' if self.malformed else 'translated: '+text

def fixture(tmp_path):
    provider=Translator();settings=Settings(data_dir=tmp_path,client_token='translation-test',paid_enabled=False)
    app=create_app(settings,provider);store=app.state.store
    install=str(uuid.uuid4());account='reader'
    headers={'Authorization':'Bearer translation-test','X-Starry-Installation':install,'X-Starry-Account':account}
    owner=hmac.new(b'translation-test',(install+'|'+account).encode(),hashlib.sha256).hexdigest()
    role='anime-kipfel';message=str(uuid.uuid4())
    parts=[dict(kind='dialogue',text='Good morning!\nDid you sleep well?',at=0),
           dict(kind='thought',text='I hope you did.',at=.5),dict(kind='narration',text='A gentle wave.',at=.7)]
    script=dict(message_id=message,text=parts[0]['text'],beats=[dict(beat_id='b',parts=parts)])
    store.message(message,owner,role,'fixture','assistant',script)
    body=dict(target_language='zh-Hans',segments=[dict(id=f'b.part.{i}',kind=s['kind'],text=s['text']) for i,s in enumerate(parts)])
    return app,provider,headers,owner,role,message,body

@pytest.mark.asyncio
async def test_translation_preserves_format_is_cached_and_owner_scoped(tmp_path):
    app,provider,headers,owner,role,message,body=fixture(tmp_path)
    path=f'/v1/conversations/{role}/messages/{message}/translation'
    before=app.state.store.history(owner,role)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        a,b=await asyncio.gather(*(client.post(path,headers=headers,json=body) for _ in range(2)))
        assert a.status_code==b.status_code==200 and a.json()==b.json() and provider.calls==4
        assert [s['kind'] for s in a.json()['segments']]==['dialogue','thought','narration']
        assert '\n' in a.json()['segments'][0]['text']
        assert app.state.store.history(owner,role)==before
        assert (await client.post(path,headers={**headers,'X-Starry-Account':'other'},json=body)).status_code==404
        altered=json.loads(json.dumps(body));altered['segments'][0]['text']='unowned content'
        assert (await client.post(path,headers=headers,json=altered)).status_code==409
        assert (await client.post(path,headers=headers,json={**body,'target_language':'de'})).status_code==422
        assert provider.calls==4
        assert (await client.post(path,headers=headers,json={**body,'target_language':'zh-Hant'})).status_code==200
        assert provider.calls==8
        assert (await client.delete(f'/v1/conversations/{role}?reset_id={uuid.uuid4()}',headers=headers)).status_code==200
        assert not app.state.store.db.execute("SELECT 1 FROM records WHERE owner=? AND character=? AND kind LIKE 'translation:%'",(owner,role)).fetchone()
        assert (await client.post(path,headers=headers,json=body)).status_code==404

@pytest.mark.asyncio
async def test_shape_errors_never_cache_or_replace_original(tmp_path):
    app,provider,headers,owner,role,message,body=fixture(tmp_path);provider.malformed=True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post(f'/v1/conversations/{role}/messages/{message}/translation',headers=headers,json=body)
        assert response.status_code==502
        assert not app.state.store.get('translation:'+message+':zh-Hans',owner,role)
        assert app.state.store.history(owner,role)[0]['text'].startswith('Good morning')

@pytest.mark.parametrize('code,name',[('zh-Hans','Chinese'),('zh-Hant','Traditional Chinese'),('en','English')])
def test_translation_uses_dedicated_mt_protocol(code,name):
    payload=translation_payload(Settings(),'Hmm… what about you?',code)
    assert payload['model']=='qwen-mt-flash'
    assert payload['translation_options']['source_lang']=='auto' and payload['translation_options']['target_lang']==name
    assert payload['messages']==[dict(role='user',content='Hmm… what about you?')]
    assert 'response_format' not in payload and 'enable_thinking' not in payload

@pytest.mark.asyncio
async def test_provider_rejects_truncated_translation_and_records_real_usage(tmp_path):
    store=Store(tmp_path/'db');settings=Settings(data_dir=tmp_path,api_key='fixture')
    seen=[]
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json=dict(id='fixture',choices=[dict(finish_reason='length',message=dict(content='incomplete'))],usage=dict(total_tokens=4)))
    provider=Provider(settings,store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(ProviderError,match='TRANSLATION_INCOMPLETE'):await provider.translate_text('u','c','short','en')
        assert len(seen)==1 and seen[0]['model']=='qwen-mt-flash'
        assert store.db.execute("SELECT status FROM usage").fetchone()[0]=='completed'
    finally:await provider.close();store.db.close()

@pytest.mark.asyncio
async def test_unpurchased_mt_is_probed_once_and_only_then_uses_fast_fallback(tmp_path):
    store=Store(tmp_path/'db');seen=[]
    def respond(request):
        data=json.loads(request.content);seen.append(data)
        if data['model']=='qwen-mt-flash':return httpx.Response(403,json={'error':{'code':'AccessDenied.Unpurchased'}})
        assert data['model']=='qwen-turbo' and data['enable_thinking'] is False
        return httpx.Response(200,json=dict(id='fixture',choices=[dict(message=dict(content='{"text":"你好……"}'))]))
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        results=await asyncio.gather(*(provider.translate_text('u','c','Hello…','zh-Hans') for _ in range(4)))
        assert results==['你好……']*4
        assert sum(p['model']=='qwen-mt-flash' for p in seen)==1
        assert store.get('translation_provider','system','')['active']=='qwen-turbo'
    finally:await provider.close();store.db.close()

@pytest.mark.asyncio
async def test_network_provider_errors_do_not_start_another_paid_translation(tmp_path):
    store=Store(tmp_path/'db');calls=[]
    def respond(request):
        calls.append(request);return httpx.Response(503,json={'error':{'code':'ServiceUnavailable'}})
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(ProviderError,match='503'):await provider.translate_text('u','c','Hello','en')
        assert len(calls)==1
    finally:await provider.close();store.db.close()

@pytest.mark.asyncio
async def test_successful_probe_releases_parallel_paragraph_requests(tmp_path):
    store=Store(tmp_path/'db');calls=0;active=0;peak=0
    async def respond(request):
        nonlocal calls,active,peak
        calls+=1;active+=1;peak=max(peak,active)
        await asyncio.sleep(.02)
        active-=1
        return httpx.Response(200,json=dict(choices=[dict(finish_reason='stop',message=dict(content='Hello.'))]))
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        assert await asyncio.gather(*(provider.translate_text('u','c','你好。','en') for _ in range(4)))==['Hello.']*4
        assert calls==4 and peak==3
    finally:await provider.close();store.db.close()

@pytest.mark.asyncio
async def test_account_recovery_reprobes_dedicated_model_without_configuration_change(tmp_path):
    store=Store(tmp_path/'db');available=False;models=[]
    def respond(request):
        models.append(json.loads(request.content)['model'])
        if not available:return httpx.Response(403,json={'error':{'code':'AccessDenied.Unpurchased'}})
        return httpx.Response(200,json=dict(id='fixture',choices=[dict(finish_reason='stop',message=dict(content='Hello.'))]))
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(ProviderError,match='Unpurchased'):await provider.translate_text('u','c','你好。','en')
        assert store.get('translation_provider','system','')['active'] is None
        available=True;provider.mt_unavailable_until=0
        assert await provider.translate_text('u','c','你好。','en')=='Hello.'
        assert models==['qwen-mt-flash','qwen-turbo','qwen-mt-flash']
        assert store.get('translation_provider','system','')['active']=='qwen-mt-flash'
    finally:await provider.close();store.db.close()
