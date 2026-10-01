"""Latency changes must preserve private context, validation and expression density."""
import json
import uuid
import httpx
import pytest
from pydantic import ValidationError
from services.character_ai.config import Settings
from services.character_ai.provider import Provider, prompt_schema, session_cache_key, structured_messages
from services.character_ai.orchestrator import interaction_mismatch
from services.character_ai.prompts import PLANNER
from services.character_ai.schemas import TimelinePlan, Request
from services.character_ai.semantic_novelty import SemanticNovelty
from services.character_ai.storage import Store
from services.character_ai.planner_wire import CompactPlan, wire_system


def test_schema_compaction_preserves_every_validation_keyword():
    compact=json.loads(prompt_schema(TimelinePlan))
    def compare(source,result):
        if isinstance(source,dict):
            for k,v in source.items():
                if k not in ('title','description','default'):compare(v,result[k])
        elif isinstance(source,list):
            assert len(source)==len(result)
            for a,b in zip(source,result):compare(a,b)
        else:assert source==result
    compare(TimelinePlan.model_json_schema(),compact)
    assert len(prompt_schema(TimelinePlan))<len(json.dumps(TimelinePlan.model_json_schema(),ensure_ascii=False))*.75


def test_variable_state_does_not_invalidate_schema_persona_or_capability_prefix():
    assert 'recent_response_focus' in wire_system(PLANNER) and 'recent_focus' not in wire_system(PLANNER)
    context=dict(character_profile={'name':'测试'},avatar_capability={'groups':[]},trigger='user_message',
                 user_message='今天有点累',state={'updated':1},recent_messages=[])
    a=structured_messages('plan',PLANNER,context,TimelinePlan)[0]['content']
    b=structured_messages('plan',PLANNER,{**context,'state':{'updated':2},'user_message':'换个话题'},TimelinePlan)[0]['content']
    assert a.split('当前状态')[0]==b.split('当前状态')[0]
    assert a!=b
    key=session_cache_key('alice','kipfel','plan','model',PLANNER)
    assert len(key)==64 and 'alice' not in key
    for args in [('bob','kipfel','plan','model',PLANNER),('alice','mame','plan','model',PLANNER),
                 ('alice','kipfel','narration','model',PLANNER),('alice','kipfel','plan','new',PLANNER)]:
        assert key!=session_cache_key(*args)


@pytest.mark.parametrize('kind',['pinch_in','pinch_out'])
@pytest.mark.parametrize('text',['你把我缩小了。','怎么把我弄大了呀。','你把我拉这么近。','我变小了啦。','你把我晃得头晕了。'])
def test_pinch_rejects_literal_resize_distance_or_rotation(kind,text):
    request=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',trigger='model_pinched',interaction=dict(kind=kind,intensity=.7))
    assert interaction_mismatch(request,text)
    assert interaction_mismatch(request,'偷偷捏我一下，这下被我抓到啦。' if kind=='pinch_in' else '扯我可是要付代价的，先说一句好听的嘛。') is None
    assert interaction_mismatch(request,'扯我一下。' if kind=='pinch_in' else '捏我一下。')


@pytest.mark.asyncio
async def test_provider_enables_isolated_cache_without_server_managed_history(tmp_path):
    store=Store(tmp_path/'db');requests=[]
    def transport(request):
        requests.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'focus':'测试','beats':[]})}}]})
    provider=Provider(Settings(data_dir=tmp_path),store,httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    try:
        for owner in ('alice','alice','bob'):
            await provider.structured(owner,'anime-kipfel','plan',PLANNER,{'user_message':'你好'},TimelinePlan)
        keys=[r.headers['x-dashscope-aca-session'] for r in requests]
        assert keys[0]==keys[1] and keys[0]!=keys[2]
        assert all('character_options' not in json.loads(r.content) for r in requests)
    finally:await provider.close();store.db.close()


@pytest.mark.asyncio
async def test_semantic_warmup_runs_once_and_disabled_mode_does_no_work(tmp_path):
    store=Store(tmp_path/'db');semantic=SemanticNovelty(Settings(data_dir=tmp_path),store);calls=[]
    def embed(texts):calls.append(texts);semantic.model=object();return [[1]]
    semantic.embed=embed
    await semantic.warmup();assert not calls
    semantic.settings.semantic_novelty=True
    await semantic.warmup();await semantic.warmup()
    assert len(calls)==1
    assert not store.db.execute('SELECT * FROM usage').fetchall()
    store.db.close()


def test_compact_wire_preserves_voice_staged_asides_all_groups_and_account_changes():
    compact=CompactPlan(focus='与今天的交流相呼应的新内容',beats=[dict(say='今天有一个新想法，想讲给你听。',mood='playful',tone='warm',strength=.7,
        asides=[['我有点期待。','middle','visible','新想法，'],['我先留在心里。','after','hidden']],
        cues=[['author.future.wings','flutter'],['pose','sit',1800],['appearance','hat',2500,False]],vocals=['giggle'])],
        state={'trust':.02},memory=[dict(content='用户喜欢画画')])
    plan=compact.expand(TimelinePlan);beat=plan.beats[0]
    assert beat.beat_id=='b1' and beat.dialogue.speech.emotion=='happy' and beat.dialogue.speech.delivery=='gentle'
    assert beat.asides[0].after_text=='新想法，' and beat.asides[1].visibility=='hidden'
    assert [(c.group,c.intent,c.offset_ms,c.active) for c in beat.performance.cues]==[
        ('author.future.wings','flutter',0,True),('pose','sit',1800,True),('appearance','hat',2500,False)]
    assert beat.vocal_events[0].event=='giggle' and plan.memory_updates[0].content=='用户喜欢画画'
    assert plan.suggested_state_delta=={'trust':.02}
    assert CompactPlan(focus='安静陪伴',idle='do_nothing').expand(TimelinePlan).beats==[]


@pytest.mark.parametrize('cue',[['ears','up',-1],['ears','up',12001],['x'*65,'up'],['ears','x'*129]])
def test_compact_controls_still_pass_through_full_standard_validation(cue):
    plan=CompactPlan(focus='测试',beats=[dict(say='你好呀。',asides=[['我有些开心。','middle']],cues=[cue])])
    with pytest.raises(ValidationError):plan.expand(TimelinePlan)
