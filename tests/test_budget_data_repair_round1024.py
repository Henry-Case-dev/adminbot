"""F22 (раунд 10.24, `budget-data-repair-round1024`, ADR-1024-23) — ремонт
потерянных per-chat seed-overrides + read-only аудит + fail-loud CLI PG.

Покрытие (spec §6.1, review iter1):
  (1) отсутствующие 8 seed-ключей целевого чата восстанавливаются (в т.ч. `-1`);
  (2) повторный прогон — идемпотентный no-op (без set/history);
  (3) ручные надстройки не перетираются (`manual-overrides-immutable`);
  (4) `--force` перезаписывает present — осознанный break-glass;
  (5) разрыв петли F20: РЕАЛЬНЫЙ роут `POST /api/config` + сид no-op;
  (6) таймлайн chat_params: детектор вайпа `wipe_suspected`, added/dropped;
  (7) аудит — строго READ-ONLY (`SELECT`, без set_chat_params/NOTIFY);
  (8) R17/R18: нет сырых key_value/секретов/полных дампов и текущих значений;
  (9) CLI `apply-chat-overrides`: connect → init → apply, fail-loud non-zero
      (PG недоступна, нечитаемый/пустой сид, реальные ошибки);
  (10) границы: `flags.chat_context_budgets_enabled` ↔ master (F21);
       резолв флага в CLI (chat/global/default) без bot-only глобала; Δ=0 пины.

R17/R18: значения секретов не цитируются; в фикстурах — синтетические маркеры.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import manage
from services import chat_settings_seed

# F20-харнесс: реальный роут, in-memory chat_params + TestClient.
from tests.test_budget_overrides_merge_round1024 import (  # noqa: F401
    K_NEW as F20_NEW_KEY,
    _post as _f20_post,
    webapp as webapp,
)

ROOT = Path(".")
SEED_ID = -1002661910336
FLAG = "flags.chat_context_budgets_enabled"

_SEED = chat_settings_seed.load_chat_settings_seed()
SEED_VERSION = _SEED["version"]
SEED_KEYS = dict(next(e for e in _SEED["chats"]
                      if int(e["chat_id"]) == SEED_ID)["overrides"])


class _FakeChatParams:
    """In-memory chat_params (overrides/meta) + счётчики set/history."""

    def __init__(self):
        self.store: dict[int, dict] = {}
        self.set_calls: list[int] = []
        self.history: list[int] = []

    async def ensure_scope_profile(self, chat_id, *, dm, pg=None):
        self.store.setdefault(int(chat_id), {"overrides": {}, "meta": {}})
        return True

    async def get_all_chat_params(self, chat_id, pg=None):
        return json.loads(json.dumps(
            self.store.get(int(chat_id), {"overrides": {}, "meta": {}})))

    async def set_chat_params(self, chat_id, patch, *, changed_by=None,
                              expected_updated_at=None, pg=None,
                              history_field="chat_params",
                              record_history=True):
        root = self.store.setdefault(int(chat_id),
                                     {"overrides": {}, "meta": {}})
        before = json.dumps(root, sort_keys=True)
        if isinstance(patch.get("overrides"), dict):
            root["overrides"] = dict(patch["overrides"])
        if isinstance(patch.get("meta"), dict):
            root["meta"] = dict(patch["meta"])
        root["v"] = patch.get("v", 1)
        if record_history and json.dumps(root, sort_keys=True) != before:
            self.history.append(int(chat_id))
        self.set_calls.append(int(chat_id))
        return root


def _pg():
    return SimpleNamespace(pool=object())


@pytest.fixture()
def fake_cp(monkeypatch):
    fake = _FakeChatParams()
    monkeypatch.setattr("services.chat_params.ensure_scope_profile",
                        fake.ensure_scope_profile)
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        fake.get_all_chat_params)
    monkeypatch.setattr("services.chat_params.set_chat_params",
                        fake.set_chat_params)
    return fake


# ── (1)/(2): ремонт и идемпотентность ───────────────────────────────────────

class TestRepair:
    @pytest.mark.asyncio
    async def test_repair_restores_all_eight_keys(self, fake_cp):
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert len(report["applied"]) == 1
        chat_id, keys = report["applied"][0]
        assert chat_id == SEED_ID
        assert set(keys) == set(SEED_KEYS)
        overrides = fake_cp.store[SEED_ID]["overrides"]
        assert overrides["limits.chat_global_key_budget_requests"] == -1
        assert overrides["limits.chat_global_key_budget_tokens"] == -1
        assert overrides["limits.worker_daily_llm_calls_per_chat"] == -1
        assert overrides["limits.worker_daily_llm_tokens_per_chat"] == -1
        assert overrides["limits.chat_global_context_max_tokens"] == -1
        assert overrides["limits.chat_thread_max_tokens"] == -1
        assert overrides["limits.chat_context_budget_tokens"] == -1
        assert overrides["limits.import_history_retention_days"] == 0
        assert fake_cp.store[SEED_ID]["meta"][
            "chat_settings_seed_version"] == SEED_VERSION

    @pytest.mark.asyncio
    async def test_repair_idempotent_no_set_no_history(self, fake_cp):
        first = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert first["applied"]
        sets_after, hist_after = len(fake_cp.set_calls), len(fake_cp.history)
        second = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert second["applied"] == []
        assert second["skipped"] == [SEED_ID]
        assert len(fake_cp.set_calls) == sets_after       # no UPDATE
        assert len(fake_cp.history) == hist_after          # no history


# ── (3)/(4): immutability и break-glass ─────────────────────────────────────

class TestImmutability:
    @pytest.mark.asyncio
    async def test_plain_seed_restores_absent_and_keeps_manual(self, fake_cp):
        fake_cp.store[SEED_ID] = {
            "overrides": {
                "limits.chat_cooldown_seconds": 42,          # чужой ключ
                "limits.chat_global_key_budget_requests": 50,  # ручной seed-ключ
            },
            "meta": {"chat_settings_seed_version": 1},
        }
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert report["applied"]
        overrides = fake_cp.store[SEED_ID]["overrides"]
        assert overrides["limits.chat_global_key_budget_requests"] == 50
        assert overrides["limits.chat_cooldown_seconds"] == 42
        assert overrides["limits.chat_context_budget_tokens"] == -1
        assert overrides["limits.chat_global_context_max_tokens"] == -1

    @pytest.mark.asyncio
    async def test_force_is_break_glass(self, fake_cp):
        fake_cp.store[SEED_ID] = {
            "overrides": {"limits.chat_global_key_budget_requests": 50},
            "meta": {"chat_settings_seed_version": 1},
        }
        await chat_settings_seed.apply_chat_settings_seed(_pg(), force=True)
        assert fake_cp.store[SEED_ID]["overrides"][
            "limits.chat_global_key_budget_requests"] == -1


# ── (5): разрыв петли — РЕАЛЬНЫЙ F20-роут + сид no-op ───────────────────────

class TestLoopBroken:
    @pytest.mark.asyncio
    async def test_f20_route_save_then_seed_noop(self, webapp):
        """Реальный `POST /api/config` (F20) сохраняет seed-набор; затем
        штатный сид видит полный набор → no-op (петля разорвана)."""
        webapp.cp.seed(SEED_ID, overrides=dict(SEED_KEYS))
        resp = _f20_post(webapp, F20_NEW_KEY, 7777)
        assert resp.status_code == 200, resp.text
        overrides = webapp.cp.store[SEED_ID]["overrides"]
        assert set(SEED_KEYS) <= set(overrides)
        assert overrides[F20_NEW_KEY] == 7777
        sets_before = len(webapp.cp.set_calls)
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert report["applied"] == []
        assert report["skipped"] == [SEED_ID]
        assert len(webapp.cp.set_calls) == sets_before


# ── Аудит: инфраструктура ───────────────────────────────────────────────────

class _AuditConn:
    """Мини-PG для аудита: отдаёт заранее заданные строки по запросу."""

    def __init__(self, *, profile=None, history=None, keys=None,
                 usage=None, worker=None, settings=None):
        self._profile = profile
        self._history = history or []
        self._keys = keys or []
        self._usage = usage or []
        self._worker = worker or []
        self._settings = settings or []
        self.queries: list[str] = []

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        return self._profile

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "chat_lore_history" in sql:
            return self._history
        if "FROM chat_keys" in sql:
            return self._keys
        if "chat_usage" in sql:
            return self._usage
        if "worker_budget" in sql:
            return self._worker
        if "bot_settings" in sql:
            return self._settings
        return []


class _AuditPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


def _audit_pg(**kwargs):
    return SimpleNamespace(pool=_AuditPool(_AuditConn(**kwargs)))


def _profile(overrides, *, meta=None, keys=None, updated_at="2026-09-20"):
    return {
        "chat_id": SEED_ID, "updated_at": updated_at,
        "chat_params": {"overrides": overrides, "meta": meta or {},
                        "keys": keys or {}},
    }


def _seed_keys() -> set:
    return set(SEED_KEYS)


def _fake_db_class(pool):
    """Фабрика подменного `PgDatabase` (connect/close; audit без init)."""
    class _FakeDb:
        def __init__(self, *a, **kw):
            self.pool = pool

        async def connect(self):
            pass

        async def init(self, **kw):
            pass

        async def close(self):
            pass

    return _FakeDb


# ── (6): таймлайн и детектор вайпа ──────────────────────────────────────────

class TestTimeline:
    def test_parse_malformed_is_safe(self):
        assert manage._parse_overrides_blob("not-json") == (set(), None)
        assert manage._parse_overrides_blob("") == (set(), None)
        assert manage._parse_overrides_blob(None) == (set(), None)

    def test_wipe_detected_on_seed_key_drop(self):
        old = json.dumps({"overrides": dict(SEED_KEYS),
                          "meta": {"chat_settings_seed_version": 1}})
        one_key = {"limits.import_history_retention_days": 0}
        new = json.dumps({"overrides": one_key,
                          "meta": {"chat_settings_seed_version": 1}})
        entry = manage._timeline_entry(
            {"id": 7, "created_at": "2026-09-19T10:00:00+00:00",
             "changed_by": None, "old_value": old, "new_value": new},
            _seed_keys())
        assert entry["wipe_suspected"] is True
        assert entry["seed_keys_old"] == 8
        assert entry["seed_keys_new"] == 1
        assert set(entry["dropped"]) >= (set(SEED_KEYS) - set(one_key))
        assert entry["added"] == []

    def test_no_wipe_when_set_intact(self):
        blob = json.dumps({"overrides": dict(SEED_KEYS),
                           "meta": {"chat_settings_seed_version": 1}})
        entry = manage._timeline_entry(
            {"id": 1, "old_value": blob, "new_value": blob,
             "changed_by": 5, "created_at": None}, _seed_keys())
        assert entry["wipe_suspected"] is False

    @pytest.mark.asyncio
    async def test_collect_classifies_absent(self):
        old = json.dumps({"overrides": dict(SEED_KEYS),
                          "meta": {"chat_settings_seed_version": 1}})
        new = json.dumps({"overrides": {},
                          "meta": {"chat_settings_seed_version": 1}})
        conn = _AuditConn(
            profile=_profile({}, meta={"chat_settings_seed_version": 1}),
            history=[{"id": 3, "created_at": None, "changed_by": None,
                      "old_value": old, "new_value": new}])
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        statuses = {i["key"]: i["status"] for i in report["classification"]}
        assert set(statuses) == set(SEED_KEYS)
        assert set(statuses.values()) == {"absent"}
        assert report["wipe_detected"] is True
        assert report["allow_global_present"] is False
        assert report["seed_meta_version"] == 1
        assert report["seed_ok"] is True


# ── (10) High-1: резолв context-флага из данных PG ──────────────────────────

class TestContextFlag:
    @pytest.mark.asyncio
    async def test_chat_source(self):
        conn = _AuditConn(profile=_profile({FLAG: False}))
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        assert report["context_flag"] == {"value": False, "source": "chat"}

    @pytest.mark.asyncio
    async def test_chat_source_from_string(self):
        conn = _AuditConn(profile=_profile({FLAG: "false"}))
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        assert report["context_flag"] == {"value": False, "source": "chat"}

    @pytest.mark.asyncio
    async def test_global_source(self):
        conn = _AuditConn(profile=_profile({}),
                          settings=[{"key": FLAG, "value": True}])
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        assert report["context_flag"] == {"value": True, "source": "global"}

    @pytest.mark.asyncio
    async def test_default_source(self):
        from config.settings import settings
        conn = _AuditConn(profile=_profile({}))
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        assert report["context_flag"]["source"] == "default"
        assert report["context_flag"]["value"] == \
            settings.CHAT_CONTEXT_BUDGETS_ENABLED


# ── (7): строго read-only ───────────────────────────────────────────────────

class TestReadOnly:
    @pytest.mark.asyncio
    async def test_only_select_and_no_write_path(self, monkeypatch):
        async def _boom(*a, **kw):
            raise AssertionError("аудит не должен писать через set_chat_params")

        monkeypatch.setattr("services.chat_params.set_chat_params", _boom)
        conn = _AuditConn(
            profile=_profile(dict(SEED_KEYS),
                             meta={"chat_settings_seed_version": 1}),
            history=[], keys=[], usage=[], worker=[], settings=[])
        await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        assert conn.queries, "аудит не выполнил запросов"
        for sql in conn.queries:
            assert sql.lstrip().upper().startswith("SELECT")
        joined = " ".join(conn.queries).lower()
        assert "pg_notify" not in joined
        assert "update " not in joined
        assert "insert " not in joined
        assert "delete " not in joined


# ── (8): R17/R18 — без секретов и текущих значений ──────────────────────────

class TestRedaction:
    @pytest.mark.asyncio
    async def test_jsonl_has_no_secret_value(self, tmp_path):
        secret = "sk-SYNTHETIC-ABCD"
        marker = "TOPSECRETVALUE"
        new_value = json.dumps({"overrides": {
            "limits.chat_mood_enabled": marker}, "meta": {}})
        conn = _AuditConn(
            profile=_profile({}, meta={"chat_settings_seed_version": 1}),
            history=[{"id": 1, "created_at": None, "changed_by": None,
                      "old_value": json.dumps({"overrides": dict(SEED_KEYS)}),
                      "new_value": new_value}],
            keys=[{"key_name": "keys.llm_api_key", "key_value": secret}])
        report = await manage._collect_chat_overrides_audit(
            SimpleNamespace(pool=_AuditPool(conn)), chat_id=SEED_ID)
        out = tmp_path / "audit.jsonl"
        manage._write_audit_jsonl(out, report)
        text = out.read_text(encoding="utf-8")
        assert secret not in text
        assert marker not in text
        assert "ABCD" in text                      # last4 маски есть
        assert '"configured": true' in text
        assert report["chat_keys"][0]["configured"] is True
        assert report["chat_keys"][0]["last4"] == "ABCD"

    def test_different_value_not_printed(self, tmp_path, capsys,
                                         monkeypatch):
        """R17: текущее (different) значение-строка НЕ попадает в stdout/JSONL."""
        marker = "SECRET_MARKER_STRING"
        overrides = dict(SEED_KEYS)
        overrides["limits.chat_context_budget_tokens"] = marker
        conn = _AuditConn(profile=_profile(
            overrides, meta={"chat_settings_seed_version": 1}))
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            _fake_db_class(_AuditPool(conn)))
        jsonl = tmp_path / "different.jsonl"
        code = manage.main(["audit-chat-overrides", "--chat-id", str(SEED_ID),
                            "--jsonl", str(jsonl)])
        out = capsys.readouterr()
        assert code == 0
        assert marker not in out.out
        assert marker not in jsonl.read_text(encoding="utf-8")
        assert "different=1" in out.out

    def test_cli_audit_output_has_no_secret(self, monkeypatch, tmp_path,
                                            capsys):
        secret = "sk-SYNTHETIC-WXYZ"
        conn = _AuditConn(
            profile=_profile(dict(SEED_KEYS),
                             meta={"chat_settings_seed_version": 1}),
            keys=[{"key_name": "keys.llm_api_key", "key_value": secret}])
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            _fake_db_class(_AuditPool(conn)))
        jsonl = tmp_path / "cli.jsonl"
        code = manage.main(["audit-chat-overrides", "--chat-id", str(SEED_ID),
                            "--jsonl", str(jsonl)])
        out = capsys.readouterr()
        assert code == 0
        assert secret not in out.out
        assert secret not in jsonl.read_text(encoding="utf-8")
        assert "ok=8" in out.out


# ── (9): CLI apply — connect → init → apply, fail-loud ──────────────────────

class TestApplyCliFailLoud:
    def test_connect_init_then_seed_applied(self, monkeypatch):
        observed = {"order": []}

        class _FakeDb:
            def __init__(self, *a, **kw):
                self.pool = object()
                observed["pg"] = self

            async def connect(self):
                observed["order"].append("connect")

            async def init(self, seed_settings=True):
                observed["order"].append(("init", seed_settings))

            async def close(self):
                pass

        async def _apply(pg, *, force=False):
            observed["order"].append("apply")
            return {"applied": [(SEED_ID, sorted(SEED_KEYS))],
                    "skipped": [], "errors": []}

        monkeypatch.setattr("services.pg_db.PgDatabase", _FakeDb)
        monkeypatch.setattr(
            "services.chat_settings_seed.apply_chat_settings_seed", _apply)
        assert manage.main(["apply-chat-overrides"]) == 0
        assert observed["order"][0] == "connect"
        assert observed["order"][1] == ("init", False)   # connect ДО init
        assert observed["order"][2] == "apply"

    def test_pg_unavailable_is_nonzero_not_silent(self, monkeypatch, capsys):
        class _DownDb:
            def __init__(self, *a, **kw):
                self.pool = None

            async def connect(self):
                pass

            async def init(self, **kw):
                raise AssertionError("init не должен вызываться без pool")

            async def close(self):
                pass

        async def _must_not_run(*a, **kw):
            raise AssertionError("сид не должен запускаться без PG")

        monkeypatch.setattr("services.pg_db.PgDatabase", _DownDb)
        monkeypatch.setattr(
            "services.chat_settings_seed.apply_chat_settings_seed",
            _must_not_run)
        assert manage.main(["apply-chat-overrides"]) == 1
        assert "PostgreSQL недоступен" in capsys.readouterr().err

    def test_real_errors_are_nonzero(self, monkeypatch):
        monkeypatch.setattr("services.pg_db.PgDatabase", _fake_db_class(object()))

        async def _apply(pg, *, force=False):
            return {"applied": [], "skipped": [], "errors": [SEED_ID]}

        monkeypatch.setattr(
            "services.chat_settings_seed.apply_chat_settings_seed", _apply)
        assert manage.main(["apply-chat-overrides"]) == 1


# ── (9) High-2: fail-loud на нечитаемый/пустой сид ──────────────────────────

class TestSeedFailLoud:
    def test_apply_unreadable_seed_nonzero(self, tmp_path, capsys):
        broken = tmp_path / "seed.json"
        broken.write_text("{not json", encoding="utf-8")
        assert manage.main(["apply-chat-overrides", "--seed", str(broken)]) == 1
        assert "нечитаем" in capsys.readouterr().err

    def test_apply_empty_seed_nonzero(self, tmp_path, capsys):
        empty = tmp_path / "seed.json"
        empty.write_text(json.dumps({"version": 1, "chats": []}),
                         encoding="utf-8")
        assert manage.main(["apply-chat-overrides", "--seed", str(empty)]) == 1
        assert "нечитаем" in capsys.readouterr().err

    def test_audit_unreadable_seed_nonzero(self, monkeypatch, tmp_path,
                                           capsys):
        broken = tmp_path / "seed.json"
        broken.write_text("{not json", encoding="utf-8")
        conn = _AuditConn(profile=None)
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            _fake_db_class(_AuditPool(conn)))
        code = manage.main(["audit-chat-overrides", "--chat-id", str(SEED_ID),
                            "--seed", str(broken),
                            "--jsonl", str(tmp_path / "a.jsonl")])
        assert code == 1
        assert "недостоверен" in capsys.readouterr().err


# ── (9)/(5) Medium-5: --strict ──────────────────────────────────────────────

class TestStrictMode:
    def _run(self, monkeypatch, tmp_path, conn, *extra):
        monkeypatch.setattr("services.pg_db.PgDatabase",
                            _fake_db_class(_AuditPool(conn)))
        return manage.main(["audit-chat-overrides", "--chat-id", str(SEED_ID),
                            "--jsonl", str(tmp_path / "a.jsonl"), *extra])

    def test_strict_nonzero_on_drift(self, monkeypatch, tmp_path):
        conn = _AuditConn(profile=_profile({}))          # все absent
        assert self._run(monkeypatch, tmp_path, conn, "--strict") == 1

    def test_non_strict_zero_on_drift(self, monkeypatch, tmp_path):
        conn = _AuditConn(profile=_profile({}))
        assert self._run(monkeypatch, tmp_path, conn) == 0

    def test_strict_zero_when_clean(self, monkeypatch, tmp_path):
        conn = _AuditConn(profile=_profile(
            dict(SEED_KEYS), meta={"chat_settings_seed_version": 1}))
        assert self._run(monkeypatch, tmp_path, conn, "--strict") == 0

    def test_strict_nonzero_when_section_failed(self, monkeypatch, tmp_path):
        """Low-6: отказ секции (warnings) → неполный аудит → strict non-zero."""
        conn = _AuditConn(profile=_profile(
            dict(SEED_KEYS), meta={"chat_settings_seed_version": 1}))

        async def _fail_keys(sql, *args):
            if "FROM chat_keys" in sql:
                raise RuntimeError("section failed")
            return []

        conn.fetch = _fail_keys  # type: ignore[assignment]
        assert self._run(monkeypatch, tmp_path, conn, "--strict") == 1


# ── (10): границы флага контекста ↔ master (F21) и Δ=0 пины ─────────────────

class TestFlagBoundary:
    def test_two_distinct_axes_in_catalog(self):
        from services import param_catalog as pc
        context = pc.get_by_pg_key("flags.chat_context_budgets_enabled")
        master = pc.get_by_pg_key("flags.budgets_enabled")
        assert context is not None and master is not None
        assert context.pg_key != master.pg_key

    def test_backfill_104_targets_only_context_flag(self):
        text = (ROOT / "scripts" / "backfill_104_chat_flags.py").read_text(
            encoding="utf-8")
        assert "flags.chat_context_budgets_enabled" in text
        assert "flags.budgets_enabled" not in text

    def test_delta_ddl_zero(self):
        from services import pg_db
        assert len(pg_db.DDL_STATEMENTS) == 45

    def test_delta_catalog_zero(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 459
        assert len(pc.GROUPS) == 98
