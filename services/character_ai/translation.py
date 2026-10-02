"""Read-only, owner-scoped translations. Never write them into AI context/audio."""
import asyncio
import hashlib
import json
import re
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import HTTPException

class Segment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=180)
    kind: Literal['dialogue', 'thought', 'narration']
    text: str = Field(min_length=1, max_length=6000)

class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_language: Literal['zh-Hans', 'zh-Hant', 'en']
    segments: list[Segment] = Field(min_length=1, max_length=64)
    source_kind: Literal['assistant','user','suggestion'] = 'assistant'
    option_id: str | None = Field(default=None,max_length=150)

    @model_validator(mode='after')
    def bounded(self):
        if len({s.id for s in self.segments}) != len(self.segments) or sum(len(s.text) for s in self.segments) > 12000:
            raise ValueError('Invalid translation segments')
        if sum(sum(bool(line.strip()) for line in s.text.splitlines()) for s in self.segments)>64:
            raise ValueError('Too many translation paragraphs')
        if self.source_kind!='assistant' and (len(self.segments)!=1 or self.segments[0].kind!='dialogue'):
            raise ValueError('A user message or suggestion is one dialogue segment')
        if self.source_kind=='suggestion' and not self.option_id:raise ValueError('Missing option identity')
        return self

class TranslationResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    segments: list[Segment] = Field(min_length=1, max_length=64)

class Translations:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.locks = {}
        self.capacity = asyncio.Semaphore(4)

    def source(self,owner,character,message_id,body):
        if body.source_kind=='user':
            # Native message IDs predate the independent worker's IDs. Match
            # the exact owned user text, never accept an arbitrary source.
            row=self.store.db.execute("SELECT id,data FROM messages WHERE owner=? AND character=? AND role='user' AND json_extract(data,'$.text')=? ORDER BY created DESC LIMIT 1",(owner,character,body.segments[0].text)).fetchone()
            if not row:raise HTTPException(404,'MESSAGE_NOT_FOUND')
            return row['id'],{('dialogue',json.loads(row['data'])['text'])}
        row=self.store.db.execute("SELECT data FROM messages WHERE id=? AND owner=? AND character=? AND role='assistant'",(message_id,owner,character)).fetchone()
        if not row:raise HTTPException(404,'MESSAGE_NOT_FOUND')
        source=json.loads(row['data'])
        if body.source_kind=='suggestion':
            choices=self.store.db.execute('SELECT data FROM quick_reply_sets WHERE owner=? AND character=? AND source=? AND expires>?',(owner,character,message_id,time.time())).fetchone()
            options=json.loads(choices['data']) if choices else []
            if source.get('opening_id') and body.option_id.startswith('opening-local-'):
                texts=source.get('initial_replies')
                if texts is None:
                    from pathlib import Path
                    catalog=json.loads(Path(__file__).with_name('opening_catalog.json').read_text())
                    texts=next((c.get('initialReplies',[]) for c in catalog['characters'] if c['characterID']==character),[])
                options.extend(dict(id=f'opening-local-{message_id}-{i}',text=t) for i,t in enumerate(texts))
            option=next((o for o in options if o['id'].lower()==body.option_id.lower()),None)
            if not option:raise HTTPException(404,'SUGGESTION_NOT_FOUND')
            return message_id,{('dialogue',option['text'])}
        allowed={('dialogue',source.get('text',''))}
        for beat in source.get('beats',[]):
            allowed.add(('dialogue',(beat.get('dialogue') or {}).get('text','')))
            allowed.add(('thought',beat.get('thought','')))
            allowed.update(('narration',part['text']) for part in beat.get('narrations',[]))
            allowed.update((part['kind'],part['text']) for part in beat.get('parts') or [])
        return message_id,allowed

    async def translate(self, owner, character, message_id, body):
        source_id,allowed=self.source(owner,character,message_id,body)
        if any((s.kind, s.text) not in allowed for s in body.segments):
            raise HTTPException(409, 'TRANSLATION_SOURCE_CHANGED')
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        kind = 'translation:' + message_id + ':' + body.target_language
        if body.source_kind!='assistant':kind+=':'+body.source_kind+':'+(body.option_id or '')
        key = (owner, character, kind)
        # A single shared request for double taps. Locks are removed only when
        # no waiter remains; chat generation has an entirely separate lifecycle.
        entry = self.locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                saved = self.store.get(kind, owner, character, {})
                if saved.get('fingerprint') == fingerprint:
                    return saved['result']
                async with asyncio.timeout(25):
                    result = await self.render(owner,character,source_id,kind,body)
                if [(s.id, s.kind) for s in result.segments] != [(s.id, s.kind) for s in body.segments]:
                    raise HTTPException(502, 'TRANSLATION_SHAPE_INVALID')
                # Deletion/account reset during a request must not resurrect data.
                self.source(owner,character,message_id,body)
                output = dict(target_language=body.target_language, segments=[s.model_dump() for s in result.segments])
                self.store.put(kind, owner, character, dict(fingerprint=fingerprint, result=output))
                return output
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self.locks.pop(key, None)

    async def render(self,owner,character,message_id,kind,body):
        # Preserve every explicit newline/blank paragraph without asking a
        # translation model to reproduce routing JSON or sentinel delimiters.
        pieces=[re.split(r'(\r\n|\r|\n)',s.text) for s in body.segments]
        phrases=dict.fromkeys(p.strip() for parts in pieces for p in parts if p.strip())
        async def phrase(text):
            part_kind=kind+':part:'+hashlib.sha256(text.encode()).hexdigest()
            saved=self.store.get(part_kind,owner,character,{})
            if isinstance(saved.get('text'),str) and saved['text'].strip():return saved['text']
            async with self.capacity:
                value=await self.provider.translate_text(owner,character,text,body.target_language)
            if not isinstance(value,str) or not value.strip():raise HTTPException(502,'TRANSLATION_SHAPE_INVALID')
            if not self.store.db.execute('SELECT 1 FROM messages WHERE id=? AND owner=? AND character=?',(message_id,owner,character)).fetchone():
                raise HTTPException(404,'MESSAGE_NOT_FOUND')
            self.store.put(part_kind,owner,character,dict(text=value))
            return value
        tasks=[asyncio.create_task(phrase(p)) for p in phrases]
        try:values=await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        lookup=dict(zip(phrases,values))
        def restored(parts):
            return ''.join(re.sub(r'\S(?:.*\S)?',lambda m:lookup[p.strip()],p) if p.strip() else p for p in parts)
        return TranslationResult(segments=[Segment(id=s.id,kind=s.kind,text=restored(parts)) for s,parts in zip(body.segments,pieces)])
