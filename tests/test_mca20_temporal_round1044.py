"""MCA-20 round 10.44 — контрактные тесты ядра временного фактчека (A/B/D).

Приёмки: A69 (старый forward + относительное «сегодня» → проверка от
original date, актуальность отделена), A70 (одинаковый claim в разные
даты/режимы → разные кеш-ключи; устаревший не выдан за свежий), A71
(неизвестная/спорная дата → unknown не заменён now; historical ≠ knowable),
A72-фрагменты (unknown origin без выдуманных message/date).

Spec: D1–D7/D9–D13 (mca-20-temporal-factcheck), §30.1–§30.3.
Запуск: .venv\\Scripts\\python.exe -m pytest tests/test_mca20_temporal_round1044.py -q
"""
import asyncio
import dataclasses
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import mca_events
from services import temporal_factcheck as tf
from services.search_aggregator import AllSearchEnginesFailedException


# ── D1/CA-20-14: TemporalClaimEnvelope — новый frozen-DTO ───────────────────

class TestEnvelopeDto:
    def test_frozen_after_build(self):
        env = tf.TemporalClaimEnvelope(
            claim_id="tcl-1", chat_id=1, target_tg_message_id=10,
            target_revision=2, target_content_hash="h",
            trigger_tg_message_id=11, claim_text="текст", claim_span=None,
            source_type="text", attribution={}, origin_type="channel",
            origin_sender_user_id=None, origin_chat_id=-777,
            origin_display_name="Канал", repost_received_at=1760000000,
            original_published_at=1600000000,
            original_published_precision="day",
            claim_period_from=None, claim_period_to=None,
            claim_period_precision=None,
            date_source="telegram_origin", date_precision="day",
            date_timezone=None, date_uncertainty={},
            requested_mode="contextual", analysis_as_of=1760000000)
        with pytest.raises(dataclasses.FrozenInstanceError):
            env.claim_text = "подмена"

    def test_ca_20_14_symbol_not_reused(self):
        """Символ `ClaimEnvelope` занят mca-22 (services/claim_envelope.py):
        mca-20 экспортирует ТОЛЬКО TemporalClaimEnvelope; DTO mca-22 не
        расширяется (grep-гарантия: у класса mca-22 нет temporal-полей)."""
        import services.claim_envelope as ce
        import services.temporal_factcheck as tmod
        assert not hasattr(tmod, "ClaimEnvelope")
        assert hasattr(tmod, "TemporalClaimEnvelope")
        mca22_fields = {f.name for f in
                        dataclasses.fields(ce.ClaimEnvelope)}
        temporal_fields = {f.name for f in
                           dataclasses.fields(tmod.TemporalClaimEnvelope)}
        assert not ({"date_source", "requested_mode", "analysis_as_of"}
                    & mca22_fields)
        assert {"date_source", "requested_mode", "analysis_as_of"} \
            <= temporal_fields

    def test_field_contract_s30_1(self):
        """Поля ровно §30.1 `:1763` (сокращать нельзя — provenance A72)."""
        names = {f.name for f in
                 dataclasses.fields(tf.TemporalClaimEnvelope)}
        required = {
            "claim_id", "chat_id", "target_tg_message_id", "target_revision",
            "target_content_hash", "trigger_tg_message_id", "claim_text",
            "claim_span", "source_type", "attribution", "origin_type",
            "repost_received_at", "original_published_at",
            "original_published_precision", "claim_period_from",
            "claim_period_to", "date_source", "date_timezone",
            "date_uncertainty", "requested_mode", "analysis_as_of",
            "related_asset_id", "related_analysis_revision"}
        assert required <= names


# ── D2/D3: единый resolver из канонических метаданных ───────────────────────

class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or {}

    async def get_smart_message_origin_block(self, chat_id, tg_id):
        return self.rows.get((chat_id, tg_id))


def _row(origin_type="channel", origin_sent_at=1600000000, sent_at=1760000000,
         text="в 2019 году всё было иначе", current_revision=3,
         content_hash="abc"):
    return {
        "chat_id": 1, "tg_message_id": 10, "text": text, "caption": None,
        "sent_at": sent_at, "content_hash": content_hash,
        "current_revision": current_revision, "origin_type": origin_type,
        "origin_sent_at": origin_sent_at, "origin_sender_user_id": None,
        "origin_chat_id": -777, "origin_display_name": "Канал X",
        "author_name": None, "forward_source": "Канал X"}


class TestBuildEnvelope:
    @pytest.mark.asyncio
    async def test_telegram_origin_wins(self):
        db = FakeDb({(1, 10): _row()})
        env, reason = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10,
                            trigger_tg_message_id=11))
        assert reason is None
        assert env.date_source == "telegram_origin"
        assert env.original_published_at == 1600000000
        assert env.repost_received_at == 1760000000
        assert env.target_revision == 3
        assert env.target_content_hash == "abc"

    @pytest.mark.asyncio
    async def test_hidden_user_has_date(self):
        """D5: hidden_user — обычный MessageOrigin со date; скрытый автор
        ≠ неизвестная дата (SC-R2c)."""
        db = FakeDb({(1, 10): _row(origin_type="hidden_user",
                                   origin_sent_at=1600000000)})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        assert env.date_source == "telegram_origin"
        assert env.original_published_at == 1600000000

    @pytest.mark.asyncio
    async def test_plain_message_uses_message_date(self):
        db = FakeDb({(1, 10): _row(origin_type=None, origin_sent_at=None,
                                   sent_at=1650000000)})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        assert env.date_source == "telegram_message"
        assert env.original_published_at == 1650000000

    @pytest.mark.asyncio
    async def test_unknown_target_rejected_without_invention(self):
        """D2: невалидный target → отказ (`temporal_envelope_rejected`),
        без выдуманных подстановок."""
        db = FakeDb({})
        env, reason = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=404))
        assert env is None
        assert reason == "temporal_envelope_rejected"

    @pytest.mark.asyncio
    async def test_tool_free_text_explicit_unknown(self):
        """D3/SC-R1c: tool без цели → free_text + explicit unknown origin;
        message/date не придумываются, now не подставляется."""
        env, reason = await tf.build_envelope(
            None, tf.InputRef(kind="tool", chat_id=5, claim_text="курс 100"))
        assert reason is None
        assert env.source_type == "free_text"
        assert env.date_source == "unknown"
        assert env.date_precision == "unknown"
        assert env.date_uncertainty == {"origin": "explicit_unknown"}
        assert env.original_published_at is None
        assert env.target_tg_message_id is None
        assert not env.origin_known

    @pytest.mark.asyncio
    async def test_extract_conflict_recorded_not_resolved(self):
        """D5/SC-R2c: extracted (2019) vs Telegram (2020-метаданные) —
        конфликт сохранён, date_source не повышен молча."""
        db = FakeDb({(1, 10): _row(origin_sent_at=1600000000,
                                   text="в 2019 году всё было иначе")})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        assert env.date_source == "telegram_origin"
        conflicts = env.date_uncertainty.get("conflicts") or []
        assert conflicts and conflicts[0]["kind"] == "extracted_vs_telegram"

    @pytest.mark.asyncio
    async def test_extract_failed_note(self):
        """D15/F-3: дата-ОШИБКА извлечения ≠ дата-ОТСУТСТВИЕ."""
        db = FakeDb({(1, 10): _row(text="случилось 45.45.2022, говорят")})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        notes = env.date_uncertainty.get("notes") or []
        assert "temporal_date_extract_failed" in notes


# ── D6/A69: относительные даты от автора фрагмента ──────────────────────────

class TestRelativeDates:
    @pytest.mark.asyncio
    async def test_today_resolves_to_original_2022_not_repost(self):
        """A69: 2026-репост сообщения 2022 со «сегодня» — «сегодня»
        разрешается относительно даты ОРИГИНАЛА."""
        db = FakeDb({(1, 10): _row(origin_sent_at=1665277000,  # 2022-10-09
                                   sent_at=1760000000,         # 2025/26 repost
                                   text="сегодня случилось страшное")})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        assert env.claim_period_from is not None
        year = tf.datetime.datetime.fromtimestamp(
            env.claim_period_from, tf.datetime.timezone.utc).year
        assert year == 2022, "«сегодня» обязано лечь на 2022, не на репост"

    def test_relative_without_author_date_stays_unknown(self):
        """D5: нет даты автора → `temporal_date_unknown`; now НЕ подставлять."""
        start, end, precision, notes = tf._extract_claimed_period(
            "сегодня всё плохо", None)
        assert start is None and end is None
        assert precision is None
        assert notes == ["temporal_date_unknown"]

    def test_tz_unknown_day_becomes_boundary_interval(self):
        """D6/TH-9 (tzr1): неизвестный TZ → интервал пограничных суток."""
        start, end = tf.tz_unknown_interval(1000000, 1086400)
        assert end - start == 86400 + 2 * 14 * 3600

    @pytest.mark.asyncio
    async def test_claim_period_beats_publication_for_content(self):
        """D6: «в 2019…» → evaluated период = 2019, даже если пост 2026."""
        db = FakeDb({(1, 10): _row(origin_sent_at=None, sent_at=1760000000,
                                   text="в 2019 году всё было иначе")})
        env, _ = await tf.build_envelope(
            db, tf.InputRef(kind="reply", chat_id=1,
                            target_tg_message_id=10))
        assert env.claim_period_precision == "year"
        assert env.claim_period_from is not None


# ── D7: режимы проверки ──────────────────────────────────────────────────────

class TestModes:
    def test_current_request(self):
        assert tf.resolve_requested_mode("фактчек, это сейчас правда?") \
            == ("current", True)

    def test_historical_request(self):
        assert tf.resolve_requested_mode("а было ли это верно тогда?") \
            == ("historical_truth", True)

    def test_knowable_only_explicit(self):
        assert tf.resolve_requested_mode("что автор мог знать на тот момент?") \
            == ("knowable_at_time", True)
        # knowable НИКОГДА автоматически: обычный текст → дефолт владельца.
        assert tf.resolve_requested_mode("обычное утверждение") \
            == ("contextual", False)

    def test_owner_default_used_and_validated(self):
        assert tf.resolve_requested_mode(None, "current") == ("current", False)
        # невалидный каталог-дефолт → безопасный contextual
        assert tf.resolve_requested_mode(None, "nonsense") \
            == ("contextual", False)


# ── D9/D12/D13: кеш — составной ключ, bypass, freshness ─────────────────────

def _env_for_cache(**overrides):
    base = dict(
        claim_id="tcl-c", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h", trigger_tg_message_id=11,
        claim_text="курс доллара 100", claim_span=None, source_type="text",
        attribution={}, origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="X",
        repost_received_at=1760000000, original_published_at=1700000000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)
    base.update(overrides)
    return tf.TemporalClaimEnvelope(**base)


class TestCacheKey:
    def test_key_differs_by_year_chat_mode(self):
        """A70: одинаковый текст за разные годы/контексты → разные ключи."""
        base = tf.build_temporal_cache_key(_env_for_cache(), scope="chat:1")
        other_year = tf.build_temporal_cache_key(
            _env_for_cache(original_published_at=1600000000), scope="chat:1")
        other_chat = tf.build_temporal_cache_key(_env_for_cache(),
                                                 scope="chat:2")
        other_mode = tf.build_temporal_cache_key(
            _env_for_cache(requested_mode="current"), scope="chat:1")
        assert len({base, other_year, other_chat, other_mode}) == 4

    def test_key_differs_by_revision(self):
        """TH-10: edited target → новый ключ (revision/content_hash)."""
        k1 = tf.build_temporal_cache_key(_env_for_cache(), scope="chat:1")
        k2 = tf.build_temporal_cache_key(
            _env_for_cache(target_revision=2, target_content_hash="h2"),
            scope="chat:1")
        assert k1 != k2

    def test_unknown_origin_bypass(self):
        """D12/SC-R4a: unknown origin → ключ невозможен (None) →
        авто-bypass; атрибутированный ответ не разделяется."""
        assert tf.build_temporal_cache_key(
            _env_for_cache(origin_type=None, target_tg_message_id=None,
                           repost_received_at=None), scope="chat:1") is None

    def test_legacy_slug_not_serving_on_path(self):
        """SC-R4b: legacy slug `factcheck` не равен temporal-ключу (namespace
        сменился; ON-путь legacy не читает/не пишет)."""
        from services.smart_cache import build_key
        legacy = build_key("factcheck", "курс доллара 100")
        temporal = tf.build_temporal_cache_key(_env_for_cache(), scope="chat:1")
        assert legacy != temporal
        # новый slug зарегистрирован
        build_key("factcheck_temporal", "x")   # ValueError если слаг потерян

    def test_bucket_volatile_vs_stable(self):
        assert tf.freshness_bucket_for("current") == "volatile"
        assert tf.freshness_bucket_for("misleading_reuse") == "volatile"
        assert tf.freshness_bucket_for("old_but_valid") == "stable"
        assert tf.freshness_bucket_for("outdated") == "stable"

    @pytest.mark.asyncio
    async def test_ttl_defaults_from_catalog_fields(self):
        volatile = await tf.freshness_ttl_seconds(None, "volatile")
        stable = await tf.freshness_ttl_seconds(None, "stable")
        assert volatile == 6 * 3600
        assert stable == 720 * 3600


# ── D11/D10: вердикт — раздельные оси, guard misleading_reuse ────────────────

class TestVerdictGuard:
    def test_misleading_reuse_requires_freshness_markers(self):
        """CA-20-11/TH-5: пересылка ≠ намерение; без маркеров подачи —
        downgrade до outdated (+ явный reason)."""
        plain = _env_for_cache(claim_text="старое утверждение без маркеров")
        v = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status":
             "misleading_reuse"}, plain)
        assert v.temporal_status == "outdated"

    def test_misleading_reuse_with_markers_kept(self):
        marked = _env_for_cache(claim_text="происходит прямо сейчас, только что")
        v = tf.verdict_from_payload(
            {"factual_verdict": "refuted",
             "temporal_status": "misleading_reuse"}, marked)
        assert v.temporal_status == "misleading_reuse"

    def test_enums_validated_no_false_refuted(self):
        env = _env_for_cache()
        v = tf.verdict_from_payload(
            {"factual_verdict": "totally_true", "temporal_status": "hype"},
            env)
        assert v.factual_verdict == "insufficient_evidence"
        assert v.temporal_status == "unknown"
        assert v.assessment_mode == env.requested_mode
        assert v.as_of == env.analysis_as_of   # as_of из envelope, не now

    def test_reason_must_be_in_dictionary(self):
        env = _env_for_cache()
        v = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status": "current",
             "reason": "made_up_reason"}, env)
        assert v.reason is None
        v2 = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status": "current",
             "reason": "temporal_date_conflict"}, env)
        assert v2.reason == "temporal_date_conflict"


# ── D8: декомпозиция и temporal search ───────────────────────────────────────

class TestDecomposition:
    def test_multipart_own_periods(self):
        env = _env_for_cache(claim_text="В 2019 году цену подняли. А в 2024 "
                                        "её снова подняли.")
        parts = tf.decompose_claim(env)
        assert len(parts) == 2
        assert parts[0].precision == "year"
        y0 = tf.datetime.datetime.fromtimestamp(
            parts[0].period_from, tf.datetime.timezone.utc).year
        y1 = tf.datetime.datetime.fromtimestamp(
            parts[1].period_from, tf.datetime.timezone.utc).year
        assert (y0, y1) == (2019, 2024)

    def test_numeric_claims_reuse_mca15_shape(self):
        """CA-20-3: числа — NumericClaim-совместимые (metric_id/unit/value),
        второй числовой контур не строится."""
        env = _env_for_cache(claim_text="город вырос на 1 200 000 человек")
        parts = tf.decompose_claim(env)
        nums = [p.numeric for p in parts if p.numeric]
        assert nums and nums[0]["value"] == 1200000
        assert nums[0]["unit"] == "человек"
        assert nums[0]["metric_id"].startswith("fc:")

    def test_search_queries_carry_temporal_constraints(self):
        env = _env_for_cache(claim_text="цены подняли",
                             original_published_at=1546300800)  # 2019
        queries = tf.search_queries_for(tf.decompose_claim(env), env)
        assert queries and "2019" in queries[0]


# ── F-1/TH-5 (R3b): отказ поиска → honest insufficient, никогда refuted ─────

class TestNoFalseVerdicts:
    @staticmethod
    def _service(aggregator, llm):
        from services.factcheck_service import FactCheckService
        return FactCheckService(aggregator, llm)

    @pytest.mark.asyncio
    async def test_search_engines_down_gives_insufficient(self):
        class DownAggregator:
            async def search(self, q, max_symbols):
                raise AllSearchEnginesFailedException("engines down")

        class FakeLLM:
            async def generate(self, messages, **kwargs):
                return ("{\"factual_verdict\": \"supported\", "
                        "\"temporal_status\": \"current\"}")

        env = _env_for_cache()
        run = await self._service(DownAggregator(), FakeLLM()) \
            .check_claim_envelope(env)
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert run.verdict.reason == "temporal_insufficient_evidence"
        assert run.evidence_rows == ()

    @pytest.mark.asyncio
    async def test_missing_source_not_proof_of_fake(self):
        """F-2/CA-20-10: evidence без published_at честно хранит unknown;
        вердикт вербализуется с оговоркой, не с «подделка»."""
        class FakeAggregator:
            async def search(self, q, max_symbols):
                return "статья https://example.com/a — сниппет"

        class FakeLLM:
            async def generate(self, messages, **kwargs):
                if "СТРОГО JSON" in messages[0]["content"] or \
                        messages[0]["content"].startswith("Ты — фактчек"):
                    return ("{\"factual_verdict\": \"insufficient_evidence\","
                            " \"temporal_status\": \"unknown\", "
                            "\"reason\": \"temporal_source_unavailable\"}")
                return "Недостаточно данных"

        env = _env_for_cache()
        run = await self._service(FakeAggregator(), FakeLLM()) \
            .check_claim_envelope(env)
        assert run.verdict.factual_verdict == "insufficient_evidence"
        assert run.verdict.reason == "temporal_source_unavailable"
        assert run.evidence_rows and run.evidence_rows[0]["published_at"] is None
