# VMQ-NEXT-02 (corrected): binding кандидата 77791184 — FAILED/PENDING

Дата: 13.11.2026. База: **`23477658`** (2.58.198). Кандидат: **`77791184`**
(полный SHA `777911841d2833b26e6d284f9661304afe2ae9c5`), worktree
`WorkspaceData/worktrees/c742e4de9e92c489/vmq-onto-01-3689dd92710d-cc7f6a83`
(detached HEAD). Контракт: `architecture-next2-corrected.md` (§A/§B), причина:
`evidence/vmq-mem/next-stage/next2-cause-decomposition-23477658.md`.

Это handoff Builder'а, **не approval**: NEXT-02 остаётся `FAILED/PENDING`;
порог 2026 share не пройден ни одним из двух candidate-прогонов. Продуктовый
код/тесты — только в указанном worktree; production, settings, prompts,
schema, БД и прогресс-карты не менялись. DDL=0, schema 47, новых LLM/сторов
нет.

## 1. Итог

| Проверка | Результат |
|---|---|
| Контракт A: периодный FTS согласован с §2 | **Реализован**, дефект источника подтверждён и снят |
| Контракт B: bounded period augmentation | **Реализован в границах**, но на этой выборке **инертен** |
| 2026 share (оба candidate-прогона) | **FAIL: 62,20 % и 60,92 %** против 58,1 % |
| Delivery | PASS count: 8/15 historical, 7/15 auto (оба прогона) |
| On-topic | PASS count-only: 8 (знаменатель 18 не подтверждён — как и прежде) |
| Irrelevant | PASS: 0,0 % |
| p95 period call | PASS: 1187 мс ≤ 1650 мс (baseline 1250 + 400) |
| `knn_ms`/`fts_ms` | PASS: 32/32 и 32/32, absent=0; baseline absent=64 |
| Итог NEXT-02 | **FAILED/PENDING**, не VERIFIED, не REVIEW как «прошло» |

Причина провала та же, что в разложении `23477658`, и теперь измерена после
исправления: **ни одна лексическая периодная строка не проходит §2**. FTS-
фильтр убирает 169 гарантированно-неподходящих строк (402 → 233), но
оставшиеся 233 делят с вопросом ровно одну основу (0 — 29, 1 — 204), поэтому
`stems_shared >= 2` не достигается. Принятый периодный набор остаётся 25
KNN-строк; числитель 2026 по-прежнему формируется только базовым retrieval.
Bounded pool (33) не насыщается (максимум 22 строки), вставки остаются
`limit//5 = 2`.

## 2. Diff относительно 23477658

`git diff --stat 23477658 77791184`: 4 файла, **+710/−25**.

| Файл | Δ | Что сделано |
|---|---|---|
| `services/mca_retrieval_context.py` | +120/−4 | §A: периодный FTS граф-фактов получает match только из §2-совместимых токенов (`_period_fts_keywords`, основа ≥4); глобальный `build_fts_query` и все прочие вызовы не изменены; пустой §2-match → пропуск только периодной лексической ноги с `fts_ms_reason="fts_match_empty"`, vector продолжает. Перенесены аддитивные `knn_ms`/`fts_ms` (NEXT-05) без изменения семантики: измеряется только реально выполненный периодный вызов, отсутствие — `None` + причина. |
| `services/direct_chat_service.py` | +36/−6 | §B: пул периода `33` (измеренное насыщение год-дедупа; выше не добавляет допустимых годов), вставки по-прежнему `limit//5`; слоты отдаются принятой лексической строке до vector (инвариант NEXT-02 «vector не вытесняет принятую lexical»), vector добирает свободное место; добавлены счётчики `pool_rows`/`pool_years`. Защита lexical от rerank уже существовала и сохранена; KNN по-прежнему судится. |
| `tests/test_memory_period_vector_leg.py` | +566/−10 | §A/§B regression: короткие токены, period-only match, пустой match, год до LIMIT, слоты, пул, год-дедуп, year share, timings, rollback. |
| `tests/test_mem_time_policy.py` | +1/−1 | Пин пула 32 → 33 (измеренное насыщение). |

Что сохранено из `c0de0c2b` **только там, где разрешает контракт**:

* NEXT-05-тайминги `knn_ms`/`fts_ms` — сохранены (аддитивны, не влияют на
  отбор); кандидат проходит их predeploy-порог.
* Приоритет слота принятой lexical-строки — сохранён как инвариант NEXT-02
  (`architecture-next2.md` п.1), **не** как remedy доли 2026: измерение
  показывает, что принятых lexical-строк нет, поэтому сам по себе приоритет
  остаётся no-op. Формулировка «priority permutation чинит долю» не
  используется.

`services/database.py`, settings, prompts, schema, operative path, общий
reranker, базовый retrieval и recency-suppression не менялись.

## 3. Тесты (candidate 77791184)

| Команда | Результат |
|---|---|
| `pytest tests/test_memory_period_vector_leg.py -q` | **39 passed** (18 baseline + 21 новая проверка) |
| `pytest tests/test_mem_time_policy.py tests/test_memory_unified_retrieval_06.py tests/test_mca07_retrieval_context_round1027.py tests/test_memory_period_vector_leg.py -q` | **167 passed** |
| `pytest tests/test_memory_core_round1020.py tests/test_asap8_v63_b03_memory.py tests/test_graphrag_memory.py tests/test_memory_lookup_round1026.py tests/test_memory_commands.py tests/test_history_relevance.py -q` | **382 passed** |

Pre-existing, не внесённые кандидатом: `tests/test_direct_fallback_recompose_asap32.py`
— 5 failed и на baseline `23477658` (проверено в чистом worktree
`...-aaecec2a`), к period-fill отношения не имеют; остаются BACKLOG_ONLY.

Что реально проверяют новые тесты (не только «зелёные»):

* `test_short_token_does_not_seed_row_that_section_two_rejects`: строка,
  совпавшая только по `к/в/с/что`, входит в полный FTS и **не** входит в
  §2-match; содержательная длинная основа остаётся; `_rag_subject_shared`
  для такой строки = 0.
* `test_period_call_drops_short_tokens_from_facts_fts_not_global`: реальный
  `retrieve(period_fill=True)` зовёт FTS фактов без `"к"*`/`"в"*`/`"что"*`/
  `"был"*`, но с `"vasek"*`/`"отношением"*`; канал сообщений сохраняет
  полный match; usage несёт `fts_words_dropped > 0`.
* `test_non_period_call_keeps_full_match`: обычный (не period) вызов
  сохраняет прежний match с короткими токенами.
* `test_all_short_tokens_skip_only_period_facts_fts`: запрос только из
  коротких токенов не строит пустое FTS-выражение и не зовёт SQL; получает
  `fts_ms_reason="fts_match_empty"`; vector-нога доставляет старую строку,
  status OK.
* `test_year_window_still_applies_before_limit` +
  `test_top_n_excluded_year_does_not_hide_older_row`: год-предикат стоит до
  `LIMIT`.
* `TestPeriodSlotPriority`: 0 lexical → максимум 2 vector; lexical занимает
  оба слота; vector не вытесняет принятую lexical; свободный слот добирает
  vector; `limit//5` = 2/1/1; self-origin и повтор года не создают фикций;
  пул 33; год базового среза не дублируется.
* `TestPeriodYearShare`: синтетический блок — периодные строки 2023/2025
  увеличивают знаменатель на 2, числитель 2026 не меняется, доля 2026
  снижается.
* `TestPeriodUsageTimings`: `knn_ms`/`fts_ms` — числа ≥0 при выполненных
  каналах; отсутствующая vector-нога → `knn_ms=None` +
  `vector_leg_unsupported`; упавший FTS → `fts_ms=None` + `fts_error`,
  vector и retrieval живы; `period_fill=False` → `period_fill is None`,
  `exclude_years=None` в SQL, usage без блока; `_exclude_years_of` — только
  period.
* Существующий `test_empty_verdict_keeps_row_model_never_saw` подтверждает:
  принятая lexical-строка §2 переживает валидный пустой вердикт rerank, KNN-
  строка — нет.

## 4. Измерение (valid paired same-copy)

| Параметр | Значение |
|---|---|
| Source DB copy | `.../probe-d86a98460c/prod-copy.db`, sha256 **`5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2`**, read-only |
| Derived copy | `sqlite3.backup` из `mode=ro&immutable=1`; sha256 **`1751418e...b6f5d27`**, user_version 47; свежая копия на каждый прогон, после прогона удалена |
| Sample | `measure-2026-11-12-sample.json`, sha256 **`d1c7e394f39a06096669c959388ce56e88e1062554a67aab88380b4625e36c58`**, 17 вопросов A1–A15/C1/C2 |
| Harness | `next2-measure-2026-11-13-harness.py`, sha256 **`ebfc79bd42725383587e6890f823f88ef9b824e5b6d6ca30775ebed35bf36517`** (без изменений) |
| Прогоны | 2 baseline (`23477658`) + 2 candidate (`77791184`), все 17 вопросов × 2 политики, ошибок/таймаутов/missing нет |
| Effective rerank | **True**, `_cp_g` resolved True 34/34 в каждом прогоне |
| Effective config | facts_limit=10, context_max_chars=2000, `deepseek/deepseek-v4.1-flash`, `https://nano-gpt.com/api/v1`, `gemini-embedding-001` dim 3072, period guard пуст |
| Модель | та же identity, что в замере 12–13.11; локальный provider **не** объявляется production-equivalent |
| Production writes | нет; source copy sha до/после совпадает; derived copies удалены |

### 4.1 Пороговые метрики

| Прогон | Код | Delivery H/A | 2026 H / A / **both** | On-topic | Irrelevant | p95 period call | `knn_ms`/`fts_ms` |
|---|---|---|---:|---:|---:|---:|---|
| base-3 | 23477658 | 8/15, 7/15 | 24/39=61,54 % / 30/47=63,83 % / **54/86=62,79 %** | 8 | 0,0 % | 1234 мс | absent=64 |
| cand-1 | 77791184 | 8/15, 7/15 | 22/37=59,46 % / 29/45=64,44 % / **51/82=62,20 %** | 8 | 0,0 % | 1187 мс | 32/32 |
| base-4 | 23477658 | 8/15, 7/15 | 25/43=58,14 % / 31/46=67,39 % / **56/89=62,92 %** | 8 | 0,0 % | 1250 мс | absent=64 |
| cand-2 | 77791184 | 8/15, 7/15 | 25/41=60,98 % / 28/46=60,87 % / **53/87=60,92 %** | 8 | 0,0 % | 1187 мс | 32/32 |

* Порог 58,1 % — **FAIL в обоих candidate-прогонах** (и в обоих baseline).
* Delivery count ≥6/15 — PASS; on-topic count-only 8 — PASS с прежней
  оговоркой о знаменателе 18; irrelevant <28 % — PASS; p95 ≤ 1250+400=1650 —
  PASS; timings 32/32 — PASS.
* Снижение точки candidate относительно baseline (62,20/60,92 против
  62,79/62,92) **не** объявляется эффектом: pre-rerank наборы идентичны,
  различие финального блока — стохастика reranker (см. §4.3).

### 4.2 Стадии (все 4 прогона, A1–A15 × обе политики)

| Стадия | base-3 | cand-1 | base-4 | cand-2 |
|---|---:|---:|---:|---:|
| base slice, всего / 2026 | 300 / 234 (78,00 %) | 300 / 234 | 300 / 234 | 300 / 234 |
| period pool, всего (lexical/knn) | 460 (354/106) | **289 (183/106)** | 460 (354/106) | **289 (183/106)** |
| принято в срез (`period_rows`) | 25, все knn | **25, все knn** | 25, все knn | **25, все knn** |
| до rerank (`rows_returned`) | 289 / 211 (73,01 %) | **289 / 211 (73,01 %)** | 289 / 211 | **289 / 211** |
| финал, всего / 2026 | 86 / 54 | 82 / 51 | 89 / 56 | 87 / 53 |
| принято → в финале | 25 → 15 | 25 → 15 | 25 → 15 | 25 → 16 |
| потеряно на rerank | 10 | 10 | 10 | 9 |

Год-разбивка пула candidate: 2022=26, 2023=82, 2024=41, 2025=140, 2026=0;
принятые годы те же, что baseline (2022=6, 2023=9, 2024=3, 2025=7).
Числитель 2026 в финале — **только base retrieval** (234 → 54/56/51/53);
периодный добор не добавляет 2026 ни одной строкой (годовое окно исключает
2026).

`pool` candidate: 32 вызова, среднее 11,34 строки / 2,34 года, максимум 22;
baseline — 16,56 / 2,41, максимум 22. Пул 33 **не насыщается**.

### 4.3 §2 per-row (полный текст фактов, та же DB copy)

| Набор | Строк | `stems_shared=0` | `=1` | `≥2` (принято) |
|---|---:|---:|---:|---:|
| baseline, A1–A15 historical | 191 | 112 | 79 | **0** |
| candidate, A1–A15 historical | 98 | 16 | 82 | **0** |
| baseline, все 17 × 2 | 402 | 206 | 196 | **0** |
| candidate, все 17 × 2 | 233 | 29 | 204 | **0** |

Фильтр §A убрал 169 строк (402 → 233) и 93 строки в A1–A15 historical
(191 → 98) — ровно те, что совпадали только по коротким служебным токенам.
Оставшиеся строки делят с вопросом только одну основу; порог §2 не достигнут
ни разу. Это фактическое объяснение, почему предсказанные контрактом «~6
строк на 15 вопросов» не материализовались в принятые строки: на полном
тексте и реальном годовом окне кандидатов с двумя общими основами среди
лексического пула нет. (Расхождение 112/79 против 113/78 в committed
разложении — на 1 строку: там пересчёт шёл по 150-символьному preview из
raw, здесь — по полному тексту из derived copy; вывод «0 принятых» одинаков.)

### 4.4 Парность и шум

* `base-3 ↔ base-4`: Σ|Δ 2026| = 6, Σ|Δ строк| = 9; pre-rerank ids
  идентичны 30/30.
* `base-3 ↔ cand-1`: Σ|Δ 2026| = 7, строк = 10; pre-rerank ids совпали
  28/30.
* `base-3 ↔ cand-2`: Σ|Δ 2026| = 9, строк = 15; pre-rerank ids 28/30.
* `cand-1 ↔ cand-2`: Σ|Δ 2026| = 8, строк = 9; pre-rerank ids 30/30.
* Различие 2/30 единиц — только порядок/первая KNN-строка пула (A7: те же
  два id в другом порядке; A8: первая KNN-строка 5375 вместо 6076 при том
  же составе пула и том же числе/годах принятых строк). Это следствие
  изменившегося состава лексической части пула, не изменение правила отбора;
  агрегат принятых и pre-rerank идентичен.
* Кластерный bootstrap (20 000 ресэмплов, 30 единиц A×policy):
  * cand-1: точка 61,66 %, 95 % CI **49,28–71,28 %**, P(≤58,1 %)=0,239;
  * cand-2: точка 60,50 %, 95 % CI **49,40–69,00 %**, P(≤58,1 %)=0,279;
  * base-3: 62,37 %, 51,19–71,68 %, 0,196; base-4: 62,57 %, 52,50–71,03 %, 0,165.
  CI накрывает порог; point FAIL остаётся формальным failure, но метрика
  по-прежнему не различает эффект малого патча. Это не основание снижать
  порог.

## 5. Почему порог не достигнут (stage-by-stage)

1. **Числитель 2026 — базовый retrieval.** Base slice 234/300 = 78 %;
   period window исключает 2026 целиком, поэтому периодный механизм не
   может добавить ни одной строки 2026. Он влияет только на знаменатель.
2. **Лексическая нога после §A всё ещё пуста по §2.** 98 кандидатов
   A1–A15-historical: 16 с 0 основами, 82 с 1, ноль с ≥2. Причина не в FTS
   (он теперь возвращает предметную область: A1 pool 7 вместо 16, без
   `"к"*`/`"в"*`), а в том, что корпус в годовом окне не содержит строк,
   делящих с вопросом две основы. Снижать §2 или защищать KNN контракт
   запрещает.
3. **Bounded pool не является ограничителем.** Максимум пула 22 < 33;
   принято 25 KNN-строк — ровно как baseline. Увеличение пула до 33 на этих
   данных не добавляет кандидатов; вставки остаются `limit//5 = 2`.
4. **Rerank снимает 10 из 25 принятых KNN-строк** (cand-2 — 9).
   Защищённых lexical-строк, которые могли бы это компенсировать, нет.
5. Чтобы при числителе 51 получить 58,1 %, нужно ≥88 строк (+6 к 82); при
   53 — ≥92 (+5 к 87). Ни один измеренный механизм не даёт этих строк:
   lexical=0, pool не насыщен, слоты заморожены, recency-suppression
   запрещён. Это и есть возврат фактов Architect'у, а не «ещё один патч».

## 6. Contract A: что именно доказано

* Глобальный `build_fts_query` не изменён: обычный и все прочие вызовы
  сохраняют прежнюю формулу; фильтр живёт только в `retrieve` при
  `period_fill`.
* A1-класс: полный FTS-запрос (LIMIT 32) забивается служебными токенами;
  §2-match возвращает 7 предметных строк; одиночный `"к"*`/`"в"*` больше не
  участвует в периодном запросе. В прогоне candidate A1 pool = 7 (1 knn + 6
  stems), baseline A1 pool = 16 (1 knn + 15 stems).
* Годовое окно остаётся до `LIMIT` (SQL boundary test), пустое окно —
  byte-identical, `period_fill=False` — прежний SQL.
* Ошибка/пустой match: лексическая нога периода пропускается с честным
  `fts_match_empty`, vector-нога и основной retrieval продолжаются; «0 ms» и
  фиктивных строк нет.
* A5 (реальная деградация): §A-пул = 0 строк (baseline — 16 отклонённых
  лексических, 0 KNN), `vector_pool_miss=1`; принятых строк 0 и в baseline,
  поэтому состав среза не меняется, а пустой лексический путь честно
  помечен, а не заполнен шумом.
* p95 считается nearest-rank по **32 фактическим** периодным вызовам
  (A1–A15/C1–C2; два вопроса без period leg не выдумываются). При прежнем
  baseline 1218 мс (лимит 1618) candidate 1187 мс тоже проходит; в таблице
  взят более строгий парный baseline 1250 мс (лимит 1650).
* Инструментированный per-row harness на той же DB copy: baseline 191
  (112/79), candidate 98 (16/82), принято 0/0; поля `query_stems`/`row_stems`
  пересчитаны продуктовыми `_rag_subject_stems`/`_rag_subject_shared` на
  полном тексте.

## 7. Contract B: что именно доказано и чего нет

Доказано:

* Пул ограничен 33 (измеренное насыщение год-дедупа), вставки — `limit//5`;
  год-дедуп, статусы, TTL/archival, origin/self exclusion не изменены.
* Принятая lexical-строка идёт до vector и защищена от rerank; KNN
  продолжает судиться; `operative` не получает периодной ноги; один
  периодный вызов на ход; `strict = policy != "historical"` сохранён
  (historical: vector без порога; auto: порог и для KNN) и покрыт тестами
  обеих веток.
* Timings аддитивны: 32/32 `knn_ms`, 32/32 `fts_ms`, absent=0; p95 1187 мс.

Не доказано / не достигнуто:

* Bounded pool не насыщается (max 22), поэтому «расширение пула» на этой
  выборке не меняет принятый набор; принято 25 KNN, как в baseline.
* Ни одной принятой lexical-строки, которую можно было бы защитить, нет.
* Порог 58,1 % не достигнут; кандидат не заявляется как remediation.

## 8. Ограничения и честные оговорки

* On-topic: 8 уникальных строк — **count-only** PASS; исходный знаменатель
  18 не подтверждён фактическим набором (54 distinct delivered id), как и в
  предыдущем замере. Denominator не подменялся.
* Кластерный CI ±10 п.п. накрывает 58,1 %; 15 вопросов не различают
  threshold от reranker-разброса. Валидный расширенный golden set и
  statistical pass-rule в контракте не зафиксированы; это остаётся
  PM/Architect/owner-вопросом, а не решается Builder'ом.
* Локальный provider (`nano-gpt`) той же identity, что в замере 12–13.11,
  но не production-equivalent; production-прогон не выполнялся.
* Никаких production/settings/prompt/schema изменений; source DB только
  read-only; derived copies удалены после прогонов.

## 9. Rollback

* Rollback — только кода к `23477658` (или к parent `77791184`); схема/DDL
  не затрагивались, миграционный откат не нужен.
* `period_fill=False` и `None`/пустой `exclude_years` — прежний SQL и
  поведение (тесты `test_period_fill_false_restores_baseline`,
  `test_empty_window_is_byte_identical`).
* §A можно оставить как отдельный defect repair даже при FAIL §B; §B
  (пул 33) на измеренных данных инертен, и его судьбу (оставить/убрать)
  решают Architect/Reviewer, а не Builder.

## 10. Артефакты (sha256)

| Файл | Байт | sha256 |
|---|---:|---|
| `next2b-measure-summary.json` | 35 230 | `34943848c09b28db7da508535ec7c7de4e9430fbd3017aeb4f350e1e3882ed13` |
| `next2b-measure-harness.py` | 20 019 | `ebfc79bd42725383587e6890f823f88ef9b824e5b6d6ca30775ebed35bf36517` |
| `next2b-raw-base-23477658-3.json` | 349 925 | `e7d0014979a2a601b2300c759a9b88f9b9940cd3bbc42edd7d256b424a96f399` |
| `next2b-raw-cand-77791184-1.json` | 314 477 | `f6346a8995d3180394c435ddc098ef2beeae217b8730d99d91c7e217b1b2cbd5` |
| `next2b-raw-base-23477658-4.json` | 350 837 | `4223426bfd4f26a4143b36c31ed2471c09969de501dffa384eb879d31171e5fe` |
| `next2b-raw-cand-77791184-2.json` | 319 519 | `78edfb746ecd0fef613eb75cb849ea3c208b03d90c8d6904713742e56f981ae2` |
| `next2b-raw-*.log.txt` | 4 | `e969da40…`, `32a2192b…`, `b06d6a93…`, `2925ca50…` |
| `next2b-measure-eval.py` | 9 252 | `7f507ce0713dccc58fe9b322f054ea81de528f1e4f897e866bc88826cf2e9567` |
| `next2b-measure-decompose.py` | 9 555 | `d14e9f76c7fa11349a897d9758077cad2f5fa22931b07ad0cb531957b226cad9` |
| `next2b-measure-runner.py` | 3 712 | `94c87a7a5bc5ea49b82a409625eafc7570e48ec131ab9be838f16da247cbf1f6` |
| `next2b-stems-exact.json` | 952 | `d730424edf03808b4bff49cd7001b09f795bbcbc375e4104078f2ccc6fa8ec35` |

## 11. Статусы и следующий шаг

* **NEXT-02: FAILED/PENDING** — 2026 share 62,20/60,92 % > 58,1 %; никакая
  часть не становится VERIFIED/REVIEW-прошло.
* **NEXT-05**: timings 32/32, absent=0, p95 1187 ≤ 1650 — predeploy-часть
  проходит; отдельный `REVIEW` возможен, но не VERIFIED без независимого
  review и применимых stage-gates.
* **NEXT-01 / TIME-09 / V live**: не входили в scope, статусы не менялись.
* Architect/Reviewer должны решить: достаточно ли §A как отдельного
  defect repair (да, источник согласован), и что делать с §B/порогом, если
  §2 и корпус не дают ни одной принятой lexical-строки. Builder не повышает
  статус и не снижает порог.

BUILDER_HANDOFF_NEXT2B_READY_FOR_REVIEW — код `77791184`, evidence этот
файл и артефакты; independent approval не заявляется.
