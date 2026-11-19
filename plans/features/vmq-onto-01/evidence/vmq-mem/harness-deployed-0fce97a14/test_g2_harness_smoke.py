# -*- coding: utf-8 -*-
"""Local smoke test for the VMQ-MEM-06 G2 harness (synthetic only).

Not product tests: it exercises imports, the fixture, the assertion plumbing
and the no-message/fact-text guarantee. It never touches production.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CODE_ROOT = HERE.parents[5]
HARNESS = HERE / "measure_g2.py"
FIXTURE = HERE / "make_fixture.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_paths():
    if str(CODE_ROOT) not in sys.path:
        sys.path.insert(0, str(CODE_ROOT))
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))


def _run_harness(db_path: str, out_dir: Path, *extra) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HARNESS), "--db", db_path,
           "--chat-id", "-1002661910336", "--out", str(out_dir),
           "--code-root", str(CODE_ROOT), *extra]
    return subprocess.run(cmd, cwd=str(CODE_ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=900)


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    _ensure_paths()
    make_fixture = _load(FIXTURE, "make_fixture_g2")
    db_path = str(tmp_path_factory.mktemp("db") / "fixture.db")
    import asyncio
    meta = asyncio.run(make_fixture.build_fixture(
        db_path, chat_id=-1002661910336))
    return db_path, meta


def test_harness_outputs_and_assertions(fixture_db, tmp_path):
    db_path, meta = fixture_db
    out = tmp_path / "out"
    proc = _run_harness(db_path, out, "--fixture")
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads((out / "g2-mem06.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "vmq-mem06-g2/1"
    assert payload["mode"] == "fixture"
    assert payload["candidate_sha"].startswith("0fce97a14")
    assert payload["snapshot"]["quick_check"] == "ok"
    assert payload["snapshot"]["user_version"] and payload["snapshot"]["user_version"] > 0
    assert payload["snapshot_sha256"] == payload["snapshot_sha256_after"]
    assert payload["product_diff_clean"] is True
    assert set(payload["configuration"]) >= {
        "retrieval_context", "evidence_bundle", "typed_reranker",
        "memory_communities", "event_contract", "telemetry_store",
        "speech_projection",
    }
    assert payload["topics"] == [
        "шизы конфы", "напиши юмористический рассказ об основных шизах конфы"]
    ids = [item["id"] for item in payload["assertions"]]
    assert ids == [
        "MEM06-A1-AUTO", "MEM06-A1-HIST", "MEM06-A1P-AUTO",
        "MEM06-A1P-HIST", "MEM06-D2023", "MEM06-T2-AUTO",
        "MEM06-T2-PLANHIST", "MEM06-T3-CURRENT", "MEM06-OLD23",
        "MEM06-OLDP", "MEM06-P1", "MEM06-P2", "MEM06-P3",
        "MEM06-THEMATIC", "MEM06-LORE-GRAPH", "MEM06-LORE-DENSE",
        "MEM06-G1-HINTS", "MEM06-G4-REFS", "MEM06-CHAT-SCOPE",
    ]
    for item in payload["assertions"]:
        assert item["status"] in ("pass", "fail", "not_executed")
        assert isinstance(item["actual"], dict)
    statuses = {item["id"]: item["status"] for item in payload["assertions"]}
    # The synthetic fixture is shaped so every contract path really executes;
    # all 19 assertions must pass (no silently "not_executed" probe).
    for aid in ids:
        assert statuses[aid] == "pass", (aid, statuses, proc.stderr[-2000:])
    # The Writer record is part of §5.2 and must be exercised, not skipped.
    writer = payload["classes"]["A1_auto"]["writer"]
    assert writer["rag_rendered"] is True
    assert int(writer["rag_chars"]) > 0
    assert "episode_rendered" in writer
    assert "episode_skip" in writer
    # §5.1 environment: venv Python 3.12 and a genuinely loaded sqlite-vec;
    # the failing embed probe is the expected reason the vector leg is off.
    environment = payload["environment"]
    assert environment["python_version"].startswith("3.12")
    assert environment["sqlite_vec_import"] is True
    assert environment["sqlite_vec_loaded"] is True
    assert environment["sqlite_vec_off_reason"] == "embed"
    assert environment["vec_ok"] is False
    assert payload["configuration"]["sqlite_vec_loaded"] is True
    assert (out / "g2-mem06-summary.md").exists()
    hashes = (out / "g2-mem06-hashes.txt").read_text(encoding="utf-8")
    assert "snapshot_sha256=" in hashes
    assert "harness_combined_sha256=" in hashes

    # No message/fact text in any output (fixture marks both).
    all_text = "\n".join(
        p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file())
    for marker in meta["secret_markers"]:
        assert marker not in all_text, marker


def test_missing_snapshot_publishes_not_executed(tmp_path):
    _ensure_paths()
    out = tmp_path / "missing"
    proc = _run_harness(str(tmp_path / "absent.db"), out)
    assert proc.returncode == 2, proc.stderr[-2000:]
    payload = json.loads((out / "g2-mem06.json").read_text(encoding="utf-8"))
    assert payload["technical_reason"].startswith("snapshot_")
    assert [item["id"] for item in payload["assertions"]] == [
        "MEM06-A1-AUTO", "MEM06-A1-HIST", "MEM06-A1P-AUTO",
        "MEM06-A1P-HIST", "MEM06-D2023", "MEM06-T2-AUTO",
        "MEM06-T2-PLANHIST", "MEM06-T3-CURRENT", "MEM06-OLD23",
        "MEM06-OLDP", "MEM06-P1", "MEM06-P2", "MEM06-P3",
        "MEM06-THEMATIC", "MEM06-LORE-GRAPH", "MEM06-LORE-DENSE",
        "MEM06-G1-HINTS", "MEM06-G4-REFS", "MEM06-CHAT-SCOPE",
    ]
    assert all(item["status"] == "not_executed"
               for item in payload["assertions"])
    assert (out / "g2-mem06-summary.md").exists()
    assert (out / "g2-mem06-hashes.txt").exists()


def test_evaluate_status_plumbing():
    _ensure_paths()
    mod = _load(HARNESS, "measure_g2_eval")
    assertions = mod.evaluate({}, {}, {}, {}, {}, {}, {}, {})
    assert [item["id"] for item in assertions] == list(mod.ASSERTION_IDS)
    assert {item["status"] for item in assertions} <= {
        "pass", "fail", "not_executed"}
    # Empty input cannot be "pass"; class-dependent ones must be honest
    # not_executed, not fabricated evidence.
    assert all(item["status"] != "pass" for item in assertions)
    assert any(item["status"] == "not_executed" for item in assertions)


def test_old_episode_plain_composition_not_a_false_failure():
    """A correct empty plain episode must not fail on a tail/ref skip."""
    _ensure_paths()
    mod = _load(HARNESS, "measure_g2_oldp")
    plain = {
        "empty": True, "hits": 0, "messages": 0,
        "candidate_composition": {"episode": 0, "graph_fact": 0,
                                  "message": 3, "other": 0},
        "candidate_message_tail": 3,
        "candidate_message_unparseable": 0,
        "episode_max_count": 8,
    }
    assertions = mod.evaluate(
        {}, {"Old_Episode_plain": plain}, {}, {}, {}, {}, {}, {})
    oldp = next(item for item in assertions if item["id"] == "MEM06-OLDP")
    assert oldp["status"] == "pass"
    assert oldp["actual"]["explanation"] == "tail_or_ref_filter"
    # Non-empty plain episode is the regression signal.
    plain["empty"] = False
    assertions = mod.evaluate(
        {}, {"Old_Episode_plain": plain}, {}, {}, {}, {}, {}, {})
    oldp = next(item for item in assertions if item["id"] == "MEM06-OLDP")
    assert oldp["status"] == "fail"


if __name__ == "__main__":
    # Standalone fallback for environments where pytest collection is not
    # available; the pytest functions above stay the canonical test.
    import asyncio
    import tempfile

    _ensure_paths()
    make_fixture = _load(FIXTURE, "make_fixture_g2")
    root = Path(tempfile.mkdtemp(prefix="vmq-g2-selftest-"))
    db_path = str(root / "fixture.db")
    meta = asyncio.run(make_fixture.build_fixture(
        db_path, chat_id=-1002661910336))
    if len(sys.argv) > 2 and sys.argv[1] == "--db":
        # Reuse an already-built synthetic fixture (faster smoke run).
        db_path = sys.argv[2]
        meta = {"secret_markers": [make_fixture.SECRET_FACT_TEXT,
                                   make_fixture.SECRET_MSG_TEXT]}
    tmp = root / "out"
    tmp.mkdir()
    test_harness_outputs_and_assertions((db_path, meta), tmp)
    test_missing_snapshot_publishes_not_executed(root / "missing")
    test_evaluate_status_plumbing()
    test_old_episode_plain_composition_not_a_false_failure()
    print("SELFTEST_OK", root)
