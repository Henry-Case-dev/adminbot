# Release 2.58.236 — B03 postdeploy fix (assembly)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (не задеплоено).
Scope: heartbeat/lease, durable per-attempt counters, bounded truncation retry,
tail retry inheritance для Experience. Без нового эпика/очереди, без
DDL/ACL/UI/embedding.

- Deployed base / rollback: `f4ad6902f92a025f62f0054efb0e85c8c64b3844`
  (2.58.235, content `b1036c53d`).
- Catastrophic fallback: `56e2450d2` (2.58.234).
- B03 reviewed candidate: `66ed5cd28363a1ab7b4074f838126b1d0135fcfe`;
  review `e91c9ccfc` **APPROVED_FOR_RELEASE_PREPARATION**.
- Release branch: `release/exp-e-trunc-lag-2.58.236`.
- Content tip (2 cherry-picks): `145f9a67a6ca09465177d3fb8b88aa4bfef9b369`.
- Bump: `ab66b66e7d5995978efd882c75a06434cd1c4dec`.
- Evidence/docs commit: этим коммитом выше bump.

## 1. Cherry-picks (linear, 0 merges)

| Source | Release commit |
|---|---|
| `2b5347af4` fix B03 | `8db82e5db` |
| `66ed5cd28` evidence | `145f9a67a` |

Проверки:

```
git diff --quiet 66ed5cd28 HEAD -- \
  services/mca_experience_jobs.py tests/test_exp_e_trunc_lag_amendment.py \
  tests/test_sxr_i2_fresh_stream_drain.py      # exit 0
git rev-list --merges f4ad6902f..HEAD | wc -l  # 0
```

E-TRUNC/E-LAG из 2.58.235 повторно не cherry-pick'ались: base уже содержит
`819361a71..066909923`. Product tree 236 равен B03 candidate (version excepted).

## 2. Version wave 2.58.235 → 2.58.236

- `APP_VERSION="2.58.236"`; `Prior 2.58.235` сохранён исторически.
- 32 files, **35 insertions / 35 deletions**; все пины (hotfix7–10,
  m4b2/m4b3, 24 Python version-pin).
- BOM/CRLF `config/settings.py` сохранены (BOM EF BB BF, 3645 CRLF);
  `git diff --check` exit 0.
- `git grep 2.58.235` — только historical evidence/Prior/описание базы;
  действующих пинов 2.58.235 в tests/js/tools нет.

## 3. DDL / schema

- Изменён только `services/mca_experience_jobs.py` + тесты/evidence.
- `services/database.py`, `services/pg_db.py`, `services/chat_lore_store.py`
  не менялись; новых таблиц/колонок/индексов нет.
- SQLite **48** (schema smoke `PRAGMA user_version=48`), PG DDL **0**.
- Deploy/rollback **code-only**; PG backup/DDL не нужны; SQLite predeploy
  backup — существующим механизмом `keep=2`.

## 4. Tests

- B03/E-TRUNC amendment: **17 passed** (`tests/test_exp_e_trunc_lag_amendment.py`).
- Релевантные Experience/смежные 18 файлов: **296 passed, 1 deselected**.
- Version-pin wave: **856 passed, 4 failed** — те же 4 node ID, что
  документированы для base 2.58.235 (`release-2.58.235/tests-2.58.235.json`;
  base proof repeated at 56e2450d2), не candidate-regression.
- JS hotfix7–10: 4× OK; `py_compile` 0; `git diff --check` 0;
  plan gate `inventory=15 manual=2 scoped=0 errors=0`.

## 5. Manifest dry-run

`manifest-dry-run.json`:

- `deployed_sha=ab66b66e7d5995978efd882c75a06434cd1c4dec` (bump tip;
  docs выше),
- `version=2.58.236`, `effect=deploy`, `dirty_tracked=false`,
- `previous_sha=f4ad6902f…`, `previous_version=2.58.235`,
- `release_branch=release/exp-e-trunc-lag-2.58.236`.

Предыдущий `.deploy/release.json` восстановлен локально из документированного
deployed-состояния 2.58.235 (production не читался), после прогона удалён.

## 6. Rollback

- Code-only: `f4ad6902f` (2.58.235), restart. DDL/настройки/ключи/override
  не откатываются; история/данные не удаляются.
- 2.58.235-код уже содержит Experience-фикс, поэтому rollback безопасен:
  `semantic_fresh`/новые counters остаются в payload, старый код их
  игнорирует; `record_feedback` идемпотентен.
- Catastrophic fallback `56e2450d2` (2.58.234) — только по отдельному
  решению; ручной DDL не выполняется.

## 7. N01 / backlog / RFL

- **EXP-E-B03-N01 (nonblocking backlog):** при `_fence=0` heartbeat передаёт
  `None`, takeover первой попытки не детектится; terminal write защищён
  store-гардом, payload может быть перезаписан идемпотентно. Код B03 не
  менялся; кандидат одобрен, N01 не блокирует релиз.
- **RFL:** точный триггер `worker_lost` 2.58.235 (registry/watchdog vs
  heartbeat) не воспроизведён; production-lag и модель на 8192 проверяются
  после деплоя bounded 2–3 проходами, без подмены нулём и без заявления о
  полном 5-дневном дренаже.
- Archive re-anchor не выполнялся.
