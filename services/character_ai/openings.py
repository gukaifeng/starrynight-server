"""Only packaged first meetings are fixed. Registration never calls a provider."""
import json
from pathlib import Path
from uuid import UUID
from pydantic import Field
from .schemas import Strict

class OpeningRegistration(Strict):
    message_id:UUID
    opening_id:str = Field(max_length=100)
    conversation_reset:str = Field(default='',max_length=36)

def register(store, owner, character, body):
    catalog=json.loads(Path(__file__).with_name('opening_catalog.json').read_text())
    variant=next((v for c in catalog['characters'] if c['characterID']==character for v in c['variants']+c.get('legacyVariants',[]) if v['id']==body.opening_id),None)
    if variant is None:raise ValueError('UNKNOWN_OPENING')
    # An offline introduction may register late. Never insert it after existing
    # live history, or overwrite another device's already registered first visit.
    if store.history(owner,character):return
    identifier=str(body.message_id)
    script=dict(message_id=identifier,character_id=character,text=variant['text'],trigger='firstMeeting',
                beats=[dict(beat_id='opening',sentences=variant.get('sentences',[]),dialogue=dict(text=variant['text'],speech=dict(emotion=variant.get('sentences',[{'emotion':'happy'}])[0]['emotion'])),narrations=[],visuals=[],
                    parts=variant.get('parts',[dict(kind='dialogue',text=variant['text'],at=0)]))],
                opening_id=body.opening_id,
                initial_replies=next((c.get('initialReplies',[]) for c in catalog['characters'] if c['characterID']==character),[]))
    store.message(identifier,owner,character,identifier,'assistant',script)
    store.put('greetings',owner,character,[variant['text']])
    if variant.get('sentences'):store.put('sentence_emotion.v1',owner,character,variant['sentences'][-1]['emotion'])
