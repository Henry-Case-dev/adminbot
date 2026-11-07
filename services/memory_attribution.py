"""MEMORY-05 (C-8 §8) — социальная, эпизодическая и мультимодальная атрибуция.

Слой **представлений** над уже существующими хранилищами (MEM-05.1,
`plans/features/memory-cognitive-02/contracts.md` §8.1): новых таблиц, колонок,
миграций, второго хранилища и второго поиска здесь нет. SQL модуля — только
`SELECT` (проверяется `tests/test_memory_attribution.py`).

Что выводит модуль для каждого запомненного утверждения:

* **кто сказал** (`speaker`/`speaker_user_id`) и **чьи это слова**
  (`content_author`): для пересылки/репоста содержание принадлежит
  первоисточнику, а не переславшему (R-9, §8.2);
* **о ком** (`subject`) — субъект утверждения, без подмены говорящим;
* **кому** (`addressee`): точный `reply_to_id` → существующий
  `thread_chain` target → достоверный alias/uid в chat scope (C-1) →
  ближайший семантический контекст; несколько кандидатов → `ambiguous`,
  получатель не выдумывается (§8.2);
* **модальность** — только из реальных сигналов (`resolve_assertion_mode`),
  иначе `unknown` (§3.3.1); ни смайлик, ни кавычка, ни длина сообщения
  модальность не меняют;
* **событие-источник** (`source_message_id`/`source_ref`).

Собственные сообщения бота (§8.4): `speaker_kind='bot'`, `corroborates=False`,
`independence='self_referential'` — «что я обещал/говорил» помним, внешний факт
не подтверждаем и самоподражание не строим.

Медиа (§8.5): переносится только **фактически выполненная** выжимка со статусом
`processed`; `not_processed`/`unavailable` не выдаются за понимание.
Повторный vision на поиск/просмотр не запускается (читаются durable-строки).

Опыт (§8.6): `experimental` отдельно от `stable`; одно наблюдение (одна
неудача) постоянного правила не создаёт, автоматического повышения в
personality core нет.

Гейт `MCA_MEMORY_ATTRIBUTION_ENABLED` / `flags.memory_attribution_enabled`
(§5.2, default OFF до приёмки): OFF — прежние пути байт-в-байт, новые поля
никем не читаются. Модуль не бросает наружу: ошибки чтения → честный `None`.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable, Mapping

from services import memory_contracts as mc
from services import mca_gates
from services import provenance

logger = logging.getLogger(__name__)

#: Измерение, к которому применяется атрибуция (диагностика/lineage).
ATTRIBUTION_VERSION = "memory-05/c8/v1"

#: Слои памяти и их НАСТОЯЩИЕ таблицы (§8.1). Второго хранилища на слой нет:
#: каждая запись уже существует; `thread_chain` — механизм чтения reply-цепи,
#: а не таблица, поэтому в списке таблиц его нет.
_LAYER_SOURCES: dict[str, tuple[str, ...]] = {
    "operational_context": ("smart_messages",),
    "episodes": ("mca_episodes", "mca_stories", "lore_stories"),
    "stable_knowledge": ("graph_facts", "edges", "mca_source_refs"),
    "social_context": ("users_meta", "persona_dossier_overrides",
                       "mca_dossier_generations"),
    "bot_self_history": ("mca_bot_outputs",),
    "experience": ("mca_lessons", "mca_lesson_applications",
                   "mca_experience_episodes", "mca_experience_feedback"),
}

#: Причины атрибуции (R17: только коды, без текста).
REASON_REPLY_TARGET = "reply_target"
REASON_THREAD_TARGET = "thread_target"
REASON_CHAT_IDENTITY = "chat_identity"
REASON_SEMANTIC_CONTEXT = "semantic_context"
REASON_AMBIGUOUS = "ambiguous_candidates"
REASON_NO_SIGNAL = "no_addressee_signal"
REASON_FORWARD_UNKNOWN = "forward_author_unknown"
REASON_BOT_SELF = "bot_self_statement"
REASON_NO_ROSTER = "no_participant_roster"

#: Границы слова при поиске имени участника в тексте (не «ключевое слово», а
#: адресация по ростeру чата): имя должно стоять отдельным токеном.
_NAME_BOUNDARY = r"(?<![0-9a-zA-Zа-яёА-ЯЁ_]){}(?![0-9a-zA-Zа-яёА-ЯЁ_])"

_ROSTER_HOURS_KEY = "limits.chat_map_participants_hours"
_ROSTER_CAP_KEY = "limits.chat_map_participants_cap"


def layer_sources() -> dict[str, tuple[str, ...]]:
    """Карта «слой → существующие таблицы» (§8.1, MEM-05.1). Копия."""
    return {name: tuple(tables) for name, tables in _LAYER_SOURCES.items()}


async def gate_enabled(chat_id: int | None = None) -> bool:
    """Effective гейт C-8 (§5.2). Никогда не бросает."""
    try:
        return bool(await mca_gates.memory_attribution_enabled(chat_id))
    except Exception:                                     # pragma: no cover
        return False


# ── §8.2: адресат ──────────────────────────────────────────────────────────

def _identity_label(value: Any) -> str | None:
    """Устойчивая метка личности: `user:<uid>` либо уже готовое имя.

    Число — Telegram `user_id`; строка — имя/алиас как есть. Ничего не
    выдумывается: пусто → `None`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"user:{value}" if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        uid = int(text)
        return f"user:{uid}" if uid > 0 else None
    return text[:mc.ENTITY_MENTION_MAX_CHARS]


def _clean_candidates(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values or ():
        label = _identity_label(value)
        if label and label not in out:
            out.append(label)
    return tuple(out)


def resolve_addressee(*, reply_target: Any = None, thread_target: Any = None,
                      chat_candidates: Iterable[Any] = (),
                      semantic_candidates: Iterable[Any] = ()
                      ) -> mc.AddresseeResolution:
    """Адресат по документированному приоритету (§8.2, MEM-05.2).

    Порядок (первое решающее правило выигрывает): точный reply target →
    существующий `thread_chain` target → достоверный alias/uid в chat scope
    (C-1) → ближайший семантический контекст.

    Несколько кандидатов на одном уровне → `ambiguous` с кандидатами и **без**
    получателя: выбор «на глаз» запрещён. Ни одного сигнала → `unknown`:
    в бессвязном чате адресат не выдумывается.
    """
    direct = _identity_label(reply_target)
    if direct is not None:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.RESOLVED, addressee=direct,
            basis=mc.AddresseeBasis.REPLY_TARGET, candidates=(direct,),
            reason_code=REASON_REPLY_TARGET)
    thread = _identity_label(thread_target)
    if thread is not None:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.RESOLVED, addressee=thread,
            basis=mc.AddresseeBasis.THREAD_TARGET, candidates=(thread,),
            reason_code=REASON_THREAD_TARGET)
    chat = _clean_candidates(chat_candidates)
    if len(chat) == 1:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.RESOLVED, addressee=chat[0],
            basis=mc.AddresseeBasis.CHAT_IDENTITY, candidates=chat,
            reason_code=REASON_CHAT_IDENTITY)
    if len(chat) > 1:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.AMBIGUOUS, candidates=chat,
            reason_code=REASON_AMBIGUOUS)
    semantic = _clean_candidates(semantic_candidates)
    if len(semantic) == 1:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.RESOLVED, addressee=semantic[0],
            basis=mc.AddresseeBasis.SEMANTIC_CONTEXT, candidates=semantic,
            reason_code=REASON_SEMANTIC_CONTEXT)
    if len(semantic) > 1:
        return mc.AddresseeResolution(
            status=mc.AddresseeStatus.AMBIGUOUS, candidates=semantic,
            reason_code=REASON_AMBIGUOUS)
    return mc.AddresseeResolution(
        status=mc.AddresseeStatus.UNKNOWN, reason_code=REASON_NO_SIGNAL)


# ── §8.2…§8.4: атрибуция утверждения ───────────────────────────────────────

def attribute_statement(
        *,
        chat_id: int,
        speaker: str | None = None,
        speaker_user_id: int | None = None,
        speaker_kind: mc.SpeakerKind = mc.SpeakerKind.PARTICIPANT,
        subject: str | None = None,
        source_message_id: int | None = None,
        source_ref: str | None = None,
        is_forward: bool = False,
        forward_source: str | None = None,
        forward_author: Any = None,
        forward_author_user_id: int | None = None,
        quoted_author: Any = None,
        quoted: bool = False,
        reply_target: Any = None,
        thread_target: Any = None,
        chat_candidates: Iterable[Any] = (),
        semantic_candidates: Iterable[Any] = (),
        denied: bool = False,
        hypothetical: bool = False,
        joking: bool = False,
        perspective: str | None = None,
        attribution_method: str | None = None,
        provenance_channel: str | None = None,
        origin: str | None = None,
) -> mc.StatementAttribution:
    """Единая атрибуция запомненного утверждения (§8.2…§8.4).

    Все аргументы — **реальные сигналы** существующих полей. Текста сообщения
    здесь нет вовсе: модальность нельзя вывести из кавычек, смайлика или
    длины — только из сигнала (`resolve_assertion_mode`), иначе `unknown`.

    `is_forward`/`forward_source` включают режим пересылки: `content_author`
    заполняется ТОЛЬКО первоисточником; без него — `None` (unknown), никогда
    переславшим.
    """
    forwarded = bool(is_forward) or bool(str(forward_source or "").strip())
    speaker_text = _identity_label(speaker) if speaker is not None else None
    content_author: str | None = None
    content_author_user_id: int | None = None
    reason_parts: list[str] = []
    if forwarded:
        content_author = _identity_label(forward_author)
        if forward_author_user_id is not None:
            content_author_user_id = int(forward_author_user_id)
            if content_author is None:
                content_author = _identity_label(content_author_user_id)
        if content_author is None and content_author_user_id is None:
            reason_parts.append(REASON_FORWARD_UNKNOWN)
    else:
        content_author = speaker_text
        content_author_user_id = (int(speaker_user_id)
                                  if speaker_user_id is not None else None)
    addressee = resolve_addressee(
        reply_target=reply_target, thread_target=thread_target,
        chat_candidates=chat_candidates,
        semantic_candidates=semantic_candidates)
    modality = mc.resolve_assertion_mode(
        forwarded=forwarded,
        forward_from=str(forward_source or ""),
        perspective="quoted" if (quoted and perspective is None) else perspective,
        attribution_method=attribution_method,
        provenance_channel=provenance_channel,
        origin=origin,
        denied=bool(denied),
        hypothetical=bool(hypothetical),
        joking=bool(joking))
    kind = mc.SpeakerKind(speaker_kind)
    corroborates = kind is not mc.SpeakerKind.BOT
    if kind is mc.SpeakerKind.BOT:
        reason_parts.append(REASON_BOT_SELF)
    reason_parts.append(addressee.reason_code or REASON_NO_SIGNAL)
    return mc.StatementAttribution(
        chat_id=int(chat_id),
        speaker_kind=kind,
        modality=modality,
        speaker=speaker_text,
        speaker_user_id=speaker_user_id,
        subject=(str(subject).strip()[:mc.ENTITY_MENTION_MAX_CHARS]
                 if subject is not None and str(subject).strip() else None),
        addressee=addressee.addressee,
        addressee_status=addressee.status,
        addressee_basis=addressee.basis,
        addressee_candidates=addressee.candidates,
        forwarded=forwarded,
        content_author=content_author,
        content_author_user_id=content_author_user_id,
        quoted_author=_identity_label(quoted_author),
        source_message_id=source_message_id,
        source_ref=source_ref,
        corroborates=corroborates,
        reason_code=";".join(dict.fromkeys(reason_parts)))


def _row_get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Поле строки БД (sqlite3.Row/`dict`) без `KeyError` на старых выборках."""
    if row is None:
        return default
    try:
        keys = row.keys() if hasattr(row, "keys") else None
        if keys is not None and key not in keys:
            return default
        return row[key]
    except (KeyError, IndexError, TypeError):              # pragma: no cover
        return default


def attribute_message_row(
        row: Mapping[str, Any] | Any, *,
        chat_id: int | None = None,
        subject: str | None = None,
        reply_target: Any = None,
        thread_target: Any = None,
        chat_candidates: Iterable[Any] = (),
        semantic_candidates: Iterable[Any] = (),
        speaker_kind: mc.SpeakerKind = mc.SpeakerKind.PARTICIPANT,
        origin: str | None = None,
        denied: bool = False,
        hypothetical: bool = False,
        joking: bool = False,
        attribution_method: str | None = None,
        provenance_channel: str | None = None,
) -> mc.StatementAttribution | None:
    """Атрибуция из строки `smart_messages` (роли/time — существующие колонки).

    Строка без чата/без данных → `None` (не выдумываем утверждение).
    """
    if row is None:
        return None
    owner = chat_id if chat_id is not None else _row_get(row, "chat_id")
    if owner is None:
        return None
    tg_id = _row_get(row, "tg_message_id")
    is_forward = bool(_row_get(row, "is_forward"))
    forward_source = str(_row_get(row, "forward_source") or "").strip() or None
    forward_author = _row_get(row, "forward_author_id")
    if forward_author is None and forward_source:
        # Канал/источник репоста — подпись первоисточника, не переславший.
        forward_author = forward_source
    quote_author = _row_get(row, "quote_author_id")
    quoted = (quote_author is not None
              or bool(str(_row_get(row, "quote_text") or "").strip()))
    reply_id = _row_get(row, "reply_to_id")
    reply_author = _row_get(row, "reply_to_author_id")
    if reply_author is None and reply_id is not None:
        # Автор цели reply дочитывается вызывающим (см. `addressee_for_message`).
        reply_author = reply_target
    else:
        reply_author = reply_author if reply_author is not None else reply_target
    return attribute_statement(
        chat_id=int(owner),
        speaker=str(_row_get(row, "author_name") or "").strip() or None,
        speaker_user_id=_row_get(row, "user_id"),
        speaker_kind=speaker_kind,
        subject=subject,
        source_message_id=(int(tg_id) if tg_id is not None else None),
        source_ref=(f"tg:{int(tg_id)}" if tg_id is not None else None),
        is_forward=is_forward,
        forward_source=forward_source,
        forward_author=forward_author,
        forward_author_user_id=_row_get(row, "forward_author_id"),
        quoted_author=quote_author,
        quoted=quoted,
        reply_target=reply_author,
        thread_target=thread_target,
        chat_candidates=chat_candidates,
        semantic_candidates=semantic_candidates,
        denied=denied,
        hypothetical=hypothetical,
        joking=joking,
        origin=origin,
        attribution_method=attribution_method,
        provenance_channel=provenance_channel)


async def message_attribution(
        db, chat_id: int, tg_message_id: int, *,
        subject: str | None = None,
        thread_target: Any = None,
        semantic_candidates: Iterable[Any] = (),
        speaker_kind: mc.SpeakerKind = mc.SpeakerKind.PARTICIPANT,
        origin: str | None = None,
        denied: bool = False,
) -> mc.StatementAttribution | None:
    """Атрибуция сохранённого сообщения по `(chat_id, tg_message_id)`.

    Один `SELECT` (`get_smart_message_by_tg_id`) + (только при наличии
    reply-цели без автора) один добор автора цели. Гейт OFF → `None` (прежние
    пути не меняются). Ошибки чтения → `None` (fail-open, без догадок).
    """
    if not await gate_enabled(chat_id):
        return None
    if db is None or tg_message_id is None:
        return None
    try:
        row = await db.get_smart_message_by_tg_id(int(chat_id),
                                                  int(tg_message_id))
    except Exception:
        logger.warning("[attribution] message read failed | chat=%s | tg=%s",
                       chat_id, tg_message_id, exc_info=True)
        return None
    if row is None:
        return None
    reply_target = None
    reply_id = _row_get(row, "reply_to_id")
    if _row_get(row, "reply_to_author_id") is None and reply_id is not None:
        reply_target = await _reply_target_label(db, int(chat_id), reply_id)
    return attribute_message_row(
        row, chat_id=int(chat_id), subject=subject,
        reply_target=reply_target, thread_target=thread_target,
        semantic_candidates=semantic_candidates, speaker_kind=speaker_kind,
        origin=origin, denied=denied)


async def _reply_target_label(db, chat_id: int, reply_to_id: Any) -> str | None:
    """Автор сообщения-цели reply: `user:<uid>` либо его видимое имя."""
    try:
        target = await db.get_smart_message_by_tg_id(int(chat_id),
                                                    int(reply_to_id))
    except Exception:                                     # pragma: no cover
        return None
    if target is None:
        return None
    uid = _row_get(target, "user_id")
    if uid is not None:
        return _identity_label(uid)
    name = str(_row_get(target, "author_name") or "").strip()
    return name or None


async def chat_identity_candidates(db, *, chat_id: int, text: str | None,
                                   exclude_user_id: int | None = None,
                                   ) -> tuple[str, ...]:
    """Упомянутые участники chat scope → детерминированные кандидаты в адресата.

    Источник — реальные участники чата (`get_active_participants`, тот же
    ростер, что у карты участников) и текущий текст сообщения. Это не словарь
    «вежливых» слов: совпадение — по имени участника отдельным токеном.
    Собственное имя говорящего адресатом не считается. Без ростера → пусто
    (не выдумываем адресата).
    """
    body = str(text or "").strip()
    if db is None or not chat_id or not body:
        return ()
    roster = await _participant_roster(db, int(chat_id))
    if not roster:
        return ()
    found: list[str] = []
    for uid, name in roster:
        if exclude_user_id is not None and uid == int(exclude_user_id):
            continue
        cleaned = str(name or "").strip()
        if len(cleaned) < 2:
            continue
        pattern = _NAME_BOUNDARY.format(re.escape(cleaned))
        if re.search(pattern, body, flags=re.IGNORECASE):
            found.append(cleaned)
    return _clean_candidates(found)


async def _participant_roster(db, chat_id: int) -> list[tuple[int | None, str]]:
    """Ростер чата: `[(user_id, последнее видимое имя)]` (bounded)."""
    from config.settings import settings

    getter = getattr(db, "get_active_participants", None)
    if not callable(getter):
        return []
    try:
        from services import hot_config as hot
        hours = int(hot.get(_ROSTER_HOURS_KEY,
                            settings.CHAT_MAP_PARTICIPANTS_HOURS) or 24)
        cap = int(hot.get(_ROSTER_CAP_KEY,
                          settings.CHAT_MAP_PARTICIPANTS_CAP) or 0) or 150
    except Exception:                                     # pragma: no cover
        hours, cap = 24, 150
    try:
        rows = await getter(int(chat_id),
                            int(time.time()) - int(hours) * 3600, int(cap))
    except Exception:
        logger.debug("[attribution] roster read failed", exc_info=True)
        return []
    out: list[tuple[int | None, str]] = []
    for row in rows or ():
        uid = _row_get(row, "user_id")
        name = str(_row_get(row, "author_name") or "").strip()
        if name:
            out.append((int(uid) if uid is not None else None, name))
    return out


async def addressee_for_message(db, *, chat_id: int, row: Any = None,
                                tg_message_id: int | None = None,
                                thread_target: Any = None,
                                semantic_candidates: Iterable[Any] = ()
                                ) -> mc.AddresseeResolution:
    """Адресат сообщения по реальным связям (§8.2, MEM-05.2).

    1. точный reply target (`reply_to_author_id` либо автор цели reply);
    2. `thread_chain` target, если он передан вызывающим (сама цепь уже
       построена на пути ответа — второй сборки здесь нет);
    3. достоверный alias/uid в chat scope: упомянутые участники,
       разрешённые ровно в одного человека (одноимённые → `ambiguous`);
    4. ближайший семантический контекст, если передан вызывающим.

    Никакого «ближайшего» получателя по догадке: без сигнала — `unknown`.
    """
    if row is None and tg_message_id is not None and db is not None:
        try:
            row = await db.get_smart_message_by_tg_id(int(chat_id),
                                                      int(tg_message_id))
        except Exception:                                 # pragma: no cover
            row = None
    reply_target = None
    reply_author = _row_get(row, "reply_to_author_id")
    if reply_author is None:
        reply_id = _row_get(row, "reply_to_id")
        if reply_id is not None and db is not None:
            reply_target = await _reply_target_label(db, int(chat_id), reply_id)
    else:
        reply_target = _identity_label(reply_author)
    if reply_target is not None:
        return resolve_addressee(reply_target=reply_target)
    if thread_target is not None:
        return resolve_addressee(thread_target=thread_target)
    text = " ".join(str(_row_get(row, key) or "")
                    for key in ("text", "caption")).strip()
    candidates = await chat_identity_candidates(
        db, chat_id=int(chat_id), text=text,
        exclude_user_id=_row_get(row, "user_id"))
    if candidates:
        # Одноимённые участники: резолв по имени даёт ≥2 uid → не выбираем.
        resolved = await _resolve_candidates(db, int(chat_id), candidates)
        if len(resolved) > 1:
            # Неоднозначность показывается именами людей (выбор не делаем).
            return resolve_addressee(chat_candidates=candidates)
        return resolve_addressee(chat_candidates=resolved,
                                 semantic_candidates=semantic_candidates)
    return resolve_addressee(semantic_candidates=semantic_candidates)


async def _resolve_candidates(db, chat_id: int,
                              names: Iterable[str]) -> tuple[str, ...]:
    """Кандидаты, разрешённые в достоверную личность (C-1/`resolve_subject_ref`).

    Имя, которое в чате принадлежит нескольким `user_id`, НЕ превращается в
    адресата: возвращается исходное имя (тогда уровень chat-identity даёт
    `ambiguous`), а не произвольно выбранный человек (§2.2.1(е)).
    """
    resolved: list[str] = []
    for name in names:
        try:
            ref = await provenance.resolve_subject_ref(db, int(chat_id), name)
        except Exception:                                 # pragma: no cover
            ref = None
        if ref is not None and getattr(ref, "resolution", None) == "resolved":
            label = _identity_label(getattr(ref, "entity_id", None))
            if label:
                resolved.append(label)
                continue
        resolved.append(name)
    return _clean_candidates(resolved)


# ── §8.5: медиа ────────────────────────────────────────────────────────────

#: Durable-статус анализа (`mca_media_analyses.status`) → контракт §8.5.
_ANALYSIS_STATUS = {
    "ready": (mc.MediaVisionStatus.PROCESSED, "analysis_ready"),
    "no_text": (mc.MediaVisionStatus.PROCESSED, "analysis_no_text"),
    "pending": (mc.MediaVisionStatus.NOT_PROCESSED, "analysis_pending"),
    "running": (mc.MediaVisionStatus.NOT_PROCESSED, "analysis_pending"),
    "failed": (mc.MediaVisionStatus.UNAVAILABLE, "analysis_failed"),
    "unreadable": (mc.MediaVisionStatus.UNAVAILABLE, "analysis_unreadable"),
    "unsupported": (mc.MediaVisionStatus.UNAVAILABLE, "analysis_unsupported"),
    "unavailable": (mc.MediaVisionStatus.UNAVAILABLE, "vision_unavailable"),
}


def media_vision_status(status: Any
                        ) -> tuple[mc.MediaVisionStatus, str]:
    """Статус выжимки медиа из реального исхода анализа (§8.5, MEM-05.5).

    Неизвестный/отсутствующий статус → `not_processed` (понимания не было),
    а не «processed по умолчанию».
    """
    key = str(status or "").strip().lower()
    if not key:
        return (mc.MediaVisionStatus.NOT_PROCESSED, "analysis_missing")
    return _ANALYSIS_STATUS.get(
        key, (mc.MediaVisionStatus.NOT_PROCESSED, "analysis_missing"))


# ── §8.6: опыт ─────────────────────────────────────────────────────────────

#: Источники доказательства, которые являются инструкцией, а не статистикой
#: («перестань так писать» — прямое указание, а не вывод из одной неудачи).
_INSTRUCTION_KINDS = frozenset({"explicit_preference", "humor_instruction"})


def experience_stability(
        *,
        lesson_type: str | None,
        status: str | None,
        validation_kind: str | None = None,
        permission_granted: bool = False,
        error_reproduced: bool = False,
        control_example_succeeded: bool = False,
        independent_outcomes: int = 0,
        required_outcomes: int | None = None,
) -> mc.ExperienceVerdict:
    """`experimental` vs `stable` для вывода опыта (§8.6, MEM-05.7).

    `stable` требует доказанной базы:
    * прямое указание (явное предпочтение/инструкция с правами) — это не
      статистический вывод, поэтому достаточно самого указания;
    * проверенный технический фикс — воспроизведённая ошибка + успешный
      контроль;
    * обобщение/паттерн — не меньше `required_outcomes` НЕЗАВИСИМЫХ исходов
      (`MCA_LESSON_MIN_INDEPENDENT_EPISODES`, default 3).

    Одна неудача постоянным правилом не становится: при одном исходе функция
    возвращает `experimental`, и сконструировать `stable` нельзя (инвариант
    `ExperienceVerdict`).
    """
    need = (int(required_outcomes)
            if required_outcomes is not None
            else int(mca_gates.lesson_min_independent_episodes()))
    need = max(1, need)
    outcomes = max(0, int(independent_outcomes))
    current = str(status or "").strip().lower()
    if current not in ("validated", "active"):
        return mc.ExperienceVerdict(
            stability=mc.ExperienceStability.EXPERIMENTAL,
            reason_code=(f"status_{current}" if current else "status_unknown"),
            independent_outcomes=outcomes, required_outcomes=need)
    kind = str(validation_kind or "").strip().lower()
    if kind in _INSTRUCTION_KINDS and permission_granted:
        return mc.ExperienceVerdict(
            stability=mc.ExperienceStability.STABLE,
            reason_code="explicit_instruction",
            basis="explicit_instruction",
            independent_outcomes=outcomes, required_outcomes=need)
    if kind == "technical_fix" and error_reproduced \
            and control_example_succeeded:
        return mc.ExperienceVerdict(
            stability=mc.ExperienceStability.STABLE,
            reason_code="verified_technical_fix",
            basis="verified_technical_fix",
            independent_outcomes=outcomes, required_outcomes=need)
    if outcomes >= need:
        return mc.ExperienceVerdict(
            stability=mc.ExperienceStability.STABLE,
            reason_code="independent_outcomes",
            basis="independent_outcomes",
            independent_outcomes=outcomes, required_outcomes=need)
    return mc.ExperienceVerdict(
        stability=mc.ExperienceStability.EXPERIMENTAL,
        reason_code="insufficient_independent_outcomes",
        independent_outcomes=outcomes, required_outcomes=need)


def lesson_stability(lesson: Mapping[str, Any] | Any, *,
                     independent_outcomes: int | None = None,
                     validation_kind: str | None = None,
                     permission_granted: bool = False,
                     error_reproduced: bool = False,
                     control_example_succeeded: bool = False
                     ) -> mc.ExperienceVerdict:
    """Стабильность урока `mca_experience` из реальной строки (§8.6).

    Без явного числа независимых исходов берутся только ДОКАЗАННЫЕ исходы
    (`counters_success`) — «неизвестно» не считается стабильностью.
    """
    if independent_outcomes is None:
        try:
            independent_outcomes = int(_row_get(lesson, "counters_success") or 0)
        except (TypeError, ValueError):                   # pragma: no cover
            independent_outcomes = 0
    return experience_stability(
        lesson_type=_row_get(lesson, "type"),
        status=_row_get(lesson, "status"),
        validation_kind=validation_kind,
        permission_granted=permission_granted,
        error_reproduced=error_reproduced,
        control_example_succeeded=control_example_succeeded,
        independent_outcomes=independent_outcomes)


def independence_for(statement: mc.StatementAttribution) -> str:
    """Независимость основания для `mca_evidence_links` (§8.4, R-3).

    Собственный вывод бота — `self_referential`: «что я говорил/обещал»
    помним, внешний факт им не подтверждается.
    """
    if statement.speaker_kind is mc.SpeakerKind.BOT or not statement.corroborates:
        return "self_referential"
    return "independent"
