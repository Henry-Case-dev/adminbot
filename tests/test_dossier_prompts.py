"""F8 (cognition-irony-dossier-round1013, spec §4/§6) — тесты канона досье.

Покрытие: байт-канон DOSSIER_SYSTEM_PROMPT (дословная инструкция ТЗ §2 +
JSON-контракт), greenfield PREV-слепок, keyword fail-safe, парсер ответа
(UNCHANGED/пусто/кривой JSON/мусор/канон-target), user-контент и рендер
двух блоков [Факты]/[Локальные мемы/Ярлыки] с общим cap (мемы первыми).
"""
import pytest

from services.dossier_prompts import (
    DOSSIER_SYSTEM_PROMPT,
    KEYWORD_MEME_HINTS,
    PREV_DOSSIER_SYSTEM_PROMPT,
    build_dossier_user,
    format_dossier_block,
    matches_meme_hint,
    parse_dossier_answer,
)

_TZ_INSTRUCTION = (
    "Пользователи часто шутят и используют сарказм. Оскорбительные или "
    "абсурдные титулы (например, 'мегачмо', 'повелитель грибов') записывать "
    "в отдельный массив `chat_memes`, а не в `real_facts`."
)


class TestCanon:
    def test_tz_instruction_verbatim(self):
        """Дословная инструкция ТЗ §2 в каноне."""
        assert _TZ_INSTRUCTION in DOSSIER_SYSTEM_PROMPT

    def test_json_contract_present(self):
        assert '"real_facts"' in DOSSIER_SYSTEM_PROMPT
        assert '"chat_memes"' in DOSSIER_SYSTEM_PROMPT
        assert '{"target":"Имя","text":"..."}' in DOSSIER_SYSTEM_PROMPT

    def test_no_elo4ki_and_long_dashes(self):
        """Канон-дисциплина (NFR-6): без «», — , –."""
        for bad in ("«", "»", "—", "–"):
            assert bad not in DOSSIER_SYSTEM_PROMPT, f"{bad!r} в каноне"

    def test_irony_filter_named(self):
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" in DOSSIER_SYSTEM_PROMPT

    def test_prev_is_empty_greenfield(self):
        """F8: отдельного канона досье до фичи не было — слепок пуст."""
        assert PREV_DOSSIER_SYSTEM_PROMPT == ""
        assert PREV_DOSSIER_SYSTEM_PROMPT != DOSSIER_SYSTEM_PROMPT

    def test_not_registered_in_prompt_migrations(self):
        import inspect
        from services import prompt_migrations
        source = inspect.getsource(prompt_migrations).lower()
        assert "dossier" not in source


class TestKeywordHints:
    @pytest.mark.parametrize("phrase", ["мегачмо", "повелитель грибов",
                                        "Мегачмо", "ПОВЕЛИТЕЛЬ ГРИБОВ",
                                        "наш король", "бог этого чата"])
    def test_hint_matches(self, phrase):
        assert matches_meme_hint(phrase) is True

    @pytest.mark.parametrize("phrase", ["", None, "вася живёт в москве",
                                        "богатый улов", "королевский приём"])
    def test_hint_no_match(self, phrase):
        assert matches_meme_hint(phrase) is False

    def test_spec_hints_present(self):
        assert "мегачмо" in KEYWORD_MEME_HINTS
        assert "повелитель грибов" in KEYWORD_MEME_HINTS


class TestParseDossierAnswer:
    def test_unchanged_and_empty(self):
        for raw in ("UNCHANGED", " unchanged ", "", None):
            assert parse_dossier_answer(raw) == {"real_facts": [],
                                                 "chat_memes": []}

    def test_valid_split(self):
        raw = ('{"real_facts":[{"target":"Вася","text":"Вася живёт в Москве"}],'
               '"chat_memes":[{"target":"Вася","text":"наш король"}]}')
        out = parse_dossier_answer(raw)
        assert out["real_facts"][0]["text"] == "Вася живёт в Москве"
        assert out["chat_memes"][0]["text"] == "наш король"

    def test_fenced_json(self):
        raw = '```json\n{"real_facts":[],"chat_memes":[{"target":"a","text":"x"}]}\n```'
        out = parse_dossier_answer(raw)
        assert out["chat_memes"][0]["text"] == "x"

    def test_bad_json_raises(self):
        with pytest.raises(ValueError):
            parse_dossier_answer("это не json")
        with pytest.raises(ValueError):
            parse_dossier_answer("[1,2,3]")
        with pytest.raises(ValueError):
            parse_dossier_answer('{"no_keys":1}')
        with pytest.raises(ValueError):
            parse_dossier_answer('{"real_facts":"x"}')

    def test_invalid_items_dropped(self):
        raw = ('{"real_facts":[null,"x",{"target":"a"},'
               '{"target":"b","text":"ок"}],"chat_memes":[]}')
        out = parse_dossier_answer(raw)
        assert [f["text"] for f in out["real_facts"]] == ["ок"]

    def test_keyword_failsafe_moves_facts_to_memes(self):
        """Мем, ошибочно попавший в real_facts, принудительно уходит в memes."""
        raw = ('{"real_facts":[{"target":"Вася","text":"мегачмо"},'
               '{"target":"Вася","text":"Вася живёт в Москве"}],'
               '"chat_memes":[]}')
        out = parse_dossier_answer(raw)
        assert [f["text"] for f in out["real_facts"]] == ["Вася живёт в Москве"]
        memes = {m["text"]: m["classified_by"] for m in out["chat_memes"]}
        assert memes == {"мегачмо": "keyword"}

    def test_canon_target_applied(self):
        raw = '{"real_facts":[],"chat_memes":[{"target":"Вася","text":"x"}]}'
        out = parse_dossier_answer(raw, canon=lambda n: n.lower())
        assert out["chat_memes"][0]["target"] == "вася"


class TestBuildDossierUser:
    def test_roster_and_window(self):
        text = build_dossier_user(["[ts] Вася: привет"], ["Вася", "Петя"])
        lines = text.splitlines()
        assert lines[0].startswith("Участники чата")
        assert "Вася, Петя" in lines[1]
        assert "[ts] Вася: привет" in lines
        assert "Свежие сообщения чата:" in lines

    def test_empty_window(self):
        text = build_dossier_user([], [])
        assert "(сообщений нет)" in text


class TestFormatDossierBlock:
    def test_two_blocks(self):
        out = format_dossier_block(["Вася живёт в Москве"], ["мегачмо"], 0)
        assert "[Факты]" in out
        assert "[Локальные мемы/Ярлыки]" in out
        assert out.index("[Факты]") < out.index("[Локальные мемы/Ярлыки]")

    def test_empty_block_not_rendered(self):
        assert format_dossier_block(["факт"], [], 0) \
            == "[Факты]\nфакт"
        assert format_dossier_block([], ["мем"], 0) \
            == "[Локальные мемы/Ярлыки]\nмем"

    def test_both_empty(self):
        assert format_dossier_block([], [], 0) == ""

    def test_memes_cut_first(self):
        facts = ["факт один", "факт два"]
        memes = ["мегачмо", "повелитель грибов"]
        one_meme = format_dossier_block(facts, memes[:1], 0)
        capped = format_dossier_block(facts, memes, len(one_meme))
        assert capped == one_meme
        assert "повелитель грибов" not in capped
        facts_only = format_dossier_block(facts, [], 0)
        capped2 = format_dossier_block(facts, memes, len(facts_only))
        assert capped2 == facts_only
        assert "факт один" in capped2 and "факт два" in capped2

    def test_zero_cap_is_unlimited(self):
        assert format_dossier_block(["a", "b"], ["c"], 0) != ""
