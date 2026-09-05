"""Epic 85 (84.12.2) — каталог-реестр ВСЕХ регулируемых параметров Settings.

ЕДИНЫЙ источник для:
  * scripts/migrate_env_to_pg.py (T-637) — полный экспорт .env → bot_settings;
  * GET /api/roles/tree (T-640) — дерево прав конструктора ролей;
  * ConfigCache.init() — belt-and-suspenders самозасев дефолтов (84.12.3);
  * фронта (вкладки админки) — дублирование ЗАПРЕЩЕНО (84.12.2).

Каждая запись ParamSpec: settings-поле (или None для env-only/PG-only ключей),
env-имя, категория bot_settings (prompts|models|keys|limits|flags|reactions|
content|memory; None = infra — НЕ мигрируется и НЕ попадает в дерево прав),
русский заголовок, тип (str|int|float|bool|json), флаг секретности (R17:
значения секретов никогда не печатаются), опциональный code_source для
prompts («module.attr» — код-канон, в .env их нет; сид при старте ConfigCache).

Ключ в PG — dotted: {category}.{snake_name} (84.12.1).

memory (фаза 2, T-755): бессрочное хранение памяти — тумблер
memory.infinite_retention (категория «Память», группа memory_infinite).
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
# Фаза 2 (T-755): бессрочное хранение памяти (memory.infinite_retention).
CATEGORY_MEMORY = "memory"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_PROMPTS,
    CATEGORY_MODELS,
    CATEGORY_KEYS,
    CATEGORY_LIMITS,
    CATEGORY_FLAGS,
    CATEGORY_REACTIONS,
    CATEGORY_CONTENT,
    CATEGORY_MEMORY,
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
    # 84.24 (дельта 02.09.2026): группа рендера (id из GROUPS) и простое
    # описание «на что влияет» — фронт админки группирует карточки.
    group: str = ""
    description: str = ""
    code_source: str | None = None  # "module.attr" — код-канон (prompts)
    pg_id: str | None = None        # явный PG-ключ (PG-only записи)
    # Эпик 04.09.2026 (3.1/FR-28): признак виджета рендера для фронта.
    # "" (дефолт) | "keyvalue" (JSON-объект «ключ→значение» — KV-редактор).
    widget: str = ""

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


@dataclasses.dataclass(frozen=True)
class GroupSpec:
    """84.24.1: группа параметров для фронта (карточка-группа)."""

    id: str            # slug "{category}_{noun}", уникален глобально
    category: str      # категория bot_settings (prompts/models/...)
    title_ru: str      # заголовок группы
    description: str   # 1-2 предложения простым русским
    order: int         # порядок рендера ВНУТРИ категории (1, 2, 3...)


# ── 84.24.2: реестр групп (63 шт.; покрытие параметров категорий) ────────────
GROUPS: tuple[GroupSpec, ...] = (
    # prompts (8)
    GroupSpec("prompts_factcheck", "prompts", "Фактчек",
              "Как бот проверяет факты и оформляет проверку.", 1),
    GroupSpec("prompts_search", "prompts", "Поиск",
              "Как бот ищет в интернете и формулирует ответ.", 2),
    GroupSpec("prompts_checkup", "prompts", "Чек-ап",
              "Инструкция для ежемесячной сводки о здоровье сервера и памяти.", 3),
    GroupSpec("prompts_direct_chat", "prompts", "Прямой чат",
              "Характер и правила ответов бота в прямом общении.", 4),
    GroupSpec("prompts_summary", "prompts", "Саммари",
              "Как бот пересказывает разговоры и каналы.", 5),
    GroupSpec("prompts_youtube", "prompts", "YouTube",
              "Пересказ видео по ссылке.", 6),
    GroupSpec("prompts_web", "prompts", "Веб-страницы",
              "Пересказ страниц по ссылке.", 7),
    GroupSpec("prompts_memory", "prompts", "Память и граф знаний",
              "Промпты извлечения и сжатия фактов для долгой памяти.", 8),
    # models (8)
    GroupSpec("models_main", "models", "Основная модель",
              "Главная нейросеть бота: адрес и название модели.", 1),
    GroupSpec("models_fallback", "models", "Фолбэк-модель",
              "Запасная нейросеть — когда основная недоступна.", 2),
    GroupSpec("models_embeddings", "models", "Эмбеддинги и токены",
              "Модель «отпечатков» текста для поиска по памяти + подсчёт длины.", 3),
    GroupSpec("models_llm_timeouts", "models", "Таймауты и повторы",
              "Сколько ждать ответ нейросети и как повторять при сбоях.", 4),
    GroupSpec("models_llm_guard", "models", "Бюджет и защита от сбоев",
              "Страховка от зависших запросов: жёсткий лимит и «рубильник».", 5),
    GroupSpec("models_extra_providers", "models", "Дополнительные провайдеры",
              "Groq — голосовые, OpenRouter — пересказы видео.", 6),
    GroupSpec("models_checkup", "models", "Чек-ап (Betterstack)",
              "Откуда бот берёт метрики сервера для чекапа.", 7),
    GroupSpec("models_video_summary", "models", "Видео-выжимка (OpenRouter)",
              "Модели, которые смотрят видео сами, и таймаут выжимки.", 8),
    # keys (7)
    GroupSpec("keys_llm", "keys", "Основной LLM",
              "Пароли доступа к основной и запасной нейросети.", 1),
    GroupSpec("keys_groq", "keys", "Groq",
              "Ключ распознавания голосовых.", 2),
    GroupSpec("keys_openrouter", "keys", "OpenRouter",
              "Ключ пересказов видео и страниц.", 3),
    GroupSpec("keys_search", "keys", "Поиск: Exa и Tavily",
              "Ключи интернет-поиска.", 4),
    GroupSpec("keys_betterstack", "keys", "Логи и чек-ап",
              "Логин и пароль SQL-базы для чекапа.", 5),
    GroupSpec("keys_youtube", "keys", "YouTube: прокси и cookies",
              "Прокси и cookies для субтитров YouTube.", 6),
    GroupSpec("keys_media", "keys", "Медиа-шара",
              "Секрет подписи временных ссылок на видео (раунд 3).", 7),
    # limits (20)
    GroupSpec("limits_persons", "limits", "Персонажи: Леха и Костик",
              "Частота ответов Лехи и Костика, приветствия Лехи.", 1),
    GroupSpec("limits_media", "limits", "Медиа-реакции",
              "Частота гифок/фото, паузы common-медиа, Оля, скачивание, войсы.", 2),
    GroupSpec("limits_mimic", "limits", "Мимикрия",
              "Правила передразнивания: минимальная длина и паузы.", 3),
    GroupSpec("limits_deadpage", "limits", "Dead page",
              "Подписи, паузы и повторы постов dead page.", 4),
    GroupSpec("limits_cooldowns", "limits", "Кулдауны модулей",
              "Паузы между срабатываниями: поиск, фактчек, YouTube, веб, чекап, /info.", 5),
    GroupSpec("limits_summary", "limits", "Саммари",
              "Окно сбора, длина ответа, лимиты и паузы генерации.", 6),
    GroupSpec("limits_search", "limits", "Поиск: лимиты",
              "Длина ответа и окно контекста поиска.", 7),
    GroupSpec("limits_factcheck", "limits", "Фактчек: лимиты",
              "Длина ответа и окно контекста фактчека.", 8),
    GroupSpec("limits_checkup", "limits", "Чек-ап: лимиты",
              "Длина ответа и потолок входящих данных.", 9),
    GroupSpec("limits_youtube_web", "limits", "YouTube и веб: лимиты",
              "Длина пересказов.", 10),
    GroupSpec("limits_chat", "limits", "Прямой чат: контекст",
              "Окно контекста, треды, кулдауны, замки, TTL.", 11),
    GroupSpec("limits_chat_behavior", "limits", "Прямой чат: поведение",
              "Молчание после кулдаунов, стилевые якоря, «печатает…».", 12),
    GroupSpec("limits_chat_budgets", "limits", "Прямой чат: бюджеты токенов",
              "Как контекст делится между блоками (карта/тред/RAG/…).", 13),
    GroupSpec("limits_temperature", "limits", "Температура ответов",
              "Насколько свободно и креативно отвечает прямой чат.", 14),
    GroupSpec("limits_memory", "limits", "Память",
              "Сроки хранения сообщений, фактов, бэкапов, кэша.", 15),
    GroupSpec("limits_graph", "limits", "Граф знаний",
              "Веса фактов, дедуп, слияние эпизодов, TTL, квоты памяти.", 16),
    GroupSpec("limits_smart_cache", "limits", "Умный кэш",
              "Сколько хранить готовые ответы и как много строк.", 17),
    GroupSpec("limits_service", "limits", "Служебное",
              "Технические интервалы — обычно не трогать.", 18),
    GroupSpec("limits_user_aliases", "limits", "Имена людей",
              "Как бот обращается к людям: алиас → имя → никнейм.", 19),
    GroupSpec("limits_youtube_proxy", "limits", "YouTube: прокси",
              "Настройки прокси для субтитров YouTube (коды стран, повторы).", 20),
    # flags (5)
    GroupSpec("flags_modules", "flags", "Модули (вкл/выкл)",
              "Рубильники функций бота целиком.", 1),
    GroupSpec("flags_media", "flags", "Медиа и Оля",
              "Капшены, репосты, реакция Оли на видео, common-медиа.", 2),
    GroupSpec("flags_memory", "flags", "Память и граф знаний",
              "Механизмы запоминания: извлечение, дедуп, бэкапы, кэш.", 3),
    GroupSpec("flags_chat_behavior", "flags", "Поведение в чате",
              "Стиль ответов, настроение, дедуп, индикатор набора, доступ к саммари.", 4),
    GroupSpec("flags_service", "flags", "Служебное",
              "Технические рубильники (БД, защита LLM) — обычно не трогать.", 5),
    # reactions (13)
    GroupSpec("reactions_persons", "reactions", "Персоны (ID)",
              "Telegram ID Лехи, Костика, Славика, Оли и админа.", 1),
    GroupSpec("reactions_deadpage", "reactions", "Dead page",
              "Канал-источник, relay-канал, папка медиа.", 2),
    GroupSpec("reactions_slavik", "reactions", "Славик",
              "Папки рандомных фото и файл гифки.", 3),
    GroupSpec("reactions_alan", "reactions", "Леха",
              "Папка видео-приветствий.", 4),
    GroupSpec("reactions_war", "reactions", "War-алерты",
              "Каналы, юзернеймы и фразы алертов.", 5),
    GroupSpec("reactions_common", "reactions", "Common-медиа",
              "Базовая папка и список danger-слов.", 6),
    GroupSpec("reactions_goodmorning", "reactions", "Утренняя рассылка",
              "Время, часовой пояс, чаты, папка медиа.", 7),
    GroupSpec("reactions_mimic", "reactions", "Мимикрия",
              "Кого передразнивать (ID «жертв»).", 8),
    GroupSpec("reactions_olya", "reactions", "Оля",
              "Папка медиа, капшены, SaveAsBot.", 9),
    GroupSpec("reactions_summary", "reactions", "Саммари",
              "Кому доступно /summary, алиасы имён, чаты.", 10),
    GroupSpec("reactions_chat", "reactions", "Прямой чат",
              "Слова-триггеры и слова настроения.", 11),
    GroupSpec("reactions_memory", "reactions", "Память",
              "Папка бэкапов памяти.", 12),
    GroupSpec("reactions_word_reactions", "reactions", "Словесные реакции",
              "Тумблеры текстовых реакций: „Вася ↔ АДМИН” и „куча → ДАЛБАЕБ”.", 13),
    # content (2)
    GroupSpec("content_info", "content", "Как это работает",
              "Текст справки для пользователей.", 1),
    GroupSpec("content_media", "content", "Медиа-шара",
              "Каталог временных публикаций видео и внешний URL (раунд 3).", 2),
    # memory (1; фаза 2, T-755)
    GroupSpec("memory_infinite", "memory", "Бессрочное хранение",
              "Хранение памяти без сроков годности: сырьё и факты не удаляются "
              "и не сжимаются по TTL/ретенции (для исторического импорта).", 1),
)


# ── prompts: PG-only сиды из код-канонов (84.12.1: «в .env их НЕТ») ────────
# (pg_id, title_ru, code_source, group, description)
_PROMPTS: list[tuple] = [
    ("prompts.factcheck_system_prompt", "Системный промпт фактчека",
     "services.factcheck_prompts.FACTCHECK_SYSTEM_PROMPT", "prompts_factcheck",
     "Инструкция нейросети при проверке фактов: как оформлять ответ. Изменения применяются сразу после сохранения."),
    ("prompts.search_system_prompt", "Системный промпт поиска",
     "services.search_prompts.SEARCH_SYSTEM_PROMPT", "prompts_search",
     "Инструкция нейросети при поиске: как формулировать ответ. Изменения применяются сразу после сохранения."),
    ("prompts.summary_system_prompt", "Системный промпт саммари",
     "services.summary_prompts.SYSTEM_PROMPT", "prompts_summary",
     "Инструкция нейросети для пересказов: стиль и структура. Изменения применяются сразу после сохранения."),
    ("prompts.checkup_system_prompt", "Системный промпт чекапа",
     "services.checkup_prompts.CHECKUP_SYSTEM_PROMPT", "prompts_checkup",
     "Инструкция для ежемесячной сводки о здоровье сервера и памяти. Изменения применяются сразу после сохранения."),
    ("prompts.direct_chat_system_prompt", "Системный промпт прямого чата",
     "services.chat_prompts.CHAT_SYSTEM_PROMPT", "prompts_direct_chat",
     "Характер и правила ответов бота в прямом общении. Изменения применяются сразу после сохранения."),
    ("prompts.extract_system_prompt", "Промпт извлечения фактов (граф)",
     "services.summary_prompts.EXTRACT_PROMPT", "prompts_memory",
     "Инструкция, как вытаскивать факты из разговора для долгой памяти. Изменения применяются сразу после сохранения."),
    ("prompts.compress_system_prompt", "Промпт сжатия истории (L3)",
     "services.summary_prompts.COMPRESS_PROMPT", "prompts_memory",
     "Инструкция, как ужимать старые сообщения в факты памяти. Изменения применяются сразу после сохранения."),
    ("prompts.youtube_system_prompt", "Системный промпт пересказа YouTube",
     "services.youtube_prompts.YOUTUBE_SYSTEM_PROMPT", "prompts_youtube",
     "Инструкция нейросети при пересказе видео по ссылке. Изменения применяются сразу после сохранения."),
    ("prompts.youtube_video_system_prompt", "Системный промпт пересказа видео (мультимодально)",
     "services.youtube_prompts.YOUTUBE_VIDEO_SYSTEM_PROMPT", "prompts_youtube",
     "Инструкция нейросети при пересказе видео, когда модель смотрит само видео (без субтитров)."),
    ("prompts.webpage_system_prompt", "Системный промпт пересказа веб-страниц",
     "services.web_prompts.WEBPAGE_SYSTEM_PROMPT", "prompts_web",
     "Инструкция нейросети при пересказе страницы по ссылке. Изменения применяются сразу после сохранения."),
]

# ── content: PG-only ключи (84.13.2) ────────────────────────────────────────
# (pg_id, title_ru, group, description)
_CONTENT: list[tuple] = [
    ("content.info_how_it_works", "Текст «Как это работает» (rich-HTML)",
     "content_info",
     "Справка для пользователей админки. Разметка HTML — можно картинки и ссылки."),
]

# ── content: поля Settings (раунд 3 — каталог медиа-шары) ──────────────────
# (field, title_ru, type, group, description)
_CONTENT_SETTINGS: list[tuple] = [
    ("MEDIA_SHARE_DIR", "Каталог временной публикации видео", "str", "content_media",
     "Папка, куда копируются видео для пересказа «по кадрам» (вне web-статики). Относительно корня проекта."),
    ("MEDIA_PUBLIC_BASE_URL", "Внешний базовый URL /media", "str", "content_media",
     "Публичный домен, через который OpenRouter видит опубликованные видео (Caddy → FastAPI)."),
]

# ── infra: остаётся в .env (84.12.1); category=None — НЕ мигрируется ───────
# (field, title_ru, type, secret)
_INFRA: list[tuple] = [
    ("API_TOKEN", "Токен Telegram-бота", "str", True),
    ("DB_PATH", "Путь к SQLite-БД", "str", False),
    ("MEDIA_BASE", "Корневая папка медиа", "str", False),
    ("WEBAPP_URL", "URL Telegram Mini App (команда /menu)", "str", False),
    ("COBALT_API_URL", "URL self-hosted cobalt", "str", False),
    ("LOCAL_BOT_API_URL", "URL локального telegram-bot-api", "str", False),
    ("TELEGRAM_API_FILES_DIR", "Хост-путь data-dir telegram-bot-api", "str", False),
    ("DOWNLOAD_DIR", "Папка скачанных файлов", "str", False),
    ("INFO_TEXT_FILE", "Путь к info_text.md", "str", False),
    ("CHECKUP_JOURNALCTL_CMD", "Команда journalctl для чекапа", "str", False),
    # Embed-фоллбэк (EMBEDDING_FALLBACK_*): Google AI Studio OpenAI-совместимый
    # /embeddings — когда основной провайдер не отдаёт эмбеддинги (403-квоты).
    ("EMBEDDING_FALLBACK_BASE_URL", "Базовый URL embed-фоллбэка", "str", False),
    ("EMBEDDING_FALLBACK_API_KEY", "Ключ embed-фоллбэка (Google AI Studio)", "str", True),
    ("EMBEDDING_FALLBACK_API_KEY_2", "Ключ эмбеддинг-фоллбэка 2 (Google AI Studio, запасной аккаунт)", "str", True),
    ("EMBEDDING_FALLBACK_MODEL", "Модель embed-фоллбэка", "str", False),
    ("EMBEDDING_FALLBACK_TIMEOUT_SECONDS", "Таймаут embed-фоллбэка, сек", "float", False),
    ("EMBEDDING_FALLBACK_MAX_RETRIES", "Ретраи embed-фоллбэка", "int", False),
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
# (field, title_ru, type, secret, group, description)
_KEYS: list[tuple] = [
    ("LLM_API_KEY", "Ключ LLM (apinet.cloud)", "str", True, "keys_llm",
     "Ключ основной нейросети — почти все ответы бота ходят через него. Получить: кабинет провайдера LLM."),
    ("LLM_FALLBACK_API_KEY", "Ключ фоллбэк-LLM", "str", True, "keys_llm",
     "Ключ запасной нейросети на случай сбоя основной. Получить: кабинет запасного провайдера."),
    ("TAVILY_API_KEY", "Ключ Tavily", "str", True, "keys_search",
     "Ключ интернет-поиска (Tavily) — бот ищет по нему. Получить: tavily.com."),
    ("EXA_API_KEY", "Ключ Exa", "str", True, "keys_search",
     "Ключ интернет-поиска (Exa) — резервный источник. Получить: exa.ai."),
    ("GROQ_API_KEY", "Ключ Groq", "str", True, "keys_groq",
     "Ключ сервиса Groq — им бот распознаёт голосовые сообщения. Получить: console.groq.com."),
    ("OPENROUTER_API_KEY", "Ключ OpenRouter", "str", True, "keys_openrouter",
     "Ключ сервиса OpenRouter — пересказы видео и страниц. Получить: openrouter.ai."),
    ("CHECKUP_BETTERSTACK_SQL_USER", "Пользователь Betterstack SQL", "str", True, "keys_betterstack",
     "Логин SQL-базы Betterstack для чекапа. Получить: betterstack.com (SQL API)."),
    ("CHECKUP_BETTERSTACK_SQL_PASSWORD", "Пароль Betterstack SQL", "str", True, "keys_betterstack",
     "Пароль SQL-базы Betterstack для чекапа. Получить: betterstack.com (SQL API)."),
    ("YOUTUBE_TRANSCRIPT_PROXY_URL", "Прокси-URL YouTube (user:pass)", "str", True, "keys_youtube",
     "Адрес прокси с логином и паролем — через него бот берёт субтитры YouTube. Получить: кабинет прокси-сервиса."),
    ("YOUTUBE_TRANSCRIPT_PROXY_USERNAME", "Логин resident-прокси Webshare", "str", True, "keys_youtube",
     "Логин резидент-прокси Webshare для субтитров. Получить: webshare.io."),
    ("YOUTUBE_TRANSCRIPT_PROXY_PASSWORD", "Пароль resident-прокси Webshare", "str", True, "keys_youtube",
     "Пароль резидент-прокси Webshare для субтитров. Получить: webshare.io."),
    ("YOUTUBE_COOKIES_FILE", "Путь к cookies-файлу YouTube (Netscape)", "str", True, "keys_youtube",
     "Файл с cookies браузера для YouTube — помогает получать субтитры. Обновляется вручную при протухании."),
    ("MEDIA_SHARE_SECRET", "Секрет подписи /media-ссылок", "str", True, "keys_media",
     "Секрет HMAC-подписи временных URL на опубликованные видео (раунд 3). ПУСТО = публикация выключена — видео пересказываются по звуку (STT). Получить: свой генератор случайных строк."),
]

# ── models: провайдеры/модели/таймауты/ретраи (не секреты) ──────────────────
# (field, title_ru, type, group, description)
_MODELS: list[tuple] = [
    ("LLM_BASE_URL", "Базовый URL LLM API", "str", "models_main",
     "Адрес сервера нейросети. Меняется, только если переезжаете на другого провайдера."),
    ("LLM_MODEL_NAME", "Модель LLM", "str", "models_main",
     "Название основной модели бота. От неё зависит качество и скорость почти всех ответов."),
    ("EMBEDDING_MODEL_NAME", "Модель эмбеддингов", "str", "models_embeddings",
     "Модель «отпечатков» текста для поиска по памяти. Менять только вместе с размерностью ниже."),
    ("EMBEDDING_DIM", "Размерность эмбеддингов", "int", "models_embeddings",
     "Длина «отпечатка» текста. Должна совпадать с моделью эмбеддингов, иначе поиск сломается."),
    ("LLM_TIMEOUT", "Таймаут запроса LLM, сек", "float", "models_llm_timeouts",
     "Сколько ждать ответ нейросети. Больше — меньше сбоев на медленных моделях, но дольше тишина."),
    ("LLM_MAX_RETRIES", "Число ретраев LLM", "int", "models_llm_timeouts",
     "Сколько раз повторить запрос при временном сбое. Больше — надёжнее, но дольше ждать."),
    ("LLM_RETRY_BACKOFF_BASE", "База экспоненциального backoff", "float", "models_llm_timeouts",
     "Начальная пауза перед повтором, сек. Больше — реже долбить провайдера при сбоях."),
    ("LLM_RETRY_BACKOFF_CAP", "Потолок backoff, сек", "float", "models_llm_timeouts",
     "Максимальная пауза между повторами. Больше — дольше терпелив, но тише при упорном сбое."),
    ("LLM_RETRY_JITTER_MAX", "Максимальный jitter, сек", "float", "models_llm_timeouts",
     "Случайная добавка к паузе повтора — чтобы запросы не стучались одновременно."),
    ("LLM_TOTAL_BUDGET", "Жёсткий дедлайн всей попытки, сек", "float", "models_llm_guard",
     "Потолок времени на запрос со всеми повторами. Меньше — бот быстрее сдаётся при проблемах."),
    ("LLM_FALLBACK_BASE_URL", "URL фоллбэк-провайдера", "str", "models_fallback",
     "Адрес запасной нейросети. Нужен, только если настроен фоллбэк."),
    ("LLM_FALLBACK_MODEL", "Модель фоллбэк-провайдера", "str", "models_fallback",
     "Название модели запасной нейросети. Используется, когда основная недоступна."),
    ("LLM_FALLBACK_MAX_RETRIES", "Ретраи фоллбэк-цепочки", "int", "models_fallback",
     "Сколько раз повторять запрос к запасной нейросети. Больше — надёжнее, но дольше."),
    ("LLM_FALLBACK_TIMEOUT_SECONDS", "Таймаут фоллбэка, сек", "float", "models_fallback",
     "Сколько ждать ответ запасной нейросети. Больше — меньше сбоев, дольше ожидание."),
    ("LLM_CB_FAILURE_THRESHOLD", "Порог сбоев защитного переключателя", "int", "models_llm_guard",
     "Сколько сбоев подряд до «рубильника» — бот временно перестаёт дёргать нейросеть."),
    ("LLM_CB_COOLDOWN_SECONDS", "Кулдаун Circuit Breaker, сек", "float", "models_llm_guard",
     "Сколько отдыхает «рубильник» после сбоев, прежде чем снова пробовать."),
    ("CHECKUP_BETTERSTACK_SQL_HOST", "Хост Betterstack SQL API", "str", "models_checkup",
     "Адрес сервера метрик Betterstack для чекапа. Меняется редко."),
    ("CHECKUP_BETTERSTACK_SQL_TABLE", "Префикс источника Betterstack", "str", "models_checkup",
     "Имя источника метрик в Betterstack. Меняется, если пересоздали источник."),
    ("CHECKUP_BETTERSTACK_SQL_QUERY", "SQL-оверрайд чекапа", "str", "models_checkup",
     "Свой SQL-запрос к метрикам, если стандартный не подходит. Обычно не трогать."),
    ("TOKENIZER_ENCODING", "Кодировка tiktoken", "str", "models_embeddings",
     "Как бот считает длину текста в токенах. Менять только вместе с моделью."),
    ("TOKEN_SAFETY_MULTIPLIER", "Множитель безопасности токенов", "float", "models_embeddings",
     "Запас при подсчёте длины: больше — бот осторожнее и чаще вписывается в лимиты."),
    ("GROQ_TIMEOUT", "Таймаут Groq, сек", "float", "models_extra_providers",
     "Сколько ждать ответ Groq при распознавании голосовых. Больше — меньше сбоев."),
    ("GROQ_MAX_CONCURRENCY", "Очередь Groq (semaphore)", "int", "models_extra_providers",
     "Сколько запросов к Groq одновременно. Меньше — спокойнее для сервиса, дольше очередь."),
    ("GROQ_MIN_INTERVAL", "Мин. интервал между запросами Groq, сек", "float", "models_extra_providers",
     "Пауза между распознаваниями голосовых. Больше — реже обращения к сервису."),
    ("GROQ_MAX_RETRIES", "Число ретраев Groq", "int", "models_extra_providers",
     "Сколько раз повторить распознавание при сбое. Больше — надёжнее, дольше ждать."),
    ("OPENROUTER_TIMEOUT", "Таймаут OpenRouter, сек", "float", "models_extra_providers",
     "Сколько ждать ответ OpenRouter при пересказах. Больше — меньше сбоев на медленных моделях."),
    ("VIDEO_PRIMARY_MODEL", "Первичная видео-модель (OpenRouter)", "str", "models_video_summary",
     "Раунд 4 (T-710): NVIDIA Nemotron 3 Nano Omni 30B (audio+video, контекст 256k) — единственная free-модель OpenRouter с аудио- и видео-модальностью. Первой пробует „посмотреть” сам ролик; отказала/не видит видео — запасная, затем субтитры."),
    ("VIDEO_FALLBACK_MODEL", "Запасная видео-модель (OpenRouter)", "str", "models_video_summary",
     "Раунд 4 (T-710): MiniMax M3 (контекст 1M) — видит кадры ролика. Используется, когда первичная недоступна или ответила отказом; упала — бот пересказывает по субтитрам."),
    ("VIDEO_TIMEOUT_SECONDS", "Таймаут видео-запроса, сек", "float", "models_video_summary",
     "Сколько ждать ответ мультимодальной модели на видео. Больше — реже сбои, но дольше тишина."),
]

# ── flags: рубильники модулей ───────────────────────────────────────────────
# (field, title_ru, group, description)
_FLAGS: list[tuple] = [
    ("SUMMARY_ENABLED", "Модуль саммари включён", "flags_modules",
     "Включает и выключает саммари целиком. Выключено — бот не делает пересказы разговоров."),
    ("DIRECT_CHAT_BOTWORD_ENABLED", "Триггер «бот»-семьи в чате", "flags_modules",
     "Включает прямые ответы бота на обращения к нему. Выключено — бот игнорирует триггеры."),
    ("ENABLE_VOICE_TRANSCRIPTION", "Транскрипция голосовых", "flags_modules",
     "Включает распознавание голосовых сообщений. Выключено — голосовые не расшифровываются."),
    ("GRAPH_RAG_ENABLED", "GraphRAG-извлечение при архивации", "flags_memory",
     "Включает извлечение фактов из старых сообщений в граф памяти. Выключено — только краткое сжатие."),
    ("SMART_CACHE_ENABLED", "Exact Match Cache", "flags_modules",
     "Кэш точных повторов вопросов — бот отвечает мгновенно из памяти. Выключено — всегда новый ответ."),
    ("THROTTLE_PERSISTENT_ENABLED", "Персистентный троттлинг", "flags_modules",
     "Включает общие лимиты частоты запросов между модулями. Выключено — модули ограничиваются сами."),
    ("DOWNLOAD_ENABLED", "Скачивание видео («скачай <url>»)", "flags_modules",
     "Включает команду скачивания видео по ссылке. Выключено — бот не качает."),
    ("YTDLP_FOR_YOUTUBE", "yt-dlp для YouTube (вместо cobalt)", "flags_modules",
     "Включает локальный движок для YouTube. Выключено — YouTube качается прежним способом."),
    ("CHAT_SILENCE_ENABLED", "Стачка кулдаунов → молчание", "flags_chat_behavior",
     "После нескольких кулдаунов подряд бот замолкает на время. Выключено — бот отвечает, как только можно."),
    ("CHAT_STYLE_ANCHORS_ENABLED", "Стилевые якоря", "flags_chat_behavior",
     "Бот запоминает фразы, сказанные вами, и повторяет их стиль. Выключено — стиль не копируется."),
    ("CHAT_MOOD_ENABLED", "Определение настроения собеседника", "flags_chat_behavior",
     "Бот следит за настроением сообщений и подстраивает ответы. Выключено — ответы нейтральные."),
    ("CHAT_RUNNING_SUMMARY_ENABLED", "Бегущий конспект", "flags_chat_behavior",
     "Бот держит краткий конспект длинного разговора. Выключено — контекст только из сообщений."),
    ("CHAT_DEDUP_ENABLED", "Дедуп одинаковых текстов подряд", "flags_chat_behavior",
     "Бот не отвечает на одинаковые сообщения подряд. Выключено — отвечает на каждое."),
    ("CHAT_CONTEXT_BUDGETS_ENABLED", "Бюджеты контекста direct_chat", "flags_chat_behavior",
     "Включает деление контекста по блокам (карта/тред/RAG). Выключено — контекст без ограничений долей."),
    ("SUMMARY_STREAMING_ENABLED", "Стриминг саммари (placeholder + edit)", "flags_chat_behavior",
     "Пересказы появляются постепенно, а не одним куском. Выключено — ответ приходит целиком."),
    ("TYPING_INDICATOR_ENABLED", "Индикатор «печатает…»", "flags_chat_behavior",
     "Бот показывает «печатает…» пока думает. Выключено — индикатора нет."),
    ("SEARCH_RERANK_ENABLED", "LLM-реранкинг поиска", "flags_modules",
     "Включает дополнительную сортировку результатов поиска нейросетью. Дороже, но точнее."),
    ("CHECKUP_MEMORY_METRICS_ENABLED", "Метрики здоровья памяти в чекап", "flags_modules",
     "Включает раздел о здоровье памяти в ежемесячной сводке. Выключено — раздел пропускается."),
    ("GRAPH_DEDUP_ENABLED", "Дедуп фактов при записи", "flags_memory",
     "Похожие факты не дублируются в памяти. Выключено — память растёт быстрее и грязнее."),
    ("GRAPH_EPISODE_MERGE_ENABLED", "Слияние повторяющихся эпизодов", "flags_memory",
     "Похожие эпизоды памяти объединяются в один. Выключено — эпизоды копятся отдельно."),
    ("GRAPH_TIME_DECAY_ENABLED", "Time-decay весов фактов", "flags_memory",
     "Старые факты со временем становятся менее важными. Выключено — важность не устаревает."),
    ("GRAPH_USER_QUOTA_ENABLED", "Квота памяти на человека", "flags_memory",
     "Ограничивает объём памяти на каждого человека. Выключено — память без потолка."),
    ("GRAPH_FACT_TOUCH_ENABLED", "TTL+LRU touch фактов", "flags_memory",
     "Упоминание факта продлевает ему жизнь. Выключено — срок жизни не продлевается."),
    ("GRAPH_REVIEW_ENABLED", "Периодический пересмотр фактов", "flags_memory",
     "Бот регулярно пересматривает и чистит память. Выключено — чистка только при архивации."),
    ("VEC_INT8_ENABLED", "int8-сжатие векторов", "flags_memory",
     "Сжимает «отпечатки» текста — память занимает меньше места. Выключено — точнее, но тяжелее."),
    ("GRAPH_MMR_ENABLED", "MMR-разнообразие RAG", "flags_memory",
     "Ответы по памяти становятся разнообразнее. Выключено — берутся самые похожие факты."),
    ("MEMORY_COMMANDS_USER_ENABLED", "Память-команды «запомни/забудь» для участников", "flags_memory",
     "Выключено — «запомни/забудь» доступны только админу и модераторам; участникам бот отвечает отказом и команду не исполняет."),
    ("MEMORY_BACKUP_ENABLED", "Ежедневный бэкап памяти", "flags_memory",
     "Включает ежедневное резервное копирование памяти. Выключено — бэкапы не создаются."),
    ("EMBED_CACHE_ENABLED", "Кэш эмбеддингов", "flags_memory",
     "Кэширует «отпечатки» текстов — быстрее и дешевле. Выключено — считать каждый раз заново."),
    ("DB_WAL_CHECKPOINT_ENABLED", "WAL-checkpoint SQLite", "flags_service",
     "Технический: периодически ужимает журнал БД. Обычно не трогать."),
    ("LLM_CB_ENABLED", "Circuit Breaker direct_chat", "flags_service",
     "«Рубильник» при сбоях нейросети: временно не дёргает её. Выключено — бот пробует всегда."),
    ("COMMON_WORK_MEDIA_ENABLED", "Медиа work-подсервиса", "flags_media",
     "Включает медиа для work-запросов («устал» и подобные). Выключено — только остальные."),
    ("COMMON_MEDIA_ENABLED", "Все common-медиа", "flags_media",
     "Главный рубильник всех медиа-реакций бота. Выключено — гифки/фото не отправляются вообще."),
    ("OLYA_ENABLED", "Сервис Оли", "flags_media",
     "Включает реакции на видео от Оли. Выключено — бот игнорирует их."),
    ("OLYA_CAPTION_ENABLED", "Капшн ответов Оли", "flags_media",
     "Включает подпись под ответами Оли. Выключено — ответы без подписи."),
    ("OLYA_REPOST_ENABLED", "Ответ репостом Оли", "flags_media",
     "Оля отвечает репостом видео. Выключено — обычным сообщением."),
    ("OLYA_ALWAYS_SEND", "Реакция на ВСЕ видео Оли", "flags_media",
     "Бот реагирует на каждое видео Оли. Выключено — с перерывами."),
    ("OLYA_CAPTION_MENTION_ENABLED", "Триггер @SaveAsBot в капшне", "flags_media",
     "Включает реакцию на упоминание SaveAsBot в подписи Оли. Выключено — упоминание игнорируется."),
    ("MIMIC_FORWARDS_ENABLED", "Мимикрировать репосты", "flags_media",
     "Бот передразнивает и обычные, и пересланные сообщения. Выключено — только обычные."),
    ("MIMIC_ENABLED", "Мимикрия включена", "flags_media",
     "Главный рубильник передразниваний common (список „жертв” — в „Реакции и Триггеры” → „Мимикрия”). Выключено — бот никого не передразнивает (кроме мимикрии Славика — она на своём переключателе)."),
    ("ALAN_REPLIES_ENABLED", "Reply-блок Лехи", "flags_chat_behavior",
     "Леха отвечает в ответ на сообщения. Выключено — Леха не отвечает."),
    ("DEAD_PAGE_POST_ON_JOIN", "Триггер dead page при join", "flags_chat_behavior",
     "Бот постит dead page при вступлении участника. Выключено — постится только по команде."),
    ("SUMMARY_ADMIN_ONLY", "Саммари только для админа", "flags_chat_behavior",
     "Пересказы доступны только админу. Выключено — по списку разрешённых."),
]

# ── limits: числа/таймауты/кулдауны/бюджеты ─────────────────────────────────
# (field, title_ru, type, group, description)
_LIMITS: list[tuple] = [
    ("ALAN_REPLY_INTERVAL", "Интервал ответа Лехи (сообщений)", "int", "limits_persons",
     "Через сколько сообщений Леха отвечает. 10 — примерно каждое десятое."),
    ("KOSTIK_REPLY_PROBABILITY", "Вероятность ответа Костика", "float", "limits_persons",
     "Шанс, что Костик ответит на сообщение. 0 — никогда, 1 — на каждое."),
    ("DEAD_PAGE_CAPTION_MAX_CHARS", "Макс. символов капшна dead page", "int", "limits_deadpage",
     "Максимальная длина подписи под постом. Больше — длиннее подпись."),
    ("DEAD_PAGE_COOLDOWN", "Кулдаун dead page, сек", "float", "limits_deadpage",
     "Пауза между постами dead page. Больше — бот постит реже."),
    ("DEAD_PAGE_MAX_FORWARD_RETRIES", "Ретраи подбора dead page", "int", "limits_deadpage",
     "Сколько раз бот подбирает другой пост, если не нашёл подходящий. Больше — надёжнее."),
    ("GIF_INTERVAL", "Интервал гифки (сообщений)", "int", "limits_media",
     "Через сколько сообщений бот кидает гифку. Меньше — чаще гифки."),
    ("ALAN_GREETING_COOLDOWN", "Кулдаун приветствия Лехи, сек", "int", "limits_persons",
     "Как часто Леха здоровается. Больше — реже приветствия."),
    ("ALAN_SILENCE_GREETING_HOURS", "Порог тишины Лехи, часов", "float", "limits_persons",
     "Сколько тишины в чате, чтобы Леха поприветствовал снова. Больше — реже приветствия."),
    ("SLAVIC_PHOTO_INTERVAL", "Интервал фото Славика (сообщений)", "int", "limits_media",
     "Через сколько сообщений Славик кидает фото. Меньше — чаще фото."),
    ("COMMON_COOLDOWN", "Общий кулдаун common-медиа, сек", "float", "limits_media",
     "Общая пауза между любыми медиа-реакциями. Больше — бот спокойнее."),
    ("DANGER_COOLDOWN", "Кулдаун danger-медиа, сек", "float", "limits_media",
     "Пауза между danger-медиа. Больше — реже опасные реакции."),
    ("SELFDEV_COOLDOWN", "Кулдаун selfdev, сек", "float", "limits_media",
     "Пауза между ответами на «саморазвитие». Больше — реже реакции."),
    ("WORK_COOLDOWN", "Кулдаун work, сек", "float", "limits_media",
     "Пауза между ответами на «устал» и подобные. Больше — реже реакции."),
    ("MIMIC_MIN_WORDS", "Мин. слов для мимикрии", "int", "limits_mimic",
     "Сколько слов должно быть в сообщении, чтобы бот его передразнил. Больше — реже мимикрия."),
    ("MIMIC_COOLDOWN", "Кулдаун мимикрии, сек", "float", "limits_mimic",
     "Пауза между передразниваниями. Больше — реже мимикрия."),
    ("SLAVIK_MIMIC_MIN_WORDS", "Мин. слов для мимикрии Славика", "int", "limits_mimic",
     "Минимальная длина сообщения для мимикрии Славика. Больше — реже мимикрия."),
    ("SLAVIK_MIMIC_COOLDOWN", "Кулдаун мимикрии Славика, сек", "float", "limits_mimic",
     "Пауза между передразниваниями Славика. Больше — реже мимикрия."),
    ("OLYA_COOLDOWN", "Кулдаун Оли, сек", "float", "limits_media",
     "Пауза между реакциями на видео Оли. Больше — реже реакции."),
    ("SUMMARY_WINDOW_HOURS", "Окно генерации саммари, часов", "float", "limits_memory",
     "За какой период брать сообщения для пересказа. Больше — шире охват, но дороже."),
    ("FULL_MEMORY_RETENTION_DAYS", "Хранение сырых сообщений, дней", "int", "limits_memory",
     "Сколько дней хранить исходные сообщения. Больше — память полнее, но тяжелее."),
    ("ARCHIVE_MEMORY_RETENTION_DAYS", "Срок жизни архивных фактов, дней", "int", "limits_memory",
     "Сколько дней живут факты в архиве памяти. Больше — дольше помнит, но растёт база."),
    ("MAX_SUMMARY_PARTS", "Макс. частей ответа саммари", "int", "limits_summary",
     "На сколько частей может разбиться пересказ длинного разговора. Больше — длиннее ответ."),
    ("SUMMARY_TIMEZONE", "Часовой пояс саммари", "str", "limits_summary",
     "Часовой пояс для границ дня пересказа. Меняется, если бот в другом поясе."),
    ("SUMMARY_THROTTLE_SECONDS", "Троттлинг /summary, сек", "float", "limits_summary",
     "Минимальная пауза между запросами пересказа. Больше — реже можно просить."),
    ("SUMMARY_CHUNK_DELAY", "Пауза между чанками саммари, сек", "float", "limits_summary",
     "Пауза между частями длинного пересказа. Больше — мягче для лимитов, дольше ответ."),
    ("SUMMARY_MAX_WINDOW_MESSAGES", "Кап окна L1 (сообщений)", "int", "limits_memory",
     "Сколько сообщений максимум берётся в пересказ. Больше — полнее, но дороже."),
    ("SUMMARY_MAX_MESSAGE_CHARS", "Кап одного сообщения, символов", "int", "limits_summary",
     "Максимальная длина одного сообщения в пересказе. Больше — учитываются длинные сообщения."),
    ("SUMMARY_MAX_CONTEXT_CHARS", "Кап контекста, символов", "int", "limits_summary",
     "Потолок текста, отдаваемого нейросети. Больше — точнее, но дороже и медленнее."),
    ("SUMMARY_RAG_L2_LIMIT", "Лимит RAG L2", "int", "limits_graph",
     "Сколько фактов памяти берётся на втором уровне. Больше — контекстнее, дороже."),
    ("SUMMARY_RAG_L3_LIMIT", "Лимит RAG L3", "int", "limits_graph",
     "Сколько фактов памяти берётся на третьем уровне. Больше — точнее, дороже."),
    ("SUMMARY_COMPRESS_BATCH", "Размер пачки сжатия L3", "int", "limits_summary",
     "Сколько сообщений сжимается за раз. Больше — быстрее, но грубее."),
    ("SUMMARY_RETRY_ONCE_PAUSE", "Пауза повтора генерации, сек", "float", "limits_summary",
     "Пауза перед повторной попыткой, если пересказ не удался. Больше — терпеливее."),
    ("SUMMARY_STREAM_EDIT_INTERVAL_PRIVATE", "Темп стрим-правок (приват)", "float", "limits_summary",
     "Как часто обновлять пересказ в личной переписке. Меньше — живее, но больше правок."),
    ("SUMMARY_STREAM_EDIT_INTERVAL_GROUP", "Темп стрим-правок (группа)", "float", "limits_summary",
     "Как часто обновлять пересказ в группе. Меньше — живее, но больше правок."),
    ("GRAPH_EDGE_WEIGHT_INCREMENT", "Инкремент веса ребра графа", "int", "limits_graph",
     "Насколько растёт связь между людьми и темами при упоминании. Больше — быстрее запоминает связи."),
    ("GRAPH_TOP_EDGES_LIMIT", "Связей-рёбер в саммари", "int", "limits_graph",
     "Сколько связей показывать в пересказе. Больше — подробнее, но длиннее."),
    ("GRAPH_EXTRACT_MAX_TRIPLETS", "Макс. триплетов за extraction", "int", "limits_graph",
     "Сколько фактов вытаскивать за один проход. Больше — полнее, но дороже."),
    ("GRAPH_FACT_TTL_DAYS", "TTL фактов графа, дней", "int", "limits_graph",
     "Срок жизни факта без упоминаний. Больше — дольше помнит."),
    ("GRAPH_RAG_FACTS_LIMIT", "Top-K фактов RAG", "int", "limits_graph",
     "Сколько фактов берётся для ответа по памяти. Больше — контекстнее, дороже."),
    ("GRAPH_RAG_CONTEXT_MAX_CHARS", "Потолок XML-контекста RAG", "int", "limits_graph",
     "Максимальный размер фактов, отдаваемых нейросети. Больше — точнее, дороже."),
    ("MEMORY_COMMANDS_REMEMBER_TTL_DAYS", "Срок «запомни» для участников, дней (0 = вечно)", "int", "limits_memory",
     "Через сколько дней забывается факт из «запомни» (origin user_memory). Пусто/0 — хранить вечно."),
    ("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", "Ретраи memorize-батча", "int", "limits_graph",
     "Сколько раз повторить сохранение фактов при сбое. Больше — надёжнее."),
    ("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", "Backoff memorize-батча, сек", "float", "limits_graph",
     "Пауза перед повтором сохранения фактов. Больше — спокойнее при сбоях."),
    ("SEARCH_MAX_SYMBOLS", "Длина ответа поиска, символов", "int", "limits_search",
     "Максимальная длина ответа поиска. Больше — ответ подробнее, но генерируется дольше и дороже."),
    ("FACTCHECK_MAX_SYMBOLS", "Длина ответа фактчека, символов", "int", "limits_factcheck",
     "Максимальная длина проверки фактов. Больше — подробнее, но дольше и дороже."),
    ("SEARCH_COOLDOWN_SECONDS", "Кулдаун поиска, сек", "float", "limits_cooldowns",
     "Пауза между поисковыми запросами. Больше — бот реже ищет в интернете и меньше нагружает поисковые сервисы."),
    ("FACTCHECK_COOLDOWN_SECONDS", "Кулдаун фактчека, сек", "float", "limits_cooldowns",
     "Пауза между проверками фактов. Больше — бот реже проверяет."),
    ("YOUTUBE_MAX_SYMBOLS", "Лимит YouTube, символов", "int", "limits_youtube_web",
     "Максимальная длина пересказа видео. Больше — подробнее, но дольше и дороже."),
    ("WEBPAGE_MAX_SYMBOLS", "Лимит веб-страниц, символов", "int", "limits_youtube_web",
     "Максимальная длина пересказа страницы. Больше — подробнее, но дольше и дороже."),
    ("YOUTUBE_COOLDOWN_SECONDS", "Кулдаун YouTube, сек", "float", "limits_cooldowns",
     "Пауза между пересказами видео. Больше — бот реже пересказывает."),
    ("WEBPAGE_COOLDOWN_SECONDS", "Кулдаун веб-страниц, сек", "float", "limits_cooldowns",
     "Пауза между пересказами страниц. Больше — бот реже пересказывает."),
    ("CHECKUP_COOLDOWN_SECONDS", "Кулдаун чекапа, сек", "float", "limits_cooldowns",
     "Пауза между запросами сводки о здоровье. Больше — реже чекап."),
    ("CHECKUP_MAX_SYMBOLS", "Длина ответа чекапа, символов", "int", "limits_checkup",
     "Максимальная длина сводки о здоровье. Больше — подробнее, но дольше и дороже."),
    ("CHECKUP_MAX_INPUT_SYMBOLS", "Потолок входа чекапа, символов", "int", "limits_checkup",
     "Сколько данных максимум берётся для сводки. Больше — полнее, но дороже."),
    ("INFO_COOLDOWN_SECONDS", "Кулдаун /info, сек", "float", "limits_cooldowns",
     "Пауза между запросами справки. Больше — реже отдаётся справка."),
    ("CHAT_GLOBAL_CONTEXT_LIMIT", "Сообщений фона <Global_Context>", "int", "limits_chat",
     "Сколько сообщений бот помнит из фона разговора. Больше — контекстнее, но дороже."),
    ("CHAT_BURST_LIMIT", "Обращений подряд до кулдауна", "int", "limits_chat",
     "Сколько обращений подряд без перерыва разрешено. Меньше — бот чаще уходит в паузу."),
    ("CHAT_COOLDOWN_SECONDS", "Кулдаун direct_chat, сек", "float", "limits_chat",
     "Пауза между ответами в прямом чате. Больше — бот реже отвечает."),
    ("CHAT_DIRECT_REPLY_TTL_DAYS", "TTL bot_direct_reply-фактов, дней", "int", "limits_chat",
     "Сколько дней помнить, что бот уже отвечал человеку. Пусто = 30 (дефолт), 0 = вечно. Больше — дольше помнит."),
    ("CHAT_GLOBAL_CONTEXT_MAX_CHARS", "Потолок <Global_Context>, символов", "int", "limits_chat",
     "Максимальный размер фона разговора. Больше — точнее, но дороже."),
    ("CHAT_THREAD_MAX_DEPTH", "Глубина <Conversation_Thread>", "int", "limits_chat",
     "Сколько последних сообщений видеть в ветке. Больше — контекстнее, но дороже."),
    ("CHAT_THREAD_MAX_CHARS", "Потолок <Conversation_Thread>, символов", "int", "limits_chat",
     "Максимальный размер ветки. Больше — точнее, но дороже."),
    ("SMART_CACHE_TTL_SECONDS", "TTL smart_cache, сек", "int", "limits_smart_cache",
     "Сколько хранить готовый ответ на повторный вопрос. Больше — быстрее отвечает, но память засоряется."),
    ("SMART_CACHE_MAX_ROWS", "Потолок строк smart_cache", "int", "limits_smart_cache",
     "Сколько готовых ответов максимум хранить. Больше — больше попаданий, но тяжелее."),
    ("CHAT_LOCK_WAIT_SECONDS", "Таймаут per-chat замка, сек", "float", "limits_chat",
     "Сколько ждать, пока чат освободится. Больше — терпеливее, но дольше тишина."),
    ("CHAT_LOCK_MAX_ENTRIES", "Потолок словаря замков", "int", "limits_chat",
     "Технический: сколько чатов держать в памяти замков. Обычно не трогать."),
    ("GRAPH_DEDUP_SIMILARITY_HIGH", "Порог дедупа HIGH", "float", "limits_graph",
     "Выше порога — факты считаются дублями. Больше — реже дубли, но грязнее память."),
    ("GRAPH_DEDUP_SIMILARITY_LOW", "Порог дедупа LOW", "float", "limits_graph",
     "Нижний порог похожести. Больше — реже считаются дублями, но память грязнее; меньше — чаще объединяются похожие факты."),
    ("GRAPH_DEDUP_WEIGHT_BONUS", "Бонус веса при подтверждении", "float", "limits_graph",
     "Насколько растёт факт, когда его повторили. Больше — важнее повторения."),
    ("GRAPH_UNCONFIRMED_RETENTION_DAYS", "Ретенция unconfirmed, дней", "int", "limits_graph",
     "Сколько жить неподтверждённым фактам. Больше — дольше шанс подтвердиться."),
    ("MEMORY_BACKUP_KEEP", "Ротация бэкапов (файлов)", "int", "limits_memory",
     "Сколько последних бэкапов хранить. Больше — надёжнее, но тяжелее на диске."),
    ("MEMORY_BACKUP_HOUR", "Час бэкапа (HH:MM)", "str", "limits_memory",
     "Во сколько создавать бэкап памяти. Лучше ночь — меньше нагрузка."),
    ("EMBED_CACHE_TTL_DAYS", "TTL кэша эмбеддингов, дней", "int", "limits_memory",
     "Сколько хранить «отпечатки» текстов. Больше — быстрее поиск, но тяжелее."),
    ("EMBED_CACHE_MAX_ROWS", "Потолок строк кэша эмбеддингов", "int", "limits_memory",
     "Сколько «отпечатков» максимум хранить. Больше — больше попаданий, но тяжелее."),
    ("DB_WAL_CHECKPOINT_HOURS", "Период WAL-checkpoint, часов", "int", "limits_service",
     "Технический: как часто ужимать журнал БД. Обычно не трогать."),
    ("FACTCHECK_CONTEXT_MESSAGES", "Окно контекста фактчека (сообщений)", "int", "limits_factcheck",
     "Сколько сообщений берётся для проверки факта. Больше — точнее, но дороже."),
    ("SEARCH_CONTEXT_MESSAGES", "Окно контекста поиска (сообщений)", "int", "limits_search",
     "Сколько сообщений берётся для поиска. Больше — точнее, но дороже."),
    ("CHAT_CONTEXT_FILL_RATIO", "Порог заполнения окна (доля)", "float", "limits_chat",
     "При заполнении доли окна бот начинает сжимать контекст. Меньше — раньше сжимает."),
    ("CHAT_RUNNING_SUMMARY_TAIL", "Хвост бегущего конспекта", "int", "limits_chat",
     "Сколько последних сообщений всегда держать рядом с конспектом. Больше — живее, но дороже."),
    ("RUNNING_SUMMARY_TTL_MINUTES", "TTL бегущего конспекта, минут", "int", "limits_chat",
     "Сколько живёт бегущий конспект без обновлений. Больше — дольше помнит."),
    ("CHAT_GLOBAL_CONTEXT_MAX_TOKENS", "Потолок глобального контекста, токенов", "int", "limits_chat",
     "Максимальный размер фона в токенах. Больше — точнее, но дороже."),
    ("CHAT_THREAD_MAX_TOKENS", "Потолок треда, токенов", "int", "limits_chat",
     "Максимальный размер ветки в токенах. Больше — точнее, но дороже."),
    ("SUMMARY_MAX_CONTEXT_TOKENS", "Потолок контекста саммари, токенов", "int", "limits_summary",
     "Максимальный размер пересказа в токенах. Больше — полнее, но дороже."),
    ("CHAT_SILENCE_AFTER_COOLDOWNS", "Кулдаунов подряд до молчания", "int", "limits_chat_behavior",
     "Сколько кулдаунов подряд до «молчания». Меньше — бот быстрее замолкает."),
    ("CHAT_STYLE_ANCHORS_COUNT", "Число стилевых якорей", "int", "limits_chat_behavior",
     "Сколько фраз помнить для копирования стиля. Больше — точнее, но дороже."),
    ("CHAT_STYLE_ANCHOR_MAX_CHARS", "Обрезка якоря, символов", "int", "limits_chat_behavior",
     "Длина одной фразы-якоря. Больше — полнее, но дороже."),
    ("TYPING_INTERVAL_SECONDS", "Интервал «печатает…», сек", "float", "limits_chat_behavior",
     "Как часто обновлять индикатор «печатает…». Меньше — живее, но больше запросов."),
    ("CHAT_TEMPERATURE_PRECISE", "Temperature: точный", "float", "limits_temperature",
     "Насколько строго бот отвечает в режиме «точный». Больше — свободнее, меньше — суше."),
    ("CHAT_TEMPERATURE_BALANCED", "Temperature: сбалансированный", "float", "limits_temperature",
     "Насколько свободно отвечает в режиме «сбалансированный». Больше — креативнее."),
    ("CHAT_TEMPERATURE_CHATTY", "Temperature: болтливый", "float", "limits_temperature",
     "Насколько вольные ответы в режиме «болтливый». Больше — креативнее и непредсказуемее."),
    ("CHAT_TEMPERATURE_PRESET_DEFAULT", "Temperature-пресет по умолчанию", "str", "limits_temperature",
     "Какой режим свободы ответов используется по умолчанию. Точный — строже, болтливый — вольнее."),
    ("GRAPH_FACT_WEIGHT_DIRECT", "Стартовый вес прямых фактов", "float", "limits_graph",
     "Сколько весит факт, сказанный напрямую. Больше — важнее прямые слова."),
    ("GRAPH_FACT_WEIGHT_ARCHIVE", "Стартовый вес архивных фактов", "float", "limits_graph",
     "Сколько весит факт из архива. Больше — важнее архивные факты."),
    ("GRAPH_EPISODE_MERGE_INTERVAL_DAYS", "Интервал слияния эпизодов, дней", "int", "limits_graph",
     "Как часто сливать похожие эпизоды памяти. Меньше — чаще чистка."),
    ("GRAPH_EPISODE_MERGE_BATCH", "Пачка кластеров за прогон", "int", "limits_graph",
     "Сколько кластеров сливать за раз. Больше — быстрее, но тяжелее прогон."),
    ("GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER", "Потолок фактов в кластере", "int", "limits_graph",
     "Сколько фактов максимум в слитом эпизоде. Больше — полнее, но грубее."),
    ("GRAPH_TIME_DECAY_HALF_LIFE_DAYS", "Half-life time-decay, дней", "float", "limits_graph",
     "Через сколько дней факт вдвое теряет вес. Меньше — быстрее забывает."),
    ("GRAPH_TIME_DECAY_FLOOR", "Пол time-decay", "float", "limits_graph",
     "Минимальный вес, ниже которого факт не падает. Больше — старые факты важнее."),
    ("GRAPH_FACTS_PER_USER_QUOTA", "Квота фактов на человека", "int", "limits_graph",
     "Сколько фактов максимум помнить на человека. Больше — полнее память, но тяжелее."),
    ("GRAPH_FACT_TOUCH_EXTEND_DAYS", "Продление TTL при touch, дней", "int", "limits_graph",
     "На сколько продлевается факт при упоминании. Больше — дольше живут важные факты."),
    ("GRAPH_MMR_LAMBDA", "MMR-λ (0..1)", "float", "limits_graph",
     "Насколько разнообразными брать факты. 0 — только похожие, 1 — максимум разнообразия."),
    ("GRAPH_MMR_FETCH_K", "MMR fetch_k", "int", "limits_graph",
     "Сколько фактов сначала берётся для разнообразия. Больше — качественнее, но дороже."),
    ("GRAPH_REVIEW_INTERVAL_DAYS", "Интервал пересмотра, дней", "int", "limits_graph",
     "Как часто бот пересматривает память. Меньше — чаще чистка."),
    ("GRAPH_COMPRESSION_LOG_RETENTION_DAYS", "Ретенция лога сжатий, дней", "int", "limits_graph",
     "Сколько хранить историю сжатий памяти. Больше — дольше диагностика."),
    ("CHAT_CONTEXT_BUDGET_TOKENS", "Бюджет контекста direct_chat, токенов", "int", "limits_chat_budgets",
     "Общий потолок токенов на ответ в прямом чате. Больше — полнее, но дороже."),
    ("CHAT_BUDGET_MAP_RATIO", "Доля бюджета: MAP", "float", "limits_chat_budgets",
     "Доля контекста на карту памяти. Больше — важнее карта."),
    ("CHAT_BUDGET_GLOBAL_RATIO", "Доля бюджета: Global", "float", "limits_chat_budgets",
     "Доля контекста на фон разговора. Больше — важнее фон."),
    ("CHAT_BUDGET_THREAD_RATIO", "Доля бюджета: Thread", "float", "limits_chat_budgets",
     "Доля контекста на ветку. Больше — важнее ветка."),
    ("CHAT_BUDGET_RAG_RATIO", "Доля бюджета: RAG", "float", "limits_chat_budgets",
     "Доля контекста на факты памяти. Больше — важнее память."),
    ("CHAT_BUDGET_TARGET_RATIO", "Доля бюджета: Target", "float", "limits_chat_budgets",
     "Доля контекста на целевое сообщение. Больше — важнее само сообщение."),
    ("CHAT_BUDGET_ANCHORS_RATIO", "Доля бюджета: Anchors", "float", "limits_chat_budgets",
     "Доля контекста на стилевые якоря. Больше — важнее стиль."),
    ("CHAT_BUDGET_RESPONSE_RATIO", "Доля бюджета: Response", "float", "limits_chat_budgets",
     "Доля контекста на сам ответ. Больше — место под ответ."),
    ("CHAT_BUDGET_RESERVE_RATIO", "Доля бюджета: Reserve", "float", "limits_chat_budgets",
     "Запасной резерв бюджета. Больше — запас на непредвиденное."),
    ("CHAT_DEDUP_TTL_SECONDS", "TTL дедуп-записи, сек", "int", "limits_chat",
     "Как долго помнить одинаковые сообщения подряд. Больше — дольше дедуп."),
    # SUMMARY_ALIASES — 6-элементная запись: последний элемент widget
    # («keyvalue» → KV-редактор пар «Telegram ID → имя» на фронте, FR-28).
    ("SUMMARY_ALIASES", "JSON-словарь алиасов имён", "json", "limits_user_aliases",
     "Как бот обращается к людям: алиас → имя → никнейм. Пары ID → имя — например {\"138811255\": \"Леха\"}.",
     "keyvalue"),
    ("YOUTUBE_TRANSCRIPT_PROXY_DOMAIN", "Домен прокси-оверрайда", "str", "limits_youtube_proxy",
     "Домен прокси, если используете не Webshare. Пусто — берётся стандартный."),
    ("YOUTUBE_TRANSCRIPT_PROXY_PORT", "Порт прокси-оверрайда", "str", "limits_youtube_proxy",
     "Порт прокси, если используете не Webshare. Пусто — берётся стандартный."),
    ("YOUTUBE_TRANSCRIPT_PROXY_LOCATIONS", "CSV-коды стран Webshare", "str", "limits_youtube_proxy",
     "Коды стран для прокси (например, de,us) — трафик будет выходить оттуда. Пусто — без ограничений."),
    ("YOUTUBE_TRANSCRIPT_PROXY_RETRIES", "Повторы при блокировке (Webshare)", "int", "limits_youtube_proxy",
     "Сколько раз повторять запрос субтитров, если прокси заблокировали. Больше — надёжнее, но медленнее."),
    ("DOWNLOAD_COOLDOWN", "Кулдаун скачивания, сек", "float", "limits_media",
     "Пауза между командами скачивания. Больше — реже можно качать."),
    ("VOICE_MAX_DURATION_SECONDS", "Макс. длительность войса, сек", "int", "limits_media",
     "Длиннее этого войса не расшифровываются. Больше — длиннее можно."),
    ("VIDEO_TRANSCRIBE_MAX_SIZE_MB", "Макс. размер видео для расшифровки, МБ",
     "int", "limits_media",
     "Видео больше этого размера по командам „транскрипт/че за видос/…” не расшифровывается. Проверяется по file_size ДО скачивания."),
    ("VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS", "Макс. длительность видео для расшифровки, сек",
     "int", "limits_media",
     "Видео длиннее не расшифровывается. Telegram отдаёт длительность для видео-сообщений; у документов проверки длительности нет."),
    # ── Раунд 3 (видео-пайплайн): медиа-шара + STT-надёжность ──
    ("MEDIA_SHARE_TTL_SECONDS", "TTL опубликованного видео, сек", "int", "limits_media",
     "Сколько секунд OpenRouter может «посмотреть» ролик по временной ссылке. Меньше 60 игнорируется (900)."),
    ("MEDIA_SHARE_MAX_MB", "Потолок публикации видео, МБ", "int", "limits_media",
     "Файл больше не публикуется — пересказ честно уходит на STT/фразы. Больше — тяжелее мультимодалка."),
    ("VIDEO_STT_TIMEOUT_SECONDS", "Таймаут STT видео, сек", "float", "limits_media",
     "Сколько ждать ОДНУ стратегию распознавания для видео-файлов (перекрывает Groq/OpenRouter таймауты). Голосовые не трогает."),
    ("VIDEO_SUMMARY_MIN_CHARS", "Мин. символов транскрипта для выжимки", "int", "limits_media",
     "Короче транскрипта выжимка не строится — честная фраза «нет речи». Больше — строже."),
    ("STT_GROQ_MAX_UPLOAD_MB", "Потолок загрузки Groq STT, МБ", "int", "limits_media",
     "Файл больше Groq-стратегия пропускается (лимит upload). Больше — риск HTTP 400."),
    ("STT_OPENROUTER_MAX_UPLOAD_MB", "Потолок загрузки OpenRouter STT, МБ", "int", "limits_media",
     "Файл больше OpenRouter-стратегия пропускается (base64 input_audio). Больше — риск HTTP 400."),
]

# ── reactions: id-списки, слова, пути, названия (не секреты) ────────────────
# (field, title_ru, type, group, description)
_REACTIONS: list[tuple] = [
    ("SLAVIK_USER_ID", "Telegram ID Славика", "int", "reactions_persons",
     "Telegram ID Славика — по нему бот понимает, чьи сообщения «славиковские»."),
    ("KOSTIK_USER_ID", "Telegram ID Костика", "int", "reactions_persons",
     "Telegram ID Костика — для его ответов и мимикрии."),
    ("ALAN_USER_ID", "Telegram ID Лехи", "int", "reactions_persons",
     "Telegram ID Лехи — для приветствий и reply-блока."),
    ("ADMIN_USER_ID", "Telegram ID админа", "int", "reactions_persons",
     "Telegram ID администратора — для особых прав и реакций."),
    ("DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "Канал-источник dead page (@d_pages)", "str", "reactions_deadpage",
     "Откуда берутся посты dead page. Указывается с @."),
    ("DEAD_PAGE_SOURCE_CHANNEL_ID", "ID канала-источника dead page", "int", "reactions_deadpage",
     "Числовой ID канала-источника. Меняется, если пересоздали канал."),
    ("DEAD_PAGE_RELAY_CHANNEL_ID", "ID relay-канала dead page", "int", "reactions_deadpage",
     "Куда бот пересылает посты dead page."),
    ("DEAD_PAGE_DIR", "Папка медиа dead page", "str", "reactions_deadpage",
     "Папка с медиа для постов dead page. Относительно корня медиа."),
    ("ALAN_USERNAME", "Юзернейм Лехи", "str", "reactions_persons",
     "Юзернейм Лехи — для упоминаний и фильтров."),
    ("ALAN_GREETING_DIR", "Папка приветствий Лехи", "str", "reactions_alan",
     "Папка с видео-приветствиями Лехи. Относительно корня медиа."),
    ("WAR_CHANNEL_IDS", "CSV ID каналов war-алертов", "str", "reactions_war",
     "Каналы, где бот следит за военными алертами. Через запятую."),
    ("WAR_CHANNEL_USERNAMES", "CSV юзернеймов war-алертов", "str", "reactions_war",
     "Юзернеймы каналов-алертов. Через запятую."),
    ("WAR_REPLIES", "CSV фраз war-алертов", "str", "reactions_war",
     "Фразы-реакции на алерты. Через запятую."),
    ("SLAVIC_RANDOM_DIR", "Папка рандомных фото Славика", "str", "reactions_slavik",
     "Папка, откуда Славик кидает случайные фото. Относительно корня медиа."),
    ("SLAVIC_PHOTO_PATH", "Одиночное фото Славика (deprecated)", "str", "reactions_slavik",
     "Старое поле одиночного фото. Лучше использовать папку рандомных фото."),
    ("COMMON_MEDIA_BASE", "Базовая папка common-медиа", "str", "reactions_common",
     "Корень медиа-реакций (otboy/danger/selfdev/work). Относительно корня медиа."),
    ("DANGER_WORDS", "CSV danger-слов", "str", "reactions_common",
     "Слова-триггеры danger-медиа. Через запятую."),
    ("GIF_PATH", "Файл гифки", "str", "reactions_slavik",
     "Путь к файлу гифки. Относительно корня медиа."),
    ("GOODMORNING_TIME", "Время рассылки (HH:MM)", "str", "reactions_goodmorning",
     "Во сколько бот шлёт утреннюю рассылку. 24-часовой формат."),
    ("GOODMORNING_TZ", "Часовой пояс рассылки", "str", "reactions_goodmorning",
     "Часовой пояс, в котором считается время рассылки. Например, Europe/Moscow."),
    ("GOODMORNING_TARGET_CHAT_IDS", "Список чатов рассылки", "json", "reactions_goodmorning",
     "Куда слать утреннюю рассылку. Список ID чатов."),
    ("GOODMORNING_MEDIA_DIR", "Папка утреннего медиа", "str", "reactions_goodmorning",
     "Папка с медиа для утренней рассылки. Относительно корня медиа."),
    ("MIMIC_VICTIM_USER_IDS", "CSV ID жертв мимикрии", "str", "reactions_mimic",
     "Кого передразнивает бот. Через запятую."),
    ("ALAN_MIMIC_ENABLED", "Мимикрия Лехи", "bool", "reactions_mimic",
     "Передразнивать сообщения Лехи (нужно также включить общий рубильник „Мимикрия включена”). Других „жертв” из списка этот тумблер не касается."),
    ("VASYA_ENABLED", "Реакция „Вася → АДМИН”", "bool", "reactions_word_reactions",
     "Кто-то написал „Вася” — бот отвечает „АДМИН”; кто-то написал „админ” — бот отвечает „ВАСЯ”. Выключено — реакция молчит."),
    ("KUCHA_ENABLED", "Реакция „куча → ДАЛБАЕБ”", "bool", "reactions_word_reactions",
     "Кто-то написал „куча” — бот отвечает „ДАЛБАЕБ”. Выключено — реакции нет (гифка Славика работает независимо)."),
    ("OLYA_USER_ID", "Telegram ID Оли", "int", "reactions_persons",
     "Telegram ID Оли — для реакций на её видео."),
    ("OLYA_MEDIA_BASE", "Папка медиа Оли", "str", "reactions_olya",
     "Папка с медиа-ответами Оли. Относительно корня медиа."),
    ("OLYA_SAVEASBOT_CHANNEL_IDS", "Канальные ID SaveAsBot", "json", "reactions_olya",
     "Каналы, где Оля реагирует на SaveAsBot. Список ID."),
    ("OLYA_SAVEASBOT_USER_IDS", "Юзер-ID SaveAsBot", "json", "reactions_olya",
     "Пользователи, чьи сообщения Оля ловит по SaveAsBot. Список ID."),
    ("OLYA_CAPTION_TEXT", "Текст капшна Оли", "str", "reactions_olya",
     "Подпись под ответами Оли. Можно менять без перезапуска."),
    ("OLYA_MEDIA_TYPE", "Тип медиа Оли (video/...)", "str", "reactions_olya",
     "Чем отвечает Оля: видео, фото и так далее."),
    ("ALLOWED_SUMMARY_IDS", "Список ID для /summary", "json", "reactions_summary",
     "Кому доступен /summary, если включён «только админ»."),
    ("SUMMARY_TARGET_CHAT_IDS", "Список чатов саммари", "json", "reactions_summary",
     "В каких чатах собирать пересказы. Список ID."),
    ("CHAT_BOTWORD_PATTERN", "Regex-триггер «бот»-семьи", "str", "reactions_chat",
     "Шаблон-триггер прямых обращений к боту. Изменять осторожно."),
    ("CHAT_MOOD_NEGATIVE_WORDS", "CSV негативных слов", "str", "reactions_chat",
     "Слова, по которым бот определяет плохое настроение. Через запятую."),
    ("CHAT_MOOD_POSITIVE_WORDS", "CSV позитивных слов", "str", "reactions_chat",
     "Слова, по которым бот определяет хорошее настроение. Через запятую."),
    ("MEMORY_BACKUP_DIR", "Папка бэкапов памяти", "str", "reactions_memory",
     "Куда складывать бэкапы памяти. Относительно корня медиа."),
]


# ── memory: бессрочное хранение (фаза 2, T-755) ────────────────────────────
# (field, title_ru, type, group, description)
_MEMORY: list[tuple] = [
    ("INFINITE_RETENTION", "Бессрочное хранение памяти", "bool",
     "memory_infinite",
     "Отключает сжатие/удаление сырья и TTL-очистки памяти: всё хранится "
     "бессрочно (импорт истории)."),
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
        field, title, typ, secret, group, desc = row
        add(ParamSpec(field, field, CATEGORY_KEYS, title, typ, secret=secret,
                      group=group, description=desc))
    for row in _MODELS:
        field, title, typ, group, desc = row
        add(ParamSpec(field, field, CATEGORY_MODELS, title, typ,
                      group=group, description=desc))
    for row in _FLAGS:
        field, title, group, desc = row
        add(ParamSpec(field, field, CATEGORY_FLAGS, title, "bool",
                      group=group, description=desc))
    for row in _LIMITS:
        if len(row) == 6:      # (field, title, type, group, desc, widget)
            field, title, typ, group, desc, widget = row
        else:
            field, title, typ, group, desc = row
            widget = ""
        add(ParamSpec(field, field, CATEGORY_LIMITS, title, typ,
                      group=group, description=desc, widget=widget))
    for row in _REACTIONS:
        field, title, typ, group, desc = row
        add(ParamSpec(field, field, CATEGORY_REACTIONS, title, typ,
                      group=group, description=desc))
    for row in _CONTENT_SETTINGS:
        field, title, typ, group, desc = row
        add(ParamSpec(field, field, CATEGORY_CONTENT, title, typ,
                      group=group, description=desc))
    for spec_id, title, code_source, group, desc in _PROMPTS:
        add(ParamSpec(None, None, CATEGORY_PROMPTS, title, "str",
                      code_source=code_source, pg_id=spec_id,
                      group=group, description=desc))
    for spec_id, title, group, desc in _CONTENT:
        add(ParamSpec(None, None, CATEGORY_CONTENT, title, "json",
                      pg_id=spec_id, group=group, description=desc))
    for field, title, typ, group, desc in _MEMORY:
        add(ParamSpec(field, field, CATEGORY_MEMORY, title, typ,
                      group=group, description=desc,
                      pg_id=f"{CATEGORY_MEMORY}.infinite_retention"))
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


_GROUPS_BY_ID: dict[str, GroupSpec] = {g.id: g for g in GROUPS}
_GROUPS_BY_CATEGORY: dict[str, list[GroupSpec]] = {}
for _g in GROUPS:
    _GROUPS_BY_CATEGORY.setdefault(_g.category, []).append(_g)
for _lst in _GROUPS_BY_CATEGORY.values():
    _lst.sort(key=lambda g: g.order)


def get_group(group_id: str) -> GroupSpec | None:
    """84.24.1: группа по id (None — нет такой группы)."""
    return _GROUPS_BY_ID.get(group_id)


def groups_by_category(category: str) -> list[GroupSpec]:
    """84.24.1: группы категории, отсортированные по order."""
    return list(_GROUPS_BY_CATEGORY.get(category, []))


def group_order(group_id: str) -> int:
    """84.24.1: order группы (для сортировки items; неизвестная — 999)."""
    g = _GROUPS_BY_ID.get(group_id)
    return g.order if g else 999


# ── Эпик 04.09.2026 (3.5.1, FR-25/FR-27): маппинг вкладок админки ───────────
# Бэк-контракт для фронта (TABS) и теста-аудита «каждая группа ровно на одной
# конфиг-вкладке». Правило: (категория, выбор групп) где выбор —
#   None                     → вся категория;
#   frozenset({группы})      → ровно перечисленные группы;
#   ("except", frozenset)    → вся категория, кроме перечисленных групп.
# Конфиг-вкладки покрывают ВСЕ группы категорий models/keys/prompts/limits/
# flags/reactions ровно один раз (не-конфиг вкладки «Доступы»/«Статус»/
# «Как это работает» здесь не участвуют).
TAB_LLM_PROVIDERS = "llm_providers"
TAB_PROMPTS = "prompts"
TAB_LIMITS = "limits"
TAB_MEMORY_RAG = "memory_rag"
TAB_REACTIONS_TRIGGERS = "reactions_triggers"

CONFIG_TAB_TITLES: dict[str, str] = {
    TAB_LLM_PROVIDERS: "LLM Провайдеры",
    TAB_PROMPTS: "Промпты",
    TAB_LIMITS: "Лимиты",
    TAB_MEMORY_RAG: "Память и RAG",
    TAB_REACTIONS_TRIGGERS: "Реакции и Триггеры",
}

_GROUPS_LIMITS_MEMORY_GRAPH = frozenset({"limits_memory", "limits_graph"})
_GROUPS_FLAGS_MEDIA_MEMORY = frozenset({"flags_memory", "flags_media"})

TAB_RULES: tuple[tuple[str, tuple[tuple[str, object], ...]], ...] = (
    (TAB_LLM_PROVIDERS, (
        (CATEGORY_MODELS, None),
        (CATEGORY_KEYS, None),
    )),
    (TAB_PROMPTS, (
        (CATEGORY_PROMPTS, None),
    )),
    (TAB_LIMITS, (
        (CATEGORY_LIMITS, ("except", _GROUPS_LIMITS_MEMORY_GRAPH)),
        (CATEGORY_FLAGS, ("except", _GROUPS_FLAGS_MEDIA_MEMORY)),
    )),
    (TAB_MEMORY_RAG, (
        (CATEGORY_LIMITS, frozenset({"limits_memory", "limits_graph"})),
        (CATEGORY_FLAGS, frozenset({"flags_memory"})),
        (CATEGORY_MEMORY, None),
    )),
    (TAB_REACTIONS_TRIGGERS, (
        (CATEGORY_REACTIONS, None),
        (CATEGORY_FLAGS, frozenset({"flags_media"})),
    )),
)

_TAB_BY_GROUP: dict[str, str] = {}


def _resolve_tab_groups(category: str, rule: object) -> frozenset[str]:
    """Группы категории по правилу (None / frozenset / ("except", set))."""
    all_groups = frozenset(g.id for g in _GROUPS_BY_CATEGORY.get(category, ()))
    if rule is None:
        return all_groups
    if isinstance(rule, frozenset):
        return rule & all_groups
    kind, excluded = rule
    if kind == "except":
        return all_groups - excluded
    return all_groups


for _tab_id, _tab_rules in TAB_RULES:
    for _category, _rule in _tab_rules:
        for _gid in _resolve_tab_groups(_category, _rule):
            _prev = _TAB_BY_GROUP.get(_gid)
            if _prev is not None and _prev != _tab_id:
                raise ValueError(
                    f"duplicate tab assignment for group {_gid}: {_prev} vs {_tab_id}")
            _TAB_BY_GROUP[_gid] = _tab_id


def tab_group_ids(tab_id: str) -> frozenset[str]:
    """3.5.1: группы, рендерящиеся на конфиг-вкладке (для аудита/фронта)."""
    return frozenset(gid for gid, tab in _TAB_BY_GROUP.items() if tab == tab_id)


def group_tab(group_id: str) -> str | None:
    """3.5.1: вкладка группы (None — группа не конфиг-вкладки)."""
    return _TAB_BY_GROUP.get(group_id)


def config_tab_sources(tab_id: str) -> list[tuple[str, object]]:
    """3.5.1: правила-источники вкладки (категория, выбор групп) — для фронта."""
    for _tid, rules in TAB_RULES:
        if _tid == tab_id:
            return list(rules)
    return []


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
    if spec.type == "str":
        # ПРОД-ИНЦИДЕНТ (A, defense-in-depth): jsonb-значение может прийти
        # строкой JSON-текста В КАВЫЧКАХ ('"https://apinet.cloud/v1"').
        # Если распаковка даёт str — возвращаем её (ключи/URL без кавычек).
        if isinstance(value, str):
            s = value.strip()
            if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
                try:
                    inner = json.loads(s)
                    if isinstance(inner, str):
                        return inner
                except ValueError:
                    pass
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
