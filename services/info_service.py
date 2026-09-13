"""Epic 43 — InfoService (R43-2, Section 52.3): info_text.md + кэш в память.

Epic 85 (84.13, T-638): источник истины — БД/ConfigCache (ключ
content.info_how_it_works, сидится ConfigCache.init при первом старте из
info_text.md); get_text() читает ConfigCache → файловый кэш → DEFAULT_INFO_TEXT
(legacy-фолбек при PG down, R6). save_text() — единственная точка записи:
файл + in-memory кэш + ConfigCache (хендлер /edit_info и веб-POST /api/info
сходятся в ней). Файла нет/пустой → канон DEFAULT_INFO_TEXT записывается на
диск. IO-ошибка чтения → WARNING + кэш = канон (файл НЕ перезаписываем).
"""
import datetime
import logging
from pathlib import Path

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# КАНОН дефолтной справки (Epic 44 R44-1 → … → Epic 71 T-549, Section 53.3 → Epic 83 T-599, Section 83 D306: байт-в-байт c info_text.md) — байт-в-байт тест
DEFAULT_INFO_TEXT = """<h1>Гайд по фичам бота. Никаких слеш-команд, всё работает нативно прямо в диалоге.</h1>

<h2>1. Фактчек сообщений и новостей (чтобы чекать репосты Лехи)</h2>
<h5>- Как вызвать: сделай Reply (ответ) на любое сообщение или репост в чате и напиши слово <h4><b><i>фактчек</i></b></h4>.
- С уточнением: если нужно проверить конкретную деталь, допиши вопрос следом.
Например: <h4><b><i>фактчек правда ли склад сгорел?</i></b></h4> или <h4><b><i>фактчек поясни за цифры</i></b></h4>.
Бот поднимет поисковики, проверит достоверность и выдаст вердикт в своем стиле прямо в ответ на исходный пост.</h5>

<h2>2. Поиск инфы (кому лень зайти в гугл во время срача)</h2>
<h5>- Как вызвать: просто начни сообщение со слов <h4><b><i>найди</i></b></h4>, <h4><b><i>поищи</i></b></h4> или <h4><b><i>загугли</i></b></h4> и дальше пиши суть.
- Примеры: <h4><b><i>загугли почему видеокарта греется в простое</i></b></h4> / <h4><b><i>найди последние новости про новый патч</i></b></h4>
Бот соберет факты из сети и пришлет выжимку реплаем на твое сообщение.
Нюансы: На поиск и <h4><b><i>фактчек</i></b></h4> стоят раздельные кулдауны по 5 минут. Если спамить — бот пошлет вас нахуй.</h5>

<h2>3. Пересказ ролика с ютуба (если есть субтитры):</h2>
<h5>Способ 1 (реплай): Ответь на сообщение с ютуб-ссылкой и напиши: <h4><b><i>транскрипт</i></b></h4>, <h4><b><i>че за видос</i></b></h4>, <h4><b><i>о чем видео</i></b></h4>, <h4><b><i>поясни за видос</i></b></h4>.
Способ 2 (одной строкой): Просто кинь ссылку и фразу в одном сообщении (<a href="https://youtu.be/">https://youtu.be/</a>... <b><i>поясни за видос</i></b>).
Бот не распознает само видео, он парсит сабы и пересказывает суть.</h5>

<h2>4. Пересказ веб-страницы</h2>
<h5>Способ 1 (реплай): Ответь на сообщение с ссылкой и напиши: <h4><b><i>поясни за ссылку</i></b></h4>, <h4><b><i>че по ссылке</i></b></h4>, <h4><b><i>о чем статья</i></b></h4>, <h4><b><i>выжимка</i></b></h4>.
Способ 2 (одной строкой): Ссылка + фраза (<a href="https://какой-то-сайт.ru">https://какой-то-сайт.ru</a> <b><i>выжимка</i></b>).
Опять же бот не "видит" веб-страницу, а парсит ее маркдаун версию, пересказывает на свой лад.</h5>

<h2>5. Checkup (Здоровье бота)</h2>
<h5>Хочешь узнать, жив ли бот и сервак? Команда заставить его посмотреть внутрь себя.
Как вызвать: напиши в чат <h4><b><i>чекап</i></b></h4>, <h4><b><i>ты в порядке</i></b></h4>, <h4><b><i>живой собака</i></b></h4> или <h4><b><i>чекни здоровье</i></b></h4>.
Бот залезет в системные логи, найдет свежие ошибки и токсично пояснит, что отвалилось на сервере.</h5>

<h2>6. Прямое обращение к Богу Машине</h2>
<h5>Способ 1 (словами через рот): Бот откликается на <h4><b><i>бот</i></b></h4>, <h4><b><i>ботик</i></b></h4>, <h4><b><i>ботяра</i></b></h4> и <h4><b><i>ботохуета</i></b></h4>. Как вызвать: просто напиши одно из этих слов в чат - бот ответит реплаем на твое сообщение. Робот, работа и ботва не в счет: они его не разбудят.
Способ 2 (реплай): бот отвечает если ответить (Reply) на его сообщение.
Способ 3 (тегнуть): Бот ответит на тег через "@".</h5>

<h2>7. Скачивание видео</h2>
<h5>Способ 1: напиши <h4><b><i>скачай</i></b></h4>, <h4><b><i>загрузи</i></b></h4> или <h4><b><i>стяни</i></b></h4> и кинь ссылку на видео в одном сообщении.
Способ 2 (реплай): Ответь на сообщение с ссылкой на видео и напиши любое из этих слов.
Бот предложит выбрать качество и зальет файл прямо в чат.
Нюансы: Между скачиваниями стоит кулдаун — сервак не бездонный.</h5>

<h2>8. Расшифровка голосовых и кружочков</h2>
<h5>- Как вызвать: никак, тут авто-режим — просто отправь в чат голосовое или кружочек, бот сам пришлет текст реплаем.
Нюансы: Голосовые длиннее 10 минут бот не осилит.</h5>

<h2>9. Саммари чата</h2>
<h5>Способ 1: Команда <h4><b><i>/summary</i></b></h4> отдает выжимку по истории чата за n времени - по дефолту 6 часов (отсчет идет с 00:00 по таймзоне - дефолт пермское время).
Способ 2: Команда /summary + "по Х", например <h4><b><i>/summary по хуям</i></b></h4> - даст выжимку конкретно по упоминаниям хуев в чате за n времени.
Нюансы:
- Кулдаун между каждым вызовом на одного юзера - по дефолту 5 минут.
- Может путать Никит и Глебов</h5>"""

INFO_KEY = "content.info_how_it_works"

# ── F6 (help-guide-integration-round1014, spec §2.2): гайд в БД ─────────────
# Файл — ТОЛЬКО источник идемпотентного сида (ConfigCache.init), не источник
# истины. Ручные правки из админки живут в PG и сидом не перезатираются.
GUIDE_KEY = "content.intelligence_guide"
# M2-фикс: абсолютный путь от корня проекта (устойчив к CWD systemd/docker).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE_SEED_FILE = str(
    _PROJECT_ROOT / "plans" / "docs" / "intelligence_user_guide.md")
DEFAULT_GUIDE_MARKDOWN = ""   # R6 fail-open: PG down и файла нет → пусто


def _read_text(path: str) -> str:
    """Чтение текстового файла; OSError → '' (fail-open, без исключений)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        logger.warning("[info service] read failed | file=%s", path,
                       exc_info=True)
        return ""


class InfoService:
    def __init__(self, file_path: str | None = None) -> None:
        # Путь резолвится в момент ВЫЗОВА (не в дефолте сигнатуры): default-
        # выражения функций фиксируются при определении класса — monkeypatch
        # settings в тестах и единый источник для web-POST (F5) работают.
        self._file_path = file_path if file_path is not None \
            else settings.INFO_TEXT_FILE
        self._cache: str | None = None

    def load(self) -> None:
        """Чтение при старте. FileNotFoundError/пустой файл → записать канон
        (UTF-8) на диск + кэш = канон; OSError чтения → WARNING + кэш = канон
        (файл НЕ перезаписываем — возможно, проблема прав)."""
        try:
            with open(self._file_path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            self._write_default()
            self._cache = DEFAULT_INFO_TEXT
            logger.info("[info service] default info_text.md created | file=%s",
                        self._file_path)
        except OSError:
            logger.warning("[info service] read failed → in-memory default | file=%s",
                           self._file_path, exc_info=True)
            self._cache = DEFAULT_INFO_TEXT
        else:
            if text.strip():
                self._cache = text
            else:
                self._write_default()          # пустой файл → канон (не битая справка)
                self._cache = DEFAULT_INFO_TEXT
                logger.warning("[info service] empty file → default written | file=%s",
                               self._file_path)

    def get_text(self) -> str:
        """84.13.3 (T-638): ConfigCache → файловый кэш → DEFAULT_INFO_TEXT.
        Источник истины — БД; при PG down/нет ключа — legacy-фолбек (R6)."""
        cached_value = hot.get(INFO_KEY)
        if isinstance(cached_value, dict):
            html = cached_value.get("html")
            if isinstance(html, str) and html.strip():
                return html
        if self._cache is not None:
            return self._cache
        return DEFAULT_INFO_TEXT

    def save_text(self, text: str) -> None:
        """Перезапись файла + кэш + ConfigCache (84.13.3: единственная точка
        записи — /edit_info и веб-POST сходятся здесь). ВЫЗЫВАТЬ ТОЛЬКО ПОСЛЕ
        успешного превью (D163). OSError — НАВЕРХ (хендлер шлёт пул, кэш
        остаётся старым)."""
        with open(self._file_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self._cache = text
        logger.info("[info service] info_text.md updated | file=%s | chars=%d",
                    self._file_path, len(text))
        value = {
            "html": text,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_by": settings.ADMIN_USER_ID,
        }
        _save_to_cache_safely(value)

    def _write_default(self) -> None:
        with open(self._file_path, "w", encoding="utf-8") as fh:
            fh.write(DEFAULT_INFO_TEXT)

    # ── F6 (10.14): гайд по возможностям (Markdown, PG-only) ───────────────

    def get_guide(self) -> dict:
        """Гайд из ConfigCache (PG); PG down/нет ключа → сид-файл (код-канон)
        → пусто. fail-open, 200, без исключений (spec §2.3)."""
        cached = hot.get(GUIDE_KEY)
        if isinstance(cached, dict):
            markdown = cached.get("markdown")
            if isinstance(markdown, str) and markdown.strip():
                return {
                    "markdown": markdown,
                    "updated_at": cached.get("updated_at"),
                    "updated_by": cached.get("updated_by"),
                }
        return {
            "markdown": _read_text(GUIDE_SEED_FILE) or DEFAULT_GUIDE_MARKDOWN,
            "updated_at": None,
            "updated_by": None,
        }

    async def save_guide(self, markdown: str,
                         updated_by: int | None = None) -> dict:
        """F6: ЕДИНСТВЕННАЯ точка записи гайда (POST /api/info/guide).
        Значение → ConfigCache (PG) + in-memory. Без PG — наверх (роут → 503)."""
        from services.config_cache import ConfigCacheUnavailableError

        value = {
            "markdown": markdown,
            "updated_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
            "updated_by": (updated_by if updated_by is not None
                           else settings.ADMIN_USER_ID),
        }
        cache = hot.get_config_cache()
        if cache is None or not cache.pg_available:
            raise ConfigCacheUnavailableError("PostgreSQL недоступен (R6)")
        await cache.set(GUIDE_KEY, value, "content")
        logger.info("[info service] guide saved | chars=%d | by=%s",
                    len(markdown), value["updated_by"])
        return value


def _save_to_cache_safely(value: dict) -> None:
    """T-638: запись в ConfigCache — только если кэш поднят и это async-контекст
    не сломает sync-поток: хендлер /edit_info вызывает save_text из async —
    создаём таску; в тестах/без loop — пропускаем (файл уже источник)."""
    import asyncio

    async def _set():
        cache = hot.get_config_cache()
        if cache is None or not cache.pg_available:
            return
        await cache.set(INFO_KEY, value, "content")

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(_set())
