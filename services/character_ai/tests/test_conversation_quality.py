import json
import uuid
from pathlib import Path
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Beat, Plan, NarrationResult, Request, visible_thought
from services.character_ai.provider import speech_input
from services.character_ai.speech_text import spoken_text, audio_key
from services.character_ai.greetings import greeting_context, repeated_greeting
from services.character_ai.director import Director
from services.character_ai.profiles import assets
from services.character_ai.orchestrator import Orchestrator


@pytest.mark.parametrize('text,expected', [
    ("今天庭院光线真柔和'（语气平稳）。", "今天庭院光线真柔和'。"),
    ('谢谢你的认可～（语气活泼带笑意）。', '谢谢你的认可～。'),
    ('嗯…你想听听哪种心情表现呢？（语气微扬带探究感）。', '嗯…你想听听哪种心情表现呢？'),
    ('(语气：平稳)可以呀【动作：眨眼】！', '可以呀！'),
    ('（语气轻柔（带笑意））晚上好。', '晚上好。'),
    ('好呀（语气轻快', '好呀'),
    ('*笑着说*谢谢你！', '谢谢你！'),
    ('（语气俏皮，声音很甜）你好呀。', '你好呀。'),
    ('[tone: curious]想听听看。', '想听听看。'),
    ('<tone>平稳</tone>你好。', '你好。'),
    ('你好呀。","speech":{"emotion":"happy"}},', '你好呀。'),
    ('维生素（B12）是这个名字。', '维生素（B12）是这个名字。'),
    ('明天（如果有空）再聊吧。', '明天（如果有空）再聊吧。'),
    ('这个词（语气是什么意思）可以解释吗？', '这个词（语气是什么意思）可以解释吗？'),
    ('我喜欢**小花**。', '我喜欢小花。'),
])
def test_stage_directions_never_enter_speech_but_spoken_asides_survive(text, expected):
    assert spoken_text(text) == expected
    output, _ = speech_input(dict(dialogue=dict(text=text), thought='不念心声',
                                 narrations=[dict(text='不念旁白')]))
    assert output == expected


def test_annotations_only_are_silent_but_structured_vocals_survive():
    beat = dict(dialogue=dict(text='（语气平稳）。', speech=dict(emotion='happy')))
    assert speech_input(beat)[0] == ''
    beat['vocal_events'] = [dict(event='giggle')]
    assert speech_input(beat)[0] == '[excited][giggles]'
    assert audio_key('u','c','v','m','b') != audio_key('u','c','v','m','b',revision='')
    assert audio_key('u','c','v','m','b') != audio_key('other','c','v','m','b')


def test_control_json_cannot_hide_inside_a_valid_dialogue_string():
    with pytest.raises(ValueError,match='control JSON'):
        Beat(beat_id='b',dialogue=dict(text='你好～","speech":{"emotion":"happy"}},'))
    assert Beat(beat_id='b',dialogue=dict(text='你说的 JSON，我听到了。')).dialogue.text


REPORTED_THOUGHT='轻唤昵称，延续晨光庭院的宁静氛围，并自然引出书籍或日常话题的分享邀请。'

@pytest.mark.parametrize('text',[
    REPORTED_THOUGHT,
    '我需要延续宁静的氛围，并自然引出书籍话题。',
    '我根据上下文选择温柔语气回应。',
    '我先引导日常话题，再发出分享邀请。',
    '我'+('有点期待。'*9),
])
def test_planning_is_not_character_inner_voice(text):
    assert visible_thought(text) is None


@pytest.mark.parametrize('text',[
    '我也想听听后面的故事。',
    '你记得这件事，让我有点开心。',
    '我很喜欢你给我的昵称。',
    '我喜欢这里安静的氛围。',
    '咱们又见面了，真好。',
])
def test_genuine_first_person_feelings_survive(text):
    assert visible_thought(text)==text


@pytest.mark.asyncio
async def test_reported_planning_hidden_for_new_and_cached_replies_without_extra_calls(tmp_path):
    class ThoughtProvider:
        def __init__(self):self.calls=[]
        async def structured(self,owner,char,purpose,system,context,schema):
            self.calls.append(purpose)
            if purpose=='plan':
                return Plan(beats=[Beat(beat_id='b',thought=REPORTED_THOUGHT,dialogue=dict(text='你回来啦。'))])
            assert context['plan']['beats'][0]['thought'] is None
            return NarrationResult()
    store=Store(tmp_path/'state.db');provider=ThoughtProvider()
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='我回来啦',wants_audio=False)
    events=[e async for e in engine.reply('u',req)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['beats'][0]['thought'] is None and script['text']=='你回来啦。'
    assert speech_input(script['beats'][0])[0]=='你回来啦。'
    # Simulate the actual old persisted payload. Read-time filtering must not
    # destroy the archive or regenerate the paid answer/audio on a retry.
    script['beats'][0]['thought']=REPORTED_THOUGHT
    store.complete('u',req.character_id,str(req.request_id),script)
    replay=[e async for e in engine.reply('u',req)]
    assert replay[0]['script']['beats'][0]['thought'] is None
    assert replay[0]['script']['text']=='你回来啦。'
    assert provider.calls==['plan','narration']
    archived=json.loads(store.db.execute('SELECT result FROM requests').fetchone()[0])
    assert archived['beats'][0]['thought']==REPORTED_THOUGHT
    store.db.close()


def test_duplicate_greeting_guard_accepts_new_topic_hook_not_old_answer():
    previous = ['你画的小花很漂亮，花瓣上的颜色也很温柔。']
    assert repeated_greeting(previous[0],previous)
    assert repeated_greeting('回来啦！'+previous[0],previous)
    assert repeated_greeting('你画的这朵小花很漂亮，花瓣的颜色也很温柔！',previous)
    assert not repeated_greeting('又见面啦。上次聊到画画，今天想继续聊，还是换个话题？',previous)
    ctx = greeting_context([dict(role='user',text='我画了一朵花。'),dict(role='assistant',text=previous[0])],[],10)
    assert ctx['has_met'] and ctx['elapsed_seconds']==10 and ctx['previous_lines_to_avoid']==previous


class GreetingProvider:
    def __init__(self,answers): self.answers=iter(answers); self.contexts=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        if purpose=='narration': return NarrationResult()
        self.contexts.append(context)
        return Plan(beats=[Beat(beat_id='b',dialogue=dict(text=next(self.answers)))])


@pytest.mark.asyncio
async def test_greeting_uses_history_corrects_once_and_replay_never_pays_twice(tmp_path):
    store=Store(tmp_path/'state.db');settings=Settings(data_dir=tmp_path)
    char='anime-kipfel';old='谢谢你陪我聊小花，我很喜欢这样柔和的颜色。';new='又见面啦。上次的小花还想接着聊吗，或者我们换个话题？'
    store.message('old','u',char,'r','assistant',dict(text=old))
    provider=GreetingProvider([old,new]);engine=Orchestrator(settings,store,provider)
    request=Request(request_id=uuid.uuid4(),character_id=char,trigger='appLaunch',wants_audio=False)
    events=[e async for e in engine.reply('u',request)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['text']==new and script['trigger']=='appLaunch'
    assert len(provider.contexts)==2 and provider.contexts[0]['user_message']==''
    assert provider.contexts[0]['greeting_context']['has_met']
    assert provider.contexts[1]['novelty_correction']['rejected_text']==old
    assert store.get('greetings','u',char)==[new]
    assert not store.get('greetings','other',char)
    assert not store.get('greetings','u','anime-mamehinata')
    assert [e async for e in engine.reply('u',request)][0]['script']==script
    assert len(provider.contexts)==2


@pytest.mark.asyncio
async def test_second_duplicate_is_not_spoken_or_saved_and_normal_reply_is_also_checked(tmp_path):
    store=Store(tmp_path/'state.db');settings=Settings(data_dir=tmp_path);char='anime-kipfel'
    old='我给你留了一个位置，我们慢慢聊。'
    store.message('old','u',char,'r','assistant',dict(text=old))
    provider=GreetingProvider([old,old,old]);engine=Orchestrator(settings,store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=char,trigger='characterSwitch',wants_audio=False)
    events=[e async for e in engine.reply('u',req)]
    assert all(e['type']=='reply.completed' for e in events)
    assert len(provider.contexts)==3 and len(store.history('u',char))==1
    provider=GreetingProvider([old,'当然，我们接着刚才没讲完的故事吧。']);engine=Orchestrator(settings,store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=char,text='再说一遍',wants_audio=False)
    _=[e async for e in engine.reply('u',req)]
    assert len(provider.contexts)==2 and 'greeting_context' not in provider.contexts[0]


@pytest.mark.parametrize('char',['anime-kipfel','anime-mamehinata'])
def test_director_reaches_real_faces_hands_ears_tails_without_body_or_costume_changes(tmp_path,char):
    store=Store(tmp_path/'state.db');director=Director(store);allowed=[a['asset_id'] for a in assets(char)]
    for action,group in [('ear_wiggle','ears'),('tail_wag','tail'),('peace','hands')]:
        beat=Beat(beat_id='b',dialogue=dict(text='好呀',speech=dict(emotion='happy')),
                  performance=dict(action_intent=action))
        result=director.beat('u'+action,char,beat,{}, {},allowed)
        assert result['expression_asset']['intent']=='bright_smile'
        assert result['action_asset']['group']==group and result['grounding']=='exact'
    assert director.resolve('u',char,'action','hug',.5,{}, {},allowed)==(None,'none')
    assert director.resolve('u',char,'action','ear_wiggle',.5,{}, {},[])==(None,'none')
    assert {a['group'] for a in assets(char)}=={'expression','hands','ears','tail','pose','appearance'}
    assert {c['asset']['group'] for c in result['performances']} <= {'expression','hands','ears','tail'}
    guide=director.capability(char,allowed)
    assert guide['intent_guide']['ear_wiggle'] and 'tail_wag' in guide['supported_action_intents']
    greeting=director.beat('first',char,Beat(beat_id='b',dialogue=dict(text='你好')),{}, {},allowed,trigger='firstMeeting')
    assert greeting['expression_asset']['intent']=='soft_smile'


def test_reviewed_mappings_match_installed_catalog():
    import os
    catalog=os.environ.get('STARRY_CHARACTER_CATALOG')
    if not catalog:pytest.skip('Set STARRY_CHARACTER_CATALOG to an exported client capability catalog')
    path=Path(catalog)
    if not path.exists(): pytest.skip('Licensed local catalog is not distributed with the public repository')
    for model in json.loads(path.read_text())['characters']:
        actual={a['id']:a for a in model['performance']['options']}
        for asset in assets(model['id']):
            option=actual[asset['asset_id']]
            assert option['group']==asset['group'] and option['kind']==asset['source_kind']
            control=option.get('control') or {}
            assert option.get('clip') or option.get('morphs') or option.get('morphTracks') or option.get('visibility') or control.get('parameter')
            if control.get('id'):
                assert 'core.avatar-controls@1' in model['compatibility']['required']
                assert control['id']==option['id'] and control['kind'] in ('toggle','button','slider')
                if asset['automatic']:
                    assert option['ai']['automatic'] is True and option['ai']['speechCompatible'] is True
                    assert control['kind']!='slider'
            elif option['kind']=='toggle':assert not asset['automatic']
