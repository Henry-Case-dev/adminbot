"""MCA-10c `mca-10c-game-stub` — focused-тесты заготовки §14.12
(T-5068/T-5069, A36 `current_task.md:917`).

Покрытие:
  * импорт + вызов stub → `not_implemented`, 0 событий `mca_events`,
    0 обращений к источнику случайности (MCA10C-R3, R5);
  * DI-шов mca-10a принимает реальный `RandomSourceService` и никогда
    его не вызывает (MCA10C-R2; spy считает ЛЮБОЙ доступ к атрибутам);
  * изоляция: runtime-импорты stub — только stdlib (SmartModule/services
    не импортируются), reason-код не добавлен в канон REASON_CODES
    (MCA10C-R1, canon 12 +0);
  * grep-gate: `mca_game_stub`/`GameStub` не упоминается ни в bot.py,
    ни в services/ (вне самого stub), handlers/, SmartModule/, tools/,
    web/, config/ — нет регистрации tools/handlers/UI/coordinator
    (MCA10C-R4).
"""
import ast
from pathlib import Path

import pytest

from services import mca_events
from services import mca_random_source as mrs
from services import mca_game_stub as stub
from services.mca_game_stub import GameStub, GameStubOutcome

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


class _TouchSpy:
    """Прокси-шпион: считает ЛЮБОЙ доступ к атрибутам источника.

    `touches == 0` после вызова stub = источник не только не вызван,
    но даже не прочитан (ни метода, ни поля)."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "touches", 0)

    def __getattr__(self, name):
        object.__setattr__(
            self, "touches", object.__getattribute__(self, "touches") + 1)
        return getattr(object.__getattribute__(self, "_inner"), name)


@pytest.mark.asyncio
async def test_stub_returns_not_implemented_without_side_effects():
    """Импорт+вызов: `not_implemented`, 0 событий, 0 draw (MCA10C-R3)."""
    stub_instance = GameStub()
    outcome = await stub_instance.run("dice_roll")
    assert isinstance(outcome, GameStubOutcome)
    assert outcome.status == stub.OUTCOME_NOT_IMPLEMENTED == "not_implemented"
    assert outcome.reason == stub.REASON_STUB_INACTIVE
    assert outcome.implemented is False
    # Случайного результата нет — в исходе нет поля значения вовсе.
    assert not hasattr(outcome, "value") and not hasattr(outcome, "index")
    assert outcome.stub_version == stub.STUB_VERSION
    # 0 событий `mca_events` (запись события = запрещённый side effect).
    assert mca_events.pending_size() == 0
    # reason-код локальный: канон REASON_CODES не расширен (canon 12 +0).
    assert stub.REASON_STUB_INACTIVE not in mca_events.REASON_CODES


@pytest.mark.asyncio
async def test_di_seam_accepts_real_source_without_invoking():
    """DI-шов mca-10a: реальный RandomSourceService принят, 0 вызовов
    и даже 0 чтений атрибутов (MCA10C-R2; `:726` — не активный
    потребитель QRNG, квота не расходуется)."""
    real = mrs.RandomSourceService()  # db=None; refill в __init__ не стартует
    spy = _TouchSpy(real)
    stub_instance = GameStub(random_source=spy)
    outcome = await stub_instance.run()
    assert outcome.status == "not_implemented"
    assert spy.touches == 0
    # Источник сохранён как есть (без копий/обёрток над ним).
    assert stub_instance._random_source is spy


@pytest.mark.asyncio
async def test_stub_runtime_imports_stdlib_only():
    """Изоляция (MCA10C-R1): runtime-импорты stub — только stdlib;
    SmartModule и services на runtime не импортируются (шов mca-10a —
    только под TYPE_CHECKING)."""
    source = Path(stub.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_levels = set()

    def _collect(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and _is_type_checking(child.test):
                continue  # блок TYPE_CHECKING — runtime-импорта нет
            if isinstance(child, ast.Import):
                top_levels.update(a.name.split(".")[0] for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                top_levels.add("." if child.level
                               else (child.module or "").split(".")[0])
            _collect(child)

    def _is_type_checking(test):
        return ((isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
                or (isinstance(test, ast.Attribute)
                    and test.attr == "TYPE_CHECKING"))

    _collect(tree)
    assert top_levels <= {"__future__", "dataclasses", "typing"}
    assert "SmartModule" not in top_levels
    assert "services" not in top_levels


def test_grep_gate_zero_registration():
    """Grep-gate (MCA10C-R4/R5): нет регистрации в tools/handlers/UI/
    coordinator/боте — 0 упоминаний stub вне самого модуля и тестов."""
    needles = ("mca_game_stub", "GameStub", "game_stub")
    surfaces = [_ROOT / "bot.py"]
    for dirname in ("services", "handlers", "SmartModule", "tools", "web",
                    "config"):
        surfaces.extend((_ROOT / dirname).rglob("*.py"))
    hits = []
    for path in surfaces:
        if path.resolve() == Path(stub.__file__).resolve():
            continue  # сам модуль — единственное легитимное место
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle in needles:
            if needle in text:
                hits.append(f"{path.relative_to(_ROOT)}:{needle}")
    assert hits == []
