import asyncio
import uuid
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.schemas import Beat, Plan, Request, TimelinePlan, ShakeTimelinePlan
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.reply_flow import compile_parts,safe_boundaries
from services.character_ai import novelty
from services.character_ai.provider import speech_input
from services.character_ai.provider import structured_messages

def test_asides_interleave_in_original_order_and_only_speech_reaches_tts():
    beat=Beat(beat_id='b',dialogue=dict(text='慢慢来，我想听后面的故事。你愿意继续吗？'),asides=[
        dict(text='我有点期待呢。',after_text='慢慢来，'),dict(text='我想再多陪你一会儿。',after_text='你愿意继续吗？'),
        dict(text='我根据设定选择温柔语气。',after_text='故事。')])
    resolved=dict(performances=[dict(active=True,offset_ms=0,asset=dict(group='expression',observable_effects=['轻轻微笑。'])),
                               dict(active=True,offset_ms=2400,asset=dict(group='ears',observable_effects=['耳朵轻轻晃动。']))])
    parts=compile_parts(beat,resolved)
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')==beat.dialogue.text
    thoughts=[p for p in parts if p['kind']=='thought']
    assert [p['text'] for p in thoughts]==['我有点期待呢。','我想再多陪你一会儿。']
    assert 0<thoughts[0]['at']<1 and thoughts[1]['at']==1
    assert all(a['at']<=b['at'] for a,b in zip(parts,parts[1:]))
    assert speech_input(dict(dialogue=beat.dialogue.model_dump(),parts=parts))[0]==beat.dialogue.text

def test_mistyped_anchor_uses_stage_and_hidden_thoughts_and_inactive_actions_never_show():
    beat=Beat(beat_id='b',dialogue=dict(text='好呀。'),asides=[dict(text='我想听下去。',after_text='不存在'),
             dict(text='我有点期待。',visibility='hidden')])
    parts=compile_parts(beat,dict(performances=[dict(active=False,offset_ms=0,asset=dict(observable_effects=['藏起耳朵。']))]))
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')=='好呀。'
    assert [p['text'] for p in parts if p['kind']=='thought']==['我想听下去。']
    assert not any(p['kind']=='narration' for p in parts)
    assert next(p['at'] for p in parts if p['kind']=='thought')>0

def test_anchor_before_comma_keeps_punctuation_with_speech():
    beat=Beat(beat_id='b',dialogue=dict(text='慢慢来，我在听。'),asides=[dict(text='我有点期待。',after_text='慢慢来')])
    parts=compile_parts(beat,dict(performances=[]))
    assert parts[0]['text']=='慢慢来，' and parts[1]['kind']=='thought' and parts[2]['text']=='我在听。'

@pytest.mark.parametrize('text,anchor',[
    ('我喜欢薰衣草的香气','薰'),
    ('我喜欢薰衣草的香气。你呢？','薰衣'),
    ('Lavender smells lovely today','Laven'),
    ('I love lavender, how about you?','lav'),
    ('嗯……我喜欢薰衣草～你呢？','嗯…'),
    ('emmmm……我还想再听听','emm'),
    ('他说“我喜欢薰衣草。”你呢？','薰'),
    ('It costs 3.14, or 3,000 for a set.','3.'),
    ('Meet Dr. Lee at 10:30. Shall we?','Dr.'),
    ('Visit https://example.com/a.b for more.','example.'),
])
def test_all_annotation_paths_preserve_words_and_pause_clusters(text,anchor):
    beat=Beat(beat_id='b',dialogue=dict(text=text),asides=[dict(text='我有点期待。',after_text=anchor),dict(text='我也想试试。',stage='middle')])
    parts=compile_parts(beat,dict(performances=[dict(active=True,offset_ms=1800,asset=dict(group='expression',observable_effects=['轻轻微笑。']))]))
    assert ''.join(p['text'] for p in parts if p['kind']=='dialogue')==text
    cursor=0
    for part in parts:
        if part['kind']=='dialogue':cursor+=len(part['text'])
        else:assert cursor in safe_boundaries(text)
    for word in ['薰衣草','lavender','Lavender','……','3.14','3,000','10:30','Dr.','https://example.com/a.b']:
        if word in text:assert any(word in p['text'] for p in parts if p['kind']=='dialogue')

def test_unpunctuated_clause_is_never_cut_even_at_spaces_or_a_bad_anchor():
    for text in ['我喜欢薰衣草','I really like lavender']:
        beat=Beat(beat_id='b',dialogue=dict(text=text),asides=[dict(text='我很开心。',stage='middle')])
        parts=compile_parts(beat,dict(performances=[]))
        assert parts[0]['text']==text and parts[1]['at']==1

def test_emotional_token_is_an_allowed_whole_pause_and_ellipsis_stays_whole():
    text='我想emmmm……再说一会儿。'
    points=safe_boundaries(text)
    assert text.index('emmmm') in points and text.index('再') in points
    assert all(p not in points for p in range(text.index('emmmm')+1,text.index('再')))

def test_timeline_requires_stage_data_and_shake_validates_only_its_real_task():
    with pytest.raises(ValueError):TimelinePlan.model_validate(dict(beats=[dict(beat_id='b',dialogue=dict(text='你好'))]))
    plan=ShakeTimelinePlan.model_validate(dict(response_focus='邀请对方答题',beats=[dict(beat_id='b',dialogue=dict(text='这一回换我出一道小小的题目。',speech=dict(emotion='soft')),
        asides=[dict(text='我也想赢一回呢。',stage='after')]),dict(beat_id='extra',dialogue=dict(text='多余的话题',speech=dict(emotion='unsupported')))]))
    assert len(plan.beats)==1 and plan.beats[0].dialogue.speech.emotion=='neutral'
    parts=compile_parts(plan.beats[0],dict(performances=[]))
    assert parts[-1]['kind']=='thought' and parts[-1]['at']==1

def test_upgrade_indexes_existing_history_and_publication_race_is_closed(tmp_path):
    path=tmp_path/'db';store=Store(path);old='你能回来我真的很开心，我们接着慢慢聊吧。'
    store.message('old','u','a','r','assistant',dict(text=old))
    # Reconstruct a pre-upgrade DB, then ensure migration protects old replies.
    with store.db:
        store.db.execute("DELETE FROM records WHERE kind='migration'")
        store.db.execute('DELETE FROM reply_novelty');store.db.execute('DELETE FROM reply_novelty_search')
    store.db.close();store=Store(path)
    assert novelty.match(store,'u',old)
    with pytest.raises(ValueError,match='REPLY_REPEATED'):
        store.publish_reply('u','b','r','你好',dict(message_id='new',text=old))
    assert not store.history('u','b'), 'Failed publication must roll back the user and assistant rows together'

def test_rewrite_keeps_real_roles_and_current_turn_without_duplicating_the_answer_corpus():
    context=dict(trigger='user_message',user_message='今天想聊画画',character_profile={'name':'test'},
        recent_messages=[dict(role='user',text='我喜欢画画'),dict(role='assistant',text='历史套话样本')],
        avatar_capability={'groups':['expression','author.new']},novelty_context={'instruction':'内容要新','previous_lines_to_avoid':['历史套话样本']},
        novelty_correction={'rejected_text':'重复候选','instruction':'换一个实质切入点'})
    messages=structured_messages('plan','system',context,TimelinePlan)
    assert [m['role'] for m in messages]==['system','user','assistant','user']
    assert messages[1]['content']=='我喜欢画画' and 'author.new' in messages[0]['content']
    assert messages[2]['content']=='历史套话样本' and messages[-1]['content']=='今天想聊画画'
    assert sum(m['content'].count('历史套话样本') for m in messages)==1
    assert '重复候选' in messages[0]['content'] and all('重复候选' not in m['content'] for m in messages[1:])

class Provider:
    def __init__(self,answers):self.answers=iter(answers);self.calls=[]
    async def structured(self,owner,char,purpose,system,context,schema):
        self.calls.append((purpose,context))
        assert purpose=='plan','timeline-v2 must never request late narration'
        return Plan(beats=[Beat(beat_id='b',dialogue=dict(text=next(self.answers)),asides=[dict(text='我也想听你说。',after_text='')])])
    async def synthesize(self,*args):
        self.calls.append(('tts',{}));yield b'\x00\x01'*100

@pytest.mark.asyncio
async def test_new_flow_is_complete_before_audio_and_has_no_second_narrator(tmp_path):
    store=Store(tmp_path/'test.db');provider=Provider(['慢慢来，我在听。'])
    engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    char='anime-kipfel';store.put('voice','system',char,dict(approved=True,voice_id='test'))
    req=Request(request_id=uuid.uuid4(),character_id=char,text='你好',timeline_reply=True)
    events=[e async for e in engine.reply('u',req)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert script['beats'][0]['parts'] and script['beats'][0]['reading_duration']>0
    types=[e['type'] for e in events]
    assert types.index('reply.narration.ready')<types.index('segment.audio.started')
    assert 'reply.script.updated' not in types
    assert [c[0] for c in provider.calls]==['plan','tts']
    req.timeline_reply=False;req.progressive_reply=True
    replay=[e async for e in engine.reply('u',req)]
    assert replay[0]['cached'] and replay[0]['script']==script
    assert [c[0] for c in provider.calls]==['plan','tts']

@pytest.mark.parametrize('a,b',[
    ('当然啦，我也很喜欢陪你一起慢慢聊今天的事情。','当然啦！我也很喜欢陪你一起慢慢聊今天的事情～'),
    ('你画的小花很漂亮，花瓣上的颜色也很温柔。','你画的这朵小花很漂亮，花瓣的颜色也很温柔！'),
    ('哎呀，你把我晃得头都晕啦，轻一点好不好嘛？','哎呀，你把我晃得脑袋都晕啦，稍微轻点好不好嘛？'),
    ('今天我们聊聊你新画的作品，一定很有意思吧。','回来啦！今天我们聊聊你新画的作品，一定很有意思吧。再给我讲讲。'),
])
def test_near_copy_including_shake_and_rewrapped_old_answer(a,b):assert novelty.similar(a,b)

def test_same_subject_with_new_content_is_allowed():
    assert not novelty.similar('你画的小花很漂亮，花瓣上的颜色也很温柔。','画画时你通常先勾轮廓，还是先挑颜色？我想听听你的习惯。')

@pytest.mark.asyncio
@pytest.mark.parametrize('trigger',['user_message','appLaunch','firstLaunch','firstMeeting','characterSwitch','story','model_shaken','model_pinched','idle'])
async def test_every_new_trigger_rewrites_duplicate_before_publication(tmp_path,trigger):
    store=Store(tmp_path/'test.db');char='anime-kipfel';old='刚才晃得我有点迷糊啦，轻一点好不好嘛？';new='哼，轮到我出题了，你能说出我的一个优点吗？'
    store.message('prior','u',char,'old','assistant',dict(text=old))
    if trigger=='idle':store.message('user','u',char,'old','user',dict(text='你好'))
    provider=Provider([old,new]);engine=Orchestrator(Settings(data_dir=tmp_path,paid_enabled=False),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id=char,text='再来',trigger=trigger,
        interaction=dict(kind='shake' if trigger=='model_shaken' else 'pinch_in',intensity=.7) if trigger in ('model_shaken','model_pinched') else None,timeline_reply=True,wants_audio=False)
    events=[e async for e in engine.reply('u',req)]
    script=next(e['script'] for e in events if e['type']=='reply.narration.ready')
    assert len(provider.calls)==2 and script['text']==new
    assert 'novelty_correction' in provider.calls[1][1]
    assert not any(e.get('script',{}).get('text')==old for e in events)

def test_persistent_exact_index_and_old_near_copy_retrieval_are_account_scoped(tmp_path):
    path=tmp_path/'test.db';store=Store(path)
    old='今天聊的花朵让我想起了一段很温柔的故事。'
    store.message('old','a','first','r','assistant',dict(text=old))
    for i in range(300):store.message(str(i),'a','second','r','assistant',dict(text=f'不同的测试记录编号为{i}，检查索引的候选召回范围。'))
    store.db.close();store=Store(path)
    assert novelty.match(store,'a',old)['reason']=='exact'
    assert novelty.match(store,'a','今天聊的小花让我想起一段很温柔的故事。')
    assert novelty.match(store,'b',old) is None
    with store.db:store.clear_novelty('a','first')
    assert novelty.match(store,'a',old) is None

@pytest.mark.asyncio
async def test_failed_rewrite_is_never_stored_or_spoken(tmp_path):
    store=Store(tmp_path/'test.db');old='你能回来我真的很开心，我们接着慢慢聊吧。'
    store.message('old','u','anime-mamehinata','r','assistant',dict(text=old))
    provider=Provider([old,old,old]);engine=Orchestrator(Settings(data_dir=tmp_path),store,provider)
    req=Request(request_id=uuid.uuid4(),character_id='anime-kipfel',text='你好',timeline_reply=True)
    with pytest.raises(ValueError,match='REPLY_UNAVAILABLE'):
        _=[e async for e in engine.reply('u',req)]
    assert len(provider.calls)==3 and not store.history('u','anime-kipfel')
    assert store.db.execute('SELECT status FROM requests').fetchone()[0]=='interrupted'
