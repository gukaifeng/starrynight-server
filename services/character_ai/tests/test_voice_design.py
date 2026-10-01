import asyncio
import base64
import io
import json
import wave

import httpx
import pytest

from services.character_ai.config import Settings
from services.character_ai.profiles import PROFILES
from services.character_ai.provider import Provider, ProviderError
from services.character_ai.storage import Store


def preview():
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000)
        audio.writeframes(b'\x01\x00'*2400)
    return output.getvalue()


@pytest.mark.asyncio
async def test_redesign_preserves_active_voice_and_reuses_paid_job(tmp_path):
    calls=[]
    def transport(request):
        payload=json.loads(request.content);calls.append(payload)
        return httpx.Response(200,json={'output':{'voice_id':'new-voice','preview_audio':{'data':base64.b64encode(preview()).decode()}},'usage':{'count':1}})
    settings=Settings(data_dir=tmp_path,max_voice_designs=1)
    store=Store(tmp_path/'test.sqlite3');char='anime-kipfel';profile=PROFILES[char]
    old=dict(voice_id='old-voice',job_id='old-job',approved=True)
    store.put('voice','system',char,old)
    store.put('voice','system','anime-mamehinata',dict(voice_id='other',approved=True))
    provider=Provider(settings,store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    assert await provider.design_voice(char,profile)==old and not calls
    new=await provider.design_voice(char,profile,revision=profile['voice_revision'])
    assert store.get('voice','system',char)==old
    assert await provider.design_voice(char,profile,revision=profile['voice_revision'])==new
    assert len(calls)==1 and calls[0]['input']['voice_prompt']==profile['voice_prompt']
    assert (tmp_path/'voices'/new['preview_file']).read_bytes()==preview()
    for job in (None,'stale-job'):
        with pytest.raises(ValueError,match='VOICE_CANDIDATE_'):store.approve_voice(char,job)
    approved=store.approve_voice(char,new['job_id'])
    assert approved['approved'] and approved['voice_id']=='new-voice'
    assert store.get('voice_history','old-job',char)==old
    assert store.get('voice','system','anime-mamehinata')['voice_id']=='other'
    assert not store.get('voice_candidate','system',char)
    assert await provider.design_voice(char,profile,revision=profile['voice_revision'])==approved
    assert len(calls)==1 and store.db.execute("SELECT count(*) FROM usage").fetchone()[0]==1
    await provider.close();store.db.close()


@pytest.mark.asyncio
async def test_pending_or_uncertain_creation_never_retries_or_changes_active_voice(tmp_path):
    started=asyncio.Event();release=asyncio.Event();calls=[]
    async def transport(request):
        calls.append(1);started.set();await release.wait()
        raise httpx.ReadTimeout('uncertain response')
    settings=Settings(data_dir=tmp_path)
    store=Store(tmp_path/'test.sqlite3');char='anime-kipfel';profile=PROFILES[char]
    old=dict(voice_id='old',approved=True,job_id='old');store.put('voice','system',char,old)
    provider=Provider(settings,store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    task=asyncio.create_task(provider.design_voice(char,profile,revision=profile['voice_revision']))
    await started.wait()
    with pytest.raises(ProviderError,match='ALREADY_REQUESTED'):
        await provider.design_voice(char,profile,revision=profile['voice_revision'])
    release.set()
    with pytest.raises(httpx.ReadTimeout):await task
    with pytest.raises(ProviderError,match='ALREADY_REQUESTED'):
        await provider.design_voice(char,profile,revision=profile['voice_revision'])
    assert calls==[1] and store.get('voice','system',char)==old
    assert store.db.execute('SELECT status FROM usage').fetchone()[0]=='interrupted_or_failed'
    await provider.close();store.db.close()


@pytest.mark.asyncio
async def test_revision_and_budget_checks_happen_before_provider_call(tmp_path):
    def transport(_):raise AssertionError('must not make any paid call')
    settings=Settings(data_dir=tmp_path,max_voice_designs=0)
    store=Store(tmp_path/'test.sqlite3');profile=PROFILES['anime-kipfel']
    provider=Provider(settings,store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    with pytest.raises(ProviderError,match='REVISION_UNKNOWN'):
        await provider.design_voice('anime-kipfel',profile,revision='unreviewed')
    with pytest.raises(ValueError,match='USAGE_LIMIT_VOICE_DESIGN'):
        await provider.design_voice('anime-kipfel',profile,revision=profile['voice_revision'])
    assert store.db.execute('SELECT count(*) FROM voice_design_jobs').fetchone()[0]==0
    await provider.close();store.db.close()


@pytest.mark.asyncio
async def test_invalid_preview_preserves_provider_id_without_activating_or_rebilling(tmp_path):
    def transport(_):return httpx.Response(200,json={'output':{'voice_id':'created-but-bad-preview','preview_audio':{'data':'aW52YWxpZCB3YXY='}},'usage':{'count':1}})
    store=Store(tmp_path/'test.sqlite3');profile=PROFILES['anime-kipfel']
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    with pytest.raises(wave.Error):await provider.design_voice('anime-kipfel',profile,revision=profile['voice_revision'])
    assert not store.get('voice','system','anime-kipfel')
    row=store.db.execute('SELECT status,data FROM voice_design_jobs').fetchone()
    assert row['status']=='interrupted_or_failed' and json.loads(row['data'])['voice_id']=='created-but-bad-preview'
    assert store.db.execute('SELECT status FROM usage').fetchone()[0]=='completed'
    with pytest.raises(ProviderError,match='ALREADY_REQUESTED'):
        await provider.design_voice('anime-kipfel',profile,revision=profile['voice_revision'])
    await provider.close();store.db.close()
