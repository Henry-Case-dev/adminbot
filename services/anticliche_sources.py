"""AC-DATA (FINAL v8 §2.1/§2.2/§3.1/§3.2) — реестр источников AntiCliche.

Модуль — единственный владелец ответов на вопросы «что за источник», «что
именно было проверено в последний реальный раз» и «насколько это свежо».
Ни парсера документов, ни LLM, ни публикации здесь нет: это границы AC-PIPE.

Контракт (заморожен Architect, `arch/integration-decisions.md` §1):

* ``Source`` — код-реестр со стабильными id (``ru-repo-a``… ``local/manual``);
  включённость живёт в PG (``anticliche_source_state.enabled``).
* ``SourceCheck`` (последняя) — ``anticliche_source_state``;
  история — существующий журнал событий ``mca_events``
  (``component='anticliche'``, ``trace_id=run_id``), без новых таблиц.
* Один транспорт: ``fetch_document`` на httpx — второй стек не создаётся.

Честность статусов (§3.2): статусы не смешиваются. ``available`` не значит
«модель проработала материал», ``unchanged`` — успешная проверка без вызова
модели, ``stale`` — отдельная пометка свежести, а не замена результата.
403 сам по себе — НЕ ``policy_blocked``: нужен положительный признак
robot-policy; иначе это ``auth_failed`` (тест 6 §9.2). ``local/manual`` не
имеет HTTP-статуса: «локальный/доступно» либо «ошибка БД».

R17: наружу уходят коды/числа/идентификаторы; тело ответа источника пишется
в лог только существующим ``log_external_api`` (усечённым).
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from services.external_log import log_external_api

logger = logging.getLogger(__name__)

# ── статусы §3.2 (+ локальный статус из AC-SRC-LOCAL) ───────────────────────
STATUS_AVAILABLE = "available"
STATUS_UNCHANGED = "unchanged"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_POLICY_BLOCKED = "policy_blocked"
STATUS_AUTH_FAILED = "auth_failed"
STATUS_NETWORK_ERROR = "network_error"
STATUS_PARSE_ERROR = "parse_error"
STATUS_MISSING = "missing"
STATUS_UNCHECKED = "unchecked"
STATUS_DISABLED = "disabled"
# AC-SRC-LOCAL: локальный источник не имеет HTTP; его единственный сбой —
# недоступность БД. Отдельный код, чтобы не называть это «сетевой ошибкой».
STATUS_DB_ERROR = "db_error"
# Внутренний сбой самого воркера (не сети и не источника). Не маскируется
# под сетевой статус: иначе диагностика «источник плохой» была бы ложной.
STATUS_INTERNAL_ERROR = "internal_error"

ALL_STATUSES: frozenset[str] = frozenset({
    STATUS_AVAILABLE, STATUS_UNCHANGED, STATUS_RATE_LIMITED,
    STATUS_POLICY_BLOCKED, STATUS_AUTH_FAILED, STATUS_NETWORK_ERROR,
    STATUS_PARSE_ERROR, STATUS_MISSING, STATUS_UNCHECKED, STATUS_DISABLED,
    STATUS_DB_ERROR, STATUS_INTERNAL_ERROR,
})

#: Успешный результат последней реальной проверки.
SUCCESS_STATUSES: frozenset[str] = frozenset({STATUS_AVAILABLE,
                                              STATUS_UNCHANGED})
#: Проверка состоялась, но источник нездоров.
PROBLEM_STATUSES: frozenset[str] = frozenset({
    STATUS_RATE_LIMITED, STATUS_POLICY_BLOCKED, STATUS_AUTH_FAILED,
    STATUS_NETWORK_ERROR, STATUS_PARSE_ERROR, STATUS_MISSING,
    STATUS_DB_ERROR, STATUS_INTERNAL_ERROR,
})
#: Ни одной реальной попытки (или автоматический опрос выключен).
IDLE_STATUSES: frozenset[str] = frozenset({STATUS_UNCHECKED, STATUS_DISABLED})

#: Пользовательские подписи §3.2 (вкладка «Источники», строка 1).
STATUS_LABELS: dict[str, dict] = {
    STATUS_AVAILABLE: {"label": "Доступен", "tone": "ok", "group": "ok"},
    STATUS_UNCHANGED: {"label": "Доступен · без изменений", "tone": "ok",
                       "group": "ok"},
    STATUS_RATE_LIMITED: {"label": "Ограничение запросов (429)",
                          "tone": "warn", "group": "limited"},
    STATUS_POLICY_BLOCKED: {"label": "Доступ запрещён политикой (403)",
                            "tone": "error", "group": "blocked"},
    STATUS_AUTH_FAILED: {"label": "Нет доступа / авторизация",
                         "tone": "error", "group": "blocked"},
    STATUS_NETWORK_ERROR: {"label": "Ошибка соединения", "tone": "error",
                           "group": "error"},
    STATUS_PARSE_ERROR: {"label": "Источник доступен, формат не распознан",
                         "tone": "warn", "group": "error"},
    STATUS_MISSING: {"label": "Документ не найден", "tone": "error",
                     "group": "error"},
    STATUS_UNCHECKED: {"label": "Ещё не проверялся", "tone": "neutral",
                       "group": "unchecked"},
    STATUS_DISABLED: {"label": "Выключен", "tone": "neutral",
                      "group": "disabled"},
    STATUS_DB_ERROR: {"label": "Ошибка БД (локальный источник)",
                      "tone": "error", "group": "error", "transport": "local"},
    STATUS_INTERNAL_ERROR: {"label": "Внутренняя ошибка проверки",
                            "tone": "error", "group": "error"},
}

# ── виды источников ────────────────────────────────────────────────────────
KIND_GITHUB = "github_repo"
KIND_WIKI = "wiki_api"
KIND_HTTP = "http_document"
KIND_LOCAL = "local"
KIND_BIBLIO = "bibliography"

#: Формат ожидаемого содержимого (детерминированная проверка разбора).
FORMAT_MARKDOWN = "markdown"
FORMAT_WIKI_JSON = "wiki_json"
FORMAT_JSON = "json"
FORMAT_NONE = "none"

#: Честный User-Agent (никогда не маскируется под браузер, §9.2 тест 3).
USER_AGENT = "adminbot-anticliche/1.0"
HTTP_TIMEOUT_SECONDS = 30.0
#: Документ короче этого — валидный, но подозрительно короткий: помечаем
#: предупреждением (`short_document`), а не «поломкой». «Пусто» = реально пусто.
MIN_USABLE_CHARS = 40
#: Признаки robot-policy блокировки в теле/заголовках (положительное
#: доказательство; сам по себе код 403 им не считается).
_POLICY_MARKERS = (
    "robot policy", "robots policy", "robot-policy", "automated access",
    "automated requests", "crawler policy", "bot policy", "scraping policy",
    "user-agent policy", "blocked by robot", "robots.txt",
)
_POLICY_HEADERS = ("x-robot-policy", "x-robots-policy", "x-robots-tag")

#: Библиографическая ссылка — не «выключенный источник», а материал для
#: ручного анализа: подпись не должна выглядеть поломкой.
BIBLIO_LABEL = "Справочный материал (ручная проверка)"


# ── модель источника ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class RetryPolicy:
    """Source-specific retry policy (§3.1/§3.3).

    ``respect_retry_after`` — обязательный минимум для 429: ждём ровно
    назначенное сервером время (в пределах ``max_retry_after_seconds``),
    а не «свою» паузу. ``jitter`` — доля равномерного шума против
    синхронных залпов нескольких источников."""

    base_seconds: int = 3600
    max_seconds: int = 86400
    jitter: float = 0.15
    respect_retry_after: bool = True
    max_retry_after_seconds: int = 86400
    #: Пауза автоматического опроса после подтверждённой policy-блокировки.
    #: ``None`` — автоматический опрос не возобновляется вовсе.
    policy_cooldown_seconds: int | None = None


@dataclass(frozen=True)
class Licence:
    """Лицензия/attribution источника (§3.1, §5.5 п.8).

    ``permits_analysis=False`` → автоматический анализ недоступен.
    ``verified=False`` → права ещё не подтверждены на конкретной ревизии;
    такой источник не включается в числитель «здоровых» по умолчанию.
    """

    name: str
    attribution: str
    permits_analysis: bool | None
    verified: bool
    verified_revision: str = ""
    note: str = ""


@dataclass(frozen=True)
class Source:
    """Конфигурация разрешённого источника (стабильный id)."""

    source_id: str
    title: str
    kind: str
    url: str
    document_paths: tuple[str, ...] = ()
    licence: Licence = Licence("unknown", "", None, False)
    enabled_by_default: bool = False
    auto_check: bool = True
    #: Участвует ли в знаменателе «живых сетевых источников» (§3.1 п.6).
    counts_as_live: bool = True
    retry: RetryPolicy = RetryPolicy()
    #: Репозиторий-владелец (github kind) и документированные upstream-базы —
    #: основа для записи lineage (§3.1, тест 16).
    origin_repo: str = ""
    upstream_bases: tuple[str, ...] = ()
    lineage_id: str = ""
    expected_format: str = FORMAT_MARKDOWN
    note: str = ""
    #: Почему источник выключен по умолчанию, если это не «просто выключен».
    activation_note: str = ""

    @property
    def is_http(self) -> bool:
        return self.kind in (KIND_GITHUB, KIND_WIKI, KIND_HTTP)

    @property
    def is_local(self) -> bool:
        return self.kind == KIND_LOCAL

    @property
    def is_bibliography(self) -> bool:
        return self.kind == KIND_BIBLIO

    @property
    def analysis_eligible(self) -> bool:
        return bool(self.licence.permits_analysis)

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "kind": self.kind,
            "type": self.kind,
            "url": self.url,
            "document_paths": list(self.document_paths),
            "licence": {
                "name": self.licence.name,
                "attribution": self.licence.attribution,
                "permits_analysis": self.licence.permits_analysis,
                "verified": self.licence.verified,
                "verified_revision": self.licence.verified_revision,
                "note": self.licence.note,
            },
            "enabled_by_default": self.enabled_by_default,
            "auto_check": self.auto_check,
            "counts_as_live": self.counts_as_live,
            "analysis_eligible": self.analysis_eligible,
            "retry_policy": {
                "base_seconds": self.retry.base_seconds,
                "max_seconds": self.retry.max_seconds,
                "jitter": self.retry.jitter,
                "respect_retry_after": self.retry.respect_retry_after,
                "max_retry_after_seconds": self.retry.max_retry_after_seconds,
                "policy_cooldown_seconds": self.retry.policy_cooldown_seconds,
            },
            "transport": "http" if self.is_http else (
                "local" if self.is_local else "none"),
            "expected_format": self.expected_format,
            "origin_repo": self.origin_repo,
            "upstream_bases": list(self.upstream_bases),
            "lineage_id": self.lineage_id,
            "note": self.note,
            "activation_note": self.activation_note,
        }


#: Сверено на реальных ревизиях 03.11.2026 (см. report w-ac-data.md):
#: MIT-текст LICENSE + ожидаемые пути + commit SHA каждого репозитория.
_GITHUB_RETRY = RetryPolicy(base_seconds=3600, max_seconds=43200, jitter=0.2)
_WIKI_RETRY = RetryPolicy(base_seconds=3600, max_seconds=86400, jitter=0.2,
                          policy_cooldown_seconds=None)
_LOCAL_RETRY = RetryPolicy(base_seconds=300, max_seconds=3600, jitter=0.0)

SOURCES: tuple[Source, ...] = (
    Source(
        source_id="ru-repo-a",
        title="russian-humanizer (tsalkin)",
        kind=KIND_GITHUB,
        url="https://github.com/tsalkin/russian-humanizer",
        origin_repo="tsalkin/russian-humanizer",
        document_paths=(
            "references/patterns.md",
            "references/kantselyarit-dict.md",
            "references/translationese.md",
            "references/false-positives.md",
            "references/automation-policy.md",
            "references/style-rules.md",
        ),
        licence=Licence(
            name="MIT",
            attribution="Copyright (c) 2026 Russian Humanizer contributors",
            permits_analysis=True,
            verified=True,
            verified_revision="324b155571b52e97c7f7027eefdbc7e908614bc7",
            note=("LICENSE GitHub опознаёт как NOASSERTION: перед текстом MIT "
                  "стоит вводная заметка об адаптации структуры из "
                  "blader/humanizer; сам текст — MIT (проверено чтением "
                  "файла на конкретной ревизии)."),
        ),
        enabled_by_default=False,
        lineage_id="repo:tsalkin/russian-humanizer",
        # LICENSE прямо сообщает происхождение материала.
        upstream_bases=("repo:blader/humanizer",
                        "wikipedia:signs-of-ai-writing"),
        note=("Русские справочники: канцелярит, переводные штампы, "
              "ложные срабатывания. Промпт/разбор — AC-PIPE."),
        activation_note=("Выключен до появления детерминированного разбора "
                         "документов (AC-PIPE): без него нельзя отличить "
                         "пример клише от пояснения."),
    ),
    Source(
        source_id="ru-repo-b",
        title="agent-skills · ru-editor (miolamio)",
        kind=KIND_GITHUB,
        url="https://github.com/miolamio/agent-skills",
        origin_repo="miolamio/agent-skills",
        document_paths=("skills/ru-editor/references/ai-markers-ru.md",),
        licence=Licence(
            name="MIT",
            attribution="miolamio/agent-skills (LICENSE, MIT)",
            permits_analysis=True,
            verified=True,
            verified_revision="17e91018207eee1557b472ee1823d3788aed4161",
            note="Файл и лицензия проверены на ревизии.",
        ),
        enabled_by_default=False,
        lineage_id="repo:miolamio/agent-skills",
        note=("Роль — независимые кандидаты/антипримеры; общий upstream не "
              "подтверждён, lineage помечается как непроверенная."),
        activation_note=("Выключен до появления разбора документов "
                         "(AC-PIPE)."),
    ),
    Source(
        source_id="ru-repo-c",
        title="humanizer-ru (Vladimir-Human)",
        kind=KIND_GITHUB,
        url="https://github.com/Vladimir-Human/humanizer-ru",
        origin_repo="Vladimir-Human/humanizer-ru",
        document_paths=(
            "skills/humanizer-ru/SKILL.md",
            "skills/humanizer-ru/references/patterns.md",
            "skills/humanizer-ru/references/examples.md",
        ),
        licence=Licence(
            name="MIT",
            attribution="Vladimir-Human/humanizer-ru (LICENSE, MIT)",
            permits_analysis=True,
            verified=True,
            verified_revision="35ad747ae4edb87225a73d471715882582853eff",
            note=("Статистика качества из README/бенчмарков репозитория — "
                  "его собственные измерения, НЕ измерения Adminbot."),
        ),
        enabled_by_default=False,
        lineage_id="repo:Vladimir-Human/humanizer-ru",
        note=("Категории и экспериментальные фикстуры. README сравнивает "
              "blader/humanizer как конкурента, а не как источник — "
              "происхождение не считается общим."),
        activation_note=("Выключен до появления разбора документов "
                         "(AC-PIPE)."),
    ),
    Source(
        source_id="local/manual",
        title="Локальные правила (владелец, PG-банк)",
        kind=KIND_LOCAL,
        url="",
        licence=Licence(
            name="owner-authored",
            attribution="Правила проекта и решения владельца",
            permits_analysis=True,
            verified=True,
            note="Локальный источник: HTTP-статуса не существует.",
        ),
        enabled_by_default=True,
        counts_as_live=False,
        retry=_LOCAL_RETRY,
        expected_format=FORMAT_NONE,
        lineage_id="local:manual",
        note=("Ручные выражения, owner pinned и миграция прежнего PG/regex. "
              "Показывается «локальный / доступно» либо «ошибка БД»."),
    ),
    Source(
        source_id="wikipedia",
        title="Wikipedia: Signs of AI writing",
        kind=KIND_WIKI,
        url=(
            "https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
            "&explaintext=1&format=json&redirects=1"
            "&titles=Wikipedia%3ASigns_of_AI_writing"
        ),
        document_paths=("Wikipedia:Signs of AI writing",),
        licence=Licence(
            name="CC BY-SA 4.0",
            attribution="Wikipedia contributors",
            permits_analysis=True,
            verified=True,
            note=("Необязательный источник: второстепенные универсальные "
                  "примеры; русские фразы не формируются переводом."),
        ),
        enabled_by_default=True,
        retry=_WIKI_RETRY,
        expected_format=FORMAT_WIKI_JSON,
        lineage_id="wikipedia:signs-of-ai-writing",
        note=("При подтверждённой robot-policy блокировке — policy_blocked "
              "и никакого автоматического долбления."),
    ),
    # ── библиографические references (ручной анализ, БЕЗ авто-scraping) ─────
    Source(
        source_id="bib-tinkoff-journal",
        title="Т—Ж (редакционные материалы)",
        kind=KIND_BIBLIO,
        url="https://journal.tinkoff.ru",
        document_paths=(),
        licence=Licence(
            name="all rights reserved",
            attribution="Редакция Т—Ж",
            permits_analysis=False,
            verified=False,
            note=("Права/robots/API не проверены: авто-анализ недоступен, "
                  "только ручной анализ человеком."),
        ),
        auto_check=False,
        counts_as_live=False,
        expected_format=FORMAT_NONE,
        lineage_id="bibliography:tinkoff-journal",
        note="Библиографическая ссылка для ручного анализа.",
    ),
    Source(
        source_id="bib-gramota",
        title="Грамота.ру",
        kind=KIND_BIBLIO,
        url="https://gramota.ru",
        licence=Licence(
            name="all rights reserved",
            attribution="Грамота.ру",
            permits_analysis=False,
            verified=False,
            note="Права/robots не проверены: только ручной анализ.",
        ),
        auto_check=False,
        counts_as_live=False,
        expected_format=FORMAT_NONE,
        lineage_id="bibliography:gramota",
        note="Библиографическая ссылка для ручного анализа.",
    ),
    Source(
        source_id="bib-textru",
        title="TEXT.RU",
        kind=KIND_BIBLIO,
        url="https://text.ru",
        licence=Licence(
            name="all rights reserved",
            attribution="TEXT.RU",
            permits_analysis=False,
            verified=False,
            note="Права/robots не проверены: только ручной анализ.",
        ),
        auto_check=False,
        counts_as_live=False,
        expected_format=FORMAT_NONE,
        lineage_id="bibliography:textru",
        note="Библиографическая ссылка для ручного анализа.",
    ),
    Source(
        source_id="bib-yurova",
        title="Статья Юровой (редакционный разбор)",
        kind=KIND_BIBLIO,
        url="",
        licence=Licence(
            name="unknown",
            attribution="",
            permits_analysis=False,
            verified=False,
            note=("Точный адрес публикации и права не подтверждены: "
                  "никакого авто-доступа, только ручной анализ."),
        ),
        auto_check=False,
        counts_as_live=False,
        expected_format=FORMAT_NONE,
        lineage_id="bibliography:yurova",
        note="Библиографическая ссылка; URL не подтверждён и не выдуман.",
    ),
)

_BY_ID: dict[str, Source] = {src.source_id: src for src in SOURCES}


def all_sources() -> tuple[Source, ...]:
    """Весь реестр в стабильном порядке (5 рабочих + 4 reference)."""
    return SOURCES


def get_source(source_id: str) -> Source | None:
    return _BY_ID.get(str(source_id or ""))


def select_sources(*, enabled_only: bool = True,
                   auto_check_only: bool = True) -> tuple[Source, ...]:
    """Источники, которые участвуют в автоматических проверках.

    ``enabled_only`` учитывает только дефолт реестра; фактическая
    включённость — ``anticliche_source_state.enabled`` (см. ``state_enabled``).
    """
    out = []
    for src in SOURCES:
        if auto_check_only and not src.auto_check:
            continue
        if enabled_only and not src.enabled_by_default:
            continue
        out.append(src)
    return tuple(out)


def state_enabled(source: Source, state: dict | None) -> bool:
    """Фактическая включённость: PG-строка важнее дефолта реестра."""
    if state and isinstance(state.get("enabled"), bool):
        return bool(state["enabled"])
    return bool(source.enabled_by_default)


def status_meta(status: str) -> dict:
    """Подпись/тон/группа статуса. Неизвестный статус — не «зелёный»."""
    return STATUS_LABELS.get(
        str(status or ""),
        {"label": "Неизвестное состояние", "tone": "warn", "group": "error"})


def is_problem(status: str) -> bool:
    return str(status or "") in PROBLEM_STATUSES


def is_success(status: str) -> bool:
    return str(status or "") in SUCCESS_STATUSES


# ── классификация ответа ───────────────────────────────────────────────────
def _header(headers, name: str) -> str:
    if not headers:
        return ""
    try:
        for key, value in headers.items():
            if str(key).lower() == name:
                return str(value or "")
    except AttributeError:      # pragma: no cover — headers не mapping
        return ""
    return ""


def _looks_like_rate_limit(headers, body: str) -> bool:
    remaining = _header(headers, "x-ratelimit-remaining")
    if remaining.strip() == "0":
        return True
    if _header(headers, "retry-after"):
        return True
    text = str(body or "").lower()
    return ("rate limit" in text or "too many requests" in text
            or "api rate limit exceeded" in text)


def _looks_like_policy_block(headers, body: str) -> bool:
    for name in _POLICY_HEADERS:
        value = _header(headers, name).lower()
        if value and any(marker in value for marker in _POLICY_MARKERS):
            return True
    text = str(body or "").lower()
    return any(marker in text for marker in _POLICY_MARKERS)


def classify_response(*, status: int, headers=None, body: str = "") -> str:
    """HTTP-ответ → честный внутренний статус §3.2.

    Порядок важен: 403 сам по себе НЕ означает обход robot-policy. Он
    становится ``policy_blocked`` только при положительном признаке политики
    (тело/заголовок), иначе это ``auth_failed`` (тест 6 §9.2). Rate-limit
    сигналы (``x-ratelimit-remaining: 0`` / ``Retry-After``) сильнее 403 —
    GitHub отдаёт лимит именно так.
    """
    code = int(status or 0)
    if code == 304:
        return STATUS_UNCHANGED
    if code == 429:
        return STATUS_RATE_LIMITED
    if 200 <= code < 300:
        return STATUS_AVAILABLE
    if code in (401, 403):
        if _looks_like_rate_limit(headers, body):
            return STATUS_RATE_LIMITED
        if code == 401:
            return STATUS_AUTH_FAILED
        if _looks_like_policy_block(headers, body):
            return STATUS_POLICY_BLOCKED
        return STATUS_AUTH_FAILED
    # Wikimedia отдаёт блокировку политики и кодом 400 в action API.
    if code == 400 and _looks_like_policy_block(headers, body):
        return STATUS_POLICY_BLOCKED
    if code in (404, 410):
        return STATUS_MISSING
    # 5xx и прочие транспортные коды — «ошибка соединения» с реальным
    # http_status рядом (не подменяем код на «успех»).
    return STATUS_NETWORK_ERROR


def classify_exception(exc: BaseException | None) -> str:
    """Исключение транспорта → статус (timeout/DNS/TLS → network_error)."""
    if exc is None:
        return STATUS_NETWORK_ERROR
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
        return STATUS_INTERNAL_ERROR
    name = type(exc).__name__.lower()
    if "cancel" in name:
        return STATUS_INTERNAL_ERROR
    return STATUS_NETWORK_ERROR


# ── retry / cooldown ───────────────────────────────────────────────────────
def parse_retry_after(value, *, now: datetime.datetime | None = None
                      ) -> datetime.datetime | None:
    """``Retry-After`` (секунды или HTTP-date) → абсолютное UTC-время."""
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds < 0:
            return None
        return moment + datetime.timedelta(seconds=seconds)
    try:
        from email.utils import parsedate_to_datetime
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def compute_backoff_seconds(policy: RetryPolicy, failures: int, *,
                            rng: random.Random | None = None) -> int:
    """Bounded экспоненциальный backoff с jitter (не бесконечный рост)."""
    attempt = max(1, int(failures or 1))
    base = max(1, int(policy.base_seconds))
    cap = max(base, int(policy.max_seconds))
    delay = min(cap, base * (2 ** min(attempt - 1, 16)))
    jitter = max(0.0, float(policy.jitter or 0.0))
    if jitter:
        generator = rng or random
        spread = int(delay * jitter)
        if spread > 0:
            delay += generator.randint(0, spread)
    return max(1, min(cap, delay))


def compute_next_attempt(status: str, policy: RetryPolicy, failures: int, *,
                         retry_after_at: datetime.datetime | None = None,
                         now: datetime.datetime | None = None,
                         rng: random.Random | None = None
                         ) -> tuple[datetime.datetime | None, str]:
    """Следующая попытка и её причина для конкретного исхода.

    * ``policy_blocked`` → автоматических попыток нет (``None``) либо
      ограниченный ``policy_cooldown_seconds``; никакого «через час ещё раз»
      по умолчанию.
    * ``rate_limited`` → ровно ``Retry-After`` (в пределах максимума) или
      bounded backoff, если заголовка нет.
    * успех/``disabled`` → ``None``.
    """
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    code = str(status or "")
    if code == STATUS_POLICY_BLOCKED:
        cooldown = policy.policy_cooldown_seconds
        if not cooldown:
            return None, "policy_blocked"
        return moment + datetime.timedelta(seconds=int(cooldown)), \
            "policy_cooldown"
    if code == STATUS_DISABLED:
        return None, "disabled"
    if code in SUCCESS_STATUSES:
        return None, "scheduled"
    if code == STATUS_RATE_LIMITED:
        if policy.respect_retry_after and retry_after_at is not None:
            limit = max(1, int(policy.max_retry_after_seconds))
            candidate = retry_after_at
            ceiling = moment + datetime.timedelta(seconds=limit)
            if candidate > ceiling:
                candidate = ceiling
            if candidate <= moment:
                return moment + datetime.timedelta(seconds=1), "retry_after"
            return candidate, "retry_after"
        return (moment + datetime.timedelta(
            seconds=compute_backoff_seconds(policy, failures, rng=rng)),
            "backoff")
    if code in PROBLEM_STATUSES:
        return (moment + datetime.timedelta(
            seconds=compute_backoff_seconds(policy, failures, rng=rng)),
            "backoff")
    return None, "scheduled"


def _as_utc(value) -> datetime.datetime | None:
    if value is None:
        return None
    moment = value
    if isinstance(moment, str):
        try:
            moment = datetime.datetime.fromisoformat(
                moment.strip().replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    if not isinstance(moment, datetime.datetime):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment


def attempt_decision(state: dict | None, *, policy: RetryPolicy | None = None,
                     now: datetime.datetime | None = None,
                     manual: bool = False) -> dict:
    """Разрешена ли попытка прямо сейчас (анти-storm, §3.3).

    ``manual=True`` — явное намерение владельца («Проверить доступ»): одна
    проверка разрешена даже для ``policy_blocked``, но это НЕ обход политики —
    запрос тот же, User-Agent/IP/прокси не меняются.
    """
    row = state or {}
    status = str(row.get("last_status") or STATUS_UNCHECKED)
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    if manual:
        return {"allowed": True, "reason": "manual", "wait_seconds": 0}
    paused = str(row.get("paused_reason") or "")
    if status == STATUS_POLICY_BLOCKED or paused == "policy_blocked":
        policy_obj = policy or RetryPolicy()
        cooldown = policy_obj.policy_cooldown_seconds
        next_at = _as_utc(row.get("next_attempt_at"))
        if not cooldown:
            return {"allowed": False, "reason": "policy_blocked",
                    "wait_seconds": None}
        if next_at is not None and next_at > moment:
            return {"allowed": False, "reason": "policy_cooldown",
                    "wait_seconds": int((next_at - moment).total_seconds())}
    next_at = _as_utc(row.get("next_attempt_at"))
    if next_at is not None and next_at > moment:
        return {"allowed": False, "reason": "backoff",
                "wait_seconds": int((next_at - moment).total_seconds())}
    return {"allowed": True, "reason": "due", "wait_seconds": 0}


def freshness_state(last_check_at, *, days: int,
                    now: datetime.datetime | None = None) -> str:
    """``current`` / ``stale`` / ``unknown`` — отдельная пометка свежести.

    Порог берётся из действующей политики refresh (``REFRESH_DAYS``),
    собственного конфига не вводится. ``stale`` никогда не заменяет
    транспортный статус: старая зелёная проверка не считается доступностью
    «прямо сейчас».
    """
    moment = _as_utc(last_check_at)
    if moment is None:
        return "unknown"
    current = now or datetime.datetime.now(datetime.timezone.utc)
    limit = max(1, int(days or 1))
    return ("current" if (current - moment) < datetime.timedelta(days=limit)
            else "stale")


# ── разбор содержимого (готовность контента) ───────────────────────────────
def checksum_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


_HTML_MARKERS = ("<!doctype html", "<html", "<head>", "<body")


def assess_markdown(body: str) -> dict:
    """Markdown-документ: пригоден ли к разбору.

    HTML вместо Markdown и пустой файл — это НЕ «готово к анализу»
    (§3.2: HTTP 200 при пустом/битом файле не является готовностью).
    Короткий, но непустой документ остаётся пригодным с предупреждением.
    """
    text = str(body or "")
    stripped = text.strip()
    lowered = stripped[:400].lower()
    if not stripped:
        return {"usable": False, "status": "empty", "chars": 0,
                "reason": "empty_document"}
    if any(marker in lowered for marker in _HTML_MARKERS):
        return {"usable": False, "status": STATUS_PARSE_ERROR,
                "chars": len(stripped), "reason": "html_instead_of_markdown"}
    short = len(stripped) < MIN_USABLE_CHARS
    return {"usable": True, "status": "parsed", "chars": len(stripped),
            "reason": "short_document" if short else ""}


def assess_json(body: str) -> dict:
    text = str(body or "").strip()
    if not text:
        return {"usable": False, "status": "empty", "chars": 0,
                "reason": "empty_document"}
    try:
        json.loads(text)
    except (ValueError, TypeError):
        return {"usable": False, "status": STATUS_PARSE_ERROR,
                "chars": len(text), "reason": "invalid_json"}
    return {"usable": True, "status": "parsed", "chars": len(text),
            "reason": ""}


def parse_wiki_extract(payload) -> str | None:
    """Wikipedia action API JSON → extract (или ``None``, если его нет)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict):
        return None
    pages = (payload.get("query") or {}).get("pages") or {}
    if isinstance(pages, dict):
        for page in pages.values():
            extract = page.get("extract") if isinstance(page, dict) else None
            if isinstance(extract, str) and extract.strip():
                return extract
    return None


def assess_wiki(body: str) -> dict:
    """Wiki action API: JSON обязателен, иначе контент не разобран.

    Невалидный JSON = ``parse_error`` (тест 8 §9.2), а не «транспорт ок,
    значит всё готово». Пустой extract = «нет пригодного содержимого».
    """
    text = str(body or "")
    stripped = text.strip()
    try:
        parsed = json.loads(stripped) if stripped else None
    except (ValueError, TypeError):
        lowered = stripped[:400].lower()
        reason = ("html_instead_of_json"
                  if any(marker in lowered for marker in _HTML_MARKERS)
                  else "invalid_json")
        return {"usable": False, "status": STATUS_PARSE_ERROR,
                "chars": len(stripped), "reason": reason, "text": None}
    if not isinstance(parsed, dict):
        return {"usable": False, "status": STATUS_PARSE_ERROR,
                "chars": len(stripped), "reason": "invalid_json",
                "text": None}
    extract = parse_wiki_extract(parsed)
    if extract is None:
        # Валидный JSON без extract: страница не найдена/переименована.
        pages = (parsed.get("query") or {}).get("pages") or {}
        missing = any(isinstance(page, dict) and page.get("missing") is not None
                      for page in (pages.values()
                                   if isinstance(pages, dict) else []))
        return {"usable": False,
                "status": STATUS_MISSING if missing else STATUS_PARSE_ERROR,
                "chars": len(stripped),
                "reason": "document_missing" if missing else "no_extract",
                "text": None}
    if not extract.strip():
        return {"usable": False, "status": "empty", "chars": 0,
                "reason": "no_usable_content", "text": None}
    short = len(extract.strip()) < MIN_USABLE_CHARS
    return {"usable": True, "status": "parsed", "chars": len(extract),
            "reason": "short_document" if short else "", "text": extract}


# ── транспорт (единственный) ───────────────────────────────────────────────
@dataclass
class TransportResponse:
    """Один реальный HTTP-ответ (или его отсутствие)."""

    status: int = 0
    headers: dict = field(default_factory=dict)
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= int(self.status or 0) < 300

    @property
    def bytes(self) -> int:
        return len(str(self.text or "").encode("utf-8"))


async def fetch_document(url: str, *, headers: dict | None = None,
                         timeout: float = HTTP_TIMEOUT_SECONDS
                         ) -> TransportResponse:
    """GET документа с честным User-Agent (без маскировки, §9.2 тест 3)."""
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update({str(k): str(v) for k, v in headers.items()})
    try:
        async with httpx.AsyncClient(timeout=timeout,
                                     follow_redirects=True) as client:
            response = await client.get(url, headers=request_headers)
    except Exception as exc:
        log_external_api(
            logger, provider=_host_label(url), method="GET", url=url,
            status=0, reason="fetch_exception",
            body=f"{type(exc).__name__}", level=logging.ERROR)
        return TransportResponse(error=type(exc).__name__)
    status = int(getattr(response, "status_code", 0) or 0)
    text = ""
    try:
        text = response.text
    except Exception:      # pragma: no cover — defensive
        text = ""
    response_headers = {}
    try:
        response_headers = {str(k): str(v)
                            for k, v in dict(response.headers).items()}
    except Exception:      # pragma: no cover — defensive
        response_headers = {}
    if status >= 400:
        log_external_api(
            logger, provider=_host_label(url), method="GET", url=url,
            status=status, reason="fetch_http", body=text,
            level=logging.ERROR)
    elif not 200 <= status < 300:
        log_external_api(
            logger, provider=_host_label(url), method="GET", url=url,
            status=status, reason="fetch_unexpected", body=text,
            level=logging.WARNING)
    return TransportResponse(status=status, headers=response_headers,
                             text=str(text or ""))


def _host_label(url: str) -> str:
    try:
        return urlsplit(str(url or "")).hostname or "source"
    except Exception:      # pragma: no cover — defensive
        return "source"


async def fetch_source_text(url: str) -> str:
    """Текст источника (Wikipedia action API JSON → extract).

    Сохранён ради существующего контракта `anticliche_worker.fetch_source`;
    реализация одна — `fetch_document`.
    """
    response = await fetch_document(url)
    if response.status >= 400 or response.error:
        raise RuntimeError(
            f"source fetch failed: status={response.status} "
            f"error={response.error or 'http'}")
    if not 200 <= response.status < 300:
        raise RuntimeError(f"source fetch unexpected: status={response.status}")
    extract = parse_wiki_extract(response.text)
    if extract:
        return extract
    return str(response.text or "")


# ── проверка источника ─────────────────────────────────────────────────────
def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def utc_now() -> datetime.datetime:
    """Публичный «сейчас» (UTC) — для read-моделей и тестов."""
    return _now()


def _iso(moment: datetime.datetime | None) -> str | None:
    return moment.astimezone(datetime.timezone.utc).isoformat() \
        if moment is not None else None


def new_check_id() -> str:
    return uuid.uuid4().hex[:16]


def _base_check(source: Source, *, now: datetime.datetime) -> dict:
    return {
        "check_id": new_check_id(),
        "source_id": source.source_id,
        "checked_at": _iso(now),
        "kind": source.kind,
        "transport": "http" if source.is_http else (
            "local" if source.is_local else "none"),
        "status": STATUS_UNCHECKED,
        "http_status": None,
        "revision": "",
        "etag": "",
        "checksum": "",
        "changed": False,
        "docs_fetched": 0,
        "docs_parsed": 0,
        "bytes": 0,
        "chars": 0,
        "content_status": "not_checked",
        "documents": [],
        "error_code": "",
        "error_detail": "",
        "retry_after": None,
        "warnings": [],
        "text": "",
        "hidden": False,
    }


def _finish(check: dict, source: Source, state: dict | None, *,
            now: datetime.datetime, rng: random.Random | None) -> dict:
    """Дозаполнить проверку: next_attempt_at, счётчик сбоев, paused_reason."""
    previous = state or {}
    failures = int(previous.get("consecutive_failures") or 0)
    status = str(check.get("status") or STATUS_UNCHECKED)
    if is_success(status):
        failures = 0
    elif is_problem(status):
        failures += 1
    policy = source.retry
    next_at, reason = compute_next_attempt(
        status, policy, failures,
        retry_after_at=_as_utc(check.get("retry_after")),
        now=now, rng=rng)
    check["consecutive_failures"] = failures
    check["next_attempt_at"] = _iso(next_at)
    check["next_attempt_reason"] = reason
    check["paused_reason"] = reason if status == STATUS_POLICY_BLOCKED else ""
    check["status_label"] = status_meta(status)["label"]
    check["status_tone"] = status_meta(status)["tone"]
    return check


def _doc_entry(path: str, *, status: str, reason: str = "", chars: int = 0,
               bytes_len: int = 0, http_status: int | None = None,
               checksum: str = "", url: str = "") -> dict:
    return {"path": path, "status": status, "reason": reason, "chars": chars,
            "bytes": bytes_len, "http_status": http_status,
            "checksum": checksum, "url": url}


async def _check_local(source: Source, check: dict, *, pg) -> dict:
    """``local/manual``: без HTTP — «локальный/доступно» либо «ошибка БД»."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    check["http_status"] = None
    check["content_status"] = "not_applicable"
    if pool is None:
        check["status"] = STATUS_DB_ERROR
        check["error_code"] = "pg_unavailable"
        check["error_detail"] = "PostgreSQL недоступен"
        return check
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        check["status"] = STATUS_DB_ERROR
        check["error_code"] = "pg_unavailable"
        check["error_detail"] = type(exc).__name__
        return check
    check["status"] = STATUS_AVAILABLE
    check["changed"] = True
    return check


async def _http_get(check: dict, url: str, *, headers: dict | None,
                    transport) -> TransportResponse:
    if transport is None:
        return await fetch_document(url, headers=headers)
    result = transport(url, headers)
    if asyncio.iscoroutine(result):
        result = await result
    if isinstance(result, TransportResponse):
        return result
    # Обратная совместимость: инъекция «url → текст» (старые тесты/воркер).
    return TransportResponse(status=200, headers={}, text=str(result or ""))


async def check_source(source: Source, *, transport=None, pg=None,
                       state: dict | None = None,
                       now: datetime.datetime | None = None,
                       manual: bool = False,
                       rng: random.Random | None = None) -> dict:
    """Одна реальная попытка проверки источника → ``SourceCheck``.

    Никогда не бросает: сбой источника/сети/парсинга возвращается статусом,
    а не исключением (независимость источников, §3.3).
    """
    moment = now or _now()
    check = _base_check(source, now=moment)
    if source.is_bibliography or not source.auto_check:
        check["status"] = STATUS_DISABLED
        check["error_code"] = ("bibliography_only" if source.is_bibliography
                               else "auto_check_disabled")
        check["content_status"] = "not_applicable"
        return _finish(check, source, state, now=moment, rng=rng)
    enabled = state_enabled(source, state)
    if not enabled and not manual:
        check["status"] = STATUS_DISABLED
        check["error_code"] = "disabled"
        check["content_status"] = "not_applicable"
        return _finish(check, source, state, now=moment, rng=rng)
    try:
        if source.is_local:
            check = await _check_local(source, check, pg=pg)
            return _finish(check, source, state, now=moment, rng=rng)
        if source.kind == KIND_GITHUB:
            check = await _check_github(source, check, state=state,
                                        transport=transport, now=moment)
        elif source.kind == KIND_WIKI:
            check = await _check_wiki(source, check, state=state,
                                      transport=transport, now=moment)
        else:
            check = await _check_http_documents(source, check, state=state,
                                                transport=transport,
                                                now=moment)
    except Exception as exc:      # изоляция сбоя одного источника
        logger.warning("[anticliche] source check failed | source=%s | %s",
                       source.source_id, type(exc).__name__)
        check["status"] = STATUS_INTERNAL_ERROR
        check["error_code"] = "check_exception"
        check["error_detail"] = type(exc).__name__
        check["content_status"] = "not_checked"
    return _finish(check, source, state, now=moment, rng=rng)


async def _check_wiki(source: Source, check: dict, *, state: dict | None,
                      transport, now: datetime.datetime) -> dict:
    headers = {}
    etag = str((state or {}).get("etag") or "")
    if etag:
        headers["If-None-Match"] = etag
    response = await _http_get(check, source.url, headers=headers,
                               transport=transport)
    check["http_status"] = int(response.status or 0) or None
    if response.error:
        check["status"] = classify_exception(
            RuntimeError(response.error))
        check["error_code"] = str(response.error or "transport")
        return check
    status = classify_response(status=response.status,
                               headers=response.headers, body=response.text)
    check["status"] = status
    check["retry_after"] = parse_retry_after(
        _header(response.headers, "retry-after"), now=now)
    if status == STATUS_UNCHANGED:
        check["content_status"] = "unchanged"
        check["revision"] = str((state or {}).get("revision") or "")
        check["etag"] = etag
        check["checksum"] = str((state or {}).get("checksum") or "")
        return check
    if status != STATUS_AVAILABLE:
        check["error_code"] = status
        return check
    etag_new = _header(response.headers, "etag")
    if etag_new:
        check["etag"] = etag_new
    assessed = assess_wiki(response.text)
    check["bytes"] = response.bytes
    check["chars"] = int(assessed.get("chars") or 0)
    check["content_status"] = assessed["status"]
    check["documents"] = [_doc_entry(
        source.document_paths[0] if source.document_paths else source.source_id,
        status=assessed["status"], reason=assessed.get("reason", ""),
        chars=check["chars"], bytes_len=response.bytes,
        http_status=response.status,
        checksum=checksum_text(response.text))]
    check["docs_fetched"] = 1
    check["docs_parsed"] = 1 if assessed["usable"] else 0
    check["checksum"] = checksum_text(assessed.get("text") or response.text)
    check["revision"] = check["etag"] or check["checksum"][:40]
    if not assessed["usable"]:
        check["status"] = (STATUS_PARSE_ERROR
                           if assessed["status"] == STATUS_PARSE_ERROR
                           else STATUS_AVAILABLE)
        check["error_code"] = assessed.get("reason", "") or "no_usable_content"
        check["text"] = ""
        return check
    previous_checksum = str((state or {}).get("checksum") or "")
    if previous_checksum and previous_checksum == check["checksum"]:
        check["status"] = STATUS_UNCHANGED
        check["content_status"] = "unchanged"
        check["changed"] = False
        check["text"] = ""
        return check
    check["changed"] = True
    check["text"] = str(assessed.get("text") or "")
    return check


async def _check_github(source: Source, check: dict, *, state: dict | None,
                        transport, now: datetime.datetime) -> dict:
    """GitHub: реальная ревизия, ожидаемые пути, лицензия и тела документов.

    Read-only запросы к публичному API (репозиторий → коммит → дерево) плюс
    по одному GET на ожидаемый файл. Формат проверяется детерминированно;
    отделение примеров клише от пояснений — задача AC-PIPE.
    """
    slug = source.origin_repo
    api = f"https://api.github.com/repos/{slug}"
    repo_resp = await _http_get(check, api, headers=None, transport=transport)
    check["http_status"] = int(repo_resp.status or 0) or None
    if repo_resp.error:
        check["status"] = classify_exception(RuntimeError(repo_resp.error))
        check["error_code"] = str(repo_resp.error or "transport")
        return check
    status = classify_response(status=repo_resp.status,
                               headers=repo_resp.headers, body=repo_resp.text)
    check["retry_after"] = parse_retry_after(
        _header(repo_resp.headers, "retry-after"), now=now)
    if status not in (STATUS_AVAILABLE, STATUS_UNCHANGED):
        check["status"] = status
        check["error_code"] = status
        return check
    try:
        repo = json.loads(repo_resp.text or "{}")
    except (ValueError, TypeError):
        repo = {}
    if not isinstance(repo, dict) or not repo:
        check["status"] = STATUS_PARSE_ERROR
        check["error_code"] = "invalid_json"
        return check
    branch = str(repo.get("default_branch") or "main")
    commits_resp = await _http_get(
        check, f"{api}/commits?per_page=1", headers=None, transport=transport)
    revision = ""
    committed_at = ""
    if commits_resp.error:
        check["status"] = classify_exception(RuntimeError(commits_resp.error))
        check["error_code"] = str(commits_resp.error or "transport")
        return check
    commit_status = classify_response(status=commits_resp.status,
                                      headers=commits_resp.headers,
                                      body=commits_resp.text)
    if commit_status in (STATUS_AVAILABLE, STATUS_UNCHANGED):
        try:
            commits = json.loads(commits_resp.text or "[]")
        except (ValueError, TypeError):
            commits = None
        if isinstance(commits, list) and commits and isinstance(commits[0],
                                                                dict):
            revision = str(commits[0].get("sha") or "")
            committed_at = str(
                ((commits[0].get("commit") or {}).get("committer") or {})
                .get("date") or "")
    elif commit_status != STATUS_MISSING:
        check["status"] = commit_status
        check["error_code"] = commit_status
        return check
    check["revision"] = revision
    check["revision_committed_at"] = committed_at
    licence = (repo.get("license") or {}) if isinstance(repo, dict) else {}
    check["licence_spdx"] = str(licence.get("spdx_id") or "")
    # Ожидаемые пути: одно дерево, без поштучных запросов.
    missing: list[str] = []
    present: list[str] = []
    if source.document_paths:
        tree_resp = await _http_get(
            check, f"{api}/git/trees/{branch}?recursive=1", headers=None,
            transport=transport)
        if tree_resp.error:
            check["status"] = classify_exception(
                RuntimeError(tree_resp.error))
            check["error_code"] = str(tree_resp.error or "transport")
            return check
        tree_status = classify_response(status=tree_resp.status,
                                        headers=tree_resp.headers,
                                        body=tree_resp.text)
        if tree_status not in (STATUS_AVAILABLE, STATUS_UNCHANGED):
            check["status"] = tree_status
            check["error_code"] = tree_status
            return check
        try:
            tree = json.loads(tree_resp.text or "{}")
        except (ValueError, TypeError):
            tree = {}
        nodes = {}
        if isinstance(tree, dict):
            for node in tree.get("tree") or []:
                if isinstance(node, dict) and node.get("path"):
                    nodes[str(node["path"])] = node
        for path in source.document_paths:
            if path in nodes:
                present.append(path)
            else:
                missing.append(path)
    check["bytes"] = int(repo_resp.bytes or 0)
    if not present:
        check["documents"] = [
            _doc_entry(path, status=STATUS_MISSING, reason="path_not_found")
            for path in missing
        ]
        check["docs_fetched"] = 0
        check["content_status"] = "empty"
        check["status"] = STATUS_MISSING
        check["error_code"] = "no_expected_documents"
        return check
    collected = await fetch_source_documents(
        source, revision=revision or branch, transport=transport)
    documents = [doc for doc in collected["documents"]
                 if doc.get("status") != STATUS_MISSING]
    documents += [_doc_entry(path, status=STATUS_MISSING,
                             reason="path_not_found") for path in missing]
    check["documents"] = documents
    check["docs_fetched"] = int(collected["documents_fetched"])
    check["docs_parsed"] = int(collected["documents_parsed"])
    check["bytes"] = int(check["bytes"] or 0) + int(collected["bytes"] or 0)
    check["chars"] = int(collected["chars"] or 0)
    check["checksum"] = checksum_text(
        f"{slug}:{revision}:" + ",".join(
            f"{doc['path']}:{doc['checksum']}" for doc in documents))
    if collected["documents_parsed"] <= 0:
        check["status"] = (collected["worst_status"]
                           if collected["worst_status"] in PROBLEM_STATUSES
                           else STATUS_PARSE_ERROR)
        check["content_status"] = collected["content_status"]
        check["error_code"] = "no_parsable_documents"
        return check
    usable = collected["worst_status"] in (STATUS_AVAILABLE, STATUS_UNCHANGED)
    check["content_status"] = "parsed" if usable and not missing else (
        "partial" if usable else STATUS_PARSE_ERROR)
    previous_revision = str((state or {}).get("revision") or "")
    previous_checksum = str((state or {}).get("checksum") or "")
    if revision and previous_revision and revision == previous_revision \
            and (not previous_checksum
                 or previous_checksum == check["checksum"]):
        check["status"] = STATUS_UNCHANGED
        check["content_status"] = "unchanged"
        check["changed"] = False
        check["text"] = ""
        return check
    check["status"] = STATUS_AVAILABLE
    check["changed"] = True
    if missing:
        check["warnings"].append(f"missing_paths={len(missing)}")
    check["text"] = str(collected["text"] or "")
    return check


async def _check_http_documents(source: Source, check: dict, *,
                                state: dict | None, transport,
                                now: datetime.datetime) -> dict:
    """Обычный документ-источник: по одному реальному GET на путь."""
    paths = source.document_paths or (source.source_id,)
    documents: list[dict] = []
    parsed = 0
    total_bytes = 0
    combined: list[str] = []
    worst = STATUS_AVAILABLE
    content_worst = ""
    content_reason = ""
    for path in paths:
        if source.origin_repo:
            url = raw_document_url(source, path, "main")
        elif len(paths) == 1:
            url = source.url
        else:
            url = f"{str(source.url).rstrip('/')}/{str(path).lstrip('/')}"
        headers = {}
        try:
            response = await _http_get(check, url, headers=headers,
                                       transport=transport)
        except Exception as exc:
            status = classify_exception(exc)
            documents.append(_doc_entry(path, status=status,
                                        reason=type(exc).__name__, url=url))
            if worst in (STATUS_AVAILABLE, STATUS_UNCHANGED):
                worst = status
            continue
        status = (classify_exception(RuntimeError(response.error))
                  if response.error else
                  classify_response(status=response.status,
                                    headers=response.headers,
                                    body=response.text))
        retry_after = parse_retry_after(
            _header(response.headers, "retry-after"), now=now)
        if retry_after is not None:
            check["retry_after"] = retry_after
        if response.status:
            check["http_status"] = int(response.status)
        total_bytes += int(response.bytes or 0)
        if status in (STATUS_AVAILABLE, STATUS_UNCHANGED):
            if response.status == 304:
                documents.append(_doc_entry(path, status=STATUS_UNCHANGED,
                                            reason="not_modified"))
                continue
            if source.expected_format == FORMAT_JSON:
                assessed = assess_json(response.text)
            else:
                assessed = assess_markdown(response.text)
            doc_status = assessed["status"]
            doc = _doc_entry(path, status=doc_status,
                             reason=assessed.get("reason", ""),
                             chars=int(assessed.get("chars") or 0),
                             bytes_len=response.bytes,
                             http_status=response.status,
                             checksum=checksum_text(response.text), url=url)
            documents.append(doc)
            if assessed["usable"]:
                parsed += 1
                combined.append(response.text)
            else:
                # «Пусто» и «формат не распознан» — разные факты контента.
                if doc_status == STATUS_PARSE_ERROR:
                    content_worst = STATUS_PARSE_ERROR
                elif not content_worst:
                    content_worst = "empty"
                if not content_reason:
                    content_reason = str(assessed.get("reason") or "")
            continue
        documents.append(_doc_entry(path, status=status, reason=status,
                                    http_status=response.status, url=url))
        if worst in (STATUS_AVAILABLE, STATUS_UNCHANGED):
            worst = status
    check["documents"] = documents
    check["bytes"] = total_bytes
    check["docs_fetched"] = len(documents)
    check["docs_parsed"] = parsed
    payload = "\n".join(combined)
    check["chars"] = len(payload)
    check["checksum"] = checksum_text(payload) if payload else ""
    if parsed == 0:
        missing = sum(1 for d in documents if d["status"] == STATUS_MISSING)
        check["status"] = (STATUS_MISSING if missing == len(documents)
                           else worst if worst in PROBLEM_STATUSES
                           else STATUS_PARSE_ERROR)
        check["content_status"] = content_worst or "empty"
        check["error_code"] = content_reason or check["status"]
        return check
    if worst in PROBLEM_STATUSES:
        check["status"] = worst
        check["error_code"] = worst
        check["warnings"].append("partial_documents")
    else:
        check["status"] = STATUS_AVAILABLE
    previous_checksum = str((state or {}).get("checksum") or "")
    if previous_checksum and previous_checksum == check["checksum"]:
        check["status"] = STATUS_UNCHANGED
        check["content_status"] = "unchanged"
        check["changed"] = False
        check["text"] = ""
        return check
    check["changed"] = True
    check["content_status"] = "parsed"
    check["text"] = payload
    return check


def raw_document_url(source: Source, path: str, ref: str) -> str:
    """Публичный raw-URL документа на конкретной ревизии."""
    if not source.origin_repo:
        return source.url
    keep = str(ref or "main").strip() or "main"
    return (f"https://raw.githubusercontent.com/{source.origin_repo}/"
            f"{keep}/{str(path).lstrip('/')}")


async def fetch_source_documents(source: Source, *, revision: str = "",
                                 transport=None,
                                 max_chars: int = 60000) -> dict:
    """Операция ``fetch`` адаптера: тела документов источника (§4.2 Stage A).

    Возвращает ``{text, documents, documents_fetched, documents_parsed,
    bytes, chars, content_status}``. Содержимое каждого документа проверяется
    на формат (markdown/HTML/JSON), но НЕ интерпретируется: отделение
    примеров клише от пояснений — задача AC-PIPE.
    """
    ref = str(revision or "main").strip() or "main"
    paths = source.document_paths or ((source.source_id,) if source.is_http
                                      else ())
    documents: list[dict] = []
    payload: list[str] = []
    total_bytes = 0
    parsed = 0
    worst = STATUS_AVAILABLE
    for path in paths:
        if source.origin_repo:
            url = raw_document_url(source, path, ref)
        elif len(paths) == 1:
            url = source.url
        else:
            url = f"{str(source.url).rstrip('/')}/{str(path).lstrip('/')}"
        try:
            response = await _http_get({}, url, headers=None,
                                       transport=transport)
        except Exception as exc:
            documents.append(_doc_entry(path,
                                        status=classify_exception(exc),
                                        reason=type(exc).__name__, url=url))
            worst = classify_exception(exc)
            continue
        if response.error:
            documents.append(_doc_entry(path, status=STATUS_NETWORK_ERROR,
                                        reason=str(response.error), url=url))
            worst = STATUS_NETWORK_ERROR
            continue
        status = classify_response(status=response.status,
                                   headers=response.headers,
                                   body=response.text)
        total_bytes += int(response.bytes or 0)
        if status not in (STATUS_AVAILABLE, STATUS_UNCHANGED):
            documents.append(_doc_entry(path, status=status, reason=status,
                                        http_status=response.status, url=url))
            if worst == STATUS_AVAILABLE:
                worst = status
            continue
        if source.expected_format == FORMAT_JSON:
            assessed = assess_json(response.text)
        elif source.expected_format == FORMAT_WIKI_JSON:
            assessed = assess_wiki(response.text)
        else:
            assessed = assess_markdown(response.text)
        documents.append(_doc_entry(
            path, status=assessed["status"], reason=assessed.get("reason", ""),
            chars=int(assessed.get("chars") or 0),
            bytes_len=response.bytes, http_status=response.status,
            checksum=checksum_text(response.text), url=url))
        if assessed["usable"]:
            parsed += 1
            body = assessed.get("text")
            payload.append(str(body if body is not None else response.text))
        elif assessed["status"] == STATUS_PARSE_ERROR \
                and worst == STATUS_AVAILABLE:
            worst = STATUS_PARSE_ERROR
    text = "\n\n".join(payload)[:max(0, int(max_chars))]
    content_status = ("parsed" if parsed and worst == STATUS_AVAILABLE
                      else "partial" if parsed else "empty")
    return {
        "text": text,
        "documents": documents,
        "documents_fetched": len(documents),
        "documents_parsed": parsed,
        "bytes": total_bytes,
        "chars": len(text),
        "content_status": content_status,
        "worst_status": worst,
    }


def summarize_checks(checks: list[dict]) -> dict:
    """Сводка реальных проверок по статусам (AC-MET-SOURCE-CHECKS)."""
    counts = {
        "total": len(checks),
        "ok": 0,
        "unchanged": 0,
        "blocked": 0,
        "limited": 0,
        "errors": 0,
        "unchecked": 0,
    }
    last_success = None
    for check in checks:
        status = str(check.get("status") or "")
        if status == STATUS_AVAILABLE:
            counts["ok"] += 1
            last_success = check.get("checked_at")
        elif status == STATUS_UNCHANGED:
            counts["unchanged"] += 1
            last_success = check.get("checked_at")
        elif status in (STATUS_POLICY_BLOCKED, STATUS_AUTH_FAILED):
            counts["blocked"] += 1
        elif status == STATUS_RATE_LIMITED:
            counts["limited"] += 1
        elif status in IDLE_STATUSES:
            counts["unchecked"] += 1
        else:
            counts["errors"] += 1
    counts["last_success_at"] = last_success
    return counts


async def check_sources(sources, *, transport=None, pg=None,
                        states: dict[str, dict] | None = None,
                        now: datetime.datetime | None = None,
                        manual: bool = False, max_parallel: int = 3,
                        rng: random.Random | None = None,
                        record: bool = True) -> list[dict]:
    """Независимые проверки: сбой одного не мешает остальным (§3.3).

    Параллелизм ограничен (транспортная гигиена), но каждая проверка
    изолирована: исключение превращается в статус этого источника.
    """
    moment = now or _now()
    known_states = states or {}
    limit = max(1, int(max_parallel or 1))
    semaphore = asyncio.Semaphore(limit)

    async def _run(source: Source) -> dict:
        state = known_states.get(source.source_id)
        async with semaphore:
            check = await check_source(
                source, transport=transport, pg=pg, state=state, now=moment,
                manual=manual, rng=rng)
        if record and pg is not None:
            await record_check(pg, check, source=source, previous=state)
        emit_check_event(check)
        return check

    tasks = [asyncio.create_task(_run(src)) for src in sources]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[dict] = []
    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            fallback = _base_check(source, now=moment)
            fallback["status"] = STATUS_INTERNAL_ERROR
            fallback["error_code"] = "check_exception"
            fallback["error_detail"] = type(result).__name__
            out.append(_finish(fallback, source, known_states.get(
                source.source_id), now=moment, rng=rng))
        else:
            out.append(result)
    return out


def emit_check_event(check: dict) -> None:
    """История проверки — существующий журнал событий (``mca_events``).

    Один терминальный outcome на одну реальную попытку: история пишется тем
    же механизмом, что и остальные mca-события (никакой второй логгер).
    """
    status = str(check.get("status") or "")
    if status in SUCCESS_STATUSES:
        outcome, level = "success", "INFO"
    elif status in IDLE_STATUSES:
        outcome, level = "skipped", "INFO"
    else:
        outcome, level = "failed", "WARN"
    reason_code = {
        STATUS_MISSING: "source_missing",
        STATUS_RATE_LIMITED: "rate_limit",
        STATUS_POLICY_BLOCKED: "cooldown",
        STATUS_DISABLED: "disabled",
        STATUS_PARSE_ERROR: "parse_error",
        STATUS_UNCHECKED: "stage_skipped",
    }.get(status)
    fields = {
        "component": "anticliche",
        "stage": "source_check",
        "status": status,
        "operation_id": str(check.get("check_id") or ""),
        "attempt": int(check.get("consecutive_failures") or 0) + 1,
        "reason_code": reason_code,
    }
    if check.get("duration_ms") is not None:
        fields["duration_ms"] = int(check["duration_ms"])
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event("anticliche_source_checked", outcome=outcome,
                       level=level, **fields)
    except Exception:      # fail-open: журнал не рвёт проверку
        pass
    try:
        from services.agentic_events import emit_agentic_event
        emit_agentic_event(
            "ANTI_CLICHE_SOURCE_CHECK", source=check.get("source_id"),
            status=status, http=check.get("http_status"),
            docs=check.get("docs_parsed"), failures=check.get(
                "consecutive_failures"))
    except Exception:      # fail-open
        pass


# ── хранилище последней проверки (PG) ──────────────────────────────────────
_STATE_COLUMNS = (
    "source_id", "enabled", "last_check_at", "last_status", "last_http",
    "revision", "etag", "checksum", "content_status", "docs_fetched",
    "docs_parsed", "bytes_fetched", "last_success_fetch_at",
    "last_success_analysis_at", "last_analysis_status", "next_attempt_at",
    "last_error_code", "last_error_detail", "consecutive_failures",
    "paused_reason", "last_check_id", "updated_at",
)
_SELECT_STATE_SQL = (
    "SELECT " + ", ".join(_STATE_COLUMNS) + " FROM anticliche_source_state")
_UPSERT_STATE_SQL = (
    "INSERT INTO anticliche_source_state ("
    + ", ".join(_STATE_COLUMNS[:-1]) + ") VALUES ("
    + ", ".join(f"${i}" for i in range(1, len(_STATE_COLUMNS))) + ") "
    "ON CONFLICT (source_id) DO UPDATE SET "
    "enabled = EXCLUDED.enabled, "
    "last_check_at = EXCLUDED.last_check_at, "
    "last_status = EXCLUDED.last_status, "
    "last_http = EXCLUDED.last_http, "
    "revision = EXCLUDED.revision, "
    "etag = EXCLUDED.etag, "
    "checksum = EXCLUDED.checksum, "
    "content_status = EXCLUDED.content_status, "
    "docs_fetched = EXCLUDED.docs_fetched, "
    "docs_parsed = EXCLUDED.docs_parsed, "
    "bytes_fetched = EXCLUDED.bytes_fetched, "
    "last_success_fetch_at = COALESCE(EXCLUDED.last_success_fetch_at, "
    "anticliche_source_state.last_success_fetch_at), "
    "last_success_analysis_at = COALESCE(EXCLUDED.last_success_analysis_at, "
    "anticliche_source_state.last_success_analysis_at), "
    "last_analysis_status = EXCLUDED.last_analysis_status, "
    "next_attempt_at = EXCLUDED.next_attempt_at, "
    "last_error_code = EXCLUDED.last_error_code, "
    "last_error_detail = EXCLUDED.last_error_detail, "
    "consecutive_failures = EXCLUDED.consecutive_failures, "
    "paused_reason = EXCLUDED.paused_reason, "
    "last_check_id = EXCLUDED.last_check_id, "
    "updated_at = now()"
)


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


def _row_to_state(row) -> dict:
    try:
        data = dict(row)
    except (TypeError, ValueError):      # pragma: no cover — defensive
        return {}
    return {key: data.get(key) for key in _STATE_COLUMNS
            if key in data or key == "enabled"}


async def fetch_states(pg) -> dict[str, dict]:
    """Все строки состояния источников. Fail-open: нет PG → ``{}``."""
    pool = _pool(pg)
    if pool is None:
        return {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_STATE_SQL)
    except Exception:
        logger.warning("[anticliche] source states read failed — fail-open",
                       exc_info=True)
        return {}
    out: dict[str, dict] = {}
    for row in rows or []:
        state = _row_to_state(row)
        source_id = str(state.get("source_id") or "")
        if source_id:
            out[source_id] = state
    return out


async def fetch_state(pg, source_id: str) -> dict | None:
    states = await fetch_states(pg)
    return states.get(str(source_id or ""))


async def record_check(pg, check: dict, *, source: Source | None = None,
                       previous: dict | None = None,
                       enabled: bool | None = None) -> None:
    """Upsert последней проверки. Сбой записи не «улучшает» статус."""
    pool = _pool(pg)
    if pool is None:
        return
    target = source or get_source(str(check.get("source_id") or ""))
    if previous is None:
        previous = await fetch_state(pg, str(check.get("source_id") or ""))
    state_enabled_value = (enabled if enabled is not None
                           else state_enabled(target, previous)
                           if target is not None else True)
    success = is_success(str(check.get("status") or ""))
    previous_analysis_at = (previous or {}).get("last_success_analysis_at")
    previous_analysis_status = str(
        (previous or {}).get("last_analysis_status") or "never")
    params = (
        str(check.get("source_id") or ""),
        bool(state_enabled_value),
        _as_utc(check.get("checked_at")),
        str(check.get("status") or STATUS_UNCHECKED),
        int(check["http_status"]) if check.get("http_status") else None,
        str(check.get("revision") or ""),
        str(check.get("etag") or ""),
        str(check.get("checksum") or ""),
        str(check.get("content_status") or "not_checked"),
        int(check.get("docs_fetched") or 0),
        int(check.get("docs_parsed") or 0),
        int(check.get("bytes") or 0),
        _as_utc(check.get("checked_at")) if success else None,
        _as_utc(previous_analysis_at),
        previous_analysis_status,
        _as_utc(check.get("next_attempt_at")),
        str(check.get("error_code") or ""),
        str(check.get("error_detail") or "")[:200],
        int(check.get("consecutive_failures") or 0),
        str(check.get("paused_reason") or ""),
        str(check.get("check_id") or ""),
    )
    try:
        async with pool.acquire() as conn:
            await conn.execute(_UPSERT_STATE_SQL, *params)
    except Exception:
        logger.warning("[anticliche] source state write failed | source=%s",
                       check.get("source_id"), exc_info=True)


async def set_enabled(pg, source_id: str, enabled: bool) -> bool:
    """Per-source control (§5.5): влияет только на будущий опрос.

    Не удаляет исторические правила и не трогает owner-pinned. Возвращает
    фактическое значение (при недоступном PG — исходное, без обмана).
    """
    source = get_source(source_id)
    if source is None:
        return False
    pool = _pool(pg)
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO anticliche_source_state (source_id, enabled) "
                "VALUES ($1, $2) ON CONFLICT (source_id) DO UPDATE SET "
                "enabled = EXCLUDED.enabled, updated_at = now()",
                str(source_id), bool(enabled))
    except Exception:
        logger.warning("[anticliche] source enable write failed | source=%s",
                       source_id, exc_info=True)
        return False
    return True


# ── read-модели для админки (UI — отдельный пакет) ─────────────────────────
def source_view(source: Source, state: dict | None, *,
                now: datetime.datetime | None = None,
                freshness_days: int = 7) -> dict:
    """Честный профиль источника (§8.3): четыре независимых поля, не ``status``.

    ``analysis`` и ``published`` заполняются тем, что реально известно;
    неизвестное — ``None`` (не выдуманный ноль).
    """
    row = state or {}
    moment = now or _now()
    status = str(row.get("last_status") or STATUS_UNCHECKED)
    if source.is_bibliography:
        # Справочник для ручного анализа: не «поломка» и не HTTP-источник.
        display_status = STATUS_DISABLED
        meta = {"label": BIBLIO_LABEL, "tone": "neutral",
                "group": "reference"}
    elif not state_enabled(source, state) and status in SUCCESS_STATUSES:
        # Явно выключенный источник не выдаём за «проверенный и здоровый».
        display_status = STATUS_DISABLED
        meta = status_meta(display_status)
    else:
        display_status = status
        meta = status_meta(display_status)
    last_check_at = row.get("last_check_at")
    return {
        "source_id": source.source_id,
        "title": source.title,
        "enabled": state_enabled(source, state),
        "kind": source.kind,
        "type": source.kind,
        "transport": "http" if source.is_http else (
            "local" if source.is_local else "none"),
        "url": source.url,
        "document_paths": list(source.document_paths),
        "status": display_status,
        "status_label": meta["label"],
        "status_tone": meta["tone"],
        "status_group": meta["group"],
        "reachability": {
            "status": display_status,
            "label": meta["label"],
            "checked_at": _iso(_as_utc(last_check_at)),
            "http_status": row.get("last_http"),
            "transport_code": ("local" if source.is_local else
                               row.get("last_http")),
            "revision": str(row.get("revision") or ""),
            "etag": str(row.get("etag") or ""),
            "freshness": freshness_state(last_check_at, days=freshness_days,
                                         now=moment),
        },
        "content": {
            "status": str(row.get("content_status") or "not_checked"),
            "documents_fetched": row.get("docs_fetched"),
            "documents_parsed": row.get("docs_parsed"),
            "bytes": row.get("bytes_fetched"),
            "checksum": str(row.get("checksum") or ""),
        },
        "analysis": {
            "status": str(row.get("last_analysis_status") or "not_run"),
            "last_success_at": _iso(_as_utc(
                row.get("last_success_analysis_at"))),
            "documents_analyzed": None,
            "model_ref": None,
            "proposals": None,
            "run_id": None,
        },
        "last_success_fetch_at": _iso(_as_utc(
            row.get("last_success_fetch_at"))),
        "next_attempt_at": _iso(_as_utc(row.get("next_attempt_at"))),
        "next_attempt_reason": str(row.get("paused_reason") or ""),
        "last_error": ({"code": str(row.get("last_error_code") or ""),
                        "detail": str(row.get("last_error_detail") or "")}
                       if row.get("last_error_code") else None),
        "consecutive_failures": int(row.get("consecutive_failures") or 0),
        "licence": source.as_dict()["licence"],
        "counts_as_live": source.counts_as_live,
        "analysis_eligible": source.analysis_eligible,
        "auto_check": source.auto_check,
        "lineage_id": source.lineage_id,
        "origin_repo": source.origin_repo,
        "upstream_bases": list(source.upstream_bases),
        "note": source.note,
        "activation_note": source.activation_note,
        "retry_policy": source.as_dict()["retry_policy"],
    }


def build_views(states: dict[str, dict] | None = None, *,
                sources: tuple[Source, ...] | None = None,
                now: datetime.datetime | None = None,
                freshness_days: int = 7) -> list[dict]:
    known = states or {}
    return [source_view(src, known.get(src.source_id), now=now,
                        freshness_days=freshness_days)
            for src in (sources if sources is not None else SOURCES)]


def summarize(views: list[dict]) -> dict:
    """Сводка вкладки «Источники»: правильные знаменатели (§5.5).

    ``local/manual`` и библиография не входят в числитель «живых сетевых
    источников»; «не проверялись» — отдельная категория, а не «проблема».
    """
    live = [v for v in views if v.get("counts_as_live")]
    local = [v for v in views if not v.get("counts_as_live")
             and v.get("transport") == "local"]
    refs = [v for v in views if v.get("kind") == KIND_BIBLIO]
    checked = [v for v in live if v.get("status") not in IDLE_STATUSES]
    available = [v for v in live if v.get("status") == STATUS_AVAILABLE]
    unchanged = [v for v in live if v.get("status") == STATUS_UNCHANGED]
    limited = [v for v in live if v.get("status") == STATUS_RATE_LIMITED]
    problems = [v for v in live if is_problem(v.get("status"))]
    blocked = [v for v in live
               if v.get("status") in (STATUS_POLICY_BLOCKED,
                                      STATUS_AUTH_FAILED)]
    unchecked = [v for v in live if v.get("status") == STATUS_UNCHECKED]
    disabled = [v for v in views if v.get("status") == STATUS_DISABLED
                and v.get("kind") != KIND_BIBLIO]
    stale = [v for v in live
             if (v.get("reachability") or {}).get("freshness") == "stale"]
    last_check = None
    for view in live:
        moment = _as_utc((view.get("reachability") or {}).get("checked_at"))
        if moment is not None and (last_check is None or moment > last_check):
            last_check = moment
    return {
        "total_live": len(live),
        "checked": len(checked),
        "unchecked": len(unchecked),
        "available": len(available) + len(unchanged),
        "available_changed": len(available),
        "unchanged": len(unchanged),
        "limited": len(limited),
        "blocked": len(blocked),
        "problems": len(problems),
        "disabled": len(disabled),
        "stale": len(stale),
        "local_sources": len(local),
        "references": len(refs),
        "last_check_at": _iso(last_check),
        "denominators": {
            "live_http": len(live),
            "local": len(local),
            "references": len(refs),
            "notes": ("local/manual и библиография не участвуют в знаменателе "
                      "живых сетевых источников"),
        },
    }


def analysis_readiness(views: list[dict]) -> dict:
    """Готовность анализа: отдельный вопрос (§2.2 п.3).

    Берётся только из фактических результатов анализа в состоянии источника;
    доступность источника сюда не подмешивается.
    """
    completed = []
    failed = []
    for view in views:
        block = view.get("analysis") or {}
        status = str(block.get("status") or "not_run")
        if status == "completed":
            completed.append(block)
        elif status in ("failed", "error"):
            failed.append(block)
    if completed:
        moments = [_as_utc(block.get("last_success_at"))
                   for block in completed if block.get("last_success_at")]
        moments = [m for m in moments if m is not None]
        return {"status": "completed",
                "last_success_at": _iso(max(moments)) if moments else None,
                "sources_completed": len(completed),
                "documents_analyzed": None,
                "model_ref": None,
                "proposals": None,
                "run_id": None}
    if failed:
        return {"status": "failed", "last_success_at": None,
                "sources_completed": 0, "documents_analyzed": None,
                "model_ref": None, "proposals": None, "run_id": None}
    return {"status": "not_run", "last_success_at": None,
            "sources_completed": 0, "documents_analyzed": None,
            "model_ref": None, "proposals": None, "run_id": None}


def reachability_health(views: list[dict]) -> dict:
    live = [v for v in views if v.get("counts_as_live")]
    if not live:
        return {"status": "unknown", "reason": "no_live_sources",
                "sources": {}}
    statuses = {v["source_id"]: v.get("status") for v in live}
    problems = [s for s in statuses.values() if is_problem(s)]
    unchecked = [s for s in statuses.values() if s in IDLE_STATUSES]
    if problems and len(problems) == len(live):
        overall = "blocked"
    elif problems:
        overall = "degraded"
    elif unchecked and len(unchecked) == len(live):
        overall = "unchecked"
    elif unchecked:
        overall = "partial"
    else:
        overall = "ok"
    return {"status": overall, "sources": statuses,
            "problems": len(problems), "unchecked": len(unchecked)}


def content_health(views: list[dict]) -> dict:
    live = [v for v in views if v.get("counts_as_live")]
    fetched = parsed = 0
    per_source: dict[str, dict] = {}
    for view in live:
        block = view.get("content") or {}
        fetched += int(block.get("documents_fetched") or 0)
        parsed += int(block.get("documents_parsed") or 0)
        per_source[view["source_id"]] = {
            "status": block.get("status"),
            "documents_fetched": block.get("documents_fetched"),
            "documents_parsed": block.get("documents_parsed"),
        }
    if fetched == 0:
        status = "unknown"
    elif parsed == 0:
        status = "failed"
    elif parsed < fetched:
        status = "partial"
    else:
        status = "ready"
    return {"status": status, "documents_fetched": fetched,
            "documents_parsed": parsed, "sources": per_source}


def runtime_health(active_version: dict | None, *, enabled: bool = True,
                   compiler: dict | None = None) -> dict:
    """Эффективность runtime: публикация + компилятор (§2.2 п.4).

    Отвечает на свой вопрос независимо от доступности источников: при живом
    опубликованном наборе runtime работает даже если все источники упали.
    """
    version = active_version or {}
    compiler_info = compiler or {"available": False, "module": "",
                                 "reason": "not_checked"}
    state = str(version.get("status") or "unavailable")
    rules = version.get("rules")
    number = version.get("version")
    blocked_by_compiler = not bool(compiler_info.get("available"))
    if not enabled:
        status, reason = "disabled", "anticliche_off"
    elif state == "unavailable":
        status, reason = "unavailable", version.get("reason") or "pg_unavailable"
    elif state == "none" or not number or not rules:
        # Отсутствие действующего набора — не ошибка, но и не «работает».
        status, reason = "no_published_rules", "no_published_snapshot" \
            if not number else "no_effective_rules"
    elif blocked_by_compiler:
        status, reason = "compiler_error", str(
            compiler_info.get("reason") or "compiler_unavailable")
    elif state == "ok":
        status, reason = "works", ""
    else:
        status, reason = "works_previous_version", str(
            version.get("reason") or "lkg")
    return {
        "status": status,
        "reason": reason,
        "active_version": number,
        "rules": rules,
        "published_at": version.get("published_at"),
        "bank_source": version.get("bank_source"),
        "compiler": compiler_info,
        "works": status in ("works", "works_previous_version"),
    }


def compiler_probe() -> dict:
    """Есть ли действующий компилятор подсказок (AC-COMPILER).

    Пакет AC-COMPILER ещё не реализован в этой ветке — тогда честно
    ``available=False`` и ``reason='not_installed'``, а не «работает».
    """
    module_name = "services.anticliche_compile"
    try:
        import importlib
        module = importlib.import_module(module_name)
    except Exception as exc:
        reason = ("not_installed" if isinstance(exc, ModuleNotFoundError)
                  else type(exc).__name__)
        return {"available": False, "module": module_name, "reason": reason,
                "state": "not_installed" if reason == "not_installed"
                else "error"}
    compile_hint = getattr(module, "compile_hint", None)
    if not callable(compile_hint):
        return {"available": False, "module": module_name,
                "reason": "compile_hint_missing", "state": "error"}
    version = str(getattr(module, "COMPILER_VERSION", "") or "")
    return {"available": True, "module": module_name, "version": version,
            "reason": "", "state": "ok"}


def build_health(views: list[dict], *, active_version: dict | None = None,
                 enabled: bool = True, compiler: dict | None = None) -> dict:
    """Четыре независимых вида здоровья (§2.2) — не один ``ok/error``."""
    return {
        "reachability": reachability_health(views),
        "content": content_health(views),
        "analysis": analysis_readiness(views),
        "runtime": runtime_health(active_version, enabled=enabled,
                                  compiler=compiler),
    }


def _lineage_node(value: str) -> str:
    """Нормализация узла lineage: ``repo:owner/name`` / ``wikipedia:slug``."""
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text.split("/", 1)[0]:
        return text
    if "/" in text:
        return f"repo:{text}"
    return text


def independent_confirmations(source_ids=None, *,
                              sources: tuple[Source, ...] | None = None
                              ) -> dict:
    """Сколько независимых подтверждений даёт набор источников (§3.1).

    Два URL ≠ два независимых подтверждения: форки/репосты одной upstream
    линии схлопываются в одну компоненту. Явно непроверенное происхождение
    остаётся видимым (``unverified_lineage``), чтобы UI не выдавал его за
    независимое подтверждение.
    """
    registry = sources if sources is not None else SOURCES
    wanted = set(source_ids) if source_ids is not None else None
    selected = [src for src in registry
                if wanted is None or src.source_id in wanted]
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for src in selected:
        node = _lineage_node(src.lineage_id) or f"source:{src.source_id}"
        find(node)
        bases = [src.origin_repo, *src.upstream_bases]
        for base in bases:
            normalised = _lineage_node(base)
            if normalised:
                union(node, normalised)
    groups: dict[str, list[str]] = {}
    for src in selected:
        node = _lineage_node(src.lineage_id) or f"source:{src.source_id}"
        groups.setdefault(find(node), []).append(src.source_id)
    unverified = [src.source_id for src in selected
                  if not src.upstream_bases]
    return {
        "independent": len(groups),
        "groups": groups,
        "unverified_lineage": unverified,
    }
