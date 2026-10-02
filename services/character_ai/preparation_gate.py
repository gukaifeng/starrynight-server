"""Bounded background slots; ready/foreground streams never wait on this gate."""
import asyncio,heapq,itertools
from dataclasses import dataclass,field

@dataclass(order=True)
class Waiter:
    priority:int
    sequence:int
    future:object=field(compare=False)
    key:object=field(default=None,compare=False)
    active:bool=field(default=False,compare=False)
from contextlib import asynccontextmanager

class PreparationGate:
    def __init__(self,capacity,quick_reserve=0):
        self.capacity=capacity;self.used=0;self.low_used=0;self.waiters=[];self.sequence=itertools.count()
        self.low_capacity=max(1,capacity-quick_reserve);self.entries={}

    def allowed(self,entry):
        # One bounded foreground handoff lane prevents a selected, queued
        # branch waiting behind unrelated background work. It is the SAME
        # generation, not a second provider request.
        if entry.priority<0:return self.used<self.capacity+1
        return self.used<self.capacity and (entry.priority==0 or self.low_used<self.low_capacity)

    def wake(self):
        while self.waiters:
            skipped=[];selected=None
            while self.waiters:
                entry=heapq.heappop(self.waiters)
                if entry.future.done():continue
                if self.allowed(entry):selected=entry;break
                skipped.append(entry)
            for entry in skipped:heapq.heappush(self.waiters,entry)
            if selected is None:break
            selected.active=True;self.used+=1
            if selected.priority>0:self.low_used+=1
            selected.future.set_result(None)

    def promote(self,key):
        entry=self.entries.get(key)
        if entry is None:return
        if entry.active and entry.priority>0:self.low_used-=1
        entry.priority=-1;heapq.heapify(self.waiters);self.wake()

    def release(self,entry):
        if entry.active:
            self.used-=1
            if entry.priority>0:self.low_used-=1
            entry.active=False
        if entry.key is not None:self.entries.pop(entry.key,None)
        self.wake()

    @asynccontextmanager
    async def acquire(self,priority,key=None):
        future=asyncio.get_running_loop().create_future()
        entry=Waiter(priority,next(self.sequence),future,key)
        if key is not None:self.entries[key]=entry
        heapq.heappush(self.waiters,entry);self.wake()
        try:await future
        except BaseException:
            future.cancel();self.release(entry);raise
        try:yield
        finally:self.release(entry)
