import copy,json
import httpx,pytest
from services.character_ai.app import create_app
from services.character_ai.config import Settings
from services.character_ai.profiles import PROFILES
from services.character_ai import prompts

@pytest.mark.asyncio
async def test_admin_console_auth_secrets_profiles_config(tmp_path,monkeypatch):
    snapshot=copy.deepcopy(PROFILES)
    for key in ('PLANNER','CORE_PLANNER','NARRATOR','PERFORMER','REPLY_LENGTH'):monkeypatch.setattr(prompts,key,getattr(prompts,key))
    settings=Settings(data_dir=tmp_path,api_key='PRIVATE_API_VALUE',admin_token='PRIVATE_ADMIN_VALUE',client_token='APP_TOKEN',paid_enabled=False)
    app=create_app(settings);headers={'Authorization':'Bearer PRIVATE_ADMIN_VALUE'}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            root='/v1/admin/console'
            assert (await client.get(root+'/resources')).status_code==401
            assert (await client.get(root+'/resources',headers={'Authorization':'Bearer APP_TOKEN'})).status_code==401
            response=await client.get(root+'/resources',headers=headers);assert response.status_code==200
            for resource in response.json():
                rows=await client.get(root+'/resources/'+resource['id'],headers=headers);assert rows.status_code==200,(resource,rows.text)
                assert 'PRIVATE_API_VALUE' not in rows.text and 'PRIVATE_ADMIN_VALUE' not in rows.text
            profiles=(await client.get(root+'/resources/profiles',headers=headers)).json()['items'];role=profiles[0];role['data']['occupation']='控制室测试'
            body=dict(keys={'id':role['id']},action='edit',expected_version=role['version'],values={'data':role['data']})
            result=await client.post(root+'/resources/profiles/mutate',json=body,headers=headers);assert result.status_code==200,result.text
            assert PROFILES[role['id']]['occupation']=='控制室测试'
            assert (await client.post(root+'/resources/profiles/mutate',json=body,headers=headers)).status_code==409
            restore=dict(keys=body['keys'],action='restore',confirmed=True,expected_version=2)
            assert (await client.post(root+'/resources/profiles/mutate',json=restore,headers=headers)).status_code==200
            assert PROFILES[role['id']]['occupation']==snapshot[role['id']]['occupation']
            cfg=(await client.get(root+'/resources/config',headers=headers)).json()['items'][0];cfg['data']['suggestions_model']='qwen-turbo-latest'
            body=dict(keys={'id':'runtime'},action='edit',expected_version=1,values={'data':cfg['data']})
            result=await client.post(root+'/resources/config/mutate',json=body,headers=headers);assert result.status_code==200,result.text
            assert settings.suggestions_model=='qwen-turbo-latest'
            assert json.loads((tmp_path/'admin-settings.json').read_text())['suggestions_model']=='qwen-turbo-latest'
            body['expected_version']=2;body['values']['data']['api_key']='FORGED';assert (await client.post(root+'/resources/config/mutate',json=body,headers=headers)).status_code==422
            app.state.store.put('voice','system',role['id'],{'voice_id':'PRIVATE_VOICE','approved':True})
            rows=await client.get(root+'/resources/records',headers=headers);assert 'PRIVATE_VOICE' not in rows.text
            search=await client.get(root+'/resources/records',params={'q':'voice'},headers=headers);assert search.status_code==200,search.text
            assert (await client.post(root+'/voices/'+role['id']+'/generate',json={},headers=headers)).status_code==422
            # Automatic memories use a content revision so inference updates or
            # SQLite row-id reuse cannot be overwritten by an old editor.
            store=app.state.store
            with store.db:store.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)',('m','owner',role['id'],'automatic','old memory',.5,1,0))
            memory=(await client.get(root+'/resources/memories',headers=headers)).json()['items'][0]
            edit=dict(keys={'_rowid':str(memory['_rowid'])},action='edit',expected_version=memory['version'],values={'content':'new memory','importance':.8})
            assert (await client.post(root+'/resources/memories/mutate',json=edit,headers=headers)).status_code==200
            assert (await client.post(root+'/resources/memories/mutate',json=edit,headers=headers)).status_code==409
            # Cache management affects only the selected account / character.
            with store.db:
                for id,owner in [('ours','owner'),('theirs','other')]:store.db.execute('INSERT INTO reaction_drafts VALUES(?,?,?,?,?,?,?,?,?)',(id,owner,role['id'],'shake','key','ready','{}',1,9999999999))
            drafts=(await client.get(root+'/resources/reaction_drafts',headers=headers)).json()['items']
            ours=next(r for r in drafts if r['id']=='ours')
            clear=dict(keys={'_rowid':str(ours['_rowid'])},action='clear_unused',confirmed=True)
            assert (await client.post(root+'/resources/reaction_drafts/mutate',json=clear,headers=headers)).status_code==200
            assert store.db.execute("SELECT 1 FROM reaction_drafts WHERE id='theirs'").fetchone()
            assert not store.db.execute("SELECT 1 FROM reaction_drafts WHERE id='ours'").fetchone()
    finally:
        PROFILES.clear();PROFILES.update(snapshot);app.state.store.db.close();await app.state.engine.provider.close()
def test_voice_authorization_duration_is_visible_but_credentials_are_not():
    from services.character_ai.admin_console import safe
    assert safe({'gateway':{'authorization_ms':9.5,'authorization':'secret'}})=={
        'gateway':{'authorization_ms':9.5,'authorization':'[已隐藏]'}}
    for value in ('secret',{'authorization':'secret'},float('nan'),True):
        assert safe({'authorization_ms':value})=={'authorization_ms':'[已隐藏]'}

@pytest.mark.asyncio
async def test_operator_scopes_and_worker_only_relationships(tmp_path):
    settings=Settings(data_dir=tmp_path,admin_token='operator-fixture',paid_enabled=False)
    app=create_app(settings);store=app.state.store
    chars=list(PROFILES)[:2]
    with store.db:
        for i in range(33):
            owner='ours' if i<27 else 'theirs';character=chars[0] if i<30 else chars[1]
            store.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(f'm{i}',owner,character,'r','assistant',json.dumps(dict(text=f'fixture {i}')),i+1))
        store.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)',('memory','ours',chars[0],'automatic','only ours',.5,1,0))
        store.db.execute('INSERT INTO reply_embeddings VALUES(?,?,?)',('m0','local-test',b'never-return-a-vector'))
        for i in range(27):
            store.db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',(f'worker-only-{i:02d}',chars[0],f'r{i}','hash','done','{}',1))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer operator-fixture'}) as client:
            root='/v1/admin/console'
            records=(await client.get(root+'/resources',headers={'Authorization':'Bearer operator-fixture'})).json()
            for resource in records:
                if 'owner' in resource['fields']:
                    response=await client.get(root+'/resources/'+resource['id'],params=dict(owner='ours',character=chars[0]));assert response.status_code==200,response.text
                    assert all(r['owner']=='ours' and r['character']==chars[0] for r in response.json()['items'])
            rows=(await client.get(root+'/resources/messages',params=dict(owner='ours',character=chars[0]))).json()['items']
            assert len(rows)==27
            filtered=(await client.get(root+'/resources/messages',params=dict(owner='ours',character=chars[0],q='fixture 26'))).json()['items'];assert len(filtered)==1 and filtered[0]['id']=='m26'
            assert not (await client.get(root+'/resources/messages',params=dict(owner="ours' OR 1=1--"))).json()['items']
            embeddings=await client.get(root+'/resources/reply_embeddings',params=dict(owner='ours',character=chars[0]));assert embeddings.status_code==200 and len(embeddings.json()['items'])==1 and 'never-return-a-vector' not in embeddings.text
            profiles=(await client.get(root+'/resources/profiles',params=dict(character=chars[0]))).json()['items'];assert len(profiles)==1 and profiles[0]['id']==chars[0]
            assert (await client.get(root+'/resources/config',params=dict(owner='ours'))).status_code==422
            assert (await client.get(root+'/resources/voice_design_jobs',params=dict(owner='ours'))).status_code==422
            assert (await client.get(root+'/relationships')).status_code==422
            page=(await client.get(root+'/relationships',params=dict(character=chars[0]))).json();assert len(page['items'])==25 and page['next']
            next_page=(await client.get(root+'/relationships',params=dict(character=chars[0],after=page['next']))).json()
            pairs={(r['owner'],r['character']) for r in page['items']+next_page['items']};assert len(pairs)==29
            assert any(r['owner']=='worker-only-00' and r['messages']==0 for r in page['items']+next_page['items'])
            ours=next(r for r in page['items'] if r['owner']=='ours');assert ours['messages']==27 and ours['memories']==1
            summary=(await client.get(root+'/entity-summary',params=dict(owner='ours',character=chars[0]))).json()
            assert summary['messages']==27 and summary['memories']==1 and summary['ai_messages']==27 and summary['archive_counts_included'] is False
            assert (await client.get(root+'/entity-summary')).status_code==422
            assert (await client.get(root+'/relationships',params=dict(character=chars[1],after=page['next']))).status_code==422
            assert (await client.get(root+'/relationships',params=dict(character=chars[0],after='not-a-cursor'))).status_code==422
            assert (await client.get(root+'/relationships',headers={'Authorization':'Bearer wrong'},params=dict(owner='ours'))).status_code==401
            for table in ('messages','requests','usage','records'):
                plan=store.db.execute(f'EXPLAIN QUERY PLAN SELECT rowid FROM {table} WHERE character=? AND owner=? ORDER BY rowid LIMIT 51',(chars[0],'ours')).fetchall()
                assert any('INDEX' in r['detail'] for r in plan),plan
    finally:
        store.db.close();await app.state.engine.provider.close()
