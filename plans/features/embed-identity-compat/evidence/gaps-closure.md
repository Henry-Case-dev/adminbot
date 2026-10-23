# EMBED-IDENTITY-COMPAT — закрытие 3 PENDING (IDENT-02 / CANARY-03 / DEC-09)

**Лейн:** `EMBED-IDENTITY-GAPS` (writer).
**Дата:** 2026-10-23.
**Код-кандидат (релизная линия 2.58.113):** тесты/гейты — d62e9720, мета-проводка — ddf139a1; SHA изменились после черри-пика в поезд.
**Карта требований:** не менялась (владелец карты — PM); статусы `PENDING` снял бы PM после ревью.
**ΔDDL = 0:** `services/database.py` не изменялся; новых таблиц/колонок/миграций нет.

## Что сделано

### 1. IDENT-02 — MSI чувствителен к каждому полю identity (source L13)

Требование: identity = модель, доступная ревизия/версия, размерность, режим,
нормализация и параметры препроцессинга. Ранее были покрыты только `model`/`dims`.

Добавлены unit-тесты (`tests/test_embed_identity_compat.py`):

| Тест | Что доказывает | Строка |
|---|---|---|
| `test_msi_changes_with_every_identity_field` | поочерёдное изменение `model` / `revision` / `dimension` / `task_mode` / `normalization` / `preprocessing_version` / значения и ключа `material_params` даёт ДРУГОЙ 16-hex MSI; разные поля не схлопываются в один digest | `tests/test_embed_identity_compat.py:898` |
| `test_msi_same_values_same_digest_regardless_of_format` | одинаковые значения → одинаковый MSI; порядок `material_params`, пробелы, `str/int` не дают ложных различий; вызов детерминирован | `:926` |
| `test_msi_default_preprocessing_version_is_factual` | `preprocessing_version=None` резолвится в ФАКТИЧЕСКУЮ версию (`summary_memory.EMBEDDING_PREPROCESSING_VERSION`), смена версии меняет MSI | `:942` |

Мутационная проверка: при удалении `revision` из payload `model_space_identity`
(`services/embedding_control_plane.py:2537`) тест падает с
`AssertionError: поле revision не влияет на MSI`. Код возвращён, дерево чистое.

### 2. CANARY-03 — проба фиксирует фактические model/revision/params (source L28)

Требование: сверить фактическую размерность, модель, доступную информацию о
версии и параметры генерации. Решение владельца (в brief): метаданные
фиксируются там, где доступны; **решает** сравнение старых векторов + KNN-hit.

Реализация (`services/embedding_control_plane.py`):

* `MODEL_SOURCE_RESPONSE|REQUEST|UNKNOWN`, `META_AVAILABLE`,
  `META_MODEL_UNKNOWN`, `META_REVISION_UNKNOWN`, `META_PARAMS_UNKNOWN`,
  process-канал `_LAST_EMBED_META` (ContextVar) — `:2468-2490`.
* Фактическая модель реально выбранного слота записывается в
  `EmbeddingExecutor.embed` после успешного батча (fallback-слот может быть
  настроен на другую модель — это и есть фактическая генерация, а не конфиг):
  `:1373`.
* `_split_embed_result` — embed-функция может вернуть `(vectors, meta)` (ответ
  провайдера/адаптера) либо прежний `list` (метаданных нет): `:2812`.
* `_generation_metadata` / `_apply_metadata` — R17-safe блок
  `{model, model_source, model_status, revision, revision_status, params,
  params_status}` в вердикте пробы (вложенно + плоские поля): `:2828`, `:2859`.
* `_normalized_model` — `models/gemini-…` и `gemini-…` не дают ложного mismatch;
  регистр/пробелы нормализуются: `:2821`.
* `_compat_probe_once(expected_model=…)`: порядок решений — `dims` mismatch →
  `incompatible/dim_mismatch`; **явное несовпадение фактической модели →
  `incompatible/model_mismatch`** (даже при численно совпавших векторах);
  недоступные revision/params — только фиксация `*_unknown`: `:3040-3118`.
* `compat_probe(expected_model=…)` — проброс в оба прогона; mismatch во втором
  прогоне не деградирует в `insufficient`, а остаётся `incompatible`: `:3174`.
* `ensure_index_compat` — ожидаемая модель берётся из candidate-строки
  (провенанс live-векторов), а метаданные попадают в `canary` (`metadata`,
  `dims`): `:3738`, `:3751`.
* `_admission_canary` — durable-допуск `adopt1:…` (frozen формат §6) не хранит
  метаданные, поэтому панель честно получает `*_unknown`, а не выдуманное
  «совпало»: `:2868`.

Тесты (`tests/test_embed_identity_compat.py`):

| Тест | Что доказывает | Строка |
|---|---|---|
| `test_canary03_response_model_mismatch_is_incompatible` | провайдер вернул `text-embedding-004` при заявленной `gemini-embedding-001`: `incompatible/model_mismatch`, `model_source='response'`, adopt нет, `hit5=None` (численное сравнение не подменяет доказательство), запускается штатная миграция | `:970` |
| `test_canary03_unknown_revision_params_do_not_block_compatible` | модель есть, `revision`/`params` недоступны → `revision_unknown`/`params_unknown`, вердикт `compatible`, adopt работает (сценарий смены шлюза не блокируется) | `:1003` |
| `test_canary03_available_metadata_is_recorded` | доступные `revision`/`params` записываются как есть; `models/gemini-…` — та же модель | `:1036` |
| `test_canary03_all_metadata_unknown_with_weak_vectors_is_insufficient` | все метаданные недоступны + слабая векторная проверка (полоса/повтор не подтвердил) → `insufficient`, vec-запись закрыта, данные целы | `:1061` |
| `test_canary03_control_plane_records_actual_routed_model` | request-level канал: `EmbeddingExecutor` с fake `LLMClient.embed_once`; модель фактического credential’а попадает в вердикт (`model_source='request'`); credential на другой модели → `incompatible/model_mismatch` | `:1087` |

Мутационная проверка: при отключении проверки модели
(`services/embedding_control_plane.py:3110-3117`) падают
`test_canary03_response_model_mismatch_is_incompatible` и
`test_canary03_control_plane_records_actual_routed_model` (2 failed). Код
возвращён.

### 3. DEC-09 — откат допуска обратим, данные целы (source L54)

Добавлен тест `test_dec09_admission_rollback_keeps_index_and_facts`
(`tests/test_embed_identity_compat.py:1164`), фикстура с настоящим FTS —
`_seed_with_fts` (`:1136`), реальные SQLite + sqlite-vec, мок только HTTP-embed.

Сценарий (документированная процедура отката — две колонки):

1. adopt при смене шлюза → `compatible`, `_vec_write_allowed=True`,
   `_index_generation_ok=True`, FTS непустой.
2. `UPDATE … SET status='building', config_revision=NULL WHERE status='active'`.
3. Наблюдения: ACTIVE нет; `resolve_index_compat → insufficient/compat_not_proven`,
   `serviceable=False`; `_index_generation_ok=False`;
   `_vec_write_allowed=False` (vec закрыт, FTS-only); авто-rebuild не стартует
   (`_find_active_job is None`, `ensure_current_generation is None`).
4. Целостность: снимок `graph_facts_vec` (`rowid/fact_id/chat_id/embedding`)
   побайтно равен, `graph_facts` = 20, поколение одно;
   `search_graph_facts_fts` возвращает непустую выдачу.
5. Обратимость: повторный `ensure_index_compat` → `compatible`, ACTIVE снова с
   `adopt1:…`, `_vec_write_allowed=True`, новых поколений нет, векторы те же.

## Прогоны (Windows, локальный `.venv`, Python 3.12.0, pytest 9.1.1)

| Набор | Результат |
|---|---|
| `tests/test_embed_identity_compat*.py` (новые + прежние) | **38 passed** (6.97 s) — 29 прежних + 9 новых |
| Смежный набор: contract + restart + asap5 identity + asap6 generations + graphrag identity + webapp memory API + mca01 tx supervisor | **125 passed** (22.92 s) — 116 прежних + 9 новых |
| Контрол-плейн/смежные: `test_embedding_control_plane_asap4` + `test_mca07_retrieval_context_round1027` + `test_graphrag_rebuild_asap32` + `test_summary_memory` | **200 passed** (22.04 s) |
| Новые тесты отдельно (`-k "msi or canary03 or dec09"`) | **9 passed** (3.66 s) |

`ΔDDL = 0`: в диффе кандидата только `services/embedding_control_plane.py`,
`tests/test_embed_identity_compat.py` и этот evidence; `services/database.py`
не тронут.

## Риски и ограничения

1. Метаданные доступны не всегда: legacy `llm.embed` (пустой пул ключей) и
   батч, целиком обслуженный `embedding_cache`, не проходят через
   `EmbeddingExecutor` → `model_unknown`. Это соответствует решению владельца:
   совместимость доказывают старые векторы + KNN, а не имя модели.
2. Сравнение модели строгое (после нормализации `models/`/регистр/пробелы):
   провайдер, отдающий другой alias для тех же весов, будет помечен
   `incompatible/model_mismatch` — так требует решение «явное несовместимость
   модели → incompatible»; обход — конфиг/перепроба, не тихий adopt.
3. Durable-допуск (`adopt1:…`) метаданные не хранит (frozen формат §6):
   панель после рестарта показывает `*_unknown` до следующей пробы.
4. `_LAST_EMBED_META` — ContextVar: канал работает, пока embed вызывается в той
   же задаче (текущий путь `_embed → execute_embed`); вынос embed в отдельную
   задачу/поток потребует явной передачи `(vectors, meta)` от callable.
5. DEC-09 проверяет поведение отката, а не новый «revoke»-метод: откат
   выполняется двумя колонками SQL (как в §8 review R2), отдельного API нет.
6. Карта требований не редактировалась: строки `IDENT-02/CANARY-03/DEC-09`
   остаются `PENDING` до решения PM/Reviewer; evidence приложен для привязки.
