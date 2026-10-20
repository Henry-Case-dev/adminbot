"""CFG-07C-G — словарь egress-классов и runtime-guard public_speech_guard.

ЕДИНЫЙ ИСТОЧНИК honesty-классов («честное ограничение / честный отказ /
честная недоступность / подтверждённый вердикт») и FORBIDDEN-словаря
метаречи для тест-гардов CFG-07A.3/.5, CFG-07D.1/.2
(tests/test_cfg07_egress_dictionary.py) и runtime-guard'а на точке
outbound (07C.1–.6, CFG-07CG-TAIL: детерминированный `guard_public_text`
на delivery-швах фактчека v2 — factcheck_orchestrator + tool_route).

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
  детерминированные предикаты + детерминированный sanitize (0 LLM-
  вызовов, 0 сетевых обращений);
* машинные артефакты корпуса (FA-06/07/08 остатки, JSON-эхо FA-01/02,
  метка SF-16, MB-10/11/12) — детерминированные детекторы/срез этого
  модуля с id-кодами корпуса (волна 07D.5); смысловая метаречь без
  дословной формулы (инверсии overclaim) — триггер bounded retry
  (metatext_retry_reason), не тихий срез;
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


# ── 07D.5: машинные артефакты корпуса (FA-06/07/08 остатки, JSON-эхо
#    FA-01/02, метка SF-16) и MB-10/11/12 ──────────────────────────────────────
# Источник — записи 07a1-corpus.json (source of record); каждая семья несёт
# id корпуса для telemetry (R17: коды, не приватные тексты). Это НЕ растущий
# black-list (07A.7): расширение = осознанная правка с записью корпуса.
# Детерминированный ремонт — срез формулы (факты/числа/ссылки не меняются);
# retry на машинные артефакты НЕ тратится (ремонт существует).

#: Границы машинного токена: латиница/кириллица/цифры/подчёркивание —
#: ``tool_not_active`` внутри ``host_not_actively`` не срабатывает.
_TOK = "0-9A-Za-zА-Яа-яёЁ_"


def _token_re(token: str) -> re.Pattern:
    return re.compile(rf"(?<![{_TOK}]){re.escape(token)}(?![{_TOK}])",
                      re.IGNORECASE)


def _token_cut_re(token: str) -> re.Pattern:
    """Срез-версия токена: окружающие пробелы и одна висячая запятая/
    двоеточие за формулой убираются (без огрызков)."""
    return re.compile(rf"\s*(?<![{_TOK}]){re.escape(token)}(?![{_TOK}])"
                      rf"(?:\s*[,:])?", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class MachineArtifact:
    """Семья машинных артефактов корпуса 07A-1 (07D.5).

    ``detect`` — детектор попадия; ``strip`` — детерминированный срез
    (применяется только к найденному — содержательные слова целы)."""

    corpus_id: str
    kind: str
    detect: tuple[re.Pattern, ...]
    strip: tuple[re.Pattern, ...]


def _bracket_block_re(head: str) -> re.Pattern:
    r"""Срез bracket-вставки целиком: «[ГОЛОВКА …]» до закрывающей скобки
    или конца строки (незакрытая — срезается по голове). ``head``
    передаётся с ведущей '[' — экранируется ТЕЛО без неё (иначе '\['
    превращается в открывающий char-class и режет чужие скобки)."""
    return re.compile(
        rf"\s*\[{re.escape(head[1:])}"
        rf"[^\]\n]*\]?", re.IGNORECASE)


_MACHINE_FAMILIES: tuple[MachineArtifact, ...] = (
    # FA-06: сервисный refusal-токен воркера (nostalgia), kind=word_ci.
    MachineArtifact(
        corpus_id="FA-06", kind="service_echo",
        detect=(_token_re("UNCHANGED"),),
        strip=(_token_cut_re("UNCHANGED"),)),
    # FA-07: layer-A маркер nostalgia в Direct-контексте.
    MachineArtifact(
        corpus_id="FA-07", kind="service_echo",
        detect=(_token_re("nostalgia_hint"),),
        strip=(re.compile(rf"\s*(?<![{_TOK}])nostalgia_hint\s*:"
                          rf"(?![{_TOK}])", re.IGNORECASE),)),
    # FA-08: bracket-вставка checkup-fallback (SYSTEM-only формат).
    MachineArtifact(
        corpus_id="FA-08", kind="bracket",
        detect=(re.compile(re.escape("[системное уведомление"),
                           re.IGNORECASE),),
        strip=(_bracket_block_re("[системное уведомление"),)),
    # FA-01/FA-02: сырой JSON-фрагмент (ключ Stage-1/handoff в тексте).
    MachineArtifact(
        corpus_id="FA-01", kind="json_echo",
        detect=(re.compile(r'"\s*reason\s*"\s*:', re.IGNORECASE),
                re.compile(r'\{\s*"reason"', re.IGNORECASE)),
        strip=(re.compile(r'\s*\{[^{}\n]*"\s*reason\s*"\s*:[^{}\n]*\}',
                          re.IGNORECASE),
               re.compile(r'\s*"\s*reason\s*"\s*:[^,\n]*(?:,)?',
                          re.IGNORECASE),
               re.compile(r'\s*\{\s*"reason"[^{}\n]*\}?', re.IGNORECASE))),
    MachineArtifact(
        corpus_id="FA-02", kind="json_echo",
        detect=(re.compile(r'"\s*response_mode\s*"', re.IGNORECASE),),
        strip=(re.compile(r'\s*\{[^{}\n]*"\s*response_mode\s*"[^{}\n]*\}',
                          re.IGNORECASE),
               re.compile(r'\s*"\s*response_mode\s*"\s*:[^,\n]*(?:,)?',
                          re.IGNORECASE),
               re.compile(r'\s*"\s*response_mode\s*"', re.IGNORECASE))),
    # SF-16: метка архивных блоков как самостоятельный артефакт в речи
    # (E3-эхо MB-02; запрет в digest уже живёт в system2_handoff).
    MachineArtifact(
        corpus_id="SF-16", kind="label",
        detect=(re.compile(r"архивная справка", re.IGNORECASE),),
        strip=(re.compile(r"\s*\[Архивная справка[^\]\n]*\]?",
                          re.IGNORECASE),
               re.compile(r'\s*[«"][^»"]*Архивная справка[^»"]*[»"]'
                          r"(?:\s*:)?", re.IGNORECASE),
               re.compile(r"\s*Архивная справка\s*:", re.IGNORECASE))),
    # MB-10: техполя фактчек-семьи в речи (период проверки/(unknown)/…).
    MachineArtifact(
        corpus_id="MB-10", kind="tech_field",
        detect=(_token_re("период проверки"), _token_re("(unknown)"),
                _token_re("precision"), _token_re("as_of"),
                _token_re("uncertainty")),
        strip=(_token_cut_re("период проверки"), _token_cut_re("(unknown)"),
               _token_cut_re("precision"), _token_cut_re("as_of"),
               _token_cut_re("uncertainty"))),
    # MB-11: англ. reason-коды Writer-заметки как видимый текст.
    MachineArtifact(
        corpus_id="MB-11", kind="reason_code",
        detect=(_token_re("tool_not_active"), _token_re("capability_not_ready"),
                _token_re("no_tool"), _token_re("low_confidence")),
        strip=(_token_cut_re("tool_not_active"),
               _token_cut_re("capability_not_ready"),
               _token_cut_re("no_tool"), _token_cut_re("low_confidence"))),
    # MB-12: имена tool-ов Writer-payload в содержательных репликах.
    MachineArtifact(
        corpus_id="MB-12", kind="tool_name",
        detect=(_token_re("execute_web_search"), _token_re("query_chat_memory"),
                _token_re("dig_into_lore"), _token_re("compile_lore_story"),
                _token_re("get_bot_health"), _token_re("fetch_article")),
        strip=(_token_cut_re("execute_web_search"),
               _token_cut_re("query_chat_memory"),
               _token_cut_re("dig_into_lore"),
               _token_cut_re("compile_lore_story"),
               _token_cut_re("get_bot_health"),
               _token_cut_re("fetch_article"))),
)


def find_machine_artifacts(text) -> tuple[str, ...]:
    """id-коды корпу�а машинных артефактов, найденные в тексте (07D.5)."""
    body = str(text or "")
    return tuple(f.corpus_id for f in _MACHINE_FAMILIES
                 if any(r.search(body) for r in f.detect))


# ── 07D.5: смысловой слой — инверсные/вариативные формулировки ───────────────
# Закрытые сеты (07D.2) ловят дословный прямой порядок. Инверсия («весь
# интернет я проверил») — НЕ дословная формула: её нельзя срезать без риска
# огрызка, поэтому она триггерит ОДИН bounded retry с причиной (пере-
# использование retry-бюджета Вербализатора), а не тихий срез и не новый
# black-list (07A.7). Источник — та же семья тотальной проверки
# (аддендум L343) + зафиксированный остаток 07cg-tail §2.2.

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

#: Срез-грамматика инверсии: «объект + (местоимение/наречие)* + глагол»
#: (прямой порядок уже срезается закрытым сетом _TOTAL_RE). Используется
#: на деградационном пути после неудачного retry и на delivery-шве.
_INVERSE_STRIP_RE = re.compile(
    rf"\s*(?<![{_TOK}]){_SEM_TOTAL_OBJ_BODY}"
    rf"(?:\s+(?:я|мы|ты|вы|он|она|они|оно|уже|давно|сам|сама|сами|тут"
    rf"|ведь|честно))*\s+{_SEM_VERIFY_VERB_BODY}"
    rf"(?![{_TOK}])(?:\s*[,:])?", re.IGNORECASE)


def _closed_total_hits(sentence: str) -> bool:
    """Предложение уже покрыто закрытым сетом 07D.2 (детерминированный
    ремонт существует — смысловой слой его не задваивает)."""
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
    """Причина bounded-retry (CFG-07D.5): смысловая метаречь, НЕ пойманная
    закрытыми сетами. Дословные формулы и машинные артефакты → None:
    для них существует детерминированный ремонт, бюджет retry не тратится.
    Никогда не бросает."""
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
# Runtime-guard на точке outbound (07C.1–.5, CFG-07CG-TAIL)
# Детерминированный sanitize: 0 LLM-вызовов, факты/ссылки/имена/цитаты/
# числа не меняются; honesty-классы и админ-контекст проходят байт-в-байт.
# ═══════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass(frozen=True)
class GuardResult:
    """Итог guard'а на одном outbound-тексте.

    ``text`` — что доставлять: исходный текст (чисто/honesty/админ),
    урезанный (маркеры срезаны, факты целы) или "" (вырожденный остаток —
    шов ОБЯЗАН подставить честный класс: enum-статус/пул, 07C.4).
    ``findings`` — головные фразы семей + ``overclaim:total_verification``.
    """

    text: str
    findings: tuple[str, ...] = ()
    changed: bool = False
    admin_context: bool = False
    repaired: bool = True


_ALL_MARKER_RES: tuple[re.Pattern, ...] = tuple(
    r for _fam, rs in _MARKERS for r in rs)


def _wrap_strip_re(r: re.Pattern) -> re.Pattern:
    """Срез-версия маркера: захват окружающих пробелов и одной висячей
    запятой/двоеточия («По моим логам, источники…» → «источники…»,
    «проверил всё в интернете: тезис…» → «тезис…») без огрызков."""
    return re.compile(rf"\s*(?:{r.pattern})(?:\s*[,:])?", re.IGNORECASE)


_STRIP_RES: tuple[re.Pattern, ...] = tuple(
    _wrap_strip_re(r) for r in _ALL_MARKER_RES + _TOTAL_RE)

#: Срез машинных артефактов (07D.5) — точечные формулы семей корпуса.
_MACHINE_STRIP_RES: tuple[re.Pattern, ...] = tuple(
    r for fam in _MACHINE_FAMILIES for r in fam.strip)


def _strip_matches(text: str) -> str:
    """Срез FORBIDDEN-формул/overclaim/машинных артефактов/инверсных
    overclaim-формул + уборка следов вырезания (пустые скобки, двойные
    пробелы, висячая пунктуация в начале). Меняет ТОЛЬКО найденные
    формулы — содержательные слова/числа остаются."""
    out = text
    for r in _STRIP_RES + _MACHINE_STRIP_RES + (_INVERSE_STRIP_RE,):
        out = r.sub(" ", out)
    out = re.sub(r"\(\s*\)", " ", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return re.sub(r"^[\s,;:\-–—]+", "", out)


def strip_guard_findings(text) -> str:
    """Детерминированный срез ВСЕХ распознанных формул (закрытые семьи,
    overclaim, машинные артефакты, инверсные overclaim-формулы) —
    деградационный путь bounded retry (07D.5) и повторное применение
    швами; guard идемпотентен."""
    return _strip_matches(str(text or ""))


def guard_public_text(text, *, admin_context: bool = False) -> GuardResult:
    """Egress-guard одного исходящего текста (07C.1/.2): детерминированно,
    без LLM, fail-soft (внутренняя ошибка → исходный текст без флагов).

    Порядок решения: пустой/честный класс/админ-контекст → байт-в-байт;
    FORBIDDEN-маркеры и overclaim-формулы → срез + findings; результат без
    букв/цифр → ``text=""`` (вырожден, шов подменяет честным классом).
    Применяется ТОЛЬКО к ответам модели — не к клеймам, поисковым
    запросам, машинному JSON и логам (07C.5)."""
    src = str(text or "")
    try:
        if not src.strip():
            return GuardResult(text=src, admin_context=bool(admin_context))
        if admin_context:
            # Наблюдение 4 review-07cg: легитимная техсправка админу не
            # режется (развязка через is_explicit_admin_context на шве).
            return GuardResult(text=src, admin_context=True)
        if honest_failure_is_allowed(src):
            return GuardResult(text=src)
        findings = list(find_backstage_metatext(src))
        overclaim = claims_total_verification(src)
        if overclaim:
            findings.append("overclaim:total_verification")
        # 07D.5: машинные артефакты корпуса (ремонт — срез ниже) и
        # смысловой слой (инверсии overclaim). Retry с причиной живёт
        # в Вербализаторе; здесь находка честно телеметрируется, а срез
        # ниже (_INVERSE_STRIP_RE в _strip_matches) — defense-in-depth:
        # шов без retry-бюджета не доставляет известную инверсную
        # формулу (review-07d5 F4).
        findings.extend(find_machine_artifacts(src))
        findings.extend(find_semantic_metatext(src))
        if not findings:
            return GuardResult(text=src)
        cleaned = _strip_matches(src)
        repaired = bool(re.search(r"[0-9a-zа-яё]", cleaned, re.IGNORECASE))
        return GuardResult(text=cleaned if repaired else "",
                           findings=tuple(findings), changed=True,
                           repaired=repaired)
    except Exception:      # fail-soft: guard не роняет доставку
        return GuardResult(text=src, admin_context=bool(admin_context))
