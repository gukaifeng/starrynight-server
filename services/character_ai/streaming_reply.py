"""Sentence-first role stream, ordered PCM, independent optional performance.

Only complete, validated AI-authored beats are published. A later optional
field cannot invalidate already accepted speech or start a second paid call.
"""
import asyncio,copy,uuid
from contextlib import aclosing
from . import voice_trace as vt,novelty,goals,parallel_performance,aside_quality
from .schemas import Plan,MemoryProposal,visible_text
from .stream_wire import beat,feedback
from .reply_flow import compile_parts,duration_hint
from .roleplay import wrong_language

async def reply(engine,owner,request,context,visuals,*,draft=False):
    char=request.character_id;rid=str(request.request_id);plan=Plan()
    script=dict(message_id=str(uuid.uuid4()),character_id=char,beats=[],text='',trigger=request.trigger,
        idle_decision='proactive_speech' if request.trigger=='idle' else None,memory_suggestions=[])
    controls=asyncio.Queue(maxsize=16);segments=asyncio.Queue(maxsize=4);end=object()
    published=False;announced=asyncio.Event()
    pending_visuals=None
    async def produce():
        nonlocal published
        try:
            async with aclosing(engine.provider.stream_beats(owner,char,context)) as source:
                async for raw in source:
                    if 'say' not in raw:
                        if 'goal_feedback' in raw:plan.goal_feedback=feedback(raw['goal_feedback'],request.text)
                        if isinstance(raw.get('focus'),str):plan.response_focus=raw['focus'][:100]
                        if isinstance(raw.get('state'),dict):
                            plan.suggested_state_delta={k:v for k,v in raw['state'].items() if k in ('happiness','sadness','anger','anxiety','energy','closeness','trust','conflict') and isinstance(v,(int,float)) and not isinstance(v,bool) and -.08<=v<=.08}
                        if request.trigger=='user_message' and isinstance(raw.get('memories'),list):
                            for value in raw['memories'][:2]:
                                try:plan.memory_updates.append(MemoryProposal.model_validate(value))
                                except (ValueError,TypeError):pass
                        script['memory_suggestions']=[m.content for m in plan.memory_updates]
                        continue
                    if len(plan.beats)>=3:continue
                    b=beat(raw,len(plan.beats)+1)
                    vt.mark('first_sentence_validated')
                    b.asides=[a for a in b.asides if aside_quality.allowed_language(a.text,goals.spoken_language(char,context['goal_context']))]
                    proposed=Plan(beats=[b])
                    lang_char='anime-lime' if goals.spoken_language(char,context['goal_context'])=='en' else char
                    from .orchestrator import interaction_mismatch
                    if wrong_language(lang_char,proposed) or interaction_mismatch(request,b.dialogue.text):raise ValueError('STREAM_CONTENT_INVALID')
                    candidate='\n'.join([script['text'],b.dialogue.text]).strip()
                    extra=[dict(text=t) for t in context.get('reserved_reactions',[])]
                    if novelty.match(engine.store,owner,candidate,extra,exclude_message=script['message_id']):raise ValueError('REPLY_REPEATED')
                    with vt.span('plan.quality_review'):
                        related=await engine.semantic.match(owner,candidate,request.trigger,exclude_message=script['message_id'])
                        if related and related['score']>=.86:raise ValueError('REPLY_REPEATED')
                    resolved=engine.director.beat(owner,char,b,context['relationship'],context['state'],request.available_assets,
                        b.dialogue.speech.emotion,request.trigger,record_usage=not draft)
                    wire=dict(beat_id=b.beat_id,thought=None,dialogue=dict(text=visible_text(b.dialogue.text),speech=b.dialogue.speech.model_dump()),
                        narrations=[],vocal_events=[],visuals=parallel_performance.resolved_visuals(resolved),
                        parts=compile_parts(b,resolved,language=goals.spoken_language(char,context['goal_context']),recent_asides=context['recent_asides_to_avoid'],visible_details=context['visible_details']),
                        reading_duration=duration_hint(b.dialogue.text),language=goals.spoken_language(char,context['goal_context']))
                    plan.beats.append(b);script['beats'].append(wire);script['text']=candidate
                    if not draft:
                        if not published:
                            engine.store.publish_reply(owner,char,rid,request.text,script)
                            engine.store.complete(owner,char,rid,script);published=True
                        else:engine.store.enrich_reply(owner,char,rid,script)
                    if draft:await controls.put(dict(type='reaction.draft',plan=plan.model_dump()))
                    await controls.put(dict(type='reply.narration.ready' if len(plan.beats)==1 else 'reply.script.updated',script=copy.deepcopy(script),cached=False,core_streaming=True))
                    await segments.put(copy.deepcopy(wire))
            if not plan.beats:raise ValueError('EMPTY_REPLY')
            vt.mark('core_generation_completed')
            if draft:await controls.put(dict(type='reaction.draft',plan=plan.model_dump()))
            else:
                script['goal_state']=await goals.commit(engine.settings,request,plan)
                goals.committed(engine.store,owner,request,script['goal_state'])
                engine.commit_context(owner,request,context,script,plan)
                engine.store.enrich_reply(owner,char,rid,script)
            await controls.put(dict(type='reply.script.updated',script=copy.deepcopy(script),core_complete=True))
        except Exception as error:
            if not plan.beats:await controls.put(error)
            else:
                # Keep accepted, replayable speech if an optional tail/transport
                # fails. Never bill a blind second generation after publication.
                vt.flag('stream_tail_error',type(error).__name__)
                if not draft:engine.commit_context(owner,request,context,script,plan)
                await controls.put(dict(type='reply.script.updated',script=copy.deepcopy(script),core_complete=True))
        finally:
            await segments.put(end);await controls.put(end)
    async def audio():
        await announced.wait() # No PCM/start event may overtake the first public script.
        while True:
            wire=await segments.get()
            if wire is end:break
            if request.wants_audio:
                one={**script,'beats':[wire]}
                async with aclosing(engine.audio(owner,char,one,True)) as stream:
                    async for item in stream:yield item
        yield dict(type='audio.completed',message_id=script['message_id'])
    producer=asyncio.create_task(produce());audio_stream=audio();next_audio=asyncio.create_task(anext(audio_stream))
    next_control=asyncio.create_task(controls.get());control_done=False
    try:
        while next_audio is not None or not control_done:
            tasks=[t for t in (next_audio,next_control,visuals) if t is not None]
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            if next_control is not None and next_control in done:
                item=next_control.result();next_control=None
                if item is end:control_done=True
                elif isinstance(item,Exception):raise item
                else:
                    if item['type']=='reply.narration.ready':announced.set()
                    yield item
                if not control_done:next_control=asyncio.create_task(controls.get())
            if next_audio is not None and next_audio in done:
                try:item=next_audio.result()
                except StopAsyncIteration:next_audio=None
                else:
                    yield item;next_audio=asyncio.create_task(anext(audio_stream))
            if visuals is not None and visuals in done:
                pending_visuals=visuals.result();visuals=None
            if pending_visuals is not None and plan.beats:
                try:
                    patch=parallel_performance.late_patch(engine,owner,request,context,plan,pending_visuals,script,0,draft=draft)
                    if patch:script.update(patch['script']);yield patch
                except Exception as error:vt.flag('stream_visual_error',type(error).__name__)
                pending_visuals=None
        await producer
        yield dict(type='reply.completed',message_id=script['message_id'])
    finally:
        tasks=[t for t in (producer,next_audio,next_control,visuals) if t is not None]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);await audio_stream.aclose()
