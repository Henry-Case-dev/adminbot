# -*- coding: utf-8 -*-
"""Smoke tests for the HC-ACCEPT paired acceptance harness.

Local only: synthetic SQLite fixture, fake Bot API, no production, no SSH,
no network.  These tests prove harness mechanics and fail-closed behaviour;
they are NOT acceptance evidence for HC-ACCEPT.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "tools" / "p0_hc_acceptance.py"
CHAT = -1002661910336
TZ = "Asia/Yekaterinburg"
AS_OF_TEXT = "2026-11-20T12:00:00Z"
AS_OF = 1795176000
PINNED_TEXT = "2026-11-20T15:14:26Z"
PINNED_AS_OF = 1795187666
PINNED_TZ = "Asia/Yekaterinburg"


def _load_harness():
    spec = importlib.util.spec_from_file_location("p0_hc_acceptance",
                                                  HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = _load_harness()


def _env():
    env = {key: value for key, value in os.environ.items()
           if key != "PYTHONPATH"}
    env["ADMINBOT_SKIP_DOTENV"] = "1"
    return env


def _run_cli(*args, timeout=900):
    return subprocess.run(
        [sys.executable, str(HARNESS_PATH), *args],
        cwd=str(ROOT), env=_env(), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout)


def _fixture(tmp_path: Path):
    product = h.load_product(str(ROOT))
    db = asyncio.run(h.create_fixture_db(
        product, tmp_path / "_fixture", chat_id=CHAT, as_of=AS_OF, tz=TZ))
    cfg = h.fixture_config(tmp_path / "_fixture", as_of=AS_OF, chat_id=CHAT,
                           tz=TZ)
    return product, db, cfg


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── CLI fixture ─────────────────────────────────────────────────────────────

def test_fixture_history_run_is_compact_and_readonly(tmp_path):
    out = tmp_path / "run"
    proc = _run_cli(
        "--fixture", "--code-root", str(ROOT), "--as-of", AS_OF_TEXT,
        "--chat-id", str(CHAT), "--tz", TZ, "--scenario-set", "history",
        "--out", str(out))
    assert proc.returncode in (0, 1, 3), proc.stderr[-3000:]
    payload = _read(out / "p0-hc-acceptance-candidate.json")
    assert payload["schema"] == "p0-hc-acceptance/1"
    assert payload["mode"] == "fixture"
    assert payload["acceptance_eligible"] is False
    assert payload["variant"] == "candidate"
    assert payload["product_sha"]
    assert payload["snapshot"]["schema"] == 48
    assert payload["snapshot"]["quick_check"] == "ok"
    assert payload["snapshot"]["read_only"] is True
    assert payload["snapshot"]["sha256_before"] == \
        payload["snapshot"]["sha256_after"]
    assert payload["network_guard"] is True
    assert payload["summary"]["payload_scenarios"] == len(
        payload["scenarios"])
    assert payload["payload"]["scenarios"] == payload["scenarios"]
    assert payload["text"]["mode"] == "stub"
    assert payload["text"]["scenarios"] == []
    assert payload["summary"]["scenarios"] == len(payload["scenarios"])
    rows = {row["id"]: row for row in payload["scenarios"]}
    for case_id in ("HIST-10H", "HIST-24H", "HIST-CUSTOM", "HIST-400",
                    "HIST-2000", "HIST-CROSSPAGE", "HIST-LONGTOPIC",
                    "HIST-EMPTY", "HIST-TOOL-ERROR"):
        assert case_id in rows
        row = rows[case_id]
        assert row["status"] in ("pass", "fail", "not_executed",
                                 "not_applicable")
        metrics = row["metrics"]
        for key in ("required_fact_recall", "relevance",
                    "episode_completeness", "temporal_correctness",
                    "participant_attribution", "source_proof",
                    "latency_cost"):
            assert key in metrics
        if metrics["required_fact_recall"].get("applicable") is not False:
            assert "num" in metrics["required_fact_recall"]
            assert "den" in metrics["required_fact_recall"]
    assert rows["HIST-10H"]["status"] == "pass"
    assert rows["HIST-10H"]["checks"]["range_contract"] is True
    assert rows["HIST-10H"]["metrics"]["required_fact_recall"]["den"] > 0
    text = json.dumps(payload, ensure_ascii=False)
    for marker in ("SECRET_ACCEPT_TEXT", "SECRET_TOPIC_TEXT",
                   "Агент Секрет", "SECRET_SAME_TS"):
        assert marker not in text
    assert "year_share" not in text
    assertions = {item["id"]: item["status"]
                  for item in payload["assertions"]}
    assert assertions["SNAPSHOT-READONLY"] == "pass"
    assert assertions["SNAPSHOT-HASH-STABLE"] == "pass"
    assert assertions["NO-TEXT"] == "pass"


def test_fixture_free_speech_stub_is_not_executed(tmp_path):
    out = tmp_path / "fs"
    proc = _run_cli(
        "--fixture", "--code-root", str(ROOT), "--as-of", AS_OF_TEXT,
        "--chat-id", str(CHAT), "--tz", TZ, "--scenario-set",
        "free-speech", "--out", str(out))
    assert proc.returncode in (0, 1, 3), proc.stderr[-3000:]
    payload = _read(out / "p0-hc-acceptance-candidate.json")
    text = payload["text"]
    assert text["mode"] == "stub"
    assert text["status"] == "not_executed"
    assert text["reason"] == "real_text_not_run"
    assert text["static_proof"]["status"] == "pass"
    row = text["scenarios"][0]
    assert row["id"] == "TEXT-FREE-SPEECH"
    assert row["status"] == "not_executed"
    assert payload["requirements"]["HC-ACC-FREE-SPEECH"]["status"] == \
        "not_executed"
    assert payload["requirements"]["HC-ACC-NO-OBJECTIVITY"]["status"] == \
        "not_executed"


def test_fixture_telegram_uses_fake_bot_payloads(tmp_path):
    out = tmp_path / "tg"
    proc = _run_cli(
        "--fixture", "--code-root", str(ROOT), "--as-of", AS_OF_TEXT,
        "--chat-id", str(CHAT), "--tz", TZ, "--scenario-set", "telegram",
        "--out", str(out))
    assert proc.returncode in (0, 1, 3), proc.stderr[-3000:]
    payload = _read(out / "p0-hc-acceptance-candidate.json")
    rows = {row["id"]: row for row in payload["scenarios"]}
    assert set(rows) == {"TG-SHORT", "TG-MARKDOWN", "TG-LITERAL",
                         "TG-HTML-LINK", "TG-CHUNK", "TG-PARTIAL"}
    assert rows["TG-SHORT"]["status"] == "pass"
    assert rows["TG-MARKDOWN"]["status"] == "pass"
    assert rows["TG-HTML-LINK"]["status"] == "pass"
    assert rows["TG-CHUNK"]["status"] == "pass"
    assert rows["TG-PARTIAL"]["status"] == "pass"
    for row in rows.values():
        assert "payload_summary" in row
        for entry in row["payload_summary"]:
            assert "text" not in entry
            assert entry["text_sha256"]
            assert entry["utf16"] <= 4096
    text = json.dumps(payload, ensure_ascii=False)
    assert "Привет, как дела" not in text
    assert "Итог:" not in text


# ── fail-closed inputs ──────────────────────────────────────────────────────

def test_missing_snapshot_is_blocked(tmp_path):
    out = tmp_path / "blocked"
    proc = _run_cli(
        "--code-root", str(ROOT), "--as-of", PINNED_TEXT,
        "--chat-id", str(CHAT), "--tz", PINNED_TZ, "--scenario-set",
        "history", "--out", str(out))
    assert proc.returncode == 2
    payload = _read(out / "p0-hc-acceptance-blocked.json")
    assert payload["status"] == "blocked"
    blockers = {row["id"] for row in payload["blockers"]}
    assert "SNAPSHOT-MISSING" in blockers


def test_missing_config_is_blocked(tmp_path):
    _, db, _ = _fixture(tmp_path)
    out = tmp_path / "blocked-cfg"
    proc = _run_cli(
        "--code-root", str(ROOT), "--snapshot", db, "--as-of", PINNED_TEXT,
        "--chat-id", str(CHAT), "--tz", PINNED_TZ, "--scenario-set",
        "history", "--out", str(out))
    assert proc.returncode == 2
    payload = _read(out / "p0-hc-acceptance-blocked.json")
    blockers = {row["id"] for row in payload["blockers"]}
    assert "CONFIG-MISSING" in blockers


def test_handwritten_config_is_blocked(tmp_path):
    _, db, _ = _fixture(tmp_path)
    cfg = tmp_path / "handwritten.json"
    cfg.write_text(json.dumps({"graph_rag_enabled": True}), encoding="utf-8")
    out = tmp_path / "blocked-prov"
    proc = _run_cli(
        "--code-root", str(ROOT), "--snapshot", db,
        "--effective-config", str(cfg), "--as-of", PINNED_TEXT,
        "--chat-id", str(CHAT), "--tz", PINNED_TZ, "--scenario-set",
        "history", "--out", str(out))
    assert proc.returncode == 2
    payload = _read(out / "p0-hc-acceptance-blocked.json")
    blockers = {row["id"] for row in payload["blockers"]}
    assert "CONFIG-PROVENANCE" in blockers


def test_config_provenance_mismatch_is_blocked(tmp_path):
    _, db, cfg = _fixture(tmp_path)
    raw = json.loads(Path(cfg).read_text(encoding="utf-8"))
    raw["hot_config_measured"] = False
    Path(cfg).write_text(json.dumps(raw), encoding="utf-8")
    out = tmp_path / "blocked-measured"
    proc = _run_cli(
        "--code-root", str(ROOT), "--snapshot", db,
        "--effective-config", cfg, "--as-of", PINNED_TEXT,
        "--chat-id", str(CHAT), "--tz", PINNED_TZ, "--scenario-set",
        "history", "--out", str(out))
    assert proc.returncode == 2
    payload = _read(out / "p0-hc-acceptance-blocked.json")
    blockers = {row["id"] for row in payload["blockers"]}
    assert "CONFIG-PROVENANCE" in blockers


def test_schema_mismatch_is_blocked(tmp_path):
    _, db, cfg = _fixture(tmp_path)
    bad = tmp_path / "schema47.db"
    shutil.copyfile(db, bad)
    conn = sqlite3.connect(str(bad))
    conn.execute("PRAGMA user_version=47")
    conn.commit()
    conn.close()
    out = tmp_path / "blocked-schema"
    proc = _run_cli(
        "--code-root", str(ROOT), "--snapshot", str(bad),
        "--effective-config", cfg, "--as-of", PINNED_TEXT,
        "--chat-id", str(CHAT), "--tz", PINNED_TZ, "--scenario-set",
        "history", "--out", str(out))
    assert proc.returncode == 2
    payload = _read(out / "p0-hc-acceptance-blocked.json")
    blockers = {row["id"] for row in payload["blockers"]}
    assert "SNAPSHOT-SCHEMA" in blockers


# ── scenario mechanics in-process ───────────────────────────────────────────

def test_time_and_channels_scenarios_denominated(tmp_path):
    product, db, _ = _fixture(tmp_path)
    conn_db, conn = asyncio.run(h.open_readonly_service(product, db))
    try:
        time_rows = {}
        for case_id in ("TIME-LAST-SECONDS", "TIME-LOCAL-MIDNIGHT",
                        "TIME-UTC-CHAT", "TIME-DST", "TIME-SAME-TS",
                        "TIME-EDIT", "TIME-FORWARD",
                        "TIME-CURRENT-VS-FACT", "TIME-FACT-EPISODE",
                        "TIME-MONTH-ONLY", "TIME-UNKNOWN"):
            time_rows[case_id] = asyncio.run(h.time_scenario(
                product, conn_db, CHAT, AS_OF, TZ, case_id))
        assert time_rows["TIME-LAST-SECONDS"]["status"] == "pass"
        assert time_rows["TIME-LOCAL-MIDNIGHT"]["status"] == "pass"
        assert time_rows["TIME-FACT-EPISODE"]["status"] == "pass"
        for row in time_rows.values():
            for key in ("required_fact_recall", "temporal_correctness",
                        "source_proof", "latency_cost"):
                assert key in row["metrics"]
        channel_rows = {}
        for case_id in ("CH-FTS", "CH-VECTOR", "CH-GRAPH", "CH-EPISODE",
                        "CH-ARCHIVE", "CH-RECENT", "CH-SUMMARY",
                        "CH-STORAGE-WRITER"):
            channel_rows[case_id] = asyncio.run(h.channels_scenario(
                product, conn_db, CHAT, AS_OF, TZ, case_id))
        assert channel_rows["CH-STORAGE-WRITER"]["status"] == "pass"
        assert channel_rows["CH-STORAGE-WRITER"]["checks"][
            "reply_segment"] is True
        assert channel_rows["CH-STORAGE-WRITER"]["checks"][
            "edit_segment"] is True
        assert channel_rows["CH-STORAGE-WRITER"]["checks"][
            "forward_segment"] is True
        text = json.dumps({"time": time_rows, "channels": channel_rows},
                          ensure_ascii=False)
        assert "SECRET" not in text
    finally:
        asyncio.run(conn.close())


def test_free_speech_is_meta_and_scanner_discriminates():
    assert h.scan_banned("это лишь моё мнение") == ["это лишь моё мнение"]
    assert h.scan_banned("жёсткий субъективный разбор") == []
    row = h.free_speech_scenario({"direct_chat": None}, str(ROOT),
                                 "baseline")
    assert row["status"] == "not_applicable"
    assert row["factual_criterion"] is False


def test_compact_pair_composition_checks_inputs(tmp_path):
    base = {
        "variant": "baseline", "product_sha": h.BASELINE_SHA,
        "snapshot": {"sha256_before": "s", "sha256_after": "s",
                     "schema": 48},
        "effective_config": {"sha256": "c"},
        "as_of": AS_OF, "chat_id": CHAT, "timezone": TZ,
        "status": "fail", "acceptance_eligible": True,
        "scenarios": [
            {"id": "X", "battery": "history",
             "requirement_ids": ["HC-ACC-HISTORY"],
             "status": "fail", "reason": "old"},
            {"id": "FS", "battery": "free-speech",
             "requirement_ids": ["HC-ACC-FREE-SPEECH"],
             "status": "not_applicable", "reason": "baseline"},
        ],
    }
    cand = json.loads(json.dumps(base))
    cand.update({"variant": "candidate", "product_sha": h.CANDIDATE_SHA,
                 "status": "pass"})
    cand["scenarios"][0]["status"] = "pass"
    cand["scenarios"][0]["reason"] = ""
    cand["scenarios"][1]["status"] = "pass"
    cand["scenarios"][1]["reason"] = ""
    pair = h.compose_pair(base, cand, tmp_path)
    assert pair["status"] == "pass"
    assert pair["scenarios"][0]["note"] == "candidate_improved_over_baseline"
    assert pair["scenarios"][1]["status"] == "pass"
    bad = json.loads(json.dumps(cand))
    bad["effective_config"]["sha256"] = "other"
    pair_bad = h.compose_pair(base, bad, tmp_path / "bad")
    assert pair_bad["status"] == "blocked"
    blockers = {row["id"] for row in pair_bad["blockers"]}
    assert "PAIR-CONFIG-MISMATCH" in blockers


def test_no_text_guard_rejects_fixture_text():
    payload = {"scenarios": [{"id": "X", "status": "pass"}],
               "note": "SECRET_ACCEPT_TEXT_1"}
    assert "fixture_marker" in h.validate_no_text(payload)
    payload = {"scenarios": [{"text": "hello"}]}
    assert "scenario_text" in h.validate_no_text(payload)
    assert h.validate_no_text({"scenarios": [{"status": "pass"}]}) == []


def test_production_config_schema_is_supported(tmp_path):
    cfg = tmp_path / "effective.json"
    cfg.write_text(json.dumps({
        "schema": "p0-hc-effective-config/1",
        "read_only": True,
        "measurement_source": ["/proc/123/environ", "settings-import"],
        "production": {"version": "2.58.225",
                       "git_head": h.BASELINE_SHA},
        "model_identity": {"LLM_MODEL_NAME": "deepseek-v4-flash",
                           "EMBEDDING_MODEL_NAME": "gemini-embedding-001"},
        "provider_hosts": {"LLM_BASE_URL": "https://nano-gpt.com"},
        "time": {"CHAT_TIMEZONE": "", "GOODMORNING_TZ": PINNED_TZ},
        "memory_history_egress_flags": {"GRAPH_RAG_ENABLED": True},
        "budgets": {"CHAT_MODEL_CONTEXT_WINDOW": None,
                    "MODEL_CAPACITY_RESOLVER_ENABLED": True,
                    "CHAT_CONTEXT_BUDGET_TOKENS": 24000,
                    "CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS": 32000,
                    "CHAT_CONTEXT_FILL_RATIO": 0.8},
        "secret_env_names_only": ["LLM_API_KEY", "POSTGRES_DSN"],
    }), encoding="utf-8")
    loaded = h.load_config(str(cfg), as_of=PINNED_AS_OF, chat_id=CHAT,
                           tz=PINNED_TZ, expected_release="2.58.225",
                           fixture=False)
    assert loaded["model"] == "deepseek-v4-flash"
    assert loaded["embedding_model"] == "gemini-embedding-001"
    assert loaded["timezone"] == PINNED_TZ
    assert loaded["timezone_source"] == "factory_default_empty_chat_timezone"
    assert loaded["model_context_window"] is None
    assert loaded["model_capacity_resolver"] is True
    assert loaded["secret_names_count"] == 2


def test_parse_as_of_accepts_iso_and_epoch():
    assert h.parse_as_of("2026-11-20T12:00:00Z") == AS_OF
    assert h.parse_as_of(str(AS_OF)) == AS_OF
    with pytest.raises(ValueError):
        h.parse_as_of("")
