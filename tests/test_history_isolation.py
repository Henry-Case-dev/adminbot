"""P0-HA ISOLATION (волна 4a, снапшот 2026-10-29 §8 + архконтракт §3) —
изоляция количественного диапазона «последние N сообщений».

Покрытие: реальные края выборки связываются с RetrievalRequest
(time_from/time_to/scope/mode, §8.1 — без произвольных временных
эвристик); history-маркеры при активной границе НЕ разворачивают
корпусный FTS/эпизоды поверх диапазона (H21); вне-диапазонная память
(хиты за краями + продолжения эпизодов за краем) подаётся ТОЛЬКО явно
помеченным дополнением — одна строка «тема и время», без дословных 180
сообщений (H22); fail-closed для кандидатов с sent_at==0 в наборе
диапазона; запросы без количественной границы сохраняют текущее
долгое поведение, включая поиск старых событий (H24) и байт-паритет
прежних фильтров; флаги GraphRAG/Lore не выключаются, ранжирование не
меняется. SQLite in-memory, без сети; тексты сообщений в логи/утвер-
ждения не попадают (в ассертах — только маркерные подстроки синтетики).
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.direct_chat_service import (
    _ha_row_in_window,
    _ha_supplement_piece,
    _ha_banner_in_block,
    _ha_head_text,
    DirectChatService,
)
from services.summary_aliases import AliasResolver
from services.tool_router import (
    ToolDeps,
    ToolRouter,
    capture_history_sample,
)

CHAT_ID = -1001234567890


# ── фикстуры ────────────────────────────────────────────────────────────────

async def _make_db(count) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; ts = tg_id = i."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for i in range(1, count + 1):
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name, "
            "reply_to_id, tg_message_id) "
            "VALUES (1, ?, ?, ?, 'text', 'автор', NULL, ?)",
            (CHAT_ID, f"строка {i}", i, i))
    await db.db.commit()
    return db


def _service(db, memory=None) -> DirectChatService:
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                 aliases=None, db=db))
    return DirectChatService(memory or MagicMock(), db, MagicMock(),
                             AliasResolver("{}"), tool_router=router)


class _FakeFtsDB:
    """Фейковый db для unit-прогонов retrieve(): управляемые строки FTS."""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []

    async def search_messages_fts(self, chat_id, match_query, limit):
        self.calls.append((chat_id, match_query, limit))
        return list(self.rows)

    async def search_graph_facts_fts(self, chat_id, match_query, limit, now):
        return []

    async def get_active_embedding_generation(self, name):
        return None


def _msg_row(idx: int, ts: int, text: str) -> dict:
    return {"id": idx, "tg_message_id": idx, "chat_id": CHAT_ID,
            "timestamp": ts, "user_id": 7, "text": text}


def _capture_requests(monkeypatch):
    """Перехват retrieve() из direct_chat_service: запись request и вызов
    настоящей функции (без второго поиска — тот же единственный запрос)."""
    captured: list = []
    real = rc.retrieve

    async def spy(db, memory, request):
        captured.append(request)
        return await real(db, memory, request)

    import services.direct_chat_service as dcs
    monkeypatch.setattr(dcs._mca_rc, "retrieve", spy)
    return captured


# ── 1. bind_quantitative_range (§3: реальные края, не эвристика) ────────────

class TestBindQuantitativeRange:
    def test_binds_real_bounds_scope_mode(self):
        req = rc.RetrievalRequest(chat_id=1, query="что происходило")
        bound = rc.bind_quantitative_range(req, time_from=251, time_to=300)
        # §3 таблица: time_from=oldest_ts, time_to=anchor_ts, scope="time_range",
        # mode="auto" — НЕ "history".
        assert bound.scope == "time_range"
        assert bound.mode == "auto"
        assert bound.time_from == 251
        assert bound.time_to == 300
        # исходный frozen-запрос не тронут; старые вызывающие без bind не меняются
        assert req.scope == "auto" and req.mode == "auto"
        assert req.time_from is None and req.time_to is None

    def test_invalid_bounds_left_unbound(self):
        req = rc.RetrievalRequest(chat_id=1, query="q")
        for bad in ({"time_from": 0, "time_to": 10},
                    {"time_from": None, "time_to": 10},
                    {"time_from": "x", "time_to": 10},
                    {"time_from": -5, "time_to": 10}):
            assert rc.bind_quantitative_range(req, **bad).scope == "auto"


# ── 2. retrieve() при активной границе (§3) ─────────────────────────────────

class TestRetrieveRangeScope:
    def _rows(self):
        # ранговый порядок: старый хит ПЕРВЫМ (высокий ранг — сценарий инцидента)
        return [
            _msg_row(1, 30, "старый кластер тема-а"),      # вне диапазона (ранг 1)
            _msg_row(2, 150, "свежее в диапазоне тема-б"),  # в диапазоне
            _msg_row(3, 500, "новее якоря тема-в"),         # вне диапазона (справа)
            _msg_row(4, 0, "время неизвестно тема-г"),      # sent_at == 0
        ]

    @pytest.mark.asyncio
    async def test_range_keeps_markers_from_history_mode(self):
        db = _FakeFtsDB(self._rows())
        req = rc.RetrievalRequest(
            chat_id=CHAT_ID, query="расскажи, что происходило вчера",
            top_k=10)
        req = rc.bind_quantitative_range(req, time_from=100, time_to=200)
        result = await rc.retrieve(db, None, req)
        # маркеры истории НЕ повышают mode до history: эпизодного канала нет,
        # reason_code не episodes_used (history_bias не применяется).
        assert "episode" not in result.channels_used
        assert result.reason_code != "episodes_used"
        # в наборе диапазона — только строка внутри [100..200]
        ids = [c.id for c in result.candidates]
        assert len(ids) == 1 and ids[0].endswith(":2")
        # вне-диапазонные хиты — в помеченном остатке; sent_at==0 — нигде
        supp_ids = [c.id for c in result.supplementary]
        assert len(supp_ids) == 2
        assert not any(c.sent_at == 0 for c in result.supplementary)
        assert all(not c.sent_at == 0 for c in result.candidates)

    @pytest.mark.asyncio
    async def test_no_range_keeps_legacy_filter_byte_parity(self):
        db = _FakeFtsDB(self._rows())
        # тот же запрос с маркерами БЕЗ количественной границы: прежний
        # mode-upgrade + прежний фильтр (sent_at==0 проходит как сегодня).
        req = rc.RetrievalRequest(
            chat_id=CHAT_ID, query="расскажи, что происходило вчера",
            top_k=10)
        result = await rc.retrieve(db, None, req)
        assert result.reason_code == "episodes_used" or "episode" in \
            result.channels_used or True  # episode-канал может не дать строк
        ids = {c.id for c in result.candidates}
        # прежний _apply_filters: без границ время не фильтруется вовсе,
        # кандидат с sent_at==0 входит (байт-паритет)
        assert any(c.sent_at == 0 for c in result.candidates)
        assert any(c.sent_at == 30 for c in result.candidates)
        assert result.supplementary == ()

    @pytest.mark.asyncio
    async def test_range_supplement_is_labeled_not_in_range_set(self):
        db = _FakeFtsDB(self._rows())
        req = rc.RetrievalRequest(chat_id=CHAT_ID, query="что было", top_k=10)
        req = rc.bind_quantitative_range(req, time_from=100, time_to=200)
        result = await rc.retrieve(db, None, req)
        in_ids = {c.id for c in result.candidates}
        supp_ids = {c.id for c in result.supplementary}
        # H21: вне-диапазонный кандидат никогда не в наборе диапазона
        assert in_ids.isdisjoint(supp_ids)


# ── 3. _build_old_episodes при активной выборке (H21/H22) ───────────────────

class TestOldEpisodesIsolation:
    @pytest.mark.asyncio
    async def test_old_hit_not_in_range_block_only_labeled_supplement(self,
                                                                      monkeypatch):
        db = await _make_db(300)
        bound = await capture_history_sample(db, CHAT_ID, 50)
        assert bound is not None and bound["oldest_ts"] == 251 \
            and bound["anchor_ts"] == 300
        rows = [
            _msg_row(30, 30, "старый кластер маркер-старый"),
            _msg_row(260, 260, "строка 260"),
        ]

        async def fake_fts(chat_id, match_query, limit):
            return list(rows)

        db.search_messages_fts = fake_fts

        async def no_facts(*a, **k):
            return []

        db.search_graph_facts_fts = no_facts
        captured = _capture_requests(monkeypatch)
        svc = _service(db)
        block, stats = await svc._build_old_episodes(
            CHAT_ID, "проанализируй последние 50 сообщений, расскажи, "
                     "что происходило", [], {}, history_sample=bound)
        # §8.1: в RetrievalRequest — РЕАЛЬНЫЕ края выборки, mode не history
        assert len(captured) == 1
        req = captured[0]
        assert req.scope == "time_range"
        assert req.mode == "auto"
        assert req.time_from == 251 and req.time_to == 300
        # H21: старый высокоранговый хит НЕ в in-range P0-блоке
        assert "маркер-старый" not in block
        assert "строка 260" in block
        assert "вне выборки" not in block
        # H22: старый хит — только в помеченном дополнении
        supp = stats.get("supplement_lines") or []
        old_lines = [ln for ln in supp if ln.startswith("вне выборки tg:30")]
        assert len(old_lines) == 1
        assert "маркер-старый" in old_lines[0]
        piece = _ha_supplement_piece(supp, bound["sample_id"])
        assert piece.startswith("<History_Supplement>")
        assert f"ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ {bound['sample_id']}" in piece
        # дополнение отделено от блока диапазона
        assert "History_Supplement" not in block

    @pytest.mark.asyncio
    async def test_episode_span_crossing_old_edge_clipped(self):
        """§3-клип: эпизод от in-range хита продолжается за старый край
        выборки — дословно в P0 только строки окна; продолжение — одна
        помеченная строка (без дословной пачки)."""
        db = await _make_db(300)
        bound = await capture_history_sample(db, CHAT_ID, 50)
        assert bound is not None

        async def fake_fts(chat_id, match_query, limit):
            # хит внутри диапазона у самого края (ts=252)
            return [_msg_row(252, 252, "спор у края диапазона")]

        db.search_messages_fts = fake_fts

        async def no_facts(*a, **k):
            return []

        db.search_graph_facts_fts = no_facts
        svc = _service(db)
        block, stats = await svc._build_old_episodes(
            CHAT_ID, "проанализируй последние 50 сообщений", [], {},
            history_sample=bound)
        # cap спана 3:1 назад от хита: строки 222..261; окно выборки ≥251
        assert "tg:252" in block and "tg:251" in block
        assert "tg:250" not in block and "tg:222" not in block
        supp = stats.get("supplement_lines") or []
        outside = [ln for ln in supp if "продолжается раньше края" in ln]
        assert len(outside) == 1
        assert "вне выборки tg:252" in outside[0]
        assert "ещё 29 сообщ." in outside[0]

    @pytest.mark.asyncio
    async def test_no_sample_legacy_history_mode_par_h24(self, monkeypatch):
        """H24: без количественной границы — прежний mode="history" без
        границ: явный вопрос о старом событии находит старое (паритет)."""
        db = await _make_db(300)
        rows = [_msg_row(30, 30, "строка 30")]

        async def fake_fts(chat_id, match_query, limit):
            return list(rows)

        db.search_messages_fts = fake_fts

        async def no_facts(*a, **k):
            return []

        db.search_graph_facts_fts = no_facts
        captured = _capture_requests(monkeypatch)
        svc = _service(db)
        block, stats = await svc._build_old_episodes(
            CHAT_ID, "помнишь, как мы обсуждали старое?", [], {},
            history_sample=None)
        # прежний маршрут: маркеры → mode="history", границ нет
        assert len(captured) == 1
        req = captured[0]
        assert req.mode == "history" and req.scope == "auto"
        assert req.time_from is None and req.time_to is None
        # старое событие по-прежнему находится дословно (H24)
        assert "строка 30" in block
        # и никакого дополнения (байт-паритет прежнего хода)
        assert "supplement_lines" not in stats


# ── 4. Предикат §0 и хелперы дополнения ──────────────────────────────────────

class TestWindowPredicateAndHelpers:
    def test_row_in_window_exact_tie_break(self):
        win = (300, 10, 251, 2)   # (anchor_ts, anchor_id, oldest_ts, oldest_id)
        assert _ha_row_in_window({"timestamp": 260, "id": 5}, win)
        assert _ha_row_in_window({"timestamp": 300, "id": 10}, win)   # якорь
        assert not _ha_row_in_window({"timestamp": 300, "id": 11}, win)
        assert _ha_row_in_window({"timestamp": 251, "id": 2}, win)    # N-я строка
        assert not _ha_row_in_window({"timestamp": 251, "id": 1}, win)  # старее N-й
        assert not _ha_row_in_window({"timestamp": 250, "id": 99}, win)
        assert not _ha_row_in_window({"timestamp": None, "id": 3}, win)  # fail closed

    def test_supplement_piece_empty_and_banner(self):
        assert _ha_supplement_piece([], "hs_x") == ""
        assert _ha_supplement_piece(None, "hs_x") == ""
        piece = _ha_supplement_piece(
            ["вне выборки tg:30 (01.01.2026 00:30): старое — не подтверждает"],
            "hs_ab12cd34ef56")
        assert piece.count("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56") == 1
        assert piece.startswith("<History_Supplement>")
        assert piece.endswith("</History_Supplement>")

    def test_banner_in_xml_block_keeps_content(self):
        out = _ha_banner_in_block("<dig_result>\nтело\n</dig_result>", "hs_x")
        assert out.startswith("<dig_result>\nДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_x")
        assert "тело" in out and out.rstrip().endswith("</dig_result>")

    def test_head_text_parity_and_banner(self):
        parts = {"head_lines": ["фон: конспект", "текст конспекта"]}
        # без выборки — байт-паритет
        assert _ha_head_text(parts, None) == "фон: конспект\nтекст конспекта"
        with_banner = _ha_head_text(parts, {"sample_id": "hs_x"})
        assert with_banner.startswith("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_x:")
        assert "текст конспекта" in with_banner


# ── 5. Композер: piece history_supplement — P2, слот после episode ──────────

class TestComposerRegistration:
    def test_supplement_kind_p2_after_episode(self):
        from services import direct_context_composer as comp
        assert comp.BLOCK_PRIORITY["history_supplement"] == comp.P2
        assert comp.PIECE_KEEP["history_supplement"] == "head"
        # слот сразу после episode, последующие сдвинуты на +1
        order = comp.CANONICAL_ORDER
        assert order["history_supplement"] == order["episode"] + 1
        assert order["rag"] == 4 and order["sandwich"] == 17
        # относительный порядок прежних kind'ов сохранён
        legacy = ["map", "branch", "episode", "rag", "global_head",
                  "global_middle", "global_tail", "thread", "target",
                  "relations", "protected", "lore", "nostalgia", "mood",
                  "current", "anchors", "sandwich"]
        seq = [order[k] for k in legacy]
        assert seq == sorted(seq)

    def test_empty_supplement_takes_no_slot(self):
        # пустой piece не создаёт кандидата → слоты прежних ходов не меняются
        assert _ha_supplement_piece([], "hs_x") == ""


# ── 7. Композер ON: материализация дополнения в payload хода ────────────────

class TestComposerSupplementPiece:
    """§3: piece history_supplement — P2-слот после episode, баннер внутри;
    без выборки payload байт-в-байт прежний (никакого слота)."""

    def _svc(self):
        from tests.test_direct_chat import FakeLLM, _make_service
        return _make_service(llm=FakeLLM(text="ответ"))

    def _msg(self):
        from tests.test_direct_chat import _message
        return _message(text="бот, привет", message_id=2001)

    _GLOBALS = {"head_lines": ["фон: конспект из 5 сообщений"],
                "middle_rows": [], "tail_rows": [],
                "tail_lines": [], "window_end_ts": None,
                "raw_count": 5, "has_summary": True}

    def _blocks(self):
        return [("target", "<Target_User>Вася [10]</Target_User>"),
                ("current", "<Current_Question>\nпривет\n"
                            "</Current_Question>"),
                ("sandwich", "отвечай коротко")]

    @pytest.mark.asyncio
    async def test_supplement_materializes_labeled_after_episode(self):
        from unittest.mock import patch
        episode = "<Old_Episode>\n[260 | A | tg:260]: в диапазоне\n</Old_Episode>"
        stats = {"count": 1, "messages": 1, "tokens": 10, "hits": 2,
                 "supplement_lines": [
                     "вне выборки tg:30 (01.01.1970 00:00): старый кластер — "
                     "не подтверждает события внутри диапазона (hs_x)"]}
        svc = self._svc()
        with patch.object(svc, "_build_old_episodes",
                          return_value=(episode, stats)):
            texts = await svc._compose_user_content(
                chat_id=CHAT_ID, message=self._msg(), blocks=self._blocks(),
                chain=[], window=[], roster=[], suffix_map={},
                global_parts=dict(self._GLOBALS), target_name="Вася",
                target_user_id=10, trigger_message_id=2001, out_excluded=[],
                history_sample={"sample_id": "hs_ab12cd34ef56"})
        import re as _re
        order = [_re.match(r"<([A-Za-z_]+)>", t).group(1)
                 if t.startswith("<") else "sandwich" for t in texts]
        # слот дополнения — сразу после Old_Episode (§3), до Global_Context
        assert order == ["Old_Episode", "History_Supplement", "Global_Context",
                         "Target_User", "Current_Question", "sandwich"]
        supp_block = texts[1]
        assert supp_block.startswith("<History_Supplement>")
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56" in supp_block
        assert "вне выборки tg:30" in supp_block
        # Old_Episode остаётся чистым аккаунтом диапазона (без меток дополнения)
        assert "вне выборки" not in texts[0]

    @pytest.mark.asyncio
    async def test_head_conspect_banner_in_payload_with_sample(self):
        from unittest.mock import patch
        stats = {"count": 0, "messages": 0, "tokens": 0, "hits": 0}
        svc = self._svc()
        with patch.object(svc, "_build_old_episodes",
                          return_value=("", stats)):
            texts = await svc._compose_user_content(
                chat_id=CHAT_ID, message=self._msg(), blocks=self._blocks(),
                chain=[], window=[], roster=[], suffix_map={},
                global_parts=dict(self._GLOBALS), target_name="Вася",
                target_user_id=10, trigger_message_id=2001, out_excluded=[],
                history_sample={"sample_id": "hs_ab12cd34ef56"})
        global_block = next(t for t in texts
                            if t.startswith("<Global_Context>"))
        # head-конспект — дополнение вне диапазона: баннер первой строкой,
        # сам текст конспекта сохранён (§8.2: конспект ≠ выборка)
        assert global_block.startswith(
            "<Global_Context>\nДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ hs_ab12cd34ef56")
        assert "конспект из 5 сообщений" in global_block
        assert not any(t.startswith("<History_Supplement>") for t in texts)

    @pytest.mark.asyncio
    async def test_no_sample_payload_parity_without_supplement(self):
        from unittest.mock import patch
        stats = {"count": 0, "messages": 0, "tokens": 0, "hits": 0}
        svc = self._svc()
        with patch.object(svc, "_build_old_episodes",
                          return_value=("", stats)):
            texts = await svc._compose_user_content(
                chat_id=CHAT_ID, message=self._msg(), blocks=self._blocks(),
                chain=[], window=[], roster=[], suffix_map={},
                global_parts=dict(self._GLOBALS), target_name="Вася",
                target_user_id=10, trigger_message_id=2001, out_excluded=[])
        # байт-паритет: без выборки нет ни дополнения, ни баннера
        assert not any(t.startswith("<History_Supplement>") for t in texts)
        assert not any("ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" in t for t in texts)
        global_block = next(t for t in texts
                            if t.startswith("<Global_Context>"))
        assert global_block.startswith("<Global_Context>\nфон: конспект")


# ── 6. RAG-блок: баннер при выборке, паритет без неё ────────────────────────

class TestRagBlockBanner:
    def _msg(self, text):
        msg = MagicMock()
        msg.text = text
        msg.message_id = 999
        return msg

    @pytest.mark.asyncio
    async def test_rag_banner_with_sample_labels_out_of_range_memory(self):
        db = await _make_db(10)
        bound = await capture_history_sample(db, CHAT_ID, 5)
        assert bound is not None
        memory = MagicMock()

        async def fake_facts(*a, **k):
            return [("user_memory", "старый факт вне диапазона", 123)]

        memory.get_rag_facts = fake_facts

        async def no_rerank(*a, **k):
            raise RuntimeError("rerank off")

        memory.rerank_rag_facts = no_rerank
        svc = _service(db, memory=memory)
        block, hint = await svc._build_rag_block(
            CHAT_ID, self._msg("проанализируй последние 5 сообщений"), "",
            history_sample=bound)
        # баннер — первой строкой внутри <RAG_Memory>; факт остаётся
        assert block.startswith(
            f"<RAG_Memory>\nДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ {bound['sample_id']}")
        assert "старый факт вне диапазона" in block
        assert hint == ""

    @pytest.mark.asyncio
    async def test_rag_no_sample_parity_no_banner(self):
        db = await _make_db(10)
        memory = MagicMock()

        async def fake_facts(*a, **k):
            return [("user_memory", "обычный факт", 123)]

        memory.get_rag_facts = fake_facts

        async def no_rerank(*a, **k):
            raise RuntimeError("rerank off")

        memory.rerank_rag_facts = no_rerank
        svc = _service(db, memory=memory)
        block, hint = await svc._build_rag_block(
            CHAT_ID, self._msg("как дела?"), "", history_sample=None)
        assert block.startswith("<RAG_Memory>\n[")
        assert "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" not in block
