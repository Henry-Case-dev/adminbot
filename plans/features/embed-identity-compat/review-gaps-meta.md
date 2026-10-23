# EMBED-IDENTITY-COMPAT — независимое ревью дельты после `570e1eee`

**Лейн:** REV-EMBED-GAPS-META (read-only, только этот файл).
**Дата:** 2026-10-23 16:47 (UTC+12).
**Ветка/worktree:** `fix/embed-gaps`, `C:\Code\Python\adminbot-wt-gaps`.
**База:** `570e1eee` (последний код-коммит до дельты); мастер-база ветки `22cc3c14`.
**Кандидат:** `cf7e00e3` (HEAD).
**Дельта:** `69da031c` (тесты + CANARY-03), `b05052a5` (evidence), `cf7e00e3` (EMBED-META-WIRE); в диапазоне также docs-коммиты `22cc3c14..69da031c`, кода не меняли.

## Вердикт лейна

**PASS для дельты, без блокирующих дефектов.** Три PENDING (`IDENT-02`, `CANARY-03`, `DEC-09`) закрыты **по существу**; формально карта остаётся PENDING и `requirements_gate` красный — это работа PM/Orchestrator по привязке, не дефект кода. Дельту можно включать в поезд `2.58.113` после обновления карты/evidence; объявлять feature DONE по этому ревью нельзя.

## Приёмочный ledger

| Пункт | Статус дельты | Чем подтверждено |
|---|---|---|
| IDENT-02 | **VERIFIED (дельта)** | `tests/test_embed_identity_compat.py:861` меняет каждое из 7 полей MSI (`model/revision/dimension/task_mode/normalization/preprocessing_version/material_params`) и получает другой sha256[:16]; `:882` — стабильность при равных значениях, порядке `material_params`, `revision=None`≡`""` и явных дефолтах. 27/27 тестов файла. |
| CANARY-03 | **VERIFIED (дельта)** | `:922` — фактическая `model` из ТЕЛА ответа, revision/params/declared_dims; `:960` — явный `model_mismatch` → `incompatible` до числовых метрик; `:987` — нет revision/params → `revision_unknown`/`params_unknown` при `compatible`, не `insufficient`; `:1052` — мета берётся у владельца `embed_fn` (`last_embed_meta`), legacy-список векторов не ломается. Физический `dims` mismatch уже покрыт `scenario_04` (`:361-377`). 27+9 тестов. |
| DEC-09 | **VERIFIED (дельта)** | `:1079`: adopt → `status='building'`, `config_revision=NULL` → `_index_generation_ok=False`, `_vec_write_allowed=False`; `graph_facts_vec`/`graph_facts` counts не меняются; FTS отдаёт непустую выдачу; повторный adopt восстанавливает active/`adopt1:...`. |
| Контракт `embed()` | **VERIFIED** | Сигнатура/возврат `list[list[float]]`/исключения не менялись; добавлен только `last_embed_meta`; `_embed_response_meta` никогда не бросает. `tests/test_embed_meta_wire.py` 4/4. |
| Резолвер меты | **VERIFIED (код)** | `_probe_meta_owner` ищет у `__self__` и `owner.llm`, затем у явного `llm`; глобальное состояние другого клиента не читает; нет атрибута → `None`, прежнее поведение. Прод-вызовы: `summary_memory.py:2086-2089` (`self._compat_probe_embed` → `MemoryManager.llm`) и `graphrag_rebuild.py:2028-2031` (`memory._embed` → тот же `.llm`). |
| Риск №2 (конкурентные embed) | **Не блокирует** | Гонка может подменить `last_embed_meta` метой другого вызова. Ложного `compatible` это не даёт: решает числовая проба старых векторов + KNN-hit5; худший случай — ложный `model_mismatch` → fail-closed `incompatible` (без смешивания), возможна лишняя target-сборка при fallback/BYOK с другой моделью. Окно узкое; для текущего apinet модель в теле совпадает. |

## Прогоны (точечные, без полного suite)

| Команда | Результат |
|---|---|
| `pytest -q tests/test_embed_identity_compat.py tests/test_embed_identity_compat_restart_legacy.py tests/test_embed_meta_wire.py` | **40 passed** (27+9+4), 7.22 s |
| `pytest -q tests/test_llm_client.py` | **115 passed**, 3.31 s |
| `pytest -q tests/test_embedding_control_plane_asap4.py` (регресс control plane) | **69 passed**, 15.40 s |
| `pytest -q tests/test_graphrag_identity_reindex.py` (смежный seam) | **14 passed**, 9.01 s |

`pytest-timeout` в окружении нет (warning «Unknown config option: timeout»), поэтому `--timeout` не использовался; внешний лимит на файл ≤3 мин соблюдён.

## Формальный gate (не дефект дельты)

`requirements_gate.py check --stage review --slice IDENT-SPLIT|CANARY|DECISION --candidate cf7e00e3` → **FAIL**:
- `candidate mismatch`: в карте `candidate_commit=570e1eee`;
- `IDENT-02`, `DEC-09` (и CANARY-03) — `mandatory not ['VERIFIED'] (got PENDING)`;
- строгий gate требует evidence, привязанный к `cf7e00e3`; старые 54 строки привязаны к `570e1eee`, а хэши `tests/test_embed_identity_compat.py` устарели.

PM/Orchestrator должен: обновить `candidate_commit` на `cf7e00e3`, перевести три строки в `VERIFIED` с evidence на текущие файлы, перепривязать остальные evidence (или применить superset-политику gate) и прогнать release-gate. Текущие SHA256: `tests/test_embed_identity_compat.py` `b90c6f9afac617259d024592102eb646183bef8c9c489fd613ca0df1b7401e70`; `tests/test_embed_meta_wire.py` `41e2f4ff4a6976842545f01e4f7580188571b29df195cd8ba5d381b7919448e7`; `evidence/gaps-closure.md` `6e409050e1352bf7ca32010b0d04c274a0e0d5b43eb0cf93f6a7f73dec64111b`.

## Находки (все неблокирующие для дельты)

1. **Документальное расхождение (nonblocking):** `plan.md:32` говорит «если ревизия недоступна → `insufficient_data`», а реализация/тест осознанно дают `compatible` + `revision_unknown` (frozen `arch-design.md:12` — revision «если известна»; пороги §3 не включают revision; A0 на реальных данных уже принял compatible). Нужно обновить plan/binding или зафиксировать решение Architect, иначе следующий ревьюер увидит противоречие. Поведение не даёт ложного compatible: числовая проба обязательна.
2. **DEC-09, тест-хардненинг (nonblocking):** тест выставляет `status='building'`/`config_revision=NULL` SQL-ом, но не делает прямых `SELECT`-assertions по этим двум колонкам; проверяются следствия (`active is None`, гейты, counts, FTS, re-adopt). Для строгого evidence достаточно добавить 2 assertions.
3. **CANARY-03, покрытие (nonblocking):** новая ветка `declared_dims != dims` не имеет отдельного теста; в реальном wire `dims` выводится из тех же векторов, а физический dim mismatch покрыт `scenario_04`. Опционально: `_MetaEmbedder(dims_meta=DIMS+1)`.
4. **Остаточный риск (nonblocking):** `_normalized_model_name` не снимает датированный суффикс снапшота; провайдер, вернувший `...-2026-05-20`, даст ложный `model_mismatch`. Для текущего apinet тело ответа — ровно `gemini-embedding-001` (A0 `embed_calls.json`), автор риск зафиксировал. Лечится конфигом/мониторингом, не откатом.
5. **Конкурентность (nonblocking):** `last_embed_meta` — общий mutable-атрибут клиента; при одновременном fallback/BYOK-вызове с другой моделью возможен ложный `model_mismatch`. Ложного compatible нет (числовой гейт), но возможна лишняя сборка. Долгосрочно — передавать мету per-call, не в этой поездке.

## Границы ревью

Прод/SSH не использовались, код/карты/`current_task.md`/`progress_scope.json`/`workflow_state.md` не менялись. Проверены diff `570e1eee..cf7e00e3`, текущий код, тесты, evidence; воспроизведены указанные прогоны. Полный suite не запускался (не требуется для дельты).
