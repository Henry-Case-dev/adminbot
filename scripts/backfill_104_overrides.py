"""Раунд 10.4 (G-5) — идемпотентный бэкфил per-chat overrides для
chat_id=-1002661910336 (расширение контекста/саммари/памяти ×1.5–×2).

Правила:
  * ensure_scope_profile(chat_id, dm=False) ДО записи (иначе 409 «профиля нет»);
  * запись ТОЛЬКО отсутствующих ключей (перезаписи запрещены; повтор — no-op);
  * expected_updated_at=None — идемпотентность (последняя запись побеждает);
  * канон write-path: set_chat_params (NOTIFY/кэш-инвалидация/история);
  * значения = множители к ТЕКУЩИМ кодовым дефолтам Settings (см. п.4 спеки);
    graph_edge_weight_increment — НЕ меняем (семантика графа, точка 11 — только
    перевод резолва, значение сохраняется глобальным).

Запуск: python scripts/backfill_104_overrides.py [--dry-run]
"""
import asyncio
import sys

TARGET_CHAT_ID = -1002661910336

# Ключ → (множитель, cap|None) — для caps (участники ≤ 300).
# Значения читаются из действующих дефолтов Settings (фолбэк hot.get).
# Ревью-фикс (R10.4-3): *TOKENS-ключи треда/глобального контекста имеют
# Settings=None (транзaction-режим выключен; рантайм работает в charset-
# режиме) → молчаливый SKIP. Таблица приведена к ФАКТИЧЕСКОМУ поведению:
# заменяем thread_tokens на ЖИВОЙ charset-ключ chat_thread_max_chars (×2 по
# таблице G «тред ×2»), global_context_max_tokens исключён (charset ×1.5 —
# через max_chars, который в таблице).
OVERRIDE_MULTIPLIERS = {
    "limits.chat_context_budget_tokens": (2.0, None),
    "limits.chat_global_context_max_chars": (1.5, None),
    "limits.chat_global_context_limit": (1.5, None),
    "limits.chat_thread_max_chars": (2.0, None),
    "limits.chat_level2_max_chars": (2.0, None),
    "limits.chat_map_participants_cap": (2.0, 300),
    "limits.summary_max_context_tokens": (2.0, None),
    "limits.summary_max_context_chars": (2.0, None),
    "limits.summary_max_window_messages": (2.0, None),
    "limits.summary_rag_l2_limit": (2.0, None),
    "limits.summary_compress_batch": (2.0, None),
    "limits.full_memory_retention_days": (2.0, None),
    "limits.archive_memory_retention_days": (2.0, None),
    "limits.graph_rag_facts_limit": (2.0, None),
    "limits.graph_rag_context_max_chars": (2.0, None),
    # graph_edge_weight_increment — НЕ в списке (семантика графа; G-п.4)
    # limits.chat_global_context_max_tokens / chat_thread_max_tokens —
    # НЕ в таблице (Settings=None, tokens-режим не используется; рантайм —
    # charset: max_chars/max_chars_level2 — см. строки выше и _thread_limit).
}


def _current_value(key: str):
    """Текущее (глобальное) значение ключа — из hot-кэша или Settings."""
    from config.settings import settings as s
    from services import hot_config as hot
    field = key.split(".", 1)[1].upper()
    default = getattr(s, field, None)
    return hot.get(key, default)


def _target_value(key: str, multiplier: float, cap: int | None):
    cur = _current_value(key)
    try:
        base = float(cur)
    except (TypeError, ValueError):
        base = None
    if base is None:
        return None            # неизвестный дефолт — пропуск (no-op на этот ключ)
    value = int(round(base * multiplier))
    if cap is not None:
        value = min(value, cap)
    return value


async def _run(dry_run: bool) -> int:
    from services import chat_params
    from services import hot_config as hot

    cache = hot.get_config_cache()
    if cache is None or getattr(cache, "pg", None) is None:
        print("[backfill_104_overrides] ConfigCache/PG недоступен — выход")
        return 1
    pg = cache.pg

    await chat_params.ensure_scope_profile(TARGET_CHAT_ID, dm=False, pg=pg)
    root = await chat_params.get_all_chat_params(TARGET_CHAT_ID)
    overrides = dict(root.get("overrides") or {})

    patch = {}
    for key, (mult, cap) in OVERRIDE_MULTIPLIERS.items():
        if key in overrides:
            continue                       # no-op: уже настроено админом
        value = _target_value(key, mult, cap)
        if value is None:
            print(f"[backfill_104_overrides] skip (нет дефолта): {key}")
            continue
        patch[key] = value
    if not patch:
        print("[backfill_104_overrides] no-op: все ключи уже в overrides")
        return 0
    print(f"[backfill_104_overrides] write {len(patch)} ключей:")
    for k, v in sorted(patch.items()):
        print(f"   {k} = {v}")
    if dry_run:
        print("[backfill_104_overrides] dry-run — запись пропущена")
        return 0
    meta = dict(root.get("meta") or {})
    meta["note"] = "backfill_104: scaling overrides (контекст/саммари/память)"
    new_overrides = dict(overrides)
    new_overrides.update(patch)
    await chat_params.set_chat_params(
        TARGET_CHAT_ID, {"overrides": new_overrides, "meta": meta},
        changed_by=None, pg=pg)
    print("[backfill_104_overrides] done: overrides установлены, NOTIFY эмит")
    return 0


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return asyncio.run(_run(dry_run))


if __name__ == "__main__":
    sys.exit(main())
