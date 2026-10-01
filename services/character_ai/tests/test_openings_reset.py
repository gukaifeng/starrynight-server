import hashlib
import hmac
import json
from pathlib import Path
import uuid

import httpx
import pytest
from services.character_ai.app import create_app
from services.character_ai.config import Settings
from services.character_ai.profiles import PROFILES
from scripts.prepare_character_openings import compile_catalog
from services.character_ai.reply_flow import safe_boundaries
from services.character_ai.schemas import visible_thought

class NoProvider:
    def __getattr__(self, key):
        raise AssertionError('Opening/deletion must not invoke provider: '+key)

def test_all_openings_match_roster_language_and_real_performances():
    catalog=compile_catalog()
    performance=json.loads(Path('services/character_ai/performance_catalog.json').read_text())['characters']
    assert len(catalog['characters'])==11
    assert {c['characterID'] for c in catalog['characters']}==set(PROFILES)
    for role in catalog['characters']:
        variants=role['variants'];assert len({v['text'] for v in variants})==3
        options={v['asset_id']:v for v in performance[role['characterID']]}
        for v in variants:
            assert v['text'].endswith(('？','?','。','！','.')) and len(v['visuals'])>=2
            if v['language']=='en':assert not any('\u4e00'<=c<='\u9fff' for c in v['text'])
            assert len([p for p in v['parts'] if p['kind']=='thought' and visible_thought(p['text'])])==2
            assert ''.join(p['text'] for p in v['parts'] if p['kind']=='dialogue')==v['text']
            cursor=0
            for part in v['parts']:
                if part['kind']=='dialogue':cursor+=len(part['text'])
                else:assert cursor in safe_boundaries(v['text'])
            assert any(mark in v['text'] for mark in ['……','～','…','!','！'])
            for visual in v['visuals']:
                original=options[visual['assetId']]
                assert original['speech_compatible'] and original['automatic']
                assert visual['group']==original['group']
                assert 0<visual['durationMs']<=4000 and visual['offsetMs']>=0
        assert len(role['legacyVariants'])==3
        assert not {v['id'] for v in variants}&{v['id'] for v in role['legacyVariants']}

@pytest.mark.asyncio
async def test_first_meeting_registration_and_full_reset_are_scoped_and_idempotent(tmp_path):
    settings=Settings(data_dir=tmp_path,client_token='opening-test',paid_enabled=False)
    app=create_app(settings,NoProvider());store=app.state.store
    install=str(uuid.uuid4());account='fixture'
    headers={'Authorization':'Bearer opening-test','X-Starry-Installation':install,'X-Starry-Account':account}
    owner=hmac.new(b'opening-test',(install+'|'+account).encode(),hashlib.sha256).hexdigest()
    role='anime-kipfel';other='anime-mamehinata';path='/v1/conversations/'+role
    store.put('voice','system',role,{'approved':True,'voice_id':'keep-system-voice'})
    store.put('relationship',owner,other,{'closeness':0.7})
    store.put('relationship','someone-else',role,{'closeness':0.9})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first={'opening_id':'anime-kipfel-v2-1','message_id':str(uuid.uuid4())}
        assert (await client.post(path+'/opening',headers=headers,json=first)).status_code==200
        assert (await client.post(path+'/opening',headers=headers,json=first)).status_code==200
        assert len(store.history(owner,role))==1
        saved=json.loads(store.db.execute('SELECT data FROM messages WHERE id=?',(first['message_id'],)).fetchone()[0])
        assert len([p for p in saved['beats'][0]['parts'] if p['kind']=='thought'])==2
        text=store.history(owner,role)[0]['text'];assert '琪宝' in text and '书屋' in text
        assert store.get('greetings',owner,role)==[text]
        store.put('relationship',owner,role,{'closeness':0.9})
        store.put('state',owner,role,{'anger':0.8})
        with store.db:
            store.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)',('m',owner,role,'user','erase me',1,0,0))
        reset=str(uuid.uuid4())
        assert (await client.delete(path+'?reset_id='+reset,headers=headers)).status_code==200
        assert not store.history(owner,role)
        assert not store.get('relationship',owner,role) and not store.get('state',owner,role)
        assert store.db.execute('SELECT count(*) FROM memories WHERE owner=? AND character=?',(owner,role)).fetchone()[0]==0
        assert store.db.execute('SELECT count(*) FROM reply_novelty WHERE owner=? AND character=?',(owner,role)).fetchone()[0]==0
        assert store.get('voice','system',role)['approved']
        assert store.get('relationship',owner,other)['closeness']==0.7
        assert store.get('relationship','someone-else',role)['closeness']==0.9
        # Old clients/drafts cannot recreate memory after reset.
        assert (await client.post(path+'/opening',headers=headers,json=first)).status_code==409
        first.update(message_id=str(uuid.uuid4()),opening_id='anime-kipfel-2',conversation_reset=reset)
        assert (await client.post(path+'/opening',headers=headers,json=first)).status_code==200
        new=store.history(owner,role)
        assert (await client.delete(path+'?reset_id='+reset,headers=headers)).status_code==200
        assert store.history(owner,role)==new # Lost acknowledgement retry does not delete new history.
        bad={**first,'opening_id':'anime-mamehinata-1'}
        assert (await client.post(path+'/opening',headers=headers,json=bad)).status_code==422
        assert (await client.delete(path+'?reset_id='+reset)).status_code==401
        assert (await client.delete(path+'?reset_id=not-a-uuid',headers=headers)).status_code==422
        # A delayed cross-device reset cannot erase conversation begun after a
        # newer account reset. The receipt gives the caller the actual epoch.
        newest=str(uuid.uuid4()); older=str(uuid.uuid4())
        assert (await client.delete(path+'?reset_id='+newest+'&reset_version=2',headers=headers)).json()['version']==2
        first.update(message_id=str(uuid.uuid4()),conversation_reset=newest)
        assert (await client.post(path+'/opening',headers=headers,json=first)).status_code==200
        new=store.history(owner,role)
        late=await client.delete(path+'?reset_id='+older+'&reset_version=1',headers=headers)
        assert late.json()['reset_id']==newest and late.json()['version']==2
        assert store.history(owner,role)==new
        assert (await client.post(path+'/opening',headers=headers,json={**first,'conversation_reset':older})).status_code==409
    await app.state.reactions.close();await app.state.turns.close();store.db.close()
