"""UR-F (UNIFIED-REPLY UI-волна) + BGS-06 UI-half — тесты effective-config.

Покрытие:
  * UR-14.2/UR-21.13/UR-21.17/UR-21.21/UR-24.2 — ключи без рантайм-ридера
    скрыты из рабочего UI/API, значения читаемы, подписи честные;
  * UR-21.15/UR-21.19/UR-21.20/UR-21.22/UR-21.23 — честные подписи
    («Свобода формулировок», «История того, кому бот уже отвечал»,
    «Частота участия», экспертный cap, технические ожидания);
  * UR-22.1 — GET /api/config отдаёт effective_value/source/eff
    (status/active_consumer/units/reason_inactive) — UI не угадывает;
  * UR-29.1/29.2 — «Модули → Время»: полный справочник IANA-зон,
    эффективный пояс + источник + серверные часы, POST с валидацией
    возвращает validated effective + now_local, 422 с причиной при
    невалидной зоне (прежнее значение сохраняется);
  * R-ADM.5/UR-20.3 — диагностика одного ответа из существующей трассы
    (direct_turn_*), честное «нет данных»/trace_not_found.

Запуск: pytest tests/test_ur_ui_effective_config.py -q
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services import param_catalog
from web.api import routes as routes_mod
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495

# Ключи UR-F без активного рантайм-ридера (UR-14.2/21.13/21.17/21.21) + канон
# пояса (UR-24.2). Зеркало services.param_catalog._UR_F_WITHOUT_RUNTIME_READER.
UR_F_DEAD_KEYS = (
    "limits.chat_style_anchors_count",
    "limits.chat_style_anchor_max_chars",
    "flags.chat_style_anchors_enabled",
    "limits.chat_budget_anchors_ratio",
    "flags.chat_mood_enabled",
    "reactions.chat_mood_positive_words",
    "reactions.chat_mood_negative_words",
    "limits.chat_budget_response_ratio",
    "limits.chat_lock_max_entries",
)


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)
        self.closed = False

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(
            INFO_TEXT_FILE=str(tmp_path / "info_text.md"),
            ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            # Явная global-строка (updated_at не NULL) → source="global".
            {"key": "limits.search_max_symbols", "value": 8000,
             "category": "limits", "updated_at": "2026-08-30T01:00:00+00:00"},
            # Синтетический дефолт (строки нет) → source="default".
            {"key": "limits.chat_direct_reply_ttl_days", "value": 30,
             "category": "limits", "updated_at": None},
            # Пресет речи (UR-21.23): явное значение.
            {"key": "limits.chat_temperature_preset_default",
             "value": "balanced", "category": "limits",
             "updated_at": "2026-08-30T02:00:00+00:00"},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
        ],
    )
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    # hot_config — единая sync-точка чтения (bot.py внедряет прод-кэш):
    # в тесте внедряем ЭТОТ кэш, чтобы POST /api/config (cache.set) был
    # виден ChatClock (hot.get) — как в проде.
    monkeypatch.setattr("services.hot_config._cache", cache)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


# ═══ Каталог: мёртвые ключи и честные подписи ══════════════════════════════

class TestCatalogHonesty:
    def test_dead_keys_hidden_but_registry_readable(self):
        """UR-14.2/UR-21.13/UR-21.17/UR-21.21: ключи без ридера выведены из
        рабочего UI (hidden), запись остаётся в реестре — читаема по
        PG-ключу (без DML)."""
        for pg_key in UR_F_DEAD_KEYS:
            spec = param_catalog.get_by_pg_key(pg_key)
            assert spec is not None, f"запись потеряна: {pg_key}"
            assert spec.hidden is True, f"ключ не скрыт из UI: {pg_key}"

    def test_dead_keys_not_promised_working(self):
        """Подписи мёртвых ключей не обещают рабочего поведения."""
        for name in ("CHAT_STYLE_ANCHORS_ENABLED", "CHAT_STYLE_ANCHORS_COUNT",
                     "CHAT_STYLE_ANCHOR_MAX_CHARS",
                     "CHAT_BUDGET_ANCHORS_RATIO", "CHAT_MOOD_ENABLED",
                     "CHAT_MOOD_POSITIVE_WORDS", "CHAT_MOOD_NEGATIVE_WORDS",
                     "CHAT_BUDGET_RESPONSE_RATIO", "CHAT_LOCK_MAX_ENTRIES"):
            spec = param_catalog.REGISTRY.get(name)
            assert spec is not None, name
            text = (spec.title_ru + " " + spec.description).lower()
            assert ("не работает" in text or "снято" in text
                    or "no-op" in text or "не влияет" in text), \
                f"подпись обещает поведение: {name}"

    def test_chat_timezone_hidden_single_surface(self):
        """UR-24.2: канонический пояс скрыт из общего каталога — единственная
        поверхность «Модули → Время» (API /api/config/time)."""
        spec = param_catalog.get_by_pg_key("limits.chat_timezone")
        assert spec is not None and spec.hidden is True
        assert ("Время" in spec.description)

    def test_honest_speech_label(self):
        """UR-21.23: «Свобода формулировок» + сэмплинг-семантика в описании,
        пометка про провайдера — через effective-config."""
        spec = param_catalog.REGISTRY["CHAT_TEMPERATURE_PRESET_DEFAULT"]
        assert spec.title_ru == "Свобода формулировок"
        desc = spec.description.lower()
        assert "сэмплинг" in desc
        assert "игнорирует температуру" in desc
        for name in ("CHAT_TEMPERATURE_PRECISE", "CHAT_TEMPERATURE_BALANCED",
                     "CHAT_TEMPERATURE_CHATTY"):
            assert ("Свобода формулировок"
                    in param_catalog.REGISTRY[name].title_ru), name

    def test_provider_ignores_temperature(self):
        assert param_catalog.provider_ignores_temperature("o3-mini") is True
        assert param_catalog.provider_ignores_temperature(
            "deepseek-r1-0528") is True
        assert param_catalog.provider_ignores_temperature("gpt-4o") is False
        assert param_catalog.provider_ignores_temperature("") is False

    def test_renamed_rows_honest(self):
        ttl = param_catalog.REGISTRY["CHAT_DIRECT_REPLY_TTL_DAYS"]
        assert "История того, кому бот уже отвечал" in ttl.title_ru
        assert "НЕ срок жизни" in ttl.description
        silence = param_catalog.REGISTRY["CHAT_SILENCE_AFTER_COOLDOWNS"]
        assert "Частота участия" in silence.title_ru
        assert "не стиль ответа" in silence.description
        budget = param_catalog.REGISTRY["CHAT_CONTEXT_BUDGET_TOKENS"]
        assert "экспертный" in budget.description.lower()
        assert "рабочее окно" in budget.description.lower()
        l1 = param_catalog.REGISTRY["CHAT_CURRENT_QUESTION_MAX_CHARS"]
        assert "лимит вопроса" in l1.description
        wait = param_catalog.REGISTRY["CHAT_LOCK_WAIT_SECONDS"]
        smart = param_catalog.REGISTRY["SMARTMODULE_CONCURRENCY_WAIT_SECONDS"]
        assert wait.group == "limits_service", "UR-21.20: замок → Служебное"
        assert smart.group == "limits_service", "UR-21.20: слот → Служебное"

    def test_effective_meta_honest(self):
        """UR-22.1/UR-21.24: мера применимости — no_op с причиной, active с
        потребителем, unknown — честный пустой consumer."""
        resp = param_catalog.effective_meta("limits.chat_budget_response_ratio")
        assert resp["status"] == "no_op"
        assert resp["reason_inactive"]
        assert resp["active_consumer"] == ""
        tz = param_catalog.effective_meta("limits.chat_timezone")
        assert tz["status"] == "active"
        assert "chat_clock" in tz["active_consumer"]
        unknown = param_catalog.effective_meta("limits.some_unknown_key")
        assert unknown == {"status": "active", "active_consumer": "",
                           "units": "", "reason_inactive": ""}

    def test_group_descriptions_not_promising_removed_mechanics(self):
        by_id = {g.id: g for g in param_catalog.GROUPS}
        behavior = by_id["flags_chat_behavior"].description.lower()
        assert "якор" not in behavior and "настроени" not in behavior
        temperature = by_id["limits_temperature"]
        assert temperature.title_ru == "Свобода формулировок"
        assert by_id["reactions_chat"].description.lower().find(
            "настроени") == -1


# ═══ API: effective-config, «Время», диагностика хода ══════════════════════

class TestEffectiveConfigAPI:
    def test_items_carry_source_effective_and_eff(self, client):
        resp = client.get("/api/config", headers=_hdr())
        assert resp.status_code == 200
        items = {it["key"]: it for it in resp.json()["items"]}
        explicit = items["limits.search_max_symbols"]
        assert explicit["source"] == "global"
        assert explicit["effective_value"] == explicit["value"]
        assert explicit["eff"]["status"] in ("active", "legacy", "no_op",
                                             "inactive")
        assert "active_consumer" in explicit["eff"]
        assert "units" in explicit["eff"]
        assert "reason_inactive" in explicit["eff"]
        default = items["limits.chat_direct_reply_ttl_days"]
        assert default["source"] == "default", \
            "строки нет в PG → честный default"

    def test_speech_item_carries_units_and_honest_note(self, client):
        resp = client.get("/api/config", headers=_hdr())
        items = {it["key"]: it for it in resp.json()["items"]}
        speech = items["limits.chat_temperature_preset_default"]
        assert speech["eff"]["status"] in ("active", "inactive")
        # UR-21.23: честная пометка появляется только при reasoning-модели;
        # без модели пусто (никаких выдуманных причин).
        if speech["eff"]["reason_inactive"]:
            assert "temperature" in speech["eff"]["reason_inactive"]

    def test_dead_keys_absent_from_config_and_params_meta(self, client):
        resp = client.get("/api/config", headers=_hdr())
        keys = {it["key"] for it in resp.json()["items"]}
        for pg_key in UR_F_DEAD_KEYS:
            assert pg_key not in keys, f"мёртвый ключ в /api/config: {pg_key}"
        assert "limits.chat_timezone" not in keys, \
            "UR-24.2: пояс вне общего каталога (поверхность — «Время»)"
        meta = client.get("/api/config/params-meta", headers=_hdr()).json()
        for pg_key in UR_F_DEAD_KEYS + ("limits.chat_timezone",):
            assert pg_key not in meta["items"], \
                f"мёртвый ключ в params-meta: {pg_key}"


class TestTimeSurface:
    def test_timezones_full_iana_list(self, client):
        resp = client.get("/api/config/timezones", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        zones = body["zones"]
        assert body["count"] == len(zones)
        assert "Europe/Moscow" in zones
        assert len(zones) > 100, "полный справочник zoneinfo, не подмножество"
        assert zones == sorted(zones)

    def test_time_global_state_from_server(self, client):
        resp = client.get("/api/config/time", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_id"] is None
        assert body["iana"], "эффективный пояс от ChatClock"
        assert body["source"] in ("chat", "chat_legacy", "global",
                                  "global_legacy", "legacy_goodmorning",
                                  "factory", "utc_fallback")
        # UR-29.2: now_local вычислен на сервере (по UTC), а не браузером.
        assert body["now_local"]
        assert "T" in body["now_local"]
        assert body["as_of_utc"]

    def test_timezones_requires_auth(self, client):
        assert client.get("/api/config/timezones").status_code == 401

    def test_post_invalid_zone_422_keeps_previous(self, client):
        """UR-29.2: невалидная зона → 422 с причиной; прежнее значение
        сохраняется (UI не применяет черновик)."""
        before = client.get("/api/config/time", headers=_hdr()).json()
        resp = client.post("/api/config/time", headers=_hdr(),
                           json={"timezone": "Mars/Olympus_Mons"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "IANA" in str(detail) or "зон" in str(detail) or detail
        after = client.get("/api/config/time", headers=_hdr()).json()
        assert after["iana"] == before["iana"]

    def test_post_valid_zone_returns_validated_effective(self, client):
        """UR-29.2: сохранение возвращает validated effective + now_local
        по UTC, а не пересчёт клиента."""
        resp = client.post("/api/config/time", headers=_hdr(),
                           json={"timezone": "Europe/Berlin"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["saved"] == "Europe/Berlin"
        assert body["iana"] == "Europe/Berlin", "validated effective"
        assert body["source"] == "global", "глобальная запись без чата"
        assert body["now_local"]
        assert body["as_of_utc"]
        assert body["utc_offset"] in ("+01:00", "+02:00"), \
            "offset соответствуетEurope/Berlin (STD/DST)"
        # Повторный GET видит то же значение (не «сохранено 200» впустую).
        after = client.get("/api/config/time", headers=_hdr()).json()
        assert after["iana"] == "Europe/Berlin"

    def test_post_chat_scope_invalid_zone_422_before_write(self, client):
        """Per-chat путь: валидация ДО записи → 422, ничего не пишется."""
        resp = client.post("/api/config/time", headers=_hdr(),
                           json={"timezone": "Not/AZone", "chat_id": -100})
        assert resp.status_code == 422

    def test_delete_without_override_404(self, client):
        resp = client.delete("/api/config/time?chat_id=-100", headers=_hdr())
        # Профиль чата в фейке отсутствует → честная ошибка (404/409/422),
        # но НЕ «успешный сброс» без факта.
        assert resp.status_code in (404, 409, 422)
        if resp.status_code < 300:
            body = resp.json()
            assert body.get("reset") is True

    def test_delete_requires_chat_scope(self, client):
        resp = client.delete("/api/config/time", headers=_hdr())
        assert resp.status_code == 422


class TestTurnDiagnostics:
    @staticmethod
    def _seed_events():
        base = int(time.time()) - 60
        return [
            {"ts": base, "event_name": "direct_turn_context",
             "outcome": "success", "trace_id": "corr-1", "chat_id": -100,
             "stage": "turn_context",
             "usage_json": json.dumps({
                 "flow": "direct", "trigger": "botword",
                 "l1": {"action": "reply", "model": "test-model"},
                 "tool_rounds": 1, "tool_degraded": False,
                 "tools": [{"tool": "web_search", "status": "success",
                            "refs": 3, "out_chars": 800}],
                 "llm_calls": {"planning": 1},
                 "clock_timezone": "Europe/Moscow",
                 "clock_as_of_utc": "2026-11-06T12:00:00+00:00",
                 "clock_timezone_source": "chat",
                 "idempotency_key": "direct:-100:1:r1:-"}),
             },
            {"ts": base + 1, "event_name": "direct_turn_writer",
             "outcome": "success", "trace_id": "corr-1", "chat_id": -100,
             "stage": "l2_writer",
             "usage_json": json.dumps({
                 "manifest": {"writer": "l2_writer",
                              "blocks": [{"block": "ctx:thread",
                                          "rendered": True, "skip": ""}]},
                 "completion": {"finish_reason": "stop",
                                "fallback_used": False, "attempt": 1,
                                "continuation_calls": 0,
                                "text_source": "author"},
                 "semantic_rewrite_count": 0}),
             },
            {"ts": base + 2, "event_name": "direct_turn_delivery",
             "outcome": "success", "trace_id": "corr-1", "chat_id": -100,
             "stage": "delivery",
             "usage_json": json.dumps({
                 "ops": [{"op": "telegram_chunk", "digest": "ab12",
                          "chars": 420, "changed": False, "chunks": 1}],
                 "raw_final_digest": "ab12", "delivered_digest": "ab12",
                 "digest_match": True, "divergence_reason": "",
                 "delivery": {"outcome": "success", "channel": "reply",
                              "tg_message_ids": [42],
                              "idempotency_key": "direct:-100:1:r1:-"}}),
             },
        ]

    @pytest.fixture(autouse=True)
    def _lore_db_stub(self, monkeypatch):
        """Хранилище телеметрии в тесте — не None (в проде SQLite-сервис
        установлен; здесь достаточно маркера, чтение мокается отдельно)."""
        from services import lore_runtime
        monkeypatch.setattr(lore_runtime, "get_lore_db",
                            lambda: object())

    @staticmethod
    def _patch_query(monkeypatch, rows):
        async def fake_query(db, **kwargs):
            return rows

        monkeypatch.setattr(routes_mod, "mca_events_query", fake_query)

    def test_chain_view_maps_all_stages(self, client, monkeypatch):
        """R-ADM.5: L1 → tools → Writer → ops → delivery собираются из
        существующих событий трассы; «нет данных» для пустых стадий."""
        self._patch_query(monkeypatch, self._seed_events())
        resp = client.get("/api/direct/turn-diagnostics?chat_id=-100",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["trace_id"] == "corr-1"
        assert body["context"]["l1"]["action"] == "reply"
        assert body["context"]["clock"]["timezone"] == "Europe/Moscow"
        assert body["context"]["tools"][0]["tool"] == "web_search"
        assert body["writer"]["completion"]["finish_reason"] == "stop"
        assert body["writer"]["manifest"]["writer"] == "l2_writer"
        assert body["delivery"]["digest_match"] is True
        assert body["delivery"]["ops"][0]["op"] == "telegram_chunk"
        assert body["turns"][0]["trace_id"] == "corr-1"

    def test_missing_stages_are_honest(self, client, monkeypatch):
        """Только context-событие → Writer/delivery «нет данных» (None),
        не выдуманный успех."""
        self._patch_query(monkeypatch, [self._seed_events()[0]])
        body = client.get("/api/direct/turn-diagnostics?chat_id=-100",
                          headers=_hdr()).json()
        assert body["available"] is True
        assert body["context"] is not None
        assert body["writer"] is None
        assert body["delivery"] is None

    def test_no_traces_honest_unavailable(self, client, monkeypatch):
        self._patch_query(monkeypatch, [])
        body = client.get("/api/direct/turn-diagnostics?chat_id=-100",
                          headers=_hdr()).json()
        assert body["available"] is False
        assert body["reason"] == "no_turn_traces"

    def test_trace_not_found(self, client, monkeypatch):
        self._patch_query(monkeypatch, self._seed_events())
        body = client.get(
            "/api/direct/turn-diagnostics?chat_id=-100&trace_id=nope",
            headers=_hdr()).json()
        assert body["available"] is False
        assert body["reason"] == "trace_not_found"

    def test_telemetry_down_is_honest(self, client, monkeypatch):
        """DB None → честный telemetry_unavailable, не пустой успех."""
        from services import lore_runtime
        monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
        body = client.get("/api/direct/turn-diagnostics?chat_id=-100",
                          headers=_hdr()).json()
        assert body["available"] is False
        assert body["reason"] == "telemetry_unavailable"

    def test_requires_chat_access(self, client):
        # Без monkeypatch тест-клиент без БД: честная деградация, не краш.
        resp = client.get("/api/direct/turn-diagnostics?chat_id=-100",
                          headers=_hdr())
        assert resp.status_code in (200, 403)
