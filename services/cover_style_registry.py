"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D1/D6/D7/D10;
spec §3.5/§3.6/§3.10) — Style Registry (PG).

Data-driven реестр Style Profile: **без** `if style == "medved_press"` (§6/§98).
Реестр **глобальный** (профили общие), а **выбор стиля — per-chat**
(`prompts.summary_cover_style_id`, DC-5). Идемпотентный seed seeded-стиля
`Графический роман Медведь Press` (`origin=seeded_example` — только UI-badge).

Хранилище — PostgreSQL (`cover_style_*`, `pg_db.DDL_STATEMENTS`), Δ DDL
SQLite = 0. Все методы fail-open: PG недоступен → base cover + публикация
продолжают работать (§1).

R17: в таблицах нет секретов/полных URL; API key — только в Connections
(`keys.image_style_api_key`).
"""
from __future__ import annotations

import json
import logging
import uuid

from services.cover_style_assets import (
    asset_id_for,
    import_seed_file,
)

logger = logging.getLogger(__name__)

ORIGIN_SEEDED = "seeded_example"
ORIGIN_CUSTOM = "custom"

MODE_GENERATE_ONLY = "generate_only"
MODE_GENERATE_THEN_EDIT = "generate_then_edit"
MODE_EDIT_ONLY = "edit_only"
PIPELINE_MODES = (MODE_GENERATE_ONLY, MODE_GENERATE_THEN_EDIT, MODE_EDIT_ONLY)

MODEL_MODE_DEFAULT = "default"
MODEL_MODE_CUSTOM = "custom"

PROVENANCE_STAGED = "staged"
PROVENANCE_STYLED = "styled"
PROVENANCE_BASE = "base"
PROVENANCE_NONE = "none"

MODE_PRODUCTION = "production"
MODE_PREVIEW = "preview"

# Seeded Style Profile `Графический роман Медведь Press` (§6/§24/§59).
SEEDED_PROFILE_ID = "medved_press"
SEEDED_PROFILE_NAME = "Графический роман Медведь Press"
SEEDED_COUNTER_FORMAT = "ВЫПУСК {counter}"
# DC-2/D8: начальное значение НЕ выдумывается (owner-input pending) —
# обратимый configurable дефолт `0` (следующий выпуск — 1).
SEEDED_COUNTER_START = 0

# Seeded edit prompt (ASAP 4.3 §8): компактная версия — ужимаем семантически,
# не строковыми ножницами; сохраняем ВСЕ invariants: PERMsoc ровно один,
# номер выпуска ровно один/заменён, логотип по reference без дублей,
# references по ролям, цельная comic/graphic-novel обложка, русский текст.
SEEDED_INSTRUCTION = (
    "Редактируй готовую обложку как выпуск «Медведь Press», не рисуй заново. "
    "Сохрани сцену, композицию и удачные плашки. PERMsoc должен быть ровно "
    "один: сохрани существующий или добавь. Номер выпуска — один, замени "
    "старый на заданный. Логотип замени на reference «Медведь Press», без "
    "дублей. References используй по их ролям. Стиль: цельная "
    "comic/graphic-novel обложка; детали и плашки — по исходнику и Summary. "
    "Весь добавляемый текст — на русском."
)

# ASAP 4.3 (T-4848): прежняя 979-символьная seeded-инструкция — только для
# идемпотентной миграции существующей prod-строки (если владелец её не
# редактировал). После миграции константа не используется в seed.
_LEGACY_SEEDED_INSTRUCTION = (
    "Приведи уже существующую обложку к правилам серии «Медведь Press», "
    "редактируя её (edit), а не рисуя заново, и не создавай дубликатов.\n"
    "Характер серии: современный русский графический роман / комикс, "
    "печатная комикс-композиция с чистым контуром и естественным русским "
    "текстом.\n"
    "Обязательно:\n"
    "• если на обложке уже есть PERMsoc — сохрани его как главный title и не "
    "добавляй второй; если нет — добавь один аккуратный PERMsoc;\n"
    "• если уже есть номер выпуска (badge) — замени/исправь его на "
    "назначенный номер выпуска; не добавляй второй badge;\n"
    "• приведи издательский знак/логотип к reference «Медведь Press» "
    "(замени чужой логотип, не дублируй уже правильный);\n"
    "• используй приложенные references согласно их описанию;\n"
    "• сохрани удачные сцену, персонажей, контекстные callouts и композицию "
    "насколько возможно; добавь 2–3 комикс-плашки/callouts, если их нет;\n"
    "• весь добавляемый текст — на русском.\n"
    "Композиция и контекстные плашки остаются творческими и зависят от "
    "исходной обложки и Summary."
)

# Файлы сида (ASAP 4.3 §5): permanent DB-asset профиля — ТОЛЬКО reference;
# `style_example_01/02` — UI fallback placeholders (не сидятся в БД/preview).
SEED_FILES = {
    "reference": "medved_press.png",
}

# UI fallback placeholders (§5): имена-стемы в `extra_images`; фактическое
# расширение — из listing (не hardcode). Не DB-assets, не preview профиля.
PLACEHOLDER_STEMS = ("style_example_01", "style_example_02")


def placeholder_files(seed_dir=None) -> dict[str, str]:
    """Фактические файлы-placeholder'ов из `extra_images` (stem → имя).

    Расширение определяется по реальному listing (`.png`/`.jpg`/`.jpeg`/
    `.webp`), приоритет — ALLOWED_MIME; отсутствует файл → ключа нет.
    """
    from services.cover_style_assets import ALLOWED_MIME
    base = seed_dir or _seed_dir()
    out: dict[str, str] = {}
    for stem in PLACEHOLDER_STEMS:
        candidates: list[str] = []
        try:
            for path in sorted(base.iterdir()):
                if path.is_file() and path.stem == stem \
                        and path.suffix.lower() in set(
                            ALLOWED_MIME.values()) | {".jpeg"}:
                    candidates.append(path.name)
        except OSError:
            continue
        if candidates:
            out[stem] = candidates[0]
    return out


# ── внутренние хелперы ──────────────────────────────────────────────────────

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _seed_dir() -> "object":
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "extra_images"


def _pool_of(pg):
    return getattr(pg, "pool", None) if pg is not None else None


# ── assets ──────────────────────────────────────────────────────────────────

async def upsert_asset(pg, meta: dict) -> bool:
    """Найти/создать asset-метаданные в PG (идемпотентно, дедуп sha+scope).

    Если активный asset с тем же `sha256`/`scope` уже есть — возвращает его
    `asset_id` в `meta` (no-op). Fail-open → False.
    """
    pool = _pool_of(pg)
    if pool is None or not isinstance(meta, dict):
        return False
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT asset_id FROM cover_style_assets "
                "WHERE sha256 = $1 AND scope = $2 AND deleted_at IS NULL",
                meta["sha256"], meta.get("scope", "global"))
            if row is not None:
                meta["asset_id"] = row["asset_id"]
                return True
            await conn.execute(
                "INSERT INTO cover_style_assets (asset_id, scope, filename, "
                "mime, size_bytes, sha256, origin, disk_path) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (asset_id) DO NOTHING",
                meta["asset_id"], meta.get("scope", "global"), meta["filename"],
                meta["mime"], meta["size_bytes"], meta["sha256"],
                meta.get("origin", "upload"), meta["disk_path"])
            return True
    except Exception:
        logger.warning("[cover_style_registry] asset upsert failed | id=%s",
                       meta.get("asset_id"), exc_info=True)
        return False


async def get_asset(pg, asset_id: str) -> dict | None:
    pool = _pool_of(pg)
    if pool is None or not asset_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cover_style_assets WHERE asset_id = $1 "
                "AND deleted_at IS NULL", asset_id)
        return dict(row) if row is not None else None
    except Exception:
        logger.warning("[cover_style_registry] asset get failed", exc_info=True)
        return None


async def soft_delete_asset(pg, asset_id: str) -> bool:
    pool = _pool_of(pg)
    if pool is None or not asset_id:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE cover_style_assets SET deleted_at = now() "
                "WHERE asset_id = $1", asset_id)
        return True
    except Exception:
        logger.warning("[cover_style_registry] asset delete failed",
                       exc_info=True)
        return False


# ── profiles ────────────────────────────────────────────────────────────────

async def list_profiles(pg, *, include_disabled: bool = False) -> list[dict]:
    """Список профилей (без удалённых). Ссылки подгружаются отдельно."""
    pool = _pool_of(pg)
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            if include_disabled:
                rows = await conn.fetch(
                    "SELECT * FROM cover_style_profiles WHERE is_deleted = false "
                    "ORDER BY origin DESC, name ASC")
            else:
                rows = await conn.fetch(
                    "SELECT * FROM cover_style_profiles WHERE is_deleted = false "
                    "AND enabled = true ORDER BY origin DESC, name ASC")
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("[cover_style_registry] list failed", exc_info=True)
        return []


async def get_profile(pg, profile_id: str) -> dict | None:
    pool = _pool_of(pg)
    if pool is None or not profile_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cover_style_profiles WHERE profile_id = $1 "
                "AND is_deleted = false", profile_id)
        return dict(row) if row is not None else None
    except Exception:
        logger.warning("[cover_style_registry] get failed", exc_info=True)
        return None


async def get_profile_with_refs(pg, profile_id: str) -> dict | None:
    profile = await get_profile(pg, profile_id)
    if profile is None:
        return None
    profile["references"] = await list_references(pg, profile_id)
    return profile


async def upsert_profile(pg, profile: dict) -> bool:
    """Создать/обновить профиль. Инкремент `revision` при обновлении."""
    pool = _pool_of(pg)
    if pool is None:
        return False
    pid = profile.get("profile_id") or _new_id("csp")
    try:
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT revision FROM cover_style_profiles "
                "WHERE profile_id = $1", pid)
            if existing is None:
                await conn.execute(
                    "INSERT INTO cover_style_profiles (profile_id, name, "
                    "origin, pipeline_mode, instruction, counter_enabled, "
                    "counter_value, counter_format, model_mode, connection_id, "
                    "model_id, preview_before_asset_id, preview_after_asset_id, "
                    "preview_revision, revision, enabled, validation_mode) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,"
                    "1,$15,$16)",
                    pid, profile["name"],
                    profile.get("origin", ORIGIN_CUSTOM),
                    profile.get("pipeline_mode", MODE_GENERATE_THEN_EDIT),
                    profile.get("instruction", ""),
                    bool(profile.get("counter_enabled", False)),
                    int(profile.get("counter_value", 0)),
                    profile.get("counter_format", SEEDED_COUNTER_FORMAT),
                    profile.get("model_mode", MODEL_MODE_DEFAULT),
                    profile.get("connection_id"),
                    profile.get("model_id"),
                    profile.get("preview_before_asset_id"),
                    profile.get("preview_after_asset_id"),
                    profile.get("preview_revision"),
                    bool(profile.get("enabled", True)),
                    profile.get("validation_mode", "off"))
            else:
                await conn.execute(
                    "UPDATE cover_style_profiles SET name=$2, pipeline_mode=$3, "
                    "instruction=$4, counter_enabled=$5, counter_value=$6, "
                    "counter_format=$7, model_mode=$8, connection_id=$9, "
                    "model_id=$10, preview_before_asset_id=$11, "
                    "preview_after_asset_id=$12, preview_revision=$13, "
                    "enabled=$14, validation_mode=$15, "
                    "revision = revision + 1, updated_at = now() "
                    "WHERE profile_id=$1",
                    pid, profile["name"],
                    profile.get("pipeline_mode", MODE_GENERATE_THEN_EDIT),
                    profile.get("instruction", ""),
                    bool(profile.get("counter_enabled", False)),
                    int(profile.get("counter_value", 0)),
                    profile.get("counter_format", SEEDED_COUNTER_FORMAT),
                    profile.get("model_mode", MODEL_MODE_DEFAULT),
                    profile.get("connection_id"),
                    profile.get("model_id"),
                    profile.get("preview_before_asset_id"),
                    profile.get("preview_after_asset_id"),
                    profile.get("preview_revision"),
                    bool(profile.get("enabled", True)),
                    profile.get("validation_mode", "off"))
        profile["profile_id"] = pid
        return True
    except Exception:
        logger.warning("[cover_style_registry] upsert failed", exc_info=True)
        return False


async def soft_delete_profile(pg, profile_id: str) -> bool:
    pool = _pool_of(pg)
    if pool is None or not profile_id:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE cover_style_profiles SET is_deleted = true, "
                "updated_at = now() WHERE profile_id = $1", profile_id)
        return True
    except Exception:
        logger.warning("[cover_style_registry] delete failed", exc_info=True)
        return False


async def set_preview(pg, profile_id: str, *, after_asset_id: str | None,
                      revision: int | None,
                      before_asset_id: str | None = None,
                      job_id: str | None = None) -> bool:
    """Сохранить preview стиля БЕЗ инкремента `revision` (§10/SC-24).

    ASAP 4.3 (§4): success pair пишется ОДНОЙ атомарной операцией
    `before + after + revision + job_id` (provenance текущего успешного job);
    failure этот метод не вызывает вовсе — прежняя пара не переписывается
    частично. `preview_revision` == текущая `revision` означает актуальный
    пример.
    """
    pool = _pool_of(pg)
    if pool is None or not profile_id:
        return False
    try:
        async with pool.acquire() as conn:
            if before_asset_id:
                # §4: одна UPDATE-операция — оба ассета + revision + job_id.
                await conn.execute(
                    "UPDATE cover_style_profiles SET "
                    "preview_after_asset_id = $2, "
                    "preview_before_asset_id = $3, "
                    "preview_revision = $4, "
                    "preview_job_id = $5, updated_at = now() "
                    "WHERE profile_id = $1",
                    profile_id, after_asset_id, before_asset_id, revision,
                    job_id)
            else:
                await conn.execute(
                    "UPDATE cover_style_profiles SET "
                    "preview_after_asset_id = $2, preview_revision = $3, "
                    "preview_job_id = $4, "
                    "updated_at = now() WHERE profile_id = $1",
                    profile_id, after_asset_id, revision, job_id)
        return True
    except Exception:
        logger.warning("[cover_style_registry] preview save failed",
                       exc_info=True)
        return False


def preview_is_stale(profile: dict) -> bool:
    """§10/SC-24: preview создан для предыдущей revision стиля."""
    if not profile:
        return False
    stored = profile.get("preview_revision")
    if stored is None or profile.get("preview_after_asset_id") is None:
        return False
    try:
        return int(stored) != int(profile.get("revision") or 0)
    except (TypeError, ValueError):
        return False


def preview_pair_current(profile: dict) -> bool:
    """ASAP 4.3 (§4): пара действительна, только если это один успешно
    завершённый job текущей revision: оба ассета + revision == current,
    не stale. Placeholder-состояние (`preview_revision IS NULL`) — НЕ пара."""
    if not profile:
        return False
    if profile.get("preview_revision") is None:
        return False
    if not (profile.get("preview_before_asset_id")
            and profile.get("preview_after_asset_id")):
        return False
    return not preview_is_stale(profile)


async def duplicate_profile(pg, profile_id: str, *,
                            new_name: str | None = None) -> str | None:
    """Дублировать профиль и его references (§63). Возвращает новый id."""
    src = await get_profile_with_refs(pg, profile_id)
    if src is None:
        return None
    new_id = _new_id("csp")
    src["profile_id"] = new_id
    src["name"] = new_name or f"{src['name']} (копия)"
    src["origin"] = ORIGIN_CUSTOM
    if not await upsert_profile(pg, src):
        return None
    for ref in src.get("references", []):
        await add_reference(pg, new_id, ref)
    return new_id


# ── references ──────────────────────────────────────────────────────────────

async def list_references(pg, profile_id: str) -> list[dict]:
    pool = _pool_of(pg)
    if pool is None or not profile_id:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM cover_style_references WHERE profile_id = $1 "
                "ORDER BY ordering ASC, created_at ASC", profile_id)
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("[cover_style_registry] refs list failed", exc_info=True)
        return []


async def add_reference(pg, profile_id: str, ref: dict) -> str | None:
    pool = _pool_of(pg)
    if pool is None or not profile_id:
        return None
    rid = ref.get("ref_id") or _new_id("csr")
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO cover_style_references (ref_id, profile_id, "
                "asset_id, label, description, ordering) VALUES "
                "($1,$2,$3,$4,$5,$6) ON CONFLICT (ref_id) DO NOTHING",
                rid, profile_id, ref["asset_id"], ref.get("label", ""),
                ref.get("description", ""), int(ref.get("ordering", 0)))
        return rid
    except Exception:
        logger.warning("[cover_style_registry] ref add failed", exc_info=True)
        return None


async def remove_reference(pg, profile_id: str, ref_id: str) -> bool:
    pool = _pool_of(pg)
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM cover_style_references WHERE profile_id = $1 "
                "AND ref_id = $2", profile_id, ref_id)
        return True
    except Exception:
        logger.warning("[cover_style_registry] ref remove failed", exc_info=True)
        return False


async def update_reference(pg, profile_id: str, ref_id: str, *,
                           asset_id: str | None = None,
                           label: str | None = None,
                           description: str | None = None) -> bool:
    """Replace reference (§12): заменить asset/label/description без удаления.

    ASAP-4 волна B (хвост B.5, T-4416): asyncpg `execute` возвращает статус
    вида ``UPDATE N`` — парсим N честно; `UPDATE 0` (ref не найден) → False
    → API отдаёт 404, а не ложный 200 (прежде `getattr(cursor, "rowcount", 1)`
    у строки-статуса всегда давал 1)."""
    pool = _pool_of(pg)
    if pool is None or not profile_id or not ref_id:
        return False
    try:
        async with pool.acquire() as conn:
            status = await conn.execute(
                "UPDATE cover_style_references SET "
                "asset_id = COALESCE($3, asset_id), "
                "label = COALESCE($4, label), "
                "description = COALESCE($5, description) "
                "WHERE profile_id = $1 AND ref_id = $2",
                profile_id, ref_id, asset_id, label, description)
            return _update_status_count(status) > 0
    except Exception:
        logger.warning("[cover_style_registry] ref update failed", exc_info=True)
        return False


def _update_status_count(status) -> int:
    """Число затронутых строк из asyncpg-статуса (`UPDATE 3` → 3).

    Compatibility: настоящий asyncpg возвращает строку-статус; тестовые
    double могут вернуть объект с `.rowcount` или int."""
    if isinstance(status, int):
        return status
    rowcount = getattr(status, "rowcount", None)
    if isinstance(rowcount, int):
        return rowcount
    text = str(status or "").strip()
    try:
        return int(text.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


async def references_using_asset(pg, asset_id: str) -> list[dict]:
    """Профили, использующие asset как reference (§64 dangling-guard)."""
    pool = _pool_of(pg)
    if pool is None or not asset_id:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT r.profile_id, p.name FROM cover_style_references r "
                "JOIN cover_style_profiles p ON p.profile_id = r.profile_id "
                "WHERE r.asset_id = $1 AND p.is_deleted = false", asset_id)
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("[cover_style_registry] asset usage failed",
                       exc_info=True)
        return []


# ── counter / issue assignment (§25–§28) ────────────────────────────────────

async def resolve_issue_number(pg, profile_id: str, summary_run_id: str
                               ) -> int | None:
    """Pin номера за run (§27): retry reuse (`44 → retry → 44`).

    Assignment allocation — атомарно одним CTE: retry возвращает прежний номер;
    параллельные Summary на одном профиле получают разные номера (§28,
    UNIQUE(profile_id, issue_number) + `FOR UPDATE`-free атомарный increment).
    """
    pool = _pool_of(pg)
    if pool is None or not profile_id or not summary_run_id:
        return None
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT issue_number FROM cover_style_issue_assignments "
                    "WHERE profile_id = $1 AND summary_run_id = $2",
                    profile_id, summary_run_id)
                if existing is not None:
                    return int(existing["issue_number"])
                # Increment counter atomically, then try to claim.
                row = await conn.fetchrow(
                    "UPDATE cover_style_profiles SET counter_value = "
                    "counter_value + 1, updated_at = now() WHERE profile_id = $1 "
                    "RETURNING counter_value", profile_id)
                if row is None:
                    return None
                issue = int(row["counter_value"])
                await conn.execute(
                    "INSERT INTO cover_style_issue_assignments (profile_id, "
                    "summary_run_id, issue_number) VALUES ($1,$2,$3) "
                    "ON CONFLICT (profile_id, summary_run_id) DO NOTHING",
                    profile_id, summary_run_id, issue)
                final = await conn.fetchrow(
                    "SELECT issue_number FROM cover_style_issue_assignments "
                    "WHERE profile_id = $1 AND summary_run_id = $2",
                    profile_id, summary_run_id)
                return int(final["issue_number"]) if final is not None else issue
    except Exception:
        logger.warning("[cover_style_registry] issue resolve failed",
                       exc_info=True)
        return None


def format_issue(counter_format: str, issue_number: int, *,
                 zero_pad: int = 0) -> str:
    """Форматировать номер по шаблону профиля (`ВЫПУСК {counter}`, §26).

    Слово `ВЫПУСК` не захардкожено — берётся из поля профиля. `zero_pad` —
    минимальная ширина (для preview `ВЫПУСК 00`, §66)."""
    fmt = str(counter_format or "").strip() or SEEDED_COUNTER_FORMAT
    try:
        num = f"{int(issue_number):0{max(0, int(zero_pad))}d}"
        return fmt.replace("{counter}", num)
    except Exception:
        return f"{fmt} {issue_number}".strip()


def preview_issue_display(counter_format: str) -> str:
    """Preview-подпись (§66): `ВЫПУСК 00` — не расходует production counter."""
    return format_issue(counter_format, 0, zero_pad=2)


# ── revision snapshot (§29) ─────────────────────────────────────────────────

def build_revision_snapshot(profile: dict, *, issue_number: int | None = None,
                            capabilities: dict | None = None,
                            slot: dict | None = None) -> dict:
    """Снимок версии стиля на старте Style Job (§29).

    Фиксирует style_id/revision/instructions/reference asset IDs/issue number/
    connection+model/capability snapshot. Изменение профиля во время генерации
    не влияет на текущий job (job работает по снимку).
    """
    refs = profile.get("references") or []
    return {
        "style_id": profile.get("profile_id"),
        "style_revision": profile.get("revision"),
        "resolved_instructions": str(profile.get("instruction") or ""),
        "reference_asset_ids": [r.get("asset_id") for r in refs],
        "issue_number": issue_number,
        "connection_id": (slot or {}).get("connection_id"),
        "model_id": (slot or {}).get("model"),
        "provider": (slot or {}).get("provider"),
        "capabilities": capabilities or {},
        "pipeline_mode": profile.get("pipeline_mode"),
    }


def preview_issue_number() -> int:
    """Test Style (§66): НЕ расходует production counter — preview `ВЫПУСК 00`."""
    return 0


# ── Image Connections (§103–§105, ASAP-3.2 D14) ─────────────────────────────

def _public_connection(row: dict) -> dict:
    """R17-safe представление подключения: api_key/секреты НЕ наружу."""
    key = str(row.get("api_key") or "")
    masked = (key[:3] + "…" + key[-2:]) if len(key) > 6 else \
        ("установлен" if key else "")
    return {
        "connection_id": row.get("connection_id"),
        "label": row.get("label") or "",
        "provider": row.get("provider") or "",
        "base_url": row.get("base_url") or "",
        "api_key_set": bool(key),
        "api_key_masked": masked,
    }


async def list_connections(pg, *, include_deleted: bool = False) -> list[dict]:
    pool = _pool_of(pg)
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            sql = ("SELECT * FROM cover_style_connections "
                   + ("" if include_deleted else "WHERE deleted_at IS NULL ")
                   + "ORDER BY created_at ASC")
            rows = await conn.fetch(sql)
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("[cover_style_registry] connections list failed",
                       exc_info=True)
        return []


async def get_connection(pg, connection_id: str) -> dict | None:
    pool = _pool_of(pg)
    if pool is None or not connection_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cover_style_connections WHERE connection_id = $1 "
                "AND deleted_at IS NULL", connection_id)
        return dict(row) if row is not None else None
    except Exception:
        logger.warning("[cover_style_registry] connection get failed",
                       exc_info=True)
        return None


async def upsert_connection(pg, data: dict) -> bool:
    """Создать/обновить подключение (секрет хранится в PG, НЕ в профиле)."""
    pool = _pool_of(pg)
    if pool is None or not isinstance(data, dict):
        return False
    cid = str(data.get("connection_id") or "").strip() or _new_id("csc")
    base_url = str(data.get("base_url") or "").strip()
    if not base_url:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO cover_style_connections (connection_id, label, "
                "provider, base_url, api_key) VALUES ($1,$2,$3,$4,$5) "
                "ON CONFLICT (connection_id) DO UPDATE SET label=$2, "
                "provider=$3, base_url=$4, "
                "api_key=CASE WHEN $5 <> '' THEN $5 ELSE "
                "cover_style_connections.api_key END, updated_at=now()",
                cid, str(data.get("label") or ""),
                str(data.get("provider") or ""), base_url,
                str(data.get("api_key") or ""))
        return True
    except Exception:
        logger.warning("[cover_style_registry] connection upsert failed",
                       exc_info=True)
        return False


async def soft_delete_connection(pg, connection_id: str) -> bool:
    pool = _pool_of(pg)
    if pool is None or not connection_id:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE cover_style_connections SET deleted_at = now() "
                "WHERE connection_id = $1", connection_id)
        return True
    except Exception:
        logger.warning("[cover_style_registry] connection delete failed",
                       exc_info=True)
        return False



# ── provenance (§30) ────────────────────────────────────────────────────────

async def record_provenance(pg, data: dict) -> str | None:
    pool = _pool_of(pg)
    if pool is None:
        return None
    pid = data.get("provenance_id") or _new_id("covp")
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO cover_style_provenance (provenance_id, "
                "summary_run_id, job_id, style_id, style_revision, issue_number, "
                "base_asset_id, final_asset_id, provider, model, connection_id, "
                "reference_asset_ids, status, fallback_mode, mode) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
                pid, data.get("summary_run_id"), data.get("job_id"),
                data.get("style_id"), data.get("style_revision"),
                data.get("issue_number"), data.get("base_asset_id"),
                data.get("final_asset_id"), data.get("provider"),
                data.get("model"), data.get("connection_id"),
                json.dumps(data.get("reference_asset_ids") or []),
                data.get("status", PROVENANCE_STAGED),
                data.get("fallback_mode"),
                data.get("mode", MODE_PRODUCTION))
        return pid
    except Exception:
        logger.warning("[cover_style_registry] provenance failed", exc_info=True)
        return None


# ── seed (§59, идемпотентно) ────────────────────────────────────────────────

async def _repair_seeded_profile(pg, existing: dict) -> None:
    """ASAP 4.3 (§5/§8): идемпотентные миграции существующей seeded-строки.

    * legacy-инструкция (979 chars, если владелец её не редактировал) →
      компактная §8; revision инкрементируется (preview честно stale);
    * seeded example-placeholder preview pointers (`preview_revision IS NULL`)
      → NULL: placeholders больше не DB preview-assets (файлы не удаляются).
    """
    pool = _pool_of(pg)
    if pool is None:
        return
    changes: list[str] = []
    try:
        async with pool.acquire() as conn:
            if str(existing.get("instruction") or "") \
                    == _LEGACY_SEEDED_INSTRUCTION:
                await conn.execute(
                    "UPDATE cover_style_profiles SET instruction = $2, "
                    "revision = revision + 1, updated_at = now() "
                    "WHERE profile_id = $1",
                    SEEDED_PROFILE_ID, SEEDED_INSTRUCTION)
                changes.append("instruction")
            if existing.get("preview_revision") is None \
                    and (existing.get("preview_before_asset_id")
                         or existing.get("preview_after_asset_id")):
                await conn.execute(
                    "UPDATE cover_style_profiles SET "
                    "preview_before_asset_id = NULL, "
                    "preview_after_asset_id = NULL, "
                    "preview_job_id = NULL, updated_at = now() "
                    "WHERE profile_id = $1", SEEDED_PROFILE_ID)
                changes.append("example_preview_pointers")
    except Exception:
        logger.warning("[cover_style_registry] seeded repair failed",
                       exc_info=True)
        return
    if changes:
        logger.info("[cover_style_registry] seeded profile repaired | %s",
                    ",".join(changes))


async def seed_seeded_style(pg, *, seed_dir=None) -> dict | None:
    """Идемпотентно засидить `Графический роман Медведь Press` (§98/§99).

    Инвариант установки (ASAP-3.2, ADR-1028-5 D14): первый install →
    создаёт профиль/asset'ы; повторный deploy → no-op (без дубля);
    отредактированный владельцем seeded-стиль НЕ перезатирается; удалённый
    владельцем профиль НЕ воскрешается при рестарте (soft-deleted marker);
    прерванный первый seed (нет asset/reference) → событие
    ``COVER_STYLE_SEED_INCOMPLETE`` (§128, fail-open). `extra_images/*`
    не мутируются (копирование, R18).

    ASAP 4.3 (§5): placeholder-файлы `style_example_01/02` НЕ сидятся в
    `cover_style_assets`/preview-колонки — это UI fallback. §8: legacy
    seeded-инструкция мигрируется на компактную (см. `_repair_seeded_profile`).
    Возвращает profile dict (или None, если PG недоступен/seed отсутствует).
    """
    pool = _pool_of(pg)
    if pool is None:
        return None
    base_dir = seed_dir or _seed_dir()
    # Идемпотентность: seeded-профиль уже есть → не трогаем определение,
    # но выполняем аддитивные миграции (§5/§8) и возвращаем refs.
    existing = await get_profile(pg, SEEDED_PROFILE_ID)
    if existing is not None:
        await _repair_seeded_profile(pg, existing)
        return await get_profile_with_refs(pg, SEEDED_PROFILE_ID)
    # §99: удалённый владельцем профиль не воскрешаем (soft-delete marker
    # виден только прямым запросом, get_profile фильтрует is_deleted).
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_id FROM cover_style_profiles "
                    "WHERE profile_id = $1 AND is_deleted = true",
                    SEEDED_PROFILE_ID)
            if row is not None:
                logger.info(
                    "[cover_style_registry] seed skipped — owner deleted "
                    "| profile_id=%s", SEEDED_PROFILE_ID)
                return None
        except Exception:
            logger.warning(
                "[cover_style_registry] seed deleted-check failed — "
                "continue", exc_info=True)

    asset_ids: dict[str, str] = {}
    missing_files: list = []
    for key, filename in SEED_FILES.items():
        src = base_dir / filename
        meta = import_seed_file(src, origin="seed")
        if meta is None:
            logger.warning("[cover_style_registry] seed file missing | %s", src)
            missing_files.append(filename)
            continue
        if await upsert_asset(pg, meta):
            asset_ids[key] = meta["asset_id"]

    profile = {
        "profile_id": SEEDED_PROFILE_ID,
        "name": SEEDED_PROFILE_NAME,
        "origin": ORIGIN_SEEDED,
        "pipeline_mode": MODE_GENERATE_THEN_EDIT,
        "instruction": SEEDED_INSTRUCTION,
        "counter_enabled": True,
        "counter_value": SEEDED_COUNTER_START,
        "counter_format": SEEDED_COUNTER_FORMAT,
        "model_mode": MODEL_MODE_DEFAULT,
        "preview_before_asset_id": asset_ids.get("preview_before"),
        "preview_after_asset_id": asset_ids.get("preview_after"),
        "preview_revision": None,
        "enabled": True,
    }
    if not await upsert_profile(pg, profile):
        return None
    ref_asset = asset_ids.get("reference")
    if ref_asset:
        await add_reference(pg, SEEDED_PROFILE_ID, {
            "asset_id": ref_asset,
            "label": "Медведь Press",
            "description": "Издательский знак серии «Медведь Press» — "
                           "используется для нормализации бренда на обложке.",
            "ordering": 0,
        })
    # §99/§128: прерванный seed (файлы/asset/reference не дошли) — видно.
    incomplete = bool(missing_files) or len(asset_ids) < len(SEED_FILES) \
        or ref_asset is None
    if incomplete:
        try:
            from services.agentic_events import emit_agentic_event
            emit_agentic_event(
                "COVER_STYLE_SEED_INCOMPLETE", style_id=SEEDED_PROFILE_ID,
                stage="seed", reason="assets_or_reference_missing",
                missing_files=len(missing_files),
                assets_ok=len(asset_ids))
        except Exception:
            pass
        logger.warning(
            "COVER_STYLE_SEED_INCOMPLETE | profile_id=%s | missing=%d | "
            "assets=%d", SEEDED_PROFILE_ID, len(missing_files),
            len(asset_ids))
    return await get_profile_with_refs(pg, SEEDED_PROFILE_ID)
