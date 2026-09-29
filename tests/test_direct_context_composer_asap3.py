"""ASAP-3 (round 1028) — тесты Direct Context Composer (T-4009…T-4017).

Приёмочные единицы спеки §3.3–§3.9 / ADR-1028-2 D3–D7:
  * приоритет-модель P0–P3 и eviction P3→P2→P1 (P0 обычным budgeter'ом не
    удаляется; §8/§16);
  * «всё влезает — не режем» (§16);
  * physical overflow — явная деградация (§17), без text[:N];
  * границы old-verbatim-эпизода — детерминизм/идемпотентность (D4, §10–§11);
  * middle top-K selection (D5, §3.7);
  * модель-aware capacity: safety-множитель РОВНО ОДИН раз (D2, §4);
  * паритет OFF (байт-в-байт прежний путь) и структура ON (D3, §47);
  * observability-хелперы R17 (D15).

Маркер ``asap3`` — прод-дефолты флагов (см. tests/conftest.py).
"""
import re
from unittest.mock import MagicMock, patch

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services.model_capacity import (
    apply_budget_policy, compute_available_budget, output_reserve_tokens,
    resolve_model_context_window,
)

pytestmark = pytest.mark.asap3


def _piece(kind, text, priority=None, keep=None, floor=0, position=None):
    return comp.ContextPiece(
        key=kind, kind=kind, text=text,
        priority=comp.BLOCK_PRIORITY.get(kind, comp.P2) if priority is None
        else priority,
        keep=keep or comp.PIECE_KEEP.get(kind, "span"),
        floor_tokens=floor,
        evictable=(comp.BLOCK_PRIORITY.get(kind, comp.P2) != comp.P0),
        position=comp.CANONICAL_ORDER.get(kind, 99) if position is None
        else position)


def _row(tg, ts, text="текст", reply_to=None, user_id=10):
    return {"tg_message_id": tg, "timestamp": ts, "text": text,
            "reply_to_id": reply_to, "user_id": user_id, "id": tg}


class TestBlockPriority:
    def test_p0_kinds(self):
        for kind in ("current", "target", "relations", "protected", "lore",
                     "branch", "episode", "sandwich"):
            assert comp.BLOCK_PRIORITY[kind] == comp.P0, kind

    def test_p1_tail_and_thread(self):
        assert comp.BLOCK_PRIORITY["global_tail"] == comp.P1
        assert comp.BLOCK_PRIORITY["thread"] == comp.P1

    def test_p2_summary_background(self):
        for kind in ("global_head", "rag", "map", "nostalgia", "mood"):
            assert comp.BLOCK_PRIORITY[kind] == comp.P2, kind

    def test_p3_middle_and_anchors(self):
        assert comp.BLOCK_PRIORITY["global_middle"] == comp.P3
        assert comp.BLOCK_PRIORITY["anchors"] == comp.P3

    def test_p2_cannot_evict_p1(self):
        # §3.4/§12: P2 (summary) не вытесняет P1 (tail) — eviction строго
        # по убыванию номера класса: сначала P3, затем P2; P1 трогается
        # последней; P0 — никогда.
        assert comp.P3 > comp.P2 > comp.P1 > comp.P0


class TestAllocateBudget:
    def test_no_pressure_no_cuts(self):
        # §16: «всё помещается — не резать из-за ratio».
        pieces = [_piece("anchors", "стиль " * 10),
                  _piece("rag", "факт " * 10),
                  _piece("global_tail", "хвост " * 10)]
        result = comp.allocate_budget(pieces, 100000)
        assert not result.excluded
        assert not result.physical_overflow
        assert all(p.text for p in result.pieces)

    def test_eviction_p3_first_then_p2(self):
        # Давление: сначала жертвуется P3 (anchors), затем P2 (rag);
        # P1 (tail) остаётся, P0 не трогается вовсе.
        pieces = [
            _piece("anchors", "якорь " * 200),           # P3
            _piece("rag", "факт " * 200),                # P2
            _piece("global_tail", "хвост " * 200),       # P1
            _piece("target", "Вася"),                    # P0
            _piece("current", "вопрос?"),                # P0
        ]
        small = len("якорь " * 200) // 6                  # жёсткое давление
        result = comp.allocate_budget(pieces, small)
        assert result.excluded, "ожидается давление и вытеснение"
        kinds_dropped = {e["kind"] for e in result.excluded}
        assert "anchors" in kinds_dropped, "P3 эвиктируется первым"
        assert "target" not in kinds_dropped and "current" not in kinds_dropped
        assert all(p.text for p in result.pieces if p.kind in ("target",
                                                               "current"))

    def test_tail_floor_real_wiring_enforced(self):
        # H2/D6 (rework): floor tail'а wired РЕАЛЬНЫМ кодом прод-пути
        # (`composer.tail_floor_tokens` — тот же вызов, что в
        # `_compose_user_content`), никакой самоподстановки floor'а.
        # Давление МЕЖДУ floor и full: P2/P3 снимаются, tail режется до
        # минимума (keep-end), но НЕ ниже 20 строк; тихой резки нет.
        tail_text = "\n".join(
            f"хвост-строка-{i} с достаточным наполнением текста"
            for i in range(30))
        floor = comp.tail_floor_tokens(tail_text,
                                       comp.fresh_tail_min_messages())
        assert floor > 0
        pieces = [_piece("rag", "факт " * 500),
                  _piece("anchors", "стиль " * 500),
                  _piece("global_tail", tail_text, floor=floor),
                  _piece("target", "Вася")]
        budget = floor + comp.count_tokens("Вася") + 10
        result = comp.allocate_budget(pieces, budget)
        tail_piece = next(p for p in result.pieces if p.kind == "global_tail")
        kept = [ln for ln in tail_piece.text.split("\n") if ln.strip()]
        assert len(kept) >= comp.fresh_tail_min_messages(), \
            "tail не режется ниже минимума, пока floor достижим"
        assert kept[-1] == tail_text.split("\n")[-1], "keep-end (свежие снизу)"

    def test_below_floor_is_physical_overflow_not_silent_cut(self):
        # H2/D6: давление НИЖЕ floor → путь §17 (physical_overflow), tail
        # НЕ режется ниже минимума молча.
        tail_text = "\n".join(
            f"хвост-строка-{i} с достаточным наполнением текста"
            for i in range(30))
        floor = comp.tail_floor_tokens(tail_text,
                                       comp.fresh_tail_min_messages())
        pieces = [_piece("rag", "факт " * 500),
                  _piece("anchors", "стиль " * 500),
                  _piece("global_tail", tail_text, floor=floor),
                  _piece("target", "Вася " * 50)]
        result = comp.allocate_budget(pieces, 30)
        assert result.physical_overflow, \
            "below-minimum возможен только через §17 с событием"
        tail_piece = next(p for p in result.pieces if p.kind == "global_tail")
        kept = [ln for ln in tail_piece.text.split("\n") if ln.strip()]
        assert len(kept) >= comp.fresh_tail_min_messages(), \
            "тихой резки ниже floor нет"
        assert "global_tail" in result.preserved_kinds

    def test_compression_without_drop_counts_as_pressure(self):
        # M-ASAP3-1: полурезка (compression) без полного дропа →
        # compressed_or_dropped > 0 при пустом excluded. Текст многострочный
        # (как реальные блоки — построчное усечение применимо).
        rag_text = "\n".join("факт с наполнением номера" for _ in range(300))
        pieces = [_piece("rag", rag_text),
                  _piece("target", "Вася"),
                  _piece("current", "вопрос?")]
        full = comp.count_tokens(rag_text) + 20
        budget = full // 2          # давление: rag режется, но не в ноль
        result = comp.allocate_budget(pieces, budget)
        assert result.compressed_or_dropped >= 1, \
            "полурезка обязана считаться pressure-сигналом"
        rag_piece = next(p for p in result.pieces if p.kind == "rag")
        assert rag_piece.text, "piece сжат, но не выброшен"
        assert all(e["kind"] != "rag" for e in result.excluded)

    def test_p0_never_evicted_by_budgeter(self):
        # §8: P0 нельзя обычным budgeter'ом молча удалить.
        pieces = [_piece("current", "текущий вопрос про метель?"),
                  _piece("target", "Вася [10]"),
                  _piece("anchors", "мусор " * 100)]
        result = comp.allocate_budget(pieces, 5)
        assert next(p for p in result.pieces if p.kind == "current").text
        assert next(p for p in result.pieces if p.kind == "target").text

    def test_physical_overflow_flag(self):
        # §17: P0 + floors не влезают → явный флаг, ядро сохранено.
        pieces = [_piece("current", "вопрос " * 300),
                  _piece("target", "Вася " * 100),
                  _piece("anchors", "x")]
        result = comp.allocate_budget(pieces, 50)
        assert result.physical_overflow
        assert result.needed > result.available
        assert "current" in result.preserved_kinds
        assert "target" in result.preserved_kinds


class TestEpisodeSpan:
    def test_gap_expansion_300s(self):
        rows = [_row(1, 1000), _row(2, 1100), _row(3, 1250),
                _row(4, 5000), _row(5, 5100)]
        span = comp.compute_episode_span(rows, 3, gap_seconds=300,
                                         max_messages=40)
        assert span is not None
        start, end, reason = span
        assert (start, end) == (0, 2)
        assert "gap" in reason

    def test_hole_splits_segment_keeps_hit(self):
        rows = [_row(1, 1000), _row(2, 5000), _row(3, 5100), _row(4, 5200)]
        span = comp.compute_episode_span(rows, 4, gap_seconds=300,
                                         max_messages=40)
        start, end, _ = span
        tgs = [_row_tg(rows[i]) for i in range(start, end + 1)]
        assert 4 in tgs and 1 not in tgs          # дырка 1000→5000 режет

    def test_reply_graph_closure(self):
        # предок вне gap-окна подтягивается reply-связью (≤6, cycle-safe).
        rows = [_row(1, 1000, reply_to=None),
                _row(2, 5200, reply_to=1),
                _row(3, 5300, reply_to=2)]
        span = comp.compute_episode_span(rows, 3, gap_seconds=60,
                                         max_messages=40)
        start, end, reason = span
        tgs = {_row_tg(rows[i]) for i in range(start, end + 1)}
        assert tgs == {1, 2, 3}
        assert "reply_links" in reason

    def test_cap_40_messages(self):
        rows = [_row(i, 1000 + i) for i in range(1, 101)]
        span = comp.compute_episode_span(rows, 50, gap_seconds=10000,
                                         max_messages=40)
        start, end, reason = span
        assert end - start + 1 <= 40
        assert "cap_applied" in reason
        tgs = [_row_tg(rows[i]) for i in range(start, end + 1)]
        assert 50 in tgs                          # хит остаётся в капе

    def test_idempotent(self):
        rows = [_row(1, 1000), _row(2, 1100, reply_to=1), _row(3, 1300)]
        first = comp.compute_episode_span(rows, 2, gap_seconds=300,
                                          max_messages=40)
        second = comp.compute_episode_span(rows, 2, gap_seconds=300,
                                           max_messages=40)
        assert first == second

    def test_anchor_missing_none(self):
        rows = [_row(1, 1000)]
        assert comp.compute_episode_span(rows, 99) is None


def _row_tg(row):
    return int(row["tg_message_id"])


class TestSelectMiddle:
    def test_deterministic_and_bounded(self):
        rows = [_row(i, 1000 + i * 10, text=f"сообщение {i}")
                for i in range(1, 21)]
        out1 = comp.select_middle(rows, query="сообщение",
                                  chain_tg_ids=set(),
                                  participant_ids=set(), top_k=5)
        out2 = comp.select_middle(rows, query="сообщение",
                                  chain_tg_ids=set(),
                                  participant_ids=set(), top_k=5)
        assert out1 == out2
        assert len(out1) == 5

    def test_chain_membership_boost(self):
        rows = [_row(1, 1000, text="обычный фон"),
                _row(2, 1100, text="строка цепочки"),
                _row(3, 1200, text="ещё фон")]
        out = comp.select_middle(rows, query="", chain_tg_ids={2},
                                 participant_ids=set(), top_k=1)
        assert len(out) == 1
        assert _row_tg(out[0]) == 2

    def test_asc_order(self):
        rows = [_row(i, 1000 + i, text=f"текст {i}") for i in range(1, 11)]
        out = comp.select_middle(rows, query="текст", chain_tg_ids=set(),
                                 participant_ids=set(), top_k=4)
        tgs = [_row_tg(r) for r in out]
        assert tgs == sorted(tgs)


class TestModelCapacityIntegration:
    def test_single_multiplier_window_growth(self):
        small = compute_available_budget(32768, 1000, 0.10)[0]
        large = compute_available_budget(131072, 1000, 0.10)[0]
        assert large > small
        # РОВНО ОДИН множитель: (window − external − reserve)/1.15.
        available, reserve = compute_available_budget(115000, 0, 0.0)
        assert available == int((115000 - 1024) / 1.15)

    def test_output_reserve_floor(self):
        assert output_reserve_tokens(100000, 0.10) == 10000
        assert output_reserve_tokens(2000, 0.10) == 1024

    def test_policy_semantics(self):
        assert apply_budget_policy(25000, -1) == (25000, "unlimited")
        assert apply_budget_policy(25000, 0) == (16000, "dynamic")
        assert apply_budget_policy(25000, None) == (16000, "dynamic")
        assert apply_budget_policy(25000, 8000) == (8000, "cap")
        assert apply_budget_policy(5000, 8000) == (5000, "cap")

    def test_unknown_model_fallback_source(self):
        window, source = resolve_model_context_window("no-such-model-asap3")
        assert source == comp.WINDOW_SOURCE_FALLBACK
        assert window == 16384


class TestComposerFlag:
    def test_kill_switch_default_on_and_per_call(self):
        assert comp.composer_on() is True

    def test_metrics_counters_and_log_line(self, caplog):
        comp.reset_direct_metrics()
        with caplog.at_level("INFO"):
            comp.record_direct_metric("direct_force_reply_total")
            comp.record_direct_metric("direct_force_reply_total")
        snapshot = comp.direct_metrics_snapshot()
        assert snapshot["direct_force_reply_total"] == 2
        lines = [r.getMessage() for r in caplog.records
                 if "direct_metric" in r.getMessage()]
        assert lines and "name=direct_force_reply_total" in lines[-1]
        assert "count=2" in lines[-1]
        comp.reset_direct_metrics()

    def test_diagnostics_roundtrip(self):
        comp.reset_diagnostics()
        comp.record_diagnostics(-100500, {"window": 131072,
                                          "policy_mode": "unlimited"})
        data = comp.get_diagnostics(-100500)
        assert data and data["window"] == 131072
        comp.reset_diagnostics()
        assert comp.get_diagnostics(-100500) is None


class TestObservabilityR17:
    def test_emit_direct_trigger_filters_raw_text(self, caplog):
        from services.agentic_events import (
            DIRECT_TRIGGER, emit_agentic_event,
        )
        with caplog.at_level("INFO"):
            emit_agentic_event(
                DIRECT_TRIGGER, chat_id=-1, message_id=1,
                trigger_type="force_keyword", force_reply_required=True,
                reply_to_bot=False, is_private=False, addressed=True,
                raw_text="секретный текст пользователя")
        logged = "\n".join(r.getMessage() for r in caplog.records
                           if "DIRECT_TRIGGER" in r.getMessage())
        assert "trigger_type=force_keyword" in logged
        assert "секретный текст" not in logged
        assert "raw_text" not in logged

    def test_context_events_r17_safe(self, caplog):
        with caplog.at_level("INFO"):
            comp.emit_context_capacity(
                model="deepseek-chat", window=131072,
                window_source="model_map", external_tokens=2000,
                output_reserve=13107, available_context=100000,
                budget=100000, policy_mode="unlimited",
                summary_revision="123:45", summary_watermark=1700000000,
                summary_lag_messages=42, summary_age=300)
            comp.emit_context_select(
                chat_id=-1, message_id=2, recent_verbatim_messages=20,
                recent_verbatim_tokens=4000, reply_thread_messages=3,
                old_episode_count=1, old_episode_messages=25,
                old_episode_tokens=3000, middle_selected_messages=10,
                compressed_background_tokens=1500, rag_tokens=800)
            comp.emit_context_pressure(
                chat_id=-1, excluded_low_priority=3, compressed_or_dropped=1,
                physical_overflow=False)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "policy_mode=unlimited" in text
        assert "old_episode_count=1" in text
        assert "physical_overflow=False" in text

    def test_physical_overflow_event(self, caplog):
        with caplog.at_level("INFO"):
            comp.emit_context_physical_overflow(
                chat_id=-1, preserved_kinds=["current", "target"],
                available=1000, needed=5000)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "CONTEXT_PHYSICAL_OVERFLOW" in text
        assert "preserved_kinds=current,target" in text


class TestComposerFlagParity:
    """T-4017: parity-комбинации трёх независимых master-флагов (D-PM-1)."""

    def test_combinations_matrix(self, monkeypatch):
        # (координатор, decision, composer) — все 8 комбинаций валидны:
        # каждый master резолвится per-call и не влияет на другие.
        # Целимся в классы module-привязанных instances (reload-safe).
        combos = [(c, d, m) for c in (True, False)
                  for d in (True, False) for m in (True, False)]
        dcs_cls = type(dcs.settings)
        comp_cls = type(comp.settings)
        for coord, dec, comp_flag in combos:
            monkeypatch.setattr(dcs_cls, "DIRECT_COORDINATOR_ENABLED", coord)
            monkeypatch.setattr(dcs_cls, "DIRECT_DECISION_MAKING_ENABLED",
                                dec)
            monkeypatch.setattr(comp_cls, "DIRECT_CONTEXT_COMPOSER_ENABLED",
                                comp_flag)
            assert dcs.coordinator_enabled() is coord
            assert dcs.decision_making_enabled() is dec
            assert comp.composer_on() is comp_flag

    @pytest.mark.asyncio
    async def test_composer_off_uses_legacy_budget_path(self, monkeypatch):
        # OFF → прежний `_apply_context_budget` (self-truncation билдеров);
        # композер не запускается (байт-в-байт parity, §3.3 спеки).
        monkeypatch.setattr(type(comp.settings),
                            "DIRECT_CONTEXT_COMPOSER_ENABLED", False)
        monkeypatch.setattr(type(dcs.settings),
                            "DIRECT_CONTEXT_COMPOSER_ENABLED", False)
        svc = _make_composer_service()
        msg = _message("бот, привет", message_id=1004)
        with patch.object(svc, "_apply_context_budget",
                          wraps=svc._apply_context_budget) as legacy, \
                patch.object(svc, "_compose_user_content",
                             side_effect=AssertionError(
                                 "композер недостижим при OFF")):
            blocks = await svc._build_user_content(
                msg.chat.id, msg, "Вася", target_user_id=10)
        legacy.assert_called_once()
        assert blocks  # прежний путь вернул блоки

    @pytest.mark.asyncio
    async def test_composer_on_skips_legacy_budget(self):
        svc = _make_composer_service()
        msg = _message("бот, привет", message_id=1005)
        with patch.object(svc, "_apply_context_budget",
                          side_effect=AssertionError(
                              "legacy budget недостижим при ON")):
            blocks = await svc._build_user_content(
                msg.chat.id, msg, "Вася", target_user_id=10)
        assert blocks


def _make_composer_service():
    from services.summary_aliases import AliasResolver
    from tests.test_direct_chat import FakeDB, FakeLLM, FakeMemory
    return dcs.DirectChatService(
        FakeMemory(), FakeDB(), FakeLLM(text="ответ"),
        AliasResolver("{}"), bot_id=12345, bot_username="test_bot",
        breaker=None, cache=None, tool_router=None)


def _message(text, message_id=100):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = -1001234567890
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = 10
    m.from_user.username = "vasya"
    m.reply_to_message = None
    m.entities = None
    return m


class TestComposerOnPath:
    """Интеграция ON-пути: структура блоков и порядок сохраняются (D3)."""

    @pytest.mark.asyncio
    async def test_service_composer_materializes_canonical_order(self):
        # Композер ON: порядок блоков payload — канонический («важное к
        # концу»); <Global_Context> присутствует; порядок блоков НЕ меняется.
        from tests.test_direct_chat import (
            FakeLLM, _make_service, _message, _bot, _window_row,
        )
        svc = _make_service(llm=FakeLLM(text="ответ"))
        msg = _message(text="бот, привет", message_id=1001)
        blocks = [("map", "<UserResolutionMap>\nкарта\n</UserResolutionMap>"),
                  ("rag", "<RAG_Memory>\nфакт\n</RAG_Memory>"),
                  ("target", "<Target_User>Вася [10]</Target_User>"),
                  ("current", "<Current_Question>\nпривет\n"
                              "</Current_Question>"),
                  ("sandwich", "отвечай коротко")]
        global_parts = {
            "head_lines": ["фон: конспект из 5 сообщений"],
            "middle_rows": [], "tail_rows": [],
            "tail_lines": ["[100 | Вася [10] | tg:5]: старое сообщение"],
            "window_end_ts": 100, "raw_count": 5, "has_summary": True,
        }
        texts = await svc._compose_user_content(
            chat_id=msg.chat.id, message=msg, blocks=blocks, chain=[],
            window=[], roster=[], suffix_map={}, global_parts=global_parts,
            target_name="Вася", target_user_id=10, trigger_message_id=1001,
            out_excluded=[])
        order = [re.match(r"<([A-Za-z_]+)>", t).group(1) if t.startswith("<")
                 else "sandwich" for t in texts]
        # map → rag → global → target → current → sandwich (канон, D3).
        assert order == ["UserResolutionMap", "RAG_Memory", "Global_Context",
                         "Target_User", "Current_Question", "sandwich"]
        global_block = texts[2]
        assert global_block.startswith("<Global_Context>")
        assert "конспект из 5 сообщений" in global_block
        assert "старое сообщение" in global_block

    @pytest.mark.asyncio
    async def test_service_composer_episode_block_position(self):
        from unittest.mock import patch
        from tests.test_direct_chat import (
            FakeLLM, _make_service, _message,
        )
        svc = _make_service(llm=FakeLLM(text="ответ"))
        msg = _message(text="бот, привет", message_id=1002)
        blocks = [("branch",
                   "<Conversation_Branch>\n[100 | A]: корень\n"
                   "</Conversation_Branch>"),
                  ("target", "<Target_User>A</Target_User>")]
        global_parts = {"head_lines": [], "middle_rows": [], "tail_rows": [],
                        "tail_lines": [], "window_end_ts": None,
                        "raw_count": 0, "has_summary": False}
        episode = ("<Old_Episode>\n[500 | A | tg:500]: старый диалог\n"
                   "</Old_Episode>")
        stats = {"count": 1, "messages": 1, "tokens": 10, "hits": 1}
        with patch.object(svc, "_build_old_episodes",
                          return_value=(episode, stats)):
            texts = await svc._compose_user_content(
                chat_id=msg.chat.id, message=msg, blocks=blocks, chain=[],
                window=[], roster=[], suffix_map={}, global_parts=global_parts,
                target_name="A", target_user_id=None,
                trigger_message_id=1002, out_excluded=[])
        order = [re.match(r"<([A-Za-z_]+)>", t).group(1) if t.startswith("<")
                 else "sandwich" for t in texts]
        # episode (P0) — сразу после branch, до target (канонический слот 2).
        assert order == ["Conversation_Branch", "Old_Episode", "Target_User"]

    @pytest.mark.asyncio
    async def test_service_composer_no_hits_no_episode_block(self):
        from tests.test_direct_chat import (
            FakeLLM, _make_service, _message,
        )
        svc = _make_service(llm=FakeLLM(text="ответ"))
        msg = _message(text="бот, привет", message_id=1003)
        blocks = [("target", "<Target_User>A</Target_User>")]
        global_parts = {"head_lines": [], "middle_rows": [], "tail_rows": [],
                        "tail_lines": [], "window_end_ts": None,
                        "raw_count": 0, "has_summary": False}
        texts = await svc._compose_user_content(
            chat_id=msg.chat.id, message=msg, blocks=blocks, chain=[],
            window=[], roster=[], suffix_map={}, global_parts=global_parts,
            target_name="A", target_user_id=None, trigger_message_id=1003,
            out_excluded=[])
        assert not any(t.startswith("<Old_Episode>") for t in texts)
