"""SOUL-1 / CORE-DOC — Core в реальном Direct-пути (композер ON) и его видимость.

Доказывается (SOUL-AMD.1.1/1.3, SOUL-02.1–02.8, SOUL-AMD.6.4):

  * при ``UNIFIED_COMPOSER_ENABLED`` ON Core реально доезжает до system
    РЕАЛЬНОГО Direct-метода (``DirectChatService._l2_write_answer``) — и
    заводская редакция действует, даже если владелец ещё не сохранял документ;
  * слой ``core`` стоит между ``channel_contract`` и ``identity`` (один рендер
    характера), выбор редакции (полная/компактная) и его причина видны в
    манифесте/Inspector (``detail``, ``versions["core_detail"]``);
  * правка Core через API реестра меняет СЛЕДУЮЩУЮ генерацию;
  * при OFF-флаге (прод-дефолт) Core не рендерится и манифест не пишется;
  * Core не добавляет LLM-вызовов и не утекает текстом в события/манифест.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.1.1 / SOUL-02.7–02.8 (soul-1, CORE-DOC)
"""
from __future__ import annotations

import json
import os

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import response_extent as _extent

BASE = "КАНАЛ-КАНОН: читай контекст и отвечай по делу."
CHARACTER_BLOCK = ("<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n"
                   "</Persona>")
PLAN = _extent.ResponsePlan(task_kind="explanation", extent="detailed",
                            structure="answer", delivery_hint="plain",
                            tool_policy="none", source="l1")
OWNER_CORE = "ЯДРО ВЛАДЕЛЬЦА: наблюдательный, язвительный, абсурдный."


class StubLLM:
    def __init__(self):
        self.captured: list[dict] = []
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
        return "ЗАГЛУШКА ОТВЕТА"


class StubMemory:
    async def get_window_messages(self, chat_id):
        return [{"speaker": "Аня", "text": "ну и что там с сервером",
                 "created_at": "2026-10-16T10:00:00+00:00"}]


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list[tuple] = []

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def set_chat_params(self, chat_id, patch, **kwargs):
        self.overrides[int(chat_id)] = dict(patch.get("overrides") or {})


def build_service():
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _compose_speech_system = D._compose_speech_system

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999

    return Stub, D


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pr.reset_cache()
    monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    monkeypatch.delenv("COMPOSER_LAYER_BUDGET_TOKENS", raising=False)
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    yield
    pr.reset_cache()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


def composer_on(monkeypatch, *, core_doc=None, hot_values=None) -> dict:
    """ON = env AND каталоговый тумблер (единственный легальный путь)."""
    values = {"flags.unified_composer_enabled": True,
              "flags.character_core_enabled": True}
    values.update(hot_values or {})
    if core_doc is not None:
        values[pr.CORE_DOC_KEY] = core_doc
    cache = FakeHot(values)
    chats = FakeChatCache({})
    hot.set_config_cache(cache)
    chat_params.set_chat_params_cache(chats)
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    pc.reset_state()
    return {"cache": cache, "chats": chats}


async def _l2_system(stub_cls, D, chat_id: int = 12345,
                     run_id: str = "run-core"):
    """System реального L2-пути + манифест (тот же метод, что в проде)."""
    llm = StubLLM()
    await D._l2_write_answer(
        stub_cls(llm), chat_id, "почему упал сервис", temperature=0.7,
        character_block=CHARACTER_BLOCK, response_plan=PLAN,
        plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=["<Context>окно</Context>"], correlation_id=run_id)
    cap = llm.captured[-1]["messages"]
    manifest = pc.get_manifest(chat_id, run_id=run_id, writer="l2_writer")
    return cap[0]["content"], cap[1]["content"], manifest, llm


def core_layer(manifest):
    return [t for t in manifest.layers if t.layer == "core"][0]


# ═══ ON: заводская редакция доезжает до речи ════════════════════════════════

@pytest.mark.asyncio
async def test_factory_core_reaches_real_l2_system_when_on(monkeypatch):
    from services import prompt_style_blocks as psb
    from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT as CANON

    Stub, D = build_service()
    composer_on(monkeypatch)
    system, user, manifest, _llm = await _l2_system(Stub, D)
    factory_compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    canon = psb.resolve_prompt("prompts.direct_chat_verbalizer_system_prompt",
                               CANON)
    assert factory_compact in system, "заводской Core не доехал до system"
    assert system.count(factory_compact) == 1, "Core отрендерен дважды"
    assert factory_compact not in user
    assert system.index(canon) < system.index(factory_compact)
    assert system.index(factory_compact) < system.index(CHARACTER_BLOCK)
    layer = core_layer(manifest)
    assert layer.rendered is True
    assert layer.detail.startswith("level=compact reason=factory_default")
    assert manifest.versions["core_detail"] == "compact:factory_default"
    assert manifest.versions["core"].startswith(pr.FACTORY_PREFIX)
    rendered = pc.render_effective_layers(manifest)
    assert rendered["rendered_layers"][:3] == ["channel_contract", "core",
                                              "identity"]
    assert rendered["layers"][1]["detail"] == layer.detail


@pytest.mark.asyncio
async def test_off_path_renders_no_core_and_writes_no_manifest():
    Stub, D = build_service()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    system, _user, manifest, llm = await _l2_system(Stub, D)
    assert pr.factory_text(pr.CORE_COMPACT_BLOCK_ID) not in system
    assert pr.factory_text(pr.CORE_FULL_BLOCK_ID) not in system
    assert manifest is None, "OFF-путь не должен писать манифест"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_owner_core_edit_changes_next_generation(monkeypatch):
    Stub, D = build_service()
    env = composer_on(monkeypatch)
    await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, OWNER_CORE,
                                cache=env["cache"], actor="owner")
    system, _user, manifest, _llm = await _l2_system(Stub, D)
    assert OWNER_CORE in system
    assert pr.factory_text(pr.CORE_COMPACT_BLOCK_ID) not in system
    assert core_layer(manifest).detail.startswith("level=full reason=owner_setting")
    assert manifest.versions["core_detail"] == "full:owner_setting"
    # Следующая правка — компактной редакции — снова меняет сборку.
    await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, "КОМПАКТ ВЛАДЕЛЬЦА.",
                                cache=env["cache"], actor="owner")
    system_2, _u, manifest_2, _llm = await _l2_system(Stub, D, run_id="run-2")
    assert "КОМПАКТ ВЛАДЕЛЬЦА." in system_2 and OWNER_CORE not in system_2
    assert manifest_2.manifest_id != manifest.manifest_id
    assert manifest_2.versions["core"] != manifest.versions["core"]


@pytest.mark.asyncio
async def test_full_requested_is_downgraded_by_budget_with_visible_reason(
        monkeypatch):
    Stub, D = build_service()
    composer_on(monkeypatch, core_doc={"revision": 5, "enabled": True,
                          "full_text": OWNER_CORE, "detail_level": "full"})
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "3")
    _system, _user, manifest, _llm = await _l2_system(Stub, D)
    assert OWNER_CORE not in _system
    assert core_layer(manifest).detail.startswith(
        "level=compact reason=context_budget")
    assert manifest.versions["core_detail"] == "compact:context_budget"
    # Бюджета хватает — действует выбранная владельцем полная редакция.
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "100000")
    system_full, _u, manifest_full, _llm = await _l2_system(Stub, D, run_id="r2")
    assert OWNER_CORE in system_full
    assert manifest_full.versions["core_detail"] == "full:owner_setting"


@pytest.mark.asyncio
async def test_chat_override_is_visible_and_does_not_change_global(monkeypatch):
    Stub, D = build_service()
    env = composer_on(monkeypatch, core_doc={"revision": 2, "enabled": True,
                                "full_text": OWNER_CORE,
                                "compact_text": "ГЛОБАЛЬНЫЙ КОМПАКТ.",
                                "detail_level": "compact"})
    env["chats"].overrides[777] = {pr.CORE_DOC_KEY: {
        "revision": 3, "enabled": True, "full_text": OWNER_CORE,
        "compact_text": "КОМПАКТ ЭТОГО ЧАТА.", "detail_level": "compact"}}
    chat_system, _u, chat_manifest, _llm = await _l2_system(Stub, D, chat_id=777)
    assert "КОМПАКТ ЭТОГО ЧАТА." in chat_system
    assert "ГЛОБАЛЬНЫЙ КОМПАКТ." not in chat_system
    assert core_layer(chat_manifest).source == "chat"
    global_system, _u2, global_manifest, _llm2 = await _l2_system(
        Stub, D, chat_id=101, run_id="run-global")
    assert "ГЛОБАЛЬНЫЙ КОМПАКТ." in global_system
    assert core_layer(global_manifest).source == "global"
    assert "КОМПАКТ ЭТОГО ЧАТА." not in global_system


@pytest.mark.asyncio
async def test_inspector_view_exposes_core_choice_and_versions(monkeypatch):
    composer_on(monkeypatch, core_doc={"revision": 7, "enabled": True,
                          "full_text": OWNER_CORE,
                          "compact_text": "ГЛОБАЛЬНЫЙ КОМПАКТ.",
                          "detail_level": "compact", "origin": "owner_edit"})
    view = await pc.core_inspection(101)
    assert view["level"] == "compact" and view["reason"] == "owner_setting"
    assert view["doc_key"] == pr.CORE_DOC_KEY and view["source"] == "global"
    assert view["active_revision"].startswith("r7.")
    assert view["factory_revisions"]["full"].startswith(pr.FACTORY_PREFIX)
    assert view["factory_revisions"]["compact"].startswith(pr.FACTORY_PREFIX)
    assert view["edit_blocks"] == {"full": pr.CORE_FULL_BLOCK_ID,
                                   "compact": pr.CORE_COMPACT_BLOCK_ID}
    # ASAP W1 (22.10.2026, §3.2): провенанс заводского Core v3 — готовый
    # текст владельца (asap-speech-arch §3.2); история v1 (SOUL-02 +
    # документированная правка) — в CORE_SOURCE_V1.
    assert str(view["source_provenance"]["path"]).endswith(
        "asap-speech-arch/source-2026-10-22.md")
    assert view["source_provenance"]["factory_rev_label"] == \
        "asap-core-full-v3"
    assert pr.CORE_SOURCE_V1["line_start"] == 43
    assert pr.CORE_SOURCE_V1["line_end"] == 53
    # Заводские редакции видны отдельно (размер/хеш/происхождение поля).
    assert view["factory"]["compact"]["origin"] == "factory"
    assert view["factory"]["compact"]["sha256_12"] == pr.sha12(
        pr.factory_text(pr.CORE_COMPACT_BLOCK_ID))
    assert view["factory"]["compact"]["words"] == \
        len(pr.factory_text(pr.CORE_COMPACT_BLOCK_ID).split())  # 225 после правки
    assert view["factory"]["full"]["chars"] == len(
        pr.factory_text(pr.CORE_FULL_BLOCK_ID))


@pytest.mark.asyncio
async def test_manifest_events_payload_shows_choice_without_prompt_text(monkeypatch):
    Stub, D = build_service()
    composer_on(monkeypatch)
    _system, _user, manifest, _llm = await _l2_system(Stub, D)
    payload = json.dumps(pc.manifest_for_events(manifest), ensure_ascii=False)
    assert pr.factory_text(pr.CORE_COMPACT_BLOCK_ID) not in payload
    events = json.loads(payload)
    assert events["versions"]["core_detail"] == "compact:factory_default"
    core = [lay for lay in events["layers"] if lay["layer"] == "core"][0]
    assert core["detail"].startswith("level=compact reason=factory_default")


@pytest.mark.asyncio
async def test_core_does_not_add_llm_calls(monkeypatch):
    Stub, D = build_service()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    _s, _u, _m, llm_off = await _l2_system(Stub, D, run_id="run-off")
    composer_on(monkeypatch)
    _s2, _u2, _m2, llm_on = await _l2_system(Stub, D, run_id="run-on")
    assert llm_on.calls == llm_off.calls == 1, "Core добавил LLM-вызов"
