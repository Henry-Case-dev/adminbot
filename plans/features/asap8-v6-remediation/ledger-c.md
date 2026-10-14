# V6 Phase 0 — Ledger C01–C10 (reconcile, read-only)

- Лейн: V6-SCAN-A; дата: 13.10.2026; HEAD: `1e980275ce5c857b825860b50a34a2486c790359` (release 2.58.77, baseline v6).
- Источник требований: `plans/ASAP8_v6_delta_after_F1-F9.md` §B (таблица B — первоисточник ID) + §C03A/§C06A.
- Правило вердиктов (v6 §A.2): код / тесты / коммит / прод-подтверждение — четыре разные сущности.
- **Установленный прод-факт (evidence-точка):** кандидат `1e98027` задеплоен на прод paramiko-сеансом
  (`git pull NEW=1e98027`, `systemctl restart`, RC=0), healthz 200 @ 2.58.77 после обеих волн.
  Целевые prod-пробы (живой Summary, styled cover, инициатива, embeddings rotation, proxy health) НЕ выполнялись.
- Коммиты F1–F9 все присутствуют в lineage HEAD (проверено `git log`): `7fdeaaf`, `fcbbf12`, `a12e6bf`,
  `02b38cb`, `2e145a4`, `cbda23b`, `df1aac4`, `781e9b3`, `dc9ca1c`; F10-пины `3f5b912`, `855a3e5`.

Итоговая сводка: C01/C02/C04/C05/C07/C08/C09 = CODE_PRESENT_LIVE_UNVERIFIED; C03 = CODE_PRESENT_LIVE_UNVERIFIED
(+semantic-выходной слой отсутствует — см. C03A); **C03A = PARTIAL; C06 = PARTIAL; C10 = ABSENT.**

---

### C01 Summary L2 (granular repair/correction)
source: v6 §B строка C01 (F1)
baseline_sha: `7fdeaaf` (в lineage HEAD; 2.58.75)
code path: `services/summary_l2_repair.py` (есть на HEAD), `services/summary_l2_writer.py` (attempt+correction, granular reason), `services/summary_generator.py` (attempted_invalid), `services/pipeline_events.py`, `services/pipeline_analytics.py` (4 coverage-оси), `web/app.js:3529+` — сверено, присутствует.
runtime path: стадия L2 в каждом Summary-ране (hybrid-режим); на прод-конфигурации выполняется при каждом living Summary — живое поведение на 2.58.77 после деплоя не наблюдалось.
ui path: Run Inspector — coverage headline (Source/L1/L2 accepted/Final), `attempted_invalid` подпись.
existing tests: `tests/test_asap8_f1_summary_l2_repair.py` (39) + summary-sweep 1665 (f1-report) — проверяют реальный repair/correction/fail-closed контракт, не мок-self-fulfilling (repair — чистые функции над документом).
missing proof: на живом проде после 2.58.77 не снят ни один run: отсутствие регрессии Hybrid→Legacy на repairable абзаце, правдивость `reason/index/coverage`, отдельный nonrepairable-сценарий.
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: targeted prod probe — 1 живой Summary-run с granular-telemetry (`SUMMARY_L2_STAGE`, coverage-оси) + контроль reason при repairable-абзаце; без нового кода.

### C02 Summary Test parity
source: v6 §B строка C02 (F2)
baseline_sha: `fcbbf12` (2.58.75)
code path: `services/summary_execution_input.py` (есть), `services/summary_generator.py` (prod-вход через ExecutionInput), `services/summary_test_run.py` (test-вход), `services/summary_l1_semantic_map.py` (unknown-ref repair) — присутствует.
runtime path: единая точка сборки входа для dry-run и production; parity fingerprint sha256(run_id∥messages_json).
ui path: dry-run TMA-редактор Summary (test-run поверхности).
existing tests: `tests/test_asap8_f2_summary_execution_input.py` (+20, S5 parity fixture→fingerprint) — контракт реальный (byte-parity), не мок.
missing proof: prod-подтверждение, что dry-run и production на 2.58.77 строят идентичный source-window/anchors (F2-отчёт это локально доказал; live на проде не снимался). unknown-ref не принимается — тестами покрыто, live не требуется сверх этого.
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: включить parity-поля (`fingerprint`, `anchor_mode`) в один живой run + dry-run того же fixture; сверить; без нового кода.

### C03 Style prompt preservation (F3)
source: v6 §B строка C03
baseline_sha: `a12e6bf` (2.58.76)
code path: `services/cover_style_jobs.py` (compile_style_prompt P0 preservation→P0 issue→P1 story→P1 style→P2 refs→P2 base_style→P3; `style_publish_skip_reason`; fail-soft-гейт :1905-1958; `_style_failed` :2224), `services/cover_prompt_assembly.py` (CONTENT_PRESERVATION + манифест) — присутствует.
runtime path: Style-стадия publication-контура Summary (`_maybe_apply_cover_style`, summary_generator.py:3202/3359); fail-soft публикует Base с reason. На проде 2.58.77 styled-исходы не наблюдались.
ui path: Run Inspector — CoverPromptManifest (7 компонент, style_publish_skipped{reason}), F4 status-коды.
existing tests: `tests/test_asap8_f3_style_preservation.py` (13) + cover-sweep 247/265 — контракты реальные (порядок строки, 0 paid calls при skip, parity манифеста).
missing proof: «Реальный styled-provider производит и публикует изображение, сохраняя сюжет» — не доказано на проде (нужен живой run с реальным provider edit + владелец видит styled). При семантическом провале публикуется Base и фиксируется причина — механика есть, но **выходной** semantic-контроль отсутствует (см. C03A): провал провайдера «проехал generic scene» код не различает.
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: живой prod-run с реальным edit-провайдером: styled публикуется, манифест в Inspector; owner visual check отдельно (OWNER_VISUAL_PENDING); семантический остаток — в C03A.

### C03A — P0: Base появляется, styled не появляется / не восстанавливается
source: v6 §C03A (отдельный owner symptom)
baseline_sha: HEAD `1e98027` (симптом зафиксирован владельцем на проде 2.58.77)
code path: полная трассировка и найденные точки разрыва — `rca-c03a-styled-cover.md`. Ключевое: `services/summary_generator.py:3202-3213` (inline style + one-shot публикация), `services/cover_style_jobs.py:630-647` (finish: RESULT_BASE → **completed**), `:696-707` (requeue только preview), `services/cover_style_preview.py:259` (единственный requeue), `services/cover_style_registry.py:880-905` (provenance INSERT без идемпотентности).
runtime path: Style-стадия inline в публикации Summary; durable-джоба kind=cover_style живёт в `task_jobs` (status остаётся `queued` весь прогон — mark_running не вызывается); рестарт посреди стадии оставляет зомби-`queued` (watchdog/recover_stale смотрят только `running`).
ui path: Run Inspector (cover_prompts_status ok/style_job_failed/style_job_not_linked) — читаемо; отдельного «retry styled» в UI НЕТ.
existing tests: F3/F4-наборы покрывают fail-soft и манифест; кейсы v6 C03A «retry восстанавливает styled без новой Base», «durable pending переживает restart и не completed» тестами на production-контуре НЕ покрыты (нет и кода).
missing proof/реализация: (1) production retry/recovery styled ABSENT; (2) reason `semantic_preservation_failed` и `UNVERIFIED_SEMANTIC` ABSENT (grep — только в v6-документе); (3) semantic compare выхода ABSENT (два сюжета → generic scene неотличимо для кода); (4) idempotent publication linkage после публикации ABSENT (сообщение строится один раз, edit_media нет); (5) прод-логи живого run не сняты.
verdict: PARTIAL
next action: (a) снять с прода evidence по живому run (mca_events COVER_STYLE_*, task_jobs kind=cover_style, cover_style_provenance, логи `_style_failed`) — определить, какой из разрывов сработал у владельца; (b) минимальный дизайн-решение по retry/recovery + `semantic_preservation_failed`/`UNVERIFIED_SEMANTIC` (Architect, отдельный артефакт); (c) сквозной provider-recording тест на runtime seam.

### C04 Cover prompt truth UX
source: v6 §B строка C04 (F4)
baseline_sha: `02b38cb` (2.58.76)
code path: `web/api/analytics.py:630` (`/analytics/pipeline/runs/latest`, global-admin fail-closed), `services/cover_style_jobs.py:1401-1473` (cover_prompts_status), `web/api/cover_styles.py` (preview-compile mode=style), `web/app.js` (latest auto-load, блок «Фактический промпт» всегда виден, `coverManifestSourceLabel` знает CONTENT_PRESERVATION) — присутствует.
runtime path: global-admin UI «ИИ → Промпты»; данные — durable task_jobs/Base-манифесты.
ui path: Run Inspector + страница «Стиль обложки» preview.
existing tests: `tests/test_asap8_f4_prompt_truth.py` (18 новых) + analytics 118/45 + routes-freeze + JS — контракты реальные (маршрут до `/runs/{run_id}`, parity байт-в-байт, R17-честность).
missing proof: «Проверить на задеплоенном global-admin UI» — Playwright/Browser Use были локальные; на проде 2.58.77 latest-загрузка/статусы не открывались; exact payload == manifest на живых манифестах не сверялся.
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: prod-проба global-admin: открыть последний run, сверить payload с манифестом и cover_prompts_status при missing; без нового кода.

### C05 Summary/module decouple
source: v6 §B строка C05 (F5)
baseline_sha: `2e145a4` (2.58.76)
code path: `bot.py:855-897` (роутеры инклюдятся безусловно — сверено), `handlers/summary.py:44-50,301` (runtime-гейт flags.summary_enabled), `handlers/direct_chat.py:168-174` (master-гейт botword), `services/param_catalog.py:2733` (`memory.random_enabled` product master PG-only), module_registry/parentGate-удаление в app.js — присутствует.
runtime path: startup-порядок роутеров без if-обёрток; runtime-гейты на входе хендлеров; Random/Experience гейты hot.
ui path: reason-enum chat_off/global_off/env_off/provider_unavailable; Random карточка.
existing tests: `tests/test_asap8_f5_module_truth.py` (19 новых + 48 targeted) — M1–M3/M6/M7 реальные (порядок роутеров бит-в-бит, chat-scope ложь «отключено глобально»).
missing proof: live startup с SUMMARY_ENABLED=false и hot-toggle на проде не выполнялись (f5: «Live: рестарт… owner/после деплоя»). F5 закрывал гейты, не весь Module Contract (оговорка v6) — полнота реестра это D11, не C05.
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: prod-рестарт-проба: выключенный Summary при старте → модульные карточки честные; hot-toggle Random; без нового кода.

### C06 Initiative producer/consumer
source: v6 §B строка C06 (F6)
baseline_sha: `cbda23b` (2.58.75)
code path: producers `services/direct_chat_service.py:1844-1938,2487,7474-7553` (unanswered_question/explicit_request; search_result — схема готова, продюсер не привязан), consumer `memory_maintenance.py:276-381` + `mca_intents.py:1237-1309` + `direct_chat_service.py:7708+` (handle_initiative → L1 → L2 → SendRecheck → send), funnel `status_service.py:850-950` — присутствует.
runtime path: heartbeat-джоба `intent_heartbeat_tick` (300с) регистрируется в `MemoryMaintenanceService.start()` ТОЛЬКО если `intent_heartbeat_enabled()` на старте (memory_maintenance.py:185) — hot-включение после рестарта джобу НЕ регистрирует (см. rca-c06a). Producers пишут intents при Direct-ходах.
ui path: **funnel/state_label/top_block_reason НЕ отрендерены в UI** (проверено на HEAD: web/app.js не содержит state_label/funnel/producers_24h/heartbeat_last_tick; карточка mod_initiative и статус-блок рендерят только requested/effective/source/pending/next_due и legacy `state`).
existing tests: `tests/test_asap8_f6_initiative.py` (23) — интеграционные на реальной SQLite (producers→heartbeat→writer→send, fake-бюджеты); контракты реальные, не мок-self-fulfilling.
missing proof (f6-report §6/§9 прямо): live owner E2E на настоящем рабочем чате; UI-рендер funnel не подключён; `search_result` producer не привязан (осознанно); controlled production observation не выполнена.
verdict: PARTIAL
next action: см. rca-c06a-initiative.md — controlled prod observation + UI-подключение funnel (D12-зависимый slice) + решение по heartbeat-registration асимметрии.

### C06A — P0: Initiative ON часами, Status «не запускалось»
source: v6 §C06A (отдельный owner symptom)
baseline_sha: HEAD `1e98027`
code path: трассировка и риски — `rca-c06a-initiative.md`. Ключевое: `memory_maintenance.py:185` (регистрация джобы один раз на старте), `mca_gates.py:1310-1344` (K1/K2/K3 = env AND hot-каталог), `status_service.py:941` (`state='not_run'` → UI «не запускалось», app.js:7217), funnel-объяснение есть в payload, но не рендерится.
runtime path: см. выше; «не запускалось» = 0 intents + 0 intent-событий у чата (не «воркер мёртв» — это separate heartbeat_last_tick).
ui path: карточка/статус Initiative; funnel invisible.
existing tests: I1–I9 покрыли payload и жизненный цикл; hot-toggle-after-start поведение джобы тестом НЕ покрыто (обнаруженный разрыв).
missing proof: живой prod-цикл initiative (created→due→decided→sent) не снят; конкретная причина у владельца не установлена.
verdict: PARTIAL
next action: (1) controlled production observation по плану из rca-c06a; (2) фикс семантики hot-включения heartbeat (restart-честность в UI либо re-registration) — дизайн-решение; (3) подключение funnel к UI.

### C07 Stories UI
source: v6 §B строка C07 (F7)
baseline_sha: `df1aac4` (2.58.76)
code path: `web/api/stories.py:192-198` (display_names серверный резолв), web/index.html (карточки, `<details data-stories-dev>`), web/app.js — присутствует.
runtime path: лента «Истории чата»; данные из /api/stories/*.
ui path: human-карточки: дата/суть/display names/count; raw IDs — collapsed developer details.
existing tests: `tests/test_asap8_f7_stories.py` (9 новых + sweep 104 + пины 93) — реальная логика резолва/коллизий.
missing proof: live-резолв на прод-чате с реальными участниками/алиасами (f7: «Live резолв на прод-чате — post-deploy evidence»).
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: открыть Stories на прод-чате, проверить display names/ambiguity на живых данных; без нового кода.

### C08 Embeddings quotas/backfill
source: v6 §B строка C08 (F8)
baseline_sha: `781e9b3` (2.58.76)
code path: `services/embedding_control_plane.py` (quota-group ladder label→auto→unknown, cooldown), `services/summary_memory.py` (backfill), `services/memory_maintenance.py:208-215,399-419` (embed_recovery_tick 600с в существующем планировщике — сверено), панель `web` (credential_rows/per-group health, rotation-WARN) — присутствует.
runtime path: rotation при 429; recovery-тик независимо от read-трафика.
ui path: MiniApp-панель embeddings.
existing tests: `tests/test_asap8_f8_embeddings.py` (10 новых + 79 acceptance) — разделение групп/rotation/cooldown реальные.
missing proof: «Live 3 independent provider projects, 429 rotation» — против РЕАЛЬНЫХ prod-ключей не проверялось; f8: «Live прод-пул (3 Gemini-ключа → rotation=grouped) — post-deploy evidence волны». Если prod credentials не работают — не объявлять fixed (оговорка v6).
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: prod-проба: панель rotation-статус, искусственный/естественный 429 → cooldown только своей группы, backfill-декремент; без нового кода.

### C09 YouTube proxy
source: v6 §B строка C09 (F9)
baseline_sha: `dc9ca1c` (2.58.75)
code path: `services/youtube_transcript_engine.py` (407→proxy_auth_failed permanent, retry-матрица :27-34), `web/api/routes.py:2032` (`/youtube/proxy/health` + test, global-admin, rate-limit/singleflight), effective_proxy_profile единый — присутствует.
runtime path: транскрипт-путь yt-dlp/transcript-api через единый профиль; 407 без retry.
ui path: MiniApp-блок «Выжимка видео» (global admin).
existing tests: `tests/test_asap8_f9_youtube_proxy.py` (41 новых + глоб 265 + webapp 162) — реальные классификации/retry-матрица.
missing proof: настоящий proxy health/auth/успешный сценарий после исправления credentials на проде (f9: «Live-проверка против прод-прокси — post-deploy evidence»).
verdict: CODE_PRESENT_LIVE_UNVERIFIED
next action: prod-проба `/api/youtube/proxy/health` + test (оба пути); при 407 — честный permanent без retry; без нового кода.

### C10 Final reconciliation
source: v6 §B строка C10 (F10 отсутствует как итоговый отчёт)
baseline_sha: `3f5b912`, `855a3e5` (только test-pin коммиты)
code path: n/a (артефакт-работа). `plans/features/asap8-reliability-truthfulness/` — f10-report ОТСУТСТВУЕТ (проверено: 0 файлов f10*); workflow_state/runtime_task на HEAD описывают старый baseline (оговорка v6 §0).
runtime path: n/a
ui path: Help/Status финальная сверка не выполнялась (это D14).
existing tests: test re-pin — не acceptance.
missing proof: сводка HEAD/release/prod по всем ID; финальный owner report; обновление Help/Status; machine-checked coverage gate (v6 §E).
verdict: ABSENT
next action: выполнить после закрытия P0-остатков (C03A/C06A и D-блокеров): requirements-map + owner-report + Help/Status reconciliation; не закрывать «зелёным sweep».

---

## Правила чтения вердиктов
- `CODE_PRESENT_LIVE_UNVERIFIED` не означает «не работает» — означает: prod-evidence не снят, закрывать ID нельзя (v6 §A.6: DevOps доказывает deployed SHA + targeted prod behavior).
- PARTIAL-элементы C03A/C06 имеют конкретные перечни остатков в rca-файлах; не переоткрывать F1–F9 целиком (v6 §B запрет).
