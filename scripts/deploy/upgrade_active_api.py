#!/usr/bin/env python3
"""Upgrade only Go API code on the active host, keeping AI, data and sessions.

An additive migration is backed up first. A readiness failure restores the old
code link, never runs a destructive down migration or restores live data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sqlite3
import time
import urllib.error
import urllib.request
from activate_standby_release import environment, pg_environment


def run(*args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)


def verify_release(release):
    manifest = json.loads((release / 'release.json').read_text())
    if manifest['target'] != 'linux/amd64' or manifest['release'] != release.name:
        raise ValueError('Unexpected release target or name')
    for name, record in manifest['files'].items():
        path = release / name
        if path.is_symlink() or not path.resolve().is_relative_to(release):
            raise ValueError('Unsafe release path')
        if path.stat().st_size != record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Release checksum mismatch: ' + name)
    for name in ('bin/starry-api', 'bin/starry-migrate'):
        if name not in manifest['files']:
            raise ValueError('Required executable missing')
    return manifest


def ready():
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with client.open('http://127.0.0.1:8090/health/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError('API did not become ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--restart-ai', action='store_true',help='Explicit combined API/AI deployment; online SQLite backup and worker restart required')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path.home() / 'app'
    project = Path.home() / 'starrynight-server'
    release = args.release.resolve()
    if platform.system() != 'Linux' or json.loads((root / 'config/provisioned.json').read_text()).get('state') != 'active':
        raise ValueError('This command requires the active Linux host')
    if release.parent != project / 'releases':
        raise ValueError('Expected versioned release in ~/starrynight-server/releases')
    manifest = verify_release(release)
    current = project / 'current'
    if not current.is_symlink():
        raise ValueError('Current version must be a symlink')
    previous = os.readlink(current)
    old = verify_release(current.resolve())
    # Updating the current link without restarting AI is safe only when its
    # source is identical. Do not silently extend this into a worker deploy.
    worker = lambda m: {k: v for k, v in m['files'].items() if k.startswith('services/')}
    if worker(old) != worker(manifest) and not args.restart_ai:
        raise ValueError('AI source changed; this Go-only updater cannot deploy it')
    ready()
    if args.check_only:
        print(json.dumps({'verified': True, 'release': release.name, 'active': True}))
        return
    backup = root / 'backups' / ('before-api-' + release.name)
    backup.mkdir(mode=0o700)
    (backup / 'previous.json').write_text(json.dumps({'current': previous, 'source_commit': manifest['source_commit']}) + '\n')
    env = environment(root / 'config/platform.env')
    run(root / 'postgres/bin/pg_dump', '-Fc', '--file', backup / 'platform.dump', env=pg_environment(env), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    dropin=Path.home()/'.config/systemd/user/starry-ai.service.d/goals.conf'
    previous_dropin=dropin.read_bytes() if dropin.exists() else None
    caddyfile=root/'config/Caddyfile'
    previous_caddy=caddyfile.read_bytes() if args.restart_ai else None
    if args.restart_ai:
        # No provider requests. SQLite's online backup is consistent while the
        # previous worker serves existing sessions; PG remains authoritative for goals.
        ai_config=json.loads((root/'config/ai-settings.json').read_text())
        state=Path(ai_config['data_dir'])/'state.sqlite3'
        with sqlite3.connect(state) as source,sqlite3.connect(backup/'ai-state.sqlite3') as target:
            source.backup(target)
    run(release / 'bin/starry-migrate', env=env)
    candidate = project / ('.api-current-' + release.name)
    candidate.symlink_to(release)
    os.replace(candidate, current)
    try:
        if args.restart_ai:
            run('systemctl','--user','stop','starry-ai')
            dropin.parent.mkdir(parents=True,exist_ok=True)
            dropin.write_text('[Service]\nEnvironment=STARRY_PLATFORM_INTERNAL_URL=http://127.0.0.1:8090\n')
            run('systemctl','--user','daemon-reload')
        run('systemctl', '--user', 'restart', 'starry-api')
        ready()
        # A later release switch must refresh the independently running admin
        # process too, so its frontend and backend come from the same release.
        if (Path.home()/'.config/systemd/user/starry-admin.service').exists():
            run('systemctl','--user','restart','starry-admin')
        if args.restart_ai:
            run('systemctl','--user','start','starry-ai')
            client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(60):
                try:
                    with client.open('http://127.0.0.1:8766/health',timeout=2) as response:
                        if response.status==200:break
                except OSError:pass
                time.sleep(.5)
            else:raise RuntimeError('AI worker did not become ready')
            edge=previous_caddy.decode()
            private='@private path /metrics /v1/ai/testing/* /v1/ai/admin/*'
            if '/internal/*' not in edge:
                if private not in edge:raise ValueError('Cannot safely add private goal route to current edge configuration')
                updated=edge.replace(private,'@private path /metrics /internal/* /v1/ai/testing/* /v1/ai/admin/*')
                candidate_edge=backup/'Caddyfile.candidate';candidate_edge.write_text(updated)
                run(root/'bin/caddy','validate','--config',candidate_edge,'--adapter','caddyfile',stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                (backup/'Caddyfile.previous').write_bytes(previous_caddy)
                caddyfile.write_text(updated)
                run('systemctl','--user','reload','starry-edge')
    except Exception:
        candidate.symlink_to(previous)
        os.replace(candidate, current)
        run('systemctl', '--user', 'restart', 'starry-api')
        if (Path.home()/'.config/systemd/user/starry-admin.service').exists():
            run('systemctl','--user','restart','starry-admin')
        if args.restart_ai:
            caddyfile.write_bytes(previous_caddy)
            run('systemctl','--user','reload','starry-edge')
            if previous_dropin is None:dropin.unlink(missing_ok=True)
            else:dropin.write_bytes(previous_dropin)
            run('systemctl','--user','daemon-reload')
            run('systemctl','--user','restart','starry-ai')
        raise
    print(json.dumps({'release': release.name, 'commit': manifest['source_commit'], 'ready': True, 'backup': str(backup), 'ai_restarted': args.restart_ai}))


if __name__ == '__main__':
    main()
