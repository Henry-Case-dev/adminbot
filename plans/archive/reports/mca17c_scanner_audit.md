# Scanner-аудит безопасности/R17 — `mca-17c-analytics-matrix` (T-5197, 07.10.2026)

## Вердикт: **к деплою ДА** (Critical 0 / High 0)

**Сводка: Critical 0 / High 0 / Medium 0 / Low 2 (backlog) / Info 3.**

- Binding перепроверен моим пересчётом: кандидат = working tree поверх HEAD `844ad15` (docs-only над `b25558e` = origin/master; прод 2.58.65/v33, mca-12 VERIFIED). Манифест `plans/reports/mca17c_wth_manifest_review.txt` — **23/23 файла байт-в-байт**, recalc MANIFEST_SHA256 `5e35f97f…22fb7bb` совпал (рецепт: sha256 UTF-8 по 23 строкам «hash  path» в порядке файла + trailing LF). Кандидат — ровно то, что ревьюено (Approved итер.2, B-1/B-2 закрыты). После аудита повторная сверка статуса — дерево не тронуто (write только в этот отчёт).
- Мои прогоны на этом дереве: focused mca-17c (API 15 + инварианты 8, вкл. persistence-тест B-1 и matrix-sync B-2) — **23 passed** (4.4с). Полный suite **12338/4** и JS **62/62** — reuse (Builder/Review, то же дерево по префлайту; 4 pre-existing документированы).
- Независимый репро корня B-1 сохранён: `build_event('OVERSIGHT_JOB_ACTION', outcome='ok')` → **None** (`'ok' not in ALL_OUTCOMES`), с `outcome='success'` → событие строится; в коде fix на месте (`oversight_router.py:504`), словарь НЕ расширялся — контракт §17.2 цел.

## Санкции (мои независимые замеры, не пересказ)

| Санкция | Ожидание | Замер | Способ |
|---|---|---|---|
| DDL | 0 (v33 не растёт) | **v33** | инвариант-тест (fresh `:memory:` → `PRAGMA user_version`=33), passed |
| Каталог | 523 | **523** | `len(param_catalog.REGISTRY)` (тест + число) |
| KS | 85 | **85** | `len(mca_gates.KILL_SWITCHES)` импортом |
| reason | 280 (+1 `oversight_job_action`) | **280**, код ∈ словаре, «контрольные» (`oversight_cancel/resume/retry`, `job_action`) отсутствуют | импорт `REASON_CODES` |
| Тулы | 14 | **14** | `len(TOOL_CALLING_TOOLS)` |
| Widget/реестр | 47 | **47** | `len(PROCESS_REGISTRY)` импортом |
| Routes | +3, NEW-файл | **ровно 3** (`/runs`, `/experience/funnel`, `/jobs/{job_id}/action`), регистрация `web/app.py` под `/api/oversight` | интроспекция роутера + тест |
| routes.py byte-freeze | пин `8153b8bd…c7b45` | **`8153b8bd3897…d0c7b45`** sha256 байт-в-байт | пересчёт |
| APP_VERSION | 2.58.65 не тронут | **2.58.65** | `test_app_version_not_bumped` passed (bump 2.58.66 — DevOps T-5198) |
| Секреты | 0 | **0** | скан 14 код/тест-файлов + 7 док-файлов фичи по 5–7 сигнатурам |

## Чек-лист (сводка, file:line)

1. **RBAC (TH-1):** все 3 маршрута за `requires_global_admin()` (`oversight_router.py:266/:386/:523`; deps: TMA 401 → `user_is_global_admin` 403). Write ровно один — POST jobs/action: только `TaskJobStore.get/cancel/requeue/set_next_retry` (`:548–589`), своего SQL/контура нет (§100.4/A56); cancel — новый expose `task_supervisor.py:685–709` (UPDATE … WHERE status IN (queued,running), fencing_token+1, write_transaction; повтор на терминальном — no-op, инвариант-тест). Actor-аудит **реально пишется** (B-1 закрыт): `outcome="success"`, reason `oversight_job_action`, usage_json{action,actor,changed,idempotent,prev_status} (`:492–515`); persistence-тест (реальный emit → flush → SELECT `mca_events`, 1 строка) — в моих 23 passed. 404/409/422/503-ветки до мутации; идемпотентные реплеи — событие с флагом (TH-8 «1 запрос = 1 событие»).
2. **Read-render честность (§27.3–27.7):** `_derive_status` (`:99–124`) — degraded/partial приоритетнее «грубого» failed; failed+success → partial; silent/skipped → валидное succeeded; interrupted-причины → interrupted; `stalled` — отдельный флаг (`:238`, бейдж «диагностика — не заменяет итог», index.html), статус не подменяет. Denominator-процентов нет; счётчики ok/fail. UI: coverage-счётчики disabled/not_run/not_instrumented видны («не инструментировано N»), honest disabled-подписи у воронки/фуннеля («выключено (гейт банка опыта) — честный disabled»), effect-state: «эффект ещё не измерен» для пустых/unknown (`app.js:8076–8098`), unknown ≠ провал/успек. 22 not_instrumented + 4 v0 — не скрыты (coverage_matrix §3, бейджи «заготовка»).
3. **R17 (TH-3):** детализация run — whitelist 22 полей (`_EVENT_PUBLIC_FIELDS :66–72`), `usage_json/source_ref_json/stack` наружу не идут; из `error_json` — только type/cause ≤120 (`:86–96`); экспорт — client-side Blob из уже очищенного `mca17cRunDetail`, без нового route и без fetch сырых данных (`app.js:7850–7883`). Фуннель личности — подпись «включение в промпт ≠ доказанный эффект (причинность не приписывается)» (index.html:3842); воронка — notes «feedback ≠ уникальные уроки», «unknown ≠ провал/успех» (роутер `:479–482`). Секреты: скан диффа+untracked — **0**; `deploy_commands.txt` git-ignored, в манифесте отсутствует.
4. **XSS (TH-7):** в диффе app.js/index.html (1270 добавленных строк) — **0** HTML-sinks (innerHTML/outerHTML/insertAdjacentHTML/document.write/v-html/eval/Function/srcdoc); единственный `innerHTML` app.js:6779 — пре-экзистинг рендер гайдов (вне диффа). Новые зоны — Vue-интерполяция (дефолтное экранирование) + `encodeURIComponent` во всех URL (`app.js` — 13 мест).
5. **DDL/каталог/KS/тулы/widget (TH-4):** замеры в таблице выше. Caps: scan 5000 / events 1000 / jobs-SQL 500 (`:47–49`), limit ≤200, days 1–365, run_id/job_id ≤120, status 422-whitelist (`_RUN_STATUSES`), SQL полностью параметризован (reason-колонки из константного кортежа `_RUN_REASON_KEYS`). OFF-поведение: гейты observability+telemetry OFF → `available/enabled=false` + пустые структуры, не нули (`:258–260/:286–288`); супервизор OFF → 409 (`:539–541`); funnel гейт OFF → честный disabled (`:401–402`).
6. **TH-1…8:** TH-1 ✓ (RBAC+audit+fencing, только существующие job'ы — 404 иначе); TH-2 ✓ (серверные фильтры, client trust не переносится; admin-API по определению cross-chat — прецедент существующего /api/oversight); TH-3 ✓ (whitelist+экспорт-из-очищенного+0 секретов); TH-4 ✓ (caps+keyset+batch-read без writer-lock); TH-5 ✓ (retry только state-машиной: active→идемпотент, completed→409, interrupted→requeue, error сохраняется; **delivery_unknown не несёт job_id** (`direct_chat_service.py:6531–6537`) → кнопки действий не рендерятся (`v-if="ev.job_id"`) — слепой retry структурно недостижим); TH-6 ✓ (stale-бейджи, honest disabled/empty, без выдуманных трендов); TH-7 ✓ (0 sinks); TH-8 ✓ (после B-1 — реальная запись; «тихих подмен» состояний нет: единственная деривация — `_derive_status`, порядок ветвей не стирает ошибки). Validator-подобных механизмов в фиче нет.
7. **coverage_matrix.md:** мой спот-чек 10+ строк — факты живы: `summary_memory.py:4039` (IMPORT_RETENTION_ENABLED) точь-в-точь; `dream_worker.py:1728/:1751` (DREAM_DEEP_RUN) точь-в-точь; `disk_retention.py:95` точь-в-точь; `direct_chat_service.py:100/:1907` (style_scope) точь-в-точь; `tool_loop.py:49/:133` точь-в-точь; `temporal_factcheck.py:250–256` (factcheck_temporal emit-зона) ✓; `mca_watchdog.py` (WATCHDOG/recover_stale) ✓; `mca_vision.py:~1240` ✓; `bot_persona.py:265–289` (self_model/prompt_render) ✓; `nostalgia_worker.py` NOSTALGIA_ENABLED ✓ (строка уехала: факт :162/:164, матрица :84–101). Шапка 47=20+1+4+22 — воспроизведена ревью и воспроизводится кодом (4 v0 = context.compress/context.selective/memory.lifecycle/relations.semantic, инвариант-тест).

## Находки

| # | Severity | Координаты | Суть | Blocking |
|---|---|---|---|---|
| L-A | Low (backlog) | `oversight_router.py:120–124` | Ветвь `cancelled_total>0 and success_total==0` → при run с успехами и последующим cancelled-событием (last_outcome='cancelled') статус деривируется в «running», а не «cancelled» — вечная «живость». **Сегодня недостижимо**: единственный эмиттер outcome='cancelled' (`mca_intents.note_decision`) и job-события task_supervisor не пишут pipeline_run_id → в /runs (WHERE pipeline_run_id IS NOT NULL) не попадают. Оживёт при будущем инструментировании. Backlog: терминальный last_outcome='cancelled' → 'cancelled' независимо от success_total. | нет |
| L-B | Low (backlog) | `oversight_router.py:299/:326–329/:484–487` | Fail-open чтения: внутренняя ошибка БД возвращают disabled-shape (`available=false, enabled=false`) — в UI неотличимо от выключенного гейта («честный disabled»), что для админ-диагностики — искажение причины пустоты (warning в логе остаётся). Backlog: отдельный `degraded/error`-флаг или distinct reason в ответе. | нет |

## Info

- **I-1.** Отклонённые действия (409 invalid state / 404 / 422) не оставляют OVERSIGHT_JOB_ACTION-события: аудит — на исполненные и идемпотентные запросы; отклонения покрыты HTTP access-log. Граница трактовки TH-8, принятая ревью итер.1/2; эскалации не требует.
- **I-2.** N-1 ревью (мёртвый `idempotency_key`) подтверждён с обеих сторон: UI шлёт body только `{action}` (`app.js:7896`) — поле мёртвое и на клиенте; идемпотентность реально обеспечивает state-машина. Диспозиция @Architect (reconcile) в силе.
- **I-3.** Дрейф номеров строк в coverage_matrix.md (~треть строк: файл/символ верны, строка уехала — напр. `chat_params.py:614` vs матрица :519) — doc-quality, sync-тест сознательно не оверфитится к строкам; поправить при касании.

## Disposition

- Блокирующих находок нет. B-1/B-2 реворка перепроверены в коде и моим рераном (23 passed, вкл. persistence-тест без моков и matrix-sync). Nonblocking-реестр ревью (N-1…N-7) подтверждён выборочно (N-1 — I-2, N-4 — код cancel с fencing, N-5 trigger-фильтр — действительно отсутствует в фильтрах `:161–184`).
- Обязательные post-deploy условия: полный pytest в деплой-цикле T-5198 (обязателен как обычно), prod-smoke двухступенчатый D16 — T-5199/mca-release (live-контур: 13-й сценарий и скриншоты с TMA — там же).
- Rollback: soft — гейты (observability/telemetry/experience/supervisor — env-only, OFF = честные disabled/409 по своим осям); cold revert — DDL=0, БД совместима в обе стороны; reason +1 — единственная словарная дельта, откат словаря не требуется (код не читает его как switch).
- Числа для DevOps (bump 2.58.66): после bump обновить байты манифеста не нужно (APP_VERSION вне 23 файлов; re-pin routes.py уже верифицирован — файл не менялся). Файлы lanes mca-21/mca-12 в кандидат не входят и не пересекаются.

R17: в отчёте секретов и сырого контента нет.

**Вердикт: к деплою ДА** (Critical 0 / High 0 / Medium 0; join-barrier T-5198 @DevOps снят).
