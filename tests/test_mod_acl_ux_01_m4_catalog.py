"""MOD-ACL-UX-01 M4A (wave 1) — контракт каталога модулей из DTO.

Предмет (design §2.1/§3.2/§6.2, brief wave-1 §2.1/§4):
  * 21 видимый `ModuleSpec` + 1 hidden; `registry_for_frontend()` отдаёт ровно
    21 без дублей и в порядке `catalog_order`;
  * группы каталога 5/5/3/5/3 (`communication/memory/autonomy/media/system`);
  * `settings_groups` 11 НОВЫХ static-модулей — ровно `tab_group_ids()` их
    config-вкладки (группы/вкладки не изобретены);
  * `runtime_gate`: 8 исправленных спецификаций == `per_chat`, embeddings —
    `global`, time — `per_chat` (policy без мастера);
  * `permissions{can_read,can_edit}` — ЕДИНСТВЕННОЕ место прав; `gate`/`state`
    их не несут, `usage_state` отсутствует;
  * `scope_capability`/`gate_feature`/`history_source` — только допустимые
    значения; `validate_spec`/`validate_registry` без ошибок;
  * живой `GET /api/config` (chat и global): у каждой карточки `state` с
    осями и `checked_at`; `dream`/`nostalgia` резолвятся через
    `feature_gates.gate_state`; chat-use «Векторной памяти» — через
    `flags.memory_search_enabled`; на global `ready/observed = None`
    (честное «не проверялось»), сырых секретов в DTO нет.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/M4A (wave 1)
"""
import json

import pytest

from services import module_registry as mr

# Фикстура живого клиента — та же, что у M4 «Векторной памяти» (fake PG,
# реальные маршруты): второй тестовый стенд не создаётся.
from tests.test_mod_acl_ux_01_m4_module_params import (  # noqa: F401
    ADMIN_ID,
    USER_ID,
    client,
    _hdr,
)

NEW_STATIC = {
    "summary": "mod_summary",
    "direct": "mod_direct",
    "search": "mod_search",
    "web": "mod_web",
    "transcribe": "mod_transcribe",
    "video_summary": "mod_video_summary",
    "media_download": "mod_media_download",
    "images": "mod_images",
    "checkup": "mod_checkup",
    "budgets": "mod_budgets",
}
GATE_FEATURES = {"sleep": "dream", "nostalgia": "nostalgia"}
AXES = ("desired", "effective_runtime", "ready", "observed", "source",
        "chat_state", "checked_at")


def _visible():
    return [s for s in mr.MODULE_REGISTRY.values() if s.visibility != "hidden"]


def _dto():
    return mr.registry_for_frontend()


def _card(dto, mid):
    return next((row for row in dto if row["id"] == mid), None)


def test_21_visible_plus_one_hidden_no_duplicates():
    assert len(_visible()) == 21, "ровно 21 видимая карточка"
    hidden = [s for s in mr.MODULE_REGISTRY.values()
              if s.visibility == "hidden"]
    assert [s.id for s in hidden] == ["factcheck_temporal"], (
        "hidden-подмодуль ровно один — factcheck_temporal")
    dto = _dto()
    ids = [row["id"] for row in dto]
    assert len(ids) == 21 and len(set(ids)) == 21, "DTO: 21 уникальный id"
    assert "factcheck_temporal" not in ids, "hidden не отдаётся карточкой"


def test_catalog_order_is_permutation_and_groups_5_5_3_5_3():
    dto = _dto()
    orders = [row["catalog_order"] for row in dto]
    assert orders == list(range(1, 22)), (
        "DTO отсортирован по catalog_order 1…21 (DOM == порядок)")
    assert [row["catalog_order"] for row in dto] == sorted(orders)
    dist = {}
    for row in dto:
        dist[row["catalog_group"]] = dist.get(row["catalog_group"], 0) + 1
    assert dist == {"communication": 5, "memory": 5, "autonomy": 3,
                    "media": 5, "system": 3}, dist
    # Нормативный порядок §3.2: первые/последние карточки.
    assert [row["id"] for row in dto[:5]] == [
        "summary", "direct", "factcheck", "search", "web"]
    assert [row["id"] for row in dto[-3:]] == ["checkup", "budgets", "time"]


def test_settings_groups_of_11_new_match_tab_rules():
    from services import param_catalog as pc
    for mid, tab in NEW_STATIC.items():
        spec = mr.MODULE_REGISTRY[mid]
        expected = pc.tab_group_ids(tab)
        assert set(spec.settings_groups) == set(expected), (
            f"{mid}: settings_groups != tab_group_ids({tab}): "
            f"{sorted(set(expected) - set(spec.settings_groups))} / "
            f"{sorted(set(spec.settings_groups) - set(expected))}")
    # «Время» — policy-экран без config-вкладки: групп нет, ось — параметр.
    time_spec = mr.MODULE_REGISTRY["time"]
    assert time_spec.settings_groups == ()
    assert time_spec.scope_capability == "limits.chat_timezone"


def test_runtime_gate_table():
    per_chat = [s.id for s in _visible() if s.runtime_gate == "per_chat"]
    # 19 карточек читают чат, 2 особые: embeddings — global, time — policy
    # per_chat без мастера → остальные 18 + time.
    assert "embeddings" not in per_chat
    assert mr.MODULE_REGISTRY["embeddings"].runtime_gate == "global"
    for mid in ("initiative", "stories", "character", "random", "factcheck",
                "vision", "nostalgia", "sleep", "summary", "direct", "search",
                "web", "transcribe", "video_summary", "media_download",
                "images", "checkup", "budgets", "time"):
        assert mr.MODULE_REGISTRY[mid].runtime_gate == "per_chat", mid
    assert mr.MODULE_REGISTRY["factcheck_temporal"].runtime_gate == "global"
    assert len(per_chat) == 20, (
        "20 карточек читают чат (19 продуктовых + «Время»; у «Времени» "
        "нет тумблера — control=none)")


def test_capability_fields_only_allowed_values():
    from services.feature_gates import ALL_GATED_FEATURES
    for spec in mr.MODULE_REGISTRY.values():
        if spec.scope_capability:
            from services import param_catalog as pc
            cap = pc.get_by_pg_key(spec.scope_capability)
            assert cap is not None and cap.per_chat, spec.scope_capability
        if spec.gate_feature:
            assert spec.gate_feature in ALL_GATED_FEATURES, spec.gate_feature
        if spec.history_source:
            assert spec.history_source in mr.HISTORY_SOURCES
    assert mr.MODULE_REGISTRY["sleep"].gate_feature == "dream"
    assert mr.MODULE_REGISTRY["nostalgia"].gate_feature == "nostalgia"
    assert mr.MODULE_REGISTRY["character"].visibility == "visible", (
        "M4A: «Характер» — видимая карточка (design §2.1)")


def test_validate_spec_and_registry_clean():
    assert mr.validate_registry() == [], "реестр обязан быть консистентным"
    for spec in mr.MODULE_REGISTRY.values():
        assert mr.validate_spec(spec) == [], spec.id


def test_permissions_single_source_no_usage_state():
    state = {
        "capability": "sleep", "key": "memory.dream_enabled",
        "domain": "gate", "chat_id": -100, "chat_state": "on",
        "desired": True, "source": "chat", "global_value": False,
        "global_source": "default", "emergency_block": False,
        "effective_runtime": True, "ready": None, "authorized": None,
        "observed": None, "observed_at": None, "last_activity_at": None,
        "reason_code": None, "pending_restart": False, "version": None,
        "can_read": True, "can_edit": False, "consent": None,
        "conflict": None, "checked_at": "2026-11-17T00:00:00+00:00",
    }
    dto = mr.registry_for_frontend({"sleep": state})
    card = _card(dto, "sleep")
    assert card["permissions"] == {"can_read": True, "can_edit": False}
    assert "can_read" not in card["gate"] and "can_edit" not in card["gate"]
    assert "can_read" not in card["state"] and "can_edit" not in card["state"]
    blob = json.dumps(dto, ensure_ascii=False)
    assert "usage_state" not in blob, "второго имени осей нет"
    # DTO не содержит сырых секретов: только реестровые метаданные.
    assert "sk-" not in blob and "password" not in blob.lower()


def test_api_chat_scope_has_axes_and_gate_paths(client, monkeypatch):
    from services import feature_gates as fg

    called = []
    original = fg.gate_state

    async def spy(chat_id, feature, *args, **kwargs):
        called.append(feature)
        return await original(chat_id, feature, *args, **kwargs)

    monkeypatch.setattr(fg, "gate_state", spy)
    resp = client.get("/api/config",
                      headers={**_hdr(ADMIN_ID), "X-Chat-Id": "-100"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mods = body["modules"]
    assert len(mods) == 21
    assert body["chat_id"] == -100
    for card in mods:
        state = card.get("state")
        assert isinstance(state, dict), card["id"]
        for axis in AXES:
            assert axis in state, (card["id"], axis)
        assert set(card["permissions"]) == {"can_read", "can_edit"}
    # Gate-домен резолвится ТОЛЬКО через feature_gates.gate_state.
    assert "dream" in called and "nostalgia" in called, called
    sleep = _card(mods, "sleep")
    assert sleep["gate_feature"] == "dream"
    assert sleep["state"]["chat_state"] in ("inherit", "on", "off")
    assert sleep["gate"]["source"] in ("emergency_env", "product_toggle",
                                       "both")
    # «Векторная память»: chat-use — flags.memory_search_enabled.
    emb = _card(mods, "embeddings")
    assert emb["scope_capability"] == "flags.memory_search_enabled"
    assert emb["master_param"] == "", "у infra нет master-оси"
    assert emb["state"]["desired"] is True       # канон/дефолт ON
    assert emb["state"]["source"] == "default"
    assert emb["runtime_gate"] == "global"


def test_api_global_scope_is_honest(client):
    resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200, resp.text
    mods = resp.json()["modules"]
    assert len(mods) == 21
    for card in mods:
        state = card["state"]
        assert state["ready"] is None, card["id"]
        assert state["observed"] is None, card["id"]
        assert state["checked_at"], card["id"]
        assert state["source"] in (None, "global", "default"), card["id"]
    time_card = _card(mods, "time")
    assert time_card["state"]["desired"] is None, (
        "у «Времени» нет мастер-оси: desired=null, не «выключено»")
    emb = _card(mods, "embeddings")
    assert emb["state"]["desired"] is None, (
        "chat-use не выдаётся за глобальный master")
    # global-путь отдаёт permissions теми же guard'ами.
    for card in mods:
        assert isinstance(card["permissions"]["can_edit"], bool)
        assert isinstance(card["permissions"]["can_read"], bool)


def test_api_user_paths_unchanged(client):
    # Чужой чат → 403 (существующий guard доступа не изменён M4A).
    resp = client.get("/api/config",
                      headers={**_hdr(USER_ID), "X-Chat-Id": "-100"})
    assert resp.status_code == 403, resp.text
    # Обычный пользователь на глобальном пути получает DTO без секретов,
    # но не может редактировать master-оси.
    resp = client.get("/api/config", headers=_hdr(USER_ID))
    assert resp.status_code == 200, resp.text
    mods = resp.json()["modules"]
    assert len(mods) == 21
    assert all(card["permissions"]["can_edit"] is False for card in mods)
