# Release 2.58.261 — FTS index integrity (P0-FTS-INDEX-INTEGRITY-01) + VMQ D1 (period-fill)

- **Дата сборки:** 2026-11-28
- **Роль:** Builder (сборка релиза, **без деплоя**)
- **Основание:** два независимо проверенных кандидата; файлы не пересекаются.
  - FTS — `afaac3e5845c3c6f96c9d7b10a03e0e81da147ee` (код+тест), evidence
    `plans/features/p0-fts-index-integrity-01/evidence/2026-11-28/audit-followup.md`
    + `evidence/builder-2026-11-28.md` (7 тестов, полный аудит путей мутации).
  - VMQ D1 — `b34cd21d184f28a0442eee21904eb9f8d4f69c11`, evidence
    `plans/features/vmq-onto-01/evidence/vmq-mem/d1-period-fill-2026-11-28/**`
    (RED/GREEN, 3 мутации, 653 passed/1 pre-existing).
- **База (deployed):** `7b68bd25d6f35df23695090c9a049c1173210987` = **2.58.260**
  (прод подтверждён read-only: `GET https://admin-bot.duckdns.org/healthz` →
  `{"status":"ok","version":"2.58.260"}`; `7b68bd25` = docs-only evidence-коммит
  поверх продуктового tip 2.58.260 `e967d1d08`, `git diff e967d1d08..7b68bd25 --
  services/ tests/ web/ bot.py manage.py config/` = пусто).
- **Ветка:** `release/2.58.261`
- **Tip релиза (bump):** `534c3c5c53c183ebbd43894aaf5fdf489f300cd7`
- **Tree product-коммита:** `e9b2e05018bbf977191b509955a174156f946e3e`
- **Tree базы:** `9fe06905c6a83cc8c1ba7b40b345ba6850f9c7be`
- **Статус:** ASSEMBLED, не деплоился. Деплой — DevOps/Orchestrator.

## 1. Состав релиза (от deployed-базы)

`raw/changed-files.txt`, `raw/product-delta.txt`: **53 файла**, из них
продуктовых (вне `plans/`) — **35**.

| Часть | Файлы | Суть |
|---|---|---|
| **FTS продукт** | `manage.py` (+82/−0), `services/database.py` (+7), `services/dossier_rebuild_jobs.py` (+91/−…), `services/memory_rebuild.py` (+125/−0, новые `inspect/repair`) | синхронизация external-content FTS5 `graph_facts_fts` в путях `INSERT OR REPLACE`/restore snapshot, индекс нового портрета досье; idempotent `memory fts-check|fts-repair` |
| **FTS тест** | `tests/test_fts_index_integrity_floor.py` (новый, 293 строки, 7 тестов) | behavioral RED/GREEN: orphan docsize, старые токены, portrait insert, repair idempotent, CLI |
| **VMQ D1 продукт** | `services/direct_chat_service.py` (+12/−2) | origin-фильтр профиля выполняется **до** удаления `period_fill`-строк; принятая периодная строка не теряется |
| **VMQ D1 тест** | `tests/test_vmq_mem_slice_d.py` (+67) | `TestSubjectHalf`: D1-пара (потеря строки + дифференциальный контроль) |
| **Bump 2.58.261** | 29 файлов | `config/settings.py`, `param-registry-round1025.meta.md`, 25 test-пинов, 2 tools |
| **Evidence** | `plans/features/p0-fts-index-integrity-01/evidence/**`, `plans/features/vmq-onto-01/evidence/vmq-mem/d1-period-fill-2026-11-28/**`, этот отчёт | доказательства инкрементов (не продуктовые) |

Посторонних продуктовых файлов нет: `web/**`, `bot.py`, `handlers/**`,
`services/pg_db.py`, промпты и карты не менялись.

## 2. Байтовая идентичность reviewed-кандидатам

`raw/identity.txt`, `BYTE_IDENTICAL_ALL=True` (сравнение по git-blob, канонические
байты; `git diff <candidate> -- <files>` = пусто).

| Срез | Файл | blob tip = blob candidate |
|---|---|---|
| FTS `afaac3e58` | `manage.py` | `8fef5e067f76…` ✅ |
| FTS | `services/database.py` | `df600c579590…` ✅ |
| FTS | `services/dossier_rebuild_jobs.py` | `2675e5a175bc…` ✅ |
| FTS | `services/memory_rebuild.py` | `bcf353f3071e…` ✅ |
| FTS | `tests/test_fts_index_integrity_floor.py` | `8edc5461a221…` ✅ |
| VMQ D1 `b34cd21d1` | `services/direct_chat_service.py` | `389aae2de05f…` ✅ |
| VMQ D1 | `tests/test_vmq_mem_slice_d.py` | `b42048bb560c…` ✅ |

## 3. Bump — version-only (доказано)

```
raw/bump-verify.txt
bump_commit=534c3c5c53c183ebbd43894aaf5fdf489f300cd7  parent=740d7d6f099fdcd1915e54a6b47162da8174e5bf
files=29  additions=34  deletions=34
non_version_changed_lines=0
pairs_differing_only_by_version=34 / 34
version_only_bump=OK
eol_settings: CRLF 3665, bare LF 0, size 362807 (base и tip одинаковы)
APP_VERSION = "2.58.261"
```

Набор пинов **не расширился**: те же 29 файлов / 34 вхождения, что и в bump
2.58.260 (`config/settings.py` ×1, `param-registry-round1025.meta.md` ×1,
`test_q07_field_stats.py` ×3, `test_webapp_round1026_polygon.py` ×2,
`ui_mod_acl_m4b2_status_e2e.py` ×3, остальные 24 файла ×1). Замена побайтовая:
каждая пара ± строка отличается только литералом версии.

## 4. Routes-пин (ROUTES_SHA256_F11) — re-pin не нужен

```
raw/routes-pin.txt
routes_sha256_head=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_sha256_base_7b68bd25=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_byte_identical=True
ROUTES_SHA256_F11=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
pin_matches_head=True
routes_changed_in_delta=False
decision=no re-pin (routes.py and pin unchanged)
```

## 5. DDL Δ = 0, `user_version` 49

```
raw/ddl-check.txt
changed_migrations_or_pg_db=[]         # migrations/ отсутствует, services/pg_db.py не менялся
ddl_keyword_hits_in_database.py_added_lines=[]   # ни CREATE/ALTER/DROP/TRIGGER, ни *_SCHEMA_VERSION
max_schema_constant=49 (_SCHEMA_VERSION_SELF_DIAG_SAMPLES)
user_version_target=49  # не менялся этим релизом
ddl_delta=0
```

`services/database.py` изменён только FTS-синхронизацией (7 строк),
схема/миграции не менялись → миграций при деплое нет, **rollback code-only**.

## 6. Прогоны (эта сессия, `C:\Code\Python\adminbot\.venv\Scripts\python.exe`,
`cwd` = релизный worktree; работа только на временных БД, прод read-only)

| Набор | Результат | Raw |
|---|---|---|
| FTS (7 тестов) `tests/test_fts_index_integrity_floor.py` | **7 passed** (6.5 s) | `tests-fts.txt` |
| `test_vmq_mem_slice_d.py` + `test_vmq_oldrow_person_delivery.py` + `test_ur_c_3_real_fts.py` | **72 passed** (10.7 s) = 43 + 19 + 10 | `tests-vmq-slice-d.txt` |
| VMQ breadth, часть 1 (9 файлов: m1, mem07, period_intent, rc1–rc6a) | **95 passed** (16.9 s) | `tests-breadth-1.txt` |
| VMQ breadth, часть 2 (9 файлов: rc7, retrieval_fixes, slice_b/c/d, oldrow, recent_window, time09, voice_writer) | **222 passed, 1 failed** (40.6 s) — единственный red предсуществующий (ниже) | `tests-breadth-2.txt` |

Числа совпадают с независимыми прогонами срезов: FTS evidence — 7 passed;
VMQ D1 evidence — Slice D 43, oldrow 19, `test_ur_c_3_real_fts` 10, полный
набор 653 passed/1 failed.

**Предсуществующий red (сверяется с базой `7b68bd25`):**
`tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`
— `AssertionError: assert 4 <= 2` (строка 152). Тот же red документирован на базе
`1defb4e05` в VMQ D1 evidence §6 (тест Slice B от 15.11.2026 утверждает потолок
`accepted`, тогда как TIME-03/P-OLDROW трактуют `slots` как ресурсный предел
вызывающего). К D1/FTS не относится, кандидатом не затронут — BACKLOG_ONLY.

### 6.1 Ещё не выполнено (честная пометка, этап 2)

Пины/реестр (25 файлов, ожидается 864/6), `gen_param_registry_round1025.py
--check`, startup smoke (10 файлов, 81), `test_round106_ia_smoke` (42/3),
dossier/cleanup/rebuild/commands (210), смежные память/RAG/БД (25 файлов).
Их результаты и сверка red-ов по node id с базой `7b68bd25` будут дописаны в
этот же файл и в `raw/` следующим коммитом; `SHA256SUMS` пересчитывается.

## 7. Manifest dry-run (на итоговом tip)

Затравка `.deploy/release.json` = фактический прод (`deployed_sha=7b68bd25…`,
`version=2.58.260`, healthz-подтверждение выше). `.deploy/` не отслеживается git
и в коммит не входит; боевой манифест DevOps пишет на сервере по фактическому HEAD.

```
raw/manifest-deploy.json
{
  "deployed_sha": "534c3c5c53c183ebbd43894aaf5fdf489f300cd7",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "7b68bd25d6f35df23695090c9a049c1173210987",
  "previous_version": "2.58.260",
  "release_branch": "release/2.58.261",
  "schema": 1,
  "version": "2.58.261"
}
```

`raw/manifest-rollback.json` — то же с `effect=rollback`, `previous_*` =
`7b68bd25` / 2.58.260 (откат возвращает на выложенную версию).
**Rollback = code-only** (DDL Δ=0, схема на проде уже v49).

## 8. Порядок для DevOps (НЕ выполнен)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD        # ожидается 7b68bd25 (2.58.260)
git pull --ff-only                          # до tip ветки release/2.58.261
python tools/release_manifest.py            # effect=deploy, previous=7b68bd25
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz     # ожидается version 2.58.261
python manage.py disk audit && python manage.py disk cleanup --apply
```

FTS-процедура (write — только производный индекс):

```bash
python manage.py memory fts-check --db local_database.db     # BEFORE: фиксируем ok/facts/docsize/orphan
sqlite3 local_database.db "SELECT COUNT(*), MAX(id), SUM(LENGTH(fact)) FROM graph_facts;"
python manage.py memory fts-repair --db local_database.db    # rebuilt=yes, orphan=0, missing=0
python manage.py memory fts-check --db local_database.db     # ok=True, rc=0
sqlite3 local_database.db "PRAGMA integrity_check;"          # ok
sqlite3 local_database.db "SELECT COUNT(*), MAX(id), SUM(LENGTH(fact)) FROM graph_facts;"   # те же счётчики
```

Ожидаемое на данных 2.58.260: `fts-check` до ремонта может дать `ok=False`
(`orphan_docsize>0`, `db_integrity` с `malformed inverted index`); после
`fts-repair` — `ok=True`, повторный repair — `rebuilt=no`. Счётчики `graph_facts`
(COUNT/MAX(id)/SUM(LENGTH(fact))) между шагами **не меняются** — пользовательские
строки не трогаются, правится только FTS5-индекс.

## 9. Ограничения

- Деплой не выполнялся; прод не затрагивался (только read-only HTTP healthz).
- Расширенные наборы (пины/реестр, startup smoke, round106, dossier/cleanup,
  смежные память/RAG/БД) и сверка их red-ов с базой `7b68bd25` — этап 2 (п. 6.1).
- Ретроспективно привязать каждую историческую orphan-строку FTS к конкретному
  rollback нельзя (зафиксировано в FTS evidence); однократный `fts-repair`
  чинит накопленное, код предотвращает повтор.

## Артефакты

`raw/`: `identity.txt`, `changed-files.txt`, `product-delta.txt`,
`bump-verify.txt`, `routes-pin.txt`, `ddl-check.txt`, `tests-fts.txt`,
`tests-vmq-slice-d.txt`, `tests-breadth-1.txt`, `tests-breadth-2.txt`,
`manifest-deploy.json`, `manifest-rollback.json`, `SHA256SUMS`.
