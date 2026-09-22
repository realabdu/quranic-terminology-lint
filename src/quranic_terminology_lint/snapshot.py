"""Load and verify the unchanged upstream resources."""
import hashlib
import json
from pathlib import Path
import types

VENDOR = Path(__file__).parent / "vendor"


def load_engine(root=VENDOR):
    path = root / "scripts/audit_terminology.py"
    # Execute the verified source, never a stale bytecode cache.
    module = types.ModuleType("_quranic_upstream_audit")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def validate(root=VENDOR, integrity=True):
    if integrity:
        manifest = json.loads((root / "provenance.json").read_text())
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and p.name != "provenance.json"}
        if actual != set(manifest["sha256"]):
            raise ValueError("snapshot file inventory differs from provenance")
        for relative, expected in manifest["sha256"].items():
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError(f"snapshot hash mismatch: {relative}")
    engine = load_engine(root)
    data = engine.load(str(root / "data/terminology.json"))
    if not data["concepts"] or not data["aliases"]:
        raise ValueError("snapshot must contain concepts and aliases")
    registries = list((root / "data/registries").glob("*.tsv"))
    if not registries:
        raise ValueError("snapshot has no registries")
    for registry in registries:
        lines = registry.read_text(encoding="utf-8").splitlines()
        headers = [line for line in lines if line.startswith("#") and "\t" in line]
        rows = [line for line in lines if line.strip() and not line.startswith("#")]
        if not headers or not rows or any(len(row.split("\t")) != len(headers[-1].split("\t")) for row in rows):
            raise ValueError(f"invalid registry table: {registry.name}")
    for entry in data["concepts"].values():
        for key in ("code", "display", "status"):
            if not isinstance(entry[key], str):
                raise ValueError(f"invalid concept field: {key}")
    index = engine.build_index(data, [])
    for _, concept, _ in index.values():
        engine.name_of(data, concept)
    for kind in data.get("registry_members", {}):
        registry = data["concepts"].get(kind, {}).get("registry")
        if registry and not (root / "data/registries" / f"{registry}.tsv").is_file():
            raise ValueError(f"missing registry: {registry}")
    return engine, data
