"""CFG-07C-G — словарь egress-классов public_speech_guard.

ЕДИНЫЙ ИСТОЧНИК honesty-классов («честное ограничение / честный отказ /
честная недоступность / подтверждённый вердикт») и FORBIDDEN-словаря
метаречи для тест-гардов CFG-07A.3/.5, CFG-07D.1/.2
(tests/test_cfg07_egress_dictionary.py) и будущего guard'а на точке
outbound (07C.1–.6 — интеграция на delivery-швах, отдельная волна;
этот файл — её основа по cfg-07-build-plan.md §3 «Переиспользовать»).

Границы словаря (07A.7 — НЕ растущий black-list):

* honesty-классы НЕ копируют тексты пулов — ссылаются на живые пулы
  smartmodule_phrases / factcheck_renderer / checkup_prompts как на
  единственные источники (фраза, добавленная в пул, автоматически
  попадает в класс; гарды сверяют идентичность объектов);
* FORBIDDEN-словарь — закрытые семьи метаречи владельца (корпус
  07a1-corpus MB-*, аддендум L342/L345/L376/L377); расширение = осознанная
  правка с источником, а не авто-рост по инцидентам;
* обычные слова «лог/анализ/проверка/модуль/инструмент» в содержательном
  контексте НЕ нарушение (07C.2, план §6.4) — словарь держит только
  конкретные backstage-формулы;
* прямой вопрос о внутреннем устройстве в явном техническом/админ
  контексте разрешает честное объяснение возможностей (07A.5) — блокировка
  метаречи не подменяет правду;
* каноны фактчека/промптов не трогаются (W3-фриз CFG-06); модуль —
  read-only проекция + детерминированные предикаты, 0 LLM-вызовов;
  машинные артефакты корпуса (FA-*) — территория 07D.5-guard'а;
* предикаты применяются к ОТВЕТАМ модели (реплики, fallback-фразы),
  НЕ к байтам канонов: каноны легитимно содержат запреты-примеры
  (блок ANTI_BOT перечисляет запрещённые самоописания дословно).
"""
from __future__ import annotations

import dataclasses
import re

from services import smartmodule_phrases as ph
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
from services.factcheck_renderer import _NO_LINKS_NOTICE, _VERDICT_HEADLINE

#: Корпус 07A-1 — source of record словаря (FORBIDDEN/SOURCE_FIX/POSITIVE).
CORPUS_PATH = "plans/features/cfg/evidence/cfg-07a/07a1-corpus.json"


# ═══════════════════════════════════════════════════════════════════════════
# Honesty-классы (POSITIVE-словарь; пулы — живые ссылки, не копии)
# ═══════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass(frozen=True)
class HonestyClass:
    """Класс честного высказывания: условие допустимости + живые источники.

    ``sources`` — ссылки на живые пулы (tuple[str, ...]) и одиночные
    канонические фразы; копий текстов здесь нет (single source of truth).
    """

    key: str
    title: str
    condition: str
    sources: tuple = ()
    examples: tuple = ()          # PC-* примеры владельца (НЕ пулы)

    def phrases(self) -> tuple[str, ...]:
        out: list[str] = []
        for src in self.sources:
            if isinstance(src, str):
                out.append(src)
            else:
                out.extend(src)
        return tuple(out)


#: Честное ограничение: проверка/рендер состоялись, но полного ответа нет.
HONEST_LIMITATION = HonestyClass(
    key="honest_limitation",
    title="Честное ограничение",
    condition=("реальная работа выполнена, но результата/ссылок недостаточно: "
               "сообщить ограничение можно и нужно (07A.3), без вывода "
               "внутреннего механизма"),
    sources=(_NO_LINKS_NOTICE,
             _VERDICT_HEADLINE.get("insufficient_evidence", "")),
    examples=("проверил — не нашёл подтверждений",       # PC-01 (L343)
              "эта часть сейчас недоступна",             # PC-09
              "источник не ответил"),                    # PC-09 alt
)

#: Честный отказ: реальная проверка/поиск состоялись — результата нет.
HONEST_REFUSAL = HonestyClass(
    key="honest_refusal",
    title="Честный отказ",
    condition=("проверка РЕАЛЬНО состоялась (контекст изучен, история "
               "перечитана) — «не нашёл» допустимо; домыслы и приписки нет"),
    sources=(ph.FACTCHECK_NO_CLAIM_PHRASES,              # после изучения контекста
             ph.FACTCHECK_CLARIFY_PHRASES,
             ph.FACTCHECK_ATTRIBUTION_MISS_PHRASES,      # 06G.3: перечитал — не нашёл
             ph.FACTCHECK_EMPTY_CONTEXT_PHRASES,
             ph.SEARCH_EMPTY_QUERY_PHRASES,
             ph.CHAT_MEMORY_FORGOT_NONE_PHRASES,
             ph.CHAT_MEMORY_CMD_DENIED_PHRASES,
             ph.VIDEO_MEDIA_EMPTY_PHRASES,
             ph.VIDEO_NO_SPEECH_PHRASES),
    examples=("такого сообщения не нашлось",             # PC-02 (L344)
              "в памяти про это пусто"),                 # PC-02 alt
)

#: Честная недоступность: источник/сервис/LLM не ответили — проверки НЕ было.
HONEST_UNAVAILABLE = HonestyClass(
    key="honest_unavailability",
    title="Честная недоступность",
    condition=("источник недоступен — говорим о недоступности, а НЕ "
               "выдаём вердикт/подтверждение (07D.2); владельческий жанр "
               "пулов сохранён (PC-05/PC-06 — NEVER flag)"),
    sources=(ph.SEARCH_ERROR_PHRASES,                    # 5.4 «интернет сдох»
             ph.FACTCHECK_ERROR_PHRASES,
             ph.LLM_ERROR_PHRASES,
             ph.YOUTUBE_ERROR_PHRASES,
             ph.YOUTUBE_AGE_RESTRICTED_PHRASES,
             ph.WEB_ERROR_PHRASES,
             ph.VIDEO_MEDIA_UNAVAILABLE_PHRASES,
             ph.VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES,
             ph.CHECKUP_FALLBACK_PHRASES,
             ph.CHECKUP_DEAD_PHRASES,
             ph.CHECKUP_LLM_ERROR_PHRASES,
             ph.CHAT_ERROR_PHRASES,
             ph.CHAT_LLM_DOWN_PHRASES,
             ph.CHAT_LOCK_BUSY_PHRASES,
             ph.SMARTMODULE_BUSY_PHRASES,
             ph.CHAT_COOLDOWN_PHRASES,
             ph.THROTTLE_PHRASES,
             CHECKUP_FALLBACK_NOTICE),                   # честный факт фолбэка (D2)
)

#: Подтверждённый вердикт: ТОЛЬКО по реальному прогону с доказательствами.
CONFIRMED = HonestyClass(
    key="confirmed",
    title="Подтверждённый вердикт",
    condition=("допустим ТОЛЬКО когда проверка реально состоялась: "
               "enum-вердикт из CheckedVerdict + EvidenceMap; renderer "
               "не выдумывает заголовок без вердикта (W5)"),
    sources=(_VERDICT_HEADLINE.get("supported", ""),
             _VERDICT_HEADLINE.get("refuted", ""),
             _VERDICT_HEADLINE.get("mixed", "")),
    examples=("нашёл подтверждение",),                   # L377: после реального поиска
)

#: Единый словарь классов (ключ → класс).
HONESTY_CLASSES: dict[str, HonestyClass] = {
    c.key: c for c in
    (HONEST_LIMITATION, HONEST_REFUSAL, HONEST_UNAVAILABLE, CONFIRMED)
}


# ═══════════════════════════════════════════════════════════════════════════
# FORBIDDEN-словарь метаречи (закрытые семьи; корпус MB-01..09/13..17 + L342)
# ═══════════════════════════════════════════════════════════════════════════

#: Семьи (головная фраза + альты из корпуса/аддендума). Подстрочное
#: совпадение с границами слов; регистр не важен.
_BACKSTAGE_FAMILIES: tuple[tuple[str, ...], ...] = (
    # MB-01: «в логах/логи» как самопрезентация
    ("по моим логам", "в моих логах", "в логах видно"),
    # MB-02: «справка» как источник самопрезентации
    ("в моей справке", "справка говорит"),
    # MB-03: вымышленный «аналитик»
    ("аналитик подтянул", "аналитик считает", "анализатор показал"),
    # MB-04: закулисная режиссура разбора (тизер вместо самого разбора)
    ("разбор подъехал", "разбор готов"),
    # MB-05 + L342/L335: декларация шутки вместо самой шутки (07D.1)
    ("сейчас сделаю смешно", "сейчас будет смешно", "сейчас пошучу",
     "сейчас напишу смешно", "сейчас сделаю ржачно"),
    # MB-06: самоименование приёма в ответе
    ("приём юмора",),
    # MB-07: «выполнение заказа» вместо разговора
    ("как вы просили", "как заказывали"),
    # MB-08 + L342: ссылка на внутренние инструкции
    ("согласно внутреннему промпту", "по инструкции", "мне велели"),
    # MB-09: внутренние механики (System2/tool-router/ранкер)
    ("system2", "system 2", "tool-router", "tool router", "ранкер",
     "в контексте мне не дали"),
    # MB-13: самоописание «я не человек» (контроль ANTI_BOT-канона)
    ("я нейросеть", "языковая модель", "я ии", "я программа"),
    # MB-14: нарратив маршрутизации/режимов
    ("активирую режим", "перевожу в режим", "режим serious включен"),
    # MB-15: наблюдательская механика в обычной беседе (админ-вопрос — 07A.5)
    ("по моим наблюдениям", "я слежу за чатом", "наблюдатель показал"),
    # MB-16: служебный маркер эпизодов как самостоятельный ответ
    ("исход неизвестен",),
    # MB-17: самоссылка на промпты/каноны
    ("фактчек-канон", "мои промпты", "мой промпт", "мои инструкции"),
)

_CYR = "a-zа-яё"


def _marker_re(marker: str) -> re.Pattern:
    """Маркер с границами слов (кириллица/латиница): «история ии» не ловит
    «я ии», «ранкер» внутри другого слова не срабатывает."""
    return re.compile(rf"(?<![{_CYR}]){re.escape(marker)}(?![{_CYR}])",
                      re.IGNORECASE)


_MARKERS: tuple[tuple[str, ...], tuple[re.Pattern, ...]] = tuple(
    (fam, tuple(_marker_re(m) for m in fam))
    for fam in _BACKSTAGE_FAMILIES)

#: Сработавший маркер → семья (для сообщений гардов).
_MARKED: tuple[tuple[tuple[re.Pattern, ...], str], ...] = tuple(
    (res, fam[0]) for fam, res in _MARKERS)


def find_backstage_metatext(text) -> tuple[str, ...]:
    """Головные фразы FORBIDDEN-семей, найденные в тексте (пусто — чисто)."""
    body = str(text or "")
    hits: list[str] = []
    for res, head in _MARKED:
        if any(r.search(body) for r in res):
            hits.append(head)
    return tuple(hits)


def contains_backstage_metatext(text) -> bool:
    """True — текст несёт backstage-метаречь (семьи MB-*)."""
    return bool(find_backstage_metatext(text))


# ── 07D.2: недоступность ≠ «я проверил всё в интернете» ─────────────────────

#: Закрытая семья заявлений о ПОЛНОЙ проверке (overclaim). Обычное
#: «проверил источники/по трём ссылкам/нашёл подтверждение» НЕ ловится.
_TOTAL_VERIFICATION_PATTERNS: tuple[str, ...] = (
    r"проверил[аи]?\s+(?:вс[её]\s+(?:в\s+)?интернет[еа]|весь\s+интернет"
    r"|всю\s+(?:сеть|паутину))\b",
    r"(?:перерыл|перерыла|обрыл|обрыла|перелопатил|перелопатила|обшарил"
    r"|обшарила|прогуглил|прогуглила|изучил|изучила)\s+"
    r"(?:весь\s+интернет|вс[её]\s+в\s+интернете|всю\s+(?:сеть|паутину))\b",
    r"весь\s+интернет\s+(?:проверен|перерыт|обрыт|изучен)\b",
)

_TOTAL_RE: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _TOTAL_VERIFICATION_PATTERNS)


def claims_total_verification(text) -> bool:
    """True — текст утверждает тотальную проверку («я проверил всё
    в интернете»), недоступная/частичная проверка не может так заявлять."""
    body = str(text or "")
    return any(r.search(body) for r in _TOTAL_RE)


# ── Предикаты принадлежности honesty-классам ────────────────────────────────

def _has_phrase(text: str, klass: HonestyClass) -> bool:
    body = str(text or "").strip().casefold()
    pool = klass.phrases() + tuple(klass.examples)
    return any(p.casefold() in body for p in pool if p)


def is_honest_refusal(text) -> bool:
    """Текст — канонический честный отказ (пул зарегистрирован в классе)."""
    return _has_phrase(text, HONEST_REFUSAL)


def is_honest_unavailability(text) -> bool:
    """Текст — каноническая честная недоступность (пул в классе)."""
    return _has_phrase(text, HONEST_UNAVAILABLE)


def honest_failure_is_allowed(text) -> bool:
    """Честный отказ/недоступность без overclaim и без метаречи.

    Инвариант CFG-07A.3/07D.2: честные пулы проходят; «я проверил всё
    в интернете» и backstage-формулы — нет."""
    t = str(text or "")
    return ((is_honest_refusal(t) or is_honest_unavailability(t))
            and not claims_total_verification(t)
            and not contains_backstage_metatext(t))


# ── 07A.5: явный технический/административный контекст ──────────────────────

#: Закрытый набор маркеров прямого вопроса об устройстве/возможностях.
#: В таком контексте честное объяснение доступных возможностей разрешено:
#: блокировка метаречи применяется к обычной беседе и фактчеку, но не
#: заставляет персонажа врать (L345). Планировщик фактов это объяснение
#: строит из человеческих имён capability (direct_capabilities), не из
#: reason-кодов — словарь FORBIDDEN не содержит общих слов.
_ADMIN_QUESTION_MARKERS: tuple[str, ...] = (
    "как ты устроен", "как устроен", "что ты умеешь", "что умеешь",
    "что ты можешь", "что можешь", "какие модули", "какие функции",
    "какие у тебя", "как ты работаешь", "как работает", "какие команды",
    "список команд", "какие инструменты", "какая у тебя",
)


def is_explicit_admin_context(text) -> bool:
    """True — текст выглядит прямым техническим/административным вопросом
    об устройстве/возможностях бота (07A.5)."""
    body = str(text or "").casefold()
    return any(m in body for m in _ADMIN_QUESTION_MARKERS)
