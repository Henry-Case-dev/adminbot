# deployment.md — asap-4-embedding-graphrag-cover-runtime (деплой 2.58.45 на прод)

## 0. Статус

**VERIFIED** — 02.10.2026, деплой 10:14–10:35 UTC. Все пост-деплой гейты пройдены; browser-сьют §61.16 A–D (T-4446) — failures: 0.

## 1. Разрешение и биндинг

- **Разрешение:** @Reviewer `Approved for release` (final round 2, 0 blocking, [M-ASAP4-E1] RESOLVED — `review.md` Round 2) + Orchestrator-приказ (phase=delivery, next_agent=DevOps, деплой 2.58.45, Wave F T-4451–T-4452).
- **Ревью-биндинг (верифицирован DevOps независимо ДО любых правок):**
  - HEAD = Reviewed-Commit `f04564b2104cb42057fc363fa5d469d7d09af4be` ✓
  - **WTH `f62243b7a3ec108695761b38e271c29c78bdf15cdf68fd47692bec5015f493d2` — воспроизведён байт-в-байт** независимым скриптом по рецепту round 1/2 (52 файла: 39 tracked `git diff` + 13 untracked content, `path␣␣hash␣␣(origin)`, sorted, LF-join без хвостового newline, SHA-256);
  - пер-файловые пины round-2 дельты: `services/pipeline_analytics.py` → `8d82a3d6` ✓, `tests/test_pipeline_analytics_asap4.py` → `a58c04f1` ✓;
  - Spec-Hash `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10` ✓; staged пусто ✓.

## 2. Release-prep (санкционировано заданием)

- **APP_VERSION 2.58.44 → 2.58.45** в `config/settings.py` (+ цепочка версий: новый head ASAP-4 round1030, mca-22 → «Предыдущая»).
- **Свип version-пинов (конвенция):** 23 py-теста (формы `== "2.58.44"` / `'APP_VERSION = "2.58.44"' in SETTINGS` / regex-группы; 24 замены, `test_webapp_round1026_polygon` — 2), 4 JS-харнесса (`2\.58\.44` → `2\.58\.45` в `tests/js/round1025_hotfix{7,8,9,10}_*`), README-баннер, `plans/docs/param-registry-round1025.meta.md`. Исторические диапазоны канона (`summary_prompts.py` «2.58.33–2.58.44») и процессные доки не тронуты.
- **Полный pytest после свипа — DETACHED-джобой через Task Scheduler (L-ASAP4-9, PowerShell-пайп не использовался): 10773 passed / 2 failed за 335.8s** — ровно пин ревью; оба failed — те же pre-existing round1026 bounds (`test_tool_coordinator…forbidden_paths_out_of_diff`, `test_unified_image_request…vs_baseline`).
- F8 `--check`: `CHECK OK: реестр 488 …`, EXIT=0. Импорт-смоук: `config.settings` (2.58.45) + 7 новых сервисов — чисто.

## 3. WTH re-measure на момент коммита против пина

- 49/52 манифест-файлов байт-идентичны ревью-состоянию (верифицировано до свипа агрегатом WTH = пин; после свипа — пер-файловым пересчётом).
- Дрейд ровно 3 манифест-файлов, каждый — только санкционированные version-pin ханки свипа (+1/−1 строка на файл): `config/settings.py` (APP_VERSION+цепочка), `tests/test_summary_publish_integration_round1026.py`, `tests/test_webapp_f6_round1025.py`. Полный пер-файловый манифест — `C:\Users\main\AppData\Local\Temp\opencode\asap4_manifest_postsweep.txt` (сессия DevOps).
- Инвалидация агрегата ожидаема и санкционирована заданием (release-prep); код вне свипа не менялся.

## 4. Коммиты и пуш

- **Feat:** `9930fc65492ebb167ea4f29dcd7fbefeae2b712a` (`9930fc6`) — **78 файлов, +14456/−348** = 52 файла скоупа ревью (39 tracked + 13 untracked) + 26 релизного свипа (README, param-meta, 20 py-пинов вне манифеста, 4 JS). Сообщение: `feat(round1030): asap-4 embedding-graphrag-cover-runtime — … (APP_VERSION 2.58.45)`.
- **Docs:** `b5eaecd` — 11 файлов (`plans/features/asap-4-…/*` 10 + `plans/reports/full_audit_results.md`).
- Push: `f04564b..b5eaecd master -> master` (origin GitHub), 02.10.2026 ~10:10 UTC.
- **Чужой WIP в коммиты не вошёл (проверено staged-диффом, 0 посторонних):** `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md`, `node_modules/`, `package.json`/`package-lock.json`, `.playwright-mcp/`, `extra_images/` — остались некоммитнутыми.

## 5. Деплой (prod `racknerd-f4e3456`, systemd `admin_bot`)

- **Диск заранее:** 81% used, **4.4G free**; live-БД 1.3G + WAL 4M → гвард mca-14 требует ≈2.65G — запас достаточен (прошлый инцидент 89%/1.5G не воспроизвёлcя).
- `git pull --ff-only origin master` → прод HEAD `b5eaecd`; tracked-дерево прода до пулла чистое.
- **Рестарт #1 (единственный): 10:14:16 UTC**, новый PID 3008232, `NRestarts=0`, ActiveState=active.
- **DDL SQLite v22 → v23 — применена при старте идемпотентно:** 10:18:26 `memory_backup: pre-migration copy created + read-back ok | target_version=22` (авто-бэкап **ДО** DDL: `pre_migration_20261002_101544.db`; старый `pre_migration_20261001_161922.db` ротирован disk_retention), 10:18:26 **`[database] migration v23 applied | embedding_control_plane`**. Суточный бэкап от 00:00 (`backups/local_database_20261002.db`) также на месте.
- **PG no-op:** `[pg_db] DDL ok (таблицы + индексы)` (идемпотентно), пул/роли/админы без изменений.

## 6. Пост-деплой верификация

| Гейт | Результат |
|---|---|
| health | `GET /api/health` → **200 `{"status":"ok"}`** (127.0.0.1:8000) |
| runtime-версия | прод-venv `config.settings.APP_VERSION` → **2.58.45**; `/web/` раздаёт `app.js?v=2.58.45` + `app.css?v=2.58.45` (оба 200) |
| SQLite | `user_version = **23**`; `embedding_quota_state` создана (1 строка состояния); 3 nullable-колонки реестра поколений на месте (`pause_reason`, `next_allowed_at`, `attempts_total`); `schema_migrations` tail: `(23, embedding_control_plane), (22, bot_outputs_ledger)` |
| данные целы | `smart_messages` = 1 990 358 (рос естественно с 1 989 659); поколения: graph_facts_vec + smart_archive |
| mca_events | **пишет**: 65 событий за час после рестарта; транспорт жив (свежие — `EMBEDDING_GENERATION_*` от нового control plane). SUMMARY_*/COVER_* эмиссия верифицирована сквозным E2E browser-сьютa (36 событий через реальный `pipeline_events`+`mca_trace`→`flush_events`); на проде появится с первым реальным Summary-прогоном владельца |
| kill-switches | runtime-резолв: 11 флагов **ON** + `EMBED_ASYNC_BATCH_ENABLED` **OFF** — ровно дефолт; **Δenv=0** (в .env переопределений 12 флагов нет; единственная `EMBED_*`-строка — тюнинг `EMBED_CACHE_MAX_ROWS`, не флаг) |
| GraphRAG rebuild job — честное состояние | `graphrag_rebuild`: resume с checkpoint `cp:graph_facts_vec:1` (10:18:40 `resumed=True`), прогресс 5500/frontier 6712, при 429 → `paused_rate_limit` + «checkpoint preserved» (cooldown ~19s) → авто-resume (`cooldown_expired`); **НЕ failed**. Реестр поколений: graph_facts_vec `building` (pause_reason=rate_limit:quota_group, attempts_total=14 — v23-колонки пишутся), smart_archive `building` |
| lease-санити (рестарт один) | дублей активных джоб нет (`ACTIVE_DUPLICATES: []`); `embedding_rebuild_lease` — 11 finished/released + 1 активный, ни одного зависшего |
| ladder/parity на прод-venv | **309 passed / 0 failed** (50.6s): 5 asap4 волновых файлов (A–E) + `test_mca22_core_round1027` (лестница цитат/core) |
| каталог F8 на проде | `CHECK OK: реестр 488 == REGISTRY…`, EXIT=0 (Δ=0) |
| новые эндпоинты RBAC | `/api/analytics/pipeline/inspector` → **401**, `/api/analytics/pipeline/runs/{id}` → **401**, `/api/memory/embeddings` → **401** (`missing init data`) — admin-only RBAC жив |
| error-spike | **0 ERROR/Traceback** за весь пост-рестарт-лог процесса (338 строк; фон — 14 вхождений «429», обработанных control plane без traceback'ов; baseline до деплоя: 0) |
| R17-скан | 0 вхождений api_key/AIza/sk-/Bearer в логах процесса; эмиссии — только id/числа/коды |

## 7. POST-DEPLOY BROWSER SUITE (T-4446, §61.16 A–D)

Метод: Playwright (MCP), desktop 1280×800 + mobile 390×844, **реальный код webapp этого коммита** (FastAPI-апп через `web.app.create_app`, TMA-initData по контракту `web.api.deps`), сценарии — **API-фикстуры через реальный транспорт mca-17a** (`pipeline_events.summary_*` + `COVER_*` → `mca_events.flush_events` в temp-SQLite v23 → `egs.reset()` = рестарт-паритет → collect_* только из durable-событий). Прод-БД фикстурами не загрязнялась; на проде дополнительно — смоук доставленной сборки (см. §6).

| Сценарий | Ожидание §61.16 | Факт (desktop + mobile) |
|---|---|---|
| A healthy | «Здоров», все узлы ✓, style ✓ | ✓ «Здоров»; Источник→L1→L2→Выбор стиля→База→Стиль→Публикация все ✓, «Итог: опубликовано — RichMessage · 4242» |
| B L2→Legacy | degraded, не healthy | ✓ «С деградацией»; L2 ✕ «Проверка отклонила статью после повторов — отправлена в резервный контур», узел «Legacy · Резервный контур» ⚠ с человечьей причиной |
| C style failure | базовая обложка + причина, публикация ок | ✓ «Здоров»; узел «Стиль» ⚠ «резервный контур — Обработка стилем не завершилась (ошибка провайдера)» (30.0с), base ✓, публикация ✓ (§61.7: fail-open виден, не скрыт) |
| D coverage-fixture | published + coverage 44.6% → НЕ healthy | ✓ latest-карточка «С деградацией», «307 / 688 · Coverage: 44.6%», «✕ Неполное саммари — coverage ниже 100%» (§61.6 first-class) |

- **failures: 0**; бейджи только текстовые, читаемы (§61.13); Run Inspector рендерится на обоих вьюпортах, мобильный — без горизонтального скролла (§61.14).
- Агрегаты 24ч/7д: `Summary runs: 4 · Здоровых: 2 · С деградацией: 2` — ровно фиксчерная истина; стейдж-карточки ✓/⚠/✕ с топ-причинами (§61.5); runs-list бейджи согласованы с drill-down'ами.
- «Developer details» collapsible присутствует (§76). Панель «Embeddings и векторная память» рендерит провайдера/алиасы ключей (без значений — R17 в UI)/quota-группы/concurrency/429-счётчик (E.3).
- Скриншоты: `evidence-browser/asap4_61_16_desktop_latest_D.jpeg`, `asap4_61_16_desktop_B_legacy.jpeg`, `asap4_61_16_mobile_latest_D.jpeg`, `asap4_61_16_mobile_timeline_D.jpeg`.
- Честные границы стенда: 2 консоль-ошибки вне скоупа эпика — `favicon.ico` 404 (нет route в стенде) и `/api/analytics/usage/summary` 500 (урезанный fake-PG стенда для pre-existing виджета токенов; на проде эндпоинт работает с реальным PG, в пост-рестарт журнале 0 ошибок). На сценарии §61.16 не влияют.

## 8. PENDING OWNER / POST-DEPLOY (за пределами delivery, не блокёры)

1. T-4447 live embeddings (платные вызовы; оба индекса → ACTIVE, live KNN) — владелец; сейчас graph_facts_vec building c checkpoint, smart_archive building.
2. T-4448 live Medved Press (precondition DC-4) — владелец.
3. T-4449 live full window (окно 600–700+, coverage 100% на проде) — владелец.
4. §50.62/§50.64 live-метрики Hybrid Writer — накопление после реальных прогонов.
5. SUMMARY_*/COVER_* эмиссия на прод-данных — оживёт с первым реальным Summary-прогоном владельца (Inspector честно покажет; транспорт и read-path доказаны).

## 9. Rollback (готовность, не применялся)

- **Soft:** env-рубильники по доменам — `EMBED_CONTROL_PLANE_ENABLED=false`, `SUMMARY_L2_REVIEW_ENABLED=false`, `SUMMARY_LEGACY_FULL_WINDOW_ENABLED=false`, `SUMMARY_QUOTE_REPAIR_ENABLED=false`, `COVER_STYLE_SNAPSHOT_ENABLED=false`, `SUMMARY_PIPELINE_EVENTS_ENABLED=false` (+ иные из 11) + рестарт → бит-в-бит legacy-пути; v23-объекты при OFF не читаются/не пишутся.
- **Cold:** `git revert`/checkout `f04564b` (v23 аддитивна — старый код её не читает; `DROP TABLE embedding_quota_state` безопасен; 3 nullable-колонки совместимы со старым кодом).
- **Restore:** `pre_migration_20261002_101544.db` (read-back ok) / суточный `backups/local_database_20261002.db`.

## 10. Итог

**VERIFIED.** Прод: HEAD `b5eaecd` (feat `9930fc6`), runtime 2.58.45, SQLite v23, рестарт один, 0 посторонних ошибок, R17 чист, kill-switches дефолт, rebuild-джоба честно resume/paused с checkpoint, RBAC жив, каталог 488, ladder/parity 309 на проде, browser §61.16 A–D desktop+mobile — failures: 0.
