# -*- coding: utf-8 -*-
"""P0IM-S6-FRESH (§126/§128): effective-слой, пояс чата и scope одного ответа.

Срез отвечает на три вопроса владельца, и здесь каждый проверяется на РЕАЛЬНЫХ
объектах сервиса (та же БД, те же резолверы, что у боевого пути):

1. **EFFECTIVE** (`P0IM-S6-EFFECTIVE`) — что реально решает сейчас и из какого
   слоя: сохранённый override чата / общая настройка / заводское значение.
   Заводское значение, выданное за «общую настройку», — дефект: это разные
   ответы на вопрос «кто это решил».
2. **TIME** (`P0IM-S6-TZ`) — время подписывается поясом ВЫБРАННОГО чата, пояс и
   его слой называет backend. Пояс чата не задан → «пояс чата не задан» +
   названный заводской пояс, а не часы сервера. Сбой чтения → «неизвестно»
   (`name=null`), а не правдоподобный дефолт.
3. **SCOPE** (`P0IM-S6-SCOPE`) — payload относится к тому чату, который
   спросили, а штамп свежести — серверный (`time.generated_at` = момент
   сборки), а не вычисленный клиентом.

Плюс `P0IM-S6-EXPIRED`: просроченный маркер и просроченная бронь не выглядят
актуальным ожиданием.

TEST-LIFECYCLE: CONTRACT owner=P0-INIT-MEME-UX-DIAG S6-FRESH
"""
from __future__ import annotations

import asyncio

from types import SimpleNamespace

from services import chat_params as params
from services import hot_config as hot
from services import initiative_diagnostics as diag
from services import initiative_observer as obs
from services import meme_initiative as meme
from services.database import DatabaseService

CHAT = -100777
OTHER_CHAT = -100778
NOW_TS = 1800000300          # 2027-01-15T08:45:00Z (зимнее время)


# ── стенд ───────────────────────────────────────────────────────────────────

async def _db(tmp_path, name="s6.db") -> DatabaseService:
    svc = DatabaseService(str(tmp_path / name))
    await svc.initialize()
    return svc


async def _schema(svc) -> None:
    meme.SqliteQuotaLedger(str(svc.db_path)).apply_schema()


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _settings_loader(monkeypatch, cfg):
    """`load_settings` отдаёт заданный снимок: сервис читает его сам."""
    async def _load(_chat_id=None, _cfg=cfg):
        return _cfg

    monkeypatch.setattr(meme, "load_settings", _load)


def _chat_state(monkeypatch, *, source: str, runtime: bool = True,
                reason_code: str = ""):
    """Тумблер инициативы чата с ЯВНО заданным слоем резолвера."""
    async def _state(_chat_id, **_kwargs):
        return SimpleNamespace(source=source, effective_runtime=runtime,
                               reason_code=reason_code)

    monkeypatch.setattr(obs, "chat_capability_state", _state)


def _global_gates(monkeypatch):
    """Продуктовый тумблер и наблюдатель включены — шум вне предмета."""
    monkeypatch.setattr(obs, "observer_enabled", lambda: True)

    async def _chat_on(_chat_id):
        return True

    monkeypatch.setattr(obs, "chat_observer_enabled", _chat_on)


def _image_ok(monkeypatch):
    async def _image(_chat_id, health=None):
        return {"available": True, "reason": "ok", "module_enabled": True}

    monkeypatch.setattr(meme, "image_dependency", _image)


def _layers_of(block: dict) -> dict:
    """`configuration.layers` → {gate: layer} (проверка принадлежности слоя)."""
    out = {}
    for row in ((block.get("configuration") or {}).get("layers") or []):
        if isinstance(row, dict):
            out[str(row.get("gate") or "")] = str(row.get("layer") or "")
    return out


def _sourced_params(monkeypatch, value: bool, layer: str):
    """Резолвер настройки мема отвечает заданной парой (значение, слой)."""
    async def _resolver(_chat_id, _key, _default=None):
        return value, layer

    monkeypatch.setattr(params, "get_chat_param_sourced", _resolver)


def _params_raise(monkeypatch):
    async def _resolver(*_args, **_kwargs):
        raise RuntimeError("chat_params недоступен")

    monkeypatch.setattr(params, "get_chat_param_sourced", _resolver)


def _override(monkeypatch, value, found: bool):
    monkeypatch.setattr(params, "read_override_sync",
                        lambda *_a, **_k: (value, found))


def _override_raise(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("профиль чата недоступен")

    monkeypatch.setattr(params, "read_override_sync", _boom)


def _global_timezone(monkeypatch, value):
    real_get = hot.get

    def _get(key, default=None):
        if str(key) == "limits.chat_timezone":
            return value
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", _get)


# ═══ 1. EFFECTIVE: слой каждого гейта ═══════════════════════════════════════

def test_configuration_layers_name_the_real_layer(tmp_path, monkeypatch):
    """Заводское значение ≠ общая настройка ≠ override чата.

    Три прогона на одной и той же БД отличаются ТОЛЬКО слоем резолвера: так
    видно, что `layers` сообщает решение слоя, а не пересказывает агрегат.
    """
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _settings_loader(monkeypatch, _settings(enabled=True))

    cases = []

    async def scenario():
        svc = await _db(tmp_path)
        try:
            await _schema(svc)
            # заводское значение тумблера чата
            _chat_state(monkeypatch, source="default", runtime=True)
            _sourced_params(monkeypatch, True, "factory")
            factory = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            # общая настройка
            _chat_state(monkeypatch, source="global", runtime=True)
            _sourced_params(monkeypatch, True, "global")
            glob = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            # сохранённый override чата
            _chat_state(monkeypatch, source="chat", runtime=True)
            _sourced_params(monkeypatch, True, "chat")
            saved = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return factory, glob, saved
        finally:
            await svc.close()

    factory, glob, saved = asyncio.run(scenario())

    f_layers = _layers_of(factory["meme"])
    g_layers = _layers_of(glob["meme"])
    s_layers = _layers_of(saved["meme"])

    # Тумблер чата: заводское значение названо заводским, а не «global».
    assert f_layers.get("chat_toggle") == diag.LAYER_FACTORY
    assert g_layers.get("chat_toggle") == diag.LAYER_GLOBAL
    assert s_layers.get("chat_toggle") == diag.LAYER_CHAT
    # Настройки мема: тот же принцип для второго гейта.
    assert f_layers.get("meme_settings") == diag.LAYER_FACTORY
    assert g_layers.get("meme_settings") == diag.LAYER_GLOBAL
    assert s_layers.get("meme_settings") == diag.LAYER_CHAT
    # Глобальные гейты честно остаются глобальными во всех трёх прогонах.
    for layers in (f_layers, g_layers, s_layers):
        assert layers.get("module_gate") == diag.LAYER_GLOBAL
        assert layers.get("observer") == diag.LAYER_GLOBAL
    # Агрегат не переписан: прежняя интерпретация статуса сохранена.
    assert factory["meme"]["configuration"]["enabled"] is True
    assert factory["meme"]["configuration"]["source"] == "meme_settings"
    assert saved["meme"]["configuration"]["source"] == "chat"
    # Все объявленные поля слоя на месте — витрина не досочиняет подписи.
    for block in (factory["meme"], factory["text_initiative"]):
        rows = block["configuration"]["layers"]
        assert rows, "слои решения не отданы"
        for row in rows:
            assert set(row) == set(diag.CONFIGURATION_LAYER_FIELDS)


def test_unreadable_config_is_unknown_not_a_default(tmp_path, monkeypatch):
    """Сбой чтения настройки → «неизвестно», а не выключено/включено."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    # Пайплайн получил fail-open дефолт (enabled=False), но слой не читается.
    _settings_loader(monkeypatch, _settings(enabled=False))
    _params_raise(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="s6_unknown.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    payload = asyncio.run(scenario())
    configuration = payload["meme"]["configuration"]
    assert configuration["enabled"] is None, (
        "нечитаемая настройка выдана за конкретное значение: %r"
        % (configuration["enabled"],))
    assert configuration["source"] == diag.SOURCE_READ_FAILED
    assert configuration["reason"] == diag.NO_DATA_READ_FAILED
    layers = _layers_of(payload["meme"])
    assert layers.get("meme_settings") == diag.LAYER_READ_FAILED
    # Нечитаемый гейт не превращает механизм в «выключенный».
    assert payload["meme"]["readiness"]["state"] != diag.READINESS_BLOCKED


def test_unreadable_chat_gate_is_unknown_not_global(tmp_path, monkeypatch):
    """Сбой чтения тумблера чата — «слой не прочитан», а не «общий слой»."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "chat")

    async def _boom(_chat_id, **_kwargs):
        raise RuntimeError("capability недоступен")

    monkeypatch.setattr(obs, "chat_capability_state", _boom)

    async def scenario():
        svc = await _db(tmp_path, name="s6_gate_fail.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    payload = asyncio.run(scenario())
    assert _layers_of(payload["meme"]).get("chat_toggle") == \
        diag.LAYER_READ_FAILED
    assert payload["meme"]["configuration"]["enabled"] is None


# ═══ 2. TIME: пояс чата с названным источником ══════════════════════════════

def test_time_block_names_chat_timezone_and_its_layer(tmp_path, monkeypatch):
    """Пояс чата из backend: имя, источник и смещение на момент снимка."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, None)
    _override(monkeypatch, "Europe/Moscow", True)

    async def scenario():
        svc = await _db(tmp_path, name="s6_tz_chat.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    payload = asyncio.run(scenario())
    block = payload["time"]
    assert set(block) == set(diag.TIME_FIELDS)
    tz = block["timezone"]
    assert set(tz) == set(diag.TIMEZONE_FIELDS)
    assert tz["name"] == "Europe/Moscow"
    assert tz["source"] == diag.TZ_SOURCE_CHAT
    assert tz["offset_seconds"] == 3 * 3600
    assert tz["default_name"] == "UTC"
    assert tz["reason"] == ""
    # Один эффективный пояс: тот же, по которому боевой путь считает сутки.
    import datetime as _dt
    stamp = _dt.datetime.fromtimestamp(NOW_TS, _dt.timezone.utc)
    assert tz["name"] == meme.day_window(CHAT, stamp).timezone_name


def test_missing_chat_timezone_falls_back_to_named_default(tmp_path,
                                                          monkeypatch):
    """Пояс не задан ни на одном слое → названный заводской пояс, не сервер."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, "")
    _override(monkeypatch, None, False)

    async def scenario():
        svc = await _db(tmp_path, name="s6_tz_none.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    tz = asyncio.run(scenario())["time"]["timezone"]
    assert tz["name"] == diag.TZ_DEFAULT_NAME
    assert tz["source"] == diag.TZ_SOURCE_FALLBACK
    assert tz["default_name"] == diag.TZ_DEFAULT_NAME
    assert tz["offset_seconds"] == 0


def test_unreadable_timezone_is_unknown_not_utc(tmp_path, monkeypatch):
    """Сбой чтения пояса: `name=null` с причиной, а не подставленный UTC."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, "")
    _override_raise(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="s6_tz_fail.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    tz = asyncio.run(scenario())["time"]["timezone"]
    assert tz["name"] is None, "неизвестный пояс выдан за конкретный"
    assert tz["source"] == diag.SOURCE_READ_FAILED
    assert tz["offset_seconds"] is None
    assert tz["reason"] == "timezone_read_failed"


def test_timezone_offset_follows_the_instant(tmp_path, monkeypatch):
    """Смещение считается на момент снимка (лето/зима), а не берётся из имени."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, None)
    _override(monkeypatch, "Europe/Berlin", True)

    async def scenario():
        svc = await _db(tmp_path, name="s6_tz_dst.db")
        try:
            await _schema(svc)
            winter = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=1768470300)      # 2026-01-15T08:25:00Z
            summer = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=1784190300)      # 2026-07-16T08:25:00Z
            return winter["time"]["timezone"], summer["time"]["timezone"]
        finally:
            await svc.close()

    winter, summer = asyncio.run(scenario())
    assert winter["name"] == summer["name"] == "Europe/Berlin"
    assert winter["offset_seconds"] == 3600
    assert summer["offset_seconds"] == 7200


# ═══ 3. SCOPE: ответ ровно про запрошенный чат, штамп — серверный ═══════════

def test_payload_is_scoped_to_the_requested_chat(tmp_path, monkeypatch):
    """Два чата: каждый ответ подписан своим chat_id, поясом и штампом."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, None)

    zones = {CHAT: "Europe/Moscow", OTHER_CHAT: "Asia/Tokyo"}

    def _read_override(chat_id, _key):
        return zones.get(int(chat_id)), True

    monkeypatch.setattr(params, "read_override_sync", _read_override)

    async def scenario():
        svc = await _db(tmp_path, name="s6_scope.db")
        try:
            await _schema(svc)
            first = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            second = await diag.collect_mechanism_diagnostics(
                svc, OTHER_CHAT, now=NOW_TS + 30)
            return first, second
        finally:
            await svc.close()

    first, second = asyncio.run(scenario())
    assert first["chat_id"] == CHAT
    assert second["chat_id"] == OTHER_CHAT
    # Пояс не «перетекает» между чатами: у каждого свой, и он назван.
    assert first["time"]["timezone"]["name"] == "Europe/Moscow"
    assert second["time"]["timezone"]["name"] == "Asia/Tokyo"
    assert first["time"]["timezone"]["source"] == diag.TZ_SOURCE_CHAT
    # Штамп свежести — момент сборки ответа на сервере, а не клиентский.
    assert first["time"]["basis"] == "server_snapshot"
    assert first["time"]["generated_at"] == first["generated_at"] == NOW_TS
    assert second["time"]["generated_at"] == second["generated_at"] == \
        NOW_TS + 30
    # Каждый блок остаётся блоком своего механизма: склейки нет.
    assert first["meme"]["mechanism"] == "meme"
    assert first["text_initiative"]["mechanism"] == "text_initiative"


def test_stale_response_for_another_chat_is_not_applicable(tmp_path,
                                                           monkeypatch):
    """Ответ описывает СВОЙ чат: этим он и отбрасывается клиентом.

    Сервер не имеет права вернуть чужой `chat_id` (иначе guard на клиенте
    бессмысленен), поэтому контракт проверяется на двух подряд ответах: у
    каждого `chat_id` равен запрошенному, а `time` относится к тому же чату.
    """
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, "Europe/Moscow")   # общий пояс = A
    _override(monkeypatch, None, False)              # в чате B своего нет

    async def scenario():
        svc = await _db(tmp_path, name="s6_stale.db")
        try:
            await _schema(svc)
            own = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            other = await diag.collect_mechanism_diagnostics(
                svc, OTHER_CHAT, now=NOW_TS)
            return own, other
        finally:
            await svc.close()

    own, other = asyncio.run(scenario())
    assert own["chat_id"] != other["chat_id"]
    # Поздний ответ второго чата нельзя применить к первому: подписи разные.
    assert own["time"]["timezone"]["name"] == "Europe/Moscow"
    assert other["time"]["timezone"]["source"] == diag.TZ_SOURCE_GLOBAL
    for payload, expected in ((own, CHAT), (other, OTHER_CHAT)):
        assert payload["chat_id"] == expected
        assert payload["time"]["generated_at"] == NOW_TS


# ═══ 4. EXPIRED: просроченное не выглядит актуальным ожиданием ═════════════

def test_expired_marker_and_claim_are_not_actual_waiting(tmp_path,
                                                         monkeypatch):
    """Истёкший маркер `/meme` и просроченная бронь — не текущий блок."""
    _image_ok(monkeypatch)
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, "Europe/Moscow")
    _override(monkeypatch, None, False)

    stale_marker = {
        "ok": False, "reason": "manual_priority", "coordination": "ok",
        "holder_kind": "meme_initiative", "holder": "text_initiative",
        "detail": "manual_priority", "state": "claimed",
        "manual_priority_until": NOW_TS - 120,   # уже прошёл
        "checked_at": NOW_TS,
        "expires_at": NOW_TS - 60,               # бронь просрочена
    }
    live_marker = dict(stale_marker, manual_priority_until=NOW_TS + 120,
                       expires_at=NOW_TS + 60)

    async def scenario():
        svc = await _db(tmp_path, name="s6_expired.db")
        try:
            await _schema(svc)
            expired = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS, publication=dict(stale_marker))
            live = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS, publication=dict(live_marker))
            return expired, live
        finally:
            await svc.close()

    expired, live = asyncio.run(scenario())
    pub = expired["meme"]["publication"]
    assert pub["manual_priority_expired"] is True
    assert pub["manual_priority_active"] is False
    # Просроченная бронь не делает механизм «занятым».
    assert expired["meme"]["readiness"]["state"] != diag.READINESS_BUSY
    # Живой маркер, наоборот, остаётся ожиданием с ДОКАЗАННЫМ основанием.
    assert live["meme"]["publication"]["manual_priority_active"] is True
    readiness = live["meme"]["readiness"]
    if readiness["state"] == diag.READINESS_WAITING:
        assert readiness["next_basis"] in ("manual_priority_until",
                                           "cross_type_interval")
    # В обоих случаях сырой дедлайн остаётся в payload — его печатает витрина,
    # но состояние «активен/истёк» считает сервер, а не часы браузера.
    assert pub["manual_priority_until"] == NOW_TS - 120


# ═══ 5. P0IM-S6-EFFECTIVE: image-модуль всегда, heartbeat и провайдер ══════

def _image_off(monkeypatch):
    async def _image(_chat_id, health=None):
        return {"available": False, "reason": meme.SKIP_IMAGE_MODULE_OFF,
                "module_enabled": False, "configured": False,
                "health": "unknown"}

    monkeypatch.setattr(meme, "image_dependency", _image)


def test_image_module_gate_is_named_even_when_enabled(tmp_path, monkeypatch):
    """§P0IM-S6-EFFECTIVE: гейт `image_module` есть ВСЕГДА, а не только при OFF."""
    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="s6_image_on.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    payload = asyncio.run(scenario())
    layers = _layers_of(payload["meme"])
    assert "image_module" in layers, layers
    assert layers["image_module"] == diag.LAYER_GLOBAL, layers
    gate = next(row for row in payload["meme"]["configuration"]["layers"]
                if row["gate"] == "image_module")
    assert gate["enabled"] is True, gate
    assert gate["reason"] == "", gate
    # Выключенный модуль — тот же гейт, но с причиной конфигурации.
    _image_off(monkeypatch)

    async def scenario_off():
        svc = await _db(tmp_path, name="s6_image_off.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    off = asyncio.run(scenario_off())
    off_gate = next(row for row in off["meme"]["configuration"]["layers"]
                    if row["gate"] == "image_module")
    assert off_gate["enabled"] is False, off_gate
    assert off_gate["reason"] == "image_module_off", off_gate
    assert off["meme"]["configuration"]["enabled"] is False, off


def test_overview_projects_heartbeat_and_image_provider_for_both_chats(
        tmp_path, monkeypatch):
    """§P0IM-S6-EFFECTIVE: heartbeat_ok и доступность провайдера — в payload."""
    import time as _time

    from services import memory_maintenance as mm

    _global_gates(monkeypatch)
    _chat_state(monkeypatch, source="global", runtime=True)
    _settings_loader(monkeypatch, _settings(enabled=True))
    _sourced_params(monkeypatch, True, "global")
    _global_timezone(monkeypatch, None)
    _override(monkeypatch, None, False)

    async def _image(_chat_id, health=None):
        return {"available": True, "reason": "ok", "module_enabled": True,
                "configured": True, "health": "healthy", "model": "img-x"}

    monkeypatch.setattr(meme, "image_dependency", _image)
    monkeypatch.setattr(
        mm, "_initiative_observer_last_tick",
        {"ts": int(_time.time()), "status": "ok"}, raising=False)

    async def scenario():
        svc = await _db(tmp_path, name="s6_effective.db")
        try:
            await _schema(svc)
            own = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            other = await diag.collect_mechanism_diagnostics(
                svc, OTHER_CHAT, now=NOW_TS)
            return own, other
        finally:
            await svc.close()

    own, other = asyncio.run(scenario())
    for payload, expected_chat in ((own, CHAT), (other, OTHER_CHAT)):
        assert payload["chat_id"] == expected_chat, payload["chat_id"]
        # heartbeat уже посчитан существующим `_health`, а не клиентом.
        assert payload["heartbeat_ok"] is True, payload["heartbeat"]
        assert payload["heartbeat"]["ok"] is True, payload["heartbeat"]
        provider = payload["meme"]["image_provider"]
        assert provider["available"] is True, provider
        assert provider["configured"] is True, provider
        assert provider["module_enabled"] is True, provider
        assert provider["health"] == "healthy", provider
        assert provider["model"] == "img-x", provider
        assert provider["source"] == "meme_initiative.image_dependency"
        gate = next(row for row in payload["meme"]["configuration"]["layers"]
                    if row["gate"] == "image_module")
        assert gate["enabled"] is True, gate
    # Глобальные значения не «перетекают» в чужой chat_id: каждый ответ
    # подписан своим чатом, а heartbeat/provider — общие существующие факты.
    assert own["chat_id"] != other["chat_id"]
    assert own["meme"]["image_provider"] == other["meme"]["image_provider"]
