"""Explicit public character cards. Never serialize the full authored persona."""
from .profiles import PROFILES
from .roleplay import public_scenarios

INTRODUCTIONS = {
    'anime-chiffon':('今天的心事，慢慢说也没关系。','戚风在小镇花店学习花艺，喜欢手账和雨后的空气。她温柔、慢热，也藏着一点俏皮，愿意陪你把平常的一天聊出小小的光亮。'),
    'anime-karin':('留一点空白，画进今天的新故事。','卡琳喜欢给小物件起名字，也爱画手绘明信片。她开朗、机灵，会和你分享小发现，也会认真听你说起不那么开心的事。'),
    'anime-kipfel': ('把平凡的小事，慢慢说给我听。',
        '住在山间小书屋楼上的琪宝，喜欢把落叶夹进旧书。她慢热、安静，有一点迷糊；熟悉以后，也会悄悄和你开个小玩笑。'),
    'anime-mamehinata': ('今天的小小开心，也想分给你。',
        '豆日向是小镇面包房的小帮手，爱散步，也爱收集好听的声音。她好奇、直率，容易为小事雀跃，也愿意认真听你把烦恼说完。'),
}

def public_profile(character):
    p=PROFILES[character]
    if character in INTRODUCTIONS:invitation,story=INTRODUCTIONS[character]
    else:invitation,story=p['presentation']['invitation'],p['presentation']['story']
    return dict(id=character,name=p['name'],invitation=invitation,story=story,
                occupation=p['occupation'],world=p['world'],traits=p['personality']['traits'],
                likes=p['personality']['likes'],tone=p['speaking_style']['tone'],
                dialogueLanguage=p['dialogue_language'],scenarios=public_scenarios(character),
                profileRevision=p.get('profile_revision','2026-09-30-base-v1'))

def public_catalog():
    return dict(version=1,characters=[public_profile(c) for c in PROFILES])
