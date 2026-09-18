"""F6 (раунд 10.22, ADR-1022-6) — egress: regex-scrubber, обёртки, покрытие.

Покрытие:
  * ``sanitize_outgoing``: `<thought>`/`fact:ID`/`msg:ID`; no-op без паттернов;
    ложные срабатывания (обычный текст, URL, «факт:» без цифр); идемпотентность;
  * обёртки ``telegram_send``: guard ON → очистка, OFF → байт-в-байт;
  * реестр ``SEND_POINTS``: покрытие всех send-точек (allowlist с обоснованием);
  * канон R1022: PREV-слепки + ступени миграции + текст ретрая без цитат клише.
"""
from pathlib import Path
import re

import pytest
from unittest.mock import AsyncMock, MagicMock

from config.settings import Settings
from services.outgoing_guard import sanitize_outgoing
from services.prompt_style_blocks import (
    ANTI_BOT_BLOCK,
    CLICHE_RETRY_SYSTEM_PROMPT,
    PREV_ANTI_BOT_BLOCK,
    PREV_STYLE_BLOCKS_SUFFIX,
    STYLE_BLOCKS_SUFFIX,
)
from services.telegram_send import (
    SEND_ALLOWLIST,
    SEND_POINTS,
    edit_text_safe,
    send_text,
)

pytestmark = pytest.mark.system2


class TestSanitizeOutgoing:
    def test_noop_without_patterns_byte_for_byte(self):
        text = "обычный текст: с двоеточием, url https://x.com/a и цифрами 42"
        assert sanitize_outgoing(text) == text

    def test_strips_reasoning_tags(self):
        assert sanitize_outgoing("a <thought>черновик</thought> b") == "a b"

    def test_strips_fact_and_msg_ids(self):
        out = sanitize_outgoing("смотри fact:12723 и msg:42 дальше")
        assert "fact:12723" not in out
        assert "msg:42" not in out
        assert "смотри" in out and "дальше" in out
        assert "  " not in out

    def test_single_separator_on_removal(self):
        assert sanitize_outgoing("до fact:7 после") == "до после"

    def test_token_at_start_or_end(self):
        assert sanitize_outgoing("fact:7 хвост") == "хвост"
        assert sanitize_outgoing("хвост fact:7") == "хвост"

    def test_false_positive_russian_and_word_no_digits(self):
        # кириллическое «факт»/«сообщение» не матчится; латинское без цифр — тоже
        for text in ("вот факт: это текст", "факт: 42", "это сообщение: важно",
                     "msg: семь", "fact:abc"):
            assert sanitize_outgoing(text) == text, text

    def test_urls_and_colons_untouched(self):
        text = "http://site.ru:8080/path?q=1"
        assert sanitize_outgoing(text) == text

    def test_idempotent(self):
        once = sanitize_outgoing("x <thinking>d</thinking> fact:9 y")
        assert sanitize_outgoing(once) == once

    def test_empty_returns_empty(self):
        assert sanitize_outgoing("") == ""
        assert sanitize_outgoing(None) == ""


class TestTelegramSendWrappers:
    @pytest.mark.asyncio
    async def test_send_text_sanitizes_when_guard_on(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        await send_text(bot, 1, "a <thought>x</thought> fact:5 b")
        assert bot.send_message.await_args.args[1] == "a b"

    @pytest.mark.asyncio
    async def test_send_text_passthrough_when_guard_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "TELEGRAM_SEND_GUARD_ENABLED", False)
        bot = MagicMock()
        bot.send_message = AsyncMock()
        await send_text(bot, 1, "a <thought>x</thought>")
        assert bot.send_message.await_args.args[1] == "a <thought>x</thought>"

    @pytest.mark.asyncio
    async def test_edit_text_safe_sanitizes(self):
        message = MagicMock()
        message.edit_text = AsyncMock()
        await edit_text_safe(message, "msg:11 текст")
        assert message.edit_text.await_args.args[0] == "текст"

    def test_guard_is_on_by_default(self):
        """Прод-дефолт рубильника — ON (ревью, High-3: ON-ветка не маскируется)."""
        assert Settings.TELEGRAM_SEND_GUARD_ENABLED is True


class TestSendPointsCoverage:
    _SEND_RE = re.compile(
        r"\.send_message\(|\.edit_message_text\(|\.edit_text\("
        r"|\.reply\(|\.answer\(")

    def _scan(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for base in ("services", "handlers", "web"):
            for path in Path(base).rglob("*.py"):
                if path.name == "telegram_send.py":
                    continue
                text = path.read_text(encoding="utf-8")
                count = len(self._SEND_RE.findall(text))
                if count:
                    found[path.as_posix()] = count
        return found

    def test_every_send_point_is_registered_or_allowlisted(self):
        for rel in self._scan():
            assert rel in SEND_POINTS or rel in SEND_ALLOWLIST, (
                f"незарегистрированная send-точка: {rel}")

    def test_migrated_modules_have_no_bare_sends(self):
        """Модули из SEND_POINTS полностью переведены на обёртки."""
        found = self._scan()
        for rel in SEND_POINTS:
            assert found.get(rel, 0) == 0, f"{rel}: остались прямые send-вызовы"

    def test_registry_has_expected_points(self):
        assert "services/summary_generator.py" in SEND_POINTS
        assert "services/smartmodule_utils.py" in SEND_POINTS

    def test_allowlist_entries_have_justification(self):
        assert SEND_ALLOWLIST
        assert all(reason.strip() for reason in SEND_ALLOWLIST.values())

    def test_voice_transcription_allowlist_justification_explicit(self):
        """S10.22-3: обоснование явно отделяет ASR-транскрипт от Stage-2
        LLM-текста и фиксирует экранирование (raw-теги недостижимы)."""
        reason = SEND_ALLOWLIST["handlers/voice_transcription.py"].lower()
        assert "asr" in reason and "не stage-2" in reason
        assert "html.escape" in reason
        src = Path("handlers/voice_transcription.py").read_text(
            encoding="utf-8")
        # транскрипт экранируется перед отправкой в HTML-режиме
        assert "escaped_text = html.escape(text)" in src
        assert 'parse_mode="HTML"' in src


class TestCanonR1022:
    def test_new_suffix_differs_from_prev(self):
        assert STYLE_BLOCKS_SUFFIX != PREV_STYLE_BLOCKS_SUFFIX
        assert PREV_ANTI_BOT_BLOCK in PREV_STYLE_BLOCKS_SUFFIX
        assert ANTI_BOT_BLOCK not in PREV_STYLE_BLOCKS_SUFFIX
        assert "жанровые штампы" not in PREV_STYLE_BLOCKS_SUFFIX

    def test_retry_message_exact_and_no_cliche_quotes(self):
        assert CLICHE_RETRY_SYSTEM_PROMPT == (
            "Ты нарушил Negative Constraints и использовал запрещенное клише. "
            "Перепиши ответ полностью, сделав его естественным."
        )
        for trop in ("как ИИ", "надеюсь, помог", "нет, ты", "подводя итог"):
            assert trop not in CLICHE_RETRY_SYSTEM_PROMPT

    def test_r1022_prev_steps_present(self):
        from services.prompt_migrations import PROMPT_MIGRATIONS
        pairs = {
            "prompts.direct_chat_system_prompt": ("PREV_R1022_CHAT"),
            "prompts.summary_system_prompt": ("PREV_R1022_SUMMARY"),
            "prompts.checkup_system_prompt": ("PREV_R1022_CHECKUP"),
            "prompts.factcheck_system_prompt": ("PREV_R1022_FACTCHECK"),
            "prompts.search_system_prompt": ("PREV_R1022_SEARCH"),
            "prompts.youtube_system_prompt": ("PREV_R1022_YOUTUBE"),
            "prompts.youtube_video_system_prompt": ("PREV_R1022_YOUTUBE_VIDEO"),
            "prompts.webpage_system_prompt": ("PREV_R1022_WEBPAGE"),
        }
        assert set(pairs) == {k for k in PROMPT_MIGRATIONS if k !=
                              "prompts.compress_system_prompt"}
        from services import (chat_prompts, checkup_prompts, factcheck_prompts,
                              search_prompts, summary_prompts, web_prompts,
                              youtube_prompts)
        prev_map = {
            "prompts.direct_chat_system_prompt":
                chat_prompts.PREV_R1022_CHAT_SYSTEM_PROMPT,
            "prompts.summary_system_prompt":
                summary_prompts.PREV_R1022_SUMMARY_SYSTEM_PROMPT,
            "prompts.checkup_system_prompt":
                checkup_prompts.PREV_R1022_CHECKUP_SYSTEM_PROMPT,
            "prompts.factcheck_system_prompt":
                factcheck_prompts.PREV_R1022_FACTCHECK_SYSTEM_PROMPT,
            "prompts.search_system_prompt":
                search_prompts.PREV_R1022_SEARCH_SYSTEM_PROMPT,
            "prompts.youtube_system_prompt":
                youtube_prompts.PREV_R1022_YOUTUBE_SYSTEM_PROMPT,
            "prompts.youtube_video_system_prompt":
                youtube_prompts.PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT,
            "prompts.webpage_system_prompt":
                web_prompts.PREV_R1022_WEBPAGE_SYSTEM_PROMPT,
        }
        for key, prev in prev_map.items():
            news = [new for p, new in PROMPT_MIGRATIONS[key] if p == prev]
            assert news, key

    @pytest.mark.asyncio
    async def test_r1022_pg_values_migrate_to_new_canon(self):
        """Прод-значение 10.21 (PREV_R1022) мигрирует до нового канона."""
        from services import (chat_prompts, checkup_prompts, factcheck_prompts,
                              search_prompts, summary_prompts, web_prompts,
                              youtube_prompts)
        from services.prompt_migrations import migrate_prompt_canons

        class FakeCache:
            def __init__(self, values):
                self.pg_available = True
                self.values = dict(values)
                self.set_calls = []

            def get(self, key, default=None):
                return self.values.get(key, default)

            async def set(self, key, value, category):
                self.set_calls.append((key, value, category))

        pairs = {
            "prompts.direct_chat_system_prompt":
                chat_prompts.PREV_R1022_CHAT_SYSTEM_PROMPT,
            "prompts.summary_system_prompt":
                summary_prompts.PREV_R1022_SUMMARY_SYSTEM_PROMPT,
            "prompts.checkup_system_prompt":
                checkup_prompts.PREV_R1022_CHECKUP_SYSTEM_PROMPT,
            "prompts.factcheck_system_prompt":
                factcheck_prompts.PREV_R1022_FACTCHECK_SYSTEM_PROMPT,
            "prompts.search_system_prompt":
                search_prompts.PREV_R1022_SEARCH_SYSTEM_PROMPT,
            "prompts.youtube_system_prompt":
                youtube_prompts.PREV_R1022_YOUTUBE_SYSTEM_PROMPT,
            "prompts.youtube_video_system_prompt":
                youtube_prompts.PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT,
            "prompts.webpage_system_prompt":
                web_prompts.PREV_R1022_WEBPAGE_SYSTEM_PROMPT,
        }
        cache = FakeCache(pairs)
        report = await migrate_prompt_canons(cache)
        assert set(report) == set(pairs)
        for _key, _new, _cat in cache.set_calls:
            assert _new not in pairs.values()   # обновилось до НОВОГО канона

