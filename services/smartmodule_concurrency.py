"""Параллельность smart module — per-chat пул семафоров (T-839, T-840, T-841).

Заменяет строгую сериализацию LLM-генераций на per-chat пул:
  * direct_chat: per-chat asyncio.Lock (Epic 60, 63.2, T-461) → N семафоров
    на чат (R60-2-семантика сохраняется при limits.smartmodule_concurrency_per_chat=1);
  * SummaryGenerator: глобальный asyncio.Lock (A5) → пул per-chat — чат A
    больше не блокирует чат B;
  * хендлеры search/factcheck/web/checkup/youtube (LLM-ветки) — те же N слотов.

N читается при создании слота из
hot.get("limits.smartmodule_concurrency_per_chat", settings.SMARTMODULE_CONCURRENCY_PER_CHAT);
1 = строгая очередь (как раньше). Смена N под живьём → слот пересоздаётся с новым
N (старый sem осиротевает; его держатели доrelease доживают на нём — ок).

НЕ трогаем: VoiceTranscriber (SmartModule/service.py) — его глобальный
asyncio.Semaphore (Epic 79.5, D295) защищает провайдера STT (Groq Free Tier),
а не чат-очередь; youtube-медиа-ветки транскрипции (STT) — тоже вне пула.
"""
import asyncio
import logging

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_CONCURRENCY_KEY = "limits.smartmodule_concurrency_per_chat"
_WAIT_KEY = "limits.smartmodule_concurrency_wait_seconds"

# Ключ-дефолт числа слотов в пуле; переопределяется из env/REGISTRY.
_DEFAULT_MAX_ENTRIES = 256


class _Slot:
    """Слот чата: семафор + N, с которым создан + счётчик ожидантов (анти-гонка
    чистки: pending>0 — корутина вышла из guard, но ещё не вошла в acquire)."""

    __slots__ = ("sem", "n", "pending")

    def __init__(self, sem: asyncio.Semaphore, n: int) -> None:
        self.sem = sem
        self.n = n
        self.pending = 0


class _Permit:
    """Пропуск на одну генерацию (пара семафором). release — строго один раз."""

    __slots__ = ("_sem", "_released")

    def __init__(self, sem: asyncio.Semaphore) -> None:
        self._sem = sem
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._sem.release()


class ChatConcurrencyPool:
    """Per-chat пул семафоров LLM-генераций smart module.

    __init__: max_entries=256 — потолок словаря слотов (ленивая чистка
    свободных при переполнении — перенос паттерна T-501 с per-chat замков
    direct_chat на семафоры).

    API:
      * try_acquire(chat_id, timeout=None) -> _Permit | None
          — ждёт слот чата; None = таймаут истёк (вызывающий сам решает:
          busy-фраза/лог). timeout=None → ждать сколько нужно (как раньше
          async with lock); таймаутом управляет вызывающий через asyncio.timeout
          поверх acquire (сохраняет busy-семантику мест вызова).
      * acquire(chat_id) -> _Permit — ждать без таймаута (удобный алиас).
      * release делает permit.release() (см. _Permit).

    Слот лениво создаётся под _guard при первом обращении к чату; N читается
    при каждом обращении и, если изменилось, слот пересоздаётся (semaphore с
    новым N; осиротевший sem доrelease доживает — безопасно). Чистка ленивая:
    при len(_slots) > max_entries удаляются слоты без ожидающих (pending==0) и
    со свободным семафором (sem._value == n) — никем не заняты.
    """

    def __init__(self, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._slots: dict[int, _Slot] = {}
        self._guard = asyncio.Lock()

    def _current_n(self) -> int:
        """Допустимая параллельность на чат (>=1)."""
        return max(
            1, int(hot.get(_CONCURRENCY_KEY,
                           settings.SMARTMODULE_CONCURRENCY_PER_CHAT) or 1))

    async def _get_slot(self, chat_id: int) -> _Slot:
        async with self._guard:
            n = self._current_n()
            slot = self._slots.get(chat_id)
            if slot is None or slot.n != n:
                slot = _Slot(asyncio.Semaphore(n), n)
                self._slots[chat_id] = slot
            slot.pending += 1
            if len(self._slots) > self._max_entries:
                self._evict(keep_chat_id=chat_id)
            return slot

    def _evict(self, keep_chat_id: int) -> None:
        """Под _guard: убрать слоты сверх потолка — свободные (sem._value == n)
        и без ожидантов (pending == 0). Занятые/ожидающие НЕ выселяются —
        иначе два «владельца» одного чата (гонка как T-501 у замков)."""
        for cid, candidate in list(self._slots.items()):
            if cid == keep_chat_id or len(self._slots) <= self._max_entries:
                continue
            if candidate.pending > 0:
                continue
            if candidate.sem._value != candidate.n:   # кто-то держит слот
                continue
            del self._slots[cid]

    def _drop_pending(self, slot: _Slot) -> None:
        """Снять одну бронь ожиданта после разрешения acquire-попытки
        (успех → слот занят/возможен — чистке не подлежит; таймаут → ушёл)."""
        slot.pending -= 1

    async def try_acquire(self, chat_id: int,
                          timeout: float | None = None) -> _Permit | None:
        """Слот чата в течение timeout секунд (None = ждать без таймаута).
        Успех → _Permit (release в finally вызывающего); таймаут → None."""
        slot = await self._get_slot(chat_id)
        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await slot.sem.acquire()
            else:
                await slot.sem.acquire()
        except (asyncio.TimeoutError, TimeoutError):
            self._drop_pending(slot)
            return None
        self._drop_pending(slot)
        return _Permit(slot.sem)

    async def acquire(self, chat_id: int) -> _Permit:
        """Ждать слот чата без таймаута (прежняя семантика async with lock)."""
        slot = await self._get_slot(chat_id)
        await slot.sem.acquire()
        self._drop_pending(slot)
        return _Permit(slot.sem)

    # ── Интроспекция для тестов/диагностики ──

    def slot_n(self, chat_id: int) -> int | None:
        """N слота чата (None — слота нет)."""
        slot = self._slots.get(chat_id)
        return slot.n if slot is not None else None

    def slot_count(self) -> int:
        return len(self._slots)

    def clear(self) -> None:
        """Очистить слоты (тесты). Держатели осиротевших sem доживают — ок."""
        self._slots.clear()


_pool_singleton: ChatConcurrencyPool | None = None


def get_smartmodule_concurrency_pool() -> ChatConcurrencyPool:
    """Модульный синглтон пула (как get_smart_cache) — единая точка для
    direct_chat, summary_generator и хендлеров smart module."""
    global _pool_singleton
    if _pool_singleton is None:
        _pool_singleton = ChatConcurrencyPool()
    return _pool_singleton


def reset_smartmodule_concurrency_pool() -> None:
    """Сброс синглтона для тестов (isolate между тестами)."""
    global _pool_singleton
    _pool_singleton = None


def smartmodule_wait_seconds() -> float:
    """Таймаут ожидания слота для хендлеров smart module
    (limits.smartmodule_concurrency_wait_seconds; дефолт 60.0)."""
    return float(hot.get(_WAIT_KEY, settings.SMARTMODULE_CONCURRENCY_WAIT_SECONDS))
