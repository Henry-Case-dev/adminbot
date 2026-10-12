"""ASAP 8 F3 — Style Edit больше не съедает сюжет Base Cover.

Контракт (plans/features/asap8-reliability-truthfulness/architecture.md §3,
ТЗ §5.1–§5.4, §20 C1/C2/C4):

* P0 CONTENT_PRESERVATION_INVARIANTS — новый обязательный компонент,
  первый в строке, в required-ядре И в retry_core-ядре (§5.3);
* P1 STORY_IDENTITY — story_scene + CoverBrief.render() поднят из
  budget_component в обязательное ядро (story floor 160 сохраняется
  в retry-ядре);
* P2 base_style_prompt — ПОНИЖЕН с P1 (не удалён: нужен preview-ветке),
  при давлении падает первым из P2;
* fail-soft (§5.4): story identity потерян при компиляции ИЛИ P0-overflow
  ⇒ styled НЕ публикуется, публикуется Base; манифест помечает
  style_publish_skipped{reason}.

TEST-LIFECYCLE: REGRESSION owner=ASAP8/F3 (C2/C4, приоритеты compile_style_prompt)
TEST-LIFECYCLE: CONTRACT owner=ASAP8/F3 (style_publish_skipped-маркер манифеста)
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
STYLED_BYTES = b"F3-STYLED-BYTES"


def _slot_stub(monkeypatch):
    """Волна B (snapshot ON): сконфигурированный слот без сети (как в
    tests/test_asap44_cover_final_closure.py::_nanogpt_slot_stub)."""

    async def _slot(**_kw):
        return {"provider": "nanogpt",
                "base_url": "https://provider.test/v1",
                "model": "m1", "connection_id": None,
                "custom_unresolved": False, "configured": True}

    monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)


# ── C2: порядок строки и новый приоритет-карт ───────────────────────────────

class TestCompileOrder:
    def test_line_order_preservation_issue_story_style_refs_base(self):
        """§5.2: preservation → issue → story → style_instruction → refs →
        base_style; preservation — первый в строке (P0)."""
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), base_style_prompt="base style",
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        p = c.prompt
        pres = cpa.content_preservation_text()
        assert p.startswith(pres), "P0 preservation — первый в строке"
        positions = [p.find(x) for x in
                     ("ВЫПУСК 42", SCENE.split(",")[0],
                      "Сделай обложку в стиле серии", "logo:",
                      "base style")]
        assert positions == sorted(positions), positions
        assert all(x >= 0 for x in positions)
        assert not c.exceeded and not c.dropped

    def test_preservation_text_meaning_fixed(self):
        """§5.3: формулировка фиксирует смысл (event/people/actions/
        composition/framing + запрет generic-подмены + style-not-content)."""
        text = cpa.content_preservation_text().lower()
        for token in ("event", "people", "actions", "composition",
                      "framing", "generic portrait", "generic city",
                      "without changing the story"):
            assert token in text, token

    def test_story_identity_in_required_core_not_budget(self):
        """C4: при давлении story (P1) не сжимается — падают P2
        (refs/base_style); core влез → exceeded=False, сюжет целиком."""
        # limit: ровно между core и core+refs: считаем по probe.
        probe = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(),
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        core = int(probe.static_len)          # preservation+runtime+story+instr
        caps = _caps_limit(core + 8)          # refs/base_style не влезают
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42", capabilities=caps,
            base_style_prompt="base style",
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        assert not c.exceeded, c.reason
        assert SCENE in c.prompt, "story identity не сжимается (P1 core)"
        assert set(c.dropped) == {"references", "base_style_prompt"}

    def test_base_style_lowered_not_removed(self):
        """§3.2 судьба base_style_prompt: P2 — едет без давления (нужен
        preview-ветке), при давлении падает (не в required-ядре)."""
        caps = _caps_unknown()
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 1", capabilities=caps,
            base_style_prompt="base style text",
            brief=compiler.brief_from_text(SUMMARY), story_scene=SCENE)
        assert "base style text" in c.prompt
        assert c.components.get("content_preservation", 0) > 0
        # unknown limit → всё ездит, включая base_style (P2)
        assert c.dropped == []

    def test_retry_core_preservation_and_story_floor_base_style_dropped(self):
        """retry_core-ядро (§3.1): preservation → runtime → story floor
        (160 сохраняется) → identity floor → ref roles; base_style (P2)
        из ядра изъят и зафиксирован в dropped[]."""
        long_scene = ("Два человека спорят возле разбитой машины на "
                      "закатном перекрёстке. " * 6)
        r = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), base_style_prompt="base style",
            brief=compiler.brief_from_text(SUMMARY), story_scene=long_scene,
            retry_core=True)
        p = r.prompt
        assert p.startswith(cpa.content_preservation_text())
        assert "ВЫПУСК 42" in p
        floor = cpa.story_floor_text(long_scene)
        assert floor in p and len(floor) >= cpa.STORY_MIN_CHARS
        assert long_scene not in p, "сверх floor — обрезано (semantic squeeze)"
        assert "base style" not in p
        assert "base_style_prompt" in r.dropped
        assert r.reason == "semantic_squeeze"
        # детерминированный fail-soft: retry-ядро не теряет story identity
        assert cjobs.style_publish_skip_reason(
            r, story_text=cjobs._story_identity_text(
                long_scene, compiler.brief_from_text(SUMMARY))) is None


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

    def test_lost_story_floor_maps_to_story_identity_dropped(self):
        class _C:
            prompt = "preservation runtime style only"
            dropped: list = []
            exceeded = False

        story = cjobs._story_identity_text(
            SCENE, compiler.brief_from_text(SUMMARY))
        assert cjobs.style_publish_skip_reason(
            _C(), story_text=story) == "story_identity_dropped"
        # cover_brief в dropped[] — тоже fail-soft сигнал
        _C.dropped = ["cover_brief"]
        assert cjobs.style_publish_skip_reason(
            _C(), story_text=story) == "story_identity_dropped"

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
        """C4/§5.4: P0-ядро (включая story) не влезает → styled НЕ
        публикуется: платный call не вызывается, outcome=Base, манифест
        помечен style_publish_skipped{reason: prompt_limit_exceeded}."""
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
        # compiled required-строка содержала story (P1-ядро) — но ядро
        # целиком не влезло в лимит: skip по overflow.
        assert diag["story_identity_present"] is True
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

    def test_story_identity_dropped_no_paid_call_base_fallback(
            self, tmp_path, monkeypatch):
        """C4/§5.4: story floor потерян при компиляции (legacy byte-контур
        `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED=false`, лимит между
        P0-ядром и story) → styled НЕ публикуется, Base fallback с честным
        reason story_identity_dropped в манифесте и reason_detail_ru."""
        monkeypatch.setattr(cjobs.compiler, "semantic_compression_enabled",
                            lambda: False)
        base = _png(tmp_path / "f3_story.png")
        _slot_stub(monkeypatch)
        profile = _profile()
        caps_unknown = _caps_unknown()
        # issue_display прогона — preview "ВЫПУСК 01" (counter off).
        probe = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 01", capabilities=caps_unknown)
        p0_len = int(probe.static_len) - len(profile["instruction"]) - 1
        # P0 влезает, story (floor 160 < сцена) — нет.
        caps = _caps_limit(p0_len + 10)
        events: list = []
        monkeypatch.setattr(cjobs, "emit_cover_event",
                            lambda name, **fields: events.append(
                                (name, dict(fields))))
        edit_call = AsyncMock(return_value=EditResult(
            ok=True, content=STYLED_BYTES, reason="ok"))
        state = cjobs.CoverJobState(style_id="csp_f3")
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=base, profile=profile,
            summary_run_id="run-f3s", capabilities=caps,
            edit_call=edit_call, reference_paths=[],
            summary_text=SUMMARY, story_scene=SCENE,
            state=state))
        assert edit_call.await_count == 0, "сюжетно ложный styled не шлётся"
        assert meta["applied"] is False
        assert meta["outcome"] == cjobs.RESULT_BASE
        assert meta["fail_reason"] == "story_identity_dropped"
        assert meta["style_publish_skipped"] == {
            "reason": "story_identity_dropped"}
        manifest = state.prompt_manifest
        assert manifest is not None
        assert manifest["style_publish_skipped"] == {
            "reason": "story_identity_dropped"}
        assert manifest["components"][0]["key"] == "CONTENT_PRESERVATION"
        story_comp = [c for c in manifest["components"]
                      if c["key"] == "STORY_SCENE"][0]
        assert story_comp["status"] == "omitted", "сюжет честно omitted"
        failed = [f for n, f in events if n == cjobs.COVER_STYLE_FAILED
                  and f.get("reason") == "story_identity_dropped"]
        assert failed and failed[-1]["reason_code"] == "story_identity_dropped"
        assert cjobs.reason_detail_ru("story_identity_dropped")

    def test_healthy_run_publishes_styled_without_skip_marker(
            self, tmp_path, monkeypatch):
        """C2 happy path: preservation + story + base_style в фактическом
        промпте; манифест: CONTENT_PRESERVATION kept, STORY_SCENE kept (P1),
        BASE_STYLE P2, маркер style_publish_skipped отсутствует; parity
        manifest == отправленный prompt."""
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
        assert prompt.startswith(cpa.content_preservation_text())
        assert SCENE in prompt, "story identity целиком"
        assert "base style" in prompt
        diag = meta["prompt_diagnostics"]
        assert diag["story_identity_present"] is True
        manifest = state.prompt_manifest
        assert "style_publish_skipped" not in manifest
        assert manifest["final_prompt"] == prompt
        comps = {c["key"]: c for c in manifest["components"]}
        assert comps["CONTENT_PRESERVATION"]["status"] == "kept"
        assert comps["STORY_SCENE"]["priority"] == "P1"
        assert comps["STORY_SCENE"]["status"] == "kept", \
            "полный сюжет в промпте — честный kept"
        assert comps["BASE_STYLE"]["priority"] == "P2"


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
