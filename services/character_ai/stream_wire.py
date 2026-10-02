"""Incremental JSON objects: complete strings/objects only, never regex repair."""
import json
from .schemas import Beat,Speech,StagedThought,GoalFeedback,CONTROL_TEXT

class Objects:
    def __init__(self):self.buffer='';self.started=False;self.depth=0;self.quoted=False;self.escape=False
    def feed(self,chunk):
        result=[]
        for c in chunk:
            if not self.started:
                if c!='{':continue
                self.started=True;self.depth=1;self.buffer=c;continue
            self.buffer+=c
            if len(self.buffer)>16000:raise ValueError('STREAM_OBJECT_TOO_LARGE')
            if self.quoted:
                if self.escape:self.escape=False
                elif c=='\\':self.escape=True
                elif c=='"':self.quoted=False
            elif c=='"':self.quoted=True
            elif c=='{':self.depth+=1
            elif c=='}':
                self.depth-=1
                if not self.depth:
                    try:result.append(json.loads(self.buffer))
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
        except (ValueError,TypeError):pass
    try:speech=Speech(emotion=value.get('mood','neutral'),delivery=value.get('tone','normal'),intensity=value.get('strength',.4))
    except ValueError:speech=Speech()
    return Beat(beat_id='b'+str(index),dialogue=dict(text=say.strip(),speech=speech),asides=asides[:3])

def feedback(value,text):
    try:
        result=GoalFeedback.model_validate(value)
        # No invented rationale or unevidenced progress.
        if not result.evidence or result.evidence not in text:return GoalFeedback()
        return result
    except (ValueError,TypeError):return GoalFeedback()
