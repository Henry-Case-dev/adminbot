"""UNIFIED-REPLY UR-B / BGS-01 — у поиска НЕТ содержательного вето.

Решение владельца (BGS-01, 2026-11-05 §0.1/§2): приватное вето на web search
снято целиком — ни `privacy_blocked` для новых ходов, ни структурного
классификатора участника, ни проверки «публичного якоря», ни словарей тем, и
никакой заменяющей классификации/белого списка/маскировщика темы.

Здесь зафиксированы ровно те реплики, которые раньше блокировались (два
перефраза из находки ревью UR-B-5, вводные слова перед подлежащим, личные
утверждения от первого лица, притяжательные конструкции). Новый контракт:
если L1 увидел внешнюю информационную потребность и технические гейты
пройдены — запрос строится и уходит провайдеру.

Остаются только технические гейты (проверяются ниже): прямой запрет сети
человеком, отсутствие инструмента в наборе, выключенный/упавший провайдер,
пустая формулировка. И гигиена payload: идентификаторы и секреты в запрос не
попадают — это фильтр данных, а НЕ вето на тему. Имена и алиасы участников
чата, наоборот, остаются частью формулировки: они и есть тема (BGS-01 §2.4).

Тесты идут через настоящий ToolRouter с подменным провайдером, без сети.

TEST-LIFECYCLE: REGRESSION owner=UNIFIED-REPLY/UR-B/BGS-01
"""
import inspect

import pytest

from services import direct_execution as _dx
from services import evidence_policy as _ep
from tests.test_unified_reply_ur_b_review_fixes import _run, _search_calls
from tests.test_unified_reply_ur_b_search_first import _SearchProvider, _plan

pytestmark = [pytest.mark.system2]

#: Тексты ровно из находок ревью UR-B (не переформулированы).
PROBE_ALIAS = "Маша ждёт ребёнка на третьем месяце, только между нами"
PROBE_PRONOUN = ("она мне шепнула что у неё задержка и она в положении, "
                 "ни слова подругам")
#: Раньше «съезжала» тема: вводное слово/частица перед подлежащим.
PROBE_LEADS = (
    "Вчера Маша ждёт ребёнка на третьем месяце",
    "Ну, Маша ждёт ребёнка на третьем месяце",
    "Хм, Маша ждёт ребёнка на третьем месяце",
    "Пишет Маша: ждёт ребёнка на третьем месяце",
)


def _assert_searched(result, search, *, expected: str):
    """Ровно один реальный вызов; тема ушла провайдеру."""
    assert len(search.queries) == 1, (
        f"BGS-01: запрос обязан уйти провайдеру: {search.queries!r}")
    sent = search.queries[0].lower()
    assert expected in sent, f"тема не ушла провайдеру: {sent!r}"
    assert result.evidence.search_called is True
    assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
    assert result.evidence.claim_policy == "claim_allowed"
    assert result.evidence.search_task  # исходник сохранён вне payload


# ── 1. ранее блокировавшиеся реплики ищутся ─────────────────────────────────


class TestFormerlyBlockedProbesNowSearch:
    @pytest.mark.asyncio
    async def test_alias_subject_paraphrase_searches_topic(self):
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, PROBE_ALIAS, search,
                            private_terms=("Маша",), required_caps=(
                                "web_search",))
        _assert_searched(result, search, expected="ребёнка")
        assert _search_calls(result), "реальный tool event не записан в трассу"

    @pytest.mark.asyncio
    async def test_pronoun_paraphrase_searches_topic(self):
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, PROBE_PRONOUN, search, required_caps=(
            "web_search",))
        _assert_searched(result, search, expected="задержка")

    @pytest.mark.parametrize("query", PROBE_LEADS)
    @pytest.mark.asyncio
    async def test_lead_word_before_subject_does_not_matter(self, query):
        """Вводное слово перед подлежащим больше ничего не решает."""
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, query, search, private_terms=("Маша",),
                            required_caps=("web_search",))
        _assert_searched(result, search, expected="ребёнка")

    @pytest.mark.parametrize("query,kept", [
        ("я вчера перевёз вещи к родителям", "перевёз"),
        ("у меня задержка", "задержка"),
        ("ей сказали что её переводят в другой отдел", "переводят"),
        ("Петя уволился из банка и переезжает в другой город", "петя"),
    ])
    def test_personal_claim_without_anchor_is_a_query(self, query, kept):
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"), query=query,
            private_terms=("Маша", "Петя"))
        assert task.skip_reason == "", f"вето по теме осталось: {query!r}"
        assert task.usable is True
        assert kept in task.query.lower(), (
            f"тема/имя вычищены из формулировки: {task.query!r}")

    @pytest.mark.asyncio
    async def test_attributed_tail_does_not_change_outcome(self):
        """Атрибуция в конце реплики («спросил Вася») — не тема и не запрет."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "какой курс биткоина, спросил Вася", search,
                            private_terms=("Вася",))
        _assert_searched(result, search, expected="биткоина")


#: Широкий корпус ранее блокировавшихся реплик (все раунды ревью UR-B).
#: Ожидаемый фрагмент — содержательный термин, который обязан уйти провайдеру.
FORMERLY_BLOCKED_CORPUS = (
    ("Маша ждёт ребёнка на третьем месяце, только между нами", "ребёнка"),
    ("она мне шепнула что у неё задержка и она в положении, ни слова "
     "подругам", "задержка"),
    ("Петя уволился из банка и переезжает в другой город", "уволился"),
    ("ей сказали что её переводят в другой отдел", "переводят"),
    ("я вчера перевёз вещи к родителям", "перевёз"),
    ("у Маши всё хорошо, она согласилась", "хорошо"),
    ("у Маши задержка на третьем месяце", "задержка"),
    ("Слушай, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Кстати, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("честно говоря, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Так, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Ага, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Эй, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Ну вчера Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Фрр, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Угу ну Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Хм, Маша ждёт ребёнка на третьем месяце", "ребёнка"),
    ("Сказала Маша что ждёт ребёнка на третьем месяце", "ребёнка"),
    ("что у меня со здоровьем", "здоровьем"),
    ("беременна, только между нами", "беременна"),
    ("Маша беременна третьем месяце говори никому", "беременна"),
)


class TestFormerlyBlockedCorpusSearches:
    @pytest.mark.parametrize("query,expected", FORMERLY_BLOCKED_CORPUS)
    @pytest.mark.asyncio
    async def test_corpus_reaches_provider_with_topic(self, query, expected):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, query, search, private_terms=("Маша", "Петя"),
                            required_caps=("web_search",))
        _assert_searched(result, search, expected=expected)
        trace = str(result.evidence.trace_fields())
        assert "privacy" not in trace.lower(), f"вето в трассе: {trace}"
        assert result.evidence.can_claim_verified is True

    @pytest.mark.asyncio
    async def test_empty_result_for_private_text_is_honest_not_blocked(self):
        """Нет выдачи — честная пустота, а не «приватная блокировка»."""
        search = _SearchProvider("")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "у Маши болит голова; какие общие причины", search,
                            private_terms=("Маша",))
        assert result.evidence.search_called is True
        assert result.evidence.search_status == _dx.SEARCH_STATUS_EMPTY
        assert result.evidence.can_claim_verified is False
        assert result.evidence.claim_policy == "claim_forbidden_no_evidence"
        assert "privacy" not in str(result.evidence.trace_fields()).lower()


# ── 2. от прежнего механизма не осталось ни классификатора, ни состояния ────

class TestNoClassifierLeft:
    def test_no_structural_or_vocabulary_privacy_rule(self):
        for name in ("_participant_reference", "_has_public_anchor",
                     "_private_topic_signal", "_private_topic_veto",
                     "_claim_topic_flags", "_is_general_question",
                     "_possessive_mention", "_verb_form",
                     "_is_finite_predicate",
                     "_PRIVATE_STATUS_WORDS", "_PRIVATE_SECRECY_WORDS",
                     "_PRIVATE_RETELL_WORDS", "_FIRST_SECOND_PERSON",
                     "_THIRD_PERSON", "_LATIN_ANCHOR_RE",
                     "_QUOTED_ANCHOR_RE", "_VERSION_ANCHOR_RE"):
            assert not hasattr(_dx, name), (
                f"приватный классификатор/словарь темы остался: {name}")

    def test_search_task_has_no_veto_state(self):
        task = _dx.SearchTask()
        assert not hasattr(task, "blocked")
        assert not hasattr(task, "blocked_reason")
        assert task.skip_reason == ""
        assert task.usable is False          # пустая формулировка — техника

    def test_skip_reasons_are_technical_only(self):
        for name in ("SKIP_USER_FORBIDDEN", "SKIP_EMPTY_QUERY", "SKIP_REUSE",
                     "SKIP_TOOL_ABSENT", "SKIP_NO_TOOLS",
                     "SKIP_INTENT_NOT_APPLICABLE",
                     "SKIP_PARTICIPATION_WITHOUT_TEXT"):
            value = getattr(_dx, name)
            assert value and "privacy" not in value, (name, value)
        assert not hasattr(_dx, "SKIP_PRIVACY")

    def test_privacy_status_is_not_produced_by_new_turns(self):
        assert _dx.SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED == "privacy_blocked"
        assert _dx.SEARCH_STATUS_LEGACY_PRIVACY_BLOCKED not in (
            _dx.SEARCH_STATUSES)
        assert len(set(_dx.SEARCH_STATUSES)) == len(_dx.SEARCH_STATUSES)

    @pytest.mark.parametrize("text,terms,kept", [
        (PROBE_ALIAS, ("Маша",), "маша"),
        (PROBE_PRONOUN, (), "задержка"),
    ])
    def test_payload_stripper_is_hygiene_not_veto(self, text, terms, kept):
        """Имя участника — часть темы: гигиена не вычищает алиасы вовсе."""
        clean, _removed = _dx._strip_sensitive(text, terms)
        assert clean.strip(), "гигиена вычистила реплику целиком"
        assert kept in clean.lower()
        assert "ребёнка" in clean.lower() or "задержка" in clean.lower()

    def test_module_source_never_emits_privacy_blocked(self):
        """В коде остаётся РОВНО одно вхождение — читаемый legacy-код."""
        source = inspect.getsource(_dx)
        assert source.count("privacy_blocked") == 1, (
            "в модуле снова появилась ветка, производящая privacy_blocked")

    def test_policy_layer_has_no_privacy_criterion(self):
        """`evidence_policy.allowed()` больше не спрашивает «приватна ли тема»."""
        assert not hasattr(_ep, "BLOCK_PRIVACY")
        assert "privacy_ok" not in _ep.EvidenceContext.__dataclass_fields__
        ctx = _ep.EvidenceContext(
            rbac_ok=True,
            network_allowed={"web_search": True},
            capabilities={"web_search": (True, "")},
            quota_ok={"web_search": True},
            ssrf_ok={})
        assert _ep.allowed("web_search", ctx) == (True, "")

    def test_policy_technical_blocks_unchanged(self):
        base = dict(capabilities={"web_search": (True, "")},
                    network_allowed={"web_search": True},
                    quota_ok={"web_search": True}, ssrf_ok={})
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            rbac_ok=False, **base)) == (False, _ep.BLOCK_RBAC)
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            user_forbids_external=True, **base)) == (
                False, _ep.BLOCK_EXTERNAL_DISABLED)
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            **dict(base, network_allowed={"web_search": False}))) == (
                False, _ep.BLOCK_EXTERNAL_DISABLED)
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            **dict(base, quota_ok={"web_search": False}))) == (
                False, _ep.BLOCK_QUOTA)
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            **dict(base, capabilities={"web_search": (
                False, _ep.BLOCK_PROVIDER_UNAVAILABLE)}))) == (
                    False, _ep.BLOCK_PROVIDER_UNAVAILABLE)
        assert _ep.allowed("web_search", _ep.EvidenceContext(
            **dict(base, ssrf_ok={"web_search": False}))) == (
                False, _ep.BLOCK_SSRF)


# ── 3. технические гейты сохранены ──────────────────────────────────────────


class TestTechnicalGatesRemain:
    @pytest.mark.asyncio
    async def test_explicit_no_web_request_blocks(self):
        search = _SearchProvider("не должно вызываться")
        result = await _run(_plan(knowledge_origin="open_world",
                                  capabilities_needed=["web_search"]),
                            "не ищи в интернете " + PROBE_ALIAS, search,
                            private_terms=("Маша",),
                            required_caps=("web_search",))
        assert search.queries == []
        assert result.evidence.search_called is False
        assert result.evidence.search_status == _dx.SEARCH_STATUS_SKIPPED
        assert result.evidence.search_skip_reason == _dx.SKIP_USER_FORBIDDEN
        assert result.evidence.search_query == ""
        assert result.evidence.claim_policy == "claim_forbidden_no_search"

    @pytest.mark.asyncio
    async def test_tool_absent_is_honest_unavailable(self):
        search = _SearchProvider("не должно вызываться")
        result = await _run(_plan(knowledge_origin="open_world"),
                            PROBE_ALIAS, search, private_terms=("Маша",),
                            tool_schemas=[{"function": {"name":
                                                        "get_recent_history"}}])
        assert search.queries == []
        assert result.evidence.search_status == _dx.SEARCH_STATUS_UNAVAILABLE
        assert result.evidence.search_skip_reason == _dx.SKIP_TOOL_ABSENT

    @pytest.mark.asyncio
    async def test_wordless_request_is_technical_skip(self):
        """Никаких терминов после гигиены — `empty_query`, а не тема."""
        search = _SearchProvider("не должно вызываться")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "79991234567 @vasya", search,
                            private_terms=("vasya",))
        assert search.queries == []
        assert result.evidence.search_status == _dx.SEARCH_STATUS_SKIPPED
        assert result.evidence.search_skip_reason == _dx.SKIP_EMPTY_QUERY

    @pytest.mark.asyncio
    async def test_silent_and_react_make_no_call(self):
        for action in ("silent", "react"):
            search = _SearchProvider("не должно вызываться")
            result = await _run(_plan(action=action,
                                      knowledge_origin="open_world"),
                                PROBE_ALIAS, search, private_terms=("Маша",))
            assert search.queries == [], action
            assert result.evidence.search_called is False
            assert result.evidence.search_skip_reason == (
                _dx.SKIP_PARTICIPATION_WITHOUT_TEXT)


# ── 4. соседние контроли: публичные запросы не задеты ───────────────────────


class TestPublicRequestsUnchanged:
    @pytest.mark.parametrize("query,private_terms,expected", [
        ("проверь что нового у Tesla по автопилоту", (), "tesla"),
        ("что слышно про Газпром и дивиденды", (), "газпром"),
        ("какой сейчас курс доллара", (), "доллара"),
        ("какой курс биткоина, спросил Вася", ("Вася",), "биткоина"),
        ("найди мне курс доллара", (), "доллара"),
        ("объясни мне что такое инфляция", (), "инфляция"),
        ("Маша сказала что SpaceX перенесла запуск", ("Маша",), "spacex"),
    ])
    @pytest.mark.asyncio
    async def test_public_request_searches_once(self, query, private_terms,
                                                expected):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        result = await _run(_plan(knowledge_origin="open_world"), query,
                            search, private_terms=private_terms)
        _assert_searched(result, search, expected=expected)

    @pytest.mark.asyncio
    async def test_inflected_alias_stays_in_public_query(self):
        """Алиас в косвенном падеже остаётся частью темы, а не вычищается."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/p")
        result = await _run(_plan(knowledge_origin="open_world"),
                            "Маше понравился новый Tesla", search,
                            private_terms=("Маша",))
        _assert_searched(result, search, expected="tesla")
        assert "маше" in search.queries[0].lower()
