# REV-REL-25897 — вердикт (релиз 2.58.97: CFG-04 + ADD-EXP F1)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.96 @ `95d11472`.

Кандидат: docs/evidence HEAD `e5217933` поверх fix `8b437c39` (test-only) и bump
`fcd73a38` (2.58.97); код-линия CFG-04 `2428768` (ревью `e27216d3` Approved) +
ADD-EXP F1 `5b86517e` (ревью `188f7414` Approved); docs `c48fe4cf` (CFG-05 prep).
Вход: отчёт `release-25897-report.md`, `evidence/release-25897/**`,
`deploy_25897.py` (`665f818a0764`), `rel97_final.sh` (`d7a755d7b3e6`),
`check_deploy_25897.py` (`375b9a219344`). Верификация — worktree
`release-25897/wt` @ `8b437c39` + `wt-base` @ `95d11472`; мои прогоны.

## 1. Bump `fcd73a38` — подтверждён

- 31 файл; набор файлов побайтово равен набору 96 (`14535c59`) — set-equality
  моим прогоном; +33/−33;
- все 33 пары изменённых строк — только версия `2.58.96→2.58.97` или meta HEAD
  `f1463f10→2428768`; моя независимая проверка — 0 нарушений (включая
  escaped-пины);
- `APP_VERSION = "2.58.97"`; meta: версия 2.58.97 + HEAD `2428768`;
- чужие файлы не в коммитах: сверены все коммиты поезда (`5b86517e` — 2
  non-plans: модуль+тест; `2428768` — 9 non-plans: 3 runtime + тесты/tool;
  `c48fe4cf`/`e27216d3`/`188f7414` — plans-only; `8b437c39` — 1 тест;
  `e5217933` — 34 файла, plans-only).

## 2. Fix `8b437c39` (test-only) — цель help-sync-гарда не ослаблена

- Патч: `tests/test_asap8_v6_d14_help_sync.py`, +4/−3; пины приведены к
  ОТГРУЖЕННОМУ runtime (`dirty: 'не сохранено'` / `saving: 'сохранение…'` —
  фактические метки чипа в `web/app.js:3103`), контракт «help matches shipped
  runtime» сохранён.
- **Мутационные пробы (мои, в scratch, дерево восстановлено):** подмена
  runtime-метки `dirty` → гард FAIL (стр. 168); подмена `saving` → FAIL
  (стр. 169). Гард живой, не тавтологичен.
- **RED→GREEN (мой прогон):** база `95d11472` — **24p**; кандидат без фикса
  (тест-файл из `fcd73a38`, точные байты) — **1f/23p**
  (`test_sticky_save_dirty_only_labels_exist`); с фиксом `8b437c39` — **24p**.

## 3. Дельта `95d11472..8b437c39` — изоляция подтверждена

- non-plans = **42** == `delta-non-plans.txt` (set-equality моим прогоном);
  всего у кандидата 235 (42 + 193 plans); у docs-HEAD 269 (+34 evidence);
- runtime = ровно **5** == вайтлист скрипта == мой расчёт, каждое объяснено:
  `web/app.js`, `web/index.html`, `web/static/app.css` (CFG-04: один save-CTA,
  чип-индикатор, safe-area/kb, tech-key, ориентация); `services/mca_expression.py`
  (ADD-EXP F1: частотные якори + честный header); `config/settings.py` — только
  bump-строка; README — только версия;
- **ΔDDL = 0** (database.py/migrations/scripts не в дельте); каталог **Δ = 0**
  (579 == REGISTRY, `--check` — мой прогон); sanity-файлы
  (`fullscreen-policy.js`/`telegram_send.py`) байт-в-байт равны базе.

## 4. Прогоны — воспроизведены (мои)

- полный pytest (чистый, wt @ `8b437c39`): **9 failed / 14583 passed / 39
  skipped** (681.02s) — множество падений = ровно те же 9 пре-сущ. ID, что у
  2.58.96 (asap7×2, history_cli, mca01, t5150×5);
- base-repro (мой, `wt-base` @ `95d11472`): **9f/63p** — те же 9 ID;
- env-флейк `mca09…single_transport_chunks`: кандидат **15p** (3 прогона);
  база — **15p** (3 прогона) и **1f/14p** (один прогон) — тайминг-флейк
  воспроизводится и на БАЗЕ ⇒ не дельта (у лейна 15/15 — «зелёный» сценарий,
  не гарантия; класс подтверждён);
- фокусные (мои): CFG-04 контракт **29**, CFG-04-профиль **202**, add-exp F1
  **33**, §5.4 **49**, кластеры **492**, capability **53**, F8 **29**,
  js-unit **38**, реестр **579** (`--check` OK), JS-свип **106/0**,
  CFG-04 e2e (Playwright, 7 viewport) **failures=0 / console_errors=0**,
  speech e2e **failures=0 / POST=22**.

## 5. Скрипты — сверены офлайн (прод не трогался)

- хэши совпали; `check_deploy_25897.py` — **EXIT 0** (мой прогон): вайтлист
  5/5 == дельта (prod..BUMP и prod..HEAD), BUMP — ancestor, upload на месте;
- `deploy_25897.py` — клон проверенного 96-скрипта (`b8179a3cdb3f` сверен по
  хэшу): apre-фикс и `_rb` detach-fallback сохранены; `PROD_REF=95d11472`,
  `PROD_BRANCH=release/fix-2.58.96`, `ROLLBACK_BRANCH=release/fix-2.58.95`,
  `ROLLBACK_TIP=113f3a62`; EXPECT12 — **все 9 sha256_12 пересчитал сам,
  совпали**;
- `rel97_final.sh`: `bash -n` OK (Git Bash); read-only; **все 43 ожидания
  маркеров сверил сам с байтами кандидата — 0 расхождений** (CFG-04 ×10,
  ADD-EXP F1 ×7, spot 2.58.96/95 ×5, DL-FIX ×8, CFG-02C ×13);
- откат: `release/fix-2.58.95` @ `113f3a62` **есть на origin** (мой ls-remote;
  создана при выкате 2.58.96), detach-fallback закрывает отсутствие локальной
  ветки в прод-репо; новый рубеж `release/fix-2.58.96` — push при выкате
  (fallback — detach `95d11472`).

## 6. Чек-лист §4 — полон и соответствует источникам

(a) CFG-04 live-матрица: 7 viewport (320×640, 360×740, 390×844, 430×932,
667×375, 844×390, 915×412), 7 проверок (ровно один save-CTA + чип-индикатор
`role=status`; safe-area ровно один раз; панель над клавиатурой; последнее поле
+ 44 px; tech-key expand/copy; поворот сохраняет скролл/key/dirty; guard
несохранённых) — источник `evidence/cfg-04/manual-checks.md` + review
`e27216d3`; **D.4 = PENDING_OWNER_E2E** (PET: необязательная обратная связь,
не блокер; автоматические проверки зелёные). (b) ADD-EXP F4: 6–7 ходов × 3
контекста, disjoint; `frequent` **≥3/6** с ≥1 своим корнем в ≥3 контекстах,
≤1 корень/предложение; `off` **0/2**; жанровые/фактчек **0 forced**;
marker+mode в wire; **raw == delivered**; `occasional` — 10 ходов или
предрегистрированный widened bound; diag-классы честные; production-typed
evidence по каждой пробе. (c) Базовые маркеры — в скриптах (healthz 2.58.97,
ERR/402-триаж, SKIPS=0, user_version без Δ, SERVED_EQ/PAGE_VER=15/SUBST_CSS=2/
**STICKY_SAVE_SERVED ≥1**, маркеры поезда 97 + spot 2.58.96/95,
LOCAL_BOT_API_MARKER ≥1). (d) Уборка тестовых сообщений.
**`EXP-ACCEPT.CRITERION` остаётся FAILED до F4** (accept-96: occ 0/7,
freq 0/9; карта: FAILED) — F1 даёт исполнимость, но не закрывает критерий.
UI-слой (визуальный гейт): Playwright e2e 7 viewport + скриншоты before/after;
мой Browser Use (реальный рендер): чип — DIV `role=status` «1 · не сохранено»
(не кнопка), ровно один CTA «Сохранить изменения» в панели, panel safe-area
считается один раз (padding-bottom 63.2 при safe=56), последнее поле выше
панели (overlap −99.6).

## 7. Дисциплина

Коммиты `--only` (все проверены); чужие WIP (workflow_state/progress_scope/
asap8/acceptance-96-доки) не входят ни в один коммит поезда; evidence полный
(32 файла перечислены, README — 33-й).

## Леджер

- **RFL (CFG-04, 11 строк):** CFG-04B.1/B.2/B.3, C.1/C.2/C.4/C.5, D.1/D.5,
  CFG-04A.1, CFG-04.B — закрыть §4(a) на deployed 2.58.97; **D.4** —
  `PENDING_OWNER_E2E` (optional, не блокер). Восемь не-live строк
  (ADD-1.C5, B.4, B.5, C.3, D.2, D.3, ADD-1.T4, CFG-04.F) — VERIFIED по
  review-эвиденсу. **До `--stage release`:** привязать 20 строк CFG-04
  (сейчас в карте все PENDING/0 evidence, candidate/deployed = 2.58.95) и
  обновить candidate/deployed SHA релиза.
- **ADD-EXP:** `EXP-ACCEPT.CRITERION` = **FAILED** до F4 (§4b); после F4 —
  VERIFIED + production-typed evidence; карту перепривязать к релиз-кандидату
  (сейчас 2.58.96), F1-эвиденс — в `EXP-INSTR.POSITIVE`.
- **Рубеж отката:** `95d11472` → `release/fix-2.58.96` (push при выкате; иначе
  tree-restore — detach). Авто-откат после рестарта — `release/fix-2.58.95`
  (на origin; detach `113f3a62`). Мягкие двери: `EXPRESSION_EXAMPLES_ENABLED=false`,
  per-chat `character.expression` = off/inherit; CFG-04 — UI-only (cold revert).
- **Фикс-строка:** `8b437c39` — test-only; гард не расширять обратно до всей
  страницы; метки чипа — отгруженные.
- Предусловие: push `master` с bump-коммитом 2.58.97 (B3 fail-closed).

## Наблюдения (не блокирующие)

* Env-флейк `mca09` воспроизвёлся и на базе (1f/14p в одном из моих прогонов;
  3×15p) — класс пре-сущ., не регрессия; «15/15» лейна — не гарантия.
* Evidence-README (строки про speech e2e и markers) содержит mojibake
  захваченного вывода (двойное перекодирование) — косметика.
* Карта CFG-04 — pre-binding (все PENDING, candidate 2.58.95): отражено в
  review `e27216d3`, закрывается на приёмке (см. леджер).
* N1 (поворот при открытой модалке модуля: value/dirty/hash/active сохранены,
  scrollTop уходит к фокусу) — документированный note, не блокер.

## Вердикт

**Approved** — релиз-пакет 2.58.97 (bump `fcd73a38`, fix `8b437c39`, HEAD
`e5217933`) проверен: bump версионно-чистый (набор == 96), fix сохраняет
контракт help-sync (мутации + RED/GREEN), дельта изолирована (5/5 runtime ==
вайтлист == reviewed-коммиты), ΔDDL=0, каталог 579, хэши 9/9, полный pytest
9f/14583p (тот же пре-сущ. набор) + base 9f/63p, фокусные/JS/UI воспроизведены,
скрипты офлайн-согласованы (43/43 маркеров, EXIT 0, откатные рубежи наличны),
чеклист §4 полон, визуальный слой подтверждён (Playwright + Browser Use).
DONE — только после live-матрицы CFG-04, F4 (CRITERION) и привязки карт;
деплой — за DevOps/Orchestrator.
