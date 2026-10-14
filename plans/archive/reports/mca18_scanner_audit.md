# Scanner-аудит — `mca-18-self-model` (T-5093, 06.10.2026)

## Вердикт: **к деплою НЕТ** (1 блокер High; исправим точечно в одном rework-цикле)

**Сводка: Critical 0 / High 1 / Medium 1 / Low 2 / Info 4.**

- Binding: HEAD `23cb2a1c9244ed1203c662ef61a90c66d811a134`, кандидат — незакоммиченный working tree. Хеш-контроль против review итер.2: `services/mca_self_model.py` = `49e4125d…`, `web/api/routes.py` = `72c22193…` — совпали, кандидат тот же, что ревьюен.
- Мой прогон: focused mca-18 (6 файлов) — **93 passed** (сходится с T-5092). R17-скан диффа поверх `23cb2a1`: секретов/токенов/ключей нет (совпадения — только прозаические упоминания имени `RANDOM_QUANTUM_API_KEY` в планах, без значений).

## S-1 — **High, BLOCKING**: chat-bound applicability не enforced на read-side — черта из одного чата действует во всех чатах

- **Механизм.** `promote_observation` создаёт chat-правило с `scope='chat'`, `applicability=["chat:<id>"]` (`services/mca_self_model.py:1264–1268`). На чтении этот биндинг никем не сопоставляется со `scope_chat_id`: `list_behavior_rules` без фильтра scope (`services/database.py:3699–3717`), `_compile_trait_view` считает любое непустое applicability включённым (`mca_self_model.py:597–622`), `select_behavior` проверяет только included/foreign/scoped-shadow и НЕ матчит applicability/scope с чатом запуска (`mca_self_model.py:1592–1624`).
- **Репро (моё, offline SQLite):** active-правило `scope='chat', applicability=["chat:111"]` → `resolve_self_model(db, 222)` → `select_behavior` → applied в чате 222, инструкция «резче обычного» присутствует в `<Persona>`-блоке. Воспроизводится 1-в-1.
- **Нарушенные требования:** spec §6/R6 (`spec.md:107`), ADR-1028-18 D8, §28.4 `:1584` — «глобальное ядро сохраняется; **отношения/локальные реакции — локальны**; chat→global — **явное** правило»; собственный контракт `promote_observation` («chat-правило», `mca_self_model.py:1260–1263`). Фактически chat→global происходит молча и автоматически.
- **Impact:** расширение blast radius T-1/T-5 за санкционированный контур — динамика одного чата меняет поведение бота во всех чатах без явного акта владельца; UI показывает бейдж `scope: chat` (web/index.html), вводя владельца в заблуждение. Усиление T-1: манипулятивная кампания в одном чате сдвигает глобальное `target_value` (оно и так глобальное — санкционировано), но теперь и **инструкция применяется глобально**, что требованием не покрыто.
- **Смягчающий факт (не снимает блокер):** deep sleep по умолчанию OFF (`DEEP_SLEEP_ENABLED=False`), сегодня наблюдения создают в основном ручные/legacy-черты; но механизм деплоится целиком, и при включении сна дефект активен немедленно.
- **Исправление (малое):** в `select_behavior` (или в `_compile_trait_view` при resolve) исключать из applied правила с chat-binding другого чата (`applicability` содержит `chat:X`, X ≠ scope_chat_id, либо `scope='chat'` без совпадения чата) — с честным `rejected_rules`-reason (например `out_of_scope_chat`); global-правила не трогать. Обязателен контракт-тест «chat:111-правило не применяется в чате 222» (сейчас RED) + мой репро.
- **Recheck после фикса:** репро выше + focused mca-18 suite + `test_mca18_contract_round1042.py`.

## S-2 — Medium, non-blocking: кап «≤0.2/24 ч» не enforcement (нет 24ч-окна)

`trait_max_step_24h` используется только как `min()` за один вызов (`mca_self_model.py:1483–1491`); скользящего суточного окна нет. Дедуп ловит только **тот же** набор refs (`event_dedup_hash`, один слот, `:1467`). Следствие: глобальное правило dimension может расти на 0.1 за каждый цикл сна **каждого** чата (cooldown deep sleep 20 ч, `dream_worker.py:164,1837`; refs разных чатов различны → дедуп не срабатывает) — до ~0.1×N/сутки против заявленных «≤0.2/24 ч» (threat T-1 п.3, evidence T-5082). Задокументированный резидуал T-1 фактически занижен.
**Disposition (non-blocking):** per-call кап 0.1 стоит, ослабление/пауза/отзыв владельцем доступны, «Аналитика» показывает версии. В backlog: реализовать 24ч-окно в `reinforce_rule` (или суточный счётчик на правило) ИЛИ честно скорректировать формулировки threat/spec на «≤0.1/цикл, цикл ≥20ч/чат». Не блокирует деплой.

## S-3 — Low: нет UNIQUE(agent_id, dimension) в DDL — гонка может создать дубликаты правил

`mca_behavior_rules` без UNIQUE-констрейнта (`database.py:1418–1445`); `_upsert_rule_candidate` делает SELECT→INSERT без уникальности (`mca_self_model.py:1297–1335`) — параллельные прогоны сна разных чатов могут создать 2 active-правила одного dimension (дубли инструкции в кадре, двойной рост версий); `find_rule_id` с `LIMIT 1` без ORDER BY (`:1121–1127`) выбирает произвольно. Bounded impact, ad-hoc консьюмер-семантика «UNIQUE по естественному ключу» (`:1286–1289`) не гарантируется СУБД. Backlog: UNIQUE-индекс + `ON CONFLICT`.

## S-4 — Low: Block B (атрибуция/запреты) — библиотека без прод-вызовов

`attribute_memory` / `store_typed_memory` / `check_typed_write` прод-кодом не вызываются (grep: только tests). Реальные поставщики хардкодят субъект: dream-хук — `subject_status="self"` всегда (`dream_worker.py:2519`), legacy-разбор — `manual→self`, иначе `ambiguous` (`mca_self_model.py:1819`). Сегодня безопасно (прямого писателя наблюдений от сообщений участников нет — T-1 закрыт архитектурно), но 8 guard-функций таблицы запретов сейчас dead code: будущий писатель может их миновать. Backlog: wiring через `store_typed_memory` или честная пометка в evidence, что guards — контракт для будущих писателей.

## Info

- **I-1.** K1 OFF + K2 ON: dream-хук (`dream_worker.py:2509` — проверяет только K2) и legacy-parse (K3) продолжают писать v31 — «мастер OFF = бит-в-бит 2.58.61» верен для промпт-пути/поведения (legacy-рид идёт из PG `persona_traits`), но формулировка в `mca_gates.py:1264` («v31 не читается/не пишется») шире фактической семантики per-axis. Поведенческого эффекта нет.
- **I-2.** Позиции/настроение рендерят сырой текст факта в системный промпт (`mca_self_model.py:1713–1717`), но прод-писателей нет: `record_adoption_link` вызывается только тестами, mood-writer отсутствует (известный disposition M-2). При появлении писателей — ревизия GEN-R18-границы (positions сейчас — единственный канал raw-памяти в промпт).
- **I-3.** Подтверждены review-находки L-1/L-2 в текущем состоянии (не исправлялись — по disposition T-5092 это норма): identity_binding='runtime' и при совпадении, и при расхождении (`mca_self_model.py:450–456`); `cols` в `_migrate_self_model_v31` определён только под guard'ом graph_facts, index-loop использует его безусловно (`database.py`, блок `_SELF_MODEL_FACT_INDEX_DDL`) — NameError-угол при отсутствии graph_facts (практически недостижим, миграция под backup-guard).
- **I-4.** Sources/self-model endpoints отдают метаданные любых rule_id (глобальные объекты) пользователю с view-правом на свой чат — только ID/dimension/статусы/refs/preview_len, без контента; ограничения доступа к правке — `_persona_can_edit` корректен. Приемлемо; отмечено для mca-17c-матрицы.

## Что проверено по чек-листу (сводка)

1. **Инъекция черт:** сырые тексты наблюдений в промпт не попадают — инструкции только из фиксированного канона `DIMENSION_INSTRUCTIONS` (`select_behavior` отклоняет unmapped с причиной), рендер — структурированный кадр; subject-гарды на записи (unmapped/foreign/subject≠self/source-missing → отказ с причиной, `promote_observation:1211–1248`). НО: см. S-1 (scope-контур) и S-4 (гарды без прод-вызовов).
2. **Самоусиление:** дедуп по исходным событиям, own-output-under-trait через mca-22 ledger (`_rule_sources_independent` + `_mca18_ledger_source` в единственной persona-точке ledger-записи `direct_chat_service.py:2875`; initiative-путь кадра не получает — тег не нужен), ослабление без капа, шаг ≤0.1/вызов. НО: 24ч-окна нет — S-2; single-slot dedup-hash и coarse refs (все self-факты периода) ослабляют точность дедупа — в пределах капа.
3. **R17/маскирование:** события — ID/коды/enum/числа (все `emit_mca_event` mca-18 проверены); `GET …/sources` — `preview_len`, refs, статусы, без сырых текстов (M-1-фикс подтверждён: только `source_observation_ids` правила, `routes.py:2388–2408`); UI — без сырцов/секретов; ошибки логируют только типы исключений.
4. **Секреты:** дифф чист (см. выше); фикстуры/тесты без токенов.
5. **Fail-режимы:** ошибка чтения → `SelfModelSnapshotError`+событие; PG-ошибка is_aware_ai → LKG со stale-маркером (TTL 600с, 0=запрет LKG) либо минимальная идентичность, `fallback` никогда не репортится как success — тесты + код (`mca_self_model.py:539–570`); K1 OFF — бит-в-бит промпт-пути (репро Reviewer итер.1/2 переиспользовано + тест). См. I-1 (формулировка).
6. **DDL v31:** идемпотентна (table/column guards, seed ON CONFLICT DO NOTHING, повтор no-op — тесты Block A), PG no-op (pg_db.py не изменён — git status), backup-guard — стандартный migration-runner. Угол L-2 — I-3.
7. **Threat-failure-analysis:** T-1 — закрыт частично: субъект-гарды/канон-инструкции да, но кап-п.3 нарушен (S-2) и chat-контур не enforced (S-1). T-5 — атрибуция корректна как библиотека, прод-пути хардкодят субъект безопасно (S-4). T-2/T-3/T-4/T-6/T-7/T-8/T-9/T-10 — выборочно перепроверены по коду: подтверждены (T-3 с оговоркой S-2; T-10 с оговоркой I-1). Дублировать закрытые H-1/H-2/H-3 не требуется — фикс подтверждён хешами и тестами.

## Disposition

- **S-1 — блокер деплоя.** Точечный rework: read-side scope/applicability-матч + RED→GREEN контракт-тест + мой репро. Полный перезапуск ревью не нужен — пересмотр только `select_behavior`/`_compile_trait_view`/тестов (blast radius ограничен этим контуром).
- S-2 — backlog с disposition (окно 24ч или правка документации); S-3/S-4 — backlog; I-1…I-4 — фиксация, действий не требуют.
- Live-приёмка T-5095 остаётся PENDING OWNER (post-deploy); paired-replay 30×≥3 — после S-1/S-2-решений, на санкции владельца.

R17: в отчёте секретов и сырого чат-контекста нет.
## Recheck S-1 — 06.10.2026 (после S-1-rework Builder'а; точечный, полный аудит не повторялся)

**Кандидат:** `services/mca_self_model.py` SHA256 = `106a8f69…f1ddf2` — совпал с handoff Builder'а (в итер.1 был `49e4125d…`). HEAD `23cb2a1`, кандидат — working tree.

**Что перепроверено (S-1):**
- Rework-зона по коду: `_scope_mismatch_reason` (`mca_self_model.py:1578–1604`) + проверка в цикле `select_behavior` после included-гарда (`:1631–1640`) + docstring'и (`:1580–1586`, `:1616–1618`). Токены `chat:<id>` действуют только при `int(scope_chat_id) in bindings`; чужой чат, глобальный запуск (`scope_chat_id=None`) и нечитаемый биндинг (`chat:abc`) → `out_of_scope_chat` (fail-closed); правила без chat-биндинга не задеты. Продюсер (`promote_observation:1268`, `f"chat:{int(chat_id)}"`) и ридер согласованы по формату токена.
- `_compile_trait_view` (`:597–622`) и `list_behavior_rules` (`database.py:3699–3717`) без scope-логики — не тронуты, как заявлено; кадр остаётся единственными воротами в `<Persona>` (единственный прод-рендер mca-18-пути — `bot_persona.py:275` из кадра; оба прод-вызова `select_behavior` — `bot_persona.py:457/465`).
- Независимое репро (мой скрипт, offline SQLite, вне репо, 1-в-1 сценарий итер.1): promote chat:111-правила (в БД подтверждены `scope='chat'`, `applicability=["chat:111"]`) → `resolve_self_model(222)` → правило НЕ в applied, причина `out_of_scope_chat` видима в `rejected_rules`, канонической инструкции «резкость» нет в `<Persona>`-блоке, global-правило-контроль применено; глобальный запуск — отвергнуто с той же причиной; свой чат 111 — применено и в `<Persona>`; нечитаемый биндинг — fail-closed, applied пуст. 7/7 проверок зелёные.
- Локальность изменений: строка `out_of_scope_chat` встречается только в `mca_self_model.py` (заявленная зона) и новом тесте — в другие файлы изменение не растеклось. Буквальный `git diff` против итер.1 невозможен (файл untracked, итер.1 не коммичен) — не-регрессия установлена хеш-совпадением кандидата с handoff, локальностью строки и статической проверкой H-зон (ниже).

**Не-регрессия (H-1/H-2/H-3):**
- H-1: `render_frame_block` — `aware = frame.is_aware_ai if is_aware_ai is None else bool(is_aware_ai)` (`:1745`), финальная проверка `if not aware:` (`:1774`) — фикс на месте; контракт-тест в прогоне.
- H-2: dream-хук (`dream_worker.py:2501–2537`, пары «text, dimension») на месте; слайс `test_dream_persona_traits.py` — 16 passed.
- H-3: `tools/mca18_paired_replay.py:213` `for _gen in range(generations)` на месте; scaling-тест в прогоне.

**Мои прогоны:** `tests/test_mca18_s1_scope_round1042.py` — 3 passed; focused mca-18 (7 файлов, вкл. H-1-контракт `test_contract_false_block_uses_effective_awareness` и H-3 `test_run_replay_generations_scale_and_spread`) — **96 passed** (93 + 3 новых; сходится с claim'ом Builder'а); dream-слайс — 16 passed.

**Инциденты Builder'а (подтверждены, не блокеры):**
- Seed `agent_id` — случайный `uuid4` при инициализации (`database.py:3492`, ON CONFLICT DO NOTHING): тесты обязаны пинить его (s1-фикстура так и делает). Info → backlog (детерминированный тестовый seed желателен, не обязателен).
- UI: `active_rules[].included` строится из snapshot-черт (`routes.py:2255–2260`) и для чужого chat-правила = true (warn-badge рисуется только при `!included`, `web/index.html:5803–5806`), при этом тот же payload честно содержит `rejected_now[].reason="out_of_scope_chat"` из кадра (`routes.py:2265–2267`). Косметическое расхождение «список/кадр»; web/ вне scope rework'а → backlog (отражать scope-отклонения кадра в списке правил).
- Попутное наблюдение речека (Info): `_scope_mismatch_reason` матчит префикс `chat:` case-sensitively — гипотетический токен `Chat:111` был бы проигнорирован (правило считалось бы global). Прод-путь такой токен создать не может (promote пишет lowercase), ручная правка БД — явный акт владельца. Backlog-заметка, не блокер.

S-2 (Medium) и S-3/S-4/Low — без изменений, в backlog, как в итер.1; в этот recheck не входят.

Вердикт: **к деплою ДА** (Critical 0 / High 0)
