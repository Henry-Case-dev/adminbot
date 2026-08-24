# Исследование Epic 60: полировка direct_chat, память, чекап (T-459)

**Дата:** 2026-08-24
**Контекст:** Telegram-бот на Python / aiogram 3.29.1, LLM deepseek-v4-flash через
OpenAI-совместимый API (`POST /chat/completions`, `POST /embeddings` — `services/llm_client.py`),
БД sqlite + sqlite-vec (KNN `distance_metric=cosine`, FTS5 fallback — `services/summary_memory.py`,
`services/database.py`). Epic 60 полирует: typing-индикатор и стриминг в direct_chat/саммари,
оценку токенов контекста, MMR/дедуп/time-decay в памяти, сжатие векторов, персистентный
троттлинг/кэш в SQLite.

**Метод:** context7 был недоступен (invalid API key у MCP-сервера), поэтому все темы
исследованы через DuckDuckGo (недоступен — rate limit) → Exa (web_search + документация
и исходники). Приоритет: официальные доки (docs.aiogram.dev, core.telegram.org,
alexgarcia.xyz/sqlite-vec, api-docs.deepseek.com, docs.mem0.ai), референсные реализации
(bytedance/deer-flow, Zep/Graphiti, zeph-memory, sl-map-web/flexiq) и эмпирические измерения.

---

## 1. tiktoken: o200k_base vs cl100k_base для рус/англ, оценка токенов для deepseek-v4-flash

**ВОПРОС:** какая кодировка точнее для смешанных рус/англ текстов, «занижает» ли o200k
кириллицу, какой множитель символ→токен брать для бюджета контекста.

**ИСТОЧНИКИ:**
- https://kathane.substack.com/p/not-speaking-english-to-chatgpt-costs — замеры по 50k самых частых слов: русский `cl100k_base` = 2.74 токена/слово, `o200k_base` = 1.96 токена/слово (улучшение −28%); путь p50k 5.16 → cl100k 2.74 → o200k 1.96.
- https://chrwittm.github.io/posts/2025-05-23-estimating-tokens-per-word/index.html — Википедия, 200 статей: русский 3.613 (cl100k) vs 2.305 (o200k) токена/слово.
- https://github.com/dmitry-brazhenko/SharpToken/issues/7 — расхождение «онлайн-токенайзер 549 vs tiktoken 219» — это не баг, а разница кодировок (r50k vs cl100k); «занижение» обычно от сравнения с моделью на другой кодировке.
- https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken — маппинг encodings→models, `tiktoken.get_encoding(...)`.
- https://api-docs.deepseek.com/quick_start/token_usage/ — DeepSeek: 1 англ. символ ≈ 0.3 токена, 1 китайский ≈ 0.6; источник истины — `usage` из ответа API.
- https://arxiv.org/html/2412.19437v2 — токенизатор DeepSeek-V3: byte-level BPE, 128K vocab, оптимизирован под мультиязычность (CJK).
- https://github.com/karpathy/tiktoken (Rust-форк: crates.io/crates/tiktoken) — существует кодировка `deepseek_v3` / `deepseek_v4` вне Python-tiktoken; в Python её нет.

**ВЕРДИКТ:**
- Для оценки контекста брать **`o200k_base`** — лучшая компрессия кириллицы среди OpenAI-кодировок (1.96–2.3 токена/слово рус., против 2.74–3.6 у cl100k). Миф «o200k занижает кириллицу» неверен: o200k считает *меньше* токенов на русском, а «занижение» возникает при сравнении с r50k/p50k или фактическим токенизатором DeepSeek.
- **Множитель символ→токен для русского:** ≈ **0.3 токена/символ** (o200k, ~2.3 токена/слово ÷ ~7.4 симв./слово с пробелом); cl100k ≈ 0.45–0.5. Заявленные «0.6–0.7 токена/символ» — завышены в ~2 раза, реальны только для китайского (0.6) или p50k.
- Грубая формула бюджета: `tokens ≈ len_chars * 0.3` (рус/англ смесь, o200k), с запасом — `chars / 3`.
- Токенизатор DeepSeek (128K) не равен ни cl100k, ни o200k: для русского считает примерно как o200k±15%, для CJK — лучше. **Точный учёт только по `usage.prompt_tokens`/`completion_tokens` из ответа API** — использовать его для лимитов/метрик, а tiktoken — только для упреждающего тримминга с запасом.

**КАК ИСПОЛЬЗОВАТЬ:** в `direct_chat_service.py` заменить символьные лимиты (`CHAT_THREAD_MAX_CHARS`) на токен-бюджет: `len(enc.encode(text))` с `tiktoken.get_encoding("o200k_base")` + запас 10–15% (DeepSeek может считать больше); лимит контекста сверять с реальным `usage` из `llm_client.py`.

---

## 2. aiogram 3.29.1: sendChatAction / индикатор «печатает…»

**ВОПРОС:** точный синтаксис, продление при долгих генерациях, сброс, флуд-лимиты, BusinessConnection.

**ИСТОЧНИКИ:**
- https://docs.aiogram.dev/en/dev-3.x/utils/chat_action.html — `ChatActionSender` (контекстный менеджер): сам шлёт action каждые `interval=5.0` с, `initial_sleep=0.0`; класс-методы `.typing()`, `.upload_photo()` и т.д.; `ChatActionMiddleware`.
- https://docs.aiogram.dev/en/latest/api/enums/chat_action.html — `ChatAction.TYPING = 'typing'` (enum).
- https://docs.aiogram.dev/en/v3.28.0/_modules/aiogram/methods/send_chat_action.html — исходник `SendChatAction`: *«The status is set for 5 seconds or less (when a message arrives from your bot, Telegram clients clear its typing status)»*; параметры `chat_id`, `message_thread_id` (только топики), `business_connection_id` (только business-чаты).

**ВЕРДИКТ:**
- Прямой вызов: `await bot.send_chat_action(chat_id=..., action=ChatAction.TYPING)` — статус держится **5 секунд**.
- Для долгих генераций использовать готовый `ChatActionSender.typing(bot=bot, chat_id=chat_id, interval=5.0)` как `async with` — фоновая таска переотправляет action каждые 5 с до выхода из блока. Это и есть «продление».
- **Явного «сброса» нет** — индикатор гаснет сам: (а) через 5 с после последней отправки, (б) **немедленно при отправке ботом сообщения** (любой `send_message`/`edit` чистит typing-статус). При таймауте генерации достаточно выйти из контекстного менеджера (таска останавливается, индикатор сам погаснет ≤5 с).
- `sendChatAction` **не считается за сообщение** и не попадает в лимиты сообщений; отдельного flood-wait за него практически не бывает (максимум — стандартные лимиты API).
- `BusinessConnection` для обычных приватных/групповых чатов **не нужен** — параметр только для business-сообщений.

**КАК ИСПОЛЬЗОВАТЬ:** в `handlers/direct_chat.py` обернуть вызов сервиса: `async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id, interval=5.0): await service.generate(...)`; при `asyncio.TimeoutError`/ошибке LLM — выйти из блока и отправить сообщение об ошибке (отправка сообщения сама погасит индикатор).

---

## 3. Стриминг ответа в aiogram/Telegram (только для саммари-теста)

**ВОПРОС:** паттерн «пустое сообщение + editMessageText», лимиты правок, чанковка 4096, защита от «Message is not modified».

**ИСТОЧНИКИ:**
- https://github.com/bytedance/deer-flow/blob/e732a741/backend/app/channels/telegram.py — эталонная реализация: placeholder → инкрементальные правки; `STREAM_EDIT_MIN_INTERVAL_SECONDS = 1.0` (приват), `3.0` (группы — лимит ~20 msg/min); `TELEGRAM_MAX_MESSAGE_LENGTH = 4096`; truncate с «…»; пропуск правки при `display == last_text`; catch `retry_after` (тихий drop) и `message is not modified`; финальный edit + overflow чанками отдельными сообщениями.
- https://github.com/NousResearch/hermes-agent/pull/1782 и /issues/1786 — «Message is not modified» убивает стриминг: track `_last_sent_text`, skip идентичных правок, no-op → success; `RetryAfter` → ждать `retry_after`, 1 retry; 4096 → финализировать edit и остаток новыми сообщениями.
- https://www.conferbot.com/errors/telegram/400-bad-request-message-is-not-modified — aiogram кидает `TelegramBadRequest`, матч по подстроке `"message is not modified"` в description; это безобидная ошибка, retry бессмыслен.
- https://www.conferbot.com/limits/telegram — текст 1–4096 символов (sendMessage и editMessageText), редактирование своих сообщений без лимита по времени.
- https://github.com/aiogram/aiogram/discussions/963 — чанковка по `\n`/пробелу у границы 4096.

**ВЕРДИКТ:**
- Паттерн: `placeholder = await bot.send_message(chat_id, text="…")` → накопление чанков от LLM → `await placeholder.edit_text(accumulated)` с троттлингом.
- **Темп правок: ~1 раз/сек в привате, ~1 раз/3 сек в группах** (иначе RetryAfter); правки одного сообщения численно не лимитированы, лимит — по частоте.
- Держать `last_text`; если новый текст == последний отправленный — пропустить edit (защита от «Message is not modified»); на сам 400 с этим описанием — ловить и трактовать как success.
- `TelegramBadRequest` с `retry_after`: ждать `retry_after` с, 1 повтор, затем drop чанка (финальный edit гарантирует полноту).
- **4096:** при достижении лимита завершить текущий edit (усечь с «…» при промежуточных, финал — полный) и слать остаток отдельными сообщениями; для саммари-теста достаточно финального `edit_text` + `send_chunked_reply` остатком.
- «Message is too long» ловить отдельно и не падать — фолбэк на новые сообщения.

**КАК ИСПОЛЬЗОВАТЬ:** отдельный модуль-хелпер `stream_edit(bot, chat_id, generator)` по паттерну deer-flow (interval=1.0/3.0, кэш last_text, catch not-modified/retry-after); использовать только в тесте саммари, остальной direct_chat остаётся на `send_chunked_reply`.

---

## 4. MMR-реранкинг фактов

**ВОПРОС:** формула, λ, как применять к top-k фактам из векторного поиска.

**ИСТОЧНИКИ:**
- https://www.cs.cmu.edu/~jgc/publication/MMR_DiversityBased_Reranking_SIGIR_1998.pdf — оригинал (Carbonell & Goldstein 1998): `MMR = argmax [λ·Sim1(Di,Q) − (1−λ)·max_{Dj∈S} Sim2(Di,Dj)]`.
- https://www.elastic.co/search-labs/blog/maximum-marginal-relevance-diversify-results — реализация на Python (numpy, greedy): λ=1.0 чистая релевантность, 0.5 баланс; рекомендации: discovery λ=0.3–0.5, precision λ=0.7–0.9, research λ=0.5–0.7.
- https://learnixo.io/blog/rag-mmr — λ=0.5 рекомендованный старт, λ=0.7–0.8 лёгкая диверсификация; fetch_k=20 → k=5.
- https://reference.langchain.com/python/langchain-qdrant/vectorstores/Qdrant/max_marginal_relevance_search — дефолты LangChain: `k=4, fetch_k=20, lambda_mult=0.5`.
- https://qdrant.tech/blog/mmr-diversity-aware-reranking/ и https://docs.opensearch.org/latest/vector-search/specialized-operations/vector-search-mmr/ — серверные реализации; ⚠️ у OpenSearch/Qdrant параметр `diversity=λ` инвертирован (`(1−λ)·relevance − λ·max_sim`), не путать при чтении доков.

**ВЕРДИКТ:**
- Каноническая формула: `score(d_i) = λ·cos(q, d_i) − (1−λ)·max_{d_j ∈ S} cos(d_i, d_j)`; greedy-выбор: сначала самый релевантный, затем argmax по остатку, пока не наберём k.
- **λ = 0.5–0.7** для фактов из памяти (слегка в сторону релевантности — факты должны отвечать на запрос); λ=1 = обычный top-k.
- Кандидатов брать **fetch_k ≈ 20–50** при нужном k≈4–8 (иначе разнообразие не из чего выбирать). Сложность O(k·fetch_k) парных сравнений — тривиально.
- Диверсификацию считать на исходных float-векторах (не на квантованных — см. тему 7).

**КАК ИСПОЛЬЗОВАТЬ:** в `summary_memory.get_rag_context`/graph-поиске: KNN `k=20` → MMR (λ=0.6) → вернуть top-4–8 фактов; ~15 строк numpy-кода, юнит-тест на кластере дублей.

---

## 5. Time-decay весов связей в графе знаний

**ВОПРОС:** формула экспоненциального затухания веса от давности подтверждения, периоды полураспада, комбинация с инкрементом веса.

**ИСТОЧНИКИ:**
- https://arxiv.org/html/2501.13956 (Zep) и https://github.com/getzep/graphiti — би-темпоральная модель: у фактов `valid_at`/`invalid_at`; decay — только в ранжировании, а не удаление; противоречие → инвалидация старого ребра (`invalid_at = valid_at` нового).
- https://docs.rs/zeph-memory/latest/src/zeph_memory/graph/activation.rs.html — формула ресенси: `recency_weight = 1 / (1 + age_days · temporal_decay_rate)` (аддитивный буст, rate=0 → отключено).
- https://docs.rs/zeph-config/latest/zeph_config/memory/struct.GraphConfig.html — A-MEM: `link_weight_decay_lambda = 0.95` (мультипликативный, ×0.95 за проход), `link_weight_decay_interval_secs = 86400` (раз в сутки), применяется к не-полученным рёбрам.
- https://github.com/getzep/graphiti/issues/1571 — важный нюанс: **decay ≠ staleness**; старый факт может быть валидным, свежий — уже устаревшим; decay только для ранга, инвалидация — через valid-интервалы.

**ВЕРДИКТ:**
- Формула эффективного веса (рекомендуем): `w_eff = w_base · 0.5^(Δdays / half_life)` (или `w_base · e^(−λ·Δdays)`); пересчитывать на лету при чтении, в БД хранить `weight`, `last_confirmed_at`.
- При новом подтверждении: `weight = min(weight + increment, cap)`, `last_confirmed_at = now` (обновление «сбрасывает» затухание) — затухание считаем от `last_confirmed_at`, а не от `created_at`.
- **half_life = 30–90 дней** для персональных фактов/предпочтений (чат-бот); floor веса 0.1, чтобы не выпадали полностью; `temporal_decay_rate` Zep-стиля (1/(1+age·rate)) с rate≈0.03–0.05/день — эквивалентная альтернатива.
- Decay применять **только как множитель ранга при retrieval**, а не для удаления; устаревание фактов — через `invalid_at` (обновление факта инвалидирует старое ребро, новое вставляется со ссылкой `supersedes`).
- A-MEM-паттерн (λ=0.95/сутки к нечитанным рёбрам) подходит, если нет `last_confirmed_at`.

**КАК ИСПОЛЬЗОВАТЬ:** в `graphrag_memory`/`summary_memory`: колонки `weight`, `last_confirmed_at`, `invalid_at`; при записи подтверждённого факта `weight += 1` (cap 5) + обновить `last_confirmed_at`; при выдаче ранжировать на `weight * 0.5^(days_since_confirm / 60)`.

---

## 6. Дедуп фактов при записи (семантический)

**ВОПРОС:** пороги косинусного сходства «дубль vs обновление vs новый», практика Mem0 (add/update/delete/noop).

**ИСТОЧНИКИ:**
- https://docs.mem0.ai/core-concepts/how-it-works и https://github.com/mem0ai/mem0/blob/main/docs/migration/oss-v2-to-v3.mdx — v2: LLM решал ADD/UPDATE/DELETE/NOOP по существующим памятям; v3: **ADD-only** — дедуп только по **exact MD5 hash**, противоречия хранятся оба, решает retrieval (recency/entity сигналы), связка через `linked_memory_ids`.
- https://github.com/mem0ai/mem0/issues/4904 — предложенный порог для UPDATE-кандидата: **cosine ≥ 0.85** к ближайшей существующей памяти; ниже — ADD; хард-дедуп — MD5.
- https://github.com/mem0ai/mem0/discussions/4787 — нюанс: LLM-джудж плохо отличает «обновление» от «противоречия»; надёжнее structured-правила (same-slot) + хранение обеих версий.
- https://github.com/getzep/graphiti — дедуп рёбер внутри пары сущностей гибридным поиском + инвалидация при пересечении validity-интервалов.

**ВЕРДИКТ (рекомендуемая схема для нашего бота):**
1. **Exact/MD5** (или нормализованный текст: lowercase, strip) — дубль, `noop`.
2. **cosine ≥ 0.95** — семантический дубль: skip (и при желании `weight += 1` на существующем факте).
3. **0.85 ≤ cosine < 0.95** — «тот же слот, другое значение» (например «живу в Москве» → «живу в Сочи»): **обновление** — старый факт `invalid_at = now`, новый INSERT со ссылкой на старый (supersedes), а не перезапись.
4. **cosine < 0.85** — новый факт.
- Порог 0.85 брать для сравнения с ближайшим кандидатом из KNN по той же паре сущностей/чату (Graphiti: ограничивать поиск той же entity-pair), не по всему корпусу.
- Валидацию «это противоречие или дополнение» LLM делать не на каждую запись, а только в зоне 0.85–0.95 (дёшево и предсказуемо); хранение обеих версий безопаснее мержа.

**КАК ИСПОЛЬЗОВАТЬ:** в момент записи факта в `summary_memory`/`graphrag_memory`: KNN k=3 по факту → пороги 0.95/0.85 → noop / supersede+insert / insert; тесты на тройке «дубль, противоречие, новый».

---

## 7. sqlite-vec: сжатие векторов и `dimensions` у эмбеддингов

**ВОПРОС:** поддержка float16/int8/binary, качество поиска при int8, backfill, экономия места; можно ли запросить укороченный вектор у модели.

**ИСТОЧНИКИ:**
- https://alexgarcia.xyz/sqlite-vec/api-reference.html и /guides/scalar-quant.html, /guides/binary-quant.html — типы колонок vec0: `float[N]`, `int8[N]`, `bit[N]`; функции `vec_quantize_float16()`, `vec_quantize_int8()`, `vec_quantize_binary()`, `vec_quantize('sqf16'|'sqi8'|'bq2'|'float16'|'int8'|'bit', vec)`; `vec_type()` → `'float32'|'int8'|'bit'`. Экономия: float32 4 B/dim → float16 2 B → int8 1 B → bit 1/8 B (до 32×).
- https://alexgarcia.xyz/sqlite-vec/guides/binary-quant.html — паттерн двух колонок: полный float-вектор + `coarse` (binary/int8); поиск: coarse-match `LIMIT k*8` → реранк точным расстоянием по полному вектору. BQ хорош только для моделей, обученных под BQ (nomic-embed, mxbai), либо на нормализованных векторах.
- https://github.com/asg017/sqlite-vec — pre-v1 (ломающие изменения возможны); vec0 = brute-force, «fast enough» для малых объёмов.
- https://alexgarcia.xyz/sqlite-vec/features/vec0.html — metadata/partition/auxiliary колонки; ALTER у виртуальных таблиц нет → backfill через новую таблицу.
- https://developers.openai.com/api/docs/guides/embeddings + https://supabase.com/blog/matryoshka-embeddings + https://community.openai.com/t/it-looks-like-text-embedding-3-embeddings-are-truncated-scaled-versions-from-higher-dim-version/602276 — `dimensions` поддерживается только OpenAI text-embedding-3; суть — Matryoshka: усечение префикса + **ренормализация**; произвольный dim можно получить офлайн из полного вектора (truncate + normalize).

**ВЕРДИКТ:**
- **Рекомендуем int8** (`vec_quantize_int8` / колонка `int8[dim]`): 4× экономия, падение качества recall ~1–3% на нормализованных векторах — приемлемо для фактов. float16 — почти без потерь (2×). binary — только с двухпроходной схемой (coarse recall + точный реранк), иначе рискованно.
- Схема: хранить **одну float-колонку как канон + одну int8-колонку для KNN**; поиск по int8 → реранк топ-кандидатов точной cosine по float (наш KNN уже `distance_metric=cosine`).
- **Backfill:** virtual table нельзя ALTER → создать новую vec0-таблицу с обеими колонками, `INSERT INTO ... SELECT id, f, vec_quantize_int8(f)`, переименовать, дропнуть старую (по образцу R46-8 re-embedding в `summary_memory.py`).
- **`dimensions` у провайдера:** параметр есть только у OpenAI text-embedding-3; для нашего OpenAI-совместимого deepseek-эндпоинта **не гарантирован** — не полагаться. Если нужен короткий вектор: один раз проверить поддержку параметра пробным запросом; иначе брать полный вектор и усекать+ренормализовать локально (валидно только для Matryoshka-обученных моделей; при обычной модели качество падает резко — поэтому каноном хранить полный dim).

**КАК ИСПОЛЬЗОВАТЬ:** миграция Epic 60: добавить int8-колонку в vec0-таблицы фактов, backfill через rebuild, KNN по int8 с реранком по float; `EMBEDDING_DIM` не менять, `dimensions` у эндпоинта не использовать (или опционально после пробы).

---

## 8. TTL + LRU в SQLite (персистентный троттлинг, кэш эмбеддингов)

**ВОПРОС:** надёжные схемы хранения кэша/состояний с TTL и LRU без внешних зависимостей.

**ИСТОЧНИКИ:**
- https://nickmccarty.me/blog/search-cache.html — канон lazy-TTL: таблица `(key, value, expires_at)` + индекс по `expires_at`; `get()`: если протух — DELETE и вернуть None; `put()`: `INSERT ... ON CONFLICT DO UPDATE` + ленивый sweep `DELETE WHERE expires_at < now` (дёшево благодаря индексу).
- https://docs.rs/cameo/latest/src/cameo/cache/sqlite.rs.html — LRU-кап на записи: `DELETE WHERE rowid NOT IN (SELECT rowid ORDER BY last_used_at DESC LIMIT N)`; периодический purge каждые ~1000 чтений; WAL + отдельные read/write соединения.
- https://github.com/tuist/tuist/pull/9499 — `last_accessed_at` обновлять на чтении батчами (буфер), не на каждый read (иначе каждый GET = write); выселение по «не трогали N дней» (30).
- https://github.com/jkelin/cache-sqlite-lru-ttl и https://deepwiki.com/joaosavi/nexotv/4.1-sqlite-persistent-cache — схемы `key/value/expires_at` + периодический GC (6 ч) + VACUUM (неделя).

**ВЕРДИКТ:**
- Единая схема: `cache(key TEXT PRIMARY KEY, value BLOB/TEXT, expires_at INTEGER, last_used_at INTEGER)` + индексы `idx_expires(expires_at)`, `idx_last_used(last_used_at)`.
- **TTL:** лениво — при чтении протухшего DELETE; плюс sweep на каждой записи (`DELETE WHERE expires_at < now`), плюс опциональный фоновый purge раз в N часов (для бота хватит ленивого).
- **LRU:** при записи, если `COUNT(*) > N`: `DELETE WHERE key NOT IN (SELECT key ORDER BY last_used_at DESC LIMIT N)`; `last_used_at` при чтении обновлять лениво/батчами (например, только если старше 60 с — избежать write-per-read).
- WAL + один writer (см. тему 9); для `_bot_replies` (сейчас in-memory LRU 200/TTL 3600) — перенос в эту таблицу даёт переживание рестарта.

**КАК ИСПОЛЬЗОВАТЬ:** таблица `direct_chat_cache`/`embed_cache` в `database.py`; заменить in-memory `_bot_replies` и throttle-состояния на персистентные; кэш эмбеддингов — key = SHA-256(text), TTL 30 дней, LRU-cap 50k.

---

## 9. Персистентный cooldown / token-bucket в БД

**ВОПРОС:** паттерны rate limiting в SQLite, переживающего рестарт; атомарность, гонки в asyncio+aiogram.

**ИСТОЧНИКИ:**
- https://docs.rs/sl-map-web/latest/src/sl_map_web/rate_limit.rs.html — **эталон:** весь refill+consume в одном атомарном UPSERT:
  `INSERT INTO rate_buckets(category, user_id, tokens, last_refill_at) VALUES(..., capacity-1, now) ON CONFLICT(category,user_id) DO UPDATE SET tokens = MIN(capacity, tokens + elapsed*refill_rate) - 1, last_refill_at = excluded.last_refill_at WHERE MIN(capacity, ...) >= 1 RETURNING tokens`; нет строки в RETURNING → отказ; Retry-After = `seconds_per_token`.
- https://docs.rs/flexiq-core/latest/src/flexiq_core/storage/sqlite/rate_limits.rs.html — альтернатива: `BEGIN IMMEDIATE` + read-refill-consume-write внутри одной транзакции (фиксит deferred-lock-upgrade → SQLITE_BUSY).
- https://github.com/iiizzzyyy/promptmetrics/issues/35 — анти-паттерн: SELECT потом UPDATE в отдельных шагах = гонка (лимиты превышаются под нагрузкой); фикс — UPSERT.
- https://emschwartz.me/psa-your-sqlite-connection-pool-might-be-ruining-your-write-performance/ и https://www.productionhardening.org/wal-optimization-concurrency-tuning/async-execution-patterns/ — SQLite single-writer; WAL + `synchronous=NORMAL` + `busy_timeout`; **не держать await внутри write-транзакции** (лок живёт через yield); один writer-connection, `BEGIN IMMEDIATE`.

**ВЕРДИКТ:**
- **Один атомарный UPSERT с условным UPDATE** (sl-map-web) — лучший паттерн: нет гонок даже в много-процессном окружении, не нужен BEGIN IMMEDIATE, идеален для aiosqlite. Логика fixed-window/cooldown выражается той же конструкцией (capacity=1, refill = 1/cooldown).
- В asyncio+aiogram один event loop → реального параллелизма нет, но **await'ы переплетаются**: SELECT-then-UPDATE разорвётся между шагами → только атомарный UPSERT; aiosqlite сериализует записи сам (SQLite single-writer).
- Прагмы на соединении: `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `synchronous=NORMAL`; не делать `await` внутри транзакций (или транзакции только через один UPSERT-стейтмент).
- Retry-After клиенту: время до следующего токена (`(1 - tokens) * seconds_per_token`).

**КАК ИСПОЛЬЗОВАТЬ:** таблица `rate_buckets(key TEXT PK, tokens REAL, last_refill REAL)`; `DirectChatThrottle.try_acquire()` переписать с in-memory token-bucket на UPSERT (логика и тесты сохраняются, состояние переживает рестарт); для чекапа — персистентный cooldown той же конструкцией.

---

## 10. (Бонус) aiogram: получение текста сообщения с entities и вырезание mention

**ВОПРОС:** как безопасно убрать `@bot`/mention-сущности из текста запроса.

**ИСТОЧНИКИ:**
- https://docs.aiogram.dev/en/latest/api/types/message%5Fentity.html — `MessageEntity(type, offset, length, ...)`, метод **`entity.extract_from(text) → str`** (вырезает подстроку по offset/length).
- https://github.com/aiogram/aiogram/pull/945 — в aiogram 3.x метод переименован `extract()` → **`extract_from()`**; `get_text()` удалён.
- https://github.com/aiogram/aiogram/blob/f217c6ad/tests/test_api/types/test_message_entity.py — `MessageEntity(type="hashtag", length=4, offset=5).extract_from("#foo #bar #baz") == "#bar"`.
- https://stackoverflow.com/questions/79133570/aiogram-does-not-display-the-mentioned-user-in-entities — у `mention` нет `user`-поля (только у `text_mention`); юзернейм — только из текста.

**ВЕРДИКТ:**
- Текст: `message.text` (или `message.caption`); entities — `message.entities` (сортированы по offset).
- Вырезать сущности безопасно **по offset/length, а не по строковому матчу**: собрать интервалы entity типа `mention` (и опц. `text_mention`, `bot_command`) и вырезать справа-налево, затем `strip()`; `entity.extract_from(text)` отдаёт саму подстроку (для проверки «это наш бот»), сам текст режется по slice'ам.
- `message.html_text`/`md_text` НЕ использовать для этой задачи (маскировка markdown не подходит для среза по raw-индексам).

**КАК ИСПОЛЬЗОВАТЬ:** в `direct_chat.py`/`checkup.py` для `/persona @bot ...`: удалить интервалы mention-сущностей по offset/length из `message.text`, проверив `extract_from(...).lstrip('@').lower() == bot_username`.

---

## Сводная таблица решений

| # | Тема | Ключевое решение | Параметры |
|---|------|------------------|-----------|
| 1 | Подсчёт токенов | `tiktoken` + `o200k_base` для упреждающего тримминга; лимиты — по `usage` из API | рус. ≈ 0.3 токена/символ (o200k), запас 10–15%; НЕ 0.6–0.7 |
| 2 | «Печатает…» | `ChatActionSender.typing(bot, chat_id)` в `async with` | interval=5.0 c; сброс автоматический при отправке сообщения; BusinessConnection не нужен |
| 3 | Стриминг | placeholder + `edit_text` по чанкам, только для саммари-теста | 1 edit/сек (приват), 3 сек (группы); лимит 4096; catch not-modified/retry-after |
| 4 | MMR | greedy: `λ·sim(q,d) − (1−λ)·max_sim(d,S)` | λ=0.6; fetch_k=20–50 → k=4–8 |
| 5 | Time-decay | `w_eff = weight · 0.5^(Δdays/half_life)`, пересчёт от `last_confirmed_at` | half_life 60 дней; +1 вес при подтверждении (cap 5), floor 0.1; decay только в ранге, устаревание — `invalid_at` |
| 6 | Дедуп фактов | hash → cosine-пороги → supersede | ≥0.95 noop, 0.85–0.95 обновление (invalidate + insert), <0.85 новый факт |
| 7 | Сжатие векторов | int8-колонка для KNN + float-канон с реранком; `dimensions` API не полагаться | `vec_quantize_int8`; экономия 4×; backfill = rebuild таблицы; Matryoshka: truncate+renormalize |
| 8 | TTL+LRU | одна таблица `(key, value, expires_at, last_used_at)` | ленивый sweep при чтении/записи, cap N через `NOT IN ... LIMIT N`; WAL |
| 9 | Token-bucket в БД | один атомарный UPSERT c `ON CONFLICT DO UPDATE ... WHERE tokens>=1 RETURNING` | Refill по elapsed; Retry-After = (1−tokens)·sec_per_token; busy_timeout=5000 |
| 10 | Вырезка mention | `MessageEntity.extract_from(text)` + вырезка по offset/length справа-налево | типы `mention`/`text_mention`/`bot_command`; по индексам, не по подстроке |
