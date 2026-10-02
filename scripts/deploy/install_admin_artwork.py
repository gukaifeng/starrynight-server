#!/usr/bin/env python3
"""Install an explicitly exported artwork package into private admin storage.

Existing artwork is preserved; catalog records, App assets and AI data are not
changed. Serializes with control-room writes and maintenance jobs.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


def install(source, root):
    source, root = source.resolve(), root.resolve()
    if json.loads((root / "config/provisioned.json").read_text()).get("state") != "active":
        raise ValueError("Requires an active server runtime")
    manifest_file = source / "manifest.json"
    if manifest_file.is_symlink() or manifest_file.stat().st_size > 4 << 20:
        raise ValueError("Invalid artwork manifest")
    manifest = json.loads(manifest_file.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("characters"), dict):
        raise ValueError("Unsupported artwork package")
    objects = {}
    for identity, variants in manifest["characters"].items():
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("Invalid character identity")
        for variant, item in variants.items():
            relative = item["path"]
            if variant not in ("avatar", "cover") or not re.fullmatch(r"objects/[a-f0-9]{64}\.jpg", relative):
                raise ValueError("Invalid artwork path")
            path = source / relative
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise ValueError("Invalid artwork file")
            if not 0 < path.stat().st_size <= 8 << 20 or path.stat().st_size != item["bytes"]:
                raise ValueError("Artwork size mismatch")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"] or relative != "objects/" + digest + ".jpg":
                raise ValueError("Artwork checksum mismatch")
            objects[relative] = path
    library = root / "data/library"
    target = library / "record-images"
    if any(path.is_symlink() for path in (root / "data", library, target)):
        raise ValueError("Private artwork directories cannot be symlinks")
    if source == target.resolve():
        raise ValueError("Source cannot be the installed artwork directory")
    lock = root / "data/admin/operations.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)
    backup = None
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix=".artwork-install-", dir=library) as stage:
            candidate = Path(stage) / "record-images"
            (candidate / "objects").mkdir(mode=0o700, parents=True)
            for relative, path in objects.items():
                shutil.copyfile(path, candidate / relative)
                (candidate / relative).chmod(0o600)
            (candidate / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            (candidate / "manifest.json").chmod(0o600)
            if target.exists():
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = root / "backups" / ("before-artwork-" + stamp + "-" + uuid.uuid4().hex[:6])
                backup.mkdir(mode=0o700, parents=True)
                target.rename(backup / "record-images")
            try:
                candidate.rename(target)
            except BaseException:
                if backup:
                    (backup / "record-images").rename(target)
                raise
    return {"installed": True, "characters": len(manifest["characters"]), "objects": len(objects),
            "bytes": sum(p.stat().st_size for p in objects.values()), "previous_backup": backup.name if backup else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(install(args.source, args.root)))


if __name__ == "__main__":
    main()
