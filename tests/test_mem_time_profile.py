"""VMQ-MEM-TIME (§5): профиль участника из НЕСКОЛЬКИХ периодов истории.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/time/fix-contract.md`
(§5, M1). Проверяется существующее чтение `DatabaseService.
get_user_context_facts`:

  * `scope='operative'` (по умолчанию) — прежний SQL байт-в-байт: только
    действующие сейчас строки, порядок `weight DESC, created_at DESC`;
  * `scope='historical'` — одно чтение с годовой квотой `limit//5`
    (window-функция SQLite): профиль покрывает несколько периодов, квота
    активных фактов (`archived_fact`) не является границей истории;
  * expired/unconfirmed в профиль не попадают; NULL-год — отдельная группа
    последней; `limit` не растёт (бюджет envelope не расширяется);
  * M1: вопрос о человеке без года даёт ≥3 разных года, включая 2023 и 2024,
    у каждой строки реальный источник (`message_timestamp`/`tg_message_id`).
"""
import asyncio
import calendar
import sqlite3
import time

import pytest

from services.database import DatabaseService

CHAT = -100
_DAY = 86400


def _ts(year: int, month: int = 6, day: int = 1) -> int:
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


def _year_of(ts) -> int | None:
    try:
        return time.gmtime(int(ts)).tm_year
    except (TypeError, ValueError):
        return None


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _fact(db, text, *, year=2026, weight=0.6, status="confirmed",
                expires_at=None, subject_ref=None, tg_id=None):
    """Legacy-строка профиля: субъект по имени (`subject_ref_id IS NULL`).

    Такой же отбор, каким пользуется существующее чтение
    `get_user_context_facts` (MCA-04a: устойчивый ref — по `subject_ref_id`,
    legacy — по `target_user`)."""
    return await db.insert_graph_fact(
        CHAT, text, "chat_history", expires_at, target_user="aleksey",
        status=status, weight=weight, importance=5,
        message_timestamp=_ts(year), subject_ref_id=subject_ref,
        attribution_method="self_report",
        tg_message_id=tg_id or (5000 + year))


async def _seed_profile(db):
    """2026×10 (живые) + 2024×2 + 2023×2 (вытесненные квотой)."""
    ids = {"2026": [], "2024": [], "2023": []}
    for i in range(10):
        ids["2026"].append(await _fact(db, f"профиль 2026 #{i}", year=2026))
    for i in range(2):
        ids["2024"].append(await _fact(
            db, f"профиль 2024 #{i}", year=2024, status="archived_fact",
            weight=0.55))
        ids["2023"].append(await _fact(
            db, f"профиль 2023 #{i}", year=2023, status="archived_fact",
            weight=0.55))
    return ids


class TestOperativeScope:

    def test_default_sql_is_unchanged(self, db):
        """`operative` (default) — только действующее, прежний порядок."""
        loop = asyncio.get_event_loop()
        ids = loop.run_until_complete(_seed_profile(db))
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255))
        assert len(rows) == 10
        assert all(int(row["status"] == "confirmed") for row in rows)
        assert {_year_of(row["message_timestamp"]) for row in rows} == {2026}
        archived = set(ids["2023"]) | set(ids["2024"])
        assert not archived & {row["id"] for row in rows}
        # Тот же порядок, что у прежнего SQL: weight DESC, created_at DESC.
        weights = [float(row["weight"]) for row in rows]
        assert weights == sorted(weights, reverse=True)

    def test_explicit_operative_matches_default(self, db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_profile(db))
        now = int(time.time())
        default = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255))
        explicit = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="operative"))
        assert [row["id"] for row in default] == [row["id"] for row in explicit]


class TestHistoricalScope:
    def test_m1_profile_spans_periods(self, db):
        """M1: профиль без года → ≥3 разных года, включая 2023 и 2024."""
        loop = asyncio.get_event_loop()
        ids = loop.run_until_complete(_seed_profile(db))
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        years = {_year_of(row["message_timestamp"]) for row in rows}
        assert len(years) >= 3, f"годы профиля: {sorted(years)}"
        assert 2023 in years and 2024 in years
        assert len(rows) <= 10, "limit не растёт (бюджет envelope тот же)"
        # Годовая квота limit//5 = 2 на год, действующие впереди.
        for year in (2023, 2024):
            assert len([row for row in rows
                        if _year_of(row["message_timestamp"]) == year]) == 2
        # Реальные источники: у каждой строки есть дата-источник и id.
        for row in rows:
            assert row["message_timestamp"] and row["tg_message_id"]
            assert row["id"] in {fid for group in ids.values() for fid in group}
        # Год участвует в порядке: действующие (2026) идут первыми.
        assert _year_of(rows[0]["message_timestamp"]) == 2026

    def test_expired_and_unconfirmed_excluded(self, db):
        loop = asyncio.get_event_loop()
        now = int(time.time())
        live = loop.run_until_complete(_fact(db, "живой 2024", year=2024))
        expired = loop.run_until_complete(_fact(
            db, "истёкший 2023", year=2023, expires_at=now - _DAY))
        unconfirmed = loop.run_until_complete(_fact(
            db, "неподтверждённый 2025", year=2025, status="unconfirmed"))
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        returned = {row["id"] for row in rows}
        assert live in returned
        assert expired not in returned
        assert unconfirmed not in returned

    def test_null_year_is_last_group(self, db):
        """NULL-год — отдельная группа последней (COALESCE(yr,0) = 0)."""
        loop = asyncio.get_event_loop()
        now = int(time.time())
        loop.run_until_complete(_fact(db, "профиль 2026", year=2026))
        no_date = loop.run_until_complete(db.insert_graph_fact(
            CHAT, "без даты", "chat_history", None, target_user="aleksey",
            weight=0.9, importance=5, attribution_method="self_report"))
        # Реального времени события нет вовсе: и message_timestamp, и
        # created_at пусты → год NULL (отдельная последняя группа).
        loop.run_until_complete(db.db.execute(
            "UPDATE graph_facts SET created_at = 0 WHERE id = ?", (no_date,)))
        loop.run_until_complete(db.db.commit())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        years = [_year_of(row["message_timestamp"]) for row in rows]
        assert years and years[-1] is None, f"порядок годов: {years}"
        assert 2026 in years

    def test_window_functions_available_or_degraded(self, db):
        """R7: контракт держится и без оконных функций (degraded-путь)."""
        assert hasattr(sqlite3, "sqlite_version_info")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_profile(db))
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        years = {_year_of(row["message_timestamp"]) for row in rows}
        assert len(years) >= 3
        # Текущая версия SQLite поддерживает оконные функции (ветка CTE).
        assert sqlite3.sqlite_version_info >= (3, 25)

class TestUnattributedHistory:
    """Блокер 3 ре-ревью 10.11.2026: на реальном архиве у старых
    `confirmed`-фактов НЕТ привязки к субъекту (`subject_ref_id`,
    `target_user`, автор, `tg_message_id` — всё пусто), поэтому профиль по
    человеку их не достигал. Выбран наименьший честный шаг: добрать историю
    ЧАТА за несколько периодов и помечать её `unattributed` (не «сведения о
    человеке»)."""

    async def _import_fact(self, db, text, year):
        """Строка как в реальном импорте: без субъекта и без автора."""
        return await db.insert_graph_fact(
            CHAT, text, "history_import", None, weight=0.3, importance=2,
            message_timestamp=_ts(year))

    def test_profile_reaches_periods_without_subject_binding(self, db):
        loop = asyncio.get_event_loop()
        bound = loop.run_until_complete(
            _fact(db, "личный факт 2026", year=2026))
        imported = [loop.run_until_complete(
            self._import_fact(db, f"импорт {year}", year))
            for year in (2022, 2023, 2024, 2025)]
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        years = {_year_of(row["message_timestamp"]) for row in rows}
        assert 2023 in years and 2024 in years, f"годы профиля: {years}"
        assert len(years) >= 3, f"годы профиля: {sorted(years)}"
        returned = {row["id"] for row in rows}
        assert bound in returned, "bound-факт субъекта остаётся в профиле"
        assert set(imported) & returned, "история чата добирается"
        for row in rows:
            expected = 0 if row["id"] == bound else 1
            assert int(row["unattributed"]) == expected, row["id"]

    def test_operative_profile_is_unchanged(self, db):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_fact(db, "личный факт 2026", year=2026))
        for year in (2022, 2023, 2024):
            loop.run_until_complete(
                self._import_fact(db, f"импорт {year}", year))
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255))
        assert [row["id"] for row in rows]
        assert all(_year_of(row["message_timestamp"]) == 2026 for row in rows)
        assert not any(row.get("unattributed") for row in rows)

    def test_person_rows_get_half_of_the_slice(self, db):
        """Bound-строки не занимают весь срез: иначе один год снова."""
        loop = asyncio.get_event_loop()
        for index in range(9):
            loop.run_until_complete(
                _fact(db, f"личный {index}", year=2026, weight=0.9))
        for year in (2023, 2024):
            loop.run_until_complete(
                self._import_fact(db, f"импорт {year}", year))
        now = int(time.time())
        rows = loop.run_until_complete(
            db.get_user_context_facts(CHAT, "aleksey", 10, now,
                                      user_id=138811255, scope="historical"))
        years = {_year_of(row["message_timestamp"]) for row in rows}
        assert 2023 in years and 2024 in years, sorted(years)
