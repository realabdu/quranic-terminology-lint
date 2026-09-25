# Quranic terminology lint

Checks that the names in your code follow the Quranic vocabulary naming
standard. Add it to pre-commit once and every commit is checked: `aya_number`,
`tajweed_rules` or `al_fatihah` are rejected with the name to use instead and
the rule behind it.

```text
Quranic terminology · 12 files · 3 errors · 1 warnings

Errors
Found       Preferred  Rule  Count
aya         ayah       019       4
tajweed     tajwid     021       2
al_fatihah  fatihah    031       1

Warnings (do not block)
Found     Preferred                     Rule  Count
ayah_idx  ayah_number or ayah_position  069       1
```

It runs offline, has no dependencies, and needs Python 3.10+. It only edits
files when you ask it to fix them.

## Set up

Add one of the two hooks to your project's `.pre-commit-config.yaml`, then run
`pre-commit install`. `pre-commit autoupdate` moves you to the latest release.

**Check only (recommended).** A commit with an error is stopped, and the table
says what to rename. Nothing is changed for you.

```yaml
repos:
  - repo: https://github.com/realabdu/quranic-terminology-lint
    rev: v0.2.0
    hooks:
      - id: quranic-terminology
```

**Check and fix.** Also renames, in place and in each name's own style, what
can be renamed without breaking anything. The commit still stops so you can
review the change and stage it.

```yaml
      - id: quranic-terminology-fix
```

Like Ruff and RuboCop, the fix separates safe renames from unsafe ones, and
like darker and SonarQube it holds new code to the standard without forcing a
rename of old code:

- **Prose**: plain words in documentation and comments (`the aya list` →
  `the ayah list`). Names in `backticks` or code blocks are left alone.
- **New names**: a code name that is not in the last commit, when every place
  it appears is one the fix edits. Write `getSuraNo` and commit
  `getSurahNumber`.
- **Everything else is reported, not renamed**: a name already committed, or
  one repeated in a string or in a file the fix cannot reach, because other
  code, data or a library's users may depend on it. Rename it with your
  editor's rename refactoring. Strings, JSON and CSV are never edited.

`--unsafe-fixes` also renames existing names. Use it only on application code
with tests, and review the diff: a text rename cannot keep a name in sync with
a string that repeats it, and a renamed export breaks everything that uses it.

```yaml
      - id: quranic-terminology-fix
        args: [--unsafe-fixes]
```

Measured on a fresh clone of the quran-meta TypeScript library (430 tests):

| | Changed | Build | Type check | Tests |
| --- | --- | --- | --- | --- |
| Before | | passes | passes | 430 pass |
| `--fix` on the existing code | 841 words in docs and comments; no code, no strings | passes | passes | 430 pass |
| `--fix` on a new function and its test | `getSuraNo(ayaKey)` → `getSurahNumber(ayahKey)` | passes | passes | 431 pass |
| `--unsafe-fixes` | 3,516 names, including 12 exported ones | passes | 73 errors | 14 fail |

A file name is never renamed. In the example above, `suraTools.ts` is still
reported so you can rename the file yourself.

To check the whole project once, run
`pre-commit run quranic-terminology --all-files`.

To run it directly or in CI:

```sh
pip install git+https://github.com/realabdu/quranic-terminology-lint@v0.2.0
quranic-terminology-lint            # the paths in .terminology.json, or the current directory
quranic-terminology-lint src --by file
quranic-terminology-lint src --json
quranic-terminology-lint src --fix  # safe renames in place; review with git diff
```

Exit status: 0 no errors (warnings do not block), 1 errors found, 2 a
configuration or file problem.

## What it checks

Each identifier is split into words (`ayahKey`, `ayah_key` and `AYAH_KEY` are
the same name) and checked against the standard's rules. The term files list
each concept's canonical name. Most misspellings are predicted by the rules
from that name, so a finding names the rule that was broken.

| Rule | Checks | Example |
| --- | --- | --- |
| 001 | One code name per concept | `chapter` → `surah`, `verse` → `ayah` |
| 009 | No transliteration marks or apostrophes | `qira'ah` → `qiraah` |
| 019, 020 | Ta marbutah | `sura` → `surah`, `hamzah_al_wasl` → `hamzat_al_wasl` |
| 021 | Long vowels are one letter | `tajweed` → `tajwid`, `tafseer` → `tafsir` |
| 022 | The nisbah ending | `makkiyy` → `makki` |
| 026 | Final hamzah and ayn after sukun | `rub_al_hizb` → `rubu_al_hizb` |
| 030–033 | The definite article | `asbab_an_nuzul` → `asbab_al_nuzul`, `al_fatihah` → `fatihah`, `rasm_al_uthmani` → `rasm_uthmani`, `rubu_hizb` → `rubu_al_hizb` |
| 046 | Deprecated names | `word_timing` → `word_timestamp` |
| 049 | Plurals add `s` | `ayat` → `ayahs`, `suras` → `surahs` |
| 050 | `_type` is for mark types | `waqf_type` (warning) |
| 055–057 | Numbering systems, personal and surah names | `qaloun` → `qalun`, `kufan` → `kufi` |
| 068, 069 | `number` and `position` | `surah_no` → `surah_number`, `ayah_idx` (warning) |
| 073 | Timing names do not include the recording | `hafs_word_timestamp` (warning) |

The other rules govern how a name is derived from vocalised Arabic, or how
concepts are modelled. They apply when a term is added to the term files, not
to code.

**Errors** are certain: a known misspelling of a Quranic term. **Warnings** are
guesses to review, and never block a commit.

### What it leaves alone

- Comments, strings with spaces (`"Surah al-Fatihah"`), text between HTML
  tags, and Markdown or text files are read as prose. Prose may use display
  names (`Tajweed`), English equivalents (`verse`), `al-` and apostrophes. It
  is only checked for misspellings such as `Sura`.
- Ordinary English words that a term also translates (`part`, `pause`,
  `reading`, `stop`, `timing`) are never reported on their own.
- General concepts with English names (`token`, `line`, `page`) are not held
  to the Arabic spelling rules.
- ALL-CAPS Unicode character names in prose (`ARABIC FATHA`, rule 043).
- In CSV and TSV files only the header row is checked, and in JSON only the
  keys. Rows and values are data, often copied from a source.
- Scholarly transliteration in prose (`riwāyāt`).
- URLs and file names (`uthmani-hafs.json`), virtualenvs of any name,
  `node_modules`, build output, and files over 2 MB.

## Exceptions

Commit a `.terminology.json` at the project root:

```json
{
  "paths": ["src"],
  "exclude": ["src/generated/**"],
  "ignore_words": ["segment"],
  "allow_gloss_in": ["src/api/v1/**"],
  "compatibility": ["src/legacy/schema.sql"],
  "external_names": ["vendor_sura_id"],
  "_comment": "Why each exception exists."
}
```

| Key | Use it for |
| --- | --- |
| `paths` | What to check when no paths are given. |
| `exclude` | Files that are never read. |
| `ignore_words` | A word with an unrelated meaning in this project. |
| `allow_gloss_in` | Files that must use English equivalents, such as a published API that says `verse`. |
| `compatibility` | Names you cannot rename without a migration. Reported, but they do not block. |
| `external_names` | Regular expressions for names someone else owns, such as a publisher's column `aya_text_emlaey`. |

A line containing `terminology: ignore` is skipped. Keys starting with `_` or
`$` are ignored, so you can record the reasons.

## Changing the terms

The terms live in `src/quranic_terminology_lint/terms/`:

- `concepts.tsv`: each concept's code name, display name, origin, Arabic
  name, and the names no rule predicts (other spellings, English
  equivalents, Arabic plurals, deprecated names).
- `members.tsv`: surahs, qiraat, rawis, riwayahs, turuq, ayah numbering
  systems and tajwid rulings.

Do not list a spelling that a rule already predicts; `tests/test_rules.py`
checks this for the common cases. A change to the terms is released like any
other change, and projects pick it up with `pre-commit autoupdate`.

## Development

```sh
python -m pip install -e '.[test]'
python -m pytest
quranic-terminology-lint          # the linter checks its own code
pre-commit validate-manifest
python -m build
```

MIT licensed.
