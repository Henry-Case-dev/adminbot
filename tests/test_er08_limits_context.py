"""ER-08 (02.11.2026) — реальные потери контекста L1, семантика лимитов и
дедлайнов, видимость неизвестной цены.

Класс: CONTRACT/REGRESSION. Каждый тест отвечает на конкретный пункт решения
владельца (`plans/owner_inputs/2026-11-02-limits-economics-decision.md`):

1. L1-пакет: исходное сообщение, цитата (reply), адресация и claim'ы в ХВОСТЕ
   длинных сообщений доезжают до планера; бюджет — из Model Capacity Resolver,
   а не из код-константы.
2. `metered_calls` — счётчик инструментов, не денег: read-only проверка фактов
   не блокируется «финансовой экономией», анти-петлевые гварды живут.
3. Дедлайн Direct Orchestrator не обрывает работу раньше tool-цепочки.
4. Неизвестная цена показывается как неизвестная (`price_known=false` +
   `unknown_rows`), а не как ноль.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

W19_TAIL = "ENDOFMSG19"
W20_TAIL = "CLAIMINSHORTMSG"
REPLY_TAIL = "CLAIMINQUOTE"
MSG_TAIL = "TAILMARK_QUEST"


def _row(i, text, author="Аня"):
    return {"id": i, "author_name": author, "text": text, "user_id": 100 + i}


def _window(row_chars=500):
    rows = []
    for i in range(1, 15):
        rows.append(_row(i, (f"реплика {i}: " + "разговор " * 200)[:row_chars]))
    for i in range(15, 19):
        rows.append(_row(i, (f"реплика {i}: " + "обсуждаем " * 200)[:row_chars]))
    # 19: 700 символов, claim и контрдовод В КОНЦЕ (типичный контрдовод)
    rows.append(_row(19, ("контекст " * 60)
                     + " но на самом деле в 1017 нет функции X "
                     + ("подробности " * 10) + " " + W19_TAIL))
    # 20: 430 символов, claim в конце
    rows.append(_row(20, ("обсуждаем версию " * 30)[:400] + " " + W20_TAIL))
    return rows


def _reply(chars=760):
    return ("начало цитаты " * 60)[:chars - 30] + " " + REPLY_TAIL + " хвост"


def _message():
    return ("Длинное рассуждение пользователя. " * 55) + " Итог: " + MSG_TAIL


# ── 1. L1: реальные потери пакета ──────────────────────────────────────────

class TestL1PackageLosses:

    def test_window_line_tail_survives_static_floor(self):
        """REGRESSION: при прежнем фиксированном бюджете (1600 токенов) claim в
        ХВОСТЕ длинной реплики раньше терялся (головной срез `[:cap]`).
        Сценарий: 20 строк, cap строки = 200 (пол), claim на ~650-м символе."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", window=_window(), speaker="Аня",
                                  addressee="Борис", budget_tokens=1600)
        assert l1.window_line_chars(_window(), budget_tokens=1600) == \
            l1.L1_WINDOW_LINE_CHARS          # пол сохранён — это не правка пола
        assert W19_TAIL in ctx, "claim/контрдовод в хвосте реплики не доехал"
        assert W20_TAIL in ctx

    def test_reply_block_tail_survives(self):
        """REGRESSION: цитата 760 символов при старом капе 400 символов теряла
        claim на ~740-м символе (головной срез)."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", reply_block=_reply(),
                                  speaker="Аня", budget_tokens=1600)
        assert REPLY_TAIL in ctx
        body = ctx.split(f"[{l1.L1_REPLY_SECTION}]\n", 1)[1]
        assert len(body) > l1.L1_REPLY_BLOCK_CHARS

    def test_memory_hint_tail_survives_pressure(self):
        """Релевантные факты (срез bundle «КОНТЕКСТ ДИАЛОГА (не терять)»):
        ограничения/уроки стоят в КОНЦЕ блока — при сжатии хвост не теряется."""
        from services import direct_l1 as l1

        hints = ("КОНТЕКСТ ДИАЛОГА (не терять):\nАдресат: Борис\n"
                 + "факт " * 400 + "\n- УРОК_ХВОСТ")
        rows = [_row(i, ("реплика %d: " % i + "обсуждаем " * 100)[:700])
                for i in range(1, 20)]
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=rows, speaker="Аня", memory_hints=hints,
            persona_frame="характер " * 45, budget_tokens=1200)
        assert "УРОК_ХВОСТ" in ctx
        assert "Адресат: Борис" in ctx

    def test_message_tail_reaches_planner(self):
        """Исходное сообщение: хвост (вопрос/итог) обязан доезжать."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", current_question=_message(),
                                  speaker="Аня", budget_tokens=1600)
        assert MSG_TAIL in ctx

    def test_reply_section_protected_under_hint_pressure(self):
        """Переполнение: сжимается ОКНО, а не цитата; claim в цитате выживает,
        окно при этом честно теряет строки (счётчик «ГРАНИЦА ИСТОРИИ»)."""
        from services import direct_l1 as l1

        rows = [_row(i, ("реплика %d: " % i + "обсуждаем " * 100)[:700])
                for i in range(1, 20)] + [_row(20, "обсуждаем " * 100)]
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=rows, speaker="Аня",
            memory_hints=("память: " + "факт " * 400)[:2000],
            persona_frame="характер " * 45, budget_tokens=1600)
        assert REPLY_TAIL in ctx
        window_part = ctx.split("[ПОСЛЕДНИЕ СООБЩЕНИЯ]\n", 1)
        delivered = (len(window_part[1].split("\n\n[", 1)[0].splitlines())
                     if len(window_part) > 1 else 0)
        assert delivered < len(rows)
        assert "[ГРАНИЦА ИСТОРИИ]" in ctx

    @pytest.mark.asyncio
    async def test_full_window_claim_reaches_planner_with_derived_budget(self):
        """ГЛАВНОЕ: бюджет из реального окна модели (Model Capacity Resolver)
        → в полном 20-строчном окне claim'ы в хвостах доезжают до планера."""
        from services import direct_l1 as l1
        from services.token_counter import count_tokens

        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash",
            mandatory_tokens=count_tokens("систем промпт " * 200))
        assert budget > l1.L1_CONTEXT_FLOOR_TOKENS
        assert meta["source"] == "model_window"
        assert meta["context_window"] >= 131072
        assert l1.window_line_chars(_window(), budget_tokens=budget) > \
            l1.L1_WINDOW_LINE_CHARS
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=_window(), speaker="Аня", addressee="Борис",
            budget_tokens=budget)
        for marker in (MSG_TAIL, W19_TAIL, W20_TAIL, REPLY_TAIL):
            assert marker in ctx
        # Бюджет — реальная граница пакета, а не «сколько влезло».
        assert count_tokens(ctx) <= budget
        assert "Адресат: Борис" in ctx

    @pytest.mark.asyncio
    async def test_budget_shrinks_with_small_model_window(self, monkeypatch):
        """Тот же резолвер: маленькое окно модели → меньший бюджет, но не ниже
        прежнего пола (правка не ухудшает чистую установку)."""
        from config.settings import Settings
        from services import direct_l1 as l1
        from services import model_capacity as capacity

        monkeypatch.setattr(Settings, "CHAT_MODEL_CONTEXT_WINDOW", 5000)
        capacity.invalidate_capacity_cache()
        capacity._WINDOW_CACHE.clear()
        try:
            budget, meta = await l1.resolve_l1_context_budget(
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash")
            # Окно 5000 → доступный вход ≈ 3.4k токенов (reserve вывода 1024 +
            # safety) — меньше, чем на 131k, и не ниже прежнего пола.
            assert meta["context_window"] == 5000
            assert l1.L1_CONTEXT_FLOOR_TOKENS <= budget < 5000
        finally:
            capacity.invalidate_capacity_cache()
            capacity._WINDOW_CACHE.clear()

    @pytest.mark.asyncio
    async def test_explicit_operator_cap_is_highest_priority(self, monkeypatch):
        """Явный hot-ключ оператора остаётся высшим приоритетом (ручное
        решение не перебивается динамикой)."""
        from services import direct_l1 as l1
        from services import hot_config as hot

        real_get = hot.get

        def _get(key, default=None):
            if key == "limits.direct_l1_context_tokens":
                return 2400
            return real_get(key, default)

        monkeypatch.setattr(hot, "get", _get)
        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash")
        assert budget == 2400 and meta["source"] == "hot"

    def test_message_cap_from_budget_not_writer_800(self):
        """Исходное сообщение: кап L1 выводится из бюджета, а не берётся
        Writer-путь 800 символов."""
        from services import direct_l1 as l1

        assert l1.message_cap_chars(1600) == 3200
        assert l1.message_cap_chars(112000) == l1.L1_MESSAGE_CHARS_MAX
        long_message = ("слово " * 700)[:3900] + " " + MSG_TAIL
        ctx = l1.build_l1_context(query="q", current_question=long_message,
                                  speaker="Аня", budget_tokens=112000)
        assert long_message.strip() in ctx

    def test_live_path_passes_derived_budget(self):
        """AST-проверка живой проводки: оба L1-сайта передают бюджет, а
        прямой путь — и кап исходного сообщения из него."""
        text = (ROOT / "services/direct_chat_service.py").read_text(
            encoding="utf-8")
        plan = text[text.index("async def _plan_direct_l1"):]
        plan = plan[:plan.index("async def _attach_l1_plan_meta")]
        assert "await _l1.resolve_l1_context_budget(" in plan
        assert "budget_tokens=_l1_budget" in plan
        assert "cap_chars=_l1.message_cap_chars(_l1_budget)" in plan
        init = text[text.index("async def plan_initiative_decision"):]
        init = init[:init.index("async def generate_initiative_reply")]
        assert "await _l1.resolve_l1_context_budget(" in init
        assert "budget_tokens=_init_budget" in init

    def test_plan_meta_exposes_effective_budget_and_source(self):
        """Durable-наблюдаемость (§8 «контракт замера»): эффективный лимит и
        его источник доезжают до usage-plan_meta."""
        from services import direct_l1 as l1
        from services import usage_events as ue
        from services.direct_chat_service import _l1_usage_plan_meta

        out = _l1_usage_plan_meta(
            l1.L1Plan(), {"l1_context_budget": 4096,
                          "l1_context_source": "model_window"},
            fallback_flag="", latency_ms=5, input_chars=100)
        safe = ue.sanitize_plan_meta(out)
        assert safe["l1_context_budget"] == 4096
        assert safe["l1_context_source"] == "model_window"
        assert {"l1_context_budget", "l1_context_source"} <= set(
            ue.PLAN_META_FIELDS)


# ── 2. metered / деньги ────────────────────────────────────────────────────

class TestMeteredIsToolCounterNotMoney:

    def test_read_only_evidence_tools_are_not_cost_limited(self):
        from services import tool_loop

        for name in ("execute_web_search", "fetch_article", "fact_check"):
            assert name in tool_loop.METERED_TOOLS        # факт метричности
            assert tool_loop.cost_limited_tool(name) is False
        for name in ("generate_image", "edit_image", "summarize_video",
                     "transcribe_video", "recognize_image"):
            assert tool_loop.cost_limited_tool(name) is True

    def test_anti_loop_guards_still_present(self):
        """Защита сохранена: общий cap вызовов, раунды, один вызов ≤2 раза."""
        from services import tool_loop

        assert tool_loop.TOOL_MAX_TOTAL_CALLS == 6
        assert tool_loop._TOOL_MAX_SAME_CALL == 2
        assert tool_loop.TOOL_MAX_ROUNDS == 4
        assert tool_loop._TOOL_CALLS_PER_ROUND_MAX == 2

    def test_money_limits_on_cannot_silently_block_evidence(self):
        """ГРАНИЦА: механизм денежных caps инертен (нет runtime-вызывающих) и
        при неизвестной цене не отказывает — включение флага не может молча
        срезать проверку фактов."""
        from config.settings import Settings
        from services import mca_money_limits as ml

        import_re = re.compile(
            r"^\s*(?:from|import)\s+.*mca_money_limits", re.MULTILINE)
        for path in (ROOT / "services").glob("*.py"):
            if path.name == "mca_money_limits.py":
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            assert not import_re.search(source), path.name
        assert Settings.MCA_MONEY_LIMITS_ENABLED is False
        # Механизм, вызванный вручную при неизвестной цене, не отказывает.
        decision = ml.check_and_reserve("direct", None, price_known=False)
        assert decision["allowed"] is True


# ── 3. Дедлайны ────────────────────────────────────────────────────────────

class TestDeadlines:

    def test_orchestrator_deadline_matches_tool_chain(self):
        """Аудит: оркестратор больше не обрывает работу на 90 с при tool-цепочке
        360 с (per-tool: поиск 25 + статья 45 = 70 с на шаг)."""
        from config.settings import Settings
        from services import direct_execution as de
        from services import tool_loop

        assert de.orchestrator_max_time_seconds() == \
            tool_loop._chain_timeout_seconds() == 360.0
        assert Settings.MCA_TOOL_CHAIN_TIMEOUT_SECONDS == 360.0

    def test_orchestrator_follows_chain_timeout_setting(self, monkeypatch):
        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 180.0)
        assert de.orchestrator_max_time_seconds() == 180.0

    def test_orchestrator_explicit_override_kept(self, monkeypatch):
        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(
            Settings, "DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS", 45.0,
            raising=False)
        assert de.orchestrator_max_time_seconds() == 45.0

    def test_chain_budget_uses_same_resolvers(self, monkeypatch):
        """ChainBudget (simple/adaptive) берёт те же значения, что tool_loop,
        а не собственные копии констант."""
        import time

        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 120.0)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 5)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", 3)
        budget = de.ChainBudget()
        assert budget.max_total == 5 and budget.max_metered == 3
        remaining = budget.deadline - time.monotonic()
        assert 110.0 < remaining <= 120.0


# ── 4. Видимость неизвестной цены ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_cost_group_marks_unknown_price(tmp_path):
    """Неизвестный тариф не превращается в ноль: сумма идёт только по
    `price_known`, а непрозрачные строки видны отдельным счётчиком."""
    from services import mca_events as me
    from services.database import DatabaseService

    d = DatabaseService(str(tmp_path / "er08.db"))
    await d.initialize()
    try:
        me.emit_mca_event("A", outcome=me.OUTCOME_SUCCESS, component="summary",
                          usage_json={"cost_usd": 0.25, "price_known": True})
        me.emit_mca_event("B", outcome=me.OUTCOME_SUCCESS, component="summary",
                          usage_json={"cost_usd": None, "price_known": False})
        await me.flush_events(d)
        m = await me.metrics(d)
        cost = m["metrics"]["cost"]
        assert cost["by_category"]["summary"] == 0.25
        assert cost["known_rows"] == 1 and cost["unknown_rows"] == 1
        assert cost["price_known"] is False
    finally:
        await d.close()
