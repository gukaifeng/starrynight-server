from services.character_ai.config import Settings
from services.character_ai.provider import structured_payload, structured_messages
from services.character_ai.quick_replies import SUGGESTIONS
from services.character_ai.schemas import QuickReplyPlan


def test_prediction_uses_fast_non_thinking_model_without_changing_character_answers():
    settings = Settings(suggestions_model='qwen-turbo', character_model='qwen-plus-character')
    messages = structured_messages('suggestions', SUGGESTIONS, {}, QuickReplyPlan)
    prediction = structured_payload(settings, 'suggestions', messages)
    assert prediction['model'] == 'qwen-turbo'
    assert prediction['enable_thinking'] is False
    assert prediction['max_tokens'] == 320
    answer = structured_payload(settings, 'plan', messages)
    assert answer['model'] == 'qwen-plus-character'
    assert 'enable_thinking' not in answer
    performance=structured_payload(settings,'performance',messages)
    assert performance['model']=='qwen-turbo' and performance['enable_thinking'] is False
    override=structured_payload(Settings(performance_model='configured-control-model'),'performance',messages)
    assert override['model']=='configured-control-model'


def test_preparation_has_its_own_character_model_without_rerouting_controls():
    settings=Settings(preparation_model='qwen-flash-character')
    messages=[dict(role='user',content='test')]
    assert structured_payload(settings,'plan',messages,preparation=True)['model']=='qwen-flash-character'
    assert structured_payload(settings,'plan',messages)['model']=='qwen-plus-character'
    assert structured_payload(settings,'performance',messages,preparation=True)['model']=='qwen-turbo'
    assert structured_payload(settings,'suggestions',messages,preparation=True)['model']=='qwen-turbo'


def test_suggestion_schema_keeps_validation_and_can_be_decoded():
    messages = structured_messages('suggestions', SUGGESTIONS, {}, QuickReplyPlan)
    assert 'minItems' in messages[0]['content']
    assert 'maxItems' in messages[0]['content']
    result = QuickReplyPlan.model_validate_json('{"options":[{"text":"想听旧书的故事","likelihood":0.7},{"text":"陪我安静坐会儿吧","likelihood":0.2},{"text":"你今天过得怎么样","likelihood":0.1}]}')
    assert len(result.options) == 3
