"""Локальный Bot API: сессия aiogram с корректным путём скачивания (DL-FIX).

**Проблема (ACCEPTANCE-92C, прод 2.58.92).** Локальный Bot API (`--local`)
возвращает в `getFile` АБСОЛЮТНЫЙ путь ВНУТРИ СВОЕГО КОНТЕЙНЕРА
(`/var/lib/telegram-bot-api/<token>/photos/file_N.jpg` — так документировано
core.telegram.org/bots/api#using-a-local-bot-api-server). aiogram при
`is_local=True` читает `file_path` с файловой системы ХОСТА бота
(`Bot.download_file` → `wrap_local_file.to_local(...)` → `aiofiles`), а на
хосте этого каталога нет: он существует только как bind-mount контейнера
(`docker-compose.yml`: `./docker/telegram-bot-api:/var/lib/telegram-bot-api`) →
`FileNotFoundError` → все vision-джобы умирают на `stage=download`.

**Почему не HTTP.** Локальный сервер в `--local` НЕ обслуживает `/file/bot…`
(HTTP-эндпоинт скачивания): прод-проба 19.10.2026 дала 404 и для абсолютного
контейнерного, и для относительного пути (`evidence/dl-fix/prod-diag-*.json`),
что совпадает с README aiogram/telegram-bot-api («local mode doesn't provide
possibility to download files from API»). HTTP-скачивание с локального сервера
требует отдельного reverse-proxy (nginx) — отдельный инфра-контур, здесь не
нужен.

**Решение.** Остаёмся в локальном режиме (чтение ФС, трафик не уходит в
облако), но путь из контейнера нормализуем к host-каталогу bind-mount —
ровно та же нормализация, что уже применяется для голосовых/видео
(`services/media_download.normalize_api_file_path`, прод-проверенный путь).
Маппинг не бросает исключений на неожиданных формах пути (относительный,
чужой абсолютный) — такой путь отдаётся как есть, т.е. поведение не хуже
прежнего.

R17: пути содержат `<bot_id>:<token>` — наружу (логи/ответы) они не попадают;
здесь только вычисление, логирование — по флагу читаемости каталога.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import (FilesPathWrapper, TelegramAPIServer)

from config.settings import settings

logger = logging.getLogger(__name__)

# Каталог данных локального Bot API в пространстве КОНТЕЙНЕРА (D263/ADR-1025-6;
# bind-source на хосте = settings.TELEGRAM_API_FILES_DIR).
CONTAINER_API_FILES_ROOT = "/var/lib/telegram-bot-api"


class HostFilesPathWrapper(FilesPathWrapper):
    """`file_path` контейнера → host-каталог bind-mount (и обратно).

    Отличия от `aiogram.client.telegram.SimpleFilesPathWrapper`: не бросает
    `ValueError`/`PermissionError` на путях вне `server_root` (относительных,
    host-абсолютных, чужих) — они возвращаются как есть (fail-safe: прежнее
    поведение вместо нового падения). Контейнерный путь — POSIX
    (`PurePosixPath`), host-каталог — нативный (`Path`), поэтому маппинг
    работает и на Windows-хосте разработчика."""

    def __init__(self, server_root: str | os.PathLike,
                 local_root: str | os.PathLike) -> None:
        self.server_root = str(server_root).rstrip("/")
        self.local_root = Path(str(local_root))

    def _rel_from_server(self, path) -> str | None:
        try:
            pure = PurePosixPath(str(path or ""))
            if not pure.is_absolute():
                return None
            rel = pure.relative_to(PurePosixPath(self.server_root))
        except (ValueError, OSError, TypeError):
            return None
        text = str(rel)
        return None if text in ("", ".") else text

    def to_local(self, path):
        """Контейнерный абсолютный → host-каталог; иначе — без изменений."""
        rel = self._rel_from_server(path)
        if rel is None:
            return path
        return str(self.local_root / rel)

    def to_server(self, path):
        """Host-каталог → контейнерный абсолютный (симметрия интерфейса)."""
        try:
            rel = Path(str(path or "")).relative_to(self.local_root)
        except (ValueError, OSError, TypeError):
            return path
        text = str(rel).replace("\\", "/")
        if text in ("", "."):
            return path
        return "%s/%s" % (self.server_root, text)


def host_files_root(files_dir: str | os.PathLike | None = None,
                    *, app_dir: str | os.PathLike | None = None) -> Path:
    """Абсолютный host-каталог файлов локального Bot API.

    `settings.TELEGRAM_API_FILES_DIR` по умолчанию относительный
    (`docker/telegram-bot-api`) и резолвится от каталога приложения (там же,
    где лежит `docker-compose.yml`), а не от текущего cwd процесса."""
    raw = str(files_dir if files_dir is not None
              else getattr(settings, "TELEGRAM_API_FILES_DIR",
                           "docker/telegram-bot-api") or "")
    path = Path(raw or "docker/telegram-bot-api")
    if path.is_absolute():
        return path
    base = Path(app_dir) if app_dir is not None \
        else Path(__file__).resolve().parent.parent
    return base / path


def local_files_dir_readable(root: str | os.PathLike | None = None) -> bool:
    """Читается ли host-каталог файлов (диагностика, без исключений).

    False — локальный режим не сможет отдать файлы: каталога нет, он не
    смонтирован или у процесса нет прав (сообщение для владельца/DevOps
    содержит только путь каталога, без токена)."""
    try:
        path = Path(root) if root is not None else host_files_root()
        return bool(path.is_dir() and os.access(path, os.R_OK | os.X_OK))
    except OSError:
        return False


def telegram_local_mode_enabled() -> bool:
    """True — инфраструктура Telegram Bot API в локальном режиме.

    ЕДИНЫЙ сигнал паритета с образом `aiogram/telegram-bot-api`:
    ЛЮБОЕ непустое значение `TELEGRAM_LOCAL` → `--local` (getFile до 2000 МБ);
    не задано/пусто → облако (20 МБ). Читается при каждом вызове: env общий
    для контейнера и хостового процесса (systemd `EnvironmentFile`), поэтому
    режим endpoint'а и режим сервера не расходятся. Это НЕ функциональный
    флаг модуля (`flags.download_enabled`): выключение функции не меняет
    endpoint Bot API.
    """
    raw = os.getenv("TELEGRAM_LOCAL")
    return bool(raw and raw.strip())


def session_local_mode(bot) -> bool | None:
    """Фактический режим aiogram-сессии: True/False либо None (неизвестно).

    Источник истины для транспорта — реальная сессия бота
    (`session.api.is_local`). Двойники/обвязки без настоящего bool-флага
    возвращают None: вызывающий берёт инфраструктурный сигнал, а НЕ
    функциональный флаг модуля. MagicMock/строки не считаются режимом.
    """
    try:
        api = getattr(getattr(bot, "session", None), "api", None)
        flag = getattr(api, "is_local", None)
    except Exception:
        return None
    return flag if isinstance(flag, bool) else None


def bot_api_mode(bot) -> dict:
    """Снимок режима Bot API для старта/диагностики (R17-safe).

    ``mode`` — фактический режим транспорта (`local`|`cloud`); ``session`` —
    что объявила сессия; ``infra`` — что требует инфраструктурная
    конфигурация (`TELEGRAM_LOCAL`). ``mismatch`` — сессия и инфраструктура
    разошлись (это надо явно видеть, а не молча работать «как получилось»).
    Значений токена/путей в снимке нет.
    """
    infra_local = telegram_local_mode_enabled()
    actual = session_local_mode(bot)
    mode = "local" if (actual if actual is not None else infra_local) \
        else "cloud"
    mismatch = actual is not None and actual != infra_local
    return {
        "mode": mode,
        "session": actual,
        "infra": infra_local,
        "mismatch": mismatch,
        "reason": ("session_vs_infra" if mismatch else ""),
    }


def log_bot_api_mode(bot, *, site: str = "bot-api") -> dict:
    """Явная фиксация режима Bot API при старте; mismatch — WARNING.

    Возвращает тот же снимок `bot_api_mode` (для тестов/диагностики).
    R17: только режимы и признак расхождения, без токена и URL.
    """
    snapshot = bot_api_mode(bot)
    if snapshot["mismatch"]:
        logger.warning(
            "[%s] mode mismatch | session=%s infra=%s (TELEGRAM_LOCAL) — "
            "endpoint выбран по фактической сессии; выровняйте "
            "инфраструктурную конфигурацию", site, snapshot["session"],
            snapshot["infra"])
    else:
        logger.info("[%s] mode=%s source=%s", site, snapshot["mode"],
                    "session" if snapshot["session"] is not None else "infra")
    return snapshot


def build_local_api_session(url: str | None = None, *,
                            files_dir: str | os.PathLike | None = None,
                            app_dir: str | os.PathLike | None = None
                            ) -> AiohttpSession:
    """Сессия aiogram для локального Bot API: API — локальная база, файлы —
    host-каталог bind-mount (без облака).

    `is_local=True` + `wrap_local_file=HostFilesPathWrapper(container → host)`:
    вызовы методов идут на локальную базу (`<url>/bot<token>/<method>`), а
    скачивание читает файл из host-каталога локального сервера. Если каталог
    не читается — WARNING с путём (R17-safe) и прежнее поведение
    (fail-safe: новый режим не маскируется и не добавляет новых отказов)."""
    base = str(url if url is not None
               else getattr(settings, "LOCAL_BOT_API_URL",
                            "http://localhost:8081") or "").rstrip("/")
    root = host_files_root(files_dir, app_dir=app_dir)
    api = TelegramAPIServer.from_base(
        base, is_local=True,
        wrap_local_file=HostFilesPathWrapper(CONTAINER_API_FILES_ROOT, root))
    if not local_files_dir_readable(root):
        logger.warning(
            "[local-bot-api] каталог файлов не читается: %s — скачивание "
            "локальных файлов не сработает (bind-mount тома "
            "telegram-bot-api на хосте / права процесса)", root)
    else:
        logger.info("[local-bot-api] файлы: %s (container %s)", root,
                    CONTAINER_API_FILES_ROOT)
    return AiohttpSession(api=api)
