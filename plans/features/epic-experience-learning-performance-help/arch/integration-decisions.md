# EPIC-EXPERIENCE-LEARNING-PERFORMANCE-HELP — интеграционные решения (E / P / H)

- Источник: `plans/owner_inputs/2026-11-02-experience-learning-performance-help.md` (336 строк, sha256 `cf854d61…4458`).
- База: worktree `evol-71536a366a11-c63f6f44`, ветка `evol/impl`, HEAD `377ea6cd`.
- Статус документа: **решения заморожены для Builder**; код в этом документе не менялся.
- Внешние источники: не требовались — все решения repo-local (проверены по текущему коду). Reflexion/Mem0/A-MEM/Letta используются только как идеи по ТЗ, не как зависимости.

## 0. Проверенное состояние (факты, на которых стоят решения)

| Что | Где (file:line) |
|---|---|
| Единый горячий проход = один LLM-вызов `chat_with_tools`; гейт System2 снят с primary path | `services/direct_chat_service.py:4412`, `:4670` |
| Роли уже раздельны: `author / direct_addressee / reply_addressee / quoted_speaker / ambiguities` | `services/direct_chat_service.py:8868-8877`, `services/mca_retrieval_context.py:226-239`, `services/canonical_messages.py:91-101` |
| Свои доставленные ответы durable: `mca_bot_outputs` + SourceRef `bot_output:<id>` | `services/bot_output_ledger.py:1-18,69-120`, DDL v22 в `services/database.py` |
| Резолв цитаты/реплая ходит по лестнице, ступень 5 = Own Output Ledger | `services/quote_resolver.py:9,233-241`, `services/direct_chat_service.py:8940` |
| Уроки: `mca_lessons` (типы×5, scope×4, статусы×5, версии, counters, compat, merged_from) | DDL `services/database.py:1199-1242`; `services/mca_experience.py:42-72` |
| Свободный текст урока ЗАПРЕЩЁН: `CANONICAL_RECOMMENDATIONS` + `anonymity_violations` «non_canonical» | `services/mca_experience.py:103-166,306-307,1011-1015` |
| Отбор уроков: scope/active → compat → `relevance_score` токены/префиксы → utility | `services/mca_experience.py:421-448,1414-1497` |
| Жизненный цикл уже есть: propose/validate/activate/suspend/recheck/revise/merge, lineage | `services/mca_experience.py:994,1062,1145,1186,1204,1243,1312` |
| `experience.review` job: LLM-экстрактор, per-chat курсоры, watermark, reject-коды, дедуп | `services/mca_experience_jobs.py:61-63,385-405,426-498,1199-1361,1393-1460` |
| Типизированный `signal_json` — только ID/коды/числа (`sanitize_typed_json`) | `services/mca_experience.py:236-265`; `mca_experience_jobs.py:1412-1447` |
| Query-embedding на ходу уже считается в direct-RAG (`_PRIO_QUERY`), кэш `embedding_cache` | `services/summary_memory.py:5004-5015,2703-2720`; `services/direct_chat_service.py:11129-11201` |
| Векторный индекс один: `graph_facts_vec` (+`smart_archive`); поколения/identity | `services/database.py:6055-6113`; `services/embedding_control_plane.py:1690,2036` |
| Витрина опыта уже есть: funnel / lessons / lesson-action | `web/api/oversight_router.py:383-477`, `web/api/memory_agi.py:1420-1572` |
| Mini App: `app.js` 1 681 966 Б, `index.html` 1 126 126 Б (14 689 строк), `app.css` 421 508 Б; 17 синхронных `<script>`, ни `defer`, ни `async` | `web/app.js`, `web/index.html:17,14809-14862`, `web/static/app.css` |
| `no-store` для `.js/.css/.html` при наличии `?v=__APP_VERSION__` | `web/app.py:73-94`, `:294-315` |
| Компрессии в ASGI нет (GZipMiddleware отсутствует) | `web/app.py`, `bot.py` — нет вхождений |
| Справка: код-канон v9 + слепки + PG-ключи + сид/миграция/дрейф | `services/info_service.py:692,814,849-860,882,933`; `services/config_cache.py:232-235,303,331,416,443-527` |

## 1. ТРЕК E

### E-1. Где живёт «понял поправку сейчас» (E3)
**Решение:** смысловая поправка обрабатывается в СУЩЕСТВУЮЩЕМ единственном проходе `chat_with_tools`; в bundle добавляются только структурные слоты, никакого нового вызова.

1. `EvidenceBundle` получает аддитивные поля (пусто = байт-паритет с прежним поведением): `own_outputs: tuple[EvidenceItem,...]` (`entity_type="message"`, `entity_id="bot_output:<id>"`, `label="own_output"`, `sent_at`, `revision`), `dispute_target_ref: str|None`, `target_is_own_output: bool`. Источник — `mca_bot_outputs` через существующий ledger (`bot_output_ledger.py:69-120`) и уже резолвленный reply/quote (`direct_chat_service.py:8789-8877`); второй store не создаётся.
2. В промпт добавляется ОДИН новый блок данных `<Own_Recent_Outputs>` (≤ тех же ссылок, что уже ограничивает `_BUNDLE_BLOCK_MAX_REFS`): только ref + время + kind + verbatim текст своих последних output'ов этого чата, попавших в reply/quote-цепочку и в последние N ходов. Блок — данные, не инструкции (как `<Verified_Lessons>`, `mca_experience.py:1570-1606`).
3. Порядок блоков задаёт единственный композер: `<Own_Recent_Outputs>` выше `<RAG_Memory>` и выше `<Verified_Lessons>` (`services/prompt_composer.py:1108,1701` — существующий план блоков). Это даёт self-reference-приоритет (E6.5) структурно, без классификатора «это вопрос о себе».
4. Карта блоков описана в 5 канонических вариантах системного промпта — правка идёт во всех сразу + bump канона (`services/chat_prompts.py:130,137,161,168,200,207,264,271,379`).
5. Роль автора/адресата/цитируемого различается существующими полями; правило «поправка третьего лица ≠ ошибка бота» — это текст системного канона поверх готовых ролей, не новый код-фильтр.

**Доказательство «нет второго LLM-вызова»:** primary path = `chat_with_tools` (`:4412`, один вызов); `self_reflection.extract_self_essence` (`self_reflection.py:93-133`) остаётся как есть (после отправки, не до ответа). Новых вызовов до/во время генерации не добавляется; Reviewer проверяет это по счётчику provider-вызовов на один ход до/после.

**Отклонено:** (а) sync-судья поправки до ответа — прямо запрещено §0.2; (б) второй раунд генерации «сначала признай ошибку» — нарушает тон и стоимость; (в) детектор «это коррекция» регуляркой/словарём — запрещено §0.2 (нет хардкода смысла); (г) брать свои слова из `smart_messages` — корпус там human-only (`bot_output_ledger.py:13`).

### E-2. Контракт единицы опыта (E2) и схема батч-экстрактора (E4.2)
**Решение:** девять логических полей §E2 раскладываются по УЖЕ существующим объектам; новых таблиц нет, добавляются nullable-колонки.

| Поле §E2 | Куда | Не дублируем |
|---|---|---|
| 1. Ситуация | `mca_experience_episodes` (chat/user/task/trace/`source_ref_json`/`decision_json`) + новая `observation_json` | — |
| 2. Предыдущее действие бота | `mca_bot_outputs` + `mca_evidence_links(link_type='derived_from')` на `bot_output:<id>` | текст не копируем |
| 3. Реакция | `mca_experience_feedback` (`source_kind`+типизированный `signal_json`) | ref-only |
| 4. Объект коррекции | `observation_json.correction_object` — закрытый enum (`fact_about_person,temporal_reading,inference,search_method,tool,style,other`) | значение выбирает модель, набор проверяет код |
| 5. Epistemic | существующие `SEMANTIC_EPISTEMICS` → `outcome_reliability` (`verified/weak/hypothesis`, `mca_experience.py:93-98`) | — |
| 6. Revision | цепочка версий урока (`supersedes_lesson_id/version`) + новая `revision_reason` | — |
| 7. Lesson | `mca_lessons` (+ `principle/applies_when/do_not_apply_when` = существующие `recommendation/applicability/exceptions`) | — |
| 8. Application | `mca_lesson_applications` | — |
| 9. Outcome | `mca_lesson_applications.outcome/outcome_source/reliability/measurement/outcome_ref` | — |

- Схема результата экстрактора — версионированная: `EXPERIENCE_UNIT_SCHEMA_VERSION="exp-unit/v2"`, поля §E4.2 (`candidate_kind, source_message_refs, target_bot_output_ref, subject_entity_ref, old_claim, correction_or_observation, proposed_revision, reason, epistemic, confidence, applicability, exceptions, evidence_refs`) + `correction_object` + `private_fact` (bool). Старый `parse_semantic_candidates` (`jobs:426-469`) расширяется, не заменяется; неизвестная версия → `REJECT_PARSE`.
- Валидация LLM-ссылок (жёстко, fail-closed): каждый `source_message_ref` обязан быть в текущем окне (`rows_index`, уже есть — `jobs:1403-1407`) ИЛИ в durable carry-over этого чата; `target_bot_output_ref` обязан резолвиться в `mca_bot_outputs` этого чата и быть в reply/quote-цепочке либо в последних N своих output'ах; `subject_entity_ref` — из уже известных identity окна, иначе `unresolved` (не выдумываем). Любой невалидный ref → кандидат отклоняется (`REJECT_BAD_MSG_REF`), содержимое не сохраняется.
- Курсоры: остаются per-chat + watermark (`jobs:117-128,1279-1361`). Добавляется клампинг: `_advance_semantic_cursors(payload, rows, required_refs)` не двигает курсор чата дальше `min(earliest_required_ref) - 1`, пока требуемый ref не разобран; в payload — bounded durable `semantic_carry` (только refs, ≤64) для перехода через границу окна (E4.1/E4.6, кейс E-22). Сбой LLM/БД → курсор стоит (уже так, `jobs:1242-1245`).
- Окно обязано добирать текст reply-цели, если `reply_to_id` вне окна (bounded добор по id, без нового бюджета): иначе «который из тезисов спорят» не восстановить.
- `old_claim/correction_or_observation/proposed_revision` (цитаты) НЕ идут в `signal_json`/`mca_events` (там остаётся typed-only, `mca_experience.py:236-265`): они живут в `observation_json` с RBAC-чтением (см. E-6).

**Отклонено:** (а) отдельная таблица `experience_units` — прямой запрет §0.2/§E2; (б) складывать текст в `signal_json` — сломает R17-инвариант и телеметрию; (в) доверять `msg_ids` от модели без сверки с окном — кейс E-14.

### E-3. Жизненный цикл урока (E5)
**Решение:** операции реализуются существующими методами, добавляется только NOOP и контентные поля.

- `ADD` = `propose()` (`:994`); `REVISE` = `revise()` (`:1243`, новая версия + supersede); `MERGE` = `merge()` (`:1312`, `merged_from_json` + источники в `superseded`); `SUSPEND` = `suspend()` (`:1186`); `SUPERSEDE` = результат `revise/merge` (отдельного метода нет и не нужно); `NOOP` = решение не создавать версию: код возврата `noop_duplicate|noop_weaker|noop_unsupported` в счётчики job + `mca_events`, без записи в `mca_lessons`.
- Дубли определяются ДО создания версии: cosine(lesson_embedding, candidate_embedding) ≥ порога → маршрут в `REVISE`/`MERGE`; плюс структурный ключ `(type, scope, applies_when-нормализация)`. Порог — существующий стиль `mca_gates` (env-only), не хардкод смысла.
- Каталог `CANONICAL_RECOMMENDATIONS` перестаёт быть условием для НОВЫХ смысловых уроков: `propose()` больше не требует `(type, rule_key)`; каталог остаётся для детерминированных (не-LLM) предложений и как регрессионный набор. Сохраняются: `LESSON_TYPES`/`SCOPES` CHECK (DDL `:1203-1207`), `_forbidden_effects` (`:329-345`), `authorize_preference` (`:279`), виды валидации `VALIDATION_KINDS` (`:65-72`), обязательные EvidenceLink на эпизоды.
- Вместо `anonymity_violations`-«non_canonical» для global-уроков вводится проверка незагрязнённости: запрещены `@`, 5+ цифр подряд, display-name/username любого участника источника, и любой непрерывный фрагмент ≥32 символов (или ≥8 слов), встречающийся в тексте сообщений-источников. Это детерминированно, без словарей «фраза→урок».
- Поля урока: `principle`→`recommendation`, `applies_when`→`applicability`, `do_not_apply_when`→`exceptions`, `supporting_evidence`→`mca_evidence_links` (refs, не текст), `scope`→`scope/scope_chat_id/scope_user_id`, `version`→PK, `revision_reason`→новая колонка (`mca_lessons`).
- Приватный факт НЕ становится уроком: `private_fact=true` → запись идёт в существующую память факта в chat/user-scope (graph_facts/user memory), а уроком становится только обобщённое поведение без сущности (E5.3).
- Узкие предпочтения («пиши короче») валидируются как `explicit_preference` в `user_in_chat` без требования N повторов (`:1087-1097`); широкое обобщение требует независимых эпизодов (`:1117-1129`). Порог N сам по себе не доказательство — сохраняется как есть, не ужесточается.

**Отклонено:** (а) оставить канон-гейт и добавить «второй список фраз» — запрещено §0.2; (б) убрать `_forbidden_effects` вместе с каноном — потеря единственного барьера от эскалации; (в) свободный текст урока в global-scope без де-идентификации — утечка (кейс E-12).

### E-4. Смысловой отбор урока на ответ (E6)
**Решение:** `relevance_score` остаётся только recall-сетью; решение принимает cosine по существующему embedding-провайдеру, без второго индекса и без новых top-N/токенных бюджетов.

1. Вектор урока считается в async-контуре при `activate()`/`revise()` через `execute_embed` (приоритет записи), кладётся в НОВЫЕ nullable-колонки `mca_lessons`: `embedding_json`, `embedding_dim`, `embedding_generation_id`, `embedding_fingerprint`. Это не второй векторный индекс: нет `vec0`-таблицы и ANN, сравнение — в Python по ≤200 кандидатам scope (`list_scope_candidates(limit=200)`, `:620-634`).
2. Вектор запроса НЕ дублируется: в ходе его уже считает direct-RAG (`summary_memory.py:5008`, `_PRIO_QUERY`, кэш `embedding_cache`). `select_for_context(...)` получает `query_vector` от вызывающего (`direct_chat_service.py:8892-8896`); при отсутствии вектора — только recall-путь с честной пометкой `semantic_source="lexical_fallback"` в событии `retrieved` (не притворяемся семантикой).
3. Совместимость вектора: `embedding_generation_id`/`fingerprint` обязаны совпадать с активным поколением `graph_facts_vec` (`database.get_active_embedding_generation`, `:6055-6113`); иначе урок исключается с причиной `embedding_mismatch` (как `stale_context`, `mca_experience.py:1446-1450`). Пересчёт — в job при активации/`recheck`; существующие embeddings не трогаем.
4. Отбор: score = cosine × применимость (`scope`, `applies_when`, время) → `utility_score`; порядок и bounded-блок (`block_max_items/block_max_tokens`) остаются прежними. `select_by_rerank` (`mca_retrieval_context.py:118-150`) применяется только там, где LLM-реранк УЖЕ вызывается (`rerank_rag_facts`, `summary_memory.py:4778-4801`, гейт `flags.chat_rag_rerank_enabled` `direct_chat_service.py:11198`) — уроки идут вторым разделом того же ответа, с той же проверкой in-range ID. Новых вызовов не появляется.
5. Подсказка Planner/Writer: существующий `<Verified_Lessons>` уже несёт `[type] + principle + (применимо: …) + (исключения: …)` (`:1570-1606`); добавляется короткий маркер доверия `confidence=verified|weak` из `counters`/`outcome` и НЕ добавляется текст источника. Блок не приказ: «данные, не инструкции» уже зафиксировано в шапке блока.
6. Self-reference (E6.5): вопрос о собственных словах решается порядком блоков + новый `<Own_Recent_Outputs>` (E-1): сначала свой output-ref, потом уроки, потом RAG. Если происхождение имени не подтверждено — модель обязана признать необоснованность (текст канона), а не искать тёзок.

**Отклонено:** (а) отдельная `mca_lessons_vec` vec0-таблица — «второй векторный индекс» без доказанной необходимости; (б) LLM-судья применимости урока на каждый ход — новый горячий LLM-вызов; (в) оставить только `relevance_score` (текущее состояние) — прямо не выполняет E6.1/E-10.

### E-5. Доказательность (E7)
**Решение:** четыре состояния различаются по данным, которые уже есть, плюс два поля.

- `selected` = `SelectionResult.lessons` + событие `retrieved` (есть, `:1485-1496`).
- `delivered_to_model` = строка `mca_lesson_applications` (существующая запись при генерации, `direct_chat_service.py:3765-3772`), НЕ «использован».
- `used/attributed` = новое nullable `used_at` + `used_evidence_kind` (`technical_consequence|explicit_reference`) только при проверяемом следе (изменившийся tool-исход, отсутствие повторной ошибки при том же входе, явная ссылка человека). Без следа — остаётся `unknown`.
- `outcome_known` = `outcome != unknown` И `reliability == verified` (`link_application_outcome`, `:876-940`, `_COUNTED_RELIABILITY`); `social`/`llm_hypothesis` счётчики не двигают (уже так).
- Независимый поздний сигнал: новая коррекция того же типа ошибки другим автором, подтверждение целевого человека, технический исход инструмента. **Самооценка модели, частота употребления урока и число зелёных статусов reward не являются** — фиксируется явным `forbidden_reward` в коде расчёта и тестом.
- Replay/holdout: переиспользуется существующий (`jobs:2150-2229`) — он уже честно возвращает `improvement_measured=False`; расширяется новыми полями, но по-прежнему не объявляет причинный эффект без человеческого/технического исхода. Holdout — на сохранённых сценариях с одинаковым входом; при отсутствии данных UI пишет «недостаточно данных».
- UI (существующие витрины): `GET /api/oversight/experience/funnel` (`oversight_router.py:383`) и `GET /api/memory/lessons` + action (`memory_agi.py:1420-1572`) расширяются раскрытием: событие → свой output-ref → корректирующий сигнал → ревизия → статус → источник → применения → исходы; `selected/delivered/used/outcome` показываются раздельно, «9/2/0» без раскрытия недопустимо.
- Все переходы журналируются существующим `mca_events` (ID/статусы/время/refs); полные приватные тексты в общий лог не идут.

**Отклонено:** (а) считать `applied=true` успехом (кейс E-17); (б) оценка полезности самой моделью; (в) новая таблица метрик — вторая истина.

### E-6. Безопасность (E5.7, E15)
**Решение:** текст чата — всегда данные; эскалация невозможна по конструкции.

- Экстрактор: фиксированный system-промпт, чат — только `user`-role (`jobs:114-115,385-405`); инъекция «запомни навсегда» отклоняется промптом и `_forbidden_effects`.
- Урок не может стать system prompt/ACL/инструментом/секретом: остаются `_forbidden_effects` (проверка на propose+validate+activate), `LESSON_TYPES`/`SCOPES` CHECK, отсутствие write-пути из урока в prompt-канон или `param_catalog`.
- Секреты/`initData`/скрытые рассуждения: не логируются (R17), не попадают в `observation_json` (фильтр секрет-паттернов на записи, как `redact_secrets` в `system2_handoff`), global-урок проходит де-идентификацию (E-3).
- RBAC витрины: чтение `observation_json`/`lesson`-текста — только через существующие права (`edit_info`-подобные не переиспользуем; опыт — существующие права «Память»/`requires_permission`, как `memory_agi.py:1420`), секреты и `initData` в ответы не попадают; сервер проверяет права, не только скрытие в UI.
- Изоляция чатов: `scope_chat_id`-фильтр уже в SQL (`list_scope_candidates`), кейс E-12 покрывается существующим фильтром + тестом; `learning_enabled_for_chat` (U4, `jobs:1311`) сохраняется.

## 2. ТРЕК P

### P-1. Базовая линия и измерительный контур (без новой платформы)
**Решение:** один SHA, один локальный стенд, готовые инструменты; чисел «на глаз» не принимаем.

- Стенд: `tools/_asap31_smoke_server.py` (локальный uvicorn, SQLite, без Telegram/PG) либо production-equivalent; SHA и `APP_VERSION` фиксируются в отчёте.
- Клиент: существующие агентские MCP Playwright / Browser Use (трассы Chrome: LCP/FCP/long tasks/parse-compile), профили троттлинга сети и CPU фиксируются. Никакого нового benchmark-фреймворка в репозитории не создаётся.
- Режимы: **cold** (новый browser context, пустой кэш) и **warm** (тот же контекст + тот же релиз, повторный вход), desktop и mobile-viewport; реальный Android WebView без устройства — «не проверено» (P-16), не имитируем.
- Метрики (обязательный минимум в отчёте): TTFB, FCP, LCP, DOMContentLoaded, load; **время до полезного статуса** (кастомный `performance.mark`, ставится только когда пришли реальные данные, а не skeleton); время до первой интерактивной вкладки; отклик смены вкладки и выбора чата (mark→paint целевого вида); long tasks >50 мс; frame drops; число requests и compressed transfer bytes; статусы кэша (memory/disk/304); JS parse/compile; для API — число SQL, топ-5 SELECT по времени, размер JSON, event-loop lag. p50/p95 по ≥7 прогонам (малая выборка — весь набор значений).
- Идентичность условий: одинаковые viewport, устройство/эмуляция, сеть, авторизация, набор данных, вкладка, состояние кэша, SHA и включённые стеклянные эффекты; холодное «до» не сравнивается с тёплым «после».

### P-2. Ранжированные кандидаты (эффект / риск / что нельзя менять)
| # | Что меняем | Ожидаемый эффект | Риск | Что НЕЛЬЗЯ менять | Приёмка |
|---|---|---|---|---|---|
| 1 | Политика кэша: `public, max-age, immutable` только для URL с `?v=<APP_VERSION>`; `.js/.css/.html` без версии — `no-cache` (ревалидация ETag), а не `no-store`; добавить `?v=` четырём vendor-скриптам без версии (`index.html:17,14809,14813,14816`); проверить GET/HEAD, ETag, 304, `Content-Length`, Vary | warm-вход перестаёт скачивать ~1.7 МБ JS + 0.4 МБ CSS; исчезает лишний round-trip на каждый файл | R2 (смешение старого JS с новым HTML) | HTML и авторизованные API не кэшируются; CSP без `unsafe-inline` | P-03, P-04: cache 200/304, байты, отсутствие mixed assets после релиза |
| 2 | Компрессия текстовых ассетов на реальном пути (Caddy/ASGI; в коде `GZipMiddleware` нет) + `Vary: Accept-Encoding`, без двойного сжатия | transfer bytes JS/CSS/HTML в 3–5× меньше | R1 (devops-конфиг) | существующая CSP/деплой; никакой новой сборки | замер HTTP и bytes после сжатия, P-05 |
| 3 | Bootstrap-разделение: первый экран грузит только Telegram init/auth + данные ТЕКУЩЕЙ вкладки; `/oversight`, аналитика, память, уроки, редакторы промптов — по открытию вкладки/deep link; уже есть механизм per-tab loader (`app.js:8067-8115`) — расширить, не переписывать | время до полезного «Статуса» | R2 (пустые чужие вкладки, deep link) | визуал, стекло, мобильная геометрия | P-02, P-05, P-16: полезный статус без загрузки скрытой аналитики |
| 4 | Отложенная загрузка тяжёлых vendor: Chart.js (208 КБ, используется лениво в `loadKeyHistory`), `ogl/liquidglass/delaunator`, `cognitive-map.js`, `execution_graph.js` — `defer`/dynamic import после первого полезного экрана; Vue остаётся синхронным | сокращение parse/compile и блокировки main-thread | R2 (эффект появится позже первого кадра, «прыжок» glass) | внешний вид и наличие эффектов; отказ необязательного не ломает вход | P-12 (эквивалентные скриншоты), P-15 |
| 5 | Прекращение невидимой работы: `document.hidden`, закрытая модалка, скрытый overlay, внеэкранные canvas — пауза rAF/ResizeObserver/движков, без изменения разметки | CPU/GPU idle, батарея, отзывчивость | R1 | восстановление без скачка геометрии; никакого глобального отключения стекла | P-07, P-08 |
| 6 | In-DOM шаблон: `index.html` 1.07 МБ компилируется Vue целиком при mount (full-сборка + `unsafe-eval`, `web/app.py:34-42`); вынести разметку скрытых вкладок в `x-template`-фрагменты, монтируемые при первом открытии (поэтапно, по вкладкам) | главный кандидат на «первый полезный экран» | R3 (регрессия разметки всех вкладок) | вся вёрстка, id/классы, responsive, fullscreen, подтверждение несохранённых изменений | P-01, P-02, P-09, P-12 по каждой перенесённой вкладке |
| 7 | API/SQL: `/config` (каталог+permission metadata), `/status`, `/oversight`, `/analytics` — только после baseline и `EXPLAIN`: keyset-пагинация, устранение доказанных N+1/повторных SELECT; без «второй таблицы быстрой истины» | p50/p95 бэкенда и время вкладок | R1 | единый source-of-truth `param_catalog`, RBAC/effective values, write-endpoints | P-10, P-14 |
| 8 | Устаревшие ответы при смене чата/scope: AbortController/request generation + проверка scope (P3.3.13), дедуп одинаковых GET | нет stale overwrite и лишних запросов | R1 | серверный RBAC, отсутствие «умного кэша» | P-06, P-11, P-13 |

Порядок обязателен: сначала P-1 baseline на SHA, затем 1–2 (сетевые, дешёвые), затем 3–5, затем 6 и 7 по результатам замеров. Пункт 6 без подтверждённого выигрыша не внедряется.

### P-3. Жёсткие запреты
- Skeleton/спиннер не считается «полезным экраном»; метрика «до полезного статуса» ставится по факту прихода данных.
- Запрещено «ускорять» отключением стекла/фона/анимаций, снижением качества картинки или урезанием функций (§P4.12, §0.2).
- Запрещены новые framework/сборка/зависимости и второй «умный кэш»; CSP без `unsafe-inline` сохраняется.
- Запрещено маскировать задержку коротким timeout, глобальным mutex или подменой отсутствующих данных нулями.
- Секреты, `initData` и приватные тексты не попадают в диагностические файлы/логи.

## 3. ТРЕК H (только условие входа и механизм; контент не проектируется)
- **Gate:** H открывается только когда ВСЕ предшествующие задачи очереди (включая E и P, AntiCliche/Memory/UI) — `REVIEW_PASS` + `DEPLOYED` + `LIVE_VERIFIED`. До этого контент справки не редактируется и не публикуется; «почти готово» не считается.
- **Место:** существующий канон/доставка — код-канон `services/info_service.py` (`DEFAULT_INFO_TEXT`, `INFO_CANON_VERSION=9`, слепки `_PREV_*`), Markdown-гайд (`GUIDE_KEY`, `GUIDE_CANON_VERSION=6`), сид-файлы `info_text.md` и `plans/docs/intelligence_user_guide.md`, PG-ключи `content.info_how_it_works` / `content.intelligence_guide`, RBAC `edit_info`, backup/reset API (`web/api/routes.py:1722-1860`). Новая справка не создаётся.
- **Версии:** bump канона + слепок в `_PREV_*`/`KNOWN_GUIDE_SNAPSHOTS`; версия гайда определяется ПО СОДЕРЖИМОМУ (`guide_version_for`), не хардкодом — поэтому «наугад» номер не ставится.
- **Ручные правки:** миграция `_migrate_intelligence_guide_r1023` (`config_cache.py:443-501`) уже различает: совпало с известным слепком → безопасная замена; неизвестный текст при отсутствии маркера доставки → одноразовая доставка С бэкапом; неизвестный текст при состоявшейся доставке → ручная правка владельца, НЕ затирается. Это поведение сохраняется; перед правкой читаются фактические deployed-версии и оба PG-значения.
- **Дата «обновлено»** ставится по факту успешного сохранения/доставки в PG, а не по дате ТЗ.

## 4. Общие инварианты (для Reviewer)
- OFF любого нового гейта = прежнее поведение бит-в-бит; новых обязательных согласований владельца не вводится (PET_PROJECT).
- Один store/один write-механизм: `mca_experience.py`, `mca_experience_jobs.py`, `mca_retrieval_context.py`, `SourceRef/EvidenceLink`, `mca_events` — расширяются, не дублируются.
- Идентичность embedding-провайдера/модели не меняется; существующие embeddings не пересчитываются.
- Никаких новых top-N/токенных/временных бюджетов «для порядка»; существующие ресурсные пределы сохраняются, при переполнении — смысловой отбор + checkpoint + явная деградация.

## 5. Миграции и откат
- SQLite `user_version` 40 → 41 (`services/database.py`): только `ALTER TABLE ... ADD COLUMN` nullable: `mca_lessons.{revision_reason, embedding_json, embedding_dim, embedding_generation_id, embedding_fingerprint}`, `mca_experience_episodes.observation_json`, `mca_lesson_applications.{used_at, used_evidence_kind}`. Существующие строки не перезаписываются; CHECK-констрейнты не пересобираются.
- PG: изменений схемы нет (H использует существующие ключи).
- Откат: выключение гейтов (`MCA_EXPERIENCE_*`) возвращает прежнее поведение; новые колонки остаются nullable и не читаются старым кодом. Пере-эмбеддинг уроков — идемпотентный job-шаг, откат = удаление векторов у новых версий, не пересчёт `graph_facts_vec`.

## 6. Параллельность (карта владения, без пересечений)
| Лейн | Файлы (эксклюзивно) |
|---|---|
| E-context | `services/direct_chat_service.py` (bundle/промпт), `services/mca_retrieval_context.py`, `services/prompt_composer.py`, `services/chat_prompts.py` (`READ_ONLY_PARALLEL` для остальных) |
| E-store | `services/mca_experience.py`, `services/database.py` (миграция v41), `services/config_cache.py` не трогается |
| E-extract | `services/mca_experience_jobs.py` |
| E-ui | `web/api/oversight_router.py`, `web/api/memory_agi.py` |
| P-cache/server | `web/app.py` (+ devops-конфиг компрессии) |
| P-frontend | `web/index.html`, `web/app.js`, `web/static/*` |
- `services/database.py` — `SERIALIZE` (одна миграция, один автор, мерж первым). `web/app.js`/`index.html` — `SERIALIZE` с любым UI-лейном cognitive map (другой worktree, файлы не пересекаются до мержа). E и P не пишут один файл: `BLOCKED_BY:deps` для `web/app.py` ↔ E-ui нет.

## 7. Приёмка (наблюдаемое доказательство)
- E: новые сценарии (не «Кирилл»), после restart, с не-каноническими формулировками: E-01, E-02, E-06, E-09, E-10, E-12, E-14, E-15, E-17, E-22, E-24 + `NOT_VERIFIED` при отсутствии живого сигнала. Тесты — интеграционные через реальные точки (`select_for_context`, `ExperienceReviewRunner`, bundle→prompt).
- P: P-01…P-16, с SHA, условиями и реальными числами; мобильный прогон без устройства — «не проверено» + конкретный blocker; визуальная эквивалентность (Playwright + Browser Use, скриншоты/видео при включённых эффектах).
- H: доставка подтверждена чтением PG/UI, а не только правкой сид-файла; тесты на запрещённые обещания прошлого текста; XSS/скрипты отбраковываются.

## 8. Риски
- R2: горячий путь E-1/E-4 (bundle+промпт+embedding) может добавить латентность → обязательный замер до/после и конкурентный запуск с RAG; деградация — честный lexical-fallback.
- R3: п.6 трека P (in-DOM → x-template) может сломать разметку скрытых вкладок → только поэтапно, с визуальной приёмкой по каждой вкладке.
- R1: политика кэша и компрессия затрагивают деплой/прокси → проверка на реальном пути, не только локально.
