"""F5 (memory-rebuild-sanitation-round1021, ADR-1021-5) — безопасный
деструктивный контур CLI `manage.py memory`.

Пересобирается/чистится **только сгенерированное**:
  * `rebuild_dossiers` — сброс старых `graph_facts.status='chat_meme'` и
    пересборка досье через двухслойный пайплайн F1 (инъекция `pipeline`);
  * `sanitize_beliefs` — факты без связей, невалидные убеждения и
    галлюцинации (source_ids/target вне БД/ростера).

⛔ ЖЁСТКИЙ ИНВАРИАНТ (ADR-1021-5 §2.2): сырая история (`smart_messages` +
FTS/vec, `import_checkpoints`) НЕ удаляется и не изменяется ни при каких
обстоятельствах. Любой DELETE проходит через `assert_derived_table` —
таблица обязана лежать в allowlist сгенерированных производных, иначе
`UnsafeMutationError` (abort).

Страховочная сетка (НЕ dry-run, тихий авто-шаг): авто-бэкап (Backup API +
fsync каталога/файла) ДО любого DELETE + JSONL-архив удаляемых строк со
сверкой `candidates == archived`, иначе удаление отменяется.

Дефолт CLI — боевой прогон (`apply`); `--dry-run` — опциональная
диагностика (ничего не пишет). Авто-кронов/HTTP-триггеров нет. R16/R17:
логи и отчёт — counts/классы/коды причин, без текстов/путей/секретов.
"""
import asyncio
import datetime
import json
import logging
from pathlib import Path

from config.settings import settings
from services import hot_config as hot
from services.memory_maintenance import _flush_fsync_and_dir

logger = logging.getLogger(__name__)

# Целевой чат (данные-защита) — НЕ в этом модуле: конкретный runtime-id
# живёт только в данных/CLI-слое (`manage.py::LEGACY_TARGET_CHAT_ID`,
# прецедент `chat_lore.py`), сервисный код id не хардкодит. Guard целевого
# чата применяет `manage._memory_scope` (не входит в --all; требует явного
# `--chat` + `--allow-target-chat`, ADR-1021-5 §2.2).

# Allowlist таблиц, DELETE из которых допустим (только СГЕНЕРИРОВАННЫЕ
# производные). Намеренно НЕ включены: smart_messages (+FTS/vec),
# import_checkpoints, persona_dossier_overrides (ручные правки — отдельный
# путь под явным --include-overrides).
DERIVED_TABLES_ALLOWLIST = frozenset({
    "graph_facts",
    "graph_facts_fts",
    "graph_facts_vec",
    "edges",
    "nodes",
    "graph_fact_compressions",
})

# Таблицы сырой истории/импорта — мутации ЗАПРЕЩЕНЫ (главный инвариант).
RAW_HISTORY_TABLES = frozenset({
    "smart_messages",
    "smart_messages_fts",
    "smart_messages_vec",
    "smart_messages_archive",
    "import_checkpoints",
})

_ARCHIVE_BATCH = 2000
_DEFAULT_BACKUP_PREFIX = "memory_rebuild_"


class UnsafeMutationError(RuntimeError):
    """Попытка DELETE/UPDATE по таблице вне allowlist сгенерированных."""


def assert_derived_table(table: str, *, extra: frozenset = frozenset()) -> None:
    """Guard перед любым DELETE: таблица ∈ allowlist производных ИЛИ `extra`.

    Сырая история запрещена всегда (даже если попадёт в `extra`)."""
    name = str(table or "").strip().lower()
    if name in RAW_HISTORY_TABLES:
        raise UnsafeMutationError(
            f"mutation guard: raw history is immutable | table={name}")
    if name not in DERIVED_TABLES_ALLOWLIST and name not in extra:
        raise UnsafeMutationError(
            f"mutation guard: table not in derived allowlist | table={name}")


async def _guarded_delete(db, table: str, where_sql: str, params=(),
                          *, extra: frozenset = frozenset()) -> int:
    """Единственный путь удаления строк: guard → DELETE → commit."""
    assert_derived_table(table, extra=extra)
    cursor = await db.db.execute(
        f"DELETE FROM {table} WHERE {where_sql}", tuple(params))
    await db.db.commit()
    return int(cursor.rowcount or 0)


async def delete_generated_facts(db, ids, *, batch: int = _ARCHIVE_BATCH) -> int:
    """Удалить сгенерированные факты по id (+FTS+vec), строго через guard.

    Возвращает число удалённых строк `graph_facts`."""
    fact_ids = [int(i) for i in ids if i is not None]
    if not fact_ids:
        return 0
    # Guard ДО первой мутации (allowlist производных).
    for table in ("graph_facts_fts", "graph_facts_vec", "graph_facts"):
        assert_derived_table(table)
    step = max(1, int(batch or _ARCHIVE_BATCH))
    deleted = 0
    for start in range(0, len(fact_ids), step):
        chunk = fact_ids[start:start + step]
        placeholders = ",".join("?" * len(chunk))
        await _guarded_delete(
            db, "graph_facts_fts", f"rowid IN ({placeholders})", chunk)
        try:
            await _guarded_delete(
                db, "graph_facts_vec", f"rowid IN ({placeholders})", chunk)
        except Exception:
            # vec-таблицы может не быть (FTS-only режим) — не фатально.
            logger.debug("[memory_rebuild] vec delete skipped (no table)")
        deleted += await _guarded_delete(
            db, "graph_facts", f"id IN ({placeholders})", chunk)
    return deleted


# ── страховочная сетка: бэкап + JSONL-архив ───────────────────────────────

def _resolve_backup_dir(backup_dir=None) -> Path:
    return Path(backup_dir or hot.get(
        "reactions.memory_backup_dir", settings.MEMORY_BACKUP_DIR))


def create_safety_backup(db_path, backup_dir=None) -> Path:
    """Backup API → файл в MEMORY_BACKUP_DIR + fsync (файл и каталог).

    Синхронный (вызывать через `asyncio.to_thread`): читает согласованный
    снимок живого SQLite, не блокируя бота. `db_path` обязателен и должен
    существовать — бэкап это страховка, а не dry-run."""
    import sqlite3

    src_path = Path(str(db_path))
    if not src_path.exists():
        raise FileNotFoundError(str(src_path.name))
    directory = _resolve_backup_dir(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = directory / f"{_DEFAULT_BACKUP_PREFIX}{stamp}.db"
    source = sqlite3.connect(str(src_path), timeout=30)
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    with open(target, "r+b") as fh:
        _flush_fsync_and_dir(fh, directory)
    return target


async def _safety_backup(db_path, backup_dir, label: str) -> tuple:
    """(ok, path, reason). Без db_path бэкап невозможен → abort (fail-closed)."""
    if not db_path:
        logger.warning("[memory_rebuild] backup unavailable — abort | "
                       "op=%s", label)
        return False, "", "backup_unavailable"
    try:
        path = await asyncio.to_thread(create_safety_backup, db_path,
                                       backup_dir)
    except Exception:
        logger.warning("[memory_rebuild] backup failed — abort (fail-safe) | "
                       "op=%s", label, exc_info=True)
        return False, "", "backup_failed"
    return True, str(path), "ok"


async def _archive_generated_rows(rows, directory: Path,
                                  label: str) -> tuple:
    """JSONL-архив удаляемых сгенерированных строк (fsync).

    Возвращает `(ok, archived, path)`. Любая ошибка записи → `ok=False`
    (вызывающий НЕ удаляет строки)."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("[memory_rebuild] archive dir unavailable | op=%s",
                       label)
        return False, 0, ""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = directory / f"memory_generated_{label}_{stamp}.jsonl"
    archived = 0
    try:
        with open(target, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(row), ensure_ascii=False,
                                    default=str))
                fh.write("\n")
                archived += 1
            await asyncio.to_thread(_flush_fsync_and_dir, fh, directory)
    except Exception:
        logger.warning("[memory_rebuild] archive failed — delete skipped "
                       "(fail-safe) | op=%s", label, exc_info=True)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return False, 0, str(target)
    return True, archived, str(target)


async def _archive_and_delete(db, rows, *, backup_dir, label: str,
                              deleter=None, batch: int = _ARCHIVE_BATCH) -> tuple:
    """Архив → сверка `candidates == archived` → guard-DELETE.

    Возвращает `(ok, archived, deleted, reason)`."""
    deleter = deleter or delete_generated_facts
    candidates = [r for r in rows if r.get("id") is not None]
    if not candidates:
        return True, 0, 0, "no_candidates"
    directory = _resolve_backup_dir(backup_dir)
    ok, archived, _path = await _archive_generated_rows(candidates, directory,
                                                        label)
    if not ok or archived != len(candidates):
        logger.warning(
            "[memory_rebuild] archive mismatch — delete aborted | op=%s | "
            "candidates=%d archived=%d", label, len(candidates), archived)
        return False, archived, 0, "archive_mismatch"
    deleted = await deleter(db, [r["id"] for r in candidates], batch=batch)
    if deleted != len(candidates):
        return False, archived, deleted, "delete_mismatch"
    return True, archived, deleted, "ok"


# ── выборки (bounded) ─────────────────────────────────────────────────────

async def _list_generated_memes(db, chat_id: int, limit: int) -> list:
    """Старые мемы однопроходного пайплайна (`status='chat_meme'`)."""
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, weight, created_at, status, kind "
        "FROM graph_facts WHERE chat_id = ? AND status = 'chat_meme' "
        "ORDER BY id ASC LIMIT ?", (int(chat_id), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


async def _list_generated_portraits(db, chat_id: int, limit: int) -> list:
    """Сгенерированные портреты Слоя Б (`status='dossier_portrait'`).
    F1 spec §3.2.1 / ADR-1021-5 §7: производные строки graph_facts."""
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, weight, created_at, status, kind "
        "FROM graph_facts WHERE chat_id = ? AND status = 'dossier_portrait' "
        "ORDER BY id ASC LIMIT ?", (int(chat_id), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


async def _list_orphan_facts(db, chat_id: int, limit: int) -> list:
    """Факты/мемы без инцидентных `edges.fact_id` (убеждения исключены)."""
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, weight, created_at, status, kind "
        "FROM graph_facts WHERE chat_id = ? AND kind NOT IN ('belief') "
        "AND status IN ('confirmed', 'chat_meme', 'unconfirmed') "
        "AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.fact_id = "
        "graph_facts.id) ORDER BY id ASC LIMIT ?",
        (int(chat_id), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


async def _list_beliefs(db, chat_id: int, limit: int) -> list:
    """Убеждения/парадигмы чата (kind='belief') — кандидаты валидатора."""
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, weight, created_at, status, kind, "
        "belief_meta, source_ids FROM graph_facts WHERE chat_id = ? "
        "AND kind = 'belief' ORDER BY id ASC LIMIT ?",
        (int(chat_id), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


async def _chat_roster(db, chat_id: int, limit: int = 500) -> dict:
    """Участники чата из НЕЗАВИСИМЫХ источников (S10.21-2).

    `nodes` (`entity_type='user'`) заполняется только триплетами и заведомо
    неполон, поэтому ростер дополняется производными портретами Слоя Б
    (`status='dossier_portrait'`) и ручными `persona_dossier_overrides`
    (user_id → имя через per-chat AliasResolver). Досье-фильтр галлюцинаций
    строим только по объединению; сырую историю НЕ читаем/не мутируем.

    Возврат `{"names": set, "independent": int}`, где `independent` — сколько
    имён дал НЕ-`nodes` источник (sanity-guard: ростер только из триплетов
    неполон и не годится для удаления мемов)."""
    names: set = set()
    independent = 0
    try:
        cursor = await db.db.execute(
            "SELECT DISTINCT entity_name FROM nodes WHERE chat_id = ? "
            "AND entity_type = 'user' AND entity_name IS NOT NULL "
            "AND entity_name != '' LIMIT ?", (int(chat_id), int(limit)))
        names.update(
            str(r["entity_name"]).strip() for r in await cursor.fetchall())
    except Exception:
        pass
    try:
        cursor = await db.db.execute(
            "SELECT DISTINCT target_user FROM graph_facts WHERE chat_id = ? "
            "AND status = 'dossier_portrait' AND target_user IS NOT NULL "
            "AND target_user != '' LIMIT ?", (int(chat_id), int(limit)))
        portraits = {
            str(r["target_user"]).strip() for r in await cursor.fetchall()}
    except Exception:
        portraits = set()
    independent += len(portraits - names)
    names.update(portraits)
    try:
        override_names = await _override_roster_names(db, chat_id, limit)
    except Exception:
        override_names = set()
    independent += len(override_names - names)
    names.update(override_names)
    return {"names": names, "independent": independent}


async def _override_roster_names(db, chat_id: int, limit: int = 500) -> set:
    """Имена участников с ручными `persona_dossier_overrides` (S10.21-2).

    Override-ключ — `user_id` (R16), имя получаем через тот же per-chat
    AliasResolver, что и досье; fallback-«имя = id» отбрасываем. Fail-open:
    ошибка/нет строк → пустое множество (сырая история не читается)."""
    cursor = await db.db.execute(
        "SELECT DISTINCT user_id FROM persona_dossier_overrides "
        "WHERE chat_id = ? LIMIT ?", (int(chat_id), int(limit)))
    user_ids = [int(r["user_id"]) for r in await cursor.fetchall()]
    if not user_ids:
        return set()
    from services import summary_aliases

    resolver = await summary_aliases.build_alias_resolver(chat_id)
    out: set = set()
    for uid in user_ids:
        try:
            resolved = str(resolver.resolve(uid, None, None) or "").strip()
        except Exception:
            continue
        if resolved and resolved != str(uid):
            out.add(resolved)
    return out


async def _existing_fact_ids(db, ids) -> set:
    """Существующие id graph_facts для сверки `source_ids` (чанками)."""
    wanted = sorted({int(i) for i in ids if i is not None})
    found: set = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        cursor = await db.db.execute(
            f"SELECT id FROM graph_facts WHERE id IN ({placeholders})", chunk)
        found.update(int(r["id"]) for r in await cursor.fetchall())
    return found


def _parse_source_ids(raw) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def validate_belief_row(row, existing_ids) -> str | None:
    """Count-agnostic валидатор убеждения (None = валидно, иначе reason-код).

    «36» не хардкодим (ADR-1021-5 Д15): проверяем структуру и ссылки."""
    if not str(row.get("fact") or "").strip():
        return "empty_text"
    raw_meta = row.get("belief_meta")
    if raw_meta not in (None, ""):
        try:
            meta = json.loads(raw_meta)
        except (TypeError, ValueError):
            return "bad_meta"
        if not isinstance(meta, dict):
            return "bad_meta"
    ids = _parse_source_ids(row.get("source_ids"))
    if not ids:
        return "no_sources"
    missing = [i for i in ids if i not in existing_ids]
    if missing:
        return "missing_sources"
    return None


# ── операции ──────────────────────────────────────────────────────────────

async def rebuild_dossiers(db, *, chat_ids, dry_run: bool = False,
                           include_overrides: bool = False, limit: int = 500,
                           pipeline=None, db_path=None, backup_dir=None,
                           window_hours: int = 168, batch: int = 2000) -> dict:
    """F5/§4.1: сброс сгенерированных мемов → пересборка досье (pipeline).

    `pipeline` — async callable `(chat_id) -> int` (число записанных мемов);
    в CLI это двухслойный пайплайн F1 (`LoreWorker.rebuild_dossier_for_chat`).
    Без pipeline боевой прогон отменяется (`no_pipeline`) — не сбрасываем
    мемы, если нечем пересобирать. Авто-бэкап — один раз до первого DELETE."""
    out = {"dry_run": bool(dry_run), "chats": 0, "scanned": 0, "reset": 0,
           "reset_portraits": 0, "rebuilt": 0, "skipped": 0, "reasons": {},
           "backup": ""}

    def _reason(code: str) -> None:
        out["reasons"][code] = out["reasons"].get(code, 0) + 1

    if not dry_run and pipeline is None:
        _reason("no_pipeline")
        return out
    if not dry_run:
        ok, backup_path, reason = await _safety_backup(db_path, backup_dir,
                                                       "rebuild")
        if not ok:
            _reason(reason)
            return out
        out["backup"] = backup_path
    for chat_id in chat_ids:
        out["chats"] += 1
        try:
            memes = await _list_generated_memes(db, chat_id, limit)
            portraits = await _list_generated_portraits(db, chat_id, limit)
        except Exception:
            logger.warning("[memory_rebuild] meme/portrait list failed | "
                           "chat=%s", chat_id, exc_info=True)
            _reason("read_error")
            out["skipped"] += 1
            continue
        out["scanned"] += len(memes) + len(portraits)
        if dry_run:
            out["reset"] += len(memes)
            out["reset_portraits"] += len(portraits)
            if memes or portraits:
                _reason("would_reset")
            continue
        if memes:
            ok, _archived, deleted, reason = await _archive_and_delete(
                db, memes, backup_dir=backup_dir, label="rebuild",
                batch=batch)
            if not ok:
                _reason(reason)
                out["skipped"] += 1
                continue
            out["reset"] += deleted
        if portraits:
            ok, _archived, deleted, reason = await _archive_and_delete(
                db, portraits, backup_dir=backup_dir,
                label="rebuild_portraits", batch=batch)
            if not ok:
                _reason(reason)
                out["skipped"] += 1
                continue
            out["reset_portraits"] += deleted
        if include_overrides:
            try:
                n, reason = await _reset_overrides(db, chat_id, backup_dir)
                if reason is not None:
                    _reason(reason)
                elif n:
                    out["reasons"]["overrides_reset"] = \
                        out["reasons"].get("overrides_reset", 0) + n
            except Exception:
                logger.warning("[memory_rebuild] overrides reset failed | "
                               "chat=%s", chat_id, exc_info=True)
                _reason("overrides_error")
        try:
            written = int(await pipeline(chat_id) or 0)
        except Exception:
            logger.warning("[memory_rebuild] rebuild failed | chat=%s",
                           chat_id, exc_info=True)
            _reason("rebuild_error")
            out["skipped"] += 1
            continue
        out["rebuilt"] += written
    return out


async def _list_overrides(db, chat_id: int, limit: int = 500) -> list:
    cursor = await db.db.execute(
        "SELECT chat_id, user_id, traits, updated_at "
        "FROM persona_dossier_overrides WHERE chat_id = ? "
        "ORDER BY user_id ASC LIMIT ?", (int(chat_id), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


async def _reset_overrides(db, chat_id: int, backup_dir) -> tuple:
    """F5/§3 п.4: сброс ручных overrides ТОЛЬКО под `--include-overrides`
    (архив → сверка → guard-DELETE по `chat_id`; ключ составной)."""
    rows = await _list_overrides(db, chat_id)
    if not rows:
        return 0, None
    ok, archived, _path = await _archive_generated_rows(
        rows, _resolve_backup_dir(backup_dir), "overrides")
    if not ok or archived != len(rows):
        return 0, "archive_mismatch"
    extra = frozenset({"persona_dossier_overrides"})
    deleted = await _guarded_delete(
        db, "persona_dossier_overrides", "chat_id = ?", (int(chat_id),),
        extra=extra)
    if deleted != len(rows):
        return deleted, "delete_mismatch"
    return deleted, None


async def sanitize_beliefs(db, *, chat_ids, dry_run: bool = False,
                           limit: int = 500, db_path=None, backup_dir=None,
                           batch: int = 2000) -> dict:
    """F5/§4.2: чистка ТОЛЬКО сгенерированных производных.

    Классы: `orphan_fact` (нет рёбер, НЕ опора живого убеждения/парадигмы),
    `invalid_belief` (структура/ссылки source_ids), `hallucination` (target
    мема вне ростера из независимых источников). Сырую историю не читаем и не
    мутуируем. Авто-бэкап — один раз до первого DELETE.

    S10.21-2: ростер — union `nodes` + портреты Слоя Б + override-имена;
    если он состоит только из `nodes` (неполон), класс «галлюцинация» не
    применяется (reason `roster_incomplete`), а `roster_size` выводится в
    отчёт. S10.21-3: факты-опоры убеждений/парадигм (`source_ids`) не
    удаляются как orphan (`belief_source`)."""
    out = {"dry_run": bool(dry_run), "chats": 0, "scanned": 0,
           "candidates": 0, "archived": 0, "deleted": 0, "skipped": 0,
           "classes": {}, "reasons": {}, "backup": "", "roster_size": {}}

    def _reason(code: str) -> None:
        out["reasons"][code] = out["reasons"].get(code, 0) + 1

    def _cls(name: str, n: int) -> None:
        out["classes"][name] = out["classes"].get(name, 0) + n

    if not dry_run:
        ok, backup_path, reason = await _safety_backup(db_path, backup_dir,
                                                       "sanitize")
        if not ok:
            _reason(reason)
            return out
        out["backup"] = backup_path
    for chat_id in chat_ids:
        out["chats"] += 1
        try:
            orphans = await _list_orphan_facts(db, chat_id, limit)
            beliefs = await _list_beliefs(db, chat_id, limit)
            roster_info = await _chat_roster(db, chat_id)
        except Exception:
            logger.warning("[memory_rebuild] sanitize read failed | chat=%s",
                           chat_id, exc_info=True)
            _reason("read_error")
            out["skipped"] += 1
            continue
        roster = roster_info["names"]
        out["roster_size"][int(chat_id)] = len(roster)
        out["scanned"] += len(orphans) + len(beliefs)
        # S10.21-3: опоры живых убеждений/парадигм (`source_ids` + `evidence`
        # из `belief_meta`) из orphan-кандидатов исключаем — иначе каскадом
        # снесли бы валидное убеждение на следующем прогоне.
        belief_sources: set = set()
        for row in beliefs:
            belief_sources.update(_parse_source_ids(row.get("source_ids")))
            raw_meta = row.get("belief_meta")
            if not raw_meta:
                continue
            try:
                meta = (json.loads(raw_meta) if isinstance(raw_meta, str)
                        else raw_meta)
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            for value in meta.get("evidence") or []:
                try:
                    belief_sources.add(int(value))
                except (TypeError, ValueError):
                    continue
        tagged: dict = {}
        kept_orphans = 0
        for row in orphans:
            if int(row["id"]) in belief_sources:
                _reason("belief_source")
                continue
            try:
                protected = await db.is_fact_protected(
                    chat_id, str(row.get("fact") or ""))
            except Exception:
                protected = True          # fail-safe: защищаем при ошибке
            if protected:
                _reason("protected")
                continue
            row = dict(row)
            row["_class"] = "orphan_fact"
            tagged[int(row["id"])] = row
            kept_orphans += 1
        _cls("orphan_fact", kept_orphans)
        all_ids = []
        for row in beliefs:
            all_ids.extend(_parse_source_ids(row.get("source_ids")))
        try:
            existing = await _existing_fact_ids(db, all_ids)
        except Exception:
            existing = set()
        invalid = 0
        for row in beliefs:
            reason = validate_belief_row(row, existing)
            if reason is None:
                continue
            invalid += 1
            _reason(reason)
            row = dict(row)
            row["_class"] = "invalid_belief"
            row["_reason"] = reason
            tagged[int(row["id"])] = row
        _cls("invalid_belief", invalid)
        if roster:
            memes = await _list_generated_memes(db, chat_id, limit)
            meme_targets = {
                str(row.get("target_user") or "").strip() for row in memes}
            meme_targets.discard("")
            unknown = meme_targets - roster
            if unknown and not roster_info["independent"]:
                # S10.21-2 sanity-guard: ростер собран ТОЛЬКО из `nodes`
                # (триплеты) и заведомо неполон — не удаляем «неизвестных».
                _reason("roster_incomplete")
            else:
                hall = 0
                for row in memes:
                    target = str(row.get("target_user") or "").strip()
                    if target and target not in roster:
                        hall += 1
                        _reason("target_not_in_roster")
                        row = dict(row)
                        row["_class"] = "hallucination"
                        tagged[int(row["id"])] = row
                _cls("hallucination", hall)
        else:
            _reason("no_roster")
        candidates = list(tagged.values())
        out["candidates"] += len(candidates)
        if dry_run or not candidates:
            if dry_run and candidates:
                _reason("would_delete")
            continue
        ok, archived, deleted, reason = await _archive_and_delete(
            db, candidates, backup_dir=backup_dir, label="sanitize",
            batch=batch)
        out["archived"] += archived
        if not ok:
            _reason(reason)
            out["skipped"] += 1
            continue
        out["deleted"] += deleted
    return out
