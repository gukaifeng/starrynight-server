"""Entry greetings are new turns, never replay or implicit historical questions."""
import re
import unicodedata
from difflib import SequenceMatcher
from .speech_text import spoken_text

ENTRY_TRIGGERS = {'appLaunch', 'firstLaunch', 'firstMeeting', 'characterSwitch'}

def greeting_context(history, previous_greetings, elapsed_seconds):
    previous = list(dict.fromkeys(previous_greetings +
                    [m['text'] for m in history if m['role'] == 'assistant']))[-10:]
    has_met=bool(history or previous_greetings)
    return dict(has_met=has_met,
                elapsed_seconds=elapsed_seconds,
                previous_lines_to_avoid=previous,
                task=('用户此刻重新进入会话，没有发送新问题。历史中的用户问题已经属于过去，不能再作答。写一条全新的见面问候；可以接续旧话题，但要带来新的内容，也可以换个自然的新切入点。'
                      if has_met else '这是你们第一次见面，没有之前的共同经历。用角色自己的口吻主动打一个简短招呼，让用户容易接话，不说好久不见或回来了，不编造曾经一起聊过的话。'))

def normalized(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', spoken_text(text))).lower()

def repeated_greeting(text, previous):
    candidate = normalized(text)
    for line in previous:
        old = normalized(line)
        if not old or not candidate: continue
        if candidate == old: return True
        matcher = SequenceMatcher(None, candidate, old, autojunk=False)
        if min(len(candidate), len(old)) >= 12 and matcher.ratio() >= .84: return True
        # Catch an old answer with only a short "welcome back" tacked on.
        if len(old) >= 16 and old in candidate: return True
    return False

def plan_text(plan):
    return '\n'.join(b.dialogue.text for b in plan.beats if b.dialogue)
