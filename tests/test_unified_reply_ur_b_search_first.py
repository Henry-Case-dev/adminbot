"""UNIFIED-REPLY UR-B — единая tool-фаза, Search-first, ToolEvidence, гигиена.

Покрывает owner-input 2026-11-05 §4 (UR-03/UR-06/UR-07/UR-08) и BGS-01:

  * ось `knowledge_origin`/`search_intent` в L1Plan с серверной нормализацией
    (`open_world|mixed` без intent → `required`), одна схема Direct/Initiative;
  * единый executor (`direct_execution.run_tool_phase`) на существующих
    `run_simple_tools`/`adaptive`/`build_evidence_pack` — реальный tool event,
    а не только `capabilities_needed=["web_search"]`;
  * SILENT/REACT → 0 tool-вызовов; поиск ради отчётности не выполняется;
  * BGS-01: содержательного вето у поиска НЕТ — участник чата, «приватно
    звучащая» тема и отсутствие «публичного якоря» поиск не отменяют;
  * честные статусы empty/timeout/unavailable/contradictory без выдуманного
    источника; ToolEvidence + R17-safe трасса.

Тесты идут через НАСТОЯЩИЙ ToolRouter с подменным поисковым провайдером
(`ToolDeps.search`), без сети.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-B
"""
import asyncio
import json

import pytest

from services import direct_execution as _dx
from services import direct_l1 as _l1
from services.search_aggregator import AllSearchEnginesFailedException
from services.tool_router import ToolContext, ToolDeps, ToolRouter

pytestmark = [pytest.mark.system2]

CHAT_ID = -1001234567890


class _SearchProvider:
    """Подменный поисковый провайдер (SearchAggregator.search-совместимый)."""

    def __init__(self, text: str = "", *, exc=None, delay: float = 0.0):
        self.text = text
        self.exc = exc
        self.delay = delay
        self.queries: list[str] = []

    async def search(self, query, max_symbols=4000, **kw):
        self.queries.append(str(query))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.text


def _plan(**over):
    return _l1.normalize_l1_plan(dict({"action": "reply", "confidence": 0.9,
                                       **over}))


def _schemas(*names):
    return [{"function": {"name": name, "description": name}}
            for name in names]


def _router(search, **deps):
    return ToolRouter(ToolDeps(search=search, memory=object(), **deps))


async def _run(plan, query, search, *, tool_schemas=None, private_terms=(),
               required_caps=(), explicit_request=False,
               capacity_chars=None, emit_trace=False):
    router = _router(search) if not isinstance(search, ToolRouter) else search
    return await _dx.run_tool_phase(
        plan=plan, router=router, ctx=ToolContext(CHAT_ID, query),
        query=query, chat_id=CHAT_ID, correlation_id="corr-ur-b",
        tool_schemas=(_schemas("execute_web_search")
                      if tool_schemas is None else tool_schemas),
        required_caps=required_caps, explicit_request=explicit_request,
        private_terms=private_terms, capacity_chars=capacity_chars,
        emit_trace=emit_trace)


# ── ось знания/поиска: схема и нормализация ─────────────────────────────────


class TestSearchAxisSchema:
    def test_open_world_without_intent_normalized_to_required(self):
        plan = _plan(knowledge_origin="open_world")
        assert plan.knowledge_origin == "open_world"
        assert plan.search_intent == _l1.SEARCH_REQUIRED
        assert plan.search_intent_source == "normalized_open_world"

    def test_mixed_without_intent_normalized_to_required(self):
        assert _plan(knowledge_origin="mixed").search_intent == "required"

    def test_chat_only_not_applicable_preserved(self):
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable")
        assert plan.knowledge_origin == "conversation_only"
        assert plan.search_intent == "not_applicable"
        assert plan.search_intent_source == "llm"

    def test_invalid_values_do_not_invalidate_plan(self):
        plan = _plan(knowledge_origin="dance", search_intent="maybe")
        assert plan is not None
        assert plan.knowledge_origin == ""
        assert plan.search_intent == ""

    def test_identical_schema_for_initiative_path(self):
        """Инициатива парсит тем же `parse_l1_plan` → те же поля/значения."""
        raw = json.dumps({"action": "reply", "knowledge_origin": "mixed"})
        direct = _plan(knowledge_origin="mixed")
        initiative = _l1.parse_l1_plan(raw)
        assert initiative is not None
        assert (initiative.knowledge_origin, initiative.search_intent,
                initiative.search_intent_source) == (
            direct.knowledge_origin, direct.search_intent,
            direct.search_intent_source)

    def test_runtime_policy_and_user_forced_not_demoted(self):
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable")
        axis = _l1.resolve_search_axis(plan, required_caps=("web_search",),
                                       explicit_request=True)
        assert (axis.search_intent, axis.source, axis.user_forced) == (
            "required", "user_forced", True)
        runtime = _l1.resolve_search_axis(plan,
                                          required_caps=("web_search",))
        assert (runtime.search_intent, runtime.source) == (
            "required", "runtime_evidence")


# ── Search-first: реальный tool event, не поле capability ───────────────────


class TestSearchFirstExecution:
    @pytest.mark.asyncio
    async def test_explicit_internet_request_makes_real_call(self):
        search = _SearchProvider(
            "Заголовок\nкурс биткоина вырос на 5%\nhttps://example.com/a")
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable", capabilities_needed=[])
        result = await _run(plan, "проверь в интернете курс биткоина", search,
                            required_caps=("web_search",),
                            explicit_request=True)
        assert search.queries, "явная просьба обязана дать реальный вызов"
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_intent == "required"
        assert result.evidence.source_count == 1
        assert result.evidence.source_ids
        assert result.evidence.source_ids[0].startswith("web:")
        assert result.evidence.can_claim_verified is True

    @pytest.mark.asyncio
    async def test_open_world_without_capability_still_searches(self):
        """Поле capability не единственный повод: ось требует реального события."""
        search = _SearchProvider(
            "Заголовок\nмодель вышла в марте\nhttps://example.com/m")
        plan = _plan(knowledge_origin="open_world", capabilities_needed=[],
                     execution_mode="none")
        result = await _run(plan, "когда вышла новая модель", search)
        assert len(search.queries) == 1
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.required_unmet is False

    @pytest.mark.asyncio
    async def test_beneficial_intent_also_executes(self):
        search = _SearchProvider("Заголовок\nдеталь\nhttps://example.com/d")
        plan = _plan(knowledge_origin="mixed", search_intent="beneficial")
        result = await _run(plan, "расскажи про технологию", search)
        assert len(search.queries) == 1
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_adaptive_mode_still_gets_real_search_first(self):
        class _LLM:
            async def generate(self, messages, **kw):
                return '{"action": "finish", "reason": "done"}'

        search = _SearchProvider(
            "Заголовок\nфакт\nhttps://example.com/f")
        plan = _plan(knowledge_origin="open_world",
                     execution_mode="adaptive_tool_chain",
                     capabilities_needed=["web_search"])
        result = await _dx.run_tool_phase(
            plan=plan, router=_router(search),
            ctx=ToolContext(CHAT_ID, "проверь факт"), query="проверь факт",
            chat_id=CHAT_ID, correlation_id="corr-ur-b", llm=_LLM(),
            tool_schemas=_schemas("execute_web_search"),
            emit_trace=False)
        assert len(search.queries) == 1, "required-поиск обязан быть до L2"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_called is True

    @pytest.mark.asyncio
    async def test_chat_only_joke_no_search(self):
        search = _SearchProvider("не должно вызываться")
        plan = _plan(knowledge_origin="conversation_only",
                     search_intent="not_applicable",
                     capabilities_needed=["web_search"])
        result = await _run(plan, "перескажи нашу шутку про 4 утра", search)
        assert search.queries == []
        assert result.evidence.search_called is False
        assert result.evidence.search_status == _dx.SEARCH_STATUS_SKIPPED
        assert result.evidence.search_skip_reason == "search_intent_not_applicable"
        assert result.evidence.source_count == 0

    @pytest.mark.asyncio
    async def test_silent_react_zero_tool_calls(self):
        for action, reaction in (("silent", None), ("react", "👍")):
            search = _SearchProvider("x")
            plan = _plan(action=action, reaction=reaction,
                         knowledge_origin="open_world",
                         search_intent="required",
                         capabilities_needed=["web_search"])
            result = await _run(plan, "что нового в мире", search)
            assert search.queries == [], f"{action}: поиск ради отчётности"
            assert result.evidence.search_called is False
            assert result.evidence.search_skip_reason == (
                _dx.SKIP_PARTICIPATION_WITHOUT_TEXT)
            assert result.evidence.claim_policy != "claim_allowed"

    @pytest.mark.asyncio
    async def test_missing_search_tool_required_is_unavailable(self):
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "цены на видеокарты", _SearchProvider("x"),
                            tool_schemas=[])
        assert result.evidence.search_status == _dx.SEARCH_STATUS_UNAVAILABLE
        assert result.evidence.search_skip_reason == _dx.SKIP_TOOL_ABSENT
        assert result.evidence.claim_policy == "claim_forbidden_no_search"


# ── BGS-01: содержательного вето нет, есть только гигиена payload ───────────


class TestNoTopicVeto:
    """Тема запроса не блокирует поиск (owner decision BGS-01)."""

    @pytest.mark.parametrize("query,private_terms,expected", [
        # участник чата назван в реплике — поиск всё равно выполняется
        ("У Маши болит голова; какие общие причины?", ("Маша",), "голова"),
        # «приватно звучащая» тема без публичного якоря
        ("беременна третьем месяце какие анализы сдают", (), "беременна"),
        # пересказ личного события — вопрос реально требует внешних данных
        ("Ну, Маша ждёт ребёнка… какие обследования нужны?",
         ("Маша",), "обследования"),
        ("Маша ждёт ребёнка на третьем месяце, только между нами", ("Маша",),
         "ребёнка"),
        # местоимение участника вместо имени
        ("ей сказали что её переводят, какие права у работника", (),
         "права"),
    ])
    @pytest.mark.asyncio
    async def test_formerly_blocked_query_reaches_provider(
            self, query, private_terms, expected):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search, private_terms=private_terms)
        assert len(search.queries) == 1, (
            f"BGS-01: запрос не должен блокироваться темой: {query!r}")
        assert expected in search.queries[0].lower(), (
            f"тема запроса не ушла провайдеру: {search.queries[0]!r}")
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.claim_policy == "claim_allowed"

    @pytest.mark.parametrize("query,private_terms", [
        ("У Маши болит голова; какие общие причины?", ("Маша",)),
        ("я вчера перевёз вещи к родителям, какие документы нужны", ()),
        ("у меня задержка, какие причины бывают", ()),
        ("Пишет Маша: ждёт ребёнка, что советуют врачи", ("Маша",)),
    ])
    def test_query_builder_never_returns_topic_veto(self, query, private_terms):
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"), query=query,
            private_terms=private_terms)
        assert task.skip_reason == "", f"вето по теме осталось: {query!r}"
        assert task.usable is True
        assert task.query

    def test_no_privacy_classifier_left_in_module(self):
        """Ни структурного правила, ни словарей тем, ни якорной проверки."""
        for name in ("_participant_reference", "_has_public_anchor",
                     "_private_topic_signal", "_claim_topic_flags",
                     "_is_general_question", "_possessive_mention",
                     "_verb_form", "_is_finite_predicate",
                     "_PRIVATE_STATUS_WORDS", "_PRIVATE_SECRECY_WORDS",
                     "_PRIVATE_RETELL_WORDS", "_FIRST_SECOND_PERSON",
                     "_THIRD_PERSON", "_LATIN_ANCHOR_RE",
                     "_QUOTED_ANCHOR_RE"):
            assert not hasattr(_dx, name), f"приватный классификатор остался: {name}"
        assert not hasattr(_dx.SearchTask, "blocked")
        assert not hasattr(_dx.SearchTask, "blocked_reason")
        # Историческое значение статуса читается, но новым ходом не выдаётся.
        assert _dx.SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED == "privacy_blocked"
        assert _dx.SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED not in _dx.SEARCH_STATUSES

    @pytest.mark.parametrize("query", [
        "Маша беременна третьем месяце говори никому",
        "она мне писала что у неё задержка",
        "беременна, только между нами",
        "у Маши задержка на третьем месяце",
    ])
    @pytest.mark.asyncio
    async def test_private_sounding_text_never_yields_privacy_blocked(self, query):
        """Даже без полезных терминов статус не «приватная блокировка»."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/x")
        result = await _run(_plan(knowledge_origin="open_world"), query, search,
                            private_terms=("Маша",))
        assert result.evidence.search_status != (
            _dx.SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED)
        assert result.evidence.search_status in _dx.SEARCH_STATUSES
        assert result.evidence.search_skip_reason != "privacy_blocked"


class TestTechnicalGatesStillBlock:
    """Технические гейты сохранены: запрет человека, набор инструментов, сеть."""

    @pytest.mark.asyncio
    async def test_explicit_no_web_request_makes_no_call(self):
        search = _SearchProvider("не должно вызываться")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, "не ищи в интернете, курс биткоина", search,
                            required_caps=("web_search",))
        assert search.queries == [], "явный запрет сети человеком нарушен"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_SKIPPED
        assert result.evidence.search_skip_reason == _dx.SKIP_USER_FORBIDDEN
        assert result.evidence.search_called is False
        assert result.evidence.claim_policy == "claim_forbidden_no_search"

    @pytest.mark.asyncio
    async def test_permission_set_without_tool_blocks(self):
        """RBAC/набор инструментов: инструмент не объявлен → нет вызова."""
        search = _SearchProvider("не должно вызываться")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "курс биткоина", search,
                            tool_schemas=_schemas("get_recent_history"))
        assert search.queries == []
        assert result.evidence.search_status == _dx.SEARCH_STATUS_UNAVAILABLE
        assert result.evidence.search_skip_reason == _dx.SKIP_TOOL_ABSENT

    @pytest.mark.asyncio
    async def test_provider_rate_limit_or_down_is_honest(self):
        search = _SearchProvider(exc=AllSearchEnginesFailedException("quota"))
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "курс биткоина", search)
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_UNAVAILABLE
        assert result.evidence.claim_policy != "claim_allowed"


class TestPayloadHygiene:
    """Гигиена payload: идентификаторы и секреты не уходят, тема — уходит."""

    @pytest.mark.asyncio
    async def test_ids_stripped_names_kept_and_search_happens(self):
        search = _SearchProvider(
            "Заголовок\nкурс вырос\nhttps://example.com/btc")
        query = "какой курс биткоина, спросил Вася 79991234567 @vasya " \
                "t.me/c/123 secret@example.com"
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search,
                            private_terms=("Вася", "vasya"))
        assert len(search.queries) == 1
        sent = search.queries[0].lower()
        assert "биткоин" in sent
        # Имя участника — тема запроса, а не утечка: оно остаётся.
        assert "вася" in sent
        for forbidden in ("79991234567", "t.me", "@",
                          "secret@example.com"):
            assert forbidden not in sent, f"утечка {forbidden!r} в поиск"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_task == query
        assert result.evidence.search_query != query

    @pytest.mark.asyncio
    async def test_participant_name_does_not_corrupt_topic(self):
        """«Макс» не должен превращать «максимальная» в «имальная»."""
        search = _SearchProvider("Заголовок\nцена\nhttps://example.com/gpu")
        query = "какая максимальная цена RTX 4060"
        result = await _run(_plan(knowledge_origin="open_world"), query, search,
                            private_terms=("Макс",))
        assert len(search.queries) == 1, "поиск обязан состояться"
        sent = search.queries[0].lower()
        assert "максимальная" in sent, f"тема испорчена: {sent!r}"
        assert "4060" in sent
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_skip_reason == ""

    @pytest.mark.asyncio
    async def test_participant_name_kept_in_topic(self):
        """«Маска Starship»: имя остаётся в запросе и не блокирует поиск."""
        search = _SearchProvider("Заголовок\nзапуск\nhttps://example.com/starship")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "Маска Starship когда следующий запуск", search,
                            private_terms=("Маска",))
        assert len(search.queries) == 1, "поиск обязан состояться"
        sent = search.queries[0].lower()
        assert "маска" in sent, f"имя вычищено из темы: {sent!r}"
        assert "starship" in sent
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_whole_word_case_does_not_break_neighbours(self):
        """«Максим» не должен резать «максимальный» внутри того же слова."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/w")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "Максим спрашивает максимальный размер памяти",
                            search, private_terms=("Максим",))
        assert len(search.queries) == 1
        sent = search.queries[0].lower()
        assert "максимальный" in sent, f"частичное слово испорчено: {sent!r}"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_reviewer_sveta_paraphrase_keeps_name(self):
        """Репро Reviewer: имя «Света» не выпадает из длинной личной реплики."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/sleep")
        query = ("Света из нашего чата уже третью ночь не спит из-за "
                 "панических атак, какие вообще бывают причины бессонницы "
                 "при тревоге")
        result = await _run(_plan(knowledge_origin="open_world"), query, search,
                            private_terms=("Света",))
        assert len(search.queries) == 1, "поиск обязан состояться"
        sent = search.queries[0].lower()
        assert "света" in sent, f"имя вычищено из темы: {sent!r}"
        assert "причины" in sent or "бессонниц" in sent, (
            f"тема не ушла провайдеру: {sent!r}")
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_reviewer_short_request_keeps_name(self):
        """Репро Reviewer: «поищи про Свету» не обрезается до «поищи про»."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/s")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "поищи про Свету", search,
                            private_terms=("Света",))
        assert len(search.queries) == 1, "поиск обязан состояться"
        sent = search.queries[0].lower()
        assert "свет" in sent, f"имя вычищено из запроса: {sent!r}"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_markers_still_stripped_while_name_stays(self):
        """Обратный контроль: телефон/почта/id/приватная ссылка не уходят."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/m")
        query = ("Света спрашивает про бессонницу 79991234567 "
                 "sekret@example.com 123456789 t.me/c/12345")
        result = await _run(_plan(knowledge_origin="open_world"), query, search,
                            private_terms=("Света",))
        assert len(search.queries) == 1, "поиск обязан состояться"
        sent = search.queries[0]
        lowered = sent.lower()
        assert "света" in lowered, f"имя вычищено из темы: {lowered!r}"
        assert "бессонниц" in lowered
        for marker in ("79991234567", "sekret@example.com", "123456789",
                       "t.me"):
            assert marker not in lowered, f"идентификатор утёк в поиск: {marker}"


        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/s")
        query = ("проверь sk-live-abcdefgh12345678 и ghp_abcdefgh12345678 "
                 "и api_key=deadbeefcafe курс биткоина")
        result = await _run(_plan(knowledge_origin="open_world"), query, search)
        assert len(search.queries) == 1
        sent = search.queries[0]
        for secret in ("sk-live-abcdefgh12345678", "ghp_abcdefgh12345678",
                       "deadbeefcafe"):
            assert secret not in sent, f"секрет утёк в поиск: {secret}"

    def test_strip_is_idempotent_and_keeps_ordinary_words(self):
        """Чистка не трогает обычные слова и не меняется от повторного прогона."""
        text = ("какая максимальная цена RTX 4060, маскарад и василёк, "
                "курс 79991234567 @vasya t.me/c/123 sekret@example.com")
        once, removed = _dx._strip_sensitive(text, ("Макс", "Вася"))
        twice, _ = _dx._strip_sensitive(once, ("Макс", "Вася"))
        assert " ".join(twice.split()) == " ".join(once.split()), (
            f"чистка не идемпотентна: {once!r} → {twice!r}")
        for word in ("максимальная", "маскарад", "василёк", "4060"):
            assert word in once.lower(), f"слово испорчено: {word} в {once!r}"
        assert removed, "идентификаторы так и не убраны"
        for marker in ("79991234567", "@vasya", "t.me", "sekret@example.com"):
            assert marker not in once

    def test_strip_guard_rejects_partial_word_corruption(self):
        """Страховка: обрезка слова распознаётся, цельная замена — нет."""
        assert _dx._payload_pass_is_safe(
            "максимальная цена", "имальная цена") is False
        assert _dx._payload_pass_is_safe(
            "курс 79991234567 биткоин", "курс   биткоин") is True

    def test_alias_parameter_cannot_rewrite_words(self):
        """Даже переданный алиас не меняет текст: имён больше не вычищаем."""
        text = "максимальная цена RTX 4060"
        for term in ("Макс", "максим", "Маска", "Маша"):
            clean, _removed = _dx._strip_sensitive(text, (term,))
            assert clean == text, f"алиас {term!r} испортил запрос: {clean!r}"

    def test_token_prefix_inside_word_is_not_a_secret(self):
        """«task-manager» — не ключ «sk-…»: префикс не режется внутри слова."""
        text = "task-manager настройка и sk-live-abcdefgh12345678"
        clean, _removed = _dx._strip_sensitive(text)
        assert "task-manager" in clean
        assert "sk-live-abcdefgh12345678" not in clean

    @pytest.mark.asyncio
    async def test_whole_chat_is_not_sent(self):
        """В поиск уходит формулировка хода, а не вся переписка."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/w")
        query = "курс биткоина " + ("предыдущая реплика чата " * 200)
        result = await _run(_plan(knowledge_origin="open_world"), query, search)
        assert len(search.queries) == 1
        assert len(search.queries[0]) <= _dx.SEARCH_QUERY_MAX_CHARS
        assert result.evidence.search_task == query

    def test_public_attributed_question_still_searchable(self):
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"),
            query="перескажи что писала Tesla о релизе 2026")
        assert task.usable is True
        assert "tesla" in task.query.lower()
        assert "2026" in task.query

    def test_empty_request_is_a_technical_skip(self):
        """Бессловесный запрос — техническая причина, а не «приватная тема»."""
        task = _dx.build_search_query(_plan(knowledge_origin="open_world"),
                                      query="  79991234567  ")
        assert task.skip_reason == _dx.SKIP_EMPTY_QUERY
        assert task.query == ""


# ── Честность статусов и источников ─────────────────────────────────────────


class TestHonestStatus:
    @pytest.mark.asyncio
    async def test_empty_result_honest(self):
        search = _SearchProvider("")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "курс биткоина", search)
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_EMPTY
        assert result.evidence.source_count == 0
        assert result.evidence.can_claim_verified is False
        assert result.evidence.claim_policy == "claim_forbidden_no_evidence"

    @pytest.mark.asyncio
    async def test_timeout_honest(self, monkeypatch):
        import services.tool_router as tool_router_mod
        monkeypatch.setattr(tool_router_mod, "_SEARCH_TOOL_TIMEOUT", 0.05)
        search = _SearchProvider("поздний ответ", delay=1.0)
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "свежие новости", search)
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_TIMEOUT
        assert result.evidence.source_count == 0
        assert result.evidence.claim_policy == "claim_forbidden_no_evidence"

    @pytest.mark.asyncio
    async def test_provider_down_honest(self):
        search = _SearchProvider(exc=AllSearchEnginesFailedException("down"))
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "доступность API", search)
        assert result.evidence.search_called is True
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_UNAVAILABLE)
        assert result.evidence.source_count == 0
        assert result.evidence.claim_policy != "claim_allowed"

    @pytest.mark.asyncio
    async def test_contradictory_results_not_evidence(self):
        search = _SearchProvider(
            "Источник\nкурс биткоина вырос на 5%\nhttps://example.com/c")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "курс биткоина упал?", search)
        assert result.evidence.search_status == (
            _dx.SEARCH_STATUS_CONTRADICTORY)
        assert result.evidence.evidence_used is False
        assert result.evidence.can_claim_verified is False
        assert result.evidence.claim_policy == "claim_forbidden_no_evidence"
        # источник — реально найденный URL, но он не «подтверждение»
        assert result.evidence.source_ids
        assert all(s.url.startswith("https://example.com/")
                   for s in result.evidence.sources)
        assert any("противоречат" in line
                   for line in (result.pack.limitations if result.pack else []))

    @pytest.mark.asyncio
    async def test_no_invented_sources(self):
        """Все источники — ровно то, что вернул провайдер (никаких выдумок)."""
        text = ("Первый\nсниппет один\nhttps://real.example/1\n\n"
                "Второй\nсниппет два\nhttps://real.example/2")
        search = _SearchProvider(text)
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "сравни два источника", search)
        urls = {s.url for s in result.evidence.sources}
        assert urls == {"https://real.example/1", "https://real.example/2"}
        assert result.evidence.source_count == 2


# ── Evidence transfer + R17-safe трасса ─────────────────────────────────────


class TestEvidenceAndTrace:
    @pytest.mark.asyncio
    async def test_verified_reuse_counts_as_evidence_without_network(self):
        search = _SearchProvider("не должно вызываться")
        plan = _plan(knowledge_origin="open_world")
        reuse = [_dx.EvidenceSource(
            tool="fetch_article", status="ok",
            content="reuse: bitcoin|exists | статья\nбиткоин вырос на 5%",
            total_chars=60, delivered_chars=0)]
        result = await _dx.run_tool_phase(
            plan=plan, router=_router(search),
            ctx=ToolContext(CHAT_ID, "курс биткоина"), query="курс биткоина",
            chat_id=CHAT_ID, correlation_id="corr-ur-b",
            tool_schemas=_schemas("execute_web_search", "fetch_article"),
            prepend_sources=reuse, emit_trace=False)
        assert search.queries == []
        assert result.evidence.search_called is False
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_skip_reason == _dx.SKIP_REUSE
        assert result.evidence.source_count == 1
        assert result.evidence.can_claim_verified is True

    def test_orchestrator_evidence_is_addressable_and_bounded(self):
        src = _dx.EvidenceSource(
            tool="execute_web_search", status="ok", content="д" * 2000,
            total_chars=2000, content_ref="ev:abc123")
        messages = _dx._orchestrator_messages(
            query="запрос " * 400, allowlist=_schemas("execute_web_search"),
            evidence_sources=[src], steps_done=[])
        user = messages[-1]["content"]
        assert "ref=ev:abc123" in user
        snippet = user.split("<<<")[1].split(">>>")[0]
        assert 0 < len(snippet.strip()) <= _dx.ORCHESTRATOR_EVIDENCE_SNIPPET_CHARS
        # Запрос обрезан структурно (не рвёт слово/сущность посередине).
        assert "запрос запрос" in user

    @pytest.mark.asyncio
    async def test_full_source_addressable_beyond_payload(self):
        long_body = "Заголовок\n" + ("важное доказательство " * 200)
        search = _SearchProvider(long_body + "\nhttps://example.com/long")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "проверь длинный факт", search,
                            capacity_chars=600)
        src = result.evidence.sources[0]
        full = result.evidence.full_text(src.content_ref)
        assert len(full) > 600
        assert "важное доказательство" in full
        fragment = result.evidence.fragment(src.content_ref, 80)
        assert 0 < len(fragment) <= 80
        # В payload — отобранный фрагмент под бюджет, с адресом полного текста.
        assert result.pack is not None and result.pack.text
        assert "полный текст: ev:" in result.pack.text

    @pytest.mark.asyncio
    async def test_trace_fields_and_emission_are_private_safe(self, monkeypatch):
        captured = {}

        def _capture(event_name, **fields):
            captured["event_name"] = event_name
            captured["fields"] = fields
            return {"event_name": event_name}

        import services.mca_events as mca_events
        monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
        search = _SearchProvider(
            "Заголовок\nбиткоин вырос\nhttps://example.com/a")
        plan = _plan(knowledge_origin="mixed")
        query = "проверь курс биткоина 79991234567 @vasya"
        result = await _run(plan, query, search,
                            private_terms=("Вася", "vasya"),
                            emit_trace=True)
        evidence = result.evidence
        trace = evidence.trace_fields()
        assert set(trace) == {"search_intent", "search_called", "search_status",
                              "source_ids", "source_count", "search_skip_reason",
                              "evidence_used", "source_dates",
                              "published_at_status"}
        assert trace["search_called"] is True
        assert trace["source_count"] == evidence.source_count == 1
        assert trace["evidence_used"] is True
        # Дата публикации: у выдачи даты нет → честный машинный статус и
        # пустой список дат (никакого подставленного значения).
        assert trace["source_dates"] == []
        assert trace["published_at_status"] == "not_reported"
        assert captured.get("event_name") == "reply_search_evidence"
        payload = json.dumps(captured.get("fields") or {}, ensure_ascii=False)
        for forbidden in ("79991234567", "вася", "vasya", "проверь курс"):
            assert forbidden not in payload, f"приватный текст в трассе: {forbidden}"
