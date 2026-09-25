"""Check that names in code follow the Quranic vocabulary naming standard."""
import argparse
from bisect import bisect_right
from collections import Counter
import fnmatch
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys

from . import fix as fixing, rules
from .context import (CODE_SUFFIXES, MAX_BYTES, PROSE_SUFFIXES, SKIP_DIRS,
                      data_names, editable_prose, mask_references, prose_ranges, string_ranges, suffix_of)

CONFIG_NAME = ".terminology.json"
CONFIG_KEYS = {"paths", "exclude", "ignore_words", "allow_gloss_in", "compatibility",
               "external_names"}
IGNORE_LINE = re.compile(r"terminology:\s*ignore", re.I)


# --- configuration -----------------------------------------------------------

def find_config(explicit):
    if explicit:
        return Path(explicit)
    for folder in (Path.cwd(), *Path.cwd().parents):
        if (folder / CONFIG_NAME).is_file():
            return folder / CONFIG_NAME
    return None


def load_config(path):
    raw = json.loads(path.read_text(encoding="utf-8")) if path else {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: configuration must be an object")
    unknown = sorted(k for k in raw if k not in CONFIG_KEYS and not k.startswith(("_", "$")))
    if unknown:
        raise ValueError(f"{path}: unknown keys {unknown}; the keys are {sorted(CONFIG_KEYS)}")
    cfg = {}
    for name in CONFIG_KEYS:
        value = raw.get(name, [])
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError(f"{path}: {name} must be an array of strings")
        cfg[name] = value
    try:
        cfg["external"] = re.compile("|".join(f"(?:{p})" for p in cfg["external_names"])) \
            if cfg["external_names"] else None
    except re.error as exc:
        raise ValueError(f"{path}: external_names is not a regular expression: {exc}") from exc
    cfg["root"] = path.resolve().parent if path else Path.cwd()
    cfg["file"] = str(path) if path else None
    return cfg


def matches(rel, patterns):
    """A glob covers a path when it matches it or any directory above it."""
    rel = rel.replace(os.sep, "/")
    for pattern in patterns:
        pattern = pattern.rstrip("/")
        bare = pattern[:-3] if pattern.endswith("/**") else pattern
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern + "/*") \
                or rel == bare or rel.startswith(bare + "/"):
            return True
    return False


# --- file selection ----------------------------------------------------------

def select(paths, cfg):
    selected, skipped, seen = [], [], set()
    root = cfg["root"]

    def visit(path):
        path = Path(os.path.abspath(path))
        if path.is_symlink() or path in seen:
            return
        seen.add(path)
        rel = os.path.relpath(path, root)
        parts = Path(rel).parts if not rel.startswith("..") else path.parts
        if any(p in SKIP_DIRS for p in parts) or matches(rel, cfg["exclude"]):
            return
        if not path.exists():
            raise ValueError(f"no such path: {path}")
        if path.is_dir():
            if (path / "pyvenv.cfg").exists():
                return  # A virtualenv, whatever it is called.
            for child in sorted(path.iterdir()):
                visit(child)
            return
        if not path.is_file() or path.name == CONFIG_NAME:
            return
        if suffix_of(path.name) not in CODE_SUFFIXES | PROSE_SUFFIXES:
            return
        (skipped if path.stat().st_size > MAX_BYTES else selected).append(path)

    for path in paths:
        # Missing explicit inputs are errors, even if an exclusion matches.
        if not os.path.lexists(path):
            raise ValueError(f"no such path: {path}")
        visit(path)
    return selected, skipped


# --- scanning ----------------------------------------------------------------

def merged(spans):
    """Sorted, non-overlapping spans with their starts, for binary search."""
    out = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return [s for s, _ in out], out


def inside(index, column):
    starts, spans = index
    i = bisect_right(starts, column) - 1
    return i >= 0 and column < spans[i][1]


def shown(path):
    rel = os.path.relpath(path)
    return rel if not rel.startswith("..") else str(path)


def scan(files, terms, cfg, unsafe_fixes=False):
    findings, renames = {}, []
    counted = Counter()
    for path in files:
        # Read strictly: a file that cannot be decoded is an error, not a pass.
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{shown(path)}: not UTF-8 ({exc.reason} at byte {exc.start}); "
                             "add it to exclude if it is not source") from None
        suffix = suffix_of(path.name)
        prose = suffix in PROSE_SUFFIXES
        spans = {} if prose else prose_ranges(text, suffix)
        names = data_names(text, suffix)
        literals = string_ranges(text, suffix) if unsafe_fixes and not prose else {}
        editable = editable_prose(text, suffix) if unsafe_fixes else {}
        code_spans = fixing.code_spans(text, fenced=prose) if unsafe_fixes else {}
        text, references = mask_references(text, prose, external=cfg["external"], suffix=suffix)
        counted["reference_literals"] += references
        counted["files_scanned"] += 1
        rel = os.path.relpath(path, cfg["root"])
        gloss_allowed = matches(rel, cfg["allow_gloss_in"])
        known = matches(rel, cfg["compatibility"])
        for number, line in enumerate(text.splitlines(), 1):
            if IGNORE_LINE.search(line):
                counted["ignored_lines"] += 1
                continue
            if cfg["external"]:
                line, hidden = cfg["external"].subn(lambda m: " " * len(m.group(0)), line)
                counted["external_names"] += hidden
            # A one-line JSON file has tens of thousands of spans on one line.
            notes = merged(spans.get(number, ()))
            keys = merged(names.get(number, ())) if names is not None else None
            strings = merged(literals.get(number, ())) if literals is not None else None
            ticks = merged(code_spans.get(number, ()))
            safe_notes = merged(editable.get(number, ()))
            for column, identifier in rules.identifiers(line):
                if keys is not None and not inside(keys, column):
                    continue
                in_note = prose or inside(notes, column)
                reported = []
                for found in rules.check(identifier, terms, in_note):
                    if gloss_allowed and found.pop("gloss"):
                        counted["allowed_glosses"] += 1
                        continue
                    found.pop("gloss", None)
                    reported.append(found)
                corrections = [f for f in reported if rules.fixable(f)]
                suggestion = rules.fix(identifier, corrections) if corrections else None
                for found in reported:
                    slot = (path, number, identifier, found["found"], tuple(found["rules"]))
                    if slot in findings:
                        findings[slot]["count"] += 1
                        continue
                    findings[slot] = {"file": shown(path), "line": number, "identifier": identifier,
                                      **found, "known": known, "count": 1,
                                      "suggested_identifier": suggestion if rules.fixable(found) else None}
                safe_prose = inside(safe_notes, column)
                if not unsafe_fixes or known or (strings is None and not safe_prose):
                    continue
                if strings is not None and inside(strings, column):
                    continue  # Strings hold data, keys and paths: never edited.
                renamed = suggestion
                if not renamed:
                    continue
                if in_note:  # A word for people. In `backticks` it names code: leave it.
                    if inside(ticks, column) or not fixing.plain_word(identifier, renamed):
                        continue
                # Prose detected heuristically may really be executable code or literal data.
                if prose and not safe_prose:
                    continue
                renames.append(fixing.Rename(path, number, column, identifier, renamed))
    return sorted(findings.values(), key=lambda f: (f["file"], f["line"], f["identifier"])), counted, renames


# --- reporting ---------------------------------------------------------------

def rule_label(finding):
    return ",".join(finding["rules"])


def table(findings, summary, limit):
    groups = Counter()
    for f in findings:
        if not f["known"]:
            groups[(f["severity"], f["found"], f["preferred"], rule_label(f))] += f["count"]
    shown_rows = sorted(groups, key=lambda k: (k[0] != "error", -groups[k], k))[:limit]
    print(f"Quranic terminology · {summary['files_scanned']} files · "
          f"{summary['errors']} errors · {summary['warnings']} warnings")
    widths = [max([len(title), *(len(k[i]) for k in shown_rows)])
              for i, title in ((1, "Found"), (2, "Preferred"), (3, "Rule"))]
    for severity, title in (("error", "Errors"), ("warning", "Warnings (do not block)")):
        rows = [k for k in shown_rows if k[0] == severity]
        if not rows:
            continue
        print(f"\n{title}")
        print(f"{'Found':<{widths[0]}}  {'Preferred':<{widths[1]}}  {'Rule':<{widths[2]}}  Count")
        for k in rows:
            print(f"{k[1]:<{widths[0]}}  {k[2]:<{widths[1]}}  {k[3]:<{widths[2]}}  {groups[k]:>5}")
    if len(groups) > len(shown_rows):
        print(f"\nShowing {len(shown_rows)} of {len(groups)}. Use --limit to show more.")
    if summary["known"]:
        print(f"{summary['known']} findings in compatibility paths (do not block).")
    if groups:
        print("Use --by file for locations and rule names.")


def detailed(findings, summary, limit):
    for f in findings[:limit]:
        where = " (compatibility)" if f["known"] else ""
        times = f" ×{f['count']}" if f["count"] > 1 else ""
        change = (f"{f['identifier']} → {f['suggested_identifier']}" if f["suggested_identifier"]
                  else f"{f['found']} → {f['preferred']} in {f['identifier']}")
        print(f"{f['file']}:{f['line']}: {f['severity']}{where} {change}{times} ({f['message']})")
    if len(findings) > limit:
        print(f"… and {len(findings) - limit} more (use --limit or --json)")
    print(f"{summary['errors']} errors, {summary['warnings']} warnings in {summary['files_scanned']} files")


def report_fixes(applied, fixed_files):
    if applied:
        print(f"\nFixed {len(applied)} names in {fixed_files} files. Review the changes, then stage them.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--by", choices=("table", "file"), default="file")
    parser.add_argument("--limit", type=int, default=None,
                        help="rows to show (default: 20 by file, 10 in the table)")
    parser.add_argument("--unsafe-fixes", action="store_true",
                        help="apply supported replacements in code and prose; may break bindings, APIs and references")
    parser.add_argument("--version", action="version", version=version("quranic-terminology-lint"))
    args = parser.parse_args(argv)
    try:
        limit = args.limit if args.limit is not None else (10 if args.by == "table" else 20)
        if limit < 1:
            raise ValueError("--limit must be positive")
        cfg = load_config(find_config(args.config))
        terms = rules.Terms(ignore_words=cfg["ignore_words"])
        paths = args.paths or [str(cfg["root"] / p) for p in cfg["paths"]] or [str(Path.cwd())]
        files, skipped = select(paths, cfg)
        if not files and not args.json:
            print("note: no eligible files (excluded, unsupported, or symlinked)", file=sys.stderr)
        findings, counted, applied = scan(files, terms, cfg, unsafe_fixes=args.unsafe_fixes)
        fixed_files = fixing.write(applied) if applied else 0
        live = [f for f in findings if not f["known"]]
        summary = {
            "files_scanned": counted["files_scanned"],
            "errors": sum(f["severity"] == "error" for f in live),
            "warnings": sum(f["severity"] == "warning" for f in live),
            "known": len(findings) - len(live),
            "ignored_lines": counted["ignored_lines"],
            "external_names": counted["external_names"],
            "allowed_glosses": counted["allowed_glosses"],
            "reference_literals": counted["reference_literals"],
            "skipped_large_files": [shown(p) for p in skipped],
            "fixed_names": len(applied),
            "fixed_files": fixed_files,
            "concepts": terms.concepts,
            "config": cfg["file"],
        }
        if args.json:
            print(json.dumps({"summary": summary, "findings": findings}, ensure_ascii=False))
        else:
            (table if args.by == "table" else detailed)(findings, summary, limit)
            if args.unsafe_fixes:
                report_fixes(applied, fixed_files)
            if skipped:
                more = f" and {len(skipped) - 3} more" if len(skipped) > 3 else ""
                print(f"skipped {len(skipped)} files larger than {MAX_BYTES // 1_000_000} MB: "
                      f"{', '.join(shown(p) for p in skipped[:3])}{more}", file=sys.stderr)
        return int(bool(summary["errors"]))
    except (OSError, ValueError, KeyError) as exc:
        print(f"quranic-terminology-lint: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
