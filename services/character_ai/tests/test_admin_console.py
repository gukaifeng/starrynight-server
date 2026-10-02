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
