"""P0 prod-incident F1 (round 10.25): нормализация пути локального Bot API.

`--local` отдаёт АБСОЛЮТНЫЙ контейнерный путь
`/var/lib/telegram-bot-api/<bot_id>:<token>/…`; на хосте каталог смонтирован
как `settings.TELEGRAM_API_FILES_DIR`. Прежний guard отбрасывал контейнерный
путь → `bot.download` открывал несуществующий путь → `FileNotFoundError`
для видео/ГС/аватаров. Проверяем container→host-нормализацию, traversal-guard
и общий helper для аватаров.

R17: токены в фикстурах синтетические (не секреты).
Windows-нюанс: каталог с ':' (как в проде на Linux) на win32 не создаётся —
FS-чтение проверяем на colon-free подкаталоге, а точный маппинг
'<bot_id>:<token>' — сравнением путей (без записи на диск).
"""
import asyncio
from types import SimpleNamespace

import pytest

from services import media_download as md

TOKEN = "42:TESTTOKENPLACEHOLDER"      # синтетический, не реальный секрет
SAFE = "bot42_testtoken"               # colon-free для win32-FS
CONTAINER = md.CONTAINER_API_FILES_ROOT


class _Bot:
    id = 42


@pytest.fixture()
def api_root(tmp_path, monkeypatch):
    # `settings` — frozen dataclass → подменяем ссылку в модуле (md.settings).
    monkeypatch.setattr(md, "settings", SimpleNamespace(
        TELEGRAM_API_FILES_DIR=str(tmp_path), API_TOKEN=TOKEN))
    return tmp_path


def _write(root, rel, data=b"payload"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# точный маппинг '<bot_id>:<token>' (Linux-форма) → host-путь (без FS-записи)
def test_container_token_dir_remaps_to_host(api_root):
    container = "%s/%s/videos/f.mp4" % (CONTAINER, TOKEN)
    assert md.local_file_path(_Bot(), container) == \
        api_root / TOKEN / "videos" / "f.mp4"


# (а) контейнерный абсолютный путь ВИДЕО → host-путь и чтение
def test_container_absolute_video_normalized_and_read(api_root):
    container = "%s/%s/videos/file_0.mp4" % (CONTAINER, SAFE)
    _write(api_root, "%s/videos/file_0.mp4" % SAFE, b"VIDEO")
    resolved = md.local_file_path(_Bot(), container)
    assert resolved == api_root / SAFE / "videos" / "file_0.mp4"
    assert asyncio.run(md.read_host_file_bytes(_Bot(), container)) == b"VIDEO"


# (б) то же для ГОЛОСОВОГО
def test_container_absolute_voice_normalized(api_root):
    container = "%s/%s/voice/file_1.oga" % (CONTAINER, SAFE)
    _write(api_root, "%s/voice/file_1.oga" % SAFE, b"VOICE")
    assert md.local_file_path(_Bot(), container) == \
        api_root / SAFE / "voice" / "file_1.oga"
    assert asyncio.run(md.read_host_file_bytes(_Bot(), container)) == b"VOICE"


# относительный путь → <root>/<bot_id:token>/<path> (сравнение пути)
def test_relative_path_uses_token_subdir(api_root):
    assert md.local_file_path(_Bot(), "videos/rel.mp4") == \
        api_root / TOKEN / "videos" / "rel.mp4"


# (в) traversal вне корня / escape → отклонено (fail-closed)
def test_traversal_outside_root_rejected(api_root):
    assert md.local_file_path(
        _Bot(), "%s/%s/../../etc/passwd" % (CONTAINER, TOKEN)) is None
    assert md.local_file_path(_Bot(), "../../etc/passwd") is None
    assert md.local_file_path(_Bot(), "/etc/passwd") is None
    assert md.local_file_path(_Bot(), CONTAINER) is None


def test_missing_file_returns_none(api_root):
    container = "%s/%s/videos/absent.mp4" % (CONTAINER, SAFE)
    assert md.local_file_path(_Bot(), container) is not None   # путь валиден
    assert asyncio.run(md.read_host_file_bytes(_Bot(), container)) is None


# (г) аватары используют тот же helper (общая логика, без дублирования)
def test_avatars_use_same_helper():
    from web.api import avatars
    assert avatars.read_host_file_bytes is md.read_host_file_bytes
