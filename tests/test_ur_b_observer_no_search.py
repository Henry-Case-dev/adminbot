"""UNIFIED-REPLY UR-06.5 — SILENT/REACT без текста и Observer не ищут.

Требование (owner §4, UR-06.5): SILENT/REACT без текста не запускают поиск
ради отчётности, а Observer не выполняет постоянный поиск по каждому окну до
решения об участии.

Тест Observer'а перенесён из `ur/b-evidence@6099cc17` (класс
`TestObserverCheckMakesNoSearch`) и адаптирован к текущей базе 2.58.273:
проход идёт через настоящий `observe_tick` с настоящим `DirectChatService`
(реальные `_evidence_preflight`, `_l1_tool_subset`, `_l1_tool_phase`,
`ToolRouter`). Поиск виден двумя независимыми каналами: подменным провайдером
роутера и `SearchAggregator.search` (любой другой путь поиска).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-06.5
"""
import json
import time

import pytest

from services import direct_execution as _dx
from tests.test_ur_b_live_wiring import (
    CHAT_ID, _plan, _service, _tool_phase, _SearchProvider)

pytestmark = [pytest.mark.system2]


# ── SILENT/REACT: живой tool-этап делает 0 поисковых вызовов ───────────────


class TestSilentReactNoSearch:
    @pytest.mark.parametrize("action,reaction", [("silent", None),
                                                 ("react", "👍")])
    @pytest.mark.asyncio
    async def test_live_tool_phase_makes_no_provider_call(self, action,
                                                          reaction):
        search = _SearchProvider()
        service = _service(search)
        plan = _plan(action=action, reaction=reaction,
                     knowledge_origin="open_world",
                     search_intent="required",
                     capabilities_needed=["web_search"])
        raw = await _tool_phase(service, plan, "что нового в мире")
        assert search.queries == [], f"{action}: поиск ради отчётности"
        assert raw is None, "SILENT/REACT не должны запускать tool-цепочку"


# ── Observer: проверка не делает поисковых вызовов (UR-06.5) ───────────────


class _ObserverVerdictLLM:
    """Оценщик Observer'а: живой вердикт «есть повод сказать»."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return json.dumps({"opportunity": True, "kind": "development",
                           "action": "say", "horizon": "now",
                           "topic_key": "games", "relevance": 0.9,
                           "significance": 0.9,
                           "goal": "участники обсуждают игры",
                           "rationale": "живая тема"}, ensure_ascii=False)


class _ObserverBot:
    def __init__(self):
        self.id = 999
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text)))

        class _Msg:
            message_id = 7100 + len(self.sent)

        return _Msg()


class _HotValues:
    def __init__(self, values):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _ChatParamValues:
    def __init__(self, by_chat):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


_OBSERVER_PARAMS = {
    "flags.initiative_observer_enabled": True,
    "initiative.enabled": True,
    "initiative.frequency_profile": "active",
    "initiative.eval_min_messages": 1,
    "initiative.eval_min_interval_seconds": 0,
    "initiative.min_gap_seconds": 0,
    "initiative.max_replies_per_day": 10,
    "initiative.eval_llm_budget_per_day": 10,
}


class TestObserverCheckMakesNoSearch:
    @pytest.mark.asyncio
    async def test_observer_check_performs_zero_search_calls(self, tmp_path,
                                                             monkeypatch):
        """Проверка Observer'а целиком (скан → оценка → инициативный Writer)
        не делает ни одного поискового вызова.

        Отсутствие импорта поиска в `initiative_observer` — не доказательство:
        проверка проверяется НА ИСПОЛНЕНИИ. Проход идёт через настоящий
        `observe_tick` с настоящим `DirectChatService` в роли Writer'а
        (реальные `_evidence_preflight`, `_l1_tool_subset`, `_l1_tool_phase`,
        `ToolRouter`), а сделанный поиск был бы виден двумя независимыми
        каналами: запросом подменного поискового провайдера и классом
        `SearchAggregator` (любой другой путь поиска)."""
        from services import chat_params
        from services import hot_config
        from services import initiative_observer as _obs
        from services import mca_exploration as _mx
        from services import search_aggregator as _sa
        from services.database import DatabaseService

        hot_config.set_config_cache(_HotValues(_OBSERVER_PARAMS))
        chat_params.set_chat_params_cache(
            _ChatParamValues({CHAT_ID: dict(_OBSERVER_PARAMS)}))
        aggregated: list[str] = []

        async def _aggregate(self, query, *a, **kw):
            aggregated.append(str(query))
            return "Заголовок\nфакт\nhttps://example.com/agg"

        monkeypatch.setattr(_sa.SearchAggregator, "search", _aggregate)
        # Детерминизм публикации: тест доказывает ОТСУТСТВИЕ поиска на полном
        # проходе, а не проверяет вероятностную политику exploration. Без
        # этого текущий рандом может отложить инициативу (random_fallback), и
        # прохода до Writer'а не будет вовсе — тогда «0 поисков» ничего не
        # значит. Шов политики не является проверяемой логикой этого теста.
        async def _no_exploration(*a, **kw):
            return (None, None)

        monkeypatch.setattr(_mx, "choose_conversation_alternative",
                            _no_exploration)
        db = DatabaseService(str(tmp_path / "observer_ur_b.db"))
        await db.initialize()
        search = _SearchProvider()
        service = _service(search)
        seen = {"plan": 0, "writer": 0}

        async def _initiative_plan(chat_id, intent_row, *,
                                   correlation_id=None):
            # Решение инициативного L1 — «разговор, внешние факты не нужны».
            seen["plan"] += 1
            return _plan(knowledge_origin="conversation_only",
                         search_intent="not_applicable")

        async def _writer(*a, **kw):
            seen["writer"] += 1
            seen["evidence"] = str(kw.get("evidence") or "")
            return ("инициативный текст", "plain")

        monkeypatch.setattr(service, "plan_initiative_decision",
                            _initiative_plan)
        monkeypatch.setattr(service, "_l2_write_answer", _writer)
        stage = {"calls": 0}
        real_stage = _dx.run_tool_phase

        async def _stage(*a, **kw):
            stage["calls"] += 1
            return await real_stage(*a, **kw)

        monkeypatch.setattr(_dx, "run_tool_phase", _stage)
        bot, verdicts = _ObserverBot(), _ObserverVerdictLLM()
        try:
            base = int(time.time()) - 600
            seed = ["обсуждаем инди-игры", "хедлайнер топ",
                    "сохранение слетело", "что посоветуешь"]
            for i, text in enumerate(seed):
                await db.db.execute(
                    "INSERT INTO smart_messages (user_id, chat_id, text, "
                    "reply_to_id, timestamp, media_type, author_name, "
                    "is_forward, tg_message_id) VALUES (?, ?, ?, NULL, ?, "
                    "'text', 'u', 0, NULL)",
                    (42 + i % 2, CHAT_ID, text, base + i))
            await db.db.commit()
            status = await _obs.observe_tick(
                db, bot=bot, writer_service=service, llm=verdicts,
                trigger="event", only_chat=CHAT_ID)
        finally:
            hot_config.set_config_cache(None)
            chat_params.set_chat_params_cache(None)
            await db.close()
        # Проверка РЕАЛЬНО дошла до инициативного Writer'а (иначе ноль
        # вызовов ничего не значит — прохода могло не быть).
        assert status == "completed"
        assert verdicts.calls >= 1 and seen["plan"] == 1
        assert seen["writer"] == 1, "инициатива не дошла до Writer'а"
        assert bot.sent, "инициатива не дошла до отправки"
        # Ноль поиска по обоим каналам наблюдения.
        assert search.queries == [], (
            f"поиск из проверки Observer: {search.queries}")
        assert aggregated == [], f"поиск через SearchAggregator: {aggregated}"
        assert seen.get("evidence", "") == "", "Writer получил evidence"
        # Ноль — это РЕШЕНИЕ, а не отсутствие возможности: поисковый
        # инструмент доступен ходу (та же схема, что уходит живому L1).
        from services.tool_schemas import active_tools
        assert "execute_web_search" in {
            t["function"]["name"] for t in active_tools(False, False)}
        # Гейт, который держит ноль: у Observer-повода нет claim-запроса,
        # поэтому единый tool-этап не запускается вовсе.
        assert stage["calls"] == 0, "tool-этап исполнялся без требуемых caps"
