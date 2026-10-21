# Prep: RFL-recon — классификация READY_FOR_LIVE-хвоста (requirements-map.json)

> Рекон PM-ASAP8-RFL-RECON, 2026-10-21. Read-only по карте. Read-time HEAD `4ff3e7d4` (legacy-биндинг уже применён).
> В задании было «37 RFL»; на момент чтения карты **33** — 4 строки уже перевязаны лейном legacy-binding (коммит `4ff3e7d4`).
> Не противоречит prep-legacy-binding.md; documented facts учтены (U08.4d/U08.5.1 — REAL, PENDING; B12.6 — 3 остатка, PENDING; U07-OWNER-REALDEV — действующий owner_optional-спутник).

## Счётчики (33 RFL-строки)

| Вердикт | строк |
|---|---|
| REUSE_DEPLOYED (доставлено и задеплоено 2.58.80–104, нужен только биндинг к deployed-evidence) | 15 |
| REAL_LIVE (реальный прогон/артефакт, которого не было) | 18 |
| OWNER_OPTIONAL | 0 — device-наблюдения уже консолидированы в `U07-OWNER-REALDEV` (owner_optional, вне RFL) |
| SUPERSEDED | 0 |
| CONTEXT | 0 |

Механическим биндингом закроется **15 строк**; 18 требуют живого прогона/артефакта (группа закрывается 5 компактными пробами, см. ниже).

## Таблица вердиктов (33 строки)

| Строка | Вердикт | Evidence-указатель / причина |
|---|---|---|
| REQ-B01-DOD (L60) | REUSE_DEPLOYED | LIVE-FUNNEL закрыт live 18.10: воронка scan=280→opportunity=6→decided=4→writer_generated=2→**sent=2** (`plans/features/soul-1/review-ledger-p0-final.md`, p0-save-init-ux/nostalgia evidence); b01-сьют 13/13 @31c16555 (two-chat isolation/reboots/chat OFF); chat-OFF live = `cron skip (disabled)` (tick-observation-25883). Хвост: 7d-мониторинг частоты — наблюдение, не блокер |
| REQ-B02-DOD (L75) | REAL_LIVE | ≥10 сценариев — тесты (18/18 контракт); «1 доказанный lesson» из боя — нет (v63-agent-close §4: «live-урока из боя нет»; B11: last attempt failure 10.10 disclosed). Acceptance допускает честный статус «недостаточно данных» — ждёт естественного потока |
| REQ-B03-DOD (L90) | REAL_LIVE | Инженерные RED/GREEN (displacement, no-delete infinite) перепрогнаны @31c16555; живая часть («архивный факт найден и попал в relevant context», «3500+ не ломают задержку») — та же проба, что V03; prod-timing не измерен |
| REQ-B04-DOD (L106) | REUSE_DEPLOYED | Реальный профиль `medved_press` rev7 — styled cover опубликован в Telegram 17.10 07:00 (OK после retry) и 13:00 (чистый ран, rich `1164062`): tick-observation-25883 + incident-tail-25887 §1; реальные фолбэки (prompt_limit/bad_json→base) наблюдались live; негативы — b04-сьют @31c16555; профиль владельца не менялся |
| REQ-U07-HARD (L233) | REUSE_DEPLOYED | fs-HOTFIX 2.58.84 @0b7a0aca изолированным релизом: policy `96db0642` байт-в-байт в проде, матрица S1–S13 12/12, postdeploy-пробы (release-fs-25884-report; 3-я evidence-строка уже в карте). Real-client часть — в `U07-OWNER-REALDEV` (owner_optional) |
| REQ-U08-DOD (L336) | REUSE_DEPLOYED | W2-glass + rebind 31c16555: ui-acceptance.md знаки (a)–(d) PASS с измерениями, glass_playwright_results.json; CSP live (data: разрешён, w4 §1). Дефект мини-линзы — отдельные PENDING U08.4d/U08.5.1, к этой строке не относится |
| REQ-B06-DOD (L348) | REUSE_DEPLOYED | TestMatrixRealGeneration (два чата, расходящиеся артефакты по override) + b06-сьют 17/17 @31c16555; реальная генерация в проде живая (тики 16–17.10). Оговорка: второй прод-чат disabled — двухчатовое расхождение доказано контролируемой real-generation матрицей, live single-chat подтверждён тиками |
| REQ-B09-BODY (L369) | REAL_LIVE | b09/wa3-тесты зелёные; end-to-end живого переноса/alias-проверки на реальных old/new chat_id не выполнялось (agent-close §4, R10: «live-переноса supergroup нет»). Закрывается одной контролируемой пробой с B10-R10 |
| B10-R01 (L377) | REAL_LIVE | «Два реальных Summary L2 (абзацы)»: задокументирован 1 чистый L2-ран (17.10 13:00, 9 абзацев, `1164062`); второй + diff источников — нет. Возможно закрылось тиками 18–20.10 — read-only речек журнала может закрыть механически |
| B10-R02 (L378) | REUSE_DEPLOYED | Styled-доставка в реальный чат есть: COVER_RICH_PUBLISH_SUCCEEDED, cover styled OK (17.10 ×2), publication ID (message_id) в tick-отчётах; post-recovery/prompts — b04/c03a тесты + editor e2e |
| B10-R03 (L379) | REUSE_DEPLOYED | Live-негатив возник естественно: L2-деградация→LEGACY_FALLBACK на тиках 16–17.10 не сломала Direct/инициативу/cover (все публиковались и работали) — tick-observation-25883 + incident-tail-25887; контракт — TestMatrixRealGeneration + chat-off skip тесты |
| B10-R04 (L380) | REUSE_DEPLOYED | Ровно эта клауза = LIVE-FUNNEL 18.10 (обычный групповой чат без обращений → outcome, sent=2); см. REQ-B01-DOD |
| B10-R06 (L382) | REAL_LIVE | Live index/backfill невозможен: квоты всех 3 групп exhausted/parked 16.10 (w4 §3); ротация в бою подтверждена журналом (429→429→429, разные группы). Ждёт восстановления квоты провайдера + backfill-проба |
| B10-R07 (L383) | REAL_LIVE | Реальный provider-проход транскрипта (407 + proxy health) не выполнялся — только классифицирующие тесты 41/41 |
| B10-R08 (L384) | REUSE_DEPLOYED | Артефакты пакета tracked и закоммичены (release-reconciliation.md, help-sync 24/24 пины на релизах 2.58.88–104, F8 --check 582==REGISTRY в каждом bump-гейте) |
| B10-R09 (L385) | REAL_LIVE | Поведенческого теста гонки dossier/settings с 409 нет (только клиентский guard) — нужен 1 тест + проба (agent-close §4) |
| B10-R10 (L386) | REAL_LIVE | Живого переноса supergroup нет; закрывается пробой вместе с REQ-B09-BODY |
| B10-R11 (L387) | REAL_LIVE | Direct L1: 43 теста контракт (d03 9 + d04 34) @кандидате; live-примеров реальных модов/запрета без ключа в проде не собрано (journal-речек может дать частичное закрытие) |
| B10-R12 (L388) | REAL_LIVE | «genuine lesson applied» — 18/18 e2e доказали контракт; live-урока из боя нет (agent-close §4, явная рекомендация «оставить READY_FOR_LIVE») |
| B10-R13 (L389) | REAL_LIVE | Displacement 9/9 в тестах; прод-timing не измерен — read-only замер на реальной БД |
| B10-R14 (L390) | REAL_LIVE | 11/11 overrides (RBAC/изоляция/fail-closed); restart-сценарий именно на 2 чатах через UI не воспроизведён — контролируемый прогон |
| B10-R15 (L391) | REAL_LIVE | Dream/Deep Sleep: gate off по умолчанию (b11: producer_off честно), «фактических изменений» нет и быть не может при выключенном продюсере. Нужен прогон при включённом гейте либо явное решение владельца о невключении (не выдумывать Human Gate) |
| B10-R16 (L392) | REAL_LIVE | Machine key inventory 16/16 + контракт дат 23/23; live-примеры датирования Фактчека не собраны (read-only сбор из прод-логов/БД) |
| B10-R17 (L393) | REUSE_DEPLOYED | recap-25880: 48 whole-viewport кадров, 6 поверхностей × 8 классов на дереве деплоя 31c16555, IHDR==вьюпорт машинно (png_index.json, verify_summary.json); подлинность кадров — V63-FE-2 (49 PNG, 0 console errors). Прод-данные в поверхностях — owner-наблюдение уже в U07-OWNER-REALDEV-классе добровольных |
| B10-R18 (L394) | REUSE_DEPLOYED | TMA event logs (mock-matrix 7/7 + postdeploy-пробы 2.58.84), no overlay (recap/fs-matrix S1–S13); «Windows native functional demo» — device-часть, консолидирована в U07-OWNER-REALDEV |
| B10-R19 (L395) | REAL_LIVE | Оптика/fallback/perf-прокси приняты (ui-acceptance.md, rebind stand_wave); **видео изгиба линии** в пакете отсутствует (repo: 0 webm/mp4/gif) — производимо агентски (Playwright-секвенция), физический FPS — добровольное device-наблюдение |
| REQ-B11-E2E (L405) | REAL_LIVE | Контролируемый E2E для `graph_memory`/`embeddings` невозможен при parked-квоте (честно never_run, 8 ok / 2 never_run); отчётная часть закрыта (REQ-B11-SCOPE). Тот же внешний триггер, что B10-R06 |
| V01 (L420) | REUSE_DEPLOYED | LIVE-FUNNEL 18.10: естественный повод→решение→**sent=2**; chat OFF отсекает (cron skip live); Direct жив (prod-журнал). Биндинг: review-ledger-p0-final.md + p0-save-init-ux evidence |
| V02 (L422) | REAL_LIVE | См. REQ-B02-DOD/B10-R12: semantic capture→lesson→application на естественном потоке не наблюдалось |
| V03 (L424) | REAL_LIVE | Требует контролируемой пробы на реальных данных (16.10: «READY_FOR_LIVE, админ-сессия»; векторный контур был деградирован — FTS-only); код перепрогнан @31c16555 |
| V04 (L426) | REUSE_DEPLOYED | Styled применён и опубликован в Telegram 17.10 (×2, rich); фолбэки при реальной невозможности наблюдались live; selection стабильность — w3 e2e 40/40 @31c16555 |
| V06 (L431) | REUSE_DEPLOYED | Engineering-часть: mock-матрица + postdeploy-пробы 2.58.84 (3-я evidence-строка карты, live 0b7a0aca); real-client часть — U07-OWNER-REALDEV (owner_optional) |
| V07 (L433) | REUSE_DEPLOYED | ui-acceptance.md (optical Tier A / frost Tier B PASS), rebind glass_playwright_results + reduced_motion, CSP live-проверен (w4 §1); физический FPS — добровольное device-наблюдение |

## REAL дефекты/хвосты и suggested-slice

1. **U08.4d + U08.5.1 (PENDING, вне RFL) — REAL дефект:** клауза мини-линзы ⛶ не доставлена — класс `.lg-mini-lens` определён (app.css:3839, входит в Tier-A селектор app.js:23024, glass-refraction.js:73), но ни один коммит не привязывает его к кнопке (index.html несёт только `header-fs-btn`). *Suggested slice:* `FE-GLASS-MINILENS` — 1-файловая привязка класса к `header-fs-btn` + e2e-проверка применения; затем биндинг обеих строк.
   - **FIX APPLIED @`6c1dea40` (21.10.2026, лейн FIX-GLASS-MINILENS), PENDING DEPLOY:** класс `lg-mini-lens` добавлен в разметку кнопки ⛶ (тот же узел/действие: `@click` → `toggleFullscreen` → FullscreenPolicy.request/exit); btn-ghost/hover-заливки сняты (материал не стирается, hover — brightness); геометрия 44×44 сохранена. Тест: `tests/js/asap8_u084d_mini_lens_binding_test.js` (REGRESSION, MINI-LENS-BINDING-OK) + когерентные пины hotfix6/fs-policy; смежные node-сьюты и pytest (avatars/cfg04) зелёные. Карта U08.4d/U08.5.1 остаётся **PENDING** — перевод в VERIFIED только по deployed-проверке после релиза (live_required: preprod).
2. **B12.6 (PENDING) — 3 остатка леджера 16.10:** негатив «ошибочный адресат», негативы «GraphRAG hallucinated stats», измеримость side effects. *Suggested slice:* `B12-6-RESIDUALS` — 3 теста + 1 замер (agent-close §5 давал ту же оценку).
3. **Группа PROBE-SUMMARY (read-only речки с сервера):** B10-R01 (второй L2-ран + diff — вероятно уже есть в тиках 18–20.10), B10-R16 (live-примеры датирования), B10-R13 (prod-timing displacement).
4. **Группа PROBE-MEMORY-MIG:** V03 + REQ-B03-DOD + REQ-B09-BODY + B10-R10 — одна контролируемая проба retrieval/alias на реальных данных.
5. **Группа PROBE-EXPERIENCE (WAITING_EXTERNAL-характер):** REQ-B02-DOD + V02 + B10-R12 — ждут естественного боевого потока; мониторинг journal.
6. **Группа PROBE-EXTERNALS:** B10-R06 + REQ-B11-E2E (триггер — восстановление квоты эмбеддингов), B10-R07 (YouTube 407 provider pass), B10-R11 (journal-речек Direct-модов).
7. **Группа PROBE-UI:** B10-R09 (1 тест 409-гонки + проба), B10-R14 (UI write/read/restart 2 чата), B10-R19 (видео изгиба + perf-артефакт).
8. **B10-R15 (Dream):** условие — включение гейта или явное решение владельца; сейчас честный producer_off. Не конвертировать в Human Gate без сверки (standing rule 18.10).

## Примечания для биндинг-лейна

- REUSE_DEPLOYED-строки биндить на **deployed-evidence** (0b7a0aca для fs-строк; 31c16555/recap-25880 для UI; tick-observation-25883/incident-tail-25887 для prod-публикаций 17.10; review-ledger-p0-final.md + p0-save-init-ux для инициативы 18.10). SHA не выдумывать — все указатели существуют в репо.
- Не трогать PENDING U08.4d/U08.5.1/B12.6 и U07.1a (user_excluded/SUPERSEDED директивой 18.10 — уже оформлено legacy-биндингом).
- B10-R17: «прод-данные» в поверхностях — добровольное device-наблюдение владельца; engineering-кадры на дереве деплоя закрывают инженерную часть строки.

## Исполнение (LEDGER-ASAP8-RFL, 2026-10-21)

- **15/15 REUSE_DEPLOYED-строк → VERIFIED**; REAL_LIVE-группа (18) не тронута. Счётчики additional_requirements: 27 V / 33 RFL / 15 P → **42 V / 18 RFL / 15 P**; items (148) без изменений (130 V / 14 P / 4 RFL).
- Каждый статус ставлен только после открытия указанного evidence-источника: `tick-observation-25883.md` + `incident-tail-25887.md` (стилед-обложки 17.10 ×2, message_id 1163554/1164062, cron-skip disabled-чата, LEGACY_FALLBACK без слома), `plans/features/soul-1/review-ledger-p0-final.md` + `acceptance-bc-25890-read.json` (LIVE-FUNNEL 18.10: scan=280→6→4→2→**sent=2**), `release-fs-25884-report.md` (2.58.84 @0b7a0aca), `recap-25880/verify_summary.json` (48 кадров, all_hard_pass, IHDR==вьюпорт), `b01_b06_b07_suite.log` + `map-reconciliation-2026-10-16.md` §B01/B06 (13/13+17/17 на 31c16555, трассировка тест-функций 13+17+12=42), editor e2e `passed=40 failed=0` @31c16555, `w4-live-probes.md` §1 (CSP data:), help-sync 24/24 + F8 `582==REGISTRY` (cfg Wave A @3022e6e8).
- SHA-байндинг новых evidence-элементов (все реальные коммиты репо): `0b7a0aca…` (fs), `31c16555…` (recap/rebind), `448cc81a…` (прод-публикации 16–17.10, продюсер 2.58.83), `3b02366e…` (LIVE-FUNNEL, прод 2.58.90), `c2775a54…` (w4 live-пробы 2.58.79), `3022e6e8…` (cfg-артефакты). Map-level `candidate_commit`/`deployed_commit` (0b7a0aca) не менялись.
- Честные оговорки сохранены в reason: B01 — хвост 7d-мониторинга частоты (наблюдение, не блокер); B06 — второй прод-чат disabled (двухчатовое расхождение — контролируемая real-generation матрица); B04 — b04-сьют по форме (b) «implementation unchanged since c2775a54» (git diff c2775a54..31c16555 пуст, проверено); R17/R18/U07-HARD/V06 — real-client/device-часть в U07-OWNER-REALDEV (owner_optional).
- Отклонений от recon-таблицы: 0; PENDING-строки не переводились. Гейт: `requirements_gate.py check --map … --stage plan` → **EXIT 0** (inventory=148, manual=75, errors=0).

## Исполнение EXEC-TAILS (лейн ASAP8-EXEC-TAILS, 2026-10-21)

Прод-захват read-only (2.58.105 @a6246e33 сверен по SSH/healthz; репо-HEAD `bf17a972`): **5 REAL_LIVE-строк закрыты** — B10-R01, B10-R07, B10-R09, B10-R13, B10-R16 + **B12.6** (3 остатка: 2+1+2 теста в `tests/test_asap8_v63_b126_residuals.py` [5 passed + 1 strict-xfail], R09-тест `tests/test_asap8_v63_b10r09_settings_409_race.py`, замер `evidence/probe-exec/b126-side-effects-measure.json`). Полный отчёт: `evidence/probe-exec/probe-exec-2026-10-21.md`.

- **PROBE-SUMMARY**: R01 ✓ (два чистых L2: 17.10 `1164062` published + 19.10 paragraphs=10 fallback=none [публикация рана не состоялась — оговорка] + diff источников 489/335 overlap 0); R13 ✓ (real-data: vec 16005, foreign_leak=0, staged partial-honest, тайминги 0.8–2.1s, historical FTS +667 expired-only); R16 ✓ (20/23 ранов с датой; current/old_but_valid/unknown; date_source оба класса).
- **PROBE-UI**: R09 ✓ (поведенческий тест 409-гонки на реальном optimistic-протоколе chat_params; живая мутация конфига владельца не делалась — read-only дисциплина).
- **PROBE-MEMORY-MIG**: V03/REQ-B03-DOD — read-only-части закрыты пробой (scope/eligibility/тайминг на реальной БД), live-хвост «попал в relevant context» + confirm/refute-мутация → остаются RFL с суженным остатком; REQ-B09-BODY/B10-R10 — `chat_id_migrations` пуста (реального переноса не было) → WAITING_EXTERNAL.
- **PROBE-EXTERNALS**: R07 ✓ (реальный проход каскада на сконфигурированном провайдере: живой 407 от апстрим-прокси классифицирован proxy_auth_failed per контракту F9/Y1; success-путь заблокирован состоянием прокси — внешнее); R06/REQ-B11-E2E — квота эмбеддингов НЕ восстановлена (journal 21.10: EmbeddingGroupCoolingDown до 23:25 UTC, EMBED_API_DEFERRED ×357/7д, FTS-only A06) → WAITING_EXTERNAL; R11 — частичный речек (direct_fresh_generation 335/7д, интенты, rate_limit) → остаётся RFL.
- **Не тронуты (вне лейна / ждут боевого потока)**: PROBE-EXPERIENCE (REQ-B02-DOD, V02, B10-R12), B10-R14, B10-R15, B10-R19, PENDING U08.4d/U08.5.1 (ждут deployed-проверку после релиза), U07.1a.
- **⚠ Инцидент-находка замера B12.6**: backup-петля `migrate_chat_memory` не покрывает `chat_running_summary` (PK=chat_id=алиас rowid, отрицательные chat_id суперчатов; `rowid > -1` отсекает) — строка переносится без backup-записи. Данных в проде нет (миграций не было), контракт 0-DELETE/сохранность не нарушен, НО фикс `services/chat_migration.py` обязателен ДО реального переноса supergroup — отдельный лейн (services/ вне WRITE_SCOPE исполнявшего лейна). Документировано strict-xfail `test_backup_covers_running_summary_negative_pk`.
- Счётчики после EXEC-TAILS: additional_requirements **47 V / 13 RFL / 15 P**; items 133 V / 11 P / 4 RFL.
