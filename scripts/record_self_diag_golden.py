"""SELF-DIAG-01 D6 (`SD1-D6-19`): записать один прогон golden-набора.

Запускает СУЩЕСТВУЮЩИЙ `tests/test_self_diag_golden.py` через pytest и пишет
ОДНО событие `self_diag_golden_run` в существующий `mca_events`. Второго
диагностического движка, новых таблиц и LLM в запросе нет: набор и кейсы те
же, запуск офлайн (по требованию/в релизном прогоне).

Правила:
* метаданные кейсов импортируются из того же тест-модуля; нет `CASES` —
  громкий ненулевой код возврата и НИ ОДНОГО события (T19);
* `false_diagnosis` — упавший кейс с `dimension` из {hallucination, scope}
  (выдуманная причина/утечка scope), список id ограничен 20;
* `--dry-run` печатает агрегаты и не пишет в БД (T18);
* временный junit-файл удаляется в `finally`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_TEST_PATH = ROOT / "tests" / "test_self_diag_golden.py"
GOLDEN_EVENT_NAME = "self_diag_golden_run"
GOLDEN_SCHEMA = 1
FALSE_DIAGNOSIS_DIMENSIONS = ("hallucination", "scope")
FALSE_DIAGNOSIS_IDS_LIMIT = 20
_CASE_NAME_RE = re.compile(r"^test_golden_case\[(?P<case>.+)\]$")


class GoldenMetadataError(RuntimeError):
    """CASES недоступны/пусты — прогон не записывается."""


class GoldenRunError(RuntimeError):
    """pytest/junit не дали пригодного результата."""


def load_cases(path: Path | None = None) -> list[dict]:
    """Импортировать `CASES` из существующего golden-модуля (метаданные)."""
    target = Path(path or GOLDEN_TEST_PATH)
    if not target.exists():
        raise GoldenMetadataError(f"golden set not found: {target.name}")
    spec = importlib.util.spec_from_file_location(
        "_self_diag_golden_cases", target)
    if spec is None or spec.loader is None:
        raise GoldenMetadataError("golden set is not importable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:      # pragma: no cover - защитная ветка
        raise GoldenMetadataError(
            f"golden set import failed: {type(exc).__name__}") from exc
    cases = getattr(module, "CASES", None)
    if not isinstance(cases, (list, tuple)) or not cases:
        raise GoldenMetadataError("CASES missing or empty")
    return [dict(case) for case in cases]


def parse_junit(path: Path) -> dict:
    """id кейса → `passed|failed|skipped|error` из реального junit XML."""
    try:
        tree = ET.parse(str(path))
    except Exception as exc:
        raise GoldenRunError(
            f"junit unreadable: {type(exc).__name__}") from exc
    outcomes: dict = {}
    for node in tree.iter("testcase"):
        name = str(node.get("name") or "")
        match = _CASE_NAME_RE.match(name)
        if not match:
            continue
        case_id = match.group("case")
        outcome = "passed"
        for child in node:
            tag = str(child.tag or "").split("}")[-1]
            if tag == "failure":
                outcome = "failed"
                break
            if tag == "error":
                outcome = "error"
                break
            if tag == "skipped":
                outcome = "skipped"
        outcomes[case_id] = outcome
    return outcomes


def build_payload(cases: list, outcomes: dict, *, code_sha: str | None,
                  dirty: bool | None, runner: str = "pytest") -> dict:
    """Агрегаты прогона по метаданным CASES и исходам junit."""
    ids = [str(case.get("id") or "") for case in cases]
    ids = [case_id for case_id in ids if case_id]
    if not ids:
        raise GoldenMetadataError("CASES без id")
    failed_ids: list[str] = []
    errors = 0
    skipped = 0
    for case_id in ids:
        outcome = outcomes.get(case_id, "missing")
        if outcome == "skipped":
            skipped += 1
        elif outcome in ("failed", "error", "missing"):
            failed_ids.append(case_id)
            if outcome == "error":
                errors += 1
    passed = len(ids) - len(failed_ids) - skipped
    dimensions = {str(case.get("id") or ""): [
        str(item) for item in (case.get("dimension") or [])]
        for case in cases}
    false_ids = []
    for case_id in failed_ids:
        if outcomes.get(case_id) == "missing":
            continue
        if any(dim in FALSE_DIAGNOSIS_DIMENSIONS
               for dim in dimensions.get(case_id, [])):
            false_ids.append(case_id)
    by_category: dict = {}
    for case in cases:
        category = str(case.get("category") or "unknown")[:60]
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "schema": GOLDEN_SCHEMA,
        "case_total": len(ids),
        "passed": passed,
        "failed": len(failed_ids),
        "skipped": skipped,
        "error": errors,
        "false_diagnosis": len(false_ids),
        "false_diagnosis_ids": false_ids[:FALSE_DIAGNOSIS_IDS_LIMIT],
        "by_category": by_category,
        "code_sha": code_sha,
        "dirty": dirty,
        "runner": runner,
    }


def _run_pytest(test_path: Path, junit_path: Path) -> int:
    """Существующий pytest-прогон (без сети/LLM в этом процессе)."""
    command = [sys.executable, "-m", "pytest", str(test_path), "-q",
               f"--junitxml={junit_path}"]
    completed = subprocess.run(
        command, cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=3600)
    return int(completed.returncode)


def _git_state() -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
            text=True, timeout=20, check=True).stdout.strip().lower()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(ROOT), capture_output=True, text=True,
            timeout=20, check=True).stdout
        return (sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None,
                bool(status.strip()))
    except Exception:
        return None, None


def _db_path() -> str:
    try:
        from config.settings import settings
        return str(getattr(settings, "DB_PATH", "local_database.db"))
    except Exception:      # pragma: no cover - защитная ветка
        return "local_database.db"


def _record_event(payload: dict, db_path: str, duration_ms: int) -> None:
    """Одно событие `self_diag_golden_run` + flush в существующий стор."""
    async def _run():
        from services import mca_events
        from services.database import DatabaseService
        db = DatabaseService(str(db_path))
        await db.initialize()
        try:
            failed = int(payload.get("failed") or 0)
            mca_events.emit_mca_event(
                GOLDEN_EVENT_NAME,
                outcome=("success" if failed == 0 else "failed"),
                level=("INFO" if failed == 0 else "WARN"),
                component="self_diag", stage="golden",
                duration_ms=int(duration_ms), source_ref_json=payload)
            await mca_events.flush_events(db)
        finally:
            await db.close()

    asyncio.run(_run())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Записать прогон golden-набора в mca_events")
    parser.add_argument("--dry-run", action="store_true",
                        help="напечатать агрегаты без записи в БД")
    parser.add_argument("--golden-tests", default=str(GOLDEN_TEST_PATH),
                        help="путь к существующему test_self_diag_golden.py")
    parser.add_argument("--db-path", default=None,
                        help="SQLite-БД (по умолчанию settings.DB_PATH)")
    args = parser.parse_args(argv)
    test_path = Path(args.golden_tests)
    try:
        cases = load_cases(test_path)
        if not cases:
            raise GoldenMetadataError("CASES пуст")
    except GoldenMetadataError as exc:
        print(f"self-diag golden: metadata error: {exc}", file=sys.stderr)
        return 2

    tmp_dir = tempfile.mkdtemp(prefix="self_diag_golden_")
    junit_path = Path(tmp_dir) / "golden.xml"
    started = time.monotonic()
    try:
        returncode = _run_pytest(test_path, junit_path)
        duration_ms = int((time.monotonic() - started) * 1000)
        if returncode not in (0, 1):
            print(f"self-diag golden: pytest rc={returncode}", file=sys.stderr)
            return 2
        try:
            outcomes = parse_junit(junit_path)
        except GoldenRunError as exc:
            print(f"self-diag golden: {exc}", file=sys.stderr)
            return 2
        code_sha, dirty = _git_state()
        payload = build_payload(
            cases, outcomes, code_sha=code_sha, dirty=dirty)
    finally:
        try:
            junit_path.unlink()
        except Exception:
            pass
        try:
            Path(tmp_dir).rmdir()
        except Exception:
            pass

    print(
        "self-diag golden: cases={case_total} passed={passed} "
        "failed={failed} skipped={skipped} error={error} "
        "false_diagnosis={false_diagnosis} code={code_sha} "
        "dirty={dirty}".format(**payload))
    if args.dry_run:
        return 0
    try:
        _record_event(payload, str(args.db_path or _db_path()), duration_ms)
    except Exception as exc:
        print(f"self-diag golden: record failed: {type(exc).__name__}",
              file=sys.stderr)
        return 2
    return 1 if int(payload.get("failed") or 0) else 0


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
