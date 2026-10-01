#!/usr/bin/env python3
"""Three opt-in text-only samples; never warms pools, generates audio or voices."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def run():
    from services.character_ai.config import Settings
    from services.character_ai.storage import Store
    from services.character_ai.provider import Provider
    from services.character_ai.orchestrator import Orchestrator
    from services.character_ai.schemas import Request,CoreTimelinePlan
    from services.character_ai.idle_presence import BY_ID
    from services.character_ai.reaction_pool import event_task
    settings=Settings.load();store=Store(settings.data_dir/'state.sqlite3')
    provider=Provider(settings,store);engine=Orchestrator(settings,store,provider)
    owner='idle-address-smoke-'+uuid.uuid4().hex
    output=ROOT/'.local/checks/idle-address';output.mkdir(parents=True,exist_ok=True)
    cases=[
        ('anime-kipfel','小星','current_activity','今天想和你聊点日常。','小北，你喜欢安静的日常还是热闹一些？'),
        ('anime-mafuyu','Sky','topic_fit','想聊聊你经营旅舍的故事。','旅舍的名字我改了好几次，最后还是选了最朴素的那一个。'),
        ('anime-lime','River','busy_hands','I am busy working on something for a little while.','Take your time. We can continue with the greenhouse story later.'),
    ]
    if ARGS.character:cases=[c for c in cases if c[0]==ARGS.character]
    report={'owner':owner,'status':'RUNNING','turns':[]};started=time.time()
    try:
        for char,nickname,angle,user,assistant in cases:
            request=Request(request_id=uuid.uuid4(),character_id=char,trigger='idle',preferences={'nickname':nickname,'nicknameSource':'character'},
                            recent_messages=[dict(role='user',text=user),dict(role='assistant',text=assistant)],
                            timeline_reply=True,parallel_performance=True,wants_audio=False)
            context=engine.context(owner,request,persist=False)
            selected=BY_ID[angle]
            context['idle_context']['angle']=dict(id=selected[0],family=selected[1],intention=selected[3])
            context['prepared_event_context']=dict(kind='idle',task=event_task('idle'))
            before=time.monotonic();budget=[1]
            plan=await engine.fresh_plan(owner,request,context,CoreTimelinePlan,budget)
            assert plan and plan.beats
            text=' '.join(b.dialogue.text for b in plan.beats if b.dialogue)
            assert text and '小北' not in text
            if char=='anime-lime':assert not re.search(r'[\u3400-\u9fff]',text)
            report['turns'].append(dict(character=char,nickname=nickname,angle=angle,text=text,
                                        seconds=round(time.monotonic()-before,2),plan=plan.model_dump()))
            print(json.dumps({'character':char,'text':text,'seconds':report['turns'][-1]['seconds']},ensure_ascii=False),flush=True)
        report['status']='PASS'
    finally:
        if report['status']!='PASS':report['status']='FAILED'
        report['usage']=[dict(r) for r in store.db.execute('SELECT kind,status,units FROM usage WHERE owner=? AND created>=?',(owner,started))]
        (output/('live-report'+('-'+ARGS.character if ARGS.character else '')+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        await provider.close();store.db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid',action='store_true')
    parser.add_argument('--character',choices=['anime-kipfel','anime-mafuyu','anime-lime']);args=parser.parse_args();ARGS=args
    if not args.allow_paid:raise SystemExit('No calls made. Requires --allow-paid.')
    asyncio.run(run())
