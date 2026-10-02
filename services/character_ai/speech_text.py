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
ACTION = re.compile(r'^(?:(?:她|他|我|角色)\s*)?(?:(?:轻轻|轻|缓缓|稍稍)\s*)?(?:扶着|扶住|揉着|揉了揉|捂着|捂住|托着|撑着|抱着|抱住|攥着|握着|拉着|抿着|抿了抿|鼓起|撅起|皱着|皱起|蹙眉|偏过头|转过头|垂下|抬起|低下|伸出|收回|靠近|后退|故作|佯装)|^(?:(?:she|he|I)\s+)?(?:holds?|rubs?|covers?|tilts?|turns?|raises?|lowers?|pretends?|feigns?|frowns?|pouts?)\b',re.I)

def bracket_spans(text):
    """Outermost annotations, including incomplete and mixed-width parentheses.

    Used by the sentence compiler as well as speech: no pause inside a bracket
    may split the bracket into separate public dialogue parts.
    """
    i=0
    while i<len(text):
        if text[i] not in PAIRS:i+=1;continue
        start=i;stack=[PAIRS[text[i]]];i+=1
        while i<len(text) and stack:
            if text[i] in PAIRS:stack.append(PAIRS[text[i]])
            elif text[i]==stack[-1] or (text[i] in ')）' and stack[-1] in ')）'):stack.pop()
            i+=1
        yield start,i,not stack

def malformed_brackets(text):
    stack=[]
    for c in text:
        if c in PAIRS:stack.append(PAIRS[c])
        elif c in PAIRS.values():
            if not stack or not (c==stack[-1] or c in ')）' and stack[-1] in ')）'):return True
            stack.pop()
    return bool(stack)

def repair_orphan_closers(text):
    """Repair a legacy orphan direction without guessing ordinary speech away."""
    spans=list(bracket_spans(text));protected={i for a,b,_ in spans for i in range(a,b)}
    ends={b-1 for _,b,closed in spans if closed}
    edits=[];cursor=0
    for i,c in enumerate(text):
        if i in protected:
            if i in ends:cursor=i+1
            continue
        if c in PAIRS.values():
            # A broken continuation belongs to the latest complete clause/line.
            start=max(cursor,max((text.rfind(mark,cursor,i)+1 for mark in '\n。！？!?'),default=cursor))
            fragment=text[start:i]
            if is_direction(fragment):edits.append((start,i+1,'（'+fragment.strip()+'）'))
            else:edits.append((i,i+1,''))
            cursor=i+1
    for a,b,value in reversed(edits):text=text[:a]+value+text[b:]
    return text

def is_direction(value: str) -> bool:
    value = value.strip().strip('*_').strip()
    if len(value) > 160:
        return False
    # A question/discussion about tone is speech, not a delivery annotation.
    if re.search(r'(?:是什么|什么意思|怎么|为什么|是不是|吗[？?]?$)', value):
        return False
    return bool(LABEL.match(value) or GESTURE.match(value) or ACTION.match(value) or
                re.match(r'^神情|^(?:我|咱)(?:心里|有点|头都|也想|觉得)|^I (?:feel|wonder|hope)\b',value,re.I) or
                re.match(r'^(?:露出|轻翻|翻着|唇角|嘴角|眼睛变|眼神|心里|心想|暗自)|^(?:(?:she|I)\s+)?(?:smiles?|blinks?|nods?|waves?)\b',value,re.I) or
                re.match(r'^(?:声音|口吻)\s*[:：]', value))

def embedded_directions(text):
    repaired=repair_orphan_closers(text)
    for start,end,closed in bracket_spans(repaired):
        inside=repaired[start+1:end-1 if closed else end]
        if is_direction(inside):yield inside
        else:yield from embedded_directions(inside)

def spoken_text(value: str) -> str:
    # Pre-upgrade stored replies can contain a broken control fragment. New
    # plans reject it, and old playback must not pronounce its field names.
    if fragment := CONTROL_TEXT.search(value):
        value = value[:fragment.start()].rstrip(' \t\n,，\\"\'{}[]')
    value = re.sub(r'<(tone|delivery|emotion|stage_direction|narration|thought)\b[^>]*>.*?</\1\s*>', '', value, flags=re.I|re.S)
    value = repair_orphan_closers(visible_text(value))

    def clean(text):
        result = []; i = 0
        while i < len(text):
            if text[i] not in PAIRS:
                result.append(text[i]); i += 1; continue
            start = i; stack = [PAIRS[text[i]]]; i += 1
            while i < len(text) and stack:
                if text[i] in PAIRS: stack.append(PAIRS[text[i]])
                elif text[i] == stack[-1] or (text[i] in ')）' and stack[-1] in ')）'): stack.pop()
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

def audio_key(owner, character, voice, message, beat, *, revision=SPEECH_REVISION, text=''):
    parts = [owner, character, voice, message, beat]
    if revision: parts.append(revision)
    # Keep clean, offline-playable PCM cache entries; only suspect legacy
    # dialogue needs a new key. Never reuse bytes that pronounced directions.
    if text and (malformed_brackets(text) or next(embedded_directions(text),None) is not None):parts.append('annotations-v3')
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()
