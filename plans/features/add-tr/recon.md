# ADD-TR — recon: runtime tool access, Direct-вход, медиа-цели и мобильная сетка

- Дата разведки: **19.10.2026** (прод — UTC; локальное дерево Windows). Режим: **read-only**.
- Записи этой разведки: только этот файл + `evidence/**`. Код/карты не менялись; чужие
  незакоммиченные правки (CFG-02B, VISION-FIX-CORE) не трогались.
- Прод: **один** read-only SSH-коннект (`evidence/recon/prod_recon_tr.py`), без записей,
  секреты не печатались; SSH-бан не провоцировался (один логин, без ретраев).
- Источники задач: `plans/current_task.md:1633-1731` (ADD-TR.0–5); VISION-RECON
  `plans/features/p0-vision-universal/recon.md`; `plans/features/p0-save-init-ux/ux-plan.md`.
- Рендер-замеры выполнены на **прод-байтах** коммита `3b02366e` (экспорт `git show` в scratch,
  см. §6) — harness `tests/ui_p0a_ux_speech_compact_e2e.py` (webroot подменён на committed-копию).

Код-якоря ниже: HEAD рабочего дерева `ce9d17ea` (== `origin/master 3b02366e` + только `plans/**`).
Файлы, изменённые чужими лейнами в worktree: `services/mca_vision.py`, `services/image_generation.py`,
`services/tool_router.py` (хвост `_generate_image`), `services/capability_registry.py` (+15 строк),
`config/settings.py`, `web/app.js`, `web/index.html`, `web/api/*`, часть тестов. Якоря в остальных
файлах — committed. Для `tool_router.py` и `capability_registry.py` указанные ниже строки правками
лейнов не затронуты (проверено `git diff -U0`).

---

## 1. ADD-TR.0 §4 — master vs producer revision и effective gates

**Git-факты (без SSH, локально):**

- `origin/master` = `3b02366e63022eb4c760892aa1bcb4f26516e789`; `git diff origin/master..master` →
  **0 runtime-файлов** (39 файлов, все — `plans/**`: доки/evidence P0).
- `git diff 3b02366e..origin/master` — **пусто** (0 строк): «прод-кандидат 3b02366e» и есть
  опубликованный `origin/master`.
- Прод (19.10.2026, read-only): `HEAD=3b02366e63022eb4c760892aa1bcb4f26516e789`, версия 2.58.90
  (деплой 18.10 13:34 UTC, `plans/features/p0-save-init-ux/evidence/release-25890/`). На момент деплоя
  `TRACKED_MOD=0`, `DELTA_RUNTIME == whitelist` (19/19), 30/30 sha артефактов совпали с кандидатом.
- Честная оговорка: сегодняшний `git status --porcelain | wc -l` на проде = **13 строк**
  (состав не расшифрован — канал один, повторный коннект не открывался). Это **не** runtime-дрифт
  относительно кандидата (HEAD неизменён; на деплое дрифт был 0), но формально 13 записей
  (вероятно untracked-артефакты) стоит закрыть в следующем штатном коннекте (например, при деплое фиксов).

**Прод effective gates (bot_settings, секретов нет; полный вывод — `evidence/recon/prod_recon-tr-2026-10-19.txt`):**

| Ключ | Значение | Комментарий |
|---|---|---|
| `flags.direct_l1_enabled` | **<no row>** → hot-дефолт **True** (env `DIRECT_L1_ENABLED` <unset>) | L1-планировщик **включён**; прод-подтверждение: `l1_planner` 155 вызовов / `L1_PLAN` 145 событий за 7 дней |
| `flags.vision_enabled` (global) | **False** | глобально выключено |
| `flags.vision_enabled` per-chat | **True** в обоих рабочих группах (−1004482340693, −1002661910336) | `chat_profiles.chat_params.overrides` — включая per-chat override зрение включено |
| `flags.factcheck_enabled` | True | |
| `temporal.tool_enabled` | True | инструмент `fact_check` включён |
| `flags.image_generation_module_enabled` | True | |
| `flags.checkup_enabled` | True | |
| `flags.direct_chat_botword_enabled` | True | |
| `flags.summary_enabled` (global) | True | в обоих owner-чатах override **False** (observer/память ведут себя как настроено) |
| env-оси инструментов | все `<unset>` | `MCA_VISION_ENABLED/ MCA_VISION_TOOL_ENABLED/ MCA_TEMPORAL_FACTCHECK_*/ NATIVE_MEDIA_TOOLS_ENABLED/ UNIFIED_IMAGE_REQUEST_ENABLED/ DIRECT_L1_ENABLED/ AGENTIC_EVENTS_ENABLED` и др. → Settings-дефолты (ON) |

Вывод: effective-набор инструментов на проде — полный канон 14 (гейты ON), при этом **исполнение
Vision реально заблокировано состоянием capability** (см. §4), а свободная маршрутизация L1 живая.

---

## 2. ADD-TR.2 — Direct-вход: caption, entities, reply, media_group

**Заявление «проверка использует `message.text`, а не `caption`» — ПОДТВЕРЖДАЮ (код + последствия).**

- `handlers/direct_chat.py:499-501`: `text = (message.text or "").strip(); if not text or text.startswith("/"): return UNHANDLED`.
  Для photo/document с подписью `message.text is None` → Direct **вообще не активируется**: ни
  «бот …», ни reply-ветка, ни caption_entities.
- `handlers/direct_chat.py:154` (`_has_bot_mention`): `text = message.text or ""` + `message.entities` —
  `caption_entities` не читаются. `:192-194` (@username regex) и `:206` (botword) — тоже только `text`.
- Единственный обработчик caption в файле — `direct_chat_edited_handler` (`:376`), и он только про
  **правки сообщений самого бота** (обновление `bot_replies`), не про вход.
- `services/direct_chat_service.py:2013`: `query = (message.text or "").strip()` — сервисный слой тоже
  текст-only.
- Caption **читают** другие роутеры: канонический фактчек (`handlers/factcheck.py:310`, включая
  display `text or caption`), checkup («чекап», `handlers/checkup.py:99`), search/youtube/web (у своих
  триггеров), summary-observer (сохраняет `caption`, `handlers/summary.py:335,426`). Т.е. «канонические
  триггеры в подписях к медиа» для `фактчек`/`чекап` работают, а для Direct/«нарисуй» — нет.
- Порядок роутеров (`bot.py:875-999`): 0a observer → 0b /summary → **0c factcheck → 0d search →
  0e youtube → 0f web → 0g checkup → 0h direct_chat → 0i voice_transcription** → admin/menu → … →
  6 vasya (last). Observer всегда `UNHANDLED` (`handlers/summary.py:482`), т.е. каждый роутер видит
  сообщение; photo+caption «бот, что на картинке?» ни одним из них не консьюмится → **ответа нет**.

**Reply/forward/медиа-маркеры (что уже есть):**

- `services/media_marker.py:104-136`: `message_media_type` — фото/док/видео/… (но только когда
  `message.text is None`); `:139-144` env-гейт `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` (ON).
- `services/direct_chat_service.py:6241-6281` (`_render_current_question`): к тексту текущего сообщения и
  **к reply-цели** добавляются маркеры `[медиа: photo tg:<id>]` — путь «текстовый reply на фото»
  доносит цель до L1. Прод-подтверждение: план 18.10 14:31:00Z `capabilities=image_understanding,
  execution_mode=simple_tools` (это и есть reply-на-фото кейс), после чего модель вызвала `recognize_image`.
- `services/direct_chat_service.py:2947-2960`: `ToolContext` получает `reply_to_message_id=message.message_id`
  (текущее сообщение), `resolved_url`, `native_media` (**только reply-видео** — `native_media.resolve_reply_video`).
- Forward: `_forward_source_of(message)` используется как veto для image-поручений (`:6618-6620`) и в
  детекторе (`forwarded=True`); факт-чека репост-вариант имеет свой путь (`factcheck.py:315-316`).

**Media group / альбомы:**

- `services/media_group_buffer.py:49-103`: буфер caption альбомов (caption приходит только с 1-го
  элемента), заполняется summary-observer'ом (`handlers/summary.py:345`), **читается только**
  `handlers/factcheck.py` (`:333`). Direct-цепочка буфер не использует; для «альбом → что на фото»
  склейки нет.
- Не-image document: политика MCA-19 — `mca_vision.extract_image_assets` (регистрация активов);
  «любой документ = картинка» не заявляется (см. VISION-RECON §5, `handlers/summary.py:464-479`).

**Итог по ADD-TR.2:** GAP ровно на входном слое Direct (caption/caption_entities + единый media-контекст
сообщения). Всё, что ниже (reply-маркеры, L1→recognize_image, veto-детектор), уже существует.

---

## 3. ADD-TR.3 — инвентарь инструментов: что рекламируется и что реально исполняется

**Реестр и гейты (код):**

- Канон 14 имён: `services/tool_schemas.py:679-694` (`TOOL_CALLING_TOOLS`), схемы
  `recognize_image` `:563-611`, `fact_check` `:617-674`, `generate_image` — две редакции
  (legacy `:402-421` / v21 `:423-456`, киль-свитч `UNIFIED_IMAGE_REQUEST_ENABLED`),
  `get_bot_health` `:317-327`.
- `active_tools()` (`:792-832`): фильтр по env-гейтам — `lore_compiler`, `image_generation`
  (аргумент), `MEDIA_TRANSCRIBE_TOOL_ENABLED`, `ARTICLE_TOOL_ENABLED`, `MEMORY_LOOKUP_ENABLED`,
  `MCA_VISION_TOOL_ENABLED` (`:741-752`), `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED` + `temporal.tool_enabled`
  + `flags.factcheck_enabled` (`:755-789`). На проде все ON ⇒ набор полный 14.
- Диспетчер: `services/tool_router.py:681-712`; исполнители `_recognize_image` `:2270-2327`,
  `_fact_check` `:2331-2437`, `_get_bot_health` `:2673-2697`, `_generate_image` `:2899-3035`.

**Два пути исполнения (важно):**

1. **L1-путь (живой на проде)**: Capability→tools allowlist `services/direct_capabilities.py:28-43`;
   анонсируется только resolved-подсет `active_tools` (`services/direct_chat_service.py:4147-4190`),
   планировщик видит «ДОСТУПНЫЕ ВОЗМОЖНОСТИ» = `available_capabilities(announced)` (`:3935`,
   `direct_l1.py:578-620`), исполнение — `_l1_tool_phase` (`:4192+`).
2. **Legacy-путь** (L1 OFF): полный `active_tools` прямо в `chat_with_tools`
   (`services/direct_chat_service.py:3094-3143`), плюс детерминированный план для «2+ URL + сравнение»
   (`response_extent.build_tool_plan:728-793`).
3. **Fast-Track пре-гейты** (до LLM): image-ключевик «нарисуй» (`_image_pre_gate_block:6594-6651`,
   семантическая дверь §5.10 `_l1_capability_consistency:6529-6543`), ностальгия-dig (`:6290+`).

**«Пять независимых фактов» по четырём инструментам — прод-факты (SSH 19.10, journal с 13.10, `mca_events`):**

| Инструмент | зарегистрирован | показан LLM | модель вызвала | исполнитель вернул данные | конечная доставка |
|---|---|---|---|---|---|
| `recognize_image` | да | да (L1-подсет; plan_meta `image_understanding` 18.10 14:31Z) | **14** вызовов (14–18.10) | **0**: все `denied` — до 15.10 `vision_disabled`, с 15.10 `vision_unavailable` (последний 18.10 14:31:00Z) | — |
| `fact_check` | да | да (capability `fact_check`) | **6** вызовов | **3 `TOOL_CALL_COMPLETE status=ok`** (14–16.10, out_chars 1912–2277) | writer/цикл; доставка в TG отдельно не логируется |
| `generate_image` | да | да (capability; 1× `L1_CAPABILITY_REJECTED image_generation tool_not_active` за 7д) | модель — **0** `TOOL_CALL` | сервисный Fast-Track работает: `[image] generated/sent` 17–18.10, `image/image` usage 101/7д, `worker_budget image_calls` 12+4 (18.10) | да (`[image] sent … delivery_failed=False`) |
| `get_bot_health` | да | **только в legacy**; в L1-подсети недостижим (нет capability) | **0** вызовов за всю доступную историю | — | канонический «чекап» идёт мимо tool: handler 0g, `bot.py:901` |

Дополнительно из `mca_events` (7д): `factcheck_temporal success` ×54 (последний 16.10 10:02Z),
`factcheck_run success` ×1 (17.10 16:14Z) — модуль Фактчека жив; `vision_media skipped
vision_unavailable` ×23 + `capability_check_pending` ×14, `vision_capability_probe failed` ×4 —
Vision-конвейер стоит (route-дефект D1/D2, активный лейн VISION-FIX-CORE).
`L1_CAPABILITY_REJECTED` (7д): `statistics no_tool` ×3, `summarization unknown_capability` ×1,
`image_generation tool_not_active` ×1, `chat_memory/chat_history low_confidence` ×1.
Ошибки других tool-раутов (не блокеры ADD-TR): `download_media error` ×1, `summarize_video error` ×2,
`get_recent_history timeout` ×1, `dig_into_lore denied tool_step_limit` ×1.

**Ключевой вывод по `get_bot_health`:** в `direct_capabilities.CAPABILITY_TOOLS` (`:28-43`) нет
capability для health/checkup (есть только web/fetch/history/memory/user_memory/historical/fact_check/
image_understanding/media_download/transcription/video_summary/image_generation/statistics). В живом
L1-пути планировщик не может запросить этот инструмент, `_l1_tool_subset` вернёт пустой список ⇒
свободное «проверь состояние сервера» до инструмента не доходит (L1 видит только capability-словарь из
контекста). В legacy-пути инструмент анонсируется, но прод-вызовов нет. Это **GAP** относительно
ADD-TR.3 п.4 (за свободную формулировку), при работающих канонических триггерах.

**Сверка с соседними контурами:** MCA-19 (`recognize_image`) — существует, ждёт фикс маршрута
(VISION-FIX-CORE, карта `p0-vision-universal` = PENDING); MCA-20 (`fact_check`) — работает;
CFG-06 — модуль существует, строки CFG-06 в `plans/features/cfg/requirements-map.json` = PENDING
(live-статус у лейна CFG); Fast-Track генерации — работает (см. таблицу).

---

## 4. ADD-TR.4 — пост-генерация: откуда берётся текст и где пиксели

- **Pre-gate путь**: после фактической отправки в контекст Writer-а инжектится блок
  `'<image_result status="ok" delivery="sent">…'` («Изображение уже сгенерировано и отправлено в чат.
  Повторно инструмент generate_image не вызывай.») — `services/image_generation.py`
  (committed `:1894-1900`; worktree `:2096-2100`), плюс `<dig_result>`/`<image_result>` в
  `direct_chat_service.py:2282-2287`.
- **Tool-путь**: модель получает JSON `{"status":"success","message":"Изображение сгенерировано и
  отправлено в чат"}` — `services/tool_router.py:2984-2998` (committed идентично; CFG-02B правит
  только хвост отказов `:2959-3020`).
- Итоговый текст пользователю пишет **L2 Writer** (тот же турн) — **без bitmap**: ни байты, ни анализ
  готовой картинки в контекст не попадают ⇒ любые фразы «получилось X, Y» — непроверенные (дефект
  ADD-TR.4 подтверждён структурно; live-случай «описал не то» не ловил).
- **Доступ к bytes для MCA-19**: байты финального файла есть в коде — `GenerationResult.content: bytes|None`
  (`image_generation.py:151-168`, committed `:151+`). Вход анализатора MCA-19 —
  `DownloadedImage(data/mime/declared_mime/width/height/byte_size, sniff_image)` и
  `analyze_image_bytes(image: DownloadedImage, *)` (`services/mca_vision.py`, worktree `:1063-1076`,
  `:1415`; committed то же семейство). Единственный вызывающий `analyze_image_bytes` — `process_asset_job`
  (тот же файл), **адаптера «исходящий файл → анализ» нет**.
- Почему сам собой не появится: observer пропускает сообщения бота (`handlers/summary.py:333-334`
  `user.id == _bot_id → UNHANDLED`), поэтому отправленная ботом картинка **не регистрируется** как
  asset MCA-19 и не попадает в очередь анализа.
- **Дедуп (уже есть, переиспользовать):** маркер прогона `ToolContext.image_request_handled`
  (`tool_router.py:609-613, 2918-2927`), replay-статус `"already"` с честным текстом
  (`image_generation.py:2087-2095`), единый `ImageRequest` («один send на ход»), coalesce задач MCA-19.
- Минимальная работа: небольшой доверенный адаптер `GenerationResult.content → sniff_image →
  DownloadedImage → analyze_image_bytes` в **существующем** контуре (гейт: Vision ON и capable),
  bounded-ожидание, и передача результата Writer-у; не второй vision-пайплайн.

---

## 5. ADD-TR.1 — регрессия сетки «Речь и характер» (ВОСПРОИЗВЕДЕНО)

**Способ:** committed-байты `3b02366e` (web) отдавались локальным стендом; Playwright-замеры DOMRect
в витрине `#/ai/speech`; скриншоты и JSON — `evidence/render/` (скрипт `addtr_speech_probe.py`,
замеры `measure.json`). Никаких изменений репозитория для замеров не требовалось.

**Замеры (витрина, 10 карточек):**

| viewport | колонок (computed) | карточка, px | `.speech-card-body`, px | переполнение заголовка (scrollWidth−clientWidth) |
|---|---|---|---|---|
| 320×640 | 1 (`280px`) | 280 | 154–172 | 0 |
| **360×740** | **2 (`156px 156px`)** | 156 | **30–66** (у «Характер» — 30) | **15–48px** (core 29, expression 27, capabilities 48) |
| **390×844** | **2 (`171px`)** | 171 | 45–81 | 2–33px |
| 430×932 | 2 (`191px`) | 191 | 65–83 | 0–13px |
| 844×390 (landscape) | 3 | 257 | 132–150 | 0 |
| 768×1024 | 3 | — | — | 0 |

- Горизонтального скролла нет (overflow=0) — дефект именно «узкие колонки + тесный body», не overflow.
- Ink-замер заголовка «Характер» на 360px: `Range.getClientRects()` правый край = 116px, badge начинается
  с x=95 ⇒ **ink заходит в badge на 21px** (на 390px — на 6px). На скриншоте `speech_360.png` это видно
  глазами: «Характер» наезжает на badge «изменено», подзаголовок бьётся на «Посто/янны/й…».

**Первопричина (CSS, `web/static/app.css` — файл у лейнов не занят):**

1. `app.css:4486-4497`: `@media (min-width:360px) and (max-width:599px) { .speech-grid, .speech-grid-tight
   { grid-template-columns: repeat(2, minmax(0,1fr)); } }` — «ровно 2 колонки» навязано по **viewport**,
   независимо от фактической ширины контейнера (решение P0A-UX §4-C1, `ux-plan.md:231,501`).
2. `app.css:4309,4320-4336`: базовая сетка `auto-fill minmax(min(220px,100%),1fr)`; карточка —
   flex-строка: иконка `flex:none` (`.speech-card-icon:4333`), body `flex:1 min-width:0` (`:4334`),
   badge `.badge` (`app.css:704-710`, `inline-block`, min-content ≈60-70px). На карточке 156px:
   156 − 20 (padding) − 18 (иконка) − 70 (badge) − 2×8 (gap) ≈ **30px** на body.
3. `.speech-card-title` (`:4335`) — без `overflow-wrap`/`min-width`; при body 30px слово «Характер»
   (≈59px) выходит за бокс в зону badge. `.speech-card-sub/:4336` и `-detail/:4337-4345` имеют
   `overflow-wrap:anywhere` → переносы по 2–5 букв («фрагменты» владельца).
4. Высоты: `min-height:64px` у карточки при обрезанном `-webkit-line-clamp:2` detail — отсюда
   «пустоты/обрезки» на части карточек.

**Ограничения замера:** реальный Android Telegram не проверялся (честно: PENDING_OWNER_E2E после
фикса); крупный системный шрифт/zoom не эмулировался; full-screen MiniApp-режим отдельно не мерился.

**Риск для фикса:** `tests/ui_p0a_ux_speech_compact_e2e.py` **закрепляет текущее поведение**
(320 → 1 колонка, 360–412 → **ровно 2**, `:1132-1135, 583-586`). Правка сетки обязана обновить этот
тест, иначе получим «зелёный тест против контракта владельца».

---

## 6. Итоговая таблица статусов ADD-TR

Формат: сценарий → статус → главное доказательство → минимальная работа.

| # | Сценарий | Статус | Доказательство | Минимальная работа |
|---|---|---|---|---|
| 1 | ADD-TR.1 сетка «Речь и характер» на узком экране | **REGRESSION** (воспроизведено на прод-байтах) | §5: 360px → 2×156px, body 30px, ink в badge +21px; `app.css:4486-4497,4309-4345`; `speech_360.png` | CSS-фикс причины + правка e2e-ожиданий + Playwright-матрица; реальное устройство — PENDING_OWNER_E2E |
| 2 | Direct: текстовые триггеры (`бот…`, @username, reply, команды) | **REUSE_VERIFIED** | `handlers/direct_chat.py:168-214,492-520`; порядок роутеров `bot.py:875-999` | — |
| 3 | Direct: caption / caption_entities / подписи к медиа | **GAP** | `direct_chat.py:499-500` (text-only), `:154` (entities только текста); фактчек/чекап caption читают (`factcheck.py:310`, `checkup.py:99`), Direct — нет | Расширить входной слой Direct (caption + caption_entities + не терять UNHANDLED-семантику) |
| 4 | Direct: reply-на-фото (текстовый) | **REUSE_VERIFIED до исполнителя** | медиа-маркеры `direct_chat_service.py:6241-6281`, `media_marker.py:104-136`; прод plan_meta `image_understanding` (18.10 14:31Z) | — (исполнитель — см. #7) |
| 5 | Direct: media_group / альбомы | **GAP** (direct) / REUSE (фактчек) | `media_group_buffer.py:49-103` — буфер заполняет observer, читает только фактчек | При склейке media-контекста Direct учесть буфер/альбом при необходимости |
| 6 | Direct: forward/чужое поручение/«я сам» | **REUSE_VERIFIED** | `direct_capabilities.py:387-412` (forwarded/reported/self/negated/conceive); veto в `direct_chat_service.py:6614-6620` | — |
| 7 | Vision `recognize_image`: сквозное исполнение | **BLOCKED** (route-дефект, активный лейн VISION-FIX-CORE) | прод: 14 вызовов, 0 данных; последний 18.10 14:31Z `vision_unavailable`; `vision_media`×23 skipped | Ждать VISION-FIX-CORE + деплой; затем live-проверка из L1-пути |
| 8 | Factcheck `fact_check`: сквозное исполнение | **REUSE_VERIFIED** | прод: 3× `TOOL_CALL_COMPLETE ok` (14–16.10); `factcheck_temporal` ×54; `tool_router.py:2331+` | — (свободная формулировка «это правда?» живьём в логах не поймана — оставить в live-матрице) |
| 9 | Генерация `generate_image`: «нарисуй» + свободные формы, один workflow | **ЧАСТИЧНО REUSE_VERIFIED**: Fast-Track подтверждён прод-логом; tool-вызов моделью 0; семантическая дверь §5.10 есть в коде, live-кейс «надо нарисовать» не пойман | `[image] generated/sent` 17–18.10; `image_calls` 12+4; `_l1_capability_consistency:6529-6543`; `_image_pre_gate_block:6594-6651` | Живой кейс дописать в live-матрицу (после фиксов), код-дверь не переделывать |
| 10 | Chekap `get_bot_health` по свободной формулировке | **GAP** (в живом L1-пути) | `direct_capabilities.py:28-43` (нет health), `_l1_tool_subset:4147-4190`, прод `TOOL_CALL get_bot_health` = 0; канон «чекап» — `handlers/checkup.py`, `tool_router.py:2673-2697` | Решить: добавить capability-имя health ИЛИ явный маршрут свободной формы на существующий tool; код исполнителя уже есть |
| 11 | Аудит остального inventory (схемы/гейты/исполнители) | **REUSE_VERIFIED с наблюдениями** | §3; прод-ошибки `download_media`/`summarize_video`/`get_recent_history` — отдельные (не ADD-TR) | Не расширять scope; ошибки зафиксированы |
| 12 | ADD-TR.4 пост-описание «как будто видел bitmap» | **GAP** | §4: Writer получает только статус; `analyze_image_bytes` без адаптера; observer скипает бота (`summary.py:333-334`) | Доверенный адаптер `GenerationResult.content → DownloadedImage → analyze_image_bytes` + гейт Vision ON; Writer — результат анализа |
| 13 | ADD-TR.4 дедуп генерации/описаний | **REUSE_VERIFIED** | `image_request_handled` (`tool_router.py:609-613,2918-2927`); `already`-replay (`image_generation.py:2087-2095`); единый ImageRequest | — |
| 14 | ADD-TR.0 §4 master↔прод, effective gates | **REUSE_VERIFIED** (0 runtime-диффов; см. §1 footnote про 13 porcelain-строк) | `git diff` пусто; прод HEAD 3b02366e; 30/30 sha на деплое | — |
| 15 | Медиа без обращения к боту — обычное поведение | **REUSE_VERIFIED** | Direct требует триггер (`direct_chat.py:502`); photo+caption ничего не консьюмит | Не ломать при расширении caption-входа (#3) |

Закрытые в других контурах пункты ADD-TR.5 (Android/Desktop клиент, деплой-приёмка) — вне этой разведки,
остаются owner/live-проверками.

---

## 7. Конфликты с активными лейнами (для планирования очереди)

| Участок | Кто занят сейчас | Замечание для ADD-TR |
|---|---|---|
| `web/app.js`, `web/index.html` | **CFG-02B** (worktree +187/+88 строк; хунки 3556/3723/3848 и 1322/1411/7692 — speech-шаблон НЕ тронут, проверено grep'ом диффа) | ADD-TR.1-фикс CSS — в `web/static/app.css` (**свободен**); если понадобится правка markup витрины — только после мерджа CFG-02B |
| `web/static/app.css` | свободен | кандидат №1 для ADD-TR.1 |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | принадлежит P0A-UX (закрепляет 2 колонки) | правка ожиданий — часть ADD-TR.1 |
| `services/mca_vision.py` (+`cover_style_jobs.py`, `capability_registry.py` и др. services) | **VISION-FIX-CORE** (активный лейн; 942 строки в `mca_vision.py` незакоммичено) | ADD-TR.4-адаптер — только после/поверх этого лейна; ADD-TR.3-#7 ждёт его |
| `services/tool_router.py`, `services/image_generation.py` | CFG-02B (хвосты `_generate_image`/`maybe_handle_keyword`) | якоря §3-§4 вне хунков; правки сериализовать |
| `handlers/direct_chat.py`, `services/direct_chat_service.py`, `services/direct_capabilities.py`, `services/tool_schemas.py` | **свободны** | основной участок ADD-TR.2/#10 |
| `web/*` в будущем | заявлено «VISION-UI» | ADD-TR.1 уложить до/вместе, чтобы не плодить двойных правок |

---

## 8. Что НЕ проверено живьём (честные ограничения)

- Реальный Android/Desktop Telegram (нативные клиенты), крупный шрифт/zoom, полноэкранный режим —
  только browser-эмуляция; после фикса — PENDING_OWNER_E2E.
- Свободные формулировки «надо нарисовать», «это правда?», «проверь состояние сервера» в проде —
  конкретных сообщений в журнале не найдено; код-пути зафиксированы, live-матрица — после фиксов.
- Прод-вызовы внешних провайдеров не выполнялись (никаких затрат/ключей).
- 13 porcelain-строк рабочего дерева прода не расшифрованы (один коннект, без повторов).
- `mca_events.capability_*` запрос упал на отсутствующей колонке `entity_id` (в прод. схеме иное имя) —
  данные о capability-трассах взяты из journal (`L1_CAPABILITY_REJECTED`) и `plan_meta`.

## 9. Артефакты разведки

- `evidence/recon/prod_recon_tr.py` — прод-скрипт (read-only, пароль не печатается).
- `evidence/recon/prod_recon-tr-2026-10-19.txt` — полный вывод единственного SSH-коннекта
  (git, env, bot_settings, overrides, usage, plan_meta, worker_budget, mca_events, task_jobs, журнал).
- `evidence/render/addtr_speech_probe.py` + `evidence/render/measure.json` — DOMRect-замеры на
  прод-байтах 3b02366e; `evidence/render/speech_{320,360,390,430,landscape}.png` — скриншоты.
- Замер-стенд: экспорт `git ls-tree/show 3b02366e:web/**` в scratch + harness
  `tests/ui_p0a_ux_speech_compact_e2e.py` (serve_static/api-стабы/SDK-стаб).
