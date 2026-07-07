import pytest
from unittest.mock import MagicMock

from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.war_word import WarWordFilter


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


class TestWarWordFilter:
    @pytest.mark.asyncio
    async def test_dron_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "летит дрон")) is True

    @pytest.mark.asyncio
    async def test_raketa_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "ракета прилетела")) is True

    @pytest.mark.asyncio
    async def test_bunker_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "иди в бункер")) is True

    @pytest.mark.asyncio
    async def test_vspyshka_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "вспышка справа")) is True

    @pytest.mark.asyncio
    async def test_prilet_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "прилет в соседний дом")) is True

    @pytest.mark.asyncio
    async def test_ukrytie_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "бегом в укрытие")) is True

    @pytest.mark.asyncio
    async def test_letit_matches(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "летит птица")) is True

    @pytest.mark.asyncio
    async def test_no_war_word_fails(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "хорошая погода сегодня")) is False

    @pytest.mark.asyncio
    async def test_empty_text_fails(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, "")) is False

    @pytest.mark.asyncio
    async def test_none_text_fails(self, make_message):
        f = WarWordFilter()
        assert await f(make_message(1, None)) is False

    @pytest.mark.asyncio
    async def test_war_word_not_at_boundary(self, make_message):
        """'беспилотники' should match 'беспилотник' pattern"""
        f = WarWordFilter()
        result = await f(make_message(1, "беспилотники"))
        assert result is True

    @pytest.mark.asyncio
    async def test_multiple_war_words_fires_once(self, make_message):
        """Filter returns True on first match (any() short-circuits)."""
        f = WarWordFilter()
        assert await f(make_message(1, "дрон летит ракета бункер")) is True

    @pytest.mark.asyncio
    async def test_synonyms_all_covered(self, make_message):
        """Test each synonym group has at least one matching word."""
        f = WarWordFilter()
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
            assert await f(make_message(1, text)) == expected


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
