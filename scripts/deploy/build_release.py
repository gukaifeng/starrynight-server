#!/usr/bin/env python3
"""Build an immutable Linux/amd64 release from a clean, committed checkout."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def main():
    root = Path(__file__).resolve().parents[2]
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root)
    if git('status', '--porcelain').strip():
        raise SystemExit('Commit reviewed source before building a release.')
    commit = git('rev-parse', 'HEAD').decode().strip()
    release = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + commit[:12]
    output = root / '.local/releases' / release
    output.mkdir(parents=True, mode=0o700)
    for name in git('ls-files', '-z').decode().split('\0'):
        if not name:
            continue
        source, target = root / name, output / name
        if source.is_symlink():
            raise SystemExit('Release source must not contain symlinks: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (output / 'bin').mkdir()
    env = os.environ | {'CGO_ENABLED': '0', 'GOOS': 'linux', 'GOARCH': 'amd64'}
    for name in ('api', 'migrate', 'publish-release', 'admin'):
        subprocess.run(['go', 'build', '-trimpath', '-ldflags=-s -w', '-o', str(output / 'bin' / ('starry-' + name)), './cmd/' + name], cwd=root, env=env, check=True)
    web=output/'admin-web'
    subprocess.run(['npm','ci','--no-fund','--no-audit'],cwd=web,check=True)
    subprocess.run(['npm','run','build'],cwd=web,check=True)
    # Dependencies are build inputs, not runtime release contents.
    shutil.rmtree(web/'node_modules')
    manifest = {'release': release, 'source_commit': commit, 'target': 'linux/amd64', 'files': {}}
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'][str(path.relative_to(output))] = {
                'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = output.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as stream:
        stream.add(output, arcname=release)
    print(json.dumps({'release': release, 'source_commit': commit, 'archive': str(archive), 'files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
