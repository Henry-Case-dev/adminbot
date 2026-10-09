"""ASAP 5 (asap5-final-fixes) — Cover Prompt Manifest + semantic squeeze.

Focused tests T-5268 (spec §16#12–20, домен B2):
1.  base manifest story+summary+style (§16#12, D8);
2.  style manifest runtime+profile+story+refs (D7);
3.  `run_style_job` получает CoverBrief от final Summary representation
    (D8/T-5251: не 300-char seed);
4.  unknown-limit retry сохраняет minimum story (§16#14/§17, D9) —
    RED-first: на прежнем коде (`minimal=True`) тест RED (сюжет
    выбрасывался целиком, прод-факт 911→708);
5.  mandatory logo/issue/reference role не drop (§16#15);
6.  actual provider prompt == stored manifest prompt/hash (§16#17);
7.  Test Style draft assembly == фактически отправленный (§16#18);
8.  full prompt API admin-only (§16#19, D7 fail-closed);
9.  no prompt text leaks to logs (§16#20, R17).

Плюс honesty `limit_source`: unknown → без выдуманного числового лимита.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs
from services import image_capabilities as cap
from services.cover_style_edit import EditResult
from services.summary_generator import SummaryGenerator

# ── fixtures ────────────────────────────────────────────────────────────────

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32
STYLED_BYTES = b"\x89PNG\r\n\x1a\n" + b"styled" * 8


def _profile(**over):
    p = {
        "profile_id": "csp_m", "name": "Manifest", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 1,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


def _caps_unknown():
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit())


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else _asyncio_run(coro)


def _asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


LONG_SCENE = ("Медведь в цилиндре открывает Чемпионат мира по шахматам "
              "на Красной площади, вокруг толпа и вспышки камер. ") * 3


# ── 1. Base manifest: story + summary + style (D8/§16#12) ───────────────────

class TestBaseManifest:
    def test_base_manifest_components(self):
        style = "photoreal, PERMsoc"
        story = "a lone cat on a neon rooftop"
        context = cpa.summary_context_text(
            "Тема выпуска", ["Первое событие. Второе событие."])
        manifest = cpa.build_base_manifest(
            base_style=style, story_scene=story,
            summary_context=context, final_prompt=(style + " " + story
                                                   + " " + context),
            provider="nano-gpt.com")
        keys = {c["key"]: c for c in manifest["components"]}
        assert set(keys) == {"BASE_STYLE", "STORY_SCENE", "SUMMARY_CONTEXT"}
        assert keys["BASE_STYLE"]["status"] == "kept"
        assert keys["STORY_SCENE"]["status"] == "kept"
        assert keys["STORY_SCENE"]["original_chars"] == len(story)
        assert keys["SUMMARY_CONTEXT"]["sent_text"] == context
        assert manifest["operation"] == "base"
        assert manifest["attempts"][0]["prompt_hash"] \
            == cpa.prompt_hash(style + " " + story + " " + context)
        # honest limit: assembly cap, не выдуманный provider-лимит
        assert manifest["limit_source"] == "assembly_cap"
        assert manifest["resolved_limit"] == 1000

    def test_base_story_minimum_style_does_not_evict_story(self):
        """D8: явный minimum budget для STORY — стиль не вытесняет сюжет.

        ASAP 7 (§2.1): канон story_first — сюжет идёт первым, стиль
        ужимается (до floor'а); story-minimum ≥160 инвариантен."""
        plan = cpa.base_prompt_plan("S" * 900, "X" * 300, "",
                                    style_cap=900, total_cap=1000)
        by_key = {c["key"]: c for c in plan}
        sent_story = by_key["STORY_SCENE"]["sent_text"]
        assert len(sent_story) >= cpa.STORY_MIN_CHARS
        assert by_key["STORY_SCENE"]["status"] in ("kept", "compacted")
        # стиль подрезан ради сюжета
        assert len(by_key["BASE_STYLE"]["sent_text"]) < 900

    def test_base_compose_without_context_matches_legacy(self, monkeypatch):
        """Бит-в-бит: без SUMMARY_CONTEXT в legacy-режиме (style_first,
        env-откат §2.1) план == прежний compose."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_PROMPT_ORDER",
                            "style_first", raising=False)
        legacy = __import__(
            "services.cover_prompt_assembly",
            fromlist=["compose_cover_image_prompt"]).compose_cover_image_prompt
        story = "Y" * 800
        assert cpa.compose_base_cover_prompt("photoreal", story, "") == \
            legacy("photoreal", story)


# ── 2/5. Style manifest + mandatory minimums (D7/D9) ────────────────────────

class TestStyleManifestAndSqueeze:
    def test_retry_core_keeps_runtime_story_profile_roles(self):
        profile = _profile(references=[
            {"ref_id": "r1", "asset_id": "cas", "label": "logo",
             "description": "D" * 300, "ordering": 0}])
        scene = LONG_SCENE
        compiled = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 42", capabilities=_caps_unknown(),
            base_style_prompt="base style", brief=None,
            story_scene=scene, retry_core=True)
        assert "ВЫПУСК 42" in compiled.prompt            # P0 полностью
        assert compiled.reason == "semantic_squeeze"
        # story-minimum: 160 chars или 100%, если короче
        floor = cpa.story_floor_text(scene)
        assert floor in compiled.prompt
        assert len(floor) >= cpa.STORY_MIN_CHARS
        assert scene not in compiled.prompt              # optional детали срезаны
        # profile identity ≥50%
        ident = cpa.profile_identity_floor(profile["instruction"])
        assert ident in compiled.prompt
        assert profile["instruction"] not in compiled.prompt
        # mandatory reference role: label живёт, описание опущено
        assert "logo" in compiled.prompt
        assert "D" * 300 not in compiled.prompt

    def test_style_manifest_runtime_profile_story_refs(self):
        profile = _profile(references=[
            {"ref_id": "r1", "asset_id": "cas", "label": "logo",
             "description": "D" * 300, "ordering": 0}])
        scene = LONG_SCENE
        brief_text = "Сюжет: Медведь открывает чемпионат."
        holder: dict = {}
        prompts: list = []

        async def edit_call(prompt, **_kw):
            prompts.append(prompt)
            if len(prompts) == 1:
                return EditResult(ok=False, reason="prompt_limit_unknown",
                                  meta={"prompt_limit_unknown": True})
            return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

        meta = _asyncio_run(cjobs.run_style_job(
            chat_id=0, base_image_path="unused", profile=profile,
            summary_run_id=None, capabilities=_caps_unknown(),
            edit_call=edit_call, reference_paths=[],
            summary_text=brief_text, story_scene=scene,
            base_style_prompt="base style",
            manifest_out=holder))
        assert meta["applied"] is True, meta
        manifest = holder["prompt_manifest"]
        comps = {c["key"]: c for c in manifest["components"]}
        assert set(comps) == {"RUNTIME_INVARIANTS", "STYLE_PROFILE",
                              "BASE_STYLE", "REFERENCES", "STORY_SCENE",
                              "SUMMARY_CONTEXT"}
        assert comps["RUNTIME_INVARIANTS"]["status"] == "kept"
        assert comps["STYLE_PROFILE"]["status"] == "compacted"
        assert comps["STYLE_PROFILE"]["reason"] == "profile_identity_floor"
        assert comps["REFERENCES"]["status"] == "compacted"
        assert comps["REFERENCES"]["sent_text"] == "logo"
        assert comps["STORY_SCENE"]["status"] == "compacted"
        assert len(comps["STORY_SCENE"]["sent_text"]) >= cpa.STORY_MIN_CHARS
        # контекст сверх story-minimum — optional: при squeeze опущен
        assert comps["SUMMARY_CONTEXT"]["status"] == "omitted"
        assert comps["SUMMARY_CONTEXT"]["reason"] == "squeezed"
        assert len(manifest["attempts"]) == 2
        assert manifest["attempts"][0]["outcome"] == "retry_superseded"
        assert manifest["attempts"][0]["reason"] == "prompt_limit_unknown"
        assert manifest["attempts"][1]["outcome"] == "ok"


# ── 3. CoverBrief от ФИНАЛЬНОГО Summary (D8/T-5251) ─────────────────────────

class TestFinalSummaryBrief:
    def test_apply_style_passes_final_summary_and_scene(self, monkeypatch):
        from services import cover_style_jobs as csj
        from services.cover_style_jobs import CoverJobState
        captured: dict = {}

        async def fake_run_style_job(**kw):
            captured.update(kw)
            return {"applied": True, "styled_path": "styled.jpg"}

        monkeypatch.setattr(csj, "cover_styles_enabled", lambda: True)
        monkeypatch.setattr(csj, "snapshot_enabled", lambda: False)
        monkeypatch.setattr(csj, "resolve_selected_style_id",
                            AsyncMock(return_value="s1"))
        monkeypatch.setattr(csj, "load_selected_profile",
                            AsyncMock(return_value=_profile()))
        monkeypatch.setattr(csj, "begin_cover_job",
                            AsyncMock(return_value=("jid", CoverJobState())))
        monkeypatch.setattr(csj, "run_style_job", fake_run_style_job)

        gen = SummaryGenerator(None, None, None, None,
                               concurrency_pool=__import__(
                                   "unittest.mock", fromlist=["MagicMock"]
                               ).MagicMock())
        meta = _asyncio_run(gen._maybe_apply_cover_style(
            -100, "base.jpg", "run-9", cover_prompt="SEED SCENE",
            base_style="style", summary_text="Финальный approved Summary."))
        assert meta["applied"] is True
        # D8/T-5251: summary_text — финальный Summary (НЕ 300-char seed),
        # story_scene — сцена base cover.
        assert captured["summary_text"] == "Финальный approved Summary."
        assert captured["story_scene"] == "SEED SCENE"


# ── 4. unknown-limit retry сохраняет minimum story (RED-first, D9) ──────────

class TestUnknownRetryStoryMinimum:
    def test_retry_keeps_story_minimum(self):
        """Прод-факт RCA: attempt 1 (911) → retry minimal=True (708) БЕЗ
        сюжета. D9: semantic squeeze сохраняет story ≥160 (или 100%).
        RED на прежнем коде: minimal выбрасывал сюжет целиком."""
        profile = _profile()
        scene = LONG_SCENE
        prompts: list = []
        holder: dict = {}

        async def edit_call(prompt, **_kw):
            prompts.append(prompt)
            if len(prompts) == 1:
                return EditResult(ok=False, reason="prompt_limit_unknown",
                                  meta={"prompt_limit_unknown": True})
            return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

        meta = _asyncio_run(cjobs.run_style_job(
            chat_id=0, base_image_path="unused", profile=profile,
            summary_run_id=None, capabilities=_caps_unknown(),
            edit_call=edit_call, reference_paths=[],
            story_scene=scene, manifest_out=holder))
        assert len(prompts) == 2, "ровно один bounded retry"
        assert len(prompts[1]) < len(prompts[0]), "retry короче"
        story_in_retry = cpa.story_floor_text(scene)
        assert story_in_retry in prompts[1]
        assert len(story_in_retry) >= cpa.STORY_MIN_CHARS
        # honesty: limit_source неизвестен → БЕЗ выдуманного числового лимита
        manifest = holder["prompt_manifest"]
        assert manifest["limit_source"] == "unknown"
        assert manifest["resolved_limit"] is None
        assert manifest["limit_unit"].startswith("unknown")
        retry = meta.get("prompt_limit_unknown_retry") or {}
        assert retry.get("mode") == "semantic_squeeze"
        assert retry.get("story_min_chars") == len(story_in_retry)


# ── 6/7. manifest == фактическая отправка + durable state round-trip ────────

class TestManifestMatchesProvider:
    def test_provider_prompt_equals_manifest_attempts(self):
        profile = _profile()
        prompts: list = []
        holder: dict = {}
        state = cjobs.CoverJobState(style_id=profile["profile_id"])

        async def edit_call(prompt, **_kw):
            prompts.append(prompt)
            return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

        meta = _asyncio_run(cjobs.run_style_job(
            chat_id=0, base_image_path="unused", profile=profile,
            summary_run_id=None, capabilities=_caps_unknown(),
            edit_call=edit_call, reference_paths=[],
            summary_text="Сюжет: медведь и шахматы.", state=state,
            manifest_out=holder))
        assert meta["applied"] is True
        manifest = holder["prompt_manifest"]
        # actual provider prompt == Inspector stored prompt/hash (§16#17)
        assert manifest["attempts"][0]["prompt"] == prompts[0]
        assert manifest["final_prompt"] == prompts[0]
        assert manifest["prompt_hash"] == cpa.prompt_hash(prompts[0])
        assert manifest["final_chars"] == len(prompts[0])
        # durable state получил тот же манифест (персист в task_jobs payload)
        assert state.prompt_manifest == manifest
        restored = cjobs.CoverJobState.from_json(state.to_json())
        assert restored.prompt_manifest == manifest

    def test_draft_assembly_equals_sent(self):
        """§16#18: draft-сборка (та же compile-функция) == отправленный."""
        profile = _profile()
        holder: dict = {}
        prompts: list = []

        async def edit_call(prompt, **_kw):
            prompts.append(prompt)
            return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

        _asyncio_run(cjobs.run_style_job(
            chat_id=0, base_image_path="unused", profile=profile,
            summary_run_id=None, capabilities=_caps_unknown(),
            edit_call=edit_call, reference_paths=[],
            summary_text="Сюжет: медведь и шахматы.",
            manifest_out=holder))
        draft = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 02",
            capabilities=_caps_unknown(),
            brief=__import__(
                "services.image_prompt_compiler",
                fromlist=["brief_from_text"]).brief_from_text(
                    "Сюжет: медведь и шахматы."))
        assert draft.prompt == holder["prompt_manifest"]["attempts"][0]["prompt"]


# ── 8. admin-only: fail-closed manifest view (D7/INV-4) ─────────────────────

class TestAdminOnlyExposure:
    def test_public_view_strips_prompt_without_admin(self):
        manifest = cpa.build_base_manifest(
            base_style="style", story_scene="story",
            summary_context="Контекст чата.", final_prompt="style story x",
            provider="p")
        public = cpa.manifest_public(manifest, include_prompt=False)
        assert public["final_prompt"] == ""
        assert public["final_chars"] == len("style story x")
        assert public["prompt_hash"] == manifest["prompt_hash"]
        for comp in public["components"]:
            assert comp["original_text"] == ""
            assert comp["sent_text"] == ""
            assert comp["sent_chars"] > 0 or comp["key"] == "SUMMARY_CONTEXT"
        for att in public["attempts"]:
            assert att["prompt"] == ""
            assert att["chars"] > 0
            assert att["prompt_hash"]

    def test_admin_view_keeps_full_prompt(self):
        manifest = cpa.build_base_manifest(
            base_style="style", story_scene="story",
            summary_context="ctx", final_prompt="style story ctx",
            provider="p")
        admin = cpa.manifest_public(manifest, include_prompt=True)
        assert admin["final_prompt"] == "style story ctx"

    def test_public_view_none_safe(self):
        assert cpa.manifest_public(None) is None
        assert cpa.manifest_public("junk") is None


# ── 9. R17: полный prompt не течёт в generic logs ───────────────────────────

class TestNoPromptLeak:
    def test_run_style_job_logs_do_not_contain_prompt_text(self, caplog):
        profile = _profile()
        secret_scene = "СЕКРЕТНЫЙСЮЖЕТXYZ " * 30

        async def edit_call(prompt, **_kw):
            if len(prompt) > 10 ** 6:      # pragma: no cover - defensive
                raise AssertionError("unreachable")
            return EditResult(ok=False, reason="provider_error",
                              meta={"prompt_limit_unknown": True})

        with caplog.at_level(logging.DEBUG):
            meta = _asyncio_run(cjobs.run_style_job(
                chat_id=0, base_image_path="unused", profile=profile,
                summary_run_id=None, capabilities=_caps_unknown(),
                edit_call=edit_call, reference_paths=[],
                story_scene=secret_scene))
        assert meta["applied"] is False
        joined = caplog.text
        assert "СЕКРЕТНЫЙСЮЖЕТXYZ" not in joined
        # манифест-факты (hash/len) — можно; текст — нельзя
        assert meta.get("prompt_manifest_hash")


# ── helpers: floors (D9 числа) ───────────────────────────────────────────────

class TestFloors:
    def test_story_floor_shorter_than_min_stays_whole(self):
        assert cpa.story_floor_text("Короткая сцена.") == "Короткая сцена."

    def test_story_floor_cut_at_word_boundary_not_below_min(self):
        text = "слово " * 100
        out = cpa.story_floor_text(text)
        assert cpa.STORY_MIN_CHARS <= len(out) < len(text)
        assert out.endswith("слово")

    def test_profile_identity_floor_ratio(self):
        text = "alpha beta gamma delta epsilon zeta eta theta"
        out = cpa.profile_identity_floor(text, 0.5)
        assert len(out) >= len(text) * 0.5 - 1
        assert out.split()[0] == "alpha"
        assert cpa.profile_identity_floor("", 0.5) == ""
        assert cpa.profile_identity_floor("ab", 0.5) == "ab"

    def test_summary_context_bounded(self):
        paras = ["Абзац %d. Лишнее предложение." % i for i in range(50)]
        ctx = cpa.summary_context_text("Титул", paras)
        assert len(ctx) <= cpa.SUMMARY_CONTEXT_MAX_CHARS
        assert ctx.startswith("Титул")


# ── D7: durable персист Base-манифеста (task_jobs kind=cover_base) ──────────

class TestBaseManifestPersist:
    def test_record_and_load_roundtrip(self, tmp_path):
        from services.database import DatabaseService
        from services import cover_style_preview as preview_jobs
        db = DatabaseService(str(tmp_path / "jobs.sqlite3"))
        _asyncio_run(db.initialize())
        try:
            manifest = cpa.build_base_manifest(
                base_style="style", story_scene="a lone cat",
                summary_context="Тема готовый текст",
                final_prompt="style a lone cat Тема готовый текст",
                provider="nano-gpt.com")
            ok = _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id="run-e2e-1", chat_id=-100,
                manifest=manifest))
            assert ok is True
            # restart-safe: повторный прогон — та же строка (детерминир. jid)
            ok2 = _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id="run-e2e-1", chat_id=-100,
                manifest=manifest))
            assert ok2 is True
            loaded = _asyncio_run(cjobs.load_base_cover_manifest(
                db, "run-e2e-1"))
            assert loaded == manifest
            assert loaded["final_prompt"] == \
                "style a lone cat Тема готовый текст"
            # fail-closed reader (web lane): без admin — только числа/хэши
            jid = cjobs.base_manifest_job_key("run-e2e-1")
            public = _asyncio_run(preview_jobs.job_manifest(db, jid))
            assert public["final_prompt"] == ""
            assert public["prompt_hash"] == manifest["prompt_hash"]
            admin = _asyncio_run(preview_jobs.job_manifest(
                db, jid, include_prompt=True))
            assert admin["final_prompt"] == manifest["final_prompt"]
            # нет run'а → None (тихо)
            missing = _asyncio_run(cjobs.load_base_cover_manifest(
                db, "run-absent"))
            assert missing is None
        finally:
            _asyncio_run(db.close())

    def test_record_fail_open_without_db(self):
        assert _asyncio_run(cjobs.record_base_cover_manifest(
            None, summary_run_id="r", manifest={"schema": "x"})) is False
        assert _asyncio_run(cjobs.record_base_cover_manifest(
            object(), summary_run_id=None, manifest={"schema": "x"})) is False


# ── Pre-fix mechanism reproduction (RED-first artefact) ─────────────────────

class TestPreFixReproduction:
    def test_old_minimal_retry_dropped_story(self):
        """Одна репродукция прежнего механизма (RCA C4): retry `minimal=True`
        = P0+P1 — сюжет НЕ входит. На этом поведении тест
        TestUnknownRetryStoryMinimum.test_retry_keeps_story_minimum — RED.
        После фикса (retry_core) сюжет присутствует (см. тест выше)."""
        profile = _profile()
        scene = LONG_SCENE
        runtime_text = cpa.runtime_invariants_text("ВЫПУСК 11")
        components = [
            __import__("services.image_prompt_compiler",
                       fromlist=["PromptComponent"]).PromptComponent(
                           runtime_text, priority=0, label="runtime_invariants"),
            __import__("services.image_prompt_compiler",
                       fromlist=["PromptComponent"]).PromptComponent(
                           profile["instruction"], priority=1,
                           label="style_instruction"),
        ]
        compiled = __import__(
            "services.image_prompt_compiler",
            fromlist=["compile_prompt"]).compile_prompt(
                components, capabilities=_caps_unknown())
        assert "Сюжет" not in compiled.prompt
        assert scene not in compiled.prompt


# ── Settings-независимость (env caps) ────────────────────────────────────────

class TestEnvCaps:
    def test_custom_caps_respect_story_minimum(self, monkeypatch):
        monkeypatch.setattr(Settings, "SUMMARY_COVER_STYLE_MAX_CHARS", 900,
                            raising=False)
        plan = cpa.base_prompt_plan("S" * 900, "X" * 300, "ctx",
                                    style_cap=900, total_cap=1000)
        by_key = {c["key"]: c for c in plan}
        assert len(by_key["STORY_SCENE"]["sent_text"]) >= cpa.STORY_MIN_CHARS
