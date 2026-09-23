"""S4 round1026 (ADR-1026-6 D1–D6) — пакет фактов §96: схема, детерминизм,
fail-closed, ID-целостность, бюджет/усечение, транзит `service`, 0 LLM-вызовов
и инварианты живого пути.

Покрытие (spec §11, SC-01…SC-10; задачи T-3296…T-3298):
  * SC-01 — §96-полнота темы (name/description/chronology/facts/evidence_ids/
    fragments), адаптированный пример §95;
  * SC-02 — 0 LLM-вызовов модуля; `await_count==2` в живом пути;
  * SC-03 — fail-closed `ok/truncated/empty/invalid/error/not_built`;
  * SC-04 — ID-пространства TG ↔ DB, evidence ⊆ темы, висячие/фабрикованные →
    invalid;
  * SC-05 — компактность: сырой лог не дублируется, fragments ⊆ подтверждённым;
  * SC-06 — усечение явное (`truncated` + `skipped_ids`/`skipped_threads` +
    WARN), последние фрагменты сохраняются;
  * SC-07 — двойной прогон байт-идентичен, вход не мутируется;
  * SC-08 — `description`/`chronology` детерминированы, без генерации;
  * SC-09 — транзит `service{response_mode, cover_prompt}`;
  * SC-10 — Δ каталога = 0; живой путь/XML вне изменений.
"""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services.summary_fact_package import (
    DELIVERABLE_STATUSES,
    DESCRIPTION_MAX,
    DESCRIPTION_SEPARATOR,
    MAX_FRAGMENTS_PER_THREAD,
    REASON_BAD_INPUT,
    REASON_BUDGET_EMPTY,
    REASON_EMPTY,
    REASON_EVIDENCE_NOT_IN_THREAD,
    REASON_MESSAGE_IN_MULTIPLE_THREADS,
    REASON_MISSING_SOURCE,
    REASON_NO_RESULT,
    REASON_PAYLOAD_MISSING,
    REASON_UNASSIGNED_CONFLICT,
    REASON_UNKNOWN_STATUS,
    SCHEMA_VERSION,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_NOT_BUILT,
    STATUS_OK,
    STATUS_TRUNCATED,
    THREAD_FIELDS,
    TOP_LEVEL_FIELDS,
    build_fact_package,
    resolve_fact_package_budget,
    serialize_package,
)
from services.summary_l1_contract import (
    L1Result,
    STATUS_OK as L1_OK,
    STATUS_TRUNCATED as L1_TRUNCATED,
    build_id_space,
    empty_result,
    error_result,
    invalid_result,
    validate_l1_response,
)

pytestmark = pytest.mark.system2

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "services" / "summary_fact_package.py"


# ── Хелперы ────────────────────────────────────────────────────────────────

def _items(rows):
    """§92-payload: rows = [(tg_message_id, timestamp, text), ...]."""
    return [{"message_id": mid, "chat_id": -100, "timestamp": ts,
             "author_id": 7, "display_name": "Вася", "text": text,
             "reply_to_id": None, "message_type": "text"}
            for mid, ts, text in rows]


def _payload(threads, unassigned=(), response_mode=None, cover_prompt=None):
    data = {"schema_version": 1, "threads": threads,
            "unassigned_message_ids": list(unassigned)}
    if response_mode is not None:
        data["response_mode"] = response_mode
    if cover_prompt is not None:
        data["cover_prompt"] = cover_prompt
    return data


def _thread(topic, ids, facts=(), thread_id="t1"):
    return {"thread_id": thread_id, "topic": topic, "message_ids": list(ids),
            "facts": [{"text": text, "evidence_message_ids": list(ev)}
                      for text, ev in facts]}


def _ok_l1(data, items, **kwargs):
    return validate_l1_response(data, build_id_space(items), **kwargs)


def _raw_l1(payload, status=L1_OK, **kwargs):
    base = dict(invalid_reason=None, threads_count=1, facts_count=1,
                auto_unassigned_count=0, skipped_ids=(), skipped_tg_ids=(),
                response_mode="", cover_prompt="", duration_ms=0.0)
    base.update(kwargs)
    return L1Result(status=status, payload=payload, **base)


def _simple():
    """Одна тема из 3 сообщений + 1 unassigned (пример §95)."""
    items = _items([(101, 100, "привет"), (102, 110, "как дела"),
                    (103, 120, "норм"), (104, 130, "пока")])
    data = _payload(
        [_thread("приветствие", (101, 102, 103),
                 facts=[("Вася поздоровался", (101,)),
                        ("Вася спросил про дела", (102, 103))])],
        unassigned=[104], response_mode="serious", cover_prompt="кот")
    return _ok_l1(data, items), items


# ── SC-01: схема и §96-полнота ─────────────────────────────────────────────

class TestSchema:
    def test_top_level_keys_exact_order(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.status == STATUS_OK and result.deliverable
        assert list(result.package.keys()) == list(TOP_LEVEL_FIELDS)
        assert result.package["schema_version"] == SCHEMA_VERSION

    def test_thread_keys_exact_order(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        thread = result.package["threads"][0]
        assert list(thread.keys()) == list(THREAD_FIELDS)

    def test_name_is_topic_verbatim(self):
        items = _items([(101, 100, "привет")])
        data = _payload([_thread("  Имя темы  ", (101,))])
        l1 = _ok_l1(data, items)
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        # topic прошёл strip ещё в L1-контракте — verbatim из payload.
        assert result.package["threads"][0]["name"] == l1.payload["threads"][0]["topic"]

    def test_chronology_asc_pair(self):
        items = _items([(103, 120, "в"), (101, 100, "а"), (102, 110, "б")])
        data = _payload([_thread("тема", (103, 101, 102))])
        l1 = _ok_l1(data, items)
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        chronology = result.package["threads"][0]["chronology"]
        assert chronology == [{"message_id": 101, "timestamp": 100},
                              {"message_id": 102, "timestamp": 110},
                              {"message_id": 103, "timestamp": 120}]

    def test_facts_verbatim_and_evidence_union(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        thread = result.package["threads"][0]
        assert thread["facts"] == l1.payload["threads"][0]["facts"]
        assert thread["evidence_ids"] == [101, 102, 103]  # union ASC

    def test_unassigned_transit(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.package["unassigned_message_ids"] == [104]

    def test_service_section_transit_and_isolation(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.package["service"] == {"response_mode": "serious",
                                             "cover_prompt": "кот"}
        # service — вне L2-контента: в темах служебных полей нет.
        for thread in result.package["threads"]:
            assert "response_mode" not in thread and "cover_prompt" not in thread

    def test_budget_section_shape(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("chars", 100000))
        assert set(result.package["budget"]) == {"kind", "limit", "estimated",
                                                 "fits"}
        assert result.package["budget"]["kind"] == "chars"


# ── SC-08: description/chronology детерминированы, без LLM ────────────────

class TestDescription:
    def test_from_facts_dedup_whitespace(self):
        items = _items([(101, 100, "а"), (102, 110, "б")])
        data = _payload([_thread("тема", (101, 102), facts=[
            ("Вася пришёл", (101,)),
            ("  Вася   пришёл  ", (102,)),        # дубль после схлопывания
            ("Петя ушёл", (102,)),
        ])])
        l1 = _ok_l1(data, items)
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        # L1 сам схлопывает дубли и объединяет evidence — проверяем агрегацию.
        description = result.package["threads"][0]["description"]
        parts = description.split(DESCRIPTION_SEPARATOR)
        assert len(parts) == len(set(p.casefold() for p in parts))
        assert "\n" not in description

    def test_empty_when_no_facts(self):
        items = _items([(101, 100, "а")])
        data = _payload([_thread("тема", (101,))])
        l1 = _ok_l1(data, items)
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.package["threads"][0]["description"] == ""
        assert result.metrics["description_truncated"] is False

    def test_cap_at_word_boundary_flag_in_metrics(self):
        items = _items([(101, 100, "а"), (102, 110, "б")])
        long_a = " ".join(["слово"] * 70)     # 419 символов (≤500)
        long_b = " ".join(["другое"] * 70)
        data = _payload([_thread("тема", (101, 102), facts=[
            (long_a, (101,)), (long_b, (102,))])])
        l1 = _ok_l1(data, items)
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        description = result.package["threads"][0]["description"]
        assert len(description) <= DESCRIPTION_MAX
        assert result.metrics["description_truncated"] is True
        assert not description.endswith("слов")
        # Флаг — в metrics, не в L2-контенте.
        assert "description_truncated" not in result.package["threads"][0]

    def test_module_has_no_llm_dependency(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert "llm_client" not in source
        assert "async def build_fact_package" not in source


# ── SC-07: детерминизм ─────────────────────────────────────────────────────

class TestDeterminism:
    def test_double_run_byte_identical(self):
        l1, items = _simple()
        first = build_fact_package(l1, items, budget=("tokens", 100000))
        second = build_fact_package(l1, items, budget=("tokens", 100000))
        assert serialize_package(first.package) == \
            serialize_package(second.package)

    def test_input_not_mutated(self):
        l1, items = _simple()
        payload_before = copy.deepcopy(l1.payload)
        items_before = copy.deepcopy(items)
        build_fact_package(l1, items, budget=("tokens", 100000))
        assert l1.payload == payload_before
        assert items == items_before

    def test_serialize_is_canonical_json(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert serialize_package(result.package) == json.dumps(
            result.package, ensure_ascii=False, separators=(",", ":"))


# ── SC-03/SC-04: fail-closed и ID-целостность ─────────────────────────────

class TestFailClosed:
    def test_ok(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.status == STATUS_OK and result.deliverable

    def test_truncated_input_passthrough(self):
        l1, items = _simple()
        truncated = _raw_l1(l1.payload, status=L1_TRUNCATED, truncated=True,
                            skipped_ids=(11, 12), skipped_tg_ids=(99, 100),
                            chunk_count=3)
        result = build_fact_package(truncated, items, budget=("tokens", 100000))
        assert result.status == STATUS_TRUNCATED and result.deliverable
        assert result.metrics["l1_skipped_count"] == 2
        assert result.metrics["l1_chunk_count"] == 3

    def test_empty_input_not_deliverable(self):
        result = build_fact_package(empty_result(), _items([]))
        assert result.status == STATUS_EMPTY
        assert result.package["threads"] == []
        assert result.reason == REASON_EMPTY
        assert not result.deliverable

    def test_invalid_input_not_deliverable(self):
        l1, items = _simple()
        result = build_fact_package(invalid_result(REASON_MISSING_SOURCE), items)
        assert result.status == STATUS_INVALID
        assert result.package["threads"] == []
        assert result.reason == REASON_MISSING_SOURCE
        assert not result.deliverable

    def test_error_input_not_deliverable(self):
        result = build_fact_package(error_result("llm_error"), _items([]))
        assert result.status == STATUS_ERROR
        assert result.package["threads"] == []
        assert not result.deliverable

    def test_not_built_no_result(self):
        result = build_fact_package(None, _items([]))
        assert result.status == STATUS_NOT_BUILT
        assert result.package is None and result.reason == REASON_NO_RESULT
        assert not result.deliverable

    def test_not_built_payload_missing(self):
        result = build_fact_package(_raw_l1(None, status=L1_OK), _items([]))
        assert result.status == STATUS_NOT_BUILT
        assert result.reason == REASON_PAYLOAD_MISSING and result.package is None

    def test_not_built_unknown_status(self):
        result = build_fact_package(_raw_l1({}, status="weird"), _items([]))
        assert result.status == STATUS_NOT_BUILT
        assert result.reason == REASON_UNKNOWN_STATUS

    def test_deliverable_matrix(self):
        assert DELIVERABLE_STATUSES == frozenset({STATUS_OK, STATUS_TRUNCATED})


class TestIdIntegrity:
    def test_db_id_instead_of_tg_fails_closed(self):
        """DB ``id`` (1/2) вместо TG ``message_id`` (101/102) → invalid."""
        items = _items([(101, 100, "а"), (102, 110, "б")])
        payload = _payload([_thread("тема", (1, 2))])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_MISSING_SOURCE
        assert not result.deliverable

    def test_dangling_fabricated_id_invalid(self):
        items = _items([(101, 100, "а")])
        payload = _payload([_thread("тема", (999,))])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_MISSING_SOURCE

    def test_evidence_outside_thread_invalid(self):
        items = _items([(101, 100, "а"), (102, 110, "б")])
        payload = _payload([_thread("тема", (101,),
                                    facts=[("факт", (102,))])])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_EVIDENCE_NOT_IN_THREAD

    def test_evidence_ids_subset_of_message_ids(self):
        items = _items([(101, 100, "а"), (102, 110, "б"), (103, 120, "в")])
        payload = _payload([_thread("тема", (101, 102, 103),
                                    facts=[("факт", (101, 103))])])
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        thread = result.package["threads"][0]
        message_ids = {c["message_id"] for c in thread["chronology"]}
        assert set(thread["evidence_ids"]) <= message_ids

    def test_message_in_multiple_threads_invalid(self):
        items = _items([(101, 100, "а")])
        payload = _payload([_thread("а", (101,), thread_id="a"),
                            _thread("б", (101,), thread_id="b")])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_MESSAGE_IN_MULTIPLE_THREADS

    def test_unassigned_conflict_invalid(self):
        items = _items([(101, 100, "а")])
        payload = _payload([_thread("тема", (101,))], unassigned=[101])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_UNASSIGNED_CONFLICT

    def test_dangling_unassigned_invalid(self):
        items = _items([(101, 100, "а")])
        payload = _payload([_thread("тема", (101,))], unassigned=[999])
        result = build_fact_package(_raw_l1(payload), items)
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_MISSING_SOURCE

    def test_bad_input_type_invalid(self):
        payload = {"schema_version": 1, "threads": "нет",
                   "unassigned_message_ids": []}
        result = build_fact_package(_raw_l1(payload), _items([(101, 100, "а")]))
        assert result.status == STATUS_INVALID
        assert result.reason == REASON_BAD_INPUT


# ── SC-05: компактность / фрагменты ────────────────────────────────────────

class TestFragments:
    def test_evidence_first_priority(self):
        items = _items([(101, 100, "а"), (102, 110, "б"), (103, 120, "в")])
        payload = _payload([_thread("тема", (101, 102, 103),
                                    facts=[("факт", (103,))])])
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        fragments = result.package["threads"][0]["fragments"]
        assert fragments[0]["message_id"] == 103          # evidence — первым
        assert {f["message_id"] for f in fragments} == {101, 102, 103}

    def test_empty_text_skipped_but_kept_in_chronology(self):
        items = _items([(101, 100, "а"), (102, 110, "")])
        payload = _payload([_thread("тема", (101, 102))])
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        thread = result.package["threads"][0]
        assert {f["message_id"] for f in thread["fragments"]} == {101}
        assert [c["message_id"] for c in thread["chronology"]] == [101, 102]

    def test_does_not_duplicate_raw_log(self):
        rows = [(i, 100 + i, f"текст-{i}") for i in range(101, 107)]
        items = _items(rows)
        payload = _payload([_thread("тема", (101, 102),
                                    facts=[("факт", (102,))])], unassigned=[106])
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        text = serialize_package(result.package)
        # Фрагменты — только id темы; остальной лог (103–106) не передаётся.
        for mid in (101, 102):
            assert f"текст-{mid}" in text
        for mid in (103, 104, 105, 106):
            assert f"текст-{mid}" not in text
        assert result.metrics["fragments_count"] == 2

    def test_per_thread_cap_is_explicit(self):
        ids = list(range(101, 101 + 35))
        items = _items([(i, 100 + i, f"т{i}") for i in ids])
        payload = _payload([_thread("тема", tuple(ids))])
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 10**9))
        thread = result.package["threads"][0]
        assert len(thread["fragments"]) == MAX_FRAGMENTS_PER_THREAD
        assert result.metrics["skipped_fragments_count"] == 35 - MAX_FRAGMENTS_PER_THREAD
        assert result.status == STATUS_TRUNCATED


# ── SC-06: бюджет и усечение ───────────────────────────────────────────────

class TestBudget:
    def test_fits(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("tokens", 100000))
        assert result.package["budget"]["fits"] is True
        assert result.status == STATUS_OK

    def test_fragments_oldest_dropped_last_saved(self):
        items = _items([(101, 100, "старое"), (102, 110, "среднее"),
                        (103, 120, "новое")])
        payload = _payload([_thread("тема", (101, 102, 103),
                                    facts=[("факт", (103,))])])
        l1 = _raw_l1(payload)
        full = build_fact_package(l1, items, budget=("chars", 10**6))
        tight = build_fact_package(l1, items,
                                   budget=("chars", full.metrics["estimated"] - 1))
        assert tight.status == STATUS_TRUNCATED
        assert tight.metrics["skipped_fragments_count"] >= 1
        remaining = [f["message_id"]
                     for f in tight.package["threads"][0]["fragments"]]
        assert 101 not in remaining          # самый старый вытеснен
        assert 103 in remaining              # последний сохранён (§93)

    def test_description_cleared_before_threads(self):
        long_text = " ".join(["факт"] * 100)
        # Пустые тексты → фрагментов нет: вытесняется именно description.
        items = _items([(101, 100, ""), (102, 110, "")])
        payload = _payload([_thread("тема", (101, 102),
                                    facts=[(long_text, (101,)), ("второй", (102,))])])
        l1 = _raw_l1(payload)
        full = build_fact_package(l1, items, budget=("chars", 10**6))
        tight = build_fact_package(l1, items,
                                   budget=("chars", full.metrics["estimated"] - 1))
        assert tight.status == STATUS_TRUNCATED
        assert tight.metrics["descriptions_cleared_count"] >= 1
        assert tight.package["threads"][0]["description"] == ""
        # Факты не режутся частично — тема и факты на месте.
        assert len(tight.package["threads"][0]["facts"]) == 2

    def test_zero_threads_becomes_empty(self):
        l1, items = _simple()
        result = build_fact_package(l1, items, budget=("chars", 1))
        assert result.status == STATUS_EMPTY
        assert result.package["threads"] == []
        assert result.reason == REASON_BUDGET_EMPTY
        assert not result.deliverable

    def test_whole_threads_dropped_oldest_first(self):
        # Пустые тексты и без фактов → вытесняются целые темы (старая первой).
        items = _items([(101, 100, ""), (102, 200, "")])
        payload = _payload([_thread("старая", (101,), thread_id="a"),
                            _thread("новая", (102,), thread_id="b")])
        l1 = _raw_l1(payload)
        full = build_fact_package(l1, items, budget=("chars", 10**6))
        tight = build_fact_package(
            l1, items, budget=("chars", full.metrics["estimated"] - 1))
        assert tight.status == STATUS_TRUNCATED
        assert tight.metrics["skipped_threads_count"] == 1
        assert tight.package["threads"][0]["thread_id"] == "b"

    def test_truncation_logged_not_silent(self, caplog):
        l1, items = _simple()
        with caplog.at_level("INFO"):
            build_fact_package(l1, items, budget=("chars", 1), correlation_id="r1")
        assert "FACT_PACKAGE_TRUNCATED" in caplog.text
        assert "FACT_PACKAGE_START" in caplog.text
        assert "FACT_PACKAGE_COMPLETE" in caplog.text

    def test_logs_r17_safe(self, caplog):
        secret = "СЕКРЕТНЫЙ_ТЕКСТ_СООБЩЕНИЯ_777"
        items = _items([(101, 100, secret)])
        payload = _payload([_thread("тема", (101,), facts=[(secret, (101,))])])
        with caplog.at_level("INFO"):
            build_fact_package(_raw_l1(payload), items,
                               budget=("tokens", 100000), correlation_id="r2")
        assert secret not in caplog.text
        assert "run_id=r2" in caplog.text

    def test_resolver_hot_first(self):
        hot = {"limits.summary_max_context_tokens": 4242}
        kind, limit = resolve_fact_package_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert (kind, limit) == ("tokens", 4242)

    def test_resolver_chars_fallback(self, monkeypatch):
        monkeypatch.setenv("SUMMARY_MAX_CONTEXT_CHARS", "7000")
        hot = {"limits.summary_max_context_tokens": None,
               "limits.summary_max_context_chars": 7000}
        kind, limit = resolve_fact_package_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert (kind, limit) == ("chars", 7000)

    def test_resolver_default_tokens(self):
        kind, limit = resolve_fact_package_budget(
            hot_get=lambda key, default=None: default)
        assert kind == "tokens" and limit == 30000

    def test_resolver_unlimited_sentinel(self):
        hot = {"limits.summary_max_context_tokens": -1}
        kind, limit = resolve_fact_package_budget(
            hot_get=lambda key, default=None: hot.get(key, default))
        assert kind == "tokens"
        assert limit == Settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS


# ── SC-02/SC-10: 0 LLM, каталог без изменений, живой путь ─────────────────

class TestLivePathInvariants:
    def test_generator_fact_package_wiring_is_flag_gated(self):
        # S5 (ADR-1026-7 D5): врезка пакета фактов в живой путь появилась, но
        # строго ЗА kill-switch (`SUMMARY_HYBRID_L2_ENABLED`, default OFF);
        # OFF-путь `_generate_two_call` (Stage-1/Stage-2) сохранён байт-в-байт.
        text = (ROOT / "services/summary_generator.py").read_text(encoding="utf-8")
        assert "summary_fact_package" in text
        assert "_generate_two_call" in text
        assert "_hybrid_l2_enabled" in text
        assert "SUMMARY_HYBRID_L2_ENABLED" in text
        # XML-модуль не тронут (S5 публикацию/XML не меняет, §104).
        xml = (ROOT / "services/summary_xml.py").read_text(encoding="utf-8")
        assert "fact_package" not in xml
        assert "summary_fact_package" not in xml

    def test_catalog_zero_delta(self):
        assert len(pc.REGISTRY) == 469
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 444
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_no_new_env_key(self):
        assert "SUMMARY_FACT_PACKAGE" not in pc.REGISTRY
        assert "SUMMARY_FACT_PACKAGE" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_app_version_bumped(self):
        assert APP_VERSION == "2.58.26"

    @pytest.mark.asyncio
    async def test_two_calls_stage1_stage2(self):
        from unittest.mock import AsyncMock, MagicMock

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
        assert "fact_package" not in str(steps)
        assert draft.text == "связный текст"
