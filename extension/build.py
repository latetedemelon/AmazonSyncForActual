#!/usr/bin/env python3
"""Package the extension into an installable ZIP.

Uses a strict *whitelist* of runtime files so no test fixtures, dev tooling or
anything sensitive can leak into the package. The manifest is placed at the
archive root (required by the Chrome Web Store and for unpacked loading).

Usage:
    python3 build.py                # -> dist/amazon-sync-for-actual-extension-<version>.zip
    python3 build.py --out /tmp     # choose output directory
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Exactly the files the extension needs at runtime. Anything not listed here is
# intentionally excluded (test/, node_modules/, package.json, make_icons.py, …).
RUNTIME_FILES = [
    "manifest.json",
    "content.js",
    "lib/parse.js",
    "lib/diagnostics.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "icons/icon16.png",
    "icons/icon48.png",
    "icons/icon128.png",
]


def _fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"build: error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def validate_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("manifest_version") != 3:
        _fail("manifest_version must be 3")
    for key in ("name", "version", "content_scripts"):
        if key not in manifest:
            _fail(f"manifest missing required key: {key}")
    # Every script the manifest references must be in our runtime whitelist.
    referenced = set()
    for cs in manifest.get("content_scripts", []):
        referenced.update(cs.get("js", []))
    action = manifest.get("action", {})
    if action.get("default_popup"):
        referenced.add(action["default_popup"])
    missing = [r for r in referenced if r not in RUNTIME_FILES]
    if missing:
        _fail(f"manifest references files not in the package whitelist: {missing}")
    return manifest


def build(out_dir: str) -> str:
    manifest_path = os.path.join(HERE, "manifest.json")
    if not os.path.exists(manifest_path):
        _fail("manifest.json not found; run from the extension/ directory")
    manifest = validate_manifest(manifest_path)
    version = manifest["version"]

    # Confirm every whitelisted file exists before zipping.
    for rel in RUNTIME_FILES:
        if not os.path.exists(os.path.join(HERE, rel)):
            _fail(f"required file missing: {rel}")

    os.makedirs(out_dir, exist_ok=True)
    zip_name = f"amazon-sync-for-actual-extension-{version}.zip"
    zip_path = os.path.join(out_dir, zip_name)

    # Deterministic archive: sorted, fixed timestamps.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(RUNTIME_FILES):
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(HERE, rel), "rb") as handle:
                zf.writestr(info, handle.read())

    size = os.path.getsize(zip_path)
    with open(zip_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()

    print(f"Built {zip_path}")
    print(f"  files:  {len(RUNTIME_FILES)}")
    print(f"  size:   {size:,} bytes")
    print(f"  sha256: {digest}")
    print("\nContents:")
    for rel in sorted(RUNTIME_FILES):
        print(f"  {rel}")
    return zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Package the browser extension into a ZIP.")
    parser.add_argument("--out", default=os.path.join(HERE, "dist"),
                        help="Output directory (default: extension/dist).")
    args = parser.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
