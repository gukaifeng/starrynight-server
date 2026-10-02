"""Optional visible text quality; never changes speech or suppresses animation."""
import json
import re
from difflib import SequenceMatcher

def flatten(text):
    text=re.sub(r'[（）()]','',text)
    return re.sub(r'\s+',' ',text).strip(' *_，,;；')

def key(text):return re.sub(r'[^\w\u3400-\u9fff]','',flatten(text).casefold())

def family(text):
    if re.search(r'笑意|笑容|微笑|轻笑|含笑|开心的(?:神情|表情)|唇角.{0,12}笑|嘴角.{0,10}(?:扬|弯)|\bsmil\w*\b',text,re.I):return 'smile'
    return None

def repeated(text,previous):
    value=key(text)
    if not value:return True
    for old in previous:
        other=key(old)
        if value==other or (family(text) and family(text)==family(old)):return True
        if min(len(value),len(other))>=6 and SequenceMatcher(None,value,other).ratio()>=.78:return True
    return False

def recent(store,owner,character,exclude_message=''):
    rows=store.db.execute("SELECT data FROM messages WHERE owner=? AND character=? AND role='assistant' AND id!=? ORDER BY created DESC LIMIT 8",(owner,character,exclude_message)).fetchall()
    result=[]
    for row in rows:
        for beat in json.loads(row['data']).get('beats',[]):
            if beat.get('parts') is not None:
                result.extend(p['text'] for p in beat['parts'] if p.get('kind')!='dialogue')
            else:
                result.extend(n['text'] for n in beat.get('narrations',[]))
                if beat.get('thought'):result.append(beat['thought'])
    return list(dict.fromkeys(result))[:32]

def allowed_language(text,language):
    return language!='en' or not re.search(r'[\u3400-\u9fff\u3040-\u30ff]',text)

def english_effect(asset):
    # Reviewed semantic labels for actual resolved resources, not invented
    # motions. Unknown labels remain animation-only instead of leaking Chinese.
    intent=asset.get('intent','')
    labels={'soft_smile':'A small smile appears.','bright_smile':'Her expression brightens.',
        'teasing_smile':'A playful smile flickers.','shy_smile':'A shy smile appears.',
        'thinking':'Her expression turns thoughtful.','surprised':'Her eyes widen slightly.',
        'pout':'A small pout appears.','serious':'Her expression grows serious.',
        'blink':'She blinks softly.','nod':'She gives a small nod.',
        'ear_wiggle':'Her ears gently twitch.','tail_wag':'Her tail sways.',
        'tail_sway':'Her tail sways.','wave':'She gives a small wave.'}
    return labels.get(intent)

def plan_problem(plan,previous):
    from .reply_text import visible_thought
    candidates=[a for b in plan.beats for a in b.asides if a.visibility=='visible']
    if not candidates:return None # Legacy / intentionally hidden-only plans.
    texts=[text for a in candidates if (text:=visible_thought(a.text))]
    if not texts or all(repeated(text,previous) for text in texts):
        return '本轮可见心声全部无效或与近期相同/近似。保持正确台词主题，写针对当前这一刻的新感受，不复述期待、陪伴或微笑，不用同义词替换。'
    return None

def appearance_choices(profile,previous,language):
    # Only reviewed model facts can be selected. Empty facts stay empty.
    english={'银灰色长发':'Silver-gray hair frames her face.','清透蓝色双眼':'Her eyes are a clear blue.',
        '银白色长发':'Silvery-white hair frames her face.','明亮蓝色双眼':'Her eyes are a bright blue.'}
    values=[english.get(fact) if language=='en' else fact for fact in profile.get('appearance_facts',[])]
    return [v for v in values if v and not repeated(v,previous)][:4]

def review_script(script,previous,language):
    """Recheck prepared candidates at consumption against intervening events."""
    seen=list(previous);beats=[]
    for beat in script.get('beats',[]):
        b=dict(beat)
        if b.get('parts') is not None:
            parts=[]
            for part in b['parts']:
                if part['kind']=='dialogue':parts.append(part);continue
                text=flatten(part['text'])
                if allowed_language(text,language) and not repeated(text,seen):
                    parts.append({**part,'text':text});seen.append(text)
            b['parts']=parts
        if b.get('thought'):
            text=flatten(b['thought'])
            b['thought']=text if allowed_language(text,language) and not repeated(text,previous) else None
        b['narrations']=[{**n,'text':flatten(n['text'])} for n in b.get('narrations',[])
            if allowed_language(n['text'],language) and not repeated(n['text'],previous)]
        beats.append(b)
    return {**script,'beats':beats}
