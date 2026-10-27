# ASAP5 W2 — VISION: актуальное состояние Vision (§12–§17)

Слайс: `ASAP5-VISION` (строки карты REQ-VISION-STATUS-ACTUAL / REQ-VISION-STATES /
REQ-VISION-PENDING-HONEST / REQ-VISION-INTERMSG / REQ-VISION-RACE /
REQ-VISION-PROMISES). Ветка `task/asap5-vision`, база `release/p0-2026-10-26`
@ `ad239f73`. Кандидат: `a3ac5c5efaa67011ea71b9fd16bfeca05cfe190e`.
Ограничения лейна: без нового провайдера/пайплайна/второго сервиса состояний;
существующий механизм `mca_vision.py` (D1–D23) сохранён; fail-open и семантика
превью W1 не тронуты.

## 1. Главный найденный дефект: no_text = вечный pending (§13/§14)

`no_text` — УСПЕШНЫЙ исход распознавания «текста на изображении нет»
(`status = "ready" if (blocks or description) else "no_text"`, D19:
`REUSABLE_ANALYSIS_STATUSES = {"ready", "no_text"}`), но:

* `get_ready_analysis` / `find_ready_analysis_by_content_hash` (SQL-хелперы
  БД) читают только `status='ready'` → no_text-гранула никогда не доходила до
  потребителей;
* рендер показывал вечное «содержание ещё не распознано» по готовому активу
  (§14: «Если задача готова, нельзя продолжать считать её выполняющейся»);
* `recognize_target` доливал весь бюджет ожидания (45 с) и отвечал
  `pending/job_linked` по готовому анализу.

Фикс (низший слой, сервисный контракт без правки общего `database.py`):
`resolve_ready_for_asset` возвращает ready И no_text
(`_find_reusable_no_text_analysis`: гранула → content_hash, read-only);
`process_asset_job` использует `find_reusable_analysis_by_content_hash`
(оба success-исхода) → тот же контент получает то же представление без нового
вызова (§15).

## 2. Честные терминальные состояния (§13) и pending только по факту (§14)

Новые read-only точки чтения фактического состояния гранулы (единственная
точка честного терминала, без нового сервиса состояний):

* `latest_asset_analysis` — последняя analysis-строка гранулы;
* `asset_active_job` / `asset_terminal_job` — живая/терминальная джоба по
  `coalesce_key` (существующий durable-словарь статусов);
* `asset_vision_outcome` — приоритет: analysis-строка → активная задача
  (retry запланирован → ожидание честно) → терминальная джоба (без
  analysis-строки: OFF/asset lost/recovery → исход по её reason);
* `terminal_tool_result` — маппинг в ToolResult-контракт D22
  (ready/pending/disabled/unavailable/unsupported/missing/failed), reason —
  существующий словарь (269), новых кодов нет.

`recognize_target`:
* сбой постановки (enqueue exception) → pending только при РЕАЛЬНО живой
  задаче (напр. auto-intake); иначе честный `failed/vision_failed,
  job_linked=false` (раньше — выдуманный pending с job_linked=true);
* wait-цикл после проверки ready проверяет durable-исход: терминал без живой
  задачи → честный ответ немедленно (раньше — drain бюджета + «вечный
  pending» по мёртвой задаче);
* ready-ответы (оба пути) несут различимый флаг `no_text` (§13, состояние 6).

Рендер `render_media_context_async`:
* `NO_TEXT_LINE` = «текста на изображении не обнаружено (распознавание
  выполнено)» — не путается с «анализа ещё нет»;
* `ANALYSIS_FAILURE_LINES` — по фактическому классу терминала
  (unavailable/failed/unreadable/unsupported/job_terminal) вместо вечного
  `PENDING_LINE`;
* выполняющаяся задача — прежний pending (регрессия сохранена).

## 3. Статус-витрина per-chat (§12, класс дефекта P0V)

`runtime_snapshot`: «последний анализ» на per-chat витрине — строка ЭТОГО
чата (LEFT JOIN по `mca_media_assets.chat_id`; строка без актива не
теряется), глобальный снапшот сохраняет прежнюю строку + честную атрибуцию
`asset_id`/`chat_id`. Ранее `last` был последней строкой любого чата.
(FIX2/NF-1 — per-chat effective/`X-Chat-Id` — уже верифицированы в P0V и не
менялись.)

## 4. Никаких выдуманных обещаний (§17)

`tool_schemas.TOOL_RECOGNIZE_IMAGE` (описание тула — самый низкий слой,
который читает LLM): убрана инструкция «say you are going to look»
(приглашение к обещанию действия, которого сервис не исполняет: после
pending-ответа ничего не отправляет результат автоматически — D18).
Новая формулировка: pending = честное «ещё обрабатывается» + приглашение
переспросить; запрещены обещания самостоятельной отправки и выдуманного
времени; `no_text=true` = «анализ выполнен, текста не найдено» ≠ «ещё не
анализировалось»; `unavailable/failed` = фактическая причина (провайдер/ошибка
обработки), а не «не умею смотреть картинки»; `disabled` = модуль выключен.
Провайдер `not_configured` — честная техническая причина
(`capability_visible_reason`: «Не настроены адрес или модель распознавания»;
матрица покрыта тестом `test_visible_reason_texts_cover_all_classes`).

## 5. Гонки (§16) — аудит и статус

Аудит пути intake → job → render:

| Гонка | Статус | Доказательство |
|---|---|---|
| Двойная джоба актива | уже защищена: coalesce_key unique partial-index + INSERT OR IGNORE (singleflight); окно album-grace requeue (finish→enqueue) перекрывается той же коалесцией | `test_asap5_w2_coalesce_singleflight_no_double_recognition` (двойной enqueue → 1 активная; повтор после завершения → кеш, 0 вызовов) |
| Потеря обновления результата | уже защищена: CAS `finish_media_analysis(expected_revision)`, stale-джоба → `vision_stale_discarded`; fencing token на `store.finish` | существующие тесты D9/D10 (без изменений, зелёные) |
| Терминал во время ожидания тул-пути | исправлено: event-wake + перечит durable-исхода → честный failed до истечения бюджета | `test_asap5_w2_failure_during_wait_is_reported` (RED: pending → GREEN: failed) |
| Повторное распознавание выполняющегося/готового актива | manual re-trigger по НОВОМУ вопросу осознанно ставит bounded-retry (честный pending при живой задаче); по тому же вопросу (dedup) — терминал/кеш немедленно | `test_asap5_w2_terminal_failure_observed_not_drained` (оба исхода) |
| Кеш capability / stale-конфиг | без изменений: TTL, config_revision invalidation (D6/D7) | существующие тесты зелёные |

Повторной генерации ответа на каждое изменение статуса не введено; обычный
ответ не превращён в ожидание фоновых задач; рендер/тул читают только
committed-строки (никаких новых LLM-опросов — D23 сохранён).

## 6. Между сообщениями (§15)

Состояние берётся из реестра на каждом ходе (`chat_context.collect_media_
analysis_blocks` → `render_media_context_async` → `resolve_ready_for_asset`):
готовое — используется, продолжающееся — честно именуется, ошибка — её
фактический смысл (§2). Тот же контент в другом сообщении/альбоме — то же
представление по content_hash без нового вызова, включая no_text
(`test_asap5_w2_no_text_hash_reuse_same_bytes`). Альбомы/документы/превью —
тот же путь W1 (не менялись).

## 7. Границы write scope (отклонение задокументировано)

`services/tool_schemas.py` не входит в write_scope слайса (slice-graph), но
именно в нём живёт LLM-инструкция, порождающая невыполнимые обещания (§17) —
правка минимальна (одна строка описания recognize_image), файл не принадлежит
ни одному другому параллельному слайсу (IMAGE-GEN берёт `tool_router.py`,
W3, после VISION). Остальное — строго в scope:
`services/mca_vision.py`, `tests/test_p0_vision_fix_core.py`.
`direct_l1.py`/`chat_context.py`/`canonical_context.py` правок не требуют
(проверено: обещаний/глобальных подмен в них нет; шов chat_context уже
читает фактический рендер).

## 8. Верификация

RED→GREEN (владелец REQ-VISION, `tests/test_p0_vision_fix_core.py`, секция
«ASAP5 §12–§17 (wave W2)»):

| Тест | Покрытие | RED на базе | GREEN на кандидате |
|---|---|---|---|
| `test_asap5_w2_no_text_is_not_pending` | no_text reusable + рендер + тул | FAILED (get_ready→None; рендер pending) | PASS |
| `test_asap5_w2_no_text_hash_reuse_same_bytes` | §15 тот же контент — то же представление | FAILED (второй вызов провайдера) | PASS |
| `test_asap5_w2_enqueue_failure_honest_no_fake_pending` | §14 постановка не удалась | FAILED (pending/job_linked без задачи) | PASS |
| `test_asap5_w2_terminal_failure_observed_not_drained` | §14/§16 терминал наблюдаем | FAILED (drain 6с → pending) | PASS |
| `test_asap5_w2_failure_during_wait_is_reported` | §16 гонка во время ожидания | FAILED (pending) | PASS |
| `test_asap5_w2_render_failure_lines_distinct_from_pending` | §13 различимые строки | FAILED (PENDING_LINE) | PASS |
| `test_asap5_w2_coalesce_singleflight_no_double_recognition` | §16 без двойной джобы/вызова | PASS на базе (регрессия-гард) | PASS |
| `test_asap5_w2_snapshot_last_is_per_chat` | §12 per-chat витрина | FAILED (чужой чат в last) | PASS |
| `test_asap5_w2_tool_schema_no_false_promises` | §17 без обещаний | FAILED (старая формулировка) | PASS |

Итого W2: 9/9 GREEN (RED-профиль: 8 failed / 1 pre-green guard).

Регрессия/фокус (кандидат `a3ac5c5e`, все PASS):

* `tests/test_p0_vision_fix_core.py` + `test_vision_adapt.py` +
  `test_slavik_media_types.py` + `test_vision_dl_fix.py` +
  `test_native_reply_media_context_round1024.py` + `test_mca19_block_a/b/d/
  e/f_round1043.py` + `test_mca19_rework_r1_round1044.py` +
  `test_addtr_postgen.py` + `test_media_download.py` → **338 passed**;
* фактчек/шов контекста: `test_mca19_block_g_round1043.py` +
  `test_factcheck_context_cfg06.py` + `test_factcheck_media_2026_10_25.py` +
  `test_factcheck_p0_fc.py` → **117 passed**;
* тул-контур: `test_tool_schemas.py` + `test_tool_loop.py` +
  `test_tool_router.py` + `test_tool_calling_round1015.py` +
  `test_smoke_round1016_tool_loop.py` + `test_addtr_tools_minifix.py` →
  **126 passed**.

Полный сьют: **15963 passed, 1 skipped, 39 failed, 8 errors** — профиль
падений идентичен чистой базе `ad239f73` (38/38 совпадений по id на тех же
файлах + 1 флейк `test_mca09_intents_block_e::test_handle_initiative_
cancelled_by_recheck`, зелёный и на базе, и на кандидате вне полной
нагрузки). 8 errors — средовые (`ModuleNotFoundError: playwright` в
subprocess-харнессе UI e2e; файлы UI не менялись; владелец UI — слайс
ASAP5-ADMIN/W3). Никакое падение не вызвано диффом кандидата.

Попутное наблюдение (unrelated, вне скоупа): тест cfg-06 W7 dispute-metrics
мутирует закоммиченный evidence-файл
(`plans/features/cfg/evidence/cfg-06/w7-dispute-metrics.json`,
`latency_ms_mock` 7→6) при прогоне — пре-существующий дефект харнесса,
дерево восстановлено, в коммит не включено.

## 9. Сводка по строкам карты

| req_id | § | Статус | Ключевое доказательство |
|---|---|---|---|
| REQ-VISION-STATUS-ACTUAL | §12 | VERIFIED | snapshot per-chat тест; durable-статусы во всех поверхностях |
| REQ-VISION-STATES | §13 | VERIFIED | no_text/failed/unavailable/unsupported различимы (рендер+тул); новые состояния не вводились |
| REQ-VISION-PENDING-HONEST | §14 | VERIFIED | pending только при живой задаче; no_text/терминал не выдаются за ожидание |
| REQ-VISION-INTERMSG | §15 | VERIFIED | реестр на каждом ходе; content_hash reuse; путь W1 сохранён |
| REQ-VISION-RACE | §16 | VERIFIED | терминал-during-wait, coalesce singleflight, CAS — таблица §5 |
| REQ-VISION-PROMISES | §17 | VERIFIED | схема тул-описания без обещаний; not_configured — честная причина |

Live-required: false (live_when: preprod) — сетевых/прод-проверок лейн не
требует и не выполнял (запрещено брифом: no push/SSH/production/Telegram/LLM).
