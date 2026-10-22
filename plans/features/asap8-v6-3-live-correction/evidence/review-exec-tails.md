# REV-ASAP8-EXEC — ревью лейна ASAP8-EXEC-TAILS (коммит 4f0ae438, база 20252faa)

Вердикт: **Approved** (лейн docs+tests+evidence; runtime-кода нет). 2026-10-21.

## Леджер приёмки

| Проверка | Статус | Evidence |
|---|---|---|
| Биндинги B10-R01/R13/R16/R07/R09/B12.6 → VERIFIED | VERIFIED | требования acceptance свергнуты с формулировками карты; артефакты probe-exec реальные (даты 21.10 UTC, prod-путь БД, run_id/sha12, journal-строки 19.10 SUMMARY_COMPLETE paragraphs=10 fallback=none) |
| Честность оговорок | VERIFIED | R01 «публикация рана 19.10 не состоялась (publication_status=failed)» — в reason+observation карты и в отчёте (capture2: state=FAILED/pub_ref=null); R16 «20/23»; R13 «полный pipeline-тайминг не инструментирован»; R07 «success-путь заблокирован внешним 407»; R09 «живой мутации не было (read-only)» — не ретушь |
| Тесты B12.6 (5 passed + 1 xfail) и R09 (1 passed) | VERIFIED | воспроизведено py -3 pytest: `5 passed, 1 xfailed` + `1 passed`; тесты гоняют реальные services (quote_resolver / chat_statistics.measure → numeric-гард / chat_migration / chat_params optimistic 409→refresh→retry), негативы + контрольные позитивы, не тавтологии; TEST-LIFECYCLE: REGRESSION owner=B12.6 / B10-R09 на месте |
| Инцидент backup-gap chat_running_summary | VERIFIED (реален) | chat_migration.py:127,133 `last_rid=-1` + `rowid > ?`; database.py:6402-6403 PK chat_id INTEGER PRIMARY KEY = rowid-алиас → отрицательный chat_id отсекается из backup, UPDATE переносит строку без backup-записи; strict-xfail воспроизводит. Прод не задет: capture1 §s4_chat_id_migrations=[] (read-only 21.10 09:10Z) |
| Вердикт по инциденту | ФИКС-ЛЕЙН ДА | обязателен ДО реального переноса supergroup (сейчас риск 0 — миграций не было); после фикса xfail станет XPASS → снять маркер |
| RFL-остатки (13 AR + 4 items) | VERIFIED | список точно соответствует: REQ-B02-DOD/V02/B10-R12 (PROBE-EXPERIENCE), REQ-B03-DOD/V03, REQ-B09-BODY/B10-R10, B10-R06/REQ-B11-E2E (квота: CoolingDown/429×331/FTS-only в journal 21.10), B10-R11 (частичный речек подтверждён capture1 §s4: 335/25/2/3), R14/R15/R19 — ни один не закрыт преждевременно |
| Гигиена | VERIFIED | git show 4f0ae438 --stat: ровно 9 заявленных файлов (5 evidence + prep-rfl-binding.md + map + 2 теста), runtime-кода нет; 2 правки U08.4d/U08.5.1-блоков карты — whitespace-only (--ignore-all-space пуст); гейт plan EXIT 0 (inventory=148, manual=75, errors=0) |

## Неблокирующие замечания

1. capture2 §s1_source_diff_same_chat: метки only_in_new/only_in_old и new_ids_sample перепутаны местами (скрипт пробы); суть (overlap=0, диапазоны id, атрибуция в отчёте) корректна. Косметика артефакта.
2. capture2 §s5 status обрезан до «HTTPSCo…» — литерала «407» в артефакте не видно; 407 доказуем контрактом кода: proxy_auth_failed классифицируется ТОЛЬКО на HTTP 407 / «Proxy Authentication Required» (youtube_transcript_engine.py:697-715, 890-915) + реальный живой прогон классифицирован. При желании — доснять полный текст исключения в фикс-лейне.

## Биндинг

Кандидат: 4f0ae4385e9ebec6893abdb815209b86d495cf3d (HEAD). Среда probes: прод 2.58.105 @a6246e33, repo-HEAD на момент проб bf17a972. Реверификация тестов: локально на 4f0ae438.
