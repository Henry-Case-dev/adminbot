"""AC-DATA (FINAL v8 §2.1/§2.2/§3.1/§3.2) — источники, статусы, LKG, здоровье.

Проверяется именно пользовательский контракт, а не внутренние детали:

* таксономия статусов §3.2 по реальным ответам (200/304/403-policy/401/429/
  timeout/HTML вместо данных/404/5xx) — тесты 1,4,5,6,7,8 §9.2;
* 403 robot-policy НЕ ретраится автоматически, а 401/403 без признака
  политики не выдаются за policy_blocked (тест 6);
* 429 уважает `Retry-After` (правильный `next_attempt_at`, без hammering);
* независимость источников: сбой Wikipedia не блокирует остальные, статусы и
  записи о проверках независимы (тесты 1,2,12);
* LKG: ошибка любого источника/модели/PG не обнуляет версию и не даёт ложных
  «0 правил» (тесты 9,12,13, AC-INV-08);
* lineage: общая upstream-база не даёт «двойного подтверждения» (тест 16);
* `local/manual` без HTTP и библиография без авто-scraping (тесты 14,15);
* четыре независимых вида здоровья (§2.2): все источники заблокированы, а
  runtime-эффективность по-прежнему работает.

Сеть не используется: транспорт инъектируется.
"""
from __future__ import annotations

import datetime
import json

import pytest

from services import anticliche_cache as ac
from services import anticliche_sources as srcs
from services import anticliche_worker as aw
from services.anticliche_worker import AntiClicheWorker

pytestmark = pytest.mark.system2

NOW = datetime.datetime(2026, 11, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)


# ── фейковый транспорт ─────────────────────────────────────────────────────
def _wiki_body(text: str) -> str:
    return json.dumps({"query": {"pages": {"1": {"extract": text}}}})


def _transport(mapping, *, raise_for=None):
    """url → TransportResponse; отсутствующий url → 404; ``raise_for`` бросает."""

    async def _call(url, headers=None):
        if raise_for and raise_for in url:
            raise TimeoutError("simulated timeout")
        value = mapping.get(url)
        if value is None:
            return srcs.TransportResponse(status=404, text="not found")
        if isinstance(value, srcs.TransportResponse):
            return value
        if isinstance(value, dict):
            return srcs.TransportResponse(**value)
        return srcs.TransportResponse(status=200, text=str(value))

    return _call


def _source(source_id="test-a", **kwargs) -> srcs.Source:
    base = dict(
        source_id=source_id,
        title=source_id,
        kind=srcs.KIND_HTTP,
        url=f"https://{source_id}.example/doc.md",
        document_paths=("doc.md",),
        licence=srcs.Licence("MIT", "test", True, True),
        enabled_by_default=True,
        auto_check=True,
        retry=srcs.RetryPolicy(base_seconds=60, max_seconds=600, jitter=0.0),
    )
    base.update(kwargs)
    return srcs.Source(**base)


def _wiki_source(**kwargs) -> srcs.Source:
    base = dict(
        source_id="test-wiki",
        title="test wiki",
        kind=srcs.KIND_WIKI,
        url="https://wiki.example/api.php?t=Test",
        document_paths=("Test",),
        licence=srcs.Licence("CC BY-SA 4.0", "wiki", True, True),
        enabled_by_default=True,
        expected_format=srcs.FORMAT_WIKI_JSON,
        retry=srcs.RetryPolicy(base_seconds=60, max_seconds=600, jitter=0.0),
    )
    base.update(kwargs)
    return srcs.Source(**base)


@pytest.fixture(autouse=True)
def _reset_state():
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)
    yield
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)


# ── §3.2: классификация ответов ────────────────────────────────────────────
class TestStatusTaxonomy:
    @pytest.mark.parametrize("status,headers,body,expected", [
        (200, {}, "ok", srcs.STATUS_AVAILABLE),
        (304, {}, "", srcs.STATUS_UNCHANGED),
        (401, {}, "unauthorized", srcs.STATUS_AUTH_FAILED),
        (403, {}, "forbidden", srcs.STATUS_AUTH_FAILED),
        (403, {}, "blocked by robot policy for automated access",
         srcs.STATUS_POLICY_BLOCKED),
        (403, {"x-ratelimit-remaining": "0"}, "API rate limit exceeded",
         srcs.STATUS_RATE_LIMITED),
        (429, {"retry-after": "120"}, "slow down", srcs.STATUS_RATE_LIMITED),
        (404, {}, "", srcs.STATUS_MISSING),
        (410, {}, "", srcs.STATUS_MISSING),
        (500, {}, "boom", srcs.STATUS_NETWORK_ERROR),
        (503, {}, "unavailable", srcs.STATUS_NETWORK_ERROR),
    ])
    def test_transport_classification(self, status, headers, body, expected):
        assert srcs.classify_response(status=status, headers=headers,
                                      body=body) == expected

    def test_single_403_is_not_policy_block(self):
        """Тест 6 §9.2: код 403 сам по себе не означает robot-policy."""
        as_auth = srcs.classify_response(status=403, headers={}, body="")
        assert as_auth == srcs.STATUS_AUTH_FAILED
        assert as_auth != srcs.STATUS_POLICY_BLOCKED
        # положительный признак политики переводит в policy_blocked
        assert srcs.classify_response(
            status=403, headers={"x-robots-tag": "noindex, robot policy"},
            body="") == srcs.STATUS_POLICY_BLOCKED

    def test_timeout_is_network_error(self):
        assert srcs.classify_exception(TimeoutError("t")) == \
            srcs.STATUS_NETWORK_ERROR
        assert srcs.classify_exception(RuntimeError("dns")) == \
            srcs.STATUS_NETWORK_ERROR

    def test_every_status_has_honest_label(self):
        for status in srcs.ALL_STATUSES:
            meta = srcs.status_meta(status)
            assert meta["label"]
            assert meta["tone"] in ("ok", "warn", "error", "neutral")
        assert srcs.status_meta("bogus")["tone"] != "ok"

    @pytest.mark.asyncio
    async def test_html_instead_of_markdown_is_parse_error(self):
        """/9.2 тест 8/: транспорт успешен, контент не разобран."""
        source = _source()
        check = await srcs.check_source(
            source, transport=_transport({
                source.url: srcs.TransportResponse(
                    status=200, text="<!doctype html><html><body>captcha")}),
            now=NOW)
        # §3.2: «Источник доступен, формат не распознан» — это parse_error,
        # при этом реальный HTTP-код остаётся видимым (не маскируется).
        assert check["status"] == srcs.STATUS_PARSE_ERROR
        assert check["http_status"] == 200
        assert check["content_status"] == srcs.STATUS_PARSE_ERROR
        assert check["docs_parsed"] == 0
        assert check["error_code"] == "html_instead_of_markdown"

    @pytest.mark.asyncio
    async def test_invalid_json_wiki_is_parse_error(self):
        source = _wiki_source()
        check = await srcs.check_source(
            source, transport=_transport({source.url: "не json вообще"}),
            now=NOW)
        assert check["status"] == srcs.STATUS_PARSE_ERROR
        assert check["content_status"] == srcs.STATUS_PARSE_ERROR
        assert check["docs_parsed"] == 0

    @pytest.mark.asyncio
    async def test_empty_document_is_not_ready_for_analysis(self):
        source = _source()
        check = await srcs.check_source(
            source, transport=_transport({source.url: "   \n  "}), now=NOW)
        assert check["content_status"] == "empty"
        assert check["docs_parsed"] == 0
        assert check["status"] != srcs.STATUS_UNCHANGED

    @pytest.mark.asyncio
    async def test_missing_document_is_missing(self):
        source = _source()
        check = await srcs.check_source(
            source, transport=_transport({}), now=NOW)
        assert check["status"] == srcs.STATUS_MISSING
        assert check["error_code"] == srcs.STATUS_MISSING


# ── retry / anti-storm ─────────────────────────────────────────────────────
class TestRetryPolicy:
    def test_retry_after_honoured_exactly(self):
        policy = srcs.RetryPolicy(base_seconds=60, max_seconds=600)
        next_at, reason = srcs.compute_next_attempt(
            srcs.STATUS_RATE_LIMITED, policy, 1,
            retry_after_at=NOW + datetime.timedelta(seconds=120), now=NOW)
        assert reason == "retry_after"
        assert next_at == NOW + datetime.timedelta(seconds=120)

    def test_retry_after_capped_by_policy(self):
        policy = srcs.RetryPolicy(base_seconds=60, max_seconds=600,
                                  max_retry_after_seconds=300)
        next_at, _ = srcs.compute_next_attempt(
            srcs.STATUS_RATE_LIMITED, policy, 1,
            retry_after_at=NOW + datetime.timedelta(days=30), now=NOW)
        assert next_at == NOW + datetime.timedelta(seconds=300)

    def test_backoff_is_bounded(self):
        policy = srcs.RetryPolicy(base_seconds=60, max_seconds=600,
                                  jitter=0.0)
        delays = [srcs.compute_backoff_seconds(policy, n)
                  for n in range(1, 25)]
        assert delays[0] == 60
        assert delays[-1] == 600
        assert max(delays) <= 600
        assert all(d >= 60 for d in delays)

    def test_policy_block_has_no_automatic_retry(self):
        policy = srcs.RetryPolicy(policy_cooldown_seconds=None)
        next_at, reason = srcs.compute_next_attempt(
            srcs.STATUS_POLICY_BLOCKED, policy, 3, now=NOW)
        assert next_at is None
        assert reason == "policy_blocked"

    def test_policy_block_state_blocks_automatic_attempt(self):
        state = {"last_status": srcs.STATUS_POLICY_BLOCKED,
                 "next_attempt_at": None, "paused_reason": "policy_blocked"}
        decision = srcs.attempt_decision(state)
        assert decision["allowed"] is False
        assert decision["reason"] == "policy_blocked"

    def test_manual_check_allowed_once_for_policy_block(self):
        state = {"last_status": srcs.STATUS_POLICY_BLOCKED}
        assert srcs.attempt_decision(state, manual=True)["allowed"] is True

    def test_backoff_state_waits(self):
        state = {"last_status": srcs.STATUS_NETWORK_ERROR,
                 "next_attempt_at": (NOW + datetime.timedelta(minutes=5))}
        decision = srcs.attempt_decision(state, now=NOW)
        assert decision["allowed"] is False
        assert decision["wait_seconds"] == 300

    @pytest.mark.asyncio
    async def test_policy_blocked_check_schedules_nothing(self):
        source = _wiki_source()
        check = await srcs.check_source(
            source, transport=_transport({
                source.url: srcs.TransportResponse(
                    status=403,
                    text="Wikimedia robot policy: automated access blocked")}),
            now=NOW)
        assert check["status"] == srcs.STATUS_POLICY_BLOCKED
        assert check["next_attempt_at"] is None
        assert check["paused_reason"] == "policy_blocked"

    @pytest.mark.asyncio
    async def test_rate_limited_check_schedules_retry_after(self):
        source = _source()
        check = await srcs.check_source(
            source, transport=_transport({
                source.url: srcs.TransportResponse(
                    status=429, headers={"retry-after": "120"},
                    text="slow down")}), now=NOW)
        assert check["status"] == srcs.STATUS_RATE_LIMITED
        assert check["next_attempt_at"].startswith("2026-11-03T12:02:00")


# ── независимость источников ───────────────────────────────────────────────
class TestSourceIndependence:
    @pytest.mark.asyncio
    async def test_wiki_policy_block_does_not_affect_others(self):
        """AC-INV-09 / тест 3: сбой Wikipedia не блокирует другие источники."""
        wiki = _wiki_source()
        other = _source("test-b")
        text = "Подводя итог, важно отметить: это шаблонный текст."
        checks = await srcs.check_sources(
            [wiki, other], transport=_transport({
                wiki.url: srcs.TransportResponse(
                    status=403, text="robot policy: automated requests are "
                                     "not permitted"),
                other.url: text}), now=NOW)
        by_id = {c["source_id"]: c for c in checks}
        assert by_id["test-wiki"]["status"] == srcs.STATUS_POLICY_BLOCKED
        assert by_id["test-b"]["status"] == srcs.STATUS_AVAILABLE
        assert by_id["test-b"]["docs_parsed"] == 1
        assert by_id["test-b"]["changed"] is True
        # независимые записи проверок, не общая «ошибка»
        assert by_id["test-wiki"]["check_id"] != by_id["test-b"]["check_id"]

    @pytest.mark.asyncio
    async def test_transport_exception_is_isolated(self):
        broken = _source("test-broken",
                         url="https://broken.example/doc.md")
        healthy = _source("test-ok", url="https://ok.example/doc.md")
        checks = await srcs.check_sources(
            [broken, healthy],
            transport=_transport({healthy.url: "Достаточно длинный текст "
                                              "справочника о штампах."},
                                 raise_for="broken.example"),
            now=NOW)
        by_id = {c["source_id"]: c for c in checks}
        assert by_id["test-broken"]["status"] == srcs.STATUS_NETWORK_ERROR
        assert by_id["test-ok"]["status"] == srcs.STATUS_AVAILABLE

    @pytest.mark.asyncio
    async def test_github_revision_and_paths(self):
        """AC-SRC-RU-A: adapter contract, реальная ревизия и ожидаемые пути."""
        source = srcs.get_source("ru-repo-a")
        assert source is not None
        api = f"https://api.github.com/repos/{source.origin_repo}"
        tree_paths = list(source.document_paths)
        mapping = {
            api: json.dumps({
                "default_branch": "main",
                "license": {"spdx_id": "NOASSERTION"},
                "archived": False}),
            f"{api}/commits?per_page=1": json.dumps([
                {"sha": "324b155571b52e97c7f7027eefdbc7e908614bc7",
                 "commit": {"committer": {"date": "2026-06-03T16:48:47Z"}}}]),
            f"{api}/git/trees/main?recursive=1": json.dumps(
                {"tree": [{"path": p} for p in tree_paths]}),
        }
        for path in source.document_paths:
            mapping[srcs.raw_document_url(
                source, path, "324b155571b52e97c7f7027eefdbc7e908614bc7")] = (
                f"# {path}\n\nСправочник штампов: подводя итог, стоит "
                "отметить, что данное предложение демонстрирует канцелярит.")
        check = await srcs.check_source(
            source, transport=_transport(mapping), now=NOW, manual=True)
        assert check["status"] == srcs.STATUS_AVAILABLE
        assert check["revision"] == "324b155571b52e97c7f7027eefdbc7e908614bc7"
        assert check["docs_fetched"] == len(source.document_paths)
        assert check["docs_parsed"] == len(source.document_paths)
        assert check["content_status"] == "parsed"
        assert check["text"]
        assert check["changed"] is True

    @pytest.mark.asyncio
    async def test_github_missing_path_is_not_green(self):
        source = srcs.get_source("ru-repo-b")
        api = f"https://api.github.com/repos/{source.origin_repo}"
        mapping = {
            api: json.dumps({"default_branch": "main",
                             "license": {"spdx_id": "MIT"}}),
            f"{api}/commits?per_page=1": json.dumps(
                [{"sha": "17e91018207eee1557b472ee1823d3788aed4161",
                  "commit": {"committer": {"date": "2026-05-05T07:47:20Z"}}}]),
            f"{api}/git/trees/main?recursive=1": json.dumps({"tree": []}),
        }
        check = await srcs.check_source(
            source, transport=_transport(mapping), now=NOW, manual=True)
        assert check["status"] == srcs.STATUS_MISSING
        assert check["error_code"] == "no_expected_documents"
        assert check["docs_parsed"] == 0
        assert not check["changed"]

    @pytest.mark.asyncio
    async def test_unchanged_revision_keeps_version(self):
        """Тест 9 §9.2: 304/та же ревизия → 0 LLM-вызовов и та же версия."""
        llm_calls = []

        class _Llm:
            async def generate_worker(self, *a, **kw):  # pragma: no cover
                llm_calls.append(1)
                return '{"patterns": []}'

        wiki = _wiki_source()
        store = _StateStore()
        store.cache_row = {
            "patterns": [{"code": "dyn_old", "phrase": "старый штамп"}],
            "source": "wikipedia", "source_url": "u", "version": 4,
            "fetched_at": "2026-10-01T00:00:00+00:00",
            "updated_at": "2026-10-01T00:00:00+00:00", "last_status": "ok"}
        manifest = {"checksum": srcs.checksum_text(
            "Достаточно длинный текст справочника о штампах.")}
        store.source_states = [{
            "source_id": wiki.source_id, "enabled": True,
            "last_status": srcs.STATUS_AVAILABLE,
            "revision": "rev-1", "checksum": manifest["checksum"],
            "etag": "etag-1", "content_status": "parsed",
            "docs_fetched": 1, "docs_parsed": 1,
            "last_check_at": NOW - datetime.timedelta(days=1),
            "consecutive_failures": 0}]
        worker = AntiClicheWorker(llm=_Llm(), pg=_FakePg(store),
                                  sources=(wiki,),
                                  transport=_transport({
                                      wiki.url: _wiki_body(
                                          "Достаточно длинный текст "
                                          "справочника о штампах.")}))
        result = await worker.refresh(force=True)
        assert result["status"] == "unchanged"
        assert result["version"] == 4
        assert llm_calls == []
        assert store.cache_row["version"] == 4


# ── LKG и отсутствие ложных нулей ──────────────────────────────────────────
class _StateStore:
    """Хранилище состояния источника + singleton кэша (эмуляция PG)."""

    def __init__(self):
        self.source_states: list[dict] = []
        self.cache_row = None
        self.snapshot_rows: list[dict] = []
        self.snapshot_error: Exception | None = None


class _StateConn:
    def __init__(self, store: _StateStore):
        self.store = store

    async def fetchrow(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("SELECT patterns"):
            return dict(self.store.cache_row) if self.store.cache_row else None
        if flat.startswith("INSERT INTO anticliche_cache"):
            patterns, source, source_url, status, fetched_at = args
            prev = self.store.cache_row or {}
            version = int(prev.get("version") or 0) + 1
            self.store.cache_row = {
                "patterns": patterns, "source": source,
                "source_url": source_url, "version": version,
                "fetched_at": fetched_at if fetched_at is not None
                else prev.get("fetched_at"),
                "updated_at": "2026-11-03T12:00:00+00:00",
                "last_status": status,
            }
            return {"version": version}
        if "FROM anticliche_snapshot" in flat:
            if self.store.snapshot_error is not None:
                raise self.store.snapshot_error
            row = (self.store.snapshot_rows or [None])[0]
            return dict(row) if row else None
        if "FROM anticliche_cache" in flat:
            return dict(self.store.cache_row) if self.store.cache_row else None
        return None

    async def fetch(self, sql, *args):
        if "FROM anticliche_source_state" in " ".join(sql.split()):
            return [dict(row) for row in self.store.source_states]
        return []

    async def execute(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("UPDATE anticliche_cache"):
            if self.store.cache_row is None:
                self.store.cache_row = {"patterns": [], "source": "",
                                        "source_url": "", "version": 0,
                                        "last_status": "never"}
            self.store.cache_row["last_status"] = args[0]
            return "UPDATE 1"
        if flat.startswith("INSERT INTO anticliche_source_state"):
            (source_id, enabled, last_check_at, last_status, last_http,
             revision, etag, checksum, content_status, docs_fetched,
             docs_parsed, bytes_fetched, last_success_fetch_at,
             last_success_analysis_at, last_analysis_status, next_attempt_at,
             last_error_code, last_error_detail, failures, paused_reason,
             check_id) = args
            current = next((row for row in self.store.source_states
                            if row["source_id"] == source_id), None)
            if current is None:
                current = {"source_id": source_id}
                self.store.source_states.append(current)
            for key, value in (
                ("enabled", enabled), ("last_check_at", last_check_at),
                ("last_status", last_status), ("last_http", last_http),
                ("revision", revision), ("etag", etag),
                ("checksum", checksum), ("content_status", content_status),
                ("docs_fetched", docs_fetched), ("docs_parsed", docs_parsed),
                ("bytes_fetched", bytes_fetched),
                ("next_attempt_at", next_attempt_at),
                ("last_error_code", last_error_code),
                ("last_error_detail", last_error_detail),
                ("consecutive_failures", failures),
                ("paused_reason", paused_reason),
                ("last_check_id", check_id),
                ("last_analysis_status", last_analysis_status),
            ):
                current[key] = value
            # COALESCE-семантика: успешное прошлое не теряется из-за сбоя.
            if last_success_fetch_at is not None:
                current["last_success_fetch_at"] = last_success_fetch_at
            if last_success_analysis_at is not None:
                current["last_success_analysis_at"] = \
                    last_success_analysis_at
            return "INSERT 0 1"
        return "UPDATE 1"


class _StatePool:
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
    def __init__(self, store: _StateStore):
        self.store = store
        self.pool = _StatePool(_StateConn(store))


class TestLastKnownGood:
    @pytest.mark.asyncio
    async def test_snapshot_wins_when_present(self):
        store = _StateStore()
        store.snapshot_rows = [{
            "version": 18, "effective_rule_count": 42, "state": "published",
            "published_at": "2026-11-02T07:23:00+00:00",
            "checksum": "abc", "compiler_version": "c1", "publisher": "auto",
            "parent_version": 17}]
        store.cache_row = {"patterns": [{"phrase": "x"}], "version": 18,
                           "updated_at": "2026-11-02T07:23:00+00:00",
                           "source": "ru-repo-b", "fetched_at": None}
        active = await ac.read_active_version(_FakePg(store))
        assert active["status"] == "ok"
        assert active["version"] == 18
        assert active["rules"] == 42
        assert active["bank_source"] == "snapshot"

    @pytest.mark.asyncio
    async def test_unreadable_snapshot_falls_back_to_cache_with_version(self):
        store = _StateStore()
        store.snapshot_error = RuntimeError("relation does not exist")
        store.cache_row = {
            "patterns": [{"phrase": "a"}, {"phrase": "b"}], "version": 7,
            "updated_at": "2026-10-02T00:00:00+00:00", "source": "wikipedia",
            "fetched_at": None}
        active = await ac.read_active_version(_FakePg(store))
        assert active["status"] == "lkg"
        assert active["version"] == 7
        assert active["rules"] == 2
        assert active["bank_source"] == "cache"

    @pytest.mark.asyncio
    async def test_empty_bank_is_honest_none(self):
        store = _StateStore()
        store.cache_row = {"patterns": [], "version": 3,
                           "updated_at": "2026-10-02T00:00:00+00:00",
                           "source": "", "fetched_at": None}
        active = await ac.read_active_version(_FakePg(store))
        assert active["status"] == "none"
        assert active["rules"] == 0

    @pytest.mark.asyncio
    async def test_pg_down_is_unavailable_not_zero(self):
        active = await ac.read_active_version(None)
        assert active["status"] == "unavailable"
        assert active["version"] is None
        assert active["rules"] is None

    @pytest.mark.asyncio
    async def test_all_sources_down_keeps_published_version(self):
        """Тесты 12,13 §9.2 + AC-INV-08: нет нового publish, нет версии 0."""
        store = _StateStore()
        store.cache_row = {
            "patterns": [{"code": "dyn_keep", "phrase": "живой штамп"}],
            "source": "wikipedia", "source_url": "u", "version": 9,
            "fetched_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00", "last_status": "ok"}
        wiki = _wiki_source()
        worker = AntiClicheWorker(
            llm=None, pg=_FakePg(store), sources=(wiki,),
            transport=_transport({
                wiki.url: srcs.TransportResponse(
                    status=403, text="robot policy: no automated access")}))
        result = await worker.refresh(force=True)
        assert result["status"] == "fetch_error"
        assert result["version"] == 9          # не 0
        assert result["rules"] == 1
        assert store.cache_row["patterns"][0]["phrase"] == "живой штамп"
        assert store.cache_row["version"] == 9
        assert store.cache_row["last_status"] == "sources_unavailable"

    @pytest.mark.asyncio
    async def test_failure_after_success_keeps_last_success_timestamps(self):
        """Тест 17 §9.2: исторические успехи переживают сбой и «рестарт»."""
        store = _StateStore()
        pg = _FakePg(store)
        source = _source()
        first = await srcs.check_source(
            source, transport=_transport({source.url: "Достаточно длинный "
                                                     "текст справочника."}),
            now=NOW)
        await srcs.record_check(pg, first, source=source, previous=None)
        row = store.source_states[0]
        assert row["last_status"] == srcs.STATUS_AVAILABLE
        assert row["last_success_fetch_at"] is not None
        # новая «сессия» читает то же хранилище
        states = await srcs.fetch_states(pg)
        assert states["test-a"]["last_status"] == srcs.STATUS_AVAILABLE
        failing = await srcs.check_source(
            source, transport=_transport({source.url: srcs.TransportResponse(
                status=503, text="down")}), state=states["test-a"], now=NOW)
        await srcs.record_check(pg, failing, source=source,
                                previous=states["test-a"])
        row = store.source_states[0]
        assert row["last_status"] == srcs.STATUS_NETWORK_ERROR
        assert row["consecutive_failures"] == 1
        assert row["last_success_fetch_at"] is not None   # не потерян
        assert row["revision"] == ""                      # честно: не обновился


# ── четыре вида здоровья ──────────────────────────────────────────────────
class _Views:
    def __init__(self, views):
        self.views = views

    @staticmethod
    def blocked_states():
        return [
            {"source_id": "ru-repo-a", "enabled": True,
             "last_status": srcs.STATUS_POLICY_BLOCKED,
             "last_check_at": NOW - datetime.timedelta(days=1),
             "content_status": "not_checked",
             "docs_fetched": 0, "docs_parsed": 0},
            {"source_id": "ru-repo-b", "enabled": True,
             "last_status": srcs.STATUS_NETWORK_ERROR,
             "last_check_at": NOW - datetime.timedelta(days=1),
             "content_status": "not_checked",
             "docs_fetched": 0, "docs_parsed": 0},
        ]

    @staticmethod
    def blocked_views():
        return srcs.build_views(
            {row["source_id"]: row for row in _Views.blocked_states()},
            sources=(srcs.get_source("ru-repo-a"),
                     srcs.get_source("ru-repo-b")),
            now=NOW)


class TestFourHealthKinds:
    def _views(self):
        return srcs.build_views(
            {row["source_id"]: row for row in _Views.blocked_states()},
            sources=(srcs.get_source("ru-repo-a"),
                     srcs.get_source("ru-repo-b")),
            now=NOW)

    def test_kinds_are_separate_fields(self):
        views = self._views()
        health = srcs.build_health(
            views,
            active_version={"status": "ok", "version": 18, "rules": 42,
                            "bank_source": "snapshot",
                            "published_at": "2026-11-02T07:23:00+00:00"},
            enabled=True,
            compiler={"available": True, "module": "services.anticliche_compile",
                      "version": "1", "reason": ""})
        assert set(health) == {"reachability", "content", "analysis", "runtime"}
        # все источники заблокированы, но runtime эффективен (§2.2 п.4)
        assert health["reachability"]["status"] == "blocked"
        assert health["content"]["status"] == "unknown"
        assert health["analysis"]["status"] == "not_run"
        assert health["runtime"]["status"] == "works"
        assert health["runtime"]["works"] is True

    def test_runtime_previous_version_when_bank_is_lkg(self):
        health = srcs.build_health(
            _Views.blocked_views(),
            active_version={"status": "lkg", "version": 7, "rules": 5,
                            "bank_source": "cache", "reason": "snapshot_absent"},
            enabled=True, compiler={"available": True, "module": "m",
                                    "version": "1", "reason": ""})
        assert health["runtime"]["status"] == "works_previous_version"
        assert health["runtime"]["active_version"] == 7

    def test_runtime_no_rules_is_not_error(self):
        health = srcs.build_health(
            [], active_version={"status": "none", "version": None, "rules": 0},
            enabled=True, compiler={"available": True, "module": "m",
                                    "version": "1", "reason": ""})
        assert health["runtime"]["status"] == "no_published_rules"

    def test_runtime_compiler_error_is_own_state(self):
        health = srcs.build_health(
            [], active_version={"status": "ok", "version": 3, "rules": 4,
                                "bank_source": "snapshot"},
            enabled=True, compiler={"available": False, "module": "m",
                                    "reason": "compile_hint_missing"})
        assert health["runtime"]["status"] == "compiler_error"

    def test_runtime_unavailable_when_pg_down(self):
        health = srcs.build_health(
            [], active_version={"status": "unavailable", "version": None,
                                "rules": None},
            enabled=True, compiler={"available": True, "module": "m",
                                    "version": "1", "reason": ""})
        assert health["runtime"]["status"] == "unavailable"

    def test_analysis_independent_from_reachability(self):
        states = {
            "ru-repo-a": {"source_id": "ru-repo-a", "enabled": True,
                          "last_status": srcs.STATUS_RATE_LIMITED,
                          "content_status": "parsed", "docs_fetched": 3,
                          "docs_parsed": 3,
                          "last_analysis_status": "completed",
                          "last_success_analysis_at": "2026-11-02T07:23:00+00:00"},
        }
        views = srcs.build_views(states, now=NOW)
        health = srcs.build_health(views)
        assert health["reachability"]["status"] == "blocked" or \
            health["reachability"]["status"] == "degraded"
        assert health["content"]["status"] == "ready"
        assert health["analysis"]["status"] == "completed"
        assert health["analysis"]["last_success_at"] == \
            "2026-11-02T07:23:00+00:00"


# ── local/manual, библиография, lineage ────────────────────────────────────
class TestLocalAndBibliography:
    @pytest.mark.asyncio
    async def test_local_source_has_no_http_status(self):
        source = srcs.get_source("local/manual")
        pg = _FakePg(_StateStore())
        check = await srcs.check_source(source, pg=pg, now=NOW)
        assert check["status"] == srcs.STATUS_AVAILABLE
        assert check["http_status"] is None
        assert check["transport"] == "local"
        view = srcs.source_view(source, {
            "source_id": "local/manual", "enabled": True,
            "last_status": srcs.STATUS_AVAILABLE, "last_http": None,
            "last_check_at": NOW, "content_status": "not_applicable"},
            now=NOW)
        assert view["transport"] == "local"
        assert view["reachability"]["transport_code"] == "local"
        assert view["reachability"]["http_status"] is None

    @pytest.mark.asyncio
    async def test_local_source_db_error(self):
        source = srcs.get_source("local/manual")
        check = await srcs.check_source(source, pg=None, now=NOW)
        assert check["status"] == srcs.STATUS_DB_ERROR
        assert check["error_code"] == "pg_unavailable"
        assert check["http_status"] is None

    @pytest.mark.asyncio
    async def test_bibliography_is_never_fetched(self):
        source = srcs.get_source("bib-textru")
        calls = []

        async def _transport(url, headers=None):  # pragma: no cover
            calls.append(url)
            return srcs.TransportResponse(status=200, text="x")

        check = await srcs.check_source(source, transport=_transport, now=NOW)
        assert check["status"] == srcs.STATUS_DISABLED
        assert check["error_code"] == "bibliography_only"
        assert calls == []          # никакого авто-scraping

    def test_denominators_exclude_local_and_bibliography(self):
        views = srcs.build_views({}, now=NOW)
        summary = srcs.summarize(views)
        # 3 ru-repo + wikipedia = 4 живых сетевых источника; local/manual и
        # библиография в знаменатель НЕ входят.
        assert summary["denominators"]["live_http"] == 4
        assert summary["denominators"]["local"] == 1
        assert summary["denominators"]["references"] == 4
        assert summary["total_live"] == 4
        assert summary["available"] == 0
        assert summary["unchecked"] == 4

    def test_lineage_shared_upstream_is_one_confirmation(self):
        lineage = srcs.independent_confirmations(["ru-repo-a", "wikipedia"])
        assert lineage["independent"] == 1
        groups = list(lineage["groups"].values())
        assert sorted(groups[0]) == ["ru-repo-a", "wikipedia"]

    def test_lineage_distinct_repos_stay_separate(self):
        lineage = srcs.independent_confirmations(
            ["ru-repo-b", "ru-repo-c", "local/manual"])
        assert lineage["independent"] == 3
        assert "ru-repo-b" in lineage["unverified_lineage"]

    def test_registry_ids_are_stable(self):
        ids = [s.source_id for s in srcs.all_sources()]
        assert ids == ["ru-repo-a", "ru-repo-b", "ru-repo-c", "local/manual",
                       "wikipedia", "bib-tinkoff-journal", "bib-gramota",
                       "bib-textru", "bib-yurova"]
        for source in srcs.all_sources():
            assert source.licence.name
            if source.kind == srcs.KIND_BIBLIO:
                assert source.auto_check is False
                assert source.counts_as_live is False
                assert source.licence.permits_analysis is False

    def test_stale_is_separate_from_transport_status(self):
        state = {"source_id": "ru-repo-a", "enabled": True,
                 "last_status": srcs.STATUS_AVAILABLE,
                 "last_check_at": NOW - datetime.timedelta(days=30),
                 "content_status": "parsed", "docs_fetched": 1,
                 "docs_parsed": 1}
        view = srcs.source_view(srcs.get_source("ru-repo-a"), state, now=NOW,
                                freshness_days=7)
        assert view["status"] == srcs.STATUS_AVAILABLE      # транспортный
        assert view["reachability"]["freshness"] == "stale"  # отдельная пометка

    def test_stale_check_is_not_fresh(self):
        state = {"source_id": "ru-repo-a", "enabled": True,
                 "last_status": srcs.STATUS_AVAILABLE,
                 "last_check_at": NOW - datetime.timedelta(days=8)}
        view = srcs.source_view(srcs.get_source("ru-repo-a"), state, now=NOW,
                                freshness_days=7)
        assert view["reachability"]["freshness"] == "stale"

    def test_disabled_source_does_not_look_healthy(self):
        state = {"source_id": "ru-repo-a", "enabled": False,
                 "last_status": srcs.STATUS_AVAILABLE,
                 "last_check_at": NOW, "content_status": "parsed",
                 "docs_fetched": 1, "docs_parsed": 1}
        view = srcs.source_view(srcs.get_source("ru-repo-a"), state, now=NOW)
        assert view["enabled"] is False
        assert view["status"] == srcs.STATUS_DISABLED


# ── воркер: A=403 + B=200/changed и ручная проверка ────────────────────────
def _worker_with_sources(store, sources, transport, llm=None):
    return AntiClicheWorker(llm=llm, pg=_FakePg(store), sources=tuple(sources),
                            transport=transport)


class TestWorkerIndependence:
    @pytest.mark.asyncio
    async def test_partial_success_publishes_from_healthy_source(
            self, monkeypatch):
        """Тест 2 §9.2: A=403 policy + B=200/changed → partial_success."""
        from unittest.mock import AsyncMock
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        blocked = _source("test-a")
        healthy = _source("test-b")
        store = _StateStore()
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value=json.dumps(
            {"patterns": [{"phrase": "резюмируя вышесказанное",
                           "origin": "b"}]}))
        worker = _worker_with_sources(
            store, [blocked, healthy], _transport({
                blocked.url: srcs.TransportResponse(
                    status=403, text="robot policy: automated access is "
                                     "forbidden"),
                healthy.url: "Справочник штампов: резюмируя вышесказанное, "
                             "важно отметить следующее."}), llm=llm)
        result = await worker.refresh(force=True)
        assert result["status"] == "partial_success"
        assert result["count"] == 1
        assert result["sources"]["blocked"] == 1
        assert result["sources"]["ok"] == 1
        assert store.cache_row["patterns"][0]["phrase"] == \
            "резюмируя вышесказанное"
        # провенанс источника записан в элемент набора
        assert store.cache_row["patterns"][0]["source"] == "test-b"
        # источник A остаётся видимо красным
        state_a = next(row for row in store.source_states
                       if row["source_id"] == "test-a")
        assert state_a["last_status"] == srcs.STATUS_POLICY_BLOCKED

    @pytest.mark.asyncio
    async def test_blocked_source_not_retried_on_next_tick(self, monkeypatch):
        from unittest.mock import AsyncMock
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        blocked = _source("test-a")
        store = _StateStore()
        store.source_states = [{
            "source_id": "test-a", "enabled": True,
            "last_status": srcs.STATUS_POLICY_BLOCKED,
            "paused_reason": "policy_blocked", "next_attempt_at": None,
            "last_check_at": NOW - datetime.timedelta(minutes=5),
            "consecutive_failures": 1}]
        calls = []

        async def _transport(url, headers=None):
            calls.append(url)
            return srcs.TransportResponse(status=200, text="текст")

        worker = _worker_with_sources(store, [blocked], _transport)
        result = await worker.refresh(force=True)
        assert calls == []                       # никакого storm
        assert result["status"] == "fresh"
        assert result["paused"][0]["reason"] == "policy_blocked"

    @pytest.mark.asyncio
    async def test_check_one_does_not_call_llm_or_publish(self, monkeypatch):
        """Тест 18 §9.2: ручное «Проверить» ≠ анализ ≠ публикация."""
        llm_calls = []

        class _Llm:
            async def generate_worker(self, *a, **kw):  # pragma: no cover
                llm_calls.append(1)
                return "{}"

        store = _StateStore()
        store.cache_row = {"patterns": [{"code": "dyn_x", "phrase": "живой"}],
                           "source": "wikipedia", "source_url": "u",
                           "version": 5, "fetched_at": None,
                           "updated_at": None, "last_status": "ok"}
        source = _source()
        worker = _worker_with_sources(
            store, [source],
            _transport({source.url: "Достаточно длинный текст справочника."}),
            llm=_Llm())
        check = await worker.check_one("test-a", manual=True)
        assert check["status"] == srcs.STATUS_AVAILABLE
        assert llm_calls == []
        assert store.cache_row["version"] == 5
        assert store.cache_row["patterns"][0]["phrase"] == "живой"
        assert store.source_states[0]["last_check_id"] == check["check_id"]


# ── read API ───────────────────────────────────────────────────────────────
def _api_client(monkeypatch, store):
    import hashlib
    import hmac
    import time
    import types
    import urllib.parse

    from fastapi.testclient import TestClient
    from services.config_cache import ConfigCache
    from web.api import deps as deps_mod
    from web.app import create_app

    token = "123456:TESTTOKEN"
    admin_id = 700000001

    def _init_data(user_id):
        fields = {"auth_date": str(int(time.time())),
                  "query_id": "AAHkFg",
                  "user": json.dumps({"id": user_id, "first_name": "A"},
                                     separators=(",", ":"))}
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=token))

    class _ApiConn(_StateConn):
        async def fetch(self, sql, *args):
            if "FROM bot_roles" in sql:
                return [{"role_name": "admin",
                         "permissions": {"wildcard": True},
                         "is_custom": False, "role_type": "global_admin"}]
            if "FROM bot_admins" in sql:
                return [{"telegram_id": admin_id, "role_name": "admin",
                         "added_by": None,
                         "created_at": "2026-09-07T00:00:00+00:00"}]
            return await super().fetch(sql, *args)

    class _Pg:
        def __init__(self):
            self.pool = _StatePool(_ApiConn(store))

        async def connect(self):
            pass

        async def init(self, seed_settings: bool = True):
            pass

        async def close(self):
            pass

    cache = ConfigCache(pg=_Pg(), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    client = TestClient(app)
    return client, {"X-Telegram-Init-Data": _init_data(admin_id)}


class TestSourcesApi:
    def _store(self):
        store = _StateStore()
        store.cache_row = {
            "patterns": [{"code": "dyn_a", "phrase": "живой штамп"}],
            "source": "ru-repo-b", "source_url": "u", "version": 6,
            "fetched_at": "2026-11-02T00:00:00+00:00",
            "updated_at": "2026-11-02T00:00:00+00:00", "last_status": "ok"}
        store.source_states = [
            {"source_id": "ru-repo-b", "enabled": True,
             "last_status": srcs.STATUS_AVAILABLE,
             "last_check_at": NOW, "last_http": 200,
             "revision": "rev-b", "content_status": "parsed",
             "docs_fetched": 1, "docs_parsed": 1,
             "last_success_fetch_at": NOW, "consecutive_failures": 0},
            {"source_id": "wikipedia", "enabled": True,
             "last_status": srcs.STATUS_POLICY_BLOCKED,
             "last_check_at": NOW, "last_http": 403,
             "content_status": "not_checked", "docs_fetched": 0,
             "docs_parsed": 0, "last_error_code": "policy_blocked",
             "paused_reason": "policy_blocked", "consecutive_failures": 2},
        ]
        return store

    def test_sources_list_keeps_fields_separate(self, monkeypatch):
        store = self._store()
        client, hdr = _api_client(monkeypatch, store)
        with client:
            response = client.get("/api/anticliche/sources", headers=hdr)
        assert response.status_code == 200
        body = response.json()
        assert body["active_version"]["version"] == 6
        assert body["active_version"]["status"] in ("lkg", "ok", "none")
        source = next(s for s in body["sources"]
                      if s["source_id"] == "wikipedia")
        # честное разделение семантики, а не один `status`
        assert source["status"] == srcs.STATUS_POLICY_BLOCKED
        assert source["reachability"]["http_status"] == 403
        assert source["content"]["documents_parsed"] == 0
        assert source["analysis"]["status"] == "not_run"
        assert body["summary"]["blocked"] >= 1
        assert body["summary"]["problems"] >= 1
        assert body["denominators"]["live_http"] == 4
        assert body["denominators"]["local"] == 1
        assert {s["source_id"] for s in body["local_sources"]} == \
            {"local/manual"}
        assert len(body["references"]) == 4
        health = body["health"]
        assert set(health) == {"reachability", "content", "analysis", "runtime"}

    def test_source_detail_and_unknown(self, monkeypatch):
        store = self._store()
        client, hdr = _api_client(monkeypatch, store)
        with client:
            ok = client.get("/api/anticliche/sources/ru-repo-b", headers=hdr)
            missing = client.get("/api/anticliche/sources/nope", headers=hdr)
        assert ok.status_code == 200
        detail = ok.json()
        assert detail["document_paths"] == [
            "skills/ru-editor/references/ai-markers-ru.md"]
        assert detail["licence"]["name"] == "MIT"
        assert detail["retry_policy"]["respect_retry_after"] is True
        assert detail["content"]["documents_parsed"] == 1
        assert missing.status_code == 404

    def test_health_endpoint_returns_four_kinds(self, monkeypatch):
        store = self._store()
        client, hdr = _api_client(monkeypatch, store)
        with client:
            response = client.get("/api/anticliche/health", headers=hdr)
        assert response.status_code == 200
        body = response.json()
        assert set(body["health"]) == {"reachability", "content", "analysis",
                                       "runtime"}
        assert body["health"]["reachability"]["status"] in (
            "ok", "degraded", "blocked", "unchecked", "partial")
