"""S9 round1026 (ADR-1026-8 D2/D3/D5) — dry-run тест-контур «Тестирование» (§113).

Покрытие (spec §9, SC-01…SC-13; задачи T-3348…T-3371):
  * SC-04/SC-12 — dry-run инварианты: 0 публикаций / 0 изменений памяти /
    0 `generate_image`; `await_count==2`; глобальный `SUMMARY_HYBRID_L2_ENABLED`
    (с S10 default ON) не читается/не меняется; OFF-путь живого пайплайна
    не вызывается;
  * SC-05 — полнота артефактов §113 (source/filtered/clusters/package/article/
    rich/plain) реальными объектами S1–S5;
  * SC-06 — пустое окно → `empty`/`TEST_WINDOW_EMPTY`, LLM не вызывается;
  * SC-07/SC-08 — fail-closed L1/L2/LLM (`TEST_*`), без публикации/повторов;
  * SC-09 — обложка по умолчанию не генерируется (`not_generated`);
  * SC-10/SC-11 — rich-предпросмотр с `<h1>`; plain (`<b>`-заголовок);
  * SC-13 — метрики §112 + «Нет данных»/«Без лимита»; статус публикации;
  * Δ каталога=0; bump `APP_VERSION`.
"""
import dataclasses
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings as settings_mod
from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services import summary_test_run as str_mod
from services import web_runtime
from services.llm_client import LLMError
from services.summary_fact_package import FactPackageResult
from services.summary_generator import SummaryGenerator
from services.summary_test_run import (
    COVER_NOT_GENERATED,
    NO_DATA,
    PUBLICATION_DRY_RUN,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_SKIPPED,
    TEST_L1_INVALID,
    TEST_LLM_UNAVAILABLE,
    TEST_NO_GENERATOR,
    TEST_PACKAGE_NOT_DELIVERABLE,
    TEST_RUN_FAILED,
    TEST_WINDOW_EMPTY,
    UNLIMITED_LABEL,
    empty_payload,
    error_result,
    present_result,
    resolve_window_hours,
    run_summary_test,
)

ROOT = Path(__file__).resolve().parents[1]

CHAT_ID = 100

L1_JSON = json.dumps({
    "schema_version": 1,
    "threads": [
        {"thread_id": "t1", "topic": "Тема",
         "message_ids": [101],
         "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}]},
    ],
    "unassigned_message_ids": [102],
})

L2_JSON = json.dumps({
    "schema_version": 1,
    "title": "Тестовая статья",
    "paragraphs": [
        {"text": "Первый абзац статьи.", "emphasis": "Первый"},
    ],
})


def _row(db_id, tg_id, text, ts=1000, user_id=1, author="A", reply=None,
         media=None):
    return {"id": db_id, "tg_message_id": tg_id, "text": text,
            "timestamp": ts, "user_id": user_id, "author_name": author,
            "reply_to_id": reply, "media_type": media}


def _rows():
    return [
        _row(1, 101, "Первое сообщение", ts=1000),
        _row(2, 102, "Второе сообщение", ts=1001, user_id=2, author="B"),
    ]


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    async def get_smart_window(self, chat_id, since_ts, limit):
        return list(self._rows)

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return None


class _FakeMemory:
    """Шпион: любая запись в память фиксируется счётчиком (должен быть 0)."""

    def __init__(self, rows):
        self.db = _FakeDb(rows)
        self.writes = 0

    async def compress_and_purge(self, chat_id):
        self.writes += 1

    async def get_window_messages(self, chat_id):
        self.writes += 1
        return []

    async def memorize_facts(self, *args, **kwargs):
        self.writes += 1


def _fake_llm(side_effect):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    return llm


@pytest.fixture(autouse=True)
def _patch_chat_limit(monkeypatch):
    """Резолв per-chat параметров без PG (S1/S2-параметры = дефолт каталога)."""
    from services import summary_generator as sg

    async def _limit(chat_id, key, default=None):
        return default

    monkeypatch.setattr(sg, "_chat_limit", _limit)
    web_runtime.reset_web_runtime()
    yield
    web_runtime.reset_web_runtime()


def _real_generator(rows, llm):
    return SummaryGenerator(memory=_FakeMemory(rows), xml=MagicMock(),
                            llm=llm, bot=None,
                            concurrency_pool=MagicMock())


# ── Dry-run инварианты (SC-04/SC-12) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_happy_path_two_calls_no_side_effects(monkeypatch):
    rows = _rows()
    llm = _fake_llm([L1_JSON, L2_JSON])
    gen = _real_generator(rows, llm)

    # Шпионы на запрещённые точки (0 публикаций / 0 image / OFF-путь).
    from services import telegram_send, image_generation, summary_memory
    send_text = MagicMock()
    send_rich = MagicMock()
    cover_media = MagicMock()
    gen_image = MagicMock()
    monkeypatch.setattr(telegram_send, "send_text", send_text)
    monkeypatch.setattr(telegram_send, "send_rich_message", send_rich)
    monkeypatch.setattr(telegram_send, "build_cover_media", cover_media)
    monkeypatch.setattr(image_generation, "generate_image_verbose", gen_image)
    for name in ("compress_and_purge", "memorize_facts", "remember_user_fact",
                 "memorize_self_reply", "get_window_messages",
                 "_build_running_summary"):
        if hasattr(summary_memory, name):
            monkeypatch.setattr(summary_memory, name, MagicMock())

    hybrid = AsyncMock(side_effect=AssertionError("_hybrid_l2_enabled used"))
    run_hybrid = AsyncMock(side_effect=AssertionError("_run_hybrid_l2 used"))
    monkeypatch.setattr(SummaryGenerator, "_hybrid_l2_enabled", hybrid)
    monkeypatch.setattr(SummaryGenerator, "_run_hybrid_l2", run_hybrid)

    flag_before = settings_mod.settings.SUMMARY_HYBRID_L2_ENABLED
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-happy", pg=None)
    flag_after = settings_mod.settings.SUMMARY_HYBRID_L2_ENABLED

    assert result.status == STATUS_OK
    assert result.dry_run is True
    assert result.publication == {"status": "not_published",
                                  "reason": "dry_run"}
    # ровно 2 физических LLM-вызова (L1 + L2).
    assert llm.generate.await_count == 2
    steps = [c.kwargs.get("step") for c in llm.generate.await_args_list]
    assert steps == ["l1_clusterizer", "l2_writer"]
    # глобальный kill-switch не читается/не меняется (S10: default ON).
    assert flag_before == flag_after is True
    assert hybrid.await_count == 0 and run_hybrid.await_count == 0
    # 0 публикаций / 0 image / 0 памяти.
    send_text.assert_not_called()
    send_rich.assert_not_called()
    cover_media.assert_not_called()
    gen_image.assert_not_called()
    assert gen.memory.writes == 0
    assert gen._filter_metrics  # S1/S2 метрики собраны (read-only)


@pytest.mark.asyncio
async def test_artifacts_completeness_and_previews(monkeypatch):
    rows = _rows()
    llm = _fake_llm([L1_JSON, L2_JSON])
    gen = _real_generator(rows, llm)
    result = await run_summary_test(CHAT_ID, {"hours": 6}, generator=gen,
                                    correlation_id="cid-art", pg=None)
    art = result.artifacts
    for key in ("source", "filtered", "dropped", "restored", "clusters",
                "package", "article", "rich_preview", "plain_preview"):
        assert key in art
    assert art["source"][0]["message_id"] == 101
    assert art["clusters"][0]["topic"] == "Тема"
    assert art["clusters"][0]["facts"][0]["text"] == "Важный факт"
    assert art["package"]["schema_version"] == 1
    assert art["article"]["title"] == "Тестовая статья"
    # SC-10/SC-11: rich с настоящим H1, plain — с <b>-заголовком.
    assert "<h1>Тестовая статья</h1>" in art["rich_preview"]
    assert "<b>Тестовая статья</b>" in art["plain_preview"]
    assert result.metrics["cover_status"] == COVER_NOT_GENERATED
    assert result.metrics["publication_status"] == PUBLICATION_DRY_RUN


@pytest.mark.asyncio
async def test_build_test_rows_reads_window_read_only(monkeypatch):
    rows = _rows()
    gen = _real_generator(rows, _fake_llm([L1_JSON, L2_JSON]))
    info = await gen.build_test_rows(CHAT_ID, since_ts=0, correlation_id="c")
    assert info["source_count"] == 2
    assert info["source"][0]["tg_message_id"] == 101
    # окно читается read-only: память/бегущий конспект не трогаются.
    assert gen.memory.writes == 0


# ── Fail-closed (SC-06/SC-07/SC-08) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_window_no_llm():
    llm = _fake_llm([L1_JSON])
    gen = _real_generator([], llm)
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-empty", pg=None)
    assert result.status == STATUS_EMPTY
    assert result.diagnostics[0]["code"] == TEST_WINDOW_EMPTY
    assert llm.generate.await_count == 0


@pytest.mark.asyncio
async def test_invalid_l1_fail_closed_no_l2():
    llm = _fake_llm(["не json"])
    gen = _real_generator(_rows(), llm)
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-l1bad", pg=None)
    assert result.status == STATUS_INVALID
    assert result.diagnostics[-1]["code"] == TEST_L1_INVALID
    assert llm.generate.await_count == 1  # L2 не вызывается
    assert result.publication["status"] == "not_published"


@pytest.mark.asyncio
async def test_llm_error_maps_to_unavailable():
    llm = _fake_llm([LLMError("boom")])
    gen = _real_generator(_rows(), llm)
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-llm", pg=None)
    assert result.status == STATUS_ERROR
    assert result.diagnostics[-1]["code"] == TEST_LLM_UNAVAILABLE
    assert llm.generate.await_count == 1


@pytest.mark.asyncio
async def test_package_not_deliverable_fail_closed(monkeypatch):
    llm = _fake_llm([L1_JSON, L2_JSON])
    gen = _real_generator(_rows(), llm)
    bad = FactPackageResult(status="empty", package=None, reason="empty",
                            metrics={}, budget={})
    monkeypatch.setattr(str_mod, "build_fact_package", lambda *a, **k: bad)
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-pkg", pg=None)
    assert result.status == STATUS_SKIPPED
    assert result.diagnostics[-1]["code"] == TEST_PACKAGE_NOT_DELIVERABLE
    assert llm.generate.await_count == 1  # L2 не вызывается


@pytest.mark.asyncio
async def test_no_generator_error():
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=None,
                                    correlation_id="cid-nogen", pg=None)
    assert result.status == STATUS_ERROR
    assert result.diagnostics[0]["code"] == TEST_NO_GENERATOR


# ── Метрики §112 (SC-13) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_no_data_without_pg():
    gen = _real_generator(_rows(), _fake_llm([L1_JSON, L2_JSON]))
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-nodata", pg=None)
    assert result.metrics["tokens"]["l1"]["input"] == NO_DATA
    assert result.metrics["cost"]["l1"] == NO_DATA
    assert result.metrics["cost"]["total"] == NO_DATA
    assert result.metrics["budget"]["display"] != ""


@pytest.mark.asyncio
async def test_metrics_unlimited_budget(monkeypatch):
    real_get = str_mod.hot.get

    def fake_get(key, default=None):
        if key == "limits.summary_max_context_tokens":
            return -1
        return real_get(key, default)

    monkeypatch.setattr(str_mod.hot, "get", fake_get)
    gen = _real_generator(_rows(), _fake_llm([L1_JSON, L2_JSON]))
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-unlim", pg=None)
    assert result.metrics["budget"]["display"] == UNLIMITED_LABEL


@pytest.mark.asyncio
async def test_collect_usage_known_and_unknown():
    class _Conn:
        async def fetch(self, sql, corr):
            return [
                {"step": "l1_clusterizer", "in_tokens": 100, "out_tokens": 20,
                 "cost": 0.0001, "price_known": True, "calls": 1},
                {"step": "l2_writer", "in_tokens": 200, "out_tokens": 50,
                 "cost": 0.0, "price_known": False, "calls": 1},
            ]

    class _Pool:
        def acquire(self):
            conn = _Conn()

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    class _Pg:
        pool = _Pool()

    usage = await str_mod._collect_usage(_Pg(), "cid")
    assert usage["l1"]["input_tokens"] == 100
    assert usage["l1"]["cost_usd"] == 0.0001
    assert usage["l2"]["price_known"] is False
    # любая неизвестная цена → total без выдуманного $0.
    assert usage["total"]["cost_usd"] is None


# ── Вход/пагинация ─────────────────────────────────────────────────────────

def test_resolve_window_hours_default_and_clamp(monkeypatch):
    monkeypatch.setattr(str_mod.hot, "get", lambda key, default=None: default)
    assert resolve_window_hours(None) == 6
    assert resolve_window_hours({"hours": 24}) == 24
    assert resolve_window_hours({"hours": 0}) == 1
    assert resolve_window_hours({"hours": 99999}) == 720
    assert resolve_window_hours({"hours": "bad"}) == 6


@pytest.mark.asyncio
async def test_present_result_pagination():
    gen = _real_generator(_rows(), _fake_llm([L1_JSON, L2_JSON]))
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=gen,
                                    correlation_id="cid-page", pg=None)
    page = present_result(result, offset=1, limit=1)
    assert len(page["artifacts"]["source"]) == 1
    assert page["artifacts"]["source"][0]["message_id"] == 102
    assert page["display"]["has_more"] is True


def test_present_result_text_cap(monkeypatch):
    long_row = _row(1, 101, "x" * 3000)
    view = str_mod._message_view(long_row)
    assert len(view["text"]) == str_mod.PER_MESSAGE_CAP
    assert view["truncated"] is True


# ── B-R1026S9-2: контракт-валидность error-ответов (UI не падает) ──────────

_METRIC_KEYS = {
    "source_count", "filtered_count", "restored_count", "drop_percent",
    "filter_status", "threads_count", "facts_count", "tokens", "cost",
    "duration_ms", "budget", "cover_status", "publication_status",
}
_ARTIFACT_KEYS = {
    "source", "filtered", "dropped", "restored", "clusters", "package",
    "article", "rich_preview", "plain_preview",
}


def _assert_contract(payload: dict) -> None:
    """Payload валиден по контракту §4.2/§112: полные metrics/artifacts/display."""
    assert _METRIC_KEYS <= set(payload["metrics"].keys())
    assert _ARTIFACT_KEYS <= set(payload["artifacts"].keys())
    assert payload["metrics"]["tokens"]["l1"]["input"] == NO_DATA
    assert payload["metrics"]["cost"]["total"] == NO_DATA
    assert payload["metrics"]["drop_percent"] is None
    assert payload["metrics"]["budget"]["display"]
    assert payload["artifacts"]["source"] == []
    assert "has_more" in payload["display"]


@pytest.mark.asyncio
async def test_no_generator_error_payload_contract():
    # error-путь TEST_NO_GENERATOR: present_result не роняет UI (§5.3/§7).
    result = await run_summary_test(CHAT_ID, {"hours": 24}, generator=None,
                                    correlation_id="cid-nogen2", pg=None)
    assert result.status == STATUS_ERROR
    _assert_contract(present_result(result))


def test_error_result_has_diagnostics_and_full_structures():
    result = error_result(test_id="cid-run", chat_id=CHAT_ID,
                          window={"hours": 6}, code=TEST_RUN_FAILED)
    assert result.status == STATUS_ERROR
    assert result.diagnostics[0]["code"] == TEST_RUN_FAILED
    _assert_contract(present_result(result))


def test_empty_payload_running_contract():
    # running/edge: entry.result is None → API отдаёт валидный пустой payload.
    payload = empty_payload(test_id="cid-run", status="running", chat_id=CHAT_ID)
    _assert_contract(payload)
    assert payload["status"] == "running"


@pytest.mark.asyncio
async def test_build_test_rows_fail_open_resets_stale_filter_metrics(monkeypatch):
    # L-R1026S9-5: fail-open `_apply_filter` не перезаписывает слот — тест-прогон
    # не должен подтянуть устаревшие метрики предыдущего прогона.
    rows = _rows()
    gen = _real_generator(rows, _fake_llm([L1_JSON, L2_JSON]))
    gen._filter_metrics[CHAT_ID] = {"status": "ok", "restored_count": 99,
                                    "drop_percent": 42.0}

    async def _fail_open(chat_id, src, correlation_id, trigger_message_id):
        return src  # fail-open: слот не пишется

    monkeypatch.setattr(gen, "_apply_filter", _fail_open)
    info = await gen.build_test_rows(CHAT_ID, since_ts=0, correlation_id="c")
    assert info["filter_metrics"] == {}
    assert info["restored_count"] == 0


# ── Δ каталога=0 / bump / границы ──────────────────────────────────────────

def test_catalog_zero_delta():
    assert len(pc.REGISTRY) == 473
    assert len({f.name for f in dataclasses.fields(Settings)}) == 430
    assert len([s for s in pc.REGISTRY.values()
                if s.category is not None]) == 448
    assert len(pc.GROUPS) == 102
    assert len(pc._TAB_BY_GROUP) == 100
    assert len(pc.TAB_RULES) == 21


def test_no_new_env_catalog_key():
    assert "SUMMARY_TEST_UI_ENABLED" not in pc.REGISTRY
    assert "SUMMARY_TEST_UI_ENABLED" not in {
        f.name for f in dataclasses.fields(Settings)}


def test_app_version_bumped():
    assert APP_VERSION == "2.58.31"


def test_forbidden_modules_outside_diff():
    # routes.py вне diff: роутер тест-контура не зарегистрирован в routes.py.
    routes = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
    assert "summary_test" not in routes
    # summary_test_run не тянет публикацию/память/image.
    src = (ROOT / "services/summary_test_run.py").read_text(encoding="utf-8")
    assert "from services.telegram_send" not in src
    assert "from services.image_generation" not in src
    assert "import telegram_send" not in src
    assert "def run_summary_test" in src
    # живой OFF-путь и ON-guard сохранены в генераторе.
    gen = (ROOT / "services/summary_generator.py").read_text(encoding="utf-8")
    assert "_generate_two_call" in gen
    assert "_run_hybrid_l2" in gen
    assert "def build_test_rows" in gen
