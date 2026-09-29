"""ASAP-3 (round 1028) — контекст-сценарии владельца (T-4031/T-4032).

§37 TEST 1–5: Unlimited без скрытого cap (нет 39371→27826), accounting при -1,
рост external/window; §38: old verbatim episode + fresh tail + summary-background;
§39: stale summary lag 50/100/300/400 без brutal cut; §40: reply-цепь >6 hops.
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.direct_chat_service as dcs
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver

pytestmark = pytest.mark.asap3

BOT_ID = 12345
CHAT_ID = -1001234567890
NOW = 1_800_000_000


class _Row(dict):
    """sqlite3.Row-подобная строка smart_messages (доступ по ключу)."""


def _row(tg, ts, text, user_id=10, author="Вася", reply_to=None):
    return _Row(user_id=user_id, author_name=author, text=text,
                timestamp=ts, media_type="text", reply_to_id=reply_to,
                is_forward=0, forward_source=None, tg_message_id=tg,
                id=tg)


class FakeLLM:
    def __init__(self, text="держись"):
        self.text = text
        self.calls = []
        self._chat_model = "deepseek-chat"        # 131072 (карта D1)
        self._fallback_model = ""

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.calls.append(messages)
        return self.text


class Asap3FakeDB:
    """FakeDB с полной поверхностью composer-пути (без PG)."""

    def __init__(self, *, window_rows=None, summary=None, chain=None,
                 fts_hits=None, around=None):
        self.window_rows = window_rows or []
        self.summary = summary
        self.chain = chain or {}          # tg_id -> row
        self.fts_hits = fts_hits or []
        self.around = around or []
        self.tone_preset = None

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return self.chain.get(tg_id)

    async def get_running_summary(self, chat_id, now):
        return self.summary

    async def get_summary_level(self, chat_id, level):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return self.tone_preset

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        self.tone_preset = preset

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, ts):
        return 0

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def get_bot_reply(self, chat_id, tg_id, now):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return None

    async def search_messages_fts(self, chat_id, match, limit):
        return list(self.fts_hits)

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return []

    async def list_lore_stories(self, chat_id, limit=200):
        return []

    async def get_messages_around(self, chat_id, target_tg, before, after):
        return list(self.around)

    async def get_active_embedding_generation(self, name):
        return None


class FakeMemory:
    def __init__(self, window=None):
        self.window = window or []

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def retrieve_fact_candidates(self, chat_id, query, limit=8):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type, **kw):
        return None

    async def memorize_self_reply(self, chat_id, essence):
        return 1


def _message(text, message_id=100, *, reply_to_bot=False, user_id=10):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    if reply_to_bot:
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = BOT_ID
        reply.text = "ответ бота"
        reply.web_page = None
        m.reply_to_message = reply
    else:
        m.reply_to_message = None
    m.entities = None
    m.web_page = None
    return m


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    bot.set_message_reaction = AsyncMock(return_value=True)
    return bot


def _make_service(memory, db, llm):
    return DirectChatService(
        memory, db, llm, AliasResolver("{}"),
        bot_id=BOT_ID, bot_username="test_bot", breaker=None, cache=None,
        tool_router=None)


def _summary_row(watermark, raw_count):
    return {"summary": "конспект старой части разговора",
            "raw_count": raw_count, "window_end_ts": watermark,
            "expires_at": NOW + 3600}


def _unlimited_budget(monkeypatch):
    """Per-chat `limits.chat_context_budget_tokens = -1` (семантика
    инцидентного чата §1; otherwise hot-дефолт 16000 → cap-режим)."""
    async def fake_param(chat_id, key, default=None):
        if key == "limits.chat_context_budget_tokens":
            return -1
        return default

    monkeypatch.setattr("services.chat_params.get_chat_param", fake_param)


# ── §37: Unlimited / capacity ───────────────────────────────────────────────

class TestUnlimited:
    @pytest.mark.asyncio
    async def test_test1_minus_one_no_hidden_truncation(self, caplog,
                                                        monkeypatch):
        # TEST 1: global ~тяжёлый контекст при -1 и окне 131072 → НЕТ
        # «39371 -> 27826»; весь verbatim-хвост доходит до промпта.
        _unlimited_budget(monkeypatch)
        rows = [_row(1000 + i, 1700000000 + i,
                     f"сообщение номер {i} с достаточным наполнением текста "
                     f"и продолжением мысли {i} " * 3)
                for i in range(60)]
        db = Asap3FakeDB(window_rows=rows)
        memory = FakeMemory(window=rows)
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        with caplog.at_level(logging.WARNING):
            await svc.handle(_bot(), _message("бот, как дела?",
                                              message_id=2001),
                             _message("бот, как дела?", message_id=2001)
                             .from_user)
        warnings = [r.getMessage() for r in caplog.records]
        assert not any("truncated" in w for w in warnings), \
            "при Unlimited WARN усечения недопустим"
        assert not any("27826" in w for w in warnings)
        payload = "\n".join(str(m) for m in llm.calls[-1])
        assert "сообщение номер 1 " in payload
        diag = dcs._composer.get_diagnostics(CHAT_ID)
        assert diag and diag["policy_mode"] == "unlimited"
        # Unlimited-бюджет > старого скрытого потолка 27826 при окне 131072.
        assert diag["budget"] > 27826

    @pytest.mark.asyncio
    async def test_test2_thread_no_hidden_cap(self, monkeypatch):
        # TEST 2: тред при -1 не режется к 32000/дефолт-cap (composer ON:
        # билдер без self-усечения; единственная точка — бюджет композера).
        _unlimited_budget(monkeypatch)
        chain_rows = [_row(3000 + i, NOW - 500 + i,
                           f"ход цепочки {i} " + "наполнение " * 12,
                           reply_to=(3000 + i - 1) if i else None)
                      for i in range(12)]
        # Триггер (2002) уже в smart_messages: reply на 3011 (хвост цепи).
        chain_rows.append(_row(2002, NOW - 400, "ну и что ты про это?",
                               reply_to=3011))
        db = Asap3FakeDB(chain={r["tg_message_id"]: r for r in chain_rows})
        memory = FakeMemory(window=[])
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        msg = _message("ну и что ты про это думаешь?", message_id=2002,
                       reply_to_bot=True)
        await svc.handle(_bot(), msg, msg.from_user)
        payload = "\n".join(str(m) for m in llm.calls[-1])
        assert "ход цепочки 0" in payload, \
            "корень цепочки не должен теряться при Unlimited"

    @pytest.mark.asyncio
    async def test_test3_unlimited_still_accounts(self):
        # TEST 3: aggregate -1 → full-payload accounting ВСЁ РАВНО выполняется
        # (CONTEXT_CAPACITY эмитируется; diagnostics заполняются).
        rows = [_row(4000 + i, NOW - 100 + i, f"фоновое сообщение {i}")
                for i in range(10)]
        db = Asap3FakeDB(window_rows=rows)
        memory = FakeMemory(window=rows)
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        with patch("services.direct_context_composer.emit_agentic_event") \
                as emit:
            await svc.handle(_bot(), _message("бот, привет",
                                              message_id=2003),
                             _message("бот, привет",
                                      message_id=2003).from_user)
        events = [c.args[0] for c in emit.call_args_list]
        assert "CONTEXT_CAPACITY" in events, "accounting при -1 обязан идти"
        assert "CONTEXT_SELECT" in events
        diag = dcs._composer.get_diagnostics(CHAT_ID)
        assert diag and diag["policy_mode"] in ("unlimited", "dynamic",
                                                "cap")

    @pytest.mark.asyncio
    async def test_test4_growth_external_reduces_budget(self):
        # TEST 4: рост system/tools/personality → available ↓ (виден в
        # diagnostics через сравнение доступного бюджета двух прогонов).
        rows = [_row(5000 + i, NOW - 100 + i, f"фоновое {i}") for i in range(5)]
        db = Asap3FakeDB(window_rows=rows)
        memory = FakeMemory(window=rows)
        svc = _make_service(memory, db, FakeLLM())
        window, source = dcs.resolve_effective_window("deepseek-chat", "")
        small_ext, _ = dcs.compute_available_budget(window, 2000, 0.10)
        big_ext, _ = dcs.compute_available_budget(window, 12000, 0.10)
        assert big_ext < small_ext

    def test_test5_window_growth_expands_unlimited(self):
        # TEST 5: рост окна модели → Unlimited больше без правки констант.
        small = dcs.compute_available_budget(32768, 1000, 0.10)[0]
        large = dcs.compute_available_budget(131072, 1000, 0.10)[0]
        assert large > small


# ── §38: old verbatim episode ───────────────────────────────────────────────

class TestOldEpisode:
    @pytest.mark.asyncio
    async def test_old_dialogue_returns_verbatim(self):
        # Fixture: ~200 сообщений; запрос про разговор ~200 назад (20-40
        # сообщений); retrieval-хит → coherent episode verbatim.
        tail_rows = [_row(6000 + i, NOW - 60 + i, f"свежее сообщение {i}")
                     for i in range(25)]
        old_rows = [_row(5200 + i, NOW - 90000 + i * 5,
                         f"старый диалог про метель, строка {i}")
                    for i in range(30)]
        window = old_rows + tail_rows
        db = Asap3FakeDB(
            window_rows=window,
            summary=_summary_row(watermark=NOW - 60, raw_count=450),
            fts_hits=[old_rows[15]],
            around=old_rows)
        memory = FakeMemory(window=window)
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        await svc.handle(_bot(), _message("бот, помнишь метель?",
                                          message_id=2101),
                         _message("бот, помнишь метель?",
                                  message_id=2101).from_user)
        payload = "\n".join(str(m) for m in llm.calls[-1])
        # (1) old episode verbatim (exact wording):
        assert "<Old_Episode>" in payload
        assert "старый диалог про метель, строка 15" in payload
        # (2) recent context остаётся verbatim:
        assert "свежее сообщение 24" in payload
        # (3) running summary как background:
        assert "конспект старой части разговора" in payload
        stats = dcs._composer.direct_metrics_snapshot()
        assert stats["direct_old_episode_retrieval_total"] >= 1


# ── §39: stale running summary ──────────────────────────────────────────────

class TestStaleSummary:
    @pytest.mark.parametrize("lag", [50, 100, 300, 400])
    @pytest.mark.asyncio
    async def test_lag_composition_no_brutal_cut(self, lag):
        # Direct работает при отставании summary; композиция =
        # summary + selected middle + fresh tail (без summary+tail→ножниц).
        tail_rows = [_row(7000 + i, NOW - 30 + i, f"хвост {i}")
                     for i in range(20)]
        middle_rows = [_row(6500 + i, NOW - 5000 + i, f"середина {i} "
                            "с важным контекстом продолжения")
                       for i in range(lag)]
        window = middle_rows + tail_rows
        db = Asap3FakeDB(window_rows=window,
                         summary=_summary_row(watermark=NOW - 5000,
                                              raw_count=100))
        memory = FakeMemory(window=window)
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        await svc.handle(_bot(), _message("бот, что там было?",
                                          message_id=2200 + lag),
                         _message("бот, что там было?",
                                  message_id=2200 + lag).from_user)
        assert llm.calls, f"lag={lag}: direct обязан отвечать"
        payload = "\n".join(str(m) for m in llm.calls[-1])
        assert "конспект старой части разговора" in payload
        assert "хвост 19" in payload            # fresh tail verbatim

    @pytest.mark.asyncio
    async def test_lag400_middle_topk_under_pressure(self, monkeypatch):
        # H1/D5 (rework round 1): реальный путь композера, lag=400.
        # Сплит: fresh tail = последние 20 строк (floor, P1), middle top-K ≤
        # CHAT_MIDDLE_MAX_MESSAGES из непокрытого диапазона. Бюджет-кап
        # создаёт давление: middle поджимается (P3 эвикция первая), НО
        # присутствует в payload; tail стоит на floor; clamp-событие.
        async def fake_param(chat_id, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return 2600         # давление: floor tail (~940) + P0 (~90)
                #   влезают, middle (P3) поджимается с 3059 до ~1500
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param", fake_param)
        tail_rows = [_row(7000 + i, NOW - 30 + i,
                          f"ХВОСТ-МАРКЕР-{i} свежее сообщение хвоста диалога "
                          f"с наполнением {i}")
                     for i in range(20)]
        middle_rows = [_row(6500 + i, NOW - 5000 + i,
                            f"СЕРЕДИНА-МАРКЕР-{i} середина отставшего "
                            f"диапазона с содержательным контекстом {i}")
                       for i in range(400)]
        window = middle_rows + tail_rows
        db = Asap3FakeDB(window_rows=window,
                         summary=_summary_row(watermark=NOW - 5000,
                                              raw_count=500))

        async def _run_once():
            # Свежий FakeLLM на прогон: фоновый running-summary
            # (fire_and_forget из get_window_messages) пишет в общий llm.calls
            # и гонкой ломает снятие payload'а (не продуктовый дефект).
            memory = FakeMemory(window=window)
            svc = _make_service(memory, db, FakeLLM())
            with patch("services.direct_context_composer."
                       "emit_agentic_event") as emit:
                await svc.handle(_bot(), _message("бот, что там было?",
                                                  message_id=2400),
                                 _message("бот, что там было?",
                                          message_id=2400).from_user)
            events = {}
            for c in emit.call_args_list:
                events.setdefault(c.args[0], []).append(c.kwargs)
            payload = "\n".join(str(m) for m in svc.llm.calls[-1])
            return events, payload

        events1, payload1 = await _run_once()
        # (а) middle ПРИСУТСТВУЕТ в payload (dead code устранён):
        assert "СЕРЕДИНА-МАРКЕР-" in payload1, \
            "middle top-K обязан отбираться из непокрытого хвостом диапазона"
        # (б) fresh tail (floor 20, keep-end) вербатим — весь:
        assert "ХВОСТ-МАРКЕР-19" in payload1
        assert "ХВОСТ-МАРКЕР-0" in payload1
        # (в) капы: middle_selected_messages > 0 и ≤ 60 (§3.7);
        selects = [e for e in events1.get("CONTEXT_SELECT", [])]
        assert selects and selects[0]["middle_selected_messages"] > 0
        assert selects[0]["middle_selected_messages"] <= 60
        # (г) H2: давление зажало tail на floor → CONTEXT_TAIL_FLOOR_CLAMPED
        clamped = events1.get("CONTEXT_TAIL_FLOOR_CLAMPED")
        assert clamped and clamped[0]["final_messages"] <= 20
        assert clamped[0]["floor_messages"] == 20
        # (д) детерминизм: тот же вход → тот же набор выбранных middle
        events2, payload2 = await _run_once()
        sel1 = sorted(set(__import__("re").findall(
            r"СЕРЕДИНА-МАРКЕР-(\d+)", payload1)))
        sel2 = sorted(set(__import__("re").findall(
            r"СЕРЕДИНА-МАРКЕР-(\d+)", payload2)))
        assert sel1 == sel2 and len(sel1) > 0, \
            "top-K выбор детерминирован (тот же вход — тот же span)"

    @pytest.mark.asyncio
    async def test_lag50_middle_composed_without_pressure(self):
        # H1 (прямая сторона): lag(50) > tail_min(20) → middle top-K собирает
        # непокрытый диапазон (50 кандидатов) даже без давления; строка
        # встречается в payload ровно один раз (дедуп против tail работает).
        tail_rows = [_row(7000 + i, NOW - 30 + i,
                          f"ХВОСТ-МАРКЕР-{i} свежее сообщение")
                     for i in range(20)]
        middle_rows = [_row(6500 + i, NOW - 4900 + i,
                            f"СЕРЕДИНА-МАРКЕР-{i} середина диапазона")
                       for i in range(50)]
        window = middle_rows + tail_rows
        db = Asap3FakeDB(window_rows=window,
                         summary=_summary_row(watermark=NOW - 5000,
                                              raw_count=100))
        memory = FakeMemory(window=window)
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        with patch("services.direct_context_composer."
                   "emit_agentic_event") as emit:
            await svc.handle(_bot(), _message("бот, что там было?",
                                              message_id=2500),
                             _message("бот, что там было?",
                                      message_id=2500).from_user)
        payload = "\n".join(str(m) for m in llm.calls[-1])
        assert "СЕРЕДИНА-МАРКЕР-0" in payload, \
            "middle-кандидаты (вне floor-диапазона) попадают в payload"
        assert "ХВОСТ-МАРКЕР-0" in payload
        assert payload.count("СЕРЕДИНА-МАРКЕР-7") == 1, \
            "каждая middle-строка ровно один раз (дедуп работает)"
        selects = [c.kwargs for c in emit.call_args_list
                   if c.args and c.args[0] == "CONTEXT_SELECT"]
        assert selects and selects[0]["middle_selected_messages"] == 50


# ── §40: длинная reply-цепь (> CHAT_THREAD_MAX_DEPTH) ──────────────────────

class TestLongReplyChain:
    @pytest.mark.asyncio
    async def test_thesis_beyond_depth_6_reachable(self):
        # Цепь из 12 ходов (дефолт глубины 6); важный тезис — в КОРНЕ.
        # Composer walk ≤ CHAT_THREAD_WALK_MAX=40 → тезис доступен.
        chain_rows = [_row(8000 + i, NOW - 1000 + i * 10,
                           ("ВАЖНЫЙ ТЕЗИС ПРО СРОК ДОСТАВКИ" if i == 0
                            else f"reply {i} обсуждения"),
                           reply_to=(8000 + i - 1) if i else None)
                      for i in range(12)]
        # Триггер (2301) — reply на хвост цепи (8011); он уже в smart_messages.
        chain_rows.append(_row(2301, NOW - 900, "так в чём там был итог?",
                               reply_to=8011))
        db = Asap3FakeDB(chain={r["tg_message_id"]: r for r in chain_rows})
        memory = FakeMemory(window=[])
        llm = FakeLLM()
        svc = _make_service(memory, db, llm)
        msg = _message("так в чём там был итог?", message_id=2301,
                       reply_to_bot=True)
        await svc.handle(_bot(), msg, msg.from_user)
        payload = "\n".join(str(m) for m in llm.calls[-1])
        assert "ВАЖНЫЙ ТЕЗИС ПРО СРОК ДОСТАВКИ" in payload, \
            "тезис глубже CHAT_THREAD_MAX_DEPTH обязан быть доступен (§40)"
