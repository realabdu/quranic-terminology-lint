"""File selection and failure policy around the upstream audit engine."""
import argparse
from collections import Counter
import io
import json
import os
from importlib.metadata import version
from pathlib import Path
import sys

from .snapshot import validate
from .context import mask_references, prepare_index


def diagnostic(finding):
    times = f" ×{finding['count']}" if finding["count"] > 1 else ""
    return (f"{finding['file']}:{finding['line']}: {finding['severity']} [{finding['rule']}] "
            f"{finding['found']!r} → {finding['canonical']!r} in {finding['identifier']!r}{times} "
            f"({finding['display']}) [{finding['layer']}]")


def compact_report(findings, summary, limit):
    groups = Counter()
    for finding in findings:
        if not finding["known"]:
            key = tuple(finding[k] for k in ("severity", "found", "canonical"))
            groups[key] += finding["count"]
    shown = sorted(groups, key=lambda k: (k[0] != "error", -groups[k], k))[:limit]
    print(f"Quranic terminology\n{summary['files_scanned']} files checked · "
          f"{summary['errors']} errors · {summary['warnings']} warnings")
    left = max([len("Found"), *(len(k[1]) for k in shown)])
    right = max([len("Preferred"), *(len(k[2]) for k in shown)])
    for severity, title in (("error", "Errors"), ("warning", "Warnings (advisory)")):
        rows = [k for k in shown if k[0] == severity]
        if rows:
            print(f"\n{title}\n{'Found':<{left}}  {'Preferred':<{right}}  Occurrences")
            print("─" * (left + right + 15))
            for key in rows:
                print(f"{key[1]:<{left}}  {key[2]:<{right}}  {groups[key]:>11}")
    if groups:
        print(f"\nShowing {len(shown)} of {len(groups)} corrections. Increase --limit to show more.")
    if summary["known"] or summary["concepts_mixed"]:
        print(f"Advisory: {summary['known']} known compatibility findings; "
              f"{summary['concepts_mixed']} mixed-spelling concepts.")
    print("Use --by file for locations, or --json for all findings.")


def configuration(engine, explicit):
    path = engine.find_config([str(Path.cwd())], explicit)
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("configuration must be an object")
        for key in engine.CONFIG_KEYS:
            value = raw.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(f"{key} must be an array of strings")
    return engine.load_config(path)


def select(engine, paths, cfg):
    selected, skipped, seen = [], [], set()
    root = Path(cfg["root"])

    def visit(path):
        path = Path(os.path.abspath(path))
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            return
        if path in seen:
            return
        seen.add(path)
        rel = os.path.relpath(path, root)
        parts = Path(rel).parts if not rel.startswith("..") else path.parts
        if any(p in engine.SKIP_DIRS for p in parts):
            return
        if engine.matches(rel, cfg["exclude"]):
            return
        if not path.exists():
            raise ValueError(f"no such path: {path}")
        if path.is_dir():
            for child in sorted(path.iterdir()):
                visit(child)
            return
        if not path.is_file() or path.name == engine.CONFIG_NAME:
            return
        if engine.suffix_of(path.name) not in engine.CODE_SUFFIXES | engine.PROSE_SUFFIXES:
            return
        destination = skipped if path.stat().st_size > engine.MAX_BYTES else selected
        destination.append(str(path))

    for path in paths:
        # Missing explicit inputs are errors, even if an exclusion matches.
        if not os.path.lexists(path):
            raise ValueError(f"no such path: {path}")
        visit(path)
    return selected, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--by", choices=("compact", "file", "concept", "rule"), default="compact")
    parser.add_argument("--limit", type=int, default=None,
                        help="maximum correction rows in compact mode; findings per group in detailed modes")
    parser.add_argument("--version", action="version", version=version("quranic-terminology-lint"))
    args = parser.parse_args(argv)
    if args.limit is None:
        args.limit = 5 if args.by == "compact" else 20
    try:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        engine, data = validate()
        cfg = configuration(engine, args.config)
        paths = args.paths or [str(Path(cfg["root"]) / p) for p in cfg["paths"]] or [str(Path.cwd())]
        files, skipped = select(engine, paths, cfg)
        # Read once, strictly. The upstream scanner otherwise silently ignores
        # read errors; cached streams retain its rule logic without that policy.
        contents = {path: Path(path).read_text(encoding="utf-8") for path in files}
        reference_count = 0
        for path, content in contents.items():
            contents[path], count = mask_references(
                content, engine, engine.suffix_of(Path(path).name) in engine.PROSE_SUFFIXES,
                external=cfg["external"], suffix=engine.suffix_of(Path(path).name))
            reference_count += count
        engine.open = lambda path, *a, **kw: io.StringIO(contents[str(path)])
        index = prepare_index(engine, data, cfg["ignore_words"])
        findings, used, counted = engine.scan(files, index, data, cfg)
        findings.sort(key=lambda f: (f["file"], f["line"], f["identifier"]))
        mixed = engine.canonical_uses(data, used)
        summary = engine.summarise(findings, mixed, counted, data, cfg)
        summary["skipped_large_files"] = skipped
        summary["reference_literals"] = reference_count
        summary["terminology_overrides"] = {"word_timing": "word_timestamp"}
        if args.json:
            print(json.dumps({"summary": summary, "findings": findings, "mixed": mixed}, ensure_ascii=False))
        else:
            if args.by == "compact":
                compact_report(findings, summary, args.limit)
            else:
                engine.line_of = diagnostic
                engine.report(findings, mixed, summary, args.by, args.limit)
            if reference_count and args.by != "compact":
                print(f"{reference_count} resource references skipped")
            for path in skipped[:args.limit]:
                print(f"skipped (larger than {engine.MAX_BYTES} bytes): {path}", file=sys.stderr)
            if len(skipped) > args.limit:
                print(f"… {len(skipped) - args.limit} more large files skipped (see --json)", file=sys.stderr)
        return int(bool(summary["errors"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SyntaxError) as exc:
        print(f"quranic-terminology-lint: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
