# M5A — EXP-FIX-01..07, 09, 10: доказательство кандидата `4e07817e`

Артефакт связывает строки среза **M5A** карты требований с фактически проверенным
кандидатом. Составлен PM после независимого вердикта Reviewer (Approved по поведению
EXP-FIX-01, 02, 03, 04, 05, 07, 09, 10) и передаёт его по-строчный леджер, воспроизведение
частичной записи, счётчики тестов и честную границу непроверенного. Продуктовый код в этом
проходе не менялся; тесты PM не перепрогонял (см. §5).

## 1. Источник требований и границы среза

- Источник: `plans/owner_inputs/2026-11-09-mod-acl-ux-01.md`
  - §7.1, строки 371–380 — таблица подтверждённых кодом дефектов EXP-FIX-01…10;
  - §7.2, строки 388–396 — пакет немедленных исправлений, regression set (а)…(к),
    раздельная телеметрия `scheduler tick` / `review job` / `semantic batch`,
    запрет менять порог `MCA_LESSON_MIN_INDEPENDENT_EPISODES` и запускать полный backfill;
  - §7.3–7.4, строки 398–417 — узкая production-проверка (60–90 мин) и обязательный
    нативный `question` владельцу **после** неё.
- Карта: `plans/features/mod-acl-ux-01/requirements-map.json`, строки `MAC-EXP-01…10`
  (срез `M5A`; `MAC-EXP-08` — `M5B`, в этот артефакт не входит).
- Ограничение объёма, зафиксированное в кандидате: никакого нового воркера,
  планировщика, очереди или второго хранилища; исторический backfill не запускается;
  существующие курсоры и сохранённые данные не стираются.

## 2. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `4e07817e9a4836a6e68837bbb815aa3ffdfe3dc8` |
| Родитель | `d0127c292766974178b071a1aa4b24719e70b0c3` (MEMORY-08 S3) |
| Сообщение | `fix(exp-fix): M5A — durable semantic checkpoint, честный дренаж, typed parse/write` |
| Ветка | `integ/unify-release` (в `master` ещё не влит: `git merge-base --is-ancestor 4e07817e HEAD` → 1) |
| Worktree кандидата | `...\WorkspaceData\worktrees\c742e4de9e92c489\EXP-FIX-MOD-ACL-M5A-0e207bc7d1f9-4655c0d6` (detached `4e07817e`) |
| Изменено | `services/mca_experience_jobs.py`, `services/mca_experience.py`, `services/memory_maintenance.py`, `web/api/memory_overview.py`, `tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`, `tests/test_asap8_v63_b02_semantic_experience.py` (6 файлов, +1746/−120) |
| Развёрнуто | нет; `deployed_commit` карты пуст |

## 3. По-строчный леджер Reviewer (8 строк)

Столбец «код» — фактическое место в дереве кандидата (номера строк `git show 4e07817e:<файл>`).
Столбец «тест» — контрактные проверки того же кандидата
(`tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`), реальные SQL-строки, progress
`payload` и повторные прогоны, а не «функция вызвана».

| Строка | Что подтверждено на кандидате | Код | Контрактный тест | Статус |
|---|---|---|---|---|
| `MAC-EXP-01` | Новый `experience.review` наследует **полный** durable semantic checkpoint (watermark, per-chat `semantic_cursor:*`, `semantic_pending`, `semantic_last_ts`, момент появления бэклога, отложенные повторы, `resume_cursor`, версия схемы) с max/min-merge и проверкой целостности; позиции не откатываются, повторный job не начинает обход с начала | `_load_payload` 1010, `_normalize_semantic_state` 1041, `_inherit_cursor` 1093 (`mca_experience_jobs.py`) | `test_exp01_new_job_inherits_full_semantic_checkpoint`, `test_b_restart_after_checkpoint_and_between_insert_and_checkpoint` | VERIFIED (Reviewer) |
| `MAC-EXP-02` | Каденция продуктового review отделена от темпа дренажа: тик планирует следующую **ограниченную** порцию при накопленном бэклоге, объём — hot-параметры, per-chat справедливость, throughput/lag в `semantic_progress` и в API | `semantic_drain_limits()` 712, `semantic_progress_snapshot()` 734, ключи `memory.experience_drain_chats_per_pass` / `memory.experience_drain_per_chat_max` / `memory.experience_pending_chat_cap` 147/721/723/730 | `test_exp02_drain_limits_are_hot_configurable`, `test_i_backlog_larger_than_one_pass_drains_by_portions` | VERIFIED (Reviewer) |
| `MAC-EXP-03` | Окно возвращает прочитанные строки отдельно от пригодных; `semantic_pending` убывает на все прочитанные; пустое окно пересчитывает фантомный pending; выключенный/пустой чат не блокирует других; ошибка SQL — retryable, не skip | `semantic_window_lines()` 453, счётчик `semantic_read_errors` 612/1612, ветка retryable ~1554 | `test_c_fully_filtered_window_advances_pending_and_last_ts`, `test_c2_empty_window_reconciles_phantom_pending`, `test_d_disabled_and_empty_chats_do_not_block_others` | VERIFIED (Reviewer) |
| `MAC-EXP-04` | `accepted` / `duplicate` / `rejected` / `skipped` / `write_failed` различаются; при `write_failed` пакет не считается обработанным, позиция чата не двигается, повтор без дублей | `SEMANTIC_WRITE_FAILED` 167, `_write_semantic_candidate` 1963–2050, обработка в батче 2767–2779 | `test_e_write_failure_does_not_advance_and_retries_without_dupes` (+ независимое воспроизведение PM, §4) | VERIFIED (Reviewer) |
| `MAC-EXP-05` | `parse_semantic_candidates_typed` различает `valid_empty` / `valid_candidates` / `invalid_output` с причиной; при `invalid_output` позиция не двигается, включён отложенный повтор | `parse_semantic_candidates_typed` 471, исходы 504/545; `SEMANTIC_PARSE_*` 155–157 | `test_f_parse_typed_outcomes_unit`, `test_f_invalid_output_does_not_advance_but_valid_empty_does` | VERIFIED (Reviewer) |
| `MAC-EXP-07` | Повторная проверка `candidate/validated` ротирует окно durable-курсором (`resume_cursor`, порядок `created_at, lesson_id`) с wrap; старые невалидные кандидаты не занимают окно навсегда, не активируются и не удаляются | `RESUME_CURSOR_KEY` 131, `_resume_incomplete` 2073–2116, наследование курсора 1170 | `test_exp07_resume_window_rotates_over_all_candidates` | VERIFIED (Reviewer) |
| `MAC-EXP-09` | Идентичность сигнала уточнена семантическим видом/субъектом/версией сигнала (+ нормализованный носитель: pref-токен/тема); два разных кандидата одного `msg_id` не склеиваются; повтор идемпотентен; legacy-ключ проверяется для совместимости | `feedback_dedup_key(..., identity)` (`mca_experience.py` 208–218), `SEMANTIC_SIGNAL_IDENTITY_VERSION = 2` (`mca_experience_jobs.py` 173/2022) | `test_exp09_two_signal_kinds_one_message_stay_separate`, `test_exp09_two_preferences_one_message_distinct_carriers`, `test_j_dedup_prevents_duplicate_lesson_creation` | VERIFIED (Reviewer) |
| `MAC-EXP-10` | Durable-индекс чатов bounded; при переполнении discovery останавливается **до** непроиндексированной строки (backpressure), watermark не уезжает за непроиндексированные данные; >64 чатов + рестарт без потерь | `semantic_pending_chat_cap()` 728, `SEMANTIC_PENDING_CHAT_CAP` 147 (=256), stop-before-unindexed в `_semantic_discover` 1821–1835 | `test_exp10_many_chats_backpressure_no_message_lost`, `test_exp10b_more_than_64_chats_no_pending_key_dropped` | VERIFIED (Reviewer) |

Не входит в этот леджер: `MAC-EXP-06` (живая проверка OFF→ON→OFF, см. §6) и `MAC-EXP-08`
(срез `M5B`, не тронут).

## 4. Независимое воспроизведение частичной записи (`write_failed`)

Reviewer воспроизвёл сценарий отдельно от набора тестов Builder — на реальных строках БД,
с принудительным сбоем первой durable-записи:

| Шаг | Наблюдение |
|---|---|
| Первый проход, первая durable-запись падает | курсор чата остаётся `0`; `semantic_pending` остаётся `2`; в таблице feedback появляется **одна** строка (успешная запись батча не откатывается) |
| Повторный проход | появляются ровно **две** строки, у них **два разных** `dedup_key`; курсор сдвигается; `semantic_pending` очищается |

Что это доказывает по строкам карты:

- `MAC-EXP-04` — сбой записи не признаётся обработкой: позиция не двигается, пакет
  повторяется, повтор не создаёт дублей (первая строка не переписана вторым проходом).
- `MAC-EXP-09` — две разные семантические записи одной реплики получают разные
  `dedup_key` (иначе на повторе осталась бы одна строка и «второй сигнал» исчез бы).
- `MAC-EXP-03` — `semantic_pending` уменьшается согласованно с фактически выданными
  строками, а не «по факту вызова».

## 5. Тесты

Вердикт Reviewer, на кандидате `4e07817e`:

- **35 контрактных проверок** среза M5A — пройдены;
- соседний прогон **52 теста** затронутых/смежных модулей опыта — пройден.

Структурная сверка PM (без перепрогона, только дерево кандидата):

- `tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py` — 19 функций: (a) два job подряд,
  (b) рестарт между insert и checkpoint, (c) 10 из 10 отфильтрованы, (c2) пустое окно,
  (d) disabled/пустой чат, (e) SQL-сбой записи, (f) typed parse (unit + integration),
  (g) OFF→ON→OFF без рестарта, (h) LLM недоступен, (i) бэклог больше прохода,
  (j) дедуп, плюс EXP-01/07/09×2/10/10b/02;
- `tests/test_asap8_v63_b02_semantic_experience.py` — 13 функций, файл изменён кандидатом
  (прежнее утверждение теста фиксировало дефект EXP-FIX-09 и обновлено).

Расхождение 19+13=32 определений против 35 собранных проверок Reviewer объясняется
сбором pytest; PM эти числа как свои не выдаёт и в этом проходе тесты не перезапускал.

## 6. Честная граница: что этим артефактом НЕ доказано

1. **`MAC-EXP-06` — живая проверка OFF→ON→OFF.** Строка остаётся `PENDING`
   (`live_required: true`, `live_when: preprod`). Код регистрирует
   `experience_review_tick` всегда (`memory_maintenance.py` 182/314/388) и проверяет
   effective enablement внутри, но **живого** наблюдения «при OFF — ноль работы, ON без
   рестарта — работа пошла, снова OFF — работа остановилась» ещё нет. Ожидаемый артефакт —
   §7.
2. **Ограниченный production-proof M5C (§7.3–7.4 исходника).** Один заранее
   ограниченный read-only диагностический проход (целевой бюджет 60–90 минут):
   `deployed_sha`, effective K1–K4/UI-параметры, зарегистрированный job, last tick,
   `review_cadence`, последние 2–3 `experience.review` из `task_jobs` с counters и
   курсорами, сравнение watermark с максимумом `smart_messages.id`, backlog / age of
   oldest pending / обработано за 24 ч, counts по `mca_experience_episodes` /
   `mca_experience_feedback` / `mca_lessons` / `mca_lesson_applications`, причины
   `proposed=0`. Этот проход **предшествует** вопросу владельцу, но самим кодом не
   заменяется и здесь не выполнен. Если VPS/БД недоступны — фиксируется `unverified`
   с конкретной причиной, а не выдуманное production evidence.
3. **Нативный `question` владельцу** (продуктовая развилка о расширении предметной
   области уроков) — M5C; в этом артефакте не открыт и не закрыт.
4. **Деплой.** Кандидат не в `master`, `deployed_commit` пуст; release-gate по этому
   артефакту не проходит и не должен.
5. **Прочие строки среза M5A.** Карта относит к `M5A` ещё 15 строк, которые Reviewer в этом
   вердикте не перечислял: `MAC-S0-12`, `MAC-S7-390`, `MAC-S7-391`, `MAC-S7-392`,
   `MAC-S7-393`, `MAC-S7-394`, `MAC-S15-06`, `MAC-S15-1-03`, `MAC-S15-1-04`,
   `MAC-S15-1-05`, `MAC-S7-BOUND-01`, `MAC-S7-LIMIT-01`, `MAC-S7-EDGE-01`,
   `MAC-S7-PROOF-01`, `MAC-M5-01`. Часть из них по смыслу пересекается с проверенными
   тестами (regression set (а)…(к), раздельная телеметрия, backpressure, порог уроков
   не менялся), но **по-строчного подтверждения Reviewer по ним нет**, поэтому они остаются
   `PENDING`. Связывать их по догадке PM нельзя — нужен явный вердикт Reviewer или
   отдельная приёмка.

## 7. Ожидаемый артефакт для `MAC-EXP-06`

Путь: `plans/features/mod-acl-ux-01/evidence/m5a/mac-exp-06-live-offf-on-off.md`
(имя может отличаться, но артефакт должен быть реальным файлом в репозитории).
Обязательное содержимое, иначе строка не биндится:

- `deployed_sha` прод-сервера и подтверждение, что это код с тиком, зарегистрированным
  безусловно (не «по состоянию на старте»);
- доказательство регистрации `experience_review_tick` в живом планировщике (строка job,
  интервал 900 с, last tick) **при выключенном** пользовательском тумблере;
- наблюдение «при OFF — ноль работы»: за интервал тика нет семантических/LLM/SQL-операций
  контура опыта (счётчики не растут, записи в логах/событиях отсутствуют или фиксируют
  только резолв гейта);
- включение ON через реальную настройку (указать точный ключ и effective-значение) →
  **без рестарта процесса** (PID/uptime неизменны, время старта то же) следующий тик
  выполняет работу: появляется job/тик с counters, растут `semantic_*`;
- обратное выключение OFF → работа снова прекращается без рестарта;
- сохранность аварийного env kill-switch (при нём тик остаётся, работа не идёт);
- точные команды/запросы и временные метки каждого шага.

После появления такого файла строка `MAC-EXP-06` биндится с `type: "live"` и
`candidate_commit`, равным **развёрнутому** кандидату. Важное следствие для gate: если
развёрнутый SHA отличается от ревьюированного `4e07817e` (merge-коммит), карта не может
держать один `candidate_commit` для двух наборов доказательств — потребуется либо
перепривязка леджера к развёрнутому кандидату при неизменной идентичности кода, либо
отдельный review-прогон по развёрнутому SHA. Молча оставлять разные SHA в одной карте
нельзя.

## 8. Что этим изменением сделано в карте

- `candidate_commit` карты = `4e07817e9a4836a6e68837bbb815aa3ffdfe3dc8` (для review-гейта
  среза M5A);
- 8 строк `MAC-EXP-01,02,03,04,05,07,09,10` → `VERIFIED` с кандидат-привязанным
  доказательством на этот файл;
- `MAC-EXP-06` оставлена `PENDING` (живого доказательства нет);
- `MAC-EXP-08` (`M5B`) и строки M1–M4, M6 не тронуты.

## 9. Строгий гейт после привязки (фактический прогон)

```
cd C:\Code\Python\adminbot
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/mod-acl-ux-01/requirements-map.json \
  --stage review --slice M5A \
  --candidate 4e07817e9a4836a6e68837bbb815aa3ffdfe3dc8
```

Итог: `stage=review inventory=279 manual=88 scoped=24 errors=16` — все 8 связанных строк
EXP-FIX проходят (по ним ошибок нет). Оставшиеся 16 ошибок:

```
FAIL: MAC-S0-12: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-390: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-391: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-392: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-393: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-394: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S15-06: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S15-1-03: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S15-1-04: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S15-1-05: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-BOUND-01: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-LIMIT-01: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-EDGE-01: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-S7-PROOF-01: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-M5-01: mandatory not ['VERIFIED'] (got PENDING)
FAIL: MAC-EXP-06: mandatory not ['VERIFIED'] (got PENDING)
```

15 из них — строки §7/§15/`MAC-M5`, по которым этот вердикт Reviewer не выносил по-строчного
заключения (§6.5); 16-я — живая `MAC-EXP-06` (§6.1, §7). До закрытия этих строк гейт среза
остаётся красным, и это правильное состояние, а не дефект привязки.
