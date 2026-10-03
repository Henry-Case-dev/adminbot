"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D2; spec §3.7/§14–§18,
§37/§38/§53/§71) — Image Model Capability Resolver.

Резолв `provider + base_url + model → ImageModelCapabilities` **без** хардкода
лимитов (`800` НЕ переносится в код, §15/DC-7). Precedence (§16):

  1. explicit developer override (env-JSON/CSV, аварийный escape hatch);
  2. runtime/provider API metadata (`GET /api/v1/image-models?detailed=true`
     + `GET /api/v1/images/models/{model}/endpoints`);
  3. provider-specific model catalog;
  4. verified internal capability registry;
  5. `unknown`/conservative fallback (`image_edit=unknown`, `max_input_images=0`).

Cache по `provider+base_url+model` (TTL + invalidation на смену connection/
model/reload config/explicit refresh, §17/§71). Fail-open: discovery недоступен
→ conservative `unknown`, сохранение профиля не запрещено (§58).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger(__name__)

# Единицы prompt-лимита (§18): chars | tokens | bytes | unknown.
UNIT_CHARS = "chars"
UNIT_TOKENS = "tokens"
UNIT_BYTES = "bytes"
UNIT_UNKNOWN = "unknown"
PROMPT_UNITS = (UNIT_CHARS, UNIT_TOKENS, UNIT_BYTES, UNIT_UNKNOWN)

# Источники значения лимита (§11.2 D3).
SOURCE_OVERRIDE = "developer_override"
SOURCE_DISCOVERY = "provider_or_registry"
SOURCE_INTERNAL = "internal_config"
SOURCE_UNKNOWN = "unknown"
# ASAP 4.2 Step 2c-1 (T-4814): дополнительные уровни precedence.
SOURCE_LIVE_MODEL = "live_model_metadata"
SOURCE_LIVE_ROUTE = "live_route_metadata"
SOURCE_VERIFIED_REGISTRY = "verified_registry"
SOURCE_RUNTIME_DISCOVERED = "cached_runtime_discovered"


def dynamic_prompt_limit_enabled() -> bool:
    """Kill-switch `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED` (ASAP 4.2 Step 2c-1,
    spec §3/R8-J; env-only, default ON). OFF → прежний precedence байт-в-байт."""
    try:
        return bool(getattr(settings, "IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True

# Трёхзначная логика для capability-полей (может быть неизвестно, §3.7).
TRUE = "yes"
FALSE = "no"
UNKNOWN = "unknown"


@dataclass
class PromptLimit:
    """Лимит промпта: значение + единица + источник (§14/§18)."""

    value: int | None = None
    unit: str = UNIT_UNKNOWN
    source: str = SOURCE_UNKNOWN

    def as_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "source": self.source}

    @property
    def known(self) -> bool:
        """T-4814: известен хотя бы числовой лимит; отсутствие единицы
        (`unknown`) не делает лимит недействительным (внутренняя арифметика
        трактует unknown как chars, §3)."""
        try:
            return self.value is not None and int(self.value) > 0
        except (TypeError, ValueError):
            return False


@dataclass
class ImageModelCapabilities:
    """Возможности image-модели (§14). Значения — из источника, не догма."""

    text_to_image: str = UNKNOWN
    image_edit: str = UNKNOWN
    prompt_limit: PromptLimit = field(default_factory=PromptLimit)
    max_input_images: int | None = None
    max_input_bytes: int | None = None
    supported_sizes: list[str] = field(default_factory=list)
    prompt_expansion: str = UNKNOWN
    async_jobs: bool = False
    source: str = SOURCE_UNKNOWN

    def as_dict(self) -> dict:
        return {
            "text_to_image": self.text_to_image,
            "image_edit": self.image_edit,
            "prompt_limit": self.prompt_limit.as_dict(),
            "max_input_images": self.max_input_images,
            "max_input_bytes": self.max_input_bytes,
            "supported_sizes": list(self.supported_sizes),
            "prompt_expansion": self.prompt_expansion,
            "async_jobs": self.async_jobs,
            "source": self.source,
        }

    @property
    def edit_supported(self) -> bool:
        """True — edit точно поддерживается; False/UNKNOWN — нет/неизвестно."""
        return self.image_edit == TRUE

    @property
    def references_available(self) -> int | None:
        """`max_input_images − base cover` = доступно references (§13/§37).

        base cover всегда занимает 1 input; None — если лимит неизвестен.
        """
        if self.max_input_images is None:
            return None
        return max(0, int(self.max_input_images) - 1)


def conservative_unknown() -> ImageModelCapabilities:
    """Conservative fallback (§16 п.5): edit неизвестен, 0 input images."""
    return ImageModelCapabilities(
        text_to_image=UNKNOWN, image_edit=UNKNOWN,
        prompt_limit=PromptLimit(), max_input_images=0,
        max_input_bytes=None, supported_sizes=[], prompt_expansion=UNKNOWN,
        async_jobs=False, source=SOURCE_UNKNOWN)


# ── Machine-readable 400 → prompt-limit extraction (T-4814, spec §3) ────────

_UNIT_WORDS = {
    "char": UNIT_CHARS, "chars": UNIT_CHARS, "character": UNIT_CHARS,
    "characters": UNIT_CHARS, "token": UNIT_TOKENS, "tokens": UNIT_TOKENS,
    "byte": UNIT_BYTES, "bytes": UNIT_BYTES,
}

_PROMPT_LIMIT_PATTERNS = (
    re.compile(r"prompt\s+(?:max|maximum)\s+(?:length\s+is\s+)?(\d+)\s*"
               r"(characters?|chars|tokens?|bytes?)?", re.IGNORECASE),
    re.compile(r"maximum\s+prompt\s+length\s+is\s+(\d+)\s*"
               r"(characters?|chars|tokens?|bytes?)?", re.IGNORECASE),
    re.compile(r"prompt\s+length\s+(?:must\s+be\s+)?(?:<=?|at\s+most|max)"
               r"\s*(\d+)\s*(characters?|chars|tokens?|bytes?)?", re.IGNORECASE),
    re.compile(r"maximum\s+(\d+)\s+(characters?|chars|tokens?|bytes?)",
               re.IGNORECASE),
    re.compile(r"max_prompt_length[\"'\s:=]+(\d+)", re.IGNORECASE),
    re.compile(r"prompt_limit[\"'\s:=]+(\d+)", re.IGNORECASE),
)


def extract_prompt_limit(text) -> tuple[int, str] | None:
    """Извлечь `(value, unit)` из machine-readable provider-ошибки (spec §3).

    Никакого hardcode `800`: значение берётся ТОЛЬКО из явного сообщения
    провайдера. `unit` неизвестен → chars (prompt провайдера — текстовая
    величина). Возвращает None, если N не распознан."""
    raw = str(text or "")
    if not raw:
        return None
    for pattern in _PROMPT_LIMIT_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except (TypeError, ValueError, IndexError):
            continue
        if value <= 0:
            continue
        unit = UNIT_CHARS
        try:
            word = (match.group(2) or "").lower()
        except IndexError:
            word = ""
        unit = _UNIT_WORDS.get(word, UNIT_CHARS)
        return value, unit
    return None


def extract_provider_error(body) -> dict:
    """R17-safe diagnostics из provider error-body (T-4813, spec §2/§29).

    Возвращает ТОЛЬКО `{status, reason_code, message, request_id, route,
    model}`; ключи/промпты/data-URL/reference-bytes НЕ извлекаются. `message`
    санитизируется (truncate, без URL/query)."""
    out: dict = {}
    if isinstance(body, dict):
        err = body.get("error")
        code = ""
        if isinstance(err, str):
            code = err
        elif isinstance(err, dict):
            code = str(err.get("code") or err.get("type") or "")
        if not code:
            code = str(body.get("code") or body.get("type") or "")
        out["reason_code"] = code[:80]
        for key in ("request_id", "requestId", "id"):
            if body.get(key):
                out["request_id"] = str(body.get(key))[:80]
                break
        raw_msg = body.get("message") or body.get("detail")
        if isinstance(err, dict):
            raw_msg = raw_msg or err.get("message")
        if raw_msg:
            out["message"] = _sanitize_error_text(str(raw_msg))[:240]
    return out


def _sanitize_error_text(text: str) -> str:
    """Убрать из сообщения URL/query, data-URL/байты и key-подобные токены
    (R17)."""
    import re as _re
    clean = _re.sub(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+",
                    "<data-url>", text)
    clean = _re.sub(r"https?://[^\s\"']+", "<url>", clean)
    clean = _re.sub(r"Bearer\s+\S+", "Bearer <redacted>", clean,
                    flags=_re.IGNORECASE)
    clean = _re.sub(r"sk-[A-Za-z0-9_\-]{3,}", "sk-<redacted>", clean)
    clean = _re.sub(r"\b[A-Za-z0-9_\-]{40,}\b", "<redacted>", clean)
    clean = _re.sub(r"\s+", " ", clean).strip()
    return clean


# ── developer override (уровень 1) ──────────────────────────────────────────

def _parse_override_entry(raw: dict) -> ImageModelCapabilities | None:
    if not isinstance(raw, dict):
        return None
    caps = conservative_unknown()
    caps.source = SOURCE_OVERRIDE
    if "text_to_image" in raw:
        caps.text_to_image = TRUE if raw["text_to_image"] else FALSE
    if "image_edit" in raw:
        caps.image_edit = TRUE if raw["image_edit"] else FALSE
    if "max_input_images" in raw:
        try:
            caps.max_input_images = int(raw["max_input_images"])
        except (TypeError, ValueError):
            pass
    if "max_input_bytes" in raw:
        try:
            caps.max_input_bytes = int(raw["max_input_bytes"])
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("supported_sizes"), list):
        caps.supported_sizes = [str(s) for s in raw["supported_sizes"]]
    if "prompt_expansion" in raw:
        caps.prompt_expansion = TRUE if raw["prompt_expansion"] else FALSE
    if "async_jobs" in raw:
        caps.async_jobs = bool(raw["async_jobs"])
    if isinstance(raw.get("prompt_limit"), dict):
        pl = raw["prompt_limit"]
        unit = str(pl.get("unit") or UNIT_UNKNOWN)
        caps.prompt_limit = PromptLimit(
            value=pl.get("value"), unit=unit if unit in PROMPT_UNITS
            else UNIT_UNKNOWN, source=SOURCE_OVERRIDE)
    return caps


def _override_map() -> dict[str, dict]:
    """env `COVER_STYLE_CAPABILITY_OVERRIDES` — JSON `{key: caps}` (§16/D2).

    Ключ — `provider+base_url+model` (или `*` wildcard). НЕ UI-настройка.
    """
    raw = os.getenv("COVER_STYLE_CAPABILITY_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        logger.warning("[image_caps] override JSON parse failed")
        return {}


def _override_key(provider: str, base_url: str, model: str) -> str:
    return f"{provider}|{base_url}|{model}"


# ── runtime discovery (уровень 2) ───────────────────────────────────────────

_PROMPT_LIMIT_KEYS = (
    "max_prompt_length", "prompt_length", "prompt_limit", "max_prompt_chars",
    "prompt_max_chars", "max_prompt_tokens", "max_input_tokens",
    "max_prompt_size",
)


def _extract_limit_value(raw) -> tuple[int, str] | None:
    """Значение лимита из metadata-поля (int | str «N chars» | dict)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("value", "max", "limit", "length"):
            if key in raw:
                return _extract_limit_value(raw[key])
        return None
    if isinstance(raw, (int, float)):
        return (int(raw), UNIT_UNKNOWN) if int(raw) > 0 else None
    parsed = extract_prompt_limit(raw)
    if parsed is not None:
        return parsed
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return (value, UNIT_UNKNOWN) if value > 0 else None


def _prompt_limit_from_metadata(entry: dict | None
                                ) -> tuple[int, str] | None:
    """Найти prompt-limit в model/route metadata (без выдумывания)."""
    if not isinstance(entry, dict):
        return None
    for key in _PROMPT_LIMIT_KEYS:
        if key in entry:
            parsed = _extract_limit_value(entry.get(key))
            if parsed is not None:
                return parsed
    for container_key in ("limits", "capabilities", "parameters",
                          "route", "input_reference_constraints"):
        container = entry.get(container_key)
        if isinstance(container, dict):
            for key in _PROMPT_LIMIT_KEYS:
                if key in container:
                    parsed = _extract_limit_value(container.get(key))
                    if parsed is not None:
                        return parsed
    return None


def parse_discovery(model_entry: dict, endpoints: dict | None = None
                    ) -> ImageModelCapabilities:
    """Собрать capabilities из discovery-ответа провайдера (§3.7/§2.3).

    `model_entry` — элемент `GET /api/v1/image-models?detailed=true`;
    `endpoints` — ответ `GET /api/v1/images/models/{model}/endpoints`.
    Ничего не выдумываем: если поле отсутствует — остаётся `unknown`.
    ASAP 4.2 Step 2c-1 (T-4814): реально заполняем `prompt_limit` из live
    model/route metadata (precedence model → route), иначе честный unknown.
    """
    caps = conservative_unknown()
    caps.source = SOURCE_DISCOVERY
    caps.max_input_images = None
    if not isinstance(model_entry, dict):
        model_entry = {}
    arch = model_entry.get("architecture") or {}
    modalities = arch.get("input_modalities") or []
    if "image" in modalities or "text" in modalities:
        caps.text_to_image = TRUE
    procs = model_entry.get("capabilities") or {}
    if procs.get("image_generation") is True:
        caps.text_to_image = TRUE
    if procs.get("image_to_image") is True or procs.get("inpainting") is True:
        caps.image_edit = TRUE
    elif procs.get("image_to_image") is False and procs.get("inpainting") is False:
        caps.image_edit = FALSE
    params = model_entry.get("supported_parameters") or {}
    if isinstance(params.get("resolutions"), list):
        caps.supported_sizes = [str(s) for s in params["resolutions"]]
    # T-4814: live model metadata → prompt_limit.
    model_limit = _prompt_limit_from_metadata(model_entry)
    if model_limit is not None:
        value, unit = model_limit
        caps.prompt_limit = PromptLimit(value=value, unit=unit,
                                        source=SOURCE_LIVE_MODEL)
    if endpoints:
        # T-4814: live route metadata → prompt_limit (только если model-слой
        # не дал значения).
        if not caps.prompt_limit.known:
            route_limit = _prompt_limit_from_metadata(endpoints)
            if route_limit is not None:
                value, unit = route_limit
                caps.prompt_limit = PromptLimit(value=value, unit=unit,
                                                source=SOURCE_LIVE_ROUTE)
        constraints = (endpoints.get("input_reference_constraints") or {})
        if constraints.get("max_items") is not None:
            try:
                caps.max_input_images = int(constraints["max_items"])
                caps.image_edit = TRUE
            except (TypeError, ValueError):
                pass
        route = endpoints.get("route") or {}
        if route.get("max_bytes") is not None:
            try:
                caps.max_input_bytes = int(route["max_bytes"])
            except (TypeError, ValueError):
                pass
        if "supports_streaming" in endpoints:
            caps.async_jobs = False      # documented image routes non-streaming
    return caps


# ── cache (§17/§71) ─────────────────────────────────────────────────────────

_CACHE: dict[str, tuple[float, ImageModelCapabilities]] = {}
_DEFAULT_TTL_SECONDS = 900.0


def _ttl() -> float:
    try:
        return float(os.getenv("COVER_STYLE_CAPABILITY_TTL_SECONDS", "")
                     or _DEFAULT_TTL_SECONDS)
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def reset_cache() -> None:
    _CACHE.clear()


def invalidate(provider: str, base_url: str, model: str) -> None:
    """Инвалидация конкретной записи (§17: смена connection/model)."""
    _CACHE.pop(_override_key(provider, base_url, model), None)


def _cache_key(provider: str, base_url: str, model: str,
               route: str | None = None) -> str:
    """Cache key T-4814: `provider+base_url+model+route` (смена route/модели
    инвалидирует; `800` не протекает между route)."""
    base = _override_key(provider, base_url, model)
    return base if not route else f"{base}|{str(route).strip().lower()}"


def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, caps = entry
    if (time.monotonic() - ts) > _ttl():
        _CACHE.pop(key, None)
        return None
    return caps


def _cache_put(key: str, caps: ImageModelCapabilities) -> None:
    _CACHE[key] = (time.monotonic(), caps)


def record_runtime_limit(provider: str, base_url: str, model: str,
                         route: str | None, value: int, unit: str) -> None:
    """Закэшировать prompt-limit, извлечённый из machine-readable 400
    (T-4814): уровень `cached runtime-discovered`, per
    `provider+base_url+model+route`. Существующие capability-поля
    сохраняются (обновляется только prompt_limit)."""
    provider = str(provider or "").strip()
    base_url = str(base_url or "").strip().rstrip("/")
    model = str(model or "").strip()
    key = _cache_key(provider, base_url, model, route)
    existing = _cache_get(key)
    caps = existing if existing is not None else conservative_unknown()
    unit = unit if unit in PROMPT_UNITS else UNIT_CHARS
    caps.source = SOURCE_RUNTIME_DISCOVERED
    caps.prompt_limit = PromptLimit(value=int(value), unit=unit,
                                    source=SOURCE_RUNTIME_DISCOVERED)
    _cache_put(key, caps)


# ── public resolver ─────────────────────────────────────────────────────────

# Verified adapter/docs registry (T-4814, уровень 4): подтверждённые лимиты
# из документации провайдера. Сейчас пуст (честный unknown) — заполняется
# ТОЛЬКО при появлении верифицированного внешнего источника, не hardcode.
VERIFIED_PROMPT_LIMIT_REGISTRY: dict[str, tuple[int, str]] = {}


def _lookup_verified_registry(provider: str, model: str
                              ) -> ImageModelCapabilities | None:
    if not VERIFIED_PROMPT_LIMIT_REGISTRY:
        return None
    for key in (f"{provider}|{model}".lower(), str(model or "").lower()):
        entry = VERIFIED_PROMPT_LIMIT_REGISTRY.get(key)
        if entry is not None:
            value, unit = entry
            caps = conservative_unknown()
            caps.source = SOURCE_VERIFIED_REGISTRY
            caps.prompt_limit = PromptLimit(
                value=value, unit=unit if unit in PROMPT_UNITS else UNIT_CHARS,
                source=SOURCE_VERIFIED_REGISTRY)
            return caps
    return None


def _resolve_legacy(provider: str, base_url: str, model: str, *,
                    discovery: dict | None = None,
                    endpoints: dict | None = None,
                    refresh: bool = False, route: str | None = None
                    ) -> ImageModelCapabilities:
    """OFF-контур `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED=false` (байт-в-байт
    2.58.47): override → cache → discovery → unknown."""
    key = _cache_key(provider, base_url, model, route)
    if refresh:
        _CACHE.pop(key, None)
    override_key = _override_key(provider, base_url, model)
    overrides = _override_map()
    for candidate in (override_key, _override_key("*", base_url, model),
                      _override_key(provider, "*", model),
                      _override_key(provider, base_url, "*")):
        if candidate in overrides:
            caps = _parse_override_entry(overrides[candidate])
            if caps is not None:
                _cache_put(key, caps)
                return caps
    cached = _cache_get(key)
    if cached is not None and discovery is None and endpoints is None:
        return cached
    if discovery is not None or endpoints is not None:
        caps = parse_discovery(discovery or {}, endpoints or {})
        _cache_put(key, caps)
        return caps
    caps = conservative_unknown()
    _cache_put(key, caps)
    return caps


def resolve_capabilities(provider: str, base_url: str, model: str, *,
                         discovery: dict | None = None,
                         endpoints: dict | None = None,
                         refresh: bool = False,
                         route: str | None = None
                         ) -> ImageModelCapabilities:
    """Резолв capabilities по `provider+base_url+model` (precedence §16).

    `discovery`/`endpoints` — уже полученные данные провайдера (сетевой вызов
    делает вызывающий контур). Без них — override/TTL-кеш/conservative
    `unknown`. `refresh=True` — форс-инвалидация (§17).

    ASAP 4.2 Step 2c-1 (T-4814): precedence override → live model metadata →
    live route metadata → verified registry → cached runtime-discovered →
    unknown; cache key включает `route`. OFF-kill-switch → прежний контур.
    """
    provider = str(provider or "").strip()
    base_url = str(base_url or "").strip().rstrip("/")
    model = str(model or "").strip()
    if not dynamic_prompt_limit_enabled():
        return _resolve_legacy(provider, base_url, model,
                               discovery=discovery, endpoints=endpoints,
                               refresh=refresh, route=route)
    key = _cache_key(provider, base_url, model, route)
    override_key = _override_key(provider, base_url, model)
    if refresh:
        _CACHE.pop(key, None)

    # Уровень 1: developer override (аварийный escape hatch).
    overrides = _override_map()
    for candidate in (override_key, _override_key("*", base_url, model),
                      _override_key(provider, "*", model),
                      _override_key(provider, base_url, "*")):
        if candidate in overrides:
            caps = _parse_override_entry(overrides[candidate])
            if caps is not None:
                _cache_put(key, caps)
                return caps

    # Уровни 2/3: live model/route metadata.
    if discovery is not None or endpoints is not None:
        caps = parse_discovery(discovery or {}, endpoints or {})
        _cache_put(key, caps)
        return caps

    # Уровень 4: verified adapter/docs registry.
    registry_caps = _lookup_verified_registry(provider, model)
    if registry_caps is not None:
        _cache_put(key, registry_caps)
        return registry_caps

    # Уровень 5: cached runtime-discovered.
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # Уровень 6: conservative unknown.
    caps = conservative_unknown()
    _cache_put(key, caps)
    return caps


async def resolve_capabilities_auto(provider: str, base_url: str, model: str,
                                    *, refresh: bool = False
                                    ) -> ImageModelCapabilities:
    """ASAP-3.2 (T-4196, §21/Q4): discovery вызывается АВТОМАТИЧЕСКИ.

    Сетевой live-discovery (каталог NanoGPT `image-models?detailed=true` +
    endpoints — ЕДИНСТВЕННЫЕ маршруты, подтверждённые кодом, §2.2) выполняется
    здесь, а не только при переданном вызывающим готовом dict; TTL-кеш
    уважается (refresh → инвалидация). Недоступен каталог → conservative
    `unknown` (честный unknown остаётся unknown, §21). Fail-open."""
    provider = str(provider or "").strip()
    base_url = str(base_url or "").strip().rstrip("/")
    model = str(model or "").strip()
    key = _cache_key(provider, base_url, model)
    if refresh:
        _CACHE.pop(key, None)
    overrides = _override_map()
    for candidate in (_override_key(provider, base_url, model),
                      _override_key("*", base_url, model),
                      _override_key(provider, "*", model),
                      _override_key(provider, base_url, "*")):
        if candidate in overrides:
            caps = _parse_override_entry(overrides[candidate])
            if caps is not None:
                _cache_put(key, caps)
                return caps
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    try:
        from services.media_execution import detect_adapter
        adapter = detect_adapter(base_url)
        caps = await adapter.discover_capabilities(model)
    except Exception:
        logger.warning("[image_caps] auto discovery failed — conservative "
                       "unknown | model=%s", model[:60])
        caps = None
    if caps is None:
        caps = conservative_unknown()
    _cache_put(key, caps)
    return caps
