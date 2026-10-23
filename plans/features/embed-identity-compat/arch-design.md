# EMBED-IDENTITY-COMPAT — архитектура (дизайн, без реализации)

**ВЕРДИКТ: `ARCH_REUSE_CONFIRMED`** — границы существующих сервисов (`embedding_control_plane` + реестр поколений + canary + `embedding_cache`), **ΔDDL=0**, новых таблиц/сервисов/реестров нет; вопрос владельцу не требуется. Вход: `source-2026-10-23.md`, аудит `_audit-2026-10-23`.
Внешние источники не нужны: совместимость доказывается измерением на своих векторах, а не документацией провайдера.
Факты: прод `2.58.111`; primary `apinet.cloud/v1`, `gemini-embedding-001`, dim 3072; старые Google-векторы в `graph_facts_vec` = 16 003; `graph_facts` = 20 051 → 4 048 без векторов.
Реестр = 2 строки `building`/`activated_at=NULL` от 29.09 (fp `96f808…` против текущего `2d0efab0…`); любой новый fp → `ensure_current_generation` (5877810d) регистрирует `building` и запускает полный shadow-rebuild (≈316 вызовов / 2.4M токенов).

## 1. Две идентичности (каноническая реализация — в control plane)

| | **Model Space Identity (MSI)** | **Provider Connection Identity (PCI)** |
|---|---|---|
| Входит | `model`, `revision` (если известна), фактическая `dims`, `task_mode`, `normalization`, `preprocessing_version` (формат входа), материальные параметры генерации (сейчас `{}`: тело запроса `{"model","input"}`, `llm_client.py:1684`) | `provider_family`, `endpoint_host`, path без секретов, `credential_alias`, `quota_group` |
| Не входит | URL/host/ключ/квота/таймауты/маршрут | модель, размерность, параметры, нормализация |
| Смысл | **единственный критерий совместимости векторов** | провенанс, диагностика, инвалидация canary |
| Функции | NEW `model_space_identity(...)` (sha256[:16] канон-JSON, без host); `generation_space_identity(row)` — MSI из колонок `model/dims/preprocessing_version` + текущих констант | `profile_identity(profile)` **переопределяется** как PCI (`embedding_control_plane.py:2246`); ключ не читается, только alias |
| Хранение и сравнение | уже есть (колонки поколения; допуск — `config_revision`, §6); MSI==MSI и dims==dims | уже есть (`provider`, `endpoint_fingerprint`, `namespace`, `config_revision`); PCI==PCI **сам по себе никогда не закрывает индекс** |

`embedding_identity_fingerprint()` (`summary_memory.py:432`) и `_identity_fingerprint()` (`:1827`) **не меняются байт-в-байт**: это legacy-полная идентичность (`host|model|dims|preproc|endpoint`), она остаётся fingerprint'ом реестра (провенанс) и ключом `embedding_cache` — иначе обнуляется весь кэш.
`_embed_cache_key/_lookup/_store` не трогаем: старые строки живут до TTL (30 дн.), новые пишутся под новый fingerprint, недостающие векторы добирает существующий `backfill_graph_fact_vectors`; кэш не чистится и не мигрируется.

## 2. Точки согласования: одно решение читается всеми

Единый резолвер **`ecp.resolve_index_compat(db, index_name, *, allow_probe=False)`** (реестр + `config_revision`; сеть только при `allow_probe`) возвращает
`{state, reason_code, serviceable, space, conn, admission, canary, source_empty, needs_probe}`, где `state ∈ compatible | insufficient | incompatible | source_empty | no_generation`.

| Точка | Что читает | Что решает |
|---|---|---|
| `summary_memory._index_generation_ok` (`:1877`) + `_vec_write_allowed` (`:1981`) | ACTIVE-строку + `generation_space_identity` + допуск (+ drift-canary) | True если `fp==current` **или** (`space==space_now` и допуск валиден); URL не сравнивается; mixed-space по-прежнему запрещён |
| `summary_memory._register_index_generations` (`:1837`) | резолвер до `ensure(...)` | при валидном допуске новое `building` не регистрируется |
| `ecp.profile_identity` / `classify_identity_compatibility` (`:2246`/`:2264`) | MSI/PCI/dims/вердикт/допуск | PCI перестаёт быть identity пространства; классы: `INSTANT_COMPATIBLE` (fp равны), **NEW `ADMITTED_COMPATIBLE`**, `REINDEX_REQUIRED` (space различается), `INCOMPATIBLE_DIMENSION`, `COMPATIBILITY_UNKNOWN` |
| `ecp.embedding_canary_check` (`:2314`) | 3 frozen-строки в `embedding_cache` | остаётся drift-детектором; доказательством совместимости со старым индексом не является |
| `graphrag_rebuild.ensure_current_generation` (`:1699`) | резолвер | compatible → adopt (None); insufficient → **ничего не регистрировать**; incompatible → target-generation |
| `graphrag_rebuild.maybe_schedule_rebuilds` (`:1895`) | резолвер до `_ensure_job` | compatible/insufficient/`source_empty` → пропуск; иначе текущий D2-путь |
| `graphrag_rebuild.generation_status` (`:1783`) | резолвер | `compat_insufficient`, `serviceable`, `action`; «identity_changed» не врёт при смене только шлюза |
| `ecp.vector_memory_panel` (`:1982`; баг `:2072` — 16-hex PCI против 64-hex fp) | тот же резолвер | блок `compat` в существующем ответе `memory_agi.py:500` (класс, метрики, reason, action) |

## 3. Canary: доказательство на СТАРЫХ векторах

1. **Предусловия** (иначе `insufficient`, без сети): строка-кандидат с `generation_space_identity(row)==space_now`; live непуста; векторы принадлежат старому fp (запись после смены шлюза была невозможна — все write-пути идут через `_vec_write_allowed`: `:2512/:3699/:5316`); `source_empty` → канарейка не нужна.
2. **Выборка** — только старые векторы и их исходные тексты: `graph_facts_vec JOIN graph_facts` (eligible по `expires_at`), детерминированно (без `RANDOM`): по каждому `chat_id` каждая `ceil(n/6)`-я строка, ≤6 на чат, всего **12** (min 8);
   бакеты длин ≥3 (<200), ≥3 (200–1999), ≥2 (≥2000) и только при `estimate_tokens(text)<=2000` (иначе включится сегментация, `ecp:1430`); дубли по `casefold(strip)` схлопываются.
3. **Новый вектор** — тем же serving-путём (`execute_embed`/`_embed`, P2), один батч; **эталоны новым провайдером не создаются**: сравнение только со старыми строками индекса.
4. **Метрики:** `cos(new, old)` по float-колонке `embedding` (не `embedding_i8`), чтение существующим `graphrag_rebuild._read_vector` (`:816`; `SELECT rowid, embedding` уже используется на `:986`);
   и **обязательная проверка поиска** — те же новые векторы как запросы к СТАРОМУ индексу `SELECT rowid FROM graph_facts_vec WHERE embedding MATCH ? AND k=5` (форма — `:1025`), `hit5` = доля запросов, чей `fact_id` в top-5. Новое-с-новым исключено: индекс старый.
5. **Пороги (frozen в коде, не hot-config):** compatible — `checked>=8`, dims совпали, `mean>=0.995`, `min>=0.990`, `hit5>=0.80`; incompatible — dim mismatch, либо `mean<0.970`, либо `min<0.940`, либо `hit5<0.40`; иначе insufficient (`weak_numeric|low_hit5|too_few_vectors|api_unavailable|no_old_vectors|provenance_unknown`).
   Полоса `0.970≤mean<0.995`: **один** независимый повтор на другой выборке, compatible — только если оба прогона compatible.
6. **Обоснование порогов:** cosine масштабно-инвариантен, сравниваются float32 одного пространства; 0.995 даёт ~100× запас на округление и отсекает чужую ревизию/квантование. **Недоступность API/мало данных** → insufficient (никогда incompatible), индекс/факты/кэш целы.
7. Hot-path без сети: `_index_generation_ok` только читает; probe — из `initialize()` (после `_register_index_generations`, **до** `_recover_runtime_jobs`/backfill) и из тика, под process-`asyncio.Lock`. Пока вердикта нет, уже запущенная сборка под новый fp **ставится на паузу** (`pause_rebuild`, обратимо) — 316 вызовов не сжигаются до решения; после compatible она отменяется (§7), после incompatible — `resume_rebuild`.

## 4. Три исхода — точные действия

**compatible:** adopt (§5) → ACTIVE = старый fp + допуск; `_index_generation_ok/_vec_write_allowed = True`; новые записи и поиск через новый API в тот же индекс;
backfill добирает 4 048 фактов (≈81 вызов), **полного rebuild и повторного извлечения фактов нет**, кэш/векторы не удаляются; событие `EMBEDDING_COMPAT_ADMITTED` + метрики в панель.

**insufficient:** не объявляем и не активируем; target-generation **не регистрируется**, rebuild не стартует; live/факты/кэш/старые `building`-строки сохранены (откат = текущее состояние); поиск FTS;
`generation.state=compat_insufficient`, `serviceable=false`, `action=retry_canary|need_old_vectors`, reason+remediation; `EMBEDDING_COMPAT_INSUFFICIENT` (warning, коалесинг).

**incompatible:** в live не пишем; существующий контролируемый путь — `register_embedding_target_generation` (`database.py:5993`) → shadow `{live}_g{gen}` → `_validate` → `_activate` (`:1057`, одна транзакция),
старый ACTIVE сервит до promotion; переэмбеддиваются только `graph_facts.fact`, без re-extract; resume/checkpoint/lease/pauses — существующие; `EMBEDDING_COMPAT_INCOMPATIBLE` (error).

## 5. Как «принять» существующий индекс

1. Кандидат — `db.get_generation_by_fingerprint(index, old_fp)` (в проде `96f808…`, status `building`); строки нет → insufficient (провенанс неизвестен, не выдумываем).
2. Новый DB-метод `adopt_embedding_generation(index_name, fingerprint, *, admission, namespace='default')`: в одной `serialized()`-транзакции проверяет отсутствие другого ACTIVE (partial UNIQUE `idx_mca_eig_active_ns`, `database.py:499`), ставит `status='active'`, `activated_at=now`, `config_revision=<допуск>`;
   `fingerprint`/`provider`/`endpoint_fingerprint` **не перезаписываются** (провенанс: векторы построены старым подключением). Непарсимый старый `config_revision` → отказ.
3. Затем `supersede_building_generations(keep_fingerprint=adopted_fp)` (`database.py:6052`) и `cancel_rebuild` (§7).
4. KNN работает сразу: live/DDL/dim не меняются; `_index_generation_ok=True` по допуску, backfill пишет в ту же таблицу.
5. Провенанс — уровень таблицы: «16 003 строк = старое подключение; далее ≥`at` = admitted»; per-row в vec0 нет и не создаётся. Повторный adopt идемпотентен (no-op).

## 6. Персистентность вердикта (без новой таблицы)

`mca_embedding_index_generations.config_revision` ACTIVE-строки: `adopt1:<space16>:<conn16>:<checked>:<mean>:<min>:<hit5>:<at>` (строгий regex; мусор → игнор, fail-closed). Durable, читается в `_EGEN_ROW_COLS` (`database.py:5836`) без новых запросов.
Инвалидация: валидно только при `space16==space_now` и `conn16==conn_now`; смена модели/размерности/preprocessing/параметров меняет `space_now` → игнор (fail-safe), settled-допуск не пересчитывается на старте.
Отвергнуто: `task_jobs` (prune терминальных), `embedding_cache`-маркер (TTL 30 дн./LRU 20k — вердикт исчезнет, JSON в vector-колонке хрупок), `smart_cache`/`channel_state` (чужая семантика, чистятся), новые таблицы (запрещены).
Негативные вердикты не сохраняются: insufficient перепроверяется раз за старт/тик (1 батч), incompatible и так требует target-generation.

## 7. Отмена уже запущенного rebuild (сценарий 9)

Порядок строгий: (1) canary+adopt (иначе тик переоткроет джобу — B1-фикс 5877810d); (2) `cancel_rebuild` (`:2190`, CAS в `cancelled`; `run_job` проверяет статус на границе батча `:1298-1303` и сам делает `_drop_shadow` — удаляется только производная shadow);
(3) `supersede_building_generations(keep=adopted)`; (4) `EMBEDDING_COMPAT_REBUILD_CANCELLED` с `processed`.
Безопасно при любом прогрессе: shadow не активируется, `_activate` не вызывается, live цел. Если сборка уже активирована (`ACTIVE.fp==current`) — отменять нечего, канарейка не запускается.

## 8. Тест-план (10/10)

Фикстура `vec_db` (temp SQLite + sqlite-vec + реальный реестр; паттерн `tests/test_graphrag_identity_reindex.py`); векторы `vec_for(text, space, noise)` детерминированно из sha256-сида. Мокается **только** `embed_fn` (HTTP); **нельзя** мокать `_cosine`, KNN/SQL, транзакции реестра, `_index_generation_ok`.

| # | Проверка | PASS |
|---|---|---|
| 1 | та же модель/space, новый host | adopt; write allowed; новых job/generation нет; класс `ADMITTED_COMPATIBLE` |
| 2 | новое = старое + шум 1e-3 / полоса ~0.99 | (а) adopt; (б) insufficient + один повтор; повтор не апгрейдит |
| 3 | то же имя модели, другое пространство | incompatible; target+job; до promotion запись запрещена |
| 4 | другая модель / другая dims | space mismatch / `INCOMPATIBLE_DIMENSION`; adopt нет; live не смешан |
| 5 | `embed_fn` бросает / нет vec | insufficient; реестр/live/shadow не изменены; `action` заполнен |
| 6 | A→B→A | после adopt B и возврата A: serviceable по `fp==current`, `embed_fn` не вызван |
| 7 | рестарт (новый MemoryManager, пустой process-кэш) | допуск из `config_revision`; `embed_fn` calls=0; новых поколений/джоб нет |
| 8 | два чата | выборка покрывает оба `chat_id`; ровно один adopt на индекс; `chat_id` векторов не меняются |
| 9 | running job + adopt | job `cancelled`, target `superseded`, adopted `active`, live count неизменен, тик `scheduled=[]` |
| 10 | семантика на реальных данных | live-проба (12 реальных фактов, apinet): `hit5>=10/12`, `mean>=0.995`; мок запрещён |

## 9. Минимальный дифф, риск, порядок

Меняем: `embedding_control_plane.py` — новые `model_space_identity`, `generation_space_identity`, `connection_identity`, `parse/format_admission`, `compat_probe`, `resolve_index_compat`; переопределить `profile_identity`/`classify_identity_compatibility`; блок `compat` в `vector_memory_panel`.
`summary_memory.py` — `_index_generation_ok`, гейт в `_register_index_generations`, skip в `_schedule_canary_probe`, inline-probe в `initialize`. `graphrag_rebuild.py` — `ensure_current_generation`, `maybe_schedule_rebuilds`, `generation_status`.
`database.py` — +`adopt_embedding_generation` (одна транзакция). `web/api/memory_agi.py` — проброс без нового роута.
Тесты: новый файл + 3 существующих (`test_asap5_embedding_identity`, `test_graphrag_identity_reindex`, `test_webapp_memory_overview_api`).
**НЕ трогаем:** `embedding_identity_fingerprint`, `_identity_fingerprint`, `_embed_cache_*`, DDL/schema/версии, строки `embedding_cache`, `_validate`/`_activate`, lease/pauses/kill-switch, `plans/*`, прод/SSH.
Порядок: **A0** — read-only прогон probe на 12 реальных прод-фактах (без деплоя, без изменения поведения) → подтвердить `mean/min/hit5` и пороги; **B** — один деплой: identity-функции + probe + гейты + допуск под kill-switch `EMBED_COMPAT_ADOPTION_ENABLED` (default ON; OFF = прежнее поведение, включая авто-rebuild); probe гарантированно до планировщика, сборка до вердикта на паузе; **C** — MiniApp-тексты (зависимый слой).
Риск **R2**: ложный adopt смешает пространства; сдерживание — `min` чувствителен к загрязнённой таблице, purity-by-write-gate, откат = снять допуск (`status='building'`, `config_revision=NULL`) → FTS-only, векторы целы, rebuild штатно.

## 10. Параллельность и приёмка

`ecp` — single-writer; `summary_memory`+`graphrag_rebuild`+`database.py` — **SERIALIZE** (общий контракт резолвера); `web/api` — PARTIAL_SAFE после заморозки имён полей; тесты — PARALLEL_SAFE; MiniApp UI — `BLOCKED_BY:api-contract-freeze`.
Живая приёмка: `GET /api/memory/embeddings` → `compat.serviceable=true`, `compat.canary.mean/min/hit5`, `generation.state`; лог `EMBEDDING_COMPAT_ADMITTED`; backfill 4 048 → 0; `_vec_write_allowed=True`; сценарий 10 — на реальных фактах.

**Handoff:** feature `embed-identity-compat`; вопрос владельцу не требуется; следующее действие — Builder по §9 (A0 → B) после картирования PM. Frozen: MSI/PCI-функции, формат `adopt1:`, поля `resolve_index_compat`, пороги §3.
