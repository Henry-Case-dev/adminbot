"""BGS-03 — словарь речевых наблюдений: диагностика, не редактирование.

ЕДИНЫЙ ИСТОЧНИК honesty-классов («честное ограничение / честный отказ /
честная недоступность / подтверждённый вердикт») и закрытого словаря
метаречи/машинных артефактов.

Контракт BEHAVIOR-GATES-SIMPLIFICATION-01 (BGS-03 §1–2):

* наблюдение НЕ меняет живой ответ: ``guard_public_text`` возвращает
  исходный текст байт-в-байт и только сообщает коды находок (место
  срабатывания + код в событии ``speech_observation``);
* ни одна фраза словаря («по моим наблюдениям», «я нейросеть», «мои
  промпты», «сейчас пошучу», «проверил весь интернет») не приводит к
  вырезанию слов, к пустому сообщению, к fail-closed или к повторной
  генерации — за содержание отвечает человек, а не ножницы;
* техническая очистка настоящих машинных маркеров (<thought>, ``fact:ID``,
  ``msg:ID``, target-маркер) живёт в ``services/outgoing_guard`` — узкая
  идемпотентная функция; сюда живые слова не переносятся;
* каноны фактчека/промптов не трогаются; модуль — детерминированные
  предикаты (0 LLM-вызовов, 0 сетевых обращений).

Границы словаря (07A.7 — НЕ растущий black-list):

* honesty-классы НЕ копируют тексты пулов — ссылаются на живые пулы
  smartmodule_phrases / factcheck_renderer / checkup_prompts как на
  единственные источники (фраза, добавленная в пул, автоматически
  попадает в класс);
* FORBIDDEN-словарь — закрытые семьи метаречи владельца (корпус
  07a1-corpus MB-*, аддендум L342/L345/L376/L377); расширение = осознанная
  правка с источником, а не авто-рост по инцидентам;
* обычные слова «лог/анализ/проверка/модуль/инструмент» в содержательном
  контексте НЕ нарушение — словарь держит только конкретные формулы;
* прямой вопрос о внутреннем устройстве в явном техническом/админ
  контексте не считается находкой;
* предикаты применяются к ОТВЕТАМ модели (реплики, fallback-фразы),
  НЕ к байтам канонов: каноны легитимно содержат запреты-примеры
  (блок ANTI_BOT перечисляет запрещённые самоописания дословно).
"""
from __future__ import annotations

import dataclasses
import logging
import re

from services import smartmodule_phrases as ph
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
from services.factcheck_renderer import _NO_LINKS_NOTICE, _VERDICT_HEADLINE

logger = logging.getLogger(__name__)

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

#: Сработавшие маркеры по семьям (для наблюдения: код = сам маркер).
_MARKED: tuple[tuple[str, tuple[re.Pattern, ...]], ...] = tuple(
    (fam[0], res) for fam, res in _MARKERS)


def find_backstage_metatext(text) -> tuple[str, ...]:
    """Сработавшие формулы FORBIDDEN-семей (пусто — чисто).

    BGS-03: это НАБЛЮДЕНИЕ (код находки), а не основание для правки текста.
    Возвращается сам сработавший маркер (casefold), а не голова семьи:
    владелец видит, что именно совпало («мои промпты», «сейчас пошучу»)."""
    body = str(text or "")
    hits: list[str] = []
    for _head, res in _MARKED:
        for pattern in res:
            match = pattern.search(body)
            if match is None:
                continue
            code = match.group(0).casefold()
            if code not in hits:
                hits.append(code)
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


# ── 07D.5: машинные артефакты корпуса (FA-06/07/08 остатки, JSON-эхо
#    FA-01/02, метка SF-16) и MB-10/11/12 ──────────────────────────────────────
# Источник — записи 07a1-corpus.json (source of record); каждая семья несёт
# id корпуса для telemetry (R17: коды, не приватные тексты). Это НЕ растущий
# black-list (07A.7): расширение = осознанная правка с записью корпуса.
# Детерминированный ремонт снят вместе с редактированием живого текста:
# детекторы остаются только для наблюдения (BGS-03).
# retry на машинные артефакты НЕ тратится (ремонт существует).

#: Границы машинного токена: латиница/кириллица/цифры/подчёркивание —
#: ``tool_not_active`` внутри ``host_not_actively`` не срабатывает.
_TOK = "0-9A-Za-zА-Яа-яёЁ_"


def _token_re(token: str) -> re.Pattern:
    return re.compile(rf"(?<![{_TOK}]){re.escape(token)}(?![{_TOK}])",
                      re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class MachineArtifact:
    """Семья машинных артефактов корпуса 07A-1 (07D.5): только детектор.

    ``detect`` — попадия семьи для наблюдения; редактирование текста в этом
    модуле отсутствует (BGS-03 §1)."""

    corpus_id: str
    kind: str
    detect: tuple[re.Pattern, ...]


_MACHINE_FAMILIES: tuple[MachineArtifact, ...] = (
    # FA-06: сервисный refusal-токен воркера (nostalgia), kind=word_ci.
    MachineArtifact(
        corpus_id="FA-06", kind="service_echo",
        detect=(_token_re("UNCHANGED"),)),
    # FA-07: layer-A маркер nostalgia в Direct-контексте.
    MachineArtifact(
        corpus_id="FA-07", kind="service_echo",
        detect=(_token_re("nostalgia_hint"),)),
    # FA-08: bracket-вставка checkup-fallback (SYSTEM-only формат).
    MachineArtifact(
        corpus_id="FA-08", kind="bracket",
        detect=(re.compile(re.escape("[системное уведомление"),
                           re.IGNORECASE),)),
    # FA-01/FA-02: сырой JSON-фрагмент (ключ Stage-1/handoff в тексте).
    MachineArtifact(
        corpus_id="FA-01", kind="json_echo",
        detect=(re.compile(r'"\s*reason\s*"\s*:', re.IGNORECASE),
                re.compile(r'\{\s*"reason"', re.IGNORECASE))),
    MachineArtifact(
        corpus_id="FA-02", kind="json_echo",
        detect=(re.compile(r'"\s*response_mode\s*"', re.IGNORECASE),)),
    # SF-16: метка архивных блоков как самостоятельный артефакт в речи
    # (E3-эхо MB-02; запрет в digest уже живёт в system2_handoff).
    MachineArtifact(
        corpus_id="SF-16", kind="label",
        detect=(re.compile(r"архивная справка", re.IGNORECASE),)),
    # MB-10: техполя фактчек-семьи в речи (период проверки/(unknown)/…).
    MachineArtifact(
        corpus_id="MB-10", kind="tech_field",
        detect=(_token_re("период проверки"), _token_re("(unknown)"),
                _token_re("precision"), _token_re("as_of"),
                _token_re("uncertainty"))),
    # MB-11: англ. reason-коды Writer-заметки как видимый текст.
    MachineArtifact(
        corpus_id="MB-11", kind="reason_code",
        detect=(_token_re("tool_not_active"), _token_re("capability_not_ready"),
                _token_re("no_tool"), _token_re("low_confidence"))),
    # MB-12: имена tool-ов Writer-payload в содержательных репликах.
    MachineArtifact(
        corpus_id="MB-12", kind="tool_name",
        detect=(_token_re("execute_web_search"), _token_re("query_chat_memory"),
                _token_re("dig_into_lore"), _token_re("compile_lore_story"),
                _token_re("get_bot_health"), _token_re("fetch_article"))),
)


def find_machine_artifacts(text) -> tuple[str, ...]:
    """id-коды корпу�а машинных артефактов, найденные в тексте (07D.5)."""
    body = str(text or "")
    return tuple(f.corpus_id for f in _MACHINE_FAMILIES
                 if any(r.search(body) for r in f.detect))


# ── 07D.5: смысловой слой — инверсные/вариативные формулировки ───────────────
# Закрытые сеты (07D.2) ловят дословный прямой порядок. Инверсия («весь
# интернет я проверил») — тоже находка для наблюдения: живой ответ по ней
# не перегенерируется и не режется (BGS-03 §1–2, BGS-04 §4). Источник —
# та же семья тотальной проверки (аддендум L343) + остаток 07cg-tail §2.2.

#: Объект тотального охвата (формы из закрытого сета 07D.2); lookahead
#: отсекает «весь интернет-магазин» («интернет-магазин» — другой объект);
#: грамматика закрытая, источник один (07A.7 — не авто-рост).
_SEM_TOTAL_OBJ_BODY = (
    r"(?:весь\s+интернет|вся\s+сеть|всю\s+сеть|всей\s+сетью"
    r"|вся\s+паутина|всю\s+паутину|всей\s+паутиной"
    r"|вс[её]\s+в\s+интернет[еа])")
_SEM_TOTAL_OBJ_RE = re.compile(
    rf"{_SEM_TOTAL_OBJ_BODY}(?![{_TOK}\-])", re.IGNORECASE)

#: Конечные формы глагола проверки (причастия «проверенный/ных» и
#: «проверилась» границами отсечены). Негативный lookbehind «не» перед
#: глаголом: честное ограничение («весь интернет я не проверил») — класс
#: PC-01/честных пулов, а НЕ инверсия overclaim (review-07d5 F3); «не»,
#: слитое с другим словом («в паутине»), границей \b отсечено — глагол
#: ловится.
_SEM_VERIFY_VERB_BODY = (
    r"(?:проверил[аи]?|перерыл[аи]?|обрыл[аи]?"
    r"|перелопатил[аи]?|обшарил[аи]?|прогуглил[аи]?|изучил[аи]?"
    r"|проверен[аоы]?|перерыт[аоы]?|обрыт[аоы]?|изучен[аоы]?)")
_SEM_VERIFY_VERB_RE = re.compile(
    rf"(?<![{_TOK}])(?<!\bне\s)(?<!\bне\s\s)"
    rf"{_SEM_VERIFY_VERB_BODY}(?![{_TOK}])", re.IGNORECASE)

def _closed_total_hits(sentence: str) -> bool:
    """Предложение уже покрыто закрытым сетом 07D.2 (смысловой слой его
    не задваивает в наблюдении)."""
    return any(r.search(sentence) for r in _TOTAL_RE)


def find_semantic_metatext(text) -> tuple[str, ...]:
    """07D.5: инверсные/вариативные формулировки тотальной проверки —
    объект охвата + глагол проверки в одном предложении в ЛЮБОМ порядке,
    НЕ пойманные закрытыми сетами. 0 LLM; код находки — не приватный текст."""
    body = str(text or "")
    hits: list[str] = []
    for sentence in re.split(r"[.!?…\n]+", body):
        if (_SEM_TOTAL_OBJ_RE.search(sentence)
                and _SEM_VERIFY_VERB_RE.search(sentence)
                and not _closed_total_hits(sentence)):
            hits.append("semantic:total_verification_variant")
    return tuple(hits)


def metatext_retry_reason(text) -> str | None:
    """Код наблюдения смысловой метаречи (совместимое имя прежнего retry).

    BGS-03/04: код БОЛЬШЕ НЕ является причиной повторной генерации —
    ``verbalize_validated`` только записывает его в
    ``stats['metatext_observed']`` и не меняет текст. Дословные формулы и
    машинные артефакты → None (у них отдельные коды). Никогда не бросает."""
    try:
        body = str(text or "")
        if (contains_backstage_metatext(body)
                or claims_total_verification(body)
                or find_machine_artifacts(body)):
            return None
        if find_semantic_metatext(body):
            return "metatext_semantic:total_verification_variant"
        return None
    except Exception:      # fail-soft: детектор не роняет валидацию
        return None


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


def is_honest_limitation(text) -> bool:
    """Текст — каноническое честное ограничение (пул/пример в классе).

    Наблюдение 3 review-07cg: PC-01 «проверил — не нашёл подтверждений»
    и honest_limitation-каноны renderer'а должны проходить allow-путь,
    иначе хвостовой guard на delivery-швах режет честное ограничение."""
    return _has_phrase(text, HONEST_LIMITATION)


def honest_failure_is_allowed(text) -> bool:
    """Честный отказ/недоступность/ограничение без overclaim и без
    метаречи.

    Инвариант CFG-07A.3/07D.2: честные пулы проходят; «я проверил всё
    в интернете» и backstage-формулы — нет. Наблюдение 3 review-07cg:
    honest_limitation (PC-01, «Недостаточно данных») входит в allow-путь."""
    t = str(text or "")
    return ((is_honest_refusal(t) or is_honest_unavailability(t)
             or is_honest_limitation(t))
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


# ═══════════════════════════════════════════════════════════════════════════
# Наблюдение на точке outbound (BGS-03)
# 0 LLM-вызовов, 0 сетевых обращений, НОЛЬ правок текста: находки словаря
# уходят в событие/лог (место + код), живой ответ доставляется байт-в-байт.
# ═══════════════════════════════════════════════════════════════════════════

#: Имя события наблюдения (mca_events, §17.1-совместимое).
OBSERVATION_EVENT = "speech_observation"
#: Компонент события — сам наблюдатель.
OBSERVATION_COMPONENT = "public_speech_guard"


@dataclasses.dataclass(frozen=True)
class GuardResult:
    """Итог наблюдения на одном outbound-тексте.

    ``text`` — ВСЕГДА исходный текст: словарь больше не редактирует и не
    блокирует живой ответ (BGS-03 §1–2). ``findings`` — коды для
    владельца/телеметрии (сработавшие маркеры, ``overclaim:...``,
    ``semantic:...``, id машинных артефактов корпуса). ``changed`` и
    ``repaired`` сохранены ради совместимости швов и всегда ``False``/``True``.
    """

    text: str
    findings: tuple[str, ...] = ()
    changed: bool = False
    admin_context: bool = False
    repaired: bool = True


def find_speech_observations(text) -> tuple[str, ...]:
    """Все диагностические коды текста (закрытые семьи + overclaim +
    машинные артефакты + смысловые инверсии). 0 LLM; коды — не текст."""
    body = str(text or "")
    if not body.strip():
        return ()
    findings: list[str] = list(find_backstage_metatext(body))
    if claims_total_verification(body):
        findings.append("overclaim:total_verification")
    findings.extend(find_machine_artifacts(body))
    findings.extend(find_semantic_metatext(body))
    return tuple(findings)


def emit_speech_observation(findings, *, seam: str = "",
                            chat_id: int | None = None) -> None:
    """Событие наблюдения: место срабатывания + коды (R17: без текста).

    Fail-open: недоступная телеметрия не влияет на доставку."""
    codes = tuple(str(code) for code in (findings or ()) if str(code))
    if not codes:
        return
    # Место срабатывания: бизнес-шов, если вызывающий его назвал, иначе —
    # точка входа самого наблюдателя (без домыслов о вызывающем).
    stage = str(seam or "guard_public_text")
    try:
        from services import mca_events
        # Literal имени события — чтобы сканеры/панель наблюдаемости видели
        # реальную точку эмиссии (OBSERVATION_EVENT — то же имя).
        mca_events.emit_mca_event(
            "speech_observation", outcome=mca_events.OUTCOME_SUCCESS,
            component=OBSERVATION_COMPONENT, stage=stage,
            chat_id=int(chat_id) if chat_id else None,
            usage_json={"codes": list(codes)})
    except Exception:      # pragma: no cover - телеметрия не рвёт доставку
        logger.debug("[speech_observation] event failed", exc_info=True)
    logger.info("[speech_observation] seam=%s | codes=%s",
                stage, ",".join(codes))


def guard_public_text(text, *, admin_context: bool = False,
                      seam: str = "", chat_id: int | None = None
                      ) -> GuardResult:
    """Наблюдение за одним исходящим текстом (BGS-03 §1–2).

    Детерминированно, без LLM, fail-soft. Текст НЕ меняется ни на одном
    пути: результат всегда ``text == исходный``. Находки словаря попадают в
    ``findings`` и в событие ``speech_observation`` (место ``seam`` + коды),
    но не приводят ни к вырезанию слов, ни к пустому сообщению, ни к retry.
    Честные классы и явный админ-контекст не считаются находками."""
    src = str(text or "")
    try:
        if not src.strip():
            return GuardResult(text=src, admin_context=bool(admin_context))
        if admin_context:
            return GuardResult(text=src, admin_context=True)
        if honest_failure_is_allowed(src):
            return GuardResult(text=src)
        findings = find_speech_observations(src)
        if not findings:
            return GuardResult(text=src)
        emit_speech_observation(findings, seam=seam, chat_id=chat_id)
        return GuardResult(text=src, findings=findings)
    except Exception:      # fail-soft: наблюдение не роняет доставку
        return GuardResult(text=src, admin_context=bool(admin_context))
