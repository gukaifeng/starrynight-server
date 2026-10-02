#!/usr/bin/env python3
"""Reuse approved system voices for authored roles. Never calls a provider.

Existing approvals are kept. Prepare all missing records before writing, so a
missing donor cannot leave a half-configured batch. Run against the authoritative
worker configuration, not a second local server.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.character_ai.config import Settings
from services.character_ai.storage import Store, dump

def provision(store,expansion,apply=False):
    changes=[]
    for role,entry in expansion['characters'].items():
        existing=store.get('voice','system',role) or {}
        if existing.get('approved') and existing.get('voice_id'):continue
        donor=entry['voiceSource'];voice=store.get('voice','system',donor)
        if not voice or not voice.get('approved') or not voice.get('voice_id'):
            raise ValueError('Approved voice source missing: '+donor)
        value=copy.deepcopy(voice)
        value.update(reused_from=donor,reuse_revision=expansion['revision'])
        changes.append((role,value))
    if apply:
        with store.db:
            store.db.executemany("INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(kind,owner,character) DO UPDATE SET data=excluded.data,updated=excluded.updated WHERE COALESCE(json_extract(records.data,'$.approved'),0)=0 OR COALESCE(json_extract(records.data,'$.voice_id'),'')=''",
                [('voice','system',role,dump(value),time.time()) for role,value in changes])
    return [r for r,_ in changes]

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');args=p.parse_args()
    store=Store(Settings.load().data_dir/'state.sqlite3')
    try:
        roles=provision(store,json.loads((ROOT/'authoring/companion-expansion.json').read_text()),args.apply)
        print(json.dumps(dict(applied=args.apply,roles=roles,paid_calls=0)))
    finally:store.db.close()
