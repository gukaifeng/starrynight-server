import pytest
from services.character_ai.schemas import Beat
from services.character_ai.speech_text import spoken_text, audio_key, bracket_spans, malformed_brackets
from services.character_ai.provider import speech_input
from services.character_ai.reply_flow import safe_boundaries, compile_parts

REPORTED='（我头都晕了，好过分）\n（露出一点小小不满）\n你是不是晃上瘾了！（扶着额头，）\n（神情变得轻松愉快）\n故作痛苦）\n再晃我可就要罢工，不让你试吃了。'

def test_exact_reported_reply_never_speaks_the_orphan_action():
    result=spoken_text(REPORTED)
    assert '扶着' not in result and '故作' not in result and '神情' not in result and '我头' not in result
    assert '你是不是晃上瘾了！' in result and '再晃我可就要罢工，不让你试吃了。' in result
    assert not any(c in result for c in '（）()')
    assert speech_input(dict(dialogue=dict(text=REPORTED)))[0]==result
    assert spoken_text('慢一点！（扶着额头，）故作痛苦）再聊吧。')=='慢一点！再聊吧。'

@pytest.mark.parametrize('text',[
    '你是不是晃上瘾了！（扶着额头，故作痛苦）再晃我可就要罢工了。',
    '好啦。（揉了揉额头，（故作痛苦））慢一点呀。',
    'Wait! (I rub my forehead, feigning pain.) Be gentle.',
    '等等！（扶着额头, 故作痛苦)轻一点。',
])
def test_new_plans_reject_actions_in_speech_before_tts(text):
    with pytest.raises(ValueError,match='stage directions'):
        Beat(beat_id='b',dialogue=dict(text=text))

@pytest.mark.parametrize('text',['故作痛苦）再聊吧。','你好）','明天（如果有空'])
def test_new_plans_reject_unmatched_brackets(text):
    with pytest.raises(ValueError,match='stage directions|unmatched brackets'):
        Beat(beat_id='b',dialogue=dict(text=text))

def test_compiler_never_inserts_asides_inside_any_parenthesis_or_word():
    text='我们明天（如果有空，或者早点下班）再聊，嗯……就这样。'
    spans=list(bracket_spans(text))
    points=safe_boundaries(text)
    assert all(not any(a<point<b for a,b,_ in spans) for point in points)
    beat=Beat(beat_id='b',dialogue=dict(text=text),asides=[dict(text='我有点期待。',stage='middle')])
    parts=compile_parts(beat,dict(performances=[]))
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')==text
    assert all(not malformed_brackets(p['text']) for p in parts if p['kind']=='dialogue')
    assert spoken_text('维生素（B12）是这个名字。')=='维生素（B12）是这个名字。'

def test_cache_revision_is_selective_clean_offline_clips_are_preserved():
    args=('u','c','voice','message','beat')
    old=audio_key(*args)
    assert audio_key(*args,text='你好！')==old
    assert audio_key(*args,text='明天（如果有空）再聊。')==old
    assert audio_key(*args,text='等等！（扶着额头，故作痛苦）轻一点。')!=old
    assert audio_key(*args,text=REPORTED)!=old
