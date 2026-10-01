"""Pure text visibility rules shared by the service and offline package compiler."""
from __future__ import annotations
import re

def visible_text(text: str) -> str:
    # Provider markup and asset control strings never reach the conversation UI.
    text = re.sub(r'\[(?:gasp|sighing|clears throat|giggles|laughing|cough|snorts|happy|sad|angry|whispering|excited|amazed|serious|empathetic)\]', '', text, flags=re.I)
    text = re.sub(r'<[^>]{1,120}>','',text)
    return text.strip()

def visible_thought(text: str) -> str | None:
    text=visible_text(text)
    # This field is fictional character monologue, never a report on reply
    # planning. Require an explicit first-person short aside, not only absence
    # of a few forbidden words. The 40-codepoint ceiling allows older genuine
    # asides; new generation targets 20. Keep the native replay guard in sync.
    english=bool(re.search(r'\b(?:I|my|we|our)\b',text,re.I)) and not re.search(r'[\u3400-\u9fff\u3040-\u30ff]',text)
    if english:
        if len(text)>96 or len(text.split())>12:return None
        if re.search(r'\b(?:user|prompt|dialogue|response strategy|as a character|should respond|need to reply|must answer|system|instruction)\b',text,re.I):return None
    elif not text or len(text)>40 or not any(word in text for word in ('我','咱')):
        return None
    metadata=('用户','让对方','对方感受','需传递','正式问候','边界清晰','回应策略',
              '准备回复','作为角色','符合人设','需要表现','应当表达','台词','情绪状态','遵守',
              '编排','提示词','分享邀请','回复意图')
    planning=(r'(?:引出|引导|转入|转向|延续|承接).{0,18}(?:话题|邀请)',
              r'(?:营造|延续|保持|维持|烘托|渲染).{0,18}氛围',
              r'(?:结合|根据|符合|体现).{0,14}(?:人设|设定|偏好|上下文)',
              r'(?:选择|使用|采用).{0,18}(?:语气|措辞|表情|动作)')
    return None if any(word in text for word in metadata) or any(re.search(p,text) for p in planning) else text
