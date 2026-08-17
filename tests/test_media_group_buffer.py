"""Tests for services/media_group_buffer.py (T-277, R36-1, Section 45.3 #1-9).

MediaGroupCaptionBuffer: OrderedDict media_group_id → {caption,
first_message_id, ts}; TTL 60с (D122), LRU 100; заполнение из
summary_observer 0a, чтение из factcheck. Прецедент механики:
handlers/dead_page_trigger.py _seen_media_groups.
"""
from unittest.mock import MagicMock

import pytest

from services import media_group_buffer as mgb_mod
from services.media_group_buffer import (
    MAX_ENTRIES,
    TTL_SECONDS,
    get_media_group_caption,
    record_media_group_message,
)


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr(mgb_mod, "time", FakeTime)
    return state


@pytest.fixture(autouse=True)
def buffer_cleanup():
    yield
    mgb_mod._buffer.clear()


def _make_msg(caption=None, text=None, media_group_id="mg1", message_id=1):
    msg = MagicMock()
    msg.caption = caption
    msg.text = text
    msg.media_group_id = media_group_id
    msg.message_id = message_id
    return msg


class TestMediaGroupBuffer:
    def test_record_first_element_with_caption(self, fake_time):
        """#1: record 1-го элемента альбома с caption → get == caption."""
        record_media_group_message(_make_msg(caption="текст новости", message_id=10))
        assert get_media_group_caption("mg1") == "текст новости"

    def test_second_element_without_caption_does_not_erase(self, fake_time):
        """#2: record 2-го элемента БЕЗ caption → caption не затёрт."""
        record_media_group_message(_make_msg(caption="текст новости", message_id=10))
        record_media_group_message(_make_msg(caption=None, message_id=11))
        assert get_media_group_caption("mg1") == "текст новости"

    def test_album_without_caption_not_stored(self, fake_time):
        """#3: альбом без caption вообще → get == None, буфер пуст."""
        record_media_group_message(_make_msg(caption=None, message_id=10))
        record_media_group_message(_make_msg(caption="   ", message_id=11))
        assert get_media_group_caption("mg1") is None
        assert len(mgb_mod._buffer) == 0

    def test_ttl_expiry_lazy_eviction(self, fake_time):
        """#4: TTL: fake-monotonic +61с → get == None, запись удалена (ленивая эвикция)."""
        record_media_group_message(_make_msg(caption="текст", message_id=10))
        fake_time["now"] += TTL_SECONDS + 1
        assert get_media_group_caption("mg1") is None
        assert "mg1" not in mgb_mod._buffer

    def test_lru_eviction_oldest(self, fake_time):
        """#5: LRU: MAX_ENTRIES+1 вставок → старейшая вытеснена, свежие живы."""
        record_media_group_message(_make_msg(caption="старейшая", media_group_id="mg-old", message_id=1))
        for i in range(1, MAX_ENTRIES + 1):
            record_media_group_message(_make_msg(caption=f"c{i}", media_group_id=f"mg-{i}", message_id=i))
        assert len(mgb_mod._buffer) == MAX_ENTRIES
        assert "mg-old" not in mgb_mod._buffer
        assert get_media_group_caption(f"mg-{MAX_ENTRIES}") == f"c{MAX_ENTRIES}"

    def test_groups_isolated(self, fake_time):
        """#6: разные media_group_id → не смешиваются."""
        record_media_group_message(_make_msg(caption="альфа", media_group_id="a", message_id=1))
        record_media_group_message(_make_msg(caption="бета", media_group_id="b", message_id=2))
        assert get_media_group_caption("a") == "альфа"
        assert get_media_group_caption("b") == "бета"

    def test_touch_refresh_extends_ttl(self, fake_time):
        """#7: touch: элементы той же группы → ts обновляется (TTL от последнего элемента)."""
        record_media_group_message(_make_msg(caption="текст", message_id=10))
        fake_time["now"] += 40.0
        record_media_group_message(_make_msg(caption=None, message_id=11))  # touch
        fake_time["now"] += 40.0  # 80с от вставки, но 40с от touch → жива
        assert get_media_group_caption("mg1") == "текст"

    def test_get_unknown_or_empty_id_returns_none(self, fake_time):
        """#8: get несуществующего/пустого id → None, без исключения."""
        assert get_media_group_caption("нет-такого") is None
        assert get_media_group_caption("") is None

    def test_record_without_media_group_id_ignored(self, fake_time):
        """#9: record без media_group_id → буфер пуст."""
        record_media_group_message(_make_msg(caption="текст", media_group_id=None))
        assert len(mgb_mod._buffer) == 0
