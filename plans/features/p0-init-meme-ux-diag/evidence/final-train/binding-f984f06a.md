# P0IM final train — объединённый кандидат `f984f06a`

> **ОБНОВЛЕНИЕ (BAN-CONFLATE).** После ревью `262f7f18` счётчик `generated` исправлен:
> он больше не растёт от одного этапа `publish`, а требует доказанной картинки
> (этап `image_generation`, кроме терминального отказа генерации). Детали, регресс
> `old-1` и мутации — в `binding-ban-conflate-2d41f2b3.md`; строка `P0IM-BAN-CONFLATE`
> перепроверяется Reviewer, этот файл её не подтверждает.

> **ПОЗДНЯЯ КОРРЕКЦИЯ (см. `binding-durability-926b093a.md`).** В §2 строка
> «§1.3 … соответствует» относилась к переносу удержанной строки ТЕМ ЖЕ объектом
> журнала. Architect нашёл окно: production создаёт новый `SqliteQuotaLedger` на
> каждый проход, поэтому перенос между экземплярами не работал. Исправлено в
> кандидате `926b093a`; этот файл остаётся привязкой полосы экранных пробелов
> (`f2d3619d`) и не подтверждает durability-строки в одиночку.

**Эпик:** `P0-INIT-MEME-UX-DIAG`. **База:** production `6c11fc08` (2.58.194).
**Кандидат (код):** `f984f06a3742f403eeec8499dc49adb803e167ae`, ветка `fix/p0im-final-train`.
**Worktree:** `WorkspaceData/worktrees/c742e4de9e92c489/p0-init-meme-ux-diag-3d0ee4a97508-554fe8dd`.
**Состав:** два входных коммита, сведённые без правок кода (blob-и идентичны источникам):

| порядок | источник | тема | файлов |
|---|---|---|---|
| 1 | `16cdb3b8` | durable-запись терминальной строки (инвариант D) | 2 |
| 2 | `f2d3619d` | устаревание, счётчики, длительность/ID шага, модель шага | 9 |

Порядок выбран так: сначала маленькая правка писателя журнала (`services/meme_initiative.py`),
затем аддитивные поля читателей. Пересечений по файлам нет, конфликтов не возникло;
`git cherry-pick` обоих прошёл чисто.

Документарная привязка — отдельный коммит `8c041419` поверх кандидата кода (этот файл), поэтому
кандидат `f984f06a` остаётся неизменным.

**Линия:** база `6c11fc08` (production 2.58.194) достижима только через ветки `release/2.58.194`,
`fix/p0im-product-gaps`, `fix/meme-attempt-durability`, `fix/p0im-final-train` — в `master`
(`06b29363`) этого коммита нет (`git merge-base --is-ancestor 6c11fc08 master` → 1). Интеграция
кандидата в `master` будет не-fast-forward; это вопрос линии релиза для DevOps, кода он не
касается.

## 1. Диф и границы

`git diff --stat 6c11fc08..f984f06a` (кандидат кода; док-коммит `8c041419` идёт сверху и добавлен отдельно) — ровно 11 файлов, 1367 вставок / 32 удаления:

```
services/initiative_diagnostics.py        98 +++-
services/meme_initiative.py              117 +++--
tests/js/initiative_ui_rework_test.js    131 +++-
tests/test_evol014_meme_initiative.py    274 ++++++
tests/test_initiative_publications_api.py 198 +++++
tests/test_meme_init_diagnostics.py      114 ++++
tests/ui_initiative_rework_e2e.py        179 +++-
web/api/initiative_publications.py       126 +++-
web/app.js                               126 +++-
web/index.html                            30 ++
web/static/app.css                         6 +
```

Проверено по диффу: нет `APP_VERSION`, пинов `requirements`, DDL/`ALTER TABLE`/`CREATE TABLE`,
флагов, `os.environ`, промптов, моделей, новых эндпоинтов и настроек. Единственное вхождение
`meme_settings` в диффе — аргумент теста (`test_meme_init_diagnostics.py`), не продуктовый код.
Схема, таблицы, очередь, планировщик не менялись.

Blob-равенство с источниками (кандидат = точная сумма двух коммитов):

| файл | blob в `HEAD` | равен источнику |
|---|---|---|
| `services/meme_initiative.py` | `28329181e1ab` | `16cdb3b8` ✔ |
| `tests/test_evol014_meme_initiative.py` | `6be870d022e5` | `16cdb3b8` ✔ |
| `services/initiative_diagnostics.py` | `d2fcbf37fef2` | `f2d3619d` ✔ |
| `web/api/initiative_publications.py` | `eb7fbae21f70` | `f2d3619d` ✔ |
| `web/app.js` | `33f07dd121c5` | `f2d3619d` ✔ |
| `web/index.html` | `26fbbd7923ae` | `f2d3619d` ✔ |
| `web/static/app.css` | `95030941ad3a` | `f2d3619d` ✔ |
| `tests/js/initiative_ui_rework_test.js` | `39d0d1b40585` | `f2d3619d` ✔ |
| `tests/test_initiative_publications_api.py` | `92fb9cad7184` | `f2d3619d` ✔ |
| `tests/test_meme_init_diagnostics.py` | `c2bfca90416f` | `f2d3619d` ✔ |
| `tests/ui_initiative_rework_e2e.py` | `c920d085f3fb` | `f2d3619d` ✔ |

SHA-256 диффа durability-части (`git diff 6c11fc08..77b9110d`):
`5db0f9a951cda5228f13a12ca27e423125784ea645a8ed15abb3fe9e69ea3106`.

## 2. Соответствие решению `architecture-identity.md` §1–§2

| пункт решения | как в коде кандидата | вывод |
|---|---|---|
| §1.1 `_spool_payload(row)`, 11 существующих полей, формат не изобретать | `SPOOL_FIELDS` = прежний набор; хелпер используется в `_spool_attempt` и в аварийном логе | соответствует |
| §1.2 отказ ДВУХ носителей → `self._unpersisted` (список на экземпляре, `ATTEMPT_UNPERSISTED_MAX = 200`), вытесняемая строка пишется в лог ЦЕЛИКОМ, `json.dumps(_spool_payload(row))`, `attempt_id` без усечения | `_hold_unpersisted` + `_log_held_row`; `[%s] note` (`held` / `evicted over cap=200`), `row=<полный JSON>` | соответствует |
| §1.3 `_retry_unpersisted()` в начале `record_attempt` после `_flush_pending_attempts()`; на строку одна попытка журнала → при отказе одна попытка спула; успех любого убирает; ≤ `ATTEMPT_SPOOL_BATCH`; не бросает | ровно так; при неудаче первого ряда путь прерывается (строки остаются удержанными) | соответствует |
| §1.4 идемпотентность (`INSERT OR IGNORE` + слияние по `attempt_id`) | не менялась; удержание дополнительно не дублирует один `attempt_id` | соответствует |
| §1 «читатели, группировка, формат спула, схема не меняются» | `attempts()`, `_parse_spool_row`, `_flush_pending_*` не тронуты | соответствует |
| §2 `P0IM-ID-CONC` — только тест | `test_id_conc_aggregator_keeps_chats_and_competitors_apart` | соответствует |

Отклонений от решения не найдено; правок в код не потребовалось.

## 3. Привязка строк

Реальные строки карты (`requirements-map.json`):

| строка | статус до | что даёт кандидат | вердикт |
|---|---|---|---|
| `P0IM-ID-FINISH` (`RW-D4-BOTH-WRITE-FAIL`) | VERIFIED на `16cdb3b8` | код и тест **побайтово те же** (blob `28329181e1ab`/`6be870d022e5`), дифф-хеш выше | привязка к `f984f06a` законна, строка не переоткрывается |
| `P0IM-PB-LLM` | PENDING | добавлено только честное представление провайдера/модели/слота шага: `null` + `reason` (`not_recorded_in_stage_record` / `not_recorded_in_event_record`), текущие настройки не подставляются; записанные ключи уезжают как есть | **НЕ закрыта.** Приёмка строки требует версий/источников системных промптов, реально отправленных messages, image-запроса/ответа, формата картинки — этого в кандидате нет; строка остаётся PENDING |
| `P0IM-PB-TRACE`, `P0IM-PB-ROW` | VERIFIED | расширены теми же полями (длительность/ID/LLM в шаге, `generated` в счётчиках) | не переоткрываются, регрессий не найдено |

Обозначения из сообщения коммита `P0IM-PB-VOCAB`, `P0IM-PB-COUNT`, `P0IM-PB-STEP`,
`P0IM-BAN-CONFLATE` **отсутствуют в карте требований** (проверены все 42 `items`): они существуют
только как метки коммита. Поведение по ним реализовано и проверено (ниже), но формальную строку
карты для них должен определить PM/Architect — Builder новых требований не создаёт.

## 4. Наблюдаемое поведение по пяти заявленным пунктам

### 4.1 `P0IM-PB-VOCAB` — третье состояние `stale`

- API (`services/initiative_diagnostics.py`): `data_state = "ok" | "no_data" | "stale"`; добавлены
  `stale`, `stale_reason`, `stale_age_seconds`, `stale_window_seconds`, `stale_window_basis`
  (внесены в `MECHANISM_BLOCK_FIELDS`). Окно не выдумывается UI: у мема — `cooldown_seconds`
  из записанной записи прохода (`basis=cooldown`), у текста — действующий
  `eval_min_interval_seconds` (`basis=eval_interval`); см. ограничение в §7.
  Нет записи → `no_data` (не `stale`); нет окна → `stale=false`,
  `stale_reason="window_not_recorded"`, `stale_window_seconds=null`, подпись окна пустая.
- UI: бейдж «данные устарели», отдельная поясняющая строка; «нет данных» не подменяется.
- Факт на экране (e2e, 1536 и 390): `meme="данные устарели"`, `staleAttr="true"`,
  `"запись старше своего окна: возраст 7 ч при окне 6 ч (по своему кулдауну)"`,
  `"…возраст 2 ч при окне 1 ч (по интервалу оценки)"`, `hScroll=0`. Без окна:
  `state="данные есть"`, `note="окно свежести не записано — возраст записи не с чем сверить"`.
- Тесты: `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` (реальный сборщик,
  реальный SQLite; 4 состояния + негатив без окна), JS `productGapsSuite` п.1, e2e `run_stale_state`.

### 4.2 `P0IM-PB-COUNT` — `llm_calls` и `images`

- Те же `rows` и то же окно, что у прежних счётчиков (`checked/decided/…`): отдельного окна,
  фильтра и эндпоинта нет. Имена этапов сверяются с `meme_initiative.STAGE_*` тестом.
- На экране: `за 7 дн.: проверено 2 · решено 2 · сгенерировано 2 · опубликовано 2 · доставлено 2 ·
  ожидает 0 · … LLM-вызовы 4 · изображения 2 · текст 0 · мемы 2`.
- Тест: `test_counts_carry_llm_calls_and_images_separately` (пересчёт по отданным строкам,
  `llm_calls == 3`, `images == 2`, числа не равны друг другу; отсутствующие ключи → `null`, не 0).

### 4.3 `P0IM-PB-STEP` — длительность и ID запроса

- `duration_ms` у мема — `null` + `duration_reason="step_timing_not_recorded"` (журнал пишет одну
  метку старта), `request_id` = записанный `job_id` попытки, `request_id_source="journal_job_id"`;
  историческая строка без родителя → `request_id=""`, `request_id_source="not_recorded"`.
  Для событий текста `duration_ms` сохраняется, если записан (`duration_reason=""`), иначе
  `duration_not_recorded`.
- На экране у каждого шага: «длительность: длительность не записана» и «запрос: job-77».
- Тесты: `test_step_carries_duration_or_reason_and_recorded_request_id`,
  `test_step_has_no_invented_request_id_for_historical_rows`, JS п.3, e2e проверки шага.

### 4.4 `P0IM-BAN-CONFLATE` — `generated` отдельно

- `generated` считается по наличию этапа `publish` (достижим только после реально полученной
  картинки: отказ генерации пишется этапом `failed`, а не `publish` — проверено по всем точкам
  записи `stage=STAGE_PUBLISH` в `services/meme_initiative.py`).
- На экране «сгенерировано 2 · опубликовано 2» при «проверено 10 · решено 10» в сценарии review4 —
  величины не склеены.
- Тест: `test_generated_is_not_considered_and_not_published` (`checked=4`, `generated=1`,
  `published=0`; у упавшей генерации `image_generation` есть, `publish` нет).

### 4.5 `P0IM-PB-LLM` — записанное или честный `null`

- `_llm_fields` читает только запись (в т.ч. вложенный `llm`): `provider/model/slot`,
  `recorded_keys`, `reason`. Текущие настройки не читаются вовсе (импорт настроек в модуле
  отсутствует). На экране при отсутствии записи: «провайдер/модель/слот не записаны».
- Тест: `test_step_llm_fields_are_record_or_honest_null` (негатив «не записано» + позитив
  «запись всё же несёт `cx / cx/gpt-5 / writer` — уезжает как есть»).

## 5. Мутации (проверены независимо, не по прозе коммита)

Каждая мутация применялась байтовой правкой, прогон — только затронутые тесты, затем файл
восстановлен из копии (`git status` чист после каждого шага).

| # | мутация | что сломано | результат |
|---|---|---|---|
| M1 | `web/app.js`: `isStale: false` | «устарело» больше не отличается от «есть данные» | JS `AssertionError` (strictEqual) — поймана |
| M2 | `web/api/initiative_publications.py`: `if True:` вместо проверки этапа `publish` | `generated` = «все рассмотренные» | `test_generated_is_not_considered_and_not_published` FAILED |
| M3 | `_step_timing`: `duration_ms = 0` вместо `null` | неизмеренная длительность выдана за 0 мс | `test_step_carries_duration_or_reason_and_recorded_request_id` FAILED |
| M4 | `_data_state`: `stale → DATA_NO_DATA` | «устарело» слито с «нет данных» | `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` FAILED |

Итог: заявление «три мутации пойманы» подтверждается; независимо проверены четыре (включая
словарную), ни одна не выжила.

## 6. Прогоны (все на `f984f06a`, cwd = worktree кандидата)

| команда | результат |
|---|---|
| `pytest tests/test_evol014_meme_initiative.py` | **56 passed** |
| `pytest tests/test_initiative_publications_api.py tests/test_meme_init_diagnostics.py` | **78 passed** |
| `pytest tests/test_evol014_ui.py` | **17 passed** |
| `node tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` |
| `node tests/js/meme_ui_fields_test.js` | `MEME-UI-FIELDS-OK` |
| 15-файловая серия мемов/инициативы/публикаций/диагностики (тот же набор, что в binding `16cdb3b8`) | **362 passed, 4 failed** |
| `tests/ui_initiative_rework_e2e.py` (1536/1024/390) | **failures=2**, оба воспроизводятся на базе |
| `tests/ui_meme_ui_fields_e2e.py` | **failures=0** |

Предсуществующие провалы (не вызваны кандидатом):

- 4 pytest: `test_act_on_opportunity_conflict_defers_to_intent`,
  `test_evaluate_phase_precheck_blocks_before_llm`,
  `test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `test_t5_every_text_send_site_passes_publish_guard`. Контрольный прогон этих четырёх на базе
  `6c11fc08` (отдельный worktree, `-B`, без кэша): **те же 4 failed**. Текстовая полоса
  инициативы; `test_t5` падает на уже существующем неохранённом вызове шва
  `tools/rlr_live_proof.py:580`, к диффу кандидата отношения не имеет.
- 2 e2e: «после снятия override источник не "Исходный из кода": 'Состояние неизвестно · журнал
  недоступен'» (1536 и 390). Контрольный прогон того же e2e на базе `6c11fc08`: идентичные две
  ошибки, `failures=2`.

## 7. Что этим кандидатом НЕ доказано

- **Живой прод не проверялся**: кандидат не выложен (задание запрещает деплой). Все наблюдения —
  локальный worktree, реальные роутер/SQLite/сборщик и локальный браузер Playwright.
- `P0IM-PB-LLM` закрыта только в части «ничего не выдумано»; остальные пункты приёмки строки
  (промпты/messages/ответ image API/формат картинки) не реализованы — строка остаётся PENDING.
- «Устаревание» на экране проверено на управляемом ответе e2e-стенда (`diag_mode="stale"`), а не на
  реальной просроченной записи в проде; сборщик проверен отдельно на реальном SQLite.
- **Окно свежести текста — действующая настройка, а не снимок на момент прохода.**
  `effective_limits()` читает текущий профиль чата (+ мягкую цель владельца), поэтому после
  изменения интервала оценка «устарело/свежо» может пересчитаться задним числом. У мема окно
  берётся из записанной записи прохода (`cooldown_seconds`). Снять это полностью можно только
  записью интервала в момент прохода — это изменение схемы, которое задание запрещает; поэтому
  ограничение фиксируется, а не «чинится» вслепую.
- `llm_calls` считает **записанные этапы** (шаг `summary`/`joke` пишется только при успехе),
  поэтому подпись «LLM-вызовы» строже значения: неудавшийся вызов в счётчик не попадает
  (докстринг API это оговаривает, UI — нет).
- Ассоциация шага текста с событием по совпадению `ts` (`eventByTs`) устойчива лишь пока события
  инициативы не пишут `duration_ms` (сегодня `services/initiative_observer.py` их не пишет вовсе);
  при появлении длительностей у нескольких событий одной секунды шаг может показать чужую.
- Телеграм-клиент, реальные чаты, image/LLM-провайдеры не задействованы.

## 8. Конфигурация, влияющая на приёмку

Новых флагов/настроек/дефолтов кандидат не вводит. Окно свежести и счётчики читают **уже
записанные** значения (`eval_min_interval_seconds`, `cooldown_seconds`); сохранённые
пользовательские настройки и override не меняются, приоритет разрешения настроек не тронут.
В тестах единственный override — `MemeSettings(cooldown_seconds=6*3600)` внутри теста; прод-дефолты
не изменялись. Правило «новая функция включается по умолчанию при первом выкладе» здесь неприменимо:
включать нечего.
