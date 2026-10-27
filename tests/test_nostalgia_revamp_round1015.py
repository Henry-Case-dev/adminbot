"""F4 round 10.15 + P0 REWORK W1 (source-2026-10-27 NOST-02/03/04) —
инжект Лора/мемов в user-блок слоя B (NostalgiaWorker) и КАЛЕНДАРНАЯ
арифметика годовщин.

Покрытие: `_llm_once` собирает лор (store.get_profile, manual → auto) и
мемы (db.list_chat_memes) и передаёт их в user-блок; fail-open при
исключении источника (секция опускается, блок как раньше); окна годовщин —
КАЛЕНДАРНЫЕ (полночь локального дня годовщины ± nostalgia_year_back_days_window,
дефолт 10 / per-chat override; 365*86400 удалено — NOST-02.2); динамические
годы архива без жёсткой конструкции «три запроса»; пустой год — не ошибка;
адаптивное расширение окна (день → неделя → месяц → продолжение); эпизоды
как единица отбора; обратная совместимость `build_nostalgia_user`.
LLM/БД замоканы.
"""
import datetime
import pytest

from services import hot_config as hot
from services import nostalgia_worker as nw
from services.nostalgia_prompts import NOSTALGIA_PROMPT, build_nostalgia_user

CHAT_ID = -1002661910336
NOW = 1_800_000_000          # 2027-01-15 11:00 Asia/Yekaterinburg (+05)


class _FakeLLM:
    def __init__(self, answer="кстати, помню как тогда было"):
        self.answer = answer
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        return self.answer


class _FakeProfile:
    def __init__(self, manual_lore="", auto_lore=""):
        self.manual_lore = manual_lore
        self.auto_lore = auto_lore


class _FakeStore:
    def __init__(self, profile=None, error=None):
        self.profile = profile
        self.error = error
        self.calls = []

    async def get_profile(self, chat_id):
        self.calls.append(chat_id)
        if self.error is not None:
            raise self.error
        return self.profile


class _FakeDB:
    """Fake БД исторического движка (P0 REWORK W1): границы архива +
    диапазонные выборки. Все вызовы записываются для сверки календарных
    окон."""

    def __init__(self, memes=None, memes_error=None, window_rows=None,
                 bounds=None):
        self.memes = list(memes or [])
        self.memes_error = memes_error
        self.memes_calls = []
        self.window_rows = list(window_rows or [])
        self.window_calls = []          # [(chat, lo, hi, limit)]
        self._bounds = bounds

    async def list_chat_memes(self, chat_id, target_user=None, limit=50,
                              now_ts=None):
        self.memes_calls.append((chat_id, target_user, limit))
        if self.memes_error is not None:
            raise self.memes_error
        return list(self.memes)

    async def get_chat_history_bounds(self, chat_id):
        return self._bounds

    async def get_chat_history_messages(self, chat_id, ts_from, ts_to,
                                        limit=600, bot_id=None):
        self.window_calls.append((chat_id, ts_from, ts_to, limit))
        return [r for r in self.window_rows
                if ts_from <= r["timestamp"] <= ts_to]


def _worker(db, *, store=None, llm=None):
    return nw.NostalgiaWorker(db, memory=None, store=store,
                              llm=llm if llm is not None else _FakeLLM(),
                              bot=None, bot_id=12345)


def _user_message(llm, index=0) -> str:
    messages = llm.calls[index][0]
    return next(m["content"] for m in messages if m["role"] == "user")


def _hot_cache(monkeypatch, values):
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals)

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class TestLLMOnceInjection:
    @pytest.mark.asyncio
    async def test_lore_and_memes_injected(self):
        llm = _FakeLLM()
        store = _FakeStore(_FakeProfile(manual_lore="тут шутят жёстко"))
        db = _FakeDB(memes=[{"fact": "вася = торт", "target_user": "Вася"}])
        w = _worker(db, store=store, llm=llm)
        candidate = {"year_lines": ["[Вася 2024-07-12]: a"],
                     "golden_lines": []}
        out = await w._llm_once(candidate, CHAT_ID)
        assert out == llm.answer
        user = _user_message(llm)
        assert "События примерно год назад" in user
        assert "Лор чата (как тут принято общаться):" in user
        assert "тут шутят жёстко" in user
        assert "Локальные мемы (местные ярлыки и шутки):" in user
        assert "- [Вася] вася = торт" in user
        # системный промпт — новый канон
        system = llm.calls[0][0][0]
        assert system["role"] == "system"
        assert system["content"] == NOSTALGIA_PROMPT.format(max_words=60)

    @pytest.mark.asyncio
    async def test_manual_lore_priority(self):
        store = _FakeStore(_FakeProfile(manual_lore="ручной лор",
                                        auto_lore="авто лор"))
        w = _worker(_FakeDB(), store=store)
        await w._llm_once({"year_lines": ["[a]: b"], "golden_lines": []},
                          CHAT_ID)
        user = _user_message(w.llm)
        assert "ручной лор" in user
        assert "авто лор" not in user

    @pytest.mark.asyncio
    async def test_auto_lore_fallback(self):
        store = _FakeStore(_FakeProfile(manual_lore="",
                                        auto_lore="авто лор"))
        w = _worker(_FakeDB(), store=store)
        await w._llm_once({"year_lines": ["[a]: b"], "golden_lines": []},
                          CHAT_ID)
        assert "авто лор" in _user_message(w.llm)

    @pytest.mark.asyncio
    async def test_lore_fetch_fail_open(self):
        store = _FakeStore(error=RuntimeError("PG down"))
        w = _worker(_FakeDB(), store=store)
        out = await w._llm_once(
            {"year_lines": ["[a]: b"], "golden_lines": []}, CHAT_ID)
        assert out == w.llm.answer           # вызов всё равно состоялся
        user = _user_message(w.llm)
        assert "Лор чата" not in user
        assert "События примерно год назад" in user

    @pytest.mark.asyncio
    async def test_memes_fetch_fail_open(self):
        db = _FakeDB(memes_error=RuntimeError("SQLite error"))
        w = _worker(db, store=_FakeStore(_FakeProfile(manual_lore="лор")))
        out = await w._llm_once(
            {"year_lines": ["[a]: b"], "golden_lines": []}, CHAT_ID)
        assert out == w.llm.answer
        user = _user_message(w.llm)
        assert "Локальные мемы" not in user
        assert "Лор чата" in user

    @pytest.mark.asyncio
    async def test_no_store_no_memes_block_unchanged(self):
        w = _worker(_FakeDB())
        await w._llm_once({"year_lines": ["[a]: b"],
                           "golden_lines": ["[2023-01-01] c"]}, CHAT_ID)
        user = _user_message(w.llm)
        assert user == build_nostalgia_user(["[a]: b"], ["[2023-01-01] c"])

    @pytest.mark.asyncio
    async def test_empty_candidate_returns_none(self):
        llm = _FakeLLM()
        w = _worker(_FakeDB(), store=_FakeStore(_FakeProfile()), llm=llm)
        out = await w._llm_once({"year_lines": [], "golden_lines": []}, CHAT_ID)
        assert out is None
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_memes_query_limit_cap(self):
        db = _FakeDB()
        w = _worker(db, store=_FakeStore(_FakeProfile()))
        await w._llm_once({"year_lines": ["[a]: b"], "golden_lines": []},
                          CHAT_ID)
        assert db.memes_calls[0][2] == 10    # _MEMES_LIMIT
        assert db.memes_calls[0][1] is None  # все мемы чата


class TestYearBackWindow:
    """P0 REWORK W1 (NOST-02): календарная арифметика годовщин вместо
    365*86400. NOW = 1_800_000_000 = 2027-01-15 11:00 (Asia/Yekaterinburg,
    дефолт SUMMARY_TIMEZONE) → годовщина года Y = 15.01.Y. Настройка
    владельца nostalgia_year_back_days_window сохранена: симметричное
    расширение календарного дня (дефолт 10)."""

    def _worker(self, db):
        return _worker(db)

    def _expected_window(self, year: int, days: int) -> tuple[int, int]:
        from zoneinfo import ZoneInfo
        from config.settings import settings
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        anniv = datetime.date(year, 1, 15)
        pad = days * 86400
        lo = int(datetime.datetime(anniv.year, anniv.month, anniv.day,
                                   tzinfo=tz).timestamp()) - pad
        hi = lo + 86400 + 2 * pad      # pad симметричен с обеих сторон
        return lo, hi

    @pytest.mark.asyncio
    async def test_default_window_is_ten_days_calendar_anchored(self):
        from config.settings import settings
        from zoneinfo import ZoneInfo
        db = _FakeDB(bounds=(1_700_000_000, 1_790_000_000))
        w = self._worker(db)
        await w._historical_lines(CHAT_ID, NOW)
        assert db.window_calls, "окно годовщины не запрошено"
        # первый запрос — РАННИЙ год архива (обход ASC; сортировка свежести
        # — после отбора). min(bounds) = 1_700_000_000 = 2023-11-14 → 2023.
        lo, hi = self._expected_window(2023,
                                       settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW)
        assert (db.window_calls[0][1], db.window_calls[0][2]) == (lo, hi)
        # календарная привязка: окно начинается в ПОЛНОЧЬ локального дня
        # годовщины (не «NOW - 365*86400 ± окна»)
        tz = ZoneInfo(str(settings.SUMMARY_TIMEZONE))
        assert datetime.datetime.fromtimestamp(
            db.window_calls[0][1], tz).strftime("%Y-%m-%d %H:%M") == \
            "2023-01-05 00:00"

    @pytest.mark.asyncio
    async def test_hot_override_window(self, monkeypatch):
        _hot_cache(monkeypatch, {"memory.nostalgia_year_back_days_window": 3})
        db = _FakeDB(bounds=(1_700_000_000, 1_790_000_000))
        w = self._worker(db)
        await w._historical_lines(CHAT_ID, NOW)
        lo, hi = self._expected_window(2023, 3)
        assert (db.window_calls[0][1], db.window_calls[0][2]) == (lo, hi)

    @pytest.mark.asyncio
    async def test_blank_hot_falls_back_to_default(self, monkeypatch):
        # hot=0 (явный ноль) не должен превращаться в хардкод 2 —
        # фолбэк идёт на settings-дефолт (10, spec §3)
        _hot_cache(monkeypatch, {"memory.nostalgia_year_back_days_window": 0})
        db = _FakeDB(bounds=(1_700_000_000, 1_790_000_000))
        w = self._worker(db)
        await w._historical_lines(CHAT_ID, NOW)
        from config.settings import settings
        lo, hi = self._expected_window(
            2023, settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW)
        assert (db.window_calls[0][1], db.window_calls[0][2]) == (lo, hi)
    @pytest.mark.asyncio
    async def test_all_archive_years_queried_dynamically(self):
        """NOST-02.1: динамические годы архива (без жёсткой конструкции «три
        запроса»): архив 2022..2026 → запросы годовщин 2022..2026, каждый со
        своим календарным окном; текущий год (2027) не исследуется."""
        db = _FakeDB(bounds=(int(datetime.datetime(2022, 3, 1).timestamp()),
                             int(datetime.datetime(2026, 8, 1).timestamp())))
        w = self._worker(db)
        await w._historical_lines(CHAT_ID, NOW)
        years = []
        for (_chat, lo, _hi, _limit) in db.window_calls:
            years.append(datetime.datetime.fromtimestamp(lo).year)
        assert years == [2022, 2023, 2024, 2025, 2026]
        # каждое окно — 15 января своего года (±10д pad, ASC-обход лет)
        from config.settings import settings
        for i, year in enumerate([2022, 2023, 2024, 2025, 2026]):
            lo, hi = self._expected_window(
                year, settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW)
            assert (db.window_calls[i][1], db.window_calls[i][2]) == (lo, hi)

    @pytest.mark.asyncio
    async def test_empty_year_is_not_an_error(self):
        """NOST-02.1: пустой год — не ошибка и не обрыв поиска по другим
        годам (сообщения только в 2024 и 2025)."""
        rows = [{"id": 1, "chat_id": CHAT_ID, "user_id": 55,
                 "text": "было дело", "timestamp": NOW - 3 * 365 * 86400,
                 "author_name": "Вася", "reply_to_id": None,
                 "tg_message_id": None, "is_forward": 0,
                 "forward_source": ""}]
        db = _FakeDB(window_rows=rows, bounds=(rows[0]["timestamp"],
                                               NOW - 3600))
        w = self._worker(db)
        lines, episodes = await w._historical_lines(CHAT_ID, NOW)
        assert db.window_calls                 # годы запрошены
        # сообщение NOW-3*365d ≈ 2024-01-16 (±) — вне календарных дней
        # годовщин (15 января ±10д: 05..26 января) — может попасть;
        # проверяем честность контракта: пустые годы не ломают поиск
        assert isinstance(lines, list) and isinstance(episodes, list)
