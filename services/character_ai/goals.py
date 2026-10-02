"""Goal policy is shared by live replies and speculative drafts; PG owns progress."""
import base64,json
import httpx
from .roleplay import language_instruction
from .roleplay import language as authored_language

REVISION=1
RELATIONS={'strangers':'初识','pursuit':'追求','flirting':'暧昧','lovers':'恋人','friends':'朋友','mentor':'师徒','rivals':'宿敌','childhood':'青梅竹马'}
INSTRUCTION='''相处目标：goal_context 是服务端验证的当前方向，优先于旧聊天中的关系或任务，保留角色本来的性格、边界与语言要求。不要向用户报分、念出目标字段或声称系统升级关系。
关系模式：成年且允许恋爱的人设，以互相吸引、追求、约会到情侣日常为高权重主线；一轮只推进一个可信的小变化。初始关系不是所有分支的结局，用户可以只做朋友、改变方向、暂停或拒绝。好感分数不能替代双方明确表达，不因聊天次数自动成为情侣。宿敌是虚构分歧，师徒不滥用权力；青梅竹马背景只在用户选择该设定后成立，不编造用户现实童年。关系进展用具体交流、共同选择与体贴体现，不反复试探表白。
任务模式：实际帮助用户优先，关系温度次要；先回应内容，再用符合性格的自然短句纠正一个最值得纠正的地方，邀请尝试即可，不变成老师训话。英语练习保持全英文，难度随用户表达调整，用户要求才展开语法。学习、计划必须产生可操作价值，不能用撒娇替代解答。
沙盒模式：没有强制任务或结局，隐性方向是有趣、理解用户和人设一致，每轮接住用户的具体新内容；不强迫进入恋爱。
短期目标是这次相处的方向，不是强迫完成的任务。优先照顾用户当前输入；用户说停止、只做朋友、不聊某事时立即尊重，不靠 guilt、占有、嫉妒或孤立用户维系关系。paused=true时不推进长期目标，仍自然回应。故事是方向下的虚构情境，不替代真实关系记忆。
goal_feedback只能描述本轮用户真实选择引发的微小变化，各delta在-0.04至0.04。evidence必须逐字引用user_message的一小段，不能用自己的台词作为证据。milestone只选shared_interest/trust_opened/date_agreed/repair/learning_step/preference_understood之一，没有证据用空字符串。不能用idle、问候、手势、预生成未交付的回答刷进度，不能确认情侣或改用户目标。语音语气与已确认关系、当前目标一致；动作表情使用实际支持的能力，亲密程度不能突破关系边界。'''

def attach(body,headers,store,owner):
    raw=headers.get('x-starry-goal-snapshot','')
    if not raw:return
    if len(raw)>24000:raise ValueError('INVALID_GOAL_SNAPSHOT')
    value=json.loads(base64.urlsafe_b64decode(raw+'='*((-len(raw))%4)))
    if value.get('schema_version')!=1:raise ValueError('UNSUPPORTED_GOAL_SCHEMA')
    body._goal_snapshot=value;body._goal_account=headers.get('x-starry-account','')
    remember(store,owner,body,value)
    body._goal_snapshot=effective(store,owner,body)

def stamp(value):
    return (value.get('version',0),value.get('progress_version',0))

def remember(store,owner,request,value):
    previous=store.get('goal_snapshot',owner,request.character_id,{})
    if stamp(value)>=stamp(previous):store.put('goal_snapshot',owner,request.character_id,value)

def effective(store,owner,request):
    latest=store.get('goal_snapshot',owner,request.character_id,{})
    return latest if stamp(latest)>stamp(request._goal_snapshot) else request._goal_snapshot

def committed(store,owner,request,value):
    if value:
        request._goal_snapshot=value
        remember(store,owner,request,value)

def branch(config):
    mode=config.get('mode','sandbox')
    if mode=='task':return 'task:'+config.get('task','study')
    if mode=='sandbox':return 'sandbox'
    return 'relationship:'+config.get('initial_relation','friends')+':'+config.get('long_term','friendship')

def context(request):
    s=request._goal_snapshot
    c=s.get('config',{'mode':'sandbox','long_term':'understanding','initial_relation':'friends','task':'study','short_term':'','paused':False})
    p=s.get('branches',{}).get(branch(c),{})
    bond=s.get('bond',p)
    romance=bool(s.get('romance_allowed')) and c.get('long_term')=='romance'
    return dict(schema_version=1,config=c,config_version=s.get('version',0),progress=p,bond=bond,
        romance_allowed=romance,initial_relation=RELATIONS.get(c.get('initial_relation'),'朋友'),
        weights={'relationship':.85,'task':.15} if c.get('mode')=='relationship' and romance else
                {'task':.8,'relationship':.2} if c.get('mode')=='task' else {'understanding':.5,'interest':.3,'persona':.2},
        relationship_status='confirmed_couple' if c.get('confirmed_couple') or c.get('initial_relation')=='lovers' else
            'mutual_interest' if romance and bond.get('affection',0)>=.45 else 'getting_to_know',
        paused=bool(c.get('paused')))

def language_contract(character,goal):
    if goal['config'].get('mode')=='task' and goal['config'].get('task')=='english':
        return language_instruction('anime-lime')
    return language_instruction(character)

def spoken_language(character,goal):
    c=goal.get('config',{})
    return 'en' if c.get('mode')=='task' and c.get('task')=='english' else authored_language(character)

async def commit(settings,request,plan):
    snapshot=request._goal_snapshot
    if not settings.platform_internal_url or not request._goal_account or not snapshot:return snapshot
    payload=dict(request_id=str(request.request_id),version=snapshot.get('version',0),conversation_reset=request.conversation_reset,
        trigger=request.trigger,user_text=request.text,**plan.goal_feedback.model_dump())
    # Same-host authenticated PG commit; no paid call or additional planning pass.
    url=settings.platform_internal_url.rstrip('/')+'/internal/goals/'+request._goal_account+'/'+request.character_id+'/feedback'
    async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
        response=await client.post(url,json=payload,headers={'Authorization':'Bearer '+settings.client_token})
    if response.status_code==409:raise ValueError('GOAL_CONTEXT_CHANGED')
    response.raise_for_status()
    return response.json()
