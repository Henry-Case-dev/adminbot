# Релиз **2.58.92** — P0V FIX2 + ADD-TR FIX2 (два фикса живой приёмки 2.58.91)

Дата сборки кандидата: 2026-10-19 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** (код-тип `f7a14994` = V-FIX2; TR-FIX2 = `9d310996`) +
bump `2c28e2a1`; прод до релиза — **`2.58.91 @ f2a6248a`**
(ветка `release/fix-2.58.91` создана локально на `f2a6248a`).
Статус: **собран и проверен локально**; деплой и приёмка — отдельный шаг (§4).
Задача: RELEASE-PKG-92 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от bump-коммита
(`OPENCODE_WORKFLOW_SCRATCH\release-25892\wt` @ `2c28e2a1`); главное дерево
параллельно правится другим лейном (CFG-02C) и для проверок не использовалось.

## 1. Состав (что вошло — ровно два фикса)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| TR-FIX2 (ADD-TR) | `9d310996` | Прямой чат, reply-путь: (1) цель медиа-инструментов разрешается приоритетом reply — своё медиа → текущее сообщение, иначе медиа replied-сообщения (`media_target_message_id`; тот же приоритет, что у канонических маркеров `_render_current_question`): текст-вопрос в reply на фото распознаёт **фото из reply**, а не текущее сообщение; (2) референтный вопрос «бот, это правда?» / «проверь его слова» / «не врёт?» берёт claim из replied-сообщения (`temporal_factcheck.is_referential_claim`; bounded 300/80 симв.), envelope-цель — из того же replied-сообщения; собственный claim («правда ли, что …») НЕ подменяется; единый пайплайн `fact_check` (дет. деривация + LLM-роутер), без второго пути. |
| V-FIX2 (P0V) | `f7a14994` | Воркер распознавания: (1) вход тика мгновенный (не ждёт БД-фаз) — два независимых single-flight sweep'а (claim: `active()` + CAS-claim + спавн + backfill ниже live; maintenance: `recover_stale` → `_expire_deferred`, каденс `VISION_MAINTENANCE_SECONDS=30`; каждая фаза bounded `wait_for` 30 c) — серии «skipped: maximum number of running instances» уходят; (2) 429 провайдера — временная причина: повтор в окне `RATE_LIMIT_RETRY_WINDOW_SECONDS=3600` сверх бюджета с backoff ≤900 c + jitter, за окном — терминал; (3) повтор той же гранулы анализа больше не падает на UNIQUE (`_next_granule_revision` = max+1); backfill re-arm через `BACKFILL_REARM_COOLDOWN_SECONDS=900` (только transient-причины); (4) per-chat state: общий хелпер `_vision_chat_scope` для GET `/api/vision/state` И POST `/api/vision/test` (`chat_id`/`X-Chat-Id` → `can_access_chat`; чужой чат → глобальный слой без утечки) — проба «Проверить подключение» больше не отдаёт контекст-независимое глобальное состояние (NF-1 ревью, закрыт). |
| Bump/F8 | `2c28e2a1` | `2.58.91 → 2.58.92`: settings + README + F8-meta (APP_VERSION `2.58.92`, HEAD `f7a14994`) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33). |

Ревью: TR-FIX2 — `6e2da038` (Approved: RED 8/8 → GREEN 8/8, sweep 4056/5 == база,
L1 cold-start backlog ок); V-FIX2 — `b33c0c47` (Approved после recheck: NF-1 закрыт,
bindings routes `d54cc29695c7` / tests `458d31d3d4fb`, mca_vision `f8cb004c6c84`;
RED-NF1 изолированно воспроизведён; sweep 373/0; UI e2e 7/7).
Леджеры: `plans/features/add-tr/**` (tr-fix2), `plans/features/p0-vision-universal/**` (fix2).

## 2. Дельта к проду (изоляция)

База = прод `f2a6248a` (2.58.91). После bump-коммита `2c28e2a1` полная дельта
(включая `plans/**`) = **88 файлов**; без `plans/**` — **39**:
- **7 runtime-файлов** — ровно они и есть вайтлист деплой-скрипта (любой другой
  runtime-файл в дельте = abort; сверка равенства множеств офлайн: PASS):
  `config/settings.py` (bump-версия), `services/direct_chat_service.py`,
  `services/direct_execution.py`, `services/mca_vision.py`,
  `services/temporal_factcheck.py`, `services/tool_router.py`,
  `web/api/routes.py` (список — `evidence/release-25892/frozen-fingerprint.txt`
  и `deploy_25892.py::RUNTIME_WHITELIST`);
- 31 файл `tests/` (включая новые контрактные `test_tr_fix2_reply_ref.py` и
  FIX2-блок `test_p0_vision_fix_core.py` + re-pins F8/routes-хешей);
- `README.md` + 30 файлов bump (из 31): `config/settings.py`, `README.md`,
  24 py-пина, 4 JS-пина; 31-й — `plans/docs/param-registry-round1025.meta.md`
  (APP_VERSION `2.58.92`, HEAD-штамп `f7a14994`);
- плюс `plans/**` (49 файлов: evidence/леджеры/ревью — документация).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.91: `services/telegram_send.py`
`e23bced2fdb8`, `web/static/fullscreen-policy.js` `96db06425079`,
`services/prompt_composer.py` `fd8a2a70d5d7` — сверено (в дельте их нет).
Runtime-дельта в строках: 7 файлов, +417/−36 (`delta-runtime-stat.txt`).
Полный список файлов дельты без plans — `evidence/release-25892/delta-non-plans.txt`.

## 3. Проверки кандидата (run-as-is, в изолированном worktree от bump-коммита)

| Проверка | Результат |
|---|---|
| Полный `pytest -q` (.venv) | **14447 passed / 9 failed** (723.06s; +15 passed к базе 2.58.91 — ровно новые тесты FIX2; атрибуция всех 9 — ниже) |
| `tests/test_tr_fix2_reply_ref.py` | **8 passed** (4.70s) |
| `tests/test_p0_vision_fix_core.py` (vision-core) | **54 passed** (13.44s) |
| `-k "fix2 or per_chat_context"` | **7 passed, 47 deselected** (10.12s) |
| `tests/test_p0_vision_ui_e2e.py` (UI e2e) | **7 passed** (72.37s) |
| `tests/ui_p0a_ux_speech_compact_e2e.py` (speech/UX e2e) | **failures=0, POST=21** (webroot = worktree кандидата) |
| js-sweep: `node tests/js/*_test.js` (88 файлов) | **88 файлов / 0 падений** |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY** (R17-чисто, TSV/map идемпотентны) |
| Офлайн-сверка деплой-скрипта (hashes 12/12, вайтлист==дельта 7/7, BUMP==HEAD) | **EXIT 0** |

Артефакты: `pytest-full.txt`, `focused-pytest.txt` (+ `focused-tr-fix2.txt`,
`focused-vision-core.txt`, `focused-fix2-k.txt`, `ui-e2e-vision.txt`,
`ux-e2e-console.txt`, `ux-e2e.json`, `js-sweep.txt`, `gen-param-check.txt`,
`deploy-offline-check.txt`).

**Атрибуция полного pytest (9 падений; полный текст — `pytest-attribution.txt`):**
- **8 — те же пре-существующие**, что в базовых прогонах 2.58.90/2.58.91:
  `asap7_direct_settings` ×2 (`assert 36 == 35` — ожидания цепочки миграций
  отстали от схемы), `mca01_tx_task_supervisor` ×1 (write-точки `database.py`
  201 vs allow-map 198 — задокументировано в fix-core design-note §4),
  `t5150` ×5 (`assert 36 == 35` / `pending=[33, 34, 35]`). Файлы дельтой не тронуты.
- **9-е — `test_history_cli::TestCliFts::test_scope_is_required`: environment-артефакт
  чистого checkout, НЕ регрессия.** Тест запускает `manage.py import_history --mode fts`
  без охвата и ждёт «выберите охват…», но `manage.py` сначала проверяет untracked-каталог
  `migrate_history/` (git-ignored локальные данные, есть только в главном дереве);
  в чистом worktree его нет → CLI выходит с другим сообщением. Доказано (raw —
  `history-cli-attr.txt`): [1] worktree кандидата — «папка migrate_history не найдена…»
  (rc=1) → assert падает; [2] главное дерево (тот же код `2c28e2a1`) — «выберите охват: …»
  → тест зелёный; [3] чистая прод-база `f2a6248a` в отдельном worktree — тот же FAILED
  идентично (1 failed in 3.18s). `manage.py`/history-CLI дельтой не тронуты.
- clock-window тест `asap5_paradigms_diagnostics::test_bootstrap_cooldown_bypass_then_cap`
  в этом прогоне **зелёный**: Asia/Yekaterinburg 03:44 — вне окна 00:00–03:00, при котором
  прогон 25891 падал (механика ранее доказана контролем `WORKER_BUDGET_TZ=UTC`).
  mca09-флейк (~5–6%) не сработал. **Новых падений дельты нет.**

## 4. Чек-лист пост-деплойной приёмки (ACCEPTANCE-92)

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.

**(a) healthz+версия.** `healthz` = `2.58.92` (loopback и HTTPS), `NRestarts=0`,
`MAINPID` сменился, журнал since T0: `ERR=0` (и RuntimeWarning/«never awaited» = 0),
миграции `complete`, `user_version` без изменений (Δ DDL=0), `INDEX_LOCK=absent`.

**(b) SKIPS=0.** Окно наблюдения ≥10 минут после T0: в журнале **ноль** строк
`skipped: maximum number of running instances reached` (было 36 в приёмке 2.58.91);
`[vision] claim sweep slow` — допустимо (медленная фаза, не пропуск);
`maintenance stage timeout` — допустимо единично, не пропуск; при этом очередь
vision доезжает до `ready` (живые джобы обрабатываются).
(`rel92_final.sh` уже печатает SKIPS/CLAIM_SLOW/MAINT_TIMEOUT.)

**(c) per-chat state — ВКЛЮЧАЯ кнопку пробы.** Сценарий приёмки 2.58.91 (глобально
`flags.vision_enabled=false`, per-chat override `true`):
GET `/api/vision/state` с `X-Chat-Id` этого чата → `state.requested=true` и
честная линия чата; POST `/api/vision/test` с тем же `X-Chat-Id` → `state.requested=true`
(НЕ `vision_disabled`) — **и до, и после пробы** UI не откатывается к глобальному
«Распознавание изображений выключено»; без заголовка — глобальный слой; чужой чат →
глобальный слой (без утечки); секрет в ответе не раскрыт (только маска).

**(d) reply-на-фото.** В чате: сообщение с фото → reply-сообщение с текстом-вопросом
(«бот, что тут?») → `recognize_image` с target = **message_id фото из reply**
(не текущего сообщения-вопроса); ответ описывает именно то фото; при неготовности —
человеческая причина, без выдуманного описания.

**(e) «это правда?» в reply.** Reply на сообщение с утверждением + «бот, это правда?»
→ `fact_check`: claim = текст **replied-сообщения** (исход claim=replied), envelope-цель —
replied-сообщение → `ready`/честный вердикт (или честный отказ по флагу); собственный
claim вопроса («правда ли, что …») не подменяется; второго параллельного пути нет.

**(f) живая Vision-проба.** POST `/api/vision/test` (кнопка «Проверить подключение») —
при HTTP 429 провайдера зафиксировать честно (лимит провайдера — временная причина):
повтор в часовом окне с backoff → `ready`; 429 не кешируется как приговор; при
устойчивом 429 — предложить владельцу смену модели (не блокер кода; честная запись).

**(g) уборка тестовых сообщений.** Все тестовые сообщения приёмки удалить/очистить
в чатах после прогонов (правило владельца; прецедент — `accept91_cleanfinal.py`).

**(h) экономика/журнал.** Списания/квоты по логу не превышены (события
`TOOL_CALL`/`POSTGEN_*`/`VISION_*`), `ERR/CRIT/402 = 0`, дедуп ответов не сломан;
чекап-вызовы в пределах per-turn границ.

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.91` (`f2a6248a`, 2.58.91) — пред-релизная линия прода;
  создана локально под этот релиз (deploy: tree-restore при abort ДО рестарта).
- `release/fix-2.58.90` (`3b02366e`, 2.58.90) — предыдущий рубеж.
- `release/cfg1-2.58.88` (`c37b8577`, 2.58.88; tip ветки `35789982` = bump +
  docs-коммит, runtime идентичен) — **штатный рубеж авто-отката деплой-скрипта**
  (путь ПОСЛЕ рестарта при неполучении healthz 2.58.92 / пустом T0).
Abort ДО рестарта (whitelist/дельта/хеши) отката не ждёт: `_tree_restore`
возвращает дерево к прод-линии 2.58.91 (`release/fix-2.58.91` / точный
`PROD_REF` detach, без рестарта) — downgrade исключён.
Мягких kill-switch'ей этот релиз не вводит (чистые код-фиксы): «мягкая дверь» —
возврат кода на ветку-рубеж (cold); per-chat/per-feature env-переключатели
Vision/ADD-TR прежние.

## 6. Риски/остатки (честно)

1. **429 у провайдера Vision** может сохраниться — это лимит провайдера, не дефект
   кода; окно ретрая/bounded-backoff теперь корректно, но при устойчивом 429 нужна
   смена модели (предложение владельцу; приёмка (f) фиксирует честно).
2. **Пре-сущ. падения** полного pytest — 8 + environment-артефакт `history_cli`
   чистого worktree (атрибуция §3, воспроизведён на прод-базе); в главном дереве
   (с untracked `migrate_history/`) ожидаемо 8 failed. Новых падений нет.
3. **mca09-флейк** (~5–6%, `test_handle_initiative_sent_single_transport_chunks`) —
   известный, может сработать.
4. **d11 hot-cache pollution** (`test_env_off_beats_product_toggle` в совместном
   прогоне 17 файлов) — воспроизведено на чистой базе ⇒ пред-существующее, не FIX2.
5. **Оговорка приёмки 2.58.91**: LOCKED=5 частично объяснялись вторым писателем
   harness'а; повторная приёмка — чистый прогон (§4b).
6. **WebView-натив** (Android/Telegram WebView) — postdeploy RFL-проверка агентом
   (устройство-чек-листы владельца отменены, PET_PROJECT §5).

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\
  release-25892\deploy_25892.py` — sha256_12 **`10322d72a735`** (T0-hardened clone
  `deploy_25891.py`/`caeebf41f201`; NF-фиксы сохранены: checked_out-гейт
  tree-restore, set-equality вайтлиста, tree-restore к прод-линии 2.58.91,
  WARNINGS-summary, SERVED_EQ): A pre-state → B fetch origin/master
  (BUMP-ancestor gate) → C checkout + runtime-whitelist дельты (7 файлов)
  → D sha256_12 (12 артефактов) + маркеры FIX2/регрессионные → F restart + T0 +
  healthz 2.58.92 + журнал → G served-bytes → J `rel92_final.sh`.
- `rel92_final.sh` — sha256_12 **`bd4d91c2c7c2`** (read-only; + SKIPS-контроль:
  «maximum number of running instances» = 0, claim-slow/maintenance-timeout).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25892.py` EXIT 0
  (hashes 12/12, вайтлист == дельта 7/7, BUMP == HEAD).
- Авто-откат ПОСЛЕ рестарта: `release/cfg1-2.58.88`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.91 (`release/fix-2.58.91`/`f2a6248a`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.92
  (B3 fail-closed, иначе прод не трогается). Ветку `release/fix-2.58.91` при
  выкате желательно запушить (иначе tree-restore идёт fallback-detach'ем на
  `f2a6248a` — объект уже есть на проде).

## 8. Кандидат-фингерпринт

- tip master / bump-коммит: `2c28e2a1` (2.58.92) — дерево кандидата заморожено им.
- Последний код-коммит: `f7a14994` (V-FIX2); TR-FIX2 — `9d310996`.
- Прод-базис: `f2a6248a` (2.58.91); ветка откатного рубежа `release/fix-2.58.91`.
- sha256_12 12 артефактов — в `deploy_25892.py::EXPECT12` и
  `evidence/release-25892/frozen-fingerprint.txt` (+ полные sha256 — `hashes-25892.txt`).
