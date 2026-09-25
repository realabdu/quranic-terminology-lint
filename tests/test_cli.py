import json
from pathlib import Path
import socket
import subprocess

import pytest

from quranic_terminology_lint import cli


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


def test_error_blocks_and_names_the_rule(capsys):
    status, result = run(capsys, "aya_number = 1\n")
    assert status == 1
    [finding] = result["findings"]
    assert (finding["found"], finding["preferred"], finding["rules"]) == ("aya", "ayah", ["019"])
    assert finding["message"] == "rule 019: Ta marbutah outside idafah"
    assert finding["arabic"] == "الآيَة"


def test_clean_and_offline(capsys, monkeypatch):
    def network_forbidden(*args, **kwargs):
        raise AssertionError("network accessed")
    monkeypatch.setattr(socket, "socket", network_forbidden)
    status, result = run(capsys, "ayah = 1\nsurahs = []\nword_timestamp = 0\n")
    assert status == 0 and not result["findings"]


def test_warnings_do_not_block(capsys):
    status, result = run(capsys, "ayah_idx = 1\n")
    assert status == 0 and result["summary"]["warnings"] == 1


@pytest.mark.parametrize("text,config,name", [
    ("Tajweed and the verse of al-Fatihah", {}, "README.md"),
    ("sura = 1", {"compatibility": ["schema.sql"]}, "schema.sql"),
    ("vendor_sura_id = 1", {"external_names": ["vendor_sura_id"]}, "model.py"),
    ("sura = 1 # terminology: ignore", {}, "model.py"),
    ("verse = 1", {"allow_gloss_in": ["model.py"]}, "model.py"),
    ("sura = 1", {"ignore_words": ["sura"]}, "model.py"),
    ("# Load surah al-Fatihah, the first chapter\nsurah = 1", {}, "model.py"),
    ('label = "Surah al-Fatihah"', {}, "model.py"),
    ('const label = "Chapter 1"; // al-Fatihah', {}, "view.ts"),
    ("<h1>Chapter 1: al-Fatihah</h1>", {}, "page.html"),
])
def test_allowances(capsys, text, config, name):
    assert run(capsys, text, config, name)[0] == 0


@pytest.mark.parametrize("text,name", [
    ('row = {"aya_number": 1}', "model.py"),
    ('{"sura": 1}', "data.json"),
    ('<div class="sura-title"></div>', "page.html"),
    ("# The aya text", "model.py"),
    ("The Sura list", "README.md"),
])
def test_names_in_strings_markup_and_prose_still_checked(capsys, text, name):
    assert run(capsys, text, None, name)[0] == 1


def test_compatibility_is_reported_but_does_not_block(capsys):
    status, result = run(capsys, "sura = 1", {"compatibility": ["legacy/**"]}, "legacy/schema.sql")
    assert status == 0
    assert result["summary"]["known"] == 1 and result["findings"][0]["known"]
    # Only listed paths are exempt; other schema files still block.
    status, _ = run(capsys, "sura = 1", {"compatibility": ["legacy/**"]}, "db/schema.sql")
    assert status == 1


def test_selection_parity(capsys):
    Path("src").mkdir()
    Path("src/a space.py").write_text("sura = 1")
    Path(".terminology.json").write_text(json.dumps({"exclude": ["src/**"]}))
    for args in (["src"], ["src/a space.py"]):
        assert cli.main([*args, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 0


def test_dedup(capsys):
    Path("a space.py").write_text("sura = 1")
    assert cli.main(["a space.py", ".", ".", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 1


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


def test_comment_keys_are_allowed(capsys):
    Path(".terminology.json").write_text('{"_comment": "why", "$schema": "x"}')
    Path("a.py").write_text("ayah = 1")
    assert cli.main(["a.py"]) == 0


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


def test_symlinked_ancestor_is_scanned(capsys, tmp_path):
    Path("real").mkdir()
    Path("real/model.py").write_text("aya_number = 1")
    Path("alias").symlink_to("real")
    assert cli.main([str(tmp_path / "alias/model.py"), "--json"]) == 1


def test_nothing_checked_is_noted(capsys):
    Path(".terminology.json").write_text(json.dumps({"exclude": ["model.py"]}))
    Path("model.py").write_text("aya_number = 1")
    assert cli.main(["model.py"]) == 0
    assert "no eligible files" in capsys.readouterr().err


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


def test_table(capsys):
    for number in range(3):
        Path(f"model{number}.py").write_text("aya = 1\nsura = 2\nayah_idx = 3\n")
    assert cli.main(["."]) == 1
    output = capsys.readouterr().out
    assert "3 files · 6 errors · 3 warnings" in output
    lines = [line.split() for line in output.splitlines()]
    assert ["aya", "ayah", "019", "3"] in lines
    assert output.index("Errors") < output.index("Warnings (do not block)")
    assert "model0" not in output


def test_table_limit_and_complete_json(capsys):
    Path("model.py").write_text("aya = sura = basmala = 1")
    assert cli.main([".", "--limit", "1"]) == 1
    assert "Showing 1 of 3" in capsys.readouterr().out
    assert cli.main([".", "--limit", "1", "--json"]) == 1
    assert len(json.loads(capsys.readouterr().out)["findings"]) == 3


def test_clean_table_has_no_empty_headers(capsys):
    Path("model.py").write_text("ayah = 1")
    assert cli.main(["."]) == 0
    output = capsys.readouterr().out
    assert "0 errors · 0 warnings" in output and "Found" not in output


def test_by_file(capsys):
    Path("model.py").write_text("aya_number = 1\naya = 2 # aya\n")
    assert cli.main(["model.py", "--by", "file"]) == 1
    output = capsys.readouterr().out
    assert "model.py:1: error aya → ayah in aya_number (rule 019: Ta marbutah outside idafah)" in output
    assert "model.py:2: error aya → ayah in aya ×2" in output
    assert cli.main(["model.py", "--by", "file", "--limit", "1"]) == 1
    assert "… and 1 more" in capsys.readouterr().out


@pytest.mark.parametrize("text,name,status", [
    ("surah_number,name\n1,Al-Fatihah\n2,al_baqarah\n", "surahs.csv", 0),
    ("sura_number,name\n1,Fatihah\n", "surahs.csv", 1),
    ('{"surah_name": "al_baqarah", "list": ["sura"]}', "data.json", 0),
    ('{"sura_name": "Baqarah"}', "data.json", 1),
])
def test_data_files_check_names_not_values(capsys, text, name, status):
    assert run(capsys, text, None, name)[0] == status


def test_prose_transliteration(capsys):
    assert run(capsys, "The riwāyāt of the Uthmānī mushaf", None, "README.md")[0] == 0


def test_virtualenv_of_any_name_is_skipped(capsys):
    Path("env-ci/lib").mkdir(parents=True)
    Path("env-ci/pyvenv.cfg").write_text("home = /usr")
    Path("env-ci/lib/bad.py").write_bytes(b"\xff")
    assert cli.main([".", "--json"]) == 0


def test_invalid_utf8_names_the_file(capsys):
    Path("bad.py").write_bytes(b"\xff")
    assert cli.main(["."]) == 2
    assert "bad.py: not UTF-8" in capsys.readouterr().err


def test_one_line_json_is_linear(capsys):
    import time
    Path("timings.json").write_text(json.dumps(
        {f"{s}:{a}": {"surah_number": s, "ayah_number": a} for s in range(1, 60) for a in range(1, 100)}))
    started = time.monotonic()
    assert cli.main(["timings.json", "--json"]) == 0
    assert time.monotonic() - started < 3  # quadratic span lookup took over 10 s here


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


def repo(files):
    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "T")
    for name, text in files.items():
        Path(name).write_text(text)
    git("add", ".")
    git("commit", "-qm", "base", "--allow-empty")


def test_fix_renames_new_names_in_their_style(capsys):
    repo({"old.ts": "export const riwaya = 1;\n"})
    Path("a.ts").write_text("const ayaNo = getSuraName(x); // the aya list\nconst AYA_NO = 1;\n")
    assert cli.main(["a.ts", "--fix"]) == 1  # Fixed files still fail, so they are reviewed.
    assert Path("a.ts").read_text() == (
        "const ayahNumber = getSurahName(x); // the ayah list\nconst AYAH_NUMBER = 1;\n")
    assert "Fixed 4 names in 1 files" in capsys.readouterr().out
    assert cli.main(["a.ts"]) == 0


def test_fix_holds_back_names_something_may_depend_on(capsys):
    repo({"lib.ts": "export function getSuraName() {}\n"})
    Path("a.ts").write_text(
        "getSuraName();\n"                    # exists in the last commit
        'const sajdaList = ["sajdaList"];\n'  # repeated in a string
        "const qiraaMap = 1;\n")              # also used in a file not being fixed
    Path("b.ts").write_text("use(qiraaMap);\n")
    assert cli.main(["a.ts", "--fix"]) == 1
    assert Path("a.ts").read_text().startswith("getSuraName();\nconst sajdaList")
    output = capsys.readouterr().out
    assert "Not renamed: getSuraName, qiraaMap, sajdaList" in output
    assert cli.main(["a.ts", "b.ts", "--fix"]) == 1  # Every occurrence reachable now.
    assert "qiraahMap" in Path("a.ts").read_text() and Path("b.ts").read_text() == "use(qiraahMap);\n"


def test_fix_prose_words_but_not_code_in_docs(capsys):
    repo({})
    Path("README.md").write_text("The Sura list.\n\nCall `get_sura()`:\n\n```\nsura = 1\n```\n")
    Path("a.py").write_text("x = 1  # the aya and `aya_id`\n")
    cli.main([".", "--fix"])
    assert Path("README.md").read_text() == "The Surah list.\n\nCall `get_sura()`:\n\n```\nsura = 1\n```\n"
    assert Path("a.py").read_text() == "x = 1  # the ayah and `aya_id`\n"


def test_unsafe_fixes_rename_existing_names(capsys):
    repo({"lib.ts": "export function getSuraName() {}\n"})
    assert cli.main(["lib.ts", "--fix"]) == 1
    assert "getSuraName" in Path("lib.ts").read_text()
    assert cli.main(["lib.ts", "--unsafe-fixes"]) == 1
    assert Path("lib.ts").read_text() == "export function getSurahName() {}\n"


def test_fix_outside_git_only_fixes_prose(capsys):
    Path("a.ts").write_text("const ayaNo = 1; // the aya\n")
    cli.main(["a.ts", "--fix"])
    assert Path("a.ts").read_text() == "const ayaNo = 1; // the ayah\n"
    assert "not a git repository" in capsys.readouterr().out


def test_fix_never_touches_strings_data_warnings_or_compatibility(capsys):
    source = 'import { x } from "./findRubAlHizb";\nname = {"sura_id": "Douri"};\nayah_idx = 1\n'
    Path("a.ts").write_text(source)
    Path("d.json").write_text('{"sura": 1}\n')
    Path("legacy.py").write_text("sura = 1\n")
    Path(".terminology.json").write_text('{"compatibility": ["legacy.py"]}')
    cli.main([".", "--unsafe-fixes"])
    assert Path("a.ts").read_text() == source
    assert Path("d.json").read_text() == '{"sura": 1}\n'
    assert Path("legacy.py").read_text() == "sura = 1\n"


def test_without_fix_nothing_is_written(capsys):
    Path("a.py").write_text("sura = 1\n")
    assert cli.main(["a.py"]) == 1
    assert Path("a.py").read_text() == "sura = 1\n"


def test_fix_never_edits_a_string_containing_the_other_quote(capsys):
    source = '  ["Al-Jumu\'a", "Friday"],\n  label = \'the "sura" list\'\n'
    Path("names.ts").write_text(source)
    cli.main(["names.ts", "--unsafe-fixes"])
    assert Path("names.ts").read_text() == source
