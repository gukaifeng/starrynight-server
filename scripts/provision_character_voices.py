#!/usr/bin/env python3
"""Explicit, bounded paid provisioning for an authored character batch.

At most three roles per invocation; provider job identities prevent retries after
ambiguous timeouts. Existing approved voices are retained. No API key is logged.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.provider import Provider
from services.character_ai.profiles import PROFILES


async def run(roles):
    settings=Settings.load();store=Store(settings.data_dir/'state.sqlite3')
    used=store.db.execute("SELECT coalesce(sum(reserved),0) FROM usage WHERE kind='voice_design'").fetchone()[0]
    missing=[r for r in roles if not store.get('voice','system',r)]
    # This operator invocation is limited to these new roles. It does not lift
    # normal conversation limits or silently enable repeated paid voice designs.
    settings.max_voice_designs=max(settings.max_voice_designs,int(used)+len(missing))
    provider=Provider(settings,store)
    try:
        for role in roles:
            voice=store.get('voice','system',role)
            if voice and voice.get('approved'):
                print('VOICE_RETAINED',role,flush=True);continue
            voice=await provider.design_voice(role,PROFILES[role])
            with wave.open(str(settings.data_dir/'voices'/voice['preview_file'])) as preview:
                seconds=preview.getnframes()/preview.getframerate()
                if not .2<seconds<60:raise ValueError('Voice preview duration invalid')
            store.approve_voice(role,voice.get('job_id'))
            print('VOICE_PREVIEW_READY',role,'seconds',round(seconds,2),flush=True)
    finally:await provider.close();store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--characters',nargs='+',required=True,choices=sorted(PROFILES));p.add_argument('--allow-paid',action='store_true');args=p.parse_args()
    if not args.allow_paid:raise SystemExit('No calls made. Pass --allow-paid for this explicit operator task.')
    roles=list(dict.fromkeys(args.characters))
    if not 1<=len(roles)<=3:raise SystemExit('Provision one batch of at most three roles.')
    asyncio.run(run(roles))
