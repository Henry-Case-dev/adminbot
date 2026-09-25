"""S8 round1026 (`summary-analytics-adapter-round1026`, ADR-1026-10 D1–D10) —
backend-нормализация карты вызовов Саммари (§23–§25/§30/§111/§112).

Покрытие (T-3413…T-3427; S6/T-3446/T-3450 — перепрофилирование publish):
  * маппинг реальных этапов → ``kind`` (§111/D2) и правило «нет данных → нет
    узла» (§24/§25/§30);
  * ``algorithm``/``format``/``publish`` — только реальные метрики/поля, БЕЗ
    выдуманных LLM-токенов (§24); publish — из снапшота (S6/D6), нет данных →
    узла нет;
  * §112 честен: неизвестная стоимость → ``None`` («Нет данных»), никогда
    ``$0``; ``publication_status`` — реальный (``published_rich``/
    ``published_text``/``failed``/``skipped``), нет данных → ``None``
    (не ``gated``);
  * R17: узлы/снапшот не содержат промптов/сырых текстов/ключей;
  * инварианты: Δ DDL=0, Δ каталога=0, 2-вызовность, publish-путь вне diff
    (`telegram_send.py`/`summary_test_run.py` и т.д.).

Автор: @Builder (S8, Step 4; S6-перепрофилирование — S6 Step 4).
"""
import re
import subprocess
from pathlib import Path

import pytest

from services import execution_graph_source as egs
from web.api import analytics as analytics_mod

_ROOT = Path(__file__).resolve().parent.parent
_SOURCE = (_ROOT / "services" / "execution_graph_source.py").read_text(
    encoding="utf-8")
_ANALYTICS = (_ROOT / "web" / "api" / "analytics.py").read_text(encoding="utf-8")
_SETTINGS = (_ROOT / "config" / "settings.py").read_text(encoding="utf-8")
_INDEX = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_store():
    egs.reset()
    yield
    egs.reset()


# ── D2/§111: маппинг реальных этапов → kind ────────────────────────────────

class TestStepKindMapping:
    def test_real_stages_mapped(self):
        assert egs.STEP_KIND["filter"] == "algorithm"
        assert egs.STEP_KIND["l1_clusterizer"] == "llm"
        assert egs.STEP_KIND["l2_writer"] == "llm"
        assert egs.STEP_KIND["formatting"] == "format"
        assert egs.STEP_KIND["format"] == "format"
        # S6 (D6): publication — publish (узел строится из снапшота).
        assert egs.STEP_KIND["publication"] == "publish"

    def test_no_real_stage_falls_into_other(self):
        for step in ("filter", "l1_clusterizer", "l2_writer", "formatting"):
            assert egs.STEP_KIND.get(step) != egs.KIND_OTHER

    def test_stage_order_is_pipeline_order(self):
        # S6 (D6): публикация — после форматирования.
        assert egs.STAGE_ORDER == (
            "filter", "l1_clusterizer", "l2_writer", "formatting",
            "publication")


# ── D2/§24: узлы только из реальных данных ─────────────────────────────────

class TestAlgorithmNode:
    def test_real_filter_metrics(self):
        node = egs.algorithm_node("r1", {
            "source_count": 10, "saved_count": 7, "restored_count": 2,
            "drop_percent": 30.0, "filter_status": "ok",
            "filter_duration_ms": 12.5,
        })
        assert node is not None
        assert node["kind"] == "algorithm"
        assert node["stageKey"] == "filter"
        assert node["status"] == "ok"
        assert node["durationMs"] == 12.5
        assert node["metrics"] == {
            "source_count": 10, "saved_count": 7, "restored_count": 2,
            "drop_percent": 30.0, "status": "ok"}
        # §24: никаких LLM-токенов/стоимости для algorithm.
        assert node["inputTokens"] is None
        assert node["outputTokens"] is None
        assert node["cost"] is None
        assert node["priceKnown"] is False

    def test_no_data_no_node(self):
        # Нет данных этапа → узла нет (§24/§25/§30), заглушка не подставляется.
        assert egs.algorithm_node("r1", {}) is None
        assert egs.algorithm_node("r1", None) is None
        assert egs.algorithm_node("r1", {"threads": 3}) is None


class TestFormatNode:
    def test_real_format_metrics(self):
        node = egs.format_node("r1", {
            "format_channel": "rich", "format_status": "ok",
            "format_duration_ms": 5.0, "paragraphs": 4})
        assert node is not None
        assert node["kind"] == "format"
        assert node["stageKey"] == "formatting"
        assert node["metrics"] == {"channel": "rich", "paragraphs": 4,
                                   "status": "ok"}
        assert node["inputTokens"] is None
        assert node["cost"] is None

    def test_no_data_no_node(self):
        assert egs.format_node("r1", {}) is None
        assert egs.format_node("r1", None) is None


class TestPublishNode:
    """S6 (ADR-1026-11 D6): publish-узел — только из реальных данных снапшота."""

    def test_real_publish_data_builds_node(self):
        node = egs.publish_node("r1", {
            "publish_channel": "rich", "publish_status": "ok",
            "publish_duration_ms": 8.0, "publish_message_id": 42})
        assert node is not None
        assert node["kind"] == "publish"
        assert node["stageKey"] == "publication"
        assert node["status"] == "ok"
        assert node["durationMs"] == 8.0
        assert node["metrics"] == {"channel": "rich", "message_id": 42,
                                   "status": "ok"}
        # §24: без LLM-токенов/стоимости.
        assert node["inputTokens"] is None
        assert node["cost"] is None
        assert node["priceKnown"] is False

    def test_no_data_no_node(self):
        assert egs.publish_node("r1", {}) is None
        assert egs.publish_node("r1", None) is None
        assert egs.publish_node("r1", {"status": "ok"}) is None

    def test_publication_status_mapping(self):
        assert egs.publication_status_of(
            {"publish_channel": "rich", "publish_status": "ok"}) == \
            "published_rich"
        assert egs.publication_status_of(
            {"publish_channel": "text", "publish_status": "ok"}) == \
            "published_text"
        assert egs.publication_status_of(
            {"publish_status": "failed"}) == "failed"
        assert egs.publication_status_of(
            {"status": "degraded"}) == "skipped"
        assert egs.publication_status_of(
            {"status": "failed"}) == "skipped"
        # Нет данных → None (не `gated`, не выдуманное «опубликовано»).
        assert egs.publication_status_of({}) is None
        assert egs.publication_status_of(None) is None

    def test_graph_order_and_link_after_formatting(self):
        snap = {"format_channel": "rich", "format_status": "ok",
                "format_duration_ms": 5.0, "paragraphs": 2,
                "publish_channel": "rich", "publish_status": "ok",
                "publish_duration_ms": 3.0, "publish_message_id": 7,
                "status": "ok"}
        graph = egs.build_graph("r1", snap, [])
        assert [n["stageKey"] for n in graph["nodes"]] == [
            "formatting", "publication"]
        assert graph["nodes"][1]["parentIds"] == ["r1:formatting"]
        assert graph["publication_status"] == "published_rich"
        assert graph["metrics"]["publication_status"] == "published_rich"


class TestLlmNode:
    def test_honest_cost_known(self):
        node = egs.llm_node("r1", {
            "step": "l1_clusterizer", "module": "summary", "model": "m1",
            "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.001,
            "price_known": True, "tokens_estimated": False, "ts": "t"})
        assert node["kind"] == "llm"
        assert node["model"] == "m1"
        assert node["cost"] == 0.001
        assert node["costCurrency"] == "USD"
        assert node["priceKnown"] is True
        assert node["status"] == "unknown"      # в данных нет статуса

    def test_unknown_price_never_zero(self):
        node = egs.llm_node("r1", {
            "step": "l1_clusterizer", "cost_usd": 0, "price_known": False})
        assert node["cost"] is None, "$0 запрещён при неизвестной цене (§112)"
        assert node["costCurrency"] is None

    def test_publish_row_not_llm_node(self):
        # S6/D6: publication — не LLM-событие; строка llm_usage_events не
        # создаёт узел (publish-узел строится отдельно из снапшота).
        assert egs.llm_node("r1", {"step": "publication",
                                   "price_known": True}) is None

    def test_empty_step_no_node(self):
        assert egs.llm_node("r1", {"step": ""}) is None
        assert egs.llm_node("r1", None) is None


# ── D6/§25: линейная последовательность одного run_id ─────────────────────

class TestBuildGraph:
    def test_order_and_linear_links(self):
        snap = {"source_count": 10, "saved_count": 7, "restored_count": 2,
                "drop_percent": 30.0, "filter_status": "ok",
                "filter_duration_ms": 12.0, "format_channel": "rich",
                "format_status": "ok", "format_duration_ms": 5.0,
                "paragraphs": 4, "threads": 3, "cover_status": "ok",
                "status": "ok", "duration_ms": 900.0}
        rows = [
            {"step": "l2_writer", "model": "m", "input_tokens": 2,
             "output_tokens": 3, "cost_usd": 0.002, "price_known": True},
            {"step": "l1_clusterizer", "model": "m", "input_tokens": 1,
             "output_tokens": 1, "cost_usd": 0.001, "price_known": True},
        ]
        graph = egs.build_graph("r1", snap, rows)
        assert [n["stageKey"] for n in graph["nodes"]] == [
            "filter", "l1_clusterizer", "l2_writer", "formatting"]
        assert graph["nodes"][0]["parentIds"] == []
        assert graph["nodes"][1]["parentIds"] == ["r1:filter"]
        assert graph["nodes"][3]["parentIds"] == ["r1:l2_writer"]
        assert len(graph["edges"]) == 3
        assert graph["empty"] is False

    def test_no_data_empty_graph(self):
        graph = egs.build_graph("r1", None, [])
        assert graph["empty"] is True
        assert graph["nodes"] == []
        assert graph["edges"] == []
        # S6/D6: нет снапшота → «Нет данных» (None), не `gated`.
        assert graph["publication_status"] is None

    def test_gap_does_not_glue_distant_stages(self):
        # Нет filter → L1 становится первым (parentIds=[]) и не «склеивается»
        # с отсутствующим этапом (§25/D6).
        rows = [{"step": "l1_clusterizer", "price_known": False}]
        graph = egs.build_graph("r1", {}, rows)
        assert [n["stageKey"] for n in graph["nodes"]] == ["l1_clusterizer"]
        assert graph["nodes"][0]["parentIds"] == []


# ── §112/D4: честные метрики ───────────────────────────────────────────────

class TestMetricsBlock:
    def test_full_list_and_publication_none(self):
        snap = {"source_count": 10, "saved_count": 7, "restored_count": 2,
                "drop_percent": 30.0, "threads": 3, "cover_status": "ok",
                "status": "ok", "duration_ms": 900.0}
        rows = [
            {"step": "l1_clusterizer", "input_tokens": 1, "output_tokens": 2,
             "cost_usd": 0.001, "price_known": True},
            {"step": "l2_writer", "input_tokens": 3, "output_tokens": 4,
             "cost_usd": 0.002, "price_known": True},
        ]
        m = egs.metrics_block(snap, rows)
        assert m["source_count"] == 10
        assert m["filtered_count"] == 7
        assert m["restored_count"] == 2
        assert m["drop_percent"] == 30.0
        assert m["threads_count"] == 3
        assert m["tokens"]["l1"]["input_tokens"] == 1
        assert m["cost"]["l1"] == 0.001
        assert m["cost"]["total"] == 0.003
        assert m["cover_status"] == "ok"
        # S6/D6: данных публикации нет → None («Нет данных»), не `gated`.
        assert m["publication_status"] is None
        # С реальными данными публикации — реальный статус.
        snap2 = dict(snap, publish_channel="text", publish_status="ok")
        assert egs.metrics_block(snap2, rows)["publication_status"] == \
            "published_text"

    def test_unknown_cost_no_fake_zero(self):
        m = egs.metrics_block({"source_count": 1}, [
            {"step": "l1_clusterizer", "cost_usd": 0, "price_known": False}])
        assert m["cost"]["l1"] is None
        assert m["cost"]["total"] is None, "неизвестная цена → «Нет данных»"

    def test_total_requires_both_steps(self):
        # Только L1 → общая стоимость не выдумывается (нет L2).
        m = egs.metrics_block({}, [
            {"step": "l1_clusterizer", "cost_usd": 0.001, "price_known": True}])
        assert m["cost"]["total"] is None
        assert m["tokens"]["total"]["price_known"] is False


# ── D7: in-memory реестр (Δ DDL=0) ─────────────────────────────────────────

class TestRegistry:
    def test_record_get_latest(self):
        egs.record_run(run_id="r1", source_count=1, status="ok")
        egs.record_run(run_id="r2", source_count=2, status="ok")
        assert egs.latest_run_id() == "r2"
        assert egs.get_run("r1")["source_count"] == 1
        assert egs.get_run("nope") is None
        assert egs.store_size() == 2

    def test_bounded(self):
        store = egs.RunSnapshotStore(maxlen=2)
        store.put("a", {"run_id": "a"})
        store.put("b", {"run_id": "b"})
        store.put("c", {"run_id": "c"})
        assert store.size() == 2
        assert store.get("a") is None

    def test_record_ignores_unknown_keys(self):
        # R17: неизвестные (потенциально чувствительные) ключи не сохраняются.
        egs.record_run(run_id="r1", source_count=1,
                       prompt="СЕКРЕТНЫЙ ПРОМПТ", raw_text="сырой текст")
        snap = egs.get_run("r1")
        assert "prompt" not in snap
        assert "raw_text" not in snap

    def test_record_run_from_context_duck_typed(self):
        class _Ctx:
            run_id = "r1"
            chat_id = 1
            mode = "hybrid_l2"
            source_count = 5
            saved_count = 4
            restored_count = 1
            threads = 2
            paragraphs = 3
            cover_status = "ok"
            status = "ok"
            format_channel = "rich"
            format_status = "ok"
            format_duration_ms = 1.0
            drop_percent = None
            filter_status = None
            filter_duration_ms = None

            def duration_ms(self):
                return 10.0

        egs.record_run_from_context(_Ctx(), {"run_id": "r1",
                                             "drop_percent": 20.0,
                                             "status": "ok",
                                             "duration_ms": 5.0})
        snap = egs.get_run("r1")
        assert snap["drop_percent"] == 20.0
        assert snap["filter_status"] == "ok"
        assert snap["duration_ms"] == 10.0

    def test_record_run_from_context_ignores_stale_metrics(self):
        class _Ctx:
            run_id = "r1"
            chat_id = 1
            mode = "off"
            source_count = 5
            saved_count = None
            restored_count = None
            threads = None
            paragraphs = None
            cover_status = None
            status = "ok"
            format_channel = None
            format_status = None
            format_duration_ms = None

            def duration_ms(self):
                return 1.0

        # Метрики другого прогона не подмешиваются (fail-open слот).
        egs.record_run_from_context(_Ctx(), {"run_id": "OTHER",
                                             "drop_percent": 99.0,
                                             "status": "error"})
        snap = egs.get_run("r1")
        assert snap["drop_percent"] is None
        assert snap["filter_status"] is None


# ── R17: никаких секретов/сырых текстов в узлах/снапшоте ───────────────────

class TestR17:
    def test_node_has_no_raw_text_fields(self):
        node = egs.llm_node("r1", {
            "step": "l1_clusterizer", "model": "m", "module": "summary",
            "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.1,
            "price_known": True, "tool_name": "t", "source": "global"})
        flat = str(node).lower()
        for forbidden in ("prompt", "response", "secret", "api_key",
                          "authorization"):
            assert forbidden not in flat, f"утечка R17: {forbidden}"
        assert set(node["metadata"]) == {"tokensEstimated", "module",
                                         "source", "toolName"}

    def test_publish_activated_no_gated_claims(self):
        # S6 (D6/AMEND ADR-1026-10 D1/D4/D8): publish активирован; в analytics
        # (только docstring) и модуле источника нет утверждений «GATED».
        assert "gated" not in _ANALYTICS.lower()
        assert egs.PUBLISHED_RICH == "published_rich"
        assert egs.PUBLISHED_TEXT == "published_text"
        assert egs.PUBLICATION_FAILED == "failed"
        assert egs.PUBLICATION_SKIPPED == "skipped"
        assert not hasattr(egs, "PUBLICATION_STATUS_GATED")


# ── Инварианты D7/D10: Δ DDL=0, Δ каталога=0, 2-вызовность, publish вне diff ─

class TestInvariants:
    def test_no_ddl_in_s8_source(self):
        assert not re.search(r"\b(CREATE\s+TABLE|ALTER\s+TABLE|CREATE\s+INDEX)",
                             _SOURCE, re.IGNORECASE), "Δ DDL=0 (D7)"

    def test_no_new_catalog_flag(self):
        # Δ каталога=0 / новый флаг не вводится (D7): env-only ClassVar нет.
        assert "SUMMARY_EXECUTION_GRAPH_ENABLED" not in _SETTINGS
        assert "param_catalog" not in _SOURCE

    def test_no_llm_calls_in_s8_source(self):
        # 2-вызовность (D10): S8 — read-only, 0 новых LLM-вызовов.
        for marker in ("run_l1", "run_l2", "llm_generate", "usage_events.record",
                       "generate_image"):
            assert marker not in _SOURCE, f"неожиданный вызов: {marker}"

    def test_single_visualization_and_no_rewrite(self):
        assert _INDEX.count('class="token-flow mb-3"') == 1, "одна карта (§111)"
        # GraphViewer/NodeCard/DetailPanel не переписываются (§30) — маркеры живы.
        assert "token-flow__node" in _INDEX
        assert "exec-detail-backdrop" in _INDEX


def _git_diff_names(base: str, paths: list):
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base, "--", *paths],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=30)
    except Exception:      # pragma: no cover - git недоступен
        return None
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


class TestBoundaries:
    """T-3427/T-3425: публикация/§110-viewer/S9/routes.py/param_catalog/db — вне diff."""

    _FORBIDDEN = [
        "services/telegram_send.py", "services/summary_xml.py",
        # NOTE (A3, ADR-1026-16 D2/D6): `services/image_generation.py`
        # исключён из запрета — A3 санкционирует аддитивный ImageRequest-
        # контракт/раннер; §104-гейт генератора ведёт линза A3
        # (tests/test_unified_image_request_round1026.py, AST-эквивалентность).
        "web/api/routes.py",
        # NOTE (A5, ADR-1026-17 D9): `services/param_catalog.py` исключён из
        # запрета — A5 санкционирует Δ каталога +1 ParamSpec
        # `limits.image_daily_limit` +1 GroupSpec `limits_images` (470/427/445/
        # 101/99/21). Δ DDL/§104/канон проверяются своими гейтами A5.
        "db",
        "services/summary_test_run.py",
    ]

    def test_forbidden_paths_outside_diff(self):
        changed = _git_diff_names("pre-round1026-s8", self._FORBIDDEN)
        if changed is None:
            pytest.skip("git/базовый тег недоступны — diff-аудит пропущен")
        assert changed == [], f"запрещённые пути изменены: {changed}"


class TestContextLimit:
    def test_unlimited_sentinel(self, monkeypatch):
        from services import hot_config
        monkeypatch.setattr(hot_config, "get",
                            lambda key, default=None: -1)
        info = analytics_mod._context_limit_info()
        assert info["unlimited"] is True
        assert info["display"] == "Без лимита"

    def test_cap_not_unlimited(self, monkeypatch):
        from services import hot_config
        monkeypatch.setattr(hot_config, "get",
                            lambda key, default=None: 30000)
        info = analytics_mod._context_limit_info()
        assert info["unlimited"] is False
