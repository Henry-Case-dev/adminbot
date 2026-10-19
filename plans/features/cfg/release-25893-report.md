# Релиз **2.58.93** — CFG-02C: жёсткая изоляция бюджетов пользовательских изображений и обложек Summary

Дата сборки кандидата: 2026-10-19 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** (код-коммит CFG-02C `1d9a7107`; доки
`77e7dd5a`/`26ebc0a8`/`3492fc45`/`1e363143`) + bump `74160a5d`;
прод до релиза — **`2.58.92 @ 1d367e4c`**
(ветка рубежа `release/fix-2.58.92` создана локально на `1d367e4c`).
Статус: **собран и проверен локально**; деплой и приёмка — отдельный шаг (§4).
Задача: RELEASE-PKG-93 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от bump-коммита
(`OPENCODE_WORKFLOW_SCRATCH\release-25893\wt` @ `74160a5d`); главное дерево
для прогонов кандидата не использовалось.

## 1. Состав (что вошло)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| CFG-02C (код) | `1d9a7107` | Бюджеты пользовательских изображений и обложек Summary разведены **в обе стороны**: тип потребления едет явным параметром от call-site до журнала (`user_image` → `direct`/`tool`; обложки → `summary_cover:base`), обложки резервируют **только shared-потолок** (per-chat `image_calls` не инкрементируется — даже при нулевой квоте и включённом частотном лимите), `release_image` для cover-строк не откатывает per-chat счётчик, агрегаты витрины — только пользовательские (`RESERVATION_DAY_SQL` исключает `summary_cover%`), честный отказ `shared_budget` с собственным TZ (`WORKER_BUDGET_TZ`) и классом шаблона `quota_exhausted`, `cover_used` + разбивка «в том числе обложки сводок: N», UI-подпись «Пользовательские изображения … Обложки сводок здесь не учитываются» (app.js + index.html). Δ DDL = 0 (тип живёт в существующей колонке `image_reservation.source`), Δ каталога = 0. |
| Доки слайса | `77e7dd5a`, `26ebc0a8`, `3492fc45`, `1e363143` | Независимое ревью (Approved), леджер CFG-02C (13 строк слайса), scope-амендмент slice-graph (2 стаба), prep CFG-03. |
| Bump/F8 | `74160a5d` | `2.58.92 → 2.58.93`: settings + README (абзац CFG-02C) + F8-meta (APP_VERSION `2.58.93`, HEAD `1e363143`) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33, версионно-чистый; «2.58.92» вне `plans/` не осталось). |

Ревью: `77e7dd5a` — **Approved** (RED 16f/3p на `f7a14994` → GREEN 19;
бласт-наборы 135/308/286/263/176/22; JS-sweep 88/0; UI e2e PASS; Δ DDL = 0;
двусторонние негативы; `CFG-02C.5` → READY_FOR_LIVE postdeploy).
Леджер: `plans/features/cfg/requirements-map.json` (slice CFG-02C, 13 строк,
`strict_evidence`), evidence слайса — `plans/features/cfg/evidence/cfg-02c/**`.

## 2. Дельта к проду (изоляция)

База = прод `1d367e4c` (2.58.92). Полная дельта после bump-коммита
(включая `plans/**`) = **90 файлов**; без `plans/**` — **44**:

- **9 runtime-файлов** — ровно они и есть вайтлист деплой-скрипта (любой
  другой runtime-файл в дельте = abort; сверка равенства множеств офлайн:
  PASS) — **8 payload CFG-02C + bump-settings**:
  `config/settings.py` (bump-версия), `services/capability_registry.py`,
  `services/cover_style_preview.py`, `services/image_generation.py`,
  `services/summary_generator.py`, `services/worker_budget.py`,
  `web/api/summary_test.py`, `web/app.js`, `web/index.html`
  (runtime-stat: 9 файлов, **+356/−23** — `delta-runtime-stat.txt`);
- **33 файла `tests/`** = 28 bump-пинов (24 py + 4 JS) + 5 файлов CFG-02C
  (новый контрактный `test_cfg02c_image_isolation.py`; пин-стабы
  `test_asap7_cover_preview.py`, `test_extra_cover_style_runtime.py`;
  перенацеленные `test_hotfix5_summary_cover_window_round1025.py`,
  `test_image_daily_limit_round1026.py`);
- `tools/ui_cfg02c_image_isolation_e2e.py` (Playwright-e2e витрины);
- `README.md` + 30 bump-файлов (31-й — `plans/docs/param-registry-round1025.meta.md`:
  APP_VERSION `2.58.93`, HEAD-штамп `1e363143`);
- плюс `plans/**` (46 файлов: evidence/леджеры/ревью/доки — документация).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.92: `services/telegram_send.py`
`e23bced2fdb8`, `web/static/fullscreen-policy.js` `96db06425079`,
`services/prompt_composer.py` `fd8a2a70d5d7` — сверено (в дельте их нет).
Полный список файлов дельты без plans — `evidence/release-25893/delta-non-plans.txt`.

## 3. Проверки кандидата (run-as-is, в изолированном worktree от bump-коммита)

| Проверка | Результат |
|---|---|
| Полный `pytest -q` (чистый прогон, без конкурентной нагрузки) | **10 failed / 14465 passed** (713.93s); 9 — пре-сущ. baseline; 10-е — environment-флейк random_source под SQLite-lock (`test_soul1_w5_initiative_vitality::test_check_dry_run_reaches_mock_send_without_publishing`), в изоляции **18 passed** |
| Полный `pytest -q` (первый прогон, параллельно с фокусными) | **10 failed / 14465 passed** (787.81s); 10-е падение — флейк `test_nostalgia_worker::test_golden_candidate_sent` под нагрузкой (SQLite lock → unrecoverable connection), в изоляции **26 passed** |
| `tests/test_cfg02c_image_isolation.py` | **19 passed** (4.82s) |
| Бласт-набор A (19 + 116) | **135 passed** (9.64s) |
| Бласт-набор B (image/tool/direct/budget) | **308 passed** (20.92s) |
| Бласт-набор C (webapp/pg/budget/mca17c/decision) | **286 passed** (11.64s) |
| Бласт-набор D (cover-style/soul1-capability) | **263 passed** (6.60s) |
| Бласт-набор E (summary/cover/asap42–44) | **176 passed** (13.59s) |
| Бласт-набор F (runtime/deploy/instrumentation; blast-110, состав чуть уже — ср. review §5) | **90 passed** (10.47s) |
| Бласт-набор G (`test_summary_test_run`) | **22 passed** (3.19s) |
| F8-пара: `test_round1025_f8_registry.py` | **29 passed** (3.40s) |
| F8-пара: `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY** (R17-чисто, TSV/map идемпотентны) |
| JS-sweep: `node tests/js/*_test.js` (88 файлов) | **88 файлов / 0 падений** |
| `tools/ui_cfg02c_image_isolation_e2e.py` (desktop 1440 + mobile 390) | **RESULT: PASS** (console_errors=[], скриншоты байт-в-байт = committed — детерминизм) |
| Офлайн-сверка деплой-скрипта (hashes 14/14, вайтлист==дельта 9/9, BUMP==HEAD) | **EXIT 0** |

Артефакты: `pytest-full.txt` (чистый прогон) + `pytest-clean-command.txt`,
`pytest-full-parallel.txt` (параллельный прогон) + `pytest-parallel-command.txt`,
`pytest-attribution.txt`, `focused-blast.txt`, `focused-raw.txt`,
`nostalgia-iso.txt`, `soul1w5-iso.txt`, `js-sweep.txt`, `ui-e2e.txt`,
`gen-param-check.txt`, `deploy-offline-check.txt`.

**Атрибуция полного pytest (чистый прогон — `pytest-attribution.txt`):**
Ожидаемый baseline окружения — **9 pre-existing** (5×`t5150` SQLite lock-тайминги;
2×`asap7_direct_settings` — ожидания цепочки миграций отстали от схемы;
1×`mca01_tx_task_supervisor` — write-точки `database.py` 201 vs allow-map 198;
1×`test_history_cli::test_scope_is_required` — environment-артефакт чистого
worktree без untracked `migrate_history/`, воспроизведён в 2.58.92 и на
прод-базе). Это ровно набор релиза 2.58.92 (14447/9) + 19 новых тестов CFG-02C
(ожидание 14466/9).

**10-е падение — environment-флейк random_source под SQLite-lock, в каждом
прогоне РАЗНЫЙ тест, оба зелёные в изоляции:** прогон 1 — `test_nostalgia_worker::
test_golden_candidate_sent` (изоляция: `tests/test_nostalgia_worker.py` **26 passed**,
`nostalgia-iso.txt`); прогон 2 — `test_soul1_w5_initiative_vitality::
test_check_dry_run_reaches_mock_send_without_publishing` (изоляция:
**18 passed**, `soul1w5-iso.txt`). Общий механизм: `database is locked` →
`connection unrecoverable | op=random_state` → `ValueError: no active connection`
в `services/mca_random_source.py` (`reserve read failed`/`write_state failed`) →
random-source fallback → ассерт «отправлено/attempted». **Независимость от
дельты:** `git diff 1d367e4c..74160a5d -- services` = только 5 payload-файлов
CFG-02C; `mca_random_source.py`, `database.py`, `nostalgia_worker.py`,
`initiative_diagnostics.py`, `initiative_observer.py` — байт-в-байт как в проде
2.58.92. Прецедент известного флейка `test_golden_candidate_sent` —
`plans/features/soul-1/w4-humor-feedback-report.md:302` (3867/2 → повтор 3869/0,
изоляция 26 passed). **Новых падений от CFG-02C нет.**

## 4. Чек-лист пост-деплойной приёмки (§Ф6)

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.
Все проверки — read-only или контролируемые, **без добивания shared-потолка и
без лишних платных вызовов**.

**(a) healthz+версия+T0+журнал.** `healthz` = `2.58.93` (loopback и HTTPS),
`NRestarts=0`, MainPID сменился; журнал since T0: `ERR/CRIT/Traceback=0`,
RuntimeWarning/«never awaited» = 0, `database is locked` = 0; миграции
`complete`, `user_version` без изменений (Δ DDL=0), `INDEX_LOCK=absent`.
**SKIPS=0** (линия 2.58.92): строки «maximum number of running instances» = 0;
`claim sweep slow`/`maintenance stage timeout` — допустимы (не пропуски).
Источник: `deploy_25893.py` (F3/F4/J) + `rel93_final.sh`.

**(b) Витрина CFG-02C (§02C.5, live — агентски).** В MiniApp секция «Лимиты
генерации» модуля изображений явно обозначает **«Пользовательские
изображения»** и поясняет **«Обложки сводок здесь не учитываются»**; при
ненулевом cover-расходе видна строка разбивки **«в том числе обложки сводок: N»**
(общий технический бюджет — не пользовательский счётчик). Прод-контроль:
served `/web/` содержит `data-image-quota-scope-label` (`rel93_final.sh` →
`SCOPE_LABEL_SERVED=1`), `CFG02C_UI_LABEL_HTML/JS=1`; визуальный rendered-просмотр
— агентом (Playwright/Browser Use по прод-URL страницы модуля изображений).
Это закрывает `CFG-02C.5` (live_required, postdeploy).

**(c) Изоляция live (без траты бюджета).** В чате с `limits.image_daily_limit = 0`
и включённым частотным лимитом (CFG-02B, ON): заказать Summary с Base-обложкой →
обложка генерируется, пользовательские счётчики не двигаются: `GET /api/workers/budget`
(user `used`/`remaining`) не изменился; в журнале — строка
`image_reservation.source='summary_cover:base'` с `chat_used=0`. Пользовательский
путь («бот, нарисуй мем») не создаёт `summary_cover`-строк и не двигает
`cover_used`/разбивку. Достаточно 1 обложки + 1 мема; сверка — read-only
(`/api/workers/budget` + журнальные агрегаты). Unit-доказательства:
`test_base_cover_works_when_user_daily_zero_and_freq_on`,
`test_cover_journal_is_typed_shared_only`,
`test_direct_and_tool_memes_do_not_touch_cover_contour`.

**(d) shared-источник честен.** Отказ по общему техническому бюджету называет
именно его (строка «Технический бюджет генераций (общий для всех чатов)…
обновится {stamp} ({WORKER_BUDGET_TZ})»), а не пользовательскую квоту;
**без реального добивания до потолка**: доказательства — unit-набор
`TestSharedCeilingHonesty` (`test_user_denial_names_technical_budget_and_shared_tz`,
`test_cover_denial_names_technical_source`) + grep-маркеры на проде
`CFG02C_SHARED_REASON`/`CFG02C_QUOTA_CLASS` (`rel93_final.sh`). Реальное
исчерпание потолка НЕ выполнять.

**(e) экономика/журнал.** Списания/квоты по логу не превышены; события
`IMAGE_*`/`COVER_*`/`TOOL_CALL` в норме; `ERR/CRIT/402 = 0`; дедуп ответов не
сломан; `COVER_JOURNAL`/`SHARED_BUDGET_DENY` (`rel93_final.sh`) — ожидаемо 0
при отсутствии соответствующих событий; `GET /api/workers/budget` отдаёт
`cover_used`-разбивку без утечки секретов.

**(f) уборка тестовых сообщений.** Все тестовые сообщения приёмки удалить/очистить
в чатах после прогонов (правило владельца; прецедент — `accept91_cleanfinal.py`).

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.92` (`1d367e4c`, 2.58.92) — пред-релизная линия прода;
  создана локально под этот релиз (deploy: tree-restore при abort ДО рестарта).
- `release/fix-2.58.91` (`f2a6248a`, 2.58.91) — предыдущий рубеж.
- `release/cfg1-2.58.88` (`c37b8577`, 2.58.88; tip ветки `35789982` = bump +
  docs-коммит, runtime идентичен) — **штатный рубеж авто-отката деплой-скрипта**
  (путь ПОСЛЕ рестарта при неполучении healthz 2.58.93 / пустом T0).
Abort ДО рестарта (whitelist/дельта/хеши) отката не ждёт: `_tree_restore`
возвращает дерево к прод-линии 2.58.92 (`release/fix-2.58.92` / точный
`PROD_REF` detach, без рестарта) — downgrade исключён.
Мягких kill-switch'ей этот релиз не вводит (CFG-02C — код-фикс без флагов):
«мягкая дверь» — возврат кода на ветку-рубеж (cold); прежние
per-chat/env-переключатели (CFG-02B, Vision, Direct) не меняются.

## 6. Риски/остатки (честно)

1. **`test_history_cli::TestCliFts::test_scope_is_required`** — environment-артефакт
   чистого worktree (нет untracked-каталога `migrate_history/`), воспроизведён
   в релизе 2.58.92 и на чистой базе; в главном дереве его нет. Не регрессия.
2. **Пре-сущ. падения (8)**: `asap7_direct_settings` ×2 (`assert 36 == 35` —
   ожидания цепочки миграций отстали от схемы), `mca01_tx_task_supervisor` ×1
   (write-точки `database.py` 201 vs allow-map 198), `t5150` ×5 (SQLite
   lock-тайминги). Файлы дельтой не тронуты; воспроизводились на чистом HEAD.
3. **`test_nostalgia_worker::test_golden_candidate_sent`** — известный флейк под
   нагрузкой (SQLite lock → `connection unrecoverable` → `reserve read failed`);
   в параллельном прогоне дал 10-е падение, изолированно **26 passed**
   (`nostalgia-iso.txt`); прецедент — `plans/features/soul-1/w4-humor-feedback-report.md:302`.
4. **`CFG-02C.5` (live_required, postdeploy)** — закрывается приёмкой §4(b) на
   живом проде (витрина); локально доказана детерминированным e2e + rendered-просмотром.
5. **mca09-флейк** (~5–6%, `test_handle_initiative_sent_single_transport_chunks`) —
   известный; в этих прогонах не сработал.
6. **Потолок shared** на проде не добивать в приёмке (экономия; §4d).

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\
  release-25893\deploy_25893.py` — sha256_12 **`ab71cc472dd7`** (T0-hardened clone
  `deploy_25892.py`/`10322d72a735`; NF-фиксы сохранены: checked_out-гейт
  tree-restore, set-equality вайтлиста, tree-restore к прод-линии 2.58.92,
  WARNINGS-summary, SERVED_EQ): A pre-state → B fetch origin/master
  (BUMP-ancestor gate) → C checkout + runtime-whitelist дельты (9 файлов)
  → D sha256_12 (14 артефактов: 9 runtime + README + meta + 3 sanity) +
  маркеры CFG-02C и регрессионные линии 2.58.92/2.58.91 → F restart + T0 +
  healthz 2.58.93 + журнал → G served-bytes (+`SCOPE_LABEL_SERVED`) →
  J `rel93_final.sh`.
- `rel93_final.sh` — sha256_12 **`9b10fa2875b4`** (read-only; + SKIPS-контроль,
  CFG-02C-маркеры с ожиданиями, `/api/workers/budget`, журнальные
  `COVER_JOURNAL`/`SHARED_BUDGET_DENY`, SERVED_EQ, PAGE_VER/SUBST_CSS).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25893.py`
  (sha12 `6dc01284f2a6`) **EXIT 0** (hashes 14/14, вайтлист == дельта 9/9,
  BUMP == HEAD, uploads на месте) — `deploy-offline-check.txt`.
- Авто-откат ПОСЛЕ рестарта: `release/cfg1-2.58.88`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.92 (`release/fix-2.58.92`/`1d367e4c`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.93
  (B3 fail-closed, иначе прод не трогается). Ветку `release/fix-2.58.92` при
  выкате желательно запушить (иначе tree-restore идёт fallback-detach'ем на
  `1d367e4c` — объект уже есть на проде).

## 8. Кандидат-фингерпринт

- tip master / bump-коммит: `74160a5d` (2.58.93) — дерево кандидата заморожено им.
- **После сборки пакета** master получил 3 plans-only docs-коммита
  (`3e959493`, `41c898e5`, `7cdf47b2`; 11 файлов, все под `plans/`) — runtime не
  изменился: дельта `1d367e4c..HEAD` по `config/services/web/handlers` = те же
  **9 файлов**; 14/14 артефактов `EXPECT12` на текущем HEAD совпадают с
  `frozen-fingerprint.txt`; `74160a5d` — ancestor HEAD (B3-гейт пройдёт).
- Последний код-коммит: `1d9a7107` (CFG-02C); доки до `1e363143`.
- Прод-базис: `1d367e4c` (2.58.92); ветка откатного рубежа `release/fix-2.58.92`.
- sha256_12 14 артефактов — в `deploy_25893.py::EXPECT12` и
  `evidence/release-25893/frozen-fingerprint.txt` (+ полные sha256 там же).
