# Release evidence — 2.58.89 (REL-25889: CFG-02A B1 + FIX-SPEECH-MOBILE)

Что это: пакет доказательств общего релиза **2.58.89** — CFG-02A («суточная
квота изображений: видима, управляема, реально влияет», кандидат `83ecd202`,
включая блокерный фикс B1) + «Речь и характер» на мобильном (кандидат
`720be161`, ревью `bf6208f5`).

| Роль | Значение |
|---|---|
| База (прод до релиза) | `c37b85779cc41ad716304024ebeea86ad4081071` = **2.58.88** |
| Ветка | `release/fix-2.58.89` |
| Порт-коммит (12 файлов) | `119b1f7d8e88bc4e697b74b8ddf1e8cebebd66d4` |
| Bump-коммит (31 файл) | `d59fab944bcb3eb0f5d3fa69101d8488da1c155b` — **деплой-тип** |
| Кандидаты | `83ecd202659c2e1a30b46f8548b0809e892b77a9` (CFG-02A+B1), `720be161` (speech) |
| Delta vs прод | **43 файла** = 12 payload + 31 bump; `UNCLASSIFIED = 0` |

## Изоляция

* `isolation-classification.txt`, `delta-files-with-stats.txt`,
  `delta-vs-base.txt` — delta 43 = 7 `cfg-02a-payload` + 3 `speech-payload` +
  2 `cfg02a+speech` (web/app.js, web/index.html) + 31 `bump-2.58.89`.
* `equivalence.txt` — `git diff 83ecd202 HEAD -- <7 CFG-файлов>` пусто;
  `git diff 720be161 HEAD -- <5 speech-файлов + 2 общих>` пусто;
  `git diff 2bc13f44 c37b8577 -- <все порт-пути>` пусто (прод == базе CFG-02A и
  speech по каждому порт-пути → порт несёт ровно эти фичи);
  `tests/test_webapp_js_unit.py` — проверен (прод-идентичен, checkout no-op).
* `soul-byte-equal.txt` — SOUL-рантайм byte-equal проду, кроме намеренных
  2.58.89-дельт: `web/app.js`, `web/index.html`, `web/static/app.css`,
  `services/image_generation.py`, `services/tool_router.py`,
  `services/worker_budget.py`.
* `wg-byte-equal.txt` — WG (fullscreen/glass) байт-в-байт.
* `hashes.txt` — sha256_12 ключевых файлов (head/prod/candidates);
  `secret-scan.txt` — 5 совпадений: 1 каталожный ключ (`keys.image_api_key`) и
  4 плейсхолдера-строки в тестах; реальных креденшелов нет.
* `preflight-frozen-check.txt` — frozen-проверка: polygon-блобы index.html и
  glass-якоря app.css сохранены, vendor-ассеты byte-equal, CRLF не вырос,
  CFG-01-файлы byte-equal, витринные/речевые маркеры == кандидатам,
  `record_voice_over` = 0 (глиф заменён на `edit_note`). RESULT: OK.

## Preflight (ветка = tip `d59fab94`, raw-логи в `preflight/`)

`preflight-summary.txt`:

| Проверка | Результат |
|---|---|
| `tests/test_cfg02a_image_quota_ui.py` | **27 passed** |
| `tests/test_speech_mobile_entry_contract.py` | **6 passed** |
| `tests/test_webapp_js_unit.py` | **38 passed** |
| `tests/test_soul1_capability_fallbacks.py` | **41 passed** |
| `node tests/js/round1024_image_module_test.js` | **IMAGE-MODULE-OK** |
| CFG-01 набор (direct_chat / concurrency / throttling) | **204 passed** (CFG-01 не сломан) |
| `tests/test_soul1_*.py` (30 файлов) | **600 passed** |
| parity | **13 passed** |
| registry `--check` | **CHECK OK: 575 == REGISTRY** |
| frozen-check | **RESULT OK** |
| node guards | **87/87** |
| `tests/ui_speech_mobile_entry_e2e.py` | **failures=0** (320/390/1280) |
| `tools/ui_cfg02a_image_quota_e2e.py` | **RESULT: PASS** |
| refraction e2e | **WG-REFRACT-E2E-OK** (37 проверок) |
| shell e2e | **W2-SHELL-E2E-OK**, `failed_checks {}`, `console_errors []` |
| fs e2e | **12/12 PASS** (скриншоты `preflight/fs-e2e/`) |

`preflight-cfg02a-e2e-shots-sha.txt` — 6/6 скриншотов CFG-02A e2e, заново
сгенерированных на ветке, **байт-идентичны** committed-скриншотам кандидата
(детерминизм).

## Деплой (1 recon + 1 main SSH-коннект)

Raw: `recon89.txt` (до выката: `c37b8577` / 2.58.88 / release/cfg1-2.58.88),
`deploy-run.txt` (A–J), `final-verification.txt` (read-only J-фаза).

* 2026-10-18 07:36:52–07:37:49Z. T0-hardened `deploy_25889.py` (клон
  отревьюенного `deploy_25888.py`): A — прод 2.58.88, `TRACKED_MOD=0`,
  `MAINPID=3275019`, оси 5/5; B/C — fetch+checkout `release/fix-2.58.89`,
  `NEW_HEAD=d59fab94…`, `TRACKED_MOD_AFTER=0`, `DELTA_FILES=43`;
  D — **25/25 sha256_12 == кандидатам**, маркеры CFG-02A/speech/CFG-01,
  `APP_VERSION = "2.58.89"`, F8-meta HEAD `119b1f7d`.
* F — graceful-рестарт `RESTART_T0=2026-10-18 07:37:01`; PID-анкер: новый
  `MAINPID=3359708`, `migrations: complete | user_version=36 | pending=[]`;
  **healthz 2.58.89**; журнал since T0: **ERR=0**, RUNTIMEWARN=0;
  `NRestarts=0`, `ExecMainStatus=0`. Автотриггер отката не срабатывал.
* J — `PAGE_VER=15`, `SUBST_CSS=2`, served app.js/app.css sha12 совпадают с
  диском (`2757a25d663d` / `d6b848cdecd0`), оси `.env` 5/5, SOUL gates 10/10,
  HTTPS healthz 2.58.89, `/web/` 200.

## Пост-проверки (живые, read-only)

`post-check.txt` — `release89_post.py` (admin-initData in-process; **0 записей**
в настройки владельца): **SUMMARY ok=17/18**.
а) `/web/` 2.58.89 ×15; served app.js `2757a25d663d`, app.css `d6b848cdecd0`;
`/static/app.css` (маршрут с подстановкой) ×2.
б) речевой вход: в отданной странице `data-speech-hub-entry` ×1, «Речь и
характер» ×6; в app.js `hubSpeechEntry` + `#/ai/speech` ×7.
в) витрина квоты: `data-image-quota-facts` ×2, «Лимиты генерации» ×1,
«Изображений в сутки» ×2; `imageQuotaFacts`/`saveImageDailyLimit`/
`imageQuotaValueValid` в app.js; `GET /api/config` → `limits.image_daily_limit`
= **60** (источник пуст = глобальное владельческое значение), DM-чат = 60.
г) SOUL gates **10/10 ON** (`/api/speech/overview`).
е) CFG-01 read-only: global burst = **10**, cooldown = **300.0**; DM-чат
наследует 10/300 — механика не сломана.
f3 (информационная, единственная False): `GET /api/workers/budget` вернул
глобальный shared image-бюджет (used=4, limit=200, source=env), но **без
записи для DM-чата** (у чата нет строк расхода за сегодня) → поле
`image_usage` отсутствует; это не дефект (UI показывает факты квоты из
`configItems` + бюджета, расход чата = 0 при отсутствии строки).

Прод-байты (live HTTPS, `prod-payload-bytes.txt`): `/web/app.js`,
`/web/static/app.css` и `/web/` (подстановка `?v=2.58.89`) — **byte-identical**
дереву релиза.

## Мобильный probe (соответствие (б) брифа)

* `post-prod-bytes-entry-e2e.json` + `post-entry-e2e-console.txt` — тот же
  отревьюенный e2e-контракт, но **webroot = прод-байты**: `failures=0` на
  320/390/1280; на хабе «ИИ» вход `[data-speech-hub-entry]` видим
  (h=155@320, h=134@390), клик → `#/ai/speech`, экран «Речь и характер»
  с 3 карточками разделов. Скриншоты: `post-prod-bytes-320-hub.png`,
  `post-prod-bytes-390-hub.png`, `post-prod-bytes-390-speech.png`
  (реальный Chrome, device-метрики 390×844 @2x).
* Живой origin вне Telegram: `post-prod-live-390-playwright.png`,
  `post-prod-live-320-playwright.png`, `post-prod-live-390-bu.png` — страница
  2.58.89 (15 маркеров) и auth-гейт «Миниапп открыт без Telegram-контекста»;
  хаб без initData не рендерится (ожидаемое поведение, не дефект релиза).
  Интерактивная проверка двери **внутри Telegram — owner-check**.

## Остаток

* Интерактивная проверка «Речь и характер» и квоты **внутри Telegram** —
  owner-шаг (initData).
* 6 live-строк CFG-02A (`READY_FOR_LIVE`) закрывает леджер отдельно; карты в
  этом релизе не менялись.

Rollback: `release/cfg1-2.58.88` (`c37b8577…`), Δ DDL = 0
(user_version=36 не менялся); авто-откат в скрипте не потребовался.
