"""Epic 65 — chat_context: окно сообщений вокруг цели для фактчека/поиска.

Исследование (NAACL 2022 «Role of Context…»: +10 п.т. от локального контекста;
MAD2 2026: past-only context ≈ full; SIGIR 2026: длинный контекст ВРЕДИТ,
улики лучше по краям промпта) → маленькое окно последних сообщений чата,
чётко маркированное как НЕ-доказательства, сразу после <claim>.
"""
import logging

from services.canonical_context import (
    format_context_item,
    format_speech_item,
    resolve_item_id,
    speech_projection_enabled,
)
from services.database import row_get
from services.media_marker import media_context_enabled, row_media_marker
from services.target_marking import is_target_row

logger = logging.getLogger(__name__)

_CHAT_CONTEXT_MAX_CHARS = 2000     # SIGIR'26: большой контекст ухудшает верификацию

# Явный потолок вложенного под-блока цепочек (F2, R1023F2-01): даже при
# большом бюджете окна цепочка не раздувает промпт сверх этого значения.
_REPLY_CHAINS_MAX_CHARS = 1200

_CONTEXT_NOTE = (
    'note="болтовня чата вокруг цели — только чтобы понять, о чём речь; '
    'это НЕ доказательства и НЕ источник фактов"'
)

_REPLY_CHAINS_CLOSE = "</reply_chains>"

# Явная пометка неполноты (EVOL v5 §5.1/§5.2, B1 ревью): keep-end вытесняет
# САМЫЕ СТАРЫЕ ходы, то есть корень цепочки — тот, что объясняет цель. Молча
# терять его запрещено, поэтому при реальной обрезке в блоке печатается
# честное «часть цепочки не показана (N)» — бюджет и лимит блока не растут.
_REPLY_CHAINS_OMITTED = "…часть цепочки не показана ({count})"


def _reply_chains_omitted_note(count: int) -> str:
    return _REPLY_CHAINS_OMITTED.format(count=int(count))


# То же правило для САМОГО окна: при обрезке в бюджет вытесняются самые старые
# строки before (якорь/свежие сохраняются), и это тоже не должно быть молчаливым
# (§5.4 «реальное отсутствие помечается как неполнота», §8 п.5).
_CHAT_CONTEXT_OMITTED = "…часть окна не показана ({count})"


def _window_omitted_note(count: int) -> str:
    return _CHAT_CONTEXT_OMITTED.format(count=int(count))


def _lines_len(lines) -> int:
    """Длина набора строк в блоке: сами строки + разделители между ними."""
    count = len(lines)
    if not count:
        return 0
    return sum(len(line) for line in lines) + (count - 1)


def _truncate_reply_chains(block: str, limit: int) -> str:
    """Обрезать уже отрендеренный ``<reply_chains>`` до ``limit`` символов,
    сохранив корректные открывающий/закрывающий теги. Вытесняются ДАЛЬНИЕ
    (корневые) ходы первыми — keep-end, как в окне; якорь-цепочка сохраняется
    по максимуму. Реальная обрезка НЕ молчит: сверху блока появляется строка
    «…часть цепочки не показана (N)» (счётчик вытесненных ходов), и она сама
    укладывается в тот же ``limit`` — при нехватке места вытесняется ещё один
    самый старый ход. Нет места даже на теги / нет тела → '' (блок
    опускается)."""
    if limit <= 0:
        return ""
    text = str(block or "")
    if not text:
        return ""
    if len(text) <= limit:
        return text
    if not text.endswith(_REPLY_CHAINS_CLOSE):
        return ""
    open_end = text.find(">")
    if open_end == -1:
        return ""
    head = text[:open_end + 1]
    inner = text[open_end + 1:-len(_REPLY_CHAINS_CLOSE)]
    # Структура под-блока — header + "\n" + строки + "\n" + close (как в
    # `_wrap_reply_chains`): переводы строк вокруг тела входят в бюджет.
    overhead = len(head) + len(_REPLY_CHAINS_CLOSE) + 2
    if limit < overhead:
        return ""
    budget = limit - overhead
    inner_lines = inner.split("\n")
    if inner_lines and inner_lines[0] == "":
        inner_lines = inner_lines[1:]
    total_lines = len([line for line in inner_lines if line])
    kept: list[str] = []
    used = 0
    for line in reversed(inner_lines):
        if not line:
            continue
        addition = len(line) + (1 if kept else 0)
        if used + addition > budget:
            break
        kept.append(line)
        used += addition
    if not kept:
        return ""
    kept.reverse()
    dropped = total_lines - len(kept)
    if dropped > 0:
        note = _reply_chains_omitted_note(dropped)
        # Новейший ход сохраняется всегда; для пометки нехватки места
        # вытесняются только более старые (и тогда N честно растёт).
        while len(kept) > 1 and (_lines_len(kept) + 1 + len(note)) > budget:
            kept.pop(0)
            dropped += 1
            note = _reply_chains_omitted_note(dropped)
        if (_lines_len(kept) + 1 + len(note)) <= budget:
            kept.insert(0, note)
    return head + "\n" + "\n".join(kept) + "\n" + _REPLY_CHAINS_CLOSE


def format_chat_context(rows, max_chars: int = _CHAT_CONTEXT_MAX_CHARS,
                        trigger_message_id=None, reply_chains: str = "",
                        anchor_message_id=None,
                        media_blocks: dict | None = None,
                        media_for_captioned: bool = False,
                        projection=None) -> str:
    """rows — хронологический список строк smart_messages (sqlite3.Row с
    author_name/user_id/text). → '<chat_context …>…</chat_context>' или ''
    (пустое окно / нет текстов).

    Политика усечения (R1023F2-10): keep-end с приоритетом ЯКОРЯ (целевого
    сообщения, ``anchor_message_id``) — сохраняются якорь, затем наиболее
    свежие ``after`` (keep-end), затем ``reply_chains`` (из остатка), затем
    ближние к якорю ``before``; первыми вытесняются САМЫЕ СТАРЫЕ ``before``.
    Длина всего блока ≤ ``max_chars`` (обёртка + окно + цепочка; R1023F2-01).

    10.20 (БЛОК 0, ADR-1020-1 ред. 3, точка 13): строка — канонический
    контекст-элемент `[Дата Время | Автор | ID | Переслано]: текст`
    (данные ts/tg/id/forward доступны в smart_messages; R16 — опускаем
    отсутствующее).

    10.23 (F1, ADR-1023-1): ``trigger_message_id`` — id команды; совпавшее
    сообщение помечается маркером; ``None``/нет совпадения → маркер не
    ставится. При дубле id маркируется только первое.

    10.23 (F2, ADR-1023-2): ``reply_chains`` — уже отрендеренный
    ``<reply_chains>``-под-блок (общий util ``services/thread_chain.py``),
    вставляется в конец ``<chat_context>`` после окна. ``anchor_message_id`` —
    целевое сообщение (центр окна), приоритет усечения.

    R1023F2-11: для окон, превышающих бюджет, усечение может отличаться от
    до-F2 алгоритма (теперь бюджет строго ≤ ``max_chars``, включая обёртку);
    при ``reply_chains=""`` и помещающемся окне вывод функционально прежний.

    EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§4.2 п.2): ``projection`` — общий
    ``SpeechProjection`` прогона. Задан → строки рендерятся РЕЧЕВОЙ функцией
    `format_speech_item` (метка прогона в слоте ID, «Имя (U1)» в авторе,
    абсолютное время/`Переслано:`/маркер цели без изменений). ``None`` или
    рубильник OFF → прежний сырой канон байт-в-байт.
    """
    wrapper = ("<chat_context " + _CONTEXT_NOTE + ">\n", "\n</chat_context>")
    content_budget = max(0, max_chars - len(wrapper[0]) - len(wrapper[1]))
    rendered: list[tuple[str, bool]] = []      # (line, is_anchor)
    remaining_trigger = trigger_message_id
    # Раунд 10.24 (F13, ADR-1024-14 D2): строки с пустым текстом и нативным
    # медиа не скипаются — рендерится медиа-маркер. Флаг OFF или отсутствие
    # медиа → прежний скип (байт-в-байт, окно/бюджет усечения не меняются).
    media_enabled = media_context_enabled()
    for row in rows:
        item_id = resolve_item_id(
            tg_message_id=row_get(row, "tg_message_id"),
            message_id=row_get(row, "id"))
        text = (row["text"] or "").strip()
        tg_id = 0
        if media_blocks:
            try:
                tg_id = int(row_get(row, "tg_message_id") or 0)
            except Exception:
                tg_id = 0
        if not text and media_enabled:
            text = row_media_marker(row, item_id=item_id,
                                    projection=projection)
            # Rework R1 (H-2, review T-5124): прод-шов единого renderer'а D9 —
            # блок фасада (OCR/описание/pending, два времени) поверх старого
            # маркера. media_blocks=None (гейт OFF/ошибка) → прежний путь
            # байт-в-байт; для строки без блока (не изображение/нет актива/
            # ошибка рендера) старый маркер сохраняется.
            if media_blocks and tg_id:
                block = media_blocks.get(tg_id)
                if block:
                    text = block
        elif text and media_enabled and media_for_captioned and media_blocks \
                and tg_id and tg_id in media_blocks:
            # ASAP-VISION-SYNC-01 §4.6 (review-fix2, P2): фото С ПОДПИСЬЮ
            # раньше теряло содержимое картинки (блок фасада подставлялся
            # только для строк без текста) — поиск отвечал по подписи, хотя
            # готовый OCR уже есть. Содержимое картинки идёт рядом с подписью
            # отдельной строкой: это данные распознавания, не слова автора.
            # Явный параметр → остальные потребители контекста получают
            # прежний вывод байт-в-байт.
            text = f"{text}\n{media_blocks[tg_id]}"
        if not text:
            continue
        name = row["author_name"] or f"id{row['user_id'] or '?'}"
        forward_source = (row_get(row, "forward_source")
                          if row_get(row, "is_forward") else None)
        is_marked = is_target_row(row, remaining_trigger)
        is_anchor = is_target_row(row, anchor_message_id)
        if projection is not None and speech_projection_enabled():
            # Речевая проекция (§4.2 п.2): тот же автор/время/forward/маркер,
            # но в слоте ID — метка прогона, а рядом с ником — `U`-метка
            # (одноимённые участники не сливаются, §5.4/§13 сц.97).
            line = format_speech_item(
                ts=row_get(row, "timestamp"), author=name,
                author_uid=row_get(row, "user_id"),
                item_id=item_id,
                forward_source=forward_source, text=text, kind="msg",
                is_target=is_marked, projection=projection)
        else:
            line = format_context_item(
                ts=row_get(row, "timestamp"), author=name,
                item_id=item_id,
                forward_source=forward_source, text=text, kind="msg",
                is_target=is_marked)
        if is_marked:
            remaining_trigger = None
        rendered.append((line, is_anchor))
    if not rendered:
        return ""
    n = len(rendered)
    anchor_idx = next((i for i, (_l, a) in enumerate(rendered) if a), None)

    def _join_len(indices) -> int:
        if not indices:
            return 0
        return len("\n".join(rendered[i][0] for i in indices))

    selected: list[int] = []
    # 1) Якорь — высший приоритет (сохраняем, если влезает хотя бы один).
    if anchor_idx is not None and len(rendered[anchor_idx][0]) <= content_budget:
        selected.append(anchor_idx)

    def _reserve_chain() -> tuple[str, int]:
        if not (reply_chains and selected):
            return "", 0
        remaining = content_budget - _join_len(selected) - 1
        if remaining <= 0:
            return "", 0
        out = _truncate_reply_chains(
            reply_chains, min(_REPLY_CHAINS_MAX_CHARS, remaining))
        return out, ((1 + len(out)) if out else 0)

    # 2) При наличии якоря цепочка резервируется СРАЗУ (R1023F2-10: сохраняем
    #    якорь/цепочку/свежие after; старые before вытесняются первыми).
    chain_out, chain_tail = _reserve_chain()
    # 3) `after` — от свежайшего к якорю (keep-end): старые after вытесняются.
    after_indices = (range(n - 1, anchor_idx, -1) if anchor_idx is not None
                     else range(n - 1, -1, -1))
    for i in after_indices:
        if _join_len(selected + [i]) + chain_tail <= content_budget:
            selected.append(i)
        else:
            break
    # Без якоря (fallback-окно) цепочка резервируется после набора окна.
    if not chain_out and anchor_idx is None:
        chain_out, chain_tail = _reserve_chain()
    # 4) `before` — от ближнего к якорю: первыми вытесняются самые старые.
    before_indices = (range(anchor_idx - 1, -1, -1)
                      if anchor_idx is not None else range(0))
    for i in before_indices:
        candidate_len = _join_len(sorted(selected + [i])) + chain_tail
        if candidate_len <= content_budget:
            selected.append(i)
        else:
            break
    if not selected:
        return ""
    body = "\n".join(rendered[i][0] for i in sorted(selected))
    if chain_out:
        body = body + "\n" + chain_out
    # §5.4 (CONTEXT-FIDELITY-01 п.153): вытеснение строк окна бюджетом не
    # должно быть МОЛЧАЛИВЫМ. Раунд 10.23 уже сохраняет якорь/свежие строки,
    # но факт неполноты раньше не объявлялся — читаем реальное число
    # вытесненных строк и пишем его той же короткой пометкой, что у цепочки.
    omitted = n - len(selected)
    if omitted > 0:
        note = _window_omitted_note(omitted)
        candidate = f"{note}\n{body}"
        if len(candidate) + len(wrapper[0]) + len(wrapper[1]) <= max_chars:
            body = candidate
        else:
            logger.warning(
                "[chat_context] окно усечено без пометки — бюджет исчерпан | "
                "omitted=%d | budget=%d", omitted, max_chars)
    return wrapper[0] + body + wrapper[1]


# ── Rework R1 (H-2, review T-5124): прод-шов renderer'а D9 ──────────────────
# Единый renderer `render_media_context_async` (mca_vision, D9) получает
# фактического потребителя в сборке контекста: для строк с нативным медиа
# блок фасада (OCR/описание/pending, event ≠ knowledge) заменяет старый
# маркер «[фото]». Read-only: готовые анализы читаются из БД, НОВЫХ
# vision-вызовов/джоб здесь нет (AUTO-гейт — про запись, не про чтение).

async def collect_media_analysis_blocks(db, chat_id: int,
                                        rows) -> dict | None:
    """Пре-рендер media-блоков строк окна (или None → байт-в-байт паритет).

    Гейты: мастер K1 `MCA_VISION_ENABLED` AND requested владельца чата
    (per-chat тумблер). OFF/ошибка/нет db/нет медиа-строк → None — вызывающий
    получает прежний контекст байт-в-байт. Результат: {tg_message_id: текст
    фасада D9}; для не-изображений (voice/video) renderer вернёт None →
    строки в словаре нет → старый маркер сохраняется. Ошибка рендера одной
    строки не ломает остальные; сам коллектор никогда не бросает."""
    try:
        from services import mca_gates
        from services import mca_vision
        from services.media_marker import is_media_type
        if db is None or not mca_gates.vision_enabled():
            return None
        try:
            requested = await mca_vision.resolve_requested(int(chat_id))
        except Exception:
            logger.warning("chat_context: requested resolve failed | chat=%s",
                           chat_id, exc_info=True)
            return None
        if not requested:
            return None
        blocks: dict[int, str] = {}
        seen: set[int] = set()
        for row in rows or ():
            try:
                if not is_media_type(row_get(row, "media_type")):
                    continue
                row_chat = int(row_get(row, "chat_id") or chat_id or 0)
                tg_id = int(row_get(row, "tg_message_id") or 0)
            except Exception:
                continue
            if not row_chat or not tg_id or tg_id in seen:
                continue
            seen.add(tg_id)
            try:
                rendered = await mca_vision.render_media_context_async(
                    db, chat_id=row_chat, tg_message_id=tg_id)
            except Exception:
                logger.warning("chat_context: media block render failed | "
                               "chat=%s tg=%s", row_chat, tg_id,
                               exc_info=True)
                continue
            text = str((rendered or {}).get("text") or "").strip()
            if text:
                blocks[tg_id] = text
        return blocks or None
    except Exception:
        logger.warning("chat_context: media blocks collect failed",
                       exc_info=True)
        return None


async def build_chat_context(db, rows, *, chat_id: int,
                             max_chars: int = _CHAT_CONTEXT_MAX_CHARS,
                             trigger_message_id=None, reply_chains: str = "",
                             anchor_message_id=None,
                             media_for_captioned: bool = False,
                             projection=None) -> str:
    """Прод-сборка контекста (единственная точка шва H-2): окна чата для
    direct/autonomous-потребителей (smartsearch/factcheck) с media-блоками
    renderer'а D9 под гейтом. Гейт OFF → ``format_chat_context`` на тех же
    строках без media_blocks — байт-в-байт прежний контекст.

    ``media_for_captioned`` (ASAP-VISION-SYNC-01 §4.6, review-fix2): медиа с
    подписью тоже получает блок содержимого (OCR/описание или честный статус).
    Включает потребитель, которому нужен поиск по картинке (smartsearch);
    остальные контексты остаются прежними."""
    media_blocks = await collect_media_analysis_blocks(db, chat_id, rows)
    return format_chat_context(
        rows, max_chars=max_chars, trigger_message_id=trigger_message_id,
        reply_chains=reply_chains, anchor_message_id=anchor_message_id,
        media_blocks=media_blocks,
        media_for_captioned=bool(media_for_captioned),
        projection=projection)


# ── ASAP-VISION-SYNC-01 §4.4: актуальная ревизия медиа для потребителя ──────
# `format_chat_context` остаётся байт-в-байт прежним (рендер только готовых
# анализов). Эти два хелпера дают потребителю возможность (а) перечитать ОДИН
# медиа-блок заново после готовности Vision и (б) проверить, что он получил
# актуальную ревизию, а не старый pending-снимок. Новых vision-вызовов нет.


async def refresh_media_block(db, chat_id: int, tg_message_id: int) -> dict:
    """Свежий медиа-блок сообщения + фактическая ревизия анализа.

    Возвращает ``{"text": str, "analysis_status": str, "analysis_revision":
    int|None, "pending": bool, "association": str}``; пустой словарь — медиа
    нет/гейт OFF/ошибка (потребитель сохраняет прежнее поведение)."""
    if db is None:
        return {}
    try:
        from services import media_readiness
        from services import mca_gates
        from services import mca_vision
        if not mca_gates.vision_enabled():
            return {}
        if not await mca_vision.resolve_requested(int(chat_id)):
            return {}
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=int(chat_id), tg_message_id=int(tg_message_id))
        text = str((rendered or {}).get("text") or "").strip()
        readiness = await media_readiness.prepare_media_evidence(
            db, chat_id=int(chat_id), message_id=int(tg_message_id),
            consumer="chat_context", wait_seconds=0.0, enqueue=False,
            force=True)
        status = ""
        revision = None
        pending = False
        association = ""
        if readiness is not None:
            status = readiness.analysis_status
            revision = readiness.analysis_revision
            pending = readiness.pending
            association = readiness.association_kind
        return {"text": text, "analysis_status": status,
                "analysis_revision": revision, "pending": pending,
                "association": association}
    except Exception:
        logger.warning("chat_context: media block refresh failed | chat=%s "
                       "tg=%s", chat_id, tg_message_id, exc_info=True)
        return {}


async def pending_media_targets(db, chat_id: int, rows,
                                anchor_message_id=None) -> dict:
    """Какие медиа окна ещё НЕ готовы: ``{tg_message_id: reason_code}``.

    Потребитель (Direct/FactCheck) использует это, чтобы не выдать
    окончательный вывод по изображению, анализ которого не получен."""
    if db is None:
        return {}
    try:
        from services import media_readiness
        result: dict[int, str] = {}
        for row in rows or ():
            try:
                if not is_media_type(row_get(row, "media_type")):
                    continue
                tg_id = int(row_get(row, "tg_message_id") or 0)
            except Exception:
                continue
            if not tg_id:
                continue
            if anchor_message_id is not None and \
                    tg_id != int(anchor_message_id):
                continue
            state = await media_readiness.prepare_media_evidence(
                db, chat_id=int(chat_id), message_id=tg_id,
                consumer="chat_context", wait_seconds=0.0, enqueue=False,
                force=True)
            if state is None or state.ready:
                continue
            result[tg_id] = state.reason_code or "vision_queued"
        return result
    except Exception:
        logger.debug("chat_context: pending media scan failed", exc_info=True)
        return {}
