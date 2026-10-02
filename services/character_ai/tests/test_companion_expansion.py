"""Authored companions and voice aliases must not perform provider requests."""
import json
from pathlib import Path
import pytest
from scripts.install_companion_voices import provision
from services.character_ai.profiles import PROFILES
from services.character_ai.public_profiles import public_catalog
from services.character_ai.storage import Store

def test_all_sixteen_are_real_personas_with_scoped_first_replies():
    active=json.loads(Path('authoring/active-roster.json').read_text())['characters']
    catalog=public_catalog()['characters']
    openings=json.loads(Path('services/character_ai/opening_catalog.json').read_text())['characters']
    assert len(active)==16 and {r['id'] for r in catalog}==set(active)
    assert {r['characterID'] for r in openings}==set(active)
    for role in openings:
        assert len(role['variants'])==len(role['initialReplies'])==3
        assert len(set(role['initialReplies']))==3
        assert all(v['audioReady'] and v['audioSHA256'] and v['visuals'] for v in role['variants'])
        assert PROFILES[role['characterID']]['background']

def test_approved_voice_is_preserved_and_alias_provision_is_idempotent(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    try:
        store.put('voice','system','donor',dict(approved=True,voice_id='unit-only-donor'))
        store.put('voice','system','existing',dict(approved=True,voice_id='unit-only-existing'))
        expansion=dict(revision='unit',characters={r:dict(voiceSource='donor') for r in ['new','existing']})
        assert provision(store,expansion)==['new']
        assert store.get('voice','system','new') is None
        assert provision(store,expansion,apply=True)==['new']
        assert store.get('voice','system','new')['reused_from']=='donor'
        assert store.get('voice','system','existing')['voice_id']=='unit-only-existing'
        assert provision(store,expansion,apply=True)==[]
    finally:store.db.close()

def test_missing_donor_cannot_leave_partial_voice_batch(tmp_path):
    store=Store(tmp_path/'state.sqlite3')
    try:
        store.put('voice','system','donor',dict(approved=True,voice_id='unit-only-donor'))
        expansion=dict(revision='unit',characters={'good':dict(voiceSource='donor'),'bad':dict(voiceSource='missing')})
        with pytest.raises(ValueError,match='Approved voice source missing'):provision(store,expansion,apply=True)
        assert store.get('voice','system','good') is None
    finally:store.db.close()
