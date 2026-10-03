"""Regression: real rejected field shape, immutable retry and public boundaries."""
import json,uuid
import httpx,pytest
from pydantic import ValidationError
from services.character_ai.provider import Provider
from services.character_ai.schemas import CoreTimelinePlan,Request
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.tests.test_reaction_pool import setup as pool_setup

def setup(path):
    values=pool_setup(path);provider=values[1];original=provider.structured
    async def structured(owner,char,purpose,system,context,schema):
        return await original(owner,char,purpose,system,{**context,"trigger":"return"},schema)
    provider.structured=structured
    return values

@pytest.mark.asyncio
async def test_provider_decoration_at_wrong_level_does_not_rebill_valid_shinano_speech(tmp_path):
    store=Store(tmp_path/'db');calls=[]
    # The failed live turn's exact field layout, with synthetic private-free prose.
    output=dict(focus='询问',beats=[dict(say='我刚刚在听窗外的雨，你也听见了吗？',mood='serene',tone='gentle',asides=[['我想听听你的感觉','before'],['我有些期待','after']])],extra_lines=True,detail=['不该进入台词的字段','middle'],visually_visible=True,vocals=[],goal_feedback=dict(familiarity=0,trust=0,affection=0,task_progress=0,evidence='听到了'))
    def answer(req):
        calls.append(req);return httpx.Response(200,json=dict(id='synthetic',choices=[dict(message=dict(content=json.dumps(output,ensure_ascii=False)))],usage={}))
    client=httpx.AsyncClient(transport=httpx.MockTransport(answer));provider=Provider(Settings(data_dir=tmp_path),store,client)
    result=await provider.structured('u','anime-shinano','plan','test',dict(trigger='user_message',user_message='听到了'),CoreTimelinePlan)
    assert len(calls)==1 and result.beats[0].dialogue.text==output['beats'][0]['say']
    assert result.beats[0].dialogue.speech.emotion=='neutral'
    assert [a.text for a in result.beats[0].asides]==['我想听听你的感觉','我有些期待']
    await provider.close();store.db.close()

def test_public_request_unknown_fields_still_rejected():
    with pytest.raises(ValidationError):Request(request_id=uuid.uuid4(),character_id='anime-shinano',extra_lines=True)

def test_worker_restart_only_recovers_unpublished_requests(tmp_path):
    store=Store(tmp_path/'db')
    store.request('u','c','a',{})
    store.request('u','c','b',{})
    store.complete('u','c','b',dict(message_id='saved',text='已完成'))
    assert store.recover_interrupted_requests()==1
    assert store.request('u','c','a',{}) is None
    assert store.request('u','c','b',{})['message_id']=='saved'
    store.db.close()

@pytest.mark.asyncio
async def test_interrupted_request_retries_once_and_completed_result_replays_without_duplication(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    request=request.model_copy(update=dict(trigger='user_message',text='这是一条要恢复的消息'))
    payload=request.model_dump(mode='json',exclude={'progressive_reply','timeline_reply','parallel_performance','interaction','quick_reply_id'})
    rid=str(request.request_id)
    assert store.request('u',request.character_id,rid,payload) is None
    with pytest.raises(ValueError,match='REQUEST_INCOMPLETE'):store.request('u',request.character_id,rid,payload)
    store.interrupt('u',request.character_id,rid)
    # Equivalent JSON object ordering from a reconstructed client must not
    # become REQUEST_ID_REUSED; actual content changes still fail below.
    assert store.request('u',request.character_id,rid,dict(reversed(list(payload.items())))) is None
    store.interrupt('u',request.character_id,rid)
    events=[e async for e in engine.reply('u',request)]
    count=len(provider.calls)
    assert any(e['type']=='reply.completed' for e in events)
    replay=[e async for e in engine.reply('u',request)]
    assert replay[0]['cached'] and len(provider.calls)==count
    assert len([m for m in store.history('u',request.character_id) if m['role']=='user'])==1
    changed={**payload,'text':'different'}
    with pytest.raises(ValueError,match='REQUEST_ID_REUSED'):store.request('u',request.character_id,rid,changed)
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_unpublished_stream_format_failure_uses_existing_planner_recovery(tmp_path):
    store,provider,engine,pool,request=setup(tmp_path)
    async def broken(*args):raise ValueError('STREAM_JSON_INVALID');yield
    provider.stream_beats=broken
    request=request.model_copy(update=dict(trigger='user_message',text='继续聊聊',timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    assert any(e['type']=='reply.narration.ready' for e in events)
    assert provider.calls.count('plan')==1 and provider.calls.count('tts')==1
    assert not any(e['type']=='reply.error' for e in events)
    await pool.close();store.db.close()
