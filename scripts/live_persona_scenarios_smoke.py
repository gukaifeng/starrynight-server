#!/usr/bin/env python3
"""Bounded opt-in real-provider check. Never creates voices or warms event pools."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import subprocess
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def run():
    from services.character_ai.config import Settings
    from services.character_ai.storage import Store
    from services.character_ai.provider import Provider
    from services.character_ai.orchestrator import Orchestrator
    from services.character_ai.roleplay import language
    from services.character_ai.schemas import Request,CoreTimelinePlan,QuickReplyPlan
    from services.character_ai.quick_replies import SUGGESTIONS
    from services.character_ai.asr import recognize
    settings=Settings.load();store=Store(settings.data_dir/'state.sqlite3')
    provider=Provider(settings,store);engine=Orchestrator(settings,store,provider)
    owner='persona-smoke-'+uuid.uuid4().hex
    output=ROOT/'.local/checks/persona-scenarios';output.mkdir(parents=True,exist_ok=True)
    cases=[('anime-lime','firstMeeting','',''),('anime-nozomi','user_message','Can we practise giving opinions about films?',''),
        ('anime-mafuyu','story','我愿意一起试茶，不过我想知道，这算是一次约会吗？','mafuyu-tea-date'),
        ('anime-ichigo','story','我不想故意让着你，不过赢了能约你下次一起散步吗？','ichigo-sweet-rival')]
    report={'owner':owner,'turns':[]};contexts={};pcm_by_role={}
    if ARGS.resume_asr:
        report=json.loads((output/'live-report.json').read_text());owner=report['owner'];cases=[]
        pcm_by_role['anime-lime']=(output/'anime-lime.pcm').read_bytes()
    report['status']='RUNNING'
    started=time.time()
    try:
        for char,trigger,text,scene in cases:
            request=Request(request_id=uuid.uuid4(),character_id=char,trigger=trigger,text=text,
                scene={'story_id':scene} if scene else {},timeline_reply=True,parallel_performance=True,wants_audio=False)
            context=engine.context(owner,request,persist=False);contexts[char]=context
            before=time.monotonic();budget=[2]
            plan=await engine.fresh_plan(owner,request,context,CoreTimelinePlan,budget)
            assert plan and plan.beats
            spoken=' '.join(b.dialogue.text for b in plan.beats if b.dialogue)
            assert spoken
            if language(char)=='en':assert not re.search(r'[\u3400-\u9fff]',spoken)
            entry=dict(character=char,seconds=round(time.monotonic()-before,2),attempts=2-budget[0],text=spoken,plan=plan.model_dump())
            if language(char)=='en':
                voice=store.get('voice','system',char);assert voice and voice['approved']
                beat=next(b for b in plan.beats if b.dialogue).model_dump()
                pcm=b''.join([chunk async for chunk in provider.synthesize(owner,char,beat,voice['voice_id'])])
                assert len(pcm)>4800 and len(pcm)%2==0
                (output/(char+'.pcm')).write_bytes(pcm);pcm_by_role[char]=pcm
                entry['audio_seconds']=round(len(pcm)/48000,2)
            report['turns'].append(entry)
            print(json.dumps({k:v for k,v in entry.items() if k not in ('text','plan')},ensure_ascii=False),flush=True)
        if not ARGS.resume_asr:
            context=contexts['anime-lime']
            suggestions=await provider.structured(owner,'anime-lime','suggestions',SUGGESTIONS,
                dict(recent_messages=[{'role':'assistant','text':report['turns'][0]['text']}],
                    preferences={},character_name='Lime',language_contract=context['language_contract'],
                    roleplay_context=context['roleplay_context'],suggestion_length='Exactly three distinct English replies, 3–8 words each, at most 45 characters.'),QuickReplyPlan)
            assert len({o.text for o in suggestions.options})==3
            assert not re.search(r'[\u3400-\u9fff]',json.dumps(suggestions.model_dump(),ensure_ascii=False))
            report['suggestions']=suggestions.model_dump()
        # Feed a short real English TTS sample through the production ASR
        # bridge. This validates language selection, not microphone hardware.
        pcm=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar','24000','-ac','1','-i','pipe:0','-ar','16000','-f','s16le','pipe:1'],input=pcm_by_role['anime-lime'][:48000*8],capture_output=True,check=True).stdout
        class Socket:
            def __init__(self):self.offset=0;self.events=[]
            async def receive(self):
                if self.offset<len(pcm):
                    part=pcm[self.offset:self.offset+3200];self.offset+=len(part)
                    await asyncio.sleep(.02)
                    return {'type':'websocket.receive','bytes':part}
                return {'type':'websocket.receive','text':'{"type":"finish"}'}
            async def send_json(self,value):self.events.append(value)
        socket=Socket()
        async with asyncio.timeout(40):await recognize(socket,settings,store,owner,'anime-lime')
        final=next(e['text'] for e in socket.events if e['type']=='asr.completed')
        assert re.search(r'[a-zA-Z]',final) and not re.search(r'[\u3400-\u9fff]',final)
        report['asr']={'source':'8s-or-shorter synthesized English, not a physical microphone','text':final,'seconds':len(pcm)/32000}
        report['status']='PASS'
    finally:
        if report['status']!='PASS':report['status']='FAILED'
        rows=store.db.execute('SELECT kind,status,units FROM usage WHERE owner=? AND created>=?',(owner,started)).fetchall()
        report['usage']=report.get('usage',[])+[dict(row) for row in rows]
        (output/'live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        await provider.close();store.db.close()
    print('PASS: four real persona turns, two existing English voices, three suggestions and one ASR stream.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid',action='store_true');parser.add_argument('--resume-asr',action='store_true');args=parser.parse_args();ARGS=args
    if not args.allow_paid:raise SystemExit('No provider calls made. Requires --allow-paid.')
    asyncio.run(run())
