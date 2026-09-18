# Задачи: system2-factcheck-two-call-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: T-2094) · Тип: backend/LLM + канон промптов
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 1. Фактчекер (2 шага)» (строки 200–204); negative constraints — п.4 (строки 215–218). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a923310`.

## Цель
Заменить костыль `<thought>` внутри одного промпта на физический конвейер из двух **независимых** вызовов LLM:
**Слой 1 — Аналитик** (текст юзера + сырые факты RAG → строгий JSON, перевод `fact:ID`/дат в человеческое время) → **Слой 2 — Вербализатор** (вход только JSON; физически без БД и системных тегов; дерзкий ответ).

## ТЗ (кратко)
Аналитик проверяет логику и переводит системные теги в человеческое описание времени («в августе юзер говорил…»). Вербализатор отрезан от базы и тегов.

## Решение (Шаг 0)
**Что уже есть:**
- Один вызов: `services/factcheck_service.py:55-157` (`check_claim`), CoVe в одном промпте — `services/factcheck_prompts.py:123-138`.
- Строгий grounding + CoVe (10.21, F2): `services/grounding_validator.py`; trusted-якоря из RAG/тулов — `services/factcheck_service.py:129-140` (fix S10.21-5).
- Канон-миграции промптов: `services/prompt_migrations.py` + PREV-слепки (`PREV_*_R1021`).
- Единая стадия пост-обработки: `services/reply_postprocess.py:39-74` (`strip_reasoning_tags`).

**Что новое:**
- Два промпта: `FACTCHECK_ANALYST_*` (строгий JSON) и `FACTCHECK_VERBALIZER_*` (JSON-only, без БД/тегов).
- JSON-контракт и строгий парсер/валидатор; оркестрация двух `llm.generate`.
- Fallback на одиночный путь 10.21 при сбое парсинга; env-only kill-switch.

**Конфликт / AMENDS:**
- **AMENDS подход 10.21** (тег `<thought>` в одном промпте) — слепки `PREV_*_R1021` **сохранить**, канон-миграция обязательна (ADR-1013-3): код + `plans/docs/canon/**` + `services/prompt_migrations.py` + тесты **одним атомарным коммитом**.
- Grounding не удаляется: он превращается в перевод тегов на слое Аналитика, а финальная проверка выхода Вербализатора опирается на regex-предохранитель (F6).

## Задачи
- [x] **T-2035** [@Architect] ADR: 2-вызовный пайплайн фактчека, JSON-схема Аналитика, AMEND 10.21-`<thought>`, fallback/kill-switch, откат.
- [x] **T-2036** [@Builder] Промпт Аналитика (`services/factcheck_prompts.py`): вход текст+сырые факты → строгий JSON; перевод `fact:ID`/`ММ.ГГГГ` в человеческое время.
- [x] **T-2037** [@Builder] Промпт Вербализатора: вход только JSON; без БД/тегов; стиль из `services/prompt_style_blocks.py`.
- [x] **T-2038** [@Builder] Оркестрация в `services/factcheck_service.py:55-157`: два независимых вызова `self.llm.generate`.
- [x] **T-2039** [@Builder] Парсинг/валидация JSON Аналитика + fallback на одиночный путь при сбое; env-only kill-switch.
- [x] **T-2040** [@Builder] Канон-миграция: `PREV_*` слепки + `services/prompt_migrations.py` + `plans/docs/canon/**`.
- [x] **T-2041** [@Builder] Grounding: выход Вербализатора не содержит `fact:\d+`/фантомных дат (`services/grounding_validator.py`).
- [x] **T-2042** [@Builder] Тесты: 2 вызова, JSON-контракт, отсутствие тегов на выходе, fallback при невалидном JSON.
- [x] **T-2043** [@Builder] Регресс + байт-тесты канона (`plans/docs/canon/**` ↔ константы).
- [x] **T-2094** [@Builder] **UPD3:** интеграция `services/negative_constraints.verbalize_validated` в Stage-2 (≤2 ретрая при клише → перегенерация → fallback 10.21 при исчерпании); `SYSTEM2_VALIDATOR_LOOP_ENABLED` (env-only, default ON); stats только коды/числа (R17).

## Риски
- **R1 (High):** двойная стоимость/латентность LLM → лимиты, таймауты, fallback (T-2039).
- **R2 (High):** невалидный/усечённый JSON Аналитика → строгий парсер + fallback на 10.21 (T-2039).
- **R3 (High):** утечка `fact:\d+`/`msg:\d+` через Вербализатор → опора на regex-предохранитель `telegram-send-regex-guard-round1022` (F6).
- **R4 (Medium):** канон-атомарность (ADR-1013-3) → слепки `PREV_*_R1021` не терять; один коммит (T-2040).
- **R5 (Medium):** «человеческое время» может исказить дату → тест на перевод `fact:ID`/дат.
- **R6 (R17/R18):** сырые логи/факты не должны попадать в отчёт с секретами.

## Зависимости / ступени вливания
- Зависит от **F6** (`telegram-send-regex-guard-round1022`): negative constraints в `services/prompt_style_blocks.py` и chokepoint-предохранитель.
- Общий канон-контур `services/prompt_migrations.py` + `plans/docs/canon/**` — **сериализовать: F6 → F3 → F4 → F5** (атомарно на фичу).
- Эксклюзив: `services/factcheck_service.py`, `services/factcheck_prompts.py`.
- Read-only/переиспользование: `services/grounding_validator.py`, `services/reply_postprocess.py`.
- **Feature flag:** `SYSTEM2_FACTCHECK_ENABLED` (env-only `ClassVar`, **Δ каталога = 0**), **default ON**; поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21); откат — kill-switch OFF / `git revert`.
