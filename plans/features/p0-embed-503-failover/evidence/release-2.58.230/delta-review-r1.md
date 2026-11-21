# Delta-review 2.58.230 — REL230-F1: PCI-bound admission блокирует рабочий Google fallback

- Задача: `p0-embed-503-failover` (P0). Ревью независимое; код/тесты/карта/очередь не менялись.
- Кандидат: branch `release/p0-embed-503-failover-2.58.230`, tip `50e01523e2f82f58a5eb7fa48923e63e59627f89`,
  content/bump `9d5cf5173fcf835974205aeeef373766b14a18bd`, code cherry-pick
  `a319431cf2b0361f4219bc1ac4b279cc48b75a98` (reviewed `4ace0a3ae52c321edfd2ef425d933198b6d08377`).
- Base/rollback: `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0).
- Owner input: `plans/owner_inputs/2026-11-22-p0-embed-503-failover.md` (sha256 `d23bf6f9…28f09`) +
  **уточнение** `plans/owner_inputs/2026-11-22-p0-embed-admission-clarification.md`
  («admission — это MSI, PCI — только подключение»; критерий завершения: 503 apinet → Google fallback →
  новый факт получает настоящий вектор и находится через semantic search).
- Дата: 2026-11-22, локальное время 06:20 (+12). Деплой/SSH/LLM/прод не выполнялись.

## 0. Вердикт

**NEEDS_FIXES — блокер REL230-F1 (IN_SCOPE, owner clarification от 22.11.2026).**

Код 5xx/timeout-failover исправлен и проверен, но продуктовый критерий владельца не выполнен: при
одинаковом MSI (`gemini-embedding-001`, dim 3072/4, то же preprocessing/generation) и отличающемся
только PCI (apinet → Google) кандидат **отбрасывает реальный Google-вектор** и оставляет факт text-only.
Причина конкретная: durable admission сравнивается по `conn` (PCI), а не по `space` (MSI), и новый
write-гейт требует `state=compatible`, которого при смене шлюза не бывает без PCI-специфичной записи.
Это не доказанная несовместимость модели; это ложная блокировка штатного fallback.

```json
{
  "artifact": "P0-EMBED-503-FAILOVER delta-review r1",
  "task": "p0-embed-503-failover",
  "ticket": "P0-EMBED-503-FAILOVER",
  "reviewed_tip": "50e01523e2f82f58a5eb7fa48923e63e59627f89",
  "reviewed_content_tip": "9d5cf5173fcf835974205aeeef373766b14a18bd",
  "reviewed_code": "a319431cf2b0361f4219bc1ac4b279cc48b75a98",
  "reviewed_code_source": "4ace0a3ae52c321edfd2ef425d933198b6d08377",
  "base_rollback": "94e227a2c096f4cc7b987c3253563bf0df442d17",
  "base_version": "2.58.229",
  "version": "2.58.230",
  "verdict": "NEEDS_FIXES",
  "deploy_allowed": false,
  "blocking_findings": ["REL230-F1"],
  "in_scope_blocking": ["REL230-F1"],
  "critical_out_of_scope": [],
  "nonblocking": ["REL230-N01", "REL230-N02", "REL230-N03", "REL230-N04"],
  "owner_inputs": [
    "plans/owner_inputs/2026-11-22-p0-embed-503-failover.md",
    "plans/owner_inputs/2026-11-22-p0-embed-admission-clarification.md"
  ],
  "lineage_ok": true,
  "merge_commits_in_range": 0,
  "patch_id_identical": true,
  "product_scope_only_3_files": true,
  "ddl": 0,
  "schema": 48,
  "new_suite": "10/10 passed",
  "profile_15_files": "585 passed / 0 failed",
  "pin_guard": "856 passed / 4 failed (same ids; no candidate-caused pin breach)",
  "red_on_base": "6 failed / 4 passed (4 assertion-level: k-primary repeated instead of failover)",
  "mutants_killed": [
    "M1 exclusion ignored -> 3 failed",
    "M2 route admission always allowed -> 1 failed",
    "M3 no parking/exclusion -> 6 failed"
  ],
  "e2e": {
    "B1": "138/0 OK",
    "B2": "92/0 OK",
    "B3": "131 checks / 1 failure detail_closed (reproduced on base too)"
  },
  "verified": false
}
```

## 1. Линия и состав (проверено самостоятельно)

| Проверка | Факт |
|---|---|
| Ancestry | `94e227a2c` — предок `50e01523e` (`merge-base --is-ancestor` rc=0) |
| Merges в `94e227a2c..50e01523e` | 0 |
| cherry-pick vs reviewed | `patch-id --stable` = `cda0175b…` у обоих; обычный `patch-id` = `482e794b…` у обоих; `git diff 4ace0a3ae a319431cf -- <3 файла>` пусто |
| Product-diff `94e227a2c..9d5cf5173` | только `services/embedding_control_plane.py`, `services/summary_memory.py`, `config/settings.py` |
| DDL / migrations / prompts / web | пусто; `APP_VERSION = "2.58.230"` |
| Bump | 32 файла / 35+ / 35−; все 31 не-settings файла становятся байт-идентичными после нормализации `2.58.230→2.58.229` (включая экранированный `2\.58\.230`) |
| BOM/CRLF | `settings.py`: BOM, 3645 CRLF + 1 bare LF; services/новый тест — LF; профиль не изменился |
| `git grep 2.58.229` вне `plans/` | только историческая строка changelog в `settings.py`; живых пинов нет |
| `git diff --check` | чисто для code `a319431cf^..a319431cf` и bump `2cfd20854..9d5cf5173` (trailing whitespace есть только в сохранённых raw-логах evidence) |

Замечание к evidence: в `assembly.md` указан patch-id `97cbf4ca…` — я его не воспроизвёл ни `--stable`,
ни обычным режимом (`cda0175b…` / `482e794b…`), но инвариант «код идентичен reviewed» доказан прямым
diff и совпадением patch-id между сравниваемыми коммитами.

## 2. Блокер REL230-F1 (IN_SCOPE, owner clarification)

**Severity:** P0 functional (продуктовый критерий владельца), не стиль и не «наблюдение».

**Ожидаемо (owner 22.11.2026, §1–4):** одинаковые MSI/model/dims/preprocessing/generation → fallback
допускается к записи в действующий индекс; PCI — только подключение и не является доказательством
несовместимости. Если доказательства эквивалентности не хватает — **одна** ограниченная canary на
**сохранённых векторах старого индекса**, затем durable admission; иначе text-only. Критерий завершения:
503 → Google → новый факт имеет настоящий вектор и находится semantic search.

**Фактически (кандидат):**

1. Durable admission привязан к PCI. `format_admission(space, conn, …)`
   (`services/embedding_control_plane.py:2872`) пишет `conn`; `admission_valid` (`:2905-2920`)
   требует `admission["conn"] == conn_now` (docstring: «Смена шлюза/квоты → новый PCI → нужна одна
   повторная проба»).
2. При совпавшем MSI и другом PCI резолвер не объявляет совместимость: `resolve_index_compat`
   (`:3586-3593`) не проходит по admission и уходит в ветку `:3631-3637`: `state=insufficient`,
   `reason_code=compat_not_proven`, `class=COMPATIBILITY_UNKNOWN`, `needs_probe=true`,
   `action=retry_canary` — то есть «MSI совпал, допуска нет».
3. Новый write-гейт признаёт только `serviceable && state == compatible`:
   `services/summary_memory.py:3227-3232` (`_serving_route_write_allowed`). Для Google-маршрута
   это `False`.
4. Вектор выбрасывается на всех путях: `_save_graph_fact_embedding` (`summary_memory.py:5671-5679`)
   → `batch.text_only += 1`, `EmbeddingRouteNotAdmitted`, `return False`; archive-путь
   (`~7880`) → `return`; backfill-циклы (`~3769`, `~3855`) → `break` (deferred).
   Строка факта остаётся (FTS), векторной строки нет.
5. Кандидат сам это кодифицирует: `tests/test_p0_embed_503_failover.py:361-376` после реального
   Google 200/3072 утверждает `graph_facts_vec == 0` и отсутствие cache-hit; `:393-404` требует
   вручную переписать `config_revision` на `format_admission(space, conn_google, …)`
   (PCI-специфичный admission), и только тогда запись разрешается. Это ровно та ложная блокировка,
   которую владелец запретил.
6. Внутреннее противоречие проекта: существующий read-гейт `_index_generation_ok`
   (`summary_memory.py:2972-2975`) прямо документирует «смена только API-шлюза при той же модели не
   закрывает индекс (адаптер/квота/хост — провенанс, не пространство)» и остаётся открытым. Новый
   write-гейт требует обратного: индекс открыт на чтение, но запись от другого PCI запрещена.
7. Требуемый владельцем механизм уже существует и не используется для этого маршрута:
   `compat_probe` (`embedding_control_plane.py:3391`) / `_compat_probe_once` (`:3266`) —
   проба **новых** векторов против **старых** строк индекса; `needs_probe=true` /
   `action=retry_canary` и есть сигнал её запустить; durable admission пишется существующим
   adopt-путём (`_ensure_index_compat_inline`).

**Reproducer (мой независимый пробник, temp-копия байтов кандидата, вне продукта):**

```
[probe] live vec rows before: 1
[probe] MSI(served)==MSI(active): True | dims: 4
[probe] PCI primary: f48365cea61e77ef | PCI google: b5cf39b6eb4f6d80
[probe] admission stored: {"space": "b4a553446743779d", "conn": "f48365cea61e77ef", "checked": 12, "mean": 1.0}
[probe] compat: {"state": "insufficient", "reason_code": "compat_not_proven",
                 "class": "COMPATIBILITY_UNKNOWN", "serviceable": false,
                 "needs_probe": true, "action": "retry_canary"}
[probe] write_allowed(google, same MSI): False
1 passed
```

**Последствие:** критерий владельца «новый факт получает настоящий вектор и находится semantic search»
не выполняется; накопленный text-only backlog не восстанавливается через fallback; формулировки
`E503-IDENTITY-01`/`E503-ACCEPT-MATRIX-01` в текущем виде недействительны.

**Не является:** дефектом failover-маршрутизации (она работает), доказательством несовместимости модели,
или вопросом на согласование владельцу. Исправление — минимальное изменение существующего контракта
admission/write-path; без нового identity-механизма, без переиндексации, без смены модели.

## 3. Что проверено и в порядке (чтобы c5 не переделывал)

- **Тесты (tip, мой прогон):** новый `tests/test_p0_embed_503_failover.py` — **10 passed**;
  15-файловый профиль (включая `test_embedding_control_plane_asap4`, `test_embed_fallback_slots_routing`,
  `test_embed_identity_compat*`, `test_summary_memory`, `test_llm_client`, graphrag) —
  **585 passed, 0 failed**.
- **RED на базе** (`git archive 94e227a2c` + новый тест): **6 failed / 4 passed**; 4 падения —
  поведенческие (`assert ['k-primary','k-primary'] == ['k-primary','k-fb1']`), 2 — отсутствие
  `_PROVIDER_UNAVAILABLE_COOLDOWN_S`.
- **Мутации (мои):** убрать `if credential.alias in excluded` → 3 failed; `allowed = True` в
  route-admission → 1 failed; отключить парковку/исключение (`_mark_transport_failure` →
  `return False`) → 6 failed. Все три убиты новым набором.
- **pin-guard (24 Python-файла):** 856 passed / 4 failed, те же ID. 2 canon-падения воспроизведены на базе
  и на master; 2 diff-падения зависят от устаревших ref (`pre-round1026-a1`, `e8646af`). Решающий
  факт: множества `web/`-путей в diff от `e8646af` на базе и на tip **идентичны (37/37)**, а
  candidate-only пути — это только `plans/features/p0-embed-503-failover/**`,
  `plans/owner_inputs/2026-11-22-…` и новый тест; ни `web/`, ни `db/`, ни запрещённых путей
  кандидат не добавляет.
- **JS/синтаксис:** 4/4 JS-пина rc=0 (`HOTFIX7/8/9/10-…-OK`); `node --check web/app.js` rc=0;
  `py_compile` settings/обоих services/нового теста/обоих e2e-tools rc=0.
- **E2E (байты кандидата, temp-копия):** B1 `ui_mod_acl_m4b_status_e2e.py` — **138/0 OK**;
  B2 `ui_mod_acl_m4b2_status_e2e.py` — **92/0 OK**; B3 `ui_mod_acl_m4b3_status_e2e.py` — 131
  проверка, 1 падение `detail_closed`, воспроизведено и на base (см. REL230-N02).
- **Manifest (dry-run на tip):** `deployed_sha=50e01523e…`, `version=2.58.230`,
  `effect=deploy`, `dirty_tracked=false`; `previous_sha=null` без seed (в evidence —
  `9d5cf5173`/`94e227a2c`, см. REL230-N01).
- **Runbook:** честный — apinet не объявляется починенным, Google admission «unproven», один минимальный
  deployed-вызов, без mass/reindex, T0/T1 text-only, rollback `94e227a2c`, disk audit+cleanup, identity
  по строковому равенству HEAD и манифеста. После c5 в §5 нужно доказать именно запись вектора, а не
  только HTTP 200.
- **Состав/DDL:** только 3 файла продукта, schema 48 / DDL 0, новых флагов/эндпоинтов/промптов/UI нет.

## 4. Nonblocking (не вето, но зафиксировано)

| ID | Класс | Суть |
|---|---|---|
| REL230-N01 | evidence accuracy | `manifest-dry-run.json` снят на content-tip `9d5cf5173`, а ветка сверху имеет docs-only `50e01523e`. Деплой обязан сгенерировать манифест на хосте и записать фактический HEAD; нельзя выдавать `9d5cf5173` за deployed SHA, если выкатывается tip. |
| REL230-N02 | environment / evidence | B3 у меня 130/131 с `detail_closed` (два прогона на кандидате и один на базе). `web/`-байты кандидата байт-идентичны базе, поэтому это не регрессия кандидата; заявленные «131/131 OK» в моём окружении не воспроизводятся. |
| REL230-N03 | evidence accuracy | Утверждение «те же 4 pin-падения на базе» частично невоспроизводимо: в архиве без `.git` diff-тесты не выполняются, а на master один из двух diff-ID проходит. Нарушения кандидатом нет (см. §3). |
| REL230-N04 | backlog re-scope | `E503-R1-N01` (read/query path использует configured identity) остаётся backlog-only; `E503-R1-N02` («дополнительному alias нужен durable admission») после уточнения владельца должен быть переформулирован: допуск — по MSI + canary, а не по PCI. Не удалять и не превращать в отдельный блокер. |

## 5. Покрытые требования (пересмотр под уточнение владельца)

| ID | Статус после delta-review |
|---|---|
| `E503-FAILOVER-01` | PASS_CODE (маршрутизация 5xx/timeout на независимые ноги доказана RED/GREEN и мутациями) |
| `E503-AUTH-01` | PASS (401/403 не выводят независимые слоты; 429 уважает group cooldown) |
| `E503-IDENTITY-01` | **FAIL_CODE — REL230-F1** (admission PCI-bound; same-MSI fallback отбрасывается) |
| `E503-RECOVERY-01` | **FAIL — REL230-F1** (fallback-вектор не пишется, новые факты остаются text-only) |
| `E503-DIAG-01` | PASS_CODE (alias/provider/model, без секретов; R17 соблюдён) |
| `E503-ACCEPT-MATRIX-01` | **FAIL/PENDING — REL230-F1** (критерий «вектор + semantic» не выполнен; live-часть не заявляется) |
| `E503-EXCLUSIONS-01` | PASS (модель/индексы/DDL/промпты/UI/флаги не менялись; без переиндексации) |
| `E503-ROUTE-01` | EXTERNAL_EVIDENCE `f2540ac60` не перепроверялся (apinet 503 — внешний факт, не «починен») |
| `E503-REPORT-01` | PENDING_FINAL_REPORT (assembly/review честно не заявляют VERIFIED; после c5 обновить) |

## 6. Что должен доказать c5 (targeted re-review, без повторного полного аудита)

1. **same MSI + different PCI admitted:** при равных model/dims/preprocessing/generation и другом `conn`
   fallback получает запись в действующий индекс; в `graph_facts_vec` появляется строка, и **реальный
   vector/KNN search** находит этот факт (не только FTS).
2. **different MSI blocked:** при другой модели/размерности/preprocessing запись по-прежнему запрещена
   (text-only) с конкретным `reason_code`, без «доказанной несовместимости» из отсутствия PCI-записи.
3. **canary на старых векторах:** одна ограниченная проба существующим механизмом (`compat_probe`/
   `_compat_probe_once`) против сохранённых строк индекса, затем durable admission; не Google-vs-Google,
   не новый identity-контур, не переиндексация, не смена модели.
4. **Backfill:** накопленные text-only факты восстанавливаются идемпотентно; повторный backfill не дублирует.
5. **Primary recovery:** после исчезновения 503 маршрутизация возвращается на primary без потери данных,
   без mixed-space и без загрязнения cache под configured identity.
6. **Регрессии:** 10/10 нового набора (обновлённого под новый контракт), 15-файловый профиль 585+, B1/B2;
   мутации «same-MSI → блок» и «different-MSI → разрешено» должны быть убиты.

## 7. Ограничения этого ревью

- Не выполнялись: деплой, SSH, прод, live-провайдеры, изменения ключей/настроек/БД,
  `progress_scope.json`, `workflow_state.md`. Только локальные прогоны на байтах кандидата и
  чтение исходников.
- SEMANTIC-hit на кандидате доказать нельзя по построению: вектор не пишется; доказано отсутствие и причина.
- B3-падение `detail_closed` не атрибутировано кандидату (web не менялся) и воспроизводится на base.
- 2 pin-ID зависят от устаревших git-ref; полное воспроизведение «на базе» ограничено отсутствием `.git`
  в архивной копии.
- Никакой VERIFIED / «apinet починен» / «память восстановлена» не заявляется.

## 8. ADDENDUM — c5 re-review (2026-11-22, MSI admission)

**Заменяет вердикт §0 для c5-кода.** §0–§7 остаются историческим ревью кандидата без c5 и
служат доказательством исходного дефекта.

- Reviewed c5: code `1b7d4bf0471a10aaff5d4f0c40eacd77f707727d`, branch head
  `5fa47ec00eeb8f892abee13310f2ae48ea046bef` (parent `d00a01b07`); `1b7d4bf..5fa47ec` — evidence only.
- Delta `d00a01b07..1b7d4bf`: 6 файлов — `services/embedding_control_plane.py` (+154/−…),
  `services/summary_memory.py` (только docstring), `tests/test_p0_embed_admission_msi.py` (new, 10),
  `tests/test_p0_embed_503_failover.py`, `tests/test_embed_identity_compat.py`,
  `tests/test_embed_identity_compat_restart_legacy.py`. `config/web/migrations/handlers/prompts` — пусто;
  `APP_VERSION`, модель, индексы, DDL, UI, настройки не тронуты. `summary_memory` после удаления docstring
  AST-идентичен базе (`True`).

```json
{
  "artifact": "P0-EMBED-503-FAILOVER delta-review r1 — addendum c5",
  "reviewed_c5_code": "1b7d4bf0471a10aaff5d4f0c40eacd77f707727d",
  "reviewed_branch_head": "5fa47ec00eeb8f892abee13310f2ae48ea046bef",
  "c5_parent": "d00a01b07eec2143f355dcba6067f92074e3d064",
  "release_candidate_tip": "50e01523e2f82f58a5eb7fa48923e63e59627f89",
  "release_candidate_has_c5": false,
  "verdict": "APPROVED_FOR_DEPLOY",
  "approval_scope": "c5 code seam (MSI admission) — cherry-pick into 2.58.230",
  "release_candidate_approved_as_is": false,
  "rel230_f1": "CLOSED (c5 code); release branch must receive c5 and be re-run before deploy",
  "blocking_findings": [],
  "nonblocking": ["REL230-N01", "REL230-N02", "REL230-N03", "REL230-N04", "REL230-N05"],
  "patch_applies_to_release_tip": true,
  "verified": false
}
```

### 8.1 Что именно изменилось (проверено по коду)

1. `admission_valid` (`embedding_control_plane.py:2916-2940`): ключ допуска — `space` (MSI) +
   `checked >= COMPAT_PROBE_MIN_SAMPLE`; сравнение `admission["conn"] != conn_now` **удалено**.
   `conn_now` остался в сигнатуре как провенанс/диагностика. Исторический PCI-keyed admission
   переиспользуется при совпадении MSI.
2. `format_admission`: формат не менялся, `conn` по-прежнему пишется как провенанс (`:2878-2896`).
3. `classify_identity_compatibility` (`:2477-2521`): dimension mismatch → `COMPAT_DIMENSION`;
   `CANARY_DRIFT` → `COMPAT_REINDEX`; admission → `COMPAT_ADMITTED` только при совпадении
   `admission.space`; равные MSI → `COMPAT_INSTANT` без требования canary; разные MSI → `COMPAT_REINDEX`.
   Ветка без переданных MSI (`plan_identity_change`, `:4259`) не изменилась.
4. `resolve_index_compat` (`:3604-3680`): при наличии ACTIVE и равном MSI →
   `state=compatible`, `serviceable=true`, `class=ADMITTED_COMPATIBLE` (если admission по MSI валиден)
   или `INSTANT_COMPATIBLE` (если нет), `action=none`, без probe/migration. Реальный mismatch MSI →
   `incompatible` + controlled_migration.
5. No-MSI путь (ACTIVE-строка без выводимого MSI): `needs_probe=true`, `reason_code=msi_unavailable`;
   `ensure_index_compat` (`:3919-4075`) делает **одну** `compat_probe` на **старых** строках индекса
   (cooldown + lock), при успехе пишет durable `format_admission(space, conn, …)` и adopt, при провале —
   без admission, `serviceable=false` → text-only. Google-vs-Google не используется.
6. Write/backfill гейты (`summary_memory.py:3180-3252, 5671-5679, ~3769/3855, ~7880`) логически не менялись:
   они уже пропускают всё, что `resolve_index_compat` признал `serviceable + compatible`, и блокируют
   остальное. `_vec_write_allowed` по-прежнему отдельно блокирует canary DRIFT для configured identity.

### 8.2 Мои независимые прогоны (c5)

| Проверка | Результат |
|---|---|
| New `tests/test_p0_embed_admission_msi.py` | **10 passed** |
| 19-файловый профиль из evidence (`--deselect test_not_serviceable_warning_coalesced`) | **657 passed / 0 failed, 1 deselected**, 87.9 s — воспроизведено |
| RED на базе `d00a01b07` (новый файл) | **6 failed / 4 passed**: падают same-MSI/write/KNN/backfill/no-MSI; проходят guard-тесты (live MSI, different MSI, dim mismatch, canary drift) |
| Deselected test | падает и на tip, и на базе `d00a01b07` (superseded + source empty coalescing) — deselection честный |
| Мутация M1: вернуть `conn` в `admission_valid` | **2 failed** (PCI-bound снова блокирует same-MSI) |
| Мутация M2: `_serving_route_write_allowed` → `False` | **3 failed** (запись/backfill/KNN) |
| Мутация M3: игнорировать `space` в admission | **1 failed** (wrong-space admission принят) |
| `git apply --check` c5-патча на release tip | **rc=0**; байты всех 6 затронутых файлов на `50e01523e` равны `d00a01b07` |
| Release branch | `50e01523e`; c5 **не** предок — текущий release-кандидат всё ещё PCI-bound |

**Мой независимый пробник (только продуктовые API, real sqlite-vec KNN, детерминированные векторы):**

```
[probe] MSI(model,dims)        : e540d4ad890e121d
[probe] MSI == live e540       : True
# same MSI, different PCI (apinet -> google fallback)
[probe] calls                  : ['k-primary', 'k-fb1']
[probe] bases                  : ['https://apinet.test/v1', 'https://generativelanguage.test/v1beta/openai']
[probe] graph_facts            : 1
[probe] graph_facts_vec        : 1
[probe] knn ids for new fact   : [1]
[probe] serving meta           : {'alias': 'fallback_1', 'provider': 'generativelanguage.test', ...}
[probe2] same-MSI/diff-PCI compat: {"state": "compatible", "reason_code": "", "class": "ADMITTED_COMPATIBLE",
                                    "serviceable": true, "needs_probe": false, "action": "none"}
[probe2] admission             : {"space": "e540d4ad890e121d", "conn": "ffffffffffffffff", "checked": 12, ...}
# different MSI
[probe] other-MSI compat       : {"state": "incompatible", "reason_code": "identity_changed",
                                  "class": "REINDEX_REQUIRED", "serviceable": false}
[probe] other-MSI write_allowed: False
[probe] other-MSI vec rows     : 0
```

То есть REL230-F1 закрыт по существу: same MSI + another PCI → реальная векторная строка и
semantic KNN hit; different MSI/dims/preprocessing → text-only; historical PCI admission
переиспользуется по MSI; ложного `COMPATIBILITY_UNKNOWN` из-за смены шлюза больше нет.

### 8.3 Nonblocking (дополнение)

| ID | Класс | Суть |
|---|---|---|
| `REL230-N05` | hardening / backlog | Canary DRIFT по-прежнему покрывает только **configured** identity (`_schedule_canary_probe` → `self._identity_fingerprint()`). Для fallback-подключения отдельной canary нет: единственное доказательство — равенство MSI. Владелец явно требует не превращать PCI в гейт, поэтому это не блокер (live-проба дала cosine 1.0 и тот же MSI), но в backlog стоит зафиксировать: при желании — периодическая canary на каждый фактически обслуживающий alias; сейчас не требуется и не мешает деплою. |

`REL230-N01..N04` из §4 остаются в силе, причём N01 обязателен к пересчёту: после cherry-pick c5 меняется
content tip, значит `manifest-dry-run.json`/`assembly.md`/`tests-2.58.230.json` в release-ветке
описывают уже другие байты.

### 8.4 Условия деплоя (что должно произойти до выката)

Деплой разрешён **не для текущего** `50e01523e`, а для release-ветки после c5:

1. Cherry-pick `1b7d4bf` (code + tests) в `release/p0-embed-503-failover-2.58.230`; патч применяется чисто
   (`git apply --check` rc=0, байты 6 файлов совпадают).
2. Пересобрать evidence 2.58.230 под новые байты: `assembly.md` (новый content tip, 6 файлов, +657/0),
   `tests-2.58.230.json/.txt`, `manifest-dry-run.json` (новый `deployed_sha`, previous остаётся
   `94e227a2c`/2.58.229), `deploy-runbook-2.58.230.md` (identity/шаги не меняются, но SHA другой).
   `APP_VERSION` остаётся 2.58.230 — bump не нужен.
3. Повторить на release-tip: новый набор 10/10, профиль 657/0 (с тем же deselected), RED не требуется повторно;
   зафиксировать фактический SHA.
4. Деплой по runbook; в §5 post-deploy обязательно записать фактический `last_served_credential()`
   alias/provider/host и **один semantic KNN-запрос**, подтверждающий, что новый факт находится вектором
   (не только FTS), плюс T0/T1 text-only; apinet по-прежнему не объявлять починенным.
5. После выката — VERIFIED только по реальному deployed SHA и этим наблюдениям; сейчас VERIFIED не заявляется.

Ограничения addendum: деплой/SSH/прод/live-провайдеры не выполнялись; semantic hit доказан на локальном
sqlite-vec с детерминированными векторами (функциональный путь), а не на production-данных; B3/`detail_closed`
и pin-evidence замечания из §3–§4 не перепроверялись повторно (вне этого seam).
