"""Единая точка принуждения для ТЕКСТА промпта (MOD-ACL-UX-01 M1-C).

Три раунда закрывали разные эндпоинты одного и того же ресурса, потому что у
текста промпта не было владельца доступа: его материализуют
``prompt_registry``/``prompt_composer``/``prompt_release_policy``/
``prompt_factory``, а решение принималось (или забывалось) в каждом
HTTP-обработчике отдельно.

Здесь — механизм, симметричный существующему journal-стражу записи
(``journal_write_scope``/``PromptJournalBypass``):

* ``TextScope`` — неизменяемый снимок решения по чату (какие ключи текста
  можно читать/писать). Живёт в ``ContextVar`` и ставится один раз на запрос
  в ``web.api.deps.get_tma_user``; вне HTTP действует ``SYSTEM``;
* ``guard_view``/``guard_edit``/``guard_manifest`` вызываются ВНУТРИ
  владельцев текста перед отдачей/записью и бросают ``PromptTextDenied``
  (403). Новый эндпоинт, переиспользующий существующий материализатор,
  получает отказ автоматически — перечислять маршруты не нужно.

Правило (какая роль видит ключ) не дублируется: ``build_scope`` берёт
готовый снимок из канонического ``web.api.prompt_access.chat_resources``,
который уже собран на ``services.access``. Этот модуль не импортирует
сервисы на уровне модуля: его импортируют владельцы текста, и циклов быть
не должно.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import logging
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: Префиксы pg-ключей, чей ТЕКСТ — инструкция (ресурс MAC-S10-13).
#: ``content.*`` (сообщения бота), ``message.*``, ``keys.*``, ``limits.*``,
#: ``flags.*`` — не тот ресурс (см. §8 дизайна).
GUARDED_PREFIXES: tuple[str, ...] = ("prompts.", "character.", "style.")

#: Документы-ключи без собственного блока реестра.
GUARDED_DOC_KEYS: tuple[str, ...] = (
    "character.core",
    "character.expression",
    "style.policy",
)


class PromptTextDenied(PermissionError):
    """Текст промпта запрошен в чате, где действующая матрица его не разрешает."""

    http_status = 403

    def __init__(self, pg_key: str | None, *, chat_id: int | None = None,
                 detail: str = "") -> None:
        self.pg_key = pg_key
        self.chat_id = chat_id
        self.detail = detail or (f"нет права на {pg_key}" if pg_key
                                 else "нет доступа к тексту промпта")
        super().__init__(self.detail)


@dataclasses.dataclass(frozen=True)
class TextScope:
    """Снимок решения по тексту промпта на время запроса/операции."""

    kind: str                                   # "system" | "global" | "chat"
    chat_id: int | None = None
    view_keys: frozenset[str] = frozenset()
    edit_keys: frozenset[str] = frozenset()
    degraded: str = ""                          # причина fail-closed


SYSTEM = TextScope(kind="system")
GLOBAL = TextScope(kind="global")

_SCOPE: contextvars.ContextVar[TextScope] = contextvars.ContextVar(
    "prompt_text_scope", default=SYSTEM)


def current() -> TextScope:
    return _SCOPE.get()


def set_scope(scope: TextScope) -> contextvars.Token:
    return _SCOPE.set(scope)


def reset_scope(token: contextvars.Token) -> None:
    try:
        _SCOPE.reset(token)
    except (ValueError, LookupError):          # pragma: no cover — чужой токен
        _SCOPE.set(SYSTEM)


@contextlib.contextmanager
def use_scope(scope: TextScope) -> Iterator[TextScope]:
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        reset_scope(token)


@contextlib.contextmanager
def system_scope(reason: str) -> Iterator[None]:
    """Системная сборка текста (бот, CLI, миграции, jobs, тесты).

    Это точное различение «системный потребитель» vs «пользовательское
    чтение»: не по вызывающему, а по входной функции сборки ответа."""
    token = _SCOPE.set(SYSTEM)
    try:
        logger.debug("[prompt_text] system scope | reason=%s", reason)
        yield
    finally:
        reset_scope(token)


def guarded_key(pg_key: str | None) -> bool:
    """True, если текст этого ключа — инструкция (ресурс MAC-S10-13)."""
    if not pg_key:
        return False
    return str(pg_key).startswith(GUARDED_PREFIXES)


def guarded_keys() -> frozenset[str]:
    """Все ключи текста, известные реестру + документы без блока."""
    from services import prompt_registry as pr

    keys = {spec.pg_key for spec in pr.all_blocks()
            if guarded_key(getattr(spec, "pg_key", None))}
    keys.update(GUARDED_DOC_KEYS)
    return frozenset(keys)


def _deny(pg_key: str | None, scope: TextScope, *, edit: bool) -> None:
    detail = (f"нет права на {pg_key}"
              if (pg_key and not edit) else
              (f"нет права на запись {pg_key}" if (pg_key and edit)
               else "нет доступа к тексту промпта"))
    if scope.degraded and not edit:
        detail = ("текст промпта скрыт: права чата недоступны "
                  "(fail-closed)")
    raise PromptTextDenied(pg_key, chat_id=scope.chat_id, detail=detail)


def guard_view(pg_key: str | None) -> None:
    """Разрешить чтение текста ключа или бросить ``PromptTextDenied``.

    Действует только в чатовом скоупе: ``system`` (бот/CLI/тесты) и
    ``global`` (HTTP без X-Chat-Id — задокументированная граница) не меняют
    прежнее поведение."""
    if not guarded_key(pg_key):
        return
    scope = current()
    if scope.kind != "chat":
        return
    if pg_key not in scope.view_keys:
        _deny(pg_key, scope, edit=False)


def guard_edit(pg_key: str | None) -> None:
    """Разрешить запись значения ключа в чате или бросить отказ."""
    if not guarded_key(pg_key):
        return
    scope = current()
    if scope.kind != "chat":
        return
    if pg_key not in scope.edit_keys:
        _deny(pg_key, scope, edit=True)


def guard_manifest(manifest: Any) -> None:
    """Проверить провенанс собранного манифеста по включённым слоям.

    Гейт идёт по ``LayerTrace.block_id`` (а не по списку ключей): новый слой
    композера проверяется сам. Слои без ``pg_key`` (identity/plan/lessons/
    humor-техники) — код-канон без per-chat состояния, вне ресурса."""
    if current().kind != "chat":
        return
    from services import prompt_registry as pr

    for layer in getattr(manifest, "layers", ()) or ():
        if not getattr(layer, "rendered", False):
            continue
        spec = pr.block(str(getattr(layer, "block_id", "") or ""))
        if spec is not None and getattr(spec, "pg_key", None):
            guard_view(spec.pg_key)


async def build_scope(cache, user_id: int, *, chat_id: int | None,
                      ctx: Any = None) -> TextScope:
    """Снимок решения на запрос: ``global`` без чата, иначе — по матрице.

    Сборка правила — существующая (``web.api.prompt_access.chat_resources`` →
    ``services.access``); здесь только раскладка в наборы ключей. Ошибка
    чтения ``chat_params``/``param_permissions`` — fail-closed: текст скрыт
    (``degraded``), а не заменён дефолтной матрицей."""
    if chat_id is None:
        return GLOBAL
    try:
        from web.api import prompt_access

        resources = await prompt_access.chat_resources(
            cache, user_id, int(chat_id), ctx=ctx, strict=True)
    except Exception:
        logger.warning("[prompt_text] scope degraded — fail-closed | "
                       "chat=%s", chat_id, exc_info=True)
        return TextScope(kind="chat", chat_id=int(chat_id),
                         degraded="storage_unavailable")
    keys = guarded_keys()
    return TextScope(
        kind="chat",
        chat_id=int(chat_id),
        view_keys=frozenset(key for key in keys if resources.visible(key)),
        edit_keys=frozenset(key for key in keys if resources.editable(key)),
    )
