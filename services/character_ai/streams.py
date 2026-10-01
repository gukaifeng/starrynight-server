"""Own each upstream stream until cancellation/cleanup really finishes.

AnyIO's bounded memory stream provides backpressure. A response always closes its
producer, including ASGI send failures while the body generator is suspended.
"""
import asyncio
from contextlib import aclosing
import re
from weakref import WeakValueDictionary

import anyio
from fastapi import HTTPException
from starlette.responses import StreamingResponse
from .storage import dump


class StreamJob:
    def __init__(self, source, finished):
        self.sender, self.receiver = anyio.create_memory_object_stream(4)
        self.stopping = False
        self.task = asyncio.create_task(self.produce(source))
        self.task.add_done_callback(lambda _: self.finished(finished))

    async def produce(self, source):
        async with self.sender:
            try:
                async with aclosing(source):
                    async with asyncio.timeout(150):
                        async for item in source:
                            await self.sender.send(item)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code = 'REPLY_TIMEOUT' if isinstance(error, TimeoutError) else (
                    str(error) if isinstance(error, ValueError) else getattr(error, 'code', 'CONNECTION_FAILED'))
                safe = code if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', code) else 'CONNECTION_FAILED'
                if safe in ('REPLY_REPEATED','GREETING_REPEATED'):safe='REPLY_UNAVAILABLE'
                await self.sender.send(dict(type='reply.error', code=safe))

    def finished(self, callback):
        # Also runs if a task was cancelled before its first coroutine step.
        self.sender.close()
        if not self.task.cancelled():
            self.task.exception()  # Retrieve exceptions even after disconnection.
        callback(self)

    async def close(self):
        if not self.task.done() and not self.stopping:
            self.stopping = True
            self.task.cancel()
        done, _ = await asyncio.wait({self.task}, timeout=3)
        if not done:
            raise HTTPException(503, 'TURN_CLEANUP_TIMEOUT', headers={'Retry-After': '1'})

    async def events(self):
        async with self.receiver:
            async for item in self.receiver:
                yield 'data: ' + dump(item) + '\n\n'


class TurnStreams:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self.active = {}
        self.locks = WeakValueDictionary()

    def lock(self, key):
        return self.locks.setdefault(key, asyncio.Lock())

    def release(self, key, job):
        if self.active.get(key, (None, None))[1] is job:
            self.active.pop(key, None)

    async def start(self, key, request_id, source, replace=True, validate=None):
        async with self.lock(key):
            if validate:validate()
            current = self.active.get(key)
            if current and current[1].task.done():
                self.release(key, current[1]); current = None
            if current:
                if current[0] == request_id or not replace:
                    raise HTTPException(409, 'TURN_IN_PROGRESS', headers={'Retry-After': '1'})
                await current[1].close()
                self.release(key, current[1])
            if validate:validate() # Cleanup awaited; deletion may have begun meanwhile.
            if len(self.active) >= self.capacity:
                raise HTTPException(503, 'SERVER_BUSY', headers={'Retry-After': '1'})
            job = StreamJob(source(), lambda item: self.release(key, item))
            self.active[key] = (request_id, job)
            return ManagedResponse(job)

    async def cancel(self, key):
        async with self.lock(key):
            if current := self.active.get(key):
                await current[1].close()
                self.release(key, current[1])

    async def close(self):
        await asyncio.gather(*(job.close() for _, job in list(self.active.values())))


class ManagedResponse(StreamingResponse):
    def __init__(self, job):
        self.job = job
        super().__init__(job.events(), media_type='text/event-stream',
                         headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    async def __call__(self, scope, receive, send):
        try:
            # Watch disconnection even on ASGI >=2.4: waiting for the next failed
            # write could otherwise leave a silent/slow provider running for 75s.
            async with anyio.create_task_group() as tasks:
                async def transmit():
                    try:
                        await self.stream_response(send)
                    except OSError:
                        pass  # Socket gone; cleanup below owns the provider.
                    finally:
                        tasks.cancel_scope.cancel()
                tasks.start_soon(transmit)
                await self.listen_for_disconnect(receive)
                tasks.cancel_scope.cancel()
        finally:
            # A disconnected AnyIO scope otherwise cancels cleanup at its first
            # await, leaving the provider socket and conversation slot occupied.
            with anyio.CancelScope(shield=True):
                await self.job.close()
                await self.body_iterator.aclose()
