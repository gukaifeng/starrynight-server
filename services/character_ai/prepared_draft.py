"""One generation, with a replayable bounded stream for speculative handoff."""
import asyncio
from dataclasses import dataclass,field

@dataclass(eq=False)
class PreparedDraft:
    id:str
    owner:str
    request:object
    key:str
    kind:str
    source:str|None=None
    claimed:bool=False
    done:bool=False
    error:BaseException|None=None
    plan:dict|None=None
    script:dict|None=None
    task:asyncio.Task|None=None
    events:list=field(default_factory=list)
    changed:asyncio.Event=field(default_factory=asyncio.Event)
    size:int=0

    def append(self,item):
        # Most bytes are base64 PCM. Limit each retained stream independently;
        # ordinary short replies use a small fraction of this bound.
        self.size+=len(item.get('data',''))+len(str(item))
        if self.size>8*1024*1024:raise ValueError('PREPARED_STREAM_TOO_LARGE')
        self.events.append(item);self.changed.set()

    async def stream(self):
        cursor=0
        while True:
            while cursor<len(self.events):
                item=self.events[cursor];cursor+=1;yield item
            if self.done:
                if self.error:raise self.error
                return
            self.changed.clear()
            await self.changed.wait()
