"""Exercise actual roster semantics, bounded group choreography and input reactions."""
import copy
import json
import random
import uuid
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Beat, Plan, Narration, NarrationResult, Request
from services.character_ai.profiles import assets
from services.character_ai.director import Director, visible_narration, grounded
from services.character_ai.orchestrator import Orchestrator, brief_shake_plan

ROLES=['anime-kipfel','anime-mamehinata']

@pytest.mark.parametrize('role',['anime-chiffon','anime-karin'])
def test_portable_gesture_faces_are_available_as_emotions(tmp_path,role):
    library=assets(role)
    faces=[a for a in library if a['kind']=='expression']
    assert len(faces)>=12
    assert all(a['asset_id'].startswith('gesture-') and a['automatic'] for a in faces)
    store=Store(tmp_path/'state.db');director=Director(store,random.Random(3))
    assert 'soft_smile' in director.capability(role,[a['asset_id'] for a in library])['supported_expression_intents']
    # This request uses the old planner's top-level emotion, not an author menu
    # group. It must ground to the new hashed menu without special-case IDs.
    beat=Beat(beat_id='b',dialogue=dict(text='今天也想和你聊一小会儿呀。'),performance=dict(expression_intent='soft_smile'))
    result=director.beat('u',role,beat,{}, {},[a['asset_id'] for a in library])
    assert result['expression_asset']['intent']=='soft_smile'
    assert result['expression_asset']['group'].startswith('menu-')
    assert all(c['asset']['kind']=='expression' for c in result['performances'])
    assert len(result['performances'])>=2
    special=next(a for a in faces if a['asset_id']=='gesture-left-6')
    assert special['intent']==('surprised' if role=='anime-chiffon' else 'sad')
    store.db.close()

def test_switching_an_accessory_off_cannot_narrate_its_on_effect(tmp_path):
    store=Store(tmp_path/'state.db');director=Director(store)
    toggle=next(a for a in assets(ROLES[0]) if a['source_kind']=='toggle' and a['speech_compatible'])
    beat=Beat(beat_id='b',dialogue=dict(text='好呀'),performance=dict(cues=[dict(group=toggle['group'],intent=toggle['intent'],active=False)]))
    result=director.beat('u',ROLES[0],beat,{}, {},[toggle['asset_id']])
    assert len(result['performances'])==1 and not result['performances'][0]['active']
    narration=Narration(beat_id='b',mode='performed',text=toggle['observable_effects'][0],visual_grounding='exact',evidence=[toggle['observable_effects'][0]])
    assert not grounded(narration,[result]), 'Inactive cue must not fall back to its legacy on-effect'
    store.db.close()

@pytest.mark.parametrize('role',ROLES)
def test_real_roster_combines_all_conversational_groups_in_two_phases(tmp_path,role):
    store=Store(tmp_path/'state.db');director=Director(store,random.Random(5))
    beat=Beat(beat_id='b',dialogue=dict(text='你真的记得我喜欢的小花呀，今天能再多陪我聊一会儿吗？',speech=dict(emotion='happy')))
    result=director.beat('u',role,beat,{}, {},[a['asset_id'] for a in assets(role)])
    cues=result['performances']
    assert 6<=len(cues)<=8
    assert {c['asset']['group'] for c in cues}=={'expression','hands','ears','tail'}
    assert len({c['asset']['asset_id'] for c in cues})==len(cues)
    assert any(c['offset_ms']>=2200 for c in cues)
    assert all(c['asset']['automatic'] and c['active'] for c in cues)
    assert all(c['duration_ms']<=8000 for c in cues)
    assert len(store.history('u',role))==0  # animation selection adds no conversation
    store.db.close()

@pytest.mark.parametrize('role',ROLES)
def test_explicit_posture_and_accessory_cues_are_reachable_but_not_random(tmp_path,role):
    store=Store(tmp_path/'state.db');director=Director(store,random.Random(2));library=assets(role)
    posture=next(a for a in library if a['group']=='pose' and '坐' in a['label'])
    toggle=next(a for a in library if a['source_kind']=='toggle' and a['speech_compatible'])
    beat=Beat(beat_id='b',dialogue=dict(text='我坐下来陪你聊一会儿。'),performance=dict(cues=[
        dict(group='pose',intent=posture['intent']),dict(group=toggle['group'],intent=toggle['intent'],active=False)]))
    result=director.beat('u',role,beat,{}, {},[a['asset_id'] for a in library])
    cues=result['performances'];ids={c['asset']['asset_id'] for c in cues}
    assert posture['asset_id'] in ids and toggle['asset_id'] in ids
    assert next(c for c in cues if c['asset']['asset_id']==toggle['asset_id'])['active'] is False
    assert all(a['automatic'] is False for a in library if a['group'] in ('pose','appearance'))
    store.db.close()

def test_new_groups_conflicts_available_assets_and_budget_are_data_driven(tmp_path,monkeypatch):
    prototype=assets(ROLES[0])[0];library=[]
    for i in range(14):
        for phase in range(2):
            library.append(dict(copy.deepcopy(prototype),asset_id=f'extension-{i}-{phase}',group=f'author.extra{i}',
                group_label=f'扩展 {i}',kind='action',intent=f'extra_{i}_{phase}',moods=['happy'],
                automatic=True,speech_compatible=True,cooldown_sec=0,conflicts=[]))
    library[0]['conflicts']=['author.extra1'];library[1]['conflicts']=['author.extra1']
    monkeypatch.setattr('services.character_ai.director.assets',lambda _:library)
    store=Store(tmp_path/'state.db');director=Director(store,random.Random(3))
    available=[a['asset_id'] for a in library if a['group']!='author.extra13']
    beat=Beat(beat_id='b',dialogue=dict(text='这些都是作者通过标准目录声明的全新表现分组。',speech=dict(emotion='happy')))
    assert len(director.capability('new',available)['groups'])==13
    reached=set()
    for _ in range(8):
        cues=director.beat('u','new',beat,{}, {},available)['performances'];groups={c['asset']['group'] for c in cues}
        assert len(cues)<=24 and len(groups)<=8
        assert not {'author.extra0','author.extra1'}<=groups
        assert 'author.extra13' not in groups
        reached|=groups
    assert len(reached)==13, 'Group fairness must eventually reach every available author group'
    store.db.close()

class ShakeProvider:
    def __init__(self):self.calls=[];self.contexts=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose);self.contexts.append(context)
        if purpose=='narration':return NarrationResult()
        assert context['trigger']=='model_shaken' and context['user_message']==''
        assert '连续晃动' in context['interaction_context']['task']
        assert 'appearance_facts' not in context['character_profile']
        return Plan(beats=[Beat(beat_id='b',dialogue=dict(text='呜，快把我晃迷糊啦！轻一点嘛，陪我好好说话好不好？' if char==ROLES[0] else '哼，现在轮到我提要求了，夸我一句好不好嘛？'))])

class PinchProvider:
    def __init__(self,kind,wrong_first=False):self.kind=kind;self.calls=[];self.wrong_first=wrong_first
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append(purpose)
        if purpose=='narration':return NarrationResult()
        assert context['trigger']=='model_pinched' and context['user_message']==''
        assert context['interaction_context']['kind']==self.kind
        assert ('向外拉开' if self.kind=='pinch_out' else '向内收拢') in context['interaction_context']['task']
        if self.wrong_first and self.calls.count('plan')==1:
            text='呜，你把我晃得头晕啦！'
        else:
            if self.wrong_first:assert '不是旋转' in context['novelty_correction']['reason']
            text='偷偷扯我一下，这下可被我抓到了。' if self.kind=='pinch_out' else '偷偷捏我一下，这下可被我抓到了。'
        return Plan(beats=[Beat(beat_id='b',dialogue=dict(text=text))])

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['pinch_out','pinch_in'])
async def test_pinch_uses_ai_specific_direction_and_revises_wrong_motion_before_publication(tmp_path,kind):
    store=Store(tmp_path/'state.db');provider=PinchProvider(kind,wrong_first=True)
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=ROLES[0],trigger='model_pinched',
        interaction=dict(kind=kind,intensity=.8),available_assets=[a['asset_id'] for a in assets(ROLES[0])],wants_audio=False)
    events=[e async for e in engine.reply('u',req)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['trigger']=='model_pinched' and '头晕' not in script['text']
    assert len(script['beats'][0]['visuals'])>=5
    assert provider.calls==['plan','plan','narration']
    replay=[e async for e in engine.reply('u',req)]
    assert replay[0]['cached'] and len(provider.calls)==3
    rotated=req.model_copy(update=dict(request_id=uuid.uuid4(),trigger='model_shaken',interaction=req.interaction.model_copy(update={'kind':'shake'})))
    assert len([e async for e in engine.reply('u',rotated)])==1
    opposite=req.model_copy(update=dict(request_id=uuid.uuid4(),interaction=req.interaction.model_copy(update={'kind':'pinch_in' if kind=='pinch_out' else 'pinch_out'})))
    assert len([e async for e in engine.reply('u',opposite)])==1
    assert len(provider.calls)==3, 'Rotation and both pinch directions share one cooldown before billing'
    assert len(store.history('u',req.character_id))==1
    store.db.close()

@pytest.mark.asyncio
async def test_shake_reaction_is_real_ai_owned_cooled_down_and_replay_is_free(tmp_path):
    store=Store(tmp_path/'state.db');provider=ShakeProvider()
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    def request(role=ROLES[0],intensity=.8):
        return Request(request_id=uuid.uuid4(),character_id=role,trigger='model_shaken',
            interaction=dict(kind='shake',intensity=intensity),available_assets=[a['asset_id'] for a in assets(role)],wants_audio=False)
    req=request();events=[e async for e in engine.reply('u',req)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['trigger']=='model_shaken' and script['text']
    assert len(script['beats'][0]['visuals'])>=5
    assert all(m['role']=='assistant' for m in store.history('u',req.character_id))
    replay=[e async for e in engine.reply('u',req)]
    assert replay[0]['cached'] and provider.calls==['plan','narration']
    assert len([e async for e in engine.reply('u',request())])==1
    assert len([e async for e in engine.reply('other',request(intensity=.1))])==1
    assert provider.calls==['plan','narration']
    _=[e async for e in engine.reply('other',request())]
    _=[e async for e in engine.reply('u',request(ROLES[1]))]
    assert len(provider.calls)==6, 'Owner and character cooldowns are isolated'
    store.db.close()

def test_reported_smile_as_speech_emotion_and_long_shake_output_are_normalized():
    plan=Plan(beats=[Beat(beat_id='b',dialogue=dict(text='哎呀，刚才被晃得有点晕乎乎呢～现在轮到我出题了，你能说出我的一个优点吗？',speech=dict(emotion='playful'))),
        Beat(beat_id='b2',dialogue=dict(text='再聊一个新话题。',speech=dict(emotion='bright_smile')))])
    brief_shake_plan(plan,'serious')
    assert len(plan.beats)==1 and plan.beats[0].dialogue.text.endswith('你能说出我的一个优点吗？')
    assert plan.beats[0].dialogue.speech.emotion=='serious'
    assert plan.beats[0].performance.expression_intent=='serious'
    assert not plan.memory_updates

@pytest.mark.asyncio
async def test_old_static_appearance_hidden_without_changing_archive(tmp_path):
    store=Store(tmp_path/'state.db');provider=ShakeProvider();engine=Orchestrator(Settings(data_dir=tmp_path),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=ROLES[0],text='你好',wants_audio=False)
    body=req.model_dump(mode='json',exclude={'progressive_reply','timeline_reply','parallel_performance','interaction','quick_reply_id'})
    store.request('u',req.character_id,str(req.request_id),body)
    script=dict(message_id='old',text='你好呀',beats=[dict(beat_id='b',thought=None,narrations=[
        dict(mode='literary',text='她有一双圆圆的眼睛。'),dict(mode='performed',text='单眼轻轻眨眼。')])])
    store.complete('u',req.character_id,str(req.request_id),script)
    replay=[e async for e in engine.reply('u',req)]
    assert replay[0]['script']['beats'][0]['narrations']==[script['beats'][0]['narrations'][1]]
    assert len(json.loads(store.db.execute('SELECT result FROM requests').fetchone()[0])['beats'][0]['narrations'])==2
    assert not provider.calls and visible_narration(dict(mode='performed',text='眼睛轻轻闭上'))
    store.db.close()
