# Prep: legacy-binding recon — asap8-v6-3-live-correction (requirements-map.json)

> **ИСПОЛНЕНИЕ (LEDGER-LEGACY-BIND, 21.10.2026, HEAD fff68d76):** VERIFIED 135→157 (+22 = 21 REUSE + U07-LAUNCHMODE),
> RFL 59→37, context 13→14 (+REQ-U08-4), owner_optional 1→2 (+U07.3b). Гейт plan EXIT 0.
> Отклонения от рекомендаций рекона (все проверены, честные остатки не стёрты):
> 1) **U07.1a** — не биндился как REUSE: строка уже `user_excluded` (SUPERSEDED директивой владельца 18.10 — режим «скрывать до e2e» отменён, переключатель восстановлен; восстановление задокументировано в release-fs-25884-report: `tdesktop_disabled_until_e2e` удалён). Оставлена как есть.
> 2) **U08.4d / U08.5.1** — остались PENDING: клауза мини-линзы ⛶ реально не доставлена. Проверено в коде: класс `.lg-mini-lens` определён (app.css:3839, комментарий «класс применяет FULLSCREEN-лейн») и включён в Tier-A селектор стекла (app.js:23024, glass-refraction.js:73), но ни один коммит не привязывает класс к кнопке (index.html: кнопка несёт только `header-fs-btn`; `git log -S lg-mini-lens -- web/` — c0535280/473f2cc1/0ca661fe, привязки класса нет).
> 3) **REQ-U08-4** — вместо context оставлен PENDING required? НЕТ: переведён в `context` по реконe, т.к. работа ведётся в детях U08.4a–4f; открытая клауза ⛶ видна в reason зонтика и остаётся в детях U08.4d/U08.5.1 (PENDING required).
> 4) **B12.6** — остался PENDING: pointer-артефакты существуют (snapshot 91f754e3, 0 DELETE), но собственный ledger строки (map-reconciliation 16.10: VERIFIED→PENDING) фиксирует три незакрытых остатка (ошибочный адресат, GraphRAG hallucinated stats негативными тестами, измеримость side effects) — закрывающих артефактов не найдено.
> 5) **U07-SYM-DESKTOP / U07.3c / REQ-U07-3** — не переводились в owner_optional/context: существующий OWNER-OBS-RECON 20.10 (manual-строка `U07-OWNER-REALDEV`, owner_optional) сознательно держит их инженерными спутниками; их engineering_req_ids сломали бы гейт. Наблюдение на реальных клиентах консолидировано в `U07-OWNER-REALDEV`.
> 6) **U07-LAUNCHMODE** — вопреки метке OWNER_OPTIONAL закрыт как инженерный REUSE VERIFIED: его acceptance — чистая launch-механика (без второго request, exit, BotFather программно не меняется — покрыто тестом, как отмечает сам рекон); реальное устройство уже в `U07-OWNER-REALDEV`.
> 7) **FINAL.4** — 4 js-RED пинов (2.58.78) устранены последующими ре-пинами: `tests/js/round1025_hotfix7…` сейчас пинит 2.58.104 (проверено git grep).

Рекон PM, 2026-10-21. Read-only по карте; рекомендации для биндинг-лейна.
Волны доставки: W1–W4 (2.58.80–82), release/reconciliation 2.58.83, fullscreen hotfix 2.58.84+ (release-fs-25884, soul-1 W7), rebind 31c16555, agent-checks 2.58.88/89.

## Счётчики (40 открытых строк: 14 PENDING + 26 READY_FOR_LIVE)

| Вердикт | строк |
|---|---|
| REUSE (доставлено волной, нужен биндинг evidence) | 25 |
| REAL_WORK | 0 |
| CONTEXT (заголовки/зонтики/констрейнты) | 11 |
| OWNER_OPTIONAL (личное наблюдение на устройствах) | 4 |

Ключевой вывод: реальной разработки в карте не осталось; всё функциональное закрыто волнами W1–W4 + fullscreen hotfix + rebind. Открытое = биндинг evidence (25), серверные/агентские live-подтверждения уже собраны (live-canary.md, release-reconciliation.md, w4-live-probes.md, evidence/v63-close/), остаются только device-наблюдения владельца (4).

## REUSE — доставлено, биндинг evidence (25)

| Строка | Чем доставлено | Указатель для биндинга |
|---|---|---|
| REQ-B01 | Initiative-воронка | tests/test_asap8_v63_b01_initiative_observer.py; live-canary.md; tick-observation-25883.md; review-w2/w3 |
| B01.4 | Per-chat профиль частоты + лимиты | tests/js/asap8_v63_w3_modules_ui_test.js; w3-reports; live-canary.md (живой чат) |
| REQ-B02 | Experience/lessons без хардкода | tests/test_asap8_v63_b02_*.py; w1-reports/ |
| B02.3 | Cursor lag/батчи/дедуп | tests/test_asap8_v63_b02_*.py; w1/w2 reports |
| REQ-B03 | Просроченная память | tests/test_asap8_v63_b03_memory.py; W1-MEMORY-MIG.md |
| B03.4 | Fix _vec_candidates scope | tests/test_asap8_v63_b03_memory.py (RED/GREEN); w1-reports |
| REQ-B04 | Style Edit Cover | tests/test_asap8_v63_b04_edit_contract.py + b04_scene_delivery.py; w3-evidence-editor/ |
| B04.5 | Late recovery/идемпотентная замена | b04-тесты; review-w2/w3; в ACC зафиксировано «recover-путь не вызывает Telegram — закрыто» |
| REQ-U07 | Fullscreen (engineering-часть) | w2-evidence-fullscreen/; release-fs-25884 (soul-1); fullscreen-policy.js. Жёсткий real-client критерий = U07.3b/3c (OWNER_OPTIONAL ниже) |
| U07.1a | tdesktop: проблемный контрол скрыт до platform e2e | web/static/fullscreen-policy.js (tdesktop-политика, prod /static/fullscreen-policy.js → 200 в 2.58.86); soul-1 w7-v63-baseline-report.md |
| U07.1e | Нет второго requestFullscreen; exit-кнопка | w2-evidence-fullscreen/; ACC уже включает отмену владельца 18.10 (стартовый fullscreen не гасится) — сверка с owner-decisions при биндинге |
| REQ-U08 | Optical Liquid Glass ≥1 линза | w2-evidence-glass/; evidence/rebind-31c16555/glass_playwright_results.json; ui-acceptance.md (знаки (a)–(d) PASS) |
| U08.3e | Reduced-motion/low-perf tier down | rebind-31c16555: reduced_motion_status.png, glass_playwright_results.json; w2-evidence-glass/ |
| U08.4d | Mobile shell Tier B / popover / fs-control | rebind-31c16555: popover_390.png, fs_control_1to1_390.png, status_390*.png; samples-ux mobile (SU-UI.*) |
| U08.5.1 | 4 измеримых признака материала | w2-evidence-glass/ui-acceptance.md — все 4 знака с измерениями и PASS (contrast 13.1:1, bend ±8±5px, rim 1.5px, specular) |
| U08.5.4 | Нет overflow/смещений; FPS | rebind-31c16555 (скринсеты 320/390/1440); w2-evidence-glass/ |
| REQ-B06 | Per-chat переключатели → runtime | tests/test_asap8_v63_b06_summary_scope.py, b07_temporal_factcheck.py; w3-evidence-modules/ |
| B08.4 | Stories: 10 эпизодов приёмка | tests/test_asap8_v63_b08_stories.py; w3-evidence-analytics/ |
| REQ-B09 | Перенос supergroup без потерь | tests/test_asap8_v63_b09_migration.py; W1-MEMORY-MIG.md |
| REQ-B10 | Legacy v6 функциональная пере-приёмка | release-reconciliation.md; live-canary.md; классификация 3 failed pytest — REQ-B10-PYTEST |
| REQ-B11 | Интеграционная проверка фоновых механизмов | evidence/v63-close/b11-mechanisms-report-history-db.json; w4-live-probes.md §1 |
| REQ-B12 | Release/evidence gate | release-reconciliation.md; requirements-map.json (валидатор); live-canary.md |
| B12.6 | Snapshot до миграций | evidence/v63-close/preserve-and-workflow-audit.md §2/§4; SNAPSHOT_MANIFEST.md |
| FINAL.2 | Prod-подтверждения + 24/48h наблюдаемость | live-canary.md; tick-observation-25883.md; b11-report; incident-tail-25887.md |
| FINAL.4 | Deployed SHA/ledger/zero pending | release-reconciliation.md; evidence/v63-close/c2775a54-verification-runs.md §3; финальные релизы 2.58.81–83 |

## OWNER_OPTIONAL — device-наблюдения (4)
Все engineering-части доставлены (см. REQ-U07/U08 биндинг). Остаток — только реальный клиент владельца; ручные device-чек-листы отменены 18.10.2026, политика — plans/owner_live_checks.md.

| Строка | Остаток | Engineering-указатель |
|---|---|---|
| U07-SYM-DESKTOP | Windows Desktop: кнопка не уводит в малое окно — проверка на настоящем клиенте | release-fs-25884-report.md; w2-evidence-fullscreen/ |
| U07-LAUNCHMODE | Launch Mode=Fullscreen на реальном клиенте (BotFather-настройка внешне не меняется — уже покрыто тестом) | w2-evidence-fullscreen/; release-fs-25884 |
| U07.3b | Ручной клиентский журнал (platform/version/drag/close) | w2-evidence-fullscreen/ (серверная часть журнала) |
| U07.3c | Матрица Windows/Android/iOS/macOS/Web | Playwright-часть: rebind/w2 evidence; реальные клиенты — владелец |

## CONTEXT — предложить disposition=context (11)

| Строка | Причина |
|---|---|
| (без id) «Liquid Glass cross-engine caveats: github.com/…» | Исследовательская ссылка-контекст; fallback-решения уже приняты и проверены (U08 evidence) |
| (без id) «## 0. Обязательный старт: восстановить правду» | Заголовок; выполнено (source-restore-2026-10-16.md, review-coverage.md) |
| (без id) «### Уточнение владельца (заменяет C4 v6.1)» | Заголовок уточнения; содержание покрыто B01.4/decision-файлами |
| REQ-U07-3 | Зонтик U07.3; дети 3b/3c отдельными строками (OWNER_OPTIONAL) |
| REQ-U08-4 | Зонтик U08.4; дети 4a–4f (4d — REUSE отдельной строкой) |
| (без id) «## V — Минимальные end-to-end сценарии» | Заголовок; сценарии = V01… покрыты B-строками |
| (без id) «## Что должен выдать Orchestrator в финале» | Заголовок; дети FINAL.* строками |
| (без id) «## Важно: пределы корректирующего задания» | Заголовок секции-ограничений |
| (без id) «Если Telegram Desktop создаёт немасштабируемое окно на уровне native host…» | Констрейнт-проза; поглощён U07-политикой (не предлагать неисправную операцию — fullscreen-policy.js) |
| (без id) «own web fullscreen button не вставляется в Telegram chrome…» | Констрейнт-проза; учтён в U07-дизайне |
| (без id) «Не объявлять dynamic liquid refraction на всём UI…» | Констрейнт-проза; учтён в U08.4 tier-модели |
