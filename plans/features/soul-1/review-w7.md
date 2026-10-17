# REVIEW-W7 — независимое адверсариальное ревью слайса W7 (SOUL-12 fullscreen + SOUL-13 хвосты v6.3)

| Поле | Значение |
|---|---|
| Кандидат | рабочее дерево поверх `ba65cbd3f47919857d272c39cab7e9eda97742fa` (фактический HEAD репо на момент ревью — `9d8da1d7`, docs-only; дифф web/services/tests идентичен; файлы W7: mtime 18.10 00:38–01:09) |
| Отчёт Builder | `plans/features/soul-1/w7-v63-baseline-report.md`; evidence `plans/features/soul-1/evidence/w7/**` |
| Verdict | **Needs Fixes** — 1 блокер (F1), остальное verified; блокер мелкий и локальный |
| Ревью выполнил | REVIEW-W7 (read-only, свои прогоны/мутации; вердикт-файл не коммичен) |
| Дата | 2026-10-18, время среды |

**Что сделано простыми словами (итог):** полноэкранный пробел закрыт правильно — кнопка больше не пропадает молча, владелец на Telegram Desktop видит понятное объяснение и точную инструкцию BotFather (Full/Compact), на поддерживаемом клиенте не появляется ничего лишнего, вне Telegram объяснение не навязывается; политика и диагностика не текут секретами; полигон/стекло не тронуты. Единственная претензия: в технической диагностике поле «Launch params» в реальном клиенте Telegram всегда будет пустым («—»), потому что параметры приходят в hash URL, а код читает query-строку.

---

## Блокирующая находка

### F1 — `diagnostics().launchParams` не увидит launch-параметры в реальном клиенте (hash vs search)

- **Требование:** SOUL-12.3/§13 («Записывать для воспроизведения: platform, SDK version, **launch params**, …», матрица «запуск из кнопки и direct deep link»); отчёт §2/§4 обещает `launchParams` («публичные `tgWebApp*` из URL»).
- **Где:** `web/static/fullscreen-policy.js`, `_launchParams()` — читает только `window.location.search`.
- **Факты:**
  1. В репозитории вендорный официальный SDK: `web/static/vendor/telegram-web-app.js` — `var locationHash = location.hash.toString(); var initParams = urlParseHashParams(locationHash);` и далее `sessionStorageSet('initParams', initParams)` (ключ `__telegram__initParams`).
  2. Внешнее подтверждение: docs.telegram-mini-apps.com → «Launch Parameters»: «Telegram client environment sends data to the Mini App through the URL's hash»; `tgWebAppPlatform`/`tgWebAppVersion` — always present.
  3. Свой репро (Playwright, реальные `web/index.html`+`app.js`+политика, мок-SDK tdesktop): открытие `http://127.0.0.1:8830/#tgWebAppPlatform=tdesktop&tgWebAppVersion=8.0&tgWebAppStartParam=deep1` →
     `launchParams_from_policy = {tgWebAppPlatform: null, tgWebAppVersion: null, tgWebAppStartParam: null}`, при `location_search: ""`, `location_hash_now: "#/"` (приложение заменяет launch-hash на `#/` через `replaceState` — см. `web/app.js` `created()`), при этом `platform=tdesktop`, `sdkVersion=8.0` (из SDK) корректны.
  4. В стрипе это строка «Launch params: — / v—»; в mock-e2e/unit-тестах это не ловится (в тестах параметры вообще не в URL).
- **Влияние:** в живом клиенте владелец не получит обещанные «launch params» — в частности `tgWebAppStartParam` (различение запуска из кнопки vs deep link, чек-лист §8 A5). Ложного успеха нет (честные «—»), секретов нет (allowlist цел), но пункт явного перечня SOUL-12.3 не выполняется там, где он единственно значим.
- **Минимальная правка (1 файл):** в `_launchParams()` дополнительно к `location.search` читать (a) `location.hash` (без `#`, тот же разбор `k=v&…`) и (b) `sessionStorage.getItem('__telegram__initParams')` (JSON, его пишет официальный SDK; брать ТОЛЬКО allowlist-ключи `tgWebAppPlatform/tgWebAppVersion/tgWebAppStartParam` — `tgWebAppData` не выносить). Порядок источников: storage → search → hash (или фиксировать hash на `init()`).
- **Перепроверка (маленькая):** node-сторож + одно новое утверждение (hash-вход → `diagnostics().launchParams.tgWebAppPlatform === 'tdesktop'`), и в mock-SDK e2e посеять `__telegram__initParams`/URL с hash-параметрами и убедиться, что строка стрипа показывает `tdesktop / v8.0`. Затем повтор моего репро: поле заполнено, секретов в blob нет.

---

## Приёмка по клаузам (ledger этого ревью)

| Клауза | Статус | Чем подтверждено (мои прогоны, если не указано иное) |
|---|---|---|
| SOUL-12.1 «кнопка не пропадает молча; объяснение + точный следующий шаг» | VERIFIED локально; живая половина LIVE_UNVERIFIED | Свой RED на снимке HEAD (`git archive HEAD web`): `hasExplain=false, hasDiagnostics=false, stripPresent=false, toasts=[], bodyMentions.BotFather=false` при `data-fs-reason=tdesktop_disabled_until_e2e` → GREEN S1 33/33; Browser Use: стрип + BotFather-инструкция видимы, ⛶ отсутствует, вызовов SDK нет |
| SOUL-12.2 «три операции разделены; нет WinAPI/moveTo/resizeTo; expand() — не замена» | VERIFIED локально | node-сторожа (негативы 5.3b/5.3c: `__calls==[]`; regex-запреты moveTo/resizeTo/expand-фолбэк) |
| SOUL-12.3 «факты воспроизведения, включая launch params» | **FAILED (только launch params)**, остальное VERIFIED | F1; состав `diagnostics()` (32 ключа) и отсутствие секретов — свой blob-скан (`hash=audit`, user id, `initData=`, `token`, `Bearer` — не найдены) |
| SOUL-12.4 «поддерживаемый клиент — enter/exit; неподдерживаемый — объяснение и безопасный workflow; native ✕» | VERIFIED локально; «визуально подтверждённый fullscreen» LIVE_UNVERIFIED | S3 8/8 (кнопка 48×44, 1 request + ack, стрипа нет); S1/S2 — объяснение+workflow; негативы 5.1/5.3 |
| SOUL-12.5 «моки — не приёмка; safe area; без jump; без DOM в шапку Telegram; полигон не тронут» | VERIFIED локально + live-open | S1 headerRect стабилен (y/h), S5 320/390 без h-overflow; в диффе `web/static/` только `fullscreen-policy.js`; мутация base64-блоба полигона → DIFF-DETECTED |
| SOUL-12.0 «не закрывать без живого подтверждения» | READY_FOR_LIVE (чек-лист §8) | отчёт не объявляет DONE; чек-лист покрывает Desktop Win (Compact/Full/Fullscreen, кнопка/deep link), Android portrait/landscape, Web/standalone, Launch Mode=Fullscreen |
| SOUL-13.0/13.1 (baseline v6.3 + видимый реестр) | VERIFIED | `v63-baseline-record.json` + `v63-live-gates-ledger.json`; мой set-свер: 65 required-open строк = ledger 1:1 (42 READY_FOR_LIVE / 18 BLOCKED / 5 PENDING), sha256 карты совпал; карта v6.3 не редактировалась (mtime 16.10 23:36) |
| SOUL-13.2 (стенд недоступен анониму) | VERIFIED локально; прод-проба = READY_FOR_LIVE на новом кандидате | своя проба: 7 путей → 404, боевые (`/static/glass-probe.js`, `glass.js`, `lg-lens-map.png`, `/web/`) → 200; файлы стенда живут в `tests/glass-teststand/**` (tracked); прод-404 из `evidence/release-25883/ev_deploy_run.txt` — другой кандидат (`448cc81a`) |
| SOUL-13.3 (14 pending → реестр без «закрытий») | VERIFIED | «14» = историческое состояние; текущие числа сверены с рабочей картой, ни одна строка не переименована |
| SOUL-13.4 (различение primary: hot/env/absent, дегенерация, WARN, без секретов) | VERIFIED (код+тесты+UI); провайдерский reset horizon — OPEN (честно) | мои прогоны: 97 passed; свои мутации 5/5 KILLED; проба приоритета (оба слоя заданы → hot); тест-гэп N2 |
| SOUL-13.5 (git-evidence, `225c3c2b`, deployed SHA) | VERIFIED | три артефакта tracked/clean (blob-сверка: `104faae2adba`/`adc9aa19a632`/`de0dfd151384`); `225c3c2b` — реальный docs-only коммит, предок `origin/master` (`git merge-base --is-ancestor` = 0), родитель `736a8834`; цепочка `c2775a54 → 6d4b9a7d → 448cc81a` существует |
| SOUL-13.6 (6 pytest) | VERIFIED | свой прогон 6/6 PASS на `.venv` (aiogram 3.31.0, trafilatura 2.2.0); `py -3` (aiogram 3.29.1) воспроизводит `ImportError: InputRichMessageMedia` и `lxml.html.clean`-ImportError; `lxml_html_clean` есть в requirements.txt |

## Не-блокирующие замечания

- **N1 (evidence hygiene).** `pytest-embedding-suites.txt` в evidence содержит `1 failed, 96 passed` (след до ре-пина), тогда как отчёт ссылается на него как на «97 passed». Мой прогон сейчас: **97 passed** — утверждение верно, но артефакт не перегенерирован. Перезапустить прогон в тот же файл.
- **N2 (тест-гэп).** Инвариант «hot перекрывает env, когда заданы оба слоя» не защищён ни одним утверждением: моя точная мутация (env выигрывает при непустом env, hot-путь сохранён) **SURVIVED** 76 тестов embedding-набора. Код ведёт себя правильно (проба: primary=HOT-KEY, `key_source='hot'`). Достаточно одного assert. Заявленная мутация Builder M5 грубее (hot перестаёт читаться) и потому её KILLED сам по себе корректен.
- **N3 (binding).** В отчёте §1 указан HEAD `ba65cbd3`, а `v63-baseline-record.json` фиксирует `head=9d8da1d7` (docs-only descendant; дифф web/services/tests идентичен — проверено). Родителю: биндить W7 к фактическому коммиту, который будет создан.
- **N4 (расширение области, оправдано).** План отдаёт W7 только `web/static` + запрет «nothing else touches static JS/CSS»; фактически добавлены аддитивные UI-вставки в `web/index.html` (+50/−1) и `web/app.js` (+43/−0). Это оправдано acceptance SOUL-12.4/13.4 (показать владельцу объяснение/состояние нечем иначе) и явно задекларировано в §4.1; регрессий W6 не нашёл (node-сторожа шелла/роутинга зелёные, смоук 5 маршрутов без pageerror, периметр зелёный). Процедурная заметка PM, не дефект.
- **N5 (pre-existing).** Дубли ключей `_prefersReducedMotion` в `web/app.js` (7 вхождений и в HEAD, и в рабочем дереве; сторож печатает WARN, проходит). Диффом W7 не добавлены.
- **N6 (чужие грязные файлы).** `tools/_ui_mca12_stories_e2e.json` (+3/−3) и 12 PNG в `w2-evidence-fullscreen/` — чужие незакоммиченные правки (mtime 15–17.10, до W7 18.10 00:38); в отчёте задекларированы, лейном не трогались.
- **N7.** На Windows-десктопе тост-объяснение показывается при каждом открытии Mini App (дедуп — в рамках страницы); это задумано (стрип — постоянный канал). Отметить владельцу, чтобы не удивлялся.
- **N8 (pre-existing).** `.playwright-mcp/` и мусорные untracked-каталоги в репозитории — вне W7.

## Что я проверил сам (не переиспользовано)

`node tests/js/*` → 86/86; периметр `-k webapp/ia_/soul1/round1025/round1024/ui_/glass/persona/prompt/registry/catalog` → **3915 passed / 0 failed**; embedding-набор (4 файла) → 97 passed; 6 ранее падавших + стенд-сторож → 11 passed; RED на снимке HEAD и GREEN-харнесс S1–S5 (55 проверок) + свой скан секретов; реплей v6.3 S1–S8 → 7/7 (70 проверок); смоук 5 маршрутов; проба стенда (7×404, 4×200); мутации: JS 5/5 KILLED (тихий tdesktop, секрет в diagnostics, лишний DOM, подменённая инструкция, clickResult), стекло-блоб DIFF-DETECTED, harness-мутация «стрип на supported» KILLED (S3); embedding-мутации 5/5 KILLED (+ выжившая E4-lite = N2); LF-проверка (CRLF=0 во всех 8 файлах); git-сверки (ancestry, blob, deploy-цепочка); Browser Use — реальный Chrome: tdesktop (стрип раскрыт, 320px), android 390 (кнопка 48×44, стрипа нет), tdesktop+Launch Mode=Fullscreen (тост+стрип, `__calls==['exitFullscreen']`).

Переиспользовано (с проверкой содержимого): ledger/baseline JSON (сверены с картой v6.3 и git-фактами), прод-проба 404 release-25883 (другой кандидат — честно помечена), скриншоты Builder (у меня свои). Внешний источник: docs.telegram-mini-apps.com «Launch Parameters» (hash-транспорт) — для F1.

## Живая граница (передаётся родителю)

Живое подтверждение SOUL-12 (реальный Telegram Desktop Windows после деплоя) — только у владельца по чек-листу §8; локально это доказать нельзя. Прод-проба стенда (SOUL-13.2) должна быть повторена на новом задеплоенном кандидате; reset horizon эмбеддингов — внешний факт провайдера; `.env EMBEDDING_API_KEY` — решение владельца (в v6.3-пробе документально подтверждено отсутствие в `.env`, primary из hot-конфига).
