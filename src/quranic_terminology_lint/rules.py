"""The naming standard's rules, applied to one identifier at a time.

The term files hold each concept's canonical code name and the irregular
names no rule can predict (`chapter` for `surah`). Everything a rule can
predict is generated here from the canonical names by running the spelling
rules backwards: `tajwid` yields `tajweed` (rule 021), `surah` yields `sura`
(rule 019), `fatihah` yields `al_fatihah` (rule 031). A finding therefore
names the rule that was broken, not just a list entry that matched.
"""
from dataclasses import dataclass
from itertools import product
from pathlib import Path
import re
import unicodedata

TERMS = Path(__file__).parent / "terms"

RULES = {
    "001": "One code name per concept",
    "009": "Characters in code spelling",
    "019": "Ta marbutah outside idafah",
    "020": "Ta marbutah in idafah",
    "021": "Long vowels",
    "022": "The nisbah ending",
    "026": "Final hamzah and ayn after a consonant with sukun",
    "030": "The definite article and sun letters",
    "031": "The definite article at the beginning",
    "032": "The definite article on an adjective",
    "033": "The definite article in idafah",
    "037": "Code-name stability",
    "046": "Deprecated names",
    "049": "Forming the code plural",
    "050": "Classification names and the _type suffix",
    "055": "Ayah numbering system names",
    "056": "Personal names",
    "057": "Deriving surah names",
    "068": "Reference numbers",
    "069": "Position in a sequence",
    "073": "Naming audio timings",
    "clear-names": "Clear names",
}
# Article and marks rules concern code names; prose writes "al-Fatihah",
# "Qur'an" and scholarly transliteration (`riwāyāt`) normally, and shows
# display names.
CODE_ONLY = {"009", "026", "030", "031", "032", "033", "037"}
MEMBER_RULE = {"surah": "057", "rawi": "056", "qiraah": "056", "riwayah": "056",
               "ayah_numbering_system": "055"}
# Surah and tariq names are often ordinary words (`elephant`, `cow`).
ORDINARY_NAME_KINDS = {"surah", "tariq"}
# Ordinary English words that some entry records as a name (`part` for juz,
# `pause` for waqf). Alone they are far more often something else, so they are
# never reported; in a compound (`juz_part`) the compound itself is checked.
ORDINARY_WORDS = {
    "segment", "reading", "stop", "sign", "mark", "dot", "place", "count", "number",
    "line", "page", "word", "letter", "root", "text", "character", "glyph", "translation",
    "position", "index", "order", "part", "unit", "quarter", "half", "eighth", "chain",
    "path", "way", "style", "pace", "school", "pos", "simple", "timing", "section",
    "group", "station", "portion", "pause", "conversion", "commentary", "assimilation",
    "concealment", "prolongation", "orthography", "vocalization", "transmitter", "para",
    "mad", "lin", "wid", "rub",
}
# Generated forms that are common English words; never report these.
ENGLISH = {"feel", "room", "hood", "teen", "jam", "rub", "cat", "rat", "mat", "sat", "hat",
           "fat", "pat", "bat", "vat", "ruk", "nun", "din", "fees", "seen", "keen"}
NUMBER_ABBREVIATIONS = {"no", "num", "nr", "nbr"}
SEQUENCE_WORDS = {"idx", "index", "seq", "ord"}
ABBREVIATIONS = {"srh": "surah", "wrd": "word"}
TIMINGS = {"ayah_timing", "word_timestamp"}
RECORDING_KINDS = {"rawi", "riwayah", "qiraah"}
RECORDING_STYLES = {"murattal", "mujawwad", "muallim"}
SUN = ("th", "dh", "sh", "t", "d", "r", "z", "s", "n", "l")

LETTER = "A-Za-zÀ-ɏḀ-ỿ"
# An apostrophe inside a word may stand for hamzah or ayn (`qira'ah`), but not
# in an English contraction or possessive (`line's`, `don't`).
IDENTIFIER = re.compile(rf"[{LETTER}](?:[{LETTER}0-9_.\-]|['’ʼʾʿ](?=[{LETTER}])(?!(?:s|t|d|m|ll|re|ve)\b))*")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
MARKS = str.maketrans("", "", "'’ʼʾʿ")


@dataclass(frozen=True)
class Term:
    code: str
    display: str
    plural: str
    arabic: str
    kind: str  # "concept", or the registry a member belongs to
    origin: str = "quranic"  # quranic, borrowed or standard (rules 002-004)


@dataclass(frozen=True)
class Hit:
    term: Term
    rules: tuple = ()        # empty: the canonical name itself
    warning: bool = False
    plural: bool = False
    gloss: bool = False


def key(form):
    return form.strip().lower().replace("-", "_").replace(" ", "_")


def read_table(path):
    rows, header = [], None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        if header is None:
            header = cells
        elif len(cells) != len(header):
            raise ValueError(f"{path.name}:{number}: {len(cells)} columns, expected {len(header)}")
        else:
            rows.append(dict(zip(header, cells)))
    return rows


def items(cell):
    return [key(v) for v in cell.split(",") if v.strip()]


# --- the spelling rules, run backwards ---------------------------------------

def part_variants(part, following):
    """Ways the rules say this canonical word part is commonly miswritten."""
    out = []
    vowels = [i for i, c in enumerate(part) if c in "iu"][:3]
    for chosen in range(1, 2 ** len(vowels)):  # rule 021: tajwid → tajweed
        letters = list(part)
        for bit, i in enumerate(vowels):
            if chosen >> bit & 1:
                letters[i] = {"i": "ee", "u": "oo"}[part[i]]
        out.append(("".join(letters), "021"))
    if part.endswith("i") and len(part) > 3:  # rule 022: makki → makkiyy
        out += [(part + "yy", "022"), (part + "y", "022"), (part[:-1] + "ee", "022")]
    if part.endswith("ah"):  # rule 019: surah → sura, surat
        out += [(part[:-1], "019"), (part[:-2] + "at", "019")]
    if part.endswith("at") and following == "al":  # rule 020: hamzat_al → hamzah_al
        out += [(part[:-2] + "ah", "020"), (part[:-1], "020")]
    match = re.fullmatch(r"(.*([aiu])[^aiu]{1,2})\2", part)
    if match and len(part) >= 4:  # rule 026: rubu → rub
        out.append((match.group(1), "026"))
    return out


def article_variants(code):
    """Ways the article rules say a whole canonical name is miswritten."""
    parts = code.split("_")
    out = [("al_" + code, "031"), ("al" + code, "031"), ("el_" + code, "031")]
    for sun in SUN:
        if code.startswith(sun):
            out.append((f"a{sun}_{code}", "031"))
    for i, part in enumerate(parts[1:-1], 1):
        if part != "al":
            continue
        head, rest = "_".join(parts[:i]), "_".join(parts[i + 1:])
        out += [(f"{head}_{v}_{rest}", "030") for v in ("ul", "el", "il")]
        out += [(f"{head}_a{sun}_{rest}", "030") for sun in SUN if rest.startswith(sun) and sun != "l"]
        out.append((f"{head}_{rest}", "033"))  # rubu_al_hizb → rubu_hizb
    for i in range(1, len(parts)):
        if "al" not in (parts[i - 1], parts[i]):  # rasm_uthmani → rasm_al_uthmani
            out.append(("_".join(parts[:i] + ["al"] + parts[i:]), "032"))
    return out


def derived_forms(term, arabic_words):
    """Every miswriting the rules predict for a term, with the rules broken.

    A general concept keeps its English words (rule 003), but a Quranic word
    inside it is still spelled by the rules: `aya_key` for `ayah_key`.
    """
    parts = term.code.split("_")
    general = term.origin == "standard"
    options = []
    for i, part in enumerate(parts):
        following = parts[i + 1] if i + 1 < len(parts) else ""
        variants = [] if general and part not in arabic_words else part_variants(part, following)
        options.append([(part, ())] + [(v, (r,)) for v, r in variants])
    forms = {}
    total = 1
    for choices in options:
        total *= len(choices)
    # ponytail: every combination only for short names; longer names get one change at a time.
    combos = product(*options) if total <= 64 else (
        [(v, r) if j == i else choices[0] for j, choices in enumerate(options)]
        for i in range(len(parts)) for v, r in options[i][1:])
    for combo in combos:
        rules = tuple(sorted({r for _, rs in combo for r in rs}))
        if rules:
            forms.setdefault("_".join(p for p, _ in combo), rules)
    for form, rule in [] if general else article_variants(term.code):
        forms.setdefault(form, (rule,))
    return forms


# --- the index ---------------------------------------------------------------

class Terms:
    def __init__(self, root=TERMS, ignore_words=()):
        self.index = {}
        concepts = [(row, Term(row["code"], row["display"], row["plural"] or row["code"] + "s",
                               row["arabic"], "concept", row["origin"]))
                    for row in read_table(root / "concepts.tsv")]
        members = [(row, Term(row["code"], row["display"], row["code"] + "s", row["arabic"], row["kind"]))
                   for row in read_table(root / "members.tsv")]
        if not concepts:
            raise ValueError("no concepts in the term files")
        terms = [t for _, t in concepts + members]
        for term in terms:  # A bare name refers to the concept (rule 058).
            self.index.setdefault(term.code, Hit(term))
            self.index.setdefault(term.plural, Hit(term, plural=True))
        canonical = set(self.index)
        for row, term in concepts:
            for form in items(row["former_names"]):
                self.put(form, Hit(term, ("046",)))
            for form in items(row["arabic_plurals"]):
                self.put(form, Hit(term, ("049",), plural=True))
        arabic_words = {t.code for t in terms if t.origin != "standard" and "_" not in t.code}
        for term in terms:
            single = "_" not in term.code
            for form, rules in derived_forms(term, arabic_words).items():
                # A short surah name respelled is usually an English word (`sab`, `feel`).
                if form in ENGLISH or single and term.kind in ORDINARY_NAME_KINDS and {"021", "026"} & set(rules):
                    continue
                self.put(form, Hit(term, rules, warning=single and rules == ("026",)))
        for row, term in concepts:
            for form in items(row["other_spellings"]):
                self.put(form, Hit(term, ("050",) if form.endswith("_type") else ("001",)))
            self.put(key(row["display"]), Hit(term, ("037",)))
            for form in items(row["english"]):
                self.put(form, Hit(term, ("001",), gloss=True))
        for row, term in members:
            rule = MEMBER_RULE.get(term.kind, "001")
            for form in items(row["other_spellings"]):
                if "_" in form or term.kind not in ORDINARY_NAME_KINDS:  # not `sad`, `cow`
                    self.put(form, Hit(term, (rule,)))
        for form, hit in list(self.index.items()):  # rule 049: plurals add `s`
            if hit.rules:
                self.put(form + "s", Hit(hit.term, hit.rules, hit.warning, True, hit.gloss))
        for word in ignore_words:
            for form in (key(word), key(word) + "s"):
                if form not in canonical:
                    self.index.pop(form, None)
        self.longest = max(len(form.split("_")) for form in self.index)
        self.concepts = len(concepts)

    def put(self, form, hit):
        if len(form) > 2 and form not in ORDINARY_WORDS and form.rstrip("s") not in ORDINARY_WORDS:
            self.index.setdefault(form, hit)


# --- checking ----------------------------------------------------------------

def split(identifier):
    """Lowercase word parts, however the identifier is cased or separated."""
    out = []
    for chunk in re.split(r"[_.\-]+", identifier):
        out += [p.lower() for p in CAMEL.split(chunk) if p]
    return out


def plain(part):
    decomposed = unicodedata.normalize("NFKD", part.translate(MARKS))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def finding(rules, found, preferred, warning=False, term=None, gloss=False):
    return {"rules": list(rules), "severity": "warning" if warning else "error",
            "found": found, "preferred": preferred, "gloss": gloss,
            "arabic": term.arabic if term else "",
            "message": "; ".join(f"rule {r}: {RULES[r]}" if r[0].isdigit() else RULES[r]
                                 for r in rules)}


def check(identifier, terms, prose=False):
    if prose and identifier.isupper() and len(identifier) > 1:
        return []  # A Unicode character name, `ARABIC FATHA`, is kept as given (rule 043).
    raw = split(identifier)
    parts = [plain(p) for p in raw]
    taken, matched, out = set(), [], []
    for size in range(min(terms.longest, len(parts)), 0, -1):
        for start in range(len(parts) - size + 1):
            span = set(range(start, start + size))
            if span & taken:
                continue
            gram = "_".join(parts[start:start + size])
            hit = terms.index.get(gram)
            if not hit:
                continue
            taken |= span
            matched.append((start, start + size, hit))
            marked = any(raw[i] != parts[i] for i in span)
            rules = hit.rules + (("009",) if marked else ())
            if not rules:
                continue
            following = parts[start + size] if start + size < len(parts) else ""
            if hit.rules == ("019",) and gram.endswith("at") and following == "al":
                continue  # `surat_al_...` is idafah, written with t (rule 020).
            if hit.rules == ("031",) and start > 0:
                continue  # Inside a compound, `al` is idafah (rule 033), not a leading article.
            if prose and (marked or hit.warning or hit.gloss or set(rules) <= CODE_ONLY
                          or gram in (key(hit.term.display), key(hit.term.display) + "s")):
                continue
            preferred = hit.term.plural if hit.plural else hit.term.code
            # Marks and apostrophes only occur in strings, often quoted text.
            warning = hit.warning or rules == ("009",)
            out.append(finding(sorted(set(rules)), "_".join(raw[start:start + size]), preferred,
                               warning, hit.term, hit.gloss))
    if prose:
        return out
    for start, end, hit in matched:
        if hit.term.kind != "concept" or hit.term.origin != "quranic" or end >= len(parts):
            continue
        code, after, written = hit.term.code, parts[end], "_".join(raw[start:end + 1])
        if after == "type" and not code.endswith("_mark"):
            out.append(finding(["050"], written, "a name for what it classifies", True, hit.term))
        elif after in NUMBER_ABBREVIATIONS:
            out.append(finding(["068"], written, f"{code}_number", term=hit.term))
        elif after in SEQUENCE_WORDS:
            out.append(finding(["069"], written, f"{code}_number or {code}_position", True, hit.term))
    for i, part in enumerate(parts):
        if i not in taken and part in ABBREVIATIONS:
            out.append(finding(["clear-names"], part, ABBREVIATIONS[part], True))
    timing = next((h.term.code for _, _, h in matched if h.term.code in TIMINGS), None)
    recording = [h.term.code for _, _, h in matched
                 if h.term.kind in RECORDING_KINDS or h.term.code in RECORDING_STYLES]
    if timing and recording:
        out.append(finding(["073"], identifier, timing, True))
    return out


def identifiers(line):
    for match in IDENTIFIER.finditer(line):
        yield match.start(), match.group(0)


# --- fixing ------------------------------------------------------------------

def part_spans(identifier):
    """Each word part of an identifier with its character span."""
    out = []
    for chunk in re.finditer(r"[^_.\-]+", identifier):
        edges = [0] + [m.start() for m in CAMEL.finditer(chunk.group())] + [len(chunk.group())]
        out += [(chunk.start() + a, chunk.start() + b) for a, b in zip(edges, edges[1:]) if b > a]
    return out


def render(written, preferred):
    """`preferred` in the style `written` uses: snake, kebab, camel, Pascal or upper."""
    words = preferred.split("_")
    separators = re.findall(r"[_.\-]+", written)
    if written.isupper() and len(written) > 1:
        return (separators[0] if separators else "_").join(w.upper() for w in words)
    if separators:
        text = separators[0].join(words)
    else:
        text = words[0] + "".join(w.capitalize() for w in words[1:])
    return text[0].upper() + text[1:] if written[0].isupper() else text


def fix(identifier, findings):
    """The identifier with each fixable finding replaced, or None."""
    spans = part_spans(identifier)
    words = [identifier[a:b].lower() for a, b in spans]
    edits = []
    for f in findings:
        size = len(f["found"].split("_"))
        for i in range(len(words) - size + 1):
            if "_".join(words[i:i + size]) == f["found"]:
                edits.append((spans[i][0], spans[i + size - 1][1], f["preferred"]))
                break
    if not edits:
        return None
    kept = []  # Where two fixes overlap (`sura`, `sura_num`), the longer one wins.
    for edit in sorted(edits, key=lambda e: e[0] - e[1]):
        if all(edit[1] <= k[0] or edit[0] >= k[1] for k in kept):
            kept.append(edit)
    for start, end, preferred in sorted(kept, reverse=True):
        identifier = identifier[:start] + render(identifier[start:end], preferred) + identifier[end:]
    return identifier


def fixable(finding):
    return finding["severity"] == "error" and re.fullmatch(r"[a-z0-9_]+", finding["preferred"])
