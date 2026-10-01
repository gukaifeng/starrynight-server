import random, math, time, re
from .profiles import assets

FALLBACK={'thinking':['confused','soft_smile','neutral'],'shy_smile':['soft_smile','neutral'],'teasing_smile':['soft_smile','neutral'],
 'bright_smile':['soft_smile','neutral'],'worried':['thinking','neutral'],
 'excited':['bright_smile','soft_smile','neutral'],'proud':['confident','teasing_smile','neutral'],
 'nod':['idle'],'shake_head':['idle'],'wave':['open_hands','idle'],'cover_mouth':['idle'],
 'look_away':['idle'],'lean_forward':['idle'],'hug':['idle']}

INTENT_GUIDE = dict(soft_smile='柔和微笑：问候、安心、倾听',bright_smile='开心明亮的笑：好消息、被认可',
    teasing_smile='俏皮笑：轻松打趣',playful='单眼眨眼：俏皮回应或用户要求眨眼',
    confident='自信：鼓励、打气',proud='小小得意：自己的小成就',pout='鼓脸/嘟嘴：轻微撒娇或玩笑',
    playful_tongue='短暂吐舌：调皮玩笑',confused='晕乎乎：困惑',sleepy='打哈欠表情：困倦',
    excited='兴奋：惊喜、期待',sad='难过/含泪：悲伤',thinking='疑惑思考：好奇、问题',
    surprised='惊叹：意外消息',serious='严肃/不满',worried='担心/紧张',
    thumbs_up='手指点赞：认可、称赞；不抬整条手臂',peace='剪刀手/比耶：庆祝、合照；手指姿势',
    open_hands='舒展手掌：友好问候；不是挥手动画',fist='手指握拳：打气',point='伸直食指：强调一个想法；不指向具体物体',
    rock='摇滚手指：活泼玩笑',ear_wiggle='耳朵动态轻动：见面、好奇、期待',ear_perk='竖耳：认真倾听、惊喜',
    ear_lower='垂耳：低落或担心',tail_wag='竖尾摇动：开心、欢迎',tail_sway='尾巴上下轻摆：轻松交流',
    tail_lower='低垂摇尾：安慰、低落')
ALIASES = dict(smile='soft_smile',happy='bright_smile',cheerful='bright_smile',curious='thinking',
               curious_smile='thinking',wink='playful',pouting='pout',excited_smile='excited',
               victory='peace',v_sign='peace',ear_twitch='ear_wiggle',wag_tail='tail_wag')
EMOTION_FACE = dict(happy='bright_smile',sad='sad',surprised='surprised',serious='serious',worried='worried',
                    curious='thinking',confused='confused',excited='excited',playful='teasing_smile')

def spoken_face(beat,dominant='neutral'):
    """Ground expressive speech metadata in existing author-defined faces."""
    if not beat.dialogue:return EMOTION_FACE.get(dominant,'neutral')
    speech=beat.dialogue.speech
    if speech.emotion in ('sad','surprised','serious','worried'):return EMOTION_FACE[speech.emotion]
    if speech.delivery=='hesitant':return 'thinking'
    if speech.delivery=='teasing':return 'teasing_smile'
    if speech.delivery in ('soft','gentle','whisper') and speech.emotion in ('neutral','happy'):return 'soft_smile'
    if any(v.event in ('giggle','laugh') for v in beat.vocal_events):return 'teasing_smile'
    return EMOTION_FACE.get(speech.emotion,EMOTION_FACE.get(dominant,'neutral'))

def visible_narration(value):
    """Read-time compatibility for old saved literary appearance descriptions."""
    if value.get('mode')=='performed':return True
    text=value.get('text','')
    return not re.search(r'头发|发色|长发|短发|棕色|金色|肤色|皮肤|眼睛|瞳孔|眼眸|身材|脸型|衣服|裙子|穿着|留着|一双|外貌',text)

class Director:
    def __init__(self,store,rng=None):self.store=store;self.rng=rng or random.Random()
    def capability(self,character,available):
        enabled=[a for a in assets(character) if a['enabled'] and a['asset_id'] in available and a.get('speech_compatible',True)]
        intents={a['intent'] for a in enabled}
        return dict(supported_expression_intents=sorted({'neutral'}|{a['intent'] for a in enabled if a['kind']=='expression'}),
                    supported_action_intents=sorted({'idle'}|{a['intent'] for a in enabled if a['kind']=='action'}),
                    intent_guide={k:v for k,v in INTENT_GUIDE.items() if k in intents},
                    groups=[dict(group=g,label=next(a.get('group_label',g) for a in enabled if a['group']==g),
                        choices=[dict(intent=a['intent'],meaning=a.get('label',a['observable_effects'][0]),
                                      automatic=a.get('automatic',True)) for a in enabled if a['group']==g])
                        for g in dict.fromkeys(a['group'] for a in enabled)],
                    choreography=dict(simultaneous_groups=True,phases=2,target_cues='每句组合4至8项，并在较长台词中自然变化；按角色实际可用组增减',
                                      contextual_only='automatic=false只在对话明确合适或用户要求时使用，不能随机更换坐躺或穿搭'))
    def resolve(self,owner,character,kind,intent,intensity,relationship,state,available):
        now=time.time()
        library=[a for a in assets(character) if a['enabled'] and a['asset_id'] in available and a['kind']==kind]
        candidates=[];match='exact'
        for semantic in [intent]+FALLBACK.get(intent,['neutral' if kind=='expression' else 'idle']):
            if semantic in ('neutral','idle'): return None, 'none'
            for a in library:
                if a['intent']!=semantic or relationship.get('closeness',0)<a['min_closeness'] or state.get('anger',0)>a['max_anger']:continue
                if not a['intensity_min']<=intensity<=a['intensity_max']:continue
                row=self.store.db.execute('SELECT count(*),max(created) FROM asset_usage WHERE owner=? AND character=? AND asset=?',(owner,character,a['asset_id'])).fetchone()
                used,last=row[0],row[1] or 0
                if now-last<a['cooldown_sec']:continue
                style=(1-.4*intensity) if character=='anime-kipfel' else (.6+.4*intensity)
                context=(1-state.get('anxiety',.1)) if kind=='action' else (.7+.3*state.get('attention_to_user',.7))
                score=.35*(1 if semantic==intent else .75)+.20*(1-abs(intensity-(a['intensity_min']+a['intensity_max'])/2))+.15*style+.10*context+.10*min(1,(now-last)/120)+.05*(1 if a['rarity']=='common' else .7)+.05/(used+1)
                candidates.append((a,score*a['base_weight']))
            if candidates:
                candidates=sorted(candidates,key=lambda x:x[1],reverse=True)[:4]
                chosen=self.rng.choices([a for a,_ in candidates],weights=[w for _,w in candidates],k=1)[0]
                with self.store.db:self.store.db.execute('INSERT INTO asset_usage(owner,character,asset,kind,created) VALUES(?,?,?,?,?)',(owner,character,chosen['asset_id'],kind,now))
                return chosen,match
            match='approximate'
        return None,'none'
    def beat(self,owner,character,beat,relationship,state,available,dominant_emotion='neutral',trigger='user_message',automatic_fill=True,record_usage=True):
        performance=beat.performance.model_copy()
        performance.expression_intent=ALIASES.get(performance.expression_intent,performance.expression_intent)
        performance.action_intent=ALIASES.get(performance.action_intent,performance.action_intent)
        for vocal in beat.vocal_events:
            if vocal.visual_sync:
                if performance.expression_intent=='neutral':performance.expression_intent=vocal.visual_sync.expression_intent
                if performance.action_intent=='idle':performance.action_intent=vocal.visual_sync.action_intent
        # A typed speech emotion is reliable fallback evidence; don't discard it
        # just because the planner left its separate performance at the default.
        if automatic_fill and performance.expression_intent=='neutral':
            performance.expression_intent=spoken_face(beat,dominant_emotion)
            if performance.expression_intent=='neutral' and trigger in ('appLaunch','firstLaunch','firstMeeting','characterSwitch'):
                performance.expression_intent='soft_smile'
        library=[a for a in assets(character) if a['enabled'] and a['asset_id'] in available and a.get('speech_compatible',True)]
        mood=dominant_emotion
        if mood=='neutral' and beat.dialogue:mood=beat.dialogue.speech.emotion
        if trigger in ('model_shaken','model_pinched'):mood='playful' if performance.expression_intent in ('pout','teasing_smile') else 'serious'
        cues=[];selected=set();occupied={};now=time.time()
        def add(group,intent=None,offset=0,active=True,automatic=False):
            if len(cues)>=24 or any(abs(offset-t)<1200 for t in occupied.get(group,[])):return
            pool=[a for a in library if a['group']==group and a['asset_id'] not in selected]
            if automatic:
                pool=[a for a in pool if a.get('automatic',True) and
                      (not a.get('moods') or mood in a['moods'] or (a['kind']=='expression' and mood=='neutral' and a['intent']=='soft_smile'))]
            elif intent:
                intent=ALIASES.get(intent,intent)
                pool=[a for a in pool if a['intent']==intent]
            else:return
            weighted=[]
            for a in pool:
                if not active and a.get('source_kind')!='toggle':continue
                if relationship.get('closeness',0)<a['min_closeness'] or state.get('anger',0)>a['max_anger']:continue
                if not a['intensity_min']<=performance.intensity<=a['intensity_max']:continue
                if any(a['group'] in c['asset'].get('conflicts',[]) or c['asset']['group'] in a.get('conflicts',[]) for c in cues):continue
                used,last=self.store.db.execute('SELECT count(*),max(created) FROM asset_usage WHERE owner=? AND character=? AND asset=?',(owner,character,a['asset_id'])).fetchone()
                if now-(last or 0)<a['cooldown_sec']:continue
                # Data-driven mood + recency diversity; no character/group enum.
                weight=a['base_weight']*(1+min(3,(now-(last or 0))/20))/(1+math.log1p(used))
                weighted.append((a,weight))
            if not weighted:return
            a=self.rng.choices([a for a,_ in weighted],weights=[w for _,w in weighted],k=1)[0]
            if record_usage:
                with self.store.db:self.store.db.execute('INSERT INTO asset_usage(owner,character,asset,kind,created) VALUES(?,?,?,?,?)',(owner,character,a['asset_id'],a['kind'],now))
            selected.add(a['asset_id']);occupied.setdefault(group,[]).append(offset)
            duration=min(8000,a['duration_ms']) if automatic else a['duration_ms']
            cues.append(dict(asset=a,offset_ms=offset,duration_ms=duration,active=active))
        # The planner can request every declared group, including new author
        # groups, postures and temporary toggles. Keep old plans compatible.
        for cue in sorted(performance.cues,key=lambda c:c.offset_ms):
            group=cue.group
            matches={a['group'] for a in library if a['intent']==ALIASES.get(cue.intent,cue.intent)}
            if group not in matches and len(matches)==1:group=next(iter(matches))
            add(group,cue.intent,cue.offset_ms,cue.active)
        if performance.expression_intent!='neutral':
            for semantic in [performance.expression_intent]+FALLBACK.get(performance.expression_intent,[]):
                match=next((a for a in library if a['kind']=='expression' and a['intent']==semantic),None)
                if match:
                    add(match['group'],semantic)
                    break
        if performance.action_intent!='idle':
            match=next((a for a in library if a['intent']==performance.action_intent),None)
            if match:add(match['group'],performance.action_intent)
        groups=list(dict.fromkeys(a['group'] for a in library if a.get('automatic',True))) if automatic_fill else []
        # Rotate underserved groups through the bounded parallel budget for
        # future avatars with many channels. Existing avatars use all 4 groups.
        groups.sort(key=lambda g:self.store.db.execute('SELECT count(*) FROM asset_usage WHERE owner=? AND character=? AND asset IN (%s)' % ','.join('?' for _ in [a for a in library if a['group']==g]),
                    (owner,character,*[a['asset_id'] for a in library if a['group']==g])).fetchone()[0])
        for index,group in enumerate(groups[:8]):
            if not occupied.get(group):add(group,offset=index*100,automatic=True)
        if beat.dialogue and len(beat.dialogue.text)>=10:
            second=min(4200,max(2200,len(beat.dialogue.text)*65))
            if automatic_fill and beat.dialogue.speech.delivery=='hesitant':
                # Resolve a brief pause into a softer expression where the
                # avatar provides one. Never invent skeletal movements.
                for a in library:
                    if a['kind']=='expression' and a['intent']=='soft_smile' and a.get('automatic',True):
                        add(a['group'],'soft_smile',second);break
            for index,group in enumerate(groups[:8]):add(group,offset=second+index*120,automatic=True)
        cues.sort(key=lambda c:c['offset_ms'])
        face=next((c['asset'] for c in cues if c['asset']['kind']=='expression'),None)
        action=next((c['asset'] for c in cues if c['asset']['kind']=='action'),None)
        return dict(beat_id=beat.beat_id,expression_asset=face,action_asset=action,performances=cues,
                    grounding='exact' if cues else 'none')

def grounded(narration,resolved,appearance_facts=()):
    entry=next((r for r in resolved if r['beat_id']==narration.beat_id),None)
    if not entry:return False
    items=([c['asset'] for c in entry['performances'] if c.get('active',True)] if 'performances' in entry
           else [entry[k] for k in ('expression_asset','action_asset') if entry.get(k)])
    effects=[s for a in items for s in a['observable_effects']]
    if narration.mode=='performed' and (not effects or not narration.evidence or any(e not in effects for e in narration.evidence)):return False
    if narration.mode=='performed':
        # Hard grounding: a valid citation alone is insufficient. Models can cite
        # a hand pose and then hallucinate handing over a cup. Permit only the
        # cited observable clauses (plus punctuation/pronoun), never an expansion.
        clean=lambda s: re.sub(r'[\s，。；、！,.!;：:她他]+','',s)
        if clean(narration.text)!=clean(''.join(narration.evidence)):return False
    if narration.mode=='literary':
        if narration.visual_grounding!='none':return False
        # Static appearance is already visible on the model. Neither reviewed
        # character facts nor fictional background authorize appearance prose.
        if narration.evidence:return False
        remainder=narration.text
        # Unperformed narration may describe conversational pace only.
        words=r'(?:短暂|片刻|轻轻|微微|渐渐|稍稍|慢慢|柔和|温柔|安静|轻柔|平静|停顿|沉默|对话|话语|话音|语气|交流|声音|字句|余音|这一刻|此刻|之间|之中|落下|放缓|停留|延续|流淌|散开|下来|一点|一阵|让|中|在|的|地|得|了|也|更|很|里|间|变|得以|带着|显得|随着|和|与|而|着|是|一|丝|份|分|，|。|、|；|：|…|\s)'
        if not re.fullmatch(words+r'*',remainder):return False
    # Do not display common hallucinated physical interactions even if the model
    # incorrectly cites an otherwise valid facial expression as evidence.
    forbidden=['走到','走向','拿起','抱住','拥抱','拍你','拍了拍','捂嘴','捂住嘴','抬手','伸手','伸出手','打开门','靠在你','坐到','递给','摸了摸','转过身','偏过头','别过脸','转过头']
    return not any(x in narration.text and not any(x in e for e in effects) for x in forbidden)

def grounded_excerpt(narration,resolved,appearance_facts=()):
    """Render only independently grounded clauses or the model's verified citations.

    Static appearance clauses are omitted even if factually correct. Preserve
    only conversational pace or observable evidence from selected animations;
    never replace rejected prose with a local invented reply or physical action.
    """
    if grounded(narration,resolved,appearance_facts):return narration
    parts=[];evidence=[]
    for clause in re.split(r'[，。！？；,!?;\n]+',narration.text):
        clause=clause.strip()
        if not clause:continue
        citations=[e for e in narration.evidence if e in clause]
        candidate=narration.model_copy(update={'text':clause,'evidence':citations})
        if grounded(candidate,resolved,appearance_facts):
            parts.append(clause)
            for citation in citations:
                if citation not in evidence:evidence.append(citation)
    if parts:
        excerpt=narration.model_copy(update={'text':'。'.join(parts)+'。','evidence':evidence})
        if grounded(excerpt,resolved,appearance_facts):return excerpt
    if narration.evidence:
        cited=narration.model_copy(update={'text':'。'.join(dict.fromkeys(narration.evidence))+'。',
                                         'evidence':list(dict.fromkeys(narration.evidence))})
        if grounded(cited,resolved,appearance_facts):return cited
    return None
