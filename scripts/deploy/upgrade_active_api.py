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
    if worker(old) != worker(manifest):
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
    run(release / 'bin/starry-migrate', env=env)
    candidate = project / ('.api-current-' + release.name)
    candidate.symlink_to(release)
    os.replace(candidate, current)
    try:
        run('systemctl', '--user', 'restart', 'starry-api')
        ready()
    except Exception:
        candidate.symlink_to(previous)
        os.replace(candidate, current)
        run('systemctl', '--user', 'restart', 'starry-api')
        raise
    print(json.dumps({'release': release.name, 'commit': manifest['source_commit'], 'ready': True, 'backup': str(backup), 'ai_restarted': False}))


if __name__ == '__main__':
    main()
