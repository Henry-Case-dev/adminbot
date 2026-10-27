"""P0 NOSTALGIA REWORK W1 (source-2026-10-27, NOST-01..04/07) — движок
исторических эпизодов NostalgiaWorker.

Покрытие:
* NOST-02.2 — календарная арифметика: годовщина вычисляется календарно
  (високосные годы, 29 февраля → 28 февраля по документированному правилу,
  часовой пояс чата, локальные полуночи), не вычитанием секунд; уровни
  окон — календарные периоды (день/ISO-неделя/календарный месяц), не
  «30 последовательных дней»; эпизод через Новый год не обрывается.
* NOST-02.1 — динамические годы по фактическим границам архива: один год /
  три года / более трёх / пропущенный год / архив начинается посреди года;
  пустой период — не ошибка; текущий год не исследуется.
* NOST-03 — адаптивные окна: день → неделя → месяц → продолжение,
  расширение ТОЛЬКО когда сегмент касается границы окна (остановка —
  сегмент закрыт, данных о продолжении нет); потолок продолжения;
  несвязанные обсуждения дня не склеиваются. Для видимости лестницы
  используется суженное окно владельца (year_back_days_window=1):
  дефолт 10 уже шире недели.
* NOST-04 — эпизод вместо отдельного сообщения: реконструкция существующим
  детерминированным сегментатором mca_episodes (время + reply-граф +
  участники); эпизод из одного сообщения допустим; кап строк — голова+хвост;
  честная карточка в логе.
* NOST-07 — достоверность: строки бота исключены из выборки (self-echo),
  forward-лейбл в строках эпизода, имя по uid (алиас приоритетнее
  исторического author_name), «данных недостаточно» — честное молчание.

LLM/бот замоканы; время фиксировано (NOW = 2027-01-15 11:00 локально,
Asia/Yekaterinburg — дефолт SUMMARY_TIMEZONE).
"""
import asyncio
import datetime
import json
import logging

import pytest

from config.settings import settings
from services import hot_config as hot
from services import nostalgia_worker as nw
from services.database import DatabaseService
from services.nostalgia_prompts import parse_nostalgia_answer

logging.getLogger("services.worker_settings").setLevel(logging.CRITICAL)
logging.getLogger("services.param_catalog").setLevel(logging.CRITICAL)
logging.getLogger("services.mca_events").setLevel(logging.CRITICAL)

CHAT_ID = -1002661910336
BOT_ID = 12345
USER_ID = 55
NOW = 1_800_000_000          # 2027-01-15 11:00 Asia/Yekaterinburg (+05)


@pytest.fixture
def db():
    """In-memory SQLite — реальная схема (эпизоды строятся из живых строк)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _SpyDB(DatabaseService):
    """DatabaseService + журнал диапазонных запросов истории (какие периоды
    исследованы; ограничение числа выборок — NOST-11)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.history_calls = []          # [(ts_from, ts_to)]

    async def get_chat_history_messages(self, chat_id, ts_from, ts_to,
                                        limit=600, bot_id=None):
        self.history_calls.append((int(ts_from), int(ts_to)))
        return await super().get_chat_history_messages(
            chat_id, ts_from, ts_to, limit=limit, bot_id=bot_id)


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    def __init__(self, answer="UNCHANGED"):
        self.answer = answer
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        return self.answer

    async def generate_worker(self, role, messages, temperature=None):
        return await self.generate(messages, temperature=temperature)


class _FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text):
        self.calls.append((int(chat_id), str(text)))


def _worker(d, llm=None, *, monkeypatch=None, values=None):
    w = nw.NostalgiaWorker(d, memory=None, store=None,
                           llm=llm if llm is not None else _FakeLLM(),
                           bot=_FakeBot(), bot_id=BOT_ID)
    _hot_cache(monkeypatch, values if values is not None else
               {"memory.nostalgia_enabled": True})
    return w


def _chain(d, a, target, *, tg_start=1000, text="шаг"):
    """Reply-цепочка с ШАГОВЫМИ сообщениями каждый час от `a` до ровно
    `target` (последнее сообщение — на самой границе окна). Шаг 1ч ≤
    reply-горизонта 6ч → сегментатор склеивает в один эпизод.
    Возвращает (число_сообщений, последний_tg_id)."""

    async def run():
        prev = await _msg(d, text, a, tg=tg_start)
        tg = tg_start
        count = 1
        ts = a
        while ts < target:
            ts += 3600
            tg += 1
            count += 1
            prev = await _msg(d, f"{text} продолжение {ts}", ts,
                              reply_to=tg - 1, tg=tg)
        return count, tg
    return run()


_KNOB_1 = {"memory.nostalgia_enabled": True,
           "memory.nostalgia_year_back_days_window": 1}


def _ts_local(y, m, d, hour, minute=0) -> int:
    """unix ts локального времени чата (детерминированные сценарии)."""
    tz = nw._zone(settings.SUMMARY_TIMEZONE)
    return int(datetime.datetime(y, m, d, hour, minute,
                                 tzinfo=tz).timestamp())


async def _msg(d, text, ts, *, uid=USER_ID, name="Вася", reply_to=None,
               is_forward=False, forward_source="", tg=None):
    """Строка smart_messages. `tg` — Telegram message_id (tg_message_id);
    `reply_to` — TG-сообщение-родитель (reply_to_id; живой чат: tg-пространство
    — ровно как в проде, сегментатор mca_episodes склеивает reply-связи)."""
    return await d.save_smart_message(
        uid, CHAT_ID, text, reply_to, int(ts), "text", name,
        is_forward=is_forward, forward_source=forward_source, message_id=tg)


def _worker_time(monkeypatch):
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 12)


# ═══ NOST-02.2: календарная арифметика ══════════════════════════════════════

class TestCalendarArithmetic:
    def test_anniversary_feb29_leap_source_year_keeps_feb29(self):
        # сегодня 29.02.2028 (високосный) → годовщина 2024 (високосный) —
        # реальная дата 29.02, не смещение секундами (NOST-02.2)
        anniv = nw._anniversary_date(datetime.date(2028, 2, 29), 2024)
        assert (anniv.year, anniv.month, anniv.day) == (2024, 2, 29)

    def test_anniversary_feb29_non_leap_maps_to_feb28(self):
        # 29.02 → невисокосный 2027: документированное правило 28.02
        anniv = nw._anniversary_date(datetime.date(2028, 2, 29), 2027)
        assert (anniv.year, anniv.month, anniv.day) == (2027, 2, 28)

    def test_day_window_is_local_midnight_to_midnight(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        anniv = nw._anniversary_date(datetime.date(2027, 1, 15), 2025)
        lo, hi = nw._anniversary_window(anniv, tz, "day", 0, 0)
        assert nw._local_datetime(lo, tz).strftime("%Y-%m-%d %H:%M") == \
            "2025-01-15 00:00"
        assert nw._local_datetime(hi, tz).strftime("%Y-%m-%d %H:%M") == \
            "2025-01-16 00:00"

    def test_month_window_is_calendar_month_not_30_days(self):
        """NOST-03.1 уровень C: месяц — календарный (январь длится до
        1 февраля, август — до 1 сентября), не «30 последовательных дней»."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        anniv = nw._anniversary_date(datetime.date(2027, 1, 15), 2025)
        lo, hi = nw._anniversary_window(anniv, tz, "month", 0, 0)
        assert nw._local_datetime(lo, tz).strftime("%Y-%m-%d") == "2025-01-01"
        assert nw._local_datetime(hi, tz).strftime("%Y-%m-%d") == "2025-02-01"
        anniv_a = nw._anniversary_date(datetime.date(2027, 8, 15), 2025)
        lo_a, hi_a = nw._anniversary_window(anniv_a, tz, "month", 0, 0)
        assert nw._local_datetime(lo_a, tz).strftime("%Y-%m-%d") == \
            "2025-08-01"
        assert nw._local_datetime(hi_a, tz).strftime("%Y-%m-%d") == \
            "2025-09-01"

    def test_week_window_is_iso_week(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        anniv = nw._anniversary_date(datetime.date(2027, 1, 15), 2025)
        assert anniv.weekday() == 2          # 15.01.2025 — среда
        lo, hi = nw._anniversary_window(anniv, tz, "week", 0, 0)
        # ISO-неделя: понедельник 13.01 .. понедельник 20.01
        assert nw._local_datetime(lo, tz).strftime("%Y-%m-%d") == "2025-01-13"
        assert nw._local_datetime(hi, tz).strftime("%Y-%m-%d") == "2025-01-20"

    def test_ladder_day_week_month_continuation_capped(self):
        """NOST-03.1/3.3: лестница день → неделя → месяц → продолжение
        с терминальным потолком; уровни — масштабы, не обязательные стадии."""
        seq = []
        level, cont = "day", 0
        while True:
            nxt = nw._next_research_level(level, cont)
            if nxt is None:
                break
            level, cont = nxt
            seq.append(level)
        assert seq == ["week", "month", "month+1", "month+2", "month+3"]

    def test_cross_year_continuation_window_spans_new_year(self):
        """NOST-02.2: окно продолжения через Новый год — календарные месяцы
        в обе стороны от месяца годовщины (январь 2025 ±1 → декабрь 2024 ..
        февраль 2025 включительно), не обрыв 30-дневным сдвигом."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        anniv = nw._anniversary_date(datetime.date(2027, 1, 15), 2025)
        lo, hi = nw._anniversary_window(anniv, tz, "month+1", 1, 0)
        assert nw._local_datetime(lo, tz).strftime("%Y-%m-%d") == "2024-12-01"
        assert nw._local_datetime(hi, tz).strftime("%Y-%m-%d") == "2025-03-01"


# ═══ NOST-02.1: динамические годы архива ════════════════════════════════════

class TestMultiYearSearch:
    @pytest.mark.asyncio
    async def test_single_year_archive_queries_only_its_year(self, db,
                                                             monkeypatch):
        """T1: архив одного исторического года — исследуется только он
        (запросы не уходят в отсутствующие годы)."""
        _worker_time(monkeypatch)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        await _msg(spy, "было дело в январе", _ts_local(2026, 1, 15, 12))
        w = _worker(spy, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["year"] == 2026
        assert len(spy.history_calls) == 1
        lo, _hi = spy.history_calls[0]
        assert nw._local_datetime(lo).year == 2026
        await spy.close()

    @pytest.mark.asyncio
    async def test_three_years_all_anniversaries_found(self, db,
                                                       monkeypatch):
        """T2: три исторических года — рассматриваются все доступные
        периоды (по эпизоду на каждый год с годовщиной)."""
        _worker_time(monkeypatch)
        await _msg(db, "январь 2023", _ts_local(2023, 1, 15, 12))
        await _msg(db, "январь 2024", _ts_local(2024, 1, 15, 12))
        await _msg(db, "январь 2025", _ts_local(2025, 1, 15, 12))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert [e["year"] for e in episodes] == [2025, 2024, 2023]
        assert all(e["messages"] == 1 for e in episodes)

    @pytest.mark.asyncio
    async def test_more_than_three_years_not_cut_off(self, db, monkeypatch):
        """T3: история длиннее трёх лет — ПОИСК не обрывается на третьем
        году: окна годовщин запрошены для всех лет архива (динамический
        список, не «три SQL-запроса»). Предъявление пулу LLM ограничено
        капом _EPISODES_MAX (свежие годы первыми) — технический кап
        предъявления, не обрыв поиска."""
        _worker_time(monkeypatch)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        for y in (2022, 2023, 2024, 2025, 2026):
            await _msg(spy, f"январь {y}", _ts_local(y, 1, 15, 12))
        w = _worker(spy, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        # поиск: все 5 лет архива исследованы
        assert len(spy.history_calls) == 5
        # предъявление: кап _EPISODES_MAX, свежие первыми (2022 — за капом)
        assert len(episodes) == nw._EPISODES_MAX
        assert [e["year"] for e in episodes] == [2026, 2025, 2024, 2023]
        assert len(lines) == nw._EPISODES_MAX
        await spy.close()

    @pytest.mark.asyncio
    async def test_missing_year_does_not_stop_other_years(self, db,
                                                          monkeypatch):
        """T4: пропущенный год — другие периоды продолжают обрабатываться,
        отсутствие материалов за год не ошибка."""
        _worker_time(monkeypatch)
        await _msg(db, "январь 2023", _ts_local(2023, 1, 15, 12))
        await _msg(db, "январь 2025", _ts_local(2025, 1, 15, 12))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        years = [e["year"] for e in episodes]
        assert years == [2025, 2023]
        assert 2024 not in years and 2026 not in years

    @pytest.mark.asyncio
    async def test_archive_starting_mid_year_no_error(self, db, monkeypatch):
        """T5: архив начинается посреди года — пустые периоды не считаются
        ошибкой; годы ДО начала архива не исследуются."""
        _worker_time(monkeypatch)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        await _msg(spy, "первое сообщение чата", _ts_local(2026, 6, 1, 12))
        w = _worker(spy, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes == [] and lines == []     # годовщина Jan не в архиве
        # единственный запрошенный год — год начала архива (2026)
        assert {nw._local_datetime(lo).year
                for lo, _hi in spy.history_calls} == {2026}
        await spy.close()

    @pytest.mark.asyncio
    async def test_morning_event_found_on_evening_tick(self, db,
                                                       monkeypatch):
        """T7: событие утром, тик вечером — сообщение доступно независимо
        от часа тика (окно — целый календарный день, не час тика)."""
        _worker_time(monkeypatch)
        await _msg(db, "утреннее событие", _ts_local(2026, 1, 15, 7))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["messages"] == 1
        assert "утреннее событие" in lines[0]

    @pytest.mark.asyncio
    async def test_feb29_anniversary_matched_on_leap_tick(self, db,
                                                          monkeypatch):
        """T6: исторический период включает 29 февраля — календарное
        сопоставление корректно (текущий день 29.02.2028, источник
        29.02.2024)."""
        tz = nw._zone(settings.SUMMARY_TIMEZONE)
        now_feb29 = int(datetime.datetime(2028, 2, 29, 12,
                                          tzinfo=tz).timestamp())
        await _msg(db, "редкий февральский день",
                   _ts_local(2024, 2, 29, 9))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, now_feb29)
        assert episodes and episodes[0]["year"] == 2024
        assert "редкий февральский день" in lines[0]

    @pytest.mark.asyncio
    async def test_cross_new_year_episode_not_cut(self, db, monkeypatch):
        """NOST-02.2: эпизод, переходящий через Новый год (обсуждение
        28.12.2025 → 01.01.2026, годовщина 2 января), собирается целиком;
        границы — фактические даты эпизода."""
        tz = nw._zone(settings.SUMMARY_TIMEZONE)
        now_jan2 = int(datetime.datetime(2027, 1, 2, 12,
                                         tzinfo=tz).timestamp())
        start = _ts_local(2025, 12, 28, 23)
        prev = await _msg(db, "собираемся на старый год", start, tg=1000)
        ts = start
        tg = 1000
        total = 1
        while ts < _ts_local(2026, 1, 1, 3):
            ts += 4 * 3600
            tg += 1
            total += 1
            prev = await _msg(db, f"продолжение праздника {ts}", ts,
                              reply_to=tg - 1, tg=tg)
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, now_jan2)
        assert episodes, "эпизод годовщины не найден"
        ep = episodes[0]
        assert ep["year"] == 2026
        assert ep["messages"] == total
        assert len(lines) == min(total, nw._EPISODE_LINES_MAX)
        assert ep["start_date"] == "2025-12-28"
        assert ep["end_date"] == "2026-01-01"
        assert "собираемся на старый год" in lines[0]

    @pytest.mark.asyncio
    async def test_far_from_anniversary_not_presented(self, db, monkeypatch):
        """Сообщения вне календарной близости к годовщине (20 дней) —
        повода нет: честное отсутствие (не подгонка ради кандидата)."""
        _worker_time(monkeypatch)
        await _msg(db, "случайное старое сообщение",
                   _ts_local(2026, 2, 4, 12))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes == [] and lines == []


# ═══ NOST-03: адаптивные временные окна ═════════════════════════════════════

class TestAdaptiveWindows:
    @pytest.mark.asyncio
    async def test_closed_episode_stays_base_level(self, db, monkeypatch):
        """Сегмент, закрытый внутри окна (нет связей за границу), не
        вызывает расширений: одна выборка, уровень day."""
        _worker_time(monkeypatch)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        await _msg(spy, "одиночная реплика дня", _ts_local(2026, 1, 15, 12))
        w = _worker(spy, monkeypatch=monkeypatch)
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["level"] == "day"
        assert len(spy.history_calls) == 1
        await spy.close()

    @pytest.mark.asyncio
    async def test_expands_week_on_edge_touching_reply_chain(self, db,
                                                             monkeypatch):
        """Reply-цепочка, упирающаяся в границу базового окна (день ± окно
        владельца), расширяется до недели; новые части за границей
        дооснащаются в тот же эпизод (NOST-03.1 уровень B)."""
        _worker_time(monkeypatch)
        # базовое окно (knob=1): 14.01 00:00 .. 17.01 00:00 локально;
        # цепочка 23:00 15.01 → ровно 17.01 00:00 (граница) — касается
        a = _ts_local(2026, 1, 15, 23)
        total, tg = await _chain(db, a, _ts_local(2026, 1, 17, 0),
                                 text="засиделись допоздна")
        # материал ЗА границей базового окна — достанется расширением недели
        await _msg(db, "и утром ещё вспоминали", _ts_local(2026, 1, 17, 5),
                   reply_to=tg, tg=tg + 1)
        await _msg(db, "финальное подведение", _ts_local(2026, 1, 17, 10),
                   reply_to=tg + 1, tg=tg + 2)
        w = _worker(db, monkeypatch=monkeypatch, values=dict(_KNOB_1))
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["level"] == "week"
        assert episodes[0]["messages"] == total + 2
        assert "засиделись допоздна" in lines[0]
        assert "финальное подведение" in lines[-1]

    @pytest.mark.asyncio
    async def test_expansion_stops_when_no_new_material(self, db,
                                                        monkeypatch):
        """Расширение останавливается, когда дальше сообщений нет
        (NOST-03.2 п.5): одна неделя — и тишина; выборок ровно две."""
        _worker_time(monkeypatch)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        a = _ts_local(2026, 1, 15, 23)
        await _chain(spy, a, _ts_local(2026, 1, 17, 0), text="шаг")
        w = _worker(spy, monkeypatch=monkeypatch, values=dict(_KNOB_1))
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes[0]["level"] == "week"
        assert len(spy.history_calls) == 2      # day + week, дальше нет
        await spy.close()

    @pytest.mark.asyncio
    async def test_month_level_for_multi_week_event(self, db, monkeypatch):
        """NOST-03.1 уровень C: событие длится больше недели (reply-цепочка
        с шагом ≤ горизонта 6ч) — окно расширяется до календарного месяца,
        включая связанные события на его границах."""
        _worker_time(monkeypatch)
        # базовое окно (knob=1): 14.01..17.01; неделя: 12.01..21.01
        # (±1д pad); цепочка до ровно 21.01 00:00 — касается конца недели
        a = _ts_local(2026, 1, 15, 23)
        total, tg = await _chain(db, a, _ts_local(2026, 1, 20, 0),
                                 text="шаг долгой истории")
        # материал за концом недели — достанется расширением месяца
        await _msg(db, "история докатилась до февраля?",
                   _ts_local(2026, 1, 20, 5), reply_to=tg, tg=tg + 1)
        w = _worker(db, monkeypatch=monkeypatch, values=dict(_KNOB_1))
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["level"] == "month"
        assert episodes[0]["messages"] == total + 1

    @pytest.mark.asyncio
    async def test_parallel_discussions_same_day_not_merged(self, db,
                                                            monkeypatch):
        """T13: два несвязанных обсуждения одного дня не объединяются
        (гэп > 30 минут, reply-связей нет) — эпизод один, из сегмента-
        повода."""
        _worker_time(monkeypatch)
        await _msg(db, "спор про футбол", _ts_local(2026, 1, 15, 10))
        await _msg(db, "обсуждение рецепта", _ts_local(2026, 1, 15, 15),
                   uid=77, name="Оля")
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["messages"] == 1
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_two_similar_events_not_one_story(self, db, monkeypatch):
        """T14: два разных события с тем же участником и похожей темой не
        становятся одной историей без подтверждённой связи."""
        _worker_time(monkeypatch)
        await _msg(db, "ездили на озеро в тот день",
                   _ts_local(2026, 1, 15, 10))
        await _msg(db, "вечером снова говорили про озеро",
                   _ts_local(2026, 1, 15, 18))
        w = _worker(db, monkeypatch=monkeypatch)
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes[0]["messages"] == 1

    @pytest.mark.asyncio
    async def test_expansion_cap_is_terminal(self, db, monkeypatch):
        """Потолок продолжения терминален (уровень D): цепочка через весь
        месяц останавливается на уровне month; число выборок ограничено
        (NOST-11: не чтение всего архива на каждый тик)."""
        _worker_time(monkeypatch)
        monkeypatch.setattr(nw, "_HISTORY_CONTINUATION_MAX", 0)
        spy = _SpyDB(":memory:")
        await spy.initialize()
        a = _ts_local(2026, 1, 15, 23)
        await _chain(spy, a, _ts_local(2026, 2, 1, 23), text="продолжение")
        w = _worker(spy, monkeypatch=monkeypatch, values=dict(_KNOB_1))
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["level"] == "month"
        assert len(spy.history_calls) <= 3      # day + week + month, стоп
        await spy.close()

    @pytest.mark.asyncio
    async def test_window_truncation_flagged_honestly(self, db, monkeypatch):
        """Усечение окна лимитом — честный признак в карточке (NOST-11.3:
        LIMIT не создаёт незаметного смещения)."""
        _worker_time(monkeypatch)
        monkeypatch.setattr(nw, "_WINDOW_FETCH_LIMIT", 3)
        for i in range(5):
            await _msg(db, f"много сообщений {i}",
                       _ts_local(2026, 1, 15, 12, i))
        w = _worker(db, monkeypatch=monkeypatch)
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes and episodes[0]["truncated"] is True


# ═══ NOST-04: эпизод вместо отдельного сообщения ════════════════════════════

class TestEpisodeReconstruction:
    @pytest.mark.asyncio
    async def test_reply_chain_three_messages_one_episode(self, db,
                                                          monkeypatch):
        """T9/T15: диалог из трёх сообщений (reply-связи, разнесённые по
        времени в пределах горизонта) собирается в один эпизод; связи не
        теряются."""
        _worker_time(monkeypatch)
        t0 = _ts_local(2026, 1, 15, 10)
        id1 = await _msg(db, "поехали на озеро", t0, tg=1000)
        id2 = await _msg(db, "кто за?", t0 + 1800, reply_to=1000, tg=1001)
        await _msg(db, "все за, выезжаем в шесть", t0 + 3600,
                   reply_to=1001, tg=1002)
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes[0]["messages"] == 3
        assert len(lines) == 3
        assert lines[0].endswith(": поехали на озеро")

    @pytest.mark.asyncio
    async def test_single_message_episode_is_valid(self, db, monkeypatch):
        """T8: самодостаточное сообщение дня — полноценный кандидат
        (обязательного минимума сообщений нет, NOST-04)."""
        _worker_time(monkeypatch)
        await _msg(db, "характерная реплика на весь год",
                   _ts_local(2026, 1, 15, 9))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes[0]["messages"] == 1
        assert "характерная реплика" in lines[0]

    @pytest.mark.asyncio
    async def test_lines_cap_head_plus_tail_keeps_arc(self, db, monkeypatch):
        """Длинный эпизод: кап строк — голова+хвост (начало и финал истории
        сохранены), полный счётчик — в карточке (честная диагностика)."""
        _worker_time(monkeypatch)
        t0 = _ts_local(2026, 1, 15, 10)
        prev = await _msg(db, "начало переписки", t0)
        for i in range(19):                    # ещё 19 → сегмент 20 строк
            prev = await _msg(db, f"реплика номер {i}", t0 + 60 * (i + 1),
                              reply_to=prev)
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        ep = episodes[0]
        assert ep["messages"] == 20
        assert len(lines) == nw._EPISODE_LINES_MAX
        assert "начало переписки" in lines[0]
        # голова+хвост: последние 6 строк — хвост сегмента (финал истории)
        assert "реплика номер 18" in lines[-1]

    @pytest.mark.asyncio
    async def test_episode_lines_have_no_time_of_day(self, db, monkeypatch):
        """NOST-02.2: рендер строки не утверждает час события — только
        дата (время публикации не выдаётся за время происшествия)."""
        _worker_time(monkeypatch)
        await _msg(db, "сообщение днём", _ts_local(2026, 1, 15, 14, 59))
        w = _worker(db, monkeypatch=monkeypatch)
        lines, _episodes = await w._historical_lines(CHAT_ID, NOW)
        assert len(lines) == 1
        head = lines[0].split("]:")[0]
        assert ":" not in head                 # в голове строки нет часов

    @pytest.mark.asyncio
    async def test_multi_year_episodes_in_llm_block(self, db, monkeypatch):
        """NOST-04: пул из нескольких лет попадает в user-блок LLM блоками
        эпизодов с честными заголовками годов и датами."""
        _worker_time(monkeypatch)
        await _msg(db, "январь две тысячи двадцать третьего",
                   _ts_local(2023, 1, 15, 12))
        await _msg(db, "январь две тысячи двадцать пятого",
                   _ts_local(2025, 1, 15, 12))
        w = _worker(db, monkeypatch=monkeypatch)
        year_lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        from services.nostalgia_prompts import build_nostalgia_user
        user = build_nostalgia_user(year_lines, [], episodes=episodes)
        assert "Эпизоды из истории чата за прошлые годы:" in user
        assert "2 года назад" in user
        assert "4 года назад" in user
        assert "январь две тысячи двадцать третьего" in user


# ═══ NOST-07: источники и историческая достоверность ════════════════════════

class TestTruthfulness:
    @pytest.mark.asyncio
    async def test_bot_own_rows_excluded_from_history(self, db):
        """NOST-07.2 self-echo: собственные ответы бота не становятся
        историческим свидетельством (SQL-фильтр user_id != bot_id)."""
        ts = _ts_local(2026, 1, 15, 12)
        await _msg(db, "реплика участника", ts)
        await _msg(db, "старый ответ бота", ts + 60, uid=BOT_ID, name="Bot")
        rows = await db.get_chat_history_messages(CHAT_ID, ts - 3600,
                                                  ts + 3600, 100, BOT_ID)
        assert [r["text"] for r in rows] == ["реплика участника"]

    @pytest.mark.asyncio
    async def test_forward_label_inside_episode(self, db, monkeypatch):
        """NOST-07.1/T24: репост новости внутри эпизода помечен «Переслано:
        источник»; обсуждение новости участниками — полноценное событие
        чата (T25)."""
        _worker_time(monkeypatch)
        t0 = _ts_local(2026, 1, 15, 10)
        id1 = await _msg(db, "Вера Косачева умерла за 300 метров", t0,
                         is_forward=True, forward_source="Спорт-Новости",
                         tg=1000)
        await _msg(db, "вы это видели?", t0 + 600, reply_to=1000, tg=1001)
        w = _worker(db, monkeypatch=monkeypatch)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert any("| Переслано: Спорт-Новости]" in l for l in lines)
        assert episodes[0]["messages"] == 2

    @pytest.mark.asyncio
    async def test_identity_by_uid_alias_priority(self, db, monkeypatch):
        """NOST-07.3/T26: актуальный алиас по Telegram user_id приоритетнее
        исторического author_name; текст исторического сообщения не
        переписывается."""
        _worker_time(monkeypatch)
        await _msg(db, "старая реплика со старым именем",
                   _ts_local(2026, 1, 15, 12), uid=USER_ID, name="СтарыйВася")
        w = _worker(db, monkeypatch=monkeypatch, values={
            "memory.nostalgia_enabled": True,
            "limits.summary_aliases": json.dumps({str(USER_ID): "Вася"}),
        })
        lines, _episodes = await w._historical_lines(CHAT_ID, NOW)
        assert lines[0].startswith("[Вася ")
        assert "СтарыйВася" not in lines[0]
        assert lines[0].endswith(": старая реплика со старым именем")

    @pytest.mark.asyncio
    async def test_two_users_same_display_name_not_merged(self, db,
                                                          monkeypatch):
        """T27: два участника с одинаковым именем не объединяются —
        идентичность по uid; сегментация различает авторов."""
        _worker_time(monkeypatch)
        await _msg(db, "первый вася пишет", _ts_local(2026, 1, 15, 10))
        await _msg(db, "второй вася пишет", _ts_local(2026, 1, 15, 11),
                   uid=77, name="Вася")
        w = _worker(db, monkeypatch=monkeypatch)
        _lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert episodes[0]["messages"] == 1

    @pytest.mark.asyncio
    async def test_insufficient_data_honest_silence(self, db, monkeypatch):
        """T19: только разрозненные случайные сообщения вне годовщин —
        исторического кандидата нет, LLM не вызывается, honest skip
        (без вымысла, NOST-07.4)."""
        _worker_time(monkeypatch)
        llm = _FakeLLM("SAY\nвыдумка")
        await _msg(db, "случайный факт без повода", NOW - 200 * 86400)
        await _msg(db, "ещё один разрозненный факт", NOW - 100 * 86400)
        w = _worker(db, llm, monkeypatch=monkeypatch, values={
            "memory.nostalgia_enabled": True,
            "memory.nostalgia_min_silence_minutes": 0,
        })
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert llm.calls == []                  # отказа-вымысла не будет
        cursor = await db.db.execute(
            "SELECT meta FROM nostalgia_log WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT 1", (CHAT_ID,))
        row = await cursor.fetchone()
        assert json.loads(row["meta"])["reason"] == "no_candidates"
        assert out["sent"] == 0

    @pytest.mark.asyncio
    async def test_llm_decline_typed_verdict_silence(self, db, monkeypatch):
        """NOST-01/T23: модель отказалась (вердикт UNCHANGED) — в чат не
        уходит ничего, включая объяснение отказа."""
        _worker_time(monkeypatch)
        await _msg(db, "слабый кандидат годовщины",
                   _ts_local(2026, 1, 15, 12))
        llm = _FakeLLM("UNCHANGED")
        bot = _FakeBot()
        w = _worker(db, llm, monkeypatch=monkeypatch, values={
            "memory.nostalgia_enabled": True,
            "memory.nostalgia_min_silence_minutes": 0,
        })
        out = await w._process_chat(CHAT_ID, NOW, manual=True)
        assert bot.calls == [] and out["sent"] == 0
        cursor = await db.db.execute(
            "SELECT meta FROM nostalgia_log WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT 1", (CHAT_ID,))
        row = await cursor.fetchone()
        assert json.loads(row["meta"])["reason"] == "unchanged"

    def test_parse_verdict_not_word_matching(self):
        """NOST-16: парсер — протокольный маркер первой строки, не смысловой
        поиск слов: произвольные имена/даты/темы контента не влияют."""
        assert parse_nostalgia_answer(
            "SAY\nКосачева, 300 метров, тромбы — любой контент")[0] == "say"
        assert parse_nostalgia_answer("UNCHANGED")[0] == "unchanged"
        assert parse_nostalgia_answer(
            "любой другой текст с любыми именами")[0] == "legacy"
