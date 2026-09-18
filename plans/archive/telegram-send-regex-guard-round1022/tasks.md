# Задачи: telegram-send-regex-guard-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: T-2092/T-2093) · Тип: канон промптов + backend `services/**`
> **ТЗ:** `plans/current_task.md`, UPD3 §3 (строки **259–262**) + «ЧАСТЬ 1 → 4» (215–218). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **UPD3-дельта (Step 2b @Architect):** **вето на `string.replace`/regex-вырезание клише**; scrubber тихо режет **только** `<thought>`/`fact:\d+`/`msg:\d+`; клише → **детектор + браковка ответа + возврат Вербализатору (max 2 ретрая)**. Детали — `spec.md` §2.3, `ADR-1022-6.md`.

## Цель
(а) Расширить negative constraints против RLHF-клише («классика жанра», «как ИИ», «подводя итог», «в заключение», «надеюсь, помог», зеркальные «нет, ты»; текст рубленый/непредсказуемый).
(б) Ввести **единый Python-egress-предохранитель**: regex тихо вырезает `<thought>`-семейство, `fact:\d+`, `msg:\d+` (**клише не вырезаются**).
(в) Ввести **Validator Loop**: детектор клише → браковка всего ответа → возврат Вербализатору (**≤2 ретрая**) с negative-constraint сообщением → детерминированная деградация.

## ТЗ (кратко)
«Regex-middleware вырезает `<thought>`, `fact:\d+`, `msg:\d+`; при обнаружении запрещённого ИИ-клише — **забраковать ответ** и вернуть Вербализатору (max 2 ретрая): “Ты нарушил Negative Constraints и использовал запрещенное клише. Перепиши ответ полностью, сделав его естественным”».

## Решение (Шаг 0)
**Что уже есть:**
- Стрип reasoning/`<thought>`: `services/reply_postprocess.py:39-74` (`strip_reasoning_tags` — единственная точка среза), `services/summary_cleanup.py:20-30` (`cleanup_llm_text`).
- Negative constraints: `services/prompt_style_blocks.py:21-27` (`ANTI_BOT_BLOCK`) и `:30-34` (`ASYMMETRY_BLOCK`) + `STYLE_BLOCKS_SUFFIX` (`:37`) — подключаются в 8 канонов.
- **Чего нет:** удаления `fact:\d+`/`msg:\d+` и **единого chokepoint отправки** — `bot.send_message` разбросан минимум по 7 сервисам (`summary_generator.py:401/461/468/473`, `nostalgia_worker.py:467`, `mimic_relay.py:56`, `dead_page_relay.py:703`, `smartmodule_utils.py:134-142`, `media_send.py:52`, `progress_reporter.py:160`).

**Что новое:**
- Расширение/новый блок клише в `services/prompt_style_blocks.py` (тонко: сам список клише — в коде, не в промпте).
- Единая функция-предохранитель `sanitize_outgoing` (reuse `strip_reasoning_tags`) + regex `fact:\d+`/`msg:\d+` (**без клише**).
- **Новый `services/negative_constraints.py`:** `find_forbidden_cliches` + `verbalize_validated` (детектор + петля ≤2 ретрая).
- Проведение всех точек отправки через chokepoint; канон-миграция для `prompt_style_blocks.py` (+ `CLICHE_RETRY_SYSTEM_PROMPT`).

**Конфликт / инварианты:**
- Не дублировать стрип: единый chokepoint вместо правок в каждом сервисе.
- Regex не должен резать легитимный текст → якорные границы слов.

## Задачи
- [x] **T-2062** [@Architect] ADR: единый chokepoint (где, как), реестр **всех** мест отправки Telegram, порядок `strip_reasoning → regex-guard`, поведение при `parse_mode=HTML`, откат; **роль детектора клише + петли возврата**.
- [x] **T-2063** [@Builder] Расширить negative constraints в `services/prompt_style_blocks.py:21-37` (клише без дословного цитирования; рубленый/непредсказуемый текст) + новый `CLICHE_RETRY_SYSTEM_PROMPT`.
- [x] **T-2064** [@Builder] `services/outgoing_guard.py`: reuse `services/reply_postprocess.py:39-74` + вырезание `fact:\d+`/`msg:\d+`; **клише НЕ вырезать**; no-op без паттернов.
- [x] **T-2065** [@Builder] Провести все найденные точки `bot.send_message`/`edit` через обёртки `services/telegram_send.py` (реестр T-2062); тест покрытия.
- [x] **T-2066** [@Builder] Канон-миграция для изменённого `services/prompt_style_blocks.py` (`PREV_*` + `services/prompt_migrations.py` + `plans/docs/canon/**`).
- [x] **T-2067** [@Builder] Тесты scrubber: вырезание `<thought>`/`fact:\d+`/`msg:\d+`; отсутствие ложных срабатываний; клише **не** вырезаются кодом.
- [x] **T-2068** [@Builder] Регресс + байт-тесты канона; `node --check`/JS-гейты не затронуты.
- [ ] **T-2069** [@DevOps] Деплой + проверка живого ответа без `<thought>`/`fact:\d+`/`msg:\d+`; при клише — ответ перегенерирован; отчёт. **(не выполнено: DevOps/приёмка, вне скоупа @Builder)**
- [x] **T-2092** [@Builder] **UPD3:** `services/negative_constraints.py` — `FORBIDDEN_CLICHE_PATTERNS` (финальный список), `find_forbidden_cliches(text)->codes` (R17, fail-open), `verbalize_validated(generate_call, base_messages, max_retries=2)` + `CLICHE_RETRY_SYSTEM_PROMPT`.
- [x] **T-2093** [@Builder] **UPD3:** тесты детектора/петли: каждый код ловится; легитимные фразы не ловятся; брак → ретрай ≤2 → успех; исчерпание → деградация; bounded-вызовы; `bullet_list` только по флагу; R17-статы.

## Риски
- **R1 (High):** regex вырежет легитимный текст → якоря `\bfact:\d+\b`/`\bmsg:\d+\b` + тесты ложных срабатываний (T-2067).
- **R2 (High):** не все точки отправки охвачены → реестр из T-2062 + тест покрытия (T-2065).
- **R3 (Medium):** дублирование стрипа → один chokepoint, reuse `strip_reasoning_tags` (T-2064).
- **R4 (Medium):** канон-атомарность — `prompt_style_blocks.py` читают 8 канонов → `PREV_*` + один коммит (T-2066).
- **R5 (Medium):** chokepoint меняет HTML/эмодзи-доставку (`parse_mode`) → тест на HTML-пути (T-2067).
- **R6 (High, UPD3):** клише в prompt-константе ловит grep-тест → финальный список клише — в `services/negative_constraints.py` (код), в промпте только текст ретрая (T-2063/T-2092).
- **R7 (Medium, UPD3):** зацикливание/срыв ретраев → жёсткий `max_retries=2` + fail-open + деградация (T-2092/T-2093).
- **R8 (R17/R18):** секреты не логировать; исходные тексты не сохранять в отчёте; детектор возвращает только коды.

## Зависимости / ступени вливания
- **Предшествует F3/F4/F5** (System 2): даёт chokepoint-предохранитель + `negative_constraints` (детектор/петля) и общие negative constraints.
- Эксклюзив: `services/prompt_style_blocks.py`, `services/reply_postprocess.py`, `services/outgoing_guard.py`, `services/telegram_send.py`, `services/negative_constraints.py`.
- Общий канон-контур `services/prompt_migrations.py` + `plans/docs/canon/**` — **ступень: F6 первым** (до F3 → F4 → F5).
- **Feature flags:** `TELEGRAM_SEND_GUARD_ENABLED` (scrubber) и `SYSTEM2_VALIDATOR_LOOP_ENABLED` (детектор+петля) — env-only `ClassVar`, **Δ каталога = 0**, **default ON**; раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert`.
