# REV-REL-258113 — независимое релизное ревью поезда 2.58.113

**Лейн:** `REV-REL-258113` (read-only; изменён только этот файл).
**Дата ревью:** 23.10.2026. **Кандидат:** `e4ee54f3` (bump 2.58.113), база `678c0616` (2.58.112), прод-база `fbf9013d` (2.58.111).
**Код-идентичность с текущим `origin/master`:** `git diff e4ee54f3 2a0f5d65 -- . ':(exclude)plans'` — пусто; все коммиты поверх поезда (`a02fe626`, `2a0f5d65`) меняют только `plans/`. Вердикт привязан к коду `e4ee54f3`; в деплой можно брать tip — код тот же, плюс review/evidence-артефакты.

## ВЕРДИКТ: `Needs Fixes`

**Блокеров кода нет.** Поезд технически пригоден к контролируемому деплою. Единственный блокер — процедурный: карта asap2 не перепривязана к поезду, из-за чего оба запрошенных слайса дают формальный `candidate mismatch`. После перепривязки — **Approved for controlled deployment, parent not DONE**.

## 1. Состав и покрытие ревью

17 коммитов `678c0616..e4ee54f3` = 15 черри-пиков + `e0f3bfbb` (chore frozen-assets) + bump. Все 15 черри-пиков **совпадают по диффу** с исходными отревьюженными коммитами (`git patch-id --stable`, 15/15 совпали): `0358b593=5e7d986e`, `141333ed=dd4e0522`, `4962ad48=30a2f868`, `67c1b509=570e1eee`, `d62e9720=69da031c`, `ddf139a1=cf7e00e3`, остальные — docs.

| Функция | Ревью-артефакт | Вердикт |
|---|---|---|
| W4 UI §8 + rework | `asap-speech-arch/evidence/w4/review.md` (Needs Fixes на `5e7d986e`) → `review-r2.md` | **Approved** (контролируемый деплой) |
| EMBED-IDENTITY-COMPAT | `embed-identity-compat/review.md` (Needs Fixes) → `review-r2.md` → `review-gaps-meta.md` | Needs Fixes → **PASS дельты**, B1/B3 и gaps закрыты |
| EMBED-REBUILD | `_audit-2026-10-23/embed-rebuild/review.md` → `review-r2.md` | **Approved for controlled deployment** |
| EMBED-FALLBACK | `_audit-2026-10-23/embed-fallback-fix/review.md` | **Approved** |
| B11 | `_audit-2026-10-23/b11-diag-fix/review.md` (на `3334141a`) | **PASS**; `924b3b51` — закрытие N1, отдельного артефакта нет, проверено мной (24 теста, scope `tools/`) |
| Summary L2-ревизия | `_audit-2026-10-23/summary-revision-fix/review.md` | Needs Fixes только из-за 4 pre-existing red; фикс `425ea79d` в поезде, `test_summary_generator.py` — **65 passed** |
| Summary factview / B-1 | `summary-factview-fix/review-factview.md`, `review-b1-recheck.md` | **Approved** |
| asap2 Direct Chat | `asap2-direct-chat/review-r2.md` | «код можно в поезд» при 3 условиях (см. F1) |

Неотревьюженного кода в поезде не осталось. `924b3b51` — единственный коммит без отдельного ревью-файла, но это реализация уже найденной находки N1 (fail-closed диагностика job-статусов), проверенная здесь независимо.

## 2. Bump / каноны / DDL

- `APP_VERSION=2.58.113` (settings, README, F8-meta). Bump: **31 файл / 33 пары**, `non-token deltas: NONE`; диффы тестов — только строки версии (ослабленных ассертов нет).
- F8-meta HEAD = `e0f3bfbb` = фактический pre-bump HEAD. `FACTORY_SET_SHA256_12 == factory_set_fingerprint() == 24ae494ac422` (проверено импортом на кандидате).
- **ΔDDL = 0** в прод-периметре для всей деплой-дельты `fbf9013d..e4ee54f3`: 2 совпадения `CREATE TABLE` — только в evidence-скрипте `plans/features/embed-identity-compat/evidence/a0-probe/raw/runner.py` (одноразовая проба, не прод). `user_version` не менялся.
- Прод-дельта фактически больше поезда: `fbf9013d..e4ee54f3` = 40 коммитов / 398 файлов, т.к. 2.58.112 в прод не выкатывался; весь этот объём покрыт ревью выше.

## 3. Guards — воспроизведено на кандидате

| Проверка | Отчёт | Мой прогон |
|---|---|---|
| F8 `--check` | 582 == REGISTRY | **EXIT 0**, 582 == REGISTRY |
| Frozen UI assets | FROZEN-ASSETS-OK | **FROZEN-ASSETS-OK** |
| Embed target (7 файлов) | 115 passed | **115 passed** |
| B11 target | 24 passed | **24 passed** |
| JS/UI (js_unit + w6 + tokens + nav) | 39/171 | **124 passed** (4 файла), EXIT 0 |
| Summary generator (блокер ревью) | — | **65 passed** |

Логи остальных наборов совпадают с README по числам и без падений: offline 14/14, bump-verify 31/33, pins24 868/0, F8-пины 29, help-sync 24, JS-unit 39, node 5/5 + syntax 107/0, py_compile 47/0, frozen 66, write-points 1, asap2 155, summary 179, всего 1581. Противоречий с отчётом нет. Полный suite в лейне не запускался (запрещено брифом) — принимаю как ограничение.

## 4. Гейты `requirements_gate.py --stage review --candidate e4ee54f3` (worktree на tip)

| Слайс | EXIT |
|---|---|
| embed `IDENT-SPLIT`, `CANARY`, `DECISION`, `ACCEPT` | **0, 0, 0, 0** |
| speech `UI-U01…U07`, `UI-P2`, `UI-U09` | **0** (все 9) |
| asap2 `CLAR-BOOL` | **1** — только `candidate mismatch` + evidence не привязан к `e4ee54f3` |
| asap2 `CLAR-SPEECH` | **1** — то же |

Проверено, что причина ровно одна и она механическая: на копии карты с `candidate_commit=e4ee54f3` и перепривязкой 163 evidence-записей оба слайса дают **EXIT 0** (`scoped=6 errors=0` / `scoped=3 errors=0`).

## 5. Блокер

### F1 — `BLOCKER` (реестр/процедура): карта asap2 не привязана к поезду
`plans/features/asap2-direct-chat/requirements-map.json` → `"candidate_commit": "34af90ff"`, во всех 163 evidence-записях `"candidate_commit": "34af90ff"`.
Репро: `check --stage review --slice CLAR-BOOL --candidate e4ee54f3` → `EXIT 1`, `FAIL: candidate mismatch`.
Код при этом идентичен отревьюженному: `git diff 34af90ff e4ee54f3 -- services/direct_l1.py services/direct_chat_service.py services/claim_envelope.py services/chat_prompts.py services/prompt_migrations.py services/prompt_registry.py tests/test_asap2_clar_contract.py` — **пусто**.
**Минимальная коррекция (PM, по уже описанной процедуре `binding-2026-10-23.md` §7):** `candidate_commit=e4ee54f3`, механическая перепривязка evidence (наблюдения не переписывать), затем повторный gate. **Проверка:** оба слайса EXIT 0.
Отдельно: в карте asap2 остаются **34 required PENDING** (T10/T11/T14/T17/T18/T20/T22/T24/T26, `MIGR-*`, `DONE-D1/D4/D5/D6/D8/REPORT`, `CLAR-L1-DIST2..5` и др.) — это агентские/postdeploy-проверки, они не блокируют деплой, но **`DONE` и release-stage по asap2 до их закрытия невозможны**. `DONE-D9` — `READY_FOR_LIVE` (допустимо).

## 6. Откат — проверено, данные не теряются

- **После успешного adopt** (штатный сценарий): строка `graph_facts_vec` = `active`, fingerprint/provenance старого шлюза сохранены. Откат кода на 2.58.111 безопасен и **тихий**: `database.ensure_embedding_generation` (`fbf9013d:services/database.py, early-return при существующем ACTIVE`) при наличии ACTIVE-строки возвращает её и **новую не создаёт**, поэтому `maybe_schedule_rebuilds` (`graphrag_rebuild.py:1617-1651`) не видит `building`-кандидата → полная перевекторизация не запускается. Итог откатa: FTS-only (ровно сегодняшнее состояние прода), векторы и факты целы, схема не менялась (ΔDDL=0).
- **Если откат делается до adopt** (проба не прошла, ACTIVE-строки нет): старый код зарегистрирует `building` с текущим fingerprint и запустит полную сборку — это до-существующее поведение 2.58.111, не регрессия поезда. При недоступном embed-API это серия неудачных попыток; если сборка не нужна — отменить job (`task_jobs`, kind `graphrag_rebuild`).
- Рекомендуется добавить в `rollback.md` одну строку про этот второй сценарий; блокером не является.

## 7. Остаточные риски (не блокируют)

1. **Fallback/BYOK с другой моделью.** `LLMClient.last_embed_meta` — общий mutable-атрибут; при обслуживании пробы слотом с иной моделью возможен ложный `model_mismatch` → `incompatible` → лишняя target-сборка. Ложного `compatible` нет (числовой гейт + hit5). Зафиксировано `review-gaps-meta.md` §5; на apinet тело ответа — ровно `gemini-embedding-001` (A0 `embed_calls.json`).
2. **Старт с недоступным embed-API.** `initialize()` ждёт inline-пробу (`summary_memory.py:1758`), ретраи `_embed` ограничены (`_ATTEMPT_BUDGET=4`), затем `insufficient` и обратимая пауза. Возможна задержка старта, не потеря данных.
3. **Визуальные доказательства W4** сняты на стенде (Chromium) с payload-фикстуры; текст строк карты в `1280`-кадре («слайс W4») приходит из старой W6-фикстуры, в текущем коде такой строки нет. Реальный Telegram WebView/Android — по стоячему правилу проекта необязательное наблюдение владельца.
4. **Мелочи evidence:** README называет 3446 добавленных py-строк, offline-агрегат — 3968, `ddl-check` — 6750 (разные базы/pathspec; вывод ΔDDL=0 одинаков). В `resolver-pre/report.md` §10 перечислены 4 `.log`, которых нет в коммите (`fetch.log`, `run.log`, `verify_config.log`, `verify_model.log`); ключевые JSON-артефакты на месте.

## 8. Что проверено по рискам поезда

- **Рестарт + inline-проба + adopt:** порядок `резолвер → проба старых векторов → adopt/cancel` до backfill; на реальных строках прод-копии — `insufficient(compat_not_proven)` → 1 батч (12 текстов) → `compatible`, `mean=min=hit5=1.0`, новых поколений нет (`resolver-pre/report.md`). Adopt идемпотентен, провенанс не перезаписывается.
- **Per-slot fallback:** `EmbeddingCredential(base_url, model)` на слот; primary/fallback разведены; регресс control plane — 69 passed (ревью дельты).
- **Summary-ревизия:** batch по `allowed_paragraph_ids` + один §99/anchor-валидатор; 1 абзац — прежний путь; durable `review_verdict/blocking/codes/revision_fixed`.
- **W4 UI vs B11:** пересечения нет — W4 меняет `web/**`+`tools/ui_w4_ui_e2e.py`, B11 — `tools/v63_b11_mechanisms_report.py`; `analytics_viz` читает `mca_events.outcome`, не `diagnosis.code`. `services/llm_client.py` (meta-wire) — аддитивный побочный канал, контракт `embed()` не изменён (115 passed).

## 9. Обязательные postdeploy-проверки

1. `/healthz` 200, версия `2.58.113`, `NRestarts`, отсутствие ошибок импорта.
2. `GET /api/memory/embeddings`: `compat.serviceable=true`, `canary.checked>=8`, `mean>=0.995`, `min>=0.990`, `hit5>=0.80`, `generation.state=active`, `reindex_required=false`; в логе `EMBEDDING_COMPAT_ADMITTED`; в реестре по-прежнему **2 строки**, без новых `building`/`building_target`.
3. Backfill: 4 224 eligible без векторов дренируются; `graph_facts_vec` не уменьшается.
4. Реальный поиск по старым фактам отдаёт непустую выдачу (не FTS-only).
5. B11: `tools/v63_b11_mechanisms_report.py --db <prod>` — нет ложного `ok` на FAILED/DEGRADED, job-статусы честные (`paused_rate_limit`/`cancelled`/`finished`), `backlog` не `null`; закрыть `REQ-B11-E2E` (READY_FOR_LIVE).
6. Следующий тик Summary: `coverage>0` с anchor-map (не `FACT_VIEW_EMPTY`), multi-paragraph `revision_fixed_count` в событии, published-cancel сохраняет `ok`.
7. Снимок до/после PG Factory/active/effective (asap2 `MIGR-*`, `DONE-D4`) и deploy/rollback/health.
8. Откат: зафиксировать деплой-SHA, подтвердить доступность `fbf9013d`, снять копию БД до рестарта.

## 10. Можно ли деплоить

**Сейчас — нет, только из-за F1 (перепривязка карты asap2).** Код `e4ee54f3` блокеров не имеет: bump/каноны/DDL/guards сходятся, все функции поезда отревьюжены, embed и W4-слайсы проходят review-гейт. После перепривязки карты — **можно деплоить `e4ee54f3` (или code-identical tip) штатным релизом с обязательным рестартом**; parent `DONE` не ставится до postdeploy-проверок §9 и закрытия оставшихся PENDING.
