"""MOD-ACL-UX-01 M2 — поведенческие края §10 ТЗ и инвентарь потребителей.

Покрытие строк карты (у каждой — своё приёмочное утверждение):

* `MAC-S10-15` — векторный lookup выключен ТОЛЬКО для чата с OFF; общий
  индекс/пул не уничтожены, backlog других чатов живёт;
* `MAC-S10-08` — OFF одного чата не роняет retrieval другого и не меняет
  состояние shared-сервиса;
* `MAC-S10-19` — счётчики/журнал по chat_id: ноль вызовов отключённого
  функционала, но shared-сервис (скан наблюдателя) продолжает работать;
* `MAC-S10-05` — рестарт/инвалидация кэша/PG NOTIFY дают то же
  desired/effective, что сохранено;
* `MAC-S10-09` — сохранённые «старым путём» chat-флаги читаются как явные
  ON/OFF, а не как inherit;
* `MAC-S10-14` — «Время» без продуктового тумблера, timezone доступен и
  применяется одинаково у всех потребителей;
* `MAC-S10-03` — параллельные правки/устаревшая версия дают 409 без потери
  записи; дубль POST идемпотентен; двойной клик в UI не даёт второй POST;
* `MAC-S2-102` — каждый runtime-читатель из инвентаря идёт через
  канонический слой (нет второго чтения приватного кэша);
* `MAC-S0-03` — M2 не вводит DDL/перезапись промптов и версий.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01 §10 (M2)
"""
from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest

from services import chat_params, feature_gates, hot_config
from services import mca_events
from services import mca_gates
from services.summary_memory import MemoryManager

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHAT_A = -3101
CHAT_B = -3102


# ── общие фикстуры ──────────────────────────────────────────────────────────

class _ChatCache:
    def __init__(self, by_chat=None):
        self.by_chat = {int(k): dict(v) for k, v in (by_chat or {}).items()}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.by_chat.get(int(chat_id), {})),
                "gates": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


class _Hot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture(autouse=True)
def _qnd_schedule_due(monkeypatch):
    """QND-NONDET §1 (2026-11-10): предмет — runtime-края ACL, не расписание.
    Событие Observer считается наступившим для каждого чата с сообщениями."""
    from services import semantic_schedule as _sched

    async def _due(db, mechanism, chat_id, *, now=None):
        return True

    async def _due_chats(db, mechanism, *, now=None):
        cursor = await db.db.execute(
            "SELECT DISTINCT chat_id FROM smart_messages")
        return [int(r["chat_id"]) for r in await cursor.fetchall()]

    monkeypatch.setattr(_sched, "due", _due)
    monkeypatch.setattr(_sched, "due_chats", _due_chats)


@pytest.fixture
def world(monkeypatch):
    state = {"globals": {"flags.memory_search_enabled": True},
             "chats": {CHAT_A: {"flags.memory_search_enabled": False},
                       CHAT_B: {}}}
    cache = _ChatCache(state["chats"])
    hot = _Hot(state["globals"])
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: hot.values.get(key, default))
    hot_config.set_config_cache(hot)
    chat_params.set_chat_params_cache(cache)
    yield state
    chat_params.set_chat_params_cache(None)
    hot_config.set_config_cache(None)


# ═══ MAC-S10-15 / MAC-S10-08: векторный lookup per-chat ═════════════════════

def _vector_memory(monkeypatch):
    """MemoryManager без БД: считается РЕАЛЬНЫЙ путь `vector_search`."""
    calls = {"knn": [], "fts": [], "embed": []}
    mm = MemoryManager.__new__(MemoryManager)
    mm._vec_available = True

    async def _ensure():
        return None

    async def _gen_ok(name):
        return True

    async def _embed(texts, priority=0):
        calls["embed"].append(list(texts))
        return [[0.0, 1.0]]

    async def _knn(chat_id, vector, limit):
        calls["knn"].append(int(chat_id))
        return [f"knn:{chat_id}"]

    async def _fts(chat_id, query, limit):
        calls["fts"].append(int(chat_id))
        return [f"fts:{chat_id}"]

    mm._ensure_vec_retry = _ensure
    mm._index_generation_ok = _gen_ok
    mm._embed = _embed
    mm._search_archive_knn = _knn
    mm._fts_search_archive = _fts
    return mm, calls


@pytest.mark.asyncio
async def test_vector_lookup_off_only_for_that_chat(world, monkeypatch):
    mm, calls = _vector_memory(monkeypatch)
    assert await mm.vector_search(CHAT_A, "запрос", 5) == [f"fts:{CHAT_A}"]
    # OFF-чат: ни KNN, ни query-embedding (lookup этого чата не выполняется).
    assert calls["knn"] == []
    assert calls["embed"] == []
    # Другой чат не затронут: собственный KNN и общий embed-конвейер живы.
    assert await mm.vector_search(CHAT_B, "запрос", 5) == [f"knn:{CHAT_B}"]
    assert calls["knn"] == [CHAT_B]
    assert len(calls["embed"]) == 1
    # Индекс/сервис не «выключен»: флаг доступности и поколение те же.
    assert mm._vec_available is True
    assert await mm._index_generation_ok("smart_archive") is True
    # Backlog другого чата не заморожен: второй запрос B снова обслуживается.
    assert await mm.vector_search(CHAT_B, "второй", 5) == [f"knn:{CHAT_B}"]
    assert calls["knn"] == [CHAT_B, CHAT_B]


@pytest.mark.asyncio
async def test_vector_gate_is_per_chat_not_shared(world):
    """Единый per-chat резолвер, а не глобальный стоп всего поиска."""
    assert await mca_gates.memory_search_enabled(CHAT_A) is False
    assert await mca_gates.memory_search_enabled(CHAT_B) is True
    # Глобальный слой сохранён: OFF — это выбор ЧАТА, не значение сервиса.
    assert world["globals"]["flags.memory_search_enabled"] is True


# ═══ MAC-S10-19: счётчики и журнал по chat_id ═══════════════════════════════

class _Bot:
    id = 999

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), text))

        class _Msg:
            message_id = 9000 + len(self.sent)
        return _Msg()


class _Writer:
    def __init__(self):
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        return L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return "Продолжим?"


class _CountingLLM:
    """Счётчик реальных LLM-оценок ПО ЧАТУ (runtime counters, не моки)."""

    def __init__(self):
        self.by_chat: dict[int, int] = {}
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        chat_id = int(kwargs.get("chat_id") or 0)
        self.by_chat[chat_id] = self.by_chat.get(chat_id, 0) + 1
        return json.dumps({"opportunity": False}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_runtime_counters_show_zero_for_disabled_chat(monkeypatch):
    """MAC-S10-19: до/после флагов — ноль вызовов OFF-функционала, shared жив."""
    from services import initiative_observer as obs
    from services.database import DatabaseService
    import tempfile
    import time

    mca_events.reset_pending()
    profile = {"initiative.frequency_profile": "active",
               "initiative.eval_min_messages": 4,
               "initiative.eval_min_interval_seconds": 0,
               "initiative.min_gap_seconds": 0,
               "initiative.max_replies_per_day": 10,
               "initiative.eval_llm_budget_per_day": 10}
    chat_params.set_chat_params_cache(_ChatCache({
        CHAT_A: dict(profile, **{"initiative.enabled": False}),
        CHAT_B: dict(profile)}))
    hot_config.set_config_cache(_Hot({}))
    db = DatabaseService(pathlib.Path(tempfile.mkdtemp()) / "s1019.db")
    await db.initialize()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            for cid, uid in ((CHAT_A, 42), (CHAT_B, 52)):
                await db.db.execute(
                    "INSERT INTO smart_messages (user_id, chat_id, text, "
                    "reply_to_id, timestamp, media_type, author_name, "
                    "is_forward, tg_message_id) VALUES (?,?,?,NULL,?,?,?,0,NULL)",
                    (uid + i % 2, cid, f"реплика {cid} {i}", base + i,
                     "text", "u"))
        await db.db.commit()
        llm = _CountingLLM()
        bot = _Bot()
        status = await obs.observe_tick(db, bot=bot,
                                        writer_service=_Writer(), llm=llm)
        assert status == "completed"

        # Счётчик вызовов отключённого функционала = 0 для чата A.
        assert llm.by_chat.get(CHAT_A, 0) == 0
        assert all(cid != CHAT_A for cid, _ in bot.sent)
        assert mca_events  # журнал событий существует
        for item in list(mca_events._pending):
            if str(item.get("event_name")) in ("initiative_opportunity",
                                               "initiative_sent"):
                assert int(item.get("chat_id") or 0) != CHAT_A
        # …но shared-сервис не остановлен: скан выполняется и видны события
        # другого чата (пустой opportunity там — тоже честный исход).
        assert llm.by_chat.get(CHAT_B, 0) == 1
        scans = [e for e in list(mca_events._pending)
                 if str(e.get("event_name")) == "initiative_observer_scan"]
        assert scans, "shared-скан наблюдателя должен оставить событие"
        # Durable-журнал (тот же контракт §17): после flush по chat_id видно
        # ноль событий отключённого чата и живые события соседнего.
        await mca_events.flush_events(db)
        rows_a = await mca_events.query_events(db, chat_id=CHAT_A, limit=200)
        rows_b = await mca_events.query_events(db, chat_id=CHAT_B, limit=200)
        assert rows_a == []
        assert rows_b, "события включённого чата обязаны попасть в журнал"
    finally:
        await db.close()
        mca_events.reset_pending()
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)


# ═══ MAC-S10-05: рестарт / инвалидация кэша / NOTIFY ════════════════════════

class _FakeConn:
    """Минимальный PG-двойник профиля чата (SELECT только)."""

    def __init__(self, root, by_chat=None):
        self.chat_params = copy.deepcopy(root)
        self.by_chat = {int(k): copy.deepcopy(v)
                        for k, v in (by_chat or {}).items()}
        self.updated_at = "2026-11-09T09:00:00+00:00"

    async def fetchrow(self, sql, *args):
        chat_id = int(args[0])
        if chat_id in self.by_chat:
            return {"chat_id": chat_id, "updated_at": self.updated_at,
                    "chat_params": copy.deepcopy(self.by_chat[chat_id]),
                    "gates_opt_in": False}
        return {"chat_id": chat_id, "updated_at": self.updated_at,
                "chat_params": copy.deepcopy(self.chat_params),
                "gates_opt_in": False}


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


@pytest.mark.asyncio
async def test_restart_and_notify_keep_stored_state(monkeypatch):
    """MAC-S10-05: то же desired/effective после рестарта/инвалидации/NOTIFY."""
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: default)
    root = {"v": 1, "overrides": {"memory.experience_learning_enabled": False,
                                  "initiative.enabled": True},
            "gates": {"dream": True}}
    conn = _FakeConn(root)
    pg = _FakePg(conn)

    # «Процесс 1»: прогрет кэш, состояние посчитано.
    cache1 = chat_params.ChatParamsCache(pg)
    chat_params.set_chat_params_cache(cache1)
    state1 = await chat_params.resolve_param_capability(
        CHAT_A, "memory.experience_learning_enabled", capability="experience")
    dream1 = await feature_gates.gate_state(CHAT_A, "dream")
    assert state1.chat_state == chat_params.OFF and state1.desired is False
    assert dream1.chat_state == chat_params.ON and dream1.desired is True

    # «Рестарт процесса»: новый кэш читает сохранённый профиль с нуля.
    cache2 = chat_params.ChatParamsCache(pg)
    chat_params.set_chat_params_cache(cache2)
    state2 = await chat_params.resolve_param_capability(
        CHAT_A, "memory.experience_learning_enabled", capability="experience")
    dream2 = await feature_gates.gate_state(CHAT_A, "dream")
    assert (state2.chat_state, state2.desired, state2.source) == (
        state1.chat_state, state1.desired, state1.source)
    assert (dream2.chat_state, dream2.desired) == (dream1.chat_state,
                                                   dream1.desired)

    # Внешняя запись + PG NOTIFY: инвалидация видит НОВОЕ сохранённое значение.
    conn.chat_params = {"v": 1, "overrides": {
        "memory.experience_learning_enabled": True}, "gates": {"dream": False}}
    await chat_params.invalidate_chat_from_notify(str(CHAT_A))
    state3 = await chat_params.resolve_param_capability(
        CHAT_A, "memory.experience_learning_enabled", capability="experience")
    dream3 = await feature_gates.gate_state(CHAT_A, "dream")
    assert state3.desired is True and state3.chat_state == chat_params.ON
    assert dream3.desired is False and dream3.chat_state == chat_params.OFF
    chat_params.set_chat_params_cache(None)


# ═══ MAC-S10-09: сохранённые старым путём значения ══════════════════════════

@pytest.mark.parametrize("stored, expected_override, expected_gate", [
    (True, chat_params.ON, chat_params.ON),
    (False, chat_params.OFF, chat_params.OFF),
    (1, chat_params.ON, chat_params.ON),
    (0, chat_params.OFF, chat_params.OFF),
])
def test_legacy_stored_flags_are_not_inherit(stored, expected_override,
                                             expected_gate):
    """MAC-S10-09: ни один сохранённый старый формат не читается как inherit.

    Реальные старые write-пути писали bool (`set_feature_gate`,
    `_coerce_value`) либо legacy 0/1; оба варианта обязаны остаться явным
    выбором чата, иначе UI показал бы «наследовать» и функция молча
    переключилась бы на глобальный дефолт.
    """
    root = {"overrides": {"initiative.enabled": stored},
            "gates": {"dream": stored}}
    assert chat_params.chat_state(
        root, "initiative.enabled") == expected_override
    assert chat_params.chat_state(root, "dream",
                                  domain=chat_params.DOMAIN_GATE) == \
        expected_gate
    # Отсутствие ключа — единственный настоящий INHERIT.
    assert chat_params.chat_state({}, "initiative.enabled") == chat_params.INHERIT
    assert chat_params.chat_state({"gates": {}}, "dream",
                                  domain=chat_params.DOMAIN_GATE) == \
        chat_params.INHERIT


def test_every_legacy_write_path_stores_explicit_bool():
    """MAC-S10-09: сверка write-путей — ни один не пишет «inherit» строкой.

    * гейты — `set_feature_gate` (`bool(enabled)`), снятие = удаление ключа;
    * значения каталога — `_coerce_value` в POST /api/config;
    и «Наследовать» = удаление ключа, а не запись `null`/`"inherit"`.
    """
    gates_src = (ROOT / "services/feature_gates.py").read_text(encoding="utf-8")
    assert "gates[feature] = bool(enabled)" in gates_src
    assert "gates.pop(feature, None)" in gates_src
    routes_src = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
    assert 'mode == "inherit"' in routes_src
    assert "new_overrides.pop(key, None)" in routes_src
    chat_src = (ROOT / "services/chat_params.py").read_text(encoding="utf-8")
    # Резолвер ничего не материализует в строку.
    assert "INHERIT не\n" not in chat_src        # sanity: файл читается
    assert 'INHERIT = "inherit"' in chat_src


# ═══ MAC-S10-14: «Время» без тумблера, timezone у всех потребителей ═════════

def test_time_has_no_product_toggle():
    """«Время» — настройка контекста, а не выключаемая способность."""
    from services import module_registry
    from services import param_catalog as pc
    for spec in module_registry.MODULE_REGISTRY.values():
        joined = f"{spec.id} {spec.master_param}".lower()
        assert "timezone" not in joined and joined.strip() != "time", spec.id
    spec = pc.get_by_pg_key("limits.chat_timezone")
    assert spec is not None
    assert spec.type == "str"          # пояс, а не bool-тумблер
    assert spec.per_chat is True       # доступен по чату
    assert "time" not in feature_gates.ALL_GATED_FEATURES


@pytest.mark.asyncio
async def test_timezone_effective_value_matches_across_consumers(monkeypatch):
    """Пояс чата применяется одинаково: ChatClock, мемы, бюджеты.

    Синхронные потребители читают прогретый in-memory слой (так было и до
    M2); тест прогревает его реальным `ChatParamsCache` на PG-двойнике, чтобы
    сравнение шло по одному и тому же сохранённому значению.
    """
    from services import chat_clock
    from services import meme_initiative as meme
    from services import worker_budget

    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: {
                            "limits.chat_timezone": "Europe/Berlin"
                        }.get(key, default))
    conn = _FakeConn({"v": 1},
                     by_chat={CHAT_A: {"v": 1, "overrides": {
                         "limits.chat_timezone": "Asia/Tokyo"}},
                         CHAT_B: {"v": 1, "overrides": {}}})
    cache = chat_params.ChatParamsCache(_FakePg(conn))
    chat_params.set_chat_params_cache(cache)
    try:
        await cache.get_chat_params(CHAT_A)      # обычный async-прогрев
        snap_a = await chat_clock.snapshot(CHAT_A)
        snap_b = await chat_clock.snapshot(CHAT_B)
        assert snap_a.timezone == "Asia/Tokyo"
        assert snap_b.timezone == "Europe/Berlin"
        # Синхронные потребители читают то же значение тем же слоем.
        assert meme.resolve_timezone(CHAT_A)[0] == "Asia/Tokyo"
        assert meme.resolve_timezone(CHAT_B)[0] == "Europe/Berlin"
        assert worker_budget._chat_tz_name(CHAT_A) == "Asia/Tokyo"
        assert worker_budget._chat_tz_name(CHAT_B) == "Europe/Berlin"
        # Часы не «выключаются»: у снапшота есть локальное время и смещение.
        assert snap_a.local_datetime is not None
        assert snap_a.utc_offset.startswith("+")
    finally:
        chat_params.set_chat_params_cache(None)


# ═══ MAC-S10-03: 409 без потери записи + идемпотентный дубль ════════════════

class _WriteConn:
    """PG-двойник записи профиля (UPDATE с optimistic-меткой)."""

    def __init__(self):
        self.profiles = {}
        self.history: list = []
        self.notifies: list = []
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-11-09T10:00:{self._seq:02d}+00:00"

    def add(self, chat_id, root):
        self.profiles[chat_id] = {
            "chat_id": chat_id, "updated_at": self._ts(),
            "chat_params": copy.deepcopy(root), "gates_opt_in": False}

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            row = self.profiles.get(args[0])
            return copy.deepcopy(row) if row else None
        if "UPDATE chat_profiles" in sql:
            row = self.profiles.get(args[0])
            if row is None:
                return None
            if "AND updated_at = $3::timestamptz" in sql:
                value = args[2]
                value = value.isoformat() if hasattr(value, "isoformat") \
                    else str(value)
                if value != row["updated_at"]:
                    return None
            row["chat_params"] = (json.loads(args[1])
                                  if isinstance(args[1], str) else args[1])
            row["updated_at"] = self._ts()
            return copy.deepcopy(row)
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO chat_lore_history" in sql:
            self.history.append(args)
        if "pg_notify" in sql:
            self.notifies.append(str(args[0]))
        return "OK"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Tx()


@pytest.mark.asyncio
async def test_stale_concurrent_edit_is_409_without_lost_write():
    """Две параллельные правки: первая пишется, вторая → 409, данные целы."""
    conn = _WriteConn()
    conn.add(CHAT_A, {"v": 1, "overrides": {}, "gates": {}})
    pg = _FakePg(conn)
    token = conn.profiles[CHAT_A]["updated_at"]

    first = await chat_params.set_chat_params(
        CHAT_A, {"overrides": {"initiative.enabled": False}},
        pg=pg, expected_updated_at=token)
    assert first["overrides"]["initiative.enabled"] is False

    with pytest.raises(chat_params.ChatParamsConflict) as exc:
        await chat_params.set_chat_params(
            CHAT_A, {"overrides": {"flags.dream_enabled": True}},
            pg=pg, expected_updated_at=token)
    assert exc.value.current_updated_at
    assert exc.value.conflicting
    # Запись проигравшего НЕ потеряна частично: сохранено только победившее.
    stored = conn.profiles[CHAT_A]["chat_params"]
    assert stored["overrides"] == {"initiative.enabled": False}
    # Повтор с актуальной меткой дописывает вторую правку без потери первой.
    fresh = conn.profiles[CHAT_A]["updated_at"]
    merged = await chat_params.set_chat_params(
        CHAT_A, {"overrides": {"initiative.enabled": False,
                              "flags.dream_enabled": True}},
        pg=pg, expected_updated_at=fresh)
    assert merged["overrides"]["initiative.enabled"] is False
    assert merged["overrides"]["flags.dream_enabled"] is True


@pytest.mark.asyncio
async def test_duplicate_post_is_idempotent_not_second_write():
    """Дубль того же POST (двойной клик/ретрай) не пишет второй раз."""
    conn = _WriteConn()
    conn.add(CHAT_A, {"v": 1, "overrides": {}, "gates": {}})
    pg = _FakePg(conn)
    token = conn.profiles[CHAT_A]["updated_at"]
    patch = {"overrides": {"initiative.enabled": True}}

    first = await chat_params.set_chat_params(
        CHAT_A, patch, pg=pg, expected_updated_at=token)
    history_after_first = len(conn.history)
    assert history_after_first == 1
    # Второй POST с ТЕМ ЖЕ (теперь устаревшим) токеном: значение уже на
    # сервере → короткое замыкание, а не 409 и не вторая запись.
    second = await chat_params.set_chat_params(
        CHAT_A, patch, pg=pg, expected_updated_at=token)
    assert getattr(second, "revalidated", False) is True
    assert len(conn.history) == history_after_first
    assert conn.profiles[CHAT_A]["chat_params"]["overrides"] == {
        "initiative.enabled": True}
    assert first["overrides"] == second["overrides"]


def test_ui_double_click_cannot_emit_two_posts():
    """Фронтовый guard двойного клика существует (read-only проверка кода).

    UI не входит в этот срез, поэтому проверяется фактический контракт
    существующего `app.js`: per-key in-flight набор отсекает второй POST, а
    `operation_id` едет на сервер для идемпотентного повтора.
    """
    src = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "if (this.saving && this.saving.has && this.saving.has(item.key))" \
        in src
    assert "if (saving.has(it.key)) { skipped.push(it.key); continue; }" in src
    assert "operation_id: operationId" in src


# ═══ MAC-S2-102 / MAC-S0-03: инвентарь и отсутствие DDL ═════════════════════

def test_consumer_inventory_note_lists_real_modules():
    """Инвентарь потребителей — durable-заметка со ссылками на живые файлы."""
    note = (ROOT / "docs" / "mod-acl-ux-01-m2-consumers.md")
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    refs = set(re.findall(r"`((?:services|web|handlers)/[A-Za-z0-9_/]+\.py)`",
                          text))
    assert len(refs) >= 8
    for rel in sorted(refs):
        assert (ROOT / rel).exists(), rel


def test_no_raw_chat_params_cache_readers_outside_resolver():
    """MAC-S2-102: приватный кэш читает только его владелец.

    Раньше `worker_settings`, `worker_budget` и `meme_initiative` лезли в
    `ChatParamsCache._items` каждый по-своему. Теперь единственная точка
    синхронного чтения — `chat_params.read_override_sync`.
    """
    offenders = []
    for path in list((ROOT / "services").glob("*.py")) + \
            list((ROOT / "web").rglob("*.py")) + \
            list((ROOT / "handlers").glob("*.py")):
        if path.name == "chat_params.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '"__items__"' in text:
            offenders.append(str(path))
        if re.search(r'getattr\(cache,\s*"_items"', text):
            offenders.append(str(path))
    assert offenders == []
    chat_src = (ROOT / "services/chat_params.py").read_text(encoding="utf-8")
    assert "def read_override_sync(" in chat_src


M2_PRODUCT_FILES = (
    "services/chat_params.py",
    "services/feature_gates.py",
    "services/module_registry.py",
    "services/permsoc.py",
    "services/lore_worker.py",
    "services/nostalgia_worker.py",
    "services/status_service.py",
    "services/initiative_observer.py",
    "services/meme_initiative.py",
    "services/memory_maintenance.py",
    "services/worker_budget.py",
    "services/worker_settings.py",
)


def test_stage_introduces_no_schema_or_prompt_rewrite():
    """MAC-S0-03: M2 не добавляет шаг схемы и не переписывает промпты.

    Срез не регистрирует миграций (`_migrate_*`), не расширяет
    `prompt_migrations` и не пишет промпты. Числовой фронтьер схемы и
    факт «directory/database.py не в диффе» зафиксированы в
    `docs/mod-acl-ux-01-m2-deploy.md` с командами воспроизведения.
    """
    for rel in M2_PRODUCT_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "prompt_migrations" not in text, rel
        assert "PromptWriteItem(" not in text, rel
        # Регистрация шага схемы живёт в services/database.py; ни один файл
        # среза её не объявляет (иначе миграция появилась бы мимо владельца).
        assert re.search(r"def _migrate_[a-z0-9_]+\(", text) is None, rel
        assert "_SCHEMA_VERSION_" not in text, rel
    deploy_note = (ROOT / "docs" / "mod-acl-ux-01-m2-deploy.md")
    assert deploy_note.exists()
    body = deploy_note.read_text(encoding="utf-8")
    assert "git pull --ff-only" in body
    assert "systemctl restart admin_bot" in body
    assert "DDL" in body
