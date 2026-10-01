import asyncio
from contextlib import aclosing
import pytest
from services.character_ai.ordered_audio import ordered_audio

@pytest.mark.asyncio
async def test_later_tts_generates_while_first_tts_waits_but_playback_order_stays_intact():
    second=asyncio.Event();closed=[]
    async def source(index):
        try:
            if index==0:await second.wait()
            else:second.set()
            yield dict(type='segment.audio.started',beat=index)
            yield dict(type='segment.audio.chunk',beat=index)
            yield dict(type='segment.audio.ready',beat=index)
        finally:closed.append(index)
    result=[item async for item in ordered_audio([source(0),source(1)])]
    assert [item['beat'] for item in result]==[0,0,0,1,1,1]
    assert set(closed)=={0,1}

@pytest.mark.asyncio
async def test_backpressure_bounds_concurrency_and_disconnect_joins_every_tts_worker():
    running=set();closed=set();three=asyncio.Event();peak=0
    async def source(index):
        nonlocal peak
        running.add(index);peak=max(peak,len(running))
        if len(running)==3:three.set()
        try:
            for chunk in range(100):yield dict(type='segment.audio.chunk',beat=index,data=chunk)
        finally:running.remove(index);closed.add(index)
    async with aclosing(ordered_audio([source(i) for i in range(6)])) as stream:
        first=await anext(stream)
        await three.wait()
        assert first['beat']==0 and peak==3
    assert not running and closed=={0,1,2}

@pytest.mark.asyncio
async def test_audio_failure_cancels_later_synthesis_without_exposing_its_chunks():
    closed=set()
    async def source(index):
        try:
            if index==0:yield dict(type='audio.error')
            else:
                while True:yield dict(type='segment.audio.chunk',beat=index)
        finally:closed.add(index)
    events=[item async for item in ordered_audio([source(0),source(1)])]
    assert events==[dict(type='audio.error')] and closed=={0,1}
