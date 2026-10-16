# v63-agent-close-2026-10-16 — lane V63-CLOSE

Задача: закрыть агентски-закрываемую часть ASAP 8 v6.3 с реальными
доказательствами, произвести три отсутствовавших обязательных артефакта
(B12.1) и предложить почленные обновления карты покрытия.
Коммита, деплоя, SSH и обращений в Telegram не было. Прод трогался только
5 HTTPS-запросами к `https://admin-bot.duckdns.org`.
Кандидат: `c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79, deployed).

## 1. Созданные артефакты

| Файл | Что это |
|---|---|
| `review-ledger.md` | журнал всех раундов ревью/верификации (R1–R7), все находки с диспозициями (исправлено / принято / открыто / owner-гейт) |
| `integration-evidence.md` | по каждой волне: что интегрировано, тесты/пробы, артефакты, коммит; таблица швов; цепочка PRIN-PIPELINE-FIRST по каждому B |
| `v63-final-coverage-report-2026-10-16.md` | финальный отчёт v6.3: coverage-таблица FINAL.1 по B01–B12/U01–U08/V01–V07 + legacy v6, полный список открытого, без маркеров `__PENDING__` |
| `evidence/v63-close/c2775a54-verification-runs.md` | все прогоны этой lane, выполненные на точном дереве кандидата (git worktree --detach) |
| `evidence/v63-close/prod-probes-2026-10-16.md` | 5 HTTPS-запросов + побайтовая сверка `/web/` и `fullscreen-policy.js` с блобами `c2775a54` |
| `evidence/v63-close/preserve-and-workflow-audit.md` | аудиты для PRIN-ONE-WORKFLOW, PRIN-PRESERVE, B12.4 и точные незакрытые клаузы B12.6 |
| `evidence/v63-close/b11-mechanisms-report-history-db.json` | реальный артефакт запуска `tools/v63_b11_mechanisms_report.py` на дереве кандидата (10 механизмов, полная цепочка, `not_green_rule`) |
| `v63-agent-close-2026-10-16.md` | этот отчёт (предложения по статусам) |

Внешний вердикт другой lane учтён (не создавался здесь):
`v63-frontend-verification-2026-10-16.md` (V63-FE-2) — 6/6 e2e-сьютов,
384 проверки, 0 console errors, 49 подлинных PNG, 1 дефект U07.2,
9 owner-only пунктов.

## 2. Как обеспечивалась привязка к кандидату

Рабочее дерево репозитория содержит незакоммиченные правки приложения
(`services/disk_retention.py`, `services/param_catalog.py`, `web/app.js`,
`web/index.html`), поэтому прогоны в нём нельзя было бы привязать к
`c2775a54`. Дерево кандидата развёрнуто в managed scratch
(`git worktree add --detach … c2775a54`) и все тесты запущены там:

* `pytest -k asap8_v63` → **152 passed**, exit 0.
* `pytest -k "asap8_f* … or asap8_v6*"` → **616 passed**, exit 0.
* `node tests/js` → asap8-файлы **11/11**, все файлы **80 pass / 4 fail** (RED — см. §6).
* `tools/v63_b11_mechanisms_report.py` → exit 0 из корня (речек фикса REV-W3PRE-N2).
* Прод: `healthz` 200 `2.58.79`, `/api/health` 200, `/web/` (727145 б) и
  `/web/static/fullscreen-policy.js` (23742 б) **побайтово равны** блобам `c2775a54`
  (sha256 `/web/` = `61960177d089ba468484e8d274b06193d48a5ab984a4bbe13e51c9fda3522f38`).

## 3. Закрываемые строки (6) — proposed ledger rows

Статусная линейка карты: `VERIFIED`. Все evidence привязаны к
`c2775a54258512a3e20c97341d3e8a6738b1a33b`.
Формат: `type | ref | observation`.

| req_id | new status | evidence |
|---|---|---|
| **REQ-B07** | VERIFIED | `test` \| `tests/test_asap8_v63_b07_temporal_factcheck.py` (12 passed на дереве `c2775a54`: сид `CATEGORY_TEMPORAL` идемпотентен, `factcheck_temporal` отсутствует в выдаче карточек, новой top-level карточки нет, hot-gate/RBAC/env-ось) \| 12/12 на кандидате |
| | | `test` \| `tests/js/asap8_v63_w3_modules_ui_test.js` (asap8-js 11/11 на кандидате) + `review-w1.md` (REV-W1 APPROVED) + `review-w3.md §7` (секция «Время и источники» в Фактчеке) |
| | | `production` \| `evidence/v63-close/prod-probes-2026-10-16.md` — `/web/` побайтово = `c2775a54`, healthz 2.58.79: код-уровневая верификация относится к живому рантайму |
| **REQ-B08** | VERIFIED | `test` \| `tests/test_asap8_v63_b08_stories.py` (24 passed на `c2775a54`: детерминизм без выдуманных финалов, `content_status`, три даты, 1970→None, участники ≤5+ещё N, bounded backfill, честная лента `display_title`) |
| | | `test` \| `tests/test_asap8_f7_stories.py` (9 passed: display-имена, fallback unknown/ambiguous, нет числовых ID в UI) + `review-w3-stories-mech.md` (VERIFIED после фикса N1) + `review-w3.md §8` |
| | | `production` \| `evidence/v63-close/prod-probes-2026-10-16.md` (то же связывание) |
| **REQ-B11-SCOPE** | VERIFIED | `production` \| `w4-live-probes.md §1` + `live-canary.md` — прод-прогон отчёта: 8 ok / 2 never_run (`graph_memory`, `embeddings`), перечень SCOPE (10 механизмов) закрыт без пропусков | |
| | | `test` \| `evidence/v63-close/b11-mechanisms-report-history-db.json` — запуск того же инструмента на дереве `c2775a54` (10 секций полной цепочки REQ-B11-CHAIN; `producer_off`/`no_input`/`unavailable`/`never_run` не перекрашены) + `tests/test_asap8_v63_b11_report.py` 17/17 | |
| **V05** | VERIFIED | `ui` \| `w3-evidence-status/_ui_w3_status.json` (STATUS 26/26: один блок Сна, Status-only logs, 1970→«ещё не выполнялся») + `w3-evidence-modules` (MODULES 42/42) + `w3-evidence-analytics` (ANALYTICS 74/74) — проверено REV-W3 на кандидате волны | |
| | | `test` \| `evidence/v63-close/c2775a54-verification-runs.md §3` — asap8-js 11/11 на `c2775a54`; `tests/test_asap8_v63_w3_analytics_viz.py` 5/5; B06/B07/B01.4-клаузы V05 — в закрытых здесь же REQ-B07 и в `TestTwoChatsAndRestart` (17/17) | |
| | | `ui` \| `w2-evidence-shell/w2_shell_e2e.json` — hOverflow=false, scrollWidth==innerWidth на 320/360/390/430/667 + zoom200, header 116.2 |
| | | `ui` \| `v63-frontend-verification-2026-10-16.md §4` (V63-FE-2): V05 UI/operational VERIFIED-BY-AGENT — 3 tabs+«Ещё», один блок Сна, Status-only logs, вкладки аналитики, нет hOverflow на 320/390/landscape; 6/6 сьютов, 384 проверки, 0 console errors |
| | | `production` \| `evidence/v63-close/prod-probes-2026-10-16.md` — прод-бандл побайтово = кандидат |
| **B12.4** | VERIFIED | `live` \| `live-canary.md` + `w4-live-probes.md §1` — deploy-протокол, rollback readiness (`b9ea4907`), smoke health, 0 ERROR/Traceback, live input/output (`initiative.observe` completed 25×/24h, `ingestion_live` success) |
| | | `live` \| `evidence/v63-close/prod-probes-2026-10-16.md` — снимок адресной поверхности и automated canary: 5 путей 200, версия 2.58.79, побайтовая сверка бандла | |
| | | `test` \| `evidence/v63-close/preserve-and-workflow-audit.md §3` — аудит источников: запись уроков/SEND возможна только через persistence-слой `services/database.py` и продюсера `services/mca_experience.py`; скриптов «донабрать счётчиков» в `tools/`/`services/` нет; фальшивые SEND/lesson в прод не создаются | |
| **B10-R05** (C07) | VERIFIED | `test` \| `tests/test_asap8_v63_b08_stories.py` (24/24) + `tests/test_asap8_f7_stories.py` (9/9) на `c2775a54` — stories как содержательный рассказ с источниками/refs по правам и без выдуманного текста; делегация acceptance к REQ-B08 (закрыт) | |

## 4. Не закрываемые строки bucket (a) — 19 из 25

| req_id | Почему не закрыто (точная клауза) | Предложение |
|---|---|---|
| **B01.4** | «на живом чате 2000–5000 сообщ/сут достигается несколько содержательных реплик в сутки» — live-outcome. UI-часть и «24ч ноль opportunities → диагностика» доказаны (`test_b01_frequency_profiles_and_thin_limits`, `test_b01_day_cap_and_min_gap_cuts_spam`, `test_b01_zero_opportunities_24h_is_diagnostic_event`, js-профиль «редко/нормально/активно» 11/11), но прод-факт `opportunities=0` (`w4-live-probes.md §1`) эту клаузу не выполняет | оставить `BLOCKED_REAL_HUMAN_GATE` (canary-окно владельца), evidence UI/диагностики дописать |
| **B08.4** | «Приёмка на **10 настоящих эпизодов**» — требует эпизодов из живого чата; механизм воспроизведён детерминированно (`test_ten_episodes_deterministic_ready`, 2 темы, merged/continuation, архив, unknown outcome, refs, provenance, mobile-карточка) | оставить READY_FOR_LIVE → владелец может принять fixture-приёмку явно, тогда VERIFIED |
| **REQ-B10** | umbrella: 20 строк B10-R открыты, `REQ-B10-PYTEST` опирается на deploy-текст, а не на классификацию; плюс найденный этой lane RED (§6) | оставить READY_FOR_LIVE |
| **REQ-B11** | «и контролируемый **E2E** REQ-B11-E2E» — для `graph_memory`/`embeddings` E2E невозможен (parked-квота эмбеддингов, `never_run`) | оставить READY_FOR_LIVE; отчётная часть закрыта (REQ-B11-SCOPE) |
| **REQ-B12** | клауза «**трекнутые** артефакты» требует git-трекинга; три созданных артефакта ещё не закоммичены | закрыть сразу после коммита (§7) |
| **FINAL.4** | «ZERO … unresolved RED (либо явное разрешение владельца)» — на кандидате 4 js-RED (§6) без waver'а владельца; остальные клаузы (deployed SHA, docs/ledger, ZERO скрытых pending, отсутствие заявления «ASAP выполнен полностью») выполнены этим отчётом | закрыть после (а) ре-пина 4 js или (б) явного waver'а владельца |
| **V03** | проверка требует админ-сессии на проде и реальных данных; векторный контур деградирован. Код доказан (`test_expired_found_by_historical_query_only`, confirm/refute без delete, `test_foreign_volume_does_not_displace_local`) | оставить READY_FOR_LIVE |
| **B10-R01** | «два **реальных** Summary L2 … на production-inputs, артефакты и diff источников» — в пакете нет двух опубликованных Summary и diff'а | оставить READY_FOR_LIVE |
| **B10-R03** | «**live** негативный тест Summary OFF»; реальная генерация доказана (`TestMatrixRealGeneration`, `TestSchedulerFollowsResolver::test_tick_skips_chat_off_runs_chat_inherit` — 0 LLM-вызовов), прод-прогона с OFF нет | оставить READY_FOR_LIVE |
| **B10-R07** | «**реальный provider проход** транскрипта (407 + proxy health), не только health» — тесты 41/41 классифицируют 407/каскад/health, но реального прохода транскрипта в пакете нет | оставить READY_FOR_LIVE |
| **B10-R02** | «Текущие image/edit call, publication ID и post-recovery» — b04/scene/c03a тесты зелёные, но публикации styled в реальный чат в пакете нет (зависит от `InputRichMessageMedia`) | оставить READY_FOR_LIVE (owner) |
| **B10-R04** | «обычный групповой чат без обращений → outcome» — тесты Initiative зелёные (13/13), естественного чата нет | оставить READY_FOR_LIVE (owner) |
| **B10-R06** | «live index/backlog, rate limit/key failover» — f8-тесты зелёные, live backfill невозможен (parked-квота) | оставить READY_FOR_LIVE (заблокировано прод-деградацией) |
| **B10-R08** | «tracked документы, help, sync release — **SHA и реально проверенный report**» — help/docs-sync 24/24 зелёные на кандидате, но артефакт «реально проверенный report» появляется только с этим пакетом | оставить READY_FOR_LIVE; закрывается вместе с коммитом пакета |
| **B10-R10** | «old/new chat retrieval» end-to-end — b09/wa3 тесты зелёные, live-переноса supergroup нет | оставить READY_FOR_LIVE (owner) |
| **B10-R13** | «displacement test **и prod timing**» — 9/9 изоляция зелёные, прод-timing не измерен | оставить READY_FOR_LIVE (owner) |
| **B10-R18** | «TMA event logs, Windows native functional demo, no overlay» — mock-матрица 7/7, реальные клиенты не задействованы | оставить READY_FOR_LIVE (owner) |
| **B10-R09** | «concurrent UI edit/refresh/**409**» — поведенческого теста гонки dossier/settings с 409 не найдено (есть `asap8_v6_wa2_dossier_guard_test.js` — клиентский guard) | оставить READY_FOR_LIVE; написать 1 тест |
| **B10-R11** | «**реальные** моды, запрет без ключа, бюджет/evidence» — 43 теста (d03 9 + d04 34) доказали контракт на кандидате; live-режимов Direct L1 в пакете нет | оставить READY_FOR_LIVE |
| **B10-R12** | «genuine lesson applied» — 18/18 e2e (коррекция→применённый урок) доказали контракт; live-урока из боя нет | оставить READY_FOR_LIVE |
| **B10-R14** | «UI write/read/**restart** 2 чата» — 11/11 overrides (RBAC, изоляция, fail-closed); restart-сценарий именно на 2 чатах через UI не воспроизведён | оставить READY_FOR_LIVE |
| **B10-R15** | «Dream/Deep Sleep/paradigms … outcome, причины zero, фактические изменения» — 10 тестов + B11 (prod dream/deep_sleep ok); «фактических изменений» как артефакта нет | оставить READY_FOR_LIVE |
| **B10-R16** | «live examples **и** machine key inventory» — inventory (16/16) и контракт дат (23/23) доказаны, live-примеров датирования Фактчека в пакете нет | оставить READY_FOR_LIVE |
| **B10-R17** | «**все 7** отложенных визуализаций и mobile UI — **реальные data**, скриншоты **всех размеров**». V63-FE-2 подтвердила кадры подлинными и покрытие 8 классов viewport, но: (1) U05.3 — OWNER-ONLY по данным («7 визуализаций на подтверждённых данных» требует прод-данных), (2) у `status` нет одиночного viewport на 768/1024/1440, у `cover_editor`/`fullscreen` нет 360/430/768, (3) её прогоны привязаны к рабочему дереву `a854ad95 + delta web/`, а не к `c2775a54` | оставить READY_FOR_LIVE; закрывается после коммита дерева/перепрогона на `c2775a54` |
| **B10-R19** | «**видео изгиба линии**, perf, fallback» — Tier A/Tier B приняты (`ui-acceptance.md`, сканлайн dx −5…−8/центр 0/контроль corr 1.0), FPS — headless-прокси; видео в пакете отсутствует, физический FPS — owner (V07) | оставить READY_FOR_LIVE |

Итого из 25 строк bucket (a): **6 закрыто** (REQ-B07, REQ-B08, REQ-B11-SCOPE,
V05, B12.4, B10-R05; аудит перечислял в bucket (a) `B10-R08` — в этом отчёте
закрыта строка B10-R05, R08 остаётся открытым по причине выше),
**19 остаются открытыми** с конкретными клаузами: B01.4, B08.4, REQ-B10,
REQ-B11, REQ-B12, FINAL.4, V03, B10-R01, R03, R07, R08, R09, R11, R12, R14,
R15, R16, R17, R19. Дополнительно (вне bucket (a), для полноты) в таблице
приведены B10-R02, R04, R06, R10, R13, R18 — они были в owner-/blocked-баккетах
аудита и остаются открытыми по тем же причинам.

## 5. Required-PENDING (9 строк) + 2 смежные — диспозиции

| req_id | Диспозиция | Условие закрытия |
|---|---|---|
| **B12.1** | артефакты произведены (`review-ledger.md`, `integration-evidence.md`, `v63-final-coverage-report-2026-10-16.md`); `ui-acceptance.md` подтверждён tracked по пути `w2-evidence-glass/ui-acceptance.md`; собственный resolved status есть у каждой из 222 строк карты; маркеров `__PENDING__` в финальном отчёте нет | **коммит** артефактов + `git log --all --name-only` показывает файлы + `grep -c __PENDING__ v63-final-coverage-report` = 0 |
| **FINAL.1** | coverage-таблица «проблема→RCA→исходники→RED→GREEN/Review→deployed SHA→outcome→статус» произведена (`v63-final-coverage-report-2026-10-16.md §2`) | коммит |
| **PRIN-OUTCOME** | по каждому ID в финальном отчёте — наблюдаемый outcome или BLOCKED_ACCESS с причиной (§2, §4) | коммит |
| **PRIN-PIPELINE-FIRST** | таблица цепочки source→event→processing→decision→output→feedback по каждому B с артефактом на каждом звене (`integration-evidence.md §3`); live-плечи честно отмечены как owner-гейты | коммит |
| **PRIN-ONE-WORKFLOW** | аудит: ΔDDL=0, новых очередей/БД/воркеров 0, используются existing SQLite+PostgreSQL, human-gate к Architect задокументирован (`db8dae53`) — `preserve-and-workflow-audit.md §1` | коммит |
| **PRIN-PRESERVE** | deploy-план с backup/rollback/feature-gate + сводка зелёных негативных тестов сохранности (`preserve-and-workflow-audit.md §2`, 152+616 passed на кандидате) | коммит |
| **REQ-B12** | validator/статусы/deploy-протокол/reconciliation/snapshot подтверждены; клауза «трекнутые артефакты» — после коммита | коммит |
| **FINAL.4** | все клаузы выполнены, кроме «unresolved RED»: 4 js-RED на кандидате | ре-пин 4 js **или** явное разрешение владельца |
| **FINAL.3** | **не закрыто**: вердикт V63-FE-2 получен — 49 PNG подлинные, 8 классов viewport покрыты; остаются: (1) у `status` нет одиночного-viewport кадра 768/1024/1440 (`status_768x1024.png` = full-page 768×4780), (2) у `cover_editor`/`fullscreen` нет 360/430/768, полноэкранного захвата на desktop нет вовсе, (3) папка `evidence/` untracked, а прогоны V63-FE-2 привязаны к рабочему дереву, не к `c2775a54` | вердикт V63-FE-2 учтён; добор кадров + коммит `evidence/` |
| **REQ-0-1** | **не закрыто**: 24/48h §0.1-датасет не собран (`baseline-inventory.md:82`) | сбор на сервере (§7) |
| **B12.6** | **не закрыто**: side effects не измерены; нет негативных тестов на «GraphRAG hallucinated stats» и на ошибочного адресата (`preserve-and-workflow-audit.md §4`) | 1 маленький лейн (3 теста + 1 замер) |

## 6. Новые находки этой lane

1. **RED на кандидате (важно).** `tests/js/round1025_hotfix{7,8,9,10}_*.js`
   падают на `c2775a54`: `assert.ok(/APP_VERSION = "2.58.78"/)` — релизный bump
   до 2.58.79 сломал версионный пин (REV-W2/REV-W3 фиксировали 0 failed до bump).
   Причина механическая, функциональной регрессии нет, но это **незакрытый RED
   на задеплоенном коммите** — влияет на FINAL.4 и на тезис «нет зелёного релиза
   при необъяснённой регрессии». Воспроизводимо: `cd tests/js && node round1025_hotfix7_shell_glass_heartbeat_test.js`.
2. **Расхождение двух артефактов по B11.** `w4-live-probes.md:17` заявляет
   «B11 на проде **с PG DSN** … gate-слой теперь покрывает и PG-каталог», а
   `live-canary.md:52` фиксирует `POSTGRES_DSN не передан`, `pg_available=false`,
   `pg_dsn_not_provided`. Оба не могут быть верны одновременно; фактическая
   команда в `live-canary.md:46` аргумента `--pg-dsn` не содержит. Требуется
   либо корректировка claim, либо перезапуск с `--pg-dsn`.
3. **Внешний домен с этой машины резолвится** (`https://admin-bot.duckdns.org`,
   5 успешных запросов) — ограничение «unverified-from-this-host (local DNS down)»
   из `w4-live-probes.md §1` и `live-canary.md §71` больше не действует для
   HTTP-проверок; live-привязка кандидата выполнена и воспроизводима.
4. **Дефект U07.2 (из вердикта V63-FE-2, воспроизводим агент-стороной):**
   горизонтальные `safeAreaInset` игнорируются — hit-box fullscreen-контрола
   заезжает в native-правую зону на 28 px в landscape-cutout. Влияет на
   U07.2/U07-SYM-ANDROID; правка однослойная, но требует отдельного лейна.

## 7. Минимальный список прод-команд для одного подключения DevOps

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git rev-parse HEAD                                        # ожидаем c2775a54258512a3e20c97341d3e8a6738b1a33b
POSTGRES_DSN="<из /etc/systemd/system/admin_bot.service или hot-конфига>" \
  venv/bin/python tools/v63_b11_mechanisms_report.py --db local_database.db \
  --pg-dsn "$POSTGRES_DSN" --json /tmp/b11_prod_pg.json   # снять расхождение §6.2
# §0.1-датасет для REQ-0-1 (24/48h): API-логи, trace, job states, counters,
# ingest cursor, LLM errors, UI-факты Status/Analytics → в отчёт, без секретов
```

Повторных коннектов не требуется; всё остальное lane закрыла локально.

## 8. Где классификация аудита/реконсиляции неточна

1. **Bucket (a) «закрываемо агентом, 25» завышен.** На строгом чтении
   acceptance закрываются 6 строк (REQ-B07, REQ-B08, REQ-B11-SCOPE, V05, B12.4,
   B10-R05), а не 25. Остальные 19 содержат клаузу, требующую live-чата,
   реального клиента, реального provider-прохода, прод-рендера на реальной БД
   или git-трекинга артефактов — перечень и точные клаузы в §4.
2. **B10-R08 и B10-R16 аудит держал в bucket (a) — для R08 это верно лишь
   отчасти** (help/docs-sync доказан, но «реально проверенный report» требует
   коммита этого пакета), а **R16 не закрывается**: «live examples» в пакете нет,
   закрыта только половина клаузы (machine key inventory + контракт дат).
3. **«14 owner-гейтов» → 18** — согласен с реконсиляцией (R6): `w4-live-probes.md`
   держал V01/V02/V04/V06 как owner-гейты, карта — как READY_FOR_LIVE.
4. **F-2 аудита («430 и 768 отсутствуют полностью») неверно** — согласен с
   поправкой реконсиляции и с вердиктом V63-FE-2: 49 PNG подлинные, все 8
   классов viewport есть. **Суть находки сохраняется в более узкой форме:**
   у `status` нет одиночного-viewport кадра 768/1024/1440 (full-page), у
   `cover_editor`/`fullscreen` нет 360/430/768, полноэкранного захвата на
   desktop нет вовсе, папка `evidence/` untracked, а прогоны V63-FE-2 привязаны
   к рабочему дереву, а не к `c2775a54`.
5. **F-3 («768 не пробовался нигде») неверно** — `_v63fe_measurements.json`
   содержит `status/768x1024`, `analytics_overview/768x1024`,
   `analytics_processes/768x1024`, `modules/768x1024`, `style_editor/768x1024`
   (vw=768, vh=1024, hOverflow=false, headerH 116.2, console_errors=[]).
   Незакрытой остаётся REQ-0-1 (сам §0.1-датасет), а не «нет пробы 768».
6. **`REQ-B11-E2E` отнесён к bucket (c) «заблокировано прод-деградацией»** —
   согласно этому, но стоит учесть строку источника `:405`: «когда нет
   безопасного natural-сценария — **безопасный staging с настоящими
   source/DB/worker**». Для не-векторных механизмов это выполнимо агентом;
   блокировка касается только `graph_memory`/`embeddings`.

## 9. Риски и границы

* Кадры `evidence/v63-frontend/` этой lane не трогались и не перепроверялись;
  все ссылки на них (FINAL.3, B10-R17) помечены как «ждёт вердикта V63-FE-2».
* Backend-инвариант «сервер = кандидат» держится на механике деплоя
  (`live-canary.md`: `git pull --ff-only`, HEAD сервера = кандидат) + версии
  2.58.79 + побайтовой сверке `/web/`; прямого доступа к файлам сервера не было.
* Карта покрытия не редактировалась: все предложения статусов — в этом файле и
  требуют применения письмом с последующим коммитом (одной scoped-коммит
  сессией Orchestrator вместе с фронтенд-лейном).
