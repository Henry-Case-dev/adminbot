# VMQ-NEXT2 (NEXT-02 + NEXT-05) — candidate binding (13.11.2026)

Кандидат: branch `vmq/next2`, worktree
`WorkspaceData/worktrees/c742e4de9e92c489/vmq-onto-01-3689dd92710d-04cb427b`.
Код **`c0de0c2b`** (код+тесты), база **`23477658`** (2.58.198). Документ — второй
коммит этой ветки. Контракт: `plans/features/vmq-onto-01/architecture-next2.md`
(ARCH_NEXT2_READY). Это handoff Builder'а; approval не заявляется — решает Reviewer.

Ничего не деплоилось, production/settings/prompts/schema не менялись, новых
LLM/агентов/сторов/DDL нет: schema 47, DDL=0.

## 1. Diff относительно 23477658

| Файл | Δ | Что |
|---|---|---|
| `services/direct_chat_service.py` | +13/−4 | `_rag_period_subject_filter` обходит **сначала принятые лексические** строки, затем векторные: vector не занимает слот `limit//5`, нужный принятой lexical-строке; остаток слота по-прежнему может занять vector. Комментарии/докстроки. |
| `services/mca_retrieval_context.py` | +57/−2 | В уже существующий `usage_json.period_fill` аддитивно `knn_ms` / `fts_ms` — длительности реально выполненных периодных KNN (`period_fill_candidates`) и FTS (`search_graph_facts_fts` с годовым окном). Нет вызова — `null` + `knn_ms_reason`/`fts_ms_reason`, никогда `0 ms`. Хелперы `_period_add_ms`, `_period_ms_of`. |
| `tests/test_memory_period_vector_leg.py` | +283/−2 | Slot-priority, top-N SQL, usage timings, rollback/degradation. |
| `services/database.py` | **не менялся** | `exclude_years` уже стоит до `ORDER BY rank LIMIT`; проверено тестом и трассой. |

`git diff --stat 23477658 c0de0c2b`: 3 files, +352/−9.

## 2. Тесты (temp fixtures, без production)

До изменения baseline: `tests/test_memory_period_vector_leg.py` — **18 passed**.

После изменения / на кандидате:

| Команда | Результат |
|---|---|
| `pytest tests/test_memory_period_vector_leg.py -q` | **30 passed** |
| `pytest tests/test_mem_time_policy.py tests/test_memory_unified_retrieval_06.py tests/test_mca07_retrieval_context_round1027.py -q` | **128 passed** |
| `pytest tests/test_memory_core_round1020.py tests/test_asap8_v63_b03_memory.py tests/test_graphrag_memory.py -q` | **244 passed** |
| `pytest tests/test_memory_lookup_round1026.py tests/test_memory_commands.py tests/test_history_relevance.py -q` | **138 passed** |

Что именно утверждают новые тесты (детерминированная синтетика, `limit=10`):

1. `TestPeriodSlotPriority`: 0 принятых lexical → **максимум 2** vector-строки;
   lexical-only заполняет два слота; 2 принятых lexical + vector → **vector не
   проходит** (слоты у lexical); 1 lexical + vector → lexical первым, свободный
   слот забирает vector; бюджет `limit//5` = 2/1/1 для limit 10/5/1; self-origin
   и повтор года **не создают фиктивной доставки**.
2. `TestSubjectThreshold`: сохранён обновлённый контракт — vector по-прежнему
   обходит порог §2 под `historical`, но **идёт после** принятой lexical.
3. `TestFtsYearWindow`: top-N строк исключаемого года (3×2026) не прячут валидную
   строку 2023 при `limit=2`; `None`/пустое окно — прежний SQL (байт-в-байт).
4. `TestPeriodUsageTimings`: численные неотрицательные `knn_ms`/`fts_ms` при
   выполненных каналах; отсутствующая vector-нога → `knn_ms=null` +
   `vector_leg_unsupported`; упавший FTS → `fts_ms=null` + `fts_error` (vector
   работает, retrieval не рвётся); `period_fill=False` → нет `period_fill` в
   usage и `exclude_years=None` в SQL; прежние ключи usage сохранены и JSON
   сериализуем.

Pre-existing вне scope: `tests/test_direct_fallback_recompose_asap32.py` — 5
failed **и на кандидате, и на чистом 23477658** (воспроизведено в baseline
worktree), к period-fill не относится → BACKLOG_ONLY, не правилось.

## 3. Замер: точное тождество стенда

| Что | Значение |
|---|---|
| Источник | `.../probe-d86a98460c/prod-copy.db`, sha256 **`5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2`** (совпал), открыт read-only |
| Целостность | `PRAGMA quick_check=ok` (12.11), `user_version=47`, `graph_facts=21704` (в чате 20478) |
| Производная копия | `sqlite3.backup` из read-only источника, **свежая на каждый прогон**; derived sha256 `1751418ec7803fb828bb4ddfe060a3ab0b79075148963ffda2e602250b6f5d27`, user_version 47 |
| Чат/путь | `-1002661910336`; реальные `_rag_unified_rows → _build_rag_block` |
| Вопросы | те же 17: A1–A15, C1, C2 (`next-stage/measure-2026-11-12-sample.json`, sha256 `d1c7e394...`) |
| Harness | без изменений, sha256 `ebfc79bd42725383587e6890f823f88ef9b824e5b6d6ca30775ebed35bf36517` (копия в этой папке) |
| Effective rerank | **True**, резолвер вернул True на каждом блоке (34/34) |
| Модель/эмбеддинги | `deepseek/deepseek-v4.1-flash` через `https://nano-gpt.com/api/v1`; `gemini-embedding-001`, dim 3072, `vec_available=true`, index gen=1 fp `96f80838…`, period guard пуст (нога допущена) |
| Effective limits | facts_limit=10, context_max_chars=2000 |

Прогоны: baseline `23477658` ×2 и кандидат `c0de0c2b` ×2 — каждый на своей
производной копии. Стохастический reranker не усреднялся: показываю каждый прогон.
Production probabilities/settings/overrides/данные не менялись, генерации не было.

## 4. Результаты и пороги контракта

`2026 share` — по A1–A15, обе политики, те же «строки в блоке», что в замере
12.11 (зафиксированный порог **≤58,1 %**).

| Прогон | Код | Доставка H/A (≥6/15) | 2026 H / A / обе (≤58,1 %) | p95 period call (≤ baseline+400) | `knn_ms` n / p95 | `fts_ms` n / p95 | Нет измерения |
|---|---|---|---|---|---|---|---|
| base-1 | 23477658 | 8/15, 7/15 | 61,36 / 65,91 / **63,64** | 1218 ms | 0 | 0 | 64 |
| base-2 | 23477658 | 8/15, 7/15 | 60,87 / 62,22 / **61,54** | 1155 ms | 0 | 0 | 64 |
| cand-1 | c0de0c2b | 8/15, 7/15 | 59,52 / 63,64 / **61,63** | 1172 ms | 32 / 232,3 | 32 / 54,0 | **0** |
| cand-2 | c0de0c2b | 8/15, 7/15 | 61,54 / 62,16 / **61,84** | 1156 ms | 32 / 204,4 | 32 / 53,2 | **0** |

- `knn_ms` кандидата: 190,5–233,2 ms; `fts_ms`: 6,0–55,3 ms (диапазоны по обеим
  прогонам). Оба поля — числа ≥0, без текстов/запросов/id.
- p95 period call baseline = max(1218, 1155) = **1218 ms**, разрешено ≤ **1618 ms**;
  кандидат 1172/1156 → **PASS**.
- Блок целиком (включая сетевой rerank) p95: base 5657/5827 ms, cand 7406/5250 ms —
  это стохастическая latency провайдера rerank, порог контракта относится к
  period call, поэтому в приёмку не входит; приведено для честности.
- Замер полный: 32 period-вызова на прогон (17 вопросов × 2 политики минус 2
  блока, где `auto`-гейт не запускает добор); во всех `limit=32`, пул ≤22 строк.

### Приёмка по пунктам

| Клауза | Порог | Факт | Вывод |
|---|---|---|---|
| Доставка якоря | ≥6/15 каждая политика | 8/15 и 7/15 в **обоих** прогонах | **PASS** |
| Доля 2026 на A1–A15 | ≤58,1 % | **61,63 % и 61,84 %** (base 63,64/61,54) | **FAIL** — NEXT-02 не закрыт |
| «По теме» | ≥8/18 | 8 различных строк в каждом прогоне (см. §5) | счёт 8≥8 PASS, но состав/знаменатель иной (10 различных), как и в замере 12.11 |
| Явно нерелевантные | <28 % | 1/10 = 10,0 % (cand-1), 0/10 = 0 % (cand-2) | **PASS** |
| p95 period call | ≤ baseline+400 ms | 1172/1156 ≤ 1618 | **PASS** |
| `knn_ms`/`fts_ms` | числа при выполненных каналах | 32/32 в обоих прогонах, absent=0 | **PASS** |

## 5. Фактическая трасса (не причинный вывод)

Ключевой измеренный факт: на этом наборе **нет принятых лексических периодных
строк**, которые можно было бы защитить приоритетом. В historical-вызовах A1–A15
пул лексики = **191 строка, отклонено порогом §2 — 191** (0 принятых); в `auto`
для каждого вызова выполняется тождество `rejected = лексика + отклонённый knn`.
Поэтому все доставленные периодные строки — `subject_proxy=knn` (25 вхождений,
20 различных), и набор периодных строк совпадает с baseline; различия блоков
между прогонами — стохастика rerank.

Следствие: гипотеза «векторные строки занимают слоты раньше лексических» на
этом наборе **не подтверждается** — вытеснять было нечего. Приоритет каналов
исправлен по контракту и покрыт синтетикой, но рост доли 2026 он не устраняет:
порог 58,1 % не пройден в обоих candidate-прогонах. Причина доли остаётся
недоказанной; это evidence для возврата на архитектурное решение, без ослабления
acceptance и без нового алгоритма в этом срезе.

Оценка релевантности (правило `time/independent-sample-709865f6.md`) по
фактически отрисованным периодным строкам A1–A15:
по теме — 1713, 1725, 1753, 1801, 2358, 2580, 2753, 4864 (**8**); тот же предмет —
1994, 6076/7302; явно нерелевантна — 8447 («рынок» одним словом, только cand-1).
Строки 2912, 6709, 6434, 7144, 8291, 3074, 3280, 2951 были в пуле, но rerank их
не отрисовал ни в одном candidate-прогоне.

## 6. Rollback

Откат — только к предыдущему reviewed коммиту `23477658` штатной процедурой;
данные и schema не требуют миграционного отката (DDL=0, schema 47); effective
флаги не трогаются. `period_fill=False` и `exclude_years=None/пусто` возвращают
прежнее поведение (тесты `test_period_fill_false_restores_baseline`,
`test_empty_window_is_byte_identical`).

## 7. Артефакты и хеши

| Файл | Размер | sha256 |
|---|---|---|
| `next2-measure-2026-11-13-summary.json` (компактные метрики + per-question + классификация) | 93 576 Б | `e801172cc92bddf50135fa3eacdd2f7aedff4ff31d31a9dd1d521c33a1a5e084` |
| `next2-measure-2026-11-13-raw-base-1.json` (полная трасса) | 352 723 Б | `253ff5bcbdeea5f428ae738cb072a4805e455d255ebb67677eae9afdeab53223` |
| `next2-measure-2026-11-13-raw-base-2.json` | 352 486 Б | `3270635c70d9719e8814ed06e3fa993766a29c38aa25f1319c60f060f52244b5` |
| `next2-measure-2026-11-13-raw-cand-1.json` | 354 476 Б | `707eda0e8f1f42730693d9eca08cd1c0903031ef0c501ad7958337c62901a00e` |
| `next2-measure-2026-11-13-raw-cand-2.json` | 349 599 Б | `ec10fccde26bc90e9a48810541b58ba5139a3e19acccf080e1bbcbb69cf152a7` |
| `next2-measure-2026-11-13-raw.log.txt` (stdout четырёх прогонов) | 21 772 Б | `d09f6426da9785621d96616699e3a06d7185ae467c3110715e6a1fa91b28c641` |
| `next2-measure-2026-11-13-harness.py` (идентичен harness 12.11) | 20 019 Б | `ebfc79bd42725383587e6890f823f88ef9b824e5b6d6ca30775ebed35bf36517` |

Сырые JSON — полные трассы harness (per-question блоки/годы/пул/тайминги).
Одноразовый каталог прогона (4 производные копии БД, ~6,7 ГБ) не коммитится и
закрывается через `run-close` после передачи evidence; baseline worktree
`...aaecec2a` (чистый, detached 23477658) оставлен для воспроизведения Reviewer'ом.

## 8. Остаточное / границы

- **NEXT-02 остаётся FAILED/PENDING**: доля 2026 выше 58,1 % в обоих прогонах;
  причина не доказана (см. §5). Нужно решение Architect, не ослабление порога.
- **NEXT-05**: реализация и p95-attribution подтверждены на этой копии; до
  независимого review — не VERIFIED. Product telemetry в проде не читалась.
- Локальная rerank-модель/провайдер совпадают с замером 12.11, но идентичность
  production-env не перепроверялась (как и в прошлом отчёте); reranker
  стохастичен — состав блоков между прогонами различается.
- «По теме»: фиксированный знаменатель 18 из исходной выборки не совпадает с
  фактическим набором (10 различных строк); счёт 8 назван честно, без подмены
  знаменателя.
- Вне scope и не проверялись: NEXT-01 (реальный live-turn), NEXT-03/04,
  TIME-09, V-01..V-04; production не изменялся.

## 9. Findings

- `IN_SCOPE`: пункты 1–3 контракта реализованы; пункт про `database.py` не
  потребовался (предикат уже до LIMIT, доказано SQL-тестом). Риск: слот-приоритет
  не влияет на измеренную долю 2026 — возврат архитектору с трассой.
- `CRITICAL_OUT_OF_SCOPE`: нет.
- `BACKLOG_ONLY`: 5 падающих тестов `tests/test_direct_fallback_recompose_asap32.py`
  воспроизводятся на чистом `23477658`; не связаны с period fill; не правились.
