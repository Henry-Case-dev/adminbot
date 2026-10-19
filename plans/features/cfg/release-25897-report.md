# Релиз **2.58.97** — CFG-04 (мобильные формы MiniApp) + ADD-EXP F1 (частотные якори мата)

Дата сборки кандидата: 2026-10-19/20 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** — код-коммиты ADD-EXP F1 `5b86517e` (ревью
`188f7414` Approved) и CFG-04 `2428768` (ревью `e27216d3` Approved), доки
`c48fe4cf` (CFG-05 prep) и сопутствующие docs-коммиты (acceptance-96/ledger —
не runtime), bump `fcd73a38` (2.58.97) + **fix `8b437c39`** (help-sync-гард под
новые подписи CFG-04 — см. §3/§6, runtime не тронут). Прод до релиза —
**`2.58.96 @ 95d11472`**.
Статус: **собран и проверен локально**; деплой и приёмка — отдельные шаги (§4).
Задача: LANE RELEASE-PKG-97 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от кандидата
(`OPENCODE_WORKFLOW_SCRATCH\release-25897\wt` @ `8b437c39`); главное дерево
для прогонов кандидата не использовалось. Незакоммиченные чужие правки
(`plans/workflow_state.md`, `plans/progress_scope.json`, asap8-доки, WIP других
лейнов) **не вошли ни в один коммит** этого поезда (commit строго `--only`;
набор bump = набор прошлого поезда, 31 файл).

## 1. Состав (что вошло)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| CFG-04 (мобильные формы) | `2428768` | Один предсказуемый сценарий сохранения: два Save сведены к **одному CTA** (`<sticky-save>`), а чип шапки стал честным **индикатором** (`role="status"`, без клика, со счётчиком «не сохранено»); **safe-area учтена ровно один раз** (`max(env, --tg-safe, --tg-content-safe)`), панель **поднимается над клавиатурой** (`--kb-offset` от visualViewport + фактическая высота панели `--sticky-save-h` через ResizeObserver), **последнее поле** доступно (scroll-padding/scroll-margin = панель + kb + 4px), toggle/кнопки **44×44**, **tech-key** раскрывается/копируется (`aria-expanded`, Clipboard API + фолбэк), **поворот экрана сохраняет** скролл/активный ключ/dirty/hash (модалка модуля — scrollTop после поворота уходит к фокусу — note N1, не блокер). Rows 20; D.4 (реальное устройство) — `PENDING_OWNER_E2E` (PET, optional). |
| ADD-EXP F1 (инструкции) | `5b86517e` | Частотные требования мата стали **исполнимыми якорями**: `occasional` — «примерно в одной из 4–5 разговорных реплик», `frequent` — «одно обсценное слово уместно в большинстве таких ответов» + частица («бля», «хули») в коротком ответе; header слоя больше **не делегирует уместность L1** («Контекст определяет уместность и жанр»). Канон/дизайн/тесты синхронизированы; ревью `188f7414` Approved (RED 5f/26p → GREEN 33 + focused 878/0). |
| Bump/F8 | `fcd73a38` | `2.58.96 → 2.58.97`: settings + README + F8-meta (APP_VERSION `2.58.97`, HEAD-штамп `2428768`) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33, версионно-чистый — `bump-verify.txt`). |
| Fix help-sync-гарда (найден полным прогоном #1) | `8b437c39` | `tests/test_asap8_v6_d14_help_sync.py` — гард «help matches shipped runtime» пинил старые подписи чипа (`dirty: 'Сохранить'` / `saving: 'Сохранение…'`), а CFG-04 осознанно заменил их на `'не сохранено'`/`'сохранение…'` (review `e27216d3`: чип — индикатор, не кнопка) → детерминированный красный тест, внесённый дельтой. Фикс приводит ожидания к отгруженному runtime (цель теста сохранена; runtime-артефакты ревью не тронуты). База `95d11472` зелёная (24p), кандидат до фикса 1f/23p, после — 24p. Test-only. |

## 2. Дельта к проду (изоляция)

База = прод `95d11472` (2.58.96). Полная дельта кандидата `8b437c39`
(включая `plans/**`) = **235 файлов**; без `plans/**` — **42**
(`delta-non-plans.txt`):

- **5 runtime-файлов** — ровно они и есть вайтлист деплой-скрипта (любой
  другой runtime-файл в дельте = abort; сверка равенства множеств офлайн:
  PASS, `deploy-offline-check.txt`):
  `web/app.js`, `web/index.html`, `web/static/app.css` (**CFG-04**),
  `services/mca_expression.py` (**ADD-EXP F1**), `config/settings.py` (bump) —
  runtime-stat в `delta-runtime-stat.txt`;
- **36 файлов `tests/`+`tools/`**: CFG-04 (`test_cfg04_forms_contract.py` (29),
  `tests/js/cfg04_forms_contract_test.js`, `ui_cfg04_forms_e2e.py` + пере-пины
  3 файлов) + ADD-EXP F1 (`test_add_exp_expression.py` (33)) + fix-файл
  `test_asap8_v6_d14_help_sync.py` + 24 py-пина + 4 JS-пина (bump);
- `README.md` — bump-файл;
- плюс `plans/**` (193 файла: evidence CFG-04/ADD-EXP-F1/acceptance-96, prep
  CFG-05, requirements-map/ledger, review-доки, F8-meta).

ΔDDL = **0**: `services/database.py`, migrations-модули и `scripts/` в дельту
не входят (`ddl-check.txt`); `user_version` на проде остаётся **36**.
Δ каталога = **0** (REGISTRY 579; `--check` OK).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.96:
`web/static/fullscreen-policy.js` `96db06425079`,
`services/telegram_send.py` `e23bced2fdb8` — сверено (в дельте их нет,
побайтовое равенство подтверждено, `frozen-fingerprint.txt`).

## 3. Проверки кандидата (run-as-is, в изолированном worktree от кандидата)

| Проверка | Результат |
|---|---|
| Полный `pytest -q`, **run #1** (кандидат `fcd73a38`, до fix) | **11 failed, 14581 passed, 39 skipped, 1 warning in 718.93s (0:11:58)** — на 2 больше пре-сущ.: help-sync (детерминированный дефект дельты) + mca09 initiative (env-флейк, см. ниже) |
| Полный `pytest -q`, **run #2** (кандидат `8b437c39`, после fix) | **9 failed, 14583 passed, 39 skipped, 1 warning in 667.18s (0:11:07)** (667.18s; start 2026-10-19T18:14:56Z → end 2026-10-19T18:26:08Z UTC) |
| Множество падений run #2 vs прогон 2.58.96 | точное совпадение множества (`pytest-attribution.txt`) |
| Help-sync гард: база → кандидат(RED) → фикс(GREEN) | **24p → 1f/23p → 24p** (`focused-help-sync-fix.txt`, `focused-help-sync-red.txt`) |
| Env-флейк `mca09…single_transport_chunks`: изоляция на кандидате/базе | **15/15 passed** в обоих worktree (`flake-mca09.txt`) — тайминг-флейк полного прогона, не дельта |
| Прямое доказательство пре-сущ. на базе `95d11472` (worktree `wt-base`, 4 файла падений) | **9 failed, 63 passed in 25.08s** |
| CFG-04 контракт: `tests/test_cfg04_forms_contract.py` | **29 passed in 2.95s** |
| CFG-04 профиль (8 файлов: контракт + 1020 + f9 + hotfix9/10 + tma + js-unit + w6) | **202 passed, 1 warning in 7.15s** |
| ADD-EXP F1: `tests/test_add_exp_expression.py` | **33 passed, 1 warning in 3.71s** |
| §5.4-наборы (w6 + persistfix + flags-composition) | **49 passed, 1 warning in 4.15s** |
| Кластеры speech/composer/direct/authorial/sample-library (16 файлов) | **492 passed, 1 warning in 21.33s** |
| capability/registry sanity (3 файла) | **53 passed in 3.21s** |
| F8-пины: `test_round1025_f8_registry.py` | **29 passed in 4.33s** |
| JS-unit sweep: `test_webapp_js_unit.py` (node) | **38 passed in 5.78s** |
| JS-syntax sweep (`node --check`, web/**/*.js + tests/js/**/*.js) | **files=106 bad=0** |
| UI e2e CFG-04: `tools/ui_cfg04_forms_e2e.py` (Playwright, 7 viewport) | **failures=0 console_errors=0** |
| Speech e2e (регрессия 2.58.96): `tests/ui_p0a_ux_speech_compact_e2e.py` | **failures=0 POST=22** |
| F8-каталог: `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.** |
| Bump-verify (каждая изменённая строка = только версия/HEAD-штамп) | **OK: 31 файл, 31 пара строк** |
| ΔDDL-check (дельта не трогает DDL/миграции) | **ΔDDL = 0** |
| Офлайн-сверка деплой-скрипта (hashes 9/9, вайтлист==дельта 5/5 prod..BUMP и prod..HEAD, upload) | **EXIT 0** |
| Маркеры `rel97_final.sh` против байтов кандидата (43 ожидания) | **PASS (43/43)** |
| D2/D3-маркеры deploy-скрипта на байтах кандидата | **PASS** (`deploy-markers-offline.txt`) |

Артефакты: `evidence/release-25897/**` (полный индекс — `README.md` там же).

## 4. Чек-лист пост-деплойной приёмки

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.
Все проверки — read-only или контролируемые, **без лишних платных вызовов**.

**(a) CFG-04 live — матрица форм (закрывает RFL-строки CFG-04).**
Источник: `plans/features/cfg/evidence/cfg-04/manual-checks.md` + review `e27216d3`.
- На deployed 2.58.97 в MiniApp (Telegram WebView), 7 viewport: **320×640,
  360×740, 390×844, 430×932** (портреты) и **667×375, 844×390, 915×412**
  (ландшафты; Telegram-chrome 56/24 px):
  1) **ровно один Save-CTA** в dirty-состоянии; чип шапки — индикатор
     (`role=status`, не кнопка) с honest-подписью «не сохранено» и счётчиком
     в title;
  2) **safe-area ровно один раз** (низ панели не задваивается);
  3) панель **поднята над клавиатурой** (`--kb-offset`), при закрытой клавиатуре
     offset = 0 (стейл исключён);
  4) **последнее поле** и кнопки доступны целиком (scroll-padding = панель+kb+4px),
     touch-цели **44 px**, toggle 44×44;
  5) **tech-key** раскрывается (title/aria-expanded) и копируется (Clipboard API +
     фолбэк, «скопировано» через 1.5 c);
  6) **поворот** экрана сохраняет скролл (config 220→220) и активный ключ;
     в модалке модуля scrollTop уходит к сфокусированному полю (N1 — note, не блокер);
  7) guard несохранённых: уход со страницы → native confirm, отказ остаётся,
     согласие уходит; сохранение ждёт ack, baseline сдвигается без провалов.
- **D.4 (реальное устройство Telegram Android, portrait+landscape) —
  `PENDING_OWNER_E2E`**: необязательная обратная связь владельца (PET-правило),
  **не блокер** релиза; автоматические проверки (Playwright 7 viewport + Browser
  Use-рендер фичевого лейна) зелёные.

**(b) ADD-EXP F4 — поведенческая приёмка (закрывает EXP-ACCEPT.CRITERION).**
Источник: `source-add-exp-2026-10-19.md` §4 + F1-канон `5b86517e` + ledger.
- **6–7 ходов на 3 контекста** (например: стёб, спор/бытовая жалоба, шутка/короткий
  ответ), **disjoint-промпты** (не повторять формулировки между пробами):
  - `frequent`: **≥3 из 6** ответов с **≥1 своим корнем** в **≥3 контекстах**,
    **≤1 корень/предложение** (без кучкования), в коротком ответе допустима частица;
  - `off`: **0 мата в 2 ходах** (off-чат не задет соседним frequent-чатом);
  - жанровые/фактчек-маршруты: **0 forced** мата (цитаты/сводки не переписываются).
- **marker+mode в wire**: `<Expression_Settings>` + `LAYER_EXPRESSION` в complete
  payload, mode = выбранный; **raw == delivered** (постпроцессор не добивает и не
  вырезает молча).
- **occasional**: 10 ходов **или** предрегистрированный widened bound (1 из 4–5
  разговорных реплик — ожидание не «в каждом сообщении»).
- Классификация причин: `model_ignored_instruction` / `provider_limitation` /
  `postprocess_changed` / `policy_not_injected` — не маскировать отказ провайдера.
- Закрытие: production-typed evidence по каждой пробе (тексты сохраняет harness —
  прод их не хранит, Ф0 §3).

**(c) Базовые маркеры выката (обязательны):** `healthz` = `2.58.97`
(loopback и HTTPS), MainPID сменился; журнал since T0: `ERR/CRITICAL/Traceback`
и `402` — разобрать построчно (класс ложных срабатываний — ms-фрагменты
таймстампов, прецедент 2.58.95/96); RuntimeWarning = 0; **SKIPS=0**;
`user_version` без изменений (ΔDDL = 0); served `SERVED_EQ_*=SAME`,
`PAGE_VER=15`, `SUBST_CSS=2`, `STICKY_SAVE_SERVED` ≥1; маркеры поезда 97
(CFG-04 + ADD-EXP F1 — в `deploy_25897.py::D3_markers_25897` и
`rel97_final.sh`) + spot-маркеры 2.58.96/95; `LOCAL_BOT_API_MARKER` ≥1.

**(d) Уборка тестовых сообщений.** Все тестовые сообщения приёмки удалить
в чатах после прогонов (правило владельца; прецедент — `accept91_cleanfinal.py`);
evidence (message_id/скрин) — до удаления.

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.96` (`95d11472`, 2.58.96) — пред-релизная линия прода;
  **новый рубеж** (ветка создаётся при пуше; deploy: tree-restore при abort
  ДО рестарта, fallback — точный detach `95d11472`).
- `release/fix-2.58.95` (`113f3a62`, 2.58.95) — **штатный рубеж авто-отката
  деплой-скрипта** (путь ПОСЛЕ рестарта при неполучении healthz 2.58.97 /
  пустом T0); ветка есть на origin (создана при выкате 2.58.96), объект коммита
  в прод-репо есть (`ROLLBACK_TIP`, fallback-detach).
Abort ДО рестарта отката не ждёт: `_tree_restore` возвращает дерево к
прод-линии 2.58.96 (без рестарта) — downgrade исключён.
Мягкие двери (без рестарта): CFG-04 — UI-only (cold revert к 2.58.96);
`EXPRESSION_EXAMPLES_ENABLED=false` (few-shot off), per-chat
`character.expression` = `off`/`inherit`; прежние env-переключатели
(CFG-02B, Vision, Direct) не меняются.

## 6. Риски/остатки (честно)

1. **Дефект help-sync-гарда (найден и закрыт в этом лейне).** Полный прогон #1
   дал 11 failed: `test_asap8_v6_d14_help_sync.py::test_sticky_save_dirty_only_labels_exist`
   — гард пинил старые подписи чипа, которые CFG-04 осознанно заменил
   (review `e27216d3`). Фикс `8b437c39` (test-only) приводит ожидания к
   отгруженному runtime; runtime-артефакты ревью не тронуты; RED/GREEN в evidence.
2. **Env-флейк mca09 initiative** (`test_handle_initiative_sent_single_transport_chunks`)
   в run #1: в изоляции проходит 15/15 и на кандидате, и на базе; дельта не
   трогает этот backend-путь. Тайминг-флейк полного прогона (класс env-флейков),
   в run #2 не повторился.
3. **Пре-сущ. падения полного pytest** (9 шт. в run #2): набор сверен с
   прогоном 2.58.96 и **прямо воспроизведён на базе `95d11472`** (worktree
   `wt-base`: 9 failed, 63 passed in 25.08s); дельтой эти файлы не тронуты. Не регрессия.
4. **EXP-ACCEPT.CRITERION = FAILED** (acceptance-96: occ 0/7, freq 0/9 — поведение
   не изменилось). F1 `5b86517e` дал исполнимые якори; закрытие — **F4** (§4b)
   после выката; до этого строка честно остаётся FAILED, не «VERIFIED».
5. **CFG-04 D.4** — `PENDING_OWNER_E2E` (реальное устройство): необязательная
   обратная связь (PET), автоматические проверки зелёные; **не блокер**.
6. **N1 (note, не блокер):** поворот при открытой модалке модуля — value/dirty/hash/
   active сохраняются, `modal-body.scrollTop` уходит к сфокусированному полю
   (config-страница сохраняет скролл ровно). Живой сценарий D.5 — postdeploy.
7. **Прод-venv / внешние зависимости не меняются** (Δ зависимостей = 0);
   единственный env-флаг ADD-EXP `EXPRESSION_EXAMPLES_ENABLED` — default ON.

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `…\release-25897\deploy_25897.py` — sha256_12 **`665f818a0764`**
  (клонирован с проверенного скрипта 96 `b8179a3cdb3f` — apre-фикс и
  `_rb` detach-fallback сохранены; T0-hardening сохранён: checked_out-гейт +
  tree-restore, set-equality вайтлиста, tree-restore к прод-линии 2.58.96,
  WARNINGS-summary, SERVED_EQ, один SSH-коннект; маркеры 97
  `D3_markers_25897` (CFG-04 + ADD-EXP F1), `A2_user_version` (ΔDDL до/после),
  `F6_journal_402`): A pre-state → B fetch origin/master (BUMP-ancestor gate) →
  C checkout + runtime-вайтлист дельты (5 файлов) → D sha256_12 (**9
  артефактов**: 5 runtime + README + meta + 2 sanity) + маркеры поезда и
  регрессионные линии 2.58.96/95/94/93/92/91 → F restart + T0 + healthz 2.58.97 +
  журнал + `[local-bot-api]`-маркер + 402 → G served-bytes → J `rel97_final.sh`.
- `rel97_final.sh` — sha256_12 **`d7a755d7b3e6`** (read-only; маркеры поезда 97
  CFG-04/ADD-EXP F1 с ожиданиями, spot-маркеры 2.58.96/95, `EXPRESSION_DIAG_JOURNAL`/
  `EXPRESSION_RESOLVE_WARN`, ERR_402, SKIPS-контроль, `USER_VERSION` (ΔDDL),
  регрессионные маркеры DL-FIX/CFG-02C/2.58.92/2.58.91, SERVED_EQ,
  PAGE_VER/SUBST_CSS/STICKY_SAVE_SERVED, read-only `mca_media_analyses`,
  `/api/workers/budget`, `/api/vision/state`).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25897.py`
  (sha256_12 `375b9a219344`) — **EXIT 0** (hashes 9/9, вайтлист == дельта 5/5
  (prod..BUMP и prod..HEAD), BUMP ancestor HEAD, upload на месте) —
  `deploy-offline-check.txt`.
- Авто-откат ПОСЛЕ рестарта: `release/fix-2.58.95`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.96 (`release/fix-2.58.96`/`95d11472`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.97
  (B3 fail-closed: tip обязан содержать BUMP_COMMIT как ancestor — fix/docs
  коммиты допускаются); ветку `release/fix-2.58.96` создать/запушить при выкате
  (иначе tree-restore идёт fallback-detach'ем на `95d11472`).

## 8. Кандидат-фингерпринт

- Кандидат (runtime+тесты): `8b437c39` = bump `fcd73a38` (2.58.97) + fix
  `8b437c39` (test-only, см. §1); дерево runtime заморожено bump-коммитом.
- Последний коммит поезда до bump (родитель bump): `2428768` (CFG-04) = HEAD-штамп F8-meta.
- Прод-базис: `95d11472` (2.58.96); новый рубеж отката `release/fix-2.58.96`.
- sha256_12 9 артефактов `EXPECT12` — в `deploy_25897.py::EXPECT12` и
  `evidence/release-25897/frozen-fingerprint.txt` (+ полные sha256 там же):
  `web/app.js 885094459700`, `web/index.html 528f358a6589`,
  `web/static/app.css 6b5ca0cc1d47` (== sha12 evidence CFG-04),
  `services/mca_expression.py d23e00763b0d` (F1),
  `config/settings.py 10b6c981b5fc`, `README.md 4b48dd825026`,
  `meta bd31b8f5914e` + sanity `96db06425079`/`e23bced2fdb8`.
- После сборки пакета master получает один plans-only docs-коммит (этот отчёт +
  `evidence/release-25897/**`) — runtime не меняется: дельта `95d11472..HEAD`
  по `config/services/web/handlers/bot.py` = те же **5 файлов**; bump-коммит
  остаётся ancestor HEAD (B3-гейт пройдёт).
