# EMBED-IDENTITY-COMPAT — закрытие трёх PENDING (IDENT-02, CANARY-03, DEC-09)

Дата: 23.10.2026. Лейн `EMBED-IDENTITY-GAPS2`.
Ветка: `fix/embed-gaps`, worktree `C:\Code\Python\adminbot-wt-gaps`, база `22cc3c14` (master).
Основной чекаут не тронут. Пуш/merge не выполнялись.

## Что изменено

### 1. IDENT-02 — MSI по каждому полю identity (только тесты)

`tests/test_embed_identity_compat.py`:

- `test_ident_02_msi_changes_with_every_identity_field` (L861) — поочерёдная
  замена `model`, `revision`, `dimension`, `task_mode`, `normalization`,
  `preprocessing_version`, `material_params` даёт ДРУГОЙ
  `model_space_identity()` (sha256[:16]).
- `test_ident_02_msi_stable_for_equal_values_and_param_order` (L882) —
  одинаковые значения дают одинаковый MSI: порядок ключей
  `material_params`, `revision=None` ≡ `revision=""`, явные значения
  по умолчанию (`task_mode`/`normalization`/текущий
  `preprocessing_version`/пустые `material_params`) совпадают с дефолтным
  вызовом.

Код MSI (`services/embedding_control_plane.py::model_space_identity`, L2495)
не менялся — он уже включал все поля; добавлено покрытие, а не поведение.

### 2. CANARY-03 — фактические метаданные ответа провайдера

`services/embedding_control_plane.py`:

- `_split_probe_response` (L2947) — эмбеддер (`embed_fn`) или `llm`
  (`last_embed_meta`) может вернуть `{"vectors", "model", "revision",
  "params", "dims"}`; legacy список векторов трактуется как «метаданные
  недоступны», а не как ошибка.
- `_normalized_model_name` (L2977) — сравнение имён без регистра/пробелов/
  префикса `models/`.
- `_probe_metadata_block` (L2985) — фактическая `model` из ответа,
  `model_expected` (конфиг), `revision`/`params` + флаги известности,
  `declared_dims` против физических `dims`.
- `_probe_metadata_reason` (L3012) — `revision_unknown` / `params_unknown`
  как ИНФОРМАЦИОННЫЙ код при `verdict=compatible` (не `insufficient`).
- `_compat_probe_once` (L3025): метаданные пишутся в `out["metadata"]`
  (L3083); явное несовпадение фактической `model` с заявленной →
  `incompatible` / `model_mismatch` ДО числовых метрик (L3086-3091);
  заявленная размерность ≠ физической → `incompatible` / `dim_mismatch`
  (L3092-3095); compatible сохраняет информационный код (L3143).
- `compat_probe` (L3150): подтверждающий повтор полосы также сохраняет
  информационный код метаданных (L3191), а не обнуляет его.
- `ensure_index_compat` (L3635): блок `compat["canary"]["metadata"]`
  (L3712) — фактическая model/revision/params едут вместе с вердиктом.

Тесты (`tests/test_embed_identity_compat.py`):

- `test_canary_03_probe_records_actual_metadata` (L922) — `model` берётся
  из ответа (`" Models/gemini-embedding-001 "`), `revision=2026-09-01`,
  `params`, `declared_dims`/`dims`; `reason_code=""`; adopt отдаёт
  `canary.metadata`.
- `test_canary_03_explicit_model_mismatch_is_incompatible` (L960) — векторы
  совпадают (space-a), но фактическая `model=text-embedding-004` →
  `incompatible`/`model_mismatch`, активного поколения нет, live-векторы
  целы.
- `test_canary_03_missing_revision_or_params_not_insufficient` (L987) —
  нет revision → `revision_unknown`; revision есть, params нет →
  `params_unknown`; оба случая `verdict=compatible` и adopt проходит
  (`config_revision=adopt1:...`), т.е. НЕ `insufficient`.

### 3. DEC-09 — откат допуска (только тест)

`tests/test_embed_identity_compat.py`:
`test_dec_09_rollback_after_adopt_keeps_data_and_is_reversible` (L1025):

1. adopt (`state=compatible`, `config_revision=adopt1:...`,
   `_vec_write_allowed=True`);
2. откат строки поколения: `status='building'`, `config_revision=NULL`;
3. `_index_generation_ok=False` (vec-поиск закрыт), `_vec_write_allowed=False`;
4. `graph_facts_vec` и `graph_facts` — те же количества;
5. FTS-путь отдаёт непустую выдачу (`search_graph_facts_fts`, chat 101);
6. повторный adopt восстанавливает `active` + `adopt1:...`,
   `_index_generation_ok=True`, `_vec_write_allowed=True`, счётчики те же.

`services/graphrag_rebuild.py` НЕ менялся: DEC-09 закрывается существующим
откатом реестра (UPDATE статуса/revision) + резолвером.

## Прогоны (точечные, `-q -x`, без сети/e2e)

`pytest-timeout` в окружении отсутствует (`ModuleNotFoundError`), поэтому
`--timeout` не добавлялся; каждая команда ограничена внешним лимитом 180 с.

| Файл | Результат | Время |
|---|---|---|
| `tests/test_embed_identity_compat.py` | **26 passed** (было 20; +6) | 21.1 с (25.4 с с запуском) |
| `tests/test_embed_identity_compat_restart_legacy.py` | **9 passed** | 3.6 с (4.4 с с запуском) |

`test_graphrag_identity_reindex.py` не запускался: `services/graphrag_rebuild.py`
не изменялся.

## Доказательство по пунктам карты

- IDENT-02: покрыты все MSI-поля (`revision/task_mode/normalization/
  preprocessing/material_params` + уже бывшие model/dims), тесты L861/L882.
- CANARY-03: проба возвращает фактические model/revision/params; явное
  расхождение model и dims → `incompatible`; отсутствие revision/params →
  `revision_unknown`/`params_unknown` при `compatible`, не `insufficient`
  (тесты L922/L960/L987).
- DEC-09: откат допуска не теряет векторы/факты, vec закрыт, FTS работает,
  повторный adopt успешен (тест L1025).
