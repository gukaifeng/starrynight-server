"""AI-ranked user choices with sequential, private speculative answer branches."""
import asyncio,json,re,time,uuid
from .schemas import QuickReplyPlan
from .storage import dump
from .roleplay import language

SUGGESTIONS='''根据真实聊天，为用户提供恰好三条可以直接发送给角色的自然接话。只输出JSON，不替角色说话，不输出括号动作或心理描写。每条优先6至18字，最多45字，具体接住最新AI发言，三条在意思与走向上不同，不机械重复“继续说”。不要编造用户经历、感受或隐私事实，不引导承诺、花钱或危险行为。可以表达好奇、接话、邀请展开或温和转向。likelihood是你根据上下文估计用户会选择的相对倾向，0至1，按高到低排序；这是启发式排序，不是校准概率。参考用户过往说话习惯，但不要照抄历史发言。未被选择前，这三条都不是用户已说的话。'''

SUGGESTIONS+='''\n用户没有明确说过的职业、住处、经历和身份不能由建议凭空补全。无这些依据时用询问、兴趣选择、邀请展开或中性的礼貌接话。English suggestions must not invent a job, home, biography or relationship: do not offer "I am a [job]" or "I work nearby" without supporting user history. Ground all three options in the actual last reply, not invented user facts.'''

class QuickReplies:
    def __init__(self,pool):self.pool=pool;self.tasks={};self.targets={}
    @property
    def store(self):return self.pool.store

    def latest(self,owner,char):
        row=self.store.db.execute('SELECT id,role FROM messages WHERE owner=? AND character=? ORDER BY created DESC LIMIT 1',(owner,char)).fetchone()
        return row['id'] if row and row['role']=='assistant' else None

    def saved(self,owner,request):
        row=self.store.db.execute('SELECT * FROM quick_reply_sets WHERE owner=? AND character=?',(owner,request.character_id)).fetchone()
        if row and row['expires']>time.time() and row['context_key']==self.pool.context_key(owner,request) and row['source']==self.latest(owner,request.character_id):
            return dict(source_message_id=row['source'],options=json.loads(row['data']))
        return None

    def valid_choice(self,owner,request):
        saved=self.saved(owner,request)
        return bool(request.trigger in ('user_message','story') and saved and any(o['id']==str(request.quick_reply_id) and o['text']==request.text for o in saved['options']))

    def status(self,owner,request):
        saved=self.saved(owner,request)
        task=self.tasks.get((owner,request.character_id))
        result=saved or dict(source_message_id=str(request.source_message_id),options=[])
        return {**result,'preparing':bool(task and not task.done())}

    def prepare(self,owner,request):
        char=request.character_id;scope=(owner,char);source=str(request.source_message_id)
        if source!=self.latest(owner,char):return dict(source_message_id=source,options=[],preparing=False)
        key=self.pool.context_key(owner,request);target=(source,key)
        previous=self.tasks.get(scope)
        if previous and not previous.done() and self.targets.get(scope)==target:return self.status(owner,request)
        if previous:previous.cancel()
        if not self.saved(owner,request):self.discard(owner,char)
        self.targets[scope]=target
        self.tasks[scope]=asyncio.create_task(self.build(owner,request.model_copy(deep=True),key,source))
        return self.status(owner,request)

    async def build(self,owner,request,key,source):
        char=request.character_id
        try:
            saved=self.saved(owner,request)
            if not saved:
                context=self.pool.engine.context(owner,request,persist=False)
                # Bounded recent conversational text, not the full performance/persona
                # catalogue. The selected answer still uses the complete role context.
                recent=[dict(role=m['role'],text=m['text'][-600:]) for m in context['recent_messages'][-8:] if m.get('text')]
                data=dict(recent_messages=recent,preferences=context['preferences'],character_name=context['character_profile'].get('english_name',context['character_profile'].get('name','')),
                    language_contract=context['language_contract'],roleplay_context=context['roleplay_context'])
                if language(char)=='en':data['suggestion_length']='Exactly three distinct English replies, normally 3–8 words each and at most 45 characters. Preserve natural English; do not translate Chinese examples.'
                async with asyncio.timeout(12):
                    plan=await self.pool.engine.provider.structured(owner,char,'suggestions',SUGGESTIONS,data,QuickReplyPlan)
                choices=sorted(plan.options,key=lambda o:o.likelihood,reverse=True)
                if language(char)=='en' and any(re.search(r'[\u3400-\u9fff\u3040-\u30ff]',o.text) for o in choices):raise ValueError('SUGGESTION_LANGUAGE_INVALID')
                if len({o.text.strip() for o in choices})!=3:raise ValueError('DUPLICATE_SUGGESTIONS')
                options=[dict(id=str(uuid.uuid4()),text=o.text.strip(),likelihood=o.likelihood) for o in choices]
                if self.latest(owner,char)!=source or self.pool.context_key(owner,request)!=key:return
                with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO quick_reply_sets VALUES(?,?,?,?,?,?)',
                    (owner,char,source,key,dump(options),time.time()+900))
                saved=dict(source_message_id=source,options=options)
            # One answer per choice, highest-likelihood branch first. Queued
            # lower choices can be promoted by a real selection immediately.
            for option in saved['options']:
                if self.latest(owner,char)!=source or self.pool.context_key(owner,request)!=key:return
                kind='quick:'+option['id']
                if self.pool.rows(owner,char,key,kind):continue
                branch=request.model_copy(update=dict(text=option['text'],trigger='story' if request.scene.get('story_id') else 'user_message',quick_reply_id=None))
                job=self.pool.ensure_job(owner,branch,key,kind,source=source)
                await asyncio.shield(job.task)
        except asyncio.CancelledError:raise
        except Exception as error:self.store.put('quick_reply_review',owner,char,dict(status='unavailable',reason=type(error).__name__))

    def discard(self,owner,char,keep=None):
        for job in list(self.pool.jobs.values()):
            if job.owner==owner and job.request.character_id==char and job.kind.startswith('quick:') and job.id!=keep and not job.claimed:job.task.cancel()
        with self.store.db:
            self.store.db.execute('DELETE FROM quick_reply_sets WHERE owner=? AND character=?',(owner,char))
            self.store.db.execute("UPDATE reaction_drafts SET status='expired' WHERE owner=? AND character=? AND kind LIKE 'quick:%' AND status!='used' AND id!=?",(owner,char,keep or ''))
        self.pool.prune(owner,char)

    async def pause(self,owner,char=None):
        tasks=[]
        for scope,task in list(self.tasks.items()):
            if scope[0]==owner and (char is None or scope[1]==char):task.cancel();tasks.append(task);self.tasks.pop(scope,None)
        await asyncio.gather(*tasks,return_exceptions=True)

    async def close(self):
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);self.tasks.clear()
