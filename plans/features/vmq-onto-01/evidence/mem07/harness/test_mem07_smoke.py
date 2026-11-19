# -*- coding: utf-8 -*-
"""Smoke tests for the VMQ-MEM-07 independent harness (synthetic only)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
HARNESS = Path(__file__).with_name("mem07.py")
OWNER = "напиши юмористический рассказ об основных шизах конфы"


def _run(args, tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(HARNESS), *args, "--code-root", str(ROOT)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300)
    return proc


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_dry_run(tmp_path):
    out = tmp_path / "dry"
    proc = _run(["--dry-run", "--out", str(out)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    data = json.loads(proc.stdout)
    assert data["candidate"].startswith("0fce97a14")
    assert data["expected_schema"] == 48


def test_fixture_run_structural(tmp_path):
    out = tmp_path / "fixture"
    proc = _run(["--fixture", "--out", str(out)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-4000:]
    payload = _load(out / "fixture.json")
    assert payload["mode"] == "fixture"
    assert payload["candidate_sha"].startswith("0fce97a14")
    assert payload["snapshot"]["quick_check"] == "ok"
    assert payload["snapshot"]["user_version"] == 48
    assert payload["snapshot_sha256_after"] == payload["snapshot"]["sha256"]
    assertions = {a["id"]: a["status"] for a in payload["assertions"]}
    for aid in ("MEM07-SNAPSHOT", "MEM07-QUESTIONS", "MEM07-CONFIG",
                "MEM07-REFERENCES", "MEM07-TRACE", "MEM07-METRICS",
                "MEM07-CONTROLS", "MEM07-NO-TEXT", "MEM07-DIAGNOSTICS",
                "MEM07-PRIVACY", "MEM07-BUILDER-DIFF", "MEM07-OLDEP-2023",
                "MEM07-OLDEP-2024", "MEM07-READONLY", "MEM07-NO-NETWORK"):
        assert assertions[aid] == "pass", (aid, assertions)
    matrix = [q for q in payload["questions"] if q["class"] in "HRPCE"]
    assert len(matrix) == 12
    assert sum(1 for q in matrix if q["class"] == "H") == 2
    assert sum(1 for q in matrix if q["class"] == "R") == 4
    assert sum(1 for q in matrix if q["class"] == "P") == 2
    assert sum(1 for q in matrix if q["class"] == "C") == 2
    assert sum(1 for q in matrix if q["class"] == "E") == 2
    assert {q["id"] for q in payload["questions"]} >= {"N1", "N2", "X1"}
    h1 = next(q for q in payload["questions"] if q["id"] == "H1")
    assert h1["query_template"] == OWNER
    assert len(h1["query_sha256"]) == 64
    auto = h1["policies"]["auto"]
    assert auto["retrieval_path"] == "unified"
    assert auto["period_present"] is True
    assert "authors" in auto
    assert "bundle_ref_count" in auto
    assert "block_tags" in auto["writer"]
    for q in matrix:
        m = q["metrics"]
        for key in ("coverage", "chrono", "relevance", "fabricated"):
            assert key in m
        assert m["coverage"]["anchor"]["den"] > 0
        assert m["relevance"]["den"] > 0
        assert m["fabricated"]["den"] > 0
        assert m["semantic"]["old_coverage"]["den"] > 0
        assert m["chrono_period"]["den"] > 0
        assert "text" not in m and "fact" not in m
    assert payload["classes"]
    assert payload["time03"] and payload["time07"]
    for qid in ("N1", "N2"):
        neg = payload["controls"][qid]["policies"]["historical"]["metrics"]["negative"]
        assert neg["pass"] is True and neg["old_rows"] > 0
    x = payload["controls"]["X1"]["policies"]["historical"]["metrics"]["counterexample"]
    assert x["pass"] is True and x["old_present"] and x["new_present"]
    oldep = payload["old_episode"]
    for key in ("2023", "2024"):
        assert oldep[key]["messages"] > 0
        assert oldep[key]["spans"] > 0
        assert oldep[key]["resolved_sources"] > 0
    assert len(payload["builder_comparison"]) >= 12
    diag = payload["diagnostics"]
    assert len(diag["log_sha256"]) == 64
    assert diag["unexpected_errors"] == 0
    assert diag["unexpected_tracebacks"] == 0
    cfg = payload["configuration"]
    assert cfg["graph_rag_enabled"] is True
    assert cfg["graph_rag_facts_limit"] > 0
    assert cfg["config_source"] in ("settings_instance", "effective_config_file")
    text = json.dumps(payload, ensure_ascii=False)
    assert "SECRET_FACT_TEXT_MEM07" not in text
    assert "SECRET_MSG_TEXT_MEM07" not in text
    assert "Участник Один" not in text
    assert "Участник Два" not in text


def test_effective_config_gate(tmp_path):
    out = tmp_path / "gate"
    cfg = tmp_path / "effective.json"
    cfg.write_text(json.dumps({"graph_rag_enabled": False,
                               "graph_rag_facts_limit": 0}), encoding="utf-8")
    proc = _run(["--fixture", "--effective-config", str(cfg),
                 "--out", str(out)], tmp_path)
    assert proc.returncode == 2, proc.stderr[-2000:]
    payload = _load(out / "fixture.json")
    assert payload["technical_reason"] == "graph_rag_disabled"
    assert payload["configuration"]["graph_rag_enabled"] is False
    assert payload["assertions"][0]["status"] == "not_executed"


def test_missing_snapshot_is_not_executed(tmp_path):
    out = tmp_path / "missing"
    missing = tmp_path / "absent.db"
    proc = _run(["--db", str(missing), "--out", str(out)], tmp_path)
    assert proc.returncode == 2, proc.stderr[-2000:]
    payload = _load(out / "mem07-independent.json")
    assert payload["technical_reason"].startswith("snapshot_")
    assert payload["assertions"][0]["status"] == "not_executed"


def test_fixture_outputs_have_no_text_leak(tmp_path):
    out = tmp_path / "fixture2"
    proc = _run(["--fixture", "--out", str(out)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for path in out.iterdir():
        if path.is_file():
            data = path.read_text(encoding="utf-8", errors="replace")
            assert "SECRET_FACT_TEXT_MEM07" not in data
            assert "SECRET_MSG_TEXT_MEM07" not in data
            assert "Участник Один" not in data
            assert "Участник Два" not in data


def test_fixture_snapshot_is_unchanged(tmp_path):
    out = tmp_path / "fixture3"
    proc = _run(["--fixture", "--out", str(out)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = _load(out / "fixture.json")
    assert payload["snapshot"]["sha256"] == payload["snapshot_sha256_after"]
    hashes = (out / "fixture-hashes.txt").read_text(encoding="utf-8")
    assert "snapshot_sha256_before:" in hashes
    assert "snapshot_sha256_after:" in hashes
    assert payload["snapshot"]["sha256"] in hashes