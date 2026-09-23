"""S3 round1026 (ADR-1026-5) — L1 «Кластеризатор»: контракт §95, ядро, слот §82,
логи §108/§109, канон ADR-1013-3 и инварианты живого пути.

Покрытие (spec §6, T-3270…T-3272):
  * SC-04/SC-05/SC-07 — структура §95, ID-матрица (TG ``message_id`` vs DB
    ``id``), fail-closed ``L1Result{ok|empty|invalid|truncated|error}``;
  * SC-02/SC-03/SC-06/SC-08/SC-11 — темы/хронология/покрытие/усечение/
    детерминизм; лишние поля → ``invalid``; лимиты;
  * SC-10 — «L1 не пишет саммари» (структурные капы);
  * SC-12 — канон: ``PREV_*`` байт-в-байт, эталон ``plans/docs/canon``,
    ``PROMPT_MIGRATIONS``/``ROLLBACK_MIGRATIONS`` (идемпотентность);
  * SC-13 — слот §82 (env-only, hot-first, «не выбрано» → глобальная модель);
  * SC-14/SC-16 — живой путь: ровно 2 LLM-вызова, ``step="l1_clusterizer"``
    в живом пути отсутствует, OFF-цепочка байт-в-байт;
  * SC-17 — логи ``L1_START``/``L1_COMPLETE``/``L1_ERROR``, R17-safe.
"""
import dataclasses
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import param_catalog as pc
from services import prompt_migrations as pm
from services.llm_client import LLMError, LLMTimeoutError
from services.prompt_style_blocks import resolve_prompt
from services.summary_l1_clusterizer import (
    CHUNK_MARKER_TEMPLATE,
    IdSpaceMismatch,
    L1Slot,
    PROMPT_PG_KEY,
    build_db_tg_map,
    build_l1_user_content,
    pack_l1_input,
    provider_host,
    resolve_l1_budget,
    resolve_l1_slot,
    run_l1,
)
from services.summary_l1_contract import (
    L1Result,
    MAX_FACTS_PER_THREAD,
    MAX_THREADS,
    REASON_BAD_SCHEMA_VERSION,
    REASON_BAD_TYPE,
    REASON_EMPTY_RESPONSE,
    REASON_EVIDENCE_NOT_IN_THREAD,
    REASON_ID_SPACE_MISMATCH,
    REASON_INVALID_FACT,
    REASON_INVALID_JSON,
    REASON_INVALID_THREAD_ID,
    REASON_INVALID_TOPIC,
    REASON_LLM_ERROR,
    REASON_LLM_TIMEOUT,
    REASON_MESSAGE_IN_MULTIPLE_THREADS,
    REASON_TOO_MANY_FACTS,
    REASON_TOO_MANY_FACTS_TOTAL,
    REASON_TOO_MANY_THREADS,
    REASON_UNASSIGNED_CONFLICT,
    REASON_UNKNOWN_FIELD,
    REASON_UNKNOWN_MESSAGE_ID,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_TRUNCATED,
    build_id_space,
    empty_result,
    parse_l1_response,
    validate_l1_response,
)
from services.summary_prompts import (
    PREV_SUMMARY_L1_CLUSTERIZER_R1026,
    PREV_SUMMARY_NARRATOR_R1023,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.target_marking import TARGET_INSTRUCTION_BLOCK, TARGET_MARKER_CORE

pytestmark = pytest.mark.system2

ROOT = Path(__file__).resolve().parent.parent
CANON_PATH = ROOT / "plans" / "docs" / "canon" / "architecture.md"


# ── Хелперы ────────────────────────────────────────────────────────────────

def _row(db_id, tg_id, ts, text="текст", user_id=7, author="Вася",
         reply_to=None, media="text"):
    return {"id": db_id, "tg_message_id": tg_id, "timestamp": ts,
            "user_id": user_id, "author_name": author, "text": text,
            "reply_to_id": reply_to, "media_type": media}


def _rows3():
    return [
        _row(1, 101, 100, "привет", 7, "Вася"),
        _row(2, 102, 110, "как дела", 8, "Петя", reply_to=101),
        _row(3, 103, 120, "норм", 7, "Вася"),
    ]


def _space(*ids):
    return build_id_space([{"message_id": i, "timestamp": i} for i in ids])


def _obj(threads=None, unassigned=None, **extra):
    data = {"schema_version": 1, "threads": threads if threads is not None else [],
            "unassigned_message_ids": unassigned if unassigned is not None else []}
    data.update(extra)
    return data


def _thread(topic="тема", ids=(101,), facts=None, thread_id="thread_001"):
    return {"thread_id": thread_id, "topic": topic, "message_ids": list(ids),
            "facts": facts if facts is not None else []}


def _fact(text="факт", evidence=(101,)):
    return {"text": text, "evidence_message_ids": list(evidence)}


def _valid_json(threads=None, unassigned=None, **extra):
    return json.dumps(_obj(threads, unassigned, **extra), ensure_ascii=False)


class ScriptedLLM:
    """``llm.generate``-совместимый мок (путь без dedicated-слота)."""

    def __init__(self, response="", error=None):
        self.response = response
        self.error = error
        self.calls = []
        self._chat_model = "global-model"
        self._base_url = "https://global.example/v1"

    async def generate(self, messages, *, module=None, step=None,
                       correlation_id=None):
        self.calls.append({"messages": messages, "module": module,
                           "step": step, "correlation_id": correlation_id})
        if self.error is not None:
            raise self.error
        return self.response


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _ok_response(raw):
    return FakeResponse({"choices": [{"message": {"content": raw}}],
                         "usage": {"prompt_tokens": 11, "completion_tokens": 22}})


class DedicatedLLM:
    """Мок dedicated-пути: ``_post``/``_fallback_with_retries`` (S3-мост)."""

    def __init__(self, raw=None, error=None, fallback_raw=None):
        self.raw = raw
        self.error = error
        self.fallback_raw = fallback_raw
        self.post_calls = []
        self.fallback_calls = []
        self._fallback_active = fallback_raw is not None
        self._chat_model = "global-model"
        self._base_url = "https://global.example/v1"

    async def _post(self, path, payload, api_key=None, base_url=None, **kwargs):
        self.post_calls.append({"path": path, "payload": payload,
                                "api_key": api_key, "base_url": base_url})
        if self.error is not None:
            raise self.error
        return _ok_response(self.raw)

    async def _fallback_with_retries(self, payload):
        self.fallback_calls.append(payload)
        if self.fallback_raw is None:
            return None
        return _ok_response(self.fallback_raw)


@pytest.fixture(autouse=True)
def _clean_l1_env(monkeypatch):
    """Изоляция слота §82: env-класс-поля пусты (тесты включают их точечно)."""
    for field in ("SUMMARY_L1_BASE_URL", "SUMMARY_L1_MODEL_NAME",
                  "SUMMARY_L1_API_KEY"):
        monkeypatch.setattr(Settings, field, "")
    yield


# ── SC-04/SC-05: структура §95 и ID-матрица ────────────────────────────────

class TestContractSchema:
    def test_valid_example_ok(self):
        data = _obj(threads=[_thread("обсуждение", (101, 102),
                                     [_fact("Вася поздоровался", (101,))])],
                    unassigned=[103])
        result = validate_l1_response(data, _space(101, 102, 103))
        assert result.status == STATUS_OK and result.usable
        assert result.payload["threads"][0]["thread_id"] == "thread_001"
        assert result.threads_count == 1 and result.facts_count == 1
        assert result.auto_unassigned_count == 0
        assert result.payload["unassigned_message_ids"] == [103]

    @pytest.mark.parametrize("version", [0, 2, "1", 1.0, True, None])
    def test_bad_schema_version(self, version):
        result = validate_l1_response(_obj(schema_version=version), _space(101))
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_BAD_SCHEMA_VERSION
        assert result.payload is None and not result.usable

    def test_missing_schema_version(self):
        data = {"threads": [], "unassigned_message_ids": []}
        result = validate_l1_response(data, _space(101))
        assert result.invalid_reason == REASON_BAD_SCHEMA_VERSION

    @pytest.mark.parametrize("extra", [{"digest": "текст"}, {"schema": 1}])
    def test_unknown_top_level_field(self, extra):
        result = validate_l1_response(_obj(**extra), _space(101))
        assert result.invalid_reason == REASON_UNKNOWN_FIELD

    def test_unknown_thread_and_fact_fields(self):
        thread = _thread(ids=(101,))
        thread["summary"] = "проза"
        assert validate_l1_response(
            _obj(threads=[thread]), _space(101)
        ).invalid_reason == REASON_UNKNOWN_FIELD
        fact = _fact()
        fact["confidence"] = 0.9
        assert validate_l1_response(
            _obj(threads=[_thread(facts=[fact])]), _space(101)
        ).invalid_reason == REASON_UNKNOWN_FIELD

    @pytest.mark.parametrize("data", [
        _obj(threads={}),
        _obj(unassigned={}),
        _obj(threads=[123]),
        _obj(threads=[_thread(ids="101")]),
        _obj(threads=[_thread(facts="нет")]),
        _obj(threads=[_thread(facts=[123])]),
        _obj(threads=[_thread(ids=(101.5,))]),
        _obj(threads=[_thread(ids=(True,))]),
        _obj(threads=[_thread(facts=[_fact(evidence="101")])]),
    ])
    def test_bad_types(self, data):
        assert validate_l1_response(
            data, _space(101)).invalid_reason == REASON_BAD_TYPE

    def test_not_a_dict(self):
        assert validate_l1_response("строка", _space(101)).invalid_reason \
            == REASON_BAD_TYPE

    @pytest.mark.parametrize("thread_id", ["", "a b", "т#1", "x" * 65, 7, None])
    def test_invalid_thread_id(self, thread_id):
        result = validate_l1_response(
            _obj(threads=[_thread(thread_id=thread_id)]), _space(101))
        assert result.invalid_reason == REASON_INVALID_THREAD_ID

    def test_invalid_topic(self):
        long_topic = "я" * 201
        for topic in ("", "   ", "две\nстроки", long_topic, None):
            result = validate_l1_response(
                _obj(threads=[_thread(topic=topic)]), _space(101))
            assert result.invalid_reason == REASON_INVALID_TOPIC, topic

    def test_invalid_fact_text(self):
        bad = ["", "   ", "a" * 501, "два\n\nабзаца", "тег fact:12 внутри",
               "msg:7 внутри", "# заголовок", None, 1]
        for text in bad:
            result = validate_l1_response(
                _obj(threads=[_thread(facts=[_fact(text=text)])]), _space(101))
            assert result.invalid_reason == REASON_INVALID_FACT, text

    def test_limits(self):
        many_threads = [_thread(ids=(101,), thread_id=f"t{i}")
                        for i in range(MAX_THREADS + 1)]
        assert validate_l1_response(
            _obj(threads=many_threads), _space(101)
        ).invalid_reason == REASON_TOO_MANY_THREADS

        facts = [_fact(f"факт {i}") for i in range(MAX_FACTS_PER_THREAD + 1)]
        assert validate_l1_response(
            _obj(threads=[_thread(facts=facts)]), _space(101)
        ).invalid_reason == REASON_TOO_MANY_FACTS

        ids = tuple(range(1001, 1001 + 100))
        space = build_id_space([{"message_id": i, "timestamp": i} for i in ids])
        threads = [_thread(ids=(i,), thread_id=f"t{i}",
                           facts=[_fact(f"факт {j}", (i,))
                                  for j in range(11)])
                   for i in ids]
        result = validate_l1_response(_obj(threads=threads), space)
        assert result.invalid_reason == REASON_TOO_MANY_FACTS_TOTAL

    def test_empty_threads_is_empty_not_invalid(self):
        result = validate_l1_response(_obj(), _space(101))
        assert result.status == STATUS_EMPTY
        assert result.payload is None and not result.usable
        assert result.invalid_reason is None


class TestIdMatrix:
    def test_unknown_message_id(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(999,))]), _space(101))
        assert result.invalid_reason == REASON_UNKNOWN_MESSAGE_ID

    def test_db_id_instead_of_tg_fails_closed(self):
        """DB ``id`` (1/2/3) вместо TG ``message_id`` (101/102/103) → invalid."""
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(1, 2))]), _space(101, 102, 103))
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_UNKNOWN_MESSAGE_ID
        assert result.payload is None

    def test_evidence_outside_thread(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,), facts=[_fact(evidence=(102,))])]),
            _space(101, 102))
        assert result.invalid_reason == REASON_EVIDENCE_NOT_IN_THREAD

    def test_message_in_multiple_threads(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,), thread_id="a"),
                          _thread(ids=(101,), thread_id="b")]),
            _space(101))
        assert result.invalid_reason == REASON_MESSAGE_IN_MULTIPLE_THREADS

    def test_unassigned_conflict(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,))], unassigned=[101]), _space(101))
        assert result.invalid_reason == REASON_UNASSIGNED_CONFLICT

    def test_unknown_unassigned_id(self):
        result = validate_l1_response(_obj(unassigned=[999]), _space(101))
        assert result.invalid_reason == REASON_UNKNOWN_MESSAGE_ID

    def test_duplicates_deduplicated(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(102, 101, 101),
                                  facts=[_fact(evidence=(101, 101))])],
                 unassigned=[103, 103]),
            _space(101, 102, 103))
        assert result.status == STATUS_OK
        thread = result.payload["threads"][0]
        assert thread["message_ids"] == [101, 102]
        assert thread["facts"][0]["evidence_message_ids"] == [101]

    def test_auto_unassigned_for_skipped_ids(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,))]), _space(101, 102, 103))
        assert result.status == STATUS_OK
        assert result.payload["unassigned_message_ids"] == [102, 103]
        assert result.auto_unassigned_count == 2

    def test_non_int_payload_ids_not_addressable(self):
        """Не-int ``message_id`` (§92) в пространство не попадают — не выдумываем."""
        space = build_id_space([{"message_id": None, "timestamp": 1},
                                {"message_id": 101, "timestamp": 2}])
        assert space.ids == frozenset({101})
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,))]), space)
        assert result.status == STATUS_OK

    def test_id_space_sort_key_deterministic(self):
        space = build_id_space([{"message_id": 103, "timestamp": 10},
                                {"message_id": 101, "timestamp": 30}])
        assert sorted(space.ids, key=space.sort_key) == [103, 101]


# ── SC-07/SC-15: fail-closed-результат и парсер ────────────────────────────

class TestFailClosedResult:
    def test_invalid_result_payload_none(self):
        result = validate_l1_response(
            {"schema_version": 9}, _space(101))
        assert isinstance(result, L1Result)
        assert result.payload is None and result.invalid_reason

    def test_empty_error_helpers(self):
        for result in (empty_result(), L1Result(
                status=STATUS_ERROR, payload=None, invalid_reason=REASON_LLM_ERROR,
                threads_count=0, facts_count=0, auto_unassigned_count=0,
                skipped_ids=(), skipped_tg_ids=(), response_mode="",
                cover_prompt="", duration_ms=0.0)):
            assert result.payload is None and not result.usable

    def test_as_metrics_additive(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(101,), facts=[_fact()])]), _space(101))
        metrics = result.as_metrics()
        assert metrics["threads_count"] == 1 and metrics["facts_count"] == 1
        assert metrics["status"] == STATUS_OK
        assert "invalid_reason" in metrics and "chunk_count" in metrics
        assert "skipped_count" in metrics and "auto_unassigned_count" in metrics

    @pytest.mark.parametrize("raw,reason", [
        ("", REASON_EMPTY_RESPONSE),
        ("   ", REASON_EMPTY_RESPONSE),
        ("не json вовсе", REASON_INVALID_JSON),
        ("[1, 2, 3]", REASON_INVALID_JSON),
        ('{"schema_version": 1', REASON_INVALID_JSON),
    ])
    def test_parser_failures(self, raw, reason):
        data, got = parse_l1_response(raw)
        assert data is None and got == reason

    def test_parser_fences_and_wrapper(self):
        raw = '```json\n{"schema_version": 1, "threads": [], ' \
              '"unassigned_message_ids": []}\n```'
        data, reason = parse_l1_response(raw)
        assert reason == "ok" and data["schema_version"] == 1

    def test_validate_never_raises_on_garbage(self):
        for data in (None, 1, [], {"threads": [None]}):
            result = validate_l1_response(data, _space(101))
            assert result.status in (STATUS_INVALID, STATUS_EMPTY)


# ── SC-03/SC-11: хронология, канонизация, детерминизм ──────────────────────

class TestCanonicalization:
    def test_thread_order_by_first_message_and_renumbering(self):
        data = _obj(threads=[
            _thread("поздняя", (103,), thread_id="zzz"),
            _thread("ранняя", (101, 102), thread_id="aaa"),
        ])
        result = validate_l1_response(data, _space(101, 102, 103))
        assert result.status == STATUS_OK
        threads = result.payload["threads"]
        assert [t["topic"] for t in threads] == ["ранняя", "поздняя"]
        assert [t["thread_id"] for t in threads] == ["thread_001", "thread_002"]

    def test_message_ids_asc_inside_thread(self):
        result = validate_l1_response(
            _obj(threads=[_thread(ids=(103, 101, 102))]),
            _space(101, 102, 103))
        assert result.payload["threads"][0]["message_ids"] == [101, 102, 103]

    def test_fact_dedup_merges_evidence(self):
        data = _obj(threads=[_thread(ids=(101, 102), facts=[
            _fact("Вася пришёл", (101,)),
            _fact("  вася   ПРИШЁЛ ", (102,)),
        ])])
        result = validate_l1_response(data, _space(101, 102))
        assert result.status == STATUS_OK
        facts = result.payload["threads"][0]["facts"]
        assert len(facts) == 1
        assert facts[0]["evidence_message_ids"] == [101, 102]

    def test_double_run_byte_identical(self):
        data = _obj(threads=[
            _thread("б", (103,), thread_id="b", facts=[_fact("ф2", (103,))]),
            _thread("а", (101, 102), thread_id="a", facts=[_fact("ф1", (101,))]),
        ], unassigned=[104])
        first = validate_l1_response(data, _space(101, 102, 103, 104))
        second = validate_l1_response(data, _space(101, 102, 103, 104))
        assert json.dumps(first.payload, ensure_ascii=False, sort_keys=True) == \
            json.dumps(second.payload, ensure_ascii=False, sort_keys=True)

    def test_service_fields_do_not_leak_into_core(self):
        result = validate_l1_response(
            _obj(threads=[_thread()], response_mode="SERIOUS",
                 cover_prompt="  a   cat  "), _space(101))
        assert result.response_mode == "serious"
        assert result.cover_prompt == "a cat"
        assert result.payload["response_mode"] == "serious"
        assert result.payload["cover_prompt"] == "a cat"

    def test_service_fields_invalid_graceful(self):
        result = validate_l1_response(
            _obj(threads=[_thread()], response_mode="unknown",
                 cover_prompt=42), _space(101))
        assert result.status == STATUS_OK
        assert result.response_mode == "" and result.cover_prompt == ""
        assert "response_mode" not in result.payload
        assert "cover_prompt" not in result.payload

    def test_cover_prompt_truncated_at_word_boundary(self):
        long_prompt = " ".join(["word"] * 100)
        result = validate_l1_response(
            _obj(threads=[_thread()], cover_prompt=long_prompt), _space(101))
        assert len(result.cover_prompt) <= 300
        assert not result.cover_prompt.endswith("wor")

    def test_skipped_and_truncated_metadata_passthrough(self):
        result = validate_l1_response(
            _obj(threads=[_thread()]), _space(101),
            skipped_ids=(1, 2), skipped_tg_ids=(99, 100), truncated=True,
            chunk_count=3, duration_ms=5.0)
        assert result.truncated is True and result.chunk_count == 3
        assert result.skipped_ids == (1, 2) and result.skipped_tg_ids == (99, 100)
        assert result.duration_ms == 5.0


# ── SC-10: «L1 не пишет саммари» ───────────────────────────────────────────

class TestL1DoesNotWriteSummary:
    def test_output_is_structure_only(self):
        result = validate_l1_response(
            _obj(threads=[_thread("тема", (101,), [_fact("атомарный факт")])]),
            _space(101))
        thread = result.payload["threads"][0]
        assert set(thread) == {"thread_id", "topic", "message_ids", "facts"}
        assert set(thread["facts"][0]) == {"text", "evidence_message_ids"}
        assert set(result.payload) == {"schema_version", "threads",
                                       "unassigned_message_ids"}
        # Никакой прозы: topic — одна строка, факты — атомарные без абзацев.
        assert "\n" not in thread["topic"]
        assert "\n\n" not in thread["facts"][0]["text"]

    def test_prose_fact_rejected(self):
        prose = "Сегодня в чате было много всего. " * 20  # 660 символов
        assert validate_l1_response(
            _obj(threads=[_thread(facts=[_fact(prose)])]), _space(101)
        ).invalid_reason == REASON_INVALID_FACT

    def test_canon_forbids_writing_summary(self):
        assert "НЕ ПИШЕШЬ САММАРИ" in SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        assert TARGET_MARKER_CORE in SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        for token in ('"schema_version": 1', "evidence_message_ids",
                      "unassigned_message_ids", "response_mode",
                      "cover_prompt", "threads"):
            assert token in SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT, token


# ── SC-08: §93-упаковка, чанки, бюджет, усечение ───────────────────────────

class TestPackAndBudget:
    def test_pack_fits_single_input(self):
        pack = pack_l1_input(_rows3(), -100, token_limit=100000)
        assert pack.chunk_count == 1 and pack.truncated is False
        assert pack.skipped_ids == () and pack.chunk_starts == ()
        assert [item["message_id"] for item in pack.payload] == [101, 102, 103]
        assert pack.source_count == 3

    def test_pack_order_is_asc_even_if_rows_shuffled(self):
        rows = list(reversed(_rows3()))
        pack = pack_l1_input(rows, -100, token_limit=100000)
        assert [item["message_id"] for item in pack.payload] == [101, 102, 103]

    def test_pack_splits_into_fragments_and_truncates(self):
        pack = pack_l1_input(_rows3(), -100, token_limit=1)
        assert pack.chunk_count >= 2
        assert pack.truncated is True
        assert pack.skipped_ids and pack.skipped_tg_ids
        # Последнее сообщение сохраняется всегда («не резать молча»).
        assert pack.payload[-1]["message_id"] == 103
        assert 103 not in pack.skipped_tg_ids

    def test_pack_chars_mode(self):
        pack = pack_l1_input(_rows3(), -100, char_limit=1)
        assert pack.kind == "chars" and pack.truncated is True
        assert pack.payload[-1]["message_id"] == 103

    def test_pack_reports_marker_overhead(self):
        plain = pack_l1_input(_rows3(), -100, token_limit=100000,
                              marker_overhead=False)
        assert plain.estimated_tokens > 0

    def test_user_content_markers_on_fragment_bounds(self):
        """Маркеры границ §93-фрагментов — метки ЕДИНОГО входа (не вызовы)."""
        items = [{"message_id": 101, "text": "раз"}, {"message_id": 102, "text": "два"}]
        content = build_l1_user_content(items, chunk_count=2,
                                        chunk_starts=(102,))
        marker = CHUNK_MARKER_TEMPLATE.format(index=2, total=2)
        assert marker in content
        assert content.index('"message_id":101') < content.index(marker) \
            < content.index('"message_id":102')

    def test_user_content_no_marker_without_starts(self):
        items = [{"message_id": 101, "text": "раз"}]
        content = build_l1_user_content(items, chunk_count=1)
        assert "ЧАСТЬ" not in content
        assert content.splitlines()[0].startswith("СООБЩЕНИЯ ЧАТА")

    def test_build_db_tg_map_ok_and_mismatch(self):
        assert build_db_tg_map(_rows3()) == {1: 101, 2: 102, 3: 103}
        with pytest.raises(IdSpaceMismatch):
            build_db_tg_map([_row(1, None, 100)])
        with pytest.raises(IdSpaceMismatch):
            build_db_tg_map([_row(1, 101, 100), _row(1, 102, 110)])

    def test_budget_resolver_tokens(self):
        hot = {"limits.summary_max_context_tokens": 5000}
        kind, limit = resolve_l1_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert (kind, limit) == ("tokens", 5000)

    def test_budget_resolver_chars_fallback(self, monkeypatch):
        monkeypatch.setenv("SUMMARY_MAX_CONTEXT_CHARS", "7000")
        hot = {"limits.summary_max_context_tokens": None,
               "limits.summary_max_context_chars": 7000}
        kind, limit = resolve_l1_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert (kind, limit) == ("chars", 7000)

    def test_budget_resolver_unlimited_sentinel(self):
        hot = {"limits.summary_max_context_tokens": -1}
        kind, limit = resolve_l1_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert kind == "tokens"
        assert limit == Settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS


# ── SC-13: слот §82 (env-only, hot-first, наследование) ────────────────────

class TestSlotResolution:
    def _st(self, **overrides):
        base = {"SUMMARY_L1_BASE_URL": "", "SUMMARY_L1_MODEL_NAME": "",
                "SUMMARY_L1_API_KEY": "", "LLM_BASE_URL": "https://global/v1",
                "LLM_MODEL_NAME": "global-model", "LLM_API_KEY": "global-key"}
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_not_selected_inherits_global(self):
        slot = resolve_l1_slot(hot_get=lambda k, d=None: d,
                               settings_obj=self._st())
        assert slot == L1Slot(base_url="https://global/v1",
                              model="global-model", api_key="global-key",
                              dedicated=False)

    def test_partial_pair_completed_from_global(self):
        slot = resolve_l1_slot(
            hot_get=lambda k, d=None: d,
            settings_obj=self._st(SUMMARY_L1_MODEL_NAME="l1-model"))
        assert slot.dedicated is True
        assert slot.model == "l1-model"
        assert slot.base_url == "https://global/v1"

    def test_hot_first_overrides_env_defaults(self):
        hot = {"models.summary_l1_model_name": "hot-model",
               "models.summary_l1_base_url": "https://hot/v1",
               "keys.summary_l1_api_key": "hot-key"}
        slot = resolve_l1_slot(hot_get=lambda k, d=None: hot.get(k, d),
                               settings_obj=self._st())
        assert slot == L1Slot(base_url="https://hot/v1", model="hot-model",
                              api_key="hot-key", dedicated=True)

    def test_secret_never_logged(self, caplog):
        slot = resolve_l1_slot(
            hot_get=lambda k, d=None: d,
            settings_obj=self._st(SUMMARY_L1_API_KEY="super-secret-key"))
        with caplog.at_level("DEBUG"):
            assert slot.api_key == "super-secret-key"
        assert "super-secret-key" not in caplog.text

    def test_provider_host_r17_safe(self):
        assert provider_host("https://api.example.com/v1?key=secret") == \
            "api.example.com"
        assert provider_host("") == ""

    def test_classvars_env_only_zero_catalog_delta(self):
        assert "SUMMARY_L1_BASE_URL" not in pc.REGISTRY
        assert "SUMMARY_L1_MODEL_NAME" not in pc.REGISTRY
        assert "SUMMARY_L1_API_KEY" not in pc.REGISTRY
        for field in ("SUMMARY_L1_BASE_URL", "SUMMARY_L1_MODEL_NAME",
                      "SUMMARY_L1_API_KEY"):
            assert field not in {f.name for f in dataclasses.fields(Settings)}


# ── SC-02/SC-14: ядро — ровно один вызов, fail-closed, логи ────────────────

class TestRunCore:
    @pytest.mark.asyncio
    async def test_exactly_one_llm_call(self):
        llm = ScriptedLLM(_valid_json([_thread(ids=(101, 102))]))
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="run-1")
        assert len(llm.calls) == 1
        call = llm.calls[0]
        assert call["module"] == "summary" and call["step"] == "l1_clusterizer"
        assert call["correlation_id"] == "run-1"
        assert call["messages"][0]["content"] == SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        assert result.status == STATUS_OK and result.usable
        assert result.threads_count == 1

    @pytest.mark.asyncio
    async def test_one_call_even_with_many_chunks(self):
        llm = ScriptedLLM(_valid_json([_thread(ids=(103,))]))
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              budget=("tokens", 1))
        assert len(llm.calls) == 1
        assert result.status == STATUS_TRUNCATED and result.usable
        assert result.skipped_ids

    @pytest.mark.asyncio
    async def test_llm_call_injection_contract(self):
        calls = []

        async def _call(messages):
            calls.append(messages)
            return _valid_json([_thread(ids=(101,))])

        result = await run_l1(llm=object(), rows=_rows3(), chat_id=-100,
                              llm_call=_call)
        assert len(calls) == 1
        assert result.status == STATUS_OK
        assert result.response_mode == ""

    @pytest.mark.asyncio
    async def test_empty_input_no_llm_call(self):
        llm = ScriptedLLM(_valid_json([_thread(ids=(101,))]))
        result = await run_l1(llm=llm, rows=[], chat_id=-100)
        assert llm.calls == []
        assert result.status == STATUS_EMPTY
        assert result.payload is None and not result.usable

    @pytest.mark.asyncio
    async def test_invalid_json_fail_closed(self):
        llm = ScriptedLLM("мусор без JSON")
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_INVALID_JSON
        assert result.payload is None and not result.usable

    @pytest.mark.asyncio
    async def test_db_id_mismatch_fail_closed(self):
        rows = [_row(1, None, 100, "привет")]
        result = await run_l1(llm=ScriptedLLM("{}"), rows=rows, chat_id=-100,
                              budget=("tokens", 1))
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_ID_SPACE_MISMATCH
        assert result.payload is None

    @pytest.mark.asyncio
    async def test_llm_error_and_timeout(self):
        for error, reason in ((LLMError("boom"), REASON_LLM_ERROR),
                              (LLMTimeoutError("timeout"), REASON_LLM_TIMEOUT)):
            llm = ScriptedLLM(error=error)
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
            assert result.status == STATUS_ERROR
            assert result.invalid_reason == reason
            assert result.payload is None and not result.usable

    @pytest.mark.asyncio
    async def test_no_llm_object_returns_error(self):
        result = await run_l1(rows=_rows3(), chat_id=-100)
        assert result.status == STATUS_ERROR
        assert result.payload is None

    @pytest.mark.asyncio
    async def test_dedicated_slot_uses_slot_pair(self):
        import services.summary_l1_clusterizer as module
        llm = DedicatedLLM(_valid_json([_thread(ids=(101,))]))
        slot = L1Slot(base_url="https://dedicated/v1", model="l1-model",
                      api_key="l1-key", dedicated=True)
        original = module.resolve_l1_slot
        module.resolve_l1_slot = lambda **kwargs: slot
        try:
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        finally:
            module.resolve_l1_slot = original
        assert result.status == STATUS_OK
        assert len(llm.post_calls) == 1
        assert llm.post_calls[0]["base_url"] == "https://dedicated/v1"
        assert llm.post_calls[0]["api_key"] == "l1-key"
        assert llm.post_calls[0]["payload"]["model"] == "l1-model"

    @pytest.mark.asyncio
    async def test_dedicated_error_uses_existing_fallback(self):
        import services.summary_l1_clusterizer as module
        llm = DedicatedLLM(error=LLMError("primary down"),
                           fallback_raw=_valid_json([_thread(ids=(101,))]))
        slot = L1Slot(base_url="https://dedicated/v1", model="l1-model",
                      api_key="l1-key", dedicated=True)
        original = module.resolve_l1_slot
        module.resolve_l1_slot = lambda **kwargs: slot
        try:
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        finally:
            module.resolve_l1_slot = original
        assert result.status == STATUS_OK
        assert len(llm.fallback_calls) == 1

    @pytest.mark.asyncio
    async def test_dedicated_failure_is_error_not_global_fallback(self):
        import services.summary_l1_clusterizer as module
        llm = DedicatedLLM(error=LLMError("primary down"))
        slot = L1Slot(base_url="https://dedicated/v1", model="l1-model",
                      api_key="l1-key", dedicated=True)
        original = module.resolve_l1_slot
        module.resolve_l1_slot = lambda **kwargs: slot
        try:
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        finally:
            module.resolve_l1_slot = original
        assert result.status == STATUS_ERROR
        assert result.invalid_reason == REASON_LLM_ERROR

    @pytest.mark.asyncio
    async def test_payload_fields_only_real(self):
        llm = ScriptedLLM(_valid_json([_thread(ids=(101,))]))
        await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        content = llm.calls[0]["messages"][1]["content"]
        assert "101" in content and "Вася" in content
        assert "mentions" not in content  # поля нет в окне — не выдумываем
        assert '"chat_id":-100' in content.replace(" ", "")

    @pytest.mark.asyncio
    async def test_double_run_same_input_identical(self):
        rows = _rows3()
        payload = _valid_json([_thread(ids=(103, 101, 102))])
        first = await run_l1(llm=ScriptedLLM(payload), rows=rows, chat_id=-100)
        second = await run_l1(llm=ScriptedLLM(payload), rows=rows, chat_id=-100)
        assert json.dumps(first.payload, ensure_ascii=False, sort_keys=True) == \
            json.dumps(second.payload, ensure_ascii=False, sort_keys=True)


class TestLogs:
    @pytest.mark.asyncio
    async def test_start_complete_fields(self, caplog):
        llm = ScriptedLLM(_valid_json(
            [_thread(ids=(101, 102), facts=[_fact("факт", (101,))])]))
        with caplog.at_level("INFO"):
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                                  correlation_id="run-42")
        assert "L1_START" in caplog.text and "L1_COMPLETE" in caplog.text
        assert "run_id=run-42" in caplog.text
        assert "tokens_in=" in caplog.text and "tokens_out=" in caplog.text
        assert "threads=1" in caplog.text and "facts=1" in caplog.text
        assert "duration_ms=" in caplog.text
        assert result.status == STATUS_OK

    @pytest.mark.asyncio
    async def test_error_log_r17_safe(self, caplog):
        secret = "СЕКРЕТНЫЙ_ТЕКСТ_СООБЩЕНИЯ_777"
        rows = [_row(1, 101, 100, secret)]
        llm = ScriptedLLM(error=LLMError("boom"))
        with caplog.at_level("INFO"):
            await run_l1(llm=llm, rows=rows, chat_id=-100)
        assert "L1_ERROR" in caplog.text
        assert "error=LLMError" in caplog.text
        assert secret not in caplog.text

    @pytest.mark.asyncio
    async def test_complete_log_no_raw_content(self, caplog):
        secret = "СЕКРЕТНЫЙ_ОТВЕТ_МОДЕЛИ_888"
        llm = ScriptedLLM(_valid_json([_thread("тема", (101,), [_fact(secret)])]))
        with caplog.at_level("INFO"):
            await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        assert "L1_COMPLETE" in caplog.text
        assert secret not in caplog.text

    @pytest.mark.asyncio
    async def test_truncation_logged_not_silent(self, caplog):
        llm = ScriptedLLM(_valid_json([_thread(ids=(103,))]))
        with caplog.at_level("INFO"):
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                                  budget=("tokens", 1))
        assert result.status == STATUS_TRUNCATED
        assert "truncated=True" in caplog.text
        assert "skipped=2" in caplog.text
        # §4.2: усечение — WARN, не только INFO-строка L1_COMPLETE.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("L1 truncated input" in r.message for r in warnings)

    @pytest.mark.asyncio
    async def test_invalid_reason_logged(self, caplog):
        llm = ScriptedLLM("не json")
        with caplog.at_level("INFO"):
            await run_l1(llm=llm, rows=_rows3(), chat_id=-100)
        assert "L1 invalid response" in caplog.text
        assert "reason=invalid_json" in caplog.text


# ── SC-12: канон L1 (ADR-1013-3) и миграции ────────────────────────────────

class TestCanon:
    def test_prev_snapshot_is_canon_base(self):
        """PREV — слепок базы канона S3 (без общего блока маркировки, ADR-1023-1)."""
        assert PREV_SUMMARY_L1_CLUSTERIZER_R1026 != \
            SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        assert SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT == (
            PREV_SUMMARY_L1_CLUSTERIZER_R1026 + "\n\n" + TARGET_INSTRUCTION_BLOCK)

    def test_separate_from_l2_canons(self):
        assert SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT not in (
            SUMMARY_EDITOR_SYSTEM_PROMPT, SUMMARY_NARRATOR_SYSTEM_PROMPT,
            SYSTEM_PROMPT, PREV_SUMMARY_NARRATOR_R1023)

    def test_canon_doc_byte_identical(self):
        text = CANON_PATH.read_text(encoding="utf-8")
        anchor = "SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT = " + '"""'
        start = text.index(anchor) + len(anchor)
        end = text.index('"""', start)
        assert text[start:end] == SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT

    def test_resolve_prompt_returns_canon_without_cache(self):
        assert resolve_prompt(PROMPT_PG_KEY, SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT) \
            == SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT

    def test_catalog_entry(self):
        spec = pc.get_by_pg_key(PROMPT_PG_KEY)
        assert spec is not None
        assert spec.category == pc.CATEGORY_PROMPTS
        assert spec.group == "prompts_summary"
        assert spec.settings_field is None and spec.env_name is None
        assert spec.type == "str" and spec.secret is False
        assert spec.progressive_level == "advanced"
        assert spec.stage == "synthesizer"
        assert spec.per_chat is True
        assert spec.code_source == \
            "services.summary_prompts.SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT"
        assert pc.group_tab(spec.group) == pc.TAB_PROMPTS
        assert pc.tab_nav(pc.TAB_PROMPTS) == pc.NAV_AI

    def test_catalog_delta_sanctioned(self):
        assert len(pc.REGISTRY) == 469
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 444
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_migration_step_present(self):
        steps = pm.PROMPT_MIGRATIONS[PROMPT_PG_KEY]
        assert (PREV_SUMMARY_L1_CLUSTERIZER_R1026,
                SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT) in steps

    def test_rollback_documented(self):
        assert pm.ROLLBACK_MIGRATIONS[PROMPT_PG_KEY] == (
            SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
            PREV_SUMMARY_L1_CLUSTERIZER_R1026)


class _FakeCache:
    def __init__(self, values, pg_available=True):
        self.values = dict(values)
        self.pg_available = pg_available
        self.sets = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category=None):
        self.sets.append((key, value, category))
        self.values[key] = value


class TestCanonMigrations:
    @pytest.mark.asyncio
    async def test_prev_updates_to_canon(self):
        cache = _FakeCache({PROMPT_PG_KEY: PREV_SUMMARY_L1_CLUSTERIZER_R1026})
        report = await pm.migrate_prompt_canons(cache)
        assert report == {PROMPT_PG_KEY: "updated"}
        assert cache.values[PROMPT_PG_KEY] == SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        assert cache.sets == [(PROMPT_PG_KEY,
                               SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
                               "prompts")]

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self):
        cache = _FakeCache({PROMPT_PG_KEY: PREV_SUMMARY_L1_CLUSTERIZER_R1026})
        await pm.migrate_prompt_canons(cache)
        report = await pm.migrate_prompt_canons(cache)
        assert PROMPT_PG_KEY not in report
        assert len(cache.sets) == 1

    @pytest.mark.asyncio
    async def test_missing_key_skipped(self):
        cache = _FakeCache({})
        report = await pm.migrate_prompt_canons(cache)
        assert PROMPT_PG_KEY not in report and cache.sets == []

    @pytest.mark.asyncio
    async def test_custom_value_untouched(self, caplog):
        cache = _FakeCache({PROMPT_PG_KEY: "мой кастомный промпт"})
        with caplog.at_level("WARNING"):
            report = await pm.migrate_prompt_canons(cache)
        assert PROMPT_PG_KEY not in report and cache.sets == []
        assert "кастом юзера" in caplog.text

    @pytest.mark.asyncio
    async def test_pg_down_skipped(self):
        cache = _FakeCache({PROMPT_PG_KEY: PREV_SUMMARY_L1_CLUSTERIZER_R1026},
                           pg_available=False)
        report = await pm.migrate_prompt_canons(cache)
        assert report == {} and cache.sets == []

    @pytest.mark.asyncio
    async def test_rollback_returns_prev(self):
        cache = _FakeCache({PROMPT_PG_KEY: SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT})
        report = await pm.rollback_prompt_canons(cache)
        assert report == {PROMPT_PG_KEY: "rolled_back"}
        assert cache.values[PROMPT_PG_KEY] == PREV_SUMMARY_L1_CLUSTERIZER_R1026

    @pytest.mark.asyncio
    async def test_rollback_idempotent(self):
        cache = _FakeCache({PROMPT_PG_KEY: PREV_SUMMARY_L1_CLUSTERIZER_R1026})
        report = await pm.rollback_prompt_canons(cache)
        assert PROMPT_PG_KEY not in report and cache.sets == []


# ── SC-14/SC-16/SC-19: живой путь не тронут, ровно 2 вызова ────────────────

class TestLivePathInvariants:
    def test_generator_l1_wiring_is_flag_gated(self):
        # S5 (ADR-1026-7 D5), AMEND S10 (ADR-1026-12 D2): врезка L1 в живой путь
        # за флагом (`SUMMARY_HYBRID_L2_ENABLED`, default ON с S10; явный false —
        # аварийный kill-switch); OFF-путь `_generate_two_call` (Stage-1/Stage-2)
        # сохранён байт-в-байт.
        text = (ROOT / "services/summary_generator.py").read_text(encoding="utf-8")
        assert "summary_l1_clusterizer" in text
        assert "_generate_two_call" in text
        assert "_hybrid_l2_enabled" in text
        xml = (ROOT / "services/summary_xml.py").read_text(encoding="utf-8")
        assert "l1_clusterizer" not in xml
        assert "summary_l1_" not in xml

    @pytest.mark.asyncio
    async def test_two_calls_stage1_stage2(self):
        from services.summary_generator import SummaryGenerator
        digest = "# Событие\n- Вася спорил с Петей"
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[digest, "связный текст"])
        gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                               bot=None)
        draft = await gen._generate_two_call("сырая история", 3800, -100)
        assert llm.generate.await_count == 2
        steps = [c.kwargs.get("step") for c in llm.generate.await_args_list]
        assert steps == ["stage1", "stage2"]
        first_system = llm.generate.await_args_list[0].args[0][0]["content"]
        assert first_system == SUMMARY_EDITOR_SYSTEM_PROMPT
        assert draft.text == "связный текст"

    @pytest.mark.asyncio
    async def test_run_on_branch_two_calls(self, monkeypatch):
        from services.summary_generator import SummaryGenerator
        from services.summary_xml import XmlGroundingBuilder
        from tests.test_summary_generator import FakeMemory, _row

        digest = "# Событие\n- Вася спорил с Петей"

        class TwoCallLLM:
            def __init__(self):
                self.calls = []

            async def generate(self, messages, **kwargs):
                self.calls.append(kwargs)
                return digest if len(self.calls) == 1 else "дерзкий рассказ"

        delivered: list = []

        async def _capture(bot, chat_id, text, **kw):
            delivered.append(text)

        monkeypatch.setattr(SummaryGenerator, "_send_streaming", _capture)
        # S6 (D2): публикационный plain-путь — чанки `send_text`.
        monkeypatch.setattr("services.summary_generator.send_text", _capture)

        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), TwoCallLLM(), AsyncMock())
        # S10 (ADR-1026-12 D2): Hybrid default ON — legacy-путь проверяем при
        # ЯВНОМ аварийном OFF (kill-switch), а не по дефолту.
        monkeypatch.setattr(gen, "_hybrid_l2_enabled",
                            AsyncMock(return_value=False))
        await gen._run(-100, False)
        assert len(gen.llm.calls) == 2
        assert [c.get("step") for c in gen.llm.calls] == ["stage1", "stage2"]
        assert "l1_clusterizer" not in str(gen.llm.calls)
        assert delivered

    @pytest.mark.asyncio
    async def test_off_chain_byte_identical_single_call(self, monkeypatch):
        from services.summary_generator import SummaryGenerator
        from services.summary_xml import XmlGroundingBuilder
        from tests.test_summary_generator import FakeMemory, _row

        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)

        class OneCallLLM:
            def __init__(self):
                self.messages = None
                self.calls = 0

            async def generate(self, messages, **kwargs):
                self.calls += 1
                self.messages = messages
                return "одиночный текст"

        delivered: list = []

        async def _capture(bot, chat_id, text, **kw):
            delivered.append(text)

        monkeypatch.setattr(SummaryGenerator, "_send_streaming", _capture)
        monkeypatch.setattr("services.summary_generator.send_text", _capture)

        llm = OneCallLLM()
        gen = SummaryGenerator(FakeMemory(rows=[_row(author_name="вася")]),
                               XmlGroundingBuilder(), llm, AsyncMock())
        monkeypatch.setattr(gen, "_hybrid_l2_enabled",
                            AsyncMock(return_value=False))
        await gen._run(-100, False)
        assert llm.calls == 1
        # OFF-цепочка: прежний одиночный канон (с {max_symbols}) — L1 не протёк.
        assert llm.messages[0]["content"] == SYSTEM_PROMPT.replace(
            "{max_symbols}", "3800")
        assert SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT != SYSTEM_PROMPT
        assert delivered
