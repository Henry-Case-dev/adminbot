"""SOUL-1 / W7 (SOUL-13.4) — embedding primary-слот: hot-конфиг vs env vs
отсутствие, деградация пула и недеструктивный WARN.

Клауза источника (§14, строка 187): «при отсутствии `EMBEDDING_API_KEY`
primary различать отсутствующий/доступный через hot-config и деградацию
пула; добавить недеструктивный WARN и понятное состояние; действительные
секреты не писать».

Контракт:
  * primary-слот берётся hot → env (как в горячем пути); источник виден
    (`pool_rotation_diagnosis()["primary_source"]` / панель `rotation.
    primary_state` = primary_from_hot | primary_from_env | primary_absent |
    empty_pool);
  * primary отсутствует при живых fallback-ключах → `degraded=True`,
    `primary_warn=True`, hint с конкретной настройкой; WARN ≤1/10 мин;
  * `degenerate` (D3/ASAP8-F8) НЕ переопределяется — контракт цел;
  * значения ключей не попадают ни в панель, ни в WARN (R17).

TEST-LIFECYCLE: CONTRACT owner=SOUL-13.4; REGRESSION owner=SOUL-13.4
(до фикса пустой primary-слот при 2 fallback-ключах давал degenerate=False
и проходил вообще без диагностики — см. `plans/backlog.md` v6.3 Wave 4, п.2).
"""
import json
import logging

import pytest

from services import embedding_control_plane as ecp
from services.embedding_control_plane import (
    build_credential_pool, pool_rotation_diagnosis, provider_panel,
)

pytestmark = pytest.mark.asap4


@pytest.fixture(autouse=True)
def fresh_warn_state(monkeypatch):
    """Изоляция in-memory rate-limit'ов WARN + singleton'ов контрол-плейна."""
    monkeypatch.setattr(ecp, "_last_rotation_warn", 0.0, raising=False)
    monkeypatch.setattr(ecp, "_last_primary_warn", 0.0, raising=False)
    yield ecp


def _hot_only(monkeypatch, values):
    """hot-слой изолированно: values — только то, что реально задано; любой
    другой ключ отсутствует (как в проде без записи в PG). settings-слой для
    EMBEDDING_* гасится в ''."""
    def _fake_hot(key, default=None):
        return values.get(key, default)

    def _fake_setting(name, default):
        if str(name).startswith("EMBEDDING_"):
            return ""
        return default

    monkeypatch.setattr(ecp, "_hot_get", _fake_hot)
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)


def _keys(pool):
    return {c.alias: c.key_source for c in pool}


def test_primary_from_hot_is_distinguished(monkeypatch):
    _hot_only(monkeypatch, {"keys.embedding_api_key": "SENTINEL-PRIMARY",
                            "keys.embedding_fallback_api_key": "SENTINEL-FB1",
                            "keys.embedding_fallback_api_key_2": "SENTINEL-FB2"})
    pool = build_credential_pool()
    assert _keys(pool) == {"primary": "hot", "fallback_1": "hot",
                           "fallback_2": "hot"}, _keys(pool)
    diag = pool_rotation_diagnosis(pool)
    assert diag["primary_present"] is True
    assert diag["primary_source"] == "hot"
    assert diag["degenerate"] is False
    assert diag["degraded"] is False
    rot = provider_panel()["rotation"]
    assert rot["primary_state"] == "primary_from_hot"
    assert rot["primary_warn"] is False and rot["primary_hint"] == ""
    # N2 (TEST-LIFECYCLE: REGRESSION owner=W7/N2): hot перекрывает env и при
    # НЕПУСТОМ env — оба слоя заданы, источник primary остаётся 'hot'.
    monkeypatch.setattr(
        ecp, "_settings_value",
        lambda name, default: "SENTINEL-ENV-KEY" if name == "EMBEDDING_API_KEY"
        else ("" if str(name).startswith("EMBEDDING_") else default))
    both_layers = build_credential_pool()
    assert _keys(both_layers)["primary"] == "hot", _keys(both_layers)


def test_primary_from_env_when_hot_is_silent(monkeypatch):
    def _fake_hot(key, default=None):
        return {"keys.embedding_fallback_api_key": "SENTINEL-FB1",
                "keys.embedding_fallback_api_key_2": "SENTINEL-FB2"}.get(
                    key, default)           # primary в hot-конфиге отсутствует

    def _fake_setting(name, default):
        return {"EMBEDDING_API_KEY": "SENTINEL-ENV"}.get(name, "") \
            if str(name).startswith("EMBEDDING_") else default

    monkeypatch.setattr(ecp, "_hot_get", _fake_hot)
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)
    pool = build_credential_pool()
    assert _keys(pool) == {"primary": "env", "fallback_1": "hot",
                           "fallback_2": "hot"}, _keys(pool)
    rot = provider_panel()["rotation"]
    assert rot["primary_present"] is True
    assert rot["primary_source"] == "env"
    assert rot["primary_state"] == "primary_from_env"
    assert rot["primary_warn"] is False
    assert rot["degraded"] is False


def test_missing_primary_is_reported_and_warned(monkeypatch, caplog):
    """REGRESSION: пустой primary при 2 fallback-ключах раньше = тишина."""
    _hot_only(monkeypatch, {"keys.embedding_fallback_api_key": "SENTINEL-FB1",
                            "keys.embedding_fallback_api_key_2": "SENTINEL-FB2"})
    pool = build_credential_pool()
    assert _keys(pool) == {"fallback_1": "hot", "fallback_2": "hot"}
    diag = pool_rotation_diagnosis(pool)
    assert diag["primary_present"] is False
    assert diag["primary_source"] == "absent"
    assert diag["degraded"] is True
    # D3-контракт не переопределён: fallback-слоты дают две известные группы.
    assert diag["degenerate"] is False

    with caplog.at_level(logging.WARNING, logger="services.embedding_control_plane"):
        rot = provider_panel()["rotation"]
    assert rot["primary_warn"] is True
    assert rot["primary_state"] == "primary_absent"
    assert rot["primary_hint"] and "EMBEDDING_API_KEY" in rot["primary_hint"]
    assert rot["primary_hint"] and "keys.embedding_api_key" in rot["primary_hint"]
    warns = [r for r in caplog.records if "primary=absent" in r.getMessage()]
    assert len(warns) == 1, [r.getMessage() for r in caplog.records]
    # rate-limit: повторный вызов панели WARN не дублирует
    with caplog.at_level(logging.WARNING, logger="services.embedding_control_plane"):
        caplog.clear()
        provider_panel()
    assert not [r for r in caplog.records if "primary=absent" in r.getMessage()]
    # ...и снова WARN после сброса окна (не «одноразовый навсегда»)
    ecp._last_primary_warn = 0.0
    assert ecp._maybe_warn_missing_primary(diag) is True


def test_warn_is_hedged_by_master_flag(monkeypatch):
    _hot_only(monkeypatch, {"keys.embedding_fallback_api_key": "SENTINEL-FB1"})
    diag = pool_rotation_diagnosis(build_credential_pool())
    monkeypatch.setattr(ecp, "control_plane_enabled", lambda: False)
    assert ecp._maybe_warn_missing_primary(diag) is False


def test_empty_pool_is_not_a_primary_defect(monkeypatch):
    _hot_only(monkeypatch, {})
    diag = pool_rotation_diagnosis(build_credential_pool())
    assert diag["keys"] == 0
    assert diag["degraded"] is True          # пул не настроен вовсе
    rot = provider_panel()["rotation"]
    assert rot["primary_state"] == "empty_pool"
    assert rot["primary_warn"] is False      # это не дефект слота
    assert ecp._maybe_warn_missing_primary(diag) is False


def test_no_key_values_leak_into_panel_or_diagnosis(monkeypatch):
    sentinels = ["LEAK-PRIMARY-42", "LEAK-FB1-42", "LEAK-FB2-42"]
    _hot_only(monkeypatch, {"keys.embedding_api_key": sentinels[0],
                            "keys.embedding_fallback_api_key": sentinels[1],
                            "keys.embedding_fallback_api_key_2": sentinels[2]})
    pool = build_credential_pool()
    blob = json.dumps(provider_panel(), ensure_ascii=False)
    blob += json.dumps(pool_rotation_diagnosis(pool), ensure_ascii=False)
    for s in sentinels:
        assert s not in blob, "значение ключа утекло в панель/диагноз (R17)"
    rows = {r["alias"]: r for r in provider_panel()["credential_rows"]}
    assert rows["primary"]["key_source"] == "hot"
    assert set(rows) == {"primary", "fallback_1", "fallback_2"}


def test_single_known_group_still_degenerate(monkeypatch):
    """D3-контракт (ASAP8-F8 E3): явная одна группа остаётся degenerate."""
    _hot_only(monkeypatch, {"keys.embedding_fallback_api_key": "SENTINEL-FB1",
                            "keys.embedding_quota_group_labels": "fallback_1:g1"})
    diag = pool_rotation_diagnosis(build_credential_pool())
    assert diag["degenerate"] is True
    rot = provider_panel()["rotation"]
    assert rot["status"] == "none" and rot["warn"] is True
