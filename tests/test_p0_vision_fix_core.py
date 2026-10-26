"""P0 Vision Universal, lane VISION-FIX-CORE — сервисный контур (recon D1–D14).

Покрытие (карта `plans/features/p0-vision-universal/requirements-map.json`,
слайсы P0V-ARCH/PROBE/PIPE — сервисная часть; UI-фаза отдельно):

  * D1 (P0V-ARCH-SPLIT/ENDPOINTS, P0V-SYMPTOMS): endpoint распознавания
    читается из канонического ключа `models.vision_api_base_url` (его пишет
    каталог/UI); legacy `models.vision_base_url` — только алиас совместимости
    с приоритетом канонического; сохранённый адрес реально уходит в запрос;
  * D2 (P0V-ARCH-KEYS/NOFAULT): ключ — строго по профилю endpoint'а;
    отдельный endpoint без своего ключа НЕ получает основной ключ (честная
    ошибка конфигурации) — включая зеркало в `cover_style_jobs` (scene verify);
  * D3 (P0V-PROBE-IMG): проба отправляет валидное непрозрачное изображение
    512×512+, сгенерированное в коде (не прозрачная PNG 1×1);
  * D4/D5 (P0V-PROBE-400/SPLIT/CLASSIFY/REAL): классы причин различимы
    (конфигурация/авторизация/нет модели/модальность/изображение/rate/
    таймаут/5xx/пустой ответ); HTTP 400 сам по себе ≠ «нет vision» —
    только явный модальный отказ провайдера даёт no_vision; «модель
    доступна» отделено от «принимает изображения»;
  * D6 (P0V-PROBE-CACHE): transient-сбои кешируются коротким TTL (минуты),
    постоянная несовместимость (no_vision/ok) — длинным; успех снимает
    transient;
  * D7 (P0V-PROBE-INVALID): смена ЗНАЧЕНИЯ ключа/endpoint/модели/типа API
    меняет config_revision → старый вердикт не показывается;
  * D8 (P0V-PIPE-E2E/BEYOND): при задании с неизвестной/устаревшей
    capability проба запускается автоматически (singleflight), а не только
    кнопкой «Проверить подключение»);
  * D9 (P0V-PIPE-WORKER): тик воркера не блокируется долгой обработкой
    (claim + фоновые задачи под семафором), перекрытие не теряет очередь и
    не дублирует обработку; heartbeat живой во время обработки;
  * D13/D14 (P0V-ARCH-ADAPTER/BASEURL/NOFAULT): api_type не декоративен —
    неподдерживаемый тип получает конкретный отказ без отправки payload;
    единая сборка URL защищает от двойного `/chat/completions`;
  * routes: `/api/vision/test` отдаёт `visible_reason` + фактического
    провайдера/модель/тип; флаг `flags.vision_enabled` (механика включения
    global/per-chat).

Оффлайн: ВСЕ внешние вызовы — контрактные моки transport (сеть не
используется; моки честно отделены: живых проверок нет).
TEST-LIFECYCLE: CONTRACT owner=P0-Vision/recon-D1-D14;
TEST-LIFECYCLE: REGRESSION owner=P0-Vision/D1 (канонический ключ endpoint);
TEST-LIFECYCLE: REGRESSION owner=P0-Vision/D9 (тик без пропусков).
"""
import asyncio
import hashlib
import hmac
import json
import struct
import time
import types
import urllib.parse
import zlib
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from services import mca_vision
from services import hot_config as hot
from services.database import DatabaseService
from services.config_cache import ConfigCache
from web.api import deps as deps_mod
from web.app import create_app

CHAT = -1005550001
TEST_TOKEN = "123456:TEST_TOKEN_FOR_P0_VISION_TESTS"
ADMIN_ID = 5885953495

_TRANSPORT_SCRIPT_CALLS: list = []


@contextmanager
def patched_settings(**kw):
    saved = {k: getattr(settings, k) for k in kw}
    for k, v in kw.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


def patched_hot(monkeypatch, mapping: dict):
    """hot.get: значения из mapping, иначе default (сеть/ConfigCache не нужны)."""
    real_get = hot.get

    def _get(key, default=None):
        if key in mapping:
            return mapping[key]
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", _get)


@pytest.fixture(autouse=True)
def _clean_state():
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    yield
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()


@pytest.fixture(autouse=True)
def _vision_env():
    """База: K1 ON, основная модель/ключ заданы, Vision-поля пусты."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY="", VISION_API_BASE_URL="",
                          VISION_MODEL="", VISION_API_TYPE="openai_compatible"):
        yield


def ok_body(text: str = "изображение: тёмный квадрат на светлом фоне"):
    return {"choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4}}


class Transport:
    """Контрактный мок транспорта: сценарий (status, body) | Exception."""

    def __init__(self, script=None, default=None):
        self.calls: list = []
        self._script = list(script or [])
        self._default = default if default is not None else (200, ok_body())

    async def __call__(self, url, *, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload,
                           "headers": dict(headers), "timeout": timeout})
        item = self._script.pop(0) if self._script else self._default
        if isinstance(item, BaseException):
            raise item
        status, body = item
        if body is None:
            body = ok_body()
        return status, body

    @property
    def n(self) -> int:
        return len(self.calls)


def probe_calls(t: Transport) -> list:
    return [c for c in t.calls
            if isinstance(c["payload"].get("messages", [{}])[-1].get("content"),
                          list)]


# ═══════════════ D1: канонический ключ endpoint'а ═══════════════════════════

def test_d1_canonical_key_used_by_route(monkeypatch):
    patched_hot(monkeypatch, {"models.vision_api_base_url":
                              "https://openrouter.ai/api/v1"})
    route = mca_vision.resolve_route()
    assert route.base_url == "https://openrouter.ai/api/v1"
    assert route.source == "dedicated"


def test_d1_legacy_alias_only_as_fallback(monkeypatch):
    patched_hot(monkeypatch, {"models.vision_base_url": "https://legacy.example/v1"})
    route = mca_vision.resolve_route()
    assert route.base_url == "https://legacy.example/v1"


def test_d1_canonical_priority_over_legacy(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_base_url": "https://legacy.example/v1",
        "models.vision_api_base_url": "https://canonical.example/api/v1"})
    route = mca_vision.resolve_route()
    assert route.base_url == "https://canonical.example/api/v1"


@pytest.mark.asyncio
async def test_d1_saved_endpoint_reaches_request(monkeypatch):
    """REGRESSION: сохранённый владельцем адрес реально уходит в запрос."""
    patched_hot(monkeypatch, {
        "models.vision_api_base_url": "https://openrouter.ai/api/v1",
        "models.vision_model": "google/gemma-4-31b-it:free",
        "keys.vision_api_key": "vision-key-123",
    })
    route = mca_vision.resolve_route()
    image = mca_vision.validate_image_bytes(mca_vision.probe_images()[0])
    t = Transport()
    await mca_vision.analyze_image_bytes(image, chat_id=CHAT, route=route,
                                         transport=t)
    assert t.n == 1
    assert t.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert t.calls[0]["headers"]["Authorization"] == "Bearer vision-key-123"


# ═══════════════ D2: ключи строго по профилю endpoint'а ═════════════════════

@pytest.mark.asyncio
async def test_d2_dedicated_endpoint_without_key_no_foreign_request(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_api_base_url": "https://openrouter.ai/api/v1",
        "models.vision_model": "google/gemma-4-31b-it:free",
        "keys.vision_api_key": "",
        "keys.llm_api_key": "main-key-999",
    })
    t = Transport()
    verdict = await mca_vision.probe_connection(transport=t)
    assert t.n == 0                       # чужой ключ НЕ отправлен
    assert verdict.capability == "unavailable"
    assert verdict.reason == "vision_unavailable"
    assert verdict.detail == "vision_key_missing"
    assert "ключ" in mca_vision.capability_visible_reason(
        verdict.capability, verdict.reason, verdict.detail).lower()


@pytest.mark.asyncio
async def test_d2_analyze_refuses_without_dedicated_key(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_api_base_url": "https://openrouter.ai/api/v1",
        "models.vision_model": "google/gemma-4-31b-it:free",
        "keys.vision_api_key": "",
        "keys.llm_api_key": "main-key-999",
    })
    image = mca_vision.validate_image_bytes(mca_vision.probe_images()[0])
    t = Transport()
    with pytest.raises(mca_vision.VisionError) as ei:
        await mca_vision.analyze_image_bytes(image, chat_id=CHAT, transport=t)
    assert ei.value.reason == "vision_unavailable"
    assert ei.value.detail == "vision_key_missing"
    assert t.n == 0


@pytest.mark.asyncio
async def test_d2_dedicated_endpoint_uses_own_key_only(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_api_base_url": "https://openrouter.ai/api/v1",
        "models.vision_model": "google/gemma-4-31b-it:free",
        "keys.vision_api_key": "vision-own-key",
        "keys.llm_api_key": "main-key-999",
    })
    t = Transport()
    await mca_vision.probe_connection(transport=t)
    assert t.n == 1
    assert t.calls[0]["headers"]["Authorization"] == "Bearer vision-own-key"


@pytest.mark.asyncio
async def test_d2_separate_model_on_main_endpoint_uses_main_key(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_model": "vlm-x",          # endpoint не задан → main
        "keys.vision_api_key": "",
        "keys.llm_api_key": "main-key-999",
    })
    route = mca_vision.resolve_route()
    assert route.source == "dedicated"
    t = Transport()
    await mca_vision.probe_connection(route=route, transport=t)
    assert t.calls[0]["headers"]["Authorization"] == "Bearer main-key-999"


@pytest.mark.asyncio
async def test_d2_scene_verifier_mirror_key_missing(monkeypatch, tmp_path):
    """Зеркало в cover_style_jobs: dedicated-endpoint без своего ключа →
    честный unknown/key_missing, основной ключ НЕ уходит на чужой endpoint."""
    from services import cover_style_jobs as cjobs
    route = mca_vision.VisionRoute(
        source="dedicated", base_url="https://openrouter.ai/api/v1",
        model="vlm", api_type="openai_compatible", api_key_present=False,
        config_revision="rev")
    monkeypatch.setattr(mca_vision, "resolve_route", lambda chat_id=None: route)
    monkeypatch.setattr(mca_vision, "_vision_base_url", lambda: route.base_url,
                        raising=False)
    monkeypatch.setattr(mca_vision, "api_key_for", lambda r: "", raising=False)
    base = tmp_path / "b.png"
    styled = tmp_path / "s.png"
    base.write_bytes(mca_vision.probe_images()[0])
    styled.write_bytes(mca_vision.probe_images()[1])
    verdict, detail = await cjobs._default_scene_verifier(str(base), str(styled))
    assert verdict == "unknown"
    assert detail in ("key_missing", "vision_key_missing")


# ═══════════════ D3: валидное изображение пробы ═════════════════════════════

def test_d3_probe_image_valid_large_and_opaque():
    images = mca_vision.probe_images()
    assert len(images) == 2
    for data in images:
        sniffed = mca_vision.sniff_image(data)
        assert sniffed is not None
        mime, width, height = sniffed
        assert mime == "image/png"
        assert width >= 512 and height >= 512      # «подходящего размера»
        assert data[24:26] != b"" and data[25] == 2  # RGB, без альфа-канала
        assert len(data) > 1024                    # не 70-байтная 1×1
        assert not data == mca_vision._NEUTRAL_PNG
    assert images[0] != images[1]                  # второй образ — другой


@pytest.mark.asyncio
async def test_d3_probe_payload_contains_large_image(monkeypatch):
    t = Transport()
    await mca_vision.probe_connection(transport=t)
    image_calls = probe_calls(t)
    assert image_calls                      # проба отправила изображение
    part = image_calls[0]["payload"]["messages"][-1]["content"][-1]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    import base64
    raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    mime, width, height = mca_vision.sniff_image(raw)
    assert width >= 512 and height >= 512


# ═══════════════ D4/D5: честная классификация причин ═══════════════════════

def _err(message: str, code: str = "") -> dict:
    return {"error": {"message": message, "code": code or "err", "type": "x"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,capability,detail_prefix", [
    (401, "access_error", "http_401"),
    (403, "access_error", "http_403"),
    (429, "rate_limited", "http_429"),
    (500, "unavailable", "http_500"),
    (503, "unavailable", "http_503"),
])
async def test_d5_matrix_statuses(status, capability, detail_prefix):
    t = Transport(script=[(status, _err("provider says no", str(status))),
                          (status, _err("provider says no", str(status)))])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == capability
    assert verdict.detail.startswith(detail_prefix)
    assert verdict.reason != "main_model_no_vision"


@pytest.mark.asyncio
async def test_d5_timeout_is_transient(monkeypatch):
    t = Transport(script=[TimeoutError(), TimeoutError()])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "unavailable"
    assert verdict.detail == "timeout"


@pytest.mark.asyncio
async def test_d4_plain_400_with_text_ok_is_not_no_vision():
    """REGRESSION (recon D3/D4): 400 без модального отказа ≠ «нет vision»."""
    t = Transport(script=[(400, _err("Bad request")),
                          (200, ok_body("pong"))])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "unavailable"
    assert verdict.capability != "no_vision"
    assert verdict.image_input is None
    assert "изображение" in mca_vision.capability_visible_reason(
        verdict.capability, verdict.reason, verdict.detail)
    state = await mca_vision.resolve_effective_state()
    assert state.effective_enabled is False
    assert state.reason == "vision_unavailable"


@pytest.mark.asyncio
async def test_d4_explicit_modality_refusal_is_no_vision():
    t = Transport(script=[
        (400, _err("This model does not support image input")),
    ])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "no_vision"
    assert verdict.image_input is False
    route = mca_vision.resolve_route()
    expected = ("main_model_no_vision" if route.source == "main_model"
                else "vision_unsupported")
    assert verdict.reason == expected
    assert t.n == 1                            # без лишних контрольных вызовов


@pytest.mark.asyncio
async def test_d5_404_openrouter_modality_refusal_is_no_vision():
    t = Transport(script=[
        (404, _err("No endpoints found that support image input")),
    ])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "no_vision"


@pytest.mark.asyncio
async def test_d5_model_missing_distinguishable_from_modality():
    t = Transport(script=[
        (404, _err("The model `google/gemma-x` does not exist", "model_not_found")),
        (404, _err("The model `google/gemma-x` does not exist")),
    ])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "unavailable"
    assert verdict.detail.startswith("model_not_found")
    assert verdict.capability != "no_vision"
    assert "не найдена" in mca_vision.capability_visible_reason(
        verdict.capability, verdict.reason, verdict.detail)


@pytest.mark.asyncio
async def test_d5_image_rejected_retries_second_image():
    t = Transport(script=[(400, _err("image too small")),
                          (200, ok_body())])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "ok"
    image_calls = probe_calls(t)
    assert len(image_calls) == 2               # второй образ (не тот же)
    first = image_calls[0]["payload"]["messages"][-1]["content"][-1]
    second = image_calls[1]["payload"]["messages"][-1]["content"][-1]
    assert first["image_url"]["url"] != second["image_url"]["url"]


@pytest.mark.asyncio
async def test_d5_image_rejected_twice_is_transient_not_permanent():
    t = Transport(script=[(400, _err("invalid image data")),
                          (400, _err("invalid image data"))])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "unavailable"
    assert "image_rejected" in verdict.detail
    assert verdict.capability != "no_vision"


@pytest.mark.asyncio
async def test_d5_empty_completion_is_not_ok_then_recovers():
    t = Transport(script=[(200, {"id": "x"}),            # 200 без choices
                          (200, ok_body("квадрат"))])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "unavailable"
    assert verdict.detail.startswith("empty_completion")
    verdict2 = await mca_vision.probe_connection(transport=t)
    assert verdict2.capability == "ok"


@pytest.mark.asyncio
async def test_d5_200_with_choices_empty_content_is_ok():
    """Shape-valid ответ (choices есть) — доказательство, что запрос прошёл."""
    t = Transport(script=[(200, {"choices": [{"message": {"content": ""}}]})])
    verdict = await mca_vision.probe_connection(transport=t)
    assert verdict.capability == "ok"


# ═══════════════ D6/D7: TTL кеша и инвалидация ══════════════════════════════

@pytest.mark.asyncio
async def test_d6_transient_short_ttl_permanent_long_ttl():
    route = mca_vision.resolve_route()
    old = time.monotonic() - 120          # 2 минуты: дольше transient-TTL
    mca_vision.store_capability(route, mca_vision.CapabilityVerdict(
        "unavailable", "vision_unavailable", None, old, "http_503"))
    state = await mca_vision.resolve_effective_state()
    assert state.reason == "capability_check_pending"     # transient протух
    mca_vision.reset_capability_cache()
    mca_vision.store_capability(route, mca_vision.CapabilityVerdict(
        "no_vision", "main_model_no_vision", False, old))
    state = await mca_vision.resolve_effective_state()
    assert state.reason != "capability_check_pending"     # постоянное — живёт
    assert state.capability == "no_vision"


@pytest.mark.asyncio
async def test_d6_success_clears_transient():
    route = mca_vision.resolve_route()
    mca_vision.store_capability(route, mca_vision.CapabilityVerdict(
        "unavailable", "vision_unavailable", None, time.monotonic() - 200,
        "http_503"))
    t = Transport()
    verdict = await mca_vision.ensure_capability(route=route, transport=t)
    assert verdict.capability == "ok"
    state = await mca_vision.resolve_effective_state()
    assert state.effective_enabled is True


@pytest.mark.asyncio
async def test_d7_key_value_change_invalidates_verdict(monkeypatch):
    # Dedicated endpoint: ротация ЕГО ключа меняет отпечаток (D7).
    mapping = {"models.vision_api_base_url": "https://openrouter.ai/api/v1",
               "models.vision_model": "vlm-x",
               "keys.vision_api_key": "key-aaa",
               "keys.llm_api_key": "main-key-999"}
    patched_hot(monkeypatch, mapping)
    route_before = mca_vision.resolve_route()
    mca_vision.store_capability(
        route_before,
        mca_vision.CapabilityVerdict("no_vision", "vision_unsupported",
                                     False, time.monotonic()))
    mapping["keys.vision_api_key"] = "key-bbb"
    route_after = mca_vision.resolve_route()
    state = await mca_vision.resolve_effective_state()
    assert route_after.config_revision != route_before.config_revision
    assert state.capability == "pending"      # старый вердикт не действует
    assert state.reason == "capability_check_pending"


@pytest.mark.asyncio
async def test_d7_main_key_rotation_invalidates_main_route(monkeypatch):
    mapping = {"keys.llm_api_key": "main-key-aaa"}
    patched_hot(monkeypatch, mapping)
    rev_before = mca_vision.resolve_route().config_revision
    mapping["keys.llm_api_key"] = "main-key-bbb"
    rev_after = mca_vision.resolve_route().config_revision
    assert rev_after != rev_before


@pytest.mark.asyncio
async def test_d7_endpoint_and_type_changes_invalidate(monkeypatch):
    rev0 = mca_vision.resolve_route().config_revision
    patched_hot(monkeypatch, {"models.vision_api_base_url":
                              "https://other.example/v1"})
    route1 = mca_vision.resolve_route()
    assert route1.config_revision != rev0


def test_d7_revision_hash_has_no_key_material():
    with patched_settings(VISION_API_KEY="super-secret-key-value"):
        route = mca_vision.resolve_route()
    assert len(route.config_revision) == 16
    assert "super-secret-key-value" not in route.config_revision
    hexpart = route.config_revision.lower()
    assert all(ch in "0123456789abcdef" for ch in hexpart)


# ═══════════════ D8: авто-проба ═════════════════════════════════════════════

async def _fresh_db(tmp_path, name="p0vision.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class _FakeBot:
    def __init__(self, blobs: dict):
        self.blobs = blobs

    async def get_file(self, file_id):
        class _F:
            pass
        f = _F()
        f.file_id = file_id
        return f

    async def download(self, tg_file, destination=None):
        destination.write(self.blobs[tg_file.file_id])


def make_png(width=10, height=10) -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    row = b"\x00" + b"\x10\x20\x30" * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def _photo_message(tg_id=101, serial=1):
    from aiogram.types import Chat, Message, PhotoSize, User
    import datetime as _dt
    return Message(
        message_id=tg_id, date=_dt.datetime(2026, 10, 6, 12, 0, 0,
                                            tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        photo=[PhotoSize(file_id=f"fid_{serial}", file_unique_id=f"uniq_{serial}",
                         width=800, height=600, file_size=12345)])


def _bot_with_variants(count: int = 6) -> _FakeBot:
    """Двойник bot: РАЗНЫЕ байты на fid_i (иначе content-hash склеит джобы)."""
    return _FakeBot({f"fid_{i}": make_png(8 + i, 8 + i) for i in range(1, count + 1)})


async def _store(db):
    from services.task_supervisor import TaskJobStore
    return TaskJobStore(db)


async def _claimed_job(db, job_id):
    store = await _store(db)
    await store.mark_running(job_id)
    job = await store.get(job_id) or {}
    job["attempt"] = int(job.get("attempt") or 1)
    return job


ASYNC_ANALYSIS_BODY = {"choices": [{"message": {"content": json.dumps({
    "ocr_blocks": [], "visual_description": "тестовое изображение",
    "uncertainty": [], "self_reported_confidence": 0.8})}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


@pytest.mark.asyncio
async def test_d8_job_auto_probes_when_capability_unknown(tmp_path):
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        msg = _photo_message(tg_id=101)
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        jobs = [j for j in await (await _store(db)).active()
                if j["status"] == "queued"]
        job = await _claimed_job(db, jobs[0]["job_id"])
        t = Transport(default=(200, ASYNC_ANALYSIS_BODY))
        bot = _FakeBot({"fid_1": make_png(12, 12)})
        await mca_vision.process_asset_job(job, db=db, bot=bot, transport=t)
        # Проба (авто) + анализ: задание НЕ умирает capability_check_pending.
        assert t.n == 2
        ready = await db.get_ready_analysis(
            assets[0], mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
        assert (await mca_vision.resolve_effective_state()).effective_enabled
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_d8_auto_probe_failure_reports_honest_reason(tmp_path):
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        msg = _photo_message(tg_id=103)
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        jobs = [j for j in await (await _store(db)).active()
                if j["status"] == "queued"]
        job = await _claimed_job(db, jobs[0]["job_id"])
        t = Transport(script=[(401, _err("no auth"))])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_1": make_png()}),
            transport=t)
        row = await (await _store(db)).get(job["job_id"])
        assert row["status"] == "failed"
        assert row["reason_code"] == "vision_unavailable"      # не pending
        assert t.n == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_d8_probe_singleflight():
    calls = {"n": 0}

    async def counting(url, *, payload, headers, timeout):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return 200, ok_body()

    route = mca_vision.resolve_route()
    results = await asyncio.gather(
        mca_vision.ensure_capability(route=route, transport=counting),
        mca_vision.ensure_capability(route=route, transport=counting))
    assert all(v.capability == "ok" for v in results)
    assert calls["n"] == 1                 # singleflight: одна проба


@pytest.mark.asyncio
async def test_d8_tool_path_probes_when_pending(tmp_path):
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        await mca_vision.register_intake_assets(db, _photo_message(tg_id=201))
        t = Transport(default=(200, ASYNC_ANALYSIS_BODY))
        from services.task_supervisor import TaskJobStore
        mca_vision._RUNTIME["job_store"] = TaskJobStore(db)
        res = await mca_vision.recognize_target(
            db, chat_id=CHAT, own_asset_ids=["x:201"], wait_seconds=0,
            transport=t)
        assert t.n >= 1                    # проба выполнена автоматически
        assert res["status"] == "pending"
        queued = [j for j in await mca_vision._job_store().active()
                  if j["kind"] == mca_vision.VISION_JOB_KIND]
        assert queued                       # manual-джоба поставлена
    finally:
        await db.close()


# ═══════════════ D9: тик воркера без пропусков ══════════════════════════════

def _cap_ok():
    mca_vision.store_capability(
        mca_vision.resolve_route(),
        mca_vision.CapabilityVerdict("ok", "", True, time.monotonic()))


async def _enqueue_asset(db, tg_id, serial=None):
    msg = _photo_message(tg_id=tg_id, serial=serial or 1)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    return assets


async def _active_vision(db, status=None):
    store = await _store(db)
    return [j for j in await store.active()
            if j.get("kind") == mca_vision.VISION_JOB_KIND
            and (status is None or j.get("status") == status)]


async def _wait_active(db, status, count=1, timeout=3.0):
    deadline = time.monotonic() + timeout
    rows: list = []
    while time.monotonic() < deadline:
        rows = await _active_vision(db, status)
        if len(rows) >= count:
            return rows
        await asyncio.sleep(0.02)
    return rows


async def _wait_for(cond, timeout=3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


@pytest.mark.asyncio
async def test_d9_tick_returns_fast_while_job_runs(tmp_path):
    """REGRESSION: долгая обработка не занимает тик (нет skip instances)."""
    db = await _fresh_db(tmp_path)
    release = asyncio.Event()
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        await _enqueue_asset(db, 301)

        async def blocking(url, *, payload, headers, timeout):
            await release.wait()
            return 200, ASYNC_ANALYSIS_BODY

        worker = mca_vision.VisionMediaWorker(
            db, _FakeBot({"fid_1": make_png()}), transport=blocking)
        worker._store = await _store(db)
        started = time.monotonic()
        await asyncio.wait_for(worker._tick_body(), timeout=2.0)
        elapsed = time.monotonic() - started
        assert elapsed < 1.5               # тик мгновенный, обработка — фоном
        running = await _wait_active(db, "running", 1)
        assert running                     # джоба реально взята в работу
        release.set()
        await worker.drain()
        assert not await _active_vision(db)
    finally:
        release.set()
        if worker is not None:
            await worker.drain(timeout=5.0)
        await db.close()


@pytest.mark.asyncio
async def test_d9_overlap_does_not_duplicate_or_lose(tmp_path):
    db = await _fresh_db(tmp_path)
    release = asyncio.Event()
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        await _enqueue_asset(db, 302)
        calls = {"n": 0}

        async def blocking(url, *, payload, headers, timeout):
            calls["n"] += 1
            await release.wait()
            return 200, ASYNC_ANALYSIS_BODY

        worker = mca_vision.VisionMediaWorker(
            db, _FakeBot({"fid_1": make_png()}), transport=blocking)
        worker._store = await _store(db)
        await worker._tick_body()
        await _wait_active(db, "running", 1)
        assert await _wait_for(lambda: calls["n"] == 1)
        await worker._tick_body()          # перекрытие: та же джоба — не дубль
        assert calls["n"] == 1
        release.set()
        await worker.drain()
        await worker._tick_body()
        await worker.drain()
        assert calls["n"] == 1             # повторной обработки нет
        ready = await db.get_ready_analysis(
            (await db.get_media_assets_for_message(CHAT, 302))[0]["asset_id"],
            mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
    finally:
        release.set()
        if worker is not None:
            await worker.drain(timeout=5.0)
        await db.close()


@pytest.mark.asyncio
async def test_d9_capacity_bounded_then_queue_progresses(tmp_path):
    db = await _fresh_db(tmp_path)
    release = asyncio.Event()
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        for serial, tg in ((1, 401), (2, 402), (3, 403)):
            await _enqueue_asset(db, tg, serial=serial)
        calls = {"n": 0}

        async def blocking(url, *, payload, headers, timeout):
            calls["n"] += 1
            await release.wait()
            return 200, ASYNC_ANALYSIS_BODY

        worker = mca_vision.VisionMediaWorker(
            db, _bot_with_variants(), transport=blocking)
        worker._store = await _store(db)
        await worker._tick_body()
        running = await _wait_active(db, "running",
                                     mca_vision.ANALYSIS_CONCURRENCY)
        assert len(running) == mca_vision.ANALYSIS_CONCURRENCY
        queued = await _active_vision(db, "queued")
        assert len(queued) == 1            # третья ждёт слот, не потеряна
        release.set()
        await worker.drain()
        await worker._tick_body()
        await worker.drain()
        assert calls["n"] == 3
        assert not await _active_vision(db)
    finally:
        release.set()
        if worker is not None:
            await worker.drain(timeout=5.0)
        await db.close()


@pytest.mark.asyncio
async def test_d9_heartbeat_alive_during_processing(tmp_path, monkeypatch):
    db = await _fresh_db(tmp_path)
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        await _enqueue_asset(db, 501)

        async def slow(url, *, payload, headers, timeout):
            await asyncio.sleep(2.2)
            return 200, ASYNC_ANALYSIS_BODY

        worker = mca_vision.VisionMediaWorker(
            db, _FakeBot({"fid_1": make_png()}), transport=slow)
        worker._store = await _store(db)
        # Прод-пол heartbeat — 1.0 с (не спамим БД); долгая обработка 2.2 с.
        worker._heartbeat_seconds = 1.0
        hb_calls = {"n": 0}
        real_hb = worker._store.heartbeat

        async def counting_hb(job_id, *, fencing_token=None):
            hb_calls["n"] += 1
            return await real_hb(job_id, fencing_token=fencing_token)

        monkeypatch.setattr(worker._store, "heartbeat", counting_hb)
        await worker._tick_body()
        rows = await _wait_active(db, "running", 1)
        assert rows
        jid = rows[0]["job_id"]
        first_hb = (await worker._store.get(jid))["heartbeat_at"]
        await asyncio.sleep(1.3)
        mid_hb = (await worker._store.get(jid))["heartbeat_at"]
        assert hb_calls["n"] >= 1           # heartbeat пишется во время работы
        assert mid_hb >= first_hb           # и не откатывает живость
        await worker.drain()
        assert (await worker._store.get(jid))["status"] == "completed"
    finally:
        if worker is not None:
            await worker.drain(timeout=5.0)
        await db.close()


# ═══════════════ D13/D14: api_type и сборка URL ═════════════════════════════

@pytest.mark.asyncio
async def test_d13_unsupported_api_type_refused_without_send(monkeypatch):
    with patched_settings(VISION_API_TYPE="anthropic_messages",
                          VISION_MODEL="claude-vision"):
        route = mca_vision.resolve_route()
        t = Transport()
        verdict = await mca_vision.probe_connection(route=route, transport=t)
        assert t.n == 0
        assert verdict.capability == "unavailable"
        assert verdict.detail == "api_type_unsupported"
        assert "не поддерживается" in mca_vision.capability_visible_reason(
            verdict.capability, verdict.reason, verdict.detail)
        image = mca_vision.validate_image_bytes(mca_vision.probe_images()[0])
        with pytest.raises(mca_vision.VisionError) as ei:
            await mca_vision.analyze_image_bytes(
                image, chat_id=CHAT, route=route, transport=t)
    assert ei.value.detail == "api_type_unsupported"
    assert t.n == 0


def test_d14_url_matrix_no_double_chat_completions():
    cases = {
        "https://h": "https://h/chat/completions",
        "https://h/": "https://h/chat/completions",
        "https://h/v1": "https://h/v1/chat/completions",
        "https://h/v1/": "https://h/v1/chat/completions",
        "https://h/api/v1": "https://h/api/v1/chat/completions",
        "https://h/api/v1/": "https://h/api/v1/chat/completions",
        "https://h/v1/chat/completions":
            "https://h/v1/chat/completions",
        "https://h/v1/chat/completions/":
            "https://h/v1/chat/completions",
    }
    for base, expected in cases.items():
        got = mca_vision.chat_completions_url(base)
        assert got == expected, base
        assert got.count("/chat/completions") == 1, base


@pytest.mark.asyncio
async def test_d14_full_path_base_not_doubled(monkeypatch):
    patched_hot(monkeypatch, {
        "models.vision_api_base_url": "https://h.example/api/v1/chat/completions",
        "models.vision_model": "vlm",
        "keys.vision_api_key": "vision-key-123"})
    route = mca_vision.resolve_route()
    image = mca_vision.validate_image_bytes(mca_vision.probe_images()[0])
    t = Transport()
    await mca_vision.analyze_image_bytes(image, chat_id=CHAT, route=route,
                                         transport=t)
    assert t.calls[0]["url"] == "https://h.example/api/v1/chat/completions"


# ═══════════════ Флаг flags.vision_enabled: механика включения ═══════════════

@pytest.mark.asyncio
async def test_flag_global_off_blocks_but_per_chat_override_enables(monkeypatch):
    from services import chat_params

    async def _override(chat_id, key, default=None):
        return True if str(chat_id) == str(CHAT) else default

    patched_hot(monkeypatch, {"flags.vision_enabled": False})
    assert await mca_vision.resolve_requested(None) is False
    monkeypatch.setattr(chat_params, "get_chat_param", _override)
    assert await mca_vision.resolve_requested(CHAT) is True
    other = await mca_vision.resolve_requested(-100999)
    assert other is False


@pytest.mark.asyncio
async def test_flag_global_on_and_per_chat_off(monkeypatch):
    from services import chat_params

    async def _override(chat_id, key, default=None):
        return False if str(chat_id) == str(CHAT) else default

    patched_hot(monkeypatch, {"flags.vision_enabled": True})
    monkeypatch.setattr(chat_params, "get_chat_param", _override)
    assert await mca_vision.resolve_requested(None) is True
    assert await mca_vision.resolve_requested(CHAT) is False


# ═══════════════ routes: /api/vision/test отдаёт витрину D11/D12 ════════════

def _make_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _make_init_data(user_id)}


class _RouteFakeConn:
    async def fetch(self, sql, *args):
        return []

    async def fetchrow(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        return "OK"


class _RouteFakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False
        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _RouteFakePg:
    def __init__(self, conn):
        self._pool = _RouteFakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def route_client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _RouteFakeConn()
    conn._settings_rows = [
        {"key": "keys.vision_api_key", "value": "vision-secret-9876",
         "category": "keys", "updated_at": None},
        {"key": "models.vision_api_base_url",
         "value": "https://openrouter.ai/api/v1", "category": "models",
         "updated_at": None},
        {"key": "models.vision_model", "value": "google/gemma-4-31b-it:free",
         "category": "models", "updated_at": None},
    ]
    conn._role_rows = [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False},
    ]
    conn._admin_rows = [{"telegram_id": ADMIN_ID, "role_name": "admin",
                         "added_by": None, "created_at": None}]

    async def _fetch(sql, *args):
        if "bot_settings" in sql:
            return conn._settings_rows
        if "bot_roles" in sql:
            return conn._role_rows
        if "bot_admins" in sql:
            return conn._admin_rows
        return []

    conn.fetch = _fetch
    cache = ConfigCache(pg=_RouteFakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as client:
        client.cache = cache
        yield client
    from web.api import routes as routes_mod
    routes_mod.reset_vision_test_rate_limit()


def test_route_vision_test_exposes_visible_reason_provider_type(
        route_client, monkeypatch):
    monkeypatch.setattr(hot, "_cache", route_client.cache)

    async def fake_probe(route=None, *, transport=None):
        return mca_vision.CapabilityVerdict(
            "access_error", "vision_unavailable", None, time.monotonic(),
            "http_401")

    monkeypatch.setattr(mca_vision, "probe_connection", fake_probe)
    resp = route_client.post("/api/vision/test", headers=_hdr(), json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visible_reason"]                   # человекочитаемая причина
    assert "ключ" in body["visible_reason"].lower()
    assert body["provider"] == "openrouter.ai"      # фактический провайдер
    assert body["api_type"] == "openai_compatible"  # тип подключения
    assert body["model"] == "google/gemma-4-31b-it:free"
    assert "vision-secret-9876" not in resp.text    # R17: секрет не раскрыт
    assert "[native code]" not in resp.text


def test_route_vision_test_ok_case(route_client, monkeypatch):
    monkeypatch.setattr(hot, "_cache", route_client.cache)

    async def fake_probe(route=None, *, transport=None):
        return mca_vision.CapabilityVerdict(
            "ok", "", True, time.monotonic(), "")

    monkeypatch.setattr(mca_vision, "probe_connection", fake_probe)
    resp = route_client.post("/api/vision/test", headers=_hdr(), json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["visible_reason"] == "Распознавание работает"
    assert body["state"]["provider"] == "openrouter.ai"
    assert body["state"]["api_type"] == "openai_compatible"


# ═══════════════ Витрина причин (D5/D11): юнит-тексты ═══════════════════════

def test_visible_reason_texts_cover_all_classes():
    cases = {
        ("ok", "", ""): "Распознавание работает",
        ("no_vision", "main_model_no_vision", ""):
            "Основная модель не поддерживает изображения",
        ("no_vision", "vision_unsupported", "image_modality_unsupported/http_400"):
            "Модель не принимает изображения",
        ("access_error", "vision_unavailable", "http_401"):
            "Неверный ключ",
        ("rate_limited", "vision_rate_limited", "http_429"):
            "Превышен лимит",
        ("unavailable", "vision_unavailable", "vision_key_missing"):
            "отдельный ключ",
        ("unavailable", "vision_unavailable", "api_type_unsupported"):
            "не поддерживается",
        ("unavailable", "vision_unavailable", "model_not_found/http_404"):
            "не найдена",
        ("unavailable", "vision_unavailable", "timeout"):
            "таймаут",
        ("unavailable", "vision_unavailable", "image_rejected/http_400"):
            "изображение не принято",
        ("unavailable", "vision_unavailable", "http_503"):
            "недоступен",
        ("pending", "capability_check_pending", ""):
            "Проверка подключения",
    }
    for (cap, reason, detail), expected in cases.items():
        text = mca_vision.capability_visible_reason(cap, reason, detail)
        assert expected.lower() in text.lower(), (cap, reason, detail, text)


# ═════════ FIX2 (live 2.58.91): планировщик-энтри, state per-chat, 429 ══════
# Живая приёмка 2.58.91 дала три дефекта: (1) SKIPS=36 `VisionMediaWorker._tick
# … maximum number of running instances reached (1)` — тик сам ждал медленную
# БД-фазу (busy_timeout 5 с ≈ интервал тика); (2) `GET /api/vision/state`
# игнорировал per-chat override (глобальный `vision_disabled`);
# (3) 429 провайдера оставлял актив/джобу терминально неразобранными.
# TEST-LIFECYCLE: REGRESSION owner=P0V-PIPE-WORKER/FIX2 (тик без пропусков);
# TEST-LIFECYCLE: REGRESSION owner=P0V-PIPE-E2E/FIX2 (state per-chat);
# TEST-LIFECYCLE: REGRESSION owner=P0V-PROBE-CACHE/FIX2 (429 не залипает).

async def _slow_db_stage(seconds: float, calls: dict | None = None):
    """Двойник медленной БД-фазы (занятая SQLite-транзакция/лок)."""
    async def _stage(*args, **kwargs):
        if calls is not None:
            calls["n"] = int(calls.get("n") or 0) + 1
        await asyncio.sleep(seconds)
        return []
    return _stage


@pytest.mark.asyncio
async def test_fix2_tick_entry_returns_immediately_while_db_busy(tmp_path,
                                                                 monkeypatch):
    """REGRESSION (P0V-PIPE-WORKER): планировщик-энтри не выполняет БД-работу
    — вызов `_tick` возвращается мгновенно даже когда recover/claim-фазы
    заблокированы (искусственно медленный шаг). RED: тик ждал фазы
    последовательно и перекрывал интервал 5 с."""
    from services.task_supervisor import TaskJobStore
    db = await _fresh_db(tmp_path)
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        await _enqueue_asset(db, 701)
        slow = await _slow_db_stage(5.0)
        monkeypatch.setattr(TaskJobStore, "recover_stale", slow)

        async def slow_active(self):
            await asyncio.sleep(5.0)
            return []
        monkeypatch.setattr(TaskJobStore, "active", slow_active)

        worker = mca_vision.VisionMediaWorker(
            db, _FakeBot({"fid_1": make_png()}), transport=Transport())
        worker._store = await _store(db)
        started = time.monotonic()
        await asyncio.wait_for(worker._tick(), timeout=1.0)
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, elapsed      # интервал тика — 5 с
    finally:
        if worker is not None:
            await worker.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_fix2_tick_never_skipped_with_slow_db_stage(
        tmp_path, monkeypatch, caplog):
    """REGRESSION (P0V-PIPE-WORKER, live SKIPS=36): медленная БД-фаза больше
    не даёт APScheduler `maximum number of running instances reached`, а
    очередь при этом не стоит (claim идёт отдельным фоновым sweep'ом)."""
    import logging
    from services.task_supervisor import TaskJobStore
    db = await _fresh_db(tmp_path)
    worker = None
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await _enqueue_asset(db, 711)
        monkeypatch.setattr(mca_vision, "VISION_TICK_SECONDS", 0.2)
        slow_calls: dict = {}
        monkeypatch.setattr(TaskJobStore, "recover_stale",
                            await _slow_db_stage(1.0, slow_calls))

        worker = mca_vision.VisionMediaWorker(
            db, _FakeBot({"fid_1": make_png()}),
            transport=Transport(default=(200, ASYNC_ANALYSIS_BODY)))
        ticks = {"n": 0}
        real_tick = worker._tick

        async def counting_tick():
            ticks["n"] += 1
            await real_tick()
        worker._tick = counting_tick
        worker.start()
        with caplog.at_level(logging.WARNING):
            await asyncio.sleep(1.2)
            skips = [r.getMessage() for r in caplog.records
                     if "maximum number of running instances"
                     in r.getMessage()]
            assert not skips, skips                # ни одного пропуска
            assert ticks["n"] >= 3, ticks          # планировщик реально тикал
            assert slow_calls.get("n")             # медленная фаза шла (фоном)
            await worker.drain(timeout=5.0)
        assert not await _active_vision(db)        # очередь не стоит из-за неё
        ready = await db.get_ready_analysis(
            assets[0], mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
    finally:
        if worker is not None:
            await worker.drain(timeout=5.0)
            await worker.shutdown()
        await db.close()


def test_route_vision_state_per_chat_context(route_client, monkeypatch):
    """REGRESSION (P0V-PIPE-E2E): `GET /api/vision/state` учитывает per-chat
    override (X-Chat-Id) и остаётся глобальным без него; маскировка секретов
    не ломается; чужой чат (нет доступа) → глобальный слой (F3 ревью)."""
    from services import access as access_srv
    from services import chat_params
    monkeypatch.setattr(hot, "_cache", route_client.cache)
    patched_hot(monkeypatch, {"flags.vision_enabled": False})
    foreign = -1009999999

    async def _override(chat_id, key, default=None):
        return True if str(chat_id) in (str(CHAT), str(foreign)) else default

    monkeypatch.setattr(chat_params, "get_chat_param", _override)
    real_can = access_srv.can_access_chat
    monkeypatch.setattr(
        access_srv, "can_access_chat",
        lambda ctx, chat=None: False if chat == foreign
        else real_can(ctx, chat))

    global_resp = route_client.get("/api/vision/state", headers=_hdr())
    assert global_resp.status_code == 200, global_resp.text
    global_body = global_resp.json()
    assert global_body["requested"] is False          # глобальный слой
    assert global_body["reason"] == "vision_disabled"

    chat_resp = route_client.get("/api/vision/state",
                                 headers={**_hdr(), "X-Chat-Id": str(CHAT)})
    assert chat_resp.status_code == 200, chat_resp.text
    chat_body = chat_resp.json()
    assert chat_body["requested"] is True             # per-chat override
    assert chat_body["reason"] != "vision_disabled"
    assert "vision-secret-9876" not in chat_resp.text  # R17: без секретов

    # Чужой чат (даже с включённым override) → глобальный слой, не per-chat.
    foreign_resp = route_client.get(
        "/api/vision/state", headers={**_hdr(), "X-Chat-Id": str(foreign)})
    assert foreign_resp.status_code == 200, foreign_resp.text
    foreign_body = foreign_resp.json()
    assert foreign_body["requested"] is False
    assert foreign_body["reason"] == "vision_disabled"


def test_route_vision_test_state_per_chat_context(route_client, monkeypatch):
    """REGRESSION (NF-1, ревью e3fa4e97 / P0V-PIPE-E2E):
    `POST /api/vision/test` отдаёт КОНТЕКСТНО-корректный `state` — с X-Chat-Id
    per-chat (global OFF + chat ON ≠ `vision_disabled`), без контекста —
    прежний глобальный слой, чужой чат — тоже глобальный (без утечки
    per-chat настроек)."""
    from services import access as access_srv
    from services import chat_params
    from web.api import routes as routes_mod
    monkeypatch.setattr(hot, "_cache", route_client.cache)
    patched_hot(monkeypatch, {"flags.vision_enabled": False})
    foreign = -1009999999

    async def _override(chat_id, key, default=None):
        return True if str(chat_id) in (str(CHAT), str(foreign)) else default

    monkeypatch.setattr(chat_params, "get_chat_param", _override)
    real_can = access_srv.can_access_chat
    monkeypatch.setattr(
        access_srv, "can_access_chat",
        lambda ctx, chat=None: False if chat == foreign
        else real_can(ctx, chat))

    async def fake_probe(route=None, *, transport=None):
        return mca_vision.CapabilityVerdict("ok", "", True, time.monotonic(),
                                            "")

    monkeypatch.setattr(mca_vision, "probe_connection", fake_probe)

    # Без контекста чата — глобальный слой (прежнее поведение пробы).
    glob = route_client.post("/api/vision/test", headers=_hdr(), json={})
    assert glob.status_code == 200, glob.text
    assert glob.json()["state"]["requested"] is False
    assert glob.json()["state"]["reason"] == "vision_disabled"

    routes_mod.reset_vision_test_rate_limit()
    # Контекст чата: per-chat override учтён в `state` ответа пробы.
    chat = route_client.post("/api/vision/test",
                             headers={**_hdr(), "X-Chat-Id": str(CHAT)},
                             json={})
    assert chat.status_code == 200, chat.text
    chat_body = chat.json()
    assert chat_body["ok"] is True                    # проба прошла (мок ok)
    assert chat_body["state"]["requested"] is True    # НЕ глобальный OFF
    assert chat_body["state"]["reason"] != "vision_disabled"
    assert "vision-secret-9876" not in chat.text      # R17: без секретов

    routes_mod.reset_vision_test_rate_limit()
    # Чужой чат → глобальный слой (per-chat настройки не раскрываются).
    foreign_resp = route_client.post(
        "/api/vision/test", headers={**_hdr(), "X-Chat-Id": str(foreign)},
        json={})
    assert foreign_resp.status_code == 200, foreign_resp.text
    assert foreign_resp.json()["state"]["requested"] is False
    assert foreign_resp.json()["state"]["reason"] == "vision_disabled"


@pytest.mark.asyncio
async def test_fix2_rate_limited_retries_within_window_then_terminal(tmp_path):
    """REGRESSION (P0V-PROBE-CACHE): 429 — временный провайдерский лимит:
    свежая джоба получает bounded-повтор сверх JOB_MAX_ATTEMPTS, старая
    (за окном) завершается честным терминальным failed."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await _enqueue_asset(db, 721)
        store = await _store(db)
        job = await _claimed_job(db, (await _active_vision(db, "queued"))[0]
                                 ["job_id"])
        job["attempt"] = mca_vision.JOB_MAX_ATTEMPTS      # попытки исчерпаны
        job["created_at"] = int(time.time())              # свежий актив
        t = Transport(script=[(429, _err("rate limited", "429")),
                              (429, _err("rate limited", "429"))])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_1": make_png()}), transport=t)
        row = await store.get(job["job_id"])
        assert row["status"] == "queued"                  # НЕ терминал
        assert row["reason_code"] == "vision_rate_limited"
        assert int(row["next_retry_at"] or 0) > int(time.time())

        # Джоба за окном ретраев → честный терминальный исход (без залипания
        # «вечно queued»).
        aged = await _claimed_job(db, job["job_id"])
        aged["attempt"] = mca_vision.JOB_MAX_ATTEMPTS
        aged["created_at"] = int(time.time()) \
            - mca_vision.RATE_LIMIT_RETRY_WINDOW_SECONDS - 60
        await mca_vision.process_asset_job(
            aged, db=db, bot=_FakeBot({"fid_1": make_png()}), transport=t)
        row = await store.get(job["job_id"])
        assert row["status"] == "failed"
        assert row["reason_code"] == "vision_rate_limited"
        assert await db.get_ready_analysis(
            assets[0], mca_vision.access_scope_for(CHAT)) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fix2_rate_limited_live_retry_succeeds_after_limit(tmp_path):
    """REGRESSION (P0V-PIPE-E2E): после снятия 429 ПОВТОР живой джобы реально
    распознаёт актив (гранула анализа получает свободный `revision`; иначе
    повтор падал на UNIQUE-грануле и актив не разбирался)."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await _enqueue_asset(db, 741)
        store = await _store(db)
        bot = _FakeBot({"fid_1": make_png()})
        jid = (await _active_vision(db, "queued"))[0]["job_id"]
        job = await _claimed_job(db, jid)
        # попытка 1: провайдерский лимит (429) → bounded-retry, не терминал
        await mca_vision.process_asset_job(
            job, db=db, bot=bot,
            transport=Transport(default=(429, _err("rate limited", "429"))))
        row = await store.get(jid)
        assert row["status"] == "queued"
        assert row["reason_code"] == "vision_rate_limited"
        # лимит снят: повтор (та же гранула) доходит до результата
        retry = await _claimed_job(db, jid)
        await mca_vision.process_asset_job(
            retry, db=db, bot=bot,
            transport=Transport(default=(200, ASYNC_ANALYSIS_BODY)))
        assert (await store.get(jid))["status"] == "completed"
        ready = await db.get_ready_analysis(
            assets[0], mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fix2_backfill_rearms_transient_terminal_job(tmp_path,
                                                           monkeypatch):
    """REGRESSION (P0V-PROBE-CACHE): 429 на архивном пути не «залипает»:
    retry-долг (`next_retry_at`) уважается, терминальная transient-неудача
    переставляется по cooldown, и после снятия лимита актив распознаётся."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        msg = _photo_message(tg_id=731)
        assets = await mca_vision.register_intake_assets(db, msg)
        asset_id = assets[0]
        await db.db.execute(
            "UPDATE mca_media_assets SET created_at=? WHERE asset_id=?",
            (int(time.time()) - 7200, asset_id))
        await db.db.commit()
        store = await _store(db)
        bot = _FakeBot({"fid_1": make_png()})
        bad = Transport(default=(429, _err("rate limited", "429")))
        first = await mca_vision.backfill_sweep(db, bot, store=store,
                                                transport=bad)
        assert first["processed"] == 1
        jid = f"vision:bf:{asset_id}"
        row = await store.get(jid)
        assert row["status"] == "queued"          # bounded-retry, не терминал
        assert row["reason_code"] == "vision_rate_limited"
        assert int(row["next_retry_at"] or 0) > int(time.time())
        # Retry-долг уважается: сразу повторный sweep НЕ берёт джобу.
        second = await mca_vision.backfill_sweep(db, bot, store=store,
                                                 transport=bad)
        assert second["processed"] == 0
        # Бюджет попыток исчерпан → терминальная transient-неудача (как в
        # живой приёмке: 429 длился дольше бюджета джобы).
        await store.finish(jid, status="failed",
                           reason_code="vision_rate_limited")
        assert (await store.get(jid))["status"] == "failed"
        # Cooldown: свежая терминальная неудача НЕ переставляется (нет шторма).
        third = await mca_vision.backfill_sweep(db, bot, store=store,
                                                transport=bad)
        assert third["processed"] == 0
        assert (await store.get(jid))["status"] == "failed"
        # Cooldown прошёл, лимит снят → актив разобран (не «залип» навсегда).
        await db.db.execute(
            "UPDATE task_jobs SET finished_at=? WHERE job_id=?",
            (int(time.time())
             - mca_vision.BACKFILL_REARM_COOLDOWN_SECONDS - 60, jid))
        await db.db.commit()
        good = Transport(default=(200, ASYNC_ANALYSIS_BODY))
        fourth = await mca_vision.backfill_sweep(db, bot, store=store,
                                                 transport=good)
        assert fourth["processed"] == 1
        ready = await db.get_ready_analysis(
            asset_id, mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
        # Идемпотентность: готовый актив больше не кандидат.
        fifth = await mca_vision.backfill_sweep(db, bot, store=store,
                                                transport=good)
        assert fifth["processed"] == 0
    finally:
        await db.close()

# ════════════════════════════════════════════════════════════════════════════
# ASAP5 §9-§11 (wave W1, slice ASAP5-MEDIA-RECOGNITION): честная матрица
# возможностей типов медиа; адаптеры превью video/video_note; единый путь
# представления (intake → job → render → reply/tool) без нового пайплайна.
# TEST-LIFECYCLE: CONTRACT owner=ASAP5-MEDIA-RECOGNITION (capability matrix)
# TEST-LIFECYCLE: INTEGRATION owner=ASAP5-MEDIA-RECOGNITION (preview intake →
#                  job → honest render → reply/tool targeting)
# ════════════════════════════════════════════════════════════════════════════

def _asap5_thumb(serial: int):
    from aiogram.types import PhotoSize
    return PhotoSize(file_id=f"asap_thumb_fid_{serial}",
                     file_unique_id=f"asap_thumb_uniq_{serial}",
                     width=320, height=240, file_size=4321)


def _asap5_photo_message(tg_id, serial=1, *, caption=None,
                         media_group_id=None):
    from aiogram.types import Chat, Message, PhotoSize, User
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        photo=[PhotoSize(file_id=f"fid_{serial}",
                         file_unique_id=f"uniq_{serial}",
                         width=800, height=600, file_size=12345)],
        caption=caption, media_group_id=media_group_id)


def _asap5_video(tg_id, serial=1, *, with_thumb=True, media_group_id=None):
    from aiogram.types import Chat, Message, User, Video
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        video=Video(file_id=f"asap_vid_fid_{serial}",
                    file_unique_id=f"asap_vid_uniq_{serial}",
                    width=1280, height=720, duration=42,
                    mime_type="video/mp4", file_size=2_000_000,
                    thumbnail=(_asap5_thumb(serial) if with_thumb else None)),
        media_group_id=media_group_id)


def _asap5_video_note(tg_id, serial=1, *, with_thumb=True):
    from aiogram.types import Chat, Message, User, VideoNote
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        video_note=VideoNote(file_id=f"asap_vn_fid_{serial}",
                             file_unique_id=f"asap_vn_uniq_{serial}",
                             length=360, duration=15,
                             file_size=800_000,
                             thumbnail=(_asap5_thumb(serial)
                                        if with_thumb else None)))


def _asap5_sticker(tg_id, *, is_animated=False, is_video=False,
                   with_thumb=False):
    from aiogram.types import Chat, Message, PhotoSize, Sticker, User
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        sticker=Sticker(file_id="asap_st_fid", file_unique_id="asap_st_uniq",
                        width=512, height=512,
                        is_animated=is_animated, is_video=is_video,
                        type="regular",
                        thumbnail=(_asap5_thumb(90 + tg_id % 100)
                                   if with_thumb else None)))


def _asap5_animation(tg_id, serial=1, *, with_thumb=True):
    from aiogram.types import Animation, Chat, Message, User
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        animation=Animation(file_id=f"asap_gif_fid_{serial}",
                            file_unique_id=f"asap_gif_uniq_{serial}",
                            width=320, height=240, duration=3,
                            mime_type="video/mp4", file_name="gif.mp4",
                            file_size=100_000,
                            thumbnail=(_asap5_thumb(serial)
                                       if with_thumb else None)))


def _asap5_document_message(tg_id, *, mime="image/jpeg",
                            file_name="pic.jpg"):
    from aiogram.types import Chat, Document, Message, User
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        document=Document(file_id="asap_doc_fid",
                          file_unique_id="asap_doc_uniq",
                          file_name=file_name, mime_type=mime,
                          file_size=3000))


def _asap5_voice_or_audio(tg_id, *, audio=False):
    from aiogram.types import Audio, Chat, Message, User, Voice
    import datetime as _dt
    media = (Audio(file_id="asap_au_fid", file_unique_id="asap_au_uniq",
                   duration=180)
             if audio else
             Voice(file_id="asap_vo_fid", file_unique_id="asap_vo_uniq",
                   duration=7))
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Sergey"),
        **({"audio": media} if audio else {"voice": media}))


def _asap5_matrix_cases() -> dict:
    """Честная матрица §9: (type → [(asset_kind, size_variant, representation)]).

    Источник истины — `mca_vision.media_capability` (тот же код, что и
    intake); ожидания зафиксированы по владельческому списку типов §9."""
    V = mca_vision.REPRESENTATION_VISION
    U = mca_vision.REPRESENTATION_UNSUPPORTED
    N = mca_vision.REPRESENTATION_NONE
    return {
        # §9: фото
        "photo": (_asap5_photo_message(801, serial=1),
                  [("photo", "large", V)]),
        # §9: изображения, отправленные документами
        "document_image": (_asap5_document_message(802),
                           [("document", "document", V)]),
        # §9: статические стикеры
        "sticker_static": (_asap5_sticker(803),
                           [("sticker", "sticker", V)]),
        # §9: GIF / Telegram Animation — источник честный unsupported (D18),
        # растровая обложка — корректное визуальное представление (§10)
        "gif_animation": (_asap5_animation(804),
                          [("animation", "animation", U),
                           ("animation_preview", "animation_preview", V)]),
        # §9: анимированные TGS-стикеры — источник honest unsupported +
        # обложка Vision (с Bot API ≥7.2; без обложки — только honest строка)
        "tgs_sticker": (_asap5_sticker(805, is_animated=True),
                        [("animation", "sticker", U)]),
        # §9: видеостикеры WebM — источник honest unsupported (обложка —
        # только при наличии thumbnail, как у TGS)
        "webm_video_sticker": (_asap5_sticker(806, is_video=True),
                               [("animation", "sticker", U)]),
        # §9: превью обычных видеозаписей — растровый кандидат Vision
        "video_with_thumb": (_asap5_video(807, serial=1),
                             [("video_preview", "video_preview", V)]),
        # §10: видео без превью — честное отсутствие (ничего не выдумываем)
        "video_no_thumb": (_asap5_video(808, serial=2, with_thumb=False),
                           []),
        # §9: превью видеосообщений (кружочки)
        "video_note_with_thumb": (_asap5_video_note(809, serial=3),
                                  [("video_preview", "video_note_preview",
                                    V)]),
        # §9: доступные медиа внутри альбомов
        "album_photo": (_asap5_photo_message(810, serial=4,
                                             media_group_id="grp-80"),
                        [("photo", "large", V)]),
        # вне визуальной матрицы: голосовые/аудио — свой STT-пайплайн
        "voice": (_asap5_voice_or_audio(811), []),
        "audio": (_asap5_voice_or_audio(812, audio=True), []),
        # не-изображение документом — визуального кандидата нет
        "document_non_image": (_asap5_document_message(813,
                                                       mime="application/pdf",
                                                       file_name="doc.pdf"),
                               []),
    }


@pytest.mark.parametrize("case", [
    "photo", "document_image", "sticker_static", "gif_animation",
    "tgs_sticker", "webm_video_sticker", "video_with_thumb",
    "video_no_thumb", "video_note_with_thumb", "album_photo",
    "voice", "audio", "document_non_image",
])
def test_asap5_capability_matrix(case):
    """CONTRACT (ASAP5 §9): матрица фактической поддержки по каждому типу —
    детект/адаптер/путь представления/маркеры payload. Один источник
    истины: `media_capability` поверх `extract_image_assets`."""
    msg, expected = _asap5_matrix_cases()[case]
    cap = mca_vision.media_capability(msg)
    got = [(d["asset_kind"], d["size_variant"], d["representation"])
           for d in cap["detected"]]
    assert got == expected, f"{case}: {got} != {expected}"
    for d in cap["detected"]:
        if d["representation"] == mca_vision.REPRESENTATION_VISION:
            assert d["asset_kind"] in mca_vision.SUPPORTED_ASSET_KINDS
            assert d["file_id_present"] and d["file_unique_id_present"]
        else:
            assert d["asset_kind"] not in mca_vision.SUPPORTED_ASSET_KINDS
    if case == "album_photo":
        assert cap["album"] is True
    if case in ("voice", "audio", "video_no_thumb", "document_non_image"):
        assert cap["detected"] == []          # честное отсутствие кандидатов


def test_asap5_preview_candidate_binds_thumb_not_video():
    """§10 (адаптер без случайного файла): кандидат превью несёт file_id
    кадра-обложки, а НЕ file_id самого видео."""
    msg = _asap5_video(807, serial=1)
    cand = mca_vision.extract_image_assets(msg)[0]
    assert cand["file_id"] == "asap_thumb_fid_1"
    assert cand["file_unique_id"] == "asap_thumb_uniq_1"
    assert cand["file_id"] != getattr(msg.video, "file_id")
    assert cand["mime"] == "image/jpeg"
    # превью видео и превью кружочка — разные size_variant → разные asset_id
    a = mca_vision.make_asset_id(CHAT, 807, "asap_thumb_uniq_1",
                                 "video_preview")
    b = mca_vision.make_asset_id(CHAT, 809, "asap_thumb_uniq_3",
                                 "video_note_preview")
    assert a != b


@pytest.mark.asyncio
async def test_asap5_video_preview_intake_job_render(tmp_path):
    """INTEGRATION (ASAP5 §9/§10): превью видео проходит СУЩЕСТВУЮЩИЙ путь
    intake → durable job → Vision (один вызов на актив) → ready-анализ;
    рендер честно маркирует уровень «анализ превью», не полный просмотр."""
    from services import message_identity
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        msg = _asap5_video(851, serial=1)
        assets = await mca_vision.register_intake_assets(db, msg)
        assert len(assets) == 1
        row = (await db.get_media_assets_for_message(CHAT, 851))[0]
        # §11: chat_id/message_id/asset_id/file_id и связь с сообщением
        assert row["chat_id"] == CHAT and row["tg_message_id"] == 851
        assert row["asset_id"] == assets[0]
        assert row["file_id"] == "asap_thumb_fid_1"
        assert row["message_key"] == f"{CHAT}:851"
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        jid = (await _active_vision(db, "queued"))[0]["job_id"]
        job = await _claimed_job(db, jid)
        t = Transport(default=(200, ASYNC_ANALYSIS_BODY))
        await mca_vision.process_asset_job(
            job, db=db,
            bot=_FakeBot({"asap_thumb_fid_1": make_png()}), transport=t)
        assert (await (await _store(db)).get(jid))["status"] == "completed"
        ready = await db.get_ready_analysis(
            assets[0], mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
        # честный рендер: заметка о превью + содержимое кадра
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text=None, caption=None,
            timestamp=1760000000, sent_at=1760000000, ingested_at=1760000000,
            media_type="video", author_name="Sergey", tg_message_id=851)
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=851)
        assert rendered is not None
        assert mca_vision.VIDEO_PREVIEW_NOTE in rendered["lines"]
        assert rendered["visual_descriptions"]
        assert f"msg:{CHAT}:851" in rendered["text"]
        # tool-путь: reply-target → готовый анализ с маркером вида актива
        res = await mca_vision.recognize_target(
            db, chat_id=CHAT, reply_tg_id=851, wait_seconds=0)
        assert res["status"] == "ready"
        assert res["asset_kind"] == mca_vision.ASSET_KIND_VIDEO_PREVIEW
        assert res["asset_id"] == assets[0]
        assert res["cache_hit"] is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_asap5_video_without_thumb_honest_no_content(tmp_path):
    """CONTRACT (ASAP5 §10): видео без превью — честный уровень «нет
    доступного содержимого», без выдуманного анализа; текстовые/голосовые
    строки по-прежнему не попадают в media-рендер (None)."""
    from services import message_identity
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        msg = _asap5_video(861, serial=2, with_thumb=False)
        assert await mca_vision.register_intake_assets(db, msg) == []
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text=None, caption=None,
            timestamp=1760000000, sent_at=1760000000, ingested_at=1760000000,
            media_type="video", author_name="Sergey", tg_message_id=861)
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=861)
        assert rendered is not None
        assert mca_vision.NO_VISUAL_CONTENT_LINE in rendered["lines"]
        assert rendered["knowledge_time"] is None
        assert not rendered["visual_descriptions"]
        assert not rendered["untrusted_ocr_texts"]
        # текстовая строка — прежнее поведение (None, нет media-блока)
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text="просто текст",
            caption=None, timestamp=1760000000, sent_at=1760000000,
            ingested_at=1760000000, media_type="text", author_name="Sergey",
            tg_message_id=862)
        assert await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=862) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_asap5_reply_targets_exact_media_not_neighbor(tmp_path):
    """INTEGRATION (ASAP5 §11): reply направляет обработку именно на
    адресованное медиа: фото → его актив; видео/GIF → ЕГО обложку; соседние
    файлы не подмешиваются."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        await mca_vision.register_intake_assets(
            db, _asap5_photo_message(871, serial=1))
        await mca_vision.register_intake_assets(
            db, _asap5_photo_message(872, serial=2))
        await mca_vision.register_intake_assets(
            db, _asap5_video(873, serial=3))
        await mca_vision.register_intake_assets(
            db, _asap5_animation(874, serial=4))
        r = await mca_vision.resolve_target_assets(db, chat_id=CHAT,
                                                   reply_tg_id=872)
        assert r["status"] == "ok"
        assert r["assets"][0]["asset_id"] == mca_vision.make_asset_id(
            CHAT, 872, "uniq_2", "large")
        r = await mca_vision.resolve_target_assets(db, chat_id=CHAT,
                                                   reply_tg_id=873)
        assert r["status"] == "ok"
        preview = r["assets"][0]
        assert preview["asset_kind"] == mca_vision.ASSET_KIND_VIDEO_PREVIEW
        assert preview["tg_message_id"] == 873          # не соседний файл
        assert preview["file_id"] == "asap_thumb_fid_3"
        # reply на GIF → обложка ИМЕННО этого GIF (§10: корректное
        # визуальное представление); байты mp4 — честный unsupported-хвост
        r = await mca_vision.resolve_target_assets(db, chat_id=CHAT,
                                                   reply_tg_id=874)
        assert r["status"] == "ok"
        assert r["assets"][0]["asset_kind"] == \
            mca_vision.ASSET_KIND_ANIMATION_PREVIEW
        assert r["assets"][0]["tg_message_id"] == 874
        assert r["assets"][0]["file_id"] == "asap_thumb_fid_4"
        assert [a["asset_kind"] for a in r["unsupported"]] == ["animation"]
    finally:
        await db.close()


def test_asap5_animation_preview_distinct_and_honest():
    """CONTRACT (ASAP5 §9/§10): обложки GIF/TGS/WebM регистрируются как
    отдельные растровые кандидаты (kind animation_preview), file_id —
    обложки; без обложки — только честный unsupported-источник."""
    gif = _asap5_animation(824, serial=4)
    cands = mca_vision.extract_image_assets(gif)
    assert [(c["asset_kind"], c["size_variant"]) for c in cands] == [
        ("animation", "animation"),
        (mca_vision.ASSET_KIND_ANIMATION_PREVIEW, "animation_preview")]
    assert cands[1]["file_id"] == "asap_thumb_fid_4"
    assert cands[1]["file_id"] != getattr(gif.animation, "file_id")
    # TGS/WebM с обложкой: источник + preview; статический стикер — без preview
    tgs = _asap5_sticker(825, is_animated=True, with_thumb=True)
    kinds = [(c["asset_kind"], c["size_variant"])
             for c in mca_vision.extract_image_assets(tgs)]
    assert kinds == [("animation", "sticker"),
                     (mca_vision.ASSET_KIND_ANIMATION_PREVIEW,
                      "sticker_preview")]
    static = _asap5_sticker(826)
    kinds = [c["asset_kind"] for c in mca_vision.extract_image_assets(static)]
    assert kinds == ["sticker"]
    # GIF без обложки — только честный unsupported-источник (ничего не выдумываем)
    bare = _asap5_animation(827, serial=7, with_thumb=False)
    kinds = [c["asset_kind"] for c in mca_vision.extract_image_assets(bare)]
    assert kinds == ["animation"]
    ids = {c["asset_kind"]: c for c in mca_vision.extract_image_assets(gif)}
    vid = mca_vision.make_asset_id(CHAT, 851, "asap_thumb_uniq_1",
                                   "video_preview")
    anim = mca_vision.make_asset_id(
        CHAT, 824, ids[mca_vision.ASSET_KIND_ANIMATION_PREVIEW
                       ]["file_unique_id"], "animation_preview")
    assert vid != anim


@pytest.mark.asyncio
async def test_asap5_animation_preview_render_honesty(tmp_path):
    """CONTRACT (ASAP5 §10): при проанализированной обложке GIF рендер даёт
    честную заметку «превью анимации, движение не анализируется» и НЕ даёт
    противоречивую строку «не применимо»; без обложки — честная строка
    D18 сохраняется."""
    from services import message_identity
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        # GIF с обложкой: intake → job → ready → рендер
        msg = _asap5_animation(831, serial=1)
        assets = await mca_vision.register_intake_assets(db, msg)
        assert len(assets) == 2          # источник (unsupported) + обложка
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        store = await _store(db)
        for jid in [j["job_id"] for j in await _active_vision(db, "queued")]:
            job = await _claimed_job(db, jid)
            import json as _json
            payload = _json.loads(str(job.get("payload") or "{}"))
            if payload.get("file_id") == "asap_thumb_fid_1":
                await mca_vision.process_asset_job(
                    job, db=db,
                    bot=_FakeBot({"asap_thumb_fid_1": make_png()}),
                    transport=Transport(default=(200, ASYNC_ANALYSIS_BODY)))
            else:
                # mp4-байты GIF не валидны как изображение — честный fail
                await mca_vision.process_asset_job(
                    job, db=db, bot=_FakeBot({}), transport=Transport(
                        default=(200, ASYNC_ANALYSIS_BODY)))
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text=None, caption=None,
            timestamp=1760000000, sent_at=1760000000, ingested_at=1760000000,
            media_type="animation", author_name="Sergey", tg_message_id=831)
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=831)
        assert rendered is not None
        assert mca_vision.ANIMATION_PREVIEW_NOTE in rendered["lines"]
        assert "не применимо" not in rendered["text"]
        assert rendered["visual_descriptions"]
        # GIF без обложки: честная строка D18 сохраняется
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text=None, caption=None,
            timestamp=1760000000, sent_at=1760000000, ingested_at=1760000000,
            media_type="animation", author_name="Sergey", tg_message_id=832)
        bare = _asap5_animation(832, serial=2, with_thumb=False)
        await mca_vision.register_intake_assets(db, bare)
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=832)
        assert rendered is not None
        assert "не применимо" in rendered["text"]
        assert rendered["visual_descriptions"] == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_asap5_album_mixed_media_fields_preserved(tmp_path):
    """INTEGRATION (ASAP5 §11): медиагруппа (фото+фото+видео) — у каждого
    актива сохраняются chat_id, message_id, asset_id, file_id и связь с
    исходным сообщением через media_group_id; caption не теряется из
    реестра (хранится в smart_messages)."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        group = "asap-grp-88"
        msgs = (_asap5_photo_message(881, serial=1, caption="подпись альбома",
                                     media_group_id=group),
                _asap5_photo_message(882, serial=2, media_group_id=group),
                _asap5_video(883, serial=3, media_group_id=group))
        ids: set[str] = set()
        for m in msgs:
            ids.update(await mca_vision.register_intake_assets(db, m))
        assert len(ids) == 3                   # каждый item — свой актив
        for tg, serial, kind in ((881, 1, "photo"), (882, 2, "photo"),
                                 (883, 3, mca_vision.ASSET_KIND_VIDEO_PREVIEW)):
            for row in await db.get_media_assets_for_message(CHAT, tg):
                assert row["chat_id"] == CHAT
                assert row["tg_message_id"] == tg
                assert row["media_group_id"] == group
                assert row["asset_id"] == mca_vision.make_asset_id(
                    CHAT, tg, row["file_unique_id"], row["size_variant"])
                assert row["file_id"]
                if kind == "photo":
                    assert row["asset_kind"] == "photo"
        # повторный observer того же сообщения — идемпотентно (без дублей)
        again = await mca_vision.register_intake_assets(db, msgs[0])
        assert again == [mca_vision.make_asset_id(CHAT, 881, "uniq_1",
                                                  "large")]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_asap5_bot_media_intake_via_observer(tmp_path):
    """INTEGRATION (ASAP5 REQ-MEDIA-PIPELINE, шов 1): медиа, созданное самим
    ботом (observer скипает собственные сообщения), регистрируется в
    каноническом intake-реестре ТЕМ ЖЕ путём, что медиа пользователей
    (register_intake_assets → durable-очередь); строка бота в контент чата
    НЕ пишется (прежний дизайн); автор актива — честно бот (payload
    user_id = bot id); representation доступна tool-пути (reply-target →
    готовый анализ). Новый пайплайн не создаётся."""
    from aiogram.dispatcher.event.bases import UNHANDLED
    import handlers.summary as summary_mod
    from aiogram.types import Chat, Message, PhotoSize, User
    import datetime as _dt
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        bot_msg = Message(
            message_id=884,
            date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
            chat=Chat(id=CHAT, type="supergroup", title="T"),
            from_user=User(id=999, is_bot=True, first_name="Bot"),
            photo=[PhotoSize(file_id="fid_9", file_unique_id="uniq_9",
                             width=800, height=600, file_size=12345)])
        summary_mod._db = db
        summary_mod._aliases = types.SimpleNamespace(resolve=lambda *a, **k: "")
        summary_mod._bot_id = 999
        try:
            result = await summary_mod.summary_observer(bot_msg)
        finally:
            summary_mod._db = None
            summary_mod._aliases = None
            summary_mod._bot_id = None
        assert result is UNHANDLED
        # (1) прежний дизайн сохранён: сообщение бота НЕ в контенте чата
        assert await db.get_smart_window(CHAT, 0, 10) == []
        # (2) актив зарегистрирован тем же intake-путём
        rows = await db.get_media_assets_for_message(CHAT, 884)
        assert len(rows) == 1
        row = rows[0]
        assert row["chat_id"] == CHAT and row["tg_message_id"] == 884
        assert row["asset_kind"] == "photo"
        assert row["file_id"] == "fid_9"
        assert row["message_key"] == f"{CHAT}:884"
        # (3) автор — бот: durable job несёт user_id = bot id (provenance)
        await mca_vision.enqueue_intake_jobs(db, bot_msg, [row["asset_id"]])
        queued = await _active_vision(db, "queued")
        assert queued
        payload = json.loads(str(queued[0].get("payload") or "{}"))
        assert payload.get("user_id") == 999
        # (4) representation: job → ready → tool-путь резолвит именно этот
        # актив без ручного пересказа содержимого
        jid = queued[0]["job_id"]
        job = await _claimed_job(db, jid)
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_9": make_png()}),
            transport=Transport(default=(200, ASYNC_ANALYSIS_BODY)))
        res = await mca_vision.recognize_target(
            db, chat_id=CHAT, reply_tg_id=884, wait_seconds=0)
        assert res["status"] == "ready"
        assert res["asset_id"] == row["asset_id"]
        assert res["asset_kind"] == "photo"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_asap5_bot_text_message_not_intake_not_saved(tmp_path):
    """CONTRACT (шов 1 границы): текстовое сообщение бота — прежнее
    поведение байт-в-байт: ни строки контента, ни активов."""
    from aiogram.dispatcher.event.bases import UNHANDLED
    import handlers.summary as summary_mod
    from aiogram.types import Chat, Message, User
    import datetime as _dt
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        bot_text = Message(
            message_id=885,
            date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
            chat=Chat(id=CHAT, type="supergroup", title="T"),
            from_user=User(id=999, is_bot=True, first_name="Bot"),
            text="я бот, это мой текст")
        summary_mod._db = db
        summary_mod._aliases = types.SimpleNamespace(resolve=lambda *a, **k: "")
        summary_mod._bot_id = 999
        try:
            result = await summary_mod.summary_observer(bot_text)
        finally:
            summary_mod._db = None
            summary_mod._aliases = None
            summary_mod._bot_id = None
        assert result is UNHANDLED
        assert await db.get_smart_window(CHAT, 0, 10) == []
        assert await db.get_media_assets_for_message(CHAT, 885) == []
    finally:
        await db.close()