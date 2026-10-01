"""Generate independent voice beats concurrently; deliver in spoken order."""
import asyncio
from contextlib import aclosing

async def ordered_audio(sources):
    # Three is the maximum current core-plan beat count. Keep the same bound
    # for older cached scripts too. Backpressure bounds prefetched PCM memory.
    slots=asyncio.Semaphore(3)
    queues=[asyncio.Queue(maxsize=16) for _ in sources]
    end=object()
    async def produce(source,queue):
        try:
            async with slots, aclosing(source) as stream:
                async for item in stream:await queue.put(item)
        except Exception as error:
            await queue.put(error)
        await queue.put(end)
    workers=[asyncio.create_task(produce(source,queue)) for source,queue in zip(sources,queues)]
    try:
        for queue in queues:
            while True:
                item=await queue.get()
                if item is end:break
                if isinstance(item,Exception):raise item
                yield item
                if item.get('type')=='audio.error':return
    finally:
        for worker in workers:worker.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        # An iterator waiting for a semaphore may never have been entered.
        for source in sources:await source.aclose()
