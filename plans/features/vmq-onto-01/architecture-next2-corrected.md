# Скорректированный контракт VMQ-NEXT-02 после причинного разложения

Дата: 13.11.2026. Основание: committed `evidence/vmq-mem/next-stage/next2-cause-decomposition-23477658.md/.json` и прежний `architecture-next2-cause.md`. Только архитектурное решение; код, карты, очередь, настройки и production не изменялись.

## Причины и границы вывода

1. **Подтверждённый дефект источника lexical candidates.** FTS-запрос периода включает короткие служебные токены, а следующий §2 фильтр считает только основы длиной ≥4 и требует две точные общие основы. Из 191 historical lexical rows: 113 имеют `stems_shared=0`, 78 — `=1`, ноль достигает порога. Среди них 97 попали только по отброшенному короткому токену. Пример A1: полная FTS-фраза достигает LIMIT=32, один `"к"*` или `"в"*` также даёт 32; после исключения токенов, несовместимых с §2, остаётся 7 строк. Следовательно, источник формирует кандидатов по более широкому правилу, чем допускает потребитель; сам предметный порог §2 не следует снижать.
2. **Подтверждённый источник высокой доли 2026.** В base slice 234/300 = 78% строк 2026. В base-1 финале все 56 строк 2026 происходят из base retrieval; period-fill добавляет 15 строк, но ни одной 2026. Базовый reranker практически нейтрален по году: 23.9% отбора для 2026 против 25.8% для прочих годов. Периодный механизм сейчас только разбавляет base, а не подавляет свежие факты. При числителе 56 для 58.1% требуется ≥97 строк знаменателя — ещё 9 сверх 88; около такого порядка составляет period-material, который может пережить rerank.
3. **Кандидат c0de0c2b не вызвал измеренную разницу до rerank.** Все детерминированные стадии baseline/candidate байт-идентичны во всех четырёх трассах. При 0 принятых lexical rows перестановка slot priority — no-op. Поэтому гипотеза «вектор вытесняет принятый lexical» отвергнута для этих данных. Rerank даёт шум итогового состава, но candidate не менял его вход.

## Контракт A — исправить FTS/§2 рассогласование

Это отдельный in-scope defect repair, необходимый до оценки любого механизма, опирающегося на lexical period leg. Он **не достаточен** для share threshold: по raw/current DB после исключения коротких токенов §2 проходит лишь около 6 lexical rows на 15 вопросов; это может дать только ~2–3 дополнительных финальных строк при observed survival, не требуемые +9.

### Минимальный write scope

- `services/mca_retrieval_context.py`: только построение lexical query для периодного FTS-вызова (или имеющийся period-only query option). Передавать в `search_graph_facts_fts` match, согласованный с §2: исключить токены, которые §2 исключит из shared-stem подсчёта (`len(stem)<4`), сохранив текущие длинные содержательные prefix/stem варианты и обычные FTS правила. Не менять глобальную `build_fts_query` семантику всех остальных callers.
- `services/database.py`: **не менять**, если текущая allowlisted `exclude_years` и фильтр окна уже стоят до `ORDER BY rank LIMIT`; этот контракт доказан для текущего кода. Менять только при новом конкретном failing test/reproduction, не по предположению.
- `tests/test_memory_period_vector_leg.py` (или близкий существующий FTS/period retrieval test): предметные regression cases.

### Инварианты и приёмка

- Порог остаётся `stems_shared >= 2`; короткий токен не должен самостоятельно занимать весь LIMIT или заводить в пул строку, которая гарантированно провалится в §2.
- Проверить каждый короткий токен (к, в, с, что и иные фактические `<4` по той же tokenizer/stemmer) исключается только для period FTS; длинные query-основы и существующие prefix/stem расширения сохраняются.
- На тесте A1 exact query: full query больше не равен одиночному short-token результату; match с удалёнными короткими токенами выдаёт ту же семантически определённую область (исключая гарантированно неподходящие rows), year window до LIMIT остаётся истинным.
- Инструментированный read-only harness на той же DB copy: для 191 A1–A15 historical rows сохранить row-level `query_stems`, `row_stems`, `stems_shared`, source-token match explanation, year/dedup/eligibility result и reason. Проверить ожидаемые hist: 113/78/0 как baseline, и новое фактическое количество candidates/accepted после исправления; не утверждать успех по простой смене hist.
- Любая ошибка query construction — сохранить текущую деградацию retrieval с честным diagnostic, не формировать пустое/неограниченное FTS выражение и не прекращать основной retrieval. Никакие LLM, новая схема, индекс/embedding rebuild или production write.

## Контракт B — механизм, способный достичь 58.1%

Минимальный механизм, согласующийся с измеренным bottleneck, — **bounded, query-relevant historical period augmentation с расширенным candidate pool и защитой принятой historical evidence от reranker-only удаления**, а не ещё один priority permutation. Однако текущих данных недостаточно зафиксировать конкретную численную квоту/слотовый divisor как готовую архитектуру: измеренная чувствительность budget 2→3→4→6→∞ даёт принятые 25→30→33→33 на A1–A15; годовой dedup насыщает набор на 33. Даже 33 принятых не гарантируют 9 дополнительных финальных строк. Простое расширение пула/слотов без ограничения качества может внести нерелевантные факты, а без защиты reranker может их удалить; нельзя обещать threshold без экспериментального evidence.

Поэтому Builder получает **один bounded экспериментальный slice**, не безусловную отгрузку:

- после контракта A, выбрать не более `limit//5` принятых lexical rows (текущая ограниченная вставка) и увеличить доступный period candidate pool только до величины, достаточной для покрытия всех допустимых годов, которые отсутствуют в base slice (текущий saturation предел 33 уникальных по году на выборке); сохранять year dedup, subject threshold, statuses, origin/self exclusion, TTL/archival semantics и effective runtime flags;
- для `policy="historical"` защищать прошедшие §2 lexical rows от удаления валидным rerank verdict, сохраняя текущий смысл period evidence; KNN не считать подтверждённым предметным совпадением и продолжать rerank по существующему контракту;
- `auto` не менять без явного экспериментального обоснования и тестов: при текущем `strict = policy != "historical"` порог распространяется на KNN под `auto`; его сохранение/пересмотр обязательно должно быть единообразно отражено в коде, тестах и тексте требований.
- Не использовать глобальный `base retrieval` age penalty / подавление свежего года как первый fix. Это меняет основной retrieval и текущие запросы без года; stage evidence указывает на period denominator как меньший seam, способный внести нужные исторические строки. Если bounded augmentation не даёт нужных ≥9 survivors при relevance gate, остановиться и вернуть факты для нового решения; не включать агрессивное suppression или произвольный большой слот бюджет.

### Write scope эксперимента B

- `services/direct_chat_service.py`: ограниченный отбор/append периодных строк, параметризация пула и policy-правило защиты только в пределах existing direct-RAG historical/auto path; не трогать base retrieval scorer, общие reranker callers или `operative` path.
- `services/mca_retrieval_context.py`: если нужно — только period-only overfetch/query contract, без общей перестройки RetrievalRequest.
- `tests/test_memory_period_vector_leg.py` плюс существующие integration tests для `_rag_unified_rows → _build_rag_block`.
- `services/database.py` не входит, кроме исправления A, если конкретный SQL boundary test покажет дефект. `usage_json.period_fill.knn_ms/fts_ms` из NEXT-05 не менять/не откатывать.

### Инварианты, ошибки, откат

- Единственный периодный вызов на ход; operative pass не содержит period vector/FTS leg и сохраняет прежний путь.
- Годовой predicate на годах базового среза выполняется до FTS LIMIT; строки периода не дублируют base IDs и не дублируют уже покрытый год согласно текущему `seen_years` contract; при расширении года-охват должен быть задан явно в тестируемом contract, а не случайно.
- `limit//5` остаётся верхним пределом вставок до отдельного доказательства, что его изменение обязательно для threshold; общее число кандидатов в пуле может быть выше, но не означает увеличение финального контекста.
- При недоступной FTS/vector leg — существующая другая leg/fallback, честные reason codes, никаких фиктивных строк/timings; при пустом/ошибочном rerank сохраняется валидный existing behavior, кроме явно защищённых accepted lexical rows на historical, для которых empty verdict не должен стирать результат. Не применять эту защиту к KNN.
- Никаких настроек/флагов production, вероятностей, seed manipulation, prompts, DDL, новых store или provider changes.
- Rollback к последнему reviewed base/candidate без схемного отката; candidate code не должен менять DB state, кроме существующего telemetry usage в изолированных test copies. Не менять сохраняемые user/chat preferences.

## Валидность acceptance-измерения

Committed decomposition доказывает: источник DB, sample и harness идентичны; 15 A units × 2 policy = 30 кластерных единиц. Но cluster bootstrap CI около 50–73%, включает 58.1%; 15-question point metric не различает threshold от run-to-run reranker variability. Это **не** основание снизить 58.1%; также point FAIL остаётся формальным failure по действующему gate. Before/after measurement с нынешним n не способен установить эффект небольшого патча.

До Builder coding PM/Architect должны в existing contract artifact операционализировать валидное статистическое правило, не меняя threshold: предпочтительный минимальный план — расширить golden set независимыми вопросами исторических событий из той же DB copy, заранее зафиксировать набор/хеш/единицу анализа и измерять paired baseline/candidate на идентичных вопросах и effective config; число единиц определить через расчёт мощности/ширины CI для отличения 58.1% от ожидаемого baseline, затем повторять model calls достаточно, чтобы оценить стохастику (не трактовать повтор одного вопроса как независимый новый вопрос). Критерий остаётся share ≤58.1%, а точное pass-rule (например, upper CI ≤58.1% либо точечный cap при заранее установленном стабильном CI) должно быть выбрано до прогона и согласовано с владельцем/исходным requirement authority, если исходный контракт не задаёт его.

Если получить более крупный валидный независимый golden set на существующем archive невозможно или нельзя определить единственный честный statistical pass rule из текущего owner contract, вопрос порога/способа приёмки — настоящий owner product tradeoff: не менять его технически в одностороннем порядке. До уточнения не строить production fix ради неразличимой статистической границы. Никаких synthetic corpus rows, production probability changes или tuning на вопросах тестового набора.

Каждый допустимый эксперимент использует ту же read-only source DB sha `5310e91e...`, отдельную derived copy, один заранее зафиксированный golden sample, одинаковую фактическую model/provider/config identity и paired baseline. Если production identity модели недоступна — это явно обозначить; локальный provider не выдавать за production-equivalent.

## §4 / §2: принятое чтение policy

Существующая реализация `strict = policy != "historical"` означает: `historical` допускает vector candidate без порога lexical shared stems; `auto` применяет порог также к KNN. Принимается **реализованная детализация §4** как более конкретное указание mode-specific semantics; общее изложение §2 «порог для лексических строк» неполно и должно быть уточнено в едином текущем feature contract: «для lexical period candidates всегда ≥2; vector candidates в historical exempt, в auto проходят тот же threshold». Этого достаточно: сейчас менять кодовую политику не следует. Добавить/сохранить тесты обеих веток, чтобы исключить случайное расширение/сужение. Не менять acceptance ретроспективно и не интерпретировать смешанный `rejected_subject` под auto как только lexical rejection; отдельная телеметрическая разбивка — не обязательная часть NEXT-02, если измерение получает per-proxy counts из harness.

## Статусы и следующий Builder scope

- **NEXT-02: FAILED/PENDING** — исторический share 61.63/61.84% выше 58.1%, valid statistical power пока недостаточна для оценки patch effect; никакая часть не становится VERIFIED от этой архитектуры.
- **NEXT-05: отдельно** — timings 32/32 и p95 1172/1156 при лимите 1618 в binding проходят predeploy evidence; допустим самостоятельный `REVIEW`, но не VERIFIED без независимого review и применимых stage gates.
- **NEXT-03** (положительный controlled-only кейс) остаётся отдельно pending; **NEXT-04** остаётся pending. Не включать их в этот исправительный scope.
- **NEXT-01 / TIME-09 / V live** остаются postrelease/production-evidence требованиями, статусы не менять.

**Следующее действие Builder:** реализовать дефект A изолированно и тестами; затем реализовать только bounded historical period augmentation из B как экспериментальный candidate (никакого slot-priority no-op и никакого базового recency suppression), с feature/integration tests, объяснимым per-row denominator/source trace и rollback. Перед финальным 17+ расширенным набором PM/Architect фиксируют валидный paired measurement plan и заранее вычисленную достаточную выборку/pass-rule с тем же пределом 58.1%. Пройти same-copy paired before/after, каждый обязательный порог, независимый Reviewer на exact candidate. Если bounded candidate не проходит порог или relevance, оставить NEXT-02 FAILED/PENDING, откатить candidate path и вернуть данные для нового решения; не расширять scope автоматически.

ARCH_NEXT2_CORRECTED_READY — Builder scope: period-only FTS short-token alignment (не общий FTS builder) + bounded historical lexical augmentation с подтверждаемой защитой принятой lexical evidence; before implementation freeze powered paired same-DB acceptance design, затем все пороги включая неизменный 58.1%.