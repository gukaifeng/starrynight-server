"""Optional, turn-owned avatar planning. Failures never fail core conversation."""
import asyncio
import time
from pydantic import Field
from .schemas import Strict, PerformanceCue, Performance
from .prompts import PERFORMER
from .provider import planner_data
from .profiles import assets

class PerformancePlan(Strict):
    cues: list[PerformanceCue] = Field(default_factory=list,max_length=24)

def performance_context(context):
    data=planner_data(context)
    return dict(avatar_capability=data.get('avatar_capability',{}),trigger=context['trigger'],
                intent_guide=context.get('avatar_capability',{}).get('intent_guide',{}),
                user_message=context.get('user_message',''),recent_messages=context.get('recent_messages',[])[-4:],
                interaction_context=context.get('interaction_context'),greeting_context=data.get('greeting_context'),
                roleplay_context=context.get('roleplay_context'),idle_context=context.get('idle_context'),
                personality=context.get('character_profile',{}).get('personality',{}))

async def plan_performance(engine,owner,request,context):
    start=time.monotonic();char=request.character_id
    try:
        async with asyncio.timeout(engine.settings.performance_timeout_seconds):
            result=await engine.provider.structured(owner,char,'performance',PERFORMER,performance_context(context),PerformancePlan)
        if engine.settings.enable_test_inspector:
            engine.store.put('performance_review',owner,char,dict(status='ready',elapsed_ms=round((time.monotonic()-start)*1000),plan=result.model_dump()))
        return result
    except Exception as error:
        # Do not promote optional schema/provider/timeout failures to a user
        # notice; automatic mood-driven motion is already available locally.
        engine.store.put('performance_review',owner,char,dict(status='skipped',reason=type(error).__name__,elapsed_ms=round((time.monotonic()-start)*1000)))
        return None

def resolved_visuals(resolved):
    return [dict(asset_id=c['asset']['asset_id'],group=c['asset']['group'],duration_ms=c['duration_ms'],
                 offset_ms=c['offset_ms'],active=c['active'],grounding=resolved['grounding']) for c in resolved['performances']]

def current_visuals(visuals,elapsed_ms):
    """Keep only the latest elapsed cue per group, plus future changes."""
    past={};future=[]
    for v in sorted(visuals,key=lambda v:v['offset_ms']):
        if v['offset_ms']<=elapsed_ms:past[v['group']]={**v,'offset_ms':0}
        else:future.append({**v,'offset_ms':v['offset_ms']-elapsed_ms})
    return sorted([*past.values(),*future],key=lambda v:v['offset_ms'])

def merge_visuals(base,extra,elapsed_ms):
    """Keep executed history and later automatic phases around a late update."""
    groups={v['group'] for v in extra}
    patch=[{**v,'offset_ms':v['offset_ms']+elapsed_ms} for v in current_visuals(extra,elapsed_ms)]
    retained=[v for v in base if v['group'] not in groups or v['offset_ms']<elapsed_ms]
    result=(retained+patch)[-24:]
    last={group:max(v['offset_ms'] for v in patch if v['group']==group) for group in groups}
    for v in sorted(base,key=lambda v:v['offset_ms']):
        if len(result)>=24:break
        if v['group'] not in groups or v['offset_ms']<elapsed_ms:continue
        if any(p['asset_id']==v['asset_id'] for p in patch):continue
        offset=max(v['offset_ms'],last[v['group']]+1200)
        if offset>12000:continue
        result.append({**v,'offset_ms':offset});last[v['group']]=offset
    return sorted(result,key=lambda v:v['offset_ms'])

def late_patch(engine,owner,request,context,plan,extra,script,elapsed_ms,draft=False):
    if not extra or not extra.cues or not plan.beats:return None
    if draft:elapsed_ms=0  # Preparation time is not elapsed performance time.
    beat=plan.beats[0].model_copy(deep=True)
    beat.performance=Performance(intensity=beat.performance.intensity,cues=extra.cues)
    resolved=engine.director.beat(owner,request.character_id,beat,context['relationship'],context['state'],
        request.available_assets,plan.state_interpretation.dominant_emotion,request.trigger,automatic_fill=False,record_usage=not draft)
    base=script['beats'][0]['visuals']
    # Preserve the spoken mood and reject conflicts with still-running groups.
    mood=beat.dialogue.speech.emotion if beat.dialogue else 'neutral'
    catalogue={a['asset_id']:a for a in assets(request.character_id)}
    retained=[catalogue[v['asset_id']] for v in base if v['asset_id'] in catalogue]
    resolved['performances']=[c for c in resolved['performances']
        if not (c['asset']['kind']=='expression' and c['asset'].get('moods') and mood not in c['asset']['moods'])
        and not any(a['group'] in c['asset'].get('conflicts',[]) or c['asset']['group'] in a.get('conflicts',[]) for a in retained)]
    visuals=resolved_visuals(resolved)
    if not visuals:return None
    groups={v['group'] for v in visuals}
    merged=merge_visuals(base,visuals,elapsed_ms)
    enriched={**script,'beats':[{**b,'visuals':merged} if i==0 else b for i,b in enumerate(script['beats'])]}
    if not draft:engine.store.enrich_reply(owner,request.character_id,str(request.request_id),enriched)
    return dict(type='reply.visuals.updated',message_id=script['message_id'],beat_id=beat.beat_id,script=enriched,
                visuals=current_visuals([v for v in merged if v['group'] in groups],elapsed_ms))

async def deliver(engine,owner,request,context,plan,script,visual_task,draft=False):
    """Merge completed tasks, always yielding ready audio before decoration."""
    audio=engine.audio(owner,request.character_id,script,True) if request.wants_audio else None
    next_audio=asyncio.create_task(anext(audio)) if audio else None
    start=time.monotonic()
    try:
        while next_audio is not None or visual_task is not None:
            done,_=await asyncio.wait([t for t in (next_audio,visual_task) if t is not None],return_when=asyncio.FIRST_COMPLETED)
            if next_audio is not None and next_audio in done:
                try:item=next_audio.result()
                except StopAsyncIteration:
                    next_audio=None
                    yield dict(type='audio.completed',message_id=script['message_id'])
                else:
                    next_audio=None
                    yield item
                    next_audio=asyncio.create_task(anext(audio))
            if visual_task is not None and visual_task in done:
                extra=visual_task.result();visual_task=None
                try:
                    patch=late_patch(engine,owner,request,context,plan,extra,script,round((time.monotonic()-start)*1000),draft=draft)
                except Exception as error:
                    # Optional resolution/storage must not tear down an already
                    # valid, actively streaming voice response either.
                    patch=None
                    try:engine.store.put('performance_review',owner,request.character_id,dict(status='patch_skipped',reason=type(error).__name__))
                    except Exception:pass
                if patch:yield patch
    finally:
        pending=[t for t in (next_audio,visual_task) if t is not None]
        for task in pending:task.cancel()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        if audio is not None:await audio.aclose()
