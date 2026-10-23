"""ASAP 3 Corrective §1/§3 — Style Policy: лимиты hint и правило тире.

Покрытие (source-2026-10-23 §1.1-1.5, §3.1-3.3, §8 S1-S10):
  * S1/S2: OFF-лимит не теряет ни одной инструкции (>400 симв., >5 привычек);
  * S3: включённый лимит виден в структуре/витрине, исключённые правила — с
    причиной ``user_limit``;
  * S4/S5: смена лимита применяется без рестарта; чаты изолированы;
  * S6-S8: тире заменяется в обычной речи, защищённые сегменты целы,
    выключенное правило не вмешивается;
  * S9: структура отдаёт фактически включённые инструкции;
  * S10: потолок привычек/правил больше не режет документ молча.

TEST-LIFECYCLE: CONTRACT owner=ASAP3 §1.1-1.5,§3.1-3.3 (asap3-corrective)
"""
from __future__ import annotations

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import prompt_style_blocks as psb
from services import style_policy as sp

CHAT_A = 301
CHAT_B = 302
EM = "\u2014"


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


@pytest.fixture(autouse=True)
def _clean_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def enable_policy(monkeypatch, *, global_doc=None, chat_overrides=None):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    values = {"flags.speech_style_policy_enabled": True}
    if global_doc is not None:
        values[sp.DOC_KEY] = global_doc
    hot.set_config_cache(FakeHot(values))
    chat_params.set_chat_params_cache(FakeChatCache(chat_overrides or {}))
    assert mca_gates.speech_style_policy_enabled() is True


def soft_rows(count: int, *, start: int = 0) -> list[dict]:
    return [{"id": f"soft.{i}",
             "text": (f"Привычка {i}: живая фраза без канцелярита и без "
                      f"лишних вводных конструкций в ответе.")}
            for i in range(start, start + count)]


def rich_document(*, soft_count: int = 8) -> dict:
    return sp.build_document(
        presets=("no_quotes", "no_trailing_period", "no_emoji"),
        rules=[{"id": "p.chars", "kind": "forbidden_chars", "strictness": "hard",
                "params": {"chars": ["·"]}, "reason": "r"},
               {"id": "p.br", "kind": "line_breaks", "strictness": "hard",
                "params": {"max_breaks": 2}, "reason": "r"}],
        soft=soft_rows(soft_count), owner=1, reason="asap3-test")


# ═══ S1/S2: OFF-лимит = все инструкции в фактической сборке ═════════════════

def test_s1_long_hint_is_not_truncated_when_limit_off():
    policy = sp.effective_policy_sync(rich_document(), None, context="regular",
                                     extent="one_word")
    assert policy.hint_limits == {"max_chars": 0, "max_items": 0}
    assert policy.hint_limited_by == ""
    assert policy.hint_truncated is False
    assert len(policy.hint) > 400, "S1: блок должен превышать прежние 400"
    assert policy.hint_included == policy.hint_total
    assert policy.hint_excluded == ()
    # Каждая активная инструкция реально в блоке, порядок детерминирован.
    assert psb.HINT_QUOTES_HARD in policy.hint
    assert psb.HINT_TRAILING_PERIOD_HARD in policy.hint
    assert psb.HINT_EMOJI_HARD in policy.hint
    assert psb.HINT_FORBIDDEN_CHARS in policy.hint
    assert "Переносы строк: не больше 2." in policy.hint


def test_s2_more_than_five_soft_instructions_all_present():
    doc = rich_document(soft_count=9)
    policy = sp.effective_policy_sync(doc, None, context="regular")
    assert len(policy.soft_instructions) == 9
    for index in range(9):
        assert f"Привычка {index}:" in policy.hint, index
    assert policy.hint_included == policy.hint_total
    assert policy.hint_limited_by == ""


# ═══ S3/S9: включённый лимит виден, структура = фактическая сборка ══════════

def test_s3_user_limit_overflow_is_visible_with_reason():
    doc = rich_document(soft_count=6)
    chat_doc = {"hint_limits": {"max_items": 3}}
    policy = sp.effective_policy_sync(doc, chat_doc, context="regular")
    assert policy.hint_limits == {"max_chars": 0, "max_items": 3}
    assert policy.hint_limit_sources["max_items"] == "chat"
    assert policy.hint_included == 3
    assert policy.hint_total > policy.hint_included
    assert "items" in policy.hint_limited_by
    assert policy.hint_excluded, "исключённые правила обязаны быть перечислены"
    assert {row["reason"] for row in policy.hint_excluded} == {"user_limit"}
    view = sp.style_policy_view(doc, chat_doc, context="regular")
    assert view["hint_render"]["overflow"] is True
    assert view["hint_render"]["included_items"] == 3
    assert view["hint_limits"]["max_items"] == 3
    assert view["hint_limits"]["sources"]["max_items"] == "chat"
    assert view["hint_limits"]["current_chars"] == len(view["hint"])


def test_s3_chars_limit_drops_whole_lines_only():
    doc = rich_document(soft_count=0)
    full = sp.effective_policy_sync(doc, None, context="regular")
    limit = len(full.hint) - 30
    policy = sp.effective_policy_sync(
        doc, {"hint_limits": {"max_chars": limit}}, context="regular")
    assert len(policy.hint) <= limit
    assert "chars" in policy.hint_limited_by
    assert policy.hint_truncated is False
    # Ни одна оставшаяся строка не обрезана посередине.
    for line in policy.hint.splitlines()[1:-1]:
        assert line.startswith("- ")
        assert line.strip() != "-"


def test_s9_structure_reports_actually_included_rules():
    doc = sp.build_document(
        presets=("no_quotes",),
        rules=[{"id": "p.off", "kind": "emoji", "strictness": "hard",
                "reason": "r"},
               {"id": "p.disabled", "kind": "emoji", "strictness": "hard",
                "enabled": False, "reason": "выключено владельцем"}],
        owner=1)
    policy = sp.effective_policy_sync(doc, None, context="regular")
    view = sp.style_policy_view(doc, None, context="regular")
    included = set(psb.render_style_policy_hint(policy).included_keys)
    assert "p.off" in included
    assert "p.disabled" not in included
    assert view["hint_render"]["included_items"] == policy.hint_included
    assert view["hint_render"]["excluded"] == []       # лимитов нет — потерь нет
    bullets = [line for line in policy.hint.splitlines() if line.startswith("- ")]
    assert len(bullets) == policy.hint_included


# ═══ S4/S5: без рестарта и с изоляцией чатов ════════════════════════════════

@pytest.mark.asyncio
async def test_s4_limit_change_applies_without_restart(monkeypatch):
    doc = rich_document(soft_count=6)
    enable_policy(monkeypatch, global_doc=doc)
    first = await sp.effective_style_policy(CHAT_A)
    assert first.hint_included == first.hint_total
    # Владелец сохранил лимит в чат: следующий резолв видит новое значение.
    cache = chat_params.get_chat_params_cache()
    cache.overrides[CHAT_A] = {
        sp.DOC_KEY: {"hint_limits": {"max_items": 2}}}
    second = await sp.effective_style_policy(CHAT_A)
    assert second.hint_limits == {"max_chars": 0, "max_items": 2}
    assert second.hint_included == 2
    assert second.hint_included < first.hint_included


@pytest.mark.asyncio
async def test_s5_chat_limits_do_not_leak_between_chats(monkeypatch):
    doc = rich_document(soft_count=6)
    enable_policy(monkeypatch, global_doc=doc,
                  chat_overrides={CHAT_A: {
                      sp.DOC_KEY: {"hint_limits": {"max_items": 2}}}})
    a = await sp.effective_style_policy(CHAT_A)
    b = await sp.effective_style_policy(CHAT_B)
    assert a.hint_included == 2 and a.hint_limited_by
    assert b.hint_included == b.hint_total and b.hint_limited_by == ""
    assert b.hint_limits == {"max_chars": 0, "max_items": 0}


# ═══ S6-S8: правило тире ════════════════════════════════════════════════════

def test_s6_dash_is_replaced_in_plain_speech():
    policy = sp.effective_policy_sync(None, None, context="regular")
    assert policy.rules_for_kind("dash"), "заводское правило тире не активно"
    out, results = sp.StylePolicyValidator(policy).run(
        f"Это {EM} обычная речь. {EM} И ещё раз.")
    assert out == "Это - обычная речь. - И ещё раз."
    row = next(r for r in results if r.kind == "dash")
    assert row.status == sp.STATUS_REPAIRED and row.reason == "dash_replaced"
    # Идемпотентность: повторный проход ничего не меняет.
    again, _ = sp.StylePolicyValidator(policy).run(out)
    assert again == out


@pytest.mark.asyncio
async def test_s6_dash_reaches_outbound_pass(monkeypatch):
    enable_policy(monkeypatch)
    policy = await sp.effective_style_policy(CHAT_A)
    outcome = await sp.apply_style_policy(
        f"Ну {EM} вот так", chat_id=0, policy=policy, record=False)
    assert outcome.text == "Ну - вот так"
    assert outcome.styled is True


def test_s7_protected_segments_keep_original_dash():
    policy = sp.effective_policy_sync(None, None, context="regular")
    text = (f"Смотри https://example.org/a{EM}b, код `x = \"a {EM} b\"`, "
            f"данные {{\"k\": \"a {EM} b\"}} и цитата: дословно {EM} так.")
    validator = sp.StylePolicyValidator(
        policy, extra_protected=[f"дословно {EM} так"])
    out, results = validator.run(text)
    assert f"https://example.org/a{EM}b" in out
    assert f"`x = \"a {EM} b\"`" in out
    assert f"{{\"k\": \"a {EM} b\"}}" in out
    assert f"дословно {EM} так" in out
    assert out.count(EM) == 4, "защищённые тире не тронуты"
    row = next(r for r in results if r.kind == "dash")
    assert row.status == sp.STATUS_EXEMPTED


def test_s8_disabled_dash_rule_does_not_touch_text():
    doc = sp.build_document(rules=[{
        "id": sp.DASH_FACTORY_ID, "kind": "dash", "strictness": "hard",
        "enabled": False, "reason": "в этом чате тире разрешено"}], owner=1)
    policy = sp.effective_policy_sync(doc, None, context="regular")
    assert not [r for r in policy.rules_for_kind("dash")]
    text = f"Оставляем {EM} как есть."
    out, results = sp.StylePolicyValidator(policy).run(text)
    assert out == text
    assert not [r for r in results if r.kind == "dash"]
    # Чатовое выключение через чат-документ (наследование id) работает так же.
    chat_off = sp.effective_policy_sync(
        None, {"rules": [{"id": sp.DASH_FACTORY_ID, "kind": "dash",
                          "strictness": "hard", "enabled": False}]},
        context="regular")
    assert sp.StylePolicyValidator(chat_off).run(text)[0] == text


# ═══ документ: round-trip лимитов и S10 (видимые потолки) ═══════════════════

def test_hint_limits_round_trip_and_inheritance():
    normalized, issues = sp.validate_document(
        {"hint_limits": {"max_chars": 120, "max_items": 0}})
    assert issues == ()
    assert normalized["hint_limits"] == {"max_chars": 120, "max_items": 0}
    twice, _ = sp.validate_document(normalized)
    assert twice["hint_limits"] == normalized["hint_limits"]
    limits, sources = sp.merge_hint_limits(
        {"hint_limits": {"max_chars": 120, "max_items": 7}},
        {"hint_limits": {"max_items": 0}})
    assert limits == {"max_chars": 120, "max_items": 0}
    assert sources == {"max_chars": "global", "max_items": "chat"}


def test_negative_or_invalid_limit_is_blocking_not_silent():
    _, issues = sp.validate_document({"hint_limits": {"max_chars": -5}})
    assert "hint_limit_negative:max_chars" in issues
    assert sp.fatal_document_issues(issues), "отрицательный лимит блокирует save"
    _, bad = sp.validate_document({"hint_limits": {"max_items": "много"}})
    assert "hint_limit_invalid:max_items" in bad
    assert sp.fatal_document_issues(bad)


def test_s10_soft_instruction_cap_no_longer_silent():
    # 13 привычек раньше молча обрезались; теперь документ сохраняется целиком.
    normalized, issues = sp.validate_document(
        {"soft_instructions": [{"id": f"s{i}", "text": f"правило {i}"}
                               for i in range(13)]})
    assert len(normalized["soft_instructions"]) == 13
    assert "soft_truncated" not in issues
    # За фактическим потолком — не тишина, а блокирующая диагностика.
    over, over_issues = sp.validate_document(
        {"soft_instructions": [{"id": f"s{i}", "text": f"правило {i}"}
                               for i in range(sp.SOFT_INSTRUCTIONS_MAX + 1)]})
    assert len(over["soft_instructions"]) == sp.SOFT_INSTRUCTIONS_MAX
    assert "soft_truncated" in over_issues
    assert sp.fatal_document_issues(over_issues)
    # Витрина показывает диагностику документа (Inspector/UI видят причину).
    view = sp.style_policy_view({"soft_instructions": [
        {"id": f"s{i}", "text": f"правило {i}"}
        for i in range(sp.SOFT_INSTRUCTIONS_MAX + 1)]}, None)
    assert "soft_truncated" in view["document"]["global_issues"]


def test_no_hidden_secondary_hint_builder_remains():
    from services import prompt_composer as cp
    assert not hasattr(psb, "STYLE_POLICY_HINT_MAX_CHARS")
    assert not hasattr(psb, "STYLE_POLICY_HINT_MAX_ITEMS")
    assert not hasattr(cp, "_style_hint")
    assert not hasattr(cp, "STYLE_HINT_MAX_CHARS")


class _AsyncCache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category=None):
        self.values[key] = value


@pytest.mark.asyncio
async def test_save_keeps_hint_limits_when_editor_omits_field():
    """Правка правил не стирает сохранённый лимит (пока UI его не знает)."""
    cache = _AsyncCache({sp.DOC_KEY: sp.build_document(
        presets=("no_quotes",), hint_limits={"max_items": 2})})
    hot.set_config_cache(cache)
    saved = await sp.save_policy_document(
        {"rules": [{"id": "trailing_period.hard.strip",
                    "kind": "trailing_period", "strictness": "hard",
                    "scope": "global", "enabled": True,
                    "reason": "owner_edit"}],
         "soft_instructions": []},
        cache=cache, actor=1, reason="owner_edit")
    assert saved["applied"] is True
    stored = cache.get(sp.DOC_KEY)
    assert stored["hint_limits"] == {"max_items": 2}
    policy = sp.effective_policy_sync(stored, None, context="regular")
    assert policy.hint_limits["max_items"] == 2
    # Явная передача поля по-прежнему управляет значением (в т.ч. OFF).
    saved_off = await sp.save_policy_document(
        {"rules": [], "soft_instructions": [],
         "hint_limits": {"max_items": 0}},
        cache=cache, actor=1, reason="owner_edit")
    assert saved_off["applied"] is True
    assert cache.get(sp.DOC_KEY)["hint_limits"] == {"max_items": 0}
