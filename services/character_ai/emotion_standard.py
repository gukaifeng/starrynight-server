"""Versioned semantic performance standard, independent of provider voice tags.

No inference here: retain AI-authored words/thoughts, normalize only controls.
Compatible neighbours avoid an unmotivated emotional jump on warm consumption.
"""
import json,re
from pathlib import Path
from .reply_text import visible_thought
from .aside_quality import allowed_language, repeated
CATALOG=json.loads(Path(__file__).with_name('emotion_standard.json').read_text())
ENTRIES={(v['kind'],v['id']):v for v in CATALOG['entries']}
EMOTIONS=tuple(k for kind,k in ENTRIES if kind=='emotion')
STYLES=tuple(k for kind,k in ENTRIES if kind=='style')
VOCALS=tuple(k for kind,k in ENTRIES if kind=='vocal')
NEIGHBOURS={
'neutral':'calm','calm':'neutral','happy':'playful','playful':'happy','excited':'happy',
'sad':'worried','crying':'sad','angry':'serious','worried':'empathetic','fearful':'worried',
'panicked':'fearful','surprised':'curious','curious':'thoughtful','thoughtful':'curious',
'serious':'thoughtful','empathetic':'affectionate','affectionate':'shy','shy':'affectionate',
'sarcastic':'playful','scornful':'serious','reluctant':'worried','bored':'tired','tired':'calm',
'confident':'hopeful','grateful':'affectionate','jealous':'shy','relieved':'calm','hopeful':'happy'}
POLICY='''情感表演标准 v1：每个beat恰好一句完整台词，情绪变化用新的beat；不要在一个beat塞两句。普通回复仍只需1至2句，总字数不增加。每句含至少一条针对当前句的第一人称真实心理感受asides，visible，不混入台词；首句、问候、待机、手势反应、预准备和快速接话一律相同。心理不复述动作或回复策略，可放完整句前后。每句明确mood；相邻两句（包括上一轮最后一句）mood不同，参考emotion_context.last，选择语义相近的自然转折，不随机改变立场、不刻意制造悲喜跳变。情绪、style和拟声vocals是不同维度；按情境使用，不为覆盖标签制造大喊或咳嗽。每次拟声用{event,at}，at为在句中实际位置0至1，不要在台词里写厂商方括号标签。'''

def contract(request):return getattr(request,'emotion_contract',0)==1

def context(store,owner,character,request):
    last=store.get('sentence_emotion.v1',owner,character,'')
    # Published partial replies are authoritative even before their tail commits.
    row=store.db.execute("SELECT data FROM messages WHERE owner=? AND character=? AND role='assistant' ORDER BY created DESC LIMIT 1",(owner,character)).fetchone()
    if row:
        data=json.loads(row['data'])
        cues=[c.get('emotion') for b in data.get('beats',[]) for c in b.get('sentences',[])]
        tags=[b.get('dialogue',{}).get('speech',{}).get('emotion') for b in data.get('beats',[]) if b.get('dialogue')]
        valid=[e for e in cues or tags if e in EMOTIONS]
        if valid:last=valid[-1]
    return dict(revision=1,last=last or getattr(request,'previous_emotion',''),emotions=list(EMOTIONS),styles=list(STYLES),vocals=list(VOCALS),rule=POLICY)

def next_emotion(value,previous):
    value=value if value in EMOTIONS else 'neutral'
    return NEIGHBOURS[value] if value==previous else value

def sentence_ranges(text):
    # Real sentence ends; ellipses, initials, decimals and rhetorical pauses stay.
    from .reply_flow import PROTECTED,CLOSERS
    spans=[m.span() for m in PROTECTED.finditer(text)]
    out=[];start=0;i=0
    while i<len(text):
        c=text[i]
        terminal=c in '。！？!?' or (c=='.' and not (i and text[i-1].isdigit() and i+1<len(text) and text[i+1].isdigit()) and not (i+1<len(text) and text[i+1]=='.') and not (i and text[i-1]=='.'))
        if terminal and not any(a<=i<b for a,b in spans):
            end=i+1
            while end<len(text) and (text[end] in CLOSERS or text[end] in '。！？!?' or text[end].isspace()):end+=1
            if text[start:end].strip():out.append((start,end))
            start=end;i=end;continue
        i+=1
    if text[start:].strip():out.append((start,len(text)))
    return out or [(0,len(text))]

def normalize(beat,previous,language,recent=()):
    """One speech/PCM segment per sentence; no invented thought or dialogue."""
    from .schemas import StagedThought
    if not beat.dialogue:return [beat],previous
    candidates=[a for a in beat.asides if a.visibility=='visible' and visible_thought(a.text) and allowed_language(a.text,language) and not repeated(a.text,recent)]
    if not candidates and beat.thought and beat.thought.visibility=='visible' and visible_thought(beat.thought.text) and allowed_language(beat.thought.text,language) and not repeated(beat.thought.text,recent):
        candidates=[StagedThought(text=beat.thought.text,stage='before')]
    if not candidates:raise ValueError('SENTENCE_THOUGHT_MISSING')
    ranges=sentence_ranges(beat.dialogue.text);result=[]
    if len(ranges)>len(candidates):raise ValueError('SENTENCE_THOUGHT_COVERAGE')
    for i,(a,b) in enumerate(ranges):
        v=beat.model_copy(deep=True)
        v.beat_id=(beat.beat_id[:23]+f'_s{i+1}') if len(ranges)>1 else beat.beat_id
        v.dialogue.text=beat.dialogue.text[a:b].strip()
        v.dialogue.speech.emotion=next_emotion(v.dialogue.speech.emotion,previous)
        previous=v.dialogue.speech.emotion
        v.asides=[candidates[i].model_copy(update={'stage':'before' if i==0 else 'after','after_text':''})] if len(ranges)>1 else candidates
        v.thought=None
        if i:v.vocal_events=[] # Original beat events belong to its onset.
        result.append(v)
    return result,previous

def review(script,previous):
    """Consume-time control review; preserve the already cached PCM and wording."""
    result={**script,'emotion_contract':1,'beats':[]}
    for raw in script.get('beats',[]):
        b={**raw}
        if b.get('dialogue'):
            speech=dict(b['dialogue'].get('speech') or {})
            # Preserve actual provider controls for diagnostic inspection.
            speech.setdefault('voice_emotion',speech.get('emotion','neutral'))
            speech['emotion']=next_emotion(speech.get('emotion','neutral'),previous)
            previous=speech['emotion']
            b['dialogue']={**b['dialogue'],'speech':speech}
        result['beats'].append(b)
    return result

def commit(store,owner,char,script):
    emotions=[b['dialogue']['speech']['emotion'] for b in script.get('beats',[]) if b.get('dialogue',{}).get('speech',{}).get('emotion')]
    if emotions:store.put('sentence_emotion.v1',owner,char,emotions[-1])
