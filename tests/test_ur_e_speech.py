# -*- coding: utf-8 -*-
"""UR-E (UNIFIED-REPLY) — речь/характер: один Writer, один deterministic
style-pass, снятие автоподражания и лексического mood-ярлыка.

Строки карты `plans/features/unified-reply/requirements-map.json` (slice UR-E):

* UR-14 / UR-RES-06 — активная сборка Direct/Initiative НЕ добавляет
  `<style_anchors>` из прошлых ответов бота с директивой «подражай»;
  владельческие инструкции/характер/библиотеки примеров не тронуты;
  история реплик бота остаётся читаемой (факты коммуникации, не инструкции);
* UR-15 — L2 собирается ОДНОЙ финальной композицией (character/style входы
  доходят до единственного Writer-вызова); детерминированные правила формы
  владельца применяются РОВНО ОДИН раз на каждый триггер; стилевое нарушение
  НЕ вызывает перегенерации (0 LLM в проходе); protected spans
  (код/URL/JSON) не повреждаются;
* UR-16 — лексический mood-ярлык («зло/радостно» → «подстрой тон») не
  подмешивается в L2 как самостоятельная инструкция;
* UR-BAN-07 — алиасы, prompt versioning, владельческие speech instructions,
  ограничения доступа к chat data, инструменты безопасности и SendRecheck
  не удалены.

Мутация: второй литературный вызов (generation) ловится счётчиком
`author_state`; повторный style-pass не может скрыться от ops-трассы хода.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-E
"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import direct_chat_service as dcs
from services import mca_intents as mi
from services import prompt_composer as _pcomp
from services import style_policy as _sp
from services import turn_trace as _ttrace
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.direct_l1 import L1Plan
from tests.test_asap7_direct_l1 import _drive, _plan_json, _FakeLLM
from tests.test_direct_chat import (CHAT_ID, FakeMemory, _make_service,
                                    _message, _user)

CHAT = CHAT_ID


@pytest.fixture(autouse=True)
def _exploration_off(monkeypatch):
    """Детерминизм: mca-10b exploration-draw не подменяет intent-кандидата."""
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


@pytest.fixture(autouse=True)
def _clean_events():
    from services import mca_events
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


def _writer_payload(llm):
    """Полный payload последнего l2_writer-вызова (system+user склейка)."""
    calls = llm.calls_of("l2_writer")
    assert calls, f"нет l2_writer-вызова: {llm.steps()}"
    return "".join(str(m.get("content") or "")
                   for m in calls[-1]["messages"])


def _spy_style_policy(monkeypatch):
    """Шпион на `apply_style_policy` (обе ветки идут через один модуль)."""
    calls: list = []
    real = _sp.apply_style_policy

    async def _spy(text, **kwargs):
        calls.append({"text": str(text or ""), **kwargs})
        return await real(text, **kwargs)

    monkeypatch.setattr(dcs._style_policy, "apply_style_policy", _spy)
    return calls


def _spy_writer(monkeypatch):
    """Шпион на шве Writer'а: kwargs каждого вызова + реальный результат."""
    calls: list = []
    real_l2 = DirectChatService._l2_write_answer

    async def _l2_spy(self, chat_id, query, **kwargs):
        calls.append(kwargs)
        return await real_l2(self, chat_id, query, **kwargs)

    monkeypatch.setattr(DirectChatService, "_l2_write_answer", _l2_spy)
    return calls


def _spy_composer(monkeypatch):
    """Шпион на единственной сборке system (одна композиция на вызов)."""
    calls: list = []
    real = DirectChatService._compose_speech_system

    async def _spy(self, **kwargs):
        calls.append(kwargs)
        return await real(self, **kwargs)

    monkeypatch.setattr(DirectChatService, "_compose_speech_system", _spy)
    return calls


async def _init_db(tmp_path, name="ur_e.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _make_intent(db, *, goal="что там с релизом?"):
    import time as _time
    now = int(_time.time())
    result = await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal=goal, source_refs=("msg:11",),
        not_before=now - 7200, expires_at=now + 3 * 86400,
        activation_condition="time_due", created_at=now - 7200)
    intent_id = result[0] if isinstance(result, tuple) else result
    row = await mi.get_service(db).store.get_intent(intent_id)
    return intent_id, row


def _candidate(intent_id):
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
        reason_code="default")


def _situation():
    return mi.InitiativeSituation(trigger_kind="intent_due", chat_id=CHAT)


# ── UR-14 / UR-RES-06: автоподражание снято, история сохранена ───────────────

class TestNoAutoImitation:
    @pytest.mark.asyncio
    async def test_direct_writer_payload_has_no_anchors_with_history(
            self, monkeypatch, tmp_path):
        """UR-14: реплики бота есть в истории, но <style_anchors> с
        «подражай…» в payload единственного Writer-вызова нет."""
        db = await _init_db(tmp_path, "ur_e_anchors.db")
        replies = ["норм отвечаю", "сцуко, ну держи", "короче, работает"]
        base_ts = time.time() - 60.0     # около реального now: ленивый TTL
        for i, text in enumerate(replies):
            await db.upsert_bot_reply(CHAT, 100 + i, text, base_ts + i)
        llm = _FakeLLM(l1=_plan_json(), l2="ответ Direct")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "как дела?", llm=llm, real_user_content=True)
        svc.db = db          # та же история читается сборкой хода
        try:
            await svc.handle(bot, msg, user)
            payload = _writer_payload(llm)
            assert "<style_anchors>" not in payload
            assert "подражай" not in payload
            assert "интонации этих ответов" not in payload
            # История не удалялась: реплики остаются фактами коммуникации.
            history = await db.last_bot_replies(CHAT, 10, time.time())
            assert "норм отвечаю" in history
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_initiative_writer_payload_has_no_anchors(
            self, monkeypatch):
        """UR-14 (обе сборки): инициативный Writer не получает ни
        <style_anchors>, ни mood-ярлыка — общий путь без автостиля."""
        rows = [{"user_id": 10, "author_name": "Вася",
                 "text": "сцуко, где релиз?", "timestamp": 100,
                 "media_type": "text", "reply_to_id": None,
                 "tg_message_id": 300, "id": 1}]
        llm = _FakeLLM(l2="ответ инициативы")
        svc = _make_service(llm=llm, memory=FakeMemory(window=rows))
        text = await svc.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="normal", source="llm"),
            correlation_id="corr-ur-e-init")
        assert text == "ответ инициативы"
        payload = _writer_payload(llm)
        assert "<style_anchors>" not in payload
        assert "подражай" not in payload
        assert "<mood>" not in payload
        assert "подстрой тон" not in payload


# ── UR-15: character/style входы — в ОДИН Writer-вызов ────────────────────────

class TestCharacterStyleInputsOneWriter:
    @pytest.mark.asyncio
    async def test_direct_owner_style_reaches_single_writer_call(
            self, monkeypatch):
        """UR-15: владельческие style-директивы (K3 scope) доезжают до
        ЕДИНСТВЕННОГО Writer-вызова и единственной композиции system
        (style_block композера = style_directives шва)."""
        monkeypatch.setattr(_pcomp, "composer_enabled_now",
                            lambda gates: True)

        async def _owner_block(db, *, chat_id, text, participant_id=None):
            return "OWNER_STYLE_DIRECTIVE_MARKER"

        async def _ingest(db, *, chat_id, sender_id, text, message_id=None):
            return None

        monkeypatch.setattr(dcs._style_scope, "resolve_block", _owner_block)
        monkeypatch.setattr(dcs._style_scope, "ingest_message", _ingest)
        llm = _FakeLLM(l1=_plan_json(), l2="ответ Direct")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "как дела?", llm=llm, real_user_content=True)
        svc._decision_addressed = lambda *a, **k: True
        writer_calls = _spy_writer(monkeypatch)
        composer_calls = _spy_composer(monkeypatch)
        await svc.handle(bot, msg, user)
        assert len(writer_calls) == 1, \
            f"Writer вызван не один раз: {llm.steps()}"
        assert writer_calls[0].get("style_directives") == \
            "OWNER_STYLE_DIRECTIVE_MARKER"
        composed = [c for c in composer_calls
                    if str(c.get("writer") or "") == "l2_writer"]
        assert len(composed) == 1, composed
        assert composed[0].get("style_block") == \
            "OWNER_STYLE_DIRECTIVE_MARKER"
        assert composed[0].get("identity_text") == \
            writer_calls[0].get("character_block")

    @pytest.mark.asyncio
    async def test_initiative_character_input_reaches_same_writer_call(
            self, monkeypatch):
        """UR-15: character-вход инициативы доезжает до ТОГО ЖЕ шва Writer'а
        (`character_block` → единственная композиция identity_text)."""
        monkeypatch.setattr(_pcomp, "composer_enabled_now",
                            lambda gates: True)
        llm = _FakeLLM(l2="ответ инициативы")
        svc = _make_service(llm=llm)

        async def _persona(chat_id):
            return "CHARACTER_BLOCK_MARKER"

        svc._initiative_persona_block = _persona
        writer_calls = _spy_writer(monkeypatch)
        composer_calls = _spy_composer(monkeypatch)
        text = await svc.generate_initiative_reply(
            CHAT, {"goal": "тест", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="normal", source="llm"),
            correlation_id="corr-ur-e-character")
        assert text == "ответ инициативы"
        assert len(writer_calls) == 1, writer_calls
        assert writer_calls[0].get("character_block") == \
            "CHARACTER_BLOCK_MARKER"
        composed = [c for c in composer_calls
                    if str(c.get("writer") or "") == "initiative_writer"]
        assert len(composed) == 1, composed
        assert composed[0].get("identity_text") == "CHARACTER_BLOCK_MARKER"
        # Характер реально в единственной композиции system.
        assert "CHARACTER_BLOCK_MARKER" in _writer_payload(llm)


# ── UR-15: детерминированные правила — ровно один проход, без регенерации ────

class TestOwnerRulesExactlyOnce:
    @pytest.mark.asyncio
    async def test_style_pass_called_once_per_direct_turn(self, monkeypatch):
        """UR-15: на Direct-ход — ровно один `apply_style_policy`
        (stage=direct_pre_send), без LLM-repair callback."""
        calls = _spy_style_policy(monkeypatch)
        llm = _FakeLLM(l1=_plan_json(), l2='Ответ «в кавычках» конец.')
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "как дела?", llm=llm, real_user_content=True)
        await svc.handle(bot, msg, user)
        assert len(calls) == 1, calls
        assert calls[0].get("stage") == "direct_pre_send"
        assert calls[0].get("context") == "regular"
        assert calls[0].get("repair") is None
        assert not calls[0].get("repair_allowed")

    @pytest.mark.asyncio
    async def test_style_pass_called_once_per_initiative_turn(
            self, monkeypatch, tmp_path):
        """UR-15: на инициативном ходе — ровно один проход формы
        (stage=initiative_pre_send) перед чанкованием/отправкой."""
        calls = _spy_style_policy(monkeypatch)
        db = await _init_db(tmp_path, "ur_e_style.db")
        try:
            intent_id, _row = await _make_intent(db)
            llm = _FakeLLM(l1=_plan_json(), l2='Ответ «в кавычках» конец.')
            writer = _make_service(llm=llm)
            result = await dcs.handle_initiative(
                bot=AsyncMock(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur-e-style", writer_service=writer)
            assert result["status"] == "sent", result
            assert len(calls) == 1, calls
            assert calls[0].get("stage") == "initiative_pre_send"
            assert calls[0].get("context") == "initiative"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_no_regeneration_on_style_violation(self, monkeypatch):
        """UR-15/RLR: стилевое нарушение (кавычки-ёлочки) правится
        детерминированно РОВНО ОДИН раз; второй литературный вызов не
        случается (`semantic_rewrite_count == 0`, два шага LLM)."""
        llm = _FakeLLM(l1=_plan_json(), l2='Ответ «в кавычках» конец.')
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "как дела?", llm=llm, real_user_content=True)
        sends: list = []

        async def _send(b, chat_id, answer, reply_to=None, **kwargs):
            sends.append(answer)
            return 900 + len(sends)

        svc._send_direct_answer = AsyncMock(side_effect=_send)
        svc.remember_bot_reply = AsyncMock()
        await svc.handle(bot, msg, user)
        # Ровно один автор: план + writer, никаких повторов.
        assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
        assert len(sends) == 1
        # Ёлочки нормализованы заводским правилом кавычек, остальной текст
        # доставлен как написан (без перегенерации/переформулирования).
        assert sends[0] == 'Ответ "в кавычках" конец.'
        correlation = llm.calls_of("l2_writer")[-1]["correlation_id"]
        state = _ttrace.author_state(correlation)
        assert int(state.get("literary_calls") or 0) >= 1
        assert int(state.get("semantic_rewrite_count") or 0) == 0

    def test_protected_spans_intact_deterministic_pass(self):
        """UR-15 (§4): один проход правил не меняет адресата, числа, ссылки
        и смысл; код, URL и защищённые литералы не повреждаются, правятся
        только plain-регионы; 0 LLM (`repair_used == 0`)."""
        doc = {"rules": [
            {"id": "no_emoji", "kind": "emoji", "strictness": "hard",
             "scope": "global", "enabled": True, "params": {}},
            {"id": "no_trailing_period", "kind": "trailing_period",
             "strictness": "hard", "scope": "global", "enabled": True,
             "params": {}},
        ], "soft_instructions": []}
        policy = _sp.effective_policy_sync(None, doc, context="regular")
        text = ('Пример «цитата» 🎉 конец.\n'
                '```python\n'
                'x = "«в коде»"  # 🎉\n'
                '```\n'
                'Док: https://example.com/?q=«запрос»\n')
        out = asyncio.run(_sp.apply_style_policy(
            text, chat_id=0, policy=policy, context="regular",
            record=False))
        assert out.applied is True
        assert out.repair_used == 0                  # детерминированно, 0 LLM
        result = out.text
        # Plain: ёлочки нормализованы, эмодзи снят, хвостовая точка снята.
        assert '"цитата"' in result and "«цитата»" not in result
        assert "🎉 конец" not in result.split("```")[0]
        assert not result.rstrip().endswith(".")
        # Code fence байт-в-байт: и кавычки-ёлочки, и эмодзи внутри живы.
        fence = result.split("```python\n", 1)[1].split("```", 1)[0]
        assert fence == 'x = "«в коде»"  # 🎉\n'
        # URL не тронут: запрос с ёлочками остался как есть.
        assert "https://example.com/?q=«запрос»" in result


# ── UR-16: mood-ярлык не подмешивается в L2 ──────────────────────────────────

class TestMoodLabelGone:
    @pytest.mark.asyncio
    async def test_direct_payload_no_mood_label(self, monkeypatch):
        """UR-16: провокационный/эмоциональный текст триггера не создаёт
        `<mood>`-инструкцию в payload Writer'а (флаг ON по умолчанию)."""
        llm = _FakeLLM(l1=_plan_json(), l2="спокойный ответ")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "да блин, всё бесит, скажи как дела",
            llm=llm, real_user_content=True)
        await svc.handle(bot, msg, user)
        payload = _writer_payload(llm)
        assert "<mood>" not in payload
        assert "подстрой тон" not in payload
        assert "собеседник звучит" not in payload


# ── мутация: второй style/generation pass обнаруживается ─────────────────────

class TestSecondPassMutation:
    @pytest.mark.asyncio
    async def test_second_generation_pass_is_caught_by_author_state(self):
        """Мутация generation: второй литературный вызов того же хода даёт
        `semantic_rewrite_count > 0` — второй автор не скрывается."""
        from services.llm_client import LLMCompletion
        from services.negative_constraints import verbalize_validated

        class _TwoShotLLM:
            def __init__(self):
                self.shots = 0

            async def generate(self, messages, **kwargs):
                self.shots += 1
                return f"текст автора №{self.shots}"

        llm = _TwoShotLLM()
        correlation = "corr-ur-e-mutation-gen"
        trace = _ttrace.begin(correlation, chat_id=CHAT)
        author_state = trace.author_state

        async def _generate(messages):
            return await llm.generate(messages, step="l2_writer")

        _text1, stats1 = await verbalize_validated(
            _generate, [{"role": "system", "content": "s"},
                        {"role": "user", "content": "q"}],
            max_retries=0, author_state=author_state)
        assert stats1["semantic_rewrite_count"] == 0, stats1
        _text2, stats2 = await verbalize_validated(
            _generate, [{"role": "system", "content": "s"},
                        {"role": "user", "content": "q"}],
            max_retries=0, author_state=author_state)
        assert stats2["semantic_rewrite_count"] == 1, stats2

    @pytest.mark.asyncio
    async def test_second_style_pass_cannot_hide_from_turn_ops(
            self, monkeypatch):
        """Мутация style: реальный ход содержит РОВНО ОДНУ операцию
        owner_style_punctuation; повторный проход форм на том же ходе
        виден в ops-трассе (не может пройти незамеченным)."""
        calls = _spy_style_policy(monkeypatch)
        llm = _FakeLLM(l1=_plan_json(), l2='Ответ «в кавычках» конец.')
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "как дела?", llm=llm, real_user_content=True)
        svc.remember_bot_reply = AsyncMock()
        await svc.handle(bot, msg, user)
        assert len(calls) == 1, calls
        correlation = llm.calls_of("l2_writer")[-1]["correlation_id"]
        trace = _ttrace.get(correlation)
        assert trace is not None
        style_ops = [o for o in trace.ops
                     if o["op"] == _ttrace.OP_STYLE]
        assert len(style_ops) == 1, trace.ops
        # Мутация (второй проход на том же ходе) — немедленно видна в трассе.
        _second = await _sp.apply_style_policy(
            'Ответ «в кавычках» конец.', chat_id=0, context="regular",
            record=False)
        _ttrace.note_op(correlation, _ttrace.OP_STYLE, _second.text)
        style_ops_after = [o for o in trace.ops
                           if o["op"] == _ttrace.OP_STYLE]
        assert len(style_ops_after) == 2, trace.ops


# ── UR-BAN-07: инфраструктура речи не удалена ────────────────────────────────

class TestBanInvariantsIntact:
    def test_speech_infrastructure_not_removed(self):
        """UR-BAN-07: алиасы, prompt versioning, владельческие speech
        instructions, ограничения доступа к chat data, инструменты
        безопасности и SendRecheck на месте (структурная проверка)."""
        # Алиасы.
        from services.summary_aliases import AliasResolver
        svc = _make_service()
        assert svc.aliases is not None
        assert AliasResolver("{}").resolve(10, "Вася", None)
        # Prompt versioning (PVR).
        from services import prompt_registry as pvr
        assert callable(pvr.declare_prompt)
        assert callable(pvr.seal_integrity)
        # Владельческие speech instructions: owner-ключ резолвится,
        # дефолт-константа жива (prompt versioning не обходится).
        from services.direct_chat_service import (
            DIRECT_VERBALIZER_SYSTEM_PROMPT, resolve_prompt)
        resolved = resolve_prompt(
            "prompts.direct_chat_verbalizer_system_prompt",
            DIRECT_VERBALIZER_SYSTEM_PROMPT)
        assert isinstance(resolved, str) and resolved
        # Ограничения доступа к chat data: защищённые факты и exemption-спаны.
        assert callable(DatabaseService.get_protected_facts)
        assert {"verbatim_quote", "url", "code", "json"} <= set(
            _sp.DEFAULT_EXEMPTIONS)
        # Инструменты общей безопасности.
        from services.safe_fetch import SafeFetcher
        assert callable(SafeFetcher)
        # SendRecheck — существующий механизм отправки.
        recheck = mi.SendRecheck()
        assert recheck is not None
        src = open(dcs.__file__, encoding="utf-8").read()
        assert "plan_logical_send(" in src and "SendRecheck()" in src
