# REV-REL-25893 — вердикт (релиз 2.58.93: CFG-02C — изоляция бюджетов изображений и обложек Summary)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.92 @ `1d367e4c`.

Кандидат: bump `74160a5d` (код CFG-02C `1d9a7107`; доки до `1e363143`).
Вход: отчёт `release-25893-report.md` (коммит `10fe95b2`), evidence
`evidence/release-25893/**`, `deploy_25893.py` (`ab71cc472dd7`),
`rel93_final.sh` (`9b10fa2875b4`), ветка `release/fix-2.58.92` @ `1d367e4c`.
Верификация — в изолированном worktree `wt` @ `74160a5d` + мои прогоны ниже.

## 1. Bump — подтверждён

31 файл, +33/−33, содержимое — только версионные строки `2.58.92 → 2.58.93`
(не-версионных изменений нет). `2.58.92` вне plans — **0**, включая
escaped-пины (`2\.58\.92` в JS-тестах — тоже 0; обновлены до `2\.58\.93`).
`APP_VERSION = "2.58.93"`, meta: APP_VERSION 2.58.93 + HEAD `1e363143`,
README: v2.58.93 + абзац CFG-02C.

## 2. Дельта `1d367e4c..74160a5d` — изоляция подтверждена

90 файлов = 46 plans + 44 non-plans (9 runtime + 33 tests + 1 tool + README).
Runtime (config/services/web/handlers) = **9** == вайтлист скрипта
(set-equality — мой прогон + `check_deploy_25893.py`). Содержимое всех 9 файлов
сверено с ожиданием CFG-02C:
- `image_generation.py`: явный `consumption_type`/`cover_stage` от call-site;
  cover-путь — `_cover_charge` (резерв ТОЛЬКО shared, типизированный ключ) →
  `_generate_image_verbose_inner` (бюджет списывается один раз) →
  `_cover_settle` (commit/release); честный `shared_budget` (+
  `image_shared_budget_note` c `WORKER_BUDGET_TZ`); replay `limit_global`
  остаётся shared-отказом; `_IMAGE_REASON_TO_CODE['shared_budget'] =
  financial_limit_reached`;
- `worker_budget.py`: `journal_consumption_type` (forward-only); `reserve_image`
  списывает shared-потолок ДО раннего возврата `chat_id is None or is_cover`
  (per-chat не инкрементируется, даже при 0); `release_image` для cover-строк
  НЕ откатывает per-chat (иначе «одолжил» бы квоту); `RESERVATION_DAY_SQL`
  исключает `summary_cover%`, новый `RESERVATION_COVER_DAY_SQL` +
  `_shared_cover_used` → `cover_used` (fail-open None); `image_usage_summary` —
  разбивка cover отдельно;
- `capability_registry.py`: `shared_budget → quota_exhausted` +
  `image_quota_state` отдаёт `image_shared_limit` (shared-контур первым);
- `summary_generator.py` / `cover_style_preview.py` / `web/api/summary_test.py`:
  все cover-вызовы типизированы (`CONSUMPTION_COVER`/`COVER_STAGE_BASE`);
- `web/app.js` / `web/index.html`: подпись «Пользовательские изображения …
  Обложки сводок здесь не учитываются» + разбивка «в том числе обложки
  сводок: N» (`data-image-quota-scope-label`/`-shared-breakdown`).
Sanity-трио (telegram_send / fullscreen-policy / prompt_composer) — байт-в-байт;
services-only дифф = 5 payload; строки 9 файлов +356/−23 (мой `--shortstat`
совпал). `mca_random_source`/`database`/`nostalgia_worker`/`initiative_*` —
байт-в-байт как в проде.

## 3. Числа — перепроверены (логи + мои прогоны)

- Полный pytest ×2 (параллельный и чистый): оба **10 failed / 14465 passed**
  (787.81s / 713.93s). 9 константных = asap7×2 + mca01×1 + t5150×5 +
  history_cli-worktree-артефакт (тот же набор, что 2.58.92; воспроизводился
  мной ранее в трёх точках).
- 10-е падение — environment-флейк random_source под SQLite-lock, в каждом
  прогоне РАЗНЫЙ тест: `nostalgia_worker::test_golden_candidate_sent`
  (параллельный) и `soul1_w5_initiative_vitality::
  test_check_dry_run_reaches_mock_send_without_publishing` (чистый). Оба
  зелёные в изоляции — **мои прогоны: 26 passed / 18 passed**. Механизм:
  `database is locked` → `connection unrecoverable | op=random_state` →
  fallback random-source → ассерт «отправлено». Независимость от дельты
  подтверждена (в services изменены только 5 payload; модули random/lock-цепочки
  байт-в-байт); прецедент — `plans/features/soul-1/w4-humor-feedback-report.md:302`.
- Мои прогоны (все exit 0): cfg02c **19**; бласты **135/308/286/263/176/90/22**;
  F8 **29**; реестр **579 == REGISTRY**; JS-sweep **88/0**; UI e2e
  `tools/ui_cfg02c_image_isolation_e2e.py` — **RESULT: PASS** (desktop+mobile,
  `console_errors=[]`, скриншоты повторно сняты и **байт-в-байт** совпали с
  committed — worktree остался чистым).

## 4. Деплой-скрипт (офлайн) — NF-фиксы сохранены

`check_deploy_25893.py` **EXIT 0** (мой прогон): вайтлист 9/9 == дельта,
BUMP == HEAD (worktree). **Все 14 хэшей EXPECT12** я независимо сверил из
git-объекта `74160a5d` — 14/14 OK (9 runtime + README + meta + 3 sanity).
Константы: `PROD_REF=1d367e4c`, `PROD_BRANCH=release/fix-2.58.92`,
`BUMP=74160a5d`, `ROLLBACK=release/cfg1-2.58.88`/2.58.88, `EXPECT_VER=2.58.93`,
`EXPECT_PAGE_VER=15`, `EXPECT_SUBST_CSS=2`. NF-фиксы 25891/25892 в коде:
`checked_out`-гейт tree-restore, set-equality (`sorted`) вайтлиста, tree-restore
→ прод-линия 2.58.92 (`release/fix-2.58.92`/detach, без downgrade),
WARNINGS-summary, SERVED_EQ, scrub секретов; гейты B3 ancestor (fail-closed до
push), D1-хэши → abort, пустой T0/healthz≠2.58.93 → `_rb`. `rel93_final.sh`:
CFG-02C-маркеры с ожиданиями — я сверил **все 15** построчно против кандидата
(совпали), регрессионные маркеры линий 2.58.92/2.58.91, `SCOPE_LABEL_SERVED`,
`/api/workers/budget`, `COVER_JOURNAL`/`SHARED_BUDGET_DENY`, SKIPS=0.

## 5. Док/чеклист — соответствуют

Состав: CFG-02C (двусторонняя изоляция бюджетов: явный тип от call-site,
shared-only для обложек, честный `shared_budget` с `WORKER_BUDGET_TZ`, витрина
user-only + разбивка; Δ DDL=0, Δ каталога=0) + доки + bump. Откат:
`release/fix-2.58.92` (abort до рестарта, без рестарта) → `fix-2.58.91` →
штатный `cfg1-2.58.88` (после рестарта). §Ф6 (a)–(f): healthz/журнал/SKIPS=0;
витрина live (CFG-02C.5); изоляция live **без траты бюджета** (1 обложка + 1
мем; потолок не добивать); shared-источник честен (unit
`TestSharedCeilingHonesty` + grep-маркеры); экономика/журнал; уборка тестовых
сообщений. Риски честные (пре-сущ./флейк; push-обязательность).

## Наблюдения (не блокирующие)

* B3 принимает tip, содержащий bump; чужие runtime-файлы в tip ловит C-стадия
  (вайтлист, fail-closed). Чужие non-runtime (tests/docs/tools) прошли бы молча,
  но на прод-рантайм не влияют — приемлемо.
* После сборки пакета master получил 4 plans-only docs-коммита (29 файлов) —
  runtime-дельта к проду по-прежнему 9, EXPECT12-файлы на HEAD совпадают с
  `74160a5d`, bump — ancestor HEAD (B3 пройдёт). Проверено.
* `tools/ui_cfg02c_image_isolation_e2e.py` и tests/ в non-plans дельте — не
  runtime, попадут на прод вместе с деревом, вреда нет.
* Флейк random_source — класс пре-существующий (SQLite-lock под нагрузкой),
  прод не затронут (тесты на проде не выполняются).

## Леджер/статус

Пакет **готов к контролируемому деплою**. Живые пункты §Ф6 — **READY_FOR_LIVE**:
(a) healthz 2.58.93/SKIPS=0; (b) витрина CFG-02C.5 на живом проде (агентски);
(c) изоляция live без траты бюджета; (d) shared-honest (без добивания потолка);
(e) экономика/журнал; (f) уборка. Выполняет DevOps/приёмка ПОСЛЕ выката;
родительский DONE — только после них. Предусловие: push `master` (B3
fail-closed); желательно push `release/fix-2.58.92` (иначе tree-restore —
detach на `1d367e4c`; объект на проде есть).

## Вердикт

**Approved** — релиз-пакет 2.58.93 (bump `74160a5d`, CFG-02C `1d9a7107`)
проверен: bump версионно-чистый, дельта изолирована (9/9), хэши 14/14,
числа 14465/10 с полной атрибуцией (9 константных + env-флейк, изоляции
зелёные), скрипт с NF-фиксами и fail-closed гейтами, чеклист/откат полны.
Деплой — за DevOps/Orchestrator; DONE — только после §Ф6-приёмки.
