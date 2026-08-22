"""Epic 43 — InfoService (R43-2, Section 52.3): info_text.md + кэш в память.

Чтение при старте; запись ТОЛЬКО через save_text() (вызывается хендлером
ПОСЛЕ успешной рендер-валидации превью — D163). Файла нет/пустой → канон
DEFAULT_INFO_TEXT записывается на диск. IO-ошибка чтения → WARNING + кэш =
канон (файл НЕ перезаписываем). Sync-IO оправдан: файл ~1-2 КБ, пути —
только старт и редкие правки админа (не горячий event-loop путь).
"""
import logging

from config.settings import settings

logger = logging.getLogger(__name__)

# КАНОН дефолтной справки (Epic 44 R44-1 → Epic 55 T-431 → Epic 56 T-437, Section 53.3) — байт-в-байт тест
DEFAULT_INFO_TEXT = """<b>Гайд по фичам бота с выходом в сеть internet. Никаких слеш-команд, всё работает нативно прямо в диалоге.</b>

<b>1. Фактчек сообщений и новостей (чтобы чекать репосты Лехи)</b>
- Как вызвать: сделай Reply (ответ) на любое сообщение или репост в чате и напиши слово <blockquote>фактчек</blockquote>.
- С уточнением: если нужно проверить конкретную деталь, допиши вопрос следом.
Например: <blockquote>фактчек правда ли склад сгорел?</blockquote> или <blockquote>фактчек поясни за цифры</blockquote>.
Бот поднимет поисковики, проверит достоверность и выдаст вердикт в своем стиле прямо в ответ на исходный пост.

<b>2. Поиск инфы (кому лень зайти в гугл во время срача)</b>
- Как вызвать: просто начни сообщение со слов <blockquote>найди</blockquote>, <blockquote>поищи</blockquote> или <blockquote>загугли</blockquote> и дальше пиши суть.
- Примеры: <blockquote>загугли почему видеокарта греется в простое</blockquote> / <blockquote>найди последние новости про новый патч</blockquote>
Бот соберет факты из сети и пришлет выжимку реплаем на твое сообщение.
Нюансы: На поиск и <blockquote>фактчек</blockquote> стоят раздельные кулдауны по 5 минут. Если спамить — бот пошлет вас нахуй.

<b>3. Пересказ ролика с ютуба (если есть субтитры):</b>
Способ 1 (реплай): Ответь на сообщение с ютуб-ссылкой и напиши: <blockquote>транскрипт</blockquote>, <blockquote>че за видос</blockquote>, <blockquote>о чем видео</blockquote>, <blockquote>поясни за видос</blockquote>.
Способ 2 (одной строкой): Просто кинь ссылку и фразу в одном сообщении (<a href="https://youtu.be/">https://youtu.be/</a>... <blockquote>поясни за видос</blockquote>).
Бот не распознает само видео, он парсит сабы и пересказывает суть.

<b>4. Пересказ веб-страницы</b>
Способ 1 (реплай): Ответь на сообщение с ссылкой и напиши: <blockquote>поясни за ссылку</blockquote>, <blockquote>че по ссылке</blockquote>, <blockquote>о чем статья</blockquote>, <blockquote>выжимка</blockquote>.
Способ 2 (одной строкой): Ссылка + фраза (<a href="https://какой-то-сайт.ru">https://какой-то-сайт.ru</a> <blockquote>выжимка</blockquote>).
Опять же бот не "видит" веб-страницу, а парсит ее маркдаун версию, пересказывает на свой лад.

<b>5. Checkup (Здоровье бота)</b>
Хочешь узнать, жив ли бот и сервак? Команда заставить его посмотреть внутрь себя.
Как вызвать: напиши в чат <blockquote>чекап</blockquote>, <blockquote>ты в порядке</blockquote>, <blockquote>живой собака</blockquote> или <blockquote>чекни здоровье</blockquote>.
Бот залезет в системные логи, найдет свежие ошибки и токсично пояснит, что отвалилось на сервере.

<b>6. Прямое обращение к Богу Машине</b>
 Способ 1 (словами через рот): Бот откликается на <blockquote>бот</blockquote>, <blockquote>ботик</blockquote>, <blockquote>ботяра</blockquote> и <blockquote>ботохуета</blockquote>. Как вызвать: просто напиши одно из этих слов в чат - бот ответит реплаем на твое сообщение. Робот, работа и ботва не в счет: они его не разбудят.
 Способ 2 (реплай): бот отвечает если ответить (Reply) на его сообщение.
 Способ 3 (тегнуть): Бот ответит на тег через "@"."""


class InfoService:
    def __init__(self, file_path: str = settings.INFO_TEXT_FILE) -> None:
        self._file_path = file_path
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
        return self._cache if self._cache is not None else DEFAULT_INFO_TEXT

    def save_text(self, text: str) -> None:
        """Перезапись файла + кэш. ВЫЗЫВАТЬ ТОЛЬКО ПОСЛЕ успешного превью (D163).
        OSError — НАВЕРХ (хендлер шлёт пул, кэш остаётся старым)."""
        with open(self._file_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self._cache = text
        logger.info("[info service] info_text.md updated | file=%s | chars=%d",
                    self._file_path, len(text))

    def _write_default(self) -> None:
        with open(self._file_path, "w", encoding="utf-8") as fh:
            fh.write(DEFAULT_INFO_TEXT)
