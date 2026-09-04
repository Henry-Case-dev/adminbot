"""Фаза 2 (T-749, B2) — потоковый парсер JSON-экспортов Telegram Desktop.

Файлы pretty-printed, до ~0.45 ГБ — цельный json.load ЗАПРЕЩЁН (серверная RAM
961 МБ): разбор строго через `ijson.items(f, "messages.item")` (по записи,
без загрузки массива). normalize_message(item) — нормализация одной записи в
схему smart_messages (маппинг-таблица spec §3.1):

| поле экспорта      | куда           | правило                                    |
|--------------------|----------------|--------------------------------------------|
| type               | —              | != "message" → отсев (None)                |
| date_unixtime      | timestamp      | int(...); битое → BadTimestampError        |
| from_id            | user_id        | 'user123' → 123; 'channel…'/None → None    |
| from               | author_name    | как есть; отсутствует → ""                 |
| text               | text           | строка; список кусков/объектов → join;     |
|                    |                | пусто/нет → None                           |
| медиа-поля         | media_type     | первое найденное из MEDIA_FIELDS;          |
| (photo/video/…),   |                | явный 'media_type' экспорта — как есть;    |
| реже 'file'        |                | иначе 'text'                               |
| reply_to_message_id| reply_to_id    | информационно (экспортные id отрицательны) |
| forwarded_from/    | is_forward /   | 1 + источник как есть (без префикса)       |
| forward_from       | forward_source |                                            |
| —                  | import_key     | sha256(f"{ts}|{user_id}|{text}")[:32]      |
| —                  | tg_message_id  | НЕ пишется (id отрицательны/коллизятся)    |

Отсев записи целиком: type != 'message'; текст пуст И медиа нет. Медиа без
подписи сохраняется (text None; в FTS строка не пишется — условие «text IS
NOT NULL AND text != ''», прецедент save_smart_message).

ОТКЛОНЕНИЕ от базовой формулы import_key (обоснование): для сообщений без
текста (медиа без подписи) ключ sha256(ts|uid|text) одинаков для РАЗНЫХ
сообщений одного юзера в одну секунду → вторая запись терялась бы дедупом.
Для text=None в ключ включается экспортный id сообщения (он стабилен для
одного и того же сообщения между экспортами того же чата — дедуп пересечения
переживает): f"{ts}|{user_id}|<media:{media_type}:{id}>".
"""
import hashlib
import ijson

# Первое найденное поле — media_type (порядок по убыванию важности, spec §3.1).
MEDIA_FIELDS: tuple[str, ...] = (
    "photo", "video", "animation", "voice", "video_note", "document",
    "sticker", "contact", "poll", "game", "location",
)

# tg_message_id намеренно НЕ пишется (экспортные id отрицательны и коллизятся
# между экспортами) — дедуп только по import_key (spec §3.1/edge 2).
TG_MESSAGE_ID_SENTINEL = None


class BadTimestampError(ValueError):
    """Битый/отсутствующий date_unixtime — запись в счётчик ошибок, пропуск."""


def _text_of(raw) -> str | None:
    """text: строка как есть; список кусков (str или {'text': …}) → join;
    отсутствует/пусто → None (спецификация §3.1)."""
    text = raw.get("text")
    if text is None:
        return None
    if isinstance(text, str):
        return text if text.strip() else None
    if isinstance(text, list):
        parts: list[str] = []
        for piece in text:
            if isinstance(piece, str):
                parts.append(piece)
            elif isinstance(piece, dict):
                inner = piece.get("text")
                if isinstance(inner, str):
                    parts.append(inner)
        joined = "".join(parts)
        return joined if joined.strip() else None
    return None


def _user_id_of(from_id) -> int | None:
    """'user123' → 123; 'channel…'/'chat…'/прочие/None → None (сообщения
    каналов-постингов — не юзеры памяти)."""
    if from_id is None:
        return None
    if isinstance(from_id, bool):
        return None
    if isinstance(from_id, int):
        return from_id
    value = str(from_id)
    if value.startswith("user"):
        digits = value[len("user"):]
        return int(digits) if digits.isdigit() else None
    if value.isdigit():
        return int(value)
    return None


def _detect_media_type(raw) -> str:
    """media_type записи: явное поле экспорта (наблюдалось 'animation' рядом
    с 'file') — как есть; иначе первое найденное медиа-поле; без медиа —
    'text' (сообщение с текстом)."""
    explicit = raw.get("media_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for field in MEDIA_FIELDS:
        if field in raw and raw.get(field) is not None:
            return field
    return "text"


def _forward_info(raw) -> tuple[int, str]:
    """is_forward/forward_source из forwarded_from/forward_from (текст
    источника как есть; dict-форма — имя/юзернейм; префикс не добавляем)."""
    source = raw.get("forwarded_from")
    if source is None:
        source = raw.get("forward_from")
    if source is None:
        return 0, ""
    if isinstance(source, dict):
        source = source.get("name") or source.get("username") or ""
    if not isinstance(source, str):
        source = str(source) if source is not None else ""
    return (1, source) if source else (0, "")


def _import_key_of(timestamp: int, user_id, text: str | None,
                   media_type: str, export_id) -> str:
    """Дедуп-ключ (FR-2): sha256 hex-префикс 32. Для text=None (медиа без
    подписи) в ключ входит export id — иначе разные медиа одного юзера в одну
    секунду схлопнулись бы дедупом (см. docstring модуля)."""
    if text is not None:
        material = f"{timestamp}|{user_id}|{text}"
    else:
        material = f"{timestamp}|{user_id}|<media:{media_type}:{export_id}>"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def normalize_message(raw) -> dict | None:
    """Нормализация одной записи экспорта → dict для INSERT в smart_messages.

    Возвращает None при отсеве: type != 'message' (служебные); текст пуст и
    медиа нет. Бросает BadTimestampError при битом date_unixtime (счётчик
    ошибок + пропуск, импорт не роняется)."""
    if not isinstance(raw, dict):
        raise BadTimestampError("record is not an object")
    if raw.get("type") != "message":
        return None
    raw_ts = raw.get("date_unixtime")
    try:
        timestamp = int(raw_ts)
    except (TypeError, ValueError):
        raise BadTimestampError(f"bad date_unixtime: {raw_ts!r}")
    text = _text_of(raw)
    media_type = _detect_media_type(raw)
    if text is None and media_type == "text":
        return None                      # пусто и без медиа — отсев
    user_id = _user_id_of(raw.get("from_id"))
    author = raw.get("from")
    author_name = author if isinstance(author, str) else ""
    is_forward, forward_source = _forward_info(raw)
    reply_to = raw.get("reply_to_message_id")
    reply_to_id = int(reply_to) if isinstance(reply_to, (int, float)) \
        and not isinstance(reply_to, bool) else None
    export_id = raw.get("id")
    return {
        "user_id": user_id,
        "text": text,
        "reply_to_id": reply_to_id,
        "timestamp": timestamp,
        "media_type": media_type,
        "author_name": author_name,
        "is_forward": is_forward,
        "forward_source": forward_source,
        "import_key": _import_key_of(timestamp, user_id, text, media_type,
                                     export_id),
    }


def parse_items(file_obj):
    """Потоковый итератор записей экспорта из ОТКРЫТОГО файла (dict
    «messages.item»; loader оборачивает файл счётчиком байт для ETA).
    Структурная ошибка файла (не JSON/обрыв) — ijson-исключение наружу:
    стоп по файлу (повторный `--resume` безопасен, spec §3.3)."""
    yield from ijson.items(file_obj, "messages.item", use_float=True)


def iter_messages(path):
    """Потоковый итератор записей экспорта по пути (удобный враппер)."""
    with open(path, "rb") as fh:
        yield from parse_items(fh)


def detect_export_id(path) -> int | None:
    """id чата из шапки экспорта (top-level 'id'; для --only-live-chat).
    Читает только начало файла — сообщения не сканируются (break на
    'messages'). None — не прочиталось (считаем не-live)."""
    with open(path, "rb") as fh:
        for prefix, event, value in ijson.parse(fh):
            if prefix == "messages":
                return None
            if prefix == "id" and event in ("number", "string"):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
    return None
