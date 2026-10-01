#!/usr/bin/env python3
"""Verify restored data and production API without invoking paid providers.

Creates two uniquely named smoke accounts and removes only those accounts via
the normal API. Credentials and conversation contents never appear in output.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import urllib.error
import urllib.request


def copy_tables(sql):
    result, table, rows, columns = {}, None, [], []
    for line in sql.splitlines():
        if line.startswith('COPY ') and line.endswith(' FROM stdin;'):
            table, rows = line, []
            columns = line.split('(', 1)[1].split(')', 1)[0].split(', ')
        elif table and line == '\\.':
            result[table] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()}
            if table.startswith('COPY public.goose_db_version '):
                result[table]['migration_rows'] = rows.copy()
            table = None
        elif table:
            fields = line.split('\t')
            for index, column in enumerate(columns):
                if (column.endswith('_at') or column == 'tstamp') and fields[index] != '\\N':
                    value = datetime.fromisoformat(fields[index])
                    if value.tzinfo is not None:
                        fields[index] = value.astimezone(timezone.utc).isoformat()
            rows.append('\t'.join(fields))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    root, snapshot = args.root, args.snapshot
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    credentials = json.loads((root / 'config/runtime-secrets.json').read_text())
    pg = root / 'postgres/bin'
    env = os.environ | {'PGPASSWORD': credentials['postgres'], 'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': str(root / 'tls/ca.crt')}
    original = subprocess.check_output([str(pg / 'pg_restore'), '--data-only', '--file=-', str(snapshot / 'platform.dump')], text=True)
    restored = subprocess.check_output([str(pg / 'pg_dump'), '-h', '127.0.0.1', '-p', '55432', '-U', 'starry', '-d', 'starry', '--data-only'], env=env, text=True)
    expected, actual = copy_tables(original), copy_tables(restored)
    # The deployed API applies the repository's additive migration 00006 to
    # the Mac snapshot at version 5. Preserve every preexisting migration row
    # and account row; permit only its one empty table and version record.
    goose = next(k for k in expected if k.startswith('COPY public.goose_db_version '))
    if expected[goose] != actual[goose]:
        previous = set(expected[goose]['migration_rows'])
        following = set(actual[goose]['migration_rows'])
        added = following - previous
        assert previous <= following and len(added) == 1
        assert next(iter(added)).split('\t')[1:3] == ['6', 't']
        extra = set(actual) - set(expected)
        assert len(extra) == 1
        added_table = extra.pop()
        assert added_table.startswith('COPY public.conversation_resets ') and actual[added_table]['rows'] == 0
        business_actual = {k: v for k, v in actual.items() if k != goose and k != added_table}
    else:
        business_actual = {k: v for k, v in actual.items() if k != goose}
    assert expected and {k: v for k, v in expected.items() if k != goose} == business_actual, 'PostgreSQL restored data mismatch'
    report = {'postgres_tables': len(actual), 'postgres_rows': {k.split()[1]: v['rows'] for k, v in actual.items()}}
    with closing(sqlite3.connect((root / 'data/ai/state.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        rows = {table: db.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in manifest['sqlite_rows']}
        assert rows == manifest['sqlite_rows'], 'AI restored row count mismatch'
    report['sqlite_rows'] = rows
    count = 0
    for name, expected_file in manifest['files'].items():
        if name.startswith(('ai/audio/', 'ai/voices/', 'ai/models/')):
            path = root / 'data' / name
            assert path.stat().st_size == expected_file['bytes']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_file['sha256']
            count += 1
    report['verified_media_files'] = count
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(method, path, body=None, token='', expected_status=200):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request('http://127.0.0.1:8090' + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        try:
            response = client.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = response.read()
            assert response.status == expected_status, f'{method} {path}: expected {expected_status}, received {response.status}'
            try:
                return json.loads(payload) if payload else None
            except json.JSONDecodeError:
                return payload.decode()

    assert request('GET', '/health/ready')['status'] == 'ready'
    request('GET', '/v1/me', expected_status=401)
    request('POST', '/v1/auth/guest', expected_status=404)
    assert request('GET', '/v1/capabilities')['test_guest'] is False
    accounts = []
    try:
        for _ in range(2):
            username, password = 'migration_' + secrets.token_hex(8), secrets.token_urlsafe(24)
            session = request('POST', '/v1/auth/register', {'username': username, 'password': password, 'display_name': 'Migration verification'})
            accounts.append((session['token'], password))
        first, second = accounts[0][0], accounts[1][0]
        document = request('GET', '/v1/me/settings', token=first)
        version = document['version']
        request('PATCH', '/v1/me/settings', {'expected_version': version, 'patch': {'migration_probe': 'isolated'}}, first)
        other = request('GET', '/v1/me/settings', token=second)
        assert 'migration_probe' not in other.get('data', {})
        request('PATCH', '/v1/me/settings', {'expected_version': version, 'patch': {'migration_probe': 'conflict'}}, first, expected_status=409)
        status = request('GET', '/v1/ai/status', token=first)
        assert status['ready'] and all(status['voices'].values())
        report['approved_character_voices'] = len(status['voices'])
        request('POST', '/v1/ai/testing/characters/anime-kipfel/inspector', {}, first, expected_status=404)
        request('GET', '/v1/ai/admin/usage', token=first, expected_status=404)
        report['api_checks'] = ['readiness', 'authentication', 'guest_disabled', 'registration', 'account_isolation', 'optimistic_conflict', 'private_ai_proxy', 'inspector_blocked', 'admin_blocked']
    finally:
        for token, password in accounts:
            request('DELETE', '/v1/me', {'password': password, 'confirmation': 'DELETE'}, token)
            request('GET', '/v1/me', token=token, expected_status=401)
    report['paid_provider_calls'] = 0
    report['smoke_accounts_removed'] = len(accounts)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
