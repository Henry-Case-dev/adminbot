"""SMART-CORRECTIVE-01 §7 (S3B-INPUT) — вход чекапа и таксономия лимитов.

Контракт (owner source §7.1/§7.2):
  * существенные диагностические факты (активные сбои, состояния источников,
    причины отказа, findings журнала) доходят до payload даже за прежним
    пределом 12 000 символов; структура строк не ломается;
  * при физическом переполнении раскладка идёт по значимости, опущенное
    честно посчитано, а путь к остатку назван (существующий инструмент);
  * `limits.checkup_max_symbols` (объём отчёта) не ограничивает исследование;
  * окно свежего журнала не запрещает исторический запрос;
  * при effective budgets OFF нет искусственной обрезки доказательств по
    старым лимитам символов (остаются физические/security/no-progress гварды);
  * фиксированной обрезки memory metrics (прежние 2000) больше нет — секция
    участвует в общей ёмкости, а не отнимает бюджет скрытой константой;
  * сохранённые настройки владельца (hot-значения) не перезаписываются.

F-S3B-01 (тот же §7, diagnostics completeness): `DiagnosticCollector.
collect_for_checkup` больше не режет facts-блок искусственными 3000
символами — объём определяется тем же операторским резолвом
(`budgets ON` → `limits.checkup_max_input_symbols`, `OFF` → без символьного
потолка), поэтому полезные факты не теряются при сборке payload.
"""
import asyncio
import types

import pytest

from services import budget_gate
from services import checkup_service as svc_mod
from services import diagnostic_collector as dc
from services import evidence_bundle as bundle
from services import model_capacity
from services import runtime_probes as rp
from services.checkup_service import CheckupService


# ── Fakes: только внешние границы (LLM, capacity-адаптер, tool-loop) ────────

class _LoopResult:
    degraded = False
    reason = "ok"
    rounds_used = 1
    tool_results = ()
    research_state = {"status": "complete", "cause": "no_research_needed"}
    continuation_offers = 0

    def __str__(self):
        return "отчёт"


def _llm():
    llm = types.SimpleNamespace()
    llm._chat_model = "deepseek/deepseek-v4.1-flash"
    llm._base_url = "https://nano-gpt.com/api/v1"
    captured = {"messages": None, "tools": None}

    async def _generate(messages):
        captured["messages"] = messages
        return "отчёт"

    llm.generate = _generate
    return llm, captured


def _hot(monkeypatch, overrides=None):
    values = {"limits.checkup_max_symbols": 3000,
              "limits.checkup_max_input_symbols": 12000,
              "flags.checkup_memory_metrics_enabled": False}
    values.update(overrides or {})

    def _get(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(svc_mod.hot, "get", _get)
    return values


def _budgets(monkeypatch, enabled: bool):
    async def _resolve(chat_id=None):
        return enabled

    monkeypatch.setattr(budget_gate, "budgets_enabled", _resolve)


def _capacity(monkeypatch, window: int | None, source="verified_registry"):
    if window is None:
        async def _boom(*args, **kwargs):
            raise RuntimeError("capacity resolver down")
        monkeypatch.setattr(model_capacity, "resolve_capacity", _boom)
        monkeypatch.setattr(model_capacity, "resolve_model_context_window",
                            lambda model: (_ for _ in ()).throw(
                                RuntimeError("capacity resolver down")))
        return

    async def _resolve(base_url, model, *, slot=None, route=None):
        return types.SimpleNamespace(effective_context_window=window,
                                     source=source)

    monkeypatch.setattr(model_capacity, "resolve_capacity", _resolve)


def _tools(monkeypatch):
    """Реальный tool-loop не запускается: фиксируем переданные сообщения."""
    captured = {}

    async def _loop(llm, messages, **kwargs):
        captured["messages"] = messages
        captured["tools"] = kwargs.get("tools")
        return _LoopResult()

    monkeypatch.setattr("services.tool_loop.chat_with_tools", _loop)
    return {"router": object(), "ctx": object(),
            "schemas": [{"type": "function",
                         "function": {"name": "inspect_runtime"}}],
            "correlation_id": "checkup:s3b"}, captured


def _run(service, payload, *, runtime=None):
    telemetry: dict = {}
    report = asyncio.run(service.checkup(
        payload, used_fallback=False, telemetry=telemetry,
        tool_runtime=runtime))
    return report, telemetry


def _filler(count=200, size=120):
    return [f"2026-11-14T10:00:{i % 60:02d} host app[1]: INFO request ok "
            f"#{i} " + "x" * size for i in range(count)]


def _significant_facts():
    return [
        "DIAGNOSTIC_EVIDENCE status=degraded observed_at=2026-11-14T10:10:00",
        "- logs.checkup [degraded] declared=1 configured=1 probe_succeeded=0 "
        "healthy=0 source=logs:checkup_input",
        "    reason_code=journal_unavailable",
        "    errors_state=unknown",
        "not_checked=journal_contents,errors_total",
        "2026-11-14T10:10:01 host app[1]: ERROR llm timeout chat=1 corr=abc "
        "stage=tool_round",
        "2026-11-14T10:10:02 host app[1]: Traceback (most recent call last):",
        "2026-11-14T10:10:02 host app[1]: CRITICAL watchdog.jobs stale "
        "heartbeat REASON=no_progress",
    ]


# ── 1. Существенный факт за прежним пределом 12k доходит до payload ────────

class TestSignificantFactsSurvive:
    def test_fact_beyond_old_symbol_limit_reaches_payload(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 12000})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        payload = "\n".join(_filler(200) + _significant_facts())
        assert len(payload) > 12000
        _, telemetry = _run(CheckupService(llm), payload)
        user = captured["messages"][1]["content"]
        # Факты в хвосте payload (за 12k) не потеряны.
        assert "ERROR llm timeout" in user
        assert "Traceback (most recent call last)" in user
        assert "CRITICAL watchdog.jobs stale heartbeat" in user
        assert "DIAGNOSTIC_EVIDENCE status=degraded" in user
        assert "reason_code=journal_unavailable" in user
        assert "not_checked=journal_contents,errors_total" in user
        # Часть обычного INFO-потока опущена, факт об этом — в payload.
        assert "[checkup-input-truncated] section=logs" in user
        assert "omitted_lines=" in user
        assert telemetry["input_truncated"] is True
        assert telemetry["input_omitted_lines"] >= 1

    def test_lines_kept_whole_and_in_original_order(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 12000})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        lines = _filler(200) + _significant_facts()
        _run(CheckupService(llm), "\n".join(lines))
        user = captured["messages"][1]["content"]
        body = user[len("<system_logs>"):-len("</system_logs>")]
        out_lines = [line for line in body.split("\n")
                     if line and not line.startswith("[checkup-input")]
        original = {line: index for index, line in enumerate(lines)}
        kept_indexes = [original[line] for line in out_lines]
        assert kept_indexes == sorted(kept_indexes)     # исходный порядок
        assert all(line in original for line in out_lines)  # строки целые


# ── 2. Физическая ёмкость: приоритет + путь к остатку ───────────────────────

class TestCapacityOverflow:
    def test_overflow_packs_by_significance_with_continuation_path(
            self, monkeypatch):
        _hot(monkeypatch)
        _budgets(monkeypatch, False)                 # только физический гвард
        _capacity(monkeypatch, 12000, source="verified_registry")
        runtime, captured_loop = _tools(monkeypatch)
        llm, captured = _llm()
        payload = ("[log-source] backend=ledger window=300 read=300 matched=2 "
                   "state=ok\n" + "\n".join(_filler(200)
                                            + _significant_facts()))
        _, telemetry = _run(CheckupService(llm), payload, runtime=runtime)
        user = captured_loop["messages"][1]["content"]
        assert telemetry["input_budget_basis"] == "physical"
        assert telemetry["input_truncated"] is True
        assert "ERROR llm timeout" in user
        assert "CRITICAL watchdog.jobs" in user
        marker = [line for line in user.split("\n")
                  if "checkup-input-truncated" in line]
        assert marker and "basis=physical" in marker[0]
        # Остаток доступен существующим инструментом (не потерян).
        assert "inspect_runtime:time_window,cursor" in marker[0]
        assert captured_loop["tools"] == runtime["schemas"]

    def test_no_tools_keeps_honest_unavailable_marker(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 12000})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        _run(CheckupService(llm), "\n".join(_filler(200)
                                            + _significant_facts()))
        user = captured["messages"][1]["content"]
        marker = [line for line in user.split("\n")
                  if "checkup-input-truncated" in line]
        assert marker and "continuation=not_available_in_this_run" in marker[0]


# ── 3. Окно журнала ≠ запрет истории ───────────────────────────────────────

class TestJournalWindowVsHistory:
    def test_fresh_window_announces_historical_access(self, monkeypatch):
        _hot(monkeypatch)
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        runtime, captured_loop = _tools(monkeypatch)
        llm, _captured = _llm()
        payload = ("[log-source] backend=systemd unit=admin_bot.service "
                   "window=300 read=300 matched=2 state=ok\n"
                   "2026-11-14T10:00:00 host app[1]: ERROR boom")
        _run(CheckupService(llm), payload, runtime=runtime)
        user = captured_loop["messages"][1]["content"]
        assert "journal_window=fresh_slice_only" in user
        assert "time_window" in user
        assert "не запрещает исторический запрос" in user
        # Сами строки не подменяются и не обрезаются на маленьком payload.
        assert "ERROR boom" in user
        assert "checkup-input-truncated" not in user

    def test_no_tools_no_false_promise_about_history(self, monkeypatch):
        _hot(monkeypatch)
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        payload = ("[log-source] backend=systemd window=300 read=300\n"
                   "2026-11-14T10:00:00 host app[1]: ERROR boom")
        _run(CheckupService(llm), payload)
        user = captured["messages"][1]["content"]
        assert "journal_window=fresh_slice_only" not in user


# ── 4. Длина отчёта не ограничивает исследование ───────────────────────────

class TestReportLengthVsResearch:
    def test_report_setting_does_not_shrink_research(self, monkeypatch):
        payload = "\n".join(_filler(40) + _significant_facts())
        runs = []
        for report_length in (250, 9000):
            _hot(monkeypatch, {"limits.checkup_max_symbols": report_length})
            _budgets(monkeypatch, True)
            _capacity(monkeypatch, 131072)
            runtime, captured_loop = _tools(monkeypatch)
            llm, _captured = _llm()
            _, telemetry = _run(CheckupService(llm), payload, runtime=runtime)
            runs.append({
                "user": captured_loop["messages"][1]["content"],
                "tools": captured_loop["tools"],
                "system": captured_loop["messages"][0]["content"],
                "telemetry": telemetry,
                "report_length": report_length,
            })
        small, large = runs
        # Payload и набор инструментов исследования идентичны; отличается
        # только желаемый объём отчёта в system-промпте.
        assert small["user"] == large["user"]
        assert small["tools"] == large["tools"]
        assert str(small["report_length"]) in small["system"]
        assert str(large["report_length"]) in large["system"]
        assert small["telemetry"]["report_length_setting"] == 250
        assert large["telemetry"]["report_length_setting"] == 9000


# ── 5. budgets OFF: без искусственной обрезки доказательств ─────────────────

class TestBudgetsOff:
    def test_operator_symbol_cap_ignored_when_budgets_off(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 1500})
        _budgets(monkeypatch, False)
        _capacity(monkeypatch, 131072)          # физической ёмкости достаточно
        llm, captured = _llm()
        payload = "\n".join(_filler(120))
        assert len(payload) > 1500
        _, telemetry = _run(CheckupService(llm), payload)
        user = captured["messages"][1]["content"]
        assert telemetry["input_truncated"] is False
        assert telemetry["budgets_enabled"] is False
        assert telemetry["input_budget_chars"] is None
        assert user.count("INFO request ok") == 120      # доказательства целы
        assert "checkup-input-truncated" not in user

    def test_operator_cap_applies_when_budgets_on(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 1500})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        _run(CheckupService(llm), "\n".join(_filler(120)))
        user = captured["messages"][1]["content"]
        body = user[len("<system_logs>"):-len("</system_logs>")]
        assert len(body) <= 1500
        assert "[checkup-input-truncated] section=logs" in user

    def test_physical_guard_still_applies_when_budgets_off(self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 10 ** 6})
        _budgets(monkeypatch, False)
        _capacity(monkeypatch, 8000)
        llm, captured = _llm()
        _run(CheckupService(llm), "\n".join(_filler(300)
                                            + _significant_facts()))
        user = captured["messages"][1]["content"]
        assert "[checkup-input-truncated] section=logs" in user
        assert "basis=physical" in user
        assert "CRITICAL watchdog.jobs" in user


# ── 6. Фиксированной обрезки метрик нет; секция живёт в общей ёмкости ──────

class TestMetricsSection:
    def test_metrics_not_clipped_by_fixed_constant(self, monkeypatch, tmp_path):
        _hot(monkeypatch, {"flags.checkup_memory_metrics_enabled": True})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        big_metrics = "\n".join(f"metric_line_{i}=" + "m" * 120
                                for i in range(30))     # > 2000 символов
        assert len(big_metrics) > 2000

        async def _metrics(db, memory):
            return big_metrics

        monkeypatch.setattr(svc_mod, "collect_metrics", _metrics)
        llm, captured = _llm()
        service = CheckupService(llm, db=object(), memory=None)
        _run(service, "короткие логи")
        user = captured["messages"][1]["content"]
        assert "metric_line_0=" in user
        assert "metric_line_29=" in user           # прежний клип 2000 бы срезал
        assert "checkup-input-truncated" not in user


# ── 7. Настройки владельца сохранены и действуют ────────────────────────────

class TestOwnerSettings:
    def test_saved_values_are_effective_and_not_rewritten(self, monkeypatch):
        saved = {"limits.checkup_max_symbols": 2500,
                 "limits.checkup_max_input_symbols": 40000,
                 "flags.checkup_memory_metrics_enabled": False}
        _hot(monkeypatch, saved)
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        llm, captured = _llm()
        payload = "\n".join(_filler(200) + _significant_facts())
        _, telemetry = _run(CheckupService(llm), payload)
        user = captured["messages"][1]["content"]
        system = captured["messages"][0]["content"]
        assert telemetry["input_budget_chars"] == 40000
        assert telemetry["report_length_setting"] == 2500
        assert "2500" in system
        assert saved["limits.checkup_max_input_symbols"] == 40000  # не переписан
        # 40000 символов операторского предела хватает: 200 INFO-строк целы.
        assert user.count("INFO request ok") == 200

    def test_no_invented_default_cap_when_capacity_unavailable(
            self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 10 ** 6})
        _budgets(monkeypatch, False)
        _capacity(monkeypatch, None)             # резолвер недоступен
        llm, captured = _llm()
        payload = "\n".join(_filler(120))
        _, telemetry = _run(CheckupService(llm), payload)
        user = captured["messages"][1]["content"]
        assert telemetry["input_budget_tokens"] is None
        assert telemetry["input_truncated"] is False
        assert user.count("INFO request ok") == 120


# ── 8. Никаких новых произвольных констант ─────────────────────────────────

class TestNoNewArbitraryConstants:
    def test_fixed_metrics_clip_removed(self):
        assert not hasattr(svc_mod, "_METRICS_MAX_SYMBOLS")

    def test_input_budget_defaults_have_no_invented_cap(self):
        budget = svc_mod._InputBudget()
        assert budget.tokens is None and budget.chars is None


# ── 9. Tool-loop получает тот же payload и те же лимиты ────────────────────

class TestToolLoopPayload:
    def test_loop_receives_assembled_payload_and_unchanged_schemas(
            self, monkeypatch):
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 12000})
        _budgets(monkeypatch, True)
        _capacity(monkeypatch, 131072)
        runtime, captured_loop = _tools(monkeypatch)
        llm, _captured = _llm()
        _run(CheckupService(llm),
             "\n".join(_filler(200) + _significant_facts()), runtime=runtime)
        messages = captured_loop["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "ERROR llm timeout" in messages[1]["content"]
        assert captured_loop["tools"] == runtime["schemas"]


# ── 10. F-S3B-01: facts-блок коллектора живёт по той же политике ───────────

def _big_facts(*, keys=40, value_len=400):
    return {f"cfg_fact_{index:02d}": "v" * value_len
            for index in range(keys)}


def _big_facts_probe(monkeypatch):
    """Probe-граница: реальный collector/bundle, крупный набор фактов."""
    facts = _big_facts()

    def _handler(ctx):
        return rp._observation(
            "config", status=bundle.STATUS_OK, facts=facts,
            source_id="probe:config.effective", owner="config")

    big = rp.ProbeSpec("config.effective", "config", "big facts", "",
                       rp.READ_SCOPE_CURRENT_CHAT, handler=_handler,
                       source_owner="config")
    real_get_probe = rp.get_probe

    def _get(probe_id):
        return (big if probe_id == "config.effective"
                else real_get_probe(probe_id))

    monkeypatch.setattr(rp, "get_probe", _get)
    return facts


def _collector():
    class _Fetcher:
        last_state = "ok"
        last_journal_state = "ok"

    return dc.DiagnosticCollector(
        deps=rp.ProbeDeps(logs_fetcher=_Fetcher()),
        limits=rp.ProbeLimits(
            probe_timeout_seconds=2.0, max_output_chars=9000,
            # Прежний искусственный потолок передаётся специально: он больше
            # не управляет facts-блоком чекапа.
            max_facts_chars=3000, snapshot_ttl_seconds=5.0))


def _collect_facts():
    collector = _collector()
    result_bundle, rendered = asyncio.run(collector.collect_for_checkup(
        logs_text="2026-11-14 ERROR boom\n", used_fallback=False,
        chat_id=-100, request_id="s3b-facts"))
    return result_bundle, rendered


class TestDiagnosticCollectorFactsBudget:
    def test_facts_beyond_3000_survive_to_payload_when_budgets_off(
            self, monkeypatch):
        _big_facts_probe(monkeypatch)
        _budgets(monkeypatch, False)
        _hot(monkeypatch)
        _capacity(monkeypatch, 131072)
        _bundle, facts = _collect_facts()
        assert len(facts) > 3000
        assert "cfg_fact_00=" in facts and "cfg_fact_39=" in facts
        assert "[facts_budget_exceeded]" not in facts
        llm, captured = _llm()
        _run(CheckupService(llm), facts + "\n2026-11-14 ERROR boom")
        body = captured["messages"][1]["content"][
            len("<system_logs>"):-len("</system_logs>")]
        assert body.startswith("DIAGNOSTIC_EVIDENCE")
        assert "cfg_fact_39=" in body
        assert "[facts_budget_exceeded]" not in body

    def test_operator_budget_clips_facts_when_budgets_on(self, monkeypatch):
        _big_facts_probe(monkeypatch)
        _budgets(monkeypatch, True)
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 1500})
        result_bundle, facts = _collect_facts()
        assert "[facts_budget_exceeded]" in facts
        assert "cfg_fact_39=" not in facts
        assert len(facts) <= (1500 + len("\n[facts_budget_exceeded]")
                              + len("\n[facts_unknown] not_checked=") + 400)
        if result_bundle.not_checked:
            assert "[facts_unknown] not_checked=" in facts

    def test_owner_operator_value_governs_facts(self, monkeypatch):
        _big_facts_probe(monkeypatch)
        _budgets(monkeypatch, True)
        _hot(monkeypatch, {"limits.checkup_max_input_symbols": 40000})
        _bundle, facts = _collect_facts()
        assert "cfg_fact_39=" in facts
        assert "[facts_budget_exceeded]" not in facts

    def test_facts_structure_and_order_under_physical_overflow(
            self, monkeypatch):
        _big_facts_probe(monkeypatch)
        _budgets(monkeypatch, False)
        _hot(monkeypatch)
        _capacity(monkeypatch, 6000)
        _bundle, facts = _collect_facts()
        llm, captured = _llm()
        _run(CheckupService(llm), facts + "\n2026-11-14 ERROR boom")
        body = captured["messages"][1]["content"][
            len("<system_logs>"):-len("</system_logs>")]
        assert body.startswith("DIAGNOSTIC_EVIDENCE")
        source_lines = set(facts.split("\n"))
        kept = [line for line in body.split("\n")
                if line.startswith("    cfg_fact_")]
        assert 1 <= len(kept) <= 40
        assert all(line in source_lines for line in kept)   # строки целые
        indexes = [int(line.split("=", 1)[0].rsplit("_", 1)[1])
                   for line in kept]
        assert indexes == sorted(indexes)                   # исходный порядок
        if "[checkup-input-truncated]" in body:
            assert len(kept) < 40
