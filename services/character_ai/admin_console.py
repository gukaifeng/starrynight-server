"""Private operator API. Mounted only on the worker's loopback listener.

The browser authenticates with the independent Go console; the shared worker
credential is never sent to it. No arbitrary SQL, paths or provider URLs.
"""
import copy, hashlib, importlib, json, os, re
from fastapi import APIRouter, HTTPException, Request
from .profiles import PROFILES, assets
from . import prompts

PROMPTS=('PLANNER','CORE_PLANNER','NARRATOR','PERFORMER','REPLY_LENGTH')
TABLES={
    'voice_traces':('语音耗时','逐次语音追踪，含预生成、缓存、模型调用和音频分段时间轴；只读，保留14天或最近5000次'),
    'messages':('AI 上下文','模型实际使用的对话上下文，只读'),
    'memories':('AI 记忆','推理提取的记忆，可修改或删除'),
    'records':('AI 状态','情绪、称呼、问候与检查状态，只读'),
    'requests':('推理请求','幂等状态与结果，只读，不能重复执行已计费请求'),
    'usage':('付费用量','调用与单位账本，只读'),
    'asset_usage':('动作调用','角色动作与表情选择记录，只读'),
    'voice_design_jobs':('音色任务','音色生成与审核状态'),
    'reaction_drafts':('场景预缓存','问候、晃动、捏扯等场景预生成状态'),
    'quick_reply_sets':('接话预缓存','三个候选回复与准备状态'),
    'reply_novelty':('回复去重','已发布回复的去重索引，只读'),
    'reply_embeddings':('语义去重','仅显示索引信息，不返回模型向量'),
    'conversation_resets':('AI 重置记录','跨服务幂等重置收据，只读'),
}
CONFIG_FIELDS={
    'streaming_core':bool,
    'character_model':str,'preparation_model':str,'suggestions_model':str,'performance_model':str,'translation_model':str,
    'tts_model':str,'asr_model':str,'paid_enabled':bool,
    'enforce_conversation_limits':bool,'enable_test_inspector':bool,
    'max_daily_calls':int,'max_daily_tts_characters':int,'max_daily_asr_seconds':int,
    'max_voice_designs':int,'narration_timeout_seconds':float,
    'performance_timeout_seconds':float,'reaction_pool_size':int,
    'reaction_pool_ttl_seconds':float,'entry_pool_ttl_seconds':float,
}
ORIGINAL_PROFILES=copy.deepcopy(PROFILES)
ORIGINAL_PROMPTS={k:getattr(prompts,k) for k in PROMPTS}

def safe(value):
    if isinstance(value,dict):
        return {k:('[已隐藏]' if re.search(r'(?i)(api_key|client_token|admin_token|voice_id|password|authorization)',k) else safe(v)) for k,v in value.items()}
    if isinstance(value,list):return [safe(v) for v in value]
    return value

def apply_prompts(values):
    # Existing modules import constants for hot paths. Keep those aliases in
    # sync, rather than presenting a saved value that inference does not use.
    for key,value in values.items():
        setattr(prompts,key,value)
        for name in ('orchestrator','provider','parallel_performance'):
            module=importlib.import_module('.'+name,__package__)
            if hasattr(module,key):setattr(module,key,value)

def load_overrides(store):
    for char in ORIGINAL_PROFILES:
        row=store.get('admin_profile','system',char)
        PROFILES[char]=copy.deepcopy(row['data'] if row else ORIGINAL_PROFILES[char])
    row=store.get('admin_prompts','system','global')
    apply_prompts(row['data'] if row else ORIGINAL_PROMPTS)

def mount(app,settings,store,engine,admin):
    load_overrides(store)
    router=APIRouter(prefix='/v1/admin/console')
    async def auth(request:Request):admin(request.headers)
    # Router-level dependency also covers newly added endpoints.
    from fastapi import Depends
    router.dependencies.append(Depends(auth))

    def revision(kind,char):return (store.get(kind,'system',char) or {}).get('version',1)
    def config_data():return dict(id='runtime',version=revision('admin_config','global'),data={k:getattr(settings,k) for k in CONFIG_FIELDS},credentials=dict(api_key_configured=bool(settings.api_key)))
    @router.get('/resources')
    async def resources():
        result=[dict(id='profiles',name='AI 角色设定',group='AI',description='完整人格、背景、语气与场景；保存后新调用生效',keys=['id'],fields=['id','name','data','version','capabilities'],edit=['data'],actions=['restore']),
                dict(id='prompts',name='全局调教',group='AI',description='完整规划、旁白与动作提示词；协议结构不开放修改',keys=['id'],fields=['id','data','version'],edit=['data'],actions=['restore']),
                dict(id='config',name='模型与预算',group='AI',description='模型选择、预缓存、用量开关；密钥只显示配置状态',keys=['id'],fields=['id','data','version','credentials'],edit=['data'],actions=[])]
        for table,(name,description) in TABLES.items():
            fields=[r['name'] for r in store.db.execute(f'PRAGMA table_info({table})') if r['name']!='vector']
            result.append(dict(id=table,name=name,group='AI',description=description,keys=['_rowid'],fields=['_rowid']+fields+(['version'] if table=='memories' else []),edit=['content','importance'] if table=='memories' else [],actions=['remove'] if table=='memories' else ['clear_unused'] if table in ('reaction_drafts','quick_reply_sets') else ['approve'] if table=='voice_design_jobs' else []))
        return result
    @router.get('/overview')
    async def overview():
        counts={table:store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES}
        audio=settings.data_dir/'audio';files=list(audio.glob('*.pcm'))
        return dict(counts=counts,profiles=len(PROFILES),audio_files=len(files),audio_bytes=sum(p.stat().st_size for p in files if p.exists()),paid_enabled=settings.paid_enabled,models=config_data()['data'])
    @router.get('/resources/{resource}')
    async def listing(resource:str,after:str='',q:str=''):
        if len(q)>200:raise HTTPException(422,'搜索文字过长')
        if resource=='profiles':
            items=[dict(id=k,name=v.get('name',k),data=copy.deepcopy(v),version=revision('admin_profile',k),capabilities=assets(k)) for k,v in sorted(PROFILES.items()) if k>after and (not q or q.lower() in (k+json.dumps(v,ensure_ascii=False)).lower())][:51]
        elif resource=='prompts':items=[dict(id='global',data={k:getattr(prompts,k) for k in PROMPTS},version=revision('admin_prompts','global'))]
        elif resource=='config':items=[config_data()]
        elif resource in TABLES:
            try:cursor=int(after or 0)
            except ValueError:raise HTTPException(422,'无效分页位置') from None
            fields=[r['name'] for r in store.db.execute(f'PRAGMA table_info({resource})') if r['name']!='vector']
            where='';args=[cursor]
            if q:
                where=' AND ('+' OR '.join(f'CAST({f} AS TEXT) LIKE ? ESCAPE \'\\\'' for f in fields)+')'
                pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';args.extend([pattern]*len(fields))
            direction='DESC' if resource=='voice_traces' else 'ASC'
            comparison='<' if resource=='voice_traces' else '>'
            if resource=='voice_traces' and not cursor:args[0]=9223372036854775807
            items=[dict(row) for row in store.db.execute(f'SELECT rowid AS _rowid,{",".join(fields)} FROM {resource} WHERE rowid{comparison}?{where} ORDER BY rowid {direction} LIMIT 51',args)]
            for row in items:
                if resource=='memories':row['version']=memory_version(row)
                for k in ('data','result','metrics'):
                    if row.get(k):
                        try:row[k]=json.loads(row[k])
                        except (TypeError,ValueError):pass
            return dict(items=safe(items[:50]),next=str(items[49]['_rowid']) if len(items)>50 else '')
        else:raise HTTPException(404)
        return dict(items=safe(items[:50]),next=items[49]['id'] if len(items)>50 else '')

    @router.post('/resources/{resource}/mutate')
    async def mutate(resource:str,request:Request):
        body=await request.json();action=body.get('action','edit');keys=body.get('keys',{});values=body.get('values',{});expected=body.get('expected_version',0)
        if action!='edit' and body.get('confirmed') is not True:raise HTTPException(422,'请确认操作')
        if resource in ('profiles','prompts','config'):
            char=keys.get('id');kind={'profiles':'admin_profile','prompts':'admin_prompts','config':'admin_config'}[resource];scope=char if resource=='profiles' else 'global'
            if char not in (PROFILES if resource=='profiles' else ['global'] if resource=='prompts' else ['runtime']):raise HTTPException(404)
            if expected!=revision(kind,scope):raise HTTPException(409,'数据已修改，请刷新')
            if action=='restore' and resource=='profiles':data=copy.deepcopy(ORIGINAL_PROFILES[char])
            elif action=='restore' and resource=='prompts':data=copy.deepcopy(ORIGINAL_PROMPTS)
            elif action=='edit':data=values.get('data')
            else:raise HTTPException(422,'不支持此操作')
            if not isinstance(data,dict) or len(json.dumps(data))>131072:raise HTTPException(422,'内容必须是受限大小的对象')
            if resource=='profiles':
                for field,original in ORIGINAL_PROFILES[char].items():
                    if field not in data or type(data[field]) is not type(original):raise HTTPException(422,'缺少有效角色字段: '+field)
                # Age boundaries are authoritative metadata, not an editable
                # prompt shortcut. Preserve all safety classification fields.
                for field in ('age','age_policy','romance_allowed','adult','age_boundary','visual_age'):
                    if data.get(field)!=ORIGINAL_PROFILES[char].get(field):raise HTTPException(422,'不可改变角色年龄与关系边界')
                store.put(kind,'system',scope,dict(version=expected+1,data=data));PROFILES[char]=copy.deepcopy(data)
            elif resource=='prompts':
                if set(data)!=set(PROMPTS) or any(not isinstance(v,str) or not v.strip() for v in data.values()):raise HTTPException(422,'必须保留完整的提示词字段')
                store.put(kind,'system',scope,dict(version=expected+1,data=data));apply_prompts(data)
            else:
                if set(data)!=set(CONFIG_FIELDS):raise HTTPException(422,'运行配置字段不完整')
                for k,v in data.items():
                    t=CONFIG_FIELDS[k]
                    valid=(type(v) is t or t is float and type(v) is int)
                    if not valid or t is str and not re.fullmatch(r'[a-zA-Z0-9_.-]{1,120}',v):raise HTTPException(422,'无效配置: '+k)
                    if t in (int,float) and not 0<=v<=1000000:raise HTTPException(422,'配置超出范围: '+k)
                if data['reaction_pool_size']!=1:raise HTTPException(422,'当前预缓存协议每场景仅保留 1 组')
                for k in ('narration_timeout_seconds','performance_timeout_seconds'):
                    if not .1<=data[k]<=30:raise HTTPException(422,'超时时间必须为 0.1–30 秒')
                path=settings.data_dir/'admin-settings.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.chmod(0o600);os.replace(tmp,path)
                store.put(kind,'system',scope,dict(version=expected+1,data=data))
                for k,v in data.items():setattr(settings,k,v)
            return dict(saved=True,version=expected+1)
        if resource=='memories':
            row=store.db.execute('SELECT * FROM memories WHERE rowid=?',(keys.get('_rowid'),)).fetchone()
            if not row:raise HTTPException(404)
            if expected!=memory_version(dict(row)):raise HTTPException(409,'记忆已变化，请刷新')
            with store.db:
                if action=='remove':store.db.execute('DELETE FROM memories WHERE rowid=?',(keys['_rowid'],))
                elif action=='edit':
                    if set(values)!={'content','importance'} or not isinstance(values['content'],str) or len(values['content'])>8000 or type(values['importance']) not in (int,float) or not 0<=values['importance']<=1:raise HTTPException(422,'需要有效记忆正文与 0–1 权重')
                    store.db.execute('UPDATE memories SET content=?,importance=? WHERE rowid=?',(values['content'],values['importance'],keys['_rowid']))
                else:raise HTTPException(422)
            return dict(saved=True)
        if resource in ('reaction_drafts','quick_reply_sets') and action=='clear_unused':
            row=store.db.execute(f'SELECT owner,character FROM {resource} WHERE rowid=?',(keys.get('_rowid'),)).fetchone()
            if not row:raise HTTPException(404)
            scopes={(row['owner'],row['character'])}
            for owner,char in scopes:await engine.reactions.pause(owner,char)
            claimed={j.id for j in engine.reactions.jobs.values() if getattr(j,'claimed',False)}
            with store.db:
                if resource=='quick_reply_sets':store.db.execute('DELETE FROM quick_reply_sets WHERE owner=? AND character=?',(row['owner'],row['character']))
                else:
                    rows=store.db.execute("SELECT id FROM reaction_drafts WHERE status IN ('ready','preparing') AND owner=? AND character=?",(row['owner'],row['character'])).fetchall()
                    for row in rows:
                        if row['id'] not in claimed:store.db.execute('DELETE FROM reaction_drafts WHERE id=?',(row['id'],))
            return dict(cleared=True,preserved_audio=True)
        if resource=='voice_design_jobs' and action=='approve':
            row=store.db.execute('SELECT id,character FROM voice_design_jobs WHERE rowid=?',(keys.get('_rowid'),)).fetchone()
            if not row:raise HTTPException(404)
            try:voice=store.approve_voice(row['character'],row['id'])
            except ValueError as error:raise HTTPException(409,str(error)) from None
            return dict(approved=True,character=row['character'],revision=voice.get('revision'))
        raise HTTPException(403,'内部账本只读')

    @router.post('/voices/{character}/generate')
    async def generate(character:str,request:Request):
        body=await request.json()
        if body.get('confirmed_paid') is not True:raise HTTPException(422,'此操作调用付费音色模型，请确认')
        if character not in PROFILES:raise HTTPException(404)
        from .provider import ProviderError
        try:return safe(await engine.provider.design_voice(character,PROFILES[character],revision=body.get('revision')))
        except (ProviderError,ValueError) as error:raise HTTPException(409,str(error)) from None
    app.include_router(router)
    from .admin_files import mount_files
    mount_files(app,settings,store,engine,admin)

def memory_version(row):
    # Fits JavaScript's exact integer range and detects row-id reuse or a
    # concurrent inference update without adding a SQLite schema migration.
    return int(hashlib.sha256(json.dumps({k:v for k,v in row.items() if k not in ('_rowid','version')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:13],16)
