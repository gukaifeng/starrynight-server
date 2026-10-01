#!/usr/bin/env python3
"""Explicit opt-in paid smoke: two short turns and <=6 seconds of ASR.

Does not create voices, retry model calls itself, or print tokens/credentials.
Ordinary pytest and UI tests never run this script.
"""
import os, argparse, asyncio, json, uuid, wave
from pathlib import Path
import httpx, websockets

ROOT=Path(__file__).resolve().parents[1]
async def run():
    config=json.loads(Path(os.environ.get('STARRY_AI_CONFIG', ROOT/'.local/character-ai/settings.json')).read_text())
    headers={'Authorization':'Bearer '+config['client_token'],'X-Starry-Installation':str(uuid.uuid4()),'X-Starry-Account':'live-smoke'}
    admin={'Authorization':'Bearer '+config['admin_token']}
    # Only local, installed assets can be presented as capabilities.
    from services.character_ai.profiles import assets
    report={'turns':[]}
    roles=[] if ARGS.asr_only else [(role,'你好，今天想和你轻松聊聊。简单打个招呼，一句就好。') for role in (ARGS.characters or ['anime-kipfel','anime-mamehinata'])]
    async with httpx.AsyncClient(timeout=120) as client:
        for char,text in roles:
            rid=str(uuid.uuid4());body=dict(request_id=rid,character_id=char,text=text,available_assets=[a['asset_id'] for a in assets(char)],wants_audio=True)
            packets=[];audio=0;script=None
            async with client.stream('POST',os.environ.get('STARRY_AI_BASE_URL','http://127.0.0.1:18766')+'/v1/conversations/'+char+'/messages',headers=headers,json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    e=json.loads(line[6:]);packets.append(e['type'])
                    if e['type']=='reply.narration.ready':script=e['script']
                    if e['type']=='segment.audio.chunk':audio+=1
                    if e['type'] in ('reply.error','audio.error'):print('FAIL',char,e.get('code') or e.get('message'),flush=True)
            result=dict(character=char,script_ready=bool(script),audio_chunks=audio,completed='reply.completed' in packets,events=packets)
            report['turns'].append(result)
            print({k:v for k,v in result.items() if k!='events'},flush=True)
            assert script and audio and 'reply.error' not in packets and 'audio.error' not in packets
            # Store private content for diagnosis; no credentials and no public fixture.
            (Path(config['data_dir'])/('smoke-'+char+'.json')).write_text(json.dumps(script,ensure_ascii=False,indent=2))
        if not ARGS.skip_asr:
          async with websockets.connect(os.environ.get('STARRY_AI_BASE_URL','http://127.0.0.1:18766').replace('http','ws',1)+'/v1/asr/anime-kipfel',additional_headers=headers) as socket:
            initial=json.loads(await socket.recv());assert initial['type']=='asr.ready',initial['type']
            fixture=ARGS.asr_fixture
            with wave.open(str(fixture)) as wav:
                assert wav.getframerate()==16000 and wav.getnchannels()==1 and wav.getsampwidth()==2
                pcm=wav.readframes(min(wav.getnframes(),16000*6))
            for offset in range(0,len(pcm),3200):
                await socket.send(pcm[offset:offset+3200]);await asyncio.sleep(.03)
            await socket.send(json.dumps(dict(type='finish')))
            partials=0;final=''
            async with asyncio.timeout(35):
                while True:
                    e=json.loads(await socket.recv())
                    if e['type']=='asr.partial':partials+=1
                    if e['type']=='asr.error':raise RuntimeError('ASR_FAILED')
                    if e['type']=='asr.completed':final=e['text'];break
            assert final
            report['asr']=dict(seconds=len(pcm)/32000,partial_count=partials,final_characters=len(final))
            print('ASR',report['asr'],flush=True)
        report['usage']=(await client.get(os.environ.get('STARRY_AI_BASE_URL','http://127.0.0.1:18766')+'/v1/admin/usage',headers=admin)).json()
    (Path(config['data_dir'])/'live-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS; private evidence and usage saved.',flush=True)

if __name__=='__main__':
    import sys;sys.path.insert(0,str(ROOT))
    from services.character_ai.profiles import PROFILES
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid',action='store_true');parser.add_argument('--asr-only',action='store_true')
    parser.add_argument('--characters',nargs='+',choices=sorted(PROFILES));parser.add_argument('--skip-asr',action='store_true');parser.add_argument('--asr-fixture',type=Path);args=parser.parse_args();ARGS=args
    if not args.allow_paid:raise SystemExit('No calls made. Real smoke requires --allow-paid.')
    if args.characters and len(args.characters)>3:raise SystemExit('Use at most three paid smoke conversations in one batch.')
    if not args.skip_asr and (args.asr_fixture is None or not args.asr_fixture.is_file()):raise SystemExit('Provide --asr-fixture WAV or --skip-asr before making paid calls.')
    asyncio.run(run())
