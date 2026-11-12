"""SELF-DIAG-01 D2-24 (`SD1-D2-24`) — typed settings adapter и запрет blob.

ТЗ §9.1: «Секретный blob никогда не сериализуется в DiagnosticEvidenceBundle
или обычный ToolResult. При технической проверке возвращаются `configured`,
`effective`, `last_success`, `last_error_code`, `key_fingerprint` (только если
уже безопасно принят проектом), но не value».

Проверяется наблюдаемый результат, а не внутренние вызовы:
  * адаптер отдаёт закрытый набор полей, значение секрета не появляется ни в
    одном из них;
  * для NON_SECRET_CONFIG значение действует, для SECRET/PROMPT — только
    статус-токен;
  * неизвестный (не классифицированный) ключ значение не раскрывает;
  * `last_success`/`last_error_code` берутся из существующих наблюдаемых
    исходов провайдеров, а не выдумываются;
  * bundle `config.secret_status` и обычный ToolResult (`inspect_runtime`)
    не содержат значения секрета, но содержат обязательные поля.
"""
import json

import pytest

from services import diagnostic_collector as dc
from services import hot_config as hot
from services import output_projection
from services import settings_view
from services.tool_router import ToolContext, ToolDeps, ToolRouter

SECRET_VALUE = "sk-live-abcdef123456"
OWNER_ID = 5885953495
GROUP_A = -1001000000001


class FakeCache:
    """ConfigCache + слой ролей: значения настроек и роль владельца."""

    def __init__(self, values=None, roles=None):
        self._values = dict(values or {})
        self._roles = dict(roles or {OWNER_ID: "admin"})

    # ConfigCache-часть
    def get(self, key, default=None):
        return self._values.get(str(key), default)

    def get_updated_at(self, key):
        return None

    def loaded_at(self):
        return "2026-11-13T00:00:00+00:00"

    # Слой прав (тот же контракт, что у реального кеша)
    def get_role(self, telegram_id):
        return self._roles.get(telegram_id)

    def get_permissions_by_telegram_id(self, telegram_id):
        from services.permissions import Permissions
        if self._roles.get(telegram_id) is None:
            return None
        return Permissions.from_dict({"wildcard": True})

    def get_permissions(self, role_name):
        from services.permissions import Permissions
        if role_name not in ("admin",):
            return None
        return Permissions.from_dict({"wildcard": True})

    def roles(self):
        return {"admin": {"permissions": {"wildcard": True},
                          "is_custom": False, "role_type": "global_admin"}}


@pytest.fixture
def cache():
    fake = FakeCache({"keys.image_api_key": SECRET_VALUE,
                      "limits.checkup_max_symbols": 1200})
    previous = hot.get_config_cache()
    hot.set_config_cache(fake)
    try:
        yield fake
    finally:
        hot.set_config_cache(previous)


def _collector(**deps_kw):
    from services import runtime_probes as rp
    return dc.DiagnosticCollector(deps=rp.ProbeDeps(**deps_kw),
                                  limits=rp.ProbeLimits(max_output_chars=9000))


async def _collect_secret_status(collector):
    return await collector.collect(dc.CollectionRequest(
        probe="config.secret_status", chat_id=GROUP_A,
        scope="current_chat", request_id="d2-24"))


# ── Адаптер: закрытый набор полей и отсутствие значения ───────────────────

def test_adapter_returns_closed_field_set_without_secret_value(cache):
    view = settings_view.setting_view("keys.image_api_key", cache=cache)
    assert set(view) == set(settings_view.VIEW_FIELDS)
    assert view["key"] == "keys.image_api_key"
    assert view["classified"] is True
    assert view["sensitivity"] == "SECRET_VALUE"
    assert view["configured"] is True
    assert view["effective"] == "configured"
    assert view["effective_kind"] == "status"
    assert view["value_exposed"] is False
    assert view["key_fingerprint"] == "…3456"
    assert view["fingerprint_kind"] == "last4"
    assert SECRET_VALUE not in json.dumps(view, ensure_ascii=False)
    assert "abcdef" not in json.dumps(view, ensure_ascii=False)


def test_prompt_content_is_a_status_not_a_text(cache):
    cache._values["prompts.checkup_system_prompt"] = "секретный текст промпта"
    view = settings_view.setting_view("prompts.checkup_system_prompt",
                                      cache=cache)
    assert view["sensitivity"] == "PROMPT_CONTENT"
    assert view["configured"] is True
    assert view["effective"] == "configured"
    assert view["value_exposed"] is False
    assert view["key_fingerprint"] is None
    assert "секретный текст" not in json.dumps(view, ensure_ascii=False)


def test_non_secret_config_keeps_its_value(cache):
    view = settings_view.setting_view("limits.checkup_max_symbols",
                                      cache=cache)
    assert view["sensitivity"] == "NON_SECRET_CONFIG"
    assert view["effective"] == 1200
    assert view["effective_kind"] == "value"
    assert view["value_exposed"] is True
    assert view["key_fingerprint"] is None


def test_unclassified_key_never_leaks_value(cache):
    cache._values["provider.new_unknown_secret"] = SECRET_VALUE
    view = settings_view.setting_view("provider.new_unknown_secret",
                                      cache=cache)
    assert view["classified"] is False
    assert view["configured"] is True        # факт наличия — можно
    assert view["effective"] is None         # значение — нельзя
    assert view["value_exposed"] is False
    assert view["reason_code"] == settings_view.REASON_UNCLASSIFIED
    assert SECRET_VALUE not in json.dumps(view, ensure_ascii=False)


def test_short_and_list_values_get_no_fingerprint(cache):
    short = settings_view.setting_view("keys.image_api_key",
                                       cache=FakeCache({
                                           "keys.image_api_key": "abc"}))
    assert short["configured"] is True
    assert short["key_fingerprint"] is None
    listed = settings_view.setting_view(
        "keys.embedding_extra_api_keys",
        cache=FakeCache({"keys.embedding_extra_api_keys": ["k1-secret-key",
                                                          "k2-secret-key"]}))
    assert listed["configured"] is True
    assert listed["key_fingerprint"] is None
    assert "secret-key" not in json.dumps(listed, ensure_ascii=False)


# ── last_success / last_error_code из существующих исходов ────────────────

def test_capability_outcomes_map_gates_to_provider_results():
    states = [
        {"gates": ["keys.image_api_key"], "last_result": "success",
         "last_result_code": "", "checked_at": "2026-11-13T09:00:00+00:00",
         "reason_code": ""},
        {"gates": ["keys.tavily_api_key"], "last_result": "failed",
         "last_result_code": "provider_timeout",
         "checked_at": "2026-11-13T09:30:00+00:00", "reason_code": ""},
        {"gates": ["keys.exa_api_key"], "last_result": "unknown",
         "last_result_code": "", "checked_at": None, "reason_code": ""},
    ]
    outcomes = settings_view.capability_outcomes(states)
    assert outcomes["keys.image_api_key"]["last_success"] \
        == "2026-11-13T09:00:00+00:00"
    assert outcomes["keys.image_api_key"]["last_error_code"] is None
    assert outcomes["keys.tavily_api_key"]["last_error_code"] \
        == "provider_timeout"
    assert outcomes["keys.tavily_api_key"]["last_success"] is None
    assert "keys.exa_api_key" not in outcomes      # «unknown» — не измерено

    view = settings_view.setting_view(
        "keys.image_api_key",
        cache=FakeCache({"keys.image_api_key": SECRET_VALUE}),
        outcomes=outcomes)
    assert view["outcome_observed"] is True
    assert view["last_success"] == "2026-11-13T09:00:00+00:00"
    assert view["last_error_code"] is None


def test_summary_is_bounded_and_reports_truncation():
    cache = FakeCache({key: f"value-for-{key}-0123456789"
                       for key in settings_view.secret_setting_keys()})
    summary = settings_view.secret_status_summary(cache=cache,
                                                  max_detailed=5)
    assert summary["total"] == len(settings_view.secret_setting_keys())
    assert summary["configured"] == summary["total"]
    assert len(summary["secrets"]) == 5
    assert len(summary["truncated_keys"]) == summary["total"] - 5
    assert summary["value_exposed"] is False
    assert "value-for-" not in json.dumps(summary, ensure_ascii=False)


# ── Bundle и обычный ToolResult ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_bundle_has_required_fields_and_never_the_secret(cache):
    bundle, page = await _collect_secret_status(_collector())
    bundle_blob = json.dumps(bundle.to_dict(), ensure_ascii=False)
    page_blob = json.dumps(page, ensure_ascii=False)
    for blob in (bundle_blob, page_blob):
        assert SECRET_VALUE not in blob
        assert "abcdef" not in blob
    source = next(src for src in bundle.to_dict()["sources"]
                  if src["source_id"] == "config:secret_status")
    item = next(entry for entry in source["facts"]["secrets"]
                if entry["key"] == "keys.image_api_key")
    assert item["configured"] is True
    assert item["effective"] == "configured"
    assert item["key_fingerprint"] == "…3456"
    assert item["last_success"] is None
    assert item["last_error_code"] is None
    assert source["facts"]["value_exposed"] is False
    assert "secret_values" in source["not_checked"]


@pytest.mark.asyncio
async def test_provider_outcomes_reach_the_bundle(cache, monkeypatch):
    async def fake_view(chat_id=None):
        return [{"gates": ["keys.image_api_key"], "last_result": "failed",
                 "last_result_code": "provider_timeout",
                 "checked_at": "2026-11-13T09:30:00+00:00",
                 "reason_code": ""}]

    collector = _collector(capability_view=fake_view)
    bundle, _ = await _collect_secret_status(collector)
    source = next(src for src in bundle.to_dict()["sources"]
                  if src["source_id"] == "config:secret_status")
    item = next(entry for entry in source["facts"]["secrets"]
                if entry["key"] == "keys.image_api_key")
    assert item["last_error_code"] == "provider_timeout"
    assert item["last_success"] is None


@pytest.mark.asyncio
async def test_tool_result_never_contains_secret_blob(cache, monkeypatch):
    """Обычный ToolResult: те же поля, значения нет (реальный output-границ)."""
    collector = _collector()
    router = ToolRouter(ToolDeps(None, None, diagnostics=collector))
    monkeypatch.setattr(ToolRouter, "_diag_runtime",
                        staticmethod(lambda: (cache, None)))
    ctx = ToolContext(chat_id=GROUP_A, query="состояние ключей",
                      user_id=OWNER_ID)
    result = await router.dispatch(
        "inspect_runtime", {"probe": "config.secret_status"}, ctx)
    assert SECRET_VALUE not in result
    assert "abcdef" not in result
    payload = json.loads(result)
    source = payload["sources"][0]
    assert source["source_id"] == "config:secret_status"
    item = next(entry for entry in source["facts"]["secrets"]
                if entry["key"] == "keys.image_api_key")
    assert set(item) == set(settings_view.COMPACT_FIELDS)
    assert item["configured"] is True
    assert item["effective"] == "configured"
    assert item["key_fingerprint"] == "…3456"


@pytest.mark.asyncio
async def test_secret_never_appears_in_logs(cache, monkeypatch, caplog):
    """Ни одна запись журнала на этом маршруте не несёт значение секрета."""
    import logging

    collector = _collector()
    router = ToolRouter(ToolDeps(None, None, diagnostics=collector))
    monkeypatch.setattr(ToolRouter, "_diag_runtime",
                        staticmethod(lambda: (cache, None)))
    ctx = ToolContext(chat_id=GROUP_A, query="ключи", user_id=OWNER_ID)
    with caplog.at_level(logging.DEBUG):
        result = await router.dispatch(
            "inspect_runtime", {"probe": "config.secret_status"}, ctx)
    assert SECRET_VALUE not in result
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET_VALUE not in joined
    assert "abcdef" not in joined


@pytest.mark.asyncio
async def test_tool_result_blocked_when_secret_sources_incomplete(
        cache, monkeypatch):
    """Неполные источники секретов → fail-closed, а не «надеемся, что чисто»."""
    collector = _collector()
    router = ToolRouter(ToolDeps(None, None, diagnostics=collector))
    monkeypatch.setattr(ToolRouter, "_diag_runtime",
                        staticmethod(lambda: (cache, None)))

    async def incomplete(*args, **kwargs):
        return output_projection.SecretSnapshot({}, False, ("settings",))

    monkeypatch.setattr(output_projection, "known_secret_values_async",
                        incomplete)
    ctx = ToolContext(chat_id=GROUP_A, query="ключи", user_id=OWNER_ID)
    result = await router.dispatch(
        "inspect_runtime", {"probe": "config.secret_status"}, ctx)
    assert SECRET_VALUE not in result
    assert "вывод заблокирован политикой секретов" in result
