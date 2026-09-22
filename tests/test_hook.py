"""Exercise the published manifest through a separate consumer's actual hook."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_real_pre_commit(tmp_path):
    hook = tmp_path / "hook"
    shutil.copytree(ROOT, hook, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", "*.egg-info", "dist", "build"))
    env = dict(os.environ, PRE_COMMIT_HOME=str(tmp_path / "cache"))
    def run(cwd, *args, expected=0):
        if args[0] == "pre-commit":
            args = (sys.executable, "-m", "pre_commit", *args[1:])
        result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
        assert result.returncode == expected, result.stdout + result.stderr
        return result
    def init(path):
        path.mkdir(exist_ok=True)
        run(path, "git", "init", "-b", "main")
        run(path, "git", "config", "user.email", "test@example.invalid")
        run(path, "git", "config", "user.name", "Hook Test")
    init(hook)
    run(hook, "git", "add", ".")
    run(hook, "git", "commit", "-m", "Test snapshot")
    rev = run(hook, "git", "rev-parse", "HEAD").stdout.strip()
    consumer = tmp_path / "consumer"
    init(consumer)
    (consumer / ".pre-commit-config.yaml").write_text(
        f"repos:\n  - repo: '{hook}'\n    rev: {rev}\n    hooks:\n      - id: quranic-terminology\n")
    (consumer / ".terminology.json").write_text('{"exclude": ["excluded/**"]}')
    model = consumer / "a space.py"
    model.write_text("ayah = 1\n")
    run(consumer, "git", "add", ".")
    run(consumer, "pre-commit", "install")
    run(consumer, "git", "commit", "-m", "Clean")
    model.write_text("sura = 1\n")
    run(consumer, "git", "add", ".")
    rejected = run(consumer, "git", "commit", "-m", "Rejected", expected=1)
    output = rejected.stdout + rejected.stderr
    assert "Occurrences" in output
    assert any(line.split() == ["sura", "surah", "1"] for line in output.splitlines())
    # A clean working copy must not hide an invalid staged version.
    model.write_text("surah = 1\n")
    run(consumer, "git", "commit", "-m", "Still rejected", expected=1)
    assert model.read_text() == "surah = 1\n"
    run(consumer, "git", "add", ".")
    # Conversely, invalid unstaged work must not block clean staged content.
    model.write_text("sura = 1\n")
    run(consumer, "git", "commit", "-m", "Clean staged content")
    assert model.read_text() == "sura = 1\n"
    model.write_text("surah = 1\n")
    run(consumer, "pre-commit", "run", "--all-files")
    (consumer / "excluded").mkdir()
    (consumer / "excluded/bad.py").write_text("sura = 1\n")
    run(consumer, "git", "add", ".")
    run(consumer, "git", "commit", "-m", "Only excluded change")
    run(consumer, "git", "rm", "a space.py")
    run(consumer, "git", "commit", "-m", "Deletion")
