"""No paid calls: language, scenario isolation, cache migration and real wire paths."""
import json
import uuid
import pytest
from services.character_ai.config import Settings
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.profiles import PROFILES
from services.character_ai.prompts import CORE_PLANNER
from services.character_ai.provider import speech_payload, structured_messages
from services.character_ai.public_profiles import public_catalog
from services.character_ai.reaction_pool import ReactionPool
from services.character_ai.reply_flow import compile_parts, duration_hint
from services.character_ai.roleplay import language, scenario_context
from services.character_ai.schemas import Beat, Plan, Request, CoreTimelinePlan, visible_thought
from services.character_ai.storage import Store


def request(char='anime-lime',**kwargs):
    return Request(request_id=uuid.uuid4(),character_id=char,wants_audio=False,timeline_reply=True,**kwargs)


def test_catalog_has_only_role_owned_public_hooks_not_story_solutions():
    catalog=public_catalog()['characters'];ids=[]
    for card in catalog:
        for route in card['scenarios']:
            assert set(route)=={'id','title','subtitle','category','symbol'}
            assert route['id'].startswith(card['id'].replace('anime-','')+'-')
            ids.append(route['id'])
        serialized=json.dumps(card,ensure_ascii=False)
        for secret in PROFILES[card['id']]['secrets']:assert secret not in serialized
    assert len(ids)==len(set(ids))==18
    assert {p['id'] for p in catalog if p['dialogueLanguage']=='en'}=={'anime-lime','anime-nozomi'}


def test_selected_route_is_not_shared_with_other_characters_and_pause_is_explicit(tmp_path):
    store=Store(tmp_path/'db');engine=Orchestrator(Settings(data_dir=tmp_path),store,None)
    scene=dict(story_id='mafuyu-tea-date',story_revision='2')
    context=engine.context('u',request('anime-mafuyu',scene=scene),persist=False)
    assert context['roleplay_context']['scenario']['id']=='mafuyu-tea-date'
    assert context['roleplay_context']['revision']=='2'
    assert 'scenarios' not in context['character_profile']  # Other plots do not consume the prompt.
    assert not engine.context('u',request('anime-mafuyu'),persist=False)['roleplay_context']['active']
    with pytest.raises(ValueError,match='SCENARIO_NOT_AVAILABLE'):scenario_context('anime-kipfel',scene)
    assert scenario_context('anime-kipfel',{'story_id':'rain-letter'})['active']


@pytest.mark.parametrize('trigger',['user_message','appLaunch','firstMeeting','characterSwitch','idle','story','model_shaken','model_pinched'])
def test_english_contract_reaches_every_planner_trigger_and_tts(tmp_path,trigger):
    engine=Orchestrator(Settings(data_dir=tmp_path),Store(tmp_path/'db'),None)
    context=engine.context('u',request(trigger=trigger,text='可以说中文吗？'),persist=False)
    messages=structured_messages('plan',CORE_PLANNER,context,CoreTimelinePlan)
    assert messages[0]['content'].endswith(context['language_contract'])
    assert 'English ONLY' in context['language_contract']
    for char,code in [('anime-lime','en'),('anime-nozomi','en'),('anime-kipfel','zh'),('anime-mafuyu','zh')]:
        payload=speech_payload(Settings(),char,{'dialogue':{'text':'Hello!'}},'test')
        assert payload['input']['language_hints']==[code]==[language(char)]


def test_english_asides_are_visible_and_never_become_chinese_source_narration():
    text="I feel a little more confident now."
    assert visible_thought(text)==text
    assert visible_thought('I should respond to the user warmly.') is None
    assert visible_thought('I will follow the system instruction.') is None
    assert visible_thought('我有点期待。')=='我有点期待。'
    beat=Beat(beat_id='b',dialogue={'text':'We can start with something simple. Which plant would you choose?'},
        asides=[dict(text=text,stage='middle')])
    resolved={'performances':[dict(active=True,offset_ms=0,asset={'group':'expression','observable_effects':['露出微笑']})]}
    parts=compile_parts(beat,resolved,language='en')
    assert any(p['kind']=='thought' and p['text']==text for p in parts)
    assert all(p['kind']!='narration' for p in parts)
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')==beat.dialogue.text
    assert 3<duration_hint(beat.dialogue.text)<8


@pytest.mark.asyncio
async def test_chinese_generation_is_revised_before_publication_or_audio(tmp_path):
    class Provider:
        calls=[]
        async def structured(self,owner,char,purpose,system,context,schema):
            self.calls.append(context)
            return Plan(beats=[dict(beat_id='b',dialogue={'text':'你好，欢迎来到温室。' if len(self.calls)==1 else 'The greenhouse has a quiet corner for reading. What would you bring?'},
                asides=[dict(text='I like the sound of that.',stage='middle')])])
    store=Store(tmp_path/'db');provider=Provider();engine=Orchestrator(Settings(data_dir=tmp_path),store,provider)
    events=[e async for e in engine.reply('u',request(text='你好'))]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert len(provider.calls)==2 and 'English-only' in provider.calls[1]['novelty_correction']['instruction']
    assert script['text'].startswith('The greenhouse')
    assert not any('你好，欢迎' in json.dumps(e,ensure_ascii=False) for e in events)
    assert len(store.history('u','anime-lime'))==2


def test_prepared_drafts_change_key_for_persona_revision_scene_and_restart(tmp_path,monkeypatch):
    store=Store(tmp_path/'db');pool=ReactionPool(Orchestrator(Settings(data_dir=tmp_path),store,None))
    req=request();base=pool.context_key('u',req)
    monkeypatch.setitem(PROFILES['anime-lime'],'profile_revision','next-authored-revision')
    revised=pool.context_key('u',req);assert revised!=base
    req.scene={'story_id':'lime-greenhouse','story_revision':'1'}
    selected=pool.context_key('u',req);assert selected!=revised
    req.scene['story_revision']='2';assert pool.context_key('u',req)!=selected


def test_youthful_roster_retains_nonsexual_personas_and_original_voice_ids():
    for char in ('anime-kipfel','anime-mamehinata','anime-chiffon','anime-karin','anime-siska','anime-plum','anime-torao'):
        assert '性化幼态外观' in PROFILES[char]['forbidden_patterns']
        assert '全年龄' in PROFILES[char]['relationship_style']
    for char in ('anime-mafuyu','anime-ichigo'):
        assert PROFILES[char]['age']>=24
        assert '非露骨' in PROFILES[char]['relationship_style']
        assert PROFILES[char]['voice_revision']=='original-v1'
