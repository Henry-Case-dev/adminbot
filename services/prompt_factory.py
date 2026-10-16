"""SOUL-1 / W1 — Factory Defaults: заводские редакции, возврат и история.

Нормативная база:
  * ``source-architectural-clarification.md`` §4.1–4.6 — все новые промпты
    SOUL-1 поставляются как **версионированные заводские редакции**;
    runtime использует эффективную активную конфигурацию, а не скрытый
    кодовый дубль; для каждого блока работает «Вернуть заводской вариант»
    (diff → новая active-ревизия → предыдущие ревизии сохранены);
    «Сбросить переопределение чата» ≠ заводской сброс; глобальный сброс
    не удаляет локальные overrides; обновление приложения может
    *предложить* новую заводскую версию, но не перезаписывает правки владельца;
  * ``design-source-of-truth.md`` §3 п.1/п.5 — переиспользуется существующий
    контур ``bot_settings`` (``ConfigCache``/RBAC) и optimistic-токен
    ``updated_at``; история глобальных ключей внутри ``bot_settings`` (одна
    аддитивная JSON-запись), новый config service НЕ создаётся;
  * ``prompt_registry`` — реестр блоков и фабричных ревизий.

Семантика (проверяется тестами ``tests/test_soul1_factory_defaults.py``):
  * ``plan_factory_reset``  — предпросмотр и diff, НИЧЕГО не пишет;
  * ``apply_factory_reset`` — записывает заводской текст как НОВУЮ активную
    ревизию; предыдущее значение (если оно было) сохраняется в историю
    ``character.prompt_history`` (append-only, bounded);
  * ``reset_chat_override`` — только снимает per-chat override (наследование
    глобального значения); НЕ трогает глобальный ключ и НЕ является
    заводским сбросом;
  * ``apply_speech_profile_reset`` — предпросмотр + сброс набора речевых
    блоков; чаты и данные бота не затрагиваются (память, SelfModel,
    биография, ключи, бюджеты не входят в набор);
  * ``restore_backup`` — обратный путь: значения из аварийной копии W1
    (``evidence/w1/backup-speech-config.json``) возвращаются в PG
    идемпотентно и с записью в историю; старое речевое значение при этом
    возвращается как ДАННЫЕ (``effective_layer=withheld_factory_governs``),
    действующим слоем остаётся заводская редакция (SOUL-AMD.1.2/4.6);
  * ``write_speech_value`` — единственный путь, делающий значение
    действующим: правка владельца через API реестра (журнал провенанса
    ``character.prompt_history.provenance``; глобальный ключ или per-chat
    override).

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.4.1/4.2/4.3/4.5 (soul-1, слайс W1)
"""
from __future__ import annotations

import datetime
import difflib
import json
import logging

from services import prompt_registry as pr

logger = logging.getLogger(__name__)

#: Аддитивная история ревизий речевых блоков (одна строка bot_settings).
#: Обоснование: у ``bot_settings`` истории нет (``design-source-of-truth`` §3
#: п.5), а заводить таблицу/сервис запрещено — поэтому bounded-история внутри
#: одной JSON-записи, как и ``character.migration_snapshots`` в дизайне.
#: Внутри документа два независимых раздела:
#:   * ``items`` — ЗАМЕНЁННЫЕ ревизии (rollback-лестница, bounded);
#:   * ``provenance`` — последняя ревизия блока, записанная API реестра
#:     (провенанс: чем можно доверять как действующим слоем, SOUL-AMD.1.2/4.6).
FACTORY_HISTORY_KEY = pr.PROVENANCE_DOC_KEY
FACTORY_HISTORY_CATEGORY = "content"
HISTORY_MAX_PER_BLOCK = 12
HISTORY_VERSION = 1


class FactoryConflict(Exception):
    """Optimistic-конфликт: значение изменилось между diff и записью."""

    def __init__(self, pg_key: str, expected: str | None,
                 current: str | None) -> None:
        super().__init__(f"factory reset conflict: {pg_key}")
        self.pg_key = pg_key
        self.expected = expected
        self.current = current


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _default_cache():
    from services import hot_config as hot
    return hot.get_config_cache()


def factory_default(block_id: str) -> str:
    """Заводской текст блока (единый источник — код-канон каталога/модуля)."""
    return pr.factory_text(block_id)


def _diff_summary(before: str, after: str) -> dict:
    rows = list(difflib.unified_diff((before or "").splitlines(),
                                     (after or "").splitlines(), lineterm="",
                                     n=0))
    added = sum(1 for row in rows if row.startswith("+") and
                not row.startswith("+++"))
    removed = sum(1 for row in rows if row.startswith("-") and
                  not row.startswith("---"))
    return {"added_lines": added, "removed_lines": removed}


async def _load_history(cache) -> dict:
    raw = None
    try:
        raw = cache.get(FACTORY_HISTORY_KEY, None)
    except Exception:          # pragma: no cover — PG down
        raw = None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
    if not isinstance(raw, dict):
        return {"v": HISTORY_VERSION, "items": {}}
    items = raw.get("items")
    if not isinstance(items, dict):
        raw["items"] = {}
    raw.setdefault("v", HISTORY_VERSION)
    return raw


async def _append_history(cache, block_id: str, *, pg_key: str,
                          value: str, source: str, kind: str,
                          actor=None, reason: str = "") -> int:
    """Добавить ревизию в историю (bounded). Возвращает число записей блока."""
    doc = await _load_history(cache)
    entry = {
        "revision": pr.ACTIVE_PREFIX + pr.sha12(value),
        "sha256_12": pr.sha12(value),
        "chars": len(value or ""),
        "text": value,
        "source": source,
        "kind": kind,                 # factory_reset | backup_restore | legacy_strip
        "at": _utc_now(),
        "by": str(actor) if actor is not None else "",
        "reason": reason,
    }
    items = doc["items"].setdefault(block_id, [])
    if items and items[-1].get("sha256_12") == entry["sha256_12"]:
        return len(items)                 # идемпотентно: та же ревизия
    items.append(entry)
    del items[:-HISTORY_MAX_PER_BLOCK]
    doc["items"][block_id] = items
    doc["v"] = HISTORY_VERSION
    if cache is not None and hasattr(cache, "set"):
        try:
            await cache.set(FACTORY_HISTORY_KEY, doc,
                            FACTORY_HISTORY_CATEGORY)
        except Exception:      # pragma: no cover — история не роняет сброс
            logger.warning("[prompt_factory] история не записана | block=%s",
                           block_id, exc_info=True)
    logger.info("[prompt_factory] history +1 | block=%s | kind=%s | chars=%d",
                block_id, kind, len(value or ""))
    return len(items)


async def _mark_provenance(cache, block_id: str, *, pg_key: str, value: str,
                           kind: str, actor=None, reason: str = "",
                           scope: str = "global",
                           chat_id: int | None = None) -> tuple[dict, bool]:
    """Отметить ревизию как записанную API реестра (провенанс).

    Провенанс — то, что делает сохранённое значение ДЕЙСТВУЮЩИМ слоем
    (SOUL-AMD.1.2/4.6): без него persisted-значение канона старой личности
    удерживается резолвером (``prompt_registry.resolve_speech_value``), а
    заводская редакция продолжает работать. Аварийный ``backup_restore``
    провенанса не даёт — старое значение возвращается как данные.

    Возвращает ``(entry, persisted)``: ``persisted=False`` означает, что
    журнал записать не удалось (PG down) — вызывающий обязан показать это
    вызывающему, а не считать правку действующей.
    """
    entry = {
        "revision": pr.ACTIVE_PREFIX + pr.sha12(value),
        "sha256_12": pr.sha12(value),
        "chars": len(value or ""),
        "kind": kind,                  # owner_edit | factory_reset
        "scope": scope,               # global | chat
        "chat_id": int(chat_id) if chat_id is not None else None,
        "at": _utc_now(),
        "by": str(actor) if actor is not None else "",
        "reason": reason,
        "block_id": block_id,
        "pg_key": pg_key,
    }
    if cache is None or not hasattr(cache, "set"):
        return entry, False
    doc = await _load_history(cache)
    provenance = doc.get(pr.PROVENANCE_MAP_FIELD)
    if not isinstance(provenance, dict):
        provenance = {}
    provenance[block_id] = entry
    doc[pr.PROVENANCE_MAP_FIELD] = provenance
    doc["v"] = HISTORY_VERSION
    persisted = True
    try:
        await cache.set(FACTORY_HISTORY_KEY, doc, FACTORY_HISTORY_CATEGORY)
    except Exception:          # pragma: no cover — PG down
        persisted = False
        logger.warning("[prompt_factory] провенанс не записан | block=%s",
                       block_id, exc_info=True)
    logger.info("[prompt_factory] provenance | block=%s | kind=%s | scope=%s "
                "| sha=%s | persisted=%s", block_id, kind, scope,
                entry["sha256_12"], persisted)
    return entry, persisted


async def history_for(block_id: str, *, cache=None) -> list[dict]:
    """Ревизии блока (без текста? — текст остаётся: rollback-контракт)."""
    cache = cache if cache is not None else _default_cache()
    if cache is None:
        return []
    doc = await _load_history(cache)
    return list(doc["items"].get(block_id, []))


async def plan_factory_reset(block_id: str, *, cache=None) -> dict:
    """Предпросмотр «Вернуть заводской вариант»: diff, БЕЗ записи."""
    spec = pr.block(block_id)
    cache = cache if cache is not None else _default_cache()
    factory = factory_default(block_id)
    if spec is None or not spec.pg_key:
        return {"block_id": block_id, "pg_key": "", "applies": False,
                "reason": "block_not_pg_managed", "changed": False}
    current = None
    present = False
    if cache is not None:
        try:
            current = cache.get(spec.pg_key, None)
            present = current is not None
        except Exception:      # pragma: no cover — PG down
            current = None
    effective = str(current) if present else None
    changed = (effective is not None) and (effective != factory)
    return {
        "block_id": block_id,
        "pg_key": spec.pg_key,
        "applies": True,
        "changed": changed,
        "source": "global" if present else "default",
        "current_present": present,
        "current_chars": len(effective or ""),
        "current_sha256_12": pr.sha12(effective or "") if present else "",
        "factory_chars": len(factory),
        "factory_sha256_12": pr.sha12(factory),
        "factory_revision": pr.factory_revision(block_id),
        "diff": _diff_summary(effective or "", factory),
        "revision_note": "запись создаст НОВУЮ активную ревизию; предыдущая "
                         "остаётся в истории " + FACTORY_HISTORY_KEY,
    }


async def apply_factory_reset(block_id: str, *, cache=None,
                              expected_updated_at: str | None = None,
                              actor=None, reason: str = "") -> dict:
    """Вернуть заводской вариант: diff уже показан вызывающим (W6 UI)."""
    spec = pr.block(block_id)
    cache = cache if cache is not None else _default_cache()
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    if cache is None:
        return {"applied": False, "reason": "config_cache_unavailable",
                "block_id": block_id}
    factory = factory_default(block_id)
    current = cache.get(spec.pg_key, None)
    if expected_updated_at is not None:
        actual = None
        try:
            actual = cache.get_updated_at(spec.pg_key)
        except Exception:      # pragma: no cover
            actual = None
        if actual != expected_updated_at:
            raise FactoryConflict(spec.pg_key, expected_updated_at, actual)
    if current is not None and current == factory:
        return {"applied": False, "reason": "already_factory",
                "block_id": block_id, "pg_key": spec.pg_key,
                "revision": pr.ACTIVE_PREFIX + pr.sha12(factory),
                "factory_revision": pr.factory_revision(block_id)}
    previous = str(current) if current is not None else ""
    if current is not None:
        await _append_history(cache, block_id, pg_key=spec.pg_key,
                              value=previous, source="global",
                              kind="factory_reset", actor=actor,
                              reason=reason or "factory_reset")
    # Провенанс: ревизия записана API реестра ⇒ является действующим слоем
    # (после заводского сброса это и так заводской текст — отметка убирает
    # ложную диагностику удержания, SOUL-AMD.1.2/4.6).
    await _mark_provenance(cache, block_id, pg_key=spec.pg_key, value=factory,
                           kind="factory_reset", actor=actor,
                           reason=reason or "factory_reset", scope="global")
    await cache.set(spec.pg_key, factory, "prompts")
    logger.info("[prompt_factory] factory reset | block=%s | key=%s | "
                "was=%s | now=%s", block_id, spec.pg_key,
                pr.sha12(previous), pr.sha12(factory))
    return {
        "applied": True,
        "block_id": block_id,
        "pg_key": spec.pg_key,
        "changed": previous != factory,
        "previous_revision": pr.ACTIVE_PREFIX + pr.sha12(previous) if previous
        else "",
        "revision": pr.ACTIVE_PREFIX + pr.sha12(factory),
        "factory_revision": pr.factory_revision(block_id),
        "history_key": FACTORY_HISTORY_KEY,
        "chat_overrides_touched": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Правка владельца через API реестра (W6-готовый writer) + провенанс
# ═══════════════════════════════════════════════════════════════════════════

async def write_speech_value(block_id: str, text: str, *, cache=None,
                             actor=None, reason: str = "",
                             chat_id: int | None = None,
                             expected_updated_at: str | None = None,
                             pg=None, get_root=None, set_root=None) -> dict:
    """Записать речевое значение через API реестра (правка владельца).

    Единственный путь, делающий значение ДЕЙСТВУЮЩИМ слоем (SOUL-AMD.1.1/4.1:
    владелец управляет речью через MiniApp): запись идёт в PG/чат + журнал
    провенанса. Значение, попавшее в PG иным путём (старый UI, SQL), остаётся
    без провенанса и удерживается резолвером (SOUL-AMD.1.2/4.6) — но не
    теряется (stay retrievable) и видно в ``prompt_registry.withheld_values``.

    ``chat_id`` задан → per-chat override (наследование глобала сохраняется);
    иначе — глобальный ключ блока. ``expected_updated_at`` — существующий
    optimistic-токен (``FactoryConflict`` при чужой правке).
    """
    from services import chat_params
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    value = str(text or "")
    if not value.strip():
        return {"applied": False, "reason": "empty_value", "block_id": block_id,
                "pg_key": spec.pg_key}
    if chat_id is not None:
        return await _write_chat_speech_value(
            spec, value, cache=cache, actor=actor, reason=reason,
            chat_id=int(chat_id), expected_updated_at=expected_updated_at,
            pg=pg, get_root=get_root, set_root=set_root)
    cache = cache if cache is not None else _default_cache()
    if cache is None:
        return {"applied": False, "reason": "config_cache_unavailable",
                "block_id": block_id}
    if expected_updated_at is not None:
        actual = None
        try:
            actual = cache.get_updated_at(spec.pg_key)
        except Exception:      # pragma: no cover
            actual = None
        if actual != expected_updated_at:
            raise FactoryConflict(spec.pg_key, expected_updated_at, actual)
    current = cache.get(spec.pg_key, None)
    previous = str(current) if current is not None else ""
    if previous:
        await _append_history(cache, block_id, pg_key=spec.pg_key,
                              value=previous, source="global",
                              kind="owner_edit", actor=actor,
                              reason=reason or "owner_edit")
    # Провенанс — ДО записи значения: успешная запись значения и есть
    # последнее действие (журнал не может «опередить» само значение).
    entry, persisted = await _mark_provenance(
        cache, block_id, pg_key=spec.pg_key, value=value, kind="owner_edit",
        actor=actor, reason=reason or "owner_edit", scope="global")
    await cache.set(spec.pg_key, value, "prompts")
    marker = pr.legacy_persona_present(value)
    if marker:
        logger.warning("[prompt_factory] owner edit несёт маркер старой "
                       "личности | block=%s | sha=%s (правка владельца не "
                       "переписывается, но видна в реестре)",
                       block_id, entry["sha256_12"])
    logger.info("[prompt_factory] owner edit | block=%s | key=%s | sha=%s | "
                "chars=%d", block_id, spec.pg_key, entry["sha256_12"],
                len(value))
    return {
        "applied": True, "block_id": block_id, "pg_key": spec.pg_key,
        "scope": "global", "chat_overrides_touched": False,
        "changed": previous != value,
        "previous_revision": pr.ACTIVE_PREFIX + pr.sha12(previous)
        if previous else "",
        "revision": entry["revision"], "sha256_12": entry["sha256_12"],
        "history_key": FACTORY_HISTORY_KEY,
        "provenance_persisted": persisted,
        "effective": persisted,
        "legacy_persona_marker": marker,
        "provenance": {"kind": entry["kind"], "scope": entry["scope"]},
    }


async def _write_chat_speech_value(spec, value: str, *, cache=None, actor=None,
                                   reason: str = "", chat_id: int,
                                   expected_updated_at: str | None = None,
                                   pg=None, get_root=None,
                                   set_root=None) -> dict:
    """Per-chat override через API реестра (наследование глобала сохраняется)."""
    from services import chat_params
    cache = cache if cache is not None else _default_cache()
    get_root = get_root or chat_params.get_all_chat_params
    set_root = set_root or (lambda chat, patch, **kw:
                            chat_params.set_chat_params(chat, patch, **kw))
    root = await get_root(chat_id, pg=pg) if pg is not None else \
        await get_root(chat_id)
    overrides = dict((root or {}).get("overrides") or {})
    previous = overrides.get(spec.pg_key)
    if previous is not None and str(previous) == value:
        entry, persisted = await _mark_provenance(
            cache, spec.block_id, pg_key=spec.pg_key, value=value,
            kind="owner_edit", actor=actor, reason=reason or "owner_edit",
            scope="chat", chat_id=chat_id)
        return {"applied": False, "reason": "already_that_value",
                "block_id": spec.block_id, "pg_key": spec.pg_key,
                "scope": "chat", "chat_id": chat_id,
                "revision": entry["revision"],
                "provenance_persisted": persisted,
                "history_key": FACTORY_HISTORY_KEY}
    overrides[spec.pg_key] = value
    patch: dict = {"overrides": overrides}
    entry, persisted = await _mark_provenance(
        cache, spec.block_id, pg_key=spec.pg_key, value=value,
        kind="owner_edit", actor=actor, reason=reason or "owner_edit",
        scope="chat", chat_id=chat_id)
    if pg is not None and expected_updated_at is not None:
        await set_root(chat_id, patch, pg=pg,
                       expected_updated_at=expected_updated_at)
    elif pg is not None:
        await set_root(chat_id, patch, pg=pg)
    else:
        await set_root(chat_id, patch)
    logger.info("[prompt_factory] owner edit (chat) | block=%s | key=%s | "
                "chat=%s | sha=%s", spec.block_id, spec.pg_key, chat_id,
                entry["sha256_12"])
    return {
        "applied": True, "block_id": spec.block_id, "pg_key": spec.pg_key,
        "scope": "chat", "chat_id": chat_id, "changed": True,
        "previous_revision": (pr.ACTIVE_PREFIX + pr.sha12(str(previous))
                              if previous is not None else ""),
        "revision": entry["revision"], "sha256_12": entry["sha256_12"],
        "history_key": FACTORY_HISTORY_KEY,
        "provenance_persisted": persisted,
        "effective": persisted,
        "legacy_persona_marker": pr.legacy_persona_present(value),
        "provenance": {"kind": entry["kind"], "scope": entry["scope"]},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Chat-override reset (НЕ заводской сброс) и профильный сброс речи
# ═══════════════════════════════════════════════════════════════════════════

async def reset_chat_override(chat_id: int, block_id: str, *, pg=None,
                              get_root=None, set_root=None,
                              expected_updated_at: str | None = None) -> dict:
    """«Сбросить переопределение чата»: возвращает наследование глобального.

    Контракт SOUL-AMD.4.3: это НЕ заводской сброс. Глобальный ключ не
    изменяется; при отсутствии override — no-op с диагностикой; наследованное
    значение возвращается вызывающему (UI показывает Factory / Global Custom).
    ``expected_updated_at`` (если задан) уходит в существующий optimistic-путь
    ``chat_params.set_chat_params`` (409 при чужой правке).
    """
    from services import chat_params
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    get_root = get_root or chat_params.get_all_chat_params
    set_root = set_root or (lambda chat, patch, **kw: chat_params.set_chat_params(
        chat, patch, **kw))
    root = await get_root(chat_id) or {}
    overrides = dict(root.get("overrides") or {})
    if spec.pg_key not in overrides:
        return {"applied": False, "reason": "no_chat_override",
                "block_id": block_id, "pg_key": spec.pg_key,
                "inherits": _inherit_view(spec.block_id)}
    overrides.pop(spec.pg_key, None)
    patch: dict = {"overrides": overrides}
    if expected_updated_at is not None:
        await set_root(chat_id, patch, pg=pg,
                       expected_updated_at=expected_updated_at)
    else:
        await set_root(chat_id, patch, pg=pg)
    logger.info("[prompt_factory] chat override reset | chat=%s | key=%s",
                chat_id, spec.pg_key)
    return {"applied": True, "block_id": block_id, "pg_key": spec.pg_key,
            "factory_value_written": False,
            "global_value_written": False,
            "inherits": _inherit_view(spec.block_id)}


def _inherit_view(block_id: str) -> dict:
    """Что унаследует чат после снятия override (global → factory)."""
    spec = pr.block(block_id)
    cache = _default_cache()
    value = None
    present = False
    if cache is not None and spec is not None and spec.pg_key:
        try:
            value = cache.get(spec.pg_key, None)
            present = value is not None
        except Exception:      # pragma: no cover
            value = None
    text = str(value) if present else factory_default(block_id)
    resolved = (pr.resolve_speech_value(spec.pg_key, text,
                                       source="global" if present else "default")
                if spec is not None and spec.pg_key else None)
    if resolved is not None and resolved.withheld:
        # Глобальное значение есть, но оно не действует (нет провенанса) →
        # чат унаследует заводскую редакцию; сохранённая ревизия видна.
        return {"source": "Factory",
                "sha256_12": pr.sha12(resolved.text),
                "differs_from_factory": resolved.text != factory_default(
                    block_id),
                "withheld": True,
                "provenance_reason": resolved.provenance_reason,
                "stored_sha256_12": resolved.withheld_sha256_12}
    text, _info = pr.suppress_legacy_speech(
        text, source="global" if present else "default")
    return {"source": "global" if present else "Factory",
            "sha256_12": pr.sha12(text),
            "differs_from_factory": text != factory_default(block_id)}


async def plan_speech_profile_reset(*, cache=None,
                                    block_ids: tuple[str, ...] | None = None
                                    ) -> dict:
    """Предпросмотр сброса всего речевого профиля (SOUL-AMD.4.4, опционально).

    Возвращает список затрагиваемых блоков; НИЧЕГО не пишет. Память, SelfModel,
    биография, отношения, Experience, ключи и бюджеты в набор не входят —
    это отдельные сущности, а не речевые редакции.
    """
    cache = cache if cache is not None else _default_cache()
    targets = block_ids or tuple(b.block_id for b in pr.speech_blocks()
                                if b.pg_key)
    affected: list[dict] = []
    unchanged: list[str] = []
    for block_id in targets:
        spec = pr.block(block_id)
        if spec is None or not spec.pg_key:
            continue
        factory = factory_default(block_id)
        current = None
        if cache is not None:
            try:
                current = cache.get(spec.pg_key, None)
            except Exception:  # pragma: no cover
                current = None
        if current is None or current == factory:
            unchanged.append(block_id)
            continue
        affected.append({"block_id": block_id, "pg_key": spec.pg_key,
                         "current_chars": len(str(current)),
                         "factory_chars": len(factory),
                         "diff": _diff_summary(str(current), factory)})
    return {"applies": True, "affected": affected, "unchanged": unchanged,
            "chat_overrides_touched": False, "data_touched": False,
            "history_key": FACTORY_HISTORY_KEY}


async def apply_speech_profile_reset(*, cache=None, block_ids=None,
                                     expected_updated_at: str | None = None,
                                     actor=None) -> dict:
    """Сброс набора речевых блоков на заводские (только globals)."""
    plan = await plan_speech_profile_reset(cache=cache, block_ids=block_ids)
    report = []
    if expected_updated_at is not None:
        # Единый optimistic-токен для пакетной записи: сверяем по первому
        # затронутому ключу (тот же контракт, что POST /api/config).
        first = (plan["affected"] or [{}])[0].get("pg_key")
        cache_ref = cache if cache is not None else _default_cache()
        if first and cache_ref is not None:
            actual = cache_ref.get_updated_at(first)
            if actual != expected_updated_at:
                raise FactoryConflict(first, expected_updated_at, actual)
    for row in plan["affected"]:
        report.append(await apply_factory_reset(
            row["block_id"], cache=cache, actor=actor,
            reason="speech_profile_reset"))
    return {"applied": [r for r in report if r.get("applied")],
            "skipped": [r for r in report if not r.get("applied")],
            "unchanged": plan["unchanged"],
            "chat_overrides_touched": False}


# ═══════════════════════════════════════════════════════════════════════════
# Обратный путь: восстановление из аварийной копии W1
# ═══════════════════════════════════════════════════════════════════════════

async def restore_backup(backup: dict, *, apply: bool = False, cache=None,
                         actor=None) -> dict:
    """Восстановить ПЕРСИСТЕНТНЫЕ значения из аварийного снимка W1.

    Идемпотентно: значение, уже совпадающее со снимком, не переписывается.
    Каждая запись проходит через историю (``kind=backup_restore``), поэтому
    повторный откат вперёд/назад не теряет ни одной ревизии.
    """
    cache = cache if cache is not None else _default_cache()
    keys = dict((backup or {}).get("keys") or {})
    planned: list[dict] = []
    restore_texts: dict[str, str] = {}
    for key, item in sorted(keys.items()):
        if not isinstance(item, dict):
            continue
        # Восстанавливаем ТОЛЬКО захваченное значение (`text`): заводской
        # текст (`factory_text`) намеренно НЕ используется как источник
        # отката — иначе аварийное восстановление могло бы молча затереть
        # правку владельца, сделанную после снятия копии. Живое значение
        # снимка хранится в `text` (пишется только при доступной PG) либо в
        # `pg_value_at_backup`.
        text = item.get("text")
        if not isinstance(text, str):
            text = item.get("pg_value_at_backup")
        if not isinstance(text, str):
            continue
        current = None
        if cache is not None:
            try:
                current = cache.get(key, None)
            except Exception:  # pragma: no cover
                current = None
        same = (current is not None) and str(current) == text
        restore_texts[key] = text
        spec = pr.by_pg_key(key)
        planned.append({"key": key, "same": same,
                        "backup_sha256_12": pr.sha12(text),
                        "current_sha256_12": (pr.sha12(str(current))
                                              if current is not None else ""),
                        "category": item.get("category") or "prompts",
                        "source_field": ("text" if isinstance(item.get("text"),
                                                              str)
                                         else "pg_value_at_backup"),
                        "withheld_in_runtime": bool(
                            spec is not None and pr.withholding_required(spec))})
    if not apply:
        return {"apply": False, "planned": planned,
                "changed": sum(1 for row in planned if not row["same"]),
                "history_key": FACTORY_HISTORY_KEY}
    applied: list[dict] = []
    for row in planned:
        if row["same"]:
            continue
        text = restore_texts[row["key"]]
        spec = pr.by_pg_key(row["key"])
        if spec is not None:
            await _append_history(cache, spec.block_id, pg_key=row["key"],
                                  value=str(cache.get(row["key"], "") or ""),
                                  source="global", kind="backup_restore",
                                  actor=actor, reason="restore_backup")
        await cache.set(row["key"], text, row["category"])
        applied.append({"key": row["key"],
                        "sha256_12": row["backup_sha256_12"],
                        # SOUL-AMD.4.6: старое значение вернулось как ДАННЫЕ;
                        # действующим речевым слоем оно не становится
                        # (провенанса нет) — заводская редакция продолжает
                        # работать, конфликт виден в prompt_registry.
                        "effective_layer": ("withheld_factory_governs"
                                            if row["withheld_in_runtime"]
                                            else "applied")})
    return {"apply": True, "applied": applied,
            "planned_changed": sum(1 for row in planned if not row["same"]),
            "history_key": FACTORY_HISTORY_KEY,
            "runtime_note": "записи с effective_layer=withheld_factory_governs "
                            "возвращены как данные: старый речевой канон не "
                            "становится действующим слоем (SOUL-AMD.4.6)"}


async def restore_backup_from_file(path: str, *, apply: bool = False,
                                   cache=None, actor=None) -> dict:
    with open(path, encoding="utf-8") as fh:
        backup = json.load(fh)
    return await restore_backup(backup, apply=apply, cache=cache, actor=actor)


# ═══════════════════════════════════════════════════════════════════════════
# CLI (ручные операции владельца/DevOps; PG-путь — только при apply)
# ═══════════════════════════════════════════════════════════════════════════

def _cli(argv: list[str] | None = None) -> int:
    """``py -3 -m services.prompt_factory <report|plan|reset|reset-all|
    history|restore> [args] [--apply]``."""
    import asyncio
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 0
    cmd, rest = args[0], args[1:]
    apply = "--apply" in rest
    rest = [a for a in rest if a != "--apply"]

    async def _run() -> int:
        from services import hot_config as hot
        cache = hot.get_config_cache()
        if cmd == "report":
            for row in pr.registry_view():
                print(f"{row['block_id']:<40} {row['production_kind']:<16} "
                      f"{row['pg_key'] or '-':<52} "
                      f"{row['factory_revision'] or '-'}")
            print(f"blocks={len(pr.registry_view())} "
                  f"fingerprint={pr.factory_set_fingerprint()}")
            return 0
        if cmd == "plan" and rest:
            print(json.dumps(await plan_factory_reset(rest[0], cache=cache),
                             ensure_ascii=False, indent=1))
            return 0
        if cmd == "reset" and rest:
            print(json.dumps(await apply_factory_reset(rest[0], cache=cache),
                             ensure_ascii=False, indent=1))
            return 0
        if cmd == "reset-all":
            if not apply:
                print(json.dumps(await plan_speech_profile_reset(cache=cache),
                                 ensure_ascii=False, indent=1))
                return 0
            print(json.dumps(await apply_speech_profile_reset(cache=cache),
                             ensure_ascii=False, indent=1))
            return 0
        if cmd == "history" and rest:
            print(json.dumps(await history_for(rest[0], cache=cache),
                             ensure_ascii=False, indent=1))
            return 0
        if cmd == "restore" and rest:
            print(json.dumps(await restore_backup_from_file(
                rest[0], apply=apply, cache=cache), ensure_ascii=False,
                indent=1))
            return 0
        print("usage: report | plan <block_id> | reset <block_id> | "
              "reset-all [--apply] | history <block_id> | "
              "restore <backup.json> [--apply]")
        return 2

    return asyncio.run(_run())


__all__ = [
    "FACTORY_HISTORY_KEY", "FACTORY_HISTORY_CATEGORY",
    "HISTORY_MAX_PER_BLOCK", "FactoryConflict", "factory_default",
    "plan_factory_reset", "apply_factory_reset", "write_speech_value",
    "history_for", "reset_chat_override", "plan_speech_profile_reset",
    "apply_speech_profile_reset", "restore_backup", "restore_backup_from_file",
]


if __name__ == "__main__":        # pragma: no cover — ручной CLI
    raise SystemExit(_cli())
