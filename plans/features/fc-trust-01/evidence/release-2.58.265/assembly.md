# Release 2.58.265 — FC-TRUST-01 S4 U2 (вердикт и технический статус исполнения)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (окружение + локальная сборка).
- **Статус:** ASSEMBLED; выкладка — отдельный `deploy-2.58.265.md`.
- **База (deployed):** `c67683dd68dc4e2e3d48bff06c6568b3448cbc20` = **2.58.264** (product `0118dc081`).
- **Ветка:** `release/2.58.265` (создана от базы).
- **Reviewed-кандидат:** `6ab3b718a665b6f61e2ab7e018f62d4d05040a66`, ветка
  `feat/fct-s4-u2-verdict-2026-11-28`, tip `6d911272e`.
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s4-u2-2026-11-28/review-r1/review-r1.md`
  sha256 `b8483a26…` — **APPROVED_FOR_RELEASE_PREPARATION** (RV-S4U2-01/02 — BACKLOG_ONLY).

## 0. Состав — reviewed-кандидат + bump

| Коммит | Назначение |
|---|---|
| `aa7f3f6d8` | feat(fct-s4-u2): PARTIAL→insufficient (без ложного mixed), `CheckedVerdict.execution_status/cause/proof_basis`, snippet-only не даёт support, RAG в типизированный `<chat_context>` — продуктовые файлы **байт-идентичны** `6ab3b718a` |
| `d95ac5ca0` | chore(release): bump 2.58.264 → 2.58.265 (version-only, 29 файлов / 34 вхождения) |
| evidence | этот файл + `raw/` (коммит-носитель = tip `release/2.58.265`) |

## 1. Продуктовая дельта — 3 файла, байтовая идентичность кандидату

`raw/identity.txt` (git index blob против `6ab3b718a`):

| Файл | blob HEAD | = candidate | base blob |
|---|---|---|---|
| `services/factcheck_orchestrator.py` | `8db1e41fece0…` | True | `485bbe38cef2…` |
| `services/factcheck_service.py` | `e06c6afb9c83…` | True | `12c74ebc578e…` |
| `services/factcheck_planner.py` | `db1e73341020…` | True | `b143e4a7713c…` |

`git diff --stat 6ab3b718a aa7f3f6d8 -- <8 файлов>` = пусто (`IDENTICAL_TO_CANDIDATE`).
`raw/product-delta.txt`: `git diff --name-only c67683dd6 -- . ':(exclude)plans'` = ровно 3
продуктовых файла + 5 тестовых; других продуктовых изменений (handlers/web/config/migrations/tools) — **0**.

Тесты кандидата перенесены тем же коммитом и также байт-идентичны:
`tests/test_fc_trust_verdict.py` (новый, `c9b0f4cae074…`), `test_evol_fc_evidence_style.py`
(`aa443043e1ab…`), `test_factcheck_fc_r1_fix.py` (`569a4b91e394…`),
`test_factcheck_orchestrator_cfg06.py` (`82298d04a82d…`), `test_factcheck_service.py`
(`0f43bb08032b…`). Это обновления под новый контракт (typed `<chat_context>`, schema-freeze,
internal-поля), review их разбирал отдельно.

`raw/product-diff-full.txt` — 299 строк полного диффа трёх продуктовых файлов.

## 2. Bump 2.58.264 → 2.58.265 — version-only

`raw/bump-verify.txt`:

```
files=29  additions=34  deletions=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
pairs_differing_only_by_version=34/34
version_only_bump=OK
eol_settings: crlf=3665 bare_lf=0 size=362807
APP_VERSION=2.58.265
```

Набор 29 файлов тот же, что в 2.58.264: `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`,
25 тестовых пинов, 2 tools. `raw/bump_2_58_265.py` — воспроизводимый скрипт (побайтовая замена,
EOL не меняется). Git-статистика bump-коммита: `29 files changed, 34 insertions(+), 34 deletions(-)`.

## 3. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: изменённых миграций/`services/database.py`/`services/pg_db.py` — 0;
DDL-строк в диффе `services/handlers/web/config` — 0; `max_schema_constant=49`; `ddl_delta=0`.
Откат — code-only (`git checkout --detach c67683dd6` + restart), без миграций.

## 4. Seed: новых настроек нет

`services/param_catalog.py` не менялся (blob `d4b0a884c738…` = база), новых `limits.factcheck_*`
в диффе — 0. `tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 668 == REGISTRY`
(`raw/registry-check.txt`). Ожидаемое число строк PG `bot_settings` — **558 без изменений**.

## 5. Routes-пин и бандл не менялись

`raw/routes-pin.txt`:

```
routes_sha256_head = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_blob_head   = a851e4f857b13ea1851ebfcc00aec940b867a896 (= base = candidate)
ROUTES_SHA256_pin_matches_expected_b8f63355 = True
app_js_sha256_disk = 3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a (2739459 B)
```

## 6. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `tests/test_fc_trust_verdict.py` | **24 passed** (7.60 s) | `tests-verdict.txt` |
| `test_fc_trust_s1_contract` + `test_fc_trust_retrieval` + `test_fc_trust_target` + `test_factcheck_p0_fc` + `test_factcheck_context_cfg06` + `test_factcheck_post_release_w1` | **218 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) | `tests-core.txt` |
| Изменённые кандидатом тесты: `test_evol_fc_evidence_style` + `test_factcheck_fc_r1_fix` + `test_factcheck_orchestrator_cfg06` + `test_factcheck_service` | **96 passed** | `tests-updated.txt` |
| Пины: `test_webapp_f11_round1025` + `test_round1025_f8_registry` | **62 passed** | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

24 и 218 совпадают с GREEN независимого Reviewer на том же кандидате (24 + 191 + 27).

## 7. Манифест

`raw/manifest-dryrun.txt` — dry-run со stub «текущий прод = `c67683dd6` / 2.58.264»
(stub удалён, `.deploy/` в worktree отсутствует):

```json
{ "deployed_sha": "d95ac5ca0e77…", "version": "2.58.265", "effect": "deploy",
  "previous_sha": "c67683dd68dc4…", "previous_version": "2.58.264",
  "release_branch": "release/2.58.265", "dirty_tracked": false, "schema": 1 }
```

На проде манифест пишется штатным `tools/release_manifest.py` после checkout ⇒ `deployed_sha` =
фактический HEAD, `previous` = `c67683dd6` / 2.58.264, `dirty_tracked=false`.
**Rollback = code-only** (DDL Δ=0, схема v49).

## 8. Ограничения

- FCT-601/603/604/305/315/193 — по ревью; публикация `execution_status` — U3 (в этот релиз не входит).
- RV-S4U2-01/02 — BACKLOG_ONLY, вне текущего скоупа.
- Тесты на проде не запускаются; live-проверки — в `deploy-2.58.265.md`.

## Приложения

`raw/`: `identity.txt`, `product-delta.txt`, `product-diff-full.txt`, `bump-verify.txt`,
`bump_2_58_265.py`, `ddl-check.txt`, `seed-factcheck.txt`, `routes-pin.txt`, `tests-verdict.txt`,
`tests-core.txt`, `tests-updated.txt`, `tests-pins.txt`, `registry-check.txt`, `manifest-dryrun.txt`,
`SHA256SUMS`.
