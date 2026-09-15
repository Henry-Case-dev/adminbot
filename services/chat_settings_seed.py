"""F3 (10.19, ADR-1019-8 D4) — сид настроек чатов: эксклюзивные per-chat настройки
чатов ДАННЫМИ, не хардкодом.

Источник — `config/chat_settings_seed.json` (versioned, без секретов):
`{version, chats: [{chat_id, note, enforce: [...], overrides: {...}}]}`.

Идемпотентность: ensure-профиль → merge overrides (текущие ∪ желаемые) →
`set_chat_params` ТОЛЬКО при фактическом изменении (иначе skip: без UPDATE,
history-шума и NOTIFY). Повторный запуск — no-op.

Политика полей (D4):
  * `enforce`-ключи (retention) применяются **всегда** — tail-инвариант
    безопасности данных (вечное хранение нельзя случайно снять через UI);
  * остальные (бюджеты/контекст) — при отсутствии ключа, при росте
    `version` сида или `force=True` (уважает ручные правки владельца).

Id чата присутствует ТОЛЬКО в `config/chat_settings_seed.json` и тестах; код-путь
полностью generic — цикл `for entry in seed["chats"]`, ветвлений по
конкретному id нет.
Fail-open: PG down / нет файла → WARNING, бот жив.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "chat_settings_seed.json")
SEED_META_KEY = "chat_settings_seed_version"
# Ключ-«вечность» импорта: присутствие в `enforce` = purge импорта для чата
# ЖЁСТКО запрещён (D-1, defence-in-depth к seed-политике; данные, не код).
RETENTION_KEY = "limits.import_history_retention_days"

# D-2.4 (Low, ревью итерации 4): кэш разбора файла сида — резолв retention
# вызывается per-chat, повторное чтение JSON на каждом вызове лишнее.
# Ключ — путь; значение — `((mtime_ns, size), data, ok, enforced_ids)`.
_seed_cache: dict[str, tuple] = {}


def _extract_enforced_ids(seed: dict) -> set[int]:
    """chat_id с retention-ключом в `enforce` (generic-обход, без хардкода id)."""
    out: set[int] = set()
    for entry in seed.get("chats") or []:
        try:
            chat_id = int(entry["chat_id"])
        except (KeyError, TypeError, ValueError):
            continue
        enforce = set(entry.get("enforce") or [])
        if RETENTION_KEY in enforce:
            out.add(chat_id)
    return out


def _seed_snapshot(seed_path: str | Path | None = None) -> tuple[dict, bool, set[int]]:
    """`(seed, ok, enforced_ids)` — разбор кэшируется по (mtime_ns, size).

    `ok=False` — файл отсутствует/нечитаем/битый JSON (данные при этом `{}`).
    D-2.4: потребитель-барьер (`retention_policy`) обязан трактовать `ok=False`
    как «запретить purge» (fail-safe), а не как «enforce пуст».
    """
    path = Path(seed_path) if seed_path else DEFAULT_SEED_PATH
    key = str(path)
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        # Файла нет — не кэшируем (появится позже → перечитаем).
        return {}, False, set()
    cached = _seed_cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1], cached[2], cached[3]
    data: dict = {}
    ok = True
    try:
        with open(path, encoding="utf-8") as fh:
            parsed = json.load(fh)
        if not isinstance(parsed, dict):
            raise ValueError("корень сида — не объект")
        data = parsed
    except Exception:
        ok = False
        logger.warning("[chat_settings_seed] сид недоступен — skip | path=%s",
                       path, exc_info=True)
    enforced = _extract_enforced_ids(data) if ok else set()
    if ok and not enforced:
        # D-2.4: барьер hard-deny фактически отключён — громкий WARNING.
        logger.warning("[chat_settings_seed] enforce retention пуст — "
                       "hard-deny барьер отключён | path=%s", path)
    _seed_cache[key] = (signature, data, ok, enforced)
    return data, ok, enforced


def load_chat_settings_seed(seed_path: str | Path | None = None) -> dict:
    """Прочитать сид (пустой dict при ошибке — fail-open для apply-пути).

    Для разрушительного барьера используйте `enforced_eternal_chat_ids_checked`
    (различает «enforce пуст» и «сид нечитаем»)."""
    data, _ok, _enforced = _seed_snapshot(seed_path)
    return data


def enforced_eternal_chat_ids(seed_path: str | Path | None = None) -> set[int]:
    """chat_id, у которых ключ retention импорта в `enforce`.

    Fail-open (пусто) при недоступном файле — для барьера используйте
    `enforced_eternal_chat_ids_checked`, чтобы отличить «пусто» от «не читается»."""
    _data, _ok, enforced = _seed_snapshot(seed_path)
    return set(enforced)


def enforced_eternal_chat_ids_checked(
        seed_path: str | Path | None = None) -> tuple[set[int], bool]:
    """`(chat_ids, ok)` — D-2.4: `ok=False` при нечитаемом/битом сиде, чтобы
    destructive-purge был запрещён (fail-safe), а не разрешён молча."""
    _data, ok, enforced = _seed_snapshot(seed_path)
    return set(enforced), ok


def _seed_version(seed: dict) -> int:
    try:
        return int(seed.get("version", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def apply_chat_settings_seed(pg, *, force: bool = False,
                         seed_path: str | Path | None = None) -> dict:
    """Применить сид настроек чатов. Возврат-отчёт: `{applied, skipped, errors}`.

    `applied` — список `(chat_id, [изменённые ключи])`; `skipped` — chat_id
    без изменений (идемпотентный повтор); `errors` — chat_id с ошибкой записи.
    """
    report: dict = {"applied": [], "skipped": [], "errors": []}
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        logger.info("[chat_settings_seed] skip: PG недоступен")
        return report
    seed = load_chat_settings_seed(seed_path)
    version = _seed_version(seed)
    entries = seed.get("chats") or []
    from services import chat_params
    for entry in entries:
        try:
            chat_id = int(entry["chat_id"])
        except (KeyError, TypeError, ValueError):
            logger.warning("[chat_settings_seed] битая запись сида — skip")
            continue
        wanted = dict(entry.get("overrides") or {})
        enforce = set(entry.get("enforce") or [])
        try:
            await chat_params.ensure_scope_profile(chat_id, dm=False, pg=pg)
            # D-2 (ревью Батча C): читаем НАПРЯМУЮ из PG, а не через
            # процесс-глобальный кэш — в CLI (`manage.py apply-chat-overrides`) кэш пуст,
            # иначе merge затирает чужие overrides/meta целевого чата.
            root = await chat_params.get_all_chat_params(chat_id, pg=pg)
            current = dict(root.get("overrides") or {})
            meta = dict(root.get("meta") or {})
            try:
                current_version = int(meta.get(SEED_META_KEY, 0) or 0)
            except (TypeError, ValueError):
                current_version = 0
            version_bump = version > current_version
            patch: dict = {}
            for key, value in wanted.items():
                present = key in current
                if key in enforce:
                    if current.get(key) != value:
                        patch[key] = value
                elif force or not present or version_bump:
                    if current.get(key) != value:
                        patch[key] = value
            if not patch:
                report["skipped"].append(chat_id)
                logger.info("[chat_settings_seed] без изменений (no-op) | chat=%s",
                            chat_id)
                continue
            merged = dict(current)
            merged.update(patch)
            meta[SEED_META_KEY] = version
            # HOTFIX (10.19): `changed_by` — колонка `chat_lore_history.changed_by
            # BIGINT` (services/pg_db.py:95). Строковый литерал
            # ("chat_settings_seed") давал asyncpg DataError на проде → сид
            # никогда не применялся (fail-open глотал исключение).
            # Выбор `None` (а не int-сентинела/`record_history=False`):
            #   * согласован с кодовой базой — все системные/скриптовые записи
            #     используют `changed_by=None` (scripts/backfill_*.py,
            #     handlers/chat_lifecycle.py); README: «changed_by NULL = бот/AI»;
            #   * сохраняет аудит-строку истории (важно для трассировки
            #     применения сида; `record_history=False` затёр бы аудит);
            #   * int-сентинел `0` в репозитории нигде не используется.
            await chat_params.set_chat_params(
                chat_id, {"overrides": merged, "meta": meta},
                changed_by=None, pg=pg)
            report["applied"].append((chat_id, sorted(patch)))
            logger.info("[chat_settings_seed] применено | chat=%s | keys=%s",
                        chat_id, ",".join(sorted(patch)))
        except Exception:
            report["errors"].append(chat_id)
            logger.warning("[chat_settings_seed] ошибка применения — fail-open | "
                           "chat=%s", chat_id, exc_info=True)
    return report
