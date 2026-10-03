import json,uuid
from pathlib import Path
import pytest
from services.character_ai import emotion_standard as standard
from services.character_ai.schemas import Beat,Speech,Request
from services.character_ai.provider import speech_input,streaming_payload
from services.character_ai.stream_wire import beat as stream_beat
from services.character_ai.reply_flow import compile_parts
from services.character_ai.storage import Store
from services.character_ai.config import Settings
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.openings import OpeningRegistration,register

OFFICIAL={'sad','amazed','deep and loud shouting','trembling','angry','excited','sarcastic','curious','like dracula','bored','tired','scornful','shouting','asmr','panicked','mischievously','empathetic','whispers','reluctantly','crying','serious','very slowly','very fast'}

def test_official_control_and_vocal_inventory_has_three_different_variants_each():
    controls={e['providerTag'] for e in standard.CATALOG['entries'] if e['kind']!='vocal' and e['providerTag']}
    assert controls==OFFICIAL
    assert len(standard.ENTRIES)==42
    assert len({v['id'] for e in standard.CATALOG['entries'] for v in e['variants']})==126
    for e in standard.CATALOG['entries']:assert len({v['base'] for v in e['variants']})==3
    for emotion in standard.EMOTIONS:assert Speech(emotion=emotion).emotion==emotion

@pytest.mark.parametrize('kind,key',list(standard.ENTRIES))
def test_every_official_tag_survives_provider_adapter_but_thoughts_never_do(kind,key):
    entry=standard.ENTRIES[kind,key]
    b=dict(dialogue=dict(text='A gentle moment.',speech={kind:key} if kind!='vocal' else {}),parts=[dict(kind='thought',text='I feel calm.',at=0)])
    if kind=='vocal':b['vocal_events']=[dict(event=key)]
    text,instruction=speech_input(b)
    if entry['providerTag']:assert '['+entry['providerTag']+']' in text
    assert 'I feel calm' not in text
    assert 'A gentle moment.' in text

@pytest.mark.parametrize('text,thoughts',[
    ('嗯……我也想去。那就选个安静的地方吧？',['我有一点期待。','我想慢慢商量。']),
    ('Hmm… I would love that. Shall we find a quiet place?',["I'm looking forward to it.",'I want to take our time.']),
    ('Meet Dr. Lee at 3.14. Shall we?',['I feel curious.','I want to listen.'])])
def test_every_sentence_has_a_thought_and_different_emotion_without_split_words(text,thoughts):
    language='en' if text.startswith(('Hmm','Meet')) else 'zh'
    b=Beat(beat_id='b',dialogue={'text':text,'speech':{'emotion':'happy'}},asides=[dict(text=t,stage='before') for t in thoughts])
    values,last=standard.normalize(b,'happy',language)
    assert len(values)==2 and values[0].dialogue.speech.emotion!='happy'
    assert all(a.dialogue.speech.emotion!=b.dialogue.speech.emotion for a,b in zip(values,values[1:]))
    assert ''.join(b.dialogue.text.replace(' ','') for b in values)==text.replace(' ','')
    for b in values:assert any(p['kind']=='thought' for p in compile_parts(b,{'performances':[]},language))
    assert last==values[-1].dialogue.speech.emotion

@pytest.mark.parametrize('asides', [[],[dict(text='需要轻唤昵称',stage='before')],[dict(text='I feel happy.',visibility='hidden')]])
def test_missing_or_planning_or_hidden_only_thought_is_rejected_before_tts(asides):
    b=Beat(beat_id='b',dialogue={'text':'你好。'},asides=asides)
    with pytest.raises(ValueError,match='SENTENCE_THOUGHT_MISSING'):standard.normalize(b,'','zh')

def test_streaming_parses_voice_style_and_positioned_vocal_without_optional_avatar_schema():
    b=stream_beat(dict(say='Hmm… I am here.',mood='empathetic',style='whisper',asides=[['I want to listen.','before']],vocals=[dict(event='sigh',at=0)]),1)
    assert b.dialogue.speech.style=='whisper' and b.vocal_events[0].at==0
    text,_=speech_input(dict(dialogue=b.dialogue.model_dump(),vocal_events=[v.model_dump() for v in b.vocal_events]))
    assert text.startswith('[empathetic][whispers][sighing]')

def test_new_contract_is_additive_and_prepared_consume_keeps_provider_control_diagnostics(tmp_path):
    req=Request(request_id=uuid.uuid4(),character_id='anime-hikarun',emotion_contract=1,previous_emotion='shy')
    store=Store(tmp_path/'state.db');engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,None)
    context=engine.context('a',req,persist=False)
    assert context['emotion_context']['last']=='shy'
    payload,_=streaming_payload(engine.settings,context)
    assert standard.POLICY in payload['messages'][0]['content']
    script=dict(message_id='b',beats=[dict(dialogue=dict(text='你好。',speech={'emotion':'happy'}))])
    consumed=standard.review(script,'happy')
    assert consumed['beats'][0]['dialogue']['speech']==dict(emotion='playful',voice_emotion='happy')
    assert script['beats'][0]['dialogue']['speech']['emotion']=='happy'
    standard.commit(store,'a',req.character_id,consumed)
    assert engine.context('a',req,persist=False)['emotion_context']['last']=='playful'
    assert standard.context(store,'other',req.character_id,req)['last']=='shy'


def test_all_48_fixed_openings_have_a_first_emotion_and_thought_for_every_sentence():
    catalog=json.loads(Path('services/character_ai/opening_catalog.json').read_text())
    active={'anime-'+n for n in ('chiffon','fiona','hikarun','ichigo','koharu','lime','mafuyu','meiyun','milfy','mao','mizuki','perula','plum','ramune','shinano','sio')}
    count=0
    for package in catalog['characters']:
        if package['characterID'] not in active:continue
        for opening in package['variants']:
            count+=1;cues=opening['sentences']
            assert len(cues)==len(standard.sentence_ranges(opening['text']))
            assert all(c['emotion'] in standard.EMOTIONS and c['thought'] for c in cues)
            assert all(a['emotion']!=b['emotion'] for a,b in zip(cues,cues[1:]))
            assert sum(p['kind']=='thought' for p in opening['parts'])==len(cues)
    assert count==48

class OfflineVoice:
    def __init__(self):self.calls=[]
    async def stream_beats(self,owner,char,context):
        from services.character_ai.roleplay import language
        self.calls.append('plan')
        en=language(char)=='en'
        yield dict(say='Shall we compare one small discovery today?' if en else '今天想和你聊聊不同的发现，你最在意哪一种呢？',mood='happy',style='whisper',
            asides=[['I want to understand your perspective.' if en else '我想听听你的独特想法。','before']],vocals=['giggle'])
        yield dict(say='A tiny detail can lead us somewhere interesting.' if en else '一个不起眼的细节，也许会带来很有趣的方向。',mood='happy',
            asides=[['I feel curious about the next step.' if en else '我期待顺着新线索聊下去。','after']])
    async def synthesize(self,owner,char,beat,voice):
        self.calls.append('tts');yield b'\0\1'*2400

@pytest.mark.asyncio
@pytest.mark.parametrize('trigger',['user_message','appLaunch','firstLaunch','firstMeeting','characterSwitch','idle','story','model_shaken','model_pinched'])
async def test_live_and_automatic_scenes_publish_complete_sentence_controls_before_audio(tmp_path,trigger):
    provider=OfflineVoice();store=Store(tmp_path/'state.db');settings=Settings(data_dir=tmp_path,paid_enabled=False)
    engine=Orchestrator(settings,store,provider);char='anime-hikarun'
    if trigger=='idle':store.message('old-user','offline',char,'old','user',dict(text='聊聊新发现。'))
    # Interaction replies have stricter gesture semantics; use neither size nor rotation.
    store.put('voice','system',char,dict(approved=True,voice_id='offline'))
    req=Request(request_id=uuid.uuid4(),character_id=char,text='一起说说新发现。' if trigger=='user_message' else '',trigger=trigger,
        emotion_contract=1,timeline_reply=True,parallel_performance=True,
        interaction={'kind':'shake' if trigger=='model_shaken' else 'pinch_in','intensity':.8} if trigger in ('model_shaken','model_pinched') else None)
    events=[e async for e in engine.reply('offline',req)]
    scripts=[e['script'] for e in events if e.get('script')]
    assert scripts
    final=scripts[-1];assert len(final['beats'])==2
    assert final['beats'][0]['dialogue']['speech']['emotion']!=final['beats'][1]['dialogue']['speech']['emotion']
    for b in final['beats']:assert any(p['kind']=='thought' for p in b['parts'])
    types=[e['type'] for e in events];assert types.index('reply.narration.ready')<types.index('segment.audio.started')
    previous_calls=list(provider.calls)
    replay=[e async for e in engine.reply('offline',req)]
    assert provider.calls==previous_calls,'Replay uses retained PCM and controls, never provider calls'

def test_latest_published_partial_controls_are_scoped_and_override_stale_committed_state(tmp_path):
    store=Store(tmp_path/'state.db');req=Request(request_id=uuid.uuid4(),character_id='anime-hikarun',emotion_contract=1)
    store.put('sentence_emotion.v1','a',req.character_id,'neutral')
    store.message('partial','a',req.character_id,'r','assistant',dict(text='你好。',beats=[dict(dialogue=dict(text='你好。',speech={'emotion':'shy'}))]))
    assert standard.context(store,'a',req.character_id,req)['last']=='shy'
    assert standard.context(store,'b',req.character_id,req)['last']==''
    assert standard.context(store,'a','anime-sio',req)['last']==''
    store.db.close()

def test_malformed_optional_vocals_do_not_break_valid_sentence():
    for invalid in (None,1,'cough',{'event':'cough'}):
        assert not stream_beat(dict(say='你好。',vocals=invalid),1).vocal_events

@pytest.mark.asyncio
async def test_rejected_duplicate_does_not_change_actual_sentence_emotion(tmp_path):
    from services.character_ai.tests.test_reaction_pool import setup
    store,provider,engine,pool,request=setup(tmp_path)
    old='我们一起给星星取个名字吧。'
    store.message('old','u',request.character_id,'old','assistant',dict(text=old,beats=[dict(dialogue=dict(text=old,speech={'emotion':'happy'}))]))
    async def source(*args):
        yield dict(say=old,mood='happy',asides=[['我想听你的想法。','before']])
        yield dict(say='如果把星星的颜色记成旋律，你会从哪个音开始呢？',mood='happy',asides=[['我好奇你的新旋律。','before']])
    provider.stream_beats=source
    request=request.model_copy(update=dict(trigger='user_message',text='聊聊新的想法',emotion_contract=1,timeline_reply=True,parallel_performance=True))
    events=[e async for e in engine.reply('u',request)]
    final=[e['script'] for e in events if e.get('script')][-1]
    assert len(final['beats'])==1 and final['beats'][0]['dialogue']['speech']['emotion']=='playful'
    assert provider.calls.count('tts')==1
    await pool.close();store.db.close()

@pytest.mark.asyncio
async def test_prepared_inflight_updates_keep_consumed_emotions_and_mandatory_thoughts(tmp_path):
    import asyncio
    from services.character_ai.tests.test_reaction_pool import setup
    from services.character_ai.tests.test_prepared_handoff import entry_request,until
    store,provider,engine,pool,request=setup(tmp_path)
    gate=asyncio.Event()
    async def source(*args):
        yield dict(say='我在想把雨声做成一段新的旋律，你愿意一起听吗？',mood='happy',asides=[['我想让你听听我的新灵感。','before']])
        await gate.wait()
        yield dict(say='一滴雨可以像一个琴键，也许还能拼出有趣的和弦。',mood='happy',asides=[['我期待和你试试新的节拍。','after']])
    provider.stream_beats=source
    entry=entry_request(request).model_copy(update=dict(emotion_contract=1,timeline_reply=True,parallel_performance=True))
    pool.prepare('u',entry)
    await until(lambda:pool.find_job('u',request.character_id,pool.context_key('u',entry),'app_launch') is not None)
    job=pool.find_job('u',request.character_id,pool.context_key('u',entry),'app_launch')
    await until(lambda:any(e['type']=='reply.narration.ready' for e in job.events))
    # An intervening committed turn changes the consume-time neighbour. The
    # unspoken draft still retains its paid PCM and exact psychological aside.
    store.message('intervening','u',request.character_id,'previous','assistant',dict(text='此前的一句。',trigger='appLaunch',beats=[dict(dialogue=dict(text='此前的一句。',speech={'emotion':'happy'}))],parts=[dict(kind='thought',text='我想让你听听我的新灵感。',at=0)]))
    pool.active.clear()
    actual=entry.model_copy(update=dict(request_id=uuid.uuid4()))
    received=[];first=asyncio.Event()
    async def collect():
        async for e in engine.reply('u',actual):
            received.append(e)
            if e['type']=='reply.narration.ready':first.set()
    pending=asyncio.create_task(collect());await asyncio.wait_for(first.wait(),2)
    gate.set();await pending
    assert any(e.get('prepared') for e in received), 'Must actually adopt the existing paid draft'
    scripts=[e['script'] for e in received if e.get('script')]
    assert len(scripts)>=2 and scripts[0]['beats'][0]['dialogue']['speech']['emotion']=='playful'
    for script in scripts:
        assert script['beats'][0]['dialogue']['speech']['emotion']=='playful'
        assert all(any(p['kind']=='thought' for p in b['parts']) for b in script['beats'])
        assert all(a['dialogue']['speech']['emotion']!=b['dialogue']['speech']['emotion'] for a,b in zip(script['beats'],script['beats'][1:]))
    assert provider.calls.count('tts')==2
    assert store.get('sentence_emotion.v1','u',actual.character_id)==scripts[-1]['beats'][-1]['dialogue']['speech']['emotion']
    await pool.close();store.db.close()
