# Отчёт @Reviewer — раунд 10.17 (UPD3), ШАГ 5 OpenSpec

> **Ревьюер:** @Reviewer (предельно строгий QA-гейт). **Дата:** 14.09.2026.
> **Baseline HEAD:** `772f192`. **Объём:** незакоммиченные изменения (git diff + untracked) по 5 фичам.
> **Режим:** код НЕ правился; проверялись контракт, корректность, безопасность, инварианты, тесты.

## 0. Сводка

Код-часть эпика **реализована и работает**: F2 реально доводит tool-скачивание через
`probe → tdq:<height> → needs_quality` и callback; F1 отдаёт HEAD/`healthz` и host-only лог;
F3 корректно считает остаток/фазу; F5 разносит ожидаемые/неожидаемые сбои Bot API; F4
поправлен README/backlog/архив. Все пять Validator-гейтов — зелёные, инварианты (R16/R17,
tool-set 7, лимиты 4/2, no-CDN, порядок роутеров `bot.py`, `media/`/`.env`, каталог Δ=0,
SQLite v9) — подтверждены.

**Однако приёмка отклоняется.** Есть несоответствия спеке/политике уровня
Medium, требующие доработки (F4 — живой overclaim в `plans/ARCHITECTURE.md`; F5 — политика
транзиентов не применена к 2 из 6 сайтов; F2 — дублирование меню вопреки T-1679). Функциональный
блокер отсутствует; блокируют именно spec/doc/policy-разрывы.

## 1. Контракт и открытые гейты

Builder-задачи `[x]` — во всех фичах. Открытые гейты (`[ ]`), в т.ч. @DevOps/DNS:

| Фича | Закрыто @Builder | Открытые гейты (`[ ]`) |
|---|---|---|
| F1 `miniapp-mobile-dns` | T-1669, T-1670, T-1672 | **T-1666** (Architect-гейт: артефакты spec/ADR есть, чекбокс открыт), **T-1667/T-1668/T-1671 @DevOps (DNS/оператор/Private DNS/фоллбэк hostname — вне репо)**, **T-1673 — живой Android-смоук**, **T-1674 @Reviewer/@PM** |
| F2 `tool-download-quality` | T-1676…T-1683 | **T-1675** (ADR-гейт; ADR-1017-2 создан), **T-1684 @Reviewer/@PM** |
| F3 `sleep-badge-countdown` | T-1686…T-1690 | **T-1685** (Architect-гейт), **T-1691 @Reviewer/@PM** |
| F4 `ssh-rotation-cancelled` | T-1693, T-1694 | **T-1692** (docs-спек создан), **T-1695 @Reviewer/@PM** |
| F5 `warnings-hygiene` | T-1697, T-1698, T-1700 | **T-1696** (Architect-гейт), **T-1699 @DevOps (Caddy `zstd+gzip`/`Content-Encoding`)**, **T-1701 (формальные гейты)**, **T-1702 @Reviewer/@PM** |

Отдельно: DoD F1 «Android-резолв стабилен», «живой Android-смоук» — **открыты** (инфра, @DevOps).

## 2. Таблица по фичам

| Фича | Контракт | Реально в коде (file:line) | Тесты | Итог |
|---|---|---|---|---|
| F1 | HEAD `/web/`, `/web/index.html`; unauth GET+HEAD `/healthz` (no-store); startup host-only; no-CDN | `web/app.py:124-135` (`_startup_diag`), `:224-234` (HEAD), `:256-264` (healthz); `handlers/menu.py:66-70`; `tests/test_webapp_dns_round1017.py` | 200 + CSP + no-store, no-CDN, host-only — зелёные | ✅ функц. / M-Low |
| F2 | tool probe→меню→`needs_quality`; callback `tdq:` доводит download; direct/явное quality без меню; bounded fallback; TTL; D279; R17 | `services/tool_router.py:135-169` (pending), `:620-766`; `handlers/video_download.py:625-682`; `services/tool_schemas.py:125-149`; `tools/video_downloader.py:105-106` | `tests/test_tool_download_quality_round1017.py` (19 кейсов) — зелёные | ✅ функц. / M3 |
| F3 | вне фазы «через {остаток}», в фазе `.glow` + «до HH:MM», эмодзи не трогать, API не менять | `web/app.js:1216-1248`, `:5113-5126` (`fmtCountdown`); `tests/test_webapp_round1017_sleep.py` + JS в `tests/js/routing_test.js` | unit + маркеры — зелёные | ✅ |
| F4 | docs-only: CANCELLED в backlog/архиве, README без overclaim, кода 0 | `README.md:74,387`; `plans/backlog.md:95-97`; `plans/archive/security-rotation-finalize-round1016/tasks.md:3-4` | grep/дифф | ⚠️ M1 |
| F5 | expect→debug без трейса; unexpected→warning с `exc_info`; транзиент не кэш; brotli WONTFIX | `web/api/avatars.py:147-156,205-210,236-241,250-255,299-304,323-328,167-182`; docs `plans/ARCHITECTURE.md`, `README.md` | `tests/test_avatars_round1017.py` — зелёные | ⚠️ M2 |

## 3. Проблемы

### Medium

**M1 — F4: живой overclaim о ротации SSH в `plans/ARCHITECTURE.md`**
- File: `plans/ARCHITECTURE.md`
- Location: `:326` («пароль пока не отротирован (`T-1661` — открытый @DevOps-гейт, §37)»), `:328` (в списке **ОТКРЫТЫХ** гейтов — `T-1661/T-1664 (SSH-ротация…)`), `:616`, `:628`.
- Problem: фича F4 объявляет задачу CANCELLED, но live-разделы ARCHITECTURE (§10/§25) по-прежнему описывают ротацию как незакрытое действие, а §37 — как процедуру для @DevOps.
- Why it matters: цель F4 — снять overclaim, чтобы никто не считал ротацию открытым долгом; README почищен, а главный архитектурный док противоречит — требование tasks.md §2.2 («README/дока не утверждают…») не выполнено.
- Required fix: внести в `plans/ARCHITECTURE.md` пометку `⚠️ CANCELLED (UPD3 §4, round1017)` к `:326`/`:328` (гейты закрыты отменой, не выполнением) и/или ссылку на `adr-1017-*`/F4; исторический §37 не переписывать, но пометить отмену (как это сделано для ADR-1016-1).

**M2 — F5: политика транзиентов не применена к 2 из 6 сайтов `avatars.py`**
- File: `web/api/avatars.py`
- Location: `chat_display_info` `:199-211`; `user_display_info` `:231-241` и `:247-256`.
- Problem: `TelegramRetryAfter`/`TelegramNetworkError` здесь не имеют отдельной ветки — попадают в generic `except Exception` → `_log_bot_api_failure(expected=False)` (WARNING + `exc_info`) и **пишутся в негатив-кэш на 1 час**. Политика spec §3 гласит: транзиент → WARNING **без** трейса, **НЕ** кэшируется (BUG-4); spec §2 (строка 42) требует «единую политику ко всем 6 сайтам», а `fetch_avatar_bytes`/`global_user_display_info` транзиент уже различают.
- Why it matters: rate-limit/сетевой сбой «залипает» пустым аватаром/именем на час, а в лог уходит трейс — ровно тот симптом, который фича F5 должна устранить.
- Required fix: добавить перед generic-`except` ветку `except (TelegramRetryAfter, TelegramNetworkError)` с флагом `transient` и `if not transient: _cache_put(...)` (паттерн `global_user_display_info:294-306`), **либо** письменно зафиксировать отклонение от политики §3 в spec/ADR (почему эти два сайта кэшируют транзиент).

**M3 — F2: меню качества продублировано вопреки T-1679 («без дублирования меню»)**
- File: `services/tool_router.py:749-766` и `handlers/video_download.py:203-222`
- Problem: `InlineKeyboardBuilder`/текст «выбери качество:»/`tdq:` vs `vd:` реализованы двумя независимыми копиями (плюс `_quality_keyboard` и `_send_quality_menu` в handlers дублируют одноимённый метод роутера).
- Why it matters: дрейф форматов меню, рассинхрон UX/подписей при следующей правке; прямое нарушение формулировки T-1679.
- Required fix: вынести построение клавиатуры/заголовка меню в общий хелпер (например, `services/media_send.py` или новый `services/download_menu.py`), вызывать его из Fast-Track и tool-пути; **или** зафиксировать осознанное дублирование в spec/ADR-1017-2 с обоснованием «слои не пересекаются».

### Low

**L1 — F2: callback не валидирует выбранную высоту.** `handlers/video_download.py:637` (`_parse_int_suffix` принимает любое int; `pending["qualities"]` не проверяется). Мусор/подделанный `tdq:99999` → `DownloadError(invalid_quality)` → generic-фраза, pending уже съеден. Required fix: сверять `quality` с `pending["qualities"]`/`_ALLOWED_HEIGHTS`, иначе `answer("эта менюха протухла")` без потери pending.

**L2 — F1: no-CDN гейт не сканирует `web/static/vendor/**`.** `tests/test_webapp_dns_round1017.py:34-39` проверяет только `index.html/app.js/app.css/telegram-init.js`; spec §6 #5 называет «vendor». Существующий `tests/test_smoke_round1016_miniapp_selfhost.py:24-40` тоже не сканирует vendor. Required fix: добавить скан баннеров vendor (или явно записать, что vendor — third-party и исключён из гейта).

**L3 — доки: рассинхрон счётчиков тестов.** `plans/features/miniapp-mobile-dns/tasks.md:64,105` (5965), `.../tool-download-quality/tasks.md:62,74` (5951), `.../sleep-badge-countdown/tasks.md:59,125` (5985), `.../warnings-hygiene/tasks.md` (5997); фактический прогон — **5997**. Плюс F1 DoD печатает каталог «435/90/88/19» без 406/411. Required fix: привести к финальному прогону/полному набору инвариантов.

**L4 — F1: `HEAD /healthz` не повторяет content-type GET.** `web/app.py:261-264` отдаёт только `Cache-Control`; spec §3.1 «те же заголовки». Косметика.

**L5 — F2: кулдаун жжётся до отправки меню.** `services/tool_router.py:674-689` — touch после probe, но до `_send_quality_menu`; провал отправки меню оставляет пользователя без меню, но с кулдауном. Spec-совместимо (§2.5), но UX-хрупко; желательно touch после успешной отправки.

**L6 — F2: нет `send_chat_action("upload_video")` в tool-callback** (`handlers/video_download.py:655-666`), в отличие от Fast-Track `cb_pick_quality`. Косметика/парность UX.

**L7 — F5: residual R17 в `dispatch`.** `services/tool_router.py:306-307` логирует `f"{type(exc).__name__}: {exc}"`; для нового пути `_download_media` URL обычно уже отфильтрован, но catch-all остаётся потенциальной утечкой (pre-existing).

**L8 — F1: `/healthz` unauth раскрывает `APP_VERSION`.** `web/app.py:256-259`. Спекой требуется; принято осознанно, но зафиксировать в т.ч. как info-disclosure.

### Critical / High
Не выявлено.

## 4. Итоги Validator (запущены @Reviewer)

| Гейт | Команда | Результат |
|---|---|---|
| pytest | `.venv/Scripts/python.exe -m pytest -q` | **5997 passed / 0 failed** (74.3 c), 1 warning (deprecated `httpx` в TestClient — pre-existing) |
| JS syntax | `node --check web/app.js` | OK |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` |
| JS mount | `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` |
| whitespace | `git diff --check` | exit 0 |

## 5. Инварианты (подтверждены)

- **R17:** startup-лог host/scheme/path (`web/app.py:124-135`), `menu` host-only (`handlers/menu.py:66-70`), tool-логи — класс/reason без URL (`services/tool_router.py:661-715`), callback — класс/reason без URL (`handlers/video_download.py:667-675`), avatar-логи `safe_exc_text`/без токенов (`web/api/avatars.py:167-182`) — ✔.
- **R16:** pending и API-ключи по id (`_TOOL_DL_PENDING[(chat_id,user_id)]`) — ✔.
- **tool-set 7 / порядок:** `TOOL_CALLING_TOOLS` = 7, порядок не изменён — ✔.
- **лимиты tool-loop:** `TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2` — не тронуты — ✔.
- **порядок роутеров `bot.py`:** `bot.py` не в диффе; `video_download_router` регистрируется из той же позиции 4e (`bot.py:756`) — ✔.
- **`media/`/`.env`:** не тронуты (git status) — ✔.
- **каталог 435/406/411/90/88/19 (Δ=0):** пин-тест зелёный — ✔.
- **SQLite v9 / DDL:** миграций нет — ✔.
- **нет внешних CDN:** `web/index.html|app.js|static/app.css|static/telegram-init.js` — 0 вхождений `http(s)://` — ✔.
- **Fast-Track F6 / фиктивный tool_response:** не задеты; direct-ветка по-прежнему `success`, платформа — `needs_quality` (по ADR-1017-2) — ✔.

## 6. Вердикт

**Rejected.**

Функциональная часть эпика реализована качественно и полностью покрыта регресс-тестами;
Validator-гейты и инварианты — чистые. Отклонение — по несоответствиям спеке/политике:
**M1** (F4 — overclaim в `plans/ARCHITECTURE.md`), **M2** (F5 — транзиентная политика не применена
к `chat_display_info`/`user_display_info`), **M3** (F2 — дублирование меню против T-1679).

## 7. Что исправить @Builder

1. `plans/ARCHITECTURE.md:326,328` (и пометка в §37 `:616,628`) — `⚠️ CANCELLED (UPD3 §4)` для ротации/`T-1661`/`T-1664`.
2. `web/api/avatars.py` — ветка `except (TelegramRetryAfter, TelegramNetworkError)` с «не кэшировать» в `chat_display_info` и `user_display_info` (member + photos), либо письменное обоснование отклонения в spec/ADR.
3. `services/tool_router.py:749-766` + `handlers/video_download.py:203-222` — единый хелпер меню качества (устранить дубль) либо ADR-обоснование.
4. Low (по желанию, но с фиксацией): L1–L8 — валидация качества в callback, скан vendor, синхронизация счётчиков тестов в tasks.md, `send_chat_action`, R17 в `dispatch`.

Инфра-гейты **T-1667/T-1668/T-1671/T-1673** (@DevOps, DNS/живой Android-смоук) и **T-1699**
(Caddy `Content-Encoding`) остаются открытыми и не закрываются в рамках этого ревью.

## 8. Повторное ревью (итерация 2) — 14.09.2026

> **Проверено фактически (file:line) + полный прогон Validator. Код не правился.**
> Итерация 1: **Rejected** (M1/M2/M3 + Low L1–L8). Ответ @Builder проверен адресно.

### 8.1 M1 — F4 overclaim в `plans/ARCHITECTURE.md` → **подтверждено (исправлено)**

- `plans/ARCHITECTURE.md:326` — R17-долг `current_task.md` помечен
  «⚠️ CANCELLED (UPD3 §4, round1017; F4 `ssh-rotation-cancelled-round1017`)»; overclaim
  «пароль пока не отротирован» снят, прямо сказано «ротация НЕ требуется», гейты закрыты **отменой**.
- `plans/ARCHITECTURE.md:328` — `T-1661/T-1664` **убраны из списка ОТКРЫТЫХ** @DevOps-гейтов
  (остались только `T-1657`, `T-1641`, прод-смоук), помечены CANCELLED.
- `plans/ARCHITECTURE.md:616` — F5 (10.16) с пометкой CANCELLED; `:624` — шапка §37
  «T-1657/T-1641 — ОТКРЫТЫ; T-1661/T-1664 — CANCELLED»; `:628` — процедура §37 помечена
  «Историческая процедура (**не действие**)».
- `README.md:74,387` — ротация объявлена ненужной (решение владельца, UPD3 §4), фича 10.16 F5
  помечена `CANCELLED`; overclaim отсутствует.
- `plans/backlog.md:95-97` — отдельная ⚠️-запись об ОТМЕНЕ; R-запись 10.16 «не является открытым действием».
- `plans/archive/security-rotation-finalize-round1016/tasks.md:3-4` (banner CANCELLED), `:32`, `:52`
  (DoD-пункты помечены CANCELLED).
- T-1692 остаётся гейтом `[ ]` в `plans/features/ssh-rotation-cancelled-round1017/tasks.md:55` — это
  штатный Architect-гейт (spec.md «✅ создан», строка 4), а не открытое действие по ротации.
- **Остаточное (Low/не блокер):** `plans/archive/security-rotation-finalize-round1016/spec.md:80` —
  единственный DoD-пункт `[ ]` без inline-пометки CANCELLED (banner в `tasks.md` есть; это не overclaim).

### 8.2 M2 — F5: транзиенты аватаров на всех 6 сайтах → **подтверждено (исправлено)**

Все 6 сайтов `web/api/avatars.py` имеют явную ветку
`except (TelegramRetryAfter, TelegramNetworkError)` → `WARNING` **без** `exc_info`
(через `safe_exc_text`) и **без** записи в негатив-кэш:

| # | Сайт | Ветка | Пропуск кэша |
|---|---|---|---|
| 1 | `fetch_avatar_bytes` | `:142-148` (`return None`) | — (ранний return) |
| 2 | `chat_display_info` (`get_chat`) | `:211-214` | `:221-222` |
| 3 | `user_display_info` (`get_chat_member`) | `:252-256` | `:263-264` |
| 4 | `user_display_info` (`get_user_profile_photos`) | `:273-277` | `:284-285` |
| 5 | `global_user_display_info` (`get_chat`) | `:323-327` | `:334-335` |
| 6 | `global_user_display_info` (`get_user_profile_photos`) | `:347-351` | `:358-359` |

Ожидаемые `TelegramBadRequest` → `debug` без трейса + негатив-кэш; прочее → `warning` с `exc_info`
(единый хелпер `_log_bot_api_failure`, `:169-184`) — точно по спеке §3 (порядок `except` соблюдён).
**Тесты:** `tests/test_avatars_round1017.py:202-229` (chat, `calls==2`, кэш пуст, все записи WARNING,
`exc_info is None`), `:231-266` (member+photos, `calls==4`, оба кэша пусты), плюс `fetch`-транзиент
`:175-…` — зелёные.

### 8.3 M3 — F2: дублирование меню качества → **подтверждено (исправлено)**

- Единый хелпер: `services/media_send.py:24` (`QUALITY_ROW_SIZE`), `:28` (`build_quality_keyboard`),
  `:43` (`quality_menu_text`), `:49` (`send_quality_menu`) — единственный построитель клавиатуры/заголовка.
- Fast-Track делегирует: `handlers/video_download.py:207-216`
  (`callback_prefix=_FASTTRACK_QUALITY_PREFIX="vd:"`, `:98`).
- Tool-путь делегирует: `services/tool_router.py:765-772`
  (`callback_prefix=_TOOL_QUALITY_PREFIX="tdq:"`, `:84`).
- Локальные копии удалены: `_quality_keyboard`/`_QUALITY_ROW_SIZE` в `handlers/video_download.py` отсутствуют;
  импорт `InlineKeyboardMarkup` убран; строка «выбери качество:» встречается только в `services/media_send.py:25`
  (grep: других вхождений нет).
- Поведение идентично прежнему Fast-Track: тот же `title[:200]+\n\n` + промпт, `adjust(3)`,
  `reply_to_message_id`, `disable_web_page_preview=True`; в `InlineKeyboardBuilder` на `:389` остаётся
  **другой** (video-select `vdv:`) меню — не дубль качества.
- **Остаточное (Low/не блокер):** нет отдельного unit-теста, пиннящего, что обе ветки вызывают общий
  хелпер; паритет покрыт косвенно (`tests/test_tool_download_quality_round1017.py:133-146` + Fast-Track-регресс).

### 8.4 Low L1–L8 → **подтверждено**

| # | Требование | Где подтверждено |
|---|---|---|
| L1 | Валидация высоты в callback (до consume) | `handlers/video_download.py:632-638` (`peek` + `f"{quality}p" in qualities`); тест `tests/test_tool_download_quality_round1017.py:178-191` |
| L2 | no-CDN скан vendor | `tests/test_webapp_dns_round1017.py:33-40` (`VENDOR_SCANNED`), `:116-121` (тест) |
| L3 | Счётчики тестов синхронизированы | `tasks.md` всех 5 фич → **6007** (`miniapp:64,108`, `sleep:59`, `tool:62,74`, `warnings:3`) |
| L4 | `HEAD /healthz` повторяет content-type GET | `web/app.py:263-268`; тест `tests/test_webapp_dns_round1017.py:93-99` |
| L5 | Кулдаун после успешной отправки меню | `services/tool_router.py:696-705` (touch после `_send_quality_menu`) |
| L6 | `send_chat_action("upload_video")` в tool-callback | `handlers/video_download.py:658-662`; тест `:174` |
| L7 | Catch-all класс без `str(exc)` | `services/tool_router.py:315-320` |
| L8 | `/healthz` version — зафиксированный info-disclosure | `web/app.py:256-257` |

- **Остаточное (Low/не блокер):** счётчики в `spec.md` не синхронизированы с финалом —
  `plans/features/tool-download-quality-round1017/spec.md:245` (**5951**) и
  `plans/features/sleep-badge-countdown-round1017/spec.md:125` (**5985**) остались значениями итер.1.
  `tasks.md` (требование L3) — приведены к 6007; эти две строки в spec.md в исходном L3 не назывались.

### 8.5 Итоги Validator (прогон @Reviewer, итерация 2)

| Гейт | Команда | Результат |
|---|---|---|
| pytest | `.venv/Scripts/python.exe -m pytest -q` | **6007 passed / 0 failed** (74.81 c), 1 warning (deprecated `httpx` в TestClient — pre-existing) |
| JS syntax | `node --check web/app.js` | OK |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` |
| JS mount | `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` |
| whitespace | `git diff --check` | exit 0 |

### 8.6 Инварианты (подтверждены, Δ=0)

- **R17:** startup host/scheme/path (`web/app.py:124-135`), `menu` host-only (`handlers/menu.py:66-70`),
  tool/callback — класс/reason без URL (`services/tool_router.py:315-320`, `handlers/video_download.py:670-678`),
  avatar — `safe_exc_text` (`web/api/avatars.py:163-184`) — ✔.
- **R16:** pending tool-скачивания по `(chat_id, user_id)` (`services/tool_router.py:693-695`) — ✔.
- **tool-set 7:** `test_tool_set_unchanged` зелёный, порядок не изменён — ✔.
- **лимиты tool-loop 4/2:** `services/tool_loop.py:24-25` не в диффе — ✔.
- **порядок роутеров `bot.py`:** не в диффе; `video_download_router` на позиции 4e (`bot.py:756`) — ✔.
- **`media/`/`.env`:** `git status --porcelain` пусто — ✔.
- **каталог 435/406/411/90/88/19:** `test_param_catalog` зелёный (Δ=0) — ✔.
- **SQLite v9 / DDL:** `services/database.py` не в диффе — ✔.
- **нет внешних CDN:** `TestNoExternalCdn` (в т.ч. vendor) зелёный — ✔.
- **PREV/PROMPT_MIGRATIONS:** `services/chat_prompts.py`/`dream_prompts.py` не в диффе — ✔.
- **F1–F5:** функциональные и JS-гейты зелёные, регрессов не выявлено — ✔.

### 8.7 Вердикт (итерация 2)

**Approved.**

Ранее выставленные блокеры сняты фактически: **M1** (`plans/ARCHITECTURE.md:326,328,616,624,628` +
README/backlog/archive), **M2** (все 6 сайтов `web/api/avatars.py` с тестами на некэширование), **M3**
(единый хелпер `services/media_send.py`, обе ветки делегируют, дубли удалены). Low L1–L8 выполнены.
Validator-гейты чисты (6007 passed, JS-OK, `git diff --check` exit 0), инварианты не сдвинуты.
Остаточные замечания носят Low/док-характер и не блокируют приёмку.
