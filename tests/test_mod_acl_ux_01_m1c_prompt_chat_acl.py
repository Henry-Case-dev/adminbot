"""MOD-ACL-UX-01 M1-C — постоянный замок MAC-S10-13: промпты в групповом чате.

Контракт строки: «промпты видны строго по resource ACL» — включая контекст
группового чата. Проверяются РЕАЛЬНЫЕ роутеры промптов и РЕАЛЬНЫЙ слой прав
(`services.roles.access_for`, `services.access.effective_matrix/can_view_param/
can_edit_param`); двойники — только хранилище (роли/админы/chat_admins/
param_permissions) и in-memory журнал промптов, как в соседних ACL-наборах.

Проверяется поведение, а не строки:

  1. **Просмотр решается матрицей ресурса** (`view_roles`): `local_admin`
     чата, исключённый из `view_roles` (`["moderator"]`), не получает ни
     историю (`/versions`), ни текст (`/revisions/{id}/source`), ни diff, ни
     baseline — 403 и без текста промпта в теле ответа. Контроль: с
     дефолтной матрицей тот же актор видит всё (это не безусловный отказ).
  2. **Запись решается `edit_roles`** ровно как раньше: `view_roles:
     ["local_admin"]` + `edit_roles: []` → просмотр 200, активация 403;
     дефолтная матрица → активация 200.
  3. **Изоляция чата**: участник без гранта — 403 на просмотр и запись; чужой
     чат (`X-Chat-Id` другого чата) — 403 и на историю.
  4. **Глобальный админ** не зависит от override: 200 на всех маршрутах.
  5. `GET /api/config` — контроль того же правила: с ограниченной матрицей
     ключа в списке нет, с дефолтной — есть.

RED-строка до исправления: кейсы 1 (просмотр истории/текста/diff/baseline при
`view_roles: ["moderator"]`) — 200 вместо 403.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/MAC-S10-13
"""
from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient

from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services import access as access_srv
from services.config_cache import ConfigCache
from tests.test_evol016_prompt_activation import FactoryEdition
from tests.test_mod_acl_ux_m4c_acl_hardening import (  # noqa: F401 — ids
    LOCAL_ADMIN_ID, OWNER_ID, PLAIN_USER_ID, TEST_TOKEN, _Conn, _Db, _Pg,
    _seed, make_init_data,
)
from web.api import deps as deps_mod
from web.api import routes as routes_mod
from web.app import create_app

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"
FACTORY_A = "ЗАВОДСКОЙ A: рассказчик саммари (замок MAC-S10-13).\n"
FACTORY_B = "РУЧНАЯ B: вторая ревизия того же блока (замок MAC-S10-13).\n"

CHAT_A = -1001000000001
CHAT_B = -1001000000002

LOCAL_ADMIN = LOCAL_ADMIN_ID
MEMBER = PLAIN_USER_ID
ADMIN = OWNER_ID

# дискриминирующие матрицы ключа (обе — валидные нормализованные формы)
VIEW_MODERATOR_ONLY = {"view_roles": ["moderator"], "edit_roles": ["moderator"]}
VIEW_ONLY_LOCAL_ADMIN = {"view_roles": ["local_admin"], "edit_roles": []}


class ChatConn(_Conn):
    """Двойник хранилища + гранты `chat_admins` + строки `param_permissions`."""

    def __init__(self, db, chat_grants: dict):
        super().__init__(db)
        self.chat_grants = dict(chat_grants)
        self.perm_rows: dict[str, dict] = {}

    async def fetchrow(self, sql, *args):
        low = " ".join(sql.lower().split())
        if "from chat_admins" in low:
            role = self.chat_grants.get((int(args[0]), int(args[1])))
            return {"role_name": role} if role else None
        if "from param_permissions" in low and low.startswith("select"):
            row = self.perm_rows.get(args[0])
            return dict(row) if row else None
        return await super().fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        if "from param_permissions" in " ".join(sql.lower().split()):
            return [dict(row) for row in self.perm_rows.values()]
        return await super().fetch(sql, *args)


@pytest.fixture(autouse=True)
def _api_token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    yield
    access_srv.reset_param_permissions_cache()


@pytest.fixture()
def edition(monkeypatch):
    """Заводская редакция блока + сброс реестра после теста."""
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    yield patch
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


def make_client(monkeypatch, *, matrix: dict | None = None,
                grants: dict | None = None) -> TestClient:
    """Клиент со реальным RBAC; матрица ключа и гранты чата — параметры."""
    # TTL-кэш override'ов (`param_permissions`) — модульный global: без сброса
    # матрица предыдущего теста жила бы 60 с и искажала следующий кейс.
    access_srv.reset_param_permissions_cache()
    db = _Db()
    conn = ChatConn(db, grants if grants is not None
                    else {(CHAT_A, LOCAL_ADMIN): "local_admin"})
    if matrix is not None:
        conn.perm_rows[PG_KEY] = {"key": PG_KEY,
                                 "value": json.dumps(matrix),
                                 "updated_at": "2026-11-26T00:00:00+00:00"}
    cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
    _seed(cache, db)
    journal = prp.MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    client = TestClient(create_app(cache))
    client.cache = cache
    client.journal = journal
    return client


def _hdr(user_id: int, chat_id: int | None = None) -> dict:
    out = {"X-Telegram-Init-Data": make_init_data(user_id)}
    if chat_id is not None:
        out["X-Chat-Id"] = str(chat_id)
    return out


def _seed_revision(client, text: str, chat_id: int, *, origin: str = "manual"):
    revision_id = pr.revision_id_for(BLOCK, "chat", chat_id, origin,
                                     pr.sha12(text))
    client.journal.revisions[revision_id] = prp.RevisionRow(
        revision_id=revision_id, block_id=BLOCK, scope="chat", origin=origin,
        content_sha12=pr.sha12(text), body=text, pg_key=PG_KEY,
        chat_id=chat_id, created_at="2026-11-26T00:00:00+00:00")
    return revision_id


def _get(client, path, headers):
    return client.get(path, headers=headers)


def _activate(client, revision_id, headers):
    return client.post(f"/api/prompts/{PG_KEY}/activate",
                       json={"revision_id": revision_id}, headers=headers)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Просмотр по матрице ресурса (RED до F02)
# ═══════════════════════════════════════════════════════════════════════════

class TestViewIsGovernedByResourceMatrix:
    """`view_roles: ["moderator"]` — local_admin чата не видит промпт нигде."""

    @pytest.fixture()
    def restricted(self, monkeypatch, edition):
        client = make_client(monkeypatch, matrix=VIEW_MODERATOR_ONLY)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)
        rev2 = _seed_revision(client, FACTORY_B, CHAT_A)
        return client, headers, rev, rev2

    def test_versions_denied(self, restricted):
        client, headers, _, _ = restricted
        resp = _get(client, f"/api/prompts/{PG_KEY}/versions", headers)
        assert resp.status_code == 403, resp.text

    def test_source_denied_and_no_body(self, restricted):
        client, headers, rev, _ = restricted
        resp = _get(client, f"/api/prompts/revisions/{rev}/source", headers)
        assert resp.status_code == 403, resp.text
        assert FACTORY_A.strip() not in resp.text
        assert "body" not in resp.text

    def test_diff_denied(self, restricted):
        client, headers, rev, rev2 = restricted
        resp = _get(client, f"/api/prompts/revisions/diff?a={rev}&b={rev2}",
                    headers)
        assert resp.status_code == 403, resp.text
        assert FACTORY_A.strip() not in resp.text

    def test_baseline_metadata_denied(self, restricted):
        client, headers, _, _ = restricted
        resp = _get(client, f"/api/prompts/{PG_KEY}/baseline", headers)
        assert resp.status_code == 403, resp.text

    def test_config_control_hides_same_key(self, restricted):
        """Тот же актор и ключ: /api/config ключ НЕ отдаёт (одно правило)."""
        client, headers, _, _ = restricted
        payload = _get(client, "/api/config", headers).json()
        assert PG_KEY not in [item.get("key") for item in payload["items"]]

    def test_default_matrix_control_allows_same_actor(self, monkeypatch,
                                                     edition):
        """Контроль: с дефолтной матрицей тот же актор видит всё — 403 выше
        создан именно override, а не безусловным отказом."""
        client = make_client(monkeypatch)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)

        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 200
        source = _get(client, f"/api/prompts/revisions/{rev}/source", headers)
        assert source.status_code == 200, source.text
        assert source.json().get("body") == FACTORY_A
        assert _get(client, f"/api/prompts/{PG_KEY}/baseline",
                    headers).status_code == 200
        payload = _get(client, "/api/config", headers).json()
        assert PG_KEY in [item.get("key") for item in payload["items"]]


# ═══════════════════════════════════════════════════════════════════════════
# 2. Запись по edit_roles — семантика не изменилась
# ═══════════════════════════════════════════════════════════════════════════

class TestEditStaysGovernedByEditRoles:
    def test_view_allowed_edit_denied(self, monkeypatch, edition):
        client = make_client(monkeypatch, matrix=VIEW_ONLY_LOCAL_ADMIN)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)

        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 200
        assert _get(client, f"/api/prompts/revisions/{rev}/source",
                    headers).status_code == 200
        assert _activate(client, rev, headers).status_code == 403

    def test_default_matrix_edit_allowed(self, monkeypatch, edition):
        client = make_client(monkeypatch)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)
        assert _activate(client, rev, headers).status_code == 200

    def test_edit_implies_view_after_normalization(self, monkeypatch, edition):
        """`view_roles |= edit_roles` (правило сервиса прав): актор с правом
        записи не может потерять чтение из-за новой проверки."""
        matrix = {"view_roles": [], "edit_roles": ["local_admin"]}
        client = make_client(monkeypatch, matrix=matrix)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)
        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 200
        assert _activate(client, rev, headers).status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 3. Изоляция: участник без гранта и чужой чат
# ═══════════════════════════════════════════════════════════════════════════

class TestChatIsolation:
    def test_member_without_grant_denied(self, monkeypatch, edition):
        client = make_client(monkeypatch)
        headers = _hdr(MEMBER, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)
        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 403
        assert _get(client, f"/api/prompts/revisions/{rev}/source",
                    headers).status_code == 403
        assert _activate(client, rev, headers).status_code == 403

    def test_foreign_chat_history_denied(self, monkeypatch, edition):
        """local_admin чата A не читает историю чата B через X-Chat-Id."""
        client = make_client(monkeypatch)
        headers = _hdr(LOCAL_ADMIN, CHAT_B)
        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 403

    def test_revision_of_foreign_chat_denied_without_header(
            self, monkeypatch, edition):
        """Ревизия чужого чата не отдаётся и без X-Chat-Id: scope берётся из
        самой ревизии."""
        client = make_client(monkeypatch)
        headers = _hdr(LOCAL_ADMIN, CHAT_A)
        foreign = _seed_revision(client, FACTORY_B, CHAT_B)
        resp = _get(client, f"/api/prompts/revisions/{foreign}/source", headers)
        assert resp.status_code == 403, resp.text
        assert FACTORY_B.strip() not in resp.text


# ═══════════════════════════════════════════════════════════════════════════
# 4. Глобальный админ не зависит от override
# ═══════════════════════════════════════════════════════════════════════════

class TestGlobalAdminUnaffected:
    def test_admin_reads_and_activates_with_restricted_matrix(
            self, monkeypatch, edition):
        client = make_client(monkeypatch, matrix=VIEW_MODERATOR_ONLY)
        headers = _hdr(ADMIN, CHAT_A)
        rev = _seed_revision(client, FACTORY_A, CHAT_A)
        assert _get(client, f"/api/prompts/{PG_KEY}/versions",
                    headers).status_code == 200
        source = _get(client, f"/api/prompts/revisions/{rev}/source", headers)
        assert source.status_code == 200, source.text
        assert source.json().get("body") == FACTORY_A
        assert _get(client, f"/api/prompts/{PG_KEY}/baseline",
                    headers).status_code == 200
        assert _activate(client, rev, headers).status_code == 200
