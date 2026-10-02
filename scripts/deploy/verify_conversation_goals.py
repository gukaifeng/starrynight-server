#!/usr/bin/env python3
"""Disposable-account goal checks. Paid AI smoke is explicit and text-only."""
import argparse,json,secrets,time,urllib.request,urllib.error,uuid

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--paid-smoke',action='store_true');args=parser.parse_args()
    base='https://39.105.116.74:8443';client=urllib.request.build_opener(urllib.request.ProxyHandler({}));accounts=[];results=[]
    def call(method,path,token=None,body=None,status=200,stream=False):
        headers={'Accept':'text/event-stream' if stream else 'application/json'}
        if token:headers['Authorization']='Bearer '+token
        if body is not None:headers['Content-Type']='application/json'
        if stream:headers['X-Starry-Reply-Mode']='timeline-v2'
        request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            with client.open(request,timeout=90 if stream else 20) as response:data=response.read();code=response.status
        except urllib.error.HTTPError as error:code=error.code;data=error.read()
        if code!=status:raise RuntimeError(method+' '+path+' returned '+str(code))
        if stream:
            events=[json.loads(line[6:]) for line in data.decode().splitlines() if line.startswith('data: ')]
            if any(e.get('type')=='reply.error' for e in events):raise RuntimeError('AI stream error')
            return next(e['script'] for e in events if e.get('type')=='reply.narration.ready')
        return json.loads(data) if data.startswith(b'{') else None
    try:
        role='anime-ichigo';path='/v1/conversations/'+role+'/goals'
        call('GET',path,status=401);call('POST','/internal/goals/'+str(uuid.uuid4())+'/'+role+'/feedback',body={},status=404)
        for _ in range(2):
            password=secrets.token_urlsafe(24)
            session=call('POST','/v1/auth/register',body={'username':'goals_'+secrets.token_hex(8),'password':password,'display_name':'Goal verification'})
            accounts.append(dict(session=session,password=password))
        a,b=accounts;token=a['session']['token'];initial=call('GET',path,token)
        assert initial['romance_allowed'] and initial['config']['long_term']=='romance'
        config=initial['config']|dict(initial_relation='pursuit',short_term='今天想约会')
        g=call('PUT',path,token,dict(expected_version=initial['version'],config=config))
        call('PUT',path,token,dict(expected_version=initial['version'],config=config),status=409)
        assert call('GET',path,b['session']['token'])['version']==0
        call('PUT','/v1/conversations/anime-kipfel/goals',token,dict(expected_version=0,config=config),status=422)
        results.append(dict(auth=True,cas=True,account_isolation=True,persona_boundaries=True,private_route_blocked=True))
        for mode,text in [('relationship','这周末想和你一起喝茶，也想慢慢了解你。'),('task','Yesterday I go to the bookshop. Can we practice a little?')]:
            if mode=='task':
                config=config|dict(mode='task',task='english',short_term='自然纠正我的表达')
                g=call('PUT',path,token,dict(expected_version=g['version'],config=config))
            if args.paid_smoke:
                body=dict(request_id=str(uuid.uuid4()),character_id=role,text=text,trigger='user_message',preferences={},memories=[],recent_messages=[],scene={},available_assets=[],wants_audio=False)
                start=time.monotonic();script=call('POST','/v1/ai/conversations/'+role+'/messages',token,body,stream=True)
                state=script.get('goal_state',{});assert state.get('version')==g['version'] and state.get('config',{}).get('mode')==mode
                if mode=='task':assert not any('\u3400'<=c<='\u9fff' for c in script['text'])
                g=call('GET',path,token);results.append(dict(mode=mode,reply=True,progress_version=g['progress_version'],bond_preserved='bond' in g['branches'],elapsed_seconds=round(time.monotonic()-start,2)))
                assert g['progress_version']>0 and 'bond' in g['branches'], 'Reply omitted goal feedback'
        g=call('PUT',path,token,dict(expected_version=g['version'],config=config|dict(paused=True)))
        assert g['config']['paused'];results.append(dict(pause=True,branches_preserved=True))
        reset=str(uuid.uuid4());receipt=call('DELETE','/v1/conversations/'+role+'?reset_id='+reset,token)
        call('DELETE','/v1/ai/conversations/'+role+'?reset_id='+reset+'&reset_version='+str(receipt['version']),token)
        cleared=call('GET',path,token);assert not cleared['branches'] and cleared['config']['paused']
        results.append(dict(reset=True,config_preserved=True))
    finally:
        for account in accounts:
            call('DELETE','/v1/me',account['session']['token'],dict(password=account['password'],confirmation='DELETE'))
    print(json.dumps(dict(paid_smoke=args.paid_smoke,results=results,temporary_accounts_deleted=True),ensure_ascii=False))

if __name__=='__main__':main()
