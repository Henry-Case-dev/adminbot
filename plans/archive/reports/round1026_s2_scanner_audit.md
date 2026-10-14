# Scanner — Эпик 2 / S2 `summary-context-restore-round1026` (Шаг 6, T-3246)

- **Дата:** 23.09.2026, Step 6 @Scanner
- **Diff base:** HEAD `7895e77` (тег `pre-round1026-s2` == `7895e77`), правки **не закоммичены** — аудит дерева.
- **Режим:** focused diff-based аудит (правки дерева + критичные зависимости).
- **Вердикт:** **К ДЕПЛОЮ — ДА** (блокеров нет). Critical 0 / High 0 / Medium 0 (блокирующих) / Low 2 (owned follow-up) / Info 2.

## 1. Область изменений (git status относительно HEAD)

Новые/изменённые в дереве:
- **new** `services/summary_context_restore.py` (391 стр.) — pure-core `restore_context` → `RestoreResult`, `RestoreParams`, `build_l1_payload`, `RESTORE_CHAIN_DEPTH=10`.
- **new** `tests/test_summary_context_restore.py` (34 теста), `tests/test_summary_context_restore_integration.py` (10 тестов).
- **new** `plans/features/summary-context-restore-round1026/{spec.md,adr-1026-4-...,tasks.md,evidence.md}`.
- **M** `services/summary_generator.py` (+207/−…) — врезка S2 в `_apply_filter`, `_restore`, `_collect_extra_parents`, `_is_open_anchor`, `_chain_tg_id`.
- **M** `config/settings.py` (`APP_VERSION` 2.58.20 → **2.58.21**), `README.md` (v2.58.21), `plans/docs/param-registry-round1025.meta.md` (APP_VERSION).
- **M** тесты — только bump 2.58.21 + изоляция S1 от S2 (`_S2_FLAG=False`) в `test_summary_filter_integration.py`; asserts не ослаблены.

## 2. D4-гейт и инварианты (с доказательствами)

| Проверка | Результат | Доказательство |
|---|---|---|
| `summary_xml.py`/`summary_prompts.py` вне diff | ✅ | `git diff --name-only HEAD -- services/summary_xml.py services/summary_prompts.py` → пусто |
| Публикация вне diff | ✅ | `image_generation.py`/`telegram_send.py` вне diff; `build_cover_media`/`send_rich_message` не тронуты |
| 2-вызовность LLM (нет третьего) | ✅ | `_restore`/`_collect_extra_parents` без LLM; тест `test_exactly_two_llm_calls_with_restore` |
| Нет новых внешних зависимостей/CDN | ✅ | импорты нового модуля: stdlib (`dataclasses`,`logging`,`time`) + `services.database`,`services.token_counter`; JS/CSP не тронуты |
| R17 (логи: числа/коды/id) | ✅ | `RESTORE_START/COMPLETE/ERROR` содержат run_id/chat_id/счётчики/`budget_kind`/`fits`; тест `test_logs_have_run_id_without_content` |
| R18 (тег/бэкапы/stash) | ✅ | тег `pre-round1026-s2`; `var/backups/s2-round1026-20260923-164410/`; `stash@{0}` присутствует |
| Δ DDL=0 | ✅ | `services/database.py`, `db/**` вне diff; `test_zero_ddl` |
| Δ каталога=0 | ✅ | `param_catalog.py` вне diff; проверено рантаймом: REGISTRY **467** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21**; Settings fields **426** |
| `APP_VERSION` синхронен | ✅ | settings=2.58.21, README v2.58.21, meta.md 2.58.21 |
| Маркер-тесты не ослаблены | ✅ | diff тестов — только version re-pin + `_S2_FLAG`; asserts сохранены |
| Гигиена индекса | ✅ | `git ls-files --cached` не содержит `.env`/`current_task.md`/`.zip`/`tools/_ui_*`/`var/backups`; `git diff --check` = exit 0 |

## 3. Логика/детерминизм (собственные прогоны)

- **Чистота:** нет I/O/сети/БД; единственное обращение к времени — `time.perf_counter()` для метрики `duration_ms` (см. L-R1026S2-1).
- **Двойной прогон идентичен** (собственный скрипт): `DET_KEPT True`, `DET_REST True` — `kept`/`restored` совпадают байт-в-байт; входные списки не мутируются.
- **`kept` не удаляется** при cap/бюджете: `assert set(kept) ⊆ set(result.kept)` — выполняется; tiny-budget → `status=truncated`, `restored_count=0`, `fits=False`, `kept` цел.
- **cap/бюджет/`truncated`:** cap=2 из 5 → `truncated`, `skipped=3`; бюджет усекает только добавления (приоритет родители → соседи: `additions.pop()` с конца).
- **fail-open:** `window=None` → `no_candidates`, `kept` сохранён; исключения → `status='error'` + `kept=list(kept)`.
- **OFF → S2 не вызывается:** `reply_context_enabled=False` → `_restore` не вызван, `restore_metrics=None`, `_filter_metrics` без S2-ключей; тест `test_off_gate_no_db_touch`.
- **`thread_chain.py` не изменён** — reuse `collect_thread_chain(db, chat_id, tg, depth)`; вторая реализация обхода не создана; `collect_thread_chain` принимает int (`_message_id_of`), `ChainItem.is_bot/item_id` используются корректно.
- **Спец-случаи §91/D5:** бот-строки (`is_bot=True` и `user_id==bot_id`) не восстанавливаются как события, но цепочка сквозь них продолжается; медиа/подписи сохранены; `mentions` не выдумывается (`build_l1_payload`).

## 4. Совместимость

- XML-вход = `RestoreResult.kept` (ON) либо `FilterResult.kept` (OFF/fail-open); `xml.build` вызывается на `xml_rows`.
- RAG/память/graph/memorize остаются на исходных `rows` (`summary_generator.py:374-404`).
- §57–§72/F0–F11/S1/IA/сердцебиение — вне diff (services публикации, web/**, промпты не тронуты).
- S1-поведение при OFF байт-в-байт (тесты изоляции + код-путь).

## 5. Находки

| ID | Severity | Статус | Локация | Суть | Влияние | Рекомендация |
|---|---|---|---|---|---|---|
| **L-R1026S2-1** | Low | OPEN (non-blocking) | `services/summary_context_restore.py:4-6,255,350,360` | Docstring заявляет «без системных часов», но `duration_ms` считается через `time.perf_counter()` | Нулевое: `kept`/`restored` детерминированы; недетерминирован лишь метрический `duration_ms` | Уточнить формулировку docstring («кроме monotonic-таймера метрики») либо вынести таймер в адаптер |
| **L-R1026S2-2** | Low | OPEN (non-blocking, perf watch) | `services/summary_generator.py:_collect_extra_parents` | До 50 последовательных `collect_thread_chain` (глубина 10) + повторное чтение каждой строки цепочки из БД | Ограниченный рост латентности на «звонких» чатах с множеством открытых якорей; фоновая генерация, не интерактив | Наблюдать в проде; при необходимости — batch-чтение/кэш строк цепочки |
| **I-R1026S2-1** | Info | — | `summary_context_restore.py:295-300` | Приоритет бюджета `token_limit > char_limit`; при заданном `token_limit` `char_limit` игнорируется | Не регрессия: идентично S1 `estimate_and_split` (`summary_filter.py:240-245`) | — |
| **I-R1026S2-2** | Info | — | `summary_generator.py:590-599` | `_filter_metrics["status"]` остаётся S1-статусом; статус восстановления — в `restore_status` | By design (ADR-1026-4 D3/D6) | — |

Блокирующих Medium/High/Critical нет. Находки L-R1026S2-1/-2 — owned follow-up, деплой не блокируют.

## 6. Тесты @Scanner (собственный прогон)

- `.venv\Scripts\python.exe -m pytest tests/test_summary_filter.py tests/test_summary_filter_integration.py tests/test_summary_context_restore.py tests/test_summary_context_restore_integration.py tests/test_webapp_round1026_polygon.py -q` → **105 passed, 0 failed**.
- Отдельно новые: `test_summary_context_restore.py` + `..._integration.py` → **44 passed**.
- Инварианты рантайм: `APP_VERSION 2.58.21`; REGISTRY 467 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21; Settings fields 426.

## 7. Handoff

**RESULT: SCANNED @Orchestrator** — блокеров нет, к деплою ДА. Отчёт: `plans/reports/round1026_s2_scanner_audit.md`. Инварианты Δ DDL=0 / Δ каталога=0 / 2 LLM / D4-гейт / R17/R18 — подтверждены. L-R1026S2-1/-2 остаются видимыми follow-up (не блокируют).
