"""F22 (раунд 10.24, `budget-data-repair-round1024`, ADR-1024-23) — ремонт
потерянных per-chat seed-overrides + read-only аудит + fail-loud CLI PG.

Покрытие (spec §6.1):
  (1) отсутствующие 8 seed-ключей целевого чата восстанавливаются (в т.ч. `-1`);
  (2) повторный прогон — идемпотентный no-op (без set/history);
  (3) ручные надстройки не перетираются (`manual-overrides-immutable`);
  (4) `--force` перезаписывает present — осознанный break-glass;
  (5) разрыв петли «save → стирание → рестарт-лечение» (F20-merge + сид no-op);
  (6) таймлайн chat_params: детектор вайпа `wipe_suspected`, added/dropped;
  (7) аудит — строго READ-ONLY (`SELECT`, без set_chat_params/NOTIFY);
  (8) R17/R18: нет сырых key_value/секретов/полных new_value в выводе;
  (9) CLI `apply-chat-overrides`: `pg.connect()` обязателен, fail-loud non-zero;
  (10) границы: `flags.chat_context_budgets_enabled` ↔ master (F21); backfill цел.

R17/R18: значения секретов не цитируются; в фикстурах — синтетические маркеры.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import manage
from services import chat_settings_seed

ROOT = Path(".")
SEED_ID = -1002661910336


def _seed_entry() -> dict:
    seed = chat_settings_seed.load_chat_settings_seed()
    for entry in seed["chats"]:
        if int(entry["chat_id"]) == SEED_ID:
            return entry
    raise AssertionError("сид без целевого чата")


SEED_ENTRY = _seed_entry()
SEED_KEYS = dict(SEED_ENTRY["overrides"])
SEED_VERSION = chat_settings_seed.load_chat_settings_seed()["version"]


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
        # безлимит (-1) восстановлен, retention=0 (enforce)
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
        # ручная правка seed-ключа НЕ затёрта (present, без bump/force)
        assert overrides["limits.chat_global_key_budget_requests"] == 50
        # чужой ключ сохранён
        assert overrides["limits.chat_cooldown_seconds"] == 42
        # отсутствующие seed-ключи восстановлены
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


# ── (5): разрыв петли F20-merge + сид ───────────────────────────────────────

class TestLoopBroken:
    @pytest.mark.asyncio
    async def test_f20_merge_keeps_set_then_seed_noop(self, fake_cp):
        # F20-merge (web/api/routes.py): new = value_overrides ∪ patch
        value_overrides = dict(SEED_KEYS)
        patch = {"limits.chat_context_budget_tokens": -1}
        new_overrides = dict(value_overrides)
        new_overrides.update(patch)
        assert set(new_overrides) == set(SEED_KEYS)        # набор цел
        fake_cp.store[SEED_ID] = {
            "overrides": new_overrides,
            "meta": {"chat_settings_seed_version": SEED_VERSION},
        }
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert report["skipped"] == [SEED_ID]
        assert report["applied"] == []


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


@pytest.fixture()
def _stub_flag(monkeypatch):
    async def _resolve(key, *, chat_id=None, default=None):
        return True, "chat"

    monkeypatch.setattr("services.worker_settings.resolve_setting_with_source",
                        _resolve)


def _seed_keys() -> set:
    return set(SEED_KEYS)


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
        # dropped содержит утраченные seed-ключи
        assert set(entry["dropped"]) >= (
            set(SEED_KEYS) - set(one_key))
        assert entry["added"] == []

    def test_no_wipe_when_set_intact(self):
        blob = json.dumps({"overrides": dict(SEED_KEYS),
                           "meta": {"chat_settings_seed_version": 1}})
        entry = manage._timeline_entry(
            {"id": 1, "old_value": blob, "new_value": blob,
             "changed_by": 5, "created_at": None}, _seed_keys())
        assert entry["wipe_suspected"] is False

    @pytest.mark.asyncio
    async def test_collect_classifies_absent(self, _stub_flag):
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


# ── (7): строго read-only ───────────────────────────────────────────────────

class TestReadOnly:
    @pytest.mark.asyncio
    async def test_only_select_and_no_write_path(self, _stub_flag,
                                                 monkeypatch):
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


# ── (8): R17/R18 — без секретов и полных дампов ─────────────────────────────

class TestRedaction:
    @pytest.mark.asyncio
    async def test_jsonl_has_no_secret_value(self, _stub_flag, tmp_path):
        secret = "sk-SYNTHETIC-ABCD"
        marker = "TOPSECRETVALUE"
        new_value = json.dumps({"overrides": {
            "limits.chat_mood_enabled": marker},
            "meta": {}})
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
        # в сводке chat_keys — только маска
        assert report["chat_keys"][0]["configured"] is True
        assert report["chat_keys"][0]["last4"] == "ABCD"

    def test_cli_audit_output_has_no_secret(self, _stub_flag, monkeypatch,
                                            tmp_path, capsys):
        secret = "sk-SYNTHETIC-WXYZ"
        conn = _AuditConn(
            profile=_profile(dict(SEED_KEYS),
                             meta={"chat_settings_seed_version": 1}),
            keys=[{"key_name": "keys.llm_api_key", "key_value": secret}])

        class _FakeDb:
            def __init__(self, *a, **kw):
                self.pool = _AuditPool(conn)

            async def connect(self):
                pass

            async def close(self):
                pass

        monkeypatch.setattr("services.pg_db.PgDatabase", _FakeDb)
        jsonl = tmp_path / "cli.jsonl"
        code = manage.main(["audit-chat-overrides", "--chat-id", str(SEED_ID),
                            "--jsonl", str(jsonl)])
        out = capsys.readouterr()
        assert code == 0
        assert secret not in out.out
        assert secret not in jsonl.read_text(encoding="utf-8")
        assert "ok=8" in out.out


# ── (9): CLI apply — connect + fail-loud ────────────────────────────────────

class TestApplyCliFailLoud:
    def test_connect_called_and_seed_applied(self, monkeypatch):
        observed = {}

        class _FakeDb:
            def __init__(self, *a, **kw):
                self.pool = object()
                self.connected = False
                observed["pg"] = self

            async def connect(self):
                self.connected = True

            async def init(self, **kw):
                raise AssertionError("init не должен вызываться раньше connect")

            async def close(self):
                pass

        async def _apply(pg, *, force=False):
            return {"applied": [(SEED_ID, sorted(SEED_KEYS))],
                    "skipped": [], "errors": []}

        monkeypatch.setattr("services.pg_db.PgDatabase", _FakeDb)
        monkeypatch.setattr("services.chat_settings_seed.apply_chat_settings_seed",
                            _apply)
        code = manage.main(["apply-chat-overrides"])
        assert code == 0
        assert observed["pg"].connected is True

    def test_pg_unavailable_is_nonzero_not_silent(self, monkeypatch, capsys):
        class _DownDb:
            def __init__(self, *a, **kw):
                self.pool = None

            async def connect(self):
                pass

            async def close(self):
                pass

        async def _must_not_run(*a, **kw):
            raise AssertionError("сид не должен запускаться без PG")

        monkeypatch.setattr("services.pg_db.PgDatabase", _DownDb)
        monkeypatch.setattr("services.chat_settings_seed.apply_chat_settings_seed",
                            _must_not_run)
        code = manage.main(["apply-chat-overrides"])
        assert code == 1
        err = capsys.readouterr().err
        assert "PostgreSQL недоступен" in err

    def test_real_errors_are_nonzero(self, monkeypatch):
        class _FakeDb:
            def __init__(self, *a, **kw):
                self.pool = object()

            async def connect(self):
                pass

            async def close(self):
                pass

        async def _apply(pg, *, force=False):
            return {"applied": [], "skipped": [], "errors": [SEED_ID]}

        monkeypatch.setattr("services.pg_db.PgDatabase", _FakeDb)
        monkeypatch.setattr("services.chat_settings_seed.apply_chat_settings_seed",
                            _apply)
        assert manage.main(["apply-chat-overrides"]) == 1


# ── (10): границы флага контекста ↔ master (F21), backfill цел ──────────────

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
        # F22 не смешивает оси: backfill не пишет master-тумблер
        assert "flags.budgets_enabled" not in text
