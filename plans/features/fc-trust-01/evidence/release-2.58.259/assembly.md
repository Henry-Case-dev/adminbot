# Release 2.58.259 — FCT-S3-RETRIEVAL (retrieval-контракт S3: якоря, типизированная секция кандидатов, структурные даты провайдера, точные коды исхода)

- **Дата сборки:** 2026-11-27
- **Роль:** Builder (сборка релиза, **без деплоя**)
- **Основание:** независимое ревью среза FCT-S3 **r2 APPROVED** (`review cc774ec0…`),
  находка F6 закрыта тестом `40866af41` (test-only).
- **База (deployed):** `886d11073cfdaa4646597c3a2b1ae09fde42c342` = **2.58.258** (UR-BAN-02)
- **Ветка:** `release/fct-s3-2.58.259`
- **Кандидат (reviewed):** `2c811d98b7257810c2fef5b61ce7b416798ccb40` (`feat/fct-s3-retrieval`, r2 APPROVED)
- **F6-тест:** `40866af418cab7f18e29a234444cf229f0561810` (только `tests/test_fc_trust_retrieval.py`, продукт не меняет)
- **Feature tip:** `d12263f35d2fafe2be4e43bfc89a7bd684b1f7e5`
- **Tip релиза (bump):** `baab52324943fa55e69378fe405b43f77a94e47a`
- **Tree релиза (bump):** `211c75fca22a4d0d805cdbd1ff211e8657d7a1ee`
- **Контракт:** `plans/features/fc-trust-01/evidence/fct-s3-s4-contract-2026-11-27.md`,
  sha256 `adb3bc325c4c4048d79d16b62f5b47c941a356ab4ee1c7b7953a5f3050630190` — совпадает.
- **Статус:** ASSEMBLED, не деплоился. Деплой — DevOps/Orchestrator.

> Evidence-коммит идёт отдельной поверхностью (`plans/` only, прецедент
> `release-2.58.258`). Продуктовые байты от него не меняются — проверяется
> `git diff baab52324..<tip> -- services/` = пусто. Поэтому manifest dry-run
> снят на `baab52324`, а боевой манифест DevOps пишет на сервере по фактическому HEAD.

## 1. Состав релиза

База `886d11073` **не является предком** кандидата: feature-ветка отведена от
`9516c9125` (2.58.257), а 2.58.258 стоит на нём же. Поэтому перенос сделан
cherry-pick'ом шести reviewed-коммитов (`-x`, provenance сохранён) поверх
`886d11073`, **без единого конфликта**:

```
4c4c41301 feat(fct-s3): retrieval contract S3 — anchors, typed candidate section, ...
090361c22 docs(fct-s3): implementation evidence — RED/GREEN, 18 mutations, ...
e813ae11c fix(fct-s3): technical claim outcome outranks empty/irrelevant ... (review F1)
00c4dbfcf docs(fct-s3): corrective F1 evidence ...
b06af5193 test(fct-s3): distinguishing seam test ... (review r2 F6)
bb3c958fb docs(fct-s3): F6 evidence — seam test, M-F1-R1 killed, GREEN 56/391
```

Сверху — один version-only bump-коммит `baab52324`.

**Байтовая идентичность reviewed-кода (доказано, `raw/product-delta.txt`):**

| Файл | release tip blob | candidate `2c811d98` | feature tip | identical |
|---|---|---|---|---|
| `services/factcheck_planner.py` | `3099bd9c30c8…` | `3099bd9c30c8…` | `3099bd9c30c8…` | **True** |
| `services/search_aggregator.py` | `9a708f2c4def…` | `9a708f2c4def…` | `9a708f2c4def…` | **True** |

**Нулевые изменения (как требует контракт):**
`services/safe_fetch.py` = `7e7cf0a505a9…`, `services/factcheck_attribution.py` = `bbcedf1b1db0…`
— байт-идентичны базе.

**Дельта `886d11073..baab52324` (61 файл, `raw/changed-files.txt`):**

| Категория | Файлы | Суть |
|---|---|---|
| **Продукт** | `services/factcheck_planner.py`, `services/search_aggregator.py` | S3: recall-кандидаты, evidence-профиль с обязательным якорем (`require_anchor=True`), claim-specific passage + провенанс, `basis`/`assertion_type`/`material_role`/`independence_group`/`evidence_version`, структурные даты провайдера, закрытый словарь `stop_reason`/`status_detail`, per-claim проекция `search_text`, распределение открытий, журнал запросов, `is_cancelled`, `coverage_summary`; мягкий recall (low-overlap пак не выбрасывается), `rate_limit` в `_REASON_PRECEDENCE` |
| Тесты | **6 изменённых + 1 новый** | `test_fc_trust_retrieval.py` (новый, 56 тестов), `test_factcheck_resources.py`, `test_factcheck_fc_r1_fix.py`, `test_factcheck_post_release_w1.py`, `test_factcheck_w7_acceptance_cfg06.py`, `test_evol_fc_evidence_style.py`, `test_fc_backend_corrective.py` |
| Bump | 29 файлов | 2.58.258 → 2.58.259 (`config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 25 test-файлов, 2 tools) |
| Evidence инкремента | `plans/features/fc-trust-01/evidence/fct-s3-implementation-2026-11-27/**` (23 файла) | RED/GREEN, 18 мутаций + F1/F6 |

**Не входит:** `web/api/routes.py`, `services/database.py`, `services/pg_db.py`,
`migrations/`, `services/direct_execution.py`, `services/safe_fetch.py`,
`services/factcheck_attribution.py`, `web/app.js`, промпты — не менялись (п. 3–5).

## 2. Bump — version-only (доказано)

```
raw/bump-verify.txt
commit: baab52324943fa55e69378fe405b43f77a94e47a
changed lines: -34 / +34
pairs differing ONLY by version: 34
pairs with other changes: 0
files in commit: 29
VERSION-ONLY BUMP: OK (34 pairs / 29 files)
APP_VERSION: 2.58.259
```

- Набор пинов = ровно список файлов предыдущего релизного bump-коммита
  `50df797da` (2.58.258): 29 файлов / 34 вхождения — те же числа.
- `config/settings.py`: `APP_VERSION = "2.58.259"` — единственная изменённая строка;
  **CRLF сохранены** (3665 CRLF, 0 bare LF), иначе файл дал бы 3665-строчный diff.
- Замена выполнена побайтово (`b"2.58.258"` → `b"2.58.259"`), поэтому окончания
  строк не затронуты.
- Провенанс-файлы **намеренно** остаются на 2.58.258:
  `plans/features/unified-reply/evidence/release-2.58.258/**` (4),
  `plans/features/unified-reply/evidence/ur-e-accept-2026-11-27/raw/prod-cleanup-verification.txt`.
- В тестах самого FCT-S3 версионных пинов нет (проверено: `2.58.25\d`/`APP_VERSION`
  в 7 тест-файлах среза отсутствуют) — расширять pin-набор не требовалось.

## 3. Routes-пин (ROUTES_SHA256_F11) — re-pin не нужен

```
raw/routes-pin.txt
routes_sha256_head=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_sha256_base_886d11073=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_byte_identical=True
ROUTES_SHA256_F11=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
pin_matches_head=True
decision=no re-pin
pin_test=tests/test_round1025_f8_registry.py::TestFrozenInvariants::test_routes_file_unchanged (29/29 passed)
```

`web/api/routes.py` байт-идентичен базе; route-set/inventory Δ=0.

## 4. DDL Δ = 0

```
raw/ddl-check.txt
changed files total: 61
changed DDL/schema files: []
services/database.py changed: False
services/pg_db.py changed: False
migrations/ changed: False
{"ddl_delta": 0}
```

Прод уже на текущей схеме (выложен 2.58.258) → миграций при деплое нет,
**rollback code-only безопасен по схеме**.

## 5. Сохранение 2.58.258 (UR-BAN-02) — подтверждено

```
raw/preservation-2.58.258.txt
direct_execution.py blob @ release tip          = f138c7a737036a7cb30e354722019ba38d5c1cb3
direct_execution.py blob @ base 886d11073       = f138c7a737036a7cb30e354722019ba38d5c1cb3
direct_execution.py blob @ 9516c9125 (2.58.257) = c77f127f976b7cb66e1ba326e4396e358a1f978e
identical_to_deployed_base = True
differs_from_2.58.257      = True
```

- Маркеры UR-BAN-02 на месте: `safety_steps = orchestrator_budget_for_window(...).max_steps`,
  `max_steps = explicit_steps or safety_steps`, `stop_reason="max_steps"`.
- `routes.py` (носитель 2.58.258) байт-идентичен базе.
- Release **не откатывает** 2.58.258: bump-коммит касается только версии, а весь
  остальной дельта-набор — файлы FCT-S3 + evidence. `git diff` по `services/`
  вне двух S3-файлов пуст.

## 6. Прогоны

| Набор | Команда (в worktree релиза) | Результат |
|---|---|---|
| FCT-S3 срез | `pytest tests/test_fc_trust_retrieval.py -q` | **56 passed** (`raw/tests-slice.txt`) |
| Контрактные наборы §3/§8 (12 файлов) | `pytest <12 files> -q` | **399 passed** (`raw/tests-acceptance.txt`) |
| Широкий набор потребителей (44 файла: все, кто импортирует planner/aggregator) | `pytest <44 files> -q` | **1392 passed, 2 failed** — оба предсуществующие (`raw/tests-broad-consumers.txt`) |
| Пины/реестр (25 файлов) | `pytest <25 files> -q` | **864 passed, 6 failed** — те же 6, что у 2.58.258 на его базе (`raw/tests-pins.txt`) |
| Смежные контуры (21 файл: direct/self-diag) | `pytest <21 files> -q` | **635 passed, 9 failed** — все предсуществующие (`raw/tests-adjacent.txt`) |

### 6.1 Почему 399, а не 391

391 — результат F6 на базе 2.58.257. База 2.58.259 = 2.58.258, который добавил
**+8 тестов** в `tests/test_unified_reply_ur_b_search_first.py` (UR-BAN-02).
Проверено: `def test_` в этом файле = 58 на релизе против 50 на `9516c9125`
(delta **+8**), и файл сам зелёный 68/68. То есть **391 + 8 = 399** — расхождение
объяснено полностью и является признаком того, что предыдущий релиз в сборке присутствует.

### 6.2 Предсуществующие red-ы (17 уникальных node id) — воспроизведены на базе

`raw/tests-base-preexisting.txt` — те же node id на `886d11073`:

- Пины (6): `test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta`,
  `test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
  `test_unified_image_request_round1026.py::{TestToolDescriptionU21::test_canon_unchanged,TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
  `test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28` — **6 failed on base**.
- Потребители (2): `test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`,
  `test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions` — **2 failed on base**.
- Смежные (9): `test_direct_context_scenarios_asap3`, 5× `test_direct_fallback_recompose_asap32`,
  `test_direct_l1_corrective_r1`, 2× `test_selfdiag_corrective_research` — **9 failed on base**.

Ни один red не связан с FCT-S3; пины 2.58.259 зелёные (864 passed — ровно как у
2.58.258, версионные пины не «протухли»).

## 7. Manifest dry-run

Затравка «предыдущего» манифеста: в базовом checkout на `886d11073` однократно
выполнен `tools/release_manifest.py` (не `--dry-run`), что записало
`.deploy/release.json` с фактическим состоянием прода
(`deployed_sha=886d11073`, `version=2.58.258`). `.deploy/` gitignored, в коммит не входит.

```
raw/manifest-deploy.json
{
  "deployed_sha": "baab52324943fa55e69378fe405b43f77a94e47a",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "886d11073cfdaa4646597c3a2b1ae09fde42c342",
  "previous_version": "2.58.258",
  "release_branch": "release/fct-s3-2.58.259",
  "schema": 1,
  "version": "2.58.259"
}
```

`raw/manifest-rollback.json` — тот же прогон с `--effect rollback`:
`deployed_sha`/`version` те же, `effect=rollback`, `previous_*=886d11073/2.58.258`,
то есть откат возвращает на выложенную версию.

**Rollback = code-only:** DDL Δ=0 (п. 4) → `git checkout 886d11073` +
`systemctl restart admin_bot`; миграции/данные не откатываются.

## 8. План выката (НЕ выполнен, для DevOps)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD          # ожидается 886d11073
git pull --ff-only                            # до tip ветки release/fct-s3-2.58.259
python tools/release_manifest.py              # effect=deploy, previous=886d11073
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz       # ожидается version 2.58.259
python manage.py disk audit && python manage.py disk cleanup --apply   # P0-PROD-DISK-01
```

После рестарта проверить: `healthz.version=2.58.259`, `deployed_sha=<фактический HEAD>`,
`.deploy/release.json` (`previous_sha=886d11073`), отсутствие ошибок схемы
(DDL не ожидается), свободное место.

Наблюдаемый эффект S3 на проде: cross-провайдерная выдача больше не выдаётся за
evidence без якоря (`word_overlap_only` → `background_only` с `basis`), в модельный
раздел не попадают отсеянные кандидаты, у даты — `published_at_source=provider`,
а исходы части различают `resource_limit`/`global_deadline`/`provider_timeout`/`rate_limit`.

## 9. Ограничения и честные расхождения с формулировкой задания

- Деплой не выполнялся; прод не затрагивался (только read-only и локальные прогоны).
- **«Правки 5 существующих наборов»** — фактически **6** существующих наборов
  (`test_factcheck_resources`, `test_factcheck_fc_r1_fix`, `test_factcheck_post_release_w1`,
  `test_factcheck_w7_acceptance_cfg06`, `test_evol_fc_evidence_style`, `test_fc_backend_corrective`)
  плюс 1 новый. Это зафиксировано в `index.md` §5/§10 самого среза (9 путей).
- **391 vs 399** — объяснено в §6.1 (+8 тестов UR-BAN-02 из базы 2.58.258).
- Контракт-файл `fct-s3-s4-contract-2026-11-27.md` в release-ветке отсутствует:
  он живёт только в docs-линии (`master`, коммит `d0964e19d`). Его sha256 сверен
  через `git show` и совпадает (`adb3bc32…`); в дельту релиза он не добавлялся,
  чтобы не расширять состав сверх продуктового контракта.
- `master` не является потомком `886d11073` (`origin/master` ≈ 2.58.128): в проекте
  релизы живут на `release/*`, а `master` — накопительная docs/state-линия.
  База сборки задана явно и проверена (`git rev-parse 886d11073` = deployed 2.58.258).
- 17 предсуществующих red-ов остаются backlog'ом (не связаны с S3, доказано на базе).
- Модельное поведение (качество исследования на якорях) — live-наблюдение;
  детерминированно доказаны коды исходов, типизация секции, даты и сохранение evidence.

## Артефакты

`raw/`: `identity.txt`, `changed-files.txt`, `product-delta.txt`, `routes-pin.txt`,
`ddl-check.txt`, `bump-verify.txt`, `preservation-2.58.258.txt`,
`tests-slice.txt`, `tests-acceptance.txt`, `tests-broad-consumers.txt`,
`tests-pins.txt`, `tests-adjacent.txt`, `tests-base-preexisting.txt`,
`manifest-deploy.json`, `manifest-rollback.json`, `test-sets.json`, `SHA256SUMS`.
