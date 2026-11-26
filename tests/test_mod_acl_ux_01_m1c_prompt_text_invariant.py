"""MOD-ACL-UX-01 M1-C — инварианты choke point для ТЕКСТА промпта.

Два инварианта из design `m1c-choke-point-design.md` §6:

1. **Поведенческий (A/B).** «Отравляем» ВСЕ guarded-ключи маркером, включаем
   запрещающую матрицу и обходим **таблицу маршрутов FastAPI** (`app.routes`,
   без ручного списка текстовых эндпоинтов): ни в одном теле ответа маркера
   нет. Затем та же матрица по умолчанию — маркер ОБЯЗАН присутствовать на
   перечне поверхностей (иначе прогон A ничего не доказывал: маршрут не
   доходил до текста).

2. **Структурный (AST).** `web/**` не импортирует системные/сырые
   материализаторы; входные функции рантайм-сборки объявляют `system_scope`;
   у владельцев текста в телах есть вызов стража (регрессия «страж тихо
   удалили» ловится до запуска).

Границы инварианта A (честно, не skip):
* маркер не попадёт в ответ, если маршрут берёт чат из источника, который
  тест не подставляет (path/нестандартное поле). Тест подставляет чат всеми
  известными способами сразу: `X-Chat-Id`, `?chat_id=`, тело `{chat_id}`;
* маршруты с побочными действиями (`/api/control/*`, `/api/summary/test/*`)
  исключены из A и B одинаково: они не отдают текст промпта, но могут менять
  процесс/запускать задачи;
* 5xx допустим, только если тот же маршрут даёт 5xx и в прогоне B
  (пре-существующий дефект), иначе тест падает.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/MAC-S10-13 (choke point)
"""
from __future__ import annotations

import ast
import json
import os
import sys
import types

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from services import access as access_srv
from services import chat_params
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services import prompt_text
from services import style_policy as sp
from services.config_cache import ConfigCache
from tests.test_evol016_prompt_activation import FactoryEdition
from tests.test_mod_acl_ux_01_m1c_prompt_chat_acl import (  # noqa: F401
    ADMIN, BASE_BLOCK, BASE_KEY, CHAT_A, CHAT_TEXT, INSPECTOR_ROLES,
    LOCAL_ADMIN, MARK, ROLES, TEST_TOKEN, ChatConn,
    CONTENT_LOCAL_ADMIN_ROLES, _Db, _Pg, _patch_chat_root, _seed,
    make_init_data, make_client,
)
from web.api import deps as deps_mod
from web.api import routes as routes_mod
from web.app import create_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Маршруты с побочными действиями: не отдают текст, но меняют процесс.
EXCLUDED_PREFIXES = ("/api/control/", "/api/summary/test/")


@pytest.fixture(autouse=True)
def _clean_param_permissions_cache():
    """Процесс-глобальный TTL-кэш `param_permissions` не переживает тест.

    `services.access._db_override_cache` общий для процесса: без сброса в
    teardown матрица этого модуля остаётся видимой следующему тесту в том же
    процессе (например, ложный 403 в
    `test_evol017_prompt_history_ui::test_chat_isolation`)."""
    access_srv.reset_param_permissions_cache()
    yield
    access_srv.reset_param_permissions_cache()


def _chat_root(overrides: dict, perm_overrides: dict | None = None):
    async def fake(chat_id, pg=None, *args, **kwargs):
        return {"overrides": dict(overrides),
                "perm_overrides": dict(perm_overrides or {}),
                "meta": {}, "gates": {}}
    return fake


def _poison_overrides() -> dict:
    """Маркер во ВСЕ guarded-ключи (текст инструкций), пригодный для рендера."""
    overrides: dict = {}
    for key in prompt_text.guarded_keys():
        if not key.startswith("prompts."):
            continue
        if key == "prompts.summary_cover_style_id":
            continue                      # не текст (id стиля обложки)
        overrides[key] = MARK
    overrides[pr.CORE_DOC_KEY] = {
        "full_text": MARK, "compact_text": MARK, "detail_level": "full",
        "enabled": True, "revision": 1, "updated_at": "2026-11-26T00:00:00+00:00",
    }
    overrides["character.expression"] = {
        "enabled": True, "note": MARK, "revision": 1,
        "updated_at": "2026-11-26T00:00:00+00:00",
    }
    overrides["style.policy"] = sp.build_document(
        soft=[{"id": "soft.probe", "text": MARK, "scope": "global",
               "enabled": True, "revision": 1}],
        revision=1, owner=1, reason="choke-point invariant")
    return overrides


def _make_invariant_client(monkeypatch, *, deny: bool):
    """Клиент стенда: реальный RBAC, двойники — только хранилище/журнал."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    access_srv.reset_param_permissions_cache()
    db = _Db(roles=INSPECTOR_ROLES)
    conn = ChatConn(db, {(CHAT_A, LOCAL_ADMIN): "local_admin"})
    if deny:
        for key in prompt_text.guarded_keys():
            conn.perm_rows[key] = {
                "key": key,
                "value": json.dumps({"view_roles": [], "edit_roles": []}),
                "updated_at": "2026-11-26T00:00:00+00:00"}
    cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
    _seed(cache, db)
    journal = prp.MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    overrides = _poison_overrides()
    # global-слой: половина ключей (проверяем, что отказ не «вырезал override»)
    original_get = cache.get

    def get_with_global(key, default=None):
        if isinstance(key, str) and prompt_text.guarded_key(key):
            return MARK
        return original_get(key, default)

    monkeypatch.setattr(cache, "get", get_with_global)
    monkeypatch.setattr(chat_params, "get_all_chat_params",
                        _chat_root(overrides))

    async def _sourced(chat_id, key, default=None):
        # Слой «чат» для карточки мемов читается штатным резолвером
        # (`get_chat_param_sourced`), а не только корнем профиля.
        if prompt_text.guarded_key(key):
            return MARK, "chat"
        return default, "default"

    monkeypatch.setattr(chat_params, "get_chat_param_sourced", _sourced)
    client = TestClient(create_app(cache))
    client.cache = cache
    client.journal = journal
    return client


#: correlation_id прогона A/B: одна запись кольца провайдера с маркером.
CORR_ID = "invcorr"


def _seed_provider_ring(mark: str) -> None:
    """Реальный след провайдера с композитным текстом в in-memory кольце."""
    from services import prompt_composer as composer
    composer.reset_provider_calls()
    composer.record_provider_call(
        payload={"probe": 1},
        messages=[{"role": "system", "content": mark},
                  {"role": "user", "content": "u"}],
        correlation_id=CORR_ID, chat_id=CHAT_A)


def _reset_provider_ring() -> None:
    from services import prompt_composer as composer
    composer.reset_provider_calls()


def _seed_marker_revision(client) -> str:
    body = f"{MARK}\n"
    rid = pr.revision_id_for(BASE_BLOCK, "chat", CHAT_A, "manual",
                             pr.sha12(body))
    client.journal.revisions[rid] = prp.RevisionRow(
        revision_id=rid, block_id=BASE_BLOCK, scope="chat", origin="manual",
        content_sha12=pr.sha12(body), body=body, pg_key=BASE_KEY,
        chat_id=CHAT_A, created_at="2026-11-26T00:00:00+00:00")
    return rid


def _iter_api_routes(routes):
    """(path, methods) по ВСЕЙ таблице маршрутов приложения.

    Эта версия FastAPI держит `include_router` ленивыми `_IncludedRouter`:
    `app.routes` не содержит плоских APIRoute, поэтому маршруты разворачиваются
    через `include_context.prefix` + `original_router.routes` (и `Mount`)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield str(route.path), tuple(route.methods or ())
            continue
        ctx = getattr(route, "include_context", None)
        original = getattr(route, "original_router", None)
        if ctx is not None and original is not None:
            prefix = str(getattr(ctx, "prefix", "") or "")
            for path, methods in _iter_api_routes(
                    getattr(original, "routes", ())):
                yield prefix + path, methods
            continue
        inner = getattr(route, "routes", None)
        if inner is None:
            inner = getattr(getattr(route, "router", None), "routes", None)
        if inner:
            mount = str(getattr(route, "path", "") or "").rstrip("/")
            for path, methods in _iter_api_routes(inner):
                yield mount + path, methods


def _collect_routes(client) -> list:
    return [(path, methods) for path, methods
            in _iter_api_routes(client.app.routes)
            if not path.startswith(EXCLUDED_PREFIXES)]


def _substitute(path: str, revision_id: str) -> str:
    subs = {
        "{block_id}": BASE_BLOCK,
        "{prompt_key}": BASE_KEY,
        "{revision_id}": revision_id,
        "{revision}": revision_id,
        "{chat_id}": str(CHAT_A),
        "{key}": BASE_KEY,
        "{sample_id}": "1",
        "{test_id}": "1",
        "{run_id}": "probe",
        "{id}": "1",
        "{role_name}": "user",
        "{telegram_id}": "1",
        "{capability}": "core",
    }
    out = path
    for needle, value in subs.items():
        out = out.replace(needle, value)
    # прочие {param} — безопасная заглушка (маршрут, скорее всего, 404/422)
    parts = []
    idx = 0
    while True:
        start = out.find("{", idx)
        end = out.find("}", start) if start >= 0 else -1
        if start < 0 or end < 0:
            parts.append(out[idx:])
            break
        parts.append(out[idx:start])
        parts.append("1")
        idx = end + 1
    return "".join(parts)


def _sweep(client, headers, revision_id: str, *,
           correlation_id: str = "") -> dict:
    """Best-effort запрос по КАЖДОМУ маршруту таблицы; возвращает статусы.

    ``correlation_id`` подставляется во все GET-маршруты (лишний query-параметр
    для остальных безвреден): иначе режим, читающий уже материализованный кэш
    провайдера (`GET /api/speech/inspector?correlation_id=...`), вообще не
    попадал в прогон A."""
    statuses: dict = {}
    for route_path, route_methods in _collect_routes(client):
        methods = [m for m in (route_methods or ()) if m not in
                   ("HEAD", "OPTIONS")]
        if not methods:
            continue
        method = "GET" if "GET" in methods else methods[0]
        path = _substitute(route_path, revision_id)
        params = {"chat_id": str(CHAT_A)}
        if correlation_id and "GET" in methods:
            params["correlation_id"] = correlation_id
        kwargs = {"headers": headers, "params": params}
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            kwargs["json"] = {"chat_id": CHAT_A}
        try:
            resp = client.request(method, path, **kwargs)
        except Exception:                       # pragma: no cover — 500-подобно
            statuses[(method, route.path)] = 599
            continue
        statuses[(method, route_path)] = resp.status_code
        body = resp.content.decode("utf-8", "replace")
        yield_key = (method, route_path)
        statuses[yield_key + ("body",)] = body
    return statuses


def _bodies(statuses: dict) -> list:
    return [(k, v) for k, v in statuses.items()
            if isinstance(k, tuple) and k[-1] == "body"]


class TestInvariantDeniedTextNeverReturned:
    @pytest.fixture(autouse=True)
    def _edition(self, monkeypatch):
        patch = FactoryEdition(monkeypatch)
        patch.set_edition(BASE_BLOCK, "narrator-a", "ЗАВОДСКОЙ A.\n")
        pr.set_release_policy_active(True)
        yield
        pr.set_release_policy_active(False)
        pr.set_retired_blocks(())
        pr.reset_cache()

    def test_no_response_returns_denied_prompt_text(self, monkeypatch):
        client = _make_invariant_client(monkeypatch, deny=True)
        headers = {"X-Telegram-Init-Data": make_init_data(LOCAL_ADMIN),
                   "X-Chat-Id": str(CHAT_A)}
        rev = _seed_marker_revision(client)
        _seed_provider_ring(MARK)
        try:
            statuses = _sweep(client, headers, rev)
            corr_statuses = _sweep(client, headers, rev,
                                   correlation_id=CORR_ID)
        finally:
            _reset_provider_ring()
        bodies = _bodies(statuses) + _bodies(corr_statuses)
        # Санити: прогон A действительно обошёл таблицу маршрутов, а не
        # «ничего не вызвал» (иначе отсутствие маркера тривиально).
        assert len(bodies) > 50, len(bodies)
        # Оба режима inspector пройдены и отказаны: обычный (снимок хода и
        # последний вызов кольца того же ответа) и correlation-режим.
        assert statuses[("GET", "/api/speech/inspector")] == 403
        assert corr_statuses[("GET", "/api/speech/inspector")] == 403
        leaks = [k for k, body in bodies
                 if MARK in body or CHAT_TEXT.strip() in body]
        assert leaks == [], "текст промпта в теле ответа без права: %r" % leaks[:5]

    def test_default_matrix_shows_the_marker(self, monkeypatch):
        """Прогон B: маркер обязан присутствовать — иначе A не доказывал бы
        ничего (маршрут не доходил до текста)."""
        client = _make_invariant_client(monkeypatch, deny=False)
        headers = {"X-Telegram-Init-Data": make_init_data(LOCAL_ADMIN),
                   "X-Chat-Id": str(CHAT_A)}
        rev = _seed_marker_revision(client)
        checks = [
            ("POST", "/api/speech/try", {"text": "привет"}),
            ("GET", "/api/speech/blocks", None),
            ("GET", f"/api/speech/block/{BASE_BLOCK}", None),
            ("GET", "/api/speech/core", None),
            ("GET", "/api/speech/style", None),
            ("GET", "/api/speech/expression", None),
            ("GET", "/api/speech/inspector", None),
            ("GET", "/api/initiative/meme-settings", None),
            ("GET", "/api/config", None),
            ("GET", f"/api/prompts/revisions/{rev}/source", None),
        ]
        missing = []
        for method, path, body in checks:
            kwargs = {"headers": headers, "params": {"chat_id": str(CHAT_A)}}
            if body is not None:
                kwargs["json"] = body
            resp = client.request(method, path, **kwargs)
            if MARK not in resp.text:
                missing.append((method, path, resp.status_code))
        assert missing == [], "прогон B вакуумный: %r" % missing[:5]

    def test_correlation_cache_is_gated_and_not_vacuous(self, monkeypatch):
        """Кэш провайдера: отказ без права и текст у глобального админа.

        Обе половины обязательны: 403 у чатовой роли доказывает страж, 200 с
        маркером у админа — что кольцо реально содержало текст (иначе отказ
        ничего не проверял)."""
        client = _make_invariant_client(monkeypatch, deny=True)
        _seed_provider_ring(MARK)
        try:
            local = client.get(
                "/api/speech/inspector",
                params={"correlation_id": CORR_ID, "chat_id": str(CHAT_A)},
                headers={"X-Telegram-Init-Data": make_init_data(LOCAL_ADMIN),
                         "X-Chat-Id": str(CHAT_A)})
            admin = client.get(
                "/api/speech/inspector",
                params={"correlation_id": CORR_ID, "chat_id": str(CHAT_A)},
                headers={"X-Telegram-Init-Data": make_init_data(ADMIN),
                         "X-Chat-Id": str(CHAT_A)})
        finally:
            _reset_provider_ring()
        assert local.status_code == 403, local.text[:300]
        assert MARK not in local.text
        assert admin.status_code == 200, admin.text[:300]
        assert MARK in admin.text


class TestStructuralInvariants:
    """AST: сырой материализатор — только у владельца; страж не удалён."""

    def _tree(self, rel: str) -> ast.AST:
        path = os.path.join(REPO, rel)
        return ast.parse(open(path, encoding="utf-8-sig").read(),
                         filename=rel)

    #: (модуль, запрещённые члены): сырые материализаторы и scope-API,
    #: которые web не имеет права вызывать (R5-F01/F02).
    FORBIDDEN = {
        "services.prompt_text": {"system_scope"},
        "services.prompt_registry": {"_factory_text_raw",
                                     "_effective_prompt_raw",
                                     "_FACTORY_TEXTS"},
        "services.prompt_release_policy": {"journal_write_scope",
                                           "legacy_migration_write"},
    }
    #: Кто единственный пишет scope (auth-time в deps, middleware в app).
    SCOPE_WRITE_ALLOWED = {
        "services.prompt_text.set_scope": {"web/api/deps.py", "web/app.py"},
        "services.prompt_text.reset_scope": {"web/app.py"},
    }

    def _prompt_text_bindings(self, tree):
        """(модульные алиасы, прямые члены) как ``{локальное имя: путь}``.

        Ловятся ВСЕ формы: ``import services.prompt_text [as X]`` (связывает
        корневое имя ``services``), ``import services [as Y]``,
        ``from services import prompt_text [as Z]``,
        ``from services.prompt_text import member [as M]`` — точечная запись
        через корень и алиасы модулей тоже разрешаются в полный путь."""
        aliases: dict[str, str] = {}
        direct: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name or ""
                    if not (mod == "services" or mod.startswith("services.")):
                        continue
                    if alias.asname:
                        aliases[alias.asname] = mod
                    else:
                        # ``import a.b`` связывает только корень ``a``.
                        root = mod.split(".")[0]
                        aliases[root] = root
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    asname = alias.asname or alias.name
                    if mod == "services":
                        aliases[asname] = "services." + alias.name
                    elif mod.startswith("services."):
                        direct[asname] = mod + "." + alias.name
        return aliases, direct

    @staticmethod
    def _dotted(node, aliases) -> str:
        """Полный путь ``a.b.c`` с раскрытием алиасов; ``""`` — не разрешён."""
        if isinstance(node, ast.Name):
            return aliases.get(node.id, "")
        if isinstance(node, ast.Attribute):
            base = TestStructuralInvariants._dotted(node.value, aliases)
            return base + "." + node.attr if base else ""
        return ""

    def _forbidden_path(self, path: str) -> str:
        for mod, members in self.FORBIDDEN.items():
            prefix = mod + "."
            if path.startswith(prefix) and path[len(prefix):] in members:
                return path
        return ""

    def test_web_does_not_import_system_materializers(self):
        offenders = []
        for root, _dirs, files in os.walk(os.path.join(REPO, "web")):
            for name in files:
                if not name.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(root, name),
                                      REPO).replace(os.sep, "/")
                tree = ast.parse(open(os.path.join(root, name),
                                      encoding="utf-8-sig").read(), filename=rel)
                offenders.extend(self._scan_offenders(tree, rel))
        assert offenders == [], offenders

    def _scan_offenders(self, tree, rel: str) -> list:
        """Нарушения файла: сырой материализатор/неразрешённая запись scope.

        Проверяются и ``Name`` (``from ... import x``), и любые ``Attribute``-
        цепочки (``services.prompt_text.system_scope``, ``pr._FACTORY_TEXTS``)."""
        aliases, direct = self._prompt_text_bindings(tree)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                path = direct.get(node.id, "")
            elif isinstance(node, ast.Attribute):
                path = self._dotted(node, aliases)
            else:
                continue
            if not path:
                continue
            if self._forbidden_path(path):
                offenders.append((rel, path))
                continue
            allowed = self.SCOPE_WRITE_ALLOWED.get(path)
            if allowed is not None and rel not in allowed:
                offenders.append((rel, path))
        return offenders

    @pytest.mark.parametrize("src,expected", [
        ("from services import prompt_text\n"
         "prompt_text.system_scope('x')\n",
         "services.prompt_text.system_scope"),
        ("from services import prompt_text as pt\n"
         "pt.system_scope('x')\n",
         "services.prompt_text.system_scope"),
        ("import services.prompt_text as ptx\n"
         "ptx.system_scope('x')\n",
         "services.prompt_text.system_scope"),
        # R5-F02: точечная форма через корневой модуль.
        ("import services.prompt_text\n"
         "services.prompt_text.system_scope('x')\n",
         "services.prompt_text.system_scope"),
        ("import services\n"
         "services.prompt_text.system_scope('x')\n",
         "services.prompt_text.system_scope"),
        ("from services.prompt_text import system_scope as ss\n"
         "ss('x')\n",
         "services.prompt_text.system_scope"),
        ("from services.prompt_text import reset_scope\n"
         "reset_scope()\n",
         "services.prompt_text.reset_scope"),
        ("from services.prompt_registry import _FACTORY_TEXTS\n"
         "_FACTORY_TEXTS\n",
         "services.prompt_registry._FACTORY_TEXTS"),
        ("from services import prompt_registry as pr\n"
         "pr._factory_text_raw('k', 'c')\n",
         "services.prompt_registry._factory_text_raw"),
        ("import services.prompt_registry\n"
         "services.prompt_registry._effective_prompt_raw('k', 'c')\n",
         "services.prompt_registry._effective_prompt_raw"),
        ("from services.prompt_release_policy import journal_write_scope\n"
         "journal_write_scope(None)\n",
         "services.prompt_release_policy.journal_write_scope"),
        # Отрицательные контроли: обычные чтения/вызовы не считаются.
        ("from services import chat_params\n"
         "chat_params.get_all_chat_params(1)\n", None),
        ("from services import prompt_text\n"
         "prompt_text.guard_view('k')\n", None),
    ])
    def test_alias_detector_catches_every_import_form(self, src, expected):
        """Самопроверка детектора: все формы импорта/алиасинга ловятся.

        Включая точечную запись через корневой модуль
        (``import services.prompt_text`` -> ``services.prompt_text.system_scope``)
        и сырые материализаторы реестра (``_FACTORY_TEXTS``)."""
        offenders = self._scan_offenders(ast.parse(src),
                                         "web/api/probe.py")
        found = [path for _rel, path in offenders]
        if expected is None:
            assert found == [], offenders
        else:
            assert found == [expected], offenders

    @pytest.mark.parametrize("rel,func", [
        ("services/prompt_composer.py", "compose_speech_system"),
        ("services/prompt_composer.py", "compose_machine_system"),
        ("services/direct_chat_service.py", "_l2_write_answer"),
        ("services/mca_authorial_speech.py", "authorial_system"),
    ])
    def test_runtime_entries_declare_system_scope(self, rel, func):
        tree = self._tree(rel)
        node = _find_func(tree, func)
        assert node is not None, (rel, func)
        assert _calls_name(node, "system_scope"), (rel, func)

    @pytest.mark.parametrize("rel,func,guard", [
        ("services/prompt_registry.py", "factory_text", "guard_view"),
        ("services/prompt_registry.py", "effective_prompt", "guard_view"),
        ("services/prompt_registry.py", "core_selection", "guard_view"),
        ("services/prompt_registry.py", "style_policy_view", "guard_view"),
        ("services/prompt_composer.py", "compose_prompt", "guard_manifest"),
        ("services/prompt_composer.py", "render_layer_texts", "guard_manifest"),
        ("services/prompt_release_policy.py", "get_revision_source",
         "_guard_revision"),
        ("services/prompt_release_policy.py", "diff_revisions",
         "_guard_revision"),
        ("services/prompt_release_policy.py", "write_prompt_values",
         "guard_edit"),
        ("services/prompt_release_policy.py", "remove_prompt_override",
         "guard_edit"),
        ("services/prompt_factory.py", "history_for", "guard_view"),
    ])
    def test_owner_functions_call_the_guard(self, rel, func, guard):
        tree = self._tree(rel)
        node = _find_func(tree, func)
        assert node is not None, (rel, func)
        assert _calls_name(node, guard), (rel, func, guard)


def _find_func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    return None


def _calls_name(node, attr: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute) and func.attr == attr:
                return True
            if isinstance(func, ast.Name) and func.id == attr:
                return True
    return False

class TestGuardSeams:
    """Точечные швы стражи: каждая мутация «убрать страж» убивается здесь.

    Полный прогон A ловит УТЕЧКУ, но при слоистых стражах одиночное удаление
    одного стража маскируется соседним; эти проверки изолируют шов."""

    def _chat_deny(self):
        return prompt_text.TextScope(kind="chat", chat_id=CHAT_A)

    def test_effective_prompt_guard(self):
        with prompt_text.use_scope(self._chat_deny()):
            with pytest.raises(prompt_text.PromptTextDenied):
                pr.effective_prompt(BASE_BLOCK, pg_value=None, chat_value=MARK)

    def test_factory_text_guard(self):
        with prompt_text.use_scope(self._chat_deny()):
            with pytest.raises(prompt_text.PromptTextDenied):
                pr.factory_text(BASE_BLOCK)

    def test_compose_prompt_manifest_guard(self, monkeypatch):
        """Только стража манифеста: сборка подменена синтетическим манифестом
        со слоем guarded-блока (так выглядит «текст уже материализован
        вызывающим»)."""
        from services import prompt_composer as composer

        layer = composer.LayerTrace(layer="base", block_id=BASE_BLOCK,
                                    rendered=True, text=MARK)
        manifest = composer.PromptManifest(system=MARK, layers=(layer,))
        monkeypatch.setattr(composer, "_compose", lambda plan: manifest)
        plan = composer.PromptPlan(profile=composer.PROFILE_SPEECH_PLAIN,
                                   writer="probe", chat_id=CHAT_A,
                                   base_prompt=MARK)
        with prompt_text.use_scope(self._chat_deny()):
            with pytest.raises(prompt_text.PromptTextDenied):
                composer.compose_prompt(plan)

    def test_render_layer_texts_guard(self):
        from services import prompt_composer as composer

        layer = composer.LayerTrace(layer="base", block_id=BASE_BLOCK,
                                    rendered=True, text=MARK)
        manifest = composer.PromptManifest(system=MARK, layers=(layer,))
        with prompt_text.use_scope(self._chat_deny()):
            with pytest.raises(prompt_text.PromptTextDenied):
                composer.render_layer_texts(manifest)

    def test_write_prompt_values_edit_guard(self):
        from services.prompt_release_policy import PromptWriteItem, write_prompt_values
        item = PromptWriteItem(block_id=BASE_BLOCK, text=MARK)
        with prompt_text.use_scope(self._chat_deny()):
            with pytest.raises(prompt_text.PromptTextDenied):
                import asyncio

                asyncio.run(write_prompt_values(
                    [item], scope="chat", chat_id=CHAT_A, actor="probe"))
