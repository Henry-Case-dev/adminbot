"""S14 FACTCHECK-REQUEST-INTEGRITY — ресурсный контракт фактчека.

Проверяем наблюдаемый контракт, а не только константы:
* заводские значения 120/600/24/64/100000/20/32 применяются на штатном пути;
* effective budgets OFF снимает продуктовый дедлайн/общие и уточняющие cap,
  char-бюджет, cap числа частей и политику открытий; сохранённый старый
  бюджет не продолжает enforcement;
* ON сохраняет законно сохранённые значения (в т.ч. выше заводских) и
  сообщает происхождение каждого effective-значения;
* поиск завершается по содержательным состояниям, а не по счётчику;
* 32 — размер порции декомпозиции, хвост не теряется;
* 100 000 символов — порция, остаток сохраняется в outcome;
* 20 результатов — размер страницы, меньшее количество используется как есть.
"""
import asyncio
import dataclasses

import pytest

from services import budget_gate
from services import factcheck_planner as fsp
from services import temporal_factcheck as tf
from services.search_aggregator import AllSearchEnginesFailedException

CHAT = -100777


# ── helpers ─────────────────────────────────────────────────────────────────

def _claim(n: int) -> str:
    return " ".join(
        f"Факт номер {i} подтверждён изданием {i}." for i in range(1, n + 1))


def _plan(n_claims: int, *, with_refine: bool = False) -> fsp.RetrievalPlan:
    claims = tuple(
        fsp.ClaimUnit(claim_id=f"c{i}", text=f"Факт номер {i} подтверждён "
                                           f"изданием {i}.")
        for i in range(1, n_claims + 1))
    queries = []
    for i in range(1, n_claims + 1):
        queries.append(fsp.SearchQuery(
            text=f"факт номер {i} подтверждён изданием {i}",
            intent=fsp.INTENT_ENTITY_CHECK, claim_id=f"c{i}"))
    if with_refine:
        for i in range(1, n_claims + 1):
            queries.append(fsp.SearchQuery(
                text=f"факт номер {i} подтверждён изданием {i} уточнение",
                intent=fsp.INTENT_NUMERIC, claim_id=f"c{i}",
                purpose=fsp.QUERY_PURPOSE_REFINE))
    return fsp.RetrievalPlan(
        queries=tuple(queries), needs_web=True, needs_primary_fetch=False,
        claim_text=" ".join(c.text for c in claims), claims=claims,
        chat_id=CHAT)


def _on_limits(**overrides) -> fsp.FactcheckLimits:
    base = fsp.FactcheckLimits()
    return dataclasses.replace(base, **overrides)


def _off_limits(**overrides) -> fsp.FactcheckLimits:
    base = fsp.FactcheckLimits(
        budgets_enabled=False, budget_source="chat", budget_known=True,
        base_seconds=None, max_seconds=None, refine_calls=None,
        total_queries=None, search_text_chars=None, primary_fetches=None,
        excerpt_chars=None)
    return dataclasses.replace(base, **overrides)


class _Agg:
    """Управляемая выдача/ошибки без сети и таймеров."""

    def __init__(self, chunk="", *, error=None, delay=0.0):
        self.chunk = chunk
        self.error = error
        self.delay = delay
        self.calls = []

    async def search_relevant(self, query, max_symbols, relevance_terms=None,
                              timeout_budget=None, trace=None):
        self.calls.append(query)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.chunk

    async def search(self, query, max_symbols, trace=None):
        return await self.search_relevant(query, max_symbols)


class _SlowAgg(_Agg):
    def __init__(self, delay=0.05):
        super().__init__("", delay=delay)


class _SupportAgg(_Agg):
    """Выдача, которая подтверждает каждый запрос его же словами."""

    async def search_relevant(self, query, max_symbols, relevance_terms=None,
                              timeout_budget=None, trace=None):
        self.calls.append(query)
        return f"{query}\nhttps://example.org/{len(self.calls)}"


def _env(claim: str) -> tf.TemporalClaimEnvelope:
    return tf.TemporalClaimEnvelope(
        claim_id="claim-1", chat_id=CHAT, target_tg_message_id=1,
        target_revision=1, target_content_hash=None,
        trigger_tg_message_id=2, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1)


# ── 1. Заводские значения применяются на штатном пути ───────────────────────

def test_factory_values_are_new_and_old_limits_removed():
    assert fsp.FACTCHECK_BUDGET_SECONDS == 120.0
    assert fsp.FACTCHECK_BUDGET_SECONDS_MAX == 600.0
    assert fsp.FACTCHECK_REFINE_CALLS == 24
    assert fsp.FACTCHECK_QUERIES_TOTAL == 64
    assert fsp.FACTCHECK_SEARCH_TEXT_CHARS == 100_000
    assert fsp.FACTCHECK_PAGE_SIZE == 20
    assert fsp.FACTCHECK_CLAIM_PORTION == 32
    # Старые значения не остались ни под другим именем, ни скрытой константой.
    assert fsp._SEARCH_TEXT_BUDGET_CHARS == 100_000
    assert fsp._BUDGET_SECONDS_DEFAULT == 120.0
    assert fsp._BUDGET_SECONDS_MAX == 600.0
    assert fsp._REFINE_CALLS_DEFAULT == 24
    assert not hasattr(fsp, "_CLAIM_UNITS_HARD_CAP")


@pytest.mark.asyncio
async def test_on_deadline_and_query_budget_are_applied():
    limits = _on_limits()
    assert fsp._budget_seconds(1, limits) == 120.0
    # адаптив: +50% базового за каждую дополнительную часть, cap 600
    assert fsp._budget_seconds(2, limits) == 180.0
    assert fsp._budget_seconds(40, limits) == 600.0

    # 40 частей, все запросы не дают покрытия → 40 базовых + 24 уточняющих,
    # общий бюджет 64 (уточняющие НЕ суммируются сверх него).
    plan = _plan(40)
    agg = _Agg("Борщ рецепт свёкла\nhttps://t.example/1")
    outcome = await fsp.run_retrieval(plan, aggregator=agg, limits=limits)
    assert outcome.queries_attempted == 64
    assert outcome.refine_calls == 24
    assert outcome.budget_exhausted is True
    assert outcome.stop_reason == fsp.STOP_BUDGET_EXHAUSTED
    assert len(agg.calls) == 64


@pytest.mark.asyncio
async def test_on_page_size_20_and_smaller_provider_results_used_as_is():
    # 30 кандидатов в выдаче; страница 20 → берём 20, не «ровно 20» и не 4.
    blocks = "\n\n".join(
        f"факт номер 1 подтверждён изданием 1 блок {i}\n"
        f"https://example.org/{i}" for i in range(1, 31))
    agg = _Agg(blocks)
    outcome = await fsp.run_retrieval(
        _plan(1), aggregator=agg, limits=_on_limits())
    assert outcome.refs_collected == 20   # 20 результатов на страницу

    # Провайдер вернул меньше страницы — используем фактическое количество.
    small = "\n\n".join(
        f"факт номер 1 подтверждён изданием 1 блок {i}\n"
        f"https://small.example/{i}" for i in range(1, 4))
    out_small = await fsp.run_retrieval(
        _plan(1), aggregator=_Agg(small), limits=_on_limits())
    assert out_small.refs_collected == 3


@pytest.mark.asyncio
async def test_on_search_text_is_a_100k_portion_without_losing_tail():
    big = "факт номер 1 подтверждён изданием 1 " * 5000  # ≈160k символов
    outcome = await fsp.run_retrieval(
        _plan(1), aggregator=_Agg(big), limits=_on_limits(),
        refine_calls=0)
    assert outcome.search_text_total_chars == len(big)
    assert len(outcome.search_text) == 100_000
    assert outcome.search_text_truncated is True
    assert len(outcome.search_text_portions) == 2
    assert "".join(outcome.search_text_portions) == big


def test_claim_portion_32_keeps_tail_beyond_32():
    claim = _claim(40)
    units = fsp.build_claim_units([], claim)
    assert len(units) == 40
    assert units[-1].text.endswith("изданием 40.")
    assert fsp._CLAIM_UNITS_PORTION == 32


def test_short_text_is_not_padded_to_portion():
    units = fsp.build_claim_units([], "Короткий факт подтверждён источником.")
    assert len(units) == 1


# ── 2. OFF-контракт: никакого скрытого enforcement ──────────────────────────

@pytest.mark.asyncio
async def test_off_removes_deadline_query_and_char_caps():
    plan = _plan(40)
    agg = _Agg("Борщ рецепт свёкла\nhttps://t.example/1")
    outcome = await fsp.run_retrieval(
        plan, aggregator=agg, limits=_off_limits())
    # 40 базовых + по одному уточнению на часть: 64 и 24 больше не потолки.
    assert outcome.queries_attempted == 80
    assert outcome.refine_calls == 40
    assert outcome.budget_exhausted is False
    assert outcome.stop_reason == fsp.STOP_PATHS_EXHAUSTED

    big = "факт номер 1 подтверждён изданием 1 " * 5000
    out_text = await fsp.run_retrieval(
        _plan(1), aggregator=_Agg(big), limits=_off_limits(),
        refine_calls=0)
    assert out_text.search_text == big
    assert out_text.search_text_truncated is False
    assert out_text.search_text_total_chars == len(big)


@pytest.mark.asyncio
async def test_off_has_no_product_deadline_even_when_queries_are_slow():
    plan = _plan(3)
    agg = _SlowAgg(delay=0.02)
    outcome = await fsp.run_retrieval(
        plan, aggregator=agg, limits=_off_limits())
    assert outcome.budget_seconds is None
    assert outcome.queries_attempted == 6   # 3 базовых + 3 уточнения, cap 64/24 не действует
    assert outcome.budget_exhausted is False
    assert outcome.stop_reason == fsp.STOP_NO_PROGRESS


# ── 3. Effective-значения и происхождение (ON/OFF, сохранённые значения) ────

@pytest.mark.asyncio
async def test_saved_settings_are_preserved_and_provenance_reported(
        monkeypatch):
    values = {
        "limits.factcheck_retrieval_seconds": (300.0, "chat"),
        "limits.factcheck_retrieval_seconds_max": (900.0, "chat"),
        "limits.factcheck_refine_calls": (12, "global"),
        "limits.factcheck_max_queries_total": (100, "global"),
        "limits.factcheck_search_text_chars": (150_000, "default"),
        "limits.factcheck_page_size": (25, "default"),
        "limits.factcheck_claim_portion": (64, "default"),
        "limits.factcheck_primary_fetches": (4, "default"),
        "limits.factcheck_excerpt_chars": (2000, "default"),
    }

    async def fake_read(key, *, chat_id=None, default=None):
        return values[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=True, source="chat", chat_id=chat_id, stale=False,
            known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    limits = await fsp.resolve_factcheck_limits(CHAT)
    assert limits.budgets_enabled is True
    assert limits.budget_source == "chat"
    # Сохранённое значение выше заводского не запрещено и не подрезается.
    assert limits.base_seconds == 300.0
    assert limits.max_seconds == 900.0
    assert limits.total_queries == 100
    assert limits.search_text_chars == 150_000
    assert limits.page_size == 25
    assert limits.claim_portion == 64
    assert dict(limits.sources)["limits.factcheck_retrieval_seconds"] == "chat"
    assert dict(limits.sources)["limits.factcheck_refine_calls"] == "global"
    assert dict(limits.sources)["limits.factcheck_search_text_chars"] == "default"


@pytest.mark.asyncio
async def test_off_ignores_saved_old_budget_and_reports_source(monkeypatch):
    async def fake_read(key, *, chat_id=None, default=None):
        # Сохранённый старый бюджет 10 с / 12 запросов существует,
        # но при master OFF он не должен продолжать enforcement.
        return {
            "limits.factcheck_retrieval_seconds": (10.0, "chat"),
            "limits.factcheck_retrieval_seconds_max": (45.0, "chat"),
            "limits.factcheck_refine_calls": (3, "chat"),
            "limits.factcheck_max_queries_total": (12, "chat"),
            "limits.factcheck_search_text_chars": (8000, "chat"),
            "limits.factcheck_page_size": (4, "chat"),
            "limits.factcheck_claim_portion": (8, "chat"),
            "limits.factcheck_primary_fetches": (2, "chat"),
            "limits.factcheck_excerpt_chars": (600, "chat"),
        }[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=False, source="chat", chat_id=chat_id, known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    limits = await fsp.resolve_factcheck_limits(CHAT)
    assert limits.budgets_enabled is False
    assert limits.base_seconds is None
    assert limits.max_seconds is None
    assert limits.refine_calls is None
    assert limits.total_queries is None
    assert limits.search_text_chars is None
    assert limits.primary_fetches is None
    assert limits.excerpt_chars is None
    # Происхождение не угадывается: сохранённое значение видно как chat,
    # но enforcement по нему не действует.
    assert dict(limits.sources)["limits.factcheck_retrieval_seconds"] == "chat"
    assert dict(limits.sources)["flags.budgets_enabled"] == "chat"


@pytest.mark.asyncio
async def test_default_provenance_is_default_not_guessed_chat(monkeypatch):
    async def fake_read(key, *, chat_id=None, default=None):
        return default, "default"

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=True, source="default", chat_id=chat_id, known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    limits = await fsp.resolve_factcheck_limits(CHAT)
    assert limits.budget_source == "default"
    assert limits.base_seconds == 120.0
    assert dict(limits.sources)["limits.factcheck_retrieval_seconds"] == "default"
    assert dict(limits.sources)["limits.factcheck_page_size"] == "default"


@pytest.mark.asyncio
async def test_all_audit_layers_are_read(monkeypatch):
    values = {
        "limits.factcheck_retrieval_seconds": (33.0, "chat"),
        "limits.factcheck_retrieval_seconds_max": (44.0, "chat"),
        "limits.factcheck_refine_calls": (9, "chat"),
        "limits.factcheck_max_queries_total": (42, "chat"),
        "limits.factcheck_search_text_chars": (123_456, "chat"),
        "limits.factcheck_page_size": (11, "chat"),
        "limits.factcheck_claim_portion": (7, "chat"),
        "limits.factcheck_primary_fetches": (5, "chat"),
        "limits.factcheck_excerpt_chars": (777, "chat"),
    }

    async def fake_read(key, *, chat_id=None, default=None):
        return values[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=True, source="chat", chat_id=chat_id, known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    limits = await fsp.resolve_factcheck_limits(CHAT)
    assert (limits.base_seconds, limits.max_seconds) == (33.0, 44.0)
    assert limits.refine_calls == 9
    assert limits.total_queries == 42
    assert limits.search_text_chars == 123_456
    assert limits.page_size == 11
    assert limits.claim_portion == 7
    assert limits.primary_fetches == 5
    assert limits.excerpt_chars == 777
    meta = limits.as_meta()
    assert meta["sources"]["limits.factcheck_claim_portion"] == "chat"


@pytest.mark.asyncio
async def test_off_saved_budget_does_not_enforce_end_to_end(monkeypatch):
    """Сохранённые 10 с / 12 запросов / 8000 символов не ограничивают
    исследование при master OFF — проверено на реальном run_retrieval."""
    async def fake_read(key, *, chat_id=None, default=None):
        return {
            "limits.factcheck_retrieval_seconds": (10.0, "chat"),
            "limits.factcheck_retrieval_seconds_max": (45.0, "chat"),
            "limits.factcheck_refine_calls": (3, "chat"),
            "limits.factcheck_max_queries_total": (12, "chat"),
            "limits.factcheck_search_text_chars": (8000, "chat"),
            "limits.factcheck_page_size": (4, "chat"),
            "limits.factcheck_claim_portion": (8, "chat"),
            "limits.factcheck_primary_fetches": (2, "chat"),
            "limits.factcheck_excerpt_chars": (600, "chat"),
        }[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=False, source="chat", chat_id=chat_id, known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    limits = await fsp.resolve_factcheck_limits(CHAT)
    outcome = await fsp.run_retrieval(
        _plan(40), aggregator=_Agg("Борщ рецепт\nhttps://t.example/1"),
        limits=limits)
    assert outcome.budget_seconds is None
    assert outcome.queries_attempted == 80
    assert outcome.refine_calls == 40
    assert outcome.budget_exhausted is False
    assert outcome.budget_source == "chat"


@pytest.mark.asyncio
async def test_normal_path_uses_plan_chat_limits_without_manual_args(
        monkeypatch):
    """Штатный вызов `run_retrieval(plan, aggregator)` (как в оркестраторе)
    сам резолвит per-chat effective-настройки по `plan.chat_id`."""
    async def fake_read(key, *, chat_id=None, default=None):
        return {
            "limits.factcheck_retrieval_seconds": (30.0, "chat"),
            "limits.factcheck_retrieval_seconds_max": (60.0, "chat"),
            "limits.factcheck_refine_calls": (0, "chat"),
            "limits.factcheck_max_queries_total": (5, "chat"),
            "limits.factcheck_search_text_chars": (50_000, "chat"),
            "limits.factcheck_page_size": (7, "chat"),
            "limits.factcheck_claim_portion": (10, "chat"),
            "limits.factcheck_primary_fetches": (1, "chat"),
            "limits.factcheck_excerpt_chars": (500, "chat"),
        }[key]

    async def fake_budgets(chat_id=None):
        return budget_gate.BudgetState(
            enabled=True, source="chat", chat_id=chat_id, known=True)

    monkeypatch.setattr(
        "services.worker_settings.resolve_setting_with_source", fake_read)
    monkeypatch.setattr(budget_gate, "resolve_budgets", fake_budgets)

    agg = _Agg("Борщ рецепт\nhttps://t.example/1")
    outcome = await fsp.run_retrieval(_plan(10), aggregator=agg)
    assert outcome.queries_attempted == 5          # общий бюджет из чата
    assert outcome.budget_exhausted is True
    assert outcome.budget_source == "chat"
    assert dict(outcome.limit_sources)[
        "limits.factcheck_max_queries_total"] == "chat"
    assert agg.calls  # поиск реально выполнялся по этому пути


# ── 4. Содержательные состояния завершения ─────────────────────────────────

@pytest.mark.asyncio
async def test_stop_reason_sufficient_evidence_before_using_all_queries():
    plan = _plan(1)
    outcome = await fsp.run_retrieval(
        plan, aggregator=_SupportAgg(), limits=_on_limits())
    assert outcome.stop_reason == fsp.STOP_SUFFICIENT_EVIDENCE
    assert outcome.budget_exhausted is False
    # Заводской бюджет 64 не является обязательным минимумом.
    assert outcome.queries_attempted <= len(plan.queries)


@pytest.mark.asyncio
async def test_stop_reason_no_progress_and_provider_failure_are_distinct():
    empty = await fsp.run_retrieval(
        _plan(2), aggregator=_Agg(""), limits=_on_limits())
    assert empty.stop_reason == fsp.STOP_NO_PROGRESS
    assert empty.budget_exhausted is False

    down = await fsp.run_retrieval(
        _plan(2),
        aggregator=_Agg(error=AllSearchEnginesFailedException("down")),
        limits=_on_limits())
    assert down.stop_reason == fsp.STOP_PROVIDERS_UNAVAILABLE
    assert down.budget_exhausted is False
    assert down.provider_failures > 0


@pytest.mark.asyncio
async def test_technical_provider_budget_is_not_product_budget():
    class _BudgetError(Exception):
        reason = "budget"

    outcome = await fsp.run_retrieval(
        _plan(1), aggregator=_Agg(error=_BudgetError("timeout")),
        limits=_on_limits())
    assert outcome.budget_exhausted is False
    assert outcome.stop_reason == fsp.STOP_TECHNICAL_LIMIT
    assert outcome.provider_failures >= 1
    assert outcome.queries_used == 0


# ── 5. Политика открытий: ON — нагрузка, OFF — без потолка ─────────────────

def _multi_url_chunk(n: int) -> str:
    return "\n\n".join(
        f"факт номер 1 подтверждён изданием 1 источник {i}\n"
        f"https://source.example/{i}" for i in range(1, n + 1))


@pytest.mark.asyncio
async def test_on_fetch_policy_limits_openings_off_has_no_cap():
    seen = []

    async def fake_fetch(url, *, max_bytes=65536, timeout=4.0):
        seen.append(url)
        return ("факт номер 1 подтверждён изданием 1. " * 30) + f" {url}"

    chunk = _multi_url_chunk(5)
    plan_fetch = dataclasses.replace(_plan(1), needs_primary_fetch=True)
    on = await fsp.run_retrieval(
        plan_fetch, aggregator=_Agg(chunk), fetch_text=fake_fetch,
        limits=_on_limits(primary_fetches=2))
    assert len(seen) <= 2
    assert on.fetch_skipped_budget >= 1

    seen.clear()
    off = await fsp.run_retrieval(
        plan_fetch, aggregator=_Agg(chunk), fetch_text=fake_fetch,
        limits=_off_limits())
    assert len(seen) == 5
    assert off.fetch_skipped_budget == 0


# ── 6. Temporal: 32 части, хвост и отсутствие скрытого cap 2 ───────────────

def test_temporal_decompose_keeps_tail_beyond_32():
    parts = tf.decompose_claim(_env(_claim(40)))
    assert len(parts) == 40
    assert parts[-1].part_id == "p40"
    assert parts[-1].text.endswith("изданием 40.")
    assert tf._CLAIM_PARTS_PORTION == 32


def test_temporal_search_queries_off_and_explicit_compat():
    env = _env(_claim(10))
    parts = tf.decompose_claim(env)
    explicit = tf.search_queries_for(parts, env, max_queries=2)
    assert len(explicit) == 2
    # OFF-контракт: фиксированного cap 2 нет.
    off = _off_limits()
    all_queries = tf.search_queries_for(parts, env, limits=off)
    assert len(all_queries) == 10
