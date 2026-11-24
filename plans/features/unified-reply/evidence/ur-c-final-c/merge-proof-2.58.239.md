# Merge-proof 2.58.239 — UR-INTEG-MERGE / UR-G

- Роль: **Builder** (assembly, read-only merge proof).
- Локальное время: **2026-11-24 17:50 +12:00** (2026-11-24 05:50Z).
- Base/rollback: `b81ec52aa4834896c8e901269e69058612ae81bf` (2.58.238).
- Release candidate: `6123a1469bbfe1019d0a1ecdb65c383988444655`
  (bump-коммит поверх content `a2624fe4f`).
- Branch: `release/unified-reply-ur-c-2.58.239`.
- Deploy/SSH/LLM/prod не вызывались.

## 1. Ancestry

```text
git merge-base --is-ancestor b81ec52aa 6123a1469   # exit 0
git rev-list --count b81ec52aa..6123a1469           # 52 commits
base                                              # b81ec52aa
RC                                                # 6123a1469
```

Base является предком RC; release-ветка содержит только линейную
UR/QRNG-UI линию плюс version-bump.

## 2. Diff scope

`git diff --name-only b81ec52aa..6123a1469` — **90 files**, без удалений
(только `M`/`A`):

| Категория | Файлов | Содержание |
|---|---:|---|
| `config/settings.py` | 1 | `APP_VERSION` 2.58.239 + version-комментарий |
| `plans/docs/param-registry-round1025.*` | 2 | generated TSV/meta, переэмитированы штатным генератором |
| `plans/features/unified-reply/evidence/**` | 18 | UR evidence, включая cluster C и merge-proof |
| `plans/features/vmq-onto-01/evidence/qrng-p5-ui/**` | 2 | QRNG UI-06/07 evidence |
| `services/**` | 12 | UR-A/B/C/UR-13 product fixes (`claim_envelope`, `direct_*`, `llm_client`, `mca_retrieval_context`, `model_capacity`, `auto_budget`, `param_catalog`, `turn_trace`, `agentic_events`) |
| `tests/js/**` | 8 | UR/UI-21 + QRNG UI node tests + 4 version-pin hotfix tests |
| `tests/*.py` | 43 | UR-A/B/C/UR-10..23 + version-pin wave |
| `tools/**` | 2 | m4b2/m4b3 status e2e version pins |
| `web/**` | 2 | `web/app.js`, `web/index.html` (UR-C/UI-21 + QRNG UI) |

Проверки границ:

```text
QRNG paths: plans/features/vmq-onto-01/evidence/qrng-p5-ui/ui06|ui07.md,
            tests/js/qrng_p4_random_ui_test.js,
            tests/js/qrng_ui07_provider_block_test.js,
            tests/js/qrng_ui_state_test.js
services/*random*|qrng|ibm|p5b: отсутствуют
plans/current_task.md, plans/owner_inputs/...:
    git diff --quiet b81ec52aa..RC -- ...  # exit 0 (byte-identity)
plans/features/unified-reply/requirements-map.json,
plans/progress_scope.json, plans/workflow_state.md:
    не входят в diff
.deploy/release.json: вне diff; dry-run manifest удалён после проверки
```

QRNG backend/API/DB/IBM/P5B в candidate отсутствует: изменены только
web/tests/evidence UI-06/07.

## 3. History / rollbacks

```text
git rev-list --merges b81ec52aa..6123a1469
61d54788fe546149cf78e96ee79cb8576ddefb97   # merge: B1 UR-13/13.8 into UR line
b054b8d35cfacc5df351511c5a50116d97dbe25e   # merge: UR main into UI-21
```

Оба merge — внутри UR-линии. Коммитов с revert/rollback чужих изменений в
диапазоне нет (`git log --oneline` без revert/rollback-сообщений); удалённых
файлов в diff нет.

## 4. Version-only delta

`git diff a2624fe4f..6123a1469`:

```text
32 files changed, 35 insertions(+), 35 deletions(-)
non-version changed lines: 0
```

Все изменённые строки — только version-токены (`2.58.238` → `2.58.239`)
в 24 Python pins, 4 JS hotfix pins, 2 tools, `param-registry` meta и
`config/settings.py`; продуктовое поведение и схема не менялись.

## 5. Schema

- `services/database.py`, `services/pg_db.py`, `services/chat_lore_store.py`
  не изменялись (`git diff --quiet` exit 0).
- SQLite `PRAGMA user_version = 48` (in-memory initialize).
- PostgreSQL DDL: **0**.

## 6. Verdict

Merge-proof **PASS для assembly**: ancestry подтверждена, diff scope — только
UR + QRNG UI + version/evidence, foreign rollbacks/QRNG backend отсутствуют,
owner-файлы byte-identical. Независимый delta review bump/RC и PM rebind
66 UR-C строк на actual RC остаются обязательными следующими шагами; это
не deploy и не разрешение на выкат.
