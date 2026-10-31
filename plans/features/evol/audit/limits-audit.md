# Полный инвентарь действующих лимитов (§2 ASAP-EVIDENCE-ROUTING-01 v3)

**Объект аудита:** ветка `evol/impl`, HEAD `57081925`, production 2.58.145 @ `4bf3604a`.
**Режим:** только чтение кода. Образцы/скрипты сканирования — во временном run-каталоге, не в репозитории.
**Связанные артефакты:** `plans/features/evol/audit/asap-evidence-routing-matrix.md` (46 сценариев), `limits-audit.md` (этот файл).

## 1. Метод и доказательство полноты охвата

1. **AST-скан** всех модульных числовых констант в `config/`, `services/`, `handlers/`, `utils/`, `core/` по семействам
   `MAX|MIN|LIMIT|CAP|BUDGET|RESERVE|HEADROOM|CHARS|BYTES|SYMBOLS|TOKENS|TIMEOUT|DEADLINE|TTL|COOLDOWN|RETR|ROUNDS|STEPS|CALLS|PAGES|CHUNK|TOP_K|WINDOW|SIZE|THRESHOLD|PERCENT|SHARE|RATIO|QUOTA`.
   Результат: **597** числовых констант в 173 файлах; исключены `tests/`, `plans/`, `web/**` (чужая полоса), `__pycache__`, миграции.
2. Для каждого кандидата определялся **реальный потребитель** (точка чтения), а не только имя: чтение кода вызова, `hot.get(...)`, `settings.*`, `param_catalog`.
3. Дополнительно проверены «не-константные» ограничители: срезы `[:N]`/`_truncate`, SQL `LIMIT`, hot-ключи каталога (`limits.*`), env-переопределения `ClassVar`, дефолты `config/settings.py`.
4. Значения ниже — **заводские значения кода** (env-дефолты / константы). Эксплуатационные переопределения живут в `.env` и PG-hot-каталоге (`limits.*`); они обязаны читаться из effective-конфигурации при замере, а не предполагаться. Там, где значение уже берётся из резолвера, это указано.

## 2. Классы и приоритеты

| Класс | Смысл | Решение по §2 |
|---|---|---|
| **A** | непреложный safety/security/RBAC/финансовый предел | сохранить без изменений |
| **B** | физический provider/model/transport предел | читать из возможностей провайдера/модели, не хардкодить |
| **C** | управляемый эксплуатационный предел (латентность/частота/ресурс) | сделать настраиваемым/динамическим с безопасным дефолтом |
| **D** | условный UX preview | применять только к отображению, с доступом к полной сущности |
| **E** | случайный/устаревший quality-degrading hardcap | удалить или заменить динамикой |

Приоритеты: **P0** — потеря evidence/source и ложные отказы; **P1** — окна инструментов/модели/контекста; **P2** — остальное (по реальной потере данных и экономике).

## 3. P0 — доставка evidence/источника и ложные отказы

| # | Файл:строка | Ограничитель / текущее значение | Runtime consumer, стадия | Область | Класс | Последствие | Альтернатива / исправление | Как доказать |
|---|---|---|---|---|---|---|---|---|
| 1 | `services/tool_router.py:91` | `_SEARCH_MAX_SYMBOLS = 4000` | `_execute_web_search` → `search(..., max_symbols=4000)` (`:1136`) **и** повторный `_truncate(text, 4000)` (`:1150`); затем EvidencePack | global / tool / model | **E** | Выдача — «индекс кандидатов» превращается в один обрезанный кусок: URL и доказательство за 4k недостижимы; двойной срез | Не резать выдачу по 4000: отдавать кандидатов (title/url/snippet) + реальный fetch первоисточника; бюджет evidence брать из существующего `l2_evidence_budget_chars` | Фикстура: 30 результатов, целевой URL на позиции 25 → URL присутствует в EvidencePack; событие `truncated=false, source=<provider>` |
| 2 | `services/tool_router.py:131` | `_ARTICLE_MAX_SYMBOLS = 8000` | `fetch_article` → `extractor.extract(url, 8000)` (`:2234`) → `text[:max]` (`web_content_extractor.py:114`) | global / tool / model | **E** | Длинная документация/репозиторий обрывается **до** нужного раздела; `truncated` без remainder | `offset|section|line_range` + `full_source_pointer` в существующем `fetch_article`; не заменять на «другие жёсткие 16000/32000» (§3) | Статья 40k, нужный раздел на 25k → выдержка с `line_range`, `remainder` доступен повторным вызовом |
| 3 | `services/tool_router.py:715-720` | `_truncate()` — слепой `text[:limit].rstrip()+"…"` | `:1150` (поиск), `:3527` (`get_bot_health`), прочие tool-ответы | global / tool | **E** | Рвёт URL/JSON/пары `claim→source`; причина и остаток не наблюдаемы | Структурный конверт: `effective_limit/source/used/truncated/why/retrievable_remainder`; границы по целым единицам (сообщение/абзац/строка/элемент) | Тест: JSON-ответ и URL не разрезаны; поля конверта присутствуют |
| 4 | `services/web_content_extractor.py:243-246` | `_truncate()` — hard slice | `extract()` (`:83-114`) | global / reader | **E** | Тот же дефект на уровне reader'а | Убрать срез из reader'а; reader возвращает полный текст/чанки, ограничение — на стороне доставки | Юнит: reader не режет; доставка режет по границам |
| 5 | `services/web_content_extractor.py:185` | `include_links=False` | `_extract_trafilatura` | global / reader | **E** | Внутренние ссылки первоисточника исчезают → нельзя проверить следующий уровень | Сохранять ссылки отдельным структурированным списком (не в тексте), ограниченно и безопасно | Фикстура html со ссылкой на официальный источник → `links[]` в payload |
| 6 | `services/web_content_extractor.py:35` | `_MIN_CONTENT_CHARS = 150`; «≤150 → провал уровня» | `extract()` | global / reader | **D → E** | Короткий официальный changelog/release-notes отвергается как «short content», уходит в облачный фолбэк или в `extract_failed` → ложный «источник недоступен» | Принимать короткий контент с пометкой `short_content`; порог — только для решения «фолбэк», не для отказа | Фикстура 120-символьной страницы → `status=ok, short_content=true` |
| 7 | `services/web_content_extractor.py:33-34` | `_FETCH_TIMEOUT = 10.0`, `_API_TIMEOUT = 15.0` | уровни каскада | global / transport | **C** | Медленный первоисточник падает по 10 с, хотя общий бюджет поиска 45 с; таймауты не связаны с `request_deadline` | Передавать остаток дедлайна (образец уже есть: `SearchAggregator.search(timeout_budget=…)`, `search_aggregator.py:510-577`) | Тест: медленный провайдер 12 с при бюджете 45 → успех |
| 8 | `services/tool_router.py:96` | `_SEARCH_TOOL_TIMEOUT = 25.0` | `asyncio.wait_for` вокруг поиска (`:1135-1138`) | global / tool | **C** | Фиксированный таймаут не согласован ни с дедлайном пользователя, ни с фоном | `min(остаток дедлайна, безопасный cap)` из существующего бюджета | Тест: дедлайн 8 с → таймаут ≤8; причина `budget_or_deadline` |
| 9 | `services/tool_router.py:130` | `_ARTICLE_TOOL_TIMEOUT = 45.0` | `fetch_article` (`:2233-2235`) | global / tool | **C** | То же для чтения статьи | То же | То же |
| 10 | `services/direct_execution.py:911` | `DEFAULT_EVIDENCE_CAP_CHARS = 4000` (окно неизвестно) | `build_evidence_pack` fallback при `capacity_chars=None` (`:956-958`) | direct / evidence | **C** | Без окна evidence жёстко 4000 на все источники; честно помечается, но остаётся потолком | Сохранить как **явно помеченный** аварийный дефолт + попытка metadata discovery (`model_capacity`) — уже есть; в trace выводить `source=unknown_fallback` | Тест: неизвестная модель → `capacity_source=unknown_fallback`, WARN один раз |
| 11 | `services/direct_execution.py:913` | `EVIDENCE_MAX_SHARE = 0.4` (40 % бюджета на evidence) | `l2_evidence_budget_chars` (`:916-931`), потребитель `direct_chat_service.py:4223-4244` | direct / evidence | **C** | При большом окне evidence ≤40 % — для сложного расследования этого мало, и остальное окно не используется | Доля зависит от типа задачи (factual research ≠ social), верхняя граница остаётся; Core/reply/OCR защищаются первыми | Тест: research-фикстура получает больше evidence, чем social при том же окне; Core не вытеснен |
| 12 | `services/direct_l1.py:1044-1051` | `DEFAULT_DIRECT_L1_EVIDENCE_MAX_CHARS = 4000` (legacy-путь `build_evidence_packet`) | `build_evidence_packet(..., max_chars=None)` | direct / evidence | **C** | Второй, независимый 4000-потолок для вызовов вне основного пайплайна | Оставить как compat-путь, но убрать из основного пути (там уже динамика) | Grep-тест: основной путь не вызывает `evidence_max_chars()` |

**Итог P0:** основной вред — №1–5 (жёсткие 4000/8000 + слепой срез + потеря ссылок) и №6 (ложный «источник недоступен» на коротком официальном тексте). Это ровно то, что §3 называет «искусственной потерей полезной информации».

## 4. P1 — окна инструментов, модели, контекста

| # | Файл:строка | Ограничитель / значение | Consumer, стадия | Область | Класс | Последствие | Исправление | Как доказать |
|---|---|---|---|---|---|---|---|---|
| 13 | `services/direct_l1.py:788` | `L1_WINDOW_LINE_CHARS = 200` | `render_window_lines` (`:1034`), весь L1-вход | direct / planner | **E** | L1 **не видит** claim в длинной реплике → не запрашивает capability → ответ без evidence (корень «не уверен → не проверяю») | Динамическая длина строки по окну L1; защищённые P0-фрагменты (вопрос, reply-цель) не резать | Тест: сообщение 1200 симв. с версией/цифрой → L1-вход содержит этот фрагмент |
| 14 | `services/direct_l1.py:787` | `L1_REPLY_BLOCK_CHARS = 400` | reply-block L1 (`:834-835`) | direct / planner | **E** | Целевая цитата режется до 400 — факт из цитаты теряется | То же: приоритет reply-цели, не резать внутри URL/числа | Тест: reply 900 симв. → версия/цифра присутствует |
| 15 | `services/direct_l1.py:785` | `L1_WINDOW_MESSAGES = 20` | `render_window_lines(..., 20)` (`:840,848`) | direct / planner | **D** | Окно планировщика уже контекстного окна; часть истории не видна планировщику (но видна Writer) | Оставить UX-окно, но добавить признак `history_partial` (уже есть) в policy решения | Тест: `history_partial=true` не блокирует evidence |
| 16 | `services/direct_l1.py:786` | `L1_PERSONA_FRAME_CHARS = 400` | `:873` | direct / planner | **D** | Персона описывается головой блока; не влияет на факты | не менять | — |
| 17 | `services/chat_context.py:17` | `_CHAT_CONTEXT_MAX_CHARS = 2000` | `build_chat_context` | retrieval / context | **E** | Фон беседы срезан до 2000 символов — при длинных технических сообщениях теряется предмет | Динамика по бюджету контекста с приоритетом reply/целевых сообщений | Тест: длинный контекст сохраняет целевые сообщения |
| 18 | `services/chat_context.py:21` | `_REPLY_CHAINS_MAX_CHARS = 1200` | `build_chat_context` | retrieval / context | **D** | Цепочка reply-разбора обрезается | Оставить с приоритетом «цитируемая сторона» | Тест: цепочка сохраняет claim-реплику |
| 19 | `config/settings.py:700` | `CHAT_UNKNOWN_MODEL_WINDOW = 16384` | `model_capacity._unknown_window()` (`model_capacity.py:173-179`) | global / model | **B/C** | Неизвестная модель консервативно 16k; корректно помечается `source=unknown_fallback` + WARN | Не менять как физику; расширять discovery-адаптеры (openrouter/nanogpt/llama.cpp/ollama/vllm уже есть) | Тест: новая модель без каталога → `fallback` + WARN один раз; после каталога → реальное окно |
| 20 | `config/settings.py:539` | `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS = 32000` | композер контекста (`direct_context_composer`) | direct / context | **C** | Верхний предел «безлимитного» контекста | Оставить как защиту от переполнения; связать с реальным окном модели | Тест: `-1` режим не превышает ceiling |
| 21 | `config/settings.py:711` | `CHAT_MIDDLE_MAX_MESSAGES = 60` | `direct_context_composer` | direct / context | **D** | Середина истории ограничена 60 сообщениями | UX-окно; при `history_partial` — честная пометка (есть) | Тест: пометка присутствует |
| 22 | `config/settings.py:713` | `CHAT_THREAD_WALK_MAX = 40` | `direct_context_composer` | direct / context | **D** | Обход ветки reply до 40 | не менять | — |
| 23 | `config/settings.py:705,707,709` | `CHAT_EPISODE_MAX_MESSAGES = 40`, `CHAT_EPISODE_MAX_COUNT = 2`, `CHAT_FRESH_TAIL_MIN_MESSAGES = 20` | эпизоды + свежий хвост | direct / context | **D** | Осознанное UX-окно (ADR-1028-2) | не менять | — |
| 24 | `config/settings.py:612` | `DIRECT_L1_CONTEXT_TOKENS = 1600` | L1 payload | direct / planner | **C** | Малое окно планировщика; при 20 сообщениях по 200 символов — на грани | Поднять/динамизировать от реального окна модели (L1 — маленькая модель, но 1600 очень мало для 20 реплик) | Тест: 20 сообщений усечены по бюджету, а не «тихо» |
| 25 | `config/settings.py:616,628` | `DIRECT_L1_MAX_OUTPUT_TOKENS = 512`, `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS = 4096` | L1 JSON / Writer | direct / model | **B** | 512 достаточно для JSON-плана; 4096 — output Writer | Читать физический max output из возможностей модели (`response_extent._MAX_OUTPUT_TOKENS_CEILING = 16384`) | Тест: модель с большим max output получает больший резерв только при longform |
| 26 | `services/response_extent.py:79-80` | `DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS = 4096`, `_MAX_OUTPUT_TOKENS_CEILING = 16384` | резолвер output | direct / model | **B/C** | Потолок 16384 не равен физическому max output некоторых моделей | Оставить потолок как safety, но резерв считать из `model_capacity.capability_aware_output_reserve` | Тест: класс модели → разный резерв |
| 27 | `services/tool_loop.py:44,50,53` | `TOOL_MAX_ROUNDS = 4`, `TOOL_MAX_TOTAL_CALLS = 6`, `TOOL_CHAIN_MAX_METERED_CALLS = 4` | `chat_with_tools` | global / tool | **C** | Разумная цепочка «поиск → 2 первоисточника → сравнение» упирается в 4 метered-вызова | Оставить как защиту от циклов; сделать конфигурируемым (`MCA_TOOL_*` уже есть) и считать «нужные» вызовы по числу непроверенных claim | Тест: 2 claim × (search+fetch) укладываются при явном бюджете |
| 28 | `services/tool_loop.py:45,52` | `_TOOL_CALLS_PER_ROUND_MAX = 2`, `_TOOL_MAX_SAME_CALL = 2` | тот же цикл | global / tool | **C** | Дубли одного вызова режутся (полезно), но параллельные независимые вызовы тоже ≤2 | Оставить; при явном плане разрешать параллель по числу claim | Тест: два независимых fetch выполняются |
| 29 | `services/tool_loop.py:51` | `TOOL_CHAIN_TIMEOUT_SECONDS = 360.0` | тот же цикл | global / tool | **C** | Может превышать пользовательский SLA (нет промежуточной реакции) | Согласовать с `request_deadline`: короткая промежуточная реакция/durable continuation (§3) | Тест: превышение SLA → промежуточный статус, не молчание |
| 30 | `services/direct_execution.py:88-94` | `ORCHESTRATOR_MAX_STEPS = 4`, `MAX_TIME_SECONDS = 90`, `MAX_TOTAL_TOKENS = 6000`, `MAX_METERED_CALLS = 4` | `run_adaptive_chain` | direct / tool | **C** | Многошаговое расследование отсекается; 6000 токенов на планировщик мало при 4 шагах с evidence | Читать бюджет из `auto_budget`/`model_capacity`; число шагов — по числу непроверенных claim | Тест: 3 claim → шаги покрывают все, бюджет из резолвера |
| 31 | `services/direct_execution.py:92-94` | `ORCHESTRATOR_QUERY_CHARS = 800`, `TOOL_DESC_CHARS = 140`, `EVIDENCE_SNIPPET_CHARS = 400` | сборка orchestrator payload (`:712-733`) | direct / tool | **E** | Планировщику показывают сниппеты по 400 символов — он не может понять, что источник прочитан и достаточен | Отдавать структурированный статус источника (read_level/роль), а не урезанный текст | Тест: сниппет 400 заменён статусом+ссылкой, план не деградирует |
| 32 | `services/factcheck_context.py:57-61` | `_VERBATIM_MSG_MAX_CHARS = 600`, `_DIGEST_LINE_MAX_CHARS = 120`, `_VERBATIM_MAX_MESSAGES = 40`, `_DIGEST_BUDGET_CHARS = 8000`, `_VERBATIM_BUDGET_CHARS = 12000` (+`_WIDE_WINDOW_MAX = 500`, `_AFTER_SHARE = 0.15`, `_CACHE_TTL = 120`) | контекст фактчека | factcheck / context | **D/C** | Усечение цитируемых сообщений; при длинном claim-сообщении теряется формулировка | Приоритет целевому сообщению claim, не резать ответ/reply-цитату | FC-фикстура: claim в длинном сообщении сохраняется целиком |
| 33 | `services/mca_retrieval_context.py:306` | `_PREVIEW_MAX_CHARS = 400` | метрики/превью | retrieval / observability | **D** | Только превью для диагностики | не менять (не влияет на доставку) | — |
| 34 | `services/mca_retrieval_context.py:37` | `DEFAULT_RERANK_FALLBACK_TOP_K = 8` | retrieval rerank | retrieval | **C** | Fallback-top-8 при сбое реранкера может потерять релевантный источник | Конфигурируемо; при сбое — fail-open к полному списку | Тест: сбой реранка не уменьшает выдачу |
| 35 | `services/tool_router.py:3503-3527` + `_MEMORY_MAX_SYMBOLS = 3500` | health-отчёт режется 3500 | `get_bot_health` | tool / self-status | **D** | Диагностика теряет хвост | Отдавать структурированные поля | — |

## 5. P2 — остальные домены (реальная потеря данных и экономика)

### 5.1. FactCheck (владелец — полоса FC, здесь только инвентарь)

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация (владелец) |
|---|---|---|---|---|---|---|
| 36 | `services/factcheck_planner.py:146` | `_MAX_QUERIES = 3` | 3 запроса на claim | `build_retrieval_plan` | C | Составной claim не покрывается | FC lane: число запросов по числу независимых частей |
| 37 | `services/factcheck_planner.py:147` | `_MAX_QUERIES_TOTAL_DEFAULT = 12` | 12 на прогон | тот же | C | Многочастный тезис упирается | FC lane |
| 38 | `services/factcheck_planner.py:150` | `_MAX_PRIMARY_FETCHES = 2` | 2 первичных чтения | `:…` | **E** | Третий источник не читается никогда | FC lane: 2→по числу claim (сохранить бюджет) |
| 39 | `services/factcheck_planner.py:151` | `_EXCERPT_MAX_CHARS = 600` | выдержка 600 | evidence map | **D** | «insufficient_evidence» при наличии доказательства | FC lane: выдержка = цитата вокруг claim, не 600 подряд |
| 40 | `services/factcheck_planner.py:1064` | `_SEARCH_TEXT_BUDGET_CHARS = 8000` | текст выдачи 8000 | planner | **E** | Тот же дефект среза, что P0-1 | FC lane: индекс кандидатов |
| 41 | `services/factcheck_planner.py:511,149` | `_CLAIM_UNITS_HARD_CAP = 16`, `_MAX_EVIDENCE_REFS = 12` | 16 частей / 12 ссылок | planner | C | Длинный пост не разбирается полностью | FC lane |
| 42 | `services/factcheck_planner.py:1068-1070` | `_BUDGET_SECONDS_DEFAULT = 10.0`, `_PER_EXTRA_CLAIM = 0.5`, `_MAX = 45.0` | дедлайн | planner | C | Заявлен и соблюдается; связан с `search_aggregator.timeout_budget` | FC lane (оставить; согласовать с user SLA) |
| 43 | `services/factcheck_planner.py:1072,148` | `_REFINE_CALLS_DEFAULT = 3`, `_QUERY_MAX_CHARS = 200` | уточнения/длина запроса | planner | C | ок | FC lane |
| 44 | `services/factcheck_service.py:340` | `_MAX_ALBUM_ELEMENTS = 10` | медиа-альбом фактчека | D | Хвост альбома не анализируется | Vision/FC lane (сохранить, но сообщать о пропуске) |

### 5.2. Summary / Sleep / Memory

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация |
|---|---|---|---|---|---|---|
| 45 | `services/summary_hybrid_budget.py:51` | `HYBRID_CONTEXT_CHARS_DEFAULT = 120000` | гибридный бюджет | C | Разумный потолок | оставить |
| 46 | `services/summary_l2_writer.py:96-138` | `TITLE_MAX = 200`, `PARAGRAPH_MAX = 900`, `MAX_PARAGRAPHS_HARD = 498`, `RICH_MAX_CHARS = 32000`, `EMPHASIS_SPAN_MAX = 4`, `FINALE_MAX = 200` | статья L2 | **D** | Форма статьи; **не** ограничение источника | оставить (preview/форма) |
| 47 | `services/summary_l2_writer.py:118` | `HYBRID_MAX_CHARS_DEFAULT = 24000` | гибрид | C | ок | оставить |
| 48 | `services/summary_article_formatter.py:52-56` | те же + `PLAIN_CHUNK_LIMIT = 4096` | доставка | **A/D** | 4096 — физический лимит Telegram | оставить (A: физика платформы) |
| 49 | `services/summary_fact_package.py:117-121` | `DESCRIPTION_MAX = 500`, `FRAGMENT_MAX_CHARS = 1000`, `MAX_FRAGMENTS_PER_THREAD = 30`, `MAX_FRAGMENTS_TOTAL = 500` | пакет фактов | **E** | Пакет — «вспомогательный индекс», оригинал подставляется окном; но 500 фрагментов на 500-сообщенческий прогон — граница потери | оставить как индекс, гарантировать окно-источник (уже есть `source_window`) |
| 50 | `services/summary_memory.py:208` | `_FACT_EXTRACT_MAX_CHARS = 8000` | ETL-извлечение фактов | **E** | Батч >8000 символов теряет хвост фактов | динамика по окну модели + chunking с сохранением `source_message_ids` |
| 51 | `services/summary_memory.py:863` | `_GRAPH_EXTRACT_MAX_CHARS = 8000` | GraphRAG extraction | **E** | То же для графа | то же |
| 52 | `services/summary_memory.py:486` | `_RUNNING_SUMMARY_HEAD_MAX_CHARS = 60000` | running summary | C | ок | оставить |
| 53 | `services/summary_memory.py:131,133` | `_KNN_SCOPE_K_CAP = 512`, `_DEDUP_KNN_CAP = 192` | векторный поиск | C | ок (ресурс) | оставить |
| 54 | `services/summary_memory.py:201,209-211` | `_FACT_BASIS_MAX_IDS = 20`, `_FACT_MAX_NAME_CHARS = 100`, `_FACT_MAX_PREDICATE_CHARS = 200`, `_FACT_MAX_CONTEXT_CHARS = 400` | факты | D | Форма полей | оставить |
| 55 | `services/summary_memory.py:72-75` | `L1_GRAPH_WINDOW = 40`, `GRAPH_ACTIVATION_CAP = 5`, `_MIN_HITS = 3`, `_NODE_CAP = 12` | граф-активация | C | ок | оставить |
| 56 | `services/summary_memory.py:353` | `_YOUTUBE_MEMORIZE_MAX_CHARS = 8000` | память по видео | **E** | Хвост расшифровки не попадает в память | chunking с сохранением ссылок на оригинал |
| 57 | `services/summary_memory.py:365` | `_BACKFILL_MAX_FACTS = 500` | backfill | C | ок | оставить |
| 58 | `services/summary_memory.py:361-362` | `_EMBED_RETRY_ATTEMPTS = 3`, `_EMBED_RETRY_BACKOFF = 1.0` | retry | C | ок | оставить |
| 59 | `config/settings.py:1018` | `SUMMARY_L1_MAP_MAX_TOKENS = 6000` | L1 semantic map | C | ок | оставить (наблюдаемо в `summary_l1_semantic_map`) |
| 60 | `config/settings.py:1016` | `SUMMARY_L1_HINT_MAX_CHARS = 160` | подсказка | D | ок | оставить |
| 61 | `config/settings.py:1844` | `MAX_SUMMARY_PARTS = 1` | число частей | **D** | Одна часть вместо многочастной статьи | оставить (решение продукта) |
| 62 | `services/summary_llm_supervisor.py:73-75` | `PRIMARY_MAX_HTTP = 2`, `FALLBACK_MAX_HTTP = 2`, `TRANSPORT_MAX_RETRIES = 1` | HTTP-политика | C | ок | оставить |
| 63 | `services/summary_llm_supervisor.py:188-189` | `_MAX_SAMPLES = 32`, `_MAX_KEYS = 256` | диагностика | C | ок | оставить |
| 64 | `services/token_counter.py:35,53-54` | `_CHARS_PER_TOKEN = 0.3`, `_PROTECTED_SPAN_MAX = 24`, `_PROTECTED_SPAN_RESERVE = 48` | оценка токенов | **B** | Оценка, не токенайзер: погрешность бюджета evidence | Использовать tokenizer провайдера, где доступен (§3.2); иначе безопасная оценка (текущая) — оставить с пометкой `estimated` |

### 5.3. Vision / media

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация |
|---|---|---|---|---|---|---|
| 65 | `services/mca_vision.py:2140` | `OUTPUT_TOKEN_DEFAULT = 4096` (было магическое 1024 — уже исправлено, комментарий `:2115`) | output Vision | **B/D** | Длинный OCR/JSON может не влезть | оставить; читать класс модели (`VISION_MAX_OUTPUT_TOKENS=0 → по классу`, `settings.py:1725`) |
| 66 | `services/mca_vision.py:2523` | `timeout=60.0` (transport) | запрос Vision | **C** | ок | оставить; связать с job lease |
| 67 | `services/mca_vision.py:2152,3203-3211` | `_VISION_MAX_ATTEMPTS = 3`, sweep `30.0`, `ALBUM_MAX_GRACE_EXTENSIONS = 4`, `RETRY_BASE = 30`, `RETRY_MAX = 900`, `JOB_MAX_ATTEMPTS = 4`, `BREAKER_THRESHOLD = 3`, `BREAKER_COOLDOWN = 60` | watchdog Vision | **C** | ок (bounded, с терминальным исходом) | оставить (ASAP-VISION-SYNC-01) |
| 68 | `services/mca_vision.py:5253` | `_PENDING_TRIGGER_TTL = 600.0` | pending-запросы | C | ок | оставить |
| 69 | `config/settings.py:1701,1700,1709` | `MCA_VISION_MAX_PIXELS = 25M`, `MCA_VISION_MAX_BYTES = 20MB`, `MCA_VISION_REOCR_BUDGET = 2` | download/prepare | **A/B** | физика и защита | оставить |
| 70 | `config/settings.py:1727-1731` | `READINESS_WAIT = 20.0`, `ASSOCIATION_WINDOW = 900`, `PENDING_INTENT_TTL`, `JOB_*` | readiness barrier | C | ок | оставить (единый barrier) |
| 71 | `services/media_readiness.py:97-99,1462-1464` | `_DEFAULT_ASSOCIATION_WINDOW_SECONDS = 900`, `_DEFAULT_INTENT_TTL_SECONDS = 1800`, `_MAX_ASSETS = 10`, `_DEFAULT_MAX_RECOVERIES = 3`, `_DEFAULT_BACKOFF_MAX = 300` | readiness | **C** | ок | оставить |
| 72 | `services/image_generation.py:101-103` | `_RETRY_MAX = 1`, `_RETRY_AFTER_CAP_SECONDS = 15.0`, `_DEFAULT = 1.0` | retry генерации | C | ок | оставить |
| 73 | `services/image_capabilities.py:528` | `prompt_limit` — динамический (T-4814) | prompt-компилятор | **B** | ок — образец «читать из модели» | не менять (эталон подхода) |
| 74 | `config/settings.py` `IMAGE_MAX_BYTES`, `IMAGE_GENERATION_MAX_ATTEMPTS`, `IMAGE_ATTEMPT_TIMEOUT_SECONDS`, `IMAGE_REQUEST_TIMEOUT_SECONDS` | ограничения картинки | image pipeline | **A/B** | защита/физика | оставить |

### 5.4. Initiative

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация |
|---|---|---|---|---|---|---|
| 75 | `services/initiative_observer.py:98-109` | `EVAL_WINDOW_BASE_MESSAGES = 10`, `MAX = 200`, `EVAL_MSG_TEXT_CAP = 300`, `DIGEST_*` (`MIN_SKIPPED=50`, `SAMPLE_MAX=200`, `PROBE_MAX=1000`, `TOTAL_CHARS=800`) | оценка уместности | **E** | `EVAL_MSG_TEXT_CAP = 300` режет реплику → инициатива может не увидеть внешний claim и не проверить его | Приоритет claim-содержащим репликам; не резать внутри факта |
| 76 | `services/initiative_observer.py:116-120` | `MAX_CHATS_PER_PASS = 3`, `MAX_EVALS_PER_PASS = 4`, `CHATS_TRACKED_MAX = 32`, `RECENT_HASHES_MAX = 16`, `TOPIC_KEYS_MAX = 24` | проход Observer | C | ок (ресурс/антифлуд) | оставить |
| 77 | `services/initiative_observer.py:196-202` | `MIN_OBSERVATION_INTERVAL_FLOOR = 600`, `MIN_EVAL_MESSAGES_FLOOR = 4`, `MIN_GAP_FLOOR_SECONDS = 1800`, `RATE_WINDOW = 3600` | антифлуд | **A** | осознанные лимиты владельца | не менять |
| 78 | `config/settings.py:1607-1614` | `INITIATIVE_MIN_GAP_SECONDS = 7200`, `MAX_REPLIES_PER_DAY = 6`, `DAY_WINDOW = 86400`, `MAX_REPLIES_PER_TOPIC = 1` | антифлуд | **A** | — | не менять |

### 5.5. Поиск/память/SQL

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация |
|---|---|---|---|---|---|---|
| 79 | `config/settings.py:2125` | `SEARCH_MAX_SYMBOLS = 4000` (+ hot `limits.search_max_symbols`) | `SearchService.research` (`search_service.py:78-96`) | **E** | Третий независимый 4000-потолок (smartmodule-путь) | Свести к одному источнику правды с P0-1 |
| 80 | `services/search_service.py:41` | `_RERANK_MIN_CHARS = 300` (fail-open при «тонком» реранке) | `_rerank_results` | C | ок | оставить |
| 81 | `services/search_aggregator.py:510-599` | `timeout_budget` (дедлайн между провайдерами) + `_truncate(max_symbols)` на выходе | поиск | **C + E** | Бюджет — правильный образец; выходной срез — наследует P0-1 | Бюджет оставить, срез убрать || 82 | `services/tool_router.py:92-94` | `_MEMORY_MAX_SYMBOLS = 3500`, `_MEMORY_FTS_LIMIT = 40`, `_MEMORY_VEC_LIMIT = 15` | `query_chat_memory` | C | ок (фильтры перенесены в SQL — комментарий `:1188-1202`) | оставить |
| 83 | `services/tool_router.py:202,204` | `_HISTORY_SEARCH_LIMIT = 80`, `_HISTORY_TOOL_TIMEOUT = 10.0` | `get_recent_history` FTS-путь | C | ок; пагинация с `cursor/remaining` — образец правильного «retrievable remainder» (`:3529-3546`) | использовать этот образец для source fetch |
| 84 | `services/tool_router.py:148-158` | `_MEMORY_LOOKUP_MAX_ITEMS_HARD = 20`, `_MESSAGE_SLICE_MAX = 5`, `_SLICE_MAX_CHARS = 240`, `_RESULT_MAX_CHARS = 4000`, `_PORTRAIT_MAX_CHARS = 600`, `_RAG_FACT_CHARS = 240` | `get_user_context` | **D** | структурированный ответ намеренно компактен | оставить (с доступом к полному сообщению) |
| 85 | `services/tool_router.py:1085` | `_DIG_GRAPH_MAX_HOP_DEPTH = 5` (+ `_DIG_PERSON_MAX_CHARS = 100`, `_DIG_YEAR_MIN = 2000`) | `dig_into_lore` | C | ок | оставить |
| 86 | `services/tool_router.py:112` | `_SUMMARIZE_TRANSCRIPT_CAP = 20000` | `_summarize_video` | **E** | Длинная расшифровка обрезается до выжимки | chunking с сохранением таймкодов |
| 87 | `services/tool_router.py:101-105,184-185` | `_SUMMARIZE_TOOL_TIMEOUT = 300`, `_LORE_TOOL_TIMEOUT = 300`, `_DOWNLOAD_TOOL_TIMEOUT = 180`, `_PROBE_TOOL_TIMEOUT = 25`, `_TOOL_DL_PENDING_TTL_SECONDS = 600` | media/lore tools | C | ок (bounded) | оставить |
| 88 | `services/tool_router.py:124` | `_DOWNLOAD_NATIVE_MAX_BYTES = 2_000_000_000` | download | **A** | защита | оставить |
| 89 | `services/database.py:7941,7968,8026-8053,8103-8118` | `LIMIT ?` (параметризованные страницы истории) + keyset-пагинация (`id < ?`/`id > ?`) | чтение истории | **C/D** | ок; остаток достижим пагинацией | оставить как образец |
| 90 | `services/database.py:6187,5194-5218` | `LIMIT ?` (выборки артефактов/прогонов) | API/UI выборки | D | ок | оставить |

### 5.6. Выход, egress, доставка

| # | Файл:строка | Ограничитель | Consumer | Класс | Последствие | Рекомендация |
|---|---|---|---|---|---|---|
| 91 | `services/smartmodule_utils.py:37` | `_CHUNK_LIMIT = 4096` | `send_chunked_reply` | **A** | физический лимит Telegram | оставить |
| 92 | `services/mca_intents.py:489`, `services/direct_chat_service.py:623` | `CHUNK_LIMIT = 4096`, `_LORE_HTML_MAX_SINGLE_CHARS = 4096` | доставка | **A** | то же | оставить |
| 93 | `services/summary_generator.py:3100-3199,4589-4648` | чанки 4096 + `max_chunks` | доставка summary | **A/D** | хвост статьи может не уйти при `max_chunks` | оставить лимит, но проверять «остаток доставлен» (§4.6: одно сообщение вместо двух) |
| 94 | `services/telegram_send.py` + `services/outgoing_guard.py:87` | `sanitize_outgoing` (режет техтеги) | отправка | **A** | защита от утечки служебного текста | оставить |
| 95 | `services/public_speech_guard.py:245-253` | `claims_total_verification` (regex-семья) | egress | **D** | Ловит только «проверил весь интернет»; не заменяет claim-guard | сохранить, добавить смысловой guard (§4.6) |

### 5.7. Экономика/воркеры/бюджеты (A/C — не трогать без владельца)

| # | Файл:строка | Ограничитель | Consumer | Класс | Примечание |
|---|---|---|---|---|---|
| 96 | `config/settings.py:1451-1459` | `MCA_TOOL_MAX_TOTAL_CALLS = 6`, `MAX_METERED_CALLS = 4`, `MAX_SAME_CALL = 2`, `CHAIN_TIMEOUT = 360`, `TRANSIENT_RETRIES_MAX = 2` | tool loop (runtime-резолв) | **A/C** | финансовые/петлевые защиты — сохранить |
| 97 | `config/settings.py` `WORKER_DAILY_LLM_TOKENS_GLOBAL/PER_CHAT`, `CHAT_GLOBAL_KEY_BUDGET_TOKENS/REQUESTS` | суточные бюджеты | workers | **A** | сохранить |
| 98 | `config/settings.py` `LLM_TIMEOUT = 30.0`, `LLM_MAX_RETRIES = 2`, `LLM_TOTAL_BUDGET = 60.0` | сетевой слой | llm_client | **B/C** | сохранить; `LLM_TOTAL_BUDGET` согласовать с SLA |
| 99 | `config/settings.py` `EMBED_CONCURRENCY_MAX`, `EMBED_BATCH_MAX = 50`, `EMBED_DEFAULT_TOKEN_LIMIT_PER_ITEM` | эмбеддинги | embed plane | **A/C** | сохранить (не пересобирать память) |
| 100 | `services/auto_budget.py:42,252` | `OUTPUT_RESERVE_FLOOR = 1024`, `_OBS_WINDOW = 512` | stage-aware резолвер | **B/C** | сохранить; расширять, не заменять |
| 101 | `services/model_capacity.py:253,315,403-406` | `OUTPUT_RESERVE_FLOOR = 1024`, `RESERVE_SAFETY_MARGIN_FLOOR = 256`, `LOCAL_ADAPTER_TTL_SECONDS = 300`, `_ADAPTER_TIMEOUT_SECONDS = 2.0`, `_FALLBACK_TTL_SECONDS = 300` | discovery | **B/C** | сохранить; discovery не должен задерживать ответ (2 с + TTL) |
| 102 | `services/safe_fetch.py:33-35,65536` | `_DEFAULT_HTML_TIMEOUT = 10.0`, `_DEFAULT_VIDEO_TIMEOUT = 240.0`, `_DEFAULT_MAX_REDIRECTS = 5`, `_READ_CHUNK = 65536`, `_DEFAULT_VIDEO_MAX = 2e9` | fetch | **A/C** | сохранить (SSRF/потоковые лимиты) |

## 6. «Никогда не удалять» (класс A) — перечень по факту кода

SSRF/URL-policy и запрет облачных фолбэков для опасных назначений (`safe_fetch.py:37-42`, `web_content_extractor.py:117-124`), лимиты размера загрузки (`_DOWNLOAD_NATIVE_MAX_BYTES`, `MCA_VISION_MAX_BYTES`), RBAC/доступ (`services/access.py`, `chat_access.py`, `permissions.py`), финансовые/суточные бюджеты (`MCA_MONEY_*`, `WORKER_DAILY_*`), антифлуд/квоты инициативы (`INITIATIVE_*`, `MIN_GAP_FLOOR_SECONDS`), защита от петель и параллелизма (`TOOL_*`, `JOB_MAX_ATTEMPTS`, breaker), телеграм-лимиты 4096, приоритет личного контента.

## 7. Что уже динамическое — не переделывать

| Механизм | Где | Что доказывает |
|---|---|---|
| stage-aware бюджеты | `services/auto_budget.py`, `services/model_capacity.py` | резолвер уже есть; расширять, а не строить третий |
| discovery окна модели | `model_capacity` адаптеры (openrouter/nanogpt/llama.cpp/ollama/vllm), TTL, `source`, WARN | §3.1 Discover закрыт |
| динамический evidence cap | `direct_execution.l2_evidence_budget_chars` (`:916-931`) | §3.3 Allocate частично закрыт |
| per-source fair allocation + limitations | `direct_execution.build_evidence_pack` (`:933-1060`) | §3.5 Preserve частично закрыт |
| пагинация с остатком | `tool_router._get_recent_history` (`:3529-3546`) | образец «retrievable remainder» для source fetch |
| бюджет поиска по дедлайну | `search_aggregator.search(timeout_budget=…)` (`:510-577`) | образец согласования таймаутов |
| output-лимит по классу модели | `mca_vision.recognize` (`:2140,2210,2330`), `image_capabilities.prompt_limit` | образец «B читается из модели» |
| Vision readiness/watchdog | `media_readiness`, `mca_vision` job/lease/breaker | §D34 закрыт |

## 8. Контракт замера (как доказывать каждое исправление)

Для каждого изменяемого лимита добавлять наблюдаемые поля (в существующие события/trace, без нового экрана):
`effective_limit`, `source` (`config|hot|env|provider|model|fallback`), `used`, `truncated`, `why` (`over_window|provider_cap|deadline|policy`), `retrievable_remainder` (bool/URL/offset), `stage`, `chat_scope`.

Минимальные доказательства:
1. **До/после** на одной фикстуре: `truncated` и `used` меняются, поведение пользователя — по контракту сценария (§10).
2. **Границы**: URL/JSON/citation ID не разрезаны (юнит-тест на `_truncate`-замену).
3. **Ретрай/дедлайн**: медленный провайдер (12–40 с) → либо успех в бюджете, либо честный `attempted_but_failed` с `why=deadline`.
4. **Не регресс A**: тесты SSRF/RBAC/квот остаются зелёными; лимиты A не меняются.
5. **Фон**: AST/импорт-тест «в summary/dream/memory нет web-модулей» (§10.19/20).
6. **Честность чисел**: `p50/p95` задержки и число вызовов до/после — из существующей аналитики, без фиктивных ожиданий.

## 9. Порядок работ и владельцы

| Очередь | Пункты | Владелец | Блокирует |
|---|---|---|---|
| **P0-a** | №3, №4, №1, №2 (анти-слепой срез, 4000/8000 → динамика, fetch с remainder) | Builder (`tool_router.py`, `web_content_extractor.py`) | §10.36–39; всё остальное evidence |
| **P0-b** | №6 (короткий официальный контент), №7–9 (таймауты из дедлайна) | Builder + DevOps | ложные «источник недоступен» (§10.9) |
| **P0-c** | №10–12 (честные fallback-cap + доля по типу задачи) | Builder + Architect (форма) | §10.38 |
| **P1** | №13–16 (L1-окно и reply-блок), №17–18 (chat_context), №24 (L1 tokens), №27–31 (tool/orchestrator окна) | Builder | качество планирования и цепочек |
| **P2-FC** | №36–44 | FC lane (не эта полоса) | §10.2/10 внутри FC |
| **P2-summary/memory** | №45–64 | Summary/memory владельцы | §10.19–27 (инвариант: не добавлять web) |
| **P2-vision/initiative/output** | №65–78, №91–95 | Vision/Initiative/UI владельцы | §10.34 |
| **P2-econ** | №96–102 | DevOps/владелец | запрещено ослаблять |

## 10. Итог

- Просканировано **597** числовых констант; в инвентарь включено **102** материальных ограничителя (остальные — пороги стиля/форматов, не влияющие на доставку информации, либо часть перечисленных групп).
- Класс **E** (удалить/динамизировать): №1–5, №13–14, №17, №31, №38, №40, №50, №51, №56, №75, №79, №81(срез), №86.
- Класс **C** (настраиваемое/динамическое с безопасным дефолтом): №7–12, №20, №24, №27–30, №34, №42, №46(частично), №47, №49, №52–55, №57–58, №62–63, №66–71, №76, №82–83, №85, №87, №89–90, №101.
- Класс **A** (сохранить): №48, №65(физика), №69, №74, №77–78, №88, №91–94, №96–100, №102.
- Класс **B** (читать из провайдера/модели): №19, №25–26, №64, №65, №73.
- Класс **D** (только preview/форма): №6(частично), №15–16, №18, №21–23, №32–33, №35, №39, №44, №60–61, №84, №90, №95.
- Смешанные строки (A/D или B/C) учтены в нескольких списках намеренно: это разные аспекты одного ограничителя (например №65 — физический output модели и одновременно форма).
- Главный вывод: **искусственная потеря evidence сосредоточена в двух файлах** (`tool_router.py`, `web_content_extractor.py`) и в **одном планировочном окне** (`direct_l1.L1_WINDOW_LINE_CHARS`). Динамические резолверы уже существуют и должны быть расширены, а не заменены.
