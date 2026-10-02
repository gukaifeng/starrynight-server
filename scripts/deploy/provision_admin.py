#!/usr/bin/env python3
"""Add the control-room listener to an already active, verified release.

Does not restore data, replace app credentials or alter the 8443 routes.
Creates the first owner only when the admin table is empty; stdin is the
bootstrap password. Existing admins are never replaced.
"""
import argparse,datetime,json,os,platform,subprocess,time,urllib.request
from pathlib import Path
from activate_standby_release import environment,pg_environment
from upgrade_active_api import verify_release

def run(*args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def ready(url):
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end=time.monotonic()+30
    while time.monotonic()<end:
        try:
            with client.open(url,timeout=2) as r:
                if r.status==200:return
        except OSError:pass
        time.sleep(.5)
    raise RuntimeError('Readiness failed: '+url)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username',default='owner');parser.add_argument('--bootstrap',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    home=Path.home();root=home/'app';config=root/'config';current=home/'starrynight-server/current'
    if platform.system()!='Linux' or json.loads((config/'provisioned.json').read_text()).get('state')!='active':raise ValueError('Requires active Linux host')
    manifest=verify_release(current.resolve())
    if 'bin/starry-admin' not in manifest['files'] or 'admin-web/dist/index.html' not in manifest['files']:raise ValueError('Verified admin build missing')
    env=environment(config/'platform.env')
    result=run(root/'postgres/bin/psql','-Atq','-c','SELECT count(*) FROM admin_users',env=pg_environment(env),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.stdout.strip()==b'0':
        if not args.bootstrap:raise ValueError('First owner requires --bootstrap and password on stdin')
        password=os.read(0,130).strip()
        if not 12<=len(password)<=128:raise ValueError('Bootstrap password must be 12–128 bytes')
        run(current/'bin/starry-admin','--bootstrap','--username',args.username,env=env,input=password,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    unit=home/'.config/systemd/user/starry-admin.service';adminenv=config/'admin.env';edge=config/'Caddyfile'
    previous={p:p.read_bytes() if p.exists() else None for p in (unit,adminenv,edge)}
    backup=root/'backups'/('before-admin-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'));backup.mkdir(mode=0o700)
    for p,value in previous.items():
        if value is not None:(backup/(p.name+'.previous')).write_bytes(value)
    existing=edge.read_text();start='# BEGIN STARRY ADMIN';end='# END STARRY ADMIN'
    if start in existing:
        before,_,rest=existing.partition(start);_,marker,after=rest.partition(end)
        if not marker:raise ValueError('Malformed managed admin block')
        existing=before+after
    block='''
# BEGIN STARRY ADMIN
https://39.105.116.74:8444 {
    tls /home/starrynight/app/config/certbot/live/starrynight-ip/fullchain.pem /home/starrynight/app/config/certbot/live/starrynight-ip/privkey.pem
    header -Server
    encode zstd gzip
    reverse_proxy 127.0.0.1:8100
}
# END STARRY ADMIN
'''
    candidate=backup/'Caddyfile.candidate';candidate.write_text(existing.rstrip()+'\n'+block)
    run(root/'bin/caddy','validate','--config',candidate,'--adapter','caddyfile',stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        unit.parent.mkdir(parents=True,exist_ok=True);unit.write_bytes((current/'scripts/deploy/starry-admin.service').read_bytes())
        adminenv.write_text('ADMIN_LISTEN=127.0.0.1:8100\nADMIN_ORIGIN=https://39.105.116.74:8444\nADMIN_WEB_ROOT=/home/starrynight/starrynight-server/current/admin-web/dist\nADMIN_SYSTEMD=true\nSTARRY_AI_CONFIG=/home/starrynight/app/config/ai-settings.json\n')
        run('systemctl','--user','daemon-reload');run('systemctl','--user','enable','--now','starry-admin');run('systemctl','--user','restart','starry-admin')
        ready('http://127.0.0.1:8100/health/ready');edge.write_bytes(candidate.read_bytes());run('systemctl','--user','reload','starry-edge')
        ready('https://39.105.116.74:8444/health/ready');ready('http://127.0.0.1:8090/health/ready')
    except Exception:
        for p,value in previous.items():
            if value is None:p.unlink(missing_ok=True)
            else:p.write_bytes(value)
        run('systemctl','--user','daemon-reload');run('systemctl','--user','reload','starry-edge')
        if previous[unit] is None:run('systemctl','--user','disable','--now','starry-admin')
        else:run('systemctl','--user','restart','starry-admin')
        raise
    print(json.dumps({'admin_ready':True,'url':'https://39.105.116.74:8444','release':manifest['release'],'backup':str(backup),'app_routes_unchanged':True}))
if __name__=='__main__':main()
