"""RC v5 — приёмочные исправления B1/B3/B4/B5 (EVOL-REPLY-CONTEXT-INTEGRITY-01).

Источник: `plans/features/evol/reports/rc-v5-final-acceptance.md`.

* B3 (§13 сц.99/115) — окно несёт ПОДТВЕРЖДЁННЫЕ reply-рёбра: у строки окна
  с ``reply_to_id``, разрешимым внутри окна, печатается ``↳ Reply M…``;
  рёбер вне окна и ложных рёбер нет. Строки берутся из РЕАЛЬНОЙ SQLite
  (схема ``smart_messages``) и в ПРОД-формате: ``reply_to_id`` = Telegram
  message_id родителя (``handlers/summary.py:476-478``), а ``id`` строки БД —
  отдельное число; рендер идёт через штатную сборку
  (``chat_context.build_chat_context`` и ``DirectChatService._build_user_content``
  с композером ON — прод-дефолт).
* B3-трасса (§9.4/сц.109) — метки нового фида имеют обратную карту в
  защищённой трассе на маршруте оркестратора и на probe-маршруте.
* B4 (§13 сц.111) — вытесненная бюджетом ``reply_chains`` объявляется
  пометкой и счётчиком в трассе; бюджет не растёт.
* B5 (§13 сц.7) — связь, установленная ПО ТЕМЕ (Reply у цели нет), помечается
  ``↳ по теме … (не Reply)`` в реальном payload фактчека.
* B1 (§13 сц.26) — артефакт трассы снят реальным прогоном: счётчики
  согласованы (``provider_attempts >= provider_failures``) и в файле есть все
  стадии пути trigger → target → context → claim → search → verdict → delivery.

TEST-LIFECYCLE: CONTRACT (owner=EVOL-REPLY-CONTEXT-INTEGRITY-01 v5, RC v5 B1/B3/B4/B5).
"""
import logging
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from services import chat_context
from services import factcheck_orchestrator as orch
from services import factcheck_suitability as fsg
from services import hot_config
from services import mca_events
from services.canonical_context import SpeechProjection
from services.database import DatabaseService
from services.factcheck_context import ConversationContext, ContextMessage

CHAT_ID = -1007700001
TS = 1_714_492_800
TG_ROOT = 6103
TG_REPLY = 6106
TG_BYSTANDER = 6105
TG_DECOY = 6200          # чужое сообщение: его `id` строки = TG_ROOT
DB_ROOT_ID = 9001        # id строки БД ≠ Telegram id (прод-формат)


class _Cache:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def speech_on():
    saved = hot_config.get_config_cache()
    hot_config.set_config_cache(
        _Cache({"flags.context_speech_projection": True}))
    yield
    hot_config.set_config_cache(saved)


@pytest_asyncio.fixture
async def db(tmp_path):
    """РЕАЛЬНАЯ SQLite со штатной схемой (не заглушка строк)."""
    service = DatabaseService(str(tmp_path / "rc-accept-fixes.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:                                  # pragma: no cover
        pass


async def _insert(db, *, tg_id, text, author="Вася", uid=10, ts=TS,
                  reply_to=None, db_id=None):
    """Строка ``smart_messages`` в ПРОД-формате.

    ``reply_to`` — Telegram message_id родителя (так пишет прод:
    ``handlers/summary.py:476-478`` и ``handlers/youtube.py:963-965``);
    ``db_id`` — ``smart_messages.id`` (своё число, может случайно совпасть с
    Telegram id другого сообщения)."""
    cols = ("user_id, chat_id, text, reply_to_id, timestamp, sent_at,"
            " media_type, author_name, is_forward, tg_message_id")
    vals = (uid, CHAT_ID, text, reply_to, ts, ts, "text", author, 0, tg_id)
    if db_id is None:
        cur = await db.db.execute(
            f"INSERT INTO smart_messages ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?)",
            vals)
    else:
        cur = await db.db.execute(
            f"INSERT INTO smart_messages (id, {cols})"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (db_id,) + vals)
    await db.db.commit()
    return int(cur.lastrowid or 0)


async def _window(db, target_tg=TG_REPLY):
    """Окно читается ШТАТНЫМ методом БД (тот же, что в проде), ASC."""
    return await db.get_messages_around(CHAT_ID, target_tg, 5, 0)


async def _render_chat_window(db, rows, projection, anchor=TG_REPLY):
    """Прод-сборка узкого окна (единственный шов медиа/рендера)."""
    return await chat_context.build_chat_context(
        db, rows, chat_id=CHAT_ID, anchor_message_id=anchor,
        projection=projection)


async def _render_direct_window(rows, projection):
    """Прод-сборка ``<Global_Context>`` (``_build_user_content``, композер ON)."""
    from tests.test_evol_reply_context_consumers import (
        _message, _service_with_window)

    svc = _service_with_window([dict(row) for row in rows])
    blocks = await svc._build_user_content(
        CHAT_ID, _message(), "Вася", target_user_id=10,
        projection=projection)
    payload = "\n".join(str(block) for block in blocks if block)
    match = re.search(r"<Global_Context>.*?</Global_Context>", payload,
                      re.DOTALL)
    return match.group(0) if match else ""


def _line(block: str, marker: str) -> str:
    return next(line for line in block.split("\n") if marker in line)


async def _seed_dialog(db, *, reply_to=TG_ROOT):
    """Диалог прод-формы: корень, сосед по теме, реальный Reply на корень."""
    await _insert(db, tg_id=TG_ROOT, text="исходный тезис", author="Пётр",
                  ts=TS)
    await _insert(db, tg_id=TG_BYSTANDER, text="параллельная ветка",
                  author="Хан", uid=30, ts=TS + 60)
    await _insert(db, tg_id=TG_REPLY, text="бот, разбери это", author="Алиса",
                  uid=20, ts=TS + 120, reply_to=reply_to)


def _row(tg_id, *, uid=10, name="Вася", text="сообщение", ts=TS,
         reply_to=None, db_id=None):
    """Строка smart_messages (dict-форма) в прод-формате.

    ``reply_to`` — Telegram message_id родителя: так его хранит БД (см.
    ``handlers/summary.py:476-478``), а ``id`` строки — отдельное число."""
    return {
        "id": db_id if db_id is not None else tg_id + 100_000,
        "tg_message_id": tg_id,
        "chat_id": CHAT_ID,
        "user_id": uid,
        "author_name": name,
        "text": text,
        "timestamp": ts,
        "reply_to_id": reply_to,
        "is_forward": 0,
        "forward_source": None,
        "media_type": "text",
    }


# ── B3: подтверждённое reply-ребро внутри окна ──────────────────────────────

@pytest.mark.asyncio
async def test_chat_window_carries_confirmed_reply_edge(db, speech_on):
    """§9.5 п.2 / сц.99: Reply 6106→6103 в реальном окне виден как Reply.

    Строки — из настоящей SQLite, ``reply_to_id`` = Telegram id родителя
    (прод-формат), рендер — штатная сборка `build_chat_context`."""
    await _seed_dialog(db)
    rows = await _window(db)
    assert rows[-1]["reply_to_id"] == TG_ROOT          # прод-формат, не `id`
    assert rows[0]["id"] != rows[0]["tg_message_id"]   # id строки ≠ tg id

    projection = SpeechProjection(run_id="run-b3-chat")
    block = await _render_chat_window(db, rows, projection)
    root_label = projection.label_of_item(f"tg:{TG_ROOT}")
    assert root_label, "метка родителя обязана существовать"

    reply_line = _line(block, "разбери это")
    assert f"↳ Reply {root_label}" in reply_line
    # Ребро печатается ровно для реального Reply, а не для соседства по теме.
    assert "↳ Reply" not in _line(block, "параллельная ветка")
    # Сырые Telegram id в речевой строке не появляются.
    assert f"tg:{TG_ROOT}" not in block


@pytest.mark.asyncio
async def test_direct_global_context_carries_confirmed_reply_edge(db, speech_on):
    """Тот же контракт в Direct: строка `<Global_Context>` несёт ребро Reply.

    Путь — реальный `_build_user_content` (композер ON, прод-дефолт), строки
    читаются из настоящей БД; руками карта окна не подаётся."""
    await _seed_dialog(db)
    rows = await _window(db)

    projection = SpeechProjection(run_id="run-b3-direct")
    block = await _render_direct_window(rows, projection)
    assert block, "окно <Global_Context> обязано собраться"
    root_label = projection.label_of_item(f"tg:{TG_ROOT}")
    assert root_label

    assert f"↳ Reply {root_label}" in _line(block, "разбери это")
    assert "↳ Reply" not in _line(block, "параллельная ветка")
    assert f"tg:{TG_ROOT}" not in block


@pytest.mark.asyncio
async def test_legacy_global_context_carries_reply_edge(db, speech_on,
                                                        monkeypatch):
    """Откатный путь (композер OFF) несёт то же ребро: один контракт окна."""
    from services import direct_context_composer as composer

    monkeypatch.setattr(composer, "composer_on", lambda: False)
    await _seed_dialog(db)
    rows = await _window(db)

    projection = SpeechProjection(run_id="run-b3-legacy")
    block = await _render_direct_window(rows, projection)
    root_label = projection.label_of_item(f"tg:{TG_ROOT}")
    assert root_label
    assert f"↳ Reply {root_label}" in _line(block, "разбери это")
    assert "↳ Reply" not in _line(block, "параллельная ветка")


@pytest.mark.asyncio
async def test_no_edge_when_parent_outside_window(db, speech_on):
    """§8: родитель вне окна — связи не выдумываем (никакого ``↳ Reply``)."""
    await _insert(db, tg_id=TG_REPLY, text="ответ в пустоту", author="Алиса",
                  uid=20, ts=TS + 120, reply_to=999_999)
    rows = await _window(db)

    chat_projection = SpeechProjection(run_id="run-b3-off-chat")
    chat_block = await _render_chat_window(db, rows, chat_projection)
    assert "ответ в пустоту" in chat_block
    assert "↳ Reply" not in chat_block

    direct_projection = SpeechProjection(run_id="run-b3-off-direct")
    direct_block = await _render_direct_window(rows, direct_projection)
    assert "ответ в пустоту" in direct_block
    assert "↳ Reply" not in direct_block


@pytest.mark.asyncio
async def test_no_false_edge_when_db_id_equals_parent_tg_id(db, speech_on):
    """Регрессия: `id` строки БД ≠ Telegram id родителя.

    В окне есть строка, чей ``smart_messages.id`` СЛУЧАЙНО равен Telegram id
    родителя (прод-риск, найденный Reviewer). Ребро обязано вести к реальному
    родителю, а не к этому чужому сообщению."""
    await _insert(db, tg_id=TG_ROOT, text="исходный тезис", author="Пётр",
                  ts=TS, db_id=DB_ROOT_ID)
    await _insert(db, tg_id=TG_DECOY, text="совсем другая тема", author="Хан",
                  uid=30, ts=TS + 60, db_id=TG_ROOT)   # id == tg id родителя
    await _insert(db, tg_id=TG_REPLY, text="бот, разбери это", author="Алиса",
                  uid=20, ts=TS + 120, reply_to=TG_ROOT, db_id=9003)
    rows = await _window(db)
    assert any(int(row["id"]) == TG_ROOT for row in rows), \
        "ловушка обязана присутствовать в окне"

    chat_projection = SpeechProjection(run_id="run-b3-false-chat")
    chat_block = await _render_chat_window(db, rows, chat_projection)
    chat_root = chat_projection.label_of_item(f"tg:{TG_ROOT}")
    chat_decoy = chat_projection.label_of_item(f"tg:{TG_DECOY}")
    assert chat_root and chat_decoy
    assert f"↳ Reply {chat_root}" in _line(chat_block, "разбери это")
    assert f"↳ Reply {chat_decoy}" not in chat_block

    direct_projection = SpeechProjection(run_id="run-b3-false-direct")
    direct_block = await _render_direct_window(rows, direct_projection)
    direct_root = direct_projection.label_of_item(f"tg:{TG_ROOT}")
    direct_decoy = direct_projection.label_of_item(f"tg:{TG_DECOY}")
    assert direct_root and direct_decoy
    assert f"↳ Reply {direct_root}" in _line(direct_block, "разбери это")
    assert f"↳ Reply {direct_decoy}" not in direct_block


# ── B3-трасса: метки фида имеют обратную карту (§9.4/сц.109) ────────────────

class _TraceCache:
    """Минимальный кэш для маршрутов фактчека (без сети/диска)."""

    def get(self, key, default=None):
        return default

    async def set(self, key, value, ttl_seconds=None, **_kw):
        return None

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return None


def _capture_speech_projection(monkeypatch):
    """Поймать защищённое событие трассы «метка → реальный ID»."""
    captured: list = []
    real = mca_events.emit_mca_event

    def _spy(event_type, **kwargs):
        if event_type == "speech_projection":
            captured.append(kwargs)
        return real(event_type, **kwargs)

    monkeypatch.setattr(mca_events, "emit_mca_event", _spy)
    return captured


async def _seed_semantic_dialog(db):
    """Цель без текста + соседи: антецедент находится ПО ТЕМЕ (basis=topic)."""
    await _insert(db, tg_id=TG_BYSTANDER, text="двойные и тройные гибриды"
                  " дают перекрестное опыление", author="Гений", uid=30, ts=TS)
    await _insert(db, tg_id=TG_ROOT, text="мышечные волокна бывают двух"
                  " типов: на силу и на выносливость, их прокачивать можно по"
                  " разному", author="Васек", ts=TS + 60)
    await _insert(db, tg_id=TG_REPLY, text="", author="Хан", uid=20, ts=TS + 120)
    await _insert(db, tg_id=TG_REPLY + 1, text="фактчек", author="Пётр",
                  uid=40, ts=TS + 180)
    return "волокна мышцы сила выносливость"


@pytest.mark.asyncio
async def test_probe_route_emits_reverse_map_for_labelled_feed(
        db, speech_on, monkeypatch):
    """§9.4/сц.109: фид с метками не уходит в payload без обратной карты."""
    hint = await _seed_semantic_dialog(db)
    captured = _capture_speech_projection(monkeypatch)

    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TG_REPLY,
        trigger_tg_message_id=TG_REPLY + 1, hint=hint, cache=_TraceCache())

    assert probe is not None and "↳ по теме" in probe.feed
    assert len(captured) == 1
    items = captured[0]["entity_ids"]["items"]
    assert items["M2"] == f"tg:{TG_ROOT}"
    assert items["M3"] == f"tg:{TG_REPLY + 1}"
    assert captured[0]["chat_id"] == CHAT_ID
    assert captured[0]["message_id"] == TG_REPLY


@pytest.mark.asyncio
async def test_orchestrator_route_emits_reverse_map_for_labelled_feed(
        db, speech_on, monkeypatch):
    """сц.109 на маршруте оркестратора: реальный прогон, трасса с картой."""
    hint = await _seed_semantic_dialog(db)
    captured = _capture_speech_projection(monkeypatch)

    req = orch.FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TG_REPLY + 1,
        target_tg_message_id=TG_REPLY, target_text="", kind="reply",
        user_hint=hint)
    service = MagicMock()
    service.check_claim = AsyncMock(
        side_effect=AssertionError("остановка после сборки фида"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(side_effect=AssertionError("LLM offline"))

    await orch.run_factcheck(req, service=service, db=db, bot=AsyncMock(),
                             cache=_TraceCache())

    assert len(captured) == 1, "метки фида без обратной карты в трассе"
    items = captured[0]["entity_ids"]["items"]
    assert f"tg:{TG_ROOT}" in items.values()
    assert f"tg:{TG_REPLY + 1}" in items.values()
    assert captured[0]["chat_id"] == CHAT_ID
    assert captured[0]["message_id"] == TG_REPLY


# ── B4: вытесненная цепочка объявляется и считается ─────────────────────────

def _chain_block() -> str:
    """Реальный ``<reply_chains>``-под-блок (общий util, не ручная строка)."""
    from services.thread_chain import ChainItem, render_reply_chains

    chain = [
        ChainItem(uid=10, name="Вася", text="это следствие, а не причина",
                  is_bot=False, ts=TS + 60, item_id=f"tg:{TG_REPLY}",
                  reply_to_item_id=f"tg:{TG_ROOT}"),
        ChainItem(uid=20, name="Хан", text="корень спора", is_bot=False,
                  ts=TS, item_id=f"tg:{TG_ROOT}"),
    ]
    return render_reply_chains(chain, projection=SpeechProjection(run_id="r"))


@pytest.mark.parametrize("budget", (420, 380, 300))
def test_tight_budget_announces_dropped_reply_chain(speech_on, caplog, budget):
    """сц.111: цепочка, вытесненная бюджетом, не исчезает молча + счётчик."""
    rows = [_row(TG_ROOT + 900 + i, text=f"реплика номер {i} с текстом",
                 ts=TS + i) for i in range(12)]
    rows.append(_row(TG_REPLY, uid=20, name="Алиса", text="цель проверки",
                     ts=TS + 100))
    chain = _chain_block()
    caplog.set_level(logging.WARNING, logger="services.chat_context")

    block = chat_context.format_chat_context(
        rows, max_chars=budget, anchor_message_id=TG_REPLY,
        reply_chains=chain, projection=SpeechProjection(run_id="run-b4"))

    # Бюджет блока не вырос: пометка не расширяет потолок.
    assert len(block) <= budget
    assert "<reply_chains" not in block
    assert "цепочка ответов не показана" in block
    records = [r for r in caplog.records if "omitted_chain=" in r.getMessage()]
    assert records, "факт вытеснения цепочки обязан попасть в трассу"
    assert "omitted_chain=0" not in records[0].getMessage()


# ── B5: смысловая связь помечена как НЕ Reply ───────────────────────────────

class _Db:
    def __init__(self, rows):
        self.rows = list(rows)

    async def get_messages_around(self, chat_id, target, before, after):
        return [dict(r) for r in self.rows]

    async def get_recent_messages(self, chat_id, limit, **kw):
        return [dict(r) for r in self.rows[-limit:]] if limit else []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return None


class _NullCache:
    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return None


@pytest.mark.asyncio
async def test_semantic_antecedent_is_marked_not_reply(speech_on):
    """сц.7/§9.5 п.2: тезис найден ПО ТЕМЕ (Reply у цели нет) → явная
    смысловая клауза, а не выдуманный Reply."""
    rows = [
        _row(TG_BYSTANDER, uid=30, name="Гений",
             text="двойные и тройные гибриды дают перекрестное опыление",
             ts=TS),
        _row(TG_ROOT, uid=10, name="Васек",
             text="мышечные волокна бывают двух типов: на силу и на"
                  " выносливость, их прокачивать можно по разному",
             ts=TS + 60),
        _row(TG_REPLY, uid=20, name="Хан", text="", ts=TS + 120),
        _row(TG_REPLY + 1, uid=40, name="Пётр", text="фактчек", ts=TS + 180),
    ]
    probe = await fsg.resolve_context_claim(
        _Db(rows), CHAT_ID, target_tg_message_id=TG_REPLY,
        trigger_tg_message_id=TG_REPLY + 1,
        hint="волокна мышцы сила выносливость", cache=_NullCache())

    assert probe is not None and probe.claim is not None
    assert probe.claim_basis == "topic"
    assert "↳ по теме" in probe.feed
    assert "(не Reply)" in probe.feed
    # Смысловая связь не выдаёт себя за подтверждённый Reply.
    assert "↳ Reply" not in probe.feed


@pytest.mark.asyncio
async def test_structural_antecedent_stays_silent_about_semantics(speech_on):
    """Обратная сторона: Reply-связь (structural) не помечается «по теме»."""
    root = _row(TG_ROOT, uid=10, name="Васек",
                text="мышечные волокна растут на 30 процентов", ts=TS)
    trigger = _row(TG_REPLY + 1, uid=40, name="Пётр", text="фактчек",
                   ts=TS + 180, reply_to=root["tg_message_id"])
    probe = await fsg.resolve_context_claim(
        _Db([root, trigger]), CHAT_ID, target_tg_message_id=TG_REPLY + 1,
        trigger_tg_message_id=TG_REPLY + 1,
        reply_to_tg_id=root["tg_message_id"], cache=_NullCache())

    assert probe is not None and probe.claim is not None
    assert probe.claim_basis == "structural"
    assert "↳ по теме" not in probe.feed


def test_render_feed_prints_semantic_relation_only_with_projection():
    """Механизм фида: связь печатается в речевом виде и не подменяет Reply."""
    from services.canonical_context import RELATION_SEMANTIC, SpeechRelation

    trigger_tg = TG_REPLY + 1
    ctx = ConversationContext(
        chat_id=CHAT_ID, target_tg_message_id=TG_REPLY,
        trigger_tg_message_id=trigger_tg,
        messages=(
            ContextMessage(
                message_id=2, tg_message_id=trigger_tg, chat_id=CHAT_ID,
                author="Пётр", timestamp=TS + 180, reply_to_tg_id=None,
                is_forward=False, forward_source=None, text="фактчек",
                verbatim=True, author_uid=40),
            ContextMessage(
                message_id=1, tg_message_id=TG_ROOT, chat_id=CHAT_ID,
                author="Васек", timestamp=TS, reply_to_tg_id=None,
                is_forward=False, forward_source=None,
                text="мышечные волокна на силу и на выносливость",
                verbatim=True, author_uid=10),
        ),
        window={"before": 0, "after": 0})
    projection = SpeechProjection(run_id="run-b5")
    relations = {f"tg:{TG_ROOT}": (SpeechRelation(
        RELATION_SEMANTIC, f"tg:{trigger_tg}", basis="topic"),)}

    feed = ctx.render_feed(projection=projection,
                           relations_by_item=relations)

    assert "↳ по теме M1 (не Reply)" in feed
    assert "↳ Reply" not in feed
    # Без проекции клаузы нет: сырой канон не печатает меток.
    raw = ctx.render_feed(relations_by_item=relations)
    assert "↳ по теме" not in raw


# ── B1: трасса снята реальным прогоном и внутренне согласована ──────────────

ARTIFACT = (pathlib.Path(__file__).resolve().parents[1] / "plans"
            / "features" / "evol-reply-context-integrity-01" / "evidence"
            / "trace-factcheck-target.txt")


def _counters(line: str) -> dict:
    return {key: value for key, value in re.findall(r"(\w+)=(\S+)", line)}


def test_evidence_trace_has_full_stage_chain():
    text = ARTIFACT.read_text(encoding="utf-8")
    for stage in ("trigger", "target", "context", "claim", "search",
                  "verdict", "delivery"):
        assert re.search(rf"^\[\d/7 {stage}\]$", text, re.MULTILINE), stage
    # Трасса обязана называть свой источник и что именно не исполнялось.
    assert "scripts/evol_trace_factcheck_target.py" in text
    assert "не исполнялось" in text


def test_evidence_trace_counters_are_internally_consistent():
    """§13.26: `provider_attempts` выводится из фактических provider_status —
    ноль попыток при двух отказах невозможен."""
    text = ARTIFACT.read_text(encoding="utf-8")
    rows = [line for line in text.split("\n")
            if line.startswith("    ") and "provider_attempts=" in line]
    assert rows, "в трассе нет строк матрицы статусов"
    for line in rows:
        counters = _counters(line)
        attempts = int(counters["provider_attempts"])
        failures = int(counters["provider_failures"])
        assert attempts >= failures, line
        # Каждый отказ провайдера наблюдаем как попытку стадии.
        if failures:
            assert attempts > 0, line
    # Отказ провайдера в основной стадии тоже согласован.
    search = next(line for line in text.split("\n")
                  if "provider_refusal" in line)
    assert int(_counters(search)["provider_failures"]) > 0
    assert int(_counters(search)["queries_attempted"]) > 0
