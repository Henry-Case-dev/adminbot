# -*- coding: utf-8 -*-
"""SOUL-14.1 — бэкенд-контракт блока `layers` в `/api/speech/overview`.

Диаграмма «Как рождается ответ» (web/index.html `[data-speech-layers]`)
читает отсюда статусы L1 и SelfModel. Контракт:

  * только реальные оси (`services.direct_l1`, `services.mca_gates`,
    снапшот SelfModel); R17 — числа/коды, без raw-текста;
  * сбой чтения — fail-open: ответ остаётся 200, слой честно `None`
    («—» в UI), витрина не ломается;
  * ключ `layers` аддитивен: sections/gates/registry на месте.

Запуск: `.venv/Scripts/python.exe -m pytest tests/test_soul14_layers_payload.py -q`

TEST-LIFECYCLE: CONTRACT owner=SOUL-14.1 (§15 ТЗ: честные статусы слоёв
для диаграммы; данные не выдумываются).
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from services.database import DatabaseService
from web.api import speech as S


class _Cache:
    """Мини-ConfigCache: enough для get_overview (чтения речевых доков)."""

    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, category=None):
        self.data[key] = value


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "soul14.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


@pytest.fixture
def overview_env(monkeypatch, db):
    """Реальный вызов get_overview: доступ разрешён, БД подключена."""
    from services import lore_runtime

    cache = _Cache()
    lore_runtime.set_lore_components(db=db)
    user = type("U", (), {"id": 5150})()
    ctx = type("C", (), {"is_global_admin": True,
                         "effective_permissions": None})()

    async def access(request, _user, x_chat_id):
        return cache, (int(x_chat_id) if x_chat_id else None), ctx

    monkeypatch.setattr(S, "_access", access)
    yield {"cache": cache, "user": user}
    lore_runtime.reset_lore_runtime()


# ═══ честные оси: реальные флаги попадают в payload ═════════════════════════

@pytest.mark.asyncio
async def test_layers_payload_reads_real_axes(monkeypatch):
    from services import direct_l1, mca_gates

    monkeypatch.setattr(direct_l1, "direct_l1_enabled", lambda: True)
    monkeypatch.setattr(direct_l1, "l1_fallback_enabled", lambda: False)
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: False)

    out = await S._layers_payload(None)
    assert out["l1"] == {"available": True, "enabled": True,
                         "fallback": False}
    # SelfModel выключен гейтом: применённых правил НЕ выдумываем.
    sm = out["self_model"]
    assert sm["available"] is True
    assert sm["enabled"] is False
    assert sm["applied"] is None and sm["rejected"] is None
    assert sm["stale"] is None and sm["fallback"] is None


@pytest.mark.asyncio
async def test_layers_self_model_counts_from_snapshot(monkeypatch):
    """Включённый SelfModel: числа — из реального снапшота (select_behavior)."""
    from services import direct_l1, mca_gates
    from services import mca_self_model as msm

    monkeypatch.setattr(direct_l1, "direct_l1_enabled", lambda: True)
    monkeypatch.setattr(direct_l1, "l1_fallback_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: True)
    snap = SimpleNamespace(stale=True, fallback=False)
    frame = SimpleNamespace(
        applied_rules=[SimpleNamespace(), SimpleNamespace()],
        rejected_rules=[SimpleNamespace()])
    async def _resolve(_db, _chat):
        return snap
    monkeypatch.setattr(msm, "resolve_self_model", _resolve)
    monkeypatch.setattr(msm, "select_behavior", lambda _snap: frame)
    # БД доступна (стаб): только тогда слой читает снапшот.
    import services.lore_runtime as lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())

    out = await S._layers_payload(None)
    sm = out["self_model"]
    assert sm["enabled"] is True
    assert sm["applied"] == 2 and sm["rejected"] == 1
    assert sm["stale"] is True and sm["fallback"] is False


# ═══ fail-open: сбой оси — честный «—», ответ не падает ═════════════════════

@pytest.mark.asyncio
async def test_layers_fail_open_on_axis_errors(monkeypatch):
    from services import direct_l1, mca_gates

    def _boom():
        raise RuntimeError("axis read failed")

    monkeypatch.setattr(direct_l1, "direct_l1_enabled", _boom)
    monkeypatch.setattr(mca_gates, "self_model_enabled", _boom)
    out = await S._layers_payload(None)
    assert out["l1"] == {"available": False, "enabled": None,
                         "fallback": None}
    sm = out["self_model"]
    assert sm["available"] is True
    assert sm["enabled"] is None and sm["applied"] is None


@pytest.mark.asyncio
async def test_layers_self_model_resolve_failure_keeps_gate(monkeypatch):
    """Снапшот упал, гейт прочитался: enabled — реальный, числа — «—»."""
    from services import direct_l1, mca_gates

    monkeypatch.setattr(direct_l1, "direct_l1_enabled", lambda: True)
    monkeypatch.setattr(direct_l1, "l1_fallback_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: True)

    import services.mca_self_model as msm
    def _boom(*_a, **_k):
        raise RuntimeError("snapshot failed")
    monkeypatch.setattr(msm, "resolve_self_model", _boom)
    out = await S._layers_payload(None)
    sm = out["self_model"]
    assert sm["available"] is True
    assert sm["enabled"] is True
    assert sm["applied"] is None and sm["stale"] is None


# ═══ аддитивность overview: layers не ломает витрину ════════════════════════

@pytest.mark.asyncio
async def test_overview_includes_layers_and_keeps_sections(overview_env,
                                                           monkeypatch):
    from services import direct_l1, mca_gates

    monkeypatch.setattr(direct_l1, "direct_l1_enabled", lambda: True)
    monkeypatch.setattr(direct_l1, "l1_fallback_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: False)
    env = overview_env
    overview = await S.get_overview(None, env["user"], None)
    # Аддитивный блок присутствует и честен.
    layers = overview["layers"]
    assert layers["l1"]["available"] is True
    assert layers["l1"]["enabled"] is True
    assert layers["self_model"]["enabled"] is False
    assert layers["self_model"]["applied"] is None
    # Витрина не пострадала: прежние ключи и состав разделов на месте.
    assert overview["gates"]["character_core_enabled"] is False or True
    ids = {row["id"] for row in overview["sections"]}
    assert {"core", "style", "expression", "humor", "examples",
            "try", "learning"} <= ids
    assert {row["id"] for row in overview["advanced"]} == {
        "all", "inspector", "capabilities"}


@pytest.mark.asyncio
async def test_overview_layers_fail_open_stays_200(overview_env, monkeypatch):
    """Полный сбой осей: overview остаётся 200, слои — честные «—»."""
    from services import mca_gates

    def _boom():
        raise RuntimeError("gates read failed")
    monkeypatch.setattr(mca_gates, "self_model_enabled", _boom)
    monkeypatch.setattr(
        "services.direct_l1.direct_l1_enabled", _boom)
    env = overview_env
    overview = await S.get_overview(None, env["user"], None)
    assert overview["layers"]["l1"]["enabled"] is None
    assert overview["layers"]["self_model"]["applied"] is None
    assert isinstance(overview["sections"], list)


if __name__ == "__main__":
    asyncio.run(pytest.main([__file__, "-q"]))
