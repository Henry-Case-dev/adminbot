# Отчёт @Scanner — раунд 10.17 (UPD3), ШАГ 6 OpenSpec

> **Сканер:** @Scanner (независимый diff-аудит). **Дата:** 14.09.2026.
> **Baseline HEAD:** `772f192`. **Объём:** незакоммиченный `git diff` + untracked (5 фич F1–F5, T-1666…T-1702).
> **Режим:** код НЕ правился; искались реальные баги/риски/регрессии (не стиль и не спек-комплаенс — это @Reviewer).
> **Метод:** `git status/diff` → адресные чтения `file:line` → прогон валидатора + инструментальные пробы (raw ASGI HEAD).

## 0. Сводка

| Severity | Кол-во | Коды |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **0** | — |
| **Medium** | **1** | S10.17-1 |
| **Low** | **2** | S10.17-2, S10.17-3 |
| **Info** | **3** | S10.17-4, S10.17-5, S10.17-6 |

Функциональная часть эпика работает: F2 реально доводит tool-скачивание через
`probe → tdq:<height> → needs_quality → callback`; F1 отдаёт HEAD/`/healthz` (проверено raw-ASGI — GET-роуты
FastAPI НЕ авто-обрабатывают HEAD, явные `@app.head` достижимы: 200 + CSP/no-store, тело пустое, content-type
совпадает с GET); F3 корректно считает остаток (границы/NaN/кламп — JS-юниты); F4 README/ARCHITECTURE почищены;
F5 разносит ожидаемые/транзиентные/неожидаемые сбои на **всех 6** сайтах `avatars.py`. Внешних CDN нет (в т.ч. vendor).
Все инварианты (R16/R17, tool-set 7, лимиты 4/2, порядок роутеров, каталог Δ=0, SQLite v9) — целы, pytest 6007/0.

Блокеров нет. Единственная находка уровня **Medium** — **остаточный overclaim об ОТМЕНЕ ротации в архивной
спеке F5 `spec.md`** (не входит в явный scope T-1692, но противоречит цели F4 и формирует ложное «действие»).

## 1. Findings

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.17-1 | Medium | `plans/archive/security-rotation-finalize-round1016/spec.md:3,72,79-83` | Архивная спека 10.16 F5 **без CANCELLED-баннера**; §8 сохраняет живую формулировку «ротация обязательна в любом случае»; DoD-чекбоксы `[ ]` без пометок | Добавить в шапку banner `⚠️ CANCELLED (UPD3 §4, round1017)` (как в `tasks.md:5`) и пометить `:72`/`:79-83`; историю не переписывать |
| S10.17-2 | Low | `web/app.js:1216-1247,1234-1256` | При `cognition==null` бейджи дают `☀️ Сон через —` / `🌅 Глубокий сон через —`, тогда как spec F3 §3.4 (:86) требует `«—»` | Либо уточнить §3.4 спеки (псевдокод §3.2 даёт именно «через —»), либо вернуть чистый `—` при отсутствии данных |
| S10.17-3 | Low | `plans/features/tool-download-quality-round1017/spec.md:245`; `plans/features/sleep-badge-countdown-round1017/spec.md:125` | Счётчики pytest в `spec.md` остались `5951`/`5985`; фактический прогон и `tasks.md` — **6007** | Синхронизировать две строки spec.md (требование L3 закрыто только для tasks.md) |
| S10.17-4 | Info | `services/tool_router.py:675-686,722-742` | Tool-путь скачивания не вызывает `log_download_env_once()` (символ в модуль не импортирован), тогда как Fast-Track вызывает (`handlers/video_download.py:350,353,468`) | Вызвать env-preflight в catch-блоках tool-пути для паритета диагностики |
| S10.17-5 | Info | `handlers/video_download.py:619-685` | Callback `tdq:` не проверяет hot-флаг `flags.download_enabled` (producer — проверяет, `tool_router.py:650`) | Проверить флаг в начале callback (паритет с 10.16 R10.15-4) |
| S10.17-6 | Info | `web/app.py:256-268` | Unauth `/healthz` отдаёт `APP_VERSION` (info-disclosure); плюс `services/tool_router.py:338,378,381` — pre-existing `query=%r` в логах R17-смежных tool-сайтов | Принято спекой F1 §3.1 (L8); query-логи — pre-existing, вне диффа |

## 2. Детали

### S10.17-1 (Medium) — архивный overclaim «ротация обязательна»

- `plans/archive/security-rotation-finalize-round1016/spec.md:3` — статус `✅ COMPLETED`, без CANCELLED.
- `:72` — риск-таблица: «…ротация **обязательна в любом случае**».
- `:79-83` — DoD-пункты `[ ]` («Установлен SSH-ключ, пароль ротирован/отозван…») без пометок.
- Контраст: `.../tasks.md:5` (banner CANCELLED), `README.md:74,387`, `plans/ARCHITECTURE.md:326,616,624,628`,
  `plans/backlog.md:95-97` — исправлены.
- Влияние: не код; но единственный артефакт той же папки без mark может быть прочитан @DevOps как
  «незакрытое действие по безопасности» — ровно тот класс overclaim, который F4 устраняет.
- Scope-нюанс: T-1692 §2 явно называет только `backlog.md` и `tasks.md` (не `spec.md`), поэтому Medium, не High.

### S10.17-2 (Low) — текст бейджа при отсутствии данных

- Код: `var c = this.cognition || {}; var d = c.dream || {}; … return { text: '☀️ Сон через ' + fmtCountdown(Number(d.next_wake_at) - now) }`.
- `Number(undefined) - now = NaN` → `fmtCountdown` → `'—'` ⇒ итог `'☀️ Сон через —'`.
- Спека противоречива сама с собой: §3.2 (псевдокод) даёт «через —», §3.4 (:86) — «`«—»`».
- Закреплено тестами (`tests/js/routing_test.js` F3-блок, `tests/test_webapp_round1017_sleep.py`). Функциональный
  вред минимален (текст осмыслен), регрессии 10.15 нет.

### S10.17-3 (Low) — доки-счётчики

- `tool-download-quality/spec.md:245` → 5951; `sleep-badge-countdown/spec.md:125` → 5985.
- Факт: `.venv/Scripts/python.exe -m pytest -q` → **6007 passed / 0 failed** (79.62 c). `tasks.md` всех 5 фич — 6007. ✔

## 3. Верифицировано чисто (доказательства)

- **F2 (полный флоу):** producer `tool_router.py:634-709` (probe → `_quality_arg`/`is_direct_media_url` →
  `store_tool_download_pending` → menu → `cooldown_touch` ПОСЛЕ успешной отправки → `needs_quality`);
  callback `video_download.py:619-685` (`peek` → валидация `f"{quality}p" in qualities` ДО consume → busy-гейт
  без потери pending → `pop` → `download(url, f"{quality}p")` → `send_media`). Единый хелпер меню
  `services/media_send.py:24-59`; дублей строки «выбери качество:»/построителя клавиатуры в коде нет (grep).
  `_TOOL_DL_PENDING` — key `(chat_id,user_id)`, TTL 600 c, ленивая чистка; peek→pop без `await` между ними —
  двойной клик не даёт двойного скачивания. Высоты 100% из probe. R17: логи — только класс/reason/chat/user/quality.
- **F2 лимиты/схема:** `QUALITY_ENUM == ("max",)+_ALLOWED_HEIGHTS`; `additionalProperties=False`; `required=["url"]`;
  `TOOL_CALLING_TOOLS` = 7, порядок не изменён; `TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2` — не в диффе.
- **F1 (HEAD/healthz):** инструментальная проба raw-ASGI — таблица роутов содержит отдельные `HEAD`-записи
  (`/web/`, `/web/index.html`, `/healthz`), HEAD отдаёт 200, тело `b''`, `Content-Security-Policy` = `_CSP_HTML`,
  `Cache-Control` c `no-store`; content-type HEAD == GET. `_startup_diag` — только scheme/host/path через `urlsplit`
  (R17). No-CDN-гейт сканирует и **6 vendor-файлов** (`tests/test_webapp_dns_round1017.py:42-49`).
- **F3:** `fmtCountdown` — `null`/`NaN`→`—`, кламп `<0`→0, `Math.floor` вниз (JS-юниты 8100/900/3600/0/-30/59/3599);
  бейджи вне фазы `badge-muted`, в фазе `glow` + `до HH:MM`; эмодзи сохранены; `«выключен»` удалён.
- **F4:** `README.md:74,387`, `plans/ARCHITECTURE.md:326,616,624,628`, `plans/backlog.md:95-97`,
  `archive/.../tasks.md:5,18,32,52,59,62` — CANCELLED. Кода в диффе нет (только `*.md`).
- **F5:** все 6 сайтов `web/api/avatars.py` (142-148, 211-220, 252-262, 273-283, 323-333, 347-357) имеют
  `except (TelegramRetryAfter, TelegramNetworkError)` (WARNING, без трейса, **без** записи в негатив-кэш) и
  `except TelegramBadRequest` (DEBUG без трейса, негатив кэшируется); generic → WARNING + `exc_info` (R17-safe
  `safe_exc_text`). brotli зафиксирован WONTFIX (build-time only, Caddy `zstd+gzip`) в README/ARCHITECTURE.
- **Инварианты (Δ=0):** `media/`/`.env` не тронуты (`git status --porcelain` пусто); `bot.py` не в диффе
  (4e на своём месте); `services/tool_loop.py`/`database.py`/`chat_prompts.py`/`dream_prompts.py` не в диффе
  (PREV/`PROMPT_MIGRATIONS`, SQLite v9); каталог 435/406/411/90/88/19 (`test_param_catalog` зелёный);
  `test_tool_set_unchanged` зелёный; `git diff --check` → exit 0.
- **Валидатор (прогон @Scanner):** pytest **6007 passed / 0 failed** (79.62 c); `node --check web/app.js` OK;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`;
  новые наборы F1/F2/F3/F5 — **71 passed**.

## 4. Вердикт по контракту

**Открытых Critical/High — НЕТ.** Medium S10.17-1 — docs-only (архивная спека), воркфлоу не блокирует;
Low/Info — не блокеры. Разрешено к передаче на Шаг 7.

## 5. Что обновлено

- `plans/reports/round10.17_scanner_audit.md` — этот отчёт (новый).
- `plans/reports/global_map.md` — аддитивная секция «Round 10.17» (связки F1–F5).
- `plans/reports/full_audit_results.md` — аддитивная секция «Round 10.17».
- `plans/reports/audit_backlog.md` — аддитивно: Round 10.17 (все файлы просканированы; открытые пункты).

*Отчёт сгенерирован @Scanner 14.09.2026 (Шаг 6 OpenSpec).*
