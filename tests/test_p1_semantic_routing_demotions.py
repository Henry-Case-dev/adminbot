"""P1 semantic-routing (owner corrective 2026-11-10, §6 + сценарий D).

Адресная ревизия соседних конфликтов семантической маршрутизации: слова в
тексте не должны переопределять модельное понимание задачи (§7). Здесь —
негатив (фраза больше не форсирует действие) и позитив (легитимный путь
жив: явная команда, реальный запрос).

TEST-LIFECYCLE: CONTRACT owner=smart-module-semantic-routing/P1
"""
import pytest

from services import direct_execution as de
from services import direct_l1 as l1
from services import media_readiness as mr


# ═══ 1. Прямые ответы / исполнитель ═════════════════════════════════════════

def _plan(**kwargs):
    return l1.L1Plan(**kwargs)


class TestExecutorDoesNotSearchByWords:
    """P1: `derive_simple_steps` — шаги только из плана L1/required_caps."""

    def test_words_do_not_add_web_search_step(self):
        """Негатив: обычная фраза с search-стемом не порождает поиск."""
        steps, limitations = de.derive_simple_steps(
            _plan(capabilities_needed=()),
            query="как найти мотивацию, я вчера в интернете видел пост",
            announced={"execute_web_search", "fetch_article"})
        assert steps == []
        assert limitations == []

    def test_plan_capability_still_derives_search_step(self):
        """Позитив: план L1 с web_search по-прежнему исполняется."""
        steps, _ = de.derive_simple_steps(
            _plan(capabilities_needed=("web_search",)),
            query="что нового в мире",
            announced={"execute_web_search"})
        assert [s["tool"] for s in steps] == ["execute_web_search"]

    def test_required_caps_still_derive_search_step(self):
        """Позитив: требование evidence-политики (required_caps) работает."""
        steps, _ = de.derive_simple_steps(
            _plan(capabilities_needed=()),
            query="сколько стоит биткоин",
            announced={"execute_web_search"},
            required_caps=("web_search",))
        assert [s["tool"] for s in steps] == ["execute_web_search"]

    def test_words_do_not_add_step_on_planner_outage(self):
        """P1 §8-E: при сбое L1 обычные слова не инициируют инструмент."""
        query = "искал в интернете курс биткоина, но так и не нашёл"
        caps = l1.infer_fallback_capabilities(
            query, "", announced={"execute_web_search"})
        assert caps == ()
        steps, _ = de.derive_simple_steps(
            _plan(capabilities_needed=caps), query=query,
            announced={"execute_web_search"})
        assert steps == []

    def test_explicit_search_command_survives_planner_outage(self):
        """Позитив: явная поисковая команда — не стем, её путь сохраняется."""
        caps = l1.infer_fallback_capabilities(
            "Бот, найди информацию о X", "",
            announced={"execute_web_search"})
        assert caps == ("web_search",)
        steps, _ = de.derive_simple_steps(
            _plan(capabilities_needed=caps), query="Бот, найди информацию о X",
            announced={"execute_web_search"})
        assert [s["tool"] for s in steps] == ["execute_web_search"]

    def test_explicit_link_still_derives_fetch_on_outage(self):
        """Позитив: структурный сигнал (явная ссылка) сохраняется."""
        caps = l1.infer_fallback_capabilities(
            "что тут https://example.com/a", "",
            announced={"fetch_article"})
        assert caps == ("fetch_url",)


# ═══ 3. Поиск и фактчек ═════════════════════════════════════════════════════

class TestExplicitSearchRequest:
    """Поручением искать считается только явная команда реестра."""

    @staticmethod
    def _request(query, reply_text=""):
        from services import direct_chat_service as dcs
        return dcs._evidence_explicit_request(query, reply_text)

    def test_words_do_not_force_search(self):
        """Негатив: упоминание интернета/поиска — не поручение."""
        for text in ("я вчера в интернете видел мем",
                     "Как найти информацию о X?",
                     "в сети пишут, что будет дождь"):
            assert self._request(text).search is False, text

    def test_explicit_search_command_forces_search(self):
        """Позитив: «Бот, найди X» — команда, поручение сохраняется."""
        assert self._request("Бот, найди информацию о X").search is True
        assert self._request("бот, поищи курс биткоина").search is True

    def test_explicit_factcheck_form_still_forces_verify(self):
        """Позитив: явная форма «проверь факт»/«фактчек» работает."""
        assert self._request(
            "Бот, проверь факт: вода кипит при 100").verify is True
        assert self._request("фактчек: двачеры спят днём").verify is True

    def test_plain_statement_is_not_verify(self):
        """Негатив: утверждение без формы запроса не вызывает проверку."""
        assert self._request("спасибо, всё правда, как ты и сказал").verify \
            is False


# ═══ 4. Vision ══════════════════════════════════════════════════════════════

class TestVisionDependencyIsStructural:
    """P1: слова о картинке не делают ход медиа-зависимым без связи с медиа."""

    @pytest.mark.parametrize("text", [
        "что на картинке?", "прочитай скрин", "разбери фото",
        "что тут написано", "распознай",
    ])
    def test_words_alone_do_not_make_turn_media_dependent(self, text):
        """Негатив: нет вложения/reply/ссылки → разбор не запускается."""
        assert mr.is_media_dependent(query=text, own_media=False,
                                     reply_media=False) is False

    def test_own_media_is_dependency(self):
        """Позитив: вложение в самом сообщении — зависимость."""
        assert mr.is_media_dependent(query="смотри", own_media=True,
                                     reply_media=False) is True

    def test_reply_to_image_with_request_is_dependency(self):
        """Позитив: reply на изображение + просьба разобрать."""
        assert mr.is_media_dependent(query="опиши картинку", own_media=False,
                                     reply_media=True) is True

    def test_reply_to_image_without_text_is_dependency(self):
        assert mr.is_media_dependent(query="", own_media=False,
                                     reply_media=True) is True

    def test_explicit_tg_reference_is_dependency(self):
        """Позитив: явный `tg:`-ref реестра (резолв через Telegram id)."""
        assert mr.is_media_dependent(query="что тут", own_media=False,
                                     reply_media=False,
                                     explicit_ref=True) is True

    def test_quote_fragment_is_dependency(self):
        assert mr.is_media_dependent(query="что тут", own_media=False,
                                     reply_media=False,
                                     quote_text="цитата") is True

    def test_plain_chat_next_to_foreign_photo_not_dependent(self):
        assert mr.is_media_dependent(query="как вообще дела?",
                                     own_media=False,
                                     reply_media=False) is False


# ═══ 2. Ностальгия ══════════════════════════════════════════════════════════

class TestNostalgiaPreGateRemoved:
    def test_lexical_pre_gate_is_gone(self):
        """P1: принудительного лексического dig-пре-гейта больше нет."""
        from services import direct_chat_service as dcs
        assert not hasattr(dcs.DirectChatService, "_dig_pre_gate_block")
        assert not hasattr(dcs, "_nostalgia_markers")
        assert not hasattr(dcs, "_NOSTALGIA_MARKERS_RE")

    def test_dig_tool_and_capability_preserved(self):
        """Позитив: `dig_into_lore` остаётся инструментом/капабилити."""
        from services import direct_capabilities as caps
        assert "dig_into_lore" in caps.CAPABILITY_TOOLS["historical_search"]
        assert caps.CAPABILITY_TOOLS["historical_search"] == (
            "dig_into_lore", "compile_lore_story")
