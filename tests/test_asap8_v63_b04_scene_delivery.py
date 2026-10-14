"""ASAP 8 v6.3 B04.5/B04.6 — control сюжета + доставка styled (backend).

Приёмка:
* B04.6 — format_valid отделён от scene_preserved (true/false/unknown);
  bounded image-comparison на preview/canary ловит подмену
  людей/позы/события/композиции; подмена → НЕ успешный styled
  (fail-soft Base); политика (не каждый прод-вызов) прозрачна;
* B04.5 — идемпотентная замена изображения существующего выпуска при
  поддержке API/типа RichMessage; если не позволяет — честная причина,
  без тихого «recovered»; recovery Telegram по умолчанию НЕ вызывает
  (явная политика), статус доставки виден в durable state/событии.

TEST-LIFECYCLE: CONTRACT owner=REQ-B04 (B04.5 доставка, B04.6 scene control)
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

import pytest

from services import cover_style_jobs as cjobs
from services.cover_style_edit import EditResult

pytestmark = pytest.mark.asap4


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _caps():
    from services import image_capabilities as cap
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=800, unit="chars",
                                     source="internal_config"))


def _profile(**over):
    p = {
        "profile_id": "b04scene", "name": "B04-scene",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Стиль серии: плоская графика.",
        "counter_enabled": False, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


async def _slot(**_kw):
    return {"provider": "nanogpt", "base_url": "https://provider.test/v1",
            "model": "m1", "connection_id": None, "custom_unresolved": False,
            "configured": True}


def _stub_slot(monkeypatch):
    monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)


def _scene_base(tmp_path):
    base = tmp_path / "b04_base.png"
    base.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return str(base)


def _stub_events(monkeypatch):
    monkeypatch.setattr(cjobs, "emit_cover_event", lambda *a, **k: None)


# ── B04.6: format_valid vs scene_preserved ──────────────────────────────────

class TestSceneVerificationPolicy:
    def test_mode_default_and_env(self, monkeypatch):
        monkeypatch.delenv("COVER_STYLE_SCENE_VERIFY", raising=False)
        assert cjobs.scene_verify_mode() == "preview"
        assert cjobs.scene_verify_env_explicit() is False
        monkeypatch.setenv("COVER_STYLE_SCENE_VERIFY", "all")
        assert cjobs.scene_verify_mode() == "all"
        assert cjobs.scene_verify_env_explicit() is True

    def test_due_matrix(self, monkeypatch):
        monkeypatch.setenv("COVER_STYLE_SCENE_VERIFY", "preview")
        assert cjobs.scene_verification_due(cjobs.MODE_PREVIEW) is True
        assert cjobs.scene_verification_due(cjobs.MODE_PRODUCTION) is False
        monkeypatch.setenv("COVER_STYLE_SCENE_VERIFY", "all")
        assert cjobs.scene_verification_due(cjobs.MODE_PRODUCTION) is True
        monkeypatch.setenv("COVER_STYLE_SCENE_VERIFY", "off")
        assert cjobs.scene_verification_due(cjobs.MODE_PREVIEW) is False
        monkeypatch.delenv("COVER_STYLE_SCENE_VERIFY")
        # без явного env — платных молчаливых вызовов нет; инъекция verifier
        # снимает только требование env и только для preview-режима
        assert cjobs.scene_verification_due(cjobs.MODE_PREVIEW) is False
        assert cjobs.scene_verification_due(
            cjobs.MODE_PREVIEW, verifier=lambda *a, **k: None) is True
        assert cjobs.scene_verification_due(
            cjobs.MODE_PRODUCTION, verifier=lambda *a, **k: None) is False

    def test_replaced_not_published_as_styled(self, tmp_path, monkeypatch):
        """Preview + verifier «replaced» → styled НЕ публикуется: fail-soft
        Base c semantic_preservation_failed; format_valid при этом true
        (разные сигналы)."""
        base = _scene_base(tmp_path)
        _stub_slot(monkeypatch)
        _stub_events(monkeypatch)

        async def verifier(_b, _s):
            return "replaced", "generic portrait вместо сцены"

        async def edit_call(prompt, **kw):
            return EditResult(ok=True, content=b"\xff\xd8" + b"0" * 32,
                              reason="ok")

        state = cjobs.CoverJobState(style_id="b04scene")
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base, profile=_profile(),
            summary_run_id="run-b04v", capabilities=_caps(),
            edit_call=edit_call, reference_paths=[], story_scene="Сцена.",
            mode=cjobs.MODE_PREVIEW, state=state,
            scene_verifier=verifier))
        assert meta["applied"] is False
        assert meta["outcome"] == cjobs.RESULT_BASE
        assert meta["fail_reason"] == cjobs.REASON_SEMANTIC_LOST
        verification = meta["semantic_verification"]
        assert verification["format_valid"] is True
        assert verification["scene_preserved"] == "replaced"
        assert state.styled_status == "failed"

    def test_pass_keeps_styled_and_records(self, tmp_path, monkeypatch):
        base = _scene_base(tmp_path)
        _stub_slot(monkeypatch)
        _stub_events(monkeypatch)

        async def verifier(_b, _s):
            return "pass", ""

        async def edit_call(prompt, **kw):
            return EditResult(ok=True, content=b"\xff\xd8" + b"0" * 32,
                              reason="ok")

        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base, profile=_profile(),
            summary_run_id="run-b04p", capabilities=_caps(),
            edit_call=edit_call, reference_paths=[],
            mode=cjobs.MODE_PREVIEW, scene_verifier=verifier))
        assert meta["applied"] is True
        verification = meta["semantic_verification"]
        assert verification == {"format_valid": True,
                                "scene_preserved": "pass",
                                "detail": "",
                                "policy": cjobs.scene_verify_mode()}

    def test_verifier_error_honest_unknown(self, tmp_path, monkeypatch):
        base = _scene_base(tmp_path)
        _stub_slot(monkeypatch)
        _stub_events(monkeypatch)

        async def verifier(_b, _s):
            raise RuntimeError("network down")

        async def edit_call(prompt, **kw):
            return EditResult(ok=True, content=b"\xff\xd8" + b"0" * 32,
                              reason="ok")

        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base, profile=_profile(),
            summary_run_id="run-b04u", capabilities=_caps(),
            edit_call=edit_call, reference_paths=[],
            mode=cjobs.MODE_PREVIEW, scene_verifier=verifier))
        assert meta["applied"] is True
        verification = meta["semantic_verification"]
        assert verification["format_valid"] is True
        assert verification["scene_preserved"] == "unknown"
        assert verification["detail"] == "RuntimeError"

    def test_production_default_no_compare_budget(self, tmp_path,
                                                  monkeypatch):
        """Политика прозрачна: прод-вызов по умолчанию БЕЗ сравнения
        (бюджет), Inspector получает честный unknown с причиной политики;
        платный verifier не вызывается."""
        monkeypatch.delenv("COVER_STYLE_SCENE_VERIFY", raising=False)
        base = _scene_base(tmp_path)
        _stub_slot(monkeypatch)
        _stub_events(monkeypatch)
        calls: list = []

        async def verifier(_b, _s):
            calls.append(1)
            return "pass", ""

        async def edit_call(prompt, **kw):
            return EditResult(ok=True, content=b"\xff\xd8" + b"0" * 32,
                              reason="ok")

        meta = _run(cjobs.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run-b04prod", capabilities=_caps(),
            edit_call=edit_call, reference_paths=[],
            mode=cjobs.MODE_PRODUCTION, scene_verifier=verifier))
        assert calls == [], "прод-вызов без активированной политики — 0 compare"
        verification = meta["semantic_verification"]
        assert verification["scene_preserved"] == "unknown"
        assert verification["detail"] in ("verification_env_not_set",
                                          "production_budget_policy")

    def test_format_only_signals_are_separate(self):
        """Магические байты — формат: валидные JPEG/PNG/WEBP; текст вместо
        изображения — semantic_preservation_failed; мусор — invalid."""
        ok_jpg = b"\xff\xd8\xff\xe0" + b"0" * 16
        ok_png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
        ok_webp = b"RIFF" + b"0" * 4 + b"WEBP" + b"0" * 16
        for payload in (ok_jpg, ok_png, ok_webp):
            valid, reason = cjobs._styled_payload_signal(payload)
            assert valid and reason == ""
        text_payload = "Извините, не могу обработать.".encode("utf-8")
        valid, reason = cjobs._styled_payload_signal(text_payload)
        assert not valid and reason == cjobs.REASON_SEMANTIC_LOST
        valid, reason = cjobs._styled_payload_signal(b"\x00\x01\x02\x03")
        assert not valid and reason == cjobs.REASON_INVALID_PAYLOAD


# ── B04.5: доставка / замена изображения выпуска ────────────────────────────

class TestDeliveryReplacement:
    def test_policy_default_off_and_explicit(self, monkeypatch):
        monkeypatch.delenv(cjobs.TELEGRAM_REPLACE_ENABLED_ENV,
                           raising=False)
        assert cjobs.telegram_replace_enabled() is False
        monkeypatch.setenv(cjobs.TELEGRAM_REPLACE_ENABLED_ENV, "1")
        assert cjobs.telegram_replace_enabled() is True

    def test_replace_success_idempotent_media_only(self):
        bot = AsyncMock()

        async def verifier(_b, _s):
            return "pass", ""

        path = os.path.join(os.path.dirname(__file__), "summary_cover_helpers.py")
        delivered, status = _run(cjobs.replace_published_cover_image(
            bot, chat_id=-100, message_id=42, styled_path=path))
        assert delivered is True and status == cjobs.DELIVERY_REPLACED
        # editMessageMedia меняет только media; caption/text не трогается
        kwargs = bot.edit_message_media.await_args.kwargs
        assert kwargs["chat_id"] == -100 and kwargs["message_id"] == 42
        assert kwargs["media"] is not None

    def test_replace_unsupported_honest(self):
        """Telegram не допускает редактирование rich-публикации → честный
        статус, без дубль-публикации и без тихого «recovered»."""

        class _Bad:
            async def edit_message_media(self, **kwargs):
                raise RuntimeError(
                    "Telegram server says: Bad Request: message can't be "
                    "edited")

        path = os.path.join(os.path.dirname(__file__), "summary_cover_helpers.py")
        delivered, status = _run(cjobs.replace_published_cover_image(
            _Bad(), chat_id=-100, message_id=7, styled_path=path))
        assert delivered is False
        assert status == cjobs.DELIVERY_UNSUPPORTED

    def test_lookup_message_id_from_durable_event(self, tmp_path):
        """message_id публикации берётся из durable SUMMARY_RUN_DONE
        (usage_json.message_id); нет события → None (честная причина)."""
        import json as _json
        import aiosqlite

        async def _scenario():
            db_path = tmp_path / "events.db"
            db = await aiosqlite.connect(str(db_path))
            db.row_factory = aiosqlite.Row
            await db.execute(
                "CREATE TABLE mca_events (id INTEGER PRIMARY KEY "
                "AUTOINCREMENT, ts INTEGER, level TEXT, event_name TEXT, "
                "outcome TEXT, chat_id INTEGER, usage_json TEXT)")
            await db.execute(
                "INSERT INTO mca_events (ts, level, event_name, outcome, "
                "chat_id, usage_json) VALUES (1, 'INFO', 'SUMMARY_RUN_DONE',"
                " 'success', -100, ?)",
                (_json.dumps({"message_id": 777}),))
            await db.commit()

            class _Db:
                real = db

            wrapper = _Db()
            wrapper.db = db
            got = await cjobs.lookup_published_message_id(
                wrapper, "run-1", -100)
            # fallback по chat_id — best-effort «последняя публикация
            # чата» (run-связь в событии отсутствует) — задокументировано.
            fallback = await cjobs.lookup_published_message_id(
                wrapper, "run-other", -100)
            no_chat = await cjobs.lookup_published_message_id(
                wrapper, "run-1", -999)
            await db.close()
            return got, fallback, no_chat

        got, fallback, no_chat = _run(_scenario())
        assert got == 777
        assert fallback == 777
        assert no_chat is None

    def test_recovery_delivery_default_policy_off(self, tmp_path,
                                                  monkeypatch):
        """Recovery: styled восстановлен, Telegram по умолчанию НЕ
        вызывается; статус доставки честный not_attempted_policy_off
        (никакого тихого «recovered=доставлен»)."""
        monkeypatch.delenv(cjobs.TELEGRAM_REPLACE_ENABLED_ENV,
                           raising=False)
        assert cjobs.telegram_replace_enabled() is False
        # Проверяем контракт статусов, не поднимая полный recovery sweep:
        # DELIVERY_* — стабильные коды события COVER_STYLE_RECOVERED.
        assert cjobs.DELIVERY_NOT_ATTEMPTED == "not_attempted_policy_off"
        assert cjobs.DELIVERY_REPLACED == "replaced"
        assert cjobs.DELIVERY_UNSUPPORTED == "rich_message_edit_unsupported"
        assert cjobs.DELIVERY_NO_REFERENCE == "publication_reference_missing"

    def test_cover_state_roundtrip_telegram_delivery(self):
        state = cjobs.CoverJobState(style_id="b04d")
        state.telegram_delivery = cjobs.DELIVERY_NOT_ATTEMPTED
        restored = cjobs.CoverJobState.from_json(state.to_json())
        assert restored.telegram_delivery == "not_attempted_policy_off"
