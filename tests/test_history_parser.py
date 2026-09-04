"""Фаза 2 (T-751, B4) — тесты потокового парсера экспортов Telegram.

normalize_message (маппинг spec §3.1) + потоковый разбор мини-фикстур
(tests/fixtures/history/) + детект export-id шапки (--only-live-chat).
"""
import json
import pytest

from tools.history_import.parser import (
    BadTimestampError,
    detect_export_id,
    iter_messages,
    normalize_message,
)

FIXTURE_DIR = "tests/fixtures/history"
CHAT_2026 = f"{FIXTURE_DIR}/chat_2026.json"
CHAT_2025 = f"{FIXTURE_DIR}/chat_2025.json"


def _msg(**over):
    base = {
        "id": -1,
        "type": "message",
        "date": "2026-01-05T12:00:00",
        "date_unixtime": "1767567600",
        "from": "Имя",
        "from_id": "user123",
        "text": "текст",
        "text_entities": [{"type": "plain", "text": "текст"}],
    }
    base.update(over)
    return base


class TestNormalizeSkips:
    def test_service_type_skipped(self):
        assert normalize_message(_msg(type="service")) is None

    def test_empty_text_without_media_skipped(self):
        assert normalize_message(_msg(text="", text_entities=[])) is None
        assert normalize_message(_msg(text=None)) is None
        assert normalize_message({**_msg(), "text": ["  ", {"type": "x"}]}) is None

    def test_not_a_dict_raises_bad_timestamp(self):
        with pytest.raises(BadTimestampError):
            normalize_message("мусор")

    def test_missing_or_broken_date_raises(self):
        raw = _msg()
        raw.pop("date_unixtime")
        with pytest.raises(BadTimestampError):
            normalize_message(raw)
        with pytest.raises(BadTimestampError):
            normalize_message(_msg(date_unixtime="курица"))
        with pytest.raises(BadTimestampError):
            normalize_message(_msg(date_unixtime=None))


class TestNormalizeFields:
    def test_plain_text_row(self):
        raw = _msg(from_id="user5885953495",
                   date_unixtime="1767567660", text="привет")
        raw["from"] = "Вася"
        m = normalize_message(raw)
        assert m["timestamp"] == 1767567660
        assert m["user_id"] == 5885953495
        assert m["author_name"] == "Вася"
        assert m["text"] == "привет"
        assert m["media_type"] == "text"
        assert m["is_forward"] == 0
        assert m["import_key"]

    def test_text_list_joined(self):
        m = normalize_message(_msg(text=[
            {"type": "plain", "text": "куски "},
            {"type": "bold", "text": "текста"},
            " хвост",
        ]))
        assert m["text"] == "куски текста хвост"

    def test_text_entities_ignored_for_join_when_str(self):
        """text строкой — как есть (text_entities не пересобираем)."""
        m = normalize_message(_msg(text="простоСтрока"))
        assert m["text"] == "простоСтрока"

    def test_media_without_caption_kept(self):
        m = normalize_message(_msg(text="", text_entities=[],
                                   media_type="animation",
                                   file="(File not included.)"))
        assert m is not None
        assert m["text"] is None
        assert m["media_type"] == "animation"

    def test_photo_field_detected_when_no_media_type(self):
        m = normalize_message(_msg(photo="(File not included.)",
                                   text="", text_entities=[]))
        assert m["media_type"] == "photo"

    def test_channel_from_id_user_none(self):
        raw = _msg(from_id="channel123")
        raw["from"] = "Канал"
        m = normalize_message(raw)
        assert m["user_id"] is None
        assert m["author_name"] == "Канал"
        assert m["media_type"] == "text"

    def test_author_missing_empty(self):
        raw = _msg()
        raw["from"] = None
        m = normalize_message(raw)
        assert m["author_name"] == ""

    def test_forwarded_from_maps(self):
        m = normalize_message(_msg(forwarded_from="Канал X", text="репост"))
        assert m["is_forward"] == 1
        assert m["forward_source"] == "Канал X"
        # forward_from (иной ключ) тоже
        m2 = normalize_message(_msg(forward_from="@канал", text="р"))
        assert m2["is_forward"] == 1
        assert m2["forward_source"] == "@канал"

    def test_forwarded_empty_source_no_flag(self):
        m = normalize_message(_msg(forwarded_from="", text="р"))
        assert m["is_forward"] == 0

    def test_reply_to_id_mapped(self):
        m = normalize_message(_msg(reply_to_message_id=-101, text="ответ"))
        assert m["reply_to_id"] == -101

    def test_timestamp_int_float_ok(self):
        assert normalize_message(_msg(date_unixtime=1767567660))["timestamp"] == \
            1767567660
        assert normalize_message(_msg(date_unixtime=1767567660.0))["timestamp"] == \
            1767567660


class TestImportKey:
    def test_stable_and_distinguishes_text(self):
        a = normalize_message(_msg(date_unixtime="1767567600", from_id="user1",
                                   text="один"))
        b = normalize_message(_msg(date_unixtime="1767567600", from_id="user1",
                                   text="один"))
        c = normalize_message(_msg(date_unixtime="1767567600", from_id="user1",
                                   text="два"))
        d = normalize_message(_msg(date_unixtime="1767567601", from_id="user1",
                                   text="один"))
        assert a["import_key"] == b["import_key"]
        assert len(a["import_key"]) == 32
        assert a["import_key"] != c["import_key"]
        assert a["import_key"] != d["import_key"]
        assert all(ch in "0123456789abcdef" for ch in a["import_key"])

    def test_media_only_rows_same_second_distinct(self):
        """ОТКЛОНЕНИЕ от базовой формулы: медиа без подписи в одну секунду у
        одного юзера не схлопываются (в ключ входит export id)."""
        a = normalize_message(_msg(id=-5, date_unixtime="1767567600",
                                   text="", text_entities=[],
                                   media_type="animation",
                                   file="(File not included.)"))
        b = normalize_message(_msg(id=-6, date_unixtime="1767567600",
                                   text="", text_entities=[],
                                   media_type="animation",
                                   file="(File not included.)"))
        assert a["import_key"] != b["import_key"]


class TestStreamingParse:
    def test_iter_messages_and_stats(self):
        messages = list(iter_messages(CHAT_2026))
        assert len(messages) == 7             # 1 service + 1 пустое + 5 принятых
        normalized = []
        errors = 0
        for raw in messages:
            try:
                m = normalize_message(raw)
            except BadTimestampError:
                errors += 1
                continue
            if m is not None:
                normalized.append(m)
        assert errors == 0
        assert len(normalized) == 5
        assert [m["user_id"] for m in normalized] == [111, 111, None, 111, 222]
        assert normalized[-1]["is_forward"] == 1
        assert normalized[-1]["reply_to_id"] == -101
        # media-only: text None, media_type animation
        media = [m for m in normalized if m["media_type"] != "text"]
        assert len(media) == 2                # animation + photo(caption)
        assert media[0]["text"] is None
        assert media[0]["media_type"] == "animation"
        assert media[1]["text"] == "вот фото"

    def test_detect_export_id(self):
        assert detect_export_id(CHAT_2026) == 2661910336
        assert detect_export_id(CHAT_2025) == 2661910336

    def test_detect_export_id_missing(self, tmp_path):
        path = tmp_path / "no_id.json"
        path.write_text(json.dumps({"name": "x", "messages": []}),
                        encoding="utf-8")
        assert detect_export_id(str(path)) is None
