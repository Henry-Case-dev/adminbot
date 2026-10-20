"""CFG-07CG — egress-словарь honesty-классов + тест-гарды честности.

Закрывает (тест-гварами, без правок канонов — W3-фриз фактчека цел):

* CFG-07A.3: «проверил — не нашёл подтверждений» допустимо ТОЛЬКО при
  реально состоявшейся проверке; недоступность источников не даёт права
  на вывод о подтверждении/опровержении. Гвард на v2-контуре фактчека
  (моки: атрибуционный промах после реального просмотра контекста,
  no_claim-маршрут, падение поиска/LLM) + renderer-контроль «вердикт
  только из реального CheckedVerdict»;
* CFG-07A.5: прямой вопрос о внутреннем устройстве в явном техническом/
  административном контексте — честное объяснение возможностей; блокировка
  метаречи не подменяет правду (FORBIDDEN-словарь не держит общих слов,
  админ-жанр checkup цел);
* CFG-07D.1: юмор ON/OFF — ни «сейчас сделаю смешно/разбор подъехал/как
  вы просили/аналитик подтянул/в моей справке», юмор выражается репликой;
  допустимый сарказм не удалён (Core/deadpan/жанры целы);
* CFG-07D.2: недоступный источник ≠ «я проверил всё в интернете»;
  метаречь не блокирует честную техническую справку администратору;
* POSITIVE-контроли корпуса PC-01/02/05/06/09/10/11 живы (словарные).

Словарь: services/public_speech_guard.py — единый источник honesty-
классов (ссылки на живые пулы фактчека/samples/checkup, без копий) и
закрытых FORBIDDEN-семей метаречи (корпус 07a1-corpus MB-*).
Машинные артефакты корпуса (FA-*, MB-10/11/12) — территория 07D.5.

TEST-LIFECYCLE: CONTRACT owner=CFG-07CG
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from config.settings import settings
from services import direct_capabilities as caps
from services import mca_humor_craft as hc
from services import public_speech_guard as psg
from services import smartmodule_phrases as ph
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE, CHECKUP_SYSTEM_PROMPT
from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    PERSONALITY_CORE_COMPACT_TEXT,
    PERSONALITY_CORE_FULL_TEXT,
)
from services.factcheck_orchestrator import (
    CheckedVerdict,
    EvidenceMap,
    EvidenceRef,
    FactcheckPresentation,
    run_factcheck,
)
from services.factcheck_renderer import (
    _NO_LINKS_NOTICE,
    render_factcheck,
)
from services.smartmodule_phrases import (
    FACTCHECK_ATTRIBUTION_MISS_PHRASES,
    FACTCHECK_CLARIFY_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
    LLM_ERROR_PHRASES,
)

CHAT_ID = -100777
TARGET_TG = 9200
TRIGGER_TG = 9201

#: Тезис без атрибуции (обычный фактчек-клейм).
CLAIM_PLAIN = "дрожжи — это грибы"
#: Атрибуционный спор: участник есть, реплики-источника в контексте нет.
CLAIM_MISS = "Вася сказал, что в Килякете выпало 500 мм снега за ночь"

#: Backstage-формулы юмора/стиля (07D.1, L376 + альты корпуса).
_HUMOR_BACKSTAGE = (
    "сейчас сделаю смешно", "сейчас будет смешно", "сейчас пошучу",
    "разбор подъехал", "как вы просили", "как заказывали",
    "аналитик подтянул", "в моей справке", "я шучу", "приём юмора",
)

#: Фразы вердикта-подтверждения, недопустимые на отказных маршрутах.
_CONFIRM_CLAIMS = ("подтверждается", "не подтверждается", "нашёл подтверждение",
                   "подтверждено", "опроверг")


# ════════════════════════════════════════════════════════════════════════════
# 1. Словарь: единственный источник, корпус-покрытие, owner-каноны целы
# ════════════════════════════════════════════════════════════════════════════

def test_honesty_classes_reference_live_pools():
    """Honesty-классы ссылаются на ЖИВЫЕ пулы (identity), не на копии:
    правка пула автоматически попадает в класс (single source)."""
    un = psg.HONEST_UNAVAILABLE.sources
    for pool in (ph.SEARCH_ERROR_PHRASES, ph.FACTCHECK_ERROR_PHRASES,
                 ph.LLM_ERROR_PHRASES, ph.YOUTUBE_ERROR_PHRASES,
                 ph.WEB_ERROR_PHRASES, ph.CHECKUP_FALLBACK_PHRASES,
                 ph.CHECKUP_DEAD_PHRASES, ph.CHECKUP_LLM_ERROR_PHRASES,
                 ph.CHAT_ERROR_PHRASES, ph.CHAT_LLM_DOWN_PHRASES,
                 ph.CHAT_LOCK_BUSY_PHRASES, ph.SMARTMODULE_BUSY_PHRASES):
        assert pool in un, pool
    ref = psg.HONEST_REFUSAL.sources
    for pool in (ph.FACTCHECK_NO_CLAIM_PHRASES, FACTCHECK_ATTRIBUTION_MISS_PHRASES,
                 FACTCHECK_CLARIFY_PHRASES, FACTCHECK_EMPTY_CONTEXT_PHRASES,
                 ph.CHAT_MEMORY_FORGOT_NONE_PHRASES):
        assert pool in ref, pool
    assert CHECKUP_FALLBACK_NOTICE in un                    # честный факт фолбэка
    assert _NO_LINKS_NOTICE in psg.HONEST_LIMITATION.sources
    for headline in ("Подтверждается", "Не подтверждается",
                     "Подтверждается частично"):
        assert headline in psg.CONFIRMED.phrases()
    assert "Недостаточно данных для проверки" in psg.HONEST_LIMITATION.phrases()
    assert set(psg.HONESTY_CLASSES) == {
        "honest_limitation", "honest_refusal", "honest_unavailability",
        "confirmed"}


def _corpus() -> dict:
    path = Path(__file__).resolve().parents[1] / psg.CORPUS_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def test_corpus_metatext_families_covered():
    """FORBIDDEN-семьи корпуса (MB-*, кроме машинных MB-10/11/12 — это
    территория 07D.5-guard'а) покрыты словарём: каждая фраза и каждый
    альт детектируются."""
    entries = {e["id"]: e for e in _corpus()["entries"]
               if e.get("cls") == "FORBIDDEN"}
    expected = {"MB-01", "MB-02", "MB-03", "MB-04", "MB-05", "MB-06",
                "MB-07", "MB-08", "MB-09", "MB-13", "MB-14", "MB-15",
                "MB-16", "MB-17"}
    for key in sorted(expected):
        entry = entries[key]
        for marker in [entry["pattern"], *entry.get("alt", ())]:
            probe = f"ну да, {marker}, двигаемся дальше"
            hits = psg.find_backstage_metatext(probe)
            assert hits, (key, marker)


def test_content_context_words_are_not_violations():
    """07C.2/план §6.4: обычные слова в содержательном контексте — не
    нарушение; словарь держит только конкретные backstage-формулы."""
    for text in ("логи сервера чистые, инцидентов нет",
                 "анализ показывает рост нагрузки",
                 "проверка заняла минуту, всё работает",
                 "модуль поиска сейчас недоступен",
                 "инструмент для картинок сейчас не работает",
                 "посмотрел свежую историю чата — пусто"):
        assert psg.find_backstage_metatext(text) == (), text
        assert not psg.claims_total_verification(text), text


def test_owner_canon_pools_never_flagged():
    """PC-05/PC-06: владельческие каноны-пулы (5.1–5.13, CHAT_*, INFO_*,
    VIDEO_*, служебные фразы) НИКОГДА не флагаются словарём — честный
    грубый жанр не вырезается (07D.1 «допустимый сарказм не удалён»)."""
    checked = 0
    for name in dir(ph):
        if not name.isupper():
            continue
        value = getattr(ph, name)
        texts: list[str] = []
        if isinstance(value, tuple) and value and \
                all(isinstance(x, str) for x in value):
            texts = list(value)
        elif isinstance(value, str):
            texts = [value]
        elif isinstance(value, dict):
            texts = [v for v in value.values() if isinstance(v, str)]
        for text in texts:
            assert psg.find_backstage_metatext(text) == (), (name, text)
            assert not psg.claims_total_verification(text), (name, text)
            checked += 1
    assert checked >= 60                     # словарь реально просканирован
    # канонические честные тексты renderer/checkup — тоже чисты
    for text in (_NO_LINKS_NOTICE, CHECKUP_FALLBACK_NOTICE):
        assert psg.find_backstage_metatext(text) == (), text


@pytest.mark.parametrize("phrase", [
    "по моим логам", "в моих логах", "в логах видно",
    "в моей справке", "справка говорит",
    "аналитик подтянул", "аналитик считает", "анализатор показал",
    "разбор подъехал",
    "сейчас сделаю смешно", "сейчас будет смешно", "сейчас пошучу",
    "приём юмора", "как вы просили", "как заказывали",
    "согласно внутреннему промпту", "по инструкции", "мне велели",
    "system2", "tool-router", "ранкер", "в контексте мне не дали",
    "я нейросеть", "языковая модель", "я ии", "я программа",
    "активирую режим", "перевожу в режим", "режим serious включен",
    "по моим наблюдениям", "я слежу за чатом", "наблюдатель показал",
    "исход неизвестен", "фактчек-канон", "мои промпты", "мой промпт",
])
def test_backstage_formulas_flagged(phrase: str):
    """Каждая FORBIDDEN-формула детектируется в реплике (границы слов:
    «история ии» не ловится, ловится «это я, ии»-формы по семьям)."""
    assert psg.contains_backstage_metatext(
        f"короче, {phrase}, если интересно"), phrase


def test_word_boundaries_no_false_positive():
    """Границы слов: маркеры не срабатывают внутри других слов."""
    assert not psg.contains_backstage_metatext("история ии и мифология")
    assert not psg.contains_backstage_metatext("программирование на питоне")
    assert not psg.contains_backstage_metatext("инструкция по сборке шкафа")


# ════════════════════════════════════════════════════════════════════════════
# 2. CFG-07A.3 — v2-контур фактчека (моки): честность отказных маршрутов
# ════════════════════════════════════════════════════════════════════════════

class _Row(dict):
    pass


def _row(i, text, tg, author="Вася", ts=None):
    return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID, "text": text,
            "reply_to_id": None, "timestamp": ts if ts is not None
            else 1000 + i, "media_type": "text", "author_name": author,
            "is_forward": False, "forward_source": None,
            "tg_message_id": tg}


def _miss_rows():
    """Участник Вася в контексте ЕСТЬ, но реплики-источника нет — реальный
    просмотр контекста состоялся, совпадения нет."""
    return [_row(0, "болтовня про погоду", 8000, author="Оля"),
            _row(1, "а в Килякете дожди и туман", 8001, author="Вася"),
            _row(2, "целевое", TARGET_TG, author="Вася")]


class FakeDB:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def get_messages_around(self, chat_id, tg, before, after):
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        return list(self._rows[-limit:]) if limit else []

    async def get_smart_message_origin_block(self, chat_id, tg):
        raise RuntimeError("no origin row")


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class FakeBot:
    id = 862000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class SpyService:
    """Фиксирует вызовы проверки; опционально падает (сеть/LLM)."""

    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.check_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_calls.append({"target_text": target_text})
        if self.exc is not None:
            raise self.exc
        return "Тезис подтверждается частично по найденным источникам."


class SpyAggregator:
    def __init__(self):
        self.searches = []

    async def search(self, query, max_symbols=2500):
        self.searches.append(query)
        return "выдача https://example.org/x"


def _req(claim: str):
    from services.factcheck_orchestrator import FactcheckRequest
    return FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text=claim, kind="reply")


@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _assert_honest_failure(text: str):
    """Реплика отказного маршрута: честная, без вердикта и без метаречи."""
    assert psg.honest_failure_is_allowed(text)
    low = text.lower()
    for claim in _CONFIRM_CLAIMS:
        assert claim not in low, (claim, text)
    assert psg.find_backstage_metatext(text) == ()
    assert not psg.claims_total_verification(text)


@pytest.mark.asyncio
async def test_attribution_miss_after_real_check_is_honest_refusal(v2_on):
    """07A.3: контекст РЕАЛЬНО просмотрен (участник найден, реплики нет) →
    честный отказ «не нашёл» из пула; проверки и внешнего поиска нет."""
    agg = SpyAggregator()
    svc = SpyService()
    # Наблюдение 1 review-07cg: SpyAggregator инжектится в retrieval-шов
    # run_factcheck (getattr(service, "aggregator")) — ассерт ниже связан
    # с реальным агрегатором, а не пустышкой.
    svc.aggregator = agg
    bot = FakeBot()
    await run_factcheck(_req(CLAIM_MISS), service=svc,
                        db=FakeDB(rows=_miss_rows()), bot=bot,
                        cache=FakeCache())
    assert svc.check_calls == []             # платная проверка не начиналась
    assert agg.searches == []                # внешний поиск тоже (privacy 06G.3)
    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert text in FACTCHECK_ATTRIBUTION_MISS_PHRASES
    assert psg.is_honest_refusal(text)
    _assert_honest_failure(text)


@pytest.mark.asyncio
async def test_no_claim_route_is_honest_refusal(v2_on, monkeypatch):
    """07A.3: тезиса нет ПОСЛЕ изучения контекста → короткая честная
    реплика без псевдопроверки (пул FACTCHECK_NO_CLAIM — класс honest_refusal)."""
    from services import factcheck_suitability as fsg
    decision = fsg.SuitabilityDecision(
        decision=fsg.DECISION_NO_CLAIM, claim_type="personal_prediction",
        claim_items=(), scope="none", reason_code="personal_prediction",
        confidence=0.9, target_ref={"chat_id": CHAT_ID})

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, None

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)
    svc = SpyService()
    bot = FakeBot()
    await run_factcheck(_req(CLAIM_PLAIN), service=svc, db=FakeDB(),
                        bot=bot, cache=FakeCache())
    assert svc.check_calls == []             # проверка не стартовала
    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert text in FACTCHECK_NO_CLAIM_PHRASES
    assert psg.is_honest_refusal(text)
    _assert_honest_failure(text)


@pytest.mark.asyncio
async def test_search_failure_is_honest_unavailability_not_verdict(
        v2_on, monkeypatch):
    """07A.3/07D.2: источники недоступны → честная недоступность из пула
    5.4b; НИКАКОГО вывода о подтверждении/опровержении."""
    from services import factcheck_suitability as fsg
    from services.search_aggregator import AllSearchEnginesFailedException
    decision = fsg.SuitabilityDecision(
        decision=fsg.DECISION_NEEDS_CONTEXT, claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": CHAT_ID})

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, None

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)
    svc = SpyService(exc=AllSearchEnginesFailedException())
    bot = FakeBot()
    await run_factcheck(_req(CLAIM_PLAIN), service=svc, db=None,
                        bot=bot, cache=FakeCache())
    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert text in FACTCHECK_ERROR_PHRASES
    assert psg.is_honest_unavailability(text)
    _assert_honest_failure(text)


@pytest.mark.asyncio
async def test_llm_failure_is_honest_unavailability(v2_on, monkeypatch):
    """07A.3: LLM недоступна → честный пул 5.5, без выдуманного вердикта."""
    from services import factcheck_suitability as fsg
    from services.llm_client import LLMError
    decision = fsg.SuitabilityDecision(
        decision=fsg.DECISION_NEEDS_CONTEXT, claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": CHAT_ID})

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, None

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)
    svc = SpyService(exc=LLMError("llm down"))
    bot = FakeBot()
    await run_factcheck(_req(CLAIM_PLAIN), service=svc, db=None,
                        bot=bot, cache=FakeCache())
    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert text in LLM_ERROR_PHRASES
    assert psg.is_honest_unavailability(text)
    _assert_honest_failure(text)


def test_confirmed_verdict_only_from_real_check():
    """07A.3-positive: проверка состоялась (CheckedVerdict+EvidenceMap) →
    «Подтверждается» разрешён; без вердикта/с неизвестным enum renderer
    заголовок НЕ выдумывает; insufficient_evidence — честное ограничение."""
    pres = FactcheckPresentation(
        text="Тезис подтверждается двумя независимыми источниками.")
    verdict = CheckedVerdict(
        verdict_text=pres.text, route="envelope_temporal",
        factual_verdict="supported",
        evidence=EvidenceMap(
            refs=(EvidenceRef("ev-1", "https://example.org/x",
                              "подтверждение"),),
            allowlist=("ev-1",)))
    out = render_factcheck(pres, verdict)
    assert "<b>Подтверждается</b>" in out.text
    # «нашёл подтверждение» после реального поиска не является нарушением
    assert psg.find_backstage_metatext(out.text) == ()
    assert not psg.claims_total_verification(out.text)
    # без вердикта заголовка нет (renderer не выдумывает проверку)
    plain = render_factcheck(pres, None)
    assert "<b>" not in plain.text
    # неизвестный enum — заголовка нет
    bogus = dataclasses.replace(verdict, factual_verdict="какая-то хрень")
    assert "<b>" not in render_factcheck(pres, bogus).text
    # недостаточно данных — честное ограничение, а не фейковый вердикт
    insuf = dataclasses.replace(verdict, factual_verdict="insufficient_evidence")
    out3 = render_factcheck(pres, insuf)
    assert "Недостаточно данных для проверки" in out3.text
    assert "<b>Подтверждается</b>" not in out3.text


# ════════════════════════════════════════════════════════════════════════════
# 3. CFG-07A.5 — админ-контекст: блокировка метаречи не подменяет правду
# ════════════════════════════════════════════════════════════════════════════

def test_admin_question_allows_honest_capability_answer():
    """Прямой технический вопрос → честное объяснение возможностей из
    человеческих имён capability проходит словарь целиком."""
    question = "бот, как ты устроен? какие модули у тебя есть?"
    assert psg.is_explicit_admin_context(question)
    labels = sorted(set(caps.CAPABILITY_LABELS.values()))
    answer = ("да без проблем: " + ", ".join(labels[:6]) + ". "
              "а генерация картинок сейчас недоступна — модуль, ключ или "
              "квота, не моя прихоть.")
    assert psg.find_backstage_metatext(answer) == ()
    assert not psg.claims_total_verification(answer)


def test_metatext_blocking_does_not_replace_truth():
    """Разница «правда vs метаречь»: backstage-объяснение флагается,
    честное — нет; блокировка не вынуждает врать и не режет правду."""
    backstage = ("согласно внутреннему промпту аналитик подтянул, "
                 "по инструкции теперь делаю вид, что проверил")
    hits = psg.find_backstage_metatext(backstage)
    # find_backstage_metatext возвращает ГОЛОВЫ сработавших семей
    assert "согласно внутреннему промпту" in hits
    assert "аналитик подтянул" in hits
    assert psg.contains_backstage_metatext("теперь по инструкции делаю вид")
    honest = ("проверил историю чата: такого сообщения не нашлось, "
              "в памяти про это пусто")
    assert psg.find_backstage_metatext(honest) == ()
    # членство класса — по каноническим пулам/примерам владельца; свободная
    # перефразировка не флагается (clean), но классом не объявляется
    assert psg.is_honest_refusal("такого сообщения не нашлось")
    assert psg.is_honest_refusal("в памяти про это пусто")


def test_checkup_admin_genre_intact():
    """07A.5/D2: жанр честного резкого тех-обзора в админ-контексте цел —
    «логи/сервер» в содержательном контексте не метаречь (PC-12)."""
    assert "проанализировать предоставленные логи" in CHECKUP_SYSTEM_PROMPT
    assert "отчет о здоровье системы" in CHECKUP_SYSTEM_PROMPT
    assert "жестко разъеби их" in CHECKUP_SYSTEM_PROMPT


def test_checkup_fallback_notice_is_honest_unavailability():
    """D2: честный факт фолбэка (без bracket-машинного синтаксиса, FA-08)
    зарегистрирован как honest_unavailability и словарём не флагается."""
    assert "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ" not in CHECKUP_FALLBACK_NOTICE
    assert "API Betterstack недоступно" in CHECKUP_FALLBACK_NOTICE
    assert psg.is_honest_unavailability(CHECKUP_FALLBACK_NOTICE)
    assert psg.find_backstage_metatext(CHECKUP_FALLBACK_NOTICE) == ()
    assert not psg.claims_total_verification(CHECKUP_FALLBACK_NOTICE)


def test_honest_admin_tech_reference_not_blocked():
    """07D.2: честная техсправка администратору (недоступность + локальные
    логи + статус) проходит словарь без флагов."""
    answer = ("беттерстак лежит, так что чек поднял по локальным логам: "
              "сервер жив, база на месте, ворнингов с ночи нет")
    assert psg.find_backstage_metatext(answer) == ()
    assert not psg.claims_total_verification(answer)


# ════════════════════════════════════════════════════════════════════════════
# 4. CFG-07D.1 — юмор ON/OFF: без backstage-режиссуры, сарказм цел
# ════════════════════════════════════════════════════════════════════════════

def test_humor_pools_have_no_backstage_direction():
    """Пулы юмора (5 техник + рамка) и Personality Core не содержат
    закулисной режиссуры и деклараций шутки — юмор выражается репликой."""
    texts = [hc.HUMOR_CRAFT_GUARD,
             *hc.TECHNIQUE_TEXTS.values(),
             PERSONALITY_CORE_FULL_TEXT, PERSONALITY_CORE_COMPACT_TEXT]
    assert len(texts) >= 8
    for text in texts:
        low = str(text).casefold()
        for phrase in _HUMOR_BACKSTAGE:
            assert phrase not in low, phrase
        assert psg.find_backstage_metatext(text) == ()
    # рамка ремесла прямо запрещает декларацию (юмор = сама реплика)
    assert "Не объясняй шутку и не называй приём" in hc.HUMOR_CRAFT_GUARD


@pytest.mark.asyncio
async def test_humor_on_renders_clean_layer(monkeypatch):
    """Юмор ON: слой приёма рендерится, чист от метаречи; 0 LLM."""
    monkeypatch.setattr("services.mca_gates.humor_craft_enabled",
                        lambda: True)
    monkeypatch.setattr("services.chat_params.get_chat_params_cache",
                        lambda: None)
    from services import hot_config
    monkeypatch.setattr(hot_config, "get", lambda key, default=None: None)
    ref = await hc.resolve_ref(chat_id=505, comic_strategy="deadpan")
    assert ref is not None and ref.enabled and ref.technique == "deadpan"
    assert ref.text
    assert "Ничего не объясняй и не подсказывай, что это шутка" in ref.text
    low = ref.text.casefold()
    for phrase in _HUMOR_BACKSTAGE:
        assert phrase not in low, phrase
    assert psg.find_backstage_metatext(ref.text) == ()


@pytest.mark.asyncio
async def test_humor_gate_off_renders_nothing(monkeypatch):
    """Юмор OFF (ось gates): слой не рендерится вообще — Core не тронут."""
    monkeypatch.setattr("services.mca_gates.humor_craft_enabled",
                        lambda: False)
    ref = await hc.resolve_ref(chat_id=505, comic_strategy="deadpan")
    assert ref is not None and ref.enabled is False
    assert not ref.text
    assert ref.skip_reason == "humor_disabled"


@pytest.mark.asyncio
async def test_humor_owner_toggle_off_disables_layer(monkeypatch):
    """Юмор ON, но toggle владельца OFF (humor.craft.enabled=false) →
    приём не рендерится, честная причина в skip_reason."""
    monkeypatch.setattr("services.mca_gates.humor_craft_enabled",
                        lambda: True)
    monkeypatch.setattr("services.chat_params.get_chat_params_cache",
                        lambda: None)
    from services import hot_config
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None:
            {"enabled": False} if key == "humor.craft" else default)
    ref = await hc.resolve_ref(chat_id=505, comic_strategy="deadpan")
    assert ref.enabled is False and not ref.text
    assert ref.skip_reason == "humor_disabled"


def test_allowed_sarcasm_not_removed():
    """Допустимый сарказм/резкость не удалён чисткой: Core, deadpan,
    честный слив Direct, админ-жанр checkup."""
    assert "язвительность" in PERSONALITY_CORE_COMPACT_TEXT
    assert "непристойный юмор" in PERSONALITY_CORE_COMPACT_TEXT
    assert "остроумие" in PERSONALITY_CORE_FULL_TEXT
    assert "Ничего не объясняй" in hc.technique_text("deadpan")
    assert ("Признай косяк в саркастичной манере, но оставайся в рамках "
            "фактов.") in CHAT_SYSTEM_PROMPT
    assert "жестко разъеби их" in CHECKUP_SYSTEM_PROMPT
    assert "поиздевайся" in CHECKUP_SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# 5. CFG-07D.2 — недоступность ≠ «я проверил всё в интернете»
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text", [
    "я проверил всё в интернете — так что не спорь",
    "проверил весь интернет, такого нигде нет",
    "перерыл весь интернет и не нашёл ни одного пруфа",
    "обрыл всю паутину, тишина",
])
def test_total_verification_claim_detected(text: str):
    assert psg.claims_total_verification(text)


@pytest.mark.parametrize("text", [
    "проверил — не нашёл подтверждений",
    "нашёл подтверждение в двух источниках",
    "проверил по трём ссылкам — сходится",
    "пруфов в сети не нашлось",
    "пересчитал твои цифры, ошибка в третьем шаге",
])
def test_bounded_check_phrases_not_overclaim(text: str):
    """Реальная ограниченная проверка/честный отказ — НЕ overclaim."""
    assert not psg.claims_total_verification(text), text
    assert not psg.contains_backstage_metatext(text), text


def test_unavailable_source_never_becomes_total_check():
    """Все зарегистрированные честные пулы (отказ/недоступность/ограничение)
    не содержат overclaim-заявлений и backstage-формул — классы и словарь
    FORBIDDEN непересекаются (structural disjoint)."""
    for klass in (psg.HONEST_REFUSAL, psg.HONEST_UNAVAILABLE,
                  psg.HONEST_LIMITATION, psg.CONFIRMED):
        for phrase in klass.phrases():
            assert not psg.claims_total_verification(phrase), phrase
            assert psg.find_backstage_metatext(phrase) == (), phrase


# ════════════════════════════════════════════════════════════════════════════
# 6. POSITIVE-контроли корпуса (словарные PC — живы)
# ════════════════════════════════════════════════════════════════════════════

def test_positive_controls_alive_dictionary():
    """PC-01/PC-02/PC-09/PC-11: честные примеры владельца зарегистрированы
    в классах и проходят словарь; PC-05/06 — test_owner_canon_pools_never_flagged."""
    assert "проверил — не нашёл подтверждений" \
        in psg.HONEST_LIMITATION.examples            # PC-01 (L343)
    assert "такого сообщения не нашлось" \
        in psg.HONEST_REFUSAL.examples               # PC-02 (L344)
    assert "эта часть сейчас недоступна" \
        in psg.HONEST_LIMITATION.examples            # PC-09
    assert "нашёл подтверждение" in psg.CONFIRMED.examples   # L377
    for sample in ("проверил — не нашёл подтверждений",
                   "такого сообщения не нашлось",
                   "эта часть сейчас недоступна",
                   "источник не ответил"):
        assert psg.find_backstage_metatext(sample) == (), sample
        assert not psg.claims_total_verification(sample), sample
    # PC-11: админ-вопрос распознан, честный ответ разрешён
    assert psg.is_explicit_admin_context("что ты умеешь, бот?")
    assert psg.is_explicit_admin_context("какие функции у тебя есть?")
