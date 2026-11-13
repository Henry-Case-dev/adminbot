"""S15-FC-EVIDENCE — контракт доставки evidence по ёмкости фактического маршрута.

Проверяется НАБЛЮДАЕМОЕ поведение, а не внутренние константы:

* evidence больше прежнего потолка 8000 символов доходит до analyst И validator,
  без обрезки выдержки историческим лимитом 1200;
* число строк не ограничено скрытым потолком 20 — порция считается единым
  capacity resolver'ом родительского эпика по фактической модели/endpoint;
* при реальном превышении ёмкости остаток НЕ исчезает молча: он перечислен в
  `<evidence_delivery>` (ID/URL), доставленные строки = durable-строкам прогона;
* при переходе на fallback-маршрут payload recompose'ится под ёмкость
  ФАКТИЧЕСКИ вызываемой модели (owner §7.4), а не под «главную»;
* остановка поиска бюджетом/deadline даёт аналитику запрет вывода «доказательств
  нет» (owner §8.2), даже когда часть evidence уже есть;
* provenance (source_kind/opened) виден аналитику: сниппет не выдаётся за
  прочитанный документ; доменных blacklist в фактчеке нет (owner §8.3);
* атрибуционная цитата из чата не режется старым лимитом 400 символов.

TEST-LIFECYCLE: CONTRACT owner=S15-FC-EVIDENCE (SFC-7-01..7-05, SFC-8-02/8-03).
"""
from __future__ import annotations

import dataclasses
import json

import pytest

import services.temporal_factcheck as tf
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import model_capacity as mc
from services.factcheck_attribution import (
    AttributionMatch,
    attribution_evidence_ref,
)
from services.factcheck_service import FactCheckService

ANALYST = json.dumps({
    "factual_verdict": "insufficient_evidence",
    "temporal_status": "unknown",
    "evaluated_period": {"from": None, "to": None},
    "reason": "test",
    "parts": [],
}, ensure_ascii=False)
VALIDATOR = json.dumps(
    {"agree": True, "corrected_factual_verdict": None,
     "corrected_temporal_status": None, "note": "ok"},
    ensure_ascii=False)


class RecordingLLM:
    """LLM-двойник: пишет payload каждой стадии; умеет вызвать fallback-adapter.

    ``fallback_on_steps`` — шаги, на которых клиент «падает на primary» и
    вызывает переданный адаптер (реальный LLMClient делает это сам).
    """

    def __init__(self, *, model="route-model",
                 base_url="https://primary.example/api/v1",
                 fallback_model="fallback-model",
                 fallback_base_url="https://fallback.example/api/v1",
                 fallback_on_steps=()):
        self._chat_model = model
        self._base_url = base_url
        self._fallback_model = fallback_model
        self._fallback_base_url = fallback_base_url
        self.fallback_on_steps = set(fallback_on_steps)
        self.calls: list[tuple[str, str, bool]] = []

    async def generate(self, messages, *, step="", fallback_payload_adapter=None,
                       **_kw):
        user = messages[-1]["content"]
        adapted = False
        if step in self.fallback_on_steps and fallback_payload_adapter:
            payload = {"model": self._chat_model, "messages": list(messages)}
            out = fallback_payload_adapter(payload)
            if isinstance(out, dict) and out.get("messages"):
                user = out["messages"][-1]["content"]
                adapted = True
        self.calls.append((step, user, adapted))
        if step in ("temporal_verdict", "temporal_fallback"):
            return ANALYST
        if step == "temporal_validator":
            return VALIDATOR
        return "Проверка: данных недостаточно (test)."

    def user_for(self, step: str) -> str:
        for name, user, _adapted in self.calls:
            if name == step:
                return user
        raise AssertionError(f"step {step} not called: {self.calls}")


def _env():
    return tf.TemporalClaimEnvelope(
        claim_id="tcl-s15", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h1",
        trigger_tg_message_id=11,
        claim_text="В стране X традиция существует без внешнего влияния",
        claim_span=None, source_type="text", attribution={"author": "A"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="A",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)


def _ref(i: int, *, support: str, url: str | None = None):
    return orch.EvidenceRef(
        evidence_id=f"ev-{i}", url=url or f"https://source{i}.example/page",
        support=support, source_kind="secondary",
        published_at=1665277000, claims=("c1",))


def _support(i: int, chars: int, *, marker: str = "") -> str:
    base = f"[{marker or 'source'}-{i}] "
    filler = "историческая практика задокументирована "
    text = base + filler * (chars // len(filler) + 1)
    return text[:max(len(base), chars)]


def _coverage(refs, *, opened: dict[str, bool] | None = None):
    unit = fsp.ClaimUnit(claim_id="c1", text="часть тезиса",
                         claim_type=fsp.CLAIM_TYPE_FACT)
    opened = opened or {}
    evidence = tuple(
        fsp.ClaimEvidence(
            claim_id="c1", evidence_id=r.evidence_id, url=r.url,
            role=fsp.EVIDENCE_ROLE_SUPPORTS, note="test",
            strength="direct",
            opened=bool(opened.get(r.evidence_id, False)))
        for r in refs)
    return (fsp.ClaimCoverage(
        claim=unit, search_status=fsp.CLAIM_SEARCH_SEARCHED,
        status_detail=fsp.CLAIM_STATUS_PARTIAL,
        outcome=fsp.CLAIM_OUTCOME_PARTIAL, evidence=evidence,
        citation_ids=tuple(r.evidence_id for r in refs),
        queries_count=1, candidates=len(refs), opened=len(refs)),)


def _outcome(refs, *, claims=(), budget_exhausted=False,
             skipped_budget=0, skipped_deadline=0):
    text = "фрагмент выдачи " * 200
    return fsp.RetrievalOutcome(
        evidence_map=orch.EvidenceMap(
            refs=tuple(refs),
            allowlist=tuple(r.evidence_id for r in refs)),
        search_text=text,
        queries_attempted=4, queries_used=4, refs_collected=len(refs),
        fetch_errors=0, budget_exhausted=budget_exhausted,
        provider_failures=0, empty_results=0, irrelevant_results=0,
        claims=tuple(claims),
        stop_reason="budget_exhausted" if budget_exhausted
        else "sufficient_evidence",
        fetch_skipped_budget=skipped_budget,
        fetch_skipped_deadline=skipped_deadline,
        search_text_portions=(text,), search_text_total_chars=len(text))


def _pin_resolver(monkeypatch, window: int, source: str = "proven_limit",
                  *, calls: list | None = None):
    def _resolve(model=None, base_url=None):
        if calls is not None:
            calls.append((model, base_url))
        return window, source

    monkeypatch.setattr(mc, "resolve_evidence_window_tokens", _resolve)
    return _resolve


def _evidence_ids(payload: str) -> list[str]:
    import re
    return re.findall(r"\[(ev-\d+)\]", payload)


async def _run(monkeypatch, window, refs, *, llm=None, claims=(),
               budget_exhausted=False, skipped="0"):
    _pin_resolver(monkeypatch, window)
    llm = llm or RecordingLLM()
    service = FactCheckService(aggregator=None, llm=llm)
    outcome = _outcome(
        refs, claims=claims, budget_exhausted=budget_exhausted,
        skipped_budget=int(skipped) if budget_exhausted else 0)
    run = await service.check_claim_envelope(_env(), retrieval=outcome)
    return run, llm


# ── 1. Прежний потолок 8000/1200 больше не универсален ──────────────────────

@pytest.mark.asyncio
async def test_evidence_over_8000_reaches_analyst_and_validator(monkeypatch):
    """SFC-7-01/7-05: >8000 символов доходят до analyst И validator целиком.

    12 выдержек по 2000 символов = 24 000: ёмкость маршрута (1M токенов)
    вмещает всё, поэтому искусственной обрезки быть не должно — ни по числу
    строк (20), ни по символам выдержки (1200)."""
    refs = [_ref(i, support=_support(i, 2000)) for i in range(1, 13)]
    run, llm = await _run(monkeypatch, 1_000_000, refs,
                          claims=_coverage(refs))
    analyst = llm.user_for("temporal_verdict")
    validator = llm.user_for("temporal_validator")
    assert _evidence_ids(analyst) == [f"ev-{i}" for i in range(1, 13)]
    assert _evidence_ids(validator) == [f"ev-{i}" for i in range(1, 13)]
    for i in range(1, 13):
        marker = f"[source-{i}]"
        assert marker in analyst, "выдержка потеряна в analyst payload"
        assert marker in validator
    # полный support (2000) а не исторические 1200
    assert len(run.evidence_rows) == 12
    assert all(len(r["support"]) == 2000 for r in run.evidence_rows)
    assert "<evidence_delivery>" not in analyst, (
        "всё поместилось — мета-блок ограничения не нужен")


@pytest.mark.asyncio
async def test_no_hidden_row_cap_20(monkeypatch):
    """SFC-7-05/7-06: доставка не ограничена скрытым потолком 20 строк."""
    refs = [_ref(i, support=_support(i, 900)) for i in range(1, 61)]
    run, llm = await _run(monkeypatch, 1_000_000, refs,
                          claims=_coverage(refs))
    ids = _evidence_ids(llm.user_for("temporal_verdict"))
    assert len(ids) == 60 and ids[-1] == "ev-60"
    assert len(run.evidence_rows) == 60
    assert "ev-25" in llm.user_for("temporal_validator")


# ── 2. Единый capacity resolver и фактический маршрут ───────────────────────

@pytest.mark.asyncio
async def test_capacity_resolver_called_with_actual_route(monkeypatch):
    """SFC-7-03/7-04: ёмкость берётся единым resolver'ом по фактической модели
    и endpoint клиента; отдельного окна 16384 в фактчеке нет."""
    calls: list = []
    _pin_resolver(monkeypatch, 3000, calls=calls)
    llm = RecordingLLM()
    refs = [_ref(1, support=_support(1, 2000))]
    service = FactCheckService(aggregator=None, llm=llm)
    await service.check_claim_envelope(_env(), retrieval=_outcome(refs))
    assert ("route-model", "https://primary.example/api/v1") in calls
    # нет собственного окна: модуль не содержит присвоения 16384
    import inspect
    import re
    import services.factcheck_service as fcs
    src = inspect.getsource(fcs)
    assert "resolve_evidence_window_tokens" in src
    assert not re.search(r"16384\s*(?:\)|,|=)", src)


@pytest.mark.asyncio
async def test_real_capacity_budget_limits_portion_and_keeps_remainder(
        monkeypatch):
    """SFC-7-02/7-05: при реальном превышении ёмкости остаток сохраняется.

    Окно 3000 токенов → evidence-бюджет 2400 символов: часть строк не входит,
    но их ID/URL перечислены в `<evidence_delivery>`, а total = delivered +
    remainder (нет молчаливой потери)."""
    refs = [_ref(i, support=_support(i, 900)) for i in range(1, 11)]
    run, llm = await _run(monkeypatch, 3000, refs, claims=_coverage(refs))
    analyst = llm.user_for("temporal_verdict")
    delivered = _evidence_ids(analyst)
    assert 0 < len(delivered) < 10
    assert "<evidence_delivery>" in analyst
    meta = json.loads(
        analyst.split("<evidence_delivery>")[1].split(
            "</evidence_delivery>")[0])
    assert meta["capacity_unknown"] is False
    assert meta["total"] == 10
    assert meta["delivered"] == len(delivered)
    all_ids = {f"ev-{i}" for i in range(1, 11)}
    assert set(delivered) | set(meta["remainder_ids"]) == all_ids
    assert len(meta["remainder_urls"]) == len(meta["remainder_ids"])
    assert meta["delivered"] + len(meta["remainder_ids"]) == meta["total"]
    # durable-строки прогона == доставленным (нет расхождения БД↔prompt)
    assert len(run.evidence_rows) == len(delivered)


@pytest.mark.asyncio
async def test_capacity_unknown_degrades_honestly(monkeypatch):
    """Если resolver недоступен — прежняя порция, но с явной пометкой."""
    def _boom(model=None, base_url=None):
        raise RuntimeError("capacity unavailable")

    monkeypatch.setattr(mc, "resolve_evidence_window_tokens", _boom)
    refs = [_ref(i, support=_support(i, 600)) for i in range(1, 26)]
    llm = RecordingLLM()
    run = await FactCheckService(None, llm).check_claim_envelope(
        _env(), retrieval=_outcome(refs))
    analyst = llm.user_for("temporal_verdict")
    delivered = _evidence_ids(analyst)
    assert len(delivered) == 20          # аварийная деградация, не «бюджет 0»
    assert "<evidence_delivery>" in analyst
    meta = json.loads(
        analyst.split("<evidence_delivery>")[1].split(
            "</evidence_delivery>")[0])
    assert meta["capacity_unknown"] is True
    assert meta["total"] == 25 and len(meta["remainder_ids"]) == 5
    assert len(run.evidence_rows) == 20


# ── 3. Fallback/endpoint: характеристики фактически вызванного маршрута ────

@pytest.mark.asyncio
async def test_fallback_route_recomposes_payload_to_its_capacity(monkeypatch):
    """SFC-7-04: при переходе на fallback порция считается по fallback-модели.

    primary вмещает всё (1M), fallback — 1000 токенов (800 символов). Клиент
    вызывает adapter; аналитик получает fallback-порцию с remainder, а не
    primary-payload «как есть»."""
    windows = {
        ("route-model", "https://primary.example/api/v1"): 1_000_000,
        ("fallback-model", "https://fallback.example/api/v1"): 1000,
    }

    def _resolve(model=None, base_url=None):
        return windows.get((model, base_url), 1_000_000), "proven_limit"

    monkeypatch.setattr(mc, "resolve_evidence_window_tokens", _resolve)
    llm = RecordingLLM(fallback_on_steps={"temporal_verdict"})
    refs = [_ref(i, support=_support(i, 400)) for i in range(1, 9)]
    run = await FactCheckService(None, llm).check_claim_envelope(
        _env(), retrieval=_outcome(refs, claims=_coverage(refs)))
    step, adapted_user, adapted = llm.calls[0]
    assert step == "temporal_verdict" and adapted is True
    delivered = _evidence_ids(adapted_user)
    assert 0 < len(delivered) < 8
    meta = json.loads(
        adapted_user.split("<evidence_delivery>")[1].split(
            "</evidence_delivery>")[0])
    assert meta["delivered"] == len(delivered)
    assert set(delivered) | set(meta["remainder_ids"]) == {
        f"ev-{i}" for i in range(1, 9)}
    # primary-порция осталась полной (не занижена заранее fallback'ом)
    assert len(run.evidence_rows) == 8


# ── 4. Остановка поиска бюджетом: запрет «доказательств нет» ────────────────

@pytest.mark.asyncio
async def test_budget_stopped_search_forbids_absence_conclusion(monkeypatch):
    """SFC-8-02: если поиск остановлен бюджетом, аналитик не может решить,
    что доказательств не существует — даже при непустом evidence."""
    refs = [_ref(1, support=_support(1, 500))]
    _pin_resolver(monkeypatch, 1_000_000)
    llm = RecordingLLM()
    run = await FactCheckService(None, llm).check_claim_envelope(
        _env(), retrieval=_outcome(refs, budget_exhausted=True,
                                   skipped_budget=7))
    analyst = llm.user_for("temporal_verdict")
    assert "Поиск остановлен ограничением бюджета" in analyst
    assert "не делай вывод «доказательств нет»" in analyst
    assert "не открыто кандидатов: 7" in analyst


@pytest.mark.asyncio
async def test_no_budget_note_on_complete_search(monkeypatch):
    """Обратная сторона: без бюджетной остановки лишней оговорки нет."""
    refs = [_ref(1, support=_support(1, 500))]
    _pin_resolver(monkeypatch, 1_000_000)
    llm = RecordingLLM()
    await FactCheckService(None, llm).check_claim_envelope(
        _env(), retrieval=_outcome(refs))
    assert "Поиск остановлен ограничением бюджета" not in \
        llm.user_for("temporal_verdict")


# ── 5. Provenance и отсутствие доменных blacklist (SFC-8-03) ───────────────

@pytest.mark.asyncio
async def test_provenance_and_social_source_not_blocked(monkeypatch):
    """SFC-8-03: соцсеть — допустимый источник (нет «Facebook всегда плохой»),
    решение опирается на содержание/provenance; сниппет помечен opened=no."""
    facebook = _ref(1, support=_support(1, 400, marker="quote"),
                    url="https://www.facebook.com/quote/123")
    other = _ref(2, support=_support(2, 400))
    _pin_resolver(monkeypatch, 1_000_000)
    llm = RecordingLLM()
    run = await FactCheckService(None, llm).check_claim_envelope(
        _env(), retrieval=_outcome(
            [facebook, other],
            claims=_coverage([facebook, other],
                             opened={facebook.evidence_id: True})))
    analyst = llm.user_for("temporal_verdict")
    assert "[ev-1]" in analyst          # соцсеть не заблокирована доменом
    assert "opened=yes" in analyst      # цитата прочитана
    assert "opened=no" in analyst       # сниппет не выдан за документ
    assert any(r["evidence_id"] == "ev-1"
               and "facebook.com" in str(r.get("url"))
               for r in run.evidence_rows)
    import inspect
    import services.factcheck_service as fcs
    import services.factcheck_attribution as fat
    src = (inspect.getsource(fcs) + inspect.getsource(fat)).lower()
    assert "facebook" not in src, (
        "доменного blacklist/allowlist в фактчеке быть не должно")


@pytest.mark.asyncio
async def test_tiny_share_route_still_marks_remainder(monkeypatch):
    """Даже очень маленькое окно не превращает отсутствие места в тихую потерю."""
    refs = [_ref(i, support=_support(i, 700)) for i in range(1, 4)]
    run, llm = await _run(monkeypatch, 250, refs)   # 200 символов бюджета
    analyst = llm.user_for("temporal_verdict")
    meta = json.loads(
        analyst.split("<evidence_delivery>")[1].split(
            "</evidence_delivery>")[0])
    assert meta["total"] == 3
    assert meta["delivered"] + len(meta["remainder_ids"]) == 3
    assert len(run.evidence_rows) == meta["delivered"]


# ── 6. Атрибуционная цитата: без старого cap 400 ───────────────────────────

def test_attribution_quote_not_truncated_at_400():
    """SFC-7-05: существенная выдержка из чата не исчезает из-за старого cap."""
    quote = "цитата " * 200       # ~1400 символов
    match = AttributionMatch(
        author="Вася", quote=quote, message_text=quote,
        timestamp=1760000000, tg_message_id=10, message_id=20,
        chat_id=-100)
    ref = attribution_evidence_ref(match)
    assert quote.strip() in ref.support
    assert len(ref.support) > 400
