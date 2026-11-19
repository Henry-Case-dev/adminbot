# VMQ-MEM-07 - независимый harness Reviewer: Stage A (design)

- Роль: Reviewer (независимо от Builder).
- Дата: 2026-11-19.
- Кандидат: 0fce97a14338521a24d94f560e896ebcb19f9492 (production 2.58.219, schema 48).
- Чат: -1002661910336; архив около 2,07 млн сообщений (2022-2026).
- Ветка/каталог: vmq/mem07-independent, plans/features/vmq-onto-01/evidence/mem07/.
- Статус: evidence tooling / design. Продуктовый код, тесты, карты, статусы и
  progress_scope не меняются. Production-прогон не выполнялся и этим документом не
  заявляется. VERIFIED не выставляется.

## 1. Назначение и границы

Цель - дать Reviewer собственный, воспроизводимый способ проверить VMQ-MEM-07:
на реальном архиве прогнать пять классов формулировок, получить собственные
retrieval-трейсы, собственные source refs и собственный расчёт четырёх метрик,
зафиксировать расхождения с матрицей Builder и не опираться на артефакты Builder как
на доказательство.

Документ фиксирует Stage A: набор вопросов, протокол размеченного эталона, определения
метрик и знаменателей, current-state негатив, контрпример и отображение на приёмку.
Stage B добавляет harness, synthetic fixture/smoke, компактный JSON/summary/hashes и
точную команду DevOps.

Не входит в задачу: продуктовые исправления, новый retrieval/store/pipeline, оценка
качества текста LLM, живой Telegram-ход, деплой, изменение карт/статусов, SSH.

## 2. Источники требования

- VMQ-MEM-07 acceptance: Reviewer независимо воспроизводит сравнение пяти классов
  на реальной истории около 2,07 млн сообщений: собственные запросы, собственные
  retrieval-трейсы, собственный подсчёт покрытия, хронологической точности,
  релевантности и выдуманных связей; расхождения с матрицей Builder зафиксированы;
  вердикт не опирается на артефакты Builder как на доказательство.
- VMQ-MEM-01: пять классов на одном историческом наборе, включая точный запрос
  владельца; каждый прогон - отдельная строка матрицы; классы не подменяют друг друга.
- VMQ-MEM-03: четыре величины с зафиксированной методикой и знаменателями,
  воспроизводимые из следа прогонов.
- VMQ-MEM-04: обычный фактический вопрос не хуже творческого рассказа по покрытию,
  хронологии и релевантности и не хуже по числу выдуманных связей; только числа
  матрицы, не впечатление от текста.
- VMQ-TIME-03: события без года (2023/2024) должны давать материал фактического
  периода с проверяемым source ref, без подмены более поздним аналогом.
- VMQ-TIME-07: матрица "до/после": класс, запрос без года, годы по блокам,
  покрытие периодов, релевантность по эталону, непроверяемые ссылки, контрпример;
  раздельно - извлечение из нескольких лет, current-state, причины исключения,
  отсутствие фиксированной доли свежих/архивных фактов.
- VMQ-TIME-08: независимые вопросы без года по людям и событиям; материал
  нескольких разных лет с source ref; current-state негатив; собственный контрпример
  "прежняя позиция уже изменена".

Точный запрос владельца (обязателен как один из humor-вопросов):
напиши юмористический рассказ об основных шизах конфы
(plans/owner_inputs/2026-11-10-vmq-multiyear-memory-regression.md).
## 3. Пять классов: собственный набор вопросов

Все вопросы - Reviewer-owned. Формулировки ниже не копируют девять запросов Builder
(A1/A1P/A2/B/C/D/E/T2/T3); совпадает только обязательный owner-запрос. Для
приватности участники в шаблонах обозначены @P1/@P2; реальное display-name
подставляется только в памяти harness и никогда не пишется в артефакты.

| ID | Класс | Шаблон запроса (ровно) | Эталон: период/годы | Роль |
|---|---|---|---|---|
| H1 | юмористический рассказ | напиши юмористический рассказ об основных шизах конфы | производные годы по "шиз*"; минимум 1 год до 2026 | owner-запрос, обязателен |
| H2 | юмористический рассказ | расскажи смешную историю про ремонт ванной | 2022 | новый humor-вопрос |
| R1 | обычный пересказ | перескажи, что происходило в чате в 2024 году | 2024 | explicit-year retelling |
| R2 | обычный пересказ | напомни, о чём говорили про собаку | 2024 | yearless retelling |
| R3 | обычный пересказ | что известно про основные шизы конфы? | тот же эталон, что H1 | ordinary twin для H1 |
| R4 | обычный пересказ | что было с ремонтом ванной? | тот же эталон, что H2 | ordinary twin для H2 |
| P1 | характеристика участника | что за человек @P1? что о нём известно за всё время? | производные годы по @P1; минимум 2 года, минимум 1 до 2026 | runtime participant A |
| P2 | характеристика участника | какие истории и взгляды связаны с @P2? | производные годы по @P2; минимум 2 года, минимум 1 до 2026 | runtime participant B |
| C1 | конкретный конфликт | из-за чего был конфликт на конфе? | 2023 (если поддержки нет - старейший pre-2026 конфликтный год) | yearless conflict |
| C2 | конкретный конфликт | восстанови, из-за чего ругались в 2024 году | 2024 | explicit-year conflict |
| E1 | изменение отношений/взглядов | как менялось отношение чата к {E1_topic}? | производные годы выбранной темы; минимум 2 года, минимум 1 до 2026 | runtime topic |
| E2 | изменение отношений/взглядов | кто с кем дружил и ссорился за всё время? | производные годы по маркерам отношений; минимум 2 года | fixed relation question |
| N1 | control | что сейчас с ремонтом ванной? | текущий год архива | current-state негатив |
| N2 | control | как сейчас обстоят дела с собакой? | текущий год архива | current-state негатив |
| X1 | control | что сейчас известно про {X1_topic}? | текущий год + старый год | контрпример "позиция изменилась" |

Минимум по классам: humor 2, retelling 4, participant 2, conflict 2, change 2 - всего
12 матричных вопросов. N1, N2, X1 - контроли, не входят в четыре метрики пяти
классов, но обязательны для TIME-03/07/08.

### 3.1 Runtime-слоты (детерминированно, без ручных данных)

- P1, P2: из smart_messages чата выбираются авторы с непустым author_name,
  user_id > 0, не входящие в Builder-набор 485008070, 138811255, 1313107079;
  требуется минимум 50 сообщений в 2022-2025, минимум 3 различных года и минимум
  5 confirmed facts с target_user/speaker_author_id или упоминанием имени. Кандидаты
  сортируются по sha256(seed + ":participant:" + user_id); берутся первые два разных
  автора. Display-name - самое частое author_name этого user_id в чате; в артефакт
  идут только @P1/@P2, user_id_sha256, name_sha256, годы. Если второго кандидата
  нет, P2 получает not_executed: participant_support_insufficient.
- E1_topic: первый кандидат из списка, у которого есть поддержка минимум в двух
  различных годах (минимум 3 facts или 20 messages на год) и хотя бы один год до 2026:
  1. работе и зарплатам (работ*, зарплат*, деньг*);
  2. органной музыке (орган*, музык*, концерт*);
  3. шаурме (шаурм*);
  4. витаминам (витамин*);
  5. вайпу сервера (вайп*, сервер*);
  6. концертам (концерт*, билет*).
  Если ни один не подходит - E1 = not_executed: topic_support_insufficient.
- X1_topic: сначала ищется реальная пара "старый confirmed fact + более поздний
  confirmed fact" по общей теме, где поздний текст содержит маркер изменения
  (уже не, больше не, перестал, сейчас, передумал, изменил); тема - общий
  содержательный термин (не имя). Если пары нет - fallback "вайп сервера"
  (событие 2024, текущее состояние изменилось), с пометкой
  counterexample_pair=fallback_event_completed.
## 4. Размеченный эталон (label protocol)

Эталон строится из самого снимка детерминированными SQL-предикатами; ids не
захардкожены. Никакой текст сообщений/фактов не попадает в выходные артефакты.

### 4.1 Единица эталона

reference_anchor - одна из двух записей:

- message: smart_messages.id, timestamp, tg_message_id, user_id;
- fact: graph_facts.id, COALESCE(message_timestamp, created_at), tg_message_id,
  status, kind, origin.

Каждый anchor обязан иметь source ref в том же чате: message - собственный id/
tg_message_id; fact - tg_message_id, указывающий на smart_messages того же чата.
Fact без tg_message_id допускается как fact:<id>-источник, но помечается
derived_no_tg и не считается подтверждённым сообщением.

### 4.2 Предикаты отбора

Для topic-вопросов используется FTS5 MATCH по префиксам (тот же токенизатор
unicode61, что у хранилища), затем SQL-фильтр по чату и году:

- H1/R3: "шиз"*; годы - все годы с поддержкой минимум 10 messages или 3 facts,
  обязателен минимум 1 год до 2026.
- H2/R4: "ремонт"* AND "ванн"*; год 2022.
- R1: без topic-предиката; все сообщения/факты 2024 года.
- R2: "собак"*; год 2024.
- P1/P2: facts с target_user = name ИЛИ speaker_author_id = uid ИЛИ FTS по name;
  messages автора (user_id = uid) и сообщения с упоминанием name; годы - все годы
  с поддержкой минимум 3 facts или 20 messages, обязательны минимум 2 года и
  минимум 1 до 2026.
- C1: ("ссор"* OR "ругал"* OR "конфликт"* OR "спор"*) AND "конф"*; сначала 2023;
  если 2023 пуст - старейший pre-2026 год с поддержкой.
- C2: ("ссор"* OR "ругал"* OR "конфликт"* OR "спор"*); год 2024.
- E1: terms выбранной темы; годы с поддержкой минимум 3 facts или 20 messages,
  обязательны минимум 2 года и минимум 1 до 2026.
- E2: ("друж"* OR "отношен"* OR "ссор"* OR "ругал"* OR "спор"* OR "люб"*);
  годы с поддержкой минимум 3 facts или 30 messages, минимум 2 года.
- N1: ("ремонт"* AND "ванн"*); текущий год; старые строки - отдельный негатив.
- N2: "собак"*; текущий год.
- X1: тема найденной пары/fallback; старый и текущий годы.

fact-предикаты: chat_id = :chat, status = 'confirmed', kind = 'fact',
origin NOT IN ('bot_direct_reply','bot_self_reply'), expires_at IS NULL OR
expires_at > as_of. message-предикаты: chat_id = :chat, timestamp в границах
года (UTC). Для current-state контролей archived/expired fact не становится
"текущим"; он может попасть в эталон только как старый anchor с отдельной пометкой.

### 4.3 Детерминированный выбор и капы

- На каждый год: до 16 fact anchors и до 16 message anchors.
- Кандидаты ограничены 200 на год; порядок - sha256(seed:kind:id), где
  seed = sha256(candidate_sha + ":" + chat_id + ":" + reference_key).
- reference_sha256 считается по компактному списку {kind,id,year,ref}; он
  позволяет проверить, что повторный прогон на том же снимке дал тот же эталон.
- Если для обязательного года anchors нет - вопрос получает
  not_executed: reference_empty:<year>, метрики не подставляются.
- Если поддержка ниже минимума - not_executed: reference_support_low:<year>;
  никакого "добора" из других лет нет.
- Год считается по UTC; current_year = год максимального timestamp чата в снимке,
  не системные часы.

### 4.4 Псевдонимы и отсутствие личного текста

- Участники: только @P1/@P2; display-name существует только в памяти harness;
  в JSON/summary/hashes - user_id_sha256, name_sha256, годы, counts.
- Вопросы: в артефакт пишется query_template (с @P1/@P2/{E1_topic}) и
  query_sha256 фактически подставленного запроса; resolved-текст с именем не
  сохраняется.
- В артефакт не пишутся smart_messages.text, graph_facts.fact, имена, цитаты,
  заголовки эпизодов. Разрешены: ids, годы, timestamps, counts, origin/status/kind,
  topic-label (не персональный), sha256, коды причин.
- Fixture содержит sentinel-маркеры; smoke-тест проверяет, что они не появились ни в
  одном выходном файле.
## 5. Метрики: определения и знаменатели

Для каждого вопроса q:

- D_q - доставленные элементы Writer-payload basis: строки <RAG_Memory>,
  source-rows <Old_Episode> и refs bundle, дедуплицированные по каноническому
  ref (fact:<id>, tg:<id>, msg:<id>, row:<id>). Один элемент может нести
  несколько refs; для coverage используется пересечение множеств.
- R_q - anchors эталона; Y_q - ожидаемые годы (|Y_q| - знаменатель периодов).
- year(x) - UTC-год rag_ts/message_timestamp доставленного элемента.

### 5.1 Покрытие (coverage)

- period_coverage_q = |Y_q пересечение years(D_q)| / |Y_q|.
- anchor_coverage_q = |anchors r in R_q, у которых refs(r) пересекает refs(D_q)| /
  |R_q|.
- class_coverage = сумма anchor_hits / сумма |R_q| (pooled); рядом - mean
  period_coverage.
- Первичная для topic/question-классов - anchor_coverage; period_coverage
  показывает, дошли ли периоды вообще. Для R1 (широкий retelling 2024) первична
  period_coverage, anchor_coverage - справочная.
- Знаменатели: число ожидаемых лет и число anchors; оба печатаются явно.

### 5.2 Хронологическая точность (chronological accuracy)

- matched_q - доставленные элементы, совпавшие хотя бы с одним anchor r.
- year_ok_q - элементы из matched_q, у которых year(d) = year(r).
- chrono_accuracy_q = year_ok_q / |matched_q|; если matched_q = 0 -
  not_applicable, а не 0 и не 1.
- Диагностика: year_sequence доставленных expected-годов в порядке payload;
  order_ok = (sequence == sorted(sequence)) - не подменяет основную метрику.
- class_chrono = сумма year_ok / сумма |matched|.

### 5.3 Релевантность (relevance)

- judged_q = |D_q| (все доставленные элементы, у которых есть текст для
  предиката; элементы без текста считаются judged с relevant=0 и отдельным
  счётчиком no_text).
- relevant_q - элементы, одновременно:
  (а) имеют resolvable same-chat source ref;
  (б) проходят relevance_predicate вопроса:
  - topic-вопросы - наличие профильного стема (шиз, ремонт/ванн, собак,
    ссор/ругал/конфликт/спор, тема E1, друж/отношен/ссор/ругал/спор/люб);
  - P1/P2 - упоминание name, user_id/speaker_author_id = uid, или target_user
    содержит name;
  - R1 - год 2024 (вопрос именно о 2024; 2026-строка нерелевантна периоду).
- relevance_precision_q = |relevant_q| / judged_q; знаменатель - все доставленные
  элементы, включая нерелевантные.
- class_relevance = сумма relevant / сумма judged.

### 5.4 Выдуманные связи (fabricated links)

- claims_q - различные link-bearing refs в payload и bundle evidence:
  fact:<id>, tg:<id>, msg:<id>, row:<id>; плюс relation-строки, если у них
  есть ref. Дедупликация по ref.
- unresolved_q - ref не разрешается в строку того же чата:
  fact: -> graph_facts.id + chat; tg:/msg:/row: -> smart_messages того же
  чата по id/tg_message_id/message_id.
- weak_q - fact-ref существует, но status != 'confirmed' или нет
  tg_message_id (источник есть, но подтверждение слабое); считается отдельно.
- fabricated_rate_q = |unresolved_q| / |claims_q|; абсолютное число unresolved
  печатается. weak_rate - отдельно; weak не приравнивается к fabricated.
- class_fabricated = сумма unresolved / сумма claims; если claims=0 -
  not_applicable.
- Ограничение: LLM-текст не генерируется, поэтому метрика измеряет целостность
  ссылок payload/bundle, а не словесные утверждения модели. Это явно фиксируется.

### 5.5 Паритет (MEM-04)

Пары на одних и тех же anchors:

- (H1, R3) - owner-запрос против обычного факта о тех же "шизах";
- (H2, R4) - humor про ремонт против обычного вопроса о ремонте.

Для каждой пары: period_coverage, anchor_coverage, chrono_accuracy,
relevance_precision, fabricated_rate. parity_pass для пары - ordinary не ниже
humor по coverage/chrono/relevance и не выше по fabricated rate; при
not_applicable/нулевом знаменателе - unverified, а не pass. Итог: pass только
если обе пары pass; иначе fail/unverified с точной причиной.

### 5.6 Агрегация и след

- Пер-question значения + pooled по классу; pooled считается по суммам числителей и
  знаменателей, не средним из отношений.
- В JSON для каждой метрики хранятся num, den, value, applicable, reason.
- Любое значение воспроизводимо из questions[*].policies[*] (ids/years/refs) без
  повторного чтения текста.
## 6. Current-state негатив и контрпример

### 6.1 Негатив N1/N2

Вопросы о текущем состоянии (N1, N2) прогоняются тем же payload-путём. Проверка:

- old_rows - доставленные элементы с year < current_year.
- Для каждой старой строки в <RAG_Memory> проверяется наличие временной метки:
  (архив, YYYY) (продуктовая пометка _mark_rag_fact) или явный год/дата в
  заголовке строки.
- unlabeled_old - старые строки без любой временной метки; negative_pass =
  (unlabeled_old == 0).
- Отдельно old_archive_marked, old_date_labeled, current_rows, old_rows.
- Если old_rows = 0, негатив pass тривиально, но в summary это помечается
  no_old_rows (не выдаётся за сильное доказательство).
- Проверяется также, что old fact с valid_now=0 не подан как действующий: продукт
  обязан поставить (архив, YYYY). Если пометки нет, но в заголовке строки есть явный
  год/дата, это честная временная метка и negative_pass сохраняется; отдельно
  считается missing_archive_marker как диагностика механизма актуальности. Fail -
  только при полном отсутствии любой временной метки у старой строки.

### 6.2 Контрпример X1

Два слоя:

1. Runtime-пара "старая позиция -> изменение": старый confirmed fact и более поздний
   confirmed fact по общей теме с маркером изменения. Вопрос "что сейчас с
   {X1_topic}?"; проверяется: старый факт либо отсутствует, либо имеет
   (архив, YYYY)/явный год; поздний факт присутствует, если он есть в архиве.
2. Fallback "вайп сервера" (2024): вопрос о текущем состоянии; старый факт 2024 не
   должен быть подан как действующий.
   X1 получает counterexample_pair=runtime_changed_position или
   fallback_event_completed; при отсутствии пары и fallback-поддержки -
   not_executed (честно), а не выдуманный кейс.

## 7. Политики прогона и матрица TIME-07

Для каждого вопроса:

- auto - штатный путь _build_rag_block/_rag_unified_rows с memory_scope='auto',
  без плана (базовое поведение хода до L1).
- auto_plan - тот же запрос и путь с plan_act='historical_recall' (структурный
  сигнал, не словарь): проверяет, меняет ли сигнал охват.
- historical - только для H1, R3, P1 как policy-reference; не является
  основным сравнением пяти классов.

TIME-07 матрица в harness - within-candidate A/B: auto (до сигнала) против
auto_plan (после сигнала) на одном снимке и одном кандидате. Колонки: класс,
запрос, годы каждого блока (RAG, Old_Episode, payload), покрытие, хронология,
релевантность, unresolved refs, контрпример. Сравнение с baseline 2.58.179 не
заявляется: для него нужен отдельный снимок того поколения; Builder-числа - только
контекст, не доказательство.

## 8. Отображение на приёмку

| Строка | Что даёт harness | Где в выводе |
|---|---|---|
| VMQ-MEM-01 | 12 матричных вопросов, минимум 2 на класс, точный owner-запрос H1, отдельная строка на прогон | questions[], classes |
| VMQ-MEM-03 | coverage/chrono/relevance/fabricated с num/den/value на вопрос и класс | questions[].metrics, classes |
| VMQ-MEM-04 | пары (H1,R3), (H2,R4) и числовой parity | parity |
| VMQ-MEM-07 | собственные вопросы/трейсы/расчёт; differences и builder_artifacts_used_as_proof=false | meta, differences |
| VMQ-TIME-03 | yearless events/person: H1/H2/R2/C1/P1/P2/E1/E2, годы 2023/2024 и source refs | time03 |
| VMQ-TIME-07 | within-candidate auto vs auto_plan, годы по блокам, coverage/relevance/refs, controls | time07 |
| VMQ-TIME-08 | yearless people/events + N1/N2 + X1, source refs | time08, controls |
## 9. Расхождения с матрицей Builder (фиксируются заранее)

Builder-матрица (formulation-class-matrix.json, 2026-11-15, 2.58.203, 2 075 621
сообщение) используется только как контекст; её значения не являются доказательством
для этого прогона. Отличия:

- вопросы: у Builder A1 (owner), A1P, A2, B, C, D, E, T2, T3; здесь
  H1/H2/R1..R4/P1/P2/C1/C2/E1/E2 - другие формулировки и/или другие темы/участники;
  совпадает только обязательный owner-запрос.
- эталон: у Builder coverage по годам поддержки темы; здесь - anchors (message/fact)
  с same-chat source ref, детерминированным хешем и reference_sha256.
- метрики: у Builder relevance - предикат по строкам без anchor-уровня; здесь
  relevance требует resolvable source ref, отдельно считаются unresolved и weak
  refs; chrono - year-match по matched anchors, а не только порядок лет.
- данные/поколение: Builder 2.58.203/c97c06e; здесь 2.58.219/0fce97a14; числа
  не переносятся, сравнение - только после реального прогона.
- controls: у Builder T3 - один current-state вопрос; здесь N1/N2 + X1
  (включая "позиция изменилась"), отдельно от пяти классов.

## 10. Stage B: harness и артефакты (план)

- harness/mem07.py - read-only harness: snapshot meta/hash, product
  _rag_unified_rows -> _build_rag_block -> _build_old_episodes ->
  payload_builder.build_messages, reference builder, metrics, controls, outputs.
- harness/make_fixture.py - synthetic SQLite fixture (product schema) для smoke.
- harness/measure_effective_config.py - read-only settings/PG hot-config probe
  used by the reissue.
- harness/test_mem07_smoke.py - pytest: fixture, schema, no-text, four metrics,
  controls, missing-snapshot not_executed.
- README.md - exact DevOps command, snapshot recipe, outputs, smoke, exit codes,
  limitations.
- Выходы: mem07-independent.json, mem07-independent-summary.md,
  mem07-independent-hashes.txt; fixture-выходы - отдельно, с пометкой
  fixture: never production evidence.

Exit codes: 0 - структурные assertions pass; 1 - fail; 2 - not_executed;
3 - read-only violation; 4 - technical failure. Метрики качества продукта не
превращаются в assertions harness: harness доказывает воспроизводимость измерения,
а приёмку оценивает Reviewer после прогона.

## 11. Ограничения и честные non-claims

- LLM/embedding - failing stubs; текст ответа не генерируется; метрика fabricated
  измеряет ссылки payload/bundle, не словесные утверждения.
- Векторная нога при stub embed недоступна (compat_not_proven); прогон проверяет
  лексический/структурный путь и фиксирует vector_leg, не выдаёт его за semantic
  retrieval.
- _compose_user_content/полный ход L1 не вызываются: harness использует
  продуктовые блок-билдеры (_build_rag_block, _build_old_episodes) и канонический
  build_messages; system prompt и plan-контекст не являются предметом измерения.
- Snapshot - копия, не живой процесс; живой L1/Telegram-путь не наблюдаются.
- Один чат, один прогон на конфиг; статистического обобщения нет.
- Кросс-релизный baseline 2.58.179 не переснимается; TIME-07 - within-candidate A/B.
- Все ids/годы/refs - из снимка; при несовпадении schema/quick_check прогон
  not_executed, а не "частично доказан".
## 12. Stage C: reissue corrections (2026-11-19)

Run-0 is invalid for acceptance: it leaked one personal display-name in the X1
subject, its config section reported fallback values, its 100 traceback lines
were deleted, and its exact-anchor metric was non-discriminatory. The following
corrections are mandatory for the reissue.

### 12.1 Effective configuration

- Import the actual settings instance: `from config.settings import settings`.
- Record and assert `graph_rag_enabled=true` and `graph_rag_facts_limit>0`.
- Preferred: run from the production env without `--effective-config`; the
  harness records `settings_instance`, a SELECT-only `bot_settings` read
  (`db_hot_config`), per-key sources, `pg_status`, `hot_config_measured`, and the
  computed `effective` values.
- Alternative: `--effective-config` must be a provenance file generated by
  `measure_effective_config.py` from the production environment, never a
  hand-written true/10 file. It carries schema, tool sha256, command, settings
  instance, DB hot values, sources, effective values and read-only flag; the
  harness records its sha256.
- Fail closed with `not_executed: graph_rag_disabled` if the measured effective
  values are false/zero; fail with
  `effective_config_provenance_*` if provenance is missing, hand-written,
  settings-only for a real run, or PG hot config is not production-ready.
  Never report fallback defaults as config.

### 12.2 Unified path

- Record `retrieval_path=unified` only when `_rag_unified_rows` returned non-None
  and the period policy is present.
- `MEM07-CONFIG` and `MEM07-TRACE` fail if the legacy fallback is used.

### 12.3 Privacy

- X1 uses only the fixed neutral fallback `вайп сервера`; no fact-text token is
  extracted. This supersedes the runtime-pair wording in section 6.2.
- `MEM07-PRIVACY` scans the output for known display names (top author names and
  user entity names) and fails on any hit; names are never written to output.
- E1 topics and participant query templates remain non-personal; participants are
  `@P1`/`@P2` with hashes only.

### 12.4 Diagnostics

- A logging handler records a text-free histogram: records/lines, levels,
  categories (readonly_write, embed_stub, llm_stub, rerank_stub, error_other,
  other), exception types, unexpected errors/tracebacks, and a `log_sha256`.
- `MEM07-DIAGNOSTICS` fails on any unexpected error/traceback or missing hash.
- The raw log may be deleted by DevOps only after the histogram/hash is in the
  artifact.

### 12.5 Metrics

- Keep exact-anchor coverage and exact chrono.
- Add `semantic.coverage` (expected years with a resolved, predicate-matching
  row / expected years), `semantic.old_coverage` (old expected years covered /
  old expected years), and `chrono_period` (resolved rows in target years /
  resolved rows). Target years are the explicit year, the current year for
  controls, or the old expected years for yearless/change questions.
- These metrics have explicit denominators and are pooled per class and used in
  parity. Exact-anchor coverage remains; it is no longer the only coverage proof.

### 12.6 Old_Episode and controls

- Add explicit `Old_Episode_2023` and `Old_Episode_2024` probes (query with the
  explicit year); record empty/messages/spans/source ids/resolved sources/years.
- `MEM07-OLDEP-*` fails if empty, has no spans/resolved sources, or years leak
  outside the target year.
- N1/N2 historical policies must have `old_rows>0` and no unlabeled old row;
  `no_old_rows` is a failure, not a trivial pass.
- X1 historical must deliver both old and new facts and label the old one; absent
  either is a failure, not a pass.

### 12.7 Builder discrepancy table

- The run JSON/summary contains a numeric `builder_comparison` table: Builder
  class/source/years/coverage/relevance versus our auto/plan years, semantic old
  coverage, relevance and fabricated values, with denominators.
- Builder values are context only; `builder_artifacts_used_as_proof=false`.

### 12.8 Reissue inputs

- Run-0 snapshot `c1d45bda...` was deleted; the reissue uses a fresh snapshot of
  the same product generation `0fce97a14`, records the new sha256 and states the
  difference. It is not the same snapshot and must not be described as such.
- Run-0 artifacts remain invalid for acceptance and are not used by the reissue.