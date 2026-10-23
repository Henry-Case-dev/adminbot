"""Epic 24 — alias resolution (R7/D61, Section 33.6).

ASAP 3 Corrective (§4–§6): единый владелец порядка имён и merge алиасов
global/chat **по каждому Telegram ID**.

Каскад (единственный для всех речевых маршрутов):
    1) chat alias этого user_id
    2) global alias этого user_id
    3) Telegram nickname (first+last)
    4) username без '@'
    5) достоверное имя из памяти (ТОЛЬКО если caller привязал его к тому же
       user_id; по текстовому сходству не угадываем)
    6) user_id

Merge: `parse_alias_map` + `merge_alias_maps(global, chat)`. Отсутствие ключа
в чатовом словаре = наследование глобального; пустое значение отбрасывается
(пустая строка не переименовывает и не подавляет глобальный алиас).
Чатовое значение перекрывает только свой user_id.

Live-apply: резолвер собирается заново в начале хода/апдейта
(`build_alias_resolver(chat_id)` + `bind_turn_aliases`), а `LiveAliasView`
делегирует `resolve`/`canon_name` действующему резолверу текущего asyncio-
контекста. Стартовый снапшот остаётся только fallback'ом для путей без
chat_id. Инвалидация — существующая: `set_chat_params` чистит кэш,
`ConfigCache` обновляется при сохранении.
"""
import contextvars
import json
import logging

logger = logging.getLogger(__name__)

ALIASES_KEY = "limits.summary_aliases"


# ── Парсинг / merge словарей ────────────────────────────────────────────────

def _coerce_alias_payload(raw) -> tuple[dict[str, str], dict]:
    """(map, meta) из JSON-строки/dict (в т.ч. двойное кодирование).

    Ключи — Telegram user_id (нормализуются к str(int)); значения — имена.
    Пустые/None/нечисловые ключи отбрасываются: они не переименовывают.
    """
    meta = {"valid": True, "encoded": isinstance(raw, str),
            "raw_keys": 0, "dropped": 0, "reason": ""}
    if raw is None or raw == "" or raw == {}:
        return {}, meta
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            meta["valid"] = False
            meta["reason"] = "invalid_json"
            return {}, meta
        # Двойное кодирование (исторический баг KV-редактора): строка в
        # строке → объект.
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                meta["valid"] = False
                meta["reason"] = "invalid_json"
                return {}, meta
    if not isinstance(data, dict):
        meta["valid"] = False
        meta["reason"] = "not_object"
        return {}, meta
    out: dict[str, str] = {}
    for key, value in data.items():
        meta["raw_keys"] += 1
        try:
            uid = str(int(str(key).strip()))
        except (TypeError, ValueError):
            meta["dropped"] += 1
            continue
        if value is None:
            meta["dropped"] += 1
            continue
        name = str(value).strip().lstrip("@").strip()
        if not name:
            meta["dropped"] += 1
            continue
        out[uid] = name
    return out, meta


def parse_alias_map(raw) -> dict[str, str]:
    """JSON/dict → {user_id: имя}; пустые значения не переименовывают."""
    return _coerce_alias_payload(raw)[0]


def merge_alias_maps(global_raw, chat_raw) -> dict[str, str]:
    """Merge по каждому user_id: global, затем chat перекрывает свой id."""
    merged = dict(parse_alias_map(global_raw))
    merged.update(parse_alias_map(chat_raw))
    return merged


class AliasResolver:
    """Resolves participant display names for speech routes."""

    def __init__(self, raw_json, *, scope_report: dict | None = None):
        """Принимает строку JSON (env) или dict (hot.get-кэш: json-тип
        каталога коэрсится в dict) — оба варианта заводятся без ошибок."""
        data, meta = _coerce_alias_payload(raw_json)
        if not meta["valid"]:
            if meta.get("reason") == "not_object":
                logger.warning(
                    "SUMMARY_ALIASES is not a JSON object — aliases disabled")
            else:
                logger.warning(
                    "SUMMARY_ALIASES invalid JSON — aliases disabled: %r",
                    raw_json)
        self._aliases: dict[str, str] = data
        # Обратная карта строится ТОЛЬКО по уникальным display-именам: если
        # два разных user_id имеют одинаковое имя, канон по строке не
        # выбирается (нельзя сливать личности по совпадению текста).
        by_name: dict[str, str] = {}
        ambiguous: set[str] = set()
        for value in self._aliases.values():
            key = value.casefold()
            if key in by_name and by_name[key] != value:
                ambiguous.add(key)
            by_name.setdefault(key, value)
        for key in ambiguous:
            by_name.pop(key, None)
        self._by_name: dict[str, str] = by_name
        self._cache: dict[tuple, str] = {}
        self.scope_report: dict = dict(scope_report or {
            "ok": True,
            "scope": "inline",
            "global": len(self._aliases),
            "chat": 0,
            "inherited": 0,
            "merged": len(self._aliases),
            "invalid_json": [],
        })

    @property
    def aliases(self) -> dict[str, str]:
        """Копия действующей карты (для диагностики/тестов)."""
        return dict(self._aliases)

    def canon_name(self, name: str, user_id=None) -> str:
        """Имя → канон-алиас (обратная карта) или действующий алиас по uid.

        * известный user_id → его действующий алиас (даже если передано
          старое/историческое имя);
        * иначе — уникальное совпадение с алиасом (регистронезависимо);
        * иначе — имя как есть.
        """
        text = str(name or "").strip()
        if user_id is not None:
            try:
                alias = self._aliases.get(str(int(user_id)))
            except (TypeError, ValueError):
                alias = None
            if alias:
                return alias
        return self._by_name.get(text.casefold(), text)

    def resolve(
        self,
        user_id: int,
        nickname: str | None = None,
        username: str | None = None,
        memory_name: str | None = None,
    ) -> str:
        """Единый каскад: alias → nickname → username → memory_name → id.

        ``memory_name`` принимается только как уже проверенная привязка к
        ЭТОМУ user_id (ростер/`subject_ref_id`); резолвер сам по текстовому
        сходству ничего не ищет. '@' снимается со всех уровней.
        """
        key = (int(user_id), nickname, username)
        if memory_name is not None:
            key = key + (memory_name,)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        name = ""
        alias = self._aliases.get(str(int(user_id)))
        if alias:
            name = str(alias).strip()
        elif isinstance(nickname, str) and nickname.strip():
            name = nickname.strip()
        elif isinstance(username, str) and username.strip():
            name = username.lstrip("@").strip()
        elif isinstance(memory_name, str) and memory_name.strip():
            name = memory_name.strip()

        if not name:
            name = str(user_id)
        name = name.lstrip("@").strip()  # guarantee: no @ on any branch
        self._cache[key] = name
        return name


class LiveAliasView:
    """Стабильный DI-объект: делегирует действующему резолверу хода/апдейта.

    Handlers/сервисы получают один экземпляр на старте, но `.resolve()` и
    `.canon_name()` читают резолвер, привязанный к текущему asyncio-контексту
    (`bind_turn_aliases`). Это даёт live-apply без рестарта и изоляцию
    параллельных чатов: contextvars копируются в каждую задачу отдельно.
    """

    def __init__(self, fallback: AliasResolver | None = None) -> None:
        self._fallback = fallback

    def _current(self) -> AliasResolver | None:
        return current_alias_resolver(self._fallback)

    def resolve(self, *args, **kwargs) -> str:
        resolver = self._current()
        if resolver is None:
            uid = args[0] if args else kwargs.get("user_id")
            return str(uid)
        return resolver.resolve(*args, **kwargs)

    def canon_name(self, *args, **kwargs) -> str:
        resolver = self._current()
        if resolver is None:
            return str(args[0] if args else kwargs.get("name") or "")
        return resolver.canon_name(*args, **kwargs)

    def __getattr__(self, name):
        # `_aliases`/`scope_report`/`_by_name` для существующих потребителей
        # (tool_router). Неизвестный атрибут — честная ошибка fallback'а.
        return getattr(self._current(), name)


# ── Действующий резолвер хода (contextvars) ─────────────────────────────────

_TURN_ALIAS: contextvars.ContextVar = contextvars.ContextVar(
    "asap3_turn_alias_resolver", default=None)


def current_alias_resolver(fallback: AliasResolver | None = None
                           ) -> AliasResolver | None:
    """Резолвер текущего asyncio-контекста либо ``fallback``."""
    return _TURN_ALIAS.get() or fallback


def set_turn_alias_resolver(resolver: AliasResolver | None) -> None:
    _TURN_ALIAS.set(resolver)


def reset_turn_alias_resolver() -> None:
    """Тест/служебный сброс (новая задача всё равно стартует с default)."""
    _TURN_ALIAS.set(None)


async def bind_turn_aliases(chat_id: int) -> AliasResolver:
    """Собрать per-chat резолвер и привязать его к текущему контексту.

    Fail-open: ошибка сборки не бросается наружу (build уже fail-open);
    вызывающий может дополнительно залогировать. Возвращает резолвер.
    """
    resolver = await build_alias_resolver(chat_id)
    set_turn_alias_resolver(resolver)
    return resolver


async def alias_scope_middleware(handler, event, data):
    """aiogram outer-middleware: live-резолвер на каждый update.

    Thin/fail-open: не меняет handler-цепочку и не рвёт hot-path, если
    конфигурация недоступна (тогда остаётся fallback стартового снапшота).
    """
    try:
        chat_id = _update_chat_id(event)
        if chat_id is not None:
            await bind_turn_aliases(int(chat_id))
    except Exception:
        logger.warning(
            "alias scope middleware failed — fallback resolver | update=%s",
            type(event).__name__, exc_info=True)
    return await handler(event, data)


def _update_chat_id(update) -> int | None:
    """chat_id первого message-like поля Update (message/callback и т.п.)."""
    try:
        for attr in ("message", "edited_message", "channel_post",
                     "edited_channel_post"):
            msg = getattr(update, attr, None)
            if msg is not None:
                return getattr(getattr(msg, "chat", None), "id", None)
        cq = getattr(update, "callback_query", None)
        if cq is not None:
            chat_id = getattr(getattr(cq, "message", None), "chat", None)
            return getattr(chat_id, "id", None)
    except Exception:
        return None
    return None


# ── Сборка per-chat резолвера (merge global + chat) ─────────────────────────

async def _read_chat_alias_layer(chat_id: int) -> tuple[object, bool]:
    """(raw override | None, layer_ok) — БЕЗ global-подстановки и каста.

    `layer_ok=False` ⇔ chat-слой существует, но не читается (A15: нельзя
    выдавать неизвестное значение за действующее без диагностики).
    Отсутствие кэша/профиля — это не сбой слоя: (None, True).
    """
    try:
        from services import chat_params
        cache = chat_params.get_chat_params_cache()
        if cache is None:
            return None, True
        checked = getattr(cache, "get_chat_params_checked", None)
        if checked is not None:
            root, ok = await checked(chat_id)
        else:
            root = await cache.get_chat_params(chat_id)
            ok = True
        return (root.get("overrides") or {}).get(ALIASES_KEY), bool(ok)
    except Exception:
        logger.warning(
            "alias resolver chat layer failed — global fallback | chat=%s",
            chat_id, exc_info=True)
        return None, False


async def build_alias_resolver(chat_id: int) -> AliasResolver:
    """Per-chat резолвер: global aliases + chat override по каждому user_id.

    Сигнатура сохранена (7 существующих вызовов). Fail-open, но честно
    помечает `scope_report.ok=false`, если слой конфигурации не прочитан.
    """
    from services import hot_config as hot
    from config.settings import settings

    report = {
        "ok": True,
        "scope": "global",
        "chat_id": int(chat_id),
        "global": 0,
        "chat": 0,
        "inherited": 0,
        "merged": 0,
        "invalid_json": [],
    }
    try:
        global_raw = hot.get(ALIASES_KEY, settings.SUMMARY_ALIASES)
    except Exception:
        logger.warning(
            "alias resolver global read failed — factory fallback | chat=%s",
            chat_id, exc_info=True)
        global_raw = settings.SUMMARY_ALIASES
        report["ok"] = False
        report["invalid_json"].append("global_unavailable")

    chat_raw, chat_ok = await _read_chat_alias_layer(chat_id)
    if not chat_ok:
        report["ok"] = False
        report["invalid_json"].append("chat_unavailable")

    gmap, gmeta = _coerce_alias_payload(global_raw)
    cmap, cmeta = _coerce_alias_payload(chat_raw)
    if not gmeta["valid"]:
        report["ok"] = False
        report["invalid_json"].append("global_invalid_json")
    if not cmeta["valid"]:
        report["ok"] = False
        report["invalid_json"].append("chat_invalid_json")

    merged = dict(gmap)
    inherited = sum(1 for uid in gmap if uid not in cmap)
    merged.update(cmap)
    if cmap and gmap:
        report["scope"] = "merged"
    elif cmap:
        report["scope"] = "chat"
    else:
        report["scope"] = "global"
    report["global"] = len(gmap)
    report["chat"] = len(cmap)
    report["inherited"] = inherited
    report["merged"] = len(merged)
    report["dropped"] = gmeta["dropped"] + cmeta["dropped"]
    resolver = AliasResolver(merged, scope_report=report)
    if not report["ok"]:
        logger.warning(
            "alias resolver degraded | chat=%s | scope=%s | ok=%s | "
            "invalid=%s — используется доступный слой",
            chat_id, report["scope"], report["ok"],
            ",".join(report["invalid_json"]))
    return resolver
