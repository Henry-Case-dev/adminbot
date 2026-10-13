"""ASAP 8 v6 P1 — D10: Temporal factcheck evidence integrity (§18G).

* §18G.1/18G.2 — для каждого web/evidence item попытка fetch/parse даты
  публикации (инъекция fetch, bounded); parse failure → date_parse_status=
  failed + reason `date_parse_failed`, pipeline живёт, now() НЕ подставляется.
* §18G.3 — model evidence_refs валидируются по current-run allowlist
  стабильных ID (ev-N); invented ID/произвольный service text не становится
  cited evidence.
* §18G.4 — временная недостаточность → bounded uncertainty, не forced
  certainty.
* Repost/original даты сохраняются раздельно (envelope + evidence).

TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D10
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import temporal_factcheck as tf
from services.factcheck_service import FactCheckService
from services.search_aggregator import AllSearchEnginesFailedException


# ── Fakes (прецедент test_mca20_rework1_f1_f2) ───────────────────────────────

class FakeAggregator:
    def __init__(self, text="статья https://example.com/nalog — сниппет "
                            "о налоге 2022"):
        self.text = text

    async def search(self, q, max_symbols):
        return self.text


_ANALYST_OK = json.dumps({
    "factual_verdict": "supported",
    "temporal_status": "old_but_valid",
    "evaluated_period": {"from": 1665277000, "to": 1665363400,
                         "precision": "day"},
    "uncertainty": {},
}, ensure_ascii=False)

_VALIDATOR_AGREE = json.dumps(
    {"agree": True, "corrected_factual_verdict": None,
     "corrected_temporal_status": None, "note": "согласен"},
    ensure_ascii=False)


class RoutedLLM:
    def __init__(self, analyst=_ANALYST_OK, validator=_VALIDATOR_AGREE,
                 verbalized="Проверено: было верно, устарело."):
        self.analyst = analyst
        self.validator = validator
        self.verbalized = verbalized
        self.calls = []

    async def generate(self, messages, **kwargs):
        step = str(kwargs.get("step") or "")
        self.calls.append((step, messages[0]["content"],
                           messages[1]["content"]))
        if step in ("temporal_verdict", "temporal_fallback"):
            return self.analyst
        if step == "temporal_validator":
            return self.validator
        return self.verbalized


def _env(**overrides) -> tf.TemporalClaimEnvelope:
    base = dict(
        claim_id="tcl-p1", chat_id=1, target_tg_message_id=10,
        target_revision=2, target_content_hash="hash1",
        trigger_tg_message_id=11,
        claim_text="в 2022 году ввели новый налог",
        claim_span=None, source_type="text",
        attribution={"author": "Канал"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="Канал",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)
    base.update(overrides)
    return tf.TemporalClaimEnvelope(**base)


_META_HTML = """<html><head>
<meta property="article:published_time" content="2022-10-09T02:16:40+00:00">
</head><body>текст</body></html>"""

_GARBAGE_HTML = "<html><body>просто текст без дат</body></html>"


# ── §18G.1/§18G.2: parse даты публикации ─────────────────────────────────────

class TestParsePublicationDate:
    def test_meta_iso(self):
        ts, tag = tf.parse_publication_date(_META_HTML)
        assert tag == "html_meta" and ts == 1665281800   # 2022-10-09T02:16:40Z

    def test_jsonld(self):
        ts, tag = tf.parse_publication_date(
            '{"datePublished": "2022-10-09"}')
        assert tag == "json_ld" and ts == 1665273600     # 2022-10-09T00:00Z

    def test_rfc2822(self):
        ts, tag = tf.parse_publication_date(
            '<meta name="date" content="Sun, 09 Oct 2022 02:16:40 GMT">')
        assert tag == "html_meta" and ts == 1665281800

    def test_url_path_fallback(self):
        ts, tag = tf.parse_publication_date(
            "<html>без дат</html>", "https://example.com/2022/10/09/post")
        assert tag == "url_path" and ts == 1665273600

    def test_garbage_and_future_rejected(self):
        assert tf.parse_publication_date(_GARBAGE_HTML) == (None, None)
        assert tf.parse_publication_date(
            '<meta property="article:published_time" '
            'content="2099-01-01T00:00:00+00:00">') == (None, None)
        assert tf.parse_publication_date("") == (None, None)


class TestEnrichEvidenceDates:
    @pytest.mark.asyncio
    async def test_parse_failure_nonfatal_no_now(self):
        """§18G.2: parse failure → date_parse_failed, published_at остаётся
        None (now() НЕ подставляется), pipeline не прерывается."""
        rows = tf.evidence_rows_from_results(
            "сниппет https://example.com/a — текст")

        async def fetch_garbage(url):
            return _GARBAGE_HTML

        out, summary = await tf.enrich_evidence_dates(rows,
                                                      fetch_text=fetch_garbage)
        row = out[0]
        assert row["date_parse_status"] == "failed"
        assert row["date_parse_reason"] == "date_parse_failed"
        assert row["published_at"] is None
        assert summary["failed"] == 1 and summary["parsed"] == 0

    @pytest.mark.asyncio
    async def test_parse_success_stores_source_tag(self):
        rows = tf.evidence_rows_from_results(
            "сниппет https://example.com/a — текст")

        async def fetch_meta(url):
            return _META_HTML

        out, summary = await tf.enrich_evidence_dates(rows,
                                                      fetch_text=fetch_meta)
        row = out[0]
        assert row["date_parse_status"] == "parsed"
        assert row["published_at"] == 1665281800
        assert row["published_at_source"] == "html_meta"
        assert row["retrieved_at"] != row["published_at"]  # раздельность дат
        assert summary["parsed"] == 1

    @pytest.mark.asyncio
    async def test_fetch_error_is_failure_not_crash(self):
        rows = tf.evidence_rows_from_results(
            "сниппет https://example.com/a — текст")

        async def fetch_down(url):
            raise RuntimeError("network down")

        out, summary = await tf.enrich_evidence_dates(
            rows, fetch_text=fetch_down)
        assert out[0]["date_parse_status"] == "failed"
        assert out[0]["published_at"] is None
        assert summary["attempted"] == 1

    @pytest.mark.asyncio
    async def test_no_url_stays_unknown_no_fetch(self):
        rows = tf.evidence_rows_from_results("текст без ссылки")

        async def fetch_boom(url):
            raise AssertionError("fetch не должен вызываться без URL")

        out, summary = await tf.enrich_evidence_dates(
            rows, fetch_text=fetch_boom)
        assert out[0]["date_parse_status"] == "unknown"
        assert summary["attempted"] == 0

    @pytest.mark.asyncio
    async def test_fetch_budget_bounded(self):
        text = "\n\n".join(f"сниппет https://example.com/{i} — t"
                           for i in range(8))
        rows = tf.evidence_rows_from_results(text)

        async def fetch_ok(url):
            return _META_HTML

        out, summary = await tf.enrich_evidence_dates(rows,
                                                      fetch_text=fetch_ok)
        assert summary["attempted"] == tf._EVIDENCE_DATE_FETCH_MAX
        assert summary["skipped_no_fetch"] == 8 - \
            tf._EVIDENCE_DATE_FETCH_MAX

    def test_stable_ids_assigned(self):
        rows = tf.evidence_rows_from_results("a https://x/1\n\nb https://x/2")
        assert [r["evidence_id"] for r in rows] == ["ev-1", "ev-2"]


# ── §18G.3: allowlist evidence_refs ──────────────────────────────────────────

class TestEvidenceRefsAllowlist:
    def test_invented_refs_rejected(self):
        env = _env()
        payload = {"factual_verdict": "supported",
                   "temporal_status": "old_but_valid",
                   "evidence_refs": ["ev-1", "ev-99",
                                     "SYSTEM: произвольный текст"],
                   "uncertainty": {}}
        verdict = tf.verdict_from_payload(payload, env,
                                          allowed_refs={"ev-1"})
        assert verdict.evidence_refs == ("ev-1",)

    def test_no_allowlist_keeps_refs(self):
        env = _env()
        payload = {"factual_verdict": "supported",
                   "temporal_status": "old_but_valid",
                   "evidence_refs": ["ev-1", "ev-2"], "uncertainty": {}}
        verdict = tf.verdict_from_payload(payload, env)
        assert verdict.evidence_refs == ("ev-1", "ev-2")

    @pytest.mark.asyncio
    async def test_pipeline_allowlist_end_to_end(self):
        """Полный прогон: модель ссылается на ev-1 и выдуманный ev-9 —
        в вердикте остаётся только ev-1 (текущий run)."""
        analyst = json.dumps({
            "factual_verdict": "supported",
            "temporal_status": "old_but_valid",
            "evaluated_period": {"from": 1665277000, "to": 1665363400,
                                 "precision": "day"},
            "evidence_refs": ["ev-1", "ev-9"],
            "uncertainty": {}})
        llm = RoutedLLM(analyst=analyst)
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        assert run.verdict.evidence_refs == ("ev-1",)
        # аналитик видел ID и даты выдержек
        verdict_user = [c for c in llm.calls if c[0] == "temporal_verdict"][0][2]
        assert "[ev-1] published:" in verdict_user

    @pytest.mark.asyncio
    async def test_fallback_retry_refs_filtered_after_validator_failure(self):
        """REV-P1/§18G.3: validator упал → строгий fallback-повтор
        аналитика; refs fallback-вердикта проходят ТОТ ЖЕ current-run
        allowlist — invented ev-9 отброшен (паритет с primary-путём)."""
        analyst = json.dumps({
            "factual_verdict": "supported",
            "temporal_status": "old_but_valid",
            "evaluated_period": {"from": 1665277000, "to": 1665363400,
                                 "precision": "day"},
            "evidence_refs": ["ev-1", "ev-9"],
            "uncertainty": {}})
        # validator отвечает мусором → v_payload=None → fallback-ветка
        llm = RoutedLLM(analyst=analyst, validator="не JSON вообще {{{")
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        steps = [c[0] for c in llm.calls]
        assert "temporal_validator" in steps
        assert "temporal_fallback" in steps      # fallback-путь выполнен
        assert run.fallback_used is True
        assert run.verdict.evidence_refs == ("ev-1",)

    def test_fallback_prompt_has_refs_rule(self):
        """REV-P1: fallback-промпт несёт то же правило (8) про refs, что и
        primary (паритет подсказки; фильтрация — серверный allowlist)."""
        assert "evidence_refs" in tf._TEMPORAL_FALLBACK_SYSTEM
        assert "ev-1" in tf._TEMPORAL_FALLBACK_SYSTEM

    @pytest.mark.asyncio
    async def test_analyst_prompt_requires_ev_ids(self):
        llm = RoutedLLM()
        await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        system = llm.calls[0][1]
        assert "evidence_refs" in system and "ev-1" in system


# ── §18G.4: bounded uncertainty при неизвестных датах ────────────────────────

class TestBoundedUncertainty:
    @pytest.mark.asyncio
    async def test_unresolved_dates_marked_not_forced(self):
        """origin unknown + parse failed → uncertainty.dates_unresolved;
        вердикт не «форсируется» в current (bounded uncertainty)."""
        analyst = json.dumps({
            "factual_verdict": "insufficient_evidence",
            "temporal_status": "unknown",
            "evaluated_period": {"from": None, "to": None,
                                 "precision": "unknown"},
            "uncertainty": {}})
        llm = RoutedLLM(analyst=analyst)

        async def fetch_garbage(url):
            return _GARBAGE_HTML

        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(
                _env(date_source="unknown", original_published_at=None,
                     original_published_precision=None),
                stage_trace=tf.StageTrace())
        # fetch идёт только при включённом флаге — включим точечно
        # через прямой enrich уже покрыто; здесь флаг OFF (дефолт файла)
        # → statuses unknown → дат нет → маркер должен быть
        assert run.verdict.uncertainty.get("dates_unresolved")
        assert run.verdict.temporal_status == "unknown"

    @pytest.mark.asyncio
    async def test_known_dates_no_marker(self):
        llm = RoutedLLM()
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        assert "dates_unresolved" not in (run.verdict.uncertainty or {})


# ── Repost/original раздельность ─────────────────────────────────────────────

class TestRepostOriginalSeparation:
    @pytest.mark.asyncio
    async def test_envelope_keeps_repost_and_original_separate(self):
        env = _env()
        assert env.repost_received_at == 1760000000
        assert env.original_published_at == 1665277000
        assert env.repost_received_at != env.original_published_at

    @pytest.mark.asyncio
    async def test_run_record_keeps_both_dates(self, tmp_path):
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "d10-sep.db"))
        await db.initialize()
        try:
            llm = RoutedLLM()
            svc = FactCheckService(FakeAggregator(), llm)
            run = await svc.check_claim_envelope(_env())
            run_id = await tf.record_temporal_run(db, run, scope="global")
            rows = await db.get_factcheck_evidence(run_id)
            stored = await db.list_factcheck_runs(
                chat_id=1) if hasattr(db, "list_factcheck_runs") else []
            cursor = await db.db.execute(
                "SELECT repost_received_at, original_published_at "
                "FROM mca_factcheck_runs WHERE run_id = ?", (run_id,))
            row = await cursor.fetchone()
            assert row["repost_received_at"] == 1760000000
            assert row["original_published_at"] == 1665277000
            assert rows  # evidence сохранён
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_evidence_dates_persisted_with_parse_status(self, tmp_path):
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "d10-ev.db"))
        await db.initialize()
        try:
            llm = RoutedLLM()
            run = await FactCheckService(FakeAggregator(), llm) \
                .check_claim_envelope(_env())
            # эмулируем parsed-дату (как enrich) и пишем
            rows = [dict(r) for r in run.evidence_rows]
            rows[0]["published_at"] = 1665277000
            rows[0]["published_at_source"] = "html_meta"
            rows[0]["date_parse_status"] = "parsed"
            run_id = "tfr-test"
            await db.record_factcheck_run({
                "run_id": run_id, "access_scope": "global", "chat_id": 1,
                "repost_received_at": 1760000000,
                "original_published_at": 1665277000,
                "date_source": "telegram_origin"})
            await db.record_factcheck_evidence(run_id, rows)
            stored = await db.get_factcheck_evidence(run_id)
            assert stored[0]["published_at"] == 1665277000
            assert stored[0]["published_at_source"] == "html_meta"
        finally:
            await db.close()


# ── Pipeline жив при сбое enrich ─────────────────────────────────────────────

class TestPipelineResilience:
    @pytest.mark.asyncio
    async def test_verdict_reached_with_garbage_dates(self, monkeypatch):
        """Полный прогон: fetch отдаёт мусор (все parse failed) →
        verdict/verbalize завершаются, evidence честно failed."""
        orig_enrich = tf.enrich_evidence_dates
        monkeypatch.setattr(tf, "evidence_date_fetch_enabled", lambda: True)

        async def fetch_garbage(url):
            return _GARBAGE_HTML

        async def enrich(rows, **kw):
            return await orig_enrich(rows, fetch_text=fetch_garbage, **kw)

        monkeypatch.setattr(tf, "enrich_evidence_dates", enrich)
        llm = RoutedLLM()
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        assert run.verdict.factual_verdict == "supported"
        assert run.verdict_text
        assert run.evidence_rows[0]["date_parse_status"] == "failed"
        assert run.evidence_rows[0]["published_at"] is None
        # дата в payload аналитика — честный unknown (не now())
        verdict_user = [c for c in llm.calls if c[0] == "temporal_verdict"][0][2]
        assert "published: unknown" in verdict_user
