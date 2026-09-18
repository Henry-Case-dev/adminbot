# Карта решений Human Gate — раунд 10.22 (UPD3)

> **Артефакт @Architect (Step 2b), 18.09.2026.** Источник решений — `plans/current_task.md` **UPD3**
> (строки 245–271) + `plans/backlog.md` §«🔴 РЕШЕНИЯ UPD3» (строки 15–20).
> Владелец прошёл гейт. Все открытые вопросы Д-1…Д-11 предыдущей итерации Step 2 **закрыты** и
> перенесены в `spec.md`/`ADR-1022-*` (статусы **Accepted**). R17/R18: `plans/current_task.md`
> untracked, SSH-значения не цитируются и не коммитятся.

## Сквозные принципы (после UPD3)

- **Δ каталога = 0.** Новых ключей `param_catalog` нет. Все рубильники — env-only `ClassVar`
  вне каталога, **default ON** (kill-switch).
- **Без поэтапной раскатки %** (`internal→10%→50%→100%` не требуется) — прецедент 10.21/10.22.
- **Инвариант `imported-history-immutable` НЕ снят:** `smart_messages`/FTS/vec/`import_checkpoints`
  не мутируются ни при каких флагах и режимах.
- **Инвариант `manual-overrides-immutable` НЕ снят:** `persona_dossier_overrides` не трогается
  ни пересборкой, ни shutdown, ни rollback.
- **SQLite остаётся v12** на этапе spec; F1/F2/F3–F7 не меняют DDL. F8 использует файловый
  job-store (без DDL) — см. ADR-1022-8.

## Таблица: открытые вопросы Д-1…Д-11 → решение UPD3

| ID | Вопрос (откуда) | Решение UPD3 | Где зафиксировано |
|---|---|---|---|
| **Д-1** | Запускать ли боевой rebuild целевого чата сейчас? (ADR-1022-1) | **Да.** Вариант **(а)**; запуск боевой, страховка — авто-бэкап + JSONL-архив + post-check. | ADR-1022-1 §Human Gate; F1 tasks T-2026/T-2027 |
| **Д-2** | Снимать ли инвариант сырой истории? (ADR-1022-1) | **Нет.** `RAW_HISTORY_TABLES`/`assert_derived_table`/`_guarded_delete` неприкосновенны; «снятие блокировок» = только операционное трение CLI. | ADR-1022-1, spec §0.2/§2.1 |
| **Д-3** | Окно прогона: auto vs `--window-hours 0`? (ADR-1022-1) | **180 дней (4320 ч)** по умолчанию (не 168 ч); `effective_window` сохраняется; `--window-hours 0` = «всё в пределах `max_msgs`». | ADR-1022-1, F1 spec §2.2, §3 |
| **Д-4** | Симметричный фикс алиасов (backend+frontend)? (ADR-1022-2) | Данные в БД **есть**; **обязателен фикс рендера JSON-объекта на фронте**; backend-распаковка строки-JSON остаётся defense-in-depth (не обязательна). Restore из бэкапа **запрещён**. | ADR-1022-2, F2 spec §2 |
| **Д-5** | Отдельные флаги на пайплайны? (ADR-1022-3) | **Да**, env-only `ClassVar`, **default ON**, Δ каталога = 0: `SYSTEM2_FACTCHECK_ENABLED`, `SYSTEM2_SUMMARY_ENABLED`, `SYSTEM2_DIRECT_ENABLED`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED`. | ADR-1022-3/4/5/6/8, backlog §Активация |
| **Д-6** | Приемлема ли ×2 стоимость/латентность? (ADR-1022-3/4/5) | **Да** — физические 2 вызова утверждены. Ограничение — per-stage таймауты/лимиты + fallback. | ADR-1022-3/4/5 §Cost |
| **Д-7** | Fallback на 10.21 при невалидном JSON/таймауте? (ADR-1022-3/4/5) | **Да.** Пользователь всегда получает ответ; при провале Stage-2/JSON → одиночный путь 10.21. | ADR-1022-3/4/5 §Fallback |
| **Д-8** | Лёгкий code-strip markdown из выхода Рассказчика? (ADR-1022-4) | **Regex-стрип — только последняя сеть для технических тегов** (`<thought>`, `fact:\d+`, `msg:\d+`). Клише **не** вырезаются кодом (вето владельца) — ими занимается validator-loop. | ADR-1022-4/6, F6 spec §2 |
| **Д-9** | Оставлять ли `lore_compiled` вне System 2? (ADR-1022-5) | **Да.** Детерминированная HTML-выдача остаётся вне пайплайна. | ADR-1022-5 §Decision п.4 |
| **Д-10** | Агрессивность стриппера / `GuardedBot` / UX-строки? (ADR-1022-6) | **Вето на `string.replace` клише.** Scrubber тихо режет **только** теги `<thought>` и `fact:\d+`/`msg:\d+`. Клише → **браковка ответа + возврат Вербализатору (max 2 ретрая)**. `GuardedBot`-пояс — **не требуется** (остаётся опцией). | ADR-1022-6 (переписан), F6 spec |
| **Д-11** | Справка: полная переписка vs точечная? (ADR-1022-7) | **Переписать строго по регламенту**: `<blockquote>` для команд, только `<h1>`/`<h2>`, без точек/запятых/«или» между примерами, разжевать транскрипт vs выжимку, убрать п.11 «Безлимиты». | ADR-1022-7, F7 spec §2 |

## Сводка изменений артефактов (Step 2b)

| Фича | Файл | Действие |
|---|---|---|
| F1 `urgent-rebuild-dossiers-target-chat-round1022` | `spec.md`, `ADR-1022-1.md`, `tasks.md` | обновлено: вариант (а), окно 180 дней, **confirmed-cleanup + JSONL-архив**, точный скоуп, R1b/`rebuild_empty` сохранены |
| F2 `urgent-summary-aliases-ui-round1022` | `spec.md`, `ADR-1022-2.md` | точечно: Д-4 (frontend-first), restore запрещён |
| F3 `system2-factcheck-two-call-round1022` | `spec.md`, `ADR-1022-3.md`, `tasks.md` | интеграция **validator-loop** |
| F4 `system2-summary-two-call-round1022` | `spec.md`, `ADR-1022-4.md`, `tasks.md` | интеграция **validator-loop** |
| F5 `system2-direct-chat-two-call-round1022` | `spec.md`, `ADR-1022-5.md`, `tasks.md` | интеграция **validator-loop** |
| F6 `telegram-send-regex-guard-round1022` | `spec.md`, `ADR-1022-6.md`, `tasks.md` | роль изменена: scrubber тегов + **детектор клише + петля возврата** |
| F7 `help-ui-system2-round1022` | `spec.md`, `ADR-1022-7.md` | Д-11: полная переписка по регламенту |
| **F8** `dossier-rebuild-async-ui-round1022` | `spec.md`, **`ADR-1022-8.md`** (новые) | async job-store + API + прогресс + persistence + cancel/rollback |

## Остаточные риски (приняты владельцем / не снимаются)

- **R1b (F1, Critical):** over-delete производных — `effective_window ≥ возраста удаляемых строк` +
  инвариант `rebuild_empty` (ненулевой exit) + JSONL-архив + авто-бэкап.
- **R1 (F1/F8, Critical):** confirmed-cleanup заденет валидные факты участников — предварительный
  JSONL-архив + защита `source_ids` живых убеждений + rollback-снапшот (F8). Beliefs/paradigms
  (`kind='belief'`) и `nodes/edges` **не трогаются**.
- **R2 (F8, High):** job не переживает краш процесса — статус `interrupted` + ручной rollback
  (осознанное решение: авто-возобновление LLM-пересборки небезопасно).
- **R17/R18:** SSH-значения не цитируются; в логах/отчётах — только counts/коды.
