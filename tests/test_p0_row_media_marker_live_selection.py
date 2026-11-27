"""P0-ROW-MEDIA-MARKER-01: live selection реально рендерит медиа-строку.

Дефект 2.58.261: `DirectChatService._context_row_line` вызывал
`row_media_marker(...)`, но имя не было импортировано в
`services/direct_chat_service.py`, поэтому любая медиа-строка без подписи
(``text == ""``) в live-ветке выбора медиа давала
``NameError: row_media_marker``.  Исключение перехватывал fail-open
(``direct: live selection failed — legacy fail-open``), и ВЕСЬ ход тихо
деградировал на legacy-контекст.

Оракул — внешний контракт медиа-маркера (``services/media_marker.py``):
медиа-строка без текста в речевой проекции рендерится ``[медиа: photo M<n>]``
и НЕ пропадает; в нормальном ходе warning fail-open не появляется.
Плюс негативный контроль: настоящая ошибка live-пути по-прежнему уходит в
legacy fail-open (исправление не убирает страховку).
"""
import logging

import pytest

from services import direct_context_composer as comp
from services import hot_config
from services.canonical_context import SpeechProjection
from tests.test_direct_chat import FakeMemory, _make_service, _message
from tests.test_ur_c_3_real_fts import (
    ADDRESSEE,
    BOT_UID,
    CHAT,
    _db,
    _force_budget,
    _global_parts,
    _row,
    _stub_episodes,
    _text,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31]

FAIL_OPEN_MARK = "live selection failed"


class _Cache:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def speech_on():
    """Рубильник речевой проекции ON (живой hot-ключ), затем восстановление."""
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": True}))
    yield
    hot_config.set_config_cache(saved)


def _media_row(i, *, media="photo", tg=990):
    """Медиа-строка без подписи: так её хранит smart_messages."""
    row = _row(i, tg=tg, uid=ADDRESSEE, ts=1_700_000_000)
    row["text"] = ""
    row["media_type"] = media
    return row


async def _compose(svc, message, window, projection):
    return await svc._compose_user_content(
        chat_id=CHAT, message=message, blocks=[], chain=[], window=window,
        roster=[], suffix_map={}, global_parts=_global_parts(
            tail_rows=window),
        target_name="Аня", target_user_id=ADDRESSEE,
        trigger_message_id=message.message_id, out_excluded=None,
        projection=projection, live_selection=True)


@pytest.mark.asyncio
async def test_live_selection_renders_media_row_marker_without_fail_open(
        tmp_path, monkeypatch, caplog, speech_on):
    """Медиа-строка окна доходит до payload меткой; live-ветка не падает."""
    db = await _db(tmp_path, "rowmedia.db")
    try:
        window = [
            _row(1, text="текстовая реплика", tg=900),
            _media_row(2, tg=991),
        ]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 200_000)
        seen = {"selection": 0}
        real_selection = comp.allocate_selection

        def _selection(*args, **kwargs):
            seen["selection"] += 1
            return real_selection(*args, **kwargs)

        monkeypatch.setattr(comp, "allocate_selection", _selection)
        projection = SpeechProjection(run_id="p0-row-media")
        msg = _message(text="что на фото?", message_id=6000)
        caplog.clear()
        with caplog.at_level(logging.WARNING,
                             logger="services.direct_chat_service"):
            blocks = await _compose(svc, msg, window, projection)
        payload = _text(blocks)
        # Речевая метка выдана рендером live-ветки (после него она известна).
        label = projection.message_label("tg:991")
        assert label, payload[:2000]
        assert f"[медиа: photo {label}]" in payload, payload[:2000]
        # Live allocator исполнялся — это не legacy-сборка.
        assert seen["selection"] == 1, seen
        # Ни NameError, ни его перехвата в нормальном ходе.
        failures = [r.getMessage() for r in caplog.records
                    if FAIL_OPEN_MARK in r.getMessage()]
        assert not failures, failures
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_genuine_live_failure_still_falls_back(
        tmp_path, monkeypatch, caplog, speech_on):
    """Страховка сохранена: реальная ошибка live-пути → legacy fail-open."""
    db = await _db(tmp_path, "rowmedia_failopen.db")
    try:
        window = [
            _row(1, text="текстовая реплика", tg=900),
            _media_row(2, tg=992),
        ]
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch)
        _force_budget(monkeypatch, svc, 200_000)

        def _boom(*args, **kwargs):
            raise RuntimeError("allocator down")

        monkeypatch.setattr(comp, "allocate_selection", _boom)
        projection = SpeechProjection(run_id="p0-row-media-fb")
        msg = _message(text="что на фото?", message_id=6001)
        caplog.clear()
        with caplog.at_level(logging.WARNING,
                             logger="services.direct_chat_service"):
            blocks = await _compose(svc, msg, window, projection)
        payload = _text(blocks)
        assert any(FAIL_OPEN_MARK in r.getMessage()
                   for r in caplog.records), [
            r.getMessage() for r in caplog.records]
        # Ход не потерян: legacy-сборка отдала контекст.
        assert payload.strip(), payload[:2000]
        assert "текстовая реплика" in payload, payload[:2000]
    finally:
        await db.close()
