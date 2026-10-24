"""ASAP 3 Corrective §8/§9 — сводная приёмка S1-S10 / A1-A16 (срез пробелов).

Этот файл закрывает только те пункты §8, у которых не было durable-доказательства
на уровне фактического пути (сохранение → effective policy, outbound verify,
защищённые сегменты, Inspector = фактическая сборка, невидимые технические лимиты):

  * S4/S5: лимит, сохранённый штатным ``chat_params.set_chat_params``, действует
    в следующем резолве БЕЗ рестарта и не утекает в другой чат (реальный
    ``ChatParamsCache`` + реальная инвалидация, не подмена словаря теста);
  * S6: цепочка raw → Style Policy → payload: остаточное ``—`` в payload
    помечается ``conflict``/``mismatch``, чистый payload проходит ``ok``;
  * S7: дополнительно защищены разметка/атрибут со ссылкой, инлайн-код и
    version-literal (существующий тест покрывает URL/JSON/цитату);
  * S9: сводка Inspector (``_style_build_summary``) отдаёт ровно тот блок и
    те счётчики, которые собраны из global+chat, а не «желаемые» настройки;
  * S10: техническое исключение слоя видно как ``budget_excluded`` и не
    выдаётся за лимит владельца, НО локальной квоты инструкций больше нет
    (ADDENDUM #3 §2.7): слой Style Policy не может быть исключён бюджетом
    композера — он либо рендерится, либо отсутствует по своей причине;
    витрины аддитивного бюджета в Inspector/API нет.

Остальные S1-S10/A1-A16 уже доказаны файлами
``tests/test_asap3_style_hint_limits.py`` и ``tests/test_asap3_identity_aliases.py``
(матрица — ``plans/features/asap3-corrective/evidence/acceptance.md``).

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP3-ACCEPT §8 S4-S10
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import prompt_composer as pc
from services import prompt_registry as pr
from services import style_policy as sp
from web.api import speech as speech_api
from web.api.speech import _style_build_summary

CHAT_A = 301
CHAT_B = 302
EM = "\u2014"


class _Hot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Txn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    """Минимальный PG-двойник chat_profiles (только нужные SQL-запросы)."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, sql, *args):
        return "OK"

    async def fetchrow(self, sql, *args):
        if sql is chat_params.SELECT_PROFILE_SQL:
            return self.rows.get(int(args[0]))
        if sql is chat_params.UPDATE_PARAMS_SQL:
            row = {"chat_id": int(args[0]),
                   "updated_at": datetime.now(timezone.utc),
                   "chat_params": json.loads(args[1])}
            self.rows[int(args[0])] = row
            return row
        return None

    def transaction(self):
        return _Txn()


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _FakePG:
    def __init__(self, rows):
        self.pool = _Pool(_FakeConn(rows))


def soft_rows(count: int) -> list[dict]:
    return [{"id": f"soft.{i}", "text": f"Привычка {i}: живая фраза."}
            for i in range(count)]


def rich_document(*, soft_count: int = 6) -> dict:
    return sp.build_document(soft=soft_rows(soft_count), owner=1,
                             reason="asap3-accept")


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    monkeypatch.delenv("SPEECH_STYLE_POLICY_ENABLED", raising=False)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def enable_policy(monkeypatch, chat_docs=None):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot.set_config_cache(_Hot({
        "flags.speech_style_policy_enabled": True,
        sp.DOC_KEY: rich_document()}))
    rows = {chat_id: {"chat_id": chat_id, "updated_at": None,
                      "chat_params": {"v": 1, "overrides": dict(overrides)}}
            for chat_id, overrides in (chat_docs or {}).items()}
    pg = _FakePG(rows)
    cache = chat_params.ChatParamsCache(pg)
    chat_params.set_chat_params_cache(cache)
    assert mca_gates.speech_style_policy_enabled() is True
    return pg


# ═══ S4/S5: сохранённый лимит действует без рестарта, чаты изолированы ══════

@pytest.mark.asyncio
async def test_s4_saved_limit_applies_next_resolve_without_restart(monkeypatch):
    """S4 на фактическом пути save → инвалидация → effective policy.

    Существующий тест S4 меняет словарь фейкового кэша напрямую; здесь лимит
    пишется штатным ``chat_params.set_chat_params`` (реальная транзакция,
    реальная инвалидация ``ChatParamsCache``), а резолв идёт через
    ``effective_style_policy`` без пересоздания процесса/резолвера.
    """
    pg = enable_policy(monkeypatch, {CHAT_A: {}})
    first = await sp.effective_style_policy(CHAT_A)
    assert first.hint_limits == {"max_chars": 0, "max_items": 0}
    assert first.hint_included == first.hint_total

    await chat_params.set_chat_params(
        CHAT_A,
        {"overrides": {sp.DOC_KEY: {"hint_limits": {"max_items": 2}}}},
        pg=pg)

    second = await sp.effective_style_policy(CHAT_A)
    assert second.hint_limits == {"max_chars": 0, "max_items": 2}
    assert second.hint_limit_sources["max_items"] == "chat"
    assert second.hint_included == 2
    assert second.hint_included < second.hint_total
    # S5: второй чат не видит лимит первого.
    other = await sp.effective_style_policy(CHAT_B)
    assert other.hint_limits == {"max_chars": 0, "max_items": 0}
    assert other.hint_included == other.hint_total


# ═══ S6: остаточное тире в payload — конфликт, а не «styled» ════════════════

def test_s6_outbound_verify_flags_remaining_dash():
    policy = sp.effective_policy_sync(None, None, context="regular")
    bad = sp.verify_outbound_payload(f"осталось {EM} тире", policy=policy)
    assert bad.payload_status == "mismatch"
    rows = [r for r in bad.results if r.kind == "dash"]
    assert rows and rows[0].status == sp.STATUS_CONFLICT
    assert rows[0].reason.startswith("payload_still_violates")

    clean, _ = sp.StylePolicyValidator(policy).run(f"было {EM} стало")
    ok = sp.verify_outbound_payload(clean, policy=policy)
    assert ok.payload_status == "ok"
    assert EM not in clean


# ═══ S7: разметка/атрибут ссылки/инлайн-код/версия не повреждены ═════════════

def test_s7_markup_link_code_and_version_survive():
    policy = sp.effective_policy_sync(None, None, context="regular")
    text = (f'<a href="https://x.org/a{EM}b">ссылка</a> тут {EM} речь, '
            f'код `x{EM}y` и версия 2.58.110.')
    out, results = sp.StylePolicyValidator(policy).run(text)
    assert f'<a href="https://x.org/a{EM}b">' in out     # атрибут цел
    assert f"`x{EM}y`" in out                            # инлайн-код цел
    assert "2.58.110" in out                             # версия цела
    assert " тут - речь" in out                          # обычная речь заменена
    row = next(r for r in results if r.kind == "dash")
    assert row.status == sp.STATUS_REPAIRED
    assert dict(row.detail)["protected_kept"] >= 1


# ═══ S9: Inspector отдаёт фактическую сборку (global+chat) ══════════════════

def test_s9_inspector_summary_matches_actual_assembly():
    global_doc = rich_document(soft_count=6)
    chat_doc = {"hint_limits": {"max_items": 3}}
    policy = sp.effective_policy_sync(global_doc, chat_doc, context="regular")
    summary = _style_build_summary(policy, [{
        "layer": "style_policy_hint", "rendered": True,
        "skip_reason": "", "chars": len(policy.hint), "tokens": 1,
        "revision": policy.revision}])
    assert summary["hint_text"] == policy.hint, "Inspector показал не тот блок"
    assert summary["total_items"] == policy.hint_total
    assert summary["included_items"] == policy.hint_included
    assert summary["included_items"] == 3
    assert summary["source"] == "chat"
    assert summary["limits"]["sources"]["max_items"] == "chat"
    assert summary["payload_included"] is True
    assert summary["layer"]["state"] == "rendered"
    assert len(summary["excluded"]) == \
        policy.hint_total - policy.hint_included
    assert {row["reason"] for row in summary["excluded"]} == {"user_limit"}
    # Редакция указывает на реально включённые строки, а не на весь документ.
    assert len(summary["hint_text"].splitlines()) == \
        len(policy.hint.splitlines())


# ═══ S10: технический бюджет виден и не выдаётся за лимит владельца ═════════

def test_s10_budget_exclusion_is_not_disguised_as_user_limit():
    policy = sp.effective_policy_sync(
        rich_document(soft_count=6), {"hint_limits": {"max_items": 2}},
        context="regular")
    summary = _style_build_summary(policy, [{
        "layer": "style_policy_hint", "rendered": False,
        "skip_reason": "budget_excluded", "chars": 0, "tokens": 0,
        "revision": policy.revision}])
    assert summary["layer"]["state"] == "budget_excluded"
    assert summary["payload_included"] is False
    assert summary["hint_text"] == policy.hint   # текст честный, но не отправлен
    # Потеря от лимита владельца и потеря от бюджета не смешиваются.
    assert {row["reason"] for row in summary["excluded"]} == {"user_limit"}
    assert summary["limits"]["max_items"] == 2
    assert summary["limits"]["off"] is False


def test_s10_rules_cap_is_blocking_diagnostic_not_silent_cut():
    rules = [{"id": f"r{i}", "kind": "emoji", "strictness": "hard",
              "reason": "r"} for i in range(sp.RULES_MAX + 1)]
    normalized, issues = sp.validate_document({"rules": rules})
    assert len(normalized["rules"]) == sp.RULES_MAX
    assert "rules_truncated" in issues
    assert "rules_truncated" in sp.fatal_document_issues(issues)
    view = sp.style_policy_view({"rules": rules}, None)
    assert "rules_truncated" in view["document"]["global_issues"]


# ═══ Проверка, что композер не имеет своего «тихого» лимита hint ════════════

def test_s10_composer_style_layer_has_no_local_quota(monkeypatch):
    """QUOTA-REMOVAL (A3): hint рендерится всегда — прод-симптом устранён.

    Прежний `COMPOSER_LAYER_BUDGET_TOKENS=1` давал `budget_excluded` для
    Style_Policy_Hint даже при отключённом бюджете чата. Теперь слой Style
    Policy **не** исключается локальным бюджетом: старая переменная окружения
    ничего не возвращает, слой физически присутствует в запросе.
    """
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "1")
    policy = sp.effective_policy_sync(rich_document(soft_count=8), None,
                                      context="regular")
    ref = pc.StylePolicyRef(
        hint=policy.hint, revision=policy.revision or "",
        source=policy.source, rule_count=len(policy.rules),
        soft_count=len(policy.soft_instructions),
        hint_total=policy.hint_total, hint_included=policy.hint_included,
        hint_excluded=tuple(policy.hint_excluded),
        hint_limits=tuple(sorted((policy.hint_limits or {}).items())),
        hint_limited_by=policy.hint_limited_by)
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=CHAT_A,
        channel="plain", html_safe=True, run_id="run-s10",
        base_prompt="КАНАЛ.", base_source="global",
        style_policy=ref,
        gates=pc.GateState(unified_composer_enabled=True))
    manifest = pc.compose_prompt(plan)
    trace = next(t for t in manifest.layers
                 if t.layer == "style_policy_hint")
    assert trace.rendered is True
    assert trace.skip_reason == ""
    # Фактическое присутствие слоя в payload — не только флаг трейса.
    assert ref.hint in manifest.system
    assert policy.hint in manifest.system
    # Ни один слой не списан на бюджет инструкций: причина исключения
    # `budget_excluded` для инструкций больше не существует.
    assert [t.layer for t in manifest.layers
            if t.skip_reason == "budget_excluded"] == []
    assert "budget_excluded" not in pc.SKIP_REASONS
    # Исключений самой подсказки по бюджету тоже нет (только лимит владельца).
    assert {row.reason for row in policy.hint_excluded} <= {"user_limit"}


def test_s10_no_composer_budget_plumbing_in_inspector():
    """QUOTA-REMOVAL (A1/A4): витрины аддитивного бюджета нет ни в API, ни в UI.

    `_composer_budget()` удалён вместе с механизмом; `core_selection_view`
    больше не принимает инертный аргумент, а срез Core в Inspector не содержит
    поля бюджета (нечему показывать «квоту», которой нет).
    """
    assert not hasattr(speech_api, "_composer_budget")
    assert "budget_tokens" not in inspect.signature(
        pr.core_selection_view).parameters
    assert "budget_tokens" not in inspect.signature(
        pr.core_selection).parameters
    view = pr.core_selection_view(None, source="default")
    assert not [key for key in view if "budget" in key]
    assert "budget_tokens" not in json.dumps(view, ensure_ascii=False)
    # Предпросмотр Core в Inspector собирается без квоты (реальный путь API).
    ref = asyncio.run(speech_api._core_ref_from_doc(None, source="default"))
    assert ref.text
    assert ref.detail_level in {"full", "compact"}

