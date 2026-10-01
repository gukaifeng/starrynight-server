#!/usr/bin/env python3
"""Read-only online backup of the Mac deployment. Never stops source services.

The stores have independent snapshot times. A final quiesced snapshot is required
after the operator authorizes cutover. Output contains secrets and stays private.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
from contextlib import closing


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def environment(path):
    result = os.environ.copy()
    for line in path.read_text().splitlines():
        words = shlex.split(line)
        if len(words) == 2 and words[0] == 'export' and '=' in words[1]:
            key, value = words[1].split('=', 1)
            result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform-environment', type=Path, required=True)
    parser.add_argument('--ai-runtime', type=Path, required=True)
    parser.add_argument('--pg-bin', type=Path, default=Path('/opt/homebrew/opt/postgresql@17/bin'))
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    runtime = args.ai_runtime.resolve()
    settings = json.loads((runtime / 'settings.json').read_text())
    data = Path(settings['data_dir'])
    ai = output / 'ai'
    ai.mkdir(mode=0o700)
    manifest = {'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'source': 'running-mac', 'consistent_across_stores': False}
    with closing(sqlite3.connect((data / 'state.sqlite3').as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(ai / 'state.sqlite3')) as destination:
            source.backup(destination, pages=1024, sleep=0.01)
            result = destination.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                raise RuntimeError('SQLite integrity check failed')
            tables = [r[0] for r in destination.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            manifest['sqlite_rows'] = {table: destination.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
    for name in ('audio', 'voices', 'models'):
        if (data / name).exists():
            subprocess.run(['rsync', '-aL', str(data / name) + '/', str(ai / name) + '/'], check=True)
    manifest['ai_snapshot_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    env = environment(args.platform_environment)
    pg_bin = args.pg_bin
    subprocess.run([str(pg_bin / 'pg_dump'), '-h', '127.0.0.1', '-p', '55432', '-U', 'starry', '-d', 'starry', '-Fc', '--file', str(output / 'platform.dump')], env=env, check=True)
    manifest['postgres_snapshot_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    subprocess.run(['redis-cli', '-h', '127.0.0.1', '-p', '56379', '--rdb', str(output / 'redis.rdb')], env=env, check=True, stdout=subprocess.DEVNULL)
    manifest['redis_snapshot_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    shutil.copy2(runtime / 'settings.json', output / 'source-ai-settings.json')
    shutil.copy2(args.platform_environment, output / 'source-platform-environment')
    manifest['files'] = {str(path.relative_to(output)): {'bytes': path.stat().st_size, 'sha256': sha256(path)} for path in sorted(output.rglob('*')) if path.is_file()}
    manifest['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'snapshot': str(output), 'files': len(manifest['files']), 'sqlite_rows': manifest['sqlite_rows'], 'finished_at': manifest['finished_at']}, indent=2))


if __name__ == '__main__':
    main()
