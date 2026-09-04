"""Tests for services/smartmodule_phrases.py (T-257-D, R33-5, D108; Epic 37 R37-5).

Пулы 5.1–5.7 ДОСЛОВНО из ТЗ (каноны пользователя — не переписывать):
принадлежность пулу, ровно по 5 фраз, плейсхолдер {remaining_time} в 5.1,
все фразы строчными, без эмодзи. Epic 37: пулы 5.6/5.7 добавлены В КОНЕЦ,
старые каноны 5.1–5.5 без правок; пул «Ошибка LLM» Epic 37 == существующий 5.5
(переиспользование, дублирование запрещено).
"""
import pytest

from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHAT_LLM_DOWN_PHRASES,
    CHAT_LOCK_BUSY_PHRASES,
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    INFO_BAD_MARKUP_PHRASES,
    INFO_EDIT_OK_PHRASES,
    INFO_NO_DELETE_RIGHTS_PHRASES,
    INFO_NOT_ADMIN_PHRASES,
    LLM_ERROR_PHRASES,
    SEARCH_EMPTY_QUERY_PHRASES,
    SEARCH_ERROR_PHRASES,
    THROTTLE_PHRASES,
    WEB_ERROR_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,
    VIDEO_MEDIA_EMPTY_PHRASES,
    VIDEO_MEDIA_TOO_BIG_PHRASES,
    VIDEO_MEDIA_TOO_LONG_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
)

# Каноны R33-5 (backlog, дословно)
EXPECTED_5_1 = (
    "отъебись от меня, подожди {remaining_time}",
    "че доебался, жди {remaining_time}",
    "иди потрогай траву {remaining_time}, потом пиши",
    "куда ты так спешишь, шиз, посиди молча {remaining_time}",
    "дай от тебя отдохнуть, таймер еще {remaining_time}",
)
EXPECTED_5_2 = (
    "и че тебе найти, мысли твои прочитать?",
    "запрос забыл высрать, гений",
    "ты мне пустоту предлагаешь гуглить, шиз?",
    "пальцы отсохли запрос дописать?",
    "воздух нашел, держи в курсе",
)
EXPECTED_5_3 = (
    "и че тут проверять, пустоту?",
    "в этом высере даже текста нет для фактчека",
    "я стикеры и войсы на пруфы не проверяю, дай текст",
    "фактчек воздуха прошел успешно: это пиздеж",
    "тут букв нет, шиз, на что мне отвечать?",
)
EXPECTED_5_4_SEARCH = (
    "интернет сдох, ищи сам",
    "поисковики легли, пиздуй в библиотеку",
    "сеть отвалилась, гугли своими культяпками",
    "провайдер сдох от твоих запросов, ничего не нашел",
    "интернет кончился, больше инфы нет",
)
EXPECTED_5_4_FACTCHECK = (
    "интернет сдох, фактчека не будет",
    "поисковики легли, проверяй свои вбросы сам",
    "пруфов в сети не нашлось, все базы упали",
    "сеть легла, считай что тебе все наврали",
    "не могу достучаться до пруфов, интернет откис",
)
EXPECTED_5_5 = (
    "база подавилась",
    "нейронка срыгнула от этого бреда",
    "мозги закипели это переваривать, попробуй позже",
    "токенов на твою хуйню не хватило, сервер сдох",
    "llm откинулась, сгенерировать не вышло",
)

# Каноны R37-5 (Epic 37, Section 46.6, дословно)
EXPECTED_5_6 = (
    "в этом высере нет субтитров, сиди и слушай ушами",
    "автор видоса зажал субтитры, пересказывать нечего",
    "видео сдохло или закрыто приватностью, иди нахуй",
    "не могу выдрать текст из этого ролика, ютуб послал меня",
    "там либо музыки навалили, либо автор немой, текста нет",
)
EXPECTED_5_7 = (
    "сайт сдох или закрылся пейволлом, читать нечего",
    "страница пустая как твоя голова, инфы ноль",
    "не могу открыть эту помойку, сервак лег",
    "сайт заблокировал парсер, читай своими глазами",
    "там три строчки рекламы и больше ничего, пересказывать нечего",
)

# Канон R41-2 (Epic 41, Section 50.7, дословно)
EXPECTED_5_8 = (
    "ютуб опять тупит, пробую выдрать текст еще раз",
    "не отвалился я, это ютуб упирается, щас повторим",
    "попытка в молоко, кручу еще раз, не ной",
    "субтитры не отдают, долблюсь в них снова",
    "канал сопротивляется, повторяю, отстань на секунду",
)

# Каноны R42-3/R42-4/R42-5 (Epic 42, Section 51.5, дословно)
EXPECTED_CHECKUP_FALLBACK = (
    "беттерстак обосрался, лезу ковырять локальные логи...",
    "облачный мониторинг сдох, ща буду читать локальную помойку на серваке...",
    "модный беттерстак отвалился, перехожу на чтение логов с жесткого диска как дед...",
    "платная хуйня легла, парсю локальные файлы. жди...",
    "беттерстак поперхнулся, откатываюсь на чтение логов из системы...",
)
EXPECTED_CHECKUP_DEAD = (
    "беттерстак лег, а локальные логи сгорели вместе с сервером",
    "не могу достучаться до логов, админ опять все сломал",
    "мониторинг сдох, мы ослепли",
    "сервисы послали меня нахуй, разбирайся сам",
    "доступ к логам отвалился везде, диагностики не будет",
)
EXPECTED_CHECKUP_LLM_ERROR = (
    "нейронка срыгнула от этого кода",
    "мозги закипели это переваривать, попробуй позже",
    "токенов на эту помойку не хватило, сервер сдох",
    "llm откинулась, сгенерировать не вышло",
)

# Каноны R50-7/R50-8 (Epic 50, Section 58.2) — VERBATIM из backlog (эталон-слайс)
EXPECTED_CHAT_COOLDOWN = (
    "ты заебал спамить, я пошел курить на {remaining_time}",
    "лимит тупых вопросов исчерпан, отдыхай {remaining_time}",
    "дай передохнуть от твоей духоты, вернусь через {remaining_time}",
    "рот оффни на {remaining_time}, я не нанимался с тобой болтать без остановки",
)
EXPECTED_CHAT_ERROR = (
    "мои мозги расплавились от твоего бреда",
    "внутренняя ошибка базы, иди нахуй",
    "я подавился токенами, попробуй позже",
)

# Канон R53-2 (Epic 53, Section 62.2.3) — VERBATIM
EXPECTED_CHAT_LLM_DOWN = (
    "так, мой мозг сейчас на перезагрузке, дай ему пару минут прийти в себя",
    "я сейчас не в ресурсе, подожди немного и попробуй снова",
    "мозги временно ушли на профилактику, скоро вернутся",
    "перегрелся я, отдохну минут пять и снова буду умничать",
)

# Канон R60-2 (Epic 60, Section 63.4) — VERBATIM
EXPECTED_CHAT_LOCK_BUSY = (
    "я ещё думаю над прошлым вопросом, подожди пару секунд",
    "не части, предыдущую мысль додумываю",
    "моя единственная извилина занята, секунду",
)

# Каноны R43-4 (Epic 43, Section 52.5, дословно)
EXPECTED_INFO_NO_DELETE_RIGHTS = (
    "какого хуя у меня нет прав удалять сообщения? выдай админку, шиз",
    "я не могу стереть твой высер с командой, дай права",
    "сделай меня админом, я не могу убирать за тобой команды",
)
EXPECTED_INFO_NOT_ADMIN = (
    "ты кто такой, чтобы мне тексты менять? пиздуй отсюда, прав нет",
    "губу закатай, редактировать инфу может только создатель",
    "слышь, кнопка редактирования не для твоих культяпок",
)
EXPECTED_INFO_BAD_MARKUP = (
    "твой маркдаун говно, телега его не жрет. переписывай, шиз.",
    "ты теги забыл закрыть или экранировать, апишка телеги выблевала твой текст. переделывай.",
    "криворукий, разметка битая. телеграм отказался это публиковать.",
)
EXPECTED_INFO_EDIT_OK = (
    "текст перезаписан. надеюсь, ты не нахуевертил там с разметкой.",
    "сохранил твою новую справку в базу. проверяй.",
    "справка обновлена, теперь юзеры будут читать эту версию.",
)

# Канон 51.5 (R42-5) ДОСЛОВНО фиксирует эти две фразы — они буквально
# совпадают с 5.5 (LLM_ERROR_PHRASES). Канон сильнее свойства «disjoint»:
# фразы whitelist-ятся в disjoint-тесте осознанно (расхождение зафиксировано
# для @Reviewer).
_CANON_SHARED_WITH_5_5 = {
    "мозги закипели это переваривать, попробуй позже",
    "llm откинулась, сгенерировать не вышло",
}


class TestPoolsVerbatim:
    """Каждый пул — ровно 5 фраз, дословно из ТЗ R33-5/R37-5."""

    @pytest.mark.parametrize(
        "actual,expected,name",
        [
            (THROTTLE_PHRASES, EXPECTED_5_1, "5.1"),
            (SEARCH_EMPTY_QUERY_PHRASES, EXPECTED_5_2, "5.2"),
            (FACTCHECK_EMPTY_CONTEXT_PHRASES, EXPECTED_5_3, "5.3"),
            (SEARCH_ERROR_PHRASES, EXPECTED_5_4_SEARCH, "5.4 search"),
            (FACTCHECK_ERROR_PHRASES, EXPECTED_5_4_FACTCHECK, "5.4 factcheck"),
            (LLM_ERROR_PHRASES, EXPECTED_5_5, "5.5"),
            (YOUTUBE_ERROR_PHRASES, EXPECTED_5_6, "5.6"),
            (WEB_ERROR_PHRASES, EXPECTED_5_7, "5.7"),
            (YOUTUBE_RETRY_PHRASES, EXPECTED_5_8, "5.8"),
            (CHECKUP_FALLBACK_PHRASES, EXPECTED_CHECKUP_FALLBACK, "checkup fallback"),
            (CHECKUP_DEAD_PHRASES, EXPECTED_CHECKUP_DEAD, "checkup dead"),
            (CHECKUP_LLM_ERROR_PHRASES, EXPECTED_CHECKUP_LLM_ERROR, "checkup llm error"),
            (CHAT_COOLDOWN_PHRASES, EXPECTED_CHAT_COOLDOWN, "chat cooldown"),
            (CHAT_ERROR_PHRASES, EXPECTED_CHAT_ERROR, "chat error"),
            (CHAT_LLM_DOWN_PHRASES, EXPECTED_CHAT_LLM_DOWN, "chat llm down"),
            (CHAT_LOCK_BUSY_PHRASES, EXPECTED_CHAT_LOCK_BUSY, "chat lock busy"),
            (INFO_NO_DELETE_RIGHTS_PHRASES, EXPECTED_INFO_NO_DELETE_RIGHTS, "info no delete"),
            (INFO_NOT_ADMIN_PHRASES, EXPECTED_INFO_NOT_ADMIN, "info not admin"),
            (INFO_BAD_MARKUP_PHRASES, EXPECTED_INFO_BAD_MARKUP, "info bad markup"),
            (INFO_EDIT_OK_PHRASES, EXPECTED_INFO_EDIT_OK, "info edit ok"),
        ],
    )
    def test_pool_matches_canon_verbatim(self, actual, expected, name):
        assert actual == expected

    @pytest.mark.parametrize(
        "actual,expected,name",
        [
            (THROTTLE_PHRASES, EXPECTED_5_1, "5.1"),
            (SEARCH_EMPTY_QUERY_PHRASES, EXPECTED_5_2, "5.2"),
            (FACTCHECK_EMPTY_CONTEXT_PHRASES, EXPECTED_5_3, "5.3"),
            (SEARCH_ERROR_PHRASES, EXPECTED_5_4_SEARCH, "5.4 search"),
            (FACTCHECK_ERROR_PHRASES, EXPECTED_5_4_FACTCHECK, "5.4 factcheck"),
            (LLM_ERROR_PHRASES, EXPECTED_5_5, "5.5"),
            (YOUTUBE_ERROR_PHRASES, EXPECTED_5_6, "5.6"),
            (WEB_ERROR_PHRASES, EXPECTED_5_7, "5.7"),
            (YOUTUBE_RETRY_PHRASES, EXPECTED_5_8, "5.8"),
            (CHECKUP_FALLBACK_PHRASES, EXPECTED_CHECKUP_FALLBACK, "checkup fallback"),
            (CHECKUP_DEAD_PHRASES, EXPECTED_CHECKUP_DEAD, "checkup dead"),
        ],
    )
    def test_pool_has_exactly_5_phrases(self, actual, expected, name):
        assert len(actual) == 5
        assert len(set(actual)) == 5  # без дублей внутри пула

    def test_checkup_llm_error_pool_has_exactly_4_phrases(self):
        """Epic 49 (57.6, D198): чистый LLM-пул из 4 фраз («база подавилась
        логами» архивирована)."""
        assert len(CHECKUP_LLM_ERROR_PHRASES) == 4
        assert len(set(CHECKUP_LLM_ERROR_PHRASES)) == 4

    def test_chat_pool_sizes(self):
        """R50-7/R50-8: кулдаун — 4 фразы, ошибки — 3 фразы."""
        assert len(CHAT_COOLDOWN_PHRASES) == 4
        assert len(set(CHAT_COOLDOWN_PHRASES)) == 4
        assert len(CHAT_ERROR_PHRASES) == 3
        assert len(set(CHAT_ERROR_PHRASES)) == 3

    def test_chat_llm_down_pool_has_exactly_4_phrases(self):
        """R53-2 (62.2.3): CHAT_LLM_DOWN_PHRASES — 4 фразы, без дублей."""
        assert len(CHAT_LLM_DOWN_PHRASES) == 4
        assert len(set(CHAT_LLM_DOWN_PHRASES)) == 4


class TestChatLockBusyPool:
    """R60-2 (Section 63.4): CHAT_LOCK_BUSY_PHRASES — 3 фразы, строчные,
    без маркдауна/эмодзи, без плейсхолдеров; отделён от R50-7/R50-8/R53-2."""

    def test_pool_has_exactly_3_phrases_no_duplicates(self):
        assert len(CHAT_LOCK_BUSY_PHRASES) == 3
        assert len(set(CHAT_LOCK_BUSY_PHRASES)) == 3

    def test_phrases_lowercase_no_emoji_no_placeholder(self):
        for phrase in CHAT_LOCK_BUSY_PHRASES:
            assert phrase == phrase.lower()
            assert "{remaining_time}" not in phrase
            assert not any(ord(ch) > 0x2000 for ch in phrase)

    def test_pool_disjoint_from_other_direct_chat_pools(self):
        assert not set(CHAT_LOCK_BUSY_PHRASES) & set(CHAT_COOLDOWN_PHRASES)
        assert not set(CHAT_LOCK_BUSY_PHRASES) & set(CHAT_ERROR_PHRASES)
        assert not set(CHAT_LOCK_BUSY_PHRASES) & set(CHAT_LLM_DOWN_PHRASES)


class TestEpic53ChatLlmDownPool:
    """R53-2 (Section 62.2.3): CHAT_LLM_DOWN_PHRASES отделён от R50-8."""

    def test_down_pool_disjoint_from_error_and_cooldown_pools(self):
        assert not set(CHAT_LLM_DOWN_PHRASES) & set(CHAT_ERROR_PHRASES)
        assert not set(CHAT_LLM_DOWN_PHRASES) & set(CHAT_COOLDOWN_PHRASES)

    def test_down_pool_no_placeholder(self):
        for phrase in CHAT_LLM_DOWN_PHRASES:
            assert "{remaining_time}" not in phrase


class TestEpic37Pools:
    """R37-5 (Section 46.6): переиспользование 5.5, отсутствие дублей."""

    def test_llm_error_pool_reused_not_duplicated(self):
        """Пул «Ошибка LLM» из ТЗ R37-5 == существующий 5.5 (T-286-ассерт)."""
        assert LLM_ERROR_PHRASES == EXPECTED_5_5

    def test_new_pools_disjoint_from_existing(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
        )
        assert not set(YOUTUBE_ERROR_PHRASES) & existing
        assert not set(WEB_ERROR_PHRASES) & existing

    def test_new_pools_disjoint_from_each_other(self):
        assert not set(YOUTUBE_ERROR_PHRASES) & set(WEB_ERROR_PHRASES)


class TestEpic41Pool:
    """R41-2 (Section 50.7): пул 5.8 disjoint со всеми существующими."""

    def test_retry_pool_disjoint_from_5_1_to_5_7(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
        )
        assert not set(YOUTUBE_RETRY_PHRASES) & existing


class TestEpic42CheckupPools:
    """R42-3…R42-5 (Section 51.5): по 5 фраз, каноны дословно."""

    CHECKUP_POOLS = (
        CHECKUP_FALLBACK_PHRASES,
        CHECKUP_DEAD_PHRASES,
        CHECKUP_LLM_ERROR_PHRASES,
    )

    def test_checkup_pools_disjoint_from_each_other(self):
        assert not set(CHECKUP_FALLBACK_PHRASES) & set(CHECKUP_DEAD_PHRASES)
        assert not set(CHECKUP_FALLBACK_PHRASES) & set(CHECKUP_LLM_ERROR_PHRASES)
        assert not set(CHECKUP_DEAD_PHRASES) & set(CHECKUP_LLM_ERROR_PHRASES)

    def test_checkup_pools_disjoint_from_5_1_to_5_8_except_canon_overlap(self):
        """Disjoint с 5.1–5.8, КРОМЕ 2 фраз: канон 51.5 (R42-5) дословно
        повторяет их из 5.5 — канон сильнее свойства (whitelist осознанный)."""
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
        )
        for pool in self.CHECKUP_POOLS:
            assert (set(pool) & existing) <= _CANON_SHARED_WITH_5_5

    def test_llm_error_pool_differs_where_canon_differs(self):
        """Epic 49 (57.6, D198): «база подавилась логами» АРХИВИРОВАНА —
        в LLM-пуле её нет (DoD T-390)."""
        assert "база подавилась логами" not in CHECKUP_LLM_ERROR_PHRASES
        assert "база подавилась логами" not in LLM_ERROR_PHRASES


class TestEpic50ChatPools:
    """R50-7/R50-8 (Section 58.2): каноны VERBATIM, disjoint со всеми пулами."""

    def test_chat_pools_disjoint_from_each_other(self):
        assert not set(CHAT_COOLDOWN_PHRASES) & set(CHAT_ERROR_PHRASES)

    def test_chat_pools_disjoint_from_all_existing(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
            | set(CHECKUP_FALLBACK_PHRASES)
            | set(CHECKUP_DEAD_PHRASES)
            | set(CHECKUP_LLM_ERROR_PHRASES)
            | set(INFO_NO_DELETE_RIGHTS_PHRASES)
            | set(INFO_NOT_ADMIN_PHRASES)
            | set(INFO_BAD_MARKUP_PHRASES)
            | set(INFO_EDIT_OK_PHRASES)
        )
        assert not set(CHAT_COOLDOWN_PHRASES) & existing
        assert not set(CHAT_ERROR_PHRASES) & existing

    def test_chat_cooldown_pool_has_placeholder_in_every_phrase(self):
        for phrase in CHAT_COOLDOWN_PHRASES:
            assert "{remaining_time}" in phrase
            assert phrase.count("{remaining_time}") == 1

    def test_chat_error_pool_no_placeholder(self):
        for phrase in CHAT_ERROR_PHRASES:
            assert "{remaining_time}" not in phrase


class TestEpic43InfoPools:
    """R43-4 (Section 52.5): по 3 фразы, каноны дословно, disjoint со всеми."""

    INFO_POOLS = (
        INFO_NO_DELETE_RIGHTS_PHRASES,
        INFO_NOT_ADMIN_PHRASES,
        INFO_BAD_MARKUP_PHRASES,
        INFO_EDIT_OK_PHRASES,
    )

    @pytest.mark.parametrize(
        "pool,name",
        [
            (INFO_NO_DELETE_RIGHTS_PHRASES, "info no delete"),
            (INFO_NOT_ADMIN_PHRASES, "info not admin"),
            (INFO_BAD_MARKUP_PHRASES, "info bad markup"),
            (INFO_EDIT_OK_PHRASES, "info edit ok"),
        ],
    )
    def test_info_pools_have_exactly_3_phrases(self, pool, name):
        assert len(pool) == 3
        assert len(set(pool)) == 3

    def test_info_pools_disjoint_from_each_other(self):
        for i, pool in enumerate(self.INFO_POOLS):
            for other in self.INFO_POOLS[i + 1:]:
                assert not set(pool) & set(other)

    def test_info_pools_disjoint_from_5_1_to_5_8_and_checkup(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
            | set(CHECKUP_FALLBACK_PHRASES)
            | set(CHECKUP_DEAD_PHRASES)
            | set(CHECKUP_LLM_ERROR_PHRASES)
        )
        for pool in self.INFO_POOLS:
            assert not set(pool) & existing


class TestPoolStyle:
    ALL_POOLS = (
        THROTTLE_PHRASES,
        SEARCH_EMPTY_QUERY_PHRASES,
        FACTCHECK_EMPTY_CONTEXT_PHRASES,
        SEARCH_ERROR_PHRASES,
        FACTCHECK_ERROR_PHRASES,
        LLM_ERROR_PHRASES,
        YOUTUBE_ERROR_PHRASES,
        WEB_ERROR_PHRASES,
        YOUTUBE_RETRY_PHRASES,
        CHECKUP_FALLBACK_PHRASES,
        CHECKUP_DEAD_PHRASES,
        CHECKUP_LLM_ERROR_PHRASES,
        CHAT_COOLDOWN_PHRASES,
        CHAT_ERROR_PHRASES,
        CHAT_LLM_DOWN_PHRASES,
        INFO_NO_DELETE_RIGHTS_PHRASES,
        INFO_NOT_ADMIN_PHRASES,
        INFO_BAD_MARKUP_PHRASES,
        INFO_EDIT_OK_PHRASES,
    )

    def test_all_phrases_lowercase(self):
        for pool in self.ALL_POOLS:
            for phrase in pool:
                assert phrase == phrase.lower()

    def test_no_emoji(self):
        for pool in self.ALL_POOLS:
            for phrase in pool:
                assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)

    def test_throttle_pool_has_placeholder_in_every_phrase(self):
        for phrase in THROTTLE_PHRASES:
            assert "{remaining_time}" in phrase
            assert phrase.count("{remaining_time}") == 1

    def test_other_pools_have_no_placeholder(self):
        for pool in (
            SEARCH_EMPTY_QUERY_PHRASES,
            FACTCHECK_EMPTY_CONTEXT_PHRASES,
            SEARCH_ERROR_PHRASES,
            FACTCHECK_ERROR_PHRASES,
            LLM_ERROR_PHRASES,
            YOUTUBE_ERROR_PHRASES,
            WEB_ERROR_PHRASES,
            YOUTUBE_RETRY_PHRASES,
            CHECKUP_FALLBACK_PHRASES,
            CHECKUP_DEAD_PHRASES,
            CHECKUP_LLM_ERROR_PHRASES,
            CHAT_ERROR_PHRASES,
            CHAT_LLM_DOWN_PHRASES,
            INFO_NO_DELETE_RIGHTS_PHRASES,
            INFO_NOT_ADMIN_PHRASES,
            INFO_BAD_MARKUP_PHRASES,
            INFO_EDIT_OK_PHRASES,
        ):
            for phrase in pool:
                assert "{remaining_time}" not in phrase

    def test_5_4_subpools_are_disjoint(self):
        assert set(SEARCH_ERROR_PHRASES) != set(FACTCHECK_ERROR_PHRASES)
        assert not set(SEARCH_ERROR_PHRASES) & set(FACTCHECK_ERROR_PHRASES)


class TestPlaceholderSubstitution:
    def test_replace_leaves_no_placeholder(self):
        for phrase in THROTTLE_PHRASES:
            substituted = phrase.replace("{remaining_time}", "5 мин")
            assert "{remaining_time}" not in substituted
            assert "5 мин" in substituted


# ── Bugfix 04.09.2026 (Часть 1, 5.9–5.12): пулы нативных TG-видео ────

class TestVideoMediaPools:
    """5.9–5.12 (ФР-3/ФР-8): пулы видео-файлов — disjoint между собой и со
    всеми существующими, строчные, без эмодзи/маркдауна (стиль-канон)."""

    VIDEO_POOLS = (
        VIDEO_MEDIA_TOO_LONG_PHRASES,
        VIDEO_MEDIA_TOO_BIG_PHRASES,
        VIDEO_MEDIA_UNAVAILABLE_PHRASES,
        VIDEO_MEDIA_EMPTY_PHRASES,
    )

    def test_pool_sizes_no_duplicates(self):
        assert len(VIDEO_MEDIA_TOO_LONG_PHRASES) == 4
        assert len(set(VIDEO_MEDIA_TOO_LONG_PHRASES)) == 4
        assert len(VIDEO_MEDIA_TOO_BIG_PHRASES) == 3
        assert len(set(VIDEO_MEDIA_TOO_BIG_PHRASES)) == 3
        assert len(VIDEO_MEDIA_UNAVAILABLE_PHRASES) == 3
        assert len(set(VIDEO_MEDIA_UNAVAILABLE_PHRASES)) == 3
        assert len(VIDEO_MEDIA_EMPTY_PHRASES) == 3
        assert len(set(VIDEO_MEDIA_EMPTY_PHRASES)) == 3

    def test_pools_disjoint_from_each_other(self):
        for i, pool in enumerate(self.VIDEO_POOLS):
            for other in self.VIDEO_POOLS[i + 1:]:
                assert not set(pool) & set(other)

    def test_pools_disjoint_from_all_existing(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
            | set(CHECKUP_FALLBACK_PHRASES)
            | set(CHECKUP_DEAD_PHRASES)
            | set(CHECKUP_LLM_ERROR_PHRASES)
            | set(CHAT_COOLDOWN_PHRASES)
            | set(CHAT_ERROR_PHRASES)
            | set(CHAT_LLM_DOWN_PHRASES)
            | set(INFO_NO_DELETE_RIGHTS_PHRASES)
            | set(INFO_NOT_ADMIN_PHRASES)
            | set(INFO_BAD_MARKUP_PHRASES)
            | set(INFO_EDIT_OK_PHRASES)
        )
        for pool in self.VIDEO_POOLS:
            assert not set(pool) & existing

    def test_style_lowercase_no_emoji_no_placeholder(self):
        for pool in self.VIDEO_POOLS:
            for phrase in pool:
                assert phrase == phrase.lower()
                assert "{remaining_time}" not in phrase
                assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)
