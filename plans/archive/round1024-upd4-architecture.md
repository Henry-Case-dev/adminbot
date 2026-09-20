# Round 10.24 (UPD4 + UPD5) — сквозной архитектурный слой: нативное видео/медиа, YouTube-мультимодалка, устойчивость SQLite

> **Эпик:** раунд 10.24 «Disaster Recovery: UI & Backend Bloat», дополнение **UPD4** — 6 фич **F13–F18** (боевые баги, собранные вживую, кластеры **A–D**). **UPD5** уточняет решения владельца: (1) YouTube-порядок подтверждён; (2) cookies/POT/proxy на проде разрешены; (3) инструменты разделены по функциям — **выжимка** (`summarize_video`) и **транскрибация** (`transcribe_video`) → новая фича **F19 `media-transcribe-tool-round1024`**, канон R9 = **10**. Step 2 @Architect, сквозная карта UPD4 + UPD5.
> **Источники:** `plans/current_task.md` UPD4 (стр. 274–400) **+ UPD5 (стр. 403)** — **untracked, в git НЕ коммитить, секреты/креды/подписанные `/media/`-URL не цитировать (R17/R18)**; `plans/backlog.md` §«Раунд 10.24»; `spec.md`/`ADR` шести фич-папок; `plans/features/round1024-architecture.md` (часть 1/2 — базовые F1–F12).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`; pytest **7424/0**; SQLite `v12`; каталог **REGISTRY 457 / GROUPS 96 / `_TAB_BY_GROUP` 94**.
> **ADR UPD4:** **ADR-1024-14** (F13), **ADR-1024-15** (F14; **канон 9→10 + разделение выжимка/транскрипт**), **ADR-1024-16** (F15), **ADR-1024-17** (F16; **UPD5: порядок подтверждён, креды разрешены, raw-транскрипт курсивом**), **ADR-1024-18** (F17), **ADR-1024-19** (F18). **UPD5 №3:** **F19** — ожидаемый ADR-1024-20 (`transcribe_video`/команда «транскрипт»/канон 10).
> **Зона:** только backend/контекст/UX сообщений. UI/web (`web/**`) не трогается ни одной фичей UPD4. **Δ каталога = 0, Δ DDL = 0** по всем шести фичам.
> **⚠️ Дисклеймер по F15:** на момент составления карты в `plans/features/video-download-native-ux-round1024/` присутствовали `tasks.md`/`spec.md`/`ADR-1024-16.md`; контракт F15 ниже — из `spec.md` (T-2307…T-2312) и описания UPD4-A-3. До старта F15 артефакты подтвердить.

---

## 1. Что решаем (кластеры UPD4)

| Кластер | Симптом (прод) | Корень | Фичи |
|---|---|---|---|
| **A** — нативное видео + tool calling | «Бот что на видео» реплаем на TG-видео → бот «слеп»; «Бот скачай видос» реплаем → «че ты мне суешь?» и «⏳ Скачивание без выбора качества…» | контекст реплая text-only; `_extract_urls` собирает caption-URL реплая и перебивает живое видео; инструменты требуют обязательный `url`; probe-fail без причины | **F13, F14, F15** |
| **B** — YouTube+summary | «Бот че за видос `<youtube-url>`» → «автор видоса зажал субтитры, пересказывать нечего» | в OpenRouter уходит **URL страницы** (не файл) → L1/L2 структурно обречены → L3; age-restricted субтитры **PERMANENT** | **F16** |
| **C** — SQLite lock | `services.smart_cache \| smart cache: set failed \| OperationalError: database is locked` — запись кэша молча теряется | отдельное соединение кэша без WAL/`busy_timeout`/`synchronous` и без retry | **F17** |
| **D** — SQLite Row | `web.api.chat_lore \| AttributeError: 'sqlite3.Row' object has no attribute 'get'` — имена участников теряются (uid-fallback) | `r.get(...)` на `aiosqlite.Row` в `_participant_names`, проглочено широким `except` | **F18** |

Общий якорь UPD4: **«тихий откат для пользователя ≠ тишина в серверных логах»** (наследие F2/ADR-1024-1). Все фичи UPD4 либо показывают пользователю понятную причину, либо явно логируют реальную причину — но не молчат.

---

## 2. Обзор 6 фич UPD4

| # | Фича (папка) | Кластер | Слой | Prio | Флаг (env-only `ClassVar`, default ON) | Δ кат. | Δ DDL | ADR | Задачи |
|---|---|---|---|---|---|---|---|---|---|
| **F13** | `native-reply-media-context-round1024` | A‑1 | backend контекста (`thread_chain`/`chat_context`/`direct_chat`) | P1 | `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` | 0 | 0 | ADR-1024-14 | T-2291…T-2298 |
| **F14** | `native-media-tools-round1024` | A‑2 | tool-calling + Fast-Track (`tool_schemas`/`tool_router`/`video_download`) | P1 | `NATIVE_MEDIA_TOOLS_ENABLED` | 0 | 0 | ADR-1024-15 (**канон R9 9→10: `summarize_video` + `transcribe_video`**) | T-2299…T-2306 |
| **F15** | `video-download-native-ux-round1024` | A‑3 | UX сообщений (`handlers/video_download.py`, пулы фраз) | P2 | `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED` | 0 | 0 | ADR-1024-16 | T-2307…T-2312 |
| **F16** | `youtube-multimodal-download-fallback-round1024` | B | backend видео-пайплайн (роутер 0e) | **P0** | `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` (+ `_TIMEOUT_SECONDS`, `_CHAT_IDS`, **`YOUTUBE_CREDENTIALED_LEVEL_ENABLED`**) | 0 | 0 | ADR-1024-17 | T-2313…T-2321 |
| **F17** | `sqlite-lock-resilience-round1024` | C | backend/надёжность БД (`smart_cache.py`) | P1 | `SMART_CACHE_LOCK_RESILIENCE_ENABLED` | 0 | 0 | ADR-1024-18 | T-2322…T-2327 |
| **F18** | `sqlite-row-get-fix-round1024` | D | backend-багфикс web-API (`web/api/chat_lore.py`) | P2 | — (без флага) | 0 | 0 | ADR-1024-19 | T-2328…T-2331 |
| **F19** | `media-transcribe-tool-round1024` | A‑2/3 (**UPD5 №3**) | tool-calling + команды (`tool_schemas`/`tool_router`/`youtube`/`voice_transcription`) | P1 | `MEDIA_TRANSCRIBE_TOOL_ENABLED` | 0 | 0 | ADR-1024-20 (ожидаемый) | T-2343…T-2352 |

**Итог UPD4 + UPD5:** базовые задачи UPD4 — **T-2291…T-2331 (41, F13–F18)**; UPD5 добавляет **13 задач**: T-2333…T-2335 (F14, контракт/схемы) + T-2343…T-2352 (F19, 10). Новых каталоговых ключей/групп **нет**; схем БД **нет**; новых env-флагов — **7** (F13/F14/F15/F16/F17 + `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` F16 + `MEDIA_TRANSCRIBE_TOOL_ENABLED` F19), F16 дополнительно получает timeout + раскаточный allowlist. **UPD5:** канон инструментов **10** (F14 контракт → F19 финал), YouTube transcript = raw-курсив, креды разрешены (F16), Open Q №1–2 закрыты.

---

## 3. Маршрутизация видео/медиа (главный сквозной сюжет, кластер A + B)

Запросы вокруг «видео/медиа» входят в **четыре независимых входа**. Ключ к багам A — понять, в какой вход попадает запрос и почему контекст/инструмент не срабатывают.

### 3.1. Карта входов

```
Сообщение пользователя
│
├─ (0e) YouTube-триггеры / URL  ──► handlers/youtube.py::_classify_video_request
│     ├─ kind=youtube + mode=summary   ──► F16: A download → B media_share+L1/L2 → C субтитры (L3)
│     │        (запрос ВЫЖИМКИ: «че за видос»/«о чем видео»/«поясни за видос»)
│     ├─ kind=youtube + mode=transcript ─► СЫРОЙ ТРАНСКРИПТ КУРСИВОМ (субтитры; иначе download→STT) — формат байт-в-байт
│     ├─ kind=native (TG-видео)         ─► эталон: download→publish→L1/L2→STT (summary) / STT (transcript, курсив); F16 НЕ трогает summary-часть
│     └─ kind=direct_url/platform_url   ─► БЕЗ ИЗМЕНЕНИЙ (байт-в-байт)
│
├─ (4e) Fast-Track «скачай/загрузи/стяни» ──► handlers/video_download.py
│     ├─ F14: native-first (своё video/видео-document → медиа реплая) ──► _handle_native_media
│     │        даже если в text/caption есть http(s)-ссылка
│     └─ иначе: _extract_urls → URL-ветка (probe → меню качества → bounded fallback)
│              F15: UX — меню качества НЕ для нативного реплай-видео; понятная причина probe-fail
│              (F15 ≠ выжимка/транскрипт: только скачивание/пересылка файла)
│
├─ (4e-гейт OFF / нет триггера / нет URL) ──► direct_chat (LLM + tool-loop)
│     ├─ F13: медиа-маркер в thread_chain / chat_context / <Current_Question>
│     ├─ F13→F14: ToolContext.native_media (разрешённый aiogram-объект)
│     └─ F14: LLM выбирает инструмент по формулировке (канон R9 = 10):
│              • «что на видео»/«че за видос» → summarize_video (ВЫЖИМКА)
│              • «транскрипт»/«транскрибация» → transcribe_video (СЫРОЙ текст)
│              • «скачай» → download_media
│              (url опционален + source="reply"; active_tools/factcheck_tools не меняются)
│
└─ прочее (текст/фото и т.п.) ──► без изменений
```

### 3.2. Почему «Бот что на видео» реплаем на видео уходит в `direct_chat`

Фраза не входит в YouTube-триггеры (`services/command_registry.py:25`), нативного пути по URL нет → запрос идёт в `direct_chat`. До F13 контекст реплая **text-only**: узел с пустым текстом отбрасывался во всех трёх рендерах (`thread_chain.py:131-146`, `chat_context.py:107-110`, `_render_current_question` — только `message.text`). LLM не видит медиа и не может вызвать инструмент. **F13** доставляет факт медиа + внутренний реф в контекст; **F14** даёт инструментам нативный путь.

### 3.3. Почему «Бот скачай видос» реплаем ломался

Это **Fast-Track** (4e, позиция роутера не меняется). `_extract_urls` собирает ссылки и из своего сообщения, **и из реплая** (`video_download.py:144-161`), поэтому caption-URL нативного видео уводил запрос в URL-ветку (probe → общая фраза). **F14** вводит **native-first**: живое видео в своём сообщении/реплае побеждает caption-URL. **F15** — пользовательский UX поверх: меню качества неприменимо к реплай-видео, probe-fail объясняется причиной, конфликт «видео+ссылка» предсказуем.

### 3.4. YouTube URL + summary (F16, P0)

Для `kind=youtube + mode=summary` вводится строгий порядок **A) скачать → B) опубликовать → мультимодалка L1/L2 по файлу → C) при провале — субтитровый L3** (порядок **подтверждён владельцем, UPD5**). Причина бага: `summarize_cascade` фабриковала `watch?v=`-URL и отдавала его как `video_url` — мультимодалка получала HTML, а не видео. F16 переиспользует проверенный нативный путь `_publish_and_cascade`; `summarize_cascade` становится **L3-only** субтитровым фолбэком. Age-restricted выделяется в отдельную понятную причину (`reason="age_restricted"` → `YOUTUBE_AGE_RESTRICTED_PHRASES`). **UPD5:** cookies/POT-provider/resident-proxy на проде **разрешены** → опциональный credentialed-уровень (`YOUTUBE_CREDENTIALED_LEVEL_ENABLED`, значения только `.env`, R17-safe presence-логи) делает age-restricted достижимым.

### 3.5. Разделение «выжимка vs транскрипт» (UPD5)

Функции разведены на обоих уровнях:

- **Командный путь 0e:** `mode=summary` → выжимка (§3.4); `mode=transcript` → **голый сырой транскрипт курсивом** (`_send_transcript_reply`, HTML `<i>`, тот же стиль, что у ГС/кружков), без саммаризации. Триггеры — `services/command_registry.py` (группа `youtube`: `транскрипт` / `че за видос` / `о чем видео` / `поясни за видос`; `mode` определяется подстрокой «транскрипт» в `_request_mode`).
- **Tool-путь (direct_chat):** два инструмента — `summarize_video` (выжимка; `mode` удалён) и `transcribe_video` (сырой текст; новый, 10-й). LLM выбирает по EN-`description`; `tool_choice` не форсируется.
- **ГС/кружок:** триггер `транскрипт` также принудительно повторяет транскрибацию (видео/кружок — 0e; ГС — слой `voice_transcription`). Контракт триггера общий.

Оба уровня не смешивают функции: выжимка не отдаёт сырой текст, транскрипт не пересказывает.

**Границы неизменности F16 (байт-в-байт):** формат `mode=transcript` (сырой транскрипт курсивом), native/direct/platform, «скачай» 4e, `_parse`/D126, cache-key, `on_retry`, 🗿-молчание, пулы 5.5/5.6/5.8, кулдаун, порядок роутеров `bot.py`, `parse_mode=None` plain-каналов (кроме локального HTML-курсива transcript).

---

## 4. Стыки и общие контракты

### 4.1. Медиа-маркер контекста (владелец — **F13**, `services/media_marker.py`)

Единый диалект маркера — единственный источник, который импортирует и F14:

```
[медиа: {media_type}]              # реф неизвестен (R16 — опускаем)
[медиа: {media_type} tg:{id}]      # внутренний реф: Telegram id медиа-узла
[медиа: {media_type} msg:{id}]     # внутренний реф: внутренний id строки (нет tg)
```

Regex для потребителя: `^\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\d+))?\]$`.
Публичный URL / `file_id` / токены в контекст **не** попадают (R17). Неизвестный/битый `media_type` санитизируется (`[a-z_]`, ≤20 → `other`). Словарь токенов совпадает с `_detect_media_type` (`handlers/summary.py:125-143`).

### 4.2. Стык F13 → F14: `ToolContext.native_media`

- **F14** определяет новый модуль `services/native_media.py` (`NativeMedia{source, media, kind}`, `document_is_video`, `resolve_reply_video`, `media_suffix`, `download_to_tmp`) и аддитивные поля `ToolContext.native_media` / `ToolDeps.transcriber`.
- **F13** владеет файлами `thread_chain.py` / `chat_context.py` / `direct_chat_service.py` и отвечает за «связку» (T-2295): при сборке `ToolContext` кладётся `native_media = native_media_module.resolve_reply_video(message)`.
- **Координация порядка (важно):** строка эмиссии в `direct_chat_service.py` ссылается на модуль F14, которого на момент старта F13 ещё нет. Во избежание forward-import: **модуль `services/native_media.py` создаётся как первый артефакт F14**, а эмиссионная строка в `direct_chat_service.py` (F13-файл) вливается **после** появления модуля в рамках ступени F13 → F14. F14 тестируется юнит-инъекцией `ctx.native_media`, независимо от F13 (риск R6 снимается).
- F13 не трогает `tool_schemas.py`/`tool_router.py`/`handlers/**`; F14 не переписывает блоки F13.

### 4.3. Схемы инструментов (владелец — **F14**, `services/tool_schemas.py`)

- **`summarize_video` = выжимка** (`mode` удаляется), **`transcribe_video` = сырая транскрибация**
  (новый, 10-й) — два отдельных инструмента с чёткими EN-`description` (UPD5). Полные схемы —
  spec F14 §4.4; обоснование — ADR-1024-15 §2.3-bis.
- `summarize_video`/`transcribe_video`/`download_media`: `url` становится **необязательным**;
  добавляется `source: enum["link","reply"]`.
- Резолв: http(s)-`url` → ссылочный путь (байт-в-байт); пустой/внутренний-реф `url` при
  `ctx.native_media` → нативный путь; иначе — понятная строка ошибки.
- **Канон инструментов R9 = 10** (см. §5): порядок первых 9 — байт-в-байт, `transcribe_video` — в конец;
  комментарий-счётчик `tool_schemas.py:241` приводится к фактическому (было «7» — техдолг 10.23 **I2**).
  `active_tools`/`factcheck_tools` не трогаются (фактчекер — 3 инструмента).
- `dispatch` инструментов **никогда не бросает** — возвращает строку статуса; лимиты tool-loop
  (4 раунда / 2 вызова) и таймауты (`_DOWNLOAD_TOOL_TIMEOUT=180`, `_SUMMARIZE_TOOL_TIMEOUT=300`) не меняются.
- **Egress:** `transcribe_video` возвращает **строку** (как query-инструменты); новых send-точек нет.
  Доставка сырого транскрипта курсивом — командный путь 0e (`_send_transcript_reply`, уже allowlisted).

### 4.4. Пулы фраз (общие по смыслу, но разные файлы)

| Пул | Файл | Владелец | Смысл |
|---|---|---|---|
| `VD_PROBE_FAIL_PHRASES` (новый) | `tools/video_download_phrases.py` | **F14** (механизм) → **F15** (формулировки) | probe_timeout / probe_failed — отдельно от общей «че ты мне суешь?» |
| `YOUTUBE_AGE_RESTRICTED_PHRASES` (новый, append-only) | `services/smartmodule_phrases.py` | **F16** | «возрастной порог / субтитры закрыты» вместо ложной «битой ссылки» |

Требование **NFR-7: пулы не пересекаются**; финальные формулировки UX — F15 (T-2308), пул/маппинг — F14 (T-2303).

### 4.5. YouTube-сервис (владелец — **F16**)

- `YoutubeSummarizerService.summarize_cascade(...)` — **сигнатура сохраняется**, семантика становится **L3-only** (делегирует в `summarize(...)`, без попыток L1/L2 и без `video_client`); удаляется `_canonical_youtube_url`.
- `summarize_media_url` (L1→L2, `VideoLevelError` наружу), `summarize`/`summarize_transcript` — без регресса.
- `YouTubeTranscriptUnavailableException` получает `reason ∈ {age_restricted, transient, unavailable}` (позиционный `message` сохраняется).
- Композиция «скачать → опубликовать → L1/L2 → субтитры» живёт в хендлере `_process_youtube_summary`, переиспользуя `_publish_and_cascade`.
- **UPD5 (credentialed):** cookies/POT/resident-proxy разрешены — использует `build_ytdlp_base_opts()`/`_transcript_proxy_config()`, гейт `YOUTUBE_CREDENTIALED_LEVEL_ENABLED`; значения только `.env`, логируется presence (`set|empty`).
- **UPD5 (transcript):** `mode=transcript` отдаёт сырой транскрипт курсивом (`_send_transcript_reply`, HTML `<i>`); выжимка — отдельный путь (не смешиваются) — см. §3.5.

### 4.6. Устойчивость кэша (владелец — **F17**, `services/smart_cache.py`)

- PRAGMA-паритет с основным соединением: `journal_mode=WAL` → `busy_timeout=5000` → `synchronous=NORMAL` (локальные константы-зеркала).
- Bounded retry **только** на `OperationalError … locked`: `_LOCK_RETRIES=3`, backoff `0.1/0.2/0.4с` (≤0.7с поверх `busy_timeout`); перед повтором — best-effort `rollback`; повторяется вся транзакция.
- При исчерпании — явный структурный WARNING `event=smart_cache_lock_exhausted` + in-process счётчик; fail-open сохраняется как последний рубеж. Успешный путь и INFO-логи `hit/miss/expired/set` — без изменений.

### 4.7. Канон доступа к строкам курсора (владелец — **F18**, ADR-1024-19)

- **Правило:** строка курсора → `row_get(row, key)` **или** предварительный `dict(row)`; прямой `row.get(...)` на `aiosqlite.Row` **запрещён**.
- `_participant_names` (`web/api/chat_lore.py:666-682`) переводится на `row_get`; широкий `except Exception` сохраняется как fail-open, но не должен срабатывать. API relations — без изменений (R16).
- Превентивный аудит `.get` по `web/api/**` и `services/**` (T-2330): безопасны только `dict`-нормализация, asyncpg `Record` (у него `.get` есть) и `row_get`/subscript. **F4** (`dossier-live-feed`) обязан соблюсти тот же канон в своём модуле.

---

## 5. AMEND / RE-OPEN карта UPD4

| Решение | Действие | Инициатор | Причина |
|---|---|---|---|
| **ADR-1020-4 R9** (канон инструментов = 8) | **AMEND → 10 инструментов** | **F14** / ADR-1024-15 §2.1 | 9-й — `generate_image` (ADR-1023-5 §D2); **10-й — `transcribe_video`** (UPD5); закрывается рассинхрон комментария `tool_schemas.py:241` (техдолг 10.23 **I2**). Порядок первых 9/имена — без изменений. |
| **ADR-1015-3** (контракт `summarize_video` с `mode`) | **AMEND** | **F14** / ADR-1024-15 §2.3-bis | `mode` удалён; функции разведены в `summarize_video` (выжимка) + `transcribe_video` (сырой текст) — UPD5. `tool_response`/dispatch-контракт сохраняется. |
| **ADR-1016-1 §2** (контракт скачивания, URL-ветка) | **AMEND** | **F14** / ADR-1024-15 §2.2 | Приоритет нативного медиа над caption-URL; квалификация своего document через `document_is_video`. |
| **ADR-1016-1 §2.4** (probe-fallback/фразы) | **AMEND** | **F14** §2.4 + **F15** | Отдельный пул `VD_PROBE_FAIL_PHRASES`; реальная причина не маскируется. |
| **ADR-1016-1 §2.5 / ADR-1017-2** (меню качества, pending) | **AMEND (UX-часть)** | **F15** / ADR-1024-16 | Меню качества **неприменимо** к нативному реплай-видео; поведение при «видео + caption-URL» объяснено. |
| **Архив `video-multimodal-pipeline-and-incidents/spec.md:37,52,241` + FR-B5:52** («YouTube-URL mode=summary — байт-в-байт») | **AMEND архивной границы** | **F16** / ADR-1024-17 | Осознанный пересмотр: добавляется «скачать → мультимодалка по файлу»; байт-в-байт сохраняется для всех немедиа/не-summary, `mode=transcript`, native/direct/platform. |
| **ADR-1023-1 / ADR-1023-2** (маркировка целевого сообщения; окно/граф фактчека — байт-в-байт) | **БЕЗ AMEND — регресс-инвариант** | **F13** | При отсутствии медиа вывод `thread_chain`/`chat_context`/`<Current_Question>` побайтово прежний; обязательный эталонный тест T-2296(b). |
| **ADR-1020-1** (канонический контракт метаданных) | Подтверждён | F13/F14 | Маркер и токены медиа не меняют канон строк. |
| **ADR-1015-3** (`tool_response`, модель не «печатает» файл) | **AMEND** (см. выше) | F14 | Ослабляется только `required` схем; `summarize_video`/`transcribe_video` разведены; dispatch-контракт прежний. |
| **`plans/ARCHITECTURE.md` §13/§15** | Обновление строки про `summarize_cascade` | **F16** (Step 7 @Architect) | Сигнатура та же, семантика — L3-only; YouTube+summary = download→file-мультимодалка→субтитры. |
| **F17 / F18** | Без AMEND | — | Поведенческие багфиксы; внешних канонов не меняют. |

---

## 6. Инварианты UPD4 (нарушать нельзя)

1. **Δ DDL = 0** — SQLite остаётся `v12`; новых таблиц/колонок/миграций нет (F13 читает существующий `smart_messages.media_type`, F17 не меняет `CREATE TABLE smart_cache`, F18 только читает).
2. **Δ каталога = 0** — все рубильники UPD4 — env-only `ClassVar` вне `param_catalog` (F18 — без флага). Счётчики `test_param_catalog` не меняются.
3. **Байт-в-байт при отсутствии нового сигнала** (ADR-1023-1/2): F13 — при отсутствии медиа; F14 — ссылочные ветки; F16 — формат transcript (сырой курсив), native/direct/platform; F17 — успешный hot-path кэша.
4. **`imported-history-immutable`** — `smart_messages`/FTS/vec/`import_checkpoints`/`imported_history_*.jsonl` не мутируются и не удаляются.
5. **`manual-overrides-immutable`** — не затрагивается.
6. **`physical-two-call-pipeline`** — System 2 не трогается; F16-ветка 0e и фоновые вызовы вне счётчика.
7. **egress-реестры** — `SEND_POINTS`/`SEND_ALLOWLIST` не расширяются: F16/F13/F14 используют существующие `_reply`/`send_chunked_reply`/`react_moai`/`send_media`/`_send_once`/`_send_transcript_reply`.
8. **`parse_mode=None`** plain-каналы — текстовая доставка не меняется; исключение — **локальный** `parse_mode="HTML"` на transcript-доставке (`<i>`-курсив, как у ГС), существовавший и сохраняемый; глобальный `parse_mode` не трогается.
9. **Порядок роутеров `bot.py`** не сдвигается — только DI-kwargs (`transcriber=…`) и внутренняя логика.
10. **`tma-menu-freeze`** — UI/меню/табы/`web/**` не трогаются.
11. **R16** — API/сигнатуры расширяются аддитивно (новые поля/атрибуты не ломают парсеры); **R17** — логи/спеки/отчёты без секретов, `file_id`, публичных/подписанных URL и без **значений** cookies/POT/proxy (только коды/классы/числа/presence `set|empty`); **R18** — `current_task.md` не коммитить, значения не цитировать.
12. **Fail-open** — кэш (F17) и relations-API (F18) не роняют вызывающий хендлер; инструменты (F14) не бросают; F13 fail-open при ошибке резолва медиа.
13. **Лимиты tool-loop** (4 раунда / 2 вызова) и таймауты инструментов — не меняются.
14. **media-политика** — `media/`, `.env` не трогаются; нативная пересылка работает с TG-объектом, без новой публикации.

---

## 7. Ступени общих файлов UPD4

Правило: общий файл вливается строго по ступеням; более поздняя фича читает результат предыдущей и не переписывает её блоки.

| Файл | Ступень | Что происходит |
|---|---|---|
| `services/thread_chain.py` | **F13** (эксклюзив) | маркер вместо скипа пустой медиа-строки |
| `services/chat_context.py` | **F13** (эксклюзив) | то же для окна контекста |
| `services/direct_chat_service.py` | **F13** (владение) → **F14** (аддитивная эмиссия) | F13 — `<Current_Question>` + маркеры; F14 — строка `ToolContext.native_media` (после появления `services/native_media.py`) |
| `services/media_marker.py` | **F13** (новый) | контракт маркера |
| `services/tool_schemas.py` | **F14 → F19** | F14: `url` необязателен + `source`; `mode` убран у `summarize_video`; контракт двух инструментов. F19: финальная схема `TRANSCRIBE_VIDEO` + счётчик **10** |
| `services/tool_router.py` | **F14 → F19** | F14: `ToolContext.native_media`, `ToolDeps.transcriber`, native-путь. F19: ветка `_transcribe_video` (raw) |
| `services/native_media.py` | **F14** (новый, первый артефакт) | единый резолвер/квалификатор медиа |
| `handlers/video_download.py` | **F14 → F15** | F14 — native-first, квалификация document, probe-пул; F15 — UX/формулировки/меню |
| `tools/video_download_phrases.py` | **F14 → F15** | F14 — `VD_PROBE_FAIL_PHRASES` (механизм); F15 — формулировки |
| `handlers/youtube.py` | **F14 → F16 → F19** | F14 делегирует `_document_is_video`/`_resolve_video_media`/`_video_suffix` в `services/native_media.py` (байт-в-байт); F16 строит пайплайн A→B→C; F19 сводит команду «транскрипт» (T-2347, курсив) поверх. Порядок: **F14 → F16 → F19**. |
| `handlers/voice_transcription.py` + `handlers/media_common.py` | **F19** (эксклюзив) | принудительный повтор транскрибации ГС/кружка по команде «транскрипт» (T-2346) |
| `services/youtube_summarizer_service.py` | **F16** (эксклюзив) | `summarize_cascade` → L3-only; удаление `_canonical_youtube_url` |
| `services/youtube_transcript_engine.py` | **F16** (эксклюзив) | атрибут `reason` |
| `services/media_share.py` | читается F14/F16 | без изменений |
| `services/smartmodule_phrases.py` | **F16** (append-only) | `YOUTUBE_AGE_RESTRICTED_PHRASES` |
| `services/smart_cache.py` | **F17** (эксклюзив) | PRAGMA + bounded retry + счётчик |
| `web/api/chat_lore.py` | **F18** (эксклюзив) | `row_get` в `_participant_names` |
| `config/settings.py` | **F13 → F14 → F15 → F16 → F17** (аддитивно) | каждый — свой блок env-only `ClassVar`; F18 — ничего. F16 — `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED/_TIMEOUT_SECONDS/_CHAT_IDS` + **`YOUTUBE_CREDENTIALED_LEVEL_ENABLED`** (UPD5) |
| `bot.py` | **F14** | DI-kwarg `transcriber=…`; порядок роутеров не сдвигается |
| `web/**` | — | **не трогается UPD4** |

**Вывод по конфликтам:** пересечения UPD4/UPD5 — `handlers/youtube.py` (**F14 → F16 → F19**) и `services/tool_schemas.py`/`services/tool_router.py` (**F14 → F19**). Разрешается порядком ступеней; остальные файлы строго эксклюзивны по фиче. `handlers/voice_transcription.py`/`handlers/media_common.py` — эксклюзив **F19**.

---

## 8. Порядок исполнения (волны)

| Волна | Состав | Обоснование |
|---|---|---|
| **A** — независимые мелкие | **F17 ∥ F18** | изолированные файлы (`smart_cache.py` / `web/api/chat_lore.py`), нет пересечений и зависимостей — можно начинать сразу. |
| **B** — нативное видео (последовательно) | **F13 → F14 → F15** | F13 отдаёт контракт маркера (T-2291) → F14 потребляет (модуль `native_media.py` + инструменты + native-first) → F15 UX-полировка поверх F14. Ступень `handlers/video_download.py`: F14 → F15. |
| **C** — YouTube (P0, самый рискованный) | **F16** | порядок и креды **подтверждены UPD5** (Open Q №1–2 закрыты); файлы (`handlers/youtube.py`, `youtube_summarizer_service.py`, `youtube_transcript_engine.py`) параллельны A/B, но `handlers/youtube.py` требует **после F14**. |
| **D** — разделение функций (UPD5 №3) | **F19** | **после F14 и F16**: F14 отдаёт контракт `tool_schemas`/`tool_router`, F16 — `handlers/youtube.py`; F19 вливает `transcribe_video`/команду «транскрипт»/канон 10 (ступени F14 → F19, F16 → F19). |

Волна B не зависит от A; Волна C не зависит от B по данным, но **зависит от порядка по `handlers/youtube.py`**; Волна D (F19) идёт строго после B и C (общие файлы).

---

## 9. Δ каталога / Δ DDL / конфиг-флаги

**Δ каталога = 0** (все шесть фич) и **Δ DDL = 0** (SQLite остаётся `v12`).

**Env-only `ClassVar` (default ON, вне `param_catalog`):**

| Фича | Флаг | Default | Смысл |
|---|---|---|---|
| F13 | `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` | True | kill-switch маркера медиа в контексте |
| F14 | `NATIVE_MEDIA_TOOLS_ENABLED` | True | kill-switch native-first + нативного tool-пути |
| F15 | `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED` | True | kill-switch UX (меню/формулировки) |
| F16 | `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` | True | master kill-switch A/B (OFF → сразу L3) |
| F16 | `YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS` | 240.0 | бюджет скачивания (clamp ≥ 30) |
| F16 | `YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS` | "" (все чаты) | CSV-allowlist для прогрессивной раскатки без редеплоя |
| F16 | **`YOUTUBE_CREDENTIALED_LEVEL_ENABLED`** | True | **UPD5:** разрешает cookies/POT/proxy для age-restricted; OFF → только публичное (значения — только `.env`) |
| F17 | `SMART_CACHE_LOCK_RESILIENCE_ENABLED` | True | kill-switch PRAGMA + retry |
| F19 | `MEDIA_TRANSCRIBE_TOOL_ENABLED` | True | **UPD5 №3:** kill-switch инструмента `transcribe_video` + команды «транскрипт» (OFF → прежнее авто-поведение) |

F18 — **без флага** (чистый behavior-fix, уже fail-open). **Разделение инструментов** (`summarize_video`/`transcribe_video`, канон 10) — безусловно (JSON-схемы не гейтятся runtime-флагом, как и 8→9 ранее).

**Progressive delivery:** «internal → 10% → 50% → 100%» **не требуется** ни одной фиче, кроме **F16 (P0)** — там раскатка доступна через `YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS` (на усмотрение владельца). Для остальных достаточно kill-switch + наблюдения логов.

**Наблюдаемость (Δ DDL = 0 — только логи + in-process счётчик):**
- F16: WARNING шагов A/B (класс исключения + safe-`reason`, без URL); причина L3 (`reason`) в логе; R17-маскирование `/media/`-URL; **presence** credentialed-ресурсов (`cookies|pot|proxy = set|empty`).
- F17: `event=smart_cache_lock_exhausted` + счётчик `smart_cache_lock_exhausted_total()`.
- F14: `error=<Class> reason=<code>` на probe-fail.
- F19: выбор инструмента (summary/transcribe), факт принудительного повтора ГС/кружка, канон-счётчик 10 (без URL/file_id).
- F18: исчезновение WARNING `[relations] имена участников недоступны … no attribute 'get'`.

---

## 10. Откат

| Фича | Мягкий откат | Полный откат | Замечание |
|---|---|---|---|
| F13 | `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED=false` | `git revert` | OFF → прежние скипы/рендер побайтово |
| F14 | `NATIVE_MEDIA_TOOLS_ENABLED=false` | `git revert` | OFF → urls-first + обязательный `url` |
| F15 | `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED=false` | `git revert` | OFF → прежние меню/фразы |
| F16 | `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED=false` | `git revert` | OFF → сразу субтитровый L3, **деградации нет**. ⚠️ Флаг **не** возвращает отправку URL страницы в OpenRouter — это безусловный багфикс; байт-в-байт-возврат только через `git revert` |
| F17 | `SMART_CACHE_LOCK_RESILIENCE_ENABLED=false` | `git revert` | OFF → нет PRAGMA/retry, прежний WARNING/no-op |
| F18 | — | `git revert` | флага нет; наблюдение логов после деплоя |
| F19 | `MEDIA_TRANSCRIBE_TOOL_ENABLED=false` | `git revert` | OFF → нет `transcribe_video`/команды «транскрипт»-повтора, прежнее авто-поведение (байт-в-байт) |

**Δ DDL = 0** во всех случаях → миграций/сидов/обратных миграций нет. `media/` и `.env` не трогаются (F16 использует **разрешённые UPD5** креды YouTube — только значения в `.env`, R17/R18; presence-лог `set|empty`).

---

## 11. Human Gate / открытые вопросы (UPD4 → UPD5)

**Закрыты владельцем (UPD5, стр. 403 `current_task.md`):**

1. ✅ **F16 (было Q №1), порядок:** «скачать → мультимодалка → фолбэк субтитры» **подтверждён**; субтитры первым уровнем не вводятся. Разблокирует Волну C.
2. ✅ **F16 (было Q №2), креды:** cookies / POT-provider / resident-proxy на проде **разрешены** → опциональный credentialed-уровень (`YOUTUBE_CREDENTIALED_LEVEL_ENABLED`; значения только `.env`, R17-safe presence).
3. ✅ **F13/F14 (было Q №3), функция:** «что на видео»/«че за видос» → **выжимка**; `транскрипт` → **сырая транскрибация** (курсив); в tool calling **два инструмента** `summarize_video`/`transcribe_video`. Меню качества для реплай-видео — неприменимо (F15).
4. ✅ **F14 (было Q №5), канон:** R9 = **10** (8 канон + `generate_image` + `transcribe_video`), комментарий `tool_schemas.py:241` правится. Решение: **все фичи делаем, нумерация не важна — важен результат** (UPD5).

**Ранее зафиксировано @Architect:** «видео + caption-URL» → медиа побеждает (Q №4); F18 — отдельная фича (Q №6, по умолчанию).

**Открыто (техническое, не блокирует):**

- **F16:** бюджет/таймаут скачивания (240с?); summary через tool-путь (follow-up); orphan-поток yt-dlp. Полный список — ADR-1024-17 §Open Questions.
- **Нумерация:** продолжаем F13+ в рамках 10.24 (18 фич) — UPD5 «нумерация не важна, важен результат».

**Технические решения @Architect (не требуют владельца):** формат медиа-маркера, PRAGMA/retry-константы F17, выбор `row_get` для F18, `reason`-атрибут исключения F16, EN-описания `summarize_video`/`transcribe_video`.

---

## 12. Кросс-фичевые риски-контроль

| Риск | Фичи | Митигация (сводно) |
|---|---|---|
| Регресс байт-эталонов ADR-1023-1/2 | F13 | эталонный тест T-2296(b) + флаг OFF |
| Forward-import `services/native_media` в F13 | F13/F14 | модуль F14 создаётся первым; эмиссия вливается после него (§4.2) |
| Конфликт одного файла `handlers/youtube.py` | F14/F16 | порядок ступеней F14 → F16 (§7) |
| Расхождение канона инструментов 9/10 | F14 | синхронная правка комментария + тест `len(TOOL_CALLING_TOOLS)==10`; ADR-1024-15 §2.1 |
| Ослабление `required` схем → вызов без `url` | F14 | понятная ошибка при отсутствии `ctx.native_media` + тесты (b)/(e) |
| LLM путает выжимку и транскрипт | F14/F19 | два инструмента с однозначными EN-`description` (ADR-1024-15 §2.3-bis) + тест (d2)/F19 (a) |
| Конфликт правок `tool_schemas.py`/`tool_router.py` | F14/F19 | ступень **F14 → F19** (§7); F14 не финализирует счётчик |
| Конфликт правок `handlers/youtube.py` | F14/F16/F19 | ступень **F14 → F16 → F19** (§7) |
| Рост цены/времени ветки YouTube | F16 | бюджет-таймаут, kill-switch, allowlist; порядок подтверждён (UPD5) |
| Утечка подписанных `/media/` URL / `file_id` / значений cookies-POT-proxy в логи | F13/F14/F16 | R17-маскирование (presence `set|empty`), caplog-тесты, egress-скан |
| «Тихая» потеря всё ещё возможна | F17/F18 | явные логи (`smart_cache_lock_exhausted`) + регресс-тест на реальном `sqlite3.Row` |
| Потеря имён участников при регрессе `.get` | F18 | канон `row_get` + аудит T-2330; F4 обязан соблюсти канон |
| Лишний оверхед hot-path кэша | F17 | retry ограничен (≤0.7с поверх 5с), PRAGMA — только при init |

---

## 13. Ссылки

- Спеки/ADR фич:
  - F13 — `plans/features/native-reply-media-context-round1024/{spec.md,ADR-1024-14.md,tasks.md}`
  - F14 — `plans/features/native-media-tools-round1024/{spec.md,ADR-1024-15.md,tasks.md}`
  - F15 — `plans/features/video-download-native-ux-round1024/{spec.md,ADR-1024-16.md,tasks.md}`
  - F16 — `plans/features/youtube-multimodal-download-fallback-round1024/{spec.md,ADR-1024-17.md,tasks.md}`
  - F17 — `plans/features/sqlite-lock-resilience-round1024/{spec.md,ADR-1024-18.md,tasks.md}`
  - F18 — `plans/features/sqlite-row-get-fix-round1024/{spec.md,ADR-1024-19.md,tasks.md}`
  - F19 — `plans/features/media-transcribe-tool-round1024/tasks.md` (**UPD5 №3; spec.md/ADR-1024-20 ожидаются — Step 2**) 
- Базовый раунд — `plans/features/round1024-architecture.md`; `plans/features/round1024-web-architecture.md`.
- ТЗ — `plans/current_task.md` UPD4 (стр. 274–400) **+ UPD5 (стр. 403)**, untracked, R17/R18.
- Backlog — `plans/backlog.md` §«Раунд 10.24» (фичи F13–F18, ступени, волны; **UPD4 Open Q №1–2 закрыты UPD5**).
- Архивные прецеденты — `plans/archive/target-message-marking-round1023/ADR-1023-1.md`, `plans/archive/factcheck-deep-context-round1023/ADR-1023-2.md`, `plans/archive/video-multimodal-pipeline-and-incidents/spec.md` (AMEND F16), `plans/archive/tool-download-quality-round1017/`, `plans/archive/download-fix-round1016/`.
- Глобальная архитектура — `plans/ARCHITECTURE.md` §13/§15 (обновление на Step 7 по F16).
