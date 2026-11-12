# Closure train C-rows — привязка к коду `0398675a`

Эпик: `p0-init-meme-ux-diag`. База: `c134f93d` (release/2.58.195, production).
Ветка: `fix/p0im-closure-train`. Код-кандидат: `0398675a136bbc55e2b9950ff1486de3002b765e`.
Документ: привязка доказательств Builder; статусы строк НЕ переведены — это
делает Reviewer/PM.

Диапазон изменения против базы: 14 файлов, +1703/−52. Код и тесты в одном
коммите `0398675a`; этот документ — следующий docs-коммит.

Новых таблиц, колонок, флагов, настроек, промптов, моделей, эндпоинтов и
планировщиков нет. Полный текст промптов по-прежнему не пишется в журнал
попытки: единственный носитель — существующее in-memory кольцо
`prompt_composer.provider_calls` (24 записи на чат, память процесса).

---

## 1. `P0IM-PB-LLM` (items[23], add[44])

**Что сделано.** В существующий `detail` этапов добавлена короткая
идентичность фактического вызова и промптов; полные тексты не записываются.

| Факт | Где | Строка |
|---|---|---|
| provider/model из того же клиента, `slot=null` + `slot_reason="slot_not_used"`; при тестовом/диагностическом шве — честная причина `custom_step_hook` | `services/meme_initiative.py` | `_llm_identity` 3926 |
| prompt source/revision/sha12 (без текста) | `services/meme_initiative.py` | `_prompt_identity` 3958 |
| этап A: `llm` + `prompt` в фактах `summary` | `services/meme_initiative.py` | 3366 |
| этап B: `llm` + `prompt` в фактах `joke` | `services/meme_initiative.py` | 3414 |
| этап C: `prompt_sha12`, `api.status/format/bytes/bytes_present` (формат — из имени файла провайдера, если оно есть) | `services/meme_initiative.py` | 3430, 3500 |
| формат из имени файла + сохранение имени в результате `_default_image` | `services/meme_initiative.py` | `_image_format` 3973, `_default_image` 4167 |
| тот же `llm`-блок уже отдаётся в `chain[].facts` read-model — новый API не нужен | `web/api/initiative_publications.py` | `publication_detail` 1018+ |

**Полный текст (PB-ACCESS ниже).** API трассы отдаёт `full_text`:
`steps[summary|joke].correlation_id = "{job_id}#meme_summary|#meme_joke"`.
Кольцо реально ключуется этими id: `_default_summarize` передаёт
`correlation_id=f"{jid}#meme_summary"` (meme_initiative.py:3344) и
`_default_joke` — `f"{jid}#meme_joke"` (3389). Если кольцо записи не содержит —
`recorded=false, reason="not_recorded", reason_detail="provider_ring_miss"`;
историческая строка — `reason="full_text_not_recorded"`.

**Тесты.**
- `tests/test_evol014_meme_initiative.py::test_llm_identity_is_short_and_full_text_stays_out_of_journal`
  — реальные дефолтные шаги A/B с клиентом-швом: identity/промпт/Image API
  записаны; correlation id, переданные пайплайном, совпадают с теми, что ищет
  API; в дампе журнала нет ни ответа модели, ни текстов промптов.
- `tests/test_initiative_publications_api.py::test_detail_carries_llm_identity_without_full_text`
  — настоящий роутер + SQLite: identity в `chain[].facts`, ключей
  `messages/text/system/summary/joke` в фактах нет.
- `tests/test_initiative_publications_api.py::test_detail_full_text_is_existing_inspector_or_honest_not_recorded`
  — промах кольца → `not_recorded`; после записи в кольцо `recorded=true`, а
  текст в detail НЕ уезжает; политика хранения названа (`24`, `process_lifetime`).

**Честные пределы.** Кольцо — 24 записи на чат в памяти процесса; после
рестарта/вытеснения текст недоступен (так и показывается). Реальный HTTP-вызов
LLM в тестах не выполняется; идентичность проверена на шве клиента, который
использует боевой `_record_provider_call`.

---

## 2. `P0IM-PB-ACCESS` (add[46])

**Что сделано.** Защищённое раскрытие полного текста — существующий
`GET /api/speech/inspector` + существующий `_can_edit_inspector` + существующая
маскировка `_mask_text`. Добавлен аддитивный отбор `correlation_id`.

| Факт | Где | Строка |
|---|---|---|
| аддитивный параметр запроса, RBAC не изменён | `web/api/speech.py` | `get_inspector` 4258 |
| точный отбор только по correlation id, без «последнего» вызова/превью | `web/api/speech.py` | `_inspector_payload` 2072+ |
| промах кольца — `status=not_recorded`, пустые messages/system (не превью) | `web/api/speech.py` | `_inspector_missing_exact` 2052 |
| явные поля ответа: `requested_correlation_id`, `requested_correlation_recorded`, `ring_limit`, `retention` | `web/api/speech.py` | 2254–2278 |
| ссылка на существующий Inspector и политика хранения в трассе | `web/api/initiative_publications.py` | `_full_text_evidence` 172, ответ 1103 |
| действие в трассе «Полный текст в Inspector →» | `web/app.js` | `iniOpenInspector` 16380 |
| запрос Inspector с correlation id; обычный вход сбрасывает отбор | `web/app.js` | 31577+, `openSpeechSection` 31397 |
| запрошенный correlation_id не даёт переключиться на «предпросмотр» | `web/app.js` | `setSpeechInspectorMode` 19686; `web/index.html` 13349/13402 |
| промах корреляции показан как «не записано» | `web/index.html` | 13393; `web/app.js` `speechExactLabel` 33263 |

**Тесты.**
- `tests/test_speech_inspector_exact.py::test_inspector_correlation_filter_returns_the_exact_meme_call`
  — админ видит СВОЙ вызов; другой чат/другая корреляция не подставляются;
  секрет `sk-live-…` замаскирован.
- `::test_inspector_correlation_miss_is_not_a_preview` — промах: `not_recorded`,
  `messages=[]`, `system=""`, а не текущие настройки.
- `::test_inspector_correlation_path_keeps_rbac` — 403 не-админу (тот же гейт).
- `::test_inspector_endpoint_passes_the_correlation_query` — параметр доходит до
  payload; без него поведение прежнее.
- `tests/test_initiative_publications_api.py::test_detail_does_not_mix_chats` —
  detail из чужого `X-Chat-Id` не даёт ни строк, ни текста.
- JS `closureTrainSuite` — нота хранения/`not_recorded`, действие и URL
  Inspector'а, сброс отбора при обычном входе.

**Честные пределы.** Кольцо — процесс/24 записи; «исторически не сохранялось»
показывается как `full_text_not_recorded`. Реальный браузерный переход в
Inspector проверен JS-навигацией; полный e2e-сценарий «трасса → Inspector» не
добавлялся (существующий Inspector покрыт своими e2e).

---

## 3. `P0IM-PB-MANUAL` (add[45])

**Что сделано.** Шаг «Приоритет /meme» показывает уже записанный
`priority_marker` (`ok`/`until`/`detail`) и факт снятия. После фактического
`release_manual_priority` в ТУ ЖЕ терминальную строку существующего `detail`
дописывается `{"manual_priority_release": {"released": true, "until": N}}` —
слияние JSON, без схемы/второй строки/второй попытки.

| Факт | Где | Строка |
|---|---|---|
| слияние в терминальную строку (выбор строки — тем же порядком `STAGES`, что read-model) | `services/meme_initiative.py` | `merge_terminal_facts` 1465 |
| запись факта после успешного снятия; `job_id` из `RunTrace` | `handlers/meme_command.py` | 200, 228–244, вызов 397 |
| шаг трассы: marker + release, иначе `release_not_recorded` | `web/app.js` | 3903+ |

Логика маркера/снятия не менялась: TTL, адресация по `until`, снятие на
успехе/отказе/исключении/отмене — прежние. Аннотация выполняется только при
`cleared=True`; повторное снятие ничего не перезаписывает.

**Тесты.**
- `tests/test_p0im_s5_meme_marker_interrupt.py::test_release_is_appended_to_the_same_terminal_attempt`
  — факт в терминальной строке; повторное снятие: 0 новых строк, факт прежний,
  одна попытка.
- `tests/test_initiative_publications_api.py::test_detail_terminal_row_carries_manual_priority_release`
  — read-model отдаёт marker в `considered` и release в `publish`, `chain_len`
  не меняется.
- JS `closureTrainSuite` — `marker ok/until` и «маркер снят» в шаге; историческая
  строка — `release_not_recorded`.

**Честные пределы.** Если строка попытки не попала в таблицу (спул/оба носителя
недоступны), аннотация не создаёт новую строку — в трассе будет
`release_not_recorded`. Это осознанно: второго носителя нет.

---

## 4. `P0IM-OV-LIST` (add[31])

**Что сделано.** Строки значимых событий обзора (до 5) показывают способ
попытки: `вручную (/meme)` / `автоматически` / `способ не записан`. Источник —
уже пришедший `analytics.attempts`; берётся ТОЛЬКО `attempt_mode` из detail
терминальной строки (ключ `mode` у этапа «прикол» — бюджет длины и не
используется). Нового API/запроса нет.

| Факт | Где | Строка |
|---|---|---|
| разбор `attempt_mode` и подпись строки | `web/app.js` | `initiativeRecentEvents` 10745+ |
| видимая метка в строке события | `web/index.html` | 2208 |

**Тесты.** JS `closureTrainSuite`: manual/auto по терминальной строке, `mode`
этапа «прикол» не выдаётся за способ, историческая строка — «способ не записан».

**Честные пределы.** Обзор получает `analytics.attempts` ограниченным окном
(20 строк этапов). Для очень длинной серии попыток терминальная строка
конкретной попытки может не попасть в окно → честная метка «способ не
записан» (не выдуманный manual/auto). Отдельный запрос ради метки не вводится
по условию «только app.js».

---

## 5. `P0IM-S6-EFFECTIVE` (add[65])

**Что сделано.** В существующем `collect_mechanism_diagnostics` (payload
обзора инициативы):
- гейт `image_module` называется ВСЕГДА (а не только при OFF), `enabled` — из
  существующего `image_dependency.module_enabled`; `layer=global`;
- `heartbeat_ok`/`heartbeat` — из уже посчитанного `_health` (тот же источник
  тика, что `initiative-vitality`);
- `meme.image_provider` — проекция существующего `image_dependency`
  (available/configured/module_enabled/reason/health/model).

| Факт | Где | Строка |
|---|---|---|
| `image_module` всегда, слой/причина | `services/initiative_diagnostics.py` | 2386+ |
| `image_provider` в блоке мема; `None` у текста — форма одна | `services/initiative_diagnostics.py` | 3205, 2889+ |
| `heartbeat_ok`/`heartbeat` в payload | `services/initiative_diagnostics.py` | 3448+, 3470 |
| контракт полей (документированная форма) | там же | `MECHANISM_BLOCK_FIELDS` 1222, `IMAGE_PROVIDER_FIELDS`, `HEARTBEAT_FIELDS` |
| UI: существующая техническая панель — строки heartbeat и провайдера | `web/app.js` 3144/3163, `web/index.html` 3594, 3724 |

**Тесты.**
- `tests/test_p0im_s6_fresh.py::test_image_module_gate_is_named_even_when_enabled`
  — ON: гейт есть, `enabled=true`, `layer=global`, причина пустая; OFF: тот же
  гейт `enabled=false`, `reason=image_module_off`, ось `enabled=false`.
- `::test_overview_projects_heartbeat_and_image_provider_for_both_chats` — два
  чата: `chat_id` свой, heartbeat=true из свежего тика, провайдер доступен,
  гейт присутствует; глобальные значения не «перетекают».
- JS `closureTrainSuite` — heartbeat живой/нет свежего/нет данных, провайдер
  доступен/недоступен (человеческая причина, не голый код), слои решения.
- `tests/test_meme_init_diagnostics.py` — форма блока и R17-гигиена обновлены
  вместе с контрактом (ключи `heartbeat*`, `image_provider` — только scalars).

**Честные пределы.** Живой снимок второго чата на этом кандидате не снимался —
это отдельная DevOps/Reviewer-проверка (как и записано в закрытии). Значения
heartbeat/provider — проекция существующих расчётов, не новая проверка.

---

## 6. `P0IM-AC-MATRIX-FAIL` (add[74])

**Новые тесты (в существующем файле мем-пайплайна):**
- `tests/test_evol014_meme_initiative.py::test_provider_failure_after_llm_stages_is_one_failed_attempt`
  — после обеих LLM-стадий провайдер падает: одна попытка, терминальный этап
  `failed`, `image_generation_failed`, ни `publish`, ни доставки, sender не
  вызывался.
- `::test_empty_image_content_is_an_honest_failure_not_publication` — `ok=True,
  content=None`: не публикуется, одна попытка, честный `detail=empty_content`,
  `generated=false`, доставки нет.

**Привязка уже существующих проверок (не переделывались):**
- ранние гейты с `job_id`: `test_evol014_meme_initiative.py::test_early_refusal_has_its_own_run_id`,
  `::test_cooldown_quota_quiet_refusals_carry_run_id`;
- конфликт отправок: `test_p0_meme_publication_hotfix.py::test_two_workers_in_one_chat_publish_exactly_once`,
  `::test_automatic_collision_after_generation_keeps_facts_and_does_not_send`;
- старые неполные записи: `test_initiative_publications_api.py::test_legacy_rows_without_job_id_are_marked_historical`.

---

## 7. Прогоны (кандидат `0398675a`, база `c134f93d`)

`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, изолированные temp-SQLite;
production не затрагивался.

| Команда | Результат |
|---|---|
| pytest `tests/test_evol014_meme_initiative.py` | **61 passed** (было 58; +3) |
| pytest `tests/test_initiative_publications_api.py` | **40 passed** (было 35; +5) |
| pytest `tests/test_meme_init_diagnostics.py` | **44 passed** |
| pytest `tests/test_p0im_s6_fresh.py` | **12 passed** (было 10; +2) |
| pytest `tests/test_p0im_s5_meme_marker_interrupt.py` | **16 passed** (было 15; +1) |
| pytest `tests/test_publication_binding_delivery.py` | **8 passed** |
| pytest `tests/test_speech_inspector_exact.py` | **21 passed** (было 17; +4) |
| Совместный прогон семи файлов выше | **202 passed**, 1 warning (deprecation) |
| `node tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` (новый `closureTrainSuite`) |
| `node tests/js/p0im_ov_honesty_test.js` | `P0IM-OV-HONESTY-OK` |
| pytest `tests/test_webapp_js_unit.py` | **45 passed** |
| `python tests/ui_initiative_rework_e2e.py` | **failures=2** — ровно те же 2 предсуществующих («Исходный из кода · журнал недоступен», 1536/390), что на 2.58.195 |
| `python tests/ui_meme_ui_fields_e2e.py` | **failures=0** |
| 5 привязанных тестов AC-MATRIX-FAIL | **5 passed** |

Уже закрытые этим поездом строки не регрессировали: PB-VOCAB/PB-COUNT/PB-STEP/
BAN-CONFLATE/ID-FINISH/ID-CONC проходят в тех же файлах (44 diagnostics,
40 publications, 61 evol014), счётчики и `generated` не менялись.

E2e запускает собственный сервер и снимает его сам; браузеры/процессы после
прогонов закрыты.

---

## 8. Отрицательные случаи (явно проверены)

1. Промах кольца (`provider_ring_miss`) → `not_recorded`, `messages=[]`,
   `system=""`: текущие настройки НЕ выдаются за фактический запрос.
2. Историческая строка → `full_text_not_recorded`, полный текст не
   подставляется.
3. Чужой `X-Chat-Id`/другая корреляция → нет строк, нет текста другого чата;
   секрет в тексте замаскирован.
4. Не-админ → 403 на том же `_can_edit_inspector` (аддитивный параметр не
   обходит RBAC).
5. Повторное снятие маркера → 0 новых строк/попыток, успешный факт не
   перезаписывается.
6. Пустой `content` при `ok=True` → не публикуется, честный `empty_content`.
7. Сбой провайдера после A/B → один failed-исход, без `publish`/доставки.
8. `attempt_mode` отсутствует/историческая строка → «способ не записан», а не
   выдуманный manual/auto.
9. `image_module` выключен → тот же гейт с `enabled=false` и
   `reason=image_module_off`; неизвестный провайдер — «неизвестно», не «доступен».

---

## 9. No-new-store statement

Новых хранилищ нет. Изменения используют только существующие поверхности:
журнал попыток `meme_initiative_attempt` (существующее поле `detail`),
`prompt_composer.provider_calls` (существующее кольцо 24/процесс),
`GET /speech/inspector` с существующими RBAC/маскировкой, существующий
read-model `initiative_publications`, существующий overview payload
`collect_mechanism_diagnostics`. DDL=0, новых флагов/настроек/промптов/моделей
нет. Полные тексты промптов в durable-журнал не пишутся.

---

## 10. Effective-конфигурация

Новых acceptance-флагов нет; поведение безусловное. Проверенные effective-
варианты: `image_dependency.module_enabled=true` (основной путь; гейт `enabled`,
провайдер доступен) и `false` (негатив: гейт выключен с причиной
`image_module_off`). Heartbeat проверен на свежем тике (true), без тика
(false/нет данных). Тестовые подмены — только существующие швы
(`image_dependency`, `_initiative_observer_last_tick`, кольцо композера);
feature-off прогонов, скрывающих основную функцию, нет.

Prod 2.58.195 не изменялся. Живой снимок payload этого кандидата на двух чатах
и effective-значения прода — за релизным шагом DevOps/Reviewer (код не
выкладывался).

---

## 11. Находки

- `IN_SCOPE` (исправлено): при тестовом/диагностическом шве шага A/B журнал
  получил бы модель клиента, который вызов не делал. Добавлена честная причина
  `custom_step_hook`; identity пишется только для реального клиента.
- `IN_SCOPE` (исправлено): прежний гейт `image_module` при OFF имел
  `scope="chat"`, хотя модуль картинок — общий слой. Теперь `scope=global`
  (слой `global`), как в привязке S6-EFFECTIVE; логика OFF не менялась.
- `BACKLOG_ONLY` (не блокирует): обзор получает `analytics.attempts`
  ограниченным окном 20 строк этапов; у длинной серии попыток терминальная
  строка конкретной попытки может не попасть в окно, и OV-LIST честно покажет
  «способ не записан» вместо manual/auto. Репро/идея: при необходимости
  расширить окно чтения analytics для обзора — но это отдельная правка
  read-model, не входящая в закрытие (условие «только app.js»).
- `CRITICAL_OUT_OF_SCOPE`: нет.

---

## 12. Diff vs `c134f93d`

```
 handlers/meme_command.py                    |  28 +-
 services/initiative_diagnostics.py          |  72 +-
 services/meme_initiative.py                 | 143 +-
 tests/js/initiative_ui_rework_test.js       | 341 ++++
 tests/test_evol014_meme_initiative.py       | 188 +++
 tests/test_initiative_publications_api.py   | 176 +++
 tests/test_meme_init_diagnostics.py         |   5 +
 tests/test_p0im_s5_meme_marker_interrupt.py |  36 +
 tests/test_p0im_s6_fresh.py                 | 113 ++
 tests/test_speech_inspector_exact.py        | 102 ++
 web/api/initiative_publications.py          |  74 +
 web/api/speech.py                           | 123 +-
 web/app.js                                  | 258 +-
 web/index.html                              |  70 +
 14 files changed, 1703 insertions(+), 52 deletions(-)
```

Housekeeping: временный probe-каталог
`WorkspaceData/runs/.../probe-0c6f7f4fde` закрывается после сдачи
(run-close --confirmed-idle --confirmed-evidence); worktree остаётся для
Reviewer/DevOps, пока кандидат не интегрирован.
