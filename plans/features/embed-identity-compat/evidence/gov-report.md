# EMBED-IDENTITY-COMPAT — GOV-аудит диффа (GOV-01…GOV-07)

Кандидат: ветка `master`, рабочее дерево лейна `EMBED-IDENTITY-IMPL`
(коммит — см. `report.md` §«Кандидат»).
Скоуп аудита: `services/embedding_control_plane.py`,
`services/summary_memory.py`, `services/graphrag_rebuild.py`,
`services/database.py`, `web/api/memory_agi.py`, тесты лейна.

## GOV-01 / GOV-06 — нет новых подсистем

* Новых файлов-сервисов нет: дифф затрагивает только существующие сервисы.
* Новых таблиц/колонок/миграций нет: `ΔDDL = 0`, `user_version` не менялся,
  `_MCA_*_DDL` не тронуты.
* Параллельного реестра моделей нет: идентичности вычисляются функциями
  (`model_space_identity`, `connection_identity`) поверх существующих колонок
  `mca_embedding_index_generations` (`model`, `dims`,
  `preprocessing_version`, `config_revision`).
* Новых агентов/планировщиков нет: проба вызывается из существующего
  `MemoryManager.initialize()` и существующего тика
  (`maybe_schedule_rebuilds`).
* Переиспользованы: существующий control plane, canary-инфраструктура
  (`_cosine`, `embedding_cache` — только как drift-детектор), система
  поколений (`register_embedding_target_generation`, `_validate`,
  `_activate`, `cancel_rebuild`, `supersede_building_generations`).

## GOV-02 — нет хардкода под API.NET/Gemini

* В коде нет строк `apinet`/`API.NET`/`gemini` в логике совместимости
  (только существующие константы профилей и `_is_gemini_endpoint` для
  адаптера, не тронутые лейном).
* `connection_identity` строится из `urlsplit(base_url)` (host/path) и
  профиля (alias/quota group); провайдер-специфичных ветвей нет.
* `model_space_identity` использует только переданные model/revision/dims/
  task/normalization/preprocessing/params.
* Тесты используют произвольные `*.test`-хосты (`old-gateway.test`,
  `apinet.cloud` только как метка нового шлюза, не как логика).

## GOV-03 — совместимость не по имени модели

* `resolve_index_compat` не возвращает `compatible` по равенству `model`:
  нужен либо точный fingerprint, либо валидный durable-допуск, полученный
  пробой на старых векторах (косинус + KNN-hit5).
* `test_scenario_03_same_name_different_space_is_incompatible`: одинаковое
  имя модели + другие векторы → `incompatible` (`low_hit5`, mean 0.151,
  hit5 0.25 на фикстуре).
* `test_antitheorem_new_vs_new_cannot_prove_compatibility`: эталоны нового
  провайдера (embedding_cache) не дают `compatible`.

## GOV-04 — защиты не отключены

* `embedding_identity_fingerprint()` / `_identity_fingerprint()` не изменены
  (git diff по этим функциям пуст); `_embed_cache_*` не тронуты.
* `_validate`, `_activate`, `RebuildLease`, pause/resume, kill-switch
  `GRAPHRAG_SHADOW_REBUILD_ENABLED`, quota-group/kill-switch'и control plane
  не изменены.
* Принудительного «все векторы совместимы» нет: adopt возможен только после
  пробы, удовлетворяющей frozen-порогам, и только для строки-провенанса
  старого индекса; при `insufficient`/`incompatible` активации нет.
* `_vec_write_allowed` по-прежнему запрещает mixed-space запись и учитывает
  canary DRIFT.

## GOV-05 — нет потери истории/фактов/графа/досье

* `adopt_embedding_generation` делает только `UPDATE` одной строки реестра
  (`status`, `activated_at`, `config_revision`); `DELETE`/`DROP` нет.
* Отмена rebuild удаляет только производную shadow-таблицу (существующий
  `run_job`/`_drop_shadow`); live и source-факты не трогаются.
* Тесты сверяют счётчики: `graph_facts`, `graph_facts_vec`,
  `mca_embedding_index_generations` до/после adopt, при insufficient и при
  отмене сборки (`test_scenario_01/03/05/08/09`).
* `report.md` §4: после всех проб на фикстуре live=20, source=20,
  поколений=1.

## GOV-07 — очередь/штатный workflow

* Задача проведена штатным workflow: Architect (`arch-design.md`,
  `ARCH_REUSE_CONFIRMED`) → PM (`requirements-map.json`, `slice-graph.json`)
  → Builder (этот лейн) → Reviewer/DevOps.
* `plans/current_task.md`, `requirements-map.json`, `plans/progress_scope.json`
  не изменялись Builder'ом.

## Остаточные замечания (не блокируют)

1. `embedding_cache` остаётся keyed по legacy-полной identity (включая host):
   после смены шлюза старые строки живут до TTL и не используются — это
   ожидаемо (кэш не чистится и не мигрирует, как заморожено дизайном §1).
2. Фоновая drift-canary (`embedding_cache`, 3 строки) — по-прежнему
   new-vs-new по своей природе; она не участвует в доказательстве
   совместимости и гейтится на время незавершённого вердикта.
