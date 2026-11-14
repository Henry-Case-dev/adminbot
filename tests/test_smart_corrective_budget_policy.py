"""SMART-CORRECTIVE-01 · S3-BUDGET — сквозная передача effective budget policy.

Контракт `plans/features/smart-corrective-01/architecture-plan.md` §3:

* единственный резолвер `flags.budgets_enabled` (chat override → global →
  заводской default) доходит от ``ToolRouter`` до ``SourceReader`` как
  ``chat_id`` + ``budget_enforced`` — для direct/nested/repeat/fallback
  вызовов, а не резолвится вложенным инструментом без контекста чата;
* политика одного чата не достаётся другому; отсутствие chat_id не
  подменяется безусловным ON/OFF (читается тот же резолвер для глобального
  слоя);
* OFF не включает искусственных потолков (файлы/глубина/запросы), ON
  применяет ЯВНО сконфигурированные значения; физические предохранители
  (запрещённые пути, ёмкость модели) остаются при любом состоянии;
* источник ON/OFF ровно один: второй флаг/второй резолв не появляется.

Тесты используют существующие контуры: настоящий ``SourceReader`` со
stub-провайдером (байты без сети), ``LocalSnapshotProvider`` для fallback и
настоящий ``budget_gate`` с fake-слоями hot/chat_params (как в
``test_budget_global_toggle_round1024``). Политика проверяется по тому, что
ФАКТИЧЕСКИ увидел SourceReader (``_RunState``), а не только по ответу
инструмента.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import settings
from services import budget_gate
from services import chat_params as cp
from services import hot_config as hot
from services import source_reader as sr
from services import source_reuse
from services import tool_router as tool_router_module
from services.tool_router import ToolContext, ToolDeps, ToolRouter

REPO = "Henry-Case-dev/adminbot"
SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
#: Обычный групповой чат и DM (положительный id) — оба обязаны иметь свою
#: политику; DM не является особым случаем для резолвера.
CHAT_OFF = -1001234567890
CHAT_INHERIT = -1009876543210
CHAT_ON = 555000111

_KEY = budget_gate.KEY_BUDGETS_ENABLED


# ── fake-слои резолвера (hot = глобальный, chat_params = per-chat) ──────────

class _FakeHot:
    def __init__(self, values) -> None:
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeChatCache:
    def __init__(self, by_chat) -> None:
        self.by_chat = by_chat or {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.by_chat.get(int(chat_id), {}))}

    async def invalidate_chat(self, chat_id):
        pass


def _set_policy(monkeypatch, *, global_value, overrides=None) -> None:
    """Эффективная политика через НАСТОЯЩИЙ резолвер (chat → global → factory)."""
    values = {} if global_value is None else {_KEY: bool(global_value)}
    monkeypatch.setattr(hot, "_cache", _FakeHot(values))
    monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache(overrides))
    budget_gate.reset_cache()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(type(settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    monkeypatch.setattr(sr, "_REPO_ORIGIN_LAST", None)
    # Автоопределение runtime root выключено для герметичности: локальное
    # дерево задаётся только тестовым provider'ом.
    monkeypatch.setattr(sr, "runtime_application_root", lambda: None)
    for name in ("SOURCE_READ_MAX_FILES", "SOURCE_READ_MAX_DEPTH",
                 "SOURCE_READ_MAX_REQUESTS", "SOURCE_READ_CONTENT_SCAN_BYTES"):
        monkeypatch.delenv(name, raising=False)
    budget_gate.reset_cache()
    source_reuse.clear()
    yield
    budget_gate.reset_cache()
    source_reuse.clear()


# ── источник: stub-байты без сети + реальный локальный snapshot ─────────────

class _SpyReader(sr.SourceReader):
    """Настоящий SourceReader + снимок ФАКТИЧЕСКИ применённой политики."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[dict] = []
        self.applied: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return await super().run(**kwargs)

    async def _run(self, state, **kwargs):
        self.applied.append({
            "budget_enforced": bool(state.budget_enforced),
            "files": int(state.limit_files),
            "depth": int(state.limit_depth),
            "requests": int(state.limit_requests)})
        return await super()._run(state, **kwargs)


class _StubRemote:
    """Детерминированный провайдер GitHub: фиксированные байты, без сети."""

    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self, files: dict[str, str] | None = None, *,
                 read_error: sr.SourceFetchError | None = None) -> None:
        self.files = dict(files or {})
        self.read_error = read_error
        self.calls: list[str] = []
        self.refs: list[str] = []
        self.read_calls = 0
        self.list_tree_calls = 0

    async def search_repos(self, query, *, limit=5):
        self.calls.append("search")
        return []

    async def resolve_repo(self, owner, repo):
        self.calls.append("resolve_repo")
        return sr.RepoInfo(owner=owner, name=repo, default_branch="main",
                           language="Python")

    async def resolve_commit(self, repo, ref):
        self.calls.append("resolve_commit")
        self.refs.append(str(ref or ""))
        text = str(ref or "").strip()
        return text.lower() if len(text) == 40 else SHA

    async def list_tree(self, repo, commit):
        self.calls.append("list_tree")
        self.list_tree_calls += 1
        return sr.TreeListing(entries=[
            sr.TreeEntry(path=path, kind="blob", size=len(text.encode()))
            for path, text in sorted(self.files.items())])

    async def read_file(self, repo, commit, path, *, blob_sha="", **kwargs):
        self.calls.append("read_file")
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        text = self.files.get(path)
        if text is None:
            return None
        return sr.SourceFile(path=path, data=text.encode("utf-8"),
                             sha="", size=len(text.encode()),
                             endpoint=sr.ENDPOINT_CONTENTS)


def _identity(*, code: str = "verified_deployed", checkout: str | None = SHA,
              deployed: str | None = SHA) -> dict:
    return {
        "schema": 1, "code": code, "reason": "",
        "repo_origin": REPO, "deployed_sha": deployed,
        "checkout_sha": checkout, "dirty": False,
        "local_source_verification": ("verified_deployed"
                                      if code == "verified_deployed"
                                      else "local_unverified"),
        "version_provenance": {"runtime": "2.58.200", "manifest": "2.58.200",
                               "consistent": True},
        "local_identity": {"checkout_sha": checkout, "dirty": False,
                           "checkout_mtime": None, "branch": "main"},
    }


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "app"
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(SHA + "\n",
                                                     encoding="utf-8")
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/{REPO}.git\n',
        encoding="utf-8")
    return root


def _local_reader(tmp_path: Path, files: dict[str, str], *,
                  identity: dict | None = None,
                  remote: _StubRemote | None = None) -> _SpyReader:
    identity = identity or _identity()
    tree = _tree(tmp_path, files)
    record = sr.resolve_local_source(
        runtime_root=tree, configured_root="", repo_origin=REPO,
        identity_reader=lambda _root: identity)
    provider = sr.LocalSnapshotProvider(
        tree, repo_origin=REPO, identity_reader=lambda _root: identity,
        source=record)
    return _SpyReader(provider=remote or _StubRemote(),
                      local_provider=provider, repo_origin=REPO)


def _remote_reader(files: dict[str, str] | None = None) -> _SpyReader:
    return _SpyReader(provider=_StubRemote(files), repo_origin=REPO)


def _router(reader) -> ToolRouter:
    return ToolRouter(ToolDeps(None, None, source_reader=reader))


async def _dispatch(router: ToolRouter, ctx: ToolContext, args: dict) -> dict:
    return json.loads(await router.dispatch("read_source_code", args, ctx))


def _simple_files() -> dict[str, str]:
    return {"services/hub.py": "def hub():\n    return 1\n"}


def _chain_files(count: int = 9) -> tuple[str, dict[str, str]]:
    """Главный файл с N вызовами + N смежных файлов (follow-up цепочка)."""
    names = [f"helper_{index:02d}_fn" for index in range(count)]
    hub = "def hub():\n" + "".join(f"    {name}()\n" for name in names)
    files: dict[str, str] = {"services/hub.py": hub}
    for name in names:
        files[f"services/{name}.py"] = f"def {name}():\n    return 1\n"
    return "services/hub.py", files


def _search_files() -> dict[str, str]:
    return {
        "services/aaa_module_0.py": "MARKER = 'ledger.reconcile.marker'\n",
        "services/aaa_module_1.py": "VALUE = 1\n",
        "services/payments_worker.py": "TARGET = 'ledger.reconcile.marker'\n",
    }


# ── 1. Политика доходит до SourceReader по реальным слоям ──────────────────

class TestPolicyPropagation:
    @pytest.mark.asyncio
    async def test_global_off_reaches_reader(self, tmp_path, monkeypatch):
        """global OFF без chat-override → SourceReader видит OFF."""
        _set_policy(monkeypatch, global_value=False)
        reader = _local_reader(tmp_path, _simple_files())
        ctx = ToolContext(CHAT_INHERIT, "q")
        payload = await _dispatch(_router(reader), ctx, {
            "operation": "read", "repo": REPO, "path": "services/hub.py",
            "follow": False})
        assert payload["status"] == sr.STATUS_OK, payload
        assert reader.calls[-1]["chat_id"] == CHAT_INHERIT
        assert reader.calls[-1]["budget_enforced"] is False
        assert reader.applied[-1]["budget_enforced"] is False
        assert payload["not_checked"]["applied_limits"]["budgets_enforced"] \
            is False

    @pytest.mark.asyncio
    async def test_factory_default_on_reaches_reader(self, tmp_path,
                                                     monkeypatch):
        """Пустые слои → заводской default ON (существующий резолвер)."""
        _set_policy(monkeypatch, global_value=None)
        reader = _local_reader(tmp_path, _simple_files())
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "path": "services/hub.py",
             "follow": False})
        assert payload["status"] == sr.STATUS_OK, payload
        assert reader.applied[-1]["budget_enforced"] is True
        assert payload["not_checked"]["applied_limits"]["budgets_enforced"] \
            is True

    @pytest.mark.asyncio
    async def test_chat_off_overrides_global_on(self, tmp_path, monkeypatch):
        """global ON + chat OFF → OFF только для этого чата (DM id)."""
        _set_policy(monkeypatch, global_value=True,
                    overrides={CHAT_ON: {_KEY: False}})
        reader = _local_reader(tmp_path, _simple_files())
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_ON, "q"),
            {"operation": "read", "repo": REPO, "path": "services/hub.py",
             "follow": False})
        assert payload["status"] == sr.STATUS_OK, payload
        assert reader.calls[-1]["chat_id"] == CHAT_ON
        assert reader.applied[-1]["budget_enforced"] is False

    @pytest.mark.asyncio
    async def test_chat_on_overrides_global_off(self, tmp_path, monkeypatch):
        """global OFF + chat ON → ON для этого чата (явная настройка сильнее)."""
        _set_policy(monkeypatch, global_value=False,
                    overrides={CHAT_INHERIT: {_KEY: True}})
        reader = _local_reader(tmp_path, _simple_files())
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "path": "services/hub.py",
             "follow": False})
        assert payload["status"] == sr.STATUS_OK, payload
        assert reader.applied[-1]["budget_enforced"] is True

    @pytest.mark.asyncio
    async def test_no_chat_id_reads_resolver_for_global_scope(
            self, tmp_path, monkeypatch):
        """Нет chat_id — не безусловный ON/OFF: резолвер читается для None."""
        _set_policy(monkeypatch, global_value=False)
        seen: list = []
        original = budget_gate.budgets_enabled

        async def _spy(chat_id=None):
            seen.append(chat_id)
            return await original(chat_id)

        monkeypatch.setattr(budget_gate, "budgets_enabled", _spy)
        reader = _local_reader(tmp_path, _simple_files())
        payload = await _dispatch(
            _router(reader), ToolContext(None, "q"),
            {"operation": "read", "repo": REPO, "path": "services/hub.py",
             "follow": False})
        assert payload["status"] == sr.STATUS_OK, payload
        assert seen == [None]
        assert reader.calls[-1]["chat_id"] is None
        assert reader.applied[-1]["budget_enforced"] is False


# ── 2. Изоляция чатов и отсутствие второго механизма ──────────────────────

class TestIsolationAndSingleResolver:
    @pytest.mark.asyncio
    async def test_policy_of_one_chat_is_not_used_for_another(self, tmp_path,
                                                              monkeypatch):
        """A OFF / B наследует global ON: политики не пересекаются."""
        _set_policy(monkeypatch, global_value=True,
                    overrides={CHAT_OFF: {_KEY: False}})
        reader = _local_reader(tmp_path, _simple_files())
        router = _router(reader)
        args = {"operation": "read", "repo": REPO, "path": "services/hub.py",
                "follow": False}
        await _dispatch(router, ToolContext(CHAT_OFF, "q"), dict(args))
        await _dispatch(router, ToolContext(CHAT_INHERIT, "q"), dict(args))
        await _dispatch(router, ToolContext(CHAT_OFF, "q"), dict(args))
        assert [item["budget_enforced"] for item in reader.applied] == \
            [False, True, False]
        assert [call["chat_id"] for call in reader.calls] == \
            [CHAT_OFF, CHAT_INHERIT, CHAT_OFF]

    @pytest.mark.asyncio
    async def test_one_resolve_per_turn_and_reader_does_not_re_resolve(
            self, tmp_path, monkeypatch):
        """Один резолв на контекст хода: второй/третий вызов не читают слой.

        SourceReader получает готовый ``budget_enforced`` и сам предикат не
        вызывает — второго независимого определения ON/OFF нет.
        """
        _set_policy(monkeypatch, global_value=True)
        gate_calls: list = []
        predicate_calls: list = []
        original_gate = budget_gate.budgets_enabled
        original_predicate = sr.budget_limits_enforced

        async def _gate(chat_id=None):
            gate_calls.append(chat_id)
            return await original_gate(chat_id)

        async def _predicate(chat_id=None):
            predicate_calls.append(chat_id)
            return await original_predicate(chat_id)

        monkeypatch.setattr(budget_gate, "budgets_enabled", _gate)
        monkeypatch.setattr(sr, "budget_limits_enforced", _predicate)
        reader = _local_reader(tmp_path, _simple_files())
        router = _router(reader)
        ctx = ToolContext(CHAT_INHERIT, "q")
        for _ in range(3):
            await _dispatch(router, ctx, {
                "operation": "read", "repo": REPO, "path": "services/hub.py",
                "follow": False})
        assert gate_calls == [CHAT_INHERIT]
        assert predicate_calls == [CHAT_INHERIT]
        assert len(reader.applied) == 3
        assert all(item["budget_enforced"] for item in reader.applied)

        # Новый ход (новый ToolContext) — новый резолв для СВОЕГО scope.
        await _dispatch(router, ToolContext(CHAT_INHERIT, "q"), {
            "operation": "read", "repo": REPO, "path": "services/hub.py",
            "follow": False})
        assert gate_calls == [CHAT_INHERIT, CHAT_INHERIT]
        assert predicate_calls == [CHAT_INHERIT, CHAT_INHERIT]

    def test_router_has_no_second_budget_switch(self):
        """Второй независимый механизм ON/OFF в ToolRouter не появляется."""
        source = Path(tool_router_module.__file__).read_text(encoding="utf-8")
        # Роутер не читает мастер-флаг сам и не импортирует budget_gate:
        # единственный seam — существующий предикат SourceReader.
        assert "import budget_gate" not in source
        assert "from services import budget_gate" not in source
        assert "budget_limits_enforced" in source


class TestRelatedContours:
    @pytest.mark.asyncio
    async def test_chain_contours_use_same_resolver_with_chat_scope(
            self, monkeypatch):
        """Связанные участки исследовательского контура (tool_loop/direct)
        резолвят политику ТЕМ ЖЕ мастер-флагом и для СВОЕГО чата."""
        from services import direct_execution as de
        from services import tool_loop

        _set_policy(monkeypatch, global_value=False,
                    overrides={CHAT_ON: {_KEY: True}})
        seen: list = []
        original = budget_gate.budgets_enabled

        async def _spy(chat_id=None):
            seen.append(chat_id)
            return await original(chat_id)

        monkeypatch.setattr(budget_gate, "budgets_enabled", _spy)
        loop_limits = await tool_loop._resolve_chain_limits(CHAT_ON)
        direct_limits = await de.resolve_chain_limits_for(CHAT_ON)
        assert seen == [CHAT_ON, CHAT_ON]
        assert loop_limits.budgets_enabled is True
        assert direct_limits.budgets_enabled is True
        # Фоновый контур уже передаёт chat scope в тот же мастер-флаг
        # (`worker_budget.consume` → `budget_gate.budgets_enabled`).
        from services import worker_budget as wb
        assert wb._scope_chat_id(f"chat:{CHAT_ON}") == CHAT_ON
        assert wb._scope_chat_id("global") is None


# ── 3. OFF без искусственных потолков, ON с явной политикой ──────────────

class TestOffOnSemantics:
    @pytest.mark.asyncio
    async def test_chat_off_ignores_operator_caps_through_router(
            self, tmp_path, monkeypatch):
        """Global ON + chat OFF: env-потолки 1/1/1 не срабатывают для чата.

        Это исходный пользовательский сценарий: выключенные в КОНКРЕТНОМ чате
        бюджеты не должны возвращаться через вложенный SourceReader.
        """
        monkeypatch.setenv("SOURCE_READ_MAX_FILES", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_DEPTH", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_REQUESTS", "1")
        _set_policy(monkeypatch, global_value=True,
                    overrides={CHAT_INHERIT: {_KEY: False}})
        path, files = _chain_files(9)
        reader = _remote_reader(files)
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "ref": SHA, "path": path,
             "follow": True})
        assert payload["status"] == sr.STATUS_OK, payload
        assert len(payload["files"]) == 10
        assert payload["not_checked"]["applied_limits"] == {
            "files": 0, "depth": 0, "requests": 0, "budgets_enforced": False}
        assert payload["followup_incomplete"] is False

    @pytest.mark.asyncio
    async def test_on_applies_configured_caps(self, tmp_path, monkeypatch):
        """ON: те же явные значения применяются (не игнорируются)."""
        monkeypatch.setenv("SOURCE_READ_MAX_FILES", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_DEPTH", "1")
        monkeypatch.setenv("SOURCE_READ_MAX_REQUESTS", "1")
        _set_policy(monkeypatch, global_value=True)
        path, files = _chain_files(9)
        reader = _remote_reader(files)
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "ref": SHA, "path": path,
             "follow": True})
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["not_checked"]["applied_limits"] == {
            "files": 1, "depth": 1, "requests": 1, "budgets_enforced": True}
        assert len(payload["files"]) < 10

    @pytest.mark.asyncio
    async def test_off_keeps_security_guard(self, tmp_path, monkeypatch):
        """OFF не отменяет безопасность: запрещённый путь остаётся отказом."""
        denied = "config/secrets_store.py"
        assert sr.path_is_denied(denied) is True
        _set_policy(monkeypatch, global_value=False)
        reader = _local_reader(tmp_path, {denied: "TOKEN = 'x'\n"})
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "path": denied,
             "follow": False})
        assert payload["outcome"] == sr.OUTCOME_PERMISSION_DENIED, payload
        assert payload["verified"] is False

    @pytest.mark.asyncio
    async def test_off_does_not_mean_infinite_execution(self, monkeypatch):
        """OFF снимает квоты, но технические предохранители остаются.

        Отказ провайдера возвращает структурированный результат за bounded
        число попыток, а не бесконечный цикл; fuse цепочки продолжает
        действовать независимо от мастер-флага.
        """
        from services import direct_execution as de
        from services import tool_loop

        _set_policy(monkeypatch, global_value=False)
        failure = sr.SourceFetchError(sr.ERR_PROVIDER_UNAVAILABLE,
                                      sr.STAGE_FETCH, retryable=True,
                                      detail="provider_unavailable")
        remote = _StubRemote(
            {"services/hub.py": "def hub():\n    return 1\n"},
            read_error=failure)
        reader = _SpyReader(provider=remote, repo_origin=REPO)
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "read", "repo": REPO, "ref": SHA,
             "path": "services/hub.py", "follow": False})
        assert payload["status"] == sr.STATUS_ERROR, payload
        assert payload["outcome"] == sr.OUTCOME_SOURCE_UNAVAILABLE
        assert remote.read_calls <= 2
        # `apply_limits` OFF, но fuse — отдельная техническая страховка.
        assert payload["not_checked"]["applied_limits"]["budgets_enforced"] \
            is False
        limits = tool_loop.resolve_chain_limits(budgets_enabled=False)
        assert limits.enforce is False
        monkeypatch.setattr(type(settings), "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            0.01)
        budget = de.ChainBudget(budgets_enabled=False)
        assert budget.limits_on is False
        import time as _time
        _time.sleep(0.02)
        assert budget.limit_skip(metered=False) == \
            tool_loop.CHAIN_TIMEOUT_REASON
        # ON без явной операторской политики не вводит скрытых потолков.
        on_limits = tool_loop.resolve_chain_limits(budgets_enabled=True)
        assert on_limits.enforce is True
        assert (on_limits.max_total_calls, on_limits.max_metered_calls,
                on_limits.max_same_call) == (0, 0, 0)


# ── 4. Fallback и повторный вызов сохраняют ту же политику ───────────────

class TestFallbackAndRepeat:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("budgets_on", [False, True])
    async def test_local_to_remote_fallback_keeps_policy(self, tmp_path,
                                                         monkeypatch,
                                                         budgets_on):
        """Fallback local→remote не теряет effective-политику вызова."""
        _set_policy(monkeypatch, global_value=budgets_on)
        seen: list = []
        original = sr.SourceReader._maybe_switch_to_remote

        def _spy(self, state, info, *, reason):
            seen.append({"budget_enforced": bool(state.budget_enforced),
                         "reason": reason})
            return original(self, state, info, reason=reason)

        monkeypatch.setattr(sr.SourceReader, "_maybe_switch_to_remote", _spy)
        remote = _StubRemote({
            "services/remote_only.py":
                "TARGET = 'ledger.reconcile.marker'\n"})
        identity = _identity(code="local_unverified", checkout=OTHER_SHA,
                             deployed=SHA)
        reader = _local_reader(
            tmp_path,
            {"services/aaa_module_0.py": "VALUE = 0\n",
             "services/aaa_module_1.py": "VALUE = 1\n"},
            identity=identity, remote=remote)
        payload = await _dispatch(
            _router(reader), ToolContext(CHAT_INHERIT, "q"),
            {"operation": "locate", "repo": REPO,
             "query": "ledger.reconcile.marker", "follow": False})
        assert seen, "fallback не сработал — сценарий не доказал бы политику"
        assert seen[0]["budget_enforced"] is budgets_on
        assert payload["status"] == sr.STATUS_OK, payload
        assert payload["source_selection"]["fallback"]
        assert payload["not_checked"]["applied_limits"]["budgets_enforced"] \
            is budgets_on

    @pytest.mark.asyncio
    async def test_repeated_call_reuses_same_policy_and_identity(
            self, tmp_path, monkeypatch):
        """Reuse повторного вызова: 0 сети, та же политика и identity."""
        _set_policy(monkeypatch, global_value=False)
        reader = _local_reader(tmp_path, _simple_files())
        router = _router(reader)
        ctx = ToolContext(CHAT_INHERIT, "q")
        args = {"operation": "read", "repo": REPO, "path": "services/hub.py",
                "follow": False,
                "claim": {"entity": "budget s3", "relation": "spec",
                          "version": "1"}}
        first = await _dispatch(router, ctx, dict(args))
        second = await _dispatch(router, ctx, dict(args))
        assert first["status"] == sr.STATUS_OK, first
        assert second["reused"] is True and second["network_calls"] == 0
        assert second["progress_id"] == first["progress_id"]
        assert second["outcome"] == first["outcome"]
        assert second["continuation"] == first["continuation"]
        assert second["source_selection"] == first["source_selection"]
        assert second["provenance"]["operation"] == "read"
        assert len(reader.applied) == 1          # сетевого вызова не было
        bucket = [item for item in ctx.evidence_limits if item.get("reused")]
        assert bucket and bucket[-1]["budgets_enforced"] is False


# ── 5. SourceReader-континуация: cursor доходит, reuse не затеняет ───────

class TestContinuationWiring:
    @pytest.mark.asyncio
    async def test_cursor_is_forwarded_and_bypasses_reuse(self, tmp_path,
                                                          monkeypatch):
        """Opaque cursor доходит до Reader; повтор с cursor — не reuse."""
        _set_policy(monkeypatch, global_value=True)
        files = _search_files()
        budget = len("MARKER = 'ledger.reconcile.marker'\n".encode()) + 1
        monkeypatch.setattr(sr, "content_scan_budget_bytes", lambda: budget)
        reader = _local_reader(tmp_path, files)
        router = _router(reader)
        ctx = ToolContext(CHAT_INHERIT, "q")
        args = {"operation": "locate", "repo": REPO,
                "query": "ledger.reconcile.marker", "follow": False,
                "claim": {"entity": "budget s3 cursor", "relation": "spec",
                          "version": "1"}}
        first = await _dispatch(router, ctx, dict(args))
        token = (first.get("continuation") or {}).get("cursor") or ""
        assert first["outcome"] == sr.OUTCOME_PARTIAL, first
        assert token and "ledger" not in token

        second = await _dispatch(router, ctx, dict(args, cursor=token))
        assert reader.calls[-1]["cursor"] == token
        assert second.get("reused") is not True
        assert second["progress_id"] == first["progress_id"]
        assert second["status"] == sr.STATUS_OK, second
        returned = {item["path"] for item in second.get("matches") or ()}
        assert "services/aaa_module_0.py" not in returned
