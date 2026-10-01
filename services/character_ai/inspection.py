"""Complete, read-only developer view of authored and effective AI configuration."""
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from . import prompts, schemas
from .profiles import PROFILES, assets
from .provider import structured_messages, structured_payload, EMOTIONS, DELIVERY, VOCALS
from .planner_wire import CompactPlan, SpokenPlan, WIRE_SHAPE, SPOKEN_SHAPE
from .parallel_performance import PerformancePlan, performance_context
from .public_profiles import public_profile

def report(settings,engine,owner,request):
    char=request.character_id;store=engine.store
    context=engine.context(owner,request,persist=False)
    sections=[]
    def add(id,title,detail,value):
        sections.append(dict(id=id,title=title,detail=detail,
                             content=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)))
    add('public','公开角色资料','用户可见字段；不含提示词和私有设定。',public_profile(char))
    add('persona','完整角色设定','实际服务端角色源配置，含背景、性格、秘密、声线设计与说话习惯。',PROFILES[char])
    add('prompts','全部提示词','当前运行版本的原文，未摘要、未省略。',
        dict(planner=prompts.PLANNER,core_planner=prompts.CORE_PLANNER,performer=prompts.PERFORMER,narrator=prompts.NARRATOR,
             structure=prompts.PLAN_SHAPE,compact_structure=WIRE_SHAPE,spoken_structure=SPOKEN_SHAPE,reply_length=prompts.REPLY_LENGTH))
    add('context','本轮上下文预览','与生成共用上下文组装；只读，不发送、不扣费、不更新记忆。',context)
    add('memories','全部服务端记忆','本账号、本角色的全部记忆；本轮实际选中的记忆见上下文。',
        [dict(r) for r in store.db.execute('SELECT id,source,content,importance,created,recalled FROM memories WHERE owner=? AND character=? ORDER BY created',(owner,char))])
    add('client','本机发送内容','当前草稿及偏好、候选记忆、可用表现等请求正文。',request.model_dump(mode='json'))
    add('payload','完整规划请求预览','与实际 provider 共用构造函数；JSON Schema、system/user 消息及采样参数全部展开。',
        structured_payload(settings,'plan',structured_messages('plan',prompts.CORE_PLANNER if request.parallel_performance else prompts.PLANNER,context,
            schemas.CoreTimelinePlan if request.parallel_performance else (schemas.ShakeTimelinePlan if request.trigger in ('model_shaken','model_pinched') else schemas.TimelinePlan) if request.timeline_reply else schemas.Plan)))
    if request.parallel_performance:
        add('performance-payload','并发表演请求预览','与核心对话同时开始，8秒默认上限；失败不影响文字、心声和语音。',
            structured_payload(settings,'performance',structured_messages('performance',prompts.PERFORMER,performance_context(context),PerformancePlan)))
    add('schemas','全部生成结构约束','规划、旁白及客户端请求的完整 JSON Schema。',
        dict(plan=schemas.Plan.model_json_schema(),timeline_plan=schemas.TimelinePlan.model_json_schema(),compact_plan=CompactPlan.model_json_schema(),spoken_plan=SpokenPlan.model_json_schema(),performance_plan=PerformancePlan.model_json_schema(),shake_plan=schemas.ShakeTimelinePlan.model_json_schema(),narration=schemas.NarrationResult.model_json_schema(),request=schemas.Request.model_json_schema()))
    add('performances','完整表演目录','实际可选资源、情绪映射所需意图、持续时间、冷却及可见效果。',assets(char))
    voice=store.get('voice','system',char,{})
    add('voice','语音与识别设定','完整音色设计在角色设定中；实际每次合成的文字、指令在请求记录中。',
        dict(active_voice={k:voice[k] for k in ('voice_id','revision','approved','model') if k in voice},
             emotion_tags=EMOTIONS,delivery_instructions=DELIVERY,vocal_tags=VOCALS,
             recognition_hotwords=PROFILES[char]['hotwords']+([request.preferences['nickname']] if request.preferences.get('nickname') else [])))
    fields=('character_model','suggestions_model','translation_model','tts_model','asr_model','narration_timeout_seconds','performance_timeout_seconds','reaction_pool_size','reaction_pool_ttl_seconds','entry_pool_ttl_seconds','paid_enabled','enforce_conversation_limits',
            'max_daily_calls','max_daily_tts_characters','max_daily_asr_seconds','max_voice_designs','enable_test_inspector','semantic_novelty')
    add('models','模型与运行参数','凭证、认证头和本机文件路径不属于角色调教，不在报告中返回。',{k:getattr(settings,k) for k in fields})
    add('translation-provider','翻译服务状态','专用 Qwen-MT 优先；只有快速模型确实可用时才临时回退。一小时后重新检查；两者均被拒绝时缩短为30秒后的下一次用户请求，不后台重试。',
        store.get('translation_provider','system','',dict(preferred=settings.translation_model)))
    add('requests','最近实际请求','本账号、本角色最近 12 次 provider 请求正文，含格式修正；升级前未记录的请求不会伪造。',
        store.get('inspection_requests',owner,char,[]))
    add('reply-flow','最近分段编排','本账号、本角色最近一轮的原始心声锚点与实际可见段落；仅测试部署记录。',store.get('reply_flow_review',owner,char,{}))
    add('novelty','最近内部生成复核','本账号、本角色最近候选的原文检查、语义相关提示和最多两次内部修订；不向聊天展示。仅测试部署记录。',store.get('novelty_review',owner,char,{}))
    add('latency','最近回复耗时','收到请求至完成规划、文字交付、首段音频及结束的毫秒数；服务端时间，不是手机扬声器时延。',store.get('reply_latency',owner,char,{}))
    add('performance-review','最近并发表演','独立任务的耗时、实际计划或降级原因。',store.get('performance_review',owner,char,{}))
    add('reaction-pool','未说出的场景候选','当前账号／角色未消费的手势、待机、初见、启动与回访候选，含台词、心声、表演及生成／过期时间；不是聊天历史。',
        [dict(id=r['id'],kind=r['kind'],created=r['created'],expires=r['expires'],draft=json.loads(r['data']))
         for r in store.db.execute("SELECT * FROM reaction_drafts WHERE owner=? AND character=? AND status='ready' ORDER BY created",(owner,char))])
    add('reaction-pool-review','预备反应命中记录','只在真实场景触发时消费，空池走实时 AI；不会为查看此页生成候选。',store.get('reaction_pool_review',owner,char,{}))
    add('latency-history','最近二十轮耗时','区分完整缓存、接管正在生成与实时生成；不包含手机扬声器测量。',store.get('reply_latency_history',owner,char,[]))
    from .quick_replies import SUGGESTIONS
    add('quick-reply-prompt','智能回复完整设定','三条用户候选及相对倾向排序；只有用户选中的分支进入聊天。',SUGGESTIONS)
    row=store.db.execute('SELECT source,data,expires FROM quick_reply_sets WHERE owner=? AND character=?',(owner,char)).fetchone()
    add('quick-replies','未选择的接话分支','包含三条用户候选；预演回答在场景候选中。未选择内容不是历史。',dict(source=row['source'],options=json.loads(row['data']),expires=row['expires']) if row else {})
    # Runtime rules live in executable code as well as prompts. Include the full
    # deployed modules so a tester can inspect thresholds/filters without a
    # hand-maintained summary becoming a second, misleading source of truth.
    for name in ('prompts','schemas','planner_wire','parallel_performance','ordered_audio','reaction_pool','prepared_draft','quick_replies','greetings','idle_presence','novelty','semantic_novelty','reply_flow','reply_text','director','performance_library','speech_text','orchestrator','provider','translation','asr','storage'):
        module=importlib.import_module('.'+name,__package__)
        add('rules-'+name,'执行规则 · '+name,'当前服务实际加载版本的完整规则源码。',Path(module.__file__).read_text())
    return dict(version=1,character_id=char,captured_at=datetime.now(timezone.utc).isoformat(),sections=sections)
