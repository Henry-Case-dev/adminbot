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
    assert assertions["MEM07-SNAPSHOT"] == "pass"
    assert assertions["MEM07-QUESTIONS"] == "pass"
    assert assertions["MEM07-REFERENCES"] == "pass"
    assert assertions["MEM07-TRACE"] == "pass"
    assert assertions["MEM07-METRICS"] == "pass"
    assert assertions["MEM07-CONTROLS"] == "pass"
    assert assertions["MEM07-NO-TEXT"] == "pass"
    assert assertions["MEM07-READONLY"] == "pass"
    assert assertions["MEM07-NO-NETWORK"] == "pass"
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
    for q in matrix:
        m = q["metrics"]
        for key in ("coverage", "chrono", "relevance", "fabricated"):
            assert key in m
        assert m["coverage"]["anchor"]["den"] > 0
        assert m["relevance"]["den"] > 0
        assert m["fabricated"]["den"] > 0
        assert "text" not in m and "fact" not in m
    assert payload["classes"]
    assert payload["time03"] and payload["time07"]
    assert payload["controls"]["N1"]["metrics"]["negative"]["pass"] is True
    assert payload["controls"]["N2"]["metrics"]["negative"]["pass"] is True
    assert payload["controls"]["X1"]["metrics"]["counterexample"]["pass"] is True
    text = json.dumps(payload, ensure_ascii=False)
    assert "SECRET_FACT_TEXT_MEM07" not in text
    assert "SECRET_MSG_TEXT_MEM07" not in text
    assert "Участник Один" not in text
    assert "Участник Два" not in text


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