# Раунд 10.16 — ревью эпика (F1–F5 + UPD2). Step 5 @Reviewer

> **Ревьюер:** @Reviewer (Senior Principal Engineer / QA / Validator / Security).
> **Дата:** 14.09.2026. **Baseline:** HEAD `18a9aa1` + рабочее дерево (незакоммичено).
> **Объём:** 5 фич (T-1625…T-1665) + UPD2 (`plans/current_task.md:148-153`).
> **Правило:** значения секретов не приводятся (R17).

## 0. Вердикт

# ❌ Rejected

Код отклонён. Валидатор зелёный (5910 passed, JS-гейты чистые, Δ=0), но в F4
заложен **прод-ломающий дефект**: CSP `script-src 'self'` без `'unsafe-eval'`
запрещает `Function()`, который **исполняет** рантайм-компилятор Vue — мини-апп
перестанет монтироваться. Тесты этого не ловят: F4 DoD-пункты «мобильный smoke»
и «CSP-прогон» заменены на статические строковые маркеры. Дополнительно F1
объявляет «R17-скан чист», оставляя логирование URL в самом файле фичи, а F2 не
гарантирует доставку канона (требует ручного reset), при том что README уже
рапортует о невыполненной ротации SSH.

## 1. Контракт: задачи и открытые гейты

Builder-задачи во всех 5 `tasks.md` отмечены `[x]` — подтверждено.

| Фича | Builder `[x]` | Открытые гейты (осталось владельцу/DevOps/PM) |
|---|---|---|
| F1 `download-fix` | T-1626…T-1632 ✅ | `T-1625` (architect-гейт, в `tasks.md:62` `[ ]`, спека объявляет закрытым), `T-1633` (reviewer; строка **задублирована** — `tasks.md:70-71`) |
| F2 `guide-delivery` | T-1635…T-1640 ✅ | `T-1634` (architect; `tasks.md:68` `[ ]`), `T-1641` (reviewer) |
| F3 `audit` | T-1643…T-1649 ✅ | `T-1642` (architect/PM; `[ ]`), `T-1650` (gate) |
| F4 `miniapp-mobile` | T-1652…T-1656, T-1658 ✅ | `T-1657` (@DevOps, Caddy/DNS), `T-1659` (@Reviewer) |
| F5 `security` | T-1660, T-1662, T-1663 ✅ | `T-1661` (@DevOps — ротация), `T-1664` (@DevOps/@PM — деплой), `T-1665` (@PM) |

**Вывод по контракту:** гейты не закрыты, но это ожидаемо для Step 5. Однако
DoD F2/F4/F5 не могли быть выполнены в полном объёме (см. ниже), а статус
`🟢 IMPLEMENTED` в `tasks.md` F4/F5 — преждевременный.

## 2. Проблемы по severity

### Critical

**[Critical] CSP `script-src 'self'` ломает Vue (рантайм-компилятор требует `'unsafe-eval'`)**
- Файл: `web/app.py:35-48` (`_CSP_HTML`)
- Связки: `web/index.html:2900` (self-host **full-сборка** `vue.global.prod.min.js`),
  `web/app.js:5716` и `:5778` (`template: '#kv-editor-tpl'` / `'#list-editor-tpl'`),
  `web/app.js:5784` (`app.mount('#app')` — in-DOM шаблон `web/index.html:25`).
- Доказательство: в `web/static/vendor/vue.global.prod.min.js` присутствует
  рантайм-компилятор `s=Function(l)()` (вызов конструктора `Function` в
  `compileToFunction`; ровно тот же запрет CSP, что и для `eval`).
- Почему это важно: под `script-src 'self'` без `'unsafe-eval'` вызов `Function()`
  бросает `EvalError` в момент монтирования → приложение не рендерится (белый
  экран + ошибка в консоли) на всех клиентах, включая Android WebView. Это
  **прямая регрессия** цели F4 («миниапп не запускается»), только причина теперь
  не DNS, а собственный CSP. Прод-ломающий отказ.
- Почему не поймано: F4 DoD-тесты №4 (mobile smoke) и №5 (CSP-прогон с
  Telegram-оригином) не выполнялись; `tests/test_smoke_round1016_miniapp_selfhost.py:67-76`
  и `tests/test_webapp_api.py::TestStatic` проверяют только строку заголовка и
  отсутствие `'unsafe-inline'`/`nonce-`, но не исполняют приложение и не тестируют
  `'unsafe-eval'`.
- Требуемый фикс (одно из):
  a) `script-src 'self' 'unsafe-eval'` в `_CSP_HTML` (осознанное ослабление;
     зафиксировать в ADR-1016-2 с обоснованием); **или**
  b) перейти на `vue.runtime.global.prod.min.js` и заменить оба `template:`-селектора
     и in-DOM `#app` на предкомпилированные render-функции (`h(...)`) — только
     тогда `script-src 'self'` корректен.
  Обязательно: добавить **реальный браузерный** smoke (Playwright/DevTools) в гейт,
  который ловит CSP-нарушения и монтирование — статических маркеров недостаточно.

### High

**[High] R17 не закрыт: логирование URL/`str(exc)` осталось в файле F1**
- Файлы/строки: `tools/video_downloader.py:439-440` (`direct downloaded | url=%s`),
  `tools/video_downloader.py:517-519` (low disk `| url=%s`),
  `tools/video_downloader.py:802-803` (`body unreadable: %s` — печатается `exc`),
  `tools/video_downloader.py:814-815` (`body=%s` — тело ответа cobalt).
- Почему важно: F1 §3 нормативно запрещает URL/`str(exc)`/секреты в логах, а
  DoD (`tasks.md:58`) и отчёт (`round10.16_audit.md:27,128`) заявляют «R17-скан
  чист». Signed/CDN-URL и query-токены — приватные; cobalt body может содержать
  исходный URL. Инвариант раунда нарушен. `tests/test_no_secrets_logging` в репо
  отсутствует — «скан» фактически не автоматизирован.
- Требуемый фикс: заменить эти 4 сайта на `error=<Class> reason=<reason>` /
  presence-поля без URL (по образцу уже исправленных `handlers/video_download.py`);
  добавить авто-тест (caplog) на `download_direct`/`_stream_to_file`/`_http_error`.

**[High] F2: доставка нового гайда в прод НЕ гарантирована (нужен ручной reset)**
- Файл: `services/config_cache.py:269-278`; `services/info_service.py:260-291`.
- Суть: авто-перезапись выполняется **только** если прод-текст нормализованно равен
  одному из `KNOWN_INFO_SNAPSHOTS` (`info_service.py:148` — там только
  `PREV_DEFAULT_INFO_TEXT`). Реальное прод-значение неизвестно; при любом ином
  тексте — `canon drift` и **никакой доставки** без явного
  `POST /api/info/reset-canon`. DoD `tasks.md:60` (`[ ]`) не закрыт.
- Владелец **разрешил force-overwrite** текущего гайда (условие задания) — код
  этого разрешения в себе не несёт: фактического reset в изменениях нет, только
  эндпоинт/кнопка. Деплой-шаг (@DevOps) обязателен, иначе UPD2 §2 остаётся
  невыполненным.
- Требуемый фикс: выполнить и зафиксировать в отчёте гейта T-1641 явный
  force-reset прод-значения (или добавить текст реального прод-слепка в
  `KNOWN_INFO_SNAPSHOTS`) с доказательством `canon_version==2` и `canon_drift==false`
  после рестарта.

**[High] README рапортует о невыполненной ротации SSH как о факте**
- Файл: `README.md` (раздел «Вход на сервер и секреты (R17)», строки ~72-74):
  «Публичный ключ лежит в `~/.ssh/authorized_keys`, `PasswordAuthentication no`…
  Парольный вход отозван/сменён».
- Факт: `plans/features/security-rotation-finalize-round1016/tasks.md:57,60`
  (`T-1661`, `T-1664`) — `[ ]`; чек-лист `ssh-rotation-checklist.md:11-18` —
  процедура «к выполнению». Ротация **не подтверждена**.
- Почему важно: security-документация утверждает, что пароль отозван, хотя он
  может быть жив. Владелец/DevOps могут пропустить обязательную ротацию (P0).
  Это неверный инвариант безопасности в репо.
- Требуемый фикс: переформулировать README в модальность «план/процедура»
  (или обновить статус на «отозван» только после отчёта @DevOps без секретов).

### Medium

**[Medium] Мёртвая ветка `_probe_error_phrase` для single-URL**
- Файл: `handlers/video_download.py:358-361`.
- `is_direct_media_url(urls[0])` здесь всегда `False` (direct-URL перехвачен ранее
  на `:280`), поэтому ветка `await message.reply(random.choice(_probe_error_phrase(...)))`
  недостижима. Живой код-путь только fallback; мёртвая ветка вводит в заблуждение.
- Фикс: удалить ветку или обосновать комментарием; при желании — покрыть тестом.

**[Medium] Несогласованность контракта `reason` при превышении размера**
- Файл: `tools/video_downloader.py:869-871` — `DownloadTooBigError(..., reason="stream_failed")`.
- Токен `stream_failed` семантически неверен для too-big и нестабилен относительно
  spec §3 (`direct_too_big`/`ytdlp_too_big`). Пользовательская фраза не страдает
  (классификация по классу), но «стабильность токенов» — часть ADR-1016-1 §4.
- Фикс: `reason="ytdlp_too_big"` (или отдельный `stream_too_big`) + тест.

**[Medium] `/edit_info` не ловит не-OSError/не-PGdown исключения `save_text`**
- Файл: `handlers/info.py:171-180`.
- Теперь `save_text` — async PG-only и может упасть любым исключением БД (например,
  обрыв соединения после прохождения `pg_available`). Пойманы только
  `ConfigCacheUnavailableError`/`OSError`; прочее всплывёт → сообщение пользователю
  не отправится (в web-роуте `web/api/routes.py:1108-1116` generic `except` есть,
  а тут нет). Асимметрия обработки.
- Фикс: добавить `except Exception` с безопасным логом и фразой (как в web-роуте),
  без утечки исключения в чат.

**[Medium] Отчёт-эвиденс содержит расходящиеся цифры**
- `plans/reports/round10.16_audit.md:12` — «5895 passed»;
  `plans/reports/round10.16_security_scan.md:133` — «5910 passed»; фактический
  прогон — **5910 passed**. Один из отчётов устарел.
- Фикс: синхронизировать цифры в `audit.md` (и в `plans/ARCHITECTURE.md:25`-блоке
  F3, где тоже 5895) с фактическим прогоном.

**[Medium] F4 DoD №4/№5/№6 не подтверждены (только статические маркеры)**
- `tests/test_smoke_round1016_miniapp_selfhost.py` — только проверки строк.
  Реальный mobile smoke, CSP-прогон и замер TTI (spec §8 тесты 4-6) не выполнены;
  в `tasks.md:80` это честно отмечено («реальный мобильный смоук — @Reviewer/@DevOps»).
  В сочетании с Critical-дефектом CSP это означает, что F4 фактически не проверена
  поведенчески.
- Фикс: реальный браузерный smoke в гейте T-1659 (см. Critical).

### Low

- **[Low] `download_env_summary` читает POT из `os.getenv`**, а cookies/proxy/cobalt —
  из `settings` (`tools/video_downloader.py:186-192`). Если `YTDLP_POT_PROVIDER`
  задаётся через `settings`, presence-диагностика может показать `absent`.
  Источник должен быть единым (`settings`).
- **[Low] `_normalize_quality` не валидирует диапазон**: `"-5"`/`"0"` проходят
  (`tools/video_downloader.py:783-789`), давая мусорный селектор
  (`_format_selector`). Вход ограничен callback'ами, но защита от мусора заявлена.
- **[Low] `split_prefix_anywhere(..., url_before)`** возвращает первое совпадение в
  порядке токенов реестра, а не по позиции (`services/command_prefix.py:87-99`),
  вопреки формулировке «первое вхождение». Практический риск мал (3–11 токенов).
- **[Low] `/static/vendor/tailwind.css` без `?v=`** (`web/index.html:19`) — при
  пересборке возможен stale-cache; `app.css` версионирован, Tailwind — нет.
- **[Low] `_render_app_css` не защищён** (`web/app.py:96-104`): при отсутствии
  `web/static/app.css` (чистый клон) `create_app` упадёт, тогда как монтирование
  `/static` в `web/app.py:238-242` аккуратно пропускается. Несогласованная
  устойчивость старта.
- **[Low] `tailwind.config.js:22` `safelist: []`** — заявлено «динамических утилит
  нет»; проверка показала, что все утилиты из `class="..."` присутствуют в
  `vendor/tailwind.css` (расхождений нет), но при появлении динамики риск
  возвращается. Документация есть — оставить как контроль.
- **[Low] `plans/features/download-fix-round1016/tasks.md:70-71`** — продублирован
  пункт `T-1633`. Косметика контракта.

## 3. Что подтверждено (по пунктам задания)

- **F1 контракт:** `services/tool_router.py:595-597` — `download(url)` без
  `"direct"`; `tools/video_downloader.py:349-372` — ветвление direct vs YouTube vs
  cobalt по URL; `_normalize_quality` (`:777-789`) — `None/""/auto/best/max/direct`
  → `max`, `1080p/1080/1080` → `1080`, мусор → `DownloadError(reason="invalid_quality")`
  до сети (подтверждено реальными тестами `tests/test_download_round1016.py:148-293`,
  не MagicMock-заглушками: вызывается настоящая нормализация и реальный `download()`).
- **F1 probe-fallback:** `handlers/video_download.py:346-362, 439-475` — одна
  bounded-попытка без меню, probe-fail и провал fallback кулдаун не жгут
  (`_download_without_menu` touch только после успеха), классифицированные фразы
  (`_fallback_phrases`). Env-preflight `tools/video_downloader.py:177-200` —
  presence без значений.
- **F1 R17 (частично):** новые/изменённые строки в
  `handlers/video_download.py`/`services/tool_router.py` чисты от URL —
  подтверждено caplog-тестами (`test_download_round1016.py:128-142,461-476`).
  **Но** см. High №2 — остаток в `tools/video_downloader.py`.
- **F2 canon_version/миграция/reset:** `services/config_cache.py:238-289`,
  `services/info_service.py:136-164,232-291`, `web/api/routes.py:1057-1147` —
  реализованы версионирование, нормализованное сравнение, идемпотентность,
  force-reset с `prev_html`, RBAC `edit_info`. Тесты §8 зелёные
  (`tests/test_guide_delivery_round1016.py`, `tests/test_info_service.py`,
  `tests/test_webapp_api.py::TestInfo`).
- **F2 PG-only write-path:** `info_service.save_text` не пишет `info_text.md`
  (`:232-258`); файл **не изменён** (в `git status` отсутствует). Write-path в
  tracked-файл устранён.
- **F3 FIX-ы реальны:** S10.13-6b (`services/database.py:3758-3768`), S10.13-13
  (`services/database.py:130-147`, делегаты в `dream_worker.py:910-915`,
  `summary_memory.py:70-79`), R10.15-10 (`services/command_prefix.py:61-99` +
  `handlers/youtube.py`/`web.py`), R10.15-11 (`handlers/youtube.py:175-186,219`).
  **R10.15-4:** `bot.py:743-761` — `dp.include_router(video_download_router)`
  вынесен из-под startup-гейта, **но позиция 4e и порядок роутеров не изменены**
  (4d Olya → 4e download → 5 Slava); горячий гейт перенесён в
  `handlers/video_download.py:246-248`, yield-условие —
  `handlers/direct_chat.py:113-127` (`download_available()`).
- **F3 смоуки детерминированы:** 7 файлов `tests/test_smoke_round1016_*.py`,
  1424 строки; сеть/реальные секреты не используются (мок yt-dlp/cobalt/LLM,
  `:memory:`‑SQLite). WONTFIX (S10.13-9/-11, R10.14-4) обоснованы в
  `plans/reports/round10.16_audit.md:89-95`.
- **F4 self-host/размеры/CSS:** external CDN в `web/` — 0 (grep чист);
  бандлы на месте (`vue.global.prod.min.js`, `chart.umd.min.js`,
  `telegram-web-app.js`, `tailwind.css`, `dompurify-3.4.15.min.js`); версии
  пинованы (Vue 3.5.42, Chart.js 4.5.1); `<style>` перенесён **без потерь**
  (184/184 селекторов baseline присутствуют в `web/static/app.css`); предсобранный
  Tailwind покрывает все утилиты из `class="..."` (сверка скриптом: расхождений
  нет, отсутствуют только семантические/кастомные имена, которых и в baseline
  не было).
- **F4 CSP-заголовок** применяется только к HTML (`web/app.py:259-268`), на
  `/static`/`/api` отсутствует (тест `test_csp_absent_on_static_and_api`).
- **F5 git-гигиена:** `plans/current_task.md` не отслеживается, в истории пусто,
  `.gitignore:70` активен — проверено независимо.
  `deploy_v2.9.2.py`/`check_remote_bot.py` санитизированы (пароль из env/getpass).
- **Инварианты:** см. §5.

## 4. Validator (запущено @Reviewer)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5910 passed**, 1 warning (`StarletteDeprecationWarning`, не наш код) | 0 |
| `node --check web/app.js` | clean (`CHECK_EXIT:0`) | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `git diff --check` | чисто (только штатные LF→CRLF) | 0 |
| `grep -rn "unpkg.com\|cdn.jsdelivr\|cdn.tailwindcss\|telegram.org/js\|fonts.gstatic" web/` | **пусто** | 1 |
| `git status --porcelain media/ .env` | пусто | 0 |

Зелёный валидатор **не отменяет** Critical по CSP: у гейта нет поведенческой
проверки миниаппа (только строки), а именно она выявила бы отказ.

## 5. Инварианты

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/URL в логах) | ❌ | остаточные URL/`str(exc)` в `tools/video_downloader.py:439,517,802,814`; авто-теста нет |
| R16 (id — ключ) | ✅ | `updated_by` — id; `:365`-запросы; смоуки |
| Порядок роутеров `bot.py` | ✅ | `bot.py:743-761` — 4e на месте, только снятие startup-гейта |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | пин-тесты зелёные (`test_frontend_tab_mapping.py:47-84`, `test_param_catalog.py:78,266`, `test_round106_ia_smoke.py:32-35`) |
| SQLite v9 / DDL нет | ✅ | новых DDL/SQL-миграций нет |
| PREV/PROMPT_MIGRATIONS, tool-set 7 | ✅ | `test_tool_schemas.py:90`, `test_tool_calling_round1015.py:627` |
| Новых CDN нет; `v-html` только через DOMPurify | ✅ | `web/app.js:4228-4237` (`sanitizeHtml`), внешних CDN — 0 |
| XSS/CSP | ❌ | CSP ломает Vue (Critical); XSS-санитайз сохранён |
| Регрессии F6–F9 10.15 | ⚠️ | pytest зелёный; но R10.15-4 меняет условие yield, а CSP-регрессия задевает весь фронт |

## 6. Итог

Эпик близок к завершению, но не готов к мержу: F4 содержит прод-ломающий CSP
(миниапп не смонтируется), F1 оставляет R17-утечки URL в логах при заявленной
чистоте, F2 не гарантирует доставку канона, README описывает невыполненную
ротацию как факт. Валидатор зелёный лишь потому, что поведенческая проверка
миниаппа заменена статическими маркерами — это и есть «на бумаге», за которое
фича отклоняется.

**@Builder (или профильный исполнитель) — исправить Critical + High (минимум),
затем повторное ревью (цикл 1 из 3).**

*Round 10.16 reviewer report generated by @Reviewer on 2026-09-14.*

---

# Повторное ревью (итерация 2)

> **Ревьюер:** @Reviewer. **Дата:** 14.09.2026. **Baseline:** HEAD `18a9aa1` + рабочее дерево (незакоммичено) — итерация 1 была Rejected.
> **Проверка:** фактическая, по коду и `file:line`; валидаторы запущены заново. Значения секретов не приводятся (R17).

## 0. ИТОГОВЫЙ ВЕРДИКТ ИТЕРАЦИИ 2

# ✅ Approved

Все Critical/High итерации 1 закрыты фактически, а не декларативно; Medium/Low — закрыты (либо обоснованно сняты). Валидатор зелёный, инварианты держатся, регрессий не выявлено.

## 1. Пункты итерации 1 — подтверждено/нет (с `file:line`)

| # | Пункт итерации 1 | Статус | Доказательство |
|---|---|---|---|
| C1 | CSP ломает Vue full build | ✅ **подтверждено** | Вариант A: `web/app.py:49-60` — `script-src 'self' 'unsafe-eval'`; ADR обновлён (`adr-1016-2-selfhost-csp.md:15,26,36,41-46`); поведенческий гейт `tests/js/vue_mount_test.js:31-59` (реальная загрузка бандла, `Vue.compile`, подмена `Function` → `EvalError`), `:61-83` (mount/inline/CDN); ассерт CSP — `tests/test_smoke_round1016_miniapp_selfhost.py:76-88` (`'unsafe-eval' in script_src`) + `tests/test_webapp_api.py` (CSP HTML) |
| H2 | R17: URL/`str(exc)`/тело в логах `tools/video_downloader.py` | ✅ **подтверждено** | Лог-сайты очищены: `:442-443` (`direct downloaded \| bytes=%d \| ext=%s`), `:516-518` (`low disk \| free=%d MB`), `:812-813` (`body unreadable \| error=%s` = `type(exc).__name__`), `:824-825` (`cobalt http %s \| code=%s \| body_chars=%d`). Хендлеры/роутер логируют только класс+reason: `handlers/video_download.py:308,324-326,351-353,467-472`; `services/tool_router.py:600-607`. caplog-тесты осмысленны: `tests/test_download_round1016.py::TestNoSecretsLogging` (`:544-645`) + `:129-142`, `:462-478` |
| H3 | F2: доставка канона не гарантирована | ✅ **подтверждено** | Одноразовая форс-доставка: `services/config_cache.py:285-293` (unknown + нет маркера → canon), маркер `:300-312`; `services/info_service.py:246-257` (`save_text` ставит `canon_delivered_version`); тесты `tests/test_guide_delivery_round1016.py:163-177` (force delivered once, `canon_drift is False`), `:130-139` (идемпотентность), `:180-194` (ручная правка после доставки не затирается). `INFO_CANON_VERSION == 2` (`info_service.py:145`) |
| H4 | README overclaim о ротации SSH | ✅ **подтверждено** | `README.md:74` — модальность «процедура ротации (выполняется @DevOps)», гейты `T-1661/T-1664` открыты, «считать отозванным только после отчёта @DevOps» |
| M1 | Мёртвая ветка `_probe_error_phrase` для single-URL | ✅ **подтверждено** | Ветка удалена, комментарий сохранён: `handlers/video_download.py:346-362` |
| M2 | `reason="stream_failed"` для too-big | ✅ **подтверждено** | `tools/video_downloader.py:879-881` → `reason="stream_too_big"`; маппинг в TOO_BIG-пул `handlers/video_download.py:418`; тест `tests/test_download_round1016.py:604-645` |
| M3 | `/edit_info` не ловит прочие исключения `save_text` | ✅ **подтверждено** | `handlers/info.py:172-183` — generic `except Exception`, лог класса без `str(exc)`, фраза пользователю |
| M4 | Расходящиеся цифры отчётов | ✅ **подтверждено** (см. ост. замечание 1) | `plans/reports/round10.16_audit.md:12` = **5931** = фактический прогон; `plans/ARCHITECTURE.md:310` = **5931** |
| L1 | POT читался из `os.getenv` | ✅ **подтверждено** | `tools/video_downloader.py:187-195` — единый хелпер `get_ytdlp_pot_provider()` (тот же, что `build_ytdlp_base_opts`; `config/settings.py:1223-1231` — намеренно env-only ради каталог-Δ=0) |
| L2 | `_normalize_quality` без диапазона | ✅ **подтверждено** | `tools/video_downloader.py:795-798` — `144 <= height <= 4320`; тест `tests/test_download_round1016.py:651-661` |
| L3 | `/static/vendor/tailwind.css` без `?v=` | ✅ **подтверждено** | `web/index.html:19` — `?v=__APP_VERSION__` |
| L4 | `_render_app_css` не защищён | ✅ **подтверждено** | `web/app.py:104-120` — `except OSError` → пустой CSS; тест `tests/test_smoke_round1016_miniapp_selfhost.py:115-126` |
| L5 | Дубль `T-1633` | ✅ **подтверждено** | `plans/features/download-fix-round1016/tasks.md:70` — единственное вхождение |

**Приложение (Critical):** приложение смонтируется — все ресурсы из `web/index.html` (`:15,19,22,2900,2904,2907,2908,2911`) физически на месте (`web/static/vendor/*`, `web/static/app.css`, `web/static/fonts/material-symbols-rounded.woff2`, `web/static/telegram-init.js`); inline-исполняемых скриптов/`<style>`/`http(s)://`/inline-обработчиков (`onclick=`) нет; `app.mount('#app')` и `template: '#kv-editor-tpl'`/`'#list-editor-tpl'` на месте.

## 2. Validator (запущено @Reviewer, итерация 2)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5931 passed**, 0 failed, 1 warning (`StarletteDeprecationWarning`, не наш код), 68.59 c | 0 |
| `node --check web/app.js` | clean (`CHECK_EXIT:0`) | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` | 0 |
| `git diff --check` | чисто (только штатные LF→CRLF) | 0 |
| `pytest tests/test_smoke_round1016_miniapp_selfhost.py test_download_round1016.py test_guide_delivery_round1016.py -q` | 73 passed, **0 skipped** (поведенческий гейт реально исполнен) | 0 |

## 3. Остаточные замечания (НЕ блокирующие Approved)

1. **[Low, docs]** `plans/reports/round10.16_security_scan.md:133` сохраняет цифру `5910` своего прогона (до +21 тестов итерации 1) — это исторический артефакт скана F5, а не текущий валидатор. Мастер-эвиденс (`round10.16_audit.md:12`) и `ARCHITECTURE.md:310` синхронизированы с фактическими 5931.
2. **[Low, hardening]** `raise`-сайты `tools/video_downloader.py:405-408,451-453,569-573,583,586,599,604,608,625,705` всё ещё вкладывают `url={url}` в текст `DownloadError`. Ни один лог-сайт его не печатает (R17-logging соблюдён), но для защиты в глубину стоит убрать URL и из сообщений исключений.
3. **[Info]** Токен `stream_too_big` присутствует в докстринге кода (`tools/video_downloader.py:134`) и маппинге фраз, но не перечислен в spec §3 / ADR-1016-1 — при следующем касании спеки уместно добавить для полноты контракта.
4. **[Info]** Открытые гейты вне ревью-скоупа: F4 `T-1657` (@DevOps, Caddy/DNS), F5 `T-1661/T-1664` (ротация/деплой), `T-1625/T-1634/T-1642` (architect-гейты) — ожидаемо для Step 5.
5. **[Info]** Реальный мобильный/браузерный smoke (DevTools device emulation + блокировка внешних хостов) остаётся за @Reviewer/@DevOps; поведенческий Node-гейт `tests/js/vue_mount_test.js` — принятая компенсация.

## 4. Инварианты (итерация 2)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/URL в логах) | ✅ | лог-сайты `tools/video_downloader.py`/хендлеров/роутера чисты (`:442,516,812,824`; `handlers/video_download.py:308,324,351,467`; `tool_router.py:600`); caplog-тесты |
| R16 (id — ключ) | ✅ | `updated_by=user.id` (`web/api/routes.py:1111,1137`, `handlers/info.py:173`); смоуки |
| Порядок роутеров `bot.py` | ✅ | `bot.py:745-762` — 4e на месте, изменён только startup-гейт; 5 Slava `:765` |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | рантайм: `REGISTRY=435`, `GROUPS=90`, `TAB_RULES=19`, `_TAB_BY_GROUP=88`, Settings=411; пин-тесты зелёные |
| SQLite v9 / DDL нет | ✅ | `git diff -- services/database.py` — нет `CREATE/ALTER/user_version`; `services/pg_db.py` не в диффе |
| tool-set 7 / PREV/PROMPT_MIGRATIONS | ✅ | `tests/test_tool_schemas.py:90` (`==7`); `tests/test_prompt_migrations.py` зелёные |
| Новых CDN нет; `v-html` только через DOMPurify | ✅ | `web/index.html` внешних ссылок 0; `web/app.js:4228-4240` — fail-closed `sanitizeHtml` |

## 5. Заключение итерации 2

Прод-ломающий CSP-дефект устранён осознанным вариантом A (`'unsafe-eval'`) с ADR-обоснованием и **поведенческим** гейтом, который реально исполняет компилятор Vue и ловит `EvalError` без `'unsafe-eval'`; R17-логирование в `tools/video_downloader.py` закрыто и покрыто caplog-тестами; доставка канона F2 гарантирована одноразовой форс-доставкой с маркером; README приведён к честной модальности. Medium/Low итерации 1 закрыты. Регрессий нет, инварианты держатся.

**@Orchestrator — фича прошла повторное ревью. Можно двигаться дальше (финальный деплой/гейты @DevOps вне ревью-скоупа).**

*Round 10.16 reviewer re-review (iteration 2) generated by @Reviewer on 2026-09-14.*
