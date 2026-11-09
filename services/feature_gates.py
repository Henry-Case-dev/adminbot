"""Раунд 10 (feature-gates-worker-budget, F-10 §2/Q1) — тяжёлые фичи-гейты.

Модель (двухслойная): колонка `chat_profiles.gates_opt_in` (чат явно
участвует в Opt-In) + значения per-feature в `chat_params["gates"]`
(feature: dream/nostalgia/lore_auto/permsoc). ЕДИНСТВЕННАЯ точка записи:
`set_feature_gate` → F-7 `set_chat_params` (транзакция + история
field='gates' + NOTIFY; 409 optimistic).

Резолв (MOD-ACL-UX-01 M2, §2.1 — канонический `chat_params`):
    gates_enabled(chat, feature):
      1. chat_params.gates[feature] — если запись ЯВНО есть (bool):
         ON / OFF (глобальный слой при этом не спрашивается);
      2. запись отсутствует (INHERIT) → глобальный слой фичи
         (`flags.<feature>_enabled` / master-флаг воркера / код-дефолт).
    GLOBAL — наследуемый дефолт, НЕ запрет: явный чат ON включает фичу при
    глобальном OFF. Приоритет и три-состояние живут в одном месте
    (`services/chat_params.py`), здесь остаётся только маппинг «фича →
    глобальный флаг» и домен хранения `chat_params["gates"]`.
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
# F7 (10.25, ADR-1025-20 D3): + per-chat блок-гейты «Общие реакции» и
# «Расписания» (память — `chat_params["gates"]`, Δ DDL = 0).
ALL_GATED_FEATURES: frozenset[str] = frozenset(
    {"dream", "nostalgia", "lore_auto", "permsoc",
     "permsoc_reactions", "permsoc_schedule"})

# Канонические флаги (F-10 §3 таблица: flags.<feature>_enabled); для
# dream/nostalgia в каталоге лежат memory.dream_enabled/memory.nostalgia_enabled
# (workers читают их) — первый найденный не-None выигрывает.
# F7: у `permsoc_reactions`/`permsoc_schedule` канонического флага НЕТ —
# только явный chat-гейт + default (baseline ON).
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
    # F7 D3: нет явного гейта → функция работает (сохраняем baseline;
    # war/danger/goodmorning раньше НЕ гейтировались мастером — не регрессия).
    "permsoc_reactions": True,
    "permsoc_schedule": True,
}

# F7/R10.18-3: фичи, у которых есть ОТДЕЛЬНЫЙ per-chat master-флаг, который
# воркер передаёт в `gates_enabled(fallback=…)`. Статус-API обязан резолвить
# тот же fallback — иначе UI «Гейты/Тяжёлые» расходится с воркером. Только
# `dream`: `nostalgia`/`lore_auto` воркеры fallback не используют, их
# поведение не меняем.
MASTER_FALLBACK_KEYS: dict[str, str] = {"dream": "memory.dream_enabled"}

# MOD-ACL-UX-01 / M2 (§2.4-4): документированный read-compat alias того же
# capability в ДРУГОМ namespace. `permsoc` исторически имеет два чатовых поля
# (`gates.permsoc` и `overrides["flags.permsoc_enabled"]`); authoritative-путь
# один — gate записи (`set_feature_gate`), а override читается ТОЛЬКО как
# alias при INHERIT. Двойной независимой записи нет.
COMPAT_OVERRIDE_KEYS: dict[str, str] = {"permsoc": "flags.permsoc_enabled"}



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
    return _global_flag_sourced(feature)[0]


def _global_flag_sourced(feature: str) -> tuple[bool, str]:
    """(значение, источник) глобального слоя: `global` — ключ реально
    сохранён в bot_settings/ConfigCache; `default` — код-дефолт каталога.

    Источник нужен каноническому резолверу/UI, чтобы не выдавать дефолт за
    пользовательскую настройку (§2.2)."""
    default = DEFAULT_BY_FEATURE[feature]
    for key in FLAG_KEYS.get(feature, ()):
        try:
            v = hot.get(key, None)
        except Exception:
            v = None
        if v is not None:
            return bool(v), "global"
    return default, "default"


async def gate_state(chat_id: int, feature: str, root: dict | None = None, *,
                     fallback: bool | None = None):
    """Каноническое состояние гейта (все оси) или ``None`` вне домена.

    Возвращает `chat_params.CapabilityState`: chat_state (INHERIT/ON/OFF),
    desired, source, global_value, emergency_block, effective_runtime +
    раздельные ready/authorized/observed. Единственная реализация семантики
    для домена `chat_params.gates` — `gates_enabled` и API/статус читают её.
    """
    if feature not in ALL_GATED_FEATURES:
        return None
    from services import chat_params as cp
    if root is None:
        try:
            from services.chat_params import get_all_chat_params
            root = await get_all_chat_params(chat_id)
        except Exception:
            root = None
    if fallback is not None:
        # F7 (ADR-1018-7 D3/R4): воркер передаёт уже разрешённый per-chat
        # master-флаг. Источник честный: `chat`, если override этого флага
        # реально записан в чате, иначе — глобальный слой.
        alias = MASTER_FALLBACK_KEYS.get(feature)
        source = "global"
        if alias and cp.chat_state(root, alias) != cp.INHERIT:
            source = "chat"
        global_value, global_source = bool(fallback), source
    else:
        global_value, global_source = _global_flag_sourced(feature)
    return await cp.resolve_gate_capability(
        chat_id, feature, global_value=global_value,
        global_source=global_source, root=root,
        chat_alias_key=COMPAT_OVERRIDE_KEYS.get(feature))


async def gates_enabled(chat_id: int, feature: str,
                        root: dict | None = None, *,
                        fallback: bool | None = None) -> bool:
    """Эффективный гейт фичи — ЧЕРЕЗ канонический резолвер chat_params (§2.1).

    Приоритет: явная настройка чата (`chat_params.gates[feature]`, read-compat
    alias — `COMPAT_OVERRIDE_KEYS`) → глобальный слой фичи → дефолт. GLOBAL —
    наследуемый дефолт, а НЕ запрет: явный чат ON включает фичу при GLOBAL
    OFF (строка 5 таблицы §2.1).

    Что изменилось (MOD-ACL-UX-01 M2): глобальный продуктовый флаг больше не
    выступает «тихим мастером-запретом» — аварийная ось остаётся только
    env-рубильником владельца оси (mca_gates), техническая готовность и
    авторизация — отдельные оси. Сама семантика чата/глобали живёт в ОДНОМ
    месте — `services/chat_params.resolve_gate_capability`.
    Fail-open: PG/кэш down → глобальный флаг (прецедентно безопасно)."""
    state = await gate_state(chat_id, feature, root, fallback=fallback)
    return bool(state is not None and state.effective_runtime)


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
