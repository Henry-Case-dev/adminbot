# REV-TOOLS-MINIFIX — вердикт (доступность чекапа ADD-TR.3 / слайс ADTR-TOOLS)

Независимое ревью. Read-only (чужие busy-лейны не тронуты); этот коммит — только данный документ.

**Кандидат (uncommitted поверх `d97d7cac`):** `services/direct_capabilities.py` sha256_12 `bbdaddc6901a`, `services/capability_registry.py` `f560b21793e1`, `services/direct_execution.py` `8785f554f4a0`, новый `tests/test_addtr_tools_minifix.py` `dadbedc29653` (15 тестов, CONTRACT owner=ADTR-TOOLS). Хеши сверены в дереве и в изолированном worktree; diff = **+63 строки в 3 файлах** (+новый тест) — как заявлено.

## 1. Capability-цепочка — воспроизведено
`CAPABILITY_TOOLS["health"] = ("get_bot_health",)` (конвенция совпадает с `response_extent.CAPABILITY_TOOLS`:`"health": "get_bot_health"` — имя уже было принято там); инструмент совпадает с каноном ToolRouter (`get_bot_health` + существующий `_get_bot_health`); инвариант `test_every_l1_capability_is_known_to_registry` — **1 passed** (мой прогон); деривация `health_N → get_bot_health {}` в `derive_simple_steps` добавлена — **без неё план не исполняется** (мой RED на base этим же файлом: **12f/3p** = архивные 10f/3p (13-тестовая редакция) + ровно 2 интеграционных теста, добавленных после фикса — README это честно оговаривает); анонс-словарь воспроизвёл сам: `health` в «ДОСТУПНЫЕ ВОЗМОЖНОСТИ» = True, `resolve(health) → ['get_bot_health'] rejected=[]`; полный `handle` → L2 Writer получает реальные данные (`test_full_handle_health_evidence_reaches_l2_writer` в 15/15).

## 2. Границы — подтверждено
`_build_health`: `unsupported/tool_absent` (нет анонса) → `disabled/checkup_module_disabled` (тот же `flags.checkup_enabled`, hot, что у 0g/исполнителя) → `ready`; диспетчер `elif cap == "health"` подключён. Исполнитель: OFF → «ОШИБКА get_bot_health: модуль выключен» без fetch/LLM; сервис недоступен/исключение/пустой отчёт → честные ошибки, без выдуманных данных. RBAC/секреты не расширялись: инструмент без аргументов (`inputs=()`, `additionalProperties:false`), chat scope из доверенного `ctx.chat_id`, новых логов/полей нет. Новый реестр/пайплайн не создан (REUSE: capability_registry + существующий ToolRouter-путь; +63 строки).

## 3. GEN free-form — тест валиден
`test_free_form_draw_reaches_single_image_workflow`: смысловая дверь `detect_action_intent` actionable=True при `is_image_keyword=False` (не регекс-путь), полный прогон сервиса → `gen_calls==1`, `l1_planner==1` — контракт «одна генерация на намерение через существующий контур», не тавтология.

## 4. Аудит-таблица (14 тулов) — классификации корректны; наблюдения
(a) `image_understanding` дет. деривация целится в текущее сообщение — **подтверждено кодом** (`direct_chat_service.py:2991-2992`: `reply_to_message_id=message.message_id`); владелец VISION-FIX-CORE/ADTR-VERIFY S2 — зафиксировано, не правится здесь. (b) `health` **отсутствует** в `_DEFAULT_VIEW_IDS` (проверено) — витрина вне scope ADD-TR.3 п.4; backlog/решение владельца. (c) `get_bot_health` **вне `METERED_TOOLS`** (проверено: frozenset в `tool_loop.py`) при LLM внутри — цитата аудита точна: ADR-1026-15 D3 прямо относит `get_bot_health` к **free/local** (spec tool-chains, стр. «Metered/Free-local»); ADR не менялся. **Это не блокер текущего лейна**: границы стоимости per-turn (dedup `_TOOL_MAX_SAME_CALL=2` — «одинаковый вызов ≤2 раз», `TOOL_MAX_TOTAL_CALLS=6`, `TOOL_MAX_ROUNDS=4`, metered-cap 4), доступ в 1–2 чатах владельца (PET), гейт `flags.checkup_enabled`. **Backlog-пункт** (не блок): смоук-контроль стоимости одного чекапа у Reviewer + вопрос о metering/кулдаун-паритете tool-пути с каноном 0g.

## 5. Числа — перепрогнаны
Новый файл **15/15**; инвариант реестра **1/1**; кластер из README (12 файлов, включая capability/checkup/ENTRY-соседей) — **478 passed**, 0 failed; RED на base — 12f/3p (сведение к архивным 10f/3p выше). Замечаний к числам нет.

## 6. Дисциплина
Периметр = ровно 4 файла + `evidence/tools-minifix/**`; чужие busy-файлы (RE-PIN/POSTGEN/VISION-UI: `prompt_registry.py`, f8-пины, плановые доки) не тронуты; мой коммит — только этот вердикт.

## Леджеру (рекомендация)
- `ADTR-TOOLS-CHECKUP`: **код → VERIFIED** (capability+деривация+реестр+15 тестов); **live → READY_FOR_LIVE (postdeploy)**: «бот, как состояние сервера?»/«проверь логи» в живом чате → TOOL_CALL get_bot_health → status=ok → ответ Writer'а с реальными данными (не «всё нормально» из памяти).
- `ADTR-TOOLS-AUDIT`: **VERIFIED** (аудит полный, 14×классификация, один доказанный дефект исправлен). `ADTR-TOOLS-REUSE-SOUL5/-FC/-VISION`: **VERIFIED по коду** (границы REUSE; live-остатки — по владельцам). `M-ADTR-TOOLS-FIVEFACTS`: F1/F2/F4 → V, F3/F5 → RFL (postdeploy). `M-ADTR-TOOLS-E2E`: код → V, live → RFL. `ADTR-TOOLS-GENIMG`: вход/одна генерация подтверждены тестом, живое списание — postdeploy.
- Backlog-маркеры: (b) `health` вне UI-витрины; (c) metered-нюанс (ADR-1026-15 D3 free/local; смоук стоимости у Reviewer); (a) `image_understanding` detail-target → VISION-FIX-CORE/ADTR-VERIFY S2.

## Вердикт
**Approved.** RED→GREEN воспроизведён (с честным сведением редакций), цепочка/границы/числа подтверждены, наблюдения классифицированы (блокеров нет; (c) — backlog).
