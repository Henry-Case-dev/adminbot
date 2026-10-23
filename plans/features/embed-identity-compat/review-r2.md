# EMBED-IDENTITY-COMPAT — независимое ревью R2 (B1/B3)

**Лейн:** `REV-EMBED-IDENTITY-R2`. **Кандидат:** `570e1eee55dff89450deef27696425a0b87a471b` (+ evidence `0a456aa9`); HEAD `0a456aa9` проверен: `git diff 570e1eee..0a456aa9 -- services tests web` пуст (код байт-идентичен). **Родитель по brief:** `30a2f868`; между ними в истории влит посторонний W4-коммит `dd4e0522` (web/app.js, web/index.html, tools/ui_w4_ui_e2e.py) — он вне объёма этого ревью и не одобряется им.
**Карта:** sha256 `c82163466c9ce46d27bfece6d34beb3766b26d7013ec0324380fed877b66d2e4`, `candidate_commit=570e1eee`, `source_sha256=429a986838d5f7…` совпадает с `source-2026-10-23.md`. Binding: `binding-2026-10-23.md`.
**Время проверки:** 2026-10-23 14:55–14:58 (+12). **Режим:** read-only; изменён только этот файл.

## ВЕРДИКТ: `Needs Fixes` — B1 и кодовая часть B3 закрыты; релиз ещё блокируют 3 PENDING-требования карты и pre-deploy resolve-проба на реальной прод-БД.

Отдельно: **B1 — VERIFIED**, **B3 (семантика legacy в коде) — VERIFIED**, **B3 (доказательство на реальных прод-строках) — UNVERIFIED/NEEDS_AGENT_CHECK** (это и есть оставшийся пункт прошлого ревью).

## 1. B1 — ЗАКРЫТО (durable compat-пауза)

**Механика.** Причина паузы теперь durable и отличается от операторской: `COMPAT_PAUSE_REASON = "paused_compat_insufficient"` (`services/graphrag_rebuild.py:110`), `pause_rebuild(..., reason_code=...)` (`:2279-2291`), поиск/снятие только по `status='paused' AND reason_code=...` (`:2294-2357`), панель различает состояние `compat_insufficient` (`:1949-1954`, `:1908-1911`), планировщик снимает compat-паузу перед миграцией (`:2033-2038`); в control plane: pause/resume/cancel по durable-причине (`services/embedding_control_plane.py:3483,3500,3517`), incompatible → resume (`:3573`), adopt → cancel (`:3685-3690`). Операторская `paused` имеет другой `reason_code` и не матчится.

**Независимый repro** (`OPENCODE_WORKFLOW_SCRATCH/rev-embed-r2/probe_r2.py`, реальная SQLite+sqlite-vec, мок только HTTP-embed; свои фикстуры, не импорт тестового файла):

| Сценарий | Наблюдение |
|---|---|
| (а) running → insufficient(`api_unavailable`) → pause → `reset_compat_state()` (рестарт) → incompatible(`low_hit5`) | job `paused → queued/compat_resume`; `maybe_schedule_rebuilds()==['graph_facts_vec']`; live 20/20; ACTIVE нет |
| (б) insufficient → рестарт → снова insufficient | job остаётся `paused/paused_compat_insufficient`; scheduler `[]`; панель `compat_insufficient`, `reindex_required=false`, reason `paused_compat_insufficient`; live 20/20 |
| (в) операторский `paused` → рестарт → incompatible | job остаётся `paused/paused` (не тронут) |

Совпадает с 9 новыми тестами (`tests/test_embed_identity_compat_restart_legacy.py`), они зелёные (см. §6). B1 закрыт.

## 2. B3 — код закрыт; pre-deploy проверка на проде остаётся

**Правило.** MSI строки выводится из сохранённого fingerprint, только если он воспроизводится с текущей версией предобработки; иначе — `insufficient(legacy_metadata_missing)`, без rebuild/adopt; доказуемо другая модель/размерность — прежняя миграция (`services/embedding_control_plane.py:2522-2610`; ветки резолвера `:3255-3273`, `:3331-3346`).

**Проверка на прод-типе (dims=3072, реальный fp `96f808…`, endpoint `e42d6fd4c65855c2`)** — `OPENCODE_WORKFLOW_SCRATCH/rev-embed-r2/probe_prod_3072.py`:

* `preprocessing_version=NULL`, endpoint сохранён → provenance `fingerprint`, MSI `e540d4ad890e121d` **равен текущему space**, вердикт `insufficient/compat_not_proven`, `needs_probe=true`, candidate = `96f808…` → проба → adopt; target-поколение не регистрируется;
* `preprocessing_version='casefold-strip-v1'` → то же (provenance `registry`);
* `endpoint_fingerprint=NULL` при NULL-preproc → `insufficient/legacy_metadata_missing`, rebuild/adopt нет.

**Формула проверена напрямую:** `sha256("generativelanguage.googleapis.com\x1fgemini-embedding-001\x1f3072\x1fcasefold-strip-v1\x1fe42d6fd4c65855c2") = 96f80838f683e1cb…4337d` — ровно прод-fingerprint. То есть legacy-строка действительно построена с `casefold-strip-v1`, и вывод MSI из fingerprint корректен, а не «подгонка».

**Ложного compatible нет:** при NULL-preproc и доказанно другой модели резолвер даёт `incompatible/identity_changed` + target (миграция), а не adopt (`probe_r2.py`, case E); при невоспроизводимом fingerprint — `insufficient/legacy_metadata_missing`, ни rebuild, ни adopt (case F). Это согласуется с `_row_space_differs_provably` (только model/dims, `ecp:2596-2609`).

**Что осталось (B3-хвост):** A0 измерял только `compat_probe` и **не** фиксировал `resolve_index_compat`/колонки реальной строки. На синтетической прод-копии ветка доказана, но по правилу прошлого ревью нужен один pre-deploy read-only прогон на копии прод-БД: `resolve_index_compat(...).state/reason_code/action/candidate` + `model/dims/preprocessing_version/endpoint_fingerprint/status`. Ожидаемо `insufficient(compat_not_proven)` (или `compatible`), **не** `incompatible` по space-mismatch. Это `NEEDS_AGENT_CHECK`, не Human Gate. Факт: в архиве `plans/archive/asap-4-…/prod-facts.md:107` у строк 29.09 указан `preprocessing_version=casefold-strip-v1`, т.е. риск NULL-preproc на проде низкий, но колонки в A0 не сняты — проверка остаётся.

## 3. Согласованность с A0 и что будет на проде

A0: `compatible`, checked=12, mean/min/hit5=1.0, расширенно 42/42 косинусов и top-1 KNN 42/42 (`evidence/a0-probe/report.md`). Проба и пороги не менялись в `570e1eee` (дифф `COMPAT_PROBE*`/thresholds пуст).

Для двух `building`-строк от 29.09 (`graph_facts_vec`, `smart_archive`; ACTIVE нет) при текущем `gemini-embedding-001/3072`:

| Состояние строки | Вердикт резолвера | Действие |
|---|---|---|
| preproc сохранён (архивный факт) | `insufficient(compat_not_proven)` | проба на 16 003 старых векторах → по A0 `compatible` → adopt, rebuild нет |
| preproc NULL, fingerprint воспроизводится | `insufficient(compat_not_proven)` | то же; проверено на реальных значениях fp/endpoint |
| preproc NULL, endpoint/поля отсутствуют | `insufficient(legacy_metadata_missing)` | rebuild/adopt нет, FTS-only, нужен разбор провенанса |
| model/dims доказуемо другие | `incompatible` | штатная миграция (на проде model/dims те же) |

Ключевое: **legacy-строка прод-типа не даёт `incompatible`/rebuild**; ожидаемый путь — проба → adopt. Но перед рестартом всё равно обязательны условия A0 §7.1 (сверить прод-конфиг URL/модель/хэш ключа с измеренным).

## 4. Инварианты не ослаблены

* Пороги canary, KNN-hit5, полоса повтора и анти-теорема «новое-с-новым» не менялись: в диффе нет изменений `COMPAT_PROBE*`/порогов/`adoption_enabled` (единственное упоминание `COMPAT_ADMITTED` — прежняя строка `__all__`); `test_antitheorem…` в контрактном файле зелёный.
* Kill-switch `EMBED_CONTROL_PLANE_*`/`GRAPHRAG_SHADOW_REBUILD_ENABLED` не тронуты.
* **ΔDDL=0**: `services/database.py` в диффе отсутствует; новых таблиц/сервисов/реестров нет; compat-маркер живёт в существующей `task_jobs.reason_code`. `services/summary_memory.py` и `web/api/memory_agi.py` тоже не менялись.
* `5877810d` не сломан: `tests/test_graphrag_identity_reindex.py`, `test_asap6_embedding_generations.py`, `test_asap5_embedding_identity.py` не менялись и зелёные; `resume_rebuild` сохраняет `status not in ({ST_PAUSED} | set(AUTO_RESUME_STATUSES))` (`graphrag_rebuild.py:2369-2376`).

## 5. Риск: `resume_compat_paused` без `fp`

`resume_compat_paused(db, index)` (`graphrag_rebuild.py:2341-2348`, вызов `:2038`) может вернуть в `queued` до 4 последних compat-пауз индекса, включая джобу под устаревший fp. Проверил, что стартовать она не может: `run_job` вызывается **только** из `maybe_schedule_rebuilds` для `_ensure_job(current_fp)` (`:2069-2090`), а watchdog берёт только `running` (`services/mca_watchdog.py:59-69`, `TaskJobStore.recover_stale` `services/task_supervisor.py:547-569`). Устаревшая `queued`-джоба остаётся мёртвой строкой (не стартует, не влияет на сборку); это некритичный мусор. Точнее было бы передать `fp=current_fp` в вызове `:2038` — необязательное улучшение, не блокер.

## 6. Прогоны (кандидат `570e1eee`, локальный `.venv`)

| Набор | Результат |
|---|---|
| `tests/test_embed_identity_compat_restart_legacy.py` (новые B1/B3) | **9 passed** (4.84 s) |
| контракт + новые (29 заявленных) | **29 passed** (9.09 s) |
| смежный набор (contract/asap5 identity/asap6 generations/graphrag identity/webapp memory API/tx-supervisor/new) | **116 passed** (27.75 s) |
| `test_embedding_control_plane_asap4` + `test_mca07_retrieval_context` | **112 passed** (16.46 s) |
| graphrag rebuild/recovery/memory/summary/asap44 batch/asap8 f8 | **315 passed** (22.17 s) |
| 7 pre-existing `37==35`: `test_t5150_startup_migrations_round1046` (5) + `test_asap7_direct_settings` (2), standalone | **7 failed, 20 passed** — воспроизводятся без кандидата, ΔDDL=0 → pre-existing |
| 8-й «сетевой» `test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener` standalone | **1 passed** → флейк, не регресс |
| полный `pytest -q` | не перезапускал (brief: выборочно); заявленные 15285/39/8 не оспариваю, классификацию 7+1 подтвердил |

## 7. Неблокирующие замечания

1. `_human_status` для `paused` + compat-причина выдаёт «пауза (оператор)» (`embedding_control_plane.py:1965-1979`), и это видно в карточке `ix.status_ru` (`web/index.html:6310`), хотя рядом печатается `код: paused_compat_insufficient`. Одно-строчная правка маппинга по `reason_code`; на приёмку B1 (нет ложного `build_in_progress`, `reindex_required=false`) не влияет.
2. `resume_compat_paused` без `fp` (см. §5) — инертная `queued`-строка; при желании сузить до `fp=current_fp`.
3. `_PAUSED_BY_COMPAT` теперь только пишется (`add/discard`), нигде не читается — мёртвое process-состояние, безвредно.
4. В истории кандидата есть посторонний W4-коммит `dd4e0522`; его UI-изменения требуют собственного ревью/binding, этот вердикт их не покрывает.

## 8. Что осталось до деплоя

1. **3 PENDING карты**: `IDENT-02` (unit на revision/task/normalization/preprocessing/material_params) и `DEC-09` (тест отката adopt → `building`/`config_revision=NULL` → vec закрыт, FTS непустой) — тесты; `CANARY-03` — **не только тест**: `_compat_probe_once` сейчас возвращает `dims` и метрики, но не `model`/доступную revision/параметры генерации (`embedding_control_plane.py:2947-2950`), поэтому требование source «сверить фактические model/version/params» не выполнено — нужно решение (фиксировать из ответа провайдера либо явно `insufficient_data`) и тест. Требования карты: `requirements_gate.py --stage review` сейчас даёт FAIL ровно по ним (IDENT-SPLIT/CANARY/DECISION), ACCEPT/INTEGRATION/GOV — PASS.
2. **Pre-deploy resolve-проба** на read-only копии прод-БД (см. §2), с ожидаемым `insufficient(compat_not_proven)`/`compatible`.
3. После этого — объединённый поезд и postdeploy `ACC-10`/`ACC-11` (`READY_FOR_LIVE`): `compat.serviceable=true`, `generation.state=active`, canary mean/min/hit5, backfill 4048→0, живой поиск; откат — снять допуск (`status='building'`, `config_revision=NULL`).

**Ответ на «можно ли к деплою после A0»:** кодовая часть готова и B1/B3-блокеров больше нет; деплой — после закрытия трёх PENDING и pre-deploy resolve-пробы (плюс штатный release-гейт). Это не Human Gate; всё перечисленное — агентские проверки.

## 9. Acceptance ledger (этот лейн)

| Пункт | Статус |
|---|---|
| B1: restart → incompatible → resume+миграция; insufficient → pause без rebuild; операторская пауза не тронута | **VERIFIED** (probe + 9 тестов) |
| B3: legacy NULL-preproc не даёт incompatible/rebuild; вывод MSI; честный `legacy_metadata_missing`; доказуемая другая модель → миграция | **VERIFIED** (probe на прод-значениях + тесты) |
| B3: реальная прод-строка через `resolve_index_compat` | **UNVERIFIED** — нужен pre-deploy read-only прогон |
| A0 `compatible` (mean/min/hit5=1.0, 42/42) | **VERIFIED** (reused, модуль пробы байт-идентичен) |
| Инварианты: пороги/new-vs-new/kill-switch/ΔDDL=0/нет новых сущностей | **VERIFIED** (дифф + тесты) |
| `5877810d` и `resume_rebuild` TypeError-fix | **VERIFIED** (файлы/код не менялись, смежные зелёные) |
| ACC-10/ACC-11 | **READY_FOR_LIVE** (postdeploy) |
| IDENT-02 / CANARY-03 / DEC-09 | **UNVERIFIED** (PENDING карты, вне этого лейна) |
| Полный suite 15285/39/8 | не перепроверял целиком; выборочно подтверждено |

## 10. Привязка

Кандидат `570e1eee`; evidence `0a456aa9`; карта `c8216346…` (binding-2026-10-23.md); source `429a9868…`. Мои пробы: `OPENCODE_WORKFLOW_SCRATCH/rev-embed-r2/probe_r2.py`, `probe_prod_3072.py` (не в репозитории). Любое изменение кода/карты после этой ревизии требует повторной сверки затронутых пунктов.