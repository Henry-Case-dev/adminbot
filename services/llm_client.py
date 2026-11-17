"""Epic 24 — OpenAI-compatible LLM client (R4/R5, Section 33.4).

One httpx.AsyncClient session per process (lazy creation, close() in on_shutdown).
Endpoints: POST {base_url}/chat/completions and POST {base_url}/embeddings.

Epic 47 (Section 56, D186/D187): ретраятся ВСЕ транзиентные ошибки —
httpx.TransportError (timeout/connect/read/write/pool/network/protocol) +
HTTP 408/425/429/5xx. Сон = `min(BASE*2**attempt, CAP) + U(0, JITTER)`;
для 429/5xx заголовок Retry-After приоритетнее backoff
(сон = min(header_seconds, CAP)); жёсткий total-budget
LLM_TOTAL_BUDGET = asyncio.timeout на всю _post; 401/403 → LLMAuthError
мгновенно. Единственный владелец ретраев — _post (56.4).

Epic 53 (Section 62, D216): классы LLMServerError/LLMTransportError (62.3.2),
диаг-лог финальных 5xx с body_5xx ≤500 (62.5), опциональный фоллбэк-провайдер
LLM_FALLBACK_* (62.4, пустые env = ровно старое поведение). CB живёт в
direct_chat_service (llm_client о нём НЕ знает — контракт 62.3).

P0 SMART transport (2.58.206): `LLM_TIMEOUT` — окно ОДНОГО HTTP-ответа
(180с по умолчанию), `LLM_TOTAL_BUDGET` — предел одной основной попытки со
всеми ретраями (360с), НЕ дедлайн исследования. Модель/адрес и политика
транспорта читаются из горячего конфига на входе каждого вызова и на входе
`_post`/stream (per-request `httpx.Timeout`, кэшированный httpx-клиент не
пересоздаётся); in-flight запрос держит снимок политики. Фоллбэк и
эмбеддинги имеют СВОИ окна (фоллбэк — `LLM_FALLBACK_TIMEOUT_SECONDS`,
эмбеддинги — min(policy, 60с)).
"""
import asyncio
import copy
import json
import logging
import random
import re
import time

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from config.settings import settings
from services import hot_config as hot
from services.status_service import status as status_service

logger = logging.getLogger(__name__)

# Хотфикс-3 (T-2501, ADR-1025-7 D4): лёгкие process-метрики доли таймаутов и
# fallback-срабатываний. R17-safe: только числа (без ключей/URL/содержимого).
# Снимок — `llm_stats()`; счётчики сбрасываются при рестарте процесса (этого
# достаточно для мониторинга «прямо сейчас» + лог-события для истории).
_LLM_STATS: dict[str, int] = {"requests": 0, "timeouts": 0, "fallbacks": 0,
                              "budget_exhausted": 0, "read_timeouts": 0}


def llm_stats() -> dict:
    """Снимок LLM-метрик: ``requests``/``timeouts``/``fallbacks`` + доля
    таймаутов (0.0 без запросов). T-2501: наблюдаемость корня A — хронических
    таймаутов провайдера (``nano-gpt.com``). P0 SMART transport: отдельно
    ``budget_exhausted`` (предел попытки/бюджет) и ``read_timeouts`` (провайдер
    не прислал HTTP-ответ в окно запроса) — чтобы отличать медленный ответ от
    исчерпанного бюджета."""
    requests = _LLM_STATS["requests"]
    timeouts = _LLM_STATS["timeouts"]
    fallbacks = _LLM_STATS["fallbacks"]
    return {
        "requests": requests,
        "timeouts": timeouts,
        "fallbacks": fallbacks,
        "budget_exhausted": _LLM_STATS["budget_exhausted"],
        "read_timeouts": _LLM_STATS["read_timeouts"],
        "timeout_share": (timeouts / requests) if requests else 0.0,
    }

_BODY_MAX_CHARS = 500   # Epic 49 (57.4) / Epic 53 (62.5): тело 4xx/5xx-ответа в диагн-логе
_AUTH_BODY_MAX_CHARS = 200   # Задача 2 (01.09.2026): тело 401/403 в LLMAuthError

# P0 SMART transport: технический потолок транспорта эмбеддингов. Чат-таймаут
# (180с) — про генерацию; «отпечатки» текста не должны висеть столько даже
# при ошибочно завышенном значении каталога.
_EMBED_TIMEOUT_CAP = 60.0
_MISSING = object()      # отличает «ключа нет в PG» от сохранённого None


def _policy_float(value, default: float, minimum: float) -> float:
    """Число политики транспорта: мусор/NaN/inf → default, иначе clamp.

    R17-safe: значения — тайминги, не секреты. Никогда не бросает."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(default)
    return max(float(minimum), parsed)


def _policy_int(value, default: int, minimum: int) -> int:
    """Целое политики транспорта: мусор → default, иначе clamp ≥ minimum."""
    if isinstance(value, bool):
        return int(default)
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return int(default)
    return max(int(minimum), parsed)

# R17: маскировка потенциальных секретов в телах ошибок провайдера.
# (а) ключ-значение: api key/key/token/secret/authorization (пробел допустим,
# \b-границы) + (б) известные префиксы ключей в ЛЮБОМ контексте
# (sk-/sk-or-/gsk_/tvly-/xoxb- и т.п.) + (в) Bearer <токен>.
# JSON-форма (ревью-блокер 01.09.2026): '"key" : "value"' — опциональная
# кавычка ДО двоеточия тоже в сепараторе; значение в кавычках — целиком.
# Ревью-фикс: re.IGNORECASE — bearer/basic в любом регистре + Token/Api-Key
# (контракт log_ring.py, там Bearer уже IGNORECASE). \b сохраняет guard:
# 'pot_token'/'access_token' НЕ маскируются (граница слова).
_SECRET_PAIR_RE = re.compile(
    r'(\b(?:api[\s_-]?key|key|token|secret|authorization)\b)'
    r'(\s*"?\s*[:=]\s*"?)(?!Bearer\b|Basic\b)([^"\s,}]{4,})',
    re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r'(?<![A-Za-z0-9])(?:sk|gsk|tvly|xoxb)[_-][A-Za-z0-9_-]{8,}',
    re.IGNORECASE)
_BEARER_RE = re.compile(r'(\bBearer\s+)[^\s,}"\']+', re.IGNORECASE)
_BASIC_RE = re.compile(r'(\bBasic\s+)[^\s,}"\']+', re.IGNORECASE)


def _mask_secrets(text: str) -> str:
    """Маскировка секретов (R17): Bearer/Basic <токен> (сначала — иначе
    пара authorization: Bearer … съест 'Bearer' как значение), пары
    ключ=значение (в т.ч. JSON-форма '"key": "value"'), префикс-ключи
    (sk-…/gsk_…/tvly-…/xoxb-…) → ***. Префикс bearer/basic сохраняется
    в исходном регистре (контракт log_ring.py)."""
    masked = _BEARER_RE.sub(r"\1***", text)
    masked = _BASIC_RE.sub(r"\1***", masked)
    masked = _SECRET_PAIR_RE.sub(r"\1\2***", masked)
    return _SECRET_VALUE_RE.sub("***", masked)


def _sanitize_snippet(text: str, max_chars: int = _AUTH_BODY_MAX_CHARS) -> str:
    """Обрезанное (≤200) тело ответа с маскировкой секретов — для
    LLMAuthError/диаг-логов 401/403 (R17). Пусто/не str → ""."""
    if not text:
        return ""
    masked = _mask_secrets(text)
    masked = masked.replace("\n", " ").replace("\r", " ").strip()
    return masked[:max_chars]


def _record_provider_call(*, payload: dict, messages, model: str,
                          provider: str, module: str | None, step: str | None,
                          correlation_id: str | None, chat_id: int | None,
                          channel: str = "primary", status: str = "ok",
                          error: str = "") -> None:
    """INS-TRACE/INS-EXACT: снимок РЕАЛЬНОГО запроса к провайдеру.

    Тексты маскируются каноническим маскером логов ДО записи (R17): журнал
    хранит структуру, хэши и санитизированный текст (owner-debug). Любой сбой
    журнала не влияет на вызов модели (fail-open, только warning).

    UR-C-CLOCK (UR-26.7): на каждом фактическом вызове логируются
    stage/module/chat_id/timezone/as_of_utc/config_version/clock_included и
    причина пропуска (без приватных текстов).
    """
    try:
        from services import prompt_composer as _pcomp
        masked_msgs = [{"role": str(m.get("role") or ""),
                        "content": _mask_secrets(str(m.get("content") or ""))}
                       for m in (messages or ()) if isinstance(m, dict)]
        _pcomp.record_provider_call(
            payload=payload, messages=masked_msgs, model=str(model or ""),
            provider=str(provider or ""), module=str(module or ""),
            step=str(step or ""), correlation_id=str(correlation_id or ""),
            chat_id=chat_id, channel=channel, status=status, error=error)
    except Exception:
        logger.warning("LLM provider trace failed — fail-open", exc_info=True)
    # UR-C-CLOCK (UR-26.7): observability часов на фактическом outbound
    # payload; R17-safe (только коды/числа). Fail-open.
    try:
        from services import chat_clock as _cclock
        _cclock.log_clock_call(module=str(module or ""), step=str(step or ""),
                               chat_id=chat_id, messages=(messages or ()),
                               channel=str(channel or "primary"))
    except Exception:
        pass


def _safe_exc_text(exc: BaseException, max_chars: int = 200) -> str:
    """T-2467 (ADR-1025-6 D4): R17-safe текст исключения для диаг-логов.

    У `httpx.ReadTimeout`/`asyncio.TimeoutError` `str(exc)` пуст — берём
    `repr`, чтобы лог не превращался в `error=ReadTimeout: `. Маскировка
    секретов (`_mask_secrets`), однострочно, с обрезкой. Никогда не бросает."""
    try:
        raw = str(exc) or repr(exc)
    except Exception:                              # pragma: no cover
        raw = ""
    raw = _mask_secrets(raw).replace("\n", " ").replace("\r", " ").strip()
    return raw[:max_chars] or type(exc).__name__


def _provider_host(base_url: str) -> str:
    """T-2467 (R17): только hostname провайдера — полный URL/креды в лог
    НЕ попадают (запрещено R17)."""
    try:
        return urlsplit(str(base_url or "")).hostname or "-"
    except ValueError:                             # pragma: no cover
        return "-"


async def _aclose(client: httpx.AsyncClient) -> None:
    try:
        await client.aclose()
    except Exception:  # pragma: no cover — закрытие старого клиента не критично
        pass

# Epic 53 (62.1): худший случай generate = бюджет primary + фоллбэк.
# Epic 64: бюджет фоллбэка больше НЕ константа 30с — настройка
# LLM_FALLBACK_TIMEOUT_SECONDS. Хотфикс-3 (T-2500, ADR-1025-7 D4, ревью M-2):
# fail-fast — дефолт снижен 120 → 60с. Это таймаут ОДНОЙ попытки фоллбэка
# (`asyncio.timeout` вокруг одного POST), НЕ суммарный бюджет цепочки; число
# ретраев (до 3 попыток) не менялось.


class LLMError(Exception):
    """Base error for all LLM client failures."""

    def __init__(self, *args, cause_class: str = "") -> None:
        super().__init__(*args)
        # EVOL-013: класс исходной транспортной причины — machine-readable
        # атрибут: downstream-классификация не парсит текст сообщения
        # (type(exc).__name__ самого LLM*-класса причину не передаёт).
        # Пусто — когда транспортной причины не было (бюджет/бизнес-ошибка).
        self.cause_class = str(cause_class or "")


class LLMAuthError(LLMError):
    """401/403 — invalid or missing API key."""


class LLMRateLimitError(LLMError):
    """429 — provider rate limit (retries exhausted)."""


class LLMTimeoutError(LLMError):
    """Request timed out (retries exhausted)."""


class LLMServerError(LLMError):
    """Epic 53 (62.3.2): исчерпание 5xx — устойчивый отказ апстрима.
    Текст без изменений: «LLM server error {code} after {N} attempts: {url}»."""


class LLMTransportError(LLMError):
    """Epic 53 (62.3.2): исчерпание не-timeout httpx.TransportError.
    Текст без изменений: «LLM transport error after {N} attempts: …»."""


class LLMBadResponseError(LLMError):
    """Malformed JSON or missing content in a 2xx response."""


class LLMContextOverflowError(LLMError):
    """SMART-EXECUTION-RELIABILITY-01 D6: провайдер отверг запрос из-за
    переполнения контекста (400/413 с structured reason).

    Несёт разобранную причину и план ограниченного восстановления:
    ``context_info`` (ContextOverflowInfo), ``context_recovery``
    (ContextRecoveryPlan | None), ``status``, ``body`` (in-memory, обрезанное
    тело ответа для диагностики — НЕ логируется), ``model``/``base_url``.
    Ёмкость endpoint/model к этому моменту уже обновлена
    (`model_capacity.record_proven_limit`), поэтому пересобранный payload
    считается по доказанному пределу. Наследник LLMError: существующие
    классификаторы/фолбэки продолжают работать. Текст сообщения — прежний
    (`LLM HTTP 400: <url>`, B1 ревью D): детали несут тип и атрибуты, а
    диагностический лог не меняется."""

    status: int | None = None
    body: str = ""
    model: str = ""
    base_url: str = ""
    context_info = None
    context_recovery = None


class NoApiKeyForChat(LLMError):
    """Раунд 10 (F-7 §5.2): у чата нет своего ключа, а глобальный
    недоступен ('forbidden' — запрет allow_global) или исчерпан ('budget').
    LLM НЕ вызывается: вызывающий отвечает sandbox-фразой
    content.no_key_reply (R16: тишины нет).
    F-15 (§3.1): аддитивный kwarg details — диагностический снапшот
    (resolve_path/day/used/limit — БЕЗ секретов, R17); дефолт None —
    существующие конструкторы/тесты не ломаются."""

    def __init__(self, chat_id: int, reason: str,
                 details: dict | None = None):
        self.chat_id = chat_id
        self.reason = reason
        self.details = details
        suffix = "" if not details else f" details={details!r}"
        super().__init__(
            f"no api key for chat: chat_id={chat_id} reason={reason}{suffix}")


# ── Задача 2 (2026-09-05): человекочитаемая причина embed/LLM-сбоя ─────────
# Статус извлекается из текста исключения (наши форматы: «HTTP 403»,
# «server error 502», «auth failed (401)», «status=429»…) или атрибута;
# затем классификация по типу/тексту. Русская строка — для WARNING-логов
# фоллбэка и печати в консоли вместо голого исключения.

_HTTP_STATUS_IN_MSG_RE = re.compile(
    r"\b(?:HTTP\s+|server error |auth failed \(|status=|rate limited \()(\d{3})\b")
_EMBED_TIMEOUT_RE = re.compile(
    r"timed? ?out|timeout|таймаут|завис", re.IGNORECASE)
_EMBED_TRANSPORT_RE = re.compile(
    r"transport|транспорт|соединение|connect|read error|недоступ", re.IGNORECASE)


def _embed_error_status(exc: BaseException) -> int | None:
    """HTTP-статус причины из атрибута исключения либо его текста."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 100 <= status < 1000:
        return status
    match = _HTTP_STATUS_IN_MSG_RE.search(str(exc))
    return int(match.group(1)) if match else None


def humanize_embed_error(exc: BaseException) -> str:
    """Понятная русская причина embed-сбоя: 401/403/429/5xx по статус-коду
    из текста/атрибутов исключения, затем таймаут/транспорт/битый ответ
    по типу и тексту. Незнакомое → общая строка (тип/код остаются в тексте
    исходного исключения, если оно печатается рядом)."""
    status = _embed_error_status(exc)
    if status == 401:
        return ("Ключ API не принят (401) — проверьте ключ основной модели "
                "памяти (и запасные ключи) в мини-аппе: «LLM Провайдеры» → "
                "«Эмбеддинги»")
    if status == 403:
        return ("Доступ запрещён (403): квота исчерпана или ключ без прав на "
                "эмбеддинги — пробуется запасной ключ; если исчерпаны все "
                "ключи — проверьте их в мини-аппе («LLM Провайдеры» → "
                "«Эмбеддинги»)")
    if status == 429:
        return ("Рейт-лимит (429) — воркер ждёт и повторит; если повторяется "
                "часто — снизьте --embed-concurrency")
    if status is not None and 500 <= status < 600:
        return "Облачный API нестабилен (5xx) — повтор с паузой"
    text = str(exc)
    name = type(exc).__name__.lower()
    if (isinstance(exc, (httpx.TimeoutException, TimeoutError))
            or "timeout" in name or _EMBED_TIMEOUT_RE.search(text)):
        return "Таймаут облачного API — повтор с паузой"
    if (isinstance(exc, httpx.TransportError)
            or "transport" in name or _EMBED_TRANSPORT_RE.search(text)):
        return "Сеть недоступна — проверьте соединение"
    if isinstance(exc, LLMBadResponseError) or "json" in text.lower() \
            or "data[].embedding" in text:
        return ("Ответ API не распознан (битый JSON или нет "
                "data[].embedding в ответе)")
    if status is not None and 400 <= status < 500:
        return (f"API отклонил запрос (HTTP {status}) — проверьте "
                f"конфигурацию/модель в мини-аппе «LLM Провайдеры» → "
                f"«Эмбеддинги»")
    return "Облачный API недоступен — см. детали выше"


# ── Эпик 04.09.2026 (3.3): результат generate_chat (Tool Calling) ──────────

@dataclass(frozen=True)
class LLMToolCall:
    """Один tool_call из ответа модели (3.3)."""

    id: str            # tool_call_id для role:"tool"
    name: str
    arguments: str     # JSON-строка аргументов (парсит исполнитель)

    def as_openai_dict(self) -> dict:
        """Сериализация для повторного запроса (assistant.tool_calls)."""
        return {"id": self.id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class LLMChatResult:
    """Разобранный ответ /chat/completions (generate_chat)."""

    content: str | None        # текст финального ответа (None при tool_calls)
    tool_calls: list[LLMToolCall] | None
    finish_reason: str | None
    # Раунд 10.20 (БЛОК 7.2a, ADR-1020-7 §2, T-1920): reasoning-черновик
    # reasoning-моделей (reasoning_content/reasoning/thinking). АДДИТИВНО,
    # default None — существующие конструкторы/тесты не ломаются.
    # Никогда не уходит пользователю (см. reply_postprocess).
    reasoning: str | None = None
    # UR-F шаг 1 (delivery snapshot, Q1): defensive copy последнего фактически
    # отправленного body (после primary/fallback). Только in-process: не
    # сериализуется и не логируется. ``None`` у двойников/старых конструкторов
    # → доставка не доказана (under-count, ложного кредита нет).
    sent_body: dict | None = None
    #: P0 L1 (2026-11-17): класс формы ответа по единому нормализатору
    #: (`text`|`tool_calls`|`reasoning_only`|…). Аддитивно: прежние
    #: конструкторы/двойники без поля получают `text`.
    response_kind: str = "text"


# EMBED-META-WIRE (CANARY-03): метаданные embed-ответа провайдера.
# Ключи совпадают с контрактом пробы совместимости
# (`embedding_control_plane._PROBE_METADATA_FIELDS`).
_EMPTY_EMBED_META: dict = {"model": None, "revision": None,
                           "params": None, "dims": None}


def _embed_response_meta(data, vectors) -> dict:
    """ФАКТИЧЕСКИЕ model/revision/params/dims из ТЕЛА ответа /embeddings.

    `model` НЕ подставляется из конфига: вопрос пробы — какую модель реально
    обслужил провайдер. Нет поля → `None` (неизвестность честно фиксируется
    потребителем как `*_known=False`, а не как несовместимость). Никогда не
    бросает: метаданные — побочный канал, а не условие успеха embed-вызова.
    """
    meta = dict(_EMPTY_EMBED_META)
    try:
        if isinstance(data, dict):
            model = data.get("model")
            if isinstance(model, str):
                meta["model"] = model.strip() or None
            revision = data.get("revision")
            if isinstance(revision, str):
                meta["revision"] = revision.strip() or None
            params = data.get("params")
            if isinstance(params, dict):
                meta["params"] = dict(params)
        first = vectors[0] if vectors else None
        if isinstance(first, (list, tuple)):
            meta["dims"] = len(first)
    except Exception:      # pragma: no cover — защитная ветка
        return dict(_EMPTY_EMBED_META)
    return meta


# ── UR-18 (UNIFIED-REPLY §7): структурированный результат генерации ────────
# Обратная совместимость: `generate()` остаётся текстовым фасадом над
# `generate_with_metadata()`; новые потребители получают объект с
# finish_reason/usage/max_output_tokens_sent и диагностикой fallback.

# ── P0 L1 (2026-11-17): классы исхода формы ответа (один нормализатор ниже) ─
RESPONSE_KIND_TEXT = "text"
RESPONSE_KIND_TOOL_CALLS = "tool_calls"
RESPONSE_KIND_REASONING_ONLY = "reasoning_only"
RESPONSE_KIND_TRUNCATED_REASONING = "truncated_reasoning"
RESPONSE_KIND_EMPTY = "empty"
RESPONSE_KIND_INVALID_CONTENT = "invalid_content"
RESPONSE_KIND_NO_CHOICES = "no_choices"
RESPONSE_KIND_PROVIDER_ERROR = "provider_error"
RESPONSE_KIND_INVALID_PAYLOAD = "invalid_payload"

#: Алиасы reasoning-черновика (провайдеры кладут его в разные поля).
_REASONING_ALIASES = ("reasoning_content", "reasoning", "thinking")

# Провайдерские эквиваленты «output оборван по лимиту длины» (нормализованные,
# т.е. уже strip().lower()): OpenAI/DeepSeek — 'length'; Anthropic — 'max_tokens'.
# Ничего не додумываем: значения вне этого сета остаются как есть.
_TRUNCATION_FINISH_REASONS = frozenset({"length", "max_tokens"})

# Поле finish_reason отсутствует/нестрока/пусто → честный 'unknown'.
# НЕ 'stop': незнакомое поле нельзя выдавать за штатное завершение (UR-18).
_FINISH_REASON_UNKNOWN = "unknown"


def is_truncation_finish_reason(value) -> bool:
    """``finish_reason`` сообщает НЕЗАКОНЧЕННЫЙ output (``length``/``max_tokens``).

    UR-19: единственная точка правды о провайдерских токенах обрезки. Сам
    клиент ничего не перегенерирует и не продолжает — решение принимает
    вызывающий (см. `services/l2_continuation.py`).
    """
    return str(value or "").strip().lower() in _TRUNCATION_FINISH_REASONS


@dataclass(frozen=True)
class LLMProviderAttempt:
    """UR-18: одна НОГА цепочки провайдеров в одном вызове generate.

    ``channel='primary'`` — основной провайдер, ``channel='fallback'`` —
    LLM_FALLBACK_*. Ретраи ВНУТРИ ноги (``_post``/LLM_MAX_RETRIES) отдельными
    ногами НЕ считаются: здесь только результат ноги, который видит generate.
    ``error_type is None`` → нога успешна.

    R17: ``error`` — ``_safe_exc_text`` (маскировка секретов, ≤200 симв.),
    без ключей и без полных URL.
    """

    channel: str
    model: str
    provider: str | None
    error_type: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_type is None

    def as_dict(self) -> dict:
        return {"channel": self.channel, "model": self.model,
                "provider": self.provider, "error_type": self.error_type,
                "error": self.error}


@dataclass(frozen=True)
class LLMCompletion:
    """UR-18: полный результат /chat/completions для новых потребителей.

    ``generate_with_metadata()`` отдаёт этот объект; ``generate()`` продолжает
    возвращать ``str`` (байт-в-байт для всех существующих вызовов).

    Гарантии:
    * ``text`` — ровно ``choices[0].message.content`` (как у ``generate()``);
    * ``finish_reason`` — нормализованный (strip + lower) токен провайдера;
      отсутствующее/нестроковое/пустое поле → ``"unknown"``, НЕ ``"stop"``;
    * ``finish_reason_raw`` — исходное значение провайдера без изменений
      (``None``, если поля не было);
    * ``provider``/``model`` — провайдер и модель, которые РЕАЛЬНО произвели
      текст (при срабатывании fallback — фоллбэк-нога);
    * ``usage`` — ``usage`` ответа как есть; отсутствует → ``None`` (не нули);
    * ``max_output_tokens_sent`` — ``max_tokens`` из фактически отправленного
      тела (после fallback-recompose); ключ не отправлялся → ``None``;
    * ``attempt`` — номер успешной ноги: 1 = primary, 2 = первый fallback;
    * ``correlation_id`` — проброшенный вызывающим id (``None`` → ``None``,
      не выдумывается);
    * ``fallback_chain`` — неуспешные ноги ДО успешной, в порядке выполнения.
    """

    text: str
    finish_reason: str
    provider: str | None
    model: str
    usage: dict | None
    max_output_tokens_sent: int | None
    attempt: int
    correlation_id: str | None
    fallback_chain: tuple[LLMProviderAttempt, ...] = ()
    finish_reason_raw: str | None = None
    #: UR-F шаг 1 (delivery snapshot, Q1): что ФАКТИЧЕСКИ ушло провайдеру
    #: (после primary/fallback и recompose). Только in-process.
    sent_body: dict | None = None
    #: P0 L1 (2026-11-17): нормализованный класс формы ответа (`text` для
    #: штатного текста) + длина reasoning-черновика (число, без содержимого).
    response_kind: str = RESPONSE_KIND_TEXT
    reasoning_chars: int = 0

    @property
    def fallback_used(self) -> bool:
        """True, когда текст произвела не primary-модель."""
        return self.attempt > 1

    @property
    def is_truncated(self) -> bool:
        """UR-18: ``length``/эквивалент = НЕЗАКОНЧЕННЫЙ output, а не готовый
        ответ. Это только статус: продолжение/отказ решает вызывающий
        (UR-19), сам llm_client ничего не перегенеряет."""
        return is_truncation_finish_reason(self.finish_reason)


def _choice_finish_reason(data) -> tuple[str, str | None]:
    """(нормализованный, сырой) finish_reason первого choice.

    Отсутствие/пустое/нестроковое значение → ``("unknown", None)``. Сырое
    значение сохраняется как есть (без lower/strip) для честной диагностики.
    """
    raw = None
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            raw = choices[0].get("finish_reason")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower(), raw.strip()
    return _FINISH_REASON_UNKNOWN, None


def _sent_body(sent, payload: dict) -> tuple[str, dict]:
    """Фактически отправленное тело: последняя запись ``sent`` либо payload.

    ``sent`` заполняют точки отправки (``_post``/``_post_fallback``) РОВНО теми
    телами, что ушли в HTTP; поэтому model/max_tokens берутся отсюда, а не из
    исходного payload (fallback подменяет model, adapter — messages).
    """
    if sent:
        channel, body = sent[-1]
        if isinstance(body, dict):
            return str(channel), body
    return "primary", payload if isinstance(payload, dict) else {}


def _sent_max_output_tokens(body: dict) -> int | None:
    """``max_tokens`` из отправленного тела; ключа нет/некорректный/<=0 → None."""
    try:
        value = int(body.get("max_tokens"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _context_overflow_exc(err: LLMError, *, status: int,
                          payload: dict, base_url: str
                          ) -> LLMContextOverflowError | None:
    """SMART D6: structured context-overflow → типизированная ошибка.

    Разбор и обновление ёмкости делает существующий `model_capacity`
    (`note_context_overflow`), сеть не используется, ключи/тело не
    логируются. Не-контекстная 400/413 → None (прежний LLMError)."""
    if status not in (400, 413, 422):
        return None
    model = str(payload.get("model") or "")
    try:
        from services import model_capacity as _mc
        reserve = None
        try:
            reserve = int(payload.get("max_tokens")) \
                if payload.get("max_tokens") else None
        except (TypeError, ValueError):
            reserve = None
        info, plan = _mc.note_context_overflow(
            err, base_url=base_url, model=model,
            output_reserve_tokens=reserve)
    except Exception:      # pragma: no cover - диагностика не рвёт ошибку
        logger.debug("LLM context-overflow parse failed", exc_info=True)
        return None
    if info is None:
        return None
    overflow = LLMContextOverflowError(str(err))
    overflow.status = status
    overflow.body = str(getattr(err, "body", "") or "")
    overflow.model = model or str(info.model or "")
    overflow.base_url = str(base_url or "")
    overflow.context_info = info
    overflow.context_recovery = plan
    return overflow


# ═══════════════════════════════════════════════════════════════════════════
# P0 L1 (2026-11-17) — ЕДИНЫЙ нормализатор ответа /chat/completions.
#
# Один разбор формы ответа для всех трёх потребителей (`generate_with_metadata`,
# `generate_chat`, `direct_l1.dedicated_generate`): content (строка/null/пустая/
# content-parts), reasoning-алиасы без финального текста, finish_reason,
# tool_calls, отсутствие choices и ошибка ВНУТРИ HTTP 200. Ничего не публикует
# и не логирует текст ответа/reasoning: только класс исхода и счётчики.
#
# Контракт исхода (ровно один класс):
#   text                 — есть непустой финальный текст (возможен truncated);
#   tool_calls           — текста нет, есть валидные tool_calls;
#   reasoning_only       — есть reasoning, финального текста нет (НЕ ответ);
#   truncated_reasoning  — reasoning + finish_reason=length|max_tokens;
#   empty                — content пуст/null без reasoning/tools;
#   invalid_content      — content неподдерживаемого типа;
#   no_choices           — choices отсутствуют/пусты/не список;
#   provider_error       — внутри HTTP 200 пришёл provider error payload;
#   invalid_payload      — ответ не JSON-объект.
# Reasoning никогда не становится `content` и не уходит как ответ.
# ═══════════════════════════════════════════════════════════════════════════

# ── Классы отказа вызова (единый taxonomy; R17 — коды, не тексты) ───────────
FAILURE_NO_KEY = "no_key"
FAILURE_RATE_LIMIT = "rate_limit"
FAILURE_AUTH = "auth"
FAILURE_INCOMPATIBLE_REQUEST = "incompatible_request"
FAILURE_BAD_REQUEST = "bad_request"
FAILURE_CONTEXT_OVERFLOW = "context_overflow"
FAILURE_SERVER_ERROR = "server_error"
FAILURE_TIMEOUT = "timeout"
FAILURE_DEADLINE_EXCEEDED = "deadline_exceeded"
FAILURE_CANCELLED = "cancelled"
FAILURE_BAD_RESPONSE = "bad_response"
FAILURE_TRANSPORT = "transport"
FAILURE_UNKNOWN = "unknown"

#: Параметры запроса, на которые провайдер отвечает «не поддерживается»
#: (4xx). Разбор по фактическому телу/тексту ответа, без имён моделей.
_INCOMPATIBLE_PARAMETERS = (
    ("max_completion_tokens", ("max_completion_tokens",)),
    ("max_tokens", ("max_tokens", "max_output_tokens")),
    ("temperature", ("temperature", "top_p")),
    ("response_format", ("response_format", "json mode", "json_mode",
                         "json_object", "structured output")),
)
_INCOMPATIBLE_HINTS = (
    "unsupported", "not supported", "unknown parameter", "unrecognized",
    "unexpected keyword", "invalid parameter", "not allowed", "does not support",
    "extra fields", "additional properties",
)


@dataclass(frozen=True)
class ChatResponse:
    """Нормализованный ответ /chat/completions (один класс исхода)."""

    kind: str
    content: str | None
    reasoning_chars: int
    tool_calls: tuple["LLMToolCall", ...]
    finish_reason: str
    finish_reason_raw: str | None
    usage: dict | None
    error_code: str | None
    content_parts: int = 0
    #: reasoning-черновик ТОЛЬКО для существующего in-process контракта
    #: `LLMChatResult.reasoning`; никогда не становится `content`, никогда не
    #: логируется (в события идут только `reasoning_chars`).
    reasoning: str | None = None

    @property
    def has_text(self) -> bool:
        return self.kind == RESPONSE_KIND_TEXT and bool(self.content)

    @property
    def truncated(self) -> bool:
        return is_truncation_finish_reason(self.finish_reason)

    @property
    def reasoning_only(self) -> bool:
        return self.kind in (RESPONSE_KIND_REASONING_ONLY,
                             RESPONSE_KIND_TRUNCATED_REASONING)

    def as_event_fields(self) -> dict:
        """R17-safe поля телеметрии (без текста/reasoning/ключей)."""
        return {
            "response_kind": self.kind,
            "finish_reason": self.finish_reason,
            "reasoning_chars": int(self.reasoning_chars),
            "tool_calls": len(self.tool_calls),
            "content_parts": int(self.content_parts),
            "error_code": self.error_code,
        }


def _content_text(value) -> tuple[str | None, int]:
    """content → ``(текст|None, число content-parts)``.

    * строка: пустая/пробельная → ``(None, 0)`` (не «ответ из пробелов»);
    * список content-parts: склеиваются ТОЛЬКО текстовые части (документ.
      форма OpenAI `{"type": "text", "text": ...}`); остальные типы
      игнорируются (изображения инструментов не становятся ответом);
    * None/иное → ``(None, 0)``."""
    if isinstance(value, str):
        text = value
        return (text if text.strip() else None), 0
    if isinstance(value, (list, tuple)):
        chunks: list[str] = []
        parts = 0
        for part in value:
            if isinstance(part, str):
                parts += 1
                if part.strip():
                    chunks.append(part)
                continue
            if not isinstance(part, dict):
                continue
            parts += 1
            part_type = str(part.get("type") or "text").strip().lower()
            if part_type not in ("text", "output_text", "input_text"):
                continue
            chunk = part.get("text")
            if isinstance(chunk, str) and chunk.strip():
                chunks.append(chunk)
        joined = "\n".join(chunks).strip()
        return (joined or None), parts
    return None, 0


def _parse_tool_calls(raw_calls) -> tuple["LLMToolCall", ...]:
    """Валидные tool_calls (без имени функции — malformed, не ответ)."""
    parsed: list[LLMToolCall] = []
    if not isinstance(raw_calls, (list, tuple)):
        return ()
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        parsed.append(LLMToolCall(
            id=str(call.get("id", "") or ""),
            name=name,
            arguments=str(function.get("arguments", "") or ""),
        ))
    return tuple(parsed)


def _provider_error_code(data: dict) -> tuple[str | None, str]:
    """Ошибка провайдера ВНУТРИ HTTP 200: ``(код, короткая причина)``."""
    error = data.get("error")
    if error is None:
        return None, ""
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("type") or "").strip()
        return (code[:48] or "provider_error"), "error_payload"
    if isinstance(error, str):
        return "provider_error", "error_payload"
    return "provider_error", "error_payload"


def classify_chat_response(data) -> ChatResponse:
    """Единый разбор формы ответа (pure; никогда не бросает).

    Один и тот же класс исхода для всех потребителей: «HTTP 200» сам по себе
    НЕ означает валидный ответ. Текст ответа/reasoning здесь только
    классифицируется и счётчиком измеряется — не логируется."""
    if not isinstance(data, dict):
        return ChatResponse(
            kind=RESPONSE_KIND_INVALID_PAYLOAD, content=None,
            reasoning_chars=0, tool_calls=(), finish_reason=_FINISH_REASON_UNKNOWN,
            finish_reason_raw=None, usage=None, error_code=None)
    error_code, _reason = _provider_error_code(data)
    if error_code:
        finish_reason, finish_raw = _choice_finish_reason(data)
        return ChatResponse(
            kind=RESPONSE_KIND_PROVIDER_ERROR, content=None,
            reasoning_chars=0, tool_calls=(), finish_reason=finish_reason,
            finish_reason_raw=finish_raw, usage=_usage_dict(data),
            error_code=error_code)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices \
            or not isinstance(choices[0], dict):
        return ChatResponse(
            kind=RESPONSE_KIND_NO_CHOICES, content=None, reasoning_chars=0,
            tool_calls=(), finish_reason=_FINISH_REASON_UNKNOWN,
            finish_reason_raw=None, usage=_usage_dict(data), error_code=None)
    choice = choices[0]
    finish_reason, finish_raw = _choice_finish_reason(data)
    usage = _usage_dict(data)
    message = choice.get("message")
    if not isinstance(message, dict):
        # choices есть, но сообщения нет — ответа нет (не пустой content).
        return ChatResponse(
            kind=RESPONSE_KIND_NO_CHOICES, content=None, reasoning_chars=0,
            tool_calls=(), finish_reason=finish_reason,
            finish_reason_raw=finish_raw, usage=usage, error_code=None)
    reasoning_chars = 0
    reasoning_text = None
    for alias in _REASONING_ALIASES:
        raw_reasoning = message.get(alias)
        if isinstance(raw_reasoning, str) and raw_reasoning.strip():
            reasoning_chars = len(raw_reasoning)
            reasoning_text = raw_reasoning
            break
    text, parts = _content_text(message.get("content"))
    tool_calls = _parse_tool_calls(message.get("tool_calls"))
    if text:
        return ChatResponse(
            kind=RESPONSE_KIND_TEXT, content=text,
            reasoning_chars=reasoning_chars, tool_calls=tool_calls,
            finish_reason=finish_reason, finish_reason_raw=finish_raw,
            usage=usage, error_code=None, content_parts=parts,
            reasoning=reasoning_text)
    raw_content = message.get("content")
    if raw_content is not None and not isinstance(raw_content, (str, list, tuple)):
        return ChatResponse(
            kind=RESPONSE_KIND_INVALID_CONTENT, content=None,
            reasoning_chars=reasoning_chars, tool_calls=tool_calls,
            finish_reason=finish_reason, finish_reason_raw=finish_raw,
            usage=usage, error_code=None, content_parts=parts,
            reasoning=reasoning_text)
    if tool_calls:
        return ChatResponse(
            kind=RESPONSE_KIND_TOOL_CALLS, content=None,
            reasoning_chars=reasoning_chars, tool_calls=tool_calls,
            finish_reason=finish_reason, finish_reason_raw=finish_raw,
            usage=usage, error_code=None, content_parts=parts,
            reasoning=reasoning_text)
    if reasoning_chars:
        kind = (RESPONSE_KIND_TRUNCATED_REASONING
                if is_truncation_finish_reason(finish_reason)
                else RESPONSE_KIND_REASONING_ONLY)
        return ChatResponse(
            kind=kind, content=None, reasoning_chars=reasoning_chars,
            tool_calls=(), finish_reason=finish_reason,
            finish_reason_raw=finish_raw, usage=usage, error_code=None,
            content_parts=parts, reasoning=reasoning_text)
    return ChatResponse(
        kind=RESPONSE_KIND_EMPTY, content=None, reasoning_chars=0,
        tool_calls=(), finish_reason=finish_reason,
        finish_reason_raw=finish_raw, usage=usage, error_code=None,
        content_parts=parts)


def _usage_dict(data) -> dict | None:
    usage = data.get("usage") if isinstance(data, dict) else None
    return usage if isinstance(usage, dict) else None


def usage_output_tokens(usage) -> tuple[int | None, int | None]:
    """``(completion_tokens, reasoning_tokens)`` из usage (None = не сообщено).

    Провайдеры кладут reasoning-токены в разные места
    (`completion_tokens_details.reasoning_tokens`); отсутствие поля — честный
    None, а не 0."""
    if not isinstance(usage, dict):
        return None, None
    completion = usage.get("completion_tokens")
    try:
        completion = int(completion) if completion is not None else None
    except (TypeError, ValueError):
        completion = None
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") \
        if isinstance(details, dict) else None
    try:
        reasoning = int(reasoning) if reasoning is not None else None
    except (TypeError, ValueError):
        reasoning = None
    return completion, reasoning


def incompatible_parameter(exc: BaseException) -> str | None:
    """Какой request-параметр провайдер отверг (только реальный 4xx-сигнал).

    Возвращает имя параметра либо ``None``. Источник — `status` и `body`
    исключения (in-memory, не логируется). Никаких догадок по имени модели:
    без 4xx и без явного маркера «unsupported/unknown parameter» → None."""
    status = getattr(exc, "status", None)
    if status not in (400, 404, 409, 415, 422):
        return None
    body = str(getattr(exc, "body", "") or "")
    text = f"{body} {exc}".lower()
    if not any(hint in text for hint in _INCOMPATIBLE_HINTS):
        return None
    for parameter, needles in _INCOMPATIBLE_PARAMETERS:
        if any(needle in text for needle in needles):
            return parameter
    return "unknown"


def classify_llm_failure(exc: BaseException, *,
                         body: str | None = None) -> str:
    """Единый класс отказа вызова (R17: код, не текст исключения).

    Владелец повтора остаётся у существующих слоёв: transport-ретраи — `_post`
    (единственный владелец), LLM-канал — `LLMClient`, L1 — матрица исхода
    хода. Эта функция только КЛАССИФИЦИРУЕТ, ничего не ретраит."""
    if isinstance(exc, asyncio.CancelledError):
        return FAILURE_CANCELLED
    if isinstance(exc, NoApiKeyForChat):
        return FAILURE_NO_KEY
    if isinstance(exc, LLMContextOverflowError):
        return FAILURE_CONTEXT_OVERFLOW
    if isinstance(exc, LLMRateLimitError):
        return FAILURE_RATE_LIMIT
    if isinstance(exc, LLMAuthError):
        return FAILURE_AUTH
    if isinstance(exc, LLMTimeoutError):
        cause = str(getattr(exc, "cause_class", "") or "")
        return (FAILURE_DEADLINE_EXCEEDED
                if cause == "budget" else FAILURE_TIMEOUT)
    if isinstance(exc, LLMServerError):
        return FAILURE_SERVER_ERROR
    if isinstance(exc, LLMBadResponseError):
        return FAILURE_BAD_RESPONSE
    if isinstance(exc, LLMTransportError):
        return FAILURE_TRANSPORT
    if isinstance(exc, LLMError):
        status = getattr(exc, "status", None)
        if status in (400, 404, 409, 415, 422) and incompatible_parameter(exc):
            return FAILURE_INCOMPATIBLE_REQUEST
        if status in (400, 404, 409, 415, 422):
            return FAILURE_BAD_REQUEST
        if status is not None:
            return FAILURE_UNKNOWN
        return FAILURE_UNKNOWN
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return FAILURE_TIMEOUT
    return FAILURE_UNKNOWN


class LLMClient:
    """Provider-agnostic async client for chat completions and embeddings."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        chat_model: str,
        embed_model: str,
        timeout: float = settings.LLM_TIMEOUT,
        max_retries: int = settings.LLM_MAX_RETRIES,
        fallback_base_url: str = settings.LLM_FALLBACK_BASE_URL,
        fallback_model: str = settings.LLM_FALLBACK_MODEL,
        fallback_api_key: str = settings.LLM_FALLBACK_API_KEY,
        # Embed-фоллбэк (EMBEDDING_FALLBACK_*): НЕЗАВИСИМ от chat-фоллбэка
        # LLM_FALLBACK_* (62.4) — только для /embeddings.
        embed_fallback_base_url: str = settings.EMBEDDING_FALLBACK_BASE_URL,
        embed_fallback_api_key: str = settings.EMBEDDING_FALLBACK_API_KEY,
        # Задача 1 (2026-09-05): второй слой ключа каскада (Google AI Studio,
        # запасной аккаунт) — тот же endpoint/модель; ключи пробуются по очереди.
        embed_fallback_api_key_2: str = settings.EMBEDDING_FALLBACK_API_KEY_2,
        embed_fallback_model: str = settings.EMBEDDING_FALLBACK_MODEL,
        embed_fallback_timeout: float = settings.EMBEDDING_FALLBACK_TIMEOUT_SECONDS,
        embed_fallback_max_retries: int = settings.EMBEDDING_FALLBACK_MAX_RETRIES,
        # Раунд 10.12 (ADR-1012-1 D1, OD-1): primary embed-путь развязан от
        # chat-base_url/ключа. None → эмбеддинги идут на chat-base/ключ
        # (полная обратная совместимость 4-аргументных вызовов и тестов).
        embed_base_url: str | None = None,
        embed_api_key: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embed_model = embed_model
        # Раунд 10.12: независимый адрес/ключ primary-эмбеддингов.
        # hot.get-приоритет; пустой адрес → chat-base (паритет).
        _embed_base = hot.get(
            "models.embedding_base_url",
            embed_base_url if embed_base_url is not None else self._base_url)
        self._embed_base_url = ((_embed_base or self._base_url) or "").rstrip("/")
        self._embed_api_key = (hot.get(
            "keys.embedding_api_key",
            (embed_api_key or "").strip()) or "").strip()
        # Миграция read-пути (2026-09-03): таймауты/ретраи читаются через
        # hot.get ВНУТРИ __init__ (в дефолтах бейкдились при импорте) —
        # значения из админки действуют при создании клиента.
        self._timeout = hot.get("models.llm_timeout", timeout)
        self._max_retries = hot.get("models.llm_max_retries", max_retries)
        # Epic 53 (62.4): фоллбэк активен ТОЛЬКО при всех трёх параметрах;
        # частичная конфигурация → WARNING (R17: только факты, без значений),
        # пустые env = ровно старое поведение.
        self._fallback_base_url = (hot.get("models.llm_fallback_base_url",
                                           fallback_base_url)
                                   or fallback_base_url or "").strip()
        self._fallback_model = (hot.get("models.llm_fallback_model",
                                        fallback_model)
                                or fallback_model or "").strip()
        self._fallback_api_key = (fallback_api_key or "").strip()
        configured = (bool(self._fallback_base_url), bool(self._fallback_model),
                      bool(self._fallback_api_key))
        self._fallback_active = all(configured)
        if any(configured) and not all(configured):
            logger.warning(
                "LLM fallback partially configured — disabled | base=%s model=%s key=%s",
                *configured,
            )
        # Epic 47 (D186): backoff base/cap/jitter + total budget (56.3/56.4).
        # Test-hook: tests may set `client.backoff_base = 0` → сон 0 (jitter тоже 0).
        self.backoff_base = hot.get("models.llm_retry_backoff_base", settings.LLM_RETRY_BACKOFF_BASE)
        self._backoff_cap = hot.get("models.llm_retry_backoff_cap", settings.LLM_RETRY_BACKOFF_CAP)
        self._jitter_max = hot.get("models.llm_retry_jitter_max", settings.LLM_RETRY_JITTER_MAX)
        self._budget = hot.get("models.llm_total_budget", settings.LLM_TOTAL_BUDGET)
        # Epic 64: бюджет фоллбэка — настройка (было жёстко 30с), плюс ретраи
        # транзиентных отказов самого фоллбэка.
        self._fallback_timeout = hot.get("models.llm_fallback_timeout_seconds", settings.LLM_FALLBACK_TIMEOUT_SECONDS)
        self._fallback_max_retries = hot.get("models.llm_fallback_max_retries", settings.LLM_FALLBACK_MAX_RETRIES)
        # Embed-фоллбэк (раунд 5): активен ТОЛЬКО при base_url + >=1 ключе;
        # пустая модель → primary embed-модель. 10.11 (ADR-1011-2): параметры
        # переведены в first-class каталог → hot.get (дефолт = прежний
        # settings/kwarg → паритет в тестах без кэша). Задача 1: упорядоченный
        # список ключей каскада [key1, key2, …] (пустые отбрасываются);
        # значение НИКОГДА не логируется (R17).
        self._embed_fallback_base_url = (hot.get(
            "models.embedding_fallback_base_url",
            (embed_fallback_base_url or "").strip()) or "").strip()
        self._embed_fallback_api_key = (hot.get(
            "keys.embedding_fallback_api_key",
            (embed_fallback_api_key or "").strip()) or "").strip()
        self._embed_fallback_api_key_2 = (hot.get(
            "keys.embedding_fallback_api_key_2",
            (embed_fallback_api_key_2 or "").strip()) or "").strip()
        self._embed_fallback_api_keys = [
            key for key in (self._embed_fallback_api_key,
                            self._embed_fallback_api_key_2) if key]
        self._embed_fallback_model = ((hot.get(
            "models.embedding_fallback_model",
            (embed_fallback_model or "").strip()) or "").strip()
                                      or self._embed_model)
        self._embed_fallback_timeout = embed_fallback_timeout
        self._embed_fallback_max_retries = embed_fallback_max_retries
        # D11 (asap5-final-fixes, T-5256, 13C.1): ДВА НЕЗАВИСИМЫХ фолбэк-
        # профиля вместо общего base/model. Fallback 1: новые ключи
        # models.embedding_fallback1_* → пусто = легаси-общие значения
        # (миграция без потери credentials). Fallback 2: свои ключи
        # models.embedding_fallback2_*; пусто = наследование Fallback 1
        # (режим миграции по умолчанию; честно помечен в статусе —
        # resolve_embedding_profiles). Ключи уже раздельные (key/key_2);
        # значения ключей не логируются (R17).
        _fb1_base = ((hot.get("models.embedding_fallback1_base_url", "")
                      or "").strip() or self._embed_fallback_base_url)
        _fb1_model = ((hot.get("models.embedding_fallback1_model", "")
                       or "").strip() or self._embed_fallback_model)
        _fb2_base = ((hot.get("models.embedding_fallback2_base_url", "")
                      or "").strip() or _fb1_base)
        _fb2_model = ((hot.get("models.embedding_fallback2_model", "")
                       or "").strip() or _fb1_model)
        self._embed_fallback_profiles = []
        if self._embed_fallback_api_key:
            self._embed_fallback_profiles.append(
                {"alias": "fallback_1", "base_url": _fb1_base,
                 "model": _fb1_model, "key": self._embed_fallback_api_key})
        if self._embed_fallback_api_key_2:
            self._embed_fallback_profiles.append(
                {"alias": "fallback_2", "base_url": _fb2_base,
                 "model": _fb2_model, "key": self._embed_fallback_api_key_2})
        self._embed_fallback_active = bool(self._embed_fallback_profiles) \
            and any(p["base_url"] for p in self._embed_fallback_profiles)
        # P0 SMART transport: снимок последних значений, пришедших ИЗ КОНФИГА
        # (PG/settings/kwarg). Hot-apply меняет рабочий атрибут только когда
        # конфиг реально изменился; ручные/тестовые переопределения атрибута
        # (`client._timeout = 0.05`, `client.backoff_base = 0`) сохраняются.
        # Модель/адрес — именно КОНФИГ-значение (``_MISSING`` — ключа нет), а
        # не рабочий kwarg: иначе явный constructor-level model/base (Speech
        # Try, per-call каналы) считался бы «изменившимся» и затирался
        # hot-значением на первом же вызове.
        self._policy_chat_model = hot.get("models.llm_model_name", _MISSING)
        self._policy_base_url = hot.get("models.llm_base_url", _MISSING)
        self._policy_timeout = _policy_float(self._timeout, settings.LLM_TIMEOUT,
                                             1.0)
        self._policy_budget = _policy_float(self._budget,
                                            settings.LLM_TOTAL_BUDGET, 1.0)
        self._policy_max_retries = _policy_int(self._max_retries,
                                               settings.LLM_MAX_RETRIES, 0)
        self._policy_backoff_base = _policy_float(self.backoff_base,
                                                  settings.LLM_RETRY_BACKOFF_BASE,
                                                  0.0)
        self._policy_backoff_cap = _policy_float(self._backoff_cap,
                                                 settings.LLM_RETRY_BACKOFF_CAP,
                                                 0.0)
        self._policy_jitter_max = _policy_float(self._jitter_max,
                                                settings.LLM_RETRY_JITTER_MAX,
                                                0.0)
        self._policy_fallback_timeout = _policy_float(
            self._fallback_timeout, settings.LLM_FALLBACK_TIMEOUT_SECONDS, 1.0)
        self._policy_fallback_max_retries = _policy_int(
            self._fallback_max_retries, settings.LLM_FALLBACK_MAX_RETRIES, 0)
        self._client: httpx.AsyncClient | None = None
        self._client_key: str | None = None
        # Раунд 10.12 (ADR-1012-1 D1, OD-1): embed-канал имеет СВОЙ
        # кэш httpx-клиента — иначе при разных chat/embed-ключах общий
        # `_client` пересоздаётся на каждом вызове (churn).
        self._embed_client: httpx.AsyncClient | None = None
        self._embed_client_key: str | None = None
        self._fallback_client: httpx.AsyncClient | None = None
        self._fallback_key: str | None = None
        self._embed_fallback_client: httpx.AsyncClient | None = None
        # Раунд 10 (F-7 §5.2): последний BYOK-источник (для счётчика).
        self._byok_source: str = "global"      # 'chat' | 'global'
        self._byok_chat_id: int | None = None
        # EMBED-META-WIRE (CANARY-03): ФАКТИЧЕСКИЕ метаданные последнего
        # embed-ответа провайдера. Аддитивный побочный канал: возвращаемый
        # тип `embed()`/`embed_once()` (list[list[float]]) НЕ меняется.
        self.last_embed_meta: dict = dict(_EMPTY_EMBED_META)

    def _current_api_key(self) -> str:
        """T-619 (84.4): ключ читается из ConfigCache на ВЫЗОВ; ключа нет в
        БД → значение из .env/settings (ровно старое поведение до миграции).
        ГЛОБАЛЬНЫЙ слой (embed/vision/видео — вне скоупа BYOK, F-7 §5.2)."""
        return hot.get("keys.llm_api_key", self._api_key) or ""

    def _current_api_key_source(self) -> str:
        """Глобальный слой нетронут: источник 'global' (для резолва)."""
        return "global"

    def _provider_label(self, model: str) -> str:
        """Хост провайдера для trace Inspector (без URL-путей и ключей)."""
        try:
            base = (self._fallback_base_url
                    if model == self._fallback_model else self._base_url)
            return _provider_host(str(base or ""))
        except Exception:       # pragma: no cover — защитная ветка
            return ""

    def _channel_label(self, model: str) -> str:
        """Канал trace: 'fallback' только когда реально ушёл fallback-модели."""
        return "fallback" if model == self._fallback_model else "primary"

    # ── P0 SMART transport: hot-apply модели/адреса и политики транспорта ──
    def _config_source(self, key: str) -> str:
        """Источник действующего значения ключа: ``pg`` | ``settings``.

        R17-safe диагностика (без значений): ключ есть в ConfigCache → pg,
        иначе process-default/settings."""
        cache = hot.get_config_cache()
        if cache is None:
            return "settings"
        try:
            return "pg" if cache.get(key, _MISSING) is not _MISSING else "settings"
        except Exception:      # pragma: no cover — диагностика не рвёт вызов
            return "settings"

    def _refresh_chat_model(self) -> None:
        """Модель/адрес чата — из горячего конфига на входе вызова.

        ``_policy_chat_model``/``_policy_base_url`` хранят последнее
        КОНФИГ-значение (``_MISSING`` — ключа в конфиге не было), а НЕ рабочий
        атрибут: hot-apply срабатывает только при реальном изменении настроек.
        Поэтому явный constructor-level model/base (per-call каналы, Speech
        Try) уважается на первом вызове, а ручные переопределения атрибутов не
        затираются. Пустое значение конфига — не подмена (паритет).
        Двойники без полного ``__init__`` (subclass/__new__) безопасны:
        отсутствующий ``_policy_*`` трактуется как «конфиг не наблюдался» →
        первое доступное значение применяется как раньше."""
        tracked_model = getattr(self, "_policy_chat_model", _MISSING)
        config_model = hot.get("models.llm_model_name", _MISSING)
        if config_model != tracked_model:
            model = (str(config_model or "").strip()
                     if config_model is not _MISSING else "")
            if model:
                self._chat_model = model
            self._policy_chat_model = config_model
        tracked_base = getattr(self, "_policy_base_url", _MISSING)
        config_base = hot.get("models.llm_base_url", _MISSING)
        if config_base != tracked_base:
            base = (str(config_base or "").strip().rstrip("/")
                    if config_base is not _MISSING else "")
            if base:
                self._base_url = base
            self._policy_base_url = config_base

    def _refresh_transport_policy(self) -> None:
        """Политика транспорта — из горячего конфига на входе вызова.

        timeout/budget/ретраи/backoff/фоллбэк: применяется к следующему
        вызову без рестарта. Значение атрибута меняется только при реальной
        смене конфига (см. ``_policy_*``), поэтому тест-хук
        ``client.backoff_base = 0`` и ручные переопределения сохраняются.
        Никакой адаптивности per-model/provider здесь нет (отложено до p95).
        Двойники без полного ``__init__`` безопасны (getattr-дефолты)."""
        timeout = _policy_float(
            hot.get("models.llm_timeout",
                    getattr(self, "_policy_timeout",
                            getattr(self, "_timeout", settings.LLM_TIMEOUT))),
            getattr(self, "_policy_timeout",
                    getattr(self, "_timeout", settings.LLM_TIMEOUT)), 1.0)
        if timeout != getattr(self, "_policy_timeout", timeout):
            self._timeout = timeout
        self._policy_timeout = timeout
        budget = _policy_float(
            hot.get("models.llm_total_budget",
                    getattr(self, "_policy_budget",
                            getattr(self, "_budget",
                                    settings.LLM_TOTAL_BUDGET))),
            getattr(self, "_policy_budget",
                    getattr(self, "_budget", settings.LLM_TOTAL_BUDGET)), 1.0)
        if budget != getattr(self, "_policy_budget", budget):
            self._budget = budget
        self._policy_budget = budget
        retries = _policy_int(
            hot.get("models.llm_max_retries",
                    getattr(self, "_policy_max_retries",
                            getattr(self, "_max_retries",
                                    settings.LLM_MAX_RETRIES))),
            getattr(self, "_policy_max_retries",
                    getattr(self, "_max_retries", settings.LLM_MAX_RETRIES)), 0)
        if retries != getattr(self, "_policy_max_retries", retries):
            self._max_retries = retries
        self._policy_max_retries = retries
        tracked_backoff = getattr(self, "_policy_backoff_base",
                                  getattr(self, "backoff_base",
                                          settings.LLM_RETRY_BACKOFF_BASE))
        backoff = _policy_float(
            hot.get("models.llm_retry_backoff_base", tracked_backoff),
            tracked_backoff, 0.0)
        if backoff != tracked_backoff:
            self.backoff_base = backoff
        self._policy_backoff_base = backoff
        tracked_cap = getattr(self, "_policy_backoff_cap",
                              getattr(self, "_backoff_cap",
                                      settings.LLM_RETRY_BACKOFF_CAP))
        cap = _policy_float(
            hot.get("models.llm_retry_backoff_cap", tracked_cap),
            tracked_cap, 0.0)
        if cap != tracked_cap:
            self._backoff_cap = cap
        self._policy_backoff_cap = cap
        tracked_jitter = getattr(self, "_policy_jitter_max",
                                 getattr(self, "_jitter_max",
                                         settings.LLM_RETRY_JITTER_MAX))
        jitter = _policy_float(
            hot.get("models.llm_retry_jitter_max", tracked_jitter),
            tracked_jitter, 0.0)
        if jitter != tracked_jitter:
            self._jitter_max = jitter
        self._policy_jitter_max = jitter
        tracked_fb_timeout = getattr(
            self, "_policy_fallback_timeout",
            getattr(self, "_fallback_timeout",
                    settings.LLM_FALLBACK_TIMEOUT_SECONDS))
        fallback_timeout = _policy_float(
            hot.get("models.llm_fallback_timeout_seconds", tracked_fb_timeout),
            tracked_fb_timeout, 1.0)
        if fallback_timeout != tracked_fb_timeout:
            self._fallback_timeout = fallback_timeout
        self._policy_fallback_timeout = fallback_timeout
        tracked_fb_retries = getattr(
            self, "_policy_fallback_max_retries",
            getattr(self, "_fallback_max_retries",
                    settings.LLM_FALLBACK_MAX_RETRIES))
        fallback_retries = _policy_int(
            hot.get("models.llm_fallback_max_retries", tracked_fb_retries),
            tracked_fb_retries, 0)
        if fallback_retries != tracked_fb_retries:
            self._fallback_max_retries = fallback_retries
        self._policy_fallback_max_retries = fallback_retries
        # Двойники/подклассы без полного __init__: гарантируем существование
        # рабочих атрибутов (значения — из текущей политики), не перетирая
        # уже заданные ручные переопределения.
        for attr, value in (
            ("_timeout", timeout),
            ("_budget", budget),
            ("_max_retries", retries),
            ("backoff_base", backoff),
            ("_backoff_cap", cap),
            ("_jitter_max", jitter),
            ("_fallback_timeout", fallback_timeout),
            ("_fallback_max_retries", fallback_retries),
        ):
            if not hasattr(self, attr):
                setattr(self, attr, value)

    def _effective_timeout(self, *, channel: str = "chat",
                           timeout: float | None = None) -> float:
        """Действующий per-request таймаут HTTP-ответа.

        ``timeout`` (per-call override Summary supervisor и пр.) — как есть
        (без нижнего clamp: sub-second дедлайны легитимны). Иначе —
        действующее policy-значение; для ``channel='embed'`` — технический
        потолок ``_EMBED_TIMEOUT_CAP`` (60с), чтобы 180-секундный чат-таймаут
        не растягивал память."""
        if timeout is not None:
            # Per-call окно (supervised Summary) — как передано; мусор/≤0 →
            # policy (никакого clamp до 1с: sub-second дедлайны легитимны).
            try:
                explicit = float(timeout)
            except (TypeError, ValueError):
                explicit = 0.0
            if explicit > 0:
                return explicit
        # self._timeout — уже действующее значение (конфиг clamp-ится ≥1 в
        # `_refresh_transport_policy`); ручные/тестовые переопределения
        # (например 0.05с) НЕ затираются повторным clamp'ом.
        effective = _policy_float(self._timeout, settings.LLM_TIMEOUT, 0.0)
        if effective <= 0:
            effective = _policy_float(settings.LLM_TIMEOUT, 180.0, 1.0)
        if channel == "embed":
            effective = min(effective, _EMBED_TIMEOUT_CAP)
        return effective

    def _record_sent_attempts(self, sent, *, payload: dict, messages, module,
                              step, correlation_id, chat_id,
                              status: str = "error", error: str = "",
                              limit: int = 8, channel: str = ""):
        """Записать ВСЕ фактические попытки вызова (ретраи не схлопываются).

        «last actual request» в Inspector = последняя запись журнала, поэтому
        неудачные попытки пишутся по порядку ДО финального результата.
        ``channel`` ограничивает выборку (fallback-провал не дублирует уже
        записанные primary-попытки).
        """
        rows = list(sent or ())
        if channel:
            rows = [r for r in rows if r[0] == channel]
        rows = rows[-max(1, int(limit)):]
        if not rows:
            self._record_sent_call(
                [], payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status=status, error=error)
            return
        for channel, body in rows:
            self._record_sent_call(
                [(channel, body)], payload=payload, messages=messages,
                module=module, step=step, correlation_id=correlation_id,
                chat_id=chat_id, status=status, error=error)

    def _record_sent_call(self, sent, *, payload: dict, messages, module,
                          step, correlation_id, chat_id, status: str = "ok",
                          error: str = ""):
        """INS-EXACT/INS-TRACE: журнал = ПОСЛЕДНЕЕ фактически отправленное тело.

        ``sent`` заполняют точки отправки (`_post_with_key` — primary,
        `_post_fallback` — тело с подменённой model). Поэтому checksum и
        сообщения в журнале совпадают с HTTP-телом даже при fallback, а не
        описывают payload до адаптера/подмены модели.
        """
        channel, body = ("primary", payload)
        if sent:
            channel, body = sent[-1]
        try:
            body_messages = body.get("messages") or messages
            model = str(body.get("model") or self._chat_model)
        except Exception:       # pragma: no cover — защитная ветка
            body_messages, model = messages, self._chat_model
        _record_provider_call(
            payload=body, messages=body_messages, model=model,
            provider=self._provider_label(model), module=module, step=step,
            correlation_id=correlation_id, chat_id=chat_id,
            channel=channel, status=status, error=error)

    def _current_embed_api_key(self) -> str:
        """OD-1 (раунд 10.12): ключ primary-эмбеддингов из горячего конфига
        (keys.embedding_api_key). Пусто → keys.llm_api_key (обратная
        совместимость). R17: значение ключа не логируется."""
        return (hot.get("keys.embedding_api_key", self._embed_api_key)
                or self._current_api_key() or "")

    async def _resolve_api_key_and_source(self, chat_id: int | None = None
                                          ) -> tuple[str, str]:
        """ФИКС R6 (F-7 §5.2): (key, source) РЕЗОЛВ НА ВЫЗОВ — без записи
        в self-атрибуты (гонка параллельных чатов перекручивала
        _byok_chat_id и ложно учитывала usage другому чату).

        1) chat_keys[chat_id]['keys.llm_api_key'] → свой ключ (бюджет не
           тратится; source 'chat');
        2) elif not chat_params['keys']['allow_global'] (default True) →
           NoApiKeyForChat (source 'forbidden');
        3) elif budget_exceeded(chat_id) → повторная проверка СВОЕГО ключа
           (F-15 §3.2: фоллбэк, покрывает гонку/персист — ключ добавлен
           между шагом 1 и 3; бюджет НЕ тратится); найден → source 'chat';
           нет → NoApiKeyForChat (source 'budget', details-снапшот);
        4) иначе глобальный hot.get (source 'global' + счётчик на конце
           вызова).
        Без собственного ключа/с запретом/с исчерпанием → NoApiKeyForChat
        (sandbox-путь F-7: бот отвечает content.no_key_reply, LLM не
        вызывается). Fail-open: PG/кэш недоступен → глобальный ключ (source
        'global'), бот жив (§1.2-4)."""
        if chat_id is None:
            return self._current_api_key(), "global"
        try:
            from services import chat_params, chat_usage, chat_keys
            own = await chat_keys.get_chat_key(
                self._pg(), chat_id, "keys.llm_api_key")
            if own:
                return own, "chat"
            root = await chat_params.get_all_chat_params(chat_id)
            allow_global = bool((root.get("keys") or {}).get("allow_global",
                                                             True))
            if not allow_global:
                raise NoApiKeyForChat(chat_id, "forbidden",
                                      details={"resolve_path": "forbidden",
                                               "allow_global": False})
            # F2 (ADR-1019-2 D4): единый снимок — и решение, и details (один
            # резолв лимитов + одно чтение usage; без двойного PG-раундтрипа и
            # TOCTOU — D-5 ревью Батча B).
            snapshot = await chat_usage.budget_snapshot(self._pg(), chat_id)
            if snapshot["exceeded"]:
                # F-15 (§3.2): BYOK-фоллбэк — дешёвый re-read своего ключа
                # (гонка/персист); строгий порядок: свой → глобал-бюджет →
                # свой-фоллбэк → sandbox.
                fallback_own = await chat_keys.get_chat_key(
                    self._pg(), chat_id, "keys.llm_api_key")
                if fallback_own:
                    return fallback_own, "chat"
                # F2 (ADR-1019-2 D4): details — из того же снимка (добавлены
                # exceeded_metric/unlimited/forbidden/source; R17-safe).
                details = {
                    "resolve_path": "budget",
                    "allow_global": bool(allow_global),
                    **snapshot,
                }
                raise NoApiKeyForChat(chat_id, "budget", details=details)
            return self._current_api_key(), "global"
        except NoApiKeyForChat:
            raise
        except Exception:
            logger.warning(
                "[llm_client] BYOK-резолв недоступен — fail-open global | "
                "chat=%s", chat_id, exc_info=True)
            return self._current_api_key(), "global"

    async def _resolve_api_key(self, chat_id: int | None = None) -> str:
        """Легаси-обёртка (совместимость API): ключ + запись источника в
        _byok_source/_byok_chat_id (для диагностики/тестов). Горячий путь —
        использовать _resolve_api_key_and_source (фикс R6)."""
        key, source = await self._resolve_api_key_and_source(chat_id)
        self._byok_source = source
        self._byok_chat_id = chat_id
        return key

    def _pg(self):
        """PgDatabase из runtime-кэша (для BYOK/бюджета); None при его нет."""
        cache = hot.get_config_cache()
        if cache is None:
            return None
        return getattr(cache, "pg", None)

    async def _record_global_usage(self, chat_id: int | None,
                                   text: str | None,
                                   source: str = "global") -> None:
        """Счётчик бюджета глобального ключа на КОНЦЕ вызова (источник
        'global'): 1 вызов + токены (оценка len/4, приблизительность —
        README F-7 §5.2). Свой ключ чата бюджет НЕ тратит. ФИКС R6:
        source передаётся per-call (не читается из self — гонка)."""
        if chat_id is None or source != "global":
            return
        try:
            from services import chat_usage
            await chat_usage.report_call(
                self._pg(), chat_id,
                chat_usage.estimate_tokens(text))
        except Exception:
            logger.warning(
                "[llm_client] usage counters failed — fail-open | chat=%s",
                chat_id, exc_info=True)

    def _current_fallback_key(self) -> str:
        return hot.get("keys.llm_fallback_api_key",
                       self._fallback_api_key) or ""

    async def _record_analytics(
        self, usage, messages, content, *, source: str,
        module: str | None, step: str | None,
        correlation_id: str | None, chat_id: int | None,
        model: str | None = None, tool_name: str = "",
    ) -> None:
        """F7 (ADR-1023-7): запись обогащённого usage-события в PG.

        Аналитика **аддитивна** и fail-open: ошибка/нет PG/флаг OFF → только
        WARNING (или no-op), бюджетный учёт (`_record_global_usage`) не
        затрагивается. Реальные токены — из `usage` ответа; при отсутствии —
        честная оценка + `tokens_estimated=true`. R17: только числа/коды."""
        try:
            from services import usage_events
            in_tokens, out_tokens, estimated = \
                usage_events.resolve_token_counts(usage, messages, content)
            await usage_events.record(
                self._pg(),
                module=module or "llm",
                step=step or "single",
                correlation_id=correlation_id,
                # BYOK-ключ чата (source='chat') в аналитике = 'byok'.
                source=("byok" if source == "chat" else source),
                chat_id=chat_id,
                model=model or self._chat_model,
                tool_name=tool_name,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                tokens_estimated=estimated,
            )
        except Exception:
            logger.warning(
                "[llm_client] analytics record failed — fail-open | module=%s",
                module, exc_info=True)

    async def _record_embedding_analytics(self, data, texts, *,
                                          model: str | None = None) -> None:
        """MCA-11 (ADR-1028-13 D4): usage-событие embeddings (fail-open).

        K3 `MCA_COST_ACCOUNTING_ENABLED` гейтит только эту НОВУЮ точку записи;
        source='embedding'. Токены — из usage ответа, иначе честная оценка
        (`tokens_estimated=true`); цена через `llm_pricing` (нет цены →
        `price_known=false`, unknown ≠ 0). R17: только числа/коды."""
        try:
            from services import usage_events
            if not usage_events.cost_accounting_enabled():
                return
            usage = data.get("usage") if isinstance(data, dict) else None
            messages = [{"content": str(t or "")} for t in (texts or [])]
            in_tokens, _out_tokens, estimated = \
                usage_events.resolve_token_counts(usage, messages, "")
            await usage_events.record(
                self._pg(),
                module="embedding",
                step="embed",
                correlation_id=None,
                source="embedding",
                chat_id=None,
                model=model or self._embed_model,
                input_tokens=in_tokens,
                output_tokens=0,
                tokens_estimated=estimated,
            )
        except Exception:
            logger.warning(
                "[llm_client] embedding analytics record failed — fail-open",
                exc_info=True)

    @staticmethod
    def _close_async(client: httpx.AsyncClient) -> None:
        """Закрытие старого клиента при смене ключа (fire-and-forget)."""
        try:
            asyncio.create_task(_aclose(client))
        except RuntimeError:
            pass                     # нет running loop — GC подберёт

    def _get_client(self, key: str | None = None) -> httpx.AsyncClient:
        """Ленивый клиент; `key` — resolve-результат (раунд 10, F-7: BYOK
        собственный ключ чата передаётся из public async-точек; None →
        глобальный _current_api_key())."""
        if key is None:
            key = self._current_api_key()
        if self._client is not None and key != self._client_key:
            self._close_async(self._client)
            self._client = None
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._client_key = key
        return self._client

    def _get_embed_client(self, key: str | None = None) -> httpx.AsyncClient:
        """Раунд 10.12 (OD-1): отдельный кэш httpx-клиента для embed-канала.

        Зеркалит `_get_client`, но не делит `_client` с chat: при разных
        chat/embed-ключах оба канала сохраняют свой клиент (без churn)."""
        if key is None:
            key = self._current_embed_api_key()
        if self._embed_client is not None and key != self._embed_client_key:
            self._close_async(self._embed_client)
            self._embed_client = None
        if self._embed_client is None:
            self._embed_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._effective_timeout(channel="embed"),
                                      connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._embed_client_key = key
        return self._embed_client

    def _get_fallback_client(self) -> httpx.AsyncClient:
        """Epic 53 (62.4): ленивый клиент фоллбэка, тот же таймаут-срез.
        T-619: ключ фоллбэка — горячая точка (пересоздание при смене).
        P0 SMART: клиент создаётся с СОБСТВЕННЫМ таймаутом фоллбэка (не
        primary 180с); per-request окно всё равно передаётся в `_post_fallback`.
        """
        key = self._current_fallback_key()
        if self._fallback_client is not None and key != self._fallback_key:
            self._close_async(self._fallback_client)
            self._fallback_client = None
        if self._fallback_client is None:
            self._fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._fallback_timeout, connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._fallback_key = key
        return self._fallback_client

    def _get_embed_fallback_client(self) -> httpx.AsyncClient:
        """Ленивый ОБЩИЙ клиент embed-фоллбэка БЕЗ auth на уровне клиента:
        Bearer-ключ каскада ставится заголовком КОНКРЕТНОГО запроса
        (_post_embed_fallback) — один клиент переиспользуется всеми ключами
        (headers per-request безопасны). Per-request таймаут
        EMBEDDING_FALLBACK_TIMEOUT_SECONDS — infra-тайминг (.env, не
        каталог); url/модель/ключи фоллбэка — first-class каталог
        (мини-апп «LLM Провайдеры» → «Эмбеддинги»)."""
        if self._embed_fallback_client is None:
            self._embed_fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._embed_fallback_timeout,
                                       connect=10.0),
            )
        return self._embed_fallback_client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._embed_client is not None:
            await self._embed_client.aclose()
            self._embed_client = None
        if self._fallback_client is not None:
            await self._fallback_client.aclose()
            self._fallback_client = None
        if self._embed_fallback_client is not None:
            await self._embed_fallback_client.aclose()
            self._embed_fallback_client = None

    def _sleep_seconds(
        self,
        attempt: int,
        status: int | None = None,
        headers: httpx.Headers | None = None,
        *,
        base: float | None = None,
        cap: float | None = None,
        jitter: float | None = None,
    ) -> float:
        """Epic 47 (56.3): сон перед retry.

        Retry-After (429/5xx, парсится как float, ≥0) приоритетнее обычного
        backoff; значение капится LLM_RETRY_BACKOFF_CAP. Кривой/отрицательный
        header либо статус ≠ 429/5xx → обычный backoff
        `min(BASE*2**attempt, CAP) + U(0, JITTER)`. backoff_base == 0 → сон 0.

        P0 SMART transport: ``base``/``cap``/``jitter`` — снимок политики
        ОДНОГО вызова (``_post`` берёт его на входе), чтобы hot-apply
        посреди in-flight запроса не менял ритм текущей попытки."""
        base_value = self.backoff_base if base is None else base
        cap_value = self._backoff_cap if cap is None else cap
        jitter_value = self._jitter_max if jitter is None else jitter
        if base_value == 0:
            return 0.0
        if status is not None and (status == 429 or 500 <= status < 600):
            raw = headers.get("Retry-After") if headers is not None else None
            if raw is not None:
                try:
                    header_seconds = float(raw)
                except (TypeError, ValueError):
                    header_seconds = -1.0
                if header_seconds >= 0:
                    return min(header_seconds, cap_value)
        base_sleep = min(base_value * (2 ** attempt), cap_value)
        return base_sleep + random.uniform(0, jitter_value)

    async def _post(self, path: str, payload: dict,
                    api_key: str | None = None,
                    base_url: str | None = None,
                    channel: str = "chat",
                    budget: float | None = None,
                    max_retries: int | None = None,
                    retry_statuses: tuple[int, ...] | None = None,
                    timeout: float | None = None,
                    budget_reason_label: str | None = None,
                    sent: list | None = None,
                    module: str | None = None,
                    step: str | None = None) -> httpx.Response:
        """POST with retry on all transient errors; auth errors raised immediately.

        Единственный владелец LLM-ретраев (56.4, D187). Жёсткий дедлайн всей
        _post — asyncio.timeout(LLM_TOTAL_BUDGET) (56.4).
        Раунд 10 (F-7 §5.2): api_key — BYOK-результат резолва (None →
        глобальный слой).
        Раунд 10.12 (ADR-1012-1 D1): base_url — per-call override (embed-путь
        ходит на `_embed_base_url`, chat — на `_base_url`).
        Раунд 10.24 (F1, ADR-1024-6 D1): `budget`/`max_retries` — опциональные
        per-call override для фонового канала. ``None`` → ровно прежнее
        поведение (self._budget/self._max_retries), не смещая других
        потребителей (байт-в-байт).
        ASAP-4 (spec §1 A.2, ADR-1028-7 D1.2): ``retry_statuses`` — allowlist
        нижнеуровневых статус-ретраев. ``None`` (default) → бит-в-бит прежнее
        поведение (ретраятся 408/425/429/5xx); кортеж → ретраится ТОЛЬКО
        явно перечисленное, остальное уходит наверх немедленно (``()`` → ни
        одного статус-ретрая: 429/5xx отдаются наверх сразу — quota-retry
        исключительно EmbeddingExecutor, нижнему слою остаётся только
        transport retry, который от параметра не зависит).
        Fix H-ASAP4-1 (review round 1): прежняя blocklist-семантика
        (``status in retry_statuses`` = «не ретраить») при ``()`` была
        всегда-ложной → 429 уходил в legacy-ветку и ретраился (2 HTTP-вызова
        на вызов адаптера, первый ретрай спал min(Retry-After, cap) —
        анти-паттерн §9/Q4).

        ASAP 4.1 волна 4 (spec §4 D.1/D.5, ADR-1028-8 D5; scope = Summary
        только): ``timeout`` — per-request transport-окно (None → прежний
        клиентский timeout, байт-в-бит); ``budget_reason_label`` — метка
        supervised-канала: при ``"summary_supervised"`` две time-budget
        точки эмиссии ниже переименованы (§30 ТЗ: ``total_budget_exceeded``
        → ``execution_deadline_exceeded`` (fuse-ветка) / ``budget_exhausted``
        → ``retry_time_budget_exhausted`` (исчерпание попыток по времени)).
        Для всех остальных потребителей (None) — прежние строки байт-в-бит.

        P0 SMART transport (2.58.206): на входе вызова политика обновляется
        из горячего конфига и СНИМАЕТСЯ в локалы (in-flight изменения не
        влияют на текущую попытку). Per-request `httpx.Timeout` передаётся
        ВСЕГДА: `timeout` (если задан) либо действующий `LLM_TIMEOUT`
        (для channel='embed' — min(…, 60с)); кэшированный клиент не
        пересоздаётся. `module`/`step` — только R17-safe поля логов.
        """
        # P0 SMART transport: hot-apply политики на входе вызова + СНИМОК
        # значений. Всё, что ниже, читает локалы — изменение настроек
        # посреди in-flight запроса не меняет текущую попытку.
        self._refresh_transport_policy()
        client = (self._get_embed_client(api_key) if channel == "embed"
                  else self._get_client(api_key))
        base = (base_url or self._base_url).rstrip("/")
        url = f"{base}{path}"
        request_len = len(str(payload))
        model = str(payload.get("model") or self._chat_model) \
            if isinstance(payload, dict) else str(self._chat_model)
        tools_count = len(payload.get("tools") or []) \
            if isinstance(payload, dict) else 0
        effective_timeout = self._effective_timeout(channel=channel,
                                                    timeout=timeout)
        timeout_source = self._config_source("models.llm_timeout")
        budget_source = self._config_source("models.llm_total_budget")
        # Кэшированный httpx-клиент НЕ пересоздаётся: окно — per-request.
        post_kwargs: dict = {
            "timeout": httpx.Timeout(effective_timeout, connect=10.0),
        }
        # F1: per-call override (None = снимок политики этого вызова).
        # Явный per-call бюджет НЕ clamp-ится до 1с: sub-second дедлайны
        # supervised-канала легитимны (паритет байт-в-бит).
        if budget is None:
            # self._budget уже действующее (конфиг clamp-ится ≥1 при refresh);
            # ручные/тестовые переопределения (0.05с) сохраняются.
            call_budget = _policy_float(self._budget,
                                        settings.LLM_TOTAL_BUDGET, 0.0)
            if call_budget <= 0:
                call_budget = _policy_float(settings.LLM_TOTAL_BUDGET, 360.0,
                                            1.0)
        else:
            call_budget = _policy_float(budget, self._budget, 0.0)
        call_retries = _policy_int(
            self._max_retries if max_retries is None else max_retries,
            self._max_retries, 0)
        snapshot_backoff = self.backoff_base
        snapshot_cap = self._backoff_cap
        snapshot_jitter = self._jitter_max
        total_attempts = call_retries + 1
        # R17-safe контекст диаг-логов: провайдер-хост, модель, канал, шаг и
        # действующие лимиты. Промптов/ключей/тел здесь нет.
        log_ctx = (
            f"provider={_provider_host(base)} | model={model} | "
            f"channel={channel} | module={module or '-'} | "
            f"step={step or '-'} | effective_timeout={effective_timeout:.1f} | "
            f"effective_budget={call_budget:.1f} | "
            f"timeout_source={timeout_source} | budget_source={budget_source} | "
            f"request_chars={request_len} | tools_count={tools_count} | "
            f"streaming=False"
        )
        # ASAP-4 / H-ASAP4-1: allowlist статус-ретраев (см. docstring).
        if retry_statuses is None:

            def _retryable(status: int) -> bool:
                # Бит-в-бит прежний сет нижнеуровневых ретраев.
                return status in (408, 425, 429) or 500 <= status < 600
        else:
            _allowed = frozenset(retry_statuses)

            def _retryable(status: int) -> bool:
                # Ретраится ТОЛЬКО явно перечисленное; остальные статусы —
                # наверх немедленно (() → ни одного статус-ретрая).
                return status in _allowed
        started_total = time.monotonic()
        budget_exceeded = False
        _LLM_STATS["requests"] += 1
        try:
            async with asyncio.timeout(call_budget):
                for attempt in range(total_attempts):
                    if attempt > 0 and (time.monotonic() - started_total) >= call_budget:
                        budget_exceeded = True
                        break                   # попытка не стартует (56.4)
                    started = time.monotonic()
                    try:
                        # INS-TRACE: каждая фактическая HTTP-попытка — в
                        # per-call список (ретраи не схлопываются в одну).
                        if sent is not None:
                            sent.append(("primary", payload))
                        response = await client.post(url, json=payload,
                                                     **post_kwargs)
                    except httpx.TransportError as exc:
                        # Транзиентное (timeout/connect/read/.../protocol) → ретрай
                        if attempt < call_retries:
                            sleep = self._sleep_seconds(
                                attempt, base=snapshot_backoff,
                                cap=snapshot_cap, jitter=snapshot_jitter)
                            logger.warning(
                                "LLM request retry | url=%s | attempt=%d/%d | sleep=%.1fs | reason=%s",
                                url, attempt + 1, total_attempts, sleep,
                                f"{type(exc).__name__}: {exc}",
                            )
                            await asyncio.sleep(sleep)
                            continue
                        if isinstance(exc, httpx.TimeoutException):
                            # T-2500 (ADR-1025-7 D4): R17-safe причина
                            # (класс: ReadTimeout/ConnectTimeout/…) + провайдер.
                            _LLM_STATS["timeouts"] += 1
                            if isinstance(exc, httpx.ReadTimeout):
                                _LLM_STATS["read_timeouts"] += 1
                            logger.error(
                                "LLM timeout | url=%s | attempt=%d/%d | "
                                "elapsed_ms=%.0f | reason=%s | cause_class=%s | %s",
                                url, attempt + 1, total_attempts,
                                (time.monotonic() - started) * 1000.0,
                                type(exc).__name__, type(exc).__name__, log_ctx)
                            raise LLMTimeoutError(
                                f"LLM request timed out after {total_attempts} attempts: {url}",
                                cause_class=type(exc).__name__,
                            ) from exc
                        raise LLMTransportError(
                            f"LLM transport error after {total_attempts} attempts: {exc}: {url}",
                            cause_class=type(exc).__name__,
                        ) from exc
                    except httpx.HTTPError as exc:
                        # Не-транспортное (InvalidURL и пр.) → мгновенно
                        raise LLMError(f"LLM HTTP client error: {exc}") from exc

                    status = response.status_code
                    latency_ms = (time.monotonic() - started) * 1000.0
                    # Epic 85 (84.11.2): замер латентности для /api/status
                    status_service.record_llm(
                        "deepseek", latency_ms,
                        None if status < 500 else f"status={status}")
                    if _retryable(status) and attempt < call_retries:
                        # Статус разрешён allowlist'ом (или legacy-сетом при
                        # None) и бюджет ретраев не исчерпан → нижнеуровневый
                        # ретрай (Retry-After приоритетнее backoff — 56.3).
                        sleep = self._sleep_seconds(
                            attempt, status, response.headers,
                            base=snapshot_backoff, cap=snapshot_cap,
                            jitter=snapshot_jitter)
                        logger.warning(
                            "LLM request retry | url=%s | attempt=%d/%d | sleep=%.1fs | reason=%s",
                            url, attempt + 1, total_attempts, sleep, f"status={status}",
                        )
                        await asyncio.sleep(sleep)
                        continue
                    # Terminal-классификация статуса: ретраи исчерпаны ЛИБО
                    # статус не входит в allowlist → наверх немедленно
                    # (H-ASAP4-1: retry_statuses=() → 429/5xx без ретрая и
                    # без сна нижним слоем).
                    _attempts_suffix = (f" after {total_attempts} attempts"
                                        if _retryable(status) else "")
                    if status == 429:
                        # R17: тело/заголовки прикладываются к исключению
                        # in-memory для классификации EmbeddingExecutor
                        # (Retry-After/kind) — НИЧЕГО из них не логируется.
                        exc_429 = LLMRateLimitError(
                            f"LLM rate limited (429){_attempts_suffix}: {url}")
                        exc_429.headers = response.headers
                        exc_429.body = response.text[:2000]
                        raise exc_429
                    if status in (408, 425):
                        raise LLMError(f"LLM HTTP {status}: {url}")
                    if 500 <= status < 600:
                        if retry_statuses is None:
                            # Epic 53 (62.5): диаг-лог финального 5xx ДО raise
                            # LLMServerError — инцидентный сигнал Betterstack.
                            # R17: url без query/секретов, заголовки не
                            # логируются, тело ≤ _BODY_MAX_CHARS. (Allowlist-
                            # путь исключения не логирует — классификация/
                            # ретрай решаются наверху контрол-плейном.)
                            logger.error(
                                "LLM HTTP %d | url=%s | request_len=%d | content_chars=%d | num_messages=%d | body_5xx=%r",
                                status, url, request_len,
                                sum(len(str(m.get("content", ""))) for m in payload.get("messages", [])),
                                len(payload.get("messages", [])),
                                response.text[:_BODY_MAX_CHARS],
                            )
                        raise LLMServerError(
                            f"LLM server error {status}{_attempts_suffix}: {url}"
                        )
                    if status in (401, 403):
                        # Задача 2 (01.09.2026): диаг-лог + тело в исключении
                        # (обрезанное, секреты замаскированы — R17), чтобы
                        # 403 «insufficient balance» был диагностируемым.
                        snippet = _sanitize_snippet(response.text)
                        logger.error(
                            "LLM HTTP %d | url=%s | body_auth=%r",
                            status, url, snippet,
                        )
                        raise LLMAuthError(
                            f"LLM auth failed ({status}): {url}"
                            f"{f' | body={snippet}' if snippet else ''}"
                        )
                    if status >= 400:
                        # Epic 49 (57.4, D197): детерминированное отклонение провайдера —
                        # инцидентный сигнал в Betterstack. R17: url без query/секретов,
                        # тело ≤ 500 симв., заголовки не логируются.
                        logger.error(
                            "LLM HTTP %d | url=%s | request_len=%d | content_chars=%d | num_messages=%d | body_4xx=%r",
                            status, url, request_len,
                            sum(len(str(m.get("content", ""))) for m in payload.get("messages", [])),
                            len(payload.get("messages", [])),
                            response.text[:_BODY_MAX_CHARS],
                        )
                        # SMART D6: тело/модель/endpoint доступны in-memory
                        # (не логируются) — по ним распознаётся context
                        # overflow и обновляется ФИЗИЧЕСКИЙ предел endpoint.
                        err = LLMError(f"LLM HTTP {status}: {url}")
                        err.status = status
                        err.body = response.text[:4000]
                        err.model = str(payload.get("model") or "")
                        err.base_url = base
                        overflow = _context_overflow_exc(
                            err, status=status, payload=payload,
                            base_url=base)
                        if overflow is not None:
                            raise overflow
                        raise err

                    # Epic 60 (64.7, T-468): фактический лимит — usage из
                    # API-ответа (источник истины для бюджетов/метрик);
                    # парсинг fail-open (нет usage в ответе → нет лога).
                    try:
                        data = response.json()
                    except Exception:
                        data = None
                    finish_reason = (_choice_finish_reason(data)[0]
                                     if isinstance(data, dict)
                                     else _FINISH_REASON_UNKNOWN)
                    logger.info(
                        "LLM request OK | url=%s | status=%d | latency_ms=%.0f "
                        "| in=%d chars | out=%d chars | elapsed_ms=%.0f | "
                        "attempt=%d/%d | %s | finish_reason=%s",
                        url, status, latency_ms, request_len,
                        len(response.content), latency_ms, attempt + 1,
                        total_attempts, log_ctx, finish_reason,
                    )
                    if isinstance(data, dict):
                        usage = data.get("usage")
                        if isinstance(usage, dict):
                            logger.info(
                                "LLM usage in=%d out=%d",
                                int(usage.get("prompt_tokens") or 0),
                                int(usage.get("completion_tokens") or 0),
                            )
                    return response
        except asyncio.TimeoutError:
            _LLM_STATS["timeouts"] += 1
            _LLM_STATS["budget_exhausted"] += 1
            # ASAP 4.1 волна 4 (T-4615, §30 ТЗ): для supervised Summary-канала
            # fuse-ветка = execution_deadline_exceeded; не-Summary потребители —
            # прежняя строка total_budget_exceeded (байт-в-бит).
            budget_reason = ("execution_deadline_exceeded"
                             if budget_reason_label == "summary_supervised"
                             else "total_budget_exceeded")
            logger.error(
                "LLM timeout | url=%s | attempt=%d/%d | elapsed_ms=%.0f | "
                "reason=%s | cause_class=budget | %s",
                url, total_attempts, total_attempts,
                (time.monotonic() - started_total) * 1000.0,
                budget_reason, log_ctx)
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}",
                cause_class="budget",
            ) from None
        if budget_exceeded:
            _LLM_STATS["timeouts"] += 1
            _LLM_STATS["budget_exhausted"] += 1
            # T-4615: попытка не стартовала — время call_budget исчерпано →
            # supervised Summary-канал: retry_time_budget_exhausted;
            # не-Summary: прежний budget_exhausted.
            budget_reason = ("retry_time_budget_exhausted"
                             if budget_reason_label == "summary_supervised"
                             else "budget_exhausted")
            logger.error(
                "LLM timeout | url=%s | attempt=%d/%d | elapsed_ms=%.0f | "
                "reason=%s | cause_class=budget | %s",
                url, total_attempts, total_attempts,
                (time.monotonic() - started_total) * 1000.0,
                budget_reason, log_ctx)
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}",
                cause_class="budget",
            )
        raise LLMError(f"LLM request failed after retries: {url}")

    async def stream_chat_completion(
            self, messages: list[dict[str, str]], *,
            model: str | None = None,
            api_key: str | None = None,
            base_url: str | None = None,
            timeout: float | None = None,
            on_activity=None,
            extra_payload: dict | None = None) -> tuple[str, dict | None]:
        """ASAP 4.2 Step 2c-1 (T-4810/AM-2): реальный SSE-стрим
        OpenAI-совместимого `POST /chat/completions` (`stream=true`).

        Для верифицированного chat-route: submit stream → приём SSE-чанков →
        `on_activity()` на каждый чанк (обновляет `last_activity_at`
        watchdog'а) → assemble финального контента из `delta.content`.
        Wall-clock НЕ является health-метрикой здесь — только внешний fuse.
        Транспортная ошибка/не-2xx классифицируются в те же LLM*-исключения,
        что и `_post` (fail-soft контур стадий не смещается). Никогда не
        логирует prompt/ключи/тело чанков (R17)."""
        # P0 SMART transport: модель/адрес/политика — из горячего конфига на
        # входе вызова (явные per-call model/base_url ниже имеют приоритет).
        self._refresh_chat_model()
        self._refresh_transport_policy()
        key = api_key if api_key is not None else self._current_api_key()
        base = (base_url or self._base_url).rstrip("/")
        url = f"{base}/chat/completions"
        payload: dict = {
            "model": model or self._chat_model,
            "messages": messages,
            "stream": True,
        }
        if extra_payload:
            payload.update(extra_payload)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        to = httpx.Timeout(self._effective_timeout(channel="chat",
                                                   timeout=timeout),
                           connect=10.0)
        parts: list[str] = []
        usage: dict | None = None
        try:
            async with httpx.AsyncClient(timeout=to) as client:
                async with client.stream("POST", url, json=payload,
                                         headers=headers) as resp:
                    status = resp.status_code
                    if status is not None and int(status) >= 400:
                        await resp.aread()
                        if int(status) == 429:
                            raise LLMRateLimitError(
                                f"LLM stream rate limited (429): {url}")
                        if 500 <= int(status) < 600:
                            raise LLMServerError(
                                f"LLM stream server error {status}: {url}")
                        if int(status) in (401, 403):
                            raise LLMAuthError(
                                f"LLM stream auth failed ({status}): {url}")
                        raise LLMError(f"LLM stream HTTP {status}: {url}")
                    async for line in resp.aiter_lines():
                        if on_activity is not None:
                            try:
                                on_activity()
                            except Exception:      # наблюдаемость не рвёт стрим
                                pass
                        line = (line or "").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        chunk_usage = chunk.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage
                        for choice in chunk.get("choices") or []:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")
                            if isinstance(piece, str) and piece:
                                parts.append(piece)
        except httpx.TransportError as exc:
            if isinstance(exc, httpx.TimeoutException):
                raise LLMTimeoutError(
                    f"LLM stream timed out: {url}",
                    cause_class=type(exc).__name__) from exc
            raise LLMTransportError(
                f"LLM stream transport error: {exc}: {url}",
                cause_class=type(exc).__name__) from exc
        content = "".join(parts)
        if not content.strip():
            raise LLMBadResponseError("LLM stream: empty content")
        # INS-TRACE: успешный SSE-стрим — тоже реальный вызов провайдера.
        # Ошибки стрима классифицируются существующими LLM*-исключениями и в
        # журнал не пишутся (это отражено в `trace_coverage` Inspector).
        _record_provider_call(
            payload=payload, messages=messages,
            model=str(payload.get("model") or ""),
            provider=_provider_host(base), module="summary_stream",
            step="chat_stream", correlation_id="", chat_id=None,
            status="ok")
        return content, usage

    async def _post_with_key(self, path: str, payload: dict,
                             chat_id: int | None = None,
                             key: str | None = None,
                             sent: list | None = None,
                             module: str | None = None,
                             step: str | None = None) -> httpx.Response:
        """Раунд 10 (F-7 §5.2): резолв ключа чата + _post с этим ключом.
        `key` — уже решённый per-call источник (фикс R6); None → резолв
        здесь (легаси-путь).

        ``sent`` — INS-EXACT: per-call список фактически отправленных тел
        (``(channel, body)``); дописывается ТОТ ЖЕ объект, что уходит в HTTP.
        ``module``/``step`` — только для R17-safe полей диаг-лога транспорта.
        """
        if key is None:
            key, _source = await self._resolve_api_key_and_source(chat_id)
        return await self._post(path, payload, api_key=key, sent=sent,
                                module=module, step=step)

    async def _post_fallback(self, payload: dict, path: str = "/chat/completions",
                             model: str | None = None,
                             timeout: float | None = None,
                             sent: list | None = None) -> httpx.Response:
        """Epic 53 (62.4): РОВНО одна попытка на фоллбэке, БЕЗ ретраев.

        Тот же payload, model заменён на LLM_FALLBACK_MODEL (или переданную —
        для /embeddings используется primary embed-модель на фоллбэк-базе).
        Ошибки (транспорт/не-2xx) разбирает вызывающий — проброс исходного
        исключения primary.
        ASAP 4.1 волна 4 (spec §4 D.1/D.2, ADR-1028-8 D5): ``timeout`` —
        per-request transport-окно supervised-попытки (None → СОБСТВЕННЫЙ
        таймаут фоллбэка `LLM_FALLBACK_TIMEOUT_SECONDS`, не primary 180с;
        ретрай fallback-ноги решает Supervisor — один транспорт-ретрай =
        ≤1 fallback-transport-retry из attempt-потолка ≤4 HTTP).
        """
        self._refresh_transport_policy()
        client = self._get_fallback_client()
        url = f"{self._fallback_base_url.rstrip('/')}{path}"
        fallback_payload = dict(payload)
        fallback_payload["model"] = model or self._fallback_model
        # INS-EXACT: журнал получает РОВНО это тело (с подменённой model),
        # а не payload до fallback-подмены.
        if sent is not None:
            sent.append(("fallback", fallback_payload))
        # P0 SMART: фоллбэк использует СОБСТВЕННОЕ окно попытки
        # (LLM_FALLBACK_TIMEOUT_SECONDS), а не primary-таймаут 180с. Явный
        # per-call timeout (supervised Summary) сохраняется как есть.
        effective_fallback_timeout = _policy_float(
            self._fallback_timeout, settings.LLM_FALLBACK_TIMEOUT_SECONDS, 1.0)
        if timeout is not None:
            try:
                explicit_fb = float(timeout)
            except (TypeError, ValueError):
                explicit_fb = 0.0
            if explicit_fb > 0:
                effective_fallback_timeout = explicit_fb
        return await client.post(
            url, json=fallback_payload,
            timeout=httpx.Timeout(effective_fallback_timeout, connect=10.0))

    async def _fallback_with_retries(self, payload: dict,
                                     sent: list | None = None
                                     ) -> httpx.Response | None:
        """Epic 64: фоллбэк с ретраями транзиентных отказов (429/5xx/транспорт).

        Детерминированные не-200 (400/401/403/404…) НЕ ретраятся. По исчерпании
        попыток логируется СТАРЫЙ формат «LLM fallback failed | error=…»
        (диаг-контракт Betterstack) и возвращается None → вызывающий пробрасывает
        ИСХОДНОЕ исключение primary.
        """
        total_attempts = self._fallback_max_retries + 1
        last_error = "unknown"
        for attempt in range(total_attempts):
            if attempt > 0:
                if self.backoff_base > 0:
                    await asyncio.sleep(
                        min(self.backoff_base * (2 ** (attempt - 1)),
                            self._backoff_cap))
                logger.warning(
                    "LLM fallback retry | attempt=%d/%d | reason=%s",
                    attempt + 1, total_attempts, last_error,
                )
            try:
                async with asyncio.timeout(self._fallback_timeout):
                    fb_resp = await self._post_fallback(payload, sent=sent)
            except Exception as fb_exc:
                # T-2467: содержательный R17-safe текст (repr при пустом
                # str) вместо `Type: ` у ReadTimeout/TimeoutError.
                last_error = (f"{type(fb_exc).__name__}: "
                              f"{_safe_exc_text(fb_exc)}")
                continue
            if fb_resp.status_code == 200:
                return fb_resp
            last_error = f"status={fb_resp.status_code}"
            if not (fb_resp.status_code == 429 or 500 <= fb_resp.status_code < 600):
                break
        # T-2467: контекст диагностики (провайдер/model/таймаут/число попыток)
        # без секретов и полного URL. Логику ретраев выше НЕ меняем.
        logger.warning(
            "LLM fallback failed | error=%s | provider=%s | model=%s | "
            "timeout=%s | attempts=%d",
            last_error, _provider_host(self._fallback_base_url),
            self._fallback_model, self._fallback_timeout, total_attempts,
        )
        return None

    async def _post_embed_fallback(self, payload: dict,
                                   api_key: str,
                                   base_url: str | None = None,
                                   model: str | None = None) -> httpx.Response:
        """Одна попытка POST {embed_fallback}/embeddings на ОБЩЕМ клиенте
        embed-фоллбэка; Bearer <api_key> каскада — заголовок конкретного
        запроса (клиент без auth, ключей в нём нет). base_url/model —
        профиль D11 (13C.1): None → легаси-общие значения (паритет)."""
        client = self._get_embed_fallback_client()
        url = (f"{(base_url or self._embed_fallback_base_url).rstrip('/')}"
               "/embeddings")
        fallback_payload = dict(payload)
        fallback_payload["model"] = model or self._embed_fallback_model
        # P0 SMART: окно — СОБСТВЕННЫЙ таймаут embed-фоллбэка (не primary).
        return await client.post(
            url, json=fallback_payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(self._embed_fallback_timeout, connect=10.0))

    async def _embed_fallback_with_retries(self,
                                           payload: dict,
                                           api_key: str,
                                           base_url: str | None = None,
                                           model: str | None = None
                                           ) -> httpx.Response | None:
        """Embed-фоллбэк ОДНИМ ключом каскада с ретраями транзиентных отказов
        (429/5xx/транспорт; EMBEDDING_FALLBACK_MAX_RETRIES), общий таймаут
        попытки EMBEDDING_FALLBACK_TIMEOUT_SECONDS (asyncio.timeout).
        Детерминированные не-200 (400/401/403/404…) НЕ ретраятся (break).
        По исчерпании попыток — WARNING «LLM fallback failed | kind=embed |
        error=…» (диаг-контракт Betterstack) и None → вызывающий пробует
        следующий ключ каскада либо пробрасывает ИСХОДНОЕ исключение primary."""
        total_attempts = self._embed_fallback_max_retries + 1
        last_error = "unknown"
        for attempt in range(total_attempts):
            if attempt > 0:
                if self.backoff_base > 0:
                    await asyncio.sleep(
                        min(self.backoff_base * (2 ** (attempt - 1)),
                            self._backoff_cap))
                logger.warning(
                    "LLM embed fallback retry | attempt=%d/%d | reason=%s",
                    attempt + 1, total_attempts, last_error)
            try:
                async with asyncio.timeout(self._embed_fallback_timeout):
                    fb_resp = await self._post_embed_fallback(
                        payload, api_key, base_url=base_url, model=model)
            except Exception as fb_exc:
                last_error = f"{type(fb_exc).__name__}: {fb_exc}"
                continue
            if fb_resp.status_code == 200:
                return fb_resp
            last_error = f"status={fb_resp.status_code}"
            if not (fb_resp.status_code == 429 or 500 <= fb_resp.status_code < 600):
                break
        logger.warning("LLM fallback failed | kind=embed | error=%s", last_error)
        return None

    async def generate(self, messages: list[dict[str, str]],
                       temperature: float | None = None,
                       chat_id: int | None = None, *,
                       module: str | None = None,
                       step: str | None = None,
                       correlation_id: str | None = None,
                       fallback_payload_adapter=None,
                       supervised_transport: dict | None = None,
                       max_output_tokens: int | None = None) -> str:
        """Текстовый фасад: ровно ``(await generate_with_metadata(...)).text``.

        UR-18: сигнатура и возвращаемый ``str`` не менялись — все прежние
        потребители (и тест-двойники, переопределяющие ``generate``) работают
        байт-в-байт. Полный контракт (payload, ретраи, fallback, логи,
        аналитика) — в ``generate_with_metadata()``.
        """
        completion = await self.generate_with_metadata(
            messages, temperature, chat_id, module=module, step=step,
            correlation_id=correlation_id,
            fallback_payload_adapter=fallback_payload_adapter,
            supervised_transport=supervised_transport,
            max_output_tokens=max_output_tokens)
        return completion.text

    async def generate_with_metadata(self, messages: list[dict[str, str]],
                                     temperature: float | None = None,
                                     chat_id: int | None = None, *,
                                     module: str | None = None,
                                     step: str | None = None,
                                     correlation_id: str | None = None,
                                     fallback_payload_adapter=None,
                                     supervised_transport: dict | None = None,
                                     max_output_tokens: int | None = None
                                     ) -> LLMCompletion:
        """POST /chat/completions → choices[0].message.content.

        Epic 60 (65.8, T-476): temperature — опциональный kwarg; None →
        ключ в payload НЕ добавляется (ровно старое поведение для всех
        остальных вызовов; дефолт провайдера).

        MCA-23 (Wave 3, §Model slots): ``max_output_tokens`` — опциональный
        kwarg; None/<=0 → ключ ``max_tokens`` в payload НЕ добавляется
        (байт-паритет всех прежних вызовов). Передаётся только явно
        longform-планами (services/response_extent); fallback-адаптер
        затрагивает только messages, ключ переживает recompose.

        Раунд 10 (F-7 §5.2): chat_id — BYOK-слой (свой ключ чата →
        глобальный с бюджетом; None → ровно старое поведение — глобальный
        ключ, embed-путь). Без ключа → NoApiKeyForChat (sandbox).

        Epic 53 (62.4): при LLMError primary (кроме LLMBadResponseError) и
        активном фоллбэке — 1 попытка на фоллбэке; фейл фоллбэка → проброс
        ИСХОДНОГО исключения primary (CB-классификация работает по классу).

        Эпик 04.09.2026 (3.3): контракт {model, messages[, temperature]}
        НЕ меняется — tools уходят ТОЛЬКО новым generate_chat (FR-10).

        ASAP-3.1 (ADR-1028-3 §14/§42): ``fallback_payload_adapter`` —
        необязательный callable ``(payload) -> payload``; вызывается РОВНО
        ОДИН раз при переключении на fallback ДО отправки (recompose под
        меньшее окно fallback-модели). None/ошибка адаптера → payload
        байт-в-байт прежний (fail-open; паритет со всеми прежними вызовами).

        ASAP 4.1 волна 4 (spec §4 D.1, ADR-1028-8 D5; scope = Summary
        только): ``supervised_transport`` — transport-контракт, который
        передаёт LLMExecutionSupervisor (ЕДИНСТВЕННЫЙ источник; прочие
        потребители не передают → байт-в-бит). При переданном контракте:
        per-call ``budget``/``max_retries=1``/``retry_statuses=()``/per-
        request ``timeout`` идут в ``_post``, а ВНУТРЕННИЙ fallback-каскад
        ``_fallback_with_retries`` ВЫКЛЮЧЕН — provider-fallback решает
        Supervisor (no retry multiplication: 1 primary + ≤1 primary
        transport retry + ≤1 fallback + ≤1 fallback transport retry).

        UR-18 (UNIFIED-REPLY §7): возвращает ``LLMCompletion`` — тот же текст
        плюс finish_reason/provider/model/usage/max_output_tokens_sent/
        attempt/correlation_id и цепочку fallback-ног. Поведение вызова
        (ретраи, таймауты, temperature, выбор модели, промпты, бюджеты,
        логи, аналитика) НЕ менялось: это ровно прежний generate + сбор
        метаданных из уже полученного ответа (никаких новых LLM-вызовов).
        """
        # P0 SMART transport: hot-apply модели/адреса/политики ДО сборки
        # payload — смена в админке действует на этот вызов без рестарта.
        self._refresh_chat_model()
        self._refresh_transport_policy()
        # ФИКС R6: key/source — per-call локалы (нет гонки параллельных чатов).
        key, source = await self._resolve_api_key_and_source(chat_id)
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        # MCA-23 (Wave 3): модельный слот длины для longform-планов. Не-верхняя
        # граница ответа, а потолок; None → ключ отсутствует (паритет).
        if max_output_tokens is not None:
            try:
                _max_out = int(max_output_tokens)
            except (TypeError, ValueError):
                _max_out = 0
            if _max_out > 0:
                payload["max_tokens"] = _max_out
        # F7 (review iter1): фактически использованная модель — при срабатывании
        # фоллбэка цена/токены атрибутируются правильной модели.
        used_model = self._chat_model
        # INS-EXACT/INS-TRACE: per-call список фактически отправленных тел
        # (канал, тело). Журнал берёт ПОСЛЕДНЕЕ — то, что реально ушло.
        sent: list = []
        # UR-18: неуспешные ноги цепочки провайдеров ДО успешной.
        fallback_chain: list[LLMProviderAttempt] = []
        try:
            if supervised_transport is not None:
                # ASAP 4.1 волна 4: supervised Summary-канал — per-call
                # transport-контракт Supervisor'а (ADR-1028-8 D5.2); ключ
                # уже резолвнут выше (тот же BYOK-слой).
                response = await self._post(
                    "/chat/completions", payload, api_key=key,
                    budget=supervised_transport.get("budget"),
                    max_retries=int(supervised_transport.get("max_retries", 1)),
                    retry_statuses=tuple(
                        supervised_transport.get("retry_statuses", ()) or ()),
                    timeout=supervised_transport.get("timeout"),
                    budget_reason_label=str(
                        supervised_transport.get("budget_reason_label") or ""),
                    sent=sent, module=module, step=step,
                )
            else:
                response = await self._post_with_key(
                    "/chat/completions", payload, chat_id=chat_id, key=key,
                    sent=sent, module=module, step=step)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:
            # INS-TRACE: неудачная попытка тоже реальный вызов провайдера —
            # фиксируем ВСЕ отправленные тела этой попытки (ретраи видны).
            self._record_sent_attempts(
                sent, payload=payload, messages=messages,
                module=module, step=step, correlation_id=correlation_id,
                chat_id=chat_id, status="error", error=type(exc).__name__)
            if supervised_transport is not None:
                # Supervisor — единственный владелец fallback-решения
                # (ADR-1028-8 D5.3: no retry multiplication) — внутренний
                # каскад для supervised-канала не запускается.
                raise
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            _LLM_STATS["fallbacks"] += 1
            # UR-18: отказ primary фиксируется ДО отправки fallback-ноги, чтобы
            # метаданные успешного фоллбэка всегда содержали причину перехода.
            fallback_chain.append(LLMProviderAttempt(
                channel="primary", model=str(self._chat_model),
                provider=_provider_host(self._base_url),
                error_type=type(exc).__name__,
                error=_safe_exc_text(exc)))
            logger.warning(
                "LLM fallback attempt | primary_error=%s | provider=%s",
                exc, _provider_host(self._fallback_base_url))
            if fallback_payload_adapter is not None:
                try:
                    adapted = fallback_payload_adapter(payload)
                    if isinstance(adapted, tuple) and len(adapted) == 2:
                        # UR-F шаг 1 (Q6): адаптер возвращает (body,
                        # prepared-вариант); вариант держит сервис, здесь нужен
                        # только body.
                        adapted = adapted[0]
                    if isinstance(adapted, dict) and adapted.get("messages"):
                        payload = adapted
                        logger.info(
                            "LLM fallback recompose | blocks_ok=1")
                    else:
                        # ADR-1028-5 D10 (усиление): адаптер вернул непригодную
                        # форму — честная диагностика, отправка primary-payload
                        # в меньшее окно ВИДИМА (не тихий fail-open).
                        logger.warning(
                            "LLM fallback recompose invalid (shape) — primary "
                            "payload SENT AS-IS | oversized_risk=1 | "
                            "adapted_type=%s", type(adapted).__name__)
                except Exception:
                    # ADR-1028-5 D10 (усиление против ASAP-3.1 :1010–1012):
                    # recompose failure — громкая честная диагностика
                    # (oversized-risk), НЕ тихая отправка. Fail-open
                    # сохранён (паритет ASAP-3.1; сервис не рвём).
                    logger.warning(
                        "LLM fallback recompose FAILED — primary payload "
                        "SENT AS-IS | oversized_risk=1 | fallback_window=%s",
                        self._fallback_model, exc_info=True)
            fb_response = await self._fallback_with_retries(payload, sent=sent)
            if fb_response is None:
                # review r2 F2: общий провал — в журнал пишутся ВСЕ фактические
                # fallback-попытки (status=error), последняя = last actual.
                self._record_sent_attempts(
                    sent, payload=payload, messages=messages, module=module,
                    step=step, correlation_id=correlation_id, chat_id=chat_id,
                    status="error", error=type(exc).__name__, channel="fallback")
                raise exc from None
            response = fb_response
            used_model = self._fallback_model
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
        try:
            data = response.json()
        except ValueError as exc:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status="error", error="LLMBadResponseError")
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        # P0 L1 (2026-11-17): ЕДИНЫЙ нормализатор формы ответа. «HTTP 200» сам
        # по себе не ответ: content-parts/reasoning-only/пустой content/ошибка
        # провайдера внутри 200 получают явный класс вместо падения на
        # индексации словаря. Reasoning в текст ответа НЕ подставляется.
        classified = classify_chat_response(data)
        content = classified.content
        if classified.kind != RESPONSE_KIND_TEXT or not content:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status="error", error="LLMBadResponseError")
            reason = classified.kind
            if classified.error_code:
                reason = f"{reason}:{classified.error_code}"
            exc = LLMBadResponseError(
                "chat/completions: no final text | "
                f"kind={reason} | finish_reason={classified.finish_reason}")
            # P0 L1: класс исхода/причина доступны вызывающему in-process
            # (матрица repair/retry решает по ним, а не по тексту сообщения).
            exc.response_kind = classified.kind
            exc.llm_finish_reason = classified.finish_reason
            exc.reasoning_chars = int(classified.reasoning_chars)
            raise exc
        logger.info(
            "LLM generate OK | model=%s | out_chars=%d", self._chat_model, len(content)
        )
        # INS-TRACE/INS-EXACT: снимок ровно того тела, что ушло провайдеру
        # (после adapt/fallback-recompose): checksum считается по этому телу.
        self._record_sent_call(
            sent, payload=payload, messages=messages, module=module,
            step=step, correlation_id=correlation_id, chat_id=chat_id)
        await self._record_global_usage(chat_id, content, source=source)
        usage = data.get("usage") if isinstance(data, dict) else None
        await self._record_analytics(usage, messages, content, source=source,
                                     module=module, step=step,
                                     correlation_id=correlation_id,
                                     chat_id=chat_id, model=used_model)
        # UR-18: метаданные собираются из УЖЕ полученного ответа и последнего
        # фактически отправленного тела — новых вызовов/изменений поведения нет.
        finish_reason, finish_reason_raw = _choice_finish_reason(data)
        sent_channel, sent_body = _sent_body(sent, payload)
        provider = _provider_host(
            self._fallback_base_url if sent_channel == "fallback"
            else self._base_url)
        model = str(sent_body.get("model") or used_model)
        return LLMCompletion(
            text=content,
            finish_reason=finish_reason,
            provider=provider,
            model=model,
            usage=usage if isinstance(usage, dict) else None,
            max_output_tokens_sent=_sent_max_output_tokens(sent_body),
            attempt=len(fallback_chain) + 1,
            correlation_id=correlation_id,
            fallback_chain=tuple(fallback_chain),
            finish_reason_raw=finish_reason_raw,
            sent_body=copy.deepcopy(sent_body) if isinstance(sent_body, dict)
            else None,
            response_kind=classified.kind,
            reasoning_chars=int(classified.reasoning_chars),
        )

    async def generate_background(self, messages: list[dict[str, str]], *,
                                  purpose: str, deadline: float,
                                  max_attempts: int) -> str:
        """F1 (ADR-1024-6 D1): отдельный канал для ФОНОВЫХ LLM-вызовов.

        Не участвует в ``physical-two-call`` (не пишет System-2 аналитику) и
        НЕ меняет общие ``self._budget``/``self._max_retries``: дедлайн и число
        попыток передаются per-call в ``_post`` (для остальных потребителей
        поведение не смещается). Использует глобальный ключ (chat-независимо).
        При исчерпании попыток бросает ``LLMError``-подкласс — решение
        (повтор/отброс батча) принимает caller.
        """
        # P0 SMART transport: hot-apply модели/адреса/политики на входе.
        self._refresh_chat_model()
        self._refresh_transport_policy()
        key = self._current_api_key()
        payload = {"model": self._chat_model, "messages": messages}
        sent: list = [("primary", payload)]
        try:
            response = await self._post(
                "/chat/completions", payload, api_key=key,
                budget=float(deadline),
                max_retries=max(0, int(max_attempts) - 1),
                module="background", step=str(purpose or "background"))
        except Exception as exc:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module="background",
                step=str(purpose or "background"), correlation_id=None,
                chat_id=None, status="error", error=type(exc).__name__)
            raise
        try:
            data = response.json()
        except ValueError as exc:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module="background",
                step=str(purpose or "background"), correlation_id=None,
                chat_id=None, status="error", error="LLMBadResponseError")
            raise LLMBadResponseError(
                "chat/completions background: invalid JSON response") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module="background",
                step=str(purpose or "background"), correlation_id=None,
                chat_id=None, status="error", error="LLMBadResponseError")
            raise LLMBadResponseError(
                "chat/completions background: no choices[0].message.content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            self._record_sent_call(
                sent, payload=payload, messages=messages, module="background",
                step=str(purpose or "background"), correlation_id=None,
                chat_id=None, status="error", error="LLMBadResponseError")
            raise LLMBadResponseError("chat/completions background: empty content")
        # INS-TRACE: фоновый канал фиксируется тем же bounded-журналом — и
        # только после валидного ответа (review r2 F4: не «ok» перед падением).
        self._record_sent_call(
            sent, payload=payload, messages=messages, module="background",
            step=str(purpose or "background"), correlation_id=None, chat_id=None)
        logger.info(
            "LLM background OK | purpose=%s | model=%s | out_chars=%d",
            purpose, self._chat_model, len(content))
        return content

    # ── F3/T-1439 (cognition-deep-sleep, ADR-1013-1): роутер воркеров ───────
    # Единые PG-ключи выделенных LLM (role history → intel_history,
    # background → intel_bg, reflection → intel_reflection). Пустые поля →
    # основная модель (no-op, нулевой регресс); ошибка dedicated → фоллбэк на
    # основную. R17: ключ не логируем.
    # Раунд 10.14 (F1 anti-echo-self-reply): роль `reflection` — экстрактор
    # сути self-ответа (F8 может наполнить keys/models.intel_reflection_*;
    # при пустых полях — прозрачный фоллбэк на основную модель).
    _WORKER_ROLE_PREFIX = {
        "history": "intel_history",
        "background": "intel_bg",
        "bg": "intel_bg",
        "reflection": "intel_reflection",
    }

    def _worker_profile(self, role: str) -> tuple[str, str, str, bool]:
        """(base_url, model, api_key, dedicated) для роли воркера.

        dedicated=True только если задан хотя бы один из трёх ключей
        (`models.intel_<role>_base_url`/`_model_name`/`keys.intel_<role>_api_key`);
        иначе вызывающий идёт прямым путём основной модели (ADR-1013-1 §2.2).
        Пустые поля подставляются значениями основной модели. R17: значение
        ключа нигде не логируется."""
        slug = self._WORKER_ROLE_PREFIX.get(str(role or "").strip().lower())
        if slug is None:
            raise ValueError(f"unknown worker role: {role!r}")
        raw_base = (hot.get(f"models.{slug}_base_url", "") or "").strip()
        raw_model = (hot.get(f"models.{slug}_model_name", "") or "").strip()
        raw_key = (hot.get(f"keys.{slug}_api_key", "") or "").strip()
        base = raw_base or self._base_url
        model = raw_model or self._chat_model
        key = raw_key or self._current_api_key()
        dedicated = bool(raw_base or raw_model or raw_key)
        return base, model, key, dedicated

    async def generate_worker(self, role: str, messages: list[dict[str, str]],
                              *, temperature: float | None = None,
                              chat_id: int | None = None) -> str:
        """Вызов выделенной LLM роли воркера (`history` | `background` |
        `reflection`) с фоллбэком на основную модель (F3/T-1439, spec §5;
        F1 round1014: `reflection`).

        Пустые поля выделенного подключения → ровно `generate` (байт-в-байт
        старое поведение). При ошибке/пустом ответе dedicated — WARNING и
        повтор вызова основной модели (fail-open). R17: ключи не логируются."""
        base, model, key, dedicated = self._worker_profile(role)
        if not dedicated:
            return await self.generate(messages, temperature=temperature,
                                       chat_id=chat_id)
        payload: dict = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        sent: list = [("primary", payload)]
        try:
            response = await self._post(
                "/chat/completions", payload, api_key=key,
                base_url=base, channel="chat",
                module="worker", step=str(role or "worker"))
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMBadResponseError("worker llm: empty content")
        except Exception as exc:
            logger.warning(
                "[worker_llm] dedicated failed → main | role=%s | error=%s",
                role, type(exc).__name__)
            self._record_sent_call(
                sent, payload=payload, messages=messages,
                module="worker", step=str(role or "worker"),
                correlation_id=None, chat_id=chat_id, status="error",
                error=type(exc).__name__)
            return await self.generate(messages, temperature=temperature,
                                       chat_id=chat_id)
        self._record_sent_call(
            sent, payload=payload, messages=messages, module="worker",
            step=str(role or "worker"), correlation_id=None, chat_id=chat_id)
        logger.info(
            "[worker_llm] dedicated OK | role=%s | model=%s | out_chars=%d",
            role, model, len(content))
        return content

    async def generate_chat(self, messages, *, temperature: float | None = None,
                            tools: list[dict] | None = None,
                            tool_choice: str | dict = "auto",
                            chat_id: int | None = None,
                            module: str | None = None,
                            step: str | None = None,
                            correlation_id: str | None = None,
                            tool_name: str = "",
                            fallback_payload_adapter=None,
                            max_output_tokens: int | None = None
                            ) -> "LLMChatResult":
        """POST /chat/completions с tools/tool_choice (Эпик 04.09.2026, 3.3).

        Контракт {model, messages}: температура — как в generate (None →
        ключа нет); tools/tool_choice добавляются в payload ТОЛЬКО когда
        tools передан. Ретраи/фоллбэк _post/_fallback_with_retries — как в
        generate (payload сквозной). Парсинг: content (может быть None при
        tool_calls) + tool_calls + finish_reason. Легаси generate() НЕ
        меняется (0 регрессий, FR-10/AC-2.1).

        MCA-23 фаза 2 (§Model slots): ``max_output_tokens`` — тот же
        контракт, что в generate(): None/<=0 → ключ ``max_tokens`` в
        payload НЕ добавляется (байт-паритет всех прежних tool-вызовов);
        передаётся только явно longform-планами (services/response_extent).
        Ключ переживает fallback-recompose (адаптер меняет только messages).
        Раунд 10 (F-7 §5.2): chat_id — BYOK-слой (см. generate). ФИКС R6:
        key/source — per-call локалы.

        ASAP-3.2 (ADR-1028-5 D10, §44–§46): ``fallback_payload_adapter`` —
        тот же контракт, что в ``generate()``: callable ``(payload) ->
        payload``; вызывается РОВНО ОДИН раз при переключении на fallback
        ДО отправки — recompose ПОЛНОГО logical context (messages +
        tool schemas + tool state) под окно fallback-модели. Tool
        schemas входят в fallback budget (§45) — recompose обязан их
        учитывать (адаптер получает payload с ``tools``/``tool_choice``).
        None/ошибка адаптера → payload байт-в-байт прежний (fail-open с
        громкой oversized-risk диагностикой, паритет generate()).
        """
        # P0 SMART transport: hot-apply модели/адреса/политики на входе.
        self._refresh_chat_model()
        self._refresh_transport_policy()
        key, source = await self._resolve_api_key_and_source(chat_id)
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        # MCA-23 фаза 2 (§Model slots): модельный слот длины — тот же
        # контракт, что в generate(); None → ключа нет (паритет).
        if max_output_tokens is not None:
            try:
                _max_out = int(max_output_tokens)
            except (TypeError, ValueError):
                _max_out = 0
            if _max_out > 0:
                payload["max_tokens"] = _max_out
        # F7 (review iter1): фактически использованная модель (фоллбэк).
        used_model = self._chat_model
        # INS-EXACT/INS-TRACE: тот же bounded-журнал, что у generate().
        sent: list = []
        try:
            response = await self._post_with_key(
                "/chat/completions", payload, chat_id=chat_id, key=key,
                sent=sent, module=module, step=step)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:
            # INS-TRACE: все фактические попытки primary (ретраи видны),
            # а не только последнее тело — как в generate().
            self._record_sent_attempts(
                sent, payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status="error", error=type(exc).__name__)
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            _LLM_STATS["fallbacks"] += 1
            logger.warning(
                "LLM fallback attempt | primary_error=%s | provider=%s",
                exc, _provider_host(self._fallback_base_url))
            if fallback_payload_adapter is not None:
                try:
                    adapted = fallback_payload_adapter(payload)
                    if isinstance(adapted, tuple) and len(adapted) == 2:
                        # UR-F шаг 1 (Q6): адаптер возвращает (body,
                        # prepared-вариант); вариант держит сервис, здесь нужен
                        # только body.
                        adapted = adapted[0]
                    if isinstance(adapted, dict) and adapted.get("messages"):
                        payload = adapted
                        logger.info(
                            "LLM fallback recompose | blocks_ok=1 | "
                            "tools=%s",
                            "kept" if adapted.get("tools") else "none")
                    else:
                        # ADR-1028-5 D10 (усиление): непригодная форма
                        # адаптера — видимая oversized-risk диагностика.
                        logger.warning(
                            "LLM fallback recompose invalid (shape) — "
                            "primary payload SENT AS-IS | oversized_risk=1 "
                            "| adapted_type=%s", type(adapted).__name__)
                except Exception:
                    logger.warning(
                        "LLM fallback recompose FAILED — primary payload "
                        "SENT AS-IS | oversized_risk=1 | tools_in_payload=%s",
                        bool(payload.get("tools")), exc_info=True)
            fb_response = await self._fallback_with_retries(payload, sent=sent)
            if fb_response is None:
                # review r2 F2: общий провал — в журнал пишутся ВСЕ фактические
                # fallback-попытки (status=error), последняя = last actual.
                self._record_sent_attempts(
                    sent, payload=payload, messages=messages, module=module,
                    step=step, correlation_id=correlation_id, chat_id=chat_id,
                    status="error", error=type(exc).__name__, channel="fallback")
                raise exc from None
            response = fb_response
            used_model = self._fallback_model
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
        try:
            data = response.json()
        except ValueError as exc:
            self._record_sent_call(
                sent, payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status="error", error="LLMBadResponseError")
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        # P0 L1 (2026-11-17): тот же единый нормализатор, что у generate()/
        # dedicated-Generate: content (строка/null/пустая/content-parts),
        # tool_calls, reasoning-алиасы и ошибка внутри HTTP 200 разбираются
        # один раз и одинаково. Reasoning НЕ смешивается с content.
        classified = classify_chat_response(data)
        choice = (data.get("choices") or [{}])[0] \
            if isinstance(data, dict) else {}
        if not isinstance(choice, dict):
            choice = {}
        content = classified.content
        tool_calls = list(classified.tool_calls) or None
        reasoning_text = classified.reasoning
        if classified.kind not in (RESPONSE_KIND_TEXT,
                                   RESPONSE_KIND_TOOL_CALLS) \
                and not reasoning_text:
            # review r2 F3: HTTP 200 с пустым content — реальный вызов, но
            # ответ невалиден: журнал не должен молча терять эту попытку.
            self._record_sent_call(
                sent, payload=payload, messages=messages, module=module,
                step=step, correlation_id=correlation_id, chat_id=chat_id,
                status="error", error="LLMBadResponseError")
            reason = classified.kind
            if classified.error_code:
                reason = f"{reason}:{classified.error_code}"
            exc = LLMBadResponseError(
                "chat/completions: empty content (no tool_calls) | "
                f"kind={reason} | finish_reason={classified.finish_reason}")
            exc.response_kind = classified.kind
            exc.llm_finish_reason = classified.finish_reason
            exc.reasoning_chars = int(classified.reasoning_chars)
            raise exc
        logger.info(
            "LLM generate_chat OK | model=%s | out_chars=%s | tool_calls=%d",
            self._chat_model,
            len(str(content)) if content is not None else "-",
            len(tool_calls) if tool_calls else 0,
        )
        if classified.reasoning_only:
            # Reasoning-only ответ: штатной деградации (молчание/🗿) — без
            # нештатного LLMBadResponseError. Содержимое черновика не логируем.
            logger.warning(
                "LLM generate_chat reasoning-only | model=%s | "
                "reasoning_chars=%d | finish_reason=%s",
                self._chat_model, int(classified.reasoning_chars),
                classified.finish_reason)
        content_text = content if classified.kind == RESPONSE_KIND_TEXT else None
        # INS-TRACE: tool-calling вызов фиксируется тем же журналом (реальный
        # Stage-1/tool вызов — не только generate()).
        self._record_sent_call(
            sent, payload=payload, messages=messages, module=module,
            step=step or "tool_call", correlation_id=correlation_id,
            chat_id=chat_id)
        await self._record_global_usage(chat_id, content_text, source=source)
        usage = classified.usage
        await self._record_analytics(usage, messages, content, source=source,
                                     module=module, step=step,
                                     correlation_id=correlation_id,
                                     chat_id=chat_id, model=used_model,
                                     tool_name=tool_name)
        return LLMChatResult(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            reasoning=reasoning_text,
            response_kind=classified.kind,
            # UR-F шаг 1 (Q1): фактически отправленный body (после fallback).
            sent_body=(copy.deepcopy(_sent_body(sent, payload)[1])
                       if isinstance(_sent_body(sent, payload)[1], dict)
                       else None),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """POST /embeddings → data[i].embedding. Raises LLMError on any failure (R3).

        Embed-фоллбэк (EMBEDDING_FALLBACK_*, независим от chat-фоллбэка
        62.4): при LLMError primary (кроме LLMBadResponseError) и активном
        embed-фоллбэке — КАСКАД по ключам: каждый ключ (с ретраями
        транзиентных отказов EMBEDDING_FALLBACK_MAX_RETRIES) на
        {EMBEDDING_FALLBACK_BASE_URL}/embeddings; фейл ВСЕХ ключей → проброс
        ИСХОДНОГО исключения primary (KNN→FTS-каскад в summary_memory решает
        деградацию)."""
        # P0 SMART transport: политика — на входе; для embed действует
        # технический потолок 60с (не 180с чата), per-request окно в _post.
        self._refresh_transport_policy()
        if not texts:
            return []
        used_model = self._embed_model
        try:
            response = await self._post(
                "/embeddings",
                {"model": self._embed_model, "input": texts},
                api_key=self._current_embed_api_key(),
                base_url=self._embed_base_url,
                channel="embed",
                module="embedding", step="embed",
            )
        except LLMError as exc:
            if not self._embed_fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            fb_response = None
            fb_idx = 0
            fb_model = self._embed_fallback_model
            # D11 (13C.1): каскад по НЕЗАВИСИМЫМ профилям (Fallback 1 →
            # Fallback 2), у каждого свой base_url/model/key.
            for idx, prof in enumerate(self._embed_fallback_profiles):
                logger.warning(
                    "LLM embed fallback attempt | profile=%s | primary_error=%s",
                    prof.get("alias") or idx, f"{type(exc).__name__}: {exc}",
                )
                fb_response = await self._embed_fallback_with_retries(
                    {"input": texts}, prof["key"],
                    base_url=prof.get("base_url") or None,
                    model=prof.get("model") or None)
                if fb_response is not None:
                    fb_idx = idx
                    fb_model = prof.get("model") or self._embed_fallback_model
                    break
                logger.warning("LLM embed fallback profile %s failed",
                               prof.get("alias") or idx)
            if fb_response is None:
                # Задача 2: человекочитаемая причина + рекомендация (консоль)
                logger.warning(
                    "LLM embed fallback exhausted | profiles=%d | reason=%s",
                    len(self._embed_fallback_profiles),
                    humanize_embed_error(exc))
                raise exc from None
            response = fb_response
            used_model = fb_model
            logger.warning("LLM embed fallback OK | model=%s | profile_idx=%d",
                           used_model, fb_idx)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("embeddings: invalid JSON response") from exc
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise LLMBadResponseError("embeddings: no data[].embedding in response") from exc
        # EMBED-META-WIRE: фактические метаданные ответа — для пробы
        # совместимости (возвращаемое значение не меняется).
        self.last_embed_meta = _embed_response_meta(data, vectors)
        logger.info(
            "LLM embed OK | model=%s | texts=%d", used_model, len(vectors)
        )
        await self._record_embedding_analytics(data, texts, model=used_model)
        return vectors

    async def embed_once(
        self,
        texts: list[str],
        *,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 0,
        retry_statuses: tuple[int, ...] | None = (),
    ) -> list[list[float]]:
        """ASAP-4 (spec §1 A.2/A.3, ADR-1028-7 D1.2): embed ОДНИМ credential
        БЕЗ key-каскада и без нижнеуровневых quota-ретраев — точка
        переиспользования сети/клиентов `LLMClient` адаптером
        `EmbeddingProviderAdapter` (EmbeddingExecutor — единственный владелец
        retry-policy).

        * api_key обязателен (контрол-плейн сам выбирает credential);
        * base_url/model — override (None → embed-дефолты клиента);
        * max_retries — transport retry нижнего слоя (0–1 по контракту A.2);
        * retry_statuses=() (default) → 429/5xx отдаются наверх немедленно
          как исключения (Executor классифицирует); None → нижний слой
          ретраит 429/5xx как раньше (не используется контрол-плейном).
        R17: ключ не логируется; тело ответа не логируется на 429.

        НЕ трогает каскад `embed()` (62.4) — тот остаётся legacy-контуром
        `EMBED_CONTROL_PLANE_ENABLED=false` (бит-в-бит)."""
        # P0 SMART transport: политика — на входе (тот же embed-cap 60с).
        self._refresh_transport_policy()
        if not texts:
            return []
        used_model = model or self._embed_model
        response = await self._post(
            "/embeddings",
            {"model": used_model, "input": texts},
            api_key=api_key,
            base_url=(base_url or self._embed_base_url),
            channel="embed",
            max_retries=max_retries,
            retry_statuses=retry_statuses,
            module="embedding", step="embed",
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("embeddings: invalid JSON response") from exc
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise LLMBadResponseError("embeddings: no data[].embedding in response") from exc
        if len(vectors) != len(texts):
            raise LLMBadResponseError(
                f"embeddings: vectors={len(vectors)} != inputs={len(texts)}")
        # EMBED-META-WIRE: тот же побочный канал, что и в `embed()` —
        # контрол-плейн читает `client.last_embed_meta` после embed_fn.
        self.last_embed_meta = _embed_response_meta(data, vectors)
        # R17: сам ключ не логируется НИКОГДА — алиас credential'а пишет
        # контрол-плейн на своём уровне (spec §0.3/§63).
        logger.info(
            "LLM embed_once OK | model=%s | texts=%d",
            used_model, len(vectors),
        )
        return vectors
