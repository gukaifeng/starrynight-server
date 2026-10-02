#!/usr/bin/env python3
"""Export only reviewed semantic capability metadata from the installed roster.

Optional option.ai: intent, effects, moods, automatic, speechCompatible,
cooldownSeconds. Unknown groups need no Swift/Python/C# branch. Pose changes
and wardrobe switches require contextual intent; they are not random fillers.
"""
import argparse
import json
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.character_ai.profiles import reviewed_assets

MOODS={
 'soft_smile':['neutral','happy','worried'],'bright_smile':['happy','excited'],
 'teasing_smile':['playful','happy'],'playful':['playful','happy'],'playful_tongue':['playful'],
 'pout':['playful','serious'],'serious':['serious'],'worried':['worried','sad'],
 'sad':['sad'],'thinking':['curious','neutral'],'confused':['confused'],'surprised':['surprised'],
 'confident':['happy','excited'],'proud':['happy','playful'],'excited':['excited','happy'],
 'sleepy':['tired'],'thumbs_up':['happy','excited'],'peace':['happy','playful'],
 'open_hands':['neutral','happy','curious','worried','sad'],'fist':['excited','serious','playful'],
 'point':['curious','neutral','serious'],'rock':['playful','excited'],
 'ear_wiggle':['neutral','happy','curious','playful'],'ear_perk':['excited','surprised','curious'],
 'ear_lower':['sad','worried','serious'],'tail_wag':['happy','excited','playful'],
 'tail_sway':['neutral','curious','happy'],'tail_lower':['sad','worried','serious'],
}

def generate(catalog, root=ROOT, legacy_catalog=None):
    source=json.loads(catalog.read_text())
    result={}
    for character in source['characters']:
        profile=character.get('performance') or {}
        try:known={a['asset_id']:a for a in reviewed_assets(character['id'])}
        except ValueError:known={}
        groups={g['id']:g['label'] for g in profile.get('groups',[])}
        options=[]
        for option in profile.get('options',[]):
            id=option['id'];group=option['group'];label=option['label'];hint=option.get('ai') or {}
            if not hint.get('intent'):hint={}
            old=known.get(id,{})
            intent=hint.get('intent',old.get('intent','perform_'+id.replace('-','_')))
            if len(intent)>128:intent=intent[:115]+'_'+hashlib.sha256(intent.encode()).hexdigest()[:12]
            effect=old.get('observable_effects')
            if not effect:
                if group=='expression':effect=['露出'+label+'的神情']
                elif group=='hands':effect=['双手摆出'+label+'手势']
                elif group=='pose':effect=[{'坐姿':'身体变成坐姿','蹲姿':'身体变成蹲姿','自然站姿':'身体恢复站姿','安静睡眠':'身体进入睡眠姿态','躺下入睡':'身体缓缓躺下','睡醒起身':'身体从睡眠中起身','轻轻呼吸':'身体随呼吸轻轻起伏'}.get(label,'身体呈现'+label)]
                elif group=='ears':effect=['耳朵呈现'+label]
                elif group=='tail':effect=['尾巴呈现'+label]
                else:effect=[groups[group]+'呈现'+label]
            compatible=hint.get('speechCompatible','固定嘴型' not in label)
            moods=hint.get('moods',MOODS.get(intent,[]))
            if not moods and group=='expression':
                for words,values in [('不满 生气 龇牙 闹别扭',['serious']),('被摸头的开心 猫眼 猫咪',['playful','happy']),('惊讶 惊叹',['surprised']),('脸色发白 紧张',['worried']),('含泪 哭泣',['sad'])]:
                    if any(word in label for word in words.split()):moods=values;break
            if not moods and group=='ears':moods=['neutral','happy','curious','playful']
            if not moods and group=='tail':
                moods=['surprised','serious'] if '蓬起' in label else ['happy','playful','excited','curious']
            automatic=hint.get('automatic',group not in ('pose','appearance') and option['kind']!='toggle' and '自然' not in label and compatible and (bool(moods) or group not in ('expression','hands')))
            if not hint and label in ('收起耳朵','展开耳朵'):automatic=False
            duration=int(min(15000,max(3500,option.get('duration',0)*1000)))
            options.append(dict(asset_id=id,label=label,kind=hint.get('kind') or ('expression' if group=='expression' else 'action'),
                group=group,group_label=groups[group],intent=intent,observable_effects=hint.get('effects',effect),
                intensity_min=0,intensity_max=1,base_weight=old.get('base_weight',1),rarity='common',
                min_closeness=0,max_anger=1,cooldown_sec=hint.get('cooldownSeconds',3),duration_ms=duration,
                source_kind=option['kind'],loop=option.get('loop',False),automatic=automatic,
                speech_compatible=compatible,moods=moods,conflicts=hint.get('conflicts') or [],interruptible=True,return_to='baseline',enabled=True))
        result[character['id']]=options
    output=root/'services/character_ai/performance_catalog.json'
    previous=json.loads(legacy_catalog.read_text()) if legacy_catalog else (json.loads(output.read_text()) if output.exists() else {})
    legacy={**previous.get('legacyCharacters',{}),**previous.get('characters',{})}
    legacy={role:options for role,options in legacy.items() if role not in result}
    output.write_text(json.dumps(dict(version=1,characters=result,legacyCharacters=legacy),ensure_ascii=False,indent=2)+'\n')
    print('AI performance catalog:',', '.join(f'{c}: {len(a)} options / {len({o["group"] for o in a})} groups' for c,a in result.items()))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True, help='Explicit exported capability catalog; no client checkout needed')
    parser.add_argument('--legacy-catalog',type=Path,help='Explicit metadata-only previous catalogue for replay/backward compatibility')
    args=parser.parse_args()
    generate(args.catalog,legacy_catalog=args.legacy_catalog)
