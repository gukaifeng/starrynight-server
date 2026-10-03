"""Private compact planner wire format; public timeline-v2 stays unchanged.

Avoid asking a token-by-token character model to generate nested defaults,
repeated field names and routing IDs. Strictly expand into the existing Plan
before novelty checks, publication, performance resolution or any TTS expense.
No text or aside is invented by the adapter.
"""
from typing import Literal
import re
from pydantic import Field, field_validator, TypeAdapter, ValidationError
from .schemas import Strict, Speech, VocalType, MemoryProposal, TimelinePlan, CoreTimelinePlan, GoalFeedback

Cue = tuple[str,str] | tuple[str,str,int] | tuple[str,str,int,bool]
Aside = tuple[str,Literal['before','middle','after']] | tuple[str,Literal['before','middle','after'],Literal['visible','hidden','unlock_required']] | tuple[str,Literal['before','middle','after'],Literal['visible','hidden','unlock_required'],str]

class PositionedVocal(Strict):
    event:VocalType
    at:float=Field(default=0,ge=0,le=1)
    intensity:float=Field(default=.3,ge=0,le=1)

class SpokenBeat(Strict):
    say: str | None = Field(default=None,max_length=220)
    mood: Speech.model_fields['emotion'].annotation = 'neutral'
    style: Speech.model_fields['style'].annotation = 'plain'
    tone: Speech.model_fields['delivery'].annotation = 'normal'
    strength: float = Field(default=.4,ge=0,le=1)
    asides: list[Aside] = Field(min_length=1,max_length=3)
    details: list[tuple[str,Literal['before','middle','after']]] = Field(default_factory=list,max_length=1)
    vocals: list[VocalType | PositionedVocal] = Field(default_factory=list,max_length=2)

    @field_validator('mood',mode='before')
    @classmethod
    def canonical_mood(cls,value):return Speech.canonical_emotion(value)

    @field_validator('tone',mode='before')
    @classmethod
    def canonical_tone(cls,value):return Speech.canonical_delivery(value)

class CompactBeat(SpokenBeat):
    cues: list[Cue] = Field(default_factory=list,max_length=24)

class CompactPlan(Strict):
    goal_feedback: GoalFeedback = Field(default_factory=GoalFeedback)
    focus: str = Field(min_length=1,max_length=100)
    beats: list[CompactBeat] = Field(default_factory=list,max_length=3)
    idle: Literal['do_nothing','visual_only','thought_only','proactive_speech'] | None = None
    state: dict[str,float] = Field(default_factory=dict)
    memory: list[MemoryProposal] = Field(default_factory=list,max_length=2)

    def expand(self,schema):
        beats=[]
        for i,b in enumerate(self.beats):
            beats.append(dict(beat_id=f'b{i+1}',
                dialogue=dict(text=b.say,speech=dict(emotion=b.mood,style=b.style,delivery=b.tone,intensity=b.strength)) if b.say is not None else None,
                asides=[dict(text=a[0],stage=a[1],visibility=a[2] if len(a)>2 else 'visible',after_text=a[3] if len(a)>3 else '') for a in b.asides],
                details=b.details,
                performance=dict(intensity=b.strength,cues=[dict(group=c[0],intent=c[1],offset_ms=c[2] if len(c)>2 else 0,active=c[3] if len(c)>3 else True) for c in getattr(b,'cues',[])]),
                vocal_events=[v.model_dump() if isinstance(v,PositionedVocal) else dict(event=v,intensity=b.strength) for v in b.vocals]))
        return schema.model_validate(dict(goal_feedback=self.goal_feedback,response_focus=self.focus,beats=beats,idle_decision=self.idle,
            reply_type='idle_event' if self.idle else 'normal_reply',suggested_state_delta=self.state,memory_updates=self.memory))

class SpokenPlan(CompactPlan):
    beats: list[SpokenBeat] = Field(default_factory=list,max_length=3)

class GroundedGoalFeedback(GoalFeedback):
    familiarity: float = Field(ge=-.04,le=.04)
    trust: float = Field(ge=-.04,le=.04)
    affection: float = Field(ge=-.04,le=.04)
    task_progress: float = Field(ge=-.04,le=.04)
    evidence: str = Field(min_length=1,max_length=100)

class GoalCompactPlan(CompactPlan):
    goal_feedback: GroundedGoalFeedback

class GoalSpokenPlan(SpokenPlan):
    goal_feedback: GroundedGoalFeedback

def optional_controls(data,schema):
    """Provider-only projection. Public request schemas remain strict.

    Unknown decoration must not invalidate correct speech. Never repair, truncate
    or invent `say`; expand still runs Dialogue's content/format validation.
    """
    if not issubclass(schema,CompactPlan) or not isinstance(data,dict):return data,0
    cleaned={k:v for k,v in data.items() if k in schema.model_fields}
    removed=len(data)-len(cleaned)
    beat_schema=SpokenBeat if issubclass(schema,SpokenPlan) else CompactBeat
    if isinstance(data.get('beats'),list):
        beats=[]
        for value in data['beats']:
            if not isinstance(value,dict):beats.append(value);continue
            b={k:v for k,v in value.items() if k in beat_schema.model_fields}
            removed+=len(value)-len(b)
            # These are optional presentation controls, never spoken content.
            for key in ('asides','details','vocals','cues'):
                if key not in beat_schema.model_fields or key not in b:continue
                adapter=TypeAdapter(beat_schema.model_fields[key].annotation.__args__[0])
                accepted=[]
                for item in b[key] if isinstance(b[key],list) else []:
                    try:accepted.append(adapter.validate_python(item))
                    except (ValidationError,TypeError,ValueError):removed+=1
                b[key]=accepted[:3 if key=='asides' else 1 if key=='details' else 2 if key=='vocals' else 24]
            # No invented visible aside when all optional proposals were bad.
            if not b.get('asides'):b['asides']=[('','before','hidden')]
            beats.append(b)
        cleaned['beats']=beats
    return cleaned,removed

def wire_schema(purpose,schema,context=None):
    grounded=bool(context and context.get('goal_context',{}).get('config_version') and context.get('trigger') in ('user_message','story') and context.get('user_message','').strip())
    if purpose=='plan' and issubclass(schema,CoreTimelinePlan):return GoalSpokenPlan if grounded else SpokenPlan
    return (GoalCompactPlan if grounded else CompactPlan) if purpose=='plan' and issubclass(schema,TimelinePlan) else schema

def wire_system(system):
    """Same content rules, expressed in the private wire's field vocabulary."""
    for old,new in (('response_focus','focus'),('suggested_state_delta','state'),('memory_updates','memory'),
                    ('idle_decision','idle'),('dialogue.text','say'),('speech.emotion','mood'),('speech.delivery','tone'),
                    ('performance.cues','cues'),('vocal_events','vocals')):
        system=re.sub(r'(?<![a-zA-Z0-9_])'+re.escape(old)+r'(?![a-zA-Z0-9_])',new,system)
    return system

WIRE_SHAPE='''输出紧凑JSON，遵循此结构，不输出旧格式的dialogue/performance/beat_id：
{"focus":"<这轮的新内容点>","beats":[{"say":"<本轮台词>","mood":"happy","tone":"gentle","asides":[["<开口时的短心声>","before"],["<话语转折后的短心声>","after"]],"cues":[["<group>","<intent>"]]}]}
asides为数组：[心声,阶段]，阶段before/middle/after，通常2条。需要隐藏时用[心声,阶段,"hidden"]；精确锚点用[心声,阶段,"visible",带结尾标点的完整台词短句]。只在完整语句/自然停顿处插入，不拆词，无停顿则放整句前后。问候及预缓存场景同样适用。
cues为数组：[group,intent]，可补第三项offset_ms、第四项active布尔。普通交谈只选1至2个关键cue，导演会扩展丰富的多组多阶段表演；用户明确要求多个时全部表达。不需要额外表现时省略cues。
mood和tone用Schema里的英文枚举。可选strength为0至1；vocals只列声音事件名。不要输出默认值、空数组或空对象凑字段；需要用户记忆、关系变化或待机决策时才填memory/state/idle。'''

SPOKEN_SHAPE='''只输出核心JSON：{"focus":"<本轮新内容>","beats":[{"say":"<台词>","mood":"happy","tone":"gentle","asides":[["<当前感受>","before"]]}]}。
asides=[第一人称心声,before/middle/after]；可加visible/hidden、带结尾标点的完整台词锚点，不拆词；中文用我/咱、英文用I/my/we/our。每句遵循当前情感标准。details=[visible_details原文,阶段]最多1条。mood/tone/style用Schema枚举；不生成cues、performance或资源ID，省略空字段。'''
