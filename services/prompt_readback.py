"""SELF-DIAG-01 D5 — типизированный ресурс `prompt_readback`.

Контракт ТЗ §8 (owner input 2026-11-09, строки 236-261):

* источник истины — СУЩЕСТВУЮЩИЙ реестр промптов (`services.prompt_registry`)
  и его resolver/versioning. Второго хранилища, копии текста в самодиагностике,
  отдельного CRUD и «скрытых подсказок» нет (`SD1-D5-01`);
* запрос — типизированный: `resource_kind=prompt`, `scope=current_chat`,
  `prompt_selector`, `requested_revision=effective|specific`,
  `delivery=reply` (`SD1-D5-02`). Значения полей проверяются сервером;
  неизвестные поля (`user_id`, `chat_id`, `role` и т.п.) отвергаются, поэтому
  аргументы модели не повышают права (`SD1-SEM-10`, ТЗ §7.4);
* текст не проходит через обычную LLM-вербализацию: сервер сам собирает
  сообщения для Telegram, а модели возвращается только машинный статус без
  тела промпта (`SD1-D5-05`, `SD1-D5-12`);
* длинный текст не усекается молча — режется на чанки по границам слов
  (`SD1-D5-06`);
* решения о доступе принимает существующая политика D2
  (`services.diagnostic_policy`, класс `PROMPT_CONTENT`): до чтения содержимого,
  с перепроверкой перед отправкой и структурной очисткой секретов
  (`SD1-D5-07`, `SD1-D5-08`, `SD1-D5-09`);
* отсутствие пользовательского override показывается честно (factory/global
  inherited + версия), чтение не создаёт ревизию (`SD1-D5-10`, `SD1-D5-04`);
* заводская редакция, уже опубликованная в публичном репозитории, помечается
  как публичная, а не как «секрет» (`SD1-D2-16`).

Модуль не знает про aiogram и не отправляет сообщения: он возвращает точный
список сообщений, а транспорт живёт в `handlers/prompt_readback.py`.
"""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping

from services import diagnostic_policy as diag
from services import prompt_registry as pr

logger = logging.getLogger(__name__)

#: Имя типизированного инструмента-ресурса (регистрация — D6).
TOOL_NAME = "prompt_readback"

#: `resource_kind` запроса по контракту ТЗ §8.1.
RESOURCE_KIND_PROMPT = "prompt"
#: Единственный допустимый скоуп: промпт действующего чата.
SCOPE_CURRENT_CHAT = "current_chat"
#: Единственная допустимая доставка: ответ в текущий чат.
DELIVERY_REPLY = "reply"
#: Ревизии, которые можно запросить.
REVISION_EFFECTIVE = "effective"
REVISION_SPECIFIC = "specific"

#: Машинные статусы результата (без тела промпта).
STATUS_DELIVERED = "delivered"
STATUS_DENIED = "denied"
STATUS_UNVERIFIED = "unverified"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"
STATUS_REVISION_UNAVAILABLE = "revision_unavailable"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_BLOCKED = "blocked"
STATUS_UNAVAILABLE = "unavailable"
#: Частичная доставка: сообщения ушли не все — не выдаётся за успех.
STATUS_PARTIAL = "partial"

#: Источник действующего значения (контракт §8.1).
SOURCE_CHAT_OVERRIDE = "chat_override"
SOURCE_GLOBAL_INHERITED = "global_inherited"
SOURCE_FACTORY = "factory_default"
SOURCE_MISSING = "missing"

#: Классификация раскрытия (`SD1-D2-16`).
CLASS_ACTIVE_VALUE = "active_value"
CLASS_FACTORY_PUBLIC = "factory_public"

#: Лимит одного Telegram-сообщения (plain text).
TELEGRAM_TEXT_LIMIT = 4096
#: Сколько кандидатов показывать в единственном уточняющем вопросе.
MAX_QUESTION_CANDIDATES = 5

#: Разделитель «метаданные / тело» в собранном сообщении. Гарантия точности:
#: тело — всё, что идёт после первого разделителя, байт в байт.
BODY_SEPARATOR = "\n---\n"

#: Метка машинного результата (не содержит текста промпта).
ACK_PREFIX = "@@PROMPT_READBACK v1"

UNVERIFIED_HINT = (
    "Повторите запрос позже или откройте промпт в подтверждённом интерфейсе "
    "админки."
)

_ALLOWED_FIELDS: frozenset[str] = frozenset({
    "resource_kind", "scope", "prompt_selector", "requested_revision",
    "revision", "delivery",
})

_SOURCE_LABELS: dict[str, str] = {
    SOURCE_CHAT_OVERRIDE: "Chat Override",
    SOURCE_GLOBAL_INHERITED: "Global Custom",
    SOURCE_FACTORY: "Factory",
}

_REGISTRY_SOURCE_TO_LABEL: dict[str, str] = {
    "chat": SOURCE_CHAT_OVERRIDE,
    "global": SOURCE_GLOBAL_INHERITED,
    "default": SOURCE_FACTORY,
    "code": SOURCE_FACTORY,
    "missing": SOURCE_MISSING,
}


# ── Типизированный запрос ──────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class PromptReadbackRequest:
    """Проверенный запрос на чтение действующего промпта."""

    selector: str
    requested_revision: str
    revision: str
    scope: str
    delivery: str


def _text_field(arguments: Mapping, name: str) -> str:
    value = arguments.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return value.strip()


def parse_request(arguments) -> tuple[PromptReadbackRequest | None, str]:
    """Проверить аргументы модели → (запрос, "") | (None, машинная причина).

    Строгая типизация: неизвестные поля отвергаются (`SD1-SEM-10`), поэтому
    `user_id`/`chat_id`/`role` в аргументах не могут подменить principal.
    """
    if not isinstance(arguments, Mapping):
        return None, "arguments_not_an_object"
    unknown = sorted(str(key) for key in arguments if key not in _ALLOWED_FIELDS)
    if unknown:
        return None, "unknown_field:" + ",".join(unknown)

    kind = _text_field(arguments, "resource_kind")
    if kind != RESOURCE_KIND_PROMPT:
        return None, "resource_kind_not_prompt"

    scope = _text_field(arguments, "scope") or SCOPE_CURRENT_CHAT
    if scope != SCOPE_CURRENT_CHAT:
        return None, "scope_not_current_chat"

    delivery = _text_field(arguments, "delivery") or DELIVERY_REPLY
    if delivery != DELIVERY_REPLY:
        return None, "delivery_not_reply"

    requested = _text_field(arguments, "requested_revision") or REVISION_EFFECTIVE
    if requested not in (REVISION_EFFECTIVE, REVISION_SPECIFIC):
        return None, "requested_revision_invalid"

    revision = _text_field(arguments, "revision")
    if requested == REVISION_SPECIFIC and not revision:
        return None, "revision_required"
    if requested == REVISION_EFFECTIVE:
        revision = ""

    return PromptReadbackRequest(
        selector=_text_field(arguments, "prompt_selector"),
        requested_revision=requested,
        revision=revision,
        scope=scope,
        delivery=delivery,
    ), ""


# ── Поиск по существующей библиотеке ───────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class Candidate:
    """Кандидат библиотеки: только метаданные, без текста промпта."""

    block_id: str
    pg_key: str
    purpose: str
    family: str
    editable: bool

    def as_line(self, index: int) -> str:
        purpose = (self.purpose or "").strip()
        if len(purpose) > 90:
            purpose = purpose[:87].rstrip() + "…"
        key = self.pg_key or "—"
        return f"{index}. {self.block_id} (key: {key}) — {purpose}"


def library_rows() -> list[dict]:
    """Непрекращённые блоки существующего реестра (без второго индекса)."""
    try:
        rows = pr.registry_view()
    except Exception:                                  # pragma: no cover
        logger.warning("[prompt-readback] реестр недоступен", exc_info=True)
        return []
    return [row for row in rows if not row.get("retired")]


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _tokens(value: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for ch in str(value or "").lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def _candidate_of(row: dict) -> Candidate:
    return Candidate(
        block_id=str(row.get("block_id") or ""),
        pg_key=str(row.get("pg_key") or ""),
        purpose=str(row.get("purpose") or ""),
        family=str(row.get("family") or ""),
        editable=bool(row.get("pg_key")),
    )


def search_library(selector: str) -> tuple[str, list[Candidate]]:
    """Найти блок по имени в СУЩЕСТВУЮЩЕЙ библиотеке.

    Возвращает `(состояние, кандидаты)`:
      * `exact` — совпал `block_id` или `pg_key`;
      * `match` — ровно один блок по подстроке/токенам;
      * `ambiguous` — несколько блоков: нужен ОДИН уточняющий вопрос;
      * `empty` — не найдено; наугад чужой промпт не выбирается.
    """
    rows = library_rows()
    wanted = str(selector or "").strip()
    wanted_low = wanted.lower()
    if not wanted:
        return "empty", []
    for row in rows:
        if wanted_low == str(row.get("block_id") or "").lower() \
                or wanted_low == str(row.get("pg_key") or "").lower():
            return "exact", [_candidate_of(row)]
    normalized = _norm(wanted)
    tokens = [tok for tok in _tokens(wanted) if len(tok) >= 3]
    if not normalized and not tokens:
        return "empty", []
    hits: list[Candidate] = []
    for row in rows:
        block_id = str(row.get("block_id") or "")
        pg_key = str(row.get("pg_key") or "")
        haystack = " ".join((
            block_id, pg_key, str(row.get("family") or ""),
            str(row.get("purpose") or ""),
            str(row.get("composition_point") or ""),
        )).lower()
        matched = False
        if normalized and normalized in _norm(block_id + " " + pg_key):
            matched = True
        elif wanted_low in block_id.lower() or (
                pg_key and wanted_low in pg_key.lower()):
            matched = True
        elif tokens and all(tok in haystack for tok in tokens):
            matched = True
        if matched:
            hits.append(_candidate_of(row))
    hits.sort(key=lambda item: item.block_id)
    if len(hits) == 1:
        return "match", hits
    if hits:
        return "ambiguous", hits
    return "empty", []


# ── Действующее значение из существующего resolver ─────────────────────────

@dataclasses.dataclass(frozen=True)
class PromptArtifact:
    """Действующий промпт: точный текст + провенанс, без второй копии."""

    block_id: str
    pg_key: str
    text: str
    source: str                   # chat_override|global_inherited|factory_default
    registry_source: str          # chat|global|default|code
    revision: str                 # act:<sha12> действующего значения
    factory_revision: str         # fac:<sha12>(label)
    differs_from_factory: bool
    editable: bool
    effective_at: str | None
    withheld: bool = False
    withheld_revision: str = ""
    withheld_reason: str = ""
    diagnostics: tuple[str, ...] = ()

    @property
    def classification(self) -> str:
        """Заводская редакция уже публична; активную правку защищает ACL."""
        return (CLASS_FACTORY_PUBLIC if not self.differs_from_factory
                else CLASS_ACTIVE_VALUE)

    @property
    def source_label(self) -> str:
        return _SOURCE_LABELS.get(self.source, self.source)


async def _chat_root(chat_id: int, *, pg=None) -> tuple[dict, bool]:
    """(root chat_params, ok) — `ok=False` ⇔ chat-слой не читается.

    «Нет override» и «слой недоступен» — разные состояния: во втором случае
    выдавать global как действующее значение нельзя (`SD1-D5-04`).
    """
    from services import chat_params
    store = chat_params.get_chat_params_cache()
    if store is not None:
        try:
            root, ok = await store.get_chat_params_checked(int(chat_id))
            return dict(root or {}), bool(ok)
        except Exception:                              # pragma: no cover
            logger.warning("[prompt-readback] chat-слой не читается | chat=%s",
                           chat_id, exc_info=True)
            return {}, False
    if pg is not None:
        try:
            root = await chat_params.get_all_chat_params(int(chat_id), pg=pg)
            return dict(root or {}), True
        except Exception:                              # pragma: no cover
            return {}, False
    return {}, False


async def _effective_at(source: str, pg_key: str, chat_id: int,
                        cache=None) -> str | None:
    """Метка «когда значение стало действующим» из существующих источников.

    Chat override → `updated_at` профиля чата; global → `updated_at` ключа
    конфиг-кэша; заводская редакция — времени активации не имеет (None,
    честно, а не выдуманная дата).
    """
    if source == SOURCE_CHAT_OVERRIDE:
        try:
            from services import chat_params
            return await chat_params.get_chat_updated_at(int(chat_id))
        except Exception:                              # pragma: no cover
            return None
    if source == SOURCE_GLOBAL_INHERITED and cache is not None:
        getter = getattr(cache, "get_updated_at", None)
        if callable(getter):
            try:
                return getter(pg_key)
            except Exception:                          # pragma: no cover
                return None
    return None


async def load_artifact(block_id: str, chat_id: int, *, cache=None,
                        pg=None) -> PromptArtifact | None:
    """Собрать действующее значение ЧЕРЕЗ существующий resolver реестра.

    `None` — chat-слой недоступен (эффективное значение неизвестно) либо блок
    не зарегистрирован. Никаких записей не выполняется: чтение ревизию не
    создаёт (`SD1-D5-10`).
    """
    spec = pr.block(block_id) if block_id else None
    if spec is None:
        return None
    root, ok = await _chat_root(int(chat_id), pg=pg)
    if not ok:
        return None
    pg_value = None
    chat_value = None
    if spec.pg_key:
        overrides = root.get("overrides") or {}
        if spec.pg_key in overrides:
            chat_value = overrides.get(spec.pg_key)
        if cache is not None:
            try:
                pg_value = cache.get(spec.pg_key, None)
            except Exception:                          # pragma: no cover
                return None
    effective = pr.effective_prompt(spec.block_id, pg_value=pg_value,
                                     chat_value=chat_value)
    source = _REGISTRY_SOURCE_TO_LABEL.get(effective.source, SOURCE_MISSING)
    if source == SOURCE_MISSING:
        return None
    text = str(effective.text or "")
    return PromptArtifact(
        block_id=spec.block_id,
        pg_key=spec.pg_key or "",
        text=text,
        source=source,
        registry_source=effective.source,
        revision=effective.revision,
        factory_revision=effective.factory_revision,
        differs_from_factory=bool(effective.differs_from_factory),
        editable=bool(spec.pg_key),
        effective_at=await _effective_at(source, spec.pg_key or "", chat_id,
                                         cache),
        withheld=bool(effective.withheld),
        withheld_revision=effective.withheld_revision,
        withheld_reason=effective.withheld_reason,
        diagnostics=tuple(effective.diagnostics or ()),
    )


def _split_rev(value: str) -> tuple[str, str]:
    """`act:<sha12>` / `fac:<sha12>(label)` / `<sha12>` → (префикс, sha)."""
    text = str(value or "").strip()
    prefix, sep, rest = text.partition(":")
    if sep and prefix in ("act", "fac"):
        return prefix, rest.split("(", 1)[0]
    return "", text.split("(", 1)[0]


def _rev_matches(requested: str, known: str) -> bool:
    """Сравнить запрошенную ревизию с идентификатором реестра.

    Принимаются полный вид (`act:<sha12>`, `fac:<sha12>(label)`), голый
    `<sha12>` и однозначный префикс. Разные префиксы (`act:` vs `fac:`) не
    считаются совпадением.
    """
    if not requested or not known:
        return False
    req_prefix, req_sha = _split_rev(requested)
    known_prefix, known_sha = _split_rev(known)
    if req_prefix and known_prefix and req_prefix != known_prefix:
        return False
    if not req_sha or not known_sha:
        return False
    return req_sha == known_sha or (
        len(req_sha) >= 6 and known_sha.startswith(req_sha))


def _metadata_payload(artifact: PromptArtifact) -> str:
    """Заголовок доставки: метаданные решения, НЕ тело промпта."""
    lines = [
        f"ПРОМПТ: {artifact.block_id}",
        f"Источник: {artifact.source} ({artifact.source_label})",
        f"Ревизия: {artifact.revision or '—'}"
        f" | заводская: {artifact.factory_revision or '—'}",
        f"Действует с: {artifact.effective_at or 'нет метки у источника'}",
        f"Символов: {len(artifact.text)}",
    ]
    if not artifact.editable:
        lines.append("Редактирование: блок только в коде (не PG-редактируемый)")
    if artifact.withheld:
        reason = artifact.withheld_reason or ""
        lines.append(
            "Сохранённая редакция удержана: "
            f"{artifact.withheld_revision or '—'}"
            + (f" ({reason})" if reason else "")
            + "; действует текст выше.")
    if artifact.classification == CLASS_FACTORY_PUBLIC:
        lines.append(
            "Класс: factory_public — заводская редакция опубликована в "
            "публичном репозитории, секретом не считается.")
    else:
        lines.append("Класс: active_value — действующая/сохранённая правка.")
    return "\n".join(lines)


def build_payload(artifact: PromptArtifact) -> str:
    """Заголовок + разделитель + ТОЧНЫЙ текст промпта."""
    return _metadata_payload(artifact) + BODY_SEPARATOR + artifact.text


def payload_body(payload: str) -> str:
    """Тело из собранного payload (байт в байт, без заголовка)."""
    _head, found, body = str(payload).partition(BODY_SEPARATOR)
    return body if found else ""


def split_chunks(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Разрезать текст без потерь: только по границам слов, длинные — жёстко.

    Инвариант: `"".join(split_chunks(t)) == t` и каждый чанк ≤ `limit`
    (`SD1-D5-06`: молчаливое усечение запрещено).
    """
    original = "" if text is None else str(text)
    if not original:
        return []
    if limit <= 0:
        return [original]
    chunks: list[str] = []
    current = ""
    for piece in _tokens_with_space(original):
        if len(piece) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(piece), limit):
                chunks.append(piece[start:start + limit])
            continue
        if current and len(current) + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _tokens_with_space(text: str) -> list[str]:
    """Куски, сохраняющие исходные пробелы (склейка даёт исходный текст)."""
    pieces: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch.isspace():
            buf.append(ch)
            pieces.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        pieces.append("".join(buf))
    return pieces


def destination_for(chat_id: int | None) -> str:
    """`group` для группового чата, `private` для личного диалога."""
    try:
        return "group" if int(chat_id) < 0 else "private"
    except (TypeError, ValueError):
        return "unknown"


# ── Результат подготовки (ещё без отправки) ────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ReadbackOutcome:
    """Итог подготовки выдачи: сообщения для Telegram + машинный статус."""

    status: str
    reason: str = ""
    messages: tuple[str, ...] = ()
    machine: str = ""
    metadata: dict = dataclasses.field(default_factory=dict)
    request_id: str = ""

    @property
    def deliverable(self) -> bool:
        return self.status == STATUS_DELIVERED and bool(self.messages)


def ack_text(*, status: str, destination: str = "", chunks: int | None = None,
             metadata: Mapping | None = None, reason: str = "") -> str:
    """Машинная строка для модели: статус/метаданные, БЕЗ тела промпта."""
    data = dict(metadata or {})
    parts = [ACK_PREFIX, f"status={status}"]
    if reason:
        parts.append(f"reason={reason}")
    if destination:
        parts.append(f"destination={destination}")
    if chunks is not None:
        parts.append(f"chunks={int(chunks)}")
    for key in ("prompt_id", "revision", "source", "chars", "classification",
                "redaction"):
        value = data.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _invalid(reason: str) -> ReadbackOutcome:
    return ReadbackOutcome(
        status=STATUS_INVALID_REQUEST, reason=reason,
        machine=f"ОШИБКА {TOOL_NAME}: {reason}")


def _ambiguous(candidates: list[Candidate], total: int) -> ReadbackOutcome:
    shown = candidates[:MAX_QUESTION_CANDIDATES]
    lines = [candidate.as_line(index)
             for index, candidate in enumerate(shown, 1)]
    machine = (
        f"{ACK_PREFIX} status=ambiguous candidates={len(shown)} of {total} "
        "next=ask_one_question\n"
        + "\n".join(lines)
    )
    return ReadbackOutcome(status=STATUS_AMBIGUOUS, reason="selector_ambiguous",
                           machine=machine,
                           metadata={"candidates": len(shown)})


async def prepare(arguments, *, telegram_id: int | None, chat_id: int | None,
                  cache=None, bot=None, pg=None,
                  secrets=None) -> ReadbackOutcome:
    """Проверить запрос, права и собрать точные сообщения для доставки.

    Защищённый текст читается ТОЛЬКО после `allow` (`SD1-D5-07`), проходит
    перепроверку прав и структурную очистку секретов перед отправкой
    (`diagnostic_policy.publish`, kind="prompt"). Ничего не отправляет.
    """
    request, error = parse_request(arguments)
    if error or request is None:
        return _invalid(error or "invalid_request")

    try:
        gate = await diag.open_gate(
            "prompts", "view", telegram_id=telegram_id, chat_id=chat_id,
            cache=cache, bot=bot, pg=pg, destination="reply")
    except Exception:
        logger.warning("[prompt-readback] политика недоступна | chat=%s",
                       chat_id, exc_info=True)
        denial = diag.policy_unavailable_denial("prompts", "view",
                                               chat_id=chat_id)
        return ReadbackOutcome(
            status=STATUS_DENIED,
            reason=denial.reason_code,
            machine=diag.denial_message(denial, tool_name=TOOL_NAME),
            metadata={"reason_code": denial.reason_code})

    if not gate.decision.allowed:
        status = (STATUS_UNVERIFIED
                  if gate.decision.effect == diag.EFFECT_UNVERIFIED
                  else STATUS_DENIED)
        machine = diag.denial_message(gate.decision, tool_name=TOOL_NAME)
        if status == STATUS_UNVERIFIED:
            machine = f"{machine} {UNVERIFIED_HINT}"
        return ReadbackOutcome(
            status=status,
            reason=gate.decision.reason_code,
            machine=machine,
            metadata={"reason_code": gate.decision.reason_code,
                      "effect": gate.decision.effect},
            request_id=gate.request_id)

    if request.selector:
        state, candidates = search_library(request.selector)
    else:
        # Селектор не назван: выбор промпта не угадывается — один вопрос.
        rows = sorted((_candidate_of(row) for row in library_rows()),
                      key=lambda item: item.block_id)
        state, candidates = ("ambiguous", rows) if rows else ("empty", [])
    if state == "ambiguous":
        return dataclasses.replace(_ambiguous(candidates, len(candidates)),
                                   request_id=gate.request_id)
    if state == "empty":
        return ReadbackOutcome(
            status=STATUS_NOT_FOUND, reason="selector_not_found",
            machine=(f"{ACK_PREFIX} status=not_found "
                     "next=ask_one_question_or_name_the_prompt"),
            request_id=gate.request_id)

    artifact = await load_artifact(candidates[0].block_id, int(chat_id),
                                  cache=cache, pg=pg)
    if artifact is None:
        return ReadbackOutcome(
            status=STATUS_UNAVAILABLE, reason="effective_value_unavailable",
            machine=(f"{ACK_PREFIX} status=unavailable "
                     "reason=effective_value_unavailable"),
            request_id=gate.request_id)

    if request.requested_revision == REVISION_SPECIFIC:
        if _rev_matches(request.revision, artifact.revision):
            pass
        elif _rev_matches(request.revision, artifact.factory_revision):
            try:
                factory_text = pr.factory_text(artifact.block_id)
            except Exception:                          # pragma: no cover
                factory_text = ""
            artifact = dataclasses.replace(
                artifact, text=str(factory_text or ""),
                source=SOURCE_FACTORY, registry_source="code",
                revision=artifact.factory_revision,
                differs_from_factory=False,
                effective_at=None)
        else:
            return ReadbackOutcome(
                status=STATUS_REVISION_UNAVAILABLE,
                reason="revision_not_available",
                machine=(f"{ACK_PREFIX} status=revision_unavailable "
                         "available=effective,factory "
                         "note=version_history_not_exposed"),
                metadata={"prompt_id": artifact.block_id},
                request_id=gate.request_id)

    if not artifact.text.strip():
        return ReadbackOutcome(
            status=STATUS_UNAVAILABLE, reason="empty_effective_value",
            machine=(f"{ACK_PREFIX} status=unavailable "
                     "reason=empty_effective_value"),
            metadata={"prompt_id": artifact.block_id},
            request_id=gate.request_id)

    payload = build_payload(artifact)
    try:
        publication = await diag.publish(gate, payload, cache=cache, bot=bot,
                                         pg=pg, kind="prompt", secrets=secrets)
    except Exception:
        logger.warning("[prompt-readback] публикация недоступна | chat=%s",
                       chat_id, exc_info=True)
        return ReadbackOutcome(
            status=STATUS_BLOCKED, reason="policy_unavailable",
            machine=(f"{ACK_PREFIX} status=blocked reason=policy_unavailable"),
            metadata={"prompt_id": artifact.block_id},
            request_id=gate.request_id)
    if not publication.allowed:
        decision = publication.decision
        if decision.effect != diag.EFFECT_ALLOW:
            # Права отозваны между проверкой и отправкой: текст не уходит,
            # ответ — честный отказ политики (revocation_detected в аудите).
            status = (STATUS_UNVERIFIED
                      if decision.effect == diag.EFFECT_UNVERIFIED
                      else STATUS_DENIED)
            machine = diag.denial_message(decision, tool_name=TOOL_NAME)
            if status == STATUS_UNVERIFIED:
                machine = f"{machine} {UNVERIFIED_HINT}"
            return ReadbackOutcome(
                status=status, reason=decision.reason_code, machine=machine,
                metadata={"prompt_id": artifact.block_id,
                          "reason_code": decision.reason_code},
                request_id=gate.request_id)
        return ReadbackOutcome(
            status=STATUS_BLOCKED,
            reason=publication.redaction.reason,
            machine=(f"{ACK_PREFIX} status=blocked "
                     f"reason={publication.redaction.reason}"),
            metadata={"prompt_id": artifact.block_id,
                      "revision": artifact.revision,
                      "redaction": publication.status},
            request_id=gate.request_id)

    text = publication.text
    messages = split_chunks(text)
    metadata = {
        "request_id": gate.request_id,
        "prompt_id": artifact.block_id,
        "pg_key": artifact.pg_key,
        # Контракт §8.1: `version_id` = идентификатор действующей ревизии.
        "version_id": artifact.revision,
        "revision": artifact.revision,
        "factory_revision": artifact.factory_revision,
        "source": artifact.source,
        "registry_source": artifact.registry_source,
        "effective_at": artifact.effective_at,
        "classification": artifact.classification,
        "withheld": artifact.withheld,
        "chars": len(payload_body(text)),
        "redaction": publication.status,
        "redacted": publication.redaction.redacted,
        "destination": destination_for(chat_id),
        "messages": len(messages),
    }
    return ReadbackOutcome(
        status=STATUS_DELIVERED, reason=publication.redaction.reason,
        messages=tuple(messages),
        metadata=metadata,
        request_id=gate.request_id,
    )
