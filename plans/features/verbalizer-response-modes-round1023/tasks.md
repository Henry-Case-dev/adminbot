# Задачи: verbalizer-response-modes-round1023

> **Раунд 10.23** · Приоритет **P0** · Шаг 1 @PM (+ Step 2 @Architect: `spec.md` + **ADR-1023-3**, UPD владельца 19.09.2026 — канальные правила) · Тип: backend/LLM + канон промптов
> **ТЗ:** `plans/current_task.md`, «Умный Вербализатор (3 режима общения)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F1, F2 (канон-контур).

## Цель
Синтезатор (Слой 1, Stage-1) определяет один из трёх режимов `response_mode` — `casual` / `serious` / `deep_research` — и передаёт его Вербализатору (Слой 2, Stage-2). Вербализатор по режиму формирует ответ: без «высокомерного профессора» и жалоб на «ленивого юзера», с сохранением саркастичного двачерского характера.

## Контекст / что уже есть
- System 2 двухслойный пайплайн уже есть: `services/system2_handoff.py` (строгая JSON-валидация: `parse_factcheck_analysis` `:75`, `validate_summary_digest` `:128`, `parse_direct_synthesis` `:140`), `services/factcheck_service.py::_check_claim_two_call`, `services/summary_generator.py::_generate_two_call` (`:298`), `services/direct_chat_service.py` (System 2 при непустом tool_trace).
- Базовые стилевые блоки: `services/prompt_style_blocks.py`; клише/ретраи: `services/negative_constraints.py::verbalize_validated` (`:132`).
- Вербализатор-промпты: `SUMMARY_NARRATOR_SYSTEM_PROMPT` (`services/summary_prompts.py:88`), аналоги в `chat_prompts.py`/`factcheck_prompts.py`.

## Ключевой конфликт (решает @Architect)
`response_mode` × строгий JSON-контракт `system2_handoff`: роутер должен жить **в Stage-1** (не третий LLM-вызов), иначе нарушается constraint **physical-two-call-pipeline**. Схему + валидаторы + тесты расширяем.

## Задачи
- [x] **T-2116** [@Architect] ADR-1023-3: `response_mode` в JSON-контракте Stage-1 (enum + default + валидатор), сохранение physical-two-call-pipeline (роутер только в Stage-1), выбор вербализатор-промпта по режиму, поведение при отсутствии/невалидном режиме (fallback), откат. Создать `spec.md` + `ADR-1023-3.md`.
- [x] **T-2117** [@Builder] Расширить `services/system2_handoff.py`: `response_mode` (enum `casual|serious|deep_research`) + валидатор/нормализатор; обновить `parse_factcheck_analysis` / `validate_summary_digest` / `parse_direct_synthesis` (fail-safe default).
- [x] **T-2118** [@Builder] Stage-1 промпты возвращают `response_mode`: summary editor, factcheck analyst, direct synthesizer (в тех же JSON-полях).
- [x] **T-2119** [@Builder] Базовый типографический блок для всех режимов в `services/prompt_style_blocks.py`: только короткий дефис (-) и двойные кавычки (""); запрет длинного тире (—) и елочек («»); разрешён мат/сленг; без понтов «я сделал за тебя работу».
- [x] **T-2120** [@Builder] Три варианта промптов Вербализатора: `casual` (торопливое письмо, запрет Markdown), `serious` (грамотно, минимальное форматирование, лёгкая циничная ирония), `deep_research` (полный структурированный отчёт; конкретная разметка задаётся канальным блоком — см. T-2183).
- [x] **T-2121** [@Builder] Оркестраторы выбирают Вербализатор-промпт по `response_mode` (`summary_generator`, `factcheck_service`, `direct_chat_service`); интеграция с `verbalize_validated` (F4-детектор) сохранена.
- [x] **T-2122** [@Builder] Канон-миграция ADR-1013-3 (слепки `PREV_*_R1023`, `services/prompt_migrations.py`, `plans/docs/canon/**`) — одним коммитом с T-2119…T-2121.
- [x] **T-2123** [@Builder] Тесты: определение режима по сэмплам, выбор промпта, типографика (нет `—`/`«`), запрет Markdown в `casual`, полный структурированный вывод в `deep_research`, отсутствие третьего LLM-вызова, fallback при отсутствии/невалидном режиме.
- [x] **T-2124** [@Builder] Регресс: стриминг/чанки саммари (R11 plain), фактчек, direct не сломаны; полный pytest 0 failed.
- [ ] **T-2125** [@DevOps] Деплой + живая приёмка: три режима различимы в живом ответе; отчёт (R17/R18).

### Канальные правила (UPD владельца, обязательны)
- [x] **T-2183** [@Builder] **Разделение форматных блоков по каналам** в `services/prompt_style_blocks.py`: `FORMAT_PLAIN_BLOCK` (Сценарий А: `<b>`-акценты + `- `-буллиты, категорический запрет таблиц любых видов) и `FORMAT_RICH_BLOCK` (Сценарий Б: полный Markdown/HTML, таблицы/сетки); narrator `deep_research` = база + `MODE_DEEP_RESEARCH_BLOCK` + ровно один канальный блок; выбор детерминирован каналом доставки (direct/factcheck/plain → plain-блок; Article F6 → rich-блок). Канон-слепки затронутых narrator-промптов — в том же коммите.
- [x] **T-2184** [@Builder] **Guard от таблиц на plain-канале:** `detect_plain_tables` (Markdown `|…|`, `<table>`, ASCII-сетки, разделители `---|`) + правило `plain_no_tables` в `services/negative_constraints.py` (bounded ≤2 ретрая, fail-open, без regex-реза); включается только для plain-каналов, на rich-канале не активно.
- [x] **T-2185** [@Builder] **Тесты «нет таблиц в plain-канале»:** ответы direct/plain-саммари с табличной разметкой бракуются/регенерируются; в финале нет `|…|`/`<table>`/ASCII-сеток; жирный `<b>…</b>` и буллиты `- ` присутствуют; `casual`/`serious` без Markdown; проверка safe-HTML доставки direct `deep_research` (фолбэк при `TelegramBadRequest`).
- [x] **T-2186** [@Builder] **Тесты «Markdown разрешён в rich-канале»:** `FORMAT_RICH_BLOCK` подключён для Article; `plain_no_tables` не активен; таблицы/сетки не бракуются и сохраняются в `InputRichMessage`.

## Критерии приёмки
- `response_mode` присутствует в JSON Stage-1 и валидируется; роутер только в Stage-1 (число LLM-вызовов не выросло).
- Три режима дают различимый стиль; `deep_research` выводит переданный структурированный отчёт полностью.
- **Каналы:** в plain-канале таблиц нет (guard `plain_no_tables`), жирный + `- `-буллиты есть; в rich-канале полный Markdown/таблицы разрешены.
- Типографика: нет `—` и `«»`; канон-миграция атомарна.
- Полный pytest — 0 failed.

## Риски
- **R1 (High):** третий LLM-вызов ломает constraint physical-two-call-pipeline → роутер только в Stage-1, тест числа вызовов (T-2116/T-2123).
- **R2 (High):** `deep_research` ломает R11/plain контракт саммари (Markdown не должен уходить в plain-каналы) → явное разделение каналов/режимов + регресс (T-2120/T-2124).
- **R3 (Medium):** невалидный/отсутствующий режим роняет ответ → fail-safe default (T-2117/T-2123).
- **R4 (Medium):** канон-атомарность → один коммит (T-2122).
- **R5 (R17/R18):** секреты/сырьё в логах.
- **R6 (High):** таблицы/тяжёлая разметка в plain-канале → `BadRequest: can't parse entities` (ParseError), ответ не уходит → канальные блоки (T-2183) + guard `plain_no_tables` (T-2184) + тесты (T-2185/T-2186).

## Зависимости / ступени вливания
- **Зависит от F1, F2** (канон-контур) → выполнять после.
- Эксклюзив канон-контура; F3 идёт **до F4** и **до F8** (UI-табы режимов).
- `services/system2_handoff.py` — общий с F7 (correlation-id/token-steps): согласовать порядок полей, не конфликтовать (F3 раньше, F7 читает).
- Требует `spec.md` + `ADR-1023-3` (Step 2 @Architect).

## Feature flag / раскатка
- `SMART_VERBALIZER_MODES_ENABLED` — env-only `ClassVar` (вне `param_catalog`, **default ON**, Δ каталога = 0); OFF → единый прежний Вербализатор. Раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert` + обратная канон-миграция.
