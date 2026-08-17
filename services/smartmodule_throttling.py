"""Epic 33 — SmartModule throttling: форматтер + dict-TTL трекер (R33-5, D107).

Два НЕЗАВИСИМЫХ инстанса CooldownTracker (search и factcheck, D107) — в
handlers/factcheck.py и handlers/search.py. In-memory: перезапуск сбрасывает
(принято; прецедент summary_throttling). Формат «X мин Y сек» / «Z сек» —
ДОСЛОВНО по ТЗ R33-5 (отличие от format_remaining_seconds для /summary —
плюрализация не требуется, «сек»/«мин» всегда сокращённо).
"""
import math
import time


def format_remaining_time(seconds: float) -> str:
    """ТЗ-формат «X мин Y сек» / «Z сек» (ceil вверх; прецедент format_remaining_seconds,
    но формат другой — ДОСЛОВНО по ТЗ R33-5):
    45.0 → «45 сек», 90.0 → «1 мин 30 сек», 300.0 → «5 мин», 0.4 → «1 сек»."""
    total = max(1, math.ceil(seconds))
    if total < 60:
        return f"{total} сек"
    minutes, secs = divmod(total, 60)
    return f"{minutes} мин {secs} сек" if secs else f"{minutes} мин"


class CooldownTracker:
    """Dict-TTL коулдаун per (chat_id, user_id). Два НЕЗАВИСИМЫХ инстанса:
    search и factcheck (D107). In-memory: перезапуск сбрасывает (принято)."""

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._last: dict[tuple[int, int], float] = {}

    def remaining(self, chat_id: int, user_id: int) -> float:
        """Остаток кулдауна, сек (0.0 = можно выполнять)."""
        key = (chat_id, user_id)
        last = self._last.get(key)
        if last is None:
            return 0.0
        return max(0.0, self._cooldown - (time.monotonic() - last))

    def touch(self, chat_id: int, user_id: int) -> None:
        """Поставить/обновить слот (вызывается при валидном триггере)."""
        self._last[(chat_id, user_id)] = time.monotonic()
