"""S5 round1026 (ADR-1026-7 D1/D4/D6) — тесты L2 «Писатель» (§96–§99).

Покрытие: SC-01 (контракт §99), SC-06/SC-07 (§97-запреты/цитаты), SC-08
(изоляция входа), SC-09 (§106 fail-closed), SC-10 (слот §82), SC-11 (канон),
SC-13 (R17-логи).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANON_PATH = ROOT / "plans" / "docs" / "canon" / "architecture.md"

from config.settings import settings
from services import param_catalog as pc
from services import prompt_migrations as pm
from services.summary_l2_writer import (
    L2Slot,
    L2SlotError,
    MAX_PARAGRAPHS_HARD,
    PROMPT_PG_KEY,
    REASON_BAD_SCHEMA_VERSION,
    REASON_EMPTY_RESPONSE,
    REASON_INVALID_JSON,
    REASON_PACKAGE_NOT_DELIVERABLE,
    REASON_QUOTE_ATTRIBUTION,
    REASON_TOO_MANY_PARAGRAPHS,
    REASON_UNKNOWN_FIELD,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
    build_l2_input,
    parse_l2_document,
    resolve_l2_slot,
    resolve_l2_slot_safe,
    run_l2,
    validate_l2_document,
)
from services.prompt_style_blocks import resolve_prompt
from services.summary_prompts import (
    PREV_SUMMARY_L2_WRITER_R1026,
    SUMMARY_L2_WRITER_SYSTEM_PROMPT,
)
from services.target_marking import TARGET_INSTRUCTION_BLOCK


# ── Фикстуры ───────────────────────────────────────────────────────────────

def _package(*, status="ok", threads=None, service=None) -> dict:
    if threads is None:
        threads = [{
            "thread_id": "thread_001",
            "name": "Погода и планы",
            "description": "Обсуждали дождь и поездку.",
            "chronology": [
                {"message_id": 101, "timestamp": 1000},
                {"message_id": 102, "timestamp": 1001},
            ],
            "facts": [
                {"text": "На улице шёл сильный дождь",
                 "evidence_message_ids": [101]},
                {"text": "Поездка отложена на выходные",
                 "evidence_message_ids": [102]},
            ],
            "evidence_ids": [101, 102],
            "fragments": [
                {"message_id": 101, "timestamp": 1000,
                 "text": "На улице шёл сильный дождь"},
                {"message_id": 102, "timestamp": 1001,
                 "text": "Поездку решили перенести"},
            ],
        }]
    return {
        "schema_version": 1,
        "status": status,
        "threads": threads,
        "unassigned_message_ids": [103],
        "service": service or {"response_mode": "serious", "cover_prompt": "rain"},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 42, "fits": True},
    }


def _doc(title="Дождливый день", paragraphs=None) -> dict:
    if paragraphs is None:
        paragraphs = [
            {"text": "В чате обсудили погоду и планы.", "emphasis": None},
        ]
    return {"schema_version": 1, "title": title, "paragraphs": paragraphs}


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.response


class _SlotStub:
    base_url = "https://api.test"
    model = "l2-model"
    api_key = "secret-key-xyz"
    dedicated = False


# ── SC-01: контракт §99 ────────────────────────────────────────────────────

class TestParseValidate:
    def test_valid_document_ok(self):
        document, metrics = validate_l2_document(_doc(), _package())
        assert document is not None
        assert metrics["status"] == STATUS_OK
        assert document["schema_version"] == 1
        assert document["paragraphs"][0]["emphasis"] is None

    def test_extra_top_field_invalid(self):
        bad = _doc()
        bad["extra"] = 1
        document, metrics = validate_l2_document(bad, _package())
        assert document is None
        assert metrics["reason"] == REASON_UNKNOWN_FIELD

    def test_bad_schema_version_invalid(self):
        bad = _doc()
        bad["schema_version"] = 2
        document, metrics = validate_l2_document(bad, _package())
        assert document is None
        assert metrics["reason"] == REASON_BAD_SCHEMA_VERSION

    def test_extra_paragraph_field_invalid(self):
        bad = _doc(paragraphs=[{"text": "ок", "emphasis": None, "x": 1}])
        document, metrics = validate_l2_document(bad, _package())
        assert document is None
        assert metrics["reason"] == REASON_UNKNOWN_FIELD

    def test_empty_title_invalid(self):
        document, _ = validate_l2_document(_doc(title="  "), _package())
        assert document is None

    def test_long_title_invalid(self):
        document, _ = validate_l2_document(_doc(title="я" * 201), _package())
        assert document is None

    def test_emphasis_not_substring_dropped(self):
        doc = _doc(paragraphs=[{"text": "Текст абзаца.", "emphasis": "нет тут"}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert document["paragraphs"][0]["emphasis"] is None
        assert metrics["emphasis_dropped_count"] == 1

    def test_emphasis_substring_kept(self):
        doc = _doc(paragraphs=[{"text": "На улице дождь.", "emphasis": "дождь"}])
        document, _ = validate_l2_document(doc, _package())
        assert document["paragraphs"][0]["emphasis"] == "дождь"

    def test_parse_empty_response(self):
        data, reason = parse_l2_document("")
        assert data is None and reason == REASON_EMPTY_RESPONSE

    def test_parse_invalid_json(self):
        data, reason = parse_l2_document("не json")
        assert data is None and reason == REASON_INVALID_JSON

    def test_parse_fenced_json(self):
        raw = "```json\n" + json.dumps(_doc(), ensure_ascii=False) + "\n```"
        data, reason = parse_l2_document(raw)
        assert reason == "ok" and data["title"] == "Дождливый день"


# ── SC-07: выдуманные цитаты / приписанные реплики ─────────────────────────

class TestQuotes:
    def test_invented_quote_stripped(self):
        doc = _doc(paragraphs=[
            {"text": "Кто-то якобы сказал «выдуманная фраза которой нет».",
             "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert "«" not in document["paragraphs"][0]["text"]
        assert metrics["quote_unverified_count"] == 1

    def test_grounded_quote_kept(self):
        doc = _doc(paragraphs=[
            {"text": "В чате прозвучало «на улице шёл сильный дождь».",
             "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert "«" in document["paragraphs"][0]["text"]
        assert metrics["quote_unverified_count"] == 0

    def test_named_attribution_fail_closed(self):
        doc = _doc(paragraphs=[
            {"text": "Вася: «на улице шёл сильный дождь»", "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is None
        assert metrics["reason"] == REASON_QUOTE_ATTRIBUTION

    def test_single_quoted_invented_quote_stripped(self):
        # S-R1026S5-2: одиночные кавычки тоже пост-валидируются (defense-in-depth).
        doc = _doc(paragraphs=[
            {"text": "Он 'придумал такое' на ходу.", "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert "'" not in document["paragraphs"][0]["text"]
        assert metrics["quote_unverified_count"] == 1

    def test_corner_quoted_invented_quote_stripped(self):
        doc = _doc(paragraphs=[
            {"text": "Кто-то сказал 「выдумка」 вслух.", "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert "「" not in document["paragraphs"][0]["text"]
        assert metrics["quote_unverified_count"] == 1

    def test_attribution_verb_fail_closed(self):
        doc = _doc(paragraphs=[
            {"text": "«на улице шёл сильный дождь», — сказал Вася",
             "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is None
        assert metrics["reason"] == REASON_QUOTE_ATTRIBUTION

    def test_raw_ids_stripped(self):
        doc = _doc(paragraphs=[
            {"text": "Факт подтверждён (fact:123, msg:456).", "emphasis": None}])
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert "fact:" not in document["paragraphs"][0]["text"]
        assert "msg:" not in document["paragraphs"][0]["text"]
        assert metrics["ids_stripped_count"] >= 2


# ── SC-08: изоляция входа §96 ──────────────────────────────────────────────

class TestBuildInput:
    def test_service_and_budget_excluded(self):
        content = build_l2_input(_package(), detail="serious")
        assert "service" not in content
        assert "rain" not in content          # cover_prompt не утёк
        assert "budget" not in content
        assert "unassigned_message_ids" not in content

    def test_content_included(self):
        content = build_l2_input(_package(), detail="deep_research")
        assert "Погода и планы" in content
        assert "На улице шёл сильный дождь" in content
        assert '"detail":"deep_research"' in content

    def test_deterministic(self):
        a = build_l2_input(_package(), detail="serious")
        b = build_l2_input(_package(), detail="serious")
        assert a == b


# ── SC-09: fail-closed §106 ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRunL2:
    async def test_one_call_ok(self):
        llm = ScriptedLLM(json.dumps(_doc(), ensure_ascii=False))
        result = await run_l2(llm, _package(),
                              service={"response_mode": "serious"},
                              correlation_id="run-1", slot=_SlotStub())
        assert result.status == STATUS_OK
        assert result.usable
        assert llm.calls == 1

    async def test_package_none_skips_llm(self):
        llm = ScriptedLLM(json.dumps(_doc(), ensure_ascii=False))
        result = await run_l2(llm, None, slot=_SlotStub())
        assert result.status == "empty"
        assert result.invalid_reason == "no_package"
        assert llm.calls == 0

    async def test_package_not_deliverable_skips_llm(self):
        llm = ScriptedLLM(json.dumps(_doc(), ensure_ascii=False))
        result = await run_l2(llm, _package(status="invalid"), slot=_SlotStub())
        assert result.invalid_reason == REASON_PACKAGE_NOT_DELIVERABLE
        assert llm.calls == 0

    async def test_invalid_document_no_publication(self):
        llm = ScriptedLLM("мусор")
        result = await run_l2(llm, _package(), slot=_SlotStub())
        assert result.status == STATUS_INVALID
        assert result.document is None
        assert llm.calls == 1

    async def test_too_many_paragraphs(self):
        paragraphs = [{"text": f"Абзац {i}.", "emphasis": None}
                      for i in range(5)]
        llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                     ensure_ascii=False))
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              max_paragraphs=3)
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_TOO_MANY_PARAGRAPHS

    async def test_no_legacy_fallback_on_llm_error(self):
        class BoomLLM:
            calls = 0

            async def generate(self, messages, **kwargs):
                BoomLLM.calls += 1
                from services.llm_client import LLMError
                raise LLMError("boom")

        result = await run_l2(BoomLLM(), _package(), slot=_SlotStub())
        assert result.status == STATUS_ERROR
        assert result.document is None
        assert BoomLLM.calls == 1


# ── SC-10: слот §82 ────────────────────────────────────────────────────────

class TestSlot:
    def test_inherit_global_when_unset(self):
        slot = resolve_l2_slot(hot_get=lambda k, d: d, settings_obj=settings)
        assert slot.dedicated is False

    def test_dedicated_when_hot_env_set(self):
        slot = resolve_l2_slot(
            hot_get=lambda k, d: "my-l2" if k == "models.summary_l2_model_name"
            else d,
            settings_obj=settings)
        assert slot.dedicated is True
        assert slot.model == "my-l2"

    def test_global_model_used_when_slot_unset(self):
        slot = resolve_l2_slot(
            hot_get=lambda k, d: "global-model" if k == "models.llm_model_name"
            else d, settings_obj=settings)
        assert slot.dedicated is False
        assert slot.model == "global-model"

    def test_safe_wrapper_raises_slot_error(self):
        def boom(*a, **k):
            raise RuntimeError("nope")

        with pytest.raises(L2SlotError):
            resolve_l2_slot_safe(hot_get=boom, settings_obj=settings)

    def test_secret_not_in_slot_error(self):
        with pytest.raises(L2SlotError) as info:
            resolve_l2_slot_safe(hot_get=lambda k, d: (_ for _ in ()).throw(
                RuntimeError("secret-key-xyz")), settings_obj=settings)
        assert "secret-key-xyz" not in str(info.value)


# ── SC-11: канон ADR-1013-3 + F8 Δ каталога ────────────────────────────────

class TestCanon:
    def test_prev_is_base(self):
        assert PREV_SUMMARY_L2_WRITER_R1026 != SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert SUMMARY_L2_WRITER_SYSTEM_PROMPT == (
            PREV_SUMMARY_L2_WRITER_R1026 + "\n\n" + TARGET_INSTRUCTION_BLOCK)

    def test_separate_from_l1_and_narrator(self):
        from services.summary_prompts import (
            SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
            SUMMARY_NARRATOR_SYSTEM_PROMPT,
        )
        assert SUMMARY_L2_WRITER_SYSTEM_PROMPT not in (
            SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
            SUMMARY_NARRATOR_SYSTEM_PROMPT)

    def test_resolve_prompt_default(self):
        assert resolve_prompt(PROMPT_PG_KEY, SUMMARY_L2_WRITER_SYSTEM_PROMPT) \
            == SUMMARY_L2_WRITER_SYSTEM_PROMPT

    def test_canon_doc_byte_identical(self):
        # S-R1026S5-3: эталон `plans/docs/canon/architecture.md` == код промпта
        # (как у L1 `test_canon_doc_byte_identical`).
        text = CANON_PATH.read_text(encoding="utf-8")
        anchor = "SUMMARY_L2_WRITER_SYSTEM_PROMPT = " + '"""'
        start = text.index(anchor) + len(anchor)
        end = text.index('"""', start)
        assert text[start:end] == SUMMARY_L2_WRITER_SYSTEM_PROMPT

    def test_catalog_entry(self):
        spec = pc.get_by_pg_key(PROMPT_PG_KEY)
        assert spec is not None
        assert spec.category == pc.CATEGORY_PROMPTS
        assert spec.group == "prompts_summary"
        assert spec.progressive_level == "advanced"
        assert spec.stage == "synthesizer"
        assert spec.settings_field is None and spec.env_name is None
        assert spec.code_source == \
            "services.summary_prompts.SUMMARY_L2_WRITER_SYSTEM_PROMPT"

    def test_migration_and_rollback(self):
        assert (PREV_SUMMARY_L2_WRITER_R1026,
                SUMMARY_L2_WRITER_SYSTEM_PROMPT) in \
            pm.PROMPT_MIGRATIONS[PROMPT_PG_KEY]
        assert pm.ROLLBACK_MIGRATIONS[PROMPT_PG_KEY] == (
            SUMMARY_L2_WRITER_SYSTEM_PROMPT, PREV_SUMMARY_L2_WRITER_R1026)

    def test_catalog_delta_sanctioned(self):
        assert len(pc.REGISTRY) == 473
        assert len({f.name for f in dataclasses.fields(settings.__class__)}) \
            == 430
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 448
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21


# ── SC-13: R17-логи ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestLogs:
    async def test_no_raw_content_in_logs(self, caplog):
        secret = "СЕКРЕТНЫЙ_ОТВЕТ_МОДЕЛИ_L2"
        llm = ScriptedLLM(json.dumps(_doc(), ensure_ascii=False))
        with caplog.at_level("INFO"):
            await run_l2(llm, _package(), correlation_id="run-9",
                         slot=_SlotStub())
        assert "L2_START" in caplog.text
        assert "L2_COMPLETE" in caplog.text
        assert "secret-key-xyz" not in caplog.text
        assert secret not in caplog.text

    async def test_skipped_log_on_bad_package(self, caplog):
        llm = ScriptedLLM("{}")
        with caplog.at_level("INFO"):
            await run_l2(llm, _package(status="empty"), slot=_SlotStub())
        assert "L2_SKIPPED" in caplog.text
