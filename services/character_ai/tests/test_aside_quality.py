import pytest
from services.character_ai.aside_quality import flatten,repeated,review_script
from services.character_ai.schemas import Beat
from services.character_ai.reply_flow import compile_parts
from services.character_ai.speech_text import spoken_text

def test_reported_nested_aside_is_one_flat_nonverbal_region():
    value='（轻翻着手账本，（眼睛变得亮晶晶）\n唇角噙着温柔笑意）'
    assert flatten(value)=='轻翻着手账本，眼睛变得亮晶晶 唇角噙着温柔笑意'
    assert spoken_text('不只是花哦。'+value+'雨后的痕迹我也会画。')=='不只是花哦。雨后的痕迹我也会画。'
    with pytest.raises(ValueError,match='stage directions'):
        Beat(beat_id='b',dialogue=dict(text='当然可以呀～（露出轻柔笑意）'))
    assert Beat(beat_id='b',dialogue=dict(text='明天（如果你有空）再聊。')).dialogue.text

@pytest.mark.parametrize('new',['露出轻柔笑意','露出开心的神情','唇角噙着温柔笑意','A small smile appears.'])
def test_smile_synonyms_share_an_avoidance_family(new):
    assert repeated(new,['露出温柔的笑容'])

def test_flattening_dedup_and_language_do_not_remove_spoken_words_or_visuals():
    beat=Beat(beat_id='b',dialogue=dict(text='Hmm… shall we try again?'),asides=[
        dict(text='（I feel curious.）',stage='middle'),dict(text='我有点期待。')])
    effects=[dict(active=True,offset_ms=0,asset=dict(group='expression',intent='soft_smile',observable_effects=['露出轻柔笑意'])),
        dict(active=True,offset_ms=1600,asset=dict(group='ears',intent='ear_wiggle',observable_effects=['耳朵轻轻摆动']))]
    parts=compile_parts(beat,dict(performances=effects),language='en',recent_asides=['A gentle smile appears.'])
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')==beat.dialogue.text
    assert any(p['text']=='I feel curious.' for p in parts)
    assert any(p['text']=='Her ears gently twitch.' for p in parts)
    assert all('我' not in p['text'] and 'smile' not in p['text'] for p in parts)
    assert len(effects)==2

def test_ready_draft_rechecks_intervening_automatic_turn_without_regeneration():
    script=dict(text='Of course!',beats=[dict(parts=[dict(kind='narration',text='露出轻柔笑意',at=0),
        dict(kind='dialogue',text='Of course!',at=0)],visuals=[dict(asset_id='smile')],narrations=[])])
    reviewed=review_script(script,['露出开心的神情'],'en')
    assert reviewed['beats'][0]['parts']==[script['beats'][0]['parts'][1]]
    assert reviewed['beats'][0]['visuals']==script['beats'][0]['visuals']
    assert len(script['beats'][0]['parts'])==2

def test_idle_details_require_actual_reviewed_facts_and_keep_english():
    from services.character_ai.aside_quality import appearance_choices
    facts=appearance_choices(dict(appearance_facts=['银灰色长发','清透蓝色双眼']),[],'en')
    assert len(facts)==2 and all('色' not in text for text in facts)
    beat=Beat(beat_id='b',dialogue=dict(text='Hmm… are you busy?'),asides=[dict(text='I wonder how your day is going.')],
        details=[(facts[0],'before')])
    parts=compile_parts(beat,dict(performances=[]),'en',visible_details=facts)
    assert any(p['kind']=='thought' for p in parts) and any(p['text']==facts[0] and p['kind']=='narration' for p in parts)
    assert all(p['kind']!='narration' for p in compile_parts(beat,dict(performances=[]),'en'))
    assert appearance_choices(dict(appearance_facts=[]),[],'zh')==[]

def test_source_review_rejects_repeated_psychology_but_accepts_new_feelings():
    from services.character_ai.aside_quality import plan_problem
    from services.character_ai.schemas import Plan
    plan=Plan(beats=[Beat(beat_id='b',dialogue=dict(text='当然可以呀～'),asides=[dict(text='我有点期待你的回应。')])])
    assert plan_problem(plan,['我有点期待你的回应。'])
    plan.beats[0].asides[0].text='我忽然想到纸上的那个小谜题。'
    assert plan_problem(plan,['我有点期待你的回应。']) is None

def test_aside_only_correction_keeps_valid_answer_topic():
    from services.character_ai.provider import structured_messages
    from services.character_ai.schemas import CoreTimelinePlan
    from services.character_ai.prompts import CORE_PLANNER
    context=dict(recent_messages=[],user_message='怎么画圆？',novelty_correction=dict(
        instruction='只重写心声',rejected_text='我们先画一个圆。',preserve_dialogue=True))
    prompt=structured_messages('plan',CORE_PLANNER,context,CoreTimelinePlan)[0]['content']
    assert '保留正确台词，只重写' in prompt and '放弃这个草稿的中心意思' not in prompt
