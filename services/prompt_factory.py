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
    ``character.prompt_history`` (append-only, bounded);  * ``reset_chat_override`` — только снимает per-chat override (наследование
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

Блоки-ПОЛЯ JSON-документа (Personality Core, SOUL-AMD.1.1): у
``core.personality`` / ``core.personality.compact`` значение живёт в документе
``character.core`` (поля ``full_text`` / ``compact_text``). Все операции этого
модуля для них документ-осознанные: правка одного поля НИКОГДА не затирает
второе, per-chat правка собирает документ из глобального (наследование
остальных полей), а «Вернуть заводской вариант» возвращает заводской текст
именно этого поля. Правка редакции делает её действующей (``detail_level``
документа), иначе правка «неактивной» версии не имела бы наблюдаемого эффекта.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.4.1/4.2/4.3/4.5 (soul-1, слайс W1)
"""
from __future__ import annotations

import datetime
import difflib
import json
import logging
from typing import Mapping

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

#: Категория записи документа Personality Core (design-source-of-truth §2.1:
#: глобальный `character.core` управляется правом на ключ категории content).
CORE_DOC_CATEGORY = "content"

#: EVOL-016 (контракт §1.2): после одноразового импорта в журнал версий
#: ``character.prompt_history`` замораживается — ``_append_history`` и
#: ``_mark_provenance`` больше не дописывают JSON. Документ не удаляется;
#: обрезанные HISTORY_MAX_PER_BLOCK хвосты не восстанавливаются и не выдаются
#: за полную историю. Флаг выставляет релизная проводка старта каждый раз,
#: когда журнал подтверждён (cutover или no-op-рестарт с целым журналом).
_HISTORY_FROZEN = False


def freeze_history() -> None:
    """Заморозить дописывание журнала ``character.prompt_history``."""
    global _HISTORY_FROZEN
    _HISTORY_FROZEN = True


def history_frozen() -> bool:
    return _HISTORY_FROZEN


class FactoryConflict(Exception):
    """Optimistic-конфликт: значение изменилось между diff и записью."""

    def __init__(self, pg_key: str, expected: str | None,
                 current: str | None) -> None:
        super().__init__(f"factory reset conflict: {pg_key}")
        self.pg_key = pg_key
        self.expected = expected
        self.current = current


# ── Блоки-поля JSON-документа (Personality Core, SOUL-02/AMD.1.1) ───────────
# `character.core` — один документ на scope (design §2.1), два поля которого
# зарегистрированы как два блока реестра. Поэтому чтение/запись/сброс таких
# блоков идут через документ: правка одного поля НИКОГДА не затирает другое,
# а скалярные `prompts.*`-блоки работают ровно как раньше.

def _doc_field(spec) -> str:
    """Имя поля JSON-документа для блока Core ("" — обычный блок)."""
    return str(getattr(spec, "pg_doc_field", "") or "")


def _doc_from_raw(raw) -> dict:
    """JSON-документ из значения слоя (dict/jsonb-строка); {} — документа нет."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8")
                                if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _doc_with_field(document: dict, field: str, text: str, *,
                    set_level: bool = True) -> dict:
    """Документ Core с записанным полем: остальные поля и служебные ключи целы.

    ``set_level`` (по умолчанию True): правка редакции делает ЕЁ действующей —
    владелец правит ту версию, которой хочет говорить; иначе правка
    «неактивной» редакции не давала бы наблюдаемого эффекта, а требование
    «правка Core меняет следующую генерацию» (SOUL-EC/§4.1) не выполнялось бы.
    Уровень остаётся явным полем документа: виден в манифесте и Inspector
    (``level``/``reason``/``active_field``), а не «угадывается» по тексту.
    """
    doc = dict(document or {})
    doc[field] = text
    try:
        previous = int(doc.get("revision") or 0)
    except Exception:          # pragma: no cover — нечисловая ревизия владельца
        previous = 0
    doc["revision"] = previous + 1
    doc["origin"] = "owner_edit"
    doc["updated_at"] = _utc_now()
    if field == "compact_text":
        doc["compact_words"] = len(text.split()) if text else 0
    if set_level:
        doc["detail_level"] = "full" if field == "full_text" else "compact"
    return doc


def _read_spec_value(spec, cache) -> tuple[bool, str, dict]:
    """``(есть_значение_в_слое, текст_значения, документ)`` ГЛОБАЛЬНОГО слоя.

    Скалярный блок → ``(значение есть, значение, {})``; блок-поле →
    ``(документ есть, поле документа или "", документ)``. Документ возвращается
    целиком, чтобы запись не потеряла остальные поля.
    """
    if cache is None:
        return False, "", {}
    try:
        raw = cache.get(spec.pg_key, None)
    except Exception:          # pragma: no cover — PG down
        return False, "", {}
    if raw is None:
        return False, "", {}
    field = _doc_field(spec)
    if not field:
        return True, str(raw), {}
    doc = _doc_from_raw(raw)
    return True, pr.doc_field_text(doc, field), doc


def _value_changed(spec, present: bool, text: str, factory: str) -> bool:
    """Отличается ли ЗАПИСАННОЕ значение блока от заводского (diff/сброс).

    Для блока-поля отсутствующее поле — это уже заводское значение (сброс
    ничего не меняет); для скаляра сохранённое значение сравнивается как есть.
    """
    if _doc_field(spec):
        return bool(text) and text != factory
    return bool(present) and text != factory


async def _store_spec_value(spec, text: str, cache, *, document=None,
                            set_level: bool = True) -> None:
    """Записать значение блока в глобальный слой (скаляр или поле документа)."""
    field = _doc_field(spec)
    if not field:
        await cache.set(spec.pg_key, text, "prompts")
        return
    await cache.set(spec.pg_key,
                    _doc_with_field(document or {}, field, text,
                                    set_level=set_level),
                    CORE_DOC_CATEGORY)


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
    """Добавить ревизию в историю (bounded). Возвращает число записей блока.

    EVOL-016: после заморозки (``freeze_history``) — no-op: ревизии ведёт
    журнал ``prompt_revisions`` (релизная политика), а не этот JSON-документ.
    """
    if _HISTORY_FROZEN:
        return 0
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

    EVOL-016: после заморозки (``freeze_history``) провенанс-факты ведёт
    журнал активаций; здесь — no-op с ``persisted=True`` (запись значения
    не должна ломаться).
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
    if _HISTORY_FROZEN:
        return entry, True
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
    field = _doc_field(spec)
    present, current, _doc = _read_spec_value(spec, cache)
    effective = current if present else None
    changed = _value_changed(spec, present, current, factory)
    return {
        "block_id": block_id,
        "pg_key": spec.pg_key,
        "document_field": field,
        "applies": True,
        "changed": changed,
        "source": "global" if present else "default",
        "current_present": bool(present),
        "current_chars": len(current or ""),
        "current_sha256_12": pr.sha12(current or "") if current else "",
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
    field = _doc_field(spec)
    present, current, document = _read_spec_value(spec, cache)
    if expected_updated_at is not None:
        actual = None
        try:
            actual = cache.get_updated_at(spec.pg_key)
        except Exception:      # pragma: no cover
            actual = None
        if actual != expected_updated_at:
            raise FactoryConflict(spec.pg_key, expected_updated_at, actual)
    if not _value_changed(spec, present, current, factory):
        return {"applied": False, "reason": "already_factory",
                "block_id": block_id, "pg_key": spec.pg_key,
                "revision": pr.ACTIVE_PREFIX + pr.sha12(factory),
                "factory_revision": pr.factory_revision(block_id)}
    previous = current or ""
    if previous:
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
    await _store_spec_value(spec, factory, cache, document=document,
                            set_level=False)
    # EVOL-016: факт «заводской текст снова активен» — в журнал (rev + строка
    # активации), иначе рестарт увидит расхождение журнала и значения.
    try:
        from services import prompt_release_policy as prp
        await prp.record_manual_activation(
            block_id, factory, scope="global", actor=actor,
            reason=reason or "factory_reset", kind="manual_rollback",
            cache=cache)
    except Exception:          # pragma: no cover — журнал не роняет сброс
        logger.warning("[prompt_factory] журнал не зафиксировал заводской "
                       "сброс | block=%s", block_id, exc_info=True)
    logger.info("[prompt_factory] factory reset | block=%s | key=%s | "
                "was=%s | now=%s", block_id, spec.pg_key,
                pr.sha12(previous), pr.sha12(factory))
    return {
        "applied": True,
        "block_id": block_id,
        "pg_key": spec.pg_key,
        "document_field": field,
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
                             set_level: bool = True,
                             pg=None, get_root=None, set_root=None) -> dict:
    """Записать речевое значение через API реестра (правка владельца).

    Единственный путь, делающий значение ДЕЙСТВУЮЩИМ слоем (SOUL-AMD.1.1/4.1:
    владелец управляет речью через MiniApp).

    EVOL-016 (контракт §1.6): правка становится ИММУТАБЕЛЬНОЙ ревизией
    журнала (``origin=manual``) со строкой активации ``kind=manual_edit``;
    ``factory_revision_applied`` не сбрасывается — рестарт без новой метки
    правку не тронет, следующая заводская ревизия снимет её в историю.
    Глобальный слой: ревизия + активация + значение одной транзакцией
    (``prompt_release_policy.write_versioned_value``). Per-chat override:
    запись значения остаётся за ``chat_params`` (его история и локи), журнал
    получает факт активации (best-effort). Журнал недоступен → прежний путь,
    честный признак ``journal_recorded=False``.

    ``chat_id`` задан → per-chat override (наследование глобала сохраняется);
    иначе — глобальный ключ блока. ``expected_updated_at`` — существующий
    optimistic-токен (``FactoryConflict`` при чужой правке). ``set_level``
    False — правка поля документа не меняет выбор владельца ``detail_level``
    (нужно owner-preserving миграции активной редакции Core).
    """
    from services import chat_params
    from services import prompt_release_policy as prp
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    value = str(text or "")
    if not value.strip():
        return {"applied": False, "reason": "empty_value", "block_id": block_id,
                "pg_key": spec.pg_key}
    classification = pr.withheld_classification(block_id, value)
    if classification and classification.get("class") == \
            pr.WITHHELD_LEGACY_CLASS:
        # P0-PROMPTS (24.10.2026): известные legacy-редакции (старая личность /
        # обход ограничений / ослабленный разбор) не активируются даже явной
        # перезаписью. Текст остаётся доступен в сохранённой редакции/истории.
        logger.warning("[prompt_factory] legacy_incompatible edit rejected | "
                       "block=%s | sha=%s", block_id, pr.sha12(value))
        return {"applied": False, "reason": "legacy_incompatible",
                "block_id": block_id, "pg_key": spec.pg_key,
                "detail": classification.get("reason", ""),
                "stored_sha256_12": pr.sha12(value)}
    cache = cache if cache is not None else _default_cache()
    if chat_id is not None:
        # Per-chat: запись значения и optimistic-токен остаются за
        # ``chat_params.set_chat_params`` (его 409-семантика и
        # идемпотентный short-circuit D-409-1 не дублируются здесь).
        legacy = await _write_chat_speech_value(
            spec, value, cache=cache, actor=actor, reason=reason,
            chat_id=int(chat_id), expected_updated_at=expected_updated_at,
            pg=pg, get_root=get_root, set_root=set_root)
        if legacy.get("applied") and cache is not None:
            recorded = await prp.record_manual_activation(
                block_id, value, scope="chat", chat_id=int(chat_id),
                actor=actor, reason=reason or "owner_edit", cache=cache)
            # Ревью (nonblocking): честный флаг — журнал мог не записать.
            legacy["journal_recorded"] = bool(recorded.get("recorded"))
        else:
            legacy.setdefault("journal_recorded", False)
        return legacy
    # Optimistic-токен глобального слоя: общий гейт журнального и
    # легаси-путей (чужая правка → 409-семантика FactoryConflict).
    if expected_updated_at is not None:
        actual = None
        try:
            actual = cache.get_updated_at(spec.pg_key) if cache is not None \
                else None
        except Exception:      # pragma: no cover
            actual = None
        if actual != expected_updated_at:
            raise FactoryConflict(spec.pg_key, expected_updated_at, actual)
    # Журнальный путь (глобальный слой): одна транзакция — ревизия,
    # активация, значение; память кэша обновляет сам write_versioned_value.
    journal = prp.default_journal(cache)
    if journal is not None:
        result = await prp.write_versioned_value(
            block_id, value, cache=cache, store=journal,
            scope="global", chat_id=None, actor=actor,
            reason=reason or "owner_edit")
        if result.get("journal_recorded"):
            return {
                "applied": result.get("applied", False),
                "reason": result.get("outcome", "ok")
                if result.get("applied") else "already_that_value",
                "block_id": block_id, "pg_key": spec.pg_key,
                "scope": "global", "chat_overrides_touched": False,
                "changed": result.get("applied", False),
                "revision": pr.ACTIVE_PREFIX + result.get("sha256_12", ""),
                "sha256_12": result.get("sha256_12", ""),
                "factory_revision_applied": result.get(
                    "factory_revision_applied", ""),
                "history_key": FACTORY_HISTORY_KEY,
                "provenance_persisted": True,
                "effective": True,
                "journal_recorded": True,
                "legacy_persona_marker": pr.legacy_persona_present(value),
                "provenance": {"kind": "manual_edit", "scope": "global"},
            }
    # журнал недоступен → прежний путь (честный journal_recorded=False)
    if cache is None:
        return {"applied": False, "reason": "config_cache_unavailable",
                "block_id": block_id, "journal_recorded": False}
    _present, previous, document = _read_spec_value(spec, cache)
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
    await _store_spec_value(spec, value, cache, document=document,
                            set_level=set_level)
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
        "journal_recorded": False,
        "legacy_persona_marker": marker,
        "provenance": {"kind": entry["kind"], "scope": entry["scope"]},
    }


async def _write_chat_speech_value(spec, value: str, *, cache=None, actor=None,
                                   reason: str = "", chat_id: int,
                                   expected_updated_at: str | None = None,
                                   pg=None, get_root=None,
                                   set_root=None) -> dict:
    """Per-chat override через API реестра (наследование глобала сохраняется).

    Для блока-поля JSON-документа (Personality Core) чат получает документ,
    СОБРАННЫЙ из глобального (наследование всех полей) с правкой целевого
    поля: локальная адаптация не «обнуляет» вторую редакцию Core и не меняет
    глобальное ядро (SOUL-02.8).
    """
    from services import chat_params
    cache = cache if cache is not None else _default_cache()
    get_root = get_root or chat_params.get_all_chat_params
    set_root = set_root or (lambda chat, patch, **kw:
                            chat_params.set_chat_params(chat, patch, **kw))
    root = await get_root(chat_id, pg=pg) if pg is not None else \
        await get_root(chat_id)
    overrides = dict((root or {}).get("overrides") or {})
    field = _doc_field(spec)
    if field:
        own_doc = _doc_from_raw(overrides.get(spec.pg_key))
        if not own_doc:
            # Наследование: базой для локальной правки служит документ
            # владельца (глобальный слой), а не пустой документ.
            _present, _text, global_doc = _read_spec_value(spec, cache)
            current_doc = global_doc
        else:
            current_doc = own_doc
        previous = pr.doc_field_text(current_doc, field)
    else:
        current = overrides.get(spec.pg_key)
        previous = None if current is None else str(current)
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
    overrides[spec.pg_key] = (
        _doc_with_field(current_doc, field, value)
        if field else value)
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
    # P0 PERSIST-FIX: RMW-консистентность — при явном пуле читаем напрямую из
    # PG (кэш-слой может быть устаревшим до TTL), иначе прежний путь.
    root = await (get_root(chat_id, pg=pg) if pg is not None
                  else get_root(chat_id)) or {}
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
    present = False
    current = ""
    if cache is not None and spec is not None and spec.pg_key:
        present, current, _doc = _read_spec_value(spec, cache)
    text = current if current else factory_default(block_id)
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
        text, source="global" if present else "default",
        custom_clean=pr.payload_custom_clean_scope(
            spec.pg_key, "global" if present else "default"))
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
        present, current, _doc = _read_spec_value(spec, cache)
        if not _value_changed(spec, present, current, factory):
            unchanged.append(block_id)
            continue
        affected.append({"block_id": block_id, "pg_key": spec.pg_key,
                         "document_field": _doc_field(spec),
                         "current_chars": len(current),
                         "factory_chars": len(factory),
                         "diff": _diff_summary(current, factory)})
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
        # EVOL-016: восстановленное значение — ревизия + активация в журнале
        # (иначе рестарт честно зафиксирует activation_drift по этому ключу).
        try:
            from services import prompt_release_policy as prp
            await prp.record_manual_activation(
                spec.block_id, text, scope="global", actor=actor,
                reason="restore_backup", kind="manual_rollback", cache=cache)
        except Exception:      # pragma: no cover — журнал не роняет откат
            logger.warning("[prompt_factory] журнал не зафиксировал "
                           "restore_backup | key=%s", row["key"],
                           exc_info=True)
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


# ═══════════════════════════════════════════════════════════════════════════
# EVOL-016/017 — API журнала версий (контракт §1.6: имена живут здесь,
# реализация — в prompt_release_policy; UI заводит только эти вызовы)
# ═══════════════════════════════════════════════════════════════════════════

async def apply_release(cache, *, release_id: str, store=None) -> dict:
    """Применить заводской релиз промптов (детерминированная проводка старта).

    Снимок legacy + активация cutover — ОДНА транзакция, поэтому контрактное
    имя ``import_legacy_snapshots`` — это тот же cutover-вызов: раздельно
    «снимок без активации» запрещён контрактом §1.4 (частичная смесь).
    """
    from services import prompt_release_policy as prp
    return await prp.apply_release(cache, release_id=release_id, store=store)


async def import_legacy_snapshots(cache, *, store=None) -> dict:
    """Одноразовый перенос текущих активных текстов в журнал (cutover)."""
    from services import prompt_release_policy as prp
    return await prp.apply_release(cache, release_id=prp.CUTOVER_RELEASE_ID,
                                   store=store)


async def activate_revision(block_id: str, revision_id: str, *, scope: str =
                            "global", chat_id: int | None = None,
                            actor=None, cache=None, store=None) -> dict:
    """Откат/вперёд на сохранённую совместимую ревизию (EVOL-017 UI)."""
    from services import prompt_release_policy as prp
    return await prp.activate_revision(
        block_id, revision_id, scope=scope, chat_id=chat_id, actor=actor,
        cache=cache, store=store)


async def list_revisions(block_id: str, *, chat_id: int | None = None,
                         cache=None, store=None,
                         actor=None) -> list[dict]:
    """Хронология ревизий блока (данные для UI истории версий)."""
    from services import prompt_release_policy as prp
    store = store if store is not None else prp.default_journal(cache)
    if store is None:
        return []
    try:
        prp.check_permission(str(actor or ""), "prompt.list_revisions",
                             block_id=block_id, chat_id=chat_id)
        await store.ensure_journal()
        rows = await store.list_revisions(block_id, chat_id)
    except prp.PromptPermissionError:
        raise
    except Exception:          # pragma: no cover — журнал не роняет view
        logger.warning("[prompt_factory] список ревизий недоступен",
                       exc_info=True)
        return []
    return [{
        "revision_id": r.revision_id, "origin": r.origin,
        "sha256_12": r.content_sha12, "factory_revision": r.factory_revision,
        "release_id": r.release_id, "actor": r.actor, "reason": r.reason,
        "retired": r.retired, "created_at": r.created_at,
        "scope": r.scope, "chat_id": r.chat_id,
    } for r in rows]


async def diff_revisions(revision_a: str, revision_b: str, *, cache=None,
                         store=None, actor=None) -> dict:
    """Diff двух ревизий (существующий difflib; EVOL-017 UI)."""
    from services import prompt_release_policy as prp
    return await prp.diff_revisions(revision_a, revision_b, cache=cache,
                                    store=store, actor=actor)


async def get_revision_source(revision_id: str, *, cache=None,
                              store=None, actor=None) -> dict:
    """Полный текст ревизии (просмотр в UI истории версий)."""
    from services import prompt_release_policy as prp
    return await prp.get_revision_source(revision_id, cache=cache,
                                         store=store, actor=actor)


async def list_versions(block_id: str, *, scope: str = "global",
                        chat_id: int | None = None, cache=None,
                        store=None, actor=None) -> dict:
    """Сводка «История версий»: активная ревизия, заводская, хронология."""
    from services import prompt_release_policy as prp
    return await prp.list_versions(block_id, scope=scope, chat_id=chat_id,
                                   cache=cache, store=store, actor=actor)


def meme_prompt_view(block_id: str, *, pg_value=None,
                     chat_value=None) -> dict:
    """EVOL-014: эффективный мем-промпт через реестр, без второго хранилища.

    ``pg_value``/``chat_value`` — уже прочитанный override (каталог/UI
    подставит его тем же путём, что и остальные блоки). Заводской текст
    остаётся константой, на которую указывает ``code_source``.
    """
    eff = pr.effective_prompt(block_id, pg_value=pg_value,
                              chat_value=chat_value)
    return {
        "block_id": eff.block_id,
        "text": eff.text,
        "source": eff.factory_source,
        "differs_from_factory": bool(eff.differs_from_factory),
        "factory_revision": eff.factory_revision,
        "revision": eff.revision,
    }


__all__ = [
    "FACTORY_HISTORY_KEY", "FACTORY_HISTORY_CATEGORY", "CORE_DOC_CATEGORY",
    "HISTORY_MAX_PER_BLOCK", "FactoryConflict", "factory_default",
    "plan_factory_reset", "apply_factory_reset", "write_speech_value",
    "history_for", "reset_chat_override", "plan_speech_profile_reset",
    "apply_speech_profile_reset", "restore_backup", "restore_backup_from_file",
    "freeze_history", "history_frozen",
    # EVOL-016/017 API журнала версий
    "apply_release", "import_legacy_snapshots", "activate_revision",
    "list_revisions", "diff_revisions", "get_revision_source", "list_versions",
    # EVOL-014: мем-промпты читаются общим effective-путём реестра.
    "meme_prompt_view",
]


if __name__ == "__main__":        # pragma: no cover — ручной CLI
    raise SystemExit(_cli())
