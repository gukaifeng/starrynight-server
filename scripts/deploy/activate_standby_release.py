#!/usr/bin/env python3
"""Activate verified code on the Linux standby; never opens business traffic.

Keeps the prior units/release and a PostgreSQL backup. Application state and
credentials stay under --root, independently of the versioned source tree.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlsplit


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def environment(path):
    env = os.environ.copy()
    for line in path.read_text().splitlines():
        words = shlex.split(line)
        if len(words) == 1 and '=' in words[0]:
            key, value = words[0].split('=', 1)
            env[key] = value
    return env


def pg_environment(env, database=None):
    # pg_dump/psql do not expand a URI supplied through PGDATABASE. Pass its
    # individual libpq settings in the environment, keeping secrets off argv.
    uri = urlsplit(env['DATABASE_URL'])
    query = parse_qs(uri.query)
    result = env | {
        'PGDATABASE': database or unquote(uri.path.lstrip('/')),
        'PGHOST': uri.hostname, 'PGPORT': str(uri.port or 5432),
        'PGUSER': unquote(uri.username), 'PGPASSWORD': unquote(uri.password),
        'PGSSLMODE': query.get('sslmode', ['verify-full'])[0]}
    cert = query.get('sslrootcert', [env.get('SSL_CERT_FILE', '')])[0]
    if cert:
        result['PGSSLROOTCERT'] = cert
    return result


def standby(root):
    if platform.system() != 'Linux':
        raise SystemExit('This command only operates on the Linux destination.')
    marker = json.loads((root / 'config/provisioned.json').read_text())
    if marker.get('state') != 'standby':
        raise SystemExit('Destination is not marked standby; refusing activation.')
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        client.open('https://39.105.116.74:8443/', timeout=15)
    except urllib.error.HTTPError as error:
        body = json.loads(error.read())
        if error.code == 503 and 'standby' in json.dumps(body).lower():
            return
    raise SystemExit('Public business gate is not in standby mode.')


def wait_ready():
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            for url in ('http://127.0.0.1:8090/health/ready', 'http://127.0.0.1:8766/health'):
                with client.open(url, timeout=3) as response:
                    if response.status != 200:
                        raise RuntimeError('Not ready')
            return
        except (OSError, RuntimeError):
            time.sleep(1)
    raise RuntimeError('Standby services did not become ready within 120 seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root, release = args.root.resolve(), args.release.resolve()
    standby(root)
    manifest = json.loads((release / 'release.json').read_text())
    for name, expected in manifest['files'].items():
        path = release / name
        if not path.resolve().is_relative_to(release) or path.is_symlink():
            raise ValueError('Unsafe release path')
        if path.stat().st_size != expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('Release checksum mismatch: ' + name)
    project = release.parent.parent
    if release.parent.name != 'releases' or project.name != 'starrynight-server':
        raise ValueError('Expected ~/starrynight-server/releases/<release>')
    units = Path.home() / '.config/systemd/user'
    backup = root / 'backups' / ('before-release-' + release.name)
    backup.mkdir(mode=0o700)
    old = {name: (units / ('starry-' + name + '.service')).read_text() for name in ('api', 'ai')}
    for name, contents in old.items():
        (backup / ('starry-' + name + '.service')).write_text(contents)
    env = environment(root / 'config/platform.env')
    run(root / 'postgres/bin/pg_dump', '-Fc', '--file', backup / 'platform.dump', env=pg_environment(env), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    # Migrations are additive; never run Goose down during rollback.
    run(release / 'bin/starry-migrate', env=env)
    current = project / 'current'
    previous = os.readlink(current) if current.is_symlink() else None
    (backup / 'previous.json').write_text(json.dumps({'current': previous, 'source_commit': manifest['source_commit']}) + '\n')
    link = project / ('.current-' + release.name)
    link.symlink_to(release)
    os.replace(link, current)
    try:
        for name, contents in old.items():
            lines = []
            for line in contents.splitlines():
                if line.startswith('WorkingDirectory='):
                    line = 'WorkingDirectory=' + str(current)
                elif name == 'api' and line.startswith('ExecStart='):
                    line = 'ExecStart=' + str(current / 'bin/starry-api')
                lines.append(line)
            (units / ('starry-' + name + '.service')).write_text('\n'.join(lines) + '\n')
        run('systemctl', '--user', 'daemon-reload')
        run('systemctl', '--user', 'restart', 'starry-ai', 'starry-api')
        wait_ready()
        standby(root)
    except Exception:
        for name, contents in old.items():
            (units / ('starry-' + name + '.service')).write_text(contents)
        if previous is None:
            current.unlink()
        else:
            link.symlink_to(previous)
            os.replace(link, current)
        run('systemctl', '--user', 'daemon-reload')
        run('systemctl', '--user', 'restart', 'starry-ai', 'starry-api')
        raise
    print(json.dumps({'release': release.name, 'commit': manifest['source_commit'], 'state': 'standby', 'ready': True, 'backup': str(backup)}))


if __name__ == '__main__':
    main()
