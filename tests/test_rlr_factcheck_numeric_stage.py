"""RLR — numeric-контракт data-стадии фактчека (REMOVE-LEGACY-REPHRASING).

R-03.4/R-06/§3.4/§8: числа финального фактчека обязаны происходить из
СТРУКТУРНЫХ данных прогона (MetricResult/NumericClaim, facts-слой Stage-1,
evidence с provenance, даты envelope). Валидированный набор уходит Writer'у
ЯВНО в payload ДО генерации, после генерации выполняется детерминированная
(без LLM) сверка.

Неподтверждённое число НЕ публикуется и НЕ переписывается в готовой фразе:
вместо пересказа доставляется структурный отчёт той же проверки (вердикт +
утверждения + источники). Post-L2 numeric-правки (`apply_numeric_guard`,
numeric-retry, `verified_phrase`) на этом маршруте нет.

TEST-LIFECYCLE: CONTRACT owner=REMOVE-LEGACY-REPHRASING (RLR-FC-NUMERIC)
"""
import json

import pytest

from services import chat_statistics as cs
from services import factcheck_service as fs
from services import negative_constraints as nc
from services import temporal_factcheck as tf
from services.factcheck_service import FactCheckService

pytestmark = pytest.mark.system2      # двухвызовный фактчек-маршрут включён

CHAT_ID = -100555
TARGET_TG = 9200
TRIGGER_TG = 9201

_ANALYST_EMPTY = {
    "claim": "земля плоская",
    "findings": [{"assertion": "земля плоская", "status": "false",
                  "human_time": "в августе", "author": "Вася",
                  "evidence": "спутники и фото"}],
    "verdict": "полный бред",
}


# ── Harness ──────────────────────────────────────────────────────────────────

def _metric_result(value=42, unit="messages",
                   metric_id="cs:deadbeef1234") -> cs.MetricResult:
    return cs.MetricResult(
        metric_id=metric_id, status=cs.STATUS_OK, value=value, unit=unit,
        query_spec_hash="h", human_label="сообщений: 42",
        scope={"chat_id": CHAT_ID}, coverage=cs.COVERAGE_KNOWN_COMPLETE,
        time_bounds={}, data_as_of=1760900000, watermark={})


def _analyst_raw(payload: dict, *, metrics=()) -> str:
    """Ответ Stage-1: строгий JSON + per-turn реестр измерений хода."""
    class _Raw(str):
        metric_results = tuple(metrics)

    return _Raw(json.dumps(payload, ensure_ascii=False))


def _two_call_service(*generated, metrics=()):
    """Stage-1 отдаёт структурный JSON, дальше — переданные ответы Writer'а."""
    aggregator = type("A", (), {})()
    aggregator.search = _async_ret("хиты поиска")
    service = FactCheckService(aggregator, _llm(generated, metrics=metrics))
    return service, service.llm


def _async_ret(value):
    async def _call(*_a, **_kw):
        return value
    return _call


def _llm(generated, *, metrics=()):
    llm = type("L", (), {})()
    texts = list(generated)
    calls = []

    async def _generate(messages, **_kw):
        calls.append(messages)
        index = min(len(calls) - 1, len(texts) - 1)
        text = texts[index]
        if index == 0 and metrics:
            # Первый вызов — Stage-1: несёт реестр измерений хода.
            class _Raw(str):
                metric_results = tuple(metrics)
            return _Raw(text)
        return text

    llm.generate = _generate
    llm.calls = calls
    return llm


class _Capture:
    """Захват фактических kwargs/статистики штатного verbalize_validated."""

    def __init__(self):
        self.kwargs = []
        self.stats = []

    def install(self, monkeypatch):
        real = fs.verbalize_validated

        async def wrapper(generate_call, base_messages, **kwargs):
            self.kwargs.append(kwargs)
            text, stats = await real(generate_call, base_messages, **kwargs)
            self.stats.append(stats)
            return text, stats

        monkeypatch.setattr(fs, "verbalize_validated", wrapper)
        return self


def _semantic_rewrites(stats: dict, writer_calls: int) -> int:
    """Литературные переписывания: штатный счётчик, если он есть в stats.

    На базовой ветке поля ещё нет, поэтому тем же смыслом служит число
    фактических вызовов Writer'а: один вызов = ноль переписываний.
    """
    if "semantic_rewrite_count" in (stats or {}):
        return int(stats["semantic_rewrite_count"])
    return max(0, int(writer_calls) - 1)


def _envelope(claim="в Килякете выпало 120 мм осадков за сутки",
              original_published_at=None, date_source="unknown"):
    return tf.TemporalClaimEnvelope(
        claim_id="c-1", chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=original_published_at,
        original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source=date_source,
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1760900000)


def _temporal_verdict(factual="refuted", parts=(), period=None):
    return tf.TemporalVerdict(
        factual_verdict=factual, temporal_status="unknown",
        evaluated_period=(period if period is not None
                          else {"from": None, "to": None,
                                "precision": "unknown"}),
        assessment_mode="contextual", as_of=1760900000,
        evidence_refs=("ev-1",), uncertainty={}, parts=tuple(parts),
        reason=None)


def _temporal_service(*generated):
    service = FactCheckService(type("A", (), {})(), _llm(generated))
    return service, service.llm


# ── (a) выдуманное число → структурный отчёт, число не публикуется ──────────

@pytest.mark.asyncio
async def test_invented_number_is_not_published(monkeypatch):
    cap = _Capture().install(monkeypatch)
    service, llm = _two_call_service(
        json.dumps(_ANALYST_EMPTY, ensure_ascii=False),
        "В чате 12 345 сообщений про это — я проверял.",
        metrics=(_metric_result(42),))
    result = await service.check_claim("земля плоская")

    # один финальный Writer-вызов (Stage-1 + Writer), без reroll/retry
    assert len(llm.calls) == 2
    writer_calls = 1
    # выдуманное число не опубликовано ни в каком написании
    assert "12 345" not in result
    assert "12345" not in result
    assert "12\xa0345" not in result
    # вместо пересказа — детерминированный структурный отчёт
    assert result == fs.deterministic_analysis_report(_ANALYST_EMPTY)
    assert result.startswith("Вердикт: полный бред")
    assert "земля плоская — не подтверждается" in result
    assert fs.NUMERIC_REPORT_NOTE in result
    # ни перегенерации, ни post-L2 numeric-правки
    assert _semantic_rewrites(cap.stats[0], writer_calls) == 0
    stats = cap.stats[0]
    assert stats["attempts"] == 1 and stats["retries"] == 0
    assert stats["fallback"] is False and stats["retry_error"] is False
    # numeric-статистики штатного guard'а нет: контракт не передавался
    assert "numeric_claim_retry" not in stats
    assert "numeric_claim_fallback" not in stats
    assert "numeric_contract" not in cap.kwargs[0]

    # валидированный набор был отдан Writer'у ЯВНО, до генерации
    stage2_payload = llm.calls[1][1]["content"]
    numbers = json.loads(
        stage2_payload.split("АНАЛИЗ (JSON):\n", 1)[1])["numbers"]
    assert {"value": "42", "source": "measurement",
            "ref": "cs:deadbeef1234", "unit": "messages"} in numbers["checked"]


# ── (b) все числа подтверждены → обычный ответ без изменений ────────────────

@pytest.mark.asyncio
async def test_validated_numbers_keep_writer_text(monkeypatch):
    cap = _Capture().install(monkeypatch)
    analyst = {
        "claim": "в чате 1200 сообщений",
        "findings": [{"assertion": "в чате 1200 сообщений", "status": "true",
                      "human_time": "без даты", "author": None,
                      "evidence": "выгрузка: 1 200 сообщений"}],
        "verdict": "сходится",
    }
    writer_text = "Да, 1 200 сообщений, сходится с выгрузкой."
    service, llm = _two_call_service(_analyst_raw(analyst), writer_text)
    result = await service.check_claim("в чате 1200 сообщений")

    assert result == writer_text          # текст Writer'а не переписан
    assert len(llm.calls) == 2
    assert _semantic_rewrites(cap.stats[0], 1) == 0
    assert cap.stats[0]["attempts"] == 1 and cap.stats[0]["retries"] == 0


# ── (c) insufficient_evidence не превращается в mixed/подтверждение ────────

@pytest.mark.asyncio
async def test_insufficient_evidence_stays_insufficient(monkeypatch):
    service, llm = _temporal_service("Нашлось 987 совпадений — всё сходится.")
    env = _envelope()
    verdict = _temporal_verdict(factual="insufficient_evidence")
    out = await service._temporal_verbalize(env, verdict, False, None)

    assert "987" not in out
    assert out == fs.deterministic_temporal_report(env, verdict)
    assert "Вердикт: данных недостаточно для уверенного вывода." in out
    assert "частично" not in out.casefold()
    assert "подтверждается" not in out.casefold()      # никакого апгрейда
    assert len(llm.calls) == 1                          # один Writer-вызов


# ── (d) подтверждённый/опровергнутый вердикт не меняется ────────────────────

@pytest.mark.asyncio
async def test_supported_verdict_with_validated_numbers(monkeypatch):
    service, _llm_calls = _temporal_service(
        "Подтверждается: за сутки выпало 120 мм.")
    env = _envelope()
    verdict = _temporal_verdict(factual="supported")
    out = await service._temporal_verbalize(env, verdict, False, None)
    # 120 — число самого тезиса (структурный источник claim), не выдумка
    assert out == "Подтверждается: за сутки выпало 120 мм."


@pytest.mark.asyncio
async def test_refuted_verdict_reports_without_softening(monkeypatch):
    service, _llm_calls = _temporal_service(
        "Опровергнуто: нашлось 987 доказательств.")
    env = _envelope()
    verdict = _temporal_verdict(factual="refuted")
    out = await service._temporal_verbalize(env, verdict, False, None)

    assert "987" not in out
    assert "Вердикт: доступные данные утверждение не подтверждают." in out
    assert "частично" not in out.casefold()


# ── (e) никакой post-L2 правки готового текста ──────────────────────────────

@pytest.mark.asyncio
async def test_no_post_l2_numeric_rewrite(monkeypatch):
    def _forbidden(*_a, **_kw):
        raise AssertionError("apply_numeric_guard не применяется в фактчеке")

    monkeypatch.setattr(nc, "apply_numeric_guard", _forbidden)
    monkeypatch.setattr(fs, "apply_numeric_guard", _forbidden,
                        raising=False)
    cap = _Capture().install(monkeypatch)
    service, _llm_calls = _two_call_service(
        _analyst_raw(_ANALYST_EMPTY),
        "В чате 12 345 сообщений про это — я проверял.")
    out = await service.check_claim("земля плоская")

    # выдуманное предложение не «починено» и не вырезано — ответ целиком
    # заменён структурным отчётом (никакой подстановки verified_phrase)
    assert "В чате" not in out and "проверял" not in out
    assert out == fs.deterministic_analysis_report(_ANALYST_EMPTY)
    assert "verified_phrase" not in cap.kwargs[0]
    assert "numeric_contract" not in cap.kwargs[0]
    # источник модуля не содержит post-L2 numeric-правки
    import inspect
    src = inspect.getsource(fs)
    assert "apply_numeric_guard(" not in src      # только упоминание в комментарии
    assert "verified_phrase=" not in src          # никакой подстановки фразы
    assert ".verified_phrase" not in src


# ── Чистые помощники контракта ──────────────────────────────────────────────

class TestNumericContractHelpers:
    def test_canonical_forms_match(self):
        claim = "в чате 1200 сообщений"
        bindings = fs.build_numeric_contract(claim_text=claim)
        assert fs.unvalidated_numbers("1 200 сообщений", bindings) == ()
        bindings2 = fs.build_numeric_contract(claim_text="1,5 млн")
        assert fs.unvalidated_numbers("1.5 млн", bindings2) == ()
        assert fs.unvalidated_numbers("1.6 млн", bindings2) == ("1.6",)

    def test_date_components_are_bound(self):
        rows = ({"evidence_id": "ev-1", "support": "выдержка",
                 "published_at": 1750000000},)      # 15.06.2025 UTC
        bindings = fs.build_numeric_contract(evidence_rows=rows)
        assert "15.06.2025" in {b.canon for b in bindings}
        # пересказ даты словами не считается выдуманным числом
        assert fs.unvalidated_numbers("15 июня 2025", bindings) == ()
        assert fs.unvalidated_numbers("16 июня 2025", bindings) == ("16",)

    def test_measurement_claims_are_bound_with_provenance(self):
        bindings = fs.build_numeric_contract(
            metric_results=(_metric_result(42),))
        payload = fs.numeric_contract_payload(bindings)
        assert payload["checked"] == [{"value": "42", "source": "measurement",
                                       "ref": "cs:deadbeef1234",
                                       "unit": "messages"}]
        assert fs.unvalidated_numbers("42 сообщения", bindings) == ()
        assert fs.unvalidated_numbers("43 сообщения", bindings) == ("43",)

    def test_empty_contract_rejects_any_number(self):
        assert fs.unvalidated_numbers("итого 7 штук", ()) == ("7",)

    def test_report_sources_come_from_real_search_output(self):
        urls = fs.report_sources_from_text(
            "см. https://example.org/a. и https://example.org/b")
        assert urls == ("https://example.org/a", "https://example.org/b")
        assert fs.deterministic_analysis_report(_ANALYST_EMPTY, sources=urls) \
            .count("https://example.org/a") == 1
