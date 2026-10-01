#!/usr/bin/env python3
"""Refresh only the Linux standby from a verified snapshot; preserve rollback.

The source Mac is never contacted or stopped by this command. The public
business gate must stay closed. Original target databases and files are kept.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

from activate_standby_release import environment, pg_environment, run, standby, wait_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root, snapshot = args.root.resolve(), args.snapshot.resolve()
    standby(root)
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = snapshot / name
        if not path.resolve().is_relative_to(snapshot) or path.is_symlink():
            raise ValueError('Unsafe snapshot path')
        if path.stat().st_size != expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('Snapshot checksum mismatch: ' + name)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    candidate, previous = 'starry_stage_' + stamp, 'starry_previous_' + stamp
    backup = root / 'backups' / ('before-refresh-' + stamp)
    backup.mkdir(mode=0o700)
    env = environment(root / 'config/platform.env')
    uri = urlsplit(env['DATABASE_URL'])
    if uri.path != '/starry':
        raise ValueError('Refresh expects the dedicated starry database')
    def connection(name):
        return urlunsplit(uri._replace(path='/' + name))
    def pg_env(name):
        return pg_environment(env, database=name)
    def rename(old, new):
        run(root / 'postgres/bin/psql', '-X', '-v', 'ON_ERROR_STOP=1', '-c', f'ALTER DATABASE {old} RENAME TO {new}', env=pg_env('postgres'), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    # Restore and migrate a separate candidate while existing standby is up.
    run(root / 'postgres/bin/psql', '-X', '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE {candidate}', env=pg_env('postgres'), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    run(root / 'postgres/bin/pg_restore', '--dbname', candidate, '--exit-on-error', '--no-owner', snapshot / 'platform.dump', env=pg_env(candidate), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    migration = Path(__file__).resolve().parents[2] / 'bin/starry-migrate'
    run(migration, env=env | {'DATABASE_URL': connection(candidate)})
    shutil.copytree(snapshot / 'ai', backup / 'next-ai')
    (backup / 'next-redis').mkdir()
    shutil.copy2(snapshot / 'redis.rdb', backup / 'next-redis/dump.rdb')
    settings = json.loads((snapshot / 'source-ai-settings.json').read_text())
    if settings['client_token'] != env['AI_SERVICE_TOKEN']:
        raise ValueError('Worker credential changed; reconcile private gateway settings before refresh')
    settings.update(data_dir=str(root / 'data/ai'), enable_test_inspector=False)
    settings_path = root / 'config/ai-settings.json'
    shutil.copy2(settings_path, backup / 'ai-settings.json')
    marker = root / 'config/provisioned.json'
    shutil.copy2(marker, backup / 'provisioned.json')
    run(root / 'postgres/bin/pg_dump', '-Fc', '--file', backup / 'platform.dump', env=pg_env('starry'), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    moved, renamed = [], []
    def move(source, destination):
        source.rename(destination)
        moved.append((source, destination))
    try:
        run('systemctl', '--user', 'stop', 'starry-api', 'starry-ai', 'starry-redis')
        rename('starry', previous)
        renamed.append(('starry', previous))
        rename(candidate, 'starry')
        renamed.append((candidate, 'starry'))
        for name in ('ai', 'redis'):
            move(root / 'data' / name, backup / ('previous-' + name))
            move(backup / ('next-' + name), root / 'data' / name)
        settings_path.write_text(json.dumps(settings, indent=2) + '\n')
        run('systemctl', '--user', 'start', 'starry-redis', 'starry-ai', 'starry-api')
        wait_ready()
        standby(root)
        verification = Path(__file__).with_name('verify_linux.py')
        with (backup / 'verification.json').open('w') as log:
            run('python3', verification, '--root', root, '--snapshot', snapshot, stdout=log)
        marker.write_text(json.dumps({'snapshot': str(snapshot), 'snapshot_at': manifest['finished_at'], 'state': 'standby'}, indent=2) + '\n')
    except Exception:
        run('systemctl', '--user', 'stop', 'starry-api', 'starry-ai', 'starry-redis')
        for source, destination in reversed(moved):
            destination.rename(source)
        for old, new in reversed(renamed):
            rename(new, old)
        shutil.copy2(backup / 'ai-settings.json', settings_path)
        shutil.copy2(backup / 'provisioned.json', marker)
        run('systemctl', '--user', 'start', 'starry-redis', 'starry-ai', 'starry-api')
        raise
    print(json.dumps({'snapshot_at': manifest['finished_at'], 'backup': str(backup), 'previous_database': previous, 'state': 'standby', 'verified': True}))


if __name__ == '__main__':
    main()
