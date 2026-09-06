"""Раунд 9 (AGI Memory, T-816, spec §3.1.1/§3.1.2) — users_meta и стадии.

Покрытие (минимум задачи B1/G1-часть): touch-апсерт (first_seen=min,
last_seen=max, msg_count+1; вызов из save_smart_message), get_users_meta/
get_user_meta, refresh_users_meta (агрегаты all-time + 30д-окно, decay
0.5^((now-ts)/14д), стадии по порогам, анти-откат Q5, last_recalc_at),
recalc_user_meta/recalc_chat_users.
"""
import asyncio
import time

import pytest

from services.database import DatabaseService
from services import user_relations as ur

NOW = 1_800_000_000          # фиксированное «сейчас» для детерминизма
DAY = 86400


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _add_msgs(db, chat_id: int, rows: list[tuple[int, int]]):
    """rows: [(user_id, timestamp), ...] — напрямую в smart_messages."""
    for user_id, ts in rows:
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, timestamp, "
            "media_type) VALUES (?, ?, ?, 'text')", (user_id, chat_id, ts))
    await db.db.commit()


class TestTouchUpsert:
    @pytest.mark.asyncio
    async def test_touch_creates_row_and_increments(self, db):
        await db.touch_user_meta(-100, 1, 100)
        row = await db.get_user_meta(-100, 1)
        assert row["first_seen"] == 100
        assert row["last_seen"] == 100
        assert row["msg_count"] == 1
        assert row["relationship_stage"] == "stranger"
        await db.touch_user_meta(-100, 1, 200)
        row = await db.get_user_meta(-100, 1)
        assert row["msg_count"] == 2
        assert row["last_seen"] == 200
        assert row["first_seen"] == 100      # min не перетирается

    @pytest.mark.asyncio
    async def test_touch_first_seen_min_last_seen_max(self, db):
        # нехронологичный порядок «касаний»
        await db.touch_user_meta(-100, 7, 500)
        await db.touch_user_meta(-100, 7, 100)
        row = await db.get_user_meta(-100, 7)
        assert row["first_seen"] == 100
        assert row["last_seen"] == 500
        assert row["msg_count"] == 2

    @pytest.mark.asyncio
    async def test_save_smart_message_touches(self, db):
        await db.save_smart_message(11, -100, "привет", None, 1000,
                                    "text", "Вася")
        row = await db.get_user_meta(-100, 11)
        assert row is not None
        assert row["first_seen"] == 1000 and row["last_seen"] == 1000
        assert row["msg_count"] == 1
        await db.save_smart_message(11, -100, "ещё", None, 2000,
                                    "text", "Вася")
        row = await db.get_user_meta(-100, 11)
        assert row["msg_count"] == 2 and row["last_seen"] == 2000

    @pytest.mark.asyncio
    async def test_save_with_none_user_id_does_not_touch(self, db):
        # импортированная история (user_id NULL) в users_meta не попадает
        await db.save_smart_message(None, -100, "импорт", None, 1000,
                                    "text", "")
        assert await db.get_user_meta(-100, None) is None
        cursor = await db.db.execute(
            "SELECT COUNT(*) FROM users_meta WHERE chat_id = -100")
        assert (await cursor.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_get_users_meta_filter_order_limit_isolation(self, db):
        await db.touch_user_meta(-100, 1, 300)
        await db.touch_user_meta(-100, 2, 900)
        await db.touch_user_meta(-100, 3, 600)
        await db.touch_user_meta(-99, 1, 100)      # другой чат
        rows = await db.get_users_meta(-100)
        assert [r["user_id"] for r in rows] == [2, 3, 1]   # last_seen DESC
        rows = await db.get_users_meta(-100, user_ids=[1, 3])
        assert {r["user_id"] for r in rows} == {1, 3}
        assert await db.get_user_meta(-100, 999) is None


class TestRefreshStagesAndDecay:
    @pytest.mark.asyncio
    async def test_refresh_stages_by_thresholds(self, db):
        chat = -100
        veteran = 1001          # 1000 сообщений (по дню), ~1000 дней
        regular = 1002          # 250 сообщений (по дню), 250 дней
        acquaintance = 1003     # 12 сообщений (по дню), 12 дней
        stranger = 1004         # 5 сообщений (по дню), 100 дней назад
        rows: list[tuple[int, int]] = []
        rows += [(veteran, NOW - 1000 * DAY + i * DAY)
                 for i in range(1000)]
        rows += [(regular, NOW - 250 * DAY + i * DAY) for i in range(250)]
        rows += [(acquaintance, NOW - 12 * DAY + i * DAY)
                 for i in range(12)]
        rows += [(stranger, NOW - 100 * DAY + i * DAY) for i in range(5)]
        await _add_msgs(db, chat, rows)
        count = await db.refresh_users_meta(chat, now=NOW)
        assert count == 4
        assert (await db.get_user_meta(chat, veteran))["relationship_stage"] \
            == "veteran"
        assert (await db.get_user_meta(chat, regular))["relationship_stage"] \
            == "regular"
        assert (await db.get_user_meta(chat, acquaintance))\
            ["relationship_stage"] == "acquaintance"
        assert (await db.get_user_meta(chat, stranger))["relationship_stage"] \
            == "stranger"
        v = await db.get_user_meta(chat, veteran)
        assert v["first_seen"] == NOW - 1000 * DAY    # all-time (импорт/старики)
        assert v["last_seen"] == NOW - DAY            # 1000-е сообщение
        assert v["msg_count"] == 1000
        assert v["active_days"] == 30                 # уникальные дни 30д-окна
        assert v["last_recalc_at"] == NOW

    @pytest.mark.asyncio
    async def test_decay_activity_score_half_life(self, db):
        chat = -200
        fresh = 2001
        old14 = 2002
        old40 = 2003          # вне 30д-окна — вклада в score нет
        rows = [
            (fresh, NOW),
            (fresh, NOW - DAY),                       # 0.5**(1/14) ≈ 0.952
            (old14, NOW - 14 * DAY),                  # ≈ 0.5
            (old14, NOW - 28 * DAY),                  # ≈ 0.25 (в окне)
            (old40, NOW - 40 * DAY),                  # вне окна decay
        ]
        await _add_msgs(db, chat, rows)
        await db.refresh_users_meta(chat, now=NOW)
        fresh_row = await db.get_user_meta(chat, fresh)
        assert fresh_row["activity_score"] == pytest.approx(
            1.0 + 0.5 ** (1 / 14), abs=1e-3)
        old14_row = await db.get_user_meta(chat, old14)
        assert old14_row["activity_score"] == pytest.approx(
            0.5 ** (14 / 14) + 0.5 ** (28 / 14), abs=1e-3)
        old40_row = await db.get_user_meta(chat, old40)
        assert old40_row is not None
        assert old40_row["activity_score"] == 0.0    # вне окна — скор 0

    @pytest.mark.asyncio
    async def test_refresh_subset_and_commit(self, db):
        chat = -300
        await _add_msgs(db, chat, [(1, NOW - 2 * DAY), (2, NOW - 3 * DAY)])
        assert await db.refresh_users_meta(chat, [1], now=NOW) == 1
        assert await db.get_user_meta(chat, 1) is not None
        assert await db.get_user_meta(chat, 2) is None
        assert await db.refresh_users_meta(chat, [], now=NOW) == 0

    @pytest.mark.asyncio
    async def test_recalc_chat_users_unions_active_and_stored(self, db):
        chat = -400
        await db.touch_user_meta(chat, 42, NOW - 10 * DAY)   # только строка
        await _add_msgs(db, chat, [
            (1, NOW - DAY), (2, NOW - 2 * DAY), (42, NOW - 40 * DAY)])
        await db.touch_user_meta(chat, 42, NOW - 40 * DAY)
        count = await db.recalc_chat_users(chat, now=NOW)
        assert count == 3
        for uid in (1, 2, 42):
            assert await db.get_user_meta(chat, uid) is not None
        # 42 вне 30д-окна: кандидат stranger, но стадии держатся (анти-откат
        # отсутствия) — строка создана/обновлена refresh'ем из all-time-агрегата
        assert (await db.get_user_meta(chat, 42))["msg_count"] == 1


class TestAntiDowngradeAtDb:
    """Q5: стадии не откатываются резко (проверка на уровне refresh)."""

    @pytest.mark.asyncio
    async def test_stage_held_while_absent_more_than_60d(self, db):
        chat = -500
        user = 5001
        # ветеран: 1200 сообщений 400–350 дней назад + 5 сообщений ~100 дней
        # назад (first_seen уходит в прошлое; all-time-агрегат)
        rows = [(user, NOW - 400 * DAY + i * 3600) for i in range(1200)]
        rows += [(user, NOW - 100 * DAY + i * DAY) for i in range(5)]
        await _add_msgs(db, chat, rows)
        await db.refresh_users_meta(chat, [user], now=NOW)
        assert (await db.get_user_meta(chat, user))["relationship_stage"] \
            == "veteran"
        # «retention» вычистил старую историю: остались 5 сообщений 100д назад
        await db.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND user_id = ? "
            "AND timestamp < ?", (chat, user, NOW - 101 * DAY))
        await db.db.commit()
        await db.refresh_users_meta(chat, [user], now=NOW)
        row = await db.get_user_meta(chat, user)
        assert row["msg_count"] == 5
        assert row["relationship_stage"] == "veteran"   # absence ~96д > 60
        assert row["activity_score"] == 0.0             # окно пусто — скор пал

    @pytest.mark.asyncio
    async def test_downgrade_max_one_step_and_cooldown(self, db):
        chat = -600
        user = 6001
        # regular: 250 сообщений (по дню), 300–51 день назад + 5 недавних
        rows = [(user, NOW - 300 * DAY + i * DAY) for i in range(250)]
        rows += [(user, NOW - 20 * DAY + i * DAY) for i in range(5)]
        await _add_msgs(db, chat, rows)
        await db.refresh_users_meta(chat, [user], now=NOW)
        assert (await db.get_user_meta(chat, user))["relationship_stage"] \
            == "regular"
        # переводим в veteran вручную (смена была 40 дней назад)
        await db.db.execute(
            "UPDATE users_meta SET relationship_stage = 'veteran', "
            "last_stage_change = ? WHERE chat_id = ? AND user_id = ?",
            (NOW - 40 * DAY, chat, user))
        await db.db.commit()
        # «retention»: старьё удалено, остались 5 сообщений 20–16 дней назад
        await db.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND user_id = ? "
            "AND timestamp < ?", (chat, user, NOW - 21 * DAY))
        await db.db.commit()
        await db.refresh_users_meta(chat, [user], now=NOW + DAY)
        row = await db.get_user_meta(chat, user)
        # кандидат stranger; absence 17д ≤ 60, кулдаун прошёл, msg_30d=5 < 10
        # → понижение на ОДНУ ступень: veteran → regular
        assert row["relationship_stage"] == "regular"
        assert row["last_stage_change"] == NOW + DAY
        # повторный recalc сразу (кулдаун 30д не прошёл) — стадия держится
        await db.refresh_users_meta(chat, [user], now=NOW + DAY + 60)
        row = await db.get_user_meta(chat, user)
        assert row["relationship_stage"] == "regular"

    @pytest.mark.asyncio
    async def test_no_downgrade_while_active_msg30(self, db):
        chat = -700
        user = 7001
        # 250 сообщений 300–51 день назад + 30 свежих (каждый час последних
        # 30 часов) — msg_30d = 30 >= 10
        rows = [(user, NOW - 300 * DAY + i * DAY) for i in range(250)]
        rows += [(user, NOW - i * 3600) for i in range(30)]
        await _add_msgs(db, chat, rows)
        await db.refresh_users_meta(chat, [user], now=NOW)
        assert (await db.get_user_meta(chat, user))["relationship_stage"] \
            == "regular"
        await db.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND user_id = ? "
            "AND timestamp < ?", (chat, user, NOW - 30 * DAY))
        await db.db.commit()
        await db.refresh_users_meta(chat, [user], now=NOW + DAY)
        row = await db.get_user_meta(chat, user)
        assert row["relationship_stage"] == "regular"   # msg30=30 >= 10


class TestPureRules:
    def test_stage_candidate_conjunction(self):
        assert ur.stage_candidate(9, 400) == "stranger"       # msg < 10
        assert ur.stage_candidate(10, 6) == "stranger"        # days < 7
        assert ur.stage_candidate(10, 7) == "acquaintance"
        assert ur.stage_candidate(199, 365) == "acquaintance"  # msg < 200
        assert ur.stage_candidate(200, 89) == "acquaintance"   # days < 90
        assert ur.stage_candidate(200, 90) == "regular"
        assert ur.stage_candidate(999, 1000) == "regular"      # msg < 1000
        assert ur.stage_candidate(1000, 364) == "regular"      # days < 365
        assert ur.stage_candidate(1000, 365) == "veteran"
        assert ur.stage_candidate(5000, 2000) == "veteran"

    def test_decide_stage_upgrade_is_instant(self):
        stage, changed = ur.decide_stage(
            "stranger", "veteran", now=NOW, last_seen=NOW - 5 * DAY,
            last_stage_change=None, msg_30d=1)
        assert (stage, changed) == ("veteran", True)

    def test_decide_stage_holds_when_absent_long(self):
        stage, changed = ur.decide_stage(
            "veteran", "stranger", now=NOW, last_seen=NOW - 100 * DAY,
            last_stage_change=NOW - 200 * DAY, msg_30d=0)
        assert (stage, changed) == ("veteran", False)

    def test_decide_stage_one_step_and_gates(self):
        # все условия для понижения: absence ≤ 60д, кулдаун прошёл, msg30 < 10
        stage, changed = ur.decide_stage(
            "veteran", "stranger", now=NOW, last_seen=NOW - 10 * DAY,
            last_stage_change=NOW - 40 * DAY, msg_30d=0)
        assert (stage, changed) == ("regular", True)     # veteran→regular
        # кулдаун 30д не прошёл → держим
        stage, _ = ur.decide_stage(
            "regular", "stranger", now=NOW, last_seen=NOW - 10 * DAY,
            last_stage_change=NOW - 10 * DAY, msg_30d=0)
        assert stage == "regular"
        # активность (msg30 >= 10) → держим
        stage, _ = ur.decide_stage(
            "regular", "stranger", now=NOW, last_seen=NOW - 10 * DAY,
            last_stage_change=NOW - 40 * DAY, msg_30d=12)
        assert stage == "regular"

    def test_decay_weight_formula(self):
        assert ur.decay_weight(NOW, NOW, 14) == 1.0
        assert ur.decay_weight(NOW, NOW - 14 * DAY, 14) == pytest.approx(0.5)
        assert ur.decay_weight(NOW, NOW - 28 * DAY, 14) == pytest.approx(0.25)
        assert ur.decay_weight(NOW, NOW - 14 * DAY, 7) == pytest.approx(0.25)

    def test_stage_ru_labels(self):
        assert ur.STAGE_RU["stranger"] == "нюфаг"
        assert ur.STAGE_RU["veteran"] == "ветеран"
