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
    """BGS-04: повтор остаётся только у form/numeric в реальной
    трансформации; формат доставки и метатекст — наблюдение."""

    @pytest.mark.asyncio
    async def test_format_tables_observed_not_regenerated(self):
        """Табличная разметка: код наблюдения, второго вызова LLM нет."""
        gen = AsyncMock(return_value=_TABLE)
        text, stats = await verbalize_validated(gen, list(_BASE),
                                                enabled_rules=_PLAIN)
        assert text == _TABLE                    # текст модели как есть
        assert gen.await_count == 1
        assert stats["format_observed"] == ["plain_no_tables"]
        assert "format_retry" not in stats
        assert "format_fallback" not in stats

    @pytest.mark.asyncio
    async def test_format_bullets_observed_not_regenerated(self):
        """Списки: формат — вкусовая форма, повтора нет."""
        gen = AsyncMock(return_value=_BULLETS)
        text, stats = await verbalize_validated(
            gen, list(_BASE), enabled_rules={"bullet_list"})
        assert text == _BULLETS
        assert gen.await_count == 1
        assert stats["format_observed"] == ["bullet_list"]
        assert CLICHE_RETRY_SYSTEM_PROMPT not in str(stats)

    @pytest.mark.asyncio
    async def test_form_guard_retries_with_own_reason(self):
        """Реальная трансформация (Stage-1 → Stage-2): form-гард даёт
        ровно один повтор своим каноном — числа/имена сохраняются."""
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
    async def test_numeric_guard_no_reroll_keeps_author_text(self):
        """Свободная генерация: число не подтверждено, но второй
        генерации нет и исходный текст не исчезает (BGS-04 §1-2)."""
        class _Claim:
            value = 9
            unit = "messages"

        gen = AsyncMock(return_value="он писал 7 сообщений")
        text, stats = await verbalize_validated(
            gen, list(_BASE),
            numeric_contract=NumericContract(claims=(_Claim(),)))
        assert gen.await_count == 1
        assert text == "он писал 7 сообщений"       # не пусто и не выдумка
        assert stats["numeric_claim_mismatch"] == 1
        assert stats["numeric_claim_retry"] is False
        assert stats["numeric_claim_fallback"] is False
        assert stats["numeric_claim_reason"] == nc.NUMERIC_CLAIM_MISMATCH

    @pytest.mark.asyncio
    async def test_numeric_free_path_uses_verified_phrase(self):
        """Если есть проверенная фраза хода — детерминированная замена
        без LLM-повтора."""
        class _Claim:
            value = 9
            unit = "messages"

        gen = AsyncMock(return_value="он писал 7 сообщений")
        text, stats = await verbalize_validated(
            gen, list(_BASE),
            numeric_contract=NumericContract(
                claims=(_Claim(),), verified_phrase="он писал 9 сообщений"))
        assert gen.await_count == 1
        assert text == "он писал 9 сообщений"
        assert stats["numeric_claim_fallback"] is True
        assert stats["numeric_claim_retry"] is False

    @pytest.mark.asyncio
    async def test_metatext_observed_not_retried(self):
        """Метатекст — наблюдение: ни повтора, ни правки текста."""
        def reason(text):
            return "metatext_test" if "служебный маркер" in text else None

        gen = AsyncMock(return_value="служебный маркер тут")
        text, stats = await verbalize_validated(
            gen, list(_BASE), metatext_reason=reason)
        assert gen.await_count == 1
        assert text == "служебный маркер тут"
        assert stats["metatext_observed"] == ["metatext_test"]
        assert "metatext_retry" not in stats
        assert "metatext_fallback" not in stats

    @pytest.mark.asyncio
    async def test_style_plus_numeric_no_regeneration(self):
        """Стиль + число: ровно один вызов, стиль наблюдаем, число
        исправляется детерминированной проверенной фразой."""
        class _Claim:
            value = 9
            unit = "messages"

        calls: list[list[dict]] = []

        async def gen(messages):
            calls.append([dict(m) for m in messages])
            return "как ИИ: он писал 7 сообщений"

        text, stats = await verbalize_validated(
            gen, list(_BASE),
            numeric_contract=NumericContract(
                claims=(_Claim(),), verified_phrase="он писал 9 сообщений"))
        assert len(calls) == 1
        assert text == "он писал 9 сообщений"
        assert stats["cliche_observed"] == ["as_ai"]
        assert stats["anti_cliche_retries"] == 0
        assert stats["numeric_claim_retry"] is False

    @pytest.mark.asyncio
    async def test_style_plus_format_keeps_text(self):
        """Стиль + таблица: текст доставляется как есть, оба кода видны
        в наблюдении."""
        text_in = "как ИИ\n" + _TABLE
        gen = AsyncMock(return_value=text_in)
        text, stats = await verbalize_validated(gen, list(_BASE),
                                               enabled_rules=_PLAIN)
        assert text == text_in
        assert gen.await_count == 1
        assert stats["format_observed"] == ["plain_no_tables"]
        assert stats["cliche_observed"] == ["as_ai"]
        assert stats["anti_cliche_retries"] == 0

    @pytest.mark.asyncio
    async def test_guard_budget_single_call_for_observations(self):
        """Наблюдения (метатекст) не расходуют бюджет LLM вовсе."""
        calls: int = 0

        def reason(text):
            return "metatext_test" if "служебный маркер" in text else None

        async def gen(messages):
            nonlocal calls
            calls += 1
            return "служебный маркер тут"

        _text, stats = await verbalize_validated(
            gen, list(_BASE), max_retries=99,
            metatext_reason=reason)
        assert calls == 1
        assert stats["retries"] == 0
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
    async def test_format_dirty_delivered_without_second_call(self):
        """Форматная находка: один вызов, текст модели доставлен."""
        gen = AsyncMock(return_value=_TABLE)
        text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], enabled_rules=_PLAIN)
        assert text == _TABLE
        assert gen.await_count == 1
        assert stats["attempts"] == 1 and stats["retries"] == 0
        assert stats["fallback"] is False
        assert stats["format_observed"] == ["plain_no_tables"]

    @pytest.mark.asyncio
    async def test_retry_generate_error_returns_last_success(self):
        """Ошибка generate на form-повторе → проверенный черновик."""
        class Boom:
            def __init__(self):
                self.n = 0

            async def __call__(self, messages):
                self.n += 1
                if self.n == 1:
                    return "13 штук"
                raise RuntimeError("boom")

        text, stats = await verbalize_validated(
            Boom(), [{"role": "user", "content": "x"}],
            form_contract=FormContract(source_text="двенадцать штук"),
            fallback_text="двенадцать штук")
        assert text == "двенадцать штук"
        assert stats["retry_error"] is True
        assert stats["fallback"] is True

    @pytest.mark.asyncio
    async def test_retry_message_appended_only_on_retry(self):
        """Системное сообщение повтора добавляется только на повторе."""
        seen = []

        async def gen(messages):
            seen.append([m["role"] for m in messages])
            return "13 штук" if len(seen) == 1 else "двенадцать штук"

        await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            form_contract=FormContract(source_text="двенадцать штук"))
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
        """Бюджет повторов общий и не растёт: ≤2 повтора (≤3 генерации);
        form-причина расходуется один раз."""
        calls = 0

        async def gen(messages):
            nonlocal calls
            calls += 1
            return "13 штук"

        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            max_retries=99,
            form_contract=FormContract(source_text="двенадцать штук"))
        assert calls <= 3                    # жёсткий потолок 2, не 99
        assert stats["retries"] <= 2

    @pytest.mark.asyncio
    async def test_base_messages_not_mutated(self):
        base = [{"role": "user", "content": "x"}]
        gen = AsyncMock(side_effect=["13 штук", "двенадцать штук"])
        await verbalize_validated(
            gen, base,
            form_contract=FormContract(source_text="двенадцать штук"))
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

    def test_metatext_and_format_retry_prompts_unreachable(self):
        """BGS-03/04: метатекст/формат больше не причины повтора — их
        retry-каноны не импортируются и не используются модулем."""
        tree = ast.parse(inspect.getsource(nc))
        imported = {alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names}
        assert "METATEXT_RETRY_SYSTEM_PROMPT" not in imported
        assert "FORMAT_PLAIN_TEXT_BLOCK" not in imported
        assert "FORMAT_NO_LISTS_RETRY_TEXT" not in imported
        assert not hasattr(nc, "format_retry_system_prompt")
