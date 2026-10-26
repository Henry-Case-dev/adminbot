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
    is_self_declining_text,
    is_unchanged_response,
)


# Эталонный слепок ПРЕДЫДУЩЕГО канона (ADR-1013-3): PREV обязан совпадать
# байт-в-байт с текстом до ревампа round 10.15.
_PREV_NOSTALGIA_PROMPT_REFERENCE = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день и/или старые факты по последней теме разговора. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""

# Эталонный слепок НОВОГО канона (ASAP5 W1, 27.10.2026): «эталон = код =
# тесты». FIX-CORRECTIVE-R1 (21.10.2026): канон round 10.15 заменён правкой
# владельца (директива §3 + Addendum #3): императивы «Вбрось…»/«пробило»
# сняты, семантическая оценка ценности кандидата, расширенное право отказа;
# прежние байты — PREV_NOSTALGIA_PROMPT_1021 (в модуле канона).
# ASAP5 W1 (source-2026-10-26 §4/§6/§8): канон R1 дополнен директивой
# владельца §8 дословно (повод/связь, запрет склейки, промолчать), provenance
# «Переслано» (§6) и формой отказа ровно UNCHANGED без публикации
# текста-самоотказа (§5); прежние байты R1 — PREV_NOSTALGIA_PROMPT_1026.
_NOSTALGIA_PROMPT_REFERENCE = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день, старые факты по последней теме, а также лор чата и список местных мемов. Вспоминай прошлое естественно, когда есть интересная связь с разговором или само воспоминание действительно заслуживает внимания - забавная, живая или характерная деталь, из которой складывается история. Не склеивай несвязанные события и не вытягивай смысл из случайных фактов. Говори своими словами, сохраняя характер, юмор и свободу выражения: с иронией и сленгом из лора, будто вспомнил вслух, обычно 1-2 короткими фразами «кстати...», ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Строки памяти с пометкой «Переслано» - чужие новости и материалы не из этого чата: событие из пересланного текста - не событие чата, а люди в нём - не участники чата.

Если из воспоминания не получается осмысленной реплики, лучше промолчи: ответь ровно одним словом - UNCHANGED. Если вспоминать неуместно, память бедна или кандидат скучный/односложный - тоже UNCHANGED. Отказ - нормальный и чаще всего правильный исход: не вытягивай воспоминание из слабого факта, не приписывай участникам того, чего нет в строках памяти и не публикуй текст о том, что вспоминать нечего или что история не та. Решил не вспоминать - ровно одно слово UNCHANGED, а не реплика.
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
        # ТЗ §3: живой стиль — ирония/сленг из лора, «вспомнил вслух».
        # FIX-CORRECTIVE-R1 (21.10.2026, §3 владельца): императивы «Вбрось…»/
        # «пробило»/«не пиши как робот-архивариус» сняты — модель сама
        # семантически оценивает ценность кандидата; отказ расширен и
        # объявлен нормальным исходом; длины в критериях ценности нет
        # (Addendum #3), анти-вымысел — одна строка.
        # ASAP5 W1 (source §8): критерий повода — директива владельца
        # («связь с разговором / само воспоминание заслуживает внимания»).
        text = NOSTALGIA_PROMPT
        assert "с иронией и сленгом из лора" in text
        assert "будто вспомнил вслух" in text
        assert "Вспоминай прошлое естественно" in text
        for imperative in ("Вбрось", "пробило на воспоминания",
                           "робот-архивариус"):
            assert imperative not in text, imperative
        assert "скучный/односложный" in text
        assert "Отказ - нормальный и чаще всего правильный исход" in text
        assert "не приписывай участникам того, чего нет в строках памяти" \
            in text
        # без критериев длины (Addendum #3: семантика, не слова)
        assert "слов" in text  # только max_words-слот
        assert "короче" not in text and "длиннее" not in text

    def test_asap5_owner_directive_verbatim(self):
        """ASAP5 W1 (source §8): директива владельца установлена дословно в
        обоих канонах (4 предложения §8)."""
        sentences = (
            "Вспоминай прошлое естественно, когда есть интересная связь "
            "с разговором или само воспоминание действительно заслуживает "
            "внимания",
            "Не склеивай несвязанные события и не вытягивай смысл из "
            "случайных фактов",
            "Говори своими словами, сохраняя характер, юмор и свободу "
            "выражения",
            "Если из воспоминания не получается осмысленной реплики, лучше "
            "промолчи",
        )
        from services.nostalgia_prompts import NOSTALGIA_CORE_CANON
        for canon in (NOSTALGIA_PROMPT, NOSTALGIA_CORE_CANON):
            for sentence in sentences:
                assert sentence in canon, (sentence, canon)

    def test_asap5_provenance_and_decline_form(self):
        """ASAP5 W1 (source §5/§6): provenance «Переслано» (репост ≠ событие
        чата) и форма отказа — ровно UNCHANGED, без публикации текста
        «вспоминать нечего / история не та»."""
        from services.nostalgia_prompts import NOSTALGIA_CORE_CANON
        for canon in (NOSTALGIA_PROMPT, NOSTALGIA_CORE_CANON):
            assert "Строки памяти с пометкой «Переслано»" in canon
            assert "не участники чата" in canon
            # форма отказа: самоотказ не публикуется как реплика
            assert "не публикуй текст о том, что вспоминать нечего" in canon
            assert "что история не та" in canon
            assert "ровно одно слово UNCHANGED, а не реплика" in canon

    def test_asap5_prev_r1_snapshot_is_outgoing_bytes(self):
        """PREV_1026 — байт-в-байт слепок канона R1 (21.10.2026) для
        отката/диффа: семантическая оценка «Оцени, есть ли…» сохранена."""
        from services.nostalgia_prompts import (
            PREV_NOSTALGIA_CORE_CANON_1026,
            PREV_NOSTALGIA_PROMPT_1026,
        )
        assert "Оцени, есть ли в памяти что-то" in PREV_NOSTALGIA_PROMPT_1026
        assert "Оцени, есть ли здесь что-то" in PREV_NOSTALGIA_CORE_CANON_1026
        assert PREV_NOSTALGIA_PROMPT_1026 != NOSTALGIA_PROMPT
        from services.nostalgia_prompts import NOSTALGIA_CORE_CANON
        assert PREV_NOSTALGIA_CORE_CANON_1026 != NOSTALGIA_CORE_CANON

    def test_core_canon_refusal_and_semantics(self):
        """CORE-канон (ON-путь) синхронен: директива §8 + право отказа +
        анти-вымысел; прежние байты — PREV_NOSTALGIA_CORE_CANON_1021 (R1) и
        PREV_NOSTALGIA_CORE_CANON_1026 (R1→ASAP5 W1)."""
        from services.nostalgia_prompts import (
            NOSTALGIA_CORE_CANON,
            PREV_NOSTALGIA_CORE_CANON_1021,
        )
        assert "Вспоминай прошлое естественно" in NOSTALGIA_CORE_CANON
        assert "вбрось" not in NOSTALGIA_CORE_CANON
        assert "скучный/односложный" in NOSTALGIA_CORE_CANON
        assert "Отказ - нормальный и чаще всего правильный исход" \
            in NOSTALGIA_CORE_CANON
        assert "{max_words}" in NOSTALGIA_CORE_CANON
        assert "—" not in NOSTALGIA_CORE_CANON
        # прежние байты заморожены: императив «вбрось» и узкий отказ
        assert "вбрось этот старый факт" in PREV_NOSTALGIA_CORE_CANON_1021
        assert "Если вспоминать неуместно или память бедна" \
            in PREV_NOSTALGIA_CORE_CANON_1021

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

    def test_year_back_line_forward_provenance_label(self):
        """ASAP5 W1 (source §6): forward-строка несёт «Переслано: источник» —
        репост новости не выглядит как реплика участника."""
        row = {"user_id": 42, "author_name": "Вася",
               "text": "Вера Косачева умерла за 300 метров до финиша",
               "timestamp": _ts(365), "is_forward": 1,
               "forward_source": "Спорт-Новости"}
        line = format_year_back_line(row)
        assert line.startswith("[Вася ")
        assert "| Переслано: Спорт-Новости]" in line
        assert "умерла за 300 метров" in line

    def test_year_back_line_forward_without_source(self):
        row = {"user_id": 42, "author_name": "Вася", "text": "текст",
               "timestamp": _ts(365), "is_forward": 1, "forward_source": ""}
        assert "| Переслано]" in format_year_back_line(row)

    def test_year_back_line_non_forward_backward_compatible(self):
        """Строки без is_forward (легаси-row/старые вызовы) — байт-в-байт
        прежний рендер без provenance-лейбла."""
        row = {"user_id": 42, "author_name": "Вася", "text": "текст",
               "timestamp": _ts(365)}
        line = format_year_back_line(row)
        assert "Переслано" not in line
        assert line == format_year_back_line(dict(row))  # детерминированно
        # is_forward=0 → лейбла нет
        assert "Переслано" not in format_year_back_line(
            {**row, "is_forward": 0, "forward_source": "Спорт-Новости"})

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


class TestSelfDeclineGuard:
    """ASAP5 W1 (source §4/§5, инцидент «не та история»): узкий страж
    самоотказа. Явный вердикт «эта история не годится» → True (текст не
    публикуется); ироничные формы с внешним сходством и обычные реплики —
    False (запрет владельца на универсальный словесный бан)."""

    def test_incident_verdict_detected(self):
        # точная форма инцидента: склейка + вердикт «не та история»
        incident = ("Вспоминать тут особо нечего, кроме того, что Вера "
                    "Косачева умерла за 300 метров до финиша, а Вася тогда "
                    "написал про тромбы ебаные. Это не та история, из "
                    "которой делают кстати")
        assert is_self_declining_text(incident)
        assert is_self_declining_text("это не та история")
        assert is_self_declining_text("История не та, короче")
        # «вспоминать нечего» без содержательного поворота — вердикт
        assert is_self_declining_text("Тут вспоминать нечего")
        assert is_self_declining_text("нечего вспоминать, опять тишина")

    def test_ironic_twist_and_normal_speech_not_blocked(self):
        """Ирония с поворотом «кроме/разве что/только» несёт настоящее
        воспоминание — не блокируется; обычные реплики — не блокируются."""
        assert not is_self_declining_text(
            "Вспоминать тут особо нечего, кроме моего позора годичной "
            "давности, ага")
        assert not is_self_declining_text(
            "вспоминать нечего, разве что как вася торт уронил")
        assert not is_self_declining_text(
            "кстати, год назад мы разъехались по домам в три ночи")
        assert not is_self_declining_text(
            "год назад вася сказал, что это лучший мем чата")
        assert not is_self_declining_text("ничего не помню, я тогда спал")
        assert not is_self_declining_text("")
        assert not is_self_declining_text(None)

    def test_unchanged_flow_untouched(self):
        # страж не пересекается с контрактом UNCHANGED (is_unchanged_response
        # решает раньше; страж срабатывает только на прозе-самоотказе)
        assert not is_self_declining_text("UNCHANGED")
        assert is_unchanged_response("UNCHANGED")
