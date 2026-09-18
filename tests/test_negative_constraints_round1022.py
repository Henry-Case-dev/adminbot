"""F6 (T-2093, ADR-1022-6 §2.3) — детектор клише + Validator Loop.

Покрытие: каждый код ловится; легитимные фразы — нет; `bullet_list` только по
флагу; брак → ретрай ≤2 → успех; исчерпание → лучший вариант (fallback);
ошибка ретрая → последний успешный; bounded-вызовы; R17-статы (коды/числа);
scrubber применяется на всех путях; kill-switch OFF → один вызов.
"""
import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from services.negative_constraints import (
    DEFAULT_ENABLED_RULES,
    find_forbidden_cliches,
    verbalize_validated,
)

pytestmark = pytest.mark.system2


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


class TestValidatorLoop:
    @pytest.mark.asyncio
    async def test_clean_first_attempt_single_call(self):
        gen = AsyncMock(return_value="нормальный дерзкий текст")
        text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert text == "нормальный дерзкий текст"
        assert gen.await_count == 1
        assert stats == {"attempts": 1, "retries": 0, "hits": [],
                         "fallback": False, "retry_error": False,
                         "enabled": True}

    @pytest.mark.asyncio
    async def test_dirty_then_clean_retries_once(self):
        gen = AsyncMock(side_effect=["ну как ИИ отвечаю", "теперь чисто"])
        text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert text == "теперь чисто"
        assert gen.await_count == 2
        assert stats["attempts"] == 2 and stats["retries"] == 1
        assert stats["fallback"] is False

    @pytest.mark.asyncio
    async def test_exhausted_returns_best_fallback(self):
        gen = AsyncMock(side_effect=[
            "как ИИ и подводя итог",       # 2 кода
            "подводя итог",                # 1 код (лучший)
            "как ИИ в заключение",         # 2 кода
        ])
        text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert gen.await_count == 3          # ≤2 ретрая → ≤3 вызова
        assert text == "подводя итог"
        assert stats["attempts"] == 3 and stats["retries"] == 2
        assert stats["fallback"] is True
        assert stats["hits"] == ["summing_up"]

    @pytest.mark.asyncio
    async def test_retry_generate_error_returns_last_success(self):
        gen = AsyncMock(side_effect=["как ИИ", RuntimeError("boom")])
        text, stats = await verbalize_validated(gen, [{"role": "user", "content": "x"}])
        assert text == "как ИИ"
        assert stats["retry_error"] is True
        assert stats["fallback"] is True
        assert gen.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_message_appended_only_on_retry(self):
        seen = []

        async def gen(messages):
            seen.append([m["role"] for m in messages])
            return "как ИИ" if len(seen) == 1 else "чисто"

        await verbalize_validated(gen, [{"role": "user", "content": "x"}])
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
        gen = AsyncMock(return_value="как ИИ")
        _text, stats = await verbalize_validated(
            gen, [{"role": "user", "content": "x"}], max_retries=99)
        assert gen.await_count == 3          # жёсткий потолок 2, не 99
        assert stats["retries"] == 2

    @pytest.mark.asyncio
    async def test_base_messages_not_mutated(self):
        base = [{"role": "user", "content": "x"}]
        gen = AsyncMock(side_effect=["как ИИ", "чисто"])
        await verbalize_validated(gen, base)
        assert base == [{"role": "user", "content": "x"}]
