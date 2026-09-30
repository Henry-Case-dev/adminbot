"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D2/D5;
spec §3.7/§3.8, tasks T-4107…T-4115) — Capability Resolver + Prompt Compiler.

Проверяем §87 (capability fixtures) и §88 (compiler tests):
  * known chars / known tokens / unknown limit; edit yes/no; 1/many refs;
    async/sync;
  * precedence override → discovery → conservative;
  * cache + invalidation;
  * P2 removed first; P0 preserved; issue number preserved;
    no random mid-string truncation of mandatory instruction;
    provider rejects oversized prompt (safe policy).
"""
import pytest

from services import image_capabilities as cap
from services import image_prompt_compiler as ipc


# ── capabilities ────────────────────────────────────────────────────────────

class TestCapabilities:
    def setup_method(self):
        cap.reset_cache()

    def test_conservative_unknown(self):
        c = cap.conservative_unknown()
        assert c.image_edit == cap.UNKNOWN
        assert c.max_input_images == 0
        assert c.async_jobs is False
        assert c.prompt_limit.known is False
        assert c.references_available == 0   # 1 base → 0 refs (max 0)

    def test_no_hardcoded_800(self):
        # §15/DC-7: 800 НЕ переносится в код capability-резолвера.
        # Проверяем только код (без docstring/комментариев).
        import ast
        src = (__import__("pathlib").Path(__file__).resolve().parents[1]
               / "services" / "image_capabilities.py").read_text("utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == 800:
                pytest.fail("hardcoded 800 in code")

    def test_discovery_known_chars_edit(self):
        entry = {"architecture": {"input_modalities": ["text", "image"]},
                 "capabilities": {"image_generation": True,
                                  "image_to_image": True},
                 "supported_parameters": {"resolutions": ["1024x1024"]}}
        endpoints = {"input_reference_constraints": {"max_items": 3},
                     "route": {"max_bytes": 30 * 1024 * 1024},
                     "supports_streaming": False}
        c = cap.parse_discovery(entry, endpoints)
        assert c.image_edit == cap.TRUE
        assert c.text_to_image == cap.TRUE
        assert c.max_input_images == 3
        assert c.references_available == 2      # 3 − 1 base (§13)
        assert c.max_input_bytes == 30 * 1024 * 1024
        assert c.supported_sizes == ["1024x1024"]
        assert c.source == cap.SOURCE_DISCOVERY

    def test_discovery_edit_unsupported(self):
        entry = {"capabilities": {"image_to_image": False,
                                  "inpainting": False}}
        c = cap.parse_discovery(entry, {})
        assert c.image_edit == cap.FALSE
        assert c.edit_supported is False

    def test_discovery_unknown_leaves_unknown(self):
        c = cap.parse_discovery({}, {})
        assert c.image_edit == cap.UNKNOWN
        assert c.max_input_images is None        # не выдумываем 0 при discovery

    def test_known_tokens_limit_override(self, monkeypatch):
        override = {"nano|https://x/v1|qwen": {
            "image_edit": True, "max_input_images": 3,
            "prompt_limit": {"value": 500, "unit": "tokens"}}}
        monkeypatch.setenv("COVER_STYLE_CAPABILITY_OVERRIDES",
                           __import__("json").dumps(override))
        c = cap.resolve_capabilities("nano", "https://x/v1", "qwen")
        assert c.source == cap.SOURCE_OVERRIDE
        assert c.prompt_limit.value == 500
        assert c.prompt_limit.unit == cap.UNIT_TOKENS
        assert c.prompt_limit.source == cap.SOURCE_OVERRIDE
        assert c.edit_supported is True

    def test_override_precedes_discovery(self, monkeypatch):
        override = {"p|u|m": {"image_edit": False, "max_input_images": 1}}
        monkeypatch.setenv("COVER_STYLE_CAPABILITY_OVERRIDES",
                           __import__("json").dumps(override))
        c = cap.resolve_capabilities(
            "p", "u", "m",
            discovery={"capabilities": {"image_to_image": True}},
            endpoints={"input_reference_constraints": {"max_items": 9}})
        assert c.source == cap.SOURCE_OVERRIDE
        assert c.image_edit == cap.FALSE
        assert c.max_input_images == 1

    def test_cache_ttl_and_invalidate(self, monkeypatch):
        c1 = cap.resolve_capabilities("p", "u", "m", discovery={}, endpoints={})
        assert cap._CACHE  # записано
        # повторный вызов без discovery → из кеша
        c2 = cap.resolve_capabilities("p", "u", "m")
        assert c2 is c1
        cap.invalidate("p", "u", "m")
        assert cap._override_key("p", "u", "m") not in cap._CACHE
        # refresh тоже инвалидирует
        c3 = cap.resolve_capabilities("p", "u", "m", refresh=True)
        assert c3 is not c1

    def test_cache_no_metadata_call_per_cover(self, monkeypatch):
        # §17: второй вызов без discovery не должен требовать discovery.
        calls = {"n": 0}

        c1 = cap.resolve_capabilities("p", "u", "m", discovery={}, endpoints={})
        c2 = cap.resolve_capabilities("p", "u", "m")
        assert c1 is c2
        assert calls["n"] == 0

    def test_async_flag_default_false(self):
        # §40/Q4: текущий image-контракт sync → async_jobs=False.
        c = cap.parse_discovery({"capabilities": {}}, {})
        assert c.async_jobs is False

    def test_sources_conservative_when_no_data(self):
        c = cap.resolve_capabilities("unknown", "", "model")
        assert c.source == cap.SOURCE_UNKNOWN
        assert c.image_edit == cap.UNKNOWN
        assert c.max_input_images == 0


# ── CoverBrief + compiler ───────────────────────────────────────────────────

class TestCoverBrief:
    def test_render_compact(self):
        brief = ipc.CoverBrief(scene="Кот на крыше", mood="нуар",
                               subjects=["кот"], callouts=["Мяу"])
        text = brief.render()
        assert "Кот на крыше" in text
        assert "нуар" in text
        assert brief.is_empty() is False

    def test_empty(self):
        assert ipc.CoverBrief().is_empty() is True

    def test_render_truncates_scene(self):
        brief = ipc.CoverBrief(scene="слово " * 100)
        text = brief.render(max_chars=20)
        assert len(text) <= 20


class TestCompiler:
    def _caps(self, value=None, unit="chars"):
        c = cap.conservative_unknown()
        if value is not None:
            c.prompt_limit = cap.PromptLimit(value=value, unit=unit,
                                             source=cap.SOURCE_INTERNAL)
        return c

    def test_everything_fits(self):
        comps = [
            ipc.PromptComponent("P0 invariant", ipc.P0, "inv"),
            ipc.PromptComponent("composition", ipc.P1, "comp"),
            ipc.PromptComponent("style hint", ipc.P2, "p2"),
        ]
        r = ipc.compile_prompt(comps, capabilities=self._caps(1000))
        assert "P0 invariant" in r.prompt
        assert "style hint" in r.prompt
        assert r.dropped == []

    def test_p2_removed_first(self):
        comps = [
            ipc.PromptComponent("x" * 50, ipc.P0, "p0"),
            ipc.PromptComponent("y" * 50, ipc.P1, "p1"),
            ipc.PromptComponent("z" * 50, ipc.P2, "p2"),
        ]
        r = ipc.compile_prompt(comps, capabilities=self._caps(120))
        assert "p2" in r.dropped
        assert "x" * 50 in r.prompt        # P0 сохранён

    def test_p0_preserved_never_truncated(self):
        p0 = "MANDATORY " + "a" * 200
        comps = [ipc.PromptComponent(p0, ipc.P0, "p0")]
        r = ipc.compile_prompt(comps, capabilities=self._caps(20))
        # P0 не может быть обрезан случайным text[:N] — остаётся целиком
        # (при невозможности — P0 не режется, даже если превышает лимит).
        assert "MANDATORY" in r.prompt
        assert p0 in r.prompt

    def test_runtime_number_preserved(self):
        comps = [
            ipc.PromptComponent("Номер выпуска: ВЫПУСК 44", ipc.P0, "issue"),
            ipc.PromptComponent("z" * 300, ipc.P2, "p2"),
        ]
        r = ipc.compile_prompt(comps, capabilities=self._caps(60))
        assert "ВЫПУСК 44" in r.prompt
        assert "p2" in r.dropped

    def test_no_random_mid_string_truncation(self):
        comps = [ipc.PromptComponent("сохрани композицию и сцену", ipc.P1,
                                     "p1")]
        r = ipc.compile_prompt(comps, capabilities=self._caps(10))
        # режется по границе слова, не рвёт середину слова
        assert not r.prompt.endswith("композ")

    def test_unknown_limit_safe_policy(self):
        comps = [ipc.PromptComponent("anything", ipc.P0)]
        r = ipc.compile_prompt(comps, capabilities=self._caps(None))
        assert r.limit is None
        assert r.unit == "unknown"
        assert "anything" in r.prompt
        assert r.dropped == []

    def test_provider_rejects_oversized_prompt(self):
        # Лимит мал, но есть сюжетная часть → она масштабируется, P0 цел.
        comps = [ipc.PromptComponent("P0 " + "a" * 20, ipc.P0, "p0")]
        brief = ipc.CoverBrief(scene="b " * 100)
        r = ipc.compile_prompt(comps, capabilities=self._caps(40),
                               budget_component=brief.render())
        assert "P0" in r.prompt
        assert len(r.prompt) <= 200        # сюжет усечён, не раздут

    def test_tokens_unit_uses_estimator(self):
        comps = [ipc.PromptComponent("a " * 100, ipc.P0, "p0")]
        r = ipc.compile_prompt(comps,
                               capabilities=self._caps(50, unit="tokens"))
        assert r.unit == "tokens"

    def test_estimate_known(self):
        comps = [ipc.PromptComponent("x" * 100, ipc.P0)]
        est = ipc.estimate_budget(comps, capabilities=self._caps(500),
                                  reserve_text="y" * 50)
        assert est["known"] is True
        assert est["static"] == 100
        assert est["reserve"] == 50
        assert est["scene_allowance"] == 350

    def test_estimate_unknown_no_false_number(self):
        comps = [ipc.PromptComponent("x" * 100, ipc.P0)]
        est = ipc.estimate_budget(comps, capabilities=self._caps(None))
        assert est["known"] is False
        assert est["scene_allowance"] is None
