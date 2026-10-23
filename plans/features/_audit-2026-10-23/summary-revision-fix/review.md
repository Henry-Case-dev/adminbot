# Review — b1525b60: L2-ревизия всех абзацев с находками + durable-диагностика

Лейн `REV-SUMMARY-REVISION`, режим read-only (единственная запись — этот файл).
Кандидат: `b1525b60` (HEAD, дерево совпадает с коммитом по 5 файлам — blob-сверка ниже).
База ревью: `468d1041`. Прод-база для сверки регрессий: `2.58.111` = дерево `ec359bb3` / `fbf9013d`.
Окружение: Windows, `.venv` Python 3.12, `pytest -p no:randomly`.
Карты требований/`requirements_gate` у этого audit-лейна нет; проверка — по брифу, RCA, отчёту и коду.

## Вердикт

**Needs Fixes** — блокер только на уровне поезда 2.58.112: 4 красных теста
`tests/test_summary_generator.py` не являются «pre-existing долгом», они созданы
коммитом `138330c0` этого же поезда. Фикс — 1 строка в тест-фикстуре (без изменения
прода). Диф `b1525b60` замечаний не имеет и переписывания не требует.

## Acceptance ledger

| # | Пункт | Статус | Краткое доказательство |
|---|---|---|---|
| 1 | F1: группировка по `paragraph_id`, 1 вызов на все абзацы, замена только заявленных, §99/anchor-валидатор, полный re-review; 1 абзац — бит-в-бит | VERIFIED | `summary_l2_review.py:1365-1412`, `:1413-1454`, `:574-633`; `summary_l2_anchor_repair.py:255-270`, `:310-352`; тесты 11/11 |
| 2 | Критерии не ослаблены: «не исправила» → rejected; `unusable` терминален; stagnation/бюджеты не менялись | VERIFIED | `:421-435`, `:1308-1344`, константы `:136-138` не в диффе; анти-тест + `unusable`-тест зелёные |
| 3 | F2 durable: `review_verdict/blocking/codes/revision_fixed` на всех путях, `revision_fixed` корректен на rejected | VERIFIED (оговорка) | `pipeline_events.py:326-340`; `summary_l2_review.py:906-924`, `:1259-1261`, `:1542-1545`, `:1560-1562`, `:1691-1699`; сквозной rejected-run проверен |
| 4 | Мусорный `quote_unverified_count` не подаётся только при закрытом учёте и без unresolved-блокеров | VERIFIED | `:1587-1609`, `:1612-1634`; accounting `summary_l2_writer.py:1079-1084` + `summary_quote_repair.py:311-370` |
| 5 | Скоуп: 5 файлов, нет DDL/env/зависимостей/секретов/чужих правок | VERIFIED | `git show --stat`, `git show --check` exit 0, скан секретов 0 |
| 6 | Независимые числа тестов и RED на родителе | VERIFIED | таблица ниже |
| 7 | 4 падения `TestPipeline` — классификация и минимальный фикс | **FAILED (уровень поезда)** | не B-1; созданы `138330c0`; 1 строка в фикстуре |
| 8 | Стоимость/латентность batch-ревизии | VERIFIED | замеры user-контента ниже; новых классов переполнения нет |
| — | UI/визуал, live-прод | N/A | кода UI нет; `repair_target="targeted_batch"` — новое значение существующего строкового поля трассы, вёрстка не менялась; деплой не выполнялся |

## 1. F1 — что именно проверено

- Группировка: `group_issues_by_paragraph` (`summary_l2_anchor_repair.py:255-270`)
  сохраняет порядок находок внутри абзаца и сортирует абзацы по id. Валидатор
  (`:196-250`) уже отбрасывает не-int/out-of-range `paragraph_id`, поэтому все
  сгруппированные id валидны и в границах документа.
- Один bounded-вызов: ветка `len(targeted_ids) > 1` (`summary_l2_review.py:1368-1412`)
  делает ровно один `_call_llm`; `calls`, `l2_revision_calls`, `revisions_done`
  инкрементируются один раз — как в одиночной ветке.
- Замена только заявленных абзацев: `allowed_paragraph_ids=targeted_ids`, в
  `apply_targeted_revision_batch` (`:574-633`) чужой id, дубль id, пустой текст и
  out-of-range дают `revision_invalid_patch`; документ при этом не публикуется
  (атомарно). Проверено тестом и моими пробами: `dup/empty_text/out_of_range` → rejected.
- §99/anchor-валидатор: тот же `validate_l2_document_anchors` на весь документ
  (`:631-632`), что и в одиночной targeted-ревизии. Полный re-review — цикл
  возвращается в начало, `build_review_content` получает новый `current_doc`
  (тест: 5 находок → 1 batch-ревизия → approved).
- Один абзац — прежний контракт: при одном уникальном `paragraph_id`
  `issues_by_paragraph[targeted_ids[0]][0]` — это ровно прежний `anchor_issues[0]`
  (группа одна, порядок сохранён); `_anchor_source_excerpts` (`:636-642`) делегирует
  в `_anchor_source_excerpts_many([issue], ...)` с идентичной логикой и порядком;
  `build_targeted_revision_content` и `apply_targeted_revision` не менялись; вывод excerpts сверен с телом из `468d1041` — идентичен и с `payload_items`, и без них.
  Фокусный набор 330 тестов (включая существующие targeted-тесты) зелёный.

Остаточное (не блокирующее): если модель вернёт замену не для всех заявленных
абзацев, применяется частичный batch и `revision_result=ok`. Проверено: 2 из 3 →
документ меняется, третий абзац остаётся; если повторный Reviewer одобрит —
публикуется с непочиненным абзацем (мой probe C). Это best-effort и строго лучше
прежнего поведения; отклонять частичный batch не нужно (сожжёт обе ревизии).
Формулировка отчёта «вторая ревизия закрывает остаток» верна только если Reviewer
снова заявит находку — стоит уточнить в отчёте/после деплоя.

## 2. Критерии не ослаблены

- «Ревизия не исправила» → rejected: анти-тест `test_batch_revision_that_does_not_fix_is_still_rejected`
  + мой probe A (5 → 2 blocking, stagnation → rejected).
- `unusable` (≥2 hard-кода в ≥2 абзацах) остаётся терминальным: `_unusable_gate_accepts`
  (`:421-435`) в диффе отсутствует; тест фиксирует `review_calls=1`, `revision_count=0`,
  ревизия не вызывается.
- Бюджеты/stagnation: `MAX_REVISIONS=2`, `MAX_REVIEWS=3`, `CALL_BUDGET_L2_STAGE=6`
  (`:136-138`) не менялись; stagnation-блок (`:1319-1344`) не менялся; batch = 1
  вызов на итерацию, поэтому бюджет не растёт.

## 3. F2 durable — проверено сквозным прогоном

- Запись полей: `_durable_review_metrics` (`:906-913`) и `_revision_fixed_count`
  (`:916-924`); вызовы на approved (`:1542-1545`), rejected/soft-only (`:1560-1562`),
  unusable-терминале (`:1259-1261`), degraded — `setdefault` (`:1691-1699`).
- Событие: `pipeline_events.l2_stage` (`:326-340`) кладёт `review_verdict`,
  `review_blocking`, `review_finding_codes` (≤8, каждый ≤48 симв.) и `revision_fixed`
  в `counts` → `usage_json`. `SUMMARY_L2_STAGE` эмитится безусловно в
  `_run_hybrid_l2` (`summary_generator.py:2653`), а прод-путь `writer_source`
  приходит туда через `_run_writer_source_stage` (`:2555`) — значит поля durable на
  реальном пути, а не только в тесте.
- `revision_fixed` на rejected корректен: probe A дал 5 → 2 blocking,
  `l2_revision_fixed_count=3`; при неизменных находках — 0 (тест); отрицательные
  значения зажаты `max(0, ...)`.
- Новых событий/таблиц/DDL нет; ключи аддитивные. Потребители читают конкретные
  ключи (`pipeline_analytics.py:1041-1048` берёт `revision_fixed` из
  `SUMMARY_L2_REVIEW`, не из `SUMMARY_L2_STAGE`) → двойного счёта нет;
  `_parse_usage` fail-open, `usage_json` и так капается 2000 симв.
- Оговорка (не блокирующая): на outage-путях (ошибка Reviewer/Revision)
  `review_verdict="degraded"`, `review_blocking=0`, `revision_fixed=0`, хотя
  `l2_review_findings_total` сохраняется (probe B: findings_total=5, blocking=0).
  Это честно на уровне стадии, но реальный pre-outage вердикт/blocking не
  персистится. Минимальное улучшение (по желанию): в `except` ревизии вызвать
  `_durable_review_metrics(metrics, verdict)` до `_degraded_or_legacy`. На приёмку
  F2 не влияет: цель — разбор rejected/unusable, там всё на месте.

## 4. Мусорный quote-hint

`_quote_unverified_is_live` (`:1587-1609`): сигнал остаётся, если есть
`quote_unresolved_blockers`, либо `quotes_total` отсутствует/не int/≤0 (legacy/OFF),
либо `verified+repaired+removed < total`. В `_deterministic_findings_from_metrics`
(`:1612-1634`) ключ вставляется только при live-условии; unresolved-блокеры
эмитятся всегда и раньше.

Учёт корректен и в безопасную сторону: каждая цитата либо verified
(`summary_quote_repair.py:331,339`), либо repaired/removed (`:365-370`), либо
fail-closed с `failure_reason` (`:362-364`, документ не публикуется). `removed`
считается и в `repaired`, и в `removed` — переучёт, а не недоучёт; дедуп
одинаковых цитат может только уменьшить `accounted` (сигнал сохранится). Живая
непроверенная цитата при закрытом учёте невозможна. Тесты покрывают закрытый
учёт, живой gap, blocker и legacy-метрики.

## 5. Скоуп, секреты, совместимость

`b1525b60` меняет 5 файлов: `summary_l2_review.py`, `summary_l2_anchor_repair.py`,
`pipeline_events.py`, новый тест, отчёт. DDL/env/зависимостей/промптов нет,
`git show --check` чистый, скан секретов — 0. Рабочее дерево по этим файлам
идентично коммиту (blob `cee67d13` = `b1525b60:services/summary_l2_review.py`).

## 6. Числа (независимый прогон)

| Прогон | Результат |
|---|---|
| Новый файл `tests/test_summary_l2_review_multi_paragraph.py` | **11 passed** |
| Фокусные 10 файлов | **330 passed**; с новым файлом — **341 passed** |
| Широкий набор 74 файла (summary/l2/review/failsoft), кандидат | **1647 passed, 4 failed** |
| Тот же набор на базе `468d1041` (73 файла, без нового) | **1636 passed, 4 failed** |
| RED нового файла на `468d1041` (файл скопирован в worktree) | **8 failed, 3 passed** |

Все числа совпали с отчётом; расхождение «фокус 330 vs 341» — это ровно +11
новых тестов.

## 7. T1 (BLOCKER, уровень поезда): 4 падения — не B-1 и не pre-existing долг

| Коммит | Что это | `tests/test_summary_generator.py` |
|---|---|---|
| `ec359bb3` (дерево 2.58.111) | прод-база | **65 passed** |
| `138330c0` | первый коммит после деплоя 2.58.111 (входит в поезд 2.58.112), добавил `except asyncio.CancelledError` в `_run` | **4 failed, 61 passed** |
| `10f3a2a0` (B-1) | только тело обработчика (`publish_status`) | **4 failed, 61 passed** |
| `468d1041` | база ревью | **4 failed, 61 passed** |
| `b1525b60` | кандидат | **4 failed, 61 passed** |

Механизм: `services/summary_generator.py:968` — `except asyncio.CancelledError`, но
фикстура `no_sleep` (`tests/test_summary_generator.py:18-27`) подменяет весь модуль
`services.summary_generator.asyncio` на `MagicMock` и восстанавливает только `Lock`
(`:25`). При всплытии `LLMError`/SQLite-ошибки интерпретатор вычисляет except-выражение
и получает `TypeError: catching classes that do not inherit from BaseException` —
4 error-path теста (`:177,:212,:220,:228`) не доходят до своих обработчиков.

Вывод: **это регрессия `138330c0` (тот же поезд 2.58.112), а не B-1 и не исторический
долг.** Метка «pre-existing» в `report.md:122-129` верна только относительно базы
`468d1041`; относительно прода 2.58.111 эти 4 теста были зелёными, и поезд вносит
их покраснение. Заявленный в сообщении `138330c0` прогон «428 passed / 0 failed»
этот файл не покрыл — иначе падения были бы видны уже там. Прод-инвариант при этом цел: обработчик `raise`-ит (`:989`), а B-1
покрыт отдельным тестом `test_summary_fact_view_v2_anchors.py:375`, который фикстуру
`no_sleep` не использует.

Минимальный фикс (1 строка, только тест): в `no_sleep` добавить
`fake.CancelledError = real_asyncio.CancelledError` рядом с `fake.Lock`. Проверено в
изолированном worktree: **65 passed**, прод-код не тронут, инвариант «опубликованный
ран не переписывается в failed» не ослаблен. Тот же паттерн есть в
`tests/test_asap8_v63_b06_summary_scope.py:43-49`,
`tests/test_hotfix3_summary_fallback_round1025.py:28`,
`tests/test_summary_wave8_ladder_matrix_asap41.py:74-80` — там сейчас не падает, но
это та же слепая зона; добавить строку можно заодно.

Recheck после фикса: `pytest tests/test_summary_generator.py` → 65 passed; широкий
набор 74 → **1651 passed, 0 failed**; отдельно 4 именованных теста. Код `b1525b60`
повторно ревьюить не нужно.

## 8. Стоимость/латентность batch-ревизии

Замер на реалистичном окне (30 сообщений, 12 абзацев, находки в 10, реальные
`review_payload_items`): draft 4368 симв., одиночная targeted-ревизия 1412 симв.,
batch 9195 симв., Reviewer-запрос с окном 14573 симв.

- Вход batch — это только заявленные абзацы + их excerpts; он меньше входа
  Reviewer'а на той же итерации (полный draft + source window), который уже
  работает в проде.
- Выход — не больше полного draft: Writer уже отдаёт весь документ одним вызовом;
  новый класс переполнения не появляется.
- Вызовов не больше: 1 ревизия = 1 вызов, ≤2 ревизий, ≤6 вызовов стадии.
  Латентность — один более крупный вызов вместо одного маленького; на фоне
  Writer/Reviewer это не меняет порядок. Для поезда риск приемлемый; рост токенов
  ревизии (~6× на её собственный вход) стоит мониторить по `SUMMARY_L2_STAGE`/cost.

## Что можно в поезд

- `b1525b60` — **да**, по существу; F1/F2/hint/скоуп/числа закрыты.
- Поезд 2.58.112 — **после** фикса T1 (1 строка фикстуры + правка формулировки
  `report.md:122-129`) и повторного широкого прогона (1651/0). Иначе поезд
  приносит 4 собственных красных теста и маскирует их меткой «pre-existing».
- F3 (roster/`run_package`/канон) сознательно вне скоупа — подтверждаю, в диффе
  его нет; после деплоя остаются проверки из `report.md` §4.2 (`review_verdict`,
  `review_blocking`, `review_finding_codes`, `revision_fixed` в
  `SUMMARY_L2_STAGE.usage_json` на обоих исходах; сравнение `findings_total` и
  микса approved/rejected/unusable).

## Ограничения ревью

- Нет карты требований и strict-evidence графа у audit-лейна; release-gate поезда
  это не заменяет.
- Прод/live и реальный провайдер не проверялись (деплоя не было); поведение
  частичного/невалидного batch на реальной модели не наблюдалось.
- Визуальные проверки не применимы: UI-код не менялся.
