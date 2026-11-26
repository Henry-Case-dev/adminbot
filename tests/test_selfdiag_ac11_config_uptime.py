"""SELF-DIAG postdeploy AC11 (2.58.252) — два дефекта, два замка.

DEFECT 1 (MAC-S10-13, security-relevant): ``GET /api/config`` БЕЗ ``X-Chat-Id``
отдавал ТЕКСТ промпта любой аутентифицированной роли. Глобальная ветка
фильтровала только ``spec.secret``, а ресурсная матрица (``view_roles``)
применялась лишь в чатовом скоупе. Замок: роль без гранта не получает ни
значения, ни ключа; глобальный админ и роль с явным грантом — получают;
чатовая ветка не изменилась; прочие настройки не сужены.

DEFECT 2: ``/api/status/self-diagnosis`` отдавал ``runtime.uptime_seconds =
null``, потому что вычитал ISO-строку ``status.started_at`` из ``datetime``
(``TypeError`` → ``None``). ``/api/status`` считает аптайм корректно. Замок:
оба эндпоинта дают ненулевой аптайм и согласуются.

TEST-LIFECYCLE: CONTRACT owner=SELF-DIAG-01/AC11+MAC-S10-13
"""
from __future__ import annotations

import datetime
import time
import types
from unittest.mock import MagicMock

import pytest

from services import access as access_srv
from tests.test_mod_acl_ux_01_m1c_prompt_chat_acl import (
    ADMIN,
    CHAT_A,
    LOCAL_ADMIN,
    MEMBER,
    PG_KEY,
    VIEW_MODERATOR_ONLY,
    _hdr,
    make_client,
)
from tests.test_mod_acl_ux_m4c_acl_hardening import MODERATOR_ID, TEST_TOKEN
from web.api import deps as deps_mod
from web.api import routes as routes_mod

PROMPT_TEXT = "AC11-PROMPT-MARKER: текст инструкции, который не должен утечь.\n"
GRANTED_PROMPT_MATRIX = {"view_roles": ["moderator"], "edit_roles": []}


@pytest.fixture(autouse=True)
def _api_token(monkeypatch):
    """Тот же TMA-токен, что у M1-C замка: реальный RBAC на фейковом PG."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    yield
    access_srv.reset_param_permissions_cache()


def _prompt_client(monkeypatch, *, matrix=None):
    """Клиент с РЕАЛЬНЫМ значением промпта в bot_settings (как в проде)."""
    client = make_client(monkeypatch, matrix=matrix)
    client.cache._settings[PG_KEY] = PROMPT_TEXT
    client.cache._settings_updated_at[PG_KEY] = "2026-11-26T00:00:00+00:00"
    return client


def _item(payload: dict, key: str) -> dict | None:
    return next((item for item in payload["items"]
                 if item.get("key") == key), None)


# ═══════════════════════════════════════════════════════════════════════════
# DEFECT 1 — глобальный /api/config не отдаёт ТЕКСТ промпта без гранта
# ═══════════════════════════════════════════════════════════════════════════

class TestGlobalConfigPromptTextACL:
    """Без ``X-Chat-Id``: значение решает ресурсная матрица, не «любая роль»."""

    def test_plain_user_gets_no_prompt_value_or_key(self, monkeypatch):
        client = _prompt_client(monkeypatch)
        resp = client.get("/api/config", headers=_hdr(MEMBER))
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert _item(payload, PG_KEY) is None
        assert PROMPT_TEXT.strip() not in resp.text

    def test_moderator_gets_no_prompt_value_or_key(self, monkeypatch):
        client = _prompt_client(monkeypatch)
        resp = client.get("/api/config", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert _item(payload, PG_KEY) is None
        assert PROMPT_TEXT.strip() not in resp.text

    def test_global_admin_keeps_prompt_value(self, monkeypatch):
        """Владелец видит значение целиком — ответ не обеднён."""
        client = _prompt_client(monkeypatch)
        payload = client.get("/api/config", headers=_hdr(ADMIN)).json()
        item = _item(payload, PG_KEY)
        assert item is not None
        assert item["value"] == PROMPT_TEXT

    def test_explicit_grant_still_reveals_prompt(self, monkeypatch):
        """Легитимный DB-грант (param_permissions) сильнее дефолта."""
        client = _prompt_client(monkeypatch, matrix=GRANTED_PROMPT_MATRIX)
        payload = client.get("/api/config", headers=_hdr(MODERATOR_ID)).json()
        item = _item(payload, PG_KEY)
        assert item is not None
        assert item["value"] == PROMPT_TEXT

    def test_non_prompt_settings_are_not_narrowed(self, monkeypatch):
        """Дефект — только текст промпта: limits.* остаются видны любой роли."""
        client = _prompt_client(monkeypatch)
        client.cache._settings["limits.checkup_max_symbols"] = 1200
        payload = client.get("/api/config", headers=_hdr(MEMBER)).json()
        item = _item(payload, "limits.checkup_max_symbols")
        assert item is not None
        assert item["value"] == 1200

    def test_chat_scope_matrix_semantics_unchanged(self, monkeypatch):
        """Чатовая ветка: дефолт local_admin видит, override — скрывает."""
        client = _prompt_client(monkeypatch)
        payload = client.get("/api/config", headers=_hdr(LOCAL_ADMIN, CHAT_A)) \
            .json()
        assert _item(payload, PG_KEY) is not None

        restricted = _prompt_client(monkeypatch, matrix=VIEW_MODERATOR_ONLY)
        payload = restricted.get(
            "/api/config", headers=_hdr(LOCAL_ADMIN, CHAT_A)).json()
        assert _item(payload, PG_KEY) is None


# ═══════════════════════════════════════════════════════════════════════════
# DEFECT 2 — self-diagnosis и /api/status согласны по аптайму
# ═══════════════════════════════════════════════════════════════════════════

async def _no_health(self, module_id, base_url, key, model="", kind="chat"):
    return {"ok": False, "status": "not_configured", "http_status": None,
            "latency_ms": None, "checked_at": None}


async def _no_uptime(self, pg):
    return []


class TestSelfDiagnosisUptime:
    @pytest.mark.asyncio
    async def test_uptime_is_non_null_and_matches_status(self, monkeypatch):
        from services import status_service

        svc = status_service.status
        started = datetime.datetime.now(datetime.timezone.utc) \
            - datetime.timedelta(seconds=3600)
        monkeypatch.setattr(svc, "started_at", started.isoformat())
        monkeypatch.setattr(svc, "started_monotonic",
                            time.monotonic() - 3600.0)
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: None)
        monkeypatch.setattr(
            "services.deploy_identity.collect_identity",
            lambda root=None, *, process_started_at=None:
                {"deployed_sha": "deadbeef"})
        monkeypatch.setattr(status_service.StatusService, "_check_health",
                            _no_health)
        monkeypatch.setattr(status_service.StatusService, "fetch_uptime_rows",
                            _no_uptime)
        monkeypatch.setattr(routes_mod, "_self_diag_cache", {})

        async def _allow(*args, **kwargs):
            return types.SimpleNamespace(allowed=True, reason_code="allowed")
        monkeypatch.setattr("services.diagnostic_policy.decide", _allow)

        client = _prompt_client(monkeypatch)
        request = MagicMock()
        monkeypatch.setattr(routes_mod, "get_cache", lambda _req: client.cache)
        user = types.SimpleNamespace(id=ADMIN)

        status_payload = await routes_mod.get_status(
            request, user, x_chat_id=None)
        diag_payload = await routes_mod.get_status_self_diagnosis(
            request, user, x_chat_id=None)

        uptime = diag_payload["runtime"]["uptime_seconds"]
        assert uptime is not None
        assert isinstance(uptime, int) and uptime > 0
        # Ровно тот аптайм, что видит оператор на /api/status.
        api_uptime = status_payload["bot"]["uptime_seconds"]
        assert abs(uptime - api_uptime) <= 2.0
        assert diag_payload["runtime"]["started_at"] == started.isoformat()
