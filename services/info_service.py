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

# КАНОН дефолтной справки (T-332-B, Section 52.4) — байт-в-байт тест инициализации
DEFAULT_INFO_TEXT = """<b>Я — админ-бот этого чата, вот че я умею</b>

<b>Фактчек</b>
Ответь реплаем на любое сообщение со словом <code>фактчек</code> — проверю инфу, найду пруфы и вынесу вердикт.

<b>Поиск</b>
Напиши <code>найди</code>, <code>поищи</code> или <code>загугли</code> и добавь запрос — соберу свежак и выдам выжимку.
Пример: <code>найди когда выйдет gta 6</code>

<b>YouTube</b>
Скинь ссылку на видео реплаем или одной строкой — выжму суть ролика, смотреть самому не придется.

<b>Веб-статьи</b>
Кинь ссылку на статью реплаем или одной строкой — перескажу коротко и по делу.

<b>Checkup</b>
Спроси <code>чекап</code>, <code>ты в порядке</code>, <code>живой собака</code> или <code>чекни здоровье</code> — полезу в логи сервака и доложу, жив ли я.

<b>Команды</b>
<code>/info</code> — эта справка, <code>/summary</code> — саммари чата, что ты пропустил.

У LLM-фич кулдаун 5 минут — не спамь, шиз."""


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
