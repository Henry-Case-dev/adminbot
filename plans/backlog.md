# AdminBot — backlog.md (глобальные неначатые эпики)

Только эпики, которые можно начать планировать. Канон-блоки промптов — в `docs/canon/`; закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).

## Раунд 10.17 (14.09.2026): UPD3 — мобильный мини-апп (DNS), tool-download quality, бейджи Сна, ОТМЕНА ротации SSH, warnings-hygiene — 5 фич — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (Step 8 @PM, 14.09.2026; деплой — Step 9 @DevOps, KG — Step 10 @Memory)

**✅ ИТОГ 10.17 (14.09.2026):** реализация завершена, все **5 фич заархивированы** — перенесены
`plans/features/*-round1017/` → **`plans/archive/*-round1017/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 6007 passed / 0 failed** (база 10.16 = 5936 → **+71**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19); новых ключей нет.
БД: **новых миграций нет** (SQLite остаётся **v9**; PG без изменений).
**Объём:** **5 фич, 37 задач** (T-1666…T-1702).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected**: 3 **Medium** — F4 overclaim ротации в
`plans/ARCHITECTURE.md` (§10/§25/§37), F5 транзиенты аватаров на 2 из 6 сайтов (rate-limit залипал в негатив-кэш
на час + трейс), F2 дублирование меню качества (T-1679). Все закрыты @Builder (CANCELLED-пометки в
`plans/ARCHITECTURE.md:326,328,616,624,628`; ветка `except (TelegramRetryAfter, TelegramNetworkError)` на **всех 6**
сайтах `web/api/avatars.py` + тесты некэширования; единый хелпер `services/media_send.py`, обе ветки делегируют).
Low L1–L8 закрыты (`plans/reports/round10.17_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium / 2 Low / 3 Info**. Medium **S10.17-1** (docs-only overclaim
ротации в архивной спеке 10.16 F5) **закрыт @Architect на Merge** (CANCELLED-баннер, DoD помечены); Low **S10.17-2**
(текст бейджа при `cognition==null`) и **S10.17-3** (доки-счётчики — синхронизированы с 6007) — техдолг/не блокеры;
Info S10.17-4/-5/-6 — не блокеры (`plans/reports/round10.17_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§38** + связанные §1/§5/§8/§9/§25).
Артефакты в архиве: `spec.md` + `tasks.md` (×5) + ADR-1017-1 (`adr-1017-1-miniapp-hostname-dns.md`),
ADR-1017-2 (`adr-1017-2-tool-download-quality.md`, **SUPERSEDE ADR-1016-1 §2 п.3/§3**),
ADR-1017-3 (`adr-1017-3-sleep-badge-countdown.md`).
**Симптомы ТЗ закрыты:** F1 — диагностика мини-аппа (HEAD `/web/`+`/healthz`, host-only startup-лог, no-CDN-гейт
с vendor) — живой DNS/Android-смоук @DevOps; F2 — tool-скачивание реально доводит `probe → tdq:<height> →
needs_quality` + callback; F3 — бейджи Сна показывают остаток / `до HH:MM` (+glow), эмодзи целы; F4 — пометки
ОТМЕНЫ ротации в README/ARCHITECTURE/backlog/архиве, кода ноль; F5 — политика логов на всех 6 сайтах
`web/api/avatars.py`, brotli WONTFIX (Caddy `zstd+gzip`).
**Фичи (финал, все ✅ COMPLETED):** F1 `miniapp-mobile-dns-round1017` (T-1666…T-1674, 9) ·
F2 `tool-download-quality-round1017` (T-1675…T-1684, 10) · F3 `sleep-badge-countdown-round1017` (T-1685…T-1691, 7) ·
F4 `ssh-rotation-cancelled-round1017` (T-1692…T-1695, 4) · F5 `warnings-hygiene-round1017` (T-1696…T-1702, 7).
Пути артефактов → **`plans/archive/*-round1017/`**.

**🧾 Техдолг / гейты (10.17):** Low **S10.17-2** (при `cognition==null` бейджи дают «Сон через —»/«Глубокий сон
через —» вместо чистого `—`; §3.4 спеки vs псевдокод §3.2 противоречивы — закреплено тестами, функц. вреда нет);
Info **S10.17-4** (tool-путь скачивания не вызывает `log_download_env_once()` — паритет диагностики),
**S10.17-5** (callback `tdq:` не проверяет hot-флаг `flags.download_enabled`), **S10.17-6** (`/healthz` отдаёт
`APP_VERSION` — принято F1 §3.1 L8; `query=%r` — pre-existing, вне диффа). **WONTFIX** — brotli (в репо build-time
only; Caddy требует `xcaddy`; `zstd+gzip` активны). **Открытые @DevOps-гейты (Step 9):** DNS/Android-смоук
(**T-1667/T-1668/T-1671/T-1673** — F1), подтверждение `zstd+gzip`/`Content-Encoding` (**T-1699** — F5).
**§4 ротация SSH — CANCELLED** (закрыта отменой, а не выполнением; **не открытый гейт**).

**Статус:** ✅ **COMPLETED + ЗААРХИВИРОВАН** (Step 8 @PM, 14.09.2026). Деплой-статус добавит @Memory после
шага 9 (@DevOps). Ниже — исторический документ планирования эпика (Step 1 @PM + Step 2 @Architect).

**Эпик:** `Epic: UPD3 багфиксы round1017` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (**UPD3**, строки 155–160); смежное — **UPD2** (строки 148–153, `DownloadError`/мобильный мини-апп).
**HEAD при планировании:** `772f192` (docs-синхронизация 10.16). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5936 passed / 0 failed**; каталог-инвариант **REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19** (**Δ=0**); SQLite **v9**; прод `eb3fd4a` / PID **1976836**.
Преемник — 10.16 (`plans/archive/*-round1016/`, 5 фич COMPLETED+DEPLOYED, 41 задача T-1625…T-1665).
**Контекст Step 0 (@Memory):** §1 — `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL` (`config/settings.py:170-173,987-989`), `/menu` (`handlers/menu.py:48-66`) и домен/схема/путь **не менялись** в 10.13–10.16; в `web/` внешних CDN нет (self-host 10.16) → `ERR_NAME_NOT_RESOLVED` = сбой резолва **топ-домена `admin-bot.duckdns.org`** на Android (A→`198.46.175.136`, AAAA нет). §2 — ADR-1016-1 (10.16) явно нормировал «quality в JSON-Schema НЕ добавляется» → **нужен SUPERSEDE**. §3 — бейджи показывают **целевой час**, не остаток (`web/app.js:1210-1245`, `web/api/memory_agi.py:75-88,425-546`). §4 — **ротация ОТМЕНЕНА** (docs-only, без кода). §5 — 3 WARNING `web/api/avatars.py` (генеральный `except` + `exc_info=True`) + «brotli» (в репо только build-time; Caddy brotli требует плагина, zstd+gzip уже включены).
**Инварианты:** каталог-Δ=0, **R17**, **R16**, порядок роутеров `bot.py` (только DI-kwargs), `media/`/`.env` не трогать, **не возвращать внешние CDN**, **Caddy/DNS — вне репо (@DevOps)**.

**5 фич (нумерация продолжает T-1665 → T-1666…T-1702, 37 задач):**

| # | Фича (папка) | Тип | ТЗ / UPD3 | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `miniapp-mobile-dns-round1017` | frontend+infra (DNS @DevOps) | **UPD3 §1** (стр. 155–156) + UPD2 §4 | — (внешняя инфра @DevOps) | **P0** (прод-блокер) | T-1666…T-1674 (9) |
| **F2** | `tool-download-quality-round1017` | backend (tools/download/LLM) | **UPD3 §2** (стр. 157) + UPD2 §1 | — (гейт `flags.download_enabled`) | **P0** (прод-баг) | T-1675…T-1684 (10) |
| **F3** | `sleep-badge-countdown-round1017` | frontend | **UPD3 §3** (стр. 158) | — (данные `/api/memory/cognition/status` уже есть) | P1 | T-1685…T-1691 (7) |
| **F4** | `ssh-rotation-cancelled-round1017` | docs (**без кода**) | **UPD3 §4** (стр. 159) — **ОТМЕНА** | 10.16 F5 `security-rotation-finalize-round1016` (**отменяется**) | **P0 (doc)** | T-1692…T-1695 (4) |
| **F5** | `warnings-hygiene-round1017` | backend+docs/infra | **UPD3 §5** (стр. 160) | — (Caddy — @DevOps, вне репо) | P2/P3 | T-1696…T-1702 (7) |

**Рекомендуемый порядок исполнения:** **F2 → F1 → {F3 ∥ F5} → F4.**
Обоснование: **F2** — прод-блокер скачивания (tool спрашивает качество; SUPERSEDE ADR-1016-1); **F1** — прод-блокер мобильного мини-аппа (диагностика DNS — @DevOps, может идти параллельно F2, разные плоскости); **F3** — UI-баг (независим по файлам `web/app.js`); **F5** — гигиена (не блокер); **F4** — docs-only, можно последней. **⚠️ F1 и F3 обе трогают `web/` (F1 — только при регрессе; F3 — `app.js`), синхронизировать при параллельной работе. F2 — backend, конфликтов с F1/F3 нет.**

**Контент по фичам (сжато):**
- **F1 (`miniapp-mobile-dns`):** Android `net::ERR_NAME_NOT_RESOLVED`, десктоп ок; после 10.16 внешних CDN нет, домен/путь не менялись → сбой резолва топ-домена. Гипотезы: блокировка `duckdns.org` мобильными операторами; протухшая/пустая запись DuckDNS (A→`198.46.175.136`, AAAA нет); Android Private DNS/DoH; кэш. Нужны: DNS-чек-лист @DevOps (резолверы/операторы/AAAA/LE), живой Android-смоук, регресс-аудит репо (git-история `settings.py:170-173,987-989`, `menu.py:48-66`, `web/*`), возможный фоллбэк hostname (ADR), статический гейт «нет внешних CDN».
- **F2 (`tool-download-quality`):** `_download_media` (`services/tool_router.py:564-622`) не скачивает и не спрашивает качество; Fast-Track (`handlers/video_download.py:284-343`) — эталон. **SUPERSEDE ADR-1016-1** в части «quality в JSON-Schema отклонён» (новый ADR-1017-2); `quality` (enum `_DOWNLOAD_QUALITIES`) в схему; запрос качества как Fast-Track; pending(url/qualities/TTL); фикс падения; `services/media_send.py`; R17; регресс-тесты (direct `.mp4` + платформа, моки yt-dlp/cobalt); лимиты tool-loop 4/2 — не менять.
- **F3 (`sleep-badge-countdown`):** `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1210-1245`) показывают `next_wake_at`/`next_run_at` как `HH:MM`; требуется остаток (`Сон через 2ч 15м`, `Глубокий сон через …`), вне фазы вместо «выключен»; в фазе — `до HH:MM` (`active_until`) + свечение; **эмодзи не трогать**; база `now` — `generated_at`; новый `fmtCountdown`; `fmtClock` не ломать.
- **F4 (`ssh-rotation-cancelled`):** решение владельца — секреты в untracked `plans/current_task.md` — норма, ротация **не нужна**; **отменить** задачу 10.16 F5; docs-only: пометка в backlog/архиве + README без overclaim; кода — ноль; R17.
- **F5 (`warnings-hygiene`):** 3 WARNING `web/api/avatars.py` (`:146-148,180-182,208-211/220-223` — генеральный `except Exception` + `exc_info=True` на ожидаемых сбоях) → политика уровней (ожидаемое — debug/без трейса; неожидаемое — WARNING, R17-safe); «brotli»: в репо **build-time only** (`scripts/requirements-font.txt`, OD17), Caddy brotli требует `xcaddy`/`http.encoders.brotli`, `zstd+gzip` уже включены (10.16) → решение+доки (Caddy — @DevOps).

**Покрытие UPD3 → фичи (`plans/current_task.md`):**

| Раздел UPD3 | Фича(и) |
|---|---|
| **§1** «Админка на десктопе работает, на Android `net::ERR_NAME_NOT_RESOLVED`; началось после последних ТЗ» (стр. 155–156) | **F1** |
| **§2** «Через tool calling видео не скачивается и не спрашивает качество (должно спрашивать); прямой путь — ок» (стр. 157) | **F2** |
| **§3** «"Сон через 11:00" → остаток до начала; "Глубокий сон выключен" → остаток; в фазе — "до HH:MM", бейдж светится; эмодзи не трогать» (стр. 158) | **F3** |
| **§4** «Секреты в файле — норма, файл не в репо, ротация не нужна — **отмени задачу**» (стр. 159) | **F4** (отмена задачи 10.16 F5, **без кода**) |
| **§5** «3 WARNING в аватарах (старый код); "brotli" требует плагина Caddy — обработать» (стр. 160) | **F5** |
| Смежное **UPD2 §4** (стр. 153): мини-апп Android + «~1 минута» | **F1** (повтор/эскалация) |
| Смежное **UPD2 §1** (стр. 149–150): `DownloadError` tool/Fast-Track | **F2** |

**Открытые вопросы для @Architect:** стратегия hostname/DNS и граница «репо vs инфра», живой Android-смоук (F1, T-1666); контракт запроса качества в tool-loop + формат `quality` в JSON-Schema + pending/TTL + SUPERSEDE ADR-1016-1 (F2, T-1675); формат остатка/точность/поведение `enabled=false`, «эмодзи не трогать» (F3, T-1685); формулировка пометки об отмене ротации и README-политика (F4, T-1692); классификация 3 WARNING + решение по brotli/`xcaddy` (F5, T-1696).
**Статус (историч.):** ✅ **COMPLETED + ЗААРХИВИРОВАН** (Step 8 @PM, 14.09.2026). Папки — `plans/features/*-round1017/` (5) → перенесены в `plans/archive/*-round1017/`. **@PM код не пишет.**

## Раунд 10.16 (14.09.2026): Багфиксы скачивания + доставка Гайда + полный аудит + мобильный мини-апп + ротация секрета — 5 фич — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (Step 8 @PM + Step 9 @DevOps + Step 10 @Memory, 14.09.2026 · commit `eb3fd4a`)

**✅ ИТОГ 10.16 (14.09.2026):** реализация завершена, все **5 фич заархивированы** — перенесены
`plans/features/*-round1016/` → **`plans/archive/*-round1016/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5936 passed / 0 failed** (база 10.15 = 5774 → **+162**; итерация 1 — 5910);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19); новых ключей нет.
БД: **новых миграций нет** (SQLite остаётся **v9**; PG без изменений; F2 — DML-миграция канона гайда, `canon_version`/`canon_delivered_version`).
**Объём:** **5 фич, 41 задача** (T-1625…T-1665).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected**: **Critical** F4 — CSP `script-src 'self'` без `'unsafe-eval'`
ломает рантайм-компилятор Vue (`Function()`), мини-апп не монтируется; **High** F1 — логирование URL/`str(exc)` в
`tools/video_downloader.py` при заявленном «R17-скан чист»; **High** F2 — доставка канона гайда не гарантирована
(нужен ручной reset); **High** F5 — README рапортовал о невыполненной ротации SSH как о факте. Все закрыты @Builder
(CSP-вариант A `'unsafe-eval'` + поведенческий гейт `tests/js/vue_mount_test.js`; caplog-тесты R17; одноразовая
форс-доставка канона с маркером; честная модальность README); Medium/Low итер.1 закрыты (`plans/reports/round10.16_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты High S10.16-1 — R17-утечка URL на
youtube-пути, Medium S10.16-2 — force-доставка без бэкапа), остаётся **Low 1** — `S10.16-9` (latent hardening)
(`plans/reports/round10.16_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§37** + связанные §1/§3/§5/§9).
Артефакты в архиве: `spec.md` + `tasks.md` (×5) + ADR-1016-1 (`adr-1016-1-download-contract.md`),
ADR-1016-2 (`adr-1016-2-selfhost-csp.md`), ADR-1016-3 (`adr-1016-3-guide-canon-versioning.md`) + `ssh-rotation-checklist.md`.
**Симптомы ТЗ закрыты:** F1 — tool-путь `download_media` (невалидный `"direct"` → `ValueError`) + Fast-Track
probe-диагностика; F2 — фактическая доставка «Гайда по фичам» (версионирование канона, force-reset, PG-only write-path);
F3 — полный аудит 10.13–10.15 + 7 смоук-наборов + FIX Low-техдолга (S10.13-6b/-13, R10.15-4/-10/-11);
F4 — мини-апп на Android (self-host CDN/Vue/Chart.js/Tailwind, CSP, сокращение загрузки); F5 — git-гигиена
`current_task.md` + скан секретов + README/R17.
**Фичи (финал, все ✅ COMPLETED):** F1 `download-fix-round1016` (T-1625…T-1633, 9) · F2 `guide-delivery-round1016`
(T-1634…T-1641, 8) · F3 `audit-recent-epics-round1016` (T-1642…T-1650, 9) · F4 `miniapp-mobile-round1016`
(T-1651…T-1659, 9) · F5 `security-rotation-finalize-round1016` (T-1660…T-1665, 6).
Пути артефактов → **`plans/archive/*-round1016/`**.

**🧾 Техдолг Low (ОТКРЫТ, 10.16 — не блокеры):** `S10.16-9` (latent hardening: 4 raise-сайта
`tools/video_downloader.py:767,772,899,904` интерполируют `{exc}` / тело cobalt-ответа; доступного лог-пути,
печатающего сообщение, нет — утечки нет); **WONTFIX** `S10.13-9` (Timeline-лор in-memory inject vs
`chat_lore_history` — осознанный источник), `S10.13-11` (LIKE-маркер парадигм матчит 2 сериализации — в проде
невоспроизводимо), `R10.14-4` (`dynamic_traits` без `chat_id` — модель «общий характер бота», не утечка).
Источник — `plans/reports/round10.16_scanner_audit.md` §2/§5 + `plans/reports/round10.16_audit.md` §3.

**✅ ГЕЙТЫ ЗАКРЫТЫ ДЕПЛОЕМ (@DevOps Step 9 + @Memory Step 10, 14.09.2026):** **T-1657** — DNS A→198.46.175.136
(AAAA нет), LE notAfter 2026-11-28, `/web/` GET 200 + CSP; Caddy `encode zstd gzip` включено (backup) — сжатие
есть. **T-1641** — гайд доставлен: `canon_version=2`, `canon_delivered_version=2`, `canon_drift=False`,
`prev_html` сохранён, `html_len==seed_len==4592`. **T-1661/T-1664** — SSH-ключ работает; парольный вход
сохранён намеренно (по требованию владельца), полная ротация пароля — по желанию владельца. Прод-смоук
скачивания (F1) — ручной шаг владельцу. **R17-долг (repo-wide):** `plans/current_task.md` содержит SSH-пароль
в рабочей копии (untracked, `.gitignore:70`; в истории утечки нет — скан чист).
**⚠️ ОТМЕНА (UPD3 §4, раунд 10.17):** задача ротации SSH признана **НЕ НУЖНОЙ** — секреты в untracked
`current_task.md` являются нормой, файл не попадает в репозиторий. R-запись выше **не является открытым
действием**; фича F4 10.17 `ssh-rotation-cancelled-round1017` снимает её docs-пометкой **без кода**.
**Статус:** ✅ **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (14.09.2026). Реализация @Builder (F1–F5),
@Reviewer **APPROVED** (итерация 2; итер.1 Rejected — Critical CSP `script-src 'self'`), @Scanner **0 C/H/M**
(Low 1 — `S10.16-9`), @Architect — `plans/ARCHITECTURE.md` **§37**. Артефакты: **`plans/archive/*-round1016/`**
(**5 папок**). **Деплой:** commit **`eb3fd4a`**, push `18a9aa1..eb3fd4a`, прод fast-forward `d01a539..eb3fd4a`,
`admin_bot` active PID **1976836**, `/api/health`=**200**, миграций БД нет. KG-синхронизация (Step 10 @Memory):
эпик → COMPLETED+DEPLOYED, релиз-узел `release-round1016`.
Ниже — исторический документ планирования эпика (Step 1 @PM + Step 2 @Architect).

**Эпик:** `Epic: Багфиксы + полный аудит round1016` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (**UPD2**, строки 148–153) + §1–§7 (строки 1–76). **HEAD при планировании:** `18a9aa1`
(docs-синхронизация 10.15). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5774 passed / 0 failed**; `node --check web/app.js` clean;
`node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант **REGISTRY 435 / GROUPS 90 / Settings 406 /
categorized 411 / mapped 88 / `TAB_RULES` 19** (**Δ=0**, новых ключей нет); SQLite **v9** (миграций БД нет).
Преемник — 10.15 (`plans/archive/*-round1015/`, 9 фич COMPLETED+DEPLOYED, 76 задач T-1549…T-1624).
**Контекст @Memory Step 0:** `plans/current_task.md` **не отслеживается git** (`.gitignore:70`; `git ls-files` — «did not match»),
в истории пароля нет, но рабочая копия содержит SSH-пароль (`:62-65`) → ротация (repo-wide R17-долг).
Остаются: **R17** (секреты `{configured,last4}`), **R16** (id — ключ), порядок роутеров `bot.py` (только DI-kwargs),
`media/`/`.env` не трогать, self-host DOMPurify/vis-network, пин-тесты каталога.

**5 фич (нумерация продолжает T-1624 → T-1625…T-1665, 41 задача):**

| # | Фича (папка) | Тип | ТЗ / UPD2 | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `download-fix-round1016` | backend (tools/download) | **UPD2 §1** (+§1 строки 3-8) | — (гейт: `flags.download_enabled`) | **P0** (прод-баг) | T-1625…T-1633 (9) |
| **F2** | `guide-delivery-round1016` | backend+docs | **UPD2 §2** (строка 151) + §7 | — | P1 (прод-регресс) | T-1634…T-1641 (8) |
| **F3** | `audit-recent-epics-round1016` | test/audit | **UPD2 §3** (строка 152) | **F1, F2** (их результаты) | P1 | T-1642…T-1650 (9) |
| **F4** | `miniapp-mobile-round1016` | frontend+infra | **UPD2 §4** (строка 153) | — (Caddy/DNS — @DevOps, вне репо) | P1 | T-1651…T-1659 (9) |
| **F5** | `security-rotation-finalize-round1016` | security+docs | **UPD2 §0** (строка 150) + R17 | **F1–F4** (финализация) | **P0** (безопасность) | T-1660…T-1665 (6) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → {F3 ∥ F4} → F5.**
Обоснование: F1 — прод-блокер скачивания (tool `download_media` передаёт невалидный `"direct"`; Fast-Track probe);
F2 — прод-регресс доставки «Гайда» (миграция пропущена из-за дрейфа PG; write-path в tracked `info_text.md`);
F3 (аудит 10.13–10.15 + смоуки) опирается на результаты F1/F2, но может идти параллельно F4;
F4 (мини-апп Android) независим по файлам (`web/*`), серверная часть — @DevOps; F5 — последняя (ротация секрета + Step 9–10).
**⚠️ F3 делит `tests/*` с F1/F2 — новые смоук-файлы; F4 делит `web/index.html`/`web/app.js` только сам с собой.**

**Контент по фичам (сжато):**
- **F1 (`download-fix`):** tool-путь `services/tool_router.py:592-594` всегда `download(url, "direct")` →
  `tools/video_downloader.py:695-705` `_normalize_quality("direct")` → `int("direct")` = `ValueError` →
  `DownloadError("invalid quality: 'direct'")` (YouTube/TikTok → гарантированный сбой, регресс F8 10.15).
  Fast-Track `handlers/video_download.py:326-331` `probe(url)` → `DownloadError` → `VD_ERROR_PHRASES`
  (`tools/video_download_phrases.py:14`); probe зависит от cookies/proxy/POT/cobalt. Нужны: валидное ветвление
  direct vs авто/качество, категорийная R17-диагностика, смоуки с моками yt-dlp/cobalt.
- **F2 (`guide-delivery`):** «Гайд по фичам» = legacy `content.info_how_it_works` (`services/info_service.py`
  `DEFAULT_INFO_TEXT`/`PREV_DEFAULT_INFO_TEXT`, сид `info_text.md`); миграция `services/config_cache.py:235-266`
  перезаписывает только если PG == `PREV_DEFAULT_INFO_TEXT`, иначе WARNING+пропуск (прод-PG дрейфовал → гайд не обновился).
  `InfoService.save_text` (`info_service.py:202-217`) пишет в **tracked** `info_text.md` → дрейф/блок fast-forward pull.
  Нужны: версионирование канона (реестр PREV/хэши), force-reset, PG-only/неблокирующий write-path, байт/смоук-тесты.
- **F3 (`audit-recent-epics`):** полный аудит 10.13/10.14/10.15: ревизия логики и корнер-кейсов; смоуки «имитация
  реальной работы» (download/probe, tool-loop, guide, graph, sleep, nostalgia, persona); закрыть релевантный
  Low-техдолг (**S10.13-6b/9/11/13**, **R10.14-4**, **R10.15-4/-10/-11**); отчёт `plans/reports/round10.16_audit.md`.
- **F4 (`miniapp-mobile`):** `net::ERR_NAME_NOT_RESOLVED` на Android (десктоп ок); «~1 минута» — таймауты блокирующих
  CDN + крупные несжатые файлы. `web/index.html` внешние `<script>`: `telegram.org` (:11), `cdn.tailwindcss.com` (:12),
  `unpkg.com/vue@3` (:3633), `cdn.jsdelivr.net/npm/chart.js@4` (:3638); нет CSP/bundle/service worker; `index.html` ~235 КБ
  + `app.js` ~285 КБ. Нужны: self-host CDN (паттерн DOMPurify/vis-network, ADR-1013-2) или безопасная замена, CSP,
  минификация/бандлинг, диагностика DNS домана (`config/settings.py:171-173`, `handlers/menu.py:53-63`); Caddy/DNS — @DevOps.
- **F5 (`security-rotation-finalize`):** подтвердить, что `plans/current_task.md` не в git (`.gitignore:70`); ротировать/отозвать
  SSH-пароль (`current_task.md:62-65`, сервер `198.46.175.136`, вне репо, @DevOps); README/R17-hardening; подготовка Step 9–10.

**Инварианты раунда (в каждой tasks.md §3):** **DDL/SQL не требуется** (миграций БД нет); **каталог-Δ = 0** —
**REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19** (новые ключи не вводятся);
**R17** секреты `{configured,last4}` (в логи — без URL/текстов/секретов); **R16** id — ключ; порядок роутеров `bot.py`
не трогать (только DI-kwargs); `media/`/`.env` не трогать; **Caddy/DNS — вне репо (@DevOps)**; новых CDN/`v-html` без
санитайза нет; байт-канон info не ломать без слепка; **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`,
`node tests/js/routing_test.js` → `JS-UNIT-OK`, R17-скан, пин-тесты каталога, русские conventional commits.

**Покрытие UPD2 / ТЗ → фичи (`plans/current_task.md`):**

| Раздел UPD2 / ТЗ | Фича(и) |
|---|---|
| **UPD2 §0** «Проверь, что `current_task.md` не попал в репозиторий» (+ R17-долг) | **F5** |
| **UPD2 §1** «Ошибка скачивания через tool calling (`download_media`); Fast-Track «Бот, скачай» → "битая ссылка"» | **F1** (+ **F3** — смоуки) |
| **UPD2 §2** «Задача 7 не выполнена — гайд по фичам в Справке остался как был» | **F2** (+ **F3** — смоук guide) |
| **UPD2 §3** «Перепроверь всё последними эпиками, полный аудит, тесты, смоук-тесты, логика, корнер-кейсы» | **F3** |
| **UPD2 §4** «Миниапп не запускается на Android `ERR_NAME_NOT_RESOLVED`; на десктопе ок; ранее ~1 минута загрузки» | **F4** |
| §1 «Умная выборка Графа Памяти» (10.15) | **F3** (аудит/смоук graph) |
| §2 «Диагностика и разблокировка Сна» (10.15) | **F3** (аудит/смоук sleep) |
| §3 «Ревамп Ностальгии» (10.15) | **F3** (аудит/смоук nostalgia) |
| §6 «Роутинг команд / Имя / Приоритеты» (10.15) | **F3** (аудит/смоук persona/routing) |
| §7 «Обновление "Гайда по фичам"» | **F2** |

**Открытые вопросы для @Architect:** контракт `download(url, quality?)` и ветвление direct vs авто (T-1625);
формат реестра PREV-слепков и семантика force-reset гайда (T-1634); глубина смоуков и приоритет Low-техдолга (T-1642);
стратегия CSP/Tailwind/бандлинга и DNS-диагностики (T-1651); политика ротации секрета (SSH-ключи vs пароль, T-1660).
**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (исторический документ планирования; артефакты — `plans/archive/*-round1016/`, 5 папок).
**@PM код не пишет.**


## Раунд 10.15 (14.09.2026): Багфиксы Графа памяти, Воркера Сна и Ностальгии + Tool Calling — 9 фич — ✅ ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН (14.09.2026; архив @PM, деплой @DevOps/@Memory 14.09.2026)

**✅ ИТОГ 10.15 (14.09.2026):** реализация завершена, все **9 фич заархивированы** — перенесены
`plans/features/*-round1015/` → **`plans/archive/*-round1015/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5774 passed / 0 failed** (база 10.14 = 5589 → **+185**; итерация 1 — 5761);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19);
новых ключей нет (пороги сна/окно ностальгии/tool-лимиты — переиспользуемые значения + код-константы).
БД: **миграций нет** (SQLite остаётся **v9**; PG — без новых таблиц/колонок; политика DDL 10.14 сохранена как
разрешение, но в 10.15 не применялась).
**Объём:** **9 фич, 76 задач** (T-1549…T-1624).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected** по трём блокерам: **H1** F5 — `enabled=false`
не гасил активность бейджа Сна в окне (фронт показывал свечение вместо «☀️/🌅 выключен»); **M1** F6 — нет правой
границы слова у триггеров («Бот, загуглика» консьюмилась); **M2** F6 — безусловный yield в `direct_chat` терял
сообщение при выключенном модуле. Все закрыты @Builder с регресс-тестами (`plans/reports/round10.15_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты Medium R10.15-1 link-first, R10.15-2
`get_bot_health` vs `checkup_enabled`, R10.15-3 ложный консьюм обычной речи), остаются **3 Low** + 3 Info — техдолг
(`plans/reports/round10.15_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§36** + связанные §1/§3/§5/§9/§25).
Артефакты в архиве: `spec.md` + `tasks.md` (×9) + ADR-1015-1 (`adr-1015-1-command-prefix-policy.md`),
ADR-1015-2 (`adr-1015-2-graph-sampling.md`), ADR-1015-3 (`adr-1015-3-tool-calling.md`).
**🚀 Деплой (Step 9–10, 14.09.2026) — ✅ DEPLOYED:** commit **`d01a539`**
(`feat(services,web,api,docs,plans): раунд 10.15 — … (тесты 5774)`), push origin/master `798e044..d01a539`;
прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `eb2a232..d01a539` (⚠️ потребовалась **ручная
разблокировка серверного дрейфа `info_text.md`**: backup + `git stash` → pull); `systemd admin_bot`
**active (running) PID 1860445**; `/api/health` = **200**, `/api/memory/graph` = **401**,
`/api/memory/stats` = **401** (не 500). **Миграций БД нет** (SQLite **v9**, PG без изменений);
`.env` не редактировался. **APP_VERSION 2.57.0** — без бампа. Релиз — KG `release-round1015`.
**Фичи (финал, все ✅ COMPLETED):** F1 `graph-sampling-centrality` (T-1549…T-1557) · F2 `graph-frontend-physics-search`
(T-1558…T-1565) · F3 `sleep-unblock-diagnostics` (T-1566…T-1574) · F4 `nostalgia-prompt-revamp` (T-1575…T-1583) ·
F5 `status-graph-ui-relocation` (T-1584…T-1592) · F6 `command-prefix-persona-routing` (T-1593…T-1602) ·
F7 `guide-rewrite-persona` (T-1603…T-1609) · F8 `hybrid-tool-calling` (T-1610…T-1618) · F9 `recent-history-tool`
(T-1619…T-1624). Пути артефактов → **`plans/archive/*-round1015/`**.

**🧾 Техдолг Low (ОТКРЫТ, 10.15 — не блокеры):** `R10.15-4` (yield в `direct_chat` по hot-флагу vs
startup-регистрация download-роутера 4e — осознанный follow-up), `R10.15-10` (link-first привязан к **первому**
вхождению имени), `R10.15-11` (триггер anywhere + **любой** http-URL консьюмит речь); **Info 3:** (1) repo-wide
**R17-долг** — `plans/current_task.md:62-65` содержит SSH-доступ и пароль (файл в `.gitignore`, но уже в истории —
рекомендовано **сменить/отозвать пароль и вычистить историю**; к 10.15 не относится), (2) реестр-комментарий F6
соответствует spec, (3) `info_text.md` §5 `Бот, живой?` — границы триггера корректны. Источник —
`plans/reports/round10.15_scanner_audit.md` §5.
**Статус:** ✅ **ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН** (14.09.2026). @PM Step 8 (Archive) + @DevOps Step 9
(commit `d01a539` / push / прод fast-forward / restart / live-верификация — миграций БД нет) выполнены;
финальные метрики + KG + деплой-статус — @Memory Step 10 (14.09.2026). Эпик помечен **COMPLETED + DEPLOYED** в knowledge graph.
Ниже — исторический документ планирования эпика (Step 1 итер.2 @PM + Step 2 @Architect).

**Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (разделы 1–7 + **UPD п.1–5**, строки 79–145, включая финальный
деплой-чеклист). **HEAD при планировании:** `798e044` (docs-коммит 10.14). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5589 passed / 0 failed** (база финала 10.14); каталог-инвариант
**REGISTRY 435 / GROUPS 90 / Settings 406 / categorized 411 / mapped 88 / `TAB_RULES` 19**; SQLite **v9**.
Преемник — 10.14 (`plans/archive/*-round1014/`, все 8 фич COMPLETED+DEPLOYED, 72 задачи T-1477…T-1548).
Снятые инварианты 10.14 (DDL разрешён) сохраняются как разрешение, но в 10.15 DDL **не требуется**.
Остаются: **R17** (секреты `{configured,last4}`), **R16** (id — ключ), порядок роутеров `bot.py`
(только DI-kwargs), `media/`/`.env` не трогать, пин-тесты каталога, self-host DOMPurify/vis-network.

**9 фич (нумерация продолжает T-1548 → T-1549…T-1624, 76 задач):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `graph-sampling-centrality-round1015` | backend | §1 (алгоритм/сироты) | — | **P0** | T-1549…T-1557 (9) |
| **F2** | `graph-frontend-physics-search-round1015` | frontend | §1 (vis-network) | **F1** | P1 | T-1558…T-1565 (8) |
| **F3** | `sleep-unblock-diagnostics-round1015` | backend | §2 | — | **P0** (блокер сна) | T-1566…T-1574 (9) |
| **F4** | `nostalgia-prompt-revamp-round1015` | backend+prompt | §3 | — | P1 | T-1575…T-1583 (9) |
| **F5** | `status-graph-ui-relocation-round1015` | frontend+API | §4+§5+UPD§3 | **F3** (частично, API), **F1/F2** | P1 | T-1584…T-1592 (9) |
| **F6** | `command-prefix-persona-routing-round1015` | backend (routing) | §6 + **UPD §1-2** | — (`flags.persona_enabled`/имя 10.14) | **P0** (регресс-риск) | T-1593…T-1602 (10) |
| **F7** | `guide-rewrite-persona-round1015` | docs+backend+UI | §7 | **F6** (+F5) | P2 | T-1603…T-1609 (7) |
| **F8** | `hybrid-tool-calling-round1015` | backend (LLM/tools) | **UPD §4** | **F6** (fast-track реестр) + существующий `tool_router`/`tool_loop` | P1 | T-1610…T-1618 (9) |
| **F9** | `recent-history-tool-round1015` | backend (LLM/tools) | **UPD §5** | **F8** (tool-loop/реестр/схемы) + **F6** | P1 | T-1619…T-1624 (6) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → F3 → F4 → {F5} → F6 → {F7 ∥ F8} → F9.**
Обоснование: F1 (backend-граф) — фундамент для F2 (фронт `barnesHut`/поиск показывает связный граф);
F3 (fallback порогов сна + `[Sleep]`-диагностика) независима и снимает блокер синтеза убеждений;
F4 (ностальгия) независима; F5 (релокация статистики + бейджи) частично опирается на аддитивное поле
`cognition/status` (согласовать с F3) и делит `web/index.html`/`web/app.js` с F2 — вливать после F2;
**F6** (префиксы/имя/приоритеты) — главный регресс-риск, **без рубильника** (триггер = непустое Имя);
**F7** (гайд) пишется по факту F6; **F8** (гибридный tool-calling) требует fast-track-приоритет F6 и
существующий `tool_router`/`tool_loop`; **F9** (`get_recent_history`) подключается к общему tool-сету F8.
**⚠️ F2, F5 делят `web/index.html`/`web/app.js` — исполнять/вливать ступенями (F2 → F5).**
**F1/F5 делят `web/api/memory_agi.py` — аддитивные поля согласовывать.**
**F4/F3 трогают `services/database.py`/`dream_worker.py`/`nostalgia_worker.py` — вливать согласованно с
пин-тестами каталога.**
**⚠️ F8/F9 делят `services/tool_schemas.py`/`tool_router.py` (аддитивно) — вливать ступенями (F8 → F9):
T-1611 F8 регистрирует `get_recent_history` из F9, T-1620 F9 добавляет саму схему — согласовать без разрыва
tool-сета.)**

**Контент по фичам (сжато):**
- **F1 (Умная выборка графа, §1 backend):** переписать `services/database.py:3610-3665` `graph_snapshot`:
  топ-50 сидов по **Degree Centrality** → раскрытие **всех смежных** узлов и рёбер → удаление **сирот**
  и висячих рёбер (закрывает техдолг **S10.13-14**); cap **120/240** (`web/api/memory_agi.py:58-59`)
  применяется ПОСЛЕ раскрытия; контракт `nodes/edges/truncated/limits` сохранён (R16). API
  `GET /api/memory/graph` (`memory_agi.py:500-520`) без ломки. Новые тесты `graph_snapshot`.
- **F2 (Физика графа + поиск, §1 frontend):** `barnesHut` в `renderCognitionGraph` (`web/app.js:5244-5283`,
  опции `:5259-5272`); инпут **«Поиск по графу»** в «Мониторинге Интеллекта» (`web/index.html:2911-2960`)
  → центрирование камеры на узле по `label` + подсветка; сохранить `reducedMotion`, `_cognitionGraphSig`,
  `destroy`, self-host vis-network (ADR-1013-2).
- **F3 (Разблокировка Сна + диагностика, §2):** динамический fallback порогов в `services/dream_worker.py:485-514`:
  «0 убеждений за 3 дня» → `min_cluster_size=2` / `min_importance_sum=8` (базовые 3/12 из
  `settings.py:1101-1103` переиспользуются); пре-гейт-лог формата
  `[Sleep] Chunks: 15, Clusters formed: 2, Max importance: 9 -> Skipped (threshold 12)` виден в панели
  «Логи» (`services/log_ring.py`); отдельный kill-switch **не вводится** (self-healing: fallback отключается
  при первом синтезированном убеждении; каталог-Δ=0, откат = `git revert`).
- **F4 (Ревамп Ностальгии, §3):** окно `memory.nostalgia_year_back_days_window` `±2`→`±10`
  (`settings.py:1173-1174`, `param_catalog.py:1535`, `nostalgia_worker.py:546-552`, Δ каталога 0);
  инжект **Лора чата** + **локальных мемов** (`database.py:3554` `list_chat_memes`, `lore_cache`/
  `chat_lore_store`) в user-блок `build_nostalgia_user` (`nostalgia_prompts.py:103-116`); переписать
  `NOSTALGIA_PROMPT` (`:21-25`) под «давнего участника» (ирония/сленг, анти-«робот-архивариус»),
  сохранив `{max_words}`/`UNCHANGED`; ADR-1013-3: PREV-слепок + байт-тесты, `PROMPT_MIGRATIONS` не трогать.
- **F5 (Релокация статистики + бейджи, §4+§5):** удалить карточку «Статистика графа памяти» из «Модулей»
  (`web/index.html:1452-1469`), консолидировать метрики в существующий блок «Сводки» (`:1804-1809`) —
  **без дубля**; бейджи `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1204-1224`): неактив
  `[☀️] Сон через [время]` / `[🌅] Глубокий сон через [время]` (без свечения), актив
  `[🌙] Сон до [время]` / `[🌌] Глубокий сон до [время]` (свечение); аддитивное поле API для
  активной фазы (либо расчёт на фронте); мобильный столбик (`index.html:2911-2927`), удалить
  «пробуждение ~11:00» (`:2923-2924`).
- **F6 (Префиксы команд / имя / приоритеты, §6 + UPD §1-2):** **флаг-рубильник `flags.command_prefix_enabled`
  ОТМЕНЁН** (UPD §1) — триггер системы = **непустое поле «Имя» Личности**: имя заполнено → префикс
  `<Имя>, ` и дефолтные `бот`/`ботик`/`ботяра` **отключаются**; имя пусто → префикс `Бот, `, дефолты
  активны. **Работает «из коробки»**, откат = `git revert` + очистка Имени. Точный реестр — **17 команд**
  (`найди`, `поищи`, `загугли`, `транскрипт`, `че за видос`, `о чем видео`, `поясни за видос`,
  `поясни за ссылку`, `че по ссылке`, `о чем статья`, `выжимка`, `ты в порядке`, `живой?` **[слово
  «собака» убрать]**, `чекни здоровье`, `скачай`, `загрузи`, `стяни`) + **исключения** `чекап`/`фактчек`
  (одним словом, **без** префикса). Новые модули `services/command_registry.py` (канон) и
  `services/command_prefix.py` (`active_name`/`split_prefix`/`name_mentioned`/`is_functional_command`);
  обязательный префикс у триггеров (`handlers/search.py:57-101`, `youtube.py:120-215`, `web.py:52-96`,
  `checkup.py:53-80`, `video_download.py:74-75`); при заданном имени — отключить дефолтные ботворды
  (`handlers/direct_chat.py:147-165`); функциональные команды — наивысший приоритет, **yield (UNHANDLED)**
  из direct_chat для download (4e), не уходят в LLM (порядок `bot.py:641-666` **не менять**). **ADR-1015-1.**
  **⚠️ Главный регресс-риск:** ломает `tests/test_epic72_gates.py:69` («эй, бот»→True) и
  `tests/test_direct_chat.py:2994-3010` («бот, загугли») — митигация: мягкий переход (пустой глобальный
  сид → прежнее поведение), пред-деплой чек-лист владельцу, правка тестов под новую семантику.
- **F7 («Гайд по фичам», §7):** переписать `DEFAULT_INFO_TEXT` (`services/info_service.py:20-70`) и
  `info_text.md` (байт-в-байт, `tests/test_info_service.py:28-45`) под **канонический реестр F6 (17+2)** и
  префиксы/имена; правило «Все команды требуют обращения: без имени — «Бот, скачай», с именем — «Олег,
  скачай»»; исключения `чекап`/`фактчек`; blockquotes/инлайн-код; сохранить ироничный стиль; второй гайд
  `content.intelligence_guide` (10.14); доставка нового канона в прод-PG идемпотентной миграцией
  `_migrate_info_how_it_works_v1015` по слепку `PREV_DEFAULT_INFO_TEXT` — **без затирания ручных правок**.
- **F8 (Гибридный вызов функций / Tool Calling, UPD §4):** основная LLM чата (`direct_chat`, DeepSeek)
  получает **JSON-Schema инструменты**; **regex Fast-Track сохраняется и приоритетнее** (F6: префикс+триггер
  → консьюм воркером, LLM не вызывается), свободная форма → `tool_call` через существующий
  `services/tool_loop.py`. Итоговый tool-сет — **7**: `query_chat_memory`, `dig_into_lore`,
  `execute_web_search` (существуют) + `summarize_video`, `download_media`, `get_bot_health` (**новые**) +
  `get_recent_history` (**F9**). Расширение `ToolDeps`(`video`/`downloader`/`health`) и `ToolContext`
  (`bot`/`reply_to_message_id`/`user_id`); `bot.py` — только DI-kwargs, порядок роутеров не трогать.
  **Корнер-кейс скачивания:** `download_media` исполняется на бэкенде и **сам шлёт MP4** (`_send_media`),
  а в LLM возвращается **фиктивный** `tool_response` `{"status":"success","message":"Файл успешно загружен
  в чат"}` (иначе модель «печатает» видео); при сбое — честный `status:"error"`, успех только после
  реальной отправки. Лимиты — **код-константы** (`TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2`),
  R17 (в логи только `tool`/`out_chars`/класс ошибки, без URL). **ADR-1015-3.**
- **F9 (Инструмент `get_recent_history`, UPD §5):** LLM получает тул чтения **сырого лога недавних
  сообщений (L1-окно)** — «что обсуждали 10 минут назад», «кто скинул ту ссылку», «кто прав в споре».
  Параметры: **`depth` (1..150)** — хронологический срез (`database.get_recent_messages`, ASC) **ИЛИ
  `query`** — поиск по сырой SQLite последних часов (FTS + фильтр окна + сортировка); при обоих —
  приоритет `query`; ни одного — `depth=50`. Стенограмма строго `Имя: текст` (R16: alias→author_name→user_id;
  медиа — маркером/текстом; пустой текст пропускается); chat-скоуп `ctx.chat_id`; при пустом результате —
  честная фраза (без галлюцинаций). Лимиты — **код-константы** (`_HISTORY_MAX_DEPTH=150`,
  `_HISTORY_SEARCH_LIMIT=80`, `_HISTORY_QUERY_WINDOW_SECONDS=12h`, `_HISTORY_MAX_SYMBOLS=3500`,
  `_HISTORY_TOOL_TIMEOUT=10s`); `get_recent_messages` **переиспользуется как есть** (DDL не требуется);
  R17. Базовая схема — в F8 (`TOOL_CALLING_TOOLS`), dispatch-ветка в `tool_router.py`.

**Инварианты раунда (в каждой tasks.md §3):** **DDL не требуется** (схема не меняется); **каталог-Δ = 0** —
**REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19**, новые ключи **не
вводятся** (флаг `flags.command_prefix_enabled` отменён; пороги сна, окно ностальгии, tool-лимиты —
переиспользуемые/код-константы; F8/F9 — `TOOL_MAX_ROUNDS=4`/`_TOOL_CALLS_PER_ROUND_MAX=2`/`_HISTORY_*` в коде);
**R17** секреты (в логах tool — только `tool`/`out_chars`/класс ошибки, без URL/текста); **R16** id — ключ;
порядок роутеров `bot.py` не трогать (только DI-kwargs: `ToolDeps(video/downloader/health)`); `media/`/`.env`
не трогать; правка промпт-канона ностальгии — PREV-слепок + байт-тесты, `PROMPT_MIGRATIONS` не трогать;
правка info-канона — идемпотентная миграция `_migrate_info_how_it_works_v1015` (не затирать ручное);
**новых `v-html` без санитайза/новых CDN нет** (DOMPurify/vis-network self-host); **feature-flag НЕ
требуется** (UPD §1 отменил рубильник для F6; F8/F9 — расширение существующего механизма, rollback =
`git revert`); **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`, `node tests/js/routing_test.js`
→ `JS-UNIT-OK`, пин-тесты каталога, R17-скан; русские conventional commits. Деплой-чеклист ТЗ
(ssh → pull → restart → status, plain-language отчёт) — за @DevOps/@PM на Step 9–10.

**✅ Open (закрыто @Architect, Step 2 итерация 1–2, 14.09.2026 — spec.md по всем 9 фичам + 3 ADR):**
- **F1:** невзвешенная Degree Centrality (число рёбер); 50 сидов — код-константа `GRAPH_SEED_NODES`
  (каталог-Δ=0); полный degree в узле; отсечение изолированных компонент; cap ПОСЛЕ раскрытия. **ADR-1015-2.**
- **F3:** fallback порогов как self-healing kill-switch (`services/dream_worker.py`, каталог-Δ=0);
  пре-гейт-лог `[Sleep] Chunks/Clusters/Max importance → Skipped`; источник «0 убеждений» — решён.
- **F4:** PREV-слепок обязателен, `PROMPT_MIGRATIONS` не трогаем; капы лора ≤600 симв., мемы ≤10×120;
  лор активного чата (manual→auto); окно `±10` по дефолту. **ADR-1013-3.**
- **F5:** аддитивные поля API (`active_until`/`ends_at`, расчёт на бэке); `.badge.glow`; мобильный столбик
  (flex-wrap); оконная семантика бейджей **утверждена владельцем (UPD §3, §3а спеки)**.
- **F6 (ключевое):** **флага нет** (UPD §1); per-chat имя → только глобальный sync-кэш
  `get_cached_global_name()`; эвристика склонений (имена ≥3 симв.); дефолтные ботворды off **iff
  `persona_enabled AND name non-empty`**; префикс применяется к 15 префиксным командам, `чекап`/`фактчек` —
  bare; `is_functional_command`-yield для download. **ADR-1015-1.**
- **F7:** доставка — идемпотентная миграция по слепку (не затирать ручное); канон = реестр F6 (17+2).
- **F8:** tool-сет 7 (3 существующих + 3 новых + `get_recent_history` F9); фиктивный `tool_response` для
  `download_media`; лимиты — существующие код-константы; layering через `services/media_send.py`. **ADR-1015-3.**
- **F9:** `depth≤150` ИЛИ `query` (приоритет `query`), стенограмма `Имя: текст`, chat-скоуп, лимиты —
  код-константы; `get_recent_messages` переиспользуется как есть (DDL не требуется).
**Остаточное на @Builder/@Reviewer:** R16/R17, идемпотентность info-миграции, регресс-риск F6 (живые чаты),
фиктивный success скачивания, пин-тесты каталога.

**Покрытие ТЗ (`plans/current_task.md`, разделы 1–7 + UPD п.1–5 → фичи):**

| Раздел ТЗ / UPD | Фича(и) |
|---|---|
| §1 «Умная выборка для Графа Памяти» | **F1** (backend) + **F2** (frontend) |
| §2 «Диагностика и разблокировка Сна» | **F3** |
| §3 «Ревамп Ностальгии» | **F4** |
| §4 «Релокация статистики графа» | **F5** |
| §5 «Редизайн бейджей Сна и мобильная вёрстка» | **F5** |
| §6 «Роутинг команд, Имя личности и Приоритеты» | **F6** |
| §7 «Обновление "Гайда по фичам"» | **F7** |
| **UPD §1** «Отказ от флага-рубильника; непустое Имя = триггер системы; «Бот, » при пустом» | **F6** (+ **F7** — правило в гайде) |
| **UPD §2** «Точный реестр 17 команд + исключения `чекап`/`фактчек`; `живой?` без слова «собака»» | **F6** (+ **F7**) |
| **UPD §3** «Оконная семантика бейджей Сна — утверждена» | **F5** |
| **UPD §4** «Гибридный вызов функций (JSON-Schema tools; regex Fast-Track; корнер-кейс скачивания)» | **F8** |
| **UPD §5** «Инструмент `get_recent_history` (depth≤150 / query, стенограмма `Имя: текст`)» | **F9** |
| Финальный блок «Деплой» (ssh/pull/restart/status/отчёт) | **@DevOps/@PM** (Step 9–10), не фича |

**Итог: все 7 разделов ТЗ + 5 пунктов UPD покрыты; 9 фич, 76 задач (T-1549…T-1624); папки заархивированы.**
**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (14.09.2026, @PM Step 8 Archive Phase). Планирование (Step 1 итер.2 @PM)
+ Step 2 @Architect — `spec.md` + `tasks.md` во всех **9** папках + 3 ADR (`adr-1015-1-command-prefix-policy`,
`adr-1015-2-graph-sampling`, `adr-1015-3-tool-calling`). Реализация @Builder (F1–F9), @Reviewer **APPROVED**
(итерация 2), @Scanner **0 C/H/M** (3 Low — техдолг, см. блок «ИТОГ 10.15»), @Architect — `plans/ARCHITECTURE.md`
**§36**. Артефакты: **`plans/archive/*-round1015/`** (**9 папок**). Деплой — @DevOps Step 9 (миграций БД нет).
**@PM код не пишет.**



**✅ ИТОГ 10.14 (13.09.2026):** реализация завершена, все **8 фич заархивированы** — перенесены
`plans/features/*-round1014/` → **`plans/archive/*-round1014/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5589 passed / 0 failed** (база 10.13 = 5392 → **+197**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
Каталог — санкционированный прирост (F1 origin/self-awareness, F2 persona-флаги, F6 `content.intelligence_guide`,
F8 `intel_reflection_*`): **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19).
БД: SQLite **v8→v9** (origin `bot_self_reply`, миграция `_migrate_self_origin_v9`); **PG** — `personas` /
`persona_traits` / `persona_state` (идемпотентный DDL).
**Объём:** **8 фич, 72 задачи** (T-1477…T-1548), все `[x]`.
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected** по трём High-блокерам: **H1** optimistic-409
персоны недостижим (`updated_at` не отдавался), **H2** RBAC-действие `edit_persona` не зарегистрировано,
**H3** новые per-chat ключи читались только глобально (`hot.get`); все закрыты @Builder и подтверждены
`file:line` + тестами (`plans/reports/round10.14_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты Medium R10.14-1 RBAC view/edit
`edit_persona` и R10.14-2 traits-LLM вне `worker_budget`), остаются **2 Low** + 2 Info — техдолг
(`plans/reports/round10.14_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§35** + связанные разделы).
Артефакты в архиве: `spec.md` + `tasks.md` (×8) + ADR-1014-1 (`adr-1014-1-persona-storage.md`),
ADR-1014-2 (`adr-1014-2-anti-echo-self.md`) + `settings-persistence-audit-round1014/report.md` + `inventory.tsv`.
**Фичи (финал, все ✅ COMPLETED):** F1 `anti-echo-self-reply` (T-1477…T-1486) · F2 `persona-storage-core`
(T-1487…T-1497) · F3 `persona-ui-tab` (T-1498…T-1504) · F4 `persona-traits-ribbon` (T-1505…T-1510) ·
F5 `settings-persistence-audit` (T-1511…T-1525) · F6 `help-guide-integration` (T-1526…T-1534) ·
F7 `status-layout-reorder` (T-1535…T-1540) · F8 `self-reflection-llm-provider` (T-1541…T-1548).

**🧾 Техдолг Low (ОТКРЫТ, 10.14 — не блокеры):** `R10.14-4` (`dynamic_traits` отдаются без фильтра `chat_id` —
оставлено **осознанно**, соответствует модели «общий характер бота» по F4), `R10.14-7` (warning
`closed 12 leaked aiosqlite connection(s)` — **pre-existing**, не регрессия), `L5` (**hot-path**: на каждый
direct-ответ 2 доп. PG-запроса `resolve_bot_persona`+`get_traits` + запись `persona_state`; кэш отсутствует —
оптимизация на будущее); **Info:** `I10.14-1` (прямой каскад v7→v9 юнит-тестами не покрыт — риска нет),
`I10.14-2` (FIFO-ротация traits глобальная, не per-chat — зафиксировать в ARCH). Источник —
`plans/reports/round10.14_scanner_audit.md` §5.
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.14 (@DevOps + Step 10 @Memory, 13.09.2026):** commit **`eb2a232`**
(`feat(services,web,api,docs,plans): раунд 10.14 — самосознание и личность бота, PG Persona и SQLite v9,
LLM-экстрактор, метрики Сводки, редактор Справки (тесты 5589)`); push origin/master `2edc65b..eb2a232`;
прод `nik@198.46.175.136:/var/www/admin_bot` fast-forward `8800bba..eb2a232`; `admin_bot`
**active (running) PID 1774527**; **миграции применены** (SQLite `PRAGMA user_version=9` / origin
`bot_self_reply`; PG `personas`/`persona_traits`/`persona_state`); `/api/health` = **200**,
`/api/persona/health` = **401** (не 500); `.env` не редактировался (дефолты безопасны, флаги ON в коде).
**APP_VERSION не бампился** (2.57.0). Статус эпика — **COMPLETED + DEPLOYED**. Step 10 @Memory —
метрики+синхронизация выполнены (`plans/metrics.md` строка 10.14; KG `release-round1014`,
`metric-snapshot-round1014-final`). Техдолг Low 2 (`R10.14-4`, `R10.14-7`) + `L5` + Info 2.
Ниже — исторический документ планирования эпика (Step 1 @PM).

**Эпик:** `Epic: Self-Awareness / Persona round1014` (@Memory, Step 0). **Источник ТЗ** —
`plans/current_task.md` (разделы 1–7) + **UPD владельца** (пп.1–5, отменяет DDL-free решения). **HEAD при
планировании:** `2edc65b` (== origin/master, дерево чистое). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5392 passed / 0 failed**; `node --check web/app.js` clean;
каталог-инвариант **REGISTRY 427 / GROUPS 90 / Settings 399 / categorized 403 / mapped 88 / `TAB_RULES` 19**;
SQLite **v8** (до миграции v9 в F1). Преемник — 10.13 (`cognition-*-round1013`, архив; все 8 фич COMPLETED,
60 задач T-1417…T-1476).
**UPD владельца (13.09.2026, отменяет редакцию 1 плана):** DDL разрешён; Persona — PG-таблицы
`personas`/`persona_traits`; новый origin `bot_self_reply` + SQLite v9; флаги ON по умолчанию; LLM-экстрактор
с 3-м провайдером; метрики Личности в «Сводке»; справка — БД-редактор.

**8 фич (нумерация продолжает T-1476 → T-1477…T-1548, 72 задачи):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `anti-echo-self-reply-round1014` | backend (+PG/SQLite DDL) | п.1 + UPD 1,3 | — (F8-роль `reflection` опциональна: фоллбэк) | **P0** (фундамент: origin+миграция+экстрактор) | T-1477…T-1486 (10) |
| **F2** | `persona-storage-core-round1014` | backend (+PG DDL) | п.2 + UPD 1,2,4 | **F1** (`persona_state` DDL) | **P0** | T-1487…T-1497 (11) |
| **F3** | `persona-ui-tab-round1014` | frontend | п.3 + UPD 2 | **F2** | P1 | T-1498…T-1504 (7) |
| **F4** | `persona-traits-ribbon-round1014` | frontend | п.3.1 + UPD 4 | **F2, F1** (`/api/persona/health`) | P1 | T-1505…T-1510 (6) |
| **F5** | `settings-persistence-audit-round1014` | backend+frontend | п.4 | — (∥ F1/F2; сверка с активной `config-read-path-audit`; охват новых API F8/F2/F6) | **P0** | T-1511…T-1525 (15) |
| **F6** | `help-guide-integration-round1014` | docs+backend+frontend | п.5+п.6 + UPD 5 | **F1, F2, F3** | P2 | T-1526…T-1534 (9) |
| **F7** | `status-layout-reorder-round1014` | frontend | п.7 | — (независима) | P2 | T-1535…T-1540 (6) |
| **F8** | `self-reflection-llm-provider-round1014` | backend+frontend | UPD 3 | **F1, F2** (роль `reflection` для LLM-экстрактора F1; UI-провайдеры; формально self-contained — пусто → основная модель) | P1 | T-1541…T-1548 (8) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → {F3, F4} → {F5 ∥ F8} → F6 → F7.**
Обоснование: F1 задаёт origin `bot_self_reply` + SQLite v9 + LLM-экстрактор (роль `reflection`, фоллбэк на
основную модель) → F2 (PG `personas`/`persona_traits` + core, промпт-склейка, `persona_state`) опирается на
DDL/канон F1; F3 (UI «Личность») и F4 (лента traits + метрики «Сводки») зависят от API F2 и могут идти
параллельно; F5 независима (аудит save/read-path), но делит `web/app.js` и включает в инвентарь новые
сущности F8/F2/F6; **F8** формально self-contained (пустые поля → основная модель), но по указанию владельца
учитывается зависимость от F1/F2: даёт роль `intel_reflection` для LLM-экстрактора F1 и provider-UI — вливать
после/параллельно F1–F2; F6 пишется по факту реализации F1–F3; F7 — чистая перестановка, независима.
**⚠️ F3, F4, F6, F7 все правят `web/index.html`/`web/app.js` — исполнять/вливать ступенями (F4 → F7 → F6).**
**F1/F2 (DDL) и F8 (models/keys) трогают `services/database.py`/`pg_db.py`/каталог — вливать согласованно с
пин-тестами каталога.**
F5 согласуется с активной F-5 `config-read-path-audit` (не дублировать read-path/касты).

**Контент по фичам (сжато):**
- **F1 (Anti-Echo & Self-Reflection, п.1 + UPD 1,3):** новый честный origin `graph_facts.origin='bot_self_reply'`
  (11-й; `status='confirmed'`), SQLite rebuild-миграция **v8→v9** (`_migrate_self_origin_v9`; все 16 колонок +
  FTS/vec; идемпотентно); вес self `limits.graph_fact_weight_bot` = **0.2** (важность 2) против пользовательского
  0.7; экстракт сути **только LLM** (новый `services/self_reflection.py`, роль `reflection` через F8, фоллбэк на
  основную модель); RAG-метка `[Источник: Я сам (Бот)]` + анти-эхо-инструкция (`_build_rag_block`, БЕЗ правки
  PG-канона); opt-in `include_self`; self исключён из Сна/«золотых»/decay/компакции/`graph_stats.facts`;
  `persona_state` (метрики экстрактора — DDL F1); флаг `flags.bot_self_awareness_enabled` **ON**. Модули:
  `services/database.py:53,67-101,…`, `services/summary_memory.py:211-222,…`, `services/dream_worker.py:132-136`,
  `services/direct_chat_service.py:959-990,1690-1771`, `services/llm_client.py:891-954`. **ADR-1014-2.**
- **F2 (Dynamic Persona, п.2 + UPD 1,2,4):** **PG-таблицы `personas`** (scope `is_global`/`chat_id` + CHECK +
  2 partial-unique + FK→`chat_profiles`) и **`persona_traits`** (`dynamic_traits`, cap 50/dedup, provenance
  `chat_id`/`source`); статические `name`/`biography`/`system_prompt_overrides`/`is_aware_ai` (default true);
  резолв per-chat → global → empty; API `GET/PUT/DELETE /api/persona` + `GET /api/persona/health`; промпт-склейка
  + имя-триггер; «Глубокий сон» пишет traits; `flags.persona_enabled` **ON**; сид пустой глобальной персоны.
  **НЕ** `bot_settings`/`chat_params.overrides`. **Naming:** `build_persona_card` (`direct_chat_service.py:1511`,
  `database.py:3390`) — досье ПОЛЬЗОВАТЕЛЯ (F8 10.13), НЕ трогать. **ADR-1014-1.**
- **F3 (UI «Личность», п.3 + UPD 2):** карточка/подраздел в Hub «ИИ» (`web/app.js:270-296`, `#/ai`), форма ТОЛЬКО
  статических полей (Имя/Биография/Характер/чекбокс «Осознаёт себя ИИ»), scope-реактивность (activeChatId/
  `X-Chat-Id`), бейдж+disabled при `flags.persona_enabled=OFF`. Модули: `web/app.js`, `web/index.html`,
  `web/api/routes.py` (персона — PG-API, каталог-Δ нет).
- **F4 (Лента «Эволюция характера» + метрики «Сводки», п.3.1 + UPD 4):** третья бегущая лента рядом с
  «Сон»/«Глубокий сон» (`web/index.html:2916-2943`), переиспользуя `_ribbonLoop`/`ribbonItemClass`
  (`web/app.js:4749-4776`); CSS-сетка 3 колонки; панель метрик Личности в дашборде **«Сводка»** (`#/oversight`):
  `traits_count`, `last_trait_at`, `extractor_status` (+`extractor_last_at`) через `GET /api/persona/health`.
- **F5 (Save/read-path audit, п.4):** инвентаризация ВСЕХ изменяемых параметров мини-аппа + матрица
  «SavePath/Scope/RuntimeConsumer»; цепочка Vue → API → БД; scope Global↔чат (422 `routes.py:414-417`);
  рестарт-персистентность; рантайм-подхват воркерами/RAG/LLM-клиентами; в инвентарь входят **новые сущности
  раунда** (`flags.persona_enabled`, `flags.bot_self_awareness_enabled`, provider-блок `intel_reflection`,
  dedicated-API `/api/persona` и `/api/info/guide`). Модули: `web/app.js:2431,3214,3263`,
  `services/chat_params.py:31-85,397-412`, `services/config_cache.py`, `services/llm_client.py`,
  `services/llm_probe.py`, `services/worker_budget.py`.
- **F6 (docs+справка, п.5/6 + UPD 5):** дополнить `plans/docs/intelligence_user_guide.md` (самосознание/личность),
  интегрировать в «Справку» (`web/index.html:3050-3083`) **вторым редактируемым блоком** под блоком
  использования функций; гайд хранится **в БД** — PG-ключ `content.intelligence_guide`
  `{markdown,updated_at,updated_by}` (json, `content_info`, PG-only), файл — только **источник идемпотентного
  сида**; Markdown-редактор + предпросмотр + **DOMPurify self-host** (без новых CDN); API `GET/POST /api/info/guide`
  (RBAC `edit_info`); `services/info_service.py`, `services/config_cache.py`, `web/api/routes.py`.
- **F7 (порядок «Статус», п.7):** «Сердцебиение» (`index.html:2883-2900`) — сразу под «Сводку» (`:2776`);
  «Мониторинг Интеллекта» (`:2901-2943`) — под «Сервер» (`:2817`). Независима.
- **F8 (3-й LLM-провайдер «Саморефлексия / Экстрактор сути», UPD 3):** новое parent+subBlocks-подключение в
  витрине «LLM Провайдеры»; PG-ключи `models.intel_reflection_base_url/_model_name/_display_name` +
  `keys.intel_reflection_api_key`; роль `reflection` в `LLMClient.generate_worker` (slug `intel_reflection`);
  probe `intel_reflection_main`; пустые поля → основная модель (DeepSeek), ошибка dedicated → `generate()`
  (fail-open). Паттерн ADR-1013-1 (`intel_history`/`intel_bg`). Потребляется F1.

**Инварианты раунда (в каждой tasks.md §3):** **DDL РАЗРЕШЁН** (UPD п.1): PG — идемпотентные
`CREATE TABLE IF NOT EXISTS`/`ON CONFLICT DO NOTHING` (`personas`, `persona_traits`, `persona_state`); SQLite
**v8→v9** rebuild с сохранением всех 16 колонок + FTS/vec и идемпотентным guard'ом; повторный
`PgDatabase.init()`/`initialize()` — no-op. **`graph_facts.origin` CHECK расширяется до 11 значений**
(`bot_self_reply`); `status='self_reply'` НЕ вводится. Порядок роутеров `bot.py` не трогать (только DI-kwargs);
каталог-инварианты **435/90/406/411/88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19 — новые ключи/вкладки/группы только
санкционированным Δ с обновлением пин-тестов (`test_param_catalog`, `test_frontend_tab_mapping`,
`TAB_SECTION_ORDER`, `TAB_RULES`, «группа → ровно 1 вкладка»); **R17** секреты `{configured,last4}`;
**R16** id — ключ, не имя; `media/`/`.env` не трогать; правка промпт-канонов — PREV-слепок +
`prompt_migrations` + байт-тесты (анти-эхо F1 — динамический блок, PG-канон НЕ трогается); байт-канон info
(`DEFAULT_INFO_TEXT`) не ломать; **новых `v-html` без санитайза/новых CDN нет** (DOMPurify self-host); **флаги
`flags.persona_enabled`/`flags.bot_self_awareness_enabled` = ON по умолчанию** (UPD п.2), OFF → байт-в-байт
прежнее поведение; **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`, пин-тесты каталога,
R17-скан, миграция дважды + «from scratch»; русские conventional commits.

**⚠️ Open (закрыто @Architect Step 2 итерация 2 — ADR-1014-1/2 + spec F1–F8; остаточное на @Builder/@Reviewer):**
- **F1/F2 (UPD):** решено — origin `bot_self_reply` (11-й) + SQLite v9; PG `personas`/`persona_traits` +
  `persona_state`; вес-ключ; LLM-экстрактор роль `reflection`; флаги ON. **@Reviewer/@Scanner:** идемпотентность
  миграций, сохранность 16 колонок/FTS/vec, R17.
- **F8:** решено — parent+subBlocks «LLM для саморефлексии (Экстрактор сути)», `intel_reflection_*`, probe
  fallback. Проверить отсутствие дублей с `intel_history`/`intel_bg`.
- **F3:** решено — отдельный экран/tab «Личность» в Hub «ИИ» (`#/ai/persona`), форма только статических полей;
  OFF → бейдж + disabled.
- **F4:** решено — 3-колоночная сетка, «ДД.ММ: текст», 12 последних traits, метрики в `#/oversight` через
  `/api/persona/health`.
- **F5:** границы с активной `config-read-path-audit` (что переносим/не дублируем) — уточнить при @Builder;
  sync-await vs optimistic UI; объём live-верификации; включить новые сущности F8/F2/F6.
- **F6:** решено — PG-ключ `content.intelligence_guide` (json PG-only) + идемпотентный сид из файла; Markdown +
  DOMPurify; второй блок в «Справке»; RBAC `edit_info`.
- **F7:** точная позиция «Доступности ключей» относительно «Мониторинга Интеллекта» (после «Сервера»; Q1).

**Покрытие ТЗ (`plans/current_task.md`, разделы 1–7 + UPD 1–5 → фичи):**

| Раздел ТЗ / UPD | Фича(и) |
|---|---|
| п.1 «Механика Самосознания (Anti-Echo & Self-Reflection)» | **F1** |
| п.2 «Архитектура Личности (Dynamic Persona)» | **F2** |
| п.3 «UI: Подраздел "Личность" в разделе "ИИ"» | **F3** |
| п.3.1 «Лента "Эволюция характера"» | **F4** |
| п.4 «Багфикс: сохранение и реактивность параметров» | **F5** |
| п.5 «Актуализация доки» | **F6** |
| п.6 «Расширение справки» | **F6** |
| п.7 «Перестановка Сердцебиения / Мониторинга Интеллекта» | **F7** |
| **UPD п.1** «Снятие DDL-инвариантов; PG-Persona; новый origin» | **F1** (`bot_self_reply`+v9) + **F2** (`personas`/`persona_traits`) |
| **UPD п.2** «Флаги ON по умолчанию; поля пустыми» | **F1** (`flags.bot_self_awareness_enabled`) + **F2/F3** (`flags.persona_enabled`) |
| **UPD п.3** «Экстрактор сути только LLM + 3-е подключение (роль `intel_reflection`)» | **F1** (LLM-экстрактор) + **F8** (провайдер/роль) |
| **UPD п.4** «Метрики Личности в "Сводке" (traits, время, статус экстрактора)» | **F4** (UI) + **F1/F2** (`/api/persona/health`) |
| **UPD п.5** «DOMPurify + БД-редактор Справки (не мёртвый файл)» | **F6** |

**Итог: все 7 разделов ТЗ + 5 пунктов UPD покрыты, 8 фич, 72 задачи (T-1477…T-1548); папки заархивированы.**
**Статус:** ✅ **ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН** (13.09.2026, @PM Step 8 Archive Phase; деплой @DevOps
commit `eb2a232`, прод active PID 1774527, health 200). Планирование (Step 1 @PM,
итерация 2 после UPD владельца) и Step 2 @Architect (ADR-1014-1/2 + spec/tasks F1–F8) завершены; реализация
@Builder (F1–F8), @Reviewer **APPROVED** (итерация 2), @Scanner **0 C/H/M** (2 Low — техдолг, см. блок
«ИТОГ 10.14»), @Architect — `plans/ARCHITECTURE.md` **§35**. Артефакты: **`plans/archive/*-round1014/`**
(**8 папок**). **@PM код не пишет.**

## Раунд 10.13 (13.09.2026): Cognition / Sleep / Memory Refactor — 8 фич — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (13.09.2026; архив @PM 13.09.2026)

**✅ ИТОГ 10.13 (13.09.2026):** реализация завершена, все **8 фич заархивированы** — перенесены
`plans/features/cognition-*-round1013/` → **`plans/archive/cognition-*-round1013/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5392 passed / 1 warning / 0 failed** (база 10.12 = 5211 → **+181**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean
(только LF→CRLF-предупреждения). Каталог — санкционированный прирост ADR-1013-1 (8 новых ключей выделенных
LLM + F8-флаги): **REGISTRY 427 / categorized 403 / Settings 399** (GROUPS 90 / `_TAB_BY_GROUP` 88 /
`TAB_RULES` 19). Инварианты: **ноль новых PG-DDL**, SQLite **v8** не бампнут, порядок роутеров `bot.py` не
тронут (только DI-kwarg `aliases=`), **R17**-скан чист, F7-гайд без запрещённого жаргона (grep 0), новые
`v-html`/CDN нет (vis-network self-host).
**Объём:** **8 фич, 60 задач** (T-1417…T-1476), все `[x]`.
@Reviewer — **APPROVED** (итерация 2; итерация 1 — Rejected по BLOCKER-1 [Critical] T-1439 роутер воркеров и
BLOCKER-2 [High] ностальгия; все BLOCKER и ISSUE-3/-4 закрыты и подтверждены `file:line` —
`plans/reports/round10.13_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты High S10.13-1 и 4 Medium
S10.13-2/-3/-4/-5), остаются **5 Low** — техдолг (`plans/reports/round10.13_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§34** + связанные разделы).
Артефакты в архиве: `spec.md` + `tasks.md` (×8) + ADR-1013-1 (`adr-1013-1-provider-keys.md`),
ADR-1013-2 (`adr-1013-2-graph-library.md`), ADR-1013-3 (`adr-1013-3-prompt-canon-policy.md`).
**Фичи (финал, все ✅ COMPLETED):** F1 `4d-memory` (T-1417…T-1423) · F2 `belief-decay` (T-1424…T-1433) ·
F3 `deep-sleep` (T-1434…T-1442) · F4 `llm-providers` (T-1443…T-1447) · F5 `dashboard` (T-1448…T-1458) ·
F6 `ekg-logs-bugfix` (T-1459…T-1464) · F7 `user-guide` (T-1465…T-1467) · F8 `irony-dossier` (T-1468…T-1476).

**🧾 Техдолг Low (ОТКРЫТ, 10.13 — не блокеры):** `S10.13-9` (Timeline-лор из in-memory
`get_process_accounting().lore_last_inject_at`, а не `chat_lore_history`), `S10.13-11` (LIKE-маркер парадигм
матчит только 2 варианта JSON-сериализации), `S10.13-13` (три дублирующих парсера `belief_meta`),
`S10.13-14` (возможны «висячие» рёбра после cap в `graph_snapshot`), `S10.13-6b` (остаточная
несогласованность `archived_beliefs` без фильтра парадигм). Источник — `plans/reports/round10.13_scanner_audit.md` §5.
**Дальше:** Step 9 — деплой @DevOps (единый коммит эпика, сейчас НЕ закоммичено); Step 10 — метрики @Memory
(проставит деплой-статус поверх `✅ COMPLETED`).
Ниже — исторический документ планирования эпика (Step 1 @PM).

**Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013` (@Memory, Step 0). **Источник ТЗ** —
`plans/current_task.md` (разделы 1–10). **HEAD при планировании:** `ce25dc7` (docs-коммит 10.12).
**Базовая линия:** pytest **5211 passed / 0 failed**; `node --check web/app.js` clean;
`node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант
**REGISTRY 405 / GROUPS 90 / Settings 377 / mapped 88 / `TAB_RULES` 19**; SQLite **v8**.
Ранее заархивирован 10.12 (`plans/archive/providers-kostik-round1012/`); открытые Scanner-ниты
10.12 (R10.12-2/-3/-4 — info) учтены в фичах.

**8 фич (продолжение нумерации T-1417…, все ✅ COMPLETED — 60/60 задач T-1417…T-1476):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `cognition-4d-memory-round1013` | backend | п.1 | — | **P0** (фундамент) | T-1417…T-1423 |
| **F2** | `cognition-belief-decay-round1013` | backend | п.4 + 4.1 | F1 | **P0** | T-1424…T-1433 |
| **F3** | `cognition-deep-sleep-round1013` | backend | п.6 + п.3 (backend) | **F1, F2** | P1 | T-1434…T-1442 |
| **F4** | `cognition-llm-providers-round1013` | frontend | п.3 (UI) | — (независима; согласовать ключи с F3) | P1 | T-1443…T-1447 |
| **F5** | `cognition-dashboard-round1013` | frontend | п.5 + п.7 | **API F2, F3** | P1 | T-1448…T-1458 |
| **F6** | `cognition-ekg-logs-bugfix-round1013` | frontend | п.8 + п.9 | — (независима) | P2 | T-1459…T-1464 |
| **F7** | `cognition-user-guide-round1013` | docs | п.10 | **F1–F6, F8 (последняя)** | P3 | T-1465…T-1467 |
| **F8** | `cognition-irony-dossier-round1013` | backend | п.2 | **F1** (инфра промпт-канона/метки); F2/F3 желательны; параллельно F4/F6 | P1 | T-1468…T-1476 |

**Рекомендуемый порядок исполнения:** **F1 → F2 → F3 → {F4 ∥ F6 ∥ F8} → F5 → F7.**
Обоснование: F1 даёт временные метки/единый RAG и инфраструктуру правки промпт-канона → F2 (decay/resurrection)
→ F3 (deep sleep) опирается на beliefs/архив; F4, F6 и F8 независимы (можно параллельно; F8 затрагивает
персоны/досье/контекст, а не UI «Статус»); F5 нужны API F2/F3; F7 пишется по факту реализации.
**F5 и F6 обе правят `web/index.html`/`web/app.js` (страница «Статус») — исполнять последовательно.
F8 делит `services/prompt_migrations.py` с F1/F2/F3 — ступень вливать в согласованном порядке (аддитивно).**

**Контент по фичам (сжато):**
- **F1 (4D-память, п.1):** префикс `[ММ.ГГГГ | Автор: ]` для фактов RAG, пометка
  `(Внимание: возможно устарело)` для фактов >6 мес (настраиваемо), группировка фактов по времени в
  обычном Сне для выводов о динамике. Модули: `services/summary_memory.py`
  (`_date_prefix:669`/`build_rag_context:693`/`get_rag_context:1958`), `services/dream_worker.py`,
  `services/dream_prompts.py`, `services/tool_router.py` (dig_into_lore).
- **F2 (Belief Decay + Resurrection, п.4/4.1):** weight −0.1/мес без подкрепления >6 мес; `<0.3` →
  `archived_belief`; векторный резонанс (пенальти −0.3, воскрешение при пороге); Сон-Реаниматор
  (отмена дублирующего синтеза + восстановление даты); активация по графу (связки 2–3 узлов в L1).
  Модули: `services/dream_worker.py` (`_write_belief:657`), `services/summary_memory.py` (KNN `:2190`),
  `services/memory_health.py`, `services/memory_maintenance.py`, `web/api/memory_agi.py`.
- **F3 («Глубокий сон», п.6 + backend п.3):** ежедневно сразу после обычного сна; «Поиск по якорям»
  (свежие beliefs + выжимка 12ч → RAG ко всей базе); синтез «Мост времени» (парадигма); парадигмы в
  контекст с весом 0.5–0.6; бэкенд-роутер моделей воркеров (историческая память/вехи/лор vs фоновые).
  Модули: `services/dream_worker.py`, `services/dream_prompts.py`, `services/worker_budget.py`,
  `services/llm_client.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`, `web/api/memory_agi.py`.
- **F4 («Провайдеры» UI, п.3):** 2 новых блока подключения (LLM для Исторической памяти/Вехи/Лор;
  LLM для Фоновых проверок/Оценка важности), фоллбэк на основную модель. Формат **parent+subBlocks (10.12)**,
  обязательны `providerCoveredKeys` + `_BLOCK_SAVED_KEY`. Модули: `web/app.js`, `web/index.html`,
  `services/llm_probe.py`, `services/param_catalog.py`, `config/settings.py`, `bot.py` (DI-kwargs).
- **F5 (Дашборд Cognition + виджет «Интеллект и Память», п.5/п.7):** две вертикальные бегущие строки
  (Убеждения/Сон, Парадигмы/Глубокий сон; верх/низ opacity-50, центр 100), бейджи
  `[🌙 Сон активен]`/`[🌌 Глубокий сон активен]`, интерактивный force-directed граф (`vis-network`/`d3.js`),
  статистика → «Модули»; виджет в «Сводке» (пульс процессов, прогресс-бары лимитов/бюджета, метрики БД,
  Timeline). Модули: `web/app.js`, `web/index.html`, `web/api/memory_agi.py`, `web/api/routes.py`,
  `services/status_service.py`, `services/worker_budget.py`.
- **F6 (EKG + багфикс «Логи», п.8/9):** удалить линейный график аптайма, добавить SVG-EKG с CSS-анимацией
  (Load/CPU/RAM: спокойный зелёный ↔ учащённый оранжевый/красный); починить рассинхрон селектора
  `INFO` vs `ALL`, новый комбинированный тег `ERROR+WARNING`, дефолт фильтра при открытии = `ERROR+WARNING`.
  **Контракт `GET /api/status/logs` изменится** — маркерные тесты учесть. Модули: `web/app.js`
  (`logLevel:860`/`loadLogs:3786`/`renderUptimeChart:3575`), `web/index.html` (`:2714-2768`),
  `web/api/routes.py` (`:1124`), `services/log_ring.py` (`get_entries:139`), `services/uptime_heartbeat.py`.
- **F7 (docs, п.10):** `plans/docs/intelligence_user_guide.md` — прозаично, простыми словами, без
  аббревиатур (RAG/LLM/токены/эндпоинты), иронично, готово к публикации; актуализация README (иронично) +
  `APP_VERSION`/cache-bust, русский коммит, push, деплой, отчёт.
- **F8 (Ирония и Досье Персонажей, п.2):** «Иронический фильтр» в системный промпт воркера досье; явная
  инструкция про `chat_memes` vs `real_facts` («мегачмо», «повелитель грибов» → мемы, не биография);
  досье в контексте — два блока `[Факты]`/`[Локальные мемы/Ярлыки]`. **Greenfield:** `real_facts`/`chat_memes`/
  `dossier` в коде НЕТ — сущность/воркер фиксирует @Architect (T-1468). Хранение `chat_memes` — только в
  существующей JSONB `chat_profiles.relations` или SQLite-поле `graph_facts` (**ноль PG-DDL**); правка канона —
  PREV-слепок + `prompt_migrations` + байт-тесты. Модули: `services/lore_worker.py`, `services/lore_prompts.py`,
  `services/lore_cache.py`, `services/chat_lore_store.py`, `services/database.py`
  (`get_persona_card:3118`/`get_protected_facts:2623`), `services/direct_chat_service.py`
  (`build_persona_card:1443`/`_build_user_relations:824`), `services/summary_memory.py`,
  `services/prompt_migrations.py`.

**Инварианты раунда (в каждой tasks.md §3):** ноль новых PG-DDL; SQLite **v8**; порядок роутеров `bot.py`
не трогать (только DI-kwargs); новые provider-блоки — только `parent`+`subBlocks` (10.12) + обязательно
`providerCoveredKeys` и `_BLOCK_SAVED_KEY`; каталог-инварианты **405/90/377/88**, `TAB_RULES` 19 — новые
ключи только санкционированным Δ с обновлением пин-тестов; **R17** секреты `{configured, last4}`;
**R16** id — ключ, не имя; `chat_memes` (F8) — только в существующей JSONB `chat_profiles.relations` или
SQLite-поле `graph_facts`, без миграции схемы; правка промпт-канонов — PREV-слепок + `prompt_migrations` +
байт-тесты; контракт `/api/status/logs` меняется (комбинированный тег) — маркерные тесты;
русские conventional commits.

**⚠️ Open (Step 1, для @Architect):**
- **ТЗ п.2 «Ирония и Досье Персонажей» — ✅ ДЕКОМПОЗИРОВАН 13.09.2026 @PM (Step 1 return):** выделена
  **8-я фича F8** `cognition-irony-dossier-round1013` (T-1468…T-1476) — см. строку F8 выше.
  Greenfield-вопросы (какой воркер = «Досье», где хранить `chat_memes`, формат блоков) — на @Architect (T-1468).
- **F4↔F3:** имена PG-ключей выделенных LLM (UI F4 / роутер F3) фиксируются одним ADR — согласовать.
- **F1↔промпт-канон:** правка `dream_prompts.py` требует PREV-слепка + `prompt_migrations` + байт-тестов —
  оценить объём. **F8 делит `prompt_migrations.py` с F1/F2/F3** — вливать ступени согласованно.

**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (13.09.2026, @PM Step 8 Archive Phase). Планирование (Step 1)
завершено @PM 13.09.2026; раздел п.2 закрыт фичей F8 (`cognition-irony-dossier-round1013`,
T-1468…T-1476) — все 10 разделов ТЗ покрыты (таблица покрытия — §«Покрытие ТЗ»). Реализация @Builder
(F1–F8), @Reviewer **APPROVED** (итерация 2), @Scanner **0 C/H/M** (5 Low — техдолг, см. блок «ИТОГ 10.13»),
@Architect — `plans/ARCHITECTURE.md` **§34**. Артефакты: **`plans/archive/cognition-*-round1013/`**
(**8 папок**: `spec.md`, `tasks.md`, ADR-1013-1/2/3).

**Покрытие ТЗ (раздел `plans/current_task.md` → фичи):**

| Раздел ТЗ | Фича(и) |
|---|---|
| п.1 «4D-Память» | **F1** |
| п.2 «Ирония и Досье Персонажей» | **F8** |
| п.3 «Выделенные LLM для Интеллекта» | **F3** (backend-роутер) + **F4** (UI-провайдеры) |
| п.4 «Охлаждение Убеждений» | **F2** |
| п.4.1 «Воскрешение» | **F2** |
| п.5 «UI: Дашборд Осмысление + Графы» | **F5** |
| п.6 «Мета-синтез / Глубокий сон» | **F3** |
| п.7 «Виджет Интеллект и Память в Сводке» | **F5** |
| п.8 «Анимация Heartbeat (EKG)» | **F6** |
| п.9 «Багфикс компонента Логи» | **F6** |
| п.10 «Человекочитаемая документация» | **F7** |

**Итог: все 10 разделов покрыты, 8 фич, дыр нет.**

## Раунд 10.12 (12.09.2026): развязка base_url провайдеров (embed ≠ direct) + merge блоков подключения + фразы Костика в PERMsoc — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (13.09.2026; архив @PM 13.09.2026)

**✅ ИТОГ 10.12 (13.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/providers-kostik-round1012/` → **`plans/archive/providers-kostik-round1012/`**
(@PM Step 8).
**Финальные метрики:** полный **pytest — 5211 passed / 0 failed** (база 10.11 = 5172 → **+39**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог — финальный
инвариант **REGISTRY 405 / GROUPS 90 / Settings 377** (санкционированный прирост: новые параметры
`base_url` embed/direct + редактируемый список фраз Костика, ADR-1012-1); R17-скан чист.
@Reviewer — **APPROVED WITH MINOR ISSUES** (дефекты 1–4 закрыты @Builder); @Scanner — **CLEAN**
(low закрыты follow-up; `plans/reports/round10.12_scanner_audit.md`); @Architect — архитектура влита
в `plans/ARCHITECTURE.md` (**§33**).
Артефакты в архиве: `spec.md`, `ADR-1012-1.md`, `tasks.md` (со статус-хедером завершения).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.12 (@DevOps, 13.09.2026):** commit
`708f7dffa3f9ef46136e33321116055dfd37191a` (`feat(admin,web,api,handlers,plans): раунд 10.12 —
развязка эмбеддингов, фикс сохранения глобальных ключей, объединённые блоки провайдеров, фразы Костика
(тесты 5211)`, 39 файлов), push `32d1aa9..708f7df` (origin/master); README **5211** / `APP_VERSION`
**2.56.0** (+ cache-bust `?v=2.56.0`; `test_app_version_matches_readme`/`test_index_version_param`
зелёные). Локальная верификация: `pytest tests/` → **5210 passed / 1 skipped / 0 failed**
(skip — нет локального `fontTools` в `test_font_subset.py:128`; в каноничном окружении — **5211**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → **JS-UNIT-OK**.
**Прод** `198.46.175.136:/var/www/admin_bot` — `git pull --ff-only` **`3624789..708f7df`**
(fast-forward; локальные `info_text.md`/бэкапы не конфликтовали).
**`.env` (потребовалась правка, бэкап `.env.bak.1012`):** `LLM_BASE_URL`
`https://apinet.cloud/v1` → **`https://nano-gpt.com/api/v1`** (direct-ответы); добавлен
`EMBEDDING_BASE_URL=https://apinet.cloud/v1`. **Миграция (ADR-1012-1 D1/D3/D4/D5, без `--force`):**
`venv/bin/python scripts/migrate_env_to_pg.py --only-category models,keys,reactions,flags` →
**`created=5 skipped=149`** (models:2, keys:1, reactions:1, flags:1), идемпотентно. Созданы:
`models.embedding_base_url` = **`https://apinet.cloud/v1`**, `models.openrouter_transcribe_display_name`
= `""` (пусто → в UI покажется адрес), `keys.embedding_api_key` = `""` (пусто → рантайм-фолбэк на
`keys.llm_api_key`, OD-1), `reactions.kostik_replies` = список из **14** фраз, `flags.kostik_enabled`
= **true**. Существующие значения сохранены (`ON CONFLICT DO NOTHING`): **resolved
`models.llm_base_url` = `https://nano-gpt.com/api/v1`** (не перезаписан), **resolved
`models.embedding_base_url` = `https://apinet.cloud/v1`**, `limits.kostik_reply_probability` = `0.1`
(прод-значение сохранено). `systemctl restart admin_bot` → **active (running)** (Main PID 1534535,
ActiveEnter 2026-09-12 12:43:59 UTC); `/api/health` → **200 `{"status":"ok"}`**; стартовые логи —
**0 app ERROR/Traceback** (только benign systemd cgroup-варнинги стопа и pre-existing BetterStack 401).
Маркеры 10.12 в проде: `/web/` и `/web/app.js` с `?v=2.56.0`; в `app.js` —
`blockDisplayName`, `list-editor`, `models.embedding_base_url`, `per_chat === false` (4×),
`options.global`, `flags.kostik_enabled`, `reactions.kostik_replies`; в `/web/` — `list-editor-tpl`.
**✅ PROD-деплой закрыт** (README/`APP_VERSION`/cache-bust синхронны; русский commit; push;
pull/restart/status; health **200**; 0 ERROR/Traceback; маркеры 10.12 на месте).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** правка base_url обоих провайдеров
(embed ≠ direct, без взаимного алиасинга); надпись «Название модели» у всех подключений; merged-блоки
(основная+запасная, транскрибация, саммаризация видео); список фраз Костика (add/delete/save) и
реальный ответ Костику.
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/providers-kostik-round1012/` (kebab: `providers-kostik-round1012`; `tasks.md` создан 12.09.2026 @PM; архивирована 13.09.2026 @PM Step 8).
**Нумерация:** **T-1382…T-1408** (продолжает T-1381 — финал 10.11).
**Преемник:** 10.11 `llm-providers-refactor-round1011` (архив; commit `3624789`, прод health 200, pytest 5172).
**Раунд подтверждён:** **10.12** (HEAD `32d1aa9`).
Базовая линия: pytest **5172 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19.
Инварианты: **ноль новых PG-DDL**, SQLite **v8**, `bot.py`-порядок/`media/`/`.env` не трогать, R16/R17.
UI + аддитивный серверный read-path ⟹ feature-flag не требуется, rollback = `git revert`.

**Запрос владельца (`plans/current_task.md`, дословно — `tasks.md` §1):**
1. **BUG:** изменение base_url основного провайдера (`models.llm_base_url`, сейчас `https://nano-gpt.com/api/v1`)
   падает «models.llm_base_url: ключ нельзя переносить на уровень чата», и base_url основного эмбеддинга
   тоже меняется на этот url. Эмбеддинги и основная модель — разные провайдеры, не должны зависеть друг от
   друга. Требуется: **embeddings base_url = `https://apinet.cloud/v1`**, **direct answers base_url =
   `https://nano-gpt.com/api/v1`**. **Без хардкода.**
2. **Блоки подключения:** маленькая надпись у header каждого подключения = значение поля **«Название модели»**;
   «Фолбэк-модель» → **«Запасная модель»** (+ merge в один блок с основной); «Groq (расшифровка)» →
   **«Модель транскрибации»**, «OpenRouter (запасной)» → **«Запасная модель транскрибации»** (+ merge);
   «Видео-модель (OpenRouter)» → **«Саммаризация видео»**, «Запасная видео-модель» → **«Запасная модель
   саммаризации видео»** (+ merge). Проверить семантику транскрибация vs саммаризация (подозрение на своп).
3. **PERMsoc Костик:** вынести захардкоженные фразы (`handlers/kostik.py:30-39` `KOSTIK_REPLIES`) в
   редактируемый список в блоке Костика (каждая фраза — плотное отдельное поле, add/delete); заменить на
   4 фразы владельца + 10 новых; проверить параметр частоты.
4. **Финал:** README (ирония), русский коммит, push, деплой (ssh → pull → restart → status), plain-language отчёт.

**Рекогносцировка (@PM, `32d1aa9`, file:line — детали `tasks.md` §2):**
- **п.1 (root cause 422):** `saveBlock` `web/app.js:2181-2225` → `api()` авто-`X-Chat-Id` `:1253-1254` →
  `routes.py:414-417` 422 при `per_chat=False`; `models.*` `per_chat=False` (`param_catalog.py:110-119`).
  **(root cause алиасинга):** `embeddings_main` биндит `models.llm_base_url` (`web/app.js:417`) — тот же
  ключ, что `direct_main` (`:362`); в рантайме `LLMClient._post` всегда `self._base_url`
  (`llm_client.py:534-544`) и `embed()` идёт туда же (`:926-942`) — отдельного embed-base-url
  settings **нет** (`config/settings.py:317-320`); `status_service.emb_main` тоже берёт `main_base`
  (`:163-164,251-256`). Точки LO `bot.py:316,486,515,542`.
- **п.2:** `PROVIDER_BLOCKS` `web/app.js:358-466` (merge-пары `:359-373`, `:374-388`, `:389-407`;
  subBlocks `:408-436`); рендер/надпись `web/index.html:806-811,946-994` (`.prov-modules` = `{{ b.modules }}` `:810`);
  маппинг/blocks `web/app.js:957-966,2800-2838`; display-name каталог `param_catalog.py:562-577`.
  **Семантика:** STT `handlers/voice_transcription.py:184`→`SmartModule/service.py:69-116` (Groq/OpenRouter
  транскрайберы) — транскрибация; `youtube_summarizer_service.py:101-147,254-303` + `video_cascade_client.py`
  — саммаризация (`video_primary/fallback_model`). **Свопа в коде нет** (подтверждено file:line) — причина
  ощущения: общий `models.openrouter_*`/display-name.
- **п.3:** фразы `handlers/kostik.py:30-39`, выбор `:54`, гейт `:42` `PermsocGateFilter("kostik")`;
  модуль `services/permsoc.py:55-57` (sub-флаг None); каталог-группа `reactions_kostik`
  (`param_catalog.py:311-312`, `KOSTIK_USER_ID` `:1139`; вкладка `:1701`); **частота ЕСТЬ** —
  `limits.kostik_reply_probability` (`settings.py:165`, `.env.example:22`, чтение `handlers/kostik.py:47-48`)
  в группе «Костик: лимиты»; **отдельного owner-блока Костика в `PERMSOC_OWNER_BLOCKS` нет**
  (`web/app.js:473-494` — группа уходит в «Общее»).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.11_scanner_audit.md` (0 blocker/0 major/0 medium;
3 low + 3 info) и `audit_backlog.md`. Включено точечно: R10.11-1 (nested `<details>`/localStorage →
T-1394), R10.11-2/R10.9-2 (embed-status vs runtime → T-1384/T-1386), R10.11-3 (.env-подсказки → T-1383),
R10.11-4 (probe caller base_url → OPEN-Q6), R10.6-1 (generic-дубль → providerCoveredKeys).
**Открытые вопросы (6 шт.)** — `tasks.md` §7 (Q1 дефолты/миграция адресов; Q2 общий openrouter display/base;
Q3 частота в блоке Костика; Q4 owner-блок Костика; Q5 виджет списка фраз; Q6 hardening probe). **@PM код не пишет.**
**Статус:** планирование завершено — передано `@Architect` (spec/ADR), затем `@Builder`/`@DevOps`.

## Раунд 10.11 (12.09.2026): память/сон/ностальгия-отчёт + LLM Провайдеры refactor + key-chart fix — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.11 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/llm-providers-refactor-round1011/` → **`plans/archive/llm-providers-refactor-round1011/`**
(@PM Step 8).
**Финальные метрики:** полный **pytest — 5172 passed / 0 failed** (база 10.10 = 5145 → **+27**;
@Scanner зафиксировал **5168** на момент аудита — до follow-up R10.11-1/-2/-3); `node --check web/app.js`
clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант
**REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88** (без роста; `categorized` **376** — sanctioned
Δ ADR-1011-2: models 40→42, keys 13→15, infra 28→24).
@Reviewer — **APPROVED WITH MINOR ISSUES** (CRITICAL/HIGH/MEDIUM исправлены @Builder); @Scanner —
**CLEAN: 3 low закрыты follow-up, 3 info → техдолг §25** (`plans/reports/round10.11_scanner_audit.md`);
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§32** + §5/§9/§25).
**✅ Пункт 4 (docs-only, без кода) — ЗАВЕРШЁН:** отчёт
**`plans/docs/memory_sleep_nostalgia_lore_report.md`** (6 тем, проза, простыми словами, каждая цифра
с `file:line`); принят @PM (T-1342).
Артефакты в архиве: `spec.md`, `ADR-1011-1.md`, `ADR-1011-2.md`, `ADR-1011-3.md`, `tasks.md`
(со статус-хедером).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.11 (@DevOps, 12.09.2026):** commit `3624789`
(`feat(admin,web,api,scripts,plans): раунд 10.11 …`, 28 файлов, тесты 5172), push `ec5dd1f..3624789`
(origin/master); README **5172** / `APP_VERSION` **2.55.0** (+ cache-bust `?v=2.55.0`; тесты
`test_app_version_matches_readme`/`test_index_version_query_param` зелёные); прод
`198.46.175.136:/var/www/admin_bot` — `git pull` `772db08..3624789` (fast-forward; `.env` не менялся).
**Миграция каталога (ADR-1011-2):** `venv/bin/python scripts/migrate_env_to_pg.py --only-category
models,keys` (без `--force`) → `created=5 skipped=48` (keys:3, models:2), идемпотентно; 4
embed-фоллбэк-записи резолвятся (`models.embedding_fallback_base_url` =
`https://generativelanguage.googleapis.com/v1beta/openai`, `_model` пустой → рантайм-фолбэк на
основную embed-модель, `keys.embedding_fallback_api_key`/`_2` — `configured(len=53)`); существующие
значения сохранены (ON CONFLICT DO NOTHING). `systemctl restart admin_bot` → **active (running)**
(Main PID 1498180); `/api/health` → **200 `{"status":"ok"}`**; стартовые логи нового PID —
**0 ERROR/Traceback**; `/web/` и `/web/app.js` несут маркеры 10.11
(`providerConnectionBlocks`/`providerAdvancedBlocks`/`subBlocks`/`blockFieldConfigured`/`spanGaps: true`/
`type: 'linear'`/`?v=2.55.0`); `POST /api/llm/test` достижим (**401** без initData — auth, не 404/500).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** **T-1377** — поле ключа + «Проверить»
без повторного ввода; навигация/профиль/сетка; две зоны «Провайдеры»; эмбеддинги (3 подблока);
видео-фоллбэк; media-share внизу; график доступности ключей (статически покрыто
`tests/test_webapp_round1011_ui.py`, JS-юнитами).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/llm-providers-refactor-round1011/` (kebab: `llm-providers-refactor-round1011`; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1340…T-1381** (продолжает T-1339 — финал 10.10).
**Преемник:** 10.10 `admin-ui-round1010` (архив; commit `ec5dd1f`, прод health 200, pytest 5145).
**Раунд подтверждён:** **10.11** (HEAD `ec5dd1f`).
Базовая линия: pytest **5145 passed / 1 skipped / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19. Инварианты: **ноль новых PG-DDL**, SQLite **v8**, `bot.py`/`media/`/`.env` не трогать, R17. UI/docs-only ⟹ feature-flag не требуется, rollback = `git revert`.

**Дословный запрос владельца (`plans/current_task.md`, приложен, добавлен в `.gitignore`):**
1. **Поле ключа провайдера:** при сохранённом ключе «Проверить» падает «ключ не задан» — сделать, чтобы ключ был явно в поле, если присвоен параметру (иначе пусто), и проверка работала без повторного ввода.
2. **Масштабный рефакторинг UI «LLM Провайдеры» + верхняя навигация** (интуитивно новичку, прагматично, без лишних компонентов):
   2.1 шапка/навигация — крупнее и плотнее иконки, зафиксировать блок профиля (аватар/ник/фулскрин), центрировать+сделать адаптивной сетку карточек;
   2.2 две зоны: **«Подключения»** (сверху, только модели) и **«Расширенные настройки»** (внизу, спойлер с таймаутами/ретраями/защитой);
   2.3 **«Эмбеддинги»** — 1 блок = ровно 3 подблока (Основная / Фоллбэк 1 / Фоллбэк 2), фоллбэкам полный набор полей (Base URL/Модель/ключ/«Проверить»);
   2.4 видео — запасную OpenRouter-модель поднять наверх под основную, полный набор полей, **убрать хардкод**;
   2.5 «Медиа-шара» — вниз в расширенные + human-subtext; весь теххаос (таймауты/защита/поиск-ключи/таймауты-повторы/отпечатки/Circuit Breaker/лимиты Groq) — в самый низ.
3. **Багфикс графика «История доступности ключей»** — разреженные данные дают разорванные чёрточки; нужен непрерывный ступенчатый график (`spanGaps:true`/`stepped:true` или range-маппинг) и X как временная шкала (`time`/`datetime`).
4. **Задача БЕЗ кода:** подробный прозаичный отчёт простыми словами о памяти, сне/синтезе воспоминаний, ностальгии, формировании лора чатов, таймингах/лимитах и сборке контекста (сначала пункт 4).
**Плюс:** README (ирония), русский коммит, push, деплой (ssh → pull → restart → status), human-readable отчёт.

**Рекогносцировка (@PM, `ec5dd1f`, file:line — детали `tasks.md` §2):**
- **п.1:** `PROVIDER_BLOCKS` `web/app.js:369-441` (secret-поля `:375,383,390,398,406,432,434,438`); `blockFieldValue` `:2047-2054` (object-маска → `''`); `blockFieldPlaceholder` `:2055-2061` (`configured ••••last4`); input `web/index.html:807-812`; `testBlock` `:2062-2090` (api_key только если truthy `:2071`); `saveBlock` `:2120-2160` (MINOR-3); `_mask_secret` `web/api/routes.py:194-203`; тест `web/api/routes.py:1243-1264` → `services/llm_probe.py:144-145` (`not_configured "ключ не задан"`) — **root cause подтверждён**.
- **п.2:** рендер `web/index.html:794-842`; данные `web/app.js:645-646`; nav `web/index.html:731-739` + CSS `.navbar-band/.nav-link/.nav-icon` `:204-229` (icon 18px), профиль `:712-727`; hub-сетка `:757-781` + `.hub-grid` `:248-251`; эмбеддинги `web/app.js:408-417` (`testable:false`), видео `:400-407`, media_share `:436-440`, тех-блоки `:418-435`; каталог-группы — `services/param_catalog.py`.
- **п.3:** `keyHistoryChartModel` `web/app.js:3473-3545` (`stepped:true` `:3533`, `spanGaps:false` `:3536`), `renderKeyHistoryChart` `:3546-3590`, X категориальная (`:3577-3578`); canvas `web/index.html:2617-2619`; данные `services/key_history.py`, API `web/api/routes.py:1090-1118`; Chart.js 4 CDN `web/index.html:3040` (time-adapter отсутствует); JS-юниты `tests/js/routing_test.js:586-660`.
- **п.4:** отчёт @Architect по сервисам памяти/сна/ностальгии/лора/контекста (`services/memory*`, `dream*`/`sleep*`, `nostalgia*`, `chat_lore.py`, `context*`; гейты `services/feature_gates.py`; лимиты `services/param_catalog.py`) → **`plans/docs/memory_sleep_nostalgia_lore_report.md`** (ранее ошибочно `plans/reports/round10.11_memory_report.md`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.10_scanner_audit.md` (0 blocker/0 major/0 medium; low R10.10-1/-2 скрипт DM, R10.10-3 chart-return — **уже закрыт** в 10.10, info R10.10-4/-5). В скоуп 10.11 из аудита прямо ничего не входит; T-1374 перепроверяет R10.10-3 регрессом. `audit_backlog.md` — пересечений blocker/major нет.
**Открытые вопросы (6 шт.)** — `tasks.md` §7 (Q1: ширина/центрирование сетки; Q2: реальные ключи эмбеддинг-фоллбэков vs Δ каталога; Q3: место хардкода видео-фоллбэка и дефолт; Q4: Chart.js time-adapter vs линейная ось; Q5: резолв сохранённого ключа без нарушения R17; Q6: «Поиск: ключи» = advanced или connections). **@PM код не пишет.**
**Статус:** планирование завершено — передано `@Orchestrator` (историческая запись; раунд **завершён и заархивирован** 12.09.2026 @PM Step 8).

## Раунд 10.10 (12.09.2026): admin UI bugfix + DM-модули OFF + Headroom stats — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.10 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round1010/` → **`plans/archive/admin-ui-round1010/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5145 passed / 1 skipped / 0 failed** (база 10.9 = 5105 → **+40**;
+1 — регресс-тест standalone-CLI `scripts/disable_dm_heavy_modules.py`, devops-fix `a477747`);
каталог-инвариант **REGISTRY 400 / GROUPS 90 / Settings 372** (mapped 88).
@Reviewer — **APPROVED WITH MINOR ISSUES** (follow-ups закрыты); @Scanner — **CLEAN: low/info**
(большинство находок устранено) (`plans/reports/round10.10_scanner_audit.md`); @Architect — архитектура
влита в `plans/ARCHITECTURE.md` (**§31** + связанные разделы).
Артефакты в архиве: `spec.md`, `ADR-1010-1.md`, `ADR-1010-2.md`, `ADR-1010-3.md`, `tasks.md`
(со статус-хедером).
**⚠️ ОТКРЫТО (PROD data-run, за @DevOps, пост-архив):** **T-1327** — применить DM-скрипт на сервере
(`scripts/disable_dm_heavy_modules.py`: `--dry-run` → `--apply` → повторный `--dry-run` = 0 изменений;
снапшот до apply), затем **T-1328** (верификация: ни одна активная ЛС не имеет модулей ON);
**T-1333** (Headroom stats через серверный прокси); **T-1337/T-1338** (русский commit / push / deploy,
health 200).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** **T-1317** (fullscreen header),
**T-1320** (mobile key-availability chart), **T-1323** (провайдеры: реальные значения полей),
**T-1332** (роли: аватар+ник, ширины) — статически покрыто (`tests/test_webapp_round1010_ui.py`,
JS-юниты).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.10 (@DevOps, 12.09.2026):** commits `d082800` (раунд, тесты 5144) +
`a477747` (fix scripts: standalone `sys.path` bootstrap + CLI-тест, тесты 5145); push `da85b60..a477747`;
прод `198.46.175.136:/var/www/admin_bot` `git pull --ff-only` `d2d1215..a477747` (fast-forward; `.env`
не менялся); `systemctl restart admin_bot` → **active (running)** (Main PID 1338398);
`/api/health` → **200 `{"status":"ok"}`**; стартовые логи — **0 ERROR/Traceback**; README **5145**,
`APP_VERSION` **2.54.0**. **T-1327/T-1328 (DM data-run):** активная ЛС `5885953495` — `--dry-run` 1 план →
`--apply` (changed=1/noop=0/total=1/errors=0) + снапшот
`var/dm_modules_off_snapshot_20260911T201219Z.json` (до записи) → повторный `--dry-run` **0 изменений**
(идемпотентно); сон/ностальгия/саммаризация — OFF. **Остаётся за владельцем/QA:** live Android
(T-1317/T-1320/T-1323/T-1332).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round1010/` (kebab: `admin-ui-round1010`; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1315…T-1339** (продолжает T-1314 — финал 10.9).
**Преемник:** 10.9 `admin-ui-round109` (архив; задеплоен 12.09.2026; commit `d2d1215`, прод fast-forward, health 200).
**Раунд подтверждён:** **10.10**.
Базовая линия: pytest **5105 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES` 19. **Ноль новых PG-DDL**; `bot.py`/`media/`/`.env` не трогать.

**Дословный запрос владельца (пункты 1–6, дословно в `tasks.md` §1):**
1. **Header padding в FULLSCREEN:** блок профиля (аватар + ник + роль + fullscreen) не перекрывается нативными кнопками Telegram.
2. **Mobile:** график доступности ключей рендерится некорректно (одна плоская полоса) — починить.
3. **«Провайдеры»:** поля Название/Адрес/Модель/Ключ должны показывать **реальные** текущие значения (сейчас выглядят пустыми); поле «Ключ» уже показывает текущее — **оставить как есть**.
4. **ЛС:** модули **сон / ностальгия / саммаризация** — **OFF по умолчанию**; выключить для **ВСЕХ текущих активных ЛС** (data-change существующих чатов).
5. **«Роли»:** список должен показывать **аватар+ник** вместо голого ID (ID — мелким серым рядом); **уменьшить ширину селектора ролей**, **расширить поле ID**.
6. **Headroom stats:** получить и вывести текущую статистику сэкономленных токенов (`headroom_stats` MCP; через серверный прокси).
**Плюс:** README (ирония), русский коммит, push, деплой, plain-language отчёт.

**Рекогносцировка (@PM, HEAD `da85b60`, дерево чистое) — опорные точки (детали `tasks.md` §2):**
- **п.1** шапка `web/index.html:628-722`, блок профиля `:694-709`, fullscreen CSS `:594-612`, safe-area `:588-591,616-620`; JS `web/app.js:717,2344-2358`.
- **п.2** `renderKeyHistoryChart` `web/app.js:3425-3481` (union `ts`, `stepped`, `spanGaps:false`, legend bottom); данные `services/key_history.py:126-203` (ring 5-мин слоты); canvas `web/index.html:2585` (`height="80"`); `GET /api/status/key-history` `web/api/routes.py:1090-1102`.
- **п.3 (root cause найден)** `PROVIDER_BLOCKS` `web/app.js:366-438`; форма `v-model="blockDrafts[f.key]"` `web/index.html:788`; `blockDrafts` создаётся пустым `web/app.js:643` и **нигде не наполняется** → инпуты пустые; `blockFieldValue` (`:2036-2043`) используется только для test/save; «Ключ» показывается через placeholder/маску (`:2044-2050`) — не трогать.
- **п.4 (хранилище)** PG `chat_profiles.chat_params` JSONB (`services/chat_params.py:1-9,41-85`; схема `services/pg_db.py:76-83`): `overrides` (per-chat значения) + `gates` (`dream`/`nostalgia`/`lore_auto`/`permsoc`, `services/feature_gates.py`). DM-идентификатор: `services/chat_params.py:31-35 is_dm_scope` = **`chat_id > 0`**; активные — `is_active=TRUE`. Ключи: Сон `memory.dream_enabled` + gate `dream`; Ностальгия `memory.nostalgia_enabled` + gate `nostalgia`; Саммаризация `flags.summary_enabled` (бегущий конспект — `flags.chat_running_summary_enabled`, уже DM-default OFF через `chat_params.py:397-412`). Безопасный флип — идемпотентный скрипт (`--dry-run`/`--apply`, прецеденты `scripts/backfill_*_gates.py`), снапшот до apply, без DDL.
- **п.5** окно «Роли» `web/index.html:1579-1621` (список `:1598-1605`, формы `:1608-1614`); данные `loadAdmins` `web/app.js:2940-2946` → `GET /api/admins` `web/api/routes.py:705-712` (`cache.admins_full()`, без имени/фото); обогащение — паттерн `user_display_info` `web/api/chat_lore.py:44,60,577-630`, аватары `web/app.js:1232,1266-1298`.
- **п.6** внешний MCP `headroom_stats` через серверный прокси (read-only; R17).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.9_scanner_audit.md` (0 blocker / 0 major / 0 medium; 3 low + 3 info) и `audit_backlog.md`. Включено P2-точечно: **R10.9-1** (`model_source`) и **R10.9-3** (stale docstring `status_service.py`) → **T-1334**. Вне скоупа — follow-up (R10.9-2/-4/-5, R10.7-1/-2, R10.6-1/-2/-3).
**Открытые вопросы (5 шт.)** — `tasks.md` §7 (величина отступа fullscreen; данные vs рендер графика; ключ «саммаризации» для ЛС; источник ника админов; способ забора `headroom_stats`). **@PM не пишет код.**

## Раунд 10.9 (12.09.2026): UI/UX-полировка + model-status — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.9 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round109/` → **`plans/archive/admin-ui-round109/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5105 passed / 0 failed** (база 10.8 = 5076 → **+29**);
каталог-инвариант **REGISTRY 400 / GROUPS 90 / Settings 372** (mapped 88; `TAB_RULES`/`CONFIG_TAB_TITLES` = 19).
@Reviewer — **APPROVED WITH MINOR ISSUES** (1 Critical + 1 High + 2 Medium + 3 Low — все устранены,
follow-ups закрыты); @Scanner — **CLEAN: 0 blocker / 0 major / 0 medium**
(3 low R10.9-1/-2/-3 + 3 info R10.9-4/-5/-6 — известный точечный техдолг)
(`plans/reports/round10.9_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (**§30** + связанные §1/§9/§25).
Артефакты в архиве: `spec.md`, `ADR-109.md`, `tasks.md` (со статус-хедером).
**R10.9-6 (info, backlog-статус) — ✅ ЗАКРЫТО:** раздел переведён «🟡 ПЛАНИРОВАНИЕ» → «✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН».
**⚠️ [OUT OF SCOPE] Пункт 2 (инфраструктура IDE):** инструмент локального IDE владельца
(OpenCode), **не часть бота**; операционного содержимого (systemd-юнит, firewall,
`opencode.jsonc`) в проекте/архиве нет — только маркеры «вне скоупа».
**Открыто (live-верификация на реальном Android):** **T-1277** (PERMsoc-блоки/тумблеры),
**T-1290** (описания «глазами новичка»), **T-1292** (гейты после удаления «Тяжёлых фич»),
**T-1294** (бюджет в «Сводке»), **T-1302** (dashboard/health), **T-1305** (мобильный dashboard) —
за владельцем/QA; статически покрыто (`tests/test_webapp_round109_ui.py`, JS-юниты).
Пост-архивная фаза @DevOps (commit/push/deploy/live-smoke, **T-1309…T-1311**) — после архивации.
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.9 (@DevOps, 12.09.2026):** commit `d2d1215`, push `51f308b..d2d1215`;
прод `198.46.175.136:/var/www/admin_bot` `git pull --ff-only` `31d2ce7..d2d1215` (fast-forward,
`.env` не менялся — UI-only, новые env-ключи не требуются); `systemctl restart admin_bot` →
**active (running)** (Main PID 1310051); `/api/health` → **200 `{"status":"ok"}`**; стартовые
логи — **0 ERROR/Traceback**; README **5105**, `APP_VERSION` **2.53.0** (T-1307 закрыт).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round109/` (изолированная папка; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1270…T-1314** (продолжает T-1269 — финал 10.8).
**Преемник:** 10.8 `admin-ui-round108` (архив; задеплоен 11.09.2026; commit `31d2ce7`, прод fast-forward, health 200).
Базовая линия: pytest **5076 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
**Состав:** один трек — TMA UI/UX-полировка (`web/*`, README/docs). Инварианты: без новых PG-DDL, без изменений `bot.py`/`media/`/`.env`; каталог-инвариант **392/91/364** меняется только осознанно (п.7.2 «Название модели»).
**[OUT OF SCOPE] Пункт 2 — вне проекта:** инфраструктурный инструмент локального IDE владельца (OpenCode), **не часть бота**; в коде/конфиге/тестах проекта ссылок нет. Серверный infra-deliverable и `opencode.jsonc` — вне репозитория. Пункт 2 исходного ТЗ в раунд **не входит**.
**Запрос владельца (пункты 1, 3–8; дословно в `tasks.md` §1):** (1) PERMsoc — разделить «Персоны (ID): Славик и Оля», сгруппировать параметры по владельцу в collapsible-блоки с ровно ОДНИМ рабочим тумблером (без дублей); (3) сохранение параметра не сбрасывает скролл наверх; (4) переписать ВСЕ описания групп/параметров (просто, без жаргона, ирония); (5) «Тяжёлые фичи» — проверить дубль per-module тумблеров, при дубле удалить; (6) «Бюджет фона» показывает нули — починить/проверить дубль со «Сводкой», возможно перенести туда; (7) dashboard — один блок «Доступность ключей» с группами по функциям (Основные/Транскрибация/Саммаризация видео/Эмбеддинги), убрать хардкод имён, реальный Health (502/503/Timeout, не cached 200) + «Название модели» первым полем формы и ограничение ширины формы; (8) ускорить фоновый градиент. **Плюс:** README (ирония), русский коммит, push, деплой, plain-language отчёт.
**Рекогносцировка (@PM, HEAD `51f308b`):** см. `tasks.md` §2 (file:line). Опорные точки: PERMsoc `services/param_catalog.py:300,1104,1156,1668-1680` + `services/permsoc.py:51-72` + `web/index.html:812-854`; скролл `web/app.js:2658-2717,2457-2504,2234-2238`; описания `param_catalog.py:73-140`; «Тяжёлые фичи» `web/index.html:1213-1250` + `services/feature_gates.py:26`; бюджет `web/index.html:1176-1211,1520-1572` + `web/api/gates.py:148`; dashboard `web/index.html:2546-2564` + `services/status_service.py:139-224,386-412`; форма провайдеров `web/index.html:762-804` + `web/app.js:364-430`; градиент `web/index.html:37-39,88-121`.
**Учёт аудита @Scanner:** прочитан `plans/reports/round10.8_scanner_audit.md` (0 blocker/0 major; minor R10.8-1 Esc / R10.8-5 `APP_VERSION`+cache-bust; info R10.8-2/-3/-4). Включено: R10.8-5 → T-1307 (поднять `APP_VERSION` до 2.53.0); R10.7-1/-2 → T-1298 (health); R10.6-1 → T-1304 (дубль generic-рендера). Вне скоупа — follow-up.
**Открытые вопросы (5 шт.)** — `tasks.md` §7 (хранение custom-name, эмбеддинг-фоллбэки, реальный health-тест, общий блок персон, решение по удалению/переносу). **@PM не пишет код.**

## Раунд 10.8 (11.09.2026): UI-доработки после 10.7 — переименование разделов, emoji→иконки, Android-логи, доступы окнами, GLOBAL-бейдж + README — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.8 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round108/` → **`plans/archive/admin-ui-round108/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5076 passed / 0 failed** (база 10.7 = 5042 → **+34**);
каталог-инвариант **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89 — без изменений).
@Reviewer — **APPROVED WITH MINOR ISSUES** (doc-nit исправлен); @Scanner — **0 blocker / 0 major**
(2 minor R10.8-1 Esc / R10.8-5 `APP_VERSION`+cache-bust субсета — закрыты точечно до Merge;
3 info R10.8-2/-3/-4 — известный техдолг) (`plans/reports/round10.8_scanner_audit.md`);
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§29** + связанные §1/§9/§25).
Артефакты в архиве: `spec.md`, `ADR-001-access-windows-modal.md`,
`ADR-002-icon-subset-parity.md`, `tasks.md` (со статус-хедером).
**Открыто (live-верификация на реальном Android):** **T-1254** (логи — ширина/дата/текст/нет
невидимого поля) и **T-1258** (три отдельных окна «Доступов») — за владельцем/QA; статически
покрыто (`tests/test_webapp_round108_ui.py`, JS-юнит). Пост-архивная фаза @DevOps
(commit/push/deploy/live-smoke, T-1265…T-1267) — после архивации.
**✅ README-счётчик тестов актуализирован @DevOps: 5073 → 5076** (шапка + changelog;
`APP_VERSION` 2.52.0 совпадает с шапкой README).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.8 (@DevOps, 11.09.2026):** commit `31d2ce7`, push
`636a75d..31d2ce7`; прод `git pull --ff-only` `7f3b790..31d2ce7` (fast-forward, без конфликтов,
`.env` не менялся — UI-only); `systemctl restart admin_bot` → **active (running)**;
`/api/health` → **200 `{"status":"ok"}`**; шрифт `/static/fonts/material-symbols-rounded.woff2?v=2.52.0`
→ **200 `font/woff2`, 18388 B, `wOF2`**; **0 ERROR/Traceback**. Полный pytest локально — **5076 passed / 0 failed**.
Детали — `plans/archive/admin-ui-round108/tasks.md` §9. **Открыто (live, за владельцем/QA):
T-1254** (логи на реальном Android) и **T-1258** (три окна «Доступов» на живом телефоне).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round108/` (изолированная папка; `tasks.md` создан 11.09.2026 @PM; архивирована 11.09.2026 @PM Step 8).
**Нумерация:** **T-1243…T-1269** (продолжает T-1242 — финал 10.7).
**Преемник:** 10.7 `admin-ui-bugfixes-round107` (архив; задеплоен 11.09.2026; commit `7f3b790`, прод fast-forward, health 200).
Базовая линия: pytest **5042 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
**Ключевой момент:** UI-only (TMA `web/*` + README/docs), без новых PG-DDL, без изменений `bot.py`/`media/`/`.env`; feature-flag не требуется (rollback = `git revert`).

**Запрос владельца (UI, дословно):**
1. **Переименовать разделы:** «Доступы и роли» → **«Доступы»**; «Функции PERMsoc» → **«PERMsoc»**;
   «Настройки AI» → **«ИИ»**; «Как это работает» → **«Справка»**; «Oversight» → **«Сводка»**.
2. **Заменить оставшиеся EMOJI** в блоках/подсекциях внутри разделов на иконки.
3. **Починить регрессию LOGS на Android:** ширина таблицы сломана; **дата исчезла**; колонка текста
   ошибки — в один символ; **невидимое selection-поле всё ещё в первой колонке** (10.7 не долечил).
   Должно работать на Android.
4. **Доступы:** «Матрица ролей», «Локальные админы», «Администраторы» — **каждый в ОТДЕЛЬНОМ окне**
   (не все на одном экране). Переименовать «Администраторы» → **«Роли»**. «Мой доступ» и
   «Telegram ID админа» — **без изменений**.
5. **Убрать внешний GLOBAL-бейдж** справа от селектора чата (дубль бейджа внутри селектора).
**Плюс:** README restructure (ироничный тон сохранить): самый-важный-для-пользователя раздел,
гайд «управление+деплой», changelog под сворачиваемым `<details>`. Русский коммит, push, деплой,
plain-language отчёт.

**Рекогносцировка (@PM, HEAD `7f3b790`, дерево чистое):** см. `plans/features/admin-ui-round108/tasks.md` §2
(file:line). Опорные точки: NAV_ITEMS/TABS/HUBS подписи `web/app.js:156,171,186,189,246-255,261-303`;
emoji `web/app.js:43,184,189` + `web/index.html:809,975,1173,1209,1220,1380,1416,1420,1452,1489,1802,1828,1840,1853,1935,1949,2146,2166,2198,2258,2279,2434,2438,2442,2450,2478,2498,2509,2548,2699,2930`;
иконки/субсет `web/app.js:207-228,2164-2170` + `scripts/build_font_subset.py:46-53` + `web/static/fonts/material-symbols-rounded.woff2`;
логи `web/index.html:2545-2589` + CSS `:400-463` + `web/app.js:3285-3291` (root-cause «дата исчезла» —
`fmtLogTime` отдаёт только `HH:MM:SS`, полная дата лишь в недоступном на тач `:title`; «невидимое поле» —
скорее всего `<button class="log-toggle">▸</button>` `index.html:2574-2577`, глиф отсутствует в Android-шрифте);
доступы `web/index.html:1577-1782` + `web/app.js:288-302,603,1851-1857,1884-1890,2062-2069`;
внешний GLOBAL-бейдж `web/index.html:672-674` (внутренний — `:638-641`, `#id` — `:669-671`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.7_scanner_audit.md` (0 blocker/0 major; minor R10.7-1;
info R10.7-2…R10.7-5). Включено: **R10.7-4** (font-test gap → T-1249, критично для emoji→иконок).
Вне UI-скоупа/опционально: R10.7-1/-2 (`services/status_service.py` gap-fill), R10.7-3 (`copiedTimer`), R10.6-1
(дубль generic-рендера `llm_providers`) → T-1250 (P2, не раздувать риск); R10.6-2/-3 — отдельный раунд.
**@PM не пишет код.** **Архив:** `plans/archive/admin-ui-round108/` (spec.md, ADR-001, ADR-002, tasks.md со статус-хедером).

## Раунд 10.7 (11.09.2026): UI/UX bugfix после 10.6 — шапка/навигация, статистика, логи — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.7 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-bugfixes-round107/` → **`plans/archive/admin-ui-bugfixes-round107/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5042 passed / 0 failed**; каталог-инвариант
**REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89). @Reviewer — **APPROVED WITH MINOR ISSUES**
(doc-nit исправлен); @Scanner — **0 blocker / 0 major** (1 minor R10.7-1 — задокументированный
spec-trade-off; info R10.7-2…R10.7-4; R10.7-5 — точность формулировки, не код)
(`plans/reports/round10.7_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (**§28** + связанные §9/§25). Артефакты в архиве: `spec.md`, `tasks.md`
(со статус-хедером). Пост-архивная фаза @DevOps (commit/push/деплой/live-smoke 1b/1c/1d/2a/3b) —
выполняется после архивации. Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-bugfixes-round107/` (изолированная папка; `tasks.md` создан 11.09.2026).
**Нумерация:** **T-1224…T-1242** (продолжает T-1223 — Scanner-миноры 10.6).
**Преемник:** 10.6 `tma-ia-modules-rework` (архив, задеплоен 11.09.2026; commit `6f91e8b`).
Базовая линия: pytest **5027 passed / 0 failed**, `node --check` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Финал: pytest **5042 passed / 0 failed** (Δ +19).

**Запрос владельца (bugfix/UI, дословно):**
1. **Header (top panel) & navigation:** (a) render-баг — select показывает `function () { [native code] }`
   (исправить Vue-привязку/потерю контекста); (b) safe area — правые элементы перекрыты нативными
   кнопками Telegram (добавить padding-right); (c) компактный user block (avatar + name + role badge +
   fullscreen) — уменьшить размеры/отступы, элементы НЕ удалять; (d) подписи меню под иконками
   переносятся неправильно («Настрой ки AI», «Как это работае т») — уменьшить кегль (text-xs или меньше)
   и отступы, чтобы влезали в одну строку.
2. **Statistics:** (a) таблица ключей — длинные имена моделей (`whisper-large-v3`) ломают ширину
   (ellipsis/word-break); (b) график — плоская линия (починить отрисовку исторических данных).
3. **Logs:** (a) фильтры — найти/убрать невидимый div/input слева от select «INFO», ломающий grid;
   (b) колонки — фиксированная ширина для уровня (ERROR/INFO) и даты, последняя текстовая колонка `flex:1`
   с корректным переносом; (c) UX — копирование строки лога по клику с визуальным откликом.
**Плюс:** README (ироничный тон), русский коммит, push, деплой, plain-language отчёт.

**Рекогносцировка (@PM, HEAD `2ccf558`, дерево чистое):** см. `plans/features/admin-ui-bugfixes-round107/tasks.md` §3
(file:line). Опорные точки: шапка `web/index.html:558-655`; scope-select `:576-618`; user block `:627-642`;
nav-labels `:205-216`, `:646-654`; таблица ключей `:2459-2495` + CSS `.avail-list` `:344-354`;
графики `web/app.js:3130-3166`, `:3195-3251` + `services/status_service.py:260-281`,`:320-336`
и `services/uptime_heartbeat.py:26` (пишется только `'up'` → плоская линия); фильтры/таблица логов
`web/index.html:2497-2537`; copy/context-loss `web/app.js:3300-3330` (подтверждён `map(this.logText)` без `bind`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.6_scanner_audit.md` (новейший; 0 blocker/0 major).
В UI-скоуп 10.7 включён **R10.6-1** (дублирующиеся редакторы LLM-провайдеров — 21 дубль) как опциональная
P2-задача **T-1234**; **R10.6-2** (SSRF `https`) и **R10.6-3** (422-эхо `api_key`, R17) — вне UI-скоупа,
кандидаты 10.8; **R10.6-5** (мёртвые `ICONS`) — низкий приоритет. Ремедиации 10.5 (R10.5-1/-2) закрыты.

**Статус (исторический):** ✅ завершён и заархивирован 11.09.2026 (@PM Step 8) — см. сводку выше.
**@PM не пишет код.**
**Архив:** `plans/archive/admin-ui-bugfixes-round107/` (spec.md, tasks.md).

**✅ ДЕПЛОЙ 10.7 (11.09.2026, @DevOps):** commit `7f3b790`, push `2ccf558..7f3b790`
(`origin/master`); прод `git pull --ff-only` `4055434..7f3b790` (fast-forward), `.env` не менялся
(UI/docs-only); `systemctl restart admin_bot` → **active (running)**, Main PID `1086594`;
`/api/health` → **HTTP 200 `{"status":"ok"}`**; логи старта чистые (**0 ERROR/Traceback**;
единственный WARNING — известный BetterStack 401). Live-smoke TMA UI (1a-1d/2a-2b/3a-3c) —
не автоматизирован, остаётся ручной проверкой владельца. Детали — `tasks.md` §9 архива.

## Раунд 10.6 (11.09.2026): TMA IA/Modules rework — 7 UX/IA-дефектов владельца после 10.5 — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (GO 11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.6 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/tma-ia-modules-rework/` → **`plans/archive/tma-ia-modules-rework/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5027 passed / 0 failed**; каталог-инвариант
**REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89; Δ GROUPS 74→91 = +17).
@Reviewer — **APPROVED WITH MINOR ISSUES** (все минорные закрыты до Merge: T-1213…T-1221);
@Scanner — **0 blocker / 0 major** (`plans/reports/round10.6_scanner_audit.md`, worthwhile-миноры
закрыты: T-1222/T-1223); @Architect — архитектура влита в `plans/ARCHITECTURE.md` (§27 +
§2/§6/§9/§25). Артефакты в архиве: `design-project.md`, `spec.md`, `tasks.md` (со статус-хедером).
**✅ Пост-архивная фаза @DevOps завершена (11.09.2026):** commit **`6f91e8b`** + push
**`be7b85b..6f91e8b`** в `origin/master`; прод `git pull` fast-forward **`c01ed72..6f91e8b`**
(`.env`-изменений не требуется — `.env.example` не менялся, 5 master-флагов сидятся в PG
`ON CONFLICT DO NOTHING`), `sudo systemctl restart admin_bot` → **active (running)** (PID 1020830),
`/api/health` = **200**, логи старта чистые (0 трейсбеков; BetterStack 401 — pre-existing).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/tma-ia-modules-rework/` (изолированная папка; `tasks.md` создан 11.09.2026).
**Нумерация:** **T-1155…T-1212** (T-1155…T-1199 — исходный план; T-1200…T-1212 — по закреплённым ответам владельца 11.09.2026; продолжает T-1154 секции H раунда 10.5).
**Преемник:** 10.5 `tma-relume-redesign` (архив, задеплоен 10.09.2026) — владелец принял редизайн,
но зафиксировал **мажорные UX/IA-дефекты** как follow-up.

**Обратная связь владельца (дословно, 7 пунктов):**
1. **TWO nav panels is wrong** — убрать SIDEBAR полностью; навигация ТОЛЬКО через TOP navbar;
   у иконок навбара добавить маленькие подписи ПОД иконками (мелкий шрифт, mobile+desktop).
2. **Desktop FULLSCREEN не скроллится** — исправить.
3. Секции хаотичны, эталонная структура не соблюдена; **«Кастомные модули» НЕ реализовывать
   (AI-галлюцинация)**. **REQUIRED IA:**
   - **«Модули»** = РОВНО 11 модулей, у каждого **on/off toggle** + кнопка **окна со ВСЕМИ
     параметрами/лимитами**: 1 Саммаризация, 2 Прямые ответы, 3 Фактчек, 4 Поиск,
     5 Транскрипт голосовых и видео, 6 Выжимка видео, 7 Скачивание медиа, 8 Веб-страницы,
     9 Диагностика, 10 Сон, 11 Ностальгия.
   - **«Настройки AI»**: убрать **«Лимиты»** (лимиты уходят в Модули). Содержит: LLM Провайдеры,
     Промпты, **Память (all memory+RAG)**, **Умный кэш**, Имена, Участники и отношения, Лор чата.
   - **«LLM Провайдеры»**: все модели/провайдеры/`base_url`; сверху — модель прямых ответов
     (main → fallback); **ОДИН визуальный блок = base_url + model + api key**; кнопка
     **«test connection»**.
   - **«Функции PERMsoc»**: убрать миселённые параметры (Кулдаун скачивания, длительность видео
     для расшифровки, длительность войса, размер видео для расшифровки, символов транскрипта для
     выжимки, Потолок загрузки Groq, Потолок загрузки OpenRouter, Потолок публикации видео,
     TTL опубликованного видео, Таймаут STT видео) → redistribute в правильные Модули.
     **PERMsoc = только захардкоженные простые per-chat функции.**
   - **Персонажи:** **«Леха» и «Костик» — РАЗДЕЛЬНЫЕ items**, не одна секция.

**Инвентаризация @PM (для @Architect):** 10 миселённых ключей **все** лежат в группе
`limits_media`; группа **смешанная** — кроме них там настоящие PERMsoc-параметры
(`GIF_INTERVAL`, `SLAVIC_PHOTO_INTERVAL`, `COMMON_COOLDOWN`, `DANGER_COOLDOWN`,
`SELFDEV_COOLDOWN`, `WORK_COOLDOWN`, `OLYA_COOLDOWN`) ⟹ redistribution требует **расщепления
`limits_media`** (изменение каталога GROUPS). Полная карта «11 модулей → группы/ключи» и
«Настройки AI → 7 подразделов» — в `tasks.md` §2. База 10.5: REGISTRY 387 / GROUPS 74 /
Settings 359. **ЦЕЛЬ 10.6 (закреплено владельцем): REGISTRY 392 / GROUPS 91 / Settings 364
(Δ GROUPS 74→91 = +17).**

**Свежие аудиты @Scanner:** `plans/reports/round10.5_scanner_audit.md` — 0 blocker / 0 major,
2 minor (R10.5-1 BackButton re-init; R10.5-2 DM `models.*` 422). Обе учтены в планах
(T-1160a, раздел LLM Провайдеры). `audit_backlog.md` — поверхность 10.5 просканирована.

**🟢 ГЕЙТ ОТКРЫТ (11.09.2026):** владелец **утвердил** дизайн/IA (`spec.md`/`design-project`) и
дал явное **«proceed»** — HARD GATE T-1156 **ПРОЙДЕН**; реализация `@Builder` **РАЗБЛОКИРОВАНА**.
**Закреплённые ответы владельца (locked) — `tasks.md` §8:**
- **A1/D1 = ДА:** тумблеры модулей реально работают; **Фактчек, Поиск, Выжимка видео,
  Веб-страницы, Диагностика — default ON**; +5 master-флагов ⟹ **REGISTRY 392 / GROUPS 91 /
  Settings 364** (Δ GROUPS 74→91 = +17).
- **A2/D2 = раздельно:** модули — в «Модули»; редакторы промптов/моделей/ключей — в «Настройки AI».
- **A3/D3 = RAG → «Память»:** RAG-доли бюджета и все RAG-ключи уходят в подраздел «Память»
  (расщепление `limits_chat_budgets`).
- **A4/D4 = per-block test:** LLM Провайдеры — визуальные блоки ПО МОДУЛЯМ (base_url+model+api key);
  main → fallback; у каждого блока кнопка test (ошибка key/model или 200).
- **A5/D5:** сервер и логи остаются на «Статус» (просмотр).
- **A6/A7:** emoji → иконка в «Как это работает» и в матрице ролей.
- **A8:** proxy+cookies → из «Провайдеров» в «Модули»; настройки логов/BetterStack/checkup →
  подраздел «Диагностика».
- **A9:** «Доступы и роли» — эксклюзивный аккордеон (открыт ровно один подраздел).
Новые задачи раунда: **T-1200…T-1212** (`tasks.md` §8.4). **Открытых вопросов НЕТ.**

**Свежие аудиты @Scanner (перепроверено 11.09.2026):** `plans/reports/round10.5_scanner_audit.md` —
0 blocker / 0 major, 2 minor (R10.5-1 BackButton re-init; R10.5-2 DM `models.*` 422); новых
отчётов после него нет. Обе ремедиации учтены (T-1160a; DM read-only в LLM Провайдерах).

## Раунд 10.5 (10.09.2026): Редизайн TMA по референсу Relume + гигиена репозитория — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (GO 10.09.2026; архив @PM 10.09.2026)

ТЗ владельца (10.09.2026): (1) добавить `relumesite_example/` в `.gitignore` (сторонний
Relume-экспорт сайта-мокапа, не код проекта; **`media/` НЕ трогать** — политика project.md);
(2) изучить референс (структура разделов, размещение параметров, палитра/стиль);
(3) подтвердить понимание и готовность полностью переделать админ-миниапп.
**REFERENCE:** `relumesite_example/` — 15 статических страниц (`index.htm` + Relume-рантайм
`index.8433654a.js`, стили `index.238f2711.css`), язык RU, реальные описания фич бота.
Заголовки: «Статус сервера и бота» `/`, «Настройки AI» `/ai/`, «Промпты» `/ai/page-13/`,
«Лимиты» `/ai/page-14/`, «Память» `/ai/page-15/`, «Сон и Ностальгия» `/ai/page-16/`,
«LLM Провайдеры» `/ai/llm/`, «Функции PERMsoc» `/permsoc/`, «Модули» `/page-1/`,
«Кастомные модули» `/page-1/page-2/`, «Как это работает» `/page/`, «Доступы и Роли»
`/page-20/`, «Матрица ролей» `/page-20/page-21/`, «Локальные админы чата» `/page-20/page-22/`,
«Управление администраторами» `/page-23/`. **Планирование 10.09.2026 @PM: 1 фича
`tma-relume-redesign` (архив: `plans/archive/`), нумерация T-1066…T-1148** (продолжает T-1065;
**позже расширена до T-1143** ответами OD11–OD15 — см. ниже).
**10.09.2026 (вечер) — решения владельца зафиксированы: OD1=B (полный ребейлд IA по
референсу), OD2=всё сразу (big-bang), OD3=та же технология (Vue3 global / zero-build),
OD4=база палитры референса + анимированные переливы (reduced-motion + WCAG AA над
градиентом), OD5=Material icons (emoji — временный fallback), OD6=структура референса —
эталон.** Уточнение: при OD1+OD3 многостраничная навигация реализуется **hash-routing
внутри одного `index.html` ⟹ hash-routing ОБЯЗАТЕЛЕН** (подтверждено @Memory).
Следующий deliverable — **архитектурно-дизайн проект** (нумерация T-1090…T-1126,
продолжает T-1089); **реализация — только ПОСЛЕ апрува проекта владельцем** (hard-gate).

**10.09.2026 (поздний вечер) — РЕШЕНИЯ ВЛАДЕЛЬЦА OD7–OD10 (SUPERSEDE прежние рек. по D6/D7):**
- **OD7 (было D6) — RESOLVED + РАСШИРЕНО.** «Чат-Профиль» = **САМЫЙ ВАЖНЫЙ элемент** —
  **глобальный переключатель контекста/скоупа** (**GLOBAL ↔ конкретный ЧАТ ↔ ЛС/DM**), который
  **управляет маршрутизацией всех настроек**. Промитентный аккуратный **drop-down селектор чата**;
  список чатов бота, **отфильтрованный по чатам текущего админа** (**RBAC**: случайный пользователь
  **НЕ** меняет параметры там, где запрещено); после выбора — **крупно ИМЯ и АВАТАР** чата.
  **НЕ сворачивается в AI-hub.** Это **хребет роутинга** мини-аппа.
- **OD8 (было D7/B1) — В СКОУПЕ, ПЕРЕРАБОТАНО.** Компактный список **всех API-ключей**:
  имя по модулю + **динамически подтянутые текущий провайдер/модель** (сейчас **хардкод** —
  исправить) + **код ответа сервера** + индикатор доступности; **мелкий шрифт/плотный line-height**;
  затем **график доступности всех ключей по времени** + небольшая **легенда**. Починить раздутый блок.
- **OD9 (было D7/B2) — ИЗ СКОУПА.** CRUD «Кастомных модулей» **не реализовывать** (read-only остаётся).
- **OD10 (было D7/B3) — В СКОУПЕ, РАСШИРЕНО.** Матрица: **все** параметры мини-аппа, сгруппированные
  **по тем же секциям**; по каждому — роли на **чтение/запись**; плюс **управление ролями**, включая
  **создание новых ролей**.
- **Deep-link — остаётся OPEN (D9).** Владелец хочет **сначала объяснение** (@Architect документирует
  простыми словами). **D11 (шрифт):** владелец **сам предоставит** Material Symbols ⟹ нужна
  **спека формата поставки** от @Architect.
Новые задачи: **E3-спеки T-1121…T-1126 (@Architect, 0 кода)**, **реализация T-1127…T-1133 (@Builder,
после GATE)**, **QA T-1134…T-1135**. Нумерация на тот момент — **T-1066…T-1135** (позже расширена
до **T-1143** — см. следующий блок OD11–OD15).

**10.09.2026 (новое сообщение владельца) — ОТВЕТЫ на Q-NEW-1…5, решения OD11–OD15 (финальные):**
- **OD11 (Q-NEW-1) — НЕТ хардкода моделей.** В проекте **не должно быть ни одной захардкоженной
  модели** (Groq/OpenRouter и любые другие) — **исправить**. **КРИТИЧНО:** уже сконфигурированные
  модели/ключи **НЕ должны сломаться** ⟹ **безопасная миграция / сохранение текущих значений**
  (дефолты новых ключей = сегодняшние константы). Следствие: STT-модели становятся конфигурируемыми
  ⟹ **+2 записи каталога (REGISTRY 383→385)** — обоснованное, согласованное исключение.
- **OD12 (Q-NEW-2) — история доступности ключей ПЕРСИСТИТСЯ между сессиями** (переживает рестарт).
  Приоритет — соблюсти «**ноль новых PG-DDL / SQLite v8**»; если невозможно — **явно оговорить
  обоснованное исключение** для владельца (in-memory ring — лишь быстрый слой).
- **OD13 (Q-NEW-3) — deep-link ВЫКЛЮЧЕН (OFF).** **D9 CLOSED**; задачи реализации нет
  (`__TMA_DEEPLINK__`=`false`).
- **OD14 (Q-NEW-4) — шрифт предоставлен:** полный `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2`
  в **корне проекта** (~5.1 МиБ; сабсет не найден) ⟹ обязательна **ИНСПЕКЦИЯ и вердикт
  (пригоден/непригоден) ДО реализации**. **D11 CLOSED-в-инспекцию.**
- **OD15 (Q-NEW-5) — переименование/удаление ролей РАЗРЕШЕНЫ, КРОМЕ superuser** (абсолютная
  защита). **D12 RESOLVED.**
Новые задачи: **E4-анализ T-1136…T-1138 (@Architect/@Scanner, 0 кода, ДО GATE)**,
**реализация T-1139…T-1142 (@Builder, после GATE)**, **QA T-1143**. `design-project.md` отревизован
до **v4** (T-1138).

**10.09.2026 (ответы владельца на Q1–Q4 `design-project.md` §16.5) — решения OD16–OD19 (финальные):**
- **OD16 (Q1) — адреса провайдеров ОБЯЗАТЕЛЬНЫ в мини-аппе.** **ВСЕ** необходимые параметры
  (провайдер, модель, `base_url`) должны быть **редактируемы из UI**; владелец обязан уметь
  **переключать провайдера И модель** из мини-аппа. Отменяет «base-url hot-only без UI-строки».
  Следствие: **+2 записи каталога** ⟹ счётчики **REGISTRY 387 / GROUPS 74 / Settings 359**
  (383 → +2 STT (OD11) → 385 → +2 адреса (OD16) → 387) — согласованное исключение.
- **OD17 (Q2) — `fonttools`+`brotli` ОДОБРЕНЫ** как **build-time** зависимость (в runtime не
  попадают).
- **OD18 (Q3) — тяжёлый исходник шрифта (5.11 МиБ в корне) → `.gitignore`**; в git только
  **субсет ~13 КБ** + **`LICENSE`** Apache-2.0.
- **OD19 (Q4) — файл `var/status_key_history.json` ОДОБРЕН**, но с **обязательной проверкой
  на утечки**: без сырых API-ключей/секретов, **R17-safe**, права файла, gitignored.
Новые задачи: **E5-ревизия T-1144 (@Architect, 0 кода, ДО GATE → проект v5)** — ✅ **выполнена
10.09.2026**, **реализация T-1145…T-1148 (@Builder, после GATE)**. Итоговая нумерация — **T-1066…T-1148**.
`design-project.md` — **v5 готов** (T-1144) и **ждёт только общего GO** владельца; открытых
вопросов/выборов не осталось.

| # | Задача ТЗ | Фича | Задачи | Ключевые AC / канон |
|---|-----------|------|--------|---------------------|
| 1 | `.gitignore += relumesite_example/` (`media/` НЕ трогать) | `tma-relume-redesign` | T-1066 | ✅ Выполнено 10.09.2026 — раздел «Сторонний референс-сайт Relume», `git check-ignore` подтверждает; `media/` по-прежнему не игнорируется |
| 2 | Глубокий анализ референса (структура/секции/параметры) | `tma-relume-redesign` | T-1067…T-1071 | Инвентаризация 15 страниц; иерархия navbar/sidebar; разбор секций/карточек/таблиц/графиков; дизайн-токены CSS (Inter, scheme-4, акцент `#14CBB6`); компонентные паттерны |
| 3 | Маппинг «раздел референса → вкладка/группа параметров mini-app» | `tma-relume-redesign` | T-1072…T-1075 | Таблица соответствия `param_catalog.TAB_RULES`/TABS-зеркалу; gap-анализ (есть/нет); инвентаризация API-эндпоинтов; отчёт `reference-mapping.md` |
| 4 | Решение: full-rebuild vs reskin | `tma-relume-redesign` | T-1076…T-1077 | ✅ **РЕШЕНО (OD1)**: вариант **B — полный ребейлд** IA по референсу; **всё сразу** (OD2); **та же технология** Vue3 global/zero-build (OD3); палитра-база референса + анимированные градиенты (OD4); Material icons/emoji-fallback (OD5); структура референса — эталон (OD6). **Поздний вечер, OD7–OD10:** Chat-Profile = **промитентный scope-switcher** (GLOBAL/ЧАТ/ЛС, RBAC-фильтр чатов, имя+аватар) — **хребет роутинга**; **B1 в скоуп** (key-availability переработка), **B2 OUT**, **B3 в скоуп** (матрица всех параметров по секциям read/write + создание ролей) |
| 5 | Архитектурно-дизайн проект (**deliverable**) | `tma-relume-redesign` | T-1090…T-1097 (+ **E3-спеки T-1121…T-1126**) | Parity-map без потери фич; градиент-токены; спека Material Symbols (+ **спека поставки шрифта** T-1121); hash-routing; композиция 15 экранов; предложения add/remove/optimize (Exa); test-plan; **спеки OD7–OD10** (scope-switcher T-1123, key-availability T-1124, матрица/роли T-1125; deep-link doc T-1122); финал `design-project.md` v3 (**T-1126**) → **GATE владельца** |
| 5a | **Доуточнения по OD11–OD15 (Q-NEW-1…5)** | `tma-relume-redesign` | **E4: T-1136…T-1138** (pre-gate, @Architect/@Scanner, 0 кода) | **T-1136** — исчерпывающий аудит ВСЕХ хардкодов моделей/ключей/base_url + план safe migration (сохранить текущие значения); **T-1137** — инспекция полного `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2` из корня → вердикт пригоден/непригоден **до реализации**; **T-1138** — ревизия `design-project.md` → **v4** (OD11–OD15, D9/D11/D12 CLOSED). **✅ Выполнено (0 кода).** |
| 5b | **Доуточнения по OD16–OD19 (Q1–Q4, §16.5)** | `tma-relume-redesign` | **E5: T-1144** (pre-gate, @Architect, 0 кода) | Ревизия `design-project.md` → **v5**: **(OD16)** адреса провайдеров **UI-редактируемы** + переключение провайдера/модели ⟹ каталог **+2** ⟹ **387/74/359**; **(OD17)** `fonttools`+`brotli` build-only; **(OD18)** 5.11 МиБ источник → `.gitignore` (в git субсет+LICENSE); **(OD19)** `var/status_key_history.json` апрув + **leak-safety**. **Разрешено до GATE (анализ).** |
| 6 | Полная переделка (big-bang) + QA | `tma-relume-redesign` | T-1098…T-1118 + **F4 T-1127…T-1133** + **F5 T-1139…T-1142** + **F6 T-1145…T-1148** + **QA T-1134…T-1135, T-1143** | Порядок: токены → shell/navbar → hub → 15 экранов → **scope-switcher → key-availability → role matrix** → **хардкод+миграция → персистентная история → role rename/delete** → **UI-редактируемость провайдера/модели/адресов → fonttools-сборка → .gitignore шрифта → leak-safety key-history** → QA; `node --check`, `TABS`↔`TAB_RULES`, каталог **387/74/359**, маркеры `test_webapp_*`/`test_frontend_tab_mapping`, pytest baseline **4860**, live Telegram. **✅ ВЫПОЛНЕНО и заархивировано 10.09.2026 (@PM Step 8; 4962 passed / 0 failed; см. `plans/archive/tma-relume-redesign/tasks.md` секция H/DoD)** |

**РЕШЕНИЕ (10.09.2026, владелец): выбран вариант B — ПОЛНЫЙ РЕБЕЙЛД** (OD1): берём
навигационную модель референса и полностью перестраиваем IA (navbar + hub-карточки +
отдельные экраны), **всё сразу** (OD2), на **той же технологии** Vue3 global/zero-build
(OD3). Варианты A (reskin) и C (hybrid) — отклонены. Палитра: **база = цвета референса +
анимированные переливы** (OD4) с `prefers-reduced-motion`-фолбэком и **WCAG AA над
движущимся градиентом**; иконки — **Material Symbols** (emoji как временный fallback, OD5);
структура — **полностью как в референсе** (15 страниц, OD6). **Hash-routing внутри одного
`index.html` обязателен** (следствие OD1+OD3; подтверждено @Memory); **D8** — нативный
back через `BackButton` (deep-link — отдельный тумблер, D9). **Поздний вечер (OD7–OD10):**
Чат-Профиль = **промитентный scope-switcher** (GLOBAL/ЧАТ/ЛС) — **хребет роутинга**;
**B1 — в скоуп**, **B2 — OUT**, **B3 — в скоуп** (матрица + создание ролей). **Новое сообщение
владельца (OD11–OD15):** ноль хардкода моделей + safe migration (OD11); персистентная история
доступности ключей (OD12); **deep-link OFF** (OD13); шрифт предоставлен → инспекция (OD14);
rename/delete ролей, кроме superuser (OD15). **Новое сообщение владельца (OD16–OD19, Q1–Q4):**
адреса провайдеров **обязательны в UI** + переключение провайдера/модели ⟹ каталог **387/74/359**
(OD16); `fonttools`+`brotli` build-only (OD17); 5.11 МиБ источник → `.gitignore` (OD18);
`var/status_key_history.json` апрув + **leak-safety** (OD19). **Порядок:** архитектурно-дизайн
проект (T-1090…T-1097) → **спеки OD7–OD10** (E3, T-1121…T-1126) → **анализ OD11–OD15** (E4,
T-1136…T-1138) → **анализ OD16–OD19** (E5, T-1144) → **ревизия проекта v5 + GATE** апрува
владельцем → **только потом** big-bang реализация @Builder (T-1098…T-1118 + F4 T-1127…T-1133 +
F5 T-1139…T-1142 + F6 T-1145…T-1148 + QA T-1134…T-1135, T-1143). **Все прежние открытые
D9/D11/D12 — ЗАКРЫТЫ** (OD13/OD14/OD15); **D6/D7/D8 — RESOLVED** (OD7–OD10 + research T-1119).

**Конфликт-матрица (проверка @PM 10.09.2026):**

| Активная | Пересечение | Решение / порядок |
|----------|-------------|-------------------|
| **F-4** `frontend-admin-bugfixes` (Баг-4 «сверка синхронизации разделов» — проверяет ВСЕ вкладки) | Редизайн меняет карту вкладок/IA **+ добавляет scope-switcher (OD7) и матрицу ролей (OD10)** | **Редизайн 10.5 ДО Бага-4** (иначе сверка по старой карте); либо Баг-4 закрыть до старта 10.5. Приоритет — на решении владельца |
| **F-6** `user-aliases-admin` (фронт-плоскость «Лимиты/Модули», алиасы/каскад имён) | **ПРЯМОЕ:** **OD7** меняет chat-контекст (scope-switcher) и трогает те же рендер-зоны (`index.html`/`app.js`); алиасы **per-chat** (`build_alias_resolver(chat_id)`); **OD10** (матрица/права) пересекается с доступом к «Лимитам/Модулям» | F-6 сейчас — аудит/верификация без ломки UI; редизайн **учитывает per-chat-семантику алиасов** (R16: ID не имя) и F-6-блоки в IA. Scope-switcher обязан сохранять per-chat-контекст алиасов — сверить после реализации OD7 |
| **F-3** `scam-incident-security-followup` (T-663: админ-гейт DM-веток) | **OD7** вводит **явный DM-скоуп**; **OD10** — права на параметры | DM-гейты (`chat_id>0`) **сохранить**; scope-switcher/матрица **не ослабляют** серверные проверки; перепроверить T-663 при вёрстке DM-скоупа |
| **F-1/F-2/F-5** | фронт/бэкенд не пересекаются напрямую | Независимы; учесть при финальном полном pytest |

**✅ СТАТУС (10.09.2026, ФИНАЛ): ЗАВЕРШЁН И ЗААРХИВИРОВАН.** Реализация big-bang
(T-1098…T-1148; секции F/F4/F5/F6/G) **выполнена**; @Reviewer — **APPROVED WITH MINOR ISSUES**,
минорные замечания закрыты до Merge; @Scanner — **0 blocker / 0 major**
(`plans/reports/round10.5_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (§25/§26). **Полный pytest — 4962 passed / 0 failed**; `node --check
web/app.js`, `tests/js/routing_test.js` и `git diff --check` — clean. **Фича перенесена
@PM (Step 8 Archive Phase): `plans/features/tma-relume-redesign/` → `plans/archive/tma-relume-redesign/`**
(сохранены `design-project.md` v5, `spec.md` v3, `tasks.md`, `reference-analysis.md`).
**Исторический статус на момент GO:** 🟢 ВСЕ РЕШЕНИЯ ВЛАДЕЛЬЦА ПОЛУЧЕНЫ (OD1–OD19);
**E5-ревизия выполнена — `design-project.md` = v5**
(T-1144 ✅, 0 кода). **🟢 10.09.2026 владелец дал явный общий GO на v5 — hard-gate ПРОЙДЕН**,
секции F/F4/F5/F6/G открыты (@Builder стартует с T-1098; порядок T-1098 → F1–F3 → F4 → F5 →
F6 → G → H). **Доп. требования владельца при GO:** parity каждого параметра мини-аппа
(все значения применяются и персистятся, ноль функциональных потерь), полный `pytest`
(baseline 4860, 0 регрессий) + smoke-тесты, live-верификация (где возможно), README (ироничный
тон), русский conventional-commit + push, деплой на прод, финальный plain-language отчёт
(done/changes/bugs/blockers). T-1066 выполнен (`.gitignore` обновлён,
`relumesite_example/` игнорируется, `media/` не тронут). Deliverable **T-1090…T-1097
готов** — `plans/archive/tma-relume-redesign/design-project.md` (parity-map без потери
фич, градиент-токены, Material Symbols, hash-routing, композиция 15 экранов, test-plan,
add/remove/optimize, Exa-источники). **Решено владельцем (OD7–OD10):**
- **D6 — ✅ RESOLVED (OD7):** «Чат-Профиль» = **промитентный глобальный scope-switcher**
  (GLOBAL/ЧАТ/ЛС) с **RBAC-фильтром** чатов и показом **имени/аватара**; **НЕ** сворачивается
  в AI-hub. Спека — **T-1123**, реализация — **T-1127**.
- **D7 — ✅ RESOLVED:** **B1 — в скоуп** (переработка key-availability: динамич. провайдер/модель,
  компактные строки, код ответа, график+легенда — **T-1124/T-1128/T-1129/T-1132**);
  **B2 — OUT** (read-only, **T-1108**); **B3 — в скоуп и расширен** (все параметры по секциям,
  read/write-роли + **создание ролей** — **T-1125/T-1130/T-1131/T-1133**).
- **D8 — ✅ back RESOLVED (T-1119):** через **нативный `BackButton`**, без своей кнопки;
  `__TMA_BACK__`=`true`.
**Решено владельцем (OD11–OD15, ответы на Q-NEW-1…5):**
- **OD11 — ✅ (Q-NEW-1):** ноль захардкоженных моделей во всём проекте; **safe migration
  с сохранением текущих значений**; STT-модели → каталог **383→385** (согласованное исключение;
  итог с OD16 — **387/74/359**). Аудит — **T-1136**, реализация — **T-1139**.
- **OD12 — ✅ (Q-NEW-2):** история доступности ключей **персистится между сессиями**;
  «ноль PG-DDL / SQLite v8» — приоритетно, иначе **явное исключение**. Реализация — **T-1140**.
- **OD13 — ✅ (Q-NEW-3): D9 CLOSED — deep-link OFF** (`__TMA_DEEPLINK__`=`false`); задач
  реализации нет.
- **OD14 — ✅ (Q-NEW-4): D11 CLOSED-в-инспекцию** — полный `MaterialSymbolsRounded[...].woff2`
  в корне проекта; **инспекция + вердикт до реализации** — **T-1137**; ревизия — **T-1138**.
- **OD15 — ✅ (Q-NEW-5): D12 RESOLVED** — rename/delete ролей разрешены, **кроме superuser**;
  backend — **T-1141**, UI — **T-1142**.
**Решено владельцем (OD16–OD19, ответы на Q1–Q4 из §16.5):**
- **OD16 — ✅ (Q1):** адреса провайдеров **ОБЯЗАТЕЛЬНЫ в мини-аппе**; **все** необходимые
  параметры (провайдер, модель, `base_url`) **редактируемы из UI**; переключение **провайдера
  И модели** из мини-аппа ⟹ **+2 записи каталога** ⟹ **REGISTRY 387 / GROUPS 74 / Settings 359**.
  Ревизия — **T-1144**, реализация — **T-1145**.
- **OD17 — ✅ (Q2):** `fonttools`+`brotli` — **build-only** зависимость. Реализация — **T-1146**.
- **OD18 — ✅ (Q3):** 5.11 МиБ источник шрифта → **`.gitignore`**; в git — субсет ~13 КБ + LICENSE.
  Реализация — **T-1147**.
- **OD19 — ✅ (Q4):** `var/status_key_history.json` одобрен при **обязательной leak-safety-проверке**
  (нет сырых ключей, R17-safe, права, gitignored). Реализация/верификация — **T-1148**.
Детали — `plans/archive/tma-relume-redesign/tasks.md` (§0 / §0.2; **E2: T-1119/T-1120**;
**E3: T-1121…T-1126**; **E4: T-1136…T-1138**; **E5: T-1144**; **F6: T-1145…T-1148**).
Scanner-аудит 10.4 (`plans/reports/round10.4_review_fixes.md`, `audit_backlog.md`,
`full_audit_results.md`, `global_map.md`) проверен **четырежды** 10.09.2026 (в т.ч. при OD11–OD15
и OD16–OD19; `plans/reports/` и `reports/scanner-reports/`): 0 blocker/major; **новых отчётов
по 10.5 нет** (самый свежий — `round10.4_review_fixes.md`, 10.09.2026 05:17). MED-017 (базовый
383/74/359) — **два согласованных исключения**: +2 OD11 (STT) и +2 OD16 (адреса) ⟹ **387/74/359**;
LOW-012 (CSP) — self-host субсета шрифта (OD18).
**Реализация (T-1098…T-1118 + F4 T-1127…T-1133 + F5 T-1139…T-1142 + F6 T-1145…T-1148 +
QA T-1134…T-1135, T-1143, H T-1149…T-1154) — 🟢 РАЗБЛОКИРОВАНА (GO владельца 10.09.2026):
«проект v5 утверждён → @Builder стартует с T-1098». Порядок: токены → shell/navbar → hub →
15 экранов → F4 → F5 → F6 → G → H.**
**CI/деплой-контур (при GO, DoD-пункты e/f):** перед коммитом — полный `pytest` (baseline 4860,
0 регрессий) + `node --check web/app.js` + `git diff --check`; **русский conventional-commit**
(`<type>(<scope>): раунд 10.5 — …`, напр. `feat(admin,web,chat,api): раунд 10.5 — …`) + push в
`master`; затем деплой на **198.46.175.136**: `ssh nik@…` → `cd /var/www/admin_bot` → `git pull`
→ при необходимости правка `.env` → `sudo systemctl restart admin_bot` → `sudo systemctl status
admin_bot`; финальный plain-language отчёт (done/changes/bugs/blockers); README — ироничный тон.
Детали — `plans/archive/tma-relume-redesign/tasks.md` (секция **H**, **✅ DoD**,
**📌 Конвенция коммитов**).**

**🟢 ДЕПЛОЙ-ВЕРИФИКАЦИЯ (10.09.2026, @DevOps):** commit **`918f675`**
(`feat(admin,web,chat,api): раунд 10.5 — редизайн TMA по референсу Relume: navbar, hubs,
hash-роутинг, scope-switcher, key-history, матрица ролей, градиенты, Material Symbols
(тесты 4962)`, 49 файлов) → push **`0bdf272..918f675`** в `origin/master`. Сервер
`cd /var/www/admin_bot && git pull` — **fast-forward `0bdf272..918f675`** (HEAD=**918f675**).
`.env`-изменений **не потребовалось** (Settings 359 без изменений; 4 новые записи каталога —
PG-only `_MODELS_PG_ONLY`, сид `ON CONFLICT DO NOTHING` → журнал «starter bot_settings seeded:
342 (ON CONFLICT DO NOTHING)»). `sudo systemctl restart admin_bot` → **active (running)**,
MainPID=917049, NRestarts=0, ActiveEnterTimestamp 10.09 08:21:05 UTC. Live-проверка:
`curl http://127.0.0.1:8000/api/health` = **200**; статика `web/static/fonts/material-symbols-rounded.woff2`
(13 428 B) и `web/static/vendor/dompurify-3.4.15.min.js` на месте; журнал старта — **0 error/traceback**
(единственный WARNING — известный betterstack 401 в `.env`, pre-existing, не связан с 10.5).
**Остаётся ручное:** live Telegram-smoke 15 экранов / scope-switcher GLOBAL-ЧАТ-ЛС / BackButton /
RBAC-матрица на реальном устройстве (T-1153) — автоматизации недоступно.

## Раунд 10 (07.09.2026): Multi-chat scaling (Variant A) — Granular RBAC, BYOK, chat_params-слой, PERMsoc-изоляция, Feature Gates+бюджет воркеров, TMA IA/UI

Эпик по research `plans/docs/multi-chat-scaling-research.md` (ВЫВОД: вариант А — один бот, per-chat изоляция+бюджеты, Epic 86/PG — не сейчас; 07.09.2026, апрув владельца «запланировать 3 части»). **Планирование: 6 фич, `plans/features/` — T-843…T-924** (нумерация продолжает T-842; spec.md при планировании НЕ создавался — A1-задачи зеркалят PM-базу дизайна и Q-протоколы, прецеденты раундов 7/9). **Часть 1 (RBAC/BYOK/параметры)** — `multi-chat-rbac-byok` (T-843…T-869): роли Global/Local/Moderator/User (+Custom, `bot_roles.role_type` ADD COL, сиды-сеты), `param_permissions` (key→view/edit min-role+hidden_from_local; роль-пикер у инпутов TMA для Global), `chat_profiles.chat_params JSONB` ADD COL + резолв chat_params→bot_settings→дефолт (hot_chat, кэш+NOTIFY+409 по profile updated_at, паттерн chat_lore), локальный админ/chat_admins-строки=local_admin, BYOK: `chat_keys` (свой ключ чата, маска last4, нигде raw), без своего ключа — глобальный + жёсткий бюджет `chat_usage`+`limits.chat_global_key_budget_*` (превышение → «нет ключа»-песочница), поля ключей у локального ВИЗУАЛЬНО ПУСТЫ, промпты «as-is»+«Использовать мой». **Часть 2** — `permsoc-module-isolation` (T-878…T-889): плагин `services/permsoc.py` (реестр 5 модулей: Славик/Костя/Алан+greeting/Оля/передразнивания), единый `PermsocGateFilter` (порядок роутеров bot.py НЕ менять), master `flags.permsoc_enabled` + под-тумблеры (olya/mimic — per-chat-фолбэк), дефолт OFF для новых чатов, backfill-скрипт + карточка в «Реакции и Триггеры» (до TMA-IA); `feature-gates-worker-budget` (T-890…T-902): жёсткий Opt-In (my_chat_member: новый профиль `gates_opt_in=false`, тяжёлые фичи Сон/Ностальгия/авто-лор — default OFF, включение ЯВНОЕ глобальным/локальным админом), `worker_budget`-ледежер в PG (суточные global/per-chat лимиты LLM-вызовов/токенов, приоритеты-деградация ностальгия→лор→сон, jitter-тики, расширение концепции memory_dream_log.tokens), API GET/PUT gates + GET budget, REGISTRY `limits.worker_daily_*`. **Часть 3 (UI/UX)** — `tma-ia-progressive-disclosure` (T-903…T-913): меню «Главная/Статус, Чат-Профиль, Модули и Фичи, Настройки AI, Доступы и Роли» (TABS+menu-тег, маппинг без слома), селектор чатов в шапке (чаты по правам, localStorage), progressive-раскрытие: REGISTRY `progressive_level` basic/advanced, натив `<details>`-аккордеон, роль user read-only (только Статус/Как это работает); `global-oversight-dashboard` (T-914…T-924): Global Oversight — сводка всех чатов (активность/Opt-In/тяжёлые фичи/ключ own/global/админы/бюджет, кэш+custom refresh), kill-switch (override-записи в chat_params+история-аудит, undo) и «запрет глобального ключа per chat», API `web/api/oversight.py` (только global admin; 403 иным), таблица+модалка-детали; `tma-ui-fixes` (T-870…T-877): шапка-flexbox, логи в `<pre><code>` (0.75rem/pre-wrap/break-all/компакт-скролл), relations-аватары+имена (Alias→никнейм→юзернейм, прокси /api/avatar), имена чатов вместо id в титулах, чип «авто» вместо «— авто», компактный дропдаун стадий+широкое поле заметки, перенос «Telegram ID админа» из «Реакции и Триггеры» → «Доступы». **Порядок/зависимости:** рбас/параметры (часть 1) → фронт-фиксы и PERMsoc (независимы после 1) → гейты+бюджет (2.3/2.4) → TMA-IA (нуждается в 1/x) → Oversight (всю). **Статус: ✅ Выполнен и заархивирован (08.09.2026 @PM, HEAD fac1b9f, tests 4717), см. `plans/archive/` — 6 фич F-7…F-12 (T-843…T-924)** — 4717 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §22; закрыто по ревью: T-843..T-924. Вне архива (исполняет @DevOps финальным шагом): PG-DDL (bot_roles.role_type, param_permissions, chat_keys, chat_usage, worker_budget, ALT chat_admins/chat_profiles/chat_lore_history-check) + `scripts/backfill_permsoc_gates.py` + `scripts/backfill_feature_gates.py` + live-верификация. Открытые вопросы (Q1–Q9/Q1–Q6 раунда) закрыты @Architect в A1-задачах кода.

**🔄 Фоллоу-апы раунда 10 — «Ре-дизайн 10.2» (09.09.2026, @Architect; по рекону владельца после прод-просмотра — 3 решения, см. BACKLOG):**
1. **BUG-3 «Функции PERMsoc»** — НАСТОЯЩАЯ вкладка `permsoc` (menu `modules`, тип config): master-тумблер per-chat (gates, global admin -> write, локальный — read-only) + карточки 5 модулей (Славик/Костик/Оля/Леха/передразнивания) с ID персон (`reactions.slavik_user_id`/`kostik_user_id`/`olya_user_id`/`alan_user_id`/`alan_username`), kucha (`reactions.kucha_enabled`), под-флагами (`flags.olya_enabled`/`flags.mimic_enabled`); новые группы каталога `flags_permsoc`/`reactions_permsoc`/`reactions_admin` (выделение из reactions_persons/flags_media/reactions_word_reactions/reactions_mimic), перенос групп `reactions_persons`/`limits_persons` на новую вкладку; из «Реакции и Триггеры» и карточки modules_feats эти ключи УБИРАЮТСЯ (вкладка видна даже при master OFF — гейт в runtime, не в UI; пер-парам доступы — флаги из BUG-6). Спека: `plans/archive/permsoc-module-isolation/spec.md` §10.
2. **BUG-5 пустые блоки «(0)»** — правило рендера по группе: basic-сетка только при basicItems>0; `<details class="advanced">` только при advancedItems>0 (никакого «(0)»; если basic==0 — details рендерится раскрытым); вся карточка группы скрыта при 0/0; то же для per-chat override UI (общий generic-рендер). Хелпер-фильтр в `groupedForTab` (app.js), маркер `<details class="advanced"` остаётся в шаблоне. Спека: `plans/archive/tma-ia-progressive-disclosure/spec.md` §10.
3. **BUG-6 флаги-модель прав** — вместо `view_min_role`/`edit_min_role`/`hidden_from_local`: `{view_roles, edit_roles}` (докетная форма: массивы из {user, moderator, local_admin}; global_admin неявный ВСЕГДА; пустые массивы = только суперюзер; запись подразумевает чтение (union на сервере); legacy-строки мигрируют на чтении (rank>=min → массив; hidden_from_local = фолдинг local_admin из view_roles, чекбокс удалён); DEFAULT_MATRIX: keys=[]/[], prompts=[local_admin]×2 (модератор промпты не видит — хард-правило), остальные view=[moderator,local_admin] edit=[local_admin] (юзер по умолчанию видит только Статус/Справку); НОВЫЙ `DELETE /api/access/param_permissions/{key}` — сброс на дефолт (удаление строки); секционный гейтинг (user) не меняется. Спека: `plans/archive/multi-chat-rbac-byok/spec.md` §3.2.

## Раунд 10.3 (09.09.2026): доработки и фиксы — 7 задач ТЗ (фоллоу-апы после 10.2)

Фоллоу-апы по ТЗ владельца (HEAD == origin/master == `d30b203`, 7 багов ультиматума + 2 бэкенд-рекона; pytest 4760; прод PID 454654). **7 задач → 3 фичи** (`plans/features/`), нумерация T-925…T-973 (продолжает T-924; T-925…T-964 — зафиксированы в KG ранее, файлы tasks.md утрачены при реструктуризации 03.09 → пересозданы @PM по KG-канону). Стадия на старте — PLANNED: spec.md пересоздавал @Architect по наблюдениям сущностей `feature-tma-chat-selector-fixes` / `feature-dm-user-settings` (файлы утрачены при реструктуризации); итоговый статус — см. абзац «Статус (10.09.2026)» ниже.

| # | Задача ТЗ | Фича | AC / канон |
|---|-----------|------|------------|
| 1 | Дубль выбора чата: нативный `<select>` (index.html:414-422) + кнопка «💬 Выбрать чат»/дропдаун (:426-442) + empty-states (:519, :1006) + бейдж (:444-446) | F-13 `tma-chat-selector-fixes` (T-925…T-944) | **AC-1**: остаётся ОДИН нативный select (компактный — без инлайн min/max-w); удалить кнопку/дропдаун (`openChatPicker`/`closeChatPicker`/`pickChat`/`chatPickerOpen`, app.js:151/675/702-711); индикация выбора = значение селектора + compact-бейдж; `activeChatTitle` ЖИВЁТ (index.html:945/1159) |
| 2 | Крестик ✕ сверху справа — выход из Mini App | F-13 | **AC-2**: удалить `closeApp` (index.html:460-461 + app.js:1180-1191); ⛶ `toggleFullscreen` (1193-1207) и мобильный ✕ сайдбара (index.html:376-378) НЕ трогать; grep-проверка других вызовов closeApp |
| 3 | Разделы «Реакции и триггеры», «Провайдеры», «Промпты», «Лимиты» не открываются (пустые) | F-13 | **AC-3** ROOT-CAUSE (подтверждён): Vue 3 v-if/v-for-precedence — `v-if="basicItems(grp).length || advancedItems(grp).length"` на ОДНОМ узле с `v-for="grp in currentTabGroups"` (index.html:551-552): v-if вне скоупа цикла → grp=undefined → все группы схлопываются; регрессия d30b203 (BUG-5). Фикс: `<template v-for>` + v-if на дочернем узле; вторично — configError-баннер на молчаливый 403 (MED-021) |
| 4 | ЛС настраиваются ОТДЕЛЬНО: саммари в ЛС по умолчанию ОТКЛЮЧЕНО; юзер правит параметры/фичи/лимиты/ключи СВОИХ ЛС; наследование от глобальных, кроме изменённых юзером; единственное исключение — саммари default-off | F-14 `dm-user-settings` (T-945…T-964) | **AC-4** канон: DM-скоуп = переиспользование `chat_profiles`/`chat_params` с chat_id=user.id; `is_dm_scope = chat_id > 0`; новый `chat_summary_enabled()` (default-off для ЛС); юзер ЛС = `is_dm_owner` (rank=local_admin, `access_for`); гейт `flags.summary_enabled` bot.py:613-643 НЕ трогать; ноль DDL; REGISTRY 383/71/359 без изменений |
| 5 | WARNING `[direct] no key — sandbox answer | chat=-1002661910336 | reason=budget` при живом ключе и балансе (минуту спустя бот отвечал) | F-15 `direct-sandbox-budget-investigation` (T-965…T-973) | Расследовать: канон — budget = `chat_usage` за день (TZ Екб) + `limits.chat_global_key_budget_*` (req 25 / tok 100k; 0 = запрет); счётчик растёт в конце вызова source='global' (llm_client.py:317-356, chat_usage.py:100-113); диагностика: SQL `chat_usage`/`bot_settings`, `GET /api/config/keys/status`; возможный фикс: диагностические логи бюджет-пути + фоллбэк на BYOK-ключ/ретраи |
| 6 | Раздел «Статус» в сайдбаре перекрыт шапкой; после ухода на другой раздел вернуться нельзя | F-13 | **AC-5** ROOT-CAUSE: мобильный `.sidebar` (index.html:347-350) `z-index:40` == `.header-sticky` `z-index:40` (:328-331), шапка позже в DOM → поверх; фикс `.sidebar { z-index:45 }` (+ `env(safe-area-inset-top)`); MENU_ORDER/TABS — без изменений |
| 7 | WARNING `graphrag memorize: LLM answer is not a JSON list — skipped` | F-15 | Канон: fire-and-forget memorize (direct_chat_service.py:581-584) → `parse_fact_list` (summary_memory.py:380-418); raw НЕ логируется; фикс: лог raw (обрезка/маск, R17), fallback-парсер, 1 ретрай с жёстким промптом |

**Статус (10.09.2026): ✅ Выполнены и заархивированы** — F-13 `tma-chat-selector-fixes` (T-925…T-944), F-14 `dm-user-settings` (T-945…T-964), F-15 `direct-sandbox-budget-investigation` (T-965…T-973) — IMPLEMENTED, аппрув @Reviewer; спеки/задачи — `plans/archive/{tma-chat-selector-fixes,dm-user-settings,direct-sandbox-budget-investigation}/`. **Все 7 задач ТЗ закрыты** (1–3, 6 → F-13; 4 → F-14; 5, 7 → F-15); pytest **4831 passed, 0 failed**; Scanner — 0 blocker/major (отчёт: `plans/reports/full_audit_results.md`); архитектура — `ARCHITECTURE.md` §23–§24 (обновлено @Architect). Техдолг-кандидат на след. раунд: HIGH-004 — полный LLM request/response-лог (в 10.3 делали точечно: диагностика бюджет-пути + raw-memorize с маской секретов); остальное из Scanner-отчёта — вне скоупа раунда. План финальной фазы (полный pytest → README → коммит → деплой + live-проверка) — единый для раунда: исполняется по воркфлоу ПОСЛЕ архивации (README-раздел 10.3 — шаг @PM 10.09.2026; коммит/деплой — следующие шаги).

## Раунд 10.4 (10.09.2026): реструктуризация TMA-миниаппа + точечные фиксы — 9 пунктов ТЗ

ТЗ владельца (HEAD == origin/master == `1410a68`, раунд 10.3 закрыт, рабочее
дерево чистое) — крупная реструктуризация админки миниаппа + точечные фиксы.
Step 0 recon — KG `recon: tma-structure-10.4` (полные координаты: TABS/MENU/
generic-рендер, TAB_RULES param_catalog.py:1374-1406 + _TAB_BY_GROUP :1424-1431
(жёстко: группа → ровно 1 вкладка), REGISTRY 383/71/359 эталон test_param_catalog
MED-017, каскад имён chat_lore.py:585-613/:621-637 + app.js:2335-2346,
точки чтения ТЗ 8). **Планирование 10.09.2026 @PM: 8 фич, T-974…T-1065** (нумерация
продолжает T-973). spec.md — @Architect для каждой фичи (стадия PLANNED).

| # | Задача ТЗ | Фича | Задачи | Ключевые AC / канон |
|---|-----------|------|--------|---------------------|
| 1 | «Реакции и Триггеры»: интервалы/кулдауны/Мимикрия/Dead page → в «Функции PERMsoc» | **A** `frontend-reorg-modules-reactions` | T-974…T-989 | Расширение TAB_PERMSOC: reactions {persons, permsoc, deadpage, mimic, slavik, alan, olya} + flags {permsoc, media} + limits {persons, mimic, deadpage, media}; исключения-списки TAB_LIMITS/TABS-зеркало; REGISTRY 383/71/359 без изменений |
| 2 | «Модули и Фичи» → «Модули»: имена/описания модулей, убрать сводку «Функции PERMsoc» | **A** | T-981…T-984 | MENU_LABELS.modules + label modules_feats → «Модули»; карточки модулей (имя+описание+статус); сводка-кнопка setTab('permsoc') удаляется (вкладка+master остаются); «Модули (вкл/выкл)» (flags_modules+flags_service) → новый config-раздел modules_switches |
| 3 | «Лор чатов»-настройки → в «Лор чатов» под «Расширенные» | **A** (частично) | T-979, T-985-T-986 | TAB_RULES-запись для TAB_CHAT_LORE (limits_lore + flags_lore) + generic-блок в шаблоне chat_lore; права — canEditConfig; исключены из «Лимитов» |
| 4 | Бюджеты «Прямой чат» → флаг вкл/выкл PER-ЧАТ (+ для -1002661910336 ВЫКЛ) | **B** `frontend-limits-temperature-budgets` | T-990…T-993 | Гейт flags.chat_context_budgets_enabled → hot_chat-резолв (async chat_param); override false для -1002661910336 (бэкфил/сид); связь с F-15 (25 req/сутки, sandbox R16); дефолты других чатов не меняются |
| 5 | Температура → выпадающий список | **B** | T-994…T-997 | Новый widget="select" + select_options (ParamSpec); API отдаёт options; валидация 422; REGISTRY без роста; тест widget-keyvalue обновлён |
| 6 | «Имена людей» → отдельный раздел + per-чат/ЛС | **B** | T-998…T-1001 | Новая config-вкладка people_names (limits_user_aliases), KV-редактор; алиасы → per-chat/ЛС-резолв (chat_param паттерн, каскад в web/api/chat_lore.py:555); гейт summary_enabled-плоскости не трогать; F-6-аудит каскада влит (см. ниже) |
| 7 | «Память и RAG» → «Память»; «Сон» и «Ностальгия» → отдельные разделы | **C** `frontend-memory-sleep-nostalgia` | T-1006…T-1017 | TAB_RULES: memory_rag = {limits_memory, limits_graph, flags_memory, memory_infinite}; новые TAB_MEMORY_DREAM / TAB_MEMORY_NOSTALGIA; переразметка basic/advanced (флаги вкл — basic), иначе вкладки пустые после ТЗ 5; гейты gates (F-10) не меняются |
| 8 | «Расширенные» по умолчанию СВЁРНУТЫ (index.html:673-675 `:open="basicItems(grp).length === 0 || expandOpen(activeTab)"`) | **D** `frontend-advanced-collapse-default` | T-1018…T-1023 | :open="expandOpen(activeTab)" — единый источник истины; персист adminbot.expand:<tab> не трогаем; маркер: положительный на :open="expandOpen(activeTab)", негатив на старую строку; итог-анализ эвристики в комментарии |
| 9 | LLM Провайдеры: основные модели → ключи → фолбэк → расширенные | **E** `frontend-llm-providers-layout` | T-1024…T-1032 | TAB_RULES секциями (models_main/keys_llm, groq, openrouter/models_fallback/остальное); groupedForTab — плоская сортировка по (категория, группа) источникам; заголовки секций; маскировка ключей/R17 без изменений; секции advanced ≥1 basic (совместимость с D) |
| 10 | «Участники и отношения» из «Лор чатов» → отдельный раздел; настройки отношений туда | **F** `frontend-relations-participants` | T-1033…T-1044 | Новая вкладка relations (menu chat_profile, свой шаблон; данные — существующий /chat_lore/{id}/relations API); TAB_RULES: relations = {limits_relations, flags_relations} (config-часть вкладки); из chat_lore блок участников удаляется; адаптеры 409/очистка без изменений; known_sections — без расширения |
| 11 | Чат -1002661910336: расширить лимиты контекста/саммари/памяти | **G** `backend-chat-1002661910336-scaling` | T-1045…T-1056 | per-chat overrides через chat_params (get_chat_param паттерн, async); точки чтения: direct_chat_service.py:996-1014/1498-1522/1622/1684-1880/1726, summary_generator.py:133-169, summary_xml.py:63-68, summary_memory.py:1283-1290/1966-2004/2406-2483/2572/2614; бэкфил override для -1002661910336; дефолты/другие чаты НЕ трогать; таблица значений в отчёте; риск: 25 req/сутки глобального ключа (F-15) — наблюдение |
| 12 | «Никнейм/username» в Участниках: у людей username есть, nickname нет / только id | **H** `backend-relations-nickname` | T-1057…T-1065 | Диагностика каскада (alias→nickname(30д/200)→username(топ-50)→''): причины — окно 30д/top-200, _RELATIONS_ENRICH_TOP=50, _display_name uid-снапшот; фикс: имена из users_meta-снапшота + username для ВСЕХ строк (кэш/лениво) или фикс-срез; R16 «id никогда не имя» — сохранить; каскад/отношения без регресса |

**Статус (10.09.2026): ✅ Выполнены и заархивированы** — 8 фич IMPLEMENTED,
аппрув @Reviewer: **D** `frontend-advanced-collapse-default` (T-1018…T-1023),
**C** `frontend-memory-sleep-nostalgia` (T-1006…T-1017), **E**
`frontend-llm-providers-layout` (T-1024…T-1032), **A** `frontend-reorg-modules-reactions`
(T-974…T-989), **B** `frontend-limits-temperature-budgets` (T-990…T-1005),
**F** `frontend-relations-participants` (T-1033…T-1044), **H**
`backend-relations-nickname` (T-1057…T-1065), **G** `backend-chat-1002661910336-scaling`
(T-1045…T-1056); спеки/задачи — `plans/archive/{frontend-advanced-collapse-default,
frontend-memory-sleep-nostalgia,frontend-llm-providers-layout,frontend-reorg-modules-reactions,
frontend-limits-temperature-budgets,frontend-relations-participants,backend-relations-nickname,
backend-chat-1002661910336-scaling}/`. Порядок исполнения **D → C → E → A → B → F → H → G**
соблюдён (обоснование — в плановом блоке выше, при планировании). **Все пункты ТЗ закрыты**
(маппинг — таблица выше); pytest **4860 passed, 0 failed** (4831 → +29: `test_104_backend_additions`
11, `test_progressive_tab_basic_coverage` 3, маркеры webapp_*/frontend_tab_mapping); Scanner-аудит
10.4 — 0 blocker/major (minor/info R10.4-1…R10.4-7 → `ARCHITECTURE.md` §25: R10.4-1/-2/-3 закрыты
follow-up @Builder; R10.4-4…-6 — открыты, кандидаты след. раунда; R10.4-7 — задокументированная
граница G-4 → кандидат F-5). Техдолг-хвосты: **B-13 points 2-4** — per-chat алиасы НЕ доходят до
инжекта `<user_relations>` (работает только точка 1 — TMA-каскад list_relations; отклонение
зафиксировано комментарием в `user_relations.py`, кандидат след. раунда); HIGH-004 (полный LLM
request/response-лог) — отложен, как и в 10.3. Архитектура — `ARCHITECTURE.md` §24–§25 (обновлено
@Architect; счётчик групп 71→74 сверен); REGISTRY 383/74/359 — БЕЗ изменений (эталон
`test_param_catalog`, MED-017); SQLite v8; каноны промптов (R9/PREV_R9, R46-2) и порядок роутеров
`bot.py` — без дифов. Код — в рабочем дереве Merge Phase (коммит/деплой + бэкфилы
`backfill_104_chat_flags.py`/`backfill_104_overrides.py` + live-верификация @DevOps — финальный
шаг раунда).

**Конфликт-матрица с активными фичами F-1…F-6 (проверка @PM 10.09.2026):**

| Активная | Пересечение | Решение / порядок |
|----------|-------------|-------------------|
| **F-1** `post-deploy-admin-minors` (T-648 атомарный POST /api/config; T-651/T-652 касты) | T-648 routes.py POST /api/config — фича B добавляет select-опции и per-chat алиасы (POST путь тот же); T-651 унификация кастов у normalize_value/_coerce — фичи B/G касаются каста (select-значения str; override-касты) | Порядок: **F-1 ДО фиш 10.4-b/g** (после D/C/E/A — не пересекаются). B/G учитывают «атомарность POST» в своих критериях (значение select/алиас — валидный item); T-653 (guard alan) — вне пересечения, но B (температура-float) учесть NaN-поведение (T-654 docstring). |
| **F-2** `admin-debug-webview` | пересечений нет (отдельная страница /debug_config) | Независима; остаётся открытой; верификация — после раунда 10.4 |
| **F-3** `scam-incident-security-followup` (T-663 админ-гейт DM-веток /mimic /deadpage /alangreet, admin_commands.py:40-127) | прямых пересечений нет (admin_commands не дифается); но T-663-плоскость DM (chat_id>0) — та же, что у B (per-chat/ЛС) и F (участники в ЛС) | T-663 — открыта; после 10.4 (иначе расхождение: F добавляет relations-блок для DM — перепроверить при вёрстке T-663: гейт-ветки остаются как есть); отметить в финальной проверке раунда |
| **F-4** `frontend-admin-bugfixes` (Баг-4 «сверка синхронизации разделов», открыт) | Баг-4 проверяет ВСЕ вкладки админки → реструктуризация 10.4 (A/B/C/E/F) меняет карту вкладок; сверку делать ПОСЛЕ | **Порядок: 10.4 (все фронт-фичи) ДО Бага-4** (иначе сверка по старой карте); Баг-4 остаётся открытым, применяется к новой структуре |
| **F-5** `config-read-path-audit` (аудит settings.X vs hot.get) | Фичи G (per-chat резолв) и B (гейт per-chat) добавляют НОВЫЕ read-пути (hot_chat/chat_param); B — алиасы-чтение per-chat | Реестры новых read-путей — в tasks.md G (T-993 AC-B4) и B; **F-5 ПОСЛЕ G/B** (аудит включает новые пути); F-5 остаётся открытой |
| **F-6** `user-aliases-admin` (алиасы в админке — в master 5d011d2; открытые: аудит каскада, «реальный эффект», человеческая верификация, регресс) | **ПРЯМОЕ пересечение с B (ТЗ 6 «Имена людей») и H (ТЗ 9 каскад)** | **Решение: НЕ переоткрывать F-6; влить остаток в 10.4:** аудит каскада AliasResolver → фича H (T-1058/T-1059/T-1063); «реальный эффект» (алиас из админки → /summary/граф) → фича B (T-1005); человеческая верификация → владельцу (сохранить в отчёте B); полный регресс — в каждой фиче. F-6 помечается в графе как «SUPERSEDED_BY(round10.4)» (папка/спека НЕ трогаются, в архив не переносим) |

**Остаётся активным (вне 10.4):** F-1 (перед B/G), F-2 (самостоятельно),
F-3 T-663 (после 10.4, перепроверка DM-плоскости), F-4 Баг-4 (после 10.4),
F-5 (после G/B), F-6 (влить/SUPERSEDED — см. выше); техдолг-кандидаты из
Scanner (plans/reports/full_audit_results.md): HIGH-004 (полный LLM-лог) —
отложен (F-15 сделал точечно); другие HIGH-001/002/003/005/006/007/008 +
MED-* — вне скоупа (дефект-эпик — кандидат на следующий раунд). Диск/SSH
сервера (fail2ban/ufw, деплой-операции) — active (см. MEMORY.md, раздел
«Безопасность сервера»).

**Тест-риски раунда:** test_frontend_tab_mapping.py и
test_webapp_nav_disclosure_ui.py придется обновить в КАЖДОЙ фронт-фиче
(MED-022-прецедент 10.2/10.3 — маркеры фиксируют старое поведение);
test_param_catalog (эталон 383/71/359) — не менять; test_webapp_avatars_ui /
test_webapp_dm_ui / test_webapp_rbac_ui — поправка под новые вкладки;
new Select-widget-тест; структура-разметка (basic ≥1 на вкладку) — новый тест;
`node --check web/app.js` — на каждой фронт-фиче; полный pytest — общий финал
раунда (baseline 4831 + новые, ожидание ~4850-4900).

**Конфликты с активными фичами (проверка @PM 09.09.2026):**
- **F-1 `post-deploy-admin-minors`** — T-648 (атомарный POST /api/config: `web/api/routes.py`) пересекается с F-14 POST /api/config (ensure_scope_profile + is_dm_owner-гейт, routes.py:380-388) → порядок: F-14 ДО T-648; T-650 (docstring `can_edit_param`, deps.py:206-212) — F-14 расширяет саму функцию в `services/access.py` → T-650 после F-14; T-651/652 (унификация кастов) — учесть новый cast в `get_chat_param_defaulted`.
- **F-3 `scam-incident-security-followup`** — T-663 (админ-гейт DM-веток `/mimic /deadpage /alangreet`, admin_commands.py:40-127) — та же DM-плоскость (chat_id>0), что F-14; в F-14 admin_commands.py НЕ диффится, T-663 остаётся открытой → исполнять после F-14, отметить в финальной проверке.
- **F-4 `frontend-admin-bugfixes`** — Баг 4 («сверка синхронизации разделов») затрагивает тот же рендер-зон конфиг-вкладок (index.html:551-552), что AC-3 → порядок: F-13 ДО Бага-4 F-4 (иначе конфликт шаблона и двойная сверка).
- **F-5 `config-read-path-audit`** — остаточный аудит `settings.`-read-путей: новые read-пути F-14 (`chat_summary_enabled`/`get_chat_param_defaulted`) и F-15 (бюджет/`WORKER_BUDGET_TZ`) включить в аудит (стиль «через hot.get» — обязателен).
- **F-6 `user-aliases-admin`** / **F-2 `admin-debug-webview`** — пересечений нет (аудит/верификация, других файлов).

**Scanner-аудит (plans/reports/full_audit_results.md, 09.09.2026) — учтён частично:** HIGH-004 → F-15 (диагностические логи бюджет-пути/raw-memorize; полный LLM request/response-лог — вне 10.3, кандидат в след. раунд), MED-021 → F-13 AC-3 (configError-баннер), MED-019 → F-14 (юнит-тесты DM-матрицы, T-941), MED-017 → F-14 (каталог без изменений — эталон test_param_catalog), MED-022 → обновление маркер-тестов (F-13/F-14), MED-015 → F-15 (точечные правки, сигнатуры не меняем). Остальное (HIGH-001/002/003/005/006/007/008, MED-003…008/011…016/018/020, LOW-*) — вне скоупа 10.3; дефект-эпик «техдолг по аудиту Scanner» — кандидат на след. раунд (список: reports/full_audit_results.md).

## Раунд 9 / Фаза 2 (06.09.2026): AGI Memory Implementation — 2a Отношения (A-Life) + dig_into_lore → 2b «Сон» (beliefs) → 2c Ностальгия

Эпик = реализация Фазы 2 research `plans/docs/agi-memory-research.md` (§3–6, §7, §10; Фаза 1 research-only завершена 06.09) по апруву владельца с правками: **локальная LLM (Ollama qwen3.5:9b) НЕ используется в боевых воркерах** — «сон»/ностальгия/отношения работают только на облачных моделях через существующий LLMClient (apinet/deepseek + fallback, путь обычных ответов; локальная осталась для разовой векторизации истории); **настройки A-Life — ВНУТРИ существующего раздела «Лор чатов»** (PG `chat_profiles`, per-chat, блок «Участники и отношения» во вкладке «Лор чатов»; блоки «Синтез (сон)» и «Ностальгия» — во вкладке «Память и RAG»), новых TMA-разделов не плодим. Планирование: `plans/archive/agi-memory-implementation/tasks.md` — **T-815..T-838** (24 задачи, секции A–H; дизайн-решения и протокол Q1–Q14 — раздел A tasks.md; spec.md при планировании не создавался по ТЗ владельца, прецедент раунда 8). **Решения @PM (структура): одна реализация + один деплой** (все подфазы в одном эпике, порядок B→C→D→E→F, один прод-окно; риск — тумблеры подфич off по умолчанию), задачи сгруппированы по подфазам. Скоуп: 2a — SQLite `users_meta` (аддитивно, PK(chat_id,user_id), стадии stranger→…→veteran с decay/анти-откатом, manual-стадии админа — PG `chat_profiles.relations JSONB` + 409-оптимизм, инжект `<user_relations>` в direct_chat) + tool `dig_into_lore` (3-й в TOOL_CALLING_TOOLS, FTS5+граф-имена+год-фильтр, 5–8 сниппетов, канон R9: ИНСТРУМЕНТЫ+=dig + контракт «помнишь/в 2024 → вызови ДО ответа» + PREV_R9-ступень миграции PG-промпта, пре-гейт маркеров); 2b — миграция **v8** (rebuild graph_facts: importance/source_ids/kind/belief_meta + origin `derived_belief`, user_version=8, по образцу v7) + importance-правило на записи + DreamWorker (облачный LLMClient, кластеризация без LLM, пороги/бюджеты, дистилляция 0–2 beliefs с source_ids, supersede, memory_dream_log); 2c — ностальгия слой A (маркер «можно вспомнить» при ответе, 0 LLM-вызовов) + слой B NostalgiaWorker (тихий период, «N лет назад», один облачный вызов на срабатывание, жёсткий анти-спам: max/сутки, quiet hours, cooldown, стоп после 2 неотвеченных, aggressiveness, nostalgia_log). **RUNTIME WARNING:** SQLite-схема прода/локально — v7; единственная миграция эпика — v8 в фазе 2b (2a работает на v7); новые таблицы — только CREATE IF NOT EXISTS без bump; PG — только ADD COLUMN IF NOT EXISTS relations; промпт-канон R9 — через PREV_R9/PROMPT_MIGRATIONS/байт-тесты. **Статус: ✅ Реализован и заархивирован (06.09.2026) — деплой T-837, см. `plans/archive/agi-memory-implementation/`** — 4562 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §21; закрыто по ревью: T-815..T-835. **Статус: ✅ Полный (06.09.2026) — T-836 (README-раздел «AGI Memory (Фаза 2, раунд 9)» + счётчик 4562) и T-837/T-838 (деплой на прод) закрыты @DevOps:** коммиты 663664e..5694f66 (6 feat + docs(readme) + docs(plans)) → пуш `84c4887..5694f66`; сервер `git pull --ff-only` → `aafb769..5694f66`; бэкап БД до миграции — `/home/nik/backups_adminbot/local_database_20260906_111233_pre_v8.db` (755 МБ, sqlite3 .backup); рестарт `admin_bot` → active; журнал: `[database] migration v8: graph_facts rebuild (importance/source_ids/kind/belief_meta + derived_belief)` + user_version=8, `[prompt_migration] канон обновлён | key=prompts.direct_chat_system_prompt` (R9), DreamWorker/NostalgiaWorker зарегистрированы (флаги off — джобов нет), RelationsService initialized, LoreWorker started, ошибок 0; live-верификация: PRAGMA user_version=8, `graph_facts` = 10557 (сохранено ~10.5k), колонки importance/source_ids/kind/belief_meta + CHECK origin `derived_belief` (INSERT-проба → ok → откат), таблицы users_meta/dream_state/memory_dream_log/nostalgia_log созданы, PG `chat_profiles.relations/relations_enabled` (information_schema) применены, пул concurrency per_chat=3, health `/api/health` = 200, error|traceback = 0.**

## Раунд 8 (06.09.2026): Context-Layer X-Features — 24 пункта [х] из CONTEXT_RESEARCH (атрибуция людей, фокус, память, RAG, промпт)

Эпик по research `plans/docs/CONTEXT_RESEARCH.md` (24 отмеченных `[х]` пункта §2; НЕ входят п.15 «дедуп повторов в окне» и п.19 «порог минимальной релевантности RAG» — `[ ]`): **(Атрибуция)** uid рядом с именем во всех рендерах Global_Context/Thread/UserResolutionMap/Target_User (каскад алиас→никнейм→юзернейм не меняется; «хвосты»-коды не выдаются в чистовых сообщениях), UserResolutionMap по активным участникам (SQL-агрегат), дискриминатор коллизий имён (внутренний, на рендере), привязка фактов к uid/канон-алиасу в memorize/_canon_fact_name, Target_User с uid + protected/RAG-фильтры по людям, «кто спрашивает vs кому адресован» + memorize-хук; **(Фокус)** блок `<Current_Question>`, правила приоритета в системный промпт, защита конспекта от обрезки (verbatim-хвост режется первым), Thread не рвётся на бот-сообщениях (parent-линк бот-реплик), итог ветки над фоном (без LLM), метки свежести блоков; **(Память)** importance-удержание verbatim при переполнении (маркеры имён/«бот»/цитат/чисел), progressive summarization (summary-of-summary, уровни конспекта), compress/purge не трогает protected/высоковесные, пересборка конспекта по заполнению (не по TTL); **(RAG)** подача по rel=cosine×w_eff (не по хронологии), дедуп RAG↔конспект, метки origin+давность, опциональный LLM-реранк top-k (флаг, off по умолчанию, паттерн search_service._rerank_results); **(Промпт)** «как читать блоки» в начало системного промпта, важное к концу user-блока (Target_User/Protected/Current_Question после map/RAG), sandwich-напоминание в конце, стабильный system-префикс для prompt-cache. Меняется `CHAT_SYSTEM_PROMPT` → PREV-слепок + ступень в `PROMPT_MIGRATIONS` + байт-тесты; порядок блоков user-контента → регресс TestContextPartitioning/бюджета. **RUNTIME:** SQLite-схема прода v7 — миграции для пунктов НЕ нужны по умолчанию (новые таблицы — только CREATE IF NOT EXISTS в init; ALTER/bump user_version v8 — только по обоснованию @Architect в A1 для п.10/п.14); локальный graph-воркер истории завершён; история-БД не трогается. Планирование: `plans/features/context-layer-x-features/tasks.md` — T-789..T-814, секции A–H (дизайн-решения и протокол Q1–Q13 — раздел A tasks.md; spec.md при планировании не создавался). **Статус: ✅ Полностью выполнен и задеплоен (06.09.2026)**: 4321 passed / 0 failed, аппрув @Reviewer, архитектура — `ARCHITECTURE.md` §20, закрыто по ревью T-789..T-811 [x]; **деплой (T-813, 21:17 UTC):** git pull --ff-only b198d13..aafb769 → рестарт `admin_bot` → active; SQLite остался v7 (миграций user_version нет), идемпотентные CREATE IF NOT EXISTS применились — таблицы `bot_reply_parents` и `chat_summary_levels` на месте (live-SQL: 2 строки); авто-миграция канона: `[prompt_migration] канон обновлён | key=prompts.direct_chat_system_prompt` (R8); health /api/health = 200; uptime-heartbeat тикает (60s), malformed/error = 0; README-раздел (T-812, коммит 6928df9) и отчёт/закрытие (T-814) выполнены; финальный memory-sync — docs-коммит @DevOps/@Memory; см. `plans/archive/context-layer-x-features/`. Вне архива (исполняет @DevOps финальным шагом в T-812..T-814): README-раздел «Context-Layer X-Features» (T-812), деплой раунда: коммит → пуш → сервер git pull --ff-only, бэкап SQLite-БД, авто-миграция канона `prompts.direct_chat_system_prompt` (migrate_prompt_canons) + идемпотентные CREATE IF NOT EXISTS новых таблиц, рестарт бота, live-верификация (T-813), отчёт юзеру и закрытие (T-814).

## Раунд 7 (05.09.2026): Chat Lore Management v2.0 — PG-профили чатов, авто-лор-воркер, TMA «Лор чатов»

Эпик по research `plans/docs/chat-lore-management-research.md` (вариант C, [x] рекомендован §5) + ТЗ владельца: вывод захардкоженного лора (`services/chat_lore.py`, раунд 5, T-733) в управляемую сущность — 4 новые PG-таблицы (`chat_profiles` manual/auto-лор независимы + `chat_lore_history`-аудит + `chat_links`-ремаппинг + `chat_admins` per-chat), раздел Mini App «Лор чатов» (селектор чатов, ручной/авто-лор, настройки окна/периода, «Сгенерировать сейчас», история, remap; 409-optimistic locking), авто-воркер лора (окно `smart_messages` → Merge-промпт-канон → запись auto_lore; pg_advisory_lock, NOTIFY `lore_updated` + LISTEN-инвалидация RAM-кэша профилей), lifecycle-хендлеры (my_chat_member бота, migrate_to_chat_id), инжект PG-лора в direct_chat (cap, fail-open, флаг `flags.lore_inject_enabled`; легаси SQLite-путь сохраняется при отсутствии PG-профиля), сид `scripts/seed_chat_lore.py` для -1002661910336. **RUNTIME WARNING:** локально работает graph-воркер юзера (SQLite-история) — вне скоупа SQLite-схема/`tools/history_import/`/`manage.py`/`summary_memory`; весь код эпика — PG + FastAPI (`web/api`) + TMA (`web/app.js`+`index.html`) + добавочные aiogram-хендлеры (порядок роутеров bot.py не менять). Планирование: `plans/archive/chat-lore-management-v2/tasks.md` — T-770..T-788, секции A–I (дизайн-решения и протокол Q1–Q9 — раздел A tasks.md; spec.md при планировании не создавался). **Статус: ✅ Выполнен и заархивирован (06.09.2026), см. plans/archive/chat-lore-management-v2/** — 4207 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §19; закрыто по ревью T-770..T-785. Вне архива (исполняет @DevOps финальным шагом в T-786..T-788): README-раздел «Лор чатов (v2.0)» (T-786), деплой раунда на прод: сид `scripts/seed_chat_lore.py` для -1002661910336 + live-верификация вкладки TMA (T-787), отчёт юзеру и закрытие (T-788).

## Раунд 6 / ФАЗА 2 (05.09.2026): эпик импорта истории + бессрочная память (гибрид FTS5 + GraphRAG)

Планирование фазы 2 (пункт 5 раунда 5) после фазы 1 (архив `betterstack-lore-prompts-round5`, 3844 passed; HEAD afe265a; дерево на планирование: `M plans/docs/memory-project-overview.md`). **Эпик** = пункт юзера «Миграция истории чатов, отмена TTL и Гибридная память (FTS5 + GraphRAG)»: 4 JSON в `migrate_history/` (1.08 ГБ, 2.217M сообщений, ОДИН чат, переезжавший между экспортными id 2661910336/2417005237/1691371902; таргет runtime-супергруппа `-1002661910336`) → FTS5-импорт в `smart_messages` (этап на СЕРВЕРЕ: только он, RAM 961МБ, диск ~14ГБ свободно) + GraphRAG-воркер по истории (этап ЛОКАЛЬНО на ноутбуке юзера: Ollama `qwen3.5:9b` через OpenAI-совместимый endpoint, эмбеддинги API gemini-embedding-001 dim 3072 в существующие vec0) + бессрочное хранение (тумблер `memory.infinite_retention`, отмена TTL/purge) + миграция v7 (`graph_facts.message_timestamp`, origin `history_import`) + `manage.py import_history` (tqdm, чекпоинты/resume). Планирование: `plans/archive/history-import-hybrid-memory/tasks.md` — T-747..T-769 (секции A–G; дизайн-решения — раздел A tasks.md, отдельный spec.md создан @Architect 05.09). **Статус: ✅ Выполнен и заархивирован (05.09.2026), см. plans/archive/history-import-hybrid-memory/** — 3936 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §18. Импорт данных — операционный шаг @DevOps/юзера ВНЕ архива: FTS-этап — на сервере (T-767), graph-этап — на ноутбуке юзера (T-768). Вне архива (исполняет @DevOps финальным шагом в T-765..T-769): README-доки (T-765), деплой фазы 2 на прод с тумблером `memory.infinite_retention` ДО импорта (T-766), FTS-импорт (T-767), graph-этап по инструкции (T-768), перенос graph-дельты на прод + отчёт (T-769).

## Раунд 5 (04.09.2026): betterstack-токен, лор-инжект, промпты; фаза 2 — импорт истории (отдельно)

Планирование раунда 5 после раунда 4 (архив ниже). ФАЗА 1, четыре пункта: (1) **betterstack-токен** — root cause 401 найден: код корректен (токен строго из .env, bot.py:115-116), юзер вставил в `LOGTAIL_SOURCE_TOKEN` public key из SENTRY_DSN вместо Source Token (Logs → Sources) → код-эвристики (детект DSN-pubkey, `from=` в attached-маркере, 401-WARNING-подсказка) + отчёт юзеру с curl-инструкцией; (2) **лор-инжект** чата 2661910336 (конфа пермская, бот ошибочно считает её екатеринбургской): миграция v6 protected_facts (user_name nullable) + чат-уровневые факты (user_name IS NULL, видны всем в `<protected_facts>`) + `services/chat_lore.py` (CHAT_LORE_2661910336 + idempotent inject) + инжект/чистка «екатеринбург»-фактов на проде с бэкапом; (3) **память sqlite→PG НЕ выполнять** — Epic 86 заморожен (04.09.2026, решение владельца, см. ниже); (4) **промпты** — во ВСЕ user-facing промпты (9 констант/9 PG-ключей prompts.*) единый запрет кавычек-ёлочек («») и длинных тире (—) + смягчение строчных («Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы»); PREV_-слепки канонов + `services/prompt_migrations.py` (PROMPT_MIGRATIONS + migrate_prompt_canons, замена migrate_direct_chat_prompt_if_legacy). **Статус: ✅ Выполнен и заархивирован (05.09.2026), см. plans/archive/betterstack-lore-prompts-round5/** — 3844 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §17. Вне архива (исполняет @DevOps финальным шагом в T-743..T-746): лор-инжект в прод (T-743), чистка «екатеринбург»-фактов в чате 2661910336 (T-744), деплой и live-проверки (T-745), отчёт юзеру с curl-инструкцией (T-746). Пункт 5 (фаза 2 — импорт истории 4 JSON + FTS5/GraphRAG) — отдельный цикл ПОСЛЕ деплоя фазы 1, в этот раунд не входит.

## Раунд 4 (04.09.2026): собственный BetterStack-хендлер, отказные ответы видео-моделей, «запомни/забудь», промпт-баг TMA

Планирование раунда 4 после раунда 3 (архив ниже). ПЯТЬ блоков. (1) BetterStack: log_config=None уже стоит (hotfix 30.08, bot.py:626-634), реальной причины «логи не идут» в коде не видно; logtail-python 0.4.0 — чёрный ящик (raise_exceptions=False, drop_extra_events=True, тихие дропы, ошибки не логирует); aiogram.event логирует КАЖДЫЙ апдейт на INFO (aiogram 3.31 dispatcher.py:174-185) → спам; уровня не задан. Решение: заменить LogtailHandler собственным BetterStackHandler (logging.Handler, POST на in.logs.betterstack.com, payload-совместимость с logtail frame.py: dt/level/severity/message/context.runtime/context.system, Bearer), буфер+фоновый флашер, ЯВНЫЙ лог ошибок в journald (WARNING, ≤1/60с), счётчики, стартовое тест-событие, flush при shutdown; aiogram.event → WARNING. (2) Видео: free-роуты OR могут отказывать/не получать видео (minimax-m3:free, gemma-4-31b-it:free — только кадры, без аудио; audio+video из free — только nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free, требует live-проверки): отказные ответы («не вижу видео» и т.п.) сейчас проходят как успех L1/L2 и уходят юзеру; даже успешный визуал не слышит звук. Решение: детект отказных/пустых ответов (маркеры + мин-длина) → считать пустым уровнем → каскад на fallback/STT; дефолты: primary → nemotron-omni:free, fallback → minimax-m3:free; промпт-маркер VIDEO_UNAVAILABLE — на решение @Architect (менять канон = PG-миграция). (3) Память-команды «запомни X» / «забудь <слово/фраза>» в direct_chat (существующее: /forget по bot_direct_reply своего target_user, /clear, protected_facts пуста в проде); RBAC чата: ConfigCache admins/roles/get_role (bot_admins: telegram_id/role_name) с фолбэком settings.ADMIN_USER_ID; тумблер flags.memory_commands_user_enabled (default false); хранение — origin 'user_memory' (CHECK-миграция v5) или protected_facts (решение @Architect); журнал graph_fact_compressions; пул CHAT_MEMORY_CMD_*. (4) Промпт-баг TMA: фронт web/app.js:550-551 `isNaN(value)` для str-полей (isNaN('текст')===true) → ложный toast «Некорректное значение…», сервер для str принимает всегда; пустой промпт — 422 сервера или тост (решение @Architect). (5) Research/процесс: отчёты импорта истории (plans/docs/memory-import-research.md — 3 файла ~602МБ ~1.27M сообщений, ТРИ разных чата: 2417005237/2661910336/1691371902 — отметить юзеру; стоимость FTS бесплатно/эмбеддинги ~$0.3-5/LLM-факты ~$3-15 на 100k; free-роуты 50 req/день непригодны) и sqlite→PG (plans/docs/sqlite-to-pg-research.md, Epic 86); .gitignore += migrate_history/ (риск коммита 600МБ — ОТСУТСТВУЕТ); даты в RAG-фактах (created_at «%Y-%m-%d» в рендер chat_history get_rag_context — «что было N-числа» сейчас не работает); правило авто-коммита memory-sync в конце каждого раунда. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/betterstack-own-handler-video-memory-cmds/** — 3794 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §16. Вне архива (исполняет @DevOps финальным шагом в T-726): правило G1 → plans/project.md, README-правки, коммит всего, пуш, деплой и live-верификация. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Epic 86: GraphRAG → PostgreSQL

Миграция GraphRAG-хранилища (граф nodes/edges, векторы, индексы, TTL/cleanup) с SQLite на PostgreSQL 16 (asyncpg). Извлечена из Epic 85 (решение человека 30.08). **Статус: ОТМЕНЁН/ЗАМОРОЖЕН (04.09.2026, решение владельца — раунд 5, пункт 3): миграцию памяти sqlite→PG НЕ выполнять, память остаётся на SQLite; DESIGN @Architect не запускать; при необходимости эпик может быть переоткрыт.** (Источники: board.md, backlog.md:8435-8437 в git-истории до 03.09.2026, MEMORY.md.)

## Epic: Улучшения фактчека (аудит FACTCHECK_AUDIT)

4 рекомендации «вне скоупа» из аудита 2026-08-20: (1) жёсткий вердикт-формат в промпте + обязательные источники; (2) параллельный каскад Tavily+Exa (замена последовательного); (3) кэш проверок claim→hash→TTL 1ч; (4) query expansion. **Статус:** не начат; НЕ связан с отложенными идеями RESEARCH_HUMAN. (Источник: FACTCHECK_AUDIT.md в git-истории до 03.09.2026; выжимка — `docs/factcheck-audit.md`.)

## Bugfix-раунд 04.09.2026: TG-видео-команды, безопасный direct-stream, Tool Calling-фиксы

Bugfix-раунд после эпика 04.09 (архив ниже). Три блока: (1) «транскрипт/че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе» работают ТОЛЬКО для YouTube-URL (handlers/youtube.py:47-107: парсер возвращает `(None, None)` без URL → UNHANDLED), обычные TG-видео (video, документы mime video/*, в т.ч. репосты/forward) никем не обрабатываются — единственный медиа-хендлер `F.voice|F.video_note`; (2) маршрутизация скачивания: `is_direct_media_url` стримит «прямые» `.mp4/.webm/...` даже у известных платформ (youtube/tiktok/instagram/vk/x/rutube и пр.), у direct-ветки «скачай» нет `cooldown_touch`, реплай «скачай» на видео-сообщение не разбирает `reply_target`; (3) tool calling direct_chat: `CHAT_SYSTEM_PROMPT` не упоминает инструменты, description'ы `query_chat_memory` не покрывают счётные вопросы («сколько раз…»), результат тула не содержит count/даты, возможна тихая деградация на 1-м раунде (`tool_loop.py:37-49`). **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/tg-video-tool-calling-fixes/** — 3526 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §14. Вне архива: README-правки, коммит всего, пуш, деплой и live-верификация (T-683…T-685) — финальный шаг @DevOps. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Раунд 3 (04.09.2026): видео-мультимодал по файлам (/media/), «сцуко»-петля, BetterStack

Планирование раунда 3 после bugfix-раунда 04.09 (архив выше). Три проблемы. ПРОБЛЕМА 1 — BetterStack: сервер исправен (токен 26 симв на месте, сеть 200, logtail-python 0.4.0), но события в панель не идут; вероятные причины — тихие потери буфера logtail (Queue 1000, raise_exceptions=False, drop_extra_events=True), жёсткий SIGKILL при рестарте 02:11:14 (stop-sigterm таймаут 30с), сторона панели. ПРОБЛЕМЫ 2+3 — видео: (02:45) выжимка «по памяти» на «немом» TG-видео (транскрипт 29 симв → RAG facts=10; визуального канала у медиа-ветки нет), (03:21) Groq timeout → OpenRouter STT HTTP 400 → отказ; баг CHECK constraint graph_facts.origin без 'video_transcript' (сотни тихих падений), «smart_message row not found» при L2-инъекции; «транскрипт» медиа-ветки без HTML как у кружков. Целевая логика: выжимка и «транскрипт» для ВСЕХ типов видео (YouTube/прямые/нативные/не-YouTube платформы) ТОЛЬКО по реальному контенту; для мультимодалки нативных файлов — новая публикация временных файлов: FastAPI /media/<signed>/<file> (HMAC+TTL, 127.0.0.1:8000) + Caddy-маршрут /media/* наружу. ПРОБЛЕМА 4 — «сцуко»: слово впервые сгенерировала САМА модель deepseek-v4-flash (fallback при аварии apinet 03:43:55), дальше петля style_anchors (копирование дословно, 14/16 ответов) + RAG bot_direct_reply (TTL пусто = вечно); промпт в БД == канону, «сцуко» в промпте нет. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/video-multimodal-pipeline-and-incidents/** — 3618 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §15. Вне архива (исполняет @DevOps финальным шагом): чистка «сцуко» в БД прода, BetterStack live-тест и TimeoutStopSec, README-правки, коммит всего, пуш, деплой с Caddy-маршрутом /media/*. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Epic: Мультимодальная саммаризация, Tool Calling, рефакторинг реакций и UX/UI админки (АРХИВ)

4 части: (1) каскадная видео-выжимка через OpenRouter `video_url` — primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем старая логика субтитров (graceful degradation); (2) Tool Calling — `execute_web_search`, `query_chat_memory`; (3) фиксы реакций — тумблеры `reactions.vasya_enabled`/`reactions.kucha_enabled`/`flags.mimic_enabled`/`reactions.alan_mimic_enabled` (default `false`), строгий гейт `slavic_chlen.mp4` по `reactions.slavik_user_id`, Alan → Леха; (4) UX/UI админки — группировка вкладок, KV-редактор `limits.summary_aliases`. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/multimodal-summarization-tools-reactions-ui/** — 3447 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §13. Вне архива: деплой и живая верификация (T33/T34) — шаг @DevOps; финальный memory-sync — шаг @Memory.

---

Сознательно отклонённые/отложенные идеи (RESEARCH_HUMAN): per-bot throttle, wallet на чат, triage-гейт, TTS, мемы и пр. — НЕ активны, см. `docs/research-directchat-digest.md`. Закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).
