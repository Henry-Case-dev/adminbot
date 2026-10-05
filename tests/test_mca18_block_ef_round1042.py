"""MCA-18 `mca-18-self-model` — focused-тесты блоков E+F (T-5084…T-5088).

Покрытие (ADR-1028-18 D7/D8/D10; §28.6 `:1578–1588`, §28.1 `:1507–1509`,
§28.5 `:1576`):
  * T-5084: фоновый идемпотентный разбор `persona_traits` (K3; manual →
    подтверждена, deep_sleep → candidate/`legacy_unverified`; повтор =
    no-op по `legacy_ref`; FIFO persona_traits не теряет наблюдение;
    chat→global не выполняется; PG down → честный failed);
  * T-5087: ошибки чтения черт ≠ тихая пустота (F-3: warning + событие);
  * T-5088: fallback PG down → last-known-good со stale-маркером (TTL) или
    минимальная тех-идентичность; НЕ тихий ON; honest reason-коды;
  * T-5086: процесс `self.model` v1 в реестре (8 стадий) + честный
    disabled; payload/UI-компакт;
  * T-5085: маршруты /api/persona/self-model + rules (pause/resume/
    sources) — правка владельца = основание; K1 OFF → 409.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from services import bot_persona, lore_runtime, mca_events, mca_gates
from services import mca_self_model as sm
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT = -100500
AGENT = "agent-uuid-fixed"


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def events(monkeypatch):
    recorded: list = []

    def _fake(name, **kw):
        recorded.append((name, kw))
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _fake)
    return recorded


@pytest.fixture
def db(tmp_path, monkeypatch):
    async def _make():
        d = DatabaseService(str(tmp_path / "mca18_ef.db"))
        await d.initialize()
        await d.rebind_self_identity(bot_user_id=4242, note="test")
        await d.db.execute("UPDATE mca_self_identity SET agent_id = ? "
                           "WHERE id = true", (AGENT,))
        await d.db.commit()
        return d

    loop = asyncio.new_event_loop()
    try:
        d = loop.run_until_complete(_make())
    finally:
        loop.close()
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: d)
    yield d
    loop2 = asyncio.new_event_loop()
    try:
        loop2.run_until_complete(d.close())
    finally:
        loop2.close()


# ═══ T-5084: legacy-разбор persona_traits ═══════════════════════════════════

class _LegacyConn:
    """PG-стаб: persona_traits с ручной и «сонной» чертами."""

    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        if "persona_traits" in sql:
            return self._rows
        return []


class _LegacyPool:
    def __init__(self, rows):
        self._conn = _LegacyConn(rows)

    def acquire(self):
        pool = self

        class _CM:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


def _pool_patch(monkeypatch, rows):
    pool = _LegacyPool(rows)
    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: pool)
    return pool


@pytest.mark.asyncio
async def test_legacy_parse_manual_verified_and_sleep_unverified(
        db, events, monkeypatch):
    _pool_patch(monkeypatch, [
        {"id": 1, "chat_id": None, "trait": "любит точные формулировки",
         "source": "manual", "created_at": 1_700_000_000},
        {"id": 2, "chat_id": CHAT, "trait": "отвечает с иронией",
         "source": "deep_sleep", "created_at": 1_700_000_100},
    ])
    monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))
    stats = await sm.run_legacy_traits_parse(db)
    assert stats["status"] == "ok"
    assert stats["parsed"] == 2
    assert stats["unverified"] == 1
    # Ручная черта: subject self доказан → активна сразу (dimension в наборе
    # отсутствует → НЕприведённый кандидат; исполняемого правила нет).
    assert await db.list_behavior_rules(AGENT, "active") == []
    # Deep sleep legacy: без доказанного субъекта → НЕприведённый кандидат
    # (observation-носитель; правил с NULL dimension не создаётся —
    # rules.dimension NOT NULL по санкции §8.1). Событие честное (A62).
    assert await db.list_behavior_rules(AGENT, "candidate") == []
    assert any(kw.get("reason_code") == "legacy_trait_unverified"
               for _, kw in events)
    # История сохранена: original ID в legacy_ref, текст дословный.
    cur = await db.db.execute(
        "SELECT legacy_ref, raw_text FROM mca_trait_observations "
        "ORDER BY id")
    rows = await cur.fetchall()
    assert [r["legacy_ref"] for r in rows] == [1, 2]
    assert rows[1]["raw_text"] == "отвечает с иронией"


@pytest.mark.asyncio
async def test_legacy_parse_idempotent_repeat_noop(db, monkeypatch, events):
    rows = [{"id": 7, "chat_id": CHAT, "trait": "шутит про грибы",
             "source": "deep_sleep", "created_at": 1_700_000_200}]
    _pool_patch(monkeypatch, rows)
    monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))
    first = await sm.run_legacy_traits_parse(db)
    assert first["parsed"] == 1
    second = await sm.run_legacy_traits_parse(db)
    assert second["parsed"] == 0 and second["skipped"] == 1   # no-op
    cur = await db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_trait_observations")
    assert (await cur.fetchone())["c"] == 1                    # без дублей


@pytest.mark.asyncio
async def test_legacy_parse_fifo_does_not_lose_observation(db, monkeypatch):
    """FIFO persona_traits (cap=1) не удаляет наблюдение: raw хранится
    дословно в observation (провенанс-ссылка переживает ротацию)."""
    _pool_patch(monkeypatch, [
        {"id": 11, "chat_id": CHAT, "trait": "черта один",
         "source": "deep_sleep", "created_at": 1},
        {"id": 12, "chat_id": CHAT, "trait": "черта два",
         "source": "deep_sleep", "created_at": 2},
    ])
    await sm.run_legacy_traits_parse(db)
    # Ротация persona_traits: остаётся только свежая строка (поведение
    # существующего `_ROTATE_TRAITS_SQL`).
    pool = bot_persona._persona_pool()
    pool._conn._rows = [pool._conn._rows[-1]]
    cur = await db.db.execute(
        "SELECT raw_text, legacy_ref FROM mca_trait_observations "
        "ORDER BY legacy_ref")
    kept = await cur.fetchall()
    assert [r["raw_text"] for r in kept] == ["черта один", "черта два"]


@pytest.mark.asyncio
async def test_legacy_parse_k3_off_and_pg_down(db, monkeypatch, events):
    monkeypatch.setattr(mca_gates, "legacy_traits_migration_enabled",
                        lambda: False)
    stats = await sm.run_legacy_traits_parse(db)
    assert stats["status"] == "disabled"
    assert any(kw.get("reason_code") == "self_model_disabled"
               for _, kw in events)
    monkeypatch.setattr(mca_gates, "legacy_traits_migration_enabled",
                        lambda: True)
    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: None)
    stats = await sm.run_legacy_traits_parse(db)
    assert stats["status"] == "pg_unavailable"
    assert any(kw.get("reason_code") == "self_model_unavailable"
               for _, kw in events)


# ═══ T-5087: ошибки чтения ≠ тихая пустота (F-3) ════════════════════════════

@pytest.mark.asyncio
async def test_get_traits_failure_event_not_silent(db, events, monkeypatch):
    class _BrokenConn:
        async def fetch(self, sql, *args):
            raise RuntimeError("pg gone")

        async def fetchrow(self, sql, *args):
            return {"is_aware_ai": 1}

    class _BrokenPool:
        def acquire(self):
            conn = _BrokenConn()

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _BrokenPool())
    rows = await bot_persona.get_traits(10)
    assert rows == []                      # fail-open, НО видно:
    assert any(kw.get("stage") == "observation_read"
               and kw.get("reason_code") == "self_model_unavailable"
               for _, kw in events)


# ═══ T-5088: fallback (PG down → LKG stale / минимальная идентичность) ══════

def _patch_personas_ok(monkeypatch):
    """PG personas жив (is_aware_ai=1, global)."""

    class _Conn:
        async def fetchrow(self, sql, *args):
            return {"is_aware_ai": 1}

    class _Pool:
        def acquire(self):
            conn = _Conn()

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _Pool())


def _patch_personas_down(monkeypatch):
    monkeypatch.setattr(bot_persona, "_persona_pool", lambda: None)


@pytest.mark.asyncio
async def test_fallback_minimal_identity_and_lkg_stale(db, events,
                                                       monkeypatch):
    sm.lkg_invalidate()
    # 1) PG жив → обычный snapshot; LKG сохранён.
    _patch_personas_ok(monkeypatch)
    snap = await sm.resolve_self_model(db, CHAT)
    assert snap.stale is False and snap.fallback == ""
    # 2) PG упал, LKG свежий → тот же снимок со stale-маркером.
    _patch_personas_down(monkeypatch)
    snap2 = await sm.resolve_self_model(db, CHAT)
    assert snap2.stale is True and snap2.fallback == "lkg"
    assert snap2.version == snap.version
    assert any(kw.get("reason_code") == "self_model_stale"
               for _, kw in events)
    # 3) TTL=0 (без устаревания нельзя) → LKG просрочен → минимальная
    # тех-идентичность; НЕ тихий ON (честный reason).
    monkeypatch.setattr(mca_gates, "self_model_fallback_ttl_seconds",
                        lambda: 0)
    snap3 = await sm.resolve_self_model(db, CHAT)
    assert snap3.stale is True and snap3.fallback == "minimal"
    assert snap3.traits == () and snap3.positions == ()
    assert snap3.self_presentation_mode == sm.MODE_IN_CHARACTER
    assert any(kw.get("reason_code") == "self_model_unavailable"
               for _, kw in events)
    sm.lkg_invalidate()


@pytest.mark.asyncio
async def test_fallback_never_reports_success_persona(db, events,
                                                      monkeypatch):
    """Fallback НИКОГДА не репортится как «успешно загруженная персона»."""
    sm.lkg_invalidate()
    _patch_personas_down(monkeypatch)
    snap = await sm.resolve_self_model(db, CHAT)
    assert snap.fallback == "minimal"
    stage_events = [kw for _, kw in events
                    if kw.get("stage") == "resolve"]
    assert all(kw.get("outcome") != "success" for kw in stage_events
               if kw.get("reason_code") in ("self_model_unavailable",
                                            "self_model_stale"))


# ═══ T-5085/T-5086: маршруты UI + реестр ════════════════════════════════════

def _make_client(monkeypatch):
    """TestClient с lifespan (with): startup грузит роли в ConfigCache —
    без `with` RBAC-кэш пуст (403). Возвращает ctx-mgr → (client, headers)."""
    import hashlib
    import hmac
    import time as _time
    import types
    import urllib.parse
    from contextlib import contextmanager
    from services.config_cache import ConfigCache
    from web.app import create_app
    from web.api import deps as deps_mod

    token = "123456:TEST_TOKEN_FOR_MCA18_UI"
    admin_id = 5885953495

    def make_init_data() -> str:
        fields = {
            "auth_date": str(int(_time.time())),
            "query_id": "AAHkFg",
            "user": json.dumps({"id": admin_id, "first_name": "A"},
                               separators=(",", ":")),
        }
        data_check = "\n".join(f"{k}={v}"
                               for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(),
                          hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(),
                        hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(sorted(fields.items())) + \
            f"&hash={calc}"

    class _Conn:
        async def execute(self, sql, *args):
            return "INSERT 0 1"

        async def fetchrow(self, sql, *args):
            return None

        async def fetch(self, sql, *args):
            if "bot_roles" in sql:
                return [{"role_name": "admin",
                         "permissions": {"wildcard": True},
                         "is_custom": False}]
            if "bot_admins" in sql:
                return [{"telegram_id": admin_id, "role_name": "admin",
                         "added_by": None, "created_at": None}]
            return []

    class _Pool:
        def acquire(self):
            conn = _Conn()

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    class _Pg:
        def __init__(self):
            self.pool = _Pool()

        async def connect(self):
            pass

        async def init(self, seed_settings=True):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=token))
    cache = ConfigCache(pg=_Pg(), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    hdr = {"X-Telegram-Init-Data": make_init_data()}

    @contextmanager
    def _ctx():
        with TestClient(app) as client:
            yield client, hdr

    return _ctx()


@pytest.mark.asyncio
async def test_ui_self_model_routes(db, monkeypatch):
    with _make_client(monkeypatch) as (client, hdr):
        resp = client.get("/api/persona/self-model", headers=hdr)
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["stages"] == ["observation_read", "attribution",
                                  "candidate_compile", "validation",
                                  "activation", "selection", "prompt_render",
                                  "final_check"]
        assert body["widget_id"] == "Что сейчас формирует характер"
        assert set(body["explanations"]) == {
            "persona_enabled", "is_aware_ai", "bot_self_awareness_enabled"}
        # Три статуса переключателя различимы в payload.
        assert body["switches"]["persona_enabled"]["source"] in (
            "default", "chat", "global")
        # Пауза несуществующего → 404; sources несуществующего — тоже 404
        # (M-1 rework: основания только у своего правила, чужие не отдаются).
        r = client.post("/api/persona/rules/999/pause", headers=hdr)
        assert r.status_code == 404
        r = client.post("/api/persona/rules/999/resume", headers=hdr)
        assert r.status_code == 404
        r = client.get("/api/persona/rules/999/sources", headers=hdr)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_ui_pause_resume_flow(db, monkeypatch):
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="резче в спорах", source_refs=("fact:1",),
        subject_status="self", chat_id=CHAT, dimension="резкость")
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    assert rule_id is not None
    with _make_client(monkeypatch) as (client, hdr):
        r = client.post(f"/api/persona/rules/{rule_id}/pause", headers=hdr)
        assert r.status_code == 200
    assert await db.list_behavior_rules(AGENT, "suspended")
    # Приостановленное не участвует в кадре.
    snap = await sm.resolve_self_model(db, CHAT)
    assert snap.traits == ()
    with _make_client(monkeypatch) as (client, hdr):
        r = client.post(f"/api/persona/rules/{rule_id}/resume", headers=hdr)
        assert r.status_code == 200
    assert await db.list_behavior_rules(AGENT, "active")


@pytest.mark.asyncio
async def test_ui_routes_k1_off_409(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: False)
    with _make_client(monkeypatch) as (client, hdr):
        r = client.get("/api/persona/self-model", headers=hdr)
        assert r.status_code == 200
        assert r.json()["enabled"] is False       # честный disabled
        r = client.post("/api/persona/rules/1/pause", headers=hdr)
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_resolve_character_context_frame_path(db, monkeypatch,
                                                    events):
    """Шов `:368`: K1 ON → один snapshot+frame на запуск, holder установлен,
    компилированные инструкции в ctx.traits; версия кадра — в ctx."""
    _patch_personas_ok(monkeypatch)

    async def _persona(chat_id):
        return bot_persona.BotPersona(name="Костик", biography="кот",
                                      overrides="", is_aware_ai=True,
                                      is_global=True)
    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _persona)
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="резче в спорах", source_refs=("fact:1",),
        subject_status="self", chat_id=CHAT, dimension="резкость")
    await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    ctx = await bot_persona.resolve_character_context(CHAT)
    assert ctx.frame_version is not None
    assert any("Ты отвечаешь резче" in t for t in ctx.traits)
    # Точка сборки рендерит из кадра (I-1: один кадр на запуск).
    persona = await bot_persona.resolve_bot_persona(CHAT)
    block = bot_persona.build_persona_prompt_block(persona, list(ctx.traits),
                                                   enabled=True)
    assert "Правила характера" in block
    assert "Ты отвечаешь резче" in block
    assert "<Persona>" in block


@pytest.mark.asyncio
async def test_resolve_character_context_legacy_on_error(db, monkeypatch,
                                                         events):
    """Ошибка frame-пути → честное событие + legacy-рендер (промпт жив)."""
    async def _boom(db_, scope):
        raise RuntimeError("boom")
    monkeypatch.setattr(sm, "resolve_self_model", _boom)
    ctx = await bot_persona.resolve_character_context(CHAT)
    assert ctx.frame_version is None
    assert any(kw.get("reason_code") == "self_model_snapshot_error"
               for _, kw in events)
    # K1 OFF → legacy целиком (нет frame-попыток).
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: False)
    mca_events.reset_pending()
    events.clear()
    ctx = await bot_persona.resolve_character_context(CHAT)
    assert ctx.frame_version is None
    assert not events


# ═══ Rework H-2 (T-5091): сквозной прод-путь сна → правило → кадр → tag ════

class _DreamDb:
    """Мини-стаб dream-воркера: кандидаты с id, учёт токенов (как
    `test_dream_persona_traits`), без PG."""

    def __init__(self, facts):
        self.facts = list(facts)
        self.events: list = []

    async def get_dream_candidates(self, chat_id, now_ts, *, origins,
                                   since_id=0, since_ts=None, limit=1000):
        return list(self.facts)

    async def list_recent_beliefs(self, chat_id=None, limit=50, status=None,
                                  belief_type=None):
        return []

    async def sum_dream_log_tokens(self, since_ts, kind=None):
        return 0

    async def log_dream_event(self, chat_id, run_at, *, kind, tokens=0,
                              status=None, **kwargs):
        self.events.append((kind, int(tokens), status))
        return len(self.events)


class _DreamLLM:
    def __init__(self, raw):
        self.raw = raw
        self.calls: list = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append((role, messages))
        return self.raw


def _patch_traits_write(monkeypatch):
    async def _append(traits, *, chat_id, source):
        return len(traits)

    async def _status(value):
        return None

    monkeypatch.setattr(bot_persona, "append_traits", _append)
    monkeypatch.setattr(bot_persona, "record_trait_status", _status)


async def _dream_run(db, monkeypatch, facts, raw):
    """Один прод-прогон `_run_persona_traits_once` с реальным lore-db."""
    _patch_traits_write(monkeypatch)
    _patch_personas_ok(monkeypatch)
    monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))
    worker = DreamWorker(db=_DreamDb(facts), memory=None, llm=_DreamLLM(raw))
    return await worker._run_persona_traits_once(CHAT)


@pytest.mark.asyncio
async def test_sleep_observation_to_active_rule_frame_and_tag(db, monkeypatch,
                                                              events):
    """H-2 (rework, pre-fix RED): сон → пары «text, dimension» → активное
    правило → кадр содержит инструкцию → ответ под чертой получает rule-tag
    (mca-22 ledger, A60/A61)."""
    out = await _dream_run(
        db, monkeypatch, [{"id": 101, "fact": "[Бот] отвечал кратко"}],
        '[{"text": "отвечает кратко, только суть", "dimension": "краткость"}]')
    assert out["status"] == "ok" and out["traits"] == 1
    rules = await db.list_behavior_rules(AGENT, "active")
    assert len(rules) == 1 and rules[0]["dimension"] == "краткость"
    assert rules[0]["scope"] == "chat"
    rule_id, version = rules[0]["id"], rules[0]["version"]
    # Кадр запуска содержит компилированную инструкцию (2-е лицо).
    ctx = await bot_persona.resolve_character_context(CHAT)
    assert any(sm.DIMENSION_INSTRUCTIONS["краткость"] in t
               for t in ctx.traits)
    persona = bot_persona.BotPersona(name="Костик", is_aware_ai=True,
                                     is_global=True)
    block = bot_persona.build_persona_prompt_block(
        persona, list(ctx.traits), enabled=True)
    assert "Ты отвечаешь короче обычного" in block
    # Маркировка ответа под чертой (mca-22 ledger source_feature).
    assert sm.current_run_frame_tag() == sm.rule_tag(rule_id, version)
    # dimension=null (наблюдение не отнесено) → кандидат без правила.
    out2 = await _dream_run(
        db, monkeypatch, [{"id": 102, "fact": "[Бот] что-то ещё"}],
        '[{"text": "непонятная черта без класса", "dimension": null}]')
    assert out2["status"] == "ok"
    assert len(await db.list_behavior_rules(AGENT, "active")) == 1  # без роста


@pytest.mark.asyncio
async def test_sleep_reinforce_only_independent_observation(db, monkeypatch,
                                                            events):
    """A61 live-path: повторное независимое наблюдение → bounded reinforce;
    свой ответ под этой чертой — НЕ подкрепление; тот же эпизод — дедуп."""
    await _dream_run(
        db, monkeypatch, [{"id": 103, "fact": "[Бот] отвечал кратко"}],
        '[{"text": "отвечает кратко, только суть", "dimension": "краткость"}]')
    rules = await db.list_behavior_rules(AGENT, "active")
    rule_id = rules[0]["id"]
    assert rules[0]["target_value"] is None and rules[0]["version"] == 1
    # 2) Свой ответ под чертой (ledger помечен) → подкрепления НЕТ.
    fid = await db.save_typed_fact(chat_id=CHAT, fact="суть моего ответа",
                                   origin="bot_self_reply")
    await db.db.execute(
        "UPDATE graph_facts SET tg_message_id = 777 WHERE id = ?", (fid,))
    await db.db.execute(
        "INSERT INTO mca_bot_outputs (chat_id, tg_message_id, output_kind, "
        "source_feature, delivery_status, created_at) VALUES "
        "(?, 777, 'direct_reply', ?, 'delivered', 1)",
        (CHAT, f"direct_chat|{sm.rule_tag(rule_id, 1)}"))
    await db.db.commit()
    await _dream_run(
        db, monkeypatch, [{"id": fid, "fact": "суть моего ответа"}],
        '[{"text": "отвечает кратко, только суть", '
        '"dimension": "краткость"}]')
    rules = await db.list_behavior_rules(AGENT, "active")
    assert rules[0]["version"] == 1 and rules[0]["target_value"] is None
    # 3) Новое независимое наблюдение → шаг ≤0.1/цикл, version+1.
    await _dream_run(
        db, monkeypatch, [{"id": 104, "fact": "принял новую манеру"}],
        '[{"text": "отвечает кратко, только суть", "dimension": "краткость"}]')
    rules = await db.list_behavior_rules(AGENT, "active")
    assert rules[0]["version"] == 2
    assert rules[0]["target_value"] == pytest.approx(0.1)
    # 4) Тот же эпизод (refs) → дедуп: повторного шага нет.
    await _dream_run(
        db, monkeypatch, [{"id": 104, "fact": "принял новую манеру"}],
        '[{"text": "отвечает кратко, только суть", "dimension": "краткость"}]')
    rules = await db.list_behavior_rules(AGENT, "active")
    assert rules[0]["version"] == 2
    assert rules[0]["target_value"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_legacy_manual_mapped_dimension_becomes_active(db, monkeypatch,
                                                            events):
    """H-2: legacy manual-черта с распознанным dimension активируется;
    нераспознанный текст остаётся кандидатом с причиной."""
    _pool_patch(monkeypatch, [
        {"id": 21, "chat_id": CHAT, "trait": "отвечает кратко, только суть",
         "source": "manual", "created_at": 1_700_000_000},
        {"id": 22, "chat_id": CHAT, "trait": "любит точные формулировки",
         "source": "manual", "created_at": 1_700_000_100},
    ])
    monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))
    stats = await sm.run_legacy_traits_parse(db)
    assert stats["status"] == "ok" and stats["parsed"] == 2
    active = await db.list_behavior_rules(AGENT, "active")
    assert [r["dimension"] for r in active] == ["краткость"]
    cur = await db.db.execute(
        "SELECT trait.dimension, trait.legacy_ref FROM mca_trait_observations "
        "trait ORDER BY legacy_ref")
    rows = await cur.fetchall()
    assert [r["legacy_ref"] for r in rows] == [21, 22]
    assert sm.infer_dimension("отвечает кратко, только суть") == "краткость"
    assert sm.infer_dimension("любит точные формулировки") is None


# ═══ Rework M-1: sources фильтруются по правилу ═════════════════════════════

@pytest.mark.asyncio
async def test_ui_rule_sources_filtered_by_rule(db, monkeypatch):
    oid_a = await sm.record_trait_observation(
        db, agent_id=AGENT, text="резче в спорах", source_refs=("fact:1",),
        subject_status="self", chat_id=CHAT, dimension="резкость")
    rule_id, _ = await sm.promote_observation(db, oid_a, scope_chat_id=CHAT)
    oid_b = await sm.record_trait_observation(
        db, agent_id=AGENT, text="короче в ответах", source_refs=("fact:2",),
        subject_status="self", chat_id=CHAT, dimension="краткость")
    await sm.promote_observation(db, oid_b, scope_chat_id=CHAT)
    with _make_client(monkeypatch) as (client, hdr):
        r = client.get(f"/api/persona/rules/{rule_id}/sources", headers=hdr)
        assert r.status_code == 200
        body = r.json()
    assert body["dimension"] == "резкость"
    assert body["source_observation_ids"] == [oid_a]
    assert [o["id"] for o in body["observations"]] == [oid_a]   # без чужих
    with _make_client(monkeypatch) as (client, hdr):
        r = client.get("/api/persona/rules/999/sources", headers=hdr)
        assert r.status_code == 404                              # M-1: не 200
