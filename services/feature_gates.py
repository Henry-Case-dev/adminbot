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

# F7/R10.18-3: фичи, у которых есть ОТДЕЛЬНЫЙ per-chat master-флаг, который
# воркер передаёт в `gates_enabled(fallback=…)`. Статус-API обязан резолвить
# тот же fallback — иначе UI «Гейты/Тяжёлые» расходится с воркером. Только
# `dream`: `nostalgia`/`lore_auto` воркеры fallback не используют, их
# поведение не меняем.
MASTER_FALLBACK_KEYS: dict[str, str] = {"dream": "memory.dream_enabled"}


def _master_fallback_default(feature: str) -> bool:
    """R10.18-15: env-дефолт master-флага — ЕДИНЫЙ с воркером.

    Воркер резолвит `memory.dream_enabled` через
    `_key_for(chat_id, "enabled", settings.DREAM_ENABLED)`, т.е. при
    отсутствии DB-ключа дефолт = `settings.DREAM_ENABLED`. Статус обязан
    использовать тот же дефолт, а НЕ `DEFAULT_BY_FEATURE["dream"]=False`:
    иначе при env `DREAM_ENABLED=true` и несозданном ключе в БД воркер ON,
    а `master_fallback`/`cognition.effective` OFF (рассинхрон класса
    S10.18-3). `DEFAULT_BY_FEATURE` остаётся дефолтом глобального слоя
    (`_global_flag_value`), т.к. kill-switch-путь исторически консервативен."""
    if feature == "dream":
        return bool(settings.DREAM_ENABLED)
    return bool(DEFAULT_BY_FEATURE.get(feature, False))


async def master_fallback(chat_id: int, feature: str) -> bool | None:
    """Per-chat master-флаг для параметра `fallback` (chat DB → global DB →
    env) — ровно то, что DreamWorker передаёт в `gates_enabled`. None — для
    фич без отдельного master-флага (поведение без fallback сохраняется)."""
    key = MASTER_FALLBACK_KEYS.get(feature)
    if key is None:
        return None
    try:
        from services.worker_settings import resolve_setting_cached
        return bool(await resolve_setting_cached(
            key, chat_id=chat_id,
            default=_master_fallback_default(feature)))
    except Exception:
        return None


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


def _explicit_flag_value(feature: str) -> bool | None:
    """Явное значение КАНОНИЧЕСКОГО kill-switch флага (первый ключ FLAG_KEYS)
    либо None, если ключ не задан.

    Фикс R10.18-3: для `dream`/`nostalgia` канонический ключ —
    `flags.<feature>_enabled` (kill-switch), а `memory.<feature>_enabled` —
    master-флаг, который воркер передаёт как `fallback`. Kill-switch должен
    побеждать fallback: явный глобальный `flags.dream_enabled=false`
    останавливает тик даже при per-chat `memory.dream_enabled=true`."""
    keys = FLAG_KEYS.get(feature, ())
    if not keys:
        return None
    try:
        v = hot.get(keys[0], None)
    except Exception:
        return None
    return None if v is None else bool(v)


async def gates_enabled(chat_id: int, feature: str,
                        root: dict | None = None, *,
                        fallback: bool | None = None) -> bool:
    """Эффективный гейт (приоритет: явный chat-гейт → явный глобальный
    kill-switch → fallback (master-флаг) → глобальный флаг → False).
    Fail-open: PG/кэш down → глобальный флаг (прецедентно безопасно).

    F7 (ADR-1018-7 D3/R4): `fallback` позволяет вызывающему передать уже
    разрешённый per-chat master-флаг (`memory.dream_enabled` по приоритету
    chat → global → default). Явный глобальный kill-switch
    (`flags.<feature>_enabled`) при этом сохраняет приоритет — иначе
    выключение рубильника не останавливало бы воркер (регрессия R10.18-3)."""
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
    explicit = _explicit_flag_value(feature)
    if explicit is not None:
        return explicit
    if fallback is not None:
        return bool(fallback)
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
        # R10.18-3: тот же fallback, что у воркера (per-chat master) — статус
        # совпадает с фактическим поведением, а не только с глобальным слоем.
        fb = await master_fallback(chat_id, feature)
        out[feature] = await gates_enabled(chat_id, feature, root=root,
                                           fallback=fb)
    return out
