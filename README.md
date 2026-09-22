# Quranic terminology lint

An offline Python CLI and pre-commit hook using a bundled Quran.ws terminology
checker and dictionary. Requires Python 3.10+. Error-level findings block;
warnings and mixed spellings are advisory. Rules currently come from a draft
standard; reports identify the snapshot and draft entry count.

## Install and run

```sh
python -m pip install .
quranic-terminology-lint src
quranic-terminology-lint src --json
quranic-terminology-lint --version
```

No arguments means use `.terminology.json`'s `paths`, or the current directory.
Configuration is discovered from the working directory upward; `--config`
selects it explicitly. Configured paths/exclusions are relative to that file.
Explicit arguments override the default paths but still respect exclusions.
Exit status: 0 no blocking findings, 1 violations, 2 configuration/data/I/O error.
Unsupported files and symlinks are skipped. Files above 2,000,000 bytes are
reported as skipped. Invalid UTF-8 in eligible files is an error.

The default report groups repeated corrections, errors first, with occurrence
counts and up to three example locations. `--limit` caps correction rows across
the entire invocation (default 20); compatibility and mixed-spelling findings
are summarized, not listed. `--json` always includes every finding.

Use `--by file`, `--by concept`, or `--by rule` for detailed diagnostics:

```text
model.py:1: error [spelling] 'aya' → 'ayah' in 'aya_number' (Ayah) [internal]
```

In these explicit detailed modes, `--limit` controls findings per group.
Compatibility findings remain in a
separate non-blocking section. `--json` retains the upstream finding fields.

The adapter treats ordinary `timing` as ambiguous (advisory in code, permitted
in prose). Complete canonical compounds take precedence over shorter aliases.
URLs and recognized filenames in quoted strings, prose, or source citations
are treated as resource references. Only those spans are skipped; surrounding
names are still checked. JSON reports count these as `reference_literals`.
Python uses the standard-library tokenizer to recognize strings and comments,
including multiline and escaped strings. Interpolated strings are not
automatically exempted, so names inside expressions remain checked. If Python
tokenization fails, the file is still linted without automatic reference
exemptions. Other languages retain lexical reference handling.
Neither approach can infer every external organization or proper name;
use `external_names` for those. Bundled upstream rules and data stay unchanged.

Local naming override: `word_timestamp` / `word_timestamps` replaces
`word_timing` / `word_timings` for word-level audio spans. The old names are
reported, including camelCase and PascalCase forms. Ayah-level and ordinary
timing are unchanged. The adapter preserves the upstream `word_timing` concept
key and snapshot bytes; JSON `summary.terminology_overrides` records the naming
difference. This is a local maintainer decision, not an upstream standard update.

## pre-commit

Add the following to your project's `.pre-commit-config.yaml`, using an
immutable commit SHA for reproducible checks:

```yaml
repos:
  - repo: https://github.com/realabdu/quranic-terminology-lint
    rev: a2f5e47fd0956ae5593badbd258fbb6d7cb1fc67
    hooks:
      - id: quranic-terminology
        files: ^(src|app|database|data)/
```

Run `pre-commit install` in the consumer repository. To try this local checkout:

```sh
pre-commit try-repo /home/abdu/Work/quranic-terminology-lint quranic-terminology --all-files
```

Run `pre-commit run quranic-terminology --all-files` after installation.
To also enable push and merge checks, install those Git hook types explicitly:

```sh
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type pre-merge-commit
```

The separate [Quranic Terminology skill](https://github.com/realabdu/quranic-terminology)
provides contextual AI-assisted audits and edits. Its 66-concept vocabulary
differs from this hook's bundled 180-entry snapshot; identical decisions are
not currently guaranteed.

The hook checks complete staged files, performs no edits, and never updates
the dictionary. Initial hook installation may need network access to install
build tooling. Subsequent lint runs need none. Serial execution prevents
parallel batches; it does not guarantee a complete repository-wide report.

For CI, use the same pinned installation and run `quranic-terminology-lint`
from the project root to scan all configured directories in one invocation.
`pre-commit run quranic-terminology --all-files` checks all matching tracked
files but can still batch them. Changes to configuration or dictionary versions
should be followed by a full scan. Mixed spellings never fail this release.

## Exceptions

Commit a `.terminology.json`, for example:

```json
{
  "paths": ["src"],
  "exclude": ["src/generated/**"],
  "ignore_words": ["segment"],
  "allow_gloss_in": ["src/api/v1/**"],
  "compatibility": ["src/legacy/schema.sql"],
  "external_names": ["vendor_sura_id"]
}
```

Use `ignore_words` for unrelated meanings, `allow_gloss_in` for allowed English
glosses, `compatibility` for established names that require a migration, and
`external_names` for regexes matching names owned upstream. These follow the
bundled engine's semantics. A line containing `terminology: ignore` is excused.
Document why each exception exists. Do not blanket-exempt new API fields.

## Development and snapshot updates

```sh
python -m pip install -e '.[test]'
python -m pytest
python -m build
pre-commit validate-manifest
python tools/import_snapshot.py /path/to/quran-ws-docs --check
python tools/import_snapshot.py /path/to/quran-ws-docs
```

Import only a trusted local source checkout: validation executes its Python
checker. The importer validates resources before replacing the bundle and
records exact hashes and provenance. `--check` returns 0 if unchanged, 1 for
a valid differing candidate, or 2 for invalid input; it never replaces files.
The original source checkout is only read. Commit imports and integration
test results together, then release a new version for consumers to adopt.

The initial snapshot is local and uncommitted upstream. See `NOTICE` and
installed `vendor/provenance.json`. New integration code is MIT; bundled
resources retain upstream licensing. No rule ownership moves here.
