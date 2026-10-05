"""MCA-11 `mca-11-tools-costs` — focused блок C (T-4953…T-4955).

Покрытие: A28 (денежные лимиты OFF при остальном ON; поведение 2.58.56),
sentinel-семантика (не задан/0/<0/>0), семантика будущего включения
(резерв конкурентных операций, overshoot/reconcile, unknown ≠ потолок,
приоритет direct > autonomous > maintenance, платные вызовы стоп / intake
жив) и неизменность существующих финансовых настроек владельца.
"""
import json
from pathlib import Path

import pytest

from config.settings import Settings, settings
from services import budget_limits, mca_gates, mca_money_limits as ml
from services import param_catalog as pc

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    ml.reset_state()
    yield
    ml.reset_state()


def _activate(monkeypatch, **caps):
    """Тестовая активация: master ON + caps (только явно переданные)."""
    monkeypatch.setattr(Settings, "MCA_MONEY_LIMITS_ENABLED", True)
    for scope, value in caps.items():
        monkeypatch.setattr(Settings, ml._SCOPE_ENV[scope], value)


# ── T-4953/A28: OFF по умолчанию, поведение baseline ────────────────────────

class TestA28DefaultOff:
    def test_master_default_off_and_registered(self):
        assert Settings.MCA_MONEY_LIMITS_ENABLED is False
        assert ml.enabled() is False
        assert mca_gates.money_limits_enabled() is False
        default, parity = mca_gates.KILL_SWITCHES["MCA_MONEY_LIMITS_ENABLED"]
        assert default is False
        assert "2.58.56" in parity

    def test_k4_registered_on(self):
        assert Settings.MCA_TOOL_CHAIN_STAGES_ENABLED is True
        assert mca_gates.tool_chain_stages_enabled() is True
        default, _ = mca_gates.KILL_SWITCHES["MCA_TOOL_CHAIN_STAGES_ENABLED"]
        assert default is True

    def test_off_inert_even_with_zero_caps(self, monkeypatch):
        """OFF → ни один вызов не затрагивается, даже если caps выставлены."""
        monkeypatch.setattr(Settings, "MCA_MONEY_LIMIT_DIRECT_USD", 0.0)
        decision = ml.check_and_reserve("direct", 10.0, price_known=True)
        assert decision["allowed"] is True
        assert decision["state"] == "off"
        assert decision["spent_usd"] == 0.0
        assert decision["reserved_usd"] == 0.0
        rec = ml.reconcile(5.0, price_known=True)
        assert rec["reconciled"] is False and rec["state"] == "off"
        assert ml.effective_state()["enabled"] is False

    def test_no_numeric_defaults_no_hidden_budget(self):
        """Скрытого «рекомендованного бюджета» нет: env-дефолты — None."""
        assert Settings.MCA_MONEY_LIMIT_DIRECT_USD is None
        assert Settings.MCA_MONEY_LIMIT_AUTONOMOUS_USD is None
        assert Settings.MCA_MONEY_LIMIT_MAINTENANCE_USD is None
        for name in ("MCA_MONEY_LIMITS_ENABLED", "MCA_MONEY_LIMIT_DIRECT_USD",
                     "MCA_MONEY_LIMIT_AUTONOMOUS_USD",
                     "MCA_MONEY_LIMIT_MAINTENANCE_USD",
                     "MCA_TOOL_CHAIN_STAGES_ENABLED"):
            assert name not in pc.REGISTRY

    def test_intake_paths_do_not_call_money_limits(self):
        """Лимит не блокирует приём/сохранение: intake-пути модуль не зовут."""
        targets = [ROOT / "services/database.py", ROOT / "bot.py"]
        targets += list((ROOT / "handlers").glob("*.py"))
        for path in targets:
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "mca_money_limits" not in text, path.name

    def test_no_runtime_callers_off_parity(self):
        """OFF-паритет 2.58.56: механизм реализован и инертен — ни один
        runtime-модуль его не вызывает (потребители — mca-09/10b)."""
        for path in (ROOT / "services").glob("*.py"):
            if path.name == "mca_money_limits.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "mca_money_limits" not in text, path.name


# ── T-4953: sentinel-семантика (REUSE budget_limits) ────────────────────────

class TestSentinelSemantics:
    def test_unset_means_no_limit(self, monkeypatch):
        _activate(monkeypatch)
        assert ml.scope_state("direct") == "unset"
        d = ml.check_and_reserve("direct", 99.0, price_known=True)
        assert d["allowed"] is True and d["limit_usd"] is None

    def test_zero_means_forbidden(self, monkeypatch):
        _activate(monkeypatch, direct=0)
        assert ml.scope_state("direct") == "forbidden"
        d = ml.check_and_reserve("direct", None, price_known=False)
        assert d["allowed"] is False
        assert d["reason"] == "financial_limit_reached"

    def test_negative_means_unlimited(self, monkeypatch):
        _activate(monkeypatch, direct=-1)
        assert ml.scope_state("direct") == "unlimited"
        for _ in range(3):
            assert ml.check_and_reserve("direct", 50.0,
                                        price_known=True)["allowed"] is True

    def test_positive_is_cap(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        assert ml.scope_state("direct") == "cap"
        assert ml.scope_limit_usd("direct") == 1.0

    def test_semantics_reuse_budget_limits(self, monkeypatch):
        """0/<0/>0 совпадают с budget_state (reuse, не второй словарь)."""
        for raw, expected in ((0, "forbidden"), (-2, "unlimited"),
                              (3, "cap"), ("мусор", "forbidden")):
            monkeypatch.setattr(Settings, "MCA_MONEY_LIMIT_DIRECT_USD", raw)
            assert ml.scope_state("direct") == expected
            assert budget_limits.budget_state(raw) == expected

    def test_invalid_scope_denied_when_on(self, monkeypatch):
        _activate(monkeypatch)
        assert ml.normalize_scope("nope") is None
        d = ml.check_and_reserve("nope", 1.0, price_known=True)
        assert d["allowed"] is False and d["state"] == "invalid_scope"
        assert d["reason"] == "job_not_allowed"


# ── T-4954: резерв/overshoot/reconcile/unknown ──────────────────────────────

class TestReserveReconcile:
    def test_concurrent_reservation_blocks_at_cap(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        first = ml.check_and_reserve("direct", 0.6, price_known=True)
        assert first["allowed"] is True and first["reservation_usd"] == 0.6
        second = ml.check_and_reserve("direct", 0.6, price_known=True)
        assert second["allowed"] is True
        assert second["reserved_usd"] == 1.2       # конкурентные резервы
        third = ml.check_and_reserve("direct", None, price_known=False)
        assert third["allowed"] is False            # known spent+reserved ≥ cap
        assert third["reason"] == "financial_limit_reached"

    def test_reconcile_releases_and_overshoot(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        ml.check_and_reserve("direct", 0.5, price_known=True)
        rec = ml.reconcile(0.9, price_known=True)   # overshoot неточной оценки
        assert rec["released_usd"] == 0.5
        assert rec["spent_usd"] == 0.9 and rec["reserved_usd"] == 0.0
        # Факт (0.9) согласован: следующий резерв при 0.9 + est > cap не нужен —
        # deny только при spent+reserved ≥ cap (0.9 < 1.0 → allow).
        assert ml.check_and_reserve("direct", None,
                                    price_known=False)["allowed"] is True
        rec2 = ml.reconcile(0.2, price_known=True)
        assert rec2["spent_usd"] == 1.1             # overshoot виден, не скрыт

    def test_unknown_price_no_reservation_no_ceiling_promise(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        d = ml.check_and_reserve("direct", None, price_known=False)
        assert d["allowed"] is True
        assert d["reservation_usd"] == 0.0
        assert d["unknown_in_flight"] == 1
        assert d["ceiling_exact"] is False          # абсолютный потолок не обещан
        # Второй unknown не создаёт резерва — deny только по known spent.
        d2 = ml.check_and_reserve("direct", None, price_known=False)
        assert d2["allowed"] is True and d2["reserved_usd"] == 0.0

    def test_unknown_deny_only_after_known_spent_reaches_cap(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        ml.check_and_reserve("direct", None, price_known=False)
        assert ml.check_and_reserve("direct", None,
                                    price_known=False)["allowed"] is True
        ml.reconcile(1.0, price_known=True)
        denied = ml.check_and_reserve("direct", None, price_known=False)
        assert denied["allowed"] is False           # known spent (1.0) ≥ cap

    def test_reconcile_unknown_releases_in_flight(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        ml.check_and_reserve("direct", None, price_known=False)
        rec = ml.reconcile(None, price_known=False)
        assert rec["reconciled"] is True
        assert rec["unknown_in_flight"] == 0 and rec["ceiling_exact"] is True

    def test_estimate_bool_and_garbage_safe(self, monkeypatch):
        _activate(monkeypatch, direct=1.0)
        d = ml.check_and_reserve("direct", True, price_known=True)
        assert d["allowed"] is True and d["reservation_usd"] == 0.0
        assert ml.check_and_reserve("direct", "abc",
                                    price_known=True)["allowed"] is True


# ── T-4954: приоритеты и независимые scope'ы ────────────────────────────────

class TestPriority:
    def test_priority_and_degradation_order(self):
        assert ml.PRIORITY == {"direct": 0, "autonomous": 1, "maintenance": 2}
        assert ml.degradation_order() == ("maintenance", "autonomous", "direct")
        assert ml.DEGRADATION_ORDER[0] == "maintenance"
        assert ml.DEGRADATION_ORDER[-1] == "direct"

    def test_scopes_independent(self, monkeypatch):
        _activate(monkeypatch, direct=0, maintenance=5.0)
        assert ml.check_and_reserve("direct", None,
                                    price_known=False)["allowed"] is False
        assert ml.check_and_reserve("autonomous", None,
                                    price_known=False)["allowed"] is True
        assert ml.check_and_reserve("maintenance", 1.0,
                                    price_known=True)["allowed"] is True

    def test_limit_stops_paid_call_intake_alive(self, monkeypatch):
        """Fixture T-4954: лимит исчерпан → платные вызовы стоп, intake жив."""
        _activate(monkeypatch, direct=0)
        intake: list[str] = []
        paid_calls: list[str] = []

        def intake_message(text: str) -> None:
            # Приём/сохранение исходных сообщений лимитом не гейтится.
            intake.append(text)

        def paid_call() -> str:
            decision = ml.check_and_reserve("direct", None, price_known=False)
            if not decision["allowed"]:
                return f"denied:{decision['reason']}"
            paid_calls.append("call")
            return "sent"

        intake_message("привет")
        assert paid_call() == "denied:financial_limit_reached"
        assert paid_calls == []
        assert intake == ["привет"]                 # intake жив


# ── T-4953: существующие настройки владельца не стираются ───────────────────

class TestOwnerSettings:
    def test_owner_settings_untouched_and_shown(self):
        state = ml.effective_state()
        owner = {row["name"]: row for row in state["owner_settings"]}
        for name in ("IMAGE_DAILY_LIMIT_ENABLED",
                     "WORKER_DAILY_IMAGE_CALLS_PER_CHAT",
                     "WORKER_DAILY_IMAGE_CALLS_GLOBAL",
                     "CHAT_GLOBAL_KEY_BUDGET_TOKENS",
                     "CHAT_GLOBAL_KEY_BUDGET_REQUESTS",
                     "WORKER_DAILY_LLM_CALLS_PER_CHAT"):
            assert name in owner, name
            assert owner[name]["value"] == getattr(settings, name)
            assert owner[name]["kind"] != "usd"     # unit/токены ≠ валюта
        assert "не стираются" in state["owner_settings_note"]
        assert state["absolute_ceiling"] is False

    def test_difference_new_vs_owner(self):
        """Новые лимиты — USD по scope; старые — единицы/вызовы/токены."""
        state = ml.effective_state()
        assert set(state["scopes"]) == {"direct", "autonomous", "maintenance"}
        assert state["priority_order"] == ["direct", "autonomous", "maintenance"]
        assert all(row["kind"] in ("unit_calls", "tokens", "requests", "calls")
                   for row in state["owner_settings"])

    def test_state_json_safe(self):
        """R17: состояние — только числа/коды/имена (без текстов/секретов)."""
        blob = json.dumps(ml.effective_state(), ensure_ascii=False)
        assert "MCA_MONEY_LIMIT_DIRECT_USD" in blob
        assert "prompt" not in blob.lower()
