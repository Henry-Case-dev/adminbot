"""MEME-JOKE-SPEECH §7 — обычная текстовая инициатива: чатовые слои речи.

Владелец: «проверить обычную текстовую инициативу на фактическое прохождение
Core, Expression и Style Policy с учётом глобальных и чатовых настроек; не
менять рабочую архитектуру Direct Writer без необходимости»
(`plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md`, дословно;
`arch/joke-speech-layers.md` §7).

Что доказывается ЗДЕСЬ (шов `generate_initiative_reply` →
`_l2_write_answer(initiative_writer)` → `_compose_speech_system`):

* чатовое переопределение Core/Style Policy/«Выражения» реально доезжает до
  payload модели и вытесняет глобальное (а не наоборот);
* ревизии манифеста (`versions`) — это те же ревизии, что у резолверов;
* выключенная ось снимает слой с НАЗВАННОЙ причиной, остальные слои живут.

Тот же Core/Policy/личность у Direct и Initiative уже покрыт
`tests/test_soul1_w5_observer_gates.py:test_initiative_writer_shares_core_style_and_persona`
(не правится). Writer не переделывался: OFF-ветка и `_l2_write_answer` прежние.

TEST-LIFECYCLE: CONTRACT owner=MEME-JOKE-SPEECH §7 (meme-pipeline-refactor-01)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services import bot_persona
from services import chat_params
from services import hot_config
from services import mca_expression
from services import prompt_composer as pc
from services import prompt_registry as pr
from services import style_policy as sp

CHAT = -2044
OTHER_CHAT = -2045
RUN = "initiative-speech-override-1"

GLOBAL_CORE = "ГЛОБАЛЬНОЕ_ЯДРО_ИНИЦИАТИВЫ: спокойный наблюдатель."
CHAT_CORE = "ЧАТОВОЕ_ЯДРО_ИНИЦИАТИВЫ: ехидный участник этого чата."
GLOBAL_EXPR_NOTE = "ГЛОБАЛЬНОЕ_ПОЖЕЛАНИЕ_ВЫРАЖЕНИЯ"
CHAT_EXPR_NOTE = "ЧАТОВОЕ_ПОЖЕЛАНИЕ_ВЫРАЖЕНИЯ"
PERSONA = "<Persona>\nИмя: Бот. Характер: язвительный наблюдатель.\n</Persona>"


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


async def _persona_ctx(_chat_id):
    return SimpleNamespace(persona=object(), traits=())


def _core_doc(text: str, revision: int) -> dict:
    return {"revision": revision, "enabled": True, "full_text": text,
            "compact_text": text}


def _configure(monkeypatch, *, core_enabled=True, style_enabled=True):
    """Глобальный документ ≠ чатовый оверрайд (те же ключи, что в проде)."""
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot_config.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        "flags.character_core_enabled": core_enabled,
        "flags.speech_style_policy_enabled": style_enabled,
        "flags.persona_enabled": True,
        "character.core": _core_doc(GLOBAL_CORE, 7),
        "character.expression": {"enabled": True, "note": GLOBAL_EXPR_NOTE},
        "style.policy": sp.build_document(presets=("no_quotes",), revision=3,
                                          owner=1, reason="test-global"),
    }))
    chat_params.set_chat_params_cache(_FakeChatParams({
        CHAT: {
            "character.core": _core_doc(CHAT_CORE, 11),
            "character.expression": {"enabled": True, "note": CHAT_EXPR_NOTE,
                                     "profanity": "occasional"},
            "style.policy": sp.build_document(
                presets=("no_trailing_period",), revision=9, owner=1,
                reason="test-chat"),
        },
    }))
    monkeypatch.setattr(bot_persona, "resolve_character_context", _persona_ctx)
    monkeypatch.setattr(bot_persona, "build_persona_prompt_block",
                        lambda *a, **kw: PERSONA)


class _StubLLM:
    def __init__(self, reply="Короткая инициативная реплика"):
        self.reply = reply
        self.calls = 0
        self.messages: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.messages.append([dict(m) for m in messages])
        return self.reply


class _StubService:
    """Duck-typed DirectChatService: РЕАЛЬНЫЕ методы Writer'а и композера."""

    def __init__(self, llm):
        self.llm = llm
        self.db = None

    async def _l2_write_answer(self, *args, **kwargs):
        from services.direct_chat_service import DirectChatService as D
        return await D._l2_write_answer(self, *args, **kwargs)

    async def _compose_speech_system(self, *args, **kwargs):
        from services.direct_chat_service import DirectChatService as D
        return await D._compose_speech_system(self, *args, **kwargs)

    async def _initiative_persona_block(self, chat_id: int) -> str:
        # Тот же единый резолв личности, что у жанрового Writer'а мемов.
        block, _ctx = await bot_persona.resolve_character_block(int(chat_id))
        return block

    async def _refresh_turn_aliases(self, chat_id: int) -> None:
        return None


def _run_initiative():
    from services.direct_chat_service import DirectChatService as D
    from services.direct_l1 import L1Plan

    llm = _StubLLM()
    service = _StubService(llm)
    plan = L1Plan(action="reply", confidence=0.9, confidence_bucket="high",
                  source="llm")

    async def _inner():
        return await D.generate_initiative_reply(
            service, CHAT, {"goal": "повод", "kind": "development",
                            "origin": "unfinished_topic"},
            l1_plan=plan, correlation_id=RUN)

    text = asyncio.run(_inner())
    assert text.strip()
    manifest = pc.get_manifest(CHAT, run_id=RUN, writer="initiative_writer")
    assert manifest is not None
    assert len(llm.messages) == 1                 # один Writer-вызов
    system = llm.messages[0][0]["content"]
    return llm, manifest, system


@pytest.fixture(autouse=True)
def _clean_state():
    pc.reset_state()
    yield
    pc.reset_state()
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def _layer(manifest, layer_name: str):
    return next(t for t in manifest.layers if t.layer == layer_name)


# ── 1. Чатовые оверрайды Core/Style/Expression доезжают до payload ─────────

def test_initiative_uses_chat_level_core_style_and_expression(monkeypatch):
    """Чат побеждает глобал; ревизии манифеста — ревизии резолверов.

    Мутация: перестать передавать чатовые слои (читать только глобал) — тест
    падает на «в payload глобальный Core/стиль/выражение».
    """
    _configure(monkeypatch)
    _llm, manifest, system = _run_initiative()

    # Core: чатовая редакция, не глобальная
    chat_core_rev = pr.core_active_revision(text=CHAT_CORE, document_revision="11")
    assert manifest.versions["core"] == chat_core_rev
    assert CHAT_CORE in system
    assert GLOBAL_CORE not in system
    assert _layer(manifest, "core").rendered is True

    # Style Policy: чатовый документ (revision 9), не глобальный
    chat_policy = asyncio.run(sp.resolve_style_policy_ref(CHAT))
    global_policy = asyncio.run(sp.resolve_style_policy_ref(OTHER_CHAT))
    assert chat_policy.source == "chat"
    assert global_policy.source == "global"
    assert chat_policy.hint and global_policy.hint
    assert chat_policy.hint != global_policy.hint
    assert manifest.versions["style_policy"] == chat_policy.revision
    assert chat_policy.hint in system
    assert global_policy.hint not in system

    # «Выражение»: чатовое пожелание владельца и чатовый контрол, не глобальные
    chat_expr = asyncio.run(pc.resolve_expression_settings(CHAT))
    global_expr = asyncio.run(pc.resolve_expression_settings(OTHER_CHAT))
    assert chat_expr.source == "chat"
    assert global_expr.source == "default"
    assert chat_expr.revision != global_expr.revision
    assert manifest.versions["expression"] == chat_expr.revision
    assert CHAT_EXPR_NOTE in system and GLOBAL_EXPR_NOTE not in system
    assert mca_expression.EXPRESSION_HEADER in system

    # Личность инициативы — тот же кадр, что у Direct-хода этого чата
    assert PERSONA in system
    assert _layer(manifest, "identity").rendered is True


# ── 2. Выключенная ось: слоя нет, причина названа, остальное живо ──────────

@pytest.mark.parametrize("axis,reason,absent,present", [
    ("core", "core_disabled", (CHAT_CORE, GLOBAL_CORE), (PERSONA, CHAT_EXPR_NOTE)),
    ("style", "style_policy_disabled", (None,), (CHAT_CORE, PERSONA)),
])
def test_initiative_disabled_axis_skips_layer_with_reason(monkeypatch, axis,
                                                          reason, absent,
                                                          present):
    if axis == "core":
        _configure(monkeypatch, core_enabled=False)
    else:
        _configure(monkeypatch, style_enabled=False)
    _llm, manifest, system = _run_initiative()
    target = _layer(manifest,
                    "style_policy_hint" if axis == "style" else "core")
    assert target.rendered is False
    assert target.skip_reason == reason
    assert reason in pc.SKIP_REASONS
    for marker in absent:
        if marker is not None:
            assert marker not in system
    for marker in present:
        assert marker in system
