# Release 2.58.235 — E-TRUNC / E-LAG (assembly)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (не задеплоено).
Scope: Experience amendment `EXP-E-TRUNC-01` / `EXP-E-LAG-01`; без нового
эпика/экстрактора/очереди, без DDL/ACL/UI/embedding.

- Production base / rollback: `56e2450d2c02e3d8ac595b9a412a121127f57b57`
  (2.58.234).
- Reviewed candidate: `066909923b1366e84e544b3aa5dfb3c7eb8fa18a`;
  review r3 `55aafa79f` **APPROVED_FOR_RELEASE_PREPARATION**.
- Release branch: `release/exp-e-trunc-lag-2.58.235`.
- Content tip (6 cherry-picks): `b1036c53d26350c36b15e75d172f7008eb49a59f`.
- Bump commit: `f2c39e36921a0487c5e645f01184c60895bc68a6`.
- Evidence/docs commit: этим коммитом выше bump (manifest фактического HEAD
  фиксируется deploy-временем).

## 1. Cherry-picks (linear, 0 merges)

`git cherry-pick 819361a71^..066909923` в worktree от `56e2450d2`:

| Source | Release commit |
|---|---|
| `819361a71` fix E-TRUNC/E-LAG | `f82ca8b72` |
| `ece1e1ca9` evidence | `1faafeafc` |
| `a5049c842` B01/N01 | `df1371b01` |
| `1df6fff16` evidence | `49609456d` |
| `161a17059` B02 | `689318580` |
| `066909923` evidence | `b1036c53d` |

Проверки:

```
git diff --quiet 066909923 b1036c53d        # exit 0 (product/content identical)
git diff --quiet 066909923 f2c39e369 -- \
  services/mca_experience_jobs.py tests/test_exp_e_trunc_lag_amendment.py \
  tests/test_mca16_experience_block_d_round1039.py   # exit 0
git rev-list --merges 56e2450d2..f2c39e369 | wc -l    # 0
```

Bump меняет только version pins: `git diff 066909923 f2c39e369` =
**32 files, 35 insertions, 35 deletions**.

## 2. Version wave 2.58.234 → 2.58.235

- `config/settings.py`: `APP_VERSION = "2.58.235"`; 2.58.234 сохранён как
  `Prior 2.58.234` (историческая запись).
- `plans/docs/param-registry-round1025.meta.md`.
- version-pin JS: hotfix7/8/9/10 (escaped regex-пины).
- 24 Python version-pin теста (включая hotfix6–10, f6/f7/f9/f11,
  summary/deploy/factcheck/tool/telegram/webapp/polygon).
- tools `ui_mod_acl_m4b2_status_e2e.py` (3) и `m4b3_status_e2e.py` (1).
- BOM/CRLF `config/settings.py` сохранены (BOM EF BB BF, 3645 CRLF);
  `git diff --check` — exit 0.
- `git grep 2.58.234` после wave: только historical evidence/release-2.58.234,
  `Prior 2.58.234` в settings и historical path в `test_acl_audit.py`;
  действующих пинов 2.58.234 нет.

## 3. DDL / schema

- Изменён только `services/mca_experience_jobs.py` (product code) + tests.
- `services/database.py`, `services/pg_db.py`, `services/chat_lore_store.py`
  не менялись; новых таблиц/колонок/индексов нет.
- SQLite остаётся **48** (локальный schema smoke: `PRAGMA user_version=48`,
  101 table); PG DDL **0**.
- Deploy/rollback — code-only; PG backup/DDL не требуются; SQLite predeploy
  backup — существующим механизмом `keep=2`.

## 4. Tests

- Version-pin wave: **856 passed, 4 failed** — те же 4 node ID падают
  идентично на deployed base `56e2450d2` (проверено detached worktree;
  `26.59s`), не candidate-regression.
- E-TRUNC/E-LAG: **13 passed** (`tests/test_exp_e_trunc_lag_amendment.py`).
- Релевантные Experience/смежные 18 файлов: **292 passed, 1 deselected**
  (`deep_sleep_not_mixed_with_lessons` — pre-existing, идентично на base).
- JS pins hotfix7–10: `node --check` + запуск — 4× OK.
- `py_compile` — 0; `git diff --check` — 0;
  plan gate — `stage=plan inventory=15 manual=2 scoped=0 errors=0`.

Точные команды/выводы: `tests-2.58.235.json`, `test-output/`.

## 5. Manifest dry-run

`manifest-dry-run.json` (exit 0, tracked tree clean):

- `deployed_sha=f2c39e36921a0487c5e645f01184c60895bc68a6`
  (bump/content tip; docs-коммит выше),
- `version=2.58.235`, `effect=deploy`, `dirty_tracked=false`,
- `previous_sha=56e2450d2c02e3d8ac595b9a412a121127f57b57`,
  `previous_version=2.58.234`,
- `release_branch=release/exp-e-trunc-lag-2.58.235`.

Предыдущий `.deploy/release.json` восстановлен локально из
документированного deployed-состояния (production не читался), после
прогона `.deploy` удалён.

## 6. Rollback

- Code-only: checkout/rollback на `56e2450d2` (2.58.234), restart.
- Новый payload-ключ `semantic_fresh` старым кодом **игнорируется**:
  таблицы/DDL не менялись, источник/история не удаляются.
- Возможен повторный проход строк свежей полосы старым алгоритмом
  (main-cursor), без потери данных; `record_feedback` идемпотентен по
  `dedup_key`, дубли уроков не создаются.
- Настройки/ключи/чатовые override не откатываются; PG backup/DDL не нужны.
- Runbook: `postdeploy-runbook-2.58.235.md`.

## 7. RFL

- Реальный production-спад lag/throughput не измерен до деплоя; после
  выката — bounded 2–3 прохода 15–30 мин, без подмены нулём и без
  заявления о полном 5-дневном дренаже.
- Реакция конкретной модели на бюджет 8192/уменьшенные окна не проверялась
  против провайдера.
- Archive re-anchor для чата без `archive_start` намеренно не выполнялся;
  fresh-полоса сохраняет старый хвост и честный lag.
