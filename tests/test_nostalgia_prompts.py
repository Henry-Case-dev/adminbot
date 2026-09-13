"""Раунд 9 (AGI Memory, spec §3.5.4/§3.5.2/§3.5.1, Q10) — промпт-канон
ностальгии и хелперы рендера (services/nostalgia_prompts.py).

Проверки: канон-текст (системная роль, UNCHANGED-контракт, max_words-слот,
запрет длинных тире в требованиях к ответу); UNCHANGED-детект (регистр/
пробелы); маркер слоя A (формат «nostalgia_hint: вспомни и вплети, если
уместно: [ГГГГ-ММ-ДД] текст» + фикс-кап); строки кандидата «год назад»
(имя/дата/текст); user-блок LLM (секции год-назад и золотых); нормализация
ответа (trim/схлопывание/кап). Никаких сетевых вызовов и БД.
"""
import datetime

from services.nostalgia_prompts import (
    NOSTALGIA_PROMPT,
    PREV_NOSTALGIA_PROMPT,
    build_nostalgia_user,
    clean_llm_text,
    format_golden_line,
    format_nostalgia_hint,
    format_year_back_line,
    is_unchanged_response,
)


# Эталонный слепок ПРЕДЫДУЩЕГО канона (ADR-1013-3): PREV обязан совпадать
# байт-в-байт с текстом до ревампа round 10.15.
_PREV_NOSTALGIA_PROMPT_REFERENCE = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день и/или старые факты по последней теме разговора. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""

# Эталонный слепок НОВОГО канона round 10.15 («эталон = код = тесты»).
_NOSTALGIA_PROMPT_REFERENCE = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день, старые факты по последней теме, а также лор чата и список местных мемов. Вбрось этот старый факт так, как будто ты давний участник беседы, которого внезапно пробило на воспоминания: с иронией и сленгом из лора, по-свойски, будто вспомнил вслух. Не пиши как робот-архивариус. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""


def _ts(offset_days: int) -> int:
    now = datetime.datetime.now()
    return int((now - datetime.timedelta(days=offset_days)).timestamp())


class TestCanon:
    def test_prev_prompt_snapshot_bytes(self):
        # ADR-1013-3: PREV — байт-в-байт слепок канона ДО ревампа 10.15.
        assert PREV_NOSTALGIA_PROMPT == _PREV_NOSTALGIA_PROMPT_REFERENCE

    def test_prompt_reference_bytes(self):
        # «эталон = код = тесты»: новый канон совпадает со слепком теста.
        assert NOSTALGIA_PROMPT == _NOSTALGIA_PROMPT_REFERENCE

    def test_prompt_canon_role_and_unchanged(self):
        text = NOSTALGIA_PROMPT
        assert "токсично-тёплый участник чата" in text
        assert "1-2 короткие фразы" in text or "1-2" in text
        assert "UNCHANGED" in text
        # user-блок «В чате давно тихо. Вот память:» собирается отдельно
        assert "Вот память:" not in text

    def test_prompt_canon_living_style_markers(self):
        # ТЗ §3: живой стиль «давний участник, которого пробило на
        # воспоминания», ирония/сленг из лора, анти-«робот-архивариус».
        text = NOSTALGIA_PROMPT
        assert "давний участник беседы" in text
        assert "пробило на воспоминания" in text
        assert "с иронией и сленгом из лора" in text
        assert "робот-архивариус" in text

    def test_prompt_has_max_words_placeholder(self):
        assert "{max_words}" in NOSTALGIA_PROMPT
        filled = NOSTALGIA_PROMPT.format(max_words=60)
        assert "{max_words}" not in filled
        # ровно один плейсхолдер (ровно одна подстановка)
        assert NOSTALGIA_PROMPT.count("{max_words}") == 1

    def test_prompt_no_em_dash_in_output_rules(self):
        # канон-стиль: длинных тире нет (дефис «-» допустим — дефисные
        # связки в промпте есть у всех канонов)
        assert "—" not in NOSTALGIA_PROMPT
        assert "—" not in PREV_NOSTALGIA_PROMPT

    def test_is_unchanged_response_cases(self):
        assert is_unchanged_response("UNCHANGED")
        assert is_unchanged_response("  unchanged \n")
        assert is_unchanged_response("Unchanged")
        assert not is_unchanged_response("UNCHANGED, кстати")
        assert not is_unchanged_response("")
        assert not is_unchanged_response(None)
        assert not is_unchanged_response("кстати, вася был прав")


class TestLayerAMarker:
    def test_format_nostalgia_hint(self):
        hint = format_nostalgia_hint("вася переехал в москву",
                                     _ts(400), 300)
        assert hint.startswith(
            "nostalgia_hint: вспомни и вплети, если уместно: [")
        assert hint.endswith("вася переехал в москву")
        assert len(hint) <= 300

    def test_format_nostalgia_hint_date_iso(self):
        ts = _ts(400)
        expected = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        hint = format_nostalgia_hint("факт", ts, 300)
        assert f"[{expected}]" in hint

    def test_format_nostalgia_hint_cap_chars(self):
        long_text = " ".join(["очень"] * 200)
        hint = format_nostalgia_hint(long_text, _ts(400), 100)
        assert len(hint) <= 100
        assert hint.startswith("nostalgia_hint:")

    def test_format_nostalgia_hint_empty_inputs(self):
        assert format_nostalgia_hint("", _ts(400), 300) == ""
        assert format_nostalgia_hint("   ", _ts(400), 300) == ""
        assert format_nostalgia_hint("текст", _ts(400), 0) == ""

    def test_format_nostalgia_hint_bad_ts(self):
        hint = format_nostalgia_hint("текст", None, 300)
        assert "[????-??-??]" in hint


class TestCandidateRender:
    def test_year_back_line_with_name(self):
        row = {"user_id": 42, "author_name": "Вася",
               "text": "  ездил в Москву  ", "timestamp": _ts(365)}
        line = format_year_back_line(row)
        assert line.startswith("[Вася ")
        assert line.endswith("]: ездил в Москву")
        assert "  " not in line

    def test_year_back_line_author_fallback(self):
        row = {"user_id": 42, "author_name": "", "text": "текст",
               "timestamp": _ts(365)}
        assert format_year_back_line(row).startswith("[42 ")

    def test_year_back_line_empty_text(self):
        row = {"user_id": 42, "author_name": "Вася", "text": "  ",
               "timestamp": _ts(365)}
        assert format_year_back_line(row) == ""

    def test_golden_line(self):
        row = {"id": 7, "fact": "купил квартиру", "rag_ts": _ts(500)}
        line = format_golden_line(row)
        expected = datetime.datetime.fromtimestamp(
            _ts(500)).strftime("%Y-%m-%d")
        assert line == f"[{expected}] купил квартиру"


class TestUserBlock:
    def test_build_nostalgia_user_only_year_back(self):
        user = build_nostalgia_user(["[Вася 2024-07-12]: переезд"], [])
        assert user.startswith("В чате давно тихо. Вот память:")
        assert "События примерно год назад в этот день" in user
        assert "Старые факты" not in user

    def test_build_nostalgia_user_only_golden(self):
        user = build_nostalgia_user([], ["[2023-01-01] старый факт"])
        assert "Старые факты по последней теме разговора" in user
        assert "год назад" not in user

    def test_build_nostalgia_user_both_sections(self):
        user = build_nostalgia_user(["[Вася 2024-07-12]: a"],
                                    ["[2023-01-01] b", "[2023-01-02] c"])
        assert "События примерно год назад" in user
        assert "Старые факты по последней теме" in user
        assert "[2023-01-01] b" in user
        assert "[2023-01-02] c" in user

    def test_build_nostalgia_user_empty(self):
        assert build_nostalgia_user([], []) == ""

    def test_build_nostalgia_user_backward_compatible(self):
        # обратная совместимость: старый вызов (2 аргумента) без лора/мемов
        user = build_nostalgia_user(["[Вася 2024-07-12]: a"],
                                    ["[2023-01-01] b"])
        assert "Лор чата" not in user
        assert "Локальные мемы" not in user
        assert "События примерно год назад" in user
        assert "Старые факты по последней теме" in user

    def test_build_nostalgia_user_lore_section(self):
        user = build_nostalgia_user([], [], lore="  тут   шутят\nжёстко  ")
        assert "Лор чата (как тут принято общаться):" in user
        assert "тут шутят жёстко" in user

    def test_build_nostalgia_user_memes_section(self):
        rows = [{"fact": "вася = торт", "target_user": "Вася"},
                {"fact": "понедельник = боль", "target_user": None}]
        user = build_nostalgia_user([], [], memes=rows)
        assert "Локальные мемы (местные ярлыки и шутки):" in user
        assert "- [Вася] вася = торт" in user
        assert "- понедельник = боль" in user

    def test_build_nostalgia_user_sections_order(self):
        user = build_nostalgia_user(["[Вася 2024-07-12]: a"],
                                    ["[2023-01-01] b"],
                                    lore="лор", memes=[{"fact": "мем"}])
        i_year = user.index("События примерно год назад")
        i_golden = user.index("Старые факты по последней теме")
        i_lore = user.index("Лор чата")
        i_memes = user.index("Локальные мемы")
        assert i_year < i_golden < i_lore < i_memes

    def test_build_nostalgia_user_lore_capped_by_word(self):
        lore = " ".join(["оченьдлинноеслово"] * 200)
        user = build_nostalgia_user([], [], lore=lore)
        lore_part = user.split("Лор чата (как тут принято общаться):\n", 1)[1]
        assert len(lore_part) <= 600
        assert not lore_part.endswith(" ")
        # обрезка по границе слова: последний токен не обрублен
        assert lore_part.split(" ")[-1] == "оченьдлинноеслово"

    def test_build_nostalgia_user_memes_capped(self):
        rows = [{"fact": f"мем номер {i}"} for i in range(25)]
        user = build_nostalgia_user([], [], memes=rows)
        assert user.count("- мем номер") == 10

    def test_build_nostalgia_user_meme_capped_chars(self):
        rows = [{"fact": "х" * 500, "target_user": "Вася"}]
        user = build_nostalgia_user([], [], memes=rows)
        line = [l for l in user.splitlines() if l.startswith("- [Вася]")][0]
        assert len(line) - len("- [Вася] ") <= 120

    def test_build_nostalgia_user_blank_lore_and_memes_omitted(self):
        user = build_nostalgia_user([], [], lore="   ", memes=[])
        assert user == ""
        # мем с пустым фактом не создаёт секцию
        assert build_nostalgia_user([], [], memes=[{"fact": "  "}]) == ""


class TestCleanText:
    def test_clean_trims_and_collapses(self):
        assert clean_llm_text("  ага,\n\n  как  тогда   ", 400) == \
            "ага, как тогда"

    def test_clean_caps_chars(self):
        text = clean_llm_text("абв" * 300, 400)
        assert len(text) <= 400

    def test_clean_keeps_unchanged_as_text(self):
        # UNCHANGED-детект — отдельная функция; clean не решает статус
        assert clean_llm_text("UNCHANGED", 400) == "UNCHANGED"

    def test_clean_empty(self):
        assert clean_llm_text("", 400) == ""
        assert clean_llm_text(None, 400) == ""
