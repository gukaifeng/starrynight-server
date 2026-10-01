"""Compile ordered speech/asides before publishing, using only resolved effects.

Parts are additive wire metadata; spoken dialogue remains the sole TTS input.
`at` is a fraction of spoken text, not a fabricated provider word timestamp.
"""
import re
from .reply_text import visible_text, visible_thought

REVISION=3
PAUSES=re.compile(r'[，。！？；：、…⋯～~!?;,.:\n\r—–]+')
HESITATION=re.compile(r'(?<![A-Za-z0-9_])(?:e+m{2,}|h+m{2,}|u+m{2,})(?![A-Za-z0-9_])',re.I)
PROTECTED=re.compile(r'https?://[^\s，。！？；]+|www\.[^\s，。！？；]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc)\.|\b(?:[A-Za-z]\.){2,}',re.I)
CLOSERS="”’」』）》】)]}\"'"

def safe_boundaries(text):
    """Clause/pause edges only. Never guess a character or a word boundary.

    A missing/mistyped LLM anchor must not split 薰衣草, a Latin word, an
    ellipsis, a number, or a URL. Ambiguous unpunctuated speech stays whole.
    """
    points={0,len(text)}
    protected=[m.span() for m in PROTECTED.finditer(text)]
    def protected_at(index):return any(a<=index<b for a,b in protected)
    def finish(index):
        # Keep all trailing punctuation and closing quotes with the clause.
        while index<len(text) and (text[index] in CLOSERS or text[index].isspace() or PAUSES.fullmatch(text[index])):index+=1
        return index
    for match in PAUSES.finditer(text):
        a,b=match.span()
        if protected_at(a):continue
        if a and b<len(text) and text[a-1].isdigit() and text[b].isdigit() and match.group() in ('.',',',':'):continue
        points.add(finish(b))
    for match in HESITATION.finditer(text):
        if not protected_at(match.start()):points.update((match.start(),finish(match.end())))
    return sorted(points)

def duration_hint(text):
    cjk=len(re.findall(r'[\u3400-\u9fff]',text))
    if not cjk and re.search(r'[a-zA-Z]',text):return max(1.8,min(45,len(text.split())/2.6))
    return max(1.8,min(45,len(text)/5.5))

def boundary(text,fraction):
    if fraction<=0:return 0
    if fraction>=1:return len(text)
    target=round(len(text)*fraction)
    internal=[p for p in safe_boundaries(text) if 0<p<len(text)]
    return min(internal,key=lambda p:(abs(p-target),-p)) if internal else len(text)

def anchored_boundary(text,anchor,fraction):
    start=text.find(anchor) if anchor else -1
    if start<0:return boundary(text,fraction)
    # Anchors may end in the middle of a noun; advance to the next real pause.
    end=start+len(anchor)
    return next(p for p in safe_boundaries(text) if p>=end)

def compile_parts(beat,resolved,language='zh'):
    text=visible_text(beat.dialogue.text) if beat.dialogue else ''
    thoughts=list(beat.asides)
    if not thoughts and beat.thought:
        thoughts=[beat.thought]
    return compile_text_parts(text,thoughts,resolved.get('performances',[]),language)

def compile_text_parts(text,thoughts,performances=(),language='zh'):
    """Shared by live, prepared and bundled first-meeting content."""
    size=max(1,len(text));markers=[];seen=set()
    for ordinal,thought in enumerate(thoughts):
        value=visible_thought(thought.text) if thought.visibility=='visible' else None
        anchor=getattr(thought,'after_text','')
        if not value or value in seen:continue
        stage=getattr(thought,'stage','before')
        fraction={'before':0,'middle':(ordinal+1)/(len(thoughts)+1),'after':1}[stage]
        index=anchored_boundary(text,anchor,fraction)
        markers.append((index,'thought',value));seen.add(value)
    # Select one genuine observation at onset and one at the later phase.
    # Do not duplicate every simultaneous hand/ear/tail cue in the transcript.
    cues=[c for c in performances if c['active'] and c['asset'].get('observable_effects')] if language!='en' else []
    phases=[sorted([c for c in cues if c['offset_ms']<1200],key=lambda c:(c['asset']['group']!='expression',c['offset_ms'])),
            sorted([c for c in cues if c['offset_ms']>=1200],key=lambda c:c['offset_ms'])]
    for phase in phases:
        for cue in phase:
            value=visible_text(cue['asset']['observable_effects'][0])
            if value in seen:continue
            fraction=min(.8,cue['offset_ms']/1000/duration_hint(text)) if text else 0
            markers.append((boundary(text,fraction),'narration',value));seen.add(value);break
    parts=[];cursor=0
    for index,kind,value in sorted(markers,key=lambda m:m[0]):
        if index>cursor:
            parts.append(dict(kind='dialogue',text=text[cursor:index],at=round(cursor/size,4)))
            cursor=index
        parts.append(dict(kind=kind,text=value,at=round(index/size,4)))
    if cursor<len(text):parts.append(dict(kind='dialogue',text=text[cursor:],at=round(cursor/size,4)))
    return parts
