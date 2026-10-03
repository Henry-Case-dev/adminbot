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
"""
import asyncio
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
_LLM_STATS: dict[str, int] = {"requests": 0, "timeouts": 0, "fallbacks": 0}


def llm_stats() -> dict:
    """Снимок LLM-метрик: ``requests``/``timeouts``/``fallbacks`` + доля
    таймаутов (0.0 без запросов). T-2501: наблюдаемость корня A — хронических
    таймаутов провайдера (``nano-gpt.com``)."""
    requests = _LLM_STATS["requests"]
    timeouts = _LLM_STATS["timeouts"]
    fallbacks = _LLM_STATS["fallbacks"]
    return {
        "requests": requests,
        "timeouts": timeouts,
        "fallbacks": fallbacks,
        "timeout_share": (timeouts / requests) if requests else 0.0,
    }

_BODY_MAX_CHARS = 500   # Epic 49 (57.4) / Epic 53 (62.5): тело 4xx/5xx-ответа в диагн-логе
_AUTH_BODY_MAX_CHARS = 200   # Задача 2 (01.09.2026): тело 401/403 в LLMAuthError

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
        self._embed_fallback_active = bool(self._embed_fallback_base_url) and \
            bool(self._embed_fallback_api_keys)
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

    def _current_api_key(self) -> str:
        """T-619 (84.4): ключ читается из ConfigCache на ВЫЗОВ; ключа нет в
        БД → значение из .env/settings (ровно старое поведение до миграции).
        ГЛОБАЛЬНЫЙ слой (embed/vision/видео — вне скоупа BYOK, F-7 §5.2)."""
        return hot.get("keys.llm_api_key", self._api_key) or ""

    def _current_api_key_source(self) -> str:
        """Глобальный слой нетронут: источник 'global' (для резолва)."""
        return "global"

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
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._embed_client_key = key
        return self._embed_client

    def _get_fallback_client(self) -> httpx.AsyncClient:
        """Epic 53 (62.4): ленивый клиент фоллбэка, тот же таймаут-срез.
        T-619: ключ фоллбэка — горячая точка (пересоздание при смене)."""
        key = self._current_fallback_key()
        if self._fallback_client is not None and key != self._fallback_key:
            self._close_async(self._fallback_client)
            self._fallback_client = None
        if self._fallback_client is None:
            self._fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
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
    ) -> float:
        """Epic 47 (56.3): сон перед retry.

        Retry-After (429/5xx, парсится как float, ≥0) приоритетнее обычного
        backoff; значение капится LLM_RETRY_BACKOFF_CAP. Кривой/отрицательный
        header либо статус ≠ 429/5xx → обычный backoff
        `min(BASE*2**attempt, CAP) + U(0, JITTER)`. backoff_base == 0 → сон 0.
        """
        if self.backoff_base == 0:
            return 0.0
        if status is not None and (status == 429 or 500 <= status < 600):
            raw = headers.get("Retry-After") if headers is not None else None
            if raw is not None:
                try:
                    header_seconds = float(raw)
                except (TypeError, ValueError):
                    header_seconds = -1.0
                if header_seconds >= 0:
                    return min(header_seconds, self._backoff_cap)
        base_sleep = min(self.backoff_base * (2 ** attempt), self._backoff_cap)
        return base_sleep + random.uniform(0, self._jitter_max)

    async def _post(self, path: str, payload: dict,
                    api_key: str | None = None,
                    base_url: str | None = None,
                    channel: str = "chat",
                    budget: float | None = None,
                    max_retries: int | None = None,
                    retry_statuses: tuple[int, ...] | None = None,
                    timeout: float | None = None,
                    budget_reason_label: str | None = None) -> httpx.Response:
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
        """
        client = (self._get_embed_client(api_key) if channel == "embed"
                  else self._get_client(api_key))
        base = (base_url or self._base_url).rstrip("/")
        url = f"{base}{path}"
        request_len = len(str(payload))
        post_kwargs: dict = {}
        if timeout is not None:
            # Per-request transport-окно (watchdog Summary-канала): не
            # пересоздаёт кешированный клиент, не трогает других потребителей.
            post_kwargs["timeout"] = httpx.Timeout(timeout, connect=10.0)
        # F1: per-call override (None = прежний self-дефолт).
        call_budget = self._budget if budget is None else budget
        call_retries = self._max_retries if max_retries is None else max_retries
        total_attempts = call_retries + 1
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
                        response = await client.post(url, json=payload,
                                                     **post_kwargs)
                    except httpx.TransportError as exc:
                        # Транзиентное (timeout/connect/read/.../protocol) → ретрай
                        if attempt < call_retries:
                            sleep = self._sleep_seconds(attempt)
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
                            logger.error(
                                "LLM timeout | url=%s | attempt=%d | "
                                "reason=%s | provider=%s",
                                url, attempt, type(exc).__name__,
                                _provider_host(base))
                            raise LLMTimeoutError(
                                f"LLM request timed out after {total_attempts} attempts: {url}"
                            ) from exc
                        raise LLMTransportError(
                            f"LLM transport error after {total_attempts} attempts: {exc}: {url}"
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
                        sleep = self._sleep_seconds(attempt, status, response.headers)
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
                        raise LLMError(f"LLM HTTP {status}: {url}")
                    logger.info(
                        "LLM request OK | url=%s | status=%d | latency_ms=%.0f | in=%d chars | out=%d chars",
                        url, status, latency_ms, request_len, len(response.content),
                    )
                    # Epic 60 (64.7, T-468): фактический лимит — usage из
                    # API-ответа (источник истины для бюджетов/метрик);
                    # парсинг fail-open (нет usage в ответе → нет лога).
                    try:
                        data = response.json()
                    except Exception:
                        data = None
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
            # ASAP 4.1 волна 4 (T-4615, §30 ТЗ): для supervised Summary-канала
            # fuse-ветка = execution_deadline_exceeded; не-Summary потребители —
            # прежняя строка total_budget_exceeded (байт-в-бит).
            budget_reason = ("execution_deadline_exceeded"
                             if budget_reason_label == "summary_supervised"
                             else "total_budget_exceeded")
            logger.error(
                "LLM timeout | url=%s | reason=%s | "
                "provider=%s", url, budget_reason, _provider_host(base))
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}"
            ) from None
        if budget_exceeded:
            _LLM_STATS["timeouts"] += 1
            # T-4615: попытка не стартовала — время call_budget исчерпано →
            # supervised Summary-канал: retry_time_budget_exhausted;
            # не-Summary: прежний budget_exhausted.
            budget_reason = ("retry_time_budget_exhausted"
                             if budget_reason_label == "summary_supervised"
                             else "budget_exhausted")
            logger.error(
                "LLM timeout | url=%s | reason=%s | provider=%s",
                url, budget_reason, _provider_host(base))
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}"
            )
        raise LLMError(f"LLM request failed after retries: {url}")

    async def _post_with_key(self, path: str, payload: dict,
                             chat_id: int | None = None,
                             key: str | None = None) -> httpx.Response:
        """Раунд 10 (F-7 §5.2): резолв ключа чата + _post с этим ключом.
        `key` — уже решённый per-call источник (фикс R6); None → резолв
        здесь (легаси-путь)."""
        if key is None:
            key, _source = await self._resolve_api_key_and_source(chat_id)
        return await self._post(path, payload, api_key=key)

    async def _post_fallback(self, payload: dict, path: str = "/chat/completions",
                             model: str | None = None,
                             timeout: float | None = None) -> httpx.Response:
        """Epic 53 (62.4): РОВНО одна попытка на фоллбэке, БЕЗ ретраев.

        Тот же payload, model заменён на LLM_FALLBACK_MODEL (или переданную —
        для /embeddings используется primary embed-модель на фоллбэк-базе).
        Ошибки (транспорт/не-2xx) разбирает вызывающий — проброс исходного
        исключения primary.
        ASAP 4.1 волна 4 (spec §4 D.1/D.2, ADR-1028-8 D5): ``timeout`` —
        per-request transport-окно supervised-попытки (None → прежний
        клиентский таймаут, байт-в-бит; ретрай fallback-ноги решает
        Supervisor — один транспорт-ретрай = ≤1 fallback-transport-retry
        из attempt-потолка ≤4 HTTP).
        """
        client = self._get_fallback_client()
        url = f"{self._fallback_base_url.rstrip('/')}{path}"
        fallback_payload = dict(payload)
        fallback_payload["model"] = model or self._fallback_model
        post_kwargs: dict = {}
        if timeout is not None:
            post_kwargs["timeout"] = httpx.Timeout(timeout, connect=10.0)
        return await client.post(url, json=fallback_payload, **post_kwargs)

    async def _fallback_with_retries(self, payload: dict) -> httpx.Response | None:
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
                    fb_resp = await self._post_fallback(payload)
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
                                   api_key: str) -> httpx.Response:
        """Одна попытка POST {embed_fallback}/embeddings на ОБЩЕМ клиенте
        embed-фоллбэка; Bearer <api_key> каскада — заголовок конкретного
        запроса (клиент без auth, ключей в нём нет). model —
        _embed_fallback_model (пустая при конструировании → primary
        embed-модель)."""
        client = self._get_embed_fallback_client()
        url = f"{self._embed_fallback_base_url.rstrip('/')}/embeddings"
        fallback_payload = dict(payload)
        fallback_payload["model"] = self._embed_fallback_model
        return await client.post(
            url, json=fallback_payload,
            headers={"Authorization": f"Bearer {api_key}"})

    async def _embed_fallback_with_retries(self,
                                           payload: dict,
                                           api_key: str) -> httpx.Response | None:
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
                    fb_resp = await self._post_embed_fallback(payload, api_key)
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
                       supervised_transport: dict | None = None) -> str:
        """POST /chat/completions → choices[0].message.content.

        Epic 60 (65.8, T-476): temperature — опциональный kwarg; None →
        ключ в payload НЕ добавляется (ровно старое поведение для всех
        остальных вызовов; дефолт провайдера).

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
        """
        # ФИКС R6: key/source — per-call локалы (нет гонки параллельных чатов).
        key, source = await self._resolve_api_key_and_source(chat_id)
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        # F7 (review iter1): фактически использованная модель — при срабатывании
        # фоллбэка цена/токены атрибутируются правильной модели.
        used_model = self._chat_model
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
                )
            else:
                response = await self._post_with_key(
                    "/chat/completions", payload, chat_id=chat_id, key=key)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:
            if supervised_transport is not None:
                # Supervisor — единственный владелец fallback-решения
                # (ADR-1028-8 D5.3: no retry multiplication) — внутренний
                # каскад для supervised-канала не запускается.
                raise
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            _LLM_STATS["fallbacks"] += 1
            logger.warning(
                "LLM fallback attempt | primary_error=%s | provider=%s",
                exc, _provider_host(self._fallback_base_url))
            if fallback_payload_adapter is not None:
                try:
                    adapted = fallback_payload_adapter(payload)
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
            fb_response = await self._fallback_with_retries(payload)
            if fb_response is None:
                raise exc from None
            response = fb_response
            used_model = self._fallback_model
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "chat/completions: no choices[0].message.content in response"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMBadResponseError("chat/completions: empty content")
        logger.info(
            "LLM generate OK | model=%s | out_chars=%d", self._chat_model, len(content)
        )
        await self._record_global_usage(chat_id, content, source=source)
        usage = data.get("usage") if isinstance(data, dict) else None
        await self._record_analytics(usage, messages, content, source=source,
                                     module=module, step=step,
                                     correlation_id=correlation_id,
                                     chat_id=chat_id, model=used_model)
        return content

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
        key = self._current_api_key()
        payload = {"model": self._chat_model, "messages": messages}
        response = await self._post(
            "/chat/completions", payload, api_key=key,
            budget=float(deadline),
            max_retries=max(0, int(max_attempts) - 1))
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError(
                "chat/completions background: invalid JSON response") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "chat/completions background: no choices[0].message.content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMBadResponseError("chat/completions background: empty content")
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
        try:
            response = await self._post(
                "/chat/completions", payload, api_key=key,
                base_url=base, channel="chat")
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMBadResponseError("worker llm: empty content")
        except Exception as exc:
            logger.warning(
                "[worker_llm] dedicated failed → main | role=%s | error=%s",
                role, type(exc).__name__)
            return await self.generate(messages, temperature=temperature,
                                       chat_id=chat_id)
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
                            fallback_payload_adapter=None) -> "LLMChatResult":
        """POST /chat/completions с tools/tool_choice (Эпик 04.09.2026, 3.3).

        Контракт {model, messages}: температура — как в generate (None →
        ключа нет); tools/tool_choice добавляются в payload ТОЛЬКО когда
        tools передан. Ретраи/фоллбэк _post/_fallback_with_retries — как в
        generate (payload сквозной). Парсинг: content (может быть None при
        tool_calls) + tool_calls + finish_reason. Легаси generate() НЕ
        меняется (0 регрессий, FR-10/AC-2.1).
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
        key, source = await self._resolve_api_key_and_source(chat_id)
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        # F7 (review iter1): фактически использованная модель (фоллбэк).
        used_model = self._chat_model
        try:
            response = await self._post_with_key(
                "/chat/completions", payload, chat_id=chat_id, key=key)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            _LLM_STATS["fallbacks"] += 1
            logger.warning(
                "LLM fallback attempt | primary_error=%s | provider=%s",
                exc, _provider_host(self._fallback_base_url))
            if fallback_payload_adapter is not None:
                try:
                    adapted = fallback_payload_adapter(payload)
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
            fb_response = await self._fallback_with_retries(payload)
            if fb_response is None:
                raise exc from None
            response = fb_response
            used_model = self._fallback_model
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "chat/completions: no choices[0] in response"
            ) from exc
        message = choice.get("message") or {}
        content = message.get("content")
        # Раунд 10.20 (БЛОК 7.2a, ADR-1020-7 §2, T-1920): reasoning-черновик
        # reasoning-моделей. Первое непустое из алиасов reasoning_content →
        # reasoning → thinking. В content НЕ помешивается (черновик не уходит
        # пользователю — сюда попадает только для деградации/телеметрии).
        reasoning_text = None
        for alias in ("reasoning_content", "reasoning", "thinking"):
            raw_reasoning = message.get(alias)
            if isinstance(raw_reasoning, str) and raw_reasoning.strip():
                reasoning_text = raw_reasoning
                break
        tool_calls = None
        raw_calls = message.get("tool_calls")
        if raw_calls:
            parsed = []
            for call in raw_calls:
                try:
                    function = call.get("function") or {}
                    name = str(function.get("name", "") or "").strip()
                    if not name:
                        logger.warning(
                            "LLM generate_chat: malformed tool_call skipped | model=%s",
                            self._chat_model)
                        continue
                    parsed.append(LLMToolCall(
                        id=str(call.get("id", "")),
                        name=name,
                        arguments=str(function.get("arguments", "") or ""),
                    ))
                except (KeyError, TypeError, AttributeError):
                    logger.warning(
                        "LLM generate_chat: malformed tool_call skipped | model=%s",
                        self._chat_model)
            if parsed:
                tool_calls = parsed
        if content is None and not tool_calls and not reasoning_text:
            raise LLMBadResponseError("chat/completions: empty content (no tool_calls)")
        logger.info(
            "LLM generate_chat OK | model=%s | out_chars=%s | tool_calls=%d",
            self._chat_model,
            len(str(content)) if content is not None else "-",
            len(tool_calls) if tool_calls else 0,
        )
        if reasoning_text and not tool_calls and not (
                isinstance(content, str) and content.strip()):
            # Reasoning-only ответ: штатной деградации (молчание/🗿) — без
            # нештатного LLMBadResponseError. Содержимое черновика не логируем.
            logger.warning(
                "LLM generate_chat reasoning-only | model=%s | reasoning_chars=%d",
                self._chat_model, len(reasoning_text))
        content_text = content if (isinstance(content, str) and content.strip()) else None
        await self._record_global_usage(chat_id, content_text, source=source)
        usage = data.get("usage") if isinstance(data, dict) else None
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
        if not texts:
            return []
        try:
            response = await self._post(
                "/embeddings",
                {"model": self._embed_model, "input": texts},
                api_key=self._current_embed_api_key(),
                base_url=self._embed_base_url,
                channel="embed",
            )
        except LLMError as exc:
            if not self._embed_fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            fb_response = None
            fb_idx = 0
            for idx, key in enumerate(self._embed_fallback_api_keys):
                logger.warning(
                    "LLM embed fallback attempt | key_idx=%d | primary_error=%s",
                    idx, f"{type(exc).__name__}: {exc}",
                )
                fb_response = await self._embed_fallback_with_retries(
                    {"input": texts}, api_key=key)
                if fb_response is not None:
                    fb_idx = idx
                    break
                logger.warning("LLM embed fallback key %d failed", idx)
            if fb_response is None:
                # Задача 2: человекочитаемая причина + рекомендация (консоль)
                logger.warning(
                    "LLM embed fallback exhausted | keys=%d | reason=%s",
                    len(self._embed_fallback_api_keys),
                    humanize_embed_error(exc))
                raise exc from None
            response = fb_response
            logger.warning("LLM embed fallback OK | model=%s | key_idx=%d",
                           self._embed_fallback_model, fb_idx)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("embeddings: invalid JSON response") from exc
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise LLMBadResponseError("embeddings: no data[].embedding in response") from exc
        logger.info(
            "LLM embed OK | model=%s | texts=%d", self._embed_model, len(vectors)
        )
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
        # R17: сам ключ не логируется НИКОГДА — алиас credential'а пишет
        # контрол-плейн на своём уровне (spec §0.3/§63).
        logger.info(
            "LLM embed_once OK | model=%s | texts=%d",
            used_model, len(vectors),
        )
        return vectors
