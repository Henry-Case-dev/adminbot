# Релиз **2.58.96** — ADD-EXP (режимы экспрессии в живой генерации)

Дата сборки кандидата: 2026-10-19/20 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** — код-коммит ADD-EXP `4a09e29a` (ревью раунд1
`981e9902` Needs Fixes → RECHECK `d0afd2cc` **Approved**, BLOCK-1 закрыт),
леджер `f1463f10`, bump `14535c59` (2.58.96) + **fix `f06f376f`** (тестовый
гард round1019 — см. §3/§6, runtime не тронут); прод до релиза — **`2.58.95 @
113f3a62`**.
Статус: **собран и проверен локально**; деплой и приёмка — отдельные шаги (§4).
Задача: LANE RELEASE-PKG-96 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от кандидата
(`OPENCODE_WORKFLOW_SCRATCH\release-25896\wt` @ `f06f376f`); главное дерево
для прогонов кандидата не использовалось. Незакоммиченные чужие правки
(`plans/workflow_state.md`, `plans/progress_scope.json`, asap8-доки, WIP других
лейнов) **не вошли ни в один коммит** этого поезда (commit строго `--only`;
набор bump = набор прошлого поезда, 31 файл).

## 1. Состав (что вошло)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| ADD-EXP (код/тесты/UI) | `4a09e29a` | Режимы экспрессии **«Без мата»/«Эпизодически»/«Часто»** перестали быть только формой: per-control effective-merge (`inherit` + alias `allowed`→`occasional`), врезка `<Expression_Settings>` в живой Direct L2 / tool_phase / system2_stage2 и авториальный Writer (`policy_not_injected`-диагностика), few-shot `<Expression_Examples>` (12 register-карточек, в runtime только `owner_approved=1`; seed-эндпоинт создаёт драфты — BLOCK-1 закрыт), diag-классы (`composer_excluded`/`policy_not_injected`/`postprocess_changed`/`provider_limitation`/`model_ignored_instruction`), UI: читаемые названия режимов, effective+источник, runtime_wired/live-check, `migration`, sticky-меню. Ревью: `981e9902` Needs Fixes (BLOCK-1: сиды недостижимы в prod) → RECHECK `d0afd2cc` **Approved**. |
| Леджер/гейты | `f1463f10` | Биндинг кандидата `4a09e29a`: 24 VERIFIED + 5 READY_FOR_LIVE (Ф6 postdeploy), все 29 required-строк привязаны; review-гейты EXIT 0 (UI 8 / INSTR 4 / RUNTIME 11 / ACCEPT 6, errors=0). |
| Bump/F8 | `14535c59` | `2.58.95 → 2.58.96`: settings + README + F8-meta (APP_VERSION `2.58.96`, HEAD-штамп `f1463f10`) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33, версионно-чистый — `bump-verify.txt`). |
| Fix гарда (найден полным прогоном #1) | `f06f376f` | `tests/test_status_section_ui_merge_round1019.py` — легаси-гард проверял подстроку «Режим:» по ВСЕЙ странице; новый (законный) блок live-check экспрессии ADD-EXP содержит метку «Режим:» → детерминированный красный тест, внесённый дельтой. Фикс сужает проверку до карточки «Статус» (контракт round1019 сохранён; глобальные `statusData.bot.mode/version`-проверки оставлены). RED 1f/6p → GREEN 7p; база `113f3a62` была зелёной (7p). Test-only: runtime-артефакты ревью не тронуты. |

## 2. Дельта к проду (изоляция)

База = прод `113f3a62` (2.58.95). Полная дельта кандидата `f06f376f`
(включая `plans/**`) = **75 файлов**; без `plans/**` — **46**
(`delta-non-plans.txt`):

- **10 runtime-файлов** — ровно они и есть вайтлист деплой-скрипта (любой
  другой runtime-файл в дельте = abort; сверка равенства множеств офлайн:
  PASS, `deploy-offline-check.txt`):
  `services/mca_expression.py` (**новый**), `services/mca_gates.py`,
  `services/prompt_composer.py`, `services/mca_sample_library.py`,
  `services/direct_chat_service.py`, `services/mca_authorial_speech.py`,
  `web/api/speech.py`, `web/app.js`, `web/index.html`, `config/settings.py`
  (bump) — runtime-stat в `delta-runtime-stat.txt`;
- **30 файлов `tests/`**: новые/правленые ADD-EXP (`test_add_exp_expression.py`
  (31), `test_p0_persistfix_speech_chat_scope.py`, `test_soul1_flags_composition.py`,
  `test_soul1_w6_speech_ui.py`, `ui_p0a_ux_speech_compact_e2e.py`) + 24 py-пина +
  4 JS-пина (bump) + fix-файл гарда `test_status_section_ui_merge_round1019.py`;
- `.gitignore` — узкий re-include `!plans/features/add-exp/evidence/build/`;
- `README.md` — bump-файл;
- плюс `plans/**` (29 файлов: evidence/build ADD-EXP, requirements-map + ledger,
  review-add-exp, F8-meta).

ΔDDL = **0**: `services/database.py`, migrations-модули и `scripts/` в дельту
не входят (`ddl-check.txt`); `user_version` на проде остаётся **36**.
Δ каталога = **0** (REGISTRY 579; `--check` OK).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.95:
`web/static/fullscreen-policy.js` `96db06425079`,
`services/telegram_send.py` `e23bced2fdb8` — сверено (в дельте их нет,
побайтовое равенство подтверждено, `frozen-fingerprint.txt`).

## 3. Проверки кандидата (run-as-is, в изолированном worktree от кандидата)

| Проверка | Результат |
|---|---|
| Полный `pytest -q`, **run #1** (кандидат `14535c59`, до fix) | **10 failed, 14551 passed, 39 skipped, 1 warning in 735.35s (0:12:15)** — на 1 больше пре-сущ.: вскрыт дефект легаси-гарда round1019 (`pytest-run1-red.txt`) |
| Полный `pytest -q`, **run #2** (кандидат `f06f376f`, после fix) | **9 failed, 14552 passed, 39 skipped, 1 warning in 690.08s (0:11:30)** (690.08s; start 2026-10-19T13:44:09Z → end 2026-10-19T13:55:43Z UTC) |
| Множество падений run #2 vs прогон 2.58.95 | точное совпадение множества (`pytest-attribution.txt`) |
| Легаси-гард round1019: база → кандидат(RED) → фикс(GREEN) | **7p → 1f/6p → 7p** (`focused-legacy-guard-fix.txt`, `focused-legacy-guard-red.txt`) |
| Прямое доказательство пре-сущ. на базе `113f3a62` (worktree `wt-base`, 4 файла падений) | **9 failed, 63 passed in 25.66s** |
| `tests/test_add_exp_expression.py` (ADD-EXP контракт) | **31 passed, 1 warning in 3.90s** |
| §5.4-наборы (w6 + persistfix + flags-composition) | **49 passed, 1 warning in 4.36s** |
| Кластеры speech/composer/direct/authorial/sample-library (16 файлов) | **492 passed, 1 warning in 24.04s** |
| capability/registry sanity (3 файла) | **53 passed in 3.81s** |
| F8-пины: `test_round1025_f8_registry.py` | **29 passed in 5.06s** |
| F8-каталог: `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.** |
| JS-syntax sweep (`node --check`, web/**/*.js + tests/js/**/*.js) | **files=105 bad=0** |
| UI e2e: `tests/ui_p0a_ux_speech_compact_e2e.py` (Playwright) | **failures=0 POST=22** |
| Bump-verify (каждая изменённая строка = только версия/HEAD-штамп) | **OK: 31 файл, 31 пара строк** |
| ΔDDL-check (дельта не трогает DDL/миграции) | **ΔDDL = 0** |
| Офлайн-сверка деплой-скрипта (hashes 14/14, вайтлист==дельта 10/10 prod..BUMP и prod..HEAD, BUMP ancestor, upload) | **EXIT 0** |
| Маркеры `rel96_final.sh` против байтов кандидата (41 ожидание) | **PASS (41/41)** |
| D2/D3-маркеры deploy-скрипта на байтах кандидата | **PASS** (`deploy-markers-offline.txt`) |

Артефакты: `evidence/release-25896/**` (полный индекс — `README.md` там же).

## 4. Чек-лист пост-деплойной приёмки (Ф6 для ADD-EXP)

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.
Все проверки — read-only или контролируемые, **без лишних платных вызовов**.

**(a) ADD-EXP Ф6 — живой набор 20–30 проб (закрывает 5 RFL-строк:
EXP-RUNTIME.WIRING/PAYLOAD, EXP-ACCEPT.LIVE-SET/ROUTES/CRITERION).**
Источник: `source-add-exp-2026-10-19.md` §4 + ledger `f1463f10`.
- 3 режима × контексты: дружеский стёб / спор / короткий ответ / быт /
  шутка / нейтральная техзадача / фактчек-цитата; вариация формулировок;
  частота измеряется по допустимым разговорным репликам (frequent заметно
  чаще occasional; off — исключает мат из собственного текста, не искажая
  цитаты/факты). Не требовать мата в каждой реплике.
- Маршруты: Direct, Initiative, подходящие жанровые Writer-маршруты;
  фактчек/тех. сводки — по жанровому контракту.
- Изоляция чатов: активный `frequent`-чат не влияет на `off`-чат
  (per-chat override vs GLOBAL).
- Переключение режима **без рестарта**; **reread после сохранения**
  (read-after-write, revision/history); **preview vs production trace**.
- Наблюдаемость: wire-маркер слоя (`LAYER_EXPRESSION`/`<Expression_Settings>`
  в complete payload) и классификация причин: `model_ignored_instruction` /
  `provider_limitation` / `postprocess_changed` / `policy_not_injected` —
  не маскировать отказ провайдера под исправление.
- Закрытие: production-typed evidence по каждой пробе (тексты ответов
  сохраняет harness — прод их не хранит, Ф0 §3).

**(b) Few-shot (опционально, не блокер).** Владелец при желании одобряет
12 register-карточек в UI (`owner_approved=1` — только они идут в runtime);
до одобрения — честный `not_owner_approved`, no-op. Ожидания seed:
`seeded=18`, `expression_seeded=12`, повторный — `skipped=18`/`expression_skipped=12`.

**(c) CFG-07B-проекция `profanity_use` — отдельный слот.** ADD-EXP её не
трогает; при включённом CFG-07B effective = {occasional, frequent} — это
контракт CFG-07B, не дефект ADD-EXP. При приёмке не смешивать.

**(d) Базовые маркеры выката (обязательны):** `healthz` = `2.58.96`
(loopback и HTTPS), MainPID сменился; журнал since T0: `ERR/CRITICAL/Traceback`
и `402` — разобрать построчно (класс ложных срабатываний — ms-фрагменты
таймстампов, прецедент 2.58.95); RuntimeWarning = 0; **SKIPS=0**;
`user_version` без изменений (ΔDDL = 0); served `SERVED_EQ_*=SAME`,
`PAGE_VER=15`, `SUBST_CSS=2`; маркеры поезда 96 (ADD-EXP — в
`deploy_25896.py::D3_markers_25896` и `rel96_final.sh`) + spot-маркеры
2.58.95; `LOCAL_BOT_API_MARKER` ≥1.

**(e) Уборка тестовых сообщений.** Все тестовые сообщения приёмки удалить
в чатах после прогонов (правило владельца; прецедент — `accept91_cleanfinal.py`);
evidence (message_id/скрин) — до удаления.

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.95` (`113f3a62`, 2.58.95) — пред-релизная линия прода;
  **новый рубеж** (ветка создаётся при пуше; deploy: tree-restore при abort
  ДО рестарта, fallback — точный detach `113f3a62`).
- `release/fix-2.58.94` (`9072347b`, 2.58.94) — **штатный рубеж авто-отката
  деплой-скрипта** (путь ПОСЛЕ рестарта при неполучении healthz 2.58.96 /
  пустом T0); ветка есть на origin (ls-remote 19.10 13:00Z), объект коммита
  в прод-репо есть (`ROLLBACK_TIP`, fallback-detach).
Abort ДО рестарта отката не ждёт: `_tree_restore` возвращает дерево к
прод-линии 2.58.95 (без рестарта) — downgrade исключён.
Мягкие двери (без рестарта, env-only): `EXPRESSION_EXAMPLES_ENABLED=false`
(few-shot off), per-chat `character.expression` = `off`/`inherit`;
прежние env-переключатели (CFG-02B, Vision, Direct) не меняются.

## 6. Риски/остатки (честно)

1. **Дефект легаси-гарда (найден и закрыт в этом лейне).** Полный прогон #1
   дал 10 failed: `test_status_section_ui_merge_round1019.py::test_mode_version_line_removed`
   — коллизия нового (законного) UI-блока ADD-EXP с over-broad проверкой
   round1019. Фикс `f06f376f` (test-only) сузил проверку до карточки «Статус»,
   сохранив контракт; runtime-артефакты ревью не тронуты; RED/GREEN-доказательства
   в evidence. Reviewer должен проверить фикс как часть пакета.
2. **Пре-сущ. падения полного pytest** (9 шт. в run #2): набор сверен с
   прогоном 2.58.95 и **прямо воспроизведён на базе `113f3a62`** (worktree
   `wt-base`: 9 failed, 63 passed in 25.66s); дельтой эти файлы не тронуты. Не регрессия.
3. **5 RFL-строк ADD-EXP** (WIRING/PAYLOAD/LIVE-SET/ROUTES/CRITERION) —
   закрываются только Ф6-эвиденсом после выката (§4a); код-половина каждой
   строки закрыта evidence и ревью RECHECK.
4. **`model_ignored_instruction`** — принципиально live-класс (модель может
   проигнорировать инструкцию): честная классификация в Ф6, не «исправление».
5. **Few-shot карточки** — до одобрения владельцем runtime честно сообщает
   `not_owner_approved` (не блокер релиза, OPTIONAL_FEEDBACK).
6. **Прод-venv / внешние зависимости не меняются** (Δ зависимостей = 0);
   единственный env-флаг ADD-EXP `EXPRESSION_EXAMPLES_ENABLED` — default ON.

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `…\release-25896\deploy_25896.py` — sha256_12 **`b8179a3cdb3f`**
  (клонирован с **ИСПРАВЛЕННОГО** скрипта 95 `473686f333fb` — apre-фикс и
  `_rb` detach-fallback сохранены; T0-hardening сохранён: checked_out-гейт +
  tree-restore, set-equality вайтлиста, tree-restore к прод-линии 2.58.95,
  WARNINGS-summary, SERVED_EQ, один SSH-коннект; маркеры 96
  `D3_markers_25896` (ADD-EXP), `A2_user_version` (ΔDDL до/после),
  `F6_journal_402`): A pre-state → B fetch origin/master (BUMP-ancestor gate) →
  C checkout + runtime-вайтлист дельты (10 файлов) → D sha256_12 (**14
  артефактов**: 10 runtime + README + meta + 2 sanity) + маркеры поезда и
  регрессионные линии 2.58.95/94/93/92/91 → F restart + T0 + healthz 2.58.96 +
  журнал + `[local-bot-api]`-маркер + 402 → G served-bytes → J `rel96_final.sh`.
- `rel96_final.sh` — sha256_12 **`26548559ad7b`** (read-only; маркеры поезда 96
  ADD-EXP с ожиданиями, spot-маркеры 2.58.95, `EXPRESSION_DIAG_JOURNAL`/
  `EXPRESSION_RESOLVE_WARN`, ERR_402, SKIPS-контроль, `USER_VERSION` (ΔDDL),
  регрессионные маркеры DL-FIX/CFG-02C/2.58.92/2.58.91, SERVED_EQ,
  PAGE_VER/SUBST_CSS, read-only `mca_media_analyses`, `/api/workers/budget`,
  `/api/vision/state`).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25896.py`
  (sha256_12 `69cf192c0a3a`) — **EXIT 0** (hashes 14/14, вайтлист == дельта 10/10
  (prod..BUMP и prod..HEAD), BUMP ancestor HEAD, upload на месте) —
  `deploy-offline-check.txt`.
- Авто-откат ПОСЛЕ рестарта: `release/fix-2.58.94`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.95 (`release/fix-2.58.95`/`113f3a62`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.96
  (B3 fail-closed: tip обязан содержать BUMP_COMMIT как ancestor — fix/docs
  коммиты допускаются); ветку `release/fix-2.58.95` создать/запушить при
  выкате (иначе tree-restore идёт fallback-detach'ем на `113f3a62`).

## 8. Кандидат-фингерпринт

- Кандидат (tip, runtime+тесты): `f06f376f` = bump `14535c59` (2.58.96) + fix
  `f06f376f` (test-only, см. §1); дерево runtime заморожено bump-коммитом.
- Последний коммит поезда до bump (родитель bump): `f1463f10` (леджер ADD-EXP) = HEAD-штамп F8-meta.
- Прод-базис: `113f3a62` (2.58.95); новый рубеж отката `release/fix-2.58.95`.
- sha256_12 14 артефактов `EXPECT12` — в `deploy_25896.py::EXPECT12` и
  `evidence/release-25896/frozen-fingerprint.txt` (+ полные sha256 там же):
  `services/mca_expression.py 2b0d09888243` (новый),
  `services/mca_gates.py 1f6c28841d8a`,
  `services/prompt_composer.py 721773eada65`,
  `services/mca_sample_library.py a7f81b4f62c0`,
  `services/direct_chat_service.py 0faaa6034f71`,
  `services/mca_authorial_speech.py 55e8fd72ccff`,
  `web/api/speech.py 85741bcacdbf`, `web/app.js 1d68fede513e`,
  `web/index.html b80dad12a482`, `config/settings.py 1f39e0269056`,
  `README.md 9af3db32f047`, `meta 5e804bb16316` + sanity
  `96db06425079`/`e23bced2fdb8`.
  Хэши runtime совпадают с sha12 пост-фиксного ревью `d0afd2cc` (BLOCK-1-коммит).
- После сборки пакета master получает один plans-only docs-коммит (этот отчёт +
  `evidence/release-25896/**`) — runtime не меняется: дельта `113f3a62..HEAD`
  по `config/services/web/handlers/bot.py` = те же **10 файлов**; bump-коммит
  остаётся ancestor HEAD (B3-гейт пройдёт).
