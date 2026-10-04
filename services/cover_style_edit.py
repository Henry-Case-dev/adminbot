"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D4; spec §3.2/§3.7/
§39–§41/§53) — capability-gated image **edit** (Style stage).

Style Edit — не overlay, а нормализатор (§23); сетевой вызов идёт **только**
если модель умеет `image_edit` (gate §38 реализован в
`services.cover_style_pipeline.check_edit_allowed` — до вызова этого модуля).

Маршрут — нормализованный `POST {base_url}/images` с `input_references`
(data URL, §2.3: «URL/data-url/typed»; нельзя смешивать с legacy-алиасами).
Байты картинок НЕ логируются и не попадают в R17-поля.

Async (§40): включается ТОЛЬКО если capability сообщает `async_jobs` И заданы
endpoint-шаблоны (`COVER_STYLE_ASYNC_SUBMIT_URL`/`_STATUS_URL`) — provider
contract без подтверждения не хардкодится. Иначе — синхронный путь §41 с
отдельным окном (НЕ общий text-LLM timeout, §69).

Ошибки fail-open: сетевые/серверные → `EditResult(ok=False, reason=…)`;
исключение наружу не уходит (как у `image_generation.generate`).
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from config.settings import settings
from services import image_capabilities as cap
from services.image_generation import is_transient_reason, reason_class

logger = logging.getLogger(__name__)

# Нормализованный edit-маршрут (spec §2.3). `/images/edits` (multipart) —
# альтернатива провайдера; используем JSON-маршрут с `input_references`.
EDIT_ROUTE = "/images"
# ASAP 4.2 Step 2c-1 (T-4812): provider-specific route names (NanoGPT).
IMAGE_API_ROUTE = "/images"
IMAGE_EDITS_ROUTE = "/images/edit"
IMAGE_EDITS_ROUTE_ALIAS = "/images/edits"

# Значения resolved route.
ROUTE_IMAGE_API = "image_api"
ROUTE_IMAGE_EDITS = "image_edits"
ROUTE_UNVERIFIED = "unverified"
ROUTE_LEGACY = "legacy_images"

_ROUTE_CACHE: dict = {}
_ROUTE_TTL_SECONDS = 900.0


def provider_routes_enabled() -> bool:
    """Kill-switch `COVER_STYLE_PROVIDER_ROUTES_ENABLED` (T-4812; env-only,
    default ON). OFF → прежний `{base_url}/images` + `input_references`."""
    try:
        return bool(getattr(settings, "COVER_STYLE_PROVIDER_ROUTES_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass
class EditResult:
    """Результат Style Edit-вызова (fail-open контракт)."""

    ok: bool
    content: bytes | None = None
    reason: str = "error"
    model: str = ""
    provider: str = ""
    task_id: str | None = None
    async_used: bool = False
    latency_ms: int = 0
    reused_task: bool = False
    meta: dict = field(default_factory=dict)


def _timeout(operation: str = "edit", base_url: str = "", model: str = ""
             ) -> float:
    """Окно одной попытки edit/preview (§22/§27/§39).

    ASAP-3.2 (T-4197, ADR-1028-5 D5): окно резолвится MediaExecutionPolicy
    (key provider+model+operation; adaptive по успешным наблюдениям, §26);
    `COVER_STYLE_EDIT_TIMEOUT_SECONDS` остаётся migration evidence —
    legacy-путь (policy OFF / ошибка резолва) и нижняя граница cold-дефолта.
    Кламп [30, 900] сохранён (§69)."""
    legacy = 240.0
    try:
        legacy = float(getattr(settings, "COVER_STYLE_EDIT_TIMEOUT_SECONDS",
                               240.0))
    except (TypeError, ValueError):
        legacy = 240.0
    legacy = max(30.0, min(legacy, 900.0))
    try:
        from services.media_execution import (OPERATION_EDIT,
                                              OPERATION_PREVIEW,
                                              media_policy_enabled,
                                              record_media_outcome,
                                              resolve_windows)
        op = OPERATION_PREVIEW if operation == "preview" else OPERATION_EDIT
        if media_policy_enabled():
            provider = _provider(base_url)
            windows = resolve_windows(provider, model, op)
            return max(30.0, min(windows.total_deadline, 900.0))
    except Exception:
        pass
    return legacy


def record_edit_outcome(operation: str, base_url: str, model: str, *,
                        ok: bool, duration_s: float | None = None,
                        timeout: bool = False) -> None:
    """§26: наблюдение исхода edit/preview → estimator политики (успешные
    длительности; timeout/failure — отдельные reliability signals)."""
    try:
        from services.media_execution import (OPERATION_EDIT,
                                              OPERATION_PREVIEW,
                                              record_media_outcome)
        op = OPERATION_PREVIEW if operation == "preview" else OPERATION_EDIT
        record_media_outcome(_provider(base_url), model, op, ok=ok,
                             duration_s=duration_s, timeout=timeout)
    except Exception:
        pass


def max_attempts() -> int:
    """Число попыток edit (env-only, кламп [1, 3]; §41 — повтор дорогой)."""
    try:
        value = int(getattr(settings, "COVER_STYLE_EDIT_MAX_ATTEMPTS", 1))
    except (TypeError, ValueError):
        value = 1
    return max(1, min(value, 3))


def retry_backoff() -> float:
    try:
        value = float(getattr(settings,
                              "COVER_STYLE_EDIT_RETRY_BACKOFF_SECONDS", 5.0))
    except (TypeError, ValueError):
        value = 5.0
    return max(0.0, min(value, 60.0))


def _mime_for(path: str | Path) -> str:
    return _MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "image/png")


def _data_url(path: str | Path) -> str | None:
    """Локальный файл → data URL для `input_references` (§2.3)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return "data:{};base64,{}".format(
        _mime_for(path), base64.b64encode(data).decode("ascii"))


def build_edit_payload(prompt: str, *, model: str, image_paths: list,
                       max_input_images: int | None = None) -> dict:
    """Собрать тело нормализованного edit-запроса (data URL references).

    Image API ветка (T-4812): `input_references` — массив строк data-URL; НЕ
    смешивается с legacy-алиасами (`imageDataUrl(s)`)."""
    refs = _data_urls(image_paths, max_input_images)
    return {
        "prompt": str(prompt or ""),
        "model": str(model or ""),
        "n": 1,
        "input_references": refs,
    }


def _data_urls(image_paths: list, max_input_images: int | None = None) -> list:
    refs = [_data_url(p) for p in image_paths]
    refs = [r for r in refs if r]
    if max_input_images is not None and max_input_images > 0:
        refs = refs[:int(max_input_images)]
    return refs


def build_image_edits_payload(prompt: str, *, model: str, image_paths: list,
                              max_input_images: int | None = None) -> dict:
    """Image Edits (T-4812): OpenAI-совместимый JSON-контракт
    `imageDataUrl` (single) / `imageDataUrls` (array). НЕ смешивается с
    `input_references`."""
    refs = _data_urls(image_paths, max_input_images)
    payload = {"prompt": str(prompt or ""), "model": str(model or ""), "n": 1}
    if len(refs) == 1:
        payload["imageDataUrl"] = refs[0]
    else:
        payload["imageDataUrls"] = refs
    return payload


def build_image_edits_multipart(prompt: str, *, model: str, image_paths: list,
                               max_input_images: int | None = None
                               ) -> tuple[dict, list]:
    """Image Edits multipart (T-4812): `(data, files)` для httpx
    (`image` или `image[]`). Возвращает (fields, files-список
    `[(field, (name, bytes, mime))]`) — байты не логируются."""
    data = {"prompt": str(prompt or ""), "model": str(model or ""), "n": "1"}
    paths = list(image_paths)
    if max_input_images is not None and max_input_images > 0:
        paths = paths[:int(max_input_images)]
    files = []
    for idx, path in enumerate(paths):
        try:
            raw = Path(path).read_bytes()
        except OSError:
            continue
        field = "image" if len(paths) == 1 else "image[]"
        files.append((field, (f"image{idx}", raw, _mime_for(path))))
    return data, files


def _route_cache_key(base_url: str, model: str) -> tuple:
    return (str(base_url or "").rstrip("/").lower(),
            str(model or "").strip().lower())


async def _discover_endpoints_for_route(base_url: str, model: str) -> dict | None:
    """Endpoint metadata модели через provider-адаптер (единственный
    подтверждённый route-discovery; НЕ выдумываем)."""
    try:
        from services.media_execution import detect_adapter
        adapter = detect_adapter(base_url)
        discover = getattr(adapter, "_discover_endpoints", None)
        if discover is None:
            return None
        return await discover(model)
    except Exception:
        return None


def _classify_route_from_endpoints(endpoints: dict | None) -> str:
    """Маршрут по discovered endpoint-metadata (tolerant, без выдумывания).

    Признаки: явный path `/images/edit(s)` → Image Edits; наличие
    `input_reference_constraints`/`input_references` → Image API; иначе
    `unverified` (fail-soft Base Cover)."""
    if not isinstance(endpoints, dict) or not endpoints:
        return ROUTE_UNVERIFIED
    try:
        blob = json_dumps_safe(endpoints).lower()
    except Exception:
        blob = str(endpoints).lower()
    if "/images/edit" in blob or "imagedataurl" in blob or "multipart" in blob:
        return ROUTE_IMAGE_EDITS
    if "input_reference" in blob:
        return ROUTE_IMAGE_API
    # Явные route/endpoint-поля.
    for key in ("route", "endpoint", "path", "url", "method"):
        value = str(endpoints.get(key) or "").lower()
        if "images/edit" in value:
            return ROUTE_IMAGE_EDITS
        if "images" in value and "edit" not in value:
            return ROUTE_IMAGE_API
    return ROUTE_UNVERIFIED


def json_dumps_safe(value) -> str:
    import json as _json
    try:
        return _json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


async def resolve_edit_route(base_url: str, model: str, *,
                             endpoints: dict | None = None) -> str:
    """T-4812: resolved route по discovered endpoint-metadata.

    Только NanoGPT (верифицированный контракт обеих веток); иные провайдеры →
    legacy `{base_url}/images`. Нет подтверждения → `unverified` (fail-soft
    Base Cover). TTL-кеш по base_url+model."""
    if not provider_routes_enabled():
        return ROUTE_LEGACY
    from services.model_capacity import detect_provider_class
    provider_class = detect_provider_class(base_url)
    if provider_class != "nanogpt":
        return ROUTE_LEGACY
    key = _route_cache_key(base_url, model)
    now = time.monotonic()
    cached = _ROUTE_CACHE.get(key)
    if cached is not None and (now - cached[0]) <= _ROUTE_TTL_SECONDS:
        return cached[1]
    if endpoints is None:
        endpoints = await _discover_endpoints_for_route(base_url, model)
    route = _classify_route_from_endpoints(endpoints)
    _ROUTE_CACHE[key] = (now, route)
    return route


def extract_edit_error(resp, *, route: str, model: str) -> dict:
    """T-4813: R17-safe 400-diagnostics (status/reason_code/sanitized
    message/request_id/route/model; БЕЗ keys/prompts/bytes)."""
    try:
        status = int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    body = None
    try:
        body = resp.json()
    except Exception:
        try:
            body = resp.text
        except Exception:
            body = None
    from services.image_capabilities import extract_provider_error
    diag = extract_provider_error(body) if isinstance(body, dict) else {}
    diag.update({"status": status, "route": str(route or ""),
                 "model": str(model or "")[:80]})
    return diag


async def _post_json(url: str, payload: dict, headers: dict,
                     timeout: float) -> httpx.Response:
    """Единая точка сетевого POST (мок в тестах)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(url, json=payload, headers=headers or {})


async def _get_bytes(url: str, timeout: float) -> bytes:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _first_item(data) -> dict:
    try:
        if isinstance(data, dict) and isinstance(data.get("data"), list) \
                and data["data"]:
            item = data["data"][0]
            return item if isinstance(item, dict) else {}
    except Exception:      # pragma: no cover - defensive
        return {}
    return {}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _endpoint(base_url: str) -> str:
    return str(base_url or "").rstrip("/") + EDIT_ROUTE


async def edit_image(prompt: str, *, base_image_path: str | None,
                     reference_paths: list | None, base_url: str, model: str,
                     api_key: str = "", capabilities: cap.ImageModelCapabilities
                     | None = None, chat_id: int | None = None,
                     correlation_id: str | None = None,
                     existing_task_id: str | None = None,
                     operation: str = "edit", endpoints: dict | None = None,
                     route: str | None = None,
                     transport=None, downloader=None) -> EditResult:
    """Capability-gated Style Edit (§3.2/§38/§41).

    `operation` — stage-aware key политики (T-4197/§23: ``edit`` ≠
    ``preview`` — разные latency-распределения). `route`/`endpoints` —
    provider-specific маршрут (T-4812; discovered endpoint-metadata).
    `transport`/`downloader` — инъекция для тестов (по умолчанию реальный
    httpx). Возвращает `EditResult`; исключений не бросает.
    """
    caps = capabilities if capabilities is not None else None
    if caps is not None and caps.image_edit == cap.FALSE:
        return EditResult(ok=False, reason="edit_unsupported", model=model,
                          provider=_provider(base_url))
    if not base_url or not model:
        return EditResult(ok=False, reason="not_configured", model=model,
                          provider=_provider(base_url))
    images: list = []
    if base_image_path:
        images.append(base_image_path)
    images.extend(reference_paths or [])
    max_inputs = caps.max_input_images if (caps and caps.max_input_images) \
        else None
    # ── T-4812: provider-specific route по discovered endpoint-metadata ─────
    resolved_route = route
    if resolved_route is None:
        resolved_route = await resolve_edit_route(base_url, model,
                                                  endpoints=endpoints)
    edit_meta: dict = {"route": resolved_route}
    if resolved_route == ROUTE_UNVERIFIED:
        # Честный fail-soft: Base Cover публикуется, API не вызывается вслепую.
        return EditResult(ok=False, reason="route_unverified", model=model,
                          provider=_provider(base_url), meta=edit_meta)
    if resolved_route == ROUTE_IMAGE_EDITS:
        payload = build_image_edits_payload(prompt, model=model,
                                            image_paths=images,
                                            max_input_images=max_inputs)
        request_endpoint = (str(base_url or "").rstrip("/")
                            + IMAGE_EDITS_ROUTE)
        has_inputs = bool(payload.get("imageDataUrl")
                          or payload.get("imageDataUrls"))
    else:
        payload = build_edit_payload(prompt, model=model, image_paths=images,
                                     max_input_images=max_inputs)
        request_endpoint = _endpoint(base_url)
        has_inputs = bool(payload.get("input_references"))
    if not has_inputs:
        return EditResult(ok=False, reason="no_input_images", model=model,
                          provider=_provider(base_url), meta=edit_meta)
    timeout = _timeout(operation, base_url, model)
    post = transport or _post_json
    getter = downloader or _get_bytes
    provider = _provider(base_url)
    started = time.monotonic()

    # Async-путь (§40): только при capability-подтверждении + endpoint-шаблонах.
    if caps is not None and getattr(caps, "async_jobs", False) \
            and _async_configured():
        return await _edit_async(
            post, getter, prompt, payload, base_url, model, api_key, provider,
            timeout, started, existing_task_id)

    attempts = max_attempts()
    backoff = retry_backoff()
    last_reason = "error"
    for attempt in range(1, attempts + 1):
        attempt_started = time.monotonic()
        try:
            resp = await post(request_endpoint, payload,
                              _headers(api_key), timeout)
        except httpx.TimeoutException:
            last_reason = "timeout"
        except httpx.HTTPError:
            last_reason = "network"
        except Exception:
            last_reason = "error"
        else:
            status = getattr(resp, "status_code", None)
            if status is not None and 200 <= int(status) < 300:
                try:
                    content, reason = _extract(resp)
                    if content is None and reason == "url":
                        content, reason = await _download(getter, resp, timeout)
                except Exception:
                    content, reason = None, "error"
                if content is not None:
                    record_edit_outcome(operation, base_url, model, ok=True,
                                        duration_s=time.monotonic()
                                        - attempt_started)
                    return EditResult(
                        ok=True, content=content, reason="ok", model=model,
                        provider=provider, meta=edit_meta,
                        latency_ms=_ms(attempt_started))
                last_reason = reason or "error"
            elif status in (429, 502, 503, 504):
                last_reason = f"http_{status}"
            elif status == 401:
                last_reason = "unauthorized"
            elif status == 400:
                # T-4813: безопасные diagnostics (status/reason_code/
                # sanitized message/request_id/route/model; без keys/prompt/
                # bytes). T-4814: machine-readable prompt-limit → N.
                # T-4875: «too long» БЕЗ числа → semantic
                # `prompt_limit_unknown` (не generic `bad_request`).
                diag = extract_edit_error(resp, route=resolved_route,
                                          model=model)
                edit_meta["provider_error"] = diag
                safe_text = _safe_resp_text(resp)
                limit = None
                try:
                    limit = cap.extract_prompt_limit(safe_text)
                except Exception:
                    limit = None
                if limit is not None and limit[0] > 0:
                    edit_meta["prompt_limit"] = {"value": int(limit[0]),
                                                 "unit": limit[1]}
                    last_reason = "prompt_limit"
                elif cap.looks_like_prompt_too_long(
                        safe_text, diag.get("reason_code") or ""):
                    edit_meta["prompt_limit_unknown"] = True
                    last_reason = "prompt_limit_unknown"
                else:
                    last_reason = "bad_request"
                logger.warning(
                    "[cover_style_edit] provider 400 | status=%s | route=%s | "
                    "model=%s | reason_code=%s | request_id=%s | classified=%s",
                    diag.get("status"), diag.get("route"), diag.get("model"),
                    (diag.get("reason_code") or "-")[:60],
                    (diag.get("request_id") or "-")[:40], last_reason)
            elif status is not None:
                last_reason = f"http_{status}"
            else:
                last_reason = "error"
        if not is_transient_reason(last_reason):
            break
        if attempt < attempts and backoff > 0:
            import asyncio
            await asyncio.sleep(backoff)
    logger.warning(
        "[cover_style_edit] edit failed | provider=%s | model=%s | "
        "reason_class=%s | reason=%s | latency_ms=%d",
        provider, model, reason_class(last_reason), last_reason,
        _ms(started))
    record_edit_outcome(operation, base_url, model, ok=False,
                        duration_s=time.monotonic() - started,
                        timeout=(last_reason == "timeout"))
    return EditResult(ok=False, reason=last_reason, model=model,
                      provider=provider, meta=edit_meta, latency_ms=_ms(started))


def _safe_resp_text(resp) -> str:
    """R17-safe текст ответа для серверного парсинга лимита (не логируется)."""
    try:
        text = getattr(resp, "text", "")
        if text:
            return str(text)
    except Exception:
        pass
    try:
        return json_dumps_safe(resp.json())
    except Exception:
        return ""


def _extract(resp) -> tuple[bytes | None, str]:
    """Синхронно достать b64 из JSON; url — отложенно (нужен downloader)."""
    if hasattr(resp, "json"):
        try:
            body = resp.json()
        except Exception:
            return None, "bad_json"
    else:      # pragma: no cover - fake в тестах
        body = resp
    item = _first_item(body)
    b64 = item.get("b64_json")
    if b64:
        try:
            return base64.b64decode(b64), "ok"
        except Exception:
            return None, "bad_json"
    if item.get("url"):
        return None, "url"
    return None, "bad_json"


async def _download(getter, resp, timeout: float) -> tuple[bytes | None, str]:
    try:
        body = resp.json()
    except Exception:
        return None, "bad_json"
    url = _first_item(body).get("url")
    if not url:
        return None, "bad_json"
    try:
        return await getter(str(url), timeout), "ok"
    except httpx.TimeoutException:
        return None, "timeout"
    except Exception:
        return None, "network"


def _async_configured() -> bool:
    submit = str(getattr(settings, "COVER_STYLE_ASYNC_SUBMIT_URL", "") or "")
    status = str(getattr(settings, "COVER_STYLE_ASYNC_STATUS_URL", "") or "")
    return bool(submit.strip() and status.strip())


def _async_deadline() -> float:
    try:
        value = float(getattr(settings, "COVER_STYLE_ASYNC_DEADLINE_SECONDS",
                              600.0))
    except (TypeError, ValueError):
        value = 600.0
    return max(30.0, min(value, 3600.0))


def async_poll_interval() -> float:
    try:
        value = float(getattr(settings, "COVER_STYLE_ASYNC_POLL_SECONDS", 5.0))
    except (TypeError, ValueError):
        value = 5.0
    return max(0.5, min(value, 60.0))


async def _edit_async(post, getter, prompt, payload, base_url, model, api_key,
                      provider, timeout, started, existing_task_id
                      ) -> EditResult:
    """Async submit → task_id → poll (§40/§43). Не хардкодит interval без contract."""
    import asyncio
    submit_url = str(getattr(settings, "COVER_STYLE_ASYNC_SUBMIT_URL", ""))
    status_tmpl = str(getattr(settings, "COVER_STYLE_ASYNC_STATUS_URL", ""))
    task_id = existing_task_id
    reused = bool(existing_task_id)
    if not task_id:
        try:
            body = dict(payload)
            body["async"] = True
            resp = await post(submit_url, body, _headers(api_key), timeout)
            if not (200 <= int(getattr(resp, "status_code", 0)) < 300):
                return EditResult(ok=False, reason=_status_reason(resp),
                                  model=model, provider=provider,
                                  latency_ms=_ms(started))
            task_id = str(_first_item(resp.json()).get("task_id")
                          or resp.json().get("task_id") or "")
        except Exception:
            return EditResult(ok=False, reason="network", model=model,
                              provider=provider, latency_ms=_ms(started))
        if not task_id:
            return EditResult(ok=False, reason="bad_json", model=model,
                              provider=provider, latency_ms=_ms(started))
    deadline = time.monotonic() + _async_deadline()
    interval = async_poll_interval()
    while time.monotonic() < deadline:
        await asyncio.sleep(interval)
        try:
            url = status_tmpl.replace("{task_id}", task_id)
            resp = await post(url, {"task_id": task_id}, _headers(api_key),
                              timeout)
            body = resp.json()
        except Exception:
            continue
        status = str(_first_item(body).get("status")
                     or body.get("status") or "").lower()
        if status in ("succeeded", "success", "completed", "done"):
            content, reason = _extract(resp)
            if content is None and reason == "url":
                content, reason = await _download(getter, resp, timeout)
            if content is not None:
                return EditResult(ok=True, content=content, reason="ok",
                                  model=model, provider=provider,
                                  task_id=task_id, async_used=True,
                                  reused_task=reused, latency_ms=_ms(started))
            return EditResult(ok=False, reason=reason or "error", model=model,
                              provider=provider, task_id=task_id,
                              async_used=True, latency_ms=_ms(started))
        if status in ("failed", "error", "cancelled"):
            return EditResult(ok=False, reason=f"provider_{status}",
                              model=model, provider=provider, task_id=task_id,
                              async_used=True, latency_ms=_ms(started))
    return EditResult(ok=False, reason="deadline_exceeded", model=model,
                      provider=provider, task_id=task_id, async_used=True,
                      latency_ms=_ms(started))


def _status_reason(resp) -> str:
    status = getattr(resp, "status_code", None)
    if status == 429:
        return "http_429"
    if status == 401:
        return "unauthorized"
    if status == 400:
        # T-4875: та же семантика, что в sync-пути (без числа → unknown).
        try:
            if cap.looks_like_prompt_too_long(_safe_resp_text(resp)):
                return "prompt_limit_unknown"
        except Exception:
            pass
        return "bad_request"
    return f"http_{status}" if status is not None else "error"


def _provider(base_url: str) -> str:
    raw = str(base_url or "").strip()
    if not raw:
        return "image"
    try:
        from urllib.parse import urlsplit
        return urlsplit(raw).hostname or "image"
    except Exception:      # pragma: no cover
        return "image"


def _ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
