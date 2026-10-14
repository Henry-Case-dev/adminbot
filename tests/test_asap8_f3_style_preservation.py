"""ASAP 8 F3 → ASAP 8 v6.3 B04 — Style Edit: компактный EDIT-контракт.

История: ASAP 8 F3 поднял story identity в P1-ядро против потери сюжета.
v6.3 B04 заменяет контракт: источник сцены в image-to-image — Base bitmap,
повторный перенос story_scene/summary в текст — сам дефект (1133/800).
Текущие инварианты:

* P0 компактный preservation («что оставить») + runtime-инварианты
  (выпуск один раз, без дублей) — первый в строке;
* P1 инструкция профиля («что изменить») + ОПЦИОНАЛЬНЫЙ короткий scene
  anchor (policy, dedupe);
* P2 роль референсов (логотип — графический образец);
* P3 base_style_prompt;
* fail-soft (B04.3): нормализованный payload не влезает в resolved limit
  минус headroom ⇒ платный вызов НЕ делается, публикуется Base, манифест
  помечает style_publish_skipped{prompt_limit_exceeded}.

TEST-LIFECYCLE: REGRESSION owner=REQ-B04 (контракт F3 заменён B04 v6.3:
компакт без повторного переноса сюжета; overflow → Base без платного вызова)
TEST-LIFECYCLE: CONTRACT owner=REQ-B04 (style_publish_skipped-маркер манифеста)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs
from services import image_capabilities as cap
from services import image_prompt_compiler as compiler
from services.cover_style_edit import EditResult

pytestmark = pytest.mark.asap4


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _png(path, size=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * size)
    return str(path)


def _profile(**over):
    p = {
        "profile_id": "csp_f3", "name": "F3", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": False, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True,
        "references": [{"ref_id": "r1", "asset_id": "cas_x", "label": "logo",
                        "description": "издательский знак", "ordering": 0}],
        "preview_issue": "ВЫПУСК 01",
    }
    p.update(over)
    return p


def _caps_unknown():
    return cap.ImageModelCapabilities(image_edit=cap.TRUE, max_input_images=3,
                                      prompt_limit=cap.PromptLimit())


def _caps_limit(value: int):
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=value, unit="chars",
                                     source="internal_config"))


SCENE = ("Человек чинит серверную стойку, аварийная лампа горит "
         "над стойкой.")
SUMMARY = "Медведь открывает чемпионат по шахматам. Вторая фраза."
STYLED_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 64


def _slot_stub(monkeypatch):
    """Волна B (snapshot ON): сконфигурированный слот без сети (как в
    tests/test_asap44_cover_final_closure.py::_nanogpt_slot_stub)."""

    async def _slot(**_kw):
        return {"provider": "nanogpt",
                "base_url": "https://provider.test/v1",
                "model": "m1", "connection_id": None,
                "custom_unresolved": False, "configured": True}

    monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)


# ── B04: порядок строки и компактный приоритет-карт ─────────────────────────

class TestCompileOrder:
    def test_line_order_preservation_issue_style_anchor_refs_base(self):
        """B04.1/B04.2: preservation → issue → style_instruction → scene
        anchor → refs → base_style; preservation — первый в строке; сцена
        в тексте максимум ОДИН раз (anchor, не полный перенос)."""
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), base_style_prompt="base style",
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        p = c.prompt
        assert p.startswith(cjobs.edit_preservation_text("ru")), \
            "P0 preservation — первый в строке"
        positions = [p.find(x) for x in
                     ("ВЫПУСК 42", "Сделай обложку в стиле серии",
                      SCENE.split(",")[0], "logo", "base style")]
        assert positions == sorted(positions), positions
        assert all(x >= 0 for x in positions)
        assert not c.exceeded and not c.dropped

    def test_summary_not_retransferred_in_edit(self):
        """B04.1: story_scene/summary НЕ переносятся в текст повторно —
        только опциональный короткий anchor; CoverBrief в промпте отсутствует
        (сюжет выражен Base bitmap)."""
        long_summary = ("Медведь открывает чемпионат по шахматам. "
                        "Вторая фраза. Третья деталь сцены. " * 3)
        brief = compiler.brief_from_text(long_summary)
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(),
            brief=brief, story_scene=SCENE)
        assert "Сюжет:" not in c.prompt, "CoverBrief.render не переносится"
        assert "Настроение" not in c.prompt
        assert c.prompt.count(SCENE.split(",")[0]) == 1, "сцена один раз"
        report = getattr(c, "edit_report", {})
        assert report.get("summary_retransferred") is False

    def test_preservation_text_meaning_fixed(self):
        """§5.3/B04.2: смысл сохранения сюжета зафиксирован в компоненте
        (event/people/actions/composition + запрет generic-подмены)."""
        text = cpa.content_preservation_text().lower()
        for token in ("event", "people", "actions", "composition",
                      "framing", "generic portrait", "generic city",
                      "without changing the story"):
            assert token in text, token
        ru_text = cjobs.edit_preservation_text("ru").lower()
        for token in ("людей", "действия", "событие", "композицию",
                      "не заменяй сцену", "не добавляй новых событий"):
            assert token in ru_text, token

    def test_compact_payload_fits_confirmed_limit(self):
        """B04.3: компактный payload профиля-владельца укладывается в
        confirmed 800 chars (дефект 1133/800 устранён архитектурно)."""
        profile = _profile(instruction=(
            "Сделай обложку в стиле серии «Графический роман»: чёрно-белые "
            "страницы с редкими синими акцентами, плотная штриховка, "
            "плашки кадра как в комиксе. Логотип издательства сохри."))
        c = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 42",
            capabilities=_caps_limit(800),
            base_style_prompt="base style", brief=compiler.brief_from_text(
                SUMMARY), story_scene=SCENE)
        assert not c.exceeded, c.reason
        assert len(c.prompt) <= 800

    def test_base_style_lowered_not_removed(self):
        """base_style_prompt — P3: едет без давления (эффект base-стиля уже
        в input image), при давлении падает первым."""
        caps = _caps_unknown()
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 1", capabilities=caps,
            base_style_prompt="base style text",
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        assert "base style text" in c.prompt
        assert c.components.get("content_preservation", 0) > 0
        # unknown limit → всё ездит, включая base_style (P3)
        assert c.dropped == []

    def test_retry_core_compact_no_story_floor(self):
        """retry_core (unknown-limit): компактное ядро preservation →
        runtime → identity floor → ref roles; textual story floor из ядра
        изъят (сюжет гарантирован Base bitmap, B04.1)."""
        long_scene = ("Два человека спорят возле разбитой машины на "
                      "закатном перекрёстке. " * 6)
        r = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), base_style_prompt="base style",
            brief=compiler.brief_from_text(SUMMARY), story_scene=long_scene,
            retry_core=True)
        p = r.prompt
        assert p.startswith(cjobs.edit_preservation_text("ru"))
        assert "ВЫПУСК 42" in p
        assert long_scene not in p, "полный сюжет в текст не возвращается"
        assert "base style" not in p
        assert "base_style_prompt" in r.dropped
        assert r.reason == "semantic_squeeze"


# ── §5.4: детерминированный skip-сигнал ─────────────────────────────────────

class TestSkipReason:
    def test_exceeded_maps_to_prompt_limit_exceeded(self):
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 1",
            capabilities=_caps_limit(120),
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        assert c.exceeded
        assert cjobs.style_publish_skip_reason(
            c, story_text=cjobs._story_identity_text(
                SCENE, compiler.brief_from_text(SUMMARY))) \
            == "prompt_limit_exceeded"

    def test_no_textual_story_floor_requirement(self):
        """B04.1: textual story floor больше НЕ обязательное требование —
        отсутствие сюжета в тексте не триггерит story_identity_dropped
        (семантику результата проверяет vision verification, B04.6)."""
        class _C:
            prompt = "preservation runtime style only"
            dropped: list = []
            exceeded = False

        story = cjobs._story_identity_text(
            SCENE, compiler.brief_from_text(SUMMARY))
        assert cjobs.style_publish_skip_reason(
            _C(), story_text=story) is None
        _C.dropped = ["cover_brief"]
        assert cjobs.style_publish_skip_reason(
            _C(), story_text=story) is None

    def test_empty_story_and_healthy_pass(self):
        class _C:
            prompt = "anything"
            dropped: list = []
            exceeded = False

        assert cjobs.style_publish_skip_reason(
            _C(), story_text="") is None
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 1",
            capabilities=_caps_unknown(),
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        assert cjobs.style_publish_skip_reason(
            c, story_text=cjobs._story_identity_text(
                SCENE, compiler.brief_from_text(SUMMARY))) is None


# ── C4: fail-soft публикации (styled НЕ публикуется → Base) ─────────────────

class TestFailSoftPublication:
    def test_overflow_no_paid_call_base_with_manifest_marker(
            self, tmp_path, monkeypatch):
        """B04.3: нормализованный payload не влезает (длинная инструкция
        против лимита 500) → styled НЕ публикуется: платный call не
        вызывается, outcome=Base, манифест помечен style_publish_skipped."""
        base = _png(tmp_path / "f3_overflow.png")
        _slot_stub(monkeypatch)
        events: list = []
        monkeypatch.setattr(cjobs, "emit_cover_event",
                            lambda name, **fields: events.append(
                                (name, dict(fields))))
        edit_call = AsyncMock(return_value=EditResult(
            ok=True, content=STYLED_BYTES, reason="ok"))
        state = cjobs.CoverJobState(style_id="csp_f3")
        holder: dict = {}
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base,
            profile=_profile(instruction="И" * 800),
            summary_run_id="run-f3", capabilities=_caps_limit(500),
            edit_call=edit_call, reference_paths=[],
            summary_text=SUMMARY, story_scene=SCENE,
            state=state, manifest_out=holder))
        assert edit_call.await_count == 0, "платный call не вызывается"
        assert meta["applied"] is False
        assert meta["outcome"] == cjobs.RESULT_BASE
        assert meta["fail_reason"] == "prompt_limit_exceeded"
        assert meta["reason"] == cjobs.REASON_STYLE_FAILED
        diag = meta["prompt_diagnostics"]
        assert diag["overflow_reason"] == "prompt_limit_exceeded"
        assert diag["preflight"] == "normalized_edit_payload_over_limit"
        manifest = state.prompt_manifest
        assert manifest is not None
        assert manifest["style_publish_skipped"] == {
            "reason": "prompt_limit_exceeded"}
        assert manifest["attempts"][0]["outcome"] == "failed"
        assert holder["prompt_manifest"]["style_publish_skipped"] == {
            "reason": "prompt_limit_exceeded"}
        failed = [f for n, f in events if n == cjobs.COVER_STYLE_FAILED
                  and f.get("reason") == "prompt_limit_exceeded"]
        assert failed and failed[-1]["reason_code"] == "prompt_limit_exceeded"

    def test_healthy_run_publishes_styled_without_skip_marker(
            self, tmp_path, monkeypatch):
        """B04 happy path: компактный EDIT-промпт (сцена один раз через
        anchor, summary не переносится), манифест без skip-маркера,
        format_valid отдельно от scene_preserved."""
        base = _png(tmp_path / "f3_ok.png")
        _slot_stub(monkeypatch)
        sent: list = []
        monkeypatch.setattr(cjobs, "emit_cover_event", lambda *a, **k: None)

        async def edit_call(prompt, **kw):
            sent.append(prompt)
            return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

        state = cjobs.CoverJobState(style_id="csp_f3")
        holder: dict = {}
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base, profile=_profile(),
            summary_run_id="run-f3ok", capabilities=_caps_limit(2000),
            edit_call=edit_call, reference_paths=[],
            summary_text=SUMMARY, story_scene=SCENE,
            base_style_prompt="base style",
            state=state, manifest_out=holder))
        assert meta["applied"] is True and meta["outcome"] == \
            cjobs.RESULT_STYLED
        assert len(sent) == 1
        prompt = sent[0]
        assert prompt.startswith(cjobs.edit_preservation_text("ru"))
        assert "Сюжет:" not in prompt, "summary не переносится (B04.1)"
        assert "base style" in prompt
        diag = meta["prompt_diagnostics"]
        assert diag["content_language"] == "ru"
        assert diag["image_input_used"] == {"base": True, "references": 0}
        verification = meta["semantic_verification"]
        assert verification["format_valid"] is True
        assert verification["scene_preserved"] == "unknown", \
            "без активации политики — честный unknown, не молчаливый true"
        manifest = state.prompt_manifest
        assert "style_publish_skipped" not in manifest
        assert manifest["final_prompt"] == prompt
        assert manifest["semantic_verification"]["format_valid"] is True


# ── C1: Base Cover Generation без style — поведение прежнее ────────────────

class TestC1BaseUnchanged:
    def test_base_prompt_story_first_canon_intact(self):
        """C1: Base-сборка (cpa) не задета: канон story → context → style."""
        prompt = cpa.compose_base_cover_prompt(
            "STYLE-BLOCK", "STORY-BLOCK", "CONTEXT-BLOCK")
        assert prompt == "STORY-BLOCK CONTEXT-BLOCK STYLE-BLOCK"
        plan = cpa.base_prompt_plan("STYLE", "STORY", "CTX")
        assert [p["key"] for p in plan] == ["STORY_SCENE", "SUMMARY_CONTEXT",
                                            "BASE_STYLE"]

    def test_style_manifest_story_kept_full_beats_floor(self):
        """Манифест не врёт о full-story: полный сюжет в промпте → kept,
        а не compacted/story_minimum (floor-ветка — только для сжатия)."""
        story = "Сюжет выпуска про серверную. " * 12
        m = cpa.build_style_manifest(
            issue_display="ВЫПУСК 1", instruction="i", story_scene=story,
            final_prompt=cpa.content_preservation_text() + " "
            + " ".join(story.split()) + " i")
        comp = {c["key"]: c for c in m["components"]}["STORY_SCENE"]
        assert comp["status"] == "kept" and comp["reason"] == ""
