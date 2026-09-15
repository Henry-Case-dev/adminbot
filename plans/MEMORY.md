# AdminBot — Memory Index (plans/MEMORY.md)

Индекс долговременной памяти. Архитектура — `plans/ARCHITECTURE.md` (§1–§39);
бэклог — `plans/backlog.md`. Полная семантическая карта — knowledge graph
(Memory MCP, entity `AdminBot` + модули `adminbot-*` + entity `feature-*`
раунда 10).

> **АКТУАЛЬНЫЙ СТАТУС (15.09.2026):** раунд **10.19 «UPD2 bugfixes»** (UPD2 + итерация 2 **UPD3**)
> — **PLANNED / SPEC_READY, Builder не начат**: **8 фич F1–F8**, **8 ADR (ADR-1019-1…-8)**,
> **88 задач T-1778…T-1865** (исходно T-1778…T-1852 + итерация 2 UPD3 T-1853…T-1865).
> Спеки/ADR — `plans/features/` (**8 папок**). ТЗ — `plans/current_task.md` §UPD2 (стр.130-175)
> + **§UPD3 (стр.178-216)**; ответ владельца — «Принято, реализуем per-chat архитектуру».
> **Каталог-Δ (санкц. UPD3 п.5):** **437/407/412/92/90/20** (REGISTRY/Settings/categorized/
> GROUPS/mapped/TAB_RULES); было 436/406/411/90/88/19. **DDL:** SQLite v10 → **v11 (в планах)** —
> `idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key)` + `import_checkpoints.chat_id`.
> **Дефолты (UPD3):** direct **100** вызовов / **500 000** токенов; фон per-chat **60** / **300 000**;
> контекст **5000/3000/16000** (+ потолок `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`, env-only);
> retention импорта **180**. Baseline: HEAD **`fd6acc7`**, прод **`16a8c0b`** (`release-round1018`,
> PID 2319614), pytest **6139**, SQLite **v10**, APP_VERSION **2.57.0**. Детали — KG-узлы
> `Epic round1019 (UPD2 bugfixes)` / `round10.19-epic` + блок **«Step 2/3»** ниже; метрики —
> `plans/metrics.md`. Предыдущий раунд — **10.18** (COMPLETED + DEPLOYED + ARCHIVED, `16a8c0b`).
>
> **Step 2/3 (Step 2 @Architect + итерация 2 после UPD3 — синк Step 3 @Memory)
> 15.09.2026 (раунд 10.19 «UPD2 bugfixes»):** эпик `Epic round1019 (UPD2 bugfixes)` —
> **PLANNED / SPEC_READY**. **8 фич / 8 ADR / 88 задач T-1778…T-1865** (итерация 2:
> ADR-1019-8 + T-1853…T-1865).
> **F1** `betterstack-ingest-bearer-contract round1019` (T-1778…T-1788, **P0**, **ADR-1019-1**):
> ingest — `POST https://{host}` **без токена в пути** + `Authorization: Bearer {SOURCE_TOKEN}`
> (202/402/403/406; 4xx не ретраить); `_HINT_401` → `_STATUS_HINTS`; **снят ложный WARNING**
> `token == SENTRY_DSN pubkey` (на unified US — **норма**, → `debug`); **`logtail-python` в проекте
> НЕТ** (посылка ТЗ ложна) — прод-точка `services/betterstack_handler.py`; curl-матрикс **{path-token,
> Bearer}×{US,EU}** до правки (**T-1779**, @DevOps, только HTTP-коды); `.env` + рестарт — вне репо; Δ=+1
> (`BETTERSTACK_HOST`, сохранён из 10.18).
> **F2** `direct-chat-budget-unlimited round1019` (T-1789…T-1798 + T-1854/T-1855, **P0**, **ADR-1019-2**):
> sentinel **`0 = запрет`, `−1 = безлимит`**; причина «рассинхрона» — `chat_usage` читал лимиты
> **только** `hot.get` → per-chat override не работал; фикс — per-chat резолв
> (`chat_params.overrides → hot.get → env`, ADR-1018-7 `resolve_setting_cached`);
> `budget_snapshot`/`exceeded_metric`; `exceeded` без метрики → ERROR + **fail-open** (ложный sandbox
> невозможен); дефолты **100/500 000**; **ревью-фиксы Батча B (D-1…D-5):** `worker_budget` (фон) —
> тот же sentinel (`-1`=безлимит, `0`=запрет) + per-chat резолв (дефолты **60/300 000**, `_metric_limit`
> async); `llm_client` — единый снимок (без двойного PG-раундтрипа); fail-open `budget_snapshot`
> пробрасывает `forbidden`/`source` (не хардкод); **SUPERSEDE F-15** (10.3); см. ARCHITECTURE §40.
> **F3** `budget-settings-section round1019` (T-1799…T-1808 + T-1856…T-1860, **P0/P1**,
> **ADR-1019-3** + **ADR-1019-8**): вкладка **`mod_budgets` «Бюджеты»** в nav «Модули»; группы
> **`limits_chat_key`**/**`limits_chat_context`**; 3 per-chat поля («Хранение импорта (дней)» 0=вечно,
> «Лимит токенов/вызовов» −1=безлимит, «Лимит контекста»); тумблер безлимита пишет **существующие**
> per-chat ключи (новых REGISTRY-записей нет); **сид настроек чатов** `services/chat_settings_seed.py` +
> `config/chat_settings_seed.json` (chat_id **−1002661910336**: retention 0, бюджеты −1, контекст max) + guard
> `retention==0 → purge запрещён`; «Сводка» — аддитивный `limits {key_budget, worker_budget, context,
> storage}` (R16) с бейджем «Безлимит (∞)» / «Импорт: Вечно».
> **F4** `direct-context-limit-expansion round1019` (T-1809…T-1817 + T-1861/T-1862, **P1**,
> **ADR-1019-4**): развязка `_build_global_context` (per-block caps) ↔ `_apply_context_budget` (общий
> бюджет); root cause 869 = `resolve_chat_limit(token_default=1000)` → `safe_budget(1000)=1000/1.15`;
> дефолты **5000/3000/16000**; per-chat `−1` → ceiling **`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`**
> (**env-only**, Δ каталога=0); chars-fallback — только аварийный.
> **F5** `status-section-ui-merge round1019` (T-1818…T-1825, **P2**, **без ADR** — UI-вёрстка):
> «Сердцебиение»+«Бот»+«Сервер» → один визуальный блок; удалить строку «Режим … · версия …»
> (`index.html:2141`; API-поля `bot.mode`/`bot.version` остаются, R16); компактное поле поиска по графу
> (мобила/десктоп); конфликт файлов с F3 → вливать ступенями **F3 → F5**.
> **F6** `media-files-avatars-sync round1019` (T-1826…T-1834, **P1**, **ADR-1019-5**): локальный
> fallback аватаров/медиа — общий хелпер `read_local_file_bytes`/`local_file_path` в
> `services/media_download.py`; новый `services/media_integrity.py` (audit/restore ФС↔БД); аддитивный
> `GET /api/status/media-health` (R16, только числа/хвосты `photos/file_*.jpg`); R17 (без `<bot_id>:<token>`
> и абсолютных путей).
> **F7** `memory-retention-health round1019` (T-1835…T-1844 + T-1863/T-1864, **P1**, **ADR-1019-6**):
> retention per-chat `limits.import_history_retention_days=180` (**0=вечно**, иной sentinel, чем бюджеты);
> `purge_imported_history(*, chat_cutoffs: dict[int,int])` — keyword-only allow-list; архив перед purge
> (сбой → не удалять); guard целевого чата; **аудит изоляции I-1…I-9**: **I-2** (`import_key` без `chat_id` +
> глобально UNIQUE → кросс-чат подавление) и **I-6** (`import_checkpoints` только `path`) → **SQLite v11**
> (`UNIQUE(chat_id, import_key)`, ключ `(path, chat_id)`); включение Сна/декая **данными** per-chat
> (ADR-1018-7) + честные метрики памяти (overdue/unconfirmed/размеры).
> **F8** `graphrag-memorize-robustness round1019` (T-1845…T-1852, **P1**, **ADR-1019-7**, **AMEND F-15 §4**):
> `parse_fact_list_ex` → `ok/empty_valid/invalid` (валидный `[]` ≠ невалидный); `LLMError` первичной
> экстракции перехватывается внутри `_memorize_facts_inner` → fallback + **1 bounded retry**; единый
> rate-limited WARNING (60с) вместо спама; канон `FACT_EXTRACT_PROMPT` байт-в-байт, Δ=0.
>
> **Порядок:** **{F1 ∥ F2} → F3 → {F4 ∥ F5} → {F6 ∥ F8} → F7**. **Пересечения файлов:** F2/F3/F4/F7 —
> `param_catalog.py`/`settings.py` (сводить Δ); F3/F5 — `web/index.html`/`app.js`/`app.css`; F7/F8 —
> `summary_memory.py`; F2/F3 — `chat_usage.py`.
>
> **Решения владельца (UPD3):** хардкод безлимитов глобально **ЗАПРЕЩЁН** → безлимит только per-chat
> override (данные), глобальные дефолты — предохранитель; целевой чат `−1002661910336` (retention 0, бюджеты −1,
> контекст max) — **сидом**; санкционированы Δ каталога и **DDL SQLite v11**; дефолты умеренные.
> **UPD2-3 (SSH-фрагмент) — ОТМЕНЁН:** вариант (а) — оставить как есть, `filter-repo` **НЕ трогаем**,
> риск принят (публичный репо, неполный обрывок); S10.18-13 закрыт; значение не цитировать.
>
> **Снятие противоречий (KG, явно):** «logtail-python используется» — **ОПРОВЕРГНУТО** (библиотеки
> в прод-пути нет с раундов 4/5); «`token == SENTRY_DSN pubkey` = ошибка» — **ОПРОВЕРГНУТО**
> (на unified US — норма, WARNING снят).
>
> **Остаётся в силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать, каталог-Δ
> только санкционированно, русские conventional commits; `plans/current_task.md` — untracked
> (`.gitignore:70`), **секреты в KG/MEMORY.md не вносились**.
> **Граф синхронизирован (Step 3):** Epic + **8 Feature** + **8 ADR** (ADR-1019-1…-8) + **7 Risk**
> (`risk-betterstack-bearer-vs-path`, `risk-cross-chat-import-collision`, `risk-catalog-delta`,
> `risk-import-purge-eternal` + `risk-direct-key-budget-ui`, `risk-context-cap-869`,
> `risk-ssh-fragment-tracked`) + **3 ArchitecturalConstraint** (`per-chat-limits-no-global-hardcode`,
> `chat-seed-data-only`, `memory-isolation-by-chat`) + **4 SpecDecision** (owner-UPD3,
> logtail-python-refuted, token==pubkey-normal, ssh-fragment-cancelled) + `tech-debt-round10.19`
> (I-4 vec-KNN global k=3) + `metric-snapshot-round1019-spec-ready`; связи HAS_FEATURE/PART_OF/HAS_ADR/
> DECIDES/GOVERNED_BY/**AMENDS** (ADR-1019-1 → ADR-1018-1; ADR-1019-3/-8 → ADR-1018-6; ADR-1019-8 →
> ADR-1018-7; ADR-1019-8 → ADR-1019-2/-3/-4/-6) / **SUPERSEDES** (ADR-1019-2 → F-15
> `direct-sandbox-budget-investigation`; ADR-1019-7 **AMEND F-15 §4**) / DEPENDS_ON /
> RESOLVED_BY / HAS_TECH_DEBT / HAS_METRIC.

> **Архив (раунд 10.18): «Memory-Graph-Sleep-BetterStack bugfixes»**
> — **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН**: **7 фич F1–F7**, **75 задач T-1703…T-1777**,
> **7 ADR (ADR-1018-1…-7)**; спеки+ADR — `plans/archive/<feature>/` (7 папок:
> `betterstack-us-region-401`, `settings-worker-sync`, `sleep-manual-cascade-badges`,
> `graph-density-scoring-stoplist`, `graph-physics-stabilization`,
> `metafact-penalty-extractor-prompt`, `role-matrix-settings-actualization`).
> **Каталог-факт: REGISTRY 435→436 / Settings 406** (Δ=+1 — только F1 `BETTERSTACK_HOST`;
> **новых фича-флагов НЕТ** — плановый 437/407 с F5-флагом **отменён**, флаг
> `flags.metafact_penalty_enabled` не вводился; `categorized 411 / GROUPS 90 / mapped 88 /
> TAB_RULES 19` — без изменений). **DDL SQLite v9→v10** (`edges.fact_id` + индекс, F3;
> применена на проде, `PRAGMA user_version=10`). Прогоны: pytest **6007 → 6139 passed / 0 failed**
> (+132), JS-гейты OK. Деплой: commit **`16a8c0b`**, push `118a03c..16a8c0b`, прод
> fast-forward `b6c153f..16a8c0b`, `admin_bot` active PID **2319614**, `/api/health` **200**
> (+ публичный healthz 200). Baseline HEAD **`118a03c`**, прод release-round1017 (**`b6c153f`**),
> APP_VERSION **2.57.0** (без бампа). Детали — KG-узлы `release-round1018` /
> `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` + блок **«Step 10 (финал)»** ниже;
> метрики — `plans/metrics.md`. ⚠️ Остаточный блокер: BetterStack 401 — версия 10.18 «неверный токен»
> **опровергнута раундом 10.19: причина — ingest-контракт (path-token → Bearer), токен корректен**
> (см. блок 10.19 выше и KG `SpecDecision token-equals-pubkey-normal round1019`).
> Предыдущий раунд — 10.17 (COMPLETED + DEPLOYED, `b6c153f`).

> **Step 2/3 (Step 2 @Architect + итерация 2 после human-gate — синк Step 3 @Memory)
> 15.09.2026 (раунд 10.18 «Memory-Graph-Sleep-BetterStack bugfixes»):** эпик
> `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` — **ARCHITECTED / SPEC_READY,
> Builder не начат**. ТЗ — `plans/current_task.md` §1–§5 + **UPD владельца (строки 109-128)**.
> **7 фич F1–F7 / 75 задач T-1703…T-1777** (итерация 2: F2 T-1767…T-1772, F3 T-1773…T-1777,
> F7 T-1758…T-1766) + **7 ADR (ADR-1018-1…-7)**. Каталог-Δ (санкц.): **REGISTRY 437 /
> Settings 407** (F1 +1, F5 +1); **GROUPS 90 / mapped 88 / TAB_RULES 19 — без изменений**;
> F2/F3/F4/F6/F7 Δ=0. **DDL: SQLite v9→v10** — nullable `edges.fact_id` + индекс (F3).
> **Порядок:** **F7 → F2 → F3 → {F4 ∥ F5} → F6** (F1 — параллельная инфра-плоскость
> @DevOps: `.env` + `systemctl restart`). **Рекомендация @PM** была `{F1 ∥ F2} → F3 →
> {F4 ∥ F5} → F6`; ADR-1018-2 D8 / ADR-1018-7 ставят F7 перед F2.
>
> **F1** `betterstack-us-region-401 round1018` (T-1703…T-1711, **P0**, **ADR-1018-1**):
> посылка ТЗ неверна — библиотечный `LogtailHandler` НЕ в прод-пути с раунда 4/5; реальная
> точка `bot.py:141-145` (`BetterStackHandler`), host не передавался → EU-дефолт
> `in.logs.betterstack.com` → 401 на US-токене. Решение: `BETTERSTACK_HOST` обязателен
> (env-only, **REGISTRY 435→436**; пусто → хендлер не создаётся + WARNING fail-safe);
> `token_equals_sentry_public_key()` → WARNING (не блок); Sentry/BetterStack разведены;
> startup-лог (R17); `.env` — только рестарт. **T-1704 — обязательный curl-матрикс
> {US,EU}×{Source Token, public key} ДО правки кода.** Артефакт `test_monitoring_smoke.py`
> (библиотечный `LogtailHandler` без host) — на ревизию. `CHECKUP_BETTERSTACK_SQL_HOST` —
> другой контур, вне скоупа.
> **F2** `sleep-manual-cascade-badges round1018` (T-1712…T-1726 + T-1767…T-1772, **P0**,
> **ADR-1018-2**): `manual=True` — **безусловный приоритет БЕЗ фича-флагов** (UPD п.2);
> обходит window_skip/kill-switch/near-limit/суточные бюджеты/тайминги каскада
> (аудит `gate_override`/`budget_override`; Worker Budget как **учёт** сохраняется);
> **НЕ обходит** локи/`protected_facts`/≥2 `source_ids`/R17/`persona_enabled`/целостность;
> каскад Сон→Глубокий→Личность (+`stats['cascade']`); пороги ослаблены 2/8/2/10/60/300000/10
> + идемпотентная **DML**-миграция PG; реактивные бейджи без WebSocket
> (`active_until=now+900с`, оптимистичный фронт + ретраи); **S10.17-2 закрывается**
> (`cognition==null` → `—`/`badge-muted`, T-1721); диагностика Личности (7 R17-safe исходов).
> **Жёстко зависит от F7** (D8).
> **F3** `graph-density-scoring-stoplist round1018` (T-1727…T-1735 + T-1773…T-1777, **P1**,
> **ADR-1018-3**, **SUPERSEDE ADR-1015-2**): `score = Σ edge_importance` (COALESCE
> `f.importance`/`e.weight`) ×2 за Убеждение/Парадигму; STOP_LIST центров (6 слов) только к
> seed-выборке; **seeds 150 / cap 800-2400** → 500–800 узлов; **DDL v9→v10**: `edges.fact_id`
> nullable + индекс, reorder `insert_graph_fact` ДО `upsert_edge(..., fact_id=…)`,
> legacy NULL (без backfill); единый `services/graph_stoplist.py`; флаг
> `flags.graph_scoring_v2_enabled` OFF (⚠️ см. дрейф Δ).
> **F4** `graph-physics-stabilization round1018` (T-1736…T-1741, **P1**, **ADR-1018-4**,
> **AMEND F2 10.15**): `iterations=150` + `net.once('stabilizationIterationsDone'/'stabilized')`
> → `physics.enabled=false`; `destroy` пересоздаёт с options; `reducedMotion`/поиск/подсветка
> без изменений; Δ=0.
> **F5** `metafact-penalty-extractor-prompt round1018` (T-1742…T-1749, **P1**, **ADR-1018-5**,
> **AMEND ADR-1013-3**): `FACT_EXTRACT_PROMPT` — модульная константа → `PREV_…` + байт-тесты,
> `PROMPT_MIGRATIONS` **не трогается** (крон-промпт `EXTRACT_PROMPT` — другой, вне скоупа);
> `importance` считает `rule_importance()`, НЕ LLM; хард-лимит **`min(imp, 1)`** в
> `insert_graph_fact` по penalty-стоп-листу (6 слов, отдельный frozenset); флаг
> `flags.metafact_penalty_enabled` OFF (**+1 REGISTRY/+1 Settings**).
> **F6** `role-matrix-settings-actualization round1018` (T-1750…T-1757, **P2**, **ADR-1018-6**):
> «Матрица ролей» = фактическая карта мини-аппа (3 nav: Модули 11 / ИИ 7 / PERMsoc);
> `NAV_TITLES`/`NAV_ORDER`/`TAB_NAV` — Python-метаданные (счётчики не растут); подпись
> `CONFIG_TAB_TITLES[permsoc]` → «PERMsoc» + инвариант-тест; аддитивные `nav/nav_title/nav_order`;
> сводит Δ каталога (**437/407** vs 436/406). Последняя.
> **F7** `settings-worker-sync round1018` (T-1758…T-1766, **P0 — новый пункт итерации 2**,
> **ADR-1018-7**): **критичный рассинхрон UI↔воркеры** — тумблеры Dream/DeepSleep ON в UI,
> бэкенд видит OFF. Корень: воркеры/статус-API читают только глобальный `hot.get`, а UI пишет
> в `chat_params.overrides`; планировщик регистрирует джоб один раз на старте; `pg_notify`
> без `LISTEN`; тумблер `deep_sleep` вне окна «Сон». Решение: единый accessor
> (**per-chat DB → глобальный DB → env-дефолт**), реактивный планировщик, `LISTEN`, `source=`
> в статус-API/логах, UI-хинт (Δ=0). **F7 — первая** (без неё F2 не проверяема).
>
> **Решения владельца (UPD, итерация 2):** DDL `edges.fact_id` v9→v10 — **ДА**; manual обходит
> гейты **без фича-флагов** (новый стандарт базовой логики); включать
> `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` + **починить рассинхрон** (F7); BetterStack host через
> env; лимиты графа (seeds 150 / cap 800-2400), STOP_LIST, **importance мета-узлов = 1** — «как есть».
>
> **Противоречие памяти о BetterStack 401 — RESOLVED WITH ADR-1018-1:** в KG две
> взаимоисключающие записи (раунд 5 / T-746: «токен == public key `SENTRY_DSN` → 401» vs
> раунд 6: «ошибочная эвристика, Errors и Logs делят один токен, Sentry-сравнения удалены»).
> Итог: первопричина — **EU-хост при US-регионе**; диагностика **curl-матриксом ДО правки**
> (T-1704); хост US через `BETTERSTACK_HOST`; сравнение возвращается **только** как WARNING-диагностик
> (KG `risk-betterstack-401-token-vs-region-round1018`).
>
> **⚠️ Дрейф — СУЖЕН (F3-часть снята, Step 3→реализация):** F3 объявляла «каталог Δ=0»,
> но ADR-1018-3 D7 вводил флаг `flags.graph_scoring_v2_enabled` — **флаг НЕ вводится**
> (D7 финально: поведение безусловно, дед-кода OFF нет, откат = `git revert`), поэтому
> конфликт «Δ=0 ↔ флаг» снят. Остаётся: spec F6 §6 всё ещё пинит `REGISTRY == 436`
> против §5 `437`; backlog (Step 1) устарел (6 фич / 5 ADR / нумерация
> `1018-4=metafact, -5=role-matrix`). На Merge — единый свод и обновление пин-тестов
> (KG `risk-catalog-delta-drift-round1018`).
>
> **Остаётся в силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать,
> каталог-Δ только санкционированно, русские conventional commits; `plans/current_task.md` —
> untracked (`.gitignore:70`), **секреты ТЗ в KG/MEMORY.md не вносились**.
> **Граф синхронизирован (Step 3):** Epic + 7 Feature + 7 ADR + 7 Risk + 3 ArchitecturalConstraint
> + ExternalDependency BetterStack + SpecDecision owner UPD + `tech-debt-round10.18` +
> `metric-snapshot-round1018-baseline`; 85 связей (HAS_FEATURE/PART_OF/GOVERNED_BY/DECIDES/
> **SUPERSEDES** (ADR-1018-3 → ADR-1015-2; ADR-1018-2 → F-10), **AMENDS** (ADR-1018-1 → раунды
> 4/5; ADR-1018-4 → F2 10.15; ADR-1018-2 → ADR-1017-3; ADR-1018-5 → ADR-1013-3),
> DEPENDS_ON (ADR-1018-2 → ADR-1018-7), RESOLVED_BY и др.).
>
> **UPD (Step 10, 15.09.2026): блок «Step 2/3» выше — исторический снимок планирования.**
> Факт финала: раунд **COMPLETED + DEPLOYED**, спеки в `plans/archive/<feature>/` (7),
> каталог **436/406** (F5-флаг не вводился; plan **437/407 отменён**), pytest **6139**,
> SQLite **v10**, commit **`16a8c0b`**; «Builder не начат» — устарело (все 75 задач закрыты).
> Актуальные цифры — в блоке «Step 10 (финал)» ниже и в `plans/metrics.md`.

> **Step 10 (финал @Memory) раунда 10.18 «Memory-Graph-Sleep-BetterStack bugfixes»
> (15.09.2026):** эпик `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)`
> → **COMPLETED + DEPLOYED + ARCHIVED**; создан релиз-узел **`release-round1018`**
> (alias **`release-16a8c0b`**, commit **`16a8c0b`**), фичи F1–F7 связаны
> (`DEPLOYED_IN release-round1018`), обновлены 7 ADR-1018-1…-7 (Accepted/реализовано),
> Risk-узлы (betterstack-401 → **RESOLVED** с остаточным блокером; catalog-delta-drift →
> **RESOLVED/NARROWED**; 5 проектных рисков **CLOSED**), `tech-debt-round10.18` (финал),
> `metric-snapshot-round1018-final`. Связи: `ADR-1018-6 AMENDS OD11-OD15`;
> дублирующие ADR-узлы итерации 2 консолидированы в канонические `ADR-1018-1…-7`.
>
> **Деплой-верификация:** commit **`16a8c0b`** (`fix(services,web,plans): раунд 10.18 —
> BetterStack US-хост и единый источник настроек воркеров, manual-приоритет Сна и каскад,
> скоринг графа Σ importance (SQLite v10), плотность и физика, пенализация мета-фактов,
> матрица ролей (тесты 6139)`); push `118a03c..16a8c0b`, прод fast-forward
> `b6c153f..16a8c0b`; `.env` += `BETTERSTACK_HOST=s2736363.us-west-2a.betterstackdata.com`,
> бэкап `.env` + SQLite (`local_database.db.bak.2026-09-15-0744`); `admin_bot` active
> PID **2319614**; `/api/health`=**200** (+ публичный healthz 200); миграция v10 применена
> (`PRAGMA user_version=10`); DML-миграция порогов Сна применена.
>
> **Метрики:** pytest 6007 → **6139 passed / 0 failed** (+132; scan-итерации 6042→6052→
> 6083→6104→6137→6139); JS-гейты OK; `git diff --check` clean; каталог **436/406/411/90/88/19**
> (Δ=+1); SQLite **v10**; APP_VERSION 2.57.0 без бампа. **@Reviewer:** Approved по всем
> батчам (4 раунда ревью + фиксы; отклонений Б1=1/B2=2/B3=1/B4=1). **@Scanner:** финал
> **0 Critical / 0 High** открыто; закрыто **1 High** (`S10.18-1`) + 6 Medium
> (`S10.18-15/-21/-22/-30/-35/-36`) + множество Low (закрыт `S10.17-2`); открыто
> **1 Low `S10.18-29`** + Info. **@Builder — ~7 rework-циклов.**
>
> **Ключевое:** BetterStack — US-хост через env (401 остаётся из-за неверного токена, не хоста);
> единый источник настроек воркеров (per-chat DB → global DB → env) + реактивный планировщик;
> manual-приоритет Сна с безусловным каскадом Сон→Глубокий→Личность (без флагов) и реактивными
> бейджами; граф — скоринг Σ importance + STOP_LIST + плотность 500–800 + физика off по
> стабилизации; пенализация мета-фактов (importance=1) + RAG-множитель; Матрица ролей под
> фактическую структуру мини-аппа. **SQLite v10**, каталог Δ=+1. §39 ARCHITECTURE.md.
>
> **Техдолг (открыт):** **Low `S10.18-29`** (deep-manual маркер при каскаде) + **Info**
> (`S10.18-12` NostalgiaWorker global-only → backlog **T-1764**; `S10.18-13` фрагмент
> SSH-пароля в tracked `plans/archive/security-rotation-finalize-round1016/spec.md:35` —
> вычистить + скан истории, значение НЕ цитировать; `S10.18-18/-19/-20`, `-31/-32/-33`,
> `-37` живая RAG-проверка). **Остаточный блокер владельцу:** реальный Source Token
> BetterStack в `.env` + рестарт (401). Живые проверки RAG/графа/бейджей/manual-каскада —
> за владельцем. Архив: `plans/archive/<feature>/` (**7 папок**; всего **76**), §39
> ARCHITECTURE.md.

> **АКТУАЛЬНЫЙ СТАТУС (14.09.2026):** раунд **10.17 «Mobile-Download-Badges»**
> — **COMPLETED + DEPLOYED** (функциональный HEAD == origin/master == **`b6c153f`**;
> ТЗ — `plans/current_task.md` секция «UPD3:», строки 155-160): 5 фич F1–F5
> (F1 `miniapp-mobile-dns`, F2 `tool-download-quality`, F3 `sleep-badge-countdown`,
> F4 `ssh-rotation-cancelled`, F5 `warnings-hygiene`), **37 задач T-1666…T-1702**,
> релиз **`release-round1017`** (alias `release-b6c153f`), 3 ADR (ADR-1017-1/2/3;
> ADR-1017-2 **SUPERSEDE** ADR-1016-1 §2 п.3/§3). ARCHITECTURE.md **§38**. Прод
> `admin_bot` active PID **2016726**, `/api/health` **200**, `/healthz` + `HEAD /web/`
> **200**, pytest **6007 passed / 0 failed** (+71), каталог **435/406/411/90/88/19**
> (Δ=0), миграций нет, APP_VERSION **2.57.0**. Спеки+ADR — `plans/archive/*-round1017/`
> (**5 папок**; всего **69**). Детали — KG-узел `Epic: Mobile-Download-Badges round1017`
> + блоки «Step 0», «Step 2/3» и **«Step 10 (финал)»** ниже; метрики — `plans/metrics.md`.
> Предыдущий раунд — **10.16 «Download-Guide-MobileAudit»**
> — **COMPLETED + DEPLOYED** (функциональный HEAD == origin/master == `eb3fd4a`): 5 фич F1–F5,
> 41 задача T-1625…T-1665, релиз **`release-round1016`**, 3 ADR (ADR-1016-1/2/3),
> заархивирован (`plans/archive/` — **64 папки**; `plans/features/` — 6 активных
> F-1…F-6). APP_VERSION **2.57.0** (без бампа), pytest **5936 passed / 0 failed**
> (+162), каталог **435/406/411/90/88/19** (Δ=0), БД без новых миграций
> (F2 — DML канона), прод `admin_bot` active PID **1976836**, `/api/health` **200**.
> Предыдущий раунд — **10.15** (COMPLETED + DEPLOYED, HEAD `d01a539`, гибридный
> Tool Calling; далее 10.14 — PG `personas`/`persona_traits`/`persona_state`;
> флаги `persona_enabled`/`bot_self_awareness_enabled` = **ON**).
> Метрики — `plans/metrics.md`. Блоки раунда 10.16 — ниже.

> **Step 0 (recon @Memory) раунда 10.17 «Mobile-Download-Badges» (14.09.2026):**
> ТЗ — `plans/current_task.md` секция «UPD3:» (строки 155-160). KG-узел
> `Epic: Mobile-Download-Badges round1017` + 5 Feature (§1–§5) + 5 Risk +
> `tech-debt-round10.17` + `metric-snapshot-round1017-baseline` +
> `ArchitecturalConstraint miniapp self-host, no external CDN` + SpecDecision
> `ssh-rotation-cancelled round1017`. Статус — **RECON, Builder не начат**.
> Baseline: HEAD `772f192`, прод release-round1016 (`eb3fd4a`), APP_VERSION 2.57.0,
> pytest 5936/0, SQLite v9, каталог 435/406/411/90/88/19 (Δ=0).
>
> **§1 (P0, миниапп Android):** `net::ERR_NAME_NOT_RESOLVED` сохраняется после F4
> 10.16 (self-host CDN + CSP). Git-находка: `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL`
> (`config/settings.py:171-173,988-989` → `https://admin-bot.duckdns.org/web/`),
> кнопка (`handlers/menu.py:48-66`) и домен/scheme/path **в 10.13–10.16 НЕ
> менялись**; единственное крупное изменение рядом — F4 10.16 (`web/index.html`
> self-host, `web/app.py:_CSP_HTML`, `/static/app.css`). В `web/` внешних
> http(s)-URL больше нет (grep пусто) → **ERR_NAME_NOT_RESOLVED = сбой резолва
> топ-домена, не CSP/subresource**; причина инфраструктурная (блокировка
> duckdns мобильными операторами / Private DNS / протухшая запись / кэш после
> смены A 10.16). Проверка — @DevOps (`dig A/AAAA`, `curl -I`, Android).
>
> **§2 (P0, tool-download):** tool `download_media` не работает и НЕ спрашивает
> качество; прямой «Бот, скачай» работает с выбором качества. ⚠️ **КОНФЛИКТ** с
> F1 10.16 / ADR-1016-1, где прямо записано «quality в JSON-Schema НЕ
> добавляется» (авто=`max`) → требуется SUPERSEDE пункта ADR. Точки:
> `services/tool_router.py` (~592-599), `tools/video_downloader.py`,
> `handlers/video_download.py` (~284-343), `services/media_send.py`.
>
> **§3 (P1, бейджи Сна):** UI показывает целевой час, не остаток —
> `web/app.js:1210-1245` (`dreamPhaseBadge`/`deepPhaseBadge`) + `fmtClock`
> (`web/app.js:5112-5119`); данные — `web/api/memory_agi.py:430-545`
> (`_next_hour_epoch` :75-88, `_in_hour_window` :104-116). Нужен duration-
> countdown; «Глубокий сон выключен» = `flags.deep_sleep_enabled` false;
> `deep.next_run_at` for `after_sleep` = next_wake (начало обычного сна) — вероятная
> логическая ошибка. Эмодзи не трогать, каталог-Δ=0.
>
> **§4 (CANCEL):** владелец отменил ротацию SSH — секреты в `plans/current_task.md`
> норма, файл не в репо (`.gitignore:70`); узел `security-rotation-finalize-round1016`
> → CANCELLED.
>
> **§5 (гигиена):** 3 WARNING в `web/api/avatars.py` (старый код, `d082800`/10.10;
> generic `except Exception`+`exc_info`) — понизить/убрать traceback (R17);
> «brotli» = только build-time (`scripts/requirements-font.txt`), Caddy-бротли
> требует плагина `http.encoders.brotli` (`xcaddy`) — @DevOps вне репо.
> Техдолг — `tech-debt-round10.17`.

> **Step 2/3 (Step 2 @Architect — синк Step 3 @Memory) 14.09.2026 (раунд 10.17
> «Mobile-Download-Badges»):** эпик `Epic: Mobile-Download-Badges round1017` —
> **ARCHITECTED / SPEC_READY, Builder не начат**. **5 фич F1–F5 / 37 задач
> T-1666…T-1702** (во всех 5 `plans/features/*-round1017/` — `spec.md` + `tasks.md`,
> 🟣 SPEC_READY) + **3 ADR** (ADR-1017-1/2/3; F4 docs-only и F5 brotli-WONTFIX — без ADR).
> Каталог-Δ = **0** (REGISTRY **435** / Settings **406** / categorized **411** /
> GROUPS **90** / mapped **88** / `TAB_RULES` **19**); **DDL нет** (SQLite v9).
> Baseline: HEAD `772f192`, pytest **5936/0**, APP_VERSION **2.57.0**, прод
> release-round1016 (`eb3fd4a`, PID **1976836**).
>
> **F1** `miniapp-mobile-dns` (T-1666…T-1674, **P0**, **ADR-1017-1**): причина —
> сбой резолва **топ-домена** `admin-bot.duckdns.org` (не subresource/CSP);
> hostname/схему/путь **в репо не меняем** (`WEBAPP_URL` env-driven → смена домена
> = правка `.env` + restart, процедура в ADR §4). Repo-меры: явные **HEAD `/web/`**
> и `/web/index.html`, unauth **`/healthz`** (GET+HEAD, `no-store`), startup-лог
> host/scheme/path (host-only, R17), регресс-гейт «нет внешних CDN + консистентные
> absolute-URL». Реальный DNS-фикс — **@DevOps** вне репо (DuckDNS A/AAAA/TTL,
> Private DNS/DoH, live Android-смоук). CDN не возвращать (ADR-1016-2 в силе).
> **F2** `tool-download-quality` (T-1675…T-1684, **P0**, **ADR-1017-2**,
> **⚠️ SUPERSEDE ADR-1016-1** §2 п.3/§3): меню качества инициирует **бэкенд** —
> `probe` → инлайн-клавиатура **`tdq:<height>`** → `tool_response`
> `{status:"needs_quality"}`; callback `tdq:` в роутере **4e** доводит download+send
> (как Fast-Track `cb_pick_quality`). `quality` в JSON-Schema — **опционально**
> (`QUALITY_ENUM` ↔ `_ALLOWED_HEIGHTS`) при явном запросе; прямой медиа-URL — без
> меню; bounded fallback `download(url,None)`; кулдаун **D279** (touch только после
> успеха, callback не трогает); pending in-memory **TTL 600с** без PG/DDL; лимиты
> tool-loop **4/2** и tool-сет **7** не меняются. **Конфликт с F1 10.16 снят.**
> **F3** `sleep-badge-countdown` (T-1685…T-1691, **P1**, **ADR-1017-3**, независима):
> `now` = серверный `cognition.generated_at`; новый `fmtCountdown` (**Xч Yм** / Yм /
> 0м, округление вниз, кламп ≥0); вне фазы — «Сон через {остаток}» / «Глубокий сон
> через {остаток}» (при `enabled=false` — остаток `badge-muted` **без свечения**, не
> «выключен»); в фазе — `.glow` + «Сон до HH:MM» / «Глубокий сон до HH:MM»; **эмодзи
> ☀️/🌙/🌅/🌌 не трогать**; `limit_exhausted` сохраняется; API и оконная семантика
> 10.15 не меняются; без tick-таймера.
> **F4** `ssh-rotation-cancelled` (T-1692…T-1695, **P0 doc**, docs-only, без ADR,
> последняя): **ОТМЕНА** ротации SSH (10.16 F5) — CANCELLED-пометка в
> `plans/backlog.md` + архиве 10.16, снятие README-overclaim (строки 74/387),
> подтверждение untracked `plans/current_task.md`; **кода — ноль**.
> `security-rotation-finalize-round1016` → **CANCELLED**.
> **F5** `warnings-hygiene` (T-1696…T-1702, **P2/P3**, без ADR, независима): политика
> уровней логов в `web/api/avatars.py` (TelegramBadRequest → `debug` без `exc_info`;
> транзиент → `warning` без трейса, не кэшируется; прочее → `warning` с `exc_info`,
> R17-safe; негатив-кэш сохранить) + **brotli WONTFIX** (Caddy `zstd+gzip` уже
> включено; brotli в репо — только build-time); тесты `caplog`.
>
> **Порядок:** F1 ∥ F2 ∥ F3 ∥ F5 → F4 (docs, последняя); **все фичи независимы**
> (DEPENDS_ON внутри раунда нет; F4 связана с 10.16 F5). **В силе:** R16, R17,
> порядок роутеров `bot.py`, `media/`/`.env` не трогать, каталог-Δ только
> санкционированно, русские conventional commits. **Граф синхронизирован (Step 3):**
> 5 Feature + 3 ADR (`ADR-1017-1/2/3`) + компоненты `HEAD /web/ + /healthz routes`,
> `tool quality-menu flow (tdq:)`, `sleep badge countdown (fmtCountdown)`,
> `avatars log hygiene`, `F5 brotli WONTFIX`, `ADR-1016-1 Download contract`;
> обновлены Risk/SpecDecision/`tech-debt-round10.17`/`DuckDNS + Caddy + Let's Encrypt`/
> `miniapp self-host, no external CDN`/`tool_router download_media`; связи
> PART_OF/IMPLEMENTS/DECIDES/**SUPERSEDES** (`ADR-1017-2` → `ADR-1016-1`; F2 →
> `download contract quality fix`) + `metric-snapshot-round1017-spec-ready`.

> **Step 10 (финал @Memory) раунда 10.17 «Mobile-Download-Badges» (14.09.2026):**
> эпик `Epic: Mobile-Download-Badges round1017` → **COMPLETED + DEPLOYED**;
> создан релиз-узел **`release-round1017`** (alias **`release-b6c153f`**, commit
> **`b6c153f`**), фичи F1–F5 связаны (COMPLETED_IN/DEPLOYED_IN), обновлены
> ADR-1017-1/2/3, компоненты (`HEAD /web/ + /healthz routes`,
> `tool quality-menu flow (tdq:)`, `sleep badge countdown (fmtCountdown)`,
> `avatars log hygiene (web/api/avatars.py)`, `F5 brotli WONTFIX`),
> Risk-узлы (закрыты), `tech-debt-round10.17`, SpecDecision
> `ssh-rotation-cancelled round1017` (**CANCELLED**) и `metric-snapshot-round1017-final`;
> связь **SUPERSEDES** `ADR-1017-2` → `ADR-1016-1 Download contract` применена.
>
> **Деплой-верификация:** commit **`b6c153f`** (`fix(services,handlers,web,docs,plans):
> раунд 10.17 — ... (тесты 6007)`), push `772f192..b6c153f`, прод fast-forward
> `eb3fd4a..b6c153f`, `admin_bot` active PID **2016726**, лог без traceback.
> `/api/health` = **200**; `/healthz` GET+HEAD = **200** (no-store); `HEAD /web/` = **200**;
> `/api/memory/graph` = **401**; `/api/persona/health` = **401**. **DNS** A→198.46.175.136
> (AAAA пусто, TTL 50); **LE** notAfter 2026-11-28; Caddy `encode zstd gzip`
> (gzip подтверждён). **Миграций БД нет, `.env` не правился.**
>
> **Метрики:** pytest 5936 → **6007 passed / 0 failed** (**+71**); `node --check
> web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean;
> каталог **Δ=0** (435/406/411/90/88/19); БД без новых миграций (SQLite v9);
> APP_VERSION **2.57.0** без бампа. **@Reviewer:** итер.1 **Rejected** (3 Medium —
> overclaim ротации в ARCHITECTURE, транзиенты аватаров на 2 из 6 сайтов,
> дублирование меню качества) → итер.2 **APPROVED**. **@Scanner:** итер.1
> **0 C / 0 H / 1 Medium / 2 Low / 3 Info** (Medium `S10.17-1` docs — закрыт
> @Architect на Merge) → контракт по C/H пройден. **@Builder — 2 реворка.**
>
> **Ключевое:** tool-скачивание предлагает выбор качества (`probe → меню tdq: →
> callback`), падение исправлено, ADR-1016-1 помечен SUPERSEDE; бейджи Сна —
> «через {остаток}» / «до HH:MM» (эмодзи не тронуты); `HEAD /web/` + `/healthz`
> (диагностика DNS, no-store) + startup host-лог; политика логов аватаров (6 сайтов,
> транзиенты без трейса/кэша); brotli — WONTFIX; **ротация SSH — CANCELLED**.
>
> **Техдолг (открыт):** **Low `S10.17-2`** (бейдж «Сон через —»/«Глубокий сон через —»
> при `cognition==null` вместо «—»; функц. вреда нет) + **Info 3** (`S10.17-4`
> `log_download_env_once` parity, `S10.17-5` hot-флаг в callback `tdq:`, `S10.17-6`
> `/healthz` version) + **WONTFIX** brotli; ротация SSH — **CANCELLED**. Ручной
> Android-смоук — у владельца (инструкция в отчёте @DevOps). Архив:
> `plans/archive/*-round1017/` (**5 папок**), §38 ARCHITECTURE.md.

> **Step 10 (финал @Memory) раунда 10.16 «Download-Guide-MobileAudit» (14.09.2026):**
> эпик `Epic: Download-Guide-MobileAudit round1016` → **COMPLETED + DEPLOYED**;
> создан релиз-узел **`release-round1016`** (commit **`eb3fd4a`**), фичи/ADR связаны
> (COMPLETED_IN/DEPLOYED_IN/IMPLEMENTED_IN), обновлены `tech-debt-round10.16`,
> SpecDecision-компоненты (download contract, canon versioning/force-delivery,
> miniapp self-host/CSP, smoke suite, SSH rotation), `security scan round1016`,
> `help guide canon`, `tool_router download_media`, `DuckDNS + Caddy + Let's Encrypt`,
> 4 Risk-узла (закрыты) и `metric-snapshot-round1016-baseline` (финал).
>
> **Деплой-верификация:** commit **`eb3fd4a`** (`fix(services,handlers,web,docs,plans):
> раунд 10.16 — ... (тесты 5936)`), push `18a9aa1..eb3fd4a`, прод fast-forward
> `d01a539..eb3fd4a`, `admin_bot` active PID **1976836**. **Гайд доставлен в PG:**
> `canon_version=2`, `canon_delivered_version=2`, `canon_drift=False`, `prev_html`
> сохранён, `html_len==seed_len==4592`. `/api/health`=200, `/api/memory/graph`=401,
> `/api/persona/health`=401. **DNS** A→198.46.175.136 (AAAA нет), LE notAfter
> 2026-11-28; `/web/` GET 200 + CSP(`'unsafe-eval'`); Caddy: включено
> `encode zstd gzip` (backup) — сжатие появилось. SSH-ключ работает (парольный вход
> сохранён намеренно); live-скачивание видео — ручной шаг владельцу.
>
> **Метрики:** pytest 5774 → **5936 passed / 0 failed** (**+162**); `node --check`
> clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean; каталог **Δ=0**
> (435/406/411/90/88/19); БД без новых миграций (F2 — DML канона `canon_version`);
> APP_VERSION **2.57.0** без бампа. **@Reviewer:** итер.1 **Rejected** (Critical CSP
> `script-src 'self'` ломал Vue full build; High R17-логи URL, доставка гайда,
> README-overclaim) → итер.2 **APPROVED**. **@Scanner:** итер.1 0C/1H/1M/6L →
> итер.2 **0 C / 0 H / 0 M** (Low 1 — `S10.16-9`). **@Builder — 2 реворка.**
>
> **Техдолг (открыт):** **Low `S10.16-9`** (latent hardening — 4 raise-сайта
> `tools/video_downloader.py:767,772,899,904`; доступного лог-пути нет — утечки нет) +
> **WONTFIX** `S10.13-9`/`S10.13-11`/`R10.14-4` + **R17-долг** `current_task.md`
> (untracked; ротация — по желанию владельца). **@DevOps-заметки:** HEAD `/web/` 404
> (pre-existing FastAPI/StaticFiles), brotli-плагин Caddy, live-smoke скачивания.
> Архив: `plans/archive/*-round1016/` (**5 папок**), §37 ARCHITECTURE.md.

> **Step 0 (recon @Memory) раунда 10.16 «Download-Guide-MobileAudit» (14.09.2026):**
> ТЗ — `plans/current_task.md` секция «UPD2:» (строки 148-153). KG-узел
> `Epic: Download-Guide-MobileAudit round1016` + 4 Risk-узла. Статус —
> **RECON, Builder не начат**. Проверка репозитория: `plans/current_task.md` —
> **НЕ в git** (`git ls-files` пусто, `git log --all` пусто, `git rev-list --all
> --objects | grep current_task` = 0, `.gitignore:70`) → **пароль в истории git
> ОТСУТСТВУЕТ**; но он есть в рабочем файле (строки 63-65) → сменить/отозвать.
> **§1 (download):** два независимых дефекта — (a) tool-путь:
> `services/tool_router.py:592-594` всегда шлёт quality `"direct"` →
> `_normalize_quality('direct')` (`tools/video_downloader.py:695-705`) →
> `DownloadError("invalid quality")` для YouTube/платформ (проверено рантаймом;
> работает только для прямых `.mp4`); (b) ручной путь: `probe()` в
> `handlers/video_download.py:326-331` падает по окружению (cookies/proxy/POT/
> SABR-403) → «битая ссылка». **§2 (гайд):** `_migrate_info_how_it_works_v1015`
> (`services/config_cache.py:235-266`) осознанно **пропускает** перезапись, если
> прод-PG `content.info_how_it_works` != `PREV_DEFAULT_INFO_TEXT` (ручная правка);
> косвенно подтверждено дрейфом `info_text.md` при деплое 10.15 (tracked-файл
> как write-path `/edit_info`). **§4 (миниапп):** DuckDNS+Caddy+LE
> (`admin-bot.duckdns.org`), Android `ERR_NAME_NOT_RESOLVED` = DNS-резолв
> (duckdns-блокировка/протухшая запись/IPv6); ~1 мин — тяжёлый несобранный
> фронт (`index.html` ~235 КБ + `app.js` ~285 КБ) + CDN-Tailwind/telegram-web-app.
> **В силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать,
> русские conventional commits. Открытый техдолг 10.13-10.15 (см. ниже) — в
> скоупе §3 (полный аудит). Детали — KG + `plans/reports/*`.

> **Step 2/3 (Step 2 @Architect — синк Step 3 @Memory) 14.09.2026 (раунд 10.16
> «Download-Guide-MobileAudit»):** эпик `Epic: Download-Guide-MobileAudit round1016`
> — **ARCHITECTED / SPEC_READY, Builder не начат**. **5 фич F1–F5 / 41 задача
> T-1625…T-1665** (во всех 5 `plans/features/*-round1016/` — `spec.md` + `tasks.md`,
> 🟣 SPEC_READY) + **3 ADR**. Каталог-Δ = **0** (REGISTRY **435** / GROUPS **90** /
> Settings **406** / categorized **411** / mapped **88** / `TAB_RULES` **19**);
> **DDL нет** (единственная миграция — DML `info_how_it_works` в F2). Baseline:
> HEAD `18a9aa1`, pytest **5774/0**, APP_VERSION **2.57.0**, SQLite **v9**.
>
> **F1** `download-fix` (T-1625…1633, **P0**, **ADR-1016-1**): контракт
> `download(url, quality=None)` — `None`/`""`/`auto`/`best`/`max` → `max`,
> `"1080p"`/`1080` → `"1080"`, мусор → `invalid_quality` без сети; **`"direct"`
> больше не quality** (legacy-алиас → `max`); ветвление direct/платформа только по
> `is_direct_media_url` (без Content-Type/пробы); **R17-safe reason-коды**
> (`probe_timeout`/`probe_bot_check`/`cobalt_*`/…; в лог только `error=<Class>
> reason=<code>`, без URL); **env-preflight** `download_env_summary()` (presence
> cookies/proxy/pot/cobalt); **bounded probe-fallback** `_download_without_menu`
> (probe-fail не жжёт кулдаун).
> **F2** `guide-delivery` (T-1634…1641, **P1**, **ADR-1016-3**): **владелец
> РАЗРЕШИЛ ПРИНУДИТЕЛЬНО перезаписать** текущий текст гайда в PG
> (`content.info_how_it_works`) новым каноном из ТЗ (ценных ручных правок нет);
> вводится **`canon_version`** + `KNOWN_INFO_SNAPSHOTS` + `normalize_canon`
> (нормализованное сравнение, unknown-текст не затирается молча → `canon_drift`);
> **force-reset** `POST /api/info/reset-canon` (RBAC `edit_info`, бэкап
> `prev_html`, аудит `updated_by` = id); **`save_text` PG-only**, `info_text.md` —
> read-only сид/байт-канон → pull не блокируется; кнопка/команда `reset-canon`.
> **F3** `audit-recent-epics` (T-1642…1650, **P1**, →F1/F2): **in-process
> смоук-тесты** (pytest + моки PG/yt-dlp/cobalt/LLM, без сети/секретов) по 7
> подсистемам (download/probe, tool-loop, guide, graph, sleep, nostalgia, persona);
> **FIX** S10.13-6b/-13, R10.15-4/-10/-11; **WONTFIX+док** S10.13-9/-11, R10.14-4;
> отчёт `plans/reports/round10.16_audit.md`.
> **F4** `miniapp-mobile` (T-1651…1659, **P1**, **ADR-1016-2**, независима,
> параллельно F3): **владелец утвердил self-host ВСЕХ зависимостей** (Vue 3,
> Chart.js 4, Telegram WebApp SDK, **Tailwind → предсобранный CSS** build-time CLI +
> safelist), строгий **CSP** (`script-src 'self'`, без inline), убрать внешние CDN;
> `<style>` → `app.css`, сжатие Caddy (вне репо); DNS/Caddy — **@DevOps**.
> **F5** `security-rotation-finalize` (T-1660…1665, **P0**, →F1–F4, последняя):
> ротация/отзыв SSH-пароля (`plans/current_task.md` — **НЕ в git**, подтверждено),
> переход на SSH-ключи, README/R17; ротация может идти параллельно.
>
> **Порядок:** F1 → F2 → F3 → {F4 ∥ F3} → F5; **F1 и F2 независимы** (зависимости
> `F1→F2` **НЕТ**). **В силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env`
> не трогать, каталог-Δ только санкционированно, русские conventional commits.
> **Граф синхронизирован (Step 3):** созданы 5 Feature + 5 SpecDecision
> (`download contract quality fix`, `guide canon versioning + force overwrite`,
> `miniapp self-host (Vue/Chart.js/Tailwind/Telegram SDK)`, `in-process smoke suite`,
> `SSH password rotation`) + `CSP script-src 'self' (round1016)` +
> `DuckDNS + Caddy + Let's Encrypt` + `tech-debt-round10.16` +
> `metric-snapshot-round1016-baseline` + `tool_router download_media`; обновлены
> 4 Risk-узла (статусы), 3 ADR, `tech-debt-round10.15`, `help guide canon`;
> связи CONTAINS/PART_OF/DEPENDS_ON (F3→F1/F2; F5→F1–F4), IMPLEMENTS, HAS_ADR,
> ADDRESSES, REQUIRES, CONSTRAINED_BY, SUPERSEDES.

> **Step 2/3 (Step 2 @Architect, итерация 2 — синк Step 3 @Memory) 14.09.2026
> (раунд 10.15 «Багфиксы Графа памяти, Воркера Сна и Ностальгии»):**
> ТЗ — `plans/current_task.md` §1–§7 + UPD владельца; эпик
> `Epic: Memory-Graph-Sleep-Nostalgia bugfixes round1015` — **ARCHITECTED /
> SPEC_READY, Builder не начат**. Владелец **отменил рубильник
> `flags.command_prefix_enabled`** (UPD §1) — **каталог-Δ = 0** (REGISTRY **435** /
> Settings **406** / categorized **411** / GROUPS **90** / mapped **88** /
> TAB_RULES **19**; прежний черновик итерации 1 с +1 ключом и 436/407/412
> **отменён**). Триггер системы = **непустое `active_persona.name`**: имя задано →
> префикс «<Имя>, » (+ эвристические склонения при len≥3), дефолтные ботворды
> `бот`/`ботик`/`ботяра` **отключаются**; имя пусто → «Бот, » и дефолты активны.
> Также **утверждена оконная семантика бейджей Сна** (UPD §3):
> `active = in_window OR running`, `active_until` = конец окна, вне окна — начало
> следующего; свечение `.glow` только в активной фазе.
>
> **9 фич / 76 задач T-1549…T-1624 (во всех 9 `plans/features/*-round1015/` —
> `spec.md` + `tasks.md`, 🟣 SPEC_READY):**
> **F1** `graph-sampling-centrality` (T-1549…1557, ADR-1015-2) — degree centrality,
> сиды топ-50 + окрестность + очистка сирот, финальный cap 120/240, закрывает
> S10.13-14; **F2** `graph-frontend-physics-search` (T-1558…1565, →F1) — barnesHut +
> «Поиск по графу»; **F3** `sleep-unblock-diagnostics` (T-1566…1574) — fallback
> порогов 2/8 за 3 дня без `distilled` (self-healing) + пре-гейт-лог `[Sleep]` на
> WARNING; **F4** `nostalgia-prompt-revamp` (T-1575…1583) — окно ±10, инжект
> Лора/мемов, перепись канона (ADR-1013-3); **F5** `status-graph-ui-relocation`
> (T-1584…1592, →F2/F3) — релокация статистики графа в Сводку + бейджи; **F6**
> `command-prefix-persona-routing` (T-1593…1602, ADR-1015-1) — реестр **17
> триггеров** (search 3 / youtube 4 / web 4 / checkup 3 / download 3) +
> bare-исключения `чекап`/`фактчек`; новые модули `services/command_registry.py`,
> `services/command_prefix.py`; порядок роутеров `bot.py` **НЕ меняется**
> (direct_chat yield → download 4e); сняты legacy-алиасы (F6-U1); **F7**
> `guide-rewrite-persona` (T-1603…1609, →F6) — перепись гайда под реестр/имя +
> идемпотентная DML-миграция `PREV_DEFAULT_INFO_TEXT`; **F8** `hybrid-tool-calling`
> (T-1610…1618, ADR-1015-3, →F6/F9) — JSON-Schema tools для основной LLM, tool-сет
> **7** (`query_chat_memory`/`dig_into_lore`/`execute_web_search`/`summarize_video`/
> `download_media`/`get_bot_health`/`get_recent_history`), Fast-Track приоритетен;
> корнер-кейс скачивания = фиктивный `tool_response {status:success}` при реальной
> отправке MP4 (сбой → честный `error`); **F9** `recent-history-tool`
> (T-1619…1624, →F8) — `get_recent_history` (depth≤150 ИЛИ query, стенограмма
> «Имя: текст», переиспользует `database.get_recent_messages`, DDL не нужен).
>
> **Порядок внедрения:** F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 (F8∥F9).
> **DDL не требуется** по всему раунду (read-only/UI/код-константы); единственная
> миграция — DML `info_how_it_works` (F7). **Остаётся в силе:** R16, R17, порядок
> роутеров `bot.py` (только DI-kwargs), `media/` и `.env` не трогать, каталог-Δ
> только санкционированно, русские conventional commits. **Граф синхронизирован
> (Step 3):** эпик + 9 Feature-узлов; 3 ADR (`round1015-command-prefix-policy`
> ADR-1015-1, `ADR-1015-2 graph sampling`, `round1015-hybrid-tool-calling-ADR-1015-3`);
> модули `services/command_registry.py`/`services/command_prefix.py`; механизмы
> `hybrid-tool-calling`/`graph centrality top-50`/`sleep threshold fallback`/
> `nostalgia lore/memes inject`/`status layout relocation`/`guide rewrite`; tool
> `get_recent_history`; связи PART_OF/DEPENDS_ON (F2→F1; F5→F2/F3; F8→F6/F9;
> F9→F8; F7→F6/F8/F9).

> **Синк STEP 10 (финал) раунда 10.15 «Багфиксы Графа памяти, Воркера Сна и
> Ностальгии + Гибридный Tool Calling» (14.09.2026):** эпик
> `Epic: Memory-Graph-Sleep-Nostalgia bugfixes round1015` — **COMPLETED +
> DEPLOYED**, 9 фич F1–F9, **76 задач T-1549…T-1624** — все закрыты;
> спеки+ADR заархивированы в `plans/archive/*-round1015/` (**9 папок**;
> `plans/archive/` — **59 папок**; `plans/features/` — 6 активных F-1…F-6).
> **Коммит:** `d01a539` (`feat(services,web,api,docs,plans): раунд 10.15 — умная
> выборка графа, диагностика Сна, ревамп ностальгии, префиксы команд и Persona,
> гибридный tool calling (тесты 5774)`); push origin/master `798e044..d01a539`.
> **APP_VERSION остался 2.57.0** (без бампа; README и код согласованы, тесты 5774).
> **Деплой-верификация:** прод `nik@198.46.175.136:/var/www/admin_bot`,
> fast-forward `eb2a232..d01a539`; ⚠️ инцидент серверного дрейфа `info_text.md`
> (fast-forward заблокирован) — разрешён вручную: backup + `git stash` → pull →
> `systemd admin_bot` **active (running) PID 1860445**; `/api/health` = **200**,
> `/api/memory/graph` = **401**, `/api/memory/stats` = **401** (не 500).
> **Миграций БД НЕТ** (SQLite остаётся **v9**; PG без изменений); `.env` не
> редактировался. **Метрики:** pytest **5589 → 5774 passed / 0 failed** (Δ **+185**;
> итер.1 @Scanner — 5761); `node --check web/app.js` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
> Каталог **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 /
> mapped 88 / `TAB_RULES` 19).
> **Ревью/аудит:** @Reviewer итерация 1 = **Rejected** (H1 F5 — `enabled=false`
> не гасил бейдж Сна; M1 F6 — нет правой границы слова у триггеров; M2 F6 —
> безусловный yield терял сообщение при выключенном модуле); итерация 2 =
> **APPROVED**. @Scanner итерация 1 = **0 C / 0 H / 3 M / 6 L**; итерация 2 =
> **0 C / 0 H / 0 M** (Low 3, Info 3). Закрыты R10.15-1/-2/-3/-5/-6/-7/-8/-9;
> остались R10.15-4 (deferred), R10.15-10, R10.15-11. @Builder — **2 цикла
> реворков**.
> **Архитектура:** `plans/ARCHITECTURE.md` **§36** «Карта раунда 10.15» +
> **ADR-1015-1** (command prefix policy), **ADR-1015-2** (graph sampling),
> **ADR-1015-3** (tool calling).
> **Ключевые решения:** команды требуют обращения; префикс = непустое имя
> персоны («из коробки», БЕЗ флага), иначе «Бот, »; реестр 17 команд + bare
> `чекап`/`фактчек`; гибридный tool-calling (7 JSON-Schema инструментов,
> корнер-кейс скачивания через `services/media_send.py`); `get_recent_history`
> (depth≤150/query); граф — Degree Centrality топ-50 + соседи + сироты (закрыт
> **S10.13-14**); сон — fallback 2/8 + лог `[Sleep]` WARNING; ностальгия ±10 +
> лор/мемы; бейджи оконной семантики. **Граф обновлён (Step 10):** эпик/милстоун
> → **COMPLETED+DEPLOYED**, созданы `release-round1015`, `tech-debt-round10.15`,
> `metric-snapshot-round1015-final`, `services/media_send.py`,
> `help guide canon (info_how_it_works)`; 9 фич → `DEPLOYED_IN release-round1015`
> + `ARCHIVED_IN plans-structure`; релиз `release-round1015 FOLLOWS release-round1014`.

> **Step 0 recon 13.09.2026 (раунд 10.14 — «Самосознание и Личность бота»,
> plans/current_task.md пп.1–7):** HEAD == origin/master == `2edc65b` (docs-финал
> 10.13), дерево ЧИСТОЕ, APP_VERSION 2.57.0, pytest **5392/0**, каталог
> **427/90/399/403** (TAB_RULES 19), SQLite v8. Эпик записан в KG —
> `Epic: Self-Awareness-Persona Refactor round1014` + милстоун
> `round1014-epic-self-awareness` (+ `round1014-persona-storage-ddl-free`,
> `risk-bot-self-echo-round1014`, `metric-snapshot-round1014-baseline`).
> §1 anti-echo: свои ответы УЖЕ хранятся как `graph_facts.origin='bot_direct_reply'`
> (query+answer) с весом 0.7 и идут в RAG+сон (`_DREAM_SOURCE_ORIGINS`); новый
> origin запрещён CHECK'ом SQLite (DDL-free маркировка — `status`/`belief_meta`).
> §2 Persona — greenfield (таблицы/полей `is_global`/`is_aware_ai`/`dynamic_traits`
> нет); «Досье» 10.13 = карточка ПОЛЬЗОВАТЕЛЯ, не бот. §3/§3.1/§7 — точки изменения
> найдены (hub «ИИ» 7 карточек, `_ribbonLoop` 2 ленты, порядок Статуса). §4 —
> global-save уже в 10.12 (R10.12-1 закрыт), нужен end-to-end аудит (связан с
> активной F-5 `config-read-path-audit`). §5/§6 — гайд и «Справка» существуют,
> нужен доп. редактируемый блок. ⚠️ Главный конфликт — **новая схема Persona vs
> инвариант «ноль новых PG-DDL»**: PG-таблицы живут в `services/pg_db.py`
> (идемпотентный DDL при старте); DDL-free путь — `bot_settings`/
> `chat_params.overrides`/каталог. Открытый техдолг: 5 Low `S10.13-*` +
> R10.11-4/R10.12-2..4/R10.3-1..2/R10.9-4. Дальше — Step 1 @PM (5–7 фич),
> Step 2 @Architect (решение Persona storage).
>
> ⚠️ **ЧАСТЬ ЭТОГО РЕКОНА УСТАРЕЛА (UPD 13.09.2026, см. блок «Step 2/3 (итерация 2)» ниже):**
> DDL-free-путь Persona (`bot_settings`/`chat_params.overrides`) и тезис «новый origin запрещён
> CHECK'ом SQLite» — **ОТМЕНЕНЫ ВЛАДЕЛЬЦЕМ**; инвариант «ноль PG-DDL» и «SQLite v8 / origin CHECK
> заморожен» **СНЯТЫ**. Актуальные цифры — 8 фич, T-1477…T-1548, каталог 435/406/411, SQLite v9.

> **Step 2/3 (итерация 2) 13.09.2026 (раунд 10.14 — ПЕРЕРАБОТКА под UPD владельца):**
> Владелец **РАЗРЕШИЛ** менять структуру БД и писать миграции (PG + SQLite) — прежние инварианты
> «ноль новых PG-DDL» (10.4–10.13) и «SQLite остаётся v8 / `graph_facts.origin` CHECK заморожен»
> **СНЯТЫ**; DDL-free-решения Шага 2 (Persona в `bot_settings`/`chat_params.overrides`, self-маркер
> через `status='self_reply'`, rule-based экстрактор) **ОТМЕНЕНЫ** владельцем («не лепим заплатки»;
> «делай базу логичной»; «вырезание сути регулярками убьёт контекст»). Политика —
> `plans/project.md` §«Политика DDL (обновлено раундом 10.14)»; KG-узел `DDL allowed (10.14)`
> (прежний узел `round1014-persona-storage-ddl-free` удалён).
>
> **Итог Шага 2: 8 фич F1–F8, задачи T-1477…T-1548 (72), 8 `spec.md` + 2 ADR, все SPEC_READY/ACCEPTED**
> (Step 1 @PM дал 7 фич/64 задачи — добавлена **F8** по UPD п.3); статус эпика — **ARCHITECTED**
> (Builder не начат). Каталог-Δ (санкционирован): **REGISTRY 427→435, Settings 399→406,
> categorized 403→411; GROUPS 90 / mapped 88 / TAB_RULES 19 — без изменений** (прежний черновик
> 436/92/20 отменён — вкладка «Личность» = special-screen, не `TABS`).
>
> **F1 `anti-echo-self-reply` (T-1477…1486):** origin `bot_self_reply` (11-й) + rebuild `graph_facts` +
> **SQLite v8→v9** (`_migrate_self_origin_v9`; копируются все 16 колонок, `id` 1:1 ⇒ FTS/vec валидны;
> обратимость — обратный `UPDATE origin` перед revert); вес `limits.graph_fact_weight_bot`=0.2,
> важность 2; экстрактор — **только LLM** (`services/self_reflection.py`, prompt-константа, fail-open);
> анти-эхо-инструкция `_SELF_ECHO_INSTRUCTION`; карантин self из Сна/золотых/компакции/
> `graph_stats.facts`; `persona_state` (PG singleton); флаг `flags.bot_self_awareness_enabled`=**True**.
> ADR-1014-2.
> **F2 `persona-storage-core` (T-1487…1497):** **PG `personas`** (id, chat_id NULL, is_global, name,
> biography, system_prompt_overrides, is_aware_ai, created_at, updated_at; CHECK скоупа, 2 partial
> UNIQUE, FK `chat_id`→`chat_profiles` ON DELETE CASCADE) + **`persona_traits`** (id, chat_id, trait,
> source, created_at); `services/bot_persona.py` (scope per-chat→global→empty, промпт-блок `<Persona>`,
> `_NO_AI_DISCLOSURE_BLOCK`); traits пишет DeepSleepWorker; API `GET/PUT/DELETE /api/persona` +
> `GET /api/persona/health`; флаг `flags.persona_enabled`=**True**. ADR-1014-1.
> **F3 `persona-ui-tab` (T-1498…1504):** special-screen `#/ai/persona` (карточка «Личность» в Hub «ИИ»),
> форма 3 поля + чекбокс «Осознаёт себя ИИ», scope-сброс; Δ каталога = 0.
> **F4 `persona-traits-ribbon` (T-1505…1510):** 3-я лента «Эволюция характера» (`_ribbonLoop`, сетка
> 3→1) + панель **метрик Личности в «Сводке»** (`#/oversight`: кол-во `dynamic_traits`, время
> последнего пересмотра, статус экстрактора; источник `GET /api/persona/health`).
> **F5 `settings-persistence-audit` (T-1511…1525):** write-path/scope/restart-аудит ВСЕХ параметров +
> dedicated-API раунда; закрывает R10.9-4 (health-кэш); границы с активной F-5
> `config-read-path-audit` (read-path — у неё, не дублировать).
> **F6 `help-guide-integration` (T-1526…1534):** гайд в БД (**PG `content.intelligence_guide`**, json) +
> второй редактируемый блок в «Справке» (Markdown-редактор + DOMPurify 3.4.15 self-host, preview,
> save); идемпотентный сид из `plans/docs/intelligence_user_guide.md` (ручные правки не
> перезатираются); API `GET/POST /api/info/guide`.
> **F7 `status-layout-reorder` (T-1535…1540):** порядок Статуса Сводка → **Сердцебиение** → Бот →
> Сервер → **Мониторинг Интеллекта** → Доступность ключей → История; Δ=0, правок `app.js` нет.
> **F8 `self-reflection-llm-provider` (T-1541…1548):** роль `reflection` → slug **`intel_reflection`**
> (`generate_worker`), 4 PG-ключа (models/keys), probe `intel_reflection_main`, третий parent-блок
> «LLM для саморефлексии (Экстрактор сути)»; пусто/ошибка → основная модель (fail-open). Паттерн
> ADR-1013-1.
>
> **Порядок внедрения:** F1 → F2 → {F3, F4} → {F5 ∥} → F6 → F7 (F8 самодостаточна, потребляется F1).
> **Остаются в силе:** R17, R16, порядок роутеров `bot.py` (DI-kwargs), `media/` и `.env` не трогать,
> каталог-Δ только санкционированно + пин-тесты, русские conventional commits. Риски:
> `risk-round1014-v9-migration-rebuild`, `risk-round1014-index-html-merge-conflicts`, self-эхо.
> **Граф синхронизирован (Step 3):** 8 Feature + 14 компонентов + ADR-1014-1/2 + `UPD owner decisions`
> + `DDL allowed (10.14)` + риски/техдолг/внешняя-зависимость/снимок метрик; узел
> `round1014-persona-storage-ddl-free` удалён.

> **Синк STEP 10 (финал) раунда 10.14 «Самосознание и Личность бота» (13.09.2026):**
> эпик **COMPLETED + DEPLOYED**, 8 фич F1–F8, **72 задачи T-1477…T-1548** — все `[x]`.
> **Коммит:** `eb2a232` (`feat(services,web,api,docs,plans): раунд 10.14 — самосознание и
> личность бота, PG Persona и SQLite v9, LLM-экстрактор, метрики Сводки, редактор Справки
> (тесты 5589)`); push origin/master `2edc65b..eb2a232`. HEAD == origin/master == `eb2a232`,
> дерево ЧИСТОЕ. **APP_VERSION НЕ бампился** (остался **2.57.0**; отдельный релиз v2.58.0 не
> выставлялся — см. KG `release-round1014`).
> **Миграции реализованы** (инварианты «ноль PG-DDL»/«SQLite v8» сняты владельцем):
> SQLite **v8→v9** (rebuild `graph_facts`, новый origin `bot_self_reply`), PG
> **`personas`/`persona_traits`/`persona_state`** (идемпотентный DDL). На проде после
> рестарта: `PRAGMA user_version=9`, PG-таблицы на месте.
> **Деплой-верификация:** прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward
> `8800bba..eb2a232`; `systemd admin_bot` **active (running) PID 1774527**; `/api/health` =
> **200**, `/api/persona/health` = **401** (не 500); `.env` не редактировался (дефолты
> безопасны, флаги ON в коде); пул `flags.persona_enabled`/`flags.bot_self_awareness_enabled`
> = **ON** по умолчанию (требование владельца).
> **Метрики:** pytest **5392 → 5589 passed / 0 failed** (Δ **+197**); `node --check web/app.js`
> clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean. Каталог
> **427/399/403 → 435/406/411** (REGISTRY/Settings/categorized); **GROUPS 90 / mapped 88 /
> TAB_RULES 19** — без изменений.
> **Ревью/аудит:** @Reviewer итерация 1 = **Rejected** (H1 persona optimistic-409 недостижим
> — `updated_at` не отдавался; H2 RBAC `edit_persona` не выдаётся; H3 per-chat флаги читались
> только глобально `hot.get`), итерация 2 = **APPROVED**. @Scanner итерация 1 =
> **0 C / 0 H / 2 M / 5 L**, итерация 2 = **0 C / 0 H / 0 M** (Low 2, Info 2); закрыты
> R10.14-1 (RBAC view/edit `edit_persona`) и R10.14-2 (traits-LLM вне `worker_budget`).
> @Builder — **2 цикла реворков**.
> **Архитектура:** `plans/ARCHITECTURE.md` **§35** «Карта раунда 10.14» + **ADR-1014-1**
> (PG Persona: `personas`/`persona_traits`/`persona_state`) + **ADR-1014-2** (origin
> `bot_self_reply` + SQLite v9 + LLM-экстрактор). Спеки+ADR заархивированы в
> `plans/archive/*-round1014/` (**8 папок**; `plans/archive/` — **50 папок**;
> `plans/features/` — снова 6 активных F-1…F-6).
> **Техдолг (открыт, не блокеры):** Low `R10.14-4` (traits без `chat_id` — осознанно по F4),
> `R10.14-7` (aiosqlite-leak, pre-existing), `L5` (@Reviewer: hot-path — 2 доп. PG-запроса +
> запись `persona_state` на каждый direct-ответ, кэша нет); Info `I10.14-1` (каскад v7→v9 не
> покрыт юнит-тестами), `I10.14-2` (FIFO-ротация traits глобальная). KG — `tech-debt-round10.14`.
> **Примечание:** `betterstack_handler WARNING 401` (внешний `LOGTAIL_SOURCE_TOKEN`) —
> pre-existing, вне раунда. Граф обновлён (Step 10): эпик/милстоун → **COMPLETED+DEPLOYED**,
> созданы `release-round1014` и `metric-snapshot-round1014-final`, 8 фич →
> `COMPLETED_IN`/`DEPLOYED_IN`/`ARCHIVED_IN plans-structure`, `DDL allowed (10.14)` →
> РЕАЛИЗОВАНО.

> Создан заново 07.09.2026 (pre-планирование эпоса «Multi-chat scaling +
> Granular RBAC + BYOK + PERMsoc-плагин + TMA-навигация»). Прежние plans/
> файлы удалены 03.09.2026. Синк STEP 3 выполнен 07.09.2026 (HEAD fac1b9f):
> раунд 10 распланирован — 6 фич F-7…F-12, T-843…T-924, spec.md @Architect,
> tasks.md @PM, статус «запланирован»; граф обновлён (entity feature-*).
> **Синк STEP 9 (финал) выполнен 08.09.2026 (HEAD fac1b9f): раунд 10
> ЗАВЕРШЁН и заархивирован** — 4717 passed / 0 failed (подтверждён прогоном,
> 54.46s), аппрув @Reviewer, архив 15 папок, ARCHITECTURE.md §22, DevOps
> runbook готов; БЕЗ коммита (worktree dirty); граф обновлён
> (feature-* → archived + round10-epic + ARCHIVED_IN).
> **Синк STEP 9 (финал, post-commit) 08.09.2026: раунд 10 закоммичен и
> задеплоен** — HEAD == origin/master == `533bf13` (69be94e + 533bf13),
> прод обновлён (PID 133710, DDL ok, бэкфилы done); граф обновлён
> (round10-epic → completed+deployed, AdminBot → DEPLOYED).
> **Step 0 recon 08.09.2026 (post-deploy баг-репорт TMA):** 4 группы
> багов найдены в коде, подробные координаты — KG-сущность
> `recon: tma-round10-postdeploy-bugs` + `bug: tma-*` (4 шт). Кратко:
> (1) конфиг-вкладки Промпты/Лимиты/LLM Провайдеры/Память и RAG/Реакции
> и Триггеры пустые — `web/index.html:436,538,542` вызывают НЕСУЩЕСТВУЮЩИЕ
> `basicItems(grp)`/`advancedItems(grp)` (в `web/app.js` только
> неиспользуемый `itemAdvanced` :1168) → TypeError при рендере;
> (2) логи — сервер отдаёт newest-first (`services/log_ring.py:153`), но
> `loadLogs` автоскроллит ВНИЗ (`app.js:1700-1704`) → старые видны внизу;
> per-line «Скопировать» (index.html:1586), невидимое поле = textarea-
> фолбек `copyText` (app.js:1742-1748); (3) relations — обогащение
> username/photo_file_id только топ-30 (`web/api/chat_lore.py:562-568`),
> имена каскадом names-map(30д/200)→aliases(флаг summary_enabled)→uid
> (user_relations.py:346-349, bot.py:570-571), панель ограничена только lg
> (index.html:1122-1123); (4) modules_feats — placeholder «Выберите чат в
> шапке» при `activeChatId==null` (index.html:748-750), карточки в v-else
> (751-869), `loadGateInfo` early-return (app.js:780-784). Тесты — только
> маркерные, баги не ловят. Отдано @Builder (RESEARCH ONLY, без правок).
> **Синк STEP 9 (финал, хотфикс 10.1) 08.09.2026:** раунд 10.1 ЗАВЕРШЁН и
> ЗАДЕПЛОЕН — HEAD == origin/master == `8eae899` (поверх 533bf13), 4 группы
> багов рекона закрыты (review PASS), тесты 4726, README «Хотфикс 10.1 —
> бот взял себя в руки»; прод 198.46.175.136: PID 159455 (active, since
> 2026-09-07 16:27:04 UTC), journal чист; граф обновлён (милстоун
> `round10.1-hotfix` → COMPLETED+DEPLOYED, FIXES tma-frontend,
> RESOLVES recon, AdminBot → COMPLETED). Новых follow-up нет.
> **Step 0 recon 09.09.2026 (пост-10.1 баг-репорт TMA, 7 багов):** RESEARCH
> ONLY, 7 багов из ультиматума юзера (bug 8 — место на диске сервера,
> DevOps, вне кода). Подробные координаты — KG `recon: tma-bugs-7-post-10.1`
> + `bug: tma-*` (7 шт). Кратко: (1) селектор чата скрыт — `index.html:389`
> `accessChats.length > 1` для global admin (+вторично PG-down → пустой
> `/api/access/chats`); (2) сайдбар без `overflow-y` (index.html:347/328-340);
> (3) нет вкладки «Функции PERMsoc» — параметры разбросаны по
> reactions_persons/reactions_mimic/reactions_word_reactions/limits_mimic/
> flags_media, TAB_RULES (param_catalog.py:1359) «группа → ровно 1 вкладка»;
> (4) аватары только инициалы (топ-50 + негатив-кэш 1ч, chat_lore.py:574-580,
> avatars.py:113-136, app.js:536-550), имена = грязный author_name БЕЗ
> санитизации (_participant_names chat_lore.py:602-616); (5) аккордеон
> `(0)` — details.advanced рендерится всегда (index.html:559-567);
> (6) модалка прав — 2 select min-ролей + checkbox (index.html:1914-1952,
> access.py:129-143 дефолт view=user); (7) «невидимое поле» — off-screen
> textarea-фолбек copyText (app.js:1792-1816), CSS-класса нет (инлайн-стили).
> Тесты: маркерные test_webapp_* (nav_disclosure/rbac/avatars/tma_fixes),
> test_frontend_tab_mapping, test_access.py, test_relations_service.py —
> баги НЕ ловят, часть фиксирует текущее поведение и потребует обновления.
> Отдано @Builder (без правок).
> **Синк STEP 9 (финал) 09.09.2026 (раунд 10.2):** фиксы рекона
> `recon: tma-bugs-7-post-10.1` РЕАЛИЗОВАНЫ и УТВЕРЖДЕНЫ (@Reviewer PASS,
> минор B-1 TABS-зеркало закрыт), 4759 passed / 0 failed (прогон в .venv,
> 64.00s), НО НЕ ЗАКОММИЧЕНЫ — 26 файлов modified + untracked plans/MEMORY.md,
> HEAD == 8eae899; коммит/деплой ожидают решения юзера. Граф обновлён:
> милстоун `round10.2-fixes` (IMPLEMENTED + PENDING_COMMIT, RESOLVES recon,
> FIXES 7 bug: tma-*). Диск сервера уже исправлен DevOps (см. раздел ниже).
> **Синк STEP 9 (финал, post-commit) 09.09.2026: раунд 10.2 ЗАКОММИЧЕН и
> ЗАДЕПЛОЕН** — HEAD == origin/master == `d30b203` (поверх 8eae899,
> 28 файлов, +1576/−314), тесты 4760 passed / 0 failed, @Reviewer APPROVED
> (имена as-is: ID никогда не имя; каскад alias→nickname raw→username(без @)→'';
> avatarInitial графема); прод 198.46.175.136: PID 454654, DDL ok, polling,
> webapp 200 «Функции PERMsoc», без Traceback, .env без изменений; README
> обновлён; граф обновлён (милстоун `round10.2-fixes` → COMPLETED+DEPLOYED,
> AdminBot → DEPLOYED, создан `server-hardening-102` → DEPLOYED).
> **Безопасность сервера (DevOps, 09.09.2026) — fail2ban/ufw/SSH-харденинг
> АКТИВНЫ** (см. раздел «Безопасность сервера» ниже); follow-up: миграция
> на SSH-ключи (решение владельца), ignoreip для статического IP, CrowdSec
> альтернатива, migrate_history 1.1G перенос.
> **Step 0 recon 09.09.2026 (раунд 10.3, 7 задач ТЗ юзера):** HEAD ==
> origin/master == `d30b203` (10.2 закоммичен+задеплоен, PID 454654),
> ветка master, дерево ЧИСТОЕ (untracked: plans/MEMORY.md + plans/reports/
> только). 7 задач ТЗ → раунд 10.3: F-13 `tma-chat-selector-fixes`
> (задачи 1,2,3,6 = AC-1/AC-2/AC-3/AC-5) + F-14 `dm-user-settings`
> (задача 4 = AC-4), милстоун `round10.3-epic` — статус **ARCHITECTED**
> (T-925…T-964, PM+Arch done, Builder не начат). ⚠️ (коррекция ниже —
> файлы уже НЕ пустые). Задачи 5 (sandbox reason=budget) и 7
> (graphrag JSON list) — НОВЫЕ бэкенд-реконы (KG: `recon:
> direct-chat-sandbox-budget` + `recon: graphrag-memorize-json-list`);
> на Step 0 были «вне планирования», но далее включены в F-15 (см. ниже).
> **Синк STEP 3 (планирование 10.3) 09.09.2026:** раунд 10.3 перепланирован —
> **3 фичи**: F-13 `tma-chat-selector-fixes` (T-925…T-944; tasks.md пересоздан по
> KG-канону, файл был утрачен), F-14 `dm-user-settings` (T-945…T-964; tasks.md
> пересоздан по KG-канону), **F-15 НОВАЯ** `direct-sandbox-budget-investigation`
> (T-965…T-973; задачи 5 и 7 ТЗ — sandbox reason=budget + graphrag JSON list;
> прод-диагностика T-965/T-966 ДО фикса). spec.md для всех трёх фич — @Architect
> (F-13/F-14 — пересоздание по KG-наблюдениям, F-15 — создание). Статус милстоуна
> `round10.3-epic` → ARCHITECTED (F-13/F-14/F-15, всё spec.md+tasks.md на диске:
> пересозданы/созданы 09.09.2026 — наблюдение Step 0 «файлы отсутствуют»
> УСТАРЕЛО; F-15: прод-диагностика T-965/T-966 (TODO) ДО фикса, Builder не начат);
> конфликт-матрица с F-1/F-3/F-4/F-5 зарегистрирована в plans/backlog.md
> (раунд 10.3); аудит Scanner (plans/reports/full_audit_results.md) учтён
> (HIGH-004/MED-015/017/019/021/022 → задачи фич; остальное — кандидат в отдельный
> техдолг-эпик). Граф обновлён (Step 3): AdminBot HAS_PLAN → F-13/F-14/F-15,
> F-14 DEPENDS_ON F-13 (+F-1 post-deploy-admin-minors, RELATED_TO F-3 scam-followup),
> F-13 CONFLICTS_WITH F-4 frontend-admin-bugfixes (Баг-4, общий рендер :551-552),
> F-15 RELATED_TO DirectChatService/summary-subsystem, PART_OF round10.3-epic.
>
> **Merge Phase 10.3 (10.09.2026, @Architect)** — F-13/F-14/F-15 IMPLEMENTED в рабочем
> дереве (HEAD d30b203 + 10.3, 27 файлов), @Reviewer APPROVED, Scanner-аудит 10.3:
> **0 blocker/major** (minor/info R10.3-1…R10.3-6 → ARCHITECTURE.md §24), pytest
> **4831 passed / 0 failed**, `node --check web/app.js` clean. ARCHITECTURE.md обновлён:
> §23 (раунд 10.3: DM-скоуп и настройки ЛС /F-14, единый селектор чатов + z-index /F-13,
> sandbox-budget + memorize-JSON /F-15) + §24 «Известные ограничения и техдолг»
> (R10.3-1…R10.3-6 + ссылка на остаток полного аудита); кросс-указатели §3/§4/§5/§9/§16.
> Локальные спеки F-13/F-14/F-15 НЕ тронуты (архивная фаза — @PM); коммит/деплой
> (T-972/T-973) — финальный шаг раунда. **Финальный синк KG/графа, статусов милстоуна
> `round10.3-epic` и архивирование — шаг 10 @Memory.**
> **Синк STEP 10 (финал) 10.09.2026: раунд 10.3 ПОЛНОСТЬЮ ЗАВЕРШЁН** — HEAD ==
> origin/master == `1410a68` (коммит 09.09.2026 12:33 UTC, автор Henry), тесты
> **4831 passed / 0 failed**, @Reviewer APPROVED, Scanner 0 blocker/major
> (R10.3-1…R10.3-6 → ARCH §24); деплой 09.09.2026 (рестарт 12:37 UTC, active);
> прод-диагностика задачи 5 проведена (чат -1002661910336 без своего ключа,
> глобальный ключ 25/25 → sandbox R16, сброс бакета 00:00 Екб — детали в KG
> `recon: direct-chat-sandbox-budget`); F-13/F-14/F-15 заархивированы
> (plans/archive/ — **18 папок**, plans/features/ — снова 6 активных F-1…F-6);
> MEMORY.md ВПЕРВЫЕ вошёл в коммит; граф обновлён (милстоун `round10.3-epic` →
> COMPLETED+DEPLOYED, фичи → ARCHIVED_IN/WAS_PART_OF). Цикл раунда полностью закрыт.
> **Step 0 recon 10.09.2026 (раунд 10.4, 9 пунктов ТЗ реструктуризации TMA):**
> RESEARCH ONLY — дерево чистое (только plans/MEMORY.md modified, остаток шага 10),
> HEAD == origin/master == `1410a68`. Изучены структура миниаппа (TABS/MENU_ORDER/
> generic-рендер, web/app.js + web/index.html), каталог параметров (REGISTRY 383 /
> 71 групп / Settings 359, TAB_RULES param_catalog.py:1374-1406, паттерн добавления
> раздела), локализованы все 9 пунктов ТЗ по группам/ключам. Всё зафиксировано —
> KG-сущность **`recon: tma-structure-10.4`** (полные координаты, реестры ключей
> реакций/лимитов/памяти/провайдеров/отношений, тест-риски, конфликты с F-1…F-6).
> Планирование — @PM (конфликт-матрица не строилась).
> **Синк STEP 3 (планирование 10.4) 10.09.2026:** раунд 10.4 распланирован и
> **ЗААРХИТЕКТИРОВАН** — **8 фич** (plans/features/, spec.md @Architect + tasks.md
> @PM для каждой, стадия ARCHITECTED, Builder не начат): **D**
> `frontend-advanced-collapse-default` (T-1018…T-1023), **C**
> `frontend-memory-sleep-nostalgia` (T-1006…T-1017), **E**
> `frontend-llm-providers-layout` (T-1024…T-1032), **A**
> `frontend-reorg-modules-reactions` (T-974…T-989), **B**
> `frontend-limits-temperature-budgets` (T-990…T-1005), **F**
> `frontend-relations-participants` (T-1033…T-1044), **H**
> `backend-relations-nickname` (T-1057…T-1065), **G**
> `backend-chat-1002661910336-scaling` (T-1045…T-1056) — итого T-974…T-1065
> (92 задачи). Порядок исполнения: **D → C → E → A → B → F → H → G** (обоснование:
> D — аккордеоны первыми; C/E/A — реструктуризация вкладок после D; B — per-chat
> алиасы/виджет ДО F и H; H — фикс каскада после B; G — деплой-бэкфил последним).
> Ключевое: REGISTRY **383/71/359 ЗАМОРОЖЕН** по всем 8 фичам (MED-017 — только
> переносы/разметка/поля виджета select); SQLite v8, порядок роутеров bot.py,
> каноны промптов, known_sections() — без дифов; R16/R17 сохранены; **девиансия
> D-A1** (фича A: war/common/goodmorning/word_reactions ТАКЖЕ переезжают в
> «Функции PERMsoc» — канон спеки §2, шире tasks.md T-975); общий новый тест
> `test_progressive_tab_basic_coverage` (≥1 basic-группа на каждую config-вкладку;
> пишется в D, зелёный после C/E/A; MED-022-маркеры обновляются в каждой
> фронт-фиче). Конфликт-матрица с F-1…F-6 зарегистрирована в backlog.md:
> **F-1 ДО B/G** (атомарный POST, касты T-651/652, NaN T-654), **F-3 T-663 ПОСЛЕ
> раунда** (DM-перепроверка), **F-4 Баг-4 ПОСЛЕ раунда** (сверка по новой карте
> вкладок), **F-5 ПОСЛЕ G/B** (реестры новых read-путей), **F-6 SUPERSEDED_BY
> round10.4** (аудит каскада → H T-1058/1059/1063, live-эффект → B T-1005,
> верификация → владельцу). Граф обновлён (Step 3): AdminBot HAS_PLAN → 8 фич,
> милстоун `round10.4-epic` → ARCHITECTED (PLANNED_IN/ARCHITECTED_IN plans-structure),
> цепочка DEPENDS_ON D→C→E→A→B→F→H→G; наблюдения добавлены в param-catalog
> (TAB_RULES-реструктуризация), DirectChatService (бюджеты B + overrides G),
> chat-lore (каскад имён H + перенос F), plans/features/user-aliases-admin
> (SUPERSEDED_BY).
> **Merge Phase 10.4 (10.09.2026, @Architect)** — 8 фич раунда (D/C/E/A/B/F/H/G,
> T-974…T-1065) IMPLEMENTED в рабочем дереве (HEAD 1410a68 + 10.4: 24 модифицированных
> файла, 8 новых фич-папок, 2 backfill-скрипта `scripts/backfill_104_{chat_flags,overrides}.py`,
> 2 новых тест-файла), @Reviewer APPROVED, Scanner-аудит 10.4: **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты
> follow-up @Builder и сверены), pytest **4860 passed / 0 failed** (4831 → +29),
> `node --check web/app.js` clean, `git diff --check` чист. ARCHITECTURE.md обновлён:
> **§24** (раунд 10.4: карта вкладок — PERMsoc 17 групп/Модули/Память+Сон+Ностальгия/
> секции LLM Провайдеров/Имена людей/Участники и отношения/Лор-расширенные; select-виджет
> (widget='select' + select_options/select_labels, 422); бюджет-флаг per-chat
> `chat_context_budgets_enabled` + backfill_104_chat_flags (-1002661910336 off);
> `build_alias_resolver(chat_id)` per-chat/ЛС алиасы; аккордеоны «Расширенные» свёрнуты
> по умолчанию (expandOpen+персист); каскад имён username-всем строкам (Semaphore 5,
> кэш 1ч, фото топ-50, R16); per-chat скейлинг -1002661910336 — 15 ключей ×1.5–×2,
> backfill_104_overrides, `_resolve_from_root` _cast_type_ok+isfinite, граница G-4,
> KPI 25 req → флаг бюджетов off) + **§25** «Известные ограничения и техдолг»
> (R10.4-1…R10.4-7 со статусами + обновлённые R10.3-*); кросс-указатели §3/§4/§9/§16
> (+ исправлен счётчик групп каталога **71→74** — ре-дизайн 10.2 BUG-3 +3 группы;
> сверка: GROUPS=74 на HEAD и в 10.4). Локальные спеки 8 фич НЕ тронуты (архивная
> фаза — @PM); коммит/деплой + прогон обоих бэкфилов (@DevOps) — финальный шаг раунда.
> **Финальный синк KG/графа, статусов милстоуна `round10.4-epic` и архивирование —
> шаг 10 @Memory.**
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.4 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `0bdf272` (feat(admin,web,chat,api):
> раунд 10.4 — реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/
> Провайдеры/Отношения), бюджеты per-чат и температура-select, имена людей
> per-чат/ЛС, каскад имён, лимиты ×1.5-×2 для -1002661910336); тесты **4860 passed /
> 0 failed** (4831 → +29), @Reviewer APPROVED, Scanner 10.4 **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты follow-up
> и сверены); деплой 10.09.2026 (198.46.175.136): git pull, **.env +=
> CHAT_THREAD_MAX_CHARS=2000**, **бэкфилы применены** — backfill_104_chat_flags.py
> (флаг бюджетов OFF для -1002661910336) + backfill_104_overrides.py
> (15 ключей ×1.5–×2), рестарт, bot active; ARCHITECTURE.md §24 (карта вкладок/
> бюджеты/каскад имён) + §25 (техдолг R10.4-*, B-13 points 2-4, HIGH-004-остаток);
> 8 фич заархивированы (@PM) — plans/archive/ **26 папок**, plans/features/ снова
> 6 активных F-1…F-6; README тесты 4860; граф обновлён (round10.4-epic →
> **COMPLETED+DEPLOYED**, 8 фич → ARCHIVED_IN/WAS_PART_OF, HAS_PLAN/PLANNED_IN/
> ARCHITECTED_IN удалены, создан `tech-debt-round10.4`). Цикл раунда полностью закрыт.
> **Синк STEP 3 (планирование 10.5) 10.09.2026:** раунд 10.5 «Редизайн TMA по
> референсу Relume + гигиена репозитория» распланирован и **ЗААРХИТЕКТИРОВАН** —
> фича **`tma-relume-redesign`** (`plans/features/tma-relume-redesign/`):
> `tasks.md` @PM (T-1066…T-1089, продолжает T-1065), `reference-analysis.md` @PM
> (recon-разбор референса, стадия ANALYSIS), `spec.md` @Architect (686 строк,
> §0–§11). Референс `relumesite_example/` — статический Relume-экспорт (15 страниц,
> 0 input/form/table) ⇒ редизайн визуальный + IA, не функциональный порт; ~90%
> функциональности уже есть (18 вкладок в 5 секциях MENU_ORDER). T-1066 (гигиена)
> **ВЫПОЛНЕНО** — `.gitignore += relumesite_example/` (отдельный раздел),
> `media/` НЕ тронут (политика project.md). ⏸ Решения **D1–D8** требуют владельца
> (рекомендации @Architect: C hybrid / поэтапно / остаться на Vue3 global / палитра
> P3 teal `#14CBB6` на dark `#161616` / emoji now + Material Symbols follow-up /
> Чат-Профиль на усмотрение / B1-B2 отложить / hash-роутинг при C); секция E
> (реализация) заблокирована до апрува D1 (T-1076). Конфликт-матрица с F-1…F-6:
> **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ редизайна 10.5**, F-1/F-2/F-3/F-5
> независимы, F-6 SUPERSEDED_BY round10.4. Граф обновлён (Step 3): entity
> `tma-relume-redesign` обогащена (+5 наблюдений: артефакты, инварианты/фазы/AC,
> `.gitignore`-гигиена, D1–D8, конфликт-матрица; дублей нет — добавлено в
> существующую сущность @Architect), создано 7 связей: `AdminBot HAS_PLAN
> tma-relume-redesign`, `CONFLICTS_WITH plans/features/frontend-admin-bugfixes`,
> `RELATED_TO` ×5 (post-deploy-admin-minors, admin-debug-webview,
> scam-incident-security-followup, config-read-path-audit, user-aliases-admin).
> Следующий шаг — решение владельца D1–D8 → @Builder секция E.
> **Синк STEP 3 (design-project) 10.09.2026 (вечер):** главный deliverable раунда
> 10.5 ГОТОВ и находится на **GATE** — `plans/features/tma-relume-redesign/design-project.md`
> (835 строк, RU, §0–§14; статус 🟡 DESIGN/GATE). `spec.md` → **v2** (согласован с
> решениями владельца **OD1–OD6**, которые отменяют/заменяют рекомендации spec v1 и
> прежние D1–D8); `tasks.md` секция **E (T-1090…T-1097) ✅ ВЫПОЛНЕНО**; секции
> **F/G (T-1098…T-1118) ⛔ заблокированы до явного апрува владельцем**. **OD1–OD6
> (LOCKED):** OD1 навигация = **вариант B, ПОЛНЫЙ ребейлд** по модели эталона
> (navbar 6 пунктов + hub-карточки + отдельные экраны); OD2 **big-bang всё сразу**
> (внутренний порядок токены→shell/navbar→hubs→15 экранов→QA); OD3 **та же
> технология** (Vue3 global / zero-build, единый `index.html`+`app.js`); OD4 палитра
> эталона как база + **АНИМИРОВАННЫЕ плавные градиенты** (reduced-motion + WCAG AA);
> OD5 **Material Symbols Rounded** primary + карта emoji-fallback; OD6 **структура
> эталона = ЭТАЛОН** композиции (15 страниц). **КРИТИЧНО:** hash-роутинг обязателен
> (следствие OD1+OD3); Telegram кладёт `initData` в `window.location.hash`
> (`#tgWebAppData=...`) — читать/кэшировать **ДО** первой записи `location.hash`,
> парсить только роуты с префиксом `#/`, **vue-router НЕ использовать** (ломает
> кодирование `tgWebAppData`, vuejs/router#2155). **Верифицированная коррекция:**
> в приложении **17 вкладок** `TABS` (`web/app.js:18-145`), а НЕ 18 (off-by-one в
> `tasks.md`/`spec.md`); паритет — «0 бездомных» из 17. **Предложения (§10):**
> **ADD A1–A10** (initData-guard, Telegram BackButton+deep-link, единые
> empty/error/retry, hub-карточки+drill-down, self-host subset Material Symbols,
> prefers-contrast:more, тема-переключатель 4 схемы, quick-search, скелетоны
> relations, breadcrumb); **REMOVE R1–R7** (sidebar как primary nav, хардкод
> `#8b5cf6/#3b82f6/#2b2b40`+Tailwind-токены, дубль локальных админов в `chat_lore`,
> emoji как основные иконки, отдельная navbar-секция «Чат-Профиль», Tailwind CDN
> runtime, 409 no-op reload); **OPTIMIZE O1–O7** (`@property inherits:false` → до
> 848% быстрее recalc, ограничение площади анимации + `contain:paint`, ленивые
> аватары R10.4-4, кэш params-meta/chats, namespace-модульность без разбиения файла,
> DM models read-only, единый fetch-слой); **NOT DO N1–N5** (bundler/vue-router,
> backend B1/B2, текст на движущемся градиенте, анимация за таблицами/формами/логами,
> изменения param_catalog/settings/SQLite v8/PG-DDL/порядок `bot.py`). Открыты
> **D6** (реком. свернуть «Чат-Профиль» в AI-hub), **D7** (реком. отложить B1/B2,
> B3 опц.), **D8** (реком. включить BackButton/deep-link). Exa-research успешен
> (6 тем: docs.telegram-mini-apps.com, core.telegram.org, W3C WCAG 2.3.3, web.dev
> @property, MDN, Google Fonts Material Symbols, admin IA). Граф обновлён:
> `tma-relume-redesign` +4 наблюдения (deliverable/status+GATE, OD1–OD6, proposals
> A/R/O/N, gotcha initData/17-vs-18); relation `HAS_DESIGN_PROJECT →
> tma-relume-redesign-design-project`; дублей нет (Voxy-сущности не затронуты,
> ничего не удалено). **Следующий шаг — владелец: D6/D7/D8 + GO → @Builder T-1098.**
> **Синк STEP 3 (догон, T-1119/T-1120) 10.09.2026 (вечер, @Memory):** доуточнения
> проекта по обратной связи владельца **ВЫПОЛНЕНЫ** — `tasks.md` секция **E2**:
> **T-1119 ✅** (Exa-research back-навигации) и **T-1120 ✅** (plain-language
> разъяснения D6 + B1/B2/B3); `design-project.md` (1105 строк) обновлён: **§0 TL;DR**
> (+п.9 «back без своей кнопки»), **§6.4 переписан** (нативный `Telegram.WebApp.BackButton`:
> `show()` на глубине >0 заменяет ✕ на ←, `hide()` на корне возвращает ✕ — один header-слот,
> конфликта нет; мы владеем history/stack, Telegram — header+OS-back; Android hardware-back
> эмитит `back_button_pressed` только при `is_visible=true`, иначе закрывает WebView;
> `onClick` регистрируется ОДИН раз → `goBack()` = детерминированный parent-route, НЕ
> `history.back()`, без popstate; единственный applier = `hashchange`; Bot API 6.1+),
> **§11** (+ **§11.1 D6**, + **§11.2 D7**), **§12** (Exa расширен **6→7 тем** + источники
> **§12.7**), **§13** (AC-5 routing переформулирован под нативный BackButton, AC-9 —
> Scanner re-check), **§14 GATE**. Новый маркер-тест `test_webapp_back_button` (§9.4).
> Тумблеры: `__TMA_BACK__=true` (решено), `__TMA_DEEPLINK__` (ждёт владельца, default false).
> **Статусы решений:** **D8 — RESOLVED-in-intent** (back-навигация подтверждена владельцем,
> паттерн определён); **D6/D7 — OPEN** (ждут решения владельца; рекомендации: свернуть
> «Чат-Профиль» в «Настройки AI» — 6 navbar-пунктов как в эталоне; B1/B2 отложить, B3
> опционально). **GATE остаётся ЗАКРЫТ** — 0 кода, реализация (F/G) не стартует до явного
> GO владельца + решения deep-link. Репо: HEAD `0bdf272`, worktree dirty (`.gitignore`,
> `plans/MEMORY.md`, `plans/backlog.md` modified; `plans/features/tma-relume-redesign/`
> untracked). Граф: обновлены `tma-relume-redesign`, `tma-relume-redesign-design-project`,
> `TMA BackButton navigation pattern`, `D6 D7 plain-language clarifications` (только
> добавление наблюдений; дублей нет; Voxy-сущности не затронуты).
> **Синк STEP 3 (v3, секция E3 — OD7–OD10) 10.09.2026 (поздний вечер, @Memory):** главный
> deliverable раунда 10.5 обновлён до **v3** — `design-project.md` **1105 → 1817 строк**,
> добавлен **§15** (15.1 scope-switcher/OD7, 15.2 key-availability/OD8, 15.3
> role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9, 15.6 Q-NEW-1..5, 15.7
> трассировка E3); обновлены §0/§2/§3/§5/§7/§10/§11/§12/§13/§14. `tasks.md`
> **T-1121…T-1126 ✅ done (E3)**; `spec.md` согласован (v3-указатель, v2 частично
> SUPERSEDED). **OD7–OD10:** OD7 «Чат-Профиль» = глобальный scope-switcher GLOBAL/ЧАТ/ЛС
> (не 7-й nav-пункт); OD8 B1 key-availability В СКОУПЕ (in-memory ring, без PG-DDL/
> SQLite v8); OD9 B2 custom-modules CRUD OUT (read-only); OD10 B3 role-matrix В СКОУПЕ и
> расширена (per-param read/write + role CRUD). **Q-NEW-1..5** (каталог 383→385?;
> key-history in-memory vs persisted; deep-link; файл шрифта; delete/rename ролей?) и
> **D9/D11** открыты владельцу; font-delivery spec готова (§15.4: self-host woff2 subset
> `web/static/fonts/`, `@font-face`, CSP `font-src 'self'`, ~2–15 КБ, emoji-fallback).
> **GATE ЗАКРЫТ: 0 кода**, T-1127+ (F4) и F/G не стартуют без GO владельца. Граф обновлён:
> добавлены наблюдения в `tma-relume-redesign` (+5), `tma-relume-redesign-design-project`
> (+1), `tma-relume-redesign v3 design-project` (+7: §15-карта, Q-NEW, трассировка, gate);
> связи — `v3 SUPERSEDES design-project`, `tma-relume-redesign HAS_DESIGN_PROJECT v3`,
> `OD7-OD10 owner decisions DECIDES tma-relume-redesign`. Дублей нет; Voxy-сущности не
> затронуты; удалений нет.
> **Синк STEP 3 (v4, секция E4 — OD11–OD15, T-1136…T-1138) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v3 → v4** — `design-project.md`
> **1817 → 2119 строк**, добавлен **§16** (16.1 hardcode-аудит H1–H22; 16.2 замеры
> шрифта; 16.3 персистентность истории; 16.4 роли; 16.5 **Q1–Q4**; 16.6 Scanner);
> обновлены шапка/§0 (пп.12–17)/§5.2/§6.4.5/§10.4 N5/§11/§13 (**AC-14…AC-18**)/
> §14/§15.2/§15.3/§15.4/§15.5/§15.8. `tasks.md` секция **E4 (T-1136/T-1137/T-1138)
> ✅ ВЫПОЛНЕНО**; **T-1139…T-1142 (F5, реализация OD11–OD15) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v4). **0 кода.** **Итоги:** (OD11) исчерпывающий аудит —
> **9 активных P0-хардкодов / 4 уникальных значения** (Groq/OpenRouter base_url +
> STT-модели whisper-large-v3 / openrouter/free) в `services/status_service.py`,
> `SmartModule/transcriber/{groq,openrouter}_transcriber.py`, `services/video_cascade_client.py`;
> миграция **аддитивная** `hot.get(key, literal)` (дефолт = текущая константа ⇒ вывод
> идентичен, существующие значения не меняются); санкционированное исключение
> **param_catalog +2 PG-only записи STT → REGISTRY 385 / GROUPS 74 / Settings 359**
> (было 383/74/359), сид `code_source` + `ON CONFLICT DO NOTHING`; P1 — дефолт-фолбэки
> (не трогать), P2 — фикс-endpoint'ы, T — tooling. (OD12) история доступности ключей
> **персистится**: in-memory ring + **атомарный JSON-снимок `var/status_key_history.json`**
> (gitignored, 288 точек/провайдер, R17-safe) — **0 PG-DDL, SQLite остаётся v8** ⇒
> **исключение у владельца НЕ требуется**. (OD13) **deep-link OFF** — D9 CLOSED,
> `__TMA_DEEPLINK__=false`, задач реализации нет. (OD14) шрифт
> `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2` **инспектирован T-1137**:
> валидный WOFF2, Material Symbols Rounded v2.967, 6607 глифов / 4277 лигатур,
> оси `FILL 0..1 / GRAD -50..200 / opsz 20..48 / wght 100..700`, **26/26 иконок**,
> Apache-2.0, но **5.36 МБ (5.11 МиБ) = не shippable** ⇒ обязателен субсет
> (`pyftsubset`): all-axes 36.3 КБ, **FILL-only 5.5 КБ**, **FILL+wght 13.2 КБ
> (рекомендован)**, static 3.7 КБ; **КРИТИЧНО:** `--unicodes-file` **теряет лигатуры**
> (`rlig/rclt→0`) ⇒ иконки рендерятся **PUA-кодпоинтом** (`&#xE850;`), а не текстом-именем;
> `--text` сохраняет лигатуры, но 4.03 МиБ (отвергнут); источник 5.11 МиБ **не
> коммитить** (`.gitignore`), коммитим субсет ~13.2 КБ + Apache-2.0 LICENSE; build-time
> зависимости `fonttools`+`brotli` (не рантайм). (OD15) **rename/delete ролей разрешены,
> КРОМЕ superuser** (жёсткая защита 403/409 + UI disabled; встроенные/занятые — нельзя).
> Открыты владельцу только **4 не-блокирующих выбора Q1–Q4** (base-url UI +2 записи
> → 387?; `fonttools`+`brotli` как build-dep?; 5.11 МиБ источник вне git?; файл
> `var/status_key_history.json`?). **GATE по-прежнему ЗАКРЫТ: 0 кода**, старт
> реализации (F/F4/F5/G) — только после общего GO владельца на v4. Граф обновлён:
> создана сущность **`tma-relume-redesign v4 design-project`** (+11 наблюдений) и
> **`OD11-OD15 owner decisions`** (+7); добавлены наблюдения в `tma-relume-redesign`
> (+2) и `tma-relume-redesign v3 design-project` (+1, SUPERSEDED); связи —
> `v4 SUPERSEDES v3`, `tma-relume-redesign HAS_DESIGN_PROJECT v4`,
> `v4 implements OD11-OD15`, `OD11-OD15 DECIDES tma-relume-redesign`.
> Дублей нет; Voxy-сущности не затронуты; удалений нет.
> **Синк STEP 3 (v5, секция E5 — OD16–OD19, T-1144) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v4 → v5** — `design-project.md`
> **2119 → 2312 строк**, добавлена трассировка **§16.7 (E5)**; обновлены
> шапка/§0/§3/§9/§10/§11/§13/**AC-19/AC-20**/§14/§15.2/§15.3/§15.4/§16.1–§16.7.
> `tasks.md` секция **E5 (T-1144) ✅ ВЫПОЛНЕНО** (pre-gate, 0 кода, landing notes);
> **T-1145…T-1148 (F6, реализация OD16–OD19) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v5). **Итоги:** **(OD16)** адреса провайдеров
> (`base_url` Groq/OpenRouter) **ОБЯЗАТЕЛЬНЫ в UI** — провайдер, модель и адрес
> редактируемы из мини-аппа, владелец **переключает провайдера И модель**; отменяет
> прежнее «base_url hot-only» (§15.2.2/§16.5 Q1); **+2 PG-only записи каталога**
> `models.groq_base_url` = `https://api.groq.com/openai/v1`,
> `models.openrouter_base_url` = `https://openrouter.ai/api/v1` ⟹ каталог-финал
> **REGISTRY 387 / GROUPS 74 / Settings 359** (383 → +2 STT OD11 → 385 → +2 адреса
> OD16 → **387**; миграция аддитивная, значения не меняются, `GET /api/status.llm[]`
> байт-идентичен, R17 — адрес НЕ секрет). **(OD17)** `fonttools`+`brotli` —
> **build-time only** (в runtime `requirements.txt` не входят). **(OD18)** тяжёлый
> источник шрифта **5.11 МиБ** → **`.gitignore`** (в git только субсет ~13.2 КБ +
> `LICENSE` Apache-2.0; на 10.09.2026 файл **untracked и ещё НЕ ignored** ⟹ T-1147
> добавит паттерн). **(OD19)** `var/status_key_history.json` **утверждён** с
> **обязательной leak-safety-верификацией**: allowlist-схема (module id, provider,
> model, key-configured bool, HTTP-код, timestamp, version, generated_at); запрет
> сырых ключей/токенов/`Authorization`/`Bearer`/`sk-`/`gsk_`/cookies/`initData`/
> credentials-in-`base_url`/тел LLM; права 0600 (каталог 0700); gitignored; **не
> отдаётся `GET /api/config`** и **не пишется в логи/`log_ring`/BetterStack**;
> атомарная запись (tmp + `os.replace`); corrupt/missing → пустая история + WARNING
> (fail-open). AC: grep-маркер (нет паттернов ключей) + unit-сериализатор +
> проверка прав + `git check-ignore` + выживание рестарта; **R17 доказан**.
> Scanner E5: `plans/reports/` — новых отчётов по 10.5 нет (последний — Round 10.4,
> 0 blocker/0 major); учтены MED-017/MED-021/LOW-012/R10.4-2/-4/-5, MED-003
> подтверждает OD16. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** —
> открытых вопросов/выборов НЕ осталось. **GATE по-прежнему ЗАКРЫТ: 0 кода**;
> реализация (F/F5/F6/G, T-1098…T-1148) стартует только после **явного общего GO
> владельца на v5**. Граф обновлён: созданы сущности
> **`tma-relume-redesign v5 design-project`** (+10 наблюдений) и
> **`OD16-OD19 owner decisions`** (+6); добавлены наблюдения в `tma-relume-redesign`
> (+1) и `tma-relume-redesign v4 design-project` (+1, SUPERSEDED); связи —
> `v5 SUPERSEDES v4`, `tma-relume-redesign HAS_DESIGN_PROJECT v5`,
> `v5 implements OD16-OD19`, `OD16-OD19 DECIDES tma-relume-redesign`.
> Цепочка SUPERSEDES: **v5 → v4 → v3**. Дублей нет; Voxy-сущности не затронуты;
> удалений нет.
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.5 ПОЛНОСТЬЮ
> ЗАВЕРШЁН — HEAD == origin/master == `c01ed72`** (`918f675` — фича, 49 файлов;
> `c01ed72` — docs деплой-верификация; поверх `0bdf272`). Единственная фича
> `tma-relume-redesign` (T-1066…T-1148) реализована целиком (Builder Pass 1–6:
> токены/градиенты, hash-router + нативный BackButton, scope-switcher GLOBAL/ЧАТ/ЛС,
> hubs + 15 экранов, key-availability + persisted chart, матрица ролей + role CRUD
> кроме superuser, hardcode H1–H22 → безопасная аддитивная миграция, каталог
> 387/74/359, font-subset ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed).
> @Reviewer: REJECTED → fixes D1–D4 → APPROVED WITH MINOR → R1–R4 закрыты.
> @Scanner: **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты, R10.5-3/-5/-6/-7
> — техдолг (ARCH §25); отчёт `plans/reports/round10.5_scanner_audit.md`.
> @Architect: merge в `plans/ARCHITECTURE.md` (§9 обновлён, §25 «по состоянию на 10.5»
> + блок R10.5, новый **§26 «Раунд 10.5»** — последняя секция). **Тесты: 4962 passed /
> 0 failed** (baseline 10.4 = 4860, +102); `node --check web/app.js` clean;
> `git diff --check` чист. @PM: фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**, plans/features/ — снова 6 активных F-1…F-6), backlog
> epic 10.5 закрыт. @DevOps: README обновлён (ироничный тон); push origin/master;
> **деплой 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, `systemctl restart admin_bot` → active (running), `/api/health` = 200,
> **0 startup-ошибок**. Граф обновлён: милстоун `round10.5-epic` → COMPLETED + DEPLOYED,
> фича → WAS_PART_OF + ARCHIVED_IN plans-structure + COMPLETED_IN/DEPLOYED_IN, создан
> `tech-debt-round10.5` (R10.5-3/5/6/7). **Осталось вручную:** live Telegram
> smoke-тест (T-1153), опциональный betterstack-401 fix, вердикт владельца.

## Активные фичи (plans/features/)

| Фича | Скоуп |
|---|---|
| `admin-debug-webview` (F-2) | `/debug_config` в HTML WebView поверх HTTPS |
| `scam-incident-security-followup` (F-3) | Секьюрити-фоллоу-ап после скам-инцидента 30.08 |
| `frontend-admin-bugfixes` (F-4) | Багфиксы админ-минги и `<Красивые ссылки>` |
| `config-read-path-audit` (F-5) | Аудит read-путей: settings.X vs hot.get |
| `user-aliases-admin` (F-6) | Алиасы юзеров в разделе «Лор чатов» (частично в master; SUPERSEDED_BY round10.4) |
| `post-deploy-admin-minors` (F-1) | Пост-деплойные миноры Epic 85 (T-648:T-655) |

> **Раунд 10.14 — 8 фич ЗАВЕРШЁН, ЗАДЕПЛОЕН и ЗААРХИВИРОВАН (13.09.2026)** — F1
> `anti-echo-self-reply`, F2 `persona-storage-core`, F3 `persona-ui-tab`, F4
> `persona-traits-ribbon`, F5 `settings-persistence-audit`, F6 `help-guide-integration`,
> F7 `status-layout-reorder`, F8 `self-reflection-llm-provider` (72 задачи T-1477…T-1548,
> все COMPLETED+DEPLOYED). Спеки+ADR — в `plans/archive/*-round1014/` (8 папок);
> `plans/archive/` — **50 папок**; `plans/features/` — 6 активных (F-1…F-6). См. блок
> «Синк STEP 10 (финал) раунда 10.14» выше.

> **Раунд 10.13 — 8 фич ЗАВЕРШЁН и ЗААРХИВИРОВАН (13.09.2026)** — F1 4D-память,
> F2 belief decay+resurrection, F3 глубокий сон+роутер, F4 UI провайдеров,
> F5 дашборд Cognition+виджет, F6 EKG+фикс логов, F7 справка+README, F8 ирония/досье
> (60 задач T-1417…T-1476, все COMPLETED). Спеки — в
> `plans/archive/cognition-*-round1013/` (spec.md + tasks.md + ADR-1013-1/2/3);
> см. блок «Синк STEP 10 (финал) 13.09.2026» выше и «Свежие архивы» ниже.

> **Раунд 10.4 — 8 фич ЗАВЕРШЁН и ЗААРХИВИРОВАН (10.09.2026)** — см. раздел
> «Раунд 10.4 — финал» ниже; их спеки — в `plans/archive/`
> (frontend-advanced-collapse-default, frontend-memory-sleep-nostalgia,
> frontend-llm-providers-layout, frontend-reorg-modules-reactions,
> frontend-limits-temperature-budgets, frontend-relations-participants,
> backend-relations-nickname, backend-chat-1002661910336-scaling);
> конфликт-матрица backlog.md «Раунд 10.4»: F-1 PRECEDES B/G — учтён; F-3 T-663 +
> F-4 Баг-4 + F-5 — остаются ПОСЛЕ раунда (фичи активны); F-6 — SUPERSEDED_BY
> round10.4-epic (подтверждена; папка F-6 остаётся в plans/features/).

> **Раунд 10.5 — DESIGN-PROJECT v3 ГОТОВ, на GATE (10.09.2026, поздний вечер)** — активная
> фича `tma-relume-redesign` в `plans/features/`: решения владельца **OD1–OD6 LOCKED**
> (полный ребейлд по эталону / big-bang всё сразу / Vue3 global zero-build /
> анимированные градиенты + reduced-motion + WCAG AA / Material Symbols Rounded +
> emoji-fallback / структура эталона = эталон) + **OD7–OD10 LOCKED** (OD7 «Чат-Профиль» =
> глобальный scope-switcher GLOBAL/ЧАТ/ЛС, НЕ 7-й nav-пункт; OD8 B1 key-availability
> В СКОУПЕ (in-memory ring, без PG-DDL/SQLite v8); OD9 B2 custom-modules CRUD OUT;
> OD10 B3 role-matrix В СКОУПЕ и расширена). Главный deliverable —
> **`design-project.md` v3 (1817 строк, RU, §0–§15, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v3-указатель, v2 частично SUPERSEDED); `tasks.md` секция
> **E/E2/E3 (T-1090…T-1126) ✅ ВЫПОЛНЕНО**; **T-1127…T-1133 (F4) + F/G ⛔ заблокированы
> до явного апрува владельцем**. **§15 (E3):** 15.1 scope-switcher/OD7, 15.2
> key-availability/OD8, 15.3 role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9,
> 15.6 **Q-NEW-1..5**, 15.7 трассировка. **Открыто владельцу:** Q-NEW-1 (+2 строки каталога
> 383→385?), Q-NEW-2 (key-history in-memory vs persisted), Q-NEW-3 (deep-link, реком. OFF),
> Q-NEW-4 (файл шрифта, emoji до поставки), Q-NEW-5 (delete/rename ролей?), **D9**
> (`__TMA_DEEPLINK__`=false), **D11** (шрифт поставляет владелец) + **GO на реализацию**.
> **RESOLVED:** D6/D7 → OD7–OD10; D8 — back через нативный `BackButton` (`__TMA_BACK__`=true).
> `.gitignore += relumesite_example/` (T-1066); `media/` НЕ тронут. **Коррекция:** 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18. Конфликт-матрица: **F-4 frontend-admin-bugfixes
> (Баг-4) — ПОСЛЕ 10.5** (редизайн меняет карту вкладок); F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Спека референса — `relumesite_example/`
> (gitignored). Детали — KG `tma-relume-redesign` + `tma-relume-redesign v3 design-project`.
> (Блок выше — исторический снимок v3; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v4 ГОТОВ, на GATE (10.09.2026, E4/OD11–OD15)** — активная
> фича `tma-relume-redesign` в `plans/features/`: **OD1–OD10 LOCKED** (см. блок v3 выше)
> + **OD11–OD15 LOCKED** (ответы владельца на §15.6 Q-NEW-1..5): **OD11** — ноль
> захардкоженных моделей (аудит T-1136: 9 P0-хардкодов, аддитивная миграция без смены
> значений, `REGISTRY 385 / 74 / 359`); **OD12** — история ключей персистится
> (`var/status_key_history.json`, 0 PG-DDL, SQLite v8, исключение не нужно); **OD13** —
> deep-link **OFF** (`__TMA_DEEPLINK__=false`); **OD14** — шрифт инспектирован (валиден
> как источник; 5.11 МиБ не shippable → субсет ~13.2 КБ + рендер по PUA-коду); **OD15** —
> rename/delete ролей, **кроме superuser**. Главный deliverable —
> **`design-project.md` v4 (2119 строк, RU, §0–§16, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v4); `tasks.md` секции **E/E2/E3/E4 (T-1090…T-1138) ✅ ВЫПОЛНЕНО**;
> **T-1127+ и F/F4/F5/G (T-1098…T-1143) ⛔ заблокированы до явного GO владельца на v4**.
> **D6–D12 — все RESOLVED** (OD7–OD15). `.gitignore += relumesite_example/` (T-1066) +
> 5.11 МиБ источник шрифта (OD14); `media/` НЕ тронут. **Коррекция:** 17 вкладок `TABS`
> (`web/app.js:18-145`), не 18. Открыты только **4 не-блокирующих выбора Q1–Q4** (§16.5).
> Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**; F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign` +
> `tma-relume-redesign v4 design-project` + `OD11-OD15 owner decisions`.
> (Блок выше — исторический снимок v4; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v5 ГОТОВ, на GATE (10.09.2026, E5/OD16–OD19) — исторический снимок v5, см. финал ниже** —
> активная фича `tma-relume-redesign` в `plans/features/`: **OD1–OD15 LOCKED** (см. блоки v3/v4
> выше) + **OD16–OD19 LOCKED** (ответы владельца на §16.5 Q1–Q4): **OD16** — адреса
> провайдеров (`base_url`) **обязательны в UI**, провайдер/модель/адрес редактируемы из
> мини-аппа ⟹ каталог **REGISTRY 387 / GROUPS 74 / Settings 359** (383→385→387);
> **OD17** — `fonttools`+`brotli` **build-time only**; **OD18** — источник шрифта **5.11 МиБ**
> → **`.gitignore`** (в git субсет ~13.2 КБ + Apache-2.0 LICENSE); **OD19** —
> `var/status_key_history.json` утверждён при **обязательной leak-safety** (allowlist-схема,
> права 0600/0700, gitignored, не в `GET /api/config`/логах, атомарная запись, R17 доказан).
> Главный deliverable — **`design-project.md` v5 (2312 строк, RU, §0–§16.7, статус
> 🟡 DESIGN v5 / GATE)**; `spec.md` согласован (v5); `tasks.md` секции
> **E/E2/E3/E4/E5 (T-1090…T-1144) ✅ ВЫПОЛНЕНО**; **F/F4/F5/F6/G (T-1098…T-1148)
> ⛔ заблокированы до явного GO владельца на v5**. Новые **AC-19** (UI-редактируемость
> провайдера/модели/адреса) и **AC-20** (leak-safety файла истории). Коррекции: 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18; `.gitignore += relumesite_example/` + источник шрифта;
> `media/` НЕ тронут. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** — открытых
> вопросов нет. Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**;
> F-1/F-2/F-3/F-5 независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign`
> + `tma-relume-redesign v5 design-project` + `OD16-OD19 owner decisions`.

> **Раунд 10.5 — ФИНАЛ: ЗАВЕРШЁН, ЗАКОММИЧЕН И ЗАДЕПЛОЕН (10.09.2026, HEAD
> `c01ed72`) — АКТУАЛЬНО** — милстоун **`round10.5-epic`** (COMPLETED + DEPLOYED).
> Коммиты `918f675` (фича, 49 файлов) + `c01ed72` (docs memory-sync), push
> origin/master. Тесты **4962 passed / 0 failed**; `node --check web/app.js` clean;
> @Reviewer APPROVED; @Scanner CLEAN (0 blocker/0 major; R10.5-3/-5/-6/-7 → техдолг
> ARCH §25); ARCHITECTURE.md §9/§25/§26. Деплой: 198.46.175.136:/var/www/admin_bot —
> git pull fast-forward, `.env` без изменений, restart active (running),
> `/api/health`=200, 0 ошибок. Фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**; features/ — 6 активных F-1…F-6); README обновлён;
> backlog epic 10.5 закрыт. **Осталось вручную:** live Telegram smoke-тест (T-1153),
> опц. betterstack-401 fix, вердикт владельца. Детали — KG `round10.5-epic` +
> `tma-relume-redesign` + `tech-debt-round10.5`. (Снимки v3/v4/v5 выше — историчны.)

> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.6 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `4055434` (`6f91e8b` — фича, 37 файлов;
> `4055434` — docs деплой-верификация; поверх `be7b85b` = задеплоенный 10.5).
> Единственная фича **`tma-ia-modules-rework`** (T-1155…T-1223) реализована
> целиком: sidebar удалён (только top navbar 6 пунктов, иконка + подпись),
> «Модули» = 11 `mod_*` с реальными тумблерами + модалка параметров,
> «Настройки AI» = 7 подразделов (RAG → «Память»), PERMsoc очищен (10 параметров →
> модули 5/6/7), Леха/Костик раздельно, LLM Провайдеры — 9 блоков по модулям +
> `POST /api/llm/test`, proxy/cookies → M6, diagnostics → M9, emoji→Material,
> эксклюзивный аккордеон «Доступы и роли». 5 master-флагов default ON
> (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED.
> **Каталог 392 / 91 / 364 / mapped 89 / TAB_RULES 19**; ноль PG-DDL, SQLite v8,
> `bot.py` и `media/` не тронуты. @Reviewer: REJECTED → fixes → APPROVED WITH MINOR
> → миноры закрыты. @Scanner: **CLEAN — 0 blocker / 0 major** (R10.6-1/-3 закрыты;
> R10.6-2/-4/-5/-6 — техдолг; отчёт `plans/reports/round10.6_scanner_audit.md`).
> @Architect: merge в `plans/ARCHITECTURE.md` (§27 + §25/§9/§6/§2). **Тесты:
> 5027 passed / 0 failed** (baseline 10.5 = 4962; +65); `node --check web/app.js`
> clean; `tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
> @PM: фича заархивирована — `plans/archive/tma-ia-modules-rework/`
> (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `4055434`, `.env`
> без изменений, restart → `is-active=running`, `/api/health`=200, **0 tracebacks**.
> Граф обновлён: милстоун `round10.6-epic` → COMPLETED + DEPLOYED, фича →
> WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.6` (R10.6-2/-4/-5/-6). **Осталось вручную:** live Telegram
> smoke-тест (desktop/Android WebView), опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.7 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `bb59476` (`7f3b790` — fix, 19 файлов;
> `bb59476` — docs деплой-верификация; поверх `2ccf558` — docs 10.6; прод до
> деплоя `4055434`).
> Единственная фича **`admin-ui-bugfixes-round107`** (spec @Architect T-1224)
> реализована целиком: 1a `scope*` → computed (фикс `function () { [native code] }`),
> 1b header safe-area padding, 1c компактный user block, 1d nav labels меньше/без
> per-letter wrap, 2a ellipsis таблицы ключей, 2b uptime gap-fill (непрерывная
> 5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None),
> 3a clipboard-ghost focusable (без visibility:hidden) + удалён, 3b фикс. ширины
> лог-колонок + flex последней, 3c copy-on-row-click с feedback, R106-5 dead ICONS
> удалены (26→20). @Reviewer: REJECTED (visibility:hidden сломал execCommand-фолбэк)
> → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт. @Scanner: **CLEAN — 0 blocker /
> 0 major** (R10.7-1 (minor) + R10.7-2..5 (info/nit) — техдолг; R10.6-5 ЗАКРЫТ; отчёт
> `plans/reports/round10.7_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§28 «Раунд 10.7»** (+§9/§25). **Тесты: 5042 passed /
> 0 failed** (baseline 10.6 = 5027; +15); каталог 392/91/364. @PM: фича
> заархивирована — `plans/archive/admin-ui-bugfixes-round107/`
> (**plans/archive/ — 29 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `7f3b790`, `.env`
> без изменений, restart → active, `/api/health` = 200, **0 errors**. Граф обновлён:
> милстоун `round10.7-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.7` (R10.7-1…R10.7-5). **Осталось вручную:** live Telegram
> smoke-тест исправленного UI, опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.8 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `976e335`** (`31d2ce7` — фича,
> 30 файлов, тесты 5076; `976e335` — docs деплой-верификация; поверх `636a75d` —
> docs-финал 10.7; прод до деплоя `7f3b790` = задеплоенный 10.7).
> Единственная фича **`admin-ui-round108`** (spec @Architect + tasks @PM; T-1243…)
> реализована целиком: (1) переименование разделов — «Доступы»/«PERMsoc»/«ИИ»/
> «Справка»/«Сводка» (route-ключи `#/how|ai|permsoc|access|oversight` не менялись);
> (2) emoji→Material-иконки, субсет шрифта **20→37** (13 428→**18 388 B**),
> идемпотентность build-script по `sha256(source_sha+ICON_NAMES)`,
> `build/icon_codepoints.json`, R10.7-4 cmap-тест; (3) фикс логов на Android —
> Material-шеврон только при `exc_text` (без невидимого глифа), дата
> **DD.MM HH:MM:SS**, блочная раскладка (без `<pre><span>`, без жёстких ширин),
> `.log-msg` full-width, R10.7-3 closed; (4) «Доступы» — подразделы отдельными
> **route-driven модалками** (`#/access/roles|local|admins`), «Администраторы»→
> «Роли», аккордеон удалён, «Мой доступ»/«Telegram ID админа» вне окон,
> BackButton/deep-link/Esc; (5) удалён внешний GLOBAL-бейдж; README переструктурирован
> (users-first, гайд «Управление и деплой», changelog под `<details>`), счётчик 5076;
> `APP_VERSION` 2.51.0→**2.52.0**, шрифт cache-busted `?v=__APP_VERSION__`.
> @Reviewer: APPROVED WITH MINOR ISSUES (doc-nit исправлен). @Scanner: **0 blocker /
> 0 major** (R10.8-1 Esc и R10.8-5 APP_VERSION/кэш субсета закрыты follow-up;
> R10.8-2/-3/-4 — info/техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**; отчёт
> `plans/reports/round10.8_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§29 «Раунд 10.8»** (+§1/§9/§25). @PM: фича заархивирована —
> `plans/archive/admin-ui-round108/` (spec.md, tasks.md, **ADR-001-access-windows-modal**,
> **ADR-002-icon-subset-parity**); **plans/archive/ — 30 папок**; plans/features/ —
> 6 активных F-1…F-6. @DevOps: README счётчик 5073→5076; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `7f3b790..31d2ce7`,
> `.env` без изменений, restart active, `/api/health`=200, шрифт `?v=2.52.0` → 200
> (wOF2, 18 388 B), 0 ошибок. Граф обновлён: милстоун `round10.8-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure,
> создан `tech-debt-round10.8` (R10.8-2/-3/-4 + закрытые R10.8-1/-5). **Осталось
> вручную:** live Android smoke **T-1254** (логи) и **T-1258** (окна «Доступов»);
> опциональный betterstack-401 fix.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.9 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `f928225`** (`d2d1215` — фича,
> 34 файла, тесты 5105; `f928225` — docs деплой-верификация; поверх `51f308b` —
> docs-финал 10.8; прод до деплоя `31d2ce7` = задеплоенный 10.8).
> Единственная фича **`admin-ui-round109`** (spec @Architect + tasks @PM + ADR-109;
> T-1270…T-1314) реализована целиком: (1) PERMsoc — 4 сворачиваемых owner-блока
> (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер; новый
> `flags.slavik_enabled` (default True), `reactions_persons` удалена,
> `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`;
> (3) `_preserveScroll` для `document.scrollingElement` И `.scroll-area` —
> сохранение не прыгает вверх, вкл. fullscreen; (4) все описания и титулы
> параметров/групп переписаны (plain ironic language, без жаргона/AI-паттернов);
> (5) карточка «Тяжёлые фичи» удалена; (6) «Бюджет фона» перенесён в «Сводку»
> (backend/endpoint не тронуты); (7.1) dashboard «Доступность ключей» из 4
> функциональных групп + реальный health `probe_openai` (ok/error/timeout/
> unreachable/not_configured; STT groq POST `/audio/transcriptions` multipart WAV;
> кэш per `module_id`: 2xx 60с, ошибки 10с; stale-200 не отдаётся); (7.2) 7
> `models.*_display_name` первым полем каждого провайдер-блока, форма `max-w-3xl`;
> (8) градиент быстрее (`--grad-speed:14s`, `grad-drift 18s`). **Каталог 400 / 90 /
> 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL, SQLite v8, `bot.py`/`media/` не
> тронуты. @Reviewer: REJECTED → фиксы → APPROVED WITH MINOR ISSUES → follow-ups
> закрыты. @Scanner: **0 blocker / 0 major / 0 medium** (3 low R10.9-1/-2/-3 +
> 3 info R10.9-4/-5/-6; R10.9-6 закрыт архивацией; отчёт
> `plans/reports/round10.9_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` §30 (+§1/§9/§25). **Тесты: 5105 passed / 0 failed**
> (baseline 10.8 = 5076; +29); `node --check web/app.js` clean; `tests/js/routing_test.js`
> → `JS-UNIT-OK`; `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round109/` (spec.md + tasks.md + ADR-109.md);
> **plans/archive/ — 31 папка**; plans/features/ — 6 активных F-1…F-6. @DevOps:
> README 5105 + APP_VERSION **2.53.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `31d2ce7..d2d1215`,
> `.env` без изменений, restart active, `/api/health` 200, 0 ошибок. Граф обновлён:
> милстоун `round10.9-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.9` (R10.9-1/-2/-3 low + R10.9-4/-5 info; R10.9-6 закрыт).
> **Осталось вручную:** live Android smoke — T-1277/1290/1292/1294/1302/1305;
> опциональный betterstack-401 fix. ⚠️ Пункт 2 исходного ТЗ (инфраструктура
> локального IDE владельца) — **вне скоупа проекта**, в репозитории/графе
> не фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.10 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `772db08`** (`d082800` — фича,
> тесты 5144; `a477747` — fix scripts standalone sys.path bootstrap + CLI-тест,
> тесты 5145; `772db08` — docs деплой-верификация; поверх `da85b60` — docs
> memory-sync 10.9; прод до деплоя — `d2d1215` = задеплоенный 10.9).
> Единственная фича **`admin-ui-round1010`** (spec @Architect + tasks @PM +
> ADR-1010-1/2/3; T-1315…T-1328) реализована целиком: (1) header fullscreen
> padding — `max(env(safe-area-inset-*), --tg-content-safe-area-inset-*,
> --tg-safe-area-inset-*)`, профиль-блок не перекрывается нативными кнопками;
> (2) мобильный график доступности ключей — окно строится ОТ КОНЦА, новейшие
> сэмплы не отбрасываются, дорожки на провайдера + временная сетка 300с (min 12
> бакетов), адаптивная высота, `api_payload` не изменён; (3) «Провайдеры» —
> реальные значения полей через `blockFieldValue` (`:value`+`@input`), секреты
> замаскированы; (4) ЛС heavy-modules OFF — `scripts/disable_dm_heavy_modules.py`
> (идемпотентный; dry-run/`--apply`/`--restore`/`--chat-id`/snapshot) + new-DM
> defaults OFF (сон/ностальгия/саммаризация; F-14 gate не тронут); (5) «Роли» —
> аватар+ник+мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
> fail-open, транзиентные ошибки не кэшируются), ширины w-24/flex-1 min-w-0/
> shrink-0. **Каталог 400 / 90 / 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL,
> SQLite v8, `bot.py`/`media/`/`.env` не тронуты. @Reviewer: REJECTED (график
> отбрасывал новейшие данные) → fix → APPROVED WITH MINOR ISSUES → restore
> exit-code Low закрыт. @Scanner: **0 blocker / 0 major / 0 medium** (low
> R10.10-1/-2/-3 + info R10.10-4/-5; большинство закрыто;
> `plans/reports/round10.10_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§31** (+§3/§9/§25). **Тесты: 5145 passed / 1 skipped /
> 0 failed** (baseline 10.9 = 5105; Scanner 5140 + 1 skipped на момент аудита);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round1010/` (spec.md + tasks.md + ADR-1010-1/2/3.md);
> **plans/archive/ — 32 папки**; plans/features/ — 6 активных F-1…F-6.
> @DevOps: README 5145 + `APP_VERSION` **2.54.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, restart active, `/api/health` 200, 0 ошибок; **DM data-run применён**
> (1 активный ЛС; snapshot `var/dm_modules_off_snapshot_20260911T201219Z.json`;
> повторный dry-run 0). Граф обновлён: милстоун `round10.10-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN
> plans-structure, создан `tech-debt-round10.10` (R10.10-1..-5). **Осталось
> вручную:** live Android QA — T-1317/1320/1323/1332; UI spot-check DM-тумблеров
> OFF (T-1328). ⚠️ П.6 Headroom (saved-tokens stats, внешняя IDE-инфраструктура) —
> **вне скоупа проекта**, в репозитории/графе не фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.11 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `cbe6ea5`** (`3624789` — фича,
> 28 файлов, тесты 5172; `cbe6ea5` — docs деплой-верификация; поверх `ec5dd1f` —
> docs memory-sync 10.10; прод до деплоя — `772db08` = задеплоенный 10.10).
> Единственная фича **`llm-providers-refactor-round1011`** (spec @Architect + tasks
> @PM + ADR-1011-1/2/3; T-1340…T-1381) реализована целиком: (п.1) `POST /api/llm/test`
> резолвит SAVED-ключ блока server-side при пустом `api_key` (R17-safe: `_BLOCK_SAVED_KEY`,
> `_saved_api_key` = `hot.get(pg_key, settings_default)`, явный draft приоритетнее, ключ
> не в `_result`/логах; UI mask+hint `{configured,last4}`) — работает без повторного ввода;
> (п.2) рефакторинг «LLM Провайдеры» — nav-icons 22px/gap .15rem/min-width 60px + pinned
> профиль; две зоны «Подключения»/«Расширенные настройки» (**computed**, не methods);
> embeddings — один блок с 3 подблоками (main/f1/f2) с полными полями base/model/key/
> «Проверить»; video fallback поднят сразу после `video_summary_openrouter`; media-share/
> search_keys/llm_guard → advanced внизу с human-subtext; теххаос внизу; (п.3) dashboard
> key-history — непрерывный график (`spanGaps:true` + `stepped:true`, линейная ось X в ms,
> `parsing:false`, ticks HH:MM; `type:'time'` НЕ используется), серверный контракт
> `api_payload`/`key_history.py` НЕ изменён; (п.4) docs-only отчёт
> `plans/docs/memory_sleep_nostalgia_lore_report.md` (память, сон/синтез снов, ностальгия,
> лор чатов, тайминги/лимиты, сборка контекста — plain language, каждая цифра `file:line`).
> **Каталог-дельта (ADR-1011-2, sanctioned):** 4 infra embed-fallback записи перенесены
> в каталог (`models.embedding_fallback_base_url/_model` → models/`models_embeddings`;
> `keys.embedding_fallback_api_key/_2` → keys/`keys_llm`, `secret=True`), `llm_client`/
> `status_service` читают `hot.get`; счётчики БЕЗ роста — REGISTRY **400** / GROUPS **90** /
> Settings **372** / mapped **88** / `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19; `categorized`
> 372→**376** (models 40→42, keys 13→15), `infra` 28→**24**. Ноль PG-DDL; SQLite v8;
> `bot.py`/`media/`/`.env` не тронуты. @Reviewer: REJECTED (CRITICAL: zone helpers в methods,
> не computed → блоки провайдеров исчезали) → фикс (computed) → APPROVED WITH MINOR ISSUES.
> @Scanner: **CLEAN — 0 blocker / 0 major / 0 medium** (3 low R10.11-1/-2/-3 закрыты
> follow-up; 3 info R10.11-4/-5/-6 → техдолг; `plans/reports/round10.11_scanner_audit.md`).
> @Architect: merge в `plans/ARCHITECTURE.md` **§32** (+§5/§9/§25). **Тесты: 5172 passed /
> 0 failed** (baseline 10.10 = 5145; Scanner 5168 на момент аудита — до follow-up
> R10.11-1/-2/-3); `node --check web/app.js` clean; `node tests/js/routing_test.js` →
> `JS-UNIT-OK`; `git diff --check` чист; R17-скан чист. @PM: фича заархивирована —
> `plans/archive/llm-providers-refactor-round1011/` (spec.md + tasks.md + ADR-1011-1/2/3.md);
> **plans/archive/ — 33 папки**; plans/features/ — 6 активных F-1…F-6. @DevOps: README +
> `APP_VERSION` 2.54.0→**2.55.0**; коммиты `3624789` (feat, 28 файлов) + `cbe6ea5` (docs
> deploy-verification); push origin/master; **деплой 198.46.175.136:/var/www/admin_bot** —
> git pull fast-forward `772db08..3624789`, миграция `migrate_env_to_pg --only-category
> models,keys` **created=5 / skipped=48**, restart active, `/api/health` 200, 0 ошибок.
> Граф обновлён: милстоун `round10.11-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан `tech-debt-round10.11`
> (R10.11-4/-5/-6; R10.11-1/-2/-3 закрыты). **Осталось вручную:** live Android/Telegram QA
> (**T-1377** — поле ключа + «Проверить» без повторного ввода, навигация/профиль/сетка,
> две зоны, эмбеддинги, video-фоллбэк, media-share, график; статически покрыто
> `tests/test_webapp_round1011_ui.py` + JS-юниты). ⚠️ Наблюдение: pre-restart PID имел
> 401 к `apinet.cloud` (возможно невалидный primary token) — стоит проверить.
> ⚠️ Headroom — вне репозитория, как сущность НЕ фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 13.09.2026: раунд 10.12 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `bad2b0d`** (`708f7df` — фича,
> 39 файлов, тесты 5211; `bad2b0d` — docs деплой-верификация; поверх `32d1aa9` —
> docs memory-sync 10.11; прод до деплоя — `cbe6ea5` = задеплоенный 10.11).
> Единственная фича **`providers-kostik-round1012`** (spec @Architect + tasks @PM +
> ADR-1012-1): (п.1) эмбеддинги развязаны от прямых ответов — новый
> `models.embedding_base_url` (PG-значение `https://apinet.cloud/v1`) +
> `keys.embedding_api_key` (OD-1; пусто → рантайм-фолбэк на llm-ключ);
> `models.llm_base_url` = `https://nano-gpt.com/api/v1`; отдельный read-path +
> отдельный кэш httpx-клиента (`_embed_client`); `.env` обновлён на проде
> (`LLM_BASE_URL=nano-gpt/api/v1`, `EMBEDDING_BASE_URL=apinet.cloud/v1`); (п.2) фикс
> 422 — глобальные (`per_chat=false`) ключи сохраняются в global-скоуп (без
> chat-скоупа) в `saveConfigItem`/`saveBlock`/`saveKeyItem`; серверный гейт + DM
> read-only не ослаблены; (п.3) блоки подключений объединены/переименованы с
> display-name подписями в шапке, OpenRouter display-name разделён (STT vs видео),
> свопа транскрибация/саммаризация нет (проверено); (п.4) Костик — JSON-параметр
> `reactions.kostik_replies` (14 фраз: 4 владельца + 10) + плотный list-editor +
> `flags.kostik_enabled` (default true) + новый PERMsoc-блок Костика; handler
> безопасен при пустом списке; `limits.kostik_reply_probability` (0.1) сохранён.
> **Каталог (sanctioned Δ +5, ADR-1012-1):** REGISTRY **405** / GROUPS **90** /
> Settings **377** / mapped **88** / `categorized` **381** (models 42→44, keys 15→16,
> flags 58→59, reactions 38→39); TAB_RULES 19. Ноль новых PG-DDL; SQLite v8;
> `bot.py` router order не тронут (только DI-kwargs `embed_base_url`/`embed_api_key`
> в 4 точках); `media/`/`.env` (git) не тронуты. @Reviewer APPROVED WITH MINOR ISSUES
> (дефекты 1–4 закрыты); @Scanner **CLEAN — 0 blocker / 0 major / 0 medium**
> (2 low R10.12-1/-5 закрыты follow-up; 3 info R10.12-2/-3/-4 → техдолг;
> `plans/reports/round10.12_scanner_audit.md`); @Architect merge в `plans/ARCHITECTURE.md`
> **§33** (+§5/§9/§12/§25). **Тесты: 5211 passed / 0 failed** (baseline 10.11 = 5172);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/providers-kostik-round1012/` (spec.md + tasks.md + ADR-1012-1.md);
> **plans/archive/ — 34 папки**; plans/features/ — 6 активных F-1…F-6. @DevOps: README +
> `APP_VERSION` 2.55.0→**2.56.0**; коммиты `708f7df` (feat, 39 файлов) + `bad2b0d` (docs
> deploy-verification); push origin/master; **деплой 198.46.175.136:/var/www/admin_bot** —
> git pull fast-forward `3624789..708f7df`, миграция `migrate_env_to_pg`
> **created=5 / skipped=149**, restart active, `/api/health` 200, 0 ошибок. Граф обновлён:
> милстоун `round10.12-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан `tech-debt-round10.12`
> (R10.12-2/-3/-4; R10.12-1/-5 закрыты), `round10.12-epic FOLLOWS round10.11-epic`.
> **Осталось вручную:** live Android/Telegram QA; опционально задать выделенный
> embedding api key. ⚠️ Headroom — вне репозитория, как сущность НЕ фиксируется.

> **Step 0 recon 13.09.2026 (раунд 10.13 — «Рефакторинг Памяти, Сна и Дашборда
> Интеллекта»):** HEAD == origin/master == `ce25dc7`, дерево ЧИСТОЕ, APP_VERSION
> 2.56.0, pytest **5210/0**, каталог **405/90/377/88** (TAB_RULES 19). Новый эпик
> `plans/current_task.md` (пп.1–10) пересёк memory/RAG/сон/ностальгию/лор/провайдеров/
> TMA. **Ни один пункт 1–10 не реализован**; есть фундамент (см. ниже).
> **Уже есть (не переделывать):** (1) `build_rag_context`/`_format_origin_labeled_line`
> (`services/summary_memory.py:676,681-710`) — факты уже с метками origin и датой
> `[ГГГГ-ММ-ДД]` (нет автора и пометки устаревания); (2) GraphRAG v2 + vec/int8-KNN +
> MMR + `dig_into_lore`; (3) `DreamWorker` (окно 4–6 local, тик 60м, бюджеты,
> beliefs `derived_belief`/kind=belief, weight 0.6, вечные) + `NostalgiaWorker`
> (слои A/B) + `LoreWorker` + `CheckupService`/`memory_health.py`/`worker_budget.py`;
> (4) provider-модель `PROVIDER_BLOCKS` parent+`subBlocks` (10.11/10.12),
> `providerCoveredKeys`, `_BLOCK_SAVED_KEY`/`KNOWN_BLOCKS` (`services/llm_probe.py`);
> (5) вкладки «Память»/«Сон»/«Ностальгия» (10.4-фича C), мини-блоки dream/nostalgia
> в TMA, «Бюджет фона (день)» в «Сводке» (10.9), `web/api/memory_agi.py`;
> (6) старый линейный график аптайма (`web/index.html:2713-2718` +
> `services/uptime_heartbeat.py`) — его заменяет п.8; key-history график (10.11) —
> ДРУГОЙ, не путать; (7) технический отчёт `plans/docs/memory_sleep_nostalgia_lore_report.md`
> (10.11) — сырьё для п.10, но новый `intelligence_user_guide.md` пишется с нуля.
> **Исторические конфликты/запреты:** комбинированного тега `ERROR+WARNING` и
> `chat_memes`/`archived_belief`/`paradigm`/`deep sleep`/force-directed graph в коде
> НЕТ (greenfield); `logLevel:'INFO'` (`web/app.js:860`) + один `level` в
> `/api/status/logs` — п.9 меняет контракт фильтра (нужен учёт тестов);
> beliefs сейчас вечные и подаются как обычные факты — п.4 меняет read-path
> контекста (регресс-риск); инварианты 10.11/10.12 в силе: **ноль новых PG-DDL,
> SQLite v8, `bot.py` router order не трогать** (только DI-kwargs), `media/`/`.env`
> не трогать, **R17** (секреты только `{configured,last4}`), каталог-счётчики
> обновлять осознанно с тестами, новые provider-блоки — в формате parent+subBlocks
> (+`providerCoveredKeys`/`_BLOCK_SAVED_KEY`, иначе generic-дубли/непроверяемые
> ключи). **Открытые Critical/High из Scanner — НЕТ:** 10.10/10.11/10.12 =
> 0 blocker/0 high/0 medium; открыт low R10.12-1 (`saveKeyItem` не на global-save →
> 422 для `keys.*` вне provider-блоков) — релевантен п.3, если новые ключи пойдут
> отдельными блоками; техдолг info R10.11-4 (probe base_url hardening), R10.12-2/-3/-4.
> **Рекомендация @PM:** 6–7 фич — F1 backend 4D-память+сон-группировка (п.1);
> F2 backend «Сон v2»: Belief Decay + Resurrection (п.4+4.1); F3 backend
> «Глубокий сон»: мета-синтез/якоря/парадигмы (п.6) + LLM-роутер фоновых воркеров
> (п.3, backend); F4 frontend «Провайдеры»: 2 новых блока (п.3, UI); F5 frontend
> «Cognition»: дашборд+граф+виджет Сводки (п.5+п.7); F6 frontend: EKG + логи (п.8+п.9);
> F7 docs: user guide + README (п.10). Дробить п.4.1 на 3 подзадачи (резонанс/
> Реаниматор/граф-активация). Зависимости: F1→F2→F3; F4∥F3; F5 зависит от API
> F2/F3/F6. Граф обновлён: `Epic: Cognition-Sleep-Memory Refactor round1013`.
>
> **Синк STEP 2 (Architecture, @Architect) 13.09.2026 (раунд 10.13):** эпик
> ЗААРХИТЕКТИРОВАН — 8 фич, во всех папках `plans/features/cognition-*-round1013/`
> созданы `spec.md` (🟣 SPEC_READY) + `tasks.md` (T-1417…T-1476) + 3 ADR:
> `adr-1013-1-provider-keys.md` (F4/F3 — единые ключи `models.intel_<role>_*` /
> `keys.intel_<role>_api_key`), `adr-1013-2-graph-library.md` (F5 — vis-network
> standalone UMD, self-host, lazy-load), `adr-1013-3-prompt-canon-policy.md`
> (F1 — модульные каноны dream/lore/dossier: PREV-snapshot + байт-тесты,
> `PROMPT_MIGRATIONS` НЕ трогаем). Список спек: **F1** `cognition-4d-memory-round1013`,
> **F2** `cognition-belief-decay-round1013`, **F3** `cognition-deep-sleep-round1013`,
> **F4** `cognition-llm-providers-round1013`, **F5** `cognition-dashboard-round1013`,
> **F6** `cognition-ekg-logs-bugfix-round1013`, **F7** `cognition-user-guide-round1013`,
> **F8** `cognition-irony-dossier-round1013`. Граф: милстоун `round1013-epic-cognition`
> → ARCHITECTED; epic `Epic: Cognition-Sleep-Memory Refactor round1013` обновлён.
>
> **Синк STEP 3 (Intent, @Memory) 13.09.2026 (раунд 10.13):** Human Gate пройден,
> решения подтверждены пользователем. **Подтверждённые решения:** F5 — vis-network
> (standalone UMD, self-host, lazy-load); F3/F4 — роли выделенных LLM
> `intel_history` (Историческая память/Лор) и `intel_bg` (Фоновые проверки/важность),
> при пустых значениях фоллбэк на `models.llm_*`/`keys.llm_api_key`; F8 — Досье через
> существующий `LoreWorker` + `build_persona_card` (новый воркер НЕ создаём),
> мемы = `graph_facts.status='chat_meme'`; архив убеждений =
> `graph_facts.status='archived_belief'`; парадигмы =
> `origin='derived_belief' + belief_meta.type='paradigm'`, weight 0.55.
> **Ключевые DDL-free решения:** `graph_facts.kind` имеет CHECK (`fact`/`belief`) →
> третий kind запрещён (был бы PG-DDL); `graph_facts.status` БЕЗ CHECK → архив/мемы/
> парадигмы кодируются колонкой `status` + JSON `belief_meta`; ноль новых PG-DDL,
> SQLite остаётся v8. **Каталог-Δ:** 405→427 (Settings 377→399), categorized
> 381→403, GROUPS 90, mapped 88, TAB_RULES 19 неизменны. **Флаги (default OFF):**
> `flags.belief_decay_enabled`, `flags.deep_sleep_enabled`,
> `flags.irony_filter_enabled`.
> **Порядок:** F1→F2→F3→F5 (цепочка данных/API); F4 ∥ F3 (RELATED_TO, общий роутер
> `LLMClient.generate_worker` и ключи `intel_*`); F6 и F8 — параллельны основной
> цепочке; F7 — последняя. **Узлы графа:** 8 фич (PART_OF `round1013-epic-cognition`,
> `AdminBot HAS_PLAN`) + 7 компонентов (`DeepSleepWorker`, `LLMClient.generate_worker`,
> `BeliefDecayService`, `CognitionDashboard`, `EKGHeartbeat`, `IronyPromptFilter`,
> `plans/docs/intelligence_user_guide.md`). Статус милстоуна →
> ARCHITECTED + INTENT_SYNCED. Следующий шаг — @Builder (Step 4) по `spec.md`;
> инварианты: ноль PG-DDL, SQLite v8, порядок роутеров `bot.py` (только DI-kwargs),
> R17 (секреты `{configured,last4}`), R16 (id-не-имя).
>
> **Синк STEP 10 (финал, post-commit+деплой) 13.09.2026: раунд 10.13 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `8800bba`** (`8800bba` — feat
> раунда, 8 фич F1–F8, 60 задач T-1417…T-1476, тесты 5392; поверх `ce25dc7` —
> docs memory-sync 10.12; прод до деплоя — `708f7df` = задеплоенный 10.12).
> **8 фич** (все COMPLETED): **F1** `cognition-4d-memory-round1013` — префикс
> `[ММ.ГГГГ \| Автор: ]` + метка `(Внимание: возможно устарело)` >6 мес + временная
> группировка фактов в Сне; **F2** `cognition-belief-decay-round1013` — decay −0.1/мес,
> архив `graph_facts.status='archived_belief'`, Resurrection (векторный резонанс
> 0.78/−0.3, Сон-Реаниматор, граф-активация); **F3** `cognition-deep-sleep-round1013` —
> «Глубокий сон» (якоря → «Мост времени» → парадигмы `origin='derived_belief'`
> weight 0.55) + роутер `LLMClient.generate_worker`; **F4**
> `cognition-llm-providers-round1013` — 2 provider-блока `intel_history`/`intel_bg`
> (parent+subBlocks, фоллбэк на llm-ключ); **F5** `cognition-dashboard-round1013` —
> дашборд «Осмысление» + виджет «Интеллект и Память» + граф vis-network
> (nodes/edges 120/240, polling 15с); **F6** `cognition-ekg-logs-bugfix-round1013` —
> SVG-EKG (Load/CPU/RAM) + багфикс «Логи» (серверный тег ERROR+WARNING, дефолт
> фильтра); **F7** `cognition-user-guide-round1013` — `plans/docs/intelligence_user_guide.md`
> (без жаргона) + README; **F8** `cognition-irony-dossier-round1013` — ироничный промпт
> Досье + мемы `graph_facts.status='chat_meme'` + блоки [Факты]/[Локальные мемы/Ярлыки].
> **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (BLOCKER-1 [Critical] T-1439 —
> роутер воркеров не подключён; BLOCKER-2 [High] — ностальгия F5) → итерация 2 —
> **APPROVED**; @Scanner итерация 1 — 0 Critical / 1 High / 4 Medium / 9 Low → итерация 2 —
> **CLEAN 0/0/0** (закрыты High S10.13-1 и Medium S10.13-2/-3/-4/-5), остаются **5 Low**
> (техдолг); @Builder — **2 цикла реворков** (после Reviewer Rejected и после Scanner High).
> Источники — `plans/reports/round10.13_reviewer.md` + `plans/reports/round10.13_scanner_audit.md`.
> **Архитектура:** `plans/ARCHITECTURE.md` **§34** + `ADR-1013-1` (provider keys
> `models.intel_<role>_*`/`keys.intel_<role>_api_key`), `ADR-1013-2` (vis-network
> standalone UMD self-host lazy-load), `ADR-1013-3` (prompt canon policy — модульные
> каноны dream/lore/dossier, `PROMPT_MIGRATIONS` не трогаем). @PM: 8 фич заархивированы —
> `plans/archive/cognition-*-round1013/` (spec.md + tasks.md + 3 ADR); **plans/archive/ —
> 42 папки**; plans/features/ — 6 активных F-1…F-6. **Тесты: 5392 passed / 0 failed**
> (база 10.12 = 5211 → **+181**); `node --check web/app.js` clean; `node tests/js/routing_test.js`
> → `JS-UNIT-OK`; `git diff --check` чист. **Каталог:** REGISTRY **427** / Settings **399** /
> `categorized` **403** / GROUPS 90 / mapped 88 / TAB_RULES 19 (санкционированный Δ
> ADR-1013-1 + флаг F8). **Инварианты:** ноль новых PG-DDL, SQLite **v8**, порядок
> роутеров `bot.py` не тронут (только DI-kwargs), R17-скан чист, F7-гайд без запрещённого
> жаргона (grep 0), новых `v-html`/CDN нет. **Флаги default OFF:** `flags.belief_decay_enabled`,
> `flags.deep_sleep_enabled`, `flags.irony_filter_enabled`. **Деплой @DevOps:** README +
> `APP_VERSION` 2.56.0→**2.57.0**; коммит `8800bba`; push origin/master `ce25dc7..8800bba`;
> **деплой 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `708f7df..8800bba`,
> restart active (running) PID 1629874, `/api/health` = 200 `{"status":"ok"}`, рабочее дерево
> чистое; `.env` на проде не редактировался (новые ключи — безопасные дефолты, флаги OFF).
> **Техдолг Low (открыт, не блокеры):** `S10.13-9` / `-11` / `-13` / `-14` / `-6b` — KG
> `tech-debt-round10.13`; `plans/reports/round10.13_scanner_audit.md` §5. Граф обновлён:
> милстоун `round1013-epic-cognition` → COMPLETED + DEPLOYED, 8 фич → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure (PART_OF/ARCHITECTED удалены),
> создан `release-v2.57.0-round1013`, `round1013-epic-cognition FOLLOWS round10.12-epic`,
> `plans/metrics.md` создан. **Остаточно (не блокеры):** betterstack_handler WARNING 401
> (внешний LOGTAIL_SOURCE_TOKEN, вне раунда); ручной live Android/Telegram QA.
>
> **Раунд 10.3 (F-13/F-14/F-15) завершён и заархивирован** — см. раздел
> «Раунд 10.3 — финал (09–10.09.2026)» ниже; их спеки — в `plans/archive/`
> (`tma-chat-selector-fixes`, `dm-user-settings`, `direct-sandbox-budget-investigation`).

## Раунд 10 — ЗАВЕРШЁН, закоммичен и ЗАДЕПЛОЕН (07.09–08.09.2026, HEAD 533bf13; статус: done+deployed)

«Multi-chat scaling (Variant A)» по `plans/docs/multi-chat-scaling-research.md`: 6 фич,
82 задачи T-843…T-924 (нумерация продолжает T-842). spec.md @Architect (закрывает
Q-протоколы раздела A tasks.md), tasks.md @PM. **Итог (08.09.2026): полный pytest
4717 passed / 0 failed (+155; подтверждён прогоном — 54.46s, 1 StarletteDeprecationWarning),
аппрув @Reviewer PASS, `git diff --check` чист; все 6 фич заархивированы
(@PM Archive Phase), архитектура — `ARCHITECTURE.md` §22, backlog.md — «✅ Выполнен
и заархивирован (08.09.2026 @PM, HEAD fac1b9f, tests 4717)».** После финала —
**коммит `69be94e` (фича, 89 файлов, +8932/−216) + фикс `533bf13` (DSN, 2 файла),
push origin/master, прод-деплой — см. «Раунд 10 — закоммичен и задеплоен» ниже.**

| Фича | Задачи | Скоуп |
|---|---|---|
| `multi-chat-rbac-byok` (F-7) | T-843…T-869 (27) | Часть 1 — фундамент раунда: роли Global/Local/Moderator/User/Custom (`bot_roles.role_type`, `services/roles.py` ROLE_RANK), `services/access.py::access_for`, таблица `param_permissions` (view/edit_min_role+hidden_from_local, DEFAULT_MATRIX в коде), `chat_profiles.chat_params` JSONB {v:1, overrides, gates, keys:{allow_global}, perm_overrides, meta} + резолв `hot_chat` chat_params→bot_settings→дефолт (409 по updated_at, NOTIFY, кэш 120с), BYOK `chat_keys` + бюджет `chat_usage` + `limits.chat_global_key_budget_*` + sandbox `content.no_key_reply`, `resolve_api_key(chat_id)` в llm_client, API `/api/access/*` + X-Chat-Id в /api/config |
| `tma-ui-fixes` (F-8) | T-870…T-877 (8) | Часть 3.2 — 8 UI/UX-фиксов TMA: flex-шапка 380px (T-870), логи `<pre><code>` 0.75rem (T-871), relations Alias→nickname→username→id + аватар-фолбэк (T-872), title чатов вместо -100… (T-873), чип «авто» (T-874), компактные стадии+note (T-875), Telegram ID админа → «Доступы» (T-876), регресс-аудит (T-877). Только web/*, без API/БД-изменений |
| `permsoc-module-isolation` (F-9) | T-878…T-889 (12) | Часть 2.1 — `services/permsoc.py` (реестр 5 модулей: slavik/kostik/alan/olya/mimic) + `PermsocGateFilter` (гейт на уровне фильтра, порядок роутеров bot.py НЕ меняется); master `flags.permsoc_enabled` default false + `chat_params.gates.permsoc`; под-флаги olya/mimic/alan через hot_chat; новые чаты OFF, живые — бэкфил `scripts/backfill_permsoc_gates.py` (ON для -1002661910336/custom-профилей) |
| `feature-gates-worker-budget` (F-10) | T-890…T-902 (13) | Части 2.3+2.4 — жёсткий Opt-In: `gates_opt_in` колонка + gates в `chat_params.gates` (dream/nostalgia/lore_auto/permsoc), `services/feature_gates.py::set_feature_gate` единый write-path; бюджет-ледежер `worker_budget` в PG (day/scope/metric/used; WORKER_BUDGET_TZ=Asia/Yekaterinburg), `services/worker_budget.py::consume`, лимиты `limits.worker_daily_*`, деградация nostalgia→lore→dream, jitter ≤ interval/3, fail-open; API GET/PUT gates + GET /api/workers/budget |
| `tma-ia-progressive-disclosure` (F-11) | T-903…T-913 (11) | Части 2.2+3.1 — MENU_ORDER (Главная/Чат-Профиль/Модули и Фичи/Настройки AI/Доступы и Роли), новая вкладка `modules_feats`, вход Oversight (F-12); селектор чатов `GET /api/access/chats` + X-Chat-Id + localStorage active_chat_id; `progressive_level` (RAG/k/vector/timeout/context/budget → advanced) + нативный `<details>` аккордеон + adminbot.expand; user → read-only (только Статус/Как это работает) |
| `global-oversight-dashboard` (F-12) | T-914…T-924 (11) | Часть 3.1 — `services/oversight.py::build_summary` → `ChatSummary` (гейты/opt_in/key_status/admins_count/last_active_ts/budget; кэши 60-120с, без новых таблиц), kill-switch через `set_feature_gate`, запрет глобального ключа `chat_params.keys.allow_global=false`, API GET /api/oversight/summary|chat/{id} + POST killswitch/global_key, `requires_global_admin` (deps.py), зверю-таблица + модалка в TMA |

Взаимозависимости: F-7 — фундамент (chat_params/RBAC/chat_keys/X-Chat-Id/params-meta);
F-9 и F-10 пишут в `chat_params.gates` через единый патч-метод F-7 `set_chat_params`;
F-11 и F-12 построены поверх F-7/F-10; F-8 — независимый UI-фикс-слой.
**Все 6 фич раунда 10 (F-7…F-12) — archived** (`plans/archive/<feature>/{spec.md,tasks.md}`);
plans/features/ — снова 6 старых активных (F-1…F-6).

### Финал раунда — ключевые факты

- **Фиксы по ревью:** R1 (chat-scope EDIT требует chat-грант local_admin|moderator
  этого чата или global-ранг — `access.py::can_edit_param`), R6 (per-call BYOK-резолв
  `_resolve_api_key_and_source(chat_id)` без `_byok_chat_id`-инстансного стейта),
  S1–S3 (config-глобальный путь по ролям; `_mask_key_for_role` — `{configured,last4}`
  глобального только global-admin; модератор/юзер без chat-гранта — read-only);
  R17 — raw-ключи никогда не логируются/не отдаются.
- **Девиансия M-F-9 (08.09.2026, вариант (а)):** alan — master-only; `reactions.alan_mimic_enabled`
  остаётся легаси-выключателем common-мимикрии на Леху (нужны ОБА флага), в реестр модуля не входит
  (обоснование: прод-сид False выключил бы живое приветствие Лехи после бэкфила master ON).
- **RUNTIME WARNING соблюдён:** SQLite остаётся v8 (новых миграций нет — только идемпотентные
  PG-DDL: `bot_roles.role_type`, `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`,
  ALTER `chat_admins`/`chat_profiles`/`chat_lore_history`-CHECK); порядок роутеров bot.py,
  `hot.get`/ConfigCache, LEGACY/PREV-каноны — без дифов.
- **Каталог:** REGISTRY 372→**383** (limits +9 в т.ч. `limits_worker` 7 + chat_global_key_budget_*,
  flags +1 `permsoc_enabled`, content +1 `no_key_reply`); группы 70→**71**; Settings 349→**359**.
- **DevOps runbook ВЫПОЛНЕН (08.09.2026):** PG-DDL прогнан (`[pg_db] DDL ok`, 8 таблиц),
  роли засеяны (admin/moderator/user/local_admin), `scripts/backfill_permsoc_gates.py` success
  (gates.permsoc=True), `scripts/backfill_feature_gates.py` success (chat=-1002661910336:
  dream=False, lore_auto=True, nostalgia=False, opt_in=True); live-верификация — post-deploy
  journal чист (без Traceback/ERROR/CRITICAL, только пре-существующий betterstack/Logtail 401).
- **Известные follow-up (вне раунда):** тест-гап `backfill_permsoc_gates.py` (нет прямых
  unit-тестов бэкфила — только детерминированное правило), проверка имени CHECK-ограничения
  `chat_lore_history` на проде (field='gates'/'chat_keys' — DDL-имя под live-верификацию),
  предложение расширения `deploy_v2.9.2.py` (шаблон деплоя: DDL + бэкфилы + live-гистограммы).

### Раунд 10 — закоммичен и задеплоен (08.09.2026)

- **Коммиты (master):** `69be94e` feat(admin,web,chat): Multi-Chat раунд 10 — RBAC и BYOK
  (chat_params-слой, param_permissions), PERMsoc-изоляция, фичи-гейты и бюджет воркеров, TMA
  (5 секций, прогрессивное раскрытие, Oversight), UI-фиксы + docs(readme) (тесты 4717)
  — 89 файлов, +8932/−216; `533bf13` fix(scripts): бэкфиллы раунда 10 — DSN из
  os.getenv(POSTGRES_DSN) вместо несуществующего settings.POSTGRES_DSN (деплой: AttributeError,
  pg_db-резолв) — 2 файла.
- **Пуш:** origin/master; local master HEAD == origin/master ==
  `533bf13f421025dc3c9c900bd0fc798d0236521a`.
- **Деплой (198.46.175.136:/var/www/admin_bot):** `git pull` fast-forward до 533bf13; .env без
  изменений (только API_TOKEN — новых переменных не требуется); `systemctl restart admin_bot` OK
  (старый процесс — SIGKILL по таймауту, пре-существующее поведение; новый инстанс чист);
  status active (running), PID 133710.
- **Прод-состояние:** `[pg_db] DDL ok` (8 таблиц); роли засеяны (admin/moderator/user/local_admin);
  `backfill_feature_gates.py` done (chat=-1002661910336: dream=False, lore_auto=True,
  nostalgia=False, opt_in=True); `backfill_permsoc_gates.py` done (gates.permsoc=True);
  post-deploy journal чист (без Traceback/ERROR/CRITICAL).
- **README.md:** строка версии — тесты 4717, бейдж «Раунд 10», новый раздел «Multi-Chat, RBAC
  и BYOK (раунд 10)», TMA-таблица перестроена (5 секций меню), +3 пункта «Известные нюансы».
- **Follow-up (известные):** betterstack/Logtail 401 в journal — LOGTAIL_SOURCE_TOKEN невалиден
  в .env (пре-раунд-10, не регрессия); graceful-stop SIGKILL по таймауту (пре-существующее
  поведение); plans/MEMORY.md untracked намеренно (в коммиты раунда не входит).

### Хотфикс 10.1 — закоммичен и задеплоен (08.09.2026)

Post-deploy багфиксы TMA по рекону `recon: tma-round10-postdeploy-bugs` (БГ1–БГ4).
- **Коммит (master):** `8eae899` fix(admin,web): TMA хотфикс 10.1 — пустые вкладки
  (basicItems/advancedItems), логи (сверху свежие, клик-копия, шрифт 0.7rem), лор (ленивые
  аватары, каскад имён, скролл/фулскрин), Модули и Фичи (бюджет всегда) + docs(readme)
  (тесты 4726) — 8 файлов, +436/−151, поверх `533bf13`; local HEAD == origin/master ==
  `8eae8992a55a9a09255c345018d909759121a04b` (подтверждено git rev-parse).
- **Фиксы (review PASS, миноры закрыты):** (1) пустые конфиг-вкладки — реализованы
  `basicItems`/`advancedItems`, прогрессивное раскрытие Basic/Advanced работает (БГ1);
  (2) логи — `scrollTop=0` (сверху свежие), клик по строке = копирование, off-screen
  textarea-фолбек, шрифт `.log-code` 0.70rem (БГ2); (3) лор — обогащение топ-50 (было топ-30),
  ленивые аватары 300ms stagger, каскад имён alias→nickname→username→id (порядок — минор
  ревью), высоты панелей + fullscreen-mode (БГ3); (4) Модули и Фичи — бюджет виден всегда
  (без выбранного чата), плейсхолдеры + optInCount, master-тумблер disabled без чата (БГ4);
  миноры ревью: template filter → methods, lazy-фильтр исключает топ-50.
- **Тесты:** 4726 passed / 0 failed (4717 + 9 новых в 4 test_webapp-файлах).
- **README.md:** «Тестов: 4726 | Раунд: 10 (хотфикс 10.1 — TMA снова открывается)»,
  абзац «Хотфикс 10.1 — бот взял себя в руки», счётчик раундов +9.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 8eae899; .env БЕЗ изменений
  (API_TOKEN присутствует; PERMSOC_ENABLED/WORKER_* не нужны — работают дефолты);
  restart OK; active (running) PID **159455**, since 2026-09-07 16:27:04 UTC; journal чист
  (DDL ok, polling, webapp lifespan, без Traceback/CRITICAL).
- **Follow-up: НОВЫХ НЕТ.** Пре-существующие (не регрессия): betterstack/Logtail 401
  (LOGTAIL_SOURCE_TOKEN невалиден), graceful-stop SIGKILL-after-timeout.

### Раунд 10.2 — фиксы (09.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d30b203)

По рекону `recon: tma-bugs-7-post-10.1` (7 багов TMA от юзера; bug 8 — диск
сервера, DevOps вне кода). HEAD == origin/master == `d30b203` (был 8eae899).

- **Статус: COMPLETED + DEPLOYED.** Коммит + пуш + деплой выполнены 09.09.2026
  (см. «Раунд 10.2 — финал» ниже). планы-док plans/MEMORY.md остаётся
  untracked намеренно.
- **Фиксы (все 7 закрыты):**
  (1) селектор чата всегда виден для админов + кнопка/дропдаун «Выбрать чат»
  в шапке и empty states (`bug: tma-chat-selector-hidden`);
  (2) сайдбар скроллится — md:sticky md:h-screen md:overflow-y-auto + mobile
  overflow-y:auto (`bug: tma-sidebar-noscroll`);
  (3) НОВАЯ вкладка «Функции PERMsoc» — группы каталога
  `flags_permsoc`/`reactions_admin`/`reactions_permsoc`, TAB_PERMSOC,
  TABS-зеркало с except-списками, master-карточка + бейджи модулей + сводка
  modules_feats; runtime `services/permsoc.py` не тронут (`bug: tma-nopermsoc-tab`);
  (4) аватары — транзиентные Bot API ошибки НЕ в негатив-кэш; каскад имён
  alias→nickname(очищенный)→username(без @)→id (`bug: tma-relations-names-avatars`);
  (5) пустые «(0)» секции скрыты — v-if advancedItems>0, группа v-if
  basic||advanced (`bug: tma-empty-advanced-accordion`);
  (6) права → FLAGS-модель {view_roles, edit_roles}: DEFAULT_MATRIX —
  keys `[]`/`[]`, prompts `[local_admin]`/`[local_admin]`, прочие
  `[moderator,local_admin]`/`[local_admin]`; legacy-нормализация;
  DELETE `/api/access/param_permissions/{key}` = сброс; модалка с
  чекбокс-строками + «Сбросить на дефолт»; глобальный админ имплицитно
  (`bug: tma-perm-flags-ui`);
  (7) clipboard-ghost — одно переиспользуемое скрытое textarea
  (`bug: tma-invisible-copy-field`);
  (8) код-часть фикса диска: MEMORY_BACKUP_KEEP дефолт 7→1 + hot-лимит
  `limits.memory_backup_keep`.
- **Файлы (26):** web/app.js, web/index.html, services/access.py,
  services/param_catalog.py, web/api/access.py, web/api/routes.py,
  web/api/chat_lore.py, web/api/avatars.py, services/memory_backup.py,
  config/settings.py; 12 тест-файлов (test_access, test_webapp_api,
  test_webapp_rbac_ui, test_chat_params, test_frontend_tab_mapping,
  test_param_catalog, test_webapp_nav_disclosure_ui, test_webapp_avatars_ui,
  test_webapp_tma_fixes_ui, test_relations_service, test_memory_backup,
  test_settings_helpers); 4 plans-дока (backlog.md «Ре-дизайн 10.2» +
  archive spec-ы multi-chat-rbac-byok / permsoc-module-isolation /
  tma-ia-progressive-disclosure).
- **Тесты: 4759 → 4760 passed / 0 failed** (финал подтверждён прогоном;
  +1 тест «ID никогда не отображается как имя»; ранее 4759 в .venv — 64.00s,
  1 StarletteDeprecationWarning пре-существующий). Только .venv: системный
  python/py не имеет `ijson` → collection error в test_history_loader/parser.
- **Замечание ревью (APPROVED):** имена отношений as-is — ID никогда не
  отображается как имя (никогда не показывать идентификатор); каскад имён
  alias→nickname raw→username(без @)→''; avatarInitial — графема.
- **Диск сервера (DevOps, уже исправлено на проде 09.09.2026):** освобождено
  ~5.8G (16G→10G used); бэкапы ротированы до 1 через `/root/bak/rotate_bak.sh`
  + root cron 03:10 daily; journal SystemMaxUse=200M; очищены /home/nik/.cache,
  /tmp, apt cache, btmp; главные подозреваемые — /var/www/admin_bot/backups
  (2.8G) + /home/nik/backups_adminbot (2.0G); migrate_history 1.1G — данные,
  не кэш (сохраняется); рекомендация fail2ban; `limits.memory_backup_keep=1`
  теперь применим через hot config. Виновник бэкапов — ежедневный VACUUM INTO
  после импорта истории.

### Раунд 10.2 — финал (09.09.2026)

- **Коммит (master):** `d30b203` fix(admin,web,api): раунд 10.2 — раздел
  «Функции PERMsoc», права-флаги (view/edit_roles), фиксы TMA (селектор чата,
  скролл сайдбара, пустые секции, копи-поле), имена отношений as-is (ID не
  имя), лимит бэкапов 1 + docs(readme) (тесты 4760) — **28 файлов, +1576/−314**,
  поверх `8eae899`; local HEAD == origin/master == `d30b203` (подтверждено
  git rev-parse); `git diff --check` чист.
- **Тесты:** 4760 passed / 0 failed (было 4759; +1 тест «ID никогда не имя»).
- **Ревью:** APPROVED (@Reviewer) — имена отношений as-is: ID никогда не
  отображается как имя; каскад alias→nickname raw→username(без @)→'';
  avatarInitial — графема.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до d30b203; бот
  active (running), PID **454654**; [pg_db] DDL ok; polling активен; webapp 200
  с разделом «Функции PERMsoc»; БЕЗ Traceback после рестарта; .env без
  изменений.
- **README.md:** тесты 4760, бейдж «Раунд 10.2», раздел «Функции PERMsoc»
  (абзац), security-буллет в «Мониторинг», нюанс про имя (ID не отображается).
- **Следующие шаги (10.2):** закрыты; новые follow-up — только security-слой
  (см. «Безопасность сервера» ниже).

### Раунд 10.3 — финал (09–10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (1410a68)

По ультиматуму юзера (7 пунктов ТЗ; задачи 1–4, 6 → F-13/F-14, задачи 5 и 7 →
F-15). HEAD == origin/master == `1410a68` (был d30b203). **Статус: COMPLETED +
DEPLOYED.** Все 3 фичи заархивированы, цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `1410a68` feat(admin,web,chat,api): раунд 10.3 — единый
  селектор чата в TMA, отдельные настройки ЛС (саммари default-off), диагностика
  sandbox budget и graphrag memorize (тесты 4831) — автор Henry, 09.09.2026
  12:33 UTC; push origin/master; `git diff --check` чист. **plans/MEMORY.md ВПЕРВЫЕ
  вошёл в коммит** (в раундах 10–10.2 был untracked намеренно).
- **Тесты:** 4831 passed / 0 failed (4760 baseline + ~71 новых). @Reviewer
  APPROVED; Scanner 0 blocker/major (миноры R10.3-1…R10.3-6 → ARCHITECTURE.md §24);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 1410a68; рестарт
  09.09.2026 12:37 UTC; `systemctl status admin_bot` → active (running); .env без
  изменений. Прод-диагностика задачи 5 проведена (см. ниже).
- **Фичи (все ARCHIVED, plans/archive/ — 18 папок):**
  - `tma-chat-selector-fixes` (F-13, T-925…T-944): единый нативный <select> +
    бейдж #id/«ЛС #id», удалены openChatPicker/✕ closeApp, фикс v-if/v-for
    precedence (<template v-for> + v-if на дочернем div; configError-баннер),
    .sidebar z-index:45 + safe-area. ARCH §23.
  - `dm-user-settings` (F-14, T-945…T-964): DM-скоуп is_dm_scope=chat_id>0 на
    chat_profiles/chat_params (ноль DDL), is_dm_owner (rank=local_admin,
    DM_OWNER_PRESET без chat_lore), ensure_scope_profile, саммари в ЛС default-off
    (S1–S5), изоляция WHERE chat_id<0 (6 точек), синтез DM-строки в
    /api/access/chats|me, TMA «Личные сообщения» в селекторе. ARCH §23.
  - `direct-sandbox-budget-investigation` (F-15, T-965…T-973): прод-диагностика
    T-965/T-966 ДО фикса; NoApiKeyForChat.details (снапшот resolve_path/day/
    used|limit calls|tokens/allow_global) + WARNING с details; BYOK-фоллбэк
    свой→глобал-бюджет→свой-фоллбэк→sandbox; parse_fact_list: _mask_llm_raw +
    _fallback_parse_facts + 1 ретрай (только fire-and-forget memorize, крон без
    ретрая). ARCH §23/§24.
- **Прод-диагностика задачи 5 (ВЫВОД):** у чата -1002661910336 НЕТ собственного
  ключа (chat_keys пуст) → работает глобальный ключ с суточным лимитом 25
  запросов; 09.09.2026 счётчик дошёл 25/25 в 09:55 UTC, WARNING reason=budget в
  09:57 — исчерпание суточного лимита; sandbox-фраза = штатный дизайн R16 (не
  баг); восстановление автоматическое после сброса бакета chat_usage в 00:00
  Екб. Рекомендации: BYOK-ключ для чата (chat_keys /api/config/keys/own) ИЛИ
  поднять limits.chat_global_key_budget_requests (25 → 50/100) через hot config.
  Детали — KG `recon: direct-chat-sandbox-budget` (+ фикс-слой F-15 уже в проде).
- **README.md:** тесты 4831, раздел раунда 10.3 (ироничный тон сохранён).

### Раунд 10.4 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (0bdf272)

По 9 пунктам ТЗ реструктуризации TMA. HEAD == origin/master == `0bdf272`
(был 1410a68). **Статус: COMPLETED + DEPLOYED.** Все 8 фич заархивированы,
цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `0bdf272` feat(admin,web,chat,api): раунд 10.4 —
  реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/Провайдеры/
  Отношения), бюджеты per-чат и температура-select, имена людей per-чат/ЛС,
  каскад имён, лимиты ×1.5-×2 для -1002661910336 (тесты 4860); push origin/master;
  `git diff --check` чист.
- **Тесты:** 4860 passed / 0 failed (4831 baseline + 29: test_104_backend_additions 11,
  test_progressive_tab_basic_coverage 3, маркеры webapp_*/frontend_tab_mapping).
  @Reviewer APPROVED; Scanner 10.4 — 0 blocker/major (minor R10.4-1…R10.4-4,
  info R10.4-5…R10.4-7 → ARCH §25; R10.4-1/-2/-3 закрыты follow-up @Builder и сверены);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 0bdf272; **.env —
  добавлена `CHAT_THREAD_MAX_CHARS=2000`**; **бэкфилы применены:**
  `scripts/backfill_104_chat_flags.py` (flags.chat_context_budgets_enabled=false
  для -1002661910336) + `scripts/backfill_104_overrides.py` (15 ключей ×1.5–×2:
  thread_max_chars ×2, global_context_max_chars/limit ×1.5, level2 ×2,
  map_participants_cap ×2, summary_*/ретенция/graph_rag_* ×2;
  graph_edge_weight_increment НЕ менялся); рестарт — `systemctl status admin_bot`
  → active (running).
- **Фичи (все ARCHIVED, plans/archive/ — 26 папок):**
  - `frontend-advanced-collapse-default` (D, T-1018…T-1023): «Расширенные» свёрнуты
    по умолчанию (:open="expandOpen(activeTab)"); 0-basic группы — свёрнуты с видимым
    summary; BUG-5-семантика сохранена; новый тест test_progressive_tab_basic_coverage. §24.
  - `frontend-memory-sleep-nostalgia` (C, T-1006…T-1017): «Память» (memory_rag) +
    отдельные «Сон»/«Ностальгия»; _ADVANCED_GROUPS минус dream/nostalgia; явная
    progressive-разметка; мини-блоки перенесены. §24.
  - `frontend-llm-providers-layout` (E, T-1024…T-1032): 4 секции
    (модели→ключи→фолбэк→расширенные), sections-зеркало TABS; маскировка/BYOK
    без изменений. §24.
  - `frontend-reorg-modules-reactions` (A, T-974…T-989): девиансия D-A1 —
    «Функции PERMsoc» 17 групп (+war/common/goodmorning/word_reactions);
    «Реакции и Триггеры» 4 группы; «Модули» (modules_switches); лор-настройки
    в «Лор чатов». §24.
  - `frontend-limits-temperature-budgets` (B, T-990…T-1005): бюджет-гейт per-chat
    (limits_chat_budgets, override false для -1002661910336); select-температура
    (widget='select' + select_options/select_labels, 422); «Имена людей» (people_names)
    + build_alias_resolver(chat_id); реестр read-путей T-993 для F-5. §24.
  - `frontend-relations-participants` (F, T-1033…T-1044): вкладка «Участники и
    отношения» (type 'relations'); перенос блока участников + «Настройки отношений»;
    DM-заглушка; серверные API без изменений. §24.
  - `backend-relations-nickname` (H, T-1057…T-1065): username для ВСЕХ строк
    (Semaphore(5), кэш 1ч; фото топ-50); каскад alias→nickname→username→''; R16. §24.
  - `backend-chat-1002661910336-scaling` (G, T-1045…T-1056): per-chat лимиты ×1.5–×2
    (12 точек чтения → get_chat_param; ревью-фикс №5: _thread_limit/_cp_g/budget_tokens),
    _resolve_from_root +_cast_type_ok+isfinite; граница G-4 задокументирована. §24/§25.
- **Диагнозы раунда:** per-chat бюджеты — флаг переведён в limits_chat_budgets,
  для -1002661910336 OFF (KPI-риск F-15: глобальный ключ 25 req/сутки; восстановление —
  1 клик); лимиты ×1.5–×2 — thread ×2 через chat_thread_max_chars (R10.4-3-фикс),
  global ×1.5 через max_chars; каскад имён — username всем строкам, R16 сохранён,
  per-chat алиасы (точка 1) через build_alias_resolver.
- **Техдолг (кандидаты следующего раунда, KG `tech-debt-round10.4`):** R10.4-4
  (фото-обогащение всех 100 строк), R10.4-5 (409-модалка relations «Перезагрузить»),
  R10.4-6 (бэкфилы без optimistic-метки), R10.4-7 (граница G-4: direct RAG-cap/
  get_rag_facts глобальные — кандидат F-5), B-13 points 2-4 (per-chat алиасы не
  доходят до инжекта <user_relations>), HIGH-004 (полный LLM request/response-лог).
- **README.md:** тесты 4860, раздел раунда 10.4.

### Раунд 10.5 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (918f675)

«Редизайн TMA по референсу Relume + гигиена репозитория». Единственная фича —
`tma-relume-redesign` (T-1066…T-1148, продолжает T-1065). HEAD == origin/master
== `c01ed72` (`918f675` + `c01ed72`, поверх `0bdf272`). **Статус: COMPLETED +
DEPLOYED.** Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `918f675` feat(admin,web,chat,api): раунд 10.5 — редизайн
  TMA по референсу Relume: navbar, hubs, hash-роутинг, scope-switcher, key-history,
  матрица ролей, градиенты, Material Symbols (тесты 4962) — 49 файлов; `c01ed72`
  docs(plans): деплой-верификация раунда 10.5; push origin/master.
- **Тесты:** 4962 passed / 0 failed (baseline 10.4 = 4860, +102); `node --check
  web/app.js` clean; `git diff --check` чист; HTML tag-balance 0.
- **Реализация (Builder Pass 1–6):** токены/анимированные градиенты (T-1098);
  hash-router + нативный `Telegram.WebApp.BackButton` (Bot API 6.1+, single
  onClick, `goBack`=routeParent, deep-link OFF) (T-1099); scope-switcher
  GLOBAL/ЧАТ/ЛС + scopeEpoch (T-1127); 6-item navbar + 3 hubs + 15 экранов
  (T-1100…T-1112); key-availability + chart + `services/key_history.py` (ring 288
  + атомарный `var/status_key_history.json`, allowlist, 0 DDL, SQLite v8)
  (T-1128/1129/1132/1139/1140/1145/1148); матрица ролей + создание/rename/delete
  кроме superuser (T-1130/1131/1133/1141/1142); hardcode H1–H22 → безопасная
  аддитивная миграция `hot.get(key, literal)`; каталог **387/74/359**; font-subset
  ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed (T-1146/1147).
- **Ревью/Scanner:** @Reviewer REJECTED → fixes D1–D4 → APPROVED WITH MINOR →
  R1–R4 закрыты. @Scanner **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты;
  R10.5-3/-5/-6/-7 — техдолг (ARCH §25). Отчёт
  `plans/reports/round10.5_scanner_audit.md`.
- **Архитектура:** @Architect — §9 обновлён, §25 «по состоянию на раунд 10.5» +
  блок R10.5, новый §26 «Раунд 10.5» (последняя секция, ARCHITECTURE.md 320 строк).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env`
  без изменений; `systemctl restart admin_bot` → active (running);
  `/api/health` = 200; 0 startup-ошибок.
- **Архивация:** `tma-relume-redesign` → `plans/archive/tma-relume-redesign/`
  (**plans/archive/ — 27 папок**; plans/features/ — 6 активных F-1…F-6); backlog
  epic 10.5 закрыт. README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (T-1153), опциональный
  betterstack-401 fix, вердикт владельца.
- **Техдолг раунда (KG `tech-debt-round10.5`):** R10.5-3 (GET
  /api/status/key-history открыт любому авторизованному TMA-юзеру),
  R10.5-5 (rename_role race → 500 вместо 409), R10.5-6 (мёртвый setMenu,
  пре-существующий), R10.5-7 (sync `key_history.maybe_save()` I/O в async path).

### Раунд 10.6 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (6f91e8b + 4055434)

«Переработка IA TMA — единый navbar, 11 Модулей с реальными тумблерами, Настройки AI
из 7 подразделов, чистка PERMsoc». Единственная фича — `tma-ia-modules-rework`
(T-1155…T-1223; follow-up после round10.5-epic). HEAD == origin/master == `4055434`
(`6f91e8b` + `4055434`, поверх `be7b85b`). **Статус: COMPLETED + DEPLOYED.** HARD GATE
T-1156 пройден владельцем 11.09.2026 (GO на IA). Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `6f91e8b` feat(admin,web,api,plans): раунд 10.6 — редизайн IA
  TMA: одна навигация, 11 модулей-тумблеров, RAG в память, тест провайдеров, чистка
  PERMsoc (тесты 5027) — **37 файлов**; `4055434` docs(plans): раунд 10.6 — деплой-
  верификация; push origin/master.
- **Тесты:** 5027 passed / 0 failed (baseline 10.5 = 4962; +65; Scanner зафиксировал
  5023 на момент аудита — до follow-up R10.6-1/-3). `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация (@Builder, T-1157…T-1223):** sidebar/`MENU_ORDER`/`sidebarOpen`/
  `setMenu` удалены — только top navbar (6 пунктов: Статус/Как это работает/Модули/
  Настройки AI/Функции PERMsoc/Доступы и Роли), иконка + подпись под ней; модель
  скролла `.app-shell` flex-col + `.scroll-area` (desktop fullscreen ⛶ скроллится);
  «Модули» = 11 `mod_*` (Саммаризация, Прямые ответы, Фактчек, Поиск, Транскрипт
  голосовых и видео, Выжимка видео, Скачивание медиа, Веб-страницы, Диагностика, Сон,
  Ностальгия) с реальными toggle + модалка параметров; «Настройки AI» = 7 подразделов
  (LLM Провайдеры, Промпты, Память+RAG, Умный кэш, Имена, Отношения, Лор чата;
  «Лимиты» растворены); 5 master-флагов default ON
  (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED
  (youtube — только summary-ветка); PERMsoc очищен — 10 миселённых параметров
  разнесены по модулям 5/6/7; Леха/Костик раздельно (`limits_alan`/`limits_kostik`,
  `reactions_kostik`); LLM Провайдеры — 9 блоков по модулям + `POST /api/llm/test`
  (global admin, rate-limit 5с, R17); `keys_youtube` → M6, `models_checkup`/
  `keys_betterstack` → M9; emoji→Material icons; эксклюзивный аккордеон «Доступы и роли».
- **Каталог (locked):** REGISTRY **392** / GROUPS **91** / Settings **364** /
  mapped **89** / `TAB_RULES` **19**. Расщепления: `limits_media`→4, `limits_persons`→2,
  `limits_youtube_web`→2, `limits_cooldowns`→растворена, `flags_modules`→7, `flags_chat_behavior`→3,
  `reactions_persons`→+`reactions_kostik`, `limits_chat_budgets`→+`limits_rag` (RAG→«Память»).
  **Ноль новых PG-DDL**; SQLite **v8**; порядок роутеров `bot.py` и `media/` не тронуты.
- **Ревью/Scanner:** @Reviewer REJECTED → fixes (BLOCKER nav-gating модулей, test-buttons,
  Sleep/Nostalgia-панели в модалке) → APPROVED WITH MINOR ISSUES → миноры закрыты
  (SSRF-префикс, search per-key, clear field). @Scanner **CLEAN — 0 blocker / 0 major**;
  R10.6-1 (дубль LLM-редакторов) и R10.6-3 (422-эхо `api_key`) закрыты; R10.6-2/-4/-5/-6 —
  техдолг (ARCH §25/§27). Отчёт `plans/reports/round10.6_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§27 «Раунд 10.6»** + обновлены
  §25 (техдолг R10.6-*), §9 (фронт/каталог/provider-блоки), §6 (таблица master-гейтов),
  §2 (гейты внутри существующих роутеров).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до `4055434`;
  `.env` без изменений; `systemctl restart admin_bot` → `is-active=running`;
  `/api/health` = 200; 0 tracebacks.
- **Архивация:** `tma-ia-modules-rework` → `plans/archive/tma-ia-modules-rework/`
  (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). README
  обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (desktop/Android WebView),
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.6`):** R10.6-2 (SSRF-периметр
  `POST /api/llm/test`: https для любого хоста без private-range-проверки),
  R10.6-4 (info — `media_share` вне списка блоков спеки), R10.6-5 (info — мёртвые
  записи `ICONS` после удаления вкладок), R10.6-6 (info — rate-limit расходуется
  до валидации блока).

### Раунд 10.7 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (7f3b790 + bb59476)

«UI/UX-багфиксы админ-минги». Единственная фича — `admin-ui-bugfixes-round107`
(spec @Architect T-1224). HEAD == origin/master == `bb59476` (`7f3b790` + `bb59476`,
поверх `2ccf558` — docs 10.6; прод до деплоя — `4055434`).
**Статус: COMPLETED + DEPLOYED.** FOLLOWS
round10.6-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `7f3b790` fix(admin,web): раунд 10.7 — UI/UX-багфиксы
  (scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей,
  gap-fill uptime, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20)
  — **19 файлов**; `bb59476` docs(plans): деплой-верификация раунда 10.7;
  push origin/master.
- **Тесты:** 5042 passed / 0 failed (baseline 10.6 = 5027; +15). Каталог
  **392 / 91 / 364** (без изменений).
- **Реализация:** 1a `scope*` → computed (фикс `function () { [native code] }`);
  1b header safe-area padding; 1c компактный user block; 1d nav labels меньше/без
  per-letter wrap; 2a ellipsis таблицы ключей; 2b uptime gap-fill (непрерывная
  5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None);
  3a clipboard-ghost focusable (без `visibility:hidden`) + удалён; 3b фиксированные
  ширины лог-колонок + flex последней; 3c copy-on-row-click с feedback; R106-5
  dead ICONS удалены (26→20).
- **Ревью/Scanner:** @Reviewer REJECTED (`visibility:hidden` сломал
  `execCommand`-фолбэк) → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.7-1 (minor) + R10.7-2..5
  (info/nit) — техдолг; R10.6-5 ЗАКРЫТ. Отчёт
  `plans/reports/round10.7_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§28 «Раунд 10.7»** + обновлены
  §9/§25.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до
  `7f3b790`; `.env` без изменений; `systemctl restart` → active; `/api/health` =
  200; 0 errors.
- **Архивация:** `admin-ui-bugfixes-round107` →
  `plans/archive/admin-ui-bugfixes-round107/` (**plans/archive/ — 29 папок**;
  plans/features/ — 6 активных F-1…F-6). README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест исправленного UI, опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.7`):** R10.7-1 (minor — gap-fill
  помечает текущий незавершённый 5-мин слот `down` до ~60 с; §2b trade-off),
  R10.7-2 (info — `[-288:]` может отсечь единственный ранний `up`-бакет),
  R10.7-3 (info — `copiedTimer` не чистится при смене вкладки),
  R10.7-4 (info — `test_font_subset` проверяет JS, не cmap WOFF2),
  R10.7-5 (info/nit — неточная формулировка «context-loss» в `copyAllLogs`).

### Раунд 10.8 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (31d2ce7 + 976e335)

«Точечные UI-правки админ-минги». Единственная фича — `admin-ui-round108`
(spec @Architect + tasks @PM, T-1243…; продолжает 10.7). HEAD == origin/master ==
`976e335` (`31d2ce7` + `976e335`, поверх `636a75d` — docs-финал 10.7; прод до
деплоя — `7f3b790`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.7-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `31d2ce7` feat(admin,web,plans): раунд 10.8 — переименование
  разделов, emoji→иконки, фикс логов на Android, окна «Доступов» (тесты 5076) —
  **30 файлов**; `976e335` docs(plans): раунд 10.8 — деплой-верификация; push origin/master.
- **Тесты:** 5076 passed / 0 failed (baseline 10.7 = 5042; +34; Scanner зафиксировал
  5073 на момент аудита — до follow-up R10.8-1/-5). Каталог **392 / 91 / 364**
  (mapped 89, `TAB_RULES` 19); `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация:** (1) переименования разделов «Доступы»/«PERMsoc»/«ИИ»/«Справка»/«Сводка»;
  (2) emoji→Material-иконки, субсет шрифта 20→37 глифов (18 388 B), идемпотентность
  build-script по sha256(source_sha+ICON_NAMES), `build/icon_codepoints.json`,
  R10.7-4 cmap-тест; (3) Android-логи — шеврон только при `exc_text`, дата
  DD.MM HH:MM:SS, блочная раскладка без `<pre><span>` и жёстких ширин, `.log-msg`
  full-width, `copiedTimer` cleanup (R10.7-3); (4) три route-driven модалки
  `#/access/roles|local|admins`, «Администраторы»→«Роли», аккордеон удалён, «Мой доступ»/
  «Telegram ID админа» без изменений, BackButton/deep-link/Esc; (5) удалён внешний
  GLOBAL-бейдж; README-реструктуризация.
- **Ревью/Scanner:** @Reviewer APPROVED WITH MINOR ISSUES → doc-nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.8-1 (Esc) и R10.8-5 (APP_VERSION
  2.51.0 vs README 2.52.0 + кэш старого субсета без `?v=`) закрыты точечно follow-up;
  R10.8-2 (stale-комментарий `section`/ветка `openHubCard`), R10.8-3 (мёртвый
  `TABS.icon`/`visibleTabs`/`tabMat`), R10.8-4 (doc-drift backlog — закрыт архивацией)
  — техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**. Отчёт `plans/reports/round10.8_scanner_audit.md`.
- **Архитектура/ADR:** @Architect — ARCHITECTURE.md **§29 «Раунд 10.8»** (+§1/§9/§25).
  ADR-001 — «Доступы» как route-driven модалки (hash — источник истины, `git revert`
  как откат); ADR-002 — паритет `ICONS`==`ICON_NAMES`↔cmap WOFF2 (PUA из GSUB,
  идемпотентность учитывает `ICON_NAMES`, fontTools/brotli build-time only).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `7f3b790..31d2ce7`; `.env` без изменений; restart → active; `/api/health` = 200;
  шрифт `?v=2.52.0` → 200 (wOF2, 18 388 B); 0 ошибок.
- **Архивация:** `admin-ui-round108` → `plans/archive/admin-ui-round108/`
  (**plans/archive/ — 30 папок**; plans/features/ — 6 активных F-1…F-6). README
  счётчик 5073→5076; `APP_VERSION` 2.52.0.
- **Осталось вручную:** live Android smoke-тест **T-1254** (логи: ширина/дата/текст/
  отсутствие невидимого поля) и **T-1258** (три отдельных окна «Доступов»); опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.8`):** R10.8-2 (info — stale-комментарий/
  осиротевшая ветка `openHubCard`), R10.8-3 (info — мёртвый `TABS.icon`/`visibleTabs`/
  `tabMat`, pre-existing), R10.8-4 (info — doc-drift backlog, закрыт @PM); закрытые
  R10.8-1/-5; закрытые из 10.7 — R10.7-3/-4.

### Раунд 10.9 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d2d1215 + f928225)

«UI/UX-правки админ-минги — PERMsoc owner-блоки и под-флаг Славика, сохранение
скролла, переписанные описания, удаление «Тяжёлых фич»/перенос «Бюджета»,
dashboard-health, display-name, градиент». Единственная фича — `admin-ui-round109`
(spec @Architect + tasks @PM + ADR-109; T-1270…T-1314, продолжает T-1269).
HEAD == origin/master == `f928225` (`d2d1215` + `f928225`, поверх `51f308b` —
docs-финал 10.8; прод до деплоя — `31d2ce7`). **Статус: COMPLETED + DEPLOYED.**
FOLLOWS round10.8-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d2d1215` feat(admin,web,plans): раунд 10.9 — PERMsoc-блоки,
  сохранение скролла, описания, доступность ключей по функциям, display-name,
  градиент (тесты 5105) — **34 файла**; `f928225` docs(plans): раунд 10.9 —
  деплой-верификация; push origin/master.
- **Тесты:** 5105 passed / 0 failed (baseline 10.8 = 5076; +29; 1 pre-existing
  warning + «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение).
  Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19, `CONFIG_TAB_TITLES` 19);
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист.
- **Реализация:** (п.1) PERMsoc — 4 сворачиваемых `<details class="owner-block">`
  (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер
  (`PERMSOC_OWNER_BLOCKS`/`_permsocOwnerGroups`/`PERMSOC_TOGGLE_KEYS`; generic-bool
  дубли и master-карта удалены); backend — новый `flags.slavik_enabled`
  (`SLAVIK_ENABLED` default True), `reactions_persons` удалена,
  `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`,
  `TAB_PERMSOC` без persons; (п.3) `_preserveScroll` для `document.scrollingElement`
  И `.scroll-area` (restore в `$nextTick`) — скролл не прыгает при сохранении,
  вкл. fullscreen; (п.4) ВСЕ описания/титулы переписаны (plain ironic language,
  тест на 28 запрещённых жаргон-подстрок + AI-шаблон); (п.5) карточка «Тяжёлые
  фичи» удалена (per-chat dream/nostalgia/lore_auto остаются в «Сводке»);
  (п.6) «Бюджет фона» перенесён в «Сводку» (`loadBudgetInfo` из `loadOversight`;
  backend/endpoint не тронуты); (п.7.1) dashboard «Доступность ключей» — 4
  функциональные группы (main+fallback / транскрибация / саммаризация видео /
  эмбеддинги) + реальный health `probe_openai` (ok/error/timeout/unreachable/
  not_configured; `stt_groq` → `POST /audio/transcriptions` multipart WAV, таймаут
  5с; кэш per `module_id`: 2xx 60с, ошибки 10с, stale-200 не отдаётся), старый
  блок → «История доступности ключей»; (п.7.2) 7 `models.*_display_name` первым
  полем каждого провайдер-блока, ширина формы `max-w-3xl`; (п.8) градиент быстрее
  (`--grad-speed:14s`, `grad-drift 18s`).
- **ADR-109 (Accepted @Architect 12.09.2026):** ADR-109-1 — display-name как 7
  новых `ParamSpec` (`models.*_display_name`, Settings, глобальные); ADR-109-3 —
  health реальным POST вместо `GET /models` (`probe_openai` chat/embeddings/stt,
  кэш per `module_id`); ADR-109-4 — `SLAVIK_ENABLED` для независимого тумблера
  Славика; ADR-109-5 — «Бюджет фона» → «Сводка».
- **Ревью/Scanner:** @Reviewer REJECTED (1 Critical + 1 High + 2 Medium + 3 Low) →
  фиксы (STT probe, AI-описания, титулы, fullscreen-скролл, dead code, owner-блоки,
  JS-единицы) → APPROVED WITH MINOR ISSUES → follow-ups закрыты. @Scanner
  **CLEAN — 0 blocker / 0 major / 0 medium**; 3 low R10.9-1/-2/-3 + 3 info
  R10.9-4/-5/-6; R10.9-6 закрыт архивацией. Отчёт
  `plans/reports/round10.9_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§30 «Раунд 10.9»** (+§1/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `31d2ce7..d2d1215`; `.env` без изменений; restart → active; `/api/health` = 200;
  0 ошибок.
- **Архивация:** `admin-ui-round109` → `plans/archive/admin-ui-round109/`
  (spec.md + tasks.md + ADR-109.md) (**plans/archive/ — 31 папка**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5105; `APP_VERSION` 2.53.0.
- **Осталось вручную:** live Android smoke — **T-1277** (owner-блоки/тумблеры
  PERMsoc), **T-1290** (скролл при сохранении), **T-1292/T-1294**
  (dashboard-health/«Доступность ключей»), **T-1302** (форма провайдеров/
  display-name), **T-1305** (градиент); реальное Android-устройство недоступно
  @Builder, статически покрыто `tests/test_webapp_round109_ui.py` + JS-юниты;
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.9`):** R10.9-1 (low — `model_source`
  запасных/эмбеддинг-записей снова `"code"` при конфиге, metadata-only),
  R10.9-2 (low — эмбеддинг-фоллбэки читаются из `settings`, не через
  `hot`/`_resolve`; `emb_fallback*` исчезают без env-ключа), R10.9-3 (low —
  устаревший docstring `status_service.py`), R10.9-4 (info — кэш health по
  `module_id` не инвалидируется при смене base_url/key/model ≤60с), R10.9-5
  (info — docstring `_LLM_BLOCKS` без `transcribe_groq`; `ConnectTimeout` →
  «timeout»); R10.9-6 закрыт архивацией; R10.8-2/-3 остаются открытыми.
- **⚠️ Вне скоупа:** пункт 2 исходного ТЗ — инфраструктура локального IDE
  владельца (не часть бота); в репозитории и в графе не фиксируется.

### Раунд 10.10 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d082800 + a477747 + 772db08)

«UI/UX-правки админ-минги — шапка в fullscreen, мобильный график доступности
ключей, реальные значения «Провайдеров», ЛС heavy-modules OFF, «Роли» с
аватарами». Единственная фича — `admin-ui-round1010` (spec @Architect + tasks @PM +
ADR-1010-1/2/3; T-1315…T-1328, продолжает 10.9). HEAD == origin/master == `772db08`
(`d082800` + `a477747` + `772db08`, поверх `da85b60` — docs memory-sync 10.9; прод
до деплоя — `d2d1215`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.9-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d082800` fix(admin,web,api,scripts,plans): раунд 10.10 —
  fullscreen safe-area, mobile key-chart, реальные значения провайдеров, ЛС
  heavy-modules OFF, роли с аватарами (тесты 5144); `a477747` fix(scripts): раунд
  10.10 — standalone-запуск `disable_dm_heavy_modules` (sys.path bootstrap) +
  регресс-тест CLI (тесты 5145); `772db08` docs(plans): раунд 10.10 —
  деплой-верификация; push origin/master.
- **Тесты:** 5145 passed / 1 skipped / 0 failed (baseline 10.9 = 5105; Scanner
  зафиксировал 5140 + 1 skipped на момент аудита — до CLI-регресс-теста).
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист. Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19,
  `CONFIG_TAB_TITLES` 19) — без изменений; ноль новых PG-DDL; SQLite v8;
  `bot.py` router order, `media/` и `.env` не тронуты.
- **Реализация:** (п.1) fullscreen-паддинг шапки — `.fullscreen-mode
  header.header-sticky` padding `calc(base + max(env(safe-area-inset-*),
  var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*)))` —
  профиль-блок не перекрывается нативными кнопками Telegram; 10.7 (ширина) и 10.9
  (`.scroll-area`) не тронуты; (п.2) мобильный график key-availability —
  RENDER-фикс: окно строится ОТ КОНЦА (`minStart`, cap ≤ `MAX_HISTORY_POINTS`,
  без `break`/`slice`) — новейшие сэмплы больше не отбрасываются; дорожки на
  провайдера + временная сетка `SAMPLE_BUCKET=300` (min 12 бакетов), динамическая
  высота, `pointRadius:3` при 1 сэмпле, пропуск = `null` + `spanGaps:false`;
  контракт `/api/status/key-history` (`api_payload`) НЕ изменён; (п.3)
  «Провайдеры» показывают реальные значения — `:value="blockFieldValue(f)"` +
  `@input` вместо `v-model`; `blockFieldValue` возвращает `''` для пустого
  черновика и значение `configItems` при отсутствии черновика, секреты
  (`type==='object'`) → `''` (placeholder-маска); `blockDrafts`/`blockResults`
  сброшены в `loadConfig` и `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не
  трогать, `''`=очистить) не менялись; (п.4) ЛС heavy-modules OFF; (п.5) «Роли» —
  аватар + ник + мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
  `get_chat(user_id)`→first/last→username, фото через `getUserProfilePhotos`;
  транзиентные `TelegramRetryAfter`/`TelegramNetworkError` НЕ в негатив-кэш,
  fail-open), `/api/admins` обогащает КОПИИ под `requires_permission("access")`,
  `Semaphore(5)`+`gather`; фронт `admin.avatarUrl` (blob через прокси, `@error`),
  `adminInitial`, `display_name||username`, ID `text-[10px] text-gray-500
  font-mono`; ширины `w-36→w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`.
- **ADR-1010:** ADR-1010-1 — ЛС heavy-modules OFF (`gates.dream/nostalgia=false` +
  4 override=false; `ensure_scope_profile(dm=True)` DM-дефолты;
  `scripts/disable_dm_heavy_modules.py` dry-run/`--apply`/`--restore`/`--chat-id`/
  snapshot, без DDL); ADR-1010-2 — key-chart render-only, дорожки + временная
  сетка 300с, контракт `api_payload` не меняется; ADR-1010-3 —
  `global_user_display_info(user_id)`, RAM-TTL 1ч, fail-open, обогащение
  `/api/admins`, фронт аватар/инициалы + мелкий серый ID.
- **Ревью/Scanner:** @Reviewer REJECTED (график отбрасывал новейшие данные) →
  фикс → APPROVED WITH MINOR ISSUES → restore exit-code Low закрыт. @Scanner
  **0 blocker / 0 major / 0 medium**; low R10.10-1/-2/-3 + info R10.10-4/-5
  (большинство точечно исправлено); отчёт
  `plans/reports/round10.10_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§31 «Раунд 10.10»** (+§3/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env` без
  изменений; `systemctl restart` → active (running); `/api/health` = 200; 0 ошибок.
- **DM data-run (прод, 12.09.2026):** `scripts/disable_dm_heavy_modules.py`
  применён — **1 активный ЛС изменён** (сон/ностальгия/саммаризация OFF),
  снапшот `var/dm_modules_off_snapshot_20260911T201219Z.json`; повторный dry-run —
  **0 изменений** (идемпотентно). F-14 gate (`bot.py flags.summary_enabled`) не
  тронут.
- **Архивация:** `admin-ui-round1010` → `plans/archive/admin-ui-round1010/`
  (spec.md + tasks.md + ADR-1010-1/2/3.md) (**plans/archive/ — 32 папки**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5145; `APP_VERSION` 2.54.0.
- **Осталось вручную:** live Android QA — **T-1317** (шапка fullscreen),
  **T-1320/T-1323/T-1332** (мобильный график/провайдеры/роли), UI spot-check
  DM-тумблеров OFF (**T-1328**); реальное Android-устройство недоступно @Builder,
  статически покрыто `tests/test_webapp_round1010_ui.py` +
  `tests/test_scripts_round1010_dm_off.py` + JS-юниты; опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.10`):** R10.10-1 (low — скрипт DM:
  `total`/`noop`/dry-run-count игнорируют `--chat-id`; операторский вывод),
  R10.10-2 (low — `meta.note` перезаписывается и не откатывается snapshot'ом),
  R10.10-3 (low — `renderKeyHistoryChart` ранний return без `destroy()` старого
  Chart.js), R10.10-4 (info — `loadAdmins` без `avatarSkipped`/`.catch`, повторные
  blob-запросы), R10.10-5 (info — `adminInitial` дублирует `avatarInitial`,
  ветка `admin.username` недостижима).
- **⚠️ Вне скоупа:** П.6 ТЗ — Headroom saved-tokens stats (внешняя
  IDE-инфраструктура владельца, не часть бота); в репозитории и в графе НЕ
  фиксируется как сущность.

### Раунд 10.11 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (3624789 + cbe6ea5)

«Рефакторинг раздела LLM Провайдеры + проверка сохранённого ключа +
непрерывный график доступности + plain-language отчёт о памяти/сне/ностальгии/
лоре». Единственная фича — `llm-providers-refactor-round1011` (spec @Architect +
tasks @PM + ADR-1011-1/2/3; T-1340…T-1381, продолжает T-1339 — финал 10.10).
HEAD == origin/master == `cbe6ea5` (`3624789` + `cbe6ea5`, поверх `ec5dd1f` —
docs memory-sync 10.10; прод до деплоя — `772db08` = задеплоенный 10.10).
**Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.10-epic; цикл раунда
полностью закрыт (Step 10).

- **Коммиты (master):** `3624789` feat(admin,web,api,scripts,plans): раунд 10.11 —
  рефакторинг «LLM Провайдеры», проверка сохранённого ключа, график доступности,
  отчёт по памяти (тесты 5172) — **28 файлов**; `cbe6ea5` docs(plans): раунд 10.11 —
  деплой-верификация; push origin/master.
- **Тесты:** 5172 passed / 0 failed (baseline 10.10 = 5145; Scanner зафиксировал
  5168 на момент аудита — до follow-up R10.11-1/-2/-3). `node --check web/app.js`
  clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист;
  R17-скан чист.
- **Пункт 1 (ADR-1011-1):** `POST /api/llm/test` при пустом/пробельном `api_key`
  резолвит СОХРАНЁННЫЙ ключ блока server-side — `_BLOCK_SAVED_KEY` (все сетевые
  блоки + media_share), `_saved_api_key` (`hot.get(pg_key, settings_default)`,
  ошибка → `""`); явный draft из UI приоритетнее (UI шлёт `api_key` только если
  truthy); резолв внутренний — ключ не попадает в `_result` (ok/status/latency/
  model/error) и не логируется, тело ошибки чистится `sanitize_error`; UI — поле
  остаётся пустым, hint «Ключ сохранён (••••last4)» через маску `{configured,last4}`.
  Работает без повторного ввода ключа.
- **Пункт 2.1–2.5:** nav-icons крупнее/плотнее (`nav-icon 22px`, `gap .15rem`,
  `min-width 60px`) + pinned профиль (`shrink-0` + `whitespace-nowrap`);
  `.hub-head`/`.hub-grid` `max-width:64rem` + `justify-self:center`; две зоны
  «Подключения»/«Расширенные настройки» — `providerConnectionBlocks`/
  `providerAdvancedBlocks` **computed** (НЕ methods; фикс ревьюера), зона advanced
  через `<component :is>` + `<summary>`, на прочих вкладках `div`; embeddings —
  один блок с 3 подблоками (`embeddings.subBlocks = [main, f1, f2]`, у каждого
  Base URL+Модель+Ключ+«Проверить»; `providerCoveredKeys` рекурсивно покрывает
  subBlocks — нет дублей в generic); video fallback строго после
  `video_summary_openrouter` (kind=chat); media_share → advanced + note,
  `search_keys`/`llm_guard` тоже advanced внизу; технический хаос ниже зоны
  «Подключения».
- **Пункт 2.3 — каталог-дельта (ADR-1011-2, sanctioned):** 4 infra
  embed-fallback записи перенесены в каталог — `models.embedding_fallback_base_url`/
  `_model` → category `models`/group `models_embeddings`;
  `keys.embedding_fallback_api_key`/`_2` → category `keys`/group `keys_llm`,
  `secret=True`; `llm_client`/`status_service` читают через `hot.get` (прежние
  дефолты — паритет). Счётчики БЕЗ роста: REGISTRY **400** / GROUPS **90** /
  Settings **372** / mapped **88** / `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19;
  `categorized` 372→**376** (models 40→42, keys 13→15), `infra` 28→**24**.
- **Пункт 3 (ADR-1011-3):** dashboard key-history — непрерывный график:
  точки `{x: ts*1000, y: lane|null}`, `spanGaps:true`, `stepped:true`,
  ось X `type:'linear'` + `min/max` (`xMin`/`xMax`) + `ticks.callback` HH:MM,
  `parsing:false`; `type:'time'` отсутствует (без date-adapter); серверный
  контракт `GET /api/status/key-history` (`api_payload`, `services/key_history.py`)
  НЕ изменён. R10.10-3 (ранний return без destroy) не регрессирован.
- **Пункт 4 (docs-only, без кода):** `plans/docs/memory_sleep_nostalgia_lore_report.md`
  — подробный plain-language отчёт: память (L1/L2/L3/GraphRAG), сон/синтез снов,
  ностальгия, чат-лор, тайминги/лимиты, сборка контекста; 6 тем, каждая цифра с
  `file:line`; принят @PM (T-1342).
- **Ревью/Scanner:** @Reviewer REJECTED (CRITICAL: zone helpers в methods, не
  computed → блоки провайдеров исчезали) → фикс (computed) + жёсткий тест →
  APPROVED WITH MINOR ISSUES. @Scanner **CLEAN — 0 blocker / 0 major / 0 medium**;
  3 low R10.11-1/-2/-3 закрыты follow-up; 3 info R10.11-4/-5/-6 → техдолг; отчёт
  `plans/reports/round10.11_scanner_audit.md`.
- **Архитектура/ADR:** @Architect — ARCHITECTURE.md **§32 «Раунд 10.11»**
  (+§5/§9/§25). ADR-1011-1 — saved-key probe (R17-safe); ADR-1011-2 — embeddings
  one block + sanctioned Δ каталога без роста счётчиков; ADR-1011-3 — key-history
  chart на линейной оси (без `type:'time'`), контракт `api_payload` неизменен.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `772db08..3624789`; миграция `python scripts/migrate_env_to_pg.py
  --only-category models,keys` → **created=5 / skipped=48** (4 embed-фоллбэка
  резолвятся); `systemctl restart` → active; `/api/health` = 200; 0 ошибок.
- **Архивация:** `llm-providers-refactor-round1011` →
  `plans/archive/llm-providers-refactor-round1011/` (spec.md + tasks.md +
  ADR-1011-1/2/3.md) (**plans/archive/ — 33 папки**; plans/features/ — 6 активных
  F-1…F-6). README счётчик 5172; `APP_VERSION` 2.55.0.
- **Осталось вручную:** live Android/Telegram QA — **T-1377** (поле ключа +
  «Проверить» без повторного ввода; навигация/профиль/сетка; две зоны
  «Провайдеры»; эмбеддинги (3 подблока); видео-фоллбэк; media-share внизу; график
  доступности ключей). Статически покрыто `tests/test_webapp_round1011_ui.py` +
  JS-юнитами; опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **⚠️ Наблюдение:** pre-restart PID имел 401 к `apinet.cloud` (возможно невалидный
  primary token) — стоит проверить.
- **Техдолг раунда (KG `tech-debt-round10.11`):** R10.11-1 (low, закрыта — вложенные
  `<details>` делят один localStorage-ключ `adminbot.expand:llm_providers`),
  R10.11-2 (low, закрыта — расхождение `embedding_fallback_model` рантайм vs
  карточка статуса при явной очистке), R10.11-3 (low, закрыта — устаревшие
  подсказки «править в .env» для embed-фоллбэк-ключей), R10.11-4 (info, открыта —
  probe прикрепляет сохранённый секрет к caller-supplied `base_url`; hardening:
  резолвить `base_url` из конфига блока/allowlist), R10.11-5 (info, открыта —
  мёртвая ветка `destroy()` в `renderKeyHistoryChart`), R10.11-6 (info, открыта —
  нет headless-теста фактического рендера `spanGaps:true`/`parsing:false`).
- **⚠️ Вне скоупа:** Headroom — внешняя IDE-инфраструктура владельца, не часть
  бота; в репозитории и в графе как сущность НЕ фиксируется.

## Безопасность сервера (fail2ban / ufw / SSH-харденинг, 09.09.2026)

Применено DevOps на 198.46.175.136 (Ubuntu 24.04.4, OpenSSH 9.6p1),
research-based (референсы: fail2ban issues #3785/#3812 для OpenSSH 9.8 —
неактуально на 9.6p1, работает; ufw порядок правил). **Активно.**

- **fail2ban 1.0.2** (`/etc/fail2ban/jail.local`): backend=systemd,
  banaction=nftables, bantime 1h + increment до 1w; jail `sshd`: maxretry=3,
  bantime=24h, findtime=10m, journalmatch=_SYSTEMD_UNIT=ssh.service +
  _COMM=sshd + _SYSTEMD_UNIT=ssh.socket; jail `recidive`: 1w/1d/3.
  Живой бан подтверждён: **176.53.159.197** (nft f2b-table); фильтр — ~65k
  матчей; btmp сокращён (было 44M/3д).
- **ufw:** default deny incoming; 22/tcp LIMIT IN; 80/443 ALLOW. Снаружи
  открыты только 22/80/443; закрыты: 4416 (bgutil POT), 8000, 8081, 9000,
  5432, 2019, 10808 (проверено извне — timeout).
- **SSH `/etc/ssh/sshd_config.d/00-hardening.conf`:** PermitRootLogin no,
  MaxAuthTries 3, LoginGraceTime 20, MaxStartups 10:30:60, MaxSessions 3,
  ClientAliveInterval 300/2, X11Forwarding no, LogLevel VERBOSE, DebianBanner no;
  `sshd -t` + reload OK. **Password auth сохранена** (требование владельца),
  порт 22 не менялся. Lockout не произошёл.
- **Follow-up (решения владельца):** миграция на SSH-ключи (key migration
  proposal); добавить IP владельца в `ignoreip`, если он статический;
  CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) вне
  диска.

## Свежие архивы (plans/archive/ — 76 папок)

> **Раунд 10.18 (15.09.2026, HEAD `16a8c0b`, §39)** — 7 фич заархивированы:
> `betterstack-us-region-401` (F1, ADR-1018-1), `settings-worker-sync` (F7, ADR-1018-7),
> `sleep-manual-cascade-badges` (F2, ADR-1018-2), `graph-density-scoring-stoplist` (F3, ADR-1018-3, SQLite v10),
> `graph-physics-stabilization` (F4, ADR-1018-4), `metafact-penalty-extractor-prompt` (F5, ADR-1018-5),
> `role-matrix-settings-actualization` (F6, ADR-1018-6). Каждый — `spec.md` + `tasks.md` + ADR.
> `plans/features/` — 6 активных (F-1…F-6); новых фича-флагов нет; каталог 436/406/411/90/88/19.

- `anti-echo-self-reply-round1014` — **Раунд 10.14, 13.09.2026** (F1, T-1477…T-1486 + ADR-1014-2): origin `bot_self_reply` (11-й, честный карантин) + rebuild `graph_facts` + **SQLite v9**; вес `limits.graph_fact_weight_bot`=0.2 (importance=2), LLM-экстрактор `services/self_reflection.py` (роль `reflection`, fail-open), `_SELF_ECHO_INSTRUCTION`, карантин self из Сна/золотых/компакции/`graph_stats`; флаг `flags.bot_self_awareness_enabled` **ON**)
- `persona-storage-core-round1014` — **Раунд 10.14, 13.09.2026** (F2, T-1487…T-1497 + ADR-1014-1): **PG `personas`/`persona_traits`** (+`persona_state`), `services/bot_persona.py` (scope per-chat→global→empty, `<Persona>`-блок, `_NO_AI_DISCLOSURE_BLOCK`), traits пишет DeepSleepWorker, API `GET/PUT/DELETE /api/persona` + `/api/persona/health`; флаг `flags.persona_enabled` **ON**)
- `persona-ui-tab-round1014` — **Раунд 10.14, 13.09.2026** (F3, T-1498…T-1504): special-screen `#/ai/persona` (карточка «Личность» в Hub «ИИ»), форма 3 поля + чекбокс «Осознаёт себя ИИ», scope-сброс, RBAC `edit_persona`; Δ каталога = 0)
- `persona-traits-ribbon-round1014` — **Раунд 10.14, 13.09.2026** (F4, T-1505…T-1510): 3-я лента «Эволюция характера» в «Мониторинге Интеллекта» (`_ribbonLoop`, сетка 3→1) + панель метрик Личности в «Сводке» `#/oversight` (`/api/persona/health`))
- `settings-persistence-audit-round1014` — **Раунд 10.14, 13.09.2026** (F5, T-1511…T-1525): инвентаризация всех изменяемых параметров + аудит write-path/scope/restart, закрыт R10.9-4 (health-кэш); `report.md` + `inventory.tsv` в архиве)
- `help-guide-integration-round1014` — **Раунд 10.14, 13.09.2026** (F6, T-1526…T-1534): гайд в PG `content.intelligence_guide` + второй редактируемый блок «Гайд по возможностям» в «Справке» (Markdown-редактор + DOMPurify 3.4.15 self-host), идемпотентный сид; API `GET/POST /api/info/guide`)
- `status-layout-reorder-round1014` — **Раунд 10.14, 13.09.2026** (F7, T-1535…T-1540): порядок «Статуса» Сводка → Сердцебиение → Бот → Сервер → Мониторинг Интеллекта → Доступность ключей → История; Δ=0)
- `self-reflection-llm-provider-round1014` — **Раунд 10.14, 13.09.2026** (F8, T-1541…T-1548): роль `reflection` → slug `intel_reflection` (`generate_worker`), 4 PG-ключа (models/keys), probe `intel_reflection_main`, третий parent-блок «LLM для саморефлексии (Экстрактор сути)», фоллбэк на основную модель)
- `cognition-4d-memory-round1013` — **Раунд 10.13, 13.09.2026** (F1, T-1417…T-1423 + ADR-1013-3): 4D-память — префикс `[ММ.ГГГГ | Автор: ]` (автор=target_user), метка `(Внимание: возможно устарело)` для фактов >6 мес (`limits.rag_stale_after_days`), временная группировка фактов в DreamWorker; канон dream/lore — PREV-снапшот + байт-тесты, `PROMPT_MIGRATIONS` не трогаем)
- `cognition-belief-decay-round1013` — **Раунд 10.13, 13.09.2026** (F2, T-1424…T-1433): Belief Decay (−0.1/мес без подкрепления >6 мес) + архив `graph_facts.status='archived_belief'`; Resurrection — векторный резонанс (пенальти −0.3, порог 0.78), Сон-Реаниматор, граф-активация (связки 2–3 узлов в L1); DDL-free, флаг `flags.belief_decay_enabled` OFF)
- `cognition-deep-sleep-round1013` — **Раунд 10.13, 13.09.2026** (F3, T-1434…T-1442 + ADR-1013-1): «Глубокий сон» — после обычного сна, «Поиск по якорям» (свежие beliefs + 12ч-выжимка → RAG) → синтез «Мост времени» → парадигмы (`origin='derived_belief'`, `belief_meta.type='paradigm'`, weight 0.55); роутер `LLMClient.generate_worker` (роли intel_history/intel_bg); флаг `flags.deep_sleep_enabled` OFF)
- `cognition-llm-providers-round1013` — **Раунд 10.13, 13.09.2026** (F4, T-1443…T-1447 + ADR-1013-1): 2 provider-блока `intel_history` / `intel_bg` (parent+subBlocks, `providerCoveredKeys`, `_BLOCK_SAVED_KEY`), ключи `models.intel_<role>_*` + `keys.intel_<role>_api_key`, фоллбэк на `models.llm_*`/`keys.llm_api_key`; R17 `{configured,last4}`)
- `cognition-dashboard-round1013` — **Раунд 10.13, 13.09.2026** (F5, T-1448…T-1458 + ADR-1013-2): дашборд «Осмысление» на «Статусе» (2 бегущие строки, бейджи фаз) + виджет «Интеллект и Память» в «Сводке» (пульс, прогресс-бары, метрики БД, Timeline); граф vis-network standalone UMD self-host lazy-load (nodes/edges 120/240, polling 15с); аддитивные read-API)
- `cognition-ekg-logs-bugfix-round1013` — **Раунд 10.13, 13.09.2026** (F6, T-1459…T-1464): SVG-EKG Heartbeat (Load/CPU/RAM, спокойный зелёный ↔ оранжево-красный), старый линейный аптайм-график удалён; багфикс «Логи» — серверный комбинированный тег ERROR+WARNING + дефолт фильтра при открытии)
- `cognition-user-guide-round1013` — **Раунд 10.13, 13.09.2026** (F7, T-1465…T-1467): `plans/docs/intelligence_user_guide.md` — простыми словами, без аббревиатур, ироничный тон; задел под раздел «Справка» + ссылка из README; APP_VERSION 2.57.0)
- `cognition-irony-dossier-round1013` — **Раунд 10.13, 13.09.2026** (F8, T-1468…T-1476 + ADR-1013-3): иронический фильтр в промпте Досье (LoreWorker + `build_persona_card`), мемы `graph_facts.status='chat_meme'`, `real_facts`=confirmed+target_user, блоки [Факты]/[Локальные мемы/Ярлыки]; флаг `flags.irony_filter_enabled` OFF)
- `providers-kostik-round1012` — **Раунд 10.12, 13.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1012-1, FOLLOWS round10.11-epic): развязка эмбеддингов (`models.embedding_base_url`=apinet.cloud/v1, `keys.embedding_api_key`, отдельный httpx-кэш `_embed_client`) от прямых ответов (`models.llm_base_url`=nano-gpt.com/api/v1), фикс 422 сохранения глобальных ключей (`saveConfigItem`/`saveBlock`/`saveKeyItem`), объединённые блоки подключений с display-name, JSON-список фраз Костика (`reactions.kostik_replies`, 14 фраз) + `flags.kostik_enabled` + owner-блок PERMsoc; каталог 405/90/377/mapped 88/categorized 381; тесты 5211 passed / 0 failed; §33)
- `llm-providers-refactor-round1011` — **Раунд 10.11, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1011-1/2/3, T-1340…T-1381): saved-key probe `/api/llm/test` без повторного ввода (R17-safe, `{configured,last4}`), рефакторинг «LLM Провайдеры» (nav-icons 22px + pinned профиль, две зоны «Подключения»/«Расширенные» computed, embeddings 3 подблока, video-fallback выше, media-share/теххаос внизу), непрерывный key-history chart (`spanGaps`+`stepped`, linear-ось, `parsing:false`), docs-отчёт `plans/docs/memory_sleep_nostalgia_lore_report.md`; каталог 400/90/372/mapped 88, `categorized` 376 (sanctioned Δ, infra 28→24); тесты 5172 passed / 0 failed; §32)
- `admin-ui-round1010` — **Раунд 10.10, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1010-1/2/3, T-1315…T-1328: fullscreen safe-area паддинг шапки, мобильный график доступности ключей (окно от конца, дорожки + 300с сетка), реальные значения полей «Провайдеров» (`blockFieldValue`), ЛС heavy-modules OFF (`disable_dm_heavy_modules.py`, прод data-run 1 ЛС), «Роли» с аватаром+ником+мелким серым ID; каталог 400/90/372/mapped 88; тесты 5145 passed / 1 skipped; §31)
- `admin-ui-round109` — **Раунд 10.9, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-109; T-1270…T-1314: PERMsoc owner-блоки + `flags.slavik_enabled`, сохранение скролла (`_preserveScroll`), переписанные описания/титулы, удаление «Тяжёлых фич», «Бюджет фона»→«Сводка», dashboard «Доступность ключей» (4 группы) + реальный health `probe_openai`, 7 `models.*_display_name`, `max-w-3xl`, градиент 14s/18s; каталог 400/90/372/mapped 88; тесты 5105; §30)
- `admin-ui-round108` — **Раунд 10.8, 11.09.2026** (единственная фича, spec @Architect + tasks @PM, T-1243…: переименование разделов, emoji→Material-иконки (субсет 20→37, 18 388 B), фикс логов на Android, route-driven окна «Доступов», README; тесты 5076; §29; ADR-001-access-windows-modal + ADR-002-icon-subset-parity)
- `admin-ui-bugfixes-round107` — **Раунд 10.7, 11.09.2026** (единственная фича, spec T-1224: UI/UX-багфиксы админ-минги — scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей, uptime gap-fill, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; тесты 5042; §28)
- `tma-ia-modules-rework` — **Раунд 10.6, 11.09.2026** (единственная фича, T-1155…T-1223: IA-ребейлд TMA — единый navbar, 11 Модулей-тумблеров, Настройки AI (7) + RAG→Память, чистый PERMsoc, Леха/Костик раздельно, provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89; тесты 5027; §27)
- `tma-relume-redesign` — **Раунд 10.5, 10.09.2026** (единственная фича, T-1066…T-1148: полный редизайн TMA по Relume — navbar/hubs/hash-роутинг/scope-switcher/key-history/матрица ролей/градиенты/Material Symbols; тесты 4962; §26)
- `frontend-advanced-collapse-default` — **Раунд 10.4, 10.09.2026** (D, T-1018…T-1023: аккордеоны «Расширенные» свёрнуты по умолчанию, AC-B1-тест; §24)
- `frontend-memory-sleep-nostalgia` — **Раунд 10.4, 10.09.2026** (C, T-1006…T-1017: «Память» + вкладки «Сон»/«Ностальгия», progressive-разметка; §24)
- `frontend-llm-providers-layout` — **Раунд 10.4, 10.09.2026** (E, T-1024…T-1032: LLM Провайдеры — 4 секции: модели→ключи→фолбэк→расширенные; §24)
- `frontend-reorg-modules-reactions` — **Раунд 10.4, 10.09.2026** (A, T-974…T-989: «Функции PERMsoc» 17 групп (девиансия D-A1), «Модули», лор-настройки; §24)
- `frontend-limits-temperature-budgets` — **Раунд 10.4, 10.09.2026** (B, T-990…T-1005: бюджеты per-чат (флаг + бэкфил), select-температура, «Имена людей» + build_alias_resolver; §24)
- `frontend-relations-participants` — **Раунд 10.4, 10.09.2026** (F, T-1033…T-1044: вкладка «Участники и отношения», перенос блока участников; §24)
- `backend-relations-nickname` — **Раунд 10.4, 10.09.2026** (H, T-1057…T-1065: username для всех строк каскада имён, Semaphore(5), фото топ-50, R16; §24)
- `backend-chat-1002661910336-scaling` — **Раунд 10.4, 10.09.2026** (G, T-1045…T-1056: per-chat лимиты ×1.5–×2 (15 override, бэкфил), _resolve_from_root-харденинг, граница G-4; §24/§25)
- `tma-chat-selector-fixes` — **Раунд 10.3, 09–10.09.2026** (F-13, T-925…T-944: единый селектор чата, удаление ✕/пикера, фикс пустых вкладок, z-index 45; §23)
- `dm-user-settings` — **Раунд 10.3, 09–10.09.2026** (F-14, T-945…T-964: ЛС-настройки вариант A, саммари default-off; §23)
- `direct-sandbox-budget-investigation` — **Раунд 10.3, 09–10.09.2026** (F-15, T-965…T-973: прод-диагностика sandbox budget + graphrag JSON, фиксы; §23/§24)
- `multi-chat-rbac-byok` — **Раунд 10, 08.09.2026** (F-7, T-843…T-869: RBAC-роли + chat_params-слой + BYOK + бюджеты; §22)
- `tma-ui-fixes` — **Раунд 10, 08.09.2026** (F-8, T-870…T-877: 8 UI/UX-фиксов TMA; §22)
- `permsoc-module-isolation` — **Раунд 10, 08.09.2026** (F-9, T-878…T-889: плагин PERMsoc + девиансия M-F-9 (а); §22)
- `feature-gates-worker-budget` — **Раунд 10, 08.09.2026** (F-10, T-890…T-902: Opt-In-гейты + worker-бюджет; §22)
- `tma-ia-progressive-disclosure` — **Раунд 10, 08.09.2026** (F-11, T-903…T-913: IA/меню 5-секций + прогрессивное раскрытие; §22)
- `global-oversight-dashboard` — **Раунд 10, 08.09.2026** (F-12, T-914…T-924: Oversight + kill-switch; §22)
- `agi-memory-implementation` — Раунд 9, 06.09.2026 (relations A-Life, сон, ностальгия, dig_into_lore, канон R9; ARCHITECTURE §21)
- `context-layer-x-features` — Раунд 8 (24 пункта CONTEXT_RESEARCH; §20)
- `chat-lore-management-v2` — Раунд 7 (PG chat_profiles, TMA «Лор чатов»; §19)
- `history-import-hybrid-memory` — Раунд 6 (FTS5 + GraphRAG, миграция v7; §18)
- `betterstack-lore-prompts-round5` — Раунд 5 (§17)
- `betterstack-own-handler-video-memory-cmds` — Раунд 4 (§16)
- `multimodal-summarization-tools-reactions-ui` — Эпик 04.09 (§13)
- `tg-video-tool-calling-fixes` — Bugfix 04.09 (§14)
- `video-multimodal-pipeline-and-incidents` — Раунд 3 (§15)

## Research (plans/docs/)

`multi-chat-scaling-research.md` (07.09.2026 — ИСХОДНИК раунда 10, вариант A),
`prod-params-audit-2026-09.md`, `memory-project-overview.md`,
`CONTEXT_RESEARCH.md`, `agi-memory-research.md`, `chat-lore-management-research.md`,
`sqlite-to-pg-research.md`, `factcheck-audit.md`, `memory-import-research.md`,
`research-directchat-digest.md`, `memory_sleep_nostalgia_lore_report.md`
(12.09.2026 — plain-language отчёт раунда 10.11: память/сон/ностальгия/лор,
тайминги, сборка контекста; каждая цифра с `file:line`), `canon/` (architecture.md, backlog.md).

## Граф: краткий обзор (узел AdminBot + feature-*)

> **Актуализация 15.09.2026 (после 10.18):** каталог **REGISTRY 436** / Settings **406** /
> categorized **411** / GROUPS 90 / mapped 88 / `TAB_RULES` 19; **SQLite v10** (`edges.fact_id`,
> nullable + индекс); релиз **`release-round1018`** (commit **`16a8c0b`**, прод PID 2319614);
> новых фича-флагов нет. Линии ниже — исторические снимки раундов 10–10.13.

- **adminbot-backend** — aiogram 3.31 (polling) + FastAPI (`web/app.py`) + asyncpg + aiosqlite; APP_VERSION=2.57.0 (раунд 10.13); порядок роутеров bot.py: slava_presence → alan_greeting → kostik → alan → dead_page → war_alert → common → olya → slavik → vasya (без изменений). F-12 добавил oversight-API (web/api/oversight.py), F-7/F-10 — access/gates/budget-роуты.
- **adminbot-pg-schema** — `bot_settings` (key/value JSONB/category), `bot_roles` (permissions JSONB; F-7 добавил `role_type`), `bot_admins`, `chat_profiles` (manual/auto лор + `relations` JSONB; **F-7 добавил `chat_params` JSONB**, **F-10 добавил `gates_opt_in`**), `chat_lore_history` (F-7 расширил CHECK поля: chat_params/chat_keys/gates), `chat_links`, `chat_admins` (F-7 добавил `role_name`), `uptime_events`. **Новые таблицы раунда 10: `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`** (итог — DDL-код в `services/pg_db.py`, прод-DDL @DevOps).
- **adminbot-sqlite-schema** — `users_meta` (стадии отношений), `smart_messages` (FTS5), `nodes/edges`, `graph_facts` (v1–v8), `dream_state`, `memory_dream_log` (бюджет суток), `nostalgia_log` и др. Миграция памяти sqlite→PG ЗАМОРОЖЕНА (04.09.2026). Вне скоупа раунда 10.
- **hot-config-layer** — `services/hot_config.py::hot.get(pg_key, default)`; ConfigCache (`services/config_cache.py`) — in-memory над PG, R6 fail-open. Цепочка глобальная; **F-7 добавил per-chat слой `hot_chat` (chat_params → bot_settings → дефолт) параллельно — hot.get/ConfigCache не менялись**.
- **llm-client-key-resolution** — `services/llm_client.py`; ключ: `hot.get("keys.llm_api_key", settings.LLM_API_KEY)`; фоллбэки `keys.llm_fallback_api_key` + embed-каскад (Google AI Studio, 2 ключа). **F-7 добавил BYOK: `_resolve_api_key_and_source(chat_id)` — свой ключ чата → allow_global=false → бюджет → глобальный; sandbox `content.no_key_reply` (фикс R6: per-call, без инстанс-стейта).**
- **param-catalog** — `services/param_catalog.py` REGISTRY ParamSpec; F-7 добавил поле `per_chat` (whitelist), F-11 — `progressive_level`, F-9/F-10 — новые ключи (`flags.permsoc_enabled`, `limits.worker_daily_*`, `limits.chat_global_key_budget_*`, `content.no_key_reply`); раунды 10.9–10.13 — итеративный прирост. Итог раунда 10.13: REGISTRY **427** / GROUPS **90** / Settings **399** / mapped **88** / categorized **403**, TAB_RULES 19 (санкционированный Δ ADR-1013-1 + флаг F8).
- **rbac-v2** — `services/permissions.py` + неймспейсы `section./param./key./action.`; GET /api/config маскирует секреты {configured,last4}; POST — per-key права. **F-7 расширил: role_type-иерархия (services/roles.py), access_for, param_permissions, локальные чат-роли (chat_admins.role_name)**; `permissions.py` остаётся чистым матчером.
- **tma-frontend** — Vue 3 global (без сборки): `web/index.html` + `web/app.js` + FastAPI `/api/*`. Вкладки: LLM Провайдеры, Промпты, Лимиты, Память и RAG, Реакции и Триггеры, Доступы, Лор чатов, Статус, Как это работает. **Раунд 10 реализован: F-8 (UI-фиксы) + F-11 (навигация 5 меню + селектор чатов + прогрессивное раскрытие + вкладка modules_feats) + F-12 (oversight) поверх F-7 (X-Chat-Id, роль-пикер, BYOK-поля).** **Хотфикс 10.1 (8eae899):** закрыты БГ1–БГ4 рекона — `basicItems`/`advancedItems` (+ прогрессивное раскрытие на всех конфиг-вкладках), логи (scrollTop=0, клик-копия, 0.70rem), лор (топ-50, ленивые аватары 300ms, каскад имён alias→nickname→username→id, фулскрин), modules_feats (бюджет всегда).
- **legacy-triggers-permsoc** — Славик (479167456), Костя (350803143), Леха/Алан (138811255), Оля (834424825, единственный с флагом `flags.olya_enabled`), передразнивания (`flags.mimic_enabled`); ID в группе `reactions_persons`. **F-9 изолировал в плагин services/permsoc.py с master-гейтом flags.permsoc_enabled + PermsocGateFilter (девиансия M-F-9 (а): alan — master-only).**
- **background-workers** — LoreWorker, DreamWorker, NostalgiaWorker, Summary/Goodmorning/валер-подобные; бюджет сна — `memory_dream_log.tokens` за local-сутки. **F-10 перевёл тяжёлые фичи под жёсткий Opt-In (gates + gates_opt_in) + суточный ledger `worker_budget` (global/per-chat лимиты LLM-вызовов/токенов, деградация nostalgia→lore→dream).**
- **plans-structure** — см. разделы выше; раунд 10 ЗАВЕРШЁН: 6 фич F-7…F-12 (entity `feature-*` в графе, статус **archived**, ARCHIVED_IN plans-structure), 82 задачи T-843…T-924; plans/archive/ — **15 папок**; раунд закоммичен (69be94e + 533bf13,
HEAD == origin/master == 533bf13); **милстоун `round10.1-hotfix`** (AdminBot → COMPLETED,
FIXES tma-frontend, RESOLVES recon: tma-round10-postdeploy-bugs) — хотфикс 10.1 закоммичен
и задеплоен (8eae899, PID 159455), HEAD == origin/master == 8eae899;
**милстоун `round10.2-fixes`** (AdminBot → COMPLETED + DEPLOYED; RESOLVES
recon: tma-bugs-7-post-10.1; FIXES 7 bug: tma-*) — раунд 10.2 ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (d30b203, 28 файлов, тесты 4760, PID 454654),
HEAD == origin/master == d30b203; **новый милстоун `server-hardening-102`**
(AdminBot → DEPLOYED) — fail2ban/ufw/SSH-харденинг 09.09.2026 (см. раздел
«Безопасность сервера» выше); **милстоун `round10.3-epic` (AdminBot → COMPLETED +
DEPLOYED, конвенция round10.2-fixes)** — раунд 10.3 ЗАВЕРШЁН, ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (коммит 1410a68, 09.09.2026 12:33 UTC; рестарт 12:37 UTC, active;
тесты 4831; прод-диагностика задачи 5 — recon: direct-chat-sandbox-budget);
3 фичи F-13 tma-chat-selector-fixes + F-14 dm-user-settings + F-15
direct-sandbox-budget-investigation (T-925…T-973) → **ARCHIVED_IN plans-structure
+ WAS_PART_OF round10.3-epic** (HAS_PLAN/PLANNED_IN/PART_OF/ARCHITECTED удалены,
конвенция F-7…F-12); ARCHITECTURE.md §23/§24;
**милстоун `round10.4-epic` (AdminBot → COMPLETED + DEPLOYED, 10.09.2026)** —
раунд 10.4 «Реструктуризация TMA-миниаппа + точечные фиксы» (9 пунктов ТЗ):
8 фич feature-frontend-advanced-collapse-default (D), feature-frontend-memory-sleep-nostalgia
(C), feature-frontend-llm-providers-layout (E), feature-frontend-reorg-modules-reactions
(A), feature-frontend-limits-temperature-budgets (B), feature-frontend-relations-participants
(F), feature-backend-relations-nickname (H), feature-backend-chat-1002661910336-scaling
(G) — **все COMPLETED + ARCHIVED** (WAS_PART_OF round10.4-epic + ARCHIVED_IN
plans-structure; HAS_PLAN/PLANNED_IN/ARCHITECTED_IN удалены — конвенция F-7…F-12;
HAS_SPEC/HAS_TASKS и цепочка DEPENDS_ON D←C←E←A←B←F←H←G сохранены как исторический
факт); архитектурная фаза зафиксирована @Architect (KG: round10.4-specs +
round10.4-dependencies; Step 0 — recon: tma-structure-10.4); конфликт-матрица:
F-1 PRECEDES B/G — учтён (фича активна), F-3/F-4 AFTER round10.4-epic (активны),
F-5 AFTER B/G (активна, R10.4-7 — её кандидат), F-6 (plans/features/user-aliases-admin)
SUPERSEDED_BY round10.4-epic — подтверждена; REGISTRY 383/**74**/359 (коррекция
71→74 — ре-дизайн 10.2 BUG-3; MED-017); техдолг-кандидаты следующего раунда —
KG `tech-debt-round10.4` (R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004-остаток);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **26 папок**;
HEAD == origin/master == `0bdf272` (коммит раунда 10.4: бэкфилы применены,
CHAT_THREAD_MAX_CHARS=2000, тесты 4860, прод active);
**милстоун `round10.5-epic`** (AdminBot → COMPLETED + DEPLOYED, 10.09.2026) —
раунд 10.5 «Редизайн TMA по референсу Relume + гигиена репозитория»: единственная
фича `tma-relume-redesign` (T-1066…T-1148) → COMPLETED + DEPLOYED + WAS_PART_OF
round10.5-epic + ARCHIVED_IN plans-structure (HAS_PLAN/HAS_FEATURE/RELATED_TO/
HAS_DESIGN_PROJECT — сохранены как исторический факт; HAS_PLAN не удалялся);
ARCHITECTURE.md §9/§25/§26; R10.5-1/-2/-4 закрыты, техдолг-кандидаты — KG
`tech-debt-round10.5` (R10.5-3/-5/-6/-7, ARCH §25); plans/features/ — **6 активных**
(F-1…F-6); plans/archive/ — **27 папок**; HEAD == origin/master == `c01ed72`
(коммиты 918f675 + c01ed72, тесты 4962, деплой 198.46.175.136 active/health 200,
0 ошибок); остаётся ручной live-smoke T-1153 + опц. betterstack 401.
**милстоун `round10.6-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.6 «Переработка IA TMA»: единственная фича `tma-ia-modules-rework` (T-1155…T-1223)
→ COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.6-epic +
ARCHIVED_IN plans-structure; sidebar удалён, «Модули» (11) + «Настройки AI» (7) + чистый
PERMsoc + provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89/TAB_RULES 19;
5 master-флагов default ON с реальными гейтами; ARCHITECTURE.md §27 (+§25/§9/§6/§2);
Scanner 0 blocker/0 major (R10.6-1/-3 закрыты; техдолг-кандидаты — KG `tech-debt-round10.6`:
R10.6-2/-4/-5/-6); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **28 папок**;
HEAD == origin/master == `4055434` (коммиты 6f91e8b + 4055434, тесты 5027, деплой
198.46.175.136 active/health 200, 0 tracebacks); остаётся ручной live-smoke (desktop/Android
WebView) + опц. betterstack 401.
**милстоун `round10.7-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.7 «UI/UX-багфиксы админ-минги»: единственная фича `admin-ui-bugfixes-round107`
(spec T-1224) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.7-epic
+ ARCHIVED_IN plans-structure; scope*-computed, safe-area шапки, компактный юзер-блок,
nav labels без per-letter wrap, ellipsis ключей, uptime gap-fill (5-мин сетка/down),
clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; ARCHITECTURE.md §28 (+§9/§25);
Scanner 0 blocker/0 major (R10.6-5 закрыт; техдолг-кандидаты — KG `tech-debt-round10.7`:
R10.7-1…R10.7-5); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **29 папок**;
HEAD == origin/master == `bb59476` (коммиты 7f3b790 + bb59476, тесты 5042, деплой
198.46.175.136 active/health 200, 0 errors); остаётся ручной live-smoke исправленного UI
+ опц. betterstack 401.
**милстоун `round10.8-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.8 «Точечные UI-правки админ-минги»: единственная фича `admin-ui-round108`
(T-1243…) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.8-epic
+ ARCHIVED_IN plans-structure; переименование разделов, emoji→Material (субсет 20→37,
18 388 B), Android-логи, route-driven окна «Доступов», README, APP_VERSION 2.52.0;
ARCHITECTURE.md §29 (+§1/§9/§25); Scanner 0 blocker/0 major (R10.8-1/-5 закрыты;
техдолг — KG `tech-debt-round10.8`: R10.8-2/-3/-4; R10.7-3/-4 закрыты);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **30 папок**;
HEAD == origin/master == `976e335` (коммиты 31d2ce7 + 976e335, тесты 5076, деплой
198.46.175.136 active/health 200, 0 errors, шрифт wOF2 18 388 B); остаётся ручной
Android smoke T-1254 (логи)/T-1258 (окна «Доступов») + опц. betterstack 401.
**милстоун `round10.9-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.9 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round109`
(T-1270…T-1314, spec @Architect + tasks @PM + ADR-109) → COMPLETED + DEPLOYED +
WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.9-epic + ARCHIVED_IN plans-structure;
PERMsoc owner-блоки (4) + `flags.slavik_enabled`, `_preserveScroll` для
`document.scrollingElement`/`.scroll-area`, переписанные описания/титулы,
«Тяжёлые фичи» удалены, «Бюджет фона»→«Сводка», dashboard «Доступность ключей»
(4 группы) + реальный health `probe_openai` (TTL 2xx 60с/ошибки 10с), 7
`models.*_display_name`, форма `max-w-3xl`, градиент 14s/18s; каталог
400/90/372/mapped 88; ARCHITECTURE.md §30 (+§1/§9/§25); Scanner 0 blocker/0 major/
0 medium (3 low R10.9-1/-2/-3 + 3 info R10.9-4/-5/-6; R10.9-6 закрыт; техдолг —
KG `tech-debt-round10.9`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **31 папка**; HEAD == origin/master == `f928225` (коммиты
d2d1215 + f928225, тесты 5105, деплой 198.46.175.136 active/health 200, 0 ошибок,
APP_VERSION 2.53.0); остаётся ручной live Android smoke T-1277/1290/1292/1294/
1302/1305 + опц. betterstack 401. ⚠️ Пункт 2 ТЗ (инфраструктура локального IDE
владельца) — вне скоупа проекта.
**милстоун `round10.10-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.10 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round1010`
(spec @Architect + tasks @PM + ADR-1010-1/2/3; T-1315…T-1328) → COMPLETED + DEPLOYED
+ WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.10-epic + ARCHIVED_IN plans-structure;
fullscreen safe-area padding шапки, мобильный график доступности ключей (окно от
конца), реальные значения полей Провайдеров (`blockFieldValue`), ЛС heavy-modules
OFF (`disable_dm_heavy_modules.py` + data-run 1 ЛС), «Роли» с аватаром+ником+мелким
ID; каталог 400/90/372/mapped 88; ARCHITECTURE.md §31 (+§3/§9/§25); Scanner
0 blocker/0 major/0 medium (low R10.10-1/-2/-3 + info R10.10-4/-5; техдолг —
KG `tech-debt-round10.10`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **32 папки**; HEAD == origin/master == `772db08` (коммиты
d082800 + a477747 + 772db08; тесты 5145 passed / 1 skipped / 0 failed; деплой
198.46.175.136 active/health 200, 0 ошибок, APP_VERSION 2.54.0); остаётся ручной
live Android QA T-1317/1320/1323/1332 + UI spot-check DM-тумблеров OFF T-1328.
**милстоун `round10.11-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.11 «Рефакторинг LLM Провайдеры + проверка сохранённого ключа + key-history
chart + отчёт по памяти»: единственная фича `llm-providers-refactor-round1011`
(spec @Architect + tasks @PM + ADR-1011-1/2/3; T-1340…T-1381) → COMPLETED + DEPLOYED
+ WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.11-epic + ARCHIVED_IN plans-structure;
saved-key probe `/api/llm/test` (R17-safe), nav-icons 22px + pinned профиль, две зоны
«Подключения»/«Расширенные» (computed), embeddings 3 подблока + 4 записи в каталог
(sanctioned Δ: categorized 376, infra 28→24), video-fallback выше, media-share/теххаос
внизу, key-history chart `spanGaps`+`stepped` (linear-ось, `parsing:false`), docs-отчёт
`memory_sleep_nostalgia_lore_report.md`; каталог 400/90/372/mapped 88; ARCHITECTURE.md
§32 (+§5/§9/§25); Scanner CLEAN 0 blocker/0 major/0 medium (R10.11-1/-2/-3 закрыты;
техдолг — KG `tech-debt-round10.11`: R10.11-4/-5/-6); plans/features/ — **6 активных**
(F-1…F-6); plans/archive/ — **33 папки**; HEAD == origin/master == `cbe6ea5` (коммиты
3624789 + cbe6ea5; тесты 5172 passed / 0 failed; деплой 198.46.175.136 active/health 200,
0 ошибок, миграция created=5/skipped=48, APP_VERSION 2.55.0); остаётся ручной live
Android/Telegram QA **T-1377**; наблюдение — pre-restart PID 401 к apinet.cloud (проверить).
**милстоун `round10.12-epic`** (AdminBot → COMPLETED + DEPLOYED, 13.09.2026) —
раунд 10.12 «Развязка эмбеддингов от прямых ответов + 422 глобальных ключей +
объединённые блоки подключений + фразы Костика»: единственная фича
`providers-kostik-round1012` (spec @Architect + tasks @PM + ADR-1012-1) → COMPLETED +
DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.12-epic + ARCHIVED_IN
plans-structure; `round10.12-epic FOLLOWS round10.11-epic`; models.embedding_base_url
=apinet.cloud/v1 + keys.embedding_api_key (OD-1, фолбэк на llm-ключ) /
models.llm_base_url=nano-gpt.com/api/v1 (отдельный read-path + httpx-кэш
`_embed_client`); global-save для per_chat=false во всех трёх путях; merged-блоки с
display-name (STT/video display-name разделены, свопа нет); reactions.kostik_replies
(14 фраз) + flags.kostik_enabled + owner-блок; каталог 405/90/377/mapped 88/
categorized 381; ARCHITECTURE.md §33 (+§5/§9/§12/§25); Scanner clean 0 blocker/0 major/
0 medium (R10.12-1/-5 закрыты; техдолг — KG `tech-debt-round10.12`: R10.12-2/-3/-4);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **34 папки**;
HEAD == origin/master == `bad2b0d` (коммиты 708f7df + bad2b0d; тесты 5211 passed /
0 failed; деплой 198.46.175.136 active/health 200, 0 ошибок, миграция
created=5/skipped=149, APP_VERSION 2.56.0); остаётся ручной live Android/Telegram QA
+ опц. выделенный embedding api key.
**милстоун `round1013-epic-cognition`** (AdminBot → COMPLETED + DEPLOYED, 13.09.2026) —
раунд 10.13 «Cognition / Sleep / Memory Refactor»: **8 фич** (F1 `cognition-4d-memory-round1013`,
F2 `cognition-belief-decay-round1013`, F3 `cognition-deep-sleep-round1013`,
F4 `cognition-llm-providers-round1013`, F5 `cognition-dashboard-round1013`,
F6 `cognition-ekg-logs-bugfix-round1013`, F7 `cognition-user-guide-round1013`,
F8 `cognition-irony-dossier-round1013`; 60 задач T-1417…T-1476) → COMPLETED + DEPLOYED +
WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure (PART_OF/ARCHITECTED
удалены — конвенция round10.12); `round1013-epic-cognition FOLLOWS round10.12-epic`;
созданы `release-v2.57.0-round1013` (AdminBot PRODUCED) и `tech-debt-round10.13` (5 Low).
4D-память + belief decay/Resurrection + «Глубокий сон»/парадигмы + UI-провайдеры
`intel_history`/`intel_bg` + дашборд «Осмысление»/граф vis-network + EKG/фикс логов +
user guide + ирония/досье (`status='chat_meme'`). ARCHITECTURE.md §34 + ADR-1013-1/2/3;
каталог **427**/90/**399**/mapped 88/categorized **403** (TAB_RULES 19); флаги default OFF
(`belief_decay_enabled`/`deep_sleep_enabled`/`irony_filter_enabled`); тесты
**5392 passed / 0 failed** (база 10.12 = 5211, +181); деплой `8800bba`, прод
198.46.175.136 active (PID 1629874)/health 200, APP_VERSION **2.57.0**;
plans/archive/ — **42 папки**; plans/features/ — 6 активных (F-1…F-6);
@Reviewer iter1 Rejected → iter2 APPROVED; @Scanner iter1 0C/1H/4M/9L → iter2 0C/0H/0M/5L;
@Builder — 2 цикла реворков. `plans/metrics.md` — метрики по раундам.

## Факты для планирования (проект)

- HEAD промпт-каноны живут в `plans/docs/canon/`; миграции промптов — `services/prompt_migrations.py`.
- Отношения: manual-стадии в PG `chat_profiles.relations`, авто — SQLite `users_meta.relationship_stage`.
- Тумблеры персоналий по умолчанию выключены только для kucha/mimic/olya; сон/ностальгия/авто-лор — включены по умолчанию (раунд 10 перевёл на жёсткий Opt-In — F-10: `gates_opt_in` + `chat_params.gates`).
- Раунд 10, F-7 (Q5, РЕАЛИЗОВАНО): `per_chat=True` = категории {prompts, limits, flags, reactions, content, memory} и secret=False; `models.*`/`keys.*` — строго глобальные.
- Раунд 10, F-7 (R17/инвариант 2, РЕАЛИЗОВАНО): локальный админ НЕ видит глобальный ключ ни в каком виде; raw-ключи никогда не логируются/не отдаются (S1/S2/S3, R17-аудит).
- Раунд 10, F-9 (Q3, РЕАЛИЗОВАНО): дефолт новых чатов — permsoc OFF; живые чаты включаются бэкфилом `scripts/backfill_permsoc_gates.py` по правилу (-1002661910336 / relations_enabled / manual|auto_lore / chat_admins).
- Раунд 10, F-12 (Q2, РЕАЛИЗОВАНО): приоритет гейтов — явный chat-гейт → `hot.get('flags.<feature>_enabled')` → False; kill-switch = явный `gates[feature]=false`.
- **Follow-up раунда 10 (вне цикла):** unit-тест-гап `backfill_permsoc_gates.py` (прямых тестов бэкфила нет); live-проверка имени CHECK-ограничения `chat_lore_history` на проде (field='gates'/'chat_keys'); предложение расширения `deploy_v2.9.2.py` (DDL + бэкфилы + live-гистограммы при деплое).
- **Follow-up безопасности сервера (ожидают решения владельца):** миграция на SSH-ключи (key migration proposal — password auth пока оставлена по требованию); добавить IP владельца в fail2ban `ignoreip`, если он статический; CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) на другой диск/раздел.
- **Раунд 10.4 (ЗАВЕРШЁН + DEPLOYED, 10.09.2026, коммит 0bdf272):** порядок фич
  D→C→E→A→B→F→H→G выполнен; REGISTRY 383/**74**/359 без изменений (коррекция счётчика
  групп 71→74 — ре-дизайн 10.2 BUG-3; MED-017; новые ключи/группы ЗАПРЕЩЕНЫ);
  SQLite v8, роутеры bot.py, каноны промптов, known_sections() — без дифов;
  девиансия D-A1 реализована (фича A: war/common/goodmorning/word_reactions →
  «Функции PERMsoc», 17 групп); бэкфилы backfill_104_chat_flags.py +
  backfill_104_overrides.py применены; техдолг-кандидаты следующего раунда:
  R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004 (KG `tech-debt-round10.4`);
  конфликт-матрица исходно: F-1 (T-648 атомарный POST) — учтён ДО B/G.
