# round1020 — «Летописец» (Lore Compiler) + рефакторинг RAG/UI + Agentic AI + Справка UI

Эпик завершён (OpenSpec Step 1 @PM → Step 8 @PM, 16.09.2026). Папка фичи: **одна** — фазы **A–H** внутри `tasks.md`.
Спеки/ADR — за @Architect (Step 2): **`spec.md` + `adr-1020-1…-8` (DONE)**.

**Статус:** ✅ **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (16.09.2026) — **Human Gate пройден**, решения **О1–О7** зафиксированы (`tasks.md` §Решения).

## Итог эпика (16.09.2026)

- **Реализация:** фазы **A–H** выполнены (@Builder Step 4). @Reviewer — **Approved**; @Scanner — **0 Critical / 0 High / 0 Medium / 0 Low** (5 Info); pytest **6546 passed / 0 failed**.
- **Архитектура:** `plans/ARCHITECTURE.md` **§45** (Merge, Step 7).
- **Деплой (Step 9 @DevOps):** коммит **`995cf83`** (+ R18-fix **`741b77c`**), запушено; на сервере `systemctl` **active**, MainPID **2668878**, SQLite **`user_version=12`**.
- **Архив (Step 8 @PM):** папка фичи — `plans/archive/round1020-lore-compiler-rag-refactor/` (перемещена из `plans/features/…`, все файлы + ADR-1020-1…-8 сохранены). R18-скан — чисто.
- **⏸ Открыто (human-pending):** **T-1904** (живая UI-приёмка), **T-1931** (приёмка Справки). **Follow-up:** **T-1932** (fallback точки 7, R26).

## Что внутри

- [`tasks.md`](./tasks.md) — полный план: фазы **A–H**, нумерация **T-1866…T-1931 (66 задач)**, решения О1–О7, DoD, риски (R1–R21), флаги, хендофф.
- [`spec.md`](./spec.md) — спека @Architect (Step 2, 🟡 PROVISIONAL → актуализируется под О1–О7 + БЛОК 7/8).
- `adr-1020-1…-6` — контракт метаданных · роутинг/хронология · Time Injection/tz · `compile_lore_story` · фактчекер · формат доставки историй.
  **ADR-1020-1 — ред. 3 (16.09):** разрешение конфликта T-1874 (двухъярусный контракт представления метаданных; остаток фазы B — точки 2/3/8/13; `<chat_history>`/legacy-RAG — байт-инвариант; ID/forward фактов — G/T-1924).
- `adr-1020-7…-8` — Agentic AI (БЛОК 7) + Справка UI (БЛОК 8) — **DONE** (Step 2 @Architect; все ADR-1020-1…-8 заархивированы).

## Исходное ТЗ

- `plans/current_task.md` (untracked) — БЛОК 0…БЛОК 6 + **UPD: О1–О7 (стр. 278–291) + БЛОК 7 (293–319) + БЛОК 8 (323–331)**.
  **⚠️ Содержит plaintext-секрет (SSH-пароль) — не коммитить, значение не цитировать (R17, решение О6).**
- Диагностика @Memory (Step 0): `plans/reports/global_map.md`, `plans/reports/round10.19_scanner_audit.md`, `plans/MEMORY.md`.
- Аудит @Architect (Фаза A, Step 2): `plans/reports/round1020_llm_engine_audit.md`.

## Решения Human Gate (О1–О7) — кратко

| # | Решение |
|---|---|
| **О1** | БЛОК 5.5 / 6.1 — **verify-only** (`T-1883`, `T-1906`); manual DeepDream привязать к кнопке **нового UI** и подтвердить. |
| **О2** | Time Injection — **первым USER-блоком**; system-промпт статичен, **Prompt Caching не ломать**. |
| **О3** | `compile_lore_story` — **простой флаг ВКЛ/ВЫКЛ, ДЕФОЛТ ON**; поэтапная раскатка 10/50/100 % **отменена**. |
| **О4** | Новый ключ **`limits.chat_timezone`** (расписания сна/бэкапа не смешивать). |
| **О5** | Глобальный `parse_mode = None` **сохраняется**; для историй Летописца **локально `parse_mode=HTML`** + **HTML-теги** в промпте. Меню не менять. |
| **О6** | `current_task.md` — untracked; секрет в git **не коммитить**. |
| **О7** | Аддитивная **`lore_stories` без бампа `user_version`**. |

## Фазы (кратко)

| Фаза | Содержание | ТЗ | Задачи | Тип |
|---|---|---|---|---|
| **A** ✅ | READ-ONLY аудит LLM-движка → отчёт; **Human Gate A пройден** | БЛОК 4 | T-1866…T-1871 | research (DONE) |
| **B** ✅ | Ядро памяти: метаданные (БЛОК 0), роутинг/хронология ASC/`/summary`/`dig_into_lore` (БЛОК 2), Time Injection + tz, анти-галлюцинации, persona fallback, «Безлимит (∞)» (БЛОК 5) | БЛОК 0/2/5 | T-1872…T-1885 | backend + prompts + UI-виджеты |
| **C** ✅ | Новая фича: tool `compile_lore_story(topic)` — граф + хронология + storytelling-промпт (**HTML**) + диффы/UPD, `lore_stories` (7→8 инструментов, флаг default ON) | БЛОК 1 | T-1886…T-1893 | backend / new feature |
| **D** ✅ | UX/UI мини-аппа: критич. баги binding/routing, досье участников, тикер досье, Liquid Glass, CSS Grid, sticky save, human-readable labels, рестайлинг Advanced-аккордеона (**меню НЕ менять**); ⏸ T-1904 — живая приёмка человека | БЛОК 3 | T-1894…T-1904 | frontend |
| **E** ✅ | Фактчекер: Full Tool Access + функциональный промпт; техдолг S10.19-15 / S10.19-23 / CLI retention | БЛОК 6 | T-1905…T-1912 | backend + prompts + ops |
| **G** ✅ | **Agentic AI:** (7.1) tool recursion fail-safe + graceful degradation + лог потерянных раундов; (7.2) `reasoning_content` + stripper reasoning-тегов + снятие канона «1-2 предложения» (P0); (7.3) Context Middleware + приоритет метаданных над капом + `graph_facts` (`tg_message_id`, `forward_from`) + миграция pg+sqlite; (7.4) EN-`description` всех схем + строгая типизация | **БЛОК 7** | T-1918…T-1927 | backend / LLM-движок + DDL |
| **H** ✅ | **Справка UI:** тексты (Летописец, Фактчек, безлимиты), удаление неактуального, **сохранение дерзкого стиля**; `services/info_service.py`/`info_text.md`/гайд, `web/`; ⏸ T-1931 — приёмка владельцем | **БЛОК 8** | T-1928…T-1931 | content/UI |
| **F** ✅ | SPEC_READY владельцу (**«go» получен**) → ревью (Approved) → аудит @Scanner (0 Critical/High/Medium/Low) → деплой (`995cf83`/`741b77c`) → архив @PM (охватывает B–H) | — | T-1913…T-1917 | финальные гейты |

**Порядок:** **A ✅ → {B ∥ D} → C → E → {G ∥ H} → F.**

## Дубли и «уже сделано» (не реализовывать повторно)

- **БЛОК 5.5** и **БЛОК 6.1** реализованы в раунде 10.18: `plans/archive/sleep-manual-cascade-badges/`, **ADR-1018-2`,
  коммит `16a8c0b`, тесты `tests/test_sleep_manual_cascade_round1018.py`, API `POST /api/memory/dream/run` → **verify-only**
  (T-1883, T-1906).
- **ASC-хронология** для DirectChat уже есть (`services/summary_memory.py:2316-2368`, канон D206) → БЛОК 2.6 = аддитивное расширение.
- **Advanced-аккордеон** уже есть (10.4 D / 10.11 F-11) → БЛОК 3.8 = рестайлинг.
- **Tool recursion** уже есть (`services/tool_loop.py`, `TOOL_MAX_ROUNDS=4`) → БЛОК 4 = READ-ONLY описание; **БЛОК 7.1** = новый скоуп (fail-safe поверх цикла).
- Имя тула в коде — **`dig_into_lore`** (`services/tool_schemas.py:72`), в ТЗ — опечатка `dig_into_lor`.
- **Reasoning/scratchpad, Context Middleware, `graph_facts.tg_message_id`** — отсутствуют (аудит Q2/Q3) → БЛОК 7 = новый скоуп.

## Каталог-Δ и флаги

- **+2 ключа:** `flags.lore_compiler_enabled` (**default ON**, О3) + `limits.chat_timezone` (О4) + N текстовых labels (T-1901). Точное Δ счётчиков фиксирует @Builder; эталон `tests/test_param_catalog.py`.
- **DDL:** `lore_stories` (аддитивно, **без** бампа `user_version`, О7) + расширение `graph_facts` (`tg_message_id`, `forward_from`, pg+sqlite, решение по `user_version` — ADR-1020-7).

**Baseline:** HEAD `2f3e1f0`; pytest **6326/0**; каталог **437/407/412/92/90/20**; SQLite **v11**; APP_VERSION 2.57.0.
