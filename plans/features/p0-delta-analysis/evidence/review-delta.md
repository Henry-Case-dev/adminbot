# P0 DELTA — независимое ревью (lane REVIEW-P0-DELTA)

- **Кандидат:** `2ac20bf3213b1f873ac9eff4993d06c9b908dfe7` (worktree
  `C:\Code\Python\adminbot-wt-delta-review`, detached), база
  `release/p0-2026-10-26` @ `87ad5908` (deployed 2.58.131).
- **Дата:** 26.10.2026. Ревьюер независим: правок кода не делал, прод/SSH/
  Telegram/LLM не трогал.
- **Источники:** вход владельца
  `plans/owner_inputs/2026-10-26-p0-delta-analysis.md` (§1-§14); карта
  `plans/features/p0-delta-analysis/requirements-map.json` (133 required);
  факты аудита `evidence/audit.md`; builder-свидетельства `evidence/impl.md`.
- **Метод:** полный диф 87ad5908..2ac20bf3 (10 файлов, +1669/-86) прочитан
  целиком; каждая интеграционная точка проверена по актуальному коду
  кандидата; прогонами подтверждено поведение.

## Вердикт

**Approved** (в объёме полосы: payload/unit-уровень, без LIVE-пробы §12 —
см. «Честные пробелы»). Блокирующих дефектов нет. Анти-шаблонный страж
владельца (§13) — без нарушений; Five fixes D1-D5 подтверждены по коду и
прогонам. Родитель от этого не становится DONE.

## Per-fix таблица (все CLOSED)

| Дефект | Статус | Код (2ac20bf3) | Проверка |
|---|---|---|---|
| **D1** Lore bypass без интента | **CLOSED** | `direct_l1.py:285-331` — предикат `lore_story_delivery_allowed` ТОЛЬКО по существующим полям плана (story-акты `creative`/`historical_recall`, structure=`story` → подмена; `research/explanation/comparison/summarization/clarification` и структуры `report/explanation/comparison/summary/steps` → подмена запрещена, интенция не определена → fail-open); `direct_chat_service.py:1317-1340` — `lore_story_override()` (никогда не бросает), call-site `3855-3857` гейтован, numeric-гард (MCA-15) сохранён ПОСЛЕ подмены; kill-switch `settings.py:575-576` `LORE_STORY_INTENT_GATE_ENABLED` (env-only ClassVar, default ON; OFF → прежнее поведение). Story при блокировке остаётся материалом: тул-результат `compile_lore_story` (JSON с `story`, `tool_router.py:3337-3346`) идёт в transcript Writer'а | `test_p0_delta_routing.py:74-179` (11 тестов: story/analysis-акты, канонизация «analysis/анализ»→research, fail-open, kill-switch, REGRESSION-пин call-site, extent НЕ сигнал маршрутизации) — зелёные |
| **D2** Период невыразим | **CLOSED** | Схемы: `tool_schemas.py:128-139` (`year_from/year_to` query_chat_memory), `:226-232` (`year_to` dig), top-level `author` с uid/me (`:110-127`), stats-`author` uid/me (`:178-184`); резолв периода `tool_router.py:1006-1043` (`_optional_year`: int-only, вне [2000, тек.год] → invalid; `_parse_memory_period`: since=max, until=конец года); инвалидный период → честный `unsupported/invalid_period` (`:1045-1056`; dig `:1196-1214`); фасады `summary_memory.py:2953-2960`/`:2976-2992` (keyword-only `since_ts/until_ts/author_ids`, kwargs ТОЛЬКО при фильтре — дефолтный вызов байт-в-байт, строгие сигнатуры заглушек тестов не ломаются); SQL-слой MCA-15 `database.py:8522-8526`/`:8554-8559`; stats `interval_to` `tool_router.py:1155` → `chat_statistics.py:510` | `test_p0_delta_routing.py:185-358` (схемы аддитивны required=["query"]; passthrough 2022..2024 → ts-границы; year_from без year_to → открытый конец; invalid → unsupported и поиск НЕ вызывается; stats interval_to + author uid/me) — зелёные |
| **D3** Покрытие/свежесть | **CLOSED** | Фильтры окна/автора — В SQL ДО LIMIT: `tool_router.py:808-824` (норм-режим), `:1298-1309` (dig); пост-фильтры сохранены как страховка; счётчик с ТЕМИ же фильтрами (`:857-866`); честное покрытие: «Показано X из N…» `:907-911`, `coverage{messages_total,messages_shown,facts_shown,sampling}` в ОБОИХ JSON-контрактах dig (`:1562-1568`, `:1585-1591`); `lore_dense_dialogs`: стрйд-сэмпл `ROW_NUMBER()%stride` по всему периоду при total>max_scan, total≤max_scan → прежний ASC байт-в-байт, ошибка window-функции → fail-open на `_dense_dialog_hits_asc` (`database.py:8865-8881`, `:8929-8965`) | `test_p0_delta_routing.py:361-534` («Показано 1 из 312»; без шума при полном показе; сниппеты узкого окна не теряются, kwargs в SQL; stride: плотный всплеск 2025 достигается при 40 разрежённых 2022-2024; паритет малого корпуса; dig coverage block) — зелёные |
| **D4** Субъект анализа | **CLOSED** | Единый резолв `tool_router.py:943-975` `_resolve_person_identity`: Telegram uid («123», «id:123», «user:123», regex `:212`) → «me/self/я/себя/мои» = `ctx.user_id` (нет → `caller_unknown`) → алиас/имя set-семантикой `_resolve_author_id:925-939` (ровно 1 мэтч; >1 → `author_ambiguous`, похожие ники не сливаются); отказ → честный JSON `:977-1003` БЕЗ выполнения поиска (фильтр автора не исчезает молча, имя не превращается в OR-токены); применён во всех трёх контурах: норм (`:783-796`), stats (`:1131-1148`, существующий reason-словарь), dig (`:1216-1235`, `_dig_person_terms` удалена, висячих ссылок нет — grep чист; каноническое имя uid идёт в name-формы для facts/target_user); упоминания без person/author не изменены | `test_p0_delta_routing.py:537-717` (uid-формы; me=777; me без uid → caller_unknown; дубликаты «вася» → author_ambiguous; незнакомец → author_unresolved и `search_long_term` NOT CALLED; без person — прежний поиск по упоминаниям; author-uid passthrough) — зелёные |
| **D5** L2-пересказы как свидетельства | **CLOSED** | Origin-метки из РЕАЛЬНЫХ данных: SELECT `search_graph_facts_fts` несёт `f.origin`/`f.status` (`database.py:10190-10196`); `_DIG_FACT_ORIGIN_LABELS` `tool_router.py:210-221`, `_fact_origin_label:1071-1079` (неизвестный origin — сам origin, пустой — «[память]»), рендер `:1424-1435` (+ «(архивное убеждение)»); vector/RAG fallback — отдельный маркированный блок «Контекст из памяти (обобщённые факты и пересказ, не дословные сообщения)» (`:907-912`) и НЕ вызываются при author-фильтре (`:858-883`: `not author_ids` в обоих условиях); msg-сниппеты — прямые цитаты без меток | `test_p0_delta_routing.py:723-786` (chat_history→«[пересказ из чата]», derived_belief→«[вывод бота]», unknown→«[weird_source]», archived_belief→маркер, сниппеты без меток пересказа) + `:431-448` (vector/get_rag_context NOT CALLED при author) — зелёные |

## Анти-шаблонный страж владельца §13 — 12/12 PASS

| # | Запрет §13 | Статус | Основание |
|---|---|---|---|
| 1 | Все анализы в одном режиме | **PASS** | Гейт ограничивает ТОЛЬКО доставку готовой story; analysis-ответы пишет Writer своими режимами; матрица §12 даёт ≥4 различных task_kind (`test_p0_delta_routing.py:807-857`) |
| 2 | Любое упоминание прошлого запускает архив | **PASS** | Инструменты вызываются только tool-моделью с явными аргументами; разговорная интерпретация с tool_policy=none остаётся social_chat без исследования (`:859-869`); никакого автотриггера dig в дифе нет |
| 3 | Бот разучился рассуждать | **PASS** | Ни одного нового постпроцессора/запрета рассуждений; NO_META в дереве — только анонсы (`prompt_style_blocks.py:236-252`, решение владельца 26.10 в коде); диф не трогает Style Policy/Expression |
| 4 | Автоматический психологический портрет | **PASS** | Ничего портретного не добавлено; единственные «портретные» строки (`dossier_portrait`, tool_router.py:2219+) — pre-existing, вне дифа |
| 5 | Подробный запрос режется краткостью | **PASS** | Extent-механика не тронута; тест `:120-127` — extent (one_word..exhaustive) НЕ влияет на маршрутизацию гейта; валидаторов длины в дифе нет |
| 6 | Подавлен Lore | **PASS** | Story-интенции доставляются как раньше (`creative/historical_recall/story`); LORE_STORY канон не тронут (lore_prompts.py/lore_compiler_service.py вне дифа; AST-тест `:894-922` — канон только в синтезе истории); kill-switch возвращает прежнее поведение; lore-тесты в прогоне 2 зелёные |
| 7 | Анализ строится на соседних событиях | **PASS** | Стало сложнее строить неправильно: author-фильтр по uid в SQL (чужие сообщения не подмешиваются), счётчик и сниппеты из одного источника фильтров, honest coverage |
| 8 | Чужие сообщения выдаются за субъекта | **PASS** | D4: неоднозначный/ненайденный субъект → честный отказ без поиска; тесты дубликатов имён и отказа (`:576-586`, `:624-671`) |
| 9 | Несколько находок = «многолетнее исследование» | **PASS** | «Показано X из N» + coverage{total,shown} в dig; честные period-метки; «ничего не нашёл»-контракт не тронут |
| 10 | Одинаковая композиция | **PASS** | Ни одного требования композиции в дифе; строки отказа/покрытия — информационные, не шаблон ответа; grep дифа: нет ALWAYS_*/MUST_*/фиксированных структур (пин-тест `:881-892`) |
| 11 | Новый инструмент без необходимости | **PASS** | Ни одного нового tool: dispatch-таблица (`tool_router.py:728`) не расширялась; только аддитивные параметры существующих схем (REQ-DELTA-06-MINIMAL-EXTENSION соблюдён) |
| 12 | Второй маршрутизатор вместо L1 | **PASS** | Единственная точка выбора — существующий L1; новый код — предикат доставки над существующими полями плана, без новых классов/enum (REQ-DELTA-03-NO-NEW-RUNTIME-CLASSES) |

**Структурные запреты (§6/§3, brief):** второй router — нет; новая Decision-Making
слоя — нет; новый агент — нет; своя GraphRAG — нет; новый LLM-пайплайн — нет;
лишние LLM-вызовы — нет (0 новых call-sites в дифе, проверено построчным
разбором добавленных строк); инструкционные квоты/фиксированные числа — нет
(§2.10 ADDENDUM соблюдён; registry CHECK OK, каталог Δ=0).

## Прогоны (реальные выводы, worktree кандидата)

1. `py -3 -m compileall -q services config tests` → **exit 0**.
2. `py -3 -m pytest tests/test_p0_delta_routing.py -q` → **54 passed**, 2.96s.
3. `py -3 -m pytest tests -k "tool_router or delta or routing or memory or lore" -q --ignore=tests/test_p0_vision_ui_e2e.py` → **1427 passed, 14501 deselected**, exit 0, 76s.
4. `py -3 -m pytest tests -k "speech_p0 or direct_l1 or factcheck" -q` → **686 passed, 15249 deselected**, exit 0, 21s (регрессионная кросс-проверка).
5. `py -3 tools\gen_param_registry_round1025.py --check` → **CHECK OK: реестр 582 == REGISTRY**, exit 0 (kill-switch env-only, каталог Δ=0).
6. Полный suite: независимый перезапуск НЕ выполнялся (снято Orchestrator'ом);
   REUSED сравнение Builder'а (`evidence/impl.md`): наборы падений кандидата и
   базы `87ad5908` идентичны (env-флейки миграций/UI-байт-тестов; 1 сетевой
   флейк betterstack проходит standalone; на базе флэйкнули 2 теста, зелёные
   на кандидате). Новых падений от дельты нет.

**Выполнено независимо:** прогоны 1-5, полный диф-аудит, AST/построчная
проверка структурных запретов, интеграционные точки (SQL-подписи MCA-15,
SELECT origin/status, scope l1_plan/response_plan в call-site, обратная
совместимость фасадов для `summary_generator.py` и заглушек тестов).
**Переиспользовано:** полное сравнение suite'ов с базой (п.6), факты аудита.

## Pre-existing наблюдение (вне полосы — передать в P0 DELTA backlog)

`services/response_extent.py:241-249` — легаси-детерминированный
fallback-классификатор (`classify_request`, 0-LLM, путь при отказе L1,
последнее изменение задолго до базы) содержит литералы «проанализируй»,
«почему», «глубокий анализ» в regex extent-классификации. Формально задевает
acceptance REQ-DELTA-02-NO-WORD-HARDCODE («решающая логика»), но: (а) это
pre-existing поведение базы 87ad5908 = deployed 2.58.131, кандидатом не
тронуто и не ухудшено; (б) основной маршрут — L1 Decision Making без
словесного хардкода; (в) новый код кандидата словесных триггеров не добавляет
(`_ME_ALIASES`/`_UID_RE` — конвенции аргументов, документированные в схемах
инструментов). Некритично для этой полосы; решение (carve-out в acceptance
или последующая чистка fallback) — за PM/родительским ревью.

## Честные пробелы (за пределами полосы)

- LIVE-проба 10 реальных сценариев §12 на проде (маршрутизация tool-модели,
  поведение L2 Writer с lore-as-material, разнообразие композиции) —
  DevOps/next step после выката; здесь payload/unit-уровень (как и в
  builder-свидетельствах).
- EN-описание `compile_lore_story` оставлено дословным по ТЗ (байт-пин двумя
  тестами); защиту анализа обеспечивает гейт доставки (аудит G1b —
  опциональный, не выполнен осознанно).

## Binding

Одобрение привязано к точному кандидату `2ac20bf3` (детачед-дерево
`C:\Code\Python\adminbot-wt-delta-review`, HEAD проверен), карте
requirements-map.json в актуальной редакции и прогонам на этом дереве.
Любое изменение кода/схем/настроек инвалидирует свидетельства.
