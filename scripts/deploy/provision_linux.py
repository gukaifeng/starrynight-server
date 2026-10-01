#!/usr/bin/env python3
"""Initialize an empty Linux deployment from a verified private Mac snapshot.

Only changes the destination user directory. Refuses to reinitialize a live
deployment; subsequent cutover sync must be performed explicitly by an operator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def write(path, text):
    path.write_text(text)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    root, snapshot = args.root.resolve(), args.snapshot.resolve()
    os.umask(0o077)
    marker = root / 'config/provisioned.json'
    if marker.exists() or (root / 'data/postgres/PG_VERSION').exists():
        raise SystemExit('Destination already initialized; refusing to replace data.')
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = snapshot / name
        if not path.resolve().is_relative_to(snapshot):
            raise ValueError('Snapshot path escapes backup directory')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected['sha256'] or path.stat().st_size != expected['bytes']:
            raise ValueError('Snapshot checksum mismatch: ' + name)
    print('Verified snapshot files:', len(manifest['files']), flush=True)
    for name in ('tls', 'config', 'data/ai', 'data/redis', 'data/socket', 'logs'):
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    tls = root / 'tls'
    run('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '3650', '-subj', '/CN=StarryNight internal CA', '-keyout', tls / 'ca.key', '-out', tls / 'ca.crt', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost', '-keyout', tls / 'server.key', '-out', tls / 'server.csr', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    write(tls / 'server.ext', 'subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\n')
    run('openssl', 'x509', '-req', '-in', tls / 'server.csr', '-CA', tls / 'ca.crt', '-CAkey', tls / 'ca.key', '-CAcreateserial', '-days', '825', '-extfile', tls / 'server.ext', '-out', tls / 'server.crt', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db_password, redis_password = secrets.token_hex(32), secrets.token_hex(32)
    write(root / 'config/pg-password', db_password)
    pg = root / 'postgres/bin'
    run(pg / 'initdb', '-D', root / 'data/postgres', '--username=starry', '--auth-local=trust', '--auth-host=scram-sha-256', '--pwfile=' + str(root / 'config/pg-password'), '--encoding=UTF8', '--locale=C.UTF-8', stdout=subprocess.DEVNULL)
    write(root / 'data/postgres/postgresql.conf', f"""listen_addresses = '127.0.0.1'
port = 55432
unix_socket_directories = '{root}/data/socket'
max_connections = 40
shared_buffers = 96MB
work_mem = 2MB
maintenance_work_mem = 32MB
ssl = on
ssl_cert_file = '{tls}/server.crt'
ssl_key_file = '{tls}/server.key'
password_encryption = 'scram-sha-256'
""")
    write(root / 'data/postgres/pg_hba.conf', 'local all all trust\nhostssl all all 127.0.0.1/32 scram-sha-256\n')
    write(root / 'config/redis.conf', f"""bind 127.0.0.1
port 0
tls-port 56379
tls-cert-file {tls}/server.crt
tls-key-file {tls}/server.key
tls-ca-cert-file {tls}/ca.crt
tls-auth-clients no
requirepass {redis_password}
dir {root}/data/redis
dbfilename dump.rdb
appendonly no
maxmemory 128mb
maxmemory-policy noeviction
daemonize no
logfile ""
""")
    shutil.copytree(snapshot / 'ai', root / 'data/ai', dirs_exist_ok=True)
    shutil.copy2(snapshot / 'redis.rdb', root / 'data/redis/dump.rdb')
    settings = json.loads((snapshot / 'source-ai-settings.json').read_text())
    settings.update(data_dir=str(root / 'data/ai'), enable_test_inspector=False)
    write(root / 'config/ai-settings.json', json.dumps(settings, indent=2) + '\n')
    database_url = f'postgres://starry:{db_password}@127.0.0.1:55432/starry?sslmode=verify-full&sslrootcert={tls}/ca.crt'
    values = {'STARRY_ENV': 'production', 'STARRY_LISTEN': '127.0.0.1:8090', 'ALLOW_TEST_GUEST': 'false',
              'DB_POOL_SIZE': '8', 'DATABASE_URL': database_url,
              'REDIS_URL': f'rediss://:{redis_password}@127.0.0.1:56379/0',
              'SSL_CERT_FILE': str(tls / 'ca.crt'), 'AI_UPSTREAM_URL': 'http://127.0.0.1:8766',
              'AI_SERVICE_TOKEN': settings['client_token']}
    write(root / 'config/platform.env', ''.join(f'{k}={v}\n' for k, v in values.items()))
    write(root / 'config/runtime-secrets.json', json.dumps({'postgres': db_password, 'redis': redis_password}) + '\n')
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    definitions = {
        'postgres': (f'{pg}/postgres -D {root}/data/postgres', '', ''),
        'redis': (f'{root}/bin/redis-server {root}/config/redis.conf', '', ''),
        'ai': (f'{root}/venv/bin/python -m uvicorn services.character_ai.app:create_app --factory --host 127.0.0.1 --port 8766 --no-access-log --log-level warning', '', f'Environment=STARRY_AI_CONFIG={root}/config/ai-settings.json\nEnvironment=PYTHONUNBUFFERED=1\n'),
        'api': (f'{root}/bin/starry-api', 'After=starry-postgres.service starry-redis.service starry-ai.service\nWants=starry-postgres.service starry-redis.service starry-ai.service\n', f'EnvironmentFile={root}/config/platform.env\n'),
    }
    for name, (command, dependencies, environment) in definitions.items():
        write(units / f'starry-{name}.service', f"""[Unit]
Description=StarryNight {name}
{dependencies}
[Service]
Type=simple
WorkingDirectory={root}/code
ExecStart={command}
{environment}Restart=on-failure
RestartSec=5
TimeoutStopSec=90
UMask=0077
NoNewPrivileges=true
LimitNOFILE=8192

[Install]
WantedBy=default.target
""")
    run('systemctl', '--user', 'daemon-reload')
    run('systemctl', '--user', 'enable', '--now', 'starry-postgres', 'starry-redis')
    import time
    env = os.environ | {'PGPASSWORD': db_password, 'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': str(tls / 'ca.crt')}
    for _ in range(30):
        if subprocess.run([str(pg / 'pg_isready'), '-h', '127.0.0.1', '-p', '55432'], env=env, stdout=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(1)
    run(pg / 'createdb', '-h', '127.0.0.1', '-p', '55432', '-U', 'starry', 'starry', env=env)
    run(pg / 'pg_restore', '-h', '127.0.0.1', '-p', '55432', '-U', 'starry', '-d', 'starry', '--exit-on-error', '--no-owner', snapshot / 'platform.dump', env=env)
    # Enable AOF only after the RDB has loaded, so an empty AOF cannot mask it.
    run(root / 'bin/redis-cli', '--tls', '--cacert', tls / 'ca.crt', '-p', '56379', 'CONFIG', 'SET', 'appendonly', 'yes', env=os.environ | {'REDISCLI_AUTH': redis_password}, stdout=subprocess.DEVNULL)
    run(root / 'bin/redis-cli', '--tls', '--cacert', tls / 'ca.crt', '-p', '56379', 'CONFIG', 'REWRITE', env=os.environ | {'REDISCLI_AUTH': redis_password}, stdout=subprocess.DEVNULL)
    run(root / 'bin/starry-migrate', env=os.environ | values)
    run('systemctl', '--user', 'enable', '--now', 'starry-ai', 'starry-api')
    write(marker, json.dumps({'snapshot': str(snapshot), 'snapshot_at': manifest['finished_at'], 'state': 'standby'}, indent=2) + '\n')
    print('Destination restored and services started. Source Mac untouched.')


if __name__ == '__main__':
    main()
