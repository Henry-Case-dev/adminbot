# REV-REL-25896 — вердикт (релиз 2.58.96: ADD-EXP — режимы экспрессии в живой генерации)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.95 @ `113f3a62`.

Кандидат: docs/evidence HEAD `3ff9b319` поверх fix `f06f376f` (test-only) и bump
`14535c59` (2.58.96); код-линия ADD-EXP `4a09e29a` (ревью `981e9902` Needs Fixes
→ RECHECK `d0afd2cc` Approved) + леджер `f1463f10`. Вход: отчёт
`release-25896-report.md`, `evidence/release-25896/**`, `deploy_25896.py`
(`b8179a3cdb3f`), `rel96_final.sh` (`26548559ad7b`), `check_deploy_25896.py`
(`69cf192c0a3a`). Верификация — worktree `release-25896/wt` @ `f06f376f` +
`wt-base` @ `113f3a62`; мои прогоны.

## 1. Bump `14535c59` — подтверждён

- 31 файл; набор файлов ПОБАЙТОВО равен набору 95 (`35b8b455`) — set-equality
  моим прогоном; +33/−33;
- все 33 пары изменённых строк — только версия `2.58.95→2.58.96` или meta HEAD
  `b20fe4f7→f1463f10`; моя независимая проверка — 0 нарушений (включая
  escaped-пины `2\.58\.95` → `2\.58\.96`);
- `APP_VERSION = "2.58.96"`; meta: версия 2.58.96 + HEAD `f1463f10`;
- чужие файлы не в коммитах: сверены все 8 коммитов поезда (`4a09e29a` — 15
  non-plans кода/тестов/`.gitignore`; `f1463f10`/`981e9902`/`d0afd2cc`/`1a58d841`/
  `3ff9b319` — plans-only; `f06f376f` — 1 тест-файл).

## 2. Fix `f06f376f` (критично) — контракт round1019 НЕ ослаблен

- Test-only: `tests/test_status_section_ui_merge_round1019.py`, +10/−2; сужение
  проверки до карточки «Статус»; глобальные `statusData.bot.mode/version`-строки
  оставлены.
- **Мутационные пробы (мои, в scratch, дерево восстановлено):** «Режим:» внутри
  карточки → FAIL (стр. 38); «· версия» внутри карточки → FAIL (стр. 39);
  `statusData.bot.mode` вне карточки → FAIL (стр. 40). Слайс не вырожден:
  6627 симв. (pulse/bot/server/ekg), закрытие карточки — 21 символ после границы
  слайса.
- **RED→GREEN (мой прогон):** база `113f3a62` — 7p; кандидат без фикса (тест-файл
  из `14535c59`, байт-в-байт) — **1f/6p** (`test_mode_version_line_removed`;
  «Режим:» из законного блока live-check `speechLiveCheckResult.mode`); с фиксом
  `f06f376f` — **7p**. RED-эвиденс лейна (`focused-legacy-guard-red.txt`) —
  подлинный (в выводе виден реальный контент live-check).

## 3. Дельта `113f3a62..f06f376f` — изоляция подтверждена

- non-plans = **46** == `delta-non-plans.txt` (set-equality моим прогоном);
  всего у кандидата 75 (46 + 29 plans); у docs-HEAD 105 (+30 evidence);
- runtime = ровно **10** == вайтлист скрипта == мой расчёт, каждое объяснено:
  `services/mca_expression.py` (**новый**, 551) — ядро ADD-EXP (режимы/effective/
  инструкции/few-shot/diag); `services/mca_gates.py` (+12) — env-рубильник
  `EXPRESSION_EXAMPLES_ENABLED` (default ON, per-call, отдельная ось от юмора);
  `services/prompt_composer.py` (+125) — `ExpressionSettings`/`LAYER_EXPRESSION`/
  `resolve_expression_settings`/examples-refs; `services/mca_sample_library.py`
  (+212) — 12 register-карточек, сиды, resolve со skip-reason;
  `services/direct_chat_service.py` (+235) — боевая врезка (Direct L2/tool_phase/
  system2_stage2), маркер-адаптер, postprocess-check, diag-эмиссии;
  `services/mca_authorial_speech.py` (+26) — слой в авториальном Writer +
  `policy_not_injected`; `web/api/speech.py` (+396) — payload (effective/
  migration/`runtime_wired=True`), live-check, сид-эндпоинт (BLOCK-1);
  `web/app.js` (+139)/`web/index.html` (+61) — UI (метки, effective, preview,
  live-run, баннер миграции); `config/settings.py` — только bump-строка;
- **ΔDDL = 0** (database.py/migrations/scripts не в дельте); каталог **Δ = 0**
  (579 == REGISTRY, `--check` — мой прогон); `.gitignore` — узкий re-include
  `!plans/features/add-exp/evidence/build/`; README — только версия.

## 4. Прогоны — воспроизведены (мои)

- полный pytest в wt @ `f06f376f` (чистый повтор): **9 failed / 14552 passed /
  39 skipped** (684.33s) — множество падений = ровно те же 9 пре-сущ. ID, что у
  2.58.95 (asap7×2, history_cli, mca01, t5150×5); первая попытка оборвалась на
  ~77% от pytest-timeout (60 c) из-за зависшего teardown `d.close()` в
  `tests/test_summary_memory.py` — файла НЕТ в дельте, в изоляции 79p; класс
  environment, повтор чистый;
- base-repro (мой, `wt-base` @ `113f3a62`): **9f/63p** — те же 9 ID;
- фокусные (мои): add-exp **31**, §5.4 **49**, кластеры **492** (одна
  транзиентная флейк-проба observer-gates, не воспроизвелась в 7 прогонах,
  вкл. 3× на базе), capability **53**, F8 **29**, реестр **579**, JS-свип
  **105/0** (`node --check`), UI e2e **failures=0 / POST=22** (Playwright).

## 5. Скрипты — сверены офлайн (прод не трогался)

- хэши совпали; `check_deploy_25896.py` — **EXIT 0** (мой прогон): вайтлист
  10/10 == дельта (prod..BUMP и prod..HEAD), BUMP — ancestor, upload на месте;
- `deploy_25896.py` — клон ИСПРАВЛЕННОГО 95-скрипта (`473686f333fb` сверен по
  хэшу): apre-фикс и `_rb` detach-fallback сохранены; `PROD_REF=113f3a62`,
  `PROD_BRANCH=release/fix-2.58.95`, `ROLLBACK_BRANCH=release/fix-2.58.94`,
  `ROLLBACK_TIP=9072347b`; EXPECT12 — **все 14 sha256_12 пересчитал сам,
  совпали**;
- `rel96_final.sh`: `bash -n` OK (Git Bash); read-only; **все 41 ожидание
  маркеров сверил сам с байтами кандидата — 0 расхождений** (лейн-селфчек
  41/41 согласован);
- откат: `release/fix-2.58.94` @ `9072347b` **есть на origin** (мой ls-remote);
  в прод-репо локальной ветки может не быть (recon-95: LOCAL94=MISSING) — detach
  fallback закрывает; новый рубеж `release/fix-2.58.95` — push при выкате
  (fallback — detach `113f3a62`).

## 6. Чек-лист §4 — полон и соответствует источнику §4

(a) живой набор 20–30 проб по 3 режимам × контексты; маршруты Direct/Initiative/
жанровые; изоляция frequent/off; переключение без рестарта; reread; preview vs
production trace; wire-маркер + классы `model_ignored_instruction`/
`provider_limitation`/`postprocess_changed`/`policy_not_injected` (код-эмиттеры
проверены: одиночная проба не «приговор», N=5 — порог); production-typed
evidence по каждой пробе — закрывает 5 RFL-строк. (b) few-shot — опционально:
сиды `seeded=18`/`expression_seeded=12` идемпотентны, в runtime только
`owner_approved=1`, до одобрения честный `not_owner_approved` (проверено в
коде). (c) CFG-07B (`profanity_use`) — будущий слот (в коде/планах сегодня нет;
design-add-exp §1.4), ADD-EXP его не трогает — при приёмке не смешивать.
(d) базовые маркеры выката — в скриптах (healthz 2.58.96, ERR/402-триаж,
SKIPS=0, user_version без Δ, SERVED_EQ/PAGE_VER=15/SUBST_CSS=2, маркеры поезда +
spot 2.58.95, LOCAL_BOT_API_MARKER≥1). (e) уборка. UI: скриншот 390px — честный
предпросмотр («не речевой результат») + live-check с реальным ответом и строкой
«Режим: occasional; корней мата: 1; маркер слоя: есть»; e2e проверяет отсутствие
сырых кодов/старой метки и счётчики «регистр речи: 0 из 12».

## 7. Дисциплина

Коммиты `--only` (все 8 проверены); acceptance-95/чужие evidence **не входят**
ни в один коммит поезда (сверка списков; в дереве остаются незакоммиченными);
evidence полный (29 файлов; README перечисляет 28 + себя).

## Леджер

- **RFL (5, postdeploy Ф6):** EXP-RUNTIME.WIRING, EXP-RUNTIME.PAYLOAD,
  EXP-ACCEPT.LIVE-SET, EXP-ACCEPT.ROUTES, EXP-ACCEPT.CRITERION — закрыть §4(a)
  production-typed evidence; после — `VERIFIED` + `deployed_commit` и
  `check --stage release --candidate 4a09e29a… --deployed-commit <SHA>`
  (карта привязана к `4a09e29a`; review-гейты у меня EXIT 0: UI 8 / INSTR 4 /
  RUNTIME 11 / ACCEPT 6, scoped=29, errors=0 — полный SHA).
- **Фикс-строка:** `f06f376f` — часть кандидата; контракт round1019 сохранён
  (мутации); не расширять проверку обратно до всей страницы — коллизия вернётся.
- **Рубеж отката:** `113f3a62` → `release/fix-2.58.95` (push при выкате; иначе
  tree-restore — detach). Авто-откат после рестарта — `release/fix-2.58.94`
  (на origin; detach `9072347b`). Мягкие двери: `EXPRESSION_EXAMPLES_ENABLED=false`,
  per-chat `character.expression` = off/inherit.
- Предусловие: push `master` с bump-коммитом (B3 fail-closed).

## Наблюдения (не блокирующие)

* Отчёт §2 в прозе пишет «30 файлов tests» — фактически 34 (30 py + 4 JS);
  разбивка полная, полный список — в `delta-non-plans.txt`.
* Первый мой полный прогон оборван environment-зависанием teardown в
  `test_summary_memory.py` (файл не в дельте; в изоляции зелёный); повтор чистый.
* Одна транзиентная флейк-проба `test_day_cap_still_hard_with_soft_target`
  (S3-кластер) не воспроизвелась 7 прогонами (3× кандидат, 3× база, 1× изоляция).
* Граница слайса round1019 — до `</section>` серверной подсекции (закрытие
  карточки +21 симв.): контент, вставленный в этот зазор, не поймается —
  теоретический случай; реалистичная мутация ловится.

## Вердикт

**Approved** — релиз-пакет 2.58.96 (bump `14535c59`, fix `f06f376f`, HEAD
`3ff9b319`) проверен: bump версионно-чистый (набор == 95), fix сохраняет
контракт round1019 (мутации + RED/GREEN), дельта изолирована (10/10 runtime ==
вайтлист == reviewed-коммиты), ΔDDL=0, каталог 579, хэши 14/14, полный pytest
9f/14552p (тот же пре-сущ. набор) + base 9f/63p, фокусные/JS/UI воспроизведены,
скрипты офлайн-согласованы (41/41 маркеров, EXIT 0, откатные рубежи наличны),
чеклист §4 полон. DONE — только после Ф6-приёмки §4 и обновления леджера;
деплой — за DevOps/Orchestrator.
