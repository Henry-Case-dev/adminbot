"""VISION-DL-FIX (ACCEPTANCE-92C): локальный Bot API — путь скачивания файлов.

Прод-факт (2.58.92): `getFile` локального сервера отдаёт АБСОЛЮТНЫЙ путь
КОНТЕЙНЕРА (`/var/lib/telegram-bot-api/<token>/photos/file_N.jpg`), aiogram при
`is_local=True` читает его с ФС ХОСТА → `FileNotFoundError` на `stage=download`
(64 skipped + 32 failed, `mca_media_analyses` пуст). HTTP-эндпоинт скачивания
локального сервера в `--local` не обслуживается (404 — прод-проба
`evidence/dl-fix/prod-diag-2026-10-19.json`), поэтому фикс — маппинг пути
контейнера на host-каталог bind-mount (`TELEGRAM_API_FILES_DIR`).

Тесты: конфиг-инвариант сессии (локальная API-база, `is_local=True`, путь
маппится, облачной базы нет) + контрактный тест на РЕАЛЬНОМ коде aiogram
(`Bot.download_file` читает host-путь, а не контейнерный) + fail-safe
обёртки на неожиданных формах пути.
TEST-LIFECYCLE: CONTRACT owner=P0V-PIPE-E2E/dl-fix (путь скачивания локального
Bot API); TEST-LIFECYCLE: REGRESSION owner=ACCEPTANCE-92C (stage=download).
"""
import io
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.types import File

from config.settings import settings
from services import local_bot_api as lba

TOKEN = "8802473181:TESTTOKENforLOCALbotAPIunit"
CONTAINER = "/var/lib/telegram-bot-api"


def _container_path(name: str = "photos/file_1317.jpg") -> str:
    return "%s/%s/%s" % (CONTAINER, TOKEN, name)


def test_session_config_invariant_local_base_and_host_mapping(tmp_path):
    """Конфиг-инвариант: API-база — ЛОКАЛЬНАЯ (не api.telegram.org),
    `is_local=True`, файловый путь маппится на host-каталог."""
    session = lba.build_local_api_session("http://localhost:8081",
                                          files_dir=tmp_path)
    api = session.api
    assert api.is_local is True
    assert api.base == "http://localhost:8081/bot{token}/{method}"
    assert "api.telegram.org" not in api.base
    assert api.file == "http://localhost:8081/file/bot{token}/{path}"
    mapped = api.wrap_local_file.to_local(_container_path())
    assert mapped == str(Path(tmp_path) / TOKEN / "photos/file_1317.jpg")
    # обратный маппинг (симметрия интерфейса FilesPathWrapper)
    assert api.wrap_local_file.to_server(mapped) == _container_path()


def test_wrapper_failsafe_for_unexpected_paths(tmp_path):
    """Fail-safe: относительный/чужой абсолютный/сам корень — без исключений
    (прежнее поведение), а не ValueError как у SimpleFilesPathWrapper."""
    w = lba.HostFilesPathWrapper(CONTAINER, tmp_path)
    assert w.to_local("photos/file_1.jpg") == "photos/file_1.jpg"
    assert w.to_local("/opt/other/file.jpg") == "/opt/other/file.jpg"
    assert w.to_local(CONTAINER) == CONTAINER
    assert w.to_local("") == ""
    assert w.to_local(None) is None
    assert w.to_server("relative/path.jpg") == "relative/path.jpg"


@pytest.mark.asyncio
async def test_download_reads_host_path_not_container_path(tmp_path,
                                                           monkeypatch):
    """CONTRACT (реальный код aiogram 3.31): `Bot.download_file` читает файл из
    host-каталога bind-mount по контейнерному `file_path`; без маппинга тот же
    вызов падает FileNotFoundError (RED прод-симптома).

    Каталог токена в тесте без ':' (Windows не умеет ':' в именах) — маппинг
    прод-формы `<bot_id>:<token>` проверяется отдельно в конфиг-инварианте."""
    token = "8802473181:AAHfakeTokEnForUnitTests"
    token_dir = "8802473181_AAHfakeTokEnForUnitTests"
    payload = b"\xff\xd8\xff\xe0test-bytes-local-bot-api"
    host_root = tmp_path / "docker-telegram-bot-api"
    target = host_root / token_dir / "photos"
    target.mkdir(parents=True)
    (target / "file_1317.jpg").write_bytes(payload)
    container_path = "%s/%s/photos/file_1317.jpg" % (CONTAINER, token_dir)

    tg_file = File(file_id="fid", file_unique_id="uniq",
                   file_size=len(payload), file_path=container_path)

    # 1) фикс: сессия с маппингом контейнер → host
    session = lba.build_local_api_session("http://localhost:8081",
                                          files_dir=host_root)
    bot = Bot(token=token, session=session)

    async def _fake_get_file(file_id):
        return tg_file

    monkeypatch.setattr(bot, "get_file", _fake_get_file)
    buf = io.BytesIO()
    await bot.download(tg_file, destination=buf)
    assert buf.getvalue() == payload
    await bot.session.close()

    # 2) прежнее поведение (без маппинга) — тот же вызов не находит файл
    from aiogram.client.telegram import TelegramAPIServer
    bare = Bot(token=token, session=lba.AiohttpSession(
        api=TelegramAPIServer.from_base("http://localhost:8081",
                                        is_local=True)))
    monkeypatch.setattr(bare, "get_file", _fake_get_file)
    with pytest.raises(FileNotFoundError):
        await bare.download(tg_file, destination=io.BytesIO())
    await bare.session.close()


def test_host_files_root_resolves_relative_to_app_dir(tmp_path):
    """`TELEGRAM_API_FILES_DIR` относительный → резолвится от каталога
    приложения (не от cwd процесса), абсолютный — как есть."""
    root = lba.host_files_root("docker/telegram-bot-api", app_dir=tmp_path)
    assert root == tmp_path / "docker" / "telegram-bot-api"
    # абсолютный путь — без изменений
    assert lba.host_files_root(tmp_path) == tmp_path
    # дефолт settings (прод: 'docker/telegram-bot-api') — относительный
    assert lba.host_files_root(app_dir=tmp_path) == \
        tmp_path / "docker" / "telegram-bot-api"


def test_files_dir_readable_probe(tmp_path):
    """Диагностика читаемости host-каталога (startup-лог, без исключений)."""
    assert lba.local_files_dir_readable(tmp_path) is True
    assert lba.local_files_dir_readable(tmp_path / "nope") is False


def test_bot_py_uses_local_api_session_factory():
    """Конфиг-инвариант bot.py: локальный режим собирается фабрикой
    `build_local_api_session` (маппинг пути контейнера на host-каталог), а не
    голым `TelegramAPIServer.from_base(..., is_local=True)` — иначе возврат
    прод-дефекта stage=download (FileNotFoundError на контейнерном пути)."""
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    assert "build_local_api_session" in src, \
        "bot.py: локальная сессия должна собираться фабрикой"
    assert "TelegramAPIServer.from_base" not in src, \
        "bot.py: голый from_base(is_local=True) — дефект stage=download"


@pytest.mark.asyncio
async def test_local_server_scenario_end_to_end(tmp_path):
    """INTEGRATION (bounded, локально): реальный HTTP-путь локального Bot API —
    `getFile` по локальной базе отдаёт АБСОЛЮТНЫЙ контейнерный путь, сессия
    читает файл из host-каталога; HTTP-эндпоинт скачивания `/file/bot…`
    отвечает 404 (прод-факт: в `--local` он не обслуживается)."""
    from aiohttp import web

    token = "8802473181:AAHfakeTokEnForUnitTests"
    token_dir = "8802473181_AAHfakeTokEnForUnitTests"
    payload = b"\xff\xd8\xff\xe0integration-local-bot-api"
    host_root = tmp_path / "docker-telegram-bot-api"
    target = host_root / token_dir / "photos"
    target.mkdir(parents=True)
    (target / "file_7.jpg").write_bytes(payload)
    container_path = "%s/%s/photos/file_7.jpg" % (CONTAINER, token_dir)

    seen: dict = {}

    async def _get_file(request):
        seen["path"] = request.path
        return web.json_response({"ok": True, "result": {
            "file_id": "fid7", "file_unique_id": "uniq7",
            "file_size": len(payload), "file_path": container_path}})

    async def _not_found(request):
        seen["file_endpoint"] = request.path
        return web.json_response(
            {"ok": False, "error_code": 404, "description": "Not Found"},
            status=404)

    app = web.Application()
    # aiogram отправляет методы Bot API POST-запросом (JSON body)
    app.router.add_post("/bot{token}/getFile", _get_file)
    app.router.add_get("/file/bot{token}/{path:.*}", _not_found)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        session = lba.build_local_api_session("http://127.0.0.1:%d" % port,
                                              files_dir=host_root)
        bot = Bot(token=token, session=session)
        buf = io.BytesIO()
        await bot.download("fid7", destination=buf)     # getFile + ФС-чтение
        assert buf.getvalue() == payload
        assert seen["path"].endswith("/getFile")
        await bot.session.close()

        # HTTP-эндпоинт файлов локального сервера в --local = 404
        import aiohttp
        async with aiohttp.ClientSession() as raw:
            url = "http://127.0.0.1:%d/file/bot%s%s" % (port, token,
                                                        container_path)
            async with raw.get(url) as resp:
                assert resp.status == 404
                assert resp.status != 200
    finally:
        await runner.cleanup()
