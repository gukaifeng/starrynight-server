#!/usr/bin/env python3
"""Compile three first-visit packages per role. Paid synthesis is explicit/resumable.

--synthesize uses existing approved voices via the official Bailian CLI. It never
designs voices or generates dialogue. --check requires verified local PCM for
every current and retained legacy variant; metadata-only compilation cannot
pass that release check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESOURCE = ROOT / '.local/exports/openings'

def digest(value):
    return hashlib.sha256(value).hexdigest()

def compile_catalog():
    recipes = json.loads((ROOT / 'authoring/openings.json').read_text())
    roster = json.loads((ROOT / 'authoring/active-roster.json').read_text())['characters']
    performances = json.loads((ROOT / 'services/character_ai/performance_catalog.json').read_text())['characters']
    assert set(recipes['characters']) == set(roster)
    packages = []
    from services.character_ai.reply_flow import compile_text_parts,duration_hint
    from types import SimpleNamespace
    for role, entries in recipes['characters'].items():
        texts=[e if isinstance(e,str) else e['text'] for e in entries]
        assert len(texts) == len(set(texts)) == 3
        options = [o for o in performances[role] if o.get('enabled') and o.get('automatic') and o.get('speech_compatible')]
        faces = [o for o in options if o['intent'] in ('soft_smile', 'bright_smile', 'teasing_smile', 'shy') and not o['asset_id'].startswith('gesture-')]
        gestures = [o for o in options if o['asset_id'] in ('gesture-right-2', 'gesture-left-2', 'gesture-right-7')]
        if not gestures:
            gestures = [o for o in options if o['group'] in ('ears', 'tail') and o['intent'] not in ('angry', 'sad') and 'idle' not in o['asset_id']]
        assert faces or gestures, role
        variants = []
        for index, entry in enumerate(entries):
            text=entry if isinstance(entry,str) else entry['text']
            version=recipes.get('contentVersions',{}).get(role,recipes.get('contentVersion',1))
            key = role + (f'-v{version}' if version>1 else '') + '-' + str(index + 1)
            visual = []
            cues=((0,faces),(900,gestures),(6500,faces)) if faces else ((0,gestures),(6500,gestures))
            for offset, pool in cues:
                if not pool:
                    continue
                item = pool[(index + (offset > 1000)) % len(pool)]
                visual.append(dict(assetId=item['asset_id'], group=item['group'], durationMs=min(4000, item['duration_ms']),
                                   grounding=item['observable_effects'][0], offsetMs=offset))
            language='en' if role in ('anime-lime','anime-nozomi') else 'zh'
            variant=dict(id=key,text=text,audio='Opening_'+key.replace('-','_'),language=language,visuals=visual)
            if isinstance(entry,dict):
                asides=[SimpleNamespace(text=a['text'],stage=a.get('stage','middle'),visibility=a.get('visibility','visible'),after_text=a.get('after_text','')) for a in entry['asides']]
                cues=[dict(active=True,offset_ms=v['offsetMs'],asset=dict(group=v['group'],observable_effects=[v['grounding']])) for v in visual]
                variant.update(speech=entry.get('speech',dict(emotion='neutral',delivery='gentle',intensity=.4)),
                    parts=compile_text_parts(text,asides,cues,language),readingDuration=duration_hint(text))
            variants.append(variant)
        legacy=[]
        for edition in recipes.get('legacyVersions',[]):
            for index,text in enumerate(edition['characters'].get(role,[])):
                v=edition['version'];key=role+(f'-v{v}' if v>1 else '')+'-'+str(index+1)
                legacy.append(dict(id=key,text=text,audio='Opening_'+key.replace('-','_'),language=language,visuals=[],legacy=True))
        packages.append(dict(characterID=role, variants=variants,legacyVariants=legacy))
    return dict(schemaVersion=1, revision=recipes['revision'], characters=packages)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesize', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--limit', type=int, default=33, help='maximum NEW paid requests this run')
    args = parser.parse_args()
    RESOURCE.mkdir(parents=True, exist_ok=True)
    catalog = compile_catalog()
    receipts = ROOT / '.local/character-openings'
    receipts.mkdir(parents=True, exist_ok=True)
    settings = voices = None
    if args.synthesize:
        from services.character_ai.config import Settings
        settings = Settings.load()
        assert settings.api_key and settings.paid_enabled, 'Paid generation is disabled/unconfigured'
        # Read only: provisioning must not migrate or alter live service state.
        with sqlite3.connect(f'file:{settings.data_dir / "state.sqlite3"}?mode=ro', uri=True) as db:
            voices = {r[0]: json.loads(r[1]) for r in db.execute("SELECT character,data FROM records WHERE kind='voice' AND owner='system'")}
    calls = 0
    missing = []
    for character in catalog['characters']:
        role = character['characterID']
        for variant in character['variants']+character.get('legacyVariants',[]):
            target = RESOURCE / (variant['audio'] + '.pcm')
            receipt_path = receipts / (variant['id'] + '.json')
            text_hash = digest(variant['text'].encode())
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
            valid = target.exists() and receipt.get('textSHA256') == text_hash and receipt.get('sha256') == digest(target.read_bytes())
            if args.synthesize and not variant.get('legacy'):
                from services.character_ai.profiles import PROFILES
                from services.character_ai.provider import speech_input
                instruction = PROFILES[role].get('voice_delivery', '')
                spoken=variant['text']
                if variant.get('speech'):
                    spoken,delivery=speech_input(dict(dialogue=dict(text=spoken,speech=variant['speech'])))
                    instruction+='。'+delivery
                voice = voices.get(role, {})
                assert voice.get('approved') and voice.get('voice_id'), f'{role}: approved voice missing'
                voice_hash = digest(voice['voice_id'].encode())
                delivery_hash=digest((variant['language']+'|'+instruction).encode())
                valid = valid and receipt.get('voiceSHA256') == voice_hash and receipt.get('model') == settings.tts_model and receipt.get('deliverySHA256')==delivery_hash
                if not valid and calls < args.limit:
                    calls += 1
                    text_file = receipts / (variant['id'] + '.txt')
                    text_file.write_text(spoken)
                    temp = receipts / (variant['id'] + '.pcm')
                    env = dict(os.environ, DASHSCOPE_API_KEY=settings.api_key, DASHSCOPE_BASE_URL=settings.host)
                    command = ['bl', 'speech', 'synthesize', '--text-file', str(text_file), '--model', settings.tts_model,
                               '--voice', voice['voice_id'], '--format', 'pcm', '--sample-rate', '24000',
                               '--language', variant['language'], '--instruction', instruction, '--out', str(temp), '--timeout', '90']
                    # Provider output may include account metadata. Keep it private;
                    # report only exit code and role, never credentials or voice IDs.
                    result = subprocess.run(command, env=env, capture_output=True, timeout=110)
                    (receipts / (variant['id'] + '.log')).write_bytes(result.stdout + result.stderr)
                    if result.returncode or not temp.exists():
                        raise SystemExit(f'{role}/{variant["id"]}: synthesis failed (exit {result.returncode}); private log retained; stopped without retrying/extra spend')
                    data = temp.read_bytes()
                    assert len(data) % 2 == 0 and 48000 < len(data) < 48000*90, 'Invalid PCM length'
                    target.write_bytes(data)
                    receipt = dict(textSHA256=text_hash, voiceSHA256=voice_hash, deliverySHA256=delivery_hash, model=settings.tts_model, sha256=digest(data))
                    receipt_path.write_text(json.dumps(receipt) + '\n')
                    valid = True
            variant['audioReady'] = valid
            if valid:
                variant['duration'] = target.stat().st_size / 48000
                variant['audioSHA256'] = receipt['sha256']
            else:
                missing.append(variant['id'])
    compiled=json.dumps(catalog, ensure_ascii=False, indent=2) + '\n'
    for path in (RESOURCE / 'CharacterOpenings.json', ROOT / 'services/character_ai/opening_catalog.json'):
        if args.check:
            if not path.exists() or path.read_text()!=compiled:raise SystemExit('Opening catalog is stale: '+str(path))
        else:path.write_text(compiled)
    total=sum(len(c['variants'])+len(c.get('legacyVariants',[])) for c in catalog['characters'])
    print(f'Opening packages: {len(catalog["characters"])} roles / 33 current variants; verified audio including legacy: {total-len(missing)}/{total}; new paid calls: {calls}')
    if args.check and missing:
        raise SystemExit('Release check failed: missing verified opening audio: ' + ', '.join(missing))

if __name__ == '__main__':
    main()
