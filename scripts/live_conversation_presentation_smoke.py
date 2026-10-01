#!/usr/bin/env python3
"""Opt-in: exactly two text-only real turns, no TTS/ASR/voice design or retries.

Uses an isolated test identity. Private output stays under .local/checks.
Schema repair, if required by the provider, retains the normal one-repair limit.
"""
import os, argparse, asyncio, hashlib, hmac, json, sqlite3, time, uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

async def run(character=None):
    import sys
    sys.path.insert(0,str(ROOT))
    from services.character_ai.profiles import assets
    config=json.loads(Path(os.environ.get('STARRY_AI_CONFIG', ROOT/'.local/character-ai/settings.json')).read_text())
    install=str(uuid.uuid4());account='presentation-smoke'
    owner=hmac.new(config['client_token'].encode(),(install+'|'+account).encode(),hashlib.sha256).hexdigest()
    headers={'Authorization':'Bearer '+config['client_token'],'X-Starry-Installation':install,
             'X-Starry-Account':account,'X-Starry-Reply-Mode':'progressive-v1'}
    cases=[('anime-kipfel','我今天终于画好了一朵小花，有点想和你分享。',True),
           ('anime-mamehinata','用一小段旁白描写一下你的头发，再告诉我你在想什么吧。',False)]
    if character:cases=[case for case in cases if case[0]==character]
    report={'turns':[]};folder=ROOT/'.local/checks/conversation-presentation-live'/time.strftime('%Y%m%d-%H%M%S');folder.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=90) as client:
        for char,text,visuals in cases:
            started=time.monotonic();script=None;events=[];first=None
            body=dict(request_id=str(uuid.uuid4()),character_id=char,text=text,wants_audio=False,
                      available_assets=[a['asset_id'] for a in assets(char)] if visuals else [])
            async with client.stream('POST',os.environ.get('STARRY_AI_BASE_URL','http://127.0.0.1:18766')+'/v1/conversations/'+char+'/messages',headers=headers,json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    event=json.loads(line[6:]);events.append(event['type'])
                    if event.get('script'):
                        script=event['script']
                        if first is None:first=round(time.monotonic()-started,3)
            (folder/(char+'.json')).write_text(json.dumps(script,ensure_ascii=False,indent=2))
            beats=(script or {}).get('beats',[])
            result=dict(character=char,dialogue=any(b.get('dialogue') for b in beats),
                        thought=any(b.get('thought') for b in beats),narration=any(b.get('narrations') for b in beats),
                        first_text_seconds=first,total_seconds=round(time.monotonic()-started,3),
                        completed='reply.completed' in events,events=events)
            report['turns'].append(result);print({k:v for k,v in result.items() if k!='events'},flush=True)
    connection=sqlite3.connect(f"file:{Path(config['data_dir'])/'state.sqlite3'}?mode=ro",uri=True)
    report['usage']=[dict(kind=k,calls=n) for k,n in connection.execute('SELECT kind,count(*) FROM usage WHERE owner=? GROUP BY kind',(owner,))]
    connection.close();(folder/'report.json').write_text(json.dumps(report,indent=2))
    assert all(t['dialogue'] and t['thought'] and t['narration'] and t['completed'] for t in report['turns']), 'Missing reply component; inspect private report, no automatic retry'
    print('PASS: real structured replies; usage '+json.dumps(report['usage']),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid',action='store_true')
    parser.add_argument('--character',choices=['anime-kipfel','anime-mamehinata'])
    options=parser.parse_args()
    if not options.allow_paid:raise SystemExit('No calls made. Explicit --allow-paid required.')
    asyncio.run(run(options.character))
