"""ASAP 8 v6.3 B04 — компактный EDIT-контракт Style Edit (backend).

Приёмка REQ-B04.1–B04.4:
* B04.1 — источник сцены Base bitmap; story_scene/summary НЕ переносятся
  в текст повторно; pure text-to-image (base cover) не смешан;
* B04.2 — один язык (язык профиля), без EN-дублей; сцена максимум один
  раз; логотип — графический референс; «PERMsoc»/выпуск — один раз;
* B04.3 — нормализатор semantic dedupe (не слепая подстрока); scene
  anchor опционален и краток; preflight chars в единицах capability с
  configurable headroom; overflow → платный вызов НЕ делается;
* B04.4 — preview компилирует ТОТ ЖЕ маршрут (compile_style_prompt),
  полный отчёт (image input/model/route/limit source/language/chars/
  dropped/final prompt), ``limited_preview`` маркер, без test-контекста.

TEST-LIFECYCLE: CONTRACT owner=REQ-B04 (EDIT-контракт B04.1–B04.4)
"""
from __future__ import annotations

import asyncio

import pytest

from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs
from services import image_capabilities as cap
from services import image_prompt_compiler as compiler

pytestmark = pytest.mark.asap4


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _caps_unknown():
    return cap.ImageModelCapabilities(image_edit=cap.TRUE, max_input_images=3,
                                      prompt_limit=cap.PromptLimit())


def _caps_limit(value: int):
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=value, unit="chars",
                                     source="internal_config"))


def _profile(**over):
    p = {
        "profile_id": "b04", "name": "B04",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": False, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True,
        "references": [{"ref_id": "r1", "asset_id": "cas_x",
                        "label": "Логотип Медведь Press",
                        "description": "издательский знак", "ordering": 0}],
    }
    p.update(over)
    return p


SCENE = ("Человек чинит серверную стойку, аварийная лампа горит "
         "над стойкой.")
# Длинное русское summary (дефект B04: 1133 chars в промпте 800).
LONG_RU_SUMMARY = ("Медведь открыл чемпионат по шахматам на Красной "
                   "площади, вокруг собралась толпа, вспышки камер, "
                   "комментатор объявляет первый тур, судья расставляет "
                   "фигуры. " * 8)


# ── B04.1: Base bitmap — источник сцены ─────────────────────────────────────

class TestBaseBitmapSource:
    def test_full_story_and_summary_not_retransferred(self):
        """B04.1: image-to-image не переносит story_scene/summary в текст
        повторно; максимум — опциональный короткий anchor (первое
        предложение)."""
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(),
            brief=compiler.brief_from_text(LONG_RU_SUMMARY),
            story_scene=SCENE)
        assert "Сюжет:" not in c.prompt, "CoverBrief не переносится"
        assert "Персонажи/объекты" not in c.prompt
        assert c.prompt.count(SCENE) <= 1
        assert len(c.prompt) < len(LONG_RU_SUMMARY), \
            "полное summary длиннее компактного EDIT-промпта"

    def test_edit_components_exclude_summary_context(self):
        """Компоненты EDIT-сборки не содержат summary/brief компонент."""
        comps = cjobs.compile_style_edit_components(
            _profile(), issue_display="ВЫПУСК 42", story_scene=SCENE)
        labels = [label for label, _t, _p in comps]
        assert "cover_brief" not in labels
        assert "summary_context" not in labels
        assert labels[0] == "content_preservation"
        assert "scene_anchor" in labels

    def test_pure_text_to_image_branch_untouched(self):
        """Pure text-to-image (base cover) — прежний канон сборки
        (story → context → style), не смешан с EDIT-маршрутом."""
        prompt = cpa.compose_base_cover_prompt(
            "STYLE-BLOCK", "STORY-BLOCK", "CONTEXT-BLOCK")
        assert prompt == "STORY-BLOCK CONTEXT-BLOCK STYLE-BLOCK"


# ── B04.2: один язык, без дублей ────────────────────────────────────────────

class TestSingleLanguage:
    def test_ru_instruction_ru_components_no_en_duplicates(self):
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), story_scene=SCENE)
        report = getattr(c, "edit_report", {})
        assert report["language"] == "ru"
        assert cpa.EDIT_PRESERVATION_RU in c.prompt
        # Английский канон §5.3 НЕ едет дублирующим компонентом
        assert cpa.content_preservation_text() not in c.prompt

    def test_en_instruction_en_components(self):
        profile = _profile(instruction=(
            "Make the cover in a graphic novel style, bold inks."))
        c = cjobs.compile_style_prompt(
            profile, issue_display="ISSUE 42",
            capabilities=_caps_unknown(), story_scene=SCENE)
        assert getattr(c, "edit_report", {})["language"] == "en"
        assert cpa.content_preservation_text() in c.prompt
        assert cpa.EDIT_PRESERVATION_RU not in c.prompt

    def test_scene_maximum_once(self):
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), story_scene=SCENE)
        key = SCENE.split(",")[0]
        assert c.prompt.count(key) == 1, "сцена в тексте максимум один раз"

    def test_logo_is_graphic_reference_role(self):
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_unknown(), story_scene=SCENE)
        assert "Логотип Медведь Press" in c.prompt
        assert "графический образец" in c.prompt or \
            "graphic sample" in c.prompt

    def test_brand_and_issue_once_in_text(self):
        """«PERMsoc» один раз, выпуск один раз: повтор в инструкции
        снимается нормализатором (semantic dedupe, не слепая подстрока)."""
        profile = _profile(instruction=(
            "Сделай обложку в стиле серии. Сохрани номер выпуска "
            "«ВЫПУСК 42». Логотип Медведь Press размести в углу."))
        c = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 42", capabilities=_caps_unknown(),
            story_scene=SCENE)
        assert c.prompt.count("ВЫПУСК 42") == 1
        assert c.prompt.count("Медведь Press") == 1


# ── B04.3: нормализатор + preflight ─────────────────────────────────────────

class TestNormalizer:
    def test_semantic_dedupe_not_blind_substring(self):
        """Near-дубль с другим поверхностным видом снимается (Jaccard),
        хотя слепая подстрока его не нашла бы; уникальная формулировка
        сохраняется."""
        components = [
            ("runtime_invariants",
             "Не добавляй дубликаты уже существующих элементов обложки.", 0),
            ("style_instruction",
             "Пожалуйста, не добавляй дубликатов элементов, которые уже "
             "есть на обложке. И добавь вечернее освещение.", 1),
        ]
        norm, dropped = cjobs.normalize_style_edit_components(
            components, issue_display="ВЫПУСК 42")
        reasons = {(d["label"], d["reason"].split(":")[0]) for d in dropped}
        assert ("style_instruction", "near_duplicate_of") in reasons
        texts = " ".join(t for _l, t, _p in norm)
        assert "вечернее освещение" in texts, \
            "новый смысл предложения сохраняется"

    def test_exact_duplicate_dropped_from_later_component(self):
        components = [
            ("runtime_invariants", "Сохрани номер выпуска «ВЫПУСК 3».", 0),
            ("style_instruction", "Сохрани номер выпуска «ВЫПУСК 3».", 1),
        ]
        _norm, dropped = cjobs.normalize_style_edit_components(
            components, issue_display="ВЫПУСК 3")
        assert any(d["label"] == "style_instruction"
                   and d["reason"] == "duplicate_of:runtime_invariants"
                   for d in dropped)

    def test_headroom_preflight(self, monkeypatch):
        """Configurable headroom вычитается из известного лимита: payload,
        влезающий в 800-headroom, но не в 760-headroom → честный overflow."""
        monkeypatch.setenv("COVER_STYLE_EDIT_HEADROOM_CHARS", "100")
        profile = _profile(instruction="К" * 460)
        ok = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 1", capabilities=_caps_limit(800))
        assert not ok.exceeded
        assert ok.edit_report["headroom_chars"] == 100
        tight = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 1", capabilities=_caps_limit(760))
        assert tight.exceeded, "P0+P1 > 760-headroom → overflow"
        monkeypatch.delenv("COVER_STYLE_EDIT_HEADROOM_CHARS")

    def test_unknown_limit_no_invented_number(self):
        """Неопределённая image-модель: лимит НЕ выдумывается, payload
        собирается, exceeded=False, preview не смешивает unknown с 800."""
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 1",
            capabilities=_caps_unknown(), story_scene=SCENE)
        assert not c.exceeded
        assert c.resolved_limit is None
        assert c.limit is None

    def test_overflow_no_paid_call(self):
        """Подтверждённый 800: итоговый payload обязан уложиться; иначе
        caller получает exceeded и НЕ делает платный вызов."""
        profile = _profile(instruction="И" * 900)
        c = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 42",
            capabilities=_caps_limit(800), story_scene=SCENE)
        assert c.exceeded
        assert c.reason == "prompt_limit_exceeded"
        assert cjobs.style_publish_skip_reason(c, story_text="") == \
            cjobs.STYLE_PUBLISH_SKIP_OVERFLOW

    def test_scene_anchor_optional_and_short(self, monkeypatch):
        """Scene anchor: короткая сцена — краткий якорь; длинная (auto) —
        нет; policy off — никогда."""
        anchor, skip = cjobs.scene_anchor_candidate(SCENE)
        assert anchor == SCENE and skip == ""
        long_scene = "Очень длинная сцена без конкретики. " * 40
        anchor2, skip2 = cjobs.scene_anchor_candidate(long_scene)
        assert anchor2 == "" and skip2 == "scene_too_long"
        monkeypatch.setenv("COVER_STYLE_EDIT_SCENE_ANCHOR", "off")
        anchor3, skip3 = cjobs.scene_anchor_candidate(SCENE)
        assert anchor3 == "" and skip3 == "policy_off"
        monkeypatch.delenv("COVER_STYLE_EDIT_SCENE_ANCHOR")

    def test_long_russian_summary_negative(self):
        """Негатив DoD: длинное русское summary не попадает в EDIT-промпт
        целиком и не ломает вместимость при подтверждённом 800."""
        c = cjobs.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 42",
            capabilities=_caps_limit(800),
            brief=compiler.brief_from_text(LONG_RU_SUMMARY),
            story_scene=SCENE)
        assert not c.exceeded
        assert len(c.prompt) <= 800
        assert LONG_RU_SUMMARY.strip() not in c.prompt


# ── B04.4: production-identical preview ─────────────────────────────────────

class TestStyleEditPreviewReport:
    def test_preview_compiles_same_route_with_full_report(self):
        """Preview = тот же compile_style_prompt: точный финальный prompt,
        image input, model/route, limit source, язык, chars, dropped;
        без test-контекста; ``limited_preview`` помечен."""
        profile = _profile()
        caps = _caps_limit(800)
        direct = cjobs.compile_style_prompt(
            profile, issue_display="ВЫПУСК 42", capabilities=caps,
            story_scene=SCENE)
        report = cjobs.style_edit_preview_report(
            profile, issue_display="ВЫПУСК 42", capabilities=caps,
            story_scene=SCENE,
            image_input={"base": True, "references": 1},
            limit_source=caps.prompt_limit.source, route="image_api",
            model="m1", provider="nanogpt")
        assert report["limited_preview"] is True
        assert report["final_prompt"] == direct.prompt, \
            "preview компилирует production-маршрут"
        assert report["image_input_used"] == {"base": True, "references": 1}
        assert report["model"] == "m1" and report["route"] == "image_api"
        assert report["limit_source"] == "internal_config"
        assert report["limit_value"] == 800
        assert report["language"] == "ru"
        assert report["original_chars"] > 0
        assert report["final_chars"] == len(direct.prompt)
        assert report["deduped_chars"] >= report["final_chars"]
        assert isinstance(report["dedupe_dropped"], list)
        assert report["exceeded"] is False

    def test_preview_overflow_reported_without_call(self):
        profile = _profile(instruction="И" * 900)
        caps = _caps_limit(800)
        report = cjobs.style_edit_preview_report(
            profile, issue_display="ВЫПУСК 42", capabilities=caps,
            story_scene=SCENE, limit_source=caps.prompt_limit.source)
        assert report["exceeded"] is True
        assert report["overflow_reason"] == "prompt_limit_exceeded"
        assert report["limited_preview"] is True

    def test_run_style_job_preview_mode_uses_same_compiler(self, tmp_path,
                                                           monkeypatch):
        """Preview-прогон (mode=preview) шлёт ТОТ ЖЕ компактный payload,
        что прод-компилятор (parity на уровне run_style_job)."""
        import os
        base = tmp_path / "b04_preview.png"
        base.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

        async def _slot(**_kw):
            return {"provider": "nanogpt",
                    "base_url": "https://provider.test/v1",
                    "model": "m1", "connection_id": None,
                    "custom_unresolved": False, "configured": True}

        monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)
        monkeypatch.setattr(cjobs, "emit_cover_event", lambda *a, **k: None)
        sent: list = []

        async def edit_call(prompt, **kw):
            sent.append(prompt)
            return cjobs.EditResult(ok=True, content=b"\xff\xd8" + b"0" * 32,
                                    reason="ok")

        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=_profile(),
            summary_run_id=None, capabilities=_caps_limit(800),
            edit_call=edit_call, reference_paths=[],
            summary_text=LONG_RU_SUMMARY, story_scene=SCENE,
            mode=cjobs.MODE_PREVIEW))
        assert meta["applied"] is True
        direct = cjobs.compile_style_prompt(
            _profile(), issue_display=meta.get("preview_issue",
                                               "ВЫПУСК 01"),
            capabilities=_caps_limit(800), story_scene=SCENE)
        assert sent and sent[0] == direct.prompt
        assert os.environ.get("COVER_STYLE_SCENE_VERIFY") in (None, "")
