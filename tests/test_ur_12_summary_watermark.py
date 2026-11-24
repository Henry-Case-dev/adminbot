"""UR-12 summary/watermark proof: trigger, tail, level2, soft bound.

Строки UR-12.1/12.2/12.3/12.5 остаются PENDING/PARTIAL до review.
"""
import asyncio
from types import SimpleNamespace

import pytest

import config.settings as settings_module
import services.direct_chat_service as dcs
import services.param_catalog as catalog
import services.summary_memory as sm
from tests.test_direct_chat import FakeMemory, _make_service

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777


def _row(ts: int, text: str = "") -> dict:
    return {
        "id": ts, "tg_message_id": 1000 + ts, "user_id": 10,
        "author_name": "Вася", "text": text or f"строка-{ts}",
        "timestamp": ts, "media_type": "text", "reply_to_id": None,
    }


def _rows(count: int, *, start: int = 1) -> list[dict]:
    return [_row(start + i) for i in range(count)]


class _WindowDB:
    def __init__(self, rows, summary=None):
        self.rows = rows
        self.summary = summary

    async def get_smart_window(self, chat_id, since, limit):
        return list(self.rows)

    async def get_running_summary(self, chat_id, now):
        return self.summary


def _memory(db) -> sm.MemoryManager:
    mem = object.__new__(sm.MemoryManager)
    mem.db = db
    return mem


def _patch_window(monkeypatch, *, working=5):
    async def _enabled(chat_id):
        return True

    async def _limit(chat_id, key, default):
        return default

    monkeypatch.setattr(sm, "chat_summary_enabled", _enabled)
    monkeypatch.setattr(sm, "_chat_limit", _limit)
    monkeypatch.setattr(sm, "_working_window_messages",
                        lambda: int(working))


# ── UR-12.1: watermark/no-repeat decision + fill ratio is not a trigger ────

def test_running_summary_watermark_and_displacement_decision():
    rows = _rows(12)
    current = sm.running_summary_decision(
        rows, watermark_ts=12, working_window_messages=5)
    assert current["refresh"] is False
    assert current["reason_code"] == "watermark_current"
    assert current["uncovered_messages"] == 0

    fits = sm.running_summary_decision(
        rows, watermark_ts=10, working_window_messages=5)
    assert fits["refresh"] is False
    assert fits["reason_code"] == "fits_working_window"

    displaced = sm.running_summary_decision(
        rows, watermark_ts=2, working_window_messages=5)
    assert displaced["refresh"] is True
    assert displaced["reason_code"] == "displaced_by_new_messages"
    assert displaced["uncovered_messages"] == 10
    assert displaced["uncovered_since_ts"] == 3


@pytest.mark.asyncio
async def test_live_trigger_ignores_fill_ratio_and_uses_watermark(monkeypatch):
    _patch_window(monkeypatch, working=5)
    rows = _rows(30)
    calls: list = []
    mem = _memory(_WindowDB(rows, summary={"window_end_ts": 30}))
    mem._schedule_running_summary = lambda chat_id, r: calls.append(
        (chat_id, len(r)))
    for ratio in (0.01, 0.99):
        monkeypatch.setattr(settings_module.Settings,
                            "CHAT_CONTEXT_FILL_RATIO", ratio)
        assert await mem.get_window_messages(CHAT) == rows
        assert calls == []

    # Непокрытый диапазон > рабочего хвоста — запуск; ratio не участвует.
    mem.db.summary = {"window_end_ts": 0}
    monkeypatch.setattr(settings_module.Settings,
                        "CHAT_CONTEXT_FILL_RATIO", 0.99)
    assert await mem.get_window_messages(CHAT) == rows
    assert calls == [(CHAT, 30)]


@pytest.mark.asyncio
async def test_singleflight_coalesces_by_chat_key(monkeypatch):
    class _Supervisor:
        def __init__(self):
            self.keys: list = []
            self.active: set = set()
            self.coalesced = 0
            self.started = 0

        async def run(self, fn, *, owner, kind, coalesce_key, emit_event):
            self.keys.append(coalesce_key)
            if coalesce_key in self.active:
                self.coalesced += 1
                return None
            self.active.add(coalesce_key)
            self.started += 1
            return None

    sup = _Supervisor()
    pending: list = []

    def _ff(coro, name):
        pending.append(coro)

    monkeypatch.setattr(sm.mca_gates, "summary_singleflight_enabled",
                        lambda: True)
    monkeypatch.setattr(sm, "fire_and_forget", _ff)
    import services.task_supervisor as task_supervisor
    monkeypatch.setattr(task_supervisor, "get_task_supervisor", lambda: sup)
    mem = _memory(_WindowDB([]))
    mem._build_running_summary = lambda *a, **k: None
    mem._schedule_running_summary(CHAT, [])
    mem._schedule_running_summary(CHAT, [])
    await asyncio.gather(*pending)
    assert sup.keys == [f"running_summary:{CHAT}",
                        f"running_summary:{CHAT}"]
    assert sup.started == 1
    assert sup.coalesced == 1


# ── UR-12.2: tail is a summary-build fallback, not a window barrier ───────

class _BuildDB:
    def __init__(self):
        self.upserts: list = []

    async def get_running_summary(self, chat_id, now):
        return None

    async def upsert_running_summary(self, chat_id, summary, start, end,
                                     count, now, ttl):
        self.upserts.append((summary, start, end, count))
        return True


class _BuildLLM:
    def __init__(self):
        self.prompts: list = []

    async def generate(self, messages):
        self.prompts.append(messages)
        return "конспект"


@pytest.mark.asyncio
async def test_tail_only_changes_summary_build_not_window(monkeypatch):
    rows = _rows(8)

    async def _media(*args, **kwargs):
        return {"pending": [], "ready": [], "failed": []}

    def _hot(key, default=None):
        if key == "limits.chat_running_summary_tail":
            return current_tail[0]
        if key == "prompts.compress_system_prompt":
            return "COMPRESS"
        if key == "limits.running_summary_ttl_minutes":
            return 60
        return default

    current_tail = [1]
    monkeypatch.setattr(sm, "visual_window_state", _media)
    monkeypatch.setattr(sm.hot, "get", _hot)
    _patch_window(monkeypatch, working=100)
    mem = _memory(_WindowDB(rows, summary={"window_end_ts": 8}))
    mem.llm = _BuildLLM()
    # tail не меняет окно чтения
    assert await mem.get_window_messages(CHAT) == rows

    db = _BuildDB()
    mem.db = db
    mem.llm = _BuildLLM()
    await mem._build_running_summary_impl(CHAT, rows)
    first = mem.llm.prompts[-1][-1]["content"]
    marker = "=== последние сообщения дословно ==="
    assert marker in first
    first_tail = first.split(marker, 1)[1]
    assert "строка-8" in first_tail
    assert "строка-5" not in first_tail
    assert db.upserts and db.upserts[-1][3] == len(rows)

    current_tail[0] = 4
    db = _BuildDB()
    mem.db = db
    mem.llm = _BuildLLM()
    await mem._build_running_summary_impl(CHAT, rows)
    second = mem.llm.prompts[-1][-1]["content"]
    second_tail = second.split(marker, 1)[1]
    assert "строка-8" in second_tail
    assert "строка-5" in second_tail
    assert db.upserts


# ── UR-12.3: level2 advances by watermark, not min raw count ──────────────

def test_level2_advance_by_watermark_and_no_same_range_rebuild():
    prev = {"summary": "старый", "window_end_ts": 120, "raw_count": 10}
    same = sm.level2_advance_decision(
        prev, covered_identity={"window_end_ts": 120, "raw_count": 10})
    assert same["build"] is False
    assert same["reason_code"] == "range_already_covered"

    older = sm.level2_advance_decision(
        prev, covered_identity={"window_end_ts": 100, "raw_count": 8})
    assert older["build"] is True
    assert older["reason_code"] == "uncovered_range_advanced"

    legacy = sm.level2_advance_decision(
        prev, covered_identity=None,
        existing={"msg_count_highwater": 10})
    assert legacy["build"] is False
    assert legacy["reason_code"] == "legacy_highwater_current"


class _Level2DB(_BuildDB):
    def __init__(self, existing):
        super().__init__()
        self.existing = existing
        self.upserts_l2: list = []

    async def get_summary_level(self, chat_id, level):
        return self.existing

    async def upsert_summary_level(self, chat_id, level, summary, now,
                                   raw_count):
        self.upserts_l2.append((level, summary, raw_count))


@pytest.mark.asyncio
async def test_level2_does_not_overwrite_same_covered_range(monkeypatch):
    async def _load(db, chat_id):
        return {"window_end_ts": 120, "raw_count": 10}

    async def _save(db, chat_id, identity):
        return None

    monkeypatch.setattr(sm, "_load_l2_source_version", _load)
    monkeypatch.setattr(sm, "_save_l2_source_version", _save)
    prev = {"summary": "старый", "window_end_ts": 120, "raw_count": 10}
    db = _Level2DB(existing={"summary": "существующий", "raw_count": 9})
    mem = _memory(db)
    mem.llm = _BuildLLM()
    await mem._build_level2(CHAT, prev)
    assert db.upserts_l2 == []
    assert mem.llm.prompts == []

    async def _load_old(db, chat_id):
        return {"window_end_ts": 100, "raw_count": 8}

    monkeypatch.setattr(sm, "_load_l2_source_version", _load_old)
    db = _Level2DB(existing={"summary": "существующий", "raw_count": 8})
    mem = _memory(db)
    mem.llm = _BuildLLM()
    await mem._build_level2(CHAT, prev)
    assert db.upserts_l2
    assert db.upserts_l2[0][2] == 10


# ── UR-12.5: Global_Context limit is a soft primary read bound ─────────────

class _GlobalDB:
    async def get_running_summary(self, chat_id, now):
        return None

    async def get_summary_level(self, chat_id, level):
        return None


@pytest.mark.asyncio
async def test_global_context_limit_is_soft_read_bound(monkeypatch):
    rows = _rows(150)
    svc = _make_service(memory=FakeMemory(window=rows), llm=None)

    async def _enabled(chat_id):
        return True

    async def _partial(chat_id, window):
        return False

    async def _cp_g(chat_id, key, default=None):
        return default

    monkeypatch.setattr(dcs, "chat_summary_enabled", _enabled)
    monkeypatch.setattr(svc, "_history_partial", _partial)
    monkeypatch.setattr(dcs, "_cp_g", _cp_g)
    svc.db = _GlobalDB()
    parts = await svc._build_global_context_parts(CHAT, rows)
    tail = parts["tail_rows"]
    assert len(tail) == settings_module.Settings.CHAT_GLOBAL_CONTEXT_LIMIT
    assert tail[0]["timestamp"] == 51
    assert tail[-1]["timestamp"] == 150
    assert all(row["timestamp"] > 50 for row in tail)
    assert settings_module.Settings.CHAT_GLOBAL_CONTEXT_LIMIT != 1000

    class _RetrievalDB:
        def __init__(self):
            self.calls: list = []

        async def search_messages_fts(self, chat_id, query, limit, **kwargs):
            self.calls.append((limit, kwargs))
            return [{"text": "OLD_MARKER_UR12", "tg_message_id": 1}]

    rdb = _RetrievalDB()
    mem = _memory(rdb)
    found = await mem.search_long_term(CHAT, ["old"], 5)
    assert found and found[0]["text"] == "OLD_MARKER_UR12"
    assert rdb.calls and rdb.calls[0][0] == 5


# ── Metadata: legacy/no-op vs active soft bound ────────────────────────────

def test_effective_meta_summary_watermark_contract():
    expect = {
        "limits.chat_context_fill_ratio": "no_op",
        "limits.chat_running_summary_tail": "legacy",
        "limits.chat_level2_min_raw_count": "legacy",
        "limits.chat_global_context_limit": "active",
    }
    for key, status in expect.items():
        meta = catalog.effective_meta(key)
        assert meta["status"] == status, key
        if status in ("no_op", "legacy"):
            assert meta["reason_inactive"], key
        else:
            assert meta["reason_inactive"] == "", key
            assert "Global_Context" in meta["active_consumer"], key
    assert "watermark" in catalog.effective_meta(
        "limits.chat_context_fill_ratio")["reason_inactive"].lower()
    assert "fallback" in catalog.effective_meta(
        "limits.chat_running_summary_tail")["reason_inactive"].lower()
    global_desc = catalog.get("CHAT_GLOBAL_CONTEXT_LIMIT").description
    assert "retrieval" in global_desc.lower()
    assert "стар" in global_desc.lower()
    assert "не триггер" in catalog.effective_meta(
        "limits.chat_context_fill_ratio")["reason_inactive"].lower()
    assert settings_module.Settings.CHAT_GLOBAL_CONTEXT_LIMIT == 100
    assert settings_module.Settings.CHAT_RUNNING_SUMMARY_TAIL == 30
    assert settings_module.Settings.CHAT_LEVEL2_MIN_RAW_COUNT == 250
    assert settings_module.Settings.CHAT_CONTEXT_FILL_RATIO == 0.8
