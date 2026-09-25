"""Write supported terminology replacements after explicit unsafe opt-in.

A name's absence from Git history does not establish ownership, binding
scope, or freedom from collisions. No code rename is considered safe.
"""
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

TICKS = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


@dataclass
class Rename:
    path: Path
    line: int
    column: int
    old: str
    new: str


def code_spans(text, fenced):
    """Per line, the spans in backticks, and whole lines inside fenced blocks."""
    spans, fence = {}, None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line) if fenced else None
        if fence:
            spans[number] = [(0, len(line))]
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
        elif match:
            fence = match[1]
            spans[number] = [(0, len(line))]
        elif fenced and (line.startswith(("    ", "\t", ">")) or "`" in line):
            # Indented/quoted examples and inline code can contain literal data.
            spans[number] = [(0, len(line))]
        else:
            spans[number] = [m.span() for m in TICKS.finditer(line)]
    return spans


def plain_word(old, new):
    return old.isalpha() and new.isalpha() and (old.islower() or old.istitle() or old.isupper())


def write(renames):
    by_file = defaultdict(list)
    for r in renames:
        by_file[r.path].append(r)
    for path, edits in by_file.items():
        with path.open(encoding="utf-8", newline="") as source:
            lines = source.read().splitlines(keepends=True)
        for r in sorted(edits, key=lambda r: (r.line, r.column), reverse=True):
            line = lines[r.line - 1]
            lines[r.line - 1] = line[:r.column] + r.new + line[r.column + len(r.old):]
        with path.open("w", encoding="utf-8", newline="") as target:
            target.write("".join(lines))
    return len(by_file)
