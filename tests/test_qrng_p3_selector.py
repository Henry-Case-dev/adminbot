"""QRNG P3 — селектор/fallback/нормализация (arch-decision 2026-11-17 §3 D4–D6).

Покрытие QAN-REC: `REG-01`, `SEL-01`, `SEL-02`, `FALL-01`, `FALL-02`,
`EXC-01…05` (Lizaonair-класс — только проверки отсутствия/резолва).

Инварианты P3:
  * селектор — ГЛОБАЛЬНЫЙ: primary_provider (select трёх действующих id,
    default ibm_quantum), fallback_enabled (bool, default true),
    fallback_order (json: только id реестра, без дублей, без primary);
    чатовая запись любого из них → 422;
  * `keys.random_quantum_provider` скрыт из UI/API (строка БД не удаляется);
  * резолв: primary → fallback_order; провайдер доступен при наличии
    конфигурации и/или расходуемого запаса; ни одного → deferred (не quantum,
    не PRNG); PRNG — отдельная явная ось, не провайдер и не ступень;
  * снятое/неизвестное сохранённое значение не действует, не подменяется
    молча и не перезаписывается: `requires_resolution` + канонический порядок
    IBM→ANU→LfDR; новые неизвестные id → 422; история draw не переписывается;
  * LfDR подключён к resolve/refill через ОДИН сервисный `LfdrClient`
    (N1: breaker/min-interval сохраняются между вызовами), IBM job не
    включается (P5);
  * существующий режим `memory.random_source` и сохранённый PRNG `true`
    сохраняются без перезаписи.
"""
import asyncio
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import hot_config as hot
from services import mca_random_source as mrs
from services import param_catalog as pc
from services.config_cache import ConfigCache
from services.database import DatabaseService
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_QRNG_P3"
ADMIN_ID = 5885953495
MEMBER_ID = 1313107079

PRIMARY = mrs.SETTING_PRIMARY_PROVIDER
ORDER = mrs.SETTING_FALLBACK_ORDER
FB_ENABLED = mrs.SETTING_PROVIDER_FALLBACK_ENABLED


# ── fixtures/helpers ────────────────────────────────────────────────────────
async def _fresh_db(tmp_path, name="qrng_p3.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def ok_uint16(length: int, start: int = 0):
    return (200, {},
            '{"success": true, "type": "uint16", "length": %d, "data": %s}'
            % (length, list(range(start, start + length))))


def ok_lfdr(length: int, start: int = 0):
    qrn = "".join("%02x" % ((start + i) % 256) for i in range(length))
    return (200, {}, json.dumps({"length": length, "qrn": qrn}))


def make_http(responses, calls=None):
    calls = calls if calls is not None else []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params)})
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, hdrs, text = item
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get, calls


@pytest.fixture
def mem(monkeypatch):
    """Слой memory.* (режим/PRNG-переключатель; чатовое наследование)."""
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    """Глобальный слой (hot): ключи ANU и селектор P3."""
    values: dict = {}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


def make_service(db, cfg, *, anu_key=None, clock=None):
    """Сервис с фейковым ANU-клиентом; запас наполняется явно в тестах."""
    cfg[mrs.SETTING_BATCH_LENGTH] = 8
    http_get, calls = make_http([])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=clock or FakeClock())
    svc = mrs.RandomSourceService(db, client=client, auto_refill=False,
                                  clock=clock or FakeClock())
    if anu_key is not None:
        cfg[mrs.SETTING_KEY] = anu_key
    return svc, calls


async def _insert_batch(db, provider, values, *, fingerprint=None,
                        data_type="uint16", created_at=None):
    store = mrs.RandomStore(db)
    return await store.insert_batch(
        mrs.AnuBatch(values=list(values), data_type=data_type,
                     length=len(values), provider=provider),
        config_fingerprint=fingerprint, created_at=created_at)


# ── API-окружение (реальный ConfigCache над фейковым PG) ────────────────────
def make_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "qrngP3",
        "user": json.dumps({"id": user_id, "first_name": "T"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID, chat_id: int | None = None) -> dict:
    headers = {"X-Telegram-Init-Data": make_init_data(user_id)}
    if chat_id is not None:
        headers["X-Chat-Id"] = str(chat_id)
    return headers


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

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "member", "permissions": {"sections": ["memory"]},
     "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
    {"telegram_id": MEMBER_ID, "role_name": "member",
     "added_by": ADMIN_ID, "created_at": None},
]


@pytest.fixture
def api_env(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[{"key": "keys.random_quantum_api_key",
                        "value": "stored-anu-key-1234", "category": "keys",
                        "updated_at": None}],
        role_rows=_ROLE_ROWS, admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as client:
        client.cache = cache
        yield client


# ── 1. Каталог: глобальные параметры и скрытый информационный ключ ─────────
class TestCatalogContract:
    def test_three_selector_params_are_global_only_memory(self):
        for key, typ in ((PRIMARY, "str"), (ORDER, "json"),
                         (FB_ENABLED, "bool")):
            spec = pc.get_by_pg_key(key)
            assert spec is not None, key
            assert spec.category == "memory", key
            assert spec.global_only is True, key
            assert spec.per_chat is False, key
            assert spec.type == typ, key
            assert spec.group == "memory_random", key
            assert spec.hidden is False, key
            assert spec.resolved_sensitivity == pc.SENSITIVITY_CONFIG, key

    def test_primary_select_offers_exactly_registry_ids(self):
        spec = pc.get_by_pg_key(PRIMARY)
        assert spec.widget == "select"
        assert spec.select_options == mrs.PROVIDER_IDS
        assert len(spec.select_labels) == len(spec.select_options)
        assert "lizaonair" not in " ".join(spec.select_labels).lower()

    def test_retired_provider_absent_from_registry_and_options(self):
        blob = json.dumps(
            {"providers": list(mrs.PROVIDER_IDS),
             "options": list(pc.get_by_pg_key(PRIMARY).select_options)},
            ensure_ascii=False).lower()
        assert "lizaonair" not in blob
        assert mrs.canonical_provider_id("lizaonair") == ""

    def test_provider_info_key_hidden_but_present_in_registry(self):
        spec = pc.get_by_pg_key("keys.random_quantum_provider")
        assert spec is not None
        assert spec.hidden is True
        # Строка/значение не удаляются: ключ остаётся в реестре и БД-слое.
        assert pc.get("RANDOM_QUANTUM_PROVIDER") is not None

    def test_defaults_are_visible_without_db_row(self):
        """Синтетика get_all: bool-ось имеет честный дефолт; скрытый ключ —
        вне UI-каталога; str/json — «не задано» (заводской default в рантайме)."""
        cache = ConfigCache.__new__(ConfigCache)
        cache._settings = {}
        snap = cache.get_all()
        assert snap[FB_ENABLED] is True
        assert snap[PRIMARY] == ""
        assert snap[ORDER] is None
        assert "keys.random_quantum_provider" not in snap

    def test_validation_rules(self):
        assert pc.validate_value_rule(PRIMARY, "anu") is None
        assert pc.validate_value_rule(PRIMARY, "") is None
        assert pc.validate_value_rule(PRIMARY, "ibm_quantum") is None
        assert "неизвестный провайдер" in (
            pc.validate_value_rule(PRIMARY, "lizaonair") or "")
        # Новые записи — только канонические id (алиас не сохраняется).
        assert pc.validate_value_rule(
            PRIMARY, "ANU Quantum Numbers") is not None
        assert pc.validate_value_rule(ORDER, []) is None
        assert pc.validate_value_rule(ORDER, ["anu", "lfdr"]) is None
        assert pc.validate_value_rule(ORDER, '["anu", "lfdr"]') is None
        assert pc.validate_value_rule(ORDER, ["anu", "anu"]) is not None
        assert pc.validate_value_rule(ORDER, ["lizaonair"]) is not None
        assert pc.validate_value_rule(ORDER, "not-json") is not None
        assert pc.validate_value_rule(ORDER, {"a": 1}) is not None


# ── 2. API: global-only (чат → 422), валидация новых id, скрытый ключ ───────
class TestConfigApi:
    def test_chat_scope_write_is_422_for_all_three(self, api_env):
        for key, value in ((PRIMARY, "anu"), (ORDER, ["anu"]),
                           (FB_ENABLED, True)):
            resp = api_env.post(
                "/api/config", headers=_hdr(chat_id=-100123),
                json={"items": [{"key": key, "value": value}]})
            assert resp.status_code == 422, (key, resp.text)
            assert "уровень чата" in resp.text, key

    def test_global_unknown_provider_is_422(self, api_env):
        resp = api_env.post("/api/config", headers=_hdr(),
                            json={"items": [{"key": PRIMARY,
                                             "value": "lizaonair"}]})
        assert resp.status_code == 422, resp.text
        assert "неизвестный провайдер" in resp.text
        # Алиас/легаси-имя тоже не проходит как НОВАЯ запись.
        resp = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": PRIMARY,
                             "value": "ANU Quantum Numbers"}]})
        assert resp.status_code == 422, resp.text

    def test_global_order_validation_422(self, api_env):
        for value in (["lizaonair"], ["anu", "anu"], ["anu", "evil"],
                      "not-json"):
            resp = api_env.post("/api/config", headers=_hdr(),
                                json={"items": [{"key": ORDER,
                                                 "value": value}]})
            assert resp.status_code == 422, (value, resp.text)

    def test_order_with_primary_is_422(self, api_env):
        resp = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": PRIMARY, "value": "anu"},
                            {"key": ORDER, "value": ["anu", "lfdr"]}]})
        assert resp.status_code == 422, resp.text
        assert "не может быть в запасном порядке" in resp.text

    def test_valid_batch_is_saved(self, api_env):
        resp = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": PRIMARY, "value": "anu"},
                            {"key": ORDER, "value": ["lfdr"]},
                            {"key": FB_ENABLED, "value": False}]})
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["updated"]) == {PRIMARY, ORDER, FB_ENABLED}
        assert api_env.cache.get(PRIMARY) == "anu"
        assert api_env.cache.get(ORDER) == ["lfdr"]
        assert api_env.cache.get(FB_ENABLED) is False

    def test_primary_change_against_saved_order_is_422(self, api_env):
        ok = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": PRIMARY, "value": "ibm_quantum"},
                            {"key": ORDER, "value": ["anu", "lfdr"]}]})
        assert ok.status_code == 200, ok.text
        resp = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": PRIMARY, "value": "lfdr"}]})
        assert resp.status_code == 422, resp.text
        # Итоговое состояние не изменилось (атомарность прохода 1).
        assert api_env.cache.get(PRIMARY) == "ibm_quantum"

    def test_provider_info_key_hidden_from_config_and_meta(self, api_env):
        items = {i["key"] for i in
                 api_env.get("/api/config", headers=_hdr()).json()["items"]}
        assert "keys.random_quantum_provider" not in items
        assert "keys.random_quantum_endpoint" in items
        meta = api_env.get("/api/config/params-meta",
                           headers=_hdr()).json()["items"]
        assert "keys.random_quantum_provider" not in meta
        resp = api_env.post(
            "/api/config", headers=_hdr(),
            json={"items": [{"key": "keys.random_quantum_provider",
                             "value": "anu"}]})
        assert resp.status_code == 422, resp.text

    def test_new_params_are_visible_in_config(self, api_env):
        items = {i["key"]: i for i in
                 api_env.get("/api/config", headers=_hdr()).json()["items"]}
        assert items[PRIMARY]["per_chat"] is False
        assert items[PRIMARY]["widget"] == "select"
        assert items[ORDER]["type"] == "json"
        assert items[FB_ENABLED]["per_chat"] is False


# ── 3. Матрица резолва ──────────────────────────────────────────────────────
class TestResolveMatrix:
    @pytest.mark.asyncio
    async def test_primary_default_ibm_unavailable_goes_to_configured_anu(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            await _insert_batch(db, "anu", range(6),
                                fingerprint=mrs.key_fingerprint("anu-key-A"))
            res = await svc.resolve_selection(1)
            assert res.primary_setting_state == "absent"
            assert res.primary_provider == "ibm_quantum"
            assert res.effective_order == ("ibm_quantum", "anu", "lfdr")
            assert res.resolved_primary == "anu"
            assert res.effective_provider == "anu"
            assert res.mode == "quantum"
            assert res.blocker is None
            draw = await svc.draw_index(3, chat_id=1, purpose="p")
            assert draw.source == "quantum" and draw.provider_id == "anu"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_explicit_primary_anu_is_chosen(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "anu"
            await _insert_batch(db, "anu", range(4))
            res = await svc.resolve_selection(1)
            assert res.primary_setting_raw == "anu"
            assert res.primary_setting_state == "set"
            assert res.effective_order == ("anu", "lfdr")
            assert res.effective_provider == "anu"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_inherited_primary_honours_saved_fallback_order(
            self, tmp_path, cfg, mem):
        """UI-08..10 R1/F-01: явный сохранённый порядок действует и при
        наследуемом primary, а не подменяется заводской цепочкой."""
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[ORDER] = ["lfdr", "anu"]
            await _insert_batch(db, "lfdr", [1, 2, 3])
            res = await svc.resolve_selection(1)
            assert res.primary_setting_state == "absent"
            assert res.effective_order == ("ibm_quantum", "lfdr", "anu")
            assert res.fallback_order == ("lfdr", "anu")
            assert res.effective_provider == "lfdr"
            assert res.resolved_primary == "lfdr"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_inherited_primary_explicit_empty_reserve_has_no_fallback(
            self, tmp_path, cfg, mem):
        """UI-08..10 R1/F-01: явный пустой резерв при наследуемом primary —
        это решение «без резерва», а не заводская цепочка."""
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[ORDER] = []
            await _insert_batch(db, "lfdr", [1, 2, 3])
            res = await svc.resolve_selection(1)
            assert res.primary_setting_state == "absent"
            assert res.effective_order == ("ibm_quantum",)
            assert res.fallback_order == ()
            assert res.effective_provider is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_primary_lfdr_uses_lfdr_batch_not_oldest(self, tmp_path,
                                                           cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "lfdr"
            # Явные created_at: ANU-партия СТАРЕЕ LfDR. Без фильтра провайдера
            # reserve_draw взял бы ANU (самая старая), с фильтром — только LfDR.
            await _insert_batch(db, "anu", range(10),
                                fingerprint=mrs.key_fingerprint("anu-key-A"),
                                created_at=1000)
            await _insert_batch(db, "lfdr", [7, 8, 9, 10], created_at=2000)
            res = await svc.resolve_selection(1)
            assert res.resolved_primary == "lfdr"
            assert res.effective_provider == "lfdr"
            assert res.effective_order == ("lfdr", "anu")
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == "quantum"
            assert draw.provider_id == "lfdr"
            assert draw.entropy_class == "hardware_quantum"
            # ANU-партия не израсходована: выбор провайдера — не «самый старый
            # batch», а действующий порядок.
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["provider_reserve"]["anu"] == 10
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_primary_unavailable_falls_to_next_with_reserve(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key=None)
            cfg[PRIMARY] = "anu"          # ключа нет → провайдер недоступен
            cfg[ORDER] = ["lfdr"]
            await _insert_batch(db, "lfdr", [1, 2, 3])
            res = await svc.resolve_selection(1)
            assert res.resolved_primary == "lfdr"
            assert res.effective_provider == "lfdr"
            assert res.mode == "quantum"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_configured_primary_without_values_uses_next(self, tmp_path,
                                                               cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            await _insert_batch(db, "lfdr", [1, 2, 3])   # у ANU запаса нет
            res = await svc.resolve_selection(1)
            assert res.resolved_primary == "anu"    # доступен (сконфигурирован)
            assert res.effective_provider == "lfdr"  # значения — из LfDR
            assert res.mode == "quantum"
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.provider_id == "lfdr"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fallback_disabled_only_primary_then_deferred(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "ibm_quantum"
            cfg[FB_ENABLED] = False
            cfg[ORDER] = ["anu", "lfdr"]
            mem[mrs.SETTING_FALLBACK] = False
            res = await svc.resolve_selection(1)
            assert res.effective_order == ("ibm_quantum",)
            assert res.fallback_order == ()
            assert res.resolved_primary is None
            assert res.mode == "deferred"
            assert res.blocker == "provider_unconfigured"
            draw = await svc.draw_index(10, chat_id=1, purpose="p")
            assert draw.deferred is True and draw.index is None
            assert await svc.recent_draws(limit=5) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fallback_disabled_with_lfdr_primary_defers(self, tmp_path,
                                                              cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            cfg[PRIMARY] = "lfdr"
            cfg[FB_ENABLED] = False
            mem[mrs.SETTING_FALLBACK] = False
            res = await svc.resolve_selection(1)
            assert res.effective_order == ("lfdr",)
            assert res.resolved_primary == "lfdr"
            assert res.effective_provider is None
            assert res.mode == "deferred"
            assert res.blocker == "provider_unavailable"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_all_unavailable_deferred_not_prng(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)     # ключа ANU нет, запасов нет
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = []
            mem[mrs.SETTING_FALLBACK] = False
            res = await svc.resolve_selection(1)
            assert res.mode == "deferred"      # ни quantum, ни PRNG
            assert res.blocker == "provider_unconfigured"
            draw = await svc.draw_probability(chat_id=1, purpose="p")
            assert draw.deferred is True and draw.value is None
            assert await svc.recent_draws(limit=5) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_prng_fallback_is_explicit_and_never_hidden(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = []
            mem[mrs.SETTING_FALLBACK] = True
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["effective_source"] == "pseudorandom"
            assert snap["fallback_setting"] is True
            assert snap["prng_active"] is True
            assert snap["fallback_setting_label"] == (
                "псевдослучайный откат (не квантовый)")
            assert snap["entropy_class"] is None
            draw = await svc.draw_index(5, chat_id=1, purpose="p")
            assert draw.source == "pseudorandom"
            assert draw.entropy_class is None
            assert draw.provider == mrs.PROVIDER_PRNG
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_quantum_draw_never_labelled_prng_and_vice_versa(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            await _insert_batch(db, "anu", [4, 5, 6])
            quantum = await svc.draw_index(2, chat_id=1, purpose="p")
            assert quantum.source == "quantum"
            assert quantum.entropy_class == "hardware_quantum"
            rows = await svc.recent_draws(limit=5)
            assert rows[0]["source"] == "quantum"
        finally:
            await db.close()


# ── 4. Снятое сохранённое значение (Lizaonair-класс) ────────────────────────
class TestRetiredValue:
    @pytest.mark.asyncio
    async def test_unknown_saved_primary_requires_resolution(self, tmp_path,
                                                             cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "lizaonair"
            await _insert_batch(db, "anu", [1, 2, 3])
            res = await svc.resolve_selection(1)
            assert res.primary_setting_raw == "lizaonair"   # как сохранено
            assert res.primary_setting_state == "requires_resolution"
            assert res.effective_order == ("ibm_quantum", "anu", "lfdr")
            assert res.primary_provider == "ibm_quantum"
            assert res.resolved_primary == "anu"
            assert res.effective_provider == "anu"
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["primary_setting_raw"] == "lizaonair"
            assert snap["primary_setting_state"] == "requires_resolution"
            assert snap["resolved_primary"] == "anu"
            # Сохранённое значение не перезаписано.
            assert cfg[PRIMARY] == "lizaonair"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_retired_value_ignores_saved_custom_order(self, tmp_path,
                                                            cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "lizaonair"
            cfg[ORDER] = ["lfdr", "anu"]
            res = await svc.resolve_selection(1)
            # Действует канонический порядок, а не порядок под снятое значение.
            assert res.effective_order == ("ibm_quantum", "anu", "lfdr")
            assert cfg[PRIMARY] == "lizaonair"
            assert cfg[ORDER] == ["lfdr", "anu"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_retired_value_does_not_rewrite_history(self, tmp_path, cfg,
                                                          mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "lizaonair"
            fp = mrs.key_fingerprint("anu-key-A")
            batch_id = await _insert_batch(db, "anu", [9, 8, 7],
                                           fingerprint=fp)
            before = [
                dict(r) for r in await _rows(
                    db, "SELECT * FROM mca_random_batches ORDER BY batch_id")]
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == "quantum"
            after = [
                dict(r) for r in await _rows(
                    db, "SELECT * FROM mca_random_batches ORDER BY batch_id")]
            assert after[0]["batch_id"] == batch_id
            assert after[0]["provider"] == "anu"
            assert after[0]["config_fingerprint"] == fp
            assert after[0]["length"] == before[0]["length"]
            assert cfg[PRIMARY] == "lizaonair"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_alias_saved_value_maps_not_flags(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            cfg[PRIMARY] = "ANU Quantum Numbers"    # легаси-алиас (D1)
            res = await svc.resolve_selection(1)
            assert res.primary_setting_state == "set"
            assert res.primary_setting_raw == "ANU Quantum Numbers"
            assert res.effective_order[0] == "anu"
        finally:
            await db.close()


async def _rows(db, sql):
    cur = await db.db.execute(sql)
    return [dict(r) for r in await cur.fetchall()]


# ── 5. LfDR в refill: общий клиент (N1), breaker/min-interval ───────────────
class TestLfdrRuntime:
    @pytest.mark.asyncio
    async def test_refill_lfdr_uses_one_shared_client(self, tmp_path, cfg,
                                                      mem, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            svc, anu_calls = make_service(db, cfg)
            cfg[PRIMARY] = "lfdr"
            cfg[FB_ENABLED] = False
            http_get, lfdr_calls = make_http(
                [ok_lfdr(8, 1), ok_lfdr(8, 9)])
            svc.set_lfdr_client(mrs.LfdrClient(
                http_get=http_get, min_interval=0.0, clock=FakeClock()))
            seen = []
            real = mrs.lfdr_fetch

            async def spy(*, length, client=None, **kwargs):
                seen.append(client)
                return await real(length=length, client=client)

            monkeypatch.setattr(mrs, "lfdr_fetch", spy)
            first = await svc.refill_if_needed(force=True)
            second = await svc.refill_if_needed(force=True)
            assert first["status"] == "completed", first
            assert second["status"] == "completed", second
            assert len(lfdr_calls) == 2
            assert anu_calls == []                     # ANU не вызывался
            assert seen[0] is seen[1] is svc._lfdr_client
            rows = await _rows(
                db, "SELECT provider, config_fingerprint FROM "
                    "mca_random_batches ORDER BY created_at, batch_id")
            assert [r["provider"] for r in rows] == ["lfdr", "lfdr"]
            assert all(r["config_fingerprint"] is None for r in rows)
            # Запас сразу расходуем выбранным провайдером.
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == "quantum" and draw.provider_id == "lfdr"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_shared_client_min_interval_and_breaker(self, tmp_path, cfg,
                                                          mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            clock = FakeClock()
            http_get, calls = make_http([ok_lfdr(8), ok_lfdr(8)])
            client = mrs.LfdrClient(http_get=http_get, min_interval=10.0,
                                    circuit_fails=3, circuit_cooldown=60.0,
                                    clock=clock)
            svc.set_lfdr_client(client)
            ok = await svc._do_lfdr_refill()
            assert ok["ok"] is True and len(calls) == 1
            # Второй вызов через ТОТ ЖЕ клиент: min-interval режет запрос
            # (N1: состояние не теряется между вызовами).
            limited = await svc._do_lfdr_refill()
            assert limited["ok"] is False
            assert limited["reason"] == "rate_limit"
            assert len(calls) == 1
            assert svc._lfdr_health["state"] == "degraded"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_lfdr_failure_does_not_poison_anu_state(self, tmp_path, cfg,
                                                          mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            http_get, _calls = make_http(
                [(500, {}, '{"error": "boom"}'), (500, {}, "{}"),
                 (500, {}, "{}")])
            svc.set_lfdr_client(mrs.LfdrClient(http_get=http_get,
                                               min_interval=0.0,
                                               clock=FakeClock()))
            for _ in range(3):
                await svc._do_lfdr_refill()
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["lfdr_state"] == "degraded"
            assert snap["anu_state"] == "unverified"   # ANU не «сломан» LfDR
            assert snap["last_fallback_reason"] is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_anu_refill_path_is_unchanged(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            cfg[mrs.SETTING_BATCH_LENGTH] = 8
            http_get, anu_calls = make_http([ok_uint16(8)])
            client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                                   clock=FakeClock())
            svc = mrs.RandomSourceService(db, client=client,
                                          auto_refill=False)
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert len(anu_calls) == 1
            assert anu_calls[0]["url"] == mrs.ANU_ENDPOINT
            rows = await _rows(db, "SELECT provider FROM mca_random_batches")
            assert [r["provider"] for r in rows] == ["anu"]
        finally:
            await db.close()


# ── 6. Режим/PRNG-настройка владельца не перезаписываются ──────────────────
class TestPreservedSettings:
    @pytest.mark.asyncio
    async def test_mode_pseudorandom_preserved(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            await _insert_batch(db, "anu", range(10))
            mem[mrs.SETTING_SOURCE] = "pseudorandom"
            res = await svc.resolve_selection(1)
            assert res.selected_mode == "pseudorandom"
            assert res.mode == "pseudorandom"
            assert res.blocker is None
            draw = await svc.draw_index(5, chat_id=1, purpose="p")
            assert draw.source == "pseudorandom"
            # Квантовый запас не израсходован явным PRNG-режимом.
            assert await svc._reserve_remaining() == 10
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_saved_prng_true_not_rewritten(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            mem[mrs.SETTING_FALLBACK] = True
            await svc.status_snapshot(chat_id=1)
            await svc.draw_index(4, chat_id=1, purpose="p")
            assert mem[mrs.SETTING_FALLBACK] is True
            assert await svc.fallback_enabled(1) is True
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_selector_settings_are_never_written_by_runtime(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            cfg[PRIMARY] = "lizaonair"
            mem[mrs.SETTING_FALLBACK] = True
            await svc.status_snapshot(chat_id=1)
            await svc.draw_index(4, chat_id=1, purpose="p")
            assert cfg[PRIMARY] == "lizaonair"
            assert ORDER not in cfg
            assert FB_ENABLED not in cfg
        finally:
            await db.close()


# ── 7. Статус: селектор и честные per-provider поля ────────────────────────
class TestStatusDto:
    @pytest.mark.asyncio
    async def test_dto_fields_and_no_fake_green(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg)
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            cfg[FB_ENABLED] = True
            snap = await svc.status_snapshot(chat_id=1)
            for key in ("primary_provider", "primary_setting_raw",
                        "primary_setting_state", "resolved_primary",
                        "effective_provider", "fallback_enabled",
                        "fallback_order", "effective_order", "prng_active",
                        "lfdr_state"):
                assert key in snap, key
            assert snap["primary_provider"] == "anu"
            assert snap["fallback_enabled"] is True
            assert snap["fallback_order"] == ["lfdr"]
            by_id = {p["id"]: p for p in snap["providers"]}
            assert by_id["anu"]["configured"] is False   # ключа нет
            assert by_id["anu"]["consumable"] is False
            assert by_id["lfdr"]["configured"] is True   # ключ не требуется
            assert by_id["lfdr"]["state"] == "unverified"
            assert by_id["ibm_quantum"]["configured"] is False  # P5, не green
            assert by_id["ibm_quantum"]["reserve"] == 0
            assert all("consumable" in p and "quarantined" in p
                       for p in snap["providers"])
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_quarantine_per_provider_after_key_rotation(self, tmp_path,
                                                              cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            svc, _ = make_service(db, cfg, anu_key="anu-key-A")
            await _insert_batch(db, "anu", range(5),
                                fingerprint=mrs.key_fingerprint("anu-key-A"))
            await _insert_batch(db, "lfdr", [1, 2])
            cfg[mrs.SETTING_KEY] = "anu-key-B"
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["provider_reserve"]["anu"] == 0
            assert snap["provider_quarantined"]["anu"] == 5
            assert snap["provider_reserve"]["lfdr"] == 2
            assert snap["effective_provider"] == "lfdr"
            assert snap["resolved_primary"] == "anu"   # ключ B есть, запаса нет
        finally:
            await db.close()


# ── 8. F2: refill failover между провайдерами (bounded, один проход) ────────
def _refill_service(db, cfg, *, anu_responses, lfdr_responses, anu_key=None,
                    circuit_fails=3, clock=None):
    cfg[mrs.SETTING_BATCH_LENGTH] = 8
    clock = clock or FakeClock()
    anu_http, anu_calls = make_http(list(anu_responses))
    anu = mrs.AnuClient(http_get=anu_http, min_interval=0.0,
                        circuit_fails=circuit_fails, clock=clock)
    svc = mrs.RandomSourceService(db, client=anu, auto_refill=False,
                                  clock=clock)
    lfdr_http, lfdr_calls = make_http(list(lfdr_responses))
    svc.set_lfdr_client(mrs.LfdrClient(http_get=lfdr_http, min_interval=0.0,
                                       circuit_fails=circuit_fails,
                                       clock=clock))
    if anu_key is not None:
        cfg[mrs.SETTING_KEY] = anu_key
    return svc, anu_calls, lfdr_calls


class TestRefillFailover:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("anu_response,expected_code", [
        ((401, {}, '{"error": "bad key"}'), "auth_failed"),
        # ANU-клиент исторически отдаёт 429 как quota_exhausted (квота
        # аккаунта), не rate_limit — фиксируем фактический код.
        ((429, {}, '{"error": "slow down"}'), "quota_exhausted"),
        ((500, {}, '{"error": "boom"}'), "provider_unavailable"),
    ])
    async def test_anu_failure_falls_to_lfdr_and_draw_uses_it(
            self, tmp_path, cfg, mem, anu_response, expected_code):
        db = await _fresh_db(tmp_path)
        try:
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            svc, anu_calls, lfdr_calls = _refill_service(
                db, cfg, anu_key="anu-key-A",
                anu_responses=[anu_response],
                lfdr_responses=[ok_lfdr(8, 1)])
            result = await svc.refill_if_needed()
            assert result["status"] == "completed", result
            assert result.get("provider") == "lfdr"
            assert len(anu_calls) == 1
            assert len(lfdr_calls) == 1
            attempts = result.get("attempts") or []
            assert attempts and attempts[0]["provider"] == "anu"
            assert attempts[0]["reason"] == expected_code
            rows = await _rows(db, "SELECT provider FROM mca_random_batches")
            assert [r["provider"] for r in rows] == ["lfdr"]
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == "quantum"
            assert draw.provider_id == "lfdr"
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["effective_provider"] == "lfdr"
            assert snap["prng_active"] is False
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fallback_disabled_does_not_call_secondary(
            self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            cfg[FB_ENABLED] = False
            mem[mrs.SETTING_FALLBACK] = True     # PRNG разрешён политикой
            svc, anu_calls, lfdr_calls = _refill_service(
                db, cfg, anu_key="anu-key-A",
                anu_responses=[(401, {}, '{"error": "bad key"}')],
                lfdr_responses=[ok_lfdr(8, 1)])
            result = await svc.refill_if_needed()
            # Честный провал fetch, НЕ completed; LfDR не вызывался.
            assert result["status"] == "failed", result
            assert result["reason"] == "auth_failed"
            assert len(anu_calls) == 1
            assert lfdr_calls == []
            assert await _rows(db, "SELECT provider FROM mca_random_batches") \
                == []
            # Политика fallback OFF: PRNG разрешён явно, квантовых значений нет.
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == "pseudorandom"
            assert draw.entropy_class is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_all_fetches_fail_is_not_completed(self, tmp_path, cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            svc, anu_calls, lfdr_calls = _refill_service(
                db, cfg, anu_key="anu-key-A",
                anu_responses=[(401, {}, '{"error": "bad key"}')],
                lfdr_responses=[(500, {}, '{"error": "boom"}')])
            result = await svc.refill_if_needed()
            assert result["status"] == "failed", result
            assert result["reason"] == "provider_unavailable"
            assert len(anu_calls) == 1 and len(lfdr_calls) == 1
            assert await _rows(db, "SELECT provider FROM mca_random_batches") \
                == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_same_provider_not_retried_in_one_call(self, tmp_path, cfg,
                                                         mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            # Ровно один ANU-ответ и один LfDR-ответ: повторный вызов любого
            # провайдера уронил бы тест (make_http без элементов).
            svc, anu_calls, lfdr_calls = _refill_service(
                db, cfg, anu_key="anu-key-A",
                anu_responses=[(500, {}, '{"error": "boom"}')],
                lfdr_responses=[(500, {}, '{"error": "boom"}')])
            result = await svc.refill_if_needed()
            assert result["status"] == "failed", result
            assert len(anu_calls) == 1
            assert len(lfdr_calls) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_open_breaker_skips_primary_on_next_call(self, tmp_path,
                                                           cfg, mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[PRIMARY] = "anu"
            cfg[ORDER] = ["lfdr"]
            svc, anu_calls, lfdr_calls = _refill_service(
                db, cfg, anu_key="anu-key-A", circuit_fails=1,
                anu_responses=[(401, {}, '{"error": "bad key"}')],
                lfdr_responses=[ok_lfdr(8, 1), ok_lfdr(8, 9)])
            first = await svc.refill_if_needed()
            assert first["status"] == "completed"
            assert first["provider"] == "lfdr"
            second = await svc.refill_if_needed()
            assert second["status"] == "completed"
            assert second["provider"] == "lfdr"
            # ANU не дёргается повторно: breaker open → кандидат исключён.
            assert len(anu_calls) == 1
            assert len(lfdr_calls) == 2
        finally:
            await db.close()


# ── 9. F3: заводской PRNG default false; сохранённое true не перетирается ───
class TestFactoryPrngDefault:
    def test_factory_default_is_false(self):
        assert mrs.DEFAULT_FALLBACK is False
        from config.settings import Settings
        assert Settings.RANDOM_FALLBACK_TO_PSEUDORANDOM is False
        assert Settings().RANDOM_FALLBACK_TO_PSEUDORANDOM is False

    @pytest.mark.asyncio
    async def test_new_install_without_saved_value_defers(self, tmp_path, cfg,
                                                          mem):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            assert await svc.fallback_enabled(1) is False
            res = await svc.resolve_selection(1)
            assert res.mode == "deferred"        # не quantum и не PRNG
            draw = await svc.draw_index(4, chat_id=1, purpose="p")
            assert draw.deferred is True and draw.index is None
            assert await svc.recent_draws(limit=5) == []
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["fallback_setting"] is False
            assert snap["prng_active"] is False
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_saved_true_preserved_and_explicit(self, tmp_path, cfg,
                                                      mem):
        db = await _fresh_db(tmp_path)
        try:
            mem[mrs.SETTING_FALLBACK] = True
            svc = mrs.RandomSourceService(db, auto_refill=False)
            res = await svc.resolve_selection(1)
            assert res.mode == "pseudorandom"
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["fallback_setting"] is True
            assert snap["prng_active"] is True
            assert mem[mrs.SETTING_FALLBACK] is True   # не перезаписано
        finally:
            await db.close()

    def test_seed_new_install_false_and_existing_true_kept(self, tmp_path):
        import sqlite3
        from services import pg_db
        key = mrs.SETTING_FALLBACK

        def _seed(name, preexisting):
            conn = sqlite3.connect(str(tmp_path / name))
            conn.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, "
                         "value TEXT, category TEXT)")
            if preexisting is not None:
                conn.execute("INSERT INTO bot_settings VALUES (?,?,?)",
                             (key, json.dumps(preexisting), "memory"))

            class _Conn:
                async def execute(self, sql, *args):
                    conn.execute(
                        sql.replace("$1", "?").replace("$2", "?")
                        .replace("$3", "?"), args)

            asyncio.run(pg_db._seed_settings_into(_Conn()))
            row = conn.execute(
                "SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
            conn.close()
            return json.loads(row[0])

        assert _seed("fresh.db", None) is False          # новая установка
        assert _seed("existing.db", True) is True        # строка владельца цела


# ── 10. F1: global-only селектор не виден чатовому non-admin ────────────────
class TestChatVisibility:
    SELECTOR_KEYS = (PRIMARY, ORDER, FB_ENABLED)

    @staticmethod
    def _keys(resp):
        assert resp.status_code == 200, resp.text
        return {i["key"] for i in resp.json()["items"]}

    def test_member_chat_scope_hides_selector(self, api_env):
        keys = self._keys(api_env.get(
            "/api/config", headers=_hdr(MEMBER_ID, chat_id=MEMBER_ID)))
        for key in self.SELECTOR_KEYS:
            assert key not in keys, key
        # Ответ не пустой: фильтр узкий (только селектор), прочие ключи живы.
        assert keys

    def test_global_admin_chat_scope_sees_selector(self, api_env):
        keys = self._keys(api_env.get(
            "/api/config", headers=_hdr(ADMIN_ID, chat_id=ADMIN_ID)))
        for key in self.SELECTOR_KEYS:
            assert key in keys, key

    def test_global_scope_sees_selector(self, api_env):
        keys = self._keys(api_env.get("/api/config", headers=_hdr()))
        for key in self.SELECTOR_KEYS:
            assert key in keys, key
