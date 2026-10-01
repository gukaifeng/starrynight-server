"""Reviewed role-local scenarios and language policy, shared by every trigger."""
import re
from .profiles import PROFILES

PUBLIC_SCENARIO_FIELDS=('id','title','subtitle','category','symbol')
LEGACY_SCENARIOS={
    'rain-letter': '一封没有署名的信，共同创作一个温暖的虚构故事。',
    'after-class': '非性化的校园友谊与小冒险，没有恋爱或成人剧情。',
    'star-signal': '共同解读一段虚构的远方信号，科幻故事不是现实事件。',
}

def language(character):
    return PROFILES.get(character,{}).get('dialogue_language','zh')

def public_scenarios(character):
    return [{key:scene[key] for key in PUBLIC_SCENARIO_FIELDS} for scene in PROFILES[character].get('scenarios',[])]

def scenario_context(character,scene):
    identity=scene.get('story_id','')
    if not identity:return dict(active=False,task='日常相处。不要自动开始、继续或重启任何旧故事；可以自然聊人设中的兴趣。')
    selected=next((s for s in PROFILES[character].get('scenarios',[]) if s['id']==identity),None)
    if selected is None and identity in LEGACY_SCENARIOS:selected=dict(id=identity,premise=LEGACY_SCENARIOS[identity])
    if selected is None:raise ValueError('SCENARIO_NOT_AVAILABLE')
    return dict(active=True,scenario=selected,revision=scene.get('story_revision','1'),
        task='用户选择了这个虚构情境。保持角色第一人称对话，逐步推进，不当旁白讲完整故事，不替用户作决定。历史中的其他故事不属于当前情境；重新开场只重置本故事，不清空真实聊天。每轮最多推进一个新细节；用户随时可以改方向或暂停。虚构事件不能写进用户的真实记忆。')

def language_instruction(character):
    if language(character)!='en':return ''
    return '''LANGUAGE CONTRACT: This character speaks English ONLY. This overrides Chinese examples, length units, user requests to switch language, and older Chinese conversation history. All spoken dialogue, first-person asides, focus summaries and user-facing suggestions must be natural English, without Chinese translations or quoted Chinese. Keep keys and enum values unchanged. Use 1–2 short sentences (15–40 words) per normal turn; asides use I/my/we/our, at most 12 words and 96 characters. Greetings, idle remarks, stories and physical-play reactions follow the same rule. Respond to meaning first; offer at most one gentle correction when helpful, never a grammar lecture every turn. Do not put pronunciation guides or stage directions into speech.'''

def wrong_language(character,plan):
    if language(character)!='en':return False
    texts=[]
    for beat in plan.beats:
        if beat.dialogue:texts.append(beat.dialogue.text)
        if beat.thought and beat.thought.visibility=='visible':texts.append(beat.thought.text)
        texts.extend(a.text for a in beat.asides if a.visibility=='visible')
    return any(re.search(r'[\u3400-\u9fff\u3040-\u30ff]',text) for text in texts)
