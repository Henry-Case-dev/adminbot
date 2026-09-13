"""F4 round 10.15 (nostalgia-prompt-revamp-round1015) — окно «год назад»
±2→±10 и инжект Лора/мемов в user-блок слоя B (NostalgiaWorker).

Покрытие: `_llm_once` собирает лор (store.get_profile, manual → auto) и
мемы (db.list_chat_memes) и передаёт их в user-блок; fail-open при
исключении источника (секция опускается, блок как раньше); окно кандидатов
центрировано на «год назад» и равно ±10 дней (дефолт) / per-chat override;
обратная совместимость `build_nostalgia_user`. LLM/БД замоканы.
"""
import pytest

from services import hot_config as hot
from services import nostalgia_worker as nw
from services.nostalgia_prompts import NOSTALGIA_PROMPT, build_nostalgia_user

CHAT_ID = -1002661910336
NOW = 1_800_000_000
_YEAR = 365 * 86400


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
    def __init__(self, memes=None, memes_error=None, window_rows=None):
        self.memes = list(memes or [])
        self.memes_error = memes_error
        self.memes_calls = []
        self.window_rows = list(window_rows or [])
        self.window_calls = []

    async def list_chat_memes(self, chat_id, target_user=None, limit=50,
                              now_ts=None):
        self.memes_calls.append((chat_id, target_user, limit))
        if self.memes_error is not None:
            raise self.memes_error
        return list(self.memes)

    async def get_year_back_messages(self, chat_id, ts_from, ts_to, center_ts,
                                     limit=3):
        self.window_calls.append((chat_id, ts_from, ts_to, center_ts, limit))
        return list(self.window_rows)


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
    def _worker(self, db):
        return _worker(db)

    @pytest.mark.asyncio
    async def test_default_window_is_ten_days(self):
        db = _FakeDB()
        w = self._worker(db)
        await w._year_back_lines(CHAT_ID, NOW)
        chat, lo, hi, center, limit = db.window_calls[0]
        assert chat == CHAT_ID
        assert center == NOW - _YEAR
        assert lo == center - 10 * 86400
        assert hi == center + 10 * 86400

    @pytest.mark.asyncio
    async def test_hot_override_window(self, monkeypatch):
        _hot_cache(monkeypatch, {"memory.nostalgia_year_back_days_window": 3})
        db = _FakeDB()
        w = self._worker(db)
        await w._year_back_lines(CHAT_ID, NOW)
        _chat, lo, hi, center, _limit = db.window_calls[0]
        assert lo == center - 3 * 86400
        assert hi == center + 3 * 86400

    @pytest.mark.asyncio
    async def test_blank_hot_falls_back_to_default(self, monkeypatch):
        # hot=0 (явный ноль) не должен превращаться в хардкод 2 —
        # фолбэк идёт на settings-дефолт (10, spec §3).
        _hot_cache(monkeypatch, {"memory.nostalgia_year_back_days_window": 0})
        db = _FakeDB()
        w = self._worker(db)
        await w._year_back_lines(CHAT_ID, NOW)
        _chat, lo, hi, center, _limit = db.window_calls[0]
        assert hi - center == 10 * 86400
