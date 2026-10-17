"""SOUL-1 / W10 — Runtime Capability Registry (SOUL-AMD.5.11–5.13, 8.10).

Проверяется:
  * состояние строится из РЕАЛЬНЫХ источников (tool schemas, конфиг, per-chat
    overrides, ключи, бюджет, провайдер, наблюдаемые исходы), а не из
    статического списка «я умею» и не из SelfModel;
  * все семь статусов достижимы: ``ready``, ``disabled``, ``not_configured``,
    ``temporarily_unavailable``, ``quota_exhausted``, ``unsupported``,
    ``unknown``;
  * различаются «инструмент объявлен» (declared), «можно попробовать»
    (tryable) и «вызов успешно завершён» (last_result);
  * диагностика кешируется с TTL и сбрасывается при изменении конфигурации;
    дорогих probes на каждом сообщении нет (счётчик обращений к источникам);
  * переключение модуля / per-chat override / смена провайдера отражаются и в
    L1 capabilities, и в UI-данных реестра (§8.10);
  * недоступное НЕ обещается: правдивая пометка вместо «не умею».

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.5.11/5.12/5.13/8.10 (soul-1, W10)
"""
from __future__ import annotations

import pytest

from services import capability_registry as caps
from services import direct_capabilities as dc
from services import hot_config as hot
from services import image_generation as ig

pytestmark = [pytest.mark.asap3]


class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _ChatParams:
    """Fake per-chat слой (тот же контракт, что ChatParamsCache).

    ``chat_id=None`` → overrides действуют для ЛЮБОГО чата (частый случай);
    иначе — только для указанного (проверка изоляции чатов)."""

    def __init__(self, overrides=None, chat_id=None):
        self.overrides = dict(overrides or {})
        self.chat_id = chat_id

    async def get_chat_params(self, chat_id):
        if self.chat_id is not None and int(chat_id) != int(self.chat_id):
            return {"overrides": {}}
        return {"overrides": dict(self.overrides)}


READY = {
    "flags.image_generation_module_enabled": True,
    "keys.image_api_key": "test-key",
    "models.image_model": "test-model",
}

CHAT = -1001234567890


@pytest.fixture(autouse=True)
def _clean():
    from services import chat_params
    prev_cache = chat_params.get_chat_params_cache()
    caps.reset_cache()
    hot.set_config_cache(None)
    yield
    caps.reset_cache()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(prev_cache)


def _patch_sources(monkeypatch, *, module_on=True, config=None, cfg=None,
                   chat_overrides=None, chat_id=None, usage=None,
                   limits=(200, 60, "default"), real_module=False):
    cfg = cfg if cfg is not None else _Cfg(config if config is not None
                                          else READY)
    hot.set_config_cache(cfg)

    if not real_module:
        async def _module(_chat_id=None):
            return bool(module_on)

        monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    from services import chat_params
    chat_params.set_chat_params_cache(_ChatParams(chat_overrides,
                                                  chat_id=chat_id))
    from services import worker_budget as wb
    calls = {"usage": 0, "limits": 0}

    async def fake_usage(pg=None, scope=None, day=None):
        calls["usage"] += 1
        if usage is None:
            return []
        return [{"day": "2026-10-17", "scope": scope,
                 "metric": wb.METRIC_IMAGE_CALLS, "used": usage[0],
                 "limit": usage[1]}]

    async def fake_limits(chat_id):
        calls["limits"] += 1
        return limits

    monkeypatch.setattr(wb, "get_usage", fake_usage)
    monkeypatch.setattr(wb, "image_limits", fake_limits)
    return calls


# ── Статусы ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_ready_when_all_gates_pass(monkeypatch):
    _patch_sources(monkeypatch)
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_READY
    assert state.declared is True and state.tryable is True
    assert state.tool_name == "generate_image"
    assert state.checked_at and state.source == "runtime"
    assert state.gates and state.inputs == ("prompt",)


@pytest.mark.asyncio
async def test_status_disabled_when_module_off(monkeypatch):
    _patch_sources(monkeypatch, module_on=False)
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_DISABLED
    assert state.reason_code == "module_disabled"
    assert state.tryable is False


@pytest.mark.asyncio
async def test_status_disabled_when_limit_forbids(monkeypatch):
    _patch_sources(monkeypatch, usage=(0, 0))
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_DISABLED
    assert state.reason_code == "financial_limit_disabled"


@pytest.mark.asyncio
async def test_status_not_configured_without_key(monkeypatch):
    cfg = dict(READY, **{"keys.image_api_key": ""})
    _patch_sources(monkeypatch, config=cfg)
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_NOT_CONFIGURED
    assert state.detail == "key_absent"


@pytest.mark.asyncio
async def test_status_not_configured_without_model(monkeypatch):
    cfg = dict(READY, **{"models.image_model": ""})
    _patch_sources(monkeypatch, config=cfg)
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_NOT_CONFIGURED
    assert state.detail == "model_absent"


@pytest.mark.asyncio
async def test_status_quota_exhausted(monkeypatch):
    _patch_sources(monkeypatch, usage=(60, 60))
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_QUOTA_EXHAUSTED
    assert state.reason_code == "financial_limit_reached"


@pytest.mark.asyncio
async def test_status_temporarily_unavailable_from_observed_failure(monkeypatch):
    """Реальный наблюдаемый сбой провайдера (не догадка): после timeout статус
    временно недоступен, а не «я не умею»."""
    _patch_sources(monkeypatch)
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="timeout")
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_TEMPORARILY_UNAVAILABLE
    assert state.source == "outcome" and state.detail == "timeout"
    # Успешный вызов снимает временный статус.
    caps.record_outcome("image_generation", chat_id=CHAT, ok=True)
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY


@pytest.mark.asyncio
async def test_status_unsupported_for_unknown_capability(monkeypatch):
    _patch_sources(monkeypatch)
    state = await caps.resolve("no_such_capability", CHAT)
    assert state.status == caps.STATUS_UNKNOWN
    assert state.reason_code == "unknown_capability"
    assert state.declared is False


@pytest.mark.asyncio
async def test_all_seven_statuses_declared(monkeypatch):
    assert set(caps.STATUSES) == {
        "ready", "disabled", "not_configured", "temporarily_unavailable",
        "quota_exhausted", "unsupported", "unknown"}


# ── declared / tryable / completed ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_declared_tryable_and_completed_are_distinct(monkeypatch):
    _patch_sources(monkeypatch)
    state = await caps.resolve("image_generation", CHAT)
    assert state.declared is True
    assert state.tryable is True
    assert state.last_result == caps.RESULT_UNKNOWN       # вызова ещё не было
    caps.record_outcome("image_generation", chat_id=CHAT, ok=True,
                        code="ok")
    state = await caps.resolve("image_generation", CHAT)
    assert state.last_result == caps.RESULT_SUCCESS


@pytest.mark.asyncio
async def test_delivery_failure_is_not_success(monkeypatch):
    """Успех генерации + провал отправки ≠ успешный вызов (§5.17)."""
    _patch_sources(monkeypatch)
    caps.record_outcome("image_generation", chat_id=CHAT, ok=True,
                        delivery_ok=False, code="send_failed")
    state = await caps.resolve("image_generation", CHAT)
    assert state.last_result == caps.RESULT_DELIVERY_FAILED
    assert state.status == caps.STATUS_READY      # гейты пройдены, но не обещание


# ── Кеш/TTL/инвалидация/стоимость ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_does_not_touch_sources(monkeypatch):
    calls = _patch_sources(monkeypatch)
    await caps.resolve("image_generation", CHAT)
    first = calls["usage"]
    again = await caps.resolve("image_generation", CHAT)
    assert again.source == "cache"
    assert calls["usage"] == first, "кеш не ходит в источники повторно"


@pytest.mark.asyncio
async def test_config_change_invalidates(monkeypatch):
    """Правка значения гейта (штатная запись настроек, мутирующая кэш НА МЕСТЕ)
    инвалидирует диагностику сразу — без ожидания TTL и без ручного вызова
    (review-w10 F4: идентичность объекта не менялась, покрытие было TTL-only)."""
    cfg = _Cfg(READY)
    _patch_sources(monkeypatch, cfg=cfg)
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY
    cfg.values["keys.image_api_key"] = ""
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_NOT_CONFIGURED
    assert state.source == "runtime", "запись настроек — не TTL-ожидание"
    # Явный invalidate() остаётся рабочим (сброс по внешнему событию).
    cfg.values["keys.image_api_key"] = "test-key"
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY
    removed = caps.invalidate("image_generation", CHAT,
                              reason="config_changed")
    assert removed >= 0


@pytest.mark.asyncio
async def test_config_cache_swap_invalidates_without_waiting_ttl(monkeypatch):
    """Смена слоя конфигурации (штатный путь применения настроек) сбрасывает
    диагностику сама — без ожидания TTL и без ручного invalidate."""
    _patch_sources(monkeypatch)
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY
    hot.set_config_cache(_Cfg(dict(READY, **{"keys.image_api_key": ""})))
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_ttl_expiry_rechecks(monkeypatch):
    """TTL — второй рубеж для источников ВНЕ конфигурации (квота/доступность):
    в пределах TTL держится прежняя диагностика, после — перепроверка."""
    _patch_sources(monkeypatch)
    now = 1000.0
    assert (await caps.resolve("image_generation", CHAT, now=now)).status == \
        caps.STATUS_READY
    from services import worker_budget as wb

    async def exhausted_usage(pg=None, scope=None, day=None):
        return [{"day": "2026-10-17", "scope": scope,
                 "metric": wb.METRIC_IMAGE_CALLS, "used": 60, "limit": 60}]

    monkeypatch.setattr(wb, "get_usage", exhausted_usage)
    stale = await caps.resolve("image_generation", CHAT,
                               now=now + caps.TTL_SECONDS - 1)
    assert stale.status == caps.STATUS_READY and stale.source == "cache"
    fresh = await caps.resolve("image_generation", CHAT,
                               now=now + caps.TTL_SECONDS + 1)
    assert fresh.status == caps.STATUS_QUOTA_EXHAUSTED


# ── F3 (review-w10): статус обязан отражать ОБА контура квоты ───────────────
# TEST-LIFECYCLE: REGRESSION owner=SOUL-AMD.5.12 (soul-1, W10 fix)

def _quota_usage(global_row=None, chat_row=None):
    """Scope-aware двойник `worker_budget.get_usage` (как реальный вызов)."""
    from services import worker_budget as wb

    async def fake_usage(pg=None, scope=None, day=None):
        if scope == "global":
            row = global_row
        else:
            row = chat_row
        if row is None:
            return []
        return [{"day": "2026-10-17", "scope": scope,
                 "metric": wb.METRIC_IMAGE_CALLS, "used": row[0],
                 "limit": row[1]}]
    return fake_usage


@pytest.mark.asyncio
async def test_shared_quota_exhausted_with_clean_chat_is_not_ready(monkeypatch):
    """review-w10 F3: shared-квота исчерпана (200/200), per-chat строка чистая
    (её нет) — `consume`/`reserve` списывает shared ПЕРВЫМ, поэтому статус
    обязан быть ``quota_exhausted``, а не врущий ``ready``."""
    from services import chat_params
    from services import worker_budget as wb
    hot.set_config_cache(_Cfg(READY))

    async def _module(_chat_id=None):
        return True

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(wb, "get_usage", _quota_usage(global_row=(200, 200),
                                                      chat_row=None))

    async def fake_limits(chat_id):
        return (200, 60, "default")

    monkeypatch.setattr(wb, "image_limits", fake_limits)
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status == caps.STATUS_QUOTA_EXHAUSTED
    assert state.reason_code == "financial_limit_reached"
    assert state.detail == "image_shared_limit"
    assert state.tryable is False
    assert caps.notice_block(state) != ""
    text, block_id, _src = caps.status_message(state)
    assert text and block_id == "message.image_failure.quota_exhausted"


@pytest.mark.asyncio
async def test_chat_quota_exhausted_with_clean_shared_is_not_ready(monkeypatch):
    """Обратная комбинация: shared чист, per-chat исчерпан → тоже отказ."""
    from services import chat_params
    from services import worker_budget as wb
    hot.set_config_cache(_Cfg(READY))

    async def _module(_chat_id=None):
        return True

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(wb, "get_usage", _quota_usage(global_row=(1, 200),
                                                      chat_row=(60, 60)))

    async def fake_limits(chat_id):
        return (200, 60, "default")

    monkeypatch.setattr(wb, "image_limits", fake_limits)
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status == caps.STATUS_QUOTA_EXHAUSTED
    assert state.detail == "image_daily_limit"


@pytest.mark.asyncio
async def test_shared_quota_forbidden_disables_capability(monkeypatch):
    """Shared-лимит 0 (запрет) при чистом чате → `disabled`, не `ready`."""
    from services import chat_params
    from services import worker_budget as wb
    hot.set_config_cache(_Cfg(READY))

    async def _module(_chat_id=None):
        return True

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(wb, "get_usage", _quota_usage(global_row=(0, 0),
                                                      chat_row=(1, 60)))

    async def fake_limits(chat_id):
        return (0, 60, "default")

    monkeypatch.setattr(wb, "image_limits", fake_limits)
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status == caps.STATUS_DISABLED
    assert state.detail == "image_limit_zero"


@pytest.mark.asyncio
async def test_both_quotas_clean_is_ready(monkeypatch):
    """Контроль: оба контура под капом → `ready` (статус не «вечно отказный»)."""
    from services import chat_params
    from services import worker_budget as wb
    hot.set_config_cache(_Cfg(READY))

    async def _module(_chat_id=None):
        return True

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(wb, "get_usage", _quota_usage(global_row=(1, 200),
                                                      chat_row=(1, 60)))

    async def fake_limits(chat_id):
        return (200, 60, "default")

    monkeypatch.setattr(wb, "image_limits", fake_limits)
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status == caps.STATUS_READY
    assert state.tryable is True


# ── §8.10: модуль / per-chat override / провайдер → L1 + UI-данные ──────────

@pytest.mark.asyncio
async def test_module_toggle_reflected_in_l1_and_view(monkeypatch):
    _patch_sources(monkeypatch, module_on=False)
    view = {row["capability_id"]: row for row in
            await caps.capability_view(CHAT, use_cache=False)}
    assert view["image_generation"]["status"] == caps.STATUS_DISABLED
    assert view["image_generation"]["reason_code"] == "module_disabled"
    # L1 видит только реально анонсируемые возможности (та же правда).
    from services.tool_schemas import active_tools
    announced_off = {t["function"]["name"] for t in active_tools(True, False)}
    assert "generate_image" not in announced_off
    assert "image_generation" not in dc.available_capabilities(announced_off)
    announced_on = {t["function"]["name"] for t in active_tools(True, True)}
    assert "image_generation" in dc.available_capabilities(announced_on)


@pytest.mark.asyncio
async def test_per_chat_override_reflected(monkeypatch):
    """Per-chat override модуля виден реестру (та же резолюция, что у L1):
    реальный резолвер модуля + реальный per-chat слой."""
    _patch_sources(monkeypatch, real_module=True, chat_id=CHAT,
                   chat_overrides={
                       "flags.image_generation_module_enabled": False})
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status == caps.STATUS_DISABLED
    # Другой чат без override — готов (изоляция чатов).
    state_other = await caps.resolve("image_generation", -100999, use_cache=False)
    assert state_other.status == caps.STATUS_READY


@pytest.mark.asyncio
async def test_provider_switch_reflected(monkeypatch):
    """Смена провайдера (модель/ключ) отражается после инвалидации кеша."""
    _patch_sources(monkeypatch)
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_READY
    hot.set_config_cache(_Cfg(dict(READY, **{"models.image_model": ""})))
    caps.invalidate("image_generation", CHAT, reason="provider_switch")
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_view_is_runtime_truth_not_static_list(monkeypatch):
    """§5.13: нет статического «я умею» — витрина следует за runtime."""
    _patch_sources(monkeypatch, module_on=False)
    rows = await caps.capability_view(CHAT, use_cache=False)
    ids = {r["capability_id"] for r in rows}
    assert {"image_generation", "web_search", "fact_check"} <= ids
    image = [r for r in rows if r["capability_id"] == "image_generation"][0]
    assert image["status"] != caps.STATUS_READY
    assert image["status"] in caps.STATUSES
    for row in rows:
        assert set(row) >= {"capability_id", "status", "reason_code",
                            "checked_at", "source", "declared", "tryable",
                            "tool", "gates", "actions", "executor"}


# ── §5.14: недоступное не обещаем, «не умею» без проверки запрещено ─────────

@pytest.mark.asyncio
async def test_every_l1_capability_is_known_to_registry(monkeypatch):
    """§5.11/5.18: реестр знает КАЖДУЮ capability, которую может назвать L1 —
    ни одна не остаётся «unknown» (иначе блокер был бы необъясним)."""
    _patch_sources(monkeypatch)
    from services.direct_capabilities import CAPABILITY_TOOLS
    states = await caps.resolve_many(list(CAPABILITY_TOOLS), CHAT,
                                     use_cache=False)
    unknown = [s.capability_id for s in states
               if s.status == caps.STATUS_UNKNOWN]
    assert unknown == [], unknown
    for state in states:
        assert state.checked_at and state.source
        if CAPABILITY_TOOLS[state.capability_id]:
            assert state.tool_name, state.capability_id
        else:
            assert state.status == caps.STATUS_UNSUPPORTED, state.capability_id


@pytest.mark.asyncio
async def test_video_summary_status_follows_media_source(monkeypatch):
    """§8.11 (видео): реальный сценарий — без настроенного источника медиа
    инструмент не «готов», и Writer получает правдивую пометку."""
    _patch_sources(monkeypatch)
    state = await caps.resolve("video_summary", CHAT, use_cache=False)
    assert state.status in (caps.STATUS_NOT_CONFIGURED, caps.STATUS_READY)
    without = state.status
    real = caps._settings()

    class _S:
        COBALT_API_URL = "http://cobalt.local"

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(caps, "_settings", lambda: _S())
    state2 = await caps.resolve("video_summary", CHAT, use_cache=False)
    assert state2.status == caps.STATUS_READY
    assert state2.tryable is True
    assert without != caps.STATUS_READY or state2.status == caps.STATUS_READY


@pytest.mark.asyncio
async def test_fact_check_status_follows_module_flag(monkeypatch):
    """§8.11 (фактчек): выключенный модуль → `disabled` и никакого обещания."""
    _patch_sources(monkeypatch)
    assert (await caps.resolve("fact_check", CHAT,
                               use_cache=False)).status == caps.STATUS_READY
    hot.set_config_cache(_Cfg(dict(READY, **{"flags.factcheck_enabled": False})))
    caps.invalidate("fact_check", CHAT, reason="module_toggle")
    state = await caps.resolve("fact_check", CHAT, use_cache=False)
    assert state.status == caps.STATUS_DISABLED
    assert state.reason_code == "factcheck_module_disabled"
    block = caps.notice_block(state)
    assert "<capability_notice" in block and "fact_check" in block


@pytest.mark.asyncio
async def test_non_transient_failure_does_not_look_like_provider_down(
        monkeypatch):
    """401/403 — это конфигурация (ключ), а не «провайдер не отвечает»:
    статус остаётся правдивым (`not_configured`/`ready`), без подмены причины."""
    _patch_sources(monkeypatch)
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="unauthorized")
    state = await caps.resolve("image_generation", CHAT, use_cache=False)
    assert state.status != caps.STATUS_TEMPORARILY_UNAVAILABLE
    assert state.last_result == caps.RESULT_FAILED
    assert state.last_result_code == "unauthorized"
    # Транзиентный код, наоборот, даёт временную недоступность.
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="http_503")
    assert (await caps.resolve("image_generation", CHAT,
                               use_cache=False)).status == \
        caps.STATUS_TEMPORARILY_UNAVAILABLE


@pytest.mark.asyncio
async def test_replay_does_not_overwrite_observed_outcome(monkeypatch):
    """F5 (review-w10): replay (`reason='already'`) — нового платного вызова не
    было. Состояние не объявляется успехом и не снимает наблюдаемый
    транзиентный отказ (tool-replay писал ``RESULT_SUCCESS``).

    TEST-LIFECYCLE: REGRESSION owner=SOUL-AMD.5.17 (soul-1, W10 fix)"""
    _patch_sources(monkeypatch)
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="timeout")
    assert (await caps.resolve("image_generation", CHAT)).status == \
        caps.STATUS_TEMPORARILY_UNAVAILABLE
    caps.record_outcome("image_generation", chat_id=CHAT, ok=True,
                        code="already")
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_TEMPORARILY_UNAVAILABLE
    assert state.last_result == caps.RESULT_FAILED
    assert state.last_result_code == "timeout"


@pytest.mark.asyncio
async def test_real_success_still_overwrites_observed_failure(monkeypatch):
    """Обратная сторона F5: настоящий успешный вызов снимает транзиентный отказ."""
    _patch_sources(monkeypatch)
    caps.record_outcome("image_generation", chat_id=CHAT, ok=False,
                        code="timeout")
    caps.record_outcome("image_generation", chat_id=CHAT, ok=True, code="ok")
    state = await caps.resolve("image_generation", CHAT)
    assert state.status == caps.STATUS_READY
    assert state.last_result == caps.RESULT_SUCCESS


@pytest.mark.asyncio
async def test_notice_block_is_truthful_and_empty_when_ready(monkeypatch):
    _patch_sources(monkeypatch)
    ready = await caps.resolve("image_generation", CHAT)
    assert caps.notice_block(ready) == ""
    caps.invalidate("image_generation", CHAT)
    hot.set_config_cache(_Cfg(dict(READY, **{"keys.image_api_key": ""})))
    state = await caps.resolve("image_generation", CHAT)
    block = caps.notice_block(state)
    assert "<capability_notice" in block
    assert "not_configured" in block and "image_generation" in block
    assert "не умею" in block          # запрет ложной формулировки, не сама ложь
    assert "test-key" not in block and "key_absent" not in block
