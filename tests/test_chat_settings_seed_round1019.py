"""Раунд 10.19 (F3, T-1859) — сид настроек чатов `services/chat_settings_seed.py` +
`config/chat_settings_seed.json`.

Покрытие:
  * применение данных сида к целевому chat_id (retention 0, бюджеты/контекст
    −1) без хардкода id в бизнес-логике;
  * идемпотентность: повторный прогон — no-op (нет set_chat_params);
  * merge: чужие overrides чата не перетираются;
  * `enforce` (retention) применяется всегда, даже поверх ручной правки;
  * бюджеты/контекст уважают ручную правку без `force`, перезаписываются с
    `force=True`;
  * grep-тест: id чата отсутствует в `services/*` (кроме самого сида).
"""
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import chat_settings_seed

ROOT = Path(".")
SEED_ID = -1002661910336


class _FakeChatParams:
    """In-memory chat_params: overrides/meta по chat_id."""

    def __init__(self):
        self.store: dict[int, dict] = {}
        self.set_calls: list[int] = []

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
        root = self.store.setdefault(int(chat_id), {"overrides": {}, "meta": {}})
        if isinstance(patch.get("overrides"), dict):
            root["overrides"] = dict(patch["overrides"])
        if isinstance(patch.get("meta"), dict):
            root["meta"] = dict(patch["meta"])
        root["v"] = patch.get("v", 1)
        self.set_calls.append(int(chat_id))
        return root


def _pg():
    return SimpleNamespace(pool=object())


class _FakeSeedConn:
    """Мини-PG: `SELECT_PROFILE_SQL` → одна строка профиля."""

    def __init__(self, row):
        self._row = row

    async def fetchrow(self, sql, *args):
        return self._row

    async def execute(self, sql, *args):
        return "INSERT 0 0"


class _FakeSeedPool:
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


def _pg_with_row(chat_params_row: dict):
    return SimpleNamespace(pool=_FakeSeedPool(_FakeSeedConn(
        {"chat_params": chat_params_row})))


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


class TestChatSettingsSeed:
    @pytest.mark.asyncio
    async def test_applies_and_is_idempotent(self, fake_cp):
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert len(report["applied"]) == 1
        chat_id, keys = report["applied"][0]
        assert chat_id == SEED_ID
        root = fake_cp.store[SEED_ID]
        assert root["overrides"]["limits.import_history_retention_days"] == 0
        assert root["overrides"]["limits.chat_global_key_budget_requests"] == -1
        assert root["overrides"]["limits.chat_context_budget_tokens"] == -1
        assert root["meta"]["chat_settings_seed_version"] == 1
        calls_after_first = len(fake_cp.set_calls)
        # повторный прогон — no-op
        report2 = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert report2["applied"] == []
        assert report2["skipped"] == [SEED_ID]
        assert len(fake_cp.set_calls) == calls_after_first

    @pytest.mark.asyncio
    async def test_merge_preserves_foreign_overrides(self, fake_cp):
        fake_cp.store[SEED_ID] = {
            "overrides": {"limits.chat_cooldown_seconds": 42}, "meta": {}}
        await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert fake_cp.store[SEED_ID]["overrides"][
            "limits.chat_cooldown_seconds"] == 42

    @pytest.mark.asyncio
    async def test_enforce_retention_always(self, fake_cp):
        fake_cp.store[SEED_ID] = {
            "overrides": {"limits.import_history_retention_days": 365,
                          "limits.chat_global_key_budget_requests": 50},
            "meta": {"chat_settings_seed_version": 1}}
        report = await chat_settings_seed.apply_chat_settings_seed(_pg())
        assert report["applied"]
        overrides = fake_cp.store[SEED_ID]["overrides"]
        # enforce-ключ перезаписан всегда
        assert overrides["limits.import_history_retention_days"] == 0
        # не-enforce ключ без force — ручная правка сохранена
        assert overrides["limits.chat_global_key_budget_requests"] == 50

    @pytest.mark.asyncio
    async def test_force_overwrites_budgets(self, fake_cp):
        fake_cp.store[SEED_ID] = {
            "overrides": {"limits.chat_global_key_budget_requests": 50},
            "meta": {"chat_settings_seed_version": 1}}
        await chat_settings_seed.apply_chat_settings_seed(_pg(), force=True)
        assert fake_cp.store[SEED_ID]["overrides"][
            "limits.chat_global_key_budget_requests"] == -1

    @pytest.mark.asyncio
    async def test_no_pg_is_fail_open(self):
        report = await chat_settings_seed.apply_chat_settings_seed(None)
        assert report == {"applied": [], "skipped": [], "errors": []}

    @pytest.mark.asyncio
    async def test_cli_path_preserves_foreign_overrides_without_cache(
            self, monkeypatch):
        """D-2 (ревью Батча C): пустой процесс-глобальный кэш
        (`_chat_params_cache=None`, CLI-путь `manage.py apply-chat-overrides`) → сид
        читает PG напрямую и НЕ теряет чужие overrides/meta целевого чата."""
        from services import chat_params
        monkeypatch.setattr(chat_params, "_chat_params_cache", None)
        stored = {
            "v": 1,
            "overrides": {
                "limits.chat_cooldown_seconds": 42,
                "limits.chat_global_key_budget_requests": 50,
            },
            "meta": {"chat_settings_seed_version": 1, "note": "owner"},
        }
        pg = _pg_with_row(stored)
        captured = {}

        async def _ensure(chat_id, *, dm, pg=None):
            return True

        async def _set(chat_id, patch, **kw):
            captured["patch"] = patch
            return {}

        monkeypatch.setattr(chat_params, "ensure_scope_profile", _ensure)
        monkeypatch.setattr(chat_params, "set_chat_params", _set)
        report = await chat_settings_seed.apply_chat_settings_seed(pg)
        assert report["applied"], report
        patch = captured["patch"]
        # чужие overrides сохранены (merge), namespace не затёрт сидом
        assert patch["overrides"]["limits.chat_cooldown_seconds"] == 42
        # ручная правка бюджета (present, version не вырос) уважена
        assert patch["overrides"][
            "limits.chat_global_key_budget_requests"] == 50
        # meta не потерян + version сида проставлен
        assert patch["meta"]["note"] == "owner"
        assert patch["meta"]["chat_settings_seed_version"] == 1

    def test_seed_file_loads(self):
        seed = chat_settings_seed.load_chat_settings_seed()
        assert seed["version"] == 1
        chat = seed["chats"][0]
        assert chat["chat_id"] == SEED_ID
        assert chat["overrides"]["limits.import_history_retention_days"] == 0
        assert set(chat["enforce"]) == {
            "limits.import_history_retention_days"}


class TestNoHardcodedId:
    # D-8 (ревью Батча C): проверяем «НОВЫХ хардкодов НЕТ», а не «id нигде
    # нет». Легаси-константы целевого чата существовали ДО F3:
    # `services/chat_lore.py` (CHAT_LORE_TARGET_CHAT_ID), `manage.py:44`
    # (LEGACY_TARGET_CHAT_ID, явный legacy-маркер D-2.8),
    # `tools/history_import/llm_worker.py` (дефолт arg)
    # — они НЕ являются настройками сида и этой фичей не добавлены.
    LEGACY_ALLOWED = {"chat_lore.py"}

    def test_chat_id_absent_from_services(self):
        """UPD3 п.3: id целевого чата — только в данных сида; новых
        хардкодов в `services/*` нет (легаси `chat_lore.py` — исключение)."""
        offenders = []
        for path in (ROOT / "services").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if str(SEED_ID) in text and path.name not in self.LEGACY_ALLOWED:
                offenders.append(path.name)
        assert offenders == [], offenders

    def test_id_lives_in_data_file(self):
        data = json.loads(
            (ROOT / "config" / "chat_settings_seed.json").read_text(encoding="utf-8"))
        assert any(chat["chat_id"] == SEED_ID for chat in data["chats"])


class TestSeedCheckedAndCache:
    """D-2.4 (Low, ревью итерации 4): нечитаемый сид → `ok=False` (fail-safe
    барьера purge), WARNING при пустом `enforce`, кэш разбора файла."""

    def test_unreadable_seed_ok_false(self, tmp_path):
        missing = tmp_path / "nope.json"
        ids, ok = chat_settings_seed.enforced_eternal_chat_ids_checked(missing)
        assert ids == set() and ok is False

    def test_invalid_json_ok_false(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        ids, ok = chat_settings_seed.enforced_eternal_chat_ids_checked(broken)
        assert ids == set() and ok is False

    def test_empty_enforce_warns(self, tmp_path, caplog):
        chat_settings_seed._seed_cache.clear()
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"version": 1, "chats": []}),
                        encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            ids, ok = chat_settings_seed.enforced_eternal_chat_ids_checked(path)
        assert ok is True and ids == set()
        assert any("enforce retention пуст" in r.getMessage()
                   for r in caplog.records)

    def test_seed_parse_cached_once(self, tmp_path, monkeypatch):
        calls = {"n": 0}
        real_load = json.load

        def _count(fh):
            calls["n"] += 1
            return real_load(fh)

        monkeypatch.setattr(chat_settings_seed.json, "load", _count)
        chat_settings_seed._seed_cache.clear()
        path = tmp_path / "seed.json"
        path.write_text(json.dumps({
            "version": 1,
            "chats": [{"chat_id": -100, "enforce": [
                "limits.import_history_retention_days"]}]}), encoding="utf-8")
        first = chat_settings_seed.enforced_eternal_chat_ids_checked(path)
        second = chat_settings_seed.enforced_eternal_chat_ids_checked(path)
        assert first == ({-100}, True)
        assert second == first
        assert calls["n"] == 1
