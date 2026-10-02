#!/usr/bin/env python3
"""Disposable cloud account/photo checks; optional one-entry paid cache probe."""
import argparse,base64,json,secrets,struct,time,urllib.request,urllib.error,uuid,zlib

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--paid-cache',action='store_true');args=parser.parse_args()
    base='https://39.105.116.74:8443';client=urllib.request.build_opener(urllib.request.ProxyHandler({}));accounts=[];results={}
    def call(method,path,token=None,body=None,status=200):
        headers={'Accept':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        data=json.dumps(body).encode() if body is not None else None
        if data:headers['Content-Type']='application/json'
        request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
        try:
            with client.open(request,timeout=30) as response:code=response.status;data=response.read()
        except urllib.error.HTTPError as error:code=error.code;data=error.read()
        if code!=status:raise RuntimeError(method+' '+path+' returned '+str(code))
        return json.loads(data) if data.startswith(b'{') else None
    def image():
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\x32\x70\xa0'*2+b'\0'+b'\x32\x70\xa0'*2))+chunk(b'IEND',b'')
    role='anime-ichigo';reset=False
    try:
        for _ in range(2):
            password=secrets.token_urlsafe(24)
            session=call('POST','/v1/auth/register',body={'username':'cache_'+secrets.token_hex(8),'password':password,'display_name':'Cache verification'})
            accounts.append((session,password))
        a,b=accounts[0][0],accounts[1][0];token=a['token'];user=a['user']
        assert user['starry_id'].startswith('xy') and user['starry_id'][2:].isdigit() and not user['starry_id'][2:].startswith('0')
        assert int(user['starry_id'][2:])>=100000001 and int(b['user']['starry_id'][2:])>=100000001
        assert user['starry_id']!=b['user']['starry_id'] and user['profile']['avatar']=='starry-orbit-v1'
        call('PATCH','/v1/me',token,dict(expected_version=user['version'],patch=dict(starry_id=b['user']['starry_id'])),422)
        uploaded=call('PUT','/v1/me/avatar',token,dict(expected_version=user['version'],image=base64.b64encode(image()).decode()))
        avatar=call('GET','/v1/me/avatar',token);assert uploaded['data']['avatar']=='upload:'+avatar['sha256']
        call('GET','/v1/me/avatar',b['token'],status=404)
        call('PATCH','/v1/me',b['token'],dict(expected_version=b['user']['version'],patch=dict(avatar=uploaded['data']['avatar'])),422)
        again=call('POST','/v1/auth/login',body=dict(username=user['username'],password=accounts[0][1]))
        assert again['user']['id']==user['id'] and again['user']['starry_id']==user['starry_id']
        assert call('GET','/v1/me/avatar',again['token'])['sha256']==avatar['sha256']
        results.update(public_handle=True,immutable_handle=True,photo_roundtrip=True,photo_owner_isolation=True,login_preserves_identity=True)
        if args.paid_cache:
            path='/v1/ai/conversations/'+role
            body=dict(request_id=str(uuid.uuid4()),character_id=role,text='',trigger='appLaunch',preparation_scope='entry',preferences={},memories=[],recent_messages=[dict(role='assistant',text='你好，这是一段测试会话。')],scene={},available_assets=[],wants_audio=True)
            start=time.monotonic();status=call('POST',path+'/reactions/prepare',token,body)
            while not status['ready'].get('app_launch') and time.monotonic()-start<100:
                time.sleep(.5);status=call('POST',path+'/reactions/status',token,body)
                if not status['pending'].get('app_launch'):break
            assert status['ready'].get('app_launch')==1,'Entry text/audio draft did not become ready'
            prepared_seconds=time.monotonic()-start
            body.pop('preparation_scope');body['request_id']=str(uuid.uuid4());body['entry_id']=str(uuid.uuid4())
            request=urllib.request.Request(base+path+'/messages',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'text/event-stream','X-Starry-Reply-Mode':'timeline-v2','X-Starry-Performance-Mode':'parallel-v1'},method='POST')
            first_reply=first_audio=None;prepared=False;start=time.monotonic()
            with client.open(request,timeout=30) as response:
                for raw in response:
                    if not raw.startswith(b'data: '):continue
                    event=json.loads(raw[6:]);kind=event.get('type')
                    if kind=='reply.error':raise RuntimeError('Prepared delivery failed')
                    if kind=='reply.narration.ready':first_reply=time.monotonic()-start;prepared=bool(event.get('prepared'))
                    if kind=='segment.audio.chunk' and first_audio is None:first_audio=time.monotonic()-start
            assert prepared and first_audio is not None,'Ready cache was not consumed'
            results['ready_entry_cache']=dict(prepared=True,background_seconds=round(prepared_seconds,3),first_reply_seconds=round(first_reply,3),first_audio_seconds=round(first_audio,3))
            identifier=str(uuid.uuid4());receipt=call('DELETE','/v1/conversations/'+role+'?reset_id='+identifier,token)
            call('DELETE',path+'?reset_id='+identifier+'&reset_version='+str(receipt['version']),token);reset=True
    finally:
        if args.paid_cache and accounts and not reset:
            token=accounts[0][0]['token'];identifier=str(uuid.uuid4())
            receipt=call('DELETE','/v1/conversations/'+role+'?reset_id='+identifier,token)
            call('DELETE','/v1/ai/conversations/'+role+'?reset_id='+identifier+'&reset_version='+str(receipt['version']),token)
        for session,password in accounts:call('DELETE','/v1/me',session['token'],dict(password=password,confirmation='DELETE'))
    print(json.dumps(dict(results=results,temporary_accounts_deleted=True,paid_cache=args.paid_cache),ensure_ascii=False))

if __name__=='__main__':main()
