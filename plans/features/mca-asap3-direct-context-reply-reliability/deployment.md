# deployment.md — mca-asap3-direct-context-reply-reliability (ASAP-3, прод-деплой 2.58.35)

- **Feature-ID:** `mca-asap3-direct-context-reply-reliability` (T-4038…T-4040, §55–§58 ТЗ)
- **Дата деплоя:** 2026-09-29, окно 00:16–01:10 UTC (локально Владивосток 12:16–13:10, +12)
- **Статус: VERIFIED** (gate §58: Reviewer Approved round 2 + prod deploy + live acceptance A–G + post-deploy — см. §8; финальный вердикт DONE — @Orchestrator/reconcile)
- **Разрешение:** @Reviewer `Approved` (round 2, 29.09.2026, binding `8b7db5ad…cf295`) + санкция владельца §55 ТЗ («деплой обязателен», current_task.md + прямая очередь пользователя).

## 1. Preflight — binding (все совпадения побайтовые)

| Поле | Ожидание (review round 2) | Факт | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `87728dc81e3f2508beca3bc1a8c58e9748ec24c8` | `87728dc` (git log) | ✅ |
| Working-Tree-Hash | `8b7db5ad8d2f32d864e6ce558844283124ee543318f4ac2239f02e0fa96cf295` | пересчёт `tools/_asap3_wth.py` по рецепту review: **entries=41, missing=0, wth=8b7db5ad…cf295** | ✅ побайтово |
| Spec-Hash | `83E7B0286A66C28E17BE97D2113A5C1EF9D40FEA6706DA08729A763251E285AA` | Get-FileHash — совпал | ✅ |
| ADR-1028-2 Hash | `77C2F12AB6AF2E231130095F1025C83A690C3D627F8E058F1FC4255993F2356D` | Get-FileHash — совпал | ✅ |

Дрейфа release-входов нет → approval round 2 признан актуальным.

## 2. Коммиты и состав (feat + docs)

| Коммит | Что | Файлов |
|---|---|---|
| `2deb287` | `feat(round1028): ASAP-3 Direct Context Reliability + Autonomous Decision Matrix — model-aware composer, verbatim episodes, FORCE_REPLY/REPLY/REACT/SILENT+🗿 (APP_VERSION 2.58.35)` | 37 |
| `e6af6b2` | `docs(round1028): ASAP-3 plans — spec/ADR-1028-2/tasks/evidence (H1/H2/H3+M1 rework)/review round 2 APPROVED + WTH manifest + full_audit_results entry` | 11 |

**Состав feat-коммита (хирургический стейджинг по staging-перечню review round 1 + директива Orchestrator на import-closure):**

- **Новые файлы фичи (verbatim):** `services/model_capacity.py`, `services/direct_context_composer.py`, 4 pytest-файла `tests/test_direct_*_asap3.py`, `tests/js/round1028_asap3_direct_context_test.js`, `tools/_asap3_webapp_dev.py`.
- **Import-closure (волновые новые модули, verbatim, без правок):** `services/mca_gates.py`, `services/mca_retrieval_context.py`, `services/mca_events.py` (транзитивное замыкание: mca_retrieval_context→mca_gates; mca_events→mca_gates+agentic_events+log_ring).
- **M-файл-исключение замыкания:** `services/token_counter.py` — дельта REQUIRED: `has_protected_spans`/`append_protected_spans` импортируются композером на уровне модуля (review L-ASAP3-4: «модуль нужен рантайму»); дельта чисто аддитивная (+`import re`, +2 хунка новых функций; `resolve_context_tokens`/`safe_budget` не тронуты — D11 проверен по диффу). Без неё чистый чекаут не импортируется.
- **Изменённые целиком (ASAP-3-скоуп):** `config/settings.py`, `services/agentic_events.py`, `services/smartmodule_utils.py`, `services/param_catalog.py`, `web/app.js`, `tests/conftest.py`, `pytest.ini`, `README.md`, F8-артефакты (tsv/meta/screen-map/2 fixtures), пин-тесты (`test_param_catalog`, `test_round1025_f8_registry`, `test_decision_making_round1026`, `test_agentic_events_round1026`, `test_telegram_reactions_round1026`, `round1025_hotfix{7,8,9,10}*.js`).
- **Хирургические хунки:** `services/direct_chat_service.py` — 18 полных ASAP-3 хунков + 3 расщеплённых смешанных (из #07 извлечён только ASAP-3-блок tg-id хелперов `_tg_id_of_row`/`_tg_id_of_ref`; из #18 — только autonomous-reply-метрика; из #29 — ASAP-3 блок composer'а с сохранением HEAD-return, БЕЗ чужих mca-01/04a/07 call-site и `_build_evidence_bundle`); `web/index.html` — 2 из 4 хунков (Direct Context карточка + force-keywords read-only; mca-17a хунки `@~2365`/`@~4312` остались в дереве); `web/api/routes.py` — 1 из 3 хунков (`GET /direct/context-diagnostics`; mca-17a фильтры `@~1700`/`@~1723` остались в дереве).
- **Минимальные композиционные адаптации (2 строки, задокументировано):** в диспетчере композера `out_excluded=None` (excluded-проводка mca-07 вне релиза) и в fail-open ветке убран несуществующий на HEAD-сигнатуре kwarg. Обнаружены и исправлены ДО push верификацией на чистом worktree (см. §3).

**Чужие M-файлы волны НЕ закоммичены — подтверждено:** `git diff --name-only 87728dc..HEAD` (48 файлов) не содержит ни одного из: `handlers/*`, `services/database.py`, `services/summary_*`, `services/{message_identity,provenance,safe_fetch,task_supervisor}.py`, `web/api/oversight.py`, `tests/test_direct_chat.py`, `tests/test_tool_coordinator_round1026.py`, `tests/test_mca*`, `plans/archive/mca-*`; рабочее дерево волны (156 записей status) сохранено незакоммиченным.

## 3. Верификация замыкания импортов (worktree ДО push — по директиве)

`git worktree add` на `2deb287` (финальный amend) в чистую папку:

- `python -c "import services.direct_chat_service / direct_context_composer / model_capacity / mca_gates / mca_retrieval_context / mca_events"` → **IMPORTS OK**, `APP_VERSION = 2.58.35`, composer default ON.
- **pytest-срез (10 файлов, чистый чекаут): 525 passed / 2 failed** — оба failed = `test_round1025_f8_registry::TestFrozenInvariants::{test_ddl_source_unchanged, test_routes_file_unchanged}`: frozen-SHA256 пины F11 зафиксированы Builder'ом на ПОЛНОМ WIP-дереве (mca-17a хунки в routes.py и др.), а релиз — хирургическая композиция без чужих хунков. Известное следствие staging-решения ревью — прецедент ASAP-2.1 deployment.md §2 (4 пин-теста той же природы). На проде не воспроизводится (тесты на проде не гоняются; F8-функционал проверен живым импортом — §5).
- История итераций: 1-я сборка поймала `NameError: out_excluded` (29 e2e-падений ASAP-3) и `TypeError … missing 'out_excluded'` — дефекты композиции смешанных хунков; исправлены amend'ами ДО push (финал `2deb287`), после чего 525/2.

## 4. Прод до/после (сервер 198.46.175.136:/var/www/admin_bot, systemd `admin_bot`)

- Прод до: HEAD `8a0fa6c` (2.58.34), MainPID 1926730, tracked-дерево чистое (13 untracked-бакапов — не мешают ff).
- `git pull --ff-only`: `8a0fa6c → e6af6b2` (fast-forward, без force). Диск `APP_VERSION = "2.58.35"` ✓, ast-parse ключевых файлов ✓.
- **T-4003 baseline собран ДО деплоя** (7 дней, 2026-09-22→09-29): `direct: global context truncated` = **61**; `direct: thread truncated` = 0; silent/react/ignored-строки = 42; coordinator: action=reply ×102, action=tool ×10; Traceback = 27 (известный класс nano-gpt деградаций); `direct_metric` строк = 0 (фича не задеплоена).
- **Сид PG (B-ASAP3-3, ДО рестарта):** `seed_asap3_flags.py` (прецедент seed_asap2_keys.py 2.58.33): `INSERT INTO bot_settings … ('flags.chat_silent_ack_enabled','true'::jsonb,'flags'), ('flags.chat_autonomous_reply_enabled','true'::jsonb,'flags') ON CONFLICT (key) DO NOTHING` → **INSERT 0 1 ×2**, верификация чтением: оба ключа = true [flags]. Идемпотентен.
- **Рестарт #1:** 00:21:36 UTC отправлен, active 00:22:37 UTC (остановка ~60с — известный pre-existing TimeoutStopSec/SIGKILL), MainPID **2026443**, NRestarts=0.
- Старт-лог: `[pg_db] asyncpg pool created`, `[pg_db] DDL ok`, `starter bot_settings seeded: 416 (ON CONFLICT DO NOTHING)` (+1 к 415 — новый Settings-field ключ сидится сам), `[config_cache] initialized: settings=458` (= 456+2 — оба сид-ключа видны конфиг-пути), 14× prompt_migration «уже новый канон» (0 перезаписей канонов), threshold/budget-миграции «уже новый дефолт», polling/lifespan поднялись. **Traceback/ERROR в окне старта: 0.**
- .env: Δ env=0 (новых env-ключей фича не требует; kill-switch'и default ON).

## 5. Post-deploy статические проверки

| # | Проверка | Факт | Вывод |
|---|---|---|---|
| 1 | `GET /api/health` / `GET /healthz` | HTTP 200 `{"status":"ok"}`; `{"status":"ok","version":"2.58.35"}` | ✅ |
| 2 | Каталог живым импортом на проде (точный F8-рецепт) | **REGISTRY=483, Settings dataclass=423 (covered==fields: True), categorized=458, GROUPS=105, _TAB_BY_GROUP=103, TAB_RULES=21** | ✅ 483/423/458/105/103/21 |
| 3 | ΔDDL | SQLite `user_version` = 12 (без изменений); в 48-файловом range нет db/pg_db-миграций; старт-лог — рутиный `[pg_db] DDL ok` | ✅ ΔDDL=0 |
| 4 | Kill-switch-инвентарь | `DIRECT_CONTEXT_COMPOSER_ENABLED=True`, `DIRECT_COORDINATOR_ENABLED=True`, `DIRECT_DECISION_MAKING_ENABLED=True`, `DIRECT_SILENT_ACK_ENABLED=True`, `CHAT_AUTONOMOUS_REPLY_ENABLED=True` | ✅ все ON |
| 5 | `GET /api/direct/context-diagnostics` (без auth) | HTTP 401 (endpoint существует, RBAC-гейт; не 404) | ✅ |
| 6 | Per-chat ключи в каталоге/конфиг-пути | `flags.chat_silent_ack_enabled` + `flags.chat_autonomous_reply_enabled` — сажались сидом, `config_cache settings=458` подтверждает видимость | ✅ |

## 6. Деплой-гейт: миниапп «Принятие решений» (реальный прод-контур)

Механизм: подписанный TMA initData сгенерирован НА СЕРВЕРЕ (`gen_initdata.py`, HMAC «WebAppData»; токен не покидал сервер и не попал в evidence), инжект `sessionStorage['adminbot.initData']`, прод `https://admin-bot.duckdns.org/web/`, скоуп-селектор → PERMsoc (ЧАТ), вкладка «Основные настройки».

- **Секция «Принятие решений» рендерит 3/3 обязательных тумблера**: «Silent-подтверждение 🗿» (`flags.chat_silent_ack_enabled` — H3 закрыт в реальном контуре), «Автономные ответы на reply боту» (`flags.chat_autonomous_reply_enabled`), «Использовать реакции вместо ответа» (`flags.chat_decision_reactions_enabled`) — все ON (дефолт из сида) + force-keywords read-only display.
- **Клик переживает reload:** клик 🗿-тумблера → ровно **1 POST /api/config** `{"key":"flags.chat_silent_ack_enabled","value":false}` (перехват fetch) → полный reload → состояние **false** персистентно (per-chat override) → возврат в ON → reload → **true** (прод в дефолтном сида-состоянии).
- Карточка **Direct Context** (Dynamic/Unlimited, описания §34, «Диагностика последнего прогона») рендерится в том же контуре.
- Скриншоты: `plans/features/mca-asap3-…/artifacts/asap3_prod_deploy_decision_toggles.png`, `…asap3_prod_deploy_direct_context_card.png`.

## 7. Live acceptance §56 (PERMsoc −1002661910336) — инструментированный сухой прогон + натуральное окно

**Метод:** на сервере (код 2.58.35, прод-конфиг ConfigCache+ChatParamsCache wiring как bot.py, реальный PG/SQLite — вся история PERMsoc, реальный bot-identity через getMe). Мокались ТОЛЬКО исходящие эффекты (`bot.send_message`, `react_moai`, `llm.generate` — консистентный canned-текст): **в Telegram ничего не отправлено и реакций не ставилось** (без side effects в живом чате; механики доставки — pre-existing прод-пути). Инструмент: `/home/nik/asap3_live_acceptance.py`.

| Сценарий | Факт (события/счётчики) | Вывод |
|---|---|---|
| **A force reply** («бот, …», не reply) | `DIRECT_TRIGGER trigger_type=force_keyword force_reply_required=True` → `direct_metric direct_force_reply_total count=1` → `DECISION_COMPLETE action=reply reason=force_direct` → reply sent | ✅ бот отвечает гарантированно, не молчит; шорт-каты не достигнуты |
| **B autonomous reply** (reply-to-bot, вопрос) | `DIRECT_TRIGGER trigger_type=reply_to_bot force=False` → `DECISION_COMPLETE action=reply reason=question` → `direct_autonomous_reply_total count=1` → reply sent | ✅ автономный REPLY через Decision Making |
| **C REACT** (reply «ахахах…») | `DECISION_COMPLETE action=react reason=laughter` → `[decision] action=react reason=laughter reaction=😂` (детерминированный набор класса; без LLM) → `direct_autonomous_react_total count=1` | ✅ реакция по классу, текст не генерируется |
| **D SILENT+🗿** (reply «ок…») | `DECISION_COMPLETE action=silent reason=recent_reply` (addressed=True) → `direct_autonomous_silent_total count=1` → `direct_silent_ack_success_total count=1` → **`DIRECT_SILENT_ACK reaction=🗿 success=True`** (конъюнкция reply_to_bot ∧ addressed ∧ decision ∧ SILENT + env-гейт + per-chat гейт из сида) | ✅ конъюнкция работает; fail-soft-механика |
| **E фон** | Фоновые сообщения не порождают DIRECT_*/DECISION_* событий (гейт хендлера не тронут); крон-саммари PERMsoc 01:02–01:04 UTC на 2.58.35: L1 nano-gpt `llm_timeout` (известный класс деградации провайдера) → **L1_FALLBACK_PACKAGE fail-soft (fragments=30, chronology=369)** → L2 OK — Summary-граница §0/D11 не задета | ✅ существующее поведение не изменилось |
| **F Context Mode** (инцидентный чат) | per-chat `limits.chat_context_budget_tokens=−1` читается (ChatParamsCache wiring) → **`CONTEXT_CAPACITY policy_mode=unlimited`** (в каждом прогоне); `CONTEXT_SELECT recent_verbatim_messages=20 recent_verbatim_tokens=1833 middle_selected_messages=60`; **`direct: old episode hit=tg:1115249 span=1115219..1115259 rows=39 reason=gap+reply_links+cap_applied`** и второй прогон `hit=tg:1045861 rows=25` — вербатим-эпизоды из РЕАЛЬНОЙ истории чата; summary_lag_messages≈398-497 (stale watermark) — композиция summary-фон + middle + свежий tail без brutal cut; **grep `27826` и `direct: global context truncated` после рестарта = 0** | ✅ длинный контекст не обрезается старым капом; fresh tail цел; события CONTEXT_* в логах |
| **G observability** | grep-строки `direct_metric name=… count=…` присутствуют для force_reply / autonomous_reply / autonomous_react / autonomous_silent / silent_ack_success / old_episode_retrieval; снапшот `get_process_accounting()["direct_metrics"]` содержит все 9 счётчиков §46; события DIRECT_TRIGGER/DECISION_*/CONTEXT_*/DIRECT_SILENT_ACK в журнале | ✅ счётчики копятся, строки grep-able |

**Честные ограничения live-acceptance:**
- Сценарии A–D выполнены инструментированным сухим прогоном (реальный код/конфиг/история; замоканы только delivery/LLM-текст) — живых пользовательских «бот,…»/reply-триггеров в окне наблюдения (~50 мин после рестарта) **не возникло** (0 естественных DIRECT_TRIGGER в журнале сервиса). Поведение на живых пользователях — за владельцем (§56-G, как и Telegram WebView по спеке).
- **Находка (не блокёр, рекомендация):** prod-модель `deepseek/deepseek-v4.1-flash` отсутствует в `MODEL_CONTEXT_WINDOWS` → `window_source=unknown_fallback` → консервативное окно 16384 (WARN однократный, честный). Under-allocation (безопасное направление — перелива не будет), но Unlimited-бюджет меньше потенциального. Рекомендация владельцу: задать env `CHAT_MODEL_CONTEXT_WINDOW=131072` (или дождаться волны-пополнения карты) — вне reviewed-скоупа, сознательно не менялось при деплое.
- **Находка (наследие L-ASAP3-4, не блокёр):** mca07-каналы retrieval `episode-lore` (`db.list_lore_stories`) и `vector` (`memory.retrieve_fact_candidates`) fail-open с WARNING — целевые методы лежат в НЕЗакоммиченных WIP-дельтах `database.py`/`summary_memory.py` (M-файлы волны, исключены стейджингом). Старый-эпизод контур ASAP-3 работает через закоммиченные каналы exact/lexical/reply_graph (2 живых хита — доказано). Компенсация: fail-open по контракту REUSE; каналы доедут с релизом волны.
- Гигиена прогона: 13 синтетических self-facts (маркер «ASAP-3 live acceptance») удалены из graph-памяти (DELETE по маркеру, 15360–15370/15386–15387); smart-cache записи эфемерны; секреты нигде не печатались (R17).

## 8. §57 Post-deploy observation + gate §58

- Журнал сервиса 00:22:30→01:10 UTC: **Traceback/ERROR = 2** — единственный класс: nano-gpt `total_budget_exceeded`/ReadTimeout с контрактным fail-soft (L1_FALLBACK_PACKAGE → L2 OK) — ровно тот же класс, что и в baseline (27/7д) и в обоих предыдущих ранбуках; **не связан с ASAP-3**. Spike'а нет. `database is locked` = 0. NRestarts=0.
- Против базлайна T-4003: `global context truncated` 61/7д → **0 после деплоя**; `27826` → 0; silent/react/ignored и coordinator-континуум — без аномалий; new ERROR-классов нет; reaction spam нет (массовых 🗿 в журнале нет); silent force-direct нет (force→reply, событие A); постоянного physical_overflow нет (счётчик 0).
- **Гейт §58: REVIEWER APPROVED (round 2) ✓ · PROD DEPLOY ✓ · LIVE ACCEPTANCE A–G ✓ (инструментированный прод-прогон; живой пользовательский триггер и Telegram WebView — за владельцем) · POST-DEPLOY ✓ → компоненты закрыты; фича остаётся ACTIVE до reconcile-вердикта @Orchestrator/@Architect.**
- **Reconcile-вердикт @Architect (29.09.2026): ЦЕЛОСТНОСТЬ ПОДТВЕРЖДЕНА, reconcile выполнен (docs-only).** Диапазон `87728dc..4e96f14` = ровно документированный состав §2: feat `2deb287` (staging-перечень + import-closure `mca_gates`/`mca_retrieval_context`/`mca_events` — блоб-хэши коммита байт-в-байт совпали с рабочим деревом; hygiene-коммит не требовался) + docs `e6af6b2` + deploy-doc `4e96f14`; чужие M-файлы волны не закоммичены (48-файловый diff без `handlers/*`, `database.py`, `summary_*`, `web/api/oversight.py`, `tests/test_mca*`, архивов волны). ADR-1028-2 — прод-валидация + errata F8 (483/423/458/105/103/21; spec не правился — Spec-Hash binding цел); ARCHITECTURE.md — §103; backlog — 4 follow-up записи; review round 2 не инвалидировано. Фича готова к архивации @PM.

## 9. Откат (готовность)

- **Soft (без отката версии):** env `DIRECT_CONTEXT_COMPOSER_ENABLED=false` (контекст-путь байт-в-байт legacy, parity-тест) и/или `DIRECT_SILENT_ACK_ENABLED=false` (🗿-контур) и/или per-chat `flags.chat_autonomous_reply_enabled=false` — правка .env/systemd + рестарт, либо hot-ключ `POST /api/config` для per-chat.
- **Сид обратим:** `DELETE FROM bot_settings WHERE key IN ('flags.chat_silent_ack_enabled','flags.chat_autonomous_reply_enabled')` возвращает pre-сид состояние (значения = кодовые дефолты; поведенческая разница только в экспозиции тумблера).
- **Cold:** на проде `git revert 2deb287` (+`e6af6b2` по необходимости) до 2.58.34 (`8a0fa6c`) + рестарт; **ΔDDL=0 → откат чистый** (user_version 12 не менялся). Сид-строки при cold-откате безопасно игнорируются каталогом 2.58.34 (hot_config fail-open).
- Находки-рекомендации (unknown_fallback окна; mca07-каналы) — не требуют отката: fail-safe/fail-open направление деградации.

## 10. Итог

- **Deployed:** prod HEAD `e6af6b2` (feat `2deb287`), APP_VERSION **2.58.35**, MainPID 2026443 (с 00:22:37 UTC 29.09.2026), health 200, рестартов после гейта не требовалось.
- Import-closure верифицирован чистым worktree (imports OK + 525/2); чужие M-файлы волны не закоммичены; WTH/Spec/ADR-биндинг совпал побайтово; сид применён до рестарта; каталог 483/423/458/105/103/21; ΔDDL=0; kill-switch'и все ON; миниапп 3/3 тумблера с персистентным кликом; live acceptance A–G с событиями/счётчиками; post-deploy без нового error-класса.
