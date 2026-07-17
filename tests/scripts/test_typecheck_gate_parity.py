"""Static contract keeping local type checks aligned with CI."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_strict_mypy_runs_in_ci_fast_verify_and_pre_commit() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    verify = (_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    pre_commit = (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "- name: mypy --strict\n        run: uv run mypy" in ci
    assert 'run_gate "mypy (strict)" uv run mypy' in verify
    assert verify.index('run_gate "mypy (strict)" uv run mypy') < verify.index(
        'if [[ "$MODE" == "full" ]]'
    )
    assert "- id: mypy-strict" in pre_commit
    assert "entry: uv run mypy" in pre_commit
    assert (
        "pass_filenames: false" in pre_commit.split("- id: mypy-strict", 1)[1].split("- id:", 1)[0]
    )
    assert '"scripts/**" = ["N999", "S603", "S607"]' in pyproject
