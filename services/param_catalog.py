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

# Раунд 10 (F-7 §4.4, Q5): категории, допустимые для per-chat-слоя.
_PER_CHAT_CATEGORIES: frozenset[str] = frozenset(
    {CATEGORY_PROMPTS, CATEGORY_LIMITS, CATEGORY_FLAGS, CATEGORY_REACTIONS,
     CATEGORY_CONTENT, CATEGORY_MEMORY}
)

# Прогрессивная разметка (F-11 §4.1): группы-маркеры «Расширенные».
_ADVANCED_GROUPS: frozenset[str] = frozenset(
    # Раунд 10.4 (C-3): dream/nostalgia вынесены из advanced-групп — их
    # рубильники размечены basic явно (_MEMORY progressive_level);
    # группы памяти/графа остаются advanced по умолчанию.
    {"limits_memory", "limits_graph", "limits_rag", "flags_memory",
     "memory_infinite"}
)

# Строковые маркеры pg_key для правила «Расширенные» (F-11 §4.1).
_ADVANCED_KEY_MARKERS: tuple[str, ...] = (
    "search_top_k", "vector", "graph", "rag", "retr", "timeout", "context",
    "summary_length", "budget", "dedup", "ttl", "window", "density", "chunk",
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
    # Раунд 10 (F-11 §4.1): уровень прогрессивного раскрытия для TMA.
    # ""/basic | "advanced" (пустое = basic; явный advanced — по правилу
    # resolve_progressive_level либо ручной разметки).
    progressive_level: str = ""
    # Раунд 10.4 (B-7): опции выпадающего списка (widget == "select");
    # len(options) == len(labels); None по умолчанию — старые записи
    # без изменений (widget ""/keyvalue — как раньше).
    select_options: tuple[str, ...] = ()
    select_labels: tuple[str, ...] = ()

    @property
    def pg_key(self) -> str:
        """Ключ bot_settings: {category}.{snake_name}."""
        if self.pg_id:
            return self.pg_id
        base = (self.settings_field or self.env_name or "").lower()
        return f"{self.category}.{base}" if self.category else base

    @property
    def per_chat(self) -> bool:
        """Раунд 10 (F-7 §4.4, Q5): параметр переносим на уровень чата.

        per_chat = (category ∈ {prompts, limits, flags, reactions, content,
        memory}) and (secret == False). models.* и keys.* — строго
        глобальные (маршрутизация/секреты; BYOK даёт пер-чат только ключ,
        не модель).
        """
        return (self.category in _PER_CHAT_CATEGORIES) and not self.secret

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


# ── 84.24.2: реестр групп (68 шт.; покрытие параметров категорий) ────────────
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
    GroupSpec("models_embeddings", "models", "Отпечатки текста и длина",
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
    GroupSpec("keys_llm", "keys", "Основная нейросеть",
              "Пароли доступа к основной и запасной нейросети.", 1),
    GroupSpec("keys_groq", "keys", "Groq",
              "Ключ распознавания голосовых.", 2),
    GroupSpec("keys_openrouter", "keys", "OpenRouter",
              "Ключ пересказов видео и страниц.", 3),
    GroupSpec("keys_search", "keys", "Поиск: Exa и Tavily",
              "Ключи интернет-поиска.", 4),
    GroupSpec("keys_betterstack", "keys", "Логи и чек-ап",
              "Логин и пароль SQL-базы для чекапа.", 5),
    GroupSpec("keys_youtube", "keys", "YouTube: прокси и пропуска",
              "Прокси и сохранённые пропуска браузера для субтитров YouTube.", 6),
    GroupSpec("keys_media", "keys", "Медиа-шара",
              "Секрет подписи временных ссылок на видео (раунд 3).", 7),
    # ── limits (28; раунд 10.6 T-1180/T-1208) ──────────────────────────────
    # Расщепления: limits_media→4, limits_persons→2, limits_youtube_web→2,
    # limits_cooldowns→растворена, limits_chat_budgets→+limits_rag.
    GroupSpec("limits_alan", "limits", "Леха: лимиты",
              "Частота ответов и приветствий Лехи.", 1),
    GroupSpec("limits_kostik", "limits", "Костик: лимиты",
              "Вероятность ответа Костика.", 2),
    GroupSpec("limits_media_permsoc", "limits", "Медиа-реакции (PERMsoc)",
              "Частота гифок/фото, паузы common-медиа, Оля.", 3),
    GroupSpec("limits_mimic", "limits", "Мимикрия",
              "Правила передразнивания: минимальная длина и паузы.", 4),
    GroupSpec("limits_deadpage", "limits", "Dead page",
              "Подписи, паузы и повторы постов dead page.", 5),
    GroupSpec("limits_summary", "limits", "Саммари",
              "Окно сбора, длина ответа, лимиты и паузы генерации.", 6),
    GroupSpec("limits_search", "limits", "Поиск: лимиты",
              "Длина ответа, окно контекста и кулдаун поиска.", 7),
    GroupSpec("limits_factcheck", "limits", "Фактчек: лимиты",
              "Длина ответа, окно контекста и кулдаун фактчека.", 8),
    GroupSpec("limits_checkup", "limits", "Чек-ап: лимиты",
              "Длина ответа, потолок входящих данных и кулдаун.", 9),
    GroupSpec("limits_transcribe", "limits", "Транскрипт: лимиты",
              "Сколько и как долго можно расшифровывать голосовые и видео.", 10),
    GroupSpec("limits_video_summary", "limits", "Выжимка видео: лимиты",
              "Минимум текста для выжимки, публикация и срок жизни медиа-шары.", 11),
    GroupSpec("limits_media_download", "limits", "Скачивание медиа: лимиты",
              "Кулдаун скачивания видео по ссылке.", 12),
    GroupSpec("limits_youtube", "limits", "YouTube: лимиты",
              "Длина пересказа и кулдаун YouTube.", 13),
    GroupSpec("limits_web", "limits", "Веб-страницы: лимиты",
              "Длина пересказа и кулдаун веб-страниц.", 14),
    GroupSpec("limits_chat", "limits", "Прямой чат: контекст",
              "Окно контекста, ветки, паузы, замки и срок жизни записей.", 15),
    GroupSpec("limits_chat_behavior", "limits", "Прямой чат: поведение",
              "Молчание после кулдаунов, стилевые якоря, «печатает…».", 16),
    GroupSpec("limits_chat_budgets", "limits", "Прямой чат: бюджеты слов",
              "Как контекст делится между блоками (карта, ветка, память).", 17),
    GroupSpec("limits_temperature", "limits", "Температура ответов",
              "Насколько свободно и креативно отвечает прямой чат.", 18),
    GroupSpec("limits_memory", "limits", "Память",
              "Сроки хранения сообщений, фактов, бэкапов, кэша.", 19),
    GroupSpec("limits_graph", "limits", "Граф знаний",
              "Веса фактов, объединение похожих, срок жизни и квоты памяти.", 20),
    # A3/D3 (T-1208): RAG-ключи из бюджета прямого чата + дедупа RAG.
    GroupSpec("limits_rag", "limits", "Память: бюджет и повторы",
              "Доля бюджета чата на поиск по памяти и порог повторов.", 21),
    GroupSpec("limits_smart_cache", "limits", "Умный кэш",
              "Сколько хранить готовые ответы и как много строк.", 22),
    GroupSpec("limits_service", "limits", "Служебное",
              "Технические интервалы и кулдаун /info — обычно не трогать.", 23),
    GroupSpec("limits_user_aliases", "limits", "Имена людей",
              "Как бот обращается к людям: алиас → имя → никнейм.", 24),
    GroupSpec("limits_youtube_proxy", "limits", "YouTube: прокси",
              "Настройки прокси для субтитров YouTube (коды стран, повторы).", 25),
    # limits (26; раунд 7, T-776): лор чатов
    GroupSpec("limits_lore", "limits", "Лор чатов",
              "Авто-лор: пороги окна, генерация, инжект в контекст.", 26),
    # limits (27; раунд 9, T-816/T-817): отношения (A-Life)
    GroupSpec("limits_relations", "limits", "Отношения",
              "Стадии участников: пороги msg/дней, decay, анти-откат, "
              "пересчёт и капы инжекта.", 27),
    # limits (28; раунд 10, F-10 T-896): бюджет фоновых воркеров
    GroupSpec("limits_worker", "limits", "Фоновые воркеры",
              "Дневной бюджет фона: вызовы и текст, порядок деградации, "
              "размазка тиков.", 28),
    # ── flags (19; раунд 10.6 T-1201/T-1180) ───────────────────────────────
    # flags_modules(9) → 7 групп + checkup-флаг в flags_service;
    # flags_chat_behavior(11) → 3 группы; +3 master-флага (D1/A1).
    GroupSpec("flags_module_summary", "flags", "Модуль: Саммаризация",
              "Рубильники модуля саммари и стриминга пересказов.", 1),
    GroupSpec("flags_module_direct", "flags", "Модуль: Прямые ответы",
              "Рубильники прямых ответов бота и поведения в чате.", 2),
    GroupSpec("flags_module_factcheck", "flags", "Модуль: Фактчек",
              "Мастер-рубильник модуля проверки фактов.", 3),
    GroupSpec("flags_module_search", "flags", "Модуль: Поиск",
              "Мастер-рубильник модуля интернет-поиска и реранкинга.", 4),
    GroupSpec("flags_module_transcribe", "flags", "Модуль: Транскрипт",
              "Мастер-рубильник распознавания голосовых и видео.", 5),
    GroupSpec("flags_module_video_summary", "flags", "Модуль: Выжимка видео",
              "Мастер-рубильник пересказа видео.", 6),
    GroupSpec("flags_module_media_download", "flags", "Модуль: Скачивание медиа",
              "Рубильники скачивания видео и движка yt-dlp.", 7),
    GroupSpec("flags_module_web", "flags", "Модуль: Веб-страницы",
              "Мастер-рубильник пересказа веб-страниц.", 8),
    GroupSpec("flags_summary", "flags", "Саммари: доступ и стриминг",
              "Стриминг пересказов и доступ по списку/админу.", 9),
    GroupSpec("flags_chat_behavior", "flags", "Поведение в чате",
              "Стиль ответов, настроение, дедуп, importance, индикатор набора.", 10),
    GroupSpec("flags_smart_cache", "flags", "Умный кэш: рубильник",
              "Exact Match Cache — мгновенные ответы на точные повторы.", 11),
    GroupSpec("flags_throttle", "flags", "Троттлинг",
              "Общие лимиты частоты запросов между smart-модулями.", 12),
    GroupSpec("flags_service", "flags", "Служебное",
              "Технические рубильники (база, защита нейросети, метрики) — обычно не трогать.", 13),
    # flags (14; ре-дизайн 10.2, BUG-3, spec §10 B): рубильники PERMsoc
    GroupSpec("flags_permsoc", "flags", "Функции PERMsoc: рубильники",
              "Мастер-дефолт PERMsoc и под-флаги Оли/мимикрии.", 14),
    # A1/T-1182: поведенческие рубильники персон PERMsoc.
    GroupSpec("flags_permsoc_behavior", "flags", "PERMsoc: поведение персон",
              "Reply-блок Лехи и постинг dead page при вступлении.", 15),
    GroupSpec("flags_media", "flags", "Медиа и Оля",
              "Капшены, репосты, реакция Оли на видео, common-медиа.", 16),
    GroupSpec("flags_memory", "flags", "Память и граф знаний",
              "Механизмы запоминания: извлечение, дедуп, бэкапы, кэш.", 17),
    # flags (18; раунд 7, T-776): лор чатов
    GroupSpec("flags_lore", "flags", "Лор чатов",
              "Рубильники лора чатов: воркер, авто-генерация, инжект.", 18),
    # flags (19; раунд 9, T-816/T-817): отношения (A-Life)
    GroupSpec("flags_relations", "flags", "Отношения",
              "Глобальный рубильник тона по стадиям участников.", 19),
    # ── reactions (15; раунд 10.6 T-1185; 10.9: reactions_persons удалена) ──
    # Ре-дизайн 10.2, BUG-3 (spec §10 B): Telegram ID админа — отдельная
    # группа (перенос из reactions_persons).
    GroupSpec("reactions_admin", "reactions", "Админ (ID)",
              "Telegram ID админа — для особых прав и реакций бота.", 2),
    GroupSpec("reactions_deadpage", "reactions", "Dead page",
              "Канал-источник, relay-канал, папка медиа.", 3),
    GroupSpec("reactions_slavik", "reactions", "Славик",
              "Папки рандомных фото и файл гифки.", 4),
    GroupSpec("reactions_alan", "reactions", "Леха",
              "Telegram ID, юзернейм и папка видео-приветствий Лехи.", 5),
    # A2/T-1185: Костик — отдельная группа (ID).
    GroupSpec("reactions_kostik", "reactions", "Костик",
              "Telegram ID Костика — для ответов и мимикрии.", 6),
    GroupSpec("reactions_war", "reactions", "War-алерты",
              "Каналы, юзернеймы и фразы алертов.", 7),
    GroupSpec("reactions_common", "reactions", "Common-медиа",
              "Базовая папка и список danger-слов.", 8),
    GroupSpec("reactions_goodmorning", "reactions", "Утренняя рассылка",
              "Время, часовой пояс, чаты, папка медиа.", 9),
    GroupSpec("reactions_mimic", "reactions", "Мимикрия",
              "Кого передразнивать (ID «жертв»).", 10),
    GroupSpec("reactions_olya", "reactions", "Оля",
              "Папка медиа, капшены, SaveAsBot.", 11),
    GroupSpec("reactions_summary", "reactions", "Саммари",
              "Кому доступно /summary, алиасы имён, чаты.", 12),
    GroupSpec("reactions_chat", "reactions", "Прямой чат",
              "Слова-триггеры и слова настроения.", 13),
    GroupSpec("reactions_memory", "reactions", "Память",
              "Папка бэкапов памяти.", 14),
    GroupSpec("reactions_word_reactions", "reactions", "Словесные реакции",
              "Тумблеры текстовых реакций: „Вася ↔ АДМИН” и „куча → ДАЛБАЕБ”.", 15),
    # reactions (?; ре-дизайн 10.2, BUG-3, spec §10 B): реакции PERMsoc —
    # kucha-выключатель и мимикрия Лехи (перенос из word_reactions/mimic)
    GroupSpec("reactions_permsoc", "reactions", "Персонаж-реакции PERMsoc",
              "Реакции персон PERMsoc: „куча → ДАЛБАЕБ” и мимикрия Лехи.", 16),
    # content (2)
    GroupSpec("content_info", "content", "Как это работает",
              "Текст справки для пользователей.", 1),
    GroupSpec("content_media", "content", "Медиа-шара",
              "Каталог временных публикаций видео и внешний адрес.", 2),
    # memory (1; фаза 2, T-755)
    GroupSpec("memory_infinite", "memory", "Бессрочное хранение",
              "Память без сроков годности: сырьё и факты не удаляются "
              "и не сжимаются по срокам (для импорта истории).", 1),
    # memory (2; раунд 9, T-824/T-825, spec §3.6.4/Q11): «сон» (beliefs)
    GroupSpec("memory_dream", "memory", "Синтез (сон)",
              "Воркер «сна»: рубильник, окно, пороги кластеров и суточные "
              "бюджеты синтеза.", 2),
    # memory (3; раунд 9, T-826/T-827, spec §3.6.4/Q11): ностальгия
    GroupSpec("memory_nostalgia", "memory", "Ностальгия",
              "NostalgiaWorker (слой B) и маркер «золотых» при ответе "
              "(слой A): рубильники, условия тика, анти-спам, пороги.", 3),
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

# ── content: PG-only строки (раунд 10, F-7 §5.2) ────────────────────────────
# (pg_id, title_ru, code_source, group, description)
_CONTENT_STR: list[tuple] = [
    ("content.no_key_reply", "Ответ «нет ключа» (sandbox)",
     "services.sandbox_reply.DEFAULT_NO_KEY_REPLY", "content_info",
     "Фраза бота, когда у чата нет своего ключа и общий недоступен. "
     "Нейросеть при этом не вызывается."),
]

# ── content: поля Settings (раунд 3 — каталог медиа-шары) ──────────────────
# (field, title_ru, type, group, description)
_CONTENT_SETTINGS: list[tuple] = [
    ("MEDIA_SHARE_DIR", "Каталог временной публикации видео", "str", "content_media",
     "Папка, куда копируются видео для пересказа «по кадрам» (вне web-статики). Относительно корня проекта."),
    ("MEDIA_PUBLIC_BASE_URL", "Внешний базовый адрес /media", "str", "content_media",
     "Публичный адрес, по которому сервис видео видит опубликованные ролики."),
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
    # Раунд 10.11 (ADR-1011-2): BASE_URL/API_KEY/API_KEY_2/MODEL переведены в
    # first-class каталог (models/keys) — здесь остаются только тайминги.
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
    ("LLM_API_KEY", "Ключ основной нейросети", "str", True, "keys_llm",
     "Ключ основной нейросети — через него идёт почти вся работа бота. Взять: кабинет провайдера."),
    ("LLM_FALLBACK_API_KEY", "Ключ запасной нейросети", "str", True, "keys_llm",
     "Ключ запасной нейросети на случай сбоя основной. Получить: кабинет запасного провайдера."),
    # Раунд 10.11 (ADR-1011-2): embed-фоллбэки — first-class каталог
    # (были infra/category None; счётчики не растут — перенос записей).
    ("EMBEDDING_FALLBACK_API_KEY", "Ключ запасной модели памяти", "str", True,
     "keys_llm",
     "Ключ первой запасной модели «отпечатков» текста (если основная не отдаёт эмбеддинги). Получить: кабинет провайдера."),
    ("EMBEDDING_FALLBACK_API_KEY_2", "Ключ второй запасной модели памяти",
     "str", True, "keys_llm",
     "Ключ второй запасной модели «отпечатков» текста — запасной аккаунт того же провайдера. Получить: кабинет провайдера."),
    # Раунд 10.12 (OD-1, ADR-1012-1 D1): отдельный ключ primary-эмбеддингов
    # (эмбеддинги могут жить у ДРУГОГО провайдера, чем direct-чат). Пусто →
    # рантайм откатывается на keys.llm_api_key.
    ("EMBEDDING_API_KEY", "Ключ основной модели памяти", "str", True, "keys_llm",
     "Ключ провайдера основной модели «отпечатков» текста. Пусто — используется ключ основной нейросети."),
    ("TAVILY_API_KEY", "Ключ Tavily", "str", True, "keys_search",
     "Ключ интернет-поиска (Tavily) — бот ищет по нему. Получить: tavily.com."),
    ("EXA_API_KEY", "Ключ Exa", "str", True, "keys_search",
     "Ключ интернет-поиска (Exa) — резервный источник. Получить: exa.ai."),
    ("GROQ_API_KEY", "Ключ Groq", "str", True, "keys_groq",
     "Ключ сервиса Groq — им бот распознаёт голосовые сообщения. Получить: console.groq.com."),
    ("OPENROUTER_API_KEY", "Ключ OpenRouter", "str", True, "keys_openrouter",
     "Ключ сервиса OpenRouter — пересказы видео и страниц. Получить: openrouter.ai."),
    ("CHECKUP_BETTERSTACK_SQL_USER", "Пользователь Betterstack SQL", "str", True, "keys_betterstack",
     "Логин базы метрик Betterstack для чекапа. Взять: кабинет сервиса."),
    ("CHECKUP_BETTERSTACK_SQL_PASSWORD", "Пароль Betterstack SQL", "str", True, "keys_betterstack",
     "Пароль базы метрик Betterstack для чекапа. Взять: кабинет сервиса."),
    ("YOUTUBE_TRANSCRIPT_PROXY_URL", "Прокси YouTube (логин:пароль)", "str", True, "keys_youtube",
     "Адрес прокси с логином и паролем — через него бот берёт субтитры YouTube. Получить: кабинет прокси-сервиса."),
    ("YOUTUBE_TRANSCRIPT_PROXY_USERNAME", "Логин resident-прокси Webshare", "str", True, "keys_youtube",
     "Логин резидент-прокси Webshare для субтитров. Получить: webshare.io."),
    ("YOUTUBE_TRANSCRIPT_PROXY_PASSWORD", "Пароль resident-прокси Webshare", "str", True, "keys_youtube",
     "Пароль резидент-прокси Webshare для субтитров. Получить: webshare.io."),
    ("YOUTUBE_COOKIES_FILE", "Путь к файлу пропусков YouTube (Netscape)", "str", True, "keys_youtube",
     "Файл с сохранёнными пропусками браузера для YouTube. Помогает получать субтитры, обновляется вручную."),
    ("MEDIA_SHARE_SECRET", "Секрет подписи /media-ссылок", "str", True, "keys_media",
     "Секрет подписи временных ссылок на опубликованное видео. Пусто — публикация выключена, ролики пересказываются по звуку."),
]

# ── models: провайдеры/модели/таймауты/ретраи (не секреты) ──────────────────
# (field, title_ru, type, group, description)
_MODELS: list[tuple] = [
    ("LLM_BASE_URL", "Адрес основной нейросети", "str", "models_main",
     "Адрес сервера нейросети. Меняется, только если переезжаете на другого провайдера."),
    ("LLM_MODEL_NAME", "Модель основной нейросети", "str", "models_main",
     "Название основной модели бота. От неё зависит качество и скорость почти всех ответов."),
    ("EMBEDDING_MODEL_NAME", "Модель эмбеддингов", "str", "models_embeddings",
     "Модель «отпечатков» текста для поиска по памяти. Менять только вместе с размерностью ниже."),
    # Раунд 10.12 (ADR-1012-1 D1): адрес primary-эмбеддингов — НЕЗАВИСИМ от
    # адреса direct-чата (models.llm_base_url). Дефолт apinet.cloud/v1.
    ("EMBEDDING_BASE_URL", "Адрес основной модели памяти", "str",
     "models_embeddings",
     "Адрес сервера модели «отпечатков» текста. Может быть у другого провайдера, чем основная нейросеть."),
    ("EMBEDDING_DIM", "Размерность эмбеддингов", "int", "models_embeddings",
     "Длина «отпечатка» текста. Должна совпадать с моделью эмбеддингов, иначе поиск сломается."),
    # Раунд 10.11 (ADR-1011-2): адрес/модель embed-фоллбэка — first-class
    # каталог (были infra/category None; счётчики не растут — перенос).
    ("EMBEDDING_FALLBACK_BASE_URL", "Адрес запасной модели памяти", "str",
     "models_embeddings",
     "Адрес сервера запасной модели «отпечатков» текста. Общий для обоих запасных ключей."),
    ("EMBEDDING_FALLBACK_MODEL", "Модель запасной модели памяти", "str",
     "models_embeddings",
     "Название запасной модели «отпечатков». Общее для обоих запасных ключей; пусто — берётся основная."),
    ("LLM_TIMEOUT", "Сколько ждать ответ нейросети, сек", "float", "models_llm_timeouts",
     "Сколько ждать ответ нейросети. Больше — меньше сбоев на медленных моделях, но дольше тишина."),
    ("LLM_MAX_RETRIES", "Число повторов при сбое нейросети", "int", "models_llm_timeouts",
     "Сколько раз повторить запрос при временном сбое. Больше — надёжнее, но дольше ждать."),
    ("LLM_RETRY_BACKOFF_BASE", "Начальная пауза между повторами", "float", "models_llm_timeouts",
     "Начальная пауза перед повтором, сек. Больше — реже долбить провайдера при сбоях."),
    ("LLM_RETRY_BACKOFF_CAP", "Максимальная пауза между повторами, сек", "float", "models_llm_timeouts",
     "Максимальная пауза между повторами. Больше — дольше терпелив, но тише при упорном сбое."),
    ("LLM_RETRY_JITTER_MAX", "Разброс паузы между повторами, сек", "float", "models_llm_timeouts",
     "Случайная добавка к паузе повтора — чтобы запросы не стучались одновременно."),
    ("LLM_TOTAL_BUDGET", "Жёсткий дедлайн всей попытки, сек", "float", "models_llm_guard",
     "Потолок времени на запрос со всеми повторами. Меньше — бот быстрее сдаётся при проблемах."),
    ("LLM_FALLBACK_BASE_URL", "Адрес запасной нейросети", "str", "models_fallback",
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
    ("CHECKUP_BETTERSTACK_SQL_HOST", "Хост базы метрик Betterstack", "str", "models_checkup",
     "Адрес сервера метрик Betterstack для чекапа. Меняется редко."),
    ("CHECKUP_BETTERSTACK_SQL_TABLE", "Префикс источника Betterstack", "str", "models_checkup",
     "Имя источника метрик в Betterstack. Меняется, если пересоздали источник."),
    ("CHECKUP_BETTERSTACK_SQL_QUERY", "SQL-оверрайд чекапа", "str", "models_checkup",
     "Свой SQL-запрос к метрикам, если стандартный не подходит. Обычно не трогать."),
    ("TOKENIZER_ENCODING", "Кодировка tiktoken", "str", "models_embeddings",
     "Как бот считает длину текста в словах. Меняется только вместе с моделью."),
    ("TOKEN_SAFETY_MULTIPLIER", "Запас при подсчёте длины текста", "float", "models_embeddings",
     "Запас при подсчёте длины: больше — бот осторожнее и чаще вписывается в лимиты."),
    ("GROQ_TIMEOUT", "Таймаут Groq, сек", "float", "models_extra_providers",
     "Сколько ждать ответ Groq при распознавании голосовых. Больше — меньше сбоев."),
    ("GROQ_MAX_CONCURRENCY", "Одновременных запросов к Groq", "int", "models_extra_providers",
     "Сколько запросов к Groq одновременно. Меньше — спокойнее для сервиса, дольше очередь."),
    ("GROQ_MIN_INTERVAL", "Мин. интервал между запросами Groq, сек", "float", "models_extra_providers",
     "Пауза между распознаваниями голосовых. Больше — реже обращения к сервису."),
    ("GROQ_MAX_RETRIES", "Число ретраев Groq", "int", "models_extra_providers",
     "Сколько раз повторить распознавание при сбое. Больше — надёжнее, дольше ждать."),
    ("OPENROUTER_TIMEOUT", "Таймаут OpenRouter, сек", "float", "models_extra_providers",
     "Сколько ждать ответ OpenRouter при пересказах. Больше — меньше сбоев на медленных моделях."),
    ("VIDEO_PRIMARY_MODEL", "Первичная видео-модель (OpenRouter)", "str", "models_video_summary",
     "Первая модель, которой бот пробует «посмотреть» ролик: NVIDIA Nemotron умеет и звук, и картинку. Откажет — включится запасная или субтитры."),
    ("VIDEO_FALLBACK_MODEL", "Запасная видео-модель (OpenRouter)", "str", "models_video_summary",
     "Раунд 4 (T-710): MiniMax M3 (контекст 1M) — видит кадры ролика. Используется, когда первичная недоступна или ответила отказом; упала — бот пересказывает по субтитрам."),
    ("VIDEO_TIMEOUT_SECONDS", "Таймаут видео-запроса, сек", "float", "models_video_summary",
     "Сколько ждать ответ мультимодальной модели на видео. Больше — реже сбои, но дольше тишина."),
    # ── Раунд 10.9 (ADR-109-1): кастомные имена моделей для админки.
    # Первое поле каждого provider-блока; питают блок «Доступность ключей». ──
    ("LLM_DISPLAY_NAME", "Название основной модели", "str", "models_main",
     "Как называть основную нейросеть в админке. Пусто — покажется адрес сервера."),
    ("LLM_FALLBACK_DISPLAY_NAME", "Название фолбэк-модели", "str", "models_fallback",
     "Как называть запасную нейросеть. Пусто — покажется адрес сервера."),
    ("GROQ_DISPLAY_NAME", "Название модели расшифровки", "str", "models_extra_providers",
     "Как называть сервис расшифровки голосовых. Пусто — покажется адрес сервера."),
    ("OPENROUTER_DISPLAY_NAME", "Название модели для видео", "str", "models_video_summary",
     "Как называть сервис, который смотрит видео. Пусто — покажется адрес сервера."),
    # Раунд 10.12 (ADR-1012-1 D5): отдельное имя STT-фолбэка OpenRouter
    # (видео-блок использует OPENROUTER_DISPLAY_NAME).
    ("OPENROUTER_TRANSCRIBE_DISPLAY_NAME",
     "Название модели расшифровки (резерв)", "str", "models_extra_providers",
     "Как называть резервный сервис расшифровки голосовых OpenRouter. Пусто — покажется адрес сервера."),
    ("EMBEDDING_DISPLAY_NAME", "Название основной модели памяти", "str", "models_embeddings",
     "Как называть модель поиска по памяти. Пусто — покажется адрес сервера."),
    ("EMBEDDING_FALLBACK_DISPLAY_NAME", "Название запасной модели памяти", "str", "models_embeddings",
     "Как называть первую запасную модель памяти. Пусто — покажется адрес сервера."),
    ("EMBEDDING_FALLBACK2_DISPLAY_NAME", "Название второй запасной модели памяти", "str", "models_embeddings",
     "Как называть вторую запасную модель памяти. Пусто — покажется адрес сервера."),
]

# ── models: PG-only записи (OD11+OD16, раунд 10.5) ──────────────────────────
# (pg_id, title_ru, group, code_source, description)
# Ноль захардкоженных моделей/адресов: STT-модели Groq/OpenRouter и base_url
# провайдеров становятся data-driven и UI-редактируемыми. Сид — из код-канонов
# (значения совпадают с прежними литералами: safe migration, status.llm[]
# до/после идентичен). settings_field=None/env_name=None → PG-only.
_MODELS_PG_ONLY: list[tuple] = [
    ("models.groq_base_url", "Адрес сервиса Groq", "models_extra_providers",
     "SmartModule.transcriber.groq_transcriber.GROQ_BASE_URL",
     "Адрес сервера Groq для распознавания голосовых. Меняется при переезде на шлюз/прокси."),
    ("models.groq_transcribe_model", "Модель распознавания Groq",
     "models_extra_providers",
     "SmartModule.transcriber.groq_transcriber.GROQ_TRANSCRIBE_MODEL",
     "Модель Groq для распознавания голосовых в текст. По умолчанию whisper-large-v3."),
    ("models.openrouter_base_url", "Адрес сервиса OpenRouter",
     "models_extra_providers",
     "SmartModule.transcriber.openrouter_transcriber.OPENROUTER_BASE_URL",
     "Адрес сервера OpenRouter для пересказов и распознавания. Меняется при переезде."),
    ("models.openrouter_transcribe_model",
     "Модель распознавания OpenRouter", "models_extra_providers",
     "SmartModule.transcriber.openrouter_transcriber.OPENROUTER_TRANSCRIBE_MODEL",
     "Модель OpenRouter для распознавания голосовых. По умолчанию openrouter/free."),
]

# ── flags: рубильники модулей ───────────────────────────────────────────────
# (field, title_ru, group, description)
_FLAGS: list[tuple] = [
    ("SUMMARY_ENABLED", "Модуль саммари включён", "flags_module_summary",
     "Пересказы разговоров и каналов. Не нужны — выключи, и бот перестанет их делать."),
    ("DIRECT_CHAT_BOTWORD_ENABLED", "Триггер «бот»-семьи в чате", "flags_module_direct",
     "Бот отвечает, когда к нему обращаются по имени. Не хочешь — выключи, и обращения останутся без ответа."),
    ("ENABLE_VOICE_TRANSCRIPTION", "Транскрипция голосовых", "flags_module_transcribe",
     "Голосовые превращаются в текст. Выключишь — расшифровка не запустится."),
    # ── Раунд 10.6 (T-1201, A1/D1): 5 master-флагов модулей (default ON) ──
    ("FACTCHECK_ENABLED", "Модуль Фактчек включён", "flags_module_factcheck",
     "Мастер-рубильник проверки фактов. Выключено — бот не отвечает на фактчек-запросы."),
    ("SEARCH_ENABLED", "Модуль Поиск включён", "flags_module_search",
     "Мастер-рубильник интернет-поиска. Выключено — бот не ищет в интернете."),
    ("VIDEO_SUMMARY_ENABLED", "Модуль Выжимка видео включён", "flags_module_video_summary",
     "Мастер-рубильник пересказа видео. Выключено — summary-пути молчат; «транскрипт» продолжает работать."),
    ("WEBPAGE_ENABLED", "Модуль Веб-страницы включён", "flags_module_web",
     "Мастер-рубильник пересказа веб-страниц. Выключено — бот не пересказывает страницы."),
    ("CHECKUP_ENABLED", "Модуль Диагностика включён", "flags_service",
     "Мастер-рубильник чекапа/диагностики. Выключено — хендлеры чекапа молчат."),
    ("GRAPH_RAG_ENABLED", "Извлечение фактов при архивации", "flags_memory",
     "Старые сообщения превращаются в факты для памяти. Выключишь — бот обойдётся кратким сжатием."),
    ("SMART_CACHE_ENABLED", "Exact Match Cache", "flags_smart_cache",
     "Кэш точных повторов вопросов — бот отвечает мгновенно из памяти. Выключено — всегда новый ответ."),
    ("THROTTLE_PERSISTENT_ENABLED", "Персистентный троттлинг", "flags_throttle",
     "Модули общими силами следят за частотой запросов. Выключишь — каждый ограничивает себя сам."),
    ("DOWNLOAD_ENABLED", "Скачивание видео («скачай <ссылка>»)", "flags_module_media_download",
     "Команда «скачай <ссылка>» качает видео. Выключишь — команда перестанет работать."),
    ("YTDLP_FOR_YOUTUBE", "yt-dlp для YouTube (вместо cobalt)", "flags_module_media_download",
     "Для YouTube бот запускает локальный движок. Выключишь — вернётся прежний способ."),
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
    # Раунд 10.4 (B-1): рендер-группа — limits_chat_budgets (блок «Прямой
    # чат: бюджеты токенов»); pg-ключ и семантика БЕЗ изменений.
    ("CHAT_CONTEXT_BUDGETS_ENABLED", "Бюджеты контекста direct_chat", "limits_chat_budgets",
     "Делит контекст на блоки (карта, ветка, память). Выключено — доли не ограничиваются."),
    ("CHAT_IMPORTANCE_KEEP_ENABLED", "Importance-удержание verbatim при обрезке", "flags_chat_behavior",
     "Строки Global_Context с важными маркерами (имена, бот, цитаты, числа, вопросы) не режутся первыми. Выключено — ровно старое поведение."),
    ("CHAT_RAG_RERANK_ENABLED", "Пересортировка фактов памяти нейросетью", "flags_memory",
     "Факты из памяти для ответа фильтруются дешёвой нейросетью. Выключено — порядок поиска как есть, без лишних вызовов."),
    ("SUMMARY_STREAMING_ENABLED", "Стриминг саммари (placeholder + edit)", "flags_summary",
     "Пересказы появляются постепенно, а не одним куском. Выключено — ответ приходит целиком."),
    ("TYPING_INDICATOR_ENABLED", "Индикатор «печатает…»", "flags_chat_behavior",
     "Бот показывает «печатает…» пока думает. Выключено — индикатора нет."),
    ("SEARCH_RERANK_ENABLED", "Пересортировка результатов поиска", "flags_module_search",
     "Включает дополнительную сортировку результатов поиска нейросетью. Дороже, но точнее."),
    ("CHECKUP_MEMORY_METRICS_ENABLED", "Метрики здоровья памяти в чекап", "flags_service",
     "В ежемесячной сводке появится раздел о здоровье памяти. Не нужно — выключи, раздел пропадёт."),
    ("GRAPH_DEDUP_ENABLED", "Дедуп фактов при записи", "flags_memory",
     "Похожие факты не дублируются в памяти. Выключено — память растёт быстрее и грязнее."),
    ("GRAPH_EPISODE_MERGE_ENABLED", "Слияние повторяющихся эпизодов", "flags_memory",
     "Похожие эпизоды памяти объединяются в один. Выключено — эпизоды копятся отдельно."),
    ("GRAPH_TIME_DECAY_ENABLED", "Time-decay весов фактов", "flags_memory",
     "Старые факты со временем становятся менее важными. Выключено — важность не устаревает."),
    ("GRAPH_USER_QUOTA_ENABLED", "Квота памяти на человека", "flags_memory",
     "Ограничивает объём памяти на каждого человека. Выключено — память без потолка."),
    ("GRAPH_FACT_TOUCH_ENABLED", "Продление срока фактов при упоминании", "flags_memory",
     "Упоминание факта продлевает ему жизнь. Выключено — срок жизни не продлевается."),
    ("GRAPH_REVIEW_ENABLED", "Периодический пересмотр фактов", "flags_memory",
     "Бот регулярно пересматривает и чистит память. Выключено — чистка только при архивации."),
    ("VEC_INT8_ENABLED", "int8-сжатие векторов", "flags_memory",
     "Сжимает «отпечатки» текста — память занимает меньше места. Выключено — точнее, но тяжелее."),
    ("GRAPH_MMR_ENABLED", "Разнообразие фактов из памяти", "flags_memory",
     "Ответы по памяти становятся разнообразнее. Выключено — берутся самые похожие факты."),
    ("MEMORY_COMMANDS_USER_ENABLED", "Память-команды «запомни/забудь» для участников", "flags_memory",
     "Выключено — «запомни/забудь» доступны только админу и модераторам; участникам бот отвечает отказом и команду не исполняет."),
    ("MEMORY_BACKUP_ENABLED", "Ежедневный бэкап памяти", "flags_memory",
     "Раз в сутки бот копирует память в резерв. Выключишь — копий не будет."),
    ("EMBED_CACHE_ENABLED", "Кэш эмбеддингов", "flags_memory",
     "Кэширует «отпечатки» текстов — быстрее и дешевле. Выключено — считать каждый раз заново."),
    ("DB_WAL_CHECKPOINT_ENABLED", "Сжатие журнала базы", "flags_service",
     "Технический: периодически ужимает журнал БД. Обычно не трогать."),
    ("LLM_CB_ENABLED", "Circuit Breaker direct_chat", "flags_service",
     "«Рубильник» при сбоях нейросети: временно не дёргает её. Выключено — бот пробует всегда."),
    ("COMMON_WORK_MEDIA_ENABLED", "Медиа work-подсервиса", "flags_media",
      "Медиа для запросов вроде «устал». Выключишь — останутся только остальные медиа."),
    # ── Раунд 10 (permsoc-module-isolation, F-9 §3): мастер-тумблер PERMsoc;
    # дефолт false (Q2, безопаснее для новых чатов). Раунд 10.9: тумблер
    # owner-блока «Общее» — рендерится в <summary>, не generic-карточкой ──
    ("PERMSOC_ENABLED", "Функции PERMsoc: мастер-тумблер", "flags_permsoc",
      "Главный выключатель всех персонажей PERMsoc. Выключишь — Славик, "
      "Костя, Леха, Оля и передразнивания молчат; каждый чат можно включить отдельно."),
    # ── Раунд 10.9 (ADR-109-4): независимый тумблер Славика, дефолт True ──
    ("SLAVIK_ENABLED", "Славик включён", "flags_permsoc",
      "Славик шутит, кидает фото и гифку. Выключишь — он замолкает, "
      "а Костя, Леха и Оля работают как обычно."),
    # ── Раунд 10.12 (ADR-1012-1 D3): независимый тумблер Костика, дефолт True
    # (поведение по умолчанию идентично прежнему). ──
    ("KOSTIK_ENABLED", "Костик включён", "flags_permsoc",
      "Бот отвечает на сообщения Кости репликами-фразами. Выключишь — "
      "Костя замолкает, остальные персоны работают как обычно."),
    ("COMMON_MEDIA_ENABLED", "Все common-медиа", "flags_media",
     "Главный рубильник всех медиа-реакций бота. Выключено — гифки/фото не отправляются вообще."),
    ("OLYA_ENABLED", "Оля включена", "flags_permsoc",
      "Бот отвечает на видео Оли. Выключишь — её видео останутся без реакции."),
    ("OLYA_CAPTION_ENABLED", "Капшн ответов Оли", "flags_media",
     "Под ответами Оли появляется подпись. Выключишь — бот ответит без неё."),
    ("OLYA_REPOST_ENABLED", "Ответ репостом Оли", "flags_media",
     "Оля отвечает репостом видео. Выключено — обычным сообщением."),
    ("OLYA_ALWAYS_SEND", "Реакция на ВСЕ видео Оли", "flags_media",
     "Бот реагирует на каждое видео Оли. Выключено — с перерывами."),
    ("OLYA_CAPTION_MENTION_ENABLED", "Триггер @SaveAsBot в капшне", "flags_media",
     "Бот реагирует на @SaveAsBot в подписи Оли. Выключишь — упоминание останется незамеченным."),
    ("MIMIC_FORWARDS_ENABLED", "Мимикрировать репосты", "flags_media",
     "Бот передразнивает и обычные, и пересланные сообщения. Выключено — только обычные."),
    ("MIMIC_ENABLED", "Мимикрия включена", "flags_permsoc",
      "Бот передразнивает людей из списка «жертв». Выключишь — "
      "передразнивания прекратятся, остальные персоны не пострадают."),
    ("ALAN_REPLIES_ENABLED", "Reply-блок Лехи", "flags_permsoc_behavior",
      "Леха отвечает в ответ на сообщения. Выключено — Леха не отвечает."),
    ("DEAD_PAGE_POST_ON_JOIN", "Триггер dead page при join", "flags_permsoc_behavior",
      "Бот постит dead page при вступлении участника. Выключено — постится только по команде."),
    ("SUMMARY_ADMIN_ONLY", "Саммари только для админа", "flags_summary",
      "Пересказы доступны только админу. Выключено — по списку разрешённых."),
    # ── Раунд 7 (T-776, spec §3.11): лор чатов — рубильники ──
    ("LORE_WORKER_ENABLED", "Лор чатов: фоновый воркер", "flags_lore",
     "Планирует тик-цикл воркера (обход активных чатов и генерация лора). Выключено — воркер не запускается."),
    ("LORE_AUTO_ENABLED", "Лор чатов: авто-генерация", "flags_lore",
     "Разрешает авто-прогоны генерации лора по расписанию. Выключено — генерация только вручную («Сгенерировать сейчас»)."),
    ("LORE_INJECT_ENABLED", "Лор чатов: инжект в контекст", "flags_lore",
     "Добавляет блок лора в контекст прямого чата. Выключено — ровно старое поведение (SQLite-легаси)."),
    # ── Раунд 9 (T-816/T-817, spec §3.6.4/Q12): отношения — рубильники ──
    ("RELATIONS_TONE_ENABLED", "Отношения: тон по стадиям", "flags_relations",
     "Глобальный рубильник тона по стадиям участников (блок <user_relations> "
     "в контекст прямого чата). Выключено (дефолт) — 0 влияния на поведение; "
     "per-chat включается колонкой relations_enabled профиля в «Лор чатов»."),
    # ── Раунд 9 (фикс-раунд, spec §3.6.4/Q11): dig_into_lore — рубильники ──
    ("DIG_ENABLED", "dig_into_lore: тул включён", "flags_memory",
     "Рубильник инструмента глубокого копания в историю чата (direct_chat). "
     "Выключено — модель не может вызвать dig_into_lore (0 добавочных "
     "раундов)."),
    ("DIG_PRE_GATE_ENABLED", "dig_into_lore: пре-гейт маркеров ностальгии",
     "flags_memory",
     "При фразе «помнишь/как мы тогда/год назад/в 2024» бот сам копает "
     "историю ДО генерации ответа и кладёт результат в <dig_result>. "
     "Выключено (дефолт) — dig только по контракту канона (вызов модели)."),
]

# ── limits: числа/таймауты/кулдауны/бюджеты ─────────────────────────────────
# (field, title_ru, type, group, description)
_LIMITS: list[tuple] = [
    ("ALAN_REPLY_INTERVAL", "Интервал ответа Лехи (сообщений)", "int", "limits_alan",
     "Через сколько сообщений Леха отвечает. 10 — примерно каждое десятое."),
    ("KOSTIK_REPLY_PROBABILITY", "Вероятность ответа Костика", "float", "limits_kostik",
     "Шанс, что Костик ответит на сообщение. 0 — никогда, 1 — на каждое."),
    ("DEAD_PAGE_CAPTION_MAX_CHARS", "Макс. символов капшна dead page", "int", "limits_deadpage",
     "Максимальная длина подписи под постом. Больше — длиннее подпись."),
    ("DEAD_PAGE_COOLDOWN", "Кулдаун dead page, сек", "float", "limits_deadpage",
     "Пауза между постами dead page. Больше — бот постит реже."),
    ("DEAD_PAGE_MAX_FORWARD_RETRIES", "Ретраи подбора dead page", "int", "limits_deadpage",
     "Сколько раз бот подбирает другой пост, если не нашёл подходящий. Больше — надёжнее."),
    ("GIF_INTERVAL", "Интервал гифки (сообщений)", "int", "limits_media_permsoc",
     "Через сколько сообщений бот кидает гифку. Меньше — чаще гифки."),
    ("ALAN_GREETING_COOLDOWN", "Кулдаун приветствия Лехи, сек", "int", "limits_alan",
     "Как часто Леха здоровается. Больше — реже приветствия."),
    ("ALAN_SILENCE_GREETING_HOURS", "Порог тишины Лехи, часов", "float", "limits_alan",
     "Сколько тишины в чате, чтобы Леха поприветствовал снова. Больше — реже приветствия."),
    ("SLAVIC_PHOTO_INTERVAL", "Интервал фото Славика (сообщений)", "int", "limits_media_permsoc",
     "Через сколько сообщений Славик кидает фото. Меньше — чаще фото."),
    ("COMMON_COOLDOWN", "Общий кулдаун common-медиа, сек", "float", "limits_media_permsoc",
     "Общая пауза между любыми медиа-реакциями. Больше — бот спокойнее."),
    ("DANGER_COOLDOWN", "Кулдаун danger-медиа, сек", "float", "limits_media_permsoc",
     "Пауза между danger-медиа. Больше — реже опасные реакции."),
    ("SELFDEV_COOLDOWN", "Кулдаун selfdev, сек", "float", "limits_media_permsoc",
     "Пауза между ответами на «саморазвитие». Больше — реже реакции."),
    ("WORK_COOLDOWN", "Кулдаун work, сек", "float", "limits_media_permsoc",
     "Пауза между ответами на «устал» и подобные. Больше — реже реакции."),
    ("MIMIC_MIN_WORDS", "Мин. слов для мимикрии", "int", "limits_mimic",
     "Сколько слов должно быть в сообщении, чтобы бот его передразнил. Больше — реже мимикрия."),
    ("MIMIC_COOLDOWN", "Кулдаун мимикрии, сек", "float", "limits_mimic",
     "Пауза между передразниваниями. Больше — реже мимикрия."),
    ("SLAVIK_MIMIC_MIN_WORDS", "Мин. слов для мимикрии Славика", "int", "limits_mimic",
     "Минимальная длина сообщения для мимикрии Славика. Больше — реже мимикрия."),
    ("SLAVIK_MIMIC_COOLDOWN", "Кулдаун мимикрии Славика, сек", "float", "limits_mimic",
     "Пауза между передразниваниями Славика. Больше — реже мимикрия."),
    ("OLYA_COOLDOWN", "Кулдаун Оли, сек", "float", "limits_media_permsoc",
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
    ("SUMMARY_RAG_L2_LIMIT", "Лимит фактов памяти, уровень 2", "int", "limits_graph",
     "Сколько фактов памяти берётся на втором уровне. Больше — контекстнее, дороже."),
    ("SUMMARY_RAG_L3_LIMIT", "Лимит фактов памяти, уровень 3", "int", "limits_graph",
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
    ("GRAPH_FACT_TTL_DAYS", "Срок жизни фактов, дней", "int", "limits_graph",
     "Срок жизни факта без упоминаний. Больше — дольше помнит."),
    ("GRAPH_RAG_FACTS_LIMIT", "Сколько фактов памяти брать", "int", "limits_graph",
     "Сколько фактов берётся для ответа по памяти. Больше — контекстнее, дороже."),
    ("GRAPH_RAG_CONTEXT_MAX_CHARS", "Потолок контекста памяти, символов", "int", "limits_graph",
     "Максимальный размер фактов, отдаваемых нейросети. Больше — точнее, дороже."),
    ("MEMORY_COMMANDS_REMEMBER_TTL_DAYS", "Срок «запомни» для участников, дней (0 = вечно)", "int", "limits_memory",
     "Через сколько дней забывается факт из «запомни» (origin user_memory). Пусто/0 — хранить вечно."),
    ("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", "Ретраи memorize-батча", "int", "limits_graph",
     "Сколько раз повторить сохранение фактов при сбое. Больше — надёжнее."),
    ("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", "Пауза между повторами пакета, сек", "float", "limits_graph",
     "Пауза перед повтором сохранения фактов. Больше — спокойнее при сбоях."),
    ("SEARCH_MAX_SYMBOLS", "Длина ответа поиска, символов", "int", "limits_search",
     "Максимальная длина ответа поиска. Больше — ответ подробнее, но генерируется дольше и дороже."),
    ("FACTCHECK_MAX_SYMBOLS", "Длина ответа фактчека, символов", "int", "limits_factcheck",
     "Максимальная длина проверки фактов. Больше — подробнее, но дольше и дороже."),
    ("SEARCH_COOLDOWN_SECONDS", "Кулдаун поиска, сек", "float", "limits_search",
     "Пауза между поисковыми запросами. Больше — бот реже ищет в интернете и меньше нагружает поисковые сервисы."),
    ("FACTCHECK_COOLDOWN_SECONDS", "Кулдаун фактчека, сек", "float", "limits_factcheck",
     "Пауза между проверками фактов. Больше — бот реже проверяет."),
    ("YOUTUBE_MAX_SYMBOLS", "Лимит YouTube, символов", "int", "limits_youtube",
     "Максимальная длина пересказа видео. Больше — подробнее, но дольше и дороже."),
    ("WEBPAGE_MAX_SYMBOLS", "Лимит веб-страниц, символов", "int", "limits_web",
     "Максимальная длина пересказа страницы. Больше — подробнее, но дольше и дороже."),
    ("YOUTUBE_COOLDOWN_SECONDS", "Кулдаун YouTube, сек", "float", "limits_youtube",
     "Пауза между пересказами видео. Больше — бот реже пересказывает."),
    ("WEBPAGE_COOLDOWN_SECONDS", "Кулдаун веб-страниц, сек", "float", "limits_web",
     "Пауза между пересказами страниц. Больше — бот реже пересказывает."),
    ("CHECKUP_COOLDOWN_SECONDS", "Кулдаун чекапа, сек", "float", "limits_checkup",
     "Пауза между запросами сводки о здоровье. Больше — реже чекап."),
    ("CHECKUP_MAX_SYMBOLS", "Длина ответа чекапа, символов", "int", "limits_checkup",
     "Максимальная длина сводки о здоровье. Больше — подробнее, но дольше и дороже."),
    ("CHECKUP_MAX_INPUT_SYMBOLS", "Потолок входа чекапа, символов", "int", "limits_checkup",
     "Сколько данных максимум берётся для сводки. Больше — полнее, но дороже."),
    ("INFO_COOLDOWN_SECONDS", "Кулдаун /info, сек", "float", "limits_service",
     "Пауза между запросами справки. Больше — реже отдаётся справка."),
    ("CHAT_GLOBAL_CONTEXT_LIMIT", "Сообщений фона <Global_Context>", "int", "limits_chat",
     "Сколько сообщений бот помнит из фона разговора. Больше — контекстнее, но дороже."),
    ("CHAT_BURST_LIMIT", "Обращений подряд до кулдауна", "int", "limits_chat",
     "Сколько обращений подряд без перерыва разрешено. Меньше — бот чаще уходит в паузу."),
    ("CHAT_COOLDOWN_SECONDS", "Кулдаун direct_chat, сек", "float", "limits_chat",
     "Пауза между ответами в прямом чате. Больше — бот реже отвечает."),
    ("CHAT_DIRECT_REPLY_TTL_DAYS", "Срок жизни фактов прямых ответов, дней", "int", "limits_chat",
     "Сколько дней помнить, что бот уже отвечал человеку. Пусто = 30 (дефолт), 0 = вечно. Больше — дольше помнит."),
    ("CHAT_GLOBAL_CONTEXT_MAX_CHARS", "Потолок <Global_Context>, символов", "int", "limits_chat",
     "Максимальный размер фона разговора. Больше — точнее, но дороже."),
    ("CHAT_THREAD_MAX_DEPTH", "Глубина <Conversation_Thread>", "int", "limits_chat",
     "Сколько последних сообщений видеть в ветке. Больше — контекстнее, но дороже."),
    ("CHAT_THREAD_MAX_CHARS", "Потолок <Conversation_Thread>, символов", "int", "limits_chat",
     "Максимальный размер ветки. Больше — точнее, но дороже."),
    ("SMART_CACHE_TTL_SECONDS", "Срок жизни умного кэша, сек", "int", "limits_smart_cache",
     "Сколько хранить готовый ответ на повторный вопрос. Больше — быстрее отвечает, но память засоряется."),
    ("SMART_CACHE_MAX_ROWS", "Потолок строк smart_cache", "int", "limits_smart_cache",
     "Сколько готовых ответов максимум хранить. Больше — больше попаданий, но тяжелее."),
    ("CHAT_LOCK_WAIT_SECONDS", "Таймаут per-chat замка, сек", "float", "limits_chat",
     "Сколько ждать, пока чат освободится. Больше — терпеливее, но дольше тишина."),
    ("CHAT_LOCK_MAX_ENTRIES", "Потолок словаря замков", "int", "limits_chat",
     "Технический: сколько чатов держать в памяти замков. Обычно не трогать."),
    ("SMARTMODULE_CONCURRENCY_PER_CHAT", "Одновременных запросов нейросети на чат", "int", "limits_chat",
     "Сколько генераций одного чата могут выполняться одновременно; 1 = строгая очередь (как раньше)."),
    ("SMARTMODULE_CONCURRENCY_WAIT_SECONDS", "Ожидание слота генерации (smart module), сек", "float", "limits_chat",
     "Сколько ждать свободный слот в поиске/фактчеке/ютубе/вебе/чекапе. Больше — терпеливее, но дольше тишина."),
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
    ("EMBED_CACHE_TTL_DAYS", "Срок жизни кэша отпечатков, дней", "int", "limits_memory",
     "Сколько хранить «отпечатки» текстов. Больше — быстрее поиск, но тяжелее."),
    ("EMBED_CACHE_MAX_ROWS", "Потолок строк кэша эмбеддингов", "int", "limits_memory",
     "Сколько «отпечатков» максимум хранить. Больше — больше попаданий, но тяжелее."),
    ("DB_WAL_CHECKPOINT_HOURS", "Период сжатия журнала базы, часов", "int", "limits_service",
     "Технический: как часто ужимать журнал БД. Обычно не трогать."),
    ("FACTCHECK_CONTEXT_MESSAGES", "Окно контекста фактчека (сообщений)", "int", "limits_factcheck",
     "Сколько сообщений берётся для проверки факта. Больше — точнее, но дороже."),
    ("SEARCH_CONTEXT_MESSAGES", "Окно контекста поиска (сообщений)", "int", "limits_search",
     "Сколько сообщений берётся для поиска. Больше — точнее, но дороже."),
    ("CHAT_CONTEXT_FILL_RATIO", "Порог заполнения окна (доля)", "float", "limits_chat",
     "При заполнении доли окна бот начинает сжимать контекст. Меньше — раньше сжимает."),
    ("CHAT_RUNNING_SUMMARY_TAIL", "Хвост бегущего конспекта", "int", "limits_chat",
     "Сколько последних сообщений всегда держать рядом с конспектом. Больше — живее, но дороже."),
    ("RUNNING_SUMMARY_TTL_MINUTES", "Срок жизни бегущего конспекта, минут", "int", "limits_chat",
     "Сколько живёт бегущий конспект без обновлений. Больше — дольше помнит."),
    ("CHAT_GLOBAL_CONTEXT_MAX_TOKENS", "Потолок глобального контекста, слов", "int", "limits_chat",
     "Максимальный размер фона разговора. Больше — точнее, но дороже."),
    ("CHAT_THREAD_MAX_TOKENS", "Потолок ветки, слов", "int", "limits_chat",
     "Максимальный размер ветки. Больше — точнее, но дороже."),
    # ── Раунд 8 (T-793/T-798/T-801, spec §3.G2): контекст-слой ──
    ("CHAT_MAP_PARTICIPANTS_HOURS", "Период активных участников карты, часов", "int", "limits_chat",
     "За сколько часов сообщений считаются «активные участники» для карты имён. Больше — карта шире, но дороже."),
    ("CHAT_MAP_PARTICIPANTS_CAP", "Потолок строк карты участников", "int", "limits_chat",
     "Сколько участников максимум в карте имён. Больше — полнее, но дороже."),
    ("CHAT_BRANCH_CONTEXT_HOPS", "Ходов в итоге ветки <Conversation_Branch>", "int", "limits_chat",
     "Сколько последних ходов reply-цепочки показывать над фоном. Больше — полнее, но дороже."),
    ("CHAT_CURRENT_QUESTION_MAX_CHARS", "Кап <Current_Question>, символов", "int", "limits_chat",
     "Максимальная длина блока текущего вопроса. Больше — длиннее вопросы видит бот, но дороже."),
    ("CHAT_LEVEL2_MIN_RAW_COUNT", "Порог сжатия конспекта L1→L2 (сообщений)", "int", "limits_chat",
     "Сколько сообщений покрывал конспект, чтобы он сжимался в широкий уровень L2. Меньше — уровни строятся раньше."),
    ("CHAT_LEVEL2_MAX_CHARS", "Кап широкого конспекта L2, символов", "int", "limits_chat",
     "Сколько символов широкого фона показывать в Global_Context. Больше — глубже история, но дороже."),
    ("CHAT_RAG_DEDUP_OVERLAP_RATIO", "Порог совпадения факта с фоном, доля", "float", "limits_rag",
     "Доля слов факта, уже найденных в фоне, после которой факт не повторяется в блоке памяти."),
    ("SUMMARY_MAX_CONTEXT_TOKENS", "Потолок контекста пересказа, слов", "int", "limits_summary",
     "Максимальный размер пересказа. Больше — полнее, но дороже."),
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
    # Раунд 10.4 (B-8): пресет — выпадающий список (widget/select-опции —
    # поля ParamSpec; опции ниже в _SELECT_WIDGET_PRESETS, REGISTRY без роста).
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
    ("GRAPH_FACT_TOUCH_EXTEND_DAYS", "На сколько продлевать факт при упоминании, дней", "int", "limits_graph",
     "На сколько продлевается факт при упоминании. Больше — дольше живут важные факты."),
    ("GRAPH_PURGE_PROTECT_WEIGHT", "Вес-гейт защиты от purge", "float", "limits_graph",
     "Факты весом не ниже порога не удаляются при чистке. Больше — чистка агрессивнее."),
    ("GRAPH_PURGE_PROTECT_DAYS", "Свежесть подтверждения для защиты от purge, дней", "int", "limits_graph",
     "Факт, подтверждённый повторением недавно, не удаляется при чистке."),
    ("GRAPH_MMR_LAMBDA", "Разнообразие при отборе, λ (0..1)", "float", "limits_graph",
     "Насколько разнообразными брать факты. 0 — только похожие, 1 — максимум разнообразия."),
    ("GRAPH_MMR_FETCH_K", "Сколько кандидатов смотреть при отборе", "int", "limits_graph",
     "Сколько фактов сначала берётся для разнообразия. Больше — качественнее, но дороже."),
    ("GRAPH_REVIEW_INTERVAL_DAYS", "Интервал пересмотра, дней", "int", "limits_graph",
     "Как часто бот пересматривает память. Меньше — чаще чистка."),
    ("GRAPH_COMPRESSION_LOG_RETENTION_DAYS", "Ретенция лога сжатий, дней", "int", "limits_graph",
     "Сколько хранить историю сжатий памяти. Больше — дольше диагностика."),
    ("CHAT_CONTEXT_BUDGET_TOKENS", "Бюджет контекста прямого чата, слов", "int", "limits_chat_budgets",
     "Общий потолок текста на ответ в прямом чате. Больше — полнее, но дороже."),
    ("CHAT_BUDGET_MAP_RATIO", "Доля бюджета: MAP", "float", "limits_chat_budgets",
     "Доля контекста на карту памяти. Больше — важнее карта."),
    ("CHAT_BUDGET_GLOBAL_RATIO", "Доля бюджета: Global", "float", "limits_chat_budgets",
     "Доля контекста на фон разговора. Больше — важнее фон."),
    ("CHAT_BUDGET_THREAD_RATIO", "Доля бюджета: Thread", "float", "limits_chat_budgets",
     "Доля контекста на ветку. Больше — важнее ветка."),
    ("CHAT_BUDGET_RAG_RATIO", "Доля бюджета: память", "float", "limits_rag",
     "Доля контекста на факты памяти. Больше — важнее память."),
    ("CHAT_BUDGET_TARGET_RATIO", "Доля бюджета: Target", "float", "limits_chat_budgets",
     "Доля контекста на целевое сообщение. Больше — важнее само сообщение."),
    ("CHAT_BUDGET_ANCHORS_RATIO", "Доля бюджета: Anchors", "float", "limits_chat_budgets",
     "Доля контекста на стилевые якоря. Больше — важнее стиль."),
    ("CHAT_BUDGET_BRANCH_RATIO", "Доля бюджета: Branch", "float", "limits_chat_budgets",
     "Доля контекста на итог ветки. Больше — важнее ветка."),
    ("CHAT_BUDGET_RESPONSE_RATIO", "Доля бюджета: Response", "float", "limits_chat_budgets",
     "Доля контекста на сам ответ. Больше — место под ответ."),
    ("CHAT_BUDGET_RESERVE_RATIO", "Доля бюджета: Reserve", "float", "limits_chat_budgets",
     "Запасной резерв бюджета. Больше — запас на непредвиденное."),
    ("CHAT_DEDUP_TTL_SECONDS", "Срок жизни записи о повторе, сек", "int", "limits_chat",
     "Как долго помнить одинаковые сообщения подряд. Больше — дольше дедуп."),
    # SUMMARY_ALIASES — 6-элементная запись: последний элемент widget
    # («keyvalue» → KV-редактор пар «Telegram ID → имя» на фронте, FR-28).
    ("SUMMARY_ALIASES", "Словарь алиасов имён", "json", "limits_user_aliases",
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
    ("DOWNLOAD_COOLDOWN", "Кулдаун скачивания, сек", "float", "limits_media_download",
     "Пауза между командами скачивания. Больше — реже можно качать."),
    ("VOICE_MAX_DURATION_SECONDS", "Макс. длительность войса, сек", "int", "limits_transcribe",
     "Длиннее этого войса не расшифровываются. Больше — длиннее можно."),
    ("VIDEO_TRANSCRIBE_MAX_SIZE_MB", "Макс. размер видео для расшифровки, МБ",
     "int", "limits_transcribe",
     "Видео больше этого размера по командам „транскрипт/че за видос/…” не расшифровывается. Проверяется по file_size ДО скачивания."),
    ("VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS", "Макс. длительность видео для расшифровки, сек",
     "int", "limits_transcribe",
     "Видео длиннее не расшифровывается. Telegram отдаёт длительность для видео-сообщений; у документов проверки длительности нет."),
    # ── Раунд 3 (видео-пайплайн): медиа-шара + STT-надёжность ──
    ("MEDIA_SHARE_TTL_SECONDS", "Срок жизни опубликованного видео, сек", "int", "limits_video_summary",
     "Сколько секунд OpenRouter может «посмотреть» ролик по временной ссылке. Меньше 60 игнорируется (900)."),
    ("MEDIA_SHARE_MAX_MB", "Потолок публикации видео, МБ", "int", "limits_video_summary",
     "Файл больше не публикуется — пересказ уходит на расшифровку. Больше — тяжелее «смотрение» видео."),
    ("VIDEO_STT_TIMEOUT_SECONDS", "Таймаут расшифровки видео, сек", "float", "limits_transcribe",
     "Сколько ждать ОДНУ стратегию распознавания для видео-файлов (перекрывает Groq/OpenRouter таймауты). Голосовые не трогает."),
    ("VIDEO_SUMMARY_MIN_CHARS", "Мин. символов транскрипта для выжимки", "int", "limits_video_summary",
     "Короче транскрипта выжимка не строится — честная фраза «нет речи». Больше — строже."),
    ("STT_GROQ_MAX_UPLOAD_MB", "Потолок загрузки в Groq, МБ", "int", "limits_transcribe",
     "Файл больше Groq-стратегия пропускается (лимит upload). Больше — риск HTTP 400."),
    ("STT_OPENROUTER_MAX_UPLOAD_MB", "Потолок загрузки в OpenRouter, МБ", "int", "limits_transcribe",
     "Файл больше OpenRouter-стратегия пропускается (base64 input_audio). Больше — риск HTTP 400."),
    # ── Раунд 7 (T-776, spec §3.11): лор чатов — лимиты ──
    ("LORE_MIN_MESSAGES", "Лор чатов: порог сообщений в окне", "int", "limits_lore",
     "Сколько «осмысленных» сообщений нужно в окне, чтобы авто-прогон состоялся. Больше — реже генерации."),
    ("LORE_MIN_MESSAGE_CHARS", "Лор чатов: мин. длина сообщения", "int", "limits_lore",
     "Минимальная длина текста, чтобы сообщение считалось «осмысленным» для авто-лора (команды и медиа-плейсхолдеры отсекаются)."),
    ("LORE_WINDOW_MAX_MESSAGES", "Лор чатов: потолок строк окна", "int", "limits_lore",
     "Сколько сообщений максимум берётся в окно для генерации. Больше — полнее, но дороже."),
    ("LORE_WINDOW_MAX_CHARS", "Лор чатов: потолок символов окна", "int", "limits_lore",
     "Потолок текста окна сообщений для нейросети. Больше — полнее, но дороже."),
    ("LORE_MAX_WORDS", "Лор чатов: бюджет в словах", "int", "limits_lore",
     "Максимум слов авто-лора (подставляется в промпт при генерации)."),
    ("LORE_INJECT_MAX_CHARS", "Лор чатов: cap инжекта", "int", "limits_lore",
     "Потолок символов блока лора в контексте ответа. Урезается авто-лор первым."),
    ("LORE_TICK_MINUTES", "Лор чатов: период тик-цикла", "int", "limits_lore",
     "Как часто фоновый воркер проверяет чаты на необходимость генерации, минут."),
    ("LORE_GENERATE_COOLDOWN", "Лор чатов: пауза между прогонами", "int", "limits_lore",
     "Минимальная пауза между генерациями одного чата, секунд (ручная генерация игнорирует)."),
    # ── Раунд 9 (T-816/T-817, spec §3.6.4): отношения — пороги/периоды ──
    ("RELATIONS_ACQUAINTANCE_MIN_MSG", "Знакомый: мин. сообщений", "int", "limits_relations",
     "Порог msg_total для стадии acquaintance (в паре с мин. днями в чате)."),
    ("RELATIONS_ACQUAINTANCE_MIN_DAYS", "Знакомый: мин. дней в чате", "int", "limits_relations",
     "Порог дней с первого сообщения для acquaintance."),
    ("RELATIONS_REGULAR_MIN_MSG", "Свой: мин. сообщений", "int", "limits_relations",
     "Порог msg_total для стадии regular."),
    ("RELATIONS_REGULAR_MIN_DAYS", "Свой: мин. дней в чате", "int", "limits_relations",
     "Порог дней с первого сообщения для regular."),
    ("RELATIONS_VETERAN_MIN_MSG", "Ветеран: мин. сообщений", "int", "limits_relations",
     "Порог msg_total для стадии veteran (1000)."),
    ("RELATIONS_VETERAN_MIN_DAYS", "Ветеран: мин. дней в чате", "int", "limits_relations",
     "Порог дней с первого сообщения для veteran (365)."),
    ("RELATIONS_HOLD_ABSENT_DAYS", "Держать стадию при отсутствии, дней", "int", "limits_relations",
     "Отсутствие дольше этого срока — стадия НЕ понижается (падает только активность)."),
    ("RELATIONS_STAGE_CHANGE_MIN_DAYS", "Понижение не чаще, дней", "int", "limits_relations",
     "Минимальный интервал между понижениями стадии (анти-откат)."),
    ("RELATIONS_DOWNGRADE_MSG_30D", "Понижение только при сообщений/30д", "int", "limits_relations",
     "Понижение возможно, только если сообщений за 30 дней меньше порога."),
    ("RELATIONS_DECAY_HALF_LIFE_DAYS", "Полураспад активности, дней", "int", "limits_relations",
     "Период, за который вклад сообщения в activity_score падает вдвое."),
    ("RELATIONS_RECALC_TTL_MINUTES", "Пересчёт карточек не чаще, минут", "int", "limits_relations",
     "Как долго не пересчитывать карточки участников повторно."),
    ("RELATIONS_SCAN_MAX_ROWS", "Потолок строк окна скана", "int", "limits_relations",
     "Строк окна decay > порога — окно сжимается вдвое (до 3 итераций)."),
    ("RELATIONS_INJECT_MAX_CHARS", "Кап инжекта <user_relations>, символов", "int", "limits_relations",
     "Потолок символов блока отношений в контексте (600; блок uncuttable бюджетом)."),
    ("RELATIONS_API_MAX_USERS", "Потолок участников в списке", "int", "limits_relations",
     "Лимит refresh/GET relations без явного списка (топ по активности)."),
    # ── Раунд 9 (фикс-раунд, spec §3.6.4/Q11): dig_into_lore — лимиты ──
    ("DIG_MAX_SNIPPETS", "dig_into_lore: сниппетов переписки", "int", "limits_memory",
     "Сколько датированных строк переписки возвращает инструмент (8)."),
    ("DIG_MAX_FACTS", "dig_into_lore: фактов графа", "int", "limits_memory",
     "Сколько строк «факт дата: текст» возвращает инструмент (3)."),
    ("DIG_MAX_SYMBOLS", "dig_into_lore: потолок результата, символов", "int", "limits_memory",
     "Обрезка результата копания (3500). Больше — полнее, но дороже."),
    ("DIG_GRAPH_HOP_DEPTH", "dig_into_lore: глубина граф-обхода имён", "int", "limits_memory",
     "На сколько ходов BFS по рёбрам графа расширять запрос именами людей (2)."),
    ("DIG_YEAR_BACK_WINDOW_DAYS", "dig_into_lore: окно «N лет назад», дней", "int", "limits_memory",
      "Диапазон вокруг даты «N лет назад» в запросе без явного года (2 дня)."),
    # ── Раунд 10 (multi-chat-rbac-byok, F-7 §5.2): бюджет глобального ключа ──
    ("CHAT_GLOBAL_KEY_BUDGET_TOKENS", "Глобальный ключ: потолок слов в сутки (чат)",
     "int", "limits_chat",
     "Суточный запас текста общего ключа для чата без своего ключа. "
     "0 — общий ключ чату запрещён."),
    ("CHAT_GLOBAL_KEY_BUDGET_REQUESTS", "Глобальный ключ: потолок вызовов в сутки (чат)",
     "int", "limits_chat",
     "Суточный запас вызовов общего ключа для чата без своего ключа. "
     "0 — общий ключ чату запрещён."),
    # ── Раунд 10 (feature-gates-worker-budget, F-10 §5.2): воркер-бюджет ──
    # (ФИКС R3: группа limits_worker; PG-ключи limits.worker_daily_* /
    # limits.worker_priority_order / limits.worker_budget_jitter_minutes)
    ("WORKER_DAILY_LLM_CALLS_GLOBAL", "Фон: дневной потолок вызовов нейросети (все чаты)",
     "int", "limits_worker",
     "Общий суточный запас вызовов фоновых воркеров (сон, ностальгия, лор). "
     "Исчерпан — отключаются по приоритету."),
    ("WORKER_DAILY_LLM_TOKENS_GLOBAL", "Фон: дневной потолок слов (все чаты)",
     "int", "limits_worker",
     "Общий суточный запас текста для фоновых воркеров."),
    ("WORKER_DAILY_LLM_CALLS_PER_CHAT", "Фон: дневной потолок вызовов нейросети (чат)",
     "int", "limits_worker",
     "Суточный запас вызовов фоновых воркеров для одного чата."),
    ("WORKER_DAILY_LLM_TOKENS_PER_CHAT", "Фон: дневной потолок слов (чат)",
     "int", "limits_worker",
     "Суточный запас текста фоновых воркеров для одного чата."),
    ("WORKER_PRIORITY_ORDER", "Фон: порядок деградации воркеров", "str",
     "limits_worker",
     "Порядок приоритетов: последний падает первым (по умолчанию "
     "nostalgia,lore,dream → первым падает dream). CSV имён воркеров."),
    ("WORKER_BUDGET_JITTER_MINUTES", "Фон: разброс тиков, минут", "int",
     "limits_worker",
     "Случайный сдвиг тиков фоновых воркеров (≤ интервал/3)."),
    ("WORKER_BUDGET_TZ", "Фон: таймзона дня бюджетов", "str",
     "limits_worker",
     "Локальная таймзона, в которой считаются сутки бюджета фоновых "
     "воркеров (по умолчанию Asia/Yekaterinburg)."),
]

# ── reactions: id-списки, слова, пути, названия (не секреты) ────────────────
# (field, title_ru, type, group, description)
_REACTIONS: list[tuple] = [
    ("SLAVIK_USER_ID", "Telegram ID Славика", "int", "reactions_slavik",
     "Кто такой Славик для бота. По этому ID он узнаёт сообщения Славика и его реакции; ошибёшься — Славик замолчит или оживёт не тот человек."),
    ("KOSTIK_USER_ID", "Telegram ID Костика", "int", "reactions_kostik",
     "Telegram ID Костика — для его ответов и мимикрии."),
    # Раунд 10.12 (ADR-1012-1 D4): редактируемый список фраз-реплик Костика
    # (JSON-массив строк, виджет list). Пустой список → молчание.
    ("KOSTIK_REPLIES", "Фразы-реплики Костика", "json", "reactions_kostik",
     "Список фраз, которыми бот отвечает Костю. Каждая фраза — отдельное поле; можно добавлять и удалять.", "list"),
    ("ALAN_USER_ID", "Telegram ID Лехи", "int", "reactions_alan",
     "Telegram ID Лехи — для приветствий и reply-блока."),
    ("ADMIN_USER_ID", "Telegram ID админа", "int", "reactions_admin",
      "Telegram ID администратора — для особых прав и реакций."),
    ("DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "Канал-источник dead page (@d_pages)", "str", "reactions_deadpage",
     "Откуда берутся посты dead page. Указывается с @."),
    ("DEAD_PAGE_SOURCE_CHANNEL_ID", "ID канала-источника dead page", "int", "reactions_deadpage",
     "Числовой ID канала-источника. Меняется, если пересоздали канал."),
    ("DEAD_PAGE_RELAY_CHANNEL_ID", "ID relay-канала dead page", "int", "reactions_deadpage",
     "Куда бот пересылает посты dead page."),
    ("DEAD_PAGE_DIR", "Папка медиа dead page", "str", "reactions_deadpage",
     "Папка с медиа для постов dead page. Относительно корня медиа."),
    ("ALAN_USERNAME", "Юзернейм Лехи", "str", "reactions_alan",
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
    ("ALAN_MIMIC_ENABLED", "Мимикрия Лехи", "bool", "reactions_permsoc",
      "Передразнивать сообщения Лехи (нужно также включить общий рубильник „Мимикрия включена”). Других „жертв” из списка этот тумблер не касается."),
    ("VASYA_ENABLED", "Реакция „Вася → АДМИН”", "bool", "reactions_word_reactions",
     "Кто-то написал „Вася” — бот отвечает „АДМИН”; кто-то написал „админ” — бот отвечает „ВАСЯ”. Выключено — реакция молчит."),
    ("KUCHA_ENABLED", "Реакция „куча → ДАЛБАЕБ”", "bool", "reactions_permsoc",
      "Кто-то написал „куча” — бот отвечает „ДАЛБАЕБ”. Выключено — реакции нет (гифка Славика работает независимо)."),
    ("OLYA_USER_ID", "Telegram ID Оли", "int", "reactions_olya",
     "Кто такая Оля. По этому ID бот ловит её видео и реагирует; не тот номер — Оля останется без ответа."),
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
    ("CHAT_BOTWORD_PATTERN", "Шаблон триггеров «бот»-семьи", "str", "reactions_chat",
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
     "Отключает удаление и сжатие памяти по срокам: всё хранится "
     "бессрочно (для импорта истории).",
     "basic"),
    # ── Раунд 9 (T-824/T-825, spec §3.6.4): «сон» (группа memory_dream) ──
    # dotted-ключи memory.dream_* (прецедент memory.infinite_retention);
    # дефолты консервативные (Q12: dream_enabled off).

    ("DREAM_ENABLED", "Сон: синтез убеждений (DreamWorker)", "bool",
     "memory_dream",
     "Рубильник фонового DreamWorker: из повторяющихся фактов чата модель "
     "делает устойчивые убеждения (beliefs). Выключено (дефолт) — тик не "
     "регистрируется, 0 влияния.",
     "basic"),

    ("DREAM_TICK_MINUTES", "Сон: период тика, минут", "int", "memory_dream",
     "Как часто воркер проверяет чаты на новые факты. "
     "Первый «сон» случится внутри ночного окна, когда бы бот ни запустился.",
     "advanced"),

    ("DREAM_WINDOW_START_HOUR", "Сон: окно дистилляций с (час local)", "int",
     "memory_dream",
     "Синтез (тратит деньги) идёт только в эти часы. "
     "Вне окна — бесплатный подбор кластеров.",
     "advanced"),

    ("DREAM_WINDOW_END_HOUR", "Сон: окно дистилляций до (час local)", "int",
     "memory_dream",
     "Конец окна дистилляций (6).",
     "advanced"),

    ("DREAM_INITIAL_WINDOW_HOURS", "Сон: окно прогрева, часов", "int",
     "memory_dream",
     "Первый «сон» чата без watermark берёт факты за этот период (168 = "
     "неделя — история импорта не захлёбывает первый прогон).",
     "advanced"),

    ("DREAM_MIN_NEW_FACTS_PER_CHAT", "Сон: мин. новых фактов для чата", "int",
     "memory_dream",
     "Чат-кандидат тика — только при новых фактах не меньше порога (5).",
     "advanced"),

    ("DREAM_MAX_CHATS_PER_RUN", "Сон: максимум чатов за тик", "int",
     "memory_dream",
     "Потолок чатов одного тика (10), топ по числу новых фактов.",
     "advanced"),

    ("DREAM_QUIET_CHECK_MINUTES", "Сон: тишина перед тиком, минут", "int",
     "memory_dream",
     "«Не пик»: чат с сообщениями за последние N минут пропускается (30).",
     "advanced"),

    ("DREAM_CLUSTER_OVERLAP_TOKENS", "Сон: общих слов для кластера", "int",
     "memory_dream",
     "Сколько общих значимых слов нужно, чтобы факт попал "
     "в кластер.",
     "advanced"),

    ("DREAM_REPEAT_THRESHOLD", "Сон: повторяемость кластера (членов)", "int",
     "memory_dream",
     "Кластер идёт в дистилляцию при членах не меньше порога (3).",
     "advanced"),

    ("DREAM_IMPORTANCE_SUM_THRESHOLD", "Сон: Σ важности кластера", "int",
     "memory_dream",
     "Кластер идёт в дистилляцию при сумме importance не меньше порога (12).",
     "advanced"),

    ("DREAM_MAX_CLUSTERS_PER_RUN", "Сон: кластеров в дистилляцию за тик",
     "int", "memory_dream",
     "Потолок кластеров на тик (5), топ по сумме важности.",
     "advanced"),

    ("DREAM_DISTILLATIONS_PER_DAY", "Сон: дистилляций в сутки", "int",
     "memory_dream",
     "Глобальный суточный лимит успешных синтезов (30; по memory_dream_log).",
     "advanced"),

    ("DREAM_TOKENS_PER_DAY", "Сон: слов в сутки (денежный)", "int",
     "memory_dream",
     "Суточный запас текста на синтез «сна». "
     "Больше — глубже сны, больше расход.",
     "advanced"),
    # ── Раунд 9 (T-826/T-827, spec §3.6.4): ностальгия (memory_nostalgia) ──
    # dotted-ключи memory.nostalgia_* (тот же прецедент memory.dream_*);
    # дефолты консервативные (Q12: оба рубильника off).

    ("NOSTALGIA_ENABLED", "Ностальгия: слой B (NostalgiaWorker)", "bool",
     "memory_nostalgia",
     "Рубильник фонового NostalgiaWorker: в тихих группах по старым "
     "сообщениям чата модель шлёт 1-2 фразы «кстати...». Выключено "
     "(дефолт) — тик не регистрируется, 0 влияния.",
     "basic"),

    ("NOSTALGIA_LAYER_A_ENABLED", "Ностальгия: слой A (маркер при ответе)",
     "bool", "memory_nostalgia",
     "Если в памяти нашёлся «золотой» факт, бот получает подсказку "
     "вплести его в ответ. Лишних вызовов нейросети нет.",
     "basic"),

    ("NOSTALGIA_TICK_MINUTES", "Ностальгия: период тика, минут", "int",
     "memory_nostalgia",
     "Как часто воркер проверяет чаты на тишину и кандидатов (60).",
     "advanced"),

    ("NOSTALGIA_MIN_SILENCE_MINUTES", "Ностальгия: тишина, минут", "int",
     "memory_nostalgia",
     "Последнее юзерское сообщение должно быть старше N минут — иначе чат "
     "пропускается (45).",
     "advanced"),

    ("NOSTALGIA_QUIET_START_HOUR", "Ностальгия: тихие часы с (час local)",
     "int", "memory_nostalgia",
     "Ночные тихие часы (пересечение полуночи): чат пропускается, если local-"
     "час ≥ start ИЛИ < end (23).",
     "advanced"),

    ("NOSTALGIA_QUIET_END_HOUR", "Ностальгия: тихие часы до (час local)",
     "int", "memory_nostalgia",
     "Конец ночных тихих часов (8).",
     "advanced"),

    ("NOSTALGIA_COOLDOWN_HOURS", "Ностальгия: пауза между отправками, часов",
     "int", "memory_nostalgia",
     "Между двумя проактивными сообщениями чата — не меньше N часов (12).",
     "advanced"),

    ("NOSTALGIA_PAUSE_HOURS", "Ностальгия: пауза после неотвеченных, часов",
     "int", "memory_nostalgia",
     "После неотвеченных проактивных чат пропускается, пока не пройдёт N "
     "часов с последней отправки (24).",
     "advanced"),

    ("NOSTALGIA_UNANSWERED_MAX", "Ностальгия: стоп неотвеченных подряд", "int",
     "memory_nostalgia",
     "Стоп после N проактивных подряд без ответа юзера (детект по "
     "smart_messages после ts отправки) (2).",
     "advanced"),

    ("NOSTALGIA_MAX_PER_DAY", "Ностальгия: отправок в сутки на чат", "int",
     "memory_nostalgia",
     "Дневной лимит status='sent' по nostalgia_log за local-сутки (3); "
     "skipped/unchanged лимит не тратят.",
     "advanced"),

    ("NOSTALGIA_GOLDEN_MIN_DAYS", "Ностальгия: «золотой» возраст, дней", "int",
     "memory_nostalgia",
     "Факт считается «золотым» при давности ≥ N дней по COALESCE("
     "message_timestamp, created_at) (60).",
     "advanced"),

    ("NOSTALGIA_GOLDEN_MIN_IMPORTANCE", "Ностальгия: «золотая» важность", "int",
     "memory_nostalgia",
     "Порог importance факта для «золотого» (v8-шкала 1..10; дефолт 5).",
     "advanced"),

    ("NOSTALGIA_LAYER_A_MAX_HINTS", "Ностальгия: хинтов на ответ (слой A)",
     "int", "memory_nostalgia",
     "Максимум строк-маркеров «золотых» за один ответ (1).",
     "advanced"),

    ("NOSTALGIA_HINT_MAX_CHARS", "Ностальгия: маркер слоя A, символов", "int",
     "memory_nostalgia",
     "Фикс-кап строки-маркера до инжекта в контекст (300).",
     "advanced"),

    ("NOSTALGIA_YEAR_BACK_DAYS_WINDOW", "Ностальгия: окно «год назад», дней",
     "int", "memory_nostalgia",
     "Кандидаты «N лет назад» — timestamp в диапазоне год назад ± N дней "
     "вокруг точной даты (2).",
     "advanced"),

    ("NOSTALGIA_AGGRESSIVENESS", "Ностальгия: агрессивность (0..1)", "float",
     "memory_nostalgia",
     "Порог срабатывания кандидата = 0.3 + агрессивность*0.5 (дефолт 0.3 → "
     "порог 0.45). Влияет ТОЛЬКО на порог («насколько слабый повод "
     "сработает»); частота — лимитами/паузами выше.",
     "advanced"),

     ("NOSTALGIA_MAX_SEND_CHARS", "Ностальгия: текст сообщения, символов",
      "int", "memory_nostalgia",
      "Кап текста проактивного сообщения перед отправкой (400).",
     "advanced"),
]


def resolve_progressive_level(spec: ParamSpec) -> str:
    """Правило по умолчанию (F-11 §4.1): advanced для групп памяти/RAG и
    ключей с техническими маркерами; явная разметка — приоритет."""
    if spec.progressive_level:
        return spec.progressive_level
    if spec.group in _ADVANCED_GROUPS:
        return "advanced"
    key = (spec.pg_key or "").lower()
    if any(marker in key for marker in _ADVANCED_KEY_MARKERS):
        return "advanced"
    return "basic"


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
    for pg_id, title, group, code_source, desc in _MODELS_PG_ONLY:
        add(ParamSpec(None, None, CATEGORY_MODELS, title, "str",
                      code_source=code_source, pg_id=pg_id,
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
        if len(row) == 6:      # (field, title, type, group, desc, widget)
            field, title, typ, group, desc, widget = row
        else:
            field, title, typ, group, desc = row
            widget = ""
        add(ParamSpec(field, field, CATEGORY_REACTIONS, title, typ,
                      group=group, description=desc, widget=widget))
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
    for spec_id, title, code_source, group, desc in _CONTENT_STR:
        add(ParamSpec(None, None, CATEGORY_CONTENT, title, "str",
                      code_source=code_source, pg_id=spec_id,
                      group=group, description=desc))
    for row in _MEMORY:      # (field, title, type, group, desc[, level])
        if len(row) == 6:
            field, title, typ, group, desc, level = row
        else:
            field, title, typ, group, desc = row
            level = ""
        add(ParamSpec(field, field, CATEGORY_MEMORY, title, typ,
                      group=group, description=desc,
                      pg_id=f"{CATEGORY_MEMORY}.{field.lower()}",
                      progressive_level=level))
    return registry


REGISTRY: dict[str, ParamSpec] = _build_registry()

# Раунд 10.4 (B-7/B-8): select-виджеты — опции/подписи (без роста записей).
_SELECT_WIDGET_PRESETS: dict[str, dict] = {
    "CHAT_TEMPERATURE_PRESET_DEFAULT": {
        "widget": "select",
        "select_options": ("precise", "balanced", "chatty"),
        "select_labels": ("Точный", "Сбалансированный", "Болтливый"),
    },
}
for _name, _opts in _SELECT_WIDGET_PRESETS.items():
    _spec = REGISTRY.get(_name)
    if _spec is not None:
        REGISTRY[_name] = dataclasses.replace(_spec, **_opts)

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
# ── Раунд 10.6 (T-1201/T-1208): 19 config-вкладок ─────────────────────────
# 11 «Модули» (mod_*) + LLM Провайдеры + Промпты + Память + Умный кэш +
# Имена + Участники и отношения + Лор чата + Функции PERMsoc.
TAB_MOD_SUMMARY = "mod_summary"
TAB_MOD_DIRECT = "mod_direct"
TAB_MOD_FACTCHECK = "mod_factcheck"
TAB_MOD_SEARCH = "mod_search"
TAB_MOD_TRANSCRIBE = "mod_transcribe"
TAB_MOD_VIDEO_SUMMARY = "mod_video_summary"
TAB_MOD_MEDIA_DOWNLOAD = "mod_media_download"
TAB_MOD_WEB = "mod_web"
TAB_MOD_CHECKUP = "mod_checkup"
TAB_MOD_SLEEP = "mod_sleep"
TAB_MOD_NOSTALGIA = "mod_nostalgia"
TAB_LLM_PROVIDERS = "llm_providers"
TAB_PROMPTS = "prompts"
TAB_MEMORY_RAG = "memory_rag"
TAB_SMART_CACHE = "smart_cache"
TAB_PEOPLE_NAMES = "people_names"
TAB_RELATIONS = "relations"
TAB_CHAT_LORE = "chat_lore"
# Ре-дизайн 10.2, BUG-3 (spec §10 A): штатная вкладка «Функции PERMsoc».
TAB_PERMSOC = "permsoc"

CONFIG_TAB_TITLES: dict[str, str] = {
    TAB_MOD_SUMMARY: "Саммаризация",
    TAB_MOD_DIRECT: "Прямые ответы",
    TAB_MOD_FACTCHECK: "Фактчек",
    TAB_MOD_SEARCH: "Поиск",
    TAB_MOD_TRANSCRIBE: "Транскрипт голосовых и видео",
    TAB_MOD_VIDEO_SUMMARY: "Выжимка видео",
    TAB_MOD_MEDIA_DOWNLOAD: "Скачивание медиа",
    TAB_MOD_WEB: "Веб-страницы",
    TAB_MOD_CHECKUP: "Диагностика",
    TAB_MOD_SLEEP: "Сон",
    TAB_MOD_NOSTALGIA: "Ностальгия",
    TAB_LLM_PROVIDERS: "LLM Провайдеры",
    TAB_PROMPTS: "Промпты",
    TAB_MEMORY_RAG: "Память",
    TAB_SMART_CACHE: "Умный кэш",
    TAB_PEOPLE_NAMES: "Имена",
    TAB_RELATIONS: "Участники и отношения",
    TAB_CHAT_LORE: "Лор чата",
    TAB_PERMSOC: "Функции PERMsoc",
}

TAB_RULES: tuple[tuple[str, tuple[tuple[str, object], ...]], ...] = (
    # ── 11 модулей (spec §4.2) ─────────────────────────────────────────────
    (TAB_MOD_SUMMARY, (
        (CATEGORY_FLAGS,
         frozenset({"flags_module_summary", "flags_summary"})),
        (CATEGORY_LIMITS, frozenset({"limits_summary"})),
        (CATEGORY_REACTIONS, frozenset({"reactions_summary"})),
    )),
    (TAB_MOD_DIRECT, (
        (CATEGORY_FLAGS,
         frozenset({"flags_module_direct", "flags_chat_behavior"})),
        (CATEGORY_LIMITS, frozenset({
            "limits_chat", "limits_chat_behavior", "limits_chat_budgets",
            "limits_temperature"})),
        (CATEGORY_REACTIONS, frozenset({"reactions_chat"})),
    )),
    (TAB_MOD_FACTCHECK, (
        (CATEGORY_FLAGS, frozenset({"flags_module_factcheck"})),
        (CATEGORY_LIMITS, frozenset({"limits_factcheck"})),
    )),
    (TAB_MOD_SEARCH, (
        (CATEGORY_FLAGS, frozenset({"flags_module_search"})),
        (CATEGORY_LIMITS, frozenset({"limits_search"})),
    )),
    (TAB_MOD_TRANSCRIBE, (
        (CATEGORY_FLAGS, frozenset({"flags_module_transcribe"})),
        (CATEGORY_LIMITS, frozenset({"limits_transcribe"})),
    )),
    (TAB_MOD_VIDEO_SUMMARY, (
        (CATEGORY_FLAGS, frozenset({"flags_module_video_summary"})),
        (CATEGORY_LIMITS, frozenset({
            "limits_video_summary", "limits_youtube",
            "limits_youtube_proxy"})),
        (CATEGORY_KEYS, frozenset({"keys_youtube"})),
    )),
    (TAB_MOD_MEDIA_DOWNLOAD, (
        (CATEGORY_FLAGS, frozenset({"flags_module_media_download"})),
        (CATEGORY_LIMITS, frozenset({"limits_media_download"})),
    )),
    (TAB_MOD_WEB, (
        (CATEGORY_FLAGS, frozenset({"flags_module_web"})),
        (CATEGORY_LIMITS, frozenset({"limits_web"})),
    )),
    (TAB_MOD_CHECKUP, (
        (CATEGORY_FLAGS, frozenset({"flags_service", "flags_throttle"})),
        (CATEGORY_LIMITS, frozenset({
            "limits_checkup", "limits_service", "limits_worker"})),
        (CATEGORY_MODELS, frozenset({"models_checkup"})),
        (CATEGORY_KEYS, frozenset({"keys_betterstack"})),
    )),
    (TAB_MOD_SLEEP, (
        (CATEGORY_MEMORY, frozenset({"memory_dream"})),
    )),
    (TAB_MOD_NOSTALGIA, (
        (CATEGORY_MEMORY, frozenset({"memory_nostalgia"})),
    )),
    # ── Настройки AI (7 подразделов) ───────────────────────────────────────
    # A8: keys_youtube → М6, models_checkup/keys_betterstack → М9.
    (TAB_LLM_PROVIDERS, (
        (CATEGORY_MODELS, frozenset({
            "models_main", "models_fallback", "models_embeddings",
            "models_llm_timeouts", "models_llm_guard",
            "models_extra_providers", "models_video_summary"})),
        (CATEGORY_KEYS, frozenset({
            "keys_llm", "keys_groq", "keys_openrouter", "keys_search",
            "keys_media"})),
    )),
    (TAB_PROMPTS, (
        (CATEGORY_PROMPTS, None),
    )),
    # A3/D3: RAG-ключи в «Память» (limits_rag).
    (TAB_MEMORY_RAG, (
        (CATEGORY_LIMITS, frozenset({
            "limits_memory", "limits_graph", "limits_rag"})),
        (CATEGORY_FLAGS, frozenset({"flags_memory"})),
        (CATEGORY_MEMORY, frozenset({"memory_infinite"})),
        (CATEGORY_REACTIONS, frozenset({"reactions_memory"})),
    )),
    (TAB_SMART_CACHE, (
        (CATEGORY_LIMITS, frozenset({"limits_smart_cache"})),
        (CATEGORY_FLAGS, frozenset({"flags_smart_cache"})),
    )),
    (TAB_PEOPLE_NAMES, (
        (CATEGORY_LIMITS, frozenset({"limits_user_aliases"})),
    )),
    (TAB_RELATIONS, (
        (CATEGORY_LIMITS, frozenset({"limits_relations"})),
        (CATEGORY_FLAGS, frozenset({"flags_relations"})),
    )),
    (TAB_CHAT_LORE, (
        (CATEGORY_LIMITS, frozenset({"limits_lore"})),
        (CATEGORY_FLAGS, frozenset({"flags_lore"})),
    )),
    # Ре-дизайн 10.2/10.6: «Функции PERMsoc» — персоны/модули-реакции +
    # рубильники + лимиты персон/медиа.
    (TAB_PERMSOC, (
        (CATEGORY_REACTIONS, frozenset({
            "reactions_admin", "reactions_deadpage",
            "reactions_slavik", "reactions_alan", "reactions_kostik",
            "reactions_war", "reactions_common", "reactions_goodmorning",
            "reactions_mimic", "reactions_olya",
            "reactions_word_reactions", "reactions_permsoc"})),
        (CATEGORY_FLAGS, frozenset({
            "flags_permsoc", "flags_media", "flags_permsoc_behavior"})),
        (CATEGORY_LIMITS, frozenset({
            "limits_alan", "limits_kostik", "limits_media_permsoc",
            "limits_mimic", "limits_deadpage"})),
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
    """Секции-идентификаторы для валидации/дерева прав (категории + access
    + chat_lore — раунд 7, chat-lore-management-v2 §3.8/Q6)."""
    return set(CATEGORIES) | {"access", "chat_lore"}


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