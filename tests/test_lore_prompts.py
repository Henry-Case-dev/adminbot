"""Раунд 7 (chat-lore-management-v2, T-775, C1) — тесты services/lore_prompts.py.

Канон (spec §3.6): макро-правила (сохранить постоянное/микро-игнор/
UNCHANGED), бюджет {max_words} через .format, запрет кавычек-ёлочек и
длинных тире. Форматирование: инжект-блок §3.6 (разделитель --- только при
двух полях, cap 3000-семантика: авто режется первым, маркер …[обрезано]),
truncate по границе абзаца/предложения, is_unchanged_response,
normalize_lore, user-контент merge/init.
"""
import pytest

from services.lore_prompts import (
    LORE_INIT_SYSTEM_PROMPT,
    LORE_MERGE_SYSTEM_PROMPT,
    PREV_LORE_INIT_SYSTEM_PROMPT,
    PREV_LORE_MERGE_SYSTEM_PROMPT,
    build_init_user,
    build_merge_user,
    format_init_user_content,
    format_lore_block,
    format_merge_user_content,
    is_unchanged_response,
    normalize_lore,
    truncate_with_marker,
)


class TestCanon:
    def test_merge_prompt_canon_rules(self):
        text = LORE_MERGE_SYSTEM_PROMPT
        assert "архивариус многолетнего чата" in text
        assert "дистилляция" in text
        assert "вечной летописи" in text
        assert "КРУПНЕЕ" in text
        assert "крупнейшие события и вехи" in text
        assert "громкие конфликты и примирения" in text
        assert "мемы, традиции" in text
        assert "ключевые имена и роли" in text
        assert "2-4 абзаца" in text
        assert "Максимум {max_words} слов" in text
        assert "UNCHANGED" in text
        assert "без кавычек-ёлочек и длинных тире" in text

    def test_init_prompt_canon_rules(self):
        text = LORE_INIT_SYSTEM_PROMPT
        assert "архивариус чата" in text
        assert "составь лор чата" in text
        assert "{max_words}" in text
        assert "UNCHANGED" in text
        assert "Если в окне нет ничего глобального" in text
        assert "Текущий авто-лор" not in text     # INIT — без merge-секции

    def test_no_elo4ki_and_long_dashes_in_canons(self):
        for prompt in (LORE_MERGE_SYSTEM_PROMPT, LORE_INIT_SYSTEM_PROMPT):
            for bad in ("«", "»", "—", "–"):
                assert bad not in prompt, f"{bad!r} в каноне"

    def test_format_placeholder(self):
        merged = LORE_MERGE_SYSTEM_PROMPT.format(max_words=150)
        assert "Максимум 150 слов" in merged
        assert "{max_words}" not in merged
        init = LORE_INIT_SYSTEM_PROMPT.format(max_words=80)
        assert "максимум 80 слов" in init

    def test_prompts_are_russian_texts(self):
        assert len(LORE_MERGE_SYSTEM_PROMPT) > 400
        assert len(LORE_INIT_SYSTEM_PROMPT) > 250


class TestUnchanged:
    @pytest.mark.parametrize("raw", ["UNCHANGED", " unchanged ", "Unchanged",
                                     "  UNCHANGED\n"])
    def test_true(self, raw):
        assert is_unchanged_response(raw) is True

    @pytest.mark.parametrize("raw", ["UNCHANGED.", "unchanged лор",
                                     "Изменить", "", None, "UNCHANGED\nтекст"])
    def test_false(self, raw):
        assert is_unchanged_response(raw) is False


class TestNormalize:
    def test_collapse_and_strip(self):
        assert normalize_lore("  абзац\n\n\n\n\nвторой  ") == "абзац\n\nвторой"
        assert normalize_lore("") == ""
        assert normalize_lore(None) == ""


class TestTruncate:
    def test_fits_untouched(self):
        assert truncate_with_marker("короткий", 100) == "короткий"

    def test_cut_at_sentence_boundary(self):
        text = "Первое предложение. Второе предложение длинное."
        cut = truncate_with_marker(text, 40)
        assert cut == "Первое предложение.\n…[обрезано]"
        assert len(cut) <= 40

    def test_cut_at_paragraph_boundary(self):
        text = "Абзац один.\n\nАбзац два с продолжением текста."
        cut = truncate_with_marker(text, 30)
        assert cut.startswith("Абзац один")
        assert cut == "Абзац один.\n…[обрезано]"
        assert len(cut) <= 30

    def test_marker_inside_budget(self):
        text = "слово " * 50
        cut = truncate_with_marker(text, 40)
        assert cut.endswith("\n…[обрезано]")
        assert len(cut) <= 40

    def test_zero_limit(self):
        assert truncate_with_marker("текст", 0) == ""
        assert truncate_with_marker("", 10) == ""


class TestLoreBlock:
    def test_empty_block(self):
        assert format_lore_block("", "", 3000) == ""
        assert format_lore_block("   ", None, 3000) == ""

    def test_manual_only(self):
        block = format_lore_block("только ручной", "", 3000)
        assert block == "<chat_lore>\nтолько ручной\n</chat_lore>"

    def test_auto_only(self):
        block = format_lore_block("", "только авто", 3000)
        assert "---" not in block
        assert block == "<chat_lore>\nтолько авто\n</chat_lore>"

    def test_both_with_separator(self):
        block = format_lore_block("ручной", "авто", 3000)
        assert block == "<chat_lore>\nручной\n---\nавто\n</chat_lore>"

    def test_cap_trims_auto_first_manual_intact(self):
        manual = "Ручной лор очень важный и не должен пострадать."
        auto = ("Авто-лор: " + "событие за событием, " * 30).strip()
        block = format_lore_block(manual, auto, 150)
        assert manual in block                 # manual цел
        assert "…[обрезано]" in block          # auto урезан с маркером
        assert len(block) <= 150

    def test_cap_trims_manual_when_needed(self):
        manual = ("Слово повторяющееся " * 40).strip()
        auto = ("Авто-событие повторяющееся " * 40).strip()
        block = format_lore_block(manual, auto, 80)
        assert len(block) <= 80
        assert "…[обрезано]" in block

    def test_cap_zero_returns_empty(self):
        assert format_lore_block("text", "", 0) == ""
        assert format_lore_block("", "", 0) == ""


class TestUserContent:
    def test_merge_content(self):
        text = format_merge_user_content("старый авто", "окно-строки",
                                         ["факт 1", "факт 2"])
        assert "Текущий авто-лор чата:\nстарый авто" in text
        assert "Новые сообщения чата (окно):\nокно-строки" in text
        assert "Защищённые факты о чате:\n- факт 1\n- факт 2" in text

    def test_merge_content_no_auto(self):
        text = format_merge_user_content("", "окно")
        assert "(нет)" in text

    def test_merge_content_no_facts_section(self):
        text = format_merge_user_content("авто", "окно", [])
        assert "Защищённые факты" not in text

    def test_init_content(self):
        text = format_init_user_content("окно", ["факт"])
        assert "Текущий авто-лор" not in text
        assert "Новые сообщения чата (окно):\nокно" in text
        assert "- факт" in text


class TestBuildHelpers:
    """build_merge_user/build_init_user — интерфейс постановки (воркер C1)."""

    def test_build_merge_user_lines(self):
        lines = ["[2026-09-05 14:03] Саша: ну что",
                 "[2026-09-05 18:41] Ксюша: ахахах"]
        text = build_merge_user("старый авто", lines, window_hours=24)
        assert "Текущий авто-лор чата:\nстарый авто" in text
        assert "окно, последние 24 ч" in text
        assert lines[0] in text and lines[1] in text

    def test_build_merge_user_empty_auto_and_no_hours(self):
        text = build_merge_user("", ["строка"])
        assert "(нет)" in text
        assert "Новые сообщения чата (окно):" in text
        assert "последние" not in text

    def test_build_merge_user_facts(self):
        text = build_merge_user("авто", ["строка"], facts=["факт 1"])
        assert "- факт 1" in text

    def test_build_init_user_has_no_merge_section(self):
        text = build_init_user(["строка окна"], window_hours=6)
        assert "Текущий авто-лор" not in text
        assert "окно, последние 6 ч" in text
        assert "строка окна" in text

    def test_build_init_user_matches_format_init(self):
        assert build_init_user(["s1", "s2"]) == \
            format_init_user_content("s1\ns2")


# F8 (cognition-irony-dossier-round1013, spec §4.2, ADR-1013-3 §2): PREV-слепки
# прежних канонов (байт-в-байт до «иронической» заметки) + байт-тесты нового
# канона. PROMPT_MIGRATIONS не трогается (канон — не PG-сид).
_PREV_LORE_MERGE_SYSTEM_PROMPT_REFERENCE = """\
Ты - архивариус многолетнего чата. Твоя задача - дистилляция лора: превращать разрозненные события в укрупнённую, "эпичную" картину жизни чата. Это НЕ пересказ новых сообщений - это обновление вечной летописи.

У тебя есть: текущий лор (летопись) и новые сообщения за последний период.

ПРОЦЕСС (строго по шагам):
1. Впитай новую информацию из сообщений.
2. Пересмотри ВЕСЬ лор целиком.
3. Перепиши его так, чтобы он становился КРУПНЕЕ: разовые события сжимай в обобщения; детали, которые не закрепились (разовый трёп, бытовые ссоры, "кто куда сходил/что поел"), отбрасывай.
4. Сохраняй и добавляй ТОЛЬКО то, что имеет вес для истории:
   - крупнейшие события и вехи (переезды, перерождения, сходки, громкие конфликты и примирения);
   - значимые изменения в отношениях и статусах ключевых персон;
   - особенности локации/чата (как менялось место, название, состав);
   - устойчивые (повторяющиеся) мемы, традиции, привычки;
   - смешные события, получившие резонанс;
   - ключевые имена и роли.
5. Интегрируй новое в существующий текст: если веха уже есть - уточни/усиль; если новое событие "прошло бесследно" - НЕ добавляй.

СТИЛЬ: связный текст, 2-4 абзаца; каждая фраза несёт вес; с каждым обновлением лор становится плотнее и лаконичнее по духу (то же или меньше слов, но больше смысла), а не простынёй деталей. Без нумерации, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов.

Если за период не произошло ничего глобального и лор менять не нужно - ответь ровно одной строкой: UNCHANGED
"""

_PREV_LORE_INIT_SYSTEM_PROMPT_REFERENCE = """\
Ты архивариус чата. По сообщениям чата за последнее время составь лор чата: кто эти
люди, чем живёт чат, ключевые мемы, истории, статусы, вайб.

Верни связный текст на русском, 1-3 абзаца, максимум {max_words} слов, в стиле сообщений
этого чата. Не используй кавычки-ёлочки и длинные тире.

Если в окне нет ничего глобального, верни ровно строку: UNCHANGED
"""


class TestCanonDeltaF8:
    """F8: PREV-слепки == прежний текст; новый канон = PREV + ироническая
    заметка; PROMPT_MIGRATIONS не трогается."""

    def test_prev_merge_byte_exact(self):
        assert PREV_LORE_MERGE_SYSTEM_PROMPT == \
            _PREV_LORE_MERGE_SYSTEM_PROMPT_REFERENCE

    def test_prev_init_byte_exact(self):
        assert PREV_LORE_INIT_SYSTEM_PROMPT == \
            _PREV_LORE_INIT_SYSTEM_PROMPT_REFERENCE

    def test_new_merge_is_prev_plus_note(self):
        assert LORE_MERGE_SYSTEM_PROMPT != PREV_LORE_MERGE_SYSTEM_PROMPT
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" in LORE_MERGE_SYSTEM_PROMPT
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" not in PREV_LORE_MERGE_SYSTEM_PROMPT

    def test_new_init_is_prev_plus_note(self):
        assert LORE_INIT_SYSTEM_PROMPT != PREV_LORE_INIT_SYSTEM_PROMPT
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" in LORE_INIT_SYSTEM_PROMPT
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" not in PREV_LORE_INIT_SYSTEM_PROMPT

    def test_not_registered_in_prompt_migrations(self):
        import inspect
        from services import prompt_migrations
        source = inspect.getsource(prompt_migrations).lower()
        assert "lore_merge" not in source
        assert "lore_init" not in source
