"""Incremental JSON objects: complete strings/objects only, never regex repair."""
import json,re
from .schemas import Beat,Speech,StagedThought,GoalFeedback,CONTROL_TEXT

class Objects:
    def __init__(self,nested=False):self.buffer='';self.started=False;self.depth=0;self.quoted=False;self.escape=False;self.nested=nested;self.array_depth=0;self.beat_start=None;self.emitted=0
    def feed(self,chunk):
        result=[]
        for c in chunk:
            if not self.started:
                if c!='{':continue
                self.started=True;self.depth=1;self.buffer=c;self.emitted=0;continue
            self.buffer+=c
            if len(self.buffer)>16000:raise ValueError('STREAM_OBJECT_TOO_LARGE')
            if self.quoted:
                if self.escape:self.escape=False
                elif c=='\\':self.escape=True
                elif c=='"':self.quoted=False
            elif c=='"':self.quoted=True
            elif c=='[':self.array_depth+=1
            elif c==']':self.array_depth-=1
            elif c=='{':
                self.depth+=1
                if self.nested and self.depth==2 and self.array_depth==1 and re.match(r'^\s*\{\s*"beats"\s*:\s*\[',self.buffer):self.beat_start=len(self.buffer)-1
            elif c=='}':
                if self.nested and self.depth==2 and self.beat_start is not None and self.array_depth==1:
                    try:result.append(json.loads(self.buffer[self.beat_start:]));self.emitted+=1
                    except ValueError:raise ValueError('STREAM_JSON_INVALID') from None
                    self.beat_start=None
                self.depth-=1
                if not self.depth:
                    try:
                        root=json.loads(self.buffer)
                        if self.nested and not self.emitted:result.extend(root.get('beats',[]) if isinstance(root.get('beats'),list) else [])
                        result.append(root)
                    except ValueError:raise ValueError('STREAM_JSON_INVALID') from None
                    self.started=False;self.buffer=''
        return result

def beat(value,index):
    say=value.get('say')
    if not isinstance(say,str) or not say.strip() or len(say)>220 or CONTROL_TEXT.search(say):raise ValueError('STREAM_SPEECH_INVALID')
    # Optional direction errors do not regenerate or suppress legitimate speech.
    asides=[]
    for a in value.get('asides',[]) if isinstance(value.get('asides',[]),list) else []:
        try:
            if isinstance(a,list) and 2<=len(a)<=4:
                asides.append(StagedThought(text=a[0],stage=a[1],visibility=a[2] if len(a)>2 else 'visible',after_text=a[3] if len(a)>3 else ''))
            elif isinstance(a,dict):
                asides.append(StagedThought.model_validate(a))
        except (ValueError,TypeError):pass
    try:speech=Speech(emotion=value.get('mood','neutral'),style=value.get('style','plain'),delivery=value.get('tone','normal'),intensity=value.get('strength',.4))
    except ValueError:speech=Speech()
    from .schemas import Vocal
    vocals=[]
    for v in (value.get('vocals',[]) if isinstance(value.get('vocals'),list) else [])[:2]:
        try:vocals.append(Vocal.model_validate(v if isinstance(v,dict) else {'event':v}))
        except (ValueError,TypeError):pass
    return Beat(beat_id='b'+str(index),dialogue=dict(text=say.strip(),speech=speech),asides=asides[:3],vocal_events=vocals)

def feedback(value,text):
    try:
        result=GoalFeedback.model_validate(value)
        # No invented rationale or unevidenced progress.
        if not result.evidence or result.evidence not in text:return GoalFeedback()
        return result
    except (ValueError,TypeError):return GoalFeedback()
