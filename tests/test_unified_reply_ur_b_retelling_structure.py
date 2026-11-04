"""UNIFIED-REPLY UR-B — review-fix UR-B-5: приватность СТРУКТУРНАЯ, не словарь.

Находка ревью (UR-B, повторная): правило приватного пересказа было закрытым
списком слов, поэтому два перефраза уходили провайдеру:

  * «Маша ждёт ребёнка на третьем месяце, только между нами» → запрос
    «ждёт ребёнка третьем месяце только между нами»;
  * «она мне шепнула что у неё задержка и она в положении, ни слова подругам».

Решение теперь принимается по СТРУКТУРЕ реплики: если утверждение делается ОБ
УЧАСТНИКЕ чата (подлежащее/тема — местоимение участника или его алиас из
контекста чата) и публичного антецедента (claim-сущность, латиница, имя
собственное внутри фразы, цитата, версия) нет — это личный пересказ, а не
поисковый вопрос: `privacy_blocked`, 0 сетевых вызовов,
`can_claim_verified=False`.

Соседние случаи (публичная сущность + упоминание участника) по-прежнему ищутся:
Tesla, Газпром, курс доллара, «…, спросил Вася».

Тесты идут через настоящий ToolRouter с подменным провайдером, без сети.

TEST-LIFECYCLE: REGRESSION owner=UNIFIED-REPLY/UR-B
"""
import pytest

from services import direct_execution as _dx
from tests.test_unified_reply_ur_b_review_fixes import _run, _search_calls
from tests.test_unified_reply_ur_b_search_first import _SearchProvider, _plan

pytestmark = [pytest.mark.system2]

#: Тексты ровно из находки ревью (не переформулированы).
PROBE_ALIAS = "Маша ждёт ребёнка на третьем месяце, только между нами"
PROBE_PRONOUN = ("она мне шепнула что у неё задержка и она в положении, "
                 "ни слова подругам")


def _assert_blocked(result, search, *, private_text=()):
    assert search.queries == [], "личный пересказ ушёл в поисковик"
    assert result.evidence.search_status == _dx.SEARCH_STATUS_PRIVACY_BLOCKED
    assert result.evidence.search_called is False
    assert result.evidence.search_query == ""
    assert result.evidence.can_claim_verified is False
    assert result.evidence.claim_policy == "claim_forbidden_no_search"
    assert _search_calls(result) == []
    payload = getattr(result.pack, "text", "") or ""
    for chunk in private_text:
        assert chunk.lower() not in payload.lower(), f"личное в payload: {chunk}"


# ── перефразы из находки ревью ───────────────────────────────────────────────


class TestLeakedParaphrasesBlocked:
    @pytest.mark.asyncio
    async def test_alias_subject_paraphrase_makes_no_call(self):
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, PROBE_ALIAS, search,
                            private_terms=("Маша",), required_caps=(
                                "web_search",))
        _assert_blocked(result, search,
                        private_text=("ждёт ребёнка", "между нами"))

    @pytest.mark.asyncio
    async def test_pronoun_paraphrase_makes_no_call(self):
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, PROBE_PRONOUN, search, required_caps=(
            "web_search",))
        _assert_blocked(result, search,
                        private_text=("шепнула", "задержка", "положении"))

    def test_block_comes_from_structure_not_from_topic_words(self):
        """Остаток после вычистки НЕ содержит deny-слов: блок даёт структура.

        Иначе перефразы того же класса («ждёт ребёнка», «задержка») снова
        утекут: словарь тем их не ловит."""
        for text, terms in ((PROBE_ALIAS, ("Маша",)), (PROBE_PRONOUN, ())):
            clean, _ = _dx._strip_private(text, terms)
            assert _dx._private_topic_signal(clean) is False, (
                f"deny-список тем сработал — проверка перестала быть "
                f"структурной: {clean!r}")
            assert _dx._participant_reference(text, terms) is True, text


# ── тот же класс перефразов (другие слова, та же структура) ─────────────────


class TestSameStructureOtherWords:
    @pytest.mark.parametrize("query,private_terms", [
        # алиас — подлежащее утверждения
        ("Петя уволился из банка и переезжает в другой город", ("Петя",)),
        # местоимение 3 лица без антецедента-сущности
        ("ей сказали что её переводят в другой отдел", ()),
        # личное утверждение от первого лица
        ("я вчера перевёз вещи к родителям", ()),
        # предлог + алиас: тема части фразы — участник
        ("у Маши всё хорошо, она согласилась", ("Маши",)),
        # алиас в косвенном падеже — та же тема (не только словарная форма)
        ("у Маши задержка на третьем месяце", ("Маша",)),
    ])
    def test_personal_claim_without_public_anchor_is_blocked(self, query,
                                                             private_terms):
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"), query=query,
            private_terms=private_terms)
        assert task.blocked is True, f"перефраз не заблокирован: {query!r}"
        assert task.blocked_reason == _dx.SEARCH_STATUS_PRIVACY_BLOCKED
        assert task.query == ""


# ── соседние отрицательные контроли: публичная тема ищется ──────────────────


class TestPublicClaimsStillSearch:
    @pytest.mark.parametrize("query,private_terms,expected", [
        ("проверь что нового у Tesla по автопилоту", (), "tesla"),
        ("что слышно про Газпром и дивиденды", (), "газпром"),
        ("какой сейчас курс доллара", (), "доллара"),
        ("какой курс биткоина, спросил Вася", ("Вася",), "биткоина"),
        ("найди мне курс доллара", (), "доллара"),
        # похоже на алиас, но это обычное слово: падежная терпимость не
        # должна превращать «машину» в участника «Маша»
        ("какую машину купить для города", (), "машину"),
        ("объясни мне что такое инфляция", (), "инфляция"),
    ])
    @pytest.mark.asyncio
    async def test_public_topic_makes_exactly_one_call(self, query,
                                                       private_terms, expected):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search, private_terms=private_terms)
        assert len(search.queries) == 1, f"публичный запрос не искался: {query!r}"
        assert expected in search.queries[0].lower()
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK
        assert result.evidence.search_called is True
        for term in private_terms:
            assert term.lower() not in search.queries[0].lower()

    @pytest.mark.asyncio
    async def test_participant_mention_with_public_entity_still_searched(self):
        """Участник назван, но утверждение — про публичную сущность."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/s")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "Маша сказала что SpaceX перенесла запуск",
                            search, private_terms=("Маша",))
        assert len(search.queries) == 1
        sent = search.queries[0].lower()
        assert "spacex" in sent
        assert "маша" not in sent
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.asyncio
    async def test_inflected_alias_is_stripped_from_public_query(self):
        """Алиас в косвенном падеже не уезжает провайдеру (UR-07.1)."""
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/p")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, "Маше понравился новый Tesla", search,
                            private_terms=("Маша",))
        assert len(search.queries) == 1
        sent = search.queries[0].lower()
        assert "tesla" in sent
        assert "маш" not in sent, f"алиас утёк в запрос: {sent!r}"
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK


# ── раунд 3 ревью: прозрачный пред-субъектный прогон ────────────────────────
#
# Находка ревью UR-B (третья): то же утверждение об участнике, но с наречием/
# вводным словом перед подлежащим, снова уходило провайдеру — тема сдвигалась
# на наречие:
#   «Вчера Маша ждёт ребёнка на третьем месяце» → «вчера ждёт ребёнка …»
#   «Слушай, Маша ждёт ребёнка на третьем месяце» → «слушай ждёт ребёнка …»
# Правило: наречия/вводные слова и знаки препинания перед подлежащим
# прозрачны — подлежащее то же («Маша»), приватность та же.

#: Те же две реплики из находки + тот же класс (другие вводные слова).
PREPENDED_LEADS = (
    "Вчера Маша ждёт ребёнка на третьем месяце",
    "Слушай, Маша ждёт ребёнка на третьем месяце",
    "Кстати, Маша ждёт ребёнка на третьем месяце",
    "честно говоря, Маша ждёт ребёнка на третьем месяце",
)


class TestPrependedLeadIsTransparent:
    @pytest.mark.parametrize("query", PREPENDED_LEADS)
    @pytest.mark.asyncio
    async def test_lead_word_before_subject_makes_no_call(self, query):
        search = _SearchProvider("Ответ\nтекст\nhttps://example.com/x")
        plan = _plan(knowledge_origin="open_world",
                     capabilities_needed=["web_search"])
        result = await _run(plan, query, search, private_terms=("Маша",),
                            required_caps=("web_search",))
        _assert_blocked(result, search,
                        private_text=("ждёт ребёнка", "маша"))

    @pytest.mark.parametrize("query", PREPENDED_LEADS)
    def test_topic_stays_on_alias_not_on_lead_word(self, query):
        """Тема — подлежащее-алиас, наречие/пунктуация её не сдвигают."""
        assert _dx._participant_reference(query, ("Маша",)) is True, query
        tokens, topics = _dx._claim_topic_flags(query)
        subject = [token for token, is_topic in zip(tokens, topics)
                   if is_topic and token.lower().startswith("маш")]
        assert subject, f"алиас потерял позицию подлежащего: {query!r}"


# ── раунд 3 ревью: «у нас» в общем вопросе — не утверждение об участнике ────


class TestPossessiveUsIsNotAPersonalClaim:
    @pytest.mark.parametrize("query", [
        "какой курс доллара у нас",
        "у меня есть вопрос, какой сейчас курс доллара",
    ])
    @pytest.mark.asyncio
    async def test_general_question_searches_normally(self, query):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/rate")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search)
        assert len(search.queries) == 1, f"общий вопрос заблокирован: {query!r}"
        assert "доллара" in search.queries[0].lower()
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

    @pytest.mark.parametrize("query", [
        "у меня задержка",
        "что у меня со здоровьем",
        "у Маши задержка на третьем месяце",
    ])
    def test_possessive_personal_assertion_still_blocked(self, query):
        """Притяжательная конструкция не открывает личное утверждение."""
        task = _dx.build_search_query(
            _plan(knowledge_origin="open_world"), query=query,
            private_terms=("Маша",))
        assert task.blocked is True, f"личное ушло в поиск: {query!r}"
        assert task.query == ""


class TestControlPolygonUnchanged:
    """Соседние публичные запросы регрессией не задеты."""

    @pytest.mark.parametrize("query,private_terms,expected", [
        ("Вчера Tesla показала новую модель", ("Маша",), "tesla"),
        ("Маша сказала что SpaceX перенесла запуск", ("Маша",), "spacex"),
        ("какой курс биткоина, спросил Вася", ("Вася",), "биткоина"),
        ("какой сейчас курс доллара", (), "доллара"),
        ("что слышно про Газпром и дивиденды", (), "газпром"),
    ])
    @pytest.mark.asyncio
    async def test_public_requests_still_search(self, query, private_terms,
                                               expected):
        search = _SearchProvider("Заголовок\nфакт\nhttps://example.com/ok")
        plan = _plan(knowledge_origin="open_world")
        result = await _run(plan, query, search, private_terms=private_terms)
        assert len(search.queries) == 1, f"публичный запрос не искался: {query!r}"
        assert expected in search.queries[0].lower()
        assert result.evidence.search_status == _dx.SEARCH_STATUS_OK

