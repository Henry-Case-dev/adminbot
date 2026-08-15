import pytest
from unittest.mock import MagicMock

from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.danger_word import DangerWordFilter
from filters.word_lists import DANGER_PHRASES


class TestUserIdFilter:
    @pytest.mark.asyncio
    async def test_matching_user_passes(self, make_message):
        f = UserIdFilter(479167456, 350803143)
        msg = make_message(479167456, text="hello")
        assert await f(msg) is True

    @pytest.mark.asyncio
    async def test_non_matching_user_fails(self, make_message):
        f = UserIdFilter(479167456)
        msg = make_message(999999999, text="hello")
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_no_from_user_fails(self, make_message):
        f = UserIdFilter(479167456)
        msg = make_message(0, text="hello")
        msg.from_user = None
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_any_message_type_passes(self, make_message):
        f = UserIdFilter(479167456)
        msg = make_message(479167456, text=None)
        msg.from_user = MagicMock()
        msg.from_user.id = 479167456
        assert await f(msg) is True


class TestKuchaWordFilter:
    @pytest.mark.asyncio
    async def test_kucha_matches(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "КУЧА")) is True

    @pytest.mark.asyncio
    async def test_kuchi_matches(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучи")) is True

    @pytest.mark.asyncio
    async def test_kuche_matches(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "о куче")) is True

    @pytest.mark.asyncio
    async def test_kuchu_matches(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "в кучу")) is True

    @pytest.mark.asyncio
    async def test_embedded_word_matches(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "смотри куча денег")) is True

    @pytest.mark.asyncio
    async def test_no_kucha_fails(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "привет как дела")) is False

    @pytest.mark.asyncio
    async def test_empty_text_fails(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, "")) is False

    @pytest.mark.asyncio
    async def test_none_text_fails(self, make_message):
        f = KuchaWordFilter()
        assert await f(make_message(1, None)) is False

    # ── Regression: forms that must NOT match ──

    @pytest.mark.asyncio
    async def test_kuchek_not_matched(self, make_message):
        """'кучек' — genitive plural of diminutive 'кучка', NOT a form of 'куча'."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучек")) is False

    @pytest.mark.asyncio
    async def test_kuchka_not_matched(self, make_message):
        """'кучка' — diminutive, NOT a form of 'куча'."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучка")) is False

    @pytest.mark.asyncio
    async def test_kuchki_not_matched(self, make_message):
        """'кучки' — diminutive, NOT a form of 'куча'."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучки")) is False

    # ── Regression: forms that MUST match ──

    @pytest.mark.asyncio
    async def test_kuch_genitive_plural_matches(self, make_message):
        """'куч' (много куч) — valid genitive plural of 'куча'."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "много куч")) is True

    @pytest.mark.asyncio
    async def test_kucheyu_matches(self, make_message):
        """'кучею' — valid instrumental singular form."""
        f = KuchaWordFilter()
        assert await f(make_message(1, "кучею")) is True


class TestDangerWordFilter:
    @pytest.mark.asyncio
    async def test_dron_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "летит дрон"))

    @pytest.mark.asyncio
    async def test_raketa_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "ракета прилетела"))

    @pytest.mark.asyncio
    async def test_bunker_matches(self, make_message):
        """Epic 23: matches via phrase 'иди в бункер' (single 'бункер' removed)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "иди в бункер"))
        assert result == {"matched_word": "иди в бункер"}

    @pytest.mark.asyncio
    async def test_vspyshka_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "вспышка справа"))

    @pytest.mark.asyncio
    async def test_prilet_not_matched(self, make_message):
        """Epic 23: 'прилет' removed from the dictionary — must NOT match."""
        f = DangerWordFilter()
        assert await f(make_message(1, "прилет в соседний дом")) is False

    @pytest.mark.asyncio
    async def test_ukrytie_matches(self, make_message):
        """Epic 23: matches via phrase 'бегом в укрытие' (single 'укрытие' removed)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "бегом в укрытие"))
        assert result == {"matched_word": "бегом в укрытие"}

    @pytest.mark.asyncio
    async def test_letit_not_matched(self, make_message):
        """Epic 23: 'летит' removed from the dictionary — must NOT match."""
        f = DangerWordFilter()
        assert await f(make_message(1, "летит птица")) is False

    @pytest.mark.asyncio
    async def test_no_war_word_fails(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "хорошая погода сегодня")) is False

    @pytest.mark.asyncio
    async def test_empty_text_fails(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "")) is False

    @pytest.mark.asyncio
    async def test_none_text_fails(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, None)) is False

    @pytest.mark.asyncio
    async def test_war_word_not_at_boundary(self, make_message):
        """'беспилотники' should match 'беспилотник' pattern"""
        f = DangerWordFilter()
        result = await f(make_message(1, "беспилотники"))
        assert result

    @pytest.mark.asyncio
    async def test_multiple_war_words_fires_once(self, make_message):
        """Filter returns dict on first match (short-circuits)."""
        f = DangerWordFilter()
        assert await f(make_message(1, "дрон летит ракета бункер"))

    @pytest.mark.asyncio
    async def test_synonyms_all_covered(self, make_message):
        """Test each synonym group has at least one matching word."""
        f = DangerWordFilter()
        test_words = [
            ("дронов много", True),
            ("беспилотник замечен", True),
            ("ракет не хватит", True),
        ]
        for text, expected in test_words:
            assert bool(await f(make_message(1, text))) == expected

    # ── New v2 keywords (Epic 10) ──

    @pytest.mark.asyncio
    async def test_opasnost_matches(self, make_message):
        """New keyword: опасность"""
        f = DangerWordFilter()
        assert await f(make_message(1, "опасность атаки"))

    @pytest.mark.asyncio
    async def test_bpla_matches(self, make_message):
        """New keyword: БПЛА"""
        f = DangerWordFilter()
        assert await f(make_message(1, "БПЛА в небе"))

    @pytest.mark.asyncio
    async def test_raketnaya_matches(self, make_message):
        """New keyword: ракетная"""
        f = DangerWordFilter()
        assert await f(make_message(1, "ракетная опасность"))

    @pytest.mark.asyncio
    async def test_ubezhishe_matches(self, make_message):
        """Epic 23: 'пройдите в убежище' matches via phrase 'в убежище'."""
        f = DangerWordFilter()
        result = await f(make_message(1, "пройдите в убежище"))
        assert result == {"matched_word": "в убежище"}

    @pytest.mark.asyncio
    async def test_ubezhishe_alone_not_matched(self, make_message):
        """Epic 23: single 'убежище' removed from the dictionary — must NOT match."""
        f = DangerWordFilter()
        assert await f(make_message(1, "убежище")) is False

    @pytest.mark.asyncio
    async def test_vnimanie_matches(self, make_message):
        """New keyword: внимание"""
        f = DangerWordFilter()
        assert await f(make_message(1, "внимание всем"))

    @pytest.mark.asyncio
    async def test_bespilotnoy_matches(self, make_message):
        """New keyword: беспилотной"""
        f = DangerWordFilter()
        assert await f(make_message(1, "беспилотной авиации"))

    @pytest.mark.asyncio
    async def test_bespilotnaya_matches(self, make_message):
        """New keyword: беспилотная"""
        f = DangerWordFilter()
        assert await f(make_message(1, "беспилотная угроза"))

    @pytest.mark.asyncio
    async def test_opoveshenie_matches(self, make_message):
        """New keyword: оповещение"""
        f = DangerWordFilter()
        assert await f(make_message(1, "срочное оповещение"))

    @pytest.mark.asyncio
    async def test_sirena_matches(self, make_message):
        """New keyword: сирена"""
        f = DangerWordFilter()
        assert await f(make_message(1, "воет сирена"))

    @pytest.mark.asyncio
    async def test_ataka_matches(self, make_message):
        """Epic 23: matches via phrase 'атака беспилотников' (single 'атака' removed)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "атака беспилотников"))
        assert result == {"matched_word": "атака беспилотников"}

    @pytest.mark.asyncio
    async def test_obstrel_matches(self, make_message):
        """Epic 23: matches via phrase 'ракетный обстрел' (single 'обстрел' removed)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "ракетный обстрел"))
        assert result == {"matched_word": "ракетный обстрел"}

    @pytest.mark.asyncio
    async def test_trevoga_matches(self, make_message):
        """New keyword: тревога"""
        f = DangerWordFilter()
        assert await f(make_message(1, "воздушная тревога"))

    @pytest.mark.asyncio
    async def test_evakuatsiya_matches(self, make_message):
        """New keyword: эвакуация"""
        f = DangerWordFilter()
        assert await f(make_message(1, "срочная эвакуация"))

    @pytest.mark.asyncio
    async def test_vzryv_matches(self, make_message):
        """New keyword: взрыв"""
        f = DangerWordFilter()
        assert await f(make_message(1, "слышен взрыв"))

    @pytest.mark.asyncio
    async def test_otboy_matches(self, make_message):
        """New keyword: отбой"""
        f = DangerWordFilter()
        assert await f(make_message(1, "отбой тревоги"))

    @pytest.mark.asyncio
    async def test_upal_not_matched(self, make_message):
        """Epic 23: 'упал' removed from the dictionary — must NOT match."""
        f = DangerWordFilter()
        assert await f(make_message(1, "ребёнок упал")) is False

    @pytest.mark.asyncio
    async def test_sbit_not_matched(self, make_message):
        """Epic 23: 'сбит' removed from the dictionary — must NOT match."""
        f = DangerWordFilter()
        assert await f(make_message(1, "самолёт сбит")) is False

    # ── Caption support (T-057 fix) ──

    @pytest.mark.asyncio
    async def test_caption_matches_keyword(self, make_message):
        """Filter should check message.caption when text is None."""
        f = DangerWordFilter()
        msg = make_message(479167456, text=None)
        msg.caption = "опасность атаки дронов"
        assert await f(msg)

    @pytest.mark.asyncio
    async def test_caption_none_and_text_none_fails(self, make_message):
        """When both text and caption are None, filter returns False."""
        f = DangerWordFilter()
        msg = make_message(479167456, text=None)
        msg.caption = None
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_text_takes_priority_over_caption(self, make_message):
        """When both text and caption exist, text should be checked (both are checked)."""
        f = DangerWordFilter()
        msg = make_message(479167456, text="опасность")
        msg.caption = "безопасный текст"
        # 'опасность' in text matches
        assert await f(msg)

    @pytest.mark.asyncio
    async def test_caption_with_media_keyword(self, make_message):
        """Forwarded photo with caption containing keywords."""
        f = DangerWordFilter()
        msg = make_message(479167456, text=None)
        msg.caption = "БПЛА замечен в районе"
        assert await f(msg)

    @pytest.mark.asyncio
    async def test_caption_empty_string(self, make_message):
        """Empty caption should not match."""
        f = DangerWordFilter()
        msg = make_message(479167456, text=None)
        msg.caption = ""
        assert await f(msg) is False


class TestDangerPhrases:
    """Epic 23 (D55–D58): phrase branch of DangerWordFilter."""

    SINGLE_WORDS_REMOVED = [
        "атака", "угроза", "обстрел", "укрытие", "убежище",
        "бункер", "бомбоубежище", "летит", "прилет", "сбит",
        "упал", "падение",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("phrase", DANGER_PHRASES)
    async def test_all_phrases_standalone_match(self, make_message, phrase):
        """All 17 phrases (D56/D58) must match as standalone messages."""
        f = DangerWordFilter()
        result = await f(make_message(1, phrase))
        assert result == {"matched_word": phrase}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("скажи в укрытие быстро", "в укрытие"),
            ("немедленно укрыться в убежище", "укрыться в убежище"),
            ("слышали ракетный обстрел района", "ракетный обстрел"),
        ],
    )
    async def test_phrase_in_context_matches(self, make_message, text, expected):
        """Phrase in the middle/end of a sentence returns the exact substring."""
        f = DangerWordFilter()
        result = await f(make_message(1, text))
        assert result == {"matched_word": expected}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", SINGLE_WORDS_REMOVED)
    async def test_single_words_removed_not_matched(self, make_message, word):
        """Singles removed in Epic 23 must NOT match (D56, D58, доп. Flight/Падение)."""
        f = DangerWordFilter()
        assert await f(make_message(1, word)) is False

    @pytest.mark.asyncio
    async def test_v_bunkere_not_matched(self, make_message):
        """'в бункере' must NOT match 'в бункер' (right boundary blocks)."""
        f = DangerWordFilter()
        assert await f(make_message(1, "сидим в бункере")) is False

    @pytest.mark.asyncio
    async def test_spryatatsya_v_bunkere_matches(self, make_message):
        """'спрятаться в бункере' matches its own phrase (32.6 п.1)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "спрятаться в бункере"))
        assert result == {"matched_word": "спрятаться в бункере"}

    @pytest.mark.asyncio
    async def test_khlopok_matches(self, make_message):
        """Epic 23 (D57): new word 'хлопок'."""
        f = DangerWordFilter()
        result = await f(make_message(1, "слышен хлопок"))
        assert result == {"matched_word": "хлопок"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["хлопки", "хлопнуло", "хлопнул"])
    async def test_khlopok_forms_match(self, make_message, word):
        """Epic 23 (D57): journalist forms of 'хлопок'."""
        f = DangerWordFilter()
        result = await f(make_message(1, f"раздался {word}"))
        assert result == {"matched_word": word}

    @pytest.mark.asyncio
    async def test_khlopkovy_not_matched(self, make_message):
        """'хлопковый' must NOT match 'хлопок' (right boundary blocks)."""
        f = DangerWordFilter()
        assert await f(make_message(1, "хлопковый пояс")) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("В БУНКЕР", "В БУНКЕР"),
            ("Ракетная Атака", "Ракетная Атака"),
        ],
    )
    async def test_phrase_case_insensitive(self, make_message, text, expected):
        """IGNORECASE matches, matched_word keeps the text case."""
        f = DangerWordFilter()
        result = await f(make_message(1, text))
        assert result == {"matched_word": expected}

    @pytest.mark.asyncio
    async def test_phrase_returned_before_word(self, make_message):
        """'ракетная атака' phrase wins over single word 'ракетная' (32.5)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "ракетная атака дронов"))
        assert result == {"matched_word": "ракетная атака"}

    @pytest.mark.asyncio
    async def test_longest_phrase_returned_first(self, make_message):
        """'иди в бункер' is returned, not the overlapping 'в бункер' (32.6 п.6)."""
        f = DangerWordFilter()
        result = await f(make_message(1, "иди в бункер"))
        assert result == {"matched_word": "иди в бункер"}

    @pytest.mark.asyncio
    async def test_phrases_independent_of_custom_words(self, make_message):
        """Custom words must NOT disable the phrase branch (D55, 32.6 п.8)."""
        f = DangerWordFilter(words=["атака"])
        result = await f(make_message(1, "в бункер"))
        assert result == {"matched_word": "в бункер"}

    @pytest.mark.asyncio
    async def test_phrase_in_caption_matches(self, make_message):
        """Phrase in message.caption must match."""
        f = DangerWordFilter()
        msg = make_message(479167456, text=None)
        msg.caption = "все в укрытие"
        result = await f(msg)
        assert result == {"matched_word": "в укрытие"}


@pytest.mark.asyncio
class TestVasyaFilter:
    """Direct filter tests for VasyaFilter (complex transliteration logic)."""
    
    async def test_vasya_cyrillic(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "вася привет")) is True
    
    async def test_vasyusha(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "васюша")) is True
    
    async def test_vasiliy_latin(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "Vasiliy пришёл")) is True
    
    async def test_vasya_latin(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "Vasya here")) is True
    
    async def test_no_vasya_fails(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "привет как дела")) is False
    
    async def test_empty_text_fails(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, "")) is False
    
    async def test_none_text_fails(self, make_message):
        from filters.vasya_name import VasyaFilter
        f = VasyaFilter()
        assert await f(make_message(1, None)) is False


@pytest.mark.asyncio
class TestStrictAdminFilter:
    """Direct filter tests for StrictAdminFilter."""
    
    async def test_admin_exact(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "админ")) is True
    
    async def test_admin_with_punctuation(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "!админ?")) is True
    
    async def test_admin_in_sentence(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "где админ?")) is True
    
    async def test_administrator_not_admin(self, make_message):
        """'администратор' should NOT match because 'админ' is not a standalone word."""
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "администратор")) is False
    
    async def test_no_admin_fails(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "привет модератор")) is False
    
    async def test_empty_text_fails(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, "")) is False
    
    async def test_none_text_fails(self, make_message):
        from filters.admin_word import StrictAdminFilter
        f = StrictAdminFilter()
        assert await f(make_message(1, None)) is False
