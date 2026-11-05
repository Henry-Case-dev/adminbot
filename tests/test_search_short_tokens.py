"""FC-SHORT-TOKENS — короткие значимые якоря в поисковых запросах
(backlog 05.11.2026). ОФЛАЙН: чистые детерминированные функции, без
LLM/поиска/Telegram.

TEST-LIFECYCLE: CONTRACT owner=FC-SHORT-TOKENS (единый токенизатор)

Контракт:

* `content_terms` (services/search_aggregator.py) — порог длины 2 симв.;
  обозначения с цифрами/латиницей (RTX, 4060, K2) выживают всегда;
* отрицание «не» — НЕ стоп-слово: «почему не работает принтер» обязано
  донести отрицание до запроса;
* служебные слова 1–3 симв. («в», «на», «и», «из», «у»…) отсекаются
  закрытым списком _SHORT_TOKEN_STOPWORDS;
* `factcheck_planner._claim_terms` использует ТОТ ЖЕ токенизатор (свои
  стоп-слова поверх), и короткие якоря доходят до текстов запросов;
* регресс-охрана: короткие термы не делают чужой документ «релевантным»
  в overlap-эвристике is_relevant_result.
"""

from services import factcheck_planner as fsp
from services.search_aggregator import (
    _SHORT_TOKEN_STOPWORDS,
    content_terms,
    is_relevant_result,
)


class TestContentTermsShortTokens:
    """Контракт content_terms: порог 2+, якоря-обозначения, «не»."""

    def test_rtx_and_model_number_reach_terms(self):
        # «какая» — 5 симв., не стоп-слово; RTX (латиница), 4060 (цифры)
        terms = content_terms("какая цена RTX 4060")
        assert "rtx" in terms
        assert "4060" in terms

    def test_negation_ne_survives_as_anchor(self):
        terms = content_terms("почему не работает принтер")
        assert "не" in terms
        assert "принтер" in terms and "работает" in terms

    def test_short_fillers_absent(self):
        terms = content_terms("кот на столе у окна в доме и из чайника")
        assert "на" not in terms
        assert "у" not in terms
        assert "в" not in terms
        assert "и" not in terms
        assert "из" not in terms
        # содержательные слова при этом на месте
        assert "кот" in terms and "столе" in terms and "чайника" in terms

    def test_designation_like_tokens_always_survive(self):
        # одиночная латиница/цифра — обозначение (X, K2→k,2, GPT-4→gpt,4)
        terms = content_terms("модель X 4 против Y 7")
        assert "x" in terms and "y" in terms
        assert "4" in terms and "7" in terms

    def test_single_cyrillic_letter_dropped(self):
        # одиночная кириллица — не обозначение, шум
        assert content_terms("а б в") == []

    def test_ne_is_not_in_stopword_list(self):
        # «не» не имеет права попасть в закрытый список служебных слов
        assert "не" not in _SHORT_TOKEN_STOPWORDS
        assert "no" not in _SHORT_TOKEN_STOPWORDS
        assert "not" not in _SHORT_TOKEN_STOPWORDS

    def test_existing_stopwords_still_apply(self):
        # прежние стоп-слова content_terms сохранены
        terms = content_terms("какой сейчас год этому проекту")
        assert "сейчас" not in terms
        assert "год" not in terms
        assert "этому" not in terms

    def test_dedup_and_order_preserved(self):
        terms = content_terms("принтер не работает не принтер")
        assert terms == ["принтер", "не", "работает"]


class TestClaimTermsSharesTokenizer:
    """factcheck_planner._claim_terms — тот же токенизатор, свои стоп-слова."""

    def test_claim_terms_includes_short_anchors(self):
        terms = fsp._claim_terms("какая цена RTX 4060", limit=8)
        assert "rtx" in terms
        assert "4060" in terms

    def test_claim_terms_negation_survives(self):
        assert "не" in fsp._claim_terms(
            "утверждают, что принтер не работает", limit=8)

    def test_claim_terms_keeps_factcheck_stopwords(self):
        # «что» — стоп-слово factcheck_context._STOPWORDS, не протекает
        terms = fsp._claim_terms("что случилось с байтом", limit=8)
        assert "что" not in terms
        assert "с" not in terms
        assert "байтом" in terms

    def test_query_text_carries_negation_and_designation(self):
        # planner собирает тексты запросов ИЗ термов (_make_query) —
        # отрицание и обозначение обязаны дойти до строки запроса
        claim = "почему не работает принтер RTX 4060"
        terms = fsp._claim_terms(claim, limit=10)
        assert "не" in terms and "rtx" in terms and "4060" in terms


class TestRelevanceOverlapGuard:
    """Короткие термы не ломают overlap-эвристику релевантности."""

    def test_negation_term_alone_is_not_relevance(self):
        terms = content_terms("почему не работает принтер")
        off_topic = "Обзор новых кофеварок этого сезона"
        assert is_relevant_result(off_topic, terms) is False

    def test_printer_doc_still_relevant_with_short_terms(self):
        terms = content_terms("почему не работает принтер")
        doc = "Принтер не работает после обновления — очередь печати зависает"
        assert is_relevant_result(doc, terms) is True
