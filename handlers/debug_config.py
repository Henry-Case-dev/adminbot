"""Epic 85 (84.18.4/84.20, T-656/T-658) — скрытая команда /debug_config [key].

Только в DM, только для is_debug_admin() (84.18.2: wildcard-роль или право
action.debug.config; деградация PG → фолбек settings.ADMIN_USER_ID). Команда
НЕ входит в set_my_commands (D95); сообщение команды удаляется. Формат v2
(84.20.3): одна компактная meta-строка + строки `KEY = value`;
`/debug_config SEARCH_MAX_SYMBOLS` (env-имя, case-insensitive) — одна
строка; неизвестный ключ → «не найден: X». Чанкинг ≤4000 символов в <pre>
с html.escape ДО чанковки (HIGH-1); секреты — только configured••••last4.
"""
import html as html_mod
import logging

from aiogram import F, Router, types
from aiogram.filters import Command

from services.debug_config import (
    build_dump,
    build_lines,
    is_debug_admin,
    resolve_param_key,
)
from services.hot_config import get_config_cache

logger = logging.getLogger(__name__)

debug_config_router = Router(name="debug_config")

_SPLIT_CHUNK = 4000          # < 4096 — лимит Telegram на сообщение


async def _delete_command(message: types.Message) -> None:
    """Паттерн admin_commands.py: удалить команду (отказ delete — не стоп)."""
    try:
        await message.delete()
    except Exception:
        logger.debug("[/debug_config] delete failed | chat=%s",
                     message.chat.id)


def _chunk_lines(lines: list[str], chunk: int = _SPLIT_CHUNK) -> list[str]:
    """Разбиение <pre>-блока по строковому лимиту (84.18.4). Сверхдлинная
    ОДНА строка жёстко нарезается по chunk — ни один чанк не превышает лимит."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        while len(line) > chunk:
            piece, line = line[:chunk], line[chunk:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)
        if len(current) + len(line) + 1 > chunk and current:
            chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        chunks.append(current)
    return chunks


@debug_config_router.message(Command("debug_config"), F.chat.type == "private")
async def cmd_debug_config(message: types.Message) -> None:
    """DM-only, admin-only; сообщение удаляется; вывод v2 <pre>-блоками."""
    user_id = message.from_user.id if message.from_user else 0
    cache = get_config_cache()
    if not is_debug_admin(cache, user_id):
        logger.debug("[/debug_config] non-admin %d rejected (DM)", user_id)
        return
    await _delete_command(message)
    args = (message.text or "").split(maxsplit=1)
    raw = args[1].strip() if len(args) > 1 else ""
    if raw:
        # 84.20.2: env-имя / settings_field / pg-ключ (case-insensitive)
        spec = resolve_param_key(raw)
        if spec is None:
            await message.answer(f"не найден: {raw}")
            logger.info("[/debug_config] not found | by=%s | raw=%r",
                        user_id, raw)
            return
        lines = build_lines(cache, key=spec.pg_key)
    else:
        lines = build_lines(cache)
    escaped = [html_mod.escape(line) for line in lines]
    chunks = _chunk_lines(escaped)
    for chunk in chunks:
        await message.answer(
            f"<pre>{chunk}</pre>", parse_mode="HTML")
    logger.info("[/debug_config] dump sent | by=%s | lines=%d",
                user_id, len(lines))
