# Release 2.58.272 — FC-TRUST S6-U3: API сводки, компактная панель, заводской флаг v2 = ON

- **Дата сборки:** 2026-11-28.
- **Роль:** DevOps (сборка релиза + деплой).
- **База (deployed):** `3a78484b92a6f3ba1273360e4a34de396dcf52f1` = **2.58.271**, схема `user_version=50`.
- **Ветка:** `release/2.58.272` от `cd30faac1` (тип `release/2.58.271` = deployed `3a78484b9` + deploy-docs),
  worktree `WorkspaceData/worktrees/…/release-2-58-272-d6f1af7a4750-a1d1466d`.
- **Reviewed-кандидат:** продукт `f6cd011e0ef73fdce9633185f7b2889c2bf7e3fe`,
  tip `c3c0e1cb3ff88cc9f4d7c8fa2a52f1b4208dd1fc` (ветка `feat/fct-s6-u3-aggregate-api-2026-11-28`).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s6-u3-2026-11-28/review-r2.md`
  sha256 `5d142070e97c0bd62c6e8efbbba7d97097b76ce0293fd82c66d30d2b8647b8bb` —
  **APPROVED_FOR_RELEASE_PREPARATION** (r1 `b33a13ea…` NEEDS_FIXES, finding RV-S6U3-01 закрыт).
- **Схема:** **не меняется** (v50, DDL Δ=0, миграции не запускаются).

## 0. Состав — merge кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `9bca32928` | `merge(fct-s6-u3)` — кандидат `c3c0e1cb3` влит `--no-ff`; все 21 продукт/тест-файл байт-в-байт |
| `cb47e6cbd` | `chore(release): bump 2.58.271 → 2.58.272 (version-only, 29 файлов / 34 вхождения)` |

**Почему merge, а не ff.** Задание предполагало `ff` до `c3c0e1cb3`, но fast-forward
невозможен: deploy-evidence коммит `cd30faac1` (добавлен после выкладки 2.58.271) не входит
в историю кандидата, а база кандидата — `3a78484b9` (`merge-base c3c0e1cb3 release/2.58.271`
= `3a78484b9`). Взят `--no-ff`-merge: конфликтов нет (deploy-docs трогает только
`plans/.../release-2.58.271/`), reviewed SHA остаются достижимыми, продуктовые байты
не переписываются (в отличие от rebase/cherry-pick, который пересоздал бы коммиты).

## 1. Byte-identity assembly

`raw/identity.txt`. Сравнение всех **48** путей, изменённых относительно типа предыдущего
релиза (`cd30faac1` → `HEAD`): блоб worktree vs блоб кандидата `c3c0e1cb3` vs блоб базы.

```
files_changed_vs_base=59   files_changed_vs_previous_tip=48
all_candidate_files_identical_or_version_only=True  mismatches=none
byte_identical=True             — 19 файлов (продукт, тесты, фикстуры, evidence)
version_literal_only=True       — 29 файлов (канонический bump-set)
non_version_lines vs candidate  — 0
ddl_or_migration_paths=none
```

`version_literal_only` проверяется побайтово: `candidate_bytes.replace(b"2.58.271", b"2.58.272")
== worktree_bytes`. Ни одного иного отличия от reviewed-кандидата в дереве нет.

sha256 деплоируемых файлов (`raw/identity.txt`, on-disk байты release-worktree; диск == блоб,
`core.autocrlf=false`):

```
web/api/routes.py                        5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf   == кандидат
web/app.js                               20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74   == кандидат
web/index.html                           b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907   == кандидат
services/factcheck_orchestrator.py       01bb941b0d5a2b64dedb34f2600baf467ae6255bdd2e3c2a66f3db39e6b03650   == кандидат
services/factcheck_prompts.py            4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4   == кандидат, == база (не менялся)
tests/test_fc_trust_s6_aggregate_api.py  f4ec5b1933ee3a2f9a304b35adc87be846a8a9ac5bf6fe298ce0b9612bba8050   == кандидат
tests/test_mca23_planned_vs_actual.py    a155eb35e6737f1bf9c72c2e09ec8097f60ce189d4c73639baa37d72c2e32510   == кандидат
tests/fixtures/round1025/f8_baseline.json 3e22a537cb6d8f8f529d2d57c9a49422d8894301fb299215ad4d4b63283f563c  == кандидат
config/settings.py                       ca3bc66df1c0b0de34f15b450d006c27a452c1e696e744c3801c2e79f44bdd7f   == кандидат + версия
tests/test_round1025_f8_registry.py      875d861eee1350ad3892b008a3124355a913a71ebe1a9077ad77ef46d934c0fb   == кандидат + версия
```

Блоб-идентичность продукта независимо подтверждена `git rev-parse`:
`web/api/routes.py` = `92bb8a727400…`, `web/app.js` = `8d3c535e6c7f…`,
`web/index.html` = `90499d81cd93…` — совпадают с `c3c0e1cb3` и `f6cd011e0`.

## 2. Продуктовый диф

`raw/identity.txt` §product: 39 путей в `web/ services/ config/ tests/ tools/` относительно базы:

- `web/api/routes.py` — только новый endpoint `GET /api/factcheck/temporal/aggregate` (+28);
- `web/app.js` (+86), `web/index.html` (+10) — компактная строка сводки на существующей вкладке;
- `config/settings.py` — литерал `APP_VERSION` + заводское `FACTCHECK_PIPELINE_V2_ENABLED: bool = _env_bool(..., True)`;
- `services/factcheck_orchestrator.py` (+9) — docstring приоритета флага (hot → env → factory ON);
- тесты: новый `tests/test_fc_trust_s6_aggregate_api.py` (+318), обновления пин-констант,
  `tests/test_mca23_planned_vs_actual.py` (RV-S6U3-01), фикстура `f8_baseline.json` (+1 путь);
- `services/factcheck_prompts.py` не менялся (sha256 `4cd1e893…` == база).

INSERT/UPDATE/DELETE/CREATE/DROP/ALTER в продуктовом дифе отсутствуют (read-only endpoint поверх
уже существующих SELECT'ов S6-U2); DDL Δ=0.

## 3. Bump 2.58.271 → 2.58.272 — version-only

`raw/bump-verify.txt`:

```
files_in_canonical_set=29 files_changed=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0 non_version_added_lines=0
remaining_old_occurrences=0 new_occurrences=34
crlf_total=3665 bare_lf_total=15448
APP_VERSION = "2.58.272"
```

Набор 29 путей — канонический bump-set `8578ebe17` (270→271) = `3eafef83c` (269→270).
Размеры всех файлов до/после совпадают (`size_before == size_after`), EOL сохранены
(`config/settings.py` CRLF 3665). Исторические evidence-каталоги `release-2.58.26x/` и
`release-2.58.271/` намеренно не бомпались.

## 4. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| Обязательный набор: `test_mca23_planned_vs_actual` + `test_round1025_f8_registry` + `test_fc_trust_s6_aggregate_api` + `test_fc_trust_s6_aggregates` + `test_factcheck_p0_fc` | **108 passed**, 0 failed (13.36 s) | `tests-mandated.txt` |
| Все 25 bump-нутых тест-файлов (пины версии/каноны/веб-инварианты) | **864 passed, 6 failed** (79.4 s) | `tests-bumped.txt` |
| Параity тех же 6 на базе `3a78484b9` (deployed 2.58.271) | **6 failed, 9 passed** — тот же набор | `tests-base-parity.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |
| `import config.settings` + orchestrator + prompts | **IMPORT_OK**, `APP_VERSION=2.58.272`, factory `FACTCHECK_PIPELINE_V2_ENABLED=True` | `import-check.txt` |

**6 падающих тестов — предсуществующие, не введены этим релизом.** Тот же набор
(`test_mca17c…::test_no_ddl_catalog_ks_tools_delta`, `test_tool_coordinator_round1026.py::
TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
`test_unified_image_request_round1026.py::{TestToolDescriptionU21::test_canon_unchanged,
TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28`) падает идентично на
**выложенной базе 2.58.271** в отдельном чистом worktree (`raw/tests-base-parity.txt`).
Причина — snapshot/diff-гарды, привязанные к master-линии (`git diff pre-round1026-a1`,
канон 28 «секретов» при фактических 34). К контракту этого релиза они не относятся и
release-барьером 2.58.271 не были; ни одного **нового** падения не появилось.

## 5. Манифест

`raw/manifest-dryrun.txt` — `tools/release_manifest.py --dry-run` на собранном дереве:
`version=2.58.272`, `release_branch=release/2.58.272`, `dirty_tracked=false`, `schema=1`.
`previous_sha`/`previous_version` подставляются на проде из фактического `.deploy/release.json`
(ожидается `3a78484b9…` / `2.58.271`); `deployed_sha` на проде = фактический HEAD после
evidence-коммитов.

## 6. Откат

DDL Δ=0, единственная продуктовая дельта — существующие web/config/services без миграций ⇒
**code-only откат** к `3a78484b92a6f3ba1273360e4a34de396dcf52f1` (`git checkout --detach 3a78484b9`
+ `systemctl restart admin_bot`). Код 2.58.271 совместим со схемой v50. Dry-run — в deploy evidence.
