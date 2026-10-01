import random
import pytest
from services.character_ai.config import Settings
from services.character_ai.schemas import Beat
from services.character_ai.storage import Store
from services.character_ai.profiles import assets
from services.character_ai.director import Director
from services.character_ai.provider import speech_input,speech_payload
from services.character_ai.prompts import CORE_PLANNER,PLANNER

@pytest.mark.parametrize('text,spoken',[
    ('emmmm……我再想想，好不好？','嗯……我再想想，好不好？'),
    ('Hmmmm… I need a moment.','Hmm… I need a moment.'),
    ('诶？真的呀～','诶？真的呀～'),
    ('这个宽 5 mm，英文是summer。','这个宽 5 mm，英文是summer。'),
])
def test_interjections_and_punctuation_remain_spoken_without_stage_directions(text,spoken):
    beat=dict(dialogue=dict(text=text+'（语气：迟疑）',speech=dict(emotion='neutral',delivery='hesitant')),
        thought='我想一想。',narrations=[dict(text='这不是台词。')])
    value,instruction=speech_input(beat)
    assert value==spoken and beat['dialogue']['text'].startswith(text)
    assert '迟疑' in instruction and '不拼读字母' in instruction
    payload=speech_payload(Settings(),'anime-kipfel',beat,'test-voice')
    assert payload['input']['text']==spoken and payload['input']['voice']=='test-voice'
    assert 'instruction' in payload['input'] and '思考' in payload['input']['instruction']

@pytest.mark.parametrize('role',['anime-kipfel','anime-mamehinata','anime-karin','anime-chiffon'])
@pytest.mark.parametrize('tone,face',[('hesitant','thinking'),('teasing','teasing_smile'),('gentle','soft_smile')])
def test_speech_delivery_uses_each_avatars_own_supported_expression(tmp_path,role,tone,face):
    expected=face
    if role in ('anime-karin','anime-chiffon') and tone=='hesitant':expected='confused'
    if role=='anime-chiffon' and tone=='teasing':expected='soft_smile'
    library=assets(role);matching=[a for a in library if a['kind']=='expression' and a['intent']==expected]
    assert matching, 'Fixture must exercise an actual author-supported face'
    store=Store(tmp_path/'state.db')
    try:
        beat=Beat(beat_id='b',dialogue=dict(text='嗯……我想多听听你的想法，再一起试试看。',speech=dict(delivery=tone)))
        resolved=Director(store,random.Random(4)).beat('u',role,beat,{}, {},[a['asset_id'] for a in library])
        assert resolved['expression_asset']['intent']==expected
        assert all(c['asset']['asset_id'] in {a['asset_id'] for a in library} for c in resolved['performances'])
        if tone=='hesitant':assert any(c['offset_ms']>=2200 and c['asset']['intent']=='soft_smile' for c in resolved['performances'])
    finally:store.db.close()

def test_core_and_full_planning_share_texture_without_canned_dialogue():
    for prompt in [PLANNER,CORE_PLANNER]:
        assert '通常自然使用1至2处' in prompt and '不是固定台词' in prompt
        assert 'speech.delivery=hesitant' in prompt and '不能一边在台词' in prompt
