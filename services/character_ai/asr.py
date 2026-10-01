import asyncio, json, uuid
import websockets
from .profiles import PROFILES
from .storage import dump
from .roleplay import language

class Transcript:
    def __init__(self):self.finals={}
    def receive(self,sentence):
        if sentence.get('heartbeat'):return None
        text=sentence.get('text',''); key=str(sentence.get('sentence_id',sentence.get('begin_time',len(self.finals))))
        if sentence.get('sentence_end'):
            self.finals[key]=text
            return dict(type='asr.final',text=''.join(self.finals.values()))
        return dict(type='asr.partial',text=''.join(self.finals.values())+text)

async def recognize(socket,settings,store,owner,character,nickname=''):
    from .diagnostics import record_request
    usage=None
    task=uuid.uuid4().hex; transcript=Transcript(); metrics={}; forwarded=0
    url=settings.host.replace('https://','wss://')+'/api-ws/v1/inference'
    words=PROFILES[character]['hotwords']+[nickname[:24]] if nickname else PROFILES[character]['hotwords']
    # Fun-ASR's documented context accepts domain hotwords without a separately
    # billed vocabulary-creation request. Never mix another role's vocabulary.
    context=[{'role':'user','content':[{'type':'input_text','text':'对话中可能出现的专有名词：'+'、'.join(words)}]}]
    try:
        async with websockets.connect(url,additional_headers={'Authorization':'Bearer '+settings.api_key},open_timeout=12,max_size=1024*1024) as upstream:
            usage=store.reserve('asr',owner,character,30,settings)
            payload={'header':{'action':'run-task','task_id':task,'streaming':'duplex'},
                'payload':{'task_group':'audio','task':'asr','function':'recognition','model':settings.asr_model,
                    'parameters':{'format':'pcm','sample_rate':16000,'language_hints':[language(character)],'max_sentence_silence':800},'input':{'context':context}}}
            record_request(settings,store,owner,character,'asr',payload)
            await upstream.send(dump(payload))
            first=json.loads(await asyncio.wait_for(upstream.recv(),15))
            metrics['start_event']=first.get('header',{}).get('event')
            metrics['provider_code']=first.get('header',{}).get('error_code')
            if first.get('header',{}).get('event')!='task-started':raise ValueError('ASR_START_FAILED')
            await socket.send_json({'type':'asr.ready'})
            async def upload():
                nonlocal forwarded
                while True:
                    message=await socket.receive()
                    if message['type']=='websocket.disconnect':raise asyncio.CancelledError()
                    if message.get('bytes') is not None:
                        chunk=message['bytes'];forwarded+=len(chunk)
                        if len(chunk)>65536 or forwarded>16000*2*30:raise ValueError('ASR_LIMIT')
                        await upstream.send(chunk)
                    elif message.get('text'):
                        control=json.loads(message['text'])
                        if control.get('type')=='finish':
                            await upstream.send(dump({'header':{'action':'finish-task','task_id':task,'streaming':'duplex'},'payload':{'input':{}}}));return
            sender=asyncio.create_task(upload())
            try:
                async with asyncio.timeout(45):
                    while True:
                        receiver=asyncio.create_task(upstream.recv())
                        watched={receiver,sender} if not sender.done() else {receiver}
                        done,_=await asyncio.wait(watched,return_when=asyncio.FIRST_COMPLETED)
                        if sender in done and (sender.cancelled() or sender.exception()):
                            receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
                            await sender
                        if receiver not in done: raw=await receiver
                        else:raw=receiver.result()
                        data=json.loads(raw); name=data.get('header',{}).get('event')
                        if name=='task-failed':raise ValueError('ASR_PROVIDER_FAILED')
                        payload=data.get('payload',{});metrics.update(payload.get('usage') or {})
                        if name=='result-generated':
                            out=transcript.receive(payload.get('output',{}).get('sentence',{}))
                            if out:await socket.send_json(out)
                        if name=='task-finished':break
                await socket.send_json({'type':'asr.completed','text':''.join(transcript.finals.values())})
                store.usage(usage,'completed',metrics,forwarded/32000)
            finally:
                sender.cancel();await asyncio.gather(sender,return_exceptions=True)
    except BaseException as error:
        metrics['error_type']=type(error).__name__
        if isinstance(error,ValueError):metrics['error_code']=str(error)[:80]
        if getattr(error,'response',None):metrics['http_status']=getattr(error.response,'status_code',None)
        if usage is not None:store.usage(usage,'interrupted_or_failed',metrics)
        raise
