# Release 2.58.237 — M5A semantic stage (assembly)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (не задеплоено).
Scope: code-only M5A — honest semantic stage status (`completed/partial/
unavailable`), durable partial reasons, NULL-watermark/limit/edge proofs.
Без DDL/ACL/UI/embedding, без M5B.

- Deployed base / rollback: `e0cc932469e92fb0c79aa3ef4f7045e85257e695`
  (2.58.236).
- Reviewed candidate: `d1315bf8698afc526eab7699998894021fd2211b`;
  code `de6472e1f`; review `8238a33eb` **APPROVED**.
- Release branch: `release/mod-acl-m5a-2.58.237`.
- Content tip (2 cherry-picks): `2c39abed2`.
- Bump: `c7db72be07f4ecae27410460e9e162227da8df01`.
- Evidence/docs commit: этим коммитом выше bump.

## 1. Cherry-picks (linear, 0 merges)

| Source | Release commit |
|---|---|
| `de6472e1f` M5A code/tests | `5c17da5f1` |
| `d1315bf86` evidence | `2c39abed2` |

```
git diff --quiet d1315bf86 HEAD -- \
  services/mca_experience_jobs.py \
  tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py  # exit 0
git rev-list --merges e0cc93246..HEAD | wc -l             # 0
```

## 2. Version wave 2.58.236 → 2.58.237

- `APP_VERSION="2.58.237"`; `Prior 2.58.236` сохранён исторически.
- **32 files, 35 insertions / 35 deletions**; все пины (hotfix7–10,
  m4b2/m4b3, 24 Python version-pin).
- BOM/CRLF `config/settings.py` сохранены; `git diff --check` exit 0.
- `git grep 2.58.236` — только historical Prior/evidence; действующих
  пинов 2.58.236 в tests/js/tools нет.

## 3. DDL / schema

- Изменён только `services/mca_experience_jobs.py` + M5A tests/evidence.
- `services/database.py`, `services/pg_db.py`,
  `services/chat_lore_store.py` не менялись; новых таблиц/колонок/индексов
  нет. SQLite **48**, PG DDL **0**.
- Deploy/rollback code-only; PG backup/DDL не нужны; SQLite predeploy
  backup — существующим механизмом `keep=2`.

## 4. Tests

- M5A: **22 passed** (`test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`).
- Block A/B/C: **49 passed**.
- Related Experience/смежные 18 файлов: **299 passed, 1 deselected**.
- Version-pin wave: **856 passed, 4 failed** — те же 4 node ID,
  документированные для base 2.58.235/236; не candidate-regression.
- JS hotfix7–10: 4× OK; schema smoke 48; `py_compile` 0;
  `git diff --check` 0; plan gate `inventory=279 manual=102 scoped=0 errors=0`.

## 5. Manifest dry-run

`manifest-dry-run.json`: `deployed_sha=c7db72be0…`, `version=2.58.237`,
`previous_sha=e0cc93246…`, `previous_version=2.58.236`,
`release_branch=release/mod-acl-m5a-2.58.237`, `dirty_tracked=false`.
Предыдущий `.deploy/release.json` восстановлен из документированного
deployed-состояния 2.58.236, после dry-run удалён.

## 6. Rollback

- Code-only: `e0cc93246` (2.58.236), restart. DDL/настройки/ключи/override
  не откатываются; история/данные не удаляются.
- Новые payload-поля `semantic_stage_status/partial/partial_reasons`
  старым кодом игнорируются; cursor/retry/truncation state сохраняются.
- M5B/ACL-сериализованные файлы не менялись; ручной DDL не требуется.

## 7. Status / RFL

- Review `8238a33eb`: **11 VERIFIED / 3 REVIEW / MAC-M5-01 PENDING**;
  `MAC-M5-01` требует M5B (`MAC-EXP-08`) и M5C/native question.
- RFL: production-lag/model 8192, точный `worker_lost` trigger,
  archive re-anchor; 3 REVIEW-строки не выдаются за VERIFIED.
