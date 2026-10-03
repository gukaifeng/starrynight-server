"""Open one authenticated, allowlisted inspector route; keep other test routes private."""
import argparse
import os
from pathlib import Path
import subprocess
import time

MARKER = "\t@private path /metrics /internal/* /v1/ai/testing/* /v1/ai/admin/*"
BLOCK = '''\t# Only the authenticated API decides inspector account access.
\t@inspector {
\t\tmethod POST
\t\tpath_regexp inspector ^/v1/ai/testing/characters/[a-zA-Z0-9_-]+/inspector$
\t}
\thandle @inspector {
\t\treverse_proxy 127.0.0.1:8090
\t}
'''

def update(text):
    if "path_regexp inspector ^/v1/ai/testing/characters/" in text:
        return text
    if text.count(MARKER) != 1:
        raise ValueError("Expected exactly one existing private-route matcher")
    return text.replace(MARKER, BLOCK + MARKER, 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "app")
    args = parser.parse_args()
    live = args.root / "config/Caddyfile"
    old = live.read_text()
    new = update(old)
    if old == new:
        print("Inspector edge route already present")
        return
    backup = args.root / "backups" / ("inspector-edge-" + time.strftime("%Y%m%dT%H%M%S"))
    backup.mkdir(mode=0o700)
    (backup / "Caddyfile.previous").write_text(old)
    candidate = backup / "Caddyfile.candidate"
    candidate.write_text(new)
    subprocess.run([str(args.root / "bin/caddy"), "validate", "--config", str(candidate), "--adapter", "caddyfile"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        replacement = live.with_suffix(".candidate")
        replacement.write_text(new)
        replacement.chmod(live.stat().st_mode & 0o777)
        os.replace(replacement, live)
        subprocess.run(["systemctl", "--user", "reload", "starry-edge"], check=True)
    except Exception:
        live.write_text(old)
        subprocess.run(["systemctl", "--user", "reload", "starry-edge"], check=True)
        raise
    print("Validated and reloaded inspector edge route; API/worker authorization retained")

if __name__ == "__main__":
    main()
