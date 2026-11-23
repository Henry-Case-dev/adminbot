# Release 2.58.238 — M5A 3 REVIEW + M5B (assembly)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (не выкачен).
Scope: code-only — закрытие 3 REVIEW-строк M5A + M5B shared review
(`MAC-EXP-08`). M5C/M6 не начаты.

## 1. Binding

- Deployed base / rollback: `f4040266013bb19374c24c39ed001ba1ccb815f4`
  (2.58.237).
- M5A: branch `fix/m5a-review-rows-2.58.237`, tip
  `19a4fabbcd4fa4a8c7b25fa746f220ab51a42811`, code
  `0907dbae615ecb4796ed716c1b07f9dbc00eb33f`, review `86dc3f32e`
  **APPROVED**; 3 REVIEW-строки закрыты → VERIFIED.
- M5B: branch `feat/m5b-exp-08`, tip
  `a8a3d75a2c4e11c5993ad988436ed25d70a22414`, candidate
  `697a28f9ec17181377a2e219a10af34e083d1fb3`, review `e13249472`
  **APPROVED**; `MAC-EXP-08` REVIEW/RFL, `MAC-M5-01` PENDING.
- Release branch: `release/mod-acl-m5a3-m5b-2.58.238` от `f40402660`.
- Content tip (6 cherry-picks): `f5567fccd4d7ebd95438a3f33754ce234929fb9e`.
- Bump: `7a36f4fc847f4f51246457c02300d047acd565d6`.
- Evidence/docs commit: этот коммит (после bump).

## 2. Cherry-picks (linear, 0 merges)

| Source | Release commit |
|---|---|
| `0907dbae6` M5A code/tests | `065930d0c` |
| `19a4fabbc` M5A evidence | `9d8ed6a1f` |
| `4b79360c7` M5B code/tests/evidence | `9a3723056` |
| `d455d9025` M5B docs binding | `e25e12a7f` |
| `697a28f9e` M5B R1 F01 fix | `64bd8f3e4` |
| `a8a3d75a2` M5B docs binding | `f5567fccd` |

`d455d9025` — фактический parent `697a28f9e`; в присланном списке он
отсутствовал, но без него R1-коммит не применяется к evidence-файлам.
Продуктовый код/тесты от этого не меняются.

Проверки равенства:

```
git diff --quiet 0907dbae6 HEAD -- \
  services/experience_diagnostics.py \
  tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py   # exit 0
git diff --quiet 697a28f9e HEAD -- \
  services/mca_experience_jobs.py \
  tests/test_mod_acl_ux_m5b_shared_review.py               # exit 0
git rev-list --merges f40402660..HEAD | wc -l              # 0
```

M5B evidence-файл `evidence/m5b/mac-exp-08.md` нормализован N05
(CRLF→LF, docs-only); остальные M5B-файлы совпадают с `a8a3d75a2`.

## 3. Version wave 2.58.237 → 2.58.238

- `APP_VERSION="2.58.238"`; комментарий описывает M5A3+M5B и сохраняет
  `Prior 2.58.237`.
- **32 files, 35 insertions / 35 deletions**; 24 Python version-pin,
  4 JS hotfix, m4b2/m4b3, `param-registry` meta.
- BOM/CRLF `config/settings.py` сохранены; `git diff --check` exit 0.
- `git grep 2.58.237` — только historical evidence (M5A/M5B evidence,
  `release-2.58.237`, previous-version ссылки в `release-2.58.238`);
  текущих пинов нет.
- JS hotfix7–10: 4/4 OK.

## 4. DDL / schema

- Schema-файлы (`services/database.py`, `services/pg_db.py`,
  `services/chat_lore_store.py`) не изменялись.
- SQLite schema smoke: **48**; PostgreSQL DDL: **0**.
- Deploy/rollback code-only; PG backup/DDL не требуются; SQLite predeploy
  backup обязателен, `keep=2`.

## 5. Tests

- M5A: **24 passed** (`test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`).
- M5B: **11 passed** (`test_mod_acl_ux_m5b_shared_review.py`).
- Combined M5B+M2 resolver/consumers/capability+M5A: **68 passed**.
  Присланное ожидание 66 устарело: M5A теперь 24, а не 22 (+2).
- Related Experience 18 файлов: **301 passed, 1 deselected**;
  вместе с M5B — **312 passed, 1 deselected** (ожидание 310 устарело по
  той же причине +2 M5A).
- Version-pin wave (24 Python tests): **856 passed, 4 failed** — те же 4
  node ID, что на base 2.58.235/236, не candidate-regression:
  - `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
  - `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
  - `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
  - `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`
- `py_compile` 0; `git diff --check` 0; plan gate
  `inventory=279 manual=102 scoped=0 errors=0`.

## 6. Manifest dry-run

`manifest-dry-run.json` (на bump-коммите, чистое tracked-дерево):

- `deployed_sha=7a36f4fc8…`, `version=2.58.238`;
- `previous_sha=f40402660…`, `previous_version=2.58.237`;
- `release_branch=release/mod-acl-m5a3-m5b-2.58.238`;
- `dirty_tracked=false`.

`.deploy/release.json` production checkout не изменялся: для dry-run
использован временный previous-manifest, удалён после прогона.

## 7. Rollback

- Code-only: `f40402660` (2.58.237), restart.
- DDL/миграций нет; SQLite schema 48, PG DDL 0.
- Данные M5A/M5B аддитивны: semantic stage fields в payload, per-chat
  lessons/feedback/candidates. Rollback не удаляет их; чтение старым
  кодом безопасно.
- M5B gates читают hot per-chat resolver; stored overrides не
  переписываются.

## 8. Status / RFL

- M5A: 3 REVIEW-строки VERIFIED по review `86dc3f32e`; остальные строки
  M5A не понижены.
- M5B: `MAC-EXP-08` **REVIEW/RFL** (live preprod-проверка не выполнялась);
  `MAC-M5-01` **PENDING** (M5C/native question).
- M5C/M6 не начаты; эпик M5 не DONE.
- Deploy/SSH/LLM/prod не выполнялись.

## 9. Evidence

- `tests-2.58.238.json` — машиночитаемые проверки.
- `manifest-dry-run.json` — фактический dry-run.
- `postdeploy-runbook-2.58.238.md` — runbook без выполнения.
