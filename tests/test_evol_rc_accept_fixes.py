"""RC v5 — приёмочные исправления B1/B3/B4/B5 (EVOL-REPLY-CONTEXT-INTEGRITY-01).

Источник: `plans/features/evol/reports/rc-v5-final-acceptance.md`.

* B3 (§13 сц.99/115) — окно несёт ПОДТВЕРЖДЁННЫЕ reply-рёбра: у строки окна
  с ``reply_to_id``, разрешимым внутри окна, печатается ``↳ Reply M…``;
  рёбер вне окна и ложных рёбер нет.
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

import pytest

from services import chat_context
from services import factcheck_suitability as fsg
from services import hot_config
from services.canonical_context import SpeechProjection
from services.factcheck_context import ConversationContext, ContextMessage

CHAT_ID = -1007700001
TS = 1_714_492_800
TG_ROOT = 6103
TG_REPLY = 6106
TG_BYSTANDER = 6105


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


def _row(tg_id, *, uid=10, name="Вася", text="сообщение", ts=TS,
         reply_to_db=None, db_id=None):
    """Строка smart_messages (как её видит рендер): reply_to_id — id строки БД."""
    return {
        "id": db_id if db_id is not None else tg_id + 100_000,
        "tg_message_id": tg_id,
        "chat_id": CHAT_ID,
        "user_id": uid,
        "author_name": name,
        "text": text,
        "timestamp": ts,
        "reply_to_id": reply_to_db,
        "is_forward": 0,
        "forward_source": None,
        "media_type": "text",
    }


# ── B3: подтверждённое reply-ребро внутри окна ──────────────────────────────

def test_window_marks_reply_edge_inside_window(speech_on):
    """§9.5 п.2 / сц.99: Reply 6106→6103 внутри окна виден как Reply."""
    root = _row(TG_ROOT, uid=10, name="Пётр", text="исходный тезис", ts=TS)
    reply = _row(TG_REPLY, uid=20, name="Алиса", text="бот, разбери это",
                 ts=TS + 120, reply_to_db=root["id"])
    bystander = _row(TG_BYSTANDER, uid=30, name="Хан", text="параллельная ветка",
                     ts=TS + 60)
    projection = SpeechProjection(run_id="run-b3")

    block = chat_context.format_chat_context(
        [root, bystander, reply], max_chars=2000,
        anchor_message_id=TG_REPLY, projection=projection)

    root_label = projection.label_of_item(f"tg:{TG_ROOT}")
    reply_line = next(line for line in block.split("\n")
                      if "разбери это" in line)
    assert f"↳ Reply {root_label}" in reply_line
    # Ребро напечатано ровно для реального Reply, а не для соседства.
    bystander_line = next(line for line in block.split("\n")
                          if "параллельная ветка" in line)
    assert "↳ Reply" not in bystander_line
    # Сырые Telegram id в речевой строке не появляются.
    assert f"tg:{TG_ROOT}" not in block


def test_window_does_not_invent_edge_for_parent_outside_window(speech_on):
    """§8: родитель вне окна — связи не выдумываем (никакого ``↳ Reply``)."""
    orphan = _row(TG_REPLY, uid=20, name="Алиса", text="ответ в пустоту",
                  ts=TS + 120, reply_to_db=999_999)
    projection = SpeechProjection(run_id="run-b3-off")

    block = chat_context.format_chat_context(
        [orphan], max_chars=2000, anchor_message_id=TG_REPLY,
        projection=projection)

    assert "ответ в пустоту" in block
    assert "↳ Reply" not in block


def test_global_context_row_marks_reply_edge(speech_on):
    """Тот же шов в Direct: строка `<Global_Context>` несёт ребро Reply."""
    from tests.test_evol_reply_context_consumers import _service

    svc = _service()
    projection = SpeechProjection(run_id="run-b3-direct")
    root = _row(TG_ROOT, uid=10, name="Пётр", text="исходный тезис", ts=TS)
    reply = _row(TG_REPLY, uid=20, name="Алиса", text="бот, разбери это",
                 ts=TS + 120, reply_to_db=root["id"])
    window_items = {row["id"]: f"tg:{row['tg_message_id']}"
                    for row in (root, reply)}
    projection.reserve([f"tg:{TG_ROOT}", f"tg:{TG_REPLY}"])

    line = svc._context_row_line(reply, {}, projection=projection,
                                 window_items=window_items)
    assert "↳ Reply" in line and f"↳ Reply M1" in line
    # Прочие вызовы (без карты окна) выводят прежнюю строку байт-в-байт.
    assert "↳ Reply" not in svc._context_row_line(
        reply, {}, projection=projection)


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
                   ts=TS + 180, reply_to_db=root["id"])
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
