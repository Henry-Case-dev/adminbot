"""Epic 65 — chat_context: окно сообщений вокруг цели для фактчека/поиска.

Исследование (NAACL 2022 «Role of Context…»: +10 п.т. от локального контекста;
MAD2 2026: past-only context ≈ full; SIGIR 2026: длинный контекст ВРЕДИТ,
улики лучше по краям промпта) → маленькое окно последних сообщений чата,
чётко маркированное как НЕ-доказательства, сразу после <claim>.
"""
import logging

from services.canonical_context import format_context_item, resolve_item_id
from services.database import row_get
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


def _truncate_reply_chains(block: str, limit: int) -> str:
    """Обрезать уже отрендеренный ``<reply_chains>`` до ``limit`` символов,
    сохранив корректные открывающий/закрывающий теги. Вытесняются ДАЛЬНИЕ
    (корневые) ходы первыми — keep-end, как в окне; якорь-цепочка сохраняется
    по максимуму. Нет места даже на теги / нет тела → '' (блок опускается)."""
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
    overhead = len(head) + len(_REPLY_CHAINS_CLOSE)
    if limit < overhead:
        return ""
    budget = limit - overhead
    inner_lines = inner.split("\n")
    if inner_lines and inner_lines[0] == "":
        inner_lines = inner_lines[1:]
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
    return head + "\n".join(kept) + _REPLY_CHAINS_CLOSE


def format_chat_context(rows, max_chars: int = _CHAT_CONTEXT_MAX_CHARS,
                        trigger_message_id=None, reply_chains: str = "",
                        anchor_message_id=None) -> str:
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
    """
    wrapper = ("<chat_context " + _CONTEXT_NOTE + ">\n", "\n</chat_context>")
    content_budget = max(0, max_chars - len(wrapper[0]) - len(wrapper[1]))
    rendered: list[tuple[str, bool]] = []      # (line, is_anchor)
    remaining_trigger = trigger_message_id
    for row in rows:
        text = (row["text"] or "").strip()
        if not text:
            continue
        name = row["author_name"] or f"id{row['user_id'] or '?'}"
        forward_source = (row_get(row, "forward_source")
                          if row_get(row, "is_forward") else None)
        is_marked = is_target_row(row, remaining_trigger)
        is_anchor = is_target_row(row, anchor_message_id)
        line = format_context_item(
            ts=row_get(row, "timestamp"), author=name,
            item_id=resolve_item_id(
                tg_message_id=row_get(row, "tg_message_id"),
                message_id=row_get(row, "id")),
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
    return wrapper[0] + body + wrapper[1]
