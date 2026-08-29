"""Epic 85 (84.12.2) — каталог-реестр ВСЕХ регулируемых параметров Settings.

ЕДИНЫЙ источник для:
  * scripts/migrate_env_to_pg.py (T-637) — полный экспорт .env → bot_settings;
  * GET /api/roles/tree (T-640) — дерево прав конструктора ролей;
  * ConfigCache.init() — belt-and-suspenders самозасев дефолтов (84.12.3);
  * фронта (вкладки админки) — дублирование ЗАПРЕЩЕНО (84.12.2).

Каждая запись ParamSpec: settings-поле (или None для env-only/PG-only ключей),
env-имя, категория bot_settings (prompts|models|keys|limits|flags|reactions|
content; None = infra — НЕ мигрируется и НЕ попадает в дерево прав), русский
заголовок, тип (str|int|float|bool|json), флаг секретности (R17: значения
секретов никогда не печатаются), опциональный code_source для prompts
(«module.attr» — код-канон, в .env их нет; сид при старте ConfigCache).

Ключ в PG — dotted: {category}.{snake_name} (84.12.1).
"""
import dataclasses
import json
import logging

from config.settings import Settings

logger = logging.getLogger(__name__)

# ── Канонические категории bot_settings (84.12.1) ──────────────────────────
CATEGORY_PROMPTS = "prompts"
CATEGORY_MODELS = "models"
CATEGORY_KEYS = "keys"
CATEGORY_LIMITS = "limits"
CATEGORY_FLAGS = "flags"
CATEGORY_REACTIONS = "reactions"
CATEGORY_CONTENT = "content"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_PROMPTS,
    CATEGORY_MODELS,
    CATEGORY_KEYS,
    CATEGORY_LIMITS,
    CATEGORY_FLAGS,
    CATEGORY_REACTIONS,
    CATEGORY_CONTENT,
)


@dataclasses.dataclass(frozen=True)
class ParamSpec:
    """Одна запись реестра параметров."""

    settings_field: str | None   # имя поля Settings (None → env-only/PG-only)
    env_name: str | None         # имя env-переменной (None → PG-only сид)
    category: str | None         # категория bot_settings; None = infra
    title_ru: str
    type: str                    # str | int | float | bool | json
    secret: bool = False
    code_source: str | None = None  # "module.attr" — код-канон (prompts)
    pg_id: str | None = None        # явный PG-ключ (PG-only записи)

    @property
    def pg_key(self) -> str:
        """Ключ bot_settings: {category}.{snake_name}."""
        if self.pg_id:
            return self.pg_id
        base = (self.settings_field or self.env_name or "").lower()
        return f"{self.category}.{base}" if self.category else base

    @property
    def migratable(self) -> bool:
        """Экспортируется в bot_settings миграцией (категория задана)."""
        return self.category is not None


# ── prompts: PG-only сиды из код-канонов (84.12.1: «в .env их НЕТ») ────────
# (pg_id, title_ru, code_source)
_PROMPTS: list[tuple] = [
    ("prompts.factcheck_system_prompt", "Системный промпт фактчека",
     "services.factcheck_prompts.FACTCHECK_SYSTEM_PROMPT"),
    ("prompts.search_system_prompt", "Системный промпт поиска",
     "services.search_prompts.SEARCH_SYSTEM_PROMPT"),
    ("prompts.summary_system_prompt", "Системный промпт саммари",
     "services.summary_prompts.SYSTEM_PROMPT"),
    ("prompts.checkup_system_prompt", "Системный промпт чекапа",
     "services.checkup_prompts.CHECKUP_SYSTEM_PROMPT"),
    ("prompts.direct_chat_system_prompt", "Системный промпт прямого чата",
     "services.chat_prompts.CHAT_SYSTEM_PROMPT"),
    ("prompts.extract_system_prompt", "Промпт извлечения фактов (граф)",
     "services.summary_prompts.EXTRACT_PROMPT"),
    ("prompts.compress_system_prompt", "Промпт сжатия истории (L3)",
     "services.summary_prompts.COMPRESS_PROMPT"),
    ("prompts.youtube_system_prompt", "Системный промпт пересказа YouTube",
     "services.youtube_prompts.YOUTUBE_SYSTEM_PROMPT"),
    ("prompts.webpage_system_prompt", "Системный промпт пересказа веб-страниц",
     "services.web_prompts.WEBPAGE_SYSTEM_PROMPT"),
]

# ── content: PG-only ключи (84.13.2) ────────────────────────────────────────
_CONTENT: list[tuple] = [
    ("content.info_how_it_works", "Текст «Как это работает» (rich-HTML)"),
]

# ── infra: остаётся в .env (84.12.1); category=None — НЕ мигрируется ───────
# (field, title_ru, type, secret)
_INFRA: list[tuple] = [
    ("API_TOKEN", "Токен Telegram-бота", "str", True),
    ("DB_PATH", "Путь к SQLite-БД", "str", False),
    ("MEDIA_BASE", "Корневая папка медиа", "str", False),
    ("COBALT_API_URL", "URL self-hosted cobalt", "str", False),
    ("LOCAL_BOT_API_URL", "URL локального telegram-bot-api", "str", False),
    ("TELEGRAM_API_FILES_DIR", "Хост-путь data-dir telegram-bot-api", "str", False),
    ("DOWNLOAD_DIR", "Папка скачанных файлов", "str", False),
    ("INFO_TEXT_FILE", "Путь к info_text.md", "str", False),
    ("CHECKUP_JOURNALCTL_CMD", "Команда journalctl для чекапа", "str", False),
]

# env-only infra (вне dataclass Settings): compose/инфраструктура Epic 85
# (env_name, title_ru, type, secret)
_INFRA_ENV_ONLY: list[tuple] = [
    ("POSTGRES_DSN", "DSN PostgreSQL", "str", True),
    ("POSTGRES_PASSWORD", "Пароль PostgreSQL", "str", True),
    ("POSTGRES_DB", "Имя БД postgres", "str", False),
    ("POSTGRES_USER", "Пользователь postgres", "str", False),
    ("WEB_PORT", "Порт веб-админки (uvicorn)", "int", False),
    ("LOG_RING_MAX_ENTRIES", "Размер ring-buffer логов", "int", False),
    ("UPTIME_EVENTS_RETENTION_HOURS", "Ретенция uptime_events, часов", "int", False),
    ("SENTRY_DSN", "Sentry DSN", "str", True),
    ("LOGTAIL_SOURCE_TOKEN", "Logtail source token", "str", True),
    ("TELEGRAM_API_ID", "API ID my.telegram.org", "str", True),
    ("TELEGRAM_API_HASH", "API hash my.telegram.org", "str", True),
    ("COBALT_HTTP_PROXY", "Исходящий HTTP-прокси cobalt", "str", True),
]

# ── keys: секреты (ключи LLM/поиск/транскриб + прокси + cookies, 84.12.1) ──
# (field, title_ru, type, secret)
_KEYS: list[tuple] = [
    ("LLM_API_KEY", "Ключ LLM (apinet.cloud)", "str", True),
    ("LLM_FALLBACK_API_KEY", "Ключ фоллбэк-LLM", "str", True),
    ("TAVILY_API_KEY", "Ключ Tavily", "str", True),
    ("EXA_API_KEY", "Ключ Exa", "str", True),
    ("GROQ_API_KEY", "Ключ Groq", "str", True),
    ("OPENROUTER_API_KEY", "Ключ OpenRouter", "str", True),
    ("CHECKUP_BETTERSTACK_SQL_USER", "Пользователь Betterstack SQL", "str", True),
    ("CHECKUP_BETTERSTACK_SQL_PASSWORD", "Пароль Betterstack SQL", "str", True),
    ("YOUTUBE_TRANSCRIPT_PROXY_URL", "Прокси-URL YouTube (user:pass)", "str", True),
    ("YOUTUBE_TRANSCRIPT_PROXY_USERNAME", "Логин resident-прокси Webshare", "str", True),
    ("YOUTUBE_TRANSCRIPT_PROXY_PASSWORD", "Пароль resident-прокси Webshare", "str", True),
    ("YOUTUBE_TRANSCRIPT_PROXY_DOMAIN", "Домен прокси-оверрайда", "str", False),
    ("YOUTUBE_TRANSCRIPT_PROXY_PORT", "Порт прокси-оверрайда", "str", False),
    ("YOUTUBE_TRANSCRIPT_PROXY_LOCATIONS", "CSV-коды стран Webshare", "str", False),
    ("YOUTUBE_TRANSCRIPT_PROXY_RETRIES", "Retries_when_blocked Webshare", "str", False),
    ("YOUTUBE_COOKIES_FILE", "Путь к cookies-файлу YouTube (Netscape)", "str", True),
]

# ── models: провайдеры/модели/таймауты/ретраи (не секреты) ──────────────────
# (field, title_ru, type)
_MODELS: list[tuple] = [
    ("LLM_BASE_URL", "Базовый URL LLM API", "str"),
    ("LLM_MODEL_NAME", "Модель LLM", "str"),
    ("EMBEDDING_MODEL_NAME", "Модель эмбеддингов", "str"),
    ("EMBEDDING_DIM", "Размерность эмбеддингов", "int"),
    ("LLM_TIMEOUT", "Таймаут запроса LLM, сек", "float"),
    ("LLM_MAX_RETRIES", "Число ретраев LLM", "int"),
    ("LLM_RETRY_BACKOFF_BASE", "База экспоненциального backoff", "float"),
    ("LLM_RETRY_BACKOFF_CAP", "Потолок backoff, сек", "float"),
    ("LLM_RETRY_JITTER_MAX", "Максимальный jitter, сек", "float"),
    ("LLM_TOTAL_BUDGET", "Жёсткий дедлайн всей попытки, сек", "float"),
    ("LLM_FALLBACK_BASE_URL", "URL фоллбэк-провайдера", "str"),
    ("LLM_FALLBACK_MODEL", "Модель фоллбэк-провайдера", "str"),
    ("LLM_FALLBACK_MAX_RETRIES", "Ретраи фоллбэк-цепочки", "int"),
    ("LLM_FALLBACK_TIMEOUT_SECONDS", "Таймаут фоллбэка, сек", "float"),
    ("LLM_CB_FAILURE_THRESHOLD", "Порог фейлов Circuit Breaker", "int"),
    ("LLM_CB_COOLDOWN_SECONDS", "Кулдаун Circuit Breaker, сек", "float"),
    ("CHECKUP_BETTERSTACK_SQL_HOST", "Хост Betterstack SQL API", "str"),
    ("CHECKUP_BETTERSTACK_SQL_TABLE", "Префикс сорса Betterstack", "str"),
    ("CHECKUP_BETTERSTACK_SQL_QUERY", "SQL-оверрайд чекапа", "str"),
    ("TOKENIZER_ENCODING", "Кодировка tiktoken", "str"),
    ("TOKEN_SAFETY_MULTIPLIER", "Множитель безопасности токенов", "float"),
    ("GROQ_TIMEOUT", "Таймаут Groq, сек", "float"),
    ("GROQ_MAX_CONCURRENCY", "Очередь Groq (semaphore)", "int"),
    ("GROQ_MIN_INTERVAL", "Мин. интервал между запросами Groq, сек", "float"),
    ("GROQ_MAX_RETRIES", "Число ретраев Groq", "int"),
    ("OPENROUTER_TIMEOUT", "Таймаут OpenRouter, сек", "float"),
]

# ── flags: рубильники модулей ───────────────────────────────────────────────
# (field, title_ru)
_FLAGS: list[tuple] = [
    ("SUMMARY_ENABLED", "Модуль саммари включён"),
    ("DIRECT_CHAT_BOTWORD_ENABLED", "Триггер «бот»-семьи в чате"),
    ("ENABLE_VOICE_TRANSCRIPTION", "Транскрипция голосовых"),
    ("GRAPH_RAG_ENABLED", "GraphRAG-извлечение при архивации"),
    ("SMART_CACHE_ENABLED", "Exact Match Cache"),
    ("THROTTLE_PERSISTENT_ENABLED", "Персистентный троттлинг"),
    ("DOWNLOAD_ENABLED", "Скачивание видео («скачай <url>»)"),
    ("YTDLP_FOR_YOUTUBE", "yt-dlp для YouTube (вместо cobalt)"),
    ("CHAT_SILENCE_ENABLED", "Стачка кулдаунов → молчание"),
    ("CHAT_STYLE_ANCHORS_ENABLED", "Стилевые якоря"),
    ("CHAT_MOOD_ENABLED", "Определение настроения собеседника"),
    ("CHAT_RUNNING_SUMMARY_ENABLED", "Бегущий конспект"),
    ("CHAT_DEDUP_ENABLED", "Дедуп одинаковых текстов подряд"),
    ("CHAT_CONTEXT_BUDGETS_ENABLED", "Бюджеты контекста direct_chat"),
    ("SUMMARY_STREAMING_ENABLED", "Стриминг саммари (placeholder + edit)"),
    ("TYPING_INDICATOR_ENABLED", "Индикатор «печатает…»"),
    ("SEARCH_RERANK_ENABLED", "LLM-реранкинг поиска"),
    ("CHECKUP_MEMORY_METRICS_ENABLED", "Метрики здоровья памяти в чекап"),
    ("GRAPH_DEDUP_ENABLED", "Дедуп фактов при записи"),
    ("GRAPH_EPISODE_MERGE_ENABLED", "Слияние повторяющихся эпизодов"),
    ("GRAPH_TIME_DECAY_ENABLED", "Time-decay весов фактов"),
    ("GRAPH_USER_QUOTA_ENABLED", "Квота памяти на человека"),
    ("GRAPH_FACT_TOUCH_ENABLED", "TTL+LRU touch фактов"),
    ("GRAPH_REVIEW_ENABLED", "Периодический пересмотр фактов"),
    ("VEC_INT8_ENABLED", "int8-сжатие векторов"),
    ("GRAPH_MMR_ENABLED", "MMR-разнообразие RAG"),
    ("MEMORY_BACKUP_ENABLED", "Ежедневный бэкап памяти"),
    ("EMBED_CACHE_ENABLED", "Кэш эмбеддингов"),
    ("DB_WAL_CHECKPOINT_ENABLED", "WAL-checkpoint SQLite"),
    ("LLM_CB_ENABLED", "Circuit Breaker direct_chat"),
    ("COMMON_WORK_MEDIA_ENABLED", "Медиа work-подсервиса"),
    ("COMMON_MEDIA_ENABLED", "Все common-медиа"),
    ("OLYA_ENABLED", "Сервис Оли"),
    ("OLYA_CAPTION_ENABLED", "Капшн ответов Оли"),
    ("OLYA_REPOST_ENABLED", "Ответ репостом Оли"),
    ("OLYA_ALWAYS_SEND", "Реакция на ВСЕ видео Оли"),
    ("OLYA_CAPTION_MENTION_ENABLED", "Триггер @SaveAsBot в капшне"),
    ("MIMIC_FORWARDS_ENABLED", "Мимикрировать репосты"),
    ("ALAN_REPLIES_ENABLED", "Reply-блок Алана"),
    ("DEAD_PAGE_POST_ON_JOIN", "Триггер dead page при join"),
    ("SUMMARY_ADMIN_ONLY", "Саммари только для админа"),
]

# ── limits: числа/таймауты/кулдауны/бюджеты ─────────────────────────────────
# (field, title_ru, type)
_LIMITS: list[tuple] = [
    ("ALAN_REPLY_INTERVAL", "Интервал ответа Алана (сообщений)", "int"),
    ("KOSTIK_REPLY_PROBABILITY", "Вероятность ответа Костика", "float"),
    ("DEAD_PAGE_CAPTION_MAX_CHARS", "Макс. символов капшна dead page", "int"),
    ("DEAD_PAGE_COOLDOWN", "Кулдаун dead page, сек", "float"),
    ("DEAD_PAGE_MAX_FORWARD_RETRIES", "Ретраи подбора dead page", "int"),
    ("GIF_INTERVAL", "Интервал гифки (сообщений)", "int"),
    ("ALAN_GREETING_COOLDOWN", "Кулдаун приветствия Алана, сек", "int"),
    ("ALAN_SILENCE_GREETING_HOURS", "Порог тишины Алана, часов", "float"),
    ("SLAVIC_PHOTO_INTERVAL", "Интервал фото Славика (сообщений)", "int"),
    ("COMMON_COOLDOWN", "Общий кулдаун common-медиа, сек", "float"),
    ("DANGER_COOLDOWN", "Кулдаун danger-медиа, сек", "float"),
    ("SELFDEV_COOLDOWN", "Кулдаун selfdev, сек", "float"),
    ("WORK_COOLDOWN", "Кулдаун work, сек", "float"),
    ("MIMIC_MIN_WORDS", "Мин. слов для мимикрии", "int"),
    ("MIMIC_COOLDOWN", "Кулдаун мимикрии, сек", "float"),
    ("SLAVIK_MIMIC_MIN_WORDS", "Мин. слов для мимикрии Славика", "int"),
    ("SLAVIK_MIMIC_COOLDOWN", "Кулдаун мимикрии Славика, сек", "float"),
    ("OLYA_COOLDOWN", "Кулдаун Оли, сек", "float"),
    ("SUMMARY_WINDOW_HOURS", "Окно генерации саммари, часов", "float"),
    ("FULL_MEMORY_RETENTION_DAYS", "Хранение сырых сообщений, дней", "int"),
    ("ARCHIVE_MEMORY_RETENTION_DAYS", "Срок жизни архивных фактов, дней", "int"),
    ("MAX_SUMMARY_PARTS", "Макс. частей ответа саммари", "int"),
    ("SUMMARY_TIMEZONE", "Часовой пояс саммари", "str"),
    ("SUMMARY_THROTTLE_SECONDS", "Троттлинг /summary, сек", "float"),
    ("SUMMARY_CHUNK_DELAY", "Пауза между чанками саммари, сек", "float"),
    ("SUMMARY_MAX_WINDOW_MESSAGES", "Кап окна L1 (сообщений)", "int"),
    ("SUMMARY_MAX_MESSAGE_CHARS", "Кап одного сообщения, символов", "int"),
    ("SUMMARY_MAX_CONTEXT_CHARS", "Кап контекста, символов", "int"),
    ("SUMMARY_RAG_L2_LIMIT", "Лимит RAG L2", "int"),
    ("SUMMARY_RAG_L3_LIMIT", "Лимит RAG L3", "int"),
    ("SUMMARY_COMPRESS_BATCH", "Размер пачки сжатия L3", "int"),
    ("SUMMARY_RETRY_ONCE_PAUSE", "Пауза повтора генерации, сек", "float"),
    ("SUMMARY_STREAM_EDIT_INTERVAL_PRIVATE", "Темп стрим-правок (приват)", "float"),
    ("SUMMARY_STREAM_EDIT_INTERVAL_GROUP", "Темп стрим-правок (группа)", "float"),
    ("GRAPH_EDGE_WEIGHT_INCREMENT", "Инкремент веса ребра графа", "int"),
    ("GRAPH_TOP_EDGES_LIMIT", "Справок-рёбер в саммари", "int"),
    ("GRAPH_EXTRACT_MAX_TRIPLETS", "Макс. триплетов за extraction", "int"),
    ("GRAPH_FACT_TTL_DAYS", "TTL фактов графа, дней", "int"),
    ("GRAPH_RAG_FACTS_LIMIT", "Top-K фактов RAG", "int"),
    ("GRAPH_RAG_CONTEXT_MAX_CHARS", "Потолок XML-контекста RAG", "int"),
    ("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", "Ретраи memorize-батча", "int"),
    ("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", "Backoff memorize-батча, сек", "float"),
    ("SEARCH_MAX_SYMBOLS", "Длина ответа поиска, символов", "int"),
    ("FACTCHECK_MAX_SYMBOLS", "Длина ответа фактчека, символов", "int"),
    ("SEARCH_COOLDOWN_SECONDS", "Кулдаун поиска, сек", "float"),
    ("FACTCHECK_COOLDOWN_SECONDS", "Кулдаун фактчека, сек", "float"),
    ("YOUTUBE_MAX_SYMBOLS", "Лимит YouTube, символов", "int"),
    ("WEBPAGE_MAX_SYMBOLS", "Лимит веб-страниц, символов", "int"),
    ("YOUTUBE_COOLDOWN_SECONDS", "Кулдаун YouTube, сек", "float"),
    ("WEBPAGE_COOLDOWN_SECONDS", "Кулдаун веб-страниц, сек", "float"),
    ("CHECKUP_COOLDOWN_SECONDS", "Кулдаун чекапа, сек", "float"),
    ("CHECKUP_MAX_SYMBOLS", "Длина ответа чекапа, символов", "int"),
    ("CHECKUP_MAX_INPUT_SYMBOLS", "Потолок входа чекапа, символов", "int"),
    ("INFO_COOLDOWN_SECONDS", "Кулдаун /info, сек", "float"),
    ("CHAT_GLOBAL_CONTEXT_LIMIT", "Сообщений фона <Global_Context>", "int"),
    ("CHAT_BURST_LIMIT", "Обращений подряд до кулдауна", "int"),
    ("CHAT_COOLDOWN_SECONDS", "Кулдаун direct_chat, сек", "float"),
    ("CHAT_DIRECT_REPLY_TTL_DAYS", "TTL bot_direct_reply-фактов, дней", "int"),
    ("CHAT_GLOBAL_CONTEXT_MAX_CHARS", "Потолок <Global_Context>, символов", "int"),
    ("CHAT_THREAD_MAX_DEPTH", "Глубина <Conversation_Thread>", "int"),
    ("CHAT_THREAD_MAX_CHARS", "Потолок <Conversation_Thread>, символов", "int"),
    ("SMART_CACHE_TTL_SECONDS", "TTL smart_cache, сек", "int"),
    ("SMART_CACHE_MAX_ROWS", "Потолок строк smart_cache", "int"),
    ("CHAT_LOCK_WAIT_SECONDS", "Таймаут per-chat замка, сек", "float"),
    ("CHAT_LOCK_MAX_ENTRIES", "Потолок словаря замков", "int"),
    ("GRAPH_DEDUP_SIMILARITY_HIGH", "Порог дедупа HIGH", "float"),
    ("GRAPH_DEDUP_SIMILARITY_LOW", "Порог дедупа LOW", "float"),
    ("GRAPH_DEDUP_WEIGHT_BONUS", "Бонус веса при подтверждении", "float"),
    ("GRAPH_UNCONFIRMED_RETENTION_DAYS", "Ретенция unconfirmed, дней", "int"),
    ("MEMORY_BACKUP_KEEP", "Ротация бэкапов (файлов)", "int"),
    ("MEMORY_BACKUP_HOUR", "Час бэкапа (HH:MM)", "str"),
    ("EMBED_CACHE_TTL_DAYS", "TTL кэша эмбеддингов, дней", "int"),
    ("EMBED_CACHE_MAX_ROWS", "Потолок строк кэша эмбеддингов", "int"),
    ("DB_WAL_CHECKPOINT_HOURS", "Период WAL-checkpoint, часов", "int"),
    ("FACTCHECK_CONTEXT_MESSAGES", "Окно контекста фактчека (сообщений)", "int"),
    ("SEARCH_CONTEXT_MESSAGES", "Окно контекста поиска (сообщений)", "int"),
    ("CHAT_CONTEXT_FILL_RATIO", "Порог заполнения окна (доля)", "float"),
    ("CHAT_RUNNING_SUMMARY_TAIL", "Хвост бегущего конспекта", "int"),
    ("RUNNING_SUMMARY_TTL_MINUTES", "TTL бегущего конспекта, минут", "int"),
    ("CHAT_GLOBAL_CONTEXT_MAX_TOKENS", "Потолок глобального контекста, токенов", "int"),
    ("CHAT_THREAD_MAX_TOKENS", "Потолок треда, токенов", "int"),
    ("SUMMARY_MAX_CONTEXT_TOKENS", "Потолок контекста саммари, токенов", "int"),
    ("CHAT_SILENCE_AFTER_COOLDOWNS", "Кулдаунов подряд до молчания", "int"),
    ("CHAT_STYLE_ANCHORS_COUNT", "Число стилевых якорей", "int"),
    ("CHAT_STYLE_ANCHOR_MAX_CHARS", "Обрезка якоря, символов", "int"),
    ("TYPING_INTERVAL_SECONDS", "Интервал «печатает…», сек", "float"),
    ("CHAT_TEMPERATURE_PRECISE", "Temperature: точный", "float"),
    ("CHAT_TEMPERATURE_BALANCED", "Temperature: сбалансированный", "float"),
    ("CHAT_TEMPERATURE_CHATTY", "Temperature: болтливый", "float"),
    ("CHAT_TEMPERATURE_PRESET_DEFAULT", "Temperature-пресет по умолчанию", "str"),
    ("GRAPH_FACT_WEIGHT_DIRECT", "Стартовый вес прямых фактов", "float"),
    ("GRAPH_FACT_WEIGHT_ARCHIVE", "Стартовый вес архивных фактов", "float"),
    ("GRAPH_EPISODE_MERGE_INTERVAL_DAYS", "Интервал слияния эпизодов, дней", "int"),
    ("GRAPH_EPISODE_MERGE_BATCH", "Пачка кластеров за прогон", "int"),
    ("GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER", "Потолок фактов в кластере", "int"),
    ("GRAPH_TIME_DECAY_HALF_LIFE_DAYS", "Half-life time-decay, дней", "float"),
    ("GRAPH_TIME_DECAY_FLOOR", "Пол time-decay", "float"),
    ("GRAPH_FACTS_PER_USER_QUOTA", "Квота фактов на человека", "int"),
    ("GRAPH_FACT_TOUCH_EXTEND_DAYS", "Продление TTL при touch, дней", "int"),
    ("GRAPH_MMR_LAMBDA", "MMR-λ (0..1)", "float"),
    ("GRAPH_MMR_FETCH_K", "MMR fetch_k", "int"),
    ("GRAPH_REVIEW_INTERVAL_DAYS", "Интервал пересмотра, дней", "int"),
    ("GRAPH_COMPRESSION_LOG_RETENTION_DAYS", "Ретенция лога сжатий, дней", "int"),
    ("CHAT_CONTEXT_BUDGET_TOKENS", "Бюджет контекста direct_chat, токенов", "int"),
    ("CHAT_BUDGET_MAP_RATIO", "Доля бюджета: MAP", "float"),
    ("CHAT_BUDGET_GLOBAL_RATIO", "Доля бюджета: Global", "float"),
    ("CHAT_BUDGET_THREAD_RATIO", "Доля бюджета: Thread", "float"),
    ("CHAT_BUDGET_RAG_RATIO", "Доля бюджета: RAG", "float"),
    ("CHAT_BUDGET_TARGET_RATIO", "Доля бюджета: Target", "float"),
    ("CHAT_BUDGET_ANCHORS_RATIO", "Доля бюджета: Anchors", "float"),
    ("CHAT_BUDGET_RESPONSE_RATIO", "Доля бюджета: Response", "float"),
    ("CHAT_BUDGET_RESERVE_RATIO", "Доля бюджета: Reserve", "float"),
    ("CHAT_DEDUP_TTL_SECONDS", "TTL дедуп-записи, сек", "int"),
    ("DOWNLOAD_COOLDOWN", "Кулдаун скачивания, сек", "float"),
    ("VOICE_MAX_DURATION_SECONDS", "Макс. длительность войса, сек", "int"),
]

# ── reactions: id-списки, слова, пути, названия (не секреты) ────────────────
# (field, title_ru, type)
_REACTIONS: list[tuple] = [
    ("SLAVIK_USER_ID", "Telegram ID Славика", "int"),
    ("KOSTIK_USER_ID", "Telegram ID Костика", "int"),
    ("ALAN_USER_ID", "Telegram ID Алана", "int"),
    ("ADMIN_USER_ID", "Telegram ID админа", "int"),
    ("DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "Канал-источник dead page (@d_pages)", "str"),
    ("DEAD_PAGE_SOURCE_CHANNEL_ID", "ID канала-источника dead page", "int"),
    ("DEAD_PAGE_RELAY_CHANNEL_ID", "ID relay-канала dead page", "int"),
    ("DEAD_PAGE_DIR", "Папка медиа dead page", "str"),
    ("ALAN_USERNAME", "Юзернейм Алана", "str"),
    ("ALAN_GREETING_DIR", "Папка приветствий Алана", "str"),
    ("WAR_CHANNEL_IDS", "CSV ID каналов war-алертов", "str"),
    ("WAR_CHANNEL_USERNAMES", "CSV юзернеймов war-алертов", "str"),
    ("WAR_REPLIES", "CSV фраз war-алертов", "str"),
    ("SLAVIC_RANDOM_DIR", "Папка рандомных фото Славика", "str"),
    ("SLAVIC_PHOTO_PATH", "Одиночное фото Славика (deprecated)", "str"),
    ("COMMON_MEDIA_BASE", "Базовая папка common-медиа", "str"),
    ("DANGER_WORDS", "CSV danger-слов", "str"),
    ("GIF_PATH", "Файл гифки", "str"),
    ("GOODMORNING_TIME", "Время рассылки (HH:MM)", "str"),
    ("GOODMORNING_TZ", "Часовой пояс рассылки", "str"),
    ("GOODMORNING_TARGET_CHAT_IDS", "Список чатов рассылки", "json"),
    ("GOODMORNING_MEDIA_DIR", "Папка утреннего медиа", "str"),
    ("MIMIC_VICTIM_USER_IDS", "CSV ID жертв мимикрии", "str"),
    ("OLYA_USER_ID", "Telegram ID Оли", "int"),
    ("OLYA_MEDIA_BASE", "Папка медиа Оли", "str"),
    ("OLYA_SAVEASBOT_CHANNEL_IDS", "Канальные ID SaveAsBot", "json"),
    ("OLYA_SAVEASBOT_USER_IDS", "Юзер-ID SaveAsBot", "json"),
    ("OLYA_CAPTION_TEXT", "Текст капшна Оли", "str"),
    ("OLYA_MEDIA_TYPE", "Тип медиа Оли (video/...)", "str"),
    ("ALLOWED_SUMMARY_IDS", "Список ID для /summary", "json"),
    ("SUMMARY_ALIASES", "JSON-словарь алиасов имён", "json"),
    ("SUMMARY_TARGET_CHAT_IDS", "Список чатов саммари", "json"),
    ("CHAT_BOTWORD_PATTERN", "Regex-триггер «бот»-семьи", "str"),
    ("CHAT_MOOD_NEGATIVE_WORDS", "CSV негативных слов", "str"),
    ("CHAT_MOOD_POSITIVE_WORDS", "CSV позитивных слов", "str"),
    ("MEMORY_BACKUP_DIR", "Папка бэкапов памяти", "str"),
]


def _build_registry() -> dict[str, ParamSpec]:
    """Единый реестр: ключ — settings_field (или env_name для env-only)."""
    registry: dict[str, ParamSpec] = {}
    field_names = {f.name for f in dataclasses.fields(Settings)}

    def add(spec: ParamSpec) -> None:
        name = spec.settings_field or spec.env_name or spec.pg_key
        if name in registry:
            raise ValueError(f"duplicate catalog entry: {name}")
        registry[name] = spec

    for row in _INFRA:
        field, title, typ, secret = row
        add(ParamSpec(field, field, None, title, typ, secret=secret))
    for row in _INFRA_ENV_ONLY:
        env_name, title, typ, secret = row
        add(ParamSpec(None, env_name, None, title, typ, secret=secret))
    for row in _KEYS:
        field, title, typ, secret = row
        add(ParamSpec(field, field, CATEGORY_KEYS, title, typ, secret=secret))
    for row in _MODELS:
        field, title, typ = row
        add(ParamSpec(field, field, CATEGORY_MODELS, title, typ))
    for row in _FLAGS:
        field, title = row
        add(ParamSpec(field, field, CATEGORY_FLAGS, title, "bool"))
    for row in _LIMITS:
        field, title, typ = row
        add(ParamSpec(field, field, CATEGORY_LIMITS, title, typ))
    for row in _REACTIONS:
        field, title, typ = row
        add(ParamSpec(field, field, CATEGORY_REACTIONS, title, typ))
    for spec_id, title, code_source in _PROMPTS:
        add(ParamSpec(None, None, CATEGORY_PROMPTS, title, "str",
                      code_source=code_source, pg_id=spec_id))
    for spec_id, title in _CONTENT:
        add(ParamSpec(None, None, CATEGORY_CONTENT, title, "json",
                      pg_id=spec_id))
    return registry


REGISTRY: dict[str, ParamSpec] = _build_registry()

_BY_PG_KEY: dict[str, ParamSpec] = {s.pg_key: s for s in REGISTRY.values()}

_SETTINGS_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(Settings)
)


def get(settings_field: str) -> ParamSpec | None:
    """Запись по имени поля Settings (или env-имени для env-only)."""
    return REGISTRY.get(settings_field)


def get_by_pg_key(pg_key: str) -> ParamSpec | None:
    """Запись по ключу bot_settings (dotted {category}.{snake})."""
    return _BY_PG_KEY.get(pg_key)


def known_sections() -> set[str]:
    """Секции-идентификаторы для валидации/дерева прав (категории + access)."""
    return set(CATEGORIES) | {"access"}


def known_param_keys() -> set[str]:
    """Полные ключи для params-группы (все migratable + pg-only ключи)."""
    return {s.pg_key for s in REGISTRY.values() if s.category is not None}


def known_secret_keys() -> set[str]:
    """Полные ключи категории keys (для валидации keys-группы)."""
    return {s.pg_key for s in REGISTRY.values() if s.category == CATEGORY_KEYS}


def normalize_value(pg_key: str, value):
    """ХОТФИКС (прод-инцидент 86b3d3a): нормализация значения bot_settings по
    типу каталога. asyncpg отдаёт jsonb как СТРОКУ (json-кодек не
    зарегистрирован) — без каста '10' (str) ломает арифметику/сравнения
    (TypeError '<=' str/int в handlers/alan.py). Неизвестные каталогу ключи —
    as-is, никогда не падаем."""
    if value is None:
        return None
    spec = get_by_pg_key(pg_key)
    if spec is None:
        return value
    try:
        return _cast_to_type(spec, value)
    except Exception:
        logger.warning("[catalog] нормализация не удалась | key=%s | type=%s",
                       pg_key, spec.type, exc_info=True)
        return value


def _cast_to_type(spec: ParamSpec, value):
    """Каст значения к типу каталога (строгий, с защитой от мусора)."""
    if spec.type == "int":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            s = value.strip()
            if s.lstrip("-").isdigit():
                return int(s)
            try:
                f = float(s)
                return int(f) if f.is_integer() else value
            except ValueError:
                return value
        return value
    if spec.type == "float":
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value
    if spec.type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            s = value.strip().strip('"\'').lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off", ""):
                return False
            return value
        return value
    if spec.type == "json":
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                logger.warning("[catalog] json-значение не парсится (оставлено "
                               "как есть) | key=%s", spec.pg_key)
                return value
        if isinstance(value, (tuple, set)):
            return list(value)   # единообразие с coerce_catalog_value (pg_db)
        return value
    return value


def iter_migratable() -> list[ParamSpec]:
    """Записи для экспорта в bot_settings (категория задана; prompts/content —
    PG-only, без settings-источника — миграцией НЕ экспортируются, их сидит
    ConfigCache)."""
    return [
        s for s in REGISTRY.values()
        if s.category is not None and s.settings_field is not None
    ]


def iter_pg_only() -> list[ParamSpec]:
    """PG-only ключи без settings/env источника (prompts/content)."""
    return [
        s for s in REGISTRY.values()
        if s.category is not None and s.settings_field is None
    ]


def by_category(category: str | None) -> list[ParamSpec]:
    return [s for s in REGISTRY.values() if s.category == category]


def settings_field_coverage() -> tuple[set[str], set[str]]:
    """(не покрытые поля Settings, лишние записи) — для юнит-теста полноты."""
    covered = {s.settings_field for s in REGISTRY.values() if s.settings_field}
    missing = set(_SETTINGS_FIELDS) - covered
    extra = covered - set(_SETTINGS_FIELDS)
    return missing, extra


if __name__ == "__main__":  # pragma: no cover — диагностика при разработке
    missing, extra = settings_field_coverage()
    logger.info("catalog entries=%d | settings fields=%d | missing=%s | extra=%s",
                len(REGISTRY), len(_SETTINGS_FIELDS), sorted(missing), sorted(extra))
    for spec in sorted(REGISTRY.values(), key=lambda s: (s.category or "", s.pg_key)):
        logger.info("%s | %s | %s | secret=%s", spec.pg_key, spec.category,
                    spec.type, spec.secret)
