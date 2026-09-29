# review.md — mca-asap31-auto-budgets-capacity-react (ASAP-3.1, R3) — единый Reviewer gate

- **Feature-ID:** `mca-asap31-auto-budgets-capacity-react`
- **Risk-Level:** R3 (живая формула бюджета Direct+Summary, P0-фронтенд, релиз 2.58.37)
- **Статус: NEEDS FIXES** — 2 High (требуют rework), 2 Medium, 3 Low. Код, коммиты, деплой Reviewer'ом не трогались.
- **Reviewed-Commit:** `fafbad8240f7e3af96a89e1ae758ac845ee4cd4c` (HEAD; docs-коммит поверх прод-базиса `c5cb5a9` 2.58.36)
- **Working-Tree-Hash (release-scope):** `e6e90cb7b775e8c276cbe573b96ded1781fbb178944c11c0a78518429ae0df7b`
  - Рецепт: SHA-256 от UTF-8-манифеста `"<path> <sha256(worktree-content)>"` по 116 путям = все 90 tracked-modified (содержимое worktree) + 26 untracked-файлов (`git ls-files --others --exclude-standard`: 4 новых сервиса, 5 тестов asap31, 8 tools/_asap31_*, 8 входных документов/артефактов фичи, README-скрипты), отсортировано по пути, `+ "\n"`. Манифест: `plans/reports/asap31_wth_manifest_944f3e4e.txt` (имя историческое, содержимое = финальный манифест).
  - Исключено из binding: мои review-артефакты (этот review.md, `review-evidence-oversight-blank.png`, сам манифест) и чужой WIP (не ASAP-3.1): `node_modules/`, `.playwright-mcp/`, `package.json`, `package-lock.json`, `plans/features/mca-04b-dossier-rebuild/`, правки `plans/metrics.md` + `plans/workflow_state.md` (foreign-контур mca-04b — в staging-перечне помечены «не стейджить»).
- **Spec-Hash:** `CC419781A8553FF2C2EB9183868863168AEFF0028BA0DC0D63C41F64523D33ED` (пересчитан — совпал); ADR-1028-3 `26329637DEFABF16EB8D9CBB55586D0C85C5B63D4623E69A6ED13844996DF664` ✓; tasks.md `ACFAA30A9296AF7F1ADAD462549E3DE75CBDF03FFB099549C46C1F97029CD8C1` ✓.

---

## 1. Git base и объём осмотренных изменений

- Base: HEAD `fafbad8` (пустой `git diff` против HEAD не принимался как доказательство — проверен `git status` 113 путей, `git diff --numstat` 90 tracked-modified = +4839/−2944, 23 untracked).
- Осмотрены полностью (не выборочно): spec.md, tasks.md, ADR-1028-3, audit.md, evidence.md Builder'а; код — новые модули (model_capacity, auto_budget, summary_budget_auto, model_slots, direct_llm_react), диффы direct_chat_service, summary_l1_clusterizer, summary_generator, summary_fact_package (read), llm_client, agentic_events, config_migrations, migrate_env_to_pg, param_catalog, settings, web/api/analytics.py, web/api/routes.py, web/app.js, web/index.html, polygon-background.js, telegram-init.js, app.css, conftest/pytest.ini, переизданные тест-пины. Fixture-файлы F8, README, tools/_asap31_* — точечно.

## 2. Выполненные проверки (команда → факт → вывод)

| # | Проверка | Факт (воспроизведено Reviewer'ом) | Вывод |
|---|---|---|---|
| 1 | Capacity resolver | `services/model_capacity.py`: precedence override→runtime→catalog→registry→fallback (§4); fallback 16384 только через `_warn_capacity_fallback` (WARNING `MODEL_CAPACITY_FALLBACK` + счётчик + `fallback_used` для badge); TTL `_ttl_for` (remote 86400 env `MODEL_CAPACITY_CACHE_TTL_SECONDS`, локальные ≤300с, fallback-результат 300с); ключ кэша = (класс, host, model, override) + `invalidate_capacity_cache()`; адаптеры httpx timeout 2с fail-open; `-1` не capacity; regex-угадывание отсутствует | Соответствует контракту §3–§8/§37–§39 ✓ |
| 2 | Auto budget формула | `services/auto_budget.py`: safety `safe_budget` ровно один раз в обеих арифметиках (direct: `(window−mandatory−reserve)×safety`; summary: `window×safety−mandatory−reserve`); output reserve: max_tokens→stage-policy (L1 4000/L2 6000)→Direct-ratio→floor 1024; policy −1/0/>0; §35 Dynamic = полный physical budget на ON-пути (санкция T-4063), OFF = прежний hard-cap | Формула §9–§12 ✓ |
| 3 | Единый источник цифр | Direct compose, Summary L1, `/api/direct/context-diagnostics`, `/api/analytics/context-budgets`, Status compact, «Бюджеты» — все через `resolve_stage_budget`/`collect_slots`; второй usage store отсутствует (read-side observations process-local). **ИСКЛЮЧЕНИЕ — см. H-1: L2-пакет молча остался на статике** | ✓ кроме L2-пакета (H-1) |
| 4 | Summary Window §118–146 | Chunked-ветка `_run_l1_lossless`: serialized-партиции, overlap=1, oversized = свой chunk без text[:N], merge по stable-ID, coverage 100%/degraded, события SUMMARY_L1_CHUNKED/DEGRADED, «skipped» только на OFF-пути; manual cap = размер chunk; бюджет от capacity слота; timeout → LEVEL-2 из полного набора | ✓ (M-1 — два поля-заглушки §127) |
| 5 | Регрессии §142–145 | `tests/test_summary_coverage_asap31.py`: 369→1 chunk/100%/без 21001; 16K → chunks>1 все обработаны; смена модели → пересчёт; 6h→12h; manual cap=chunk; Auto-семантика §77/78; события §128; OFF-паритет ×2 | Существуют, запуск 14/14 зелёные ✓ |
| 6 | LLM REACT | `direct_llm_react.py` + врезка: матрица владеет action; react — один LLM-вызов на REACT-ход (шорт-кат был 0-вызовный; REPLY-путь await_count==2 не тронут — `TestHandleOrder` не менялся); allowed = 10 emoji union A8+💀🤡; невалид/LLMError → детерминированный fallback fail-soft; kill-switch env+per-chat → OFF байт-в-байт (2 asap3-теста переизданы со смыслом сохранён, ON покрыт новыми 18); SILENT→🗿 не тронут; Force → REPLY | ✓ (REACT-ход теперь 1 full-context вызов — санкция Q11) |
| 7 | Miniapp разводка §17 | SPLIT ON: `budgetsUnlimitedKeys` = 4 quota-ключа; Context Mode = context-ключ; канальные ключи вне тумблеров; SPLIT OFF = 7 ключей байт-в-байт; миграция non-destructive по построению; подтверждено живым UI + тестами | ✓ |
| 8 | Labels ×6 + override | Все 6 renames spec 10.1 в param_catalog; ключ `models.chat_context_window_override` размещён в `models_main` (отклонение D-3 — ПРИНЯТО: группы стабильны, F8-числа сходятся, advanced-правило pg_key "window") | ✓ |
| 9 | Analytics §88/§87/§24 | Endpoint global-admin + `?chat_id=` + `?refresh=1` + kill-switch 404; shape §25; human-first карточки, machine states → русский, fail-open блок | ✓ живьём |
| 10 | Status §28–29 | Компакт-строки из того же resolver'а, warning badge, ссылка в Аналитику, legacy memoryContext сохранён, `/api/status.context` не публиковался | ✓ |
| 11 | Polygon | `TOPO_HZ`/`TOPO_FADE_MS` удалены; rebuild = 30s/displacement-26px + crossfade 4000ms, пол яркости 0.85; узлы 0.85±0.10, halo 0.30±0.05; crypto-seed 1/lifetime + `?bgseed` + `start({seed})`; дрейф 97/140/160с; reduced-motion без endless rAF; diagnostics §69 | ✓ §115-запреты не нарушены |
| 12 | Bottom nav | `--app-usable-height` = фактическая видимая высота (Telegram stable/текущая → visualViewport → innerHeight); inset ровно один раз на `.bottom-nav`; scroll-padding для SaveBar; legacy-переменная только для rollback | ✓ единая модель §92–§93 |
| 13 | Kill-switch OFF-паритет | 7 env-only ClassVar default ON; conftest-изоляция: старые тесты идут с OFF, asap31 — с ON; полный suite зелёный (см. 15) | ✓ |
| 14 | События 28→33 | +5 в `BUDGET_EVENT_TYPES`, коллизий нет; R17-whitelist полей по D15-паттерну | ✓ |
| 15 | pytest + JS | Независимый полный прогон: **10046 passed + ровно 2 failed** = якорные `test_forbidden_paths_out_of_diff` (test_tool_coordinator_round1026, test_unified_image_request_round1026 — известные, у Builder'а deselected; числа идентичны); новые asap31+F8 файлы — 98/98; JS — **50/50**; `node --check` ×3 OK | ✓ подтверждено |
| 16 | F8 | `gen_param_registry_round1025.py --check` → **CHECK OK: реестр 484**; пины тестов 484/423/459/105/103/21; fixtures переизданы; `ROUTES_SHA256_F11` перепинен | ✓ санкция атомарна |
| 17 | R17 | Diff + новые файлы: секретов нет (pattern-скан + ручной осмотр); raw-текст в логи не пишется (whitelist'ы, `model[:64]`, host-only); initData/ключи в артефакты не попали | ✓ |

## 3. Browser-Verification (REQUIRED) — реальный контур, Browser Use

Контур: локальный uvicorn 127.0.0.1:8033 (create_app из worktree 2.58.37), in-memory ConfigCache с seeded global-admin ролью (PG локально недоступен — целостность prod не затронута), TMA-сессия = подписанный HMAC initData локальным токеном (Telegram launch-params). Reviewer взаимодействовал реальными кликами/вводом, не только скриншотами.

| §71 12 шагов + TMA-флоу | Результат |
|---|---|
| 1. Открытие как global admin | ✓ `/api/me` is_global_admin=true, ui_flags ON |
| 2. Discoverability desktop | ✓ sidebar IA v2 = 8 пунктов, «Аналитика» на месте |
| 2b. Discoverability mobile | ✓ «Ещё» → more-sheet с карточкой «Аналитика» |
| 3–4. Клик → route → template | **✗ BLANK PAGE** (см. H-2): hash `#/oversight`, Vue root = `<!---->`, bodyLen=0, только Polygon-фон (скриншот зафиксирован) |
| 5. Console errors | **✗ 6× TypeError: `execMetricsRows is not a function` / `self.execTokenPair is not a function` (app.js:2747→2760)** |
| 6. Network | ✓ /api/oversight/summary, /api/analytics/usage/latest|summary, /api/analytics/execution/latest, /api/analytics/context-budgets — все 200 |
| 7. Deep-link #/oversight | **✗ тот же blank** (детерминированно, 3 пути входа) |
| 8–9. Desktop + mobile повтор | ✓ идентично воспроизводится на обоих |
| 10. Бюджеты страница | ✓ карточка «Автоматические бюджеты моделей» с ЖИВЫМИ данными resolver'а: 5 слотов, «deepseek v4 flash · окно 131.1 тыс. · доступно 102.6 тыс.», «наследует основную модель», «справочник моделей», SPLIT-тумблер «Без суточных квот» + §17-copy |
| 11. Status compact | ✓ (рендер Status без краша; compact-блок budgetsAuto) |
| 12. Viewports §96 | ✓ §94-инварианты на 320×640/360×800/390×844/430×932: rect.top≥0, rect.bottom=высота вьюпорта (844/640/800/932), h=45, labels видимы; desktop 1440 — sidebar, bottom-nav нет; `--app-usable-height` = полная видимая высота (guessed-offset отсутствует) |
| Polygon §100 | ✓ sceneSeed=3997161063 (crypto ≠ 20260923); `?bgseed=12345` → seed 12345, композиция иная (scale 1.02 vs 0.61); topologyRebuilds=1 и не растёт (56с наблюдения — 4Hz устранён); все поля diagnostics §69 |
| Per-chat UI / SaveBar | Недоступно честно: локальный PG отсутствует — списки чатов/сохранение конфигов fail-soft; см. Unavailable |

**Итог браузерной фазы:** P0-баг «Аналитика не открывается» воспроизведён и локализован; fix NAV_ITEMS_V2 необходим, но не достаточен. Все остальные проверенные экраны — pass.

## 4. Blocking findings

### [H-ASAP31-1] High — L2 Stage Auto Budget не применяется (тихая интеграция 3-tuple → 2-tuple)
- **Где:** `services/summary_generator.py:766–767,871–873`; `services/summary_budget_auto.py:175–213` (`resolve_l2_package_budget` возвращает `(kind, effective, budget_mode)`); `services/summary_fact_package.py:231–241` (`_resolve_budget` принимает только `(kind, limit)`/int — 3-tuple → fallback на `resolve_fact_package_budget()`), `:626` (`_enforce_budget` режет fragments→descriptions→целые темы).
- **Факт:** в Auto-режиме L2-пакет (§96) строится по статическому legacy-бюджету (~19–21K), резолверное значение вычисляется и молча отбрасывается. При большом окне L1 отдаёт 100% coverage, но на границе L2-пакета темы выбрасываются `_enforce_budget` → FACT_PACKAGE_TRUNCATED — второй искусственный потолок ровно того класса, который фича устраняет. `resolve_l2_effective_budget` — мёртвый код (вызовов нет). Тестов на L2-package-auto-budget нет (потому и прошло).
- **Нарушает:** T-4069 acceptance («L2-бюджет передаётся генератором» — фактически no-op; evidence-claims не соответствуют коду), §131/§37/DoD-76 (все стадии из одного резолвера), контракт раздела 4 spec.
- **Fix:** передавать `budget=l2_budget[:2]` (или научить `_resolve_budget` понимать len==3) + `build_fallback_package` получает тот же вид бюджета; добавить тест «Auto: limit пакета == effective_input_budget резолвера слота summary.l2» и «кастом >0 = manual cap».
- **Проверка после фикса:** прогон T-4074-набора + новый L2-тест; пересчёт WTH.

### [H-ASAP31-2] High — «Аналитика не открывается»: настоящая первопричина не устранена (render-краш oversight-ветки)
- **Где:** `web/index.html:2620,2623` (шаблон вызывает `execMetricsRows()` со скобками), `web/app.js:2722` (`execMetricsRows` — computed), `:2747–2748` (вызов `self.execTokenPair(...)`), `:2760` (`execTokenPair` тоже в `computed`-блоке: computed 1925–3724, methods с 3725). Идентично на HEAD `fafbad8` — баг предсуществующий, это и есть прод-симптом владельца (2.58.36).
- **Факт (воспроизведение):** любой вход в #/oversight (sidebar / «Ещё» / deep-link, global admin, endpoints 200) → Vue render TypeError (`execMetricsRows is not a function`; внутри — `self.execTokenPair is not a function`) → корень приложения рендерит `<!---->` → полностью пустой экран (скриншот в папке фичи: `review-evidence-oversight-blank.png`).
- **Нарушает:** T-4082 acceptance «реальная причина неоткрытия найдена и устранена» (устранена только дверь — NAV_ITEMS_V2; комната пустая), §99-регрессию (heading «Аналитика» visible — невозможен), §52/§108-acceptance. Q3/F12 static analysis пропустил краш (проверял null-safety, а не method/computed-распределение); Builder без TMA-сессии не мог увидеть.
- **Fix:** перенести `execTokenPair` (и проверить каждого хелпера, вызываемого как метод: `execDuration`, `execCoverLabel`, `execPublicationLabel`, `execFilterActive`, `fmtCost`, `fmtExactTokens` — где лежат) в `methods:` ЛИБО вызывать computed без скобок; обязателен реальный §71-проход + §99 Playwright-регрессия после фикса.
- **Проверка после фикса:** 12-шаговый §71 на аутентифицированном контуре + autobudget-блок видим + 0 console errors.

## 5. Non-blocking findings

- **[M-ASAP31-1] Medium:** §127-поля-заглушки: `duplicate_overlap_messages` всегда 0, `source_window_start/end` всегда None (`summary_l1_clusterizer._record_run_coverage` — аргументы никогда не передаются). T-4071 acceptance частично не выполнен; UI-полнота честна (processed/total/coverage/chunks), потребителей полей нет. Рекомендовано закрыть в том же rework (дёшево: считать overlap при партиционировании, пробрасывать окно прогона).
- **[M-ASAP31-2] Medium (non-blocking):** tool-loop путь Direct без `fallback_payload_adapter` (отклонение #4 Builder'а, задокументировано): при tool-конфигурации + сбое primary + fallback с меньшим окном §14/§42-инвариант «fallback не получает oversized primary payload» нарушается; отказ громкий (ошибка провайдера), fail-soft сохранён. Follow-up: прокинуть factory в tool-путь.
- **[L-ASAP31-1] Low:** `AUTO_CONTEXT_BUDGET`/`MODEL_CAPACITY_RESOLVED` эмитятся и на read-side (`collect_slots` → до 7 событий на каждое открытие Аналитики/Бюджетов/Статуса) — шум observability; лучше эмитить только на compute-пути.
- **[L-ASAP31-2] Low:** `capacity.runtime` всегда None в shape слотов (model_slots.py:115) — поле §25 не заполняется фактическим runtime-значением из CapacityResult.
- **[L-ASAP31-3] Low:** Dynamic (direct.*) на ON-пути теперь = полный physical budget (санкция §35/T-4063): средний payload/latency Direct вырастет на больших окнах — мониторить p95 после деплоя.

**Трактовки-отклонения Builder'а — СУЖДЕНЫ:** D-1 §123 oversized «свой chunk verbatim» — ПРИНЯТО (инварианты §121/§95 соблюдены; text[:N] нет; переполнение — явный degraded, coverage честный; фабрикация part-ID не вводилась); D-2 §140 mid-flight rechunk — ПРИНЯТО (§141-инвариант полного source set соблюдён структурно, наследованные fail-soft тесты зелёные); D-3 override в `models_main` — ПРИНЯТО (см. п.2.8); D-4 adapter только на plain-generate — учтено как M-2; D-5 «Settings 424» — ПРИНЯТО (оба инварианта запинены); D-6 §104 группировка — ПРИНЯТО (первая секция, санкции не нарушают).

## 6. Counterexamples (проверено)

1. «Молчаливый 16384 на ON-пути» — опровергнуто кодом (`_warn_capacity_fallback` единственная точка, badge из `fallback_used`); live-проверка: прод-модель deepseek → registry 131072, не 16384.
2. «Второй счётчик бюджетов» — найден и опровергнут наоборот: единственный резолвер, но L2-пакет его игнорирует (H-1) — подтверждено чтением `_resolve_budget`.
3. «Analytics не открывается из-за NAV» — гипотеза Q3 опровергнута как единственная причина: воспроизведён render-краш (H-2) на 3 путях входа.
4. «OFF ≠ байт-в-байт» — полный suite (10046) с conftest-OFF изоляцией зелёный; аддитивные лог-поля (budget_mode) не меняют поведение (паритет-тесты ×2).
5. «4Hz rebuild остался» — diagnostics: topologyRebuilds=1 за 56с; код: таймера нет.
6. «Seed недетерминирован для тестов» — `?bgseed=12345` → точный seed, композиция отличается от crypto-seed.
7. «Слабленные тесты REACT» — diff 2 переизданных тестов: смысл сохранён (детерминированный путь = OFF), ON покрыт новыми 18.

## 7. Счётчики

- Critical: **0**; High: **2** (H-1, H-2 — блокирующие); Medium: **2** (M-1 — закрыть в rework, M-2 — follow-up); Low: **3**.
- Отклонения-трактовки: 6 — все ПРИНЯТЫ (2 вошли как findings M-2/L-2).
- pytest: 10046 passed / 2 якорных failed (известные, поименованы); JS 50/50; F8 CHECK OK 484; R17 чисто.

## 8. Unavailable checks (честная фиксация)

- Per-chat Dynamic/Unlimited save→reload и SaveBar в живом UI — локальный PG отсутствует (конфиги/чаты не пишутся; fail-soft). Тест-покрытие §16/§46 — unit/integration зелёные; UI-флоу — на живой приёмке T-4089.
- Реальный Telegram WebView (viewportStableHeight-ветка, клавиатура) — вне локальной среды; геометрия верифицирована на visualViewport/innerHeight-ветках всех 5 viewports §96.
- Polygon 60–90с foreground-анимация — фоновая вкладка ставит rAF на паузу (frameCount=1); структурные свойства §100 (rebuild/seed/drift-поля) подтверждены, визуальная плавность — на §61-приёмке владельца.
- Прод-сценарий §102 (nano-gpt/deepseek раздельный резолв) — registry-значения верифицированы локально, сетевые адаптеры — только mock-тестами (по spec §41).

## 9. Staging-перечень для DevOps (хунки ASAP-3.1 vs чужое)

**Стейджить (release-scope 2.58.37):** 90 tracked-modified + 26 untracked (поимённый список — манифест WTH в plans/reports/, рецепт в шапке этого отчёта).

**Смешанные файлы (eol-перезапись + реальные хунки — стейджить целиком, реальный diff мал):**
| Файл | raw diff | реальный diff |
|---|---|---|
| `services/llm_client.py` | 2639 строк | 19 (kwarg `fallback_payload_adapter` + fallback-блок) |
| `web/static/telegram-init.js` | 299 | 51 (новая модель `--app-usable-height`) |
| `tests/js/round1021_ui_audit_test.js` | 626 | 8 (пины) |
| `tests/test_context_limits_round1019.py` | 757 | 13 (пины) |
| `tests/test_history_retention_toggle.py` | 880 | 6 (пины) |

**НЕ стейджить (чужой WIP mca-04b / окружение):** `node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`, `plans/features/mca-04b-dossier-rebuild/`, правки `plans/metrics.md` + `plans/workflow_state.md`.

**Опционально (решение Orchestrator'а):** `tools/_asap31_*.py` (8 одноразовых скриптов переизданий — документация процедуры; можно удалить перед коммитом), `review-evidence-oversight-blank.png` (evidence ревью).

## 10. Вердикт и handoff

**Status: NEEDS FIXES** — согласовано с §113: Orchestrator маршрутизирует `review → build`. Объём rework:
1. H-ASAP31-1: L2-budget tuple-фикс + тесты (малый, изолированный);
2. H-ASAP31-2: method/computed-фикс oversight-хелперов + обязательный §71-проход и §99-регрессия;
3. M-ASAP31-1: §127-поля (желательно в том же цикле);
4. Пересчёт binding (новый WTH), повторный полный pytest + JS.

После исправлений — повторный единый gate Reviewer'а (recheck: H-1, H-2, затронутые инварианты §127/§131, регрессии T-4074, fresh §71). Approval этой итерации недействителен для любого другого состояния дерева.

---

# ROUND 2 (rework re-validation) — 30.09.2026 — единый Reviewer gate

- **Feature-ID:** `mca-asap31-auto-budgets-capacity-react`
- **Risk-Level:** R3 (без изменений)
- **Статус: APPROVED FOR RELEASE** — оба High round 1 устранены и независимо верифицированы; M-1 закрыт; новый 1 Medium non-blocking (M-3); 2 Medium follow-up + 3 Low — без изменений. Блокирующих findings нет.
- **Reviewed-Commit:** `fafbad8240f7e3af96a89e1ae758ac845ee4cd4c` (HEAD не менялся; всё дерево — по-прежнему незакоммиченный worktree поверх прод-базиса 2.58.36).
- **Working-Tree-Hash:** `1b9fd47701dbd4546894f2cf69e7f16f299295ba7f408ef646bfa58715c4b6ba`
  - Рецепт round 1 (без изменений): SHA-256 от UTF-8-манифеста `"<path> <sha256(worktree-content)>"`, 121 путь (то же множество путей, что в rework1 — сверено с `git status`: вне множества только исключения/чужой WIP/манифесты), отсортировано, `+ "\n"`. Манифест: `plans/reports/asap31_wth_manifest_rework2.txt`. Идемпотентность проверена двойным пересчётом (совпадение байт-в-байт).
  - **WTH round 1 (`f71bac9…fb11`) устарел закономерно:** единственный контентный дрейф множества — `plans/features/…/evidence.md`, дописанный Builder'ом уже после снятия манифеста rework1 (проверено: 120/121 хешей совпали, evidence.md — нет; множество путей не менялось). Правка реестра `full_audit_results.md` (round-2 запись) выполнена ДО финального снимка; для отсутствия самоссылки значение WTH живёт здесь и в манифесте, запись реестра ссылается на манифест.
  - Исключения — как в round 1: review-артефакты (этот review.md, оба манифеста WTH), чужой WIP (`node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/features/mca-04b-dossier-rebuild/`, `plans/metrics.md`, `plans/workflow_state.md`).
- **Spec-Hash:** `CC419781A8553FF2C2EB9183868863168AEFF0028BA0DC0D63C41F64523D33ED` ✓ (пересчитан, совпал); ADR-1028-3 `26329637…DF664` ✓; tasks.md `ACFAA30A…D8C1` ✓ — spec/ADR/tasks не менялись с round 1.

## R2.1 Git base и объём осмотренной дельты rework

Base: тот же HEAD `fafbad8`. Осмотрено точечно по дельте rework (полный diff `summary_generator.py` — 2 хунка; `summary_fact_package.py` — `_resolve_budget`; `summary_l1_clusterizer.py` — coverage-контуры; `web/app.js` — methods/computed-распределение; новый harness; 2 новых тест-файла) плюс независимые полные прогоны. Round-1 вердикт по остальному ядру остаётся в силе (§2 round 1 не пересматривался — дельта его не касается).

## R2.2 Выполненные проверки (команда → факт → вывод)

| # | Проверка | Факт (воспроизведено Reviewer'ом) | Вывод |
|---|---|---|---|
| 1 | H-2 код: распределение хелперов | `web/app.js`: ровно 6 определений (`execMetricsRows:4575`, `execTokenPair:4613`, `execDuration:4618`, `execCoverLabel:4622`, `execPublicationLabel:4629`, `execFilterActive:4565`) — все в `methods` (блок с 3671); в `computed` (1925–3670) — 0 дублей; зависимости `fmtCost:4529`/`fmtExactTokens:4522` тоже в methods; шаблон `index.html:2620/2623` вызывает `execMetricsRows()` — консистентно с methods | Фикс соответствует round-1 предписанию ✓ |
| 2 | H-2 harness зелёный | `node tests/js/asap31_oversight_render_test.js` → `ASAP31-OVERSIGHT-RENDER-OK` (exit 0); пин `round1026_s6_publish_test.js` → `S6-PUBLISH-OK` | ✓ |
| 3 | H-2 harness ловит pre-fix | Изолированная симуляция в temp (копия app.js + harness): (а) хелперы возвращены в computed в пре-фикс форме → падение check-3 «обязан быть в methods»; (б) то же с отключённым check-3 → падение check-1 «шаблон вызывает execMetricsRows(…) … она COMPUTED» (первый TypeError round 1); (в) только execTokenPair в computed + computed-запись с `self.execTokenPair(...)` → падение check-2 «вызывает … как функцию, но … тоже COMPUTED» (второй TypeError round 1). Реальный harness в репо не менялся | Чувствительность доказана на все три аспекта ✓ |
| 4 | H-1 код: контракт бюджета | `_resolve_budget` (`summary_fact_package.py:231–250`): `(kind, limit)` И `(kind, limit, budget_mode)` → единая форма, «доп. поля после limit игнорируются (НЕ молча)»; int → tokens; None → статика (OFF-путь). `build_fallback_package:741` принимает budget; `_enforce_budget:784` использует | Контракт round-1 fix ✓ |
| 5 | H-1 код: передача генератором | `summary_generator.py`: `l2_budget = await resolve_l2_package_budget()` (defensive try/except → None, :765–769); передаётся в `build_fact_package` (:871–873) и в defensive-ветку `build_fallback_package` (:880–883) | ✓ (но см. M-3 — третий call-site) |
| 6 | H-1 тесты | `tests/test_l2_budget_asap31.py` — **6/6**: triple-форма; end-to-end auto (limit пакета == resolver-значению слота summary.l2, payload между статикой (~19–21K) и авто (~106K) НЕ режется, 2 темы целы); exact-match без пересчёта; manual cap режет ПО капу; fallback-пакет получает тот же бюджет; OFF → прежняя статическая точка | ✓ |
| 7 | M-1: coverage-поля | `summary_l1_clusterizer.py`: `window_start/end` = реальные min/max timestamps source set (:805–806 chunked, :1364–1366 single-pass); `overlap_count` = фактические дубли (сообщение уходит в >1 chunk, :913; = chunks−1 при N≥1); прокинуты во все 3 call-sites `_record_run_coverage` (:837/843/845, :867/872/874, :1368/1372); тест ассертит точные значения (start/end окна 369 сообщений, overlap == chunks−1) | §127 закрыт ✓ |
| 8 | Полный pytest | **10053 passed / 2 failed** — оба failed ровно якорные `test_forbidden_paths_out_of_diff` (test_tool_coordinator_round1026:651) и `…_vs_baseline` (test_unified_image_request_round1026:636) — те же, что в round 1, байт-в-байт failure; известные, поименованы, non-blocking (адъюдикация round 1 §2.15). Счётчики сходятся с Builder'ом (10052/0): −2 deselected-якоря, −1 внешний betterstack-флак (`pytest -k betterstack` изоляция: 44 passed) | ✓ |
| 9 | JS полный suite | **51/51** (50 файлов round 1 + новый harness), все `node tests/js/*.js` exit 0; `node --check` ×3 (app.js, polygon-background.js, telegram-init.js) OK | ✓ (Builder гонял срез 36 — восполнено) |
| 10 | F8 | `tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 484**, карта полна, R17-чисто, TSV/map идемпотентны | ✓ |
| 11 | Binding | Пересчитан WTH по рецепту (см. шапку R2); spec/ADR/tasks-хеши совпали с round 1 | ✓ |

## R2.3 Browser-Verification (только затронутое — дельта H-2; остальное покрывает round 1 §3)

Контур round 1 воспроизведён заново: локальный uvicorn (create_app из worktree), in-memory ConfigCache с seeded global-admin (роль `admin` + wildcard — идентично round 1), TMA-сессия = подписанный HMAC initData локальным токеном (self-check валидацией aiogram `safe_parse_webapp_init_data`), реальный Chrome/Browser Use, реальные клики.

| Шаг | Результат |
|---|---|
| `/api/me` | ✓ is_global_admin=true, ui_flags ON (IA_V2, POLYGON, BUDGETS_SPLIT, …) |
| Вход в «Аналитику» кликом по sidebar | **✓ РЕНДЕРИТСЯ С КОНТЕНТОМ** (round 1: Vue root `<!---->`, blank): «Аналитика» + секция «Модели и автобюджеты» с 5 живыми карточками resolver'а (Прямые ответы 131.1 тыс./102.6 тыс.; L1/L2/Legacy «наследует основную модель» 110/108/113 тыс.; Фоновая память 102.6 тыс.; источник «справочник моделей»), все аналитические секции (активность, ключи, бюджеты, наблюдаемость, токены, Метрики Саммари, интеллект) |
| Console errors | **✓ 0** (round 1: 6× TypeError `execMetricsRows is not a function` / `self.execTokenPair is not a function`); error-hook + повторные входы чистые |
| Deep-link `#/oversight` (путь 3 round 1) | ✓ тот же рендер с контентом, rootLen ~15.5K |
| «Бюджеты» (`#/modules/budgets`) | ✓ без регрессии: карточка «Автоматические бюджеты моделей», 5 слотов с живыми цифрами, «наследует основную модель», SPLIT-тумблер «Без суточных квот», 0 ошибок |
| Скриншоты | Зафиксированы в сессии ревью (обе страницы); пустой экран не воспроизводится ни на одном пути входа |

Примечание по контуру: RBAC-редирект «Нет доступа к разделу» наблюдался только на недосеянной роли (без wildcard) — корректное поведение доступа, не дефект; после полного сида (как round 1) обе страницы доступны.

## R2.4 Counterexamples (round 2)

1. «Harness зелёный ⇒ фикс доказан» — опровергнуто и усилено: чувствительность harness доказана pre-fix симуляциями (3 отдельных срабатывания check-1/2/3, R2.2#3), а не только зелёным прогоном.
2. «L2-бюджет доходит во ВСЕ fallback-пути» — опровергнуто частично: call-site `summary_generator.py:854` (L1-unusable) бюджет не передаёт → M-3 (ниже).
3. «WTH `f71bac9…` валиден» — опровергнуто: evidence.md дописан после снимка; binding пересчитан (идемпотентно).
4. «Ожидание 10052/0» — независимо воспроизведено 10053 passed / 2 known-anchor failed; расхождение объяснено (2 deselected + 1 betterstack-флак, изоляция 44 passed).
5. «Бюджеты могли отломать rework-правки app.js» — проверено живьём: страница целостна, 0 ошибок.
6. «Редирект «Нет доступа» на «Бюджеты» — регрессия rework» — опровергнуто: воспроизводится только на роли без wildcard (корректный RBAC-гейт; на сеяной роли round 1 страница открывается).

## R2.5 Findings

**Blocking findings: нет.**

**Non-blocking debt (регистрация прозрачная; в релиз 2.58.37 не блокирует):**

- **[M-ASAP31-3] Medium (новый, follow-up):** `summary_generator.py:854–859` — ветка L1-unusable строит fallback-пакет (`build_fallback_package`) БЕЗ `budget=l2_budget` → на этой degraded-ветке в ON-режиме действует статический потолок `resolve_fact_package_budget()` (~19–21K) вместо резолверного. Impact ограничен: путь достижим только при непригодном L1 (LLM error/timeout/invalid), поведение == OFF-режиму/legacy (паритет не нарушен), усечение громкое (metrics truncated/limit/kind), нормальный и defensive-пути чисты (§131/§37 соблюдены там, где покрыто тестами). Fix: одна строка `budget=l2_budget` + тест в `test_l2_budget_asap31.py`. Верификация: прогон файла + пересчёт binding.
- **[M-ASAP31-2] Medium (carry-over round 1, без изменений):** tool-loop путь Direct без `fallback_payload_adapter` — follow-up.
- **[L-ASAP31-1/2/3] Low ×3 (carry-over round 1, без изменений):** события на read-side `collect_slots`; `capacity.runtime`=None в shape; мониторинг p95 Dynamic=full-budget после деплоя.

**Трактовки-отклонения round 2:** новых нет; 6 принятых round 1 остаются в силе.

## R2.6 Unavailable checks (round 2, честная фиксация)

- Строки exec-метрик прогона Саммари («Токены L1» и т.д.) в живом UI: на локальном контуре нет LLM-вызовов → `execMetricsRows()` возвращает [] → блок скрыт `v-if` (штатная data-gating семантика, не баг). Рендер секции «Метрики Саммари» и отсутствие render-краша верифицированы; наполнение строк — структурным harness (check 4) и JS-пинами; фактические цифры — на живой приёмке T-4089 (как в round 1).
- Остальные Unavailable round 1 (§8) не пересматривались — дельта rework их не касается: per-chat save/SaveBar и Telegram WebView (T-4089), Polygon foreground-плавность (§61 приёмка), §102 сетевые адаптеры (mock-only по spec §41).

## R2.7 Вердикт, binding и handoff

**Status: APPROVED FOR RELEASE** (обе обязательные гейт-линзы пройдены независимо; блокеров нет).

- Approval привязан к: **Reviewed-Commit `fafbad8240f7e3af96a89e1ae758ac845ee4cd4c`** + **WTH `1b9fd47701dbd4546894f2cf69e7f16f299295ba7f408ef646bfa58715c4b6ba`** (манифест `plans/reports/asap31_wth_manifest_rework2.txt`, 121 путь, идемпотентен) + **Spec-Hash `CC419781…D33ED`**. Любое изменение кода/спека/релевантных untracked-файлов после этого снимка инвалидирует approval; новый коммит с байт-идентичным содержимым принимается только после пересчёта binding.
- Handoff: @Orchestrator → фаза **delivery** (релиз 2.58.37). Staging-перечень DevOps — без изменений (round 1 §9: 90 tracked-modified + 26 untracked по манифесту; смешанные файлы стейджить целиком; чужой WIP не стейджить). Follow-up backlog: M-ASAP31-3 (одна строка + тест), M-ASAP31-2, L×3; живая приёмка T-4089.
- Reviewer-инфраструктура сессии снята: оба локальных uvicorn-контура остановлены, порты 8033/8034 закрыты, временные файлы — вне репо (temp). Код не правился, коммиты не создавались; записи внесены только в review-артефакты (`review.md` round-2 секция, `full_audit_results.md` round-2 запись, манифест WTH rework2).

*Reviewer-артефакты этой сессии удалены из worktree (временный контур `​.review_tmp_asap31/` снят: сервер остановлен, порт закрыт, каталог удалён).*
