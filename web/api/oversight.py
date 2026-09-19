"""Раунд 10 (global-oversight-dashboard, F-12 §4/§5) — API Oversight.

Все эндпоинты: 401 без initData; 403 не-глобальный (requires_global_admin);
404 неизвестный чат; 422 feature ∉ домена; 409 optimistic
{code:'conflict', current_updated_at}. Kill-switch и запрет глобального
ключа — ЕДИНЫЕ пути записи (feature_gates.set_feature_gate /
chat_params.set_chat_params keys.allow_global): приоритет совпадает с
F-7/F-10 (явный chat-гейт > глобальный флаг > False). R17: без сырых
ключей (только статусы own/global/forbidden/none + last4 своего own).
"""
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from services import (chat_params, feature_gates, lore_runtime, oversight,
                      summary_aliases)
from services.chat_params import ChatParamsConflict
from services.database import row_get
from web.api.deps import get_cache, get_tma_user, requires_global_admin

logger = logging.getLogger(__name__)

oversight_router = APIRouter()

# F4 (10.24, ADR-1024-8 D2): горизонт обратного резолва имени участника
# (совпадает с `web/api/chat_lore.py::_participant_names` — окно 30 дней).
_FEED_RESOLVE_WINDOW_DAYS = 30
_FEED_RESOLVE_CAP = 200


def _feed_key(value) -> str:
    """Ключ сопоставления имён ленты: strip + casefold (канон-имя может
    отличаться регистром/пробелами от `target_user`)."""
    return str(value or "").strip().casefold()


async def _feed_user_index_one(db, chat_id: int, since_ts: int) -> dict:
    """Обратная карта «имя(casefold) → (user_id, канон-имя)» ОДНОГО чата.

    Источник — активные участники (`get_active_participants`, тот же вызов,
    что у `_participant_names`), поверх — `AliasResolver` (канон алиасов).
    Порядок строк БД (cnt DESC, user_id ASC) задаёт приоритет при коллизии
    имён детерминированно: первым побеждает более активный (меньший uid)."""
    rows = await db.get_active_participants(
        chat_id, since_ts, _FEED_RESOLVE_CAP)
    pairs: list = []
    for r in rows:
        uid = row_get(r, "user_id")
        if not uid:
            continue
        pairs.append((int(uid), str(row_get(r, "author_name") or "").strip()))
    if not pairs:
        return {}
    try:
        resolver = await summary_aliases.build_alias_resolver(chat_id)
    except Exception:
        logger.warning("[oversight] dossier_feed alias-резолв не удался — "
                       "имена как есть | chat=%s", chat_id, exc_info=True)
        resolver = None
    index: dict = {}
    for uid, author in pairs:
        canon = author
        if resolver is not None:
            try:
                resolved = resolver.resolve(uid, author or None, None)
            except Exception:
                resolved = None
            if resolved and str(resolved) != str(uid):
                canon = str(resolved)
        if not canon:
            continue
        # Сырое имя и канон указывают на одного участника — первый побеждает.
        for key in {_feed_key(author), _feed_key(canon)}:
            if key:
                index.setdefault(key, (uid, canon))
    return index


async def _feed_user_index(db, chat_ids: list) -> dict:
    """Кэш резолва в пределах запроса: один проход на chat_id, не на строку.
    Fail-open: ошибка чата → пустая карта (строка останется с `user_id=null`)."""
    index: dict = {}
    since_ts = int(time.time()) - _FEED_RESOLVE_WINDOW_DAYS * 86400
    for cid in chat_ids:
        try:
            index[cid] = await _feed_user_index_one(db, cid, since_ts)
        except Exception:
            logger.warning("[oversight] dossier_feed resolve failed — "
                           "user_id=null | chat=%s", cid, exc_info=True)
            index[cid] = {}
    return index


class KillswitchBody(BaseModel):
    feature: str
    enabled: bool
    expected_updated_at: str | None = None


class GlobalKeyBody(BaseModel):
    allow: bool
    expected_updated_at: str | None = None


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


async def _require_chat_exists(cache, chat_id: int) -> None:
    """ФИКС S-F12 (spec §4): 404 для неизвестного chat_id (409 остаётся
    только для конфликтов версии; раньше несуществующий чат давал 409)."""
    pool = _pool(cache)
    if pool is None:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM chat_profiles WHERE chat_id = $1", chat_id)
    except Exception:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    if row is None:
        raise HTTPException(status_code=404, detail="чат не найден")


@oversight_router.get("/summary")
async def oversight_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Сводка всех чатов (F-12 §4): кэш сервера 60 с; PG down → errors."""
    cache = get_cache(request)
    data = await oversight.build_summary(cache.pg)
    data["cached"] = "60s-server-cache"      # UI-mark; polling НЕ добавляем
    return data


@oversight_router.get("/chat/{chat_id}")
async def oversight_chat(
    chat_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Детали чата (модалка): summary + admins + 5 записей истории."""
    cache = get_cache(request)
    store = lore_runtime.get_lore_store()
    details = await oversight.get_chat_details(cache.pg, chat_id,
                                               store=store)
    if details is None:
        raise HTTPException(status_code=404, detail="чат не найден")
    return details


@oversight_router.post("/chat/{chat_id}/killswitch")
async def oversight_killswitch(
    chat_id: int,
    request: Request,
    payload: KillswitchBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Kill-switch фичи (F-12 §3): запись gates[feature] через
    set_feature_gate (единый путь с F-10); response {feature, enabled,
    previous, updated_at}; 409 optimistic; 422 feature ∉ домена."""
    cache = get_cache(request)
    if payload.feature not in feature_gates.ALL_GATED_FEATURES:
        raise HTTPException(status_code=422,
                            detail=f"неизвестная фича: {payload.feature}")
    await _require_chat_exists(cache, chat_id)      # 404 неизвестный чат
    root = await chat_params.get_all_chat_params(chat_id)
    previous = bool((root.get("gates") or {}).get(
        payload.feature,
        await feature_gates.gates_enabled(
            chat_id, payload.feature, root=root,
            fallback=await feature_gates.master_fallback(
                chat_id, payload.feature))))
    new_root = None
    try:
        new_root = await feature_gates.set_feature_gate(
            chat_id, payload.feature, payload.enabled,
            changed_by=user.id, pg=cache.pg,
            expected_updated_at=payload.expected_updated_at)
    except ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    oversight.invalidate_summary()
    # ФИКС S-F12: updated_at — АКТУАЛЬНАЯ метка профиля (gates-запись
    # идёт через set_chat_params → updated_at chat_profiles; meta.updated_at
    # отсутствует — раньше возвращался вечный None).
    updated_at = await chat_params.get_chat_updated_at(chat_id)
    logger.info(
        "[oversight] killswitch | chat=%s feature=%s enabled=%s "
        "previous=%s by=%s", chat_id, payload.feature, payload.enabled,
        previous, user.id)
    return {"feature": payload.feature, "enabled": payload.enabled,
            "previous": previous,
            "updated_at": updated_at}


@oversight_router.post("/chat/{chat_id}/global_key")
async def oversight_global_key(
    chat_id: int,
    request: Request,
    payload: GlobalKeyBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Запрет/разрешение глобального ключа чата: chat_params.keys.
    allow_global (JSONB, F-7 §4.2); собственными ключами не запрещается."""
    cache = get_cache(request)
    await _require_chat_exists(cache, chat_id)      # 404 неизвестный чат
    root = await chat_params.get_all_chat_params(chat_id)
    keys_ns = dict(root.get("keys") or {})
    previous = bool(keys_ns.get("allow_global", True))
    if previous == bool(payload.allow):
        return {"allow": previous, "previous": previous,
                "updated_at": await chat_params.get_chat_updated_at(chat_id),
                "noop": True}
    keys_ns["allow_global"] = bool(payload.allow)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        new_root = await chat_params.set_chat_params(
            chat_id, {"keys": keys_ns, "meta": meta},
            changed_by=user.id, pg=cache.pg,
            expected_updated_at=payload.expected_updated_at)
    except ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    oversight.invalidate_summary()
    logger.info(
        "[oversight] global_key | chat=%s allow=%s previous=%s by=%s",
        chat_id, payload.allow, previous, user.id)
    return {"allow": payload.allow, "previous": previous,
            "updated_at": await chat_params.get_chat_updated_at(chat_id)}


@oversight_router.get("/dossier_feed")
async def dossier_feed(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    chat_id: int | None = None,
    limit: int = Query(default=12, ge=1, le=40),
):
    """Раунд 10.20 (БЛОК 3.3/T-1897): «Живая лента досье».

    GLOBAL (chat_id пуст) → случайные выдержки-факты по всем чатам; конкретный
    чат → только его участники. Источник — graph_facts (те же данные, что у
    досье; новых таблиц нет). Fail-open: нет БД/ошибка → пустая лента (200).

    F4 (10.24, ADR-1024-8 D2/D3): аддитивно отдаём `user_id`/`user_name`
    (обратный резолв `target_user` → участник, read-time, без DDL). Нерезолвленное
    имя/ошибка резолва → `user_id=null`, строка остаётся текстом (R16/R17)."""
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"chat_id": chat_id, "items": []}
    try:
        rows = await db.dossier_feed(limit=limit, chat_id=chat_id)
    except Exception:
        logger.warning("[oversight] dossier_feed failed — пустая лента | "
                       "chat=%s", chat_id, exc_info=True)
        return {"chat_id": chat_id, "items": []}
    chat_ids: list = []
    for row in rows:
        cid = int(row.get("chat_id") or 0)
        if cid and cid not in chat_ids:
            chat_ids.append(cid)
    try:
        index = await _feed_user_index(db, chat_ids) if chat_ids else {}
    except Exception:
        logger.warning("[oversight] dossier_feed index failed — "
                       "user_id=null | chats=%s", len(chat_ids), exc_info=True)
        index = {}
    items = []
    for row in rows:
        excerpt = str(row.get("fact") or "").strip()
        name = str(row.get("name") or "").strip()
        if not excerpt or not name:
            continue
        cid = int(row.get("chat_id") or 0)
        hit = index.get(cid, {}).get(_feed_key(name))
        items.append({
            "chat_id": cid,
            "name": name,
            "excerpt": excerpt[:240],
            # F4/R16: аддитивные поля; при неудаче резолва — null/имя как есть.
            "user_id": hit[0] if hit else None,
            "user_name": hit[1] if hit else name,
        })
    return {"chat_id": chat_id, "items": items}
