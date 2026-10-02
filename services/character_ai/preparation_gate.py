"""Bounded background slots; ready/foreground streams never wait on this gate."""
import asyncio,heapq,itertools
from contextlib import asynccontextmanager

class PreparationGate:
    def __init__(self,capacity):
        self.capacity=capacity;self.used=0;self.waiters=[];self.sequence=itertools.count()

    def wake(self):
        while self.used<self.capacity and self.waiters:
            _,_,future=heapq.heappop(self.waiters)
            if future.done():continue
            self.used+=1;future.set_result(None)

    @asynccontextmanager
    async def acquire(self,priority):
        future=asyncio.get_running_loop().create_future()
        heapq.heappush(self.waiters,(priority,next(self.sequence),future));self.wake()
        try:await future
        except BaseException:
            if not future.cancelled() and future.done():self.used-=1
            future.cancel();self.wake();raise
        try:yield
        finally:self.used-=1;self.wake()
