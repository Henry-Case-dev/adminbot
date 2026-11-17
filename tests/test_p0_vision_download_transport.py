"""P0 Vision download (LVS-VIS-02/03/04/07) — единый local/cloud транспорт
и честная классификация ошибок получения файла Bot API.

Контракт (карта `plans/features/llm-vision-scheduler-p0/requirements-map.json`,
owner input §2):

  * LVS-VIS-02 — Vision получает байты через ЕДИНЫЙ транспорт
    `services.media_download.download_api_file_bytes` (local file path →
    bytes, container/relative path, cloud fallback), а не собственную пару
    `bot.get_file` + `bot.download`; голос/видео/аватары не затронуты;
  * LVS-VIS-03 — вместо общего `except Exception → vision_unavailable`
    визны стадии `get_file`/`local_read`/`cloud_download`/`validate` и
    классы (`missing_local_file`, `permission_denied`, `invalid_file_id`,
    `timeout`, `network`, `oversized`, `unreadable_raster`,
    `provider_error`); причина доезжает до `vision.media` события
    (`error_json`), очереди (`task_jobs.error_code`) и чекапа
    (`runtime_snapshot.last_error`); R17 — без байтов/путей с токеном/URL;
  * LVS-VIS-04 — семантика breaker: ошибка скачивания = сбой (streak++),
    успех = сброс, контент-детерминированный исход нейтрален; открытый
    breaker не мешает последующему успешному cloud fallback;
  * LVS-VIS-05 — retry/requeue не теряют джобу, CAS/idempotency не
    дублируют обработку;
  * LVS-VIS-06 — готовое описание попадает в контекст потребителя без
    нового пользовательского запроса и без нового вызова провайдера.

Оффлайн: внешние вызовы — только контрактные двойники транспорта
(`Transport` провайдера, `cloud_fetcher`/`_default_cloud_fetch`), сеть не
используется; локальный Bot API моделируется реальным каталогом `tmp_path`.
TEST-LIFECYCLE: CONTRACT owner=P0-VISION-DL (LVS-VIS-02/03);
TEST-LIFECYCLE: REGRESSION owner=LVS-VIS-04 (breaker), LVS-VIS-05 (retry/CAS),
LVS-VIS-06 (downstream-контекст), LVS-VIS-07 (матрица классов).
"""
import asyncio
import dataclasses
import json
import logging
import struct
import time
import types
import zlib
from contextlib import contextmanager
from pathlib import Path

import pytest
from aiogram.types import Chat, File, Message, PhotoSize, User

from config.settings import settings as real_settings
from services import media_download as md
from services import mca_vision
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

CHAT = -1005550777
BOT_ID = 4242
TOKEN = "4242:p0-vision-download-test-token"
TOKEN_DIR = TOKEN                       # local_files_subdir: '<bot_id>:<secret>'
CONTAINER_ROOT = "/var/lib/telegram-bot-api"


# ═════════════════════ общие двойники/фикстуры ═════════════════════════════

@contextmanager
def patched_settings(**kw):
    """Временная подмена Settings-полей (сеть/каталог/флаги)."""
    saved = {k: getattr(real_settings, k) for k in kw}
    for key, value in kw.items():
        object.__setattr__(real_settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(real_settings, key, value)


@pytest.fixture(autouse=True)
def _clean_runtime():
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    yield
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()


@pytest.fixture(autouse=True)
def _vision_env(monkeypatch):
    """K1 ON, основная модель/ключ заданы, Vision-поля пусты; облачный
    fallback по умолчанию ВЫКЛЮЧЕН, чтобы ни один тест не ходил в сеть."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "0")
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY="", VISION_API_BASE_URL="",
                          VISION_MODEL="",
                          VISION_API_TYPE="openai_compatible"):
        yield


class _VirtualRoot:
    """Виртуальный host-каталог локального Bot API.

    Каталог токена называется '<bot_id>:<token>' — на Windows такой каталог
    физически создать нельзя, поэтому файлы моделируются на уровне ФС-границы
    (`Path.stat`/`Path.read_bytes`), а ВСЯ логика транспорта
    (`local_file_path` → stat/read → класс ошибки) выполняется по-настоящему."""

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, bytes] = {}
        self.denied: set[str] = set()

    def path(self, rel: str) -> Path:
        return self.root / TOKEN_DIR / rel

    def put(self, rel: str, data: bytes) -> Path:
        target = self.path(rel)
        self.files[_key(target)] = data
        return target

    def deny(self, rel: str) -> Path:
        target = self.path(rel)
        self.denied.add(_key(target))
        return target


def _key(path) -> str:
    return str(path).replace("\\", "/").lower()


@pytest.fixture
def files_root(tmp_path, monkeypatch) -> _VirtualRoot:
    """host-каталог локального Bot API (+ подмена настроек транспорта)."""
    root = tmp_path / "tgapi"
    root.mkdir(parents=True, exist_ok=True)
    cfg = dataclasses.replace(real_settings,
                              TELEGRAM_API_FILES_DIR=str(root),
                              API_TOKEN=TOKEN)
    monkeypatch.setattr(md, "settings", cfg)
    vroot = _VirtualRoot(root)
    real_stat = Path.stat
    real_read = Path.read_bytes
    prefix = _key(root) + "/"

    def _is_virtual(path) -> bool:
        return _key(path).startswith(prefix)

    def fake_stat(self, *args, **kwargs):
        key = _key(self)
        if _is_virtual(self):
            if key in vroot.denied:
                raise PermissionError(13, "Permission denied", str(self))
            if key in vroot.files:
                return types.SimpleNamespace(st_size=len(vroot.files[key]))
            # Детерминированная модель локального Bot API: файла нет
            # (на Windows путь с '<bot_id>:<token>' — валидный синтаксис ADS,
            # поэтому ошибка ФС здесь не делегируется ОС).
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    def fake_read(self, *args, **kwargs):
        key = _key(self)
        if _is_virtual(self):
            if key in vroot.denied:
                raise PermissionError(13, "Permission denied", str(self))
            if key in vroot.files:
                return vroot.files[key]
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(Path, "read_bytes", fake_read)
    return vroot


def make_png(width: int = 12, height: int = 12, fill: bytes = b"\x10\x20\x30"
             ) -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))

    row = b"\x00" + fill * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0,
                                         0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


class _Session:
    def __init__(self, is_local: bool):
        self.api = types.SimpleNamespace(is_local=is_local)


class _Bot:
    """Двойник bot с сессией: local-mode читает диск, cloud — HTTP.

    `download_file` в локальном режиме ведёт себя как aiogram: читает путь с
    диска через `wrap_local_file` (здесь — фиксированный FileNotFoundError,
    если файл не найден транспортом раньше)."""

    def __init__(self, *, local: bool = True, file_path="photos/a.png",
                 get_file_exc: BaseException | None = None,
                 download_exc: BaseException | None = None,
                 download_bytes: bytes | None = None, token: str = TOKEN):
        self.session = _Session(local)
        self.token = token
        self.id = BOT_ID
        self.file_path = file_path
        self.get_file_exc = get_file_exc
        self.download_exc = download_exc
        self.download_bytes = download_bytes
        self.get_file_calls = 0
        self.download_file_calls = 0

    async def get_file(self, file_id):
        self.get_file_calls += 1
        if self.get_file_exc is not None:
            raise self.get_file_exc
        return File(file_id=str(file_id), file_unique_id="uniq",
                    file_path=self.file_path)

    async def download_file(self, file_path, destination=None, timeout=30):
        self.download_file_calls += 1
        if self.download_exc is not None:
            raise self.download_exc
        if self.download_bytes is None:
            raise FileNotFoundError(str(file_path))
        destination.write(self.download_bytes)

    async def download(self, file, destination=None):
        target = getattr(file, "file_id", file)
        if self.download_exc is not None:
            raise self.download_exc
        if self.download_bytes is None:
            raise FileNotFoundError(str(target))
        destination.write(self.download_bytes)


def _put(vroot: _VirtualRoot, rel: str, data: bytes) -> Path:
    return vroot.put(rel, data)


class _CloudOk:
    """Двойник облачного fallback: фиксирует аргументы, отдаёт байты."""

    def __init__(self, data: bytes):
        self.data = data
        self.calls: list[dict] = []

    async def __call__(self, token, file_id, rel_path, *, timeout, max_bytes):
        self.calls.append({"token": token, "file_id": file_id,
                           "rel": rel_path, "timeout": timeout,
                           "max_bytes": max_bytes})
        return self.data


# ═══════════════════ A. Единый транспорт (LVS-VIS-02/03/07) ════════════════

@pytest.mark.asyncio
async def test_local_relative_path_returns_bytes_single_read(files_root):
    """Локальный Bot API + относительный file_path → байты с диска.

    Единый транспорт: `bot.download_file` (второе чтение) не вызывается —
    диск читается ровно один раз через `local_file_path`."""
    payload = make_png()
    _put(files_root, "photos/a.png", payload)
    bot = _Bot(local=True, file_path="photos/a.png")
    data = await md.download_api_file_bytes(bot, "fid", site="vision",
                                            attempts=1)
    assert data == payload
    assert bot.download_file_calls == 0
    assert bot.get_file_calls == 1


@pytest.mark.asyncio
async def test_container_path_maps_to_host_root(files_root):
    """Контейнерный абсолютный путь (`/var/lib/telegram-bot-api/<token>/…`,
    как отдаёт `--local`) нормализуется к host-корню."""
    payload = make_png(14, 14, b"\x01\x02\x03")
    _put(files_root, "photos/b.png", payload)
    bot = _Bot(local=True,
               file_path=f"{CONTAINER_ROOT}/{TOKEN_DIR}/photos/b.png")
    data = await md.download_api_file_bytes(bot, "fid", site="vision",
                                            attempts=1)
    assert data == payload


@pytest.mark.asyncio
async def test_host_absolute_path_inside_root(files_root):
    """Host-абсолютный путь внутри TELEGRAM_API_FILES_DIR — допустим."""
    payload = make_png(9, 9)
    target = _put(files_root, "photos/c.png", payload)
    bot = _Bot(local=True, file_path=str(target))
    data = await md.download_api_file_bytes(bot, "fid", site="vision",
                                            attempts=1)
    assert data == payload


@pytest.mark.asyncio
async def test_missing_local_file_uses_cloud_fallback(files_root, monkeypatch):
    """Файла нет на диске → облачный fallback (LVS-VIS-02/07).

    Локальный Bot API в `--local` не отдаёт файлы по HTTP, поэтому промах
    диска — не приговор: транспорт добирает байты из облака, путь в облако
    относительный (без каталога токена)."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    payload = make_png(16, 16)
    cloud = _CloudOk(payload)
    bot = _Bot(local=True, file_path="photos/gone.png")
    diag: dict = {}
    data = await md.download_api_file_bytes(bot, "fid", site="vision",
                                            attempts=2, sleep=0,
                                            cloud_fetcher=cloud,
                                            diagnostics=diag)
    assert data == payload
    assert cloud.calls and cloud.calls[0]["rel"] == "photos/gone.png"
    assert TOKEN_DIR not in cloud.calls[0]["rel"]
    assert diag["outcome"] == "cloud_fallback"


@pytest.mark.asyncio
async def test_missing_local_file_classified_without_cloud(files_root):
    """Cloud выключен → честный класс `missing_local_file` (не «unknown»).

    R17: текст исключения — только stage:class, без пути и токена."""
    bot = _Bot(local=True, file_path="photos/gone.png")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=2, sleep=0)
    exc = ei.value
    assert (exc.stage, exc.error_class) == (md.STAGE_LOCAL_READ,
                                            md.ERROR_MISSING_LOCAL_FILE)
    assert exc.retryable is True
    assert str(exc) == "local_read:missing_local_file"
    assert TOKEN not in str(exc) and "photos" not in str(exc)


@pytest.mark.asyncio
async def test_invalid_file_id_is_permanent_and_skips_cloud(files_root,
                                                            monkeypatch):
    """`get_file` «invalid file identifier» → постоянный класс; облако не
    вызывается (повтор/фолбэк не помогут)."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    cloud = _CloudOk(make_png())

    class _BadRequest(Exception):
        pass

    bot = _Bot(local=True,
               get_file_exc=_BadRequest(
                   "Bad Request: invalid file identifier specified"))
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=2, sleep=0,
                                         cloud_fetcher=cloud)
    assert ei.value.error_class == md.ERROR_INVALID_FILE_ID
    assert ei.value.retryable is False
    assert cloud.calls == []


@pytest.mark.asyncio
async def test_timeout_class(files_root):
    """Таймаут Bot API — отдельный класс `timeout` (не «provider_error»)."""
    bot = _Bot(local=True, get_file_exc=asyncio.TimeoutError())
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=1, sleep=0)
    assert ei.value.stage == md.STAGE_GET_FILE
    assert ei.value.error_class == md.ERROR_TIMEOUT


@pytest.mark.asyncio
async def test_permission_denied_class(files_root):
    """Права на файл → `permission_denied` (не «missing» и не «unknown»)."""
    files_root.put("photos/b.png", make_png())
    files_root.deny("photos/b.png")
    bot = _Bot(local=True, file_path="photos/b.png")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=1, sleep=0)
    assert ei.value.error_class == md.ERROR_PERMISSION_DENIED
    assert TOKEN not in str(ei.value)


@pytest.mark.asyncio
async def test_local_oversized_is_permanent(files_root):
    """Оversize локального файла — постоянный класс `oversized`, без облака."""
    _put(files_root, "photos/big.png", make_png(20, 20))
    bot = _Bot(local=True, file_path="photos/big.png")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=1, sleep=0,
                                         max_bytes=32)
    assert ei.value.error_class == md.ERROR_OVERSIZED
    assert ei.value.retryable is False
    assert "32" in ei.value.detail


@pytest.mark.asyncio
async def test_cloud_oversized_and_network_classes(files_root, monkeypatch):
    """Классы облачного fallback: oversized (постоянный) и network."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    bot = _Bot(local=True, file_path="photos/gone.png")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=1, sleep=0, max_bytes=8,
                                         cloud_fetcher=_CloudOk(make_png()))
    assert ei.value.stage == md.STAGE_CLOUD_DOWNLOAD
    assert ei.value.error_class == md.ERROR_OVERSIZED

    class _Unreachable:
        async def __call__(self, *a, **kw):
            raise ConnectionError("dns failure")

    with pytest.raises(md.MediaDownloadError) as ei2:
        await md.download_api_file_bytes(bot, "fid", site="vision",
                                         attempts=1, sleep=0,
                                         cloud_fetcher=_Unreachable())
    assert ei2.value.error_class == md.ERROR_NETWORK


@pytest.mark.asyncio
async def test_empty_file_id_is_invalid_without_io(files_root):
    bot = _Bot(local=True)
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.download_api_file_bytes(bot, "", site="vision", attempts=1)
    assert ei.value.stage == md.STAGE_GET_FILE
    assert ei.value.error_class == md.ERROR_INVALID_FILE_ID
    assert bot.get_file_calls == 0


def test_cloud_relative_path_strips_token_and_rejects_traversal(files_root):
    """Путь в облако — относительный, без каталога токена; `..` запрещён."""
    bot = _Bot(local=True)
    assert md.cloud_relative_path(
        bot, f"{CONTAINER_ROOT}/{TOKEN_DIR}/photos/a.png") == "photos/a.png"
    assert md.cloud_relative_path(
        bot, f"/srv/adminbot/docker/telegram-bot-api/{TOKEN_DIR}/photos/a.png"
    ) == "photos/a.png"
    assert md.cloud_relative_path(bot, "photos/a.png") == "photos/a.png"
    assert md.cloud_relative_path(bot, "../../etc/passwd") is None
    assert md.cloud_relative_path(bot, "") is None


def test_safe_path_tail_never_contains_token(files_root):
    bot = _Bot(local=True)
    tail = md.safe_path_tail(f"{CONTAINER_ROOT}/{TOKEN_DIR}/photos/a.png")
    assert tail == "photos/a.png"
    assert TOKEN not in tail and ":" not in tail


def test_vision_module_has_no_download_bypass():
    """LVS-VIS-02: у vision нет собственной пары get_file+download — только
    делегация в единый транспорт; токен-URL в сервисе не строится."""
    import inspect
    source = inspect.getsource(mca_vision)
    assert "download_api_file_bytes(" in source
    assert "file/bot" not in source and "/file/bot" not in source
    body = inspect.getsource(mca_vision.download_telegram_file)
    assert "bot.download(" not in body
    assert "bot.get_file(" not in body


def test_error_class_matrix_maps_to_existing_reason_codes():
    """LVS-VIS-03/07: каждый класс транспорта отображается на СУЩЕСТВУЮЩИЙ
    reason_code (словарь 269 не расширяется), подстадии — фиксированный
    набор; постоянные и временные классы различимы."""
    assert set(md.ERROR_CLASSES) == {
        "invalid_file_id", "missing_local_file", "local_read_failed",
        "permission_denied", "timeout", "network", "oversized",
        "unreadable_raster", "provider_error"}
    allowed = {"vision_unavailable", "vision_missing_source",
               "vision_unreadable"}
    for cls in md.ERROR_CLASSES:
        assert mca_vision.download_reason_for(cls) in allowed
    assert mca_vision.download_reason_for(
        md.ERROR_INVALID_FILE_ID) == "vision_missing_source"
    assert mca_vision.download_reason_for(md.ERROR_OVERSIZED) \
        == "vision_unreadable"
    for cls in ("missing_local_file", "permission_denied", "timeout",
                "network", "local_read_failed", "provider_error"):
        assert mca_vision.download_reason_for(cls) == "vision_unavailable"
    assert tuple(mca_vision.DOWNLOAD_SUBSTAGES) == (
        "get_file", "local_read", "cloud_download", "validate")
    # Классы validate: стабильные detail-строки → различимые классы.
    assert mca_vision.validate_error_class(
        "image exceeds 20971520 bytes") == "oversized"
    assert mca_vision.validate_error_class(
        "not a supported raster image") == "unreadable_raster"
    assert mca_vision.validate_error_class(
        "unsupported format image/tiff") == "unsupported_format"
    assert mca_vision.validate_error_class("") == "unreadable_raster"


# ═════════════ C. Пайплайн: классы → событие/очередь/чекап (LVS-VIS-03) ════

async def _fresh_db(tmp_path) -> DatabaseService:
    db = DatabaseService(str(tmp_path / "vision-dl.db"))
    await db.initialize()
    return db


def _cap_ok() -> None:
    mca_vision.store_capability(
        mca_vision.resolve_route(),
        mca_vision.CapabilityVerdict("ok", "", True, time.monotonic()))


def _photo_message(tg_id: int, *, serial: int = 1,
                   group: str | None = None) -> Message:
    import datetime as _dt
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 11, 17, 9, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        media_group_id=group,
        photo=[PhotoSize(file_id=f"fid_{tg_id}_{serial}",
                         file_unique_id=f"uniq_{tg_id}_{serial}",
                         width=800, height=600, file_size=12345)])


async def _enqueue(db, msg: Message) -> tuple[str, str]:
    assets = await mca_vision.register_intake_assets(db, msg)
    assert assets
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    store = TaskJobStore(db)
    queued = [j for j in await store.active()
              if j.get("kind") == mca_vision.VISION_JOB_KIND
              and j.get("status") == "queued"
              and str(json.loads(j.get("payload") or "{}").get("asset_id"))
              == str(assets[0])]
    assert queued, "vision job не поставлена"
    return assets[0], queued[0]["job_id"]


async def _claimed_job(db, job_id: str, *, attempt: int | None = None) -> dict:
    store = TaskJobStore(db)
    assert await store.mark_running(job_id)
    job = await store.get(job_id) or {}
    if attempt is not None:
        job["attempt"] = int(attempt)
    return job


class _Events:
    def __init__(self):
        self.items: list[dict] = []

    def __call__(self, name, **fields):
        self.items.append({"name": name, **fields})
        return None

    def stage(self, stage):
        return [e for e in self.items
                if e["name"] == "vision_media" and e.get("stage") == stage]

    def last(self, stage):
        rows = self.stage(stage)
        return rows[-1] if rows else None


async def _analysis_body(text: str = "тёмный квадрат на светлом фоне") -> dict:
    return {"choices": [{"message": {"content": json.dumps({
        "ocr_blocks": [], "visual_description": text,
        "uncertainty": [], "self_reported_confidence": 0.9})}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 3}}


class _Transport:
    def __init__(self, body: dict | None = None, *, status: int = 200):
        self.body = body
        self.status = status
        self.calls: list[dict] = []

    async def __call__(self, url, *, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload})
        return self.status, self.body


@pytest.mark.asyncio
async def test_download_failure_class_reaches_event_queue_and_checkup(
        tmp_path, files_root, monkeypatch):
    """Отсутствующий локальный файл при выключенном облаке → класс
    `missing_local_file` в событии, durable-строке очереди и чекапе; job
    остаётся в очереди на bounded-retry (не теряется)."""
    events = _Events()
    monkeypatch.setattr("services.mca_events.emit_mca_event", events)
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(501))
        bot = _Bot(local=True, file_path="photos/missing-501.png")
        job = await _claimed_job(db, job_id, attempt=1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=_Transport({}))
        # Первая попытка — bounded retry (событие `skipped`), не терминал.
        retry_event = events.stage("download")[-1]
        assert retry_event["outcome"] == "skipped"
        assert retry_event["reason_code"] == "vision_unavailable"
        assert retry_event["error_json"]["class"] == "missing_local_file"
        assert retry_event["error_json"]["stage"] == "local_read"
        assert retry_event["attempt"] == 1 and retry_event["job_id"] == job_id
        row = await TaskJobStore(db).get(job_id)
        assert row["status"] == "queued"            # retry, не терминал
        assert row["reason_code"] == "vision_unavailable"
        assert row["error_code"] == "missing_local_file"

        # Терминальная попытка (бюджет исчерпан) → чекап видит класс.
        job2 = dict(row)
        job2["attempt"] = mca_vision.JOB_MAX_ATTEMPTS - 1
        await mca_vision.process_asset_job(job2, db=db, bot=bot,
                                          transport=_Transport({}))
        failed = events.last("download")
        assert failed["outcome"] == "failed"
        assert failed["error_json"]["class"] == "missing_local_file"
        row2 = await TaskJobStore(db).get(job_id)
        assert row2["status"] == "failed"
        assert row2["error_code"] == "missing_local_file"
        snapshot = await mca_vision.runtime_snapshot(db=db, chat_id=CHAT)
        assert snapshot["last_error"]["reason_code"] == "vision_unavailable"
        assert snapshot["last_error"]["error_code"] == "missing_local_file"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cloud_fallback_restores_analysis(tmp_path, files_root,
                                                monkeypatch):
    """LVS-VIS-02: файла нет на диске, облако доступно → анализ ГОТОВ.

    Это и есть путь восстановления прод-инцидента: локальный Bot API не
    материализует файл, транспорт добирает байты и vision продолжает работу
    (без нового пользовательского запроса)."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    payload = make_png(18, 18)
    seen: list[str] = []

    async def _cloud(token, file_id, rel_path, *, timeout, max_bytes):
        seen.append(rel_path)
        return payload

    monkeypatch.setattr(md, "_default_cloud_fetch", _cloud)
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(502))
        bot = _Bot(local=True, file_path="photos/missing-502.png")
        transport = _Transport(await _analysis_body("кот на диване"))
        job = await _claimed_job(db, job_id, attempt=1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=transport)
        row = await TaskJobStore(db).get(job_id)
        assert row["status"] == "completed"
        assert seen == ["photos/missing-502.png"]
        assert TOKEN_DIR not in seen[0]
        scope = mca_vision.access_scope_for(CHAT)
        assets = await db.get_media_assets_for_message(CHAT, 502)
        ready = await mca_vision.resolve_ready_for_asset(db, assets[0], scope)
        assert ready is not None and ready["status"] == "ready"
        assert "кот на диване" in str(ready["visual_description"])
        assert len(transport.calls) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_invalid_file_id_is_honest_terminal(tmp_path, files_root,
                                                  monkeypatch):
    """`invalid_file_id` → `vision_missing_source` (постоянно), без retry."""
    events = _Events()
    monkeypatch.setattr("services.mca_events.emit_mca_event", events)
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(503))
        bot = _Bot(local=True,
                   get_file_exc=RuntimeError("Bad Request: file is not found"))
        job = await _claimed_job(db, job_id, attempt=1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=_Transport({}))
        row = await TaskJobStore(db).get(job_id)
        assert row["status"] == "failed"
        assert row["reason_code"] == "vision_missing_source"
        assert row["error_code"] == "invalid_file_id"
        failed = events.last("download")
        assert failed["error_json"]["class"] == "invalid_file_id"
        assert failed["error_json"]["stage"] == "get_file"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unreadable_raster_reports_validate_stage(tmp_path, files_root,
                                                        monkeypatch):
    """Нечитаемый растр → стадия `validate`, класс `unreadable_raster`
    (а не общий `download`); исход нейтрален для breaker."""
    events = _Events()
    monkeypatch.setattr("services.mca_events.emit_mca_event", events)
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(504))
        # Локальный файл есть, но это не изображение.
        _put(files_root, "photos/504.bin", b"MZ\x90\x00 not an image")
        bot = _Bot(local=True, file_path="photos/504.bin")
        job = await _claimed_job(db, job_id, attempt=1)
        mca_vision._RUNTIME["breaker_streak"] = 1
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=_Transport({}))
        row = await TaskJobStore(db).get(job_id)
        assert row["status"] == "failed"
        assert row["reason_code"] == "vision_unreadable"
        assert row["error_code"] == "unreadable_raster"
        failed = events.last("validate")
        assert failed is not None and failed["outcome"] == "failed"
        assert failed["error_json"]["class"] == "unreadable_raster"
        assert failed["error_json"]["stage"] == "validate"
        # Контент-детерминированный отказ НЕ считается сбоем инфраструктуры.
        assert mca_vision._RUNTIME["breaker_streak"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_download_failure_counts_breaker(tmp_path, files_root):
    """LVS-VIS-04: ошибка скачивания = streak++ (а не сброс, как раньше)."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(505))
        bot = _Bot(local=True, file_path="photos/missing-505.png")
        job = await _claimed_job(db, job_id, attempt=1)
        assert mca_vision._RUNTIME["breaker_streak"] == 0
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=_Transport({}))
        assert mca_vision._RUNTIME["breaker_streak"] == 1
    finally:
        await db.close()


# ═══════════════════ D. Breaker (LVS-VIS-04) ═══════════════════════════════

def test_note_breaker_contract():
    """Ошибка → streak++; успех → сброс; порог открывает breaker."""
    mca_vision._note_job_outcome("vision_unavailable")
    mca_vision._note_job_outcome("vision_unavailable")
    assert mca_vision._RUNTIME["breaker_streak"] == 2
    assert not mca_vision.breaker_open()
    mca_vision._note_job_outcome("vision_unavailable")
    assert mca_vision.breaker_open()
    mca_vision._note_job_outcome(None)
    assert mca_vision._RUNTIME["breaker_streak"] == 0
    assert not mca_vision.breaker_open()


def test_note_job_outcome_permanent_is_neutral():
    """Постоянные контентные исходы не считаются сбоем и не сбрасывают."""
    mca_vision._RUNTIME["breaker_streak"] = 2
    for reason in ("vision_unreadable", "vision_unsupported",
                   "vision_missing_source", "vision_failed"):
        mca_vision._note_job_outcome(reason)
    assert mca_vision._RUNTIME["breaker_streak"] == 2


@pytest.mark.asyncio
async def test_breaker_open_pauses_claim_then_success_resets(tmp_path,
                                                             files_root,
                                                             monkeypatch):
    """Открытый breaker приостанавливает pull; после паузы успешный
    cloud-fallback обрабатывает джобу и сбрасывает streak (breaker не мешает
    восстановлению)."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    payload = make_png(22, 22)

    async def _cloud(token, file_id, rel_path, *, timeout, max_bytes):
        return payload

    monkeypatch.setattr(md, "_default_cloud_fetch", _cloud)
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(506))
        bot = _Bot(local=True, file_path="photos/missing-506.png")
        worker = mca_vision.VisionMediaWorker(
            db, bot, transport=_Transport(await _analysis_body("собака")))
        worker._store = TaskJobStore(db)
        worker._sem = asyncio.Semaphore(2)
        mca_vision._RUNTIME.update({"breaker_streak": 3,
                                    "breaker_until":
                                        time.monotonic() + 60.0})
        assert await worker._claim_once() == 0        # pull приостановлен
        assert (await TaskJobStore(db).get(job_id))["status"] == "queued"
        # Пауза истекла → claim работает, cloud fallback даёт успех.
        mca_vision._RUNTIME["breaker_until"] = 0.0
        assert await worker._claim_once() == 1
        await worker.drain(timeout=10.0)
        row = await TaskJobStore(db).get(job_id)
        assert row["status"] == "completed"
        assert mca_vision._RUNTIME["breaker_streak"] == 0
        assert not mca_vision.breaker_open()
    finally:
        await db.close()


# ═══════════ E. Retry/CAS/idempotency + downstream (LVS-VIS-05/06) ═════════

@pytest.mark.asyncio
async def test_repeat_processing_reuses_ready_without_new_call(tmp_path,
                                                              files_root):
    """Повтор той же джобы после успеха: готовый анализ переиспользуется,
    провайдер НЕ вызывается второй раз (idempotency/CAS)."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(507))
        _put(files_root, "photos/507.png", make_png(24, 24))
        bot = _Bot(local=True, file_path="photos/507.png")
        transport = _Transport(await _analysis_body("дом"))
        job = await _claimed_job(db, job_id, attempt=1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=transport)
        assert (await TaskJobStore(db).get(job_id))["status"] == "completed"
        assert len(transport.calls) == 1
        # Повтор (retry/повторный claim того же актива) — кеш, не вызов.
        repeat = dict(job)
        repeat["attempt"] = 2
        await mca_vision.process_asset_job(repeat, db=db, bot=bot,
                                          transport=transport)
        assert len(transport.calls) == 1
        cur = await db.db.execute(
            "SELECT COUNT(*) AS n FROM mca_media_analyses WHERE asset_id=?",
            (asset_id,))
        row = await cur.fetchone()
        assert int(dict(row)["n"]) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_album_two_photos_both_analyzed(tmp_path, files_root):
    """Альбом из двух снимков: обе джобы доходят до ready (нет потери
    sibling'ов), описания не путаются."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        first = _photo_message(601, serial=1, group="alb-1")
        second = _photo_message(602, serial=2, group="alb-1")
        a1, j1 = await _enqueue(db, first)
        a2, j2 = await _enqueue(db, second)
        _put(files_root, "photos/601.png", make_png(26, 26, b"\x01\x01\x01"))
        _put(files_root, "photos/602.png", make_png(27, 27, b"\x02\x02\x02"))
        # Оба sibling'а уже в реестре → grace не продлевается.
        transport = _Transport(await _analysis_body("альбомное фото"))
        for job_id, path in ((j1, "photos/601.png"), (j2, "photos/602.png")):
            bot = _Bot(local=True, file_path=path)
            job = await _claimed_job(db, job_id, attempt=1)
            await mca_vision.process_asset_job(job, db=db, bot=bot,
                                              transport=transport)
        scope = mca_vision.access_scope_for(CHAT)
        for asset_id, tg_id in ((a1, 601), (a2, 602)):
            assets = await db.get_media_assets_for_message(CHAT, tg_id)
            ready = await mca_vision.resolve_ready_for_asset(
                db, assets[0], scope)
            assert ready is not None and ready["status"] == "ready"
        assert len(transport.calls) == 2       # два снимка = два анализа
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_downstream_context_gets_description_without_new_call(
        tmp_path, files_root):
    """LVS-VIS-06: готовое описание попадает в контекст потребителя без
    нового пользовательского запроса и без нового вызова провайдера."""
    db = await _fresh_db(tmp_path)
    try:
        mca_vision.bind_runtime(db)
        _cap_ok()
        asset_id, job_id = await _enqueue(db, _photo_message(508))
        _put(files_root, "photos/508.png", make_png(28, 28))
        bot = _Bot(local=True, file_path="photos/508.png")
        transport = _Transport(await _analysis_body("скриншот переписки"))
        job = await _claimed_job(db, job_id, attempt=1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                          transport=transport)
        from services import message_identity
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=42, text=None, caption=None,
            timestamp=1760000000, sent_at=1760000000, ingested_at=1760000000,
            media_type="photo", author_name="Sergey", tg_message_id=508)
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=508)
        assert rendered is not None
        assert "скриншот переписки" in rendered["text"]
        assert len(transport.calls) == 1       # потребитель не платит повторно
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_download_logs_never_leak_token_or_bytes(tmp_path, files_root,
                                                        monkeypatch, caplog):
    """R17: ни путь с '<bot_id>:<token>', ни URL, ни байты не попадают в
    логи (успех/промах диска/фейл класса)."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    payload = make_png(30, 30)

    async def _cloud(token, file_id, rel_path, *, timeout, max_bytes):
        return payload

    monkeypatch.setattr(md, "_default_cloud_fetch", _cloud)
    with caplog.at_level(logging.WARNING):
        ok_bot = _Bot(local=True, file_path="photos/ok-509.png")
        _put(files_root, "photos/ok-509.png", payload)
        await md.download_api_file_bytes(ok_bot, "fid", site="vision",
                                         attempts=1)
        cloud_bot = _Bot(local=True, file_path="photos/gone-509.png")
        await md.download_api_file_bytes(cloud_bot, "fid", site="vision",
                                         attempts=1)
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert blob, "ожидались WARNING-строки транспорта"
    assert TOKEN not in blob
    assert TOKEN_DIR not in blob
    assert "4242:" not in blob
    assert "api.telegram.org" not in blob
    assert "/var/lib/telegram-bot-api" not in blob
    # Байты/базовое64 не логируются даже частично.
    assert payload[:8].hex() not in blob
    assert payload[:8].decode("latin-1") not in blob
