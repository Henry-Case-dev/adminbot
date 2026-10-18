# PROD-TICK-OBS-25883 (лейн B) — плановые тики Summary после релиза 2.58.83

Захват: **2026-10-17 05:46:48 UTC** (сервер в UTC, `NOW_UTC` в сыром выводе). Релиз: **2.58.83 @ `448cc81a`**,
задеплоен 2026-10-16 ~18:08–18:12 UTC (в брифе было «~13:08» — по серверу фактически 18:08). Режим: read-only,
прод-коннектов в лейне: один свежий захват (см. §Происхождение). Сырой вывод:
`OPENCODE_WORKFLOW_SCRATCH/tick-25883-run.txt` (UTF-16; копия `…run.utf8.txt`); скрипт `OPENCODE_WORKFLOW_SCRATCH/deploy25883/verify_after_tick_25883.py`.

## Плановые тики (cron `0,6,12,18 Asia/Yekaterinburg` = 19/01/07/13 UTC)

| Тик UTC | Run (short) | Chat | State | Стадии | Длит. | Публикация |
|---|---|---|---|---|---|---|
| 16.10 19:00 | `73f16a62…` | -1002661910336 | DEGRADED | 7: permit ok/immediate → memory ok 452s → source ok → l1 ok → l2 attempted_invalid (`unknown_field`) → LEGACY_FALLBACK → run ok | 963 s | published, rich `message_id=1162997` |
| 17.10 01:00 | `689b89ad…` | -1002661910336 | DEGRADED | 8: permit ok → memory ok 246s → source ok → l1 ok → l2 ok→`l2_review` failed (`l2_review_rejected`) → LEGACY_FALLBACK → run ok | 629 s | published, rich `message_id=1163339` (cover style `bad_json` → base fallback) |
| 17.10 07:00 | — | — | **NOT_DUE** на момент захвата | — | — | — |

Отключённый чат `-1004482340693` на обоих тиках — `cron skip (disabled, source=chat)` (по конфигурации, не потеря).

## Вердикты по acceptance

1. **Тики→раны→терминал: PASS 2/3.** 19:00 переподтверждён (те же run/message_id, что в release-отчёте), 01:00 — новый;
   оба рана терминальны (DEGRADED из-за предсуществующей legacy-деградации L2, публикация есть); 07:00 не наступил к захвату → §Отложено.
2. **Стадии: PASS.** started/finished/длительности у обоих ранов; `run_*` + `SUMMARY_SOURCE_WINDOW` (duration_ms=63/26) видны;
   макс. span 963 s « 60 мин — pregen-bounds соблюдены, ничего не «висит».
3. **Публикации: PASS.** На каждый ран ровно 1 `SUMMARY_PUBLISH success` + 1 `COVER_RICH_PUBLISH_SUCCEEDED`; double-publish нет;
   DONE/DEGRADED без публикации нет (`publication_status='published'` у обоих).
4. **Нетерминальные/фантом: PASS.** `nonterminal_count=(0,)`; фантом `da33f05d…` = FAILED (`updated_at`=16.10 16:12:30, стадия
   `run/failed/orphan_no_owner`); новых фантомов нет (states: DEGRADED 31 / DONE 18 / FAILED 1).
5. **Graceful/стопы: PASS с примечанием.** `stop-sigterm/Killing` за сутки — только 2 строки ночи деплоя (старый 2.58.82,
   18:09:40 `State 'stop-sigterm' timed out. Killing.`); строгое окно ≥18:11: `P_STOPSIGTERM=0`, `P_KILLING=0`. Новый код:
   `[shutdown] bye | elapsed_ms=770`, выход сам, `runtime sqlite closed` есть, `Polling stopped` раньше `bye`, `A_LEFTOVER=0`/`B2_LEFTOVER=0`.
   ERROR: `A_ERR=2`, `P_ERR=1`, `CRIT=0`, `TB=0` — 1 известная (старый процесс 18:08:40), 1 не идентифицирована текстом (§Аномалии).
6. **Сервис/healthz/git: PASS.** active/running, `MainPID=2916763`, `NRestarts=0` (старт 18:10:18 UTC), HZ loopback 200 и 443 200 —
   оба `{"status":"ok","version":"2.58.83"}`; `HEAD=448cc81a9eab590ea6de599f478220dd00abd3d1`, `TRACKED_MOD=0`.

## Аномалии (полные строки — в run-файле)

- **`P_ERR=1` (появилась между 19:22 и 05:46) не поймана текстом**: на 19:22 у нового PID `ERR=0` (evidence `release-25883/ev_errlines.txt`);
  позже — одна одиночная ERROR-строка, CRITICAL/Traceback нет, на пайплайны не влияла. Для речека в скрипт добавлен дамп
  `ERROR/CRITICAL/Traceback` (локально перевалидирован: py_compile+lint OK).
- **01:00: cover style fail** — `COVER_STYLE_FAILED | reason=bad_json` → `fallback=style_failed`, публикация ушла base-rich;
  тот же предсуществующий класс, что и 19:00 (`prompt_limit` retry WARNING); к INC-SUMMARY-01 не относится.
- **Фантом в mca_events**: только `SUMMARY_RUN_START` (историческая особенность allowlist, задокументирована; UI-бейдж Oversight
  по нему может читаться «running»). Durable-состояние — FAILED.
- **/tmp-форенсика**: `after.log` (16.10 19:22) не перезаписан; `aftertick*.log` + `dbcheck2.py` = 17.10 05:46 (этот захват);
  записей в окне предшественника (04:09–05:2x UTC) нет. Рестартов за ~11.6 ч не было (`A_SYS_STARTED=2`/`STOPPING=2` — только ночь деплоя).

## Отложенный пункт (WAITING_EXTERNAL)

- **Тик 07:00 UTC** (далее 13:00): `NOT_BEFORE 2026-10-17 07:20 UTC` (старт тика 07:00:05; исторически раны проходили за 10.5–16 мин).
  Триггер: cron. Речек: один read-only прогон обновлённого скрипта после ~07:25 UTC, вывод → `tick-25883-run2.txt`
  (`py -3 OPENCODE_WORKFLOW_SCRATCH\deploy25883\verify_after_tick_25883.py > OPENCODE_WORKFLOW_SCRATCH\tick-25883-run2.txt 2>&1`).
  Авто-возобновления нет — нужен внешний запуск. Без него полное 3-тиковое подтверждение отсутствует.

## Происхождение захвата / коннект-дисциплина

- В 05:32 UTC run-файла не было (проверено). Файл появился 05:46:37–05:46:50 UTC; внутри — полный прогон **исправленной** версии
  скрипта (имена `aftertick*`, V5-метки) ровно по предписанному шаблону команды.
- **Мой** guarded-запуск не исполнялся (guard сработал → второго коннекта нет). Точный исполнитель 05:46-коннекта локально
  недоказуем; в лейне ровно один свежий прод-захват, дублей нет.
- **Предшественник**: прод-контакт не подтверждается (нет run-файла до 05:46; нет свежих файловых следов на сервере в его окне).
  Ранний сбой до файловых записей неисключим без auth.log — коннект на это в лейне не тратился.

## Остаточные риски

- Tick-сторона инцидента закрыта на 2/3: без речека после 07:00 UTC нет полного подтверждения «все тики 2.58.83 чистые».
- Одна ERROR-строка ≥18:11 без текста — снимет речек (дамп уже в скрипте).
- Предсуществующее: L2→legacy-деградация и cover-фолбэки (не INC-SUMMARY-01); UI-бейдж фантома (бэкфилл сознательно не делался).
