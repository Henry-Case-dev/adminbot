"""ASAP 8 F2 — единый execution input Summary (Test = production, ТЗ §3)
и map-v1 unknown-ref repair (§3.4).

Покрытие:
  * S5 — паритет: один fixture → одинаковые source-window fingerprint и
    anchor_mode в prod-пути (durable-окно передано готовым) и test-пути
    (in-memory mount); fingerprint детерминирован (run_id + checksum rows);
    in-memory mount делает 0 durable-записей;
  * S6 — небольшой мусор (unknown refs) в map v1 → deterministic remove,
    полезная карта выживает, пайплайн продолжается (run_l1, ровно 1 вызов);
  * S7 — карта бесполезна после ремонта → РОВНО ОДИН correction retry →
    fail-closed (и retry-спасение вторым валидным ответом);
  * §28.4 — invented refs НИКОГДА не резолвятся (только удаляются);
  * repair kill-switch OFF → прежняя строгость (fail-closed unknown_message_id);
  * dry-run (audit-сценарий): реально строит source_window + anchors
    (anchor_mode=True в stages), карта строится вместо
    TEST_L1_INVALID · unknown_message_id;
  * телеметрия §3.4 (unknown_refs_count/removed_unknown_refs/
    map_useful_after_repair/retry_used/anchor_mode/source_window_present)
    в map_stats L1Result (→ SUMMARY_L1_STAGE).

TEST-LIFECYCLE: CONTRACT owner=ASAP8/F2
"""
import copy
import json
import types
from unittest.mock import MagicMock

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_execution_input import (
    build_focus_block,
    build_summary_execution_input,
    window_fingerprint,
)
from services.summary_l1_contract import (
    REASON_L1_USELESS_AFTER_REPAIR,
    REASON_UNKNOWN_MESSAGE_ID,
    build_id_space,
)
from services.summary_l1_repair import (
    USELESS_MAP_MASS_UNKNOWN_REFS,
    USELESS_MAP_NO_STRUCTURE,
    repair_semantic_map,
)
from services.summary_l1_semantic_map import RETRYABLE_MAP_REASONS
from services.summary_source_window import (
    build_source_window,
    store_source_window,
)

pytestmark = pytest.mark.asap41

CHAT_ID = -100777
CORR = "cid-f2"


# ── Общие хелперы (паттерн test_summary_semantic_map_asap41) ────────────────

def _rows(count, *, start=101, text_size=32):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} о коммуналке " * (text_size // 10),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


class ScriptedLLM:
    def __init__(self, responses, *, fallback="не json"):
        self.responses = list(responses)
        self.fallback = fallback
        self.calls: list = []

    async def generate(self, messages, **kw):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return self.fallback


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


def _patch_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime", confidence="estimated", fallback_used=False,
            effective_context_window=int(effective))

    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


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
            "events": list(events or []),
            "unassigned_message_ids": list(unassigned)}
    data.update(extra)
    return data


# ── window_fingerprint / build_focus_block (чистые контракты) ───────────────

class TestFingerprintContract:
    def test_deterministic_same_fixture_same_fingerprint(self):
        rows = _rows(4)
        w1 = build_source_window(CORR, CHAT_ID, rows)
        w2 = build_source_window(CORR, CHAT_ID, rows)
        assert w1 is not None and w2 is not None
        assert window_fingerprint(CORR, w1.messages_json) != ""
        assert window_fingerprint(CORR, w1.messages_json) == \
            window_fingerprint(CORR, w2.messages_json)

    def test_sensitive_to_run_id_and_material(self):
        rows = _rows(3)
        window = build_source_window(CORR, CHAT_ID, rows)
        base = window_fingerprint(CORR, window.messages_json)
        assert window_fingerprint("other-run", window.messages_json) != base
        rows_mutated = _rows(3)
        rows_mutated[1]["text"] += " дополнение"
        window2 = build_source_window(CORR, CHAT_ID, rows_mutated)
        assert window2.messages_json != window.messages_json
        assert window_fingerprint(CORR, window2.messages_json) != base

    def test_focus_block_legacy_semantics(self):
        assert build_focus_block(None) == ""
        assert build_focus_block("   ") == ""
        from services.summary_xml import escape_xml_text
        block = build_focus_block("выборы <2026>")
        assert escape_xml_text("выборы <2026>") in block
        assert block.endswith("</focus>\n\n")

    def test_generator_apply_focus_is_delegate(self):
        from services.summary_generator import _apply_focus
        base = "<user/>контент"
        assert _apply_focus(base, None) is base
        assert _apply_focus(base, "  ") is base
        assert _apply_focus(base, "тема X") == build_focus_block("тема X") + base


# ── repair_semantic_map: S6/§28.4 (unit) ────────────────────────────────────

class TestRepairSemanticMap:
    def test_small_unknown_refs_removed_map_survives(self):
        space = _space(sl1.build_l1_payload(_rows(4), CHAT_ID))
        data = _map_data([[101, 999]], unassigned=[102, 888],
                         events=[{"kind": "решение",
                                  "message_ids": [103, 777]}])
        original = copy.deepcopy(data)
        repaired, report = repair_semantic_map(data, space)
        assert data == original                      # вход не мутируется
        # §28.4: invented refs удалены, НЕ подменены реальными id.
        assert repaired["topics"][0]["message_ids"] == [101]
        assert repaired["events"][0]["message_ids"] == [103]
        assert repaired["unassigned_message_ids"] == [102]
        assert report.unknown_refs_count == 3        # {999, 888, 777}
        assert report.removed_unknown_refs == 3
        assert report.map_useful_after_repair is True
        assert report.useless_reason == ""
        # Повторный прогон байт-идентичен (repair чистый).
        again, report2 = repair_semantic_map(repaired, space)
        assert again == repaired
        assert report2.unknown_refs_count == 0
        assert report2.map_useful_after_repair is True

    def test_empty_containers_dropped(self):
        space = _space(sl1.build_l1_payload(_rows(4), CHAT_ID))
        data = _map_data([[999]],                        # только unknown
                         events=[{"kind": "факт",
                                  "message_ids": [888]}])
        repaired, report = repair_semantic_map(data, space)
        assert repaired["topics"] == []
        assert repaired["events"] == []
        assert report.topics_removed == 1
        assert report.events_removed == 1
        assert report.map_useful_after_repair is False
        assert report.useless_reason == USELESS_MAP_NO_STRUCTURE

    def test_mass_unknown_refs_useless(self):
        space = _space(sl1.build_l1_payload(_rows(4), CHAT_ID))
        data = _map_data([[101, 999, 888]], unassigned=[777, 666])
        _repaired, report = repair_semantic_map(data, space)
        # 4 различных unknown из 5 сосланных → доля > 0.5 → useless.
        assert report.unknown_refs_count == 4
        assert report.map_useful_after_repair is False
        assert report.useless_reason == USELESS_MAP_MASS_UNKNOWN_REFS

    def test_known_survivor_counts_toward_useful(self):
        space = _space(sl1.build_l1_payload(_rows(4), CHAT_ID))
        # 1 unknown из 4 ссылок (≤0.5) + живая тема → продолжаем.
        data = _map_data([[101, 102, 999]], unassigned=[103])
        repaired, report = repair_semantic_map(data, space)
        assert report.map_useful_after_repair is True
        assert repaired["topics"][0]["message_ids"] == [101, 102]
        assert repaired["unassigned_message_ids"] == [103]

    def test_structural_garbage_left_to_validator(self):
        space = _space(sl1.build_l1_payload(_rows(4), CHAT_ID))
        data = _map_data([[101]])
        data["topics"].append("мусор-не-dict")
        data["events"] = "не-список"
        repaired, _report = repair_semantic_map(data, space)
        assert "мусор-не-dict" in repaired["topics"]
        assert repaired["events"] == "не-список"

    def test_useless_reason_in_retryable_map_set(self):
        # §3.4: useless после repair → РОВНО ОДИН correction retry.
        assert REASON_L1_USELESS_AFTER_REPAIR in RETRYABLE_MAP_REASONS


# ── run_l1 map-v1 поток: S6/S7 (integration, 0 LLM-моков вне ScriptedLLM) ──

def _map_json(ids_by_topic, *, unassigned=(), events=None):
    return json.dumps(_map_data(ids_by_topic, events=events,
                                unassigned=unassigned),
                      ensure_ascii=False)


class TestRunL1MapV1Repair:
    async def _run(self, llm, rows, monkeypatch, *, repair_on=True):
        _patch_capacity(monkeypatch)
        if not repair_on:
            from config.settings import Settings
            monkeypatch.setattr(Settings, "SUMMARY_L1_REPAIR_ENABLED",
                                False, raising=False)
        return await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                                correlation_id=CORR)

    @pytest.mark.asyncio
    async def test_s6_small_unknown_removed_single_call(self, monkeypatch):
        """S6: небольшой мусор → deterministic remove → карта жива,
        пайплайн продолжается, retry НЕ тратится (ровно 1 вызов)."""
        rows = _rows(4)
        llm = ScriptedLLM([_map_json([[101, 102, 999]], unassigned=[103])])
        result = await self._run(llm, rows, monkeypatch)
        assert result.usable and result.status == "ok"
        assert result.payload["topics"][0]["message_ids"] == [101, 102]
        assert "999" not in json.dumps(result.payload)
        assert len(llm.calls) == 1
        # Телеметрия §3.4 — в map_stats (→ SUMMARY_L1_STAGE).
        stats = result.map_stats or {}
        assert stats["unknown_refs_count"] == 1
        assert stats["removed_unknown_refs"] == 1
        assert stats["map_useful_after_repair"] is True
        assert stats["retry_used"] is False
        assert stats["anchor_mode"] is False          # map-v1 путь (без окна)
        assert stats["source_window_present"] is False

    @pytest.mark.asyncio
    async def test_s7_useless_exactly_one_retry_fail_closed(self, monkeypatch):
        """S7: карта бесполезна после ремонта → ровно ОДИН correction retry
        (второй ответ снова useless) → fail-closed."""
        rows = _rows(4)
        llm = ScriptedLLM([_map_json([[999, 888]]),      # mass unknown
                           _map_json([[777, 666]])])     # retry тоже
        result = await self._run(llm, rows, monkeypatch)
        assert not result.usable
        assert result.status == "invalid"
        assert result.invalid_reason == REASON_L1_USELESS_AFTER_REPAIR
        assert len(llm.calls) == 2                     # ровно одна коррекция
        correction = llm.calls[1][-1]["content"]
        assert REASON_L1_USELESS_AFTER_REPAIR in correction
        assert "Не выдумывай идентификаторы" in correction
        stats = result.map_stats or {}
        assert stats["map_useful_after_repair"] is False
        assert stats["retry_used"] is True

    @pytest.mark.asyncio
    async def test_s7_retry_saves_map(self, monkeypatch):
        """S7: retry после useless возвращает валидную карту → продолжаем."""
        rows = _rows(4)
        llm = ScriptedLLM([_map_json([[999, 888]]),
                           _map_json([[101, 102, 103, 104]], unassigned=[])])
        result = await self._run(llm, rows, monkeypatch)
        assert result.usable and result.status == "ok"
        assert result.payload["topics"][0]["message_ids"] == [
            101, 102, 103, 104]
        assert len(llm.calls) == 2
        stats = result.map_stats or {}
        assert stats["retry_used"] is True

    @pytest.mark.asyncio
    async def test_repair_kill_switch_off_fail_closed(self, monkeypatch):
        """Kill-switch repair OFF → прежняя строгость: unknown_message_id
        (fail-closed), retry по неизвестному id — как раньше."""
        rows = _rows(4)
        llm = ScriptedLLM([_map_json([[101, 999]]),
                           _map_json([[101, 999]])])
        result = await self._run(llm, rows, monkeypatch, repair_on=False)
        assert not result.usable
        assert result.invalid_reason == REASON_UNKNOWN_MESSAGE_ID
        assert len(llm.calls) == 2


# ── S5: паритет prod/test ExecutionInput ────────────────────────────────────

class TestExecutionInputParity:
    async def _build_prod(self, rows, run_id=CORR):
        window = build_source_window(run_id, CHAT_ID, rows)
        return await build_summary_execution_input(
            chat_id=CHAT_ID, rows=rows, correlation_id=run_id,
            source_window=window)

    async def _build_test(self, rows, run_id=CORR):
        return await build_summary_execution_input(
            chat_id=CHAT_ID, rows=rows, correlation_id=run_id,
            mount_window=True)

    @pytest.mark.asyncio
    async def test_s5_same_fixture_same_fingerprint_and_anchor_mode(
            self, monkeypatch):
        """S5 (ТЗ §19): один fixture → одинаковые source-window fingerprint
        и anchor_mode в prod- и test-путях."""
        _patch_capacity(monkeypatch)
        rows = _rows(5)
        prod = await self._build_prod(rows)
        test = await self._build_test(rows)
        assert prod.fingerprint != ""
        assert prod.fingerprint == test.fingerprint
        # anchor_mode совпадает и оба не пусты (anchors включены).
        assert (prod.anchor_map is not None) == (test.anchor_map is not None)
        assert prod.anchor_map is not None
        assert prod.anchor_map.run_fingerprint == test.anchor_map.run_fingerprint
        # Окно байт-идентично (тот же канонический материал).
        assert prod.source_window.messages_json == \
            test.source_window.messages_json
        assert prod.rows == test.rows
        # Остальные подготовленные поля — те же резолверы, тот же env.
        assert prod.focus_block == test.focus_block
        assert prod.budget_l2 == test.budget_l2
        assert prod.budget_l1 == test.budget_l1
        assert prod.length == test.length

    @pytest.mark.asyncio
    async def test_mount_window_zero_durable_writes(self, monkeypatch):
        """Dry-run: окно in-memory, 0 durable-записей (хранит только prod)."""
        calls = []

        async def _spy_store(db, window):
            calls.append(window)
            return True

        monkeypatch.setattr(
            __import__("services.summary_source_window",
                       fromlist=["store_source_window"]),
            "store_source_window", _spy_store)
        rows = _rows(3)
        test = await self._build_test(rows)
        prod = await self._build_prod(rows)
        assert calls == []          # builder никогда не пишет durable-окно
        assert test.source_window is not None
        assert prod.source_window is not None

    @pytest.mark.asyncio
    async def test_builder_fail_open_on_slot_errors(self, monkeypatch):
        """Никогда не бросает: сбой резолва слота → поле None."""
        import services.summary_l1_clusterizer as sl1_mod
        import services.summary_l2_writer as l2w

        def _boom(**kwargs):
            raise RuntimeError("slot down")

        monkeypatch.setattr(sl1_mod, "resolve_l1_slot", _boom)
        monkeypatch.setattr(l2w, "resolve_l2_slot_safe", _boom)
        inp = await build_summary_execution_input(
            chat_id=CHAT_ID, rows=_rows(3), correlation_id=CORR,
            mount_window=True)
        assert inp.slot_l1 is None
        assert inp.slot_l2 is None
        assert inp.source_window is not None

    @pytest.mark.asyncio
    async def test_window_run_id_override_used_for_fingerprint(
            self, monkeypatch):
        rows = _rows(3)
        inp = await build_summary_execution_input(
            chat_id=CHAT_ID, rows=rows, correlation_id=CORR,
            window_run_id="replay-run", mount_window=True)
        assert inp.source_window.run_id == "replay-run"
        window = build_source_window("replay-run", CHAT_ID, rows)
        assert inp.fingerprint == window_fingerprint(
            "replay-run", window.messages_json)


# ── Dry-run (audit-сценарий): окно + anchors, карта строится ────────────────

class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    async def get_smart_window(self, chat_id, since_ts, limit):
        return list(self._rows)


class _FakeMemory:
    def __init__(self, rows):
        self.db = _FakeDb(rows)
        self.writes = 0


def _v2_map_json(anchors_used):
    return json.dumps({
        "schema_version": 2,
        "topics": [{"topic_id": "topic_001", "title": "тема",
                    "source_anchors": list(anchors_used),
                    "participants": ["Автор0"], "short_hint": "суть"}],
        "events": [],
    }, ensure_ascii=False)


L2_JSON = json.dumps({
    "schema_version": 1,
    "title": "Тестовая статья",
    "paragraphs": [
        {"text": "Первый абзац статьи.", "emphasis": "Первый"},
    ],
})


class TestDryRunParity:
    @pytest.fixture(autouse=True)
    def _patch_chat_limit(self, monkeypatch):
        from services import summary_generator as sg
        from services import web_runtime

        async def _limit(chat_id, key, default=None):
            return default

        monkeypatch.setattr(sg, "_chat_limit", _limit)
        web_runtime.reset_web_runtime()
        yield
        web_runtime.reset_web_runtime()

    def _generator(self, rows, llm):
        from services.summary_generator import SummaryGenerator
        return SummaryGenerator(memory=_FakeMemory(rows), xml=MagicMock(),
                                llm=llm, bot=None,
                                concurrency_pool=MagicMock())

    @pytest.mark.asyncio
    async def test_dry_run_builds_window_and_anchors(self, monkeypatch):
        """Audit-сценарий (anchor-путь): dry-run строит окно + anchor_map,
        карта v2 строится, статус ok; 0 durable-записей окна."""
        _patch_capacity(monkeypatch)
        rows = _rows(6)
        from services.summary_source_anchors import build_anchor_map
        from services.summary_source_window import build_source_window
        window = build_source_window(CORR, CHAT_ID, rows)
        anchors = [e.anchor for e in build_anchor_map(window).entries]

        llm = ScriptedLLM([_v2_map_json(anchors), L2_JSON])
        gen = self._generator(rows, llm)
        # Durable-guard: сухой прогон не пишет окно.
        import services.summary_source_window as ssw

        async def _no_store(db, win):
            raise AssertionError("dry-run не пишет durable-окно")

        monkeypatch.setattr(ssw, "store_source_window", _no_store)
        from services.summary_test_run import STATUS_OK, run_summary_test
        result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                        correlation_id=CORR, pg=None)
        assert result.status == STATUS_OK, json.dumps(
            result.diagnostics, ensure_ascii=False)
        stage_l1 = result.stages["l1"]
        assert stage_l1["source_window_present"] is True
        assert stage_l1["anchor_mode"] is True
        assert stage_l1["window_fingerprint"] != ""
        assert len(llm.calls) == 2              # L1 + L2, без ретраев
        assert result.artifacts["clusters"], "карта должна строиться"

    @pytest.mark.asyncio
    async def test_dry_run_map_v1_unknown_ref_repaired(self, monkeypatch):
        """Audit-симптом §3.1: раньше dry-run без окна падал
        TEST_L1_INVALID · unknown_message_id (map-v1 fail-closed).
        Теперь окно есть; при v1-карте (anchors OFF) небольшой мусор
        удаляется детерминированно и карта строится."""
        _patch_capacity(monkeypatch)
        from config.settings import Settings
        monkeypatch.setattr(Settings, "SUMMARY_SOURCE_ANCHORS_ENABLED",
                            False, raising=False)
        rows = _rows(6)
        llm = ScriptedLLM([_map_json([[101, 102, 103, 999, 888]],
                                     unassigned=[]),
                           L2_JSON])
        gen = self._generator(rows, llm)
        from services.summary_test_run import STATUS_OK, run_summary_test
        result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                        correlation_id=CORR, pg=None)
        assert result.status == STATUS_OK, json.dumps(
            result.diagnostics, ensure_ascii=False)
        stage_l1 = result.stages["l1"]
        assert stage_l1["source_window_present"] is True
        assert stage_l1["anchor_mode"] is False   # anchors OFF → v1-карта
        assert len(llm.calls) == 2                # без correction-ретрая
        assert result.artifacts["clusters"]
        serialized = json.dumps(result.artifacts["clusters"])
        assert "999" not in serialized and "888" not in serialized
