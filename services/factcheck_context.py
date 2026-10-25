"""CFG-06 W1 — широкий чат-контекст фактчека (06I.1–06I.9, бриф
cfg-06-build-plan §W1).

Режим широкого контекста: **по умолчанию ВКЛЮЧЁН** (решение владельца
25.10.2026). Гейт `flags.factcheck_wide_context` /
`FACTCHECK_WIDE_CONTEXT_ENABLED` остаётся штатным откатом без рестарта:
явное `false` возвращает прежнее узкое окно. Для ПУСТОЙ цели окружение
проверяется всегда (уточнение владельца №2) — гейт там не читается.

Требования исходника (source-cfg-addendum L310–L318):

* 06I.1 — контекст собирается до suitability-решений (feed для gate W2);
* 06I.2 — широкое адаптивное окно последних сообщений (дизайн-диапазон
  200–500, бюджет-настройка, НЕ фиксированное число), а не 10–20 реплик;
* 06I.3 — двухуровневая подача: дешёвая хронология/метаданные из локальной
  БД (компакт) + дословные существенные фрагменты; НЕ «тысячи сообщений
  сыром» и НЕ «summary вместо оригиналов»;
* 06I.4/5 — явные связи (reply_to) и стабильные опоры message_id/chat_id/
  author/timestamp/reply_to/forward в каждой строке (канон
  `canonical_context.format_context_item` — «нет голого текста»);
* 06I.8 — чужие чаты не читаются (все запросы строго по chat_id); приватное
  наружу не уходит (контекст едет только в user-content, как и раньше);
* 06I.9 — reuse существующих DB-доступов (`get_messages_around`/
  `get_recent_messages` — БЕЗ новых политик доступа), бюджеты/дедлайны,
  кеш среза с версией/диапазоном/ID; новые сообщения инвалидируют кеш
  (newest_message_id в ключе).

Fail-open: ЛЮБАЯ ошибка сборки → '' (вызывающий получает прежнее поведение
без широкого контекста / падает в узкое окно фактчека).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re

from config.settings import settings
from services.canonical_context import format_context_item, resolve_item_id
from services.database import row_get
from services.smart_cache import build_key, normalize_text

logger = logging.getLogger(__name__)

# ── Версия схемы среза (06I.9): изменение алгоритма → старый кеш мёртв. ─────
WIDE_CONTEXT_VERSION = "fcx1"

# Дизайн-диапазон окна (06I.2): 200–500. Дефолт 300; владелец может сузить
# hot-ключом (адаптивность: окно — бюджет, а не фиксированное число строк).
_WIDE_WINDOW_DEFAULT = 300
_WIDE_WINDOW_MAX = 500
# Распределение окна вокруг цели: спор разворачивается ДО цели, триггер —
# сразу после; 15% после цели хватает на вызов фактчека и пару реплик.
_AFTER_SHARE = 0.15

# Двухуровневая подача (06I.3): бюджеты символов.
_DIGEST_LINE_MAX_CHARS = 120     # строка компакт-хронологии
_VERBATIM_MSG_MAX_CHARS = 600    # дословный фрагмент одного сообщения
_VERBATIM_MAX_MESSAGES = 40      # потолок дословных сообщений
_DIGEST_BUDGET_CHARS = 8000
_VERBATIM_BUDGET_CHARS = 12000

# Кеш среза (06I.9): короткий TTL + newest_message_id в ключе.
_CACHE_SLUG = "factcheck_wide_context"
_CACHE_TTL_DEFAULT_SECONDS = 120

_RARE_TERM_LEN = 5


def wide_context_enabled() -> bool:
    """Гейт широкого контекста: по умолчанию ВКЛЮЧЁН (owner 25.10.2026).

    Приоритет: hot-ключ ``flags.factcheck_wide_context`` (rollback без
    рестарта, паттерн CFG-01) → env ``FACTCHECK_WIDE_CONTEXT_ENABLED`` →
    **True**. Явный ``false`` (владелец выключил в админке) действует;
    значения нет → включено. Никогда не бросает.

    Для ПУСТОЙ цели гейт намеренно не читается: окружение проверяется
    всегда (уточнение №2), флаг — откат для непустых целей."""
    try:
        default = bool(getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED",
                               True))
        from services import hot_config as hot
        return bool(hot.get("flags.factcheck_wide_context", default))
    except Exception:      # pragma: no cover — конфиг не должен ронять
        return True


def _hot_int(hot_key: str, *, settings_field: str, default: int,
             maximum: int | None = None) -> int:
    """Горячий int-параметр (ConfigCache → Settings-фолбек), clamp ≥ 0.

    Settings-поле может отсутствовать (инженерный knobs без env) — тогда
    действует ``default``. Никогда не бросает."""
    value = default
    try:
        from services import hot_config as hot
        value = hot.get(hot_key,
                        getattr(settings, settings_field, default))
    except Exception:
        value = default
    try:
        value = max(0, int(value or 0))
    except (TypeError, ValueError):
        value = default
    if maximum is not None:
        value = min(value, maximum)
    return value


async def resolve_window(chat_id: int | None = None) -> tuple[int, int]:
    """Адаптивное окно (06I.2): целевой бюджет сообщений → (before, after).

    Бюджет: per-chat ``limits.factcheck_wide_context_messages``
    (chat_params → hot → default 300, потолок 500 — дизайн-диапазон 06I.2).
    before/after — 85%/15% (спор разворачивается до цели). Никогда не
    бросает."""
    default = _hot_int("limits.factcheck_wide_context_messages",
                       settings_field="FACTCHECK_WIDE_CONTEXT_MESSAGES",
                       default=_WIDE_WINDOW_DEFAULT,
                       maximum=_WIDE_WINDOW_MAX)
    total = default
    if chat_id not in (None, 0):
        try:
            from services.chat_params import get_chat_param
            resolved = await get_chat_param(
                int(chat_id), "limits.factcheck_wide_context_messages",
                default)
            total = max(0, int(resolved or default))
        except Exception:
            total = default
    total = min(total, _WIDE_WINDOW_MAX)
    after = int(total * _AFTER_SHARE)
    before = max(0, total - after)
    return before, after


# ── DTO (06I.5): стабильные опоры каждого сообщения. ────────────────────────

@dataclasses.dataclass(frozen=True)
class ContextMessage:
    """Одно сообщение среза. Якоря обязательны (привязка тезиса к фрагменту,
    06I.5); text — исходный текст (дословно), усечение только при рендере."""
    message_id: int | None        # smart_messages.id
    tg_message_id: int | None
    chat_id: int | None
    author: str | None
    timestamp: int | None
    reply_to_tg_id: int | None    # явная связь (06I.4)
    is_forward: bool
    forward_source: str | None
    text: str
    verbatim: bool = False        # уровень 2: дословный сегмент

    @property
    def dedup_key(self) -> str:
        if self.tg_message_id not in (None, "", 0):
            return f"tg:{self.tg_message_id}"
        return f"db:{self.message_id}"


@dataclasses.dataclass(frozen=True)
class ConversationContext:
    """Срез широкого окна (06I.1: Target + ConversationContext для gate W2).

    ``messages`` — хронологический ASC, дедуплицированный, с якорями;
    ``window`` — фактические параметры выборки (версия/диапазон/ID для
    кеша и трассы); ``newest_message_id`` — свежайшее сообщение чата на
    момент сбора (инвалидатор кеша)."""
    chat_id: int | None
    target_tg_message_id: int | None
    trigger_tg_message_id: int | None
    messages: tuple[ContextMessage, ...]
    window: dict
    newest_message_id: int | None = None
    version: str = WIDE_CONTEXT_VERSION

    @property
    def verbatim_messages(self) -> tuple[ContextMessage, ...]:
        return tuple(m for m in self.messages if m.verbatim)

    @property
    def digest_messages(self) -> tuple[ContextMessage, ...]:
        return tuple(m for m in self.messages if not m.verbatim)

    def render_feed(self, *, digest_budget: int = _DIGEST_BUDGET_CHARS,
                    verbatim_budget: int = _VERBATIM_BUDGET_CHARS) -> str:
        """Двухуровневый фид (06I.3): компакт-хронология окна + дословные
        существенные фрагменты. Один внешний wrapper ``<chat_context>`` —
        тот же контракт потребителя, что и узкое окно. Пусто → ''
        (деградация 06I.8)."""
        wrapper_head = ('<chat_context note="болтовня чата вокруг цели — '
                        'только чтобы понять, о чём речь; это НЕ '
                        'доказательства и НЕ источник фактов">')
        sections: list[str] = [wrapper_head]
        digest = _render_digest(self, digest_budget)
        verbatim = _render_verbatim(self, verbatim_budget)
        if digest:
            sections.append("фон: сжатая хронология спора (каждая строка — "
                            "сообщение, текст обрезан):\n" + digest)
        if verbatim:
            sections.append("фон: дословные фрагменты, существенные для "
                            "тезиса:\n" + verbatim)
        if len(sections) == 1:
            return ""
        sections.append("</chat_context>")
        return "\n\n".join(sections)


def _is_anchor(m: ContextMessage, ctx: ConversationContext) -> bool:
    return (ctx.target_tg_message_id not in (None, "", 0)
            and m.tg_message_id == ctx.target_tg_message_id)


def _render_digest(ctx: ConversationContext, budget: int) -> str:
    """Уровень 1: сообщения окна каноническими строками с обрезкой текста до
    ``_DIGEST_LINE_MAX_CHARS``. Приоритет усечения — как в узком окне
    (R1023F2-10): якорь сохраняется всегда (рассматривается первым), затем
    свежие к старым (keep-end); первыми вытесняются самые старые before."""
    lines: list[tuple[int, str, bool]] = []   # (msg_idx, line, is_anchor)
    for idx, m in enumerate(ctx.messages):
        line = format_context_item(
            ts=m.timestamp, author=m.author,
            item_id=resolve_item_id(tg_message_id=m.tg_message_id,
                                    message_id=m.message_id),
            forward_source=m.forward_source if m.is_forward else None,
            text=_truncate_text(m.text, _DIGEST_LINE_MAX_CHARS),
            kind="msg")
        if line:
            lines.append((idx, line, _is_anchor(m, ctx)))
    if not lines:
        return ""
    anchor_idx = next((i for i, (_idx, _l, a) in enumerate(lines) if a), None)
    order: list[int] = []
    if anchor_idx is not None:
        order.append(anchor_idx)
    order += [i for i in range(len(lines) - 1, -1, -1) if i != anchor_idx]
    selected: list[int] = []
    used = 0
    for i in order:
        addition = len(lines[i][1]) + (1 if selected else 0)
        if used + addition > max(0, int(budget)):
            break
        selected.append(i)
        used += addition
    if not selected:
        return ""
    by_msg_idx = {idx: line for idx, line, _a in lines}
    ordered = sorted(lines[i][0] for i in selected)
    return "\n".join(by_msg_idx[i] for i in ordered)


def _render_verbatim(ctx: ConversationContext, budget: int) -> str:
    """Уровень 2: выбранные дословные сообщения (полный текст до
    ``_VERBATIM_MSG_MAX_CHARS``), хронологически, общий бюджет символов;
    якорь-целевое сохраняется всегда (если влезает)."""
    lines: list[tuple[int, str, bool]] = []
    for idx, m in enumerate(ctx.messages):
        if not m.verbatim:
            continue
        line = format_context_item(
            ts=m.timestamp, author=m.author,
            item_id=resolve_item_id(tg_message_id=m.tg_message_id,
                                    message_id=m.message_id),
            forward_source=m.forward_source if m.is_forward else None,
            text=_truncate_text(m.text, _VERBATIM_MSG_MAX_CHARS),
            kind="msg")
        if line:
            lines.append((idx, line, _is_anchor(m, ctx)))
    if not lines:
        return ""
    anchor_idx = next((i for i, (_idx, _l, a) in enumerate(lines) if a), None)
    selected: list[int] = []
    used = 0
    if anchor_idx is not None and len(lines[anchor_idx][1]) <= budget:
        selected.append(anchor_idx)
        used = len(lines[anchor_idx][1])
    for i in range(len(lines) - 1, -1, -1):
        if i in selected:
            continue
        if len(selected) >= _VERBATIM_MAX_MESSAGES:
            break
        addition = len(lines[i][1]) + (1 if selected else 0)
        if used + addition > max(0, int(budget)):
            break
        selected.append(i)
        used += addition
    if not selected:
        return ""
    by_msg_idx = {idx: line for idx, line, _a in lines}
    ordered = sorted(lines[i][0] for i in selected)
    return "\n".join(by_msg_idx[i] for i in ordered)


def _truncate_text(text: str, limit: int) -> str:
    """Обрезка без разрыва юникода, схлопывание пробелов; пустое → ''."""
    clean = " ".join(str(text or "").split())
    if limit <= 0:
        return ""
    if len(clean) <= limit:
        return clean
    return clean[:max(0, limit - 1)].rstrip() + "…"


# ── Выбор дословных фрагментов (детерминированно, без LLM — 06I.4). ────────

_STOPWORDS = frozenset({
    "это", "этого", "этому", "того", "том", "тем", "чтобы", "как", "так",
    "вот", "или", "если", "когда", "тогда", "для", "над", "под",
    "про", "что", "чего", "чем", "все", "всё", "весь", "вся", "свои",
    "свой", "одно", "один", "два", "три", "будет", "были", "было", "есть",
    "нет", "они", "них", "него", "нее", "ней", "ним", "ими", "мне", "тебе",
    "себе", "даже", "уже", "ещё", "очень", "более", "менее", "самый",
})

_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    """Токены для релевантности: буквы/цифры, длина ≥ 4, без стоп-слов."""
    tokens = set()
    for raw in _WORD_RE.findall(str(text or "").lower()):
        if len(raw) >= 4 and raw not in _STOPWORDS:
            tokens.add(raw)
    return tokens


# Публичный алиас для потребителей релевантности (CFG-06 W2 suitability/CR):
# единый токенайзер, чтобы «тема» в gate и «дословный выбор» W1 совпадали.
tokenize_for_relevance = _tokenize


def select_verbatim(ctx: ConversationContext,
                    claim_text: str | None) -> ConversationContext:
    """Пометить дословные сообщения (детерминированная эвристика W1):

    1. целевое (якорь) и триггер — всегда;
    2. прямые ответы на них (reply_to) — всегда (явная связь, 06I.4);
    3. лексическая релевантность клейму: ≥2 общих токена (≥4 симв.) ИЛИ
       редкий термин (токен ≥5 симв., встречается в окне ≤2 раз) из клейма;
    4. ответы на уже выбранные (1 хоп) — замыкание ветки.

    При ``claim_text=None`` → только якоря/связи (W2 уточнит выбор)."""
    messages = list(ctx.messages)
    if not messages:
        return ctx
    anchor_tg = ctx.target_tg_message_id
    trigger_tg = ctx.trigger_tg_message_id
    df: dict[str, int] = {}
    msg_tokens = [_tokenize(m.text) for m in messages]
    for tokens in msg_tokens:
        for token in tokens:
            df[token] = df.get(token, 0) + 1
    claim_tokens = _tokenize(claim_text)
    verbatim_ids: set[str] = set()
    for i, m in enumerate(messages):
        if _is_anchor(m, ctx) or (trigger_tg not in (None, "", 0)
                                  and m.tg_message_id == trigger_tg):
            verbatim_ids.add(m.dedup_key)
            continue
        if m.reply_to_tg_id and m.reply_to_tg_id in (anchor_tg, trigger_tg):
            verbatim_ids.add(m.dedup_key)
            continue
        overlap = msg_tokens[i] & claim_tokens
        if len(overlap) >= 2:
            verbatim_ids.add(m.dedup_key)
            continue
        for token in overlap:
            if len(token) >= _RARE_TERM_LEN and df.get(token, 0) <= 2:
                verbatim_ids.add(m.dedup_key)
                break
    # 1 хоп замыкания: ответы на выбранные — тоже дословно.
    selected_tg = {m.tg_message_id for m in messages
                   if m.dedup_key in verbatim_ids
                   and m.tg_message_id not in (None, "", 0)}
    for m in messages:
        if m.reply_to_tg_id and m.reply_to_tg_id in selected_tg:
            verbatim_ids.add(m.dedup_key)
    updated = tuple(
        dataclasses.replace(m, verbatim=m.dedup_key in verbatim_ids)
        for m in messages)
    return dataclasses.replace(ctx, messages=updated)


# ── Кеш среза (06I.9): версия/диапазон/ID в ключе; новые сообщения → miss. ──

def slice_cache_components(ctx: ConversationContext, *,
                           before: int, after: int) -> dict:
    return {
        "version": WIDE_CONTEXT_VERSION,
        "chat_id": ctx.chat_id,
        "target": ctx.target_tg_message_id,
        "trigger": ctx.trigger_tg_message_id,
        "window": [before, after],
        "newest": ctx.newest_message_id,
    }


def slice_cache_key(ctx: ConversationContext, *,
                    before: int, after: int) -> str | None:
    try:
        raw = json.dumps(slice_cache_components(ctx, before=before,
                                                after=after),
                         ensure_ascii=False, sort_keys=True)
        return build_key(_CACHE_SLUG, normalize_text(raw))
    except Exception:
        return None


async def read_slice_cache(cache, ctx: ConversationContext, *,
                           before: int, after: int,
                           ttl_seconds: int | None = None):
    """Чтение среза: попадание только при совпадении версии/окна/newest.
    Никогда не бросает (ошибка кеша → None)."""
    if cache is None:
        return None
    key = slice_cache_key(ctx, before=before, after=after)
    if key is None:
        return None
    if ttl_seconds is None:
        ttl_seconds = _hot_int("limits.factcheck_wide_context_cache_ttl",
                               settings_field="FACTCHECK_WIDE_CONTEXT_CACHE_TTL",
                               default=_CACHE_TTL_DEFAULT_SECONDS)
    try:
        raw = await cache.get_update_marker(key, ttl_seconds=ttl_seconds)
        if not raw:
            return None
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != WIDE_CONTEXT_VERSION:
        return None
    if payload.get("newest") != ctx.newest_message_id:
        return None
    try:
        messages = tuple(
            ContextMessage(**dict(item)) for item in payload.get("messages")
            or ())
    except (TypeError, ValueError):
        return None
    if not messages:
        return None
    return dataclasses.replace(ctx, messages=messages)


async def write_slice_cache(cache, ctx: ConversationContext, *,
                            before: int, after: int,
                            ttl_seconds: int | None = None) -> bool:
    """Запись среза (TTL ``limits.factcheck_wide_context_cache_ttl``,
    default 120 с). Никогда не бросает."""
    if cache is None:
        return False
    key = slice_cache_key(ctx, before=before, after=after)
    if key is None:
        return False
    if ttl_seconds is None:
        ttl_seconds = _hot_int("limits.factcheck_wide_context_cache_ttl",
                               settings_field="FACTCHECK_WIDE_CONTEXT_CACHE_TTL",
                               default=_CACHE_TTL_DEFAULT_SECONDS)
    payload = json.dumps({
        "version": WIDE_CONTEXT_VERSION,
        "newest": ctx.newest_message_id,
        "window": [before, after],
        "messages": [dataclasses.asdict(m) for m in ctx.messages],
    }, ensure_ascii=False)
    try:
        await cache.set_update_marker(key, payload, ttl_seconds=ttl_seconds)
        return True
    except Exception:
        return False


# ── Сборка (единая точка входа лейна). ──────────────────────────────────────

def _row_to_context_message(row, chat_id: int) -> ContextMessage:
    # P0-FACTCHECK уточнение №2: подпись (caption) — такое же содержание
    # сообщения, как text (раньше окно видело фото-строки пустыми и молча
    # выбрасывало их вместе с утверждением автора).
    return ContextMessage(
        message_id=row_get(row, "id"),
        tg_message_id=row_get(row, "tg_message_id"),
        chat_id=row_get(row, "chat_id") or chat_id,
        author=row_get(row, "author_name"),
        timestamp=row_get(row, "timestamp"),
        reply_to_tg_id=row_get(row, "reply_to_id"),
        is_forward=bool(row_get(row, "is_forward")),
        forward_source=row_get(row, "forward_source"),
        text=str(row_get(row, "text") or row_get(row, "caption") or ""))


async def fetch_newest_message_id(db, chat_id: int) -> int | None:
    """Свежайший id чата (инвалидатор кеша) — reuse ``get_recent_messages``
    (существующий доступ, 1 строка; НЕТ новых политик доступа)."""
    try:
        rows = await db.get_recent_messages(chat_id, 1)
    except Exception:
        return None
    if not rows:
        return None
    try:
        newest = row_get(rows[-1], "id")
        return int(newest) if newest is not None else None
    except (TypeError, ValueError):
        return None


async def build_wide_context(db, chat_id: int, *,
                             target_tg_message_id=None,
                             trigger_tg_message_id=None,
                             claim_text: str | None = None,
                             cache=None,
                             window_override: tuple[int, int] | None = None,
                             skip_cache_read: bool = False
                             ) -> ConversationContext | None:
    """Собрать широкий срез (06I.1/2/9). Источники — только существующие
    DB-доступы, строго по chat_id. Ошибка/пусто → None (fail-open).

    ``window_override`` — принудительное окно (CFG-06 W2: одно ограниченное
    расширение по needs_context, 06J.1; потолок тот же _WIDE_WINDOW_MAX).
    ``skip_cache_read`` — дозапрос расширения всегда свежий (ключ другого
    окна и так другой; флаг для явности теста протокола)."""
    if db is None or chat_id in (None, 0):
        return None
    if window_override is not None:
        raw_total = (max(0, int(window_override[0] or 0))
                     + max(0, int(window_override[1] or 0)))
        total = min(raw_total, _WIDE_WINDOW_MAX)
        if total <= 0:
            before, after = await resolve_window(chat_id)
        else:
            after = int(total * _AFTER_SHARE)
            before = max(0, total - after)
    else:
        before, after = await resolve_window(chat_id)
    # Свежайший id чата ДО чтения кеша: новые сообщения меняют ключ →
    # честный miss (06I.9), hit не отдаёт устаревший срез.
    newest = await fetch_newest_message_id(db, int(chat_id))
    probe = ConversationContext(
        chat_id=int(chat_id),
        target_tg_message_id=target_tg_message_id,
        trigger_tg_message_id=trigger_tg_message_id,
        messages=(), window={"before": before, "after": after},
        newest_message_id=newest)
    cached = None if skip_cache_read else await read_slice_cache(
        cache, probe, before=before, after=after)
    if cached is not None and cached.messages:
        return select_verbatim(cached, claim_text)
    try:
        rows = await db.get_messages_around(
            int(chat_id), target_tg_message_id, before, after)
    except Exception:
        logger.warning("[factcheck_context] window fetch failed | chat=%s",
                       chat_id, exc_info=True)
        return None
    messages: list[ContextMessage] = []
    seen: set[str] = set()
    for row in rows or ():
        try:
            item = _row_to_context_message(row, int(chat_id))
        except Exception:
            continue
        # Чужой чат не включается никогда (06I.8, защита в глубину).
        if item.chat_id not in (None, int(chat_id)):
            continue
        if not str(item.text or "").strip():
            continue
        if item.dedup_key in seen:
            continue
        seen.add(item.dedup_key)
        messages.append(item)
    # Защитный потолок окна (06I.9): ≤ 500 сообщений, keep-end, якорь
    # гарантирован (SQL LIMIT уже режет; это защита в глубину от скриптовых/
    # fail-open выборок).
    if len(messages) > _WIDE_WINDOW_MAX:
        keep_idx = set(range(len(messages) - _WIDE_WINDOW_MAX,
                             len(messages)))
        for i, item in enumerate(messages):
            if _is_anchor(item, probe):
                keep_idx.add(i)
        messages = [item for i, item in enumerate(messages) if i in keep_idx]
    if not messages:
        return None
    ctx = ConversationContext(
        chat_id=int(chat_id),
        target_tg_message_id=target_tg_message_id,
        trigger_tg_message_id=trigger_tg_message_id,
        messages=tuple(messages),
        window={"before": before, "after": after,
                "fetched": len(messages), "verbatim": 0},
        newest_message_id=newest)
    ctx = select_verbatim(ctx, claim_text)
    ctx = dataclasses.replace(
        ctx, window={**ctx.window, "verbatim": len(ctx.verbatim_messages)})
    await write_slice_cache(cache, ctx, before=before, after=after)
    return ctx


async def build_factcheck_context(db, chat_id: int, *,
                                  target_tg_message_id=None,
                                  trigger_message_id=None,
                                  claim_text: str | None = None,
                                  cache=None) -> str:
    """Готовый фид для user-content (тот же контракт, что узкое окно:
    ``<chat_context>…</chat_context>`` или '' при пустом срезе/ошибке).
    ``cache=None`` → ленивый SmartCache-синглтон (no-op при выключенном)."""
    if cache is None:
        try:
            from services.smart_cache import get_smart_cache
            cache = get_smart_cache()
        except Exception:      # pragma: no cover
            cache = None
    try:
        ctx = await build_wide_context(
            db, chat_id, target_tg_message_id=target_tg_message_id,
            trigger_tg_message_id=trigger_message_id, claim_text=claim_text,
            cache=cache)
    except Exception:
        logger.warning("[factcheck_context] wide context build failed | "
                       "chat=%s", chat_id, exc_info=True)
        return ""
    if ctx is None:
        return ""
    return ctx.render_feed()
