#!/usr/bin/env python3
"""Public HTTPS smoke test; creates/deletes only its own two random accounts.

No paid AI calls, no credentials or private response bodies in output.
"""
import json
import secrets
import urllib.error
import urllib.request


def main():
    base = 'https://39.105.116.74:8443'
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    accounts = []
    checks = 0

    def call(method, path, token=None, body=None, status=200):
        nonlocal checks
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with client.open(request, timeout=20) as response:
                code, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, data = error.code, error.read()
        if code != status:
            raise RuntimeError(method + ' ' + path + ' returned ' + str(code) + ', expected ' + str(status))
        checks += 1
        try:
            return json.loads(data)
        except ValueError:
            return None

    try:
        call('GET', '/health/ready')
        call('GET', '/v1/me', status=401)
        call('GET', '/v1/ai/status', status=401)
        call('GET', '/metrics', status=404)
        call('GET', '/docs', status=404)
        call('GET', '/openapi.json', status=404)
        roles = call('GET', '/v1/characters?limit=200')
        if len(roles['items']) < 41:
            raise RuntimeError('Imported character catalog is incomplete')
        for _ in range(2):
            password = secrets.token_urlsafe(24)
            session = call('POST', '/v1/auth/register', body={'username': 'upgrade_' + secrets.token_hex(8), 'password': password, 'display_name': 'Upgrade verification'})
            accounts.append({'session': session, 'password': password})
        owner, other = accounts
        session = owner['session']
        uid, old = session['user']['id'], session['token']
        call('PATCH', '/v1/me', old, {'expected_version': session['user']['version'], 'patch': {'id': other['session']['user']['id']}}, status=422)
        changed = call('PATCH', '/v1/me', old, {'expected_version': session['user']['version'], 'patch': {'display_name': 'Updated fixture', 'gender': 'other', 'bio': 'Verification only'}})
        renamed = call('POST', '/v1/me/username', old, {'username': 'upgrade_' + secrets.token_hex(8), 'password': owner['password'], 'expected_version': changed['version']})
        owner['session'] = renamed
        if renamed['user']['id'] != uid:
            raise RuntimeError('Renaming changed immutable account identity')
        call('GET', '/v1/me', old, status=401)
        token = renamed['token']
        call('POST', '/v1/me/feedback', token, {'category': 'suggestion', 'content': 'Automated upgrade verification; safe to ignore.'})
        if call('GET', '/v1/me/feedback', other['session']['token'])['items']:
            raise RuntimeError('Feedback crossed account boundary')
        call('PUT', '/v1/me/subscriptions/anime-airi', token)
        call('GET', '/v1/characters/anime-airi/preferences', token)
        call('GET', '/v1/me/export?limit=200', token)
        call('POST', '/v1/characters/anime-airi/download', status=401)
        call('POST', '/v1/characters/anime-airi/download', token, status=404)
        refreshed = call('POST', '/v1/me/sessions/revoke', token, {'password': owner['password']})
        owner['session'] = refreshed
        call('GET', '/v1/me', token, status=401)
        call('GET', '/v1/me', refreshed['token'])
    finally:
        cleanup_failures = 0
        for account in accounts:
            try:
                call('DELETE', '/v1/me', account['session']['token'], {'password': account['password'], 'confirmation': 'DELETE'})
            except Exception:
                cleanup_failures += 1
        if cleanup_failures:
            raise RuntimeError('Verification account cleanup needs attention; count=' + str(cleanup_failures))
    print(json.dumps({'origin': base, 'checks': checks, 'account_isolation': True, 'immutable_id': True, 'revocation': True, 'catalog': '41+', 'paid_calls': 0, 'temporary_accounts_removed': len(accounts)}))


if __name__ == '__main__':
    main()
