"""Раунд 10.24 (F8 `dead-extractor-paradigms-round1024`, ADR-1024-5).

Покрытие корневого бага «мёртвого экстрактора» и Empty State (spec §6):
  * (a) traits пишутся при наличии self-фактов даже когда парадигмы пусты
    (`no_anchors`/`unchanged`) — ранний return больше не пропускает traits;
  * (b) без self-фактов traits не генерируются, причина `no_self_facts`
    (без галлюцинаций), Empty State получает явный код;
  * (c) `persona_disabled`/`master_off` отражаются явно;
  * (d) парадигмы о пользователях пишутся с `target_user`; дедуп/идемпотентность;
  * (e) API отдаёт статус/причину лент (непустые/status-поля);
  * (f) `parse_bridge_answer` не теряет валидные элементы при частичном мусоре;
  * (g) ошибка записи/LLM видна в трассе, прогон не падает (fail-open);
  * kill-switch `DEEP_SLEEP_EXTRACT_FIX_ENABLED` возвращает прежний порядок.
"""
import asyncio
import json
import time

import pytest

from services import bot_persona
from services import chat_params as cp
from services import hot_config as hot
from services.database import DatabaseService
from services.dream_prompts import parse_bridge_answer
from services.dream_worker import DreamWorker

CHAT_ID = -100
_NOW = int(time.time())
_DAY = 86400


# ── фикстуры/моки ───────────────────────────────────────────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeMemory:
    _vec_available = False

    def __init__(self, anchors):
        self._anchors = list(anchors)

    async def get_rag_facts(self, chat_id, query):
        return list(self._anchors)


class _RoleLLM:
    """Роль-зависимый мок: history (парадигмы) / background (traits)."""

    def __init__(self, *, history='{"paradigms":[]}',
                 background="[]", error_role=None):
        self.history = history
        self.background = background
        self.error_role = error_role
        self.calls: list[str] = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append(role)
        if role == self.error_role:
            raise RuntimeError("llm down")
        if role == "history":
            return self.history
        if role == "background":
            return self.background
        return "[]"


def _old_anchor(fact, *, days=200, author=None):
    return ("chat_history", fact, _NOW - days * _DAY, author)


def _worker(db, memory, llm, *, values, monkeypatch):
    _hot_cache(monkeypatch, values)
    return DreamWorker(db, memory=memory, llm=llm)


async def _add_fact(db, text, origin="chat_history", importance=5):
    return await db.insert_graph_fact(CHAT_ID, text, origin, None,
                                      importance=importance)


def _patch_persona(monkeypatch):
    """Перехват записи traits (PG недоступен в unit-тестах)."""
    state = {"traits": [], "statuses": []}

    async def _append(traits, *, chat_id, source):
        state["traits"].extend(traits)
        return len(traits)

    async def _status(value):
        state["statuses"].append(value)

    monkeypatch.setattr(bot_persona, "append_traits", _append)
    monkeypatch.setattr(bot_persona, "record_trait_status", _status)
    return state


async def _fact_rows(db):
    cursor = await db.db.execute(
        "SELECT id, fact, origin, kind, target_user, belief_meta "
        "FROM graph_facts WHERE kind = 'belief' ORDER BY id")
    return await cursor.fetchall()


# ── (a) развязка traits от paradigms ────────────────────────────────────────

class TestTraitsIndependentFromParadigms:
    @pytest.mark.asyncio
    async def test_traits_run_on_no_anchors(self, db, monkeypatch):
        """Корневой баг: ранний return `no_anchors` больше не пропускает
        persona-блок — traits пишутся при наличии self-фактов."""
        await _add_fact(db, "свежий факт чата")
        await _add_fact(db, "бот решил пошутить", origin="bot_self_reply")
        state = _patch_persona(monkeypatch)
        llm = _RoleLLM(background='["стал чаще шутить"]')
        worker = _worker(db, _FakeMemory([]), llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "no_anchors"
        assert out["traits"] == 1
        assert state["traits"] == ["стал чаще шутить"]
        assert "background" in llm.calls

    @pytest.mark.asyncio
    async def test_traits_run_on_unchanged(self, db, monkeypatch):
        """`unchanged` (пустой ответ парадигм) тоже не блокирует traits."""
        await _add_fact(db, "свежий факт чата")
        await _add_fact(db, "бот решил молчать", origin="bot_self_reply")
        state = _patch_persona(monkeypatch)
        memory = _FakeMemory([_old_anchor("старый A"), _old_anchor("старый B")])
        llm = _RoleLLM(history='{"paradigms":[]}',
                       background='["стал спокойнее", "реже спорит"]')
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "unchanged"
        assert out["traits"] == 2
        assert state["traits"] == ["стал спокойнее", "реже спорит"]

    @pytest.mark.asyncio
    async def test_kill_switch_off_restores_old_order(self, db, monkeypatch):
        """`DEEP_SLEEP_EXTRACT_FIX_ENABLED=False` → прежний порядок: при
        `no_anchors` traits не запускаются."""
        await _add_fact(db, "свежий факт чата")
        await _add_fact(db, "бот решил пошутить", origin="bot_self_reply")
        state = _patch_persona(monkeypatch)
        # Kill-switch — env-only ClassVar; подменяем сам хелпер (устойчиво к
        # reload модуля настроек в общем прогоне).
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_extract_fix_enabled", lambda: False)
        llm = _RoleLLM(background='["стал чаще шутить"]')
        worker = _worker(db, _FakeMemory([]), llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "no_anchors"
        assert out["traits"] == 0
        assert state["traits"] == []


# ── (b) без self-фактов — без галлюцинаций, явная причина ───────────────────

class TestNoSelfFacts:
    @pytest.mark.asyncio
    async def test_no_self_facts_no_llm_and_reason(self, db, monkeypatch):
        await _add_fact(db, "обычный факт чата")     # не self-факт
        state = _patch_persona(monkeypatch)
        llm = _RoleLLM(background='["выдуманная черта"]')
        worker = _worker(db, _FakeMemory([]), llm, monkeypatch=monkeypatch,
                         values={})
        out = await worker._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "empty", "traits": 0}
        assert state["traits"] == []
        assert state["statuses"] == ["no_self_facts"]
        assert llm.calls == []            # без self-фактов LLM не вызывается

    @pytest.mark.asyncio
    async def test_step_returns_reason_when_disabled(self, db, monkeypatch):
        state = _patch_persona(monkeypatch)

        async def _off(chat_id, key, default=None):
            return False

        monkeypatch.setattr(cp, "get_chat_param", _off)
        worker = _worker(db, _FakeMemory([]), _RoleLLM(), monkeypatch=monkeypatch,
                         values={})
        written = await worker._run_persona_traits_step(CHAT_ID, _NOW)
        assert written == 0
        assert state["statuses"] == ["persona_disabled"]


# ── (e) API статусы/причины лент ────────────────────────────────────────────

class _ApiDb:
    def __init__(self, *, paradigms=None, log=None):
        self._paradigms = list(paradigms or [])
        self._log = list(log or [])

    async def list_recent_beliefs(self, **kwargs):
        return list(self._paradigms)

    async def count_paradigms(self):
        return len(self._paradigms)

    async def last_deep_run(self):
        return None

    async def count_dream_log(self, *a, **kw):
        return 0

    async def recent_dream_log(self, limit=50):
        return list(self._log)


class TestDeepSleepStatusApi:
    @pytest.mark.asyncio
    async def test_status_reason_master_off(self, monkeypatch):
        from web.api import memory_agi as ma
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _ApiDb())

        async def _with_source(key, *, chat_id=None, default=None):
            return False, "default"

        async def _cached(key, *, chat_id=None, default=None):
            return False

        monkeypatch.setattr(ma, "resolve_setting_with_source", _with_source)
        monkeypatch.setattr(ma, "resolve_setting_cached", _cached)
        data = await ma.deep_sleep_status(request=None, user=None,
                                          chat_id=CHAT_ID)
        assert data["paradigms_status"] == "empty"
        assert data["paradigms_reason"] == "master_off"
        assert data["deep_enabled"] is False
        assert data["master_enabled"] is False

    @pytest.mark.asyncio
    async def test_status_reason_from_last_skip(self, monkeypatch):
        from web.api import memory_agi as ma
        log = [{"id": 1, "chat_id": CHAT_ID, "run_at": _NOW,
                "kind": "deep_skip", "cluster_id": None, "source_ids": "[]",
                "belief_id": None, "tokens": 0, "status": "no_anchors"}]
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _ApiDb(log=log))

        async def _with_source(key, *, chat_id=None, default=None):
            return True, "default"

        async def _cached(key, *, chat_id=None, default=None):
            return True

        monkeypatch.setattr(ma, "resolve_setting_with_source", _with_source)
        monkeypatch.setattr(ma, "resolve_setting_cached", _cached)
        data = await ma.deep_sleep_status(request=None, user=None,
                                          chat_id=CHAT_ID)
        assert data["paradigms_status"] == "empty"
        assert data["paradigms_reason"] == "no_anchors"

    @pytest.mark.asyncio
    async def test_status_ok_when_paradigms_present(self, monkeypatch):
        from web.api import memory_agi as ma
        row = {"id": 1, "chat_id": CHAT_ID, "fact": "парадигма",
               "origin": "derived_belief", "status": "confirmed",
               "weight": 0.55, "importance": 3, "source_ids": "[]",
               "belief_meta": json.dumps({"type": "paradigm"}),
               "created_at": _NOW, "supersedes": None,
               "last_confirmed_at": None}
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _ApiDb(paradigms=[row]))

        async def _with_source(key, *, chat_id=None, default=None):
            return True, "default"

        async def _cached(key, *, chat_id=None, default=None):
            return True

        monkeypatch.setattr(ma, "resolve_setting_with_source", _with_source)
        monkeypatch.setattr(ma, "resolve_setting_cached", _cached)
        data = await ma.deep_sleep_status(request=None, user=None,
                                          chat_id=CHAT_ID)
        assert data["paradigms_status"] == "ok"
        assert data["paradigms_reason"] == "ok"
        assert data["paradigms"]


# ── (d) парадигмы о пользователях + дедуп ───────────────────────────────────

class TestParadigmsAboutUsers:
    @pytest.mark.asyncio
    async def test_paradigm_gets_target_user_and_dedup(self, db, monkeypatch):
        await _add_fact(db, "толян снова заказал литрбол", importance=6)
        await _add_fact(db, "бот решил пошутить", origin="bot_self_reply")
        _patch_persona(monkeypatch)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу", author="Толян"),
            _old_anchor("толян бросил пить в 2024"),
        ])
        ans = ('{"paradigms":[{"text":"Толян раньше пил, теперь спортсмен",'
               '"anchors":[1,2]}]}')
        llm = _RoleLLM(history=ans, background="[]")
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})
        first = await worker._run_deep_once(CHAT_ID, manual=True)
        assert first["paradigms"] == 1
        rows = await _fact_rows(db)
        assert len(rows) == 1
        # факт/парадигма о пользователе: target_user из автора якоря
        assert rows[0]["target_user"] == "Толян"
        assert rows[0]["origin"] == "derived_belief"
        meta = json.loads(rows[0]["belief_meta"])
        assert meta["type"] == "paradigm" and meta["dedup_key"]
        # повторный прогон идемпотентен (дедуп по dedup_key)
        second = await worker._run_deep_once(CHAT_ID, manual=True)
        assert second["paradigms"] == 0
        assert len(await _fact_rows(db)) == 1


# ── (g) fail-open: ошибка записи видна, прогон жив ──────────────────────────

class TestFailOpen:
    @pytest.mark.asyncio
    async def test_write_error_logged_not_raised(self, db, monkeypatch, caplog):
        import logging
        await _add_fact(db, "толян снова в деле", importance=6)
        _patch_persona(monkeypatch)
        memory = _FakeMemory([_old_anchor("толян A", author="Толян"),
                              _old_anchor("толян B")])
        ans = ('{"paradigms":[{"text":"Толян снова активен","anchors":[1,2]}]}')
        llm = _RoleLLM(history=ans)
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})

        async def _boom(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(worker, "_write_paradigm", _boom)
        with caplog.at_level(logging.WARNING):
            out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["paradigms"] == 0          # прогон не упал
        assert "paradigm write failed" in caplog.text

    @pytest.mark.asyncio
    async def test_llm_error_traits_fail_open(self, db, monkeypatch):
        await _add_fact(db, "бот решил пошутить", origin="bot_self_reply")
        state = _patch_persona(monkeypatch)
        llm = _RoleLLM(error_role="background")
        worker = _worker(db, _FakeMemory([]), llm, monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["traits"] == 0
        assert state["statuses"] == ["error"]


class TestPersonaTraitsMeta:
    """`/api/persona` аддитивные поля traits_status/traits_reason/self_facts."""

    @pytest.mark.asyncio
    async def test_no_self_facts_reason(self, monkeypatch):
        from web.api import routes
        from services import lore_runtime

        async def _health():
            return {"last_trait_status": "no_self_facts"}

        class _DB:
            async def get_dream_candidates(self, *a, **kw):
                return []

        monkeypatch.setattr(bot_persona, "get_persona_health", _health)
        monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: _DB())
        out = {"persona_enabled": True, "dynamic_traits": []}
        await routes._persona_traits_meta(out, chat_id=CHAT_ID)
        assert out["traits_status"] == "empty"
        assert out["traits_reason"] == "no_self_facts"
        assert out["self_facts_count"] == 0

    @pytest.mark.asyncio
    async def test_self_facts_present_uses_last_status(self, monkeypatch):
        from web.api import routes
        from services import lore_runtime

        async def _health():
            return {"last_trait_status": "ok"}

        class _DB:
            async def get_dream_candidates(self, *a, **kw):
                return [{"id": 1}]

        monkeypatch.setattr(bot_persona, "get_persona_health", _health)
        monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: _DB())
        out = {"persona_enabled": True, "dynamic_traits": []}
        await routes._persona_traits_meta(out, chat_id=CHAT_ID)
        assert out["traits_status"] == "ok"
        assert out["traits_reason"] == "ok"
        assert out["self_facts_count"] == 1

    @pytest.mark.asyncio
    async def test_persona_disabled_reason(self, monkeypatch):
        from web.api import routes

        async def _health():
            return {"last_trait_status": "never"}

        monkeypatch.setattr(bot_persona, "get_persona_health", _health)
        out = {"persona_enabled": False, "dynamic_traits": []}
        await routes._persona_traits_meta(out, chat_id=None)
        assert out["traits_status"] == "skip"
        assert out["traits_reason"] == "persona_disabled"

    @pytest.mark.asyncio
    async def test_db_error_is_fail_open(self, monkeypatch):
        from web.api import routes
        from services import lore_runtime

        async def _health():
            raise RuntimeError("pg down")

        monkeypatch.setattr(bot_persona, "get_persona_health", _health)
        monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
        out = {"persona_enabled": True, "dynamic_traits": []}
        await routes._persona_traits_meta(out, chat_id=CHAT_ID)
        assert out["traits_reason"] == "never"      # нейтрально, без 500


# ── (f) парсер не теряет валидные элементы ──────────────────────────────────

class TestParseKeepsValid:
    def test_partial_garbage_keeps_valid_items(self):
        raw = json.dumps({"paradigms": [
            "мусор-строка",
            {"text": "", "anchors": [1, 2]},
            {"text": "валидная", "anchors": [1, 2]},
            {"text": "без опор", "anchors": [99]},
            {"text": "ещё валидная", "anchors": ["x", 2, 1, 1]},
        ]})
        out = parse_bridge_answer(raw, anchor_count=2)
        assert out == [
            {"text": "валидная", "anchors": [1, 2]},
            {"text": "ещё валидная", "anchors": [2, 1]},
        ]


# ── настройки ───────────────────────────────────────────────────────────────

class TestFlag:
    def test_extract_fix_default_on_env_only(self):
        from config.settings import Settings
        from services import param_catalog as pc
        assert Settings().DEEP_SLEEP_EXTRACT_FIX_ENABLED is True
        # env-only ClassVar вне каталога настроек → Δ каталога = 0.
        assert pc.get("DEEP_SLEEP_EXTRACT_FIX_ENABLED") is None
