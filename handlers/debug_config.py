"""Epic 85 (84.18.4, T-656) — скрытая команда /debug_config [key].

Только в DM, только для is_debug_admin() (84.18.2: wildcard-роль или право
action.debug.config; деградация PG → фолбек settings.ADMIN_USER_ID). Команда
НЕ входит в set_my_commands (D95 — меню «/» не раскрывает существование);
сообщение команды удаляется. Вывод — <pre>-блоки с разбиением ≤4000 символов
на чанк (лимит Telegram 4096 с запасом на <pre>-обёртку); ЛЮБОЕ значение
(строка/repr(dict/json)) обрезается до 200 символов + value_len (84.18.3);
все значения проходят html.escape ОДНОЙ точкой ДО чанковки (HIGH-1:
content.info_how_it_works — dict с HTML, prompts.* — строки с <b>/& —
не должны ронять TelegramBadRequest). Секреты — только configured/last4.
"""
import html as html_mod
import logging

from aiogram import F, Router, types
from aiogram.filters import Command

from services.debug_config import (
    _TG_TRUNCATE_CHARS,
    build_dump,
    is_debug_admin,
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


def _format_value(item: dict) -> str:
    """HIGH-1: обрезка ЛЮБОГО представления значения (строка и repr
    dict/json/…) до 200 символов + value_len; секреты — configured/last4."""
    value = item["value"]
    if item["secret"]:
        return ("configured" if value.get("configured") else "not configured") \
            + (f" (last4: {value['last4']})" if value.get("last4") else "")
    if isinstance(value, str):
        text = value
        full_len = item.get("value_len") or len(value)
    else:
        text = repr(value)
        full_len = len(text)
    if len(text) > _TG_TRUNCATE_CHARS:
        return text[:_TG_TRUNCATE_CHARS] + f"… [len={full_len}]"
    return text


def _render_key_line(item: dict) -> str:
    return (f"{item['key']} | source={item['source']} | type={item['type']} "
            f"| updated_at={item['updated_at']}\n"
            f"    value={_format_value(item)}")


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
    """DM-only, admin-only; сообщение удаляется; вывод <pre>-блоками."""
    user_id = message.from_user.id if message.from_user else 0
    cache = get_config_cache()
    if not is_debug_admin(cache, user_id):
        logger.debug("[/debug_config] non-admin %d rejected (DM)", user_id)
        return
    await _delete_command(message)
    args = (message.text or "").split(maxsplit=1)
    key = args[1].strip() if len(args) > 1 else ""
    dump = build_dump(cache, key=key or None)
    meta = dump["meta"]
    header = (
        f"In-Memory State Dump\n"
        f"pid={meta['pid']} | version={meta['app_version']} | "
        f"initialized={meta['is_initialized']} | pg={meta['pg_available']}\n"
        f"keys_total={meta['keys_total']} | "
        f"cache_loaded_at={meta['cache_loaded_at']}\n"
        f"generated_at={meta['generated_at']}\n"
        + ("─" * 40)
    )
    if "item" in dump:
        body_lines = [_render_key_line(dump["item"])]
    else:
        body_lines = [
            _render_key_line(item)
            for item in dump["items"]
        ]
    # HIGH-1: html.escape — ОДНА точка, ДО чанковки (экранирование не меняет
    # \n; чанк ≤ 4000 экранированных символов → сообщение ≤ 4000+<pre>-обёртка
    # < 4096 при любом содержимом).
    escaped_lines = [html_mod.escape(line) for line in [header] + body_lines]
    chunks = _chunk_lines(escaped_lines)
    for chunk in chunks:
        await message.answer(
            f"<pre>{chunk}</pre>", parse_mode="HTML")
    logger.info("[/debug_config] dump sent | by=%s | keys=%d",
                user_id, len(dump.get("items", [1])))
