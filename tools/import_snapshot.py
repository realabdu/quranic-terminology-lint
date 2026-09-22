"""Import trusted upstream code/data; use --check to validate without replacing."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quranic_terminology_lint.snapshot import VENDOR, validate


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, help="trusted local guidelines checkout")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    source = args.source.resolve()
    skill = source / "skills/quranic-terminology"
    # Stage on the destination filesystem so installation only needs renames.
    with tempfile.TemporaryDirectory(prefix="terminology-import-", dir=VENDOR.parent) as temporary:
        candidate = Path(temporary) / "vendor"
        resources = [(skill / "scripts/audit_terminology.py", "scripts/audit_terminology.py"),
                     (skill / "data/terminology.json", "data/terminology.json"),
                     (source / "LICENSE", "LICENSE"),
                     (source / "LICENSES/CC-BY-4.0.txt", "LICENSES/CC-BY-4.0.txt")]
        resources += [(p, f"data/registries/{p.name}") for p in sorted((skill / "data/registries").glob("*.tsv"))]
        hashes, sources = {}, {}
        for original, relative in resources:
            payload = original.read_bytes()
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            hashes[relative] = hashlib.sha256(payload).hexdigest()
            sources[relative] = str(original.relative_to(source))
        _, data = validate(candidate, integrity=False)
        dirty = bool(git(source, "status", "--porcelain", "--", "."))
        provenance = {
            "source_repository": "https://github.com/quran-ws/docs",
            "containing_repository_remote": git(source, "remote", "get-url", "origin"),
            "containing_commit": git(source, "rev-parse", "HEAD"),
            "dirty": dirty, "origin": "local-uncommitted" if dirty else "local-committed",
            "dictionary_snapshot": data.get("version", {}).get("snapshot"),
            "source_paths": sources, "sha256": hashes,
        }
        (candidate / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        validate(candidate)
        if args.check:
            same = VENDOR.exists() and (VENDOR / "provenance.json").read_bytes() == (candidate / "provenance.json").read_bytes()
            if VENDOR.exists():
                validate(VENDOR)
            print("snapshot matches" if same else "valid candidate differs from bundled snapshot")
            return 0 if same else 1
        # Candidate validation is complete before touching the existing bundle.
        backup = Path(temporary) / "old"
        if VENDOR.exists():
            VENDOR.rename(backup)
        try:
            candidate.rename(VENDOR)
        except BaseException:
            if backup.exists():
                backup.rename(VENDOR)
            raise
        print(f"imported {len(hashes)} resources ({provenance['origin']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"snapshot import failed: {exc}", file=sys.stderr)
        sys.exit(2)
