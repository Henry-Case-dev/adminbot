-- SCH postdeploy reconciliation (read-only).
-- slot_claims(fired=1, kind='summary')  <->  summary_runs(manual=0, в окне слота).
-- Единицы slot_utc_instant / created_at: epoch-секунды UTC.
-- Окно слота: [slot_utc_instant, следующий слот чата), последний слот: +86400 s.
-- Для окна «с даты деплоя» добавить в CTE summary_slots:
--     AND local_date >= '<YYYY-MM-DD>'
--
-- Запуск:
--   sqlite3 -readonly -header -column /var/www/admin_bot/local_database.db \
--           < sch_reconcile.sql
--
-- Ожидания после деплоя: Q2 gaps_no_run=0, dups_multi_run=0; Q3 — 0 строк.

-- Q1: по каждому fired=1 слоту — число auto-прогонов в его окне.
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.local_date, s.local_slot, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
)
SELECT b.chat_id, b.local_date, b.local_slot,
       datetime(b.slot_utc_instant, 'unixepoch') AS slot_utc,
       b.window_end - b.slot_utc_instant AS window_seconds,
       (SELECT COUNT(*) FROM summary_runs r
         WHERE r.chat_id = b.chat_id
           AND r.manual = 0
           AND r.created_at >= b.slot_utc_instant
           AND r.created_at <  b.window_end) AS runs_in_window
FROM bounded b
ORDER BY b.slot_utc_instant, b.chat_id;

-- Q2: сводка по тем же окнам.
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
),
counted AS (
    SELECT b.chat_id,
           (SELECT COUNT(*) FROM summary_runs r
             WHERE r.chat_id = b.chat_id
               AND r.manual = 0
               AND r.created_at >= b.slot_utc_instant
               AND r.created_at <  b.window_end) AS runs_in_window
    FROM bounded b
)
SELECT COUNT(*) AS fired_slots,
       SUM(CASE WHEN runs_in_window = 0 THEN 1 ELSE 0 END) AS gaps_no_run,
       SUM(CASE WHEN runs_in_window = 1 THEN 1 ELSE 0 END) AS ok_one_run,
       SUM(CASE WHEN runs_in_window >= 2 THEN 1 ELSE 0 END) AS dups_multi_run
FROM counted;

-- Q3: обратная сторона — auto-runs без покрывающего fired=1 слота (ожидание: 0).
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
)
SELECT r.run_id, r.chat_id,
       datetime(r.created_at, 'unixepoch') AS run_utc, r.state
FROM summary_runs r
WHERE r.manual = 0
  AND NOT EXISTS (
      SELECT 1 FROM bounded b
       WHERE b.chat_id = r.chat_id
         AND r.created_at >= b.slot_utc_instant
         AND r.created_at <  b.window_end)
ORDER BY r.created_at;
