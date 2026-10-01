#!/usr/bin/env python3
"""Open the prepared cloud gateway after explicit user cutover authorization.

Keeps the existing cloud data, backs up the standby configuration, validates
Caddy, reloads it, and records active state. Does not touch the Mac deployment.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('Caddyfile.active'))
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root
    state_path = root / 'config/provisioned.json'
    state = json.loads(state_path.read_text())
    if state.get('state') != 'standby':
        raise SystemExit('Only a provisioned standby can be activated.')
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in ('http://127.0.0.1:8090/health/ready', 'http://127.0.0.1:8766/health'):
        with client.open(url, timeout=15) as response:
            assert response.status == 200
    caddy = str(root / 'bin/caddy')
    subprocess.run([caddy, 'validate', '--config', str(args.config), '--adapter', 'caddyfile'], check=True)
    timestamp = datetime.now(timezone.utc)
    backup = root / 'backups' / ('before-cutover-' + timestamp.strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True)
    live = root / 'config/Caddyfile'
    old_config, old_state = live.read_bytes(), state_path.read_bytes()
    (backup / 'Caddyfile').write_bytes(old_config)
    (backup / 'provisioned.json').write_bytes(old_state)
    candidate = args.config.read_bytes()
    temporary = live.with_suffix('.candidate')
    temporary.write_bytes(candidate)
    try:
        temporary.replace(live)
        subprocess.run(['systemctl', '--user', 'reload', 'starry-edge'], check=True)
        # TLS verification includes the IP SAN and the system trust store.
        with client.open('https://39.105.116.74:8443/v1/capabilities', timeout=20) as response:
            assert response.status == 200
            assert json.load(response)['test_guest'] is False
        state.update(state='active', activated_at=timestamp.isoformat(),
                     cutover_policy='existing_cloud_data_no_final_sync',
                     active_config_sha256=hashlib.sha256(candidate).hexdigest())
        temporary_state = state_path.with_suffix('.candidate')
        temporary_state.write_text(json.dumps(state, indent=2) + '\n')
        temporary_state.replace(state_path)
    except Exception:
        temporary.write_bytes(old_config)
        temporary.replace(live)
        state_path.write_bytes(old_state)
        subprocess.run(['systemctl', '--user', 'reload', 'starry-edge'], check=True)
        raise
    print(json.dumps({'state': 'active', 'activated_at': state['activated_at'],
                      'snapshot_at': state['snapshot_at'], 'backup': str(backup),
                      'paid_provider_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
