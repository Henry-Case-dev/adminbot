# Фича F4 — `direct-context-limit-expansion` (Расширение обрезки контекста Global_Context, развязка двух систем лимитов, починка token_counter/chars-fallback)

> **Статус: ✅ IMPLEMENTED — Батч D (@Builder, 16.09.2026)**; T-1810…T-1816, T-1861/T-1862 закрыты; гейты T-1809 (@Architect) / T-1817 (@Reviewer/@PM) — за ревью.
> **Spec/ADR:** создаёт @Architect — `spec.md` + **ADR-1019-4** (развязка контекстных лимитов + целевые значения).
> **Раунд:** 10.19 (UPD2, `plans/current_task.md:130-175`). **Нумерация:** T-1809…T-1817.
> **Тип:** backend + каталог/UI (`services/direct_chat_service.py`, `services/token_counter.py`, `config/settings.py`, `services/param_catalog.py`). **Приоритет:** **P1** (память бота «схлопнута» — качество ответов).
> **Зависимости:** **F2/F3** (каталог-Δ и UI-паттерн понятных настроек). **Конфликт файлов:** `services/param_catalog.py` (F3/F7), `config/settings.py` (F7), `services/direct_chat_service.py`.
> **ТЗ:** UPD2 **п.6** (строка 162: «контекст глобальный обрезают с семи тысяч токенов до 869») + (строки 164, 174) + чекап.
> **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/406/411/90/88/19**; SQLite **v10**; APP_VERSION 2.57.0.

## 0. Цель

Убрать жёсткое «схлопывание» контекста direct-чата (из ~7000 токенов до 869) и дать **понятную настройку** с человекочитаемым описанием. Развязать две независимые системы обрезки (`_build_global_context` vs `CHAT_CONTEXT_BUDGET_TOKENS`). Починить `token_counter`: `CHAT_THREAD_MAX_TOKENS=None` → осмысленный дефолт, убрать `chars-fallback`-костыль.

**Требуется (UPD2 п.6, строки 162/164/174):**
- «с семи тысяч токенов до 869» — **недопустимо**; лимит значительно расширить.
- Нужна **понятная настройка** в миниаппе с понятным человекочитаемым описанием.
- `token_counter` не должен «ныть, что токенный лимит не задан», и падать на chars-fallback 2000 — это костыль.

## 1. Доказательства / карта кода (HEAD `fd6acc7`)

- `services/direct_chat_service.py:1965-2035` — `_build_global_context`: ветка verbatim-режима режет окно по `limits.chat_global_context_limit` и считает `resolve_chat_limit(..., token_default=1000)` (`:1993-2002`).
- `services/direct_chat_service.py:2012-2015` — `budget = safe_budget(limit)`; при `tokens` → `safe_budget(1000)=869` (см. ниже) + WARNING `direct: global context truncated`.
- `services/token_counter.py:119-121` — `safe_budget(1000) = 1000 / TOKEN_SAFETY_MULTIPLIER(1.15) = 869`.
- `services/token_counter.py:124-140` — `resolve_chat_limit`: токен-лимит задан → tokens; иначе при заданном chars-env → chars-fallback + **WARNING** «токенный лимит не задан … chars-fallback=2000»; иначе дефолтный токен-бюджет.
- `config/settings.py:756-757` — `CHAT_GLOBAL_CONTEXT_MAX_TOKENS: int | None = None`, `CHAT_THREAD_MAX_TOKENS: int | None = None` (по умолчанию **None** → срабатывает chars-ветка).
- `config/settings.py:650,659,663` — `CHAT_GLOBAL_CONTEXT_LIMIT=100`, `CHAT_GLOBAL_CONTEXT_MAX_CHARS=4000`, `CHAT_THREAD_MAX_CHARS=2000`.
- `config/settings.py:865-869` — отдельный контур `CHAT_CONTEXT_BUDGET_TOKENS=4000` (+ доли map/global/thread/target/anchors/branch, `:1088-1102` каталог).
- `services/direct_chat_service.py:1125-1258` — `_apply_context_budget` (другой контур обрезки) — **развязать** с `_build_global_context`.
- `services/param_catalog.py:963-975,1017-1019` — REGISTRY `limits_chat`: `CHAT_GLOBAL_CONTEXT_LIMIT`, `CHAT_GLOBAL_CONTEXT_MAX_CHARS`, `CHAT_THREAD_MAX_CHARS`, `CHAT_GLOBAL_CONTEXT_MAX_TOKENS` («Потолок глобального контекста, **слов**»), `CHAT_THREAD_MAX_TOKENS` («Потолок ветки, слов») — **формулировки неточны** («слов» вместо токенов).

## 2. Требования

- [x] Расширить целевой лимит `Global_Context` (1000 → 5000; фиксирует ADR).
- [x] Развязать **две системы**: `_build_global_context` (собственный лимит) и `CHAT_CONTEXT_BUDGET_TOKENS`/`_apply_context_budget` — чтобы обрезка не срабатывала дважды и не «схлопывала» до 869.
- [x] `token_counter`: задать осмысленный дефолт `CHAT_THREAD_MAX_TOKENS` (не `None`); убрать/минимизировать `chars-fallback`-костыль и его WARNING.
- [x] Понятная настраиваемая в миниаппе настройка с человекочитаемым описанием (что режется, почему, что будет при увеличении/уменьшении).
- [x] Замерить фактические размеры контекста до/после (evidence: токены), уложиться в perf-бюджет запроса.
- [x] Каталог-Δ = 0 (формулировки без Δ; число ключей 437/407/412/92/90/20).

## 3. Constraints (инварианты раунда)

- **R16** (аддитивные поля/ключи), **R17** (без секретов).
- **Каталог:** Δ только санкцией владельца (human-gate (c)); формулировки ключей можно уточнить без Δ, если не меняется число ключей.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Канон промптов не трогать** (FACT_EXTRACT/CHAT_SYSTEM_PROMPT и пр.); изменение лимита контекста — не правка канона.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `node --check`; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** T-1809 (@Architect, ADR-1019-4).
- **Вверх (код):** **F3** — паттерн понятных настроек/каталог; **F2** — если лимиты контекста связаны с бюджетом ключа (разграничить!).
- **Вниз:** F7 (каталог/настройки памяти).
- **Порядок:** **F3 → F4**; F4 делит `services/param_catalog.py` с F3/F7 — свести Δ.

## 5. Definition of Done

- [x] Обрезка контекста больше не даёт бюджет 869 при исходных ~7000 токенах (evidence до/после).
- [x] Две системы лимитов явно развязаны и документированы; двойная обрезка устранена.
- [x] `token_counter` использует осмысленный токенный дефолт; chars-fallback не является основным путём (WARNING → debug).
- [x] Настройка видна в миниаппе с понятным описанием.
- [x] Полный `pytest` **0 failed** (6259); perf-бюджет запроса соблюдён; каталог-Δ согласован.

## 6. Чек-лист задач

- [ ] **T-1809 (@Architect, гейт):** `spec.md` + **ADR-1019-4** — целевые значения (токены) для `Global_Context` и `Thread`, развязка `_build_global_context` vs `CHAT_CONTEXT_BUDGET_TOKENS`/`_apply_context_budget`, судьба `chars-fallback`, состав настроек/описаний, точные Δ каталога; ответ на human-gate (e).
- [x] **T-1810 (@Builder):** рассчитать/выставить новый токенный лимит `Global_Context` (конфигурируемо; без хардкода значения в коде — через settings/каталог).
- [x] **T-1811 (@Builder):** развязать контуры: `_build_global_context` и `_apply_context_budget` не режут один и тот же текст дважды; задокументировать владельца каждого лимита.
- [x] **T-1812 (@Builder):** `token_counter` — осмысленный дефолт `CHAT_THREAD_MAX_TOKENS`; убрать/минимизировать `chars-fallback` и WARNING-«ной»; сохранить безопасное поведение на границах.
- [x] **T-1813 (@Builder):** каталог/UI — понятное человекочитаемое описание настройки(ок) контекста (что именно обрезается; единицы — «кусочки текста», round-10.9 jargon-гейт).
- [x] **T-1814 (@Builder):** тесты — новые значения/границы; развязка (нет двойной обрезки); `resolve_chat_limit` без chars-fallback-ветки; WARNING не срабатывает в штатном режиме.
- [x] **T-1815 (@Builder):** замер реального контекста до/после (evidence: токены/время), проверка perf-бюджета запроса.
- [x] **T-1816 (@Builder):** гейты — полный `pytest` 0 failed; `node --check`; каталог-Δ зафиксирован; `git diff --check` clean.
- [ ] **T-1817 (@Reviewer + @PM, гейт):** сверка DoD; подтверждение целевого лимита (human-gate (e)); согласованность ADR-1019-4 ↔ код; проверка отсутствия двойной обрезки.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | Увеличение контекста → рост стоимости/латентности | T-1815 замер; лимит конфигурируем; human-gate (e) |
| R2 | Две системы лимитов неявно связаны — «развязка» ломает поведение | ADR фиксирует модель; T-1811 + тесты |
| R3 | `chars-fallback` используется как страховка | Сохранить безопасный фоллбэк, убрать «WARNING-шум»; ADR решает |
| R4 | Δ каталога без санкции | Human-gate (c) |
| R5 | Формулировки «слов» вместо токенов вводят в заблуждение | T-1813 уточнение (без обязательного Δ) |
| R6 | Пересечение с F2/F3 по `chat_usage`/каталогу | Согласованное вливание; F3 → F4 |

**ADR:** требуется новый **ADR-1019-4**.

## 8. Feature flag / progressive delivery

- **Feature flag:** рекомендуется per-chat/глобальный ключ «расширенный контекст» для поэтапного включения (internal → тестовый чат → 100%), если ADR сочтёт риск стоимости значимым; иначе — безусловно + `git revert`.
- **Rollback:** `git revert` + возврат прежних значений лимитов (settings/каталог).
- **Progressive delivery:** применимо: тестовый чат → 10% → 50% → 100% (по решению ADR).

## 9. Handoff / деплой

`@Orchestrator` — план F4 готов. Spec/ADR — T-1809 (@Architect). Реализация — T-1810…T-1816 (@Builder). **Деплой (SSH + рестарт + live-проверка размера `<Global_Context>` в логах) — @DevOps. Секреты в репозитории НЕ хранятся.**

## 10. 🔴 Итерация 2 — UPD3 (15.09.2026): per-chat sentinel контекста + потолок безопасности

> **Источник:** `plans/current_task.md:189-207`. **ADR:** `../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`; `adr-1019-4` D3 (updated). **Обновлены:** `spec.md` §3/§4.6/§5/§9.

- [x] **T-1853 (@Architect, гейт) — ✅ DONE (Step 2).**
- [x] **T-1861 (@Builder):** `context_state` (`0=unset`/`−1=unlimited`/`>0=cap`); `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only, default 32000); `−1` общего бюджета → пропуск `_apply_context_budget`.
- [x] **T-1862 (@Builder):** дефолты-предохранитель 5000/3000/16000 + описания с sentinel-пояснением; **не** глобальный безлимит (целевой чат — сидом F3 T-1859).
