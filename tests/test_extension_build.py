"""Guard the extension packaging: build it and assert the zip is clean.

Runs the real `extension/build.py` into a temp dir, then checks that the archive
contains exactly the runtime whitelist, the manifest is at the root, and no
test/dev files leaked in. Pure stdlib; no browser needed.
"""

import importlib.util
import json
import os
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(REPO, "extension")
BUILD = os.path.join(EXT, "build.py")


def _load_build():
    spec = importlib.util.spec_from_file_location("ext_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_produces_clean_zip(tmp_path):
    build = _load_build()
    zip_path = build.build(str(tmp_path))
    assert os.path.exists(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert zf.testzip() is None  # integrity
        names = set(zf.namelist())

    # Exactly the runtime whitelist, nothing more.
    assert names == set(build.RUNTIME_FILES)
    assert "manifest.json" in names

    # No dev/test artifacts.
    forbidden = ("test", "node_modules", "build.py", "package.json", "make_icons", ".git")
    assert not [n for n in names if any(f in n for f in forbidden)]


def test_zip_filename_matches_manifest_version(tmp_path):
    build = _load_build()
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as fh:
        version = json.load(fh)["version"]
    zip_path = build.build(str(tmp_path))
    assert os.path.basename(zip_path) == f"amazon-sync-for-actual-extension-{version}.zip"
