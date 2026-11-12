# Closure train C-rows — привязка к коду `21a3aef7`

Эпик: `p0-init-meme-ux-diag`. База: `c134f93d` (release/2.58.195, production).
Ветка: `fix/p0im-closure-train`. Код-кандидат:
`21a3aef78dba022e52cff21f9a87cbbccfce55fe` (поверх `3b1c4ba9`; docs `87b5f0e4` —
предыдущая привязка). Документ: привязка доказательств Builder; статусы строк
НЕ переведены — это делает Reviewer/PM.

Диапазон изменения против базы: **15 файлов кода/тестов, +1891/−58** плюс этот
evidence-документ. Код-кандидат собран тремя коммитами: `0398675a` (закрытие
C-строк), `3b1c4ba9` (два блокера Reviewer) и `21a3aef7` (test-contract fix
после DevOps-остановки 2.58.196). Этот документ — следующий docs-коммит.

Новых таблиц, колонок, флагов, настроек, промптов, моделей, эндпоинтов и
планировщиков нет. Полный текст промптов по-прежнему не пишется в журнал
попытки: единственный носитель — существующее in-memory кольцо
`prompt_composer.provider_calls` (24 записи **на процесс**, общие для чатов;
память процесса).

---

## 0. Reviewer blockers на `0398675a` (tree `931945b7`) и исправление

Источник: `evidence/closure-train/review-931945b7.md` (Needs Fixes, только
P0IM-PB-ACCESS; остальные строки поезда были UNVERIFIED, не FAILED).

### Blocker 1 — correlation-режим отдавал превью текущей сборки

**Наблюдение Reviewer.** В ответе
`GET /speech/inspector?correlation_id=…` оставались `preview`
(`system_masked` 9185 знаков, «РОЛЬ И ЗАДАЧА…»), `hierarchy` (7 групп,
12945 знаков), `skip_reasons`, `conflicts_detail`; на промахе бейдж говорил
«только предпросмотр». Прежний тест смотрел только пустые
`exact.messages/system` и утечку не ловил.

**Исправление.** В `web/api/speech.py` добавлен отдельный
`_inspector_correlation_payload` (2080) и ранний возврат из
`_inspector_payload` при заданном `correlation_id` (2148). В этом режиме
`_preview_manifest`/`core`/`sent`/`layers`/`style`/`hierarchy`/`skip_reasons`/
`conflicts_detail` **не строятся и не отдаются**: только `exact` из кольца
(или `not_recorded`/`provider_ring_miss`), `last_run_present`,
`last_run_note`, `requested_correlation_id/_recorded`, `ring_limit`,
`ring_hits`, `last_call`, `masked`, `retention`. Обычный Inspector (без
`correlation_id`) восстановлен к прежнему поведению и по-прежнему отдаёт
preview/hierarchy.

**UI.** В correlation-режиме карточки текущей сборки скрыты
(`v-if="!speechInspector.requested_correlation_id"`): причины пропуска
(13517), иерархия (13539), конфликты (13587), «фактически отправленный
payload» (13716), «Характер в сборке» (13743), режим-переключатель (13350).
Бейдж и пояснение на промахе говорят «полный текст не найден (not_recorded)»,
а не «только предпросмотр» (13436+). Переключение на «предпросмотр» для
запрошенного correlation_id запрещено (app.js `setSpeechInspectorMode` 19686).

**RED→GREEN.** Тесты усилены до проверки фактического ответа:
`CORRELATION_FORBIDDEN_KEYS` (preview/sent/core/layers/style/hierarchy/
skip_reasons/conflicts_detail/sent_note/trace_coverage), отсутствие маркера
текущей сборки (берётся из реального `_preview_manifest`), отсутствие
«предпросмотр» в подписи промаха. На коде `0398675a` эти тесты **падали**:
`AssertionError: в ответе correlation_id осталась текущая сборка: preview`
(3 теста), после исправления — **23 passed** в
`tests/test_speech_inspector_exact.py`. Новые/усиленные тесты:
`test_inspector_correlation_filter_returns_the_exact_meme_call`,
`test_inspector_correlation_miss_is_not_a_preview`,
`test_inspector_correlation_foreign_chat_returns_no_text`,
`test_ring_is_process_wide_not_per_chat`.

### Blocker 2 — «24 записи на чат» было ложью

**Наблюдение Reviewer.** `PROVIDER_CALL_MAX = 24` — ОДИН общий `OrderedDict`
на процесс; 25 вызовов другого чата вытеснили запись этого чата. Новые фразы
обещали «24 записи на чат».

**Исправление.** Все пользовательские/API-строки переведены на «24 записи
**процесса**, общие для всех чатов (фильтр по чату — при чтении)»:
`INSPECTOR_RETENTION` (speech.py 1993), `last_run_note` correlation-режима
(2080+), `FULL_TEXT_STORAGE` (initiative_publications.py 164+),
`iniFullTextNote` (app.js 3551). Лимит 24 не менялся; отдельного кольца на чат
и нового хранилища нет.

**Тест.** `test_ring_is_process_wide_not_per_chat` пишет одну запись своего
чата, затем 25 записей чужого — своя запись исчезает, Inspector честно даёт
`not_recorded`, текст не подставляется; строки политики проверяются на
«процесс» и отсутствие «на чат» (`_assert_no_current_build`). Публикационная
привязка `full_text.storage` проверяется тем же требованием.

**Честный предел.** Кольцо общее: 24 записи процесса, чужие вызовы вытесняют
запись этого чата раньше, чем «свои 24». Это состояние существующего
композера, не новый store; UI/API теперь говорят это прямо.

### Post-approval test-contract fix (DevOps stop 2.58.196)

**Наблюдение DevOps.** После одобрения `3b1c4ba9` один тест серии падал:
`tests/test_initiative_coordination.py::test_command_marks_priority_before_generation`
— `TypeError: _clear() got an unexpected keyword argument 'job_id'`. Продукт
передаёт `job_id` в `release_manual_priority`
(`handlers/meme_command.py:200` определение, `:396` вызов), чтобы дописать
снятие в терминальную строку; тестовый двойник сохранял старую подпись.
Продуктовый код не менялся.

**Исправление (только тест).** `_clear(chat_id, mark, **_kw)` принимает новый
keyword; `_pipeline`-стаб выставляет `trace.job_id = "meme-job-coord-1"`
(реальный пайплайн минтит job_id до первого гейта). Проверяется `clear` с
непустым `job_id` и ровно одно снятие; прежняя последовательность
`delete → priority → pipeline → clear` и `until` сохранена. Других двойников
`release_manual_priority` в репозитории нет.

**Результаты.** Target — **1 passed**; файл — **56 passed / 4 failed**
(те же 4 предсуществующих); 22-файловая серия meme/initiative/publication/
diagnostic — **519 passed / 4 failed** (база 2.58.195 — 510/4; +9 новых
тестов, новых падений 0); 7-файловый closure set — **204 passed**; JS
`INITIATIVE-UI-OK` / `P0IM-OV-HONESTY-OK` / `test_webapp_js_unit.py`
**45 passed**; e2e — те же 2 предсуществующих / 0.

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

**Честные пределы.** Кольцо — 24 записи НА ПРОЦЕСС (общие для чатов); после
рестарта/вытеснения (в т.ч. вызовом другого чата) текст недоступен — так и
показывается. Реальный HTTP-вызов LLM в тестах не выполняется; идентичность
проверена на шве клиента, который использует боевой `_record_provider_call`.

---

## 2. `P0IM-PB-ACCESS` (add[46])

**Что сделано.** Защищённое раскрытие полного текста — существующий
`GET /api/speech/inspector` + существующий `_can_edit_inspector` + существующая
маскировка `_mask_text`. Добавлен аддитивный отбор `correlation_id`.

| Факт | Где | Строка |
|---|---|---|
| аддитивный параметр запроса, RBAC не изменён | `web/api/speech.py` | `get_inspector` 4290 |
| correlation-ответ — ОТДЕЛЬНАЯ сборка: только exact/not_recorded, без текущей сборки | `web/api/speech.py` | `_inspector_correlation_payload` 2080, ранний возврат 2148 |
| промах кольца — `status=not_recorded`, пустые messages/system | `web/api/speech.py` | `_inspector_missing_exact` 2060 |
| явные поля ответа: `requested_correlation_id`, `requested_correlation_recorded`, `ring_limit`, `retention` | `web/api/speech.py` | 2120–2130 |
| политика хранения — 24 записи ПРОЦЕССА, общие для чатов | `web/api/speech.py` | `INSPECTOR_RETENTION` 1993 |
| ссылка на существующий Inspector и политика хранения в трассе | `web/api/initiative_publications.py` | `_full_text_evidence` 174, ответ 1106; `FULL_TEXT_STORAGE` 165 |
| действие в трассе «Полный текст в Inspector →» | `web/app.js` | `iniOpenInspector` 16380 |
| запрос Inspector с correlation id; обычный вход сбрасывает отбор | `web/app.js` | 31577+, `openSpeechSection` 31397 |
| запрошенный correlation_id не даёт переключиться на «предпросмотр» | `web/app.js` | `setSpeechInspectorMode` 19686; `web/index.html` 13350/13410 |
| в correlation-режиме карточки текущей сборки не рендерятся | `web/index.html` | 13517, 13539, 13587, 13716, 13743 |
| промах корреляции показан как «не записано», не «предпросмотр» | `web/index.html` | 13383–13405; `web/app.js` `speechExactLabel` 33263 |

**Тесты.**
- `tests/test_speech_inspector_exact.py::test_inspector_correlation_filter_returns_the_exact_meme_call`
  — админ видит СВОЙ вызов; другой чат/другая корреляция не подставляются;
  секрет `sk-live-…` замаскирован; в ответе НЕТ `preview/sent/core/layers/
  style/hierarchy/skip_reasons/conflicts_detail/sent_note/trace_coverage` и
  маркера текущей сборки.
- `::test_inspector_correlation_miss_is_not_a_preview` — промах: `not_recorded`,
  `messages=[]`, `system=""`, подпись не «предпросмотр», текущей сборки нет.
- `::test_inspector_correlation_foreign_chat_returns_no_text` — чужая
  корреляция/чужой чат: `not_recorded`, текста и текущей сборки нет.
- `::test_ring_is_process_wide_not_per_chat` — 25 вызовов чужого чата вытесняют
  запись этого; Inspector честно `not_recorded`; политика — «процесс».
- `::test_inspector_correlation_path_keeps_rbac` — 403 не-админу (тот же гейт).
- `::test_inspector_endpoint_passes_the_correlation_query` — параметр доходит до
  payload; без него поведение прежнее.
- `tests/test_initiative_publications_api.py::test_detail_full_text_is_existing_inspector_or_honest_not_recorded`
  — `full_text.storage` говорит «процесс/общие», без «на чат».
- `tests/test_initiative_publications_api.py::test_detail_does_not_mix_chats` —
  detail из чужого `X-Chat-Id` не даёт ни строк, ни текста.
- JS `closureTrainSuite` — нота хранения/`not_recorded`, действие и URL
  Inspector'а, сброс отбора при обычном входе, запрет текущей сборки в
  correlation-режиме (анкеры/guard'ы шаблона).

**RED→GREEN.** На коде `0398675a` усиленные тесты падали с
`AssertionError: в ответе correlation_id осталась текущая сборка: preview`
(3 теста). После исправления весь файл — **23 passed**.

**Честные пределы.** Кольцо — 24 записи ПРОЦЕССА, общие для чатов; чужие
вызовы вытесняют запись этого чата (это доказано тестом, не только словами).
«Исторически не сохранялось» показывается как `full_text_not_recorded`.
Реальный браузерный переход в Inspector проверен JS-навигацией; полный
e2e-сценарий «трасса → Inspector» не добавлялся (существующий Inspector
покрыт своими e2e: `tests/ui_inspector_exact_e2e.py` — 142 проверки, 0
падений после фикса; обычный режим не изменён).

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

## 7. Прогоны (кандидат `21a3aef7`, база `c134f93d`)

`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, изолированные temp-SQLite;
production не затрагивался.

| Команда | Результат |
|---|---|
| pytest `tests/test_initiative_coordination.py::test_command_marks_priority_before_generation` | **1 passed** (target; после test-contract fix) |
| pytest `tests/test_initiative_coordination.py` (файл) | **56 passed / 4 failed** — те же 4 предсуществующих |
| 22-файловая серия meme/initiative/publication/diagnostic | **519 passed / 4 failed** (база 2.58.195 — 510/4; +9 новых тестов, новых падений 0) |
| pytest `tests/test_evol014_meme_initiative.py` | **61 passed** (было 58; +3) |
| pytest `tests/test_initiative_publications_api.py` | **40 passed** (было 35; +5) |
| pytest `tests/test_meme_init_diagnostics.py` | **44 passed** |
| pytest `tests/test_p0im_s6_fresh.py` | **12 passed** (было 10; +2) |
| pytest `tests/test_p0im_s5_meme_marker_interrupt.py` | **16 passed** (было 15; +1) |
| pytest `tests/test_publication_binding_delivery.py` | **8 passed** |
| pytest `tests/test_speech_inspector_exact.py` | **23 passed** (было 17; +6, включая RED→GREEN correlation) |
| Совместный прогон семи файлов выше | **204 passed**, 1 warning (deprecation) |
| `node tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` (`closureTrainSuite`, correlation guards) |
| `node tests/js/p0im_ov_honesty_test.js` | `P0IM-OV-HONESTY-OK` |
| pytest `tests/test_webapp_js_unit.py` | **45 passed** |
| pytest `tests/test_soul1_w6_speech_ui.py` (затронутый Inspector-контур) | **23 passed** |
| `python tests/ui_inspector_exact_e2e.py` (обычный Inspector) | **checks=142, failures=0** |
| `python tests/ui_initiative_rework_e2e.py` | **failures=2** — ровно те же 2 предсуществующих («Исходный из кода · журнал недоступен», 1536/390), что на 2.58.195 |
| `python tests/ui_meme_ui_fields_e2e.py` | **failures=0** |
| 5 привязанных тестов AC-MATRIX-FAIL | **5 passed** |

RED (до фикса, код `0398675a`): три correlation-теста падали
`AssertionError: в ответе correlation_id осталась текущая сборка: preview`.
GREEN (после `3b1c4ba9`): `tests/test_speech_inspector_exact.py` — 23 passed;
семь файлов — 204 passed.

Уже закрытые этим поездом строки не регрессировали: PB-VOCAB/PB-COUNT/PB-STEP/
BAN-CONFLATE/ID-FINISH/ID-CONC проходят в тех же файлах (44 diagnostics,
40 publications, 61 evol014), счётчики и `generated` не менялись.

E2e запускает собственный сервер и снимает его сам; браузеры/процессы после
прогонов закрыты. `ui_inspector_exact_e2e.py` пишет скриншоты в чужой
evidence-каталог (`asap-speech-arch`) — после прогона эти tracked-файлы
возвращены `git checkout`, в кандидат не входят.

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

- `IN_SCOPE` (тестовый контракт, DevOps stop 2.58.196, исправлено): двойник
  `release_manual_priority` в `test_initiative_coordination.py` сохранял старую
  подпись без keyword-only `job_id`. Обновлён только тест; продуктовая
  подпись/семантика снятия не менялись. Других таких двойников нет.
- `IN_SCOPE` (Reviewer blocker 1, исправлено): correlation-режим Inspector
  отдавал текущую сборку (`preview`/`hierarchy`/`skip_reasons`/`conflicts`)
  и на промахе подписывался «только предпросмотр». Теперь correlation-ответ
  собирается отдельно и содержит только запись кольца/`not_recorded`;
  UI-карточки текущей сборки в этом режиме не рендерятся. RED→GREEN
  зафиксирован в §0/§7.
- `IN_SCOPE` (Reviewer blocker 2, исправлено): «24 записи на чат» было ложью —
  кольцо одно на процесс, чужие вызовы вытесняют запись. Все строки переведены
  на «24 записи процесса, общие для чатов»; лимит 24 и само кольцо не менялись.
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
 handlers/meme_command.py                     |  28 +-
 services/initiative_diagnostics.py           |  72 +-
 services/meme_initiative.py                  | 143 +-
 tests/js/initiative_ui_rework_test.js        | 365 ++++
 tests/test_evol014_meme_initiative.py        | 188 ++
 tests/test_initiative_coordination.py        |  14 +-
 tests/test_initiative_publications_api.py    | 181 ++
 tests/test_meme_init_diagnostics.py          |   5 +
 tests/test_p0im_s5_meme_marker_interrupt.py  |  36 +
 tests/test_p0im_s6_fresh.py                  | 113 ++
 tests/test_speech_inspector_exact.py         | 193 ++
 web/api/initiative_publications.py           |  77 +
 web/api/speech.py                            | 141 +-
 web/app.js                                   | 266 +-
 web/index.html                               | 127 +-
 15 files changed, 1891 insertions(+), 58 deletions(-)
```

(плюс этот evidence-документ и `review-931945b7.md` в docs-коммите).

Housekeeping: временный probe-каталог
`WorkspaceData/runs/.../probe-0c6f7f4fde` закрыт после предыдущей сдачи
(`run-close --confirmed-idle --confirmed-evidence --apply`); worktree остаётся
для Reviewer/DevOps, пока кандидат не интегрирован. После
`ui_inspector_exact_e2e.py` чужие tracked-скриншоты возвращены `git checkout`,
в кандидат не входят.
