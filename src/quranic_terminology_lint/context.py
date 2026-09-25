"""Which files are read, and which spans of them are resource references."""
import io
import os
import re
import tokenize

CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".swift", ".rb", ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".dart",
    ".sql", ".graphql", ".gql", ".proto", ".json", ".yml", ".yaml", ".toml",
    ".prisma", ".vue", ".svelte", ".scala", ".ex", ".exs", ".sh", ".html",
    ".xml", ".csv", ".tsv", ".ini", ".env", ".blade.php",
}
PROSE_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc"}
EXTRA_NAMES = {".env.example", ".env.sample"}
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", "target",
    "__pycache__", ".venv", "venv", ".next", ".nuxt", ".cache", "coverage",
    ".mypy_cache", ".pytest_cache", "migrations_backup", "site-packages",
}
MAX_BYTES = 2_000_000

URL = re.compile(r"https?://[^\s<>\"'`)]+")
QUOTED = re.compile(r"(?P<quote>[\"'`])(?P<body>[^\n\"'`]+)(?P=quote)")
SOURCE_LINE = re.compile(r"(?:^\s*(?://|#|\*)\s*source\s*:|\"source\"\s*:)", re.I)
PATH_TOKEN = re.compile(r"(?<![\w.])(?:[A-Za-z0-9_@./-]+\.)[A-Za-z0-9]+(?![\w.])")
RESOURCE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".zip",
                     ".gz", ".mp3", ".wav", ".ogg", ".ttf", ".woff", ".woff2"}


def suffix_of(name):
    lower = name.lower()
    if lower.endswith(".blade.php"):
        return ".blade.php"
    if lower in EXTRA_NAMES:
        return ".env"
    return os.path.splitext(lower)[1]


def python_reference_ranges(text):
    """Return string/comment spans; never exempt interpolated expressions."""
    lines = text.splitlines(keepends=True)
    ranges = {}
    interpolation_depth = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.ERRORTOKEN and not token.string.isspace():
                return {}
            name = tokenize.tok_name[token.type]
            if name in {"FSTRING_START", "TSTRING_START"}:
                interpolation_depth += 1
            elif name in {"FSTRING_END", "TSTRING_END"}:
                interpolation_depth -= 1
            if interpolation_depth or token.type not in {tokenize.STRING, tokenize.COMMENT}:
                continue
            # Python 3.10/3.11 expose whole f-strings as STRING tokens.
            if token.type == tokenize.STRING and re.match(r"(?i)^[rub]*[ft]", token.string):  # terminology: ignore
                continue
            filenames = token.type == tokenize.STRING or bool(SOURCE_LINE.match(token.string))
            first, last = token.start[0], token.end[0]
            for row in range(first, last + 1):
                start = token.start[1] if row == first else 0
                end = token.end[1] if row == last else len(lines[row - 1])
                ranges.setdefault(row, []).append((start, end, filenames))
    except (tokenize.TokenError, SyntaxError):
        # Incomplete source is still linted, but receives no automatic exemptions.
        return {}
    return ranges


def mask_references(text, prose=False, external=None, suffix=""):
    """Mask locator spans without changing line numbers or surrounding names.

    Recognize URLs, quoted filenames, and filenames in prose/source citations.
    Other strings and attribute names remain subject to ordinary rules.
    """
    count = 0
    extensions = CODE_SUFFIXES | RESOURCE_SUFFIXES | PROSE_SUFFIXES
    python_ranges = python_reference_ranges(text) if suffix == ".py" else None
    output = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if python_ranges is not None:
            contexts = python_ranges.get(number, [])
            spans = [m.span() for start, end, _ in contexts for m in URL.finditer(line, start, end)]
            ranges = [(start, end) for start, end, filenames in contexts if filenames]
        else:
            # ponytail: other languages use lexical context; add tokenizers when syntax causes misclassification.
            spans = [m.span() for m in URL.finditer(line)]
            ranges = ([(0, len(line))] if prose or SOURCE_LINE.search(line)
                      else [m.span("body") for m in QUOTED.finditer(line)])
        for start, end in ranges:
            for match in PATH_TOKEN.finditer(line, start, end):
                if suffix_of(match.group()) in extensions:
                    spans.append(match.span())
        # Preserve complete project-defined matches for the upstream scanner.
        # Masking a filename inside one could otherwise break its regex and
        # expose the rest of a deliberately exempted citation.
        protected = [m.span() for m in external.finditer(line)] if external else []
        spans = [(start, end) for start, end in spans
                 if not any(start < finish and end > begin for begin, finish in protected)]
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        count += len(merged)
        for start, end in reversed(merged):
            line = line[:start] + " " * (end - start) + line[end:]
        output.append(line)
    return "".join(output), count


SLASH_COMMENTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt",
                  ".swift", ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".dart", ".scala",
                  ".vue", ".svelte", ".prisma", ".proto"}
HASH_COMMENTS = {".py", ".rb", ".sh", ".yml", ".yaml", ".toml", ".ini", ".env", ".ex", ".exs",
                 ".graphql", ".gql", ".php"}
LINE_COMMENT = {"//": re.compile(r"//.*"), "#": re.compile(r"(?:^|(?<=\s))#.*"),
                "--": re.compile(r"--.*")}
BLOCK_LINE = re.compile(r"^\s*(?:/\*|\*|<!--)")
SPACED = re.compile(r"\s")
MARKUP = {".html", ".xml"}
TAG = re.compile(r"<[^<>]*>?|^[^<>]*>")


def quoted_spans(line, open_ended=False):
    """Quoted strings on a line. A quote only closes a string of its own kind,
    so `"Al-Jumu'a"` is one string. With open_ended, an unclosed quote runs to
    the end of the line."""
    spans, i = [], 0
    while i < len(line):
        if line[i] in "\"'`":
            j = i + 1
            while j < len(line) and line[j] != line[i]:
                j += 2 if line[j] == "\\" else 1
            if j < len(line):
                spans.append((i, j + 1))
                i = j + 1
                continue
            if open_ended:
                spans.append((i, len(line)))
                break
        i += 1
    return spans


def prose_ranges(text, suffix):
    """Spans of a code file written for people: comments, and strings with spaces.

    `"Surah al-Fatihah"` is a label and `// load al-Fatihah` a note, so they are
    read like prose. `"ayah_number"` has no spaces: it is a name, and stays code.
    """
    if suffix == ".py":
        ranges = _python_prose(text)
        if ranges is not None:
            return ranges
    markers = [m for m, kinds in (("//", SLASH_COMMENTS), ("#", HASH_COMMENTS), ("--", {".sql"}))
               if suffix in kinds]
    ranges = {}
    for number, line in enumerate(text.splitlines(), 1):
        spans = ranges.setdefault(number, [])
        if BLOCK_LINE.match(line):
            spans.append((0, len(line)))
            continue
        if suffix in MARKUP:  # Text between tags is what the reader sees.
            edge = 0
            for tag in TAG.finditer(line):
                spans.append((edge, tag.start()))
                edge = tag.end()
            spans.append((edge, len(line)))
        for start, end in quoted_spans(line):
            if SPACED.search(line[start + 1:end - 1]):
                spans.append((start, end))
        for marker in markers:
            match = LINE_COMMENT[marker].search(line)
            if match:
                spans.append((match.start(), len(line)))
    return ranges


def _python_prose(text):
    lines = text.splitlines(keepends=True)
    ranges = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.ERRORTOKEN and not token.string.isspace():
                return None
            if token.type == tokenize.COMMENT or (
                    token.type == tokenize.STRING and not re.match(r"(?i)^[rub]*[ft]", token.string)
                    and SPACED.search(token.string)):
                first, last = token.start[0], token.end[0]
                for row in range(first, last + 1):
                    start = token.start[1] if row == first else 0
                    end = token.end[1] if row == last else len(lines[row - 1])
                    ranges.setdefault(row, []).append((start, end))
    except (tokenize.TokenError, SyntaxError):
        return None
    return ranges


JSON_KEY = re.compile(r'"(?:[^"\\\n]|\\.)*"(?=\s*:)')


def data_names(text, suffix):
    """In a data file, the spans that are names; None when every span is.

    A CSV's rows and a JSON file's values are data, often copied from a source
    (`"Al-Baqarah"`). The names chosen for them are the header and the keys.
    """
    if suffix in {".csv", ".tsv"}:
        first = text.split("\n", 1)[0]
        return {1: [(0, len(first))]}
    if suffix == ".json":
        ranges = {}
        for number, line in enumerate(text.splitlines(), 1):
            ranges[number] = [m.span() for m in JSON_KEY.finditer(line)]
        return ranges
    return None


def string_ranges(text, suffix):
    """Every string literal. A fix never edits these: they hold data, import
    paths and keys that something outside the file depends on."""
    if suffix == ".py":
        ranges = {}
        try:
            lines = text.splitlines(keepends=True)
            for token in tokenize.generate_tokens(io.StringIO(text).readline):
                if token.type == tokenize.STRING or tokenize.tok_name[token.type].startswith("FSTRING"):
                    first, last = token.start[0], token.end[0]
                    for row in range(first, last + 1):
                        start = token.start[1] if row == first else 0
                        end = token.end[1] if row == last else len(lines[row - 1])
                        ranges.setdefault(row, []).append((start, end))
            return ranges
        except (tokenize.TokenError, SyntaxError):
            pass
    if suffix in {".json", ".csv", ".tsv"}:
        return None  # Data files are never fixed.
    return {number: quoted_spans(line, open_ended=True)
            for number, line in enumerate(text.splitlines(), 1)}
