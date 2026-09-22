"""Conservative lexical context around the bundled terminology rules."""
import io
import re
import tokenize

AMBIGUOUS_WORDS = {"timing", "timings"}
URL = re.compile(r"https?://[^\s<>\"'`)]+")
QUOTED = re.compile(r"(?P<quote>[\"'`])(?P<body>[^\n\"'`]+)(?P=quote)")
SOURCE_LINE = re.compile(r"(?:^\s*(?://|#|\*)\s*source\s*:|\"source\"\s*:)", re.I)
PATH_TOKEN = re.compile(r"(?<![\w.])(?:[A-Za-z0-9_@./-]+\.)[A-Za-z0-9]+(?![\w.])")
RESOURCE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".zip",
                     ".gz", ".mp3", ".wav", ".ogg", ".ttf", ".woff", ".woff2"}


def prepare_index(engine, data, ignore_words):
    # Maintainer-approved local naming override; preserve upstream concept identity.
    data["concepts"]["word_timing"].update(
        code="word_timestamp", display="Word Timestamp", plural="word_timestamps")
    # Reuse upstream generic-word severity: advisory in code, allowed in prose.
    engine.GENERIC_WORDS = engine.GENERIC_WORDS | AMBIGUOUS_WORDS
    index = engine.build_index(data, ignore_words)
    ignored = {form.lower().replace("-", "_").replace(" ", "_")
               for word in ignore_words for form in (word, word + "s")}
    for form in ("word_timing", "word_timings"):
        if form not in ignored:
            index[form] = ("spelling", "word_timing", "word_timing")
    # Consider a complete canonical compound before a deprecated short prefix.
    longest = max((len(form.split("_")) for form in index), default=4)
    upstream_ngrams = engine.ngrams
    engine.ngrams = lambda parts, longest=longest: upstream_ngrams(parts, longest)
    return index


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
            if token.type == tokenize.STRING and re.match(r"(?i)^[rub]*[ft]", token.string):
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


def mask_references(text, engine, prose=False, external=None, suffix=""):
    """Mask locator spans without changing line numbers or surrounding names.

    Recognize URLs, quoted filenames, and filenames in prose/source citations.
    Bare strings such as "aya" and object.aya remain subject to ordinary rules.
    """
    count = 0
    extensions = engine.CODE_SUFFIXES | RESOURCE_SUFFIXES | engine.PROSE_SUFFIXES
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
                if engine.suffix_of(match.group()) in extensions:
                    spans.append(match.span())
        # Preserve complete project-defined matches for the upstream scanner.
        # Masking a filename inside one could otherwise break its regex and
        # expose the rest of a deliberately exempted citation.
        protected = [m.span() for m in external.finditer(line)] if external else []
        spans = [(start, end) for start, end in spans
                 if not any(start < stop and end > begin for begin, stop in protected)]
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
