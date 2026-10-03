"""ASAP 4.1 волна 3 (эпик asap-4-1-durable-whole-window-summary) — T-4607 /
T-4608: L1 semantic map v1 + fail-soft/partial success (spec §2 B.1/B.2;
ADR-1028-8 D3).

Покрытие:
  * контракты map v1: topics/events/relationships/unassigned_message_ids;
    schema_version 1; unknown-field строго; bad type; bad version; unknown
    message_id; unassigned ОБЯЗАТЕЛЕН; id-space (TG);
  * «в L1 output нет текстов сообщений» (R6-B-002): валидатор/compaction
    не допускают payload-полей; канон-промпт — без facts/текстов;
  * бюджеты: topics ≤100 / title ≤200 / hint ≤160 (env) / tokens ≤
    SUMMARY_L1_MAP_MAX_TOKENS (env) → deterministic compaction + честный
    map_degraded (НИКОГДА не whole-run invalid и не «гильотина»: ids
    сохраняются);
  * L1 в map-режиме (run_l1): «ровно 1 запрос» (WHOLE_WINDOW), correction
    retry, kill-switch OFF → §95-v2 + too_many_facts (бит-в-бит);
  * T-4608 partial success: в overflow успешные maps сохраняются, падение
    сегмента → deterministic minimal map (ids сохранены), coverage 100%,
    честный map_degraded; L1 failed ≠ Summary failed; OFF-возврат LEVEL-2
    mechanics.
"""
import json
import types

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_l1_contract import (
    REASON_TOO_MANY_FACTS,
    REASON_UNKNOWN_MESSAGE_ID,
    build_id_space,
)
from services.summary_l1_semantic_map import (
    MAP_SCHEMA_VERSION,
    REASON_MAP_DEGRADED,
    MapResult,
    collect_unknown_map_ids,
    compact_semantic_map,
    map_correction_block,
    map_payload_tokens,
    map_result_invalid,
    merge_map_payloads,
    minimal_map_for_rows,
    parse_map_response,
    resolve_map_budgets,
    semantic_map_enabled,
    validate_semantic_map,
)

pytestmark = pytest.mark.asap41

CHAT_ID = -100777


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _slot(monkeypatch, base_url="http://127.0.0.1:8080/v1",
          model="large-model"):
    # Global model (не dedicated slot) → llm.generate-канон (мок-совместимо).
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_MODEL_NAME", model,
                        raising=False)


def _patch_capacity(monkeypatch, effective=262144, eager=True):
    """Deterministic capacity резолв (runtime discovery level)."""

    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime" if eager else "fallback",
            confidence="estimated",
            fallback_used=not eager,
            effective_context_window=int(effective))

    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


def _rows(count, *, start=101, text_size=32):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} о коммуналке " * (text_size // 10),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _payload_items(rows, chat_id=CHAT_ID):
    return sl1.build_l1_payload(rows, chat_id)


def _space(items):
    return build_id_space(items)


def _map_data(ids_by_topic, *, events=None, unassigned=(), **extra):
    topics = [
        {"topic_id": f"topic_{i + 1:03d}", "title": f"тема {i + 1}",
         "message_ids": list(ids), "participants": ["Автор0"],
         "short_hint": "суть темы"}
        for i, ids in enumerate(ids_by_topic)
    ]
    data = {"schema_version": 1, "topics": topics,
            "events": events or [],
            "unassigned_message_ids": list(unassigned)}
    data.update(extra)
    return data


# ── Контракт map v1 (T-4607) ───────────────────────────────────────────────

class TestMapContract:
    def test_valid_canonical(self):
        rows = _rows(5)
        space = _space(_payload_items(rows))
        data = _map_data([[101, 102], [102, 103]], unassigned=[104],
                         events=[{"kind": "спор", "message_ids": [101]}],
                         relationships=[{"type": "reply",
                                         "message_ids": [102],
                                         "topic_ids": ["topic_001"]}])
        res = validate_semantic_map(data, space)
        assert res.usable and res.status == "ok"
        assert res.topics_count == 2 and res.events_count == 1
        # unassigned покрывает остальные id окна (не упомянутые в темах).
        assert 105 in res.payload["unassigned_message_ids"]
        assert 104 in res.payload["unassigned_message_ids"]
        assert res.payload["schema_version"] == MAP_SCHEMA_VERSION

    def test_no_source_payload_in_output(self):
        """R6-B-002: тексты сообщений в L1 output не живут ни в схеме, ни в
        канонизации — topics несут только id/title/participants/hint."""
        rows = _rows(4)
        space = _space(_payload_items(rows))
        data = _map_data([[101, 102]])
        res = validate_semantic_map(data, space)
        assert res.usable
        for topic in res.payload["topics"]:
            assert set(topic) == {"topic_id", "title", "message_ids",
                                  "participants", "short_hint"}
            assert all(isinstance(v, (str, int, list))
                       for v in topic.values())
        # Тексты сообщений окна не попадают в payload ни в каком поле.
        serialized = json.dumps(res.payload, ensure_ascii=False)
        assert "сообщение 0 о коммуналке" not in serialized

    def test_unknown_field_strict(self):
        space = _space(_payload_items(_rows(3)))
        bad = _map_data([[101]])
        bad["unknown"] = 1
        res = validate_semantic_map(bad, space)
        assert res.status == "invalid" and res.reason == "unknown_field"

    def test_topic_unknown_field_strict(self):
        space = _space(_payload_items(_rows(3)))
        data = _map_data([[101]])
        data["topics"][0]["text"] = "текст сообщения"   # source payload
        res = validate_semantic_map(data, space)
        assert res.status == "invalid" and res.reason == "unknown_field"

    def test_bad_schema_version_rejected(self):
        space = _space(_payload_items(_rows(3)))
        data = _map_data([[101]])
        data["schema_version"] = 2
        res = validate_semantic_map(data, space)
        assert res.status == "invalid" and res.reason == "bad_schema_version"

    def test_bad_type(self):
        space = _space(_payload_items(_rows(3)))
        res = validate_semantic_map({"schema_version": 1, "topics": "x",
                                     "events": [], "unassigned_message_ids":
                                     []}, space)
        assert res.status == "invalid" and res.reason == "bad_type"

    def test_unknown_message_id_rejected(self):
        space = _space(_payload_items(_rows(3)))
        res = validate_semantic_map(_map_data([[101, 999]]), space)
        assert res.status == "invalid"
        assert res.reason == REASON_UNKNOWN_MESSAGE_ID

    def test_unassigned_required(self):
        """unassigned_message_ids — ОБЯЗАТЕЛЬНОЕ поле (может быть пустым
        списком; отсутствующее поле → invalid)."""
        space = _space(_payload_items(_rows(3)))
        data = _map_data([[101]])
        data.pop("unassigned_message_ids")
        res = validate_semantic_map(data, space)
        assert res.status == "invalid"

    def test_empty_ok(self):
        space = _space(_payload_items(_rows(3)))
        res = validate_semantic_map(_map_data([], unassigned=[101, 102]),
                                    space)
        assert res.status == "empty" and not res.usable
        # 101/102 — явные, 103 — auto-unassigned (покрытие по построению).
        assert res.unassigned_count == 3

    def test_many_to_many_ok(self):
        space = _space(_payload_items(_rows(4)))
        res = validate_semantic_map(_map_data([[101, 102], [102, 103]]), space)
        assert res.usable

    def test_collect_unknown_ids(self):
        space = _space(_payload_items(_rows(3)))
        data = _map_data([[101, 999]], unassigned=[888],
                         events=[{"kind": "x", "message_ids": [777]}])
        assert collect_unknown_map_ids(data, space) == [999, 777, 888]


# ── Бюджеты + deterministic compaction (никогда не invalid) ────────────────

class TestBudgesAndCompaction:
    def test_hint_trimmed_and_degraded(self, monkeypatch):
        monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_HINT_MAX_CHARS",
                            20, raising=False)
        space = _space(_payload_items(_rows(3)))
        data = _map_data([[101]], )
        data["topics"][0]["short_hint"] = "очень длинный хинт " * 5
        res = validate_semantic_map(data, space)
        compacted, stats, degraded = compact_semantic_map(res.payload,
                                                          id_space=space)
        assert degraded
        assert stats["hints_trimmed"] >= 1
        assert all(len(t["short_hint"]) <= 20 for t in compacted["topics"])
        # ids не потеряны
        assert compacted["topics"][0]["message_ids"] == [101]

    def test_topics_over_cap_merged_not_invalid(self):
        """> MAX_THREADS тем → deterministic merge (пересечения, затем
        pairwise) — НИКОГДА не invalid; полный набор ids сохранён."""
        space = _space(_payload_items(_rows(
            108, start=1, text_size=10)))
        data = _map_data([[1 + i] for i in range(108)])
        res = validate_semantic_map(data, space)
        assert res.usable
        compacted, stats, degraded = compact_semantic_map(res.payload,
                                                          id_space=space)
        assert degraded and stats["topics_merged"] > 0
        topics = compacted["topics"]
        assert len(topics) <= 100
        covered = set()
        for t in topics:
            covered.update(t["message_ids"])
        assert covered == set(range(1, 109))          # не гильотина
        assert stats["reason"] == "map_compacted"

    def test_token_budget_compaction(self, monkeypatch):
        monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MAP_MAX_TOKENS",
                            220, raising=False)
        space = _space(_payload_items(_rows(40, text_size=8)))
        extra_topics = [
            {"topic_id": f"topic_{i + 1:03d}", "title": f"тема {i + 1} "
             "с длинным пояснением и контекстом обсуждения",
             "message_ids": [101 + i, 102 + i],
             "participants": ["Автор0", "Автор1", "Автор2"],
             "short_hint": "подробный хинт темы " * 6} for i in range(30)]
        data = {"schema_version": 1, "topics": extra_topics, "events": [],
                "relationships": [{"type": "reply",
                                   "message_ids": [101],
                                   "topic_ids": ["topic_001"]}],
                "unassigned_message_ids": []}
        res = validate_semantic_map(data, space)
        assert res.usable
        before = map_payload_tokens(res.payload)
        assert before > 220
        compacted, stats, degraded = compact_semantic_map(res.payload,
                                                          id_space=space)
        after = map_payload_tokens(compacted)
        assert degraded
        assert after < before
        covered = set()
        for t in compacted["topics"]:
            covered.update(t["message_ids"])
        assert covered == {101 + i for i in range(31)}   # не гильотина

    def test_relationships_dropped_before_topics(self, monkeypatch):
        monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MAP_MAX_TOKENS",
                            220, raising=False)
        space = _space(_payload_items(_rows(6)))
        long_hint = "подробное пояснение темы " * 6
        data = _map_data([[101, 102], [103, 104], [105, 106]],
                         relationships=[{"type": "reply",
                                         "message_ids": [101],
                                         "topic_ids": ["topic_001"]}])
        data["top"
             "ics"][0]["short_hint"] = long_hint
        data["topics"][1]["short_hint"] = long_hint
        data["topics"][2]["short_hint"] = long_hint
        res = validate_semantic_map(data, space)
        assert map_payload_tokens(res.payload) > 220
        compacted, stats, degraded = compact_semantic_map(res.payload,
                                                          id_space=space)
        assert degraded
        assert map_payload_tokens(compacted) <= 220
        assert stats["relationships_dropped"] >= 1 \
            or stats["topics_merged"] > 0 or stats["hints_cleared"] > 0
        assert "relationships" not in compacted \
            or stats["relationships_dropped"] == 0

    def test_compact_never_invalid(self):
        space = _space(_payload_items(_rows(4)))
        garbage = {"schema_version": 1, "topics": "мусор"}
        compacted, stats, degraded = compact_semantic_map(garbage,
                                                          id_space=space)
        assert compacted is None and not degraded


# ── Merge + minimal map (T-4608 partial success) ───────────────────────────

class TestMergeAndMinimal:
    def test_merge_map_payloads_intersects(self):
        space = _space(_payload_items(_rows(6)))
        a = validate_semantic_map(_map_data([[101, 102]], unassigned=[105]),
                                  space)
        b = validate_semantic_map(_map_data([[102, 103]],
                                            events=[{"kind": "спор",
                                                     "message_ids": [102]}],
                                            unassigned=[106]), space)
        merged = merge_map_payloads([a.payload, b.payload])
        assert merged["schema_version"] == MAP_SCHEMA_VERSION
        assert len(merged["topics"]) == 1
        assert merged["topics"][0]["message_ids"] == [101, 102, 103]
        assert merged["events"][0]["message_ids"] == [102]
        assert 105 in merged["unassigned_message_ids"] \
            and 106 in merged["unassigned_message_ids"]

    def test_minimal_map_full_ids_and_roster(self):
        rows = _rows(5)
        items = _payload_items(rows)
        minimal = minimal_map_for_rows(items, seg_index=3)
        assert minimal is not None
        assert minimal["schema_version"] == MAP_SCHEMA_VERSION
        topic = minimal["topics"][0]
        assert topic["message_ids"] == [101, 102, 103, 104, 105]
        assert topic["participants"] == ["Автор0", "Автор1", "Автор2"]
        assert minimal["events"] == []
        assert minimal["unassigned_message_ids"] == []

    def test_minimal_map_none_without_ids(self):
        assert minimal_map_for_rows([{"no_id": 1}], seg_index=1) is None


# ── L1 map-режим (WHOLE_WINDOW, correction retry, OFF-паритет) ─────────────

class ScriptedLLM:
    def __init__(self, responses, *, fallback="не json"):
        self.responses = list(responses)
        self.fallback = fallback
        self.calls = []

    async def generate(self, messages, **kw):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return self.fallback

    @property
    def consumed(self) -> int:
        return len(self.calls)


def _map_json(ids_by_topic, *, unassigned=(), events=None):
    topics = [{"topic_id": f"topic_{i + 1:03d}",
               "title": f"тема {i + 1}", "message_ids": list(ids),
               "participants": ["Автор0"], "short_hint": "суть"}
              for i, ids in enumerate(ids_by_topic)]
    return json.dumps({"schema_version": 1, "topics": topics,
                       "events": events or [],
                       "unassigned_message_ids": list(unassigned),
                       "response_mode": "serious", "cover_prompt": ""},
                      ensure_ascii=False)


@pytest.mark.asyncio
async def test_run_l1_map_whole_window_single_call(monkeypatch):
    """§44-A: 839-совместимый happy path — map-режим, ровно ОДИН L1-запрос,
    payload = map v1, coverage 100%."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch, effective=262144)
    rows = _rows(40)
    llm = ScriptedLLM([_map_json([[101 + i for i in range(40)]],
                                 unassigned=[])])
    result = await run_l1_map_call(llm, rows)
    assert result.usable and result.status == "ok"
    assert result.payload["schema_version"] == MAP_SCHEMA_VERSION
    assert len(result.payload["topics"]) == 1
    assert result.payload["topics"][0]["message_ids"] == [
        101 + i for i in range(40)]
    assert len(llm.calls) == 1                      # ровно один запрос
    cov = sl1.last_run_coverage()
    assert cov and cov["coverage_percent"] == 100.0
    assert not result.map_degraded


async def run_l1_map_call(llm, rows):
    """WHOLE_ADDRESS map-call через capacity-first (мастер + map ON)."""
    return await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                            correlation_id="map-run-1")


@pytest.mark.asyncio
async def test_run_l1_map_correction_retry(monkeypatch):
    """Retryable-причина (bad_schema_version) map-ответа → ровно одна
    исправляющая попытка с map-коррекцией; второй ответ → ok."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)
    rows = _rows(4)
    bad = "не json"
    good = _map_json([[101, 102, 103, 104]])
    llm = ScriptedLLM([bad, good])
    result = await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                              correlation_id="map-run-2")
    assert result.usable and len(result.payload["topics"][0][
        "message_ids"]) == 4
    assert len(llm.calls) == 2
    correction = llm.calls[1][-1]["content"]
    assert "semantic map v1" in correction


@pytest.mark.asyncio
async def test_run_l1_map_degraded_on_budget(monkeypatch):
    """Переполнение бюджета карты (малый env-бюджет) → compaction + честный
    map_degraded в L1_RESULT, статус ok (никогда не invalid)."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MAP_MAX_TOKENS",
                        190, raising=False)
    rows = _rows(32, text_size=8)
    topics = [{"topic_id": f"topic_{i + 1:03d}",
               "title": f"тема {i + 1} подробная микроистория эпизода",
               "message_ids": [101 + i, 102 + i],
               "participants": ["Автор0", "Автор1"],
               "short_hint": "нечто длинное про тему " * 4}
              for i in range(30)]
    llm = ScriptedLLM([json.dumps({"schema_version": 1, "topics": topics,
                                   "events": [], "unassigned_message_ids":
                                   []}, ensure_ascii=False)])
    result = await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                              correlation_id="map-run-3")
    assert result.usable and result.map_degraded
    assert result.map_reason == REASON_MAP_DEGRADED
    ids = set()
    for t in (result.payload or {}).get("topics") or []:
        ids.update(t["message_ids"])
    assert {101 + i for i in range(30)}.issubset(ids)


@pytest.mark.asyncio
async def test_run_l1_kill_switch_off_keeps_v2(monkeypatch):
    """OFF → бит-в-бит 2.58.46: §95-v2 контракт + too_many_facts
    (capacity guard OFF — прежняя валидация), chunking-триггер planning
    estimate."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_SEMANTIC_MAP_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_CAPACITY_GUARD_ENABLED",
                        False, raising=False)
    _slot(monkeypatch)
    rows = _rows(3)
    v2_payload = json.dumps({
        "schema_version": 2, "threads": [{"thread_id": "thread_001",
                                          "topic": "тема",
                                          "message_ids": [101, 102, 103],
                                          "facts": [{"text": f"факт {i}",
                                                     "evidence_message_ids":
                                                     [101, 102, 103]}
                                                    for i in range(31)]}],
        "unassigned_message_ids": []}, ensure_ascii=False)
    llm = ScriptedLLM([v2_payload])
    result = await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                              correlation_id="off-run-1", budget=(
                                  "tokens", 100000))
    # 31 факт в теме → too_many_facts (structural ceiling §95-v2; OFF-ветка
    # сохраняет класс исхода; capacity guard снимает repair).
    assert result.status == "invalid"
    assert result.invalid_reason == REASON_TOO_MANY_FACTS
    assert not result.usable


@pytest.mark.asyncio
async def test_map_mode_too_many_facts_impossible(monkeypatch):
    """T-4607 (D3): 31+ «фактов» в map-режиме невозможны по построению —
    output map v1 даже от модели, которая «хочет» перечислить тексты: лишние
    поля → invalid (schema), но/topics не несут фактов — too_many_facts
    reason не существует."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)
    rows = _rows(33)
    # модель пытается вернуть §95-v2: кардинальность фактов больше не
    # является выходным измерением → валидатор карты Mapping отклоняет
    # (threads=unknown field), retryable → correction (map-канон) задан в
    # промпте; в mock map-JSON возвращает все темы без facts.
    v2_attempt = json.dumps({"schema_version": 2, "threads": [],
                             "unassigned_message_ids": []})
    corrected = _map_json([[101 + i for i in range(33)]])
    llm = ScriptedLLM([v2_attempt, corrected])
    result = await run_l1_map_call(llm, rows)
    assert result.usable
    assert 31 <= len(result.payload["topics"][0]["message_ids"])
    correction = llm.calls[1][-1]["content"]
    assert "schema_version: 1" in correction \
        or "semantic map v1" in correction


# ── T-4608: partial success в overflow ─────────────────────────────────────

@pytest.mark.asyncio
async def test_overflow_partial_success_minimal_map(monkeypatch):
    """CAPACITY_OVERFLOW: 3 сегмента, средний падает после restore →
    deterministic minimal map; успешные maps сохраняются; coverage 100%;
    честный map_degraded (не «success» маска)."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)

    async def _force_budget(system, slot):
        return ("tokens", 260, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _force_budget)
    rows = _rows(9)
    invalid = json.dumps({"schema_version": 91, "threads": []})
    llm = ScriptedLLM([
        _map_json([[101, 102]]),                  # seg1 ok
        invalid, invalid, invalid, invalid,       # seg2: run + retry + restore
        _map_json([[108, 109]]),                  # seg3 ok
    ])
    result = await run_l1_map_call(llm, rows)
    assert result.usable and result.status == "ok"
    assert result.map_degraded
    assert result.map_reason == REASON_MAP_DEGRADED
    ids = set()
    for t in (result.payload or {}).get("topics") or []:
        ids.update(t["message_ids"])
    # Никогда не превращать 3/4 в 0/9: все 9 id покрыты (полный coverage).
    assert {101 + i for i in range(9)} == ids
    cov = sl1.last_run_coverage()
    assert cov and cov["coverage_percent"] == 100.0


@pytest.mark.asyncio
async def test_overflow_total_failure_still_honest(monkeypatch):
    """Все сегменты упали после restore — ledger ON: deterministic minimal
    maps сохраняют полное покрытие (частичный success по построению; run
    жив, честный map_degraded)."""
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)

    async def _force_budget(system, slot):
        return ("tokens", 260, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _force_budget)
    rows = _rows(9)
    invalid = json.dumps({"broken": True})
    llm = ScriptedLLM([invalid] * 12)
    result = await run_l1_map_call(llm, rows)
    # minimal map затягивает все непроанализированные сегменты → живой run.
    assert result.usable and result.map_degraded
    ids = set()
    for t in (result.payload or {}).get("topics") or []:
        ids.update(t["message_ids"])
    assert ids == {101 + i for i in range(9)}


@pytest.mark.asyncio
async def test_l1_failed_writer_source_no_legacy(monkeypatch):
    """T-4608 §46: L1 total failure + writer-source ON → Writer от полного
    окна (instruction unavailable), НИКАКОГО урезанного Legacy; run жив."""
    import types as _types
    from unittest.mock import AsyncMock, MagicMock
    from services.summary_generator import SummaryGenerator
    _patch_capacity(monkeypatch, effective=262144)
    rows = _rows(6)
    doc = {"schema_version": 1, "title": "Заголовок.",
           "paragraphs": [{"text": "текст.", "emphasis_spans": [],
                           "evidence_message_ids": [101]}]}
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=[
        "не json", "не json",
        json.dumps(doc, ensure_ascii=False),
        json.dumps({"status": "approved", "findings": []},
                   ensure_ascii=False)])
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_COVER_ARTICLE_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_COVER_FALLBACK_ENABLED",
                        False, raising=False)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    legacy = AsyncMock(return_value=False)
    gen._run_legacy_pipeline = legacy
    await gen._run_hybrid_l2(CHAT_ID, rows, None, "wave3-l1-fail")
    contents = [(call.args[0][-1]["content"] if call.args else
                 (call.kwargs.get("messages") or [{}])[-1].get("content")
                 or "")
                for call in llm.generate.await_args_list]
    assert any("structure source yourself" in c for c in contents)
    writer_content = next(c for c in contents
                          if "structure source yourself" in c)
    assert all(str(101 + i) in writer_content for i in range(6))
    gen._deliver_l2_plain.assert_awaited_once()
    legacy.assert_not_awaited()          # запрет Legacy из-за L1 (§48 Run 1)
