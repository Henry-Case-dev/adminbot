"""UR-23.4: фактчек-доставка пишет durable ledger `mca_bot_outputs`.

До фикса factcheck-ответ доставлялся через общий `send_chunked_reply`
БЕЗ записи ledger — ответы фактчека были невидимы для «бот помнит свои
ответы» (UR-14/UR-23) и duplicate/observability-логики.

Покрытие (acceptance UR-23.4):
  * (a) temporal-доставка вердикта → ровно одна ledger-строка с маркером
    ветки `source_feature='factcheck'` и РЕАЛЬНЫМ tg_message_id первой
    доставленной части;
  * (b) content_text/content_hash строки совпадают с фактически
    доставленным текстом (digest);
  * (c) чанковая доставка (текст > 4096) → по-прежнему ОДНА строка
    (нет double-write на чанки);
  * (d) mutation: запись ledger нейтрализована → доставленный ответ НЕ
    оставляет строку (чувствительность (a) к факту записи);
  * renderer v2: `deliver_factcheck` возвращает id первой доставленной
    части — сайт v2-оркестратора пишет ledger по этому id (флаг-OFF ветка,
    контракт возврата закреплён).

R17: в тестах числа/коды; секретов нет.
"""
import dataclasses
import types

import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import factcheck as fh
from services import bot_output_ledger as bol
from services.database import DatabaseService
from services.factcheck_orchestrator import FactcheckPresentation
from services.factcheck_renderer import deliver_factcheck
from services.factcheck_service import ClaimPublication

CHAT_ID = -1002340001
VERDICT = "Вердикт: тезис не подтверждается источниками"


# ── Инфраструктура ──────────────────────────────────────────────────────────

class _NullCtx:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeBot:
    """bot.send_message → Message-двойник с монотонными реальными id."""

    def __init__(self, first_id=4100):
        self._next_id = first_id
        self.sent = []                      # (chat_id, text, kwargs)

    async def send_message(self, chat_id, text, **kwargs):
        mid = self._next_id
        self._next_id += 1
        self.sent.append((int(chat_id), str(text), dict(kwargs)))
        return types.SimpleNamespace(message_id=mid)


async def _db(tmp_path, name="ur234.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _ledger_rows(db, chat_id=CHAT_ID):
    cursor = await db.db.execute(
        "SELECT * FROM mca_bot_outputs WHERE chat_id = ? ORDER BY output_id",
        (int(chat_id),))
    return [dict(r) for r in await cursor.fetchall()]


def _msg(message_id=11):
    msg = MagicMock()
    msg.text = "фактчек"
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = 7
    return msg


@pytest.fixture
def handler_env(monkeypatch):
    """Temporal-ветка без сети: envelope rejected → честный легаси
    check_claim внутри temporal-маршрута; РЕАЛЬНЫЙ send_chunked_reply."""
    pool = MagicMock()
    permit = MagicMock()
    permit.release = lambda: None
    pool.try_acquire = AsyncMock(return_value=permit)
    monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool",
                        lambda: pool)
    monkeypatch.setattr(fh, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value="contextual"))
    from services import temporal_factcheck as tf
    monkeypatch.setattr(tf, "build_envelope",
                        AsyncMock(return_value=(None, "test_rejected")))
    yield fh
    fh._service = None
    fh._db = None


async def _run_temporal(db, bot, *, verdict=VERDICT):
    """Один прогон `_factcheck_temporal` до доставки вердикта."""
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=verdict)
    fh.setup_factcheck(service, db)
    target = _msg(message_id=77)
    msg = _msg(message_id=11)
    msg.reply_to_message = target
    publication = ClaimPublication(
        text="Проверяемый тезис про дату",
        target_tg_message_id=77,
        target_source="explicit_reply",
        text_sufficient=True)
    outcome = await fh._factcheck_temporal(
        msg, bot, target, "Проверяемый тезис про дату", None, None,
        publication=publication, context_feed="ctx-feed")
    return outcome


# ── (a) Доставленный ответ → ledger-строка с маркером factcheck ─────────────

class TestFactcheckLedgerWritten:
    @pytest.mark.asyncio
    async def test_delivered_verdict_ledger_record(self, handler_env,
                                                   tmp_path):
        db = await _db(tmp_path)
        bot = _FakeBot(first_id=4101)
        outcome = await _run_temporal(db, bot)
        assert outcome == "verdict"
        # доставка состоялась в фейковый Telegram
        assert len(bot.sent) >= 1
        # ровно одна ledger-строка на один доставленный ответ
        rows = await _ledger_rows(db)
        assert len(rows) == 1
        row = rows[0]
        # маркер ветки factcheck + честная таксономия/статус доставки
        assert row["source_feature"] == "factcheck"
        assert row["output_kind"] == "rich_message"
        assert row["delivery_status"] == "delivered"
        # РЕАЛЬНЫЙ message_id первой (реплай-)части, возвращённый Telegram
        assert row["tg_message_id"] == 4101
        # chat и reply-связь (фактический Telegram-reply на цель)
        assert row["chat_id"] == CHAT_ID
        assert row["parent_message_ref"] == "tg:77"
        # correlation_id есть (temporal run_id или новый correlation)
        assert row["correlation_id"]
        assert row["sent_at"] and row["sent_at"] > 0

    @pytest.mark.asyncio
    async def test_correlation_matches_temporal_run(self, handler_env,
                                                    tmp_path, monkeypatch):
        """Envelope-ветка: correlation_id = run_id temporal-прогона."""
        from services import temporal_factcheck as tf
        db = await _db(tmp_path, "ur234_run.db")
        bot = _FakeBot()
        run = MagicMock()
        run.verdict_text = VERDICT
        run.fallback_used = False
        service = MagicMock()
        service.check_claim_envelope = AsyncMock(return_value=run)
        fh.setup_factcheck(service, db)
        async def _fake_record(db_, result, **kwargs):
            return "tfr-test0000000001"
        monkeypatch.setattr(tf, "record_temporal_run", _fake_record)
        monkeypatch.setattr(tf, "build_envelope",
                            AsyncMock(return_value=(object(), None)))
        target = _msg(message_id=77)
        msg = _msg(message_id=11)
        msg.reply_to_message = target
        publication = ClaimPublication(
            text="Проверяемый тезис про дату",
            target_tg_message_id=77, target_source="explicit_reply",
            text_sufficient=True)
        outcome = await fh._factcheck_temporal(
            msg, bot, target, "Проверяемый тезис про дату", None, None,
            publication=publication, context_feed="ctx-feed")
        assert outcome == "verdict"
        rows = await _ledger_rows(db)
        assert len(rows) == 1
        assert rows[0]["source_feature"] == "factcheck"
        assert rows[0]["correlation_id"] == "tfr-test0000000001"


# ── (b) Digest: ledger-контент = фактически доставленный текст ──────────────

class TestLedgerMatchesDeliveredText:
    @pytest.mark.asyncio
    async def test_content_and_hash_match_delivery(self, handler_env,
                                                   tmp_path):
        db = await _db(tmp_path, "ur234_digest.db")
        bot = _FakeBot()
        outcome = await _run_temporal(db, bot)
        assert outcome == "verdict"
        rows = await _ledger_rows(db)
        assert len(rows) == 1
        row = rows[0]
        # одна часть: content_text байт-в-байт равен доставленному тексту
        assert len(bot.sent) == 1
        assert row["content_text"] == bot.sent[0][1]
        # digest стабильный и соответствующий контенту
        assert row["content_hash"] == bol.content_hash(row["content_text"])
        assert row["content_hash"] == bol.content_hash(bot.sent[0][1])


# ── (c) Чанковая доставка: нет double-write ─────────────────────────────────

class TestNoDoubleWriteOnChunks:
    @pytest.mark.asyncio
    async def test_chunked_delivery_single_ledger_row(self, handler_env,
                                                      tmp_path):
        db = await _db(tmp_path, "ur234_chunks.db")
        bot = _FakeBot()
        long_verdict = ("длинный вывод о проверке " * 900)   # ~22k chars
        outcome = await _run_temporal(db, bot, verdict=long_verdict)
        assert outcome == "verdict"
        # доставка реально многочастная
        assert len(bot.sent) >= 2
        # ledger: ОДНА строка на ответ, а не по чанку
        rows = await _ledger_rows(db)
        assert len(rows) == 1
        row = rows[0]
        # id первой (реплой-)части; полный текст ответа — в одной строке
        assert row["tg_message_id"] == 4100
        assert row["content_text"] == long_verdict
        assert row["content_hash"] == bol.content_hash(long_verdict)
        # все части одного ответа имеют одинаковый correlation_id
        # (одно строка-представитель, correlation не дробится)
        assert row["correlation_id"]


# ── (d) Mutation: запись нейтрализована → (a) краснеет ──────────────────────

class TestMutationSensitivity:
    @pytest.mark.asyncio
    async def test_write_disabled_leaves_no_row(self, handler_env, tmp_path,
                                                monkeypatch):
        """Если ledger-вызов убрать/нейтрализовать — доставка работает, но
        строка НЕ появляется: assertion (a) реально ловит отсутствие."""
        db = await _db(tmp_path, "ur234_mut.db")
        monkeypatch.setattr(bol, "record_delivered_output",
                            AsyncMock(return_value=None))
        bot = _FakeBot()
        outcome = await _run_temporal(db, bot)
        assert outcome == "verdict"
        assert len(bot.sent) >= 1          # доставка была
        assert await _ledger_rows(db) == []   # записи нет → (a) red


# ── Renderer v2: deliver_factcheck возвращает id первой части ───────────────

class TestRendererFirstDeliveredId:
    @pytest.mark.asyncio
    async def test_plain_delivery_returns_first_id(self):
        bot = _FakeBot(first_id=5100)
        presentation = FactcheckPresentation(
            text="plain вердикт", reply_to_message_id=77, parse_mode=None)
        first = await deliver_factcheck(bot, CHAT_ID, presentation,
                                        reply_to_message_id=77)
        assert first == 5100
        assert bot.sent[0][2].get("reply_to_message_id") == 77

    @pytest.mark.asyncio
    async def test_html_chunks_return_first_chunk_id(self):
        bot = _FakeBot(first_id=5200)
        presentation = FactcheckPresentation(
            text=("<b>вердикт</b> " + "подробности проверки " * 600),
            reply_to_message_id=77, parse_mode="HTML")
        first = await deliver_factcheck(bot, CHAT_ID, presentation,
                                        reply_to_message_id=77)
        assert first == 5200
        assert len(bot.sent) >= 1          # HTML-чанки доставлены
        # reply-таргет только у первой части
        assert bot.sent[0][2].get("reply_to_message_id") == 77
        for _chat, _text, kwargs in bot.sent[1:]:
            assert kwargs.get("reply_to_message_id") is None
