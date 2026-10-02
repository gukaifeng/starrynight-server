#!/usr/bin/env python3
"""Compile authored role-local data. No model, voice or image API calls."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def compile_data(root=ROOT, check=False):
    load=lambda p:json.loads((root/p).read_text())
    expansion=load('authoring/companion-expansion.json')
    roster=load('authoring/active-roster.json')['characters']
    profiles=load('services/character_ai/character_profiles.json')
    scenarios=load('services/character_ai/character_scenarios.json')
    openings=load('authoring/openings.json')
    assert expansion['schemaVersion']==1 and set(expansion['characters'])<=set(roster)
    for role, e in expansion['characters'].items():
        english=e['language']=='en'
        profile=dict(name=e['name'],age=e['age'],gender='female',world='星夜小镇 · '+e['place'],
            occupation=e['occupation'],appearance_facts=[],
            background=dict(family='和关心自己的家人保持联系，也有独立的日常安排。',childhood=e['history'],
                education=e['history'],current_life=e['activity']),
            personality=dict(traits=e['traits'],likes=e['likes'],dislikes=['被催促','敷衍','不被尊重的边界']),
            speaking_style=dict(default_length='日常1至2个自然短句，用户要求详细时再展开',tone=e['tone'],
                habits=['先回应具体内容','自然使用停顿和语气符号','偶尔表达第一人称心理活动，不复述外貌']),
            secrets=[e['secret']],scene=dict(location=e['place'],current_activity=e['activity'],environment='舒适安静'),
            hotwords=[e['name'],'星夜'],dialogue_language=e['language'],
            voice_revision='approved-reuse-v1',voice_source_character=e['voiceSource'],
            voice_prompt='复用已获批准的原创声线，不新建或仿制音色。',voice_delivery=e['tone'],
            preview_text=e['openings'][0],presentation=dict(invitation=e['hook'],story=e['story']),
            profile_revision=expansion['revision'])
        profiles['characters'][role]=profile
        short=role.removeprefix('anime-')
        routes=[]
        for kind,title,premise,symbol in [
            ('relationship','慢慢认识','从自然的相识开始，了解彼此的喜好。保持角色自身生活与边界，关系按用户选择推进，可暂停或转向。','heart'),
            ('task','一起练习','围绕角色的兴趣陪用户练表达、整理思路或学习。先回应意思，每轮最多一个具体建议，不变成说教。','book'),
            ('sandbox','随心聊聊','保持人设，顺着用户当下的话题探索有趣的小细节，不强制恋爱或任务。','sparkles')]:
            if english:title={'relationship':'Get to know me','task':'Practice together','sandbox':'Just talk'}[kind]
            routes.append(dict(id=short+'-'+kind,title=title,subtitle=e['hook'],category=kind,symbol=symbol,premise=premise))
        scenarios['characters'][role]=dict(profile={},scenarios=routes)
        variants=[]
        for i,text in enumerate(e['openings']):
            thoughts=(['I feel curious about this new meeting.','I feel comfortable right now.','I feel a little excited.'] if english else
                      ['新朋友让我有一点期待。','我觉得这会儿安静得很舒服。','我有一点小小的兴奋。'])
            variants.append(dict(text=text,speech=dict(emotion='happy' if i==0 else 'neutral',delivery='gentle',intensity=.42),
                asides=[dict(text=thoughts[i],stage='before'),dict(text='I feel happy to share this little corner.' if english else '这样的相遇，让我有一点开心。',stage='after')]))
        assert len(variants)==3 and len({v['text'] for v in variants})==3
        openings['characters'][role]=variants
        openings.setdefault('initialReplies',{})[role]=e['openingReplies']
    openings['characters']={r:openings['characters'][r] for r in roster}
    openings['revision']=expansion['revision']
    values={'services/character_ai/character_profiles.json':profiles,
            'services/character_ai/character_scenarios.json':scenarios,'authoring/openings.json':openings}
    for file,data in values.items():
        text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
        if check:assert (root/file).read_text()==text,file+' is stale'
        else:(root/file).write_text(text)
    print('Authored companion expansion:',len(roster),'active roles;',len(expansion['characters']),'new personas; paid calls: 0')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true')
    compile_data(check=p.parse_args().check)
