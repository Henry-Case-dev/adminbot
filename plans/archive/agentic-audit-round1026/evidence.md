# A0 `agentic-audit-round1026` — evidence (Step 3 @Builder, read-only)

- **Задача:** Step 3, блоки B–E (T-3484…T-3497) — read-only наполнение durable-артефакта.
- **Baseline:** HEAD **`e8065e9`** == `origin/master`; `APP_VERSION` **2.58.29**; тег `pre-round1026-a0` → `e8065e9`.
- **Дата:** 24.09.2026. **Агент:** @Builder. **Изменения product code:** **0**.
- **Durable-артефакт:** `plans/docs/agentic-audit-round1026.md` (создан).

## 1. Что аудировано (по блокам/файлам)

| Блок | Задачи | Файлы (read-only) | Разделы артефакта |
|---|---|---|---|
| **B** — инструменты/tool-loop/лимиты | T-3484…T-3487 | `services/tool_schemas.py`, `services/tool_loop.py`, `services/tool_router.py`, `services/llm_client.py` | §1 (карта 8/8), §2, §3, §7 |
| **C** — image + первопричина | T-3488…T-3490 | `services/image_generation.py`, `services/direct_chat_service.py` (пре-гейт/tool-врезка), `services/tool_router.py` (`_generate_image`), `services/worker_budget.py` | §4, §6 |
| **D** — память/фактчек/решения/тумблеры | T-3491…T-3494 | `services/direct_chat_service.py`, `services/dossier_prompts.py`, `services/summary_memory.py`, `services/factcheck_service.py`, `services/web_content_extractor.py`, `services/system2_handoff.py`, `services/summary_l1_contract.py`, `services/summary_fact_package.py`, `services/smartmodule_utils.py`, `services/param_catalog.py`, `services/feature_gates.py`, `services/worker_budget.py` | §5 |
| **E** — сборка/трассировка/handoff | T-3495…T-3497 | (сборка) + `plans/ARCHITECTURE.md` §65/§79 (REUSE-ссылки), `plans/current_task.md` §12/§54/§85/§104 | §8, §9, §10 |

## 2. Выполненные команды/пробы и результаты (read-only)

| # | Команда/проба | Результат |
|---|---|---|
| P-01 | `git rev-parse HEAD` | `e8065e9257077098476e5bf3892ccaeefe775717` |
| P-02 | `git rev-list -n1 pre-round1026-a0` | `e8065e9…` (тег указывает на baseline) |
| P-03 | `git status --short` | только `plans/docs/agentic-audit-round1026.md` (??), `plans/features/agentic-audit-round1026/` (??) — мои; `plans/MEMORY.md`/`plans/workflow_state.md` (M) — **не мои** (роли @Memory/@Orchestrator) |
| P-04 | `git diff --stat -- . ":(exclude)plans"` | **пусто** (0 изменений product code/тестов/конфигов) |
| P-05 | `git diff --check` | `check=0` (только CRLF-warning для не моих файлов) |
| P-06 | `rg "APP_VERSION = " config/settings.py` | `APP_VERSION = "2.58.29"` (bump не выполнялся) |
| P-07 | Подсчёт элементов `TOOL_CALLING_TOOLS` (парс `tool_schemas.py:337–348`) | **10** имён ровно; порядок канона подтверждён |
| P-08 | `rg -c "get_user_context" --glob "*.py" -g "!var/**"` | **0** совпадений (инструмент отсутствует — EV-21) |
| P-09 | Подсчёт определений схем `TOOL_* = {` в `tool_schemas.py` | **10** схем |
| P-10 | Просмотр `plans/ARCHITECTURE.md` §65/§79 | REUSE ExecutionGraph/analytics-adapter подтверждён (для handoff §8) |

> **Живой прогон провайдера (реальная генерация / LLM tool-probe) НЕ выполнялся** — read-only-ограничение ADR-1026-13 D2 / spec §4(d).

## 3. Покрытие SC

| SC | Где закрыт | Статус |
|---|---|---|
| SC-01 | артефакт §2.1 (инвентарь, канон 10) | ✅ |
| SC-02 | артефакт §2.2 (схемы/аргументы, `file:line`) | ✅ |
| SC-03 | артефакт §3.1 (tool-loop, роли, `tool_choice="auto"`) | ✅ |
| SC-04 | артефакт §3.2 (обработка результатов, plain-fallback) | ✅ |
| SC-05 | артефакт §3.3 (лимиты 4/2 + поведение при превышении) | ✅ |
| SC-06 | артефакт §4.1 (прямой image-контур) | ✅ |
| SC-07 | артефакт §4.2/§4.3 (tool-контур + сравнение) | ✅ |
| SC-08 | артефакт §5.1 (досье; отсутствие `get_user_context`) | ✅ |
| SC-09 | артефакт §5.2 (RAG/вектор) | ✅ |
| SC-10 | артефакт §5.3 (фактчек) | ✅ |
| SC-11 | артефакт §5.4 (Markdown из URL) | ✅ |
| SC-12 | артефакт §5.5 (Decision Making) | ✅ |
| SC-13 | артефакт §5.6 (JSON L1↔L2) | ✅ |
| SC-14 | артефакт §5.7 (реакции) | ✅ |
| SC-15 | артефакт §5.8 (тумблеры/лимиты) | ✅ |
| SC-16 | артефакт §1 (карта 8/8 × 10 + прямые пути) | ✅ |
| SC-17 | артефакт §7 (дубликаты/пересечения; канон 10) | ✅ |
| SC-18 | артефакт §6 (9 мест + 5 кандидатов, EVIDENCE/HYPOTHESIS) | ✅ (первопричина частично — см. §5) |
| SC-19 | артефакт §8/§9 (durable-артефакт, `file:line` baseline) | ✅ |
| SC-20 | P-04/P-05/P-06 + §9 (read-only, Δ DDL=0, Δ каталога=0) | ✅ |
| SC-21 | §9 (R17: только числа/коды/`file:line`; R18: тег цел) | ✅ |
| SC-22 | артефакт §8 (A1–A10 не реализованы; вход зафиксирован) | ✅ |
| SC-23 | артефакт §10 (матрица §12 пп.1–15 + §54 п.1 → REQ → SC) | ✅ |

## 4. EVIDENCE vs HYPOTHESIS

- **EVIDENCE: 34** (EV-01…EV-34, артефакт Приложение A). Все привязаны к `file:line` baseline `e8065e9` либо к read-only git-проверкам (EV-34).
- **HYPOTHESIS: 6** (HY-01…HY-06, артефакт Приложение A). Каждая — с планом проверки и волной A1–A10.
- **Запрещённый вывод** («дело только в промпте») не использован и опровергнут по коду (места №1/№2/№9 §12 исправны).

## 5. Незакрытые гипотезы и почему

| ID | Гипотеза | Почему не закрыта в A0 | Волна |
|---|---|---|---|
| HY-01 | Провайдер/модель не поддерживает `tools` | Живой прогон запрещён (D2); логов провайдера нет | A3/A4 |
| HY-02 | Реальная ошибка генератора изображений | Нет доступа к прод-логам в A0 | A3/A4 |
| HY-03 | Рубильник модуля фактически OFF (env/per-chat) | Фактическое состояние БД/env в A0 не читается (read-only) | A3 |
| HY-04 | plain-fallback (провайдер-отказ tools) реально срабатывает | Нет лога `provider rejected tools` | A3 |
| HY-05 | Описание/схема влияют на выбор модели | Влияние модели не измерено (дефекта по коду нет) | A3 |
| HY-06 | Симптом относится к свободной форме, а не к форме пре-гейта | Наблюдаемые запросы неизвестны | A3 |

**Итог по первопричине:** доказаны **code-path-механизмы** отказа (а/б/в из 5 кандидатов Step 0); кандидаты (г/д) и фактическое состояние рубильников остаются **HYPOTHESIS**. Полная первопричина в A0 **не установлена** — это честно зафиксировано (Critical KG `Risk-a0-false-toolcall-cause`), план проверки приложен.

## 6. Незакрытое / для следующих шагов

- **T-3496 (@Architect):** реконсиляция артефакта с ADR-1026-13; подтверждение готовности как входа A1.
- **T-3497 (@PM):** финальная матрица (в артефакте §10 уже заполнена) + формулировка A1.
- **T-3498 (@Reviewer):** единый gate (обе линзы) — проверка полноты 15/8/9/5, меток, read-only.
- **Первопричина image-tool-calling** — не закрыта (см. §5); требует пробы/логов в A3/A4 (вне A0).
- **Инварианты для Reviewer:** product-diff пуст (P-04), Δ DDL=0, Δ каталога=0, `APP_VERSION` без bump, тег/бэкапы целы; изменены только `plans/features/agentic-audit-round1026/**` и `plans/docs/agentic-audit-round1026.md`.

## 7. Реконсиляция @Architect (T-3496, read-only)

- **Изменено:** только `plans/docs/agentic-audit-round1026.md` (явные анкоры; реестр §10.1; матрицы §10.2–§10.4; сводка §8.3 «интеграция/анти-дубликат»; уточнение меток §6.1) и статусные строки `spec.md` / `adr-1026-13` (**Proposed**). Product code, `tasks.md`, `plans/current_task.md`, машинный блок — **не трогались**.
- **Анкоры:** все ссылки `#…` разрешаются; реестр — **38 явных анкоров** (`#s12-1`…`#s12-15`, `#root-cause-*`, `#epic3-*`, `#labels-*` и др.).
- **Orphan'ы:** §12 — **15/15**; §54 п.1 — **1/1**; **REQ — 19/19**; **SC — 23/23**. Orphan'ов нет.
- **Метки:** EVIDENCE/HYPOTHESIS согласованы с ADR-1026-13 **D2**; каждая гипотеза **HY-01…HY-06** имеет план проверки и волну **A3/A4**; гипотеза не подаётся как доказанная причина; вывод «только промпт» опровергнут.
- **ADR-1026-13:** остаётся **Proposed** (решения D1–D3 не менялись; Accepted — по факту merge/архивации, **T-3499**).
- **Read-only:** подтверждено — `git diff` по product-путям пуст; изменены только `plans/features/agentic-audit-round1026/**` и `plans/docs/agentic-audit-round1026.md`.
