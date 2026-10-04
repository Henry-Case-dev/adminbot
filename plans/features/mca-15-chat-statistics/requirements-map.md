# MCA-15 `mca-15-chat-statistics` — requirements-map (Step 1 @PM, 05.10.2026)

Feature: **`mca-15-chat-statistics`** — достоверная статистика чата: ChatStatistics/StatsQuery, MetricResult, NumericClaim, уместность обращения к истории (эпик `memory-context-autonomy`, Wave 2), включая probe-кейс Васи (§26).
Источник: `plans/current_task.md:1094–1171` (§24; файл НЕ изменялся, R17) + probe `:1283–1321` (§26). Смежные обязательные: §19 приёмки `:919–923` (A38–A42), §20.2 `:1017` («Достоверная статистика / NumericClaim — ON, все пути отправки»), §21 `:1046–1093`, строка матрицы §27.1 `:1358` (ChatStatistics/NumericClaim).
Планирование: волновой план `plans/docs/mca-round1027-plan.md:135–138` (REQ MCA15-R1…R4), строка фичи `:202`, порядок Wave 2 `:235`; `plans/backlog.md:13`.
Нумерация задач: **T-4916+** (max занятого = T-4915, `plans/features/mca-08-character-speech/tasks.md:74`; совпадений T-4916…T-494x в репо нет — проверено grep).

---

## 1. Подтверждение: следующая незавершённая MCA-задача

Порядок из плана (`mca-round1027-plan.md:235`, дубль — `backlog.md:13`):

**Wave 2 (когниция):** `mca-04b` ∥ `mca-05` ∥ `mca-06` ∥ `mca-08` ∥ **`mca-15`** ∥ `mca-11` (внутри волны — параллель по зависимостям; **порядок списка — приоритетный хвост**, `plans/features/mca-08-character-speech/requirements-map.md:14`).

Последнее документированное указание на следующую задачу (`mca-08/tasks.md:74`, T-4915): «Следующая — Wave 2 (`mca-15`/`mca-11` по приоритету) сразу, без ожидания владельца».

| Фича | Статус | Ссылка |
|---|---|---|
| `mca-04b-dossier-rebuild` | ✅ RELEASED 2.58.41 + ARCHIVED | `plans/archive/mca-04b-dossier-rebuild-round1029/` |
| `mca-05-episodes-stories` | ✅ RELEASED 2.58.42 + ARCHIVED | `plans/archive/mca-05-episodes-stories-round1029/` |
| `mca-06-sleep-paradigms` | ✅ RELEASED 2.58.49 + ARCHIVED | `plans/archive/mca-06-sleep-paradigms-round1034/` |
| `mca-08-character-speech` | ✅ RELEASED + VERIFIED 2.58.55 (T-4915 reconcile/archive в работе) | `plans/workflow_state.md` NOTE 36 |
| **`mca-15-chat-statistics`** | ⏭️ **следующая незавершённая Wave 2** (приоритетный хвост: первый) | `mca-round1027-plan.md:202` |
| `mca-11-tools-costs` | после mca-15 в приоритетном хвосте (deps готовы; не отменяется) | `mca-round1027-plan.md:203` |

**Почему `mca-15`, а не `mca-11`:** оба хвоста Wave 2 разблокированы (`mca-15` deps `mca-03`+`mca-07` — закрыты; `mca-11` deps `mca-01`+`mca-13` — закрыты, `mca-round1027-plan.md:202–203`), приоритет задаёт порядок списка: и в плане (`:202` vs `:203`), и в волновой строке (`:235`), и в приоритетном хвосте mca-08-map (`:14`) `mca-15` идёт первым. Дополнительно: `mca-16` (Wave 3) зависит от `mca-15` (`:208`) — следующий шаг после mca-15 держит очередь; фикс «достоверная статистика/NumericClaim» — headline-строка релиза §20.2 (`:1017`).

**Почему не другие:** `mca-10a/16/09/10b` — Wave 3 (начинается после хвоста Wave 2; `:238–240`); `mca-18/19/20` — Wave 4; `mca-17c` — Wave 5 (`:213, :247`); `mca-22` — RELEASED 2.58.44 + ARCHIVED; `mca-23` заперт до завершения всей MCA-очереди (`current_task.md:20852–20859`).

**Проверка расхождений:** working-выжимка KG-памяти группировала `mca-15` в перечне Wave 3 — выбор устойчив при любом прочтении: `mca-15` раньше `mca-11` по приоритетному хвосту во всех документах, а Wave-3-пункты документированного опережения Wave-2-хвоста не имеют. Других расхождений не найдено.

---

## 2. Требования владельца (§24 `:1094–1171` + §26 `:1283–1321`)

Сквозная рамка: REUSE (`GEN-R19`), «уже исправленное подтвердить тестом, а не дублировать» (`:47, :75`); без второго координатора/провайдера/свободного text-to-SQL (`:1139`); все функции релиза — ON, kill-switch по прецеденту.

| REQ | Требование (суть §24) | Якорь | Проверяемый критерий | Приёмки |
|---|---|---|---|---|
| **MCA15-R1** | Воспроизводимый дефект вместо предположения: пути неверной интерпретации (prefix-OR вместо фразы; person/graph-expansion влияет на счётчик; COUNT сообщений ≠ occurrences; фильтры сниппетов расходятся со счётчиком; группировка по display name; формулировка «Найдено N упоминаний» приписывает точный смысл; total_mentions без метода; payload truncation; lore-агрегаты; полнота bot-history; классификация intent). Различать `social_banter`/`historical_evidence`/`chat_statistics` по контексту и reply, а не по слову «никогда»; смешанный запрос → две цели; без жёсткой реплики на пример и без блокировки инструментов для юмора; reason_code объясняет цель поиска; graph-expansion — только кандидаты, не условие измерения. | §24.1–24.2 `:1102–1133`; probe §26 `:1283–1321` | (R1a) §26-механизм воспроизведён на текущем HEAD или явно подтверждён как уже исправленный (с тестом); RED-доказательство для незакрытых путей; (R1b) подкол без просьбы → короткий ответ/реакция/молчание, отчёт не обязателен; «сколько сообщений содержат слово» → измерение; «найди, когда ты так меня называл» → одно подтверждённое событие, не подсчёт архива; (R1c) три числа кейса без исходных данных не выдумываются и не «сверяются» фиктивно | A42 `:923` |
| **MCA15-R2** | ChatStatistics поверх существующих репозиториев; доступ через структурированный режим существующего инструмента либо один специализированный (по уже развёрнутому контракту). StatsQuery: metric `messages/occurrences/distinct_authors`; match_mode `exact_phrase/token/prefix/all_terms/any_terms`; text/terms; author_ids; subject_ids (отдельно проверяемая семантика); chat/interval/timezone; source kinds; bot/human/unknown; quote/forward policy; normalization version; corpus scope. Author ≠ subject. Фильтры count и examples — из одного нормализованного запроса, до LIMIT. Display name — подпись к user_id, не ключ группировки. Цитаты/forward по метаданным; нет метаданных → unknown. Канонические ID, исключение доказанных дублей импорт/live; не складывать counts хранилищ без проверки пересечения (иначе partial + предупреждение). Watermark/revision snapshot: примеры и подсчёт из одной версии данных. | §24.3 `:1135–1147` | (R2a) truth set: фраза/OR/prefix/occurrences — разные измерения, корректные единицы и значения (A38); (R2b) author/time/quote/forward-фильтры применяются одинаково к числу и примерам, до LIMIT; (R2c) два одинаковых имени не сливаются; смена алиаса одного ID не дробит личность; (R2d) prefix не называется морфологическим анализом; корень слова, если неопределим, — явный prefix/формы с пометкой метода; (R2e) 2 млн строк — FTS/индексы, потоковые границы, read-only bounded jobs | A38 `:919`, A39 `:920` |
| **MCA15-R3** | MetricResult: metric_id, status `ok/partial/unsupported/error`, value (nullable), unit, query_spec/hash, human_label, scope, coverage `known_complete/partial/unknown`, time bounds, data_as_of/watermark, author IDs, filters, excluded/unknown counts, example_source_refs, duration, error/reason. `value=0,status=ok` — только после успешного расчёта области; timeout/ошибка → value=null. Числа — NumericClaim (metric_id/unit/scope); сервис готовит проверенную фактическую формулировку/слот; модель может окружение/стиль, но не единицу/число/автора/период; финальный сборщик подставляет числа из MetricResult после стилизации. Контроль на всех путях: обычный, System2, fallback, готовая lore-story, постпроцессор. Одна ограниченная коррекция; иначе детерминированная фраза с оговоркой или без неподтверждённой статистики. Не запрещать все цифры/цитаты; даты/возраст из источников не обязаны иметь metric_id. total_mentions без описания не отдавать; при урезании убирать examples, сохраняя schema/status/unit/scope/method; обязательное не помещается → `insufficient_output_budget`, value=null. Ошибка счётчика видна отдельно от сниппетов. Не хранить бессрочно число как факт о человеке; повторный запрос — пересчёт или валидный кеш по snapshot. Старые истории с ненадёжными агрегатами — пометить на перепроверку, не удалять lore. | §24.4 `:1149–1163` | (R3a) число другого metric через verbalizer/lore fallback не публикуется (A41); (R3b) ошибка count / обрезанный payload / частичный корпус → нет ложного нуля и «никогда» (A40); (R3c) stale cache после импорта/редактирования пересчитывается по snapshot; (R3d) обычная речь/цитаты/даты не блокируются; (R3e) enforcement — детерминированная подстановка/проверка, сильнее второго LLM-судьи | A40 `:921`, A41 `:922` |
| **MCA15-R4** | Диагностика: intent; аргументы инструмента с учётом доступа; исходный и нормализованный запрос; retrieval expansion отдельно; metric spec; corpus/snapshot; метод/единица; count status; NumericClaim mapping; исход проверки; финальная доставка; без секретов; из карточки/аналитики — переход к измерению и источникам. Регрессии §24.5 `:1171`. | §24.5 `:1165–1171` | (R4a) по одному trace владелец отвечает «откуда эти цифры»; (R4b) полный регрессионный список §24.5 зелёный (OR/фраза; 3 вхождения в одном сообщении; два одинаковых имени; смена алиаса; фильтр автора до LIMIT; год/часовой пояс; цитаты/forward/unknown; отсутствие bot messages; duplicate import; ошибка счётчика; payload truncation; число из другого metric; ноль в частичном корпусе; stale cache после импорта; обход через lore-story; подкол vs явная просьба); (R4c) R17-safe | A38–A42 `:919–923` |
| GEN-R17 (сквозное) | ChatStatistics/NumericClaim — строка обязательной матрицы §27.1: виджет «Измерения, проверки и отказы» → «Метод, corpus, единица, фильтры, число, полнота, итоговая формулировка». | `:1358`; §27.1 `:1331–1362` | процесс/стадии зарегистрированы в едином реестре mca-17a; widget ID — контракт для mca-17c (рендер не здесь); OFF → честный `not_run` | A48/A73 (контрактная часть, рендер — mca-17c) |

Проверка владельца (§24 `:1100`): любое число о статистике раскрывается в диагностике до MetricResult — что искали, кого считали, где, за какой период, что исключили, как получили.

---

## 3. Reuse-inventory (существующий код — переиспользовать, вторых механизмов не создавать)

### 3.1. Измерительные пути (FIX-точки §24.1)
- `services/summary_memory.py:877` `build_fts_query` — prefix-OR (`"kw1"* OR "kw2"*`); для измерений нужны фраза/токен/OR раздельно (§24.1 п.1). `services/summary_memory.py:2369` `count_mentions`.
- `services/database.py:5834` `search_messages_fts_count_by_author` — COUNT(*) сообщений (не occurrences), разбивка по `author_name`+`user_id`, `since/until` в SQL; рядом — `search_messages_fts_count` (`:5830`). Группировка/имя — не ключ личности (R16-каскад имён у вызывающего).
- `services/tool_router.py:606` `_query_chat_memory`; `:673` `_dig_into_lore` (person+graph-expansion в тот же FTS-запрос, `:697–712`; счётчик fail-open `:830–843`; `total_mentions` `:862`; рендер «Найдено N упоминаний» `:667`); `:336` `_dig_json_payload` (truncation сохраняет `total_mentions`); `_resolve_name`-каскад.
- `services/lore_compiler_service.py:70` `LoreCompilerService` (+`total_mentions` `:138`); `services/lore_prompts.py:285` `build_lore_story_user` (+`:290, :306–307`).
- Отрицательные границы: расширение графа — только кандидаты (§24.2 `:1133`); счётчик и сниппеты должны иметь общие фильтры (§24.1 п.4).

### 3.2. Единые контракты (обязательные к REUSE)
- **Retrieval/`retrieve()`:** `services/mca_retrieval_context.py:452` — единая точка комбинированного retrieval; обязательство `L-MCA07-5`: `mca-15` маршрутизирует retrieval через `retrieve()`, второй комбинированный retrieval запрещён (`plans/archive/mca-07-retrieval-context-round1027/spec.md:255`, review `:65`).
- **Identity (mca-03):** `(chat_id, tg_message_id)`, revisions, aliases; группировка только по каноническим ID.
- **Attribution/свежесть (mca-22, 2.58.44):** `services/claim_envelope.py` (speech acts/write-gate — не для intent статистики, границы не размывать), `services/response_freshness.py`; запрет отдельного paraphrase-постпроцессора — `tests/test_mca22_core_round1027.py:810–813`.
- **События/наблюдаемость (mca-13/17a):** `services/mca_events.py` `REASON_CODES` (аддитивное расширение — прецедент mca-06/mca-08), `services/mca_process_registry.py` (реестр процессов), `services/mca_gates.py` (прецедент kill-switch K1–K4 mca-08).
- **Постобработка/финальный сборщик:** `services/negative_constraints.py:342` `verbalize_validated` — существующая валидация после LLM; точка контроля числовых утверждений, а не новый перефразер.
- **Tool-поверхность:** `services/tool_schemas.py` `TOOL_CALLING_TOOLS` == 12 (канон; `:539`); `services/tool_loop.py` (вызовы/раунды). Выбор «структурированный режим существующего инструмента vs один специализированный» — решение @Architect (канон 12 не менять без явной санкции).

---

## 4. Conflict-audit (CA-15-1…10)

| # | Конфликт-кандидат | Существующий контракт | Действие mca-15 | Правило |
|---|---|---|---|---|
| CA-15-1 | Второй retrieval | `retrieve()` mca-07 (§99); запрет второго комбинированного retrieval | Вызов только `retrieve()`; graph-expansion — кандидаты для примеров, не измерение | L-MCA07-5; GEN-R19 |
| CA-15-2 | Второй identity/группировка | mca-03 `(chat_id, tg_message_id)`/revision/aliases; R16-каскад имён | Канонические ID; display name — подпись; слияние по имени запрещено | `:1145`; MCA03-R1/R3 |
| CA-15-3 | Второй постпроцессор/парафразер | `verbalize_validated`; mca-22 §18 (тест `:810–813`) | NumericClaim-контроль — детерминированная проверка/подстановка в существующем контуре; не второй LLM-судья | `:1161`; mca-22 |
| CA-15-4 | Запись измерений как фактов | mca-04a/04b provenance/write-gate | MetricResult — привязан к запросу/версии/дате; в факты о человеке не пишется | `:1155` |
| CA-15-5 | Второй словарь событий | mca-13 `REASON_CODES` + mca-17a реестр | Только аддитивные reason_code/стадии; второй канал телеметрии запрещён | §17; §27.1 |
| CA-15-6 | Шутка → обязательный отчёт | mca-08 CA-08-8: «подкол не форсирует отчёт; статистика — mca-15» (handoff T-4915) | Intent-различение — здесь; mca-08-граница сохраняется | `:1124–1133`; A42 |
| CA-15-7 | Преждевременный ToolResult mca-11 | mca-11 (Wave 2, после mca-15) вводит типизированные статусы ToolResult | count status MetricResult совместим с будущими `ok/empty/error/timeout/...`; контракт mca-11 не подменять | handoff mca-11 |
| CA-15-8 | Второй DecisionPolicy/action-schema | mca-09 (Wave 3): `reply/react/silent/tool`, `CoordinatorDecision` A7 | Различение intent — на уровне существующего координатора/tool-роутинга; action-schema не менять | `:1126`; `:15383–15385` |
| CA-15-9 | UI/витрина раньше времени | mca-17c (Wave 5) — рендер/действия | Только контрактные ID стадий/виджета; UI не делать; SQL обычному участнику не показывать | `:1169`; GEN-R17 |
| CA-15-10 | Лимиты/расходы | GEN-R7/§15.2 — зона `mca-11` (денежные лимиты OFF) | Не смешивать; mca-15 не вводит бюджетные механизмы | `mca-round1027-plan.md:119–121` |

Сквозные запреты: R17 (секреты/сырой текст не журналировать и не переносить), не изменять `plans/current_task.md` (R17/R18), не трогать runtime вне санкций, не создавать вторые identity/provenance/retrieval/bundle/постпроцессор/очередь/аналитику/координатор.

---

## 5. Что уже покрыто и что реально добавляет mca-15

| Область | Уже есть (проверить, не дублировать) | Реально добавить в mca-15 |
|---|---|---|
| Intent «шутка vs просьба» | mca-08 (banter≠bio, clarify), существующий tool-роутинг | Различение `social_banter`/`historical_evidence`/`chat_statistics`, reason_code цели, mixed-intent |
| FTS-поиск/счётчики | FTS5, `search_messages_fts_count*`, `_query_chat_memory`, `_dig_into_lore`, lore-агрегаты | Раздельные единицы (фраза/токен/prefix/OR; messages/occurrences/authors), общие фильтры до LIMIT, канонические ID/дедуп, snapshot |
| Retrieval | `retrieve()` mca-07 (без живого caller) | Маршрутизация примеров/кандидатов через `retrieve()` |
| Валидация ответа | `verbalize_validated`, mca-22 speech acts/attribution | MetricResult + NumericClaim + проверка чисел на всех путях + bounded-коррекция |
| Наблюдаемость | mca-13/17a реестр/события | Процесс `chat.statistics`, стадии измерения/проверки, диагностика §24.5 |
| Хранение | mca-14 реестр миграций; факты/провенанс | Решение по cache/snapshot — за @Architect (reuse или аддитивная версия) |

---

## 6. Зависимости и открытые заявки @Architect (Step 2 обязателен)

**Закрытые зависимости:** `mca-03` ✅ (§96; identity), `mca-07` ✅ (§99; retrieval/`retrieve()`; обязательство L-MCA07-5), `mca-22` ✅ 2.58.44 (attribution/freshness/запрет второго парафразера), `mca-08` ✅ 2.58.55 (handoff banter≠stats), `mca-17a` ✅ §100 (реестр/события), `mca-01/13/14` ✅ (транзакции/события/схема).

**Заявки на санкции (решение @Architect; PM не решает):**
1. **Δ DDL:** 0 (reuse `smart_messages`/FTS + существующие счётчики/watermark) либо аддитивная версия **v27** через реестр `mca-14` (+backup-guard), если санкционируется durable snapshot/metric-кеш; PG — no-op либо аддитивно.
2. **Δ каталога:** 0 (env-only) либо +N с переизданием F8 — только явной санкцией.
3. **Kill-switches:** env-only `MCA_CHAT_STATISTICS_*`/`MCA_NUMERIC_CLAIM_*` (точный список — @Architect; default ON, OFF = паритет 2.58.55).
4. **reason_code:** аддитивное расширение единого `mca_events.REASON_CODES` (второй словарь запрещён).
5. **Tool-поверхность:** reuse структурированного режима существующего инструмента vs один специализированный; канон 12 не менять без явной санкции (прецедент mca-19 «тулы 12→+1»).
6. **Risk:** плановый **R3** → обязателен `threat-failure-analysis.md`; финал — за @Architect/@Reviewer.
7. **Deploy:** практика CA-11 (пер-фичевый bump 2.58.55→2.58.56 либо DEFERRED_TO_RELEASE) — решение @Architect.
8. **Хранилище/кеш измерений:** recompute vs valid cache by snapshot; где живёт (reuse `task_jobs`/`mca_events`/новая таблица) — @Architect.
9. **Историческая полнота bot-history** (§24.1 п.10): где проверяется источник (SQLite vs PG vs импорт) — дизайн @Architect; в отчёте — честная формулировка «не найдено в доступной истории».

**Owner-часть live:** три числа кейса Васи сверяются только при наличии исходных данных (§24.5 `:1171`); live-примеры в реальном чате — `PENDING OWNER` без имитации (no-false-acceptance `:15167`, прецедент ASAP 4.4).

---

## 7. Out of scope (явно)

- Денежные лимиты/учёт расходов/бюджеты — **mca-11** (§15.2; GEN-R7); ToolResult-контракт цепочек — mca-11.
- Intent/Decision lifecycle, `reply/react/silent/tool` — **mca-09**; lessons/experience — **mca-16**; random exploration — **mca-10a/b**; рендер UI/диагностические действия — **mca-17c**; гайды — **mca-21**; SelfModel/vision/временной фактчек — **mca-18/19/20**.
- Вторые: retrieval/identity/провенанс/bundle/постпроцессор/словарь событий/координатор/LLM-провайдер.

---

## 8. Маппинг «REQ → приёмки → задачи»

| REQ | Приёмки | Задачи tasks.md |
|---|---|---|
| MCA15-R1 | A42 | T-4919…T-4922 |
| MCA15-R2 | A38, A39 | T-4923…T-4928 |
| MCA15-R3 | A40, A41 | T-4929…T-4933 |
| MCA15-R4 | A38–A42 | T-4934…T-4936 |
| GEN-R17 (контракт) | A48/A73 (частично) | T-4935 |
| Сводная проверка/ревью | §19 `:874–976`, §21 | T-4937…T-4938 |
| Deploy/live/reconcile | §20 `:986–1045`, no-false-acceptance `:15167` | T-4939…T-4941 |

**Статус документа:** `PLANNING_CONSISTENT` — при условии санкций @Architect (T-4917/T-4918) по пунктам §6. Код на шаге PM не менялся; `plans/current_task.md` не изменялся (R17).
