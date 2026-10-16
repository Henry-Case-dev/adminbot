# review-ledger — ASAP 8 v6.3 live correction

Артефакт, требуемый строкой `source-lines-37423-EOF.md:409` (B12.1):
«Трекнуть `requirements-map.md`, `review-ledger.md`, `integration-evidence.md`,
`ui-acceptance.md`, `live-canary.md`, `release-reconciliation.md, скриншоты/видео
с замаскированными личными данными. Каждый подпункт B01–B12, U01–U08, V01–V07
имеет собственный resolved status».

Кандидат/деплой всего эпика: `c2775a54258512a3e20c97341d3e8a6738b1a33b`
(2.58.79). Этот файл — сводный журнал **всех** раундов ревью/верификации по
эпику: вердикт, находки, диспозиция по каждой находке, ссылка на реальный
документ. Отдельных «галочек раздела» здесь нет — по каждому пункту записан
исход.

## 1. Раунды

| # | Раунд | Документ | Кандидат | Дата | Вердикт |
|---|---|---|---|---|---|
| R1 | REV-W1 (Wave 1, backend B01–B09/B10-фикс) | `review-w1.md` | `f1418d7` (= `1e24eca` W1 + docs `bc91b90`) | 15.10.2026 | **NEEDS_FIXES** → закрыт фикс-нотой |
| R2 | REV-W2 (Wave 2, U01/U02/U07/U08) | `review-w2.md` | `c053528` | 15.10.2026 | **Approved** (в объёме Wave 2) |
| R3 | REV-W3PRE (B08 backend + B11) | `review-w3-stories-mech.md` | `ccdd0a7` (=`4b64b38`+`ccdd0a76`) | 15.10.2026 | **Needs Fixes** → закрыт фикс-нотой |
| R4 | REV-W3 (Wave 3, B05/U06/U03/U04/U05/B06/B07/B01.4/B08-UI) | `review-w3.md` | `da58e24b` | 16.10.2026 | **Approved** (в объёме Wave 3) |
| R5 | Независимый аудит релиза (read-only) | `verification-report-2026-10-16.md` | `c2775a54` (deployed) | 16.10.2026 | **Эпик НЕ завершён** (3 ложных VERIFIED, 48 READY_FOR_LIVE, 18 owner-гейтов) |
| R6 | Реконсиляция карты покрытия | `map-reconciliation-2026-10-16.md` | `c2775a54` | 16.10.2026 | демоушен 9 строк + 4 переключения V01/V02/V04/V06 |
| R7 | Закрытие агентского остатка (эта lane) | `v63-agent-close-2026-10-16.md` | `c2775a54` | 16.10.2026 | 7 строк закрыто, 18 — открыты с точными причинами |

Смежные ревью-артефакты фронтенда (вне журнала раундов, но влияют на вердикты):
`w2-evidence-glass/ui-acceptance.md` (два вердикта U08: optical Tier A passed,
frost Tier B passed), `w4-live-probes.md` (V01–V07), `release-reconciliation.md`
(f10-расхождение), `baseline-pytest-b10.md` (классификация 3 failed pytest).

## 2. Находки и диспозиции

| ID | Раунд | Строка/область | Находка | Диспозиция |
|---|---|---|---|---|
| REV-W1-F1 | R1 | B09 (safe backup) | backup читался `LIMIT 200_000`, cap-hit давал только WARNING, перенос продолжался для незабэкапленных строк — нарушение acceptance B09 | **ИСПРАВЛЕНО** `72cab8fc`: chunked backup до исчерпания (`_BACKUP_CHUNK=5000`, rowid-курсор), `_BACKUP_HARD_CAP=5M` → явная ошибка + abort. Речек 39 passed, 2 регресс-теста |
| REV-W1-N1 | R1 | B09 | аварийные пути возвращали `None` → AttributeError в `on_chat_migrated` | **ИСПРАВЛЕНО** тем же `72cab8fc` (`return result`) |
| REV-W1-N2 | R1 | B01.1 | `reply_to_id` не попадает в eval-промпт (reply-структура не видна оценщику) | **ПРИНЯТО (non-blocking)** → backlog |
| REV-W1-N3 | R1 | B01 | REACT фиксируется как решение, recheck-плечо canary-воронки не пишется | **ПРИНЯТО (non-blocking)** → учесть при интерпретации canary |
| REV-W1-N4 | R1 | B06 | 422 на inert override покрыт source-string тестом, не поведенческим | **ЗАКРЫТО в W3** (`web/api` guard + e2e-чеки REV-W3 §7) |
| REV-W1-N5 | R1 | B02 | regex-детектор сохранён как hybrid-вход | **ПРИНЯТО (осознанное решение)** → владельцу на заметку |
| REV-W1-N6 | R1 | B04.6 | scene-verify требует явного env, иначе `scene_preserved=unknown` | **ОТКРЫТО** — задача owner (включить `COVER_STYLE_SCENE_VERIFY=preview/all` на canary), иначе evidence останется unknown |
| REV-W2-N1 | R2 | U08.4d | `.lg-mini-lens` не применён на прод-⛶ | **ОТКРЫТО (non-blocking)** — W4-hardening |
| REV-W2-N2 | R2 | assets | мёртвый `web/static/vendor/lg-lens-map.png` (6.7 КБ) | **ОТКРЫТО (non-blocking)** |
| REV-W2-N3 | R2 | exposure | `/static/glass-teststand.html` доступен без auth на проде | **ОТКРЫТО (non-blocking)** — W4-hardening: за gate или убрать из прод-пакета |
| REV-W2-N4 | R2 | U08.5.1 | нет 1:1 close-up маленького ⛶-контрола | **ОТКРЫТО (non-blocking)** |
| REV-W2-N5 | R2 | app.js | дубликат `_prefersReducedMotion` (app.js:18314/18333) | **ОТКРЫТО (non-blocking)** |
| REV-W2-U07-live / U08-FPS | R2 | U07/U08 | mock + headless-FPS ≠ реальные клиенты/физический Android | **ОТКРЫТО → owner-гейт** (V06/V07) |
| REV-W3PRE-N1 | R3 | B08 лента | `_feed_item` отдавал сырой `title` из `stories_titles` — легаси-заглушка «Эпизод 1780…» проходила в ленту | **ИСПРАВЛЕНО** `f8f9d9a0` (`_stories_display` + `stories_rows`), +2 регресс-теста (24 passed) |
| REV-W3PRE-N2 | R3 | B11 | `py -3 tools/v63_b11_mechanisms_report.py` падал `ModuleNotFoundError: config` из корня | **ИСПРАВЛЕНО** `f8f9d9a0` (sys.path-бутстрап); перепроверено этой lane: exit 0 из корня |
| REV-W3PRE-NB-1/2 | R3 | B08 | эпизод с ключами, но короткими сообщениями — вечный кандидат backfill; `reextract_episode` пишет `updated_at=now` | **ПРИНЯТО (non-blocking)** → backlog |
| REV-W3-NB-1 | R4 | W3 | `tools/ui_asap8_v63_w3_status_e2e.py` не был закоммичен | **ИСПРАВЛЕНО** `d5794ddd` |
| REV-W3-NB-2 | R4 | W3 | fingerprint `w3-evidence-status` привязан к CRC W3a | **ПРИНЯТО** — superseded перепрогоном на HEAD |
| REV-W3-NB-3 | R4 | B10 | flaky `test_direct_chat_concurrency` (FakeDB-артефакт) | **ОТКРЫТО** — зона B10/W4 (`baseline-pytest-b10.md` item 1) |
| REV-W3-NB-4 | R4 | W3 | незакоммиченный `services/disk_retention.py` | **ОТКРЫТО (вне эпика)** |
| AUDIT-F-1 | R5 | B12.1 | `review-ledger.md` и `integration-evidence.md` отсутствовали в репо и в `git log --all`; финального отчёта v6.3 не было; `ui-acceptance.md` лежит вне корня пакета | **ЧАСТИЧНО ЗАКРЫТО этой lane** — документы созданы (`review-ledger.md`, `integration-evidence.md`, `v63-final-coverage-report-2026-10-16.md`); `ui-acceptance.md` подтверждён как tracked по пути `w2-evidence-glass/ui-acceptance.md`; **осталось: коммит** (lane без git) |
| AUDIT-F-2 | R5 | FINAL.3 | 430/768 «отсутствуют полностью», 360 — только кропы | **УТОЧНЕНО R6 + этой lane**: 430 и 768 есть (5 маршрутов), 360 — 5 полноценных viewport-кадров; **но** `status_768x1024.png` — full-page 768×4780, а `cover_editor`/`fullscreen` не имеют 360/430/768, и папка `evidence/` untracked → строка остаётся открытой |
| AUDIT-F-3 | R5 | REQ-0-1 | `baseline-inventory.md:82` — «§0.1-данные для сбора на S0», 24/48h датасет не собран | **ОТКРЫТО** — сбор на сервере за владельцем/DevOps |
| AUDIT-NB-3 | R5 | десятки строк | общий deploy-текст как evidence неродных строк | **ЧАСТИЧНО ЗАКРЫТО** — R6 заменил ref на конкретные; эта lane добавила реальные артефакты в `evidence/v63-close/` |
| AUDIT-NB-4 | R5 | прод | деградация векторного контура (parked-квота эмбеддингов) | **ОТКРЫТО** — backlog (`plans/backlog.md`), честно блокирует часть live |
| MAPFIX-1..9 | R6 | B12.1, FINAL.1, FINAL.3, REQ-0-1, PRIN-OUTCOME, PRIN-PIPELINE-FIRST, PRIN-ONE-WORKFLOW, PRIN-PRESERVE, B12.6 | демоушен VERIFIED→PENDING без доказательств | **ЗАКРЫТО бухгалтерски**; статус по каждой строке — в `v63-final-coverage-report-2026-10-16.md` |
| MAPFIX-V | R6 | V01/V02/V04/V06 | расхождение карты и `w4-live-probes.md` | **ЗАКРЫТО** — 18 owner-гейтов, не 14 |
| CLOSE-1 | R7 | candidate binding | прод-фронтенд побайтово = `c2775a54` (`/web/` sha `61960177…`, `/web/static/fullscreen-policy.js` sha `c868a42e…`), healthz 2.58.79 | **НОВОЕ** (`evidence/v63-close/prod-probes-2026-10-16.md`) |
| CLOSE-2 | R7 | RED на кандидате | 4 js-файла RED на `c2775a54`: `round1025_hotfix7/8/9/10_*_test.js` пинят `APP_VERSION "2.58.78"` | **ОТКРЫТО** — механический версионный пин, сломан релизным bump; правка тестов вне WRITE_SCOPE lane |
| CLOSE-3 | R7 | B11 | `w4-live-probes.md:17` заявляет прогон «с PG DSN» и покрытие PG-каталога, а `live-canary.md:52` фиксирует `POSTGRES_DSN не передан`, `pg_available=false` | **ОТКРЫТО** — нужно либо исправить claim, либо повторить B11-прогон с `--pg-dsn` (DevOps) |

## 3. Ledger-свода по раундам (что признано ревьюерами)

* **R1 (код+тесты, ревьюером):** B01, B02, B03, B04, B06, B07, B10-фикс VERIFIED;
  B09 NEEDS_FIXES → IMPLEMENTED+TESTED (fix applied). Live/wave-4 по B01–B09 отложены честно.
* **R2:** VERIFIED 24, UNVERIFIED→BLOCKED_ACCESS 2 (U07 live, U08 физический FPS), N/A 1, FAILED 0.
* **R3:** B08.1–B08.4 + B11 SCOPE/CHAIN/диагнозы VERIFIED (B08.4 — на fixtures);
  2 блокера → оба исправлены; UI/live вне объёма.
* **R4:** CORR-1, B05, U06, U03, U04, U05, B06-UI, B07-UI, B01.4-UI, B08-UI,
  f7-re-pin VERIFIED; e2e перепрогнаны на кандидате (EDITOR 40/40, STATUS 26/26,
  ANALYTICS 74/74, MODULES — все чеки); js 84/84 на том кандидате (до bump 2.58.79).
* **R5:** релиз задеплоен и привязан к кандидату, ядро волн имеет реальные
  артефакты; эпик не закрыт — см. находки выше.
* **R6:** бухгалтерия приведена к артефактам; 18 owner-гейтов; release-gate RED 110.
* **R7 (эта lane):** 7 строк предложено VERIFIED, 6 — условно после коммита
  артефактов, остальное открыто с причинами (см. lane-отчёт).

## 4. Незакрытый RED (состояние на 16.10.2026)

| Что | Где | Статус |
|---|---|---|
| 4 js-файла с пином `APP_VERSION "2.58.78"` | `tests/js/round1025_hotfix{7,8,9,10}_*.js` | RED на кандидате, причина механическая |
| 1 pytest (`test_direct_chat_concurrency…n2`) | `baseline-pytest-b10.md` item 1 | RED, RCA требует разрешения в волне B10 |
| release coverage gate | `requirements_gate.py --stage release` | RED, exit 1, scoped=200, errors=110 |

Ни один из этих RED не перекрашен: они требуют правки кода/тестов, что вне
WRITE_SCOPE этой lane, и должны быть закрыты отдельным минимальным фиксом.
