"""F6 (T-2093, ADR-1022-6 §2.3) — детектор клише + Validator Loop.

ASAP-EVOL-ANTICLICHE (FINAL v8 §1.1/§1.2, ADR §3): анти-клише — НАБЛЮДЕНИЕ.
Стилевое попадание (hardcoded/динамическое/pinned/множественное) больше НЕ
вызывает повторной генерации: на такой ответ ровно один ``generate_call``,
``stats['anti_cliche_retries'] == 0``, ``CLICHE_RETRY_SYSTEM_PROMPT``
недостижим. Независимые guard'ы (form/факты, numeric, метатекст, формат
доставки) сохраняют поведение и собственную причину, включая отдельный
``format_retry`` для ``plain_no_tables``/``bullet_list``.

Покрытие: каждый код ловится; легитимные фразы — нет; `bullet_list` только по
флагу; guard-ретрай ≤2 → успех; исчерпание → лучший вариант (fallback);
ошибка ретрая → последний успешный; bounded-вызовы; R17-статы (коды/числа);
scrubber применяется на всех путях; kill-switch OFF → один вызов.
"""
import ast
import inspect

import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from services import negative_constraints as nc
from services.negative_constraints import (
    DEFAULT_ENABLED_RULES,
    DYNAMIC_PREFIX,
    FORBIDDEN_CLICHE_PATTERNS,
    FORMAT_GUARDS,
    FORMAT_RETRY_REASON,
    STYLE_SIGNALS,
    FormContract,
    NumericContract,
    build_dynamic_rule,
    channel_enabled_rules,
    find_forbidden_cliches,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    CLICHE_RETRY_SYSTEM_PROMPT,
    FORMAT_NO_LISTS_RETRY_TEXT,
    FORMAT_PLAIN_TEXT_BLOCK,
    FORM_GUARD_RETRY_SYSTEM_PROMPT,
    METATEXT_RETRY_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.system2

_BASE = [{"role": "user", "content": "x"}]
_TABLE = "| a | b |\n|---|---|"
_BULLETS = "- первый пункт\n- второй пункт"
#: Набор plain-канала: именно он включает ``plain_no_tables`` (secondary).
_PLAIN = channel_enabled_rules("plain", "serious")

# Один характерный текст на каждый стилевой код (инвариант §1.1).
_STYLE_SAMPLES = (
    ("as_ai", "я как ИИ отвечаю"),
    ("classic_genre", "ну это классика жанра"),
    ("summing_up", "подводя итог, всё плохо"),
    ("in_conclusion", "в заключение скажу"),
    ("hope_helped", "надеюсь, помог"),
    ("you_asked_before", "ты уже спрашивал это"),
    ("mirror_no_you", "нет, это ты виноват"),
)


class TestDetector:
    @pytest.mark.parametrize("text,code", [
        ("я как искусственный интеллект тут", "as_ai"),
        ("как языковая модель отвечаю", "as_ai"),
        ("ну это классика жанра", "classic_genre"),
        ("подводя итог, всё плохо", "summing_up"),
        ("в заключение скажу", "in_conclusion"),
        ("надеюсь, помог", "hope_helped"),
        ("надеюсь, это было полезно", "hope_helped"),
        ("ты уже спрашивал это", "you_asked_before"),
        ("вы уже спрашивали", "you_asked_before"),
        ("нет, это ты виноват", "mirror_no_you"),
    ])
    def test_each_code_detected(self, text, code):
        assert code in find_forbidden_cliches(text)

    @pytest.mark.parametrize("text", [
        "как интересно получилось",
        "ну и классика, ничего нового",
        "надеюсь на лучшее",
        "ты спрашивал про погоду вчера",
        "нет, я не согласен",
        "искусственный отбор",
        # Ревью (High-2): голое «искусственный интеллект» — НЕ клише
        # («языковая модель» и «я … ИИ» остаются запретными).
        "учёные создали искусственный интеллект и он решает задачи",
        # Ревью (High-2): уступка — не перепалка.
        "нет, ты прав, я ошибался",
        "Нет, ты верно заметил",
    ])
    def test_legit_phrases_not_detected(self, text):
        assert find_forbidden_cliches(text) == []

    def test_concession_not_mirror_but_retort_is(self):
        assert "mirror_no_you" not in find_forbidden_cliches(
            "Нет, ты прав, я ошибался")
        assert "mirror_no_you" in find_forbidden_cliches(
            "нет, это ты виноват")

    def test_bullet_list_secondary_flag(self):
        text = "- первый пункт\n- второй пункт"
        assert find_forbidden_cliches(text) == []
        assert find_forbidden_cliches(
            text, enabled_rules={"bullet_list"}) == ["bullet_list"]
        assert "bullet_list" not in DEFAULT_ENABLED_RULES

    def test_returns_codes_only_not_matches(self):
        hits = find_forbidden_cliches("подводя итог: как ИИ")
        assert set(hits) == {"summing_up", "as_ai"}
        assert all(h in DEFAULT_ENABLED_RULES for h in hits)

    def test_fail_open_on_bad_input(self):
        assert find_forbidden_cliches(None) == []

    def test_as_ai_first_person_flagged_third_person_not(self):
        """S10.22-4: «как ИИ» — клише только как самоидентификация (1-е лицо
        или обращение к боту), а не как третьеличное сравнение."""
        assert "as_ai" in find_forbidden_cliches("я как ИИ, отвечаю")
        assert "as_ai" in find_forbidden_cliches("как ИИ, я не могу это сделать")
        assert "as_ai" not in find_forbidden_cliches(
            "Он ведёт себя как искусственный интеллект, без эмоций")
        assert "as_ai" not in find_forbidden_cliches(
            "Оно ведёт себя как искусственный интеллект")


class TestRuleClassification:
    """ADR §3: стиль и формат доставки разделены в ОДНОМ месте."""

    def test_every_rule_code_is_style_or_format(self):
        codes = {rule.code for rule in FORBIDDEN_CLICHE_PATTERNS}
        assert codes == set(STYLE_SIGNALS) | set(FORMAT_GUARDS)
        assert not set(STYLE_SIGNALS) & set(FORMAT_GUARDS)

    def test_style_set_is_observation_only_named_tropes(self):
        assert STYLE_SIGNALS == frozenset({
            "as_ai", "classic_genre", "summing_up", "in_conclusion",
            "hope_helped", "mirror_no_you", "you_asked_before"})

    def test_format_guards_are_delivery_not_style(self):
        assert FORMAT_GUARDS == frozenset({"plain_no_tables", "bullet_list"})
        assert FORMAT_RETRY_REASON == "format_retry"

    def test_dynamic_rules_classified_as_style(self):
        rule = build_dynamic_rule("шаблонное словосочетание")
        observed, fmt = nc.split_rule_codes([rule.code, "plain_no_tables"])
        assert observed == [rule.code]
        assert fmt == ["plain_no_tables"]
        # неизвестный код — тоже наблюдение (fail-safe: без лишнего вызова LLM)
        assert nc.split_rule_codes(["some_unknown_code"]) == (
            ["some_unknown_code"], [])
        assert nc.is_format_guard("plain_no_tables")
        assert not nc.is_format_guard("bullet_list_typo")

    def test_no_lists_retry_text_is_existing_canon_line(self):
        assert "АНТИ-БОТ" in FORMAT_NO_LISTS_RETRY_TEXT
        assert "перечни" in FORMAT_NO_LISTS_RETRY_TEXT


class TestAntiClicheNeverRegenerates:
    """§1.1 инвариант: анти-клише НИКОГДА не вызывает генерацию повторно."""

    @pytest.mark.parametrize("code,text", _STYLE_SAMPLES)
    @pytest.mark.asyncio
    async def test_style_signal_single_generate_call(self, code, text):
        gen = AsyncMock(return_value=text)
        result, stats = await verbalize_validated(gen, list(_BASE))
        assert gen.await_count == 1          # никакого второго вызова
        assert result == text                # текст не переписан
        assert stats["attempts"] == 1 and stats["retries"] == 0
        assert stats["anti_cliche_retries"] == 0
        assert stats["fallback"] is False
        assert code in stats["cliche_observed"]
        assert code in stats["hits"]         # наблюдение сохраняется

    @pytest.mark.asyncio
    async def test_multiple_style_hits_single_call(self):
        text = "как ИИ, подводя итог: надеюсь, помог"
        gen = AsyncMock(return_value=text)
        result, stats = await verbalize_validated(gen, list(_BASE))
        assert gen.await_count == 1
        assert result == text
        assert set(stats["cliche_observed"]) == {
            "as_ai", "summing_up", "hope_helped"}
        assert stats["anti_cliche_retries"] == 0

    @pytest.mark.asyncio
    async def test_dynamic_rule_single_call(self):
        rule = build_dynamic_rule("шаблонное словосочетание")
        gen = AsyncMock(return_value="ну шаблонное словосочетание тут")
        result, stats = await verbalize_validated(
            gen, list(_BASE), dynamic_rules=[rule])
        assert gen.await_count == 1
        assert result == "ну шаблонное словосочетание тут"
        assert rule.code in stats["cliche_observed"]
        assert stats["anti_cliche_retries"] == 0
        assert stats["hits"] == [rule.code]

    @pytest.mark.asyncio
    async def test_style_never_sends_retry_prompt(self):
        seen: list[list[dict]] = []

        async def gen(messages):
            seen.append([dict(m) for m in messages])
            return "подводя итог: как ИИ"

        await verbalize_validated(gen, list(_BASE), max_retries=2)
        assert len(seen) == 1                    # второго промпта нет вообще
        for messages in seen:
            assert [m["role"] for m in messages] == ["user"]
            for message in messages:
                assert CLICHE_RETRY_SYSTEM_PROMPT not in message["content"]

    @pytest.mark.asyncio
    async def test_style_hit_is_not_reported_as_guard(self):
        """Стиль не выдаётся за format/metatext/form/numeric-отказ."""
        gen = AsyncMock(return_value="как ИИ отвечаю")
        _text, stats = await verbalize_validated(gen, list(_BASE))
        assert stats["cliche_observed"] == ["as_ai"]
        assert not any(key.startswith(("format_", "form_", "metatext_",
                                       "numeric_")) for key in stats)
        assert stats["fallback"] is False

    @pytest.mark.asyncio
    async def test_anti_cliche_retries_zero_on_all_paths(self, monkeypatch):
        """Измеряемый инвариант §4.4: счётчик всегда 0 на всех путях."""
        async def run(gen, **kwargs):
            return await verbalize_validated(gen, list(_BASE), **kwargs)

        cases = [
            await run(AsyncMock(return_value="чистый текст")),
            await run(AsyncMock(return_value="как ИИ")),
            await run(AsyncMock(side_effect=[_TABLE, "чистый текст"]),
                      enabled_rules=_PLAIN),
            await run(AsyncMock(return_value=_TABLE), enabled_rules=_PLAIN),
            await run(AsyncMock(side_effect=["как ИИ", RuntimeError("boom")])),
        ]
        for _text, stats in cases:
            assert stats["anti_cliche_retries"] == 0, stats
        assert all("anti_cliche_retries" in stats for _t, stats in cases)


class TestIndependentGuardsStillFire:
    """§1.2 инвариант: independent guard'ы сохраняются со своей причиной."""

    @pytest.mark.asyncio
    async def test_format_tables_retry_with_own_reason(self):
        seen: list[str] = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return _TABLE if len(seen) == 1 else "чистый текст"

        text, stats = await verbalize_validated(gen, list(_BASE),
                                               enabled_rules=_PLAIN)
        assert text == "чистый текст"
        assert len(seen) == 2
        assert seen[1] == FORMAT_PLAIN_TEXT_BLOCK     # не стилевой промпт
        assert stats["format_retry"] is True
        assert stats["format_guard_reason"] == "format_retry"
        assert stats["format_rejects"] == 1
        assert stats["format_fallback"] is False
        assert stats["attempts"] == 2 and stats["retries"] == 1
        assert stats["anti_cliche_retries"] == 0

    @pytest.mark.asyncio
    async def test_format_bullets_retry_with_own_reason(self):
        seen: list[str] = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return _BULLETS if len(seen) == 1 else "чистый текст"

        text, stats = await verbalize_validated(
            gen, list(_BASE), enabled_rules={"bullet_list"})
        assert text == "чистый текст"
        assert seen[1] == FORMAT_NO_LISTS_RETRY_TEXT
        assert stats["format_guard_reason"] == "format_retry"
        assert stats["format_retry"] is True
        assert CLICHE_RETRY_SYSTEM_PROMPT not in seen[1]

    @pytest.mark.asyncio
    async def test_format_exhausted_bounded_once(self):
        calls: list[int] = []

        async def gen(messages):
            calls.append(1)
            return _TABLE

        text, stats = await verbalize_validated(gen, list(_BASE),
                                                max_retries=99,
                                                enabled_rules=_PLAIN)
        assert len(calls) == 2                    # ровно ≤1 format-повтор
        assert text == _TABLE                     # текст не режем молча
        assert stats["format_fallback"] is True
        assert stats["fallback"] is True
        assert stats["format_rejects"] == 2

    @pytest.mark.asyncio
    async def test_form_guard_keeps_own_reason(self):
        seen: list[str] = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return "13 штук" if len(seen) == 1 else "двенадцать штук"

        text, stats = await verbalize_validated(
            gen, list(_BASE),
            form_contract=FormContract(source_text="двенадцать штук"),
            fallback_text="двенадцать штук")
        assert text == "двенадцать штук"
        assert seen[1] == FORM_GUARD_RETRY_SYSTEM_PROMPT
        assert stats["form_retry"] is True
        assert stats["form_guard_reason"] == nc.FORM_GUARD_REJECTED
        assert not any(k.startswith(("format_", "metatext_"))
                       for k in stats)

    @pytest.mark.asyncio
    async def test_numeric_guard_keeps_own_reason(self):
        class _Claim:
            value = 9
            unit = "messages"

        seen: list[str] = []

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return ("он писал 7 сообщений" if len(seen) == 1
                    else "он писал 9 сообщений")

        text, stats = await verbalize_validated(
            gen, list(_BASE),
            numeric_contract=NumericContract(
                claims=(_Claim(),), verified_phrase="он писал 9 сообщений"))
        assert text == "он писал 9 сообщений"
        assert stats["numeric_claim_retry"] is True
        assert stats["numeric_claim_mismatch"] == 1
        assert "9" in seen[1]
        assert not any(k.startswith(("format_", "form_", "metatext_"))
                       for k in stats)

    @pytest.mark.asyncio
    async def test_metatext_guard_keeps_own_reason(self):
        seen: list[str] = []

        def reason(text):
            return "metatext_test" if "служебный маркер" in text else None

        async def gen(messages):
            seen.append(messages[-1]["content"] if len(messages) > 1 else "")
            return ("служебный маркер тут" if len(seen) == 1
                    else "чистый текст")

        text, stats = await verbalize_validated(
            gen, list(_BASE), metatext_reason=reason)
        assert text == "чистый текст"
        assert stats["metatext_retry"] is True
        assert stats["metatext_reason_code"] == "metatext_test"
        assert seen[1] == METATEXT_RETRY_SYSTEM_PROMPT.replace(
            "{reason}", "metatext_test")

    @pytest.mark.asyncio
    async def test_style_plus_numeric_uses_numeric_guard_only(self):
        class _Claim:
            value = 9
            unit = "messages"

        calls: list[list[dict]] = []

        async def gen(messages):
            calls.append([dict(m) for m in messages])
            if len(calls) == 1:
                return "как ИИ: он писал 7 сообщений"
            return "он писал 9 сообщений"

        text, stats = await verbalize_validated(
            gen, list(_BASE),
            numeric_contract=NumericContract(claims=(_Claim(),)))
        assert len(calls) == 2                     # ровно один guard-повтор
        assert text == "он писал 9 сообщений"
        assert stats["cliche_observed"] == ["as_ai"]
        assert stats["anti_cliche_retries"] == 0
        assert stats["numeric_claim_retry"] is True
        assert "as_ai" not in str(stats.get("format_guard_reason"))

    @pytest.mark.asyncio
    async def test_style_plus_format_uses_format_reason(self):
        async def gen(messages):
            if len(messages) == 1:
                return "как ИИ\n" + _TABLE
            return "как ИИ, коротко"

        text, stats = await verbalize_validated(gen, list(_BASE),
                                               enabled_rules=_PLAIN)
        assert text == "как ИИ, коротко"
        assert stats["format_guard_reason"] == "format_retry"
        assert stats["cliche_observed"] == ["as_ai"]
        assert stats["anti_cliche_retries"] == 0

    @pytest.mark.asyncio
    async def test_guard_budget_is_bounded_by_hard_cap(self):
        """Бюджет повторов общий и не растёт: ≤2 повтора (≤3 генерации)."""
        calls: int = 0
        texts = ("он писал 7 сообщений", "служебный маркер тут",
                 "служебный маркер тут")

        def reason(text):
            return "metatext_test" if "служебный маркер" in text else None

        async def gen(messages):
            nonlocal calls
            value = texts[min(calls, len(texts) - 1)]
            calls += 1
            return value

        _text, stats = await verbalize_validated(
            gen, list(_BASE), max_retries=99,
            numeric_contract=NumericContract(claims=()),
            metatext_reason=reason)
        assert calls <= 3
        assert stats["retries"] <= 2
        assert stats["anti_cliche_retries"] == 0


class TestValidatorLoop:
    @pytest.mark.asyncio
    async def test_clean_first_attempt_single_call(self):
        gen = AsyncMock(return_value="нормальный дерзкий текст")
        text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert text == "нормальный дерзкий текст"
        assert gen.await_count == 1
        assert stats == {"attempts": 1, "retries": 0, "hits": [],
                         "fallback": False, "retry_error": False,
                         "enabled": True, "anti_cliche_retries": 0,
                         "cliche_observed": []}

    @pytest.mark.asyncio
    async def test_format_dirty_then_clean_retries_once(self):
        gen = AsyncMock(side_effect=[_TABLE, "теперь чисто"])
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], enabled_rules=_PLAIN)
        assert text == "теперь чисто"
        assert gen.await_count == 2
        assert stats["attempts"] == 2 and stats["retries"] == 1
        assert stats["fallback"] is False
        assert stats["format_retry"] is True

    @pytest.mark.asyncio
    async def test_exhausted_returns_best_fallback(self):
        gen = AsyncMock(side_effect=[_TABLE, _TABLE, _TABLE])
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], enabled_rules=_PLAIN)
        assert gen.await_count == 2          # ≤1 format-повтор
        assert text == _TABLE
        assert stats["attempts"] == 2 and stats["retries"] == 1
        assert stats["fallback"] is True
        assert stats["hits"] == ["plain_no_tables"]

    @pytest.mark.asyncio
    async def test_retry_generate_error_returns_last_success(self):
        gen = AsyncMock(side_effect=[_TABLE, RuntimeError("boom")])
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], enabled_rules=_PLAIN)
        assert text == _TABLE
        assert stats["retry_error"] is True
        assert stats["fallback"] is True
        assert gen.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_message_appended_only_on_retry(self):
        seen = []

        async def gen(messages):
            seen.append([m["role"] for m in messages])
            return _TABLE if len(seen) == 1 else "чисто"

        await verbalize_validated(gen, [{"role": "user", "content": "x"}],
                                  enabled_rules=_PLAIN)
        assert seen[0] == ["user"]
        assert seen[1] == ["user", "system"]

    @pytest.mark.asyncio
    async def test_scrubber_applied_on_all_paths(self):
        gen = AsyncMock(return_value="хвост fact:123 как ИИ")
        text, _stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], max_retries=1)
        assert "fact:123" not in text
        assert text == "хвост как ИИ"

    @pytest.mark.asyncio
    async def test_kill_switch_off_single_call(self, monkeypatch):
        monkeypatch.setattr(Settings, "SYSTEM2_VALIDATOR_LOOP_ENABLED", False)
        gen = AsyncMock(return_value="как ИИ")
        _text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert gen.await_count == 1
        assert stats["enabled"] is False
        assert stats["attempts"] == 1

    @pytest.mark.asyncio
    async def test_max_retries_hard_cap(self):
        calls = 0
        texts = ("служебный маркер тут", "служебный маркер тут",
                 "служебный маркер тут")

        def reason(text):
            return "metatext_test" if "служебный маркер" in text else None

        async def gen(messages):
            nonlocal calls
            value = texts[min(calls, len(texts) - 1)]
            calls += 1
            return value

        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            max_retries=99, metatext_reason=reason)
        assert calls <= 3                    # жёсткий потолок 2, не 99
        assert stats["retries"] <= 2

    @pytest.mark.asyncio
    async def test_base_messages_not_mutated(self):
        base = [{"role": "user", "content": "x"}]
        gen = AsyncMock(side_effect=[_TABLE, "чисто"])
        await verbalize_validated(gen, base, enabled_rules=_PLAIN)
        assert base == [{"role": "user", "content": "x"}]

    def test_cliche_retry_prompt_unreachable(self):
        """§1.1/ADR §3: пути со стилевым retry-промптом больше нет.

        Проверяется КОД, а не документация: имя константы не импортируется и
        не загружается ни в одном выражении модуля (AST-обход игнорирует
        строки докстрингов/комментариев)."""
        tree = ast.parse(inspect.getsource(nc))
        imported = {alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names}
        assert "CLICHE_RETRY_SYSTEM_PROMPT" not in imported
        used: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.append(node.id)
            elif isinstance(node, ast.Attribute):
                used.append(node.attr)
        assert "CLICHE_RETRY_SYSTEM_PROMPT" not in used
        assert not hasattr(nc, "CLICHE_RETRY_SYSTEM_PROMPT")
