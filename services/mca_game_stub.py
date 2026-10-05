"""mca-10c (`mca-10c-game-stub`, §14.12 `current_task.md:718–728`) —
игровая заготовка: место для будущих кубиков, жеребьёвок и игровых
случайных заданий.

**Заготовка, не реализовано** (`:722`). Это ЕДИНСТВЕННОЕ намеренно
неактивное исключение из «всё ON» (решение владельца §2.18,
`current_task.md:39`); §20.2 (`:1020`): «только код stub; не
зарегистрирована и не активна». Kill-switch НЕ вводится — неактивность
конструктивная (нет включаемой функции, `requirements-map.md` §6 п.3).

Границы (§14.12 `:724,726`):
  * изолированный модуль ВНЕ SmartModule; SmartModule о нём не знает
    (grep-проверка: 0 импортов в обе стороны);
  * будущий вход RandomSource обозначен ТОЛЬКО через DI: конструктор
    принимает источник, типизированный на шов mca-10a
    (`RandomSourceService`, `services/mca_random_source.py:7–9`) —
    будущий путь активации (передача источника при реализации игр);
  * stub НИКОГДА не вызывает источник: 0 draw, 0 записей в
    `mca_random_draws`, 0 расхода квоты, 0 событий `mca_events`,
  * вызов возвращает явный типизированный `not_implemented`-исход
    без случайного результата и side effects: нет сети, БД, scheduler,
    регистрации tools, Telegram handlers, UI.

Активация: передать реальный `RandomSourceService` в конструктор и
реализовать игровой вход поверх него; до того модуль остаётся без
поведения, без регистрации и без потребителей.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # только типизация шва mca-10a; runtime-импорта нет
    from services.mca_random_source import RandomSourceService

STUB_VERSION = "mca10c-v1"
OUTCOME_NOT_IMPLEMENTED = "not_implemented"
# Локальный код причины; в канон `mca_events.REASON_CODES` НЕ добавляется
# (reason_code +0; событие stub не создаёт — запись была бы side effect).
REASON_STUB_INACTIVE = "game_stub_inactive"
_DETAIL_MAX = 80


@dataclass(frozen=True)
class GameStubOutcome:
    """Типизированный исход заготовки (без случайного результата)."""

    status: str
    reason: str
    detail: str = ""
    stub_version: str = STUB_VERSION

    @property
    def implemented(self) -> bool:
        return self.status != OUTCOME_NOT_IMPLEMENTED


class GameStub:
    """Игровая заготовка §14.12 (неактивная; поведение не реализовано)."""

    def __init__(self,
                 random_source: RandomSourceService | None = None) -> None:
        # DI-шов mca-10a: источник сохраняется для будущей активации и
        # НИКОГДА не вызывается (0 draw / 0 сети / 0 квоты).
        self._random_source = random_source

    async def run(self, action: str = "") -> GameStubOutcome:
        """Единый игровой вход: всегда честный `not_implemented`."""
        action = " ".join(str(action or "").split())[:_DETAIL_MAX]
        return GameStubOutcome(
            status=OUTCOME_NOT_IMPLEMENTED,
            reason=REASON_STUB_INACTIVE,
            detail=f"game action not implemented: {action or '<none>'}",
        )
