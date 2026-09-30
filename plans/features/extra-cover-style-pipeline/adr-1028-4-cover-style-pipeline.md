# ADR-1028-4 — Modular Cover Styles / Branded Cover Pipeline (EXTRA)

- **Статус:** **Accepted — прод-валидирован 2.58.39; Merge в `plans/ARCHITECTURE.md` §105 (reconcile @Architect, 30.09.2026).** История статуса — §8.
- **Фича:** `extra-cover-style-pipeline` (prefix `EXTRA`). **Эпик:** `memory-context-autonomy`.
- **Дата:** Step 2 @Architect (round 10.28+). **Следующий свободный ADR после ADR-1028-3.**
- **Связанные:** ADR-1027-9 (D13 — бронь v20), ADR-1027-1 (mca-14 registry), ADR-1027-3 (task_jobs), ADR-1027-8 (observability), ADR-1026-17 (A5 PG-DDL `image_reservation`), ADR-1024-4 (image payload/compat), ADR-1023-5 (image module), ADR-1023-6 (cover prompt), ADR-1025-7/-8 (cover fallback/hotfix4), ADR-1026-2 (F8), ADR-1026-11 (summary publish integration), ADR-1022-5 (2-call pipeline), ADR-1013-3 (prompt migrations).
- **Spec:** `plans/features/extra-cover-style-pipeline/spec.md`.
- **Risk-Level:** **R3**. **Deploy:** обязательный прод-деплой; rollback §95.
- **Grounding:** `services/summary_generator.py`, `services/image_generation.py`, `services/pg_db.py`, `services/database.py` (mca-14 registry), `services/task_supervisor.py`, `services/mca_trace.py`, `services/param_catalog.py`; docs.nano-gpt.com (Image API/image-models/Image Edits/Qwen Image, 2026).

---

## 1. Context

Summary pipeline зрелый; генерация обложек работает (ASAP-2/2.1, per-chat `prompts.summary_cover_style`, fallback cover, ADR-1023-6/-1024-4/-1025-7/-8). Требуется добавить **опциональный** модульный слой Cover Style поверх уже готовой base cover, не ломая base-путь, с durable-поведением, counters, capabilities и UI.

Ограничения/факты:
- SQLite на проде — **v19**; реестр миграций `mca-14` (`migration_steps()`) — единственный механизм бампов; следующая свободная **v20**, но она **уже забронирована** за `mca-04b` (ADR-1027-9 D13, frames §1.2.5), а `mca-04b` ещё не построен (deploy `DEFERRED_TO_RELEASE`). Очередь владельца: **EXTRA идёт раньше MCA-tasks**.
- PG-DDL уже используется как идемпотентный стартовый механизм (`pg_db.py::DDL_STATEMENTS`); A5 добавил PG-only `image_reservation` при **Δ SQLite = 0**.
- Durable job/telemetry (LIVE на 2.58.38): `task_jobs`(v14)/`TaskSupervisor`, `mca_events`(v15), `mca_pipeline_runs`/`mca_incidents`(v19), code-declared process registry.
- Фактический image-API: base-путь `POST {base}/images/generations` (`{prompt,model,n:1}`); провайдер публикует **machine-readable capabilities** (`GET /api/v1/image-models?detailed=true` + `/images/models/{model}/endpoints`) и **edit-route** (`POST /api/v1/images/edits`, multipart `image[]`); Qwen Image — edit, ≤3 reference images, 30 MB, sync.

---

## 2. Decisions

### D1 — Хранилище Style Registry: **PG**, Δ DDL SQLite = **0** (вариант (b))

**Решение.** Style Registry, references, assets-метаданные, issue-assignment, revision и provenance живут в **PostgreSQL** через идемпотентные `CREATE TABLE IF NOT EXISTS` в `services/pg_db.py::DDL_STATEMENTS`. **SQLite `user_version` не поднимается (остаётся 19).**

**Альтернативы.**
- (a) EXTRA берёт SQLite **v20**, `mca-04b` → v21 + AMEND ADR-1027-9 D13 + правка frames §1.2.4.
- (c) Смешанный (Registry PG, issue-assignment SQLite → всё равно v20).
- (d) Файловый store.

**Rationale (почему (b)).**
1. **Устраняет кросс-фичевый конфликт без правок чужого артефакта.** (a) требует AMEND уже санкционированного ADR-1027-9 D13 и правки `mca-round1027-arch-frames.md`; (b) оставляет `mca-04b`=v20 и frames неизменными.
2. **Исполнимо и прецедентно.** Механизм PG-DDL («DDL_PG-паттерн mca-05/A5») в проекте уже есть: `image_reservation` (A5) добавлена в `DDL_STATEMENTS` при Δ SQLite=0. Аналогично добавляются 5 таблиц EXTRA.
3. **Данные подходят PG, а не SQLite.** Registry/counters/issues — это админ-конфигурация и низкообъёмные транзакционные записи (как `bot_settings`, `chat_keys`, `worker_budget`, `personas`), а не память/граф (которые сознательно на SQLite). Issue-assignment требует настоящей транзакционной уникальности и `ON CONFLICT`/`FOR UPDATE` — PG даёт это чисто.
4. **Класс отказа приемлем.** Если PG недоступен — Style-функции деградируют (base cover + публикация продолжают работать), что соответствует §1 («обложка/стиль не критическая точка отказа»).

**Consequences.**
- Δ DDL SQLite **= 0**; `mca-04b` сохраняет v20; **AMEND ADR-1027-9 D13 и правка frames не требуются**.
- Требуется PG-migration-процедура: аддитивные таблицы + индексы в `DDL_STATEMENTS`; обновление `sha256(pg_db.py)` при F8-переиздании.
- F6 (пересмотр): SQLite-файл prod не меняется.
- Негатив: Style-фичи недоступны без PG; это осознанно (fail-soft).

### D2 — Image Model Capability Resolver: **runtime discovery как источник истины**

**Решение.** Capability резолвится `provider+base_url+model` → `ImageModelCapabilities`. Precedence (§16): (1) explicit developer override (env, аварийный) → (2) **runtime/provider discovery** (`GET /api/v1/image-models?detailed=true` + `/images/models/{model}/endpoints`) → (3) provider-specific catalog → (4) verified internal registry → (5) `unknown`/conservative (`image_edit=unknown`, `max_input_images=0`). Cache по `provider+base_url+model` с TTL и инвалидацией (смена connection/model, reload config, refresh).

**Rationale.** Провайдер **прямо запрещает** хардкод capability-таблиц; владелец (§14/§15) требует dynamic resolver и «не переносить 800». Discovery отдаёт `capabilities.image_to_image`, `supported_parameters.max_images`, `input_reference_constraints.max_items`, `route.max_bytes`, `pricing` — всё, что нужно UI/compiler.

**Consequences.** `800` не хардкодится; `prompt_limit.source ∈ {provider_or_registry, internal_config, unknown}`; unit `chars|tokens|bytes|unknown`; для неизвестных/локальных провайдеров — override/registry/conservative.

### D3 — Base и Style Edit — **разные model slots/connections**

**Решение.** Слоты `Base Cover Generation` (существующие `models.image_base_url`/`models.image_model`/`keys.image_api_key`) и `Cover Style Processing` (новые `models.image_style_base_url`/`models.image_style_model`/`keys.image_style_api_key`, §4.1 spec). Per-style override (`default`/`custom`). **Secrets только в Connections** (R17).

**Rationale.** §31–§35: провайдеры/модели base и edit различаются (base — генерация, edit — image-to-image). Интеграция через существующую Connections/Model-Slots архитектуру (`models.*`/`keys.*` группы) — без второго механизма (Q5).

**Consequences.** +3 каталог-ключа (гр. `models_images`/`keys_images`); CLI-маска ключа §74; селектор модели в Style Editor + deep-link §35.

### D4 — Style Edit = normalizer, capability-gated; sync-путь

**Решение.** Style Edit — не overlay, а нормализатор (§23). **API-call запускается ТОЛЬКО если `image_edit=true`**; иначе §38-ошибка. Edit осуществляется через `POST /api/v1/images/edits` (multipart `image[]`) / нормализованный `POST /api/v1/images` (`input_references`); билд-путь синхронный (§41) с отдельным image-timeout. Async (`submit→task_id→poll`) — capability-gated, provider task_id в durable job payload.

**Rationale.** Текущий код-дефолт (Pollinations/flux) edit не умеет; провайдер публикует edit-route с multi-image (`image[]`); Qwen Image даёт ≤3 reference. Сила §20/§23 — в промпт-компиляторе, а не в новом пайплайне.

**Consequences.** Без edit-capable provider в Connections Style stage «не работает» корректно (base публикуется); это продуктовая зависимость, выносится в отчёт §101 (DC-4).

### D5 — Image Prompt Compiler: priority-aware P0/P1/P2 + CoverBrief

**Решение.** Compiler собирает prompt из компонент §19 с приоритетами §20 (P0 = runtime invariants + issue number, P1 = композиция/callouts, P2 = stylistic); при pressure режется **сначала P2**; `text[:N]` по mandatory-инструкции запрещён. CoverBrief (§21) — компактный сюжет.

**Rationale.** §19–§21/§57/§58/§88. Budget indicator строится из тех же компонент; unknown-limit не блокирует save.

### D6 — Asset storage: PG-метаданные + durable файлы (новый регистр)

**Решение.** Новый durable asset-регистр: PG `cover_style_assets` (stable `asset_id`, meta) + файлы в `var/cover_style_assets/` (env `COVER_STYLE_ASSETS_DIR`). Seed-файлы **копируются** (originals не мутируются, R18). Thumbnail-отдача — по HMAC-URL (паттерн `media_share`). Dangling-protection §64.

**Rationale.** §8/§12 требуют stable `asset_id` и «существующее media/assets storage», но в коде **нет** durable asset-регистра (есть лишь TTL-шаринг `media_share` и audit). Поэтому регистр вводится (DC-6). Хранение байтов в PG неоправданно; метаданные в PG + файлы на диске — чемоданно и обратимо.

### D7 — Counters/issue: PG, транзакционно, retry-reuse

**Решение.** Per-style counter (не глобальный); `cover_style_issue_assignments (profile_id, summary_run_id) → issue_number` с `UNIQUE(profile_id, issue_number)`; allocator транзакционный (FOR UPDATE / `+1 RETURNING` + `ON CONFLICT DO NOTHING`) — retry-reuse (`44→44`), uniqueness при конкурренции. Test Style не расходует counter (§66).

**Rationale.** §25–§28/§83/§84/§60. PG даёт нужную транзакционность.

### D8 — Durable job: **REUSE** существующей инфраструктуры MCA

**Решение.** `TaskSupervisor`/`TaskJobStore` (`task_jobs`, v14) — durable job/coalescing/heartbeat/recovery; `mca_trace.start_run`/`finish_run` (`mca_pipeline_runs`, v19) — run lifecycle; `mca_events` (v15) — телеметрия. **Второй очереди/стора нет.** State machine §42 → `task_jobs.status/reason_code/checkpoint_ref`; provider task_id в `payload`.

**Rationale.** §42/§43/§89/§93–§100 владельца; MCA-инфраструктура LIVE. Запрет «второго экземпляра» (§42).

### D9 — Fail-soft ladder в существующем публикационном контуре

**Решение.** REUSE `_publish_rich_document`/`_plain_fallback`/`_send_rich_with_retry`/`_send_text_with_retry` и коды `*_FAILED`. **Аддитивно** добавить degraded Rich-without-cover (media=[]). Ladder: `styled → base(no base regen) → Rich without cover → sendMessage`. Классификация §96.

**Rationale.** §4/§49–§52/§96; второй publication pipeline запрещён (§52/Q10).

### D10 — Seed idempotent; фактические имена файлов

**Решение.** Seed выполняется идемпотентно (повтор — no-op; ручной стиль не перезатирается). Импортируются фактические имена: `medved_press.png`, `style_example_01.png`, `style_example_02.**jpg**`. `origin=seeded_example` — только UI-badge; runtime без special-case.

**Rationale.** §6/§7/§9/§59/§77; DC-1 (расхождение литерала `.png` vs фактический `.jpg`).

### D11 — Kill-switch env-only; Δ каталога +4

**Решение.** `COVER_STYLES_ENABLED` — env-only `ClassVar`, default ON, OFF → parity baseline (style пропущен, UI disabled). Каталог: **+4** ParamSpec (3 connection + 1 per-chat selection), F8 переиздается → 488/427/463/105/103/21.

**Rationale.** §95 + правило F8 (ADR-1026-2): kill-switch без UI → env-only Δ=0; connection/selection — UI-настройки → Δ≠0.

### D12 — UI/deep-link + browser verification

**Решение.** Новые экраны Style Registry/Editor (RU, §56/§75); deep-link `Настроить подключения →` на существующий `llm_providers` с фокусом на `Обработка стилей обложки` и сохранением контекста. `Browser-Verification: REQUIRED`, default Playwright MCP + Browser Use для visual.

### D13 — Risk/Deploy/Rollback

**Решение.** Risk **R3**; обязательный прод-деплой (bump `2.58.38 → 2.58.39`); rollback hot `COVER_STYLES_ENABLED=false`, cold `git revert` (PG-таблицы аддитивны, SQLite Δ=0).

---

## 3. Affected contracts

| Контракт | Изменение |
|---|---|
| `services/pg_db.py::DDL_STATEMENTS` | **+5 таблиц + индексы** (аддитивно/идемпотентно) |
| `services/param_catalog.py` | **+4 ParamSpec** (F8 переиздается) |
| `services/image_generation.py` | **аддитивно**: capability Resolver, edit-вызов (capability-gated), отдельная image policy; base-путь не меняется |
| `services/summary_generator.py` | **аддитивно**: style stage hook + degraded Rich-without-cover; base/no-style parity |
| `services/task_supervisor.py`/`mca_trace.py`/`mca_events.py` | **REUSE**, без изменения контракта |
| `web/api/*` (новый router) + `web/app.js`/`index.html` | Style Registry/Editor UI, upload, deep-link |
| SQLite `user_version` | **не меняется (19)** |
| `plans/docs/mca-round1027-arch-frames.md` / ADR-1027-9 D13 | **не меняются** |

---

## 4. Alternatives rejected

- **SQLite v20 (вариант a):** отвергнут — требует AMEND санкционированного ADR-1027-9 D13 и правки чужой рамки; создаёт риск двойного/переупорядоченного применения шагов; данные по природе PG-конфигурационные.
- **Файловый store для Registry:** отвергнут — нет транзакционности/уникальности для issue-assignment, плохой multi-worker и auditability.
- **Хардкод capability (`800`, `max=2`):** отвергнут — §14/§15 + прямой запрет провайдера.
- **Второй publication pipeline / вторая job-очередь:** отвергнут — §4/§42/§52.
- **Хранение байтов ассетов в PG:** отвергнут — избыточно; метаданные PG + диск чемоданнее.

---

## 5. Consequences / follow-ups

- F8-переиздание обязательно (repin sha256 `param_catalog.py` **и** `pg_db.py`, regenerate TSV/meta/ScreenMap/widget-map, update `tests/fixtures/round1025/f8_baseline.json`).
- Продуктовая зависимость: нужен edit-capable provider для реального Style Edit (DC-4) — не блокирует код.
- Owner-decision: counter start (D8/§60).
- PM-правки tasks.md: DC-1 (`.jpg`), DC-3 (`RichMessage without cover` — изменение контура), DC-6 (формулировка «asset storage»), DC-5 (per-chat selection).
- Carry-over watch: при будущем касании — `validation_mode` (§93), async image jobs (если провайдер добавит).

---

## 6. Status

**Accepted** — фактом Merge @Architect в `plans/ARCHITECTURE.md` **§105** (reconcile 30.09.2026) после Reviewer `Approved for release` (round 2) и VERIFIED прод-деплоя **2.58.39**. Прод-валидация — §7; история статуса — §8.

---

## 7. Production validation (прод 2.58.39, 30.09.2026)

**Deploy:** релиз `cc1b960` (feat) + `7d03b58` (docs) + `c0e0362` (deploy-doc); push `bbdee1c..c0e0362` без force; прод ff; `APP_VERSION` **2.58.39**; `/healthz` = `{"status":"ok","version":"2.58.39"}`, `/api/health` = 200. **Обязательные прод-проверки — 9/9 выполнены** (`deployment.md` §0.3):

1. **PG-DDL применён дважды** (`PgDatabase.init(seed_settings=False)` ×2 на боевом asyncpg + `pg_tables`/`pg_indexes`) → **APPLY1_OK / APPLY2_OK**; ровно **5 таблиц + 5 индексов** (`cover_style_profiles`/`_references`/`_assets`/`_issue_assignments`/`_provenance`; partial unique `idx_cover_style_assets_sha … WHERE deleted_at IS NULL`, `idx_cover_style_issue_unique`); **0 дублей**, без ошибок → D1/D6/D7.
2. **Real-pool CRUD-smoke** (боевой asyncpg): create/get/duplicate(`origin=custom`)/edit(revision 1→2)/delete; ref add/replace(label L1→L2)/remove; upload-дедуп по `sha256` → тот же `asset_id`, count=1; cleanup leftovers=0 → D6/D7.
3. **Counter/concurrency:** 10 параллельных `resolve_issue_number` разных run → номера **1..10 (10 distinct, без пропусков)**; тот же `summary_run_id` → **тот же номер** (retry-reuse); `UNIQUE(profile_id, issue_number)` держит (**UniqueViolation**); Test Style (`preview_issue_number()==0`) counter **не расходует** (10→10) → D7.
4. **`UPDATE … RETURNING` + `resolve_issue_number`** под боевым READ COMMITTED (`conn.transaction()`) → без задвоенных/пропущенных номеров (1..10), `counter_value`=10 → D7.
5. **`update_reference` rowcount:** PUT на несуществующий `ref_id` → asyncpg `conn.execute()` вернул **строку** `"UPDATE 0"`, `getattr(...,"rowcount",1)`=1 → функция `True` → API отдаёт **200**, не 404. Валидный путь корректен; зафиксировано как non-blocking (backlog §3).
6. **Durable restart-resume:** прод-прогон `test_extra_cover_style_jobs.py -k "DurableRestart or ProductionWiring"` → **4 passed**; resume из `task_jobs` (`provider_task_id` переиспользован, нового submit нет); статическая wiring `begin/run/finish` в `summary_generator.py` подтверждена → D8.
7. **DC-4 / T-4173 (§85/§86 + live style-success):** `models.image_style_base_url/_model` пусты, `keys.image_style_api_key` absent, `connection_status.configured=False`, `edit_supported=None` → **edit-capable провайдера НЕТ**; живой style-success и visual §85/§86 отложены владельцу (база публикуется, runtime §78/§90 зелёные) → D4.
8. **Ladder/parity на проде:** `tests/test_extra_cover_style_runtime.py` + jobs/pipeline → **61 passed**; 7/7 runtime-сценариев (§78 no-style, §79 style-success, §80 style-failure→base без регенерации, §81 base-failure→Rich без обложки, §81 parity plain при degraded OFF, §95 kill-switch OFF, §82 rich-failure→plain) зелёные → D9.
9. **Операционка:** health 200, `version=2.58.39`, `database is locked` = **0**; R17-скан `COVER_*`-логов — **0 утечек**.

**Seed (§59) + D8:** `seed_seeded_style(pg)` выполнен на проде — профиль **`medved_press`** (`origin=seeded_example`), `counter_enabled=True`, **`counter_value=0`** (обратимый дефолт `SEEDED_COUNTER_START`, owner-input PENDING); 1 reference «Медведь Press»; импортированы 3 ассета из `extra_images/` (`cas_<sha256[:32]>`: `medved_press.png`, `style_example_01.png`, `style_example_02.jpg`), идемпотентно (profiles 1→1, assets 3→3, refs 1→1); оригиналы `extra_images/*` **байт-в-байт не изменены** (R18) → D10.

**Итог:** все решения D1–D13 подтверждены на боевой СУБД/проде в объёме, доступном без edit-capable провайдера; продуктовые хвосты **D8** и **DC-4** (включая живой async resume, L-EXTRA-7) честно задокументированы и вынесены владельцу (`deployment.md` §0.8, `plans/backlog.md`). Прод-проверки — binding-условие вердикта Reviewer, выполнены полностью.

---

## 8. Status history

| Дата | Статус | Событие |
|---|---|---|
| Step 2 @Architect | **Proposed** | spec + ADR-1028-4 (D1–D13) созданы; Δ DDL SQLite=0, PG-DDL +5 таблиц (D1) |
| 30.09.2026, round 1 @Reviewer | **Needs Fixes** | H-EXTRA-1 (durable job §42/§43 не врезан) + M-EXTRA-1/2/3 (stale-preview, CoverBrief, deep-link) + 5 Low; DC-4 Unavailable |
| 30.09.2026, round 2 @Reviewer | **Approved for release** | H-EXTRA-1 + M-EXTRA-1/2/3 закрыты и врезаны в живой контур; Low/гигиена закрыты; остаточный PG-риск принят как задокументированное ограничение с 9 обязательными прод-проверками; DC-4/T-4173 Unavailable помечено честно |
| 30.09.2026, @DevOps | **DEPLOYED / VERIFIED** | прод **2.58.39** (`cc1b960`/`7d03b58`/`c0e0362`); 9/9 прод-проверок; PG DDL ×2 идемпотентно; counter 1..10; seed `medved_press` counter=0 |
| 30.09.2026, reconcile @Architect | **Accepted** | Merge `plans/ARCHITECTURE.md` §105; прод-валидация §7; follow-up в `plans/backlog.md` |

> Reconcile правки (этот §7/§8) — **docs-only** и сделаны после ревью-bound манифеста: реализованный код байт-идентичен ревью-артефактам, approval не инвалидирован. Binding-reviewed кандидат остаётся WTH `d0203e00…dc9b` (`review.md`/`deployment.md` §0.1).
