"""Private import checks; no production database or AI provider is involved."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("artwork_install", Path(__file__).resolve().parents[1] / "install_admin_artwork.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def package(tmp_path):
    root, source = tmp_path / "runtime", tmp_path / "source"
    (root / "config").mkdir(parents=True)
    (root / "config/provisioned.json").write_text('{"state":"active"}')
    (source / "objects").mkdir(parents=True)
    # Tests exercise the import transaction; Go validates actual JPEG content.
    content = b"private artwork fixture"
    digest = hashlib.sha256(content).hexdigest()
    relative = "objects/" + digest + ".jpg"
    (source / relative).write_bytes(content)
    item = {"path": relative, "sha256": digest, "bytes": len(content)}
    manifest = {"schema_version": 1, "characters": {"fixture": {"avatar": item, "cover": item}}}
    (source / "manifest.json").write_text(json.dumps(manifest))
    return root, source, relative


def test_install_checksums_and_preserves_previous_artwork(package):
    root, source, relative = package
    first = installer.install(source, root)
    assert first["characters"] == 1 and first["objects"] == 1
    second = installer.install(source, root)
    assert (root / "backups" / second["previous_backup"] / "record-images" / relative).read_bytes() == (source / relative).read_bytes()
    current = (root / "data/library/record-images/manifest.json").read_bytes()
    (source / relative).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        installer.install(source, root)
    assert (root / "data/library/record-images/manifest.json").read_bytes() == current


def test_failed_switch_restores_previous_artwork(package, monkeypatch):
    root, source, relative = package
    installer.install(source, root)
    original = Path.rename

    def fail_candidate(path, target):
        if path.name == "record-images" and path.parent.name.startswith(".artwork-install-"):
            raise OSError("fixture atomic switch failure")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail_candidate)
    with pytest.raises(OSError):
        installer.install(source, root)
    assert (root / "data/library/record-images" / relative).read_bytes() == (source / relative).read_bytes()
    assert not list((root / "data/library").glob(".artwork-install-*"))
