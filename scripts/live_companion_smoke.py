#!/usr/bin/env python3
"""Explicit bounded paid validation of installed companion voices and controls.

Use the authoritative worker configuration. Each role gets one synthetic draft,
then a PCM cache replay without another paid call. No real account history is
modified, no event/suggestion pools are warmed, and no images/voices are created.
"""
import argparse
import asyncio
from contextlib import aclosing
import json
from pathlib import Path
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def verify(role):
    from services.character_ai.config import Settings
    from services.character_ai.storage import Store
    from services.character_ai.provider import Provider
    from services.character_ai.orchestrator import Orchestrator
    from services.character_ai.profiles import assets
    from services.character_ai.roleplay import language
    from services.character_ai.schemas import Request
    from services.character_ai import voice_trace as vt
    settings=Settings.load()
    assert settings.paid_enabled,'Paid provider is disabled'
    store=Store(settings.data_dir/'state.sqlite3')
    provider=Provider(settings,store);engine=Orchestrator(settings,store,provider)
    owner='companion_verification_'+uuid.uuid4().hex
    output=ROOT/'.local/checks/sixteen-companions';output.mkdir(parents=True,exist_ok=True)
    calls=[]
    async def bounded(request):
        if len(calls)>=4:raise RuntimeError('Verification HTTP call budget exhausted')
        payload=json.loads(request.content);calls.append(payload.get('model',''))
    provider.http.event_hooks['request']=[bounded]
    english=language(role)=='en'
    body=Request(request_id=uuid.uuid4(),character_id=role,
        text='Tell me one small discovery from your day, in one short sentence.' if english else '今天心情很好，可以分享一个你今天的小发现吗？简短说一句就好。',
        timeline_reply=True,parallel_performance=True,wants_audio=True,
        available_assets=[a['asset_id'] for a in assets(role)])
    body._goal_snapshot=dict(schema_version=1,version=1,progress_version=0,romance_allowed=False,
        config=dict(mode='task' if english else 'sandbox',task='english' if english else '',
                    initial_relation='friends',long_term='understanding',short_term='',paused=False),branches={})
    trace=vt.Trace(store,owner,role,'verification:sixteen_companions')
    script=None;pcm_bytes=0;visuals=[]
    try:
        voice=store.get('voice','system',role)
        assert voice and voice.get('approved') and voice.get('voice_id'),'Approved reused voice missing'
        async with asyncio.timeout(75):
            context=engine.context(owner,body,persist=False)
            async with aclosing(vt.source(trace,engine.compose_reply(owner,body,context,budget=[1],draft=True))) as source:
                async for item in source:
                    if item['type']=='reply.narration.ready':script=item['script']
                    if item['type']=='reply.visuals.updated':script=item['script']
                    if item['type']=='segment.audio.chunk':
                        import base64
                        pcm_bytes+=len(base64.b64decode(item['data']))
                    if item['type'] in ('reply.error','audio.error'):raise RuntimeError(item['type'])
        assert script and script.get('text') and pcm_bytes>4800,'Missing reply or real speech'
        if english:assert not re.search(r'[\u3400-\u9fff]',script['text']),'English role spoke Chinese'
        else:assert re.search(r'[\u3400-\u9fff]',script['text']),'Chinese role did not speak Chinese'
        allowed=set(body.available_assets)
        visuals=[v for b in script['beats'] for v in b.get('visuals',[])]
        assert visuals and all(v['asset_id'] in allowed for v in visuals),'No supported model performance'
        before=len(calls);replay=vt.Trace(store,owner,role,'verification:cached_pcm_replay');replayed=0
        async with asyncio.timeout(15):
            async for item in vt.source(replay,engine.audio(owner,role,script,create=False)):
                if item['type']=='segment.audio.chunk':replayed+=1
                if item['type']=='audio.error':raise RuntimeError('Cached speech unavailable')
        assert len(calls)==before and replayed>0,'Replay made another paid call or missed PCM'
        first=trace.snapshot();cached=replay.snapshot()
        result=dict(character=role,passed=True,http_calls=len(calls),models=calls,
            pcm_bytes=pcm_bytes,visual_cues=len(visuals),groups=sorted({v['group'] for v in visuals}),
            text_ms=first['marks'].get('text_ready'),first_pcm_ms=first['marks'].get('first_audio_egress'),
            total_ms=first['total_ms'],cached_first_pcm_ms=cached['marks'].get('first_audio_egress'),
            cached_total_ms=cached['total_ms'])
        (output/(role+'.json')).write_text(json.dumps(dict(report=result,script=script),ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return result
    finally:
        await provider.close();store.db.close()

async def run(roles):
    # Foreground worker remains authoritative; keep operational checks small.
    for role in roles:await verify(role)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid',action='store_true');parser.add_argument('--characters',nargs='+',required=True)
    args=parser.parse_args()
    if not args.allow_paid:raise SystemExit('No provider calls made. Requires --allow-paid.')
    roster=json.loads((ROOT/'authoring/active-roster.json').read_text())['characters']
    if not 1<=len(args.characters)<=4 or len(set(args.characters))!=len(args.characters) or not set(args.characters)<=set(roster):
        raise SystemExit('Provide one to four distinct active characters per batch.')
    asyncio.run(run(args.characters))
