# baseline-inventory — §0.1 ТЗ (ASAP 8 v6.3 Live Correction)

- Дата фиксации: 15.10.2026. Все пути/функции проверены grep'ом на HEAD.
- **Git SHA (HEAD/master): `f58a644c5d4997a2fb9a4f6bd913b49220ec279e`** (commit «docs(asap8-v6): workflow_state — v6 deployed 2.58.78, owner live-gates pending»).
- **Версия: 2.58.78** (b9ea490 bump). Deployed: 2.58.78 по сообщению коммита; повторная сверка `/healthz` (порт 443, без SSH) — шаг S0 (см. §3, правила fail2ban AGENTS.md: HTTP-проверка разрешена, SSH не трогать).
- Рабочее дерево на момент фиксации: есть модификации в plans/* (параллельный лен CLEAN-1 архивирует старые каталоги plans/) — код не тронут.
- `plans/workflow_state.md` для этой карты не перечитывался (конкуренция с CLEAN-1); остатки взяты из lane-input + f10-report §4.

## 1. Owner-файлы/функции по требованиям (проверено на f58a644)

| Требование | Файл | Символ/место | Строки на HEAD | Примечание |
|---|---|---|---|---|
| B01 | services/direct_chat_service.py | `handle()` | 1861 | единственные производители — F6 |
| B01 | services/direct_chat_service.py | `_f6_maybe_create_unanswered_question` | 1879 | узкий производитель |
| B01 | services/direct_chat_service.py | `_f6_create_future_intent` | 2550 | узкий производитель |
| B01 | services/memory_maintenance.py | `_tick_intent_heartbeat` | 288, 398 | сканирует due-намерения; 24h ноль — симптом |
| B02 | services/mca_experience_jobs.py | `classify_chat_message` | 259 | regex-хардкод — цель B02.1 |
| B02 | services/mca_experience_jobs.py | `_detect_chat_feedback` | 684 | сканер сообщений |
| B02 | services/mca_experience_jobs.py | `tick_experience_review` | 475 | не доказывает capture→outcome |
| B03 | services/database.py | `purge_expired_graph_facts` | 9634 (упом. G3 в шапке: 43) | noop при infinite_retention |
| B03 | services/database.py | `infinite_retention` | 34, 49, 53 | конфиг-поверхность |
| B03.4 | services/summary_memory.py | `_vec_candidates` | 4206, 4423 | глобальный KNN → фильтр chat_id (остаток D06) |
| B04 | services/cover_style_jobs.py | `compile_style_prompt` | 1440 | P0+P1-состав, `story_floor` обязателен |
| B04 | services/cover_style_jobs.py | `story_floor` | 1430 | полный сюжет обязательным текстом |
| B04 | services/cover_style_jobs.py | `style_publish_skip_reason` | 1412 | overflow → публикация Base |
| B04.5 | services/cover_style_jobs.py | recovery: `recovery_enabled` 237, `recovery_max_attempts` 247, `recovery_backoff_seconds` 303, `recovery_dir` 308; комментарии 2651/2873 («Telegram не позволяет…») | — | см. discrepancy D1 |
| B05/U06 | web/app.js | `coverStyles` state | 1830, 1871 | таймер дёргает state — цель B05.2 |
| B05/U06 | web/index.html | `cover-editor` | 809, 827 | панель редактора |
| B05/U06 | web/static/app.css | `.cover-editor-body` | 2791 | единственная прокрутка (целевая) |
| U01 | web/app.js | `mobileTopnavItems` | 2530 | отдаёт весь navItems — дефект |
| U01 | web/index.html | `mobile-topnav` | 252, 268 | горизонтальная лента всех разделов |
| U01/U07 | web/static/app.css | `.header-sticky` | 378, 960 | |
| U02/U04/U05 | web/app.js | `oversightTabs` | 2016 | содержит `{id:'logs'}` — цель U04.1 |
| U04 | web/app.js | `loadLogs` | 4825, 5045 | на входе в Analytics |
| U04 | web/index.html | `#status-logs` | 5682–5683 | текущее место — секция Analytics |
| U05 | web/app.js | stories render (episode) | 2326–2332 | |
| U07 | web/app.js | `toggleFullscreen` | 12802 | |
| U07 | web/app.js | `initFullscreen` | 4998, 5059 | |
| U07 | web/app.js | `setFullscreenFromTma` | 12823, 12836 | legacy-угадывание isFullscreen |
| U07 | web/app.js | `teardownFullscreen` | 12900, 18472 | |
| U07 | web/index.html | `.header-fs-btn` | 166 | крупная кнопка — симптом Android |
| U07 | web/static/telegram-init.js | SafeArea/viewport bridge | 33–37 | актуальный viewport bridge найден |
| U07 | web/static/vendor/telegram-web-app.js | SDK vendored | файл есть | |
| U07 | web/static/app.css | `.fullscreen-mode` | 858, 1037 | |
| U07 | web/static/app.css | `.header-compact-v2` | 986, 998 | |
| U08 | web/static/app.css | `--glass-*` токены | 11, 20 | |
| U08 | web/static/app.css | `[data-glass]` | 51 | |
| U08 | web/static/app.css | `.glass-panel` | 1485, 1651 | |
| U08 | web/index.html | SVG `#lg-lens` | 32, 40 | filter:url на псевдоэлементе |
| U08 | web/index.html | `data-glass-surface` | 32, 73, 110, 3884 | |
| U08 | web/index.html | vendor liquidglass 0.5.3 | 25, 27 | css+min.js существуют |
| U08 | web/static/vendor/liquidglass.core.0.5.3.{css,min.js} | — | файлы есть | |
| U08 | web/app.js | `_liquidGlassSupported` | 18049, 18087 | |
| U08 | web/app.js | `reconcileLiquidGlass` | 4956, 5002 | |
| U08 | web/app.js | `_initLiquidGlassObserver` | 5003, 18145 | |
| U08 | web/app.js | `_syncGlassLib` | 4881, 18142 | |
| U08 | web/app.js | `UI_LIQUID_GLASS_LIB`/`UI_GLASS_TIER_OVERRIDE`/`UI_LENS_MAX_NODES` | 4296, 18060, 18067, 18244 | lib OFF по умолчанию |
| B06 | web/app.js | `moduleRuntimeNotice` | 10111, 10167 | «не влияет; глобально» |
| B06/B07 | services/param_catalog.py | `_PER_CHAT_CATEGORIES` | 56, 131; `CATEGORY_TEMPORAL` 41, 52; GroupSpec temporal_factcheck 537 | категория известна каталогу |
| B07 | services/pg_db.py | `SEED_CATEGORIES` | 572, 722 | **CATEGORY_TEMPORAL отсутствует** — подтверждено grep (причина ТЗ верна) |
| B06 | services/config_cache.py | `_synthetic_group_items` | 534, 538, 541 | PG-only покрытие |
| B08 | services/mca_episodes.py | `_process_segment` | 1890 | пустой summary без LLM |
| B08 | services/mca_episodes.py | participants `[:50]` cap | 1390 | остаток «stories [:50]» |
| B08 | services/mca_episodes.py | `effective_story` | 370 | |
| B09 | services/database.py | `resolve_canonical_chat_id` | 7735 | canonical resolver (D02) |
| B09 | services/database.py | `_migrate_chat_protected_facts_v6` | 6417 (хук 2638) | защищённые факты |
| B09 | services/chat_lore.py | runtime supergroup -100 prefix | 17 | |
| B11 | services/summary_memory.py | scheduler-область | 4747 | Summary scheduler |
| B11 | services/mca_experience_jobs.py / memory_maintenance.py | тики механизмов | см. выше |Experience/Initiative/Sleep |

Прочее, упомянутое в lane-input как остатки v6: `dossierSaving` shared-state — web/app.js 2071, 8752–8784; stories recall-emitter — **отсутствует** (f10 §4: только прокси excluded_from_retrieval); Direct concurrency live-тест — не проводился (f10 D01 live pending); Experience K2-OFF ре-обработка — f10 D05 live pending.

## 2. Discrepancies (ТЗ ↔ HEAD)

1. **`recover_cover_style_jobs`**: функции с таким именем нет; recovery-механика — `recovery_*` helper'ы (237–308). Комментарии 2651/2873 подтверждают ТЗ: recovery **не вызывает Telegram** (B04.5 нужно спроектировать замену изображения).
2. **`_PER_CHAT_CATEGORIES` отсутствует в web/app.js** — это backend-каталог (services/param_catalog.py); UI-сторона — moduleRuntimeNotice/флаги через API.
3. **CATEGORY_TEMPORAL** есть в param_catalog (L41/52), отсутствует в pg_db.SEED_CATEGORIES (L572/722) — «confirmed code cause» ТЗ B07.2 воспроизведён на HEAD.
4. `web/static/telegram-init.js` — существует и содержит safe-area bridge (ТЗ допускал «найти актуальный»).
5. Имена отчётов v6.3 (`requirements-map.md`, `review-ledger.md`, …) в репо ещё не существуют — создаются волнами (B12.1); путь `plans/features/asap8-v6-3-live-correction/` актуален.
6. Рабочее дерево содержит модификации `plans/*` от параллельного CLEAN-1 (архивация) — для baseline не релевантно, но Builder не должен полагаться на старые пути `plans/features/asap8-v6-remediation/*` (возможен перенос в `plans/archive/`); содержимое f10 используется по существу.

## 3. §0.1-данные для сбора на S0 (не секреты)

Git SHA (f58a644) и deployed SHA (сверка /healthz → version), environment-gates (UI_LIQUID_GLASS_LIB и др.), факты PostgreSQL/SQLite, настройки выбранного чата (Summary/Initiative/Direct/память), 24/48h: API-метрики, trace, job states, counters, ingest cursor, LLM errors, UI-скриншоты Status/Analytics; затем сверка «26/26» f10 с реальностью (B10). Сбор — read-only, до любых миграций; snapshot до массовых операций (B12.6).
