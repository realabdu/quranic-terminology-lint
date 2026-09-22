import json
from pathlib import Path
import shutil
import subprocess
import sys
import runpy

import pytest

from quranic_terminology_lint.snapshot import VENDOR, validate

ROOT = Path(__file__).resolve().parents[1]


def test_import_checks_and_failure_preserve_bundle(tmp_path, monkeypatch):
    repo = tmp_path / "lint"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", "*.egg-info", "dist", "build"))
    source = tmp_path / "source"
    skill = source / "skills/quranic-terminology"
    shutil.copytree(VENDOR, skill)
    shutil.copy(skill / "LICENSE", source / "LICENSE")
    shutil.copytree(skill / "LICENSES", source / "LICENSES")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    for args in (["config", "user.email", "test@example.invalid"], ["config", "user.name", "Test"],
                 ["remote", "add", "origin", "https://example.invalid/source"], ["add", "."], ["commit", "-m", "Snapshot"]):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    bundled = repo / "src/quranic_terminology_lint/vendor"
    def run(*args):
        return subprocess.run([sys.executable, str(repo / "tools/import_snapshot.py"), str(source), *args], capture_output=True)
    before = (bundled / "provenance.json").read_bytes()
    assert run("--check").returncode == 1
    assert (bundled / "provenance.json").read_bytes() == before
    assert run().returncode == 0
    validate(bundled)
    assert run("--check").returncode == 0
    valid = (bundled / "provenance.json").read_bytes()
    assert not json.loads(valid)["dirty"]
    # A failed installation must restore the existing snapshot, not delete it
    # when the temporary staging directory is cleaned up.
    importer = runpy.run_path(str(repo / "tools/import_snapshot.py"))["main"]
    with monkeypatch.context() as patch:
        patch.setitem(importer.__globals__, "VENDOR", bundled)
        patch.setattr(sys, "argv", ["import_snapshot.py", str(source)])
        rename = Path.rename
        def fail_install(path, target):
            if path.name == "vendor" and target == bundled:
                raise OSError("installation failed")
            return rename(path, target)
        patch.setattr(Path, "rename", fail_install)
        with pytest.raises(OSError, match="installation failed"):
            importer()
    assert (bundled / "provenance.json").read_bytes() == valid
    validate(bundled)
    registry = skill / "data/registries/qiraat.tsv"
    original_registry = registry.read_bytes()
    registry.write_text("broken table")
    assert run().returncode == 2
    assert (bundled / "provenance.json").read_bytes() == valid
    registry.write_bytes(original_registry)
    (skill / "data/terminology.json").write_text("{}")
    assert run().returncode == 2
    assert (bundled / "provenance.json").read_bytes() == valid
    validate(bundled)
