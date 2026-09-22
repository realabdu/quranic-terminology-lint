import json
from pathlib import Path
import shutil
import socket

import pytest

from quranic_terminology_lint import cli, snapshot


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def run(capsys, text, config=None, name="model.py"):
    Path(name).parent.mkdir(parents=True, exist_ok=True)
    Path(name).write_text(text)
    if config is not None:
        Path(".terminology.json").write_text(json.dumps(config))
    status = cli.main([name, "--json"])
    return status, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("text,rule", [
    ("suras = []", "spelling"), ("ayat = []", "arabic_plural"),
    ("waqf_jaiz = 1", "deprecated"), ("qaloun = 1", "member"),
])
def test_blocking_rules(capsys, text, rule):
    status, result = run(capsys, text)
    assert status == 1
    assert any(f["rule"] == rule for f in result["findings"])


def test_clean_offline(capsys, monkeypatch):
    def network_forbidden(*args, **kwargs):
        raise AssertionError("network accessed")
    monkeypatch.setattr(socket, "socket", network_forbidden)
    status, result = run(capsys, "ayah = 1\nsurahs = []\n")
    assert status == 0 and not result["findings"]


def test_warnings_and_mixed_advisory(capsys):
    status, result = run(capsys, "ayah = 1\nverse = 2\n")
    assert status == 0
    assert result["summary"]["warnings"]
    assert result["mixed"]


@pytest.mark.parametrize("text,config,name", [
    ("Tajweed and verse", {}, "README.md"),
    ("sura = 1", {"compatibility": ["schema.sql"]}, "schema.sql"),
    ("vendor_sura_id = 1", {"external_names": ["vendor_sura_id"]}, "model.py"),
    ("sura = 1 # terminology: ignore", {}, "model.py"),
    ("verse = 1", {"allow_gloss_in": ["model.py"]}, "model.py"),
    ("sura = 1", {"ignore_words": ["sura"]}, "model.py"),
])
def test_allowances(capsys, text, config, name):
    assert run(capsys, text, config, name)[0] == 0


def test_selection_parity(capsys):
    Path("src").mkdir()
    Path("src/a space.py").write_text("sura = 1")
    Path(".terminology.json").write_text(json.dumps({"exclude": ["src/**"]}))
    for args in (["src"], ["src/a space.py"]):
        assert cli.main([*args, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 0


def test_dedup_spaces(capsys, monkeypatch):
    Path("a space.py").write_text("sura = 1")
    original = Path.iterdir
    visited = []
    def track(path):
        visited.append(path)
        return original(path)
    monkeypatch.setattr(Path, "iterdir", track)
    assert cli.main(["a space.py", ".", ".", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 1
    assert visited.count(Path.cwd()) == 1


def test_config_relative_and_explicit_override(capsys, monkeypatch):
    Path("src").mkdir()
    Path("src/a.py").write_text("sura = 1")
    Path("child").mkdir()
    Path("child/ok.py").write_text("ayah = 1")
    Path(".terminology.json").write_text(json.dumps({"paths": ["src"]}))
    monkeypatch.chdir("child")
    assert cli.main(["--json"]) == 1
    capsys.readouterr()
    assert cli.main(["ok.py", "--json"]) == 0


@pytest.mark.parametrize("config", [[], {"paths": "src"}, {"exclude": [3]},
                                          {"unknown": []}, {"external_names": ["("]}])
def test_invalid_config(config):
    Path(".terminology.json").write_text(json.dumps(config))
    assert cli.main([]) == 2


def test_missing_inputs():
    assert cli.main(["missing.py"]) == 2
    assert cli.main(["--config", "missing.json"]) == 2


def test_skips(capsys):
    Path("node_modules").mkdir()
    Path("node_modules/bad.py").write_text("sura = 1")
    Path("bad.bin").write_bytes(b"sura")
    Path("link.py").symlink_to("node_modules/bad.py")
    Path("broken.py").symlink_to("missing")
    assert cli.main([".", "node_modules/bad.py", "link.py", "broken.py", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 0


def test_size_limit(capsys):
    Path("large.py").write_text("sura " * 400001)
    assert cli.main(["large.py", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["summary"]["skipped_large_files"]) == 1


def test_read_failure(monkeypatch):
    Path("bad.py").write_text("ayah = 1")
    original = Path.read_text
    def denied(path, *args, **kwargs):
        if path.name == "bad.py":
            raise PermissionError("denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    assert cli.main(["bad.py"]) == 2


def test_invalid_utf8():
    Path("bad.py").write_bytes(b"\xff")
    assert cli.main(["bad.py"]) == 2


def test_snapshot_integrity(tmp_path):
    snapshot.validate()
    dest = tmp_path / "vendor"
    shutil.copytree(snapshot.VENDOR, dest, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "data/terminology.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        snapshot.validate(dest)


@pytest.mark.parametrize("by", ["file", "concept", "rule"])
def test_text_diagnostics(capsys, by):
    Path("model.py").write_text("aya_number = 1\nverse = 2\n")
    assert cli.main(["model.py", "--by", by]) == 1
    output = capsys.readouterr().out
    assert "model.py:1: error [spelling] 'aya' → 'ayah' in 'aya_number'" in output
    assert "model.py:2: warning [gloss] 'verse' → 'ayah' in 'verse'" in output
    assert "1 errors, 1 warnings" in output


def test_text_limit_and_compatibility(capsys):
    Path("model.py").write_text("aya = 1\nsura = 2\n")
    assert cli.main(["model.py", "--by", "file", "--limit", "1"]) == 1
    output = capsys.readouterr().out
    assert output.count(": error [spelling]") == 1
    assert "and 1 more" in output
    Path(".terminology.json").write_text('{"compatibility": ["model.py"]}')
    assert cli.main(["model.py", "--by", "file"]) == 0
    output = capsys.readouterr().out
    assert "2 on a compatibility surface — known" in output
    assert ": error [" not in output


def test_diagnostic_keeps_repeated_occurrences():
    finding = {"file": "model.py", "line": 1, "severity": "error", "rule": "spelling",
               "found": "aya", "canonical": "ayah", "identifier": "aya",
               "count": 2, "display": "Ayah", "layer": "internal"}
    assert cli.diagnostic(finding).endswith("in 'aya' ×2 (Ayah) [internal]")


def test_compact_report_global_limit_and_complete_json(capsys):
    for number in range(30):
        Path(f"model{number}.py").write_text("aya = 1\nsura = 2\nverse = 3\n")
    assert cli.main([".", "--limit", "1"]) == 1
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 4
    assert "60 errors, 30 warnings; 3 distinct corrections" in output
    assert "error [spelling] 'aya' → 'ayah' ×30" in output
    assert "+27 locations" in output
    assert "2 more corrections" in output
    assert cli.main([".", "--limit", "1", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert len(report["findings"]) == 90


def test_compact_advisories_are_bounded(capsys):
    Path("model.py").write_text("aya = 1\nayah = 2\n")
    Path(".terminology.json").write_text('{"compatibility": ["model.py"]}')
    assert cli.main(["."]) == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 2
    assert "1 known compatibility findings" in output
    assert "1 mixed-spelling concepts" in output
