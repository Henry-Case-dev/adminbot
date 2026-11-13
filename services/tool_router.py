"""Эпик 04.09.2026 (3.3, Часть 2) — исполнение инструментов Tool Calling.

Фиксированный реестр имён (dispatch по таблице, БЕЗ исполнения произвольного
кода); аргументы валидируются (кривой JSON/тип → текст ошибки); результаты
режутся (4000/3500 симв.); параллельного исполнения НЕТ (последовательно, по
одному tool_call за раунд — бюджет в tool_loop).

dispatch ВСЕГДА возвращает строку результата (в т.ч. 'ОШИБКА …') — НЕ бросает
(FR-14: результат ошибки уходит модели как role:"tool").

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): ветка _dig_into_lore — глубокое
копание в историю чата (датированные сниппеты L1 по FTS5 + факты графа);
флаг flags.dig_enabled (default true; hot-фолбек settings.DIG_ENABLED); год →
диапазон по timestamp (в т.ч. «N лет назад» из query); person → user_id-
фильтр (если алиас) + OR-токены имён + расширение именами из граф-обхода
(nodes/edges, глубина limits.dig_graph_hop_depth; фолбэк target_user);
лимиты — hot-ключи группы limits_memory с фолбэком settings (REGISTRY
фикс-раунда, spec §3.6.4). НЕ бросает: ошибка этапа → WARNING + секция пуста.

Раунд 10.15 (F8, ADR-1015-3, T-1612…T-1615): +4 инструмента tool-сета —
summarize_video (делегирование YoutubeSummarizerService), download_media
(корнер-кейс: бэкенд сам шлёт MP4, в LLM — фиктивный tool_response),
get_bot_health (CheckupLogsFetcher+CheckupService) и get_recent_history
(полная реализация — F9, см. ниже). ToolDeps/ToolContext расширены аддитивно
(обратная совместимость: старые вызовы без новых kwargs работают).

Раунд 10.15 (F9, spec §2-§6, T-1620…T-1623): `_get_recent_history` реализован
полностью — сырая хронологическая стенограмма недавних сообщений чата
(«Имя: текст»): путь `depth` (без верхнего предела — P0-HA §3.1) через
`database.get_recent_messages` либо путь `query` (FTS + окно последних часов +
ASC). Лимиты — код-константы (каталог-Δ=0); R17: логи только chat_id/fetched/
count/out_chars.

Раунд 10.17 (F2, ADR-1017-2 — SUPERSEDE ADR-1016-1 §2 п.3/§3): tool
`download_media` для платформенного URL делает `probe()` → инлайн-меню
качества `tdq:<height>` → фиктивный `tool_response {"status":"needs_quality"}`
(скачивание доводит callback `tdq:` в роутере 4e); прямой медиа-URL или явно
названное `quality` — сразу `download(url, quality)`; провал probe — одна
bounded попытка `download(url, None)`. Кулдаун (D279) — только после успеха.

Раунд 10.20 (БЛОК 1/О3, ADR-1020-4 п.1-4, T-1887): 8-й тул
`compile_lore_story(topic)` — «Летописец». Dispatch делегирует в
изолированный `LoreCompilerService` (Шаг А граф + Шаг Б хронология → свой
канон `LORE_STORY_SYSTEM_PROMPT` → готовый рассказ), ставит
`ToolContext.lore_compiled = True` (сигнал доставки HTML — ADR-1020-6);
гейт `flags.lore_compiler_enabled` (default ON). Ошибки → «ОШИБКА …».

Раунд 10.24 (F19, ADR-1024-20 §2.2): `transcribe_video` — СЫРАЯ
транскрибация (дословный текст, без пересказа), отдельно от `summarize_video`.
Источник link/native (voice/video_note включительно); YouTube → субтитры raw,
иначе download→STT; native → fetch→STT. Возвращает строку (усечённую
`_MEMORY_MAX_SYMBOLS`), никогда не бросает. Egress не расширяется.
"""
import asyncio
import base64
import datetime
import dataclasses
import hashlib
import hmac
import json
import logging
import re
import secrets
import time

from config.settings import settings
from services import hot_config as hot
from services import image_context_memory
from services import image_generation
from services import mca_gates
from services import mca_events as _mca_events
from services import media_share
from services import native_media
from services.canonical_context import (
    SpeechProjection,
    format_context_item,
    format_speech_item,
    resolve_item_id,
    speech_projection_enabled,
)
from services.media_send import send_media, send_quality_menu
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
)
from services.search_aggregator import (
    PUBLISHED_LABEL as _SEARCH_PUBLISHED_LABEL,
    AllSearchEnginesFailedException,
    normalise_publication_date,
)
from services.smartmodule_urls import extract_urls, extract_youtube_video_id
from services import auto_budget
from services import source_reuse
from services import tool_result as _tool_result
from services.tool_schemas import _memory_lookup_enabled
from services.web_content_extractor import (
    WebContentExtractionFailedException,
    build_source_pointer,
    clip_at_boundary,
    content_terms,
    select_excerpt,
)
from tools.video_downloader import DownloadError, is_direct_media_url

logger = logging.getLogger(__name__)

# Лимиты результатов инструментов (3.3): символы.
#
# ASAP-EVIDENCE-ROUTING-01 v3 (§3 Retrieve, limits-audit.md №1–3): 4000/8000
# больше НЕ «потолок качества» — это legacy-дефолт вызовов БЕЗ бюджета и
# нижний пол поиска. Фактический лимит приходит per-call из
# `auto_budget.resolve_evidence_tool_window` (реальное окно модели / бюджет
# композера), см. `_evidence_window`.
_SEARCH_MAX_SYMBOLS = auto_budget.LEGACY_SEARCH_MAX_SYMBOLS   # legacy-пол
_MEMORY_MAX_SYMBOLS = 3500
_MEMORY_FTS_LIMIT = 40
_MEMORY_VEC_LIMIT = 15
# Бюджет одного инструмента веб-поиска (сумма таймаутов каскада + запас).
_SEARCH_TOOL_TIMEOUT = 25.0

# Раунд 10.15 (F8, ADR-1015-3 §8): таймауты новых инструментов — код-константы
# (новых каталог-ключей нет). download_media — в пределах NFR-4 скачивания;
# summarize_video — страховка поверх внутреннего бюджета сервиса.
_DOWNLOAD_TOOL_TIMEOUT = 180.0
_SUMMARIZE_TOOL_TIMEOUT = 300.0
# Раунд 10.20 (БЛОК 1, ADR-1020-4 п.3, T-1887): «Летописец» делает ВТОРОЙ
# LLM-вызов (синтез) — страховочный wait_for поверх него (как summarize_video).
_LORE_TOOL_TIMEOUT = 300.0
# Служебная инструкция tool-response: детерминизм доставки — в ctx
# (`lore_compiled`), но модель просим вернуть story дословно (мягкая страховка).
_LORE_RETURN_INSTRUCTION = (
    "[СИСТЕМНАЯ ИНСТРУКЦИЯ: верни пользователю текст из поля \"story\" "
    "ДОСЛОВНО, без сокращений, без пересказа и без собственных добавлений.]")
# Cap транскрипта для mode=transcript (прецедент handlers/youtube T-690).
_SUMMARIZE_TRANSCRIPT_CAP = 20000

# Раунд 10.24 (F14, ADR-1024-15 §2.3/§2.5): нативный источник инструментов
# (summarize_video/download_media) — только video/видео-document; bytes берём
# из разрешённого aiogram-объекта `ToolContext.native_media` (не из текста
# модели). STT-таймаут — паритет с youtube (`limits.video_stt_timeout_seconds`);
# download-кулдаун на нативную пересылку НЕ жжётся (копирование TG-файла,
# паритет Fast-Track). Kill-switch `NATIVE_MEDIA_TOOLS_ENABLED` гейтит нативный
# резолв (OFF → прежние ошибки, native fetch/STT не запускаются).
# F19 (ADR-1024-20 §2.5): наборы kind-ов — единый источник `services.native_media`
# (`VIDEO_KINDS` для summarize/download; `MEDIA_KINDS` — включая voice/video_note
# для `transcribe_video`), без дублирующих локальных констант.
_DOWNLOAD_NATIVE_MAX_BYTES = 2_000_000_000

# Раунд 10.26 (A2, ADR-1026-15 D5): инструмент `fetch_article` — извлечение
# статьи по URL в Markdown+метаданные через reuse `WebContentExtractor.extract`
# (каскад trafilatura 10 c / Tavily 15 c / Exa 15 c + запас). Код-константы
# (Δ каталога = 0).
_ARTICLE_TOOL_TIMEOUT = 45.0
# ASAP-EVIDENCE-ROUTING-01 v3: 8000 — legacy-дефолт (динамика OFF) и нижний
# пол; фактический лимит доставки — `auto_budget.resolve_evidence_tool_window`
# (окно модели / бюджет композера), извлечение — `article_extract_ceiling`.
_ARTICLE_MAX_SYMBOLS = auto_budget.LEGACY_ARTICLE_MAX_SYMBOLS

# COR-01 (p0-nostalgia corrective §COR-01): исходник edit сохраняется во
# временный файл с расширением по СНИФФЕР-формату (mca_vision.DownloadedImage
# .mime), а не «всё в .png» — иначе MIME edit-запроса врал (JPEG/WebP-исходник
# объявлялся image/png). Неизвестный mime → консервативный прежний .png.
_EDIT_SOURCE_SUFFIX_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# ── A6 (раунд 10.26, ADR-1026-18 D3/D4/D5): structured memory lookup
# `get_user_context`. Капы — код-константы (Δ каталога = 0); инструмент
# read-only и free/local (не в METERED_TOOLS). R17: в логи — только
# purpose/user_id/chat_id/count/latency/empty_reason.
_MEMORY_LOOKUP_MAX_ITEMS_HARD = 20          # hard-ceiling max_items (D5)
_MEMORY_LOOKUP_MESSAGE_SLICE_MAX = 5        # срез сообщений (hard 10)
_MEMORY_LOOKUP_MESSAGE_SLICE_HARD = 10
_MEMORY_LOOKUP_SLICE_MAX_CHARS = 240        # символов на фрагмент сообщения
_MEMORY_LOOKUP_RESULT_MAX_CHARS = 4000      # общий бюджет результата
_MEMORY_LOOKUP_CONFIRMED_WEIGHT = 0.5       # graph_facts.weight → confirmed/likely
_MEMORY_LOOKUP_APPEARANCE_SCAN = 200        # bounded-пул под лексиконный фильтр
_MEMORY_LOOKUP_STYLE_SCAN = 120             # bounded-пул recent-сообщений
#: Минимум характерных сообщений (D3). Теперь это лишь порог «тонкого»
#: среза: сам срез читает канал `recent` единого retrieval (§7.5).
_MEMORY_LOOKUP_STYLE_MIN_MESSAGES = 2
_MEMORY_LOOKUP_PORTRAIT_MAX_CHARS = 600     # портрет/профиль (производные)
_MEMORY_LOOKUP_RAG_FACT_CHARS = 240         # фрагмент RAG-факта
# Per-purpose дефолты max_items (D5, spec §3.5).
_MEMORY_LOOKUP_PURPOSE_DEFAULTS = {
    "identity": 5,
    "appearance": 10,
    "speech_style": 5,
    "biography": 10,
    "relationships": 10,
    "general": 8,
}
_MEMORY_LOOKUP_PURPOSES = tuple(_MEMORY_LOOKUP_PURPOSE_DEFAULTS)
# MEMORY-06 (§7.5, фикс регрессии ре-ревью): профильные назначения читают
# ФАКТЫ О СУБЪЕКТЕ — канал `subject` единого retrieval отбирает их по
# существующим колонкам субъекта (`subject_ref_id` по uid / legacy
# `target_user`), а не по совпадению текста с запросом. FTS-каналы
# (exact/lexical) для этого не годятся: факт «любит дронов» о человеке не
# содержит его имени, а `exact` требует кавычек в запросе, поэтому не
# компенсировал потерю. «Ленивый» vector-канал здесь не читается (прежняя
# семантика D3); срез собственной речи — канал `recent` (scope=participants).
_MEMORY_LOOKUP_SUBJECT_CHANNELS = ("subject",)
# Лексикон внешности — generic-фильтр поверх graph_facts (A6). Извлечение/
# классификация внешности (в т.ч. из изображений) — граница A4 (U1).
_APPEARANCE_LEXICON = (
    "внешн", "выгляд", "причёс", "причес", "волос", "бород", "усы", "очк",
    "одет", "одежд", "носит", "высок", "низк", "худ", "полн", "толст",
    "стройн", "глаз", "улыб", "тату", "шрам", "рост", "лицо", "шляп", "кепк",
    "куртк", "костюм", "кроссовк", "пальто", "стриж", "бров", "родинк",
    "веснушк", "седин", "лыс", "модн",
)

# Раунд 10.17 (F2, ADR-1017-2 §2.1/§2.6): tool-скачивание спрашивает качество
# (probe → инлайн-меню `tdq:<height>` → callback доводит download). Таймаут
# probe в tool-пути — с запасом над внутренним `_PROBE_TIMEOUT_SECONDS=20`;
# pending-состояние — in-memory с TTL (как Fast-Track `_PENDING`). Код-константы
# (каталог-Δ=0).
_PROBE_TOOL_TIMEOUT = 25.0
_TOOL_DL_PENDING_TTL_SECONDS = 600
_TOOL_QUALITY_PREFIX = "tdq:"             # callback меню качества tool-пути

# Раунд 10.15 (F9, spec §6): лимиты get_recent_history — код-константы
# (каталог-Δ=0; прецедент _DIG_GRAPH_MAX_HOP_DEPTH/_MEMORY_FTS_LIMIT).
# P0-HA (снапшот 2026-10-29, §3.1): _HISTORY_MAX_DEPTH=150 удалён как общий
# потолок — depth передаётся в БД-выборку без уменьшения; дефолт 50 — НЕ
# максимум. Физический размер одного чтения БД ограничивает только
# database._RECENT_MESSAGES_PAGE_SIZE (страница); число страниц определяется
# фактическим размером выборки, нового общего потолка нет.
# P0-HA TRUNC-PAGES (§4 директивы + архконтракт §1): символьная обрезка
# результата истории (константа 3500 + вызов усечки) УДАЛЕНА полностью —
# символьное ограничение как способ определения доступной истории исчезло
# (не заменено ни 5000, ни 100000). Если выборка помещается в страницу
# целиком — возвращается целиком; иначе — структурированные страницы целых
# сообщений с честными счётителями и подписанным cursor (§4.2).
_HISTORY_DEFAULT_DEPTH = 50              # default при отсутствии параметров
_HISTORY_SEARCH_LIMIT = 80               # FTS-строк на этапе query (до фильтра)
_HISTORY_QUERY_WINDOW_SECONDS = 12 * 3600  # «последние часы» для query
_HISTORY_TOOL_TIMEOUT = 10.0             # страховочный wait_for (локальная SQLite)
# Технический предел ОДНОГО возврата инструмента — в целых сообщениях
# (архконтракт §1 «Размер страницы»). НЕ потолок выборки: совпадает с уже
# существующим техническим батчем эпизода (episode_max_messages, дефолт 40).
_HISTORY_PAGE_ROWS = 40
# Честная фраза при пустом результате: модель не выдумывает (spec §3).
_HISTORY_EMPTY = "За последние сообщения ничего не нашлось"

# ── TRUNC-PAGES: структурированное продолжение выборки (архконтракт §1) ──
# Стабильная машина-читаемая голова результата + хвостовой сентинел (не
# заканчивается на «…», чтобы tool_result не помечал конверт truncated).
_HISTORY_SAMPLE_HEADER = "@@HISTORY_SAMPLE v1"
_HISTORY_HEADER_END = "@@END_HEADER"
_HISTORY_SAMPLE_END = "@@HISTORY_SAMPLE_END"
# Ключ подписи cursor: secrets на импорте модуля (архконтракт §1 Cursor —
# рестарт процесса инвалидирует подпись → честная ошибка, не новая выборка).
_HISTORY_CURSOR_KEY = secrets.token_bytes(32)
# Коды отказа cursor (fail closed: путь B и дефолт 50 запрещены).
_HISTORY_CURSOR_ERRORS = ("unknown_cursor", "stale_cursor", "anchor_missing")


class _HistoryCursorError(Exception):
    """Структурированный отказ cursor (не подменяется новой выборкой)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = str(reason)

# Окна query_chat_memory (3.3): time_range → секунды (0 = всё время).
_TIME_RANGE_SECONDS = {
    "last_day": 24 * 3600,
    "last_week": 7 * 24 * 3600,
    "last_month": 30 * 24 * 3600,
    "all": 0,
}

# Bugfix 04.09.2026 (Часть 2, 3.3(г)): человечные лейблы окна для заголовка
# счётчика query_chat_memory.
_TIME_RANGE_LABELS = {
    "last_day": "за сутки",
    "last_week": "за неделю",
    "last_month": "за месяц",
    "all": "за всё время",
}

# ── P0-DELTA (26.10.2026, дефекты 2/4 аудита p0-delta-analysis) ─────────
# «Мои сообщения» = uid говорящего (ctx.user_id); значение author/person
# «123»/«id:123»/«user:123» — явный Telegram uid. Похожие ники НЕ сливаются.
_ME_ALIASES = frozenset({"me", "self", "myself", "я", "себя", "мои"})
_UID_RE = re.compile(r"^(?:id:|user:)?(\d{3,})$")

# Происхождение фактов dig (дефект 5/provenance): пересказ/вывод не выдаются
# за независимые свидетельства и за дословные сообщения (kind="msg"
# сниппеты — прямые цитаты корпуса). Неизвестный origin — сам origin.
_DIG_FACT_ORIGIN_LABELS = {
    "chat_history": "[пересказ из чата]",
    "derived_belief": "[вывод бота]",
    "user_memory": "[запомнено]",
    "history_import": "[импорт истории]",
    "search_fact": "[из поиска]",
    "web_content": "[из статьи]",
    "youtube_content": "[из видео]",
    "video_transcript": "[из видео]",
    "voice_transcript": "[из голосового]",
    "bot_self_reply": "[прошлые слова бота]",
    "bot_direct_reply": "[прошлые слова бота]",
}

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

# Валидация ссылок инструментов (F8): только http(s)-URL.
_HTTP_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _is_http_url(url: str) -> bool:
    """True — строка похожа на http(s)-ссылку (иначе инструмент → ОШИБКА)."""
    return bool(_HTTP_URL_RE.match(str(url or "").strip()))


def _path_ext(path) -> str:
    """Расширение tmp-файла для STT (без точки); пусто/нет суффикса → ``mp4``."""
    try:
        suffix = str(getattr(path, "suffix", "") or "").lstrip(".")
    except Exception:
        suffix = ""
    return suffix or "mp4"


def _native_tools_enabled() -> bool:
    """env-only kill-switch ``NATIVE_MEDIA_TOOLS_ENABLED`` (default ON).

    Единая точка чтения флага для нативного резолва инструментов
    (F14 §9/ADR-1024-15 §2.5). OFF → нативные вызовы без ``url`` не
    исполняются (прежние строки ошибок, native fetch/STT не запускаются)."""
    return bool(getattr(settings, "NATIVE_MEDIA_TOOLS_ENABLED", True))


def _download_status(status: str, message: str) -> str:
    """Фиктивный tool_response для download_media (ADR-1015-3 §4): LLM видит
    JSON, а реальный MP4 уходит в чат на бэкенде (модель не «печатает» файл).
    Статусы: success | needs_quality (меню отправлено) | error (ADR-1017-2 §3.2)."""
    return json.dumps({"status": status, "message": message},
                      ensure_ascii=False)


# Раунд 10.17 (F2, ADR-1017-2 §2.6): pending выбора качества tool-скачивания.
# Key `(chat_id, user_id)`; TTL `_TOOL_DL_PENDING_TTL_SECONDS`; ленивая чистка
# при каждом обращении. In-memory (без PG/DDL) — по ADR.
_TOOL_DL_PENDING: dict[tuple[int, int], dict] = {}


def _purge_stale_pending(now: float) -> None:
    """Ленивая чистка протухших записей pending (без отдельного таймера)."""
    for key in [k for k, v in _TOOL_DL_PENDING.items()
                if v.get("expires", 0) <= now]:
        _TOOL_DL_PENDING.pop(key, None)


def store_tool_download_pending(chat_id: int, user_id, *, url: str,
                                title, qualities, trigger_message_id) -> None:
    """Сохранить выбор качества для callback `tdq:` (producer — tool)."""
    now = time.monotonic()
    _purge_stale_pending(now)
    _TOOL_DL_PENDING[(chat_id, user_id)] = {
        "url": url,
        "title": title,
        "qualities": tuple(qualities or ()),
        "trigger_message_id": trigger_message_id,
        "expires": now + _TOOL_DL_PENDING_TTL_SECONDS,
    }


def pop_tool_download_pending(chat_id: int, user_id) -> dict | None:
    """Забрать pending (одноразово). Нет/протух → None (callback «протухла»)."""
    now = time.monotonic()
    _purge_stale_pending(now)
    entry = _TOOL_DL_PENDING.pop((chat_id, user_id), None)
    if entry is None or entry.get("expires", 0) <= now:
        return None
    return entry


def peek_tool_download_pending(chat_id: int, user_id) -> dict | None:
    """Pending БЕЗ изъятия — валидация callback до consume (ревью-итер.1 L1).

    Позволяет отвергнуть подделанную/несуществующую высоту, не теряя pending
    и не снимая рабочую клавиатуру. Нет/протух → None.
    """
    now = time.monotonic()
    _purge_stale_pending(now)
    entry = _TOOL_DL_PENDING.get((chat_id, user_id))
    if entry is None or entry.get("expires", 0) <= now:
        return None
    return entry


def keywords(query: str) -> list[str]:
    """Токены запроса для FTS-поиска (L2-путь query_chat_memory)."""
    return _TOKEN_RE.findall(str(query or "").lower())


def _time_range_since(time_range: str) -> int:
    """Секунды с эпохи для окна (0 = без фильтра по времени)."""
    seconds = _TIME_RANGE_SECONDS.get((time_range or "all").strip().lower(), 0)
    return 0 if not seconds else int(time.time()) - seconds


def _history_depth(raw) -> int:
    """depth get_recent_history → int ≥ 1.

    Отсутствие/кривой тип → _HISTORY_DEFAULT_DEPTH; 0/отрицательное → 1.
    P0-HA (снапшот 2026-10-29, §3.1): верхнего предела больше нет —
    запрошенное число (200/400/2000/…) идёт в выборку как есть, без
    уменьшения до фиксированного числа; дефолт 50 — НЕ максимум."""
    if raw is None or raw == "":
        return _HISTORY_DEFAULT_DEPTH
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _HISTORY_DEFAULT_DEPTH
    return max(1, value)


# ── TRUNC-PAGES: фиксация границы выборки, cursor, экстрактор N ──────────


def _history_sample_id(chat_id: int, anchor_ts: int, anchor_id: int,
                       requested: int) -> str:
    """Стабильный id выборки (архконтракт §0): ``hs_`` + 12 hex от sha256
    (chat_id|anchor_ts|anchor_id|requested). Не UUID: та же граница — тот же
    id."""
    digest = hashlib.sha256(
        f"{int(chat_id)}|{int(anchor_ts)}|{int(anchor_id)}|{int(requested)}"
        .encode("utf-8")).hexdigest()
    return f"hs_{digest[:12]}"


def _history_cursor_ttl() -> float:
    """Срок жизни cursor — существующая техническая константа цепочки.

    SMART-EXECUTION-RELIABILITY-01 (owner 2026-11-14 §B1): 360 c больше НЕ
    продуктовый дедлайн исследования; для cursor это просто срок жизни
    подписанного состояния (тот же, что у `diagnostic_collector`). Новый TTL
    не вводится (архконтракт §1 Cursor), значение не изменилось."""
    from services.diagnostic_collector import _CURSOR_TTL_SECONDS
    try:
        value = float(getattr(settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 0)
                      or 0)
    except (TypeError, ValueError):
        return _CURSOR_TTL_SECONDS
    return value if value > 0 else _CURSOR_TTL_SECONDS


def _history_cursor_encode(bound: dict, after_ts: int, after_id: int,
                           processed: int = 0) -> str:
    """Подписанный самодостаточный cursor (архконтракт §1, формат v2).

    Payload (ASCII, без текста сообщений), base64url без padding:
    ``v2|chat_id|anchor_ts|anchor_id|oldest_ts|oldest_id|requested|
    available|processed|after_ts|after_id|exp|sample_id``; подпись — первые
    16 hex hmac.sha256(process_key, payload). ``available``/``processed`` —
    захваченные счётчики выборки (ревью H14, 2026-10-29): продолжение
    сверяет обещанный остаток (available - processed) с живой БД и честно
    рапортует удалённые строки, а не молча ужмёт available до выжившего
    COUNT. Формат v2 принят fail-closed: payload прежней сборки без этих
    полей не разбирается вовсе (unknown_cursor); TTL 360 с делает
    совместимость с v1 бессмысленной. Тела страниц в состоянии НЕ хранятся:
    следующая страница перечитывается из БД тем же предикатом."""
    payload = "|".join(str(v) for v in (
        "v2", int(bound["chat_id"]), int(bound["anchor_ts"]),
        int(bound["anchor_id"]), int(bound["oldest_ts"]),
        int(bound["oldest_id"]), int(bound["requested"]),
        int(bound["available"]), max(0, int(processed)),
        int(after_ts), int(after_id),
        int(bound.get("exp") or (time.time() + _history_cursor_ttl())),
        str(bound.get("sample_id") or ""),
    ))
    token = base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")
    sig = hmac.new(_HISTORY_CURSOR_KEY, payload.encode("ascii"),
                   hashlib.sha256).hexdigest()[:16]
    return f"v2.{token}.{sig}"


def _history_cursor_decode(cursor: str, chat_id: int) -> tuple[dict | None, str]:
    """Разбор + проверка cursor. (None, reason) при отказе — fail closed:
    путь B и дефолт 50 запрещены (архконтракт §1). Чужой chat_id и битая
    подпись неотличимы для caller'а — оба ``unknown_cursor``. Только формат
    v2 (с захваченными available/processed): payload старой сборки (v1,
    без счётчиков выборки) → ``unknown_cursor`` — молчаливое чтение по
    уменьшенному окну запрещено (ревью H14)."""
    parts = str(cursor or "").strip().split(".")
    if len(parts) != 3 or parts[0] != "v2" or not parts[1] or not parts[2]:
        return None, "unknown_cursor"
    try:
        pad = "=" * (-len(parts[1]) % 4)
        payload = base64.urlsafe_b64decode(parts[1] + pad).decode("ascii")
    except Exception:
        return None, "unknown_cursor"
    expected = hmac.new(_HISTORY_CURSOR_KEY, payload.encode("ascii"),
                        hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected, parts[2]):
        return None, "unknown_cursor"
    fields = payload.split("|")
    if len(fields) != 13 or fields[0] != "v2":
        return None, "unknown_cursor"
    try:
        cur_chat = int(fields[1])
        anchor_ts, anchor_id = int(fields[2]), int(fields[3])
        oldest_ts, oldest_id = int(fields[4]), int(fields[5])
        requested = int(fields[6])
        available, processed = int(fields[7]), int(fields[8])
        after_ts, after_id = int(fields[9]), int(fields[10])
        exp = int(fields[11])
    except (TypeError, ValueError):
        return None, "unknown_cursor"
    sample_id = fields[12]
    if not sample_id.startswith("hs_") or len(sample_id) != 15:
        return None, "unknown_cursor"
    # Счётчики выборки обязательны и согласованы; кривые значения — отказ,
    # не «лучшая догадка» (fail closed).
    if available < 1 or processed < 0 or processed > available:
        return None, "unknown_cursor"
    if cur_chat != int(chat_id):
        return None, "unknown_cursor"
    if exp < int(time.time()):
        return None, "stale_cursor"
    return {
        "chat_id": cur_chat, "anchor_ts": anchor_ts, "anchor_id": anchor_id,
        "oldest_ts": oldest_ts, "oldest_id": oldest_id,
        "requested": requested, "available": available,
        "processed": processed, "after_ts": after_ts, "after_id": after_id,
        "exp": exp, "sample_id": sample_id,
    }, ""


def _history_window(bound: dict) -> tuple[int, int, int, int]:
    """Окно выборки (anchor_ts, anchor_id, oldest_ts, oldest_id) из bound."""
    return (int(bound["anchor_ts"]), int(bound["anchor_id"]),
            int(bound["oldest_ts"]), int(bound["oldest_id"]))


# Предикат окна выборки (chat_id + верхняя граница «до якоря включительно»,
# нижняя — «не старее oldest включительно»); параметризуется как SQL.
_HISTORY_WINDOW_SQL = (
    "chat_id = ? AND (timestamp < ? OR (timestamp = ? AND id <= ?)) "
    "AND (timestamp > ? OR (timestamp = ? AND id >= ?))"
)


async def _history_probe_row(db, sql: str, params: tuple):
    """Точечное чтение метаданных (id/timestamp, БЕЗ тел сообщений) —
    архконтракт §0: захват границы выбирает только метаданные. Доступ через
    существующий aiosqlite-коннект DatabaseService (прецедент:
    canonical_messages.py / chat_lore.py). Duck-typing фейков (нет коннекта)
    → None — caller обязан иметь честный fallback."""
    conn = getattr(db, "db", None)
    if conn is None or not hasattr(conn, "execute"):
        return None
    cursor = await conn.execute(sql, params)
    row = await cursor.fetchone()
    return row


def _bound_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _row_field(row, key: str, default: int = 0) -> int:
    """Толерантное чтение числового поля строки (dict ИЛИ aiosqlite.Row —
    у Row нет .get, отсутствующий ключ → default)."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return _bound_int(value, default)


async def capture_history_sample(db, chat_id: int, requested: int) -> dict | None:
    """Захват границы выборки (архконтракт §0): два точечных чтения
    метаданных (якорь + граница N-й строки) и COUNT в окне. Тела сообщений
    НЕ выбирает — вторая полная копия истории в памяти процесса запрещена.

    Возвращает маленький объект границы (dict) или None (пустой чат).
    Куда попадает: локальная переменная хода; волна SEGMENTS дополнительно
    ставит его на ``tool_ctx.history_sample`` (setattr) ДО сборки контекста."""
    if db is None or not hasattr(db, "get_recent_messages"):
        raise RuntimeError("db недоступен")
    wanted = max(1, int(requested))
    anchor_row = await db.get_recent_messages(chat_id, 1)
    if not anchor_row:
        return None
    newest = anchor_row[-1]
    a_ts, a_id = _row_field(newest, "timestamp"), _row_field(newest, "id")
    window = (a_ts, a_id, 0, 0)          # нижняя граница пока «весь чат»
    available = wanted
    o_ts, o_id = 0, 0
    try:
        # COUNT в окне «до якоря включительно» (метаданные, не тела).
        row = await _history_probe_row(
            db, f"SELECT COUNT(*) AS n FROM smart_messages WHERE {_HISTORY_WINDOW_SQL}",
            (chat_id, a_ts, a_ts, a_id, 0, 0, 0))
        in_window = _bound_int(row["n"] if row is not None else row, 0)
        if in_window <= 0:
            return None
        if in_window <= wanted:
            # Окно короче запроса: доступно ровно in_window (H7), нижний край
            # — фактическое самое старое сообщение окна.
            available = in_window
            row = await _history_probe_row(
                db,
                "SELECT id, timestamp FROM smart_messages WHERE "
                + _HISTORY_WINDOW_SQL + " ORDER BY timestamp ASC, id ASC LIMIT 1",
                (chat_id, a_ts, a_ts, a_id, 0, 0, 0))
            if row is None:
                return None
            o_ts, o_id = _bound_int(row["timestamp"]), _bound_int(row["id"])
        else:
            # N-я строка назад от якоря включительно (OFFSET wanted-1) —
            # второй точечный метаданный захват.
            row = await _history_probe_row(
                db,
                "SELECT id, timestamp FROM smart_messages WHERE "
                + _HISTORY_WINDOW_SQL + " ORDER BY timestamp DESC, id DESC "
                "LIMIT 1 OFFSET ?",
                (chat_id, a_ts, a_ts, a_id, 0, 0, 0, wanted - 1))
            if row is None:
                return None
            o_ts, o_id = _bound_int(row["timestamp"]), _bound_int(row["id"])
    except (TypeError, AttributeError):
        # Коннект недоступен (duck-typed фейк без aiosqlite): честный
        # fallback на существующий reader — окна ≤ wanted; прод-путь всегда
        # идёт через метаданные выше. Тела не сохраняются между вызовами.
        rows = await db.get_recent_messages(chat_id, wanted)
        if not rows:
            return None
        ordered = sorted(
            rows, key=lambda r: (_row_field(r, "timestamp"),
                                 _row_field(r, "id")))
        newest = ordered[-1]
        a_ts, a_id = _row_field(newest, "timestamp"), _row_field(newest, "id")
        oldest = ordered[0]
        o_ts, o_id = _row_field(oldest, "timestamp"), _row_field(oldest, "id")
        available = min(wanted, len(ordered))
    return {
        "sample_id": _history_sample_id(chat_id, a_ts, a_id, wanted),
        "chat_id": int(chat_id),
        "anchor_ts": a_ts, "anchor_id": a_id,
        "oldest_ts": o_ts, "oldest_id": o_id,
        "requested": wanted,
        "available": max(1, min(available, wanted)),
        "captured_wall": time.time(),
    }


async def _history_count_in_window(db, bound: dict, up_to: tuple | None,
                                   after: tuple | None = None):
    """COUNT строк окна выборки (метаданные). ``up_to=(ts, id)`` — только
    строки не позже точки; ``after=(ts, id)`` — только строки строго после
    точки (выжившие остатки для H14). Коннект недоступен → None."""
    params: list = [int(bound["chat_id"]), _bound_int(bound["anchor_ts"]),
                    _bound_int(bound["anchor_ts"]), _bound_int(bound["anchor_id"]),
                    _bound_int(bound["oldest_ts"]), _bound_int(bound["oldest_ts"]),
                    _bound_int(bound["oldest_id"])]
    sql = f"SELECT COUNT(*) AS n FROM smart_messages WHERE {_HISTORY_WINDOW_SQL}"
    if up_to is not None:
        sql += " AND (timestamp < ? OR (timestamp = ? AND id <= ?))"
        params.extend([up_to[0], up_to[0], up_to[1]])
    if after is not None:
        sql += " AND (timestamp > ? OR (timestamp = ? AND id > ?))"
        params.extend([after[0], after[0], after[1]])
    try:
        row = await _history_probe_row(db, sql, tuple(params))
    except (TypeError, AttributeError):
        return None
    if row is None:
        return None
    return _bound_int(row["n"] if row is not None else row, 0)


async def _history_anchor_exists(db, fields: dict) -> bool:
    """Проверка «якорь выборки ещё в БД» (устойчивая идентичность строки —
    пара timestamp+id, не только timestamp). Коннект недоступен → None
    (проверка невозможна — не блокируем; прод-путь проверяет всегда)."""
    try:
        row = await _history_probe_row(
            db,
            "SELECT id FROM smart_messages WHERE chat_id = ? AND id = ? "
            "AND timestamp = ? LIMIT 1",
            (int(fields["chat_id"]), int(fields["anchor_id"]),
             int(fields["anchor_ts"])))
    except (TypeError, AttributeError):
        return True
    return row is not None


_HISTORY_NUM_RE = re.compile(r"\d[\d \u00A0,]*\d|\d")
_HISTORY_UNIT_RE = re.compile(r"(сообщени|messages|реплик)", re.IGNORECASE)
_HISTORY_RECENT_RE = re.compile(r"(последн|last|недавн)", re.IGNORECASE)


def extract_history_depth(text: str) -> int | None:
    """Чистая функция (архконтракт §1): целое N ≥ 1 (допускается разделитель
    тысяч «2 000» / «2,000») в окне ~40 символов от единицы счёта
    («сообщени»/«messages»/«реплик») И от маркера недавности
    («последн»/«last»/«недавн»). Нет числа/единицы/недавности → None (путь B
    / дефолт, как сейчас). Числа 400 и 2000 не особые; список тем пуст."""
    value = str(text or "")
    if not value:
        return None
    lowered = value.lower()
    for match in _HISTORY_NUM_RE.finditer(lowered):
        digits = re.sub(r"[ \u00A0,]", "", match.group())
        if not digits.isdigit():
            continue
        start, end = match.span()
        window = lowered[max(0, start - 40):end + 40]
        if _HISTORY_UNIT_RE.search(window) and _HISTORY_RECENT_RE.search(window):
            number = int(digits)
            if number >= 1:
                return number
    return None


def parse_history_sample(text: str) -> dict | None:
    """Парсер головы ``@@HISTORY_SAMPLE v1 … @@END_HEADER`` (архконтракт §1).
    Блока нет (старый результат / путь B / ошибка) → None. Числовые поля —
    int, остальные — строки. Текст сообщений в блок не входит."""
    value = str(text or "")
    start = value.find(_HISTORY_SAMPLE_HEADER)
    if start < 0:
        return None
    end = value.find(_HISTORY_HEADER_END, start)
    if end < 0:
        return None
    fields: dict = {"raw_header": value[start:end + len(_HISTORY_HEADER_END)]}
    for line in value[start + len(_HISTORY_SAMPLE_HEADER):end].splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key in ("requested", "available", "processed", "remaining",
                   "has_next", "incomplete"):
            try:
                fields[key] = int(val)
            except (TypeError, ValueError):
                fields[key] = val
        else:
            fields[key] = val
    return fields


# ── структурная обрезка результата (§4.4 Preserve, limits-audit.md №3) ─────


@dataclasses.dataclass(frozen=True)
class Truncation:
    """Наблюдаемый конверт обрезки: `effective_limit/source/used/truncated/
    why/retrievable_remainder` (контракт замера §8).

    ``retrievable_remainder`` — число символов/кандидатов, которые можно
    догрузить существующим инструментом (не «потеряно навсегда»)."""

    text: str = ""
    effective_limit: int = 0
    source: str = ""
    used: int = 0
    total: int = 0
    truncated: bool = False
    why: str = ""
    retrievable_remainder: int = 0
    unit: str = "chars"
    candidates_total: int = 0
    candidates_kept: int = 0

    def as_event_fields(self) -> dict:
        return {
            "effective_limit": int(self.effective_limit),
            "limit_source": self.source,
            "used": int(self.used),
            "total": int(self.total),
            "truncated": bool(self.truncated),
            "why": self.why,
            "retrievable_remainder": int(self.retrievable_remainder),
            "unit": self.unit,
            "candidates_total": int(self.candidates_total),
            "candidates_kept": int(self.candidates_kept),
        }


def _truncate(text: str, limit: int) -> str:
    """Обрезка результата до лимита символов БЕЗ разрыва URL/JSON.

    Было: ``text[:limit].rstrip() + "…"`` — рвало ссылку/JSON/пару
    claim→source (limits-audit.md №3). Теперь: граница слова/токена
    (`web_content_extractor.clip_at_boundary`), валидный JSON не режется
    вовсе (структурную обрезку делает владелец схемы, например
    ``_dig_json_payload``); маркер ``…`` сохранён (tool_result отличает
    усечённый конверт по нему)."""
    body = str(text or "")
    try:
        boundary = int(limit)
    except (TypeError, ValueError):
        return body
    if boundary <= 0 or len(body) <= boundary:
        return body
    stripped = body.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(body)
            return body
        except Exception:
            pass
    return clip_at_boundary(body, boundary).rstrip() + "…"


def _parse_hit_blocks(text: str) -> list[dict]:
    """Разобрать выдачу поиска на кандидатов:
    ``{title, snippet, url[, published_at]}``.

    Формат `SearchAggregator._format_hits`: блоки через ``\\n\\n``, внутри
    ``title\\nsnippet\\n[дата публикации: YYYY-MM-DD\\n]url``. Строка даты
    вынимается в ОТДЕЛЬНОЕ поле: иначе она попадала бы в сниппет и её срезало
    бы сжатие сниппета (дата молча пропадала бы из выдачи). Незнакомый
    формат → пустой список (тогда работает обычная текстовая обрезка)."""
    blocks: list[dict] = []
    for chunk in str(text or "").split("\n\n"):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        published_at = ""
        kept: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith(_SEARCH_PUBLISHED_LABEL):
                if not published_at:
                    published_at = normalise_publication_date(
                        stripped[len(_SEARCH_PUBLISHED_LABEL):])
                # Метка — метаданные источника, а не текст: в сниппет не идёт.
                # Кривое значение отбрасывается (дата остаётся пустой, а не
                # «правдоподобной»).
                continue
            kept.append(line)
        lines = kept
        if not lines:
            continue
        url = ""
        if lines and re.match(r"^https?://", lines[-1].strip()):
            url = lines[-1].strip()
            lines = lines[:-1]
        title = lines[0].strip() if lines else ""
        snippet = " ".join(line.strip() for line in lines[1:]).strip()
        if not url and not title:
            continue
        block = {"title": title, "snippet": snippet, "url": url}
        if published_at:
            block["published_at"] = published_at
        blocks.append(block)
    return blocks


def _render_hit_blocks(blocks: list[dict]) -> str:
    """Собрать кандидатов обратно в формат выдачи (без потери URL и даты)."""
    parts: list[str] = []
    for block in blocks:
        lines = [str(block.get("title") or "")]
        snippet = str(block.get("snippet") or "").strip()
        if snippet:
            lines.append(snippet)
        published = normalise_publication_date(block.get("published_at"))
        if published:
            lines.append(f"{_SEARCH_PUBLISHED_LABEL} {published}")
        url = str(block.get("url") or "").strip()
        if url:
            lines.append(url)
        parts.append("\n".join(line for line in lines if line))
    return "\n\n".join(part for part in parts if part)


def _compact_search_candidates(text: str, limit: int, *,
                               source: str = "", stage: str = "retrieve"
                               ) -> Truncation:
    """Сжать выдачу поиска, НЕ теряя ни одного URL (сценарий 36).

    Выдача поиска — индекс кандидатов (§4.3). Прежний слепой срез 4000
    выкидывал URL, оказавшийся после 4k (сценарий 36): релевантный источник
    становился недостижим для `fetch_article`. Здесь:
      1) если всё влезает — без изменений;
      2) иначе сначала сокращаются СНИППЕТЫ (все URL и заголовки остаются);
      3) если даже `title+url` не влезают — оставшиеся кандидаты уходят
         списком URL, а их число попадает в ``retrievable_remainder``.
    Никогда не режет внутри URL/JSON."""
    body = str(text or "")
    total = len(body)
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0 or total <= cap:
        blocks_all = _parse_hit_blocks(body)
        return Truncation(text=body, effective_limit=cap, source=source,
                          used=total, total=total, truncated=False,
                          unit="blocks",
                          candidates_total=len(blocks_all),
                          candidates_kept=len(blocks_all))
    blocks = _parse_hit_blocks(body)
    if not blocks:
        cut = clip_at_boundary(body, cap)
        return Truncation(text=cut + "…", effective_limit=cap, source=source,
                          used=len(cut), total=total, truncated=True,
                          why="over_window_single_block",
                          retrievable_remainder=max(0, total - len(cut)),
                          unit="chars")
    total_candidates = len(blocks)
    # 1) Урезать сниппеты, сохранив каждый title+url (+дату публикации: это
    #    метаданные источника, а не текст, сжимать её нельзя).
    skeleton = [{"title": b["title"], "snippet": "", "url": b["url"],
                 "published_at": b.get("published_at", "")}
                for b in blocks]
    skeleton_len = len(_render_hit_blocks(skeleton))
    if skeleton_len <= cap:
        allowance = cap - skeleton_len
        snippet_lengths = [len(b["snippet"]) for b in blocks]
        raw_total = sum(snippet_lengths)
        scaled: list[dict] = []
        for block in blocks:
            length = len(block["snippet"])
            if not length:
                scaled.append(block)
                continue
            share = int(allowance * (length / raw_total)) if raw_total else 0
            if share < 40:
                # Сниппет без полезной информации не несём: URL и дата остаются.
                scaled.append({"title": block["title"], "snippet": "",
                               "url": block["url"],
                               "published_at": block.get("published_at", "")})
                continue
            scaled.append({
                "title": block["title"],
                "snippet": clip_at_boundary(block["snippet"], share),
                "url": block["url"],
                "published_at": block.get("published_at", "")})
        compacted = _render_hit_blocks(scaled)
        while len(compacted) > cap and any(b["snippet"] for b in scaled):
            # добор переполнения: самый длинный сниппет урезаем первым
            idx = max(range(len(scaled)),
                      key=lambda k: len(scaled[k]["snippet"]))
            snippet = scaled[idx]["snippet"]
            if not snippet:
                break
            over = len(compacted) - cap
            scaled[idx]["snippet"] = clip_at_boundary(
                snippet, max(0, len(snippet) - over - 8))
            compacted = _render_hit_blocks(scaled)
        kept_all = sum(1 for block in scaled if block["url"])
        # Маркер частичности (tool_result отличает усечённый конверт по «…»);
        # это не потеря URL: индекс кандидатов полон, сокращены только сниппеты.
        compacted = compacted.rstrip() + "\n…"
        return Truncation(
            text=compacted, effective_limit=cap, source=source,
            used=len(compacted), total=total, truncated=True,
            why="over_window_snippets_compacted",
            retrievable_remainder=max(0, total - len(compacted)),
            unit="blocks", candidates_total=total_candidates,
            candidates_kept=kept_all)
    # 2) Даже title+url не влезают: полные первые K + список URL остальных.
    kept: list[dict] = []
    tail_urls: list[str] = []
    used = 0
    for block in blocks:
        piece = _render_hit_blocks([block])
        addition = len(piece) + (2 if kept else 0)
        if used + addition <= cap:
            kept.append(block)
            used += addition
        elif block["url"]:
            tail_urls.append(block["url"])
    urls_only = "\n".join(tail_urls)
    if tail_urls:
        header = f"…ещё {len(tail_urls)} кандидатов (только ссылки):"
        room = max(0, cap - used - len(header) - 2)
        urls_text = clip_at_boundary(urls_only, room) if room else ""
        compacted = "\n\n".join(
            part for part in (_render_hit_blocks(kept),
                              (header + "\n" + urls_text) if urls_text else "")
            if part)
        shown_urls = sum(1 for url in tail_urls if url in compacted)
    else:
        compacted = _render_hit_blocks(kept)
        shown_urls = 0
    compacted = compacted.rstrip() + "\n…"
    return Truncation(
        text=compacted, effective_limit=cap, source=source, used=len(compacted),
        total=total, truncated=True, why="over_window_url_index",
        retrievable_remainder=max(0, len(tail_urls) - shown_urls),
        unit="blocks", candidates_total=total_candidates,
        candidates_kept=len(kept) + shown_urls)


def _image_memory_note(request) -> str:
    """A4 (ADR-1026-19 D5/D6): reply-заметка tool-пути (уточнение/
    дисклеймер/запрос фото) — только при memory-aware запросе.

    F2 (T-3640): `exact_likeness` — независимый интент-сигнал, поэтому
    заметка эмитится при `context_required OR exact_likeness` (иначе
    exact-запрос с неразрешённым субъектом молча терял ветку фото/референса)."""
    if request is None:
        return ""
    mc = getattr(request, "memory_context", None)
    exact = bool(mc.get("exact_likeness")) if isinstance(mc, dict) else False
    if not (bool(getattr(request, "context_required", False)) or exact):
        return ""
    try:
        return image_context_memory.build_reply_note(mc)
    except Exception:  # pragma: no cover
        return ""


def _dig_json_payload(result: dict, limit: int) -> str:
    """S10.20-3: сериализовать dig-контракт, ужимая СЕКЦИИ по бюджету.

    ``_truncate(json.dumps(...))`` рвал JSON (невалидные скобки). Здесь
    сначала выкидываются хвостовые элементы ``snippets``/``facts``, затем
    укорачиваются самые длинные строки — итог ВСЕГДА валидный JSON. При
    усечении добавляется ``"truncated": true`` (честный сигнал модели).

    MCA-15 (T-4926, §24.1 п.8; K1 ON): голое число без метода не остаётся.
    После секций уходят необязательные поля; schema/status/unit/method/scope
    сохраняются; если обязательное не помещается — structured
    ``{"status": "insufficient_output_budget", "value": null}`` вместо
    ``{truncated, total_mentions}``. K1 OFF → прежний контракт байт-в-байт.
    """
    budget = max(1, int(limit or 0))
    payload = json.dumps(result, ensure_ascii=False)
    if len(payload) <= budget:
        return payload
    if not mca_gates.chat_statistics_enabled():
        out = dict(result)
        out["snippets"] = list(result.get("snippets") or [])
        out["facts"] = list(result.get("facts") or [])
        out["truncated"] = True

        def _size() -> int:
            return len(json.dumps(out, ensure_ascii=False))

        # 1) выкидываем хвостовые элементы секций (сначала facts — они дешевле).
        while _size() > budget and (out["snippets"] or out["facts"]):
            if out["facts"]:
                out["facts"].pop()
            else:
                out["snippets"].pop()
        # 2) усекаем самые длинные строки (валидность JSON сохраняется).
        for _ in range(100):
            if _size() <= budget:
                break
            target = out["snippets"] if out["snippets"] else out["facts"]
            if not target:
                break
            idx = max(range(len(target)), key=lambda k: len(str(target[k])))
            text = str(target[idx])
            if len(text) <= 1:
                break
            overshoot = _size() - budget
            target[idx] = text[:max(1, len(text) - overshoot - 8)]
        serialized = json.dumps(out, ensure_ascii=False)
        if len(serialized) > budget:
            # Даже метаданные не влезли — честный минимум (JSON валиден).
            serialized = json.dumps(
                {"truncated": True,
                 "total_mentions": int(result.get("total_mentions") or 0)},
                ensure_ascii=False)
        return serialized

    # ── K1 ON: сохраняем обязательное (status/stats), жертвуем остальным ──
    out = dict(result)
    out["snippets"] = list(result.get("snippets") or [])
    out["facts"] = list(result.get("facts") or [])
    out["truncated"] = True

    def _size() -> int:
        return len(json.dumps(out, ensure_ascii=False))

    # 1) секции — первыми (сначала facts).
    while _size() > budget and (out["snippets"] or out["facts"]):
        if out["facts"]:
            out["facts"].pop()
        else:
            out["snippets"].pop()
    # 2) длинные строки секций.
    for _ in range(100):
        if _size() <= budget:
            break
        target = out["snippets"] if out["snippets"] else out["facts"]
        if not target:
            break
        idx = max(range(len(target)), key=lambda k: len(str(target[k])))
        text = str(target[idx])
        if len(text) <= 1:
            break
        overshoot = _size() - budget
        target[idx] = text[:max(1, len(text) - overshoot - 8)]
    # 3) необязательные поля (status/stats неприкосновенны).
    for key in ("authors", "mentions_by_authors", "first_seen", "last_seen",
                "data_as_of", "time_bounds", "message", "total_mentions",
                "facts", "snippets"):
        if _size() <= budget:
            break
        if key in out and key not in ("status", "stats", "truncated"):
            out.pop(key, None)
    has_content = bool(out.get("snippets") or out.get("facts")
                       or out.get("status") or out.get("stats"))
    serialized = json.dumps(out, ensure_ascii=False)
    if len(serialized) <= budget and has_content:
        return serialized
    # 4) обязательное не помещается (или не осталось содержательного) —
    #    structured honest error (не голое число и не context-free `{truncated}`).
    compact = {"status": "insufficient_output_budget", "value": None,
               "reason": "insufficient_output_budget"}
    serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) <= budget:
        return serialized
    return json.dumps({"status": "insufficient_output_budget"},
                      ensure_ascii=False)


# Обязательные ключи stats-контракта (T-4932): schema/status/unit/scope/method
# сохраняются при любом урезании; голое число не остаётся никогда.
_STATS_MANDATORY_KEYS = ("metric_id", "status", "value", "unit", "method",
                         "method_label", "scope", "coverage")


def _stats_json_payload(result: dict, limit: int) -> str:
    """Сериализовать stats-контракт с честным урезанием (T-4932, §4.3).

    Порядок: сначала уходят ``examples``, затем необязательные поля
    (authors/time_bounds/watermark/...); обязательные schema/status/unit/
    scope/method остаются. Если обязательное не помещается —
    ``{"status":"insufficient_output_budget","value":null}`` (не голое
    число и не частичный JSON)."""
    budget = max(1, int(limit or 0))
    out = dict(result or {})
    payload = json.dumps(out, ensure_ascii=False)
    if len(payload) <= budget:
        return payload

    def _size() -> int:
        return len(json.dumps(out, ensure_ascii=False))

    # 1) examples — первыми (сначала убираются примеры, T-4932).
    examples = list(out.get("examples") or [])
    while _size() > budget and examples:
        examples.pop()
    out["examples"] = examples
    # 2) необязательные поля.
    for key in ("examples", "authors", "human_label", "verified_phrase",
                "time_bounds", "watermark", "data_as_of", "duration_ms",
                "excluded_count", "unknown_count", "reason"):
        if _size() <= budget:
            break
        if key in out and key not in _STATS_MANDATORY_KEYS:
            out.pop(key, None)
    serialized = json.dumps(out, ensure_ascii=False)
    if len(serialized) <= budget and all(k in out
                                         for k in _STATS_MANDATORY_KEYS):
        return serialized
    compact = {"status": "insufficient_output_budget", "value": None,
               "reason": "insufficient_output_budget"}
    serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) <= budget:
        return serialized
    return json.dumps({"status": "insufficient_output_budget"},
                      ensure_ascii=False)


async def resolve_lore_compiler_flag(chat_id: int | None) -> bool:
    """S10.20-2: флаг «Летописца» тем же per-chat каскадом, что DirectChat
    (override → hot → канон). ``chat_id=None`` — глобальный hot-слой."""
    base = hot.get("flags.lore_compiler_enabled",
                   settings.LORE_COMPILER_ENABLED)
    if chat_id is None:
        return bool(base)
    try:
        from services.chat_params import get_chat_param
        value = await get_chat_param(
            chat_id, "flags.lore_compiler_enabled", base)
        return bool(value)
    except Exception:
        logger.warning("[tools] lore flag resolve failed — global | chat=%s",
                       chat_id)
        return bool(base)


def _format_timestamp(ts) -> str:
    """timestamp (int/float) → 'YYYY-MM-DD HH:MM' (пусто при отсутствии)."""
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return ""


class ToolHealthDeps:
    """Контейнер health-инструмента: CheckupService + CheckupLogsFetcher.

    Инжектится из bot.py (тот же путь, что роутер 0g), чтобы инструмент
    get_bot_health не тянул хендлер в сервисный слой.
    """

    def __init__(self, service, fetcher) -> None:
        self.service = service            # CheckupService
        self.fetcher = fetcher            # CheckupLogsFetcher


class ToolDeps:
    """Контейнер зависимостей инструментов (инжектится из bot.py).

    Раунд 10.15 (F8): video/downloader/health/db — аддитивные keyword-only
    (старые вызовы `ToolDeps(search, memory, aliases)` не ломаются).
    """

    def __init__(self, search, memory, aliases=None, *, video=None,
                 downloader=None, health=None, db=None,
                 download_cooldown=None, llm=None, transcriber=None,
                 extractor=None, source_reader=None, diagnostics=None) -> None:
        self.search = search            # SearchAggregator
        self.memory = memory            # MemoryManager
        self.aliases = aliases          # AliasResolver | None
        self.video = video              # YoutubeSummarizerService | None
        self.downloader = downloader    # VideoDownloader | None
        self.health = health            # ToolHealthDeps | None
        self.db = db                    # Database | None (F9)
        # R10.15-9: zero-arg-провайдер общего download-кулдауна роутера 4e
        # (ленивая ссылка: `setup_video_download` пересоздаёт трекер в
        # on_startup уже после сборки ToolDeps). None → гейта нет.
        self.download_cooldown = download_cooldown
        # Раунд 10.20 (БЛОК 1, ADR-1020-4 п.3, T-1887): LLM-клиент для
        # изолированного синтеза истории «Летописца» (compile_lore_story).
        # None → инструмент честно вернёт «сервис недоступен».
        self.llm = llm                  # LLMClient | None
        # Раунд 10.24 (F14, ADR-1024-15 §2.3): STT-сервис для нативного
        # пути summarize_video (STT-фолбэк выжимки). Тот же инстанс, что у
        # youtube/voice (DI в bot.py). None → честная деградация.
        self.transcriber = transcriber  # VoiceTranscriber | None
        # Раунд 10.26 (A2, ADR-1026-15 D5): extractor для `fetch_article`
        # (reuse `WebContentExtractor`; тот же инстанс, что у web-модуля).
        # None → инструмент честно вернёт структурный error.
        self.extractor = extractor      # WebContentExtractor | None
        # EVOL-SRC-READER (W6): SourceReader для `read_source_code`. None →
        # роутер собирает штатный (SafeFetcher + GitHubProvider) лениво; тесты
        # передают подменный провайдер (детерминизм, без сети).
        self.source_reader = source_reader
        # SELF-DIAG-01 D3: единый read-only диагностический collector для
        # `inspect_runtime` И `get_bot_health` (не вторая инсталляция probes).
        # None → роутер собирает один экземпляр лениво из существующих
        # db/memory/logs-зависимостей.
        self.diagnostics = diagnostics


class ToolContext:
    """Контекст вызова инструментов (одно сообщение direct_chat).

    Раунд 10.15 (F8): bot/reply_to_message_id/user_id — аддитивные
    keyword-only (у download_media есть куда отправить файл и на что
    ответить реплаем).

    Раунд 10.20 (БЛОК 1, ADR-1020-6 п.2, T-1887/T-1892): ``lore_compiled`` —
    детерминированный СИГНАЛ РЕЖИМА. Ставится инструментом
    compile_lore_story (успешный синтез) и читается DirectChat ПОСЛЕ цикла
    `chat_with_tools`: `True` → доставка истории локально с parse_mode=HTML
    (О5), иначе — обычный plain-путь байт-в-байт. Сам цикл (`tool_loop.py`)
    сигнал НЕ обрабатывает — он лишь проносит ctx.
    """

    def __init__(self, chat_id: int, query: str, *, bot=None,
                 reply_to_message_id=None, user_id=None,
                 reply_source_message_id=None, reply_source_text="",
                 media_target_message_id=None,
                 lore_verbatim_instruction: bool = True,
                 correlation_id: str | None = None,
                 native_media=None,
                 resolved_url: str | None = None,
                 image_request_handled: bool = False,
                 speech=None,
                 diagnostic_research: dict | None = None) -> None:
        self.chat_id = chat_id
        self.query = str(query or "")
        self.bot = bot
        self.reply_to_message_id = reply_to_message_id
        # TR-FIX2 (live 2.58.91, findings 3/5): ``reply_to_message_id`` —
        # сообщение-ТРИГГЕР хода (на него бот отвечает); ``reply_source_*`` —
        # сообщение, на которое ответил ПОЛЬЗОВАТЕЛЬ (``reply_to_message``):
        # источник медиа (recognize_image) и claim'а reply-фактчека.
        # ``media_target_message_id`` — разрешённая медиа-цель хода
        # (своё медиа → текущее, иначе reply-медиа → replied-сообщение).
        self.reply_source_message_id = reply_source_message_id
        self.reply_source_text = str(reply_source_text or "")
        self.media_target_message_id = media_target_message_id
        self.user_id = user_id
        # F7 (ADR-1023-7 D4): сквозной id ответа — прокидывается в
        # инструменты, которые пишут телеметрию (generate_image → step='image').
        self.correlation_id = correlation_id
        # Раунд 10.24 (F14, ADR-1024-15 §2.3): разрешённый aiogram-объект
        # нативного медиа (``native_media.NativeMedia`` | None). Заполняется
        # DirectChat (F13), потребляется нативным путём инструментов (F14).
        self.native_media = native_media
        # Раунд 10.26 (A2, ADR-1026-15 D6): общий контекстный резолв ссылки
        # (текущее сообщение → reply). `fetch_article` без `url` берёт её
        # отсюда; None → честный `no_url`.
        self.resolved_url = str(resolved_url or "").strip() or None
        # A3 (ADR-1026-16 D3): авторитетный маркер прогона «изображение уже
        # обработано на этом ходу» (срабатывание пре-гейта ключевика →
        # direct_chat_service прокидывает image_pre_gate_fired). Читается
        # _generate_image ПЕРВЫМ делом → skipped/already_handled не сгенерирует.
        self.image_request_handled = bool(image_request_handled)
        # EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§4.2 п.2/п.5): ОБЩАЯ проекция
        # прогона хода (``SpeechProjection`` | None) — результаты инструментов
        # (история/копание/факты) адресуют сообщения ТЕМИ ЖЕ метками, что
        # остальной payload. None → сырой канон байт-в-байт (прежнее
        # поведение, машинные потребители не затронуты).
        self.speech = speech
        # P0 MEME-IMAGE-ONLY (owner 02.11.2026): «изображение уже доставлено в
        # чат на этом ходу» — отличает УСПЕШНУЮ доставку от простого
        # срабатывания пре-гейта (тот ставится и при отказе провайдера).
        # Ставится единственной точкой доставки: `_generate_image` (tool) и
        # `image_generation.maybe_handle_keyword` (пре-гейт). Читается
        # `DirectChatService.handle` ПОСЛЕ цикла инструментов: ход, который
        # ответил картинкой, не добавляет к ней текстовое сообщение.
        self.image_delivered = False
        # Раунд 10.26 (A2, ADR-1026-15 D1): out-of-band envelope-журнал
        # прогона (структурные результаты/ошибки/лимиты) — программный
        # A→B-handoff для инструментов и Синтезатора. В модельный ввод НЕ
        # сериализуется.
        self.tool_results: list[dict] = []
        # MCA-11 (ADR-1028-13 D1/D3): out-of-band сигнал инструмента
        # (SafeFetcher stage/retryable, `delivery_unknown`, usage) —
        # одноразово читается tool_loop и очищается на входе dispatch.
        # В модельно-видимый канал не попадает (R17-safe: коды/числа/id).
        self.tool_result_signal: dict | None = None
        self.lore_compiled = False
        # Раунд 10.20 (БЛОК 7.2c, ADR-1020-7 §2, T-1922): готовый текст
        # истории «Летописца» (HTML). DirectChat при `lore_compiled` доставляет
        # его детерминированно, не полагаясь на «верни дословно».
        self.lore_story = ""
        # S10.20-4: служебная инструкция «верни story ДОСЛОВНО» нужна только
        # DirectChat (там сигнал доставки уже есть, это мягкая страховка).
        # В фактчеке она провоцировала вердикт-историю → caller ставит False.
        self.lore_verbatim_instruction = bool(lore_verbatim_instruction)
        # MCA-15 (T-4920, ADR-1028-12 D6): детерминированный intent текущего
        # хода (`chat_statistics`/`historical_evidence`/`social_banter`/
        # `mixed`; "" — классификатор не работал). Аддитивное поле; инструменты
        # читают его только как сигнал (глобальной блокировки инструментов нет).
        self.stats_intent = ""
        # MCA-15 (T-4929/T-4931, ADR-1028-12 D4/D5): per-turn реестр
        # MetricResult (in-memory, один ход) — источник NumericClaim для
        # numeric-гарда; durable-хранения чисел нет (пересчёт).
        self.metric_results: list = []
        # MCA-15 (T-4932, §7.3): доставлена lore-история UPD-ветки `unchanged`
        # со старыми агрегатами → пометка на перепроверку (lore не удаляется).
        self.lore_stats_recheck = False
        # ASAP-EVIDENCE-ROUTING-01 v3 (§4.3): per-call бюджет evidence в
        # символах, который композер уже посчитал под реальное окно L2 БЕЗ
        # output reserve (один резерв — один раз, C4). 0 → лимит инструмента
        # выводится из реального окна модели (`_evidence_window`).
        self.evidence_budget_chars = 0
        # Наблюдаемый конверт обрезки инструментов (§8 «Контракт замера»):
        # effective_limit/source/used/truncated/why/retrievable_remainder.
        # Out-of-band (в модельный ввод не сериализуется), R17-safe.
        self.evidence_limits: list[dict] = []
        # VMQ-MEM-TIME (§2): политика временнóго охвата памяти из плана L1
        # (`operative|historical|auto`; "" — план не давал значения, тогда
        # действует серверный `auto`). Аддитивное поле, читается профилем и
        # обзором памяти; второй meanings-канал не создаётся.
        self.memory_scope = ""
        # SELF-DIAG-01 D3: решение политики D2 для текущего диагностического
        # вызова (без секретов). Заполняется `_diagnostic_guard` ДО исполнения;
        # `inspect_runtime` кладёт его в bundle.access.permission_decision.
        self.diagnostic_decision: dict | None = None
        # SELF-DIAG-01 corrective (13.11.2026): исполняемое структурированное
        # решение L1 `diagnostic_research` (+ серверная identity своего repo).
        # Заполняется вызывающим ТОЛЬКО после target=self; аргументы модели
        # этот контекст не задают и прав не повышают. None — обычный вызов.
        self.diagnostic_research: dict | None = (
            dict(diagnostic_research)
            if isinstance(diagnostic_research, dict) else None)

    def result_for(self, tool_name: str) -> dict | None:
        """A2 (ADR-1026-15 D1/D6): последний envelope-результат инструмента.

        Общий (не per-combination) программный handoff A→B: инструмент B
        (или Синтезатор) может прочитать структурный результат A. Возвращает
        envelope-запись или ``None`` (инструмент не вызывался).
        """
        for entry in reversed(getattr(self, "tool_results", []) or []):
            if entry.get("tool") == tool_name:
                return entry
        return None


# ── dig_into_lore (раунд 9, T-820): код-дефолты (spec §3.6.4; REGISTRY-ключи
# flags.dig_*/limits.dig_* заведены фикс-раундом — группы flags_memory/
# limits_memory; код читает через hot.get с фолбэком settings, код-константы
# ниже — только страховка для пустого значения).
_DIG_YEAR_MIN = 2000
_DIG_PERSON_MAX_CHARS = 100
# «N лет назад» в query без year (major-2/D-fix): слова-количества → N.
_DIG_YEARS_AGO_NUM_RE = re.compile(
    r"(\d{1,2})\s+(?:лет|год(?:а)?)\s+назад")
_DIG_YEARS_AGO_WORD_RE = re.compile(
    r"(несколько|пару|тройку)\s+лет\s+назад")
_DIG_YEARS_AGO_WORDS = {"несколько": 3, "пару": 2, "тройку": 3}
# Верхний предел глубины BFS по графу (защита от кривого hot-значения).
_DIG_GRAPH_MAX_HOP_DEPTH = 5


class ToolRouter:
    """Реестр исполнения инструментов (3.3). Никогда не бросает."""

    def __init__(self, deps: ToolDeps) -> None:
        self.deps = deps

    async def dispatch(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """→ строка результата инструмента (в т.ч. 'ОШИБКА …') — НЕ бросает."""
        # MCA-11 (ADR-1028-13 D1): слот сигнала — строго per-call.
        _tool_result.clear_signal(ctx)
        registry = {
            "execute_web_search": self._execute_web_search,
            "query_chat_memory": self._query_chat_memory,
            "dig_into_lore": self._dig_into_lore,
            "summarize_video": self._summarize_video,
            "download_media": self._download_media,
            "get_bot_health": self._get_bot_health,
            "get_recent_history": self._get_recent_history,
            "compile_lore_story": self._compile_lore_story,
            "generate_image": self._generate_image,
            "transcribe_video": self._transcribe_video,
            "fetch_article": self._fetch_article,
            "get_user_context": self._get_user_context,
            "recognize_image": self._recognize_image,
            "fact_check": self._fact_check,
            # ASAP5 §20 (edit-route): существующий submit_edit-маршрут
            # (media_execution → cover_style_edit) из Direct Chat.
            "edit_image": self._edit_image,
            # EVOL-SRC-READER (W6): проверенное чтение исходников
            # (discover|locate|read) поверх существующего SafeFetcher.
            "read_source_code": self._read_source_code,
            # SELF-DIAG-01 D3: один расширяемый read-only инструмент
            # диагностики (area/probe/scope/time_window/cursor/arguments).
            "inspect_runtime": self._inspect_runtime,
            # SELF-DIAG-01 D5/D6 (`SD1-D5-02`, `SD1-AMX-04`): защищённый
            # серверный readback промпта. Типизированный запрос исполняет
            # существующий handler; второго tool-loop/ACL/промпта нет.
            "prompt_readback": self._prompt_readback,
        }
        method = registry.get(name)
        if method is None:
            logger.warning("[tools] unknown tool | name=%s", name)
            return f"ОШИБКА: неизвестный инструмент {name}"
        # SELF-DIAG-01 D2 (owner amendment 2026-11-09): решение политики
        # доступа принимается ДО выполнения инструмента; principal берётся
        # только из Telegram-контекста (chat_id/user_id), не из arguments.
        blocked = await self._diagnostic_guard(name, ctx)
        if blocked is not None:
            return blocked
        started = time.monotonic()
        if name == "read_source_code":
            self._emit_diag_tool_event(
                "read_source_attempted", ctx,
                status=str((arguments or {}).get("operation") or "read")
                if isinstance(arguments, dict) else "read")
        try:
            result = await method(arguments, ctx)
        except Exception as exc:
            # R17: только класс исключения (без str(exc) — он может нести
            # URL/секреты; ревью-итер.1 L7).
            logger.warning("[tools] exec failed | tool=%s | error=%s",
                           name, type(exc).__name__)
            return f"ОШИБКА {name}: {type(exc).__name__}"
        # SELF-DIAG-01 D6: машинная телеметрия существующих диагностических
        # инструментов (без текстов/URL/ключей) — источник аналитики админки.
        self._emit_tool_outcome(name, arguments, result, ctx, started)
        # SELF-DIAG-01 D2: перепроверка прав ПЕРЕД возвратом защищённого
        # результата (revocation действует на уже запущенную проверку) +
        # структурное удаление секретов из результата инструмента.
        return await self._diagnostic_output(name, ctx, result)

    # ── SELF-DIAG-01 D2: политика доступа к диагностике ────────────
    #
    # Единая точка для ЛЮБОГО Tool Calling: решение принимается до
    # выполнения инструмента и перепроверяется перед возвратом результата.
    # Роль актора берётся только из Telegram-контекста (`ctx.chat_id`,
    # `ctx.user_id`); аргументы модели (`arguments`) прав не повышают.
    @staticmethod
    def _diag_runtime():
        """(cache, pg) существующего слоя прав; недоступность — не падение."""
        try:
            from services import hot_config as hot
            cache = hot.get_config_cache()
        except Exception:
            cache = None
        pg = getattr(cache, "pg", None) if cache is not None else None
        if getattr(pg, "pool", None) is None:
            pg = None
        return cache, pg

    async def _diagnostic_guard(self, name: str, ctx) -> str | None:
        """Отказ политики до выполнения инструмента (None — можно)."""
        from services import diagnostic_policy as diag
        if name not in diag.TOOL_CAPABILITIES:
            return None
        cache, pg = self._diag_runtime()
        decision = await diag.check_tool_call(
            name,
            telegram_id=getattr(ctx, "user_id", None),
            chat_id=getattr(ctx, "chat_id", None),
            cache=cache, bot=getattr(ctx, "bot", None), pg=pg,
            destination="tool")
        if decision is None or decision.allowed:
            self._remember_decision(ctx, decision)
            return None
        return diag.denial_message(decision, tool_name=name)

    @staticmethod
    def _remember_decision(ctx, decision) -> None:
        """SELF-DIAG-01 D3: сохранить решение политики для bundle.access.

        Только машинные поля (role/effect/reason/class) — без message и без
        секретных значений; аргументы модели сюда не попадают.
        """
        if decision is None:
            return
        try:
            ctx.diagnostic_decision = {
                "evaluated": True,
                "effect": decision.effect,
                "reason_code": decision.reason_code,
                "capability": decision.capability,
                "action": decision.action,
                "data_class": decision.data_class,
                "role": decision.role,
                "matrix_role": decision.matrix_role,
                "source": decision.source,
            }
        except Exception:      # pragma: no cover - защитная ветка
            ctx.diagnostic_decision = None

    async def _diagnostic_output(self, name: str, ctx, result: str) -> str:
        """Перепроверка прав + удаление секретов перед отдачей результата."""
        from services import diagnostic_policy as diag
        from services import output_projection as projection
        cache, pg = self._diag_runtime()
        capability = diag.TOOL_CAPABILITIES.get(name)
        try:
            if capability is not None:
                # fresh_telegram: отзыв админства действует на уже
                # запущенный вызов, поэтому перепроверка идёт мимо кэша.
                decision = await diag.check_tool_call(
                    name,
                    telegram_id=getattr(ctx, "user_id", None),
                    chat_id=getattr(ctx, "chat_id", None),
                    cache=cache, bot=getattr(ctx, "bot", None), pg=pg,
                    destination="tool_result", fresh_telegram=True)
                if decision is not None and not decision.allowed:
                    return diag.denial_message(decision, tool_name=name)
            # Секреты вычищаются из ЛЮБОГО результата инструмента (ТЗ §9.2:
            # output validation перед моделью и перед Telegram). Для
            # диагностических инструментов дополнительно учитывается
            # BYOK-ключ конкретного чата; для остальных — глобальные
            # источники (без БД).
            if capability is not None:
                secrets = await projection.known_secret_values_async(
                    cache=cache, pg=pg, chat_id=getattr(ctx, "chat_id", None))
            else:
                secrets = projection.known_secret_values(cache=cache)
            sanitized = projection.sanitize(result, kind="tool_result",
                                            secrets=secrets)
        except Exception as exc:
            # Политика/санитайзер недоступны → fail-closed: сырой результат
            # не отдаём (никогда не бросаем — контракт ToolRouter).
            logger.warning("[tools] diag output failed | tool=%s | error=%s",
                           name, type(exc).__name__)
            return (f"ОШИБКА {name}: вывод заблокирован "
                    "(политика недоступна)")
        if not sanitized.allowed:
            self._emit_diag_tool_event("diagnostic_output_validated", ctx,
                                       status="blocked")
            return f"ОШИБКА {name}: вывод заблокирован политикой секретов"
        # SELF-DIAG-01 D6 (`SD1-D6-17`): измеренный enforcement — каждая
        # отдача защищённого результата проходит через sanitize; статус
        # redaction виден аналитике (значения не пишутся).
        self._emit_diag_tool_event(
            "diagnostic_output_validated", ctx,
            status=str(sanitized.report.status or "clean")[:40],
            stage=name)
        return sanitized.text

    # ── SELF-DIAG-01 D6: prompt_readback + машинная телеметрия ─────────
    #
    # Регистрация инструмента = ровно три шва (D5 §«Регистрация»):
    # `tool_schemas.TOOL_CALLING_TOOLS`, этот реестр и
    # `diagnostic_policy.CAPABILITIES["prompts"].tool_names`. Ни второго
    # tool-loop, ни второго ACL, ни второго промпта здесь нет.

    async def _prompt_readback(self, arguments: dict, ctx) -> str:
        """Серверный readback промпта: типизированный запрос D5 handler'а.

        Модель не получает тело промпта — только машинный ack. Права
        проверяет существующая политика D2 внутри handler'а; аргументы
        модели доступа не повышают.
        """
        from handlers.prompt_readback import prompt_readback as _handler
        self._emit_diag_tool_event(
            "prompt_readback_requested", ctx,
            status=str((arguments or {}).get("requested_revision") or "")
            if isinstance(arguments, dict) else "")
        result = await _handler(arguments, ctx)
        self._note_prompt_readback_outcome(ctx, result)
        return result

    @staticmethod
    def _ack_fields(text) -> dict:
        """Разобрать машинный ack `prompt_readback` (без свободного текста)."""
        fields: dict = {}
        for token in str(text or "").split():
            if "=" not in token:
                continue
            key, _, value = token.partition("=")
            if key in ("status", "reason", "destination", "chunks",
                       "prompt_id", "revision", "source", "classification"):
                fields[key] = value
        return fields

    def _note_prompt_readback_outcome(self, ctx, text) -> None:
        """Статус ack → out-of-band сигнал ToolResult (denied ≠ ok)."""
        fields = self._ack_fields(text)
        status = fields.get("status") or ("error" if str(text).startswith(
            "ОШИБКА") else "")
        reason = str(fields.get("reason") or "")[:64]
        signal: dict = {"partial": status in ("partial", "ambiguous",
                                              "unverified", "not_found")}
        if status in ("denied", "unverified", "blocked"):
            signal["status"] = "denied"
        elif status in ("invalid_request", "unavailable", "ambiguous",
                        "not_found", "revision_unavailable", "partial"):
            signal["status"] = "error"
        if reason:
            signal["error_code"] = reason
            signal["reason"] = reason
        try:
            ctx.tool_result_signal = signal
        except Exception:      # pragma: no cover - произвольный ctx в тестах
            pass
        if status in ("denied", "unverified", "blocked"):
            self._emit_diag_tool_event("prompt_readback_denied", ctx,
                                       status=reason or status)
        elif status == "delivered":
            # SELF-DIAG-01 D6 B1: `allowed` — ТОЛЬКО фактически доставленный
            # промпт. partial/invalid_request/not_found/revision_unavailable/
            # unavailable/ambiguous не считаются разрешённой выдачей.
            self._emit_diag_tool_event("prompt_readback_allowed", ctx,
                                       status=status)

    def _emit_read_source_outcome(self, result, ctx, duration_ms: int) -> None:
        """`read_source_attempted/verified` и `code_unavailable` по payload."""
        try:
            payload = json.loads(str(result or ""))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "")
        if bool(payload.get("verified")):
            self._emit_diag_tool_event(
                "read_source_verified", ctx,
                status=str(payload.get("read_level") or status)[:40],
                duration_ms=duration_ms)
        if status in ("unavailable", "not_configured", "permission_denied",
                      "unsupported") or payload.get("error") == "disabled":
            self._emit_diag_tool_event(
                "code_unavailable", ctx,
                status=status or str(payload.get("error") or "")[:40],
                duration_ms=duration_ms)

    def _emit_tool_outcome(self, name: str, arguments, result, ctx,
                           started: float) -> None:
        """Один хук: телеметрия существующих диагностических инструментов."""
        duration_ms = int((time.monotonic() - started) * 1000)
        if name == "read_source_code":
            self._emit_read_source_outcome(result, ctx, duration_ms)

    @staticmethod
    def _emit_diag_tool_event(event_name: str, ctx, *, status: str = "",
                              duration_ms: int = 0,
                              stage: str = "tool") -> None:
        """Существующий контракт `mca_events` (код/числа, без payloads)."""
        try:
            _mca_events.emit_mca_event(
                event_name, outcome="success", component="self_diag",
                stage=str(stage or "tool")[:120],
                status=str(status or "")[:40] or None,
                duration_ms=int(duration_ms or 0),
                chat_id=getattr(ctx, "chat_id", None))
        except Exception:      # pragma: no cover - телеметрия fail-open
            return

    # ── execute_web_search ────────────────────────────────────────

    def _evidence_window(self, kind: str, ctx: ToolContext):
        """Окно ОДНОГО tool-вызова: бюджет композера → окно модели → legacy.

        Учитывает уже доставленный в этом ходе evidence (суммарная доля окна
        ограничена — защита от лавины tool-результатов). Никогда не бросает;
        возвращает ``auto_budget.EvidenceToolWindow``."""
        try:
            budget = int(getattr(ctx, "evidence_budget_chars", 0) or 0)
        except (TypeError, ValueError):
            budget = 0
        spent = 0
        for record in (getattr(ctx, "evidence_limits", None) or ()):
            if not isinstance(record, dict) or record.get("reused"):
                continue
            try:
                spent += max(0, int(record.get("used") or 0))
            except (TypeError, ValueError):
                continue
        try:
            # SMART D4: окно считается для ФАКТИЧЕСКИ назначенной модели
            # провайдера этого роутера, а не «всегда главной модели чата».
            _llm = getattr(self, "llm", None)
            _model = str(getattr(_llm, "_chat_model", "") or "") or None
            _base = str(getattr(_llm, "_base_url", "") or "") or None
            return auto_budget.resolve_evidence_tool_window(
                kind, call_budget_chars=budget, turn_spent_chars=spent,
                model=_model, base_url=_base)
        except Exception:      # pragma: no cover - защитная ветка
            floor = (auto_budget.SEARCH_RESULT_SOFT_FLOOR
                     if kind == "search" else 0)
            legacy = (auto_budget.LEGACY_SEARCH_MAX_SYMBOLS
                      if kind == "search"
                      else auto_budget.LEGACY_ARTICLE_MAX_SYMBOLS)
            return auto_budget.EvidenceToolWindow(
                kind=str(kind or ""), effective_limit=max(floor, legacy),
                source="legacy", hard_ceiling=legacy, floor=floor)

    def _record_limit(self, ctx: ToolContext, tool: str, truncation,
                      *, stage: str, extra: dict | None = None) -> None:
        """Записать наблюдаемый лимит (out-of-band, R17-safe)."""
        try:
            record = {"tool": tool, "stage": stage}
            record.update(truncation.as_event_fields())
            if extra:
                record.update({k: v for k, v in extra.items()
                               if isinstance(v, (str, int, float, bool))})
            bucket = getattr(ctx, "evidence_limits", None)
            if isinstance(bucket, list):
                bucket.append(record)
            logger.info(
                "[tools] evidence window | tool=%s | limit=%s | source=%s | "
                "used=%s/%s | truncated=%s | why=%s | remainder=%s",
                tool, record.get("effective_limit"), record.get("limit_source"),
                record.get("used"), record.get("total"),
                record.get("truncated"), record.get("why") or "-",
                record.get("retrievable_remainder"))
        except Exception:      # pragma: no cover - защитная ветка
            pass

    @staticmethod
    def _claim_keys(ctx: ToolContext, arguments: dict) -> list:
        """Claim-key текущего хода (§1.6/§3.2): аргумент → ctx → пусто.

        Ключи приходят из существующей аннотации L1 (`external_claims`) через
        `ctx.claim_keys` (ставит policy-слой) либо явным аргументом
        ``claim``/``claims``. Невалидные элементы отбрасываются."""
        raw_items: list = []
        args = arguments if isinstance(arguments, dict) else {}
        for name in ("claim", "claims", "claim_keys"):
            value = args.get(name)
            if isinstance(value, (list, tuple)):
                raw_items.extend(value)
            elif isinstance(value, dict):
                raw_items.append(value)
            elif isinstance(value, str) and value.strip():
                raw_items.append(value)
        for name in ("claim_keys", "claims", "external_claims"):
            value = getattr(ctx, name, None)
            if isinstance(value, (list, tuple)):
                raw_items.extend(value)
        keys: list = []
        for item in raw_items:
            key = None
            if isinstance(item, str) and "|" in item:
                parts = [part.strip() for part in item.split("|")]
                parts += [""] * (5 - len(parts))
                key = source_reuse.claim_key(parts[0], parts[1], parts[2],
                                             parts[3], parts[4])
            elif not isinstance(item, str):
                key = source_reuse.claim_key_from_mapping(item)
            if key is not None and all(key.key() != existing.key()
                                       for existing in keys):
                keys.append(key)
        return keys

    @staticmethod
    def _reuse_bypass(arguments: dict, ctx: ToolContext) -> bool:
        """Явная просьба «обнови/проверь заново» → bypass кеша (§3.3)."""
        args = arguments if isinstance(arguments, dict) else {}
        for name in ("refresh", "force_refresh", "no_cache"):
            if args.get(name):
                return True
        return bool(getattr(ctx, "force_refresh", False))

    def _reuse_search(self, arguments: dict, ctx: ToolContext) -> str | None:
        """Поиск по уже прочитанному claim-bound источнику без сети.

        Возвращает готовый текст выдачи с машинной строкой ``reuse:`` либо
        ``None`` (тогда выполняется обычный поиск)."""
        keys = self._claim_keys(ctx, arguments)
        if not keys:
            return None
        bypass = self._reuse_bypass(arguments, ctx)
        chat_id = getattr(ctx, "chat_id", None)
        records = []
        for key in keys:
            record = source_reuse.lookup(key, scope="public", chat_id=chat_id,
                                          bypass=bypass)
            if record is not None:
                records.append(record)
        if not records:
            return None
        blocks: list[str] = []
        for record in records:
            title = (record.snippet.splitlines()[0] if record.snippet else "")
            snippet = record.snippet[:600]
            # Дата публикации уже прочитанного источника: reuse дату НЕ
            # выдумывает и сети не делает — берёт сохранённое поле записи.
            published = normalise_publication_date(
                getattr(record, "published_at", ""))
            blocks.append("\n".join(part for part in
                                    (title, snippet,
                                     (f"{_SEARCH_PUBLISHED_LABEL} {published}"
                                      if published else ""),
                                     record.url) if part))
        query = str(arguments.get("query") or getattr(ctx, "query", "") or "")
        lines = [source_reuse.reuse_line(record) for record in records]
        bucket = getattr(ctx, "evidence_limits", None)
        if isinstance(bucket, list):
            bucket.append({
                "tool": "execute_web_search", "stage": "retrieve",
                "reused": True, "network_calls": 0,
                "reuse_count": len(records),
                "source_read_level": records[0].read_level,
                "limit_source": "reuse",
                "effective_limit": 0, "used": 0, "total": 0,
                "truncated": False, "why": "", "retrievable_remainder": 0,
                "unit": "blocks"})
        logger.info("[tools] web search skipped (reuse) | claims=%d",
                    len(records))
        return (f"Результаты поиска по запросу «{query}» (reuse):\n"
                + "\n\n".join(blocks) + "\n\n" + "\n".join(lines))

    # ── execute_web_search ────────────────────────────────────────

    async def _execute_web_search(self, arguments: dict,
                                  ctx: ToolContext) -> str:
        """Поиск = индекс кандидатов (§4.3): URL не теряются при упаковке."""
        query = self._require_query(arguments, ctx)
        window = self._evidence_window("search", ctx)
        # §4.5: тот же проверенный claim с готовым источником → 0 новых
        # сетевых вызовов (повторный identical Search — ненужная работа).
        reuse = self._reuse_search(arguments, ctx)
        if reuse is not None:
            return reuse
        try:
            # ASAP-EVIDENCE-ROUTING-01 v3 (limits-audit.md №1): агрегатору
            # отдаётся технический ceiling, а НЕ 4000 — иначе его собственный
            # слепой срез терял бы URL до нашей структурной упаковки. Ровно
            # один содержательный лимит — ниже, по индексу кандидатов.
            text = await asyncio.wait_for(
                self.deps.search.search(query,
                                        max_symbols=window.hard_ceiling
                                        or window.effective_limit),
                timeout=_SEARCH_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return ("ОШИБКА execute_web_search: поиск недоступен (timeout)")
        except AllSearchEnginesFailedException as exc:
            return f"ОШИБКА execute_web_search: поиск недоступен ({exc})"
        except Exception as exc:      # FR-11: любой сбой — структурированный текст
            logger.warning("[tools] web search failed | query=%r | error=%s",
                           query, f"{type(exc).__name__}: {exc}")
            return (f"ОШИБКА execute_web_search: поиск недоступен "
                    f"({type(exc).__name__})")
        if not text or not str(text).strip():
            return f"ОШИБКА execute_web_search: поиск недоступен (empty result)"
        truncation = _compact_search_candidates(
            str(text), window.effective_limit, source=window.source)
        self._record_limit(
            ctx, "execute_web_search", truncation, stage="retrieve",
            extra={"window_source": window.window_source,
                   "capacity_source": window.capacity_source,
                   "turn_capped": window.turn_capped,
                   # Поиск — только кандидаты (§4.4): страница НЕ прочитана.
                   "source_read_level": source_reuse.READ_LEVEL_SNIPPET})
        return (f"Результаты поиска по запросу «{query}»:\n{truncation.text}")

    # ── query_chat_memory ─────────────────────────────────────────

    async def _query_chat_memory(self, arguments: dict, ctx: ToolContext) -> str:
        query = self._require_query(arguments, ctx)
        stats_arg = arguments.get("stats")
        if (mca_gates.chat_statistics_enabled()
                and isinstance(stats_arg, dict) and stats_arg):
            # MCA-15 (T-4929, ADR-1028-12 D3): структурированный stats-режим
            # существующего инструмента (canon 12 не меняется). K1 OFF →
            # прежний путь байт-в-байт.
            return await self._query_chat_memory_stats(arguments, stats_arg,
                                                       ctx)
        # P0-DELTA (дефект 4): author в ОБЫЧНОМ режиме — тот же единый
        # резолв субъекта, что в stats/dig (Telegram uid → «me/self» = uid
        # говорящего → алиас/имя set-семантикой). Не найден/неоднозначен →
        # честный unsupported: поиск без фильтра автора не выполняется,
        # чужие сообщения не выдаются за сообщения субъекта.
        author_ids: tuple[int, ...] = ()
        author_arg = self._dig_person_text(arguments.get("author"))
        if author_arg is not None:
            uid, detail, _terms = self._resolve_person_identity(author_arg,
                                                                ctx)
            if uid is None:
                return self._identity_unsupported_payload(
                    "query_chat_memory", "author", author_arg, detail)
            author_ids = (uid,)
        # P0-DELTA (дефект 2): произвольный период year_from/year_to (годы)
        # пересекается с legacy time_range (since = max). Инвалидный явный
        # период → честный unsupported, не молчаливое игнорирование.
        time_range, since, until, year_from, year_to, invalid = \
            self._parse_memory_period(arguments)
        if invalid:
            return self._period_unsupported_payload(year_from, year_to)
        lines: list[str] = []
        indirect_lines: list[str] = []

        # 1. FTS по L1-сообщениям (search_long_term): фильтры окна/автора —
        # В SQL ДО LIMIT (P0-DELTA дефект 3: top-40 по rank больше не съедает
        # узкое окно/автора пост-фильтром; пост-фильтр ниже — страховка для
        # memory-заглушек без SQL-фильтров). Новые kwargs передаются только
        # при реально заданном фильтре: дефолтный вызов — прежний байт-в-байт.
        search_kwargs: dict = {}
        if since:
            search_kwargs["since_ts"] = since
        if until:
            search_kwargs["until_ts"] = until
        if author_ids:
            search_kwargs["author_ids"] = author_ids
        rows = await self.deps.memory.search_long_term(
            ctx.chat_id, keywords(query), limit=_MEMORY_FTS_LIMIT,
            **search_kwargs)
        # T-678 (прод-лог): реальные строки — aiosqlite.Row, у которого НЕТ
        # .get (AttributeError в проде) → нормализация в dict ДО обработки.
        rows = [dict(row) for row in rows]
        for row in rows:
            ts = int(row.get("timestamp") or 0)
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            name = self._resolve_name(row)
            ts_fmt = _format_timestamp(row.get("timestamp"))
            stamp = f" [{ts_fmt}]" if ts_fmt else ""
            text = str(row.get("text") or "").strip()
            if text:
                lines.append(f"[{name}{stamp}]: {text}")
        fts_shown = len(lines)

        # 1b. Счётчик + диапазон дат (best-effort; ошибка не роняет результат)
        # — ТЕ ЖЕ фильтры, что у сниппетов (один источник, показ и число
        # согласованы). `since_ts` — легаси-kwargs, новые — при фильтре.
        stats = None
        try:
            count_kwargs: dict = {"since_ts": since}
            if until:
                count_kwargs["until_ts"] = until
            if author_ids:
                count_kwargs["author_ids"] = author_ids
            stats = await self.deps.memory.count_mentions(
                ctx.chat_id, keywords(query), **count_kwargs)
        except Exception:
            logger.warning("[tools] query_chat_memory count failed | query=%r",
                           query, exc_info=True)
        if isinstance(stats, dict) and stats.get("count"):
            logger.info("[tools] query_chat_memory | query=%r | count=%d | since_ts=%d",
                        query, stats["count"], since)

        # 2. Векторный поиск по фактам архива/графа (только широкие окна и
        # БЕЗ фильтра автора: vector/RAG не умеют фильтровать по автору —
        # честно не смешиваем). P0-DELTA (дефект 5/provenance): производные
        # факты — обобщения/пересказы, рендерятся отдельным маркированным
        # блоком, не как дословные сообщения.
        if not lines and not author_ids \
                and time_range in ("last_month", "all"):
            facts = await self.deps.memory.vector_search(
                ctx.chat_id, query, limit=_MEMORY_VEC_LIMIT)
            indirect_lines.extend(str(fact).strip() for fact in facts
                                  if str(fact).strip())

        # 3. Гибридный RAG-контекст, если всё ещё пусто (тот же запрет
        # смешивания при фильтре автора).
        if not lines and not indirect_lines and not author_ids:
            # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
            rag = await self.deps.memory.get_rag_context(
                ctx.chat_id, query, sort_by_timestamp=True)
            if rag and str(rag).strip():
                indirect_lines.append(str(rag).strip())

        if not lines and not indirect_lines and not \
                (isinstance(stats, dict) and stats.get("count")):
            return f"По запросу «{query}» в памяти ничего не найдено."
        parts: list[str] = []
        if isinstance(stats, dict) and stats.get("count"):
            period = _TIME_RANGE_LABELS.get(time_range, "за всё время")
            if year_from is not None or year_to is not None:
                period = self._period_label(year_from, year_to, period)
            stamp = ""
            if stats.get("first_seen") or stats.get("last_seen"):
                first = _format_timestamp(stats.get("first_seen"))
                last = _format_timestamp(stats.get("last_seen"))
                if first and last and first != last:
                    stamp = f" (с {first} по {last})"
            if mca_gates.chat_statistics_enabled():
                # MCA-15 (T-4926, §24.1 п.6): широкий prefix-OR-счёт больше
                # не выдаётся за точное число «упоминаний»: единица (сообщения)
                # и метод (префиксы, не морфология) названы явно.
                parts.append(
                    f"Широкий поиск (префиксы, не морфология): "
                    f"{stats['count']} сообщений «{query}» {period}{stamp}")
            else:
                parts.append(
                    f"Найдено {stats['count']} упоминаний «{query}» "
                    f"{period}{stamp}")
            # P0-DELTA (дефект 3): честное покрытие показа — счётчик
            # корпус-полный, сниппеты — верх по релевантности; модель не
            # принимает показанное за весь корпус.
            if fts_shown and int(stats["count"]) > fts_shown:
                parts.append(
                    f"Показано {fts_shown} из {stats['count']} сообщений "
                    f"(верх по релевантности); при необходимости сузь "
                    f"период или автора.")
        parts.extend(lines)
        if indirect_lines:
            parts.append("Контекст из памяти (обобщённые факты и пересказ, "
                         "не дословные сообщения):")
            parts.extend(indirect_lines)
        return _truncate("\n".join(parts), _MEMORY_MAX_SYMBOLS)

    # ── query_chat_memory stats-режим (MCA-15 T-4929, ADR-1028-12 D3/D4) ──

    def _resolve_author_id(self, name: str) -> tuple[int | None, str]:
        """Имя/алиас → канонический user_id (mca-03-контур, без второго
        identity). Неоднозначность/ненайденность → (None, detail) —
        `ambiguous_identity`, без угадывания и без слияния по имени."""
        mapping = getattr(self.deps.aliases, "_aliases", None)
        low = str(name or "").strip().casefold()
        matches: set[int] = set()
        if isinstance(mapping, dict) and low:
            for key, value in mapping.items():
                if str(value).casefold() != low:
                    continue
                try:
                    matches.add(int(key))
                except (TypeError, ValueError):
                    continue
        if len(matches) == 1:
            return matches.pop(), ""
        return None, ("author_ambiguous" if len(matches) > 1
                      else "author_unresolved")

    # ── P0-DELTA (26.10.2026, дефекты 2/4 аудита p0-delta-analysis) ─────

    def _resolve_person_identity(self, raw, ctx: ToolContext
                                 ) -> tuple[int | None, str, list[str]]:
        """Единый резолв субъекта анализа для author/person-аргументов
        инструментов памяти (дефект 4: «искать по Telegram ID, а не имени»).

        Порядок: Telegram uid («123», «id:123», «user:123») → «me/self/я» =
        uid говорящего (``ctx.user_id``) → алиас/имя (set-семантика
        `_resolve_author_id`: ровно одно совпадение; 0 → author_unresolved;
        >1 → author_ambiguous — похожие ники НЕ сливаются, «первое
        совпадение побеждает» устранено).

        Возвращает (uid|None, detail, name_terms): name_terms — OR-токены
        имени (для facts/target_user-фильтров); у uid/me — пусто (вызывающий
        добавляет каноническое имя резолвенного uid). Никогда не бросает."""
        text = str(raw or "").strip()
        if not text:
            return None, "", []
        low = text.casefold()
        if low in _ME_ALIASES:
            uid = getattr(ctx, "user_id", None)
            try:
                uid = int(uid) if uid is not None else None
            except (TypeError, ValueError):
                uid = None
            if uid is None:
                return None, "caller_unknown", []
            return uid, "", []
        m = _UID_RE.match(low)
        if m:
            return int(m.group(1)), "", []
        resolved, detail = self._resolve_author_id(text)
        return resolved, detail, keywords(text)

    @staticmethod
    def _identity_unsupported_payload(tool: str, argument: str, value: str,
                                      detail: str) -> str:
        """Дефект 4: честный JSON-отказ, когда субъект анализа НЕ
        идентифицирован. Фильтр автора не исчезает молча (прежний путь
        превращал имя в OR-токены и выдавал упоминания разными людьми за
        «сообщения субъекта»); поиск без фильтра не выполняется. Reasons —
        существующий словарь идентичности (stats-контракт)."""
        message = {
            "author_ambiguous":
                f"«{value}» соответствует нескольким участникам чата "
                f"(похожие имена не объединяются): уточни точное "
                f"имя/алиас или укажи Telegram id",
            "caller_unknown":
                "«мои сообщения»: на этом ходу неизвестен uid говорящего",
        }.get(detail,
              f"субъект «{value}» не найден в алиасах чата: фильтр по "
              f"автору НЕ применён; уточни точное имя/алиас, укажи "
              f"Telegram id (или «me») либо убери {argument} для поиска "
              f"по упоминаниям разными людьми")
        return json.dumps({
            "status": "unsupported",
            "reason": (detail or "subject_unresolved"),
            "tool": tool,
            "argument": argument,
            "value": value,
            "message": message,
        }, ensure_ascii=False)

    @staticmethod
    def _optional_year(raw) -> tuple[int | None, bool]:
        """(year|None, was_given) для period-параметров инструментов памяти
        (дефект 2). Отсутствует/пусто → (None, False). Присутствует, но вне
        [2000, текущий] или не число → (None, True) — вызывающий отвечает
        честным unsupported вместо молчаливого игнорирования периода."""
        if raw in (None, ""):
            return None, False
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None, True
        if value < _DIG_YEAR_MIN or value > datetime.datetime.now().year:
            return None, True
        return value, False

    @classmethod
    def _parse_memory_period(cls, arguments: dict) -> tuple:
        """(time_range, since, until, year_from, year_to, invalid) — окно
        инструментов памяти (дефект 2). time_range — legacy enum; годовой
        диапазон year_from/year_to аддитивен: since = max(...), until =
        конец года year_to. Явно инвалидный период (вне диапазона/год_to <
        year_from) → invalid=True (вызывающий отвечает unsupported)."""
        time_range = str(arguments.get("time_range") or "all")
        if time_range not in _TIME_RANGE_SECONDS:
            time_range = "all"
        since = _time_range_since(time_range)
        year_from, given_from = cls._optional_year(arguments.get("year_from"))
        year_to, given_to = cls._optional_year(arguments.get("year_to"))
        invalid = ((given_from and year_from is None)
                   or (given_to and year_to is None)
                   or (year_from is not None and year_to is not None
                       and year_to < year_from))
        if year_from is not None:
            start = cls._year_bounds(year_from)[0]
            since = max(since, start) if since else start
        until = cls._year_bounds(year_to)[1] if year_to is not None else 0
        return time_range, since, until, year_from, year_to, invalid

    @staticmethod
    def _period_unsupported_payload(year_from, year_to) -> str:
        """Честный отказ на инвалидный период (дефект 2): окно не исчезает
        молча, модель может повторить с валидными годами."""
        return json.dumps({
            "status": "unsupported",
            "reason": "invalid_period",
            "period": {"year_from": year_from, "year_to": year_to},
            "message": ("период задан неверно: годы вне [2000, текущий] "
                        "или year_to раньше year_from; повтори с "
                        "year_from <= year_to"),
        }, ensure_ascii=False)

    @staticmethod
    def _period_label(year_from, year_to, fallback: str) -> str:
        """Человечная метка явного периода для заголовка счётчика."""
        if year_from is not None and year_to is not None:
            if year_from == year_to:
                return f"за {year_from} год"
            return f"за {year_from}-{year_to} годы"
        if year_from is not None:
            return f"с {year_from} года"
        if year_to is not None:
            return f"до {year_to} года"
        return fallback

    @staticmethod
    def _fact_origin_label(row: dict) -> str:
        """Дефект 5 (provenance): метка происхождения факта графа в рендере
        dig — пересказ/вывод не выдаются за дословные сообщения и за
        независимые свидетельства. Неизвестный origin — сам origin; пустой —
        честная «память»."""
        origin = str(row.get("origin") or "").strip()
        if not origin:
            return "[память]"
        return _DIG_FACT_ORIGIN_LABELS.get(origin, f"[{origin}]")

    @staticmethod
    def _stats_unsupported_payload(metric: str, reason: str,
                                   detail: str = "") -> str:
        """Честный structured-отказ stats-режима (не число и не ноль)."""
        payload = {
            "status": "unsupported",
            "value": None,
            "unit": {"messages": "messages", "occurrences": "occurrences",
                     "distinct_authors": "authors"}.get(metric, metric),
            "reason": reason,
        }
        if detail:
            payload["scope"] = {"detail": detail}
        return json.dumps(payload, ensure_ascii=False)

    async def _query_chat_memory_stats(self, arguments: dict,
                                       stats_arg: dict,
                                       ctx: ToolContext) -> str:
        """Stats-режим (T-4929/D3): одна нормализованная спека → `measure()`
        → типизированный JSON + `MetricResult` в `ctx.metric_results`
        (источник NumericClaim хода). Никогда не бросает."""
        from services import chat_statistics as _cs
        db = self.deps.db if self.deps.db is not None \
            else getattr(self.deps.memory, "db", None)
        metric = str(stats_arg.get("metric") or _cs.METRIC_MESSAGES).strip()
        match_mode = str(stats_arg.get("match_mode")
                         or _cs.MATCH_TOKEN).strip()
        phrase = str(stats_arg.get("phrase")
                     or arguments.get("query") or "").strip()
        raw_terms = stats_arg.get("terms")
        terms: tuple[str, ...] = ()
        if isinstance(raw_terms, (list, tuple)):
            terms = tuple(str(t).strip() for t in raw_terms
                          if str(t or "").strip())
        if match_mode == _cs.MATCH_EXACT_PHRASE:
            text, query_terms = phrase, ()
        else:
            text = ""
            query_terms = ((phrase,) if phrase else ()) + terms
        quote_forward = str(stats_arg.get("quote_forward")
                            or _cs.QUOTE_INCLUDE).strip()
        sender = str(stats_arg.get("sender") or _cs.SENDER_ANY).strip()
        # P0-DELTA (дефект 2): годовой диапазон в точной статистике — те же
        # year_from/year_to, что в обычном режиме (interval_to SQL-фильтр).
        time_range, since, until, year_from, year_to, invalid = \
            self._parse_memory_period(arguments)
        if invalid:
            return self._stats_unsupported_payload(
                metric, "invalid_period",
                f"year_from={year_from} year_to={year_to}")
        author_ids: tuple[int, ...] = ()
        author_name = str(stats_arg.get("author") or "").strip()
        if author_name:
            # P0-DELTA (дефект 4): тот же единый резолв субъекта (uid →
            # «me/self» → алиас/имя). R16/mca-03: имя — подпись, не ключ;
            # не угадываем и не сливаем двух людей. Reason — существующий
            # `ambiguous_identity` (detail различает
            # ambiguous/unresolved/caller_unknown).
            resolved, detail, _terms = self._resolve_person_identity(
                author_name, ctx)
            if resolved is None:
                _mca_events.emit_mca_event(
                    "chat_statistics", outcome="skipped",
                    component="tool_router", stage="measurement",
                    reason_code="ambiguous_identity", chat_id=ctx.chat_id)
                return self._stats_unsupported_payload(
                    metric, "ambiguous_identity", detail)
            author_ids = (resolved,)
        if db is None:
            return self._stats_unsupported_payload(
                metric, _cs.REASON_STATS_UNSUPPORTED, "db_unavailable")
        query = _cs.StatsQuery(
            chat_id=ctx.chat_id, metric=metric, match_mode=match_mode,
            text=text, terms=query_terms, author_ids=author_ids,
            interval_from=(since or None), interval_to=(until or None),
            quote_forward=quote_forward,
            sender_kinds=sender)
        try:
            result = await _cs.measure(db, query)
        except Exception as exc:      # measure не бросает, но не доверяем
            logger.warning("[tools] stats measure failed | error=%s",
                           type(exc).__name__)
            return self._stats_unsupported_payload(
                metric, _cs.REASON_STATS_COUNT_ERROR, "measure_failed")
        metric_result = _cs.build_metric_result(result, query)
        ctx.metric_results.append(metric_result)
        _cs.emit_measurement_event(metric_result, chat_id=ctx.chat_id,
                                   intent=ctx.stats_intent)
        payload = _cs.metric_result_payload(result, query,
                                            metric_result=metric_result)
        return _stats_json_payload(payload, _MEMORY_MAX_SYMBOLS)

    # ── dig_into_lore (раунд 9, AGI Memory T-820, spec §3.2.1/Q6) ────────

    async def _dig_into_lore(self, arguments: dict, ctx: ToolContext) -> str:
        """Глубокое копание в историю чата: FTS5-сниппеты L1 с датами
        (mode messages/both) + факты графа (mode facts/both); пост-фильтры
        периода (year / «N лет назад» из query) и участника (person, с
        расширением именами из граф-обхода nodes/edges). НЕ бросает: ошибка
        этапа → WARNING, секция пуста; всё пусто → «ничего не нашёл по
        запросу»; флаг flags.dig_enabled=false → строка отключения."""
        if not hot.get("flags.dig_enabled", settings.DIG_ENABLED):
            return "Инструмент dig_into_lore отключен."
        # EVOL v5 (§4.1 P5): результаты копания — тоже речевая поверхность
        # (модель пересказывает их в ответе); берём ОБЩУЮ проекцию хода.
        _speech = getattr(ctx, "speech", None)
        query = self._require_query(arguments, ctx)
        mode = str(arguments.get("mode") or "both").strip().lower()
        if mode not in ("messages", "facts", "both"):
            logger.warning("[tools] dig mode invalid - default 'both' | "
                           "mode=%r", mode)
            mode = "both"
        year = self._dig_year(arguments.get("year"))
        if year is None:
            # major-2(а): query «(\d+|несколько|пару) лет назад» без year →
            # год = now.year − N (spec §3.2.1 п.3(б), фикс-раунд).
            year = self._dig_year_from_query(query)
        # P0-DELTA (дефект 2): опциональный year_to — период [year..year_to],
        # а не один календарный год (многолетний диапазон выразим без
        # второго роутера). Инвалидный явный период → честный unsupported.
        year_to = None
        year_to_raw = arguments.get("year_to")
        if year_to_raw not in (None, ""):
            year_to = self._dig_year(year_to_raw)
            if year_to is None:
                return json.dumps({
                    "status": "unsupported", "reason": "invalid_period",
                    "message": "year_to указан, но вне диапазона [2000, "
                               "текущий год]; повтори с валидным годом"},
                    ensure_ascii=False)
        bounds = self._year_bounds(year) if year is not None else None
        if year is not None and bounds is None:
            logger.warning("[tools] dig year вне диапазона | year=%s", year)
        if year_to is not None:
            if year is not None and year_to < year:
                return json.dumps({
                    "status": "unsupported", "reason": "invalid_period",
                    "message": f"период задан неверно: year_to ({year_to}) "
                               f"раньше year ({year}); нужен year <= year_to"},
                    ensure_ascii=False)
            start = bounds[0] if bounds else 0
            bounds = (start, self._year_bounds(year_to)[1])
        person = self._dig_person_text(arguments.get("person"))
        # P0-DELTA (дефект 4): единый резолв субъекта (Telegram uid →
        # «me/self» = uid говорящего → алиас/имя set-семантикой, дубликаты
        # имён обнаруживаются). Ненайден/неоднозначен → честный unsupported:
        # фильтр автора НЕ исчезает молча и имя не превращается в OR-токены
        # (чужие сообщения не выдаются за сообщения субъекта).
        person_uid = None
        person_terms: list[str] = []
        if person is not None:
            person_uid, person_detail, person_terms = \
                self._resolve_person_identity(person, ctx)
            if person_uid is None:
                return self._identity_unsupported_payload(
                    "dig_into_lore", "person", person, person_detail)
            # каноническое имя резолвенного uid — в name-формы для
            # facts/target_user-фильтров (uid в тексте не встречается).
            canonical = self._resolve_name(
                {"user_id": person_uid, "author_name": ""})
            for word in keywords(canonical):
                if word and word not in person_terms:
                    person_terms.append(word)
        tokens = keywords(query)
        # Имена-формы (person) расширяют запрос OR-токенами (spec п.2).
        merged = list(dict.fromkeys(tokens + person_terms))
        # MCA-15 (T-4926/T-4927, ADR-1028-12 D1/D3): K1 ON — измерение
        # строится ТОЛЬКО по явным токенам запроса и person-формам;
        # graph-expansion — кандидаты для примеров (через `retrieve()`), НЕ
        # условие измерения. K1 OFF — прежний merged (байт-паритет).
        k1_stats = mca_gates.chat_statistics_enabled()
        # major-2(б): имена из граф-обхода (BFS по nodes/edges глубиной
        # limits.dig_graph_hop_depth; фолбэк target_user) — источник ИМЁН
        # для FTS (spec п.4; best-effort, пусто при любой ошибке).
        graph_names = await self._dig_graph_names(
            ctx, person_terms if person is not None else tokens)
        if graph_names and not k1_stats:
            for name in graph_names:
                for word in keywords(name):
                    if len(word) >= 3 and word not in merged:
                        merged.append(word)
                if len(merged) >= 40:
                    break
        # Условие измерения: K1 ON — без graph-expansion; K1 OFF — как было.
        measurement_tokens = (list(dict.fromkeys(tokens + person_terms))
                              if k1_stats else list(merged))

        dig_max_symbols = int(hot.get("limits.dig_max_symbols",
                                      settings.DIG_MAX_SYMBOLS)
                              or settings.DIG_MAX_SYMBOLS)
        max_snippets = int(hot.get("limits.dig_max_snippets",
                                   settings.DIG_MAX_SNIPPETS)
                           or settings.DIG_MAX_SNIPPETS)
        max_facts = int(hot.get("limits.dig_max_facts",
                                settings.DIG_MAX_FACTS)
                        or settings.DIG_MAX_FACTS)

        msg_lines: list[str] = []
        fact_lines: list[str] = []
        seen_texts: set[str] = set()
        stage_error = None
        count_status = "ok"
        total_mentions = 0
        mentions_by_authors: dict[str, int] = {}
        authors_list: list[dict] = []
        first_seen = None
        last_seen = None
        if not merged:
            if k1_stats:
                return self._dig_not_found(query, stats_block={
                    "status": "unsupported", "value": None,
                    "unit": "messages", "method": "", "method_label": "",
                    "scope": {"chat_id": ctx.chat_id,
                              "corpus": "smart_messages"},
                    "coverage": "unknown", "reason": "stats_unsupported"})
            return self._dig_not_found(query)
        # (в) mode messages/both: FTS5 по smart_messages (search_long_term) +
        #     пост-фильтр периода/user_id; рендер «[Имя YYYY-MM-DD]: текст».
        if mode in ("messages", "both"):
            try:
                # P0-DELTA (дефекты 2-3): фильтры окна/автора — В SQL ДО
                # LIMIT (top-40 по rank больше не теряет старые периоды и
                # сообщения персоны); пост-фильтры ниже — страховка для
                # memory-заглушек без SQL-фильтров. Новые kwargs — только
                # при заданном фильтре (дефолтный вызов прежний).
                dig_search_kwargs: dict = {}
                if bounds:
                    dig_search_kwargs["since_ts"] = bounds[0]
                    dig_search_kwargs["until_ts"] = bounds[1]
                    # VMQ-MEM (дефект 3 измерения 2.58.179): окно периода
                    # обслуживается bounded-планом (`order="time"`: диапазон
                    # `idx_smart_messages_chat_ts` + один проход doclist'ов
                    # FTS). Rank-план читал content-таблицу на КАЖДОЕ
                    # совпадение корпуса и на 2,07 млн сообщений не
                    # укладывался в бюджет запроса. Порядок тогда — по
                    # времени; это названо в payload (`coverage.sampling`).
                    dig_search_kwargs["order"] = "time"
                if person_uid is not None:
                    dig_search_kwargs["author_ids"] = (person_uid,)
                rows = await self.deps.memory.search_long_term(
                    ctx.chat_id, merged, limit=_MEMORY_FTS_LIMIT,
                    **dig_search_kwargs)
                rows = [dict(row) for row in rows]     # T-678: aiosqlite.Row
                for row in rows:
                    ts = int(row.get("timestamp") or 0)
                    if bounds and not (bounds[0] <= ts <= bounds[1]):
                        continue
                    if person_uid is not None and \
                            int(row.get("user_id") or 0) != person_uid:
                        continue
                    text = str(row.get("text") or "").strip()
                    if not text or text in seen_texts:
                        continue
                    seen_texts.add(text)
                    name = self._resolve_name(row)
                    # 10.20 (БЛОК 2.8, ADR-1020-2 п.2): канонический рендер
                    # строки контекста (§2.2, kind="msg") — дата ВРЕМЯ | автор
                    # | ID (tg:→msg:) | Переслано.
                    item_id = resolve_item_id(
                        tg_message_id=row.get("tg_message_id"),
                        message_id=row.get("id"))
                    forward_source = (row.get("forward_source")
                                      if row.get("is_forward") else None)
                    if _speech is not None and speech_projection_enabled():
                        msg_lines.append(format_speech_item(
                            ts=ts, author=name,
                            author_uid=row.get("user_id"), item_id=item_id,
                            forward_source=forward_source, text=text,
                            kind="msg", projection=_speech))
                    else:
                        msg_lines.append(format_context_item(
                            ts=ts, author=name, item_id=item_id,
                            forward_source=forward_source, text=text,
                            kind="msg"))
                    if len(msg_lines) >= max_snippets:
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_error = f"{type(exc).__name__}"
                logger.warning("[tools] dig messages failed | query=%r | "
                               "error=%s", query, stage_error, exc_info=True)
        # MCA-15 (T-4927, L-MCA07-5): graph-expansion — кандидаты ТОЛЬКО
        # через единую точку mca-07 `retrieve()`; второй комбинированный
        # retrieval не создаётся, условие измерения НЕ меняется.
        if k1_stats and graph_names and mode in ("messages", "both"):
            try:
                from services import chat_statistics as _cs
                expansion = await _cs.collect_candidates(
                    getattr(self.deps.memory, "db", None), self.deps.memory,
                    chat_id=ctx.chat_id, query=query,
                    top_k=max(1, max_snippets), mode="history",
                    time_from=bounds[0] if bounds else None,
                    time_to=bounds[1] if bounds else None,
                    participants=((person_uid,) if person_uid is not None
                                  else ()))
                for cand in expansion.candidates or ():
                    if len(msg_lines) >= max_snippets:
                        break
                    if cand.entity_type != "message" or not cand.preview:
                        continue
                    if person_uid is not None and cand.author_id is not None \
                            and int(cand.author_id) != person_uid:
                        continue
                    text = str(cand.preview).strip()
                    if not text or text in seen_texts:
                        continue
                    seen_texts.add(text)
                    if _speech is not None and speech_projection_enabled():
                        msg_lines.append(format_speech_item(
                            ts=cand.sent_at,
                            author=self._resolve_name(
                                {"user_id": cand.author_id,
                                 "author_name": ""}),
                            author_uid=cand.author_id,
                            item_id=cand.id, text=text, kind="msg",
                            projection=_speech))
                    else:
                        msg_lines.append(format_context_item(
                            ts=cand.sent_at,
                            author=self._resolve_name(
                                {"user_id": cand.author_id, "author_name": ""}),
                            item_id=cand.id, text=text, kind="msg"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[tools] dig expansion candidates failed | "
                               "error=%s", type(exc).__name__)
        # (г) mode facts/both: FTS по graph_facts (v7-совместимо: колонки v8
        #     не используются); пост-фильтр периода и target_user (person).
        if mode in ("facts", "both"):
            try:
                db = getattr(self.deps.memory, "db", None)
                if db is not None and hasattr(db, "search_graph_facts_fts"):
                    from services.summary_memory import (
                        _stale_suffix,
                        build_fts_query,
                    )
                    match = build_fts_query(merged)
                    if match:
                        # F2/T-1426 (spec §2): dig_into_lore — прямое копание,
                        # архивные beliefs участвуют (include_archived=True).
                        rows = await db.search_graph_facts_fts(
                            ctx.chat_id, match,
                            limit=max_facts * 3,
                            now_ts=int(time.time()),
                            include_direct_reply=False,
                            include_archived=True)
                        seen_facts: set[str] = set()
                        for row in (dict(r) for r in rows):
                            ts = int(row.get("rag_ts") or 0)
                            if bounds and not (bounds[0] <= ts <= bounds[1]):
                                continue
                            if person is not None:
                                target = str(row.get("target_user") or "").strip()
                                if not target or not any(
                                        term in target.casefold()
                                        for term in person_terms):
                                    continue
                            text = str(row.get("fact") or "").strip()
                            if not text or text in seen_facts:
                                continue
                            seen_facts.add(text)
                            # 10.20 (БЛОК 2.8, ADR-1020-2 п.2): единый
                            # канонический рендер факта (§2.2, kind="fact"):
                            # «[ММ.ГГГГ | Автор | fact:ID]: текст (+ устарело)».
                            # Автор — target_user строки (R16, не выдумываем).
                            # P0-DELTA (дефект 5/provenance): метка
                            # происхождения — пересказ/вывод бота не
                            # выдаются за дословные сообщения и независимые
                            # свидетельства; архивные убеждения помечены.
                            ts_render = ts if ts else None
                            if _speech is not None and \
                                    speech_projection_enabled():
                                line = format_speech_item(
                                    ts=ts_render,
                                    author=row.get("target_user"),
                                    item_id=resolve_item_id(
                                        fact_id=row.get("id")),
                                    text=text, kind="fact",
                                    stale=bool(_stale_suffix(ts_render)),
                                    projection=_speech)
                            else:
                                line = format_context_item(
                                    ts=ts_render,
                                    author=row.get("target_user"),
                                    item_id=resolve_item_id(
                                        fact_id=row.get("id")),
                                    text=text, kind="fact",
                                    stale=bool(_stale_suffix(ts_render)))
                            if str(row.get("status") or "") \
                                    == "archived_belief":
                                line = f"{line} (архивное убеждение)"
                            elif str(row.get("status") or "") \
                                    == "archived_fact":
                                # P0-квота: вытеснено квотой без удаления —
                                # в историческом копании помечаем как архив.
                                line = f"{line} (архивный факт)"
                            fact_lines.append(
                                f"{self._fact_origin_label(row)} {line}")
                            if len(fact_lines) >= max_facts:
                                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_error = f"{type(exc).__name__}"
                logger.warning("[tools] dig facts failed | query=%r | "
                               "error=%s", query, stage_error, exc_info=True)
        # (д) 10.20 (БЛОК 2.8, ADR-1020-2 п.2): агрегация упоминаний по
        # авторам — GROUP BY в SQL, имя резолвится тем же R16-каскадом
        # (_resolve_name). Считается по окну year (since/until).
        # MCA-15 (T-4926): K1 ON — счётчик применяет ТЕ ЖЕ фильтры, что
        # сниппеты (person_uid, окно года); graph-expansion в измерение НЕ
        # входит; ошибка счётчика — отдельный статус `stats_count_error`,
        # НЕ ноль (A40); ключ автора — канонический user_id, имя — подпись.
        if mode in ("messages", "both") and merged:
            try:
                db = getattr(self.deps.memory, "db", None)
                counter = getattr(
                    db, "search_messages_fts_count_by_author", None)
                from services.summary_memory import build_fts_query
                match = build_fts_query(measurement_tokens)
                if callable(counter) and match:
                    counter_kwargs = {}
                    if k1_stats and person_uid is not None:
                        counter_kwargs["author_ids"] = (person_uid,)
                    stats = await counter(
                        ctx.chat_id, match,
                        since_ts=bounds[0] if bounds else 0,
                        until_ts=bounds[1] if bounds else 0,
                        **counter_kwargs)
                    total_mentions = int(stats.get("count") or 0)
                    if k1_stats:
                        by_id: dict = {}
                        for entry in stats.get("by_author") or []:
                            uid = entry.get("user_id")
                            label = self._resolve_name(entry)
                            key = (int(uid) if uid is not None
                                   else ("unknown", label))
                            item = by_id.get(key)
                            if item is None:
                                by_id[key] = {
                                    "user_id": uid, "label": label,
                                    "count": int(entry.get("count") or 0)}
                            else:
                                item["count"] += int(
                                    entry.get("count") or 0)
                        authors_list = sorted(
                            by_id.values(),
                            key=lambda a: (-a["count"], str(a["label"])))
                    else:
                        for entry in stats.get("by_author") or []:
                            name = self._resolve_name(entry)
                            mentions_by_authors[name] = (
                                mentions_by_authors.get(name, 0)
                                + int(entry.get("count") or 0))
                    first_seen = _format_timestamp(stats.get("first_seen"))
                    last_seen = _format_timestamp(stats.get("last_seen"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                count_status = "error"
                logger.warning("[tools] dig count failed | query=%r | "
                               "error=%s", query, type(exc).__name__)

        def _dig_coverage() -> dict:
            """Честное покрытие показа (VMQ-MEM, дефект 3): чем именно
            сформирован срез сниппетов и обрезан ли он счётчиком периода."""
            return {
                "messages_total": int(total_mentions),
                "messages_shown": len(msg_lines),
                "facts_shown": len(fact_lines),
                # Без периода сниппеты — верх по релевантности (bm25 FTS5).
                # С периодом запрос идёт bounded-планом по времени
                # (`search_messages_fts(order="time")`: стоимость ∝ окну, а не
                # match-set корпуса) — порядок тогда «последние совпадения
                # периода», и это названо, а не выдано за релевантность.
                "sampling": ("window_scan_by_time" if bounds
                             else "top_by_relevance"),
                "truncated": bool(total_mentions
                                  and len(msg_lines) < int(total_mentions)),
            }

        if k1_stats:
            from services import chat_statistics as _cs
            if mode == "facts":
                # Режим facts не измеряет сообщения: честный unsupported,
                # а не ложный ноль.
                stats_block = {
                    "status": "unsupported", "value": None,
                    "unit": "messages", "method": "", "method_label": "",
                    "scope": {"chat_id": ctx.chat_id,
                              "corpus": "smart_messages"},
                    "coverage": "unknown", "reason": "stats_unsupported",
                }
            else:
                stats_block = {
                    "status": ("error" if count_status == "error" else "ok"),
                    "value": (None if count_status == "error"
                              else int(total_mentions)),
                    "unit": "messages",
                    "method": _cs.FTS_PREFIX_OR_METHOD,
                    "method_label": _cs.method_label(_cs.MATCH_PREFIX),
                    "scope": {"chat_id": ctx.chat_id,
                              "corpus": "smart_messages",
                              "since_ts": bounds[0] if bounds else None,
                              "until_ts": bounds[1] if bounds else None,
                              "person_user_id": person_uid},
                    "coverage": "known_complete",
                    "reason": ("stats_count_error"
                               if count_status == "error" else None),
                }
            # T-4929/T-4934 (D4/D7): измерение dig регистрируется как
            # MetricResult (источник NumericClaim хода) и видно в
            # диагностике; ошибка счётчика — value=None (без claim), ноль —
            # только после успешного расчёта области.
            self._register_dig_measurement(
                ctx, stats_block, measurement_tokens, person_uid, bounds)
            has_material = bool(msg_lines or fact_lines)
            if not has_material and count_status == "error":
                if stage_error:
                    return (f"ОШИБКА dig_into_lore: этап поиска не выполнен "
                            f"({stage_error})")
                result = {
                    "status": "error",
                    "stats": stats_block,
                    "authors": authors_list,
                    "first_seen": first_seen or None,
                    "last_seen": last_seen or None,
                    "snippets": msg_lines,
                    "facts": fact_lines,
                    "message": "счётчик недоступен — число не публикуется",
                }
                return _dig_json_payload(result, dig_max_symbols)
            if not has_material and not total_mentions:
                if stage_error:
                    return (f"ОШИБКА dig_into_lore: этап поиска не выполнен "
                            f"({stage_error})")
                return self._dig_not_found(query, stats_block=stats_block)
            result = {
                "status": ("partial" if count_status == "error" else "ok"),
                "stats": stats_block,
                "authors": authors_list,
                "first_seen": first_seen or None,
                "last_seen": last_seen or None,
                # P0-DELTA (дефект 3): честное покрытие показа — счётчик
                # корпус-полный, сниппеты/факты — верх по релевантности;
                # показанное не выдаётся за весь корпус.
                "coverage": _dig_coverage(),
                "snippets": msg_lines,
                "facts": fact_lines,
            }
            return _dig_json_payload(result, dig_max_symbols)
        if not msg_lines and not fact_lines and not total_mentions:
            if stage_error:
                return (f"ОШИБКА dig_into_lore: этап поиска не выполнен "
                        f"({stage_error})")
            return self._dig_not_found(query)
        result = {
            "total_mentions": total_mentions,
            "mentions_by_authors": mentions_by_authors,
            "first_seen": first_seen or None,
            "last_seen": last_seen or None,
            # P0-DELTA (дефект 3): честное покрытие показа (см. K1-ветку).
            "coverage": _dig_coverage(),
            "snippets": msg_lines,
            "facts": fact_lines,
        }
        return _dig_json_payload(result, dig_max_symbols)

    # ── F8 (раунд 10.15, ADR-1015-3): новые инструменты ──────────────

    async def _summarize_video(self, arguments: dict, ctx: ToolContext) -> str:
        """Выжимка видео (F14, ADR-1024-15 §2.3/§4.5; UPD5 — только
        саммаризация, без `mode`). Источник: http(s)-`url` → ссылочный путь
        (YouTube → каскад; иная ссылка → мультимодальная выжимка); иначе
        нативное видео из `ctx.native_media` (видео-document) → tmp →
        публикация `media_share` + L1/L2 → STT-фолбэк выжимки. Нет источника →
        понятная ОШИБКА. Результат усечён до `_MEMORY_MAX_SYMBOLS`.
        R17: URL/пути не логируются."""
        source, url, native = self._resolve_tool_source(arguments, ctx)
        if source is None:
            # F14 §2.5: OFF → прежняя (до-F14) строка ошибки; ON → понятная
            # «нет источника» (нужна ссылка или видео из реплая).
            if not _native_tools_enabled():
                return "ОШИБКА summarize_video: некорректная ссылка"
            return ("ОШИБКА summarize_video: нет источника "
                    "(нужна ссылка или видео из реплая)")
        service = self.deps.video
        if service is None:
            return "ОШИБКА summarize_video: сервис недоступен"
        try:
            if source == "link":
                text = await asyncio.wait_for(
                    self._video_summary(service, url, ctx),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
            else:
                text = await asyncio.wait_for(
                    self._video_native_summary(service, ctx, native),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] summarize_video timeout | source=%s",
                           source)
            return "ОШИБКА summarize_video: timeout"
        except Exception as exc:
            logger.warning("[tools] summarize_video failed | source=%s | "
                           "error=%s", source, type(exc).__name__)
            return f"ОШИБКА summarize_video: {type(exc).__name__}"
        text = str(text or "").strip()
        if not text:
            return "ОШИБКА summarize_video: пустой результат"
        return _truncate(text, _MEMORY_MAX_SYMBOLS)

    @staticmethod
    async def _video_transcript(service, url: str) -> str:
        """Субтитры YouTube (cap). F14 сохраняет хелпер для F19
        (`transcribe_video`); ссылочный STT/direct — зона F19."""
        video_id = extract_youtube_video_id(url)
        if video_id is None:
            raise ValueError("transcript доступен только для YouTube")
        return await service.engine.fetch_transcript(
            video_id, _SUMMARIZE_TRANSCRIPT_CAP, on_retry=None)

    @staticmethod
    async def _video_summary(service, url: str, ctx: ToolContext) -> str:
        """Ссылочная выжимка: YouTube → каскад выжимки по video_id;
        прямая/платформа → мультимодальная выжимка по video_url."""
        video_id = extract_youtube_video_id(url)
        if video_id is not None:
            return await service.summarize_cascade(video_id,
                                                   chat_id=ctx.chat_id)
        return await service.summarize_media_url(chat_id=ctx.chat_id,
                                                 video_url=url)

    async def _video_native_summary(self, service, ctx: ToolContext,
                                    native) -> str:
        """Нативная выжимка (F14, ADR-1024-15 §2.3): tmp-файл → публикация
        `media_share` → L1/L2 (`summarize_media_url`); при недоступности/пустом
        результате — STT-фолбэк выжимки (`deps.transcriber` +
        `summarize_transcript`). tmp чистится в finally. R17: без URL/путей."""
        path = None
        text = ""
        try:
            path = await native_media.download_to_tmp(
                ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT)
            video_client = getattr(service, "video_client", None)
            if (video_client is not None
                    and getattr(video_client, "available", False)
                    and media_share.enabled()):
                ttl = int(hot.get("limits.media_share_ttl_seconds",
                                  settings.MEDIA_SHARE_TTL_SECONDS) or 0)
                ticket = await media_share.publish_media_file(str(path), ttl)
                if ticket is not None:
                    try:
                        text = await service.summarize_media_url(
                            chat_id=ctx.chat_id, video_url=ticket.abs_url,
                            label="tg-file")
                    except Exception as exc:
                        logger.warning("[tools] native summarize L1/L2 "
                                       "unavailable — STT fallback | error=%s",
                                       type(exc).__name__)
                        text = ""
                    finally:
                        await media_share.delete_file(ticket.file_id)
            if not str(text or "").strip():
                transcript = await self._native_stt(path, native)
                text = await service.summarize_transcript(
                    chat_id=ctx.chat_id, transcript=transcript)
            return text
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _native_stt(self, path, native) -> str:
        """STT нативного видео-файла (F14): `deps.transcriber.transcribe_voice`
        с видео-расширением; нет сервиса → RuntimeError (dispatch → ОШИБКА).
        Таймаут — паритет youtube (`limits.video_stt_timeout_seconds`)."""
        transcriber = getattr(self.deps, "transcriber", None)
        if transcriber is None:
            raise RuntimeError("transcriber unavailable")
        ext = native_media.media_suffix(native).lstrip(".") or "mp4"
        timeout = float(hot.get("limits.video_stt_timeout_seconds",
                                settings.VIDEO_STT_TIMEOUT_SECONDS)
                        or settings.VIDEO_STT_TIMEOUT_SECONDS)
        return await transcriber.transcribe_voice(
            str(path), ext, timeout=timeout)

    # ── F19 (раунд 10.24, ADR-1024-20): transcribe_video (сырой текст) ──

    async def _transcribe_video(self, arguments: dict,
                                ctx: ToolContext) -> str:
        """Сырая транскрибация (F19, ADR-1024-20 §2.2/§2.5): дословный текст
        БЕЗ пересказа. Источник: http(s)-``url`` → ссылочный путь (YouTube →
        субтитры raw, иначе download+STT); иначе нативное медиа из
        ``ctx.native_media`` (video/document/voice/video_note) → fetch → STT.
        Нет источника → понятная ОШИБКА. Результат усечён до
        ``_MEMORY_MAX_SYMBOLS``. НИКОГДА не бросает (контракт dispatch).
        R17: только ``source``/``kind``/``out_chars``/``error=<Class>``."""
        source, url, native = self._resolve_tool_source(
            arguments, ctx, kinds=native_media.MEDIA_KINDS)
        if source is None:
            return ("ОШИБКА transcribe_video: нет источника "
                    "(нужна ссылка или медиа из реплая)")
        kind = getattr(native, "kind", "") if source == "native" else "link"
        try:
            if source == "link":
                text = await asyncio.wait_for(
                    self._link_transcript(url),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
            else:
                text = await asyncio.wait_for(
                    self._native_transcript(ctx, native),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] transcribe_video timeout | source=%s | "
                           "kind=%s", source, kind)
            return "ОШИБКА transcribe_video: timeout"
        except Exception as exc:
            logger.warning("[tools] transcribe_video failed | source=%s | "
                           "kind=%s | error=%s", source, kind,
                           type(exc).__name__)
            return f"ОШИБКА transcribe_video: {type(exc).__name__}"
        text = str(text or "").strip()
        if not text:
            logger.info("[tools] transcribe_video | source=%s | kind=%s | "
                        "out_chars=0", source, kind)
            return "ОШИБКА transcribe_video: пустой результат"
        truncated = _truncate(text, _MEMORY_MAX_SYMBOLS)
        logger.info("[tools] transcribe_video | source=%s | kind=%s | "
                    "out_chars=%d", source, kind, len(truncated))
        return truncated

    async def _link_transcript(self, url: str) -> str:
        """Ссылочный путь: YouTube → субтитры raw (cap); при недоступности
        субтитров (или для direct/platform) → download+STT. R17: без URL в
        логах (только класс ошибки)."""
        video_id = extract_youtube_video_id(url)
        if video_id is not None and self.deps.video is not None:
            try:
                return await self._video_transcript(self.deps.video, url)
            except Exception as exc:
                logger.warning(
                    "[tools] transcribe_video subtitles unavailable — "
                    "download+STT | error=%s", type(exc).__name__)
        return await self._link_stt(url)

    async def _link_stt(self, url: str) -> str:
        """direct/platform (и YouTube-фолбэк): download → STT raw. tmp-файл
        удаляется в finally. R17: без URL/путей в логах."""
        downloader = getattr(self.deps, "downloader", None)
        if downloader is None:
            raise RuntimeError("downloader unavailable")
        path = await asyncio.wait_for(
            downloader.download(url, None), timeout=_DOWNLOAD_TOOL_TIMEOUT)
        try:
            return await self._stt_media(path, _path_ext(path))
        finally:
            try:
                path.unlink(missing_ok=True)
            except (OSError, AttributeError):
                pass

    async def _native_transcript(self, ctx: ToolContext, native) -> str:
        """Нативный путь (F19): ``download_to_tmp`` → STT raw. tmp чистится в
        finally. R17: без file_id/путей в логах."""
        path = None
        try:
            path = await native_media.download_to_tmp(
                ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT)
            return await self._stt_media(
                path, native_media.media_suffix(native).lstrip(".") or "mp4")
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _stt_media(self, path, ext: str) -> str:
        """STT файла ``deps.transcriber`` (F19): нет сервиса → RuntimeError
        (dispatch → ОШИБКА). Таймаут — паритет youtube
        (``limits.video_stt_timeout_seconds``)."""
        transcriber = getattr(self.deps, "transcriber", None)
        if transcriber is None:
            raise RuntimeError("transcriber unavailable")
        timeout = float(hot.get("limits.video_stt_timeout_seconds",
                                settings.VIDEO_STT_TIMEOUT_SECONDS)
                        or settings.VIDEO_STT_TIMEOUT_SECONDS)
        return await transcriber.transcribe_voice(str(path), ext,
                                                  timeout=timeout)

    # ── fetch_article (A2, раунд 10.26, ADR-1026-15 D5) ──────────────────

    async def _fetch_article(self, arguments: dict, ctx: ToolContext) -> str:
        """Извлечение статьи по URL → JSON (ADR-1026-15 D5 + v3 §4.3/§4.4).

        Сохранены прежние ключи (`status,url,source_id,chars,truncated,
        markdown[,title]`), добавлены: ``excerpt_chars, line_range,
        selected_by, sections, remainder_chars, budget_chars, budget_source,
        effective_limit, full_source_pointer, read_level, total_chars,
        published_at, published_at_source, source_kind, links, links_source,
        short_content``.

        Отличия (P0, `limits-audit.md` №2/№4/№6):
          * извлечение до `article_extract_ceiling` (класс C), а не до 8000 —
            нужный раздел после 8k достижим (сценарий 37);
          * доставка — section selection по терминам claim (`terms`) либо по
            явным `section`/`offset` (догрузка остатка тем же инструментом);
          * `truncated` = есть `remainder_chars`, а не «chars >= 8000»;
          * `full_source_pointer` и `line_range` — отдельные поля, поэтому
            обрезка не ломает указатель на полный источник (§4.4).

        Один экземпляр текста в payload: ``markdown`` — доставленная выдержка.
        Дублировать её в ``excerpt`` значило бы удвоить tool-payload в окне
        модели; эквивалент по информации дают ``excerpt_chars``,
        ``line_range`` и ``selected_by`` (см. отчёт w13).
        НИКОГДА не бросает (контракт dispatch). R17: в логи — только
        ``source``/``chars``/класс ошибки, без URL/текста/заголовка."""
        args = arguments if isinstance(arguments, dict) else {}
        raw_url = str(args.get("url") or "").strip()
        source = "argument"
        if raw_url:
            candidates = extract_urls(raw_url)    # reuse smartmodule_urls
            url = candidates[0] if candidates else ""
        else:
            source = "context"
            url = str(getattr(ctx, "resolved_url", "") or "").strip()
        if not url:
            # Честный no_url: нет ссылки в аргументах и однозначной в контексте.
            return json.dumps({"status": "error", "error": "no_url",
                               "reason": "no_url", "retryable": False},
                              ensure_ascii=False)
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        extractor = getattr(self.deps, "extractor", None)
        if extractor is None:
            return json.dumps({"status": "error",
                               "error": "service_unavailable",
                               "reason": "service_unavailable",
                               "retryable": False,
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        claim_keys = self._claim_keys(ctx, args)
        bypass = self._reuse_bypass(args, ctx)
        chat_id = getattr(ctx, "chat_id", None)
        if claim_keys and not bypass:
            for key in claim_keys:
                record = source_reuse.lookup(key, scope="public",
                                              chat_id=chat_id)
                if record is None:
                    continue
                # §3.4: Writer получает ТУ ЖЕ выдержку; источник не перечитывается.
                reused_payload = {
                    "status": "ok", "url": record.url or url,
                    "source_id": record.source_id or source_id,
                    "chars": len(record.snippet), "truncated": True,
                    "markdown": record.snippet,
                    "excerpt_chars": len(record.snippet),
                    "selected_by": "reuse",
                    "remainder_chars": max(
                        0, int(record.full_source_pointer.get("total_chars") or 0)
                        - len(record.snippet)),
                    "read_level": record.read_level,
                    "source_kind": record.source_kind,
                    "published_at": record.published_at,
                    "published_at_source": record.published_at_source,
                    "full_source_pointer": dict(record.full_source_pointer or {}),
                    "reused": True, "reuse": source_reuse.reuse_line(record),
                    "budget_source": "reuse", "network_calls": 0,
                }
                bucket = getattr(ctx, "evidence_limits", None)
                if isinstance(bucket, list):
                    bucket.append({
                        "tool": "fetch_article", "stage": "retrieve",
                        "reused": True, "network_calls": 0,
                        "source_read_level": record.read_level,
                        "limit_source": "reuse", "effective_limit": 0,
                        "used": len(record.snippet),
                        "total": int(record.full_source_pointer.get(
                            "total_chars") or 0),
                        "truncated": False, "why": "",
                        "retrievable_remainder": reused_payload[
                            "remainder_chars"], "unit": "chars"})
                logger.info("[tools] fetch_article reuse | read=%s | chars=%d",
                            record.read_level, len(record.snippet))
                return json.dumps(reused_payload, ensure_ascii=False)
        window = self._evidence_window("article", ctx)
        ceiling, ceiling_source = auto_budget.article_extract_ceiling()
        started = time.monotonic()
        try:
            fetch = getattr(extractor, "extract_document", None)
            document = None
            if callable(fetch):
                candidate = await asyncio.wait_for(
                    fetch(url, ceiling=ceiling), timeout=_ARTICLE_TOOL_TIMEOUT)
                from services.web_content_extractor import ExtractedDocument
                if isinstance(candidate, ExtractedDocument):
                    document = candidate
            if document is None:
                # Совместимость: экстрактор без document-режима (двойники в
                # тестах, внешние обёртки) → прежний вход `extract`.
                from services.web_content_extractor import ExtractedDocument
                raw_text = await asyncio.wait_for(
                    extractor.extract(url, ceiling),
                    timeout=_ARTICLE_TOOL_TIMEOUT)
                text_value = raw_text if isinstance(raw_text, str) else ""
                document = ExtractedDocument(
                    url=url, text=text_value,
                    total_chars=len(text_value), ceiling=ceiling)
        except asyncio.TimeoutError:
            logger.warning("[tools] fetch_article timeout | source=%s", source)
            return json.dumps({"status": "error", "error": "timeout",
                               "reason": "deadline_exceeded", "retryable": True,
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        except WebContentExtractionFailedException as exc:
            logger.warning("[tools] fetch_article failed | source=%s | error=%s",
                           source, type(exc).__name__)
            # MCA-11 (D1/T-4948, M-MCA02-3): SafeFetchError code/stage/
            # retryable → ToolResult через out-of-band сигнал (payload
            # модельно-видимого канала не меняется).
            safe = getattr(exc, "safe_error", None)
            if safe is not None:
                _tool_result.set_signal(ctx, {
                    "error_code": str(getattr(safe, "code", "") or ""),
                    "stage": str(getattr(safe, "stage", "") or ""),
                    "reason": str(getattr(safe, "reason", "") or ""),
                    "retryable": bool(getattr(safe, "retryable", False)),
                })
            # Сценарий 9: честная деградация с различимой причиной — никогда
            # «источник не существует»/фантомный URL/неверная причина.
            payload = {"status": "error", "error": "extract_failed",
                       "reason": ("destination_blocked"
                                  if getattr(safe, "code", "") in
                                  ("destination_blocked", "metadata_endpoint_blocked",
                                   "redirect_blocked") else
                                  "source_unavailable"),
                       "retryable": bool(getattr(safe, "retryable", False)),
                       "url": url, "source_id": source_id}
            if safe is not None and getattr(safe, "code", ""):
                payload["safe_error_code"] = str(safe.code)
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            logger.warning("[tools] fetch_article failed | source=%s | error=%s",
                           source, type(exc).__name__)
            return json.dumps({"status": "error", "error": type(exc).__name__,
                               "reason": "source_unavailable",
                               "retryable": True,
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        markdown_full = str(getattr(document, "text", "") or "")
        total_chars = int(getattr(document, "total_chars", 0)
                          or len(markdown_full))
        if not markdown_full.strip():
            return json.dumps({"status": "error", "error": "empty",
                               "reason": "no_relevant_results",
                               "retryable": False,
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        terms = self._article_terms(args, ctx)
        excerpt = select_excerpt(
            markdown_full, budget_chars=window.effective_limit, terms=terms,
            section=args.get("section"), offset=args.get("offset"))
        delivered = excerpt.text
        # Остаток: внутри извлечённого документа (достижим тем же инструментом
        # через offset) ЛИБО потерянный на extraction-ceiling'е (недостижим).
        retrievable = int(excerpt.remainder_chars or 0)
        remainder = max(retrievable, max(0, total_chars - int(excerpt.end or 0)))
        extraction_truncated = bool(
            getattr(document, "truncated_at_extraction", False))
        pointer = build_source_pointer(
            url, source_id, offset=int(excerpt.end or 0),
            total_chars=total_chars, line_range=excerpt.line_range)
        read_level = (source_reuse.READ_LEVEL_SELECTED
                      if (excerpt.selected_by != "whole" or remainder)
                      else source_reuse.READ_LEVEL_PARSED)
        try:
            from services.search_aggregator import classify_source_kind
            source_kind = str(classify_source_kind(url) or "")
        except Exception:      # pragma: no cover - защитная ветка
            source_kind = ""
        sections = list(excerpt.sections or ())[:40]
        payload = {
            "status": "ok", "url": url, "source_id": source_id,
            "chars": len(delivered), "truncated": bool(remainder),
            "markdown": delivered,
            # ── v3: выдержка, provenance и достижимый остаток ────────────
            "excerpt_chars": len(delivered),
            "line_range": [int(excerpt.line_range[0]),
                           int(excerpt.line_range[1])],
            "selected_by": excerpt.selected_by,
            "sections": sections,
            "sections_total": len(excerpt.sections or ()),
            "remainder_chars": remainder,
            "budget_chars": int(window.budget_chars),
            "budget_source": window.source,
            "effective_limit": int(window.effective_limit),
            "window_source": window.window_source,
            "capacity_source": window.capacity_source,
            "full_source_pointer": pointer,
            "read_level": read_level,
            "total_chars": total_chars,
            "extraction_ceiling": int(getattr(document, "ceiling", 0) or 0),
            "extraction_ceiling_source": ceiling_source,
            "truncated_at_extraction": extraction_truncated,
            # v3 (review fix): «сколько осталось в источнике» и «сколько из
            # этого можно добрать тем же инструментом» — разные числа; при
            # extraction-ceiling'е разница честно видна.
            "remainder_retrievable_chars": retrievable,
            "short_content": bool(getattr(document, "short_content", False)),
            "provider": str(getattr(document, "provider", "") or ""),
            "source_kind": source_kind,
            "published_at": str(getattr(document, "published_at", "") or ""),
            "published_at_source": str(
                getattr(document, "published_at_source", "") or ""),
            "links_source": str(getattr(document, "links_source", "")
                                or "unavailable"),
            "links": list(getattr(document, "links", ()) or ())[:20],
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        title = self._article_title(delivered)
        if title:
            payload["title"] = title
        self._record_limit(
            ctx, "fetch_article",
            Truncation(
                text=delivered, effective_limit=window.effective_limit,
                source=window.source, used=len(delivered), total=total_chars,
                truncated=bool(remainder),
                why=("over_window" if retrievable else
                     ("extraction_ceiling"
                      if extraction_truncated else "")),
                retrievable_remainder=retrievable, unit="chars"),
            stage="retrieve",
            extra={"window_source": window.window_source,
                   "capacity_source": window.capacity_source,
                   "turn_capped": window.turn_capped,
                   "source_read_level": read_level,
                   "extraction_ceiling_source": ceiling_source})
        logger.info("[tools] fetch_article | source=%s | chars=%d | "
                    "total=%d | remainder=%d | selected_by=%s | limit=%d | "
                    "limit_source=%s", source, len(delivered), total_chars,
                    remainder, excerpt.selected_by, window.effective_limit,
                    window.source)
        # §3.3/§3.4: запомнить прочитанный источник под claim-key (если ход
        # аннотирован claims). Хранится ограниченная выдержка + указатель, а не
        # весь документ; после рестарта кеш пуст — обычный fetch.
        for key in claim_keys:
            source_reuse.store(
                key, url=url, source_id=source_id,
                snippet=delivered[:2000], read_level=read_level,
                source_kind=source_kind,
                published_at=str(getattr(document, "published_at", "") or ""),
                published_at_source=str(
                    getattr(document, "published_at_source", "") or ""),
                scope="public", chat_id=chat_id,
                full_source_pointer=pointer)
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _article_terms(args: dict, ctx: ToolContext) -> list[str]:
        """Термины claim для секционного отбора (``terms`` → запрос хода)."""
        raw = args.get("terms")
        terms: list[str] = []
        if isinstance(raw, (list, tuple)):
            terms = [str(item) for item in raw if str(item).strip()]
        elif isinstance(raw, str) and raw.strip():
            terms = [item for item in re.split(r"[,;\s]+", raw) if item.strip()]
        if terms:
            return terms[:24]
        query = str(getattr(ctx, "query", "") or "")
        return sorted(content_terms(query))

    @staticmethod
    def _article_title(markdown: str) -> str:
        """Best-effort заголовок статьи: первый markdown-заголовок `# …`."""
        for line in str(markdown or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title[:200]
        return ""

    # ── read_source_code (EVOL-SRC-READER, W6) ───────────────────────────

    async def _read_source_code(self, arguments: dict,
                                ctx: ToolContext) -> str:
        """Проверенное чтение исходников → JSON Evidence Contract (§1.1).

        Инструмент делает сетевую работу через существующий `SafeFetcher`
        (`services/source_reader.py`), поэтому здесь только проводка
        существующих контуров:

        * env-рубильник `SOURCE_READ_ENABLED` OFF → честный `disabled`
          (инструмент при этом не объявляется — гейт анонса в tool_schemas);
        * динамическое окно evidence (`_evidence_window("code")`) — БЕЗ нового
          потолка 4000/8000: неизвестный вид использует существующий legacy;
        * qualified reuse (`source_reuse`): тот же claim + та же идентичность
          источника (repo/ref/commit/path) → 0 сетевых вызовов; смена
          ref/commit инвалидирует запись (§3.3); приватный доступ (токен) —
          scope=chat, поэтому между чатами не переиспользуется;
        * `truncation`/`not_checked` пишутся в существующий out-of-band
          журнал `evidence_limits` (`_record_limit`).

        НИКОГДА не бросает (контракт dispatch). R17: в логи — только коды и
        числа, без URL/текста кода/токенов."""
        from services import source_reader as _sr

        args = arguments if isinstance(arguments, dict) else {}
        if not _sr.source_read_enabled():
            logger.info("[tools] read_source_code disabled (env kill-switch)")
            # Форма отказа как у существующих выключенных инструментов
            # (`vision/fact_check`): status=disabled → ToolResult `denied`
            # с кодом `disabled`. Сетевой lookup не выполняется.
            return json.dumps({"status": "disabled", "error": "disabled",
                               "reason": "disabled", "retryable": False,
                               "stage": _sr.STAGE_DISCOVER},
                              ensure_ascii=False)
        operation = str(args.get("operation") or _sr.OPERATION_READ).strip() \
            .lower()
        if operation not in _sr.OPERATIONS:
            return json.dumps(
                {"status": "error", "error": "invalid_arguments",
                 "reason": "invalid_operation", "retryable": False,
                 "stage": _sr.STAGE_DISCOVER}, ensure_ascii=False)
        url = str(args.get("url") or "").strip()
        if not url:
            # Существующий резолв ссылки хода (`fetch_article` берёт так же).
            url = str(getattr(ctx, "resolved_url", "") or "").strip()
        query = str(args.get("query") or "").strip()
        if not query:
            query = str(getattr(ctx, "query", "") or "").strip()
        repo = str(args.get("repo") or "").strip()
        # SELF-DIAG-01 corrective (§3/§4): структурированное решение модели
        # `target=self` разрешает серверную каноническую identity своего repo.
        # Это исполнение решения, а не угадывание по словам/URL; аргументы
        # модели (URL/repo внешнего проекта) имеют приоритет и не подменяются.
        _diag = getattr(ctx, "diagnostic_research", None)
        diag_ctx = _diag if isinstance(_diag, dict) \
            and str(_diag.get("target") or "") == "self" else None
        if diag_ctx is not None and not repo and not url:
            repo = str(diag_ctx.get("repo") or "").strip()
        ref = str(args.get("ref") or "").strip()
        if (diag_ctx is not None and not ref and repo
                and repo.casefold() == str(diag_ctx.get("repo") or "").casefold()):
            ref = str(diag_ctx.get("ref") or "").strip()
        if diag_ctx is not None and not ref and url:
            try:
                _parsed_diag = _sr.parse_source_url(url)
                if (_parsed_diag is not None
                        and str(_parsed_diag.repo or "").casefold()
                        == str(diag_ctx.get("repo") or "").casefold()):
                    ref = str(diag_ctx.get("ref") or "").strip()
            except Exception:      # pragma: no cover - защитная ветка
                pass
        if not url and not repo and not query:
            return json.dumps({"status": "error", "error": "invalid_url",
                               "reason": "no_url_no_repo_no_query",
                               "retryable": False,
                               "stage": _sr.STAGE_DISCOVER},
                              ensure_ascii=False)
        path = str(args.get("path") or "").strip()
        symbol = str(args.get("symbol") or "").strip()
        line_start = args.get("line_start")
        line_end = args.get("line_end")
        for value in (line_start, line_end):
            if value is not None and (not isinstance(value, int)
                                      or isinstance(value, bool) or value < 1):
                return json.dumps(
                    {"status": "error", "error": "invalid_arguments",
                     "reason": "invalid_line_range", "retryable": False,
                     "stage": _sr.STAGE_DISCOVER}, ensure_ascii=False)
        window = self._evidence_window("code", ctx)
        reader = self._source_reader()
        claim_keys = self._claim_keys(ctx, args)
        chat_id = getattr(ctx, "chat_id", None)
        scope = "chat" if _sr.github_token() else "public"
        identity = self._source_identity(url=url, repo=repo, ref=ref,
                                         path=path, symbol=symbol)
        bypass = self._reuse_bypass(args, ctx)
        # Reuse — про ПРОЧИТАННЫЙ источник: discovery всегда ищет заново
        # (дешёвый вызов, а «найденный ранее репозиторий» может устареть).
        reuse_allowed = operation in (_sr.OPERATION_READ, _sr.OPERATION_LOCATE)
        if claim_keys and not bypass and reuse_allowed:
            reused = self._source_reuse_payload(
                reader, claim_keys, identity=identity, scope=scope,
                chat_id=chat_id, operation=operation)
            if reused is not None:
                bucket = getattr(ctx, "evidence_limits", None)
                if isinstance(bucket, list):
                    bucket.append({
                        "tool": "read_source_code", "stage": "retrieve",
                        "reused": True, "network_calls": 0,
                        "source_read_level": reused.get("read_level") or "",
                        "limit_source": "reuse", "effective_limit": 0,
                        "used": int(reused.get("snippet_chars") or 0),
                        "total": int(reused.get("file_total_lines") or 0),
                        "truncated": False, "why": "",
                        "retrievable_remainder": 0, "unit": "chars"})
                logger.info("[tools] read_source_code reuse | read=%s | "
                            "chars=%d", reused.get("read_level"),
                            int(reused.get("snippet_chars") or 0))
                return json.dumps(reused, ensure_ascii=False)
        payload = await reader.run(
            operation=operation, url=url, repo=repo, query=query, ref=ref,
            path=path, symbol=symbol, line_start=line_start,
            line_end=line_end, follow=args.get("follow"),
            language=str(args.get("language") or ""),
            budget_chars=int(window.effective_limit or 0),
            context_query=str(getattr(ctx, "query", "") or ""))
        truncation = payload.get("truncation") or {}
        if isinstance(truncation, dict) and truncation:
            # Источник лимита — существующее окно (`call_budget|window|legacy`),
            # а не «своя» константа инструмента.
            truncation["limit_source"] = window.source
            truncation["effective_limit"] = int(window.effective_limit or 0)
            payload["truncation"] = truncation
        self._record_limit(
            ctx, "read_source_code",
            Truncation(
                text=str(payload.get("snippet") or ""),
                effective_limit=int(truncation.get("effective_limit")
                                    or window.effective_limit or 0),
                source=str(truncation.get("limit_source") or window.source),
                used=int(payload.get("snippet_chars") or 0),
                total=int(payload.get("file_total_lines") or 0),
                truncated=bool(truncation.get("truncated")),
                why=str(truncation.get("why") or ""),
                retrievable_remainder=int(
                    truncation.get("retrievable_remainder_lines") or 0),
                unit="lines"),
            stage=str(payload.get("stage") or "fetch"),
            extra={"window_source": window.window_source,
                   "capacity_source": window.capacity_source,
                   "turn_capped": window.turn_capped,
                   "source_read_level": payload.get("read_level") or "",
                   "verified": bool(payload.get("verified")),
                   "network_calls": int(payload.get("network_calls") or 0)})
        # §3.3/§3.5: запомнить ПРОЧИТАННЫЙ источник под claim-key. Повторный
        # read той же идентичности = reuse (0 сетевых вызовов); изменённый
        # ref/commit/path → другой указатель → запись не подходит.
        if claim_keys and payload.get("status") == _sr.STATUS_OK \
                and payload.get("verified"):
            for key in claim_keys:
                # Хранится ровно доставленный фрагмент (без среза): иначе reuse
                # отдавал бы меньше текста, чем первый ответ, и не мог бы
                # честно сообщить обрезку (§1.1, прецедент `fetch_article`).
                source_reuse.store(
                    key, url=str(payload.get("verified_url") or ""),
                    source_id=str(payload.get("source_id") or ""),
                    snippet=str(payload.get("snippet") or ""),
                    read_level=str(payload.get("read_level")
                                   or source_reuse.READ_LEVEL_SELECTED),
                    source_kind=str(payload.get("source_kind") or ""),
                    scope=scope, chat_id=chat_id,
                    full_source_pointer=self._source_pointer(payload))
        # MCA-11 (M-MCA02-3, контракт §2): SafeFetchError-код/стадия/retryable →
        # out-of-band сигнал ToolResult. Полная запись лежит в `error_detail`
        # (`error` — строкой-кодом ради `tool_result`), поэтому читаем её;
        # dict-форма поддержана для совместимости.
        error = payload.get("error_detail")
        if not isinstance(error, dict):
            candidate = payload.get("error")
            error = candidate if isinstance(candidate, dict) else {}
        if error.get("code"):
            _tool_result.set_signal(ctx, {
                "error_code": str(error.get("code") or ""),
                "stage": str(error.get("stage") or ""),
                "reason": str(error.get("detail") or ""),
                "retryable": bool(error.get("retryable")),
            })
        logger.info("[tools] read_source_code | op=%s | status=%s | stage=%s "
                    "| verified=%s | lines=%s | files=%s | calls=%s",
                    operation, payload.get("status"), payload.get("stage"),
                    bool(payload.get("verified")),
                    payload.get("line_range"), len(payload.get("files") or ()),
                    payload.get("network_calls"))
        if diag_ctx is not None:
            requested_repo = repo
            if not requested_repo and url:
                try:
                    parsed = _sr.parse_source_url(url)
                    requested_repo = str(getattr(parsed, "repo", "") or "")
                except Exception:      # pragma: no cover - защитная ветка
                    requested_repo = ""
            origin = str(diag_ctx.get("repo") or "").casefold()
            if not requested_repo or requested_repo.casefold() == origin:
                payload["repo_identity"] = {
                    "target": "self",
                    "repo": diag_ctx.get("repo") or "",
                    "requested_ref": str(diag_ctx.get("ref") or ""),
                    "ref_source": str(diag_ctx.get("ref_source") or ""),
                    "deployed_sha": diag_ctx.get("deployed_sha"),
                    "checkout_sha": diag_ctx.get("checkout_sha"),
                    "deployed_matches_checkout": diag_ctx.get(
                        "deployed_matches_checkout"),
                    "local_source_verification": diag_ctx.get(
                        "local_source_verification"),
                    "dirty": diag_ctx.get("dirty"),
                    "conflict": list(diag_ctx.get("conflict") or ()),
                    "identity_error": str(
                        diag_ctx.get("identity_error") or ""),
                    "note": str(diag_ctx.get("note") or ""),
                }
        return json.dumps(payload, ensure_ascii=False)

    def _source_reader(self):
        """Инстанс `SourceReader` (DI из ToolDeps либо один штатный на deps).

        Собранный инстанс кэшируется на контейнере зависимостей: иначе каждый
        вызов создавал бы новый `httpx.AsyncClient` (утечка соединений), а
        транспорт проекта единственный — `SafeFetcher`."""
        from services import source_reader as _sr
        reader = getattr(self.deps, "source_reader", None)
        if reader is not None:
            return reader
        reader = _sr.SourceReader(search=getattr(self.deps, "search", None))
        try:
            self.deps.source_reader = reader
        except Exception:      # pragma: no cover - защита от frozen-контейнера
            pass
        return reader

    @staticmethod
    def _source_pointer(payload: dict) -> dict:
        """Указатель источника для reuse (без текста кода — identity/строки)."""
        truncation = payload.get("truncation") or {}
        return {
            "provider": str(payload.get("provider") or "github"),
            "host": str(payload.get("host") or "github.com"),
            "repo": str(payload.get("repo") or ""),
            "ref": str(payload.get("ref") or ""),
            "commit": str(payload.get("commit") or ""),
            "path": str(payload.get("path") or ""),
            "line_range": list(payload.get("line_range") or []),
            "file_total_lines": int(payload.get("file_total_lines") or 0),
            "source_kind": str(payload.get("source_kind") or ""),
            "sha256": str((payload.get("provenance") or {}).get("sha256") or ""),
            # Метаданные ДОСТАВЛЕННОГО фрагмента: без них reuse-ответ врал бы
            # «truncated=false, остаток 0» (§1.1 «объём/обрезка»).
            "delivered_chars": int(payload.get("snippet_chars") or 0),
            "truncated": bool(truncation.get("truncated")),
            "why": str(truncation.get("why") or ""),
            "effective_limit": int(truncation.get("effective_limit") or 0),
            "remainder_lines": int(
                truncation.get("retrievable_remainder_lines") or 0),
            "language": str(payload.get("language") or ""),
            "symbol": str(payload.get("symbol") or ""),
            "symbol_found": bool(payload.get("symbol_found")),
            "parameter_only": bool(payload.get("parameter_only")),
            "stage": str(payload.get("stage") or ""),
            # SELF-DIAG-01 D4-B: локальный источник обязан сохранить свою
            # пометку и в reuse-ответе (не выдавать local_unverified за GitHub).
            "local_source_verification": str(
                payload.get("local_source_verification") or ""),
            "local_source_note": str(payload.get("local_source_note") or ""),
        }

    @staticmethod
    def _source_identity(*, url: str, repo: str, ref: str, path: str,
                         symbol: str) -> dict:
        """Идентичность запроса для qualified reuse (B2).

        Считается из ФАКТИЧЕСКОГО адреса поверх явных аргументов: ссылка сама
        несёт repo/ref/path (`url is enough, no repo needed`), поэтому сверка
        по сырым аргументам пропускала бы смену версии и файла и отдавала бы
        чужой commit как `verified` (§3.3 контракта).

        ``pairs`` — все допустимые пары (ref, path) из ссылки («короткий ref
        первым», как в провайдере) и из аргументов: указатель совпадает, если
        попал хотя бы в одну из них (ветка со слэшем разрешается однозначно)."""
        from services import source_reader as _sr
        parsed = _sr.parse_source_url(url) if str(url or "").strip() else None
        repo_full = ""
        if parsed is not None and parsed.owner and parsed.repo:
            repo_full = f"{parsed.owner}/{parsed.repo}"
        if not repo_full:
            spec = _sr.parse_repo_spec(repo)
            if spec is not None:
                repo_full = f"{spec[0]}/{spec[1]}"
        ref = str(ref or "").strip()
        path = str(path or "").strip()
        pairs: list[tuple[str, str]] = []
        if ref and path:
            pairs.append((ref, path))
        if parsed is not None:
            for pair in parsed.ref_path_candidates or ():
                if pair not in pairs:
                    pairs.append(pair)
        return {"repo": repo_full, "pairs": tuple(pairs[:4]), "ref": ref,
                "path": path, "symbol": str(symbol or "")}

    @staticmethod
    def _source_pointer_matches(pointer: dict, identity: dict) -> bool:
        """Совпадает ли указатель записи с запрошенной идентичностью (B2/R-1)."""
        repo = str(identity.get("repo") or "").lower()
        if repo and str(pointer.get("repo") or "").lower() != repo:
            return False
        # R-1: фрагмент окна относится к конкретному СИМВОЛУ. Если запрошен
        # другой символ, отдавать прежний файл как `verified` (с прежним
        # `symbol_found`) нельзя — пусть будет честный fetch/несовпадение.
        symbol = str(identity.get("symbol") or "").strip()
        if symbol and str(pointer.get("symbol") or "").strip() != symbol:
            return False
        pairs = tuple(identity.get("pairs") or ())
        stored = (str(pointer.get("ref") or ""), str(pointer.get("path") or ""))
        if pairs:
            return stored in pairs
        # Явных (ref, path) нет (запрос «найди реализацию X»): reuse допустим
        # только внутри того же репозитория и только на уже найденный файл —
        # иначе это была бы подмена адреса.
        return bool(repo and stored[1])

    def _source_reuse_payload(self, reader, claim_keys, *, identity: dict,
                              scope: str, chat_id, operation: str):
        """Готовый payload из свежей записи `source_reuse` (0 сетевых вызовов).

        Запись принимается, только если её указатель совпадает с запрошенной
        идентичностью (repo/ref/path/operation): изменённая версия/ветка/
        commit обязана привести к новому fetch (§3.3), а не к старому
        доказательству. `verified` НЕ выдумывается: он берётся из реального
        указателя прочитанных байт (`sha256` + line_range), записанного после
        успешного чтения."""
        try:
            for key in claim_keys:
                record = source_reuse.lookup(key, scope=scope, chat_id=chat_id)
                if record is None:
                    continue
                pointer = dict(record.full_source_pointer or {})
                if not pointer.get("commit") or not pointer.get("path"):
                    continue
                if not pointer.get("sha256"):
                    continue
                if not self._source_pointer_matches(pointer, identity):
                    continue
                # Запись и доставленный текст обязаны быть согласованы: если
                # сохранённый фрагмент короче записанного объёма, честнее
                # перечитать файл, чем отдавать усечённое как полное.
                if int(pointer.get("delivered_chars") or 0) != \
                        len(record.snippet):
                    continue
                return {
                    "status": "ok", "stage": "fetch", "verified": True,
                    "host": str(pointer.get("host") or "github.com"),
                    "provider": str(pointer.get("provider") or "github"),
                    "local_source_verification": str(
                        pointer.get("local_source_verification") or ""),
                    "local_source_note": str(
                        pointer.get("local_source_note") or ""),
                    "repo": str(pointer.get("repo") or ""),
                    "ref": str(pointer.get("ref") or ""),
                    "commit": str(pointer.get("commit") or ""),
                    "path": str(pointer.get("path") or ""),
                    "source_kind": str(pointer.get("source_kind") or "file"),
                    "verified_url": record.url,
                    "line_range": list(pointer.get("line_range") or []),
                    "snippet": record.snippet,
                    "snippet_chars": len(record.snippet),
                    "file_total_lines": int(pointer.get("file_total_lines")
                                            or 0),
                    "language": str(pointer.get("language") or ""),
                    "symbol": str(pointer.get("symbol")
                                  or identity.get("symbol") or ""),
                    "symbol_found": bool(pointer.get("symbol_found")),
                    "parameter_only": bool(pointer.get("parameter_only")),
                    # Честная обрезка ДОСТАВЛЕННОГО фрагмента: те же числа, что
                    # были в первом ответе (§1.1 «объём/обрезка»).
                    "truncation": {
                        "truncated": bool(pointer.get("truncated")),
                        "why": str(pointer.get("why") or ""),
                        "effective_limit": int(pointer.get("effective_limit")
                                               or 0),
                        "limit_source": "reuse",
                        "retrievable_remainder_lines": int(
                            pointer.get("remainder_lines") or 0)},
                    "not_checked": {
                        "files_considered": 0, "files_read": 0,
                        "depth_left": 0, "reason": "reuse"},
                    "followup_incomplete": False,
                    "files": [],
                    "read_level": record.read_level,
                    "reused": True,
                    "reuse": source_reuse.reuse_line(record),
                    "source_id": record.source_id,
                    "network_calls": 0,
                    "latency_ms": 0,
                    "operation": operation,
                    "provenance": {
                        "provider": str(pointer.get("provider") or "github"),
                        "endpoint": "reuse",
                        "fetched_at": int(record.retrieved_at or 0),
                        "bytes": 0,
                        "sha256": str(pointer.get("sha256") or ""),
                        "read_level": record.read_level,
                        "network_calls": 0,
                    },
                }
        except Exception:      # pragma: no cover - reuse не рвёт инструмент
            logger.warning("[tools] read_source_code reuse lookup failed",
                           exc_info=True)
        return None

    # ── get_user_context (A6, раунд 10.26, ADR-1026-18 D1–D8) ───────────

    async def _get_user_context(self, arguments: dict,
                                ctx: ToolContext) -> str:
        """Structured memory lookup по инициативе LLM (ADR-1026-18).

        Единая точка: валидация аргументов (§52 п.14) → резолв субъекта
        существующим AliasResolver (`chat_id` — из ``ToolContext``, НЕ параметр
        модели, D2) → purpose-роутинг (D3; lazy RAG только general/speech_style)
        → envelope из 5 полей §33 (D4: facts/sources/confidence/time/no_data) →
        R17-лог (purpose/user_id/chat_id/count/latency/empty_reason). Read-only,
        reuse существующего досье/RAG (D9): НЕ второй резолвер/RAG/БД.
        НИКОГДА не бросает (контракт dispatch)."""
        started = time.monotonic()
        purpose = ""
        try:
            if not _memory_lookup_enabled():
                return self._memory_lookup_finish(
                    ctx, purpose, None, 0, started, "disabled",
                    {"status": "error", "error": "disabled"})
            args = arguments if isinstance(arguments, dict) else {}
            raw_purpose = str(args.get("purpose") or "").strip().lower()
            parsed, detail = self._memory_lookup_parse(args)
            if detail is not None:
                return self._memory_lookup_finish(
                    ctx, raw_purpose, None, 0, started, detail,
                    {"status": "error", "error": "invalid_arguments",
                     "detail": detail})
            purpose = parsed["purpose"]
            aliases = await self._memory_lookup_aliases(ctx)
            person = self._memory_lookup_resolve(parsed, aliases)
            payload = await self._memory_lookup_build(ctx, parsed, person)
            return self._memory_lookup_finish(
                ctx, purpose, person.get("user_id"),
                len(payload.get("facts") or []), started,
                str(payload.get("empty_reason") or ""), payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] memory lookup failed | purpose=%s | "
                           "error=%s", purpose or "-", type(exc).__name__)
            return self._memory_lookup_finish(
                ctx, purpose, None, 0, started, "lookup_failed",
                {"status": "error", "error": "lookup_failed"})

    @staticmethod
    def _memory_lookup_finish(ctx, purpose, user_id, count, started,
                              empty_reason, payload) -> str:
        """R17-лог (только разрешённые поля) + JSON результата (кап 4000)."""
        latency = int((time.monotonic() - started) * 1000)
        label = purpose if purpose in _MEMORY_LOOKUP_PURPOSE_DEFAULTS else "-"
        logger.info(
            "[memory] lookup | purpose=%s | user_id=%s | chat_id=%s | "
            "count=%d | latency_ms=%d | empty_reason=%s",
            label, user_id if user_id is not None else "-",
            getattr(ctx, "chat_id", None), int(count), latency,
            empty_reason or "")
        return ToolRouter._memory_lookup_serialize(payload)

    @staticmethod
    def _memory_lookup_serialize(payload: dict) -> str:
        """JSON-строка результата в бюджете `_MEMORY_LOOKUP_RESULT_MAX_CHARS`.

        При переполнении честно урезаются хвостовые facts/sources (и тексты
        фактов) с ``truncated: true`` — валидный JSON сохраняется."""
        budget = _MEMORY_LOOKUP_RESULT_MAX_CHARS
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= budget:
            return text
        out = dict(payload)
        out["facts"] = list(payload.get("facts") or [])
        out["sources"] = list(payload.get("sources") or [])
        out["truncated"] = True

        def _size() -> int:
            return len(json.dumps(out, ensure_ascii=False))

        while out["facts"] and _size() > budget:
            out["facts"].pop()
            if out["sources"]:
                out["sources"].pop()
        for _ in range(100):
            if _size() <= budget or not out["facts"]:
                break
            idx = max(range(len(out["facts"])),
                      key=lambda k: len(str(out["facts"][k].get("text") or "")))
            item = out["facts"][idx]
            current = str(item.get("text") or "")
            if len(current) <= 1:
                break
            overshoot = _size() - budget
            item["text"] = current[:max(1, len(current) - overshoot - 8)]
        return json.dumps(out, ensure_ascii=False)

    @staticmethod
    def _memory_lookup_parse(arguments):
        """Валидация аргументов (§52 п.14/D2) → (parsed | None, detail | None).

        detail ∈ {missing_person, invalid_person, invalid_purpose,
        invalid_max_items}. НИКОГДА не бросает."""
        args = arguments if isinstance(arguments, dict) else {}
        raw_person = args.get("person")
        if raw_person is not None and not isinstance(raw_person, str):
            return None, "invalid_person"
        person = str(raw_person or "").strip()
        raw_uid = args.get("user_id")
        uid = None
        if raw_uid not in (None, ""):
            if isinstance(raw_uid, bool):
                return None, "invalid_person"
            try:
                uid = int(raw_uid)
            except (TypeError, ValueError):
                return None, "invalid_person"
        if not person and uid is None:
            return None, "missing_person"
        purpose = str(args.get("purpose") or "").strip().lower()
        if purpose not in _MEMORY_LOOKUP_PURPOSE_DEFAULTS:
            return None, "invalid_purpose"
        max_items = _MEMORY_LOOKUP_PURPOSE_DEFAULTS[purpose]
        raw_max = args.get("max_items")
        if raw_max not in (None, ""):
            if isinstance(raw_max, bool):
                return None, "invalid_max_items"
            try:
                value = int(raw_max)
            except (TypeError, ValueError):
                return None, "invalid_max_items"
            if value < 1:
                return None, "invalid_max_items"
            max_items = value
        max_items = min(int(max_items), _MEMORY_LOOKUP_MAX_ITEMS_HARD)
        return ({"person": person, "user_id": uid, "purpose": purpose,
                 "max_items": max_items}, None)

    async def _memory_lookup_aliases(self, ctx):
        """Существующий AliasResolver (deps.aliases) либо per-chat fail-open
        `build_alias_resolver` — второй резолвер НЕ создаётся (D9)."""
        aliases = getattr(self.deps, "aliases", None)
        if aliases is not None:
            return aliases
        try:
            from services.summary_aliases import build_alias_resolver
            return await build_alias_resolver(ctx.chat_id)
        except Exception:
            logger.warning("[tools] memory lookup aliases unavailable | "
                           "chat=%s", getattr(ctx, "chat_id", None))
            return None

    def _memory_lookup_resolve(self, parsed: dict, aliases) -> dict:
        """Идентичность субъекта (D2): user_id → AliasResolver; иначе alias-карта
        (коллизия одинаковых имён → ambiguous, без слияния фактов); иначе
        canon-имя для точечного чтения. Возврат: name/user_id/resolution/
        aliases/candidates."""
        uid = parsed.get("user_id")
        person = str(parsed.get("person") or "").strip().lstrip("@")
        mapping = (getattr(aliases, "_aliases", None)
                   if aliases is not None else None)
        if uid is None and person.isdigit():
            uid = int(person)
        if uid is not None:
            name = self._memory_lookup_resolve_name(aliases, uid, person)
            return {"name": name, "user_id": uid, "resolution": "resolved",
                    "aliases": self._memory_lookup_person_aliases(
                        mapping, uid, name),
                    "candidates": []}
        candidates = self._memory_lookup_alias_candidates(mapping, person)
        if len(candidates) > 1:
            return {"name": "", "user_id": None, "resolution": "ambiguous",
                    "aliases": [], "candidates": candidates}
        if len(candidates) == 1:
            uid = candidates[0]
            name = self._memory_lookup_resolve_name(aliases, uid, person)
            return {"name": name, "user_id": uid, "resolution": "resolved",
                    "aliases": self._memory_lookup_person_aliases(
                        mapping, uid, name),
                    "candidates": []}
        name = person
        if aliases is not None and hasattr(aliases, "canon_name"):
            try:
                name = str(aliases.canon_name(person) or person)
            except Exception:
                name = person
        return {"name": name, "user_id": None, "resolution": "resolved",
                "aliases": [], "candidates": []}

    @staticmethod
    def _memory_lookup_resolve_name(aliases, uid, fallback) -> str:
        if aliases is not None and hasattr(aliases, "resolve"):
            try:
                return str(aliases.resolve(int(uid), fallback or None, None))
            except Exception:
                pass
        return str(fallback or uid)

    @staticmethod
    def _memory_lookup_alias_candidates(mapping, person) -> list:
        if not isinstance(mapping, dict) or not person:
            return []
        low = str(person).casefold()
        out: list[int] = []
        for key, value in mapping.items():
            if str(value).casefold() != low:
                continue
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            if uid not in out:
                out.append(uid)
        return sorted(out)

    @staticmethod
    def _memory_lookup_person_aliases(mapping, uid, name) -> list:
        if not isinstance(mapping, dict) or uid is None:
            return []
        value = mapping.get(str(uid), mapping.get(uid))
        if not value:
            return []
        value = str(value).strip()
        return [value] if value and value != name else []

    async def _memory_lookup_build(self, ctx, parsed: dict,
                                   person: dict) -> dict:
        """Purpose-роутинг (D3) — единая таблица без per-combination веток."""
        purpose = parsed["purpose"]
        max_items = parsed["max_items"]
        if person.get("resolution") == "ambiguous":
            return self._memory_lookup_payload(
                "ok", purpose, person, [], [], no_data=True,
                empty_reason="ambiguous")
        if not person.get("name") and person.get("user_id") is None:
            return self._memory_lookup_payload(
                "ok", purpose, person, [], [], no_data=True,
                empty_reason="unknown_person")
        handler = {
            "identity": self._memory_lookup_identity,
            "appearance": self._memory_lookup_appearance,
            "speech_style": self._memory_lookup_speech_style,
            "biography": self._memory_lookup_biography,
            "relationships": self._memory_lookup_relationships,
            "general": self._memory_lookup_general,
        }[purpose]
        return await handler(ctx, person, max_items)

    async def _memory_lookup_identity(self, ctx, person, max_items) -> dict:
        """identity: AliasResolver (name/aliases/id) + факты субъекта.

        MEMORY-06 (§7.5/MEM-06.10): сами факты читаются ЕДИНЫМ retrieval
        (`retrieve`, канал `subject` — факты О субъекте, не поиск по тексту),
        envelope прежний (status/facts/sources/confidence/time/no_data)."""
        result = await self._memory_lookup_unified(
            ctx, person, purpose="identity", max_items=max_items,
            channels=_MEMORY_LOOKUP_SUBJECT_CHANNELS)
        facts, sources = await self._memory_lookup_unified_items(
            ctx, result, max_items, entity_types=("graph_fact",))
        if not facts:
            return self._memory_lookup_payload(
                "ok", "identity", person, [], [], no_data=True,
                empty_reason="unknown_person")
        return self._memory_lookup_payload(
            "ok", "identity", person, facts, sources,
            extra=self._memory_lookup_dossier_extra(facts))

    async def _memory_lookup_appearance(self, ctx, person, max_items) -> dict:
        """appearance: generic-фильтр поверх graph_facts + honest no_data.

        Извлечение/классификация внешности (в т.ч. из изображений) — A4 (U1);
        здесь только лексиконный отбор существующих подтверждённых фактов,
        отобранных единым retrieval (§7.5) ПО СУБЪЕКТУ."""
        result = await self._memory_lookup_unified(
            ctx, person, purpose="appearance",
            max_items=_MEMORY_LOOKUP_APPEARANCE_SCAN,
            channels=_MEMORY_LOOKUP_SUBJECT_CHANNELS)
        rows, row_sources = await self._memory_lookup_unified_items(
            ctx, result, _MEMORY_LOOKUP_APPEARANCE_SCAN,
            entity_types=("graph_fact",))
        facts, sources = [], []
        for fact, source in zip(rows, row_sources):
            if not self._memory_lookup_is_appearance(
                    str(fact.get("text") or "")):
                continue
            facts.append(fact)
            sources.append(source)
            if len(facts) >= max_items:
                break
        if not facts:
            return self._memory_lookup_payload(
                "ok", "appearance", person, [], [], no_data=True,
                empty_reason="no_storage_for_purpose")
        return self._memory_lookup_payload(
            "ok", "appearance", person, facts, sources)

    async def _memory_lookup_biography(self, ctx, person, max_items) -> dict:
        """biography: факты субъекта (единый retrieval) + generated слой Б."""
        result = await self._memory_lookup_unified(
            ctx, person, purpose="biography", max_items=max_items,
            channels=_MEMORY_LOOKUP_SUBJECT_CHANNELS)
        facts, sources = await self._memory_lookup_unified_items(
            ctx, result, max_items, entity_types=("graph_fact",))
        db = getattr(self.deps, "db", None)
        dossier = await self._memory_lookup_generated_dossier(db, ctx, person)
        if dossier:
            facts.append(self._memory_lookup_portrait_item(dossier))
            sources.append({
                "kind": "dossier_portrait", "ref": "dossier_portrait",
                "origin": "dossier_portrait",
                "ts": int(dossier.get("updated_at") or 0) or None})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "biography", person, [], [], no_data=True,
                empty_reason="unknown_person")
        return self._memory_lookup_payload(
            "ok", "biography", person, facts, sources,
            extra=self._memory_lookup_dossier_extra(facts))

    async def _memory_lookup_relationships(self, ctx, person,
                                           max_items) -> dict:
        """relationships: рёбра субъекта — санкционированная проекция единого
        retrieval (`include_relations`).

        MEMORY-06 (§7.5, MEM-06.10): ветка не создаётся и не переименовывается
        — она уже диспатчится. Основание ребра (`legacy_ids`,
        `has_unsupported_sources`) приходит из `RetrievalResult.relations`
        (проекция существующего чтения C-2/common retrieval), собственного
        SQL-поиска здесь нет. Ребро без основания честно помечается «источник
        не указан», но остаётся в выдаче (не деградирует до `general`)."""
        result = await self._memory_lookup_unified(
            ctx, person, purpose="relationships", max_items=max_items,
            channels=(), include_relations=True)
        facts, sources = [], []
        for rel in getattr(result, "relations", ()) or ():
            if len(facts) >= max_items:
                break
            legacy_ids = [str(v) for v in (rel.get("legacy_ids") or [])]
            unsupported = bool(rel.get("has_unsupported_sources"))
            facts.append({
                "text": str(rel.get("text") or ""),
                "confidence": "unknown", "weight": rel.get("weight"),
                "time": None, "source_id": str(rel.get("fact_id") or ""),
                "legacy_ids": legacy_ids,
                "has_unsupported_sources": unsupported,
                "source_basis": str(rel.get("source_basis") or "")})
            sources.append({"kind": "edge",
                            "ref": str(rel.get("edge_id") or ""),
                            "origin": str(rel.get("origin") or "graph_edge"),
                            "ts": None, "legacy_ids": legacy_ids,
                            "has_unsupported_sources": unsupported})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "relationships", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "relationships", person, facts, sources)

    async def _memory_lookup_unified(self, ctx, person: dict, *,
                                     purpose: str, max_items: int,
                                     mode: str = "specific",
                                     channels=None,
                                     participants=(),
                                     include_relations: bool = False,
                                     preserve_channel_order: bool = True,
                                     memory_scope: str | None = None):
        """MEMORY-06 (§4.4/§7.5): ЕДИНСТВЕННОЕ чтение памяти lookup-ветки.

        Все шесть purpose (`identity`/`appearance`/`speech_style`/
        `biography`/`relationships`/`general`) идут через ОДНУ существующую
        точку `mca_retrieval_context.retrieve`; различаются только
        документированные поля запроса — каналы, scope, участники, имена
        субъекта, проекция связей — а не второй поиск/резолвер. Двойники без
        поисковых каналов → ``None`` (честная деградация, второй движок не
        создаётся). Ноль LLM-вызовов. Никогда не бросает.

        §7.5 (фикс регрессии): `subject_names` — имена/алиасы субъекта для
        канала `subject`: факты о человеке отбираются по колонкам субъекта
        (`subject_ref_id`/`target_user`), а не по совпадению текста с запросом
        (иначе терялись факты без имени в тексте). `preserve_channel_order`
        оставляет порядок самого канала (`weight DESC` профиля / `recent`-
        срез) — это принятый контракт выдачи этих purpose."""
        db = getattr(self.deps, "db", None)
        memory = getattr(self.deps, "memory", None)
        capable = (callable(getattr(db, "search_messages_fts", None))
                   or callable(getattr(db, "search_graph_facts_fts", None))
                   or callable(getattr(db, "get_user_context_facts", None))
                   or callable(getattr(db, "get_persona_card", None))
                   or callable(getattr(memory, "retrieve_fact_candidates",
                                       None)))
        if not capable:
            return None
        try:
            from services import mca_retrieval_context as _rc
            uid = person.get("user_id")
            try:
                subjects = (int(uid),) if uid is not None else ()
            except (TypeError, ValueError):
                subjects = ()
            uids: tuple[int, ...] = ()
            for raw in participants or ():
                try:
                    uids += (int(raw),)
                except (TypeError, ValueError):
                    continue
            names: list[str] = []
            for value in [person.get("name")] + list(
                    person.get("aliases") or ()):
                name = " ".join(str(value or "").split())
                if name and name not in names:
                    names.append(name)
            request = _rc.RetrievalRequest(
                chat_id=int(ctx.chat_id),
                query=str(person.get("name") or ""),
                mode=mode, top_k=max(1, int(max_items)),
                purpose="dossier", intent="who",
                subject_entity_ids=subjects,
                subject_names=tuple(names),
                channels=channels,
                scope=("participants" if uids else "auto"),
                participants=uids,
                preserve_channel_order=bool(preserve_channel_order),
                include_relations=bool(include_relations),
                # VMQ-MEM-TIME (§5): профиль человека строится из нескольких
                # периодов; identity/внешность/речь/связи — действующие
                # сведения. Явное «сейчас» от L1 понижает и профиль.
                memory_scope=self._memory_lookup_scope(
                    ctx, purpose, memory_scope))
            return await _rc.retrieve(db, memory, request)
        except Exception:
            logger.warning("[tools] unified memory retrieval failed | "
                           "purpose=%s | chat=%s", purpose,
                           getattr(ctx, "chat_id", None))
            return None

    #: VMQ-MEM-TIME (§5): purpose, чей профиль строится из НЕСКОЛЬКИХ
    #: периодов истории человека (`biography`/общий обзор). Identity,
    #: внешность, речь и связи — действующие сведения (`operative`).
    _MEMORY_SCOPE_HISTORY_PURPOSES = frozenset({"biography", "general"})

    @classmethod
    def _memory_lookup_scope(cls, ctx, purpose: str,
                             memory_scope: str | None = None) -> str:
        """Политика охвата памяти для профиля (§5), закрытый набор.

        Источник — `L1Plan.memory_scope` (через `ToolContext`), нормализация
        серверная: явное `operative` («что сейчас») понижает и профиль,
        `historical` не понижается, отсутствие/мусор → `auto` (по существу).
        Никаких словарных триггеров года.
        """
        if str(purpose or "") not in cls._MEMORY_SCOPE_HISTORY_PURPOSES:
            return "operative"
        value = str(memory_scope or getattr(ctx, "memory_scope", "") or "")
        value = value.strip().lower()
        if value == "operative":
            return "operative"
        if value == "historical":
            return "historical"
        return "auto"

    @staticmethod
    def _memory_lookup_row_get(row, key: str, default=None):
        """Поле строки graph_facts (dict или sqlite3.Row) без исключений."""
        try:
            if isinstance(row, dict):
                return row.get(key, default)
            return row[key]
        except Exception:
            return default

    async def _memory_lookup_unified_items(self, ctx, result, max_items: int,
                                           *, entity_types=("graph_fact",),
                                           text_cap: int | None = None
                                           ) -> tuple[list, list]:
        """Кандидаты единого retrieval → прежний envelope фактов/источников.

        Отбор/ранжирование — в `retrieve`; здесь только сборка envelope и
        bounded batch-чтение полных строк уже отобранных фактов
        (`get_graph_fact_records`, не поиск) — поэтому weight/status/source
        остаются прежними. Порядок отбора сохраняется."""
        facts: list = []
        sources: list = []
        if result is None:
            return facts, sources
        types = tuple(entity_types or ())
        limit = max(1, int(max_items))
        # Отобранные строки graph_facts приходят вместе с результатом
        # (`fact_rows` — канал их уже прочитал); второго чтения нет.
        by_id: dict = {}
        if "graph_fact" in types:
            for row in getattr(result, "fact_rows", ()) or ():
                try:
                    by_id[int(self._memory_lookup_row_get(row, "id"))] = row
                except (TypeError, ValueError):
                    continue
        for cand in getattr(result, "candidates", ()) or ():
            if len(facts) >= limit:
                break
            entity_type = getattr(cand, "entity_type", "")
            if entity_type not in types:
                continue
            if entity_type == "graph_fact":
                try:
                    row = by_id.get(int(str(getattr(cand, "entity_id", ""))))
                except (TypeError, ValueError):
                    row = None
                if row is None:
                    continue
                try:
                    data = dict(row)
                except (TypeError, ValueError):
                    continue
                fact = self._memory_lookup_fact_item(data)
                if text_cap:
                    fact["text"] = _truncate(fact["text"], text_cap)
                facts.append(fact)
                sources.append(self._memory_lookup_source_item(data))
            else:
                built = self._memory_lookup_candidate_message_item(cand)
                if built is None:
                    continue
                facts.append(built["fact"])
                sources.append(built["source"])
        return facts, sources

    @staticmethod
    def _memory_lookup_candidate_message_item(cand):
        """Кандидат-сообщение единого retrieval → короткий факт + источник."""
        text = str(getattr(cand, "preview", "") or "").strip()
        if not text:
            return None
        ref = str(getattr(cand, "id", "") or "")
        ts = int(getattr(cand, "sent_at", 0) or 0) or None
        fact = {"text": _truncate(text, _MEMORY_LOOKUP_SLICE_MAX_CHARS),
                "confidence": "unknown", "weight": None, "time": ts,
                "source_id": ref}
        source = {"kind": "message", "ref": ref, "origin": "chat_history",
                  "ts": ts}
        return {"fact": fact, "source": source}

    async def _memory_lookup_general(self, ctx, person, max_items) -> dict:
        """general: lazy RAG — graph-факты + релевантные сообщения (D3).

        MEMORY-06 (§4.4/§7.5): сначала ЕДИНЫЙ retrieval (exact/FTS/vector/
        reply/episode через один `retrieve`, плюс канал `subject` — факты о
        человеке, отобранные по субъекту, а не по тексту); если зависимостей
        для него нет (двойник без каналов) — прежний путь без изменений.
        Порядок здесь — типизированный ранг: general смешивает факты о
        субъекте с релевантными сообщениями (прежняя семантика D3)."""
        unified = await self._memory_lookup_unified(
            ctx, person, purpose="general", max_items=max_items,
            preserve_channel_order=False)
        if unified is not None:
            facts, sources = await self._memory_lookup_unified_items(
                ctx, unified, max_items,
                entity_types=("graph_fact", "message"),
                text_cap=_MEMORY_LOOKUP_RAG_FACT_CHARS)
            if facts:
                return self._memory_lookup_payload(
                    "ok", "general", person, facts, sources)
        memory = getattr(self.deps, "memory", None)
        name = person.get("name") or ""
        message_cap = min(max_items, _MEMORY_LOOKUP_MESSAGE_SLICE_MAX,
                          _MEMORY_LOOKUP_MESSAGE_SLICE_HARD)
        facts, sources = [], []
        if memory is not None and hasattr(memory, "get_rag_facts"):
            try:
                rag = await memory.get_rag_facts(ctx.chat_id, name)
            except Exception:
                rag = []
            for entry in rag or []:
                built = self._memory_lookup_rag_fact_item(entry)
                if built is None:
                    continue
                facts.append(built["fact"])
                sources.append(built["source"])
                if len(facts) >= max_items:
                    break
        if (memory is not None and hasattr(memory, "search_long_term")
                and len(facts) < max_items):
            try:
                rows = await memory.search_long_term(
                    ctx.chat_id, keywords(name), limit=message_cap)
            except Exception:
                rows = []
            for row in rows or []:
                built = self._memory_lookup_message_item(row)
                if built is None:
                    continue
                facts.append(built["fact"])
                sources.append(built["source"])
                if len(facts) >= max_items:
                    break
        if not facts and memory is not None \
                and hasattr(memory, "get_rag_context"):
            try:
                text = await memory.get_rag_context(ctx.chat_id, name)
            except Exception:
                text = ""
            text = str(text or "").strip()
            if text:
                facts.append({
                    "text": _truncate(text, _MEMORY_LOOKUP_RAG_FACT_CHARS),
                    "confidence": "unknown", "weight": None, "time": None,
                    "source_id": "rag:context"})
                sources.append({"kind": "rag", "ref": "rag:context",
                                "origin": "rag", "ts": None})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "general", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "general", person, facts, sources)

    async def _memory_lookup_speech_style(self, ctx, person,
                                          max_items) -> dict:
        """speech_style: bounded per-user slice + patterns досье → compact
        профиль. Системная личность бота НЕ меняется (стилизация — дело
        caller'а, §34).

        MEMORY-06 (§7.5): срез собственной речи человека читается ТЕМ ЖЕ
        единым retrieval (канал `recent` + `scope='participants'` с uid
        субъекта — существующее bounded-чтение `get_recent_messages`), а не
        прямым обращением к БД из ветки. Прежний lazy-RAG фолбэк не нужен:
        `recent` уже является каналом единого контракта."""
        db = getattr(self.deps, "db", None)
        uid = person.get("user_id")
        slice_cap = min(max_items, _MEMORY_LOOKUP_MESSAGE_SLICE_MAX,
                        _MEMORY_LOOKUP_MESSAGE_SLICE_HARD)
        participants = ()
        if uid is not None:
            try:
                participants = (int(uid),)
            except (TypeError, ValueError):
                participants = ()
        result = await self._memory_lookup_unified(
            ctx, person, purpose="speech_style",
            max_items=max(slice_cap, _MEMORY_LOOKUP_STYLE_MIN_MESSAGES),
            channels=("recent",), participants=participants)
        facts, sources = await self._memory_lookup_unified_items(
            ctx, result, slice_cap, entity_types=("message",))
        facts, sources = list(facts[:slice_cap]), list(sources[:slice_cap])
        dossier = await self._memory_lookup_generated_dossier(db, ctx, person)
        if dossier:
            patterns = [str(x).strip() for x in (dossier.get("patterns") or [])
                        if str(x).strip()]
            themes = [str(x).strip() for x in (dossier.get("themes") or [])
                      if str(x).strip()]
            profile = self._memory_lookup_style_profile(patterns, themes)
            if profile:
                ts = int(dossier.get("updated_at") or 0) or None
                facts.append({"text": profile, "confidence": "unknown",
                              "weight": None, "time": ts,
                              "source_id": "dossier_portrait"})
                sources.append({"kind": "profile", "ref": "dossier_patterns",
                                "origin": "dossier_portrait", "ts": ts})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "speech_style", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "speech_style", person, facts, sources)

    async def _memory_lookup_generated_dossier(self, db, ctx, person):
        """Reuse `db.get_generated_dossier` (Слой Б) — fail-open → None."""
        getter = getattr(db, "get_generated_dossier", None)
        name = person.get("name")
        if not callable(getter) or not name:
            return None
        try:
            return await getter(ctx.chat_id, name)
        except Exception:
            logger.warning("[tools] memory lookup dossier read failed | "
                           "chat=%s", getattr(ctx, "chat_id", None))
            return None

    def _memory_lookup_fact_item(self, row: dict) -> dict:
        """graph_facts-строка → факт envelope (per-fact confidence/source).

        VMQ-MEM-TIME (§6): аддитивные поля `status`, `valid_now`, `as_of_year`
        — Writer (и человек) видит, историчность это или действующее
        сведение. Промпты не меняются: маркировка живёт в данных, как
        «(не подтверждено)». `confidence` — по R (вес+provenance), статус
        `archived_fact` её НЕ понижает (квота ≠ ложность).
        """
        weight = row.get("weight")
        status = str(row.get("status") or "")
        now = int(time.time())
        expires_at = row.get("expires_at")
        valid_now = status == "confirmed"
        if valid_now and expires_at not in (None, ""):
            try:
                valid_now = int(expires_at) > now
            except (TypeError, ValueError):
                valid_now = True
        ts = row.get("message_timestamp") or row.get("created_at")
        as_of_year = None
        try:
            if ts:
                as_of_year = datetime.datetime.fromtimestamp(
                    int(ts), datetime.timezone.utc).year
        except (TypeError, ValueError, OSError, OverflowError, AttributeError):
            as_of_year = None
        return {
            "text": str(row.get("fact") or "").strip(),
            "confidence": self._memory_lookup_conf_label(
                status, weight),
            "weight": float(weight) if weight is not None else None,
            "time": int(row.get("message_timestamp")
                        or row.get("created_at") or 0) or None,
            "source_id": resolve_item_id(
                tg_message_id=row.get("tg_message_id"), fact_id=row.get("id")),
            "status": status,
            "valid_now": bool(valid_now),
            "as_of_year": as_of_year,
            # VMQ-MEM-TIME (§5, блокер 3 ре-ревью 10.11.2026): строка —
            # исторический контекст ЧАТА без привязки к субъекту (архив
            # импортирован без `subject_ref_id`/`target_user`/автора).
            # `True` = это НЕ сведение о названном человеке.
            "unattributed": bool(row.get("unattributed")),
        }

    def _memory_lookup_source_item(self, row: dict) -> dict:
        return {
            "kind": "graph_fact",
            "ref": resolve_item_id(tg_message_id=row.get("tg_message_id"),
                                   fact_id=row.get("id")),
            "origin": str(row.get("origin") or ""),
            "ts": int(row.get("message_timestamp")
                      or row.get("created_at") or 0) or None,
        }

    def _memory_lookup_rag_fact_item(self, entry):
        """RAG-факт (4-кортеж origin/fact/ts/target или dict) → fact+source."""
        if isinstance(entry, dict):
            origin = str(entry.get("origin") or "")
            text = str(entry.get("fact") or entry.get("text") or "").strip()
            ts = int(entry.get("rag_ts") or entry.get("message_timestamp")
                     or entry.get("created_at") or 0) or None
        elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
            origin = str(entry[0] or "")
            text = str(entry[1] or "").strip()
            ts = (int(entry[2] or 0) or None) if len(entry) > 2 else None
        else:
            return None
        if not text:
            return None
        fact = {"text": _truncate(text, _MEMORY_LOOKUP_RAG_FACT_CHARS),
                "confidence": "unknown", "weight": None, "time": ts,
                "source_id": ""}
        source = {"kind": "rag", "ref": "", "origin": origin or "rag",
                  "ts": ts}
        return {"fact": fact, "source": source}

    def _memory_lookup_message_item(self, row):
        """smart_messages-строка → короткий факт (slice ≤240) + msg/tg-источник."""
        try:
            item = dict(row)
        except (TypeError, ValueError):
            return None
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        ts = int(item.get("timestamp") or 0) or None
        ref = resolve_item_id(tg_message_id=item.get("tg_message_id"),
                              message_id=item.get("id"))
        fact = {"text": _truncate(text, _MEMORY_LOOKUP_SLICE_MAX_CHARS),
                "confidence": "unknown", "weight": None, "time": ts,
                "source_id": ref}
        source = {"kind": "message", "ref": ref, "origin": "chat_history",
                  "ts": ts}
        return {"fact": fact, "source": source}

    @staticmethod
    def _memory_lookup_dossier_extra(facts) -> dict:
        """Reuse `format_dossier_block` для компактного рендера фактов.

        VMQ-MEM-TIME (§5, ре-ревью 10.11.2026): строки с `unattributed`
        (история ЧАТА, не привязанная к субъекту) в досье НЕ попадают.
        Досье — компактная сводка О ЧЕЛОВЕКЕ; даже помеченная строка внутри
        него читается как сведение о нём, поэтому такой факт остаётся только
        в `facts` и в RAG-блоке (где несёт «(общий контекст чата)»).
        """
        try:
            from services.dossier_prompts import format_dossier_block
            texts = [str(f.get("text") or "") for f in facts
                     if isinstance(f, dict) and not f.get("unattributed")
                     and str(f.get("text") or "").strip()]
            block = format_dossier_block(texts, [],
                                         _MEMORY_LOOKUP_RESULT_MAX_CHARS)
        except Exception:
            block = ""
        return {"dossier": block} if block else {}

    @staticmethod
    def _memory_lookup_portrait_item(dossier: dict) -> dict:
        text = str(dossier.get("portrait") or "").strip()
        if not text:
            patterns = [str(x).strip() for x in (dossier.get("patterns") or [])
                        if str(x).strip()]
            themes = [str(x).strip() for x in (dossier.get("themes") or [])
                      if str(x).strip()]
            parts = []
            if patterns:
                parts.append("Паттерны: " + "; ".join(patterns))
            if themes:
                parts.append("Темы: " + "; ".join(themes))
            text = " ".join(parts)
        return {"text": text[:_MEMORY_LOOKUP_PORTRAIT_MAX_CHARS],
                "confidence": "unknown", "weight": None,
                "time": int(dossier.get("updated_at") or 0) or None,
                "source_id": "dossier_portrait"}

    @staticmethod
    def _memory_lookup_style_profile(patterns, themes) -> str:
        parts = []
        if patterns:
            parts.append("Паттерны речи: " + "; ".join(patterns[:5]))
        if themes:
            parts.append("Темы: " + "; ".join(themes[:5]))
        return _truncate(" ".join(parts), _MEMORY_LOOKUP_PORTRAIT_MAX_CHARS)

    @staticmethod
    def _memory_lookup_conf_label(status, weight) -> str:
        """graph_facts.status+weight → confirmed/likely/unconfirmed (D4).

        VMQ-MEM-TIME (§6): `archived_fact` (вытеснение квотой) — не признак
        недостоверности: достоверность считается из веса и provenance, статус
        квоты в неё не входит. `valid_now`/`as_of_year` несут историчность
        отдельными полями.
        """
        if str(status or "").strip().lower() not in ("confirmed",
                                                     "archived_fact"):
            return "unconfirmed"
        try:
            value = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            value = None
        if value is None or value >= _MEMORY_LOOKUP_CONFIRMED_WEIGHT:
            return "confirmed"
        return "likely"

    @staticmethod
    def _memory_lookup_is_appearance(text: str) -> bool:
        low = str(text or "").casefold()
        return any(stem in low for stem in _APPEARANCE_LEXICON)

    @staticmethod
    def _memory_lookup_person_dict(person: dict) -> dict:
        out = {
            "name": str(person.get("name") or ""),
            "user_id": person.get("user_id"),
            "resolution": str(person.get("resolution") or "resolved"),
        }
        aliases = list(person.get("aliases") or [])
        if aliases:
            out["aliases"] = aliases
        if out["resolution"] == "ambiguous":
            out["candidates"] = list(person.get("candidates") or [])
        return out

    @staticmethod
    def _memory_lookup_confidence(facts) -> dict:
        """Агрегат подтверждённости (D4): нет носителя → available=false/unknown;
        ни один элемент не помечен confirmed без подтверждения носителем."""
        labels = [str(f.get("confidence") or "unknown") for f in facts or []]
        weights = [float(f.get("weight")) for f in facts or []
                   if f.get("weight") is not None]
        if not labels or all(lbl == "unknown" for lbl in labels):
            return {"available": False, "label": "unknown", "value": None}
        if "confirmed" in labels:
            label = "confirmed"
        elif "likely" in labels:
            label = "likely"
        else:
            label = "unconfirmed"
        return {"available": True, "label": label,
                "value": max(weights) if weights else None}

    @staticmethod
    def _memory_lookup_time_context(facts) -> dict:
        times = [int(f.get("time")) for f in facts or [] if f.get("time")]
        if not times:
            return {"from": None, "to": None, "label": ""}
        lo, hi = min(times), max(times)
        try:
            y_lo = datetime.datetime.fromtimestamp(lo).year
            y_hi = datetime.datetime.fromtimestamp(hi).year
        except (ValueError, OSError, OverflowError):
            return {"from": lo, "to": hi, "label": ""}
        label = str(y_lo) if y_lo == y_hi else f"{y_lo}–{y_hi}"
        return {"from": lo, "to": hi, "label": label}

    def _memory_lookup_payload(self, status, purpose, person, facts, sources,
                               *, no_data=False, empty_reason="",
                               extra=None) -> dict:
        """Envelope из 5 полей §33 (D4) + служебные (status/purpose/person/
        no_data/empty_reason/truncated)."""
        facts = list(facts or [])[:_MEMORY_LOOKUP_MAX_ITEMS_HARD]
        sources = list(sources or [])[:_MEMORY_LOOKUP_MAX_ITEMS_HARD]
        is_empty = bool(no_data) or not facts
        payload = {
            "status": status,
            "purpose": purpose,
            "person": self._memory_lookup_person_dict(person),
            "facts": facts,
            "sources": sources,
            "confidence": self._memory_lookup_confidence(facts),
            "time_context": self._memory_lookup_time_context(facts),
            "no_data": is_empty,
            "empty_reason": (empty_reason if is_empty else ""),
            "truncated": False,
        }
        if extra:
            payload.update(extra)
        return payload

    # ── recognize_image (MCA-19, ADR-1028-19 D22/D23, round 10.43) ────────

    async def _recognize_image(self, arguments: dict, ctx: ToolContext) -> str:
        """Vision-инструмент (канон 13): target MessageRef → ЕДИНЫЙ сервис
        mca-19 (`mca_vision.recognize_target`; auto/manual/tool — один вход).
        ACL (D22): chat scope — из доверенного рантайма (ctx.chat_id); цель
        в ДРУГОМ чате отклоняется (кэш/права не переносятся, TH-5);
        произвольные URL/API key/модель от LLM НЕ принимаются (schema
        additionalProperties: false + игнор неизвестных полей).
        Серверная проверка OFF — defence in depth (инструмент может быть
        скрыт из набора, устаревший вызов всё равно получает честный
        disabled). Результат — JSON ToolResult-контракта D22 (прецедент
        get_user_context): status ready/pending/disabled/unavailable/
        unsupported/ambiguous/missing/failed + reason из финального
        словаря (269) + cache_hit/analysis_revision/source refs.
        Pending — связка с job; «посмотрю» ≠ «посмотрел» (D23)."""
        import json as _json
        from services import mca_gates, mca_vision
        if not (mca_gates.vision_enabled()
                and mca_gates.vision_tool_enabled()):
            return _json.dumps({"status": "disabled",
                                "reason": "vision_disabled"},
                               ensure_ascii=False)
        db = self.deps.db
        if db is None:
            return _json.dumps({"status": "failed",
                                "reason": "vision_unavailable"},
                               ensure_ascii=False)
        args = arguments if isinstance(arguments, dict) else {}
        target = args.get("target") if isinstance(args.get("target"),
                                                  dict) else {}
        try:
            target_chat = int(target.get("chat_id"))
            target_msg = int(target.get("message_id"))
        except (TypeError, ValueError, AttributeError):
            return _json.dumps(
                {"status": "failed", "reason": "vision_failed",
                 "note": "target required: chat_id + message_id"},
                ensure_ascii=False)
        if target_chat != int(ctx.chat_id):
            # TH-5/SC-R3c: другой чат — вне ACL доверенного рантайма.
            return _json.dumps(
                {"status": "missing", "reason": "vision_missing_source",
                 "out_of_scope": True},
                ensure_ascii=False)
        reply_id = (target_msg or getattr(ctx, "media_target_message_id", None)
                    or ctx.reply_to_message_id)
        selector = str(args.get("asset_selector") or "").strip() or None
        question = str(args.get("question") or "").strip()[:200]
        try:
            result = await mca_vision.recognize_target(
                db, chat_id=int(ctx.chat_id), reply_tg_id=reply_id,
                selector=selector, question=question,
                wait_seconds=mca_vision.RECOGNIZE_TOOL_WAIT_SECONDS)
        except Exception as exc:
            logger.warning("[tools] recognize_image failed | error=%s",
                           type(exc).__name__)
            return _json.dumps({"status": "failed",
                                "reason": "vision_failed"},
                               ensure_ascii=False)
        return _json.dumps(result, ensure_ascii=False)

    # ── fact_check (MCA-20, ADR-1028-20 D4/§7.5, round 10.44) ─────────────

    @staticmethod
    def _guard_tool_verdict(run):
        """CFG-07C-G-хвост (07C.5, v2-only): human-language verdict-текст
        tool-ответа агент ретранслирует в чат → public_speech_guard.
        Служебные поля конверта (reason-коды/статусы/даты/claim) — машинный
        JSON, НЕ трогаются (07C.5: guard не применяется к машинному JSON).
        BGS-03: guard только наблюдает — verdict-текст возвращается
        байт-в-байт (находки видны в событии/логе). Сбой guard'а → run как
        есть (fail-soft)."""
        try:
            from services.public_speech_guard import guard_public_text
            g = guard_public_text(run.verdict_text)
        except Exception:
            logger.warning("[tools] fact_check speech guard failed — "
                           "passthrough", exc_info=True)
            return run
        if not g.findings:
            return run
        logger.warning("[tools] fact_check guard | findings=%s | "
                       "repaired=%s", ",".join(g.findings), g.repaired)
        try:
            from services import temporal_factcheck as tf
            tf.stage_event("egress_guard", "failed",
                           reason_code=",".join(g.findings)[:120])
        except Exception:      # события не рвут tool-ответ
            pass
        if not g.text:
            return None
        return (dataclasses.replace(run, verdict_text=g.text)
                if g.changed else run)

    async def _fact_check(self, arguments: dict, ctx: ToolContext) -> str:
        """Tool временного фактчека (канон 14): ОДИН адаптер к общему
        сервису (FactCheckService.check_claim_envelope) — не второй
        пайплайн (CA-20-1). ACL (D2/D4): scope — из доверенного рантайма
        (ctx.chat_id); target чужого чата отклоняется; chat_id/URL/даты
        от LLM НЕ принимаются (additionalProperties: false + игнор).
        claim_period_hint — НЕавторитетная extracted-подсказка (D5).
        Серверная проверка OFF — defence in depth (K2/каталог-тумблер).
        Свободный текст без цели → explicit unknown origin без выдуманных
        message/date (D3). Рекурсия невозможна: стадии — data-only
        (service.tool_router в адаптере не передаётся), belt-and-suspenders
        depth-guard в tool loop (CA-20-12). ToolResult-контракт D4:
        status ∈ {ready, disabled, unavailable, insufficient_evidence,
        failed} + payload. CFG-06 (REV-CFG-06 F1, 06B.1/06H.2): при v2 ON
        (pipeline_v2_enabled) tool-интент идёт через ЕДИННЫЙ контур
        оркестратора, как handler-маршрут: suitability-gate + широкий
        контекст ДО платного поиска; no_claim/ambiguous → структурный
        JSON агенту БЕЗ платного поиска (status="skipped"); иначе тот же
        check_claim_envelope с chat_context=feed. OFF → прежний вызов
        байт-в-байт (2.58.98)."""
        import json as _json
        from services import mca_gates, temporal_factcheck as tf
        if not (mca_gates.temporal_factcheck_enabled()
                and mca_gates.temporal_factcheck_tool_enabled()
                and bool(getattr(settings, "TEMPORAL_TOOL_ENABLED", True))):
            return _json.dumps({"status": "disabled",
                                "reason": "fact_check_disabled"},
                               ensure_ascii=False)
        args = arguments if isinstance(arguments, dict) else {}
        claim = str(args.get("claim") or "").strip()
        if not claim:
            return _json.dumps(
                {"status": "failed", "reason": "temporal_envelope_rejected",
                 "note": "claim required"},
                ensure_ascii=False)
        mode = str(args.get("mode") or "").strip() or None
        if mode is not None and mode not in tf.ASSESSMENT_MODES:
            # D7/F-1: невалидный mode от LLM — честный отказ, не молча
            # (существующий reason-код, без молчаливой подмены дефолтом).
            return _json.dumps({"status": "failed",
                                "reason": "temporal_envelope_rejected",
                                "note": "invalid mode"},
                               ensure_ascii=False)
        # CFG-06 (live 2.58.91, finding 5): референтный вопрос («бот, это
        # правда?» / «проверь его слова» / «не врёт?») — claim берётся из
        # replied-сообщения (тот же кейс, что канонический reply-фактчек 0g,
        # ``handlers.factcheck``: цель reply'я и есть проверяемый текст).
        # Собственный claim и нереферентные вопросы («как работает фактчек?»)
        # не подменяются. Единый пайплайн: тот же envelope-путь ниже.
        reply_text = str(getattr(ctx, "reply_source_text", "") or "").strip()
        reply_src_id = getattr(ctx, "reply_source_message_id", None)
        claim_from_reply = bool(reply_text and reply_src_id is not None
                                and tf.is_referential_claim(claim))
        # BD-9 (§1.4/M7): происхождение тезиса tool-маршрута фиксируется
        # явно: тезис пришёл от LLM (`tool_claim`) и мог быть усечён. Это
        # допустимо для tool-ветки, но обязано быть видно в трассе, а не
        # выглядеть как дословный текст цели.
        claim_origin = "tool_claim"
        claim_truncated = False
        if claim_from_reply:
            claim_truncated = len(reply_text) > 300
            claim = reply_text[:300]      # bounded — как в дет. деривации
        target = args.get("target") if isinstance(args.get("target"),
                                                  dict) else {}
        try:
            target_chat = int(target.get("chat_id"))
            target_msg = int(target.get("message_id"))
        except (TypeError, ValueError, AttributeError):
            target_chat, target_msg = None, None
        if target_chat is not None and target_chat != int(ctx.chat_id):
            # CA-20-7/12: другой чат — вне ACL доверенного рантайма.
            return _json.dumps(
                {"status": "unavailable",
                 "reason": "temporal_envelope_rejected",
                 "out_of_scope": True},
                ensure_ascii=False)
        if claim_from_reply and (target_msg is None
                                 or target_msg == ctx.reply_to_message_id):
            # Источник claim'а — replied-сообщение, а не триггер хода:
            # даты/происхождение envelope берутся из него (D2/D5).
            target_msg = int(reply_src_id)
        db = self.deps.db
        ref = tf.InputRef(
            kind="tool", chat_id=int(ctx.chat_id) if ctx.chat_id else None,
            target_tg_message_id=target_msg,
            trigger_tg_message_id=ctx.reply_to_message_id,
            claim_text=claim,
            # F-1/§30.2 `:1783`: явный mode tool-вызова — структурное поле,
            # идёт в envelope МИМО фразового resolver'а (hint — не для enum).
            explicit_mode=mode,
            source_type="text")
        envelope, reject_reason = await tf.build_envelope(db, ref)
        if envelope is None:
            tf.stage_event("target_resolve", "failed",
                           reason_code=reject_reason, chat_id=ctx.chat_id)
            return _json.dumps(
                {"status": "unavailable", "reason": reject_reason},
                ensure_ascii=False)
        try:
            from services.factcheck_service import FactCheckService
            service = FactCheckService(self.deps.search, self.deps.llm)
        except Exception:
            return _json.dumps({"status": "failed",
                                "reason": "provider_unavailable"},
                               ensure_ascii=False)
        # CFG-06 (REV-CFG-06 F1): v2-контур оркестратора на tool-маршруте.
        # Gate ДО платного поиска; сбой гейта → честный failed БЕЗ вызова
        # check_claim_envelope (не обходим gate платным поиском).
        v2 = False
        try:
            from services.factcheck_orchestrator import pipeline_v2_enabled
            v2 = bool(pipeline_v2_enabled())
        except Exception:
            v2 = False
        feed = None
        if v2:
            skip_reason = None
            try:
                from services import factcheck_suitability as fsg
                from services.smart_cache import get_smart_cache
                decision, fctx = await fsg.evaluate_with_expansion(
                    db, int(ctx.chat_id) if ctx.chat_id else 0,
                    claim_text=claim, user_hint=None,
                    target_tg_message_id=target_msg,
                    trigger_tg_message_id=ctx.reply_to_message_id,
                    cache=get_smart_cache())
                feed = fctx.render_feed(
                    projection=SpeechProjection(
                        run_id=f"factcheck-tool:{int(ctx.chat_id or 0)}")) \
                    if fctx is not None else ""
                if decision is not None and decision.decision in (
                        fsg.DECISION_NO_CLAIM, fsg.DECISION_AMBIGUOUS):
                    skip_reason = decision.decision
            except Exception:
                logger.warning("[tools] fact_check v2 gate failed",
                               exc_info=True)
                return _json.dumps({"status": "failed",
                                    "reason": "temporal_insufficient_evidence"},
                                   ensure_ascii=False)
            # CFG-06 06G.3: атрибуционный спор («кто это сказал») —
            # локальная резолюция по ConversationContext ДО платного
            # поиска; совпадения нет → честный skip, реплика найдена →
            # поисковые стадии получают тезис клейма (BGS-01: имена внутри
            # тезиса не вычищаются).
            try:
                from services import factcheck_attribution as fat
                attribution = fat.detect_attribution_claim(claim)
                if (attribution is not None and fat.mention_is_participant(
                        fctx, attribution.author_mention)):
                    if fat.resolve_attribution(fctx, attribution) is None:
                        skip_reason = "attribution_not_found"
                    else:
                        envelope = fat.with_claim_thesis(
                            envelope,
                            fat.attribution_thesis(claim, attribution))
            except Exception:
                logger.warning("[tools] fact_check attribution failed",
                               exc_info=True)
            if skip_reason is not None:
                tf.stage_event("deliver", "skipped",
                               reason_code=skip_reason, chat_id=ctx.chat_id)
                return _json.dumps({"status": "skipped",
                                    "reason": skip_reason},
                                   ensure_ascii=False)
        try:
            if v2:
                run = await service.check_claim_envelope(
                    envelope, chat_context=feed or None)
                run = self._guard_tool_verdict(run)
                if run is None:
                    # CFG-07C-G-хвост: вердикт-текст невыразим (сплошная
                    # метаречь) → честный failed БЕЗ записи прогона и БЕЗ
                    # ретранслируемой агентом метаречи (07C.4).
                    return _json.dumps(
                        {"status": "failed",
                         "reason": "temporal_insufficient_evidence"},
                        ensure_ascii=False)
            else:
                run = await service.check_claim_envelope(envelope)
        except Exception as exc:
            logger.warning("[tools] fact_check failed | error=%s",
                           type(exc).__name__)
            return _json.dumps({"status": "failed",
                                "reason": "temporal_insufficient_evidence"},
                               ensure_ascii=False)
        scope = f"chat:{int(ctx.chat_id)}" if ctx.chat_id else "global"
        run_id = await tf.record_temporal_run(db, run, scope=scope)
        verdict = run.verdict
        # EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§9.2/§9.3 п.3/§4.1 P5):
        # результат инструмента читает МОДЕЛЬ, поэтому в нём не должно быть
        # служебных идентификаторов прогона (`run_id` — метаданные §9.2):
        # корреляция уходит в машинный слой (`tf.stage_event(..., pipeline_run_id)`).
        # Зато содержательные опоры — тезис, даты, автор тезиса и РЕАЛЬНЫЕ
        # проверенные ссылки — видны структурно, а не только внутри текста
        # вердикта: модель может на них сослаться, не пересказывая трассу.
        attribution = dict(getattr(envelope, "attribution", None) or {})
        claim_author = str(attribution.get("author") or "").strip() \
            or str(getattr(envelope, "origin_display_name", "") or "").strip()
        evidence_payload = []
        for row in (run.evidence_rows or ()):
            try:
                item = {
                    "url": str(row.get("url") or "").strip() or None,
                    "published_at": row.get("published_at"),
                    "source_kind": str(row.get("source_kind") or "").strip() or None,
                    "excerpt": str(row.get("support") or "").strip()[:300] or None,
                }
            except AttributeError:
                continue
            if item["url"] or item["excerpt"]:
                evidence_payload.append(item)
        payload = {
            "status": "ready",
            "reason": verdict.reason,
            "claim": envelope.claim_text[:400],
            "claim_author": claim_author or None,
            "factual_verdict": verdict.factual_verdict,
            "temporal_status": verdict.temporal_status,
            "evaluated_period": verdict.evaluated_period,
            "assessment_mode": verdict.assessment_mode,
            "as_of": verdict.as_of,
            "date_source": envelope.date_source,
            "original_published_at": envelope.original_published_at,
            "repost_received_at": envelope.repost_received_at,
            "uncertainty": verdict.uncertainty,
            "evidence": evidence_payload,
            "cache_hit": False,
            "verdict": run.verdict_text[:2000],
            # M7/BD-9: происхождение тезиса tool-ветки и его анкор. Без этих
            # полей пересказ LLM выглядел бы как дословный Target.
            "claim_origin": claim_origin,
            "target_source": "tool",
            "claim_anchor_tg_message_id": (
                int(reply_src_id) if claim_from_reply and reply_src_id
                else target_msg),
            "claim_truncated": claim_truncated,
        }
        tf.stage_event("target_resolve", "success",
                       reason_code="tool_claim", chat_id=ctx.chat_id,
                       pipeline_run_id=run_id)
        tf.stage_event("deliver", "success", chat_id=ctx.chat_id,
                       pipeline_run_id=run_id)
        return _json.dumps(payload, ensure_ascii=False)

    def _resolve_tool_source(self, arguments: dict, ctx: ToolContext,
                             kinds: tuple[str, ...] | None = None):
        """Общий резолв источника медиа-инструментов (F14, §4.5):

        * ``source == "reply"`` → нативный путь при доступном видео (приоритет
          над http-``url`` — спецификация §4.5); иначе нет источника;
        * http(s)-``url`` → ``("link", url, None)``;
        * иначе при нативном медиа в ``ctx.native_media`` (по умолчанию
          video/видео-document) → ``("native", None, media)``;
        * иначе ``(None, None, None)``.

        ``kinds`` — какие виды нативного медиа допустимы: по умолчанию
        ``native_media.VIDEO_KINDS`` (F14, video/document); F19
        ``transcribe_video`` передаёт ``native_media.MEDIA_KINDS``
        (включая voice/video_note). Kill-switch ``NATIVE_MEDIA_TOOLS_ENABLED``
        OFF → нативный резолв не срабатывает (прежнее поведение: нужен
        http-``url``)."""
        allowed = kinds if kinds is not None else native_media.VIDEO_KINDS
        args = arguments if isinstance(arguments, dict) else {}
        url = str(args.get("url") or "").strip()
        source = str(args.get("source") or "").strip().lower()
        native = getattr(ctx, "native_media", None)
        native_ok = (native is not None
                     and getattr(native, "kind", "") in allowed)
        if source == "reply":
            if _native_tools_enabled() and native_ok:
                return "native", None, native
            return None, None, None
        if _is_http_url(url):
            return "link", url, None
        if _native_tools_enabled() and native_ok:
            return "native", None, native
        return None, None, None

    def _download_cooldown(self):
        """Общий download-кулдаун роутера 4e | None (R10.15-9). Провайдер —
        zero-arg callable (ленивая ссылка на трекер); сбой провайдера → None
        (не роняем tool-loop)."""
        provider = getattr(self.deps, "download_cooldown", None)
        if provider is None:
            return None
        try:
            return provider() if callable(provider) else provider
        except Exception:
            logger.warning("[tools] download cooldown unavailable")
            return None

    async def _download_media(self, arguments: dict, ctx: ToolContext) -> str:
        """Корнер-кейс файлов (ADR-1015-3 §4) + запрос качества (ADR-1017-2).

        Раунд 10.17 (F2, ADR-1017-2 §2 — SUPERSEDE ADR-1016-1 §2 п.3/§3):
        платформенный URL → `probe()` → инлайн-меню качества `tdq:<height>` →
        фиктивный `tool_response {"status":"needs_quality"}`; скачивание
        доводит callback `tdq:` (роутер 4e). Прямой медиа-URL или ЯВНО
        названное пользователем `quality` → скачиваем сразу без меню. Провал
        probe → одна bounded попытка `download(url, None)` без меню.

        Файл шлём САМИ (send_media), в LLM — фиктивный JSON (модель не
        «печатает» видео). Кулдаун (D279) жжётся только после успешного probe
        (ask-ветка) либо успешного download. R17: без URL/текстов в логах."""
        source, url, native = self._resolve_tool_source(arguments, ctx)
        if source is None:
            return _download_status("error", "Некорректная ссылка")
        if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
            return _download_status("error", "Скачивание отключено")
        if ctx.bot is None:
            return _download_status("error", "Скачивание недоступно")
        # (а) нативный источник (F14): пересылка TG-файла без меню качества и
        # без download-кулдауна (паритет Fast-Track `_handle_native_media`).
        if source == "native":
            return await self._download_native(ctx, native)
        if self.deps.downloader is None:
            return _download_status("error", "Скачивание недоступно")
        # Follow-up R10.15-9: уважаем общий download-кулдаун роутера 4e
        # (тот же трекер через DI-провайдер; R17 — без URL/текстов в логах).
        cooldown = self._download_cooldown()
        if cooldown is not None and ctx.user_id is not None:
            cooldown_refresh(cooldown, hot.get("limits.download_cooldown",
                                               settings.DOWNLOAD_COOLDOWN))
            remaining = await cooldown_remaining(cooldown, ctx.chat_id,
                                                 ctx.user_id)
            if remaining > 0:
                return _download_status("error",
                                        "Скачивание на кулдауне — позже")

        # (а) явное качество ИЛИ прямой медиа-URL → без меню (ADR-1017-2 §2.3/§2.2).
        explicit = self._quality_arg(arguments.get("quality"))
        if explicit is not None or is_direct_media_url(url):
            return await self._download_now(ctx, url, explicit, cooldown)

        # (б) платформа → probe → меню качества (эталон Fast-Track :284-343).
        try:
            probe = await asyncio.wait_for(self.deps.downloader.probe(url),
                                           timeout=_PROBE_TOOL_TIMEOUT)
        except DownloadError as exc:
            # R17: только класс + safe-reason, БЕЗ str(exc) (может нести URL).
            logger.warning(
                "[tools] download probe failed | tool=download_media | "
                "error=%s reason=%s", type(exc).__name__, exc.reason)
            return await self._download_now(ctx, url, None, cooldown)
        except Exception as exc:
            logger.warning(
                "[tools] download probe failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            # (в) bounded fallback: одна попытка без меню (ADR-1017-2 §2.4).
            return await self._download_now(ctx, url, None, cooldown)

        # D279: touch только после успешного probe (fail кулдаун не жжёт).
        # Ревью-итер.1 L5: touch — ПОСЛЕ успешной отправки меню, чтобы провал
        # доставки не оставлял пользователя без меню, но с кулдауном.
        title = getattr(probe, "title", None)
        qualities = getattr(probe, "qualities", ()) or ()
        store_tool_download_pending(
            ctx.chat_id, ctx.user_id, url=url, title=title,
            qualities=qualities, trigger_message_id=ctx.reply_to_message_id)
        try:
            await self._send_quality_menu(ctx, title, qualities)
        except Exception as exc:
            logger.warning(
                "[tools] quality menu send failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            _TOOL_DL_PENDING.pop((ctx.chat_id, ctx.user_id), None)
            return _download_status("error", "Не удалось отправить меню качества")
        if cooldown is not None and ctx.user_id is not None:
            await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)
        return _download_status(
            "needs_quality",
            "Пользователю предложен выбор качества — меню с кнопками "
            "отправлено в чат")

    async def _download_native(self, ctx: ToolContext, native) -> str:
        """Нативная пересылка TG-файла (F14, ADR-1024-15 §2.1/§2.3):
        `fetch_media_to_tmp` → `send_media`; меню качества НЕ предлагается,
        download-кулдаун НЕ жжётся; лимит 2 ГБ (лимит Telegram). tmp чистится в
        finally. R17: без file_id/URL/локальных путей в логах."""
        path = None
        try:
            path = await asyncio.wait_for(
                native_media.download_to_tmp(
                    ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT),
                timeout=_DOWNLOAD_TOOL_TIMEOUT)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > _DOWNLOAD_NATIVE_MAX_BYTES:
                logger.warning(
                    "[tools] native download too big | tool=download_media | "
                    "bytes=%d", size)
                return _download_status("error",
                                        "Файл больше лимита Telegram")
            await send_media(ctx.bot, ctx.chat_id, path,
                             reply_to=ctx.reply_to_message_id)
        except asyncio.TimeoutError:
            logger.warning(
                "[tools] native download timeout | tool=download_media")
            return _download_status("error", "Таймаут нативного скачивания")
        except Exception as exc:
            logger.warning(
                "[tools] native download failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            return _download_status("error", "Не удалось переслать видео")
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return _download_status("success", "Файл успешно загружен в чат")

    async def _download_now(self, ctx: ToolContext, url: str, quality,
                            cooldown) -> str:
        """Скачать и отправить без меню (direct / явное качество / fallback).

        Успех — только после реальной отправки файла; провал download или
        send → честный `status:"error"` (без URL в логах, R17)."""
        path = None
        try:
            path = await asyncio.wait_for(
                self.deps.downloader.download(url, quality),
                timeout=_DOWNLOAD_TOOL_TIMEOUT)
        except DownloadError as exc:
            logger.warning(
                "[tools] download failed | tool=download_media | "
                "error=%s reason=%s", type(exc).__name__, exc.reason)
            return _download_status("error", "Не удалось скачать видео")
        except Exception as exc:
            logger.warning(
                "[tools] download failed | tool=download_media | error=%s",
                type(exc).__name__)
            return _download_status("error", "Не удалось скачать видео")
        if cooldown is not None and ctx.user_id is not None:
            # D279: успешный download жжёт кулдаун (провал — нет).
            await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)
        try:
            await send_media(ctx.bot, ctx.chat_id, path,
                             reply_to=ctx.reply_to_message_id)
        except Exception as exc:
            logger.warning(
                "[tools] media send failed | tool=download_media | error=%s",
                type(exc).__name__)
            return _download_status("error", "Не удалось отправить файл")
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return _download_status("success", "Файл успешно загружен в чат")

    def _quality_arg(self, raw):
        """enum-значение `quality` из аргументов → нормализованный `"max"`/`"1080"`.

        Мусор/пусто → None (не роняем: тогда работает меню). Нормализация —
        тот же `_normalize_quality` downloader'а, что и Fast-Track (T-1679)."""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return self.deps.downloader._normalize_quality(raw)
        except DownloadError:
            return None
        except Exception:
            logger.warning("[tools] invalid quality arg | tool=download_media")
            return None

    async def _send_quality_menu(self, ctx: ToolContext, title,
                                 qualities) -> None:
        """Инлайн-меню качества tool-пути `tdq:<height>` — единый хелпер
        `services.media_send.send_quality_menu` (T-1679; без дублирования меню
        с Fast-Track). R17: в лог — только chat_id и число качеств."""
        await send_quality_menu(
            ctx.bot, ctx.chat_id, reply_to=ctx.reply_to_message_id, title=title,
            qualities=qualities, callback_prefix=_TOOL_QUALITY_PREFIX)
        logger.info("[tools] download quality menu sent | chat=%s | qualities=%d",
                    ctx.chat_id, len(qualities))

    async def _inspect_runtime(self, arguments: dict,
                               ctx: ToolContext) -> str:
        """SELF-DIAG-01 D3: единый read-only диагностический вход.

        Один инструмент на все области; конкретная операция — зарегистрированный
        typed probe. Без LLM, без shell/SQL и без чтения чужого chat scope:
        ``chat_id`` берётся только из ``ctx``, аргументы модели проходят
        валидацию схемы probe. Никогда не бросает (контракт ToolRouter).
        """
        from services import diagnostic_collector as dc
        from services import runtime_probes as probes

        args = arguments if isinstance(arguments, dict) else {}
        allowed = {"area", "probe", "scope", "time_window", "cursor",
                   "arguments"}
        unknown = [key for key in args if key not in allowed]
        if unknown:
            return self._inspect_error("unknown_tool_argument", ctx)
        area = str(args.get("area") or "").strip()
        if area and area not in probes.AREAS:
            return self._inspect_error("unknown_area", ctx)
        probe = str(args.get("probe") or "").strip()
        scope = str(args.get("scope") or "current_chat").strip()
        if scope not in probes.REQUEST_SCOPES:
            return self._inspect_error("invalid_scope", ctx)
        cursor = str(args.get("cursor") or "").strip()
        op_args = args.get("arguments")
        if op_args is None:
            op_args = {}
        if not isinstance(op_args, dict):
            return self._inspect_error("arguments_must_be_object", ctx)
        try:
            collector = self._diagnostics()
        except Exception as exc:
            logger.warning("[tools] diagnostics init failed | error=%s",
                           type(exc).__name__)
            return "ОШИБКА inspect_runtime: коллектор недоступен"
        if not probe:
            catalog = probes.probe_catalog(deps=collector.deps, area=area)
            catalog["scope_values"] = list(probes.REQUEST_SCOPES)
            catalog["hint"] = (
                "call inspect_runtime again with area+probe; "
                "probe='investigate_incident' is the incident scenario")
            limit = collector.limits.max_output_chars
            while (len(json.dumps(catalog, ensure_ascii=False)) > limit
                   and catalog["probes"]):
                catalog["probes"].pop()
                catalog["truncated"] = True
            if catalog["probes"] or len(
                    json.dumps(catalog, ensure_ascii=False)) <= limit:
                return json.dumps(catalog, ensure_ascii=False)
            return json.dumps({
                "schema": "self-diag-01/d3-catalog-v1",
                "areas": list(probes.AREAS),
                "probes": [],
                "truncated": True,
                "reason_code": "output_budget_exceeded",
            }, ensure_ascii=False)
        request = dc.CollectionRequest(
            probe=probe, area=area, scope=scope,
            time_window=args.get("time_window"), cursor=cursor,
            arguments=op_args, chat_id=getattr(ctx, "chat_id", None),
            permission=getattr(ctx, "diagnostic_decision", None),
            request_id=secrets.token_hex(16))
        try:
            _, page = await collector.collect(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] inspect_runtime failed | probe=%s | "
                           "error=%s", probe, type(exc).__name__)
            return f"ОШИБКА inspect_runtime: {type(exc).__name__}"
        text = json.dumps(page, ensure_ascii=False)
        status = str(page.get("status") or "")
        reason = str(page.get("reason_code") or "")[:120]
        partial = status not in ("", "ok")
        signal: dict = {"partial": partial}
        if status == "unavailable":
            signal["status"] = "error"
            signal["error_code"] = reason or "runtime_unavailable"
        elif status == "permission_denied":
            signal["status"] = "denied"
            signal["error_code"] = reason or "permission_denied"
        if reason:
            signal["reason"] = reason
        refs = [str(src.get("source_id")) for src in page.get("sources") or ()
                if isinstance(src, dict) and src.get("source_id")]
        if refs:
            signal["evidence_refs"] = refs
        ctx.tool_result_signal = signal
        self._emit_inspect_event(ctx, page)
        if len(text) > collector.limits.max_output_chars:
            return json.dumps({
                "schema": "self-diag-01/d3-bundle-v1",
                "status": "degraded",
                "reason_code": "output_budget_exceeded",
                "probe": page.get("probe"),
                "truncated": True,
                "sources": [],
                "not_checked": ["output_budget_exceeded"],
            }, ensure_ascii=False)
        return text

    @staticmethod
    def _inspect_error(reason: str, ctx: ToolContext) -> str:
        """Структурный отказ валидатора без исполнения probes."""
        status = ("permission_denied"
                  if reason in ("invalid_scope", "argument_not_allowed")
                  else "unsupported")
        ctx.tool_result_signal = {
            "status": ("denied" if status == "permission_denied" else "error"),
            "error_code": reason[:64],
            "reason": reason[:120],
            "partial": True,
        }
        payload = {
            "schema": "self-diag-01/d3-bundle-v1",
            "status": status,
            "reason_code": reason,
            "sources": [],
            "not_checked": [reason],
            "access": {"chat_id": getattr(ctx, "chat_id", None)},
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _emit_inspect_event(ctx: ToolContext, page: dict) -> None:
        """Существующая телеметрия §13.3: код/числа, без payloads."""
        try:
            status = str(page.get("status") or "")
            outcome = ("success" if status in ("ok", "degraded")
                       else "failed" if status == "unavailable" else "skipped")
            level = ("INFO" if status == "ok" else "WARN")
            _mca_events.emit_mca_event(
                "inspect_runtime_called", outcome=outcome, level=level,
                component="self_diag",
                stage=str(page.get("probe") or "inspect_runtime")[:120],
                status=status[:40],
                duration_ms=int(page.get("latency_ms") or 0),
                chat_id=getattr(ctx, "chat_id", None))
        except Exception:      # pragma: no cover - телеметрия fail-open
            return

    def _status_service(self):
        try:
            from services.status_service import status as _status
            return _status
        except Exception:
            return None

    def _diagnostics(self):
        """Один collector на роутер (общий для inspect_runtime/get_bot_health)."""
        existing = getattr(self.deps, "diagnostics", None)
        if existing is not None:
            return existing
        from services.diagnostic_collector import DiagnosticCollector
        from services.runtime_probes import ProbeDeps, ProbeLimits

        health = self.deps.health
        db = self.deps.db or getattr(self.deps.memory, "db", None)
        collector = DiagnosticCollector(
            deps=ProbeDeps(
                db=db, memory=self.deps.memory,
                logs_fetcher=getattr(health, "fetcher", None),
                status=self._status_service()),
            limits=ProbeLimits.from_env())
        self.deps.diagnostics = collector
        return collector

    async def _get_bot_health(self, arguments: dict, ctx: ToolContext) -> str:
        """Здоровье бота: тот же путь, что роутер 0g — CheckupLogsFetcher.fetch
        → CheckupService.checkup. Кулдаун не применяем (вызов по интенту LLM;
        ограничение — лимиты tool-loop). R17: без текстов логов.

        Follow-up R10.15-2: уважаем master-флаг модуля (`flags.checkup_enabled`,
        тот же гейт, что `handlers/checkup.py`) — при выключенном модуле
        инструмент не делает сетевой/LLM-вызов, а возвращает честную ошибку."""
        if not hot.get("flags.checkup_enabled", settings.CHECKUP_ENABLED):
            return "ОШИБКА get_bot_health: модуль выключен"
        # SELF-DIAG-01 D6 (`SD1-D6-17`): счётчик реальных вызовов входа.
        self._emit_diag_tool_event("get_bot_health_called", ctx,
                                   status="called")
        health = self.deps.health
        if health is None or getattr(health, "service", None) is None \
                or getattr(health, "fetcher", None) is None:
            return "ОШИБКА get_bot_health: сервис недоступен"
        try:
            logs, used_fallback = await health.fetcher.fetch()
            # SELF-DIAG-01 D3 (§2.1 п.1, AC-04): тот же collector, что у
            # `inspect_runtime`, отдаёт структурированные факты и в этот вход.
            # Ошибка collector'а не отменяет исправный чекап (graceful
            # degradation): отчёт строится на логах, как раньше.
            facts_text = ""
            try:
                collector = self._diagnostics()
                _, facts_text = await collector.collect_for_checkup(
                    logs_text=logs, used_fallback=used_fallback,
                    chat_id=getattr(ctx, "chat_id", None),
                    permission=getattr(ctx, "diagnostic_decision", None))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[tools] get_bot_health facts failed | "
                               "error=%s", type(exc).__name__)
                facts_text = ""
            payload = (facts_text + "\n" + logs) if facts_text else logs
            report = await health.service.checkup(payload, used_fallback)
        except Exception as exc:
            logger.warning("[tools] get_bot_health failed | error=%s",
                           type(exc).__name__)
            return f"ОШИБКА get_bot_health: {type(exc).__name__}"
        text = str(report or "").strip()
        if not text:
            return "ОШИБКА get_bot_health: пустой отчёт"
        return _truncate(text, _MEMORY_MAX_SYMBOLS)

    async def _get_recent_history(self, arguments: dict,
                                  ctx: ToolContext) -> str:
        """F9 (spec §2-§5): сырая хронологическая стенограмма недавних
        сообщений чата («Имя: текст») — кратковременная память, НЕ RAG.

        P0-HA TRUNC-PAGES (§4.2 директивы + архконтракт §1): символьной
        обрезки НЕТ. Если выборка помещается в одну страницу — возвращается
        целиком; иначе — структурированная страница целых сообщений с
        машиной-читаемой головой @@HISTORY_SAMPLE (id выборки, границы,
        requested/available/processed/remaining, has_next, подписанный
        cursor). Маршрутизация (жёсткий порядок):
        1) непустой ``cursor`` → только продолжение этой выборки (путь B и
           дефолт запрещены; неверный cursor НЕ подменяется depth=50);
        2) ``ctx.history_sample`` задан → страница этой выборки;
        3) явный ``depth`` → путь A (якорь фиксируется этим вызовом);
        4) ``extract_history_depth`` нашёл N в тексте → путь A с этим N
           (защита simple-пути, который шлёт только query);
        5) иначе ``query`` → путь B (FTS) без изменений;
        6) иначе depth = 50 (дефолт не максимум).

        НЕ бросает: ошибка/пусто/сбой → структурная строка (R17: в логах
        только chat_id/sample_id/счётчики/has_next/reason, без текстов/URL/
        имён)."""
        args = arguments if isinstance(arguments, dict) else {}
        db = self.deps.db if self.deps.db is not None \
            else getattr(self.deps.memory, "db", None)
        # 1. Cursor → продолжение выборки, только он (fail closed).
        cursor_raw = str(args.get("cursor") or "").strip()
        if cursor_raw:
            try:
                return await asyncio.wait_for(
                    self._history_continue(ctx, db, cursor_raw),
                    timeout=_HISTORY_TOOL_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[tools] get_recent_history timeout | chat=%s",
                               ctx.chat_id)
                return "ОШИБКА get_recent_history: timeout"
            except asyncio.CancelledError:
                raise
            except _HistoryCursorError as exc:
                logger.warning(
                    "[tools] get_recent_history cursor rejected | chat=%s | "
                    "reason=%s", ctx.chat_id, exc.reason)
                return f"ОШИБКА get_recent_history: {exc.reason}"
            except Exception as exc:
                logger.warning(
                    "[tools] get_recent_history failed | chat=%s | error=%s",
                    ctx.chat_id, type(exc).__name__)
                return f"ОШИБКА get_recent_history: {type(exc).__name__}"

        # 2-6. Маршрутизация без cursor.
        depth_raw = args.get("depth")
        explicit_depth = (None if depth_raw in (None, "")
                          else _history_depth(depth_raw))
        query_arg = str(args.get("query") or "").strip()
        query_text = query_arg or str(getattr(ctx, "query", "") or "").strip()
        extracted_depth = extract_history_depth(query_text)
        bound = self._history_bound_from_ctx(ctx)
        if bound is not None:                       # 2. выборка хода
            requested = _bound_int(bound.get("requested"), 0)
            if requested < 1:
                bound, requested = None, 0
        elif explicit_depth is not None:            # 3. явный depth
            requested = explicit_depth
        elif extracted_depth is not None:           # 4. N в тексте хода
            requested = extracted_depth
        else:
            requested = 0
        if requested < 1 and query_text:            # 5. путь B (FTS)
            try:
                fetched, lines = await asyncio.wait_for(
                    self._recent_history_by_query(ctx, query_text),
                    timeout=_HISTORY_TOOL_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[tools] get_recent_history timeout | chat=%s",
                               ctx.chat_id)
                return "ОШИБКА get_recent_history: timeout"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[tools] get_recent_history failed | chat=%s | error=%s",
                    ctx.chat_id, type(exc).__name__)
                return f"ОШИБКА get_recent_history: {type(exc).__name__}"
            # P0-HA §4.1: путь B больше НЕ проходит через символьную обрезку —
            # выборка ограничена собственным FTS-лимитом (_HISTORY_SEARCH_LIMIT).
            text = "\n".join(lines)
            if not lines:
                logger.info("[tools] get_recent_history | chat=%s | mode=query "
                            "| fetched=%d | count=0 | out_chars=0",
                            ctx.chat_id, fetched)
                return _HISTORY_EMPTY
            logger.info("[tools] get_recent_history | chat=%s | mode=query | "
                        "fetched=%d | count=%d | out_chars=%d",
                        ctx.chat_id, fetched, len(lines), len(text))
            return text
        if requested < 1:                           # 6. дефолт (не максимум)
            requested = _HISTORY_DEFAULT_DEPTH
        # Путь A: страница выборки (якорь фиксируется при необходимости).
        try:
            if bound is None:
                bound = await asyncio.wait_for(
                    capture_history_sample(db, ctx.chat_id, requested),
                    timeout=_HISTORY_TOOL_TIMEOUT)
                if bound is None:
                    logger.info("[tools] get_recent_history | chat=%s | "
                                "fetched=0 | count=0 | out_chars=0",
                                ctx.chat_id)
                    return _HISTORY_EMPTY
            page = await asyncio.wait_for(
                self._history_read_page(db, bound, after=None,
                                        projection=getattr(ctx, "speech", None)),
                timeout=_HISTORY_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] get_recent_history timeout | chat=%s",
                           ctx.chat_id)
            return "ОШИБКА get_recent_history: timeout"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[tools] get_recent_history failed | chat=%s | error=%s",
                ctx.chat_id, type(exc).__name__)
            return f"ОШИБКА get_recent_history: {type(exc).__name__}"
        return self._format_history_page(bound, page, processed_before=0)

    def _history_bound_from_ctx(self, ctx: ToolContext) -> dict | None:
        """Граница выборки хода (архконтракт §0: setattr ``tool_ctx.history_
        sample``; волна SEGMENTS ставит её до сборки контекста). Кривой/чужой
        объект игнорируется → свежий захват (это новый ход, не подмена
        продолжения)."""
        bound = getattr(ctx, "history_sample", None)
        if not isinstance(bound, dict):
            return None
        required = ("sample_id", "anchor_ts", "anchor_id", "oldest_ts",
                    "oldest_id", "requested", "available")
        if any(key not in bound for key in required):
            return None
        if _bound_int(bound.get("available"), 0) < 1 \
                or _bound_int(bound.get("requested"), 0) < 1:
            return None
        normalized = dict(bound)
        normalized.setdefault("chat_id", int(ctx.chat_id))
        return normalized

    async def _history_read_page(self, db, bound: dict, *,
                                 after: tuple | None,
                                 projection=None) -> dict:
        """Одна страница выборки: ASC-чтение вперёд от точки after по окну
        (keyset по timestamp+id через существующий reader wave 1), LIMIT
        _HISTORY_PAGE_ROWS целых сообщений. Тел больше страницы не читается и
        в памяти не копится."""
        if db is None or not hasattr(db, "get_recent_messages"):
            raise RuntimeError("db недоступен")
        rows = await db.get_recent_messages(
            int(bound["chat_id"]), _HISTORY_PAGE_ROWS,
            anchor=_history_window(bound), after=after)
        rows = list(rows or [])
        page_from = ""
        page_to = ""
        if rows:
            first, last = rows[0], rows[-1]
            page_from = (f"{_row_field(first, 'timestamp')}:"
                         f"{_row_field(first, 'id')}")
            page_to = (f"{_row_field(last, 'timestamp')}:"
                       f"{_row_field(last, 'id')}")
        # P0-HA волна 4 (блокер 2 review-w4): строки страницы выборки несут
        # Telegram user_id (сравнение людей по uid, не по id сообщения).
        lines = self._history_lines(rows, with_user_id=True,
                                    projection=projection)
        return {"rows": rows, "lines": lines, "page_from": page_from,
                "page_to": page_to,
                "fetched": len(rows)}

    async def _history_continue(self, ctx: ToolContext, db,
                                cursor_raw: str) -> str:
        """Продолжение по cursor: проверка подписи/чата/срока/якоря — fail
        closed (архконтракт §1). Следующая страница перечитывается из БД тем
        же предикатом; тел между вызовами не хранится. Счётчики выборки
        (available/processed) берутся из подписанного cursor, а не живым
        COUNT: иначе удалённые между страницами строки молча ужали бы
        выборку до «полной» (ревью H14). Обещанный остаток сверяется с
        живыми строками после точки курсора; выживших меньше обещанного →
        incomplete=1/reason=tail_missing, строки всё равно отдаются."""
        fields, reason = _history_cursor_decode(cursor_raw, ctx.chat_id)
        if fields is None:
            raise _HistoryCursorError(reason or "unknown_cursor")
        if not await _history_anchor_exists(db, fields):
            raise _HistoryCursorError("anchor_missing")
        after = (fields["after_ts"], fields["after_id"])
        processed_before = int(fields["processed"])
        expected_remaining = max(0, int(fields["available"]) - processed_before)
        survivors_after = await _history_count_in_window(db, fields,
                                                         up_to=None, after=after)
        if survivors_after is None:
            # Счётчики без БД не выдумываются: честный структурированный отказ.
            raise _HistoryCursorError("db_error")
        bound = {
            "sample_id": fields["sample_id"], "chat_id": fields["chat_id"],
            "anchor_ts": fields["anchor_ts"], "anchor_id": fields["anchor_id"],
            "oldest_ts": fields["oldest_ts"], "oldest_id": fields["oldest_id"],
            "requested": fields["requested"],
            "available": int(fields["available"]),  # захваченный available
            "exp": fields["exp"],
        }
        page = await self._history_read_page(
            db, bound, after=after, projection=getattr(ctx, "speech", None))
        return self._format_history_page(bound, page,
                                         processed_before=processed_before,
                                         expected_remaining=expected_remaining,
                                         survivors_after=survivors_after)

    def _format_history_page(self, bound: dict, page: dict,
                             *, processed_before: int,
                             expected_remaining: int | None = None,
                             survivors_after: int | None = None) -> str:
        """Голова @@HISTORY_SAMPLE (компактная, стабильная, разбирается кодом,
        без текста сообщений) + канонические строки целых сообщений +
        хвостовой сентинел (не «…», чтобы tool_result не помечал truncated).
        Отдельная страница никогда не подаётся как полная выборка: при
        has_next=1 / incomplete=1 это видно в голове (REQ-HA-PAGES-NOT-FULL).

        ``expected_remaining``/``survivors_after`` — только на продолжении по
        cursor: обещанный остаток выборки (из подписанного cursor) против
        живого числа строк после точки курсора. Живых строк меньше
        обещанных → incomplete=1/reason=tail_missing; выжившие строки всё
        равно отдаются, счётчик processed не пересчитывается живым COUNT —
        потеря названа, не скрыта (ревью H14). Первая страница поведение не
        меняет (H7: короткий архив честно полон)."""
        fetched = int(page.get("fetched") or 0)
        processed = processed_before + fetched
        available = _bound_int(bound.get("available"), 0)
        remaining = max(0, available - processed)
        has_next = remaining > 0 and fetched > 0
        incomplete = 0
        reason = ""
        if expected_remaining is not None and survivors_after is not None:
            if survivors_after < expected_remaining:
                # H14: часть недочитанного хвоста удалена из БД (retention)
                # — promised остаток выборки недостижим, неполнота объявлена
                # явно; выжившие строки ниже всё равно отдаются.
                incomplete = 1
                reason = "tail_missing"
            # has_next — по живым строкам: цепочка дочитывает выживших,
            # потеря уже названа в этой голове.
            has_next = fetched > 0 and survivors_after > fetched
            if fetched == 0 and remaining > 0 and incomplete == 0:
                # Гонка: окно опустело между COUNT и чтением страницы.
                has_next = False
                incomplete = 1
                reason = "anchor_missing"
        elif fetched == 0 and remaining > 0:
            # Остаток выборки исчез из БД (retention) — честная неполнота,
            # молчаливого обрыва нет (REQ-HA-INCOMPLETENESS-REPORTING).
            has_next = False
            incomplete = 1
            reason = "anchor_missing"
        cursor_field = ""
        if has_next and page.get("page_to"):
            to_ts, _, to_id = str(page["page_to"]).partition(":")
            # Свежий захват: exp = сейчас + TOOL_CHAIN_TIMEOUT_SECONDS;
            # продолжение наследует срок исходной выборки (не новый TTL).
            cursor_field = _history_cursor_encode(bound, int(to_ts), int(to_id),
                                                  processed)
        header = "\n".join((
            _HISTORY_SAMPLE_HEADER,
            f"sample_id={bound.get('sample_id') or ''}",
            f"requested={_bound_int(bound.get('requested'), 0)}",
            f"available={available}",
            f"processed={processed}",
            f"remaining={remaining}",
            f"has_next={1 if has_next else 0}",
            f"boundary_to={_bound_int(bound.get('anchor_ts'))}:"
            f"{_bound_int(bound.get('anchor_id'))}",
            f"boundary_from={_bound_int(bound.get('oldest_ts'))}:"
            f"{_bound_int(bound.get('oldest_id'))}",
            f"page_from={page.get('page_from') or ''}",
            f"page_to={page.get('page_to') or ''}",
            f"incomplete={incomplete}",
            f"reason={reason}",
            f"cursor={cursor_field}",
            _HISTORY_HEADER_END,
        ))
        lines = list(page.get("lines") or [])
        text = header
        if lines:
            text += "\n" + "\n".join(lines)
        text += "\n" + _HISTORY_SAMPLE_END
        # P0-HA (§3.3): честный охват в логах — fetched (страница из БД) vs
        # count (строк в стенограмме страницы); без текстов/URL/имён (R17).
        logger.info("[tools] get_recent_history | chat=%s | sample=%s | "
                    "page_from=%s | page_to=%s | fetched=%d | count=%d | "
                    "processed=%d | remaining=%d | has_next=%d | out_chars=%d",
                    bound.get("chat_id"), bound.get("sample_id"),
                    page.get("page_from") or "-", page.get("page_to") or "-",
                    fetched, len(lines), processed, remaining,
                    1 if has_next else 0, len(text))
        return text

    async def _recent_history_by_query(self, ctx: ToolContext, query: str
                                       ) -> tuple[int, list[str]]:
        """Путь B: FTS по L1 + фильтр окна последних часов →
        (fetched, ASC-стенограмма)."""
        since = int(time.time()) - _HISTORY_QUERY_WINDOW_SECONDS
        rows = await self.deps.memory.search_long_term(
            ctx.chat_id, keywords(query), limit=_HISTORY_SEARCH_LIMIT)
        # T-678: aiosqlite.Row не имеет .get → нормализация в dict.
        rows = [dict(row) for row in rows]
        rows = [r for r in rows if int(r.get("timestamp") or 0) >= since]
        rows.sort(key=lambda r: int(r.get("timestamp") or 0))
        return len(rows), self._history_lines(
            rows, projection=getattr(ctx, "speech", None))

    def _history_lines(self, rows, *, with_user_id: bool = False,
                       projection=None) -> list[str]:
        """Строки smart_messages → канонические строки контекста (10.20,
        БЛОК 0, ADR-1020-1 ред. 3, точка 8): «[ts | Имя | ID | Переслано]:
        текст» (R16-каскад имён; пустой текст без медиа пропускается;
        медиа-событие — маркером).

        P0-HA волна 4 (блокер 2 review-w4): ``with_user_id=True`` — только
        строки КОЛИЧЕСТВЕННОЙ ВЫБОРКИ (путь A `get_recent_history`) несут
        Telegram user_id тем же приёмом, что `_speaker_tag` («Имя [uid]»):
        анализ последних N различает одинаковые имена разных участников и
        сравнивает людей по uid, а не по id сообщения. Путь B (FTS-query) и
        прочие вызовы — прежний формат (байт-паритет).

        EVOL v5 (§4.1 P5 / §4.2 п.2): ``projection`` — общая проекция хода.
        Тогда uid различается `U`-меткой (а не числом в скобках), а id
        сообщения — меткой прогона; автор, абсолютная дата, `Переслано:` и
        медиа-тип остаются. ``None``/рубильник OFF → сырой канон байт-в-байт."""
        lines: list[str] = []
        for row in rows or []:
            try:
                item = dict(row)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or "").strip()
            media_type = ""
            if not text:
                media = str(item.get("media_type") or "").strip()
                if not media or media == "text":
                    continue
                media_type = media
                text = f"[медиа: {media}]"
            forward_source = (item.get("forward_source")
                              if item.get("is_forward") else None)
            author = self._resolve_name(item)
            if with_user_id:
                uid = item.get("user_id")
                if uid not in (None, "", 0):
                    author = f"{author} [{uid}]"
            if projection is not None:
                if speech_projection_enabled():
                    item_id = resolve_item_id(
                        tg_message_id=item.get("tg_message_id"),
                        message_id=item.get("id"))
                    if media_type:
                        from services.media_marker import media_marker
                        text = media_marker(media_type, item_id,
                                            projection=projection)
                    lines.append(format_speech_item(
                        ts=item.get("timestamp"),
                        author=self._resolve_name(item),
                        author_uid=item.get("user_id"),
                        item_id=item_id, forward_source=forward_source,
                        text=text, kind="msg", projection=projection))
                    continue
            lines.append(format_context_item(
                ts=item.get("timestamp"), author=author,
                item_id=resolve_item_id(
                    tg_message_id=item.get("tg_message_id"),
                    message_id=item.get("id")),
                forward_source=forward_source, text=text, kind="msg"))
        return lines

    # ── compile_lore_story (раунд 10.20, БЛОК 1, ADR-1020-4 п.1-4, T-1887) ──

    async def _chat_timezone(self, chat_id: int | None) -> str:
        """S10.20-14 → UR-C-CLOCK: tz чата через ЕДИНСТВЕННЫЙ резолвер
        ChatClock (каноническая цепочка UR-24.3: per-chat canonical →
        legacy summary → global → GOODMORNING_TZ(env) → factory). Второй
        копии цепочки нет (UR-25: без независимых резолверов). Возвращает
        ВАЛИДНОЕ имя tz (неизвестное → явный UTC-fallback)."""
        from services.canonical_context import resolve_timezone
        try:
            from services import chat_clock as _cclock
            tz, _source, _cv = await _cclock.resolve_chat_timezone(chat_id)
            return resolve_timezone(tz, fallback="UTC")
        except Exception:
            logger.warning("[tools] chat tz resolve failed — UTC | chat=%s",
                           chat_id, exc_info=True)
            return "UTC"


    async def _compile_lore_story(self, arguments: dict,
                                  ctx: ToolContext) -> str:
        """«Летописец»: Шаг А (граф) + Шаг Б (хронология) → JSON-контракт →
        изолированный синтез своим каноном `LORE_STORY_SYSTEM_PROMPT`
        (LoreCompilerService) → готовый рассказ. При успехе ставит
        ``ctx.lore_compiled = True`` (сигнал доставки, ADR-1020-6 п.2).

        Гейт: ``flags.lore_compiler_enabled`` (О3, default ON) — OFF → честная
        строка отключения, LLM не вызывается. НЕ бросает: таймаут/сбой →
        «ОШИБКА …» (диалог не роняется, NFR-4). R17: без текстов истории."""
        if not await resolve_lore_compiler_flag(ctx.chat_id):
            return "Инструмент compile_lore_story отключен."
        topic = self._require_str(arguments, "topic") or str(ctx.query or "")
        topic = topic.strip()
        if not topic:
            return "ОШИБКА compile_lore_story: не указан topic"
        db = self.deps.db if self.deps.db is not None \
            else getattr(self.deps.memory, "db", None)
        if db is None or self.deps.llm is None:
            return "ОШИБКА compile_lore_story: сервис недоступен"
        try:
            from services.lore_compiler_service import LoreCompilerService
            tz_name = await self._chat_timezone(ctx.chat_id)
            service = LoreCompilerService(db, self.deps.llm, self.deps.aliases,
                                          tz_name=tz_name)
            result = await asyncio.wait_for(
                service.compile(ctx.chat_id, topic), timeout=_LORE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] compile_lore_story timeout | chat=%s",
                           ctx.chat_id)
            return "ОШИБКА compile_lore_story: timeout"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] compile_lore_story failed | chat=%s | "
                           "error=%s", ctx.chat_id, type(exc).__name__)
            return f"ОШИБКА compile_lore_story: {type(exc).__name__}"
        status = str(result.get("status") or "")
        if status != "ok":
            return str(result.get("message")
                       or "ОШИБКА compile_lore_story: не удалось собрать историю")
        story = str(result.get("story") or "").strip()
        if not story:
            return "ОШИБКА compile_lore_story: пустая история"
        ctx.lore_compiled = True
        ctx.lore_story = story
        # MCA-15 (T-4930/T-4932, §7.3): свежая компиляция — её измерение
        # становится NumericClaim хода (числа истории проверяемы); UPD-ветка
        # `unchanged` отдаёт СТАРЫЕ агрегаты — помечаем на перепроверку
        # (`lore_stats_recheck_flagged`), lore не удаляется; непроверенные
        # числа снимет финальный numeric-гард direct.
        metric_result = result.get("metric_result")
        if metric_result is not None:
            ctx.metric_results.append(metric_result)
        stats_recheck = bool(result.get("stats_recheck"))
        if stats_recheck:
            ctx.lore_stats_recheck = True
            _mca_events.emit_mca_event(
                "chat_statistics", outcome="skipped",
                component="tool_router", stage="claim_check",
                reason_code="lore_stats_recheck_flagged",
                chat_id=ctx.chat_id)
            logger.info("[tools] lore stats recheck flagged | chat=%s",
                        ctx.chat_id)
        payload = json.dumps({
            "status": "ok",
            "is_update": bool(result.get("is_update")),
            "previous_story_at": result.get("previous_story_at"),
            "story": story,
            "stats_recheck": stats_recheck,
        }, ensure_ascii=False)
        if getattr(ctx, "lore_verbatim_instruction", True):
            return f"{payload}\n\n{_LORE_RETURN_INSTRUCTION}"
        return payload

    async def _generate_image(self, arguments: dict, ctx: ToolContext) -> str:
        """Раунд 10.23 (F5, ADR-1023-5): генерация изображения по промпту.

        Бэкенд САМ отправляет изображение в чат (`services.image_generation`),
        модели возвращается короткий JSON-статус (прецедент `download_media`).
        Гейт модуля: env-рубильник + каталоговый тумблер (per-chat). Провал
        провайдера/бюджета → циничная отмазка в статусе, бот жив. R17: без
        промпта/URL/ключа в логах.

        A3 (§21/ADR-1026-16 D3/D2/D4): (1) ПЕРВЫМ делом проверяется
        авторитетный маркер прогона ``ctx.image_request_handled`` — True →
        ``{"status":"skipped","reason":"already_handled"}`` без генерации/
        списания бюджета (двойная генерация исключена); гейтился киль-свитчем
        ``UNIFIED_IMAGE_REQUEST_ENABLED``; (2) запрос строится как единый
        ``ImageRequest`` (source="tool") → единый раннер → существующий
        ``generate_and_send``; OFF — прежний прямой вызов; (3) валидация
        аргументов fail-closed (статус `error` НЕ роняет цикл, FAIL-closed
        исключений нет); (4) реальный `reason` генератора доводится —
        вымышленный «отказ модели» не подставляется."""
        # D3, слой 2: маркер прогона — до любого гейта модуля/генерации.
        if image_generation.unified_image_request_enabled() \
                and getattr(ctx, "image_request_handled", False):
            logger.info("[tools] generate_image skipped | reason="
                        "already_handled | chat=%s", ctx.chat_id)
            return json.dumps(
                {"status": "skipped", "reason": "already_handled",
                 "message": "Изображение на этом ходу уже обработано "
                            "(генерация выполняется один раз)"},
                ensure_ascii=False)
        if not await image_generation.resolve_module_enabled(ctx.chat_id):
            return json.dumps({"status": "error",
                               "message": "Генерация изображений отключена"},
                              ensure_ascii=False)
        prompt = self._require_str(arguments, "prompt")
        if not prompt:
            return json.dumps({"status": "error",
                               "message": "Не указан prompt"},
                              ensure_ascii=False)
        if image_generation.unified_image_request_enabled():
            request = image_generation.build_image_request(
                "tool", ctx.chat_id, prompt,
                requester_id=getattr(ctx, "user_id", None),
                original_message_id=getattr(ctx, "reply_to_message_id", None))
            # A4 (ADR-1026-19 D1/D2/§7.3): тот же helper, что у direct-пути;
            # память читается только при ON kill-switch и разрешённом субъекте.
            if image_generation.image_context_memory_enabled():
                deps = getattr(self, "deps", None)
                data = await image_context_memory.build_image_memory_context(
                    chat_id=ctx.chat_id, user_request=prompt,
                    requester_id=getattr(ctx, "user_id", None),
                    aliases=getattr(deps, "aliases", None),
                    db=getattr(deps, "db", None),
                    memory=getattr(deps, "memory", None))
                image_context_memory.attach_image_memory(request, data)
            result = await image_generation.run_image_request(
                request, bot=ctx.bot,
                correlation_id=getattr(ctx, "correlation_id", None))
        else:
            # A5 (ADR-1026-17 D3): source="tool" — idem-дискриминатор
            # входа (резерв/журнал); генератор и контракт прежние.
            # CFG-02B (§02B.3): участник — тот же вход, что у A3-ветки.
            request = None
            result = await image_generation.generate_and_send(
                ctx.bot, ctx.chat_id, prompt,
                reply_to_message_id=ctx.reply_to_message_id,
                correlation_id=getattr(ctx, "correlation_id", None),
                source="tool",
                user_id=getattr(ctx, "user_id", None))
        # MCA-11 (ADR-1028-13 D3/D4): out-of-band сигнал медиа-пути —
        # `delivery_unknown` при неясной Telegram-доставке (без слепого
        # повтора, A21) и usage-детализация (цена провайдера не заявляется
        # нулём: unknown ≠ 0). Модельно-видимый payload не меняется.
        signal: dict = {}
        if _tool_result.cost_accounting_enabled():
            signal["usage"] = {
                "input_tokens": 0, "output_tokens": 0, "cached_tokens": None,
                "cost_usd": None, "price_known": False, "currency": "USD",
                "price_version": "unknown", "source": "image"}
        if (not result.ok and result.reason == "send_failed"
                and _tool_result.delivery_guard_enabled()):
            signal.update({"status": _tool_result.STATUS_DELIVERY_UNKNOWN,
                           "error_code": "delivery_unknown",
                           "retryable": False})
        if signal:
            _tool_result.set_signal(ctx, signal)
        if result.ok:
            # SOUL-1 W10 (SOUL-AMD.5.12): «вызов успешно завершён» — отдельное
            # наблюдаемое состояние (result.ok=False при send_failed).
            try:
                from services import capability_registry as _caps
                _caps.record_outcome("image_generation", chat_id=ctx.chat_id,
                                     ok=True, code=str(result.reason or ""))
            except Exception:      # pragma: no cover
                pass
            # P0 MEME-IMAGE-ONLY (owner 02.11.2026): успешная НОВАЯ отправка
            # изображения — единственный ответ хода; повтор («already») новой
            # доставки не делал и ответом хода не является.
            if str(getattr(result, "reason", "") or "") != "already":
                try:
                    ctx.image_delivered = True
                except Exception:      # pragma: no cover
                    pass
            payload = {"status": "success",
                       "message": "Изображение сгенерировано и отправлено в чат"}
            note = _image_memory_note(request)
            if note:
                payload["note"] = note
            # ADD-TR.4 (ADTR-POSTGEN, M-ADTR-POSTGEN-DEFECT): Writer получает
            # data-only распознавание ФАКТИЧЕСКИ отправленного bitmap — только
            # по нему допустимы фразы «получилось X, Y»; при OFF/unavailable/
            # pending — честный статус без описания. Replay («already») не
            # анализируется: новой отправки не было. Bounded/fail-open.
            if str(getattr(result, "reason", "") or "") != "already":
                try:
                    from services import postgen_vision
                    outcome = await postgen_vision.analyze_generated_image(
                        getattr(result, "content", None) or b"",
                        chat_id=ctx.chat_id,
                        correlation_id=getattr(ctx, "correlation_id", None))
                    analysis = postgen_vision.tool_payload(outcome)
                    if analysis is not None:
                        payload["image_analysis"] = analysis
                except Exception:      # pragma: no cover - fail-open
                    logger.warning("[tools] postgen analysis skipped — "
                                   "fail-open | chat=%s", ctx.chat_id,
                                   exc_info=True)
            return json.dumps(payload, ensure_ascii=False)
        logger.info("[tools] generate_image failed | chat=%s | reason=%s",
                    ctx.chat_id, result.reason)
        # SOUL-1 W10 (SOUL-AMD.5.15/5.17): сообщение модели — управляемый
        # Factory Default по РЕАЛЬНОМУ коду отказа (реестр
        # `message.image_failure.*`); успех/доставка не заявляются, если их не
        # подтвердил исполнитель. Реальный `reason` доводится как есть.
        try:
            from services import capability_registry as _caps
            _caps.record_outcome(
                "image_generation", chat_id=ctx.chat_id, ok=False,
                code=str(result.reason or ""))
            _msg, _block_id, _src = _caps.failure_message_for_reason(
                str(result.reason or ""))
        except Exception:      # pragma: no cover - реестр не рвёт цикл
            _msg, _block_id = "Генерация не удалась", ""        # CFG-02A (§02A.5): исчерпание СУТОЧНОЙ квоты — честное фактическое
        # время следующего сброса (единый helper с direct-путём; не cooldown).
        if str(result.reason or "") == "budget":
            _note = image_generation.image_quota_reset_note(ctx.chat_id)
            if _note:
                _msg = f"{_msg} {_note}"
        # CFG-02B (§02B.6/§02B.7): отказ короткой паузы — фактический остаток
        # («снова можно через …»); при исчерпании обоих лимитов — обе строки
        # (тот же helper, что у direct-пути; второго текста нет).
        try:
            _freq_note = await image_generation.image_denial_details(
                result, ctx.chat_id, user_id=getattr(ctx, "user_id", None),
                # дневной сброс выше уже назван для reason='budget' — не дублим
                daily_already_shown=(str(result.reason or "") == "budget"))
        except Exception:      # pragma: no cover - диагностика не рвёт цикл
            _freq_note = ""
        if _freq_note:
            _msg = f"{_msg} {_freq_note}"
        return json.dumps(
            {"status": "error", "reason": result.reason,
             "message": _msg, "message_id": _block_id},
            ensure_ascii=False)

    # ── ASAP5 §20 (edit-route): изменение СУЩЕСТВУЮЩЕГО изображения ────────

    #: kinds исходника, пригодные для edit (растровые; preview-покрытые
    #: носители дают обложку того же kind — W1 §7.2).
    _EDIT_SOURCE_KINDS = frozenset({"photo", "document", "sticker",
                                    "video_preview", "animation_preview"})

    async def _edit_image(self, arguments: dict, ctx: ToolContext) -> str:
        """ASAP5 §20 (edit-route): пользовательский маршрут Direct Chat →
        СУЩЕСТВУЮЩИЙ ``media_execution`` edit-путь
        (``detect_adapter`` → ``submit_edit`` → ``cover_style_edit.edit_image``).

        Изменение исходника ≠ создание нового: генерация здесь НЕ вызывается,
        новая независимая генерация не выдаётся за изменение оригинала.
        Исходник: ``target`` (chat_id+message_id) из аргументов, иначе
        reply-цель хода; активы — канонический реестр ``mca_media_assets``,
        скачивание — существующий ``mca_vision.download_telegram_file``.
        Операция выбирается через Capability Registry (`image_edit`); модель
        без edit-capability получает честный ``unsupported`` (не генерацию).
        Результат отправляется существующей доставкой
        (`telegram_send.send_photo`), исход связывается с запросом (reply).
        Ошибка никогда не выдаётся за успешное редактирование. R17: без
        промпта/URL/ключа в логах."""

        def _err(reason: str, message: str) -> str:
            try:
                from services import capability_registry as _caps
                _caps.record_outcome("image_edit", chat_id=ctx.chat_id,
                                     ok=False, code=reason)
                _msg, _block_id, _src = _caps.failure_message_for_reason(
                    reason)
            except Exception:      # pragma: no cover - реестр не рвёт отказ
                _msg, _block_id = message, ""
            return json.dumps(
                {"status": "error", "reason": reason, "message": _msg,
                 "message_id": _block_id}, ensure_ascii=False)

        if not await image_generation.resolve_module_enabled(ctx.chat_id):
            return _err("module_disabled", "Генерация изображений отключена")
        # Операция выбирается через Capability Registry: модель без
        # edit-capability → честный unsupported (спекулятивная генерация
        # вместо edit запрещена §20).
        try:
            from services import capability_registry as _capreg
            state = await _capreg.resolve("image_edit", ctx.chat_id)
            if state.status == "unsupported":
                return _err("edit_unsupported",
                            "Модель не умеет редактировать изображения")
            if state.status != "ready":
                # Только ПОДТВЕРЖДЁННАЯ capability ведёт к исполнению (§20:
                # операция выбирается реестром); не-ready → честный отказ.
                return _err(state.reason_code or state.status,
                            "Редактирование сейчас недоступно")
        except asyncio.CancelledError:
            raise
        except Exception:      # pragma: no cover - реестр fail-open
            pass
        prompt = self._require_str(arguments, "prompt")
        if not prompt:
            return _err("empty_prompt", "Не указан prompt")
        # ── Исходник: target из аргументов → reply-цель хода ─────────────
        target = arguments.get("target") if isinstance(arguments, dict) \
            else None
        src_chat = src_msg = None
        if isinstance(target, dict):
            try:
                src_chat = int(target.get("chat_id"))
                src_msg = int(target.get("message_id"))
            except (TypeError, ValueError):
                src_chat = src_msg = None
            if src_chat is not None and src_chat != int(ctx.chat_id):
                # Переход в другой чат запрещён (как у recognize_image).
                src_chat = src_msg = None
        if src_msg is None:
            rid = getattr(ctx, "reply_to_message_id", None)
            try:
                rid = int(rid) if rid is not None else None
            except (TypeError, ValueError):
                rid = None
            if rid:
                src_chat, src_msg = int(ctx.chat_id), rid
        # deps.db — DatabaseService (метод get_media_assets_for_message).
        db = getattr(self.deps, "db", None)
        if db is None or not hasattr(db, "get_media_assets_for_message"):
            db = getattr(ctx, "db", None)
        assets: list[dict] = []
        if src_msg is not None and db is not None and \
                hasattr(db, "get_media_assets_for_message"):
            try:
                assets = await db.get_media_assets_for_message(
                    int(ctx.chat_id), int(src_msg))
            except Exception:
                assets = []
        candidates = [a for a in assets
                      if str(a.get("asset_kind")) in self._EDIT_SOURCE_KINDS]
        if not candidates:
            # Честный отказ: исходник не найден. НИКАКОЙ генерации «вместо»
            # (§20: новая независимая генерация не выдаётся за изменение).
            return _err("no_source_image",
                        "Исходное изображение не найдено: пришли картинку "
                        "или сделай Reply на неё")
        file_id = str(candidates[0].get("file_id") or "")
        if not file_id:
            return _err("no_source_image",
                        "Исходное изображение недоступно (нет file_id)")
        # ── Скачивание исходника (существующий Bot API-путь) ──────────────
        import os
        import tempfile
        from services import mca_vision
        from services.media_execution import detect_adapter
        src_path = ""
        try:
            img = await mca_vision.download_telegram_file(ctx.bot, file_id)
            # COR-01: реальный формат исходника сохраняется — суффикс
            # временного файла по сниффер-MIME (не безусловный .png).
            suffix = _EDIT_SOURCE_SUFFIX_BY_MIME.get(
                str(getattr(img, "mime", "") or ""), ".png")
            fd, src_path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(bytes(img.data))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if src_path:
                try:
                    os.unlink(src_path)
                except OSError:
                    pass
            logger.warning("[tools] edit_image source download failed | "
                           "chat=%s | error=%s", ctx.chat_id,
                           type(exc).__name__)
            return _err("download_failed",
                        "Исходное изображение не удалось скачать")
        # ── Исполнение: существующий submit_edit-маршрут ──────────────────
        result = None
        try:
            # COR-01: effective-настройки чата тем же резолвом, что у проверки
            # capability (`capability_registry.chat_value` = per-chat override
            # → hot → default) — провайдер исполнения совпадает с проверенным;
            # новых конфигурационных систем нет.
            from services import capability_registry as _capcfg
            base_url = str(await _capcfg.chat_value(
                ctx.chat_id, image_generation.KEY_BASE_URL,
                getattr(settings, "IMAGE_BASE_URL", "")) or "").strip()
            model = str(await _capcfg.chat_value(
                ctx.chat_id, image_generation.KEY_MODEL,
                getattr(settings, "IMAGE_MODEL", "")) or "").strip()
            api_key = str(await _capcfg.chat_value(
                ctx.chat_id, image_generation.KEY_API_KEY,
                getattr(settings, "IMAGE_API_KEY", "")) or "").strip()
            adapter = detect_adapter(base_url)
            result = await adapter.submit_edit(
                prompt=prompt, model=model, image_paths=[src_path],
                api_key=api_key, chat_id=ctx.chat_id,
                correlation_id=getattr(ctx, "correlation_id", None))
        except asyncio.CancelledError:
            if src_path:
                try:
                    os.unlink(src_path)
                except OSError:
                    pass
            raise
        except Exception as exc:
            logger.warning("[tools] edit_image failed | chat=%s | error=%s",
                           ctx.chat_id, type(exc).__name__)
            result = None
        finally:
            if src_path:
                try:
                    os.unlink(src_path)
                except OSError:
                    pass
        if result is None or not getattr(result, "ok", False):
            reason = str(getattr(result, "reason", "") or "error") if result \
                else "error"
            logger.info("[tools] edit_image failed | chat=%s | reason=%s",
                        ctx.chat_id, reason)
            return _err(reason, "Редактирование не удалось")
        # ── Доставка: существующий путь отправки изображений ──────────────
        from aiogram.types import BufferedInputFile
        from services import capability_registry as _capreg
        from services import telegram_send
        try:
            photo = BufferedInputFile(
                bytes(result.content or b""), filename="image_edit.png")
            rid = getattr(ctx, "reply_to_message_id", None)
            if rid is not None:
                await telegram_send.send_photo(ctx.bot, ctx.chat_id, photo,
                                               reply_to_message_id=int(rid))
            else:
                await telegram_send.send_photo(ctx.bot, ctx.chat_id, photo)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] edit_image delivery failed | chat=%s | "
                           "error=%s", ctx.chat_id, type(exc).__name__)
            return _err("send_failed",
                        "Отредактированное изображение не удалось отправить")
        _capreg.record_outcome("image_edit", chat_id=ctx.chat_id, ok=True,
                               code="ok")
        # Маркер прогона: edit на этом ходу обработан — повторный
        # generate_image/edit_image в том же ходе не создаёт дубликат.
        try:
            ctx.image_request_handled = True
        except Exception:      # pragma: no cover
            pass
        logger.info("[tools] edit_image sent | chat=%s | bytes=%d",
                    ctx.chat_id, len(result.content or b""))
        return json.dumps(
            {"status": "success",
             "message": "Изображение отредактировано и отправлено в чат",
             "operation": "edit",
             "source": {"chat_id": int(ctx.chat_id),
                        "message_id": int(src_msg) if src_msg else None}},
            ensure_ascii=False)

    # ── helpers dig (T-820; переиспользуют _require_query/_resolve_name) ──
    @staticmethod
    def _dig_year(raw) -> int | None:
        """year-параметр → int (вне [2000, текущий] → None; кривой тип →
        None). Период «N лет назад» парсится отдельно — _dig_year_from_query."""
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value < _DIG_YEAR_MIN or value > datetime.datetime.now().year:
            return None
        return value

    @classmethod
    def _dig_year_from_query(cls, query: str) -> int | None:
        """Фикс-раунд (major-2): «N лет назад» в тексте запроса при year
        None → год = текущий − N (N 1..50); слова «несколько/пару/тройку
        лет назад» → 3/2/3. Вне диапазона [2000, текущий] → None."""
        text = str(query or "").casefold()
        n = None
        m = _DIG_YEARS_AGO_NUM_RE.search(text)
        if m:
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                n = None
        else:
            m = _DIG_YEARS_AGO_WORD_RE.search(text)
            if m:
                n = _DIG_YEARS_AGO_WORDS.get(m.group(1))
        if not n or n < 1 or n > 50:
            return None
        year = datetime.datetime.now().year - n
        if year < _DIG_YEAR_MIN:
            return None
        return year

    async def _dig_graph_names(self, ctx: ToolContext,
                               seed_terms: list[str]) -> list[str]:
        """major-2(б)/spec п.4: имена из графа для FTS-расширения: BFS по
        nodes/edges (db.dig_graph_related_names, глубина limits.
        dig_graph_hop_depth); если узлы/рёбра пусты или недоступны — фолбэк
        db.dig_fallback_target_names (target_user фактов, содержащие токен).
        Best-effort: любая ошибка/нет db/нет токенов → [] (WARNING)."""
        db = getattr(self.deps.memory, "db", None)
        seeds = [str(t).strip() for t in (seed_terms or [])
                 if len(str(t).strip()) >= 4]
        if db is None or not seeds:
            return []
        depth = int(hot.get("limits.dig_graph_hop_depth",
                            settings.DIG_GRAPH_HOP_DEPTH)
                    or settings.DIG_GRAPH_HOP_DEPTH)
        depth = min(max(1, depth), _DIG_GRAPH_MAX_HOP_DEPTH)
        try:
            if hasattr(db, "dig_graph_related_names"):
                names = await db.dig_graph_related_names(
                    ctx.chat_id, seeds, max_depth=depth)
                if names:
                    return names
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[tools] dig graph names failed — fallback target_user | "
                "chat=%s", ctx.chat_id, exc_info=True)
        try:
            if hasattr(db, "dig_fallback_target_names"):
                return await db.dig_fallback_target_names(
                    ctx.chat_id, seeds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[tools] dig fallback target_user failed — empty | "
                "chat=%s", ctx.chat_id, exc_info=True)
        return []

    @staticmethod
    def _year_bounds(year: int) -> tuple[int, int] | None:
        """[Y-01-01 00:00, Y-12-31 23:59:59] local — unix-диапазон для
        пост-фильтра по timestamp (spec §3.2.1 п.3(а))."""
        if not year:
            return None
        start = datetime.datetime(year, 1, 1, 0, 0).timestamp()
        end = datetime.datetime(year, 12, 31, 23, 59, 59).timestamp()
        return int(start), int(end)

    @staticmethod
    def _dig_date(ts) -> str:
        """timestamp → 'YYYY-MM-DD' (дата сниппета; без времени)."""
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return ""

    @staticmethod
    def _dig_not_found(query: str, stats_block: dict | None = None) -> str:
        """Честный JSON-контракт при отсутствии попаданий (БЛОК 2.8/R16):
        нули + текст «ничего не нашёл» — БЕЗ выдуманных цифр.

        Сохраняет обратную совместимость по подстроке «ничего не нашёл по
        запросу» (снапшот-тесты: plain→JSON обновлены осознанно).
        MCA-15 (K1 ON): вместо голого `total_mentions` — типизированный
        `stats`-блок (status/value/unit/method/scope) с value=0 после
        успешного расчёта области."""
        payload = {
            "total_mentions": 0,
            "mentions_by_authors": {},
            "first_seen": None,
            "last_seen": None,
            "snippets": [],
            "facts": [],
            "status": "not_found",
            "message": f"ничего не нашёл по запросу «{query}»",
        }
        if stats_block is not None:
            payload.pop("total_mentions", None)
            payload["stats"] = stats_block
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _register_dig_measurement(ctx: ToolContext, stats_block: dict,
                                  measurement_tokens: list,
                                  person_uid: int | None,
                                  bounds) -> None:
        """MetricResult для dig-измерения (T-4929/D4; без второго измерения).

        Спека строится по тем же токенам/окну/person, что применялись к
        счётчику; ошибка/unsupported → value=None (claim не создаётся)."""
        try:
            from services import chat_statistics as _cs
            query = _cs.StatsQuery(
                chat_id=ctx.chat_id, metric=_cs.METRIC_MESSAGES,
                match_mode=_cs.MATCH_PREFIX,
                terms=tuple(measurement_tokens),
                author_ids=((person_uid,) if person_uid is not None else ()),
                interval_from=(bounds[0] if bounds else None),
                interval_to=(bounds[1] if bounds else None))
            metric_result = _cs.build_metric_result(stats_block, query)
            ctx.metric_results.append(metric_result)
            _cs.emit_measurement_event(
                metric_result, chat_id=ctx.chat_id,
                intent=ctx.stats_intent)
        except Exception:
            logger.warning("[tools] dig measurement register failed",
                           exc_info=True)

    @staticmethod
    def _dig_person_text(raw) -> str | None:
        """person → строка ≤ _DIG_PERSON_MAX_CHARS (None — пусто)."""
        text = str(raw or "").strip()
        if not text:
            return None
        return text[:_DIG_PERSON_MAX_CHARS]

    # ── helpers ───────────────────────────────────────────────────

    def _require_query(self, arguments: dict, ctx: ToolContext) -> str:
        """query из аргументов (fallback — исходное сообщение юзера)."""
        raw = arguments.get("query")
        text = str(raw or "").strip() if isinstance(raw, str) else str(raw or "").strip()
        return text or ctx.query

    @staticmethod
    def _require_str(arguments: dict, key: str) -> str:
        """Строковый аргумент инструмента (None/не-строка → "")."""
        raw = arguments.get(key)
        if raw is None:
            return ""
        return str(raw).strip()

    def _resolve_name(self, row: dict) -> str:
        """Имя автора строки FTS: алиас → имя → ник → user_id (R7-каскад)."""
        user_id = row.get("user_id")
        if self.deps.aliases is not None and user_id is not None:
            try:
                return self.deps.aliases.resolve(
                    int(user_id), (row.get("author_name") or None), None)
            except (TypeError, ValueError):
                pass
        author = str(row.get("author_name") or "").strip()
        if author:
            return author
        return str(user_id) if user_id is not None else "кто-то"
