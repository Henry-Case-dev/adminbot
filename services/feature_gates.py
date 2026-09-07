"""Раунд 10 (feature-gates-worker-budget, F-10 §2/Q1) — тяжёлые фичи-гейты.

Модель (двухслойная): колонка `chat_profiles.gates_opt_in` (чат явно
участвует в Opt-In) + значения per-feature в `chat_params["gates"]`
(feature: dream/nostalgia/lore_auto/permsoc). ЕДИНСТВЕННАЯ точка записи:
`set_feature_gate` → F-7 `set_chat_params` (транзакция + история
field='gates' + NOTIFY; 409 optimistic).

Резолв (единый, F-9/F-12):
    gates_enabled(chat, feature):
      1. chat_params.gates[feature] — если явно (bool);
      2. hot.get("flags.<feature>_enabled", settings-дефолт) — глобальный
         слой (существующие флаги остаются глобальными дефолтами);
      3. иначе False (безопасно).
"OFF для новых чатов" — явная запись gates=false при ensure_profile
(chat_lifecycle.ensure_gates_defaults); живые чаты (без явных гейтов) при
включённом глобальном флаге остаются ON (прежнее поведение).
"""
import logging

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# Тяжёлые фичи (Q2): ровно три; relations/dig_into_lore НЕ гейтируются.
HEAVY_FEATURES: frozenset[str] = frozenset({"dream", "nostalgia",
                                            "lore_auto"})
# Все гейтящиеся фичи (тяжёлые + лёгкий master PERMsoc, F-9).
ALL_GATED_FEATURES: frozenset[str] = frozenset(
    {"dream", "nostalgia", "lore_auto", "permsoc"})

# Канонические флаги (F-10 §3 таблица: flags.<feature>_enabled); для
# dream/nostalgia в каталоге лежат memory.dream_enabled/memory.nostalgia_enabled
# (workers читают их) — первый найденный не-None выигрывает.
FLAG_KEYS: dict[str, tuple[str, ...]] = {
    "dream": ("flags.dream_enabled", "memory.dream_enabled"),
    "nostalgia": ("flags.nostalgia_enabled", "memory.nostalgia_enabled"),
    "lore_auto": ("flags.lore_auto_enabled",),
    "permsoc": ("flags.permsoc_enabled",),
}

DEFAULT_BY_FEATURE = {
    "dream": False,
    "nostalgia": False,
    "lore_auto": True,      # settings.LORE_AUTO_ENABLED (живые чаты ON)
    "permsoc": False,
}


def _global_flag_value(feature: str) -> bool:
    """Значение глобального слоя: первый НЕ-None из FLAG_KEYS[feature]
    (None = ключ не задан в кэше — переходим к следующему/дефолту)."""
    default = DEFAULT_BY_FEATURE[feature]
    value = default
    for key in FLAG_KEYS.get(feature, ()):
        try:
            v = hot.get(key, None)
        except Exception:
            v = None
        if v is not None:
            value = bool(v)
            break
    return value


async def gates_enabled(chat_id: int, feature: str,
                        root: dict | None = None) -> bool:
    """Эффективный гейт (приоритет §2: явный chat-гейт → глобальный флаг →
    False). Fail-open: PG/кэш down → глобальный флаг (pretcедачно безопасно)."""
    if feature not in ALL_GATED_FEATURES:
        return False
    if root is None:
        try:
            from services.chat_params import get_all_chat_params
            root = await get_all_chat_params(chat_id)
        except Exception:
            root = None
    if isinstance(root, dict):
        gates = root.get("gates") or {}
        if feature in gates:
            try:
                return bool(gates[feature])
            except Exception:
                return False
    try:
        return _global_flag_value(feature)
    except Exception:
        return False


async def set_feature_gate(chat_id: int, feature: str, enabled: bool, *,
                           changed_by=None, expected_updated_at: str | None = None,
                           pg=None) -> dict:
    """ЕДИНСТВЕННАЯ точка записи gates (F-7 set_chat_params; история
    field='gates'; 409 optimistic; auto_opt_in при первом тяжёлом ON)."""
    if feature not in ALL_GATED_FEATURES:
        raise ValueError(f"неизвестная фича: {feature}")
    from services import chat_params as cp
    root = await cp.get_all_chat_params(chat_id)
    gates = dict(root.get("gates") or {})
    gates[feature] = bool(enabled)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = changed_by
    new_root = await cp.set_chat_params(
        chat_id, {"gates": gates, "meta": meta},
        changed_by=changed_by, pg=pg,
        expected_updated_at=expected_updated_at,
        history_field="gates")
    if feature in HEAVY_FEATURES and enabled:
        try:
            await auto_opt_in(chat_id, pg=pg)
        except Exception:
            logger.warning("[gates] auto_opt_in failed — fail-open | chat=%s",
                           chat_id, exc_info=True)
    return new_root


async def has_opt_in(chat_id: int, pg=None, root: dict | None = None) -> bool:
    """gates_opt_in (колонка). Fail-open → False."""
    if root is None:
        try:
            if pg is None:
                from services import hot_config as hot
                cache = hot.get_config_cache()
                pg = getattr(cache, "pg", None) if cache is not None else None
            pool = getattr(pg, "pool", None) if pg is not None else None
            if pool is None:
                return False
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT gates_opt_in FROM chat_profiles "
                    "WHERE chat_id = $1", chat_id)
            return bool(row and row["gates_opt_in"])
        except Exception:
            return False
    return bool(root.get("gates_opt_in"))


async def auto_opt_in(chat_id: int, pg=None) -> None:
    """Первое включение тяжёлой: gates_opt_in=true (та же идемпотентность)."""
    try:
        if pg is None:
            from services import hot_config as hot
            cache = hot.get_config_cache()
            pg = getattr(cache, "pg", None) if cache is not None else None
        if pg is None:
            return
        async with getattr(pg, "pool").acquire() as conn:
            await conn.execute(
                "UPDATE chat_profiles SET gates_opt_in = true "
                "WHERE chat_id = $1 AND NOT gates_opt_in", chat_id)
    except Exception:
        logger.warning("[gates] auto_opt_in write failed — fail-open | "
                       "chat=%s", chat_id, exc_info=True)


async def allowed_features(chat_id: int) -> dict[str, bool]:
    """{feature: effective} для API/сводки (без N+1: один root-чтение)."""
    root = {}
    try:
        from services.chat_params import get_all_chat_params
        root = await get_all_chat_params(chat_id)
    except Exception:
        pass
    out = {}
    for feature in sorted(ALL_GATED_FEATURES):
        out[feature] = await gates_enabled(chat_id, feature, root=root)
    return out
