"""Раунд 10.23 (F5, ADR-1023-5) — генерация изображений для прямого чата.

Провайдер по умолчанию — Pollinations.ai (`IMG_BASE_URL`, модель `flux`).
Интеграция (веб-ресёрч, spec §0.1/ADR §References):

* **POST-режим** (default): ``POST {base}/images/generations`` с
  ``Authorization: Bearer <key>``, JSON ``{prompt, model, n:1}`` — строго по
  стандарту OpenAI-совместимого image API. Поля ``size``/``quality``/
  ``response_format`` НЕ отправляются (раунд 10.24, F12/ADR-1024-4 D1): часть
  моделей/провайдеров отвергает их (HTTP 400) — payload обязан быть
  универсальным. Ответ принимается в обеих формах: ``data[0].url``
  (скачиваем) и ``data[0].b64_json`` (декодируем). Kill-switch
  ``SUMMARY_COVER_MODEL_COMPAT_ENABLED=False`` возвращает прежнее тело
  (``size``/``response_format:"url"``) для отката.
* **GET-режим**: ``GET {host}/image/{quote(prompt)}?model=&width=1024&
  height=1024&seed=<random>``; ключ — ``?key=<key>``, ЕСЛИ задан.

Изображение скачивается СЕРВЕРОМ в байты и отправляется ``sendPhoto`` из
памяти — keyed-URL никогда не уходит в Telegram/логи (R17).

Секрет (R17/R18): ключ только ``.env``/PG, резолв ``hot → settings``;
в логи попадают лишь статус/класс ошибки/латентность/размер.

Бюджет (ADR-1023-5 §D4): платный вызов проходит через
``worker_budget.consume(metric="image_calls")``; исчерпание/запрет →
деградация без сетевого вызова; PG down → fail-open.

Публичный контракт для F6 (обложки): ``generate_image(prompt, *,
chat_id=None) -> str | None`` — путь к локальному файлу (fail-open).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

import httpx

from config.settings import settings
from services import hot_config as hot
from services.external_log import log_external_api, safe_text

logger = logging.getLogger(__name__)

# Defense-in-depth (review iter1, Finding 1): httpx на INFO печатает полный
# URL запроса. GET-режим анонимный, но даже гипотетический keyed-URL не должен
# попадать в консоль/journald — глушим INFO httpx до WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Имена каталоговых ключей (pg_key).
KEY_BASE_URL = "models.image_base_url"
KEY_MODEL = "models.image_model"
KEY_GET_MODE = "models.image_get_mode"
KEY_API_KEY = "keys.image_api_key"
KEY_MODULE_ENABLED = "flags.image_generation_module_enabled"

# Имя инструмента Tool Calling (9-й, канон R9: добавляется в конец).
TOOL_NAME = "generate_image"

# Размер — ТОЛЬКО для kill-switch OFF (прежнее тело POST) и GET-эндпоинта;
# в универсальном POST-теле (default ON) НЕ отправляется (ADR-1024-4 D1).
_IMAGE_SIZE = "1024x1024"
_IMAGE_WIDTH = 1024
_IMAGE_HEIGHT = 1024

# Тестовый промпт диагностики подключения (ADR-1024-4 D3). Нейтральный,
# без пользовательских данных (R17).
PROBE_PROMPT = "a simple red circle on a white background"

# Ретрай только для перегрузки/лимита: ≤1 попытка (ADR §D1).
_RETRY_STATUSES = frozenset({429, 503})
_RETRY_MAX = 1
_RETRY_AFTER_CAP_SECONDS = 15.0
_RETRY_AFTER_DEFAULT_SECONDS = 1.0

# Саркастичная заглушка (код-константа; Δ каталога = 0). Показывается на
# пре-гейт-пути, когда изображение сгенерировать/отправить не удалось.
IMAGE_GENERATION_FALLBACK_PHRASE = (
    "Рисовать я, конечно, не умею — руки из кода растут. "
    "Так что довольствуйся тем, что есть, и попробуй ещё раз попозже.")

# Пре-гейт ключевиков (spec §2.2): сообщение НАЧИНАЕТСЯ с «бот|bot» и сразу
# содержит явную просьбу нарисовать/создать/сгенерировать. `tool_choice` при
# этом НЕ форсируется (канон R9/backlog §16 п.2).
IMAGE_KEYWORD_RE = re.compile(
    r"^\s*(?:бот|bot)\b[\s,:\-—]*"
    r"(?:"
    r"нарисуй\b"
    r"|сгенерируй\b"
    r"|создай\s+(?:изображение|картинку|мем|арт)\b"
    r")",
    re.IGNORECASE,
)

# Снятие служебной обёртки «Бот, нарисуй …» → чистый промпт для провайдера.
_IMAGE_PROMPT_STRIP_RE = re.compile(
    r"^\s*(?:бот|bot)\b[\s,:\-—]*"
    r"(?:нарисуй|сгенерируй|создай)\s+"
    r"(?:(?:изображение|картинку|мем|арт)\s+)?",
    re.IGNORECASE,
)


class ImageGenerationError(Exception):
    """Внутренняя ошибка провайдера (reason — R17-safe код, без URL/ключа)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = str(reason or "error")


@dataclass
class GenerationResult:
    """Результат генерации. ``reason`` — код, безопасный для логов (R17)."""

    ok: bool
    reason: str = ""
    content: bytes | None = None
    filename: str = "image.jpg"


@dataclass
class ProbeResult:
    """Результат диагностики подключения провайдера (ADR-1024-4 D3).

    ``reason`` — R17-safe код; ``body_excerpt`` — сырой текст ответа
    провайдера, прогнанный через ``external_log.safe_text`` (усечён, без
    секретов: ключ никогда не возвращается)."""

    ok: bool
    status_code: int | None
    reason: str
    body_excerpt: str
    latency_ms: int
    model: str
    mode: str

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "reason": self.reason,
            "body_excerpt": self.body_excerpt,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "mode": self.mode,
        }


def is_image_keyword(query: str) -> bool:
    """True — сообщение начинается с ключевика генерации изображения."""
    return bool(IMAGE_KEYWORD_RE.match(str(query or "")))


def extract_prompt(query: str) -> str:
    """Промпт из сообщения: снимаем «Бот, нарисуй …» (пусто → исходное)."""
    text = str(query or "").strip()
    stripped = _IMAGE_PROMPT_STRIP_RE.sub("", text).strip()
    return stripped or text


async def resolve_module_enabled(chat_id: int | None = None) -> bool:
    """Флаг модуля: env-рубильник AND каталоговый тумблер (per-chat).

    Прецедент `resolve_lore_compiler_flag` (tool_router): override → hot →
    code-канон; ошибка резолва → глобальный слой (fail-open)."""
    if not bool(getattr(settings, "IMAGE_GENERATION_ENABLED", True)):
        return False
    base = hot.get(KEY_MODULE_ENABLED, settings.IMAGE_GENERATION_MODULE_ENABLED)
    if chat_id is None:
        return bool(base)
    try:
        from services.chat_params import get_chat_param
        value = await get_chat_param(chat_id, KEY_MODULE_ENABLED, base)
        return bool(value)
    except Exception:
        logger.warning("[image] module flag resolve failed — global | chat=%s",
                       chat_id)
        return bool(base)


def _resolve_str(key: str, default: str) -> str:
    try:
        value = hot.get(key, default)
    except Exception:
        value = default
    return str(value if value not in (None, "") else default)


def _resolve_bool(key: str, default: bool) -> bool:
    try:
        value = hot.get(key, default)
    except Exception:
        value = default
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _model_compat_enabled() -> bool:
    """Универсальный payload (default ON); OFF → прежнее тело (откат)."""
    try:
        return bool(getattr(settings, "SUMMARY_COVER_MODEL_COMPAT_ENABLED", True))
    except Exception:  # pragma: no cover — конфиг не должен ронять генерацию
        return True


def _build_post_body(prompt: str, model: str) -> dict:
    """Тело POST строго по стандарту OpenAI-совместимого image API.

    Default: ``{prompt, model, n:1}`` — никаких ``size``/``quality``/
    ``response_format`` (часть моделей их отвергает — ADR-1024-4 D1).
    Kill-switch OFF → байт-в-байт прежнее тело (для отката)."""
    body: dict = {"prompt": prompt, "model": model, "n": 1}
    if not _model_compat_enabled():
        body["size"] = _IMAGE_SIZE
        body["response_format"] = "url"
    return body


def _first_image_item(data) -> dict:
    """Первый элемент ``data[]`` ответа image API ({} при любой форме)."""
    if isinstance(data, dict):
        data_list = data.get("data") or []
        if isinstance(data_list, list) and data_list:
            first = data_list[0]
            if isinstance(first, dict):
                return first
    return {}


def _host_from_base(base_url: str) -> str:
    """Хост из base-URL (для GET-эндпоинта `/{...}` без `/v1`)."""
    parts = urlsplit(str(base_url or "").strip())
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return str(base_url or "").rstrip("/").removesuffix("/v1")


def _reason_from_status(status: int) -> str:
    """Код ошибки HTTP → R17-safe reason (без тела ответа/URL)."""
    return {
        400: "bad_request",
        401: "unauthorized",
        402: "payment_required",
        403: "forbidden",
        429: "rate_limited",
        502: "bad_gateway",
        503: "unavailable",
    }.get(int(status), f"http_{int(status)}")


def _provider_from_url(url: str) -> str:
    """Ярлык провайдера для лога — host без схемы (R17-safe).

    Понимает и scheme-less вход (`image.pollinations.ai`), т.к. GET-режим
    получает host без схемы (R1024F2-05)."""
    raw = str(url or "").strip()
    if not raw:
        return "image"
    try:
        host = urlsplit(raw).hostname
        if not host:
            host = urlsplit("//" + raw.lstrip("/")).hostname
    except Exception:  # pragma: no cover — defensive
        host = None
    return host or "image"


def _endpoint_for_log(base_url: str, get_mode: bool) -> str:
    """R17-safe эндпоинт провайдера для лога (без промпта/query)."""
    if get_mode:
        return f"{_host_from_base(base_url)}/image"
    return f"{str(base_url or '').rstrip('/')}/images/generations"


async def _http_request(method: str, url: str, *,
                        json_body: dict | None = None,
                        headers: dict | None = None,
                        timeout: float = 90.0):
    """Тонкая обёртка httpx (единая точка мока в тестах)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, json=json_body,
                                    headers=headers or {})


def _retry_delay(resp) -> float:
    """Задержка перед bounded-ретраем из `Retry-After` (кап/дефолт)."""
    raw = None
    try:
        raw = (resp.headers or {}).get("Retry-After")
    except Exception:
        raw = None
    try:
        seconds = float(str(raw).strip()) if raw not in (None, "") else \
            _RETRY_AFTER_DEFAULT_SECONDS
    except (TypeError, ValueError):
        seconds = _RETRY_AFTER_DEFAULT_SECONDS
    return max(0.0, min(seconds, _RETRY_AFTER_CAP_SECONDS))


async def _request_with_retry(method: str, url: str, *,
                              json_body: dict | None = None,
                              headers: dict | None = None,
                              timeout: float = 90.0,
                              log_url: str | None = None):
    """Запрос с ≤1 ретраем на 429/503 (учёт `Retry-After`).

    ``log_url`` — R17-safe URL для лога. GET-режим кодирует пользовательский
    промпт прямо в path (`/image/{quote(prompt)}`), поэтому сырой ``url``
    логировать нельзя (R1024F2-01): caller передаёт безопасный эндпоинт без
    промпта. None → ``url`` (POST/download — путь промпта не содержит)."""
    resp = await _http_request(method, url, json_body=json_body,
                               headers=headers, timeout=timeout)
    attempt = 0
    while (getattr(resp, "status_code", 0) in _RETRY_STATUSES
           and attempt < _RETRY_MAX):
        delay = _retry_delay(resp)
        safe_url = log_url or url
        log_external_api(
            logger, provider=_provider_from_url(safe_url), method=method,
            url=safe_url, status=getattr(resp, "status_code", None),
            reason="retry", body=getattr(resp, "text", ""),
            attempt=attempt + 1, level=logging.WARNING)
        if delay > 0:
            await asyncio.sleep(delay)
        attempt += 1
        resp = await _http_request(method, url, json_body=json_body,
                                   headers=headers, timeout=timeout)
    return resp


async def _consume_budget(chat_id: int | None) -> bool:
    """Платный вызов в budget: `image_calls` (per-chat, реюз лимита)."""
    try:
        from services import worker_budget
        scope = f"chat:{chat_id}" if chat_id is not None else "global"
        return await worker_budget.consume(
            None, scope=scope, metric=worker_budget.METRIC_IMAGE_CALLS,
            amount=1)
    except Exception:
        logger.warning("[image] budget consume failed — fail-open")
        return True


async def _generate_post(base_url: str, model: str, prompt: str, key: str,
                         timeout: float, max_bytes: int) -> bytes:
    """POST-режим: универсальное тело → байты (url скачиваем / b64 декодируем).

    Раунд 10.24 (F12/ADR-1024-4 D1): тело строго ``{prompt, model, n:1}``;
    ``size``/``response_format`` убраны (их отвергает часть моделей, напр.
    community/`gptimage`). Обе формы ответа — `data[0].url` и
    `data[0].b64_json` — равноправны."""
    url = f"{str(base_url).rstrip('/')}/images/generations"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = _build_post_body(prompt, model)
    resp = await _request_with_retry("POST", url, json_body=body,
                                     headers=headers, timeout=timeout)
    status = int(getattr(resp, "status_code", 0))
    if status != 200:
        log_external_api(
            logger, provider=_provider_from_url(url), method="POST", url=url,
            status=status, reason=_reason_from_status(status),
            body=getattr(resp, "text", ""), level=logging.ERROR)
        raise ImageGenerationError(_reason_from_status(status))
    try:
        data = resp.json()
    except Exception:
        log_external_api(
            logger, provider=_provider_from_url(url), method="POST", url=url,
            status=status, reason="bad_json",
            body=getattr(resp, "text", ""), level=logging.ERROR)
        raise ImageGenerationError("bad_json")
    item = _first_image_item(data)
    b64 = item.get("b64_json")
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception:
            raise ImageGenerationError("bad_b64")
    image_url = item.get("url")
    if not image_url:
        log_external_api(
            logger, provider=_provider_from_url(url), method="POST", url=url,
            status=status, reason="no_url", body=getattr(resp, "text", ""),
            level=logging.ERROR)
        raise ImageGenerationError("no_url")
    return await _download_bytes(str(image_url), timeout, max_bytes)


async def _download_bytes(image_url: str, timeout: float,
                          max_bytes: int) -> bytes:
    """Скачать байты изображения (без авторизации — внешний URL)."""
    # R17: URL ресурса выдан провайдером (может содержать подписанный токен в
    # path) — в лог/ретрай уходит только host, без path/query.
    safe_url = _provider_from_url(image_url)
    resp = await _request_with_retry("GET", image_url, timeout=timeout,
                                     log_url=safe_url)
    status = int(getattr(resp, "status_code", 0))
    if status != 200:
        log_external_api(
            logger, provider=_provider_from_url(image_url), method="GET",
            url=safe_url, status=status,
            reason=f"download_{_reason_from_status(status)}",
            body=getattr(resp, "text", ""), level=logging.ERROR)
        raise ImageGenerationError(f"download_{_reason_from_status(status)}")
    content = bytes(getattr(resp, "content", b"") or b"")
    if not content:
        raise ImageGenerationError("empty")
    if len(content) > max_bytes:
        raise ImageGenerationError("too_large")
    return content


async def _generate_get(host: str, model: str, prompt: str,
                        timeout: float, max_bytes: int) -> bytes:
    """GET-режим: `/image/{prompt}` — СТРОГО АНОНИМНЫЙ.

    Ключ доступа в query НЕ добавляется сознательно (review iter1, Finding 1):
    httpx логирует полный URL на INFO, а консольный/journald-обработчик не
    гарантирует маскировку — `?key=` утёк бы в журнал. Это ровно семантика UI:
    «в GET-режиме поле ключа блокируется». Провайдер для GET работает по
    серверному лимиту без авторизации."""
    params = {
        "model": model,
        "width": _IMAGE_WIDTH,
        "height": _IMAGE_HEIGHT,
        "seed": random.randint(0, 2147483647),
    }
    url = f"{host}/image/{quote(prompt, safe='')}?{urlencode(params)}"
    # R17: в path GET-URL зашит пользовательский промпт → и в ретрае
    # (`_request_with_retry`), и в ошибке логируем только эндпоинт без промпта.
    safe_url = f"{host}/image"
    resp = await _request_with_retry("GET", url, timeout=timeout,
                                     log_url=safe_url)
    status = int(getattr(resp, "status_code", 0))
    if status != 200:
        log_external_api(
            logger, provider=_provider_from_url(safe_url), method="GET",
            url=safe_url, status=status,
            reason=_reason_from_status(status),
            body=getattr(resp, "text", ""), level=logging.ERROR)
        raise ImageGenerationError(_reason_from_status(status))
    content = bytes(getattr(resp, "content", b"") or b"")
    if not content:
        raise ImageGenerationError("empty")
    if len(content) > max_bytes:
        raise ImageGenerationError("too_large")
    return content


async def _probe_post(base_url: str, model: str, prompt: str, key: str,
                      timeout: float) -> tuple[int | None, str, str]:
    """Тестовый POST тем же универсальным телом; байты НЕ скачиваются.

    Возвращает (status, reason, body_excerpt). ``body_excerpt`` — уже
    R17-safe (``safe_text``). Исключения наружу (их маппит ``probe``)."""
    url = f"{str(base_url).rstrip('/')}/images/generations"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = await _request_with_retry(
        "POST", url, json_body=_build_post_body(prompt, model),
        headers=headers, timeout=timeout)
    status = int(getattr(resp, "status_code", 0))
    text = safe_text(getattr(resp, "text", ""))
    if status != 200:
        return status, _reason_from_status(status), text
    try:
        data = resp.json()
    except Exception:
        return status, "bad_json", text
    item = _first_image_item(data)
    if item.get("url") or item.get("b64_json"):
        return status, "ok", ""
    return status, "no_image", text


async def _probe_get(host: str, model: str, prompt: str,
                     timeout: float) -> tuple[int | None, str, str]:
    """Тестовый GET (анонимный) — проверка без скачивания вложения."""
    params = {
        "model": model,
        "width": _IMAGE_WIDTH,
        "height": _IMAGE_HEIGHT,
        "seed": random.randint(0, 2147483647),
    }
    url = f"{host}/image/{quote(prompt, safe='')}?{urlencode(params)}"
    safe_url = f"{host}/image"
    resp = await _request_with_retry("GET", url, timeout=timeout,
                                     log_url=safe_url)
    status = int(getattr(resp, "status_code", 0))
    if status != 200:
        return (status, _reason_from_status(status),
                safe_text(getattr(resp, "text", "")))
    if not bytes(getattr(resp, "content", b"") or b""):
        return status, "empty", ""
    return status, "ok", ""


async def probe(*, chat_id: int | None = None,
                prompt: str | None = None) -> ProbeResult:
    """Диагностика подключения провайдера (ADR-1024-4 D3).

    Идёт тем же универсальным путём, что генерация, но **не** отправляет в
    Telegram и **не** расходует per-chat бюджет. Возвращает ``ProbeResult``;
    ``body_excerpt`` — сырой текст ошибки провайдера, обезвреженный
    ``external_log.safe_text`` (R17: ключ никогда не возвращается)."""
    text = str(prompt or "").strip() or PROBE_PROMPT
    base_url = _resolve_str(KEY_BASE_URL, settings.IMAGE_BASE_URL)
    model = _resolve_str(KEY_MODEL, settings.IMAGE_MODEL)
    get_mode = _resolve_bool(KEY_GET_MODE, settings.IMAGE_GET_MODE)
    key = _resolve_str(KEY_API_KEY, getattr(settings, "IMAGE_API_KEY", "") or "")
    timeout = float(getattr(settings, "IMAGE_REQUEST_TIMEOUT_SECONDS", 90.0))
    mode = "get" if get_mode else "post"
    started = time.monotonic()
    try:
        if get_mode:
            status, reason, body = await _probe_get(
                _host_from_base(base_url), model, text, timeout)
        else:
            status, reason, body = await _probe_post(
                base_url, model, text, key, timeout)
    except httpx.TimeoutException:
        status, reason, body = None, "timeout", ""
    except httpx.HTTPError as exc:
        status, reason, body = None, "unreachable", safe_text(str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        status, reason, body = None, "unreachable", safe_text(str(exc))
    latency_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "[image] probe | mode=%s | model=%s | status=%s | reason=%s | "
        "latency_ms=%d", mode, model, status, reason, latency_ms)
    # F2/ADR-1024-1: реальная причина видна в логе (тихий откат ≠ тишина).
    log_external_api(
        logger, provider=_provider_from_url(base_url),
        method="GET" if get_mode else "POST",
        url=_endpoint_for_log(base_url, get_mode),
        status=status, reason=reason, body=body, duration_ms=latency_ms,
        level=logging.INFO if reason == "ok" else logging.ERROR)
    return ProbeResult(ok=reason == "ok", status_code=status, reason=reason,
                       body_excerpt=body, latency_ms=latency_ms, model=model,
                       mode=mode)


def _pg():
    """PgDatabase из runtime-кэша (для аналитики F7); None при его нет."""
    cache = hot.get_config_cache()
    if cache is None:
        return None
    return getattr(cache, "pg", None)


async def _record_image_event(correlation_id: str | None) -> None:
    """F7 (ADR-1023-7 D4): телеметрия `step='image'` (fail-open, R17).

    Изображение токенов LLM не тратит, поэтому `input/output=0`, `cost=0`;
    событие нужно для полноты дерева вызовов (`source='image'`)."""
    try:
        from services import usage_events
        await usage_events.record(
            _pg(), module="image", step="image", tool_name="generate_image",
            source="image", correlation_id=correlation_id,
            input_tokens=0, output_tokens=0)
    except Exception:
        logger.warning("[image] analytics record failed — fail-open")


async def generate(prompt: str, *, chat_id: int | None = None,
                   correlation_id: str | None = None) -> GenerationResult:
    """Платный вызов провайдера → байты изображения (fail-open контракт)."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return GenerationResult(ok=False, reason="empty_prompt")
    if not await _consume_budget(chat_id):
        return GenerationResult(ok=False, reason="budget")
    base_url = _resolve_str(KEY_BASE_URL, settings.IMAGE_BASE_URL)
    model = _resolve_str(KEY_MODEL, settings.IMAGE_MODEL)
    get_mode = _resolve_bool(KEY_GET_MODE, settings.IMAGE_GET_MODE)
    key = _resolve_str(KEY_API_KEY, getattr(settings, "IMAGE_API_KEY", "") or "")
    timeout = float(getattr(settings, "IMAGE_REQUEST_TIMEOUT_SECONDS", 90.0))
    max_bytes = int(getattr(settings, "IMAGE_MAX_BYTES", 9 * 1024 * 1024))
    started = time.monotonic()
    try:
        if get_mode:
            content = await _generate_get(_host_from_base(base_url), model,
                                          prompt, timeout, max_bytes)
        else:
            content = await _generate_post(base_url, model, prompt, key,
                                           timeout, max_bytes)
    except ImageGenerationError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "[image] generation failed | mode=%s | model=%s | reason=%s | "
            "latency_ms=%d", "get" if get_mode else "post", model, exc.reason,
            elapsed_ms)
        # F2/ADR-1024-1: «тихий откат» для юзера ≠ тишина в логах.
        log_external_api(
            logger, provider=_provider_from_url(base_url),
            method="GET" if get_mode else "POST",
            url=_endpoint_for_log(base_url, get_mode),
            status=None, reason=exc.reason, duration_ms=elapsed_ms,
            level=logging.ERROR)
        return GenerationResult(ok=False, reason=exc.reason)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "[image] generation error | mode=%s | model=%s | error=%s | "
            "latency_ms=%d", "get" if get_mode else "post", model,
            type(exc).__name__, elapsed_ms)
        log_external_api(
            logger, provider=_provider_from_url(base_url),
            method="GET" if get_mode else "POST",
            status=None, reason=type(exc).__name__, duration_ms=elapsed_ms,
            level=logging.ERROR)
        return GenerationResult(ok=False, reason="error")
    if len(content) > max_bytes:
        return GenerationResult(ok=False, reason="too_large")
    logger.info(
        "[image] generated | mode=%s | model=%s | bytes=%d | latency_ms=%d",
        "get" if get_mode else "post", model, len(content),
        int((time.monotonic() - started) * 1000))
    await _record_image_event(correlation_id)
    return GenerationResult(ok=True, content=content)


async def generate_image_verbose(prompt: str, *, chat_id: int | None = None,
                                 correlation_id: str | None = None
                                 ) -> tuple[str | None, str]:
    """Как ``generate_image``, но возвращает ``(путь|None, reason)``.

    F12/ADR-1024-4 D4: причина отказа видна вызывающему — обложка саммари
    пишет её в F2-лог вместо безликого «image unavailable». Fail-open."""
    result = await generate(prompt, chat_id=chat_id,
                            correlation_id=correlation_id)
    if not result.ok or not result.content:
        return None, result.reason or "error"
    try:
        fd, path = tempfile.mkstemp(prefix="genimg_", suffix=".jpg")
        with os.fdopen(fd, "wb") as handle:
            handle.write(result.content)
        return path, "ok"
    except Exception:
        logger.warning("[image] temp file write failed — fail-open")
        return None, "temp_write_failed"


async def generate_image(prompt: str, *, chat_id: int | None = None,
                         correlation_id: str | None = None) -> str | None:
    """F6-контракт (сохранить): изображение → путь к локальному файлу.

    Fail-open: любая ошибка/пустой результат → ``None``. Вызывающий владеет
    файлом и удаляет его сам (tmp, ``delete=False``)."""
    path, _reason = await generate_image_verbose(
        prompt, chat_id=chat_id, correlation_id=correlation_id)
    return path


async def generate_and_send(bot, chat_id: int, prompt: str, *,
                            reply_to_message_id=None,
                            correlation_id: str | None = None
                            ) -> GenerationResult:
    """Сгенерировать и отправить изображение в чат (байты из памяти).

    R17: keyed-URL провайдера не покидает сервер; в Telegram уходит
    ``BufferedInputFile`` без подписи."""
    result = await generate(prompt, chat_id=chat_id,
                            correlation_id=correlation_id)
    if not result.ok:
        return result
    if bot is None:
        return GenerationResult(ok=False, reason="no_bot")
    from aiogram.types import BufferedInputFile
    from services import telegram_send
    photo = BufferedInputFile(result.content, filename=result.filename)
    try:
        if reply_to_message_id:
            await telegram_send.send_photo(
                bot, chat_id, photo, reply_to_message_id=reply_to_message_id)
        else:
            await telegram_send.send_photo(bot, chat_id, photo)
    except Exception as exc:
        logger.warning("[image] send failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return GenerationResult(ok=False, reason="send_failed")
    logger.info("[image] sent | chat=%s | bytes=%d", chat_id,
                len(result.content or b""))
    return result


async def maybe_handle_keyword(ctx, query: str) -> str:
    """Пре-гейт ключевиков (spec §2.2): генерация+отправка ДО Stage-1.

    Возвращает блок ``<image_result status="ok|error">…</image_result>`` для
    инъекции в user-content, либо ``""`` (нет ключевика/нет бота). НЕ бросает
    и НЕ форсирует ``tool_choice``."""
    if not is_image_keyword(query):
        return ""
    bot = getattr(ctx, "bot", None)
    chat_id = getattr(ctx, "chat_id", None)
    if bot is None or chat_id is None:
        return ""
    result = await generate_and_send(
        bot, chat_id, extract_prompt(query),
        reply_to_message_id=getattr(ctx, "reply_to_message_id", None),
        # F7 rework: пре-гейт встраивается в дерево ответа — тот же сквозной
        # correlation_id, что у Stage-1/Stage-2 (иначе step='image' создаёт
        # новую одиночную ноду в дашборде).
        correlation_id=getattr(ctx, "correlation_id", None))
    if result.ok:
        return ('<image_result status="ok">\n'
                "Изображение уже сгенерировано и отправлено в чат. "
                "Повторно инструмент generate_image не вызывай.\n"
                "</image_result>")
    return (f'<image_result status="error">\n'
            f"{IMAGE_GENERATION_FALLBACK_PHRASE}\n"
            "</image_result>")
