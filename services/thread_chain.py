"""Раунд 10.23 (F2, ADR-1023-2 §3.2) — общий util графа реплаев.

Единственная реализация прохода по reply-цепочке (кто кому отвечал):
раньше жила в ``DirectChatService._collect_thread_chain``, теперь
переиспользуется и прямым чатом, и фактчеком (R3: логика direct не
дублируется).

Проход: стартуем от сообщения (или его Telegram id), идём по
``smart_messages.reply_to_id`` (user-ходы) и сквозь бот-ответы
``bot_replies``/``bot_reply_parents``; глубина ограничена вызывающим.
Возврат — от ТЕКУЩЕГО сообщения (самое свежее первое) к корню.

Рендер хода — канонический ``format_context_item`` (10.20, ADR-1020-1,
точка 3): user-ход с ts/ID/forward, бот-ход — ts опущен (R16), ID ``tg:<id>``.
Фактчек оборачивает цепочку в ``<reply_chains>``-под-блок с явной пометкой
«не доказательства»; direct сохраняет свои ``<Conversation_Thread>``.

EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§4.2, одна структура — две проекции):

* **машинная сторона** — ``format_chain_line`` / ``collect_thread_chain``:
  настоящие ``tg:``-рефы нужны direct-дедупу, attribution, планировщику;
* **речевая сторона** — ``render_reply_chains`` (под-блок фактчека) и
  ``render_speech_line`` (построчный рендер, напр. direct): метки прогона
  ``M``/``U`` с обратным отображением в ``SpeechProjection``, явные отношения
  («отвечает на M3 (Telegram Reply)» / «относится к теме» / «родитель вне
  доступного окна»), автор цитаты по имени, абсолютное время сохраняется.
  Единый рубильник — ``flags.context_speech_projection`` (OFF → сырой вид
  байт-в-байт).
"""
import logging
import time
from typing import NamedTuple

from services.canonical_context import (
    RELATION_REPLY,
    SpeechProjection,
    SpeechQuote,
    SpeechRelation,
    emit_speech_projection_event,
    format_context_item,
    format_speech_item,
    resolve_item_id,
    speech_projection_enabled,
)
from services.database import row_get
from services.media_marker import (
    is_media_type,
    media_context_enabled,
    media_marker,
    row_media_marker,
)
from services.target_marking import is_target_item_id

logger = logging.getLogger(__name__)


def _emit_quote_context_event(code: str, *, chat_id, message_id=None):
    """EVOL-015: fail-open эмиссия контекстной половины quote-таксономии
    (`delivered_to_context`/`unavailable`); источник — component="context".
    R17: только id/коды — никаких текстов цитат в телеметрии."""
    try:
        from services.mca_events import emit_mca_event
        outcome = "skipped" if code == "unavailable" else "success"
        emit_mca_event("quote", outcome=outcome, component="context",
                       stage=f"quote_{code}", chat_id=chat_id,
                       message_id=message_id)
    except Exception:
        pass


class ChainItem(NamedTuple):
    """Ход reply-цепочки + метаданные канона.

    user-ход — ts/tg/id/forward из smart_messages; бот-ход — ts ОПУЩЕН
    (bot_replies не хранит время сообщения; ``last_used_at`` = время доступа,
    R16), item_id = ``tg:<current_id>``.

    EVOL-015 (v38): полные метаданные цитаты хода-user (verbatim из
    Telegram: text/author/position UTF-16/is_manual; position НЕ
    пересчитывается). ``quote_original_available`` — честный статус доставки
    оригинала в ЭТУ цепочку: True = найден (следующий ход), False = не
    найден (контекст ограничен — пометка в рендере), None = неизвестно
    (автономный рендер вне walk)."""
    uid: int | None
    name: str
    text: str
    is_bot: bool
    ts: int | None = None
    item_id: str = ""
    forward_source: str | None = None
    quote_text: str | None = None
    quote_author_id: int | None = None
    quote_position: int | None = None
    quote_is_manual: int | None = None
    quote_original_available: bool | None = None
    # EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (аддитивно, §4.2/§8 п.4):
    # ``reply_to_item_id`` — РЕАЛЬНЫЙ id родителя (``tg:<id>``), когда он
    # известен из БД, — основание для явного отношения «отвечает на …» в
    # речевой проекции (пусто = связь неизвестна, догадок нет);
    # ``quote_author_name`` — имя автора цитаты (без него §9.2 закрыть
    # нельзя: был только числовой uid); ``media_type`` — тип медиа, если
    # строка рендерилась медиа-маркером (речевая проекция перерисовывает
    # маркер меткой, сырой вид остаётся байт-в-байт).
    reply_to_item_id: str = ""
    quote_author_name: str = ""
    media_type: str = ""


def speaker_tag(name: str, uid, *, is_bot: bool = False,
                suffix: str = "") -> str:
    """Display-строка участника для внутренних рендеров —
    «{имя}{суффикс} [{uid}]» (бот — «{имя} [bot]»). uid None/0 → без скобки.
    suffix — дискриминатор коллизии, пуст при отсутствии коллизии."""
    rendered = f"{name}{suffix}"
    if is_bot:
        return f"{rendered} [bot]"
    if uid not in (None, 0):
        return f"{rendered} [{uid}]"
    return rendered


def _default_row_speaker(row) -> tuple[str, int | None]:
    """Фолбэк-резолв имени user-строки (без alias-каскада direct):
    ``author_name`` → ``id<user_id>`` + uid."""
    uid = row_get(row, "user_id")
    name = row_get(row, "author_name") or f"id{uid or '?'}"
    return name, uid


def _media_type_of(row) -> str:
    """Тип медиа строки, если она рендерится медиа-маркером (иначе '').

    Нужен речевой проекции: маркер перерисовывается меткой прогона вместо
    внутреннего ref (EVOL v5 §4.2 п.2), сырой вид остаётся байт-в-байт."""
    try:
        media_type = row_get(row, "media_type")
    except Exception:
        return ""
    return str(media_type or "") if is_media_type(media_type) else ""


def _message_id_of(message):
    """Telegram id стартового сообщения: int как есть, иначе ``.message_id``."""
    if isinstance(message, int):
        return message
    return getattr(message, "message_id", None)


async def _get_bot_reply(db, chat_id: int, tg_message_id: int):
    """Текст бот-ответа из DB (ленивый TTL на чтении), fail-open → None."""
    try:
        return await db.get_bot_reply(chat_id, tg_message_id, time.time())
    except Exception:
        logger.warning("thread_chain: bot_replies read failed | chat=%s msg=%s",
                       chat_id, tg_message_id, exc_info=True)
        return None


async def _get_bot_reply_parent(db, chat_id: int, tg_message_id: int):
    """Parent бот-ответа (ленивый TTL), fail-open → None (цепочка оборвётся)."""
    try:
        return await db.get_bot_reply_parent(chat_id, tg_message_id, time.time())
    except Exception:
        logger.warning(
            "thread_chain: bot_reply_parents read failed | chat=%s msg=%s",
            chat_id, tg_message_id, exc_info=True)
        return None


async def collect_thread_chain(db, chat_id: int, message, depth: int, *,
                               row_speaker=None, bot_name_resolver=None,
                               bot_reply_getter=None,
                               bot_parent_getter=None,
                               quote_author_resolver=None) -> list:
    """Рекурсивная цепочка reply по tg_message_id (глубина ``depth``).

    ``message`` — объект с ``.message_id`` (aiogram Message) или сразу id.
    ``db`` — DatabaseService-совместимый источник (get_smart_message_by_tg_id,
    get_bot_reply, get_bot_reply_parent). ``row_speaker`` — опциональный
    резолвер имени user-строки (direct передаёт alias-каскад);
    ``bot_name_resolver`` — имя бота (callable или строка; дефолт «бот»).
    ``bot_reply_getter``/``bot_parent_getter`` — опциональные резолверы
    бот-хода/родителя (direct передаёт свои методы — паритет time/TTL);
    без них используются внутренние fail-open обёртки над ``db``.
    ``quote_author_resolver`` — опциональный ``callable(user_id) -> имя`` для
    автора выделенной цитаты (EVOL v5 §8 п.4: без имени автора цитаты в
    речевой проекции остаётся только число или «автор неизвестен»);
    недоступен → остаётся честное «не определён», догадок нет.
    Возврат — ``list[ChainItem]`` от текущего сообщения к корню; пусто, если
    цепочки нет. Fail-open по БД — на уровне вызывающего."""
    try:
        depth = int(depth or 0)
    except (TypeError, ValueError):
        depth = 0
    if bot_name_resolver is None:
        bot_name = "бот"
    elif callable(bot_name_resolver):
        bot_name = bot_name_resolver() or "бот"
    else:
        bot_name = str(bot_name_resolver)
    speaker = row_speaker or _default_row_speaker

    def _quote_author_name(uid) -> str:
        """Имя автора цитаты через переданный резолвер (fail-open → '')."""
        if quote_author_resolver is None or uid in (None, "", 0):
            return ""
        try:
            return str(quote_author_resolver(uid) or "")
        except Exception:
            logger.debug("thread_chain: quote author resolve failed",
                         exc_info=True)
            return ""

    def _parent_item_id(tg_id) -> str:
        """Известный id родителя → ``tg:<id>``; неизвестен → '' (без догадок)."""
        return resolve_item_id(tg_message_id=tg_id)

    get_report = bot_reply_getter or (
        lambda cid, mid: _get_bot_reply(db, cid, mid))
    get_parent = bot_parent_getter or (
        lambda cid, mid: _get_bot_reply_parent(db, cid, mid))
    chain: list[ChainItem] = []
    current_id = _message_id_of(message)
    seen: set = set()
    # EVOL-015: индекс хода с цитатой, чей оригинал (следующий hop) ещё не
    # разрешён. Разрешён (row/bot-ход) → True; walk оборвался/исчерпал
    # глубину → False (честное «оригинал недоступен», событие
    # quote_unavailable). Оригинал, найденный БЕЗ текста (медиа без маркера),
    # тоже не доставлен → False (текстовая цитата из безтекстового хода
    # не верифицируема).
    pending_quote_idx: int | None = None

    def _resolve_pending_quote(available: bool) -> None:
        nonlocal pending_quote_idx
        if pending_quote_idx is None:
            return
        idx, pending_quote_idx = pending_quote_idx, None
        item = chain[idx]
        if item.quote_original_available is None:
            chain[idx] = item._replace(quote_original_available=available)
            if not available:
                _tg_ref = item.item_id.split(":", 1)[-1] \
                    if item.item_id.startswith("tg:") else None
                _emit_quote_context_event(
                    "unavailable", chat_id=chat_id,
                    message_id=int(_tg_ref)
                    if _tg_ref and _tg_ref.isdigit() else None)
    # Раунд 10.24 (F13, ADR-1024-14 D2): медиа-строки (пустой текст + медиа)
    # не отбрасываются — вместо текста рендерится медиа-маркер. Флаг OFF или
    # отсутствие медиа → прежний скип (байт-в-байт).
    media_enabled = media_context_enabled()
    for _ in range(max(1, depth)):
        if current_id is None or current_id in seen:
            break
        seen.add(current_id)
        row = await db.get_smart_message_by_tg_id(chat_id, current_id)
        if row is not None:
            item_id = resolve_item_id(
                tg_message_id=row_get(row, "tg_message_id"),
                message_id=row_get(row, "id"))
            text = row["text"] or ""
            media_type = ""
            if not text and media_enabled:
                text = row_media_marker(row, item_id=item_id)
                if text:
                    media_type = _media_type_of(row)
            if text:
                name, uid = speaker(row)
                forward_source = (row_get(row, "forward_source")
                                  if row_get(row, "is_forward") else None)
                # EVOL-015: quote-метаданные хода (verbatim; NULL → None).
                # EVOL v5: + реальный id родителя (основание явного отношения)
                # и имя автора цитаты (метка вместо числа).
                quote_author_id = row_get(row, "quote_author_id")
                chain.append(ChainItem(
                    uid=uid, name=name, text=text, is_bot=False,
                    ts=row_get(row, "timestamp"),
                    item_id=item_id,
                    forward_source=forward_source,
                    quote_text=(row_get(row, "quote_text") or None),
                    quote_author_id=quote_author_id,
                    quote_position=row_get(row, "quote_position"),
                    quote_is_manual=row_get(row, "quote_is_manual"),
                    reply_to_item_id=_parent_item_id(row["reply_to_id"]),
                    quote_author_name=_quote_author_name(quote_author_id),
                    media_type=media_type))
                _resolve_pending_quote(True)   # предыдущий quote → найден
                if chain[-1].quote_text:
                    pending_quote_idx = len(chain) - 1
            else:
                _resolve_pending_quote(False)  # ход без текста — не доставлен
            current_id = row["reply_to_id"]
            continue
        bot_text = await get_report(chat_id, current_id)
        bot_sent_at = None
        bot_reply_to = ""
        if bot_text is None:
            # MCA-22 (C2, T-4288; ADR-1028-6 D2): bot_replies TTL/LRU протух
            # → durable ledger `mca_bot_outputs` восстанавливает ход бота и
            # parent-ссылку (регресс §4: «TTL-кеш протух — ledger восстановил»).
            # Gate `MCA_BOT_OUTPUT_LEDGER_ENABLED` OFF → None (паритет:
            # цепочка обрывается как сегодня). Fuzzy-совпадений нет — только
            # точный `(chat_id, tg_message_id)`.
            try:
                from services import bot_output_ledger as _bot_ledger
                _rec = await _bot_ledger.resolve_bot_output_by_tg(
                    db, chat_id, current_id)
            except Exception:
                _rec = None
            if _rec is not None:
                bot_text = _rec.get("content_text")
                bot_sent_at = _rec.get("sent_at")
                _parent_ref = _rec.get("parent_message_ref") or ""
                if bot_text is not None:
                    _resolve_pending_quote(True)   # цитировали ход бота
                    if _parent_ref.startswith("tg:"):
                        bot_reply_to = _parent_ref
                    chain.append(ChainItem(
                        uid=None, name=bot_name, text=bot_text, is_bot=True,
                        ts=bot_sent_at, item_id=f"tg:{current_id}",
                        forward_source=None,
                        reply_to_item_id=bot_reply_to))
                    if _parent_ref.startswith("tg:"):
                        try:
                            current_id = int(_parent_ref.split(":", 1)[1])
                        except (TypeError, ValueError):
                            current_id = None
                    else:
                        current_id = None
                    continue
        if bot_text is not None:
            _resolve_pending_quote(True)   # цитировали ход бота
            chain.append(ChainItem(
                uid=None, name=bot_name, text=bot_text, is_bot=True,
                ts=None, item_id=f"tg:{current_id}", forward_source=None))
            parent = await get_parent(chat_id, current_id)
            if parent is not None:
                # EVOL v5: явное основание Reply для речевой проекции.
                chain[-1] = chain[-1]._replace(
                    reply_to_item_id=_parent_item_id(parent))
            if parent is None:
                break
            current_id = parent
            continue
        break                          # обрыв: нет reply_to_id/не найдено
    _resolve_pending_quote(False)      # walk кончился: оригинал не доставлен
    return chain


# ── EVOL-015: рендер выделенной цитаты хода ─────────────────────────────────
# Цитата — НЕ слова отвечающего: маркируется отдельно, с автором (роль
# различима — анти-инвариант MCA-22), inline в канонической строке (после
# squash — строка остаётся соответствовать per-point pattern «нет голого
# текста»). Приоритет: у хода-триггера цитата = ПРЕДМЕТ ответа, полный
# оригинал — контекст. Недоступный оригинал — честная пометка ограничения.
def _quote_annotation(item: ChainItem, *, is_target: bool) -> str:
    """Аннотация цитаты хода или '' (без цитаты — байт-паритет)."""
    quote_text = (item.quote_text or "").strip()
    if not quote_text:
        return ""
    author = (str(item.quote_author_id)
              if item.quote_author_id is not None else "автор unknown")
    base = f"цитата (автор: {author}): «{quote_text}»"
    if item.quote_original_available is False:
        return (f"{base} — выделенный фрагмент, оригинал недоступен "
                f"(контекст ограничен)")
    if is_target:
        return (f"{base} — выделенный фрагмент оригинала, ПРИОРИТЕТНЫЙ "
                f"ПРЕДМЕТ ответа; полное исходное сообщение — контекст")
    return f"{base} (выделенный фрагмент оригинала выше по цепочке)"


def format_chain_line(item, suffix_map: dict | None = None,
                      trigger_message_id=None) -> str:
    """Каноническая строка хода цепочки (ярус A). user — «[ts | имя [uid] |
    ID]: текст», бот — ts опущен, ID ``tg:``. Ход-триггер (F1) получает
    маркер (единый матчер/guard ``is_target_item_id``).
    EVOL-015: ход с цитатой получает inline-аннотацию выделенного фрагмента
    (без цитаты — байт-в-байт прежняя строка)."""
    if not isinstance(item, ChainItem):
        item = ChainItem(*item)
    if item.is_bot:
        author = speaker_tag(item.name, None, is_bot=True)
    else:
        author = speaker_tag(
            item.name, item.uid, suffix=(suffix_map or {}).get(item.uid, ""))
    is_target = is_target_item_id(item.item_id, trigger_message_id)
    text = item.text
    annotation = _quote_annotation(item, is_target=is_target)
    if annotation:
        text = f"{text}\n{annotation}"
        # EVOL-015: цитата реально ушла в LLM-контекст (render = delivery).
        _tg_ref = (item.item_id.split(":", 1)[-1]
                   if item.item_id.startswith("tg:") else None)
        _emit_quote_context_event(
            _QUOTE_DELIVERED_EVENT, chat_id=None,
            message_id=int(_tg_ref)
            if _tg_ref and _tg_ref.isdigit() else None)
    return format_context_item(
        ts=item.ts, author=author, item_id=item.item_id,
        forward_source=item.forward_source, text=text, kind="msg",
        is_target=is_target)


_REPLY_CHAINS_NOTE = (
    '<reply_chains note="цепочки ответов вокруг тейка — это контекст, '
    'а НЕ доказательства и НЕ источник фактов">')


def _wrap_reply_chains(lines) -> str:
    """Общая обёртка под-блока `<reply_chains>` (сырой и речевой вид)."""
    if not lines:
        return ""
    return _REPLY_CHAINS_NOTE + "\n" + "\n".join(lines) + "\n</reply_chains>"


def _render_raw_chains(chain, trigger_message_id=None) -> str:
    """Сырой вид под-блока (откат флага): ``tg:``/числовой автор цитаты."""
    return _wrap_reply_chains(
        [format_chain_line(item, None, trigger_message_id)
         for item in reversed(chain)])


def render_reply_chains(chain: list, trigger_message_id=None, *,
                        projection=None) -> str:
    """``<reply_chains>``-под-блок фактчека (ASC: корень → якорь) или ''
    при пустой цепочке. Явная пометка: цепочки — контекст, НЕ доказательства
    (учитываем growth поверхности фантомных fact/msg-якорей).

    EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 §4.2: это ЧИСТО речевая поверхность —
    результат целиком уходит в LLM-payload (`factcheck_context.render_feed`,
    `factcheck_suitability` feed, `handlers.factcheck`), машинных парсеров
    внутри ID нет. Поэтому по умолчанию рендерится РЕЧЕВАЯ проекция (метки
    прогона вместо `tg:`/числового uid, явные отношения), а ``projection``
    позволяет переиспользовать общий прогон. Ровно ``flags.
    context_speech_projection`` OFF → сырой под-блок байт-в-байт (откат).

    Единственное исключение — общий `format_chain_line` (нужен direct-дедупу
    по `tg:`, attribution, планировщику): он остаётся сырым, и вызывающие
    машинные потребители берут именно его."""
    if not chain:
        return ""
    if not speech_projection_enabled():
        return _render_raw_chains(chain, trigger_message_id)
    active = projection if projection is not None else SpeechProjection()
    return _render_speech_chains(chain, active, trigger_message_id)


# ── EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 §4.2 — речевая проекция цепочки ─────
# `format_chain_line` остаётся СЫРЫМ видом (машинная сторона: dedup по `tg:`,
# attribution, планировщик). Речевая сторона — `render_speech_line` (для
# построчного рендера на стороне direct), `render_reply_chains` выше (для
# под-блока фактчека) и `format_speech_item` в canonical_context.
_QUOTE_DELIVERED_EVENT = "delivered_to_context"


def _speech_quote(item, *, is_target: bool):
    """Выделенная цитата хода → `SpeechQuote` (или None). Автор — имя/метка,
    не числовой uid (§9.2)."""
    if not (item.quote_text or "").strip():
        return None
    return SpeechQuote(
        text=item.quote_text,
        author_name=item.quote_author_name,
        author_uid=item.quote_author_id,
        original_available=item.quote_original_available,
        priority_subject=is_target)


def _speech_reply_relation(item):
    """Подтверждённый Reply-край хода → `SpeechRelation` (None — связи нет).

    Печатается ТОЛЬКО при известном реальном id родителя; родитель вне окна
    даёт честный `missing_edge` без выдуманного ID (§8)."""
    raw = str(item.reply_to_item_id or "").strip()
    if not raw:
        return None
    return SpeechRelation(kind=RELATION_REPLY, target_item_id=raw,
                          basis="Telegram Reply")


def render_speech_line(item, projection, suffix_map: dict | None = None,
                       trigger_message_id=None, relations=()) -> str:
    """Речевая строка хода цепочки (EVOL v5 §4.2 п.2).

    Всё содержательное сохраняется: абсолютное время, имя+`U`-метка автора,
    ``Переслано:``, медиа-тип, выделенная цитата с автором, Reply-край и
    маркер целевого хода. Меняется ровно *неозвучиваемая* форма технических
    ключей: ``tg:<id>`` → ``M<n>`` с обратным отображением в
    `SpeechProjection` (§5.4 «допустимы метки при точном обратном
    отображении»)."""
    if not isinstance(item, ChainItem):
        item = ChainItem(*item)
    suffix = (suffix_map or {}).get(item.uid, "") if not item.is_bot else ""
    author = f"{item.name}{suffix}" if suffix else item.name
    is_target = is_target_item_id(item.item_id, trigger_message_id)
    quote = _speech_quote(item, is_target=is_target)
    if quote is not None:
        # EVOL-015: цитата реально ушла в LLM-контекст (render = delivery).
        _tg_ref = (item.item_id.split(":", 1)[-1]
                   if item.item_id.startswith("tg:") else None)
        _emit_quote_context_event(
            _QUOTE_DELIVERED_EVENT, chat_id=None,
            message_id=int(_tg_ref)
            if _tg_ref and _tg_ref.isdigit() else None)
    if item.media_type:
        # Медиа-строка: маркер перерисовывается меткой (реф = та же строка).
        text = media_marker(item.media_type, item.item_id,
                            projection=projection)
    else:
        text = item.text
    edge = _speech_reply_relation(item)
    all_relations = ([edge] if edge is not None else []) + list(relations or ())
    return format_speech_item(
        ts=item.ts, author=author,
        author_uid=None if item.is_bot else item.uid,
        item_id=item.item_id, forward_source=item.forward_source,
        text=text, kind="msg", is_target=is_target,
        projection=projection, relations=all_relations, quote=quote)


def _render_speech_chains(chain: list, projection,
                          trigger_message_id=None) -> str:
    """Речевой под-блок `<reply_chains>` (EVOL v5 §4.2).

    Рендер идёт в порядке хронологии (корень → якорь), поэтому нумерация
    меток соответствует хронологии прогона, а к моменту рендера потомка
    метка родителя уже известна — отношение «отвечает на M2» печатается, а
    не деградирует в `missing_edge` (§4.3 п.3)."""
    chronological = [it if isinstance(it, ChainItem) else ChainItem(*it)
                     for it in reversed(chain)]
    lines = [render_speech_line(it, projection, None, trigger_message_id)
             for it in chronological]
    if not lines:
        return ""
    emit_speech_projection_event(projection)
    return _wrap_reply_chains(lines)
