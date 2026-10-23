# BIND-DEPLOYED-258113 — привязка фактического деплоя 2.58.113 к картам

**Дата:** 23.10.2026, 18:25 +12:00.
**Лейн:** `PM-BIND-DEPLOYED-258113` (writer: только карты / реестр / binding; код и прод не трогались).
**Релиз:** `2.58.113 @ e4ee54f3cc12c39492c60eb2a0865f5da429454c` (bump 2.58.112 → 2.58.113).

## 1. Источник production-фактов

Факты взяты из `DEPLOY-258113` — коммит `b92226cf` (`docs(release-258113): DEPLOY-258113 production evidence`).

Живой `plans/features/_audit-2026-10-23/release-258113/deploy.md` после `b92226cf`
продолжает дописываться лейном `VERIFY-258113-B` (postcheck B), поэтому его SHA-256 меняется.
Чтобы evidence не указывал на движущийся файл, создан замороженный снимок:

`plans/features/_audit-2026-10-23/release-258113/deploy-frozen-b92226cf.md`
SHA-256 `11667c19a8c000201431333b00c9f8b2f5e758359653e6feaeec6519bcd47209`
(тело — байт-в-байт `git show b92226cf:.../deploy.md`, sha256 тела `19fc2653...`, + provenance-заголовок).

Подтверждённые факты деплоя:

- healthz **200** `{"status":"ok","version":"2.58.113"}`; `systemctl active/running`, MainPID **715288**, `NRestarts=0`, `ExecMainStatus=0`.
- adopt: `gen=1 fp=96f80838f683`; `EMBEDDING_COMPAT_ADMITTED checked=12 mean=1.0 min=1.0 hit5=1.0`;
  поколение `graph_facts_vec` = `active`, `config_revision=adopt1:…`, `superseded_at=NULL`.
- полной перевекторизации **не было**: `EMBEDDING_GENERATION_BUILD_START=0`; старый job переведён в `cancelled`.
- backfill: `graph_facts_vec 16003 → 16503`, backlog `4234 → 3734 (T2) → 3619 (B11)`, `backlog_status=ok`, `re-embedded 500 facts`.
- журнал после рестарта: `ERROR=0`, `CRITICAL=0`, `Traceback=0`, `database is locked=0`.
- API `generation.graph_facts_vec`: `state=active`, `serviceable=true`, `reindex_required=false`, canary `12/1.0/1.0/1.0`.
  Агрегированный `compat` пуст (legacy `graphrag_rebuild.payload` без `index`) — отдельная находка панели, не блокер.
- реальный семантический поиск: top-5, cosine `0.832/0.8047/0.7973/0.7953/0.7952` (не FTS-only).
- B11: Summary `degraded` (не ложно-`ok`), backlog `3619`; `ok=6, attention=2, unknown=1, degraded=1`.
- откат: `fbf9013d` (2.58.111), backup БД `pre_deploy_258113_1792734640.db`, ΔDDL=0.

Ограничение источников: в `deploy.md` **нет** снимков Factory / active PG / effective, эффективного model payload
и статистики уточнений; B11 зафиксировал `pg_available=false` (DSN не предоставлялся).

## 2. Итоговая таблица привязки

| Карта | candidate | deployed | required | Release-gate | EXIT | Итог |
|---|---|---|---|---|---|---|
| `embed-identity-compat` | `e4ee54f3` | `e4ee54f3` | **59 VERIFIED** | `check --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3` | **0** | задача **VERIFIED** |
| `asap2-direct-chat` | `e4ee54f3` | `e4ee54f3` | 74 VERIFIED / 34 PENDING / 1 READY_FOR_LIVE | то же | **1** (35 errors) | остаётся **BUILDING** |
| `asap-speech-arch` | `e4ee54f3` | `e4ee54f3` | 80 VERIFIED / 35 PENDING | то же | **1** (177 errors) | остаётся **BUILDING** |

Команда выполнялась из корня проекта:
`py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --map <map> --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3 --repo .`

## 3. embed-identity-compat — что закрыто

| Строка | Было | Стало | Evidence |
|---|---|---|---|
| `ACC-10` | READY_FOR_LIVE | **VERIFIED** | `deploy-frozen-b92226cf.md` (sha `11667c19…`): adopt + canary + реальный поиск; плюс pre-deploy `evidence/resolver-pre/report.md` |
| `ACC-11` | READY_FOR_LIVE | **VERIFIED** | тот же production-evidence + pre-deploy resolver |
| `IDENT-02`, `CANARY-03`, `DEC-09` | VERIFIED | VERIFIED | sha `gaps-closure.md` исправлен на актуальный `3345a14d…` (файл в master после пина `60789cff`); прежние `6e409050…`/`9f20785…` устарели |

`deployed_commit` карты = `e4ee54f3`. Evidence-артефакты релиза (`guards.txt`, `focused-*.txt`, `rollback.md`,
`review-rel.md`, `deploy-frozen-*.md`) добавлены в рабочее дерево; на них ссылаются VERIFIED-строки карты.
Release-gate: **`stage=release inventory=43 manual=29 scoped=59 errors=0`, EXIT 0**.

## 4. asap2-direct-chat — что реально закрывает деплой

- `candidate_commit` и `deployed_commit` = `e4ee54f3`.
- `git diff 34af90ff e4ee54f3 -- services/direct_l1.py services/direct_chat_service.py services/claim_envelope.py services/chat_prompts.py services/prompt_migrations.py services/prompt_registry.py tests/test_asap2_clar_contract.py` — **пусто**; код asap2 байт-идентичен, поэтому 163 evidence-записи перепривязаны к `e4ee54f3`.
- **Ни одна из спорных строк не переведена в VERIFIED:** в `deploy.md` нет Factory/active PG/effective, payload и статистики уточнений.
  - `DONE-D9` — остаётся `READY_FOR_LIVE`: deploy/health/rollback-точка доказаны, но «разрешённая демонстрация финального payload» и статистика уточнений отсутствуют.
  - `MIGR-INSPECT`, `MIGR-EFFECTIVE`, `MIGR-PAYLOAD`, `MIGR-BOTHSIDES`, `MIGR-DEVOPS`, `DONE-D4` — остаются `PENDING` с прежними `next_check`.
- Release-gate: **EXIT 1**, 35 errors = 34 PENDING + `DONE-D9` (READY_FOR_LIVE). `DONE` не ставится.
- Остаток до DONE: 34 агентские/postdeploy-строки (9 сценариев+парафразы, 5 MIGR/DevOps-снимков, T20/T24, DONE-D1/D5/D6/D8/REPORT и др.) + postdeploy payload/effective для `DONE-D9`.

## 5. asap-speech-arch — W4 и postdeploy

- `deployed_commit` = `e4ee54f3` (было `fbf9013d` = 2.58.111).
- W4/§8 `UI-U01..U09 + UI-P2` — **9/9 VERIFIED**, evidence-bound к `e4ee54f3`; review-гейт по W4-слайсам ранее **EXIT 0**.
- Postdeploy W4 (реальный Telegram WebView / Android, FPS) — **необязательное наблюдение владельца**, не гейт; не выдавалось за VERIFIED.
- `INIT-48H` (48-часовая прод-наблюдаемость) остаётся `PENDING` — окно ещё не закрыто.
- Release-gate по всей карте: **EXIT 1**, 177 errors: 35 PENDING-строк других слайсов + legacy-evidence 80 VERIFIED-строк, привязанных к предыдущим релизным коммитам (`fbf9013d`, `0f3ed53a`, …), а не к `e4ee54f3`. Это не регрессия W4; для полного release-stage потребуется отдельная перепривязка остальных слайсов.

## 6. Прогресс по `plans/progress_scope.json`

`py -3 C:\Users\main\.config\opencode\tools\workflow_progress.py --scope-file plans/progress_scope.json`:

- Поручения владельца: **6/14 (42%)**.
- Этапы: **87/116 (75%)**.
- Требования: **1181/1428 (82%)**.
- Ждут postdeploy-проверки: **8**; необязательная обратная связь: 21 (вне знаменателя).

Изменения реестра: `embed-identity-compat` → `VERIFIED`; `asap2-direct-chat` и `asap-speech-arch` остались `BUILDING` с обновлёнными note. Задачи не удалялись.

## 7. Что осталось до DONE

| Задача | Остаток |
|---|---|
| `embed-identity-compat` | **DONE** (59/59 VERIFIED, release EXIT 0) |
| `asap2-direct-chat` | 34 PENDING + `DONE-D9` postdeploy payload/effective/статистика; release EXIT 1 |
| `asap-speech-arch` | 35 PENDING (W1/W2/W3/W5, I-серия и др.), `INIT-48H`; release EXIT 1; W4 закрыт |
