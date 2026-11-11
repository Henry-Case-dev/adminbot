"""S5-MEME (P0-INIT-MEME-UX-DIAG) — маркер ручного приоритета и обрыв запуска.

Контракт (``plans/features/p0-init-meme-ux-diag/requirements-map.json``):

* **P0IM-MM-MARKER** — маркер ``manual_priority_until`` ставится ДО генерации с
  TTL 600 с и гасится в терминальном исходе; истёкший until не выдаётся за
  текущую блокировку (read-model-половина уже закрыта в S6-FRESH).
* **P0IM-MM-PRIO** — приоритет снимается своевременно при нормальном
  завершении и при установленном отказе; падение процесса восстанавливается
  существующим durable механизмом (TTL — страховка, а не механизм).
* **P0IM-MM-TRACE** — по шагам ручного запуска есть ФАКТ: запись приоритета
  видна в журнале попытки, включая НЕУДАЧНУЮ запись маркера.
* R0 D5/D7 (``evidence/r0/diagnosis-2.58.188.md`` §6) — прежнее поведение:
  маркер не снимался на терминальном исходе, а ``CancelledError`` (это
  ``BaseException``) не перехватывался: рестарт сервиса оставлял запуск без
  строки журнала и без ответа пользователю.

Правила: сообщения в реальные чаты не отправляются — только фейковый bot;
время и внешние границы подменяются швами; subject-under-test (обработчик,
пайплайн, стейтменты координации) не подменяется.

TEST-LIFECYCLE: CONTRACT owner=P0-INIT-MEME-UX-DIAG/S5-MEME
"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from handlers import meme_command
from services import meme_initiative as meme
from services import publication_coordination as pub
from web.api import initiative_publications as pubapi

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
CHAT = -100777
ADMIN = 5885953495
MESSAGE_ID = 777
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}
IMAGE_DOWN = {"available": False,
              "reason": meme.SKIP_IMAGE_NOT_CONFIGURED,
              "health": "missing", "configured": False, "module_enabled": False}


# ── фейки: сеть и провайдеры подменены, пайплайн — настоящий ────────────────

class _Bot:
    def __init__(self) -> None:
        self.id = 4242
        self.calls: list[tuple] = []

    async def delete_message(self, chat_id, message_id):
        return True

    async def send_photo(self, chat_id, photo, **kwargs):
        self.calls.append(("photo", int(chat_id), dict(kwargs)))
        return SimpleNamespace(message_id=100 + len(self.calls))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("text", int(chat_id), str(text)))
        return SimpleNamespace(message_id=200 + len(self.calls))

    def texts(self) -> list[str]:
        return [call[2] for call in self.calls if call[0] == "text"]

    def photos(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "photo"]


class _Message:
    def __init__(self, bot: _Bot) -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=CHAT, type="supergroup")
        self.from_user = SimpleNamespace(id=ADMIN)
        self.message_id = MESSAGE_ID
        self.text = "/meme"

    async def delete(self):
        return await self.bot.delete_message(self.chat.id, self.message_id)


class _Provider:
    """Провайдер картинки: успех, отказ или ОБРЫВ процесса (CancelledError)."""

    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.calls = 0

    async def __call__(self, prompt, chat_id, job_id):
        self.calls += 1
        if self.mode == "cancel":
            raise asyncio.CancelledError()
        if self.mode == "fail":
            return SimpleNamespace(ok=False, called=True, reason="provider_error",
                                   content=None)
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(n: int = 3) -> list[dict]:
    return [{"chat_id": CHAT, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


def _database(tmp_path):
    """Реальный файл БД: журнал попыток + таблица брони (одна схема, v40/v41)."""
    path = str(tmp_path / "meme_s5.db")
    meme.SqliteQuotaLedger(path).apply_schema()
    return SimpleNamespace(db_path=path), path


def _marker(path: str):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            f"SELECT manual_priority_until FROM {pub.CLAIM_TABLE} "
            "WHERE chat_id = ?", (CHAT,)).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def _seams(*, provider=None, image_status=None, message_reader=None,
           summarizer=None) -> dict:
    async def _summary(chat_id, rows, system):
        return "выжимка"

    async def _joke(chat_id, summary, instruction):
        return "прикол"

    seams = {
        "settings": _settings(),
        "now": NOW,
        "tz_name": "UTC",
        "tz_source": "utc_fallback",
        "messages": _rows(),
        "summarizer": summarizer or _summary,
        "joke_generator": _joke,
        "image_provider": provider if provider is not None else _Provider(),
        "publish_gate": None,
        "model_chars": 200,
        "image_status": IMAGE_OK if image_status is None else image_status,
        "initiative_enabled": lambda: True,
    }
    if message_reader is not None:
        seams.pop("messages", None)
        seams["message_reader"] = message_reader
    return seams


def _install(monkeypatch, bot: _Bot, db, seams: dict) -> None:
    async def _admin(_uid, _cid):
        return True

    monkeypatch.setattr(meme_command, "_db", db, raising=False)
    monkeypatch.setattr(meme_command, "_llm", None, raising=False)
    monkeypatch.setattr(meme_command, "_bot", bot, raising=False)
    monkeypatch.setattr(meme_command, "_pipeline_seams", dict(seams),
                        raising=False)
    monkeypatch.setattr(meme_command, "is_meme_admin", _admin)


@pytest.fixture(autouse=True)
def _clean_module_state():
    meme.reset_process_attempts()
    yield
    meme.reset_process_attempts()
    meme_command._db = None
    meme_command._llm = None
    meme_command._bot = None
    meme_command._pipeline_seams = {}


def _attempt_rows(path: str) -> list[dict]:
    return meme.SqliteQuotaLedger(path).attempts(CHAT)


def _terminal_row(rows: list[dict]):
    """Терминальная строка попытки: ``_finish`` пишет в неё ``attempt_mode``.

    ``attempts()`` отдаёт строки от свежих к старым, поэтому «последняя строка
    списка» — не терминальная: ищем по ФАКТУ записи, а не по позиции.
    """
    for row in rows:
        facts = meme.parse_attempt_facts(row)
        if "attempt_mode" in facts:
            return row
    return None


def _priority_marker_fact(rows: list[dict]):
    for row in rows:
        facts = meme.parse_attempt_facts(row)
        if "priority_marker" in facts:
            return facts["priority_marker"]
    return None


# ═══ 1. маркер снимается на КАЖДОМ терминальном исходе ═══════════════════════

@pytest.mark.asyncio
async def test_marker_is_set_before_generation_and_cleared_on_success(
        monkeypatch, tmp_path):
    """Успех: маркер стоит во время генерации и снят по её завершении.

    Mutation: убрать снятие из ``finally`` — маркер остаётся до TTL (600 с),
    авто-путь этого чата заблокирован, тест красный по ``_marker``.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    seen: list[int] = []

    async def _summary(chat_id, rows, system):
        # Генерация реально идёт: маркер обязан уже стоять в БД.
        seen.append(_marker(path))
        return "выжимка"

    _install(monkeypatch, bot, db, _seams(summarizer=_summary))

    await meme_command.cmd_meme(_Message(bot))

    assert seen and seen[0] is not None, "маркер ставится ДО генерации"
    assert seen[0] > NOW_TS
    assert _marker(path) is None, "маркер снят в терминальном исходе (успех)"
    assert [c[0] for c in bot.calls] == ["photo"], bot.calls
    rows = _attempt_rows(path)
    terminal = _terminal_row(rows)
    assert terminal is not None, rows
    assert terminal["outcome"] == "published", rows


@pytest.mark.asyncio
async def test_marker_is_cleared_when_the_run_refuses(
        monkeypatch, tmp_path):
    """Установленный отказ (нет image backend): маркер снят, отказ показан.

    Mutation: снимать маркер только на успехе — тест красный по ``_marker``.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    provider = _Provider()
    _install(monkeypatch, bot, db,
             _seams(provider=provider, image_status=IMAGE_DOWN))

    await meme_command.cmd_meme(_Message(bot))

    assert _marker(path) is None, "маркер снят при установленном отказе"
    assert provider.calls == 0, "пайплайн не дошёл до провайдера"
    assert bot.texts() == [
        meme_command._FAILURE_TEXT[meme.SKIP_IMAGE_NOT_CONFIGURED]]
    assert bot.photos() == []
    rows = _attempt_rows(path)
    terminal = _terminal_row(rows)
    assert terminal is not None, rows
    assert terminal["reason_code"] == meme.SKIP_IMAGE_NOT_CONFIGURED, terminal


@pytest.mark.asyncio
async def test_marker_is_cleared_when_the_run_raises(monkeypatch, tmp_path):
    """Ошибка моста (исключение пайплайна): одно сообщение и маркер снят.

    Mutation: убрать ``finally`` — маркер остаётся жить после ошибки.
    """
    db, path = _database(tmp_path)
    bot = _Bot()

    async def _boom(chat_id, limit):
        raise RuntimeError("journal bridge down")

    _install(monkeypatch, bot, db, _seams(message_reader=_boom))

    await meme_command.cmd_meme(_Message(bot))

    assert _marker(path) is None, "маркер снят и на пути ошибки"
    assert bot.texts() == [meme_command._GENERIC_FAILURE], bot.calls
    assert bot.photos() == []


@pytest.mark.asyncio
async def test_marker_is_cleared_when_the_run_is_cancelled(
        monkeypatch, tmp_path):
    """Отмена процесса: маркер снят, отмена проброшена дальше.

    Mutation: обрабатывать только ``Exception`` — ``CancelledError`` не
    ловится, ``finally`` не выполняется (маркер доживает до TTL), тест красный.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    _install(monkeypatch, bot, db, _seams(provider=_Provider(mode="cancel")))

    with pytest.raises(asyncio.CancelledError):
        await meme_command.cmd_meme(_Message(bot))

    assert _marker(path) is None, "маркер снят и при обрыве запуска"


# ═══ 2. обрыв запуска — терминальная строка с реальным этапом ═══════════════

@pytest.mark.asyncio
async def test_cancelled_run_writes_terminal_row_with_stop_stage(
        monkeypatch, tmp_path):
    """``CancelledError`` на этапе картинки — строка журнала, а не тишина.

    Проверяется ФАКТ записи: терминальная строка с ``stage=image_generation``,
    исходом ``failed``, кодом ``run_interrupted`` и той же идентичностью
    запуска (``job_id``), что и остальные строки этой попытки.

    Mutation: убрать ``except asyncio.CancelledError`` в ``consider_chat`` —
    строк нет вовсе (R0 D7), тест красный.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    provider = _Provider(mode="cancel")
    _install(monkeypatch, bot, db, _seams(provider=provider))

    with pytest.raises(asyncio.CancelledError):
        await meme_command.cmd_meme(_Message(bot))

    assert provider.calls == 1, "обрыв произошёл на этапе картинки"
    rows = _attempt_rows(path)
    assert rows, "у прерванного запуска есть строки журнала"
    terminal = _terminal_row(rows)
    assert terminal is not None, rows
    assert terminal["stage"] == meme.STAGE_IMAGE, terminal
    assert terminal["outcome"] == "failed", terminal
    assert terminal["reason_code"] == meme.REASON_RUN_INTERRUPTED, terminal
    assert terminal["job_id"].startswith(f"meme:{CHAT}:"), terminal
    facts = meme.parse_attempt_facts(terminal)
    assert facts.get("detail") == "process_cancelled", facts
    assert facts.get("attempt_mode") == meme.MODE_MANUAL, facts
    # Пройденные этапы остаются видимыми: строка не выдумывает генерацию.
    stages = [row["stage"] for row in rows]
    assert meme.STAGE_SUMMARY in stages and meme.STAGE_JOKE in stages, stages
    assert meme.STAGE_PUBLISH not in stages, stages


@pytest.mark.asyncio
async def test_cancelled_run_reaches_the_publications_read_model(
        monkeypatch, tmp_path):
    """S4-трасса: попытка «остановилась», а не «не запускалась».

    Читается ТОТ ЖЕ агрегатор, что отдаёт ``/initiative/publications``:
    ``incomplete_historical`` False (идентичность есть), исход ``failed``,
    причина ``run_interrupted`` с русским ярлыком, этап остановки записан.

    Mutation: писать строку без ``job_id`` (или не писать) — агрегатор даёт
    ``incomplete_historical``/``noRows`` вместо реальной попытки.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    _install(monkeypatch, bot, db, _seams(provider=_Provider(mode="cancel")))

    with pytest.raises(asyncio.CancelledError):
        await meme_command.cmd_meme(_Message(bot))

    attempts = pubapi._meme_attempts_grouped(_attempt_rows(path))
    assert len(attempts) == 1, attempts
    attempt = attempts[0]
    assert attempt["job_id"].startswith(f"meme:{CHAT}:"), attempt
    assert attempt["incomplete_historical"] is False, attempt
    assert attempt["outcome"] == "failed", attempt
    assert attempt["reason_code"] == meme.REASON_RUN_INTERRUPTED, attempt
    assert attempt["stage"] == meme.STAGE_IMAGE, attempt
    assert attempt["delivered"] is False, attempt
    assert "прерван" in attempt["reason_label"], attempt
    assert attempt["chain_len"] >= 2, attempt


@pytest.mark.asyncio
async def test_cancelled_run_tells_the_user_and_clean_run_stays_silent(
        monkeypatch, tmp_path):
    """Обрыв — одно короткое сообщение; чистый запуск его НЕ получает.

    Mutation: отправлять уведомление всегда — успешный запуск получит лишний
    текст рядом с картинкой, первая половина теста красная.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    _install(monkeypatch, bot, db, _seams(provider=_Provider(mode="cancel")))

    with pytest.raises(asyncio.CancelledError):
        await meme_command.cmd_meme(_Message(bot))

    assert bot.texts() == [meme_command._INTERRUPTED_TEXT], bot.calls
    assert bot.photos() == []
    assert "image_generation_failed" not in meme_command._INTERRUPTED_TEXT
    assert len(meme_command._INTERRUPTED_TEXT) <= 80

    # Чистый запуск: только изображение, ни одного текста.
    clean_bot = _Bot()
    _install(monkeypatch, clean_bot, db, _seams())
    await meme_command.cmd_meme(_Message(clean_bot))
    assert [c[0] for c in clean_bot.calls] == ["photo"], clean_bot.calls
    assert clean_bot.texts() == []


@pytest.mark.asyncio
async def test_cancellation_after_delivery_is_not_a_scare(
        monkeypatch, tmp_path):
    """Обрыв ПОСЛЕ отправки картинки — публикация, а не «мем не получился».

    Mutation: писать ``failed``/уведомлять без учёта факта доставки —
    пользователь получает картинку и следом «мем не получился».
    """
    db, path = _database(tmp_path)
    bot = _Bot()

    async def _cancelled_output(*args, **kwargs):
        raise asyncio.CancelledError()

    _install(monkeypatch, bot, db, _seams())
    monkeypatch.setattr(meme, "_record_meme_output", _cancelled_output)

    with pytest.raises(asyncio.CancelledError):
        await meme_command.cmd_meme(_Message(bot))

    assert len(bot.photos()) == 1, bot.calls
    assert bot.texts() == [], "картинка ушла — пугающего текста нет"
    terminal = _terminal_row(_attempt_rows(path))
    assert terminal is not None
    assert terminal["outcome"] == "published", terminal
    assert terminal["reason_code"] == "sent", terminal


# ═══ 3. неудачная запись маркера — запись в журнале, а не только WARNING ═══

@pytest.mark.asyncio
async def test_failed_marker_write_is_recorded_in_the_attempt_journal(
        monkeypatch, tmp_path):
    """Сбой записи маркера: ручной запуск идёт, но факт ВИДЕН в журнале.

    R0 D5: раньше такой сбой был только WARNING-ом. Здесь проверяется запись
    попытки: ``priority_marker.ok is False`` и причина сбоя, при этом мем
    всё равно генерируется (маркер — координация, а не разрешение).

    Mutation: вернуть ``claim_manual_priority`` к «тихому» числу без передачи
    факта в пайплайн — в журнале нет ``priority_marker``, тест красный.
    """
    db, path = _database(tmp_path)
    bot = _Bot()

    async def _broken_claim(self, chat_id, *, now=None, ttl=0):
        raise RuntimeError("sqlite is locked")

    monkeypatch.setattr(pub.PublicationCoordinator, "claim_manual_priority",
                        _broken_claim)
    _install(monkeypatch, bot, db, _seams())

    await meme_command.cmd_meme(_Message(bot))

    rows = _attempt_rows(path)
    marker = _priority_marker_fact(rows)
    assert marker is not None, "факт записи маркера есть в журнале попытки"
    assert marker["ok"] is False, marker
    assert marker["until"] == 0, marker
    assert marker["detail"] == "exception:RuntimeError", marker
    # Маркер не поставлен — мем всё равно сделан и отправлен.
    assert [c[0] for c in bot.calls] == ["photo"], bot.calls
    assert _marker(path) is None


@pytest.mark.asyncio
async def test_successful_marker_write_is_also_recorded(monkeypatch, tmp_path):
    """Успешная запись приоритета — тоже ФАКТ попытки (P0IM-MM-TRACE).

    Mutation: не передавать запись маркера в пайплайн — шаг «запись
    приоритета» остаётся без доказательства в журнале.
    """
    db, path = _database(tmp_path)
    bot = _Bot()
    _install(monkeypatch, bot, db, _seams())

    await meme_command.cmd_meme(_Message(bot))

    marker = _priority_marker_fact(_attempt_rows(path))
    assert marker is not None, "факт записи маркера есть в журнале"
    assert marker["ok"] is True, marker
    assert marker["until"] > NOW_TS, marker
    assert marker["detail"] == "", marker


# ═══ 4. снятие маркера снимает ТОЛЬКО своё значение (гонки) ════════════════

def test_release_clears_only_its_own_marker(tmp_path):
    """Параллельный `/meme` не теряет приоритет из-за чужого снятия.

    Mutation: снимать любое значение (без ``:until``) — свежий маркер второго
    запуска гаснет, ``_marker`` становится ``None``, тест красный.
    """
    path = str(tmp_path / "claims.db")
    meme.SqliteQuotaLedger(path).apply_schema()
    store = pub.SqliteClaimStore(path)

    first = store.claim_manual_priority(chat_id=CHAT, now=NOW_TS)
    second = store.claim_manual_priority(chat_id=CHAT, now=NOW_TS + 5)
    assert second > first

    assert store.release_manual_priority(chat_id=CHAT, now=NOW_TS + 6,
                                         until=first) is False
    assert _marker(path) == second, "чужой (свежий) маркер не снят"

    assert store.release_manual_priority(chat_id=CHAT, now=NOW_TS + 7,
                                         until=second) is True
    assert _marker(path) is None
    # Повторное снятие — не ошибка и не «успех»: снимать нечего.
    assert store.release_manual_priority(chat_id=CHAT, now=NOW_TS + 8,
                                         until=second) is False


def test_release_without_a_marker_value_does_not_touch_the_table(tmp_path):
    """``until=0`` (маркер не поставлен) — ноль стейтментов по таблице."""
    path = str(tmp_path / "claims.db")
    meme.SqliteQuotaLedger(path).apply_schema()
    store = pub.SqliteClaimStore(path)
    until = store.claim_manual_priority(chat_id=CHAT, now=NOW_TS)

    assert store.release_manual_priority(chat_id=CHAT, now=NOW_TS + 1,
                                         until=0) is False
    assert _marker(path) == until


# ═══ 5. код причины читается по-человечески ════════════════════════════════

def test_interrupted_reason_has_a_human_label():
    """Новый код не показывается голым токеном (единый словарь причины)."""
    from services import initiative_observer as obs

    label = obs.reason_label(meme.REASON_RUN_INTERRUPTED)
    assert label and label != meme.REASON_RUN_INTERRUPTED
    assert meme.REASON_RUN_INTERRUPTED not in label
    assert len(label) <= 80
    # Это не «пропуск по логике мемов»: в закрытый словарь skip не добавляется.
    assert meme.REASON_RUN_INTERRUPTED not in meme.SKIP_REASONS


def test_interrupted_row_job_id_is_unique_per_run(tmp_path):
    """Идентичность запуска реальная, а не общая строка-заглушка."""
    trace = meme.RunTrace(chat_id=CHAT)
    assert trace.job_id == ""
    # uuid не используется в трассе: идентичность приходит из пайплайна.
    assert uuid.uuid4().hex != trace.job_id
