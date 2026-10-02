#!/usr/bin/env python3
"""Export existing Xcode artwork to a private, standalone admin media package.

Explicit inputs only; no AI calls, database edits or publication. Install the
output under <runtime>/data/library/record-images, not the public web directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageOps


def asset_file(name, roots):
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        return None
    for root in roots:
        folder = root / (name + ".imageset")
        if not (folder / "Contents.json").is_file():
            continue
        images = json.loads((folder / "Contents.json").read_text())["images"]
        for image in images:
            filename = image.get("filename")
            if filename and Path(filename).name == filename:
                candidate = folder / filename
                if candidate.is_file() and not candidate.is_symlink():
                    return candidate
    return None


def render(source, variant, head=None):
    import io

    with Image.open(source) as raw:
        if raw.width * raw.height > 40_000_000:
            raise ValueError("Source artwork dimensions are too large")
        image = ImageOps.exif_transpose(raw).convert("RGBA")
        background = Image.new("RGBA", image.size, (18, 23, 36, 255))
        background.alpha_composite(image)
        image = background.convert("RGB")
        if variant == "avatar":
            if head:
                w, h = image.size
                x, y = head["x"] * w, head["y"] * h
                width, height = head["width"] * w, head["height"] * h
                side = min(max(width, height) * 1.18, w, h)
                left = min(max(0, x + width / 2 - side / 2), w - side)
                top = min(max(0, y + height / 2 - side / 2), h - side)
                image = image.crop((left, top, left + side, top + side))
            image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS, centering=(0.5, 0.25))
        else:
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return output.getvalue(), image.size


def export(catalog, covers, roots, output):
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    objects = output / "objects"
    objects.mkdir(mode=0o700, exist_ok=True)
    definitions = {entry["runtimeID"]: entry for entry in covers["covers"]}
    manifest = {"schema_version": 1, "characters": {}}
    missing = []
    for character in catalog["characters"]:
        identity, display = character["id"], character["display"]
        cover = definitions.get(identity, {})
        cover_name = cover.get("asset", display["thumbnail"])
        cover_source = asset_file(cover_name, roots) or asset_file(display["thumbnail"], roots)
        avatar_name = cover.get("avatar", "")
        avatar_source = asset_file(avatar_name, roots)
        head = None
        if not avatar_source:
            head = cover.get("headBounds")
            avatar_source = cover_source
        if not cover_source or not avatar_source:
            missing.append(identity)
            continue
        artwork = {}
        for variant, source in (("avatar", avatar_source), ("cover", cover_source)):
            content, size = render(source, variant, head if variant == "avatar" else None)
            digest = hashlib.sha256(content).hexdigest()
            relative = "objects/" + digest + ".jpg"
            target = output / relative
            if target.exists() and target.read_bytes() != content:
                raise ValueError("Content-addressed artwork collision")
            target.write_bytes(content)
            target.chmod(0o600)
            artwork[variant] = {"path": relative, "sha256": digest, "bytes": len(content),
                                "width": size[0], "height": size[1],
                                "source_asset": avatar_name or cover_name if variant == "avatar" else cover_name}
        manifest["characters"][identity] = artwork
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(output / "manifest.json")
    return {"characters": len(manifest["characters"]), "missing": missing,
            "objects": len(list(objects.glob("*.jpg"))),
            "bytes": sum(path.stat().st_size for path in objects.glob("*.jpg"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--covers", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = export(json.loads(args.catalog.read_text()), json.loads(args.covers.read_text()),
                    args.asset_root, args.output)
    print(json.dumps(result))
    if result["missing"]:
        raise SystemExit("Missing artwork; inspect the report before installing")


if __name__ == "__main__":
    main()
