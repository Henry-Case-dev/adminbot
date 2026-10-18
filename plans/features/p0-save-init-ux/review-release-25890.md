# REV-REL-25890 — независимое ревью релиза 2.58.90 (P0-хотфиксы)

Read-only ревью кандидата и деплой-артефактов; деплой и push НЕ выполнялись.
Этот коммит — данный вердикт + применённый патч релиз-дока (NF-2/NF-3;
`release-25890-report.md`). Мои перепрогоны писались в scratch
(`rev-rel-25890-audit/`), чужой evidence не трогался (`git status` чист по
`plans/features/soul-1/**` и `p0-save-init-ux/evidence/**`).

Биндинг:
* Кандидат: `f2cd3a71fb63f74b322a4cdaf46c639f76b1607d` (bump 2.58.83→2.58.90;
  родитель — payload `01e1cc8d`); отчёт — `9286ed0e`; evidence — 8 файлов
  `evidence/release-25890/**`.
* Деплой-артефакты ПОСЛЕ FIX-DEPLOY-90 (пере-биндинг ре-ревью):
  `deploy_25890.py` sha256_12 **`2d47290eeeb0`**, `rel90_final.sh` sha256_12
  **`c4e74d87e477`** (до-фиксовые `619bb9f59c543b83`/`0bf51a7d2e7fb3a2` —
  история NF ниже; `deploy_25890_orig.py` == до-фиксовой версии по sha).
* На момент ревью `origin/master` = `829e39d1` (bump ещё НЕ запушен) → B3
  fail-closed сработает до пуша — предусловие реально.

## 1. Линия версий — подтверждена

* master до бампа: `config/settings.py` APP_VERSION = **2.58.83** (прод =
  2.58.89 @ `d59fab94`, ветка `release/fix-2.58.89`) → бамп на **2.58.90** =
  следующий номер после прода; прецедент подтверждён (`9d8aeaf9`: 2.58.81→
  2.58.82 тем же набором «settings + README + meta + 24 py + 4 JS = 31»);
  `2.58.90` ранее не использовался.
* Бамп-коммит `f2cd3a71` = ровно **31 файл** (+33/−33): `config/settings.py`,
  `README.md`, `plans/docs/param-registry-round1025.meta.md` (APP_VERSION
  `2.58.90`, HEAD `01e1cc8d`), **24 py-пина** и **4 JS-пина** (regex-пины
  `APP_VERSION = "2\.58\.90"`). Спот-проверка 11 позиций (4 py + 4 js +
  settings + README + meta) — все несут 2.58.90; пересчёт 24/4/31 — сходится.
* Старых версий в runtime/тестах/инструментах не осталось: `2.58.83/2.58.88/
  2.58.89` встречаются только в `plans/**` (история/эвиденс).

## 2. Дельта-доказательство — подтверждено

* Дельта `d59fab94..HEAD` без `plans/` = **74 файла** = 30 bump (все 30 вне
  `plans/`) + 44 P0 (18 runtime payload + 23 теста + 2 инструмента +
  `AGENTS.md`) — пересчитал пофайлово, состав совпадает с отчётом.
* **19 runtime-отличий** = 18 payload + `config/settings.py`; RUNTIME_WHITELIST
  скрипта == фактической дельте (точное равенство, 19/19). Fingerprint (20
  записей, вкл. meta; README — отдельной строкой) — **20/20 sha256_12 совпали
  с рабочим деревом**; рабочие runtime-файлы дерева == HEAD (чистые).
* Sanity-файлы вне дельты и совпадают с заявленными хешами: fullscreen-policy
  `96db06425079`, glass-refraction `6a09d962d59d`, prompt_registry
  `a606bcafc1be`, image_generation `db1d60cd4b54`, worker_budget
  `e18dab826da1`, tool_router `70840e163e17` (6/6).
* EXPECT12 скрипта — **30/30 пар** совпали с деревом кандидата.

## 3. Числа кандидата — подтверждены; флейк разобран мной независимо

* `pytest-full.txt`: **14240 passed / 9 failed** (628.71s). 8 из 9 — те же
  пре-существующие, что в `persist-fix/full-suite-post-fix.txt` (asap7_direct_
  settings ×2, mca01_tx ×1, t5150 ×5); исторический `mca12 js_ui_suite` в этом
  прогоне **зелёный** (закрыт `3e044c8a`).
* Флейк `test_handle_initiative_sent_single_transport_chunks`:
  — тест и ассерты P0-коммитами **не менялись**: функция байт-идентична
    `8c88bbda`↔HEAD (единственная правка файла — no_chat-хунк снапшот-теста в
    `f0bd29e2`);
  — метод зонда `probe_flake.py` валиден (повтор сценария теста с теми же
    хелперами, проверка `attempts==1/status==deferred`, 100 итераций с чистыми
    tmp-БД); логи evidence подтверждают N=100: база `8c88bbda` 5/100, HEAD 6/100;
  — **мой перепрогон**: N=40 → 0 fails; N=120 → **3 fails (2.5%)**, все ровно по
    задокументированному механизму (`dec.intent_id=None`, attempts=0,
    2× status=sent chunks=3, 1× silent) — тот же класс, что я независимо
    трассировал в P0A-леджере (draw mca-10b подменяет durable-intent
    form-кандидатом). Вероятностный, не блокер; follow-up «пин draw в тесте»
    корректен.
* **Перепрогоны (мои, в свой scratch)**: js-sweep `node tests/js/*_test.js` →
  **87 файлов / 0 падений**; UX e2e `tests/ui_p0a_ux_speech_compact_e2e.py` →
  **failures=0, POST=21**; W6 `tools/ui_soul1_w6_speech_e2e.py` (обёртка с моим
  каталогом) → **failures=0, POST=16, shots=94** — всё сходится с evidence.

## 4. Релиз-док — точен; две формулировки требуют уточнения (NF-2/NF-3)

Состав (4 линии + коммиты), риски §6, откат §5 и чек-лист §4 a–e по существу
исполнимы без домыслов: (a) healthz 2.58.90/loopback+HTTPS, NRestarts=0,
MAINPID, журнал since T0, миграции/user_version; (b) 10-шаговый real-DB цикл по
типам настроек + изоляция чатов + инъекции 409/503; (c) nostalgia live (точный
journal-маркер, воронка, `nostalgia_log`, `mca_events`, per-chat gate
`-1004482340693`); (d) initiative live (`scan_anchored≥1`, writer/recheck/sent
или честная причина, lag, `/api/status`); (e) smoke-маршруты + байт-эквивалент
served-файлов + оси `.env` + регрессионные маркеры.

## 5. Деплой-скрипт (офлайн-аудит) — найденные дыры

Проверено и в порядке: fail-fast (T0-fail → откат; B3 fail-closed до checkout;
abort до рестарта), ровно один SSH-коннект на режим (recon 15 c; main — один;
SFTP в том же сеансе), без ретраев после auth-fail (единственный `connect`,
единственный fetch-fallback в том же сеансе без цикла), креды не печатаются
(scrub + команды не логируются, askpass-файл удаляется), авт-откат
`release/cfg1-2.58.88` при неполучении healthz 2.58.90, BUMP-ancestor gate
через origin/master, вайтлист 19/19, EXPECT12 30/30, пост-рестарт проверки
(healthz/T0/journal/G-served/J-final с миграциями и user_version).

**NF-1 (обязательная, малая, скрипт). Прод-дерево при abort не возвращается к
пред-релизному состоянию.**
   * `checked_out=True` выставляется только при полном успехе C. Если checkout
     УДАЛСЯ (CO_RC=0), но не прошёл whitelist/`TRACKED_MOD_AFTER` — abort без
     `_tree_restore`: дерево остаётся на `origin/master` (неверифицированный
     кандидат), процесс работает старым кодом → следующий рестарт поднимет
     неверифицированный кандидат.
   * `_tree_restore` (путь D-abort) откатывает дерево на `ROLLBACK_BRANCH`
     (2.58.88), тогда как прод до релиза = 2.58.89 (`d59fab94`) → тихий
     downgrade на следующем рестарте. В `deploy_25889.py` этот путь был
     корректен (PROD_REF тогда и был 2.58.88); клон потерял это свойство.
   * Мини-правка: (i) ставить `checked_out=True` сразу после CO_RC=0; (ii) в
     `_tree_restore` использовать `PROD_REF` (`d59fab94`, либо ветку
     `release/fix-2.58.89`) вместо `ROLLBACK_BRANCH`; (iii) при TR_RC≠0 —
     явный предупреждающий вывод «дерево требует ручного восстановления».
   * Recheck: офлайн-дифф логики (таблица «шаг → состояние дерева»), без
     прогона на проде.

**NF-2 (малая, док+скрипт). `PAGE_VER`/`SUBST_CSS` — это счётчики строк.**
`sh rel90_final.sh <T0> 2.58.90` печатает `PAGE_VER=<число строк с ?v=2.58.90>`
(ожидание **15**) и `SUBST_CSS=2` — как в 25887–25889; формулировка отчёта
«PAGE_VER = 2.58.90» может быть прочитана как ожидание значения 2.58.90.
Уточнить в §4(e): «PAGE_VER=15 (все подстановки `?v=2.58.90`), SUBST_CSS=2»;
опционально — добавить в G-шаг явные маркеры `SERVED_EQ=SAME/DIFF` (сейчас
SERVED/DISK печатаются, но не сравниваются автоматически).

**NF-3 (малая, док). §5 отката:** ветка `release/cfg1-2.58.88` сейчас указывает
на `35789982` (= `c37b8577` + docs-коммит отчёта; runtime 2.58.88 идентичен).
Указать в доке ветку (tip) или оговорить, что cited `c37b8577` — bump-коммит,
а checkout идёт по ветке.

Неблокирующие заметки: (i) B3-ancestor + C-вайтлист + EXPECT12 уже покрывают
runtime-безопасность деплоя `origin/master` — строгая ти-равность не нужна
(docs-коммиты сверху штатны: сам отчёт `9286ed0e`); (ii) дрейф-скоуп A/C
(`config services web handlers`) не включает `bot.py` — при желании добавить
его или сверять `OLD_HEAD==PROD_REF`; (iii) PID-анкерный migration-wait из
25889 не перенесён: F3 теперь анкорится версией в healthz (новый код
обслуживает), миграции выполняются в `on_startup` до обслуживания, Δ DDL=0,
J печатает migration-строки и `user_version` — приемлемо; (iv) аргумент режима
не валидируется (неизвестный режим = main-путь).

## REV-REL-RECHECK — после FIX-DEPLOY-90 (моим исполнением)

Дельта скриптов: `deploy_25890.diff.txt` (+121/−20), `rel90_final.diff.txt`
(+10/−5); `deploy_25890_orig.py` == моей ранее ревьюенной версии
(sha256_16 `619bb9f59c543b83`) — база диффа верна. Ниже — результаты.

1) **NF-1a/b — закрыто.** `checked_out = True` ставится сразу после
   `CO_RC=0` (до проверок whitelist/TRACKED_MOD) → guard
   `if abort is not None and checked_out: _tree_restore(abort)` теперь
   срабатывает на ВСЕХ abort'ах после успешного checkout. `_tree_restore`
   целится в `release/fix-2.58.89` (fallback `git checkout --detach
   d59fab94`) и подтверждается тремя условиями: `TR_RC=0` +
   `TR_RUNTIME_DRIFT=0` (дифф дерева к `d59fab94` по
   config/services/web/handlers) + `TR_TRACKED_MOD=0`; иначе WARNING.
   Офлайн-симуляция 22/22 (orig RED / fixed GREEN): s1/s2/s2b/s3/s4/s5 —
   TR=True target=PROD; s6 (до checkout) и s7 (успех) — рестора нет
   (корректно); s8/s9 — штатный откат `_rb` (2.58.88) после рестарта;
   **я перепрогнал `sim_abort_paths.py` в своей копии — FAILURES: 0, таблица
   совпала построчно**.
   **s10_restart_rc_fail** (`systemctl restart` rc≠0, наследовано от 25889):
   оставить как есть — слепо рестартовать/откатывать при неопределённом
   состоянии сервиса опаснее; запуск под надзором, abort виден сразу. Опция
   (не блокер): добавить в текст abort'а подсказку «проверь состояние юнита и,
   при необходимости, выполни откат вручную».
2) **NF-1c — закрыто:** при неподтверждённом ресторе — `!! WARNING` в месте
   срабатывания + `WARNINGS-SUMMARY (N): …` в конце (сработало в s4/s5;
   harness дополнительно сверяет `warning_summary == warning`).
3) **NF-2/NF-3 — закрыто, патч релиз-дока применён этим коммитом.**
   `EXPECT_PAGE_VER=15`/`EXPECT_SUBST_CSS=2`; G-шаг печатает
   `SERVED_EQ_APP_JS/CSS=SAME/DIFF` и `PAGE_VER`/`SUBST_CSS` через
   `grep -cF`. Проверка по байтам кандидата (моя): index.html — ровно
   **15 строк** `?v=__APP_VERSION__` (3 CSS-link L21/L24/L27 + 12 script
   L11400…L11435) → после подстановки `_render_index` PAGE_VER=15; app.css —
   **2 строки** (L160 комментарий, L168 `@font-face` url) → SUBST_CSS=2;
   `web/app.py::_render_index/_render_app_css` существуют и обслуживают
   маршруты. NF-3: tip `release/cfg1-2.58.88` = `35789982` (= c37b8577 +
   docs, runtime идентичен); `release/fix-2.58.89` tip = `3dfb48ef`
   (= d59fab94 + plans-only). Все три блока патча применил; плюс добавил в §7
   строку ревью-биндингов (sha12 скриптов + симуляция 22/22).
4) **Сверх-правка (точное равенство множеств вайтлиста) — корректна.**
   Разбор `DELTA_RUNTIME:` строки + `sorted(rt_files) != sorted(whitelist)`.
   s2b (лишний `web/zzz_rogue.js`): orig проходил (rc=0 — подстроковая
   проверка молча пропускала лишний runtime-файл), fixed — abort+restore
   (rc=2). s7 (нормальный путь) — без ложных срабатываний (rc=0, рестора нет);
   мой `check_delta_logic.py`-эквивалент (равенство множеств «19 == 19»)
   подтверждаю по коду.
5) **Таблица 22/22** — выборочно сверил s1 (D-mismatch → TR к PROD),
   s2 (delta missing → abort + TR), s2b (лишний файл: orig rc=0 → fixed
   abort+TR), s3 (tracked mod → abort + TR), s8 (healthz fail → RB 2.58.88,
   без TR) — совпадает с кодом и моим прогоном.

Остаток (не блокер, прежний): исключение между успешным checkout и guard'ом
(скажем, таймаут SSH/SFTP) не вызывает `_tree_restore` — обернуть
пост-checkout секцию в try/except было бы belt-and-braces; вероятность мала.

## Вердикт

**Approved.** NF-1a/b/NF-1c/NF-2/NF-3 закрыты в `deploy_25890.py`
(`2d47290eeeb0`) и `rel90_final.sh` (`c4e74d87e477`); сверх-правка
вайтлиста корректна; мой независимый перепрогон abort-симуляции 22/22
(FAILURES 0); патч релиз-дока применён. Кандидат кода/эвиденс не менялся
(`f2cd3a71`). Деплой и push НЕ выполнялись: запуск — после push `master`
(B3-gate) и решения оркестратора.