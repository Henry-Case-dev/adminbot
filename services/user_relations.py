"""Раунд 9 (AGI Memory, T-816/T-817, spec §3.1.2) — стадии/decay/анти-откат.

`users_meta` (SQLite) хранит СЧИТАЕМОЕ: авто-стадия `relationship_stage`,
активность, скоры (см. database.py). Здесь — чистая логика расчёта (Q5) и
`RelationsService` — ленивый кэш над db/мета-строками для инжекта (B4) и
API-чтения (F1). Ручное (manual_stage/note админа) живёт в PG
`chat_profiles.relations` (Q1) и мержится поверх авто (manual ?? auto).

Правила авто-стадии (spec §3.1.2, Q5):
  * кандидат — конъюнкция (msg_total И days_in_chat = now − first_seen):
    veteran 1000/365, regular 200/90, acquaintance 10/7, иначе stranger;
  * повышение — мгновенно (без кулдауна);
  * анти-откат: (1) отсутствие > relations_hold_absent_days (60д) → стадия
    НЕ понижается (падает только activity_score); (2) иначе понижение не
    чаще раза в relations_stage_change_min_days (30д, по last_stage_change)
    И только при msg_30d < relations_downgrade_msg_30d (10); (3) максимум
    на 1 ступень за раз; (4) ручная стадия из PG блокирует авто и НЕ трогает
    relationship_stage/last_stage_change.

Ленивый пересчёт: RAM-кэш per chat (TTL 60 с) + db-гейт по колонке
last_recalc_at (`limits.relations_recalc_ttl_minutes` = 5): протухшие/
отсутствующие строки пересчитываются `db.refresh_users_meta` по явному
списку user_ids (инжект); без списка — refresh топ-N чата (API-список).

Зависимости модуля: hot_config/config.settings (пороги — hot-лимиты группы
`limits_relations`); database.py импортирует отсюда чистые функции — циклов
нет (модуль НЕ импортирует database).
"""
import asyncio
import logging
import time

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

STAGE_STRANGER = "stranger"
STAGE_ACQUAINTANCE = "acquaintance"
STAGE_REGULAR = "regular"
STAGE_VETERAN = "veteran"

STAGES: tuple[str, ...] = (
    STAGE_STRANGER, STAGE_ACQUAINTANCE, STAGE_REGULAR, STAGE_VETERAN,
)
STAGE_RANK: dict[str, int] = {stage: i for i, stage in enumerate(STAGES)}

# Русские подписи стадий для инжекта `<user_relations>`/API (spec §3.1.4).
STAGE_RU: dict[str, str] = {
    STAGE_STRANGER: "нюфаг",
    STAGE_ACQUAINTANCE: "знакомый",
    STAGE_REGULAR: "свой",
    STAGE_VETERAN: "ветеран",
}

_MISSING = object()   # маркер отсутствующего hot-ключа (дефолт из settings)


def _limit(name: str):
    """hot-лимит `limits.relations_*` с фолбэком Settings (T-619-паттерн)."""
    return hot.get(f"limits.{name}",
                   getattr(settings, name.upper(), _MISSING))


def relations_limits() -> dict:
    """Снимок порогов/периодов группы limits_relations (по одному чтению)."""
    return {
        "acquaintance_min_msg": int(_limit("relations_acquaintance_min_msg")),
        "acquaintance_min_days": int(_limit("relations_acquaintance_min_days")),
        "regular_min_msg": int(_limit("relations_regular_min_msg")),
        "regular_min_days": int(_limit("relations_regular_min_days")),
        "veteran_min_msg": int(_limit("relations_veteran_min_msg")),
        "veteran_min_days": int(_limit("relations_veteran_min_days")),
        "hold_absent_days": int(_limit("relations_hold_absent_days")),
        "stage_change_min_days": int(_limit("relations_stage_change_min_days")),
        "downgrade_msg_30d": int(_limit("relations_downgrade_msg_30d")),
        "decay_half_life_days": float(
            _limit("relations_decay_half_life_days") or 14.0),
        "recalc_ttl_minutes": int(_limit("relations_recalc_ttl_minutes")),
        "scan_max_rows": int(_limit("relations_scan_max_rows")),
        "inject_max_chars": int(_limit("relations_inject_max_chars")),
        "api_max_users": int(_limit("relations_api_max_users")),
    }


def decay_weight(now_ts: int, ts: int, half_life_days: float) -> float:
    """Вес сообщения в activity_score: 0.5 ** ((now − ts)/half_life).

    Экспоненциальный decay (spec §3.1.1): сообщение давностью в один
    полураспад (14д) весит 0.5, в два — 0.25 и т.д. Свежие (ts >= now) —
    1.0; half_life <= 0 → консервативный дефолт 14д (деградация без падения).
    """
    if ts >= now_ts:
        return 1.0
    half_life = (float(half_life_days) or 14.0) * 86400.0
    if half_life <= 0:
        half_life = 14.0 * 86400.0
    return 0.5 ** ((now_ts - ts) / half_life)


def stage_candidate(
    msg_total: int,
    days_in_chat: int,
    *,
    acquaintance_min_msg: int = 10,
    acquaintance_min_days: int = 7,
    regular_min_msg: int = 200,
    regular_min_days: int = 90,
    veteran_min_msg: int = 1000,
    veteran_min_days: int = 365,
) -> str:
    """Кандидат авто-стадии: конъюнкция (msg_total И days_in_chat) сверху
    вниз; недобор по любой паре → ступень ниже (stranger — иначе)."""
    if msg_total >= veteran_min_msg and days_in_chat >= veteran_min_days:
        return STAGE_VETERAN
    if msg_total >= regular_min_msg and days_in_chat >= regular_min_days:
        return STAGE_REGULAR
    if msg_total >= acquaintance_min_msg and days_in_chat >= acquaintance_min_days:
        return STAGE_ACQUAINTANCE
    return STAGE_STRANGER


def decide_stage(
    prev_stage: str,
    candidate: str,
    *,
    now: int,
    last_seen: int | None,
    last_stage_change: int | None,
    msg_30d: int,
    hold_absent_days: int = 60,
    stage_change_min_days: int = 30,
    downgrade_msg_30d: int = 10,
) -> tuple[str, bool]:
    """Итоговая стадия с анти-откатом (Q5): (stage, changed).

    Повышение/равенство — сразу. Понижение допустимо только если:
    (1) юзер не отсутствовал дольше hold_absent_days (иначе стадия держится,
        падает только activity_score);
    (2) прошло >= stage_change_min_days с last_stage_change (или смены не
        было вовсе);
    (3) msg_30d < downgrade_msg_30d (юзер не «просто в отпуске», а реально
        остыл);
    и не более чем на 1 ступень за раз (veteran→regular, никогда
    veteran→stranger). last_stage_change = now при любом изменении."""
    prev_rank = STAGE_RANK.get(str(prev_stage or ""), STAGE_RANK[STAGE_STRANGER])
    cand_rank = STAGE_RANK.get(str(candidate or ""), prev_rank)
    if cand_rank >= prev_rank:
        return candidate, candidate != prev_stage
    if last_seen is None or now - last_seen > hold_absent_days * 86400:
        return prev_stage, False
    if (last_stage_change is not None
            and now - last_stage_change < stage_change_min_days * 86400):
        return prev_stage, False
    if msg_30d >= downgrade_msg_30d:
        return prev_stage, False
    downgraded = STAGES[max(0, prev_rank - 1)]
    return downgraded, downgraded != prev_stage


# ── RelationsService: ленивый пересчёт + чтение (SQLite) + manual из PG ────

_CACHE_TTL_SECONDS = 60.0   # spec §3.1.2: RAM-кэш per chat (TTL 60 с)


class RelationsService:
    """Сервис отношений (spec §3.1.2/§3.1.4; T-817).

    db — DatabaseService (обязателен; users_meta/SQL-агрегаты). aliases —
    AliasResolver|None (имена в снапшоте). store/cache — PG-компоненты лора
    (manual_stage/note через `chat_profiles.relations`); недоступны/ошибка →
    manual-часть пуста (fail-open), авто-стадия работает.

    Публичный контракт:
      * ensure_fresh(chat_id, user_ids=None, *, force=False) -> dict[int, dict]
        — строки users_meta по ключу user_id, с ленивым пересчётом (RAM-TTL
        60 с + db-гейт last_recalc_at > relations_recalc_ttl_minutes);
      * get_user_relation(chat_id, user_id) -> dict | None — скор/стадия +
        manual-мерж (stage = manual ?? auto);
      * stage_for(chat_id, user_id) -> str — итоговая стадия (для инжекта);
      * get_relations_snapshot(chat_id, *, user_ids=None, names=None)
        -> list[dict] — строки для блока `<user_relations>`/API-списка
        (сортировка last_seen DESC, None в конце).
    ВСЕ методы fail-open на PG-части; ошибки db НЕ глотаются (решает
    вызывающий, NFR-4).
    """

    def __init__(self, db, aliases=None, store=None, cache=None,
                 ttl_seconds: float = _CACHE_TTL_SECONDS):
        self._db = db
        self._aliases = aliases
        self._store = store
        self._cache = cache
        self._ttl = ttl_seconds
        self._rows: dict[int, tuple[float, dict[int, dict]]] = {}
        self._lock = asyncio.Lock()

    @property
    def db(self):
        return self._db

    # ── внутреннее ─────────────────────────────────────────────────────────

    def _cached(self, chat_id: int) -> dict[int, dict] | None:
        entry = self._rows.get(chat_id)
        if entry is None:
            return None
        mono, rows = entry
        if time.monotonic() - mono >= self._ttl:
            return None
        return rows

    def _display_name(self, user_id: int) -> str:
        aliases = self._aliases
        if aliases is not None and hasattr(aliases, "resolve"):
            try:
                name = aliases.resolve(user_id)
                if name:
                    return str(name)
            except Exception:
                logger.warning("[user_relations] name resolve failed — uid "
                               "fallback | user_id=%s", user_id, exc_info=True)
        return str(user_id)

    async def _manual_relations(self, chat_id: int) -> dict:
        """{str(user_id): {"manual_stage", "note", ...}} из PG (Q1).

        Порядок источника: LoreProfile-кэш (дедуп с _chat_lore_state на 1
        запрос) → store.get_relations; PG нет/ошибка/профиля нет → {}."""
        try:
            if self._cache is not None:
                profile = await self._cache.get(chat_id)
                if profile is not None:
                    rel = getattr(profile, "relations", None) or {}
                    return dict(rel)
            if self._store is not None:
                return await self._store.get_relations(chat_id)
        except Exception:
            logger.warning(
                "[user_relations] PG relations недоступны — fail-open (пусто) "
                "| chat_id=%s", chat_id, exc_info=True)
        return {}

    # ── чтение/пересчёт ────────────────────────────────────────────────────

    async def ensure_fresh(self, chat_id: int, user_ids=None, *,
                           force: bool = False) -> dict[int, dict]:
        """Строки users_meta чата (ключ user_id), гарантируя свежесть
        запрошенных юзеров: RAM-TTL 60 с; протухшие/отсутствующие строки
        пересчитываются db.refresh_users_meta (по user_ids, если задан;
        без списка — refresh топ-N чата). Возврат — dict[user_id -> row]."""
        requested = None
        if user_ids is not None:
            requested = {int(uid) for uid in user_ids if uid}
        rows = self._cached(chat_id)
        if not force:
            if rows is not None:
                if requested is None or requested <= set(rows):
                    return dict(rows)
        now_wall = int(time.time())
        meta = await self._db.get_users_meta(chat_id, user_ids=requested)
        if requested is not None:
            meta_rows = {row["user_id"]: row for row in meta}
            ttl = relations_limits()["recalc_ttl_minutes"] * 60
            stale = sorted(
                uid for uid in requested
                if (row := meta_rows.get(uid)) is None
                or now_wall - int(row.get("last_recalc_at") or 0) >= ttl)
            if stale or force:
                await self._db.refresh_users_meta(chat_id, user_ids=stale,
                                                  now=now_wall)
        else:
            if not rows or force:
                await self._db.refresh_users_meta(chat_id, now=now_wall)
        fetched = await self._db.get_users_meta(chat_id, user_ids=requested)
        fresh = {row["user_id"]: row for row in fetched}
        async with self._lock:
            self._rows[chat_id] = (time.monotonic(), dict(fresh))
        return dict(fresh)

    async def get_user_relation(self, chat_id: int, user_id: int) -> dict | None:
        """Карточка юзера: авто-строка users_meta + manual из PG (если есть).
        stage = manual_stage ?? relationship_stage (Q5 п.4: manual блокирует
        авто; relationship_stage/last_stage_change НЕ трогаются). Дополнительно
        msg30 — COUNT сообщений за 30д-окно (D-14: карточка `<user_relations>`
        = «{N} сообщ. за 30 дней»); счётчик best-effort (ошибка → 0, WARNING)."""
        rows = await self.ensure_fresh(chat_id, [user_id])
        row = rows.get(int(user_id))
        if row is None:
            return None
        result = dict(row)
        manual = (await self._manual_relations(chat_id)).get(str(user_id))
        entry = manual if isinstance(manual, dict) else None
        manual_stage = entry.get("manual_stage") if entry else None
        result["note"] = entry.get("note") if entry else None
        result["manual_stage"] = manual_stage
        result["manual_updated_by"] = entry.get("updated_by") if entry else None
        result["manual_updated_at"] = entry.get("updated_at") if entry else None
        auto = result.get("relationship_stage") or STAGE_STRANGER
        result["stage_auto"] = auto
        result["stage_manual"] = manual_stage
        result["stage"] = manual_stage or auto
        result["msg30"] = await self._msg30(chat_id, int(user_id))
        return result

    async def _msg30(self, chat_id: int, user_id: int) -> int:
        """COUNT сообщений юзера за 30 дней (D-14, fail-open → 0)."""
        count_method = getattr(self._db, "count_user_msg30", None)
        if count_method is None:
            return 0
        try:
            return int(await count_method(chat_id, user_id) or 0)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[user_relations] msg30 count failed — 0 | chat=%s user=%s",
                chat_id, user_id, exc_info=True)
            return 0

    async def stage_for(self, chat_id: int, user_id: int) -> str:
        """Итоговая стадия (manual ?? auto) для инжекта; нет данных →
        stranger (fail-open, 0 влияния)."""
        relation = await self.get_user_relation(chat_id, user_id)
        if relation is None:
            return STAGE_STRANGER
        return relation.get("stage") or STAGE_STRANGER

    async def get_relations_snapshot(self, chat_id: int, *, user_ids=None,
                                     names: dict | None = None) -> list[dict]:
        """Строки блока `<user_relations>`/API: {user_id, name, stage,
        stage_auto, stage_manual, activity_score, msg_count, active_days,
        first_seen, last_seen, note}. names: {user_id: display} (roster-
        каскад готовит вызывающий); сортировка last_seen DESC (None — в
        конце, стабильно по user_id)."""
        rows = await self.ensure_fresh(chat_id, user_ids=user_ids)
        manual = await self._manual_relations(chat_id)
        out: list[dict] = []
        for user_id in sorted(rows):
            row = rows[user_id]
            entry = manual.get(str(user_id)) if isinstance(manual, dict) else None
            manual_stage = None
            if isinstance(entry, dict):
                manual_stage = entry.get("manual_stage")
            auto = row.get("relationship_stage") or STAGE_STRANGER
            if names is not None and int(user_id) in names:
                name = str(names[int(user_id)])
            else:
                name = self._display_name(int(user_id))
            out.append({
                "user_id": int(user_id),
                "name": name,
                "stage_auto": auto,
                "stage_manual": manual_stage,
                "stage": manual_stage or auto,
                "activity_score": float(row.get("activity_score") or 0.0),
                "msg_count": int(row.get("msg_count") or 0),
                "active_days": int(row.get("active_days") or 0),
                "first_seen": row.get("first_seen"),
                "last_seen": row.get("last_seen"),
                "note": (entry or {}).get("note")
                if isinstance(entry, dict) else None,
            })
        out.sort(key=lambda item: (item["last_seen"] is None,
                                   -(item["last_seen"] or 0), item["user_id"]))
        return out

    # ── инвалидация/диагностика ────────────────────────────────────────────

    async def invalidate(self, chat_id: int) -> None:
        """Сброс RAM-кэша чата (NOTIFY lore_updated / служебно)."""
        async with self._lock:
            self._rows.pop(chat_id, None)

    async def invalidate_all(self) -> None:
        """Полный сброс (тесты/shutdown)."""
        async with self._lock:
            self._rows.clear()

    def size(self) -> int:
        """Число закэшированных чатов (диагностика)."""
        return len(self._rows)
