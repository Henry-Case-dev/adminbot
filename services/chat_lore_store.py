"""Раунд 7 (chat-lore-management-v2, T-772, B2) — транзакционный PG-слой лора.

`ChatLoreStore(pg)` — тонкий слой над пулом asyncpg. ТРАНЗАКЦИОННАЯ единица
(spec §3.3, инвариант §1.3-4): в одной `async with conn.transaction()`:
(1) мутирующий SQL по профилю; (2) при контентном изменении — запись
`chat_lore_history`; (3) `SELECT pg_notify('lore_updated', $payload)`.
Сбой в любой точке → полный откат (ни апдейта, ни истории, ни NOTIFY).

Методы-контракт §3.3 (имена — по spec; см. также «алиасы» в конце класса):

  * профиль: get_profile / list_profiles / list_active_chats / ensure_profile /
    set_manual (alias update_manual) / set_auto / mark_auto_done / clear_auto /
    update_settings / set_active / migrate_profile;
  * chat_links: add_link / resolve_chat_id (глубина ≤ 5, цикл-защита);
  * chat_admins: list_chat_admins (alias list_admins) / add_chat_admin (alias
    add_admin) / remove_chat_admin (alias remove_admin) / is_chat_admin;
  * история: history (alias list_history), timeline DESC.

Ошибки PG — НЕ глотаются (их ловят вызывающие: кэш/API/воркер); пустые/нет
профиля → None (get_profile) или `ChatLoreConflict(chat_id, current_updated_at)`
для мутирующих операций (0 строк = рассинхрон optimistic-метки ИЛИ профиля нет —
текущий updated_at = None). Пул отсутствует (PG down) → `ChatLorePgUnavailable`
(fail-open решается уровнем выше).
"""
import logging
from datetime import datetime

from services.lore_cache import LoreProfile

logger = logging.getLogger(__name__)

# ── SQL (идемпотентные, параметризованные; $N — позиционные аргументы) ──────

_PROFILE_COLS = (
    "chat_id", "manual_lore", "auto_lore", "auto_enabled", "auto_period_hours",
    "auto_window_hours", "is_active", "last_auto_at", "updated_at",
)
_PROFILE_SELECT = "SELECT {cols} FROM chat_profiles WHERE chat_id = $1"

INSERT_DEFAULT_PROFILE = (
    "INSERT INTO chat_profiles (chat_id) VALUES ($1) "
    "ON CONFLICT (chat_id) DO NOTHING"
)

# NOTE (реальный PG, не фейки): fetchrow на UPDATE без RETURNING отдаёт
# None ВСЕГДА — строки меняющих операций обязаны заканчиваться RETURNING *.
SET_MANUAL_SQL = (
    "UPDATE chat_profiles SET manual_lore = $2, updated_at = now() "
    "WHERE chat_id = $1 RETURNING *"
)
SET_MANUAL_LOCKED_SQL = (
    "UPDATE chat_profiles SET manual_lore = $2, updated_at = now() "
    "WHERE chat_id = $1 AND updated_at = $3::timestamptz RETURNING *"
)

SET_AUTO_SQL = (
    "UPDATE chat_profiles SET auto_lore = $2, last_auto_at = now(), "
    "updated_at = now() WHERE chat_id = $1 RETURNING *"
)

MARK_AUTO_DONE_SQL = (
    "UPDATE chat_profiles SET last_auto_at = now(), updated_at = now() "
    "WHERE chat_id = $1"
)

CLEAR_AUTO_SQL = (
    "UPDATE chat_profiles SET auto_lore = '', last_auto_at = NULL, "
    "updated_at = now() WHERE chat_id = $1 RETURNING *"
)

SET_ACTIVE_SQL = (
    "UPDATE chat_profiles SET is_active = $2, updated_at = now() "
    "WHERE chat_id = $1"
)

INSERT_HISTORY_SQL = (
    "INSERT INTO chat_lore_history "
    "(chat_id, field, changed_by, old_value, new_value) "
    "VALUES ($1, $2, $3, $4, $5)"
)

NOTIFY_SQL = "SELECT pg_notify('lore_updated', $1)"

UPSERT_LINK_SQL = (
    "INSERT INTO chat_links (old_chat_id, new_chat_id) VALUES ($1, $2) "
    "ON CONFLICT (old_chat_id) DO UPDATE "
    "SET new_chat_id = EXCLUDED.new_chat_id"
)
LINK_RESOLVE_SQL = (
    "SELECT new_chat_id FROM chat_links WHERE old_chat_id = $1"
)

# migrate_profile: чистый перенос (нового профиля нет) — chat_id переезжает.
MOVE_PROFILE_SQL = (
    "UPDATE chat_profiles SET chat_id = $1, updated_at = now() "
    "WHERE chat_id = $2"
)
# merge (новый профиль занят): данные из старого переносятся по Q9.
MERGE_PROFILE_SQL = (
    "UPDATE chat_profiles SET manual_lore = $2, auto_lore = $3, "
    "auto_enabled = $4, auto_period_hours = $5, auto_window_hours = $6, "
    "is_active = $7, last_auto_at = $8::timestamptz, updated_at = now() "
    "WHERE chat_id = $1 RETURNING *"
)
DELETE_PROFILE_SQL = "DELETE FROM chat_profiles WHERE chat_id = $1"

# chat_admins: перенос при merge (Q9): копируем строки старого на новый
# (конфликты не дублируем), затем удаляем ВСЕ строки старого чата — после
# копирования они целиком переехали (админы, бывшие только у нового, живы).
MOVE_ADMINS_SQL = (
    "UPDATE chat_admins SET chat_id = $1 WHERE chat_id = $2"
)
COPY_ADMINS_SQL = (
    "INSERT INTO chat_admins (chat_id, telegram_id, added_by, created_at) "
    "SELECT $1, telegram_id, added_by, created_at FROM chat_admins "
    "WHERE chat_id = $2 ON CONFLICT (chat_id, telegram_id) DO NOTHING"
)
PRUNE_ADMINS_SQL = "DELETE FROM chat_admins WHERE chat_id = $1"

LIST_ADMINS_SQL = (
    "SELECT telegram_id FROM chat_admins WHERE chat_id = $1 "
    "ORDER BY telegram_id"
)
ADMIN_EXISTS_SQL = (
    "SELECT 1 FROM chat_admins WHERE chat_id = $1 AND telegram_id = $2 LIMIT 1"
)
INSERT_ADMIN_SQL = (
    "INSERT INTO chat_admins (chat_id, telegram_id, added_by) "
    "VALUES ($1, $2, $3) ON CONFLICT (chat_id, telegram_id) DO NOTHING"
)
DELETE_ADMIN_SQL = (
    "DELETE FROM chat_admins WHERE chat_id = $1 AND telegram_id = $2"
)

LIST_PROFILES_SQL = ("SELECT {cols} FROM chat_profiles{where} ORDER BY chat_id")
LIST_ACTIVE_CHATS_SQL = (
    "SELECT chat_id FROM chat_profiles WHERE is_active AND auto_enabled "
    "ORDER BY chat_id"
)
HISTORY_SQL = (
    "SELECT id, chat_id, field, changed_by, old_value, new_value, created_at "
    "FROM chat_lore_history WHERE chat_id = $1 "
    "ORDER BY created_at DESC, id DESC LIMIT $2"
)

_MAX_RESOLVE_DEPTH = 5   # spec §4: глубина > 5 → исходный id (безопасный возврат)


class ChatLoreConflict(Exception):
    """Рассинхрон optimistic-метки (0 строк) либо профиля нет вовсе.

    Атрибуты: chat_id; current_updated_at (ISO-строка или None, если
    профиль не существует) — API отдаёт их в 409 {"detail": ...}.
    """

    def __init__(self, chat_id: int, current_updated_at: str | None):
        self.chat_id = chat_id
        self.current_updated_at = current_updated_at
        super().__init__(
            f"chat_lore conflict: chat_id={chat_id} "
            f"current_updated_at={current_updated_at}")


class ChatLorePgUnavailable(RuntimeError):
    """Мутирующая операция требует PostgreSQL, но пул отсутствует."""


def _iso(value) -> str | None:
    """datetime/ISO-строка → ISO-строка (метки UTC; None при отсутствии)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_profile(row) -> LoreProfile:
    """Строка PG (asyncpg Record/dict) → frozen LoreProfile (метки ISO)."""
    return LoreProfile(
        chat_id=row["chat_id"],
        manual_lore=row["manual_lore"] or "",
        auto_lore=row["auto_lore"] or "",
        auto_enabled=bool(row["auto_enabled"]),
        auto_period_hours=row["auto_period_hours"],
        auto_window_hours=row["auto_window_hours"],
        is_active=bool(row["is_active"]),
        last_auto_at=_iso(row.get("last_auto_at")),
        updated_at=_iso(row["updated_at"]),
    )


def _max_ts(a: str | None, b: str | None) -> str | None:
    """max(last_auto_at) старого и нового профиля (Q9 merge)."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        pa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        pb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return a
    return a if pa >= pb else b


def _iso_same(a: str | None, b: str | None) -> bool:
    """Равенство ISO-меток с ленивым парсингом (клиент мог переформатировать
    updated_at: Z/микросекунды/офсет). Не-ISO мусор — сравнение строк."""
    if a is None or b is None:
        return a == b
    try:
        pa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        pb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return a == b
    return pa == pb


class ChatLoreStore:
    """Тонкий слой над пулом PgDatabase: профили/история/ссылки/админы."""

    def __init__(self, pg):
        self._pg = pg

    @property
    def pg(self):
        return self._pg

    # ── внутренние помощники ──────────────────────────────────────────────

    def _pool(self):
        pool = self._pg.pool if hasattr(self._pg, "pool") else None
        if pool is None:
            raise ChatLorePgUnavailable("PostgreSQL недоступен (пул отсутствует)")
        return pool

    async def _resolve_on(self, conn, chat_id: int) -> int:
        """Жадный проход по цепочке chat_links на данном соединении.

        Глубина ≤ 5, защита от циклов (множество посещённых); превышение
        глубины или цикл → безопасный возврат ИСХОДНОГО id (spec §4)."""
        current = chat_id
        visited = {chat_id}
        hops = 0
        while True:
            row = await conn.fetchrow(LINK_RESOLVE_SQL, current)
            if row is None:
                return current
            nxt = row["new_chat_id"]
            if nxt in visited:
                logger.warning(
                    "[chat_lore_store] resolve cycle detected | chat_id=%s",
                    chat_id)
                return chat_id
            hops += 1
            if hops > _MAX_RESOLVE_DEPTH:
                logger.warning(
                    "[chat_lore_store] resolve depth > %d | chat_id=%s → "
                    "исходный id", _MAX_RESOLVE_DEPTH, chat_id)
                return chat_id
            visited.add(nxt)
            current = nxt

    # ── профиль: чтение ────────────────────────────────────────────────────

    async def get_profile(self, chat_id: int) -> LoreProfile | None:
        """Профиль по chat_id (с резолвом chat_links внутри); None — нет."""
        pool = self._pool()
        async with pool.acquire() as conn:
            resolved = await self._resolve_on(conn, chat_id)
            row = await conn.fetchrow(
                _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                resolved)
        return _to_profile(row) if row is not None else None

    async def list_profiles(self, active_only: bool = False) -> list[LoreProfile]:
        """Все профили (или только is_active) — для API-списков."""
        pool = self._pool()
        where = " WHERE is_active" if active_only else ""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                LIST_PROFILES_SQL.format(
                    cols=", ".join(_PROFILE_COLS), where=where))
        return [_to_profile(r) for r in rows]

    async def list_active_chats(self) -> list[int]:
        """chat_id активных авто-чатов (is_active AND auto_enabled) — воркер."""
        pool = self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(LIST_ACTIVE_CHATS_SQL)
        return [r["chat_id"] for r in rows]

    async def ensure_profile(self, chat_id: int) -> LoreProfile:
        """INSERT дефолтного профиля ON CONFLICT DO NOTHING + SELECT."""
        pool = self._pool()
        async with pool.acquire() as conn:
            await conn.execute(INSERT_DEFAULT_PROFILE, chat_id)
            row = await conn.fetchrow(
                _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                chat_id)
        if row is None:  # practically unreachable (INSERT выше), защита
            raise ChatLoreConflict(chat_id, None)
        return _to_profile(row)

    # alias (устаревшее имя, T-772-промпт): вступление бота в чат (FR-6)
    upsert_profile_on_join = ensure_profile

    # ── профиль: изменения (транзакция профиль+история+NOTIFY) ─────────────

    async def set_manual(
        self, chat_id: int, text: str, changed_by: int | None = None,
        expected_updated_at: str | None = None,
    ) -> LoreProfile:
        """Ручная правка manual_lore (FR-2). Только manual_lore — auto_lore/
        last_auto_at/auto_enabled НЕ трогаются. Optimistic-метка: задан
        expected_updated_at → `AND updated_at = $…::timestamptz`; 0 строк →
        ChatLoreConflict(chat_id, current_updated_at). История field='manual',
        changed_by=telegram_id; NOTIFY."""
        pool = self._pool()
        text = text or ""
        async with pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                    chat_id)
                if old is None:
                    raise ChatLoreConflict(chat_id, None)
                if expected_updated_at is not None:
                    sql = SET_MANUAL_LOCKED_SQL
                    args = (chat_id, text, expected_updated_at)
                else:
                    sql = SET_MANUAL_SQL
                    args = (chat_id, text)
                row = await conn.fetchrow(sql, *args)
                if row is None:
                    current = await conn.fetchrow(
                        _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                        chat_id)
                    raise ChatLoreConflict(
                        chat_id, _iso(current["updated_at"]))
                await conn.execute(
                    INSERT_HISTORY_SQL, chat_id, "manual", changed_by,
                    old["manual_lore"] or "", text)
                await conn.execute(NOTIFY_SQL, str(chat_id))
        return _to_profile(row)

    # alias (имя из ТЗ B2/prompts): единая реализация
    update_manual = set_manual

    async def set_auto(
        self, chat_id: int, text: str, changed_by: int | None = None,
        record_history: bool = True,
    ) -> LoreProfile:
        """Запись результата авто-генерации воркера: auto_lore + метка
        last_auto_at=now() (период «сброшен»); история field='auto'
        (changed_by NULL — AI), NOTIFY. Без optimistic-метки (воркер — свой
        гейт)."""
        pool = self._pool()
        text = text or ""
        async with pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                    chat_id)
                row = await conn.fetchrow(SET_AUTO_SQL, chat_id, text)
                if row is None:
                    current = await conn.fetchrow(
                        _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                        chat_id)
                    raise ChatLoreConflict(
                        chat_id, _iso(current["updated_at"])
                        if current is not None else None)
                if record_history:
                    await conn.execute(
                        INSERT_HISTORY_SQL, chat_id, "auto", changed_by,
                        (old["auto_lore"] or "") if old is not None else "",
                        text)
                await conn.execute(NOTIFY_SQL, str(chat_id))
        return _to_profile(row)

    async def mark_auto_done(self, chat_id: int) -> None:
        """UNCHANGED-путь воркера: только метка last_auto_at=now() БЕЗ истории
        (контент не менялся); NOTIFY."""
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(MARK_AUTO_DONE_SQL, chat_id)
                await conn.execute(NOTIFY_SQL, str(chat_id))

    async def clear_auto(self, chat_id: int,
                         changed_by: int | None = None) -> LoreProfile:
        """Очистка auto_lore: auto_lore='', last_auto_at=NULL (следующий
        прогон не ждёт период); история field='auto' old=текст new=''."""
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                old = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                    chat_id)
                if old is None:
                    raise ChatLoreConflict(chat_id, None)
                row = await conn.fetchrow(CLEAR_AUTO_SQL, chat_id)
                if row is None:
                    raise ChatLoreConflict(
                        chat_id, _iso((await conn.fetchrow(
                            _PROFILE_SELECT.format(
                                cols=", ".join(_PROFILE_COLS)),
                            chat_id))["updated_at"]))
                await conn.execute(
                    INSERT_HISTORY_SQL, chat_id, "auto", changed_by,
                    old["auto_lore"] or "", "")
                await conn.execute(NOTIFY_SQL, str(chat_id))
        return _to_profile(row)

    async def update_settings(
        self, chat_id: int, *, auto_enabled: bool | None = None,
        auto_period_hours: int | None = None,
        auto_window_hours: int | None = None,
        changed_by: int | None = None,
        expected_updated_at: str | None = None,
    ) -> LoreProfile:
        """Частичное обновление настроек. История — ПО-ПОЛЕВОЙ строкой на
        каждое реально изменённое поле (field='auto_enabled'|'auto_period_hours'|
        'auto_window_hours'). Ни одно поле не изменилось → ни UPDATE, ни
        истории, ни NOTIFY (возврат текущего профиля). Optimistic-метка →
        ChatLoreConflict."""
        pool = self._pool()
        candidates = (
            ("auto_enabled", auto_enabled),
            ("auto_period_hours", auto_period_hours),
            ("auto_window_hours", auto_window_hours),
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                    chat_id)
                if row is None:
                    raise ChatLoreConflict(chat_id, None)
                profile = _to_profile(row)
                changed = []
                for name, value in candidates:
                    if value is None:
                        continue
                    if getattr(profile, name) != value:
                        changed.append((name, getattr(profile, name), value))
                if not changed:
                    return profile
                if (expected_updated_at is not None
                        and not _iso_same(_iso(row["updated_at"]),
                                          expected_updated_at)):
                    raise ChatLoreConflict(
                        chat_id, _iso(row["updated_at"]))
                set_parts: list[str] = []
                args: list = [chat_id]
                for name, _old, value in changed:
                    args.append(value)
                    set_parts.append(f"{name} = ${len(args)}")
                sql = ("UPDATE chat_profiles SET " + ", ".join(set_parts)
                       + ", updated_at = now() WHERE chat_id = $1")
                if expected_updated_at is not None:
                    args.append(expected_updated_at)
                    sql += f" AND updated_at = ${len(args)}::timestamptz"
                sql += " RETURNING *"
                updated = await conn.fetchrow(sql, *args)
                if updated is None:
                    current = await conn.fetchrow(
                        _PROFILE_SELECT.format(cols=", ".join(_PROFILE_COLS)),
                        chat_id)
                    raise ChatLoreConflict(
                        chat_id, _iso(current["updated_at"])
                        if current is not None else None)
                for name, old_value, new_value in changed:
                    await conn.execute(
                        INSERT_HISTORY_SQL, chat_id, name, changed_by,
                        str(old_value), str(new_value))
                await conn.execute(NOTIFY_SQL, str(chat_id))
        return _to_profile(updated)

    async def set_active(self, chat_id: int, is_active: bool) -> None:
        """Lifecycle-апсерт is_active (без истории, без optimistic-метки);
        при включении — ensure-профиль (бот вошёл в чат). NOTIFY."""
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                if is_active:
                    await conn.execute(INSERT_DEFAULT_PROFILE, chat_id)
                await conn.execute(SET_ACTIVE_SQL, chat_id, is_active)
                await conn.execute(NOTIFY_SQL, str(chat_id))

    async def migrate_profile(self, old_chat_id: int, new_chat_id: int,
                              changed_by: int | None = None) -> dict:
        """Переезд чата (Q9, D5): перенос/merge профиля + chat_links +
        chat_admins + история field='remap' + NOTIFY old+new. Возврат
        {"moved": bool, "merged": bool}; профиля old нет → WARNING + no-op."""
        if old_chat_id == new_chat_id:
            return {"moved": False, "merged": False}
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                resolved_old = await self._resolve_on(conn, old_chat_id)
                if resolved_old == new_chat_id:
                    return {"moved": False, "merged": False}
                cols = ", ".join(_PROFILE_COLS)
                old_row = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=cols), resolved_old)
                if old_row is None:
                    logger.warning(
                        "[chat_lore_store] migrate_profile: профиль %s не "
                        "найден — no-op | new=%s", resolved_old, new_chat_id)
                    return {"moved": False, "merged": False}
                new_row = await conn.fetchrow(
                    _PROFILE_SELECT.format(cols=cols), new_chat_id)
                await conn.execute(
                    INSERT_HISTORY_SQL, resolved_old, "remap", changed_by,
                    str(resolved_old), str(new_chat_id))
                await conn.execute(UPSERT_LINK_SQL, resolved_old, new_chat_id)
                if new_row is None:
                    # чистый перенос: строки переезжают на новый id
                    await conn.execute(MOVE_PROFILE_SQL, new_chat_id,
                                       resolved_old)
                    await conn.execute(MOVE_ADMINS_SQL, new_chat_id,
                                       resolved_old)
                    moved, merged = True, False
                else:
                    # merge по Q9: новый профиль занят — объединяем
                    old = _to_profile(old_row)
                    new = _to_profile(new_row)
                    await conn.fetchrow(
                        MERGE_PROFILE_SQL, new_chat_id,
                        old.manual_lore or new.manual_lore,
                        new.auto_lore or old.auto_lore,
                        old.auto_enabled or new.auto_enabled,
                        old.auto_period_hours,
                        old.auto_window_hours,
                        old.is_active or new.is_active,
                        _max_ts(old.last_auto_at, new.last_auto_at),
                    )
                    await conn.execute(DELETE_PROFILE_SQL, resolved_old)
                    await conn.execute(COPY_ADMINS_SQL, new_chat_id,
                                       resolved_old)
                    await conn.execute(PRUNE_ADMINS_SQL, resolved_old)
                    moved, merged = False, True
                await conn.execute(NOTIFY_SQL, str(resolved_old))
                await conn.execute(NOTIFY_SQL, str(new_chat_id))
                if resolved_old != old_chat_id:
                    # кэш мог держать и исходный (доконцевой) id
                    await conn.execute(NOTIFY_SQL, str(old_chat_id))
        return {"moved": moved, "merged": merged}

    # ── chat_links ──────────────────────────────────────────────────────────

    async def add_link(self, old_chat_id: int, new_chat_id: int) -> None:
        """Запись переезда old→new (upsert: повторный remap того же old
        актуализирует new_chat_id — §3.2/§4)."""
        pool = self._pool()
        async with pool.acquire() as conn:
            await conn.execute(UPSERT_LINK_SQL, old_chat_id, new_chat_id)

    async def resolve_chat_id(self, chat_id: int) -> int:
        """Актуальный chat_id по цепочке chat_links (≤ 5 хопов, цикл-защита)."""
        pool = self._pool()
        async with pool.acquire() as conn:
            return await self._resolve_on(conn, chat_id)

    # ── chat_admins (per-chat админы, §3.8/Q6) ─────────────────────────────

    async def list_chat_admins(self, chat_id: int) -> list[int]:
        """telegram_id админов чата."""
        pool = self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(LIST_ADMINS_SQL, chat_id)
        return [r["telegram_id"] for r in rows]

    async def add_chat_admin(self, chat_id: int, telegram_id: int,
                             added_by: int | None = None) -> bool:
        """Добавить админа чата (ON CONFLICT DO NOTHING). История
        field='chat_admin' new_value=str(telegram_id) — только при реальной
        вставке. True — строка добавлена."""
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    INSERT_ADMIN_SQL, chat_id, telegram_id, added_by)
                inserted = _tagged_count(result, "INSERT") > 0
                if inserted:
                    await conn.execute(
                        INSERT_HISTORY_SQL, chat_id, "chat_admin", added_by,
                        "", str(telegram_id))
        return inserted

    async def remove_chat_admin(self, chat_id: int,
                                telegram_id: int) -> bool:
        """Удалить админа чата; история field='chat_admin'
        old_value=str(telegram_id) — только при реальном удалении."""
        pool = self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    DELETE_ADMIN_SQL, chat_id, telegram_id)
                removed = _tagged_count(result, "DELETE") > 0
                if removed:
                    await conn.execute(
                        INSERT_HISTORY_SQL, chat_id, "chat_admin", None,
                        str(telegram_id), "")
        return removed

    async def is_chat_admin(self, telegram_id: int, chat_id: int) -> bool:
        """RBAC (Q6): есть ли строка (telegram_id, chat_id) в chat_admins."""
        pool = self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(ADMIN_EXISTS_SQL, chat_id, telegram_id)
        return row is not None

    # ── история (аудит, §3.3/Q7) ───────────────────────────────────────────

    async def history(self, chat_id: int, limit: int = 100) -> list[dict]:
        """Строки истории чата, timeline DESC: created_at (ISO), field,
        changed_by, old_value, new_value."""
        pool = self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(HISTORY_SQL, chat_id, max(1, int(limit)))
        return [
            {
                "id": r["id"],
                "chat_id": r["chat_id"],
                "field": r["field"],
                "changed_by": r["changed_by"],
                "old_value": r["old_value"],
                "new_value": r["new_value"],
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ]

    # alias (имя из промпта B2): единая реализация
    list_history = history


def _tagged_count(tag: str | None, op: str) -> int:
    """Разбор command-tag («INSERT 0 1» / «DELETE 1» / «UPDATE 1») → число."""
    parts = (tag or "").split()
    if len(parts) < 2 or parts[0].upper() != op:
        return 0
    return int(parts[-1]) if parts[-1].isdigit() else 0
