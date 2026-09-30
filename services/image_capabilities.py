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
import time
from dataclasses import dataclass, field

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
        return bool(self.value is not None and self.unit != UNIT_UNKNOWN
                    and int(self.value) > 0)


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

def parse_discovery(model_entry: dict, endpoints: dict | None = None
                    ) -> ImageModelCapabilities:
    """Собрать capabilities из discovery-ответа провайдера (§3.7/§2.3).

    `model_entry` — элемент `GET /api/v1/image-models?detailed=true`;
    `endpoints` — ответ `GET /api/v1/images/models/{model}/endpoints`.
    Ничего не выдумываем: если поле отсутствует — остаётся `unknown`.
    """
    caps = conservative_unknown()
    caps.source = SOURCE_DISCOVERY
    caps.max_input_images = None
    if not isinstance(model_entry, dict):
        return caps
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
    if endpoints:
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


# ── public resolver ─────────────────────────────────────────────────────────

def resolve_capabilities(provider: str, base_url: str, model: str, *,
                         discovery: dict | None = None,
                         endpoints: dict | None = None,
                         refresh: bool = False) -> ImageModelCapabilities:
    """Резолв capabilities по `provider+base_url+model` (precedence §16).

    `discovery`/`endpoints` — уже полученные данные провайдера (сетевой вызов
    делает вызывающий контур, Pass 2 block F). Без них — override/TTL-кеш/
    conservative `unknown`. `refresh=True` — форс-инвалидация (§17).
    """
    provider = str(provider or "").strip()
    base_url = str(base_url or "").strip().rstrip("/")
    model = str(model or "").strip()
    key = _override_key(provider, base_url, model)
    if refresh:
        _CACHE.pop(key, None)

    # Уровень 1: developer override (аварийный escape hatch).
    overrides = _override_map()
    for candidate in (key, _override_key("*", base_url, model),
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

    # Уровень 2: runtime discovery.
    if discovery is not None or endpoints is not None:
        caps = parse_discovery(discovery or {}, endpoints or {})
        _cache_put(key, caps)
        return caps

    # Уровень 5: conservative unknown.
    caps = conservative_unknown()
    _cache_put(key, caps)
    return caps
