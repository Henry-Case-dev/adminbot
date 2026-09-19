"""F4 (раунд 10.23, ADR-1023-4) — динамический анти-клише кэш.

Покрытие: разбор LLM-ответа; нормализация/дедуп/лимит/фильтр хардкод-дублей;
стабильные коды; подача динамических правил в детектор; scrubber НЕ режет
клише; ретраи validator-loop с динамическим правилом; фикс S10.22-4b;
fail-open (нет PG/битый JSON/ошибки воркера); идемпотентный DDL; API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from config.settings import Settings
from services import anticliche_cache as ac
from services import anticliche_worker as aw
from services.anticliche_worker import (
    AntiClicheWorker,
    build_patterns,
    parse_patterns,
)
from services.negative_constraints import (
    DEFAULT_ENABLED_RULES,
    DynamicClicheRule,
    build_dynamic_rule,
    dynamic_rule_code,
    find_forbidden_cliches,
    normalize_dynamic_phrase,
    verbalize_validated,
)
from services.outgoing_guard import sanitize_outgoing

pytestmark = pytest.mark.system2


# ── фейковый PG ─────────────────────────────────────────────────────────────

class _Store:
    def __init__(self):
        self.row = None


class _FakeConn:
    def __init__(self, store: _Store):
        self.store = store

    async def fetchrow(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("SELECT patterns"):
            return dict(self.store.row) if self.store.row else None
        if flat.startswith("INSERT INTO anticliche_cache"):
            patterns, source, source_url, status, fetched_at = args
            prev = self.store.row or {}
            version = int(prev.get("version") or 0) + 1
            previous_fetched = prev.get("fetched_at")
            self.store.row = {
                "patterns": patterns, "source": source,
                "source_url": source_url, "version": version,
                "fetched_at": fetched_at if fetched_at is not None
                else previous_fetched,
                "updated_at": "2026-09-19T00:00:00+00:00",
                "last_status": status,
            }
            return {"version": version}
        if "INSERT INTO worker_budget" in flat:
            return {"used": 1}
        return None

    async def execute(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("UPDATE anticliche_cache"):
            if self.store.row is None:
                self.store.row = {"patterns": [], "source": "",
                                  "source_url": "", "version": 0,
                                  "last_status": "never"}
            self.store.row["last_status"] = args[0]
        return "UPDATE 1"


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CM:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, store: _Store | None = None):
        self.store = store or _Store()
        self.pool = _FakePool(_FakeConn(self.store))


@pytest.fixture(autouse=True)
def _reset_cache_state():
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)
    yield
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)


# ── разбор LLM-ответа ───────────────────────────────────────────────────────

class TestParsePatterns:
    def test_valid_json(self):
        raw = json.dumps({"patterns": [{"phrase": "Фраза один",
                                        "origin": "раздел"}]})
        assert parse_patterns(raw) == [
            {"phrase": "Фраза один", "origin": "раздел"}]

    def test_markdown_fences(self):
        raw = '```json\n{"patterns": [{"phrase": "тест"}]}\n```'
        assert parse_patterns(raw) == [{"phrase": "тест", "origin": None}]

    def test_string_items_accepted(self):
        assert parse_patterns('{"patterns": ["фраза"]}') == [
            {"phrase": "фраза", "origin": ""}]

    @pytest.mark.parametrize("raw", [
        "", "не json", '{"patterns":', '{"other": []}', "[1,2,3]",
        '{"patterns": "нет"}',
    ])
    def test_invalid_returns_none(self, raw):
        assert parse_patterns(raw) is None


# ── нормализация/дедуп/лимит ────────────────────────────────────────────────

class TestBuildPatterns:
    def test_normalizes_and_stable_code(self):
        out = build_patterns([{"phrase": "  ЁЖИК   тут ", "origin": "x"}])
        assert out[0]["phrase"] == "ежик тут"
        assert out[0]["code"] == dynamic_rule_code("ежик тут")
        assert out[0]["code"].startswith("dyn_")

    def test_dedup_within_dynamic(self):
        out = build_patterns([{"phrase": "повтор фразы"},
                              {"phrase": "Повтор   фразы"}])
        assert len(out) == 1

    def test_skips_hardcoded_duplicates(self):
        out = build_patterns([{"phrase": "подводя итог"},
                              {"phrase": "свежая фраза"}])
        assert [p["phrase"] for p in out] == ["свежая фраза"]

    def test_limit_and_drop_invalid(self):
        """F7/ADR-1024-3 D1: искусственный потолок 20 снят (default 200)."""
        entries = [{"phrase": f"фраза номер {i}"} for i in range(30)]
        entries += [{"phrase": "a"}, {"phrase": "я" * 200}]
        out = build_patterns(entries)
        assert len(out) == 30          # все валидные (30 > прежних 20)
        assert "a" not in [p["phrase"] for p in out]

    def test_code_deterministic(self):
        assert dynamic_rule_code("одна фраза") == dynamic_rule_code("одна фраза")
        assert dynamic_rule_code("одна фраза") != dynamic_rule_code("другая")

    def test_normalize_phrase_none_for_garbage(self):
        assert normalize_dynamic_phrase(None) is None
        assert normalize_dynamic_phrase("") is None
        assert normalize_dynamic_phrase("x") is None


# ── подача в детектор ───────────────────────────────────────────────────────

class TestDetectorDynamic:
    def test_dynamic_rule_detected_by_code(self):
        rule = build_dynamic_rule("шаблонная конструкция")
        assert rule is not None
        hits = find_forbidden_cliches("тут шаблонная конструкция внутри",
                                      dynamic_rules=[rule])
        assert rule.code in hits

    def test_dynamic_none_is_byte_equal(self):
        text = "обычный текст без клише"
        assert find_forbidden_cliches(text) == find_forbidden_cliches(
            text, dynamic_rules=None)
        assert find_forbidden_cliches(text, dynamic_rules=[]) == \
            find_forbidden_cliches(text)

    def test_literal_only_not_regex(self):
        rule = DynamicClicheRule(code="dyn_x", phrase="a.b")
        assert find_forbidden_cliches("axb", dynamic_rules=[rule]) == []
        assert find_forbidden_cliches("a.b", dynamic_rules=[rule]) == ["dyn_x"]

    def test_normalized_haystack(self):
        rule = build_dynamic_rule("Ёжик Иголка")
        assert find_forbidden_cliches("ёжик иголка", dynamic_rules=[rule])

    def test_only_codes_returned(self):
        rule = build_dynamic_rule("динамический штамп")
        hits = find_forbidden_cliches("динамический штамп тут",
                                      dynamic_rules=[rule])
        assert all(h.startswith("dyn_") or h in DEFAULT_ENABLED_RULES
                   for h in hits)

    def test_generator_rules_materialized(self):
        """M2: генератор допустим сигнатурой и должен находиться."""
        rules = (r for r in [build_dynamic_rule("штамп генератора")])
        hits = find_forbidden_cliches("штамп генератора", dynamic_rules=rules)
        assert len(hits) == 1 and hits[0].startswith("dyn_")


class TestScrubberDoesNotCutCliches:
    def test_sanitize_keeps_dynamic_phrase(self):
        text = "тут динамический штамп и всё"
        assert sanitize_outgoing(text) == text

    def test_sanitize_keeps_hardcoded_cliche(self):
        text = "подводя итог, всё плохо"
        assert sanitize_outgoing(text) == text


# ── validator-loop с динамическими правилами ────────────────────────────────

class TestValidatorDynamic:
    @pytest.mark.asyncio
    async def test_dynamic_rule_triggers_retry(self):
        rule = build_dynamic_rule("шаблонное словосочетание")
        gen = AsyncMock(side_effect=[
            "ну шаблонное словосочетание тут", "теперь чисто"])
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            dynamic_rules=[rule])
        assert text == "теперь чисто"
        assert stats["retries"] == 1
        assert gen.await_count == 2

    @pytest.mark.asyncio
    async def test_dynamic_rule_exhausted_fallback(self):
        rule = build_dynamic_rule("шаблонное словосочетание")
        gen = AsyncMock(return_value="шаблонное словосочетание всегда")
        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            dynamic_rules=[rule], max_retries=99)
        assert gen.await_count == 3
        assert stats["fallback"] is True
        assert rule.code in stats["hits"]

    @pytest.mark.asyncio
    async def test_no_dynamic_rules_unchanged(self):
        gen = AsyncMock(return_value="подводя итог")
        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}])
        assert stats["hits"] == ["summing_up"]

    @pytest.mark.asyncio
    async def test_generator_rules_survive_retries(self):
        """M2: генератор не должен исчерпаться на ретраях."""
        rule = build_dynamic_rule("секретный штамп")
        calls = []

        async def gen(messages):
            calls.append(messages)
            return "секретный штамп опять"

        rules = (r for r in [rule])
        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            dynamic_rules=rules, max_retries=2)
        assert len(calls) == 3          # каждый ответ забракован
        assert stats["retries"] == 2
        assert rule.code in stats["hits"]


# ── S10.22-4b ───────────────────────────────────────────────────────────────

class TestS1022_4b:
    @pytest.mark.parametrize("text", [
        "Он, как искусственный интеллект, не устаёт",
        "Она, как искусственный интеллект, ошибается",
        "Оно, как искусственный интеллект, считает",
        "Это, как искусственный интеллект, странно",
        "Люди, как искусственный интеллект, ошибаются",
        "Человек, как искусственный интеллект, ошибается",
        "она, как языковая модель",
        "Он, как языковая модель, отвечает",
        # M3 (review iter1): пробел ПЕРЕД запятой (дефект набора).
        "Он , как искусственный интеллект, не устаёт",
        "Она , как ИИ, ошибается",
        "Люди , как ИИ",
        "Человек , как искусственный интеллект",
        "Оно , как языковая модель",
    ])
    def test_third_person_comma_not_flagged(self, text):
        assert find_forbidden_cliches(text) == []

    def test_first_person_comma_still_flagged(self):
        assert "as_ai" in find_forbidden_cliches("Я, как ИИ, не могу")
        assert "as_ai" in find_forbidden_cliches("я, как искусственный интеллект")

    def test_bare_language_model_flagged(self):
        assert "as_ai" in find_forbidden_cliches("языковая модель отвечает")
        assert "as_ai" in find_forbidden_cliches("как языковая модель отвечаю")


class TestPromptInvariants:
    """L6 (review iter1): тест-гарант «фразы не в промпте»."""

    _TROPES = ("как ИИ", "надеюсь, помог", "нет, ты", "ты уже спрашивал",
               "подводя итог", "в заключение")

    def test_extract_prompt_does_not_quote_cliches(self):
        for trop in self._TROPES:
            assert trop not in aw.EXTRACT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_dynamic_phrase_never_in_verb_messages(self):
        rule = build_dynamic_rule("динамическая улика")
        seen: list[list[dict]] = []

        async def gen(messages):
            seen.append(list(messages))
            return "динамическая улика опять"

        await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            dynamic_rules=[rule], max_retries=1)
        assert seen
        for messages in seen:
            for message in messages:
                assert rule.phrase not in message["content"]


# ── кэш: fail-open/резолв ───────────────────────────────────────────────────

class TestCacheFailOpen:
    @pytest.mark.asyncio
    async def test_fetch_cache_none_pg(self):
        assert await ac.fetch_cache(None) == {}

    @pytest.mark.asyncio
    async def test_load_rules_none_pg_keeps_current(self):
        ac.set_rules([{"phrase": "фраза из кэша"}])
        rules = await ac.load_rules(None)
        assert rules == ac.get_rules()
        assert len(rules) == 1

    def test_get_rules_disabled(self, monkeypatch):
        monkeypatch.setattr(Settings, "DYNAMIC_ANTICLICHE_ENABLED", False)
        ac.set_rules([{"phrase": "не должна попасть"}])
        assert ac.get_rules() == ()
        assert ac.set_rules([{"phrase": "x"}]) == ()

    def test_set_get_invalidate(self):
        rules = ac.set_rules([{"phrase": "нужная фраза"}])
        assert ac.get_rules() == rules
        ac.invalidate()
        assert ac.get_rules() == ()

    def test_status_sql_does_not_touch_updated_at(self):
        """L3: status-only апдейт не двигает updated_at."""
        assert "updated_at" not in ac._STATUS_SQL

    @pytest.mark.asyncio
    async def test_mark_status_whitelist(self):
        """L1: неизвестный статус не пишется как есть."""
        pg = _FakePg()
        await ac.mark_status(pg, "bogus_status")
        assert pg.store.row["last_status"] == "never"
        await ac.mark_status(pg, "llm_error")
        assert pg.store.row["last_status"] == "llm_error"

    @pytest.mark.asyncio
    async def test_read_write_roundtrip(self):
        pg = _FakePg()
        ac.set_runtime_pg(pg)
        patterns = build_patterns([{"phrase": "живая фраза"}])
        version = await ac.write_patterns(pg, patterns, source="manual",
                                          source_url="")
        assert version == 1
        data = await ac.fetch_cache(pg)
        assert data["source"] == "manual"
        assert data["patterns"][0]["phrase"] == "живая фраза"
        assert ac.get_rules()[0].phrase == "живая фраза"

    @pytest.mark.asyncio
    async def test_write_without_pg_raises(self):
        ac.set_runtime_pg(None)
        with pytest.raises(RuntimeError):
            await ac.write_patterns(None, [], source="manual", source_url="")


# ── воркер ──────────────────────────────────────────────────────────────────

def _worker(store: _Store, *, fetch=None, llm=None):
    return AntiClicheWorker(llm=llm, pg=_FakePg(store), fetch=fetch)


class TestWorker:
    @pytest.mark.asyncio
    async def test_refresh_ok(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value=json.dumps(
            {"patterns": [{"phrase": "свежий штамп", "origin": "wiki"}]}))
        fetch = AsyncMock(return_value="исходный текст справочника")
        worker = _worker(store, fetch=fetch, llm=llm)
        result = await worker.refresh()
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert store.row["last_status"] == "ok"
        assert store.row["patterns"][0]["phrase"] == "свежий штамп"
        assert ac.get_rules()[0].phrase == "свежий штамп"

    @pytest.mark.asyncio
    async def test_refresh_parse_error_keeps_cache(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {"patterns": [{"phrase": "старое", "code": "dyn_old"}],
                     "source": "wikipedia", "source_url": "u", "version": 3,
                     "last_status": "ok"}
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value="не json вообще")
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        result = await worker.refresh()
        assert result["status"] == "parse_error"
        assert store.row["patterns"][0]["phrase"] == "старое"
        assert store.row["last_status"] == "parse_error"

    @pytest.mark.asyncio
    async def test_refresh_fetch_error(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {"patterns": [], "source": "wikipedia", "source_url": "u",
                     "version": 1, "last_status": "ok"}
        fetch = AsyncMock(side_effect=RuntimeError("boom"))
        worker = _worker(store, fetch=fetch, llm=AsyncMock())
        result = await worker.refresh()
        assert result["status"] == "fetch_error"
        assert store.row["last_status"] == "fetch_error"

    @pytest.mark.asyncio
    async def test_refresh_llm_error(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {"patterns": [], "source": "wikipedia", "source_url": "u",
                     "version": 1, "last_status": "ok"}
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(side_effect=RuntimeError("llm down"))
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        result = await worker.refresh()
        assert result["status"] == "llm_error"
        assert store.row["last_status"] == "llm_error"

    @pytest.mark.asyncio
    async def test_refresh_budget_skip(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=False))
        store = _Store()
        fetch = AsyncMock(return_value="text")
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value="{}")
        worker = _worker(store, fetch=fetch, llm=llm)
        result = await worker.refresh()
        assert result["status"] == "budget_skip"
        # L5: бюджет call-лимита проверяется ПОСЛЕ fetch, но ДО LLM.
        assert fetch.await_count == 1
        assert llm.generate_worker.await_count == 0

    @pytest.mark.asyncio
    async def test_empty_result_keeps_previous_cache(self, monkeypatch):
        """Review iter1 H1: валидный вырожденный ответ не затирает кэш."""
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {
            "patterns": [{"code": "dyn_keep", "phrase": "живая фраза",
                          "origin": "wiki"}],
            "source": "wikipedia", "source_url": "u", "version": 5,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "last_status": "ok",
        }
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value='{"patterns": []}')
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        result = await worker.refresh()
        assert result["status"] == "empty"
        assert result["count"] == 0
        assert store.row["patterns"][0]["phrase"] == "живая фраза"
        assert store.row["version"] == 5          # запись не производилась
        assert store.row["last_status"] == "empty"

    @pytest.mark.asyncio
    async def test_hardcoded_echo_keeps_previous_cache(self, monkeypatch):
        """Все фразы — эхо захардкоженного списка → кэш не затирается."""
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {
            "patterns": [{"code": "dyn_keep", "phrase": "живая фраза"}],
            "source": "wikipedia", "source_url": "u", "version": 2,
            "fetched_at": "2026-01-01T00:00:00+00:00", "last_status": "ok",
        }
        echo = json.dumps({"patterns": [{"phrase": "подводя итог"},
                                        {"phrase": "надеюсь, помог"}]})
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value=echo)
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        result = await worker.refresh()
        assert result["status"] == "empty"
        assert store.row["patterns"][0]["phrase"] == "живая фраза"
        assert store.row["version"] == 2

    @pytest.mark.asyncio
    async def test_apply_manual(self):
        store = _Store()
        store.row = {"patterns": [], "source": "wikipedia", "source_url": "u",
                     "version": 1,
                     "fetched_at": "2026-01-01T00:00:00+00:00",
                     "last_status": "ok"}
        result = await aw.apply_manual(_FakePg(store),
                                       [{"phrase": "ручная фраза"}])
        assert result["status"] == "ok"
        assert store.row["source"] == "manual"
        assert store.row["patterns"][0]["phrase"] == "ручная фраза"
        # L3: ручная правка не двигает fetched_at.
        assert store.row["fetched_at"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_apply_manual_allows_empty(self):
        """Пустая запись допустима только через явный ручной PUT."""
        store = _Store()
        store.row = {"patterns": [{"code": "dyn_x", "phrase": "фраза"}],
                     "source": "wikipedia", "source_url": "u", "version": 1,
                     "fetched_at": "2026-01-01T00:00:00+00:00",
                     "last_status": "ok"}
        result = await aw.apply_manual(_FakePg(store), [])
        assert result["count"] == 0
        assert store.row["patterns"] == []

    @pytest.mark.asyncio
    async def test_refresh_disabled(self, monkeypatch):
        monkeypatch.setattr(Settings, "DYNAMIC_ANTICLICHE_ENABLED", False)
        worker = _worker(_Store(), llm=AsyncMock())
        assert (await worker.refresh())["status"] == "disabled"


class TestWorkerScheduler:
    def test_start_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setattr(Settings, "DYNAMIC_ANTICLICHE_ENABLED", False)
        worker = AntiClicheWorker(llm=AsyncMock(), pg=None)
        worker.start()
        assert worker._scheduler is None

    def test_start_registers_job(self, monkeypatch):
        class _Sched:
            def __init__(self, running=False):
                self.jobs = []
                self.running = running
                self.start_calls = 0

            def add_job(self, *a, **k):
                self.jobs.append((a, k))

            def start(self):
                self.start_calls += 1
                self.running = True

        sched = _Sched()
        worker = AntiClicheWorker(llm=AsyncMock(), pg=None, scheduler=sched)
        worker.start()
        assert sched.running is True
        assert sched.start_calls == 1
        assert sched.jobs and sched.jobs[0][1]["id"] == aw._JOB_ID
        assert sched.jobs[0][1]["coalesce"] is True
        assert sched.jobs[0][1]["max_instances"] == 1

    def test_start_does_not_restart_running_scheduler(self):
        """Review iter1 L8: внешний запущенный планировщик не перезапускаем."""
        class _Sched:
            def __init__(self):
                self.running = True
                self.start_calls = 0
                self.jobs = []

            def add_job(self, *a, **k):
                self.jobs.append((a, k))

            def start(self):
                self.start_calls += 1

        sched = _Sched()
        worker = AntiClicheWorker(llm=AsyncMock(), pg=None, scheduler=sched)
        worker.start()
        assert sched.start_calls == 0
        assert sched.jobs


class TestDdlIdempotent:
    def test_ddl_contains_anticliche_table(self):
        from services.pg_db import DDL_STATEMENTS
        joined = "\n".join(DDL_STATEMENTS)
        assert "CREATE TABLE IF NOT EXISTS anticliche_cache" in joined
        assert "CREATE INDEX IF NOT EXISTS idx_anticliche_cache_updated" in joined
        assert ("INSERT INTO anticliche_cache (id) VALUES (1) "
                "ON CONFLICT (id) DO NOTHING") in joined

    def test_seed_and_index_idempotent(self):
        from services.pg_db import DDL_STATEMENTS
        for statement in DDL_STATEMENTS:
            flat = " ".join(statement.split())
            if "anticliche_cache" in flat:
                assert ("IF NOT EXISTS" in flat or "DO NOTHING" in flat
                        or "DROP" in flat)


# ── API ─────────────────────────────────────────────────────────────────────

TEST_TOKEN = "123456:TEST_TOKEN_ANTICLICHE"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


def _make_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _make_init_data(user_id)}


class _ApiConn:
    def __init__(self, store: _Store):
        self.store = store
        self._roles = [
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False, "role_type": "global_admin"},
            {"role_name": "moderator", "permissions": {"sections": ["limits"]},
             "is_custom": False, "role_type": "moderator"},
            {"role_name": "user", "permissions": {}, "is_custom": False,
             "role_type": "user"},
        ]
        self._admins = [
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"},
            {"telegram_id": MODERATOR_ID, "role_name": "moderator",
             "added_by": ADMIN_ID, "created_at": "2026-09-07T00:00:01+00:00"},
        ]
        self._inner = _FakeConn(store)

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return list(self._roles)
        if "FROM bot_admins" in sql:
            return list(self._admins)
        return []

    async def fetchrow(self, sql, *args):
        return await self._inner.fetchrow(sql, *args)

    async def execute(self, sql, *args):
        return await self._inner.execute(sql, *args)


@pytest.fixture
def api_client(monkeypatch):
    from web.api import deps as deps_mod
    from web.app import create_app
    from services.config_cache import ConfigCache
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    store = _Store()
    store.row = {
        "patterns": [{"code": "dyn_abc", "phrase": "старый штамп",
                      "origin": "wiki", "added_at": "2026-09-19"}],
        "source": "wikipedia", "source_url": "u", "version": 2,
        "fetched_at": "2026-09-19T00:00:00+00:00",
        "updated_at": "2026-09-19T00:00:00+00:00", "last_status": "ok",
    }

    class _Pg:
        def __init__(self):
            self.pool = _FakePool(_ApiConn(store))

        async def connect(self):
            pass

        async def init(self, seed_settings: bool = True):
            pass

        async def close(self):
            pass

    cache = ConfigCache(pg=_Pg(), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.store = store
        yield tc


class TestAnticlicheApi:
    def test_get_401_without_init_data(self, api_client):
        assert api_client.get("/api/anticliche").status_code == 401

    def test_get_403_for_non_admin(self, api_client):
        assert api_client.get("/api/anticliche",
                              headers=_hdr(MODERATOR_ID)).status_code == 403

    def test_get_returns_patterns(self, api_client):
        resp = api_client.get("/api/anticliche", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "wikipedia"
        assert body["version"] == 2
        assert body["count"] == 1
        assert body["patterns"][0]["code"] == "dyn_abc"
        assert body["max_patterns"] == ac.max_patterns()

    def test_get_returns_resolved_max_patterns(self, api_client, monkeypatch):
        """F7/ADR-1024-3 D1: API отдаёт резолвленный лимит (не хардкод 20)."""
        monkeypatch.setattr(ac, "settings", types.SimpleNamespace(
            ANTICLICHE_MAX_PATTERNS=350))
        resp = api_client.get("/api/anticliche", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["max_patterns"] == 350

    def test_put_manual_edit(self, api_client):
        resp = api_client.put(
            "/api/anticliche", headers=_hdr(ADMIN_ID),
            json={"patterns": [{"phrase": "новая ручная фраза"}]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "manual"
        assert body["count"] == 1
        assert api_client.store.row["patterns"][0]["phrase"] == "новая ручная фраза"

    def test_put_422_over_cap(self, api_client):
        payload = {"patterns": [{"phrase": f"фраза {i}"} for i in range(201)]}
        resp = api_client.put("/api/anticliche", headers=_hdr(ADMIN_ID),
                              json=payload)
        assert resp.status_code == 422

    def test_put_422_phrase_too_long(self, api_client):
        """L4: длина фразы ограничена до regex-нормализации."""
        payload = {"patterns": [{"phrase": "я" * 501}]}
        resp = api_client.put("/api/anticliche", headers=_hdr(ADMIN_ID),
                              json=payload)
        assert resp.status_code == 422

    def test_put_manual_preserves_fetched_at(self, api_client):
        before = api_client.store.row["fetched_at"]
        resp = api_client.put(
            "/api/anticliche", headers=_hdr(ADMIN_ID),
            json={"patterns": [{"phrase": "ручная фраза"}]})
        assert resp.status_code == 200
        assert api_client.store.row["fetched_at"] == before

    def test_post_refresh_uses_runtime_worker(self, api_client, monkeypatch):
        worker = AsyncMock()
        worker.refresh = AsyncMock(return_value={
            "status": "ok", "count": 4, "version": 3, "source": "wikipedia"})
        monkeypatch.setattr(aw, "get_runtime_worker", lambda: worker)
        resp = api_client.post("/api/anticliche/refresh", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["count"] == 4
        assert worker.refresh.await_count == 1

    def test_post_refresh_503_without_worker(self, api_client, monkeypatch):
        monkeypatch.setattr(aw, "get_runtime_worker", lambda: None)
        resp = api_client.post("/api/anticliche/refresh", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503
