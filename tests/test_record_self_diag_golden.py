"""SELF-DIAG-01 D6-19 (T17-T19): запись golden-прогона без выдуманных чисел."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record_self_diag_golden.py"

# Внешний golden-модуль импортирует пакет из КОРНЯ репозитория: так проверяется,
# что CLI сам подкладывает ROOT в `sys.path` при запуске по пути скрипта.
FOREIGN_GOLDEN = '''
from services import mca_events  # noqa: F401  (импорт из корня репозитория)
import pytest

CASES = [{"id": "G-PASS", "category": "style", "dimension": ["style"]}]


@pytest.mark.parametrize("case_id", ["G-PASS"])
def test_golden_case(case_id):
    assert case_id == "G-PASS"
'''


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "_record_self_diag_golden_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CASES = [
    {"id": "G-FAIL-HALL", "category": "negative",
     "dimension": ["hallucination", "scope"]},
    {"id": "G-FAIL-ACC", "category": "known_cause", "dimension": ["accuracy"]},
    {"id": "G-PASS", "category": "style", "dimension": ["style"]},
]


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_self_diag_golden"
            name="test_golden_case[G-FAIL-HALL]">
    <failure message="выдуманная причина">traceback</failure>
  </testcase>
  <testcase classname="tests.test_self_diag_golden"
            name="test_golden_case[G-FAIL-ACC]">
    <failure message="факт неверен">traceback</failure>
  </testcase>
  <testcase classname="tests.test_self_diag_golden"
            name="test_golden_case[G-PASS]"/>
  <testcase classname="tests.test_self_diag_golden"
            name="test_golden_dataset_shape_and_coverage"/>
</testsuite></testsuites>
"""


def test_junit_fixture_counts_and_false_diagnosis(tmp_path):
    module = _load_script()
    junit = tmp_path / "golden.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    outcomes = module.parse_junit(junit)
    assert outcomes["G-FAIL-HALL"] == "failed"
    assert outcomes["G-PASS"] == "passed"
    payload = module.build_payload(
        CASES, outcomes, code_sha="a" * 40, dirty=False)
    assert payload["case_total"] == 3
    assert payload["passed"] == 1
    assert payload["failed"] == 2
    assert payload["skipped"] == 0
    assert payload["error"] == 0
    assert payload["false_diagnosis"] == 1
    assert payload["false_diagnosis_ids"] == ["G-FAIL-HALL"]
    assert payload["by_category"] == {
        "negative": 1, "known_cause": 1, "style": 1}
    assert payload["code_sha"] == "a" * 40
    assert payload["schema"] == 1

    many = [{"id": f"G{i:02d}", "category": "negative",
             "dimension": ["hallucination"]} for i in range(25)]
    failed = {f"G{i:02d}": "failed" for i in range(25)}
    bounded = module.build_payload(
        many, failed, code_sha=None, dirty=None)
    assert bounded["false_diagnosis"] == 25
    assert len(bounded["false_diagnosis_ids"]) == 20


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    module = _load_script()
    junit = tmp_path / "golden.xml"

    def _fake_pytest(test_path, junit_path):
        Path(junit_path).write_text(JUNIT, encoding="utf-8")
        return 1

    def _forbidden_record(*args, **kwargs):
        raise AssertionError("--dry-run не должен писать событие")

    monkeypatch.setattr(module, "load_cases", lambda path=None: CASES)
    monkeypatch.setattr(module, "_run_pytest", _fake_pytest)
    monkeypatch.setattr(module, "_record_event", _forbidden_record)
    assert module.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "cases=3" in out
    assert "false_diagnosis=1" in out


def test_missing_case_metadata_fails_loudly(monkeypatch, capsys):
    module = _load_script()

    def _broken_load(path=None):
        raise module.GoldenMetadataError("CASES missing or empty")

    def _must_not_run(*args, **kwargs):
        raise AssertionError("pytest не должен запускаться без метаданных")

    def _must_not_record(*args, **kwargs):
        raise AssertionError("частичное событие запрещено")

    monkeypatch.setattr(module, "load_cases", _broken_load)
    monkeypatch.setattr(module, "_run_pytest", _must_not_run)
    monkeypatch.setattr(module, "_record_event", _must_not_record)
    assert module.main(["--dry-run"]) != 0
    err = capsys.readouterr().err
    assert "metadata error" in err


def _run_cli(args, cwd):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=600, env=env)


def test_cli_runs_as_plain_script_and_as_module(tmp_path):
    """CLI работает и `python scripts/...`, и `python -m scripts...`.

    Запуск по пути скрипта кладёт в `sys.path` каталог `scripts`, а не корень
    репозитория; внешний golden-модуль импортирует `services`, поэтому без
    бутстрапа корня прогон падает с metadata error (rc=2).
    """
    golden = tmp_path / "foreign_golden.py"
    golden.write_text(FOREIGN_GOLDEN, encoding="utf-8")
    args = ["--dry-run", "--golden-tests", str(golden)]

    plain = _run_cli([str(SCRIPT), *args], cwd=tmp_path)
    assert plain.returncode == 0, plain.stderr
    assert "cases=1" in plain.stdout
    assert "passed=1" in plain.stdout
    assert "metadata error" not in plain.stderr

    module_form = _run_cli(
        ["-m", "scripts.record_self_diag_golden", *args], cwd=ROOT)
    assert module_form.returncode == 0, module_form.stderr
    assert "cases=1" in module_form.stdout
    assert "passed=1" in module_form.stdout
    assert "metadata error" not in module_form.stderr
