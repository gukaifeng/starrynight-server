"""Single-use real AI event drafts, including handoff of an in-flight stream."""
import asyncio,hashlib,json,random,time,uuid
from contextlib import aclosing
from . import novelty
from .schemas import ModelInteraction,Plan
from .speech_text import audio_key
from .storage import dump
from .greetings import ENTRY_TRIGGERS
from .prepared_draft import PreparedDraft
from . import idle_presence,reply_flow

REACTIONS={'shake':'model_shaken','pinch_in':'model_pinched','pinch_out':'model_pinched'}
SCENARIOS={**REACTIONS,'idle':'idle','first_meeting':'firstMeeting','app_launch':'appLaunch','return':'characterSwitch'}
AUTOMATIC_TRIGGERS=set(SCENARIOS.values())|ENTRY_TRIGGERS

def event_task(kind):
    return {
        'first_meeting':'这是你与这个用户第一次见面。简短主动打招呼，不认识对方、不曾共同经历，不说欢迎回来。',
        'app_launch':'用户重新打开应用来看你，你们以前见过。这是一次新的开场，轻轻接续此前的相处，不能重新作答历史问题或重复问候。',
        'return':'用户从别的角色或页面切回与你的会话，你们已经见过。像熟悉的伙伴重新接上话，短暂离开也适用，不说好久不见。',
        'idle':idle_presence.TASK+'按idle_context丰富表达；idle_decision选择proactive_speech，实际是否打破安静由触发时判断。',
    }.get(kind,'依照interaction_context回应这个真实触发的手势。')

class ReactionPool:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store;self.settings=engine.settings
        self.tasks={};self.jobs={};self.active={};self.leases={};self.backoff={}
        self.slots=asyncio.Semaphore(4)
        from .quick_replies import QuickReplies
        self.quick=QuickReplies(self)
        with self.store.db:self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE status='preparing'")

    @property
    def capacity(self):return max(0,min(1,self.settings.reaction_pool_size))

    def has_met(self,owner,request):
        return bool(self.store.history(owner,request.character_id,1) or request.recent_messages or self.store.get('greetings',owner,request.character_id,[]))

    def kind(self,owner,request):
        if request.quick_reply_id:return 'quick:'+str(request.quick_reply_id) if self.quick.valid_choice(owner,request) else None
        if request.trigger in REACTIONS.values():return request.interaction.kind if request.interaction else None
        if request.trigger=='idle':return 'idle'
        if request.trigger in ENTRY_TRIGGERS:
            if not self.has_met(owner,request):return 'first_meeting'
            return 'app_launch' if request.trigger in ('appLaunch','firstLaunch') else 'return'
        return None

    def eligible(self,owner,request):
        if getattr(request,'preparation_scope','active')=='entry':
            kind=self.kind(owner,request)
            return [kind] if kind in ('first_meeting','app_launch','return') else []
        if not self.has_met(owner,request):return ['first_meeting']
        history=self.store.history(owner,request.character_id) or [m.model_dump() for m in request.recent_messages]
        return [*REACTIONS,*(['idle'] if idle_presence.availability(history)!='quiet_requested' else []),'app_launch','return']

    def context_key(self,owner,request):
        rows=self.store.db.execute('SELECT id,role,data FROM messages WHERE owner=? AND character=? ORDER BY created DESC LIMIT 80',(owner,request.character_id)).fetchall()
        history=[]
        for row in rows:
            data=json.loads(row['data'])
            if row['role']=='assistant' and data.get('trigger') in AUTOMATIC_TRIGGERS:continue
            history.append([row['id'],row['role'],data.get('text','')])
            if len(history)>=12:break
        if not rows:history=[m.model_dump() for m in request.recent_messages]
        voice=self.store.get('voice','system',request.character_id,{})
        from .profiles import PROFILES
        # v4 adds conversational pauses/delivery and corresponding expression
        # selection. Retire only unspoken drafts; archive/audio remain intact.
        value=[4,reply_flow.REVISION,idle_presence.REVISION,request.character_id,self.has_met(owner,request),PROFILES[request.character_id],voice.get('voice_id'),request.preferences,
               [m.model_dump() for m in request.memories],sorted(request.available_assets),{k:v for k,v in request.scene.items() if k!='time'},history]
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

    def rows(self,owner,char,key,kind=None):
        query="SELECT * FROM reaction_drafts WHERE owner=? AND character=? AND context_key=? AND status='ready' AND expires>?"
        args=[owner,char,key,time.time()]
        if kind:query+=' AND kind=?';args.append(kind)
        return self.store.db.execute(query+' ORDER BY created',args).fetchall()

    def has_audio(self,owner,char,script):
        voice=self.store.get('voice','system',char,{})
        if not voice.get('approved'):return False
        for beat in script['beats']:
            if not beat.get('dialogue') and not beat.get('vocal_events'):continue
            path=self.settings.data_dir/'audio'/(audio_key(owner,char,voice['voice_id'],script['message_id'],beat['beat_id'])+'.pcm')
            try:
                if not path.is_file() or path.stat().st_size==0:return False
            except OSError:return False
        return True

    def find_job(self,owner,char,key,kind):
        return next((j for j in self.jobs.values() if j.owner==owner and j.request.character_id==char and j.key==key and j.kind==kind and not j.claimed and not j.done and not j.task.done() and not j.task.cancelling()),None)

    def status(self,owner,request):
        key=self.context_key(owner,request);char=request.character_id
        counts={k:sum(self.has_audio(owner,char,json.loads(r['data'])['script']) for r in self.rows(owner,char,key,k)) for k in SCENARIOS}
        pending={k:self.find_job(owner,char,key,k) is not None for k in SCENARIOS}
        return dict(capacity=self.capacity,ready=counts,pending=pending,preparing=any(pending.values()),kinds=SCENARIOS)

    def prepare(self,owner,request,*,renew_lease=True):
        char=request.character_id;scope=(owner,char);key=self.context_key(owner,request)
        if renew_lease:self.leases[scope]=str(request.request_id)
        self.active[owner]=char
        for j in list(self.jobs.values()):
            if j.owner==owner and not j.claimed and (j.request.character_id!=char or j.key!=key):j.task.cancel()
        with self.store.db:
            self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE owner=? AND character=? AND status='ready' AND (context_key!=? OR expires<=?)",(owner,char,key,time.time()))
            for kind in SCENARIOS:
                valid=0
                for row in self.rows(owner,char,key,kind):
                    if valid>=self.capacity or not self.has_audio(owner,char,json.loads(row['data'])['script']):self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE id=?",(row['id'],))
                    else:valid+=1
        self.prune(owner,char)
        jobs=[]
        if self.capacity:
            for kind in self.eligible(owner,request):
                if time.monotonic()>=self.backoff.get((owner,char,key,kind),0) and not self.rows(owner,char,key,kind):
                    jobs.append(self.ensure_job(owner,request,key,kind))
        old=self.tasks.get(scope)
        if old:old.cancel() # Only the joiner; generation is independently owned.
        self.tasks[scope]=asyncio.create_task(self.wait_jobs(jobs))
        return self.status(owner,request)

    async def wait_jobs(self,jobs):
        await asyncio.gather(*(asyncio.shield(j.task) for j in jobs),return_exceptions=True)

    def ensure_job(self,owner,request,key,kind,source=None):
        existing=self.find_job(owner,request.character_id,key,kind)
        if existing:return existing
        self.jobs={id:j for id,j in self.jobs.items() if not j.done}
        changes=dict(request_id=uuid.uuid4(),entry_id=None,quick_reply_id=None,wants_audio=True,timeline_reply=True,parallel_performance=True)
        if kind in SCENARIOS:changes.update(text='',trigger=SCENARIOS[kind],interaction=ModelInteraction(kind=kind,intensity=.75) if kind in REACTIONS else None)
        else:changes.update(trigger='user_message',interaction=None)
        job=PreparedDraft(str(uuid.uuid4()),owner,request.model_copy(update=changes,deep=True),key,kind,source)
        self.jobs[job.id]=job;job.task=asyncio.create_task(self.run(job))
        def settled(task):
            if not job.done:
                job.error=asyncio.CancelledError() if task.cancelled() else task.exception()
                job.done=True;job.changed.set()
        job.task.add_done_callback(settled)
        return job

    def current(self,job):
        return job.claimed or (self.context_key(job.owner,job.request)==job.key and (not job.source or self.quick.latest(job.owner,job.request.character_id)==job.source))

    async def run(self,job):
        owner=job.owner;request=job.request;char=request.character_id;voice=self.store.get('voice','system',char,{})
        try:
            async with self.slots:
                if not voice.get('approved') or not self.current(job):raise ValueError('DRAFT_NOT_APPLICABLE')
                context=self.engine.context(owner,request,persist=False)
                if job.kind in SCENARIOS:
                    context['scene']={k:v for k,v in context['scene'].items() if k!='time'}
                    if 'interaction_context' in context:context['interaction_context']['mood']=random.choice(['playful','serious'])
                    context['prepared_event_context']=dict(kind=job.kind,task=event_task(job.kind),rule='这是一条未来事件的候选，还没有说出。只参考真实历史，不编造共同经历，不提具体日期、时刻、离开多久或刚刚说过什么，不把准备过程说出来。')
                    if 'greeting_context' in context:
                        context['greeting_context']['elapsed_seconds']=None;context['greeting_context']['task']=event_task(job.kind)
                siblings=[json.loads(r['data']) for r in self.rows(owner,char,job.key)]
                context['reserved_reactions']=[s['script']['text'] for s in siblings]
                context['recent_response_focus']=(context['recent_response_focus']+[s['plan']['response_focus'] for s in siblings])[-12:]
                async with aclosing(self.engine.compose_reply(owner,request,context,draft=True)) as output:
                    async for item in output:
                        if not self.current(job):raise ValueError('DRAFT_CONTEXT_CHANGED')
                        if item['type']=='reaction.draft':job.plan=item['plan'];continue
                        if item['type'] in ('reply.narration.ready','reply.visuals.updated'):
                            job.script=item['script']
                            if item['type']=='reply.narration.ready':
                                if not job.script['text']:raise ValueError('EMPTY_DRAFT')
                                other=[dict(role='assistant',text=json.loads(r['data'])['script']['text']) for r in self.rows(owner,char,job.key)]
                                if novelty.match(self.store,owner,job.script['text'],extra=other):raise ValueError('REPLY_REPEATED')
                                ttl=self.settings.entry_pool_ttl_seconds if job.kind in ('first_meeting','app_launch','return') else self.settings.reaction_pool_ttl_seconds
                                with self.store.db:self.store.db.execute('INSERT INTO reaction_drafts VALUES(?,?,?,?,?,?,?,?,?)',(job.id,owner,char,job.kind,job.key,'preparing',dump(dict(script=job.script,plan=job.plan,voice_id=voice['voice_id'])),time.time(),time.time()+ttl))
                        job.append(item)
                        await asyncio.sleep(0) # Attached foreground consumers get the first PCM promptly.
                if not job.script or not self.has_audio(owner,char,job.script):raise ValueError('DRAFT_AUDIO_FAILED')
                with self.store.db:self.store.db.execute("UPDATE reaction_drafts SET data=?,status=CASE WHEN status='preparing' THEN 'ready' ELSE status END WHERE id=?",(dump(dict(script=job.script,plan=job.plan,voice_id=voice['voice_id'])),job.id))
        except BaseException as error:
            job.error=error
            with self.store.db:self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE id=? AND status!='used'",(job.id,))
            if not isinstance(error,asyncio.CancelledError):
                self.backoff[(owner,char,job.key,job.kind)]=time.monotonic()+30
                self.store.put('reaction_pool_review',owner,char,dict(status='preparation_failed',kind=job.kind,reason=type(error).__name__))
        finally:job.done=True;job.changed.set()

    def claim(self,owner,request):
        kind=self.kind(owner,request);char=request.character_id;key=self.context_key(owner,request)
        if kind is None:return None
        for row in self.rows(owner,char,key,kind):
            candidate=json.loads(row['data'])
            if not self.has_audio(owner,char,candidate['script']) or novelty.match(self.store,owner,candidate['script']['text']):
                with self.store.db:self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE id=?",(row['id'],))
                continue
            return dict(id=row['id'],kind=kind,candidate=candidate)
        job=self.find_job(owner,char,key,kind)
        if job is None and kind.startswith('quick:'):job=self.ensure_job(owner,request,key,kind,source=self.quick.latest(owner,char))
        if job:
            job.claimed=True;return dict(id=job.id,kind=kind,job=job)
        self.store.put('reaction_pool_review',owner,char,dict(status='miss',kind=kind));return None

    def publish(self,owner,request,context,claim,script,plan):
        char=request.character_id;script={**script,'trigger':request.trigger}
        self.store.publish_reply(owner,char,str(request.request_id),request.text,script,prepared_id=claim['id'],allow_preparing='job' in claim)
        self.engine.commit_context(owner,request,context,script,Plan.model_validate(plan))
        self.store.put('vocals',owner,char,[v['event'] for b in script['beats'] for v in b['vocal_events']])
        from .profiles import assets
        catalogue={a['asset_id']:a for a in assets(char)};selected={v['asset_id'] for b in script['beats'] for v in b['visuals']}
        with self.store.db:
            for asset in selected & catalogue.keys():self.store.db.execute('INSERT INTO asset_usage(owner,character,asset,kind,created) VALUES(?,?,?,?,?)',(owner,char,asset,catalogue[asset]['kind'],time.time()))
        self.store.put('reaction_pool_review',owner,char,dict(status='inflight' if 'job' in claim else 'hit',kind=claim['kind'],message_id=script['message_id']))
        if claim['kind'].startswith('quick:'):self.quick.discard(owner,char,keep=claim['id'])
        elif self.active.get(owner)==char:self.prepare(owner,request,renew_lease=False)
        return script

    async def deliver(self,owner,request,context,claim):
        if 'candidate' in claim:
            candidate=claim['candidate'];script=self.publish(owner,request,context,claim,candidate['script'],candidate['plan'])
            yield dict(type='reply.narration.ready',script=script,cached=False,prepared=True)
            if request.wants_audio:
                async with aclosing(self.engine.audio(owner,request.character_id,script,create=False)) as audio:
                    async for item in audio:yield item
                yield dict(type='audio.completed',message_id=script['message_id'])
            yield dict(type='reply.completed',message_id=script['message_id']);return
        job=claim['job'];completed=False
        try:
            async with aclosing(job.stream()) as stream:
                async for item in stream:
                    if item['type']=='reply.narration.ready':
                        script=self.publish(owner,request,context,claim,item['script'],job.plan)
                        item={**item,'script':script,'prepared':True,'preparation_inflight':True}
                    elif item['type']=='reply.visuals.updated':
                        script={**item['script'],'trigger':request.trigger};self.store.enrich_reply(owner,request.character_id,str(request.request_id),script);item={**item,'script':script}
                    if not request.wants_audio and (item['type'].startswith('segment.audio.') or item['type'].startswith('audio.')):continue
                    yield item
            completed=True
        finally:
            if not completed and not job.done:
                job.task.cancel();await asyncio.gather(job.task,return_exceptions=True)

    def prune(self,owner,char):
        rows=self.store.db.execute("SELECT * FROM reaction_drafts WHERE owner=? AND character=? AND status='expired'",(owner,char)).fetchall()
        for row in rows:
            candidate=json.loads(row['data']);script=candidate['script']
            if not self.store.db.execute('SELECT 1 FROM messages WHERE id=?',(script['message_id'],)).fetchone():
                voice=candidate.get('voice_id',self.store.get('voice','system',char,{}).get('voice_id',''))
                for beat in script['beats']:(self.settings.data_dir/'audio'/(audio_key(owner,char,voice,script['message_id'],beat['beat_id'])+'.pcm')).unlink(missing_ok=True)
        with self.store.db:
            self.store.db.execute("DELETE FROM reaction_drafts WHERE owner=? AND character=? AND status='expired'",(owner,char))
            self.store.db.execute("DELETE FROM reaction_drafts WHERE owner=? AND character=? AND status='used' AND created<?",(owner,char,time.time()-86400))

    async def yield_to_reply(self,owner,keep=None):
        await self.quick.pause(owner)
        tasks=[]
        for scope,task in list(self.tasks.items()):
            if scope[0]==owner:task.cancel();tasks.append(task);self.tasks.pop(scope,None)
        for job in list(self.jobs.values()):
            if job.owner==owner and job is not keep and not job.claimed and not job.done:job.task.cancel();tasks.append(job.task)
        await asyncio.gather(*tasks,return_exceptions=True)

    async def pause(self,owner,char,lease=None):
        if lease is not None and self.leases.get((owner,char))!=lease:return
        if self.active.get(owner)==char:self.active.pop(owner,None)
        task=self.tasks.pop((owner,char),None);tasks=[task] if task else []
        tasks.extend(j.task for j in list(self.jobs.values()) if j.owner==owner and j.request.character_id==char and not j.claimed and not j.done)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);await self.quick.pause(owner,char)

    async def close(self):
        await self.quick.close()
        tasks=[*self.tasks.values(),*(j.task for j in self.jobs.values() if not j.done)]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.tasks.clear();self.jobs.clear();self.active.clear()
