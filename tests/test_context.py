import json
from pathlib import Path
import pytest
from quranic_terminology_lint import cli


def audit(tmp_path, monkeypatch, capsys, text, filename):
    monkeypatch.chdir(tmp_path)
    Path(filename).write_text(text)
    status = cli.main([filename, "--json"])
    return status, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("text,filename,warnings", [
    ("There is no timing threshold. Load and hit-test timing.", "notes.md", 0),
    ("timing_threshold = 1\nloadTiming = 2", "benchmark.py", 2),
    ("ayah_timing = 1", "model.py", 0),
])
def test_ordinary_timing(tmp_path, monkeypatch, capsys, text, filename, warnings):
    status, result = audit(tmp_path, monkeypatch, capsys, text, filename)
    assert status == 0
    assert result["summary"]["warnings"] == warnings


@pytest.mark.parametrize("text,filename", [
    ('// source: quran-tajweed uthmani-hafs.json 2:26\nsura = 1', "fixture.rs"),
    ('{"source": "quran-tajweed uthmani-hafs.json 2:26", "aya": 1}', "fixture.json"),
    ('| source | quran-tajweed uthmani-hafs.json 2:26 |\naya', "notes.md"),
    ('source = "https://example.org/sura/aya.json"\naya = 1', "model.py"),
    ('source = "uthmani-hafs.json"; aya = 1', "model.py"),
    ('See [source](https://example.org/uthmani-hafs.json).\naya', "notes.md"),
])
def test_locators_do_not_hide_neighbors(tmp_path, monkeypatch, capsys, text, filename):
    status, result = audit(tmp_path, monkeypatch, capsys, text, filename)
    assert status == 1
    assert result["summary"]["reference_literals"] == 1
    errors = [f for f in result["findings"] if f["severity"] == "error"]
    assert len(errors) == 1
    assert errors[0]["found"] in {"aya", "sura"}
    assert errors[0]["line"] == (2 if "\n" in text else 1)
    assert not any(f["found"] == "uthmani" for f in result["findings"])


@pytest.mark.parametrize("text", ['field = "aya"', 'object.aya = 1', 'aya.json = 1'])
def test_non_locator_identifiers_still_fail(tmp_path, monkeypatch, capsys, text):
    status, result = audit(tmp_path, monkeypatch, capsys, text, "model.py")
    assert status == 1
    assert result["summary"]["reference_literals"] == 0


@pytest.mark.parametrize("name", ["waqf_jaiz_mustawi_al_tarafayn", "waqfJaizMustawiAlTarafayn"])
def test_long_canonical_name(tmp_path, monkeypatch, capsys, name):
    status, result = audit(tmp_path, monkeypatch, capsys, f"{name} = 1", "model.py")
    assert status == 0
    assert not result["findings"]


def test_bare_deprecated_still_fails(tmp_path, monkeypatch, capsys):
    status, result = audit(tmp_path, monkeypatch, capsys,
        "waqf_jaiz_mustawi_al_tarafayn = 1\nwaqf_jaiz = 2", "model.py")
    assert status == 1
    assert len(result["findings"]) == 1
    assert result["findings"][0]["rule"] == "deprecated"
    assert result["findings"][0]["line"] == 2


def test_explicit_external_expression_preserved(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path('.terminology.json').write_text(json.dumps({
        'external_names': [r'uthmani-hafs\.json sura'],
    }))
    status, result = audit(tmp_path, monkeypatch, capsys,
        'source = "uthmani-hafs.json sura"\naya = 1', 'model.py')
    assert status == 1
    assert result['summary']['external_names'] == 1
    assert [f['found'] for f in result['findings']] == ['aya']


@pytest.mark.parametrize("text,line", [
    ('source = """\nuthmani-hafs.json\n"""\naya = 1', 4),
    ('source = "a \\"quote\\" uthmani-hafs.json"\naya = 1', 2),
    ('# source: uthmani-hafs.json\naya = 1', 2),
])
def test_python_literal_context(tmp_path, monkeypatch, capsys, text, line):
    status, result = audit(tmp_path, monkeypatch, capsys, text, "model.py")
    assert status == 1
    assert result["summary"]["reference_literals"] == 1
    assert [(f["found"], f["line"]) for f in result["findings"]] == [("aya", line)]


@pytest.mark.parametrize("text,found", [
    ('url = f"https://example.org/{sura}.json"', "sura"),
    ('url = rf"https://example.org/{aya.json}"', "aya"),
    ('metadata = {"source": True}; aya.json = 1', "aya"),
    ('source = """unterminated\naya.json', "aya"),
    ('broken = "\nsource = "aya.json"', "aya"),
    ('url = f"https://example.org/{sura:{aya}}"', "aya"),
])
def test_python_executable_or_unparsed_names_still_fail(tmp_path, monkeypatch, capsys, text, found):
    status, result = audit(tmp_path, monkeypatch, capsys, text, "model.py")
    assert status == 1
    assert result["summary"]["reference_literals"] == 0
    assert any(f["found"] == found for f in result["findings"])


@pytest.mark.parametrize("name", ["word_timestamp", "word_timestamps", "wordTimestamp", "WordTimestamps", "WORD_TIMESTAMP"])
def test_word_timestamp_canonical(tmp_path, monkeypatch, capsys, name):
    status, result = audit(tmp_path, monkeypatch, capsys, f"{name} = 1", "model.py")
    assert status == 0 and not result["findings"]
    assert result["summary"]["terminology_overrides"] == {"word_timing": "word_timestamp"}


@pytest.mark.parametrize("name", ["word_timing", "word_timings", "wordTiming", "WordTimings", "WORD_TIMING"])
def test_word_timing_legacy(tmp_path, monkeypatch, capsys, name):
    status, result = audit(tmp_path, monkeypatch, capsys, f"{name} = 1", "model.py")
    assert status == 1
    assert len(result["findings"]) == 1
    assert result["findings"][0]["canonical"] == "word_timestamp"
    assert result["findings"][0]["concept"] == "word_timing"  # Stable upstream identity.


def test_word_timing_ignore_and_unrelated_timing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path(".terminology.json").write_text('{"ignore_words": ["word_timing"]}')
    status, result = audit(tmp_path, monkeypatch, capsys,
                           "word_timing = 1\nword_timings = 2\nayah_timing = 3", "model.py")
    assert status == 0
    assert not any(f["canonical"] == "word_timestamp" or f["line"] == 3 for f in result["findings"])
