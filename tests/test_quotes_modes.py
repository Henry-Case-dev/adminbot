"""QUOTES-MODES: два детерминированных режима кавычек (владелец 24.10.2026).

A (normalize, по умолчанию ON): « » → "; содержимое не меняется.
B (strip, по умолчанию OFF): « », " удаляются, слова остаются.
Режимы взаимоисключающие (одна настройка), оба могут быть OFF.
Смыслового анализа (ирония/цитата/переформулирование) нет.

TEST-LIFECYCLE: CONTRACT owner=QUOTES-MODES/A-B
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services import style_policy as sp

CHAT = 7
ROOT = Path(__file__).resolve().parents[1]


def doc(rules=None, presets=None):
    if presets:
        return sp.build_document(presets=list(presets), owner=1, reason="test")
    return {"v": 1, "revision": 1, "rules": list(rules or []),
            "soft_instructions": []}


def quotes_rule(mode, *, enabled=True, rule_id=None):
    return {"id": rule_id or ("q.%s" % mode), "kind": "quotation_marks",
            "strictness": "hard", "params": {"mode": mode},
            "enabled": enabled, "reason": "r"}


def run(text, global_doc=None, chat_doc=None, **kwargs):
    policy = sp.effective_policy_sync(global_doc, chat_doc, **kwargs)
    out, results = sp.StylePolicyValidator(policy).run(text)
    rows = [r for r in results if r.kind == "quotation_marks"]
    return out, rows, policy


# ═══ A: заводской default ON, замена ёлочек ═════════════════════════════════

def test_mode_a_is_default_on():
    out, rows, policy = run("Ну это «гениальная» идея")
    assert out == 'Ну это "гениальная" идея'
    assert len(rows) == 1
    assert rows[0].status == sp.STATUS_REPAIRED
    assert rows[0].reason == "quotes_normalized"
    assert rows[0].source == "factory"


def test_mode_a_nested_and_other_quote_classes_untouched():
    text = "Он сказал «внешние «внутренние» слова» и „другие“"
    out, _rows, _policy = run(text)
    assert out == 'Он сказал "внешние "внутренние" слова" и „другие“'


def test_mode_a_is_idempotent():
    first, _rows, policy = run("«раз» и «два»")
    assert first == '"раз" и "два"'
    second, results = sp.StylePolicyValidator(policy).run(first)
    assert second == first
    rows = [r for r in results if r.kind == "quotation_marks"]
    assert rows and rows[0].status == sp.STATUS_PASS


# ═══ B: удаление кавычек ═════════════════════════════════════════════════════

def test_mode_b_preset_strips_quotes_and_keeps_words():
    out, rows, _policy = run("Он сказал «база это сила»",
                             doc(presets=["no_quotes"]))
    assert out == "Он сказал база это сила"
    assert len(rows) == 1 and rows[0].reason == "quotes_removed"


def test_mode_b_removes_straight_quotes_too():
    out, _rows, _policy = run('Он сказал "база это сила"',
                              doc(rules=[quotes_rule("strip")]))
    assert out == "Он сказал база это сила"


def test_mode_b_nested():
    out, _rows, _policy = run("«внешние «внутренние» слова»",
                              doc(rules=[quotes_rule("strip")]))
    assert out == "внешние внутренние слова"


# ═══ OFF: оба выключены ══════════════════════════════════════════════════════

def test_both_modes_off_keeps_text_byte_identical():
    text = 'Ну это «гениальная» идея и "прямые" кавычки'
    out, rows, policy = run(text, doc(rules=[quotes_rule(
        "normalize", enabled=False, rule_id=sp.QUOTES_FACTORY_ID)]))
    assert out == text
    assert rows == [], "выключенная настройка не должна давать исходов"
    assert policy.rules_for_kind("quotation_marks") == ()


# ═══ взаимоисключение: ровно одно правило, без двойной обработки ════════════

def test_two_rules_in_document_collapse_to_one():
    global_doc = doc(rules=[quotes_rule("normalize", rule_id="q.a"),
                            quotes_rule("strip", rule_id="q.b")])
    policy = sp.effective_policy_sync(global_doc, None)
    quotes = policy.rules_for_kind("quotation_marks")
    assert len(quotes) == 1, "A и B не могут действовать одновременно"
    assert quotes[0].rule.params["mode"] == "strip"
    out, rows, _policy = run("«база»", global_doc)
    assert out == "база" and len(rows) == 1


def test_no_quotes_preset_does_not_double_process_with_factory_a():
    global_doc = doc(presets=["no_quotes"])
    policy = sp.effective_policy_sync(global_doc, None)
    assert len(policy.rules_for_kind("quotation_marks")) == 1
    out, rows, _policy = run("«текст»", global_doc)
    assert out == "текст", "режим A не должен сработать поверх B"
    assert [r.reason for r in rows] == ["quotes_removed"]


def test_chat_mode_overrides_global_mode():
    chat_doc = doc(rules=[quotes_rule("strip", rule_id="q.chat")])
    policy = sp.effective_policy_sync(None, chat_doc)
    quotes = policy.rules_for_kind("quotation_marks")
    assert len(quotes) == 1 and quotes[0].source == "chat"
    out, _rows, _policy = run("«текст»", None, chat_doc)
    assert out == "текст"


def test_chat_off_overrides_global_a():
    chat_doc = doc(rules=[quotes_rule("normalize", enabled=False,
                                      rule_id=sp.QUOTES_FACTORY_ID)])
    out, rows, _policy = run("«текст»", None, chat_doc)
    assert out == "«текст»"
    assert rows == []


# ═══ защищённые технические данные ═══════════════════════════════════════════

@pytest.mark.parametrize("mode", ["normalize", "strip"])
@pytest.mark.parametrize("text", [
    'Код: print("hi")',
    'Фрагмент: ```print("hi")```',
    'Данные: {"k": "«v»"}',
    "Файл C:\\path\\x.txt тут",
])
def test_technical_data_is_byte_identical(mode, text):
    out, rows, _policy = run(text, doc(rules=[quotes_rule(mode)]))
    assert out == text, (mode, text, out)
    # Внутри защищённых сегментов кавычки не трогаются: pass (нечего менять
    # в этом режиме) либо честный exempted (символы есть, но защищены).
    assert rows and rows[0].status in (sp.STATUS_PASS, sp.STATUS_EXEMPTED)


@pytest.mark.parametrize("mode", ["normalize", "strip"])
def test_url_is_kept_while_plain_text_is_processed(mode):
    text = "Ссылка https://example.org/a?x=1 и «слово»"
    out, _rows, _policy = run(text, doc(rules=[quotes_rule(mode)]))
    assert "https://example.org/a?x=1" in out
    assert ("слово" in out) if mode == "normalize" else ("«" not in out)


@pytest.mark.parametrize("mode", ["normalize", "strip"])
@pytest.mark.parametrize("text", [
    "Смотри https://example.org/s?q=«x» и всё",
    "https://x/«y»",
    "Поиск https://x/a?q=«термин»&page=2",
])
def test_url_with_guillemets_stays_byte_identical(mode, text):
    """REGRESSION (QUOTES-URL-FIX): кавычки ВНУТРИ ссылки — часть URL."""
    out, rows, _policy = run(text, doc(rules=[quotes_rule(mode)]))
    assert out == text, (mode, text, out)
    assert rows and rows[0].status in (sp.STATUS_PASS, sp.STATUS_EXEMPTED)


@pytest.mark.parametrize("mode", ["normalize", "strip"])
def test_quotes_outside_url_are_still_processed(mode):
    """REGRESSION (QUOTES-URL-FIX): кавычки ПОСЛЕ ссылки — обычный текст."""
    text = "Ссылка https://example.org/a?x=1 и «слово»"
    out, rows, _policy = run(text, doc(rules=[quotes_rule(mode)]))
    expected = ('Ссылка https://example.org/a?x=1 и "слово"' if mode == "normalize"
                else "Ссылка https://example.org/a?x=1 и слово")
    assert out == expected
    assert rows[0].status == sp.STATUS_REPAIRED


@pytest.mark.parametrize("mode", ["normalize", "strip"])
def test_trailing_closer_after_url_is_not_swallowed(mode):
    """Закрывающая ёлочка предложения не приклеивается к URL."""
    out, _rows, _policy = run("«https://x/a»", doc(rules=[quotes_rule(mode)]))
    assert out == ('"https://x/a"' if mode == "normalize" else "https://x/a")


def test_inches_literal_is_not_a_quote():
    text = 'Экран 5" и ещё 7" — итого 12'
    out, rows, _policy = run(text, doc(rules=[quotes_rule("strip")]))
    assert '5"' in out and '7"' in out
    assert rows and rows[0].status in (sp.STATUS_PASS, sp.STATUS_EXEMPTED)


# ═══ каталог/пресеты/подсказка ═══════════════════════════════════════════════

def test_catalog_and_factory_declare_deterministic_modes():
    assert sp.RULE_KIND_SPECS["quotation_marks"]["params"]["mode"] == \
        "normalize|strip"
    assert sp.PRESET_SPECS["no_quotes"]["rules"][0]["params"] == \
        {"mode": "strip"}
    factory = {rule.id: rule for rule in sp.factory_rules()}
    assert factory[sp.QUOTES_FACTORY_ID].params == {"mode": "normalize"}
    assert factory[sp.QUOTES_FACTORY_ID].enabled is True


def test_hint_has_no_writer_instruction_for_mode_a():
    policy_a = sp.effective_policy_sync(None, None)
    assert "Кавычки" not in policy_a.hint, policy_a.hint
    policy_b = sp.effective_policy_sync(doc(presets=["no_quotes"]), None)
    assert "НЕ используй графические кавычки" in policy_b.hint


def test_unknown_mode_is_diagnosed_and_defaults_to_strip():
    raw = {"v": 1, "revision": 1, "rules": [
        {"id": "q.bad", "kind": "quotation_marks", "strictness": "hard",
         "params": {"mode": "banana"}, "reason": "r"}]}
    _normalized, issues = sp.validate_document(raw)
    assert "rule_params_default:quotation_marks.mode=banana" in issues
    out, _rows, _policy = run("«текст»", raw)
    assert out == "текст"


# ═══ рестарт: выбор сохраняется и читается заново ═══════════════════════════

class _AsyncCache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, **kwargs):
        self.values[key] = value


@pytest.mark.asyncio
async def test_global_mode_survives_save_and_reload():
    cache = _AsyncCache()
    result = await sp.save_policy_document(
        doc(rules=[quotes_rule("strip")]), chat_id=None, cache=cache, actor=1,
        reason="test")
    assert result["applied"] is True
    stored = cache.values[sp.DOC_KEY]
    out, _rows, _policy = run("Он сказал «база»", stored)
    assert out == "Он сказал база", "после рестарта действует сохранённый режим"


@pytest.mark.asyncio
async def test_chat_mode_survives_save_and_reload():
    root: dict = {}

    async def get_root(chat_id, **kwargs):
        return dict(root.get(int(chat_id)) or {})

    async def set_root(chat_id, patch, **kwargs):
        root[int(chat_id)] = dict(patch)

    result = await sp.save_policy_document(
        doc(rules=[quotes_rule("normalize", rule_id=sp.QUOTES_FACTORY_ID)]),
        chat_id=CHAT, get_root=get_root, set_root=set_root, actor=1,
        reason="test")
    assert result["applied"] is True and result["scope"] == "chat"
    chat_doc = root[CHAT]["overrides"][sp.DOC_KEY]
    policy = sp.effective_policy_sync(None, chat_doc)
    out, _results = sp.StylePolicyValidator(policy).run("«база»")
    assert out == '"база"'


# ═══ UI-контракт: два пункта с взаимоисключением ════════════════════════════

def test_style_ui_exposes_two_exclusive_quote_toggles():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-speech-quotes-mode="normalize"' in html
    assert 'data-speech-quotes-mode="strip"' in html
    assert "setStyleQuotesMode('normalize'" in html
    assert "setStyleQuotesMode('strip'" in html
    assert "Оба режима выключены" in html
    assert "speechQuotesMode: function" in js
    assert "setStyleQuotesMode: function" in js
    # Оба чекбокса читают ОДНО состояние режима — взаимоисключение в UI.
    assert html.count("speechQuotesMode() === 'normalize'") == 1
    assert html.count("speechQuotesMode() === 'strip'") == 1


def test_document_keeps_single_quotes_rule_after_ui_toggle_shape():
    """Форма правила, которую пишет UI (id/params), валидна и читается."""
    payload = {"v": 1, "revision": 1, "rules": [{
        "id": sp.QUOTES_FACTORY_ID, "kind": "quotation_marks",
        "strictness": "hard", "scope": "chat", "params": {"mode": "strip"},
        "enabled": True, "reason": "владелец: без кавычек в обычной речи"}],
        "soft_instructions": []}
    normalized, issues = sp.validate_document(payload)
    assert normalized["rules"][0]["params"] == {"mode": "strip"}
    assert "rule_kind_unknown" not in json.dumps(issues)
    out, _rows, _policy = run("«x»", None, payload)
    assert out == "x"


# ??? UI: ?????? ???? ???????? = ???? ??????? (REV F2) ?????????????????????

APP_JS = ROOT / "web" / "app.js"
NODE = shutil.which("node")


def _fn(src, start_marker, end_marker):
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end].rstrip().rstrip(",")


@pytest.mark.skipif(NODE is None, reason="node ??????????")
def test_ui_preset_no_quotes_leaves_exactly_one_quotes_rule(tmp_path):
    """F2: ?+ ??? ???????? ???????? ??????? ???????, ? ?? ????????? ??????.

    ???????? ?????: ? ????????? ??? ???? ????????? A (normalize); ?????
    ??????? ? ????????? ????? ???? ?????????? ??????? ??????? (B=strip),
    ???????? ?????????? B, ????????? ???? ?? ????????? ???? ??????.
    """
    src = APP_JS.read_text(encoding="utf-8")
    parts = [
        _fn(src, "ensureStyleDraft: function", "speechStyleOwnLimits: function"),
        _fn(src, "speechStyleViewRules: function", "speechStyleViewSoft: function"),
        _fn(src, "speechQuotesRules: function", "setStyleQuotesMode: function"),
        _fn(src, "addStylePreset: function", "addSoftInstruction: function"),
    ]
    presets = json.dumps({"no_quotes": {"rules": sp.preset_rules("no_quotes"),
                                        "soft_instructions": []}},
                         ensure_ascii=False)
    factory = json.dumps([
        {"id": "dash.hard.factory", "kind": "dash", "strictness": "hard",
         "enabled": True, "params": {}, "reason": "r"},
        {"id": sp.QUOTES_FACTORY_ID, "kind": "quotation_marks",
         "strictness": "hard", "enabled": True,
         "params": {"mode": "normalize"}, "reason": "r"},
    ], ensure_ascii=False)
    script = (
        "var obj = {\n" + ",\n".join(parts) + "\n};\n"
        "var presets = JSON.parse(" + json.dumps(presets) + ");\n"
        "var factory = JSON.parse(" + json.dumps(factory) + ");\n"
        "function ctx(rules) {\n"
        "  return { speechStyleDraft: {rules: rules, soft_instructions: [],"
        " hint_limits: {}},\n"
        "    speechStyle: {preset_documents: presets}, speechDirty: {},\n"
        "    toasts: [], toast: function (m) { this.toasts.push(m); },\n"
        "    clearSpeechSaved: function () {},\n"
        "    ensureStyleDraft: obj.ensureStyleDraft,\n"
        "    speechStyleViewRules: obj.speechStyleViewRules,\n"
        "    speechQuotesRules: obj.speechQuotesRules,\n"
        "    speechQuotesMode: obj.speechQuotesMode,\n"
        "    addStylePreset: obj.addStylePreset };\n"
        "}\n"
        "function quotes(c) { return c.speechQuotesRules(); }\n"
        "var a = ctx(JSON.parse(JSON.stringify(factory)));\n"
        "a.addStylePreset('no_quotes');\n"
        "var first = {rules: a.speechStyleDraft.rules,"
        " quotes: quotes(a), mode: a.speechQuotesMode()};\n"
        "a.addStylePreset('no_quotes');\n"
        "var again = {quotes: quotes(a), mode: a.speechQuotesMode(),"
        " all: a.speechStyleDraft.rules};\n"
        "var b = ctx([]);\n"
        "b.addStylePreset('no_quotes');\n"
        "var empty = {quotes: quotes(b), mode: b.speechQuotesMode()};\n"
        "console.log(JSON.stringify({first: first, again: again,"
        " empty: empty}));\n"
    )
    proc = subprocess.run([NODE, "-e", script], capture_output=True,
                          text=True, timeout=60, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    first = out["first"]
    assert len(first["quotes"]) == 1, first["rules"]
    assert first["quotes"][0]["params"]["mode"] == "strip"
    assert first["quotes"][0]["enabled"] is True
    assert first["mode"] == "strip", "UI ?????? ???????? B, ? ?? A"
    # ?????? ??????? ????????? ?? ??????????
    assert [r["id"] for r in first["rules"] if r["kind"] != "quotation_marks"] \
        == ["dash.hard.factory"]
    # ????????? ???? ??? ?? ???????? ?? ???????? ?????????
    assert len(out["again"]["quotes"]) == 1, out["again"]
    assert out["again"]["mode"] == "strip"
    assert len(out["empty"]["quotes"]) == 1
    assert out["empty"]["mode"] == "strip"
