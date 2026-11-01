"""Раунд 10.14 (F2 persona-storage-core, ADR-1014-1) — личность БОТА.

ВАЖНО (naming): это личность БОТА (`personas`/`persona_traits` в PG).
Существующие `build_persona_card`/`get_persona_card`/«досье» — карточка
ПОЛЬЗОВАТЕЛЯ (F8 10.13) — НЕ ТРОГАЮТСЯ.

Хранилище (PG):
  * `personas` — статические поля (name/biography/system_prompt_overrides/
    is_aware_ai) со scope first-class (`is_global` + `chat_id`);
  * `persona_traits` — динамические черты характера (пишет «Глубокий сон»).

Резолв scope: per-chat строка → global строка → `BotPersona.empty()`.
Fail-open: PG down/ошибка → пустая персона (промпт деградирует к прежнему
поведению байт-в-байт, spec §3.2/F2-Q5).

Промпт-блок дописывается ХВОСТОМ системного промпта direct-чата
(`system_prompt + "\n\n" + block`); при `is_aware_ai=false` после `</Persona>`
идёт жёсткий запрет `_NO_AI_DISCLOSURE_BLOCK` (fail-safe: бот не признаёт
ИИ-природу).
"""
import dataclasses
import datetime
import logging

from config.settings import settings
from services import hot_config as hot
from services import mca_gates

logger = logging.getLogger(__name__)

# Hard prohibition (spec §3.1, ADR-1014-1 §2): при is_aware_ai=false —
# дописывается ПОСЛЕ </Persona>. Текст — канон из spec §3.1.
_NO_AI_DISCLOSURE_BLOCK = (
    "Ты НЕ раскрываешь и не признаёшь, что ты бот, ИИ, программа или модель. "
    "На вопросы «ты бот/ИИ/нейросеть?» — отвечай в образе своей биографии, "
    "не подтверждай и не опровергай техническую природу."
)

# ── MCA-08 (D1, ADR-1028-11): read-side слои характера ──────────────────────
# Доменные слои персоны (read-side; без нового хранилища): постоянное ядро
# владельца, настроенный стиль и изменяемые производные черты. Порядок
# разрешения конфликтов — канон §28.4 (`current_task.md:1560`), один на фичу.
CHARACTER_LAYERS: tuple[str, ...] = ("owner_core", "owner_style",
                                     "derived_traits")
CHARACTER_PRECEDENCE: tuple[str, ...] = ("owner_core", "owner_style",
                                         "scoped_request", "derived_traits",
                                         "state")

# Канон §4 (D2): мнение vs факт + запрет выдуманных событий. Рендерится
# вызывающим ТОЛЬКО вместе с непустым persona-блоком; K1 OFF — не строится.
_CHARACTER_RULES_BLOCK = (
    "<Character_Rules>\n"
    "Своё мнение — это твоя позиция: помечай его как мнение, а не как факт. "
    "Обсуждай события, встречи и действия только по материалам диалога; "
    "если материалов нет — честно скажи об этом и ничего не выдумывай.\n"
    "</Character_Rules>"
)

# ── SQL ─────────────────────────────────────────────────────────────────────
_SELECT_CHAT_SQL = (
    "SELECT name, biography, system_prompt_overrides, is_aware_ai, updated_at "
    "FROM personas WHERE chat_id = $1 AND is_global = false LIMIT 1"
)
_SELECT_GLOBAL_SQL = (
    "SELECT name, biography, system_prompt_overrides, is_aware_ai, updated_at "
    "FROM personas WHERE is_global = true LIMIT 1"
)
_UPSERT_GLOBAL_SQL = """
    INSERT INTO personas (chat_id, is_global, name, biography,
                          system_prompt_overrides, is_aware_ai)
    VALUES (NULL, true, $1, $2, $3, $4)
    ON CONFLICT (is_global) WHERE is_global DO UPDATE SET
        name = EXCLUDED.name,
        biography = EXCLUDED.biography,
        system_prompt_overrides = EXCLUDED.system_prompt_overrides,
        is_aware_ai = EXCLUDED.is_aware_ai,
        updated_at = now()
    RETURNING updated_at
"""
_UPSERT_CHAT_SQL = """
    INSERT INTO personas (chat_id, is_global, name, biography,
                          system_prompt_overrides, is_aware_ai)
    VALUES ($1, false, $2, $3, $4, $5)
    ON CONFLICT (chat_id) WHERE chat_id IS NOT NULL DO UPDATE SET
        name = EXCLUDED.name,
        biography = EXCLUDED.biography,
        system_prompt_overrides = EXCLUDED.system_prompt_overrides,
        is_aware_ai = EXCLUDED.is_aware_ai,
        updated_at = now()
    RETURNING updated_at
"""
_DELETE_CHAT_SQL = (
    "DELETE FROM personas WHERE chat_id = $1 AND is_global = false"
)
_INSERT_TRAIT_SQL = (
    "INSERT INTO persona_traits (chat_id, trait, source) VALUES ($1, $2, $3)"
)
_ROTATE_TRAITS_SQL = (
    "DELETE FROM persona_traits WHERE id NOT IN ("
    "SELECT id FROM persona_traits ORDER BY created_at DESC, id DESC LIMIT $1)"
)
_TRAITS_STATS_SQL = (
    "SELECT COUNT(*) AS traits_count, MAX(created_at) AS last_trait_at "
    "FROM persona_traits"
)
_SELECT_PERSONA_STATE_SQL = (
    "SELECT last_extract_status, last_extract_at, last_trait_status, "
    "last_trait_at FROM persona_state WHERE id = true LIMIT 1"
)
_UPSERT_TRAIT_STATE_SQL = """
    INSERT INTO persona_state (id, last_trait_at, last_trait_status, updated_at)
    VALUES (true, now(), $1, now())
    ON CONFLICT (id) DO UPDATE SET
        last_trait_at = now(),
        last_trait_status = EXCLUDED.last_trait_status,
        updated_at = now()
"""


class PersonaUnavailable(RuntimeError):
    """PG недоступен — запись персоны невозможна (503 на API)."""


class PersonaConflict(RuntimeError):
    """Optimistic-конфликт updated_at (409 на API)."""

    def __init__(self, current_updated_at: str | None):
        super().__init__("persona updated_at conflict")
        self.current_updated_at = current_updated_at


# ── Pool (DI/фейки в тестах; рантайм — ConfigCache.pg.pool) ────────────────
_pool_override = None


def set_persona_pool(pool) -> None:
    """Инъекция PG-пула (бот/тесты); None → рантайм-резолв через hot_config."""
    global _pool_override
    _pool_override = pool


def reset_persona_pool() -> None:
    global _pool_override
    _pool_override = None


def _persona_pool():
    if _pool_override is not None:
        return _pool_override
    cache = hot.get_config_cache()
    pg = getattr(cache, "pg", None) if cache is not None else None
    return getattr(pg, "pool", None) if pg is not None else None


# ── Модель ──────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class BotPersona:
    """Резолвнутая личность бота (frozen). `scope_chat_id=None` → global."""

    name: str = ""
    biography: str = ""
    overrides: str = ""
    is_aware_ai: bool = True
    scope_chat_id: int | None = None
    is_global: bool = False
    # Раунд 10.14 (F2, H1 fix): optimistic-токен строки personas. Отдаётся
    # в GET/PUT и возвращается обратно клиентом для 409-протокола.
    updated_at: str | None = None

    @classmethod
    def empty(cls) -> "BotPersona":
        return cls()

    @property
    def is_empty(self) -> bool:
        return not (self.name or self.biography or self.overrides)


@dataclasses.dataclass(frozen=True)
class CharacterReadContext:
    """MCA-08 (D1): единый read-контекст характера на ответ (§3).

    `traits_scope="global"` фиксирует текущую семантику общего пула черт
    (`get_traits` без chat_id) — шов mca-18: замена выбора/компиляции черт
    на BehaviorFrame выполняется через этот контекст, сигнатуры не ломаются.
    """

    persona: BotPersona
    traits: tuple[str, ...] = ()
    traits_scope: str = "global"
    # mca-18 (T-5081): версия BehaviorFrame запуска (None = frame-путь
    # не активен — K1 OFF/ошибка; честный skip, промпт legacy).
    frame_version: str | None = None


# ── Резолв scope ────────────────────────────────────────────────────────────

def _clean(value) -> str:
    return str(value or "").strip()


def _row_to_persona(row, *, chat_id: int | None,
                    is_global: bool) -> BotPersona:
    return BotPersona(
        name=_clean(row.get("name")),
        biography=_clean(row.get("biography")),
        overrides=_clean(row.get("system_prompt_overrides")),
        is_aware_ai=bool(row.get("is_aware_ai", True)),
        scope_chat_id=chat_id,
        is_global=is_global,
        updated_at=_iso(row.get("updated_at")),
    )


async def resolve_bot_persona(chat_id: int | None) -> BotPersona:
    """per-chat строка → global строка → `BotPersona.empty()`.
    Fail-open: PG down/ошибка → empty (WARNING; промпт не рушится)."""
    pool = _persona_pool()
    if pool is None:
        return BotPersona.empty()
    try:
        async with pool.acquire() as conn:
            if chat_id is not None:
                row = await conn.fetchrow(_SELECT_CHAT_SQL, int(chat_id))
                if row is not None:
                    return _row_to_persona(row, chat_id=int(chat_id),
                                           is_global=False)
            row = await conn.fetchrow(_SELECT_GLOBAL_SQL)
            if row is not None:
                return _row_to_persona(row, chat_id=None, is_global=True)
    except Exception:
        logger.warning("[bot_persona] resolve failed — fail-open empty | "
                       "chat=%s", chat_id, exc_info=True)
        return BotPersona.empty()
    return BotPersona.empty()


# ── Промпт-блок ─────────────────────────────────────────────────────────────

def build_persona_prompt_block(persona: BotPersona,
                               traits: "list[str] | tuple[str, ...]" = (),
                               *, enabled: bool | None = None,
                               frame=None) -> str:
    """Блок <Persona> для хвоста системного промпта (spec §3.2).

    Пусто/флаг OFF → '' (промпт байт-в-байт прежний). Пустые секции не
    рендерятся. `is_aware_ai=false` → после `</Persona>` запрет признавать ИИ.

    `enabled` (H3-фикс): резолвнутый per-chat гейт `flags.persona_enabled`.
    None → глобальный hot.get (sync-совместимость и старые тесты).

    mca-18 (D3/T-5080/T-5081): мастер-гейт ON + кадр запуска (holder из
    `resolve_character_context` или явный `frame=`) → рендер ИЗ BehaviorFrame:
    правила во 2-м лице (≠ цитат), A58-минимум при пустой персоне,
    формулировка False ЗАМЕНЯЕТ `_NO_AI_DISCLOSURE_BLOCK`. Без кадра →
    legacy-ветка байт-в-байт (K1 OFF/прямые вызовы тестов)."""
    if enabled is None:
        enabled = hot.get("flags.persona_enabled", settings.PERSONA_ENABLED)
    if not enabled:
        return ""
    if persona is None:
        return ""
    # ── mca-18: кадр запуска → рендер из BehaviorFrame (одна точка сборки).
    if frame is None and mca_gates.self_model_enabled():
        try:
            from services import mca_self_model as msm
            frame = msm.current_run_frame()
        except Exception:
            frame = None
    if frame is not None:
        from services import mca_events
        try:
            from services import mca_self_model as msm
            block = msm.render_frame_block(
                frame, name=_clean(persona.name),
                biography=_clean(persona.biography),
                overrides=_clean(persona.overrides))
            mca_events.emit_mca_event(
                "self_model", outcome="success", component="self_model",
                stage="prompt_render", status=frame.version[:64])
            return block
        except Exception:
            logger.warning("[bot_persona] frame render failed — legacy",
                           exc_info=True)
            try:
                mca_events.emit_mca_event(
                    "self_model", outcome="failed", level="WARN",
                    component="self_model", stage="prompt_render",
                    reason_code="self_model_snapshot_error",
                    status="render_failed_legacy")
            except Exception:
                pass
    lines: list[str] = []
    name = _clean(persona.name)
    biography = _clean(persona.biography)
    overrides = _clean(persona.overrides)
    trait_list = [t for t in ((" ".join(str(x).split()) for x in (traits or ())))
                  if t]
    if name:
        lines.append(f"Имя: {name}")
    if biography:
        lines.append(f"Биография: {biography}")
    if overrides:
        lines.append(f"Характер: {overrides}")
    if trait_list:
        lines.append("Черты, которые ты приобрёл: "
                     + " ".join(f"• {t}" for t in trait_list))
    if not lines:
        return ""
    block = "<Persona>\n" + "\n".join(lines) + "\n</Persona>"
    if not persona.is_aware_ai:
        block = block + "\n" + _NO_AI_DISCLOSURE_BLOCK
    return block


def build_character_rules_block() -> str:
    """MCA-08 (D2): канон «мнение vs факт» / запрет выдуманных событий.

    Чистый текст; решение о рендере (непустой persona-блок + K1 ON) принимает
    вызывающий. K1 OFF (`mca_gates.character_layers_enabled()` False) →
    блок не вызывается и в промпт не попадает (байт-паритет 2.58.54)."""
    return _CHARACTER_RULES_BLOCK


# ── ASAP-FC-VOICE-01 / B: характер как ДАННЫЕ для decision-планеров ─────────
# Причина правки по коду (plans/owner_inputs/2026-11-02-asap-fc-voice-01.md §5):
# L1 получал головной срез ПРОЗЫ `<Persona>` (`L1_PERSONA_FRAME_CHARS = 400`)
# и не получал ни одного поведенческого факта: 400 символов обычно обрывались
# на биографии, а секция «ХАРАКТЕР (кадр)» стояла последней, не была защищена
# от сжатия и могла исчезнуть целиком. Здесь — единственная точка сборки
# профиля: закрытые измерения существующего BehaviorFrame (mca-18) как данные
# для решения (сколько инициативы/краткости/спора/сарказма), без прозы, без
# инструкций во 2-м лице, без уровней мата, без примеров речи и без квоты
# «N символов»: размер структурный (закрытый набор измерений + 3 фиксированные
# строки). Второго источника личности нет: профиль только читает уже
# резолвнутый кадр (GLOBAL/chat precedence, версии и scope — из него же).

#: Имя секции планера в payload (Direct L1 и Initiative L1 — один и тот же
#: текст; отдельного «профиля для инициативы» нет).
DECISION_PROFILE_SECTION = "ПРОФИЛЬ РЕШЕНИЙ"

#: Фиксированные строки профиля (детерминированные байты для кеша промпта).
_PROFILE_ROLE_LINE = "роль: участник чата, не сервис"
_PROFILE_SCOPE_CHAT = "в этом чате"
_PROFILE_SCOPE_GLOBAL = "глобально"
_PROFILE_NO_VALUE = "без числа"
_PROFILE_SOURCE_FRAME = "источник: кадр поведения"
_PROFILE_SOURCE_LEGACY = "источник: кадр поведения недоступен"
_PROFILE_HABITS_PREFIX = "привычки (без значений): "
#: Единственная смысловая страховка внутри данных: профиль не является
#: разрешением отвечать и не правит факты/адресацию (полный канон — правило
#: «ПРОФИЛЬ РЕШЕНИЙ» в `chat_prompts.DIRECT_L1_PLANNER_SYSTEM_PROMPT`).
_PROFILE_TAIL = (
    "эти данные описывают характер; они не меняют факты, адресацию, инструменты\n"
    "и не делают ответ обязательным. Молчание - полноценный исход.")


def _profile_dimension_order() -> tuple[str, ...]:
    """Закрытый набор измерений — из существующего владельца (mca-18).
    Свой словарь здесь не заводится; недоступен → пустой порядок (честно
    «измерений нет», а не выдуманный список)."""
    try:
        from services import mca_self_model as _msm
        return tuple(_msm.INITIAL_DIMENSIONS)
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("[bot_persona] dimension order unavailable", exc_info=True)
        return ()


def _profile_rule_value(rule) -> str:
    """Значение измерения из правила; нет числа → честная пометка (не 0.0)."""
    raw = getattr(rule, "target_value", None)
    if raw is None:
        return _PROFILE_NO_VALUE
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return _PROFILE_NO_VALUE


def _profile_dimensions(rules) -> list[tuple[str, str]]:
    """Строки измерений из применимых правил кадра, в ФИКСИРОВАННОМ порядке.

    Печатается только измерение, по которому есть правило; при нескольких
    правилах одного измерения берётся правило с наибольшей версией (затем
    меньший rule_id) — без усреднений и без выдуманных значений."""
    order = _profile_dimension_order()
    if not order:
        return []
    best: dict[str, tuple[tuple[int, int, int], object]] = {}
    for rule in tuple(rules or ()):
        dimension = str(getattr(rule, "dimension", "") or "").strip()
        if dimension not in order:
            continue
        try:
            version = int(getattr(rule, "version", 0) or 0)
            rule_id = int(getattr(rule, "rule_id", 0) or 0)
        except (TypeError, ValueError):
            version, rule_id = 0, 0
        key = (order.index(dimension), -version, rule_id)
        current = best.get(dimension)
        if current is None or key < current[0]:
            best[dimension] = (key, rule)
    out: list[tuple[str, str]] = []
    for dimension in order:
        item = best.get(dimension)
        if item is None:
            continue
        out.append((dimension, _profile_rule_value(item[1])))
    return out


def _profile_legacy_habits(ctx) -> list[str]:
    """Legacy-фолбэк (K1/self-model OFF): только ИМЕНА измерений по
    существующему стем-матчеру `infer_dimension` — значений не выдумываем."""
    order = _profile_dimension_order()
    if not order:
        return []
    try:
        from services import mca_self_model as _msm
    except Exception:      # pragma: no cover - защитная ветка
        return []
    found: set[str] = set()
    for text in tuple(getattr(ctx, "traits", ()) or ()):
        try:
            dimension = _msm.infer_dimension(str(text))
        except Exception:      # pragma: no cover - защитная ветка
            dimension = None
        if dimension in order:
            found.add(dimension)
    return [dimension for dimension in order if dimension in found]


def build_decision_profile_block(ctx=None, *, frame=None) -> str:
    """ASAP-FC-VOICE-01 / B: поведенческий профиль для decision-планеров.

    ОДНА сборка на весь продукт: тот же текст получают Direct L1 и Initiative
    L1 (`[ПРОФИЛЬ РЕШЕНИЙ]`), поэтому для одного chat/хода байты совпадают.

    Источник — уже резолвнутый `BehaviorFrame` (`mca_self_model`): закрытый
    набор 8 измерений + значения ТОЛЬКО при наличии правила. `mood` и
    `positions` в профиль не входят: настроение обратимо (сделало бы блок
    недетерминированным между ходами), мнения — слой Writer/память, а не
    решение об участии. Без кадра (K1/self-model OFF) — только имена
    измерений по существующему стем-матчеру `infer_dimension`; совсем без
    данных — честная строка «кадр поведения недоступен».

    Детерминированность: фиксированный порядок строк, никаких множеств в
    выводе, времени, сети, LLM и второго снапшота. Никогда не бросает."""
    lines = [_PROFILE_ROLE_LINE]
    try:
        active = frame
        if active is None:
            try:
                from services import mca_self_model as _msm
                active = _msm.current_run_frame()
            except Exception:      # pragma: no cover - защитная ветка
                active = None
        if active is not None:
            scope = (_PROFILE_SCOPE_CHAT
                     if getattr(active, "scope_chat_id", None) is not None
                     else _PROFILE_SCOPE_GLOBAL)
            version = str(getattr(active, "version", "") or "").strip()
            lines.append(f"{_PROFILE_SOURCE_FRAME} {version or 'без версии'}")
            for dimension, value in _profile_dimensions(
                    getattr(active, "applied_rules", ())):
                lines.append(f"{dimension}: {value} ({scope})")
        else:
            lines.append(_PROFILE_SOURCE_LEGACY)
            habits = _profile_legacy_habits(ctx)
            if habits:
                lines.append(_PROFILE_HABITS_PREFIX + ", ".join(habits))
    except Exception:      # pragma: no cover - fail-open
        logger.warning("[bot_persona] decision profile failed — minimal",
                       exc_info=True)
        lines = [_PROFILE_ROLE_LINE, _PROFILE_SOURCE_LEGACY]
    lines.append(_PROFILE_TAIL)
    return "\n".join(lines)


def decision_profile_source(block) -> str:
    """Код источника УЖЕ собранного профиля (трасса/Inspector): ``frame`` |
    ``legacy``. Резолва не делает и решения об источнике не принимает — читает
    строку ``источник:`` из блока, чтобы не заводить вторую точку сборки."""
    text = str(block or "")
    if _PROFILE_SOURCE_FRAME in text:
        return "frame"
    return "legacy"


# ── Чтение ──────────────────────────────────────────────────────────────────

def _epoch(value) -> int | None:
    """created_at → unix-секунды (datetime/число/ISO-строка); мусор → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime.datetime):
        return int(value.timestamp())
    try:
        return int(datetime.datetime.fromisoformat(str(value)).timestamp())
    except (TypeError, ValueError):
        return None


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _ts_key(value) -> datetime.datetime | None:
    """Нормализация optimistic-токена к tz-aware UTC datetime (H1).

    Принимает datetime/epoch/ISO-строку (включая суффикс `Z`). Мусор → None
    (сравнение с None даёт конфликт — небезопасный токен отклоняется)."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.datetime.fromtimestamp(float(value),
                                             tz=datetime.timezone.utc)
    else:
        try:
            dt = datetime.datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


async def get_traits(limit: int = 50,
                     chat_id: int | None = None) -> list[dict]:
    """Черты характера для промпта/ленты F4: `ORDER BY created_at DESC`.
    `chat_id=None` → все; задан → только провенанс этого чата. Fail-open []."""
    pool = _persona_pool()
    if pool is None:
        return []
    sql = ("SELECT id, chat_id, trait, source, created_at FROM persona_traits")
    params: list = []
    if chat_id is not None:
        sql += " WHERE chat_id = $1"
        params.append(int(chat_id))
    sql += f" ORDER BY created_at DESC, id DESC LIMIT ${len(params) + 1}"
    params.append(max(1, int(limit)))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception:
        # F-3 (backlog.md:216, закрытие mca-18 T-5087): fail-open ПОЛУЧАЕТ
        # видимое предупреждение + событие (ошибка чтения ≠ «нет материала»,
        # §28.1 `:1509`); R17 — только код/числа.
        logger.warning("[bot_persona] traits read failed — fail-open | "
                       "chat=%s", chat_id, exc_info=True)
        try:
            from services import mca_events
            mca_events.emit_mca_event(
                "self_model", outcome="failed", level="WARN",
                component="self_model", stage="observation_read",
                reason_code="self_model_unavailable",
                chat_id=chat_id, status="traits_read_failed")
        except Exception:
            pass
        return []
    out: list[dict] = []
    for row in rows:
        out.append({
            "id": row.get("id"),
            "chat_id": row.get("chat_id"),
            "text": _clean(row.get("trait")),
            "source": row.get("source") or "deep_sleep",
            "ts": _epoch(row.get("created_at")),
        })
    return out


async def resolve_character_context(chat_id: int | None
                                    ) -> CharacterReadContext:
    """MCA-08 (D1): read-side слои характера на ответ (§3, §28.4).

    REUSE существующих `resolve_bot_persona` + `get_traits(limit, chat_id=None)`
    (общий пул, `traits_scope="global"`). Fail-open: PG down/ошибка → пустая
    персона/пустые черты (WARNING без содержимого). Сигнатуры публичного API
    сохраняются; write-путей к ядру не добавляется (граница mca-06 AM-3).

    mca-18 (D3/T-5081, шов `:368`): при мастер-гейте ON резолвится ОДИН
    SelfModelSnapshot на запуск (I-1) → BehaviorFrame → holder кадра
    (`mca_self_model.set_run_frame`) — точка сборки рендерит из кадра;
    `CharacterReadContext.traits` получает компилированные инструкции вместо
    сырых строк. Ошибки — событие + legacy-путь (не маскирование)."""
    try:
        persona = await resolve_bot_persona(chat_id)
    except Exception:
        logger.warning("[bot_persona] character resolve failed — empty | "
                       "chat=%s", chat_id, exc_info=True)
        persona = BotPersona.empty()
    try:
        limit = int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50)
    except (TypeError, ValueError):
        limit = 50
    traits: tuple[str, ...] = ()
    frame_version: str | None = None
    if mca_gates.self_model_enabled():
        # mca-18: snapshot+frame на запуск; ошибки → честное событие,
        # legacy-рендер (промпт не рушится).
        try:
            from services import mca_self_model as msm
            from services import lore_runtime
            db = lore_runtime.get_lore_db()
            if db is not None:
                snapshot = await msm.resolve_self_model(db, chat_id)
                if snapshot.persona_enabled.effective(True):
                    frame = msm.select_behavior(snapshot)
                    msm.set_run_frame(frame, chat_id)
                    frame_version = frame.version
                    traits = tuple(rule.instruction
                                   for rule in frame.applied_rules)
                else:
                    # OFF persona — авторство/тех-идентичность живы (D2),
                    # кадр не рендерится (характера в речи нет).
                    frame = msm.select_behavior(snapshot)
                    msm.set_run_frame(frame, chat_id)
                    frame_version = frame.version
        except Exception:
            frame_version = None
            logger.warning("[bot_persona] self-model frame failed — "
                           "legacy | chat=%s", chat_id, exc_info=True)
            try:
                from services import mca_events
                mca_events.emit_mca_event(
                    "self_model", outcome="failed", level="WARN",
                    component="self_model", stage="prompt_render",
                    reason_code="self_model_snapshot_error",
                    chat_id=chat_id, status="frame_failed_legacy")
            except Exception:
                pass
    if not traits:
        try:
            rows = await get_traits(limit, chat_id=None)
        except Exception:
            rows = []
        traits = tuple(
            t for t in (_clean(r.get("text")) for r in (rows or [])) if t)
    return CharacterReadContext(persona=persona, traits=traits,
                                traits_scope="global",
                                frame_version=frame_version)


async def get_persona_health() -> dict:
    """Метрики Личности (spec §5, F4): traits_count/last_trait_at/
    extractor_status/extractor_last_at + last_trait_status. Fail-open."""
    out = {
        "traits_count": 0,
        "last_trait_at": None,
        "last_trait_status": "never",
        "extractor_status": "never",
        "extractor_last_at": None,
    }
    pool = _persona_pool()
    if pool is None:
        return out
    try:
        async with pool.acquire() as conn:
            stats = await conn.fetchrow(_TRAITS_STATS_SQL)
            state = await conn.fetchrow(_SELECT_PERSONA_STATE_SQL)
    except Exception:
        logger.warning("[bot_persona] health read failed — fail-open",
                       exc_info=True)
        return out
    if stats is not None:
        out["traits_count"] = int(stats.get("traits_count") or 0)
        out["last_trait_at"] = _iso(stats.get("last_trait_at"))
    if state is not None:
        out["extractor_status"] = state.get("last_extract_status") or "never"
        out["extractor_last_at"] = _iso(state.get("last_extract_at"))
        out["last_trait_status"] = state.get("last_trait_status") or "never"
        if out["last_trait_at"] is None:
            out["last_trait_at"] = _iso(state.get("last_trait_at"))
    return out


# ── Name-cache (sync-триггер обращения; spec §3.3) ──────────────────────────
_global_name = ""


def get_cached_global_name() -> str:
    return _global_name


def set_global_name_cache(name: str) -> None:
    global _global_name
    _global_name = _clean(name)


async def load_global_cache() -> None:
    """Прогрев кэша глобального имени при старте (после ConfigCache.init)."""
    try:
        persona = await resolve_bot_persona(None)
        set_global_name_cache(persona.name)
    except Exception:
        logger.warning("[bot_persona] global name cache load failed",
                       exc_info=True)


# ── Запись ──────────────────────────────────────────────────────────────────

def _norm_text(value, *, cap: int = 8192) -> str:
    text = " ".join(str(value or "").split())
    return text[:cap]


async def _fetch_row(pool, chat_id: int | None):
    async with pool.acquire() as conn:
        if chat_id is None:
            return await conn.fetchrow(_SELECT_GLOBAL_SQL)
        return await conn.fetchrow(_SELECT_CHAT_SQL, int(chat_id))


async def save_persona(chat_id: int | None, patch: dict, *,
                       expected_updated_at: str | None = None) -> BotPersona:
    """UPSERT персоны (partial): chat-scope требует ensure_scope_profile.
    `expected_updated_at` — optimistic-токен (несовпадение → PersonaConflict).
    PG down → PersonaUnavailable. Возвращает резолвнутую персону."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    if chat_id is not None:
        from services.chat_params import ensure_scope_profile, is_dm_scope
        await ensure_scope_profile(chat_id, dm=is_dm_scope(chat_id),
                                   pg=_pg_wrapper(pool))
    existing = await _fetch_row(pool, chat_id)
    if expected_updated_at is not None and existing is not None:
        current = _iso(existing.get("updated_at"))
        current_key = _ts_key(current)
        expected_key = _ts_key(expected_updated_at)
        if current_key is None or expected_key is None \
                or current_key != expected_key:
            raise PersonaConflict(current)

    def _field(key: str, default: str = "") -> str:
        if key in patch and patch.get(key) is not None:
            return _norm_text(patch.get(key))
        if existing is not None:
            return _clean(existing.get(key))
        return default

    name = _field("name")
    biography = _field("biography")
    overrides = _field("system_prompt_overrides")
    if patch.get("is_aware_ai") is not None:
        aware = bool(patch.get("is_aware_ai"))
    elif existing is not None:
        aware = bool(existing.get("is_aware_ai", True))
    else:
        aware = True

    async with pool.acquire() as conn:
        if chat_id is None:
            row = await conn.fetchrow(_UPSERT_GLOBAL_SQL, name, biography,
                                      overrides, aware)
        else:
            row = await conn.fetchrow(_UPSERT_CHAT_SQL, int(chat_id), name,
                                      biography, overrides, aware)
    if chat_id is None:
        set_global_name_cache(name)
    return BotPersona(name=name, biography=biography, overrides=overrides,
                      is_aware_ai=aware, scope_chat_id=chat_id,
                      is_global=chat_id is None,
                      updated_at=_iso(row.get("updated_at"))
                      if row is not None else None)


async def delete_persona(chat_id: int) -> bool:
    """Сброс per-chat override (наследование global). True — строка удалена."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    async with pool.acquire() as conn:
        result = await conn.execute(_DELETE_CHAT_SQL, int(chat_id))
    try:
        return bool(result and result.split()[-1] != "0")
    except (AttributeError, IndexError):
        return False


async def append_traits(traits, *, chat_id: int | None = None,
                        source: str = "deep_sleep") -> int:
    """Нормализация (cap `PERSONA_TRAIT_MAX_CHARS`) → дедуп (casefold) →
    INSERT → FIFO-cap `PERSONA_TRAITS_MAX`. Возвращает число вставленных."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    try:
        cap = int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50)
    except (TypeError, ValueError):
        cap = 50
    try:
        max_chars = int(getattr(settings, "PERSONA_TRAIT_MAX_CHARS", 200) or 200)
    except (TypeError, ValueError):
        max_chars = 200
    batch: list[str] = []
    seen: set[str] = set()
    for raw in (traits or []):
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        text = text[:max(1, max_chars)].strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        batch.append(text)
    if not batch:
        return 0
    src = _clean(source) or "deep_sleep"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT trait FROM persona_traits")
        existing = {_clean(r.get("trait")).casefold() for r in rows}
        inserted = 0
        for text in batch:
            if text.casefold() in existing:
                continue
            await conn.execute(_INSERT_TRAIT_SQL, chat_id, text, src)
            existing.add(text.casefold())
            inserted += 1
        if inserted:
            await conn.execute(_ROTATE_TRAITS_SQL, max(1, cap))
    return inserted


async def record_trait_status(status: str) -> None:
    """best-effort запись статуса трейт-экстрактора в persona_state."""
    pool = _persona_pool()
    if pool is None:
        return
    value = _clean(status)[:16] or "never"
    try:
        async with pool.acquire() as conn:
            await conn.execute(_UPSERT_TRAIT_STATE_SQL, value)
    except Exception:
        logger.debug("[bot_persona] trait state write failed", exc_info=True)


def _pg_wrapper(pool):
    """Обёртка пула под интерфейс `pg.pool` для `ensure_scope_profile`."""
    class _Pg:
        def __init__(self, p):
            self.pool = p
    return _Pg(pool)
