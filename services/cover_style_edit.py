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
    """Собрать тело нормализованного edit-запроса (data URL references)."""
    refs = [_data_url(p) for p in image_paths]
    refs = [r for r in refs if r]
    if max_input_images is not None and max_input_images > 0:
        refs = refs[:int(max_input_images)]
    return {
        "prompt": str(prompt or ""),
        "model": str(model or ""),
        "n": 1,
        "input_references": refs,
    }


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
                     operation: str = "edit",
                     transport=None, downloader=None) -> EditResult:
    """Capability-gated Style Edit (§3.2/§38/§41).

    `operation` — stage-aware key политики (T-4197/§23: ``edit`` ≠
    ``preview`` — разные latency-распределения). `transport`/`downloader` —
    инъекция для тестов (по умолчанию реальный httpx). Возвращает
    `EditResult`; исключений не бросает.
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
    payload = build_edit_payload(prompt, model=model, image_paths=images,
                                 max_input_images=max_inputs)
    if not payload["input_references"]:
        return EditResult(ok=False, reason="no_input_images", model=model,
                          provider=_provider(base_url))
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
            resp = await post(_endpoint(base_url), payload,
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
                        provider=provider,
                        latency_ms=_ms(attempt_started))
                last_reason = reason or "error"
            elif status in (429, 502, 503, 504):
                last_reason = f"http_{status}"
            elif status == 401:
                last_reason = "unauthorized"
            elif status == 400:
                # §58: API validation error → capability mismatch (в логах).
                last_reason = "bad_request"
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
                      provider=provider, latency_ms=_ms(started))


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
