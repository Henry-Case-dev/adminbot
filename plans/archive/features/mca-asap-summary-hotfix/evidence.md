# mca-asap-summary-hotfix — evidence.md

Feature ID: `mca-asap-summary-hotfix` (ASAP, round1027, приоритет владельца).
Прод-инцидент: 2026-09-27 03:17 UTC, chat_id=-1002661910336. Baseline: прод
APP_VERSION 2.58.31 (git `05bc870`), worktree = 2.58.31 + незакоммиченная
MCA-волна round1027 (~68 файлов, pre-existing — НЕ принадлежат этому hotfix).

## 1. Диагноз

### Что сломало публикацию (первопричина)
`services/summary_l2_writer.py` — в `run_l2` документ §99, валидный по всем
жёстким контрактам (структура/цитаты/ID/длина абзаца), **жёстко отбраковывался
`too_many_paragraphs`**, если число абзацев > мягкого капа
`limits.max_summary_parts`. Далее `summary_generator._run_hybrid_l2` логировал
`L2_ERROR | reason=too_many_paragraphs — не публикуем` и делал `return` —
публикация отменялась ЦЕЛИКОМ (без UX-сообщения, без fallback).

Корень рассогласования (латентный дефект S5/round1026, существовал с 2.58.24):
- `MAX_SUMMARY_PARTS: int = _env_int("MAX_SUMMARY_PARTS", 1)` — легаси-дефолт
  ещё с Epic 24 (v2.22.0), семантика «частей ×4000 символов» для budget-
  подстановки legacy-промпта (`summary_generator.py:548`).
- S5 (ADR-1026-7 D2/D4) переиспользовал этот же ключ `limits.max_summary_parts`
  как кап АБЗАЦЕВ статьи L2 (`resolve_l2_max_paragraphs`), при этом
  `MAX_PARAGRAPHS_DEFAULT = 6` в модуле никогда не применяется (settings-ключ
  существует = 1), а L2-промпт просит ~6 абзацев (`_DETAIL_PARAGRAPH_HINT`
  serious=6). Итог: любая статья >1 абзаца → отбраковка → «не публикуем».
- Вероятностное всплытие 27.09: LLM выдал статью длиннее капа → publication
  died. Почему раньше публиковалось: вероятностно короткие ответы LLM и/или
  hot-значение `limits.max_summary_parts` в прод-БД (см. «Действия для DevOps»).

### Роль mca-07-регресса — НЕ подтверждена
- `services/summary_l2_writer.py` НЕ входит в mca-дифф (`git diff pre-round1026-a1 --
  services/summary_l2_writer.py` до hotfix содержал только мои правки; mca-волна
  его не трогала). `services/summary_generator.py` и
  `services/summary_fact_package.py` тоже вне mca-диффа.
- Payload-бюджет mca-07 влияет на вход L1/L2 не сильнее прежнего: бюджет L2 —
  `limits.summary_max_context_tokens/_chars` (S4, не менялся mca-волной).
- LLM-таймауты nano-gpt (ReadTimeout, retry attempt=1/3) — независимая
  параллельная деградация провайдера; она уронила **граф-экстракт** (см. ниже),
  но НЕ публикацию: L2 успел получить ответ (L2_ERROR — это валидация
  контента, а не таймаут).

### Граф-ветка: уже безопасна (требование №2 — проверено)
- `GraphExtractionError` при LLMTimeoutError НЕ выходит из
  `_compress_purge_extract_only` (`except Exception` → лог
  «batch kept, pipeline continues» → `break`; батч сохранён, не помечен).
- Вызовы `_extract_and_save_graph` защищены: extract-only ветка (3735-3757) —
  except Exception; легаси-ветка compress_and_purge (3642-3660) —
  GraphExtractDropped → pass, прочие → except Exception → break (raw kept).
- `GraphExtractDropped` (после GRAPH_EXTRACT_MAX_BATCH_FAILURES=3) → батч ЯВНО
  отброшен (mark) — прежняя семантика F1/ADR-1024-6 сохранена.
- mca-дифф в этих регионах — только `db.serialized()`-обёртки транзакций
  (MCA-01, B-MCA01-1), защитная логика except не менялась.
- Вызов `compress_and_purge` из `summary_generator._run:428` не может сорвать
  публикацию графом — подтверждено тестами (см. §3).

## 2. Фиксы (точечные, Δ DDL=0, Δ каталога=0, промпты не менялись)

1. **`config/settings.py`** — новый env-only ClassVar kill-switch
   `SUMMARY_L2_TRIM_ENABLED` (default ON; `_env_bool`; вне dataclass-полей →
   Δ каталога=0; тест `test_settings_trim_env_only_no_catalog_delta`).
2. **`services/summary_l2_writer.py`**:
   - `run_l2`: при `len(paragraphs) > cap` (мягкий кап
     `limits.max_summary_parts`) и флаге ON → детерминированная обрезка
     «первые N абзацев» через `_trim_document_for_publication` вместо
     отбраковки; OFF → точный прежний fail-closed (`too_many_paragraphs`).
   - `_trim_document_for_publication`: сохраняет title + первые cap абзацев;
     после абзацев проверяет бюджет `RICH_MAX_CHARS` (снимает абзацы с конца);
     пусто → None (fail-closed). Жёсткий потолок §99 (MAX_PARAGRAMS_HARD=498,
     too_long 32000, PARAGRAPH_MAX 900) НЕ ослаблен — валидатор отклоняет до
     trim-логики.
   - Метрики (R17-safe, только числа): `trimmed_for_publication=True`,
     `paragraphs_before`, `paragraphs_dropped_count`, `paragraphs_count`.
   - Логи §109: `L2_COMPLETE ... trimmed=1|no` + WARN-строка
     `L2 trimmed_for_publication | paragraphs_before/kept/dropped`.
   - Новый код `REASON_TRIMMED_FOR_PUBLICATION` (маркер, не причина отбраковки).
3. **`tests/`** — см. §3. **Baund-тест** `test_tool_coordinator_round1026.py`:
   `summary_l2_writer.py` добавлен в санкционированный список diff с NOTE
   (прецедент NOTE-исключений A3/A5/A9/mca-17a сохранён).
4. **APP_VERSION 2.58.31 → 2.58.32** (`config/settings.py:2130`) + README
   «Версия» v2.58.32 + синхронизация версия-пинов в баунд-тестах и JS-харнессе
   (плановая релизная механика проекта) + `param-registry-round1025.meta.md`
   APP_VERSION.

## 3. Тесты

- Полный pytest: **9839 passed, 0 failed** (`.venv\Scripts\python.exe -m pytest
  tests/ -q --timeout=120`, ~211s). Baseline round1026 — 9828; delta = 11
  (новый файл 10 тестов + 1 обновлённый сценарий).
- JS vm-харнесс: **48/48 файлов, exit 0** (`node tests/js/*.js`).
- Точечный файл `tests/test_summary_asap_hotfix_round1027.py` (10 тестов):
  - (а) прод-сценарий L2: 6 абзацев при капе 1 → `status=ok`, документ = 1
    абзац, `trimmed_for_publication=True` — публикация СОСТОИТСЯ;
  - (б) kill-switch OFF → точный прежний fail-closed (`too_many_paragraphs`);
  - бюджет `RICH_MAX_CHARS` после trim-абзацев (юнит с подменой лимита);
  - LLMError → `status=error`, документа нет, ровно 1 вызов (fail-closed не
    размыт);
  - жёсткий потолок 498 → `too_many_paragraphs` даже при trim ON;
  - (в) интеграция delivery: обрезанный документ доходит до
    `_publish_plain_document` и публикуется (не «не публикуем»);
  - (г) граф: все чанки LLMTimeoutError → GraphExtractionError ПОЙМАН внутри
    `_compress_purge_extract_only`, батч НЕ помечен processed, метод вернулся
    штатно (pipeline continues); GraphExtractDropped → mark (отброс);
    успешный батч → mark (no-infinite-loop инвариант);
  - Δ каталога=0 (env-only ClassVar).
- Обновлён `tests/test_summary_l2_writer.py::test_too_many_paragraphs` →
  обрезка (5→3 при капе 3) + kill-switch OFF-сценарий.
- Срез S5/S6: `test_summary_publish_integration_round1026.py` (58) +
  execution_graph + deploy + cover_compat + hotfix3 = **162 passed**.

## 4. Изменённые файлы (принадлежат ЭТОМУ hotfix)

- `config/settings.py` — APP_VERSION 2.58.32 + ClassVar SUMMARY_L2_TRIM_ENABLED
- `services/summary_l2_writer.py` — trim-фикс + логи
- `README.md` — версия
- `plans/docs/param-registry-round1025.meta.md` — APP_VERSION маркер
- `tests/test_summary_asap_hotfix_round1027.py` — НОВЫЙ (10 тестов)
- `tests/test_summary_l2_writer.py` — 2 сценария too_many_paragraphs
- `tests/test_tool_coordinator_round1026.py` — baund NOTE + APP_VERSION pin
- версия-пины (APP_VERSION/README-сверки): test_decision_making_round1026,
  test_image_context_memory_round1026, test_round1025_f8_registry (+meta),
  test_scope_selector_round1025, test_summary_deploy_round1026,
  test_summary_fact_package, test_summary_logging_runid,
  test_summary_publish_integration_round1026, test_summary_test_run,
  test_telegram_reactions_round1026, test_unified_image_request_round1026,
  test_webapp_design_tokens_round1025, test_webapp_f11/f6/f7/f9_round1025,
  test_webapp_hotfix6/7/8/9/10_round1025, test_webapp_round1026_polygon,
  tests/js/round1025_hotfix7/8/9/10_*.js
- артефакты: `plans/features/mca-asap-summary-hotfix/{tasks,evidence}.md`

Pre-existing mca-волна (~68 файлов) НЕ тронута этим hotfix.

## 5. Проверки, которые НЕ удалось выполнить здесь
- Реальное hot-значение `limits.max_summary_parts` в прод-БД (bot_settings) и
  env `MAX_SUMMARY_PARTS` на сервере — доступ к прод-БД вне сессии. Действие
  DevOps — см. §6 п.1 (не блокирует деплой: фикс корректен при любом значении).

## 6. Deployment-заметки для @DevOps

1. (После деплоя, не блокирует) Проверить на проде фактический кап абзацев:
   `sqlite3`/PG `SELECT value FROM bot_settings WHERE key='limits.max_summary_parts';`
   и env `MAX_SUMMARY_PARTS` в systemd-юните. Если значение маленькое (1-3) —
   саммари теперь публикуется обрезанным до этого значения; рекомендуется
   выставить 6 (совпадает с L2-промпт-хинтом serious) — это hot-ключ/каталог,
   без рестарта. Сейчас (дефолт 1) саммари будет публиковаться ОДНИМ абзацем —
   корректно, но коротко.
2. Деплой штатный: `git pull --ff-only`, systemd `admin_bot` restart,
   TimeoutStopSec=30. Дополнительных миграций НЕТ (Δ DDL=0), новых файлов/зависимостей
   НЕТ (Δ каталога=0), env-правок НЕТ (флаг default ON).
3. Откат (если что-то пойдёт не так): env `SUMMARY_L2_TRIM_ENABLED=false` +
   рестарт → точный прежний fail-closed путь (до-хотфиксное поведение).
   Или cold-revert к pre-hotfix коммиту.
4. После деплоя верификация на проде: дождаться следующего саммари
   (-1002661910336) и проверить лог: отсутствие `L2_ERROR | reason=too_many_paragraphs — не публикуем`;
   при обрезке ожидается строка `L2 trimmed_for_publication | paragraphs_before=N |
   paragraphs_kept=K | paragraphs_dropped=M`. Граф-ошибки LLMTimeoutError могут
   продолжаться (провайдер nano-gpt) — они НЕ влияют на публикацию: критерий
   «batch kept, pipeline continues» в логе + саммари публикуется.
5. Р17-скан диффа — CLEAN; секреты не затронуты.

## 7. Остаточные риски
- `too_long` (>32000 симв. суммарно) остаётся fail-closed (жёсткий контракт
  §99, вне требований владельца; кейс крайне редкий). Если владельцу нужен
  и там fallback — отдельная задача.
- Nano-gpt деградация (LLMTimeoutError) никуда не делась: она влияет на
  граф-экстракт (батчи остаются необработанными до следующего крона) и на
  ретраи llm_client. Публикация саммари теперь от неё не зависит при
  too_many_paragraphs, но полный L2-таймаут → `_send_ux(_UX_LLM_FAILED)`
  (сообщение в чат есть, публикации нет) — прежняя семантика сохранена.
- Дефолт капа 1 (легаси) — см. §6 п.1: при дефолте саммари будет «коротким».
  Требование владельца «не пустой чат» выполнено; качество (длина) — вопрос
  hot-ключа, рекомендация выставить 6.

---

# ASAP-2: L1-ретрай (пост-деплой 2.58.32)

## 8. Прод-факты и диагноз

- Пост-деплой 2.58.32: L2-фикс работает (too_many_paragraphs исчез), но 2
  свежих прогона пали РАНЬШЕ — на L1:
  - `L1_COMPLETE status=invalid | invalid_reason=invalid_json` (07:30);
  - `L1_COMPLETE status=invalid | invalid_reason=message_in_multiple_threads`
    (08:23);
  - → `L2_SKIPPED | reason=l1_not_usable` → `SUMMARY_COMPLETE degraded,
    code=SUMMARY_GENERATION_FAILED`.
- Статистика 30 дней: 17 SUMMARY, 16 degraded, L2_COMPLETE всего 2.
- Причина: `run_l1` — single-shot (один LLM-вызов, невалидный ответ → сразу
  `invalid_result` без повторной попытки, `services/summary_l1_clusterizer.py`).
  Оба прод-кода — случайный сбой модели (битый JSON; дубль id между тредами),
  не переполнение контракта.

## 9. Механика ретрая (фикс)

`services/summary_l1_clusterizer.py::run_l1`:
- тело «call → parse → validate» обёрнуто в цикл попыток: максимум 2
  (`attempt in (1, 2)`), вторая — ТОЛЬКО если первая `STATUS_INVALID` с
  reason в `_RETRYABLE_REASONS` (frozenset: invalid_json, bad_type,
  unknown_field, invalid_fact, unknown_message_id,
  message_in_multiple_threads);
- НЕ ретраятся (точный прежний путь):
  - `LLMError`/`LLMTimeoutError` → `error_result` (транспорт, есть свой
    retry-канал llm_client);
  - жёсткие лимиты `too_many_threads`/`too_many_facts`/
    `too_many_facts_total` (переполнение контракта, ретрай = трата токенов);
  - прочие invalid-коды (bad_schema_version, invalid_topic, invalid_thread_id,
    evidence_not_in_thread, unassigned_conflict, internal_error,
    id_space_mismatch, empty_response) — не в списке по ТЗ;
- валидация обеих попыток идентична — тот же `parse_l1_response`/
  `validate_l1_response`; ретрай НЕ ослабляет hard-контракт §95: обе
  невалидны → прежний `invalid` с reason ВТОРОЙ попытки;
- логи R17-safe: WARN `L1 retry | run_id | chat_id | attempt=1/2 |
  reason=<первой попытки> — повторная попытка`; итоговый `L1_COMPLETE` —
  прежний формат + аддитивное поле `attempts=%d` (1 — single-shot, 2 — был
  ретрай); фактический статус = последней попытки;
- kill-switch: env-only ClassVar `SUMMARY_L1_RETRY_ENABLED` (config/settings.py,
  default ON; OFF → `max_attempts=1` — точный прежний single-shot байт-в-байт;
  Δ каталога=0, тест env-only).

## 10. Тесты ASAP-2

Новый `tests/test_summary_asap2_l1_retry_round1027.py` (12 тестов, QueueLLM
с очередью ответов):
1. invalid_json → ретрай → ok/usable, calls=2, «L1 retry reason=invalid_json»,
   `attempts=2` в L1_COMPLETE;
2. message_in_multiple_threads → ретрай → ok (прод-код 08:23 покрыт);
3. обе попытки невалидны → прежний invalid/invalid_json (не новый статус);
4. reason ВТОРОЙ попытки в финальном результате (invalid_json → dup_threads);
5. ровно один ретрай без лавины (3-й ответ не запрашивается);
6. too_many_facts → single-shot, calls=1 (не тратим токены);
7. kill-switch OFF + невалидный первый → ровно 1 вызов, прежний invalid
   (второй ответ из очереди не используется);
8. kill-switch OFF + валидный → 1 вызов, ok;
9. LLMError → error_result без ретрая, calls=1;
10. LLMTimeoutError → error_result без ретрая, calls=1;
11. валидный с первой → ok, calls=1, `attempts=1`, «L1 retry» в логе нет;
12. Δ каталога=0 (env-only ClassVar, default ON).

Обновлены под новую семантику (fail-closed не ослаблен):
- `tests/test_summary_test_run.py::test_invalid_l1_fail_closed_no_l2` —
  обе попытки невалидны → 2×L1, L2 НЕ вызывается, not_published;
- `tests/test_summary_deploy_round1026.py::test_scenario_07_invalid_json_l1_fail_closed`
  (§114 harness) — 2×L1, 0 публикаций, `code=SUMMARY_GENERATION_FAILED`.

Баунд-гейты (прецедент NOTE-исключений):
- `test_tool_coordinator_round1026.py::test_forbidden_paths_out_of_diff` —
  `summary_l1_clusterizer.py` добавлен в санкционированные summary-файлы;
- `test_summary_deploy_round1026.py::test_forbidden_paths_unchanged` —
  файл исключён из списка запрещённых (NOTE ASAP-2).

## 11. Полные прогоны ASAP-2

- Полный pytest: **9851 passed / 0 failed** (~222 s; baseline 9839 → +12).
- JS vm-харнесс: **48/48, exit 0**.
- `git diff --check`: CLEAN. R17-скан диффа: CLEAN.

## 12. Файлы ASAP-2

- `services/summary_l1_clusterizer.py` — retry-цикл, `_RETRYABLE_REASONS`,
  `attempts` в L1_COMPLETE, docstring;
- `config/settings.py` — ClassVar `SUMMARY_L1_RETRY_ENABLED` +
  APP_VERSION 2.58.33;
- `tests/test_summary_asap2_l1_retry_round1027.py` — НОВЫЙ (12 тестов);
- `tests/test_summary_test_run.py`, `tests/test_summary_deploy_round1026.py`
  (scenario_07 + baund-исключение), `tests/test_tool_coordinator_round1026.py`
  (baund NOTE);
- версия-пины 2.58.33: 23 py-файла + 4 JS-харнесса (механика 270c277);
- `README.md`, `plans/docs/param-registry-round1025.meta.md`;
- артефакты: tasks.md/evidence.md (эта секция).

## 13. Deployment-заметки ASAP-2 для @DevOps

1. Деплой штатный: `git pull --ff-only`, рестарт `admin_bot`; миграций нет
   (Δ DDL=0), env-правок нет (флаг default ON).
2. Верификация после деплоя: следующее саммари — в логе `L1_COMPLETE ...
   attempts=2 | status=ok` при ретрае (или `attempts=1` если с первой);
   ошибки `L2_SKIPPED | reason=l1_not_usable` по invalid_json/
   message_in_multiple_threads должны практически исчезнуть. Остаточные
   degraded возможны при LLMError (транспорт) — это прежняя семантика.
3. Откат: env `SUMMARY_L1_RETRY_ENABLED=false` + рестарт → точный прежний
   single-shot.
4. Стоимость: максимум +1 LLM-вызов L1 на прогон и ТОЛЬКО при невалидном
   ответе (прод-статистика: до 14/17 прогонов экономились бы от ретрая);
   too_many_* не ретраятся — без затрат на заведомо невалидных ответах.

## 14. Остаточные риски ASAP-2

- `empty_response` (пустой ответ модели) не входит в retry-набор по ТЗ —
  если прод покажет кластер таких сбоев, вопрос отдельным пунктом.
- Ретрай дублирует вход (тот же messages) — при устойчивом «дурном» состоянии
  модели (например, системно ломает формат) прогон по-прежнему fail-closed
  после 2 попыток; это осознанный предел по ТЗ («ровно одна повторная
  попытка»).
- Задержка публикации растёт на длительность второй попытки только при ретрае
  (таймауты не ретраятся → worst case ограничен обычным временем ответа).

