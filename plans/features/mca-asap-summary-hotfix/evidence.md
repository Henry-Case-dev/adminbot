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
