"""Раунд 10.13 (F3 `cognition-deep-sleep-round1013`) — «глубокий сон».

Покрытие (spec §2–§9, T-1435…T-1441):
  * канон «Мост времени» (`DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT`) + байт-тест +
    `build_bridge_user`/`parse_bridge_answer` (STRICT JSON, анти-галлюцинации);
  * расписание: after_sleep-хук после обычного сна, fixed-тик по local-часу,
    cooldown 20ч и суточный лимит 1 прогон;
  * «Поиск по якорям»: пакет (свежие beliefs + выжимка 12ч) → RAG, top-k cap,
    skip при < 2 исторических опорах (≥90 дней);
  * запись парадигмы (kind='belief', origin='derived_belief', weight=0.55,
    belief_meta.type='paradigm') + анти-дубли по dedup_key;
  * роутер `LLMClient.generate_worker`: dedicated / пусто → основная / ошибка
    dedicated → фоллбэк; R17 (ключ не логируется);
  * каталог-Δ + Settings-дефолты + DB-хелперы (last_deep_run/count_paradigms).
"""
import asyncio
import json
import time

import httpx
import pytest

import services.llm_client as llm_client
from config.settings import Settings
from services import hot_config as hot
from services import param_catalog as pc
from services.database import DatabaseService
from services.dream_prompts import (
    DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT,
    build_bridge_user,
    parse_bridge_answer,
)
from services.dream_worker import DreamWorker
from services.llm_client import LLMClient

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
        self.queries = []

    async def get_rag_facts(self, chat_id, query):
        self.queries.append((chat_id, query))
        return list(self._anchors)


class _FakeWorkerLLM:
    """Мок LLMClient: generate_worker (роль history) + generate (main)."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append((role, messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        self.calls.append(("main", messages, temperature))
        return '{"beliefs":[]}'


def _old_anchor(fact, *, days=200, author=None):
    return ("chat_history", fact, _NOW - days * _DAY, author)


def _worker(db, memory, llm, *, values, monkeypatch):
    _hot_cache(monkeypatch, values)
    return DreamWorker(db, memory=memory, llm=llm)


async def _add_fact(db, text, importance=5):
    return await db.insert_graph_fact(CHAT_ID, text, "chat_history", None,
                                      importance=importance)


async def _paradigm_rows(db):
    cursor = await db.db.execute(
        "SELECT id, fact, origin, kind, weight, importance, source_ids, "
        "belief_meta, status FROM graph_facts WHERE kind = 'belief' ORDER BY id")
    return await cursor.fetchall()


# ── T-1437: канон «Мост времени» ────────────────────────────────────────────

_BRIDGE_REFERENCE = """\
Ты - синтезатор долговременной памяти чата на этапе глубокого сна. Тебе дают
свежий контекст чата (недавние убеждения и выжимку активности за последние
часы) и подборку старых фактов из истории. Найди связь между текущими
событиями и историческими фактами и сформулируй мета-факт (парадигму) о
развитии ситуации или человека.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"paradigms":[{"text":"...","anchors":[<номера исторических фактов>]}]}
2. Парадигма - обобщение о ДИНАМИКЕ (что было раньше и что стало теперь),
   а не пересказ отдельного факта.
3. Каждая парадигма опирается минимум на 2 исторических факта; anchors - их
   номера из нумерованного списка.
4. Текст парадигмы до 200 символов, без кавычек-ёлочек и длинных тире.
5. Если связи нет или данных мало - верни {"paradigms":[]}.
"""


class TestBridgeCanon:
    def test_canon_byte_exact(self):
        assert DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT == _BRIDGE_REFERENCE

    def test_canon_no_quotes_and_dashes(self):
        for bad in ("«", "»", "—", "–"):
            assert bad not in DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT, bad

    def test_canon_contract(self):
        assert '"paradigms"' in DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT
        assert "минимум на 2" in DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT
        assert "ДИНАМИКЕ" in DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT

    def test_prompt_migrations_untouched(self):
        import inspect
        from services import prompt_migrations
        assert "deep_sleep" not in inspect.getsource(prompt_migrations).lower()


class TestBuildBridgeUser:
    def test_renders_context_and_numbered_anchors(self):
        packet = {"beliefs": [{"fact": "свежее убеждение"}],
                  "recent": [{"fact": "факт за 12ч"}]}
        historical = [_old_anchor("старый факт", days=200),
                      ("chat_history", "ещё старый", _NOW - 300 * _DAY, None)]
        text = build_bridge_user(packet, historical)
        assert "свежее убеждение" in text
        assert "факт за 12ч" in text
        lines = text.splitlines()
        assert any(ln.startswith("1. [") and "старый факт" in ln
                   for ln in lines)
        assert any(ln.startswith("2. [") and "ещё старый" in ln
                   for ln in lines)

    def test_empty_context_and_anchors(self):
        text = build_bridge_user({}, [])
        assert "свежих данных нет" in text
        assert "исторических фактов не найдено" in text


class TestParseBridgeAnswer:
    def test_valid(self):
        out = parse_bridge_answer(
            '{"paradigms":[{"text":"раньше пил, теперь спортсмен",'
            '"anchors":[1,2]}]}', anchor_count=3)
        assert out == [{"text": "раньше пил, теперь спортсмен",
                        "anchors": [1, 2]}]

    def test_empty_and_unchanged(self):
        for raw in ("UNCHANGED", " unchanged ", '{"paradigms":[]}',
                    '{"paradigms": []}'):
            assert parse_bridge_answer(raw, anchor_count=2) == []

    def test_bad_json_raises(self):
        for raw in ("", "не json", '{"no_paradigms":1}', "[1,2]"):
            with pytest.raises(ValueError):
                parse_bridge_answer(raw, anchor_count=2)

    def test_anchors_out_of_range_dropped(self):
        out = parse_bridge_answer(
            '{"paradigms":[{"text":"t","anchors":[1,99,2]}]}', anchor_count=2)
        assert out == [{"text": "t", "anchors": [1, 2]}]

    def test_single_anchor_paradigm_rejected(self):
        """ISSUE-3: минимум 2 исторические опоры (spec §4/промпт). Одна
        валидная опора → парадигма не пишется (анти-галлюцинации)."""
        assert parse_bridge_answer(
            '{"paradigms":[{"text":"т","anchors":[1]}]}',
            anchor_count=3) == []
        # явное ослабление (min_anchors=1) по-прежнему возможно
        assert parse_bridge_answer(
            '{"paradigms":[{"text":"т","anchors":[1]}]}',
            anchor_count=3, min_anchors=1) == [{"text": "т", "anchors": [1]}]

    def test_paradigm_without_valid_anchor_not_written(self):
        out = parse_bridge_answer(
            '{"paradigms":[{"text":"без опор","anchors":[9]},'
            '{"text":"ок","anchors":[1,2]}]}', anchor_count=2)
        assert out == [{"text": "ок", "anchors": [1, 2]}]


# ── T-1436/T-1438: «Поиск по якорям» + запись парадигмы ─────────────────────

class TestDeepSleepRun:
    @pytest.mark.asyncio
    async def test_paradigm_written_with_weight_and_meta(self, db, monkeypatch):
        await _add_fact(db, "толян снова заказал литрбол", importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил литрбол каждую пятницу", author="Толян"),
            _old_anchor("толян бросил пить в 2024"),
            _old_anchor("свежий факт", days=1),
        ])
        llm = _FakeWorkerLLM(
            '{"paradigms":[{"text":"Толян раньше пил, теперь спортсмен",'
            '"anchors":[1,2]}]}')
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True,
            "memory.deep_sleep_trigger": "after_sleep",
        })
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "ok" and out["paradigms"] == 1
        rows = await _paradigm_rows(db)
        assert len(rows) == 1
        row = rows[0]
        assert row["origin"] == "derived_belief"
        assert row["kind"] == "belief"
        assert abs(float(row["weight"]) - 0.55) < 1e-9
        meta = json.loads(row["belief_meta"])
        assert meta["type"] == "paradigm"
        assert meta["bridge"] is True
        assert meta["lookback_hours"] == 12
        assert meta["dedup_key"]
        assert len(meta["anchors"]) == 2
        assert row["status"] == "confirmed"
        # RAG-запрос ушёл именно в выделенный путь (roles history)
        assert memory.queries and memory.queries[0][0] == CHAT_ID
        assert llm.calls and llm.calls[0][0] == "history"

    @pytest.mark.asyncio
    async def test_duplicate_not_written_twice(self, db, monkeypatch):
        await _add_fact(db, "толян снова заказал литрбол", importance=6)
        memory = _FakeMemory([_old_anchor("толян пил каждую пятницу"),
                              _old_anchor("толян бросил пить")])
        ans = ('{"paradigms":[{"text":"Толян раньше пил, теперь спортсмен",'
               '"anchors":[1,2]}]}')
        llm = _FakeWorkerLLM(ans, ans)
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        first = await worker._run_deep_once(CHAT_ID, manual=True)
        second = await worker._run_deep_once(CHAT_ID, manual=True)
        assert first["paradigms"] == 1
        assert second["status"] == "duplicate"
        assert second["paradigms"] == 0
        assert len(await _paradigm_rows(db)) == 1

    @pytest.mark.asyncio
    async def test_skip_when_less_than_two_historical(self, db, monkeypatch):
        await _add_fact(db, "свежий факт чата", importance=5)
        memory = _FakeMemory([_old_anchor("один старый факт")])
        llm = _FakeWorkerLLM()
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "no_anchors"
        assert await _paradigm_rows(db) == []
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_top_k_cap_applied(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        # первые два кандидата — свежие; при top-k=2 исторические в выборку
        # не попадают, хотя в базе они есть (демонстрация cap).
        anchors = [_old_anchor("свежий A", days=1),
                   _old_anchor("свежий B", days=2)] + [
                       _old_anchor(f"старый {i}", days=200 + i)
                       for i in range(3)]
        memory = _FakeMemory(anchors)
        llm = _FakeWorkerLLM('{"paradigms":[]}')
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True,
            "limits.deep_sleep_top_k": 2,
        })
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "no_anchors"


# ── T-1435: расписание, cooldown, лимиты ────────────────────────────────────

class TestDeepSleepSchedule:
    @pytest.mark.asyncio
    async def test_after_sleep_hook_runs_deep(self, db, monkeypatch):
        memory = _FakeMemory([])
        worker = _worker(db, memory, _FakeWorkerLLM(),
                         monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True,
                                 "memory.deep_sleep_trigger": "after_sleep"})
        seen = {}

        async def _fake(chat_ids, *, since_ts=None, manual=False):
            seen["args"] = (list(chat_ids), since_ts, manual)
            return {"chats": len(chat_ids), "paradigms": 0, "ran": 0,
                    "skipped": 0}

        monkeypatch.setattr(worker, "_run_deep_all", _fake)
        worker._last_chat_ids = [CHAT_ID]
        worker._last_run_started = 111
        await worker._maybe_deep_after_sleep({"distilled": 1, "chats": 1})
        assert seen["args"] == ([CHAT_ID], 111, False)

    @pytest.mark.asyncio
    async def test_after_sleep_hook_off_when_flag_off(self, db, monkeypatch):
        worker = _worker(db, _FakeMemory([]), _FakeWorkerLLM(),
                         monkeypatch=monkeypatch, values={})
        called = {"n": 0}

        async def _fake(*a, **kw):
            called["n"] += 1
            return {}

        monkeypatch.setattr(worker, "_run_deep_all", _fake)
        worker._last_chat_ids = [CHAT_ID]
        await worker._maybe_deep_after_sleep({"distilled": 1, "chats": 1})
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_fixed_trigger_skips_after_sleep_hook(self, db, monkeypatch):
        worker = _worker(db, _FakeMemory([]), _FakeWorkerLLM(),
                         monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True,
                                 "memory.deep_sleep_trigger": "fixed"})
        called = {"n": 0}

        async def _fake(*a, **kw):
            called["n"] += 1
            return {}

        monkeypatch.setattr(worker, "_run_deep_all", _fake)
        worker._last_chat_ids = [CHAT_ID]
        await worker._maybe_deep_after_sleep({"distilled": 1, "chats": 1})
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_deep_tick_fixed_at_target_hour(self, db, monkeypatch):
        worker = _worker(db, _FakeMemory([]), _FakeWorkerLLM(),
                         monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True,
                                 "memory.deep_sleep_trigger": "fixed",
                                 "memory.deep_sleep_hour": 7})
        called = {"n": 0}

        async def _fake(*a, **kw):
            called["n"] += 1
            return {}

        monkeypatch.setattr(worker, "_run_deep_all", _fake)
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 7)
        await worker._deep_tick()
        assert called["n"] == 1
        monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 8)
        await worker._deep_tick()
        assert called["n"] == 1

    @pytest.mark.asyncio
    async def test_cooldown_blocks_non_manual(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        worker = _worker(db, _FakeMemory([]), _FakeWorkerLLM(),
                         monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})

        async def _count(*a, **kw):
            return 0

        async def _last(chat_id=None):
            return _NOW - 3600

        monkeypatch.setattr(worker.db, "count_deep_attempts", _count)
        monkeypatch.setattr(worker.db, "last_deep_attempt", _last)
        out = await worker._run_deep_once(CHAT_ID, manual=False)
        assert out["status"] == "cooldown"

    @pytest.mark.asyncio
    async def test_daily_limit_one_run(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        worker = _worker(db, _FakeMemory([]), _FakeWorkerLLM(),
                         monkeypatch=monkeypatch,
                         values={"flags.deep_sleep_enabled": True})

        async def _count(*a, **kw):
            return 1

        monkeypatch.setattr(worker.db, "count_deep_attempts", _count)
        out = await worker._run_deep_once(CHAT_ID, manual=False)
        assert out["status"] == "daily_limit"

    @pytest.mark.asyncio
    async def test_start_registers_deep_tick_when_flag_on(self, db,
                                                          monkeypatch):
        _hot_cache(monkeypatch, {"memory.dream_enabled": False,
                                 "flags.deep_sleep_enabled": True})
        worker = DreamWorker(db, memory=None, llm=_FakeWorkerLLM())
        try:
            worker.start()
            ids = {j.id for j in worker._scheduler.get_jobs()}
            assert "deep_sleep_tick" in ids
        finally:
            await worker.stop()


# ── T-1439: роутер выделенных моделей ───────────────────────────────────────

def _mock_client(handler, monkeypatch, **kwargs):
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient("https://api.test/v1", "main-key", "chat-model",
                       "embed-model", **kwargs)
    client.backoff_base = 0
    return client


class TestWorkerRouter:
    @pytest.mark.asyncio
    async def test_dedicated_history_model_used(self, monkeypatch, caplog):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "из истории"}}]},
                request=request)

        _hot_cache(monkeypatch, {
            "models.intel_history_base_url": "https://history.test/v1",
            "models.intel_history_model_name": "hist-model",
            "keys.intel_history_api_key": "hist-secret-key",
        })
        client = _mock_client(handler, monkeypatch)
        out = await client.generate_worker(
            "history", [{"role": "user", "content": "q"}], temperature=0.3)
        assert out == "из истории"
        assert seen["url"] == "https://history.test/v1/chat/completions"
        assert seen["auth"] == "Bearer hist-secret-key"
        assert seen["payload"]["model"] == "hist-model"
        assert seen["payload"]["temperature"] == 0.3
        # R17: ключ не должен попасть в логи
        assert "hist-secret-key" not in caplog.text

    @pytest.mark.asyncio
    async def test_empty_fields_fall_back_to_main(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "основная"}}]},
                request=request)

        _hot_cache(monkeypatch, {})
        client = _mock_client(handler, monkeypatch)
        out = await client.generate_worker(
            "background", [{"role": "user", "content": "q"}])
        assert out == "основная"
        assert seen["url"] == "https://api.test/v1/chat/completions"
        assert seen["auth"] == "Bearer main-key"

    @pytest.mark.asyncio
    async def test_dedicated_error_falls_back_to_main(self, monkeypatch):
        def handler(request):
            if "history.test" in str(request.url):
                return httpx.Response(500, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "основная"}}]},
                request=request)

        _hot_cache(monkeypatch, {
            "models.intel_history_base_url": "https://history.test/v1",
            "models.intel_history_model_name": "hist-model",
            "keys.intel_history_api_key": "hist-key",
        })
        client = _mock_client(handler, monkeypatch)
        out = await client.generate_worker(
            "history", [{"role": "user", "content": "q"}])
        assert out == "основная"

    @pytest.mark.asyncio
    async def test_dedicated_background_role_uses_bg_keys(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "фон"}}]},
                request=request)

        _hot_cache(monkeypatch, {
            "models.intel_bg_base_url": "https://bg.test/v1",
            "models.intel_bg_model_name": "bg-model",
            "keys.intel_bg_api_key": "bg-key",
        })
        client = _mock_client(handler, monkeypatch)
        out = await client.generate_worker(
            "background", [{"role": "user", "content": "q"}])
        assert out == "фон"
        assert seen["url"] == "https://bg.test/v1/chat/completions"
        assert seen["auth"] == "Bearer bg-key"
        assert seen["payload"]["model"] == "bg-model"

    @pytest.mark.asyncio
    async def test_unknown_role_raises(self, monkeypatch):
        _hot_cache(monkeypatch, {})
        client = _mock_client(_json_ok, monkeypatch)
        with pytest.raises(ValueError):
            await client.generate_worker("nope", [])


def _json_ok(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]},
                          request=request)


# ── T-1440/T-1442: каталог, Settings, DB-хелперы ────────────────────────────

class TestCatalogAndDb:
    def test_catalog_delta_and_defaults(self):
        settings = Settings()
        assert settings.DEEP_SLEEP_ENABLED is False
        assert settings.DEEP_SLEEP_TRIGGER == "after_sleep"
        assert settings.DEEP_SLEEP_HOUR == 7
        assert settings.DEEP_SLEEP_TOP_K == 20
        assert settings.DEEP_SLEEP_MAX_PARADIGMS == 3
        assert settings.DEEP_SLEEP_TOKENS_PER_DAY == 40000
        expected = {
            "flags.deep_sleep_enabled": pc.get("DEEP_SLEEP_ENABLED"),
            "memory.deep_sleep_trigger": pc.get("DEEP_SLEEP_TRIGGER"),
            "memory.deep_sleep_hour": pc.get("DEEP_SLEEP_HOUR"),
            "limits.deep_sleep_top_k": pc.get("DEEP_SLEEP_TOP_K"),
            "limits.deep_sleep_max_paradigms_per_run":
                pc.get("DEEP_SLEEP_MAX_PARADIGMS"),
            "limits.deep_sleep_tokens_per_day":
                pc.get("DEEP_SLEEP_TOKENS_PER_DAY"),
        }
        for pg_key, spec in expected.items():
            assert spec is not None, pg_key
            assert spec.pg_key == pg_key
            assert spec.group in ("flags_memory", "memory_dream",
                                  "limits_memory")

    def test_trigger_select_widget(self):
        spec = pc.get("DEEP_SLEEP_TRIGGER")
        assert spec.widget == "select"
        assert spec.select_options == ("after_sleep", "fixed")

    @pytest.mark.asyncio
    async def test_db_helpers_paradigms_and_last_run(self, db):
        pid = await db.insert_graph_fact(
            CHAT_ID, "парадигма", "derived_belief", None, weight=0.55,
            importance=3, kind="belief",
            belief_meta=json.dumps({"type": "paradigm", "dedup_key": "abc"}))
        await db.insert_graph_fact(CHAT_ID, "обычное убеждение",
                                   "derived_belief", None, kind="belief",
                                   belief_meta=json.dumps({"type": "belief"}))
        assert await db.count_paradigms() == 1
        assert await db.count_paradigms(CHAT_ID) == 1
        only_paradigms = await db.list_recent_beliefs(
            chat_id=CHAT_ID, belief_type="paradigm")
        assert [int(r["id"]) for r in only_paradigms] == [pid]
        only_beliefs = await db.list_recent_beliefs(
            chat_id=CHAT_ID, belief_type="belief")
        assert len(only_beliefs) == 1
        assert await db.last_deep_run() is None
        await db.log_dream_event(CHAT_ID, _NOW, kind="deep_run", tokens=10,
                                 status="ok")
        assert await db.last_deep_run(CHAT_ID) == _NOW
        assert await db.last_deep_run() == _NOW
        assert await db.sum_dream_log_tokens(0, kind="deep_run") == 10

    @pytest.mark.asyncio
    async def test_deep_attempt_markers_and_cost_counter(self, db):
        """S10.13-2: cooldown видит скип-попытки, но суточный лимит/кап
        считает только стоимостные прогоны (deep_run + токен-скипы)."""
        day = _NOW - _DAY
        await db.log_dream_event(CHAT_ID, day, kind="deep_skip", tokens=0,
                                 status="no_anchors")
        # пре-LLM скип: не стоит токенов → в лимит не входит, но cooldown
        assert await db.count_deep_attempts(0) == 0
        assert await db.last_deep_attempt(CHAT_ID) == day
        assert await db.last_deep_run(CHAT_ID) is None
        # скип, потративший токены (retry-ветка/unchanged) — стоимостной
        await db.log_dream_event(CHAT_ID, day + 10, kind="deep_skip",
                                 tokens=500, status="unchanged")
        assert await db.count_deep_attempts(0) == 1
        # успешный прогон
        await db.log_dream_event(CHAT_ID, day + 20, kind="deep_run",
                                 tokens=300, status="ok")
        assert await db.count_deep_attempts(0) == 2
        assert await db.last_deep_attempt(CHAT_ID) == day + 20
        assert await db.last_deep_run(CHAT_ID) == day + 20

    @pytest.mark.asyncio
    async def test_token_cap_counts_skip_tokens(self, db, monkeypatch):
        """S10.13-2: токен-кап глубокого сна суммирует и deep_skip — иначе
        error/unchanged/duplicate обходили суточный лимит 40000."""
        _hot_cache(monkeypatch, {"limits.deep_sleep_tokens_per_day": 100})
        worker = DreamWorker(db, memory=None, llm=_FakeWorkerLLM())
        await db.log_dream_event(CHAT_ID, _NOW, kind="deep_skip", tokens=80,
                                 status="unchanged")
        # estimate_tokens("x"*200) = 50 → 80 + 50 > 100 → отказ
        assert await worker._deep_budget_ok(CHAT_ID, "x" * 200) is False


# ── S10.13-10: probe зеркалит runtime-фолбэк выделенных LLM ─────────────────

class TestProbeIntelFallback:
    def test_intel_probe_fallback_fills_main(self, monkeypatch):
        from services import llm_probe

        _hot_cache(monkeypatch, {
            "models.llm_base_url": "https://main.test/v1",
            "models.llm_model_name": "main-model",
        })
        base, model = llm_probe._intel_probe_fallback(
            "intel_history_main", "", "")
        assert base == "https://main.test/v1"
        assert model == "main-model"

    def test_intel_probe_fallback_keeps_explicit(self):
        from services import llm_probe
        base, model = llm_probe._intel_probe_fallback(
            "intel_background_main", "https://bg.test/v1", "bg-model")
        assert base == "https://bg.test/v1"
        assert model == "bg-model"

    def test_non_intel_block_untouched(self):
        from services import llm_probe
        assert llm_probe._intel_probe_fallback(
            "direct_main", "", "") == ("", "")

    @pytest.mark.asyncio
    async def test_probe_block_uses_fallback(self, monkeypatch):
        from services import llm_probe
        seen = {}

        async def _fake_probe(base_url, api_key="", model="", kind="chat",
                              timeout=None):
            seen.update(base=base_url, model=model)
            return {"ok": True, "status": "ok", "http_status": 200,
                    "latency_ms": 1}

        monkeypatch.setattr(llm_probe, "probe_openai", _fake_probe)
        monkeypatch.setattr(llm_probe, "_saved_api_key", lambda block: "k")
        monkeypatch.setattr(
            llm_probe, "_intel_probe_fallback",
            lambda block, base, model: ("https://main.test/v1", "main-model"))
        out = await llm_probe.probe_block("intel_history_main")
        assert out["ok"] is True
        assert seen == {"base": "https://main.test/v1", "model": "main-model"}
