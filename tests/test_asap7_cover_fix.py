"""ASAP 7 (F6) — Cover content-loss fix: ordering/limits/anomaly guard/B4/B5.

Покрытие (architecture.md §2.1/§2.2/§2.4, audit-cover.md B1/B2/B4/B5/B6,
current_task.md §8/§11/§12):
1.  канонический порядок строки STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE
    (default story_first); env style_first — legacy байт-в-байт (§12 откат);
2.  B4: sent_style перекапируется total_cap (env-миссконфиг не переполняет);
3.  GENERATE prompt-limit: 400 too-long классификация (число → prompt_limit,
    без числа → prompt_limit_unknown), известный лимит → компиляция под него,
    unknown → полный промпт БЕЗ silent trim, манифест честен (assembly_cap) +
    COVER_LIMIT_UNKNOWN;
4.  shorter-retry: РОВНО ОДИН (максимум 2 платные попытки), story+context
    сохранены, стиль сжат; observed limit → source=observed_provider_400 в
    манифесте + capability-cache learning; повторный too-long →
    prompt_limit_unknown_after_retry;
5.  §11 anomaly guard: восстановление сцены (anomaly_recovered) / честный
    cover_context_missing + событие COVER_ANOMALY;
6.  E2E A/B (§12): semantic-маркеры двух summary не перепутываются;
7.  B5: learned safe ceiling не ракетится вниз (only_raise bound).

TEST-LIFECYCLE: CONTRACT owner=asap7/F6 (+ REGRESSION B1/B2/B4/B5).
Сеть не используется; полный prompt — только в манифестах (R17).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs
from services import image_capabilities as cap
from services import image_generation as ig
from services import summary_generator as sg
from services.summary_generator import SummaryGenerator

# ── fixtures ────────────────────────────────────────────────────────────────

STYLE = "photorealistic, cinematic light"

DOC_A = {
    "schema_version": 1,
    "title": "Riverside library budget approved",
    "paragraphs": [{"text": "The town council approved the riverside "
                             "library renovation budget after a long "
                             "evening debate on Monday.", "emphasis": None}],
}
DOC_B = {
    "schema_version": 1,
    "title": "Volcano eruption grounds flights",
    "paragraphs": [{"text": "A volcanic eruption in Iceland grounded "
                            "transatlantic flights and displaced a village "
                            "near Reykjavik early on Tuesday.", "emphasis":
                    None}],
}


def _mark_a(story: str) -> str:
    return story


def _collapse(text) -> str:
    return cpa.prompt_hash(text)[:0] or str(text or "").strip()


# ── 1. Ordering (§2.1) ──────────────────────────────────────────────────────

class TestOrdering:
    def test_default_story_first_canonical(self):
        """Канон: STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE."""
        assert cpa.cover_prompt_order() == "story_first"
        story, ctx = "M" * 300, "C" * 200
        out = cpa.compose_base_cover_prompt(STYLE, story, ctx)
        assert out.startswith(story + " " + ctx)
        assert out.endswith(STYLE)
        assert len(out) <= cpa.default_total_cap()
        plan = cpa.base_prompt_plan(STYLE, story, ctx)
        assert [p["key"] for p in plan] == \
            ["STORY_SCENE", "SUMMARY_CONTEXT", "BASE_STYLE"]
        by = {p["key"]: p for p in plan}
        assert by["STORY_SCENE"]["status"] == "kept"
        assert by["SUMMARY_CONTEXT"]["status"] == "kept"
        # длинный стиль ужимается до остатка (стиль — хвост канона)
        plan_long = cpa.base_prompt_plan("S" * 500, story, ctx)
        by_long = {p["key"]: p for p in plan_long}
        assert by_long["BASE_STYLE"]["status"] == "compacted"
        assert len(by_long["BASE_STYLE"]["sent_text"]) \
            >= cpa.STYLE_FLOOR_CHARS

    def test_env_style_first_legacy_bytes(self, monkeypatch):
        """env SUMMARY_COVER_PROMPT_ORDER=style_first → прежний порядок
        байт-в-байт (legacy compose 2-компонент без ctx)."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_PROMPT_ORDER",
                            "style_first", raising=False)
        story = "Y" * 800
        legacy = cpa.compose_cover_image_prompt("photoreal", story)
        assert cpa.compose_base_cover_prompt("photoreal", story, "") == legacy
        plan = cpa.base_prompt_plan(STYLE, "X" * 300, "C" * 100)
        assert [p["key"] for p in plan] == \
            ["BASE_STYLE", "STORY_SCENE", "SUMMARY_CONTEXT"]

    def test_unknown_env_value_falls_back_to_canon(self, monkeypatch):
        monkeypatch.setattr(Settings, "SUMMARY_COVER_PROMPT_ORDER",
                            "nonsense", raising=False)
        assert cpa.cover_prompt_order() == "story_first"

    def test_style_floor_reserved_in_canon(self):
        """Floor стиля 160: story+ctx не выталкивают стиль полностью."""
        out = cpa.compose_base_cover_prompt("S" * 500, "K" * 900, "C" * 400)
        # стиль получил floor и стоит в хвосте
        assert out.endswith("S" * cpa.STYLE_FLOOR_CHARS)
        assert len(out) <= cpa.default_total_cap()

    def test_story_never_fully_dropped_when_floor_fits(self):
        """Даже при жёстком капе story-minimum не исчезает целиком."""
        plan = cpa.base_prompt_plan("S" * 500, "K" * 300, "C" * 137,
                                    total_cap=150)
        by = {p["key"]: p for p in plan}
        assert by["STORY_SCENE"]["sent_text"], "story не выбрасывается"
        assert len(by["BASE_STYLE"]["sent_text"]) >= min(
            500, cpa.STYLE_FLOOR_CHARS) or not by["BASE_STYLE"]["sent_text"]


# ── 2. B4: recaper total_cap ────────────────────────────────────────────────

class TestB4StyleRecaper:
    def test_misconfig_style_never_exceeds_total(self, monkeypatch):
        """B4: style_cap=900 при total_cap=500 → sent_style ≤ total (пустой
        story не обходить clamp)."""
        for order in ("story_first", "style_first"):
            monkeypatch.setattr(Settings, "SUMMARY_COVER_PROMPT_ORDER",
                                order, raising=False)
            plan = cpa.base_prompt_plan("S" * 900, "", "C" * 400,
                                        style_cap=900, total_cap=500)
            by = {p["key"]: p for p in plan}
            assert len(by["BASE_STYLE"]["sent_text"]) <= 500
            joined = cpa.compose_base_cover_prompt(
                "S" * 900, "", "C" * 400, style_cap=900, total_cap=500)
            assert len(joined) <= 500

    def test_misconfig_with_story_keeps_story_minimum(self):
        plan = cpa.base_prompt_plan("S" * 900, "X" * 300, "",
                                    style_cap=900, total_cap=500)
        by = {p["key"]: p for p in plan}
        assert len(by["STORY_SCENE"]["sent_text"]) >= cpa.STORY_MIN_CHARS
        assert len(by["BASE_STYLE"]["sent_text"]) \
            + len(by["STORY_SCENE"]["sent_text"]) <= 501

    def test_sane_config_legacy_bytes_unchanged(self, monkeypatch):
        """Sane-конфиг (500/1000/160): style_first байт-в-байт прежний."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_PROMPT_ORDER",
                            "style_first", raising=False)
        story = "Y" * 800
        assert cpa.compose_base_cover_prompt("photoreal", story, "") == \
            cpa.compose_cover_image_prompt("photoreal", story)


# ── 3. limit_to_chars (§2.2) ────────────────────────────────────────────────

class TestLimitToChars:
    def test_conversions_conservative(self):
        assert cpa.limit_to_chars(400, "chars") == 400
        assert cpa.limit_to_chars(400, "unknown") == 400
        assert cpa.limit_to_chars(100, "tokens") == 300
        assert cpa.limit_to_chars(800, "bytes") == 400
        assert cpa.limit_to_chars(0, "chars") is None
        assert cpa.limit_to_chars(None, "chars") is None
        assert cpa.limit_to_chars("x", "chars") is None


# ── 4. E2E A/B (§12): semantic markers ──────────────────────────────────────

class TestE2EABMarkers:
    def test_marker_stays_with_own_summary_and_fits_known_limit(self):
        story_a = "unique-marker-A council library budget scene"
        story_b = "unique-marker-B volcano eruption ash scene"
        for story, other in ((story_a, "unique-marker-B"),
                             (story_b, "unique-marker-A")):
            out = cpa.compose_base_cover_prompt(STYLE, story,
                                                "context " + story)
            assert story in out
            assert other not in out
        # known limit: промпт укладывается, маркер живёт в начале строки
        for story in (story_a, story_b):
            out = cpa.compose_base_cover_prompt(
                "S" * 500, story + " " + "d" * 200, "c" * 300,
                total_cap=800)
            assert len(out) <= 802
            assert story in out, "story-first: маркер не срезан известным лимитом"

    def test_unknown_limit_full_prompt_manifest_honest(self):
        """unknown → полный промпт БЕЗ дополнительного silent trim; манифест
        честен: assembly_cap (наш кап), resolved == 1000."""
        story, ctx = "M" * 300, "C" * 200
        prompt = cpa.compose_base_cover_prompt(STYLE, story, ctx)
        manifest = cpa.build_base_manifest(
            base_style=STYLE, story_scene=story, summary_context=ctx,
            final_prompt=prompt)
        assert manifest["final_prompt"] == prompt
        assert manifest["limit_source"] == "assembly_cap"
        assert manifest["resolved_limit"] == cpa.default_total_cap()
        assert len(manifest["final_prompt"]) <= cpa.default_total_cap()


# ── 5. GENERATE 400-classification (§2.2) ───────────────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b"",
                 text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.text = text

    def json(self):
        return self._json


def _patch_transport(monkeypatch, responses):
    seq = list(responses)

    async def fake(method, url, *, json_body=None, headers=None,
                   timeout=90.0, redact_key=None, max_retries=0):
        return seq.pop(0)

    monkeypatch.setattr(ig, "_http_request", fake)


class TestGenerateLimitClassification:
    @pytest.mark.asyncio
    async def test_400_with_number_classified_prompt_limit(
            self, monkeypatch):
        _patch_transport(monkeypatch, [
            _FakeResp(400, text='{"error": {"message": "prompt maximum '
                                'length is 800 characters"}}')])
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        res = await ig.generate("x" * 50)
        assert res.ok is False
        assert res.reason == "prompt_limit"
        assert res.meta["prompt_limit"] == {"value": 800, "unit": "chars"}

    @pytest.mark.asyncio
    async def test_400_too_long_without_number_unknown(self, monkeypatch):
        _patch_transport(monkeypatch, [
            _FakeResp(400, text='{"error": "Your prompt is too long. '
                                'Please shorten it."}')])
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        res = await ig.generate("x" * 50)
        assert res.reason == "prompt_limit_unknown"
        assert res.meta.get("prompt_limit_unknown") is True

    @pytest.mark.asyncio
    async def test_400_generic_stays_bad_request(self, monkeypatch):
        _patch_transport(monkeypatch, [
            _FakeResp(400, text='{"error": "invalid model"}')])
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        res = await ig.generate("x" * 50)
        assert res.reason == "bad_request"
        assert res.meta == {}


# ── 6. Shorter-retry (§2.2): ровно один, story+ctx сохранены ────────────────

def _base_url_model():
    base_url = ig._resolve_str(ig.KEY_BASE_URL, Settings.IMAGE_BASE_URL)
    model = ig._resolve_str(ig.KEY_MODEL, Settings.IMAGE_MODEL)
    return base_url, model


class TestShorterRetry:
    def _patch_budget_and_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ig, "_consume_budget",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(ig, "_write_temp_image",
                            lambda content: str(tmp_path / "img.jpg"))

    @pytest.mark.asyncio
    async def test_observed_limit_one_retry_then_ok(self, monkeypatch,
                                                    tmp_path):
        self._patch_budget_and_file(monkeypatch, tmp_path)
        cap.reset_cache()
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return ig.GenerationResult(
                    ok=False, reason="prompt_limit",
                    meta={"prompt_limit": {"value": 400, "unit": "chars"}})
            return ig.GenerationResult(ok=True, content=b"png-bytes")

        monkeypatch.setattr(ig, "generate", fake_generate)
        builder = None

        def shorter(_orig, value, unit):
            nonlocal builder
            builder = (value, unit)
            return "short prompt under limit"

        log: list = []
        path, reason = await ig.generate_image_verbose(
            "L" * 900, chat_id=-1, correlation_id="run-retry",
            shorter_prompt=shorter, attempt_log=log)
        assert reason == "ok"
        assert path
        assert len(calls) == 2, "максимум 2 платные попытки"
        assert calls[1] == "short prompt under limit"
        assert builder == (400, "chars")
        assert [a["outcome"] for a in log] == ["retry_superseded", "ok"]
        # learning: observed limit в capability-cache
        base_url, model = _base_url_model()
        caps = cap.resolve_capabilities(
            ig.provider_label(), base_url, model,
            operation=cap.OPERATION_GENERATE)
        assert caps.prompt_limit.known
        assert caps.prompt_limit.value == 400
        assert caps.prompt_limit.unit == "chars"

    @pytest.mark.asyncio
    async def test_second_too_long_honest_after_retry(self, monkeypatch,
                                                      tmp_path):
        self._patch_budget_and_file(monkeypatch, tmp_path)
        cap.reset_cache()
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            return ig.GenerationResult(
                ok=False, reason="prompt_limit",
                meta={"prompt_limit": {"value": 300, "unit": "chars"}})

        monkeypatch.setattr(ig, "generate", fake_generate)
        path, reason = await ig.generate_image_verbose(
            "L" * 900, chat_id=-1, correlation_id="run-retry2",
            shorter_prompt=lambda p, v, u: "s" * 200)
        assert path is None
        assert reason == "prompt_limit_unknown_after_retry"
        assert len(calls) == 2, "третьего платного вызова нет"

    @pytest.mark.asyncio
    async def test_standalone_deterministic_trim_retry(self, monkeypatch,
                                                       tmp_path):
        """Standalone generate (без компилятора): word-boundary trim под
        observed limit → ровно один ретрай."""
        self._patch_budget_and_file(monkeypatch, tmp_path)
        cap.reset_cache()
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return ig.GenerationResult(
                    ok=False, reason="prompt_limit",
                    meta={"prompt_limit": {"value": 100, "unit": "chars"}})
            return ig.GenerationResult(ok=True, content=b"png")

        monkeypatch.setattr(ig, "generate", fake_generate)
        path, reason = await ig.generate_image_verbose(
            "word " * 100, chat_id=-1, correlation_id="run-retry3")
        assert reason == "ok"
        assert len(calls) == 2
        assert len(calls[1]) <= 100
        assert calls[1] != calls[0]

    @pytest.mark.asyncio
    async def test_not_shorter_no_paid_resend(self, monkeypatch, tmp_path):
        """Идентичный/не короче resend запрещён (деньги впустую)."""
        self._patch_budget_and_file(monkeypatch, tmp_path)
        cap.reset_cache()
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            return ig.GenerationResult(
                ok=False, reason="prompt_limit_unknown",
                meta={"prompt_limit_unknown": True})

        monkeypatch.setattr(ig, "generate", fake_generate)
        path, reason = await ig.generate_image_verbose(
            "tiny", chat_id=-1, correlation_id="run-retry4",
            shorter_prompt=lambda p, v, u: "tiny")
        assert path is None
        assert reason == "prompt_limit_unknown"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_unknown_no_observed_value_builder_empty_no_retry(
            self, monkeypatch, tmp_path):
        """too-long без числа и builder вернул пусто → ретрая нет."""
        self._patch_budget_and_file(monkeypatch, tmp_path)
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            return ig.GenerationResult(ok=False,
                                       reason="prompt_limit_unknown",
                                       meta={"prompt_limit_unknown": True})

        monkeypatch.setattr(ig, "generate", fake_generate)
        path, reason = await ig.generate_image_verbose(
            "L" * 900, chat_id=-1, correlation_id="run-retry5",
            shorter_prompt=lambda p, v, u: "")
        assert path is None
        assert reason == "prompt_limit_unknown"
        assert len(calls) == 1

    # ── REWORK B11: бюджет ≤2 платных вызова при любых цепочках ────────────

    @pytest.mark.parametrize("max_attempts", [2, 5])
    @pytest.mark.asyncio
    async def test_transient_then_400_no_shorter_retry_budget(
            self, monkeypatch, tmp_path, max_attempts):
        """REGRESSION B11: timeout (платно) → 400 too-long → shorter-retry
        ЗАПРЕЩЁН: too-long случился не на первой платной попытке, бюджет
        ≤2 платных вызова исчерпан → честный терминальный ``prompt_limit``,
        ровно 2 платных вызова, attempt_log пуст (ретрай не начинался).
        При env max_attempts=5 — не «до 6», а те же 2 в цепочке с 400."""
        self._patch_budget_and_file(monkeypatch, tmp_path)
        monkeypatch.setattr(ig, "_image_max_attempts",
                            lambda: max_attempts)
        monkeypatch.setattr(ig, "_image_retry_backoff", lambda: 0.0)
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return ig.GenerationResult(ok=False, reason="timeout")
            return ig.GenerationResult(
                ok=False, reason="prompt_limit",
                meta={"prompt_limit": {"value": 400, "unit": "chars"}})

        monkeypatch.setattr(ig, "generate", fake_generate)
        log: list = []
        path, reason = await ig.generate_image_verbose(
            "L" * 900, chat_id=-1, correlation_id=f"run-b11-t400-{max_attempts}",
            shorter_prompt=lambda p, v, u: "short prompt", attempt_log=log)
        assert path is None
        assert reason == "prompt_limit", "честный терминальный исход"
        assert len(calls) == 2, "третьего платного вызова (shorter-retry) нет"
        assert calls[0] == calls[1] == "L" * 900, "trim-resend не выполнялся"
        assert log == [], "shorter-retry не начинался"

    @pytest.mark.parametrize("max_attempts", [2, 5])
    @pytest.mark.asyncio
    async def test_400_on_first_attempt_retry_within_budget(
            self, monkeypatch, tmp_path, max_attempts):
        """REGRESSION B11: прямой путь остаётся зелёным — 400 too-long на
        ПЕРВОЙ платной попытке → РОВНО один shorter-retry = 2 платных
        вызова суммарно; env max_attempts>2 бюджет не расширяет."""
        self._patch_budget_and_file(monkeypatch, tmp_path)
        monkeypatch.setattr(ig, "_image_max_attempts",
                            lambda: max_attempts)
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return ig.GenerationResult(
                    ok=False, reason="prompt_limit",
                    meta={"prompt_limit": {"value": 400, "unit": "chars"}})
            return ig.GenerationResult(ok=True, content=b"png")

        monkeypatch.setattr(ig, "generate", fake_generate)
        path, reason = await ig.generate_image_verbose(
            "L" * 900, chat_id=-1,
            correlation_id=f"run-b11-direct-{max_attempts}",
            shorter_prompt=lambda p, v, u: "short prompt")
        assert reason == "ok"
        assert len(calls) == 2, "бюджет ≤2 платных вызова соблюдён"
        assert calls[1] == "short prompt"


class TestRetryCompileKeepsStoryContext:
    def test_retry_compile_preserves_story_and_context(self):
        """§2.2 retry-компиляция: story+context сохранены, стиль сжат."""
        style, story, ctx = "S" * 500, "K" * 300, "C" * 200
        shorter = cpa.compose_base_cover_prompt(style, story, ctx,
                                                total_cap=800)
        assert story in shorter
        assert ctx in shorter
        assert shorter.startswith(story)
        assert len(shorter) <= 802
        assert len(shorter) < len(cpa.compose_base_cover_prompt(
            style, story, ctx))


# ── 7. §11 anomaly guard ────────────────────────────────────────────────────

class TestAnomalyGuardDecision:
    def test_recovered_from_meaningful_article(self):
        decision = cpa.cover_context_decision(
            "", DOC_A["title"], [DOC_A["paragraphs"][0]["text"]])
        assert decision["status"] == "anomaly_recovered"
        assert decision["reason"] == "anomaly_recovered"
        assert decision["story"], "сцена восстановлена из статьи"
        assert decision["ctx"], "ctx пересобран из финального документа"

    def test_missing_short_article(self):
        decision = cpa.cover_context_decision("", "T", ["коротко"])
        assert decision["status"] == "cover_context_missing"
        assert decision["reason"] == "cover_context_missing"

    def test_ok_when_story_present(self):
        decision = cpa.cover_context_decision(
            "a council scene", DOC_A["title"],
            [DOC_A["paragraphs"][0]["text"]])
        assert decision["status"] == "ok"


class TestAnomalyGuardImpl:
    """Интеграция: точка сборки Base (_publish_rich_document_impl)."""

    def _gen(self):
        return SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                                MagicMock(), concurrency_pool=MagicMock())

    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(SummaryGenerator, "_resolve_cover_style_text",
                            AsyncMock(return_value=STYLE))
        monkeypatch.setattr(cjobs, "selection_stage",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(SummaryGenerator, "_degrade_without_cover",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(sg, "resolve_generate_prompt_limit_async",
                            AsyncMock(return_value=None))

    @pytest.mark.asyncio
    async def test_recovered_scene_recompiled_and_manifest_marked(
            self, monkeypatch, caplog):
        self._patch_common(monkeypatch)
        saved: dict = {}
        sent: dict = {}

        async def fake_gen(prompt, **kwargs):
            sent["prompt"] = prompt
            return None, "unavailable"

        async def fake_record(db, *, summary_run_id=None, chat_id=None,
                              manifest=None):
            saved["manifest"] = manifest
            return True

        monkeypatch.setattr(sg, "generate_image_verbose", fake_gen)
        monkeypatch.setattr(cjobs, "record_base_cover_manifest", fake_record)
        meta: dict = {}
        with caplog.at_level(logging.INFO,
                             logger="services.cover_style_jobs"):
            ok = await self._gen()._publish_rich_document_impl(
                -100, DOC_A, "", correlation_id="run-guard-rec",
                ctx=None, max_chunks=None, _publish_meta=meta)
        assert ok is True
        story = cpa.cover_context_decision(
            "", DOC_A["title"], [DOC_A["paragraphs"][0]["text"]])["story"]
        # канон story_first: восстановленная сцена — начало промпта
        assert sent["prompt"].startswith(story)
        assert "Riverside library budget approved" in sent["prompt"]
        manifest = saved["manifest"]
        by_key = {c["key"]: c for c in manifest["components"]}
        assert by_key["STORY_SCENE"]["sent_text"] == story
        assert by_key["STORY_SCENE"]["reason"] == "anomaly_recovered"
        assert "COVER_ANOMALY" in caplog.text
        assert "anomaly_recovered" in caplog.text

    @pytest.mark.asyncio
    async def test_short_article_no_cover_honest_reason(
            self, monkeypatch, caplog):
        self._patch_common(monkeypatch)
        gen_mock = AsyncMock(return_value=(None, "unavailable"))
        monkeypatch.setattr(sg, "generate_image_verbose", gen_mock)
        degrade = AsyncMock(return_value=True)
        monkeypatch.setattr(SummaryGenerator, "_degrade_without_cover",
                            degrade)
        short_doc = {"schema_version": 1, "title": "T",
                     "paragraphs": [{"text": "коротко", "emphasis": None}]}
        meta: dict = {}
        with caplog.at_level(logging.INFO,
                             logger="services.cover_style_jobs"):
            ok = await self._gen()._publish_rich_document_impl(
                -100, short_doc, "", correlation_id="run-guard-miss",
                ctx=None, max_chunks=None, _publish_meta=meta)
        assert ok is True
        assert degrade.await_count == 1
        kwargs = degrade.await_args.kwargs
        assert kwargs.get("reason") == "cover_context_missing"
        assert meta.get("reason") == "cover_context_missing"
        assert gen_mock.await_count == 0, "платного вызова нет"
        assert "COVER_ANOMALY" in caplog.text
        assert "cover_context_missing" in caplog.text


# ── 8. Known/unknown limit compile + manifest (§2.2) ────────────────────────

class TestLimitAwareCompileImpl:
    def _gen(self):
        return SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                                MagicMock(), concurrency_pool=MagicMock())

    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(SummaryGenerator, "_resolve_cover_style_text",
                            AsyncMock(return_value=STYLE))
        monkeypatch.setattr(cjobs, "selection_stage",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(SummaryGenerator, "_degrade_without_cover",
                            AsyncMock(return_value=True))

    @pytest.mark.asyncio
    async def test_known_limit_compiles_under_it(self, monkeypatch):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            sg, "resolve_generate_prompt_limit_async",
            AsyncMock(return_value=cap.PromptLimit(
                value=400, unit="chars",
                source=cap.SOURCE_DISCOVERY)))
        saved: dict = {}
        sent: dict = {}

        async def fake_gen(prompt, **kwargs):
            sent["prompt"] = prompt
            return None, "unavailable"

        async def fake_record(db, *, summary_run_id=None, chat_id=None,
                              manifest=None):
            saved["manifest"] = manifest
            return True

        monkeypatch.setattr(sg, "generate_image_verbose", fake_gen)
        monkeypatch.setattr(cjobs, "record_base_cover_manifest", fake_record)
        await self._gen()._publish_rich_document_impl(
            -100, DOC_A, "a council budget scene",
            correlation_id="run-limit-known", ctx=None, max_chunks=None,
            _publish_meta={})
        assert len(sent["prompt"]) <= 402
        manifest = saved["manifest"]
        assert manifest["resolved_limit"] == 400
        assert manifest["limit_source"] == "provider_or_registry"

    @pytest.mark.asyncio
    async def test_unknown_limit_event_and_assembly_manifest(
            self, monkeypatch, caplog):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(sg, "resolve_generate_prompt_limit_async",
                            AsyncMock(return_value=None))
        saved: dict = {}

        async def fake_gen(prompt, **kwargs):
            return None, "unavailable"

        async def fake_record(db, *, summary_run_id=None, chat_id=None,
                              manifest=None):
            saved["manifest"] = manifest
            return True

        monkeypatch.setattr(sg, "generate_image_verbose", fake_gen)
        monkeypatch.setattr(cjobs, "record_base_cover_manifest", fake_record)
        with caplog.at_level(logging.INFO,
                             logger="services.cover_style_jobs"):
            await self._gen()._publish_rich_document_impl(
                -100, DOC_A, "a council budget scene",
                correlation_id="run-limit-unknown", ctx=None,
                max_chunks=None, _publish_meta={})
        assert "COVER_LIMIT_UNKNOWN" in caplog.text
        manifest = saved["manifest"]
        assert manifest["limit_source"] == "assembly_cap"
        assert manifest["resolved_limit"] == cpa.default_total_cap()

    @pytest.mark.asyncio
    async def test_retry_manifest_observed_provider_400(
            self, monkeypatch, tmp_path):
        """Shorter-retry через generate_image_verbose: манифест содержит
        обе attempts, финальный промпт = фактический, source=
        observed_provider_400, story+context сохранены."""
        self._patch_common(monkeypatch)
        monkeypatch.setattr(sg, "resolve_generate_prompt_limit_async",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(ig, "_consume_budget",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(ig, "_write_temp_image",
                            lambda content: str(tmp_path / "img.jpg"))
        monkeypatch.setattr(SummaryGenerator, "_maybe_apply_cover_style",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(SummaryGenerator, "_send_rich_with_retry",
                            AsyncMock(return_value=MagicMock(message_id=7)))
        # env: aiogram без InputRichMessageMedia — media-билд стабится
        monkeypatch.setattr(sg, "build_cover_media",
                            lambda path: MagicMock())
        cap.reset_cache()
        saved: dict = {}

        async def fake_record(db, *, summary_run_id=None, chat_id=None,
                              manifest=None):
            saved["manifest"] = manifest
            return True

        monkeypatch.setattr(cjobs, "record_base_cover_manifest", fake_record)

        async def real_verbose(prompt, **kwargs):
            return await ig.generate_image_verbose(prompt, **kwargs)

        monkeypatch.setattr(sg, "generate_image_verbose", real_verbose)
        calls: list = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return ig.GenerationResult(
                    ok=False, reason="prompt_limit",
                    meta={"prompt_limit": {"value": 150, "unit": "chars"}})
            return ig.GenerationResult(ok=True, content=b"png")

        monkeypatch.setattr(ig, "generate", fake_generate)
        ok = await self._gen()._publish_rich_document_impl(
            -100, DOC_A, "a council budget scene",
            correlation_id="run-retry-manifest", ctx=None, max_chunks=None,
            _publish_meta={})
        assert ok is True
        assert len(calls) == 2
        manifest = saved["manifest"]
        assert manifest["limit_source"] == "observed_provider_400"
        assert manifest["resolved_limit"] == 150
        attempts = manifest["attempts"]
        assert len(attempts) == 2
        assert attempts[0]["outcome"] == "retry_superseded"
        assert attempts[1]["outcome"] == "ok"
        final = attempts[1]["prompt"]
        assert manifest["final_prompt"] == final
        assert "a council budget scene" in final, "story сохранён"
        assert "Riverside library budget approved" in final, "ctx частично живёт"
        assert len(final) <= 152

    def teardown_method(self):
        cap.reset_cache()


# ── 9. B5: learned ceiling bound ────────────────────────────────────────────

class TestB5CeilingBound:
    def teardown_method(self):
        cap.reset_cache()

    def test_only_raise_never_lowers_ceiling(self):
        cap.reset_cache()
        v1 = cap.record_runtime_safe_ceiling("p", "https://x", "m", None, 800)
        assert v1 == 800
        v2 = cap.record_runtime_safe_ceiling("p", "https://x", "m", None,
                                             300, only_raise=True)
        assert v2 == 800, "bound: ceiling не понижается squeeze-ретраем"
        stored = cap.resolve_capabilities("p", "https://x", "m")
        assert stored.prompt_limit.value == 800

    def test_without_flag_previous_behavior_lowering(self):
        cap.reset_cache()
        cap.record_runtime_safe_ceiling("p", "https://y", "m", None, 800)
        v = cap.record_runtime_safe_ceiling("p", "https://y", "m", None, 300)
        assert v == 300, "OFF-семантика прежняя (обратная совместимость)"

    def test_exact_limit_not_overwritten(self):
        cap.reset_cache()
        cap.record_runtime_limit("p", "https://z", "m", None, 500, "chars")
        v = cap.record_runtime_safe_ceiling("p", "https://z", "m", None, 900,
                                            only_raise=True)
        assert v == 500, "published/runtime exact сильнее learned ceiling"
