"""Which renames are safe to apply, and applying them.

Following the linters that fix names at all, a fix is only automatic when it
cannot break anything:

- Prose: a plain word in documentation or a comment. Nothing
  runs it. Names in `backticks` or code blocks refer to code and are left.
- New names: a code name that is not in the last commit, and whose every
  occurrence in the working tree is one this fix edits. Nothing can depend on
  it yet, and no string repeats it.

Existing names are renamed only with --unsafe-fixes: other code, strings, data
or a library's users may depend on them.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

SEPARATOR = re.compile(r"[.\-]")
TICKS = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Rename:
    path: Path
    line: int
    column: int
    old: str
    new: str
    prose: bool

    def changes(self):
        """The dot- or dash-separated tokens that change, as git sees words."""
        old, new = SEPARATOR.split(self.old), SEPARATOR.split(self.new)
        if len(old) != len(new):
            return None
        return [(a, b) for a, b in zip(old, new) if a != b]


def code_spans(text, fenced):
    """Per line, the spans in backticks, and whole lines inside fenced blocks."""
    spans, inside = {}, False
    for number, line in enumerate(text.splitlines(), 1):
        if fenced and FENCE.match(line):
            inside = not inside
            spans[number] = [(0, len(line))]
        elif inside:
            spans[number] = [(0, len(line))]
        else:
            spans[number] = [m.span() for m in TICKS.finditer(line)]
    return spans


def plain_word(old, new):
    return old.isalpha() and new.isalpha()


WORD = re.compile(rb"[A-Za-z0-9_]+")


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def repository(start):
    result = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def _words(data, tokens):
    """(line, token) for each whole-word occurrence of a token; nothing for binary data."""
    if b"\0" in data[:8000]:
        return
    for number, line in enumerate(data.split(b"\n"), 1):
        for word in WORD.findall(line):
            if word in tokens:
                yield number, word.decode()


def occurrences(root, tokens):
    """Where each token occurs in the working tree, and which tokens the last commit has.

    One pass over the files git knows (tracked and untracked, not ignored). A
    token is in the last commit if an unchanged tracked file has it, or the
    committed version of a changed file does.
    """
    encoded = {t.encode() for t in tokens}
    tracked = set((_git(root, "ls-files", "-z") or b"").split(b"\0")) - {b""}
    untracked = set((_git(root, "ls-files", "-z", "-o", "--exclude-standard") or b"").split(b"\0")) - {b""}
    has_head = _git(root, "rev-parse", "--verify", "-q", "HEAD") is not None
    changed = set((_git(root, "diff", "-z", "--name-only", "HEAD") or b"").split(b"\0")) - {b""} \
        if has_head else set(tracked)
    found, committed = defaultdict(Counter), set()
    for name in tracked | untracked:
        path = root / name.decode()
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for line, token in _words(data, encoded):
            found[token][(path.resolve(), line)] += 1
            if name in tracked and name not in changed:
                committed.add(token)
    for name in changed if has_head else ():
        data = _git(root, "show", f"HEAD:{name.decode()}")
        committed |= {token for _, token in _words(data or b"", encoded)}
    return found, committed


def select(renames, unsafe=False):
    """(applied, held back, reason for holding back)."""
    prose = [r for r in renames if r.prose]
    code = [r for r in renames if not r.prose]
    if unsafe or not code:
        return prose + code, [], None
    root = repository(Path.cwd())
    if root is None:
        return prose, code, "not a git repository, so new names cannot be told from existing ones"
    tokens = {old for r in code for old, _ in (r.changes() or [])}
    found, existing = occurrences(root, tokens)
    planned = defaultdict(Counter)
    for r in code:
        for old, _ in r.changes() or []:
            planned[old][(r.path.resolve(), r.line)] += 1
    safe = {t for t in tokens if t not in existing and found[t] <= planned[t]}
    applied = [r for r in code if r.changes() and all(old in safe for old, _ in r.changes())]
    held = [r for r in code if r not in applied]
    return prose + applied, held, None


def write(renames):
    by_file = defaultdict(list)
    for r in renames:
        by_file[r.path].append(r)
    for path, edits in by_file.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for r in sorted(edits, key=lambda r: (r.line, r.column), reverse=True):
            line = lines[r.line - 1]
            lines[r.line - 1] = line[:r.column] + r.new + line[r.column + len(r.old):]
        path.write_text("".join(lines), encoding="utf-8")
    return len(by_file)
