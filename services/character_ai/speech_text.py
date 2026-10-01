"""Deterministic speech boundary, including replay of pre-upgrade dialogue.

Stage directions belong to the planner's structured fields. TTS providers do
not consistently treat parentheses as instructions, so never delegate that
decision to them. Ordinary parenthetical speech must remain intact.
"""
import hashlib
import re
from .schemas import visible_text, CONTROL_TEXT

SPEECH_REVISION = 'spoken-v2'
PAIRS = {'（': '）', '(': ')', '[': ']', '【': '】', '〔': '〕'}
LABEL = re.compile(r'^(?:(?:她|我|角色)\s*)?(?:语气|语调|语速|音量|音色|声线|声音|口吻|情绪|表情|神态|动作|旁白|心声|心理活动|内心独白)(?=\s*[:：]|\s*[\u3400-\u9fff]|$)|^(?:tone|delivery|emotion|stage direction)\s*[:：]', re.I)
GESTURE = re.compile(r'^(?:(?:她|我|角色)\s*)?(?:微笑|轻笑|笑着|含笑|眨眼|眨了|点头|摇头|歪头|抬头|低头|叹气|叹了|深吸|停顿|沉默|轻声|小声|柔声|低声|轻轻地?说|温柔地?说|(?:开心|平静|好奇|害羞|兴奋)地|用.{0,24}(?:语气|语调)|以.{0,24}(?:语气|语调))')

def is_direction(value: str) -> bool:
    value = value.strip().strip('*_').strip()
    if len(value) > 160:
        return False
    # A question/discussion about tone is speech, not a delivery annotation.
    if re.search(r'(?:是什么|什么意思|怎么|为什么|是不是|吗[？?]?$)', value):
        return False
    return bool(LABEL.match(value) or GESTURE.match(value) or
                re.match(r'^(?:声音|口吻)\s*[:：]', value))

def spoken_text(value: str) -> str:
    # Pre-upgrade stored replies can contain a broken control fragment. New
    # plans reject it, and old playback must not pronounce its field names.
    if fragment := CONTROL_TEXT.search(value):
        value = value[:fragment.start()].rstrip(' \t\n,，\\"\'{}[]')
    value = re.sub(r'<(tone|delivery|emotion|stage_direction|narration|thought)\b[^>]*>.*?</\1\s*>', '', value, flags=re.I|re.S)
    value = visible_text(value)

    def clean(text):
        result = []; i = 0
        while i < len(text):
            if text[i] not in PAIRS:
                result.append(text[i]); i += 1; continue
            start = i; stack = [PAIRS[text[i]]]; i += 1
            while i < len(text) and stack:
                if text[i] in PAIRS: stack.append(PAIRS[text[i]])
                elif text[i] == stack[-1]: stack.pop()
                i += 1
            closed = not stack
            inside = text[start+1:i-1 if closed else i]
            if not is_direction(inside):
                result.append(text[start]+clean(inside)+(text[i-1] if closed else ''))
        return ''.join(result)

    value = clean(value)
    # Models occasionally use Markdown stage directions instead of parentheses.
    value = re.sub(r'\*{1,2}([^*\n]{1,160})\*{1,2}',
                   lambda m: '' if is_direction(m[1]) else m[1], value)
    value = re.sub(r'[ \t]+', ' ', value)
    value = re.sub(r'([。！？!?，,；;])\s*[。。，,；;]+', r'\1', value)
    return value.strip(' \t\n。。，,；;') if not re.search(r'[\w\u4e00-\u9fff]', value) else value.strip()

def audio_key(owner, character, voice, message, beat, *, revision=SPEECH_REVISION):
    parts = [owner, character, voice, message, beat]
    if revision: parts.append(revision)
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()
