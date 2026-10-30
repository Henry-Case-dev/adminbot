"""EVOL §4 — единое разрешение видео-намерения и источника (``VideoIntent``).

Проблема (подтверждённый сценарий §4.1): участник **сначала** просит сделать
выжимку видео, **затем** отдельным сообщением пересылает ролик. Разные
обработчики (``youtube_handler`` 0e, ``direct_chat_handler`` 0h,
``video_download_handler`` 4e) трактовали это как несколько независимых задач:
«не вижу видео», маршрут скачивания, повторный анализ. Модуль даёт **одно**
разрешение намерения и источника ДО запуска любого media-tool.

Контракт (логический, без новой БД/очереди):

* намерение: ``summary`` / ``transcript`` / ``download`` / ``describe`` /
  ``unknown`` — «скачай» это отдельная просьба о файле, а не анализ;
* источник: ``native_video`` / ``video_document`` / ``video_note`` / ``url`` /
  ``platform_forward`` / ``unresolved`` + ``source_ref`` (``file_unique_id``
  либо нормализованный URL/платформенный ID);
* разрешение: ``resolved`` / ``waiting`` / ``ambiguous`` / ``unavailable``.

Приоритет источника (§4.2): 1) явный reply/цитата с медиа; 2) медиа/URL в
самом запросе; 3) уже имеющееся соседнее сообщение того же чата/ветки;
4) короткое ограниченное ожидание медиа после запроса. На шагах 3–4 берётся
**только однозначный** кандидат; два правдоподобных ролика → ``ambiguous``
(случайная подстановка запрещена).

Позднее видео (§4.3): pending-намерение живёт в существующем механизме
короткоживущего pending-состояния (тот же паттерн, что ``_PENDING`` меню
качества в ``handlers/video_download.py``; ΔDDL = 0, новых таблиц/очередей
нет). TTL/окно соседства — общая конфигурация
(``limits.video_intent_*`` → ``settings.VIDEO_INTENT_*``), не скрытые
константы. Истечение TTL → **один** понятный ответ с просьбой прислать видео.
Реестр in-memory: после рестарта старый запрос не привязывается к чужому
ролику и не публикует дубль (привязка «задним числом» исключена by design).

Single-flight (§4.4): ключ идемпотентности ``chat_id + source_ref + операция``;
почти одновременные запросы к тому же ролику дают **один** дорогой анализ,
остальные присоединяются (``joined_existing_job``) без второго ответа и без
повторного списания кулдауна.

R17: наружу/в логи — только ``chat_id``/``message_id``/код причины/хеш ссылки
на источник. Сырые URL, ``file_id``, ключи и тексты сообщений не логируются.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import re
import time
import uuid
from collections import deque

from config.settings import settings
from services import command_prefix
from services import hot_config as hot
from services import native_media
from services.smartmodule_urls import extract_urls, extract_youtube_video_id
from tools.video_downloader import is_direct_media_url, is_platform_url

logger = logging.getLogger(__name__)

# ── Намерения ────────────────────────────────────────────────────────
SUMMARY = "summary"
TRANSCRIPT = "transcript"
DOWNLOAD = "download"
DESCRIBE = "describe"
UNKNOWN = "unknown"

#: Намерения, которые являются ЦЕЛЬЮ АНАЛИЗА (а не просьбой о файле).
ANALYSIS_INTENTS: tuple[str, ...] = (SUMMARY, TRANSCRIPT, DESCRIBE)

# ── Виды источника ───────────────────────────────────────────────────
NATIVE_VIDEO = "native_video"
VIDEO_DOCUMENT = "video_document"
VIDEO_NOTE = "video_note"
URL = "url"
PLATFORM_FORWARD = "platform_forward"
UNRESOLVED = "unresolved"

# ── Разрешение ───────────────────────────────────────────────────────
RESOLVED = "resolved"
WAITING = "waiting"
AMBIGUOUS = "ambiguous"
UNAVAILABLE = "unavailable"

# ── Коды причин (наблюдаемость §4.5) ─────────────────────────────────
REASON_REPLY_MEDIA = "reply_media"
REASON_OWN_MEDIA = "own_media"
REASON_WINDOW_AFTER = "window_after_request"
REASON_WINDOW_BEFORE = "window_before_request"
REASON_PENDING_BOUND = "pending_bound"
REASON_NO_SOURCE = "no_source"
REASON_TWO_SOURCES = "two_competing_sources"
REASON_PENDING_EXPIRED = "pending_expired"
REASON_JOINED = "joined_existing_job"
REASON_OWN_REQUEST = "own_request_covers_pending"

#: Причина «источник только звуковой» (кружок/голосовое) — честный фолбэк:
#: визуального анализа нет, есть только расшифровка.
REASON_AUDIO_ONLY = "audio_only_source"
#: Причина «визуальный анализ недоступен» — выжимка построена по транскрипту.
REASON_TRANSCRIPT_ONLY = "transcript_only_summary"

# ── Классификаторы текста (единственный источник истины для роутинга) ─
# Скачивание — отдельная просьба о файле: триггер в НАЧАЛЕ остатка команды
# (паритет с прежним ``handlers/video_download._TRIGGER_RE``). Единственный
# источник истины — ``services.video_intent`` (EVOL §4.4: один запрос не
# трактуется разными обработчиками как несколько задач).
DOWNLOAD_TRIGGER_RE = re.compile(
    r"^\s*(скачай|скачать|загрузи|стяни)\b", re.IGNORECASE)
_TRANSCRIPT_RE = re.compile(
    r"(транскрипт|расшифров|текст\s+видео|текстом\s+видео)", re.IGNORECASE)
_DESCRIBE_RE = re.compile(
    r"(ч[её]\s+за\s+видос|что\s+за\s+видос|что\s+происходит|что\s+на\s+видео|"
    r"опиши\s+видео|поясни\s+за\s+видос|что\s+в\s+видосе|что\s+в\s+видео)",
    re.IGNORECASE)
_SUMMARY_RE = re.compile(
    r"(выжимк|перескаж|пересказ|краткое\s+содерж|суть|"
    r"о\s*ч[её]м\s+(видео|видос|ролик)|о\s+ч[её]м\s+видос|"
    r"смысл\s+видео)", re.IGNORECASE)
_VIDEO_WORD_RE = re.compile(
    r"(видео|видос|ролик|клип|кружок|видяшк|запись)", re.IGNORECASE)

# ── Наблюдаемость: ограниченное кольцо событий (диагностика/тесты) ───
_EVENTS: deque = deque(maxlen=400)


def emit(event: str, *, correlation_id: str = "", reason_code: str = "",
         chat_id: int | None = None, message_id: int | None = None,
         source_kind: str | None = None, intent: str | None = None,
         source_ref: str | None = None, **extra) -> None:
    """Событие по единому ``correlation_id`` (§4.5).

    R17: сырой источник не логируется — только ``ref_hash`` (8 hex)."""
    record = {
        "event": event,
        "correlation_id": correlation_id,
        "reason_code": reason_code,
        "chat_id": chat_id,
        "message_id": message_id,
        "source_kind": source_kind,
        "intent": intent,
        "ref_hash": ref_hash(source_ref),
        "at": time.time(),
    }
    if extra:
        record.update(extra)
    _EVENTS.append(record)
    logger.info("[video_intent] %s | corr=%s reason=%s chat=%s msg=%s "
                "kind=%s intent=%s ref=%s",
                event, correlation_id or "-", reason_code or "-",
                chat_id, message_id, source_kind or "-", intent or "-",
                record["ref_hash"] or "-")


def emit_for(vintent: "VideoIntent", event: str, reason_code: str = "",
             **extra) -> None:
    """Событие из объекта намерения (короткая форма для обработчиков)."""
    emit(event, correlation_id=vintent.correlation_id, reason_code=reason_code,
         chat_id=vintent.chat_id, message_id=vintent.request_tg_message_id,
         source_kind=vintent.source_kind, intent=vintent.intent,
         source_ref=vintent.source_ref, **extra)


def recent_events(limit: int | None = None) -> list[dict]:
    """Последние события (для диагностики и офлайн-тестов)."""
    items = list(_EVENTS)
    if limit is not None:
        items = items[-limit:]
    return items


def reset() -> None:
    """Полный сброс состояния (тесты/рестарт процесса)."""
    global _WATCHDOG_TASK
    _EVENTS.clear()
    _WINDOW.clear()
    _PENDING.clear()
    _JOBS.clear()
    _WATCHDOG_TASK = None


def ref_hash(source_ref: str | None) -> str:
    """Стабильный короткий хеш ссылки на источник (R17: не логируем сырое)."""
    raw = str(source_ref or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


# ── Конфигурация (общая, не скрытые константы) ───────────────────────
def pending_ttl_seconds() -> float:
    """Окно ожидания медиа после запроса (``limits.video_intent_pending_ttl_seconds``)."""
    try:
        value = float(hot.get("limits.video_intent_pending_ttl_seconds",
                              settings.VIDEO_INTENT_PENDING_TTL_SECONDS) or 0)
    except (TypeError, ValueError):
        value = float(settings.VIDEO_INTENT_PENDING_TTL_SECONDS)
    return max(value, 5.0)


def window_messages() -> int:
    """Сколько последних сообщений чата держим как окно соседства."""
    try:
        value = int(hot.get("limits.video_intent_window_messages",
                            settings.VIDEO_INTENT_WINDOW_MESSAGES) or 0)
    except (TypeError, ValueError):
        value = int(settings.VIDEO_INTENT_WINDOW_MESSAGES)
    return max(value, 1)


def window_max_age_seconds() -> float:
    """Максимальный возраст соседнего медиа в окне."""
    try:
        value = float(hot.get("limits.video_intent_window_max_age_seconds",
                              settings.VIDEO_INTENT_WINDOW_MAX_AGE_SECONDS) or 0)
    except (TypeError, ValueError):
        value = float(settings.VIDEO_INTENT_WINDOW_MAX_AGE_SECONDS)
    return max(value, 10.0)


# ── Классификация намерения ──────────────────────────────────────────
def command_body(text: str) -> str:
    """Остаток сообщения после обязательного префикса («Бот,»/Имя)."""
    tok, rest = command_prefix.split_prefix(text)
    return rest if tok is not None else str(text or "")


def detect_intent(text: str) -> str:
    """Намерение по тексту запроса: summary/transcript/download/describe/unknown.

    Порядок важен: «скачай» — отдельная просьба о файле (не анализ), даже если
    в тексте есть слово «выжимка» (паритет с прежним Fast-Track)."""
    raw = str(text or "").strip()
    if not raw:
        return UNKNOWN
    body = command_body(raw)
    if DOWNLOAD_TRIGGER_RE.match(body):
        return DOWNLOAD
    if _TRANSCRIPT_RE.search(body):
        return TRANSCRIPT
    if _DESCRIBE_RE.search(body):
        return DESCRIBE
    if _SUMMARY_RE.search(body):
        return SUMMARY
    return UNKNOWN


def is_download_request(text: str) -> bool:
    """Явная просьба «скачай/загрузи/стяни» в начале остатка команды."""
    return detect_intent(text) == DOWNLOAD


def mentions_video(text: str) -> bool:
    """В тексте есть слово про видео (гейт «не перехватывать чужую речь»)."""
    return bool(_VIDEO_WORD_RE.search(str(text or "")))


def operation_of(intent: str) -> str:
    """Операция для ключа идемпотентности: describe — это тоже анализ-выжимка."""
    if intent == DESCRIBE:
        return SUMMARY
    if intent in (SUMMARY, TRANSCRIPT, DOWNLOAD):
        return intent
    return UNKNOWN


# ── Кандидаты-источники ──────────────────────────────────────────────
def media_ref(media) -> str:
    """Стабильная ссылка медиа: ``file_unique_id`` → ``file_id`` → ''."""
    for attr in ("file_unique_id", "file_id"):
        value = getattr(media, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def url_ref(url: str) -> str:
    """Нормализованная ссылка на источник: ``yt:<id>`` либо хеш пути."""
    yt_id = extract_youtube_video_id(url)
    if yt_id:
        return f"yt:{yt_id}"
    base = str(url or "").split("#", 1)[0].split("?", 1)[0].strip().lower()
    return "url:" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _video_url(text: str) -> str | None:
    """Первый URL текста, который реально обслуживается видео-ветками."""
    for url in extract_urls(str(text or "")):
        if extract_youtube_video_id(url) is not None:
            return url
        if is_direct_media_url(url) or is_platform_url(url):
            return url
    return None


def _message_text(message) -> str:
    for attr in ("text", "caption"):
        value = getattr(message, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def own_media(message):
    """Нативное медиа САМОГО сообщения (без реплая) либо ``None``."""
    try:
        video = getattr(message, "video", None)
        if video is not None and media_ref(video):
            return native_media.NativeMedia(source=message, media=video,
                                            kind="video")
        document = getattr(message, "document", None)
        if (document is not None and media_ref(document)
                and native_media.document_is_video(document)):
            return native_media.NativeMedia(source=message, media=document,
                                            kind="document")
        for attr in ("voice", "video_note"):
            media = getattr(message, attr, None)
            if media is not None and media_ref(media):
                return native_media.NativeMedia(source=message, media=media,
                                                kind=attr)
    except Exception:                              # pragma: no cover — защита
        logger.debug("[video_intent] own media resolve failed")
    return None


def source_kind_of_media(media, message) -> str:
    """Вид источника для нативного медиа-носителя."""
    kind = getattr(media, "kind", "")
    if kind in ("voice", "video_note"):
        return VIDEO_NOTE
    if kind == "document":
        return VIDEO_DOCUMENT
    if getattr(message, "forward_origin", None) is not None:
        return PLATFORM_FORWARD
    return NATIVE_VIDEO


@dataclasses.dataclass
class MediaCandidate:
    """Соседний/явный источник видео в чате (окно соседства)."""

    chat_id: int
    message_id: int
    user_id: int | None
    source_kind: str
    source_ref: str
    message: object
    media: object | None = None
    url: str | None = None
    thread_id: int | None = None
    observed_at: float = dataclasses.field(default_factory=time.monotonic)


def candidate_of(message) -> MediaCandidate | None:
    """Кандидат-источник из сообщения (медиа или видео-URL) либо ``None``."""
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if not isinstance(chat_id, int):
        return None
    message_id = getattr(message, "message_id", None)
    if not isinstance(message_id, int):
        return None
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        user_id = None
    thread_id = getattr(message, "message_thread_id", None)
    if not isinstance(thread_id, int):
        thread_id = None
    media = own_media(message)
    if media is not None:
        ref = media_ref(getattr(media, "media", None))
        if not ref:
            return None
        return MediaCandidate(
            chat_id=chat_id, message_id=message_id, user_id=user_id,
            source_kind=source_kind_of_media(media, message),
            source_ref=ref, message=message, media=media,
            thread_id=thread_id)
    url = _video_url(_message_text(message))
    if url is not None:
        return MediaCandidate(
            chat_id=chat_id, message_id=message_id, user_id=user_id,
            source_kind=URL, source_ref=url_ref(url), message=message,
            url=url, thread_id=thread_id)
    return None


# ── Окно соседства ───────────────────────────────────────────────────
_WINDOW: dict[int, deque] = {}


def _window(chat_id: int) -> deque:
    ring = _WINDOW.get(chat_id)
    if ring is None:
        ring = deque(maxlen=window_messages())
        _WINDOW[chat_id] = ring
    return ring


def _record(candidate: MediaCandidate) -> None:
    ring = _window(candidate.chat_id)
    for existing in list(ring):
        if existing.message_id == candidate.message_id:
            ring.remove(existing)
    ring.append(candidate)


def window_candidates(chat_id: int, *, now: float | None = None
                      ) -> list[MediaCandidate]:
    """Живые кандидаты окна чата (свежие, в пределах размера окна)."""
    ring = _window(chat_id)
    moment = time.monotonic() if now is None else now
    max_age = window_max_age_seconds()
    alive = [c for c in ring if moment - c.observed_at <= max_age]
    if len(alive) != len(ring):
        _WINDOW[chat_id] = deque(alive, maxlen=window_messages())
    return alive


def _thread_ok(candidate: MediaCandidate, thread_id: int | None) -> bool:
    """Ветка обязана совпадать: медиа другого топика не привязываем."""
    return candidate.thread_id == thread_id


def _pick(candidates: list[MediaCandidate], request_message_id: int | None,
          thread_id: int | None) -> tuple[MediaCandidate | None, str]:
    """Однозначный кандидат из окна либо ``(None, reason)``.

    Правило (§4.2 шаг 3–4): сообщения ПОСЛЕ запроса приоритетнее; внутри
    выбранного набора — только один ``source_ref``. Два разных ролика → не
    выбираем случайный."""
    pool = [c for c in candidates if _thread_ok(c, thread_id)]
    if request_message_id is not None:
        pool = [c for c in pool if c.message_id != request_message_id]
    if not pool:
        return None, REASON_NO_SOURCE
    after: list[MediaCandidate] = []
    before: list[MediaCandidate] = []
    for candidate in pool:
        if request_message_id is not None and candidate.message_id > request_message_id:
            after.append(candidate)
        else:
            before.append(candidate)
    if after:
        refs = {c.source_ref for c in after}
        if len(refs) > 1:
            return None, REASON_TWO_SOURCES
        return min(after, key=lambda c: c.message_id), REASON_WINDOW_AFTER
    refs = {c.source_ref for c in before}
    if len(refs) > 1:
        return None, REASON_TWO_SOURCES
    return max(before, key=lambda c: c.message_id), REASON_WINDOW_BEFORE


# ── Намерение ────────────────────────────────────────────────────────
@dataclasses.dataclass
class VideoIntent:
    """Единое намерение + источник (§4.2). Заполняется ДО media-tool."""

    chat_id: int
    request_tg_message_id: int | None
    request_user_id: int | None
    intent: str
    media_tg_message_id: int | None = None
    media_owner_user_id: int | None = None
    source_kind: str = UNRESOLVED
    source_ref: str | None = None
    resolution: str = UNAVAILABLE
    reason_code: str = ""
    correlation_id: str = ""
    job_id: str | None = None
    url: str | None = None
    media: object | None = None
    media_message: object | None = None
    thread_id: int | None = None

    @property
    def operation(self) -> str:
        return operation_of(self.intent)

    def bind(self, candidate: MediaCandidate, reason_code: str) -> None:
        """Привязать источник-кандидат к намерению."""
        self.media_tg_message_id = candidate.message_id
        self.media_owner_user_id = candidate.user_id
        self.source_kind = candidate.source_kind
        self.source_ref = candidate.source_ref
        self.media = candidate.media
        self.media_message = candidate.message
        self.url = candidate.url
        self.resolution = RESOLVED
        self.reason_code = reason_code
        self.job_id = job_key(self.chat_id, candidate.source_ref,
                              self.operation)


def new_correlation_id(chat_id: int, message_id: int | None) -> str:
    """Короткий correlation_id без приватных данных (R17)."""
    return f"{chat_id}:{message_id or 0}:{uuid.uuid4().hex[:8]}"


def resolve_request(message, intent: str, *, request_user_id: int | None = None,
                    allow_window: bool = True) -> VideoIntent:
    """Разрешить источник запроса по приоритету §4.2 (без ожидания).

    ``waiting`` возвращается для ANALYSIS_INTENTS, когда источника пока нет:
    вызывающий регистрирует pending-намерение (шаг 4 — ограниченное ожидание).
    """
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if not isinstance(chat_id, int):
        chat_id = 0
    message_id = getattr(message, "message_id", None)
    if not isinstance(message_id, int):
        message_id = None
    user = getattr(message, "from_user", None)
    if request_user_id is None:
        raw_user = getattr(user, "id", None)
        request_user_id = raw_user if isinstance(raw_user, int) else None
    thread_id = getattr(message, "message_thread_id", None)
    if not isinstance(thread_id, int):
        thread_id = None
    vintent = VideoIntent(
        chat_id=chat_id, request_tg_message_id=message_id,
        request_user_id=request_user_id, intent=intent,
        correlation_id=new_correlation_id(chat_id, message_id),
        thread_id=thread_id)

    # 1) явный reply/цитата с медиа
    reply = getattr(message, "reply_to_message", None)
    if reply is not None:
        candidate = candidate_of(reply)
        if candidate is not None:
            vintent.bind(candidate, REASON_REPLY_MEDIA)
            return vintent
    # 2) медиа/URL в самом запросе
    own = candidate_of(message)
    if own is not None:
        vintent.bind(own, REASON_OWN_MEDIA)
        return vintent
    # 3) соседнее сообщение того же чата/ветки
    if allow_window:
        picked, reason = _pick(window_candidates(chat_id), message_id, thread_id)
        if picked is not None:
            vintent.bind(picked, reason)
            return vintent
        if reason == REASON_TWO_SOURCES:
            vintent.resolution = AMBIGUOUS
            vintent.reason_code = reason
            return vintent
    # 4) ожидание медиа после запроса
    if intent in ANALYSIS_INTENTS:
        vintent.resolution = WAITING
        vintent.reason_code = REASON_NO_SOURCE
    else:
        vintent.resolution = UNAVAILABLE
        vintent.reason_code = REASON_NO_SOURCE
    return vintent


# ── Pending-намерения (поздний приход видео, §4.3) ───────────────────
@dataclasses.dataclass
class PendingIntent:
    """Ожидающий медиа запрос: живёт до TTL, привязывается один раз."""

    vintent: VideoIntent
    deadline: float
    answered: bool = False
    notify: object | None = None
    created_at: float = dataclasses.field(default_factory=time.monotonic)


_PENDING: dict[int, list[PendingIntent]] = {}

#: Watchdog отправки финального ответа по истёкшему pending (production).
_WATCHDOG_ENABLED = True
_WATCHDOG_TASK: asyncio.Task | None = None


def configure_watchdog(enabled: bool) -> None:
    """Тестовый/сервисный выключатель фонового watchdog-цикла."""
    global _WATCHDOG_ENABLED
    _WATCHDOG_ENABLED = bool(enabled)


def register_pending(vintent: VideoIntent, *, notify=None) -> PendingIntent:
    """Зарегистрировать ожидание медиа (TTL из общей конфигурации)."""
    entry = PendingIntent(vintent=vintent,
                          deadline=time.monotonic() + pending_ttl_seconds(),
                          notify=notify)
    _PENDING.setdefault(vintent.chat_id, []).append(entry)
    emit_for(vintent, "waiting_for_media", REASON_NO_SOURCE)
    _ensure_watchdog()
    return entry


def pending_for(chat_id: int) -> list[PendingIntent]:
    """Живые (не истёкшие, не отвеченные) ожидания чата."""
    return [e for e in _PENDING.get(chat_id, []) if not e.answered]


def has_pending(chat_id: int) -> bool:
    return bool(pending_for(chat_id))


def _drop(entry: PendingIntent) -> None:
    bucket = _PENDING.get(entry.vintent.chat_id) or []
    if entry in bucket:
        bucket.remove(entry)


async def expire(now: float | None = None) -> list[PendingIntent]:
    """Истечь TTL: по каждому ожиданию — РОВНО один ответ (просьба прислать).

    Возвращает истёкшие записи (тесты/диагностика). Повторный вызов ничего не
    дублирует: запись удаляется из реестра до отправки."""
    moment = time.monotonic() if now is None else now
    expired: list[PendingIntent] = []
    for chat_id in list(_PENDING.keys()):
        for entry in list(_PENDING.get(chat_id, [])):
            if entry.answered or entry.deadline > moment:
                continue
            entry.answered = True
            _drop(entry)
            expired.append(entry)
            emit_for(entry.vintent, "failed", REASON_PENDING_EXPIRED)
            notify = entry.notify
            if notify is not None:
                try:
                    await notify(entry)
                except Exception:                  # fail-open: не роняем цикл
                    logger.warning("[video_intent] pending notify failed | "
                                   "chat=%s corr=%s", chat_id,
                                   entry.vintent.correlation_id,
                                   exc_info=True)
    return expired


def _ensure_watchdog() -> None:
    """Ленивый фоновый watchdog (не дублируется, не держит процесс)."""
    global _WATCHDOG_TASK
    if not _WATCHDOG_ENABLED:
        return
    if _WATCHDOG_TASK is not None and not _WATCHDOG_TASK.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _WATCHDOG_TASK = loop.create_task(_watchdog_loop())


async def _watchdog_loop() -> None:
    """Ждать ближайший дедлайн и отправлять ограниченный fallback."""
    while _PENDING:
        deadlines = [e.deadline for bucket in _PENDING.values() for e in bucket
                     if not e.answered]
        if not deadlines:
            break
        delay = min(deadlines) - time.monotonic()
        await asyncio.sleep(max(0.2, min(delay, 5.0)))
        await expire()


# ── Single-flight / идемпотентность (§4.4) ───────────────────────────
_JOB_TTL_SECONDS = 1800.0
_JOBS: dict[str, float] = {}


def job_key(chat_id: int, source_ref: str | None, operation: str,
            version: str = "v1") -> str:
    """Ключ идемпотентности: чат + стабильная ссылка + операция + версия."""
    return f"{chat_id}|{source_ref or '-'}|{operation}|{version}"


def try_begin(key: str) -> bool:
    """``True`` — этот вызов владелец дорогой операции, ``False`` — join."""
    now = time.monotonic()
    for stale in [k for k, started in _JOBS.items()
                  if now - started > _JOB_TTL_SECONDS]:
        _JOBS.pop(stale, None)
    if key in _JOBS:
        return False
    _JOBS[key] = now
    return True


def finish(key: str) -> None:
    """Освободить операцию (идемпотентно)."""
    _JOBS.pop(key, None)


def active_job(chat_id: int) -> str | None:
    """Ключ выполняющейся операции этого чата (для «что за видос» → join)."""
    prefix = f"{chat_id}|"
    for key in list(_JOBS.keys()):
        if key.startswith(prefix):
            return key
    return None


# ── Наблюдение входящих сообщений (окно + привязка ожиданий) ─────────
def observe(message) -> list[PendingIntent]:
    """Записать медиа/ссылку в окно чата и привязать ожидающие запросы.

    Возвращает привязанные pending-намерения (вызывающий решает, запускать
    анализ сам или отдать его обычному пути запроса). Никогда не бросает.
    """
    try:
        candidate = candidate_of(message)
    except Exception:                              # pragma: no cover — защита
        logger.debug("[video_intent] observe candidate failed")
        return []
    if candidate is None:
        return []
    _record(candidate)
    bound: list[PendingIntent] = []
    for entry in pending_for(candidate.chat_id):
        vintent = entry.vintent
        picked, reason = _pick(
            [c for c in window_candidates(candidate.chat_id)],
            vintent.request_tg_message_id, vintent.thread_id)
        if picked is None:
            if reason == REASON_TWO_SOURCES:
                emit_for(vintent, "media_ambiguous", reason)
            continue
        vintent.bind(picked, REASON_PENDING_BOUND)
        entry.answered = True
        _drop(entry)
        bound.append(entry)
        emit_for(vintent, "media_matched", REASON_PENDING_BOUND)
    return bound
