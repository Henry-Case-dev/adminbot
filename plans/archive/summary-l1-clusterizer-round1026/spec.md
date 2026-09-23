# spec.md — S3 `summary-l1-clusterizer-round1026` (Эпик 2, шаг 3: L1 «Кластеризатор»)

> **Раунд 10.26 · Эпик 2 («Summary Hybrid Pipeline») · Приоритет P0 · Тип: backend/LLM + канон промптов**
> **Step 2 @Architect (23.09.2026):** спека + **ADR-1026-5** (D1–D6: вариант (a) 2-вызовности, AMEND ADR-1022-4/1023-3/-6, судьба `cover_prompt`/`response_mode`, момент врезки, состав §82, контракт §95, deploy).
> **Задачи:** `tasks.md` (T-3253…T-3282, блоки 0/A–H). **ТЗ:** `plans/current_task.md` §80–§82, §92–§96, §104–§109, §113–§114.
> **Зависит от:** **S1** ✅ (MERGED §71, deployed 2.58.18) и **S2** ✅ (MERGED §73, deployed 2.58.21) — потребляет `RestoreResult.kept`, `build_l1_payload` (§92), `FilterResult.fragments` (§93; `Fragment.message_ids` — **DB `id`**).
> **Baseline (Step 0 @Memory):** HEAD `4007081` == `origin/master`, `APP_VERSION` **2.58.21**, pytest `.venv` **8569/0**, JS **43/43**, каталог **467/426/442/100/98/21**, **Δ DDL=0**, CSP/zero-build, R17/R18.
> **Продолжают:** S4 «Пакет фактов» §96 (потребитель `L1Result.payload`), S5 L2 Писатель (§97–§99, врезка L1+L2), S6 публикация (§100–§106, гейт), S7 `run_id`/логи, S8 узлы ExecutionGraph, S9 §113, S10 §107/§114.

---

## 1. Область / вне области

**В области S3 (этап «L1 — Кластеризатор», §80/§81/§94–§95):**
- Новый **чистый контракт** `services/summary_l1_contract.py`: JSON-Schema §95 (единый источник для парсера/валидатора/тестов), парсер (переиспользует `system2_handoff.parse_json_object`), канонизация, валидатор ID/evidence, **fail-closed**-результат `L1Result` с кодом причины.
- Новый **модуль L1** `services/summary_l1_clusterizer.py`: сборка входа из §92-payload → **ровно 1 LLM-вызов** → парсер → валидатор; упаковка §93-фрагментов в один вход; логи `L1_*`; resolver env-слота §82.
- **Промпт-канон** L1 (отдельный от L2, §81): `prompts.summary_l1_clusterizer_system_prompt` (+1 каталог, санкция D4), `PREV_*`-слепок, ступень `PROMPT_MIGRATIONS` + документированный ROLLBACK, эталон `plans/docs/canon/**`, байт-тесты — **одним коммитом** (ADR-1013-3).
- Env-only слот summary L1 (§82): `SUMMARY_L1_BASE_URL`/`SUMMARY_L1_MODEL_NAME`/`SUMMARY_L1_API_KEY`; «не выбрано» → глобальная основная модель.
- Метрики/логи §108/§109 аддитивно (`L1_START/COMPLETE/ERROR`, `threads_count`/`facts_count`/`chunk_count`/`invalid_reason`) — без узлов ExecutionGraph (S8).

**ВНЕ области S3 (не реализуется здесь):**
- **Врезка L1 в живой путь** — S5 (после S4-пакета фактов) / S6 (публикация); в S3 `services/summary_generator.py`, `_generate_two_call`, `_llm_generate`, `_run` — **вне diff** (T-3273 DEFERRED).
- Пакет фактов §96 — S4; L2 Писатель §97–§99 — S5; публикация/`generate_image`/`sendRichMessage`/fallback `sendMessage` §100–§106 — S6 (гейт S6/S10 + D4/ADR-1025-24 закрыт до live-приёмки Эпика 1).
- Слоты summary L2 (§82) и direct L1/L2 (§84) — **вне S1–S10** (S5 — L2; direct — отдельное решение после Эпика 2).
- S9 §113 (тестирование из Mini App) — отдельная фича; S7 `run_id` — S7 (S3 использует существующий `correlation_id`).
- Δ DDL, новые таблицы/поля, новые API/библиотеки, `web/**` — **нет**.

---

## 2. Факты аудита кода (перепроверено Step 2)

| Факт | Точка в коде |
|---|---|
| Ровно 2 физических вызова: Stage-1 «Редактор» (`step="stage1"`) → Stage-2 «Рассказчик» (`step="stage2"`) | `services/summary_generator.py::_generate_two_call:806-905`; fallback → `step="single"` `:449-465` |
| Тест 2-вызовности | `tests/test_summary_two_call_round1022.py:38` (`llm.generate.await_count == 2`); `test_summary_filter_integration.py:229`; `test_summary_context_restore_integration.py:303`; `test_summary_cover_round1023.py:517` |
| Stage-1 JSON: `{response_mode, digest, cover_prompt}` | `services/summary_prompts.py:94-169`; парсер `services/system2_handoff.py::parse_summary_handoff_ex:217-246`; нормализаторы `normalize_response_mode:68`, `normalize_cover_prompt:91` |
| `cover_prompt` — служебное поле того же JSON (третьего вызова нет) | ADR-1023-3 п.1; ADR-1023-6 п.1; hotfix4/ADR-1025-8 D1; `SummaryDraft{text,cover_prompt,response_mode}` `:129-141` |
| Стиль+`cover_prompt` конкатенируются в image-промпт | `compose_cover_image_prompt:144-156`; `_resolve_cover_prompt` `:478-479`; §104 не трогать |
| §92-вход L1 | `services/summary_context_restore.py::build_l1_payload:365-391` (`message_id←tg_message_id`, `author_id←user_id`, `display_name←author_name`, `message_type←media_type`, `reply_to_id`, `timestamp`, `chat_id` из запуска; `mentions` — только если поле есть) |
| `reply_to_id` — **TG** `message_id` | `services/thread_chain.py:153` (`get_smart_message_by_tg_id(chat_id, row["reply_to_id"])`) |
| `Fragment.message_ids` — **DB `id`** | `services/summary_filter.py:56-61,269-278` (`_row_id`); S1 spec/§71 |
| Бюджет/фрагменты §93 (существующие ключи) | `summary_filter.py::estimate_and_split:230` (`overlap=1`); `token_counter.resolve_context_tokens/resolve_chat_limit` |
| Промпт-канон: `resolve_prompt` + `PREV_*` + `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` | `services/prompt_migrations.py:92-193`; ADR-1013-3; эталон `plans/docs/canon/architecture.md:489-536` |
| `llm.generate(..., module="summary", step=...)` — analytics-метки, модель берётся из клиента | `services/llm_client.py::generate:953-1023`; модель per-call не переключается |
| Образец dedicated-слота (провайдер+модель+ключ, пусто → основная) | `llm_client.py::_worker_profile:1076-1094`; каталог `INTEL_HISTORY_*`/`INTEL_BG_*`/`INTEL_REFLECTION_*` `param_catalog.py:731-759,613-622`; F5-витрина `web/app.js:753-790` |
| F5-вкладки mod_summary | `web/app.js:570-602` (`prep/clusterizer/writer/models/limits/testing` — каркас, ADR-1025-15 D5) |
| Каталог: санкция Δ + переиздание frozen F8 | ADR-1026-1 D1 (прецедент +8/+2); ADR-1026-2 (repin sha256 + регенерация `tools/gen_param_registry_round1025.py` + recount) |

**Критично (установлено по коду):**
1. Сейчас **нет** dedicated-слота Саммари: оба вызова идут общей моделью `self._chat_model`; `module`/`step` — только телеметрия. Слот §82 — новая сущность, в S3 **не врезан**.
2. `build_l1_payload` уже отдаёт **TG** `message_id`; `reply_to_id` тоже TG; DB-id живут только в `Fragment.message_ids` (S1). Смешение пространств — источник Critical-риска.
3. Валидация ID обязана идти **по payload-индексу** (TG id), а не по строкам БД: L1 видит только payload.
4. §93-фрагменты адресованы S3 (ADR-1026-4 D2); S2 их не потребляет.

---

## 3. Трассируемость REQ → сценарии

| REQ | Источник (verbatim) | Сценарии |
|---|---|---|
| REQ-S3-01 | §80 «L1 — Кластеризатор → Пакет фактов → L2 — Писатель… Не переписывать работающий механизм публикации» | SC-01, SC-16 |
| REQ-S3-02 | §81 «Не использовать один общий промпт для всех L1 и L2. Это разные задачи» | SC-12 |
| REQ-S3-03 | §82 «Отдельная модель L1… Провайдер. Модель. Промпт. Параметры генерации. Существующую политику fallback… не выбрана → глобальную основную модель» | SC-13, SC-14 |
| REQ-S3-04 | §94 «Conversation Disentanglement. L1 НЕ ПИШЕТ САММАРИ… Выделить темы. Восстановить переплетённые разговоры… Сохранить хронологию. Выделить проверяемые факты. Результат — строгий JSON» | SC-02, SC-03, SC-08, SC-10 |
| REQ-S3-05 | §95 «Проверять: Корректность структуры. Существование message_id. Корректность evidence_message_ids. Отсутствие несуществующих ссылок» | SC-04, SC-05, SC-06 |
| REQ-S3-06 | §95 «Не передавать невалидный JSON в L2» + §106 «не публиковать пустое или выдуманное Саммари» | SC-07, SC-15 |
| REQ-S3-07 | §92 «Использовать только реальные доступные поля… Сохранять корректную идентификацию авторов» | SC-09 |
| REQ-S3-08 | §93 «Оценивать токенный объём… перекрывающиеся фрагменты… объединить темы… устранить дубли… не отрезать последние сообщения молча» | SC-08, SC-11 |
| REQ-S3-09 | §108 «L1_START. L1_COMPLETE. L1_ERROR» | SC-17 |
| REQ-S3-10 | §109 «L1_COMPLETE: Провайдер. Модель. Входные/выходные токены. Количество тем. Длительность» | SC-17 |
| REQ-S3-11 | §80/§81 + ADR-1022-4: L1 заменяет Stage-1, L2 заменяет Stage-2 ⇒ ровно 2 вызова | SC-01, SC-16 |
| REQ-S3-12 | §104/§105 + D4: обложка/`cover_prompt`/`response_mode`/публикация не тронуты; гейт S6/S10 закрыт | SC-16, SC-19 |
| REQ-S3-13 | §96 «Название. Описание. Хронологию. Факты. Подтверждающие ID…» — граница контракта (реализация S4) | SC-02, SC-10 |
| REQ-S3-14 | §113 — отдельная фича S9 | SC-20 (NOT_APPLICABLE) |
| REQ-S3-15 | §107/§114 минимальные тесты перед деплоем; deploy/bump — решение @Architect | SC-18 |
| REQ-S3-16 | ADR-1013-3: `resolve_prompt` + `PREV_*` + `PROMPT_MIGRATIONS` + ROLLBACK + эталон — атомарно | SC-12 |

---

## 4. Наблюдаемое поведение

### 4.1. Что активируется в S3 (без врезки)
```
[живой путь — НЕ меняется]
_run → get_window_messages → S1-фильтр → S2-restore → XML → Stage-1 «Редактор» → Stage-2 «Рассказчик» → публикация
                                                                     (ровно 2 LLM-вызова, await_count==2)

[S3 — новый автономный модуль, вызывается только тестами]
build_l1_payload(kept, chat_id)            # §92 (S2, без изменений)
  → pack §93-фрагментов в один вход        # overlap=1, дедуп, ASC
  → РОВНО 1 LLM-вызов L1                   # промпт-канон L1 + env-слот
  → parse_json_object (system2_handoff)    # фенсы/обрамление — существующая политика
  → validate/canonicalize (§95)            # fail-closed
  → L1Result{status, payload, response_mode, cover_prompt, metrics}
```
### 4.2. Режимы и статусы `L1Result`
- `ok` — ≥1 тред, все проверки пройдены; `payload` канонизирован, детерминирован.
- `empty` — валидная структура, но 0 тредов (весь вход в `unassigned`) → **в L2 не передаётся** (§106: не публиковать пустое).
- `invalid` — структура/типы/ID/evidence/лимиты нарушены → `invalid_reason` (код), `payload=None` → **в L2 не передаётся** (fail-closed).
- `truncated` — вход не влез в бюджет слота даже после упаковки → последние сообщения сохранены (гарантия S1), `skipped_ids` + WARN (не молча); обработка продолжается.
- `error` — исключение/`LLMError` → WARN `L1_ERROR`, `payload=None`; тихой потери нет.
### 4.3. Границы будущей врезки (S5/S6)
- Врезка — только S5 (когда существует S4-пакет фактов) / S6 (публикация), по санкции @Architect, **после** live-приёмки Эпика 1 (D4).
- До врезки: `services/summary_generator.py`, XML, промпты Редактора/Рассказчика, публикация, обложка — **вне diff**; OFF-цепочка байт-в-байт.

---

## 5. Контракты (D5, D2, D4)

### 5.1. JSON §95 (строгая схема; `services/summary_l1_contract.py`)
```json
{
  "schema_version": 1,
  "threads": [
    {"thread_id": "thread_001", "topic": "≤200 символов, без переводов строки",
     "message_ids": [101, 102],
     "facts": [{"text": "≤500 символов", "evidence_message_ids": [101, 102]}]}
  ],
  "unassigned_message_ids": [103],
  "response_mode": "serious",
  "cover_prompt": "english visual prompt"
}
```
- Обязательные: `schema_version` (int, ровно `1`), `threads` (list), `unassigned_message_ids` (list). `threads`/`facts` могут быть пустыми.
- **Служебные поля того же JSON (D2, опциональные):** `response_mode` ∈ `{casual,serious,deep_research}` иначе `""` (существующий `normalize_response_mode`); `cover_prompt` EN ≤300 по границе слова иначе `""` (`normalize_cover_prompt`). В L2-контент **не попадают** (изоляция как `stage2_payload`).
- **Лишние поля → `invalid`** (`unknown_field`): top-level — ровно 5 ключей; thread — ровно 4; fact — ровно 2. Политика строгая и детерминированная.
- `thread_id`: непустая строка `^[A-Za-z0-9_\-]{1,64}$`; канонизация — перенумерация `thread_001…` по `(timestamp первого сообщения, message_id)`; дубли `thread_id` не фатальны (перенумеровываются).
- `topic`: непустая, ≤200, без `\n`; `fact.text`: непустой, ≤500, без `\n\n`, без `contains_system_ids` (R17), без markdown-заголовков (`^#{1,6}\s`).
- **Хард-лимиты (превышение → `invalid`):** тредов ≤100 (`too_many_threads`), фактов на тред ≤30 (`too_many_facts`), всего фактов ≤1000. Промпт задаёт мягкие лимиты.
- **Кап «L1 не пишет саммари»:** никакой прозы/заголовков/списков — только `topic`-метка и атомарные `facts` с evidence; проверяется структурно + @Reviewer (SC-10).
### 5.2. Пространства ID (правило без подмены)
- Вход L1 — §92-payload; `message_id` = **TG** `message_id`; индекс валидатора строится **по payload** (первое вхождение).
- Выход L1 — только TG id из payload-индекса; `evidence_message_ids` ⊆ `message_ids` своего треда; `unassigned ∩ threads = ∅`; один id ровно в одном треде (`message_in_multiple_threads`).
- `Fragment.message_ids` (DB `id`) — только для упаковки §93; DB `id` → TG `message_id` через таблицу соответствия строк окна (`rows` несут оба поля). Неоднозначность/пропуск → `invalid` (`id_space_mismatch`); конвертация «на глаз» и фабрикация id **запрещены**.
- Покрытие: любой payload-id, не упомянутый моделью, детерминированно добавляется в `unassigned_message_ids` (`auto_unassigned_count`, WARN-метрика) — «не терять молча».
### 5.3. Парсер/нормализация/детерминизм
- Разбор — `system2_handoff.parse_json_object` (снятие reasoning-тегов/фенсов, первый `{…}` через `raw_decode`); не-JSON/нет объекта → `invalid_json`.
- Канонизация: `message_ids` — дедуп (первое вхождение) + ASC `(timestamp, message_id)`; `unassigned` — дедуп + ASC; факты — дедуп по нормализованному тексту (strip/casefold/пробелы) с объединением evidence; `thread_id` — перенумерация. Повторный прогон на том же входе — байт-идентичен.
### 5.4. Слот §82 (D4)
- Env-only ClassVars `SUMMARY_L1_BASE_URL`/`SUMMARY_L1_MODEL_NAME`/`SUMMARY_L1_API_KEY` (секрет не логируется) + forward-compatible резолв `hot.get("models.summary_l1_*", settings.*)` — **каталог/UI-слот — S5** (Δ каталога=0 в части слота).
- Резолв пары: `base_url`+`model` разрешаются **как согласованная пара** (пустое поле добирается из глобальной модели); `dedicated = any(непустое)`. `dedicated=False` → ровно текущее поведение (глобальная модель). Ошибка dedicated → **существующая политика fallback** (`LLM_FALLBACK_*`), без подмены на глобальную модель (наследование ≠ аварийное резервирование, §82).
- Параметры генерации — существующие (`LLM_TIMEOUT`/ретраи); temperature не вводится (дефолт провайдера, как сегодня).
- Вызов — `llm.generate(..., module="summary", step="l1_clusterizer", correlation_id=...)`.
### 5.5. Промпт-канон (D4, ADR-1013-3)
- `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` в `services/summary_prompts.py` — отдельный канон (не общий с L2), включающий формат §95 + служебные поля + правило «не писать саммари» + маркер целевого сообщения (`TARGET_INSTRUCTION_BLOCK`) + запрет системных тегов.
- Новый PG-ключ `prompts.summary_l1_clusterizer_system_prompt` (группа `prompts_summary`, advanced, роль `synthesizer`) — **Δ каталога +1 (санкция D4)**; доступен в «ИИ → Библиотека промптов → Сводки чатов» (§85, один промпт — один источник).
- `PREV_SUMMARY_L1_CLUSTERIZER_R1026` (слепок S3-канона) + ступень `PROMPT_MIGRATIONS` (идемпотентна; кастом пользователя не перезаписывается; до сида — skip) + документированный `ROLLBACK_MIGRATIONS`/процедура отката + эталон в `plans/docs/canon/architecture.md` + байт-тесты — **один коммит**.
### 5.6. §93-фрагменты и бюджет (D1)
- Оценка объёма — существующие `count_tokens` + `resolve_context_tokens`/`resolve_chat_limit`; фрагменты — существующий `estimate_and_split` (overlap=1, последний фрагмент всегда заканчивается последним `kept`).
- **L1-слой = ровно 1 физический LLM-вызов на запуск** (целевой пайплайн S5 = 2: L1+L2). Фрагменты **упаковываются в один вход** (ASC, дедуп, маркеры границ), а не обрабатываются отдельными вызовами: третий вызов — **блокер** (ADR-1022-3/4/5, инвариант 1). Мультивызовый merge по чанкам — **BLOCKED**; при нехватке контекста — детерминированный `truncated` + `skipped_ids` + лог (гарантия «не резать молча»). Пересмотр — только отдельным ADR при живых данных S6/S10.
### 5.7. Логи/метрики (§108/§109, аддитивно)
- `L1_START` / `L1_COMPLETE` / `L1_ERROR` (адаптация к формату существующих логов), `run_id = correlation_id` (S7 введёт формальный `run_id` — S3 не вводит).
- `L1_COMPLETE`: провайдер, модель, входные/выходные токены (`tokens_estimated=true` при оценке), `threads_count`, `duration_ms`; аддитивно `facts_count`, `chunk_count`, `auto_unassigned_count`, `invalid_reason`.
- R17: только числа/коды/id; без ключей, текстов сообщений и сырого ответа LLM.

---

## 6. Тесты S3 (без живой врезки) — §114/§107

| # | Сценарий | Проверка |
|---|---|---|
| SC-01 | Живой путь не изменён | `services/summary_generator.py` вне diff; существующие тесты зелёные |
| SC-02 | Ядро L1 на моках LLM | темы/переплетённые разговоры/хронология/факты; импорт модуля без сайд-эффектов |
| SC-03 | Хронология/связи | ASC `(timestamp,message_id)` внутри тредов; `reply_to`-связи сохранены |
| SC-04 | Структура §95 | матрица валид/невалид: типы, `schema_version`, лишние поля, пустые topic/fact |
| SC-05 | ID-матрица | несуществующий id; evidence вне треда; id в двух тредах; дубли; `unassigned`-конфликт; DB-id вместо TG → `invalid` |
| SC-06 | Покрытие | пропущенные id → `unassigned` (`auto_unassigned_count`), не потеряны |
| SC-07 | Fail-closed | битый JSON/фенсы/обёртки/обрыв → `invalid` + причина; `payload=None` (нечего передавать в L2) |
| SC-08 | §93 | фрагменты/overlap → один консистентный вход; усечение → `truncated` + `skipped_ids` + лог |
| SC-09 | §92-поля | только реальные поля; авторы не подменяются; `mentions` не выдумывается |
| SC-10 | «L1 не пишет саммари» | в выходе нет прозы/заголовков/абзацев (структурные проверки) |
| SC-11 | Детерминизм | двойной прогон байт-идентичен (порядок тредов/ID/фактов) |
| SC-12 | Канон | `resolve_prompt` → новый ключ; `PREV_*` байт-в-байт; миграция идемпотентна; ROLLBACK документирован; эталон = код = тесты |
| SC-13 | Слот | `dedicated`/наследование/пара-резолв; «не выбрано» → глобальная модель; fallback-политика; секрет не логируется |
| SC-14 | Слот не врезан | `step="l1_clusterizer"` в вызовах живого пути отсутствует; `await_count==2` |
| SC-15 | §106-гейт | `empty`/`invalid` → «нет корректного результата» → публикации нет (юнит-гейт) |
| SC-16 | 2-вызовность/регресс | `await_count==2`; Stage-1/Stage-2/`response_mode`/`cover_prompt` не тронуты; OFF-цепочка байт-в-байт |
| SC-17 | Логи | `L1_*` формат/поля §109; R17 (нет ключей/контента) |
| SC-18 | Deploy-гейт | полный pytest ≥ baseline 8569/0; JS 43/43; `test_zero_ddl`; каталог-числа после +1 |
| SC-19 | D4-гейт | публикация/обложка/XML/`summary_generator` вне diff |
| SC-20 | S9 | §113 не реализуется в S3 (граница зафиксирована) |

---

## 7. Инварианты, deploy, rollback (D6)

- **Ровно 2 LLM-вызова** на целевой пайплайн (L1+L2); в S3 вызовов не добавляется; L1-слой = 1 вызов; третий — блокер.
- **Δ DDL = 0**; **Δ каталога = +1** (санкция D4: промпт-ключ L1) → REGISTRY 467→**468**, Settings **426 (без изменений** — prompts-ключи PG-only, `settings_field=None`)**, categorized 442→**443**, GROUPS 100, `_TAB_BY_GROUP` 98, TAB_RULES 21. **Переиздание frozen-артефактов F8** по штатной процедуре ADR-1026-2 (repin sha256 + регенерация `tools/gen_param_registry_round1025.py` + recount/дельта) — обязательно.
- **CSP/zero-build** (stdlib + существующие сервисы, без новых либ); **R17/R18**; `plans/current_task.md` не изменяется.
- **Не ломать** §57–§73/F0–F11/S1/S2, публикацию/обложку/режимы, IA, сердцебиение; `summary_generator.py`/`summary_xml.py`/публикация — вне diff.
- **Deploy = ДА** (T-3280 применим): меняются рантайм-файлы (`param_catalog.py`, `summary_prompts.py`, `prompt_migrations.py`, `config/settings.py`, два новых модуля) и сид нового промпт-ключа в PG → **bump `APP_VERSION` 2.58.21 → 2.58.22** + `README.md` (version-тест) + cache-bust; перед деплоем — минимальные §114-тесты (SC-01…SC-18).
- **Откат:** hot — OFF не требуется (живой путь не тронут); `git revert` пакета + annotated-тег `pre-round1026-s3` (T-3253); канон-откат — документированный ROLLBACK (слепок `PREV_SUMMARY_L1_CLUSTERIZER_R1026`); seed-ключ в PG не перезаписывает кастом.
- **§17:** после деплоя workflow не останавливать; live-проверки — PENDING OWNER VERIFICATION; продолжение — S4.

---

## 8. Риски

| Риск | Уровень | Митигация |
|---|---|---|
| Третий LLM-вызов (per-chunk L1 / роутер) | **Critical** | D1: L1 = 1 вызов, упаковка в один вход; SC-14/SC-16 |
| Смешение пространств ID (DB `id` ↔ TG `message_id`) | **Critical** | D5: payload-индекс; явная таблица соответствия; `invalid` при неоднозначности; SC-05 |
| Невалидный JSON уходит в L2 / выдуманные факты | **Critical** | D5: fail-closed `L1Result`; SC-07/SC-15 |
| «L1 пишет саммари» | High | D5: структурные капы + промпт + @Reviewer; SC-10 |
| Потеря `cover_prompt`/`response_mode` при замене Stage-1 | High | D2: служебные поля того же JSON; §104 не тронут; SC-16 |
| Канон без `PREV_*`/миграции/эталона | High | D4/ADR-1013-3: один коммит; SC-12 |
| Преждевременная врезка L1 | High | D3: модуль автономен, `summary_generator` вне diff; T-3273 DEFERRED |
| Строгий валидатор → частые `invalid` | Medium | промпт жёсткий + толерантный парсер + коды причин + метрики; пересмотр на S5 |
| Δ каталога без переиздания F8 | Medium | ADR-1026-2-процедура в D6; SC-18 |

---

## 9. Ссылки

- **ADR:** `adr-1026-5-l1-clusterizer-contract-two-call-amend.md` (D1–D6, AMEND ADR-1022-4/1023-3/-6); `plans/archive/system2-summary-two-call-round1022/ADR-1022-4.md`; `plans/archive/verbalizer-response-modes-round1023/ADR-1023-3.md`; `plans/archive/summary-cover-rich-article-round1023/ADR-1023-6.md`; `plans/archive/hotfix4-cover-nav-shell-round1025/adr-1025-8-...md`; `plans/archive/cognition-4d-memory-round1013/adr-1013-3-prompt-canon-policy.md`; `plans/archive/epic1-verification-round1025/adr-1025-24-verification-gate.md`; ADR-1026-1/-2/-4.
- **Задачи:** `tasks.md` (T-3253…T-3282); трассируемость REQ-S3-01…-16.
- **Код-точки:** `services/summary_context_restore.py::build_l1_payload`; `services/summary_filter.py::estimate_and_split`; `services/system2_handoff.py::parse_json_object`/`normalize_response_mode`/`normalize_cover_prompt`; `services/summary_prompts.py`; `services/prompt_migrations.py`; `services/param_catalog.py`; `config/settings.py`; `services/llm_client.py::generate`.
- **Merge:** `plans/ARCHITECTURE.md` (§ S3 — T-3278); **архивация:** T-3279; **метрики:** T-3281.
