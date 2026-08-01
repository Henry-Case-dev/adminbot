import pytest
from unittest.mock import MagicMock

from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.danger_word import DangerWordFilter


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
        f = DangerWordFilter()
        assert await f(make_message(1, "иди в бункер"))

    @pytest.mark.asyncio
    async def test_vspyshka_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "вспышка справа"))

    @pytest.mark.asyncio
    async def test_prilet_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "прилет в соседний дом"))

    @pytest.mark.asyncio
    async def test_ukrytie_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "бегом в укрытие"))

    @pytest.mark.asyncio
    async def test_letit_matches(self, make_message):
        f = DangerWordFilter()
        assert await f(make_message(1, "летит птица"))

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
            ("летает самолет", True),
            ("прилетел поезд", True),
            ("летят гуси", True),
            ("дронов много", True),
            ("беспилотник замечен", True),
            ("два бункера", True),
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
        """New keyword: убежище"""
        f = DangerWordFilter()
        assert await f(make_message(1, "пройдите в убежище"))

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
        """New keyword: атака"""
        f = DangerWordFilter()
        assert await f(make_message(1, "атака беспилотников"))

    @pytest.mark.asyncio
    async def test_obstrel_matches(self, make_message):
        """New keyword: обстрел"""
        f = DangerWordFilter()
        assert await f(make_message(1, "обстрел города"))

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
    async def test_upal_matches(self, make_message):
        """New keyword: упал"""
        f = DangerWordFilter()
        assert await f(make_message(1, "упал беспилотник"))

    @pytest.mark.asyncio
    async def test_sbit_matches(self, make_message):
        """New keyword: сбит"""
        f = DangerWordFilter()
        assert await f(make_message(1, "сбит дрон"))

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
