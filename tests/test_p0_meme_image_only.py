"""P0 MEME-IMAGE-ONLY — успешная генерация мема/картинки = РОВНО ОДНО
исходящее сообщение, само изображение.

Контракт владельца (02.11.2026): после сгенерированного мема бот не присылает
второе сообщение — ни промпт («Создай мем с шрифтом импакт: …»), ни описание
сгенерированного, ни список панелей, ни служебную ремарку. Промпт и служебный
текст остаются внутренними (логи/аналитика/журнал попытки). Отказ генерации
даёт ровно один короткий текст ошибки и НИ ОДНОЙ картинки.

Каждая проверка использует фейковый бот, который записывает КАЖДЫЙ исходящий
вызов (`send_photo`/`send_message`): счёт вызовов — наблюдаемый контракт, а не
внутренний флаг.

TEST-LIFECYCLE: CONTRACT owner=2026-11-02-meme-image-only-fix
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import image_generation
from services import initiative_observer as io
from services import meme_initiative as meme

PREFIX = meme.MEME_IMAGE_PROMPT
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}


class _RecordingBot:
    """Фейковый бот: пишет КАЖДЫЙ исходящий вызов в порядке отправки."""

    def __init__(self) -> None:
        self.id = 4242
        self.calls: list[tuple] = []

    async def send_photo(self, chat_id, photo, **kwargs):
        self.calls.append(("photo", int(chat_id), photo, dict(kwargs)))
        return SimpleNamespace(message_id=100 + len(self.calls))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("text", int(chat_id), str(text), dict(kwargs)))
        return SimpleNamespace(message_id=200 + len(self.calls))

    # ── наблюдение ────────────────────────────────────────────────────────
    def kinds(self) -> list[str]:
        return [call[0] for call in self.calls]

    def photos(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "photo"]

    def texts(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "text"]


class _Provider:
    def __init__(self, *, ok=True, called=True, reason="") -> None:
        self.ok = ok
        self.called = called
        self.reason = reason
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=self.called,
                               reason=self.reason, content=b"png")


class _Hit:
    def __init__(self, value=0.0) -> None:
        self.value = value

    async def draw_probability(self, **kwargs):
        from services import mca_random_source as mrs
        return mrs.DrawResult(value=self.value, deferred=False,
                              fallback_reason=None, source="pseudorandom",
                              selected_source="quantum", draw_id="draw-1")


@pytest.fixture(autouse=True)
def _reset_meme_ring():
    meme.reset_process_attempts()
    yield
    meme.reset_process_attempts()


def _ledger(tmp_path):
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme_p0.db"))
    led.apply_schema()
    return led


def _settings() -> meme.MemeSettings:
    return meme.MemeSettings(enabled=True, window_messages=8, daily_limit=3,
                             cooldown_seconds=0, min_messages=1,
                             trigger_probability=1.0)


def _rows(chat_id: int, n: int = 3) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


async def _initiative_pass(*, bot, sender, provider, ledger, chat_id=-100):
    async def gate(_chat_id):
        return True, "ok"

    async def summarizer(_cid, _rows_arg, _target, _system):
        return "хук"

    return await meme.consider_chat(
        None, chat_id, settings=_settings(), ledger=ledger, now=NOW,
        tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True, image_status=IMAGE_OK,
        random_source=_Hit(), messages=_rows(chat_id),
        summarizer=summarizer, image_provider=provider,
        publish_gate=gate, sender=sender, model_chars=200)


def _build_observer(bot):
    """Наблюдатель без БД: нужен ровно РЕАЛЬНЫЙ binding доставки мема."""
    return io.InitiativeObserverRunner(None, bot=bot)


# ═══ (a) инициативный мем: успех = только картинка ═════════════════════════

@pytest.mark.asyncio
async def test_a_initiative_success_sends_only_the_image(tmp_path):
    """(a) Инициатива + успешная генерация: ровно ОДИН исходящий вызов —
    фото; ни одного текстового вызова после него; caption (подпись под фото,
    та же утечка служебного текста) не передаётся."""
    bot = _RecordingBot()
    ledger = _ledger(tmp_path)
    provider = _Provider(ok=True)
    sender = _build_observer(bot)._meme_sender()

    result = await _initiative_pass(bot=bot, sender=sender,
                                    provider=provider, ledger=ledger)

    assert result.published is True and result.reason == "sent"
    assert len(provider.calls) == 1          # платный вызов состоялся один
    assert len(bot.calls) == 1, bot.calls    # НИ ОДНОГО второго сообщения
    kind, chat_id, _payload, kwargs = bot.calls[0]
    assert kind == "photo" and chat_id == -100
    assert bot.texts() == []                 # текстового сообщения нет вовсе
    assert "caption" not in kwargs, kwargs   # подпись (промпт) не отправляется
    # Промпт остаётся внутренним: его нет ни в одном исходящем payload.
    assert PREFIX not in str(bot.calls)


@pytest.mark.asyncio
async def test_a2_initiative_prompt_never_reaches_chat(tmp_path, caplog):
    """(a2) Успешный мем: полный текст промпта (включая подпись «импакт»)
    отсутствует во всех исходящих вызовах, хотя провайдеру он уходил."""
    bot = _RecordingBot()
    ledger = _ledger(tmp_path)
    provider = _Provider(ok=True)
    sender = _build_observer(bot)._meme_sender()

    await _initiative_pass(bot=bot, sender=sender, provider=provider,
                           ledger=ledger)

    sent_prompt = provider.calls[0][0]
    assert sent_prompt.startswith(PREFIX)     # провайдер получил промпт
    assert sent_prompt not in str(bot.calls)  # а в чат он не попал
    assert len(bot.calls) == 1


@pytest.mark.asyncio
async def test_c_initiative_failure_sends_no_image(tmp_path):
    """(c-инициатива) Провайдер отказал → ни картинки, ни текста (у
    инициативы нет адресата-запроса: молчание честнее выдуманного сообщения)."""
    bot = _RecordingBot()
    ledger = _ledger(tmp_path)
    provider = _Provider(ok=False, reason="provider_error")
    sender = _build_observer(bot)._meme_sender()

    result = await _initiative_pass(bot=bot, sender=sender,
                                    provider=provider, ledger=ledger)

    assert result.published is False
    assert bot.photos() == []
    assert bot.texts() == []


# ═══ (d) аналитика/журнал успешной генерации — без изменений ═══════════════

@pytest.mark.asyncio
async def test_d_success_analytics_and_journal_unchanged(tmp_path):
    """(d) Успешная генерация по-прежнему журналируется теми же полями:
    стадии summary/image_generation/publish + outcome published, слот
    provider_called, счётчик квоты spent=1, метаданные результата."""
    bot = _RecordingBot()
    ledger = _ledger(tmp_path)
    provider = _Provider(ok=True)
    sender = _build_observer(bot)._meme_sender()

    result = await _initiative_pass(bot=bot, sender=sender,
                                    provider=provider, ledger=ledger)

    rows = ledger.attempts(-100)
    stages = {str(row.get("stage") or "") for row in rows}
    outcomes = {str(row.get("outcome") or "") for row in rows}
    assert {"summary", "image_generation", "publish"} <= stages
    assert "published" in outcomes
    assert not [row for row in rows if row.get("outcome") == "failed"]

    reservation = _reservation_status(ledger, -100)
    assert reservation == ["provider_called"]
    day = meme.day_window(-100, NOW, tz_name="UTC")
    quota = meme.quota_view(ledger, chat_id=-100, day=day, limit=3)
    assert quota["spent"] == 1
    assert ledger.last_provider_ts(-100) >= int(NOW.timestamp())

    payload = result.as_dict()
    assert payload["generated"] is True
    assert payload["published"] is True
    assert payload["outcome"] == "published"
    assert payload["reason"] == "sent"
    assert payload["prompt_origin"] in {"factory", "custom"}
    assert payload["output_kind"] == meme.OUTPUT_KIND
    assert payload["blocks_text_initiative"] is False
    assert payload["limit"] and payload["limit"]["value"] > 0
    assert payload["limit"]["known"] is True
    assert result.prompt.startswith(PREFIX)   # промпт записан внутри результата
    assert result.counters.get(meme.STAGE_PUBLISH) == 1


def _reservation_status(ledger, chat_id):
    import sqlite3
    conn = sqlite3.connect(ledger.path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            f"SELECT status FROM {meme.RESERVATION_TABLE} WHERE chat_id = ?",
            (chat_id,))
        return [str(row["status"]) for row in cur.fetchall()]
    finally:
        conn.close()


# ═══ (e) прочие типы инициативы: текст отправляется как раньше ═════════════

@pytest.mark.asyncio
async def test_e_text_initiative_still_sends_its_text(tmp_path, monkeypatch):
    """(e) Текстовая инициатива (не мем) по-прежнему отправляет свой текст
    через существующий путь `telegram_send.send_text`."""
    from services import direct_chat_service as dcs
    from services import mca_exploration as expl
    from tests.test_asap8_f6_initiative import (
        CHAT, _FakeBot, _FakeWriter, _candidate, _db, _make_intent,
        _situation)

    async def _off(_db, _purpose, _chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)
    sent: list[tuple] = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return SimpleNamespace(message_id=7001)

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    db = await _db(tmp_path, "p0_text_initiative.db")
    intent_id, _created = await _make_intent(db)
    result = await dcs.handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db,
        writer_service=_FakeWriter(text="Ну что, продолжим?"))

    assert result["status"] == "sent"
    assert len(sent) == 1
    assert sent[0] == (CHAT, "Ну что, продолжим?")


# ═══ (b) явный запрос пользователя: успех = только картинка ════════════════

def _patch_image_env(monkeypatch):
    """Общие предпосылки генерации: модуль ON + ключ/модель в hot-слое."""
    from services import hot_config as _hot

    class _Cfg:
        def get(self, key, default=None):
            return {"keys.image_api_key": "test-key",
                    "models.image_model": "test-model"}.get(key, default)

    _hot.set_config_cache(_Cfg())
    monkeypatch.setattr("services.image_generation.resolve_module_enabled",
                        AsyncMock(return_value=True))
    # Legacy-ветка пре-гейта (без ImageRequest) — прямой вызов генерации.
    monkeypatch.setattr(
        "services.image_generation.unified_image_request_enabled",
        lambda: False)
    return _hot


def _fake_generator(bot, *, ok=True, reason="ok"):
    """Подменяет ТОЛЬКО провайдера генерации: отправку делает РЕАЛЬНЫЙ
    `telegram_send.send_photo` (тот же путь, что в продакшене)."""
    async def _generate(prompt, _bot, chat_id, *args, **kwargs):
        if ok:
            from services import telegram_send
            await telegram_send.send_photo(bot, chat_id, b"png-bytes")
        return image_generation.GenerationResult(
            ok=ok, reason=reason,
            content=b"png-bytes" if ok else None, filename="meme.png")

    return _generate


@pytest.mark.asyncio
async def test_b_explicit_request_success_sends_only_the_image(monkeypatch):
    """(b) Явный запрос «Бот, нарисуй мем …»: ровно ОДИН исходящий вызов —
    фото; ни одного текстового сообщения после него, ни подписи под фото."""
    from tests.test_direct_chat import _bot, _make_service, _message, _user

    hot = _patch_image_env(monkeypatch)
    bot = _bot()
    bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=501))
    calls: list[str] = []

    async def _send_photo(*args, **kwargs):
        calls.append("photo")
        return SimpleNamespace(message_id=501)

    async def _send_message(*args, **kwargs):
        calls.append("text")
        return SimpleNamespace(message_id=502)

    bot.send_photo = AsyncMock(side_effect=_send_photo)
    bot.send_message = AsyncMock(side_effect=_send_message)
    monkeypatch.setattr(
        "services.image_generation.generate_and_send",
        _fake_generator(bot))
    service = _make_service(tool_router=MagicMock())
    user = _user()
    try:
        await service.handle(
            bot, _message(text="Бот, нарисуй мем про дедлайн",
                          message_id=21, user=user), user)
    finally:
        hot.set_config_cache(None)

    assert calls == ["photo"], calls          # одно сообщение — картинка
    photo_kwargs = bot.send_photo.await_args.kwargs
    assert "caption" not in photo_kwargs, photo_kwargs
    assert PREFIX not in str(photo_kwargs)


@pytest.mark.asyncio
async def test_c_explicit_request_failure_sends_no_image_one_short_text(
        monkeypatch):
    """(c) Отказ генерации: НИ ОДНОЙ картинки и ровно одно короткое
    текстовое сообщение (ошибка не прячется и не дублируется)."""
    from tests.test_direct_chat import (
        FakeLLM, _bot, _make_service, _message, _user)

    hot = _patch_image_env(monkeypatch)
    bot = _bot()
    calls: list[str] = []

    async def _send_photo(*args, **kwargs):
        calls.append("photo")
        return SimpleNamespace(message_id=501)

    async def _send_message(*args, **kwargs):
        calls.append("text")
        return SimpleNamespace(message_id=502)

    bot.send_photo = AsyncMock(side_effect=_send_photo)
    bot.send_message = AsyncMock(side_effect=_send_message)
    monkeypatch.setattr(
        "services.image_generation.generate_and_send",
        _fake_generator(bot, ok=False, reason="provider_error"))
    service = _make_service(llm=FakeLLM(text="Не получилось с картинкой"),
                            tool_router=MagicMock())
    user = _user()
    try:
        await service.handle(
            bot, _message(text="Бот, нарисуй мем про дедлайн",
                          message_id=22, user=user), user)
    finally:
        hot.set_config_cache(None)

    assert calls == ["text"], calls            # картинки нет
    assert bot.send_photo.await_count == 0
    assert bot.send_message.await_count == 1
    assert "Не получилось с картинкой" in str(
        bot.send_message.await_args.args)


@pytest.mark.asyncio
async def test_e2_plain_text_turn_still_answers_with_text(monkeypatch):
    """(e2) Обычный текстовый ход (без изображения) отвечает текстом как
    раньше: подавление привязано к ДОСТАВЛЕННОЙ картинке, а не к чату."""
    from tests.test_direct_chat import (
        FakeLLM, _bot, _make_service, _message, _user)

    bot = _bot()
    bot.send_photo = AsyncMock()
    service = _make_service(llm=FakeLLM(text="Нормальный ответ"),
                            tool_router=MagicMock())
    user = _user()
    await service.handle(bot, _message(text="как дела?", message_id=23,
                                       user=user), user)

    assert bot.send_photo.await_count == 0
    assert bot.send_message.await_count >= 1
    assert "Нормальный ответ" in str(bot.send_message.await_args.args)
