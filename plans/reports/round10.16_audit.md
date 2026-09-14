# Раунд 10.16 — F3 `audit-recent-epics-round1016`: полный аудит 10.13–10.15 + смоук-тесты

> **Исполнитель:** @Builder (Step 4, T-1643…T-1650). **Дата:** 14.09.2026.
> **Baseline:** HEAD `18a9aa1` + незакоммиченное рабочее дерево (F1 `download-fix`,
> F2 `guide-delivery` + эта F3). **Тип:** test/audit + точечные FIX по спеке.
> **Прод-код изменён ТОЛЬКО** по доказанным дефектам (spect §3/§5); каталог-Δ=0.

## 0. Валидатор (финальный прогон)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5931 passed**, 0 failed, 1 warning (`StarletteDeprecationWarning` — не наш код) | 0 |
| `node --check web/app.js` | `NODE_CHECK_OK` | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `git diff --check` | чисто (только штатные LF→CRLF-предупреждения) | 0 |
| `git status --porcelain media/ .env` | пусто | 0 |

База 10.15 = 5774; +F1/F2/F3-тесты + фиксы ревью-итер.1 → 5931. Новых смоук-файлов — **7** (T-1643…T-1649).

## 1. Ревизия эпиков 10.13–10.15 (подсистемы)

### 1.1. download / probe (`tools/video_downloader.py`, `services/tool_router.py`, `handlers/video_download.py`)
- Проверено: ветвление `download()` direct vs YouTube vs cobalt (ADR-1016-1 §2),
  `_normalize_quality` (None/auto/best/max/direct → auto, `1080p`→1080, мусор →
  `invalid_quality` без сети), reason-коды probe (`probe_timeout`/`probe_bot_check`/
  `probe_failed`), Fast-Track bounded fallback, честный `status:"error"` tool-сет
  без отправки файла, R17 (URL/тексты не логируются).
- Корнер-кейсы: platform URL («tiktok») через auto; direct `.mp4`; отключённый
  флаг; сбой downloader; общий кулдаун 4e (R10.15-9).
- Вердикт: **регрессий нет**; F1-фиксы (/`reason`-коды, fallback) подтверждены.

### 1.2. tool-loop (`services/tool_loop.py`, `tool_router.py`)
- Проверено: полный цикл LLM→tool_call→dispatch→tool_response→финал; фиктивный
  success скачивания (F8, `send_media` + `{"status":"success"}`); лимиты
  ≤2 вызовов/раунд (truncate + WARNING) и ≤4 раундов (`LLMBadResponseError`);
  fail-safe неизвестного/упавшего инструмента → `ОШИБКА …`, цикл жив;
  деградация провайдера (`LLMError` на 1-м раунде) → обычный ответ без tools.
- Вердикт: **корректен**; лимиты и fail-safe подтверждены смоуком.

### 1.3. guide (`config_cache.py`, `info_service.py`, `handlers/info.py`, `web/api/routes.py`)
- Проверено: versioned-идемпотентная миграция PREV→канон (в т.ч. whitespace/CRLF
  дрейф), unknown/ручной текст не затирается + WARNING + `canon_drift`, дрейф
  версии добивается, повтор — no-op; `/info` rich-доставка; `/edit_info` (админ)
  превью + **PG-only** `save_text` (файл-сид read-only), не-админ → отказ;
  `reset_canon` бэкапит `prev_html`; второй блок `content.intelligence_guide`.
- Вердикт: F2-доставка подтверждена; **дефектов нет**.

### 1.4. graph (`services/database.py::graph_snapshot`, `web/api/memory_agi.py`)
- Проверено: Degree Centrality (топ-50 сидов), раскрытие окрестности, отсечение
  сирот, cap после раскрытия (120/240), контракт `nodes/edges/truncated/limits`,
  chat-скоуп, исключение `origin='bot_direct_reply'`, отсутствие висячих рёбер
  (S10.13-14 фактически закрыт: `graph_snapshot` фильтрует ребра и сирот,
  тесты `test_webapp_round1015_graph.py`; дополнительно проверено смоуком).
- Вердикт: **корректен**.

### 1.5. sleep (`services/dream_worker.py`)
- Проверено: fallback порогов при «0 убеждений 3 дня» (2/Σ8) и базовые 3/Σ12,
  self-healing после синтеза, защита от одиночного факта, fail-safe детекта
  (ошибка БД → база), точный формат `[Sleep]`-пре-гейт-лога, видимость WARNING
  в лог-ринге.
- Вердикт: **корректен** (диагностика 10.15 работает).

### 1.6. nostalgia (`services/nostalgia_worker.py`, `nostalgia_prompts.py`)
- Проверено: окно ±10 дней по умолчанию (+hot override), инжект `Лор чата`/
  `Локальные мемы` (капы 600/10×120), пустые секции опускаются, fail-open
  нормализация ответа (`UNCHANGED`), PREV-слепок сохранён и отличается от
  ревампнутого канона (анти-«робот-архивариус»).
- Вердикт: **корректен** (ревамп 10.15 подтверждён).

### 1.7. persona (`services/bot_persona.py`, `handlers/direct_chat.py`, `command_prefix.py`)
- Проверено: resolve per-chat → global → empty (fail-open), traits-cap,
  `get_persona_health`, гейт имени в `command_prefix` (Имя задано → дефолтные
  бот-триггеры off), `build_persona_prompt_block` (traits-cap, enabled=false → '').
- Вердикт: **корректен**; R10.14-4 — WONTFIX (см. §3).

## 2. FIX-техдолг (spec §3/§5) — закрыто с регресс-тестами

| ID | Файл:строка (после фикса) | Суть фикса | Регресс-тест |
|---|---|---|---|
| **S10.13-6b** | `services/database.py:3761-3768` | `graph_stats.archived_beliefs` получил тот же NOT LIKE-фильтр F3-парадигм, что `beliefs`/`count_beliefs_by_status` — счётчики больше не расходятся | `test_smoke_round1016_fixes.py::TestArchivedBeliefsParadigmFilter` |
| **S10.13-13** | `services/database.py:130-147` + `:2031-2036`; `services/dream_worker.py:62,910-915`; `services/summary_memory.py:49,70-79` | единый `parse_belief_meta` (dict/JSON/None → dict, fail-open); `DatabaseService._parse_belief_meta`, `DreamWorker._belief_meta`, `_belief_base_weight` делегируют ему — рассинхрон парсеров исключён | `test_smoke_round1016_fixes.py::TestUnifiedBeliefMetaParser` |
| **R10.15-4** | `bot.py:745-761`; `handlers/video_download.py:126-134,230-249`; `handlers/direct_chat.py:36,112-127` | download-роутер 4e и сервис регистрируются **всегда** (порядок роутеров не меняется); горячий гейт `flags.download_enabled` перенесён в хендлер (OFF → `UNHANDLED`); `direct_chat` yield-ит только при флаге **И** доступном DI-сервисе (`download_available()`), иначе сообщение не теряется | `test_smoke_round1016_fixes.py::TestDownloadAlwaysRegistered` |
| **R10.15-10** | `services/command_prefix.py:61-99`; `handlers/youtube.py:224`; `handlers/web.py:99` | `split_prefix_anywhere(text, url_before)` — при повторном обращении выбирается первое вхождение, перед которым стоит валидная цель, иначе последнее; без `url_before` контракт прежний | `test_smoke_round1016_fixes.py::TestLinkFirstOccurrence` |
| **R10.15-11** | `handlers/youtube.py:175-186,219`; `handlers/web.py:99` | целью youtube считается только YouTube/direct-media/известная платформа (`_has_video_target`), а не любой http-URL; обычная речь с не-media ссылкой уходит в LLM; web уже фильтрует YouTube (D128) | `test_smoke_round1016_fixes.py::TestValidVideoTargetOnly` |

Диф прод-кода минимальный: `bot.py` — только снятие startup-гейта вокруг 4e
(позиция/порядок не тронуты); `handlers/*` — аддитивные гейты/хелперы.

## 3. WONTFIX (зафиксировано; обоснование)

| ID | Файл:строка | Вердикт | Обоснование |
|---|---|---|---|
| **S10.13-9** Timeline-лор = in-memory inject vs `chat_lore_history` | `web/api/memory_agi.py:596-604` | **WONTFIX + doc** | Инжект лора — осознанный источник Timeline: сброс рестартом допустим (Timeline и так перестраивается от живой памяти); переход на `chat_lore_history` меняет семантику «когда лор реально подмешался» на «когда запись лора обновлена». Поведенческого дефекта нет. |
| **S10.13-11** LIKE-маркер парадигм матчит 2 сериализации | `services/database.py` (NOT LIKE-маркеры) | **WONTFIX + doc** | Матч возможен только при ручной/бэкап-правке JSON вне `json.dumps` (`"type" : "paradigm"`); в проде не воспроизводится (все записи идут через `json.dumps`, `dream_worker` и миграции). Смена SQL на JSON-оператор рискованна (SQLite/PG-совместимость) при нулевой прод-выгоде. |
| **R10.14-4** `dynamic_traits` без `chat_id` | `web/api/routes.py` (GET persona) | **WONTFIX + doc** | Соответствует модели F4 «общий характер бота» (FIFO-ротация трейтов глобальная, I10.14-2); это UX-несогласованность подписи ленты в chat-scope, **не утечка** (трейты не секрет, провенанс `chat_id` есть). Менять модель — вне скоупа F3. |

## 4. Смоук-набор (7 файлов, in-process, без сети/секретов)

| Файл | Подсистема | Ключевое |
|---|---|---|
| `tests/test_smoke_round1016_download.py` | download/probe | реальный `VideoDownloader.probe` (yt-dlp mock) → качества/reason; `download_media` (реальный `ToolRouter`) YouTube/платформа/direct; Fast-Track fallback 4e; честный error |
| `tests/test_smoke_round1016_tool_loop.py` | tool-loop | полный цикл с фиктивным success скачивания; лимиты 4/2; fail-safe неизвестного инструмента; деградация провайдера |
| `tests/test_smoke_round1016_guide.py` | guide | прод-PG старый текст → миграция → канон; `/info`; `/edit_info` (админ/не админ, PG-only); `reset_canon` |
| `tests/test_smoke_round1016_graph.py` | graph | centrality/кластеры/сироты/cap; контракт API `nodes/edges/truncated/limits`; fail-open; chat-скоуп/R17 |
| `tests/test_smoke_round1016_sleep.py` | sleep | idle-fallback 2/Σ8, self-healing, fail-safe детекта, `[Sleep]` в лог-ринге |
| `tests/test_smoke_round1016_nostalgia_persona.py` | nostalgia+persona | окно ±10, инжект лора/мемов, PREV-канон, fail-open; resolve per-chat→global, traits-cap, health, scope имени |
| `tests/test_smoke_round1016_fixes.py` | регресс FIX | S10.13-6b/-13, R10.15-4/-10/-11 (см. §2) |

Смоуки детерминированы, используют `:memory:`-SQLite и моки yt-dlp/cobalt/LLM/PG;
сеть/прод не задействованы. Обновлены существующие тесты под R10.15-4
(прямые вызовы download-хендлера теперь требуют включённого master-флага):
`test_video_download.py` (autouse-фикстура), `test_download_round1016.py`
(`_gate(True)` в fallback-кейсах), `test_tool_calling_round1015.py`
(`_set_download_gate(True)` в Fast-Track), `test_command_registry_round1015.py`
(доступность сервиса в yield-кейсе).

## 5. Новые дефекты

- **Не выявлено.** Medium R10.15-1/-2/-3 закрыты в 10.15; S10.13-14 фактически
  закрыт `graph_snapshot` (фильтр висячих рёбер) и покрыт тестами. Отдельных T
  не требуется.

## 6. Инварианты раунда

| Инвариант | Статус | Доказательство |
|---|---|---|
| Каталог 435/90/406/411/88/19 (Δ=0) | ✅ | полный pytest зелёный (в т.ч. пин-тесты каталога); новых параметров нет |
| R17 (секреты/приватный текст в логах) | ✅ | ревью-итер.1: URL/`str(exc)`/тело убраны из логов `tools/video_downloader.py` (`direct 403`/`direct downloaded`/`low disk`/merge-фолбек/retry/`cobalt http`); caplog-тест `tests/test_download_round1016.py::TestNoSecretsLogging` (URL/токен/тело не в логах) |
| R16 (id/entity_name/entity_type) | ✅ | смоуки используют id/`target_user`-лейблы, не id вместо имён |
| Порядок роутеров `bot.py` | ✅ | только снятие startup-гейта вокруг 4e; позиция/порядок не менялись |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| SQL/DDL | ✅ | не требуется; SQLite v9 |
| JS-гейты | ✅ | `NODE_CHECK_OK`, `JS-UNIT-OK` |

*Round 10.16 F3 audit generated by @Builder on 2026-09-14.*
