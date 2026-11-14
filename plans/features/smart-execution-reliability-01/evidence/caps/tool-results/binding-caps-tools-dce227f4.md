# C2-01 / C3-01 · tool-result family — binding evidence

Стадия C (SMART-EXECUTION-RELIABILITY-01), делегированный lane: результаты
инструментов `search_aggregator`, `tool_router` (memory/transcripts/health),
`voice_transcripts`, `mca_vision` (+ непосредственно необходимые helper'ы
`youtube_transcript_engine`, `youtube_summarizer_service`, `tool_schemas`).

* База: `aca1370250a7579cd3cc969679852cf2b1d2608b`.
* Ветка: `smart/caps-tools`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-43c9d868`.
* Кодовый кандидат (CODE_SHA): **`dce227f4`** — финальный кандидат тестов
  (пять малых коммитов по семейству + test-only коммит, добавляющий composer-
  проверку для memory/transcripts/vision; `8bb18603` — предыдущая точка того
  же кода). Docs-коммиты этого файла код не меняют.
* Итоговый HEAD ветки: docs-коммит с этим файлом ПОСЛЕ `dce227f4`; Reviewer
  работает с CODE_SHA `dce227f4` (docs-изменения код не меняют).
* Дифф: 7 файлов `services/`, 6 файлов `tests/`; `git diff --check
  aca13702 HEAD -- services tests` пуст. `git diff -w` отличается от обычного
  только на 1 строку (`voice_transcripts._select_around` — та же строка с
  другой индентацией; whitespace-only churn отсутствует).
* Требования: `SXR-C2-01` (в границах семейства), `SXR-C3-01` (7 шагов для
  затронутых инструментов). `SXR-C2-01` НЕ закрывается этим lane целиком:
  документы/страницы = S3 (уже закрыт), фактчек и длина сообщений — отдельные
  lane'ы, суммарный объём/повторное усечение L1/Writer = C3-02.

## 1. Решения по каждому потолку

| # | Точка (file:line кандидата) | Было | Решение | Замена | Тест |
|---|---|---|---|---|---|
| 1 | `services/search_aggregator.py:724,820` (+ удалён `_truncate`) | `return self._truncate(text, max_symbols)` → `text[:max_symbols]`; tool_router передавал `hard_ceiling`, settings-дефолт 4000 | **искусственный** → удалён | весь ответ провайдера; `max_symbols` — только совместимость сигнатуры, не режет; упаковку делает `tool_router._compact_search_candidates` (URL-индекс + `retrievable_remainder`) | `test_caps_tool_results.py::test_search_provider_result_is_not_trimmed_to_4000`, `::test_search_tool_result_reaches_payload_and_answer`; обновлён `test_search_aggregator.py::test_max_symbols_is_not_a_hard_trim` |
| 2 | `services/tool_router.py:2088-2091` (`_query_chat_memory`) | `_truncate(..., _MEMORY_MAX_SYMBOLS=3500)` | **искусственный** → удалён | `"\n".join(parts)` целиком; top-K FTS/vector (40/15) остаётся семантической выборкой | `::test_query_chat_memory_result_not_trimmed_to_3500`; `test_tool_router.py::TestQueryChatMemory::test_result_not_truncated_to_3500` |
| 3 | `services/tool_router.py:2345-2347` (stats) | `_stats_json_payload(payload, 3500)` | **искусственный** → удалён | `limit=0` = без бюджета; явный положительный бюджет по-прежнему работает (`_stats_json_payload:1145`) | `::test_stats_payload_no_budget_returns_complete_contract` |
| 4 | `services/tool_router.py:2949-2990` (`_transcribe_video`) | `_truncate(text, 3500)` | **искусственный** → удалён | полный транскрипт | `::test_transcribe_video_link_stt_returns_full_text` |
| 5 | `services/tool_router.py:2829-2868` (`_summarize_video`) | `_truncate(text, 3500)` | **искусственный** → удалён | полная выжимка | `test_tool_calling_round1015.py::TestSummarizeVideo::test_result_not_truncated` |
| 6 | `services/tool_router.py:5405-5451` (`_get_bot_health`) | `_truncate(text, 3500)` | **искусственный**, тот же общий константный потолок → удалён (смежная точка в том же файле) | полный отчёт | покрыто `tests/test_selfdiag_corrective_research.py` (без изменений) |
| 7 | `services/tool_router.py:1191-1211` (`_dig_result_budget`) + `_dig_json_payload:1026` | `int(hot.get("limits.dig_max_symbols", settings.DIG_MAX_SYMBOLS=3500))` — заводской потолок 3500 с урезанием секций | **искусственный factory-default** → не применяется; бюджет только при явной операторской настройке (`limits.dig_max_symbols>0`), `limit<=0` = целиком | `_dig_json_payload(result, 0)`; явный бюджет сохранён для тестов/вызовов | `::test_dig_result_budget_is_explicit_policy_only`; `test_tool_router.py::TestDigIntoLore::test_result_not_truncated_to_3500` |
| 8 | `services/tool_router.py:3840-3880` (`_memory_lookup_parse`) | hard-ceiling `max_items ≤ 20` | **искусственный** → удалён | явный `max_items` уважается (`max(1,int)`), дефолты purpose сохранены | `::test_user_context_explicit_max_items_and_full_fragments`, `::test_user_context_explicit_small_max_items_still_applies`; `test_memory_lookup_round1026.py::TestCaps::test_explicit_max_items_is_honored` |
| 9 | `services/tool_router.py:3831-3837` (`_memory_lookup_serialize`) | JSON-бюджет 4000: при переполнении хвостовые facts/sources **выбрасывались** (в тесте 2 факта×3000 → `facts=[]`) | **искусственный** → удалён | полный `json.dumps(payload)` | `::test_user_context_explicit_max_items_and_full_fragments`; `TestCaps::test_result_has_no_artificial_budget` |
| 10 | `services/tool_router.py:4637-4655` (`_memory_lookup_payload`) | `facts[:_MEMORY_LOOKUP_MAX_ITEMS_HARD=20]`, `sources[:20]` | **искусственный** | без среза: набор ограничен явным `max_items` | те же тесты §1 п.8 |
| 11 | `services/tool_router.py:4213-4290` (`_memory_lookup_unified_items`, `candidate_message_item`), `4495-4520` (`message_item`), `4463` (`rag_fact_item`) | срезы 240 символов (`_MEMORY_LOOKUP_SLICE_MAX_CHARS`, `_MEMORY_LOOKUP_RAG_FACT_CHARS`) | **искусственные** → удалены | полный текст факта/сообщения; `source_id`/`origin` сохранены | `::test_user_context_general_messages_are_full`; `TestCaps::test_slice_chars_not_capped` |
| 12 | `services/tool_router.py:4368-4372`, `4302-4314` (speech_style/general fallback) | `min(max_items, 5, 10)` сообщений | **искусственный** | `max(1, max_items)` | `TestCaps::test_message_slice_uses_requested_max_items` |
| 13 | `services/tool_router.py:4529-4535` (dossier), `4550-4564` (portrait/style) | cap 4000 на dossier-рендер; портрет 600; patterns/themes `[:5]` | **искусственные** → убраны | dossier без бюджета (`cap_chars=0`), портрет/профиль целиком, все patterns/themes | `::test_user_context_explicit_max_items_and_full_fragments` (payload без обрезки) |
| 14 | `services/tool_router.py:2871-2877` (`_video_transcript`); `services/youtube_transcript_engine.py:237,662-683`; `services/youtube_summarizer_service.py:99,148-156` | `_SUMMARIZE_TRANSCRIPT_CAP=20000`; `settings.YOUTUBE_MAX_SYMBOLS=4000` в `fetch_transcript`; срез `transcript[:max_symbols]` в `summarize_transcript` | **искусственные** → удалены для входного транскрипта | `fetch_transcript(video_id, None/0)` = все сегменты; `max_symbols` остаётся **только** лимитом ДЛИНЫ ОТВЕТА в промпте (разрешённый класс «лимит генерации») | `::test_youtube_transcript_full_without_factory_cap`, `::test_transcribe_video_youtube_requests_whole_subtitles`; обновлены `test_youtube_summarizer_service.py` |
| 15 | `services/voice_transcripts.py:458-487` (`_select`/`_select_around`) | `_MAX_ITEMS=3`: ряд 2–3 голосовых, хвост ряда отбрасывался | **искусственный** → удалён | без явного `count` — весь ряд; явный `count`/направление — семантическая выборка пользователя, `omitted` честно считает вытесненное | `::test_voice_bundle_returns_whole_run_not_three`, `::test_voice_bundle_explicit_count_is_semantic_selection` |
| 16 | `services/voice_transcripts.py:68,422-440,771,820` | страница БД 120 строк молча могла отрезать начало ряда | **технический** (один SQL-запрос `get_voice_window(limit)`), но честно помечен | `window_truncated` в bundle/to_dict/атрибуте `window="truncated"` + строка «страница окна чтения заполнена»; контракт продолжения через повторный запрос/уточнение | `::test_voice_bundle_page_full_is_marked_not_exhaustive` |
| 17 | `services/mca_vision.py:2134-2150` (`OUTPUT_TOKEN_*`), `resolve_output_token_limit:2198` | `max_tokens` vision-вызова (пол 512, потолок 32768, дефолт 4096/16384 reasoning) | **физический/провайдерский** → сохранён и документирован | completion-budget OpenAI-совместимого вызова; конфигурируется `models.vision_max_output_tokens`; обрезание провайдером → честный `output_truncated` + bounded-повтор; контент (OCR/описание) не режется | `::test_vision_provider_step_keeps_full_ocr_and_real_limit`, `::test_recognize_image_tool_result_and_payload_full_ocr`, `::test_vision_media_render_keeps_full_ocr_and_description` |
| 18 | `services/mca_vision.py:1185,1228-1234` (`_CONTENT_SAMPLE_MAX=160`) | короткий образец для диагностики | **безопасность/R17** → сохранён | полный OCR в диагностику не уходит; на доставку evidence не влияет | покрыто существующими vision-тестами |

Классификация: п.1–15, 17-контент — искусственные/прежние продуктовые;
п.16 — техническая страница чтения с честной пометкой; п.17 (`max_tokens`) —
физический предел генерации; п.18 — приватность диагностики (не evidence).

Сохранённые СЕЛЕКТОРЫ (не постфактум-срезы, владелец разрешает семантическую
выборку, §C2): `SearchAggregator(max_results=5)` — запрошенное у провайдера
число хитов; Exa `contents.text.maxCharacters=2000` — параметр запроса
провайдеру (провайдер отдаёт меньше — используем как есть, не добиваем);
`_MEMORY_FTS_LIMIT=40`, `_MEMORY_VEC_LIMIT=15`,
`_MEMORY_LOOKUP_APPEARANCE_SCAN=200`, `_MEMORY_LOOKUP_STYLE_SCAN=120`;
`_MAX_WINDOW_ROWS=120` (п.16, с честной пометкой). Это top-K/пулы
ранжирования, а не обрыв уже полученного текста.

## 2. C3-01: семь шагов по семействам

| Семейство | Шаг 1 (что реально получил инструмент) | Шаги 2–7 | Статус |
|---|---|---|---|
| Поиск | **реальный** provider-путь `SearchAggregator._search_tavily` → `_format_hits` поверх `httpx.MockTransport` (5 хитов × 1200 симв.) | агрегатор → `execute_web_search` (`_compact_search_candidates`) → tool-loop (`role:tool`) → composer `build_context_selection(budget_tokens=0)` → payload → финальный ответ по маркеру | проверено исполняемым тестом |
| Память (`query_chat_memory`) | repository-двойник (`search_long_term`/`count_mentions`) — это тот же шов, что используют 40+ существующих тестов; **живой SQLite-объём не гонялся** | tool result → tool-loop → payload (byte-identical) → финальный ответ; composer покрыт общим тестом §C3 S3 | шаг 1 — на границе хранилища, не live-DB |
| Память (`get_user_context`) | durable-строки graph_facts через `mca_retrieval_context.retrieve` (реальный retrieval-код) на двойнике БД | payload (30 фактов × 3002 симв.) → tool-loop byte-identical → финальный ответ | шаг 1 — retrieval-код с двойником БД |
| YouTube-транскрипт | **реальные сегменты** провайдера через `YouTubeTranscriptEngine.fetch_transcript` (стаб `_fetch_ytdlp` возвращает сегмент-структуры; реальный `_format`) | `transcribe_video` → ToolResult → tool-loop → payload; полный текст 9000+ | проверено |
| STT-транскрипт | транспортный стаб `transcriber.transcribe_voice` (внешний STT не вызывался) | `transcribe_video` link-путь → tool-loop → payload → ответ | шаг 1 — stub внешнего STT |
| Голосовые | durable-строки `smart_messages` (voice, ready) через `resolve_voice_bundle`; реальный `render_voice_block` | bundle → блок Writer'а; 6 фрагментов × 900 симв. доходят целиком | проверено |
| OCR/Vision | **реальный** `analyze_image_bytes` с transport-стабом провайдера (200 + JSON, 5000-симв. OCR) | `recognize_target` → `recognize_image` → tool-loop → payload (byte-identical); потребительский `render_media_context_async` | проверено; живой Telegram/провайдер — только postdeploy |

Честно: живой LLM/Telegram/Vision-провайдер и production effective config не
вызывались (нет деплоя). Это не доказывает production-поведение; см. §6.

## 3. RED на базе и mutation proof

`tests/test_caps_tool_results.py` (17 тестов) на базе `aca13702`:
**12 failed, 5 passed** (`raw/red-base-aca13702.txt`,
`raw/red-base-aca13702-verbose.txt`).

Проходят на базе осознанно:
* `test_vision_*` (3) — в Vision не было искусственного контентного потолка
  (классификация «оставить»);
* `test_search_tool_result_reaches_payload_and_answer` — router и раньше
  передавал агрегатору `hard_ceiling` (200000), поэтому 4k-срез не срабатывал;
* `test_voice_bundle_explicit_count_is_semantic_selection` — явный `count=2`
  разрешался и старым `_MAX_ITEMS=3`.

Mutation proof (возврат одного потолка): в `_query_chat_memory` временно
возвращён `_truncate(..., 3500)` → целевой
`test_query_chat_memory_result_not_trimmed_to_3500` **failed**; после отката —
**1 passed**. (`git status` после отката чистый.)

## 4. Прогоны (venv `C:\Code\Python\adminbot\.venv`)

| Прогон | Результат |
|---|---|
| `pytest tests/test_caps_tool_results.py` | **17 passed** |
| search: caps + `test_search_aggregator.py` + `test_search_source_dates.py` | **53 passed** |
| factcheck-потребители агрегатора: `test_factcheck_p0_fc.py`, `test_factcheck_fc_r1_fix.py`, `test_fc_backend_corrective.py` | **84 passed** |
| memory: caps + `test_memory_lookup_round1026.py` + `test_memory_unified_retrieval_06.py` + `test_mem_time_policy.py` + `test_mem_time_profile.py` + `test_mca15_chat_statistics_round1028.py` + `test_scanner_fixes_round1020.py` + `test_tool_schemas.py` + `test_mca11_tool_result_round1028.py` | **306 passed** |
| transcripts: caps + `test_youtube_transcript_engine.py` + `test_youtube_summarizer_service.py` + `test_video_cascade.py` + `test_vmq_v_voice_writer.py` + `test_media_transcribe_tool_round1024.py` + `test_native_media_tools_round1024.py` + `test_asap8_f9_youtube_proxy.py` | **386 passed** |
| vision: caps + `test_evol011_vision_telemetry.py`, `test_evol019_vision_recognition.py`, `test_evol_vision_sync_core.py`, `test_evol_vision_sync_wave2.py`, `test_p0_vision_fix_core.py`, `test_vision_adapt.py`, `test_mca19_block_[a-g]_round1043.py`, `test_mca19_rework_r1_round1044.py` | **314 passed, 38 skipped** (`raw/vision-batch.txt`) |
| affected tool/loop batch (12 файлов: tool_router/tool_chains/tool_calling/agentic/memory_commands/recent_history/smart_execы/selfdiag) | **428 passed** |
| broad affected набор (121 файл: smart/memory/mem/tool/search/factcheck/fc/youtube/video/vmq/selfdiag/checkup/agentic/mca15/mca19/mca2x/direct_chat/evol seams) | **3523 passed, 4 failed, 18 errors** (`raw/broad-affected.txt`) |

4 падения и 18 ошибок broad-набора **воспроизведены на базе `aca13702` тем же
прогоном** (pre-existing): `test_mca20_rework1_f1_f2` (escape injection),
`test_mca23_planned_vs_actual::test_routes_pin_untouched` (routes.py byte-freeze),
`test_tool_coordinator_round1026::TestBounds::{test_forbidden_paths_out_of_diff,
test_canon_twelve_tools}`, `test_youtube_multimodal_download_round1024.py`
(18 fixture-errors). Мои изменения их не вводят; отдельный backlog не заводился
(это уже известный класс pre-existing из предыдущих binding'ов, кроме
routes/canon — см. §7).

## 5. Effective configuration

* Ни один из снятых потолков не гейтился `flags.budgets_enabled` — это были
  безусловные заводские срезы. После удаления поведение одинаково при OFF/ON
  бюджетах; новые бюджеты не вводились.
* `tool_router` для search/fetch_article по-прежнему использует существующий
  `auto_budget.resolve_evidence_tool_window` (окно фактической модели). В
  тестовой среде unknown-model даёт planning-window 1 000 000 токенов и
  `effective_limit=200000` симв. — этого достаточно для >4000-проверок.
* `settings.YOUTUBE_MAX_SYMBOLS` (дефолт 4000) остаётся **только** лимитом
  длины ответа в промпте; входной транскрипт больше не ограничивается.
* `limits.dig_max_symbols`: заводской `settings.DIG_MAX_SYMBOLS=3500` больше
  не применяется; действует только явно сохранённое значение каталога.
  **Postdeploy:** проверить effective-значение ключа в production-конфиге (если
  оно там сохранено старым UI как 3500, оно останется явной политикой).
* `models.vision_max_output_tokens`: физический completion-budget; дефолт
  4096 (16384 для reasoning), кламп 512..32768.

## 6. Что осталось непроверенным / residual

1. **Postdeploy (агент-исполняемое):** production-прогон
   search/memory/transcripts/vision на deployed SHA — реальные ответы
   провайдеров, effective-конфигурация, Telegram-доставка. Локально сеть
   провайдеров не вызывалась (кроме случайного DDG в одном старом тесте).
2. **Остаточный потолок вне write-scope lane:** `mca_retrieval_context.
   _truncate_preview` (`_PREVIEW_MAX_CHARS=400`) режет `preview` кандидатов
   retrieval; `get_user_context` general/speech_style строит message-факты из
   этого preview, поэтому тексты сообщений из unified-канала остаются ≤400
   симв. Это контракт `memory_contracts.PREVIEW_MAX_CHARS` публичного
   memory-search API (не только tool) — его изменение выходит за границы
   делегированного lane; tool_router-срезы (240/5/10/20) сняты и проверены на
   fallback-пути. **Нужен отдельный решение/слайс по memory-retrieval.**
3. `handlers/youtube.py:226` `_YT_TRANSCRIPT_CAP=20000` — прямой
   user-командный путь «транскрипт» (вне tool-result family); handler уже
   чанкует Telegram, но cap остаётся. Не менялся (вне scope).
4. `voice_transcripts._MAX_WINDOW_ROWS=120` — техническая страница одного
   SQL-запроса; >120-строчный ряд помечается `window_truncated`, но не
   дочитывается (нет DB-API для страницы назад). Редкий случай, честно виден
   модели.
5. `mca_vision` живой Vision-провайдер/Telegram не вызывались; провайдерский
   `finish_reason=length` обрабатывается существующим `output_truncated`.
6. Pre-existing падения broad-набора (см. §4) — не мои; `routes.py` byte-freeze
   и `tool_coordinator` bounds падают и на базе.

## 7. Безопасность / контракты

* Не ослаблены: path traversal/ADS, binary, SSRF SafeFetcher, Vision image
  pixel/size preprocessing, rate/timeout, Telegram chunking, R17 (в логи не
  уходят URL/ключи/полный OCR), trust-контракт OCR (untrusted data channel).
* Provenance/порядок источников сохранены: `source_id`, `origin`, `published_at`,
  `source_ref`, `primary`, `omitted`, `requested` не менялись; новые поля
  аддитивны (`window_truncated`).
* Никаких новых LLM-стадий, instruction-quota, storage/pipeline не введено.

## 8. Housekeeping

Одноразовый прогон `WorkspaceData/runs/.../probe-bba9aa6255` закрыт
(`run-close --apply`): RED/mutation/broad/vision логи скопированы в `raw/`
этого артефакта; базовый RED-worktree `...-20d51a52` снят (чистый, RED
зафиксирован здесь). `unit-check` для `sxr-c2-01-toolcaps`:
`cleanup_complete=true`, `remaining=[]`.

Главный worktree `...-43c9d868` (`smart/caps-tools`) и feature-ветка
сохраняются для Reviewer/интеграции (не объединены в master/train; это
ожидаемое удержание до независимого review).
