"""ASAP-4 волна B (epic `asap-4-embedding-graphrag-cover-runtime`, spec §2
B.1–B.5, ADR-1028-7 D6; T-4415…T-4420) — Cover Style production path.

Покрытие:
  * §36/§37 (T-4415): selection snapshot — единая точка резолва style id на
    run; `COVER_STYLE_SELECTION` до base generation/style edit (R17-safe);
    selection_source chat/global/none; персистентность выбора через
    «рестарт» (§73).
  * §38/§39 (T-4416): единый pipeline для всех текстовых исходов —
    Hybrid happy path (§70) и Level-3 Legacy (§39/§71: medved_press →
    force Legacy → base cover → style stage invoked) — одна публикация,
    ladder styled/base/no_cover.
  * §40–§47 (T-4417/T-4418): resolver test↔prod (один `run_style_job`);
    reference integrity §45 (DB-row/file/MIME/readable + метрики
    reference_count/reference_bytes_total, R17-safe); prompt compilation
    diagnostics §46 (вкл. dropped sections); capability matrix §47;
    profile diagnostics §41 (чек-лист полей без секретов); хвост
    L-ASAP31-4 (budget в dry-run).
  * §42–§45 (T-4419): видимый fail-open — distinct reason codes
    (no_style/profile_missing/disabled/edit_unsupported/connection_missing/
    reference_missing/capability_unknown/not_configured), mca_events
    reason_code без generic-схлопывания, provenance при всех исходах
    (styled|base_fallback|no_cover), issue counter только на реальные
    submissions (прод-факт Q15: 1→2→3 на фейлах — запрещено).
  * Хвосты B.5 (T-4416): L-EXTRA-6 (checkpoint-payload merge), L-EXTRA-7
    (стабильный cover_job_key от run_id), update_reference rowcount→200.
  * OFF-паритет `COVER_STYLE_SNAPSHOT_ENABLED` (spec §8.2, T-4420): OFF —
    бит-в-бит прежний контур (без snapshot/SELECTION/SKIPPED, тихие выходы,
    прежний порядок вызовов и counter'а).

R17: в событиях/логах — только id/числа/enum; ключи/контент не логируются.
"""
import asyncio
import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import cover_style_jobs as j
from services import cover_style_registry as registry
from services import mca_events as me
from services import summary_generator as sg
from services.cover_style_edit import EditResult
from services.image_capabilities import (
    FALSE, TRUE, UNKNOWN, ImageModelCapabilities, PromptLimit,
)
from services.summary_run_log import RunContext

pytestmark = pytest.mark.asap4

CHAT = -100266
RID = "asap4b-run-0001"


# ── fixtures/helpers ────────────────────────────────────────────────────────

def _png(path, size=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * size)
    return str(path)


def _jpg(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8" + b"1" * 32)
    return str(path)


def _profile(**over):
    p = {
        "profile_id": "medved_press", "name": "Медведь Press",
        "origin": "seeded", "pipeline_mode": "generate_then_edit",
        "instruction": "Нормализуй обложку под издательский знак серии.",
        "counter_enabled": True, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True,
        "references": [{"ref_id": "r1", "asset_id": "cas_ref1",
                        "label": "Медведь Press",
                        "description": "издательский знак", "ordering": 0}],
    }
    p.update(over)
    return p


def _caps(**over):
    c = ImageModelCapabilities(
        image_edit=TRUE, max_input_images=3,
        prompt_limit=PromptLimit(value=2000, unit="chars",
                                 source="internal_config"))
    for k, v in over.items():
        setattr(c, k, v)
    return c


class _FakePg:
    """PG-like объект: непустой pool (registry-функции мокаются отдельно)."""

    pool = object()


def _patch_pg(monkeypatch):
    pg = _FakePg()
    monkeypatch.setattr(j, "_pg", lambda: pg)
    return pg


def _patch_profile(monkeypatch, profile):
    async def _get(pg, style_id):
        assert pg is not None
        return profile if style_id == profile["profile_id"] else None

    monkeypatch.setattr(registry, "get_profile_with_refs", _get)


class _ProvenanceSpy:
    def __init__(self):
        self.rows = []

    async def __call__(self, pg, data):
        self.rows.append(data)
        return "covp-1"


def _patch_provenance(monkeypatch):
    spy = _ProvenanceSpy()
    monkeypatch.setattr(registry, "record_provenance", spy)
    return spy


def _patch_issue_counter(monkeypatch):
    calls = {"n": 0}

    async def _resolve(pg, profile_id, run_id):
        calls["n"] += 1
        return calls["n"]

    monkeypatch.setattr(registry, "resolve_issue_number", _resolve)
    return calls


def _asset_map(monkeypatch, mapping):
    """registry.get_asset → mapping[asset_id] (dict|None)."""

    async def _get(pg, asset_id):
        return mapping.get(asset_id)

    monkeypatch.setattr(registry, "get_asset", _get)


def _lines(caplog, needle):
    return [r.getMessage() for r in caplog.records
            if needle in r.getMessage()]


def _flag(monkeypatch, value):
    """Патч `COVER_STYLE_SNAPSHOT_ENABLED` на всех вариантах класса Settings
    (паттерн Wave A S10.18-10): reload в полном сьюте пересоздаёт
    `config.settings.settings`, а сервис-модули (cover_style_jobs) держат
    instance ORIGINAL-класса — патчим и его."""
    import config.settings as _cs
    from config.settings import Settings as _S
    classes = {_S, type(_cs.settings), type(j.settings)}
    for _cls in classes:
        monkeypatch.setattr(_cls, "COVER_STYLE_SNAPSHOT_ENABLED", value,
                            raising=False)


@pytest.fixture(autouse=True)
def _wb_env(monkeypatch):
    """Волна B по умолчанию ON (прод-дефолт); слот — сконфигурированный
    (тесты pre-execution фейлов переопределяют точечно)."""
    _flag(monkeypatch, True)
    # T-4619 (AMEND, волна 6): врезка — resolve_style_slot_inherited
    # (лестница §35); тест патчит её — слот сконфигурированный (async —
    # run_style_job ожидает резолв).
    async def _slot(*, profile, connection, pg=None):
        return {"base_url": "https://edit.example/v1",
                "model": "qwen-image-edit",
                "provider": "edit.example",
                "connection_id": "default",
                "custom_unresolved": False,
                "configured": True}
    monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
    yield


def _gen(monkeypatch, tmp_path, *, edit_result=None, edit_calls=None,
         image=None):
    """SummaryGenerator с замоканной image-генерацией и rich-отправкой."""
    from tests.test_summary_generator import FakeMemory
    from services.summary_xml import XmlGroundingBuilder

    gen = sg.SummaryGenerator(FakeMemory(), XmlGroundingBuilder(),
                              MagicMock(), AsyncMock())
    gen._resolve_cover_style_text = AsyncMock(return_value="cinematic")
    if image is None:
        image = _png(tmp_path / "base_cover.png")
    monkeypatch.setattr(sg, "generate_image_verbose",
                        AsyncMock(return_value=(image, "ok")))
    media_seen = []
    media_bytes = []

    def _media(path):
        media_seen.append(path)
        try:
            with open(path, "rb") as fh:
                media_bytes.append(fh.read())
        except OSError:
            media_bytes.append(None)
        return "M"

    monkeypatch.setattr(sg, "build_cover_media", _media)
    rich = AsyncMock(return_value=SimpleNamespace(message_id=4321))
    monkeypatch.setattr(sg, "send_rich_message", rich)
    monkeypatch.setattr(sg, "send_text",
                        AsyncMock(return_value=SimpleNamespace(message_id=1)))
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)

    state = {"calls": 0}

    async def _edit(prompt, **kw):
        state["calls"] += 1
        if edit_calls is not None:
            edit_calls.append(kw)
        if callable(edit_result):
            return edit_result(state)
        return edit_result or EditResult(ok=True, content=b"STYLED-BYTES",
                                         reason="ok", latency_ms=5)

    monkeypatch.setattr(j, "edit_image", _edit)
    gen._wb_media_seen = media_seen
    gen._wb_media_bytes = media_bytes
    gen._wb_rich = rich
    gen._wb_edit_state = state
    return gen


# ══ §36/§37 (T-4415): selection snapshot + COVER_STYLE_SELECTION ════════════

class TestSelectionSnapshot:
    async def _snapshot(self, monkeypatch, profile=None, style_id="medved_press"):
        monkeypatch.setattr(
            j, "resolve_selected_style_id",
            AsyncMock(return_value=style_id))
        _patch_pg(monkeypatch)
        if profile is not None:
            _patch_profile(monkeypatch, profile)
        return await j.resolve_selection(CHAT)

    @pytest.mark.asyncio
    async def test_snapshot_fields_and_single_resolve(self, monkeypatch,
                                                      caplog):
        """R4-B-001: snapshot с полным набором полей; резолв style id —
        ЕДИНственный на run (запрет трёх резолвов)."""
        profile = _profile(references=[])      # без референсов — focus snapshot
        resolve = AsyncMock(return_value="medved_press")
        monkeypatch.setattr(j, "resolve_selected_style_id", resolve)
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, profile)
        snapshot = await j.selection_stage(CHAT, run_id=RID)
        assert resolve.await_count == 1
        assert snapshot["chat_id"] == CHAT
        assert snapshot["selected_style_id"] == "medved_press"
        assert snapshot["style_revision"] == 1
        assert snapshot["enabled"] is True
        assert snapshot["pipeline_mode"] == "generate_then_edit"
        assert snapshot["selection_source"] in ("chat", "global", "none")
        with caplog.at_level(logging.INFO):
            # Style stage потребляет snapshot БЕЗ повторного резолва.
            gen = SimpleNamespace(memory=SimpleNamespace(db=None))
            meta = await sg.SummaryGenerator._maybe_apply_cover_style(
                gen, CHAT, "base.png", RID, snapshot=snapshot)
        assert resolve.await_count == 1          # второй резолв запрещён
        assert meta is not None and meta["style_id"] == "medved_press"
        if meta.get("styled_path"):
            os.remove(meta["styled_path"])

    @pytest.mark.asyncio
    async def test_selection_event_before_image_api(self, monkeypatch,
                                                    tmp_path, caplog):
        """R4-B-002: SELECTION раньше base generation и style edit
        (для medved_press выбор виден до image API)."""
        order = []
        profile = _profile()
        resolve = AsyncMock(return_value="medved_press")
        monkeypatch.setattr(j, "resolve_selected_style_id", resolve)
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, profile)
        real_stage = j.selection_stage

        async def _stage(chat_id, **kw):
            order.append("selection")
            return await real_stage(chat_id, **kw)

        monkeypatch.setattr(j, "selection_stage", _stage)
        gen = _gen(monkeypatch, tmp_path)

        async def _img(prompt, **kw):
            order.append("image_api")
            return (str(tmp_path / "base_cover.png"), "ok")

        monkeypatch.setattr(sg, "generate_image_verbose", _img)
        with caplog.at_level(logging.INFO):
            await gen._publish_rich_document(
                CHAT, {"schema_version": 1, "title": "Т",
                       "paragraphs": [{"text": "Абзац.", "emphasis": None}]},
                "a lone cat", correlation_id=RID)
        assert order[:2] == ["selection", "image_api"]
        sel = [ln for ln in _lines(caplog, "COVER_STYLE_SELECTION")
               if "medved_press" in ln]
        assert sel and "style_revision=1" in sel[0]

    @pytest.mark.asyncio
    async def test_selection_source_chat_global_none(self, monkeypatch):
        """§36: selection_source = chat (override) | global | none."""
        from services import chat_params as cp
        from services import hot_config as hot

        class _Cache:
            def __init__(self, overrides):
                self._o = overrides

            async def get_chat_params(self, chat_id):
                return {"overrides": self._o}

        KEY = "prompts.summary_cover_style_id"
        monkeypatch.setattr(cp, "get_chat_params_cache",
                            lambda: _Cache({KEY: "medved_press"}))
        assert await j._selection_source(CHAT) == "chat"
        # Нет override'а чата, но глобальное значение задано → global.
        monkeypatch.setattr(cp, "get_chat_params_cache", lambda: _Cache({}))
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: "medved_press"
                            if key == KEY else default)
        assert await j._selection_source(CHAT) == "global"
        # Ни override'а, ни глобального → none.
        monkeypatch.setattr(hot, "get", lambda key, default=None: default)
        assert await j._selection_source(CHAT) == "none"

    @pytest.mark.asyncio
    async def test_selection_persistence_restart_reload(self, monkeypatch):
        """§73 (R4-B-018): выбор персистентен — «рестарт» (новый резолв)
        даёт тот же style/revision; правка профиля (revision++) видна после
        reload, но style_id стабилен."""
        profile = _profile(revision=1)
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value="medved_press"))
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, profile)
        first = await j.resolve_selection(CHAT)
        # «Рестарт»: новый process → тот же выбор из персистентного слоя.
        second = await j.resolve_selection(CHAT)
        assert (second["selected_style_id"], second["style_revision"]) == \
            (first["selected_style_id"], first["style_revision"])
        # Reload после правки владельцем: revision обновляется, выбор живёт.
        _patch_profile(monkeypatch, _profile(revision=2))
        reloaded = await j.resolve_selection(CHAT)
        assert reloaded["selected_style_id"] == "medved_press"
        assert reloaded["style_revision"] == 2

    @pytest.mark.asyncio
    async def test_off_parity_no_snapshot_no_events(self, monkeypatch,
                                                    tmp_path, caplog):
        """Spec §8.2 (T-4420): OFF — бит-в-бит прежний контур: без
        SELECTION/SKIPPED, тихие ранние выходы, события COVER_* как есть."""
        _flag(monkeypatch, False)
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value=""))   # стиль не выбран
        _patch_pg(monkeypatch)
        gen = _gen(monkeypatch, tmp_path)
        with caplog.at_level(logging.INFO):
            published = await gen._publish_rich_document(
                CHAT, {"schema_version": 1, "title": "Т",
                       "paragraphs": [{"text": "Абзац.", "emphasis": None}]},
                "a lone cat", correlation_id=RID)
        assert published is True
        assert not _lines(caplog, "COVER_STYLE_SELECTION")
        assert not _lines(caplog, "COVER_STYLE_SKIPPED")
        assert _lines(caplog, "COVER_PIPELINE_START")   # события как есть
        assert gen._wb_edit_state["calls"] == 0         # edit не вызывался


# ══ §38/§39 (T-4416): единый pipeline + ladder (§70/§71/§72) ════════════════

class TestUnifiedPipeline:
    async def _run_publication(self, monkeypatch, tmp_path, caplog, *,
                               profile=None, edit_result=None):
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value="medved_press"))
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, profile or _profile())
        ref = _png(tmp_path / "medved_ref.png")
        _asset_map(monkeypatch, {"cas_ref1": {
            "asset_id": "cas_ref1", "disk_path": ref, "mime": "image/png"}})
        prov = _patch_provenance(monkeypatch)
        counter = _patch_issue_counter(monkeypatch)
        gen = _gen(monkeypatch, tmp_path, edit_result=edit_result)
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Первый абзац.", "emphasis": None}]}
        with caplog.at_level(logging.INFO):
            published = await gen._publish_rich_document(
                CHAT, doc, "a lone cat", correlation_id=RID)
        return published, prov, counter, gen

    @pytest.mark.asyncio
    async def test_hybrid_happy_path_styled(self, monkeypatch, tmp_path,
                                            caplog):
        """§70 (R4-B-015): style на Hybrid happy path → edit вызван, финал —
        styled asset, provenance styled, публикация rich."""
        published, prov, counter, gen = await self._run_publication(
            monkeypatch, tmp_path, caplog)
        assert published is True
        assert gen._wb_edit_state["calls"] == 1
        assert len(gen._wb_media_seen) == 1
        assert gen._wb_media_seen[0].endswith(".jpg")
        assert gen._wb_media_bytes[0] == b"STYLED-BYTES"   # styled, не base
        assert _lines(caplog, "COVER_STYLE_SUCCEEDED")
        styled = [r for r in prov.rows if r.get("status") == "styled"]
        assert styled and styled[0]["style_id"] == "medved_press"
        assert styled[0]["issue_number"] == 1   # counter потрачен на submission
        assert counter["n"] == 1

    @pytest.mark.asyncio
    async def test_legacy_fallback_style_invoked_regression_39(
            self, monkeypatch, tmp_path, caplog):
        """§39/§71 (R4-B-004): selected medved_press → force Legacy →
        Legacy article → base cover → style stage ВЫЗВАН (владелец §39/§71).
        Legacy-доставка идёт через то же ядро `_publish_rich_document`."""
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value="medved_press"))
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, _profile())
        ref = _png(tmp_path / "medved_ref.png")
        _asset_map(monkeypatch, {"cas_ref1": {
            "asset_id": "cas_ref1", "disk_path": ref, "mime": "image/png"}})
        _patch_provenance(monkeypatch)
        _patch_issue_counter(monkeypatch)
        gen = _gen(monkeypatch, tmp_path)
        with caplog.at_level(logging.INFO):
            published = await gen._deliver_rich(
                CHAT, "Наследиеlegacy-статья. Второй абзац.", "a lone cat",
                correlation_id=RID, title="Событие")
        assert published is True
        assert gen._wb_edit_state["calls"] == 1
        assert _lines(caplog, "COVER_STYLE_START")
        assert _lines(caplog, "COVER_STYLE_SUCCEEDED")
        assert gen._wb_media_bytes[0] == b"STYLED-BYTES"   # styled финал

    @pytest.mark.asyncio
    async def test_provider_failure_base_fallback_visible_reason(
            self, monkeypatch, tmp_path, caplog):
        """§72 (R4-B-017): provider failure → base cover fallback, причина
        видна, provenance=base_fallback, следующий run снова пробует style."""
        published, prov, counter, gen = await self._run_publication(
            monkeypatch, tmp_path, caplog,
            edit_result=EditResult(ok=False, reason="timeout",
                                   latency_ms=10))
        assert published is True                       # fail-open
        assert len(gen._wb_media_seen) == 1
        assert gen._wb_media_seen[0].endswith(".png")  # base, не styled
        failed = _lines(caplog, "COVER_STYLE_FAILED")
        assert failed and "reason=timeout" in failed[0]
        base_rows = [r for r in prov.rows if r.get("status") == "base"]
        assert base_rows and base_rows[0]["fallback_mode"] == "style_failed"
        assert base_rows[0]["issue_number"] == 1       # submission был
        assert counter["n"] == 1
        # Следующий run: style снова пробуется (не отключается навсегда).
        caplog.clear()
        published2, prov2, _counter2, gen2 = await self._run_publication(
            monkeypatch, tmp_path, caplog)
        assert published2 is True
        assert gen2._wb_edit_state["calls"] == 1       # повторная попытка
        assert [r for r in prov2.rows if r.get("status") == "styled"]
        assert gen2._wb_media_bytes[0] == b"STYLED-BYTES"

    @pytest.mark.asyncio
    async def test_no_cover_provenance_on_base_failure(self, monkeypatch,
                                                       tmp_path, caplog):
        """§44: base generation failed → provenance `no_cover` (не молча)."""
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value="medved_press"))
        pg = _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, _profile())
        prov = _patch_provenance(monkeypatch)
        counter = _patch_issue_counter(monkeypatch)
        gen = _gen(monkeypatch, tmp_path)
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(None, "no_key")))
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Абзац.", "emphasis": None}]}
        with caplog.at_level(logging.INFO):
            await gen._publish_rich_document(
                CHAT, doc, "a lone cat", correlation_id=RID)
        none_rows = [r for r in prov.rows if r.get("status") == "none"]
        assert none_rows and none_rows[0]["style_id"] == "medved_press"
        assert gen._wb_edit_state["calls"] == 0        # style не вызывался
        assert counter["n"] == 0                       # submission не было
        assert pg is not None


# ══ §42–§45 (T-4419): видимый fail-open — distinct reasons ══════════════════

class TestVisibleFailOpen:
    async def _apply(self, monkeypatch, snapshot):
        gen = SimpleNamespace(memory=SimpleNamespace(db=None))
        return await sg.SummaryGenerator._maybe_apply_cover_style(
            gen, CHAT, "base.png", RID, snapshot=snapshot)

    @pytest.mark.asyncio
    async def test_skip_no_style_info_event(self, monkeypatch, caplog):
        snapshot = {"chat_id": CHAT, "selected_style_id": None,
                    "style_revision": None, "selection_source": "none",
                    "enabled": False, "pipeline_mode": "none"}
        with caplog.at_level(logging.INFO):
            meta = await self._apply(monkeypatch, snapshot)
        assert meta is None
        skipped = _lines(caplog, "COVER_STYLE_SKIPPED")
        assert skipped and "reason=no_style" in skipped[0]

    @pytest.mark.asyncio
    async def test_skip_profile_missing_warning_and_provenance(
            self, monkeypatch, caplog):
        """R4-B-007/009: выбранный стиль потерян (профиль удалён) —
        WARNING + provenance base_fallback; counter не расходуется."""
        _patch_pg(monkeypatch)
        prov = _patch_provenance(monkeypatch)
        counter = _patch_issue_counter(monkeypatch)
        snapshot = {"chat_id": CHAT, "selected_style_id": "gone_style",
                    "style_revision": None, "selection_source": "chat",
                    "enabled": False, "pipeline_mode": "none", "_profile": None}
        with caplog.at_level(logging.INFO):
            meta = await self._apply(monkeypatch, snapshot)
        assert meta is None
        skipped = _lines(caplog, "COVER_STYLE_SKIPPED")
        assert skipped and "reason=profile_missing" in skipped[0]
        rows = [r for r in prov.rows if r.get("fallback_mode")
                == "profile_missing"]
        assert rows and rows[0]["status"] == "base"
        assert rows[0]["issue_number"] is None         # counter не тронут
        assert counter["n"] == 0
        human = [ln for ln in caplog.records if "style not applied" in
                 ln.getMessage()]
        assert human and "profile_missing" in human[0].getMessage()

    @pytest.mark.asyncio
    async def test_skip_disabled_warning(self, monkeypatch, caplog):
        _patch_pg(monkeypatch)
        _patch_provenance(monkeypatch)
        snapshot = {"chat_id": CHAT, "selected_style_id": "medved_press",
                    "style_revision": 3, "selection_source": "chat",
                    "enabled": False, "pipeline_mode": "generate_then_edit",
                    "_profile": _profile(enabled=False)}
        with caplog.at_level(logging.INFO):
            meta = await self._apply(monkeypatch, snapshot)
        assert meta is None
        skipped = _lines(caplog, "COVER_STYLE_SKIPPED")
        assert skipped and "reason=disabled" in skipped[0]

    @pytest.mark.asyncio
    async def test_not_configured_no_counter_no_submitted(
            self, monkeypatch, tmp_path, caplog):
        """§B.5 (прод-факт Q15): pre-execution `not_configured` — counter
        НЕ расходуется, SUBMITTED (real submission) не эмитится."""
        async def _slot(*, profile, connection, pg=None):
            return {"base_url": "", "model": "", "provider": "",
                    "connection_id": "default", "custom_unresolved": False,
                    "configured": False}
        monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
        base = _png(tmp_path / "b.png")
        counter = _patch_issue_counter(monkeypatch)
        with caplog.at_level(logging.INFO):
            meta = await j.run_style_job(
                chat_id=CHAT, base_image_path=base, profile=_profile(),
                summary_run_id=RID, capabilities=_caps(), edit_call=AsyncMock(),
                reference_paths=[])
        assert meta["fail_reason"] == "not_configured"
        assert meta["applied"] is False
        assert counter["n"] == 0
        assert not _lines(caplog, "COVER_STYLE_SUBMITTED")
        failed = _lines(caplog, "COVER_STYLE_FAILED")
        assert failed and "reason=not_configured" in failed[0]
        # mca-причина не схлопывается: style_reason_code честный.
        assert j.style_reason_code("not_configured") == "not_configured"

    @pytest.mark.asyncio
    async def test_connection_missing_exit(self, monkeypatch, tmp_path,
                                           caplog):
        """§40/B.4: профиль указывает на подключение, записи которого нет —
        ранний выход `connection_missing` (default-слот молча не
        подставляется, edit не уходит «не туда»)."""
        async def _no_connection(pg, connection_id):
            return None

        monkeypatch.setattr(registry, "get_connection", _no_connection)
        async def _slot(*, profile, connection, pg=None):
            return {"base_url": "https://d.example/v1",
                    "model": "m", "provider": "d.example",
                    "connection_id": "default",
                    "custom_unresolved": True,
                    "configured": True}
        monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
        base = _png(tmp_path / "b.png")
        counter = _patch_issue_counter(monkeypatch)
        edit = AsyncMock()
        with caplog.at_level(logging.INFO):
            meta = await j.run_style_job(
                chat_id=CHAT, base_image_path=base,
                profile=_profile(model_mode="custom",
                                 connection_id="csc_missing"),
                summary_run_id=RID, capabilities=_caps(), edit_call=edit,
                reference_paths=[])
        assert meta["fail_reason"] == "connection_missing"
        edit.assert_not_awaited()
        assert counter["n"] == 0
        failed = _lines(caplog, "COVER_STYLE_FAILED")
        assert failed and "reason=connection_missing" in failed[0]

    @pytest.mark.asyncio
    async def test_reference_missing_exit(self, monkeypatch, tmp_path,
                                          caplog):
        """§45: референсы настроены, но ни один не читаем →
        `reference_missing`, edit не вызывается, counter не тратится."""
        _patch_pg(monkeypatch)
        _asset_map(monkeypatch, {"cas_ref1": {
            "asset_id": "cas_ref1", "disk_path": str(tmp_path / "nope.png"),
            "mime": "image/png"}})
        counter = _patch_issue_counter(monkeypatch)
        edit = AsyncMock()
        with caplog.at_level(logging.INFO):
            meta = await j.run_style_job(
                chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
                profile=_profile(), summary_run_id=RID,
                capabilities=_caps(), edit_call=edit)
        assert meta["fail_reason"] == "reference_missing"
        edit.assert_not_awaited()
        assert counter["n"] == 0

    @pytest.mark.asyncio
    async def test_mca_reason_codes_registered(self):
        """§2 B.4: 7 новых причин — в `mca_events.REASON_CODES` (не новый
        словарь); mca-событие несёт конкретную причину, provider-класс
        (`timeout`) остаётся под umbrella `style_failed` в reason_code."""
        for code in ("no_style", "profile_missing", "disabled",
                     "connection_missing", "reference_missing",
                     "capability_unknown", "not_configured"):
            assert code in me.REASON_CODES
        ev = me.build_event("COVER_STYLE_FAILED", outcome="failed",
                            reason_code="not_configured")
        assert ev["reason_code"] == "not_configured"
        ev2 = me.build_event("COVER_STYLE_FAILED", outcome="failed",
                             reason_code="style_failed")
        assert ev2["reason_code"] == "style_failed"
        assert j.style_reason_code("timeout") == "style_failed"
        assert j.style_reason_code("connection_missing") == \
            "connection_missing"

    def test_ru_translations(self):
        """§43: человекочитаемая причина для каждого кода."""
        for reason in ("no_style", "profile_missing", "disabled",
                       "edit_unsupported", "connection_missing",
                       "reference_missing", "capability_unknown",
                       "not_configured"):
            assert j.reason_detail_ru(reason)
        status = j.style_skip_status("not_configured")
        assert status.startswith("Обработка стилем — не выполнена")
        assert "не настроены адрес/модель" in status


# ══ §45/§46/§47/§41 (T-4418): integrity + diagnostics + capability ══════════

class TestReferenceIntegrityAndDiagnostics:
    @pytest.mark.asyncio
    async def test_integrity_metrics_in_edit_request(self, monkeypatch,
                                                     tmp_path, caplog):
        """R4-B-010: edit request реально содержит читаемый референс;
        метрики reference_count/reference_bytes_total — без контента."""
        ref_ok = _png(tmp_path / "ref.png", size=128)
        ref_bad_mime = _jpg(tmp_path / "fake.png")   # jpg-байты под .png
        _patch_pg(monkeypatch)
        _asset_map(monkeypatch, {
            "cas_ref1": {"asset_id": "cas_ref1", "disk_path": ref_ok,
                         "mime": "image/png"},
            "cas_ref2": {"asset_id": "cas_ref2", "disk_path": ref_bad_mime,
                         "mime": "image/png"},          # сигнатура ≠ MIME
        })
        profile = _profile(references=[
            {"ref_id": "r1", "asset_id": "cas_ref1", "label": "logo",
             "description": "знак", "ordering": 0},
            {"ref_id": "r2", "asset_id": "cas_ref2", "label": "broken",
             "description": "битый", "ordering": 1}])
        seen = {}

        async def edit(prompt, **kw):
            seen["reference_paths"] = kw.get("reference_paths")
            return EditResult(ok=True, content=b"S", reason="ok")

        with caplog.at_level(logging.INFO):
            meta = await j.run_style_job(
                chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
                profile=profile, summary_run_id=RID, capabilities=_caps(),
                edit_call=edit)
        assert meta["applied"] is True
        assert seen["reference_paths"] == [ref_ok]     # битый отфильтрован
        details = meta["reference_details"]
        assert details[0]["db_row"] and details[0]["readable"]
        assert details[0]["bytes"] > 0
        assert details[1]["readable"] is False         # MIME-несоответствие
        assert meta["reference_bytes_total"] > 0
        submitted = _lines(caplog, "COVER_STYLE_SUBMITTED")
        assert submitted and "reference_count=1" in submitted[0]
        assert "reference_bytes_total=" in submitted[0]
        # R17: контент референса не логируется.
        assert all("0" * 32 not in ln.getMessage() for ln in caplog.records)

    @pytest.mark.asyncio
    async def test_prompt_diagnostics_dropped_visible(self, monkeypatch,
                                                      tmp_path, caplog):
        """§46 (R4-B-011): diagnostics компиляции — instruction/brief chars,
        issue text, references, compiled chars, limit source; выброшенная по
        cap секция (бренд-инструкция P2) — видна."""
        _patch_pg(monkeypatch)
        profile = _profile(references=[
            {"ref_id": "r1", "asset_id": "cas_ref1", "label": "logo",
             "description": "D" * 400, "ordering": 0}])
        tiny = _caps(prompt_limit=PromptLimit(value=120, unit="chars",
                                              source="internal_config"))
        with caplog.at_level(logging.INFO):
            meta = await j.run_style_job(
                chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
                profile=profile, summary_run_id=RID, capabilities=tiny,
                edit_call=AsyncMock(return_value=EditResult(
                    ok=True, content=b"S", reason="ok")),
                reference_paths=[], summary_text="Герой в лесу. Дальше.",
                base_style_prompt="cinematic")
        diag = meta["prompt_diagnostics"]
        assert diag["instruction_chars"] > 0
        assert diag["brief_chars"] > 0
        assert diag["compiled_chars"] > 0
        assert diag["issue_present"] is True           # «ВЫПУСК N» в промпте
        assert diag["references_count"] == 0
        assert diag["limit_unit"] == "120:chars"
        assert "references" in diag["dropped_sections"]  # P2 выброшен — виден
        submitted = _lines(caplog, "COVER_STYLE_SUBMITTED")
        assert submitted and "brief_chars=" in submitted[0]
        assert "compiled_chars=" in submitted[0]
        assert "issue_present=True" in submitted[0]

    @pytest.mark.asyncio
    async def test_capability_matrix_47(self, monkeypatch, tmp_path):
        """§47: no → edit_unsupported (API не вызывается); unknown → НЕ
        блокирует (§58), но capability_state виден; yes → edit."""
        base = _png(tmp_path / "b.png")

        # no
        meta = await j.run_style_job(
            chat_id=CHAT, base_image_path=base, profile=_profile(),
            summary_run_id=RID, capabilities=_caps(image_edit=FALSE),
            edit_call=AsyncMock(), reference_paths=[])
        assert meta["fail_reason"] == "edit_unsupported"
        assert "не умеет" in meta["message"]

        # unknown — не блокирует, но честно помечен
        meta = await j.run_style_job(
            chat_id=CHAT, base_image_path=base, profile=_profile(),
            summary_run_id=RID, capabilities=_caps(image_edit=UNKNOWN),
            edit_call=AsyncMock(return_value=EditResult(
                ok=True, content=b"S", reason="ok")),
            reference_paths=[])
        assert meta["applied"] is True
        assert meta["capability_state"] == "unknown"
        os.remove(meta["styled_path"])

        # yes
        meta = await j.run_style_job(
            chat_id=CHAT, base_image_path=base, profile=_profile(),
            summary_run_id=RID, capabilities=_caps(image_edit=TRUE),
            edit_call=AsyncMock(return_value=EditResult(
                ok=True, content=b"S", reason="ok")),
            reference_paths=[])
        assert meta["capability_state"] == "yes"
        os.remove(meta["styled_path"])

    @pytest.mark.asyncio
    async def test_profile_diagnostics_checklist_41(self, monkeypatch,
                                                    tmp_path):
        """§41 (R4-B-006): полный чек-лист полей профиля, БЕЗ секретов."""
        ref = _png(tmp_path / "ref.png")
        _patch_pg(monkeypatch)
        _asset_map(monkeypatch, {"cas_ref1": {
            "asset_id": "cas_ref1", "disk_path": ref, "mime": "image/png"}})
        monkeypatch.setattr(j, "slot_capabilities",
                            lambda *, profile, discovery=None,
                            endpoints=None, refresh=False,
                            connection=None: _caps())

        async def _resolved(*, profile, connection=None, pg=None,
                            refresh=False, operation=None):
            slot = {"profile_id": profile.get("profile_id"),
                    "provider": "p", "base_url": "https://x/v1",
                    "model": "m", "connection_id": None,
                    "custom_unresolved": False, "configured": True,
                    "resolve_source": "global_style_slot"}
            return {"slot": slot, "connection": connection,
                    "provider": "p", "base_url": "https://x/v1", "model": "m",
                    "connection_id": None, "configured": True,
                    "custom_unresolved": False,
                    "resolve_source": "global_style_slot",
                    "route": "legacy_images", "operation": "image_edit",
                    "capabilities": _caps()}

        monkeypatch.setattr(j, "resolve_effective_edit_capability",
                            _resolved)
        diag = await j.profile_diagnostics(_FakePg(), _profile())
        for key in ("profile_id", "revision", "enabled", "pipeline_mode",
                    "connection_id", "connection_configured", "provider",
                    "model", "capability_image_edit", "references",
                    "instruction_chars", "counter_enabled", "counter_value"):
            assert key in diag, key
        assert diag["profile_id"] == "medved_press"
        assert diag["capability_image_edit"] == "yes"
        assert diag["references"]["configured"] == 1
        assert diag["references"]["ready"] == 1
        assert diag["references"]["bytes_total"] > 0
        blob = json.dumps(diag, ensure_ascii=False)
        assert "api_key" not in blob and "secret" not in blob

    @pytest.mark.asyncio
    async def test_resolver_unified_test_vs_prod(self, monkeypatch, tmp_path):
        """§40 (R4-B-005): preview и production идут через ОДИН
        `run_style_job` (slot/caps/refs/compiler); различия — только issue
        assignment и mode."""
        base = _png(tmp_path / "b.png")
        _patch_pg(monkeypatch)
        slots = []

        async def _slot(*, profile, connection, pg=None):
            slots.append((profile.get("profile_id"),))
            return {"base_url": "https://edit.example/v1",
                    "model": "qwen-image-edit", "provider": "edit.example",
                    "connection_id": "default", "custom_unresolved": False,
                    "configured": True}

        monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
        counter = _patch_issue_counter(monkeypatch)
        preview = await j.run_style_preview(
            profile=_profile(), base_image_path=base,
            edit_call=AsyncMock(return_value=EditResult(
                ok=True, content=b"S", reason="ok")),
            reference_paths=[], capabilities=_caps())
        prod = await j.run_style_job(
            chat_id=CHAT, base_image_path=base, profile=_profile(),
            summary_run_id=RID,
            edit_call=AsyncMock(return_value=EditResult(
                ok=True, content=b"S", reason="ok")),
            reference_paths=[], capabilities=_caps())
        assert len(slots) == 2 and slots[0] == slots[1]
        assert preview["mode"] == "preview"
        assert preview["issue_number"] is None      # preview counter не тратит
        assert prod["issue_number"] == 1
        assert counter["n"] == 1
        assert preview["style_id"] == prod["style_id"]
        os.remove(preview["styled_path"])
        os.remove(prod["styled_path"])


# ══ Хвосты B.5 (T-4416): L-EXTRA-6/7 + rowcount→200 ═════════════════════════

class TestTailsB5:
    @pytest.mark.asyncio
    async def test_checkpoint_payload_merge_lextra6(self, tmp_path):
        """L-EXTRA-6: `save_checkpoint` вливает cursor/processed в payload,
        не затирая identity-поля (chat_id/correlation_id/style_id)."""
        from services.database import DatabaseService
        from services.task_supervisor import TaskJobStore

        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            store = TaskJobStore(db)
            jid = await store.enqueue(
                owner="summary", kind="cover_style",
                coalesce_key="cover_style:run-m",
                payload=json.dumps({"chat_id": CHAT,
                                    "correlation_id": "run-m",
                                    "style_id": "medved_press"},
                                   ensure_ascii=False),
                job_id="cov_merge1")
            assert await store.save_checkpoint(
                jid, cursor_token="STYLE_RUNNING", processed=2) is True
            row = await store.get(jid)
            payload = json.loads(row["payload"])
            assert payload["chat_id"] == CHAT              # merge, не overwrite
            assert payload["style_id"] == "medved_press"
            assert payload["cursor"] == "STYLE_RUNNING"
            assert payload["processed"] == 2
            cp = await store.get_checkpoint(jid)
            assert cp["cursor"] == "STYLE_RUNNING"
            # Битый payload → прежнее поведение (checkpoint-only).
            await db.db.execute(
                "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
                ("not-json", jid))
            await db.db.commit()
            assert await store.save_checkpoint(
                jid, cursor_token="c2", processed=3) is True
            assert json.loads((await store.get(jid))["payload"])["cursor"] \
                == "c2"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cover_job_key_stable_run_id_lextra7(self):
        """L-EXTRA-7: cover_job_key детерминирован от run_id (e2e-resume)."""
        k1 = j.cover_job_key(summary_run_id="run-z", style_id="medved_press")
        k2 = j.cover_job_key(summary_run_id="run-z", style_id="medved_press")
        other = j.cover_job_key(summary_run_id="run-y",
                                style_id="medved_press")
        assert k1 == k2 and k1 != other
        assert k1.startswith("cov_")

    @pytest.mark.asyncio
    async def test_update_reference_rowcount_zero_is_false(self):
        """B.5: asyncpg `UPDATE 0` → False (API отдаёт 404, не ложный 200);
        `UPDATE 1` → True; объект с rowcount → честное значение."""

        class _Conn:
            def __init__(self, status):
                self._s = status

            async def execute(self, *a, **kw):
                return self._s

        class _Pool:
            def __init__(self, status):
                self._s = status

            def acquire(self):
                return _Ctx(self._s)

        class _Ctx:
            def __init__(self, status):
                self._s = status

            async def __aenter__(self):
                return _Conn(self._s)

            async def __aexit__(self, *exc):
                return False

        pg0 = SimpleNamespace(pool=_Pool("UPDATE 0"))
        pg1 = SimpleNamespace(pool=_Pool("UPDATE 1"))
        assert await registry.update_reference(
            pg0, "p", "r", asset_id="a") is False
        assert await registry.update_reference(
            pg1, "p", "r", asset_id="a") is True


# ══ Хвост L-ASAP31-4 (T-4417): budget в dry-run ═════════════════════════════

class TestDryRunBudget:
    @pytest.mark.asyncio
    async def test_dry_run_passes_resolver_budget(self, monkeypatch):
        """L-ASAP31-4: dry-run `build_fact_package` получает тот же
        resolver-бюджет, что и живой путь (точность preview)."""
        from services import summary_test_run as str_mod
        from tests.test_summary_test_run import _FakeMemory, _rows

        captured = {}
        real_build = str_mod.build_fact_package

        def _spy_build(*a, **kw):
            captured["budget"] = kw.get("budget")
            return real_build(*a, **kw)

        monkeypatch.setattr(str_mod, "build_fact_package", _spy_build)

        async def _budget():
            return ("l2", 7777)

        monkeypatch.setattr("services.summary_budget_auto."
                            "resolve_l2_package_budget", _budget)

        class _Usable:
            usable = True
            status = "ok"
            invalid_reason = None
            threads_count = 1
            facts_count = 1
            auto_unassigned_count = 0
            truncated = False
            skipped_ids = ()
            duration_ms = 1
            threads = ()

        async def _run_l1(*a, **kw):
            return _Usable()

        monkeypatch.setattr(str_mod, "run_l1", _run_l1)

        async def _run_l2(*a, **kw):
            raise AssertionError("L2 не должен вызываться в этом тесте")

        monkeypatch.setattr(str_mod, "run_l2", _run_l2)
        gen = sg.SummaryGenerator(_FakeMemory(_rows()), MagicMock(),
                                  MagicMock(), AsyncMock())
        result = await str_mod.run_summary_test(
            CHAT, {"hours": 1}, generator=gen, correlation_id="cid-budget")
        assert captured["budget"] == ("l2", 7777)
