"""Varied intentions for AI-authored check-ins, never a canned dialogue bank.

Selection is read-only. An intention enters history only when its actual text
is published, including a prepared draft consumed later by another request.
"""
import random
import re

REVISION = 'presence-checkin-v1'
TASK = ('你们安静相处了一会儿。优先关心用户此刻在做什么、是否正忙或想安静陪伴，'
        '按idle_context选定的角度写一句全新的角色式轻声搭话，不是另起无关的自我分享。'
        '只留一个容易回应的口子，具体措辞由你结合角色性格、当前剧情与真实上下文创作。')
RULES = ('通常1至2个短句，中文15至40字、英语10至28词；固定英语角色仍只说英语。'
         '可以自然使用preferences.nickname，但不用每次点名，也不反复套同一种问句。'
         '允许轻微好奇、俏皮、惦记或偶尔不确定刚才是否聊得合拍；不认定用户嫌弃你、'
         '不控诉被冷落、不要求证明感情或立刻回复，不把沉默写成用户的过错。'
         '没有信息就用询问或假设，不能假装看到了用户在做什么。'
         '不虚构用户忙完了、疲惫了、生气了或正在某个地点，不报具体沉默时长。'
         '已明确要求安静时不说话；若用户提过正在忙，优先留空间。'
         '避免重复最近主动发言的意思、句式与response_focus，不照抄角度说明。'
         '未获得回复时降低追问感，不连续表达委屈或自我怀疑。')

# (id, family, weight, writing intention). These are semantic briefs, not lines
# that the app can speak. Lower-weight uncertainty never follows an unanswered
# check-in; the first two families dominate selection in the common case.
ANGLES = (
    ('current_activity','curiosity',5,'好奇用户此刻在做什么，以不假定答案的方式轻轻问起。'),
    ('attention_elsewhere','curiosity',4,'好奇是否有什么事情吸引了用户的注意力，给对方分享的空间。'),
    ('thinking_pause','curiosity',4,'猜想用户可能在想事情，邀请分享一个念头，也接受暂时不说。'),
    ('small_update','curiosity',3,'想听听用户眼下的一件小事，问题具体但不替用户编造场景。'),
    ('something_to_share','curiosity',3,'关心用户是否有想说、却还没找到开头的事，不催促倾诉。'),
    ('busy_hands','consideration',5,'试探是不是正腾不开手；表达不急着回应，避免命令式安慰。'),
    ('need_a_pause','consideration',4,'关心是否想歇一歇或放空，留一个轻松选择，不判断用户累了。'),
    ('convenient_moment','consideration',4,'体贴地确认现在是否方便聊天，允许之后再接着说。'),
    ('pace_preference','consideration',3,'询问希望继续聊还是暂时安静一下，尊重用户自己的节奏。'),
    ('light_company','company',3,'用角色的性格表达愿意安静陪着，不要求用户交代理由。'),
    ('unfinished_thread','connection',3,'若最近有具体未完的话题，轻轻确认是否想继续；没有就关心近况，不重答旧问题。'),
    ('curious_about_mood','connection',3,'关心此刻的心情是否愿意分享，不把沉默等同难过。'),
    ('gentle_ping','playful',2,'以角色风格俏皮地确认对方还在不在，把它当轻松招呼而非查岗。'),
    ('imaginary_detour','playful',2,'把短暂走神比作一个明确的想象，用小玩笑接上话，不指责不理自己。'),
    ('miss_the_exchange','warmth',2,'表达有点想听对方接话的亲近感，不要求陪伴或制造亏欠。'),
    ('topic_fit','uncertainty',1,'偶尔有一点不确定刚才的话题是否合口味，温和允许换题，不说自己被嫌弃了。'),
    ('too_much_detail','uncertainty',1,'仅在上一轮确实较长时，试探是否说得太细；否则换为询问聊天节奏。'),
    ('misread_tone','uncertainty',1,'若刚才确有分歧，轻声确认自己是否误会了意思；否则试探对方想不想换个轻松角度。'),
)
BY_ID = {a[0]:a for a in ANGLES}
QUIET = re.compile(r'(?:先|暂时|现在|一会|请)?(?:别|不要|不用)(?:再|主动)?(?:说话|打扰|找我|发消息|回复)|让我(?:先|暂时)?(?:安静|静静)|'
                   r'\b(?:please be quiet|leave me alone|give me (?:some )?space|(?:don.t|do not) (?:talk|interrupt|message))\b',re.I)
BUSY = re.compile(r'(?:我|现在|正在|这会).{0,8}(?:忙|开会|工作|上课|开车)|\b(?:I(?:.m| am) busy|in a meeting|working|driving)\b',re.I)

def availability(messages):
    last = next((m.get('text','') for m in reversed(messages) if m.get('role')=='user'),'')
    if QUIET.search(last):return 'quiet_requested'
    return 'busy' if BUSY.search(last) else 'unknown'

def context(store,owner,char,conversation):
    recent = store.get('idle_presence',owner,char,{}).get('recent_angles',[])[-6:]
    unanswered = store.get('proactive',owner,char,{}).get('unanswered',0)
    state = availability(conversation.get('recent_messages',[]))
    last_family = BY_ID[recent[-1]][1] if recent and recent[-1] in BY_ID else None
    choices = [a for a in ANGLES if a[0] not in recent[-4:] and a[1]!=last_family
               and (not unanswered or a[1] not in ('uncertainty','playful','warmth'))
               and (state=='unknown' or a[1] in ('consideration','company'))]
    if not choices:choices = [a for a in ANGLES if a[1] in ('consideration','company') and a[0] not in recent[-3:]]
    chosen = random.choices(choices,weights=[a[2] for a in choices],k=1)[0]
    return dict(revision=REVISION,task=TASK,rules=RULES,
                angle=dict(id=chosen[0],family=chosen[1],intention=chosen[3]),
                recent_angles=recent,unanswered_checkins=unanswered,availability=state)

def commit(store,owner,char,script):
    angle = script.get('idle_angle')
    if script.get('text') and angle in BY_ID:
        previous = store.get('idle_presence',owner,char,{}).get('recent_angles',[])
        store.put('idle_presence',owner,char,dict(revision=REVISION,recent_angles=(previous+[angle])[-6:]))
