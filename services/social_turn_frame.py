"""EVOL — социальный контекст хода (доп. директива §§1–3, 31.10.2026).

`SocialTurnFrame` — ВРЕМЕННАЯ структура одного хода (живёт только в рамках
текущего turn'а), собранная из УЖЕ загруженных данных:

  * Telegram-метаданные сообщения (`reply_to_message`, `quote.text`) —
    нативный reply и выбранный фрагмент цитаты;
  * MCA-22 bundle (`reply_addressee` / `quoted_speaker` / `ambiguities` /
    `branch`) — канонический ряд MCA-03 + существующий Quote Resolver;
  * окно чата (`tg_message_id` ближайшей ветки) — для инициативного повода;
  * существующий `RelationsService` — ТОЛЬКО стаж/активность/ручные пометки.

0 LLM-вызовов, 0 новых таблиц, 0 фоновых задач, 0 второго store. Семантику
(«дружеский подкол или спор», «сказать или промолчать», tone/response_act)
по-прежнему решает СУЩЕСТВУЮЩИЙ L1/Decision — адаптер лишь подаёт ему
структуру текущего социального обмена.

Приоритет источников адресации (директива §2.1):

  1. нативный Telegram reply (`reply_to_message.message_id` +
     `reply_to_message.from_user.id`) и выделенный фрагмент цитаты;
  2. достоверные связи уже собранной ветки (`bundle.reply_addressee`,
     `bundle.quoted_speaker`, `bundle.branch`);
  3. иначе — честный `unknown`/`ambiguous`; адресат НИКОГДА не угадывается
     по имени/алиасу в тексте и не выбирается «самым частым собеседником».

Инварианты:

  * говорящий (`speaker_user_id`), адресат (`addressed_user_id`) и автор
    цитаты (`quote_author_user_id`) — ТРИ разных слота: это могут быть три
    разных человека, автор цитаты не становится автором запроса;
  * идентичность — Telegram user ID / message ID; алиас — только отображение;
  * `quote_span` — именно выделенный фрагмент, а не весь оригинальный текст;
  * `relation_ref` — данные существующего RelationsService (стаж, активность,
    явные ручные пометки). Это НЕ социальный рейтинг и НЕ оценка уместности
    подкола: `activity_score` в кадр не переносится;
  * ошибка/недоступность адаптера → пустой кадр, прежний путь ответа
    продолжает работать (fail-open, без новых LLM-вызовов);
  * kill-switch `SOCIAL_TURN_FRAME_ENABLED` (env, per-call, default ON):
    OFF → пустой кадр и точный прежний payload (байт-паритет).

R17: наружу (события/логи) — только id/коды; сырые реплики не логируются.
"""
from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger(__name__)

#: Kill-switch (env-ось, per-call; тот же резолвер, что у осей W2).
GATE_NAME = "SOCIAL_TURN_FRAME_ENABLED"

# ── статус атрибуции (директива §2.1) ───────────────────────────────────────
ATTRIBUTION_RESOLVED = "resolved"
ATTRIBUTION_AMBIGUOUS = "ambiguous"
ATTRIBUTION_UNKNOWN = "unknown"
ATTRIBUTION_STATUSES = (ATTRIBUTION_RESOLVED, ATTRIBUTION_AMBIGUOUS,
                        ATTRIBUTION_UNKNOWN)

#: Кап выделенного фрагмента цитаты (это фрагмент, не весь пост).
QUOTE_SPAN_MAX = 240
#: Кап реальных ID ветки (bounded; окно уже загружено вызывающим).
CONTEXT_REFS_MAX = 8
#: Кап подсказки Writer'у (короткая, источниковая; не «социальный текст»).
HINT_MAX_CHARS = 300

#: Маркер ambiguous-резолва цитаты в bundle v2 (`quote:priority_N`).
_AMBIGUITY_QUOTE_PREFIX = "quote:"

#: Allowlist ключей RelationsService для `relation_ref` (НЕ activity_score).
_RELATION_KEYS = ("user_id", "stage", "stage_manual", "first_seen",
                  "last_seen", "msg_count", "msg30", "note")


@dataclasses.dataclass(frozen=True)
class SocialTurnFrame:
    """Канонический социальный кадр одного хода (директива §2.1).

    Frozen и in-memory: durable-записи нет, второй схемы нет. Пустой кадр
    (все поля кроме `chat_id` = None/()) — штатный fail-open результат.
    """

    chat_id: int
    trigger_message_id: int | None = None
    speaker_user_id: int | None = None
    addressed_user_id: int | None = None
    addressed_message_id: int | None = None
    #: Автор цитаты — ОТДЕЛЬНЫЙ слот (может не совпадать с адресатом).
    quote_author_user_id: int | None = None
    quote_span: str | None = None
    #: Реальные Telegram ID ближайшей релевантной ветки (из уже собранного
    #: окна/bundle.branch), не отдельный запрос на каждое сообщение.
    context_refs: tuple[int, ...] = ()
    #: Только существующие данные RelationsService (стаж/активность/заметки).
    relation_ref: dict | None = None
    attribution_status: str = ATTRIBUTION_UNKNOWN

    def has_addressing(self) -> bool:
        """Есть ли у хода хоть какая-то доказанная/спорная адресация."""
        return bool(self.addressed_message_id or self.quote_span
                    or self.addressed_user_id
                    or self.attribution_status == ATTRIBUTION_AMBIGUOUS)


def feature_enabled() -> bool:
    """`SOCIAL_TURN_FRAME_ENABLED` (env, default ON, per-call). Не бросает."""
    try:
        from services.mca_gates import w2_env_axis
        return w2_env_axis(GATE_NAME, True)
    except Exception:                                   # pragma: no cover
        return True


def empty_frame(chat_id) -> SocialTurnFrame:
    """Пустой кадр (fail-open результат; никогда не бросает)."""
    try:
        value = int(chat_id)
    except (TypeError, ValueError):
        value = 0
    return SocialTurnFrame(chat_id=value)


def _as_int(value) -> int | None:
    """Положительный int либо None (bool/мусор/≤0 → None). Не бросает."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _row_get(row, key, default=None):
    """Безопасное чтение ключа из dict / sqlite Row / объекта."""
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


def _clean_quote(text) -> str | None:
    """Выделенный фрагмент цитаты → одна строка без переводов строк.

    Угловые скобки заменяются на безопасные аналоги: фрагмент — это данные
    пользователя, он не должен уметь закрыть структурный тег плана."""
    if not isinstance(text, str):
        return None
    value = " ".join(text.split()).strip()
    if not value:
        return None
    value = value.replace("<", "‹").replace(">", "›")
    return value[:QUOTE_SPAN_MAX]


def _refs_from_branch(branch) -> tuple[int, ...]:
    """`bundle.branch` (`tg:<id>`/`msg:<id>`) → реальные Telegram ID ветки."""
    out: list[int] = []
    try:
        for ref in tuple(branch or ()):
            text = str(ref or "")
            if not text.startswith("tg:"):
                continue
            number = _as_int(text.split(":", 1)[1])
            if number is not None and number not in out:
                out.append(number)
            if len(out) >= CONTEXT_REFS_MAX:
                break
    except Exception:                                   # pragma: no cover
        return tuple(out)
    return tuple(out)


def _refs_from_window(window) -> tuple[int, ...]:
    """Окно чата → последние реальные `tg_message_id` (bounded)."""
    out: list[int] = []
    try:
        rows = list(window or ())
    except Exception:                                   # pragma: no cover
        return ()
    for row in reversed(rows):
        number = _as_int(_row_get(row, "tg_message_id"))
        if number is not None and number not in out:
            out.append(number)
        if len(out) >= CONTEXT_REFS_MAX:
            break
    out.reverse()
    return tuple(out)


def relation_ref_from_relation(relation) -> dict | None:
    """Карточка RelationsService → `relation_ref` (allowlist, без рейтинга).

    Переносятся только стаж/активность/ручные пометки; `activity_score`
    сознательно не переносится — это не «любовь», не «вражда» и не
    социальный рейтинг (директива §2.1 п.5)."""
    if not isinstance(relation, dict) or not relation:
        return None
    ref = {}
    for key in _RELATION_KEYS:
        value = relation.get(key)
        if value is not None:
            ref[key] = value
    return ref or None


async def build_social_turn_frame(*, chat_id, message=None, bundle=None,
                                  window=None, opportunity=None,
                                  relations=None,
                                  relation_skip_user_id=None
                                  ) -> SocialTurnFrame:
    """Собрать `SocialTurnFrame` из УЖЕ загруженных данных. Никогда не бросает.

    `message` — aiogram-сообщение (нативный reply/quote), `bundle` —
    существующий MCA-22 EvidenceBundle, `window` — окно чата,
    `opportunity` — строка существующего повода инициативы
    (`addressee_user_id`/`rationale`), `relations` — существующий
    RelationsService (только для `relation_ref`), `relation_skip_user_id` —
    пользователь, чья карточка уже подана существующим блоком
    `<user_relations>` (повторное чтение не нужно).
    """
    frame = empty_frame(chat_id)
    if not feature_enabled():
        return frame
    try:
        return await _build(frame.chat_id, message=message, bundle=bundle,
                            window=window, opportunity=opportunity,
                            relations=relations,
                            relation_skip_user_id=relation_skip_user_id)
    except Exception:
        logger.warning("[social] frame build failed — empty frame",
                       exc_info=True)
        return frame


async def _build(chat_id: int, *, message, bundle, window, opportunity,
                 relations, relation_skip_user_id) -> SocialTurnFrame:
    trigger_id = _as_int(getattr(message, "message_id", None))
    speaker = _as_int(getattr(getattr(message, "from_user", None), "id", None))
    if speaker is None:
        # bundle.author — Telegram ID строкой в каноническом пути; в legacy-
        # паритете это display-name → _as_int вернёт None (честный unknown).
        speaker = _as_int(getattr(bundle, "author", None))

    reply = getattr(message, "reply_to_message", None)
    reply_message_id = _as_int(getattr(reply, "message_id", None))
    reply_author = _as_int(
        getattr(getattr(reply, "from_user", None), "id", None))

    quote_span = _clean_quote(getattr(getattr(message, "quote", None), "text",
                                      None))
    bundle_reply_addressee = _as_int(getattr(bundle, "reply_addressee", None))
    bundle_quoted = _as_int(getattr(bundle, "quoted_speaker", None))
    try:
        ambiguities = tuple(getattr(bundle, "ambiguities", ()) or ())
    except Exception:                                   # pragma: no cover
        ambiguities = ()
    quote_ambiguous = any(str(item).startswith(_AMBIGUITY_QUOTE_PREFIX)
                          for item in ambiguities)

    # ── адресат: native reply → канонический reply-адресат → автор цитаты ──
    addressed_user = None
    if reply_author is not None:
        addressed_user = reply_author
    elif bundle_reply_addressee is not None:
        addressed_user = bundle_reply_addressee
    elif quote_span is not None and bundle_quoted is not None:
        addressed_user = bundle_quoted
    elif opportunity is not None:
        # Инициатива без trigger-сообщения: явный адресат существующего
        # повода (директива §2.1 — ссылка на opportunity вместо выдуманного
        # идентификатора).
        addressed_user = _as_int(_row_get(opportunity, "addressee_user_id"))

    # ── автор цитаты: отдельный слот (третье лицо не становится адресатом) ──
    quote_author = None
    if quote_span is not None:
        if bundle_quoted is not None:
            quote_author = bundle_quoted
        elif reply_author is not None:
            quote_author = reply_author

    if addressed_user is not None:
        attribution = ATTRIBUTION_RESOLVED
    elif (reply_message_id is not None or quote_span is not None
          or bundle_reply_addressee is not None or bundle_quoted is not None
          or quote_ambiguous):
        attribution = ATTRIBUTION_AMBIGUOUS
    else:
        attribution = ATTRIBUTION_UNKNOWN

    context_refs = _refs_from_branch(getattr(bundle, "branch", ()))
    if not context_refs and message is None:
        # Инициативный повод без trigger-сообщения: ссылка на реальные ID
        # уже загруженного окна (директива §2.1). Direct-путь окно в кадр не
        # дублирует — там ветка приходит из bundle.branch.
        context_refs = _refs_from_window(window)

    relation_ref = None
    target_user = addressed_user if addressed_user is not None else speaker
    skip_user = _as_int(relation_skip_user_id)
    if (relations is not None and target_user is not None
            and target_user != skip_user):
        try:
            relation = await relations.get_user_relation(chat_id,
                                                         int(target_user))
            relation_ref = relation_ref_from_relation(relation)
        except Exception:
            logger.warning(
                "[social] relations read failed — no relation_ref | "
                "chat=%s", chat_id, exc_info=True)
            relation_ref = None

    return SocialTurnFrame(
        chat_id=int(chat_id),
        trigger_message_id=trigger_id,
        speaker_user_id=speaker,
        addressed_user_id=addressed_user,
        addressed_message_id=reply_message_id,
        quote_author_user_id=quote_author,
        quote_span=quote_span,
        context_refs=context_refs,
        relation_ref=relation_ref,
        attribution_status=attribution)


def _addressing_line(frame) -> str:
    """Короткая источниковая строка: адресат/ветка/цитата (только факты)."""
    parts: list[str] = []
    if frame.addressed_user_id is not None:
        parts.append(f"адресат [user:{frame.addressed_user_id}]")
    if frame.addressed_message_id is not None:
        parts.append(f"reply на [msg:{frame.addressed_message_id}]")
    if frame.quote_author_user_id is not None:
        parts.append(f"автор цитаты [user:{frame.quote_author_user_id}]")
    if frame.quote_span:
        parts.append(f"цитата: «{frame.quote_span}»")
    if frame.context_refs:
        parts.append("ветка: " + ", ".join(f"[msg:{ref}]"
                                           for ref in frame.context_refs))
    return "; ".join(parts)


def render_context_lines(frame) -> str:
    """Кадр → строка данных для компактного контекста L1 (не инструкция).

    Пустая строка при отсутствии адресации → прежний payload байт-в-байт
    (обычная реплика без reply/цитаты ничего не добавляет)."""
    try:
        if frame is None:
            return ""
        line = _addressing_line(frame)
        if frame.attribution_status == ATTRIBUTION_AMBIGUOUS:
            line = f"{line}; адресация неоднозначна" if line \
                else "адресация неоднозначна"
        if not line:
            return ""
        return f"кадр хода: {line}"
    except Exception:                                   # pragma: no cover
        return ""


def render_writer_hint(frame) -> str:
    """Кадр → короткая источниковая подсказка Writer'у (данные, не приказ).

    Содержит только адресата/ветку/цитату и статус атрибуции; выбранные
    действие/тон уже несёт существующий план L1/Decision (дубля нет).
    Пустая строка → payload Writer'а не меняется."""
    try:
        if frame is None:
            return ""
        line = _addressing_line(frame)
        if frame.attribution_status == ATTRIBUTION_AMBIGUOUS:
            line = f"{line}; адресация неоднозначна" if line \
                else "адресация неоднозначна"
        if not line:
            return ""
        return f"кадр хода: {line}"[:HINT_MAX_CHARS]
    except Exception:                                   # pragma: no cover
        return ""


__all__ = [
    "GATE_NAME", "ATTRIBUTION_RESOLVED", "ATTRIBUTION_AMBIGUOUS",
    "ATTRIBUTION_UNKNOWN", "ATTRIBUTION_STATUSES", "QUOTE_SPAN_MAX",
    "CONTEXT_REFS_MAX", "HINT_MAX_CHARS", "SocialTurnFrame",
    "feature_enabled", "empty_frame", "build_social_turn_frame",
    "relation_ref_from_relation", "render_context_lines", "render_writer_hint",
]
