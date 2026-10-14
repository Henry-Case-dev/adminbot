# S4 `summary-fact-package-round1026` — focused diff-based аудит @Scanner (T-3301)

- **Дата:** 23.09.2026. **Роль:** Step 6 @Scanner.
- **Baseline:** HEAD `59f5921` (annotated-тег `pre-round1026-s4` → `59f5921`), `APP_VERSION` 2.58.22.
- **Правки НЕ закоммичены** — аудит дерева относительно HEAD (24 M + 6 ??; ничего не staged).
- **Артефакты фичи:** `plans/features/summary-fact-package-round1026/{spec.md, adr-1026-6-*.md, tasks.md, evidence.md}`.
- **Отчёт Builder:** `evidence.md` (Step 4).

## Вердикт: **К деплою — ДА (по коду блокеров нет)**

Critical 0 / High 0 / requirement-blocking Medium 0. Все инварианты S4 подтверждены независимо
(0 LLM-вызовов, Δ DDL=0, Δ каталога=0, живой путь/публикация/обложка/`web/**` вне diff). Low — owned follow-up (S5).
**Процессный gate:** `T-3300 @Reviewer` не закрыт — `review.md` в папке фичи **отсутствует** (см. M-R1026S4-1).

## Таблица severity

| ID | Severity | Статус | Место | Суть |
|---|---|---|---|---|
| M-R1026S4-1 | Medium (процесс/gate, не код-дефект) | OPEN | `plans/features/summary-fact-package-round1026/` | Нет `review.md` (T-3300 @Reviewer не выполнен; T-3301 по `tasks.md` зависит от T-3300) |
| L-R1026S4-1 | Low (observability) | OPEN (owned, S5) | `services/summary_fact_package.py:251-253` | Обрезка фрагмента >`FRAGMENT_MAX_CHARS` не помечает пакет `truncated` и не даёт WARN |
| L-R1026S4-2 | Low (perf) | OPEN (owned, S5) | `services/summary_fact_package.py:382-412` | `_enforce_budget` пересчитывает полный JSON+токены на каждое вытеснение (O(n²)) |
| I-R1026S4-1 | Info | OPEN | `services/summary_fact_package.py:382-412` | `unassigned_message_ids` не усекаются бюджетом; `cut` не используется |
| I-R1026S4-2 | Info | OPEN | `services/summary_fact_package.py:639-645`, `_fail_result` | `invalid`/`error` без `invalid_reason` → `result.reason=None`, а `metrics.reason`/лог = `ok` |

## Находки с доказательствами

### 1. Critical/High — нет

- **0 LLM-вызовов:** `services/summary_fact_package.py` импортирует только stdlib (`dataclasses, json, logging, re, time`)
  + `config.settings`, `services.summary_l1_contract`, `services.token_counter`; `llm_client` в исходнике отсутствует
  (тест `test_module_has_no_llm_dependency`; повторный `rg` — 0 совпадений).
- **Живой путь вне diff:** `git diff --name-only HEAD` не содержит `services/summary_generator.py`,
  `services/summary_xml.py`, `services/telegram_send.py`, `services/image_generation.py`, `web/**` (проверено; тест
  `test_generator_has_no_fact_package_wiring`). `_generate_two_call` вызывает ровно 2 LLM (`await_count==2`,
  `steps=[stage1, stage2]`).
- **CSP/zero-build:** новых библиотек/CDN/inline/eval нет — `web/**` не менялся, единственный новый рантайм-файл — Python-модуль.

### 2. §96 — нет дублирования сырого лога; доказательства не генерируются

- `fragments` отбираются только из `message_ids`/`evidence_ids` темы (`_select_fragments`); текст `unassigned` и
  прочие §92-строки в пакет не попадают. Тест `test_does_not_duplicate_raw_log`: тексты 103–106 отсутствуют в сериализованном пакете.
- `description` — детерминированная агрегация `facts[].text` (дедуп casefold + схлопывание пробелов + `" · "` + кап 500
  по границе слова) — LLM/проза не привлекаются.
- `chronology` — ASC `(timestamp, message_id)` из §92 `IdSpace.order` (`sort_key`); темы — ASC по первой паре.
- Фрагменты ограничены: `FRAGMENT_MAX_CHARS=1000`, `MAX_FRAGMENTS_PER_THREAD=30`, `MAX_FRAGMENTS_TOTAL=500`.

### 3. Fail-closed — корректно

`ok→ok`; `truncated→truncated` + проброс `skipped_ids`/`chunk_count`; `empty/invalid/error → threads=[]`,
`deliverable=False` (в L2 не идёт); нет `L1Result`/нет `payload` при `ok|truncated`/неизвестный статус → `not_built`
(`package=None`). Любое исключение → `error`/`internal_error`. Усечение явное: `truncated` + `skipped_ids`/
`skipped_threads` + WARN `FACT_PACKAGE_TRUNCATED` (`test_truncation_logged_not_silent`). Ноль тем → `empty`
(`reason=budget_empty`) → L2 не вызывается.

### 4. ID-пространства — корректно

Пакет оперирует TG `message_id`; DB `id` (1/2) как message_id → `invalid`/`missing_source`; висячие/фабрикованные id,
`evidence` вне темы, дубль между темами, конфликт с `unassigned` → `invalid` (воспроизведено 8 тестами).
`evidence_ids ⊆ message_ids` проверяется повторно (defense-in-depth). В логах — только числа/коды/id.

### 5. Инварианты

- **Δ DDL=0:** `services/database.py`/`services/pg_db.py` вне diff.
- **Δ каталога=0:** импортом подтверждено `REGISTRY 468 / Settings 426 / categorized 443 / GROUPS 100 /
  _TAB_BY_GROUP 98 / TAB_RULES 21`; `services/param_catalog.py` вне diff; F8 не переиздавался.
- `APP_VERSION` 2.58.23 синхронен (`config/settings.py` + `README.md`; тесты-пины 2.58.22→2.58.23).
- **Маркер-тесты не ослаблены:** весь diff тестов — только version-пины (`grep` по добавленным/удалённым строкам:
  иных правок нет).
- **R17:** тест `test_logs_r17_safe` — секретный текст сообщения в логах отсутствует; логи только числа/коды/id.
- **R18:** тег `pre-round1026-s4` → `59f5921` (annotated, `rev-list -n1` = `59f5921…`); бэкап
  `var/backups/s4-round1026-20260923-202326/`; `.env.bak.round1026-s4`; `stash@{0}` на месте.
- **Гигиена индекса:** в `git ls-files`/untracked нет `.env`/`current_task.md`/zip/`tools/_ui_*`/`var/backups`
  (только `plans/features/…`, `services/summary_fact_package.py`, `tests/test_summary_fact_package.py`).
- `git diff --check` → exit 0.

## Прогоны @Scanner

| Проверка | Команда | Результат |
|---|---|---|
| Новый файл тестов | `.venv\Scripts\python.exe -m pytest tests/test_summary_fact_package.py -q` | **52 passed / 0 failed** |
| Каталог (импорт) | `python -c "services.param_catalog …"` | **468/426/443/100/98/21** = Δ0 |
| Тег отката | `git rev-list -n1 pre-round1026-s4` | `59f592147f2ae5b316a56361e03e4b7a1d9a7c7c` |
| Whitespace | `git diff --check` | exit 0 |
| Обрезка фрагмента (проба) | 1500-символьный текст → пакет | `status=ok`, `fragment_char_truncated_count=1`, `truncated_count=0` (L-R1026S4-1) |
| Бюджет (проба) | 17 тем × 30 фрагментов × 1000 симв., limit=199000 | вытеснено 341, **0.29 s** (L-R1026S4-2) |

## Изменённые файлы

**Новые:** `services/summary_fact_package.py` (694 строки, 0 LLM), `tests/test_summary_fact_package.py` (52 теста),
`plans/features/summary-fact-package-round1026/**`.
**Изменённые:** `config/settings.py` (bump 2.58.23), `README.md`, `plans/docs/param-registry-round1025.meta.md`
(версия), `plans/MEMORY.md`, `plans/backlog.md`, `plans/round1025-architecture.md`, `plans/workflow_state.md`,
13 Python + 4 JS теста (только version-пины), `tests/test_webapp_round1026_polygon.py`.

## Handoff

**RESULT: SCANNED @Orchestrator** — по коду блокеров нет (C0/H0); вердикт **к деплою ДА** после закрытия
процессного gate **T-3300 @Reviewer**. L-R1026S4-1/-2 — owned follow-up (S5); I-R1026S4-1/-2 — информационно.
Инварианты: 0 LLM, Δ DDL=0, Δ каталога=0, живой путь/публикация/обложка/`web/**` вне diff, `git diff --check`=0.
