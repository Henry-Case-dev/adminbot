"""MEME-MANUAL-CMD — админская команда ``/meme`` и автоудаление её сообщения.

Контракт (``plans/owner_inputs/2026-11-03-meme-pipeline-refactor-01.md`` §4 +
``plans/owner_inputs/2026-11-03-meme-command-autodelete.md``, решения
``arch/integration-decisions.md`` §4/§10):

* команда только для админа; не-админу — полная тишина (ни ответа, ни
  удаления, ни генерации);
* сообщение команды удаляется ОДНИМ вызовом СРАЗУ после RBAC и ДО пайплайна:
  порядок «delete → summary → joke → provider → photo» доказуется общим
  списком событий, а не фактом «мок вызван»;
* любой сбой удаления (нет прав / >48 ч / сеть / таймаут / уже удалено)
  переживаем: один WARNING без traceback, одна попытка, пайплайн и число
  исходящих сообщений не меняются;
* успех = только изображение, без caption и без текста после него; сбой =
  ровно одно короткое сообщение, без кодов/промпта/выжимки/прикола;
* ``manual=True`` обходит квоту 0, кулдаун, минимум сообщений, тихие часы,
  тумблеры и гейт публикации, но не обходит готовность image backend;
* ярлыки: стадия ``joke`` и четыре новых кода причины дают человеческий
  текст, а не голый код.

Все фейки (бот, суммаризатор, генератор прикола, провайдер картинки) пишут в
ОДИН общий ``events`` — иначе порядок «удаление раньше пайплайна» недоказуем.

TEST-LIFECYCLE: CONTRACT owner=2026-11-03-meme-pipeline-refactor-01/P3
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from handlers import meme_command
from services import initiative_observer as obs
from services import meme_initiative as meme

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
CHAT = -100777
ADMIN = 5885953495          # заводской settings.ADMIN_USER_ID
STRANGER = 99999
MESSAGE_ID = 777
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}
IMAGE_DOWN = {"available": False,
              "reason": meme.SKIP_IMAGE_NOT_CONFIGURED,
              "health": "missing", "configured": False,
              "module_enabled": False}


# ── фейки: один журнал событий на все вызовы ───────────────────────────────

class _Bot:
    """Telegram-клиент: пишет КАЖДЫЙ вызов в общий ``events``."""

    def __init__(self, events: list[str], *, fail_delete: BaseException | None = None,
                 delete_delay: float = 0.0) -> None:
        self.id = 4242
        self.events = events
        self.calls: list[tuple] = []
        self.delete_calls: list[tuple] = []
        self.fail_delete = fail_delete
        self.delete_delay = delete_delay

    async def delete_message(self, chat_id, message_id):
        self.events.append("delete")
        self.delete_calls.append((int(chat_id), int(message_id)))
        if self.delete_delay:
            import asyncio
            await asyncio.sleep(self.delete_delay)
        if self.fail_delete is not None:
            raise self.fail_delete
        return True

    async def send_photo(self, chat_id, photo, **kwargs):
        self.events.append("photo")
        self.calls.append(("photo", int(chat_id), photo, dict(kwargs)))
        return SimpleNamespace(message_id=100 + len(self.calls))

    async def send_message(self, chat_id, text, **kwargs):
        self.events.append("text")
        self.calls.append(("text", int(chat_id), str(text), dict(kwargs)))
        return SimpleNamespace(message_id=200 + len(self.calls))

    # ── наблюдение ────────────────────────────────────────────────────────
    def kinds(self) -> list[str]:
        return [call[0] for call in self.calls]

    def photos(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "photo"]

    def texts(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "text"]


class _Message:
    """Сообщение команды. ``delete()`` идёт через ``bot.delete_message`` —
    ровно так же, как это делает настоящий ``aiogram.types.Message``."""

    def __init__(self, bot: _Bot, *, user_id: int = ADMIN, chat_id: int = CHAT,
                 message_id: int = MESSAGE_ID, text: str = "/meme") -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id,
                                    type="supergroup" if chat_id < 0 else "private")
        self.from_user = SimpleNamespace(id=user_id)
        self.message_id = message_id
        self.text = text

    async def delete(self):
        """Как в aiogram: удаление = один сетевой вызов через бота."""
        return await self.bot.delete_message(self.chat.id, self.message_id)


def _target(bot: _Bot, *, user_id: int = ADMIN) -> _Message:
    return _Message(bot, user_id=user_id)


class _Feed:
    """Этапы A/B пайплайна: событие + запись аргументов."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.summary_calls: list[tuple] = []
        self.joke_calls: list[tuple] = []

    def summarizer(self, text: str = "выжимка"):
        async def _inner(chat_id, rows, system):
            self.events.append("summary")
            self.summary_calls.append((chat_id, rows, system))
            return text
        return _inner

    def joke(self, text: str = "прикол"):
        async def _inner(chat_id, summary, instruction):
            self.events.append("joke")
            self.joke_calls.append((chat_id, summary, instruction))
            return text
        return _inner


class _Provider:
    def __init__(self, events: list[str], *, ok: bool = True,
                 reason: str = "") -> None:
        self.events = events
        self.ok = ok
        self.reason = reason
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.events.append("provider")
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=True, reason=self.reason,
                               content=b"png" if self.ok else None)


async def _ok_gate(_chat_id):
    return True, "ok"


async def _closed_gate(_chat_id):
    return False, "recheck_demoted"


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(chat_id: int = CHAT, n: int = 3) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


def _ledger(tmp_path, name: str = "meme_cmd.db"):
    led = meme.SqliteQuotaLedger(str(tmp_path / name))
    led.apply_schema()
    return led


def _seams(events: list[str], *, ledger, provider=None, gate=_ok_gate,
           settings=None, messages=None, image_status=None,
           initiative_enabled=None) -> dict:
    """Швы ``consider_chat``: внешние границы подменены, режим — нет."""
    feed = _Feed(events)
    provider = provider if provider is not None else _Provider(events)
    seams = {
        "settings": settings if settings is not None else _settings(),
        "ledger": ledger,
        "now": NOW,
        "tz_name": "UTC",
        "tz_source": "utc_fallback",
        "messages": messages if messages is not None else _rows(),
        "summarizer": feed.summarizer(),
        "joke_generator": feed.joke(),
        "image_provider": provider,
        "publish_gate": gate,
        "model_chars": 200,
        "image_status": IMAGE_OK if image_status is None else image_status,
        "initiative_enabled": initiative_enabled or (lambda: True),
    }
    seams["feed"] = feed
    seams["provider"] = provider
    return seams


def _install(monkeypatch, bot: _Bot, seams: dict) -> None:
    """DI команды: бот + швы пайплайна (в проде швов нет)."""
    clean = {k: v for k, v in seams.items() if k not in ("feed", "provider")}
    monkeypatch.setattr(meme_command, "_db", None, raising=False)
    monkeypatch.setattr(meme_command, "_llm", None, raising=False)
    monkeypatch.setattr(meme_command, "_bot", bot, raising=False)
    monkeypatch.setattr(meme_command, "_pipeline_seams", clean, raising=False)


@pytest.fixture(autouse=True)
def _clean_module_state():
    meme.reset_process_attempts()
    yield
    meme.reset_process_attempts()
    meme_command._db = None
    meme_command._llm = None
    meme_command._bot = None
    meme_command._pipeline_seams = {}


# ═══ T1: ровно один delete и он ПЕРВЫЙ (до пайплайна) ═══════════════════════

@pytest.mark.asyncio
async def test_admin_delete_is_first_network_action_and_runs_exactly_once(
        monkeypatch, tmp_path):
    """``events == ["delete", "summary", "joke", "provider", "photo"]``.

    Мутация: перенести удаление после ``consider_chat`` (или убрать его) —
    порядок/состав событий меняется, тест падает.
    """
    events: list[str] = []
    bot = _Bot(events)
    led = _ledger(tmp_path)
    seams = _seams(events, ledger=led)
    _install(monkeypatch, bot, seams)

    await meme_command.cmd_meme(_target(bot))

    assert events == ["delete", "summary", "joke", "provider", "photo"], events
    assert bot.delete_calls == [(CHAT, MESSAGE_ID)]
    assert len(bot.delete_calls) == 1
    assert seams["provider"].calls, "провайдер картинки обязан быть вызван"


# ═══ T2: успех = ровно одно исходящее сообщение, изображение ════════════════

@pytest.mark.asyncio
async def test_admin_success_sends_exactly_one_photo_without_caption(
        monkeypatch, tmp_path):
    """Один исходящий вызов — фото, ни текста, ни caption, ни reply-цели."""
    events: list[str] = []
    bot = _Bot(events)
    _install(monkeypatch, bot, _seams(events, ledger=_ledger(tmp_path)))

    await meme_command.cmd_meme(_target(bot))

    assert bot.kinds() == ["photo"], bot.calls
    chat_id, photo_kwargs = bot.calls[0][1], bot.calls[0][3]
    assert chat_id == CHAT
    assert "caption" not in photo_kwargs
    assert bot.texts() == []
    # Прикол и промпт в чат не уходят (правило §5 ТЗ не затронуто).
    assert "прикол" not in str(bot.calls)
    assert meme.MEME_IMAGE_PROMPT not in str(bot.calls)


# ═══ T3/T5: сбой удаления не меняет исход и не повторяется ══════════════════

def _telegram_bad_request():
    from aiogram.exceptions import TelegramBadRequest
    return TelegramBadRequest(method="deleteMessage",
                              message="Bad Request: message to delete not found")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    RuntimeError("not enough rights to delete this message"),
    _telegram_bad_request(),
])
async def test_delete_failure_keeps_pipeline_and_message_count(
        monkeypatch, tmp_path, caplog, failure):
    """403/400 → пайплайн тот же, исходящих столько же, один WARNING.

    Мутация: пробросить исключение удаления наружу — пайплайн не дойдёт до
    фото и событий ``summary/joke/provider/photo`` не будет.
    """
    events: list[str] = []
    bot = _Bot(events, fail_delete=failure)
    _install(monkeypatch, bot, _seams(events, ledger=_ledger(tmp_path)))

    with caplog.at_level(logging.WARNING):
        await meme_command.cmd_meme(_target(bot))

    assert events == ["delete", "summary", "joke", "provider", "photo"], events
    assert bot.kinds() == ["photo"], bot.calls     # столько же, сколько в T2
    assert bot.delete_calls == [(CHAT, MESSAGE_ID)]  # одна попытка, без ретраев
    warnings = [rec for rec in caplog.records
                if rec.levelno == logging.WARNING
                and "command delete failed" in rec.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]
    record = warnings[0]
    assert type(failure).__name__ in record.getMessage()
    assert record.exc_info is None, "traceback в лог не пишется"


@pytest.mark.asyncio
async def test_delete_timeout_is_bounded_and_non_fatal(monkeypatch, tmp_path,
                                                       caplog):
    """Зависший ``delete()`` не отодвигает старт пайплайна (ожидание ограничено).

    Мутация: убрать ``asyncio.wait_for`` — тест ждёт медленный фейк и
    получает пайплайн позже предела (или отсутствие WARNING о таймауте).
    """
    monkeypatch.setattr(meme_command, "DELETE_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    bot = _Bot(events, delete_delay=0.5)
    _install(monkeypatch, bot, _seams(events, ledger=_ledger(tmp_path)))

    with caplog.at_level(logging.WARNING):
        await meme_command.cmd_meme(_target(bot))

    assert events == ["delete", "summary", "joke", "provider", "photo"], events
    assert bot.kinds() == ["photo"], bot.calls
    warnings = [rec.getMessage() for rec in caplog.records
                if rec.levelno == logging.WARNING
                and "command delete failed" in rec.getMessage()]
    assert warnings and "TimeoutError" in warnings[0], warnings


# ═══ T4: сбой пайплайна = одно короткое сообщение, фото нет ═════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("delete_fails", [False, True])
async def test_pipeline_failure_sends_one_short_message_no_photo(
        monkeypatch, tmp_path, delete_fails):
    """Провайдер не отдал картинку → ровно один текст, ни одного фото, и
    ничего про удаление — при успешном и при проваленном удалении."""
    events: list[str] = []
    failure = RuntimeError("no rights") if delete_fails else None
    bot = _Bot(events, fail_delete=failure)
    provider = _Provider(events, ok=False, reason="provider_error")
    _install(monkeypatch, bot,
             _seams(events, ledger=_ledger(tmp_path), provider=provider))

    await meme_command.cmd_meme(_target(bot))

    assert bot.kinds() == ["text"], bot.calls
    text = bot.calls[0][2]
    assert text == meme_command._FAILURE_TEXT["image_generation_failed"]
    assert len(text) <= 120, "сообщение об ошибке — короткое"
    # Внутренности не утекают: ни кода, ни промпта, ни текста прикола.
    assert "image_generation_failed" not in text
    assert meme.MEME_IMAGE_PROMPT not in text
    assert "прикол" not in text.casefold()
    assert "delete" not in text.casefold() and "удал" not in text.casefold()
    assert provider.calls, "провайдер вызван: пайплайн реально шёл"


# ═══ T6: не-админ — полная тишина ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_non_admin_gets_silence_without_delete_or_pipeline(
        monkeypatch, tmp_path):
    """0 delete, 0 исходящих, ни одной строки журнала (пайплайна не было).

    Мутация: убрать RBAC-гейт (или пустить по ``is_dm_owner``) — появляются
    удаление и исходящее сообщение, тест падает.
    """
    from services import roles

    async def _plain_user(_uid, _chat_id=None, cache=None):
        return SimpleNamespace(is_global_admin=False, is_local_admin=False,
                               is_dm_owner=True)   # ЛС владельца — НЕ админ

    monkeypatch.setattr(roles, "access_for", _plain_user)
    events: list[str] = []
    bot = _Bot(events)
    led = _ledger(tmp_path)
    _install(monkeypatch, bot, _seams(events, ledger=led))

    await meme_command.cmd_meme(_target(bot, user_id=STRANGER))

    assert events == [], events
    assert bot.delete_calls == []
    assert bot.calls == []
    assert led.attempts(CHAT) == [], "ручного запуска в журнале быть не должно"


@pytest.mark.asyncio
async def test_admin_gate_accepts_roles_and_owner_id(monkeypatch):
    """Гейт: global_admin / local_admin / ADMIN_USER_ID; всё остальное — нет."""
    from services import roles

    async def _ctx(uid, chat_id=None, cache=None):
        table = {1: (True, False), 2: (False, True), 3: (False, False)}
        global_admin, local_admin = table.get(uid, (False, False))
        return SimpleNamespace(is_global_admin=global_admin,
                               is_local_admin=local_admin,
                               is_dm_owner=False)

    monkeypatch.setattr(roles, "access_for", _ctx)
    assert await meme_command.is_meme_admin(ADMIN, CHAT) is True     # owner id
    assert await meme_command.is_meme_admin(1, CHAT) is True         # global
    assert await meme_command.is_meme_admin(2, CHAT) is True         # local
    assert await meme_command.is_meme_admin(3, CHAT) is False        # user
    assert await meme_command.is_meme_admin(0, CHAT) is False        # без автора


@pytest.mark.asyncio
async def test_admin_gate_fails_closed_when_access_check_raises(monkeypatch):
    """Сбой проверки доступа = отказ, а не 500 в чат и не пропуск."""
    from services import roles

    async def _boom(_uid, _chat_id=None, cache=None):
        raise RuntimeError("pg down")

    monkeypatch.setattr(roles, "access_for", _boom)
    assert await meme_command.is_meme_admin(STRANGER, CHAT) is False


# ═══ bypass-матрица: квота 0 + кулдаун + гейт закрыт → мем всё равно есть ══

@pytest.mark.asyncio
async def test_manual_run_bypasses_quota_cooldown_and_closed_gate(
        monkeypatch, tmp_path):
    """Квота 0, активный кулдаун, мало сообщений, тихие часы, выключенные
    тумблеры и закрытый publish-гейт — ручной запуск всё равно публикует.

    Мутация: убрать ``manual=True`` из ``run_manual_pipeline`` — пайплайн
    выходит на первом же гейте (тумблер/квота/кулдаун), текста ошибки и фото
    в чате не появляется нужного состава, журнал не содержит ``published``.
    """
    events: list[str] = []
    bot = _Bot(events)
    led = _ledger(tmp_path)
    sealed = led.reserve(chat_id=CHAT, day_bucket=NOW.date().isoformat(),
                         job_id="prev", limit=3, tz_name="UTC",
                         tz_source="utc_fallback",
                         now_ts=int(NOW.timestamp()) - 60)
    assert sealed.ok
    led.mark("prev", "provider_called")
    before = led.status_counts(CHAT, NOW.date().isoformat())

    def _tumbler_forbidden():
        raise AssertionError("manual=True обязан не спрашивать тумблеры")

    seams = _seams(
        events, ledger=led,
        settings=_settings(enabled=False, daily_limit=0, cooldown_seconds=3600,
                           min_messages=99, quiet_hours="00:00-23:59"),
        messages=_rows(n=1), gate=_closed_gate,
        initiative_enabled=_tumbler_forbidden)
    _install(monkeypatch, bot, seams)

    await meme_command.cmd_meme(_target(bot))

    assert bot.kinds() == ["photo"], bot.calls
    published = [row for row in led.attempts(CHAT)
                 if str(row.get("outcome")) == "published"]
    assert published, led.attempts(CHAT)
    assert meme.parse_attempt_facts(published[-1]).get("manual") is True \
        or published[-1].get("stage") == meme.STAGE_PUBLISH
    # Квота дня не потрачена: ручной запуск не создаёт бронь.
    assert led.status_counts(CHAT, NOW.date().isoformat()) == \
        {"provider_called": before["provider_called"]}


@pytest.mark.asyncio
async def test_manual_run_does_not_bypass_image_backend_availability(
        monkeypatch, tmp_path):
    """Нет рабочего image backend → честное короткое сообщение, фото нет.

    Мутация: обойти проверку ``image_dependency`` в ручном режиме — появится
    вызов провайдера и/или фото вместо ошибки.
    """
    events: list[str] = []
    bot = _Bot(events)
    provider = _Provider(events)
    seams = _seams(events, ledger=_ledger(tmp_path), provider=provider,
                   image_status=IMAGE_DOWN)
    _install(monkeypatch, bot, seams)

    await meme_command.cmd_meme(_target(bot))

    assert events == ["delete", "text"], events   # пайплайн не начинался
    assert "summary" not in events and "provider" not in events
    assert bot.kinds() == ["text"], bot.calls
    assert bot.calls[0][2] == \
        meme_command._FAILURE_TEXT[meme.SKIP_IMAGE_NOT_CONFIGURED]
    assert provider.calls == []


# ═══ команда не рекламируется как пользовательская ═════════════════════════

def test_meme_command_is_not_advertised_in_bot_menu():
    """В меню ``/`` команды нет: скрытая админская диагностика (§4 ТЗ)."""
    from services import bot_commands

    names = [cmd.command for cmd in bot_commands._COMMANDS]
    assert "meme" not in names, names


# ═══ P5 (service-часть): ярлыки стадии и новых кодов причины ═══════════════

def test_joke_stage_label_exists_for_every_pipeline_stage():
    """Каждая стадия пайплайна получает человеческий ярлык, ``joke`` — тоже.

    Мутация: убрать ``joke`` из ``MEME_STAGE_LABELS`` — бейдж покажет код.
    """
    assert set(obs.MEME_STAGE_LABELS) == set(meme.STAGES), \
        set(meme.STAGES) ^ set(obs.MEME_STAGE_LABELS)
    for stage in meme.STAGES:
        label = obs.meme_stage_label(stage)
        assert label and label != stage, (stage, label)
    assert "прикол" in obs.meme_stage_label(meme.STAGE_JOKE)
    assert obs.meme_stage_label("") == "—"
    assert obs.meme_stage_label("brand_new_stage") == "brand_new_stage"


@pytest.mark.parametrize("code", [
    meme.SKIP_JOKE_FAILED,
    meme.SKIP_JOKE_EMPTY,
    meme.SKIP_NO_JOKE_BUDGET,
    meme.SKIP_TEMPLATE_EMPTY,
])
def test_new_skip_codes_resolve_to_human_labels(code):
    """Ни один новый код не показывается в бейдже голым кодом."""
    label = obs.reason_label(code)
    assert label and label != code, (code, label)
    assert code not in label
    assert len(label) <= 80, label
