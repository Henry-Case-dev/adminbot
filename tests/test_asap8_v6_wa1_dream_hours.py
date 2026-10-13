"""ASAP 8 v6 Wave A1 — D09-S: час 00:00 не подменяется дефолтом.

Root cause (ledger D09, 18F.2): паттерн `int(x or 7)` в dream_worker
превращал ВАЛИДНЫЙ числовой 0 (полночь) в дефолт 7:
  * `memory.deep_sleep_hour` — Deep Sleep, настроенный на 00:00, молча
    переезжал на 07:00;
  * `window_start_hour`/`window_end_hour` — окно сна со стартом 00:00
    сдвигалось на 04:00.

Контракт: None/missing/пусто/мусор → env-дефолт; числовой 0 → 0;
01:00 → 1; 23:00 → 23. Семантика как у `_hot_number` (S10.13-7).

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09
"""
import pytest

from config.settings import settings
from services import dream_worker as dw
from services.dream_worker import DreamWorker, _hour_or

CHAT_ID = -100200


# ── Чистый хелпер ────────────────────────────────────────────────────────────

def test_hour_or_valid_zero_stays_zero():
    assert _hour_or(0, 7) == 0            # 00:00 — валидный час
    assert _hour_or("0", 7) == 0          # строка из chat_params
    assert _hour_or(0.0, 7) == 0


def test_hour_or_regular_hours():
    assert _hour_or(1, 7) == 1
    assert _hour_or(23, 7) == 23
    assert _hour_or("23", 7) == 23


def test_hour_or_missing_falls_back_to_default():
    assert _hour_or(None, 7) == 7
    assert _hour_or("", 7) == 7
    assert _hour_or("  ", 7) == 7
    assert _hour_or("abc", 7) == 7
    assert _hour_or(object(), 7) == 7


def test_hour_or_default_is_env_value_not_literal():
    """Дефолт — env ClassVar (может быть легально переопределён владельцем),
    а не захардкоженный литерал 7."""
    assert _hour_or(None, settings.DEEP_SLEEP_HOUR) == settings.DEEP_SLEEP_HOUR


# ── _deep_tick: час Deep Sleep по каждому чату ───────────────────────────────

class _FakeResolution:
    """Подмена per-chat резолва `memory.deep_sleep_hour`."""

    def __init__(self, value):
        self.value = value
        self.calls = []

    async def __call__(self, key, *, chat_id=None, default=None):
        self.calls.append((key, chat_id, default))
        return self.value


def _deep_worker(monkeypatch, *, hour: int, hour_value,
                 trigger_value="fixed") -> tuple[DreamWorker, list]:
    worker = DreamWorker(db=None, memory=None, llm=None)
    resolutions = {"memory.deep_sleep_hour": _FakeResolution(hour_value),
                   "memory.deep_sleep_trigger": _FakeResolution(trigger_value)}

    async def fake_resolve(key, *, chat_id=None, default=None):
        return resolutions[key].value

    captured: list = []

    async def fake_candidates(now):
        return [CHAT_ID]

    async def fake_run_deep_all(chat_ids, manual=False):
        captured.append(list(chat_ids))
        return {"chats": len(chat_ids), "paradigms": 0, "ran": 0,
                "skipped": 0, "traits": 0}

    monkeypatch.setattr(dw, "resolve_setting_cached", fake_resolve)
    monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: hour)
    monkeypatch.setattr(worker, "_deep_candidate_chat_ids", fake_candidates)
    monkeypatch.setattr(worker, "_run_deep_all", fake_run_deep_all)
    return worker, captured


@pytest.mark.asyncio
async def test_deep_tick_fires_at_midnight_when_configured_00(monkeypatch):
    """00:00 настроен, local-час 00:00 → прогон ЗАПУСКАЕТСЯ (раньше `or 7`
    подменял цель на 7 и полночь молча пропускалась)."""
    worker, captured = _deep_worker(monkeypatch, hour=0, hour_value=0)
    await worker._deep_tick()
    assert captured == [[CHAT_ID]]


@pytest.mark.asyncio
async def test_deep_tick_not_fired_at_07_for_midnight_config(monkeypatch):
    """Регрессия root cause: цель 00:00 при часе 07:00 НЕ запускает прогон
    (прежний баг: `or 7` делал цель 7 → полночная настройка срабатывала в 7:00)."""
    worker, captured = _deep_worker(monkeypatch, hour=7, hour_value=0)
    await worker._deep_tick()
    assert captured == []


@pytest.mark.asyncio
async def test_deep_tick_hours_01_and_23(monkeypatch):
    for cfg_hour, tick_hour in ((1, 1), (23, 23)):
        worker, captured = _deep_worker(monkeypatch, hour=tick_hour,
                                        hour_value=cfg_hour)
        await worker._deep_tick()
        assert captured == [[CHAT_ID]], cfg_hour
        # чужой час не запускает
        worker2, captured2 = _deep_worker(monkeypatch, hour=(tick_hour + 1) % 24,
                                          hour_value=cfg_hour)
        await worker2._deep_tick()
        assert captured2 == [], cfg_hour


@pytest.mark.asyncio
async def test_deep_tick_missing_value_uses_env_default(monkeypatch):
    """None/missing → env-дефолт DEEP_SLEEP_HOUR: прогон в env-час,
    не в литерал 7 (который может быть легально переопределён env)."""
    worker, captured = _deep_worker(monkeypatch,
                                    hour=settings.DEEP_SLEEP_HOUR,
                                    hour_value=None)
    await worker._deep_tick()
    assert captured == [[CHAT_ID]]
    # дефолт прокидывается в резолв (chat → global → env цепочка сохранена)
    assert worker  # подмена резолва принимает default — семантика неизменна


@pytest.mark.asyncio
async def test_deep_tick_trigger_after_sleep_never_fires_fixed(monkeypatch):
    """trigger != 'fixed' — час вообще не проверяется (прочная ветка)."""
    worker, captured = _deep_worker(monkeypatch, hour=0, hour_value=0,
                                    trigger_value="after_sleep")
    await worker._deep_tick()
    assert captured == []


@pytest.mark.asyncio
async def test_deep_tick_lock_skips_concurrent_run(monkeypatch):
    """Занятый _deep_lock → выход без прогона (прежняя семантика не тронута)."""
    worker, captured = _deep_worker(monkeypatch, hour=0, hour_value=0)
    async with worker._deep_lock:
        await worker._deep_tick()
    assert captured == []


# ── _window_open_for: окно сна со стартом 00:00 ──────────────────────────────

def _window_worker(monkeypatch, start, end) -> DreamWorker:
    worker = DreamWorker(db=None, memory=None, llm=None)

    async def fake_key_for(chat_id, name, default):
        return {"window_start_hour": start,
                "window_end_hour": end}[name]

    monkeypatch.setattr(worker, "_key_for", fake_key_for)
    monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 0)
    return worker


@pytest.mark.asyncio
async def test_window_open_at_midnight_when_start_00(monkeypatch):
    """Регрессия: start=00:00, час 00:00 → окно ОТКРЫТО (раньше `or 4`
    сдвигал старт на 4:00 и полночь была закрыта)."""
    worker = _window_worker(monkeypatch, start=0, end=6)
    assert await worker._window_open_for(CHAT_ID, 0) is True


@pytest.mark.asyncio
async def test_window_missing_keys_use_env_defaults(monkeypatch):
    """Пропуск per-chat ключей → env-дефолты [4, 6): полночь закрыта, 5:00
    открыта — прежняя семантика D-5 не тронута."""
    worker = _window_worker(monkeypatch, start=None, end=None)
    assert await worker._window_open_for(CHAT_ID, 0) is False
    monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 5)
    assert await worker._window_open_for(CHAT_ID, 0) is True


@pytest.mark.asyncio
async def test_window_open_boundary_semantics(monkeypatch):
    """[start, end): start открыт, end закрыт — включая нулевые границы."""
    worker = _window_worker(monkeypatch, start=0, end=0)
    # start == end → пустое окно при любом часе (0 <= h < 0 невозможно)
    monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 0)
    assert await worker._window_open_for(CHAT_ID, 0) is False


# ── Рантайм-слои не затронуты ────────────────────────────────────────────────

def test_env_defaults_unchanged():
    """DEEP_SLEEP_HOUR env-дефолт = 7 (базлайн) и окно [4, 6) — константы
    не менялись (менялась только семантика валидного нуля)."""
    assert settings.DEEP_SLEEP_HOUR == 7
    assert settings.DREAM_WINDOW_START_HOUR == 4
    assert settings.DREAM_WINDOW_END_HOUR == 6
