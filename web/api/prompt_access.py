"""Единое решение доступа к ресурсу промпта (MOD-ACL-UX-01 M1-C).

Правило одно и живёт не здесь: сборка действующей матрицы —
``services.access.chat_param_matrix``, сравнение — ``can_view_param`` /
``can_edit_param``, скрытость ключа — каталог параметров. Этот модуль только
склеивает «актор + scope + ключ» в одно решение, чтобы у ``/api/prompts/*``,
``/api/speech/*`` и ``GET /api/config`` не появлялось второго разбора матрицы
и ручных сравнений.

HTTP-исключений модуль не бросает: API-слой переводит отказ в 403 со своими
существующими формулировками (у промпт-маршрутов — ``нет права на <key>``).

Паритет с ``GET /api/config``: ключи ТЕКСТА промпта решает ресурсная
матрица в обоих скоупах — в чатовом (``chat_resources``) и в глобальном
(``global_resources``: дефолт ⊕ DB-override, чатовых перекрытий нет).
Историю промпта глобально дополнительно закрывает ``decide``.
``resource_access`` — поверхность текста (``/api/speech/*``) — в глобальном
скоупе сохраняет прежнюю границу (сужает только hidden-ключи); это не
видимость значения в ``/api/config``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services import access as access_srv
from services import chat_params
from services import roles as roles_srv
from services.param_catalog import get_by_pg_key
from web.api.deps import can_edit_param, user_is_global_admin

ROLE_LOCAL_ADMIN = "local_admin"
ROLE_MODERATOR = "moderator"


def is_hidden_key(pg_key: str | None) -> bool:
    """Скрытость ресурса — свойство каталога параметров, не реестра."""
    if not pg_key:
        return False
    cat = get_by_pg_key(pg_key)
    return bool(cat is not None and getattr(cat, "hidden", False))


@dataclass(frozen=True)
class Access:
    """Решение по одному ключу: можно ли смотреть/писать и текст отказа."""

    view: bool
    edit: bool
    detail: str = ""
    ctx: Any = None


@dataclass
class ChatResources:
    """Входы матрицы чата, прочитанные ОДИН раз на запрос.

    Для списков (``/api/speech/blocks``) матрица считается по каждому ключу
    без повторного I/O; для одиночных запросов — один вызов ``view/edit``.
    """

    ctx: Any
    db_overrides: dict
    chat_root: dict
    global_admin: bool

    def matrix(self, pg_key: str | None) -> dict:
        return access_srv.chat_param_matrix(pg_key, self.db_overrides,
                                            self.chat_root)

    def visible(self, pg_key: str | None) -> bool:
        if is_hidden_key(pg_key) and not self.global_admin:
            return False
        return bool(access_srv.can_view_param(self.ctx, self.matrix(pg_key)))

    def editable(self, pg_key: str | None) -> bool:
        if is_hidden_key(pg_key) and not self.global_admin:
            return False
        return bool(access_srv.can_edit_param(self.ctx, self.matrix(pg_key)))


async def chat_resources(cache, user_id: int, chat_id: int, *,
                         ctx: Any = None,
                         strict: bool = False) -> ChatResources:
    """Контекст актора в чате + входы матрицы.

    ``ctx`` можно передать уже разрешённым (``/api/speech/*`` получает его из
    своего access-пути) — тогда повторного чтения ролей нет.

    ``strict=False`` (HTTP-поверхности) — прежний fail-open на ошибке чтения
    входов: бот/UI живут, решение считается по дефолтной матрице.
    ``strict=True`` (``services.prompt_text.build_scope``) — ошибка чтения
    пробрасывается: снимок прав не подменяется дефолтом (fail-closed)."""
    if ctx is None:
        ctx = await roles_srv.access_for(user_id, chat_id, cache=cache)
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:                       # pragma: no cover — fail-open
        if strict:
            raise
        db_overrides = {}
    try:
        chat_root = await chat_params.get_all_chat_params(chat_id)
    except Exception:                       # pragma: no cover — fail-open
        if strict:
            raise
        chat_root = {}
    return ChatResources(ctx=ctx, db_overrides=db_overrides,
                         chat_root=chat_root,
                         global_admin=bool(getattr(ctx, "is_global_admin",
                                                   False)))


def global_resources(ctx: Any, db_overrides: dict | None = None) -> ChatResources:
    """Входы ресурсной матрицы ГЛОБАЛЬНОГО скоупа (HTTP без X-Chat-Id).

    Чатовых перекрытий здесь нет по определению запроса, поэтому сборка —
    та же ``chat_param_matrix(key, db_overrides, {})``: дефолт ⊕ DB-override.
    Возвращаем тот же ``ChatResources``, чтобы потребитель (``GET /api/config``
    без чата) спрашивал ``visible(key)``, а не разбирал матрицу сам: одно
    правило (hidden → только глобальный админ, иначе ``can_view_param``).

    Второго правила не появляется: ``/api/config`` в чатовом скоупе решает
    ``chat_resources(...).visible``, в глобальном — ``global_resources`` с тем
    же ``visible``. Отличается только отсутствие ``perm_overrides`` чата.
    """
    return ChatResources(
        ctx=ctx,
        db_overrides=dict(db_overrides or {}),
        chat_root={},
        global_admin=bool(getattr(ctx, "is_global_admin", False)),
    )


def _is_admin(cache, user_id: int, ctx: Any) -> bool:
    if ctx is not None:
        return bool(getattr(ctx, "is_global_admin", False))
    return bool(user_is_global_admin(cache, user_id))


async def resource_access(cache, user_id: int, pg_key: str | None,
                          chat_id: int | None, *,
                          ctx: Any = None) -> Access:
    """Решение для поверхности, отдающей ТЕКСТ ресурса (не историю).

    * hidden-ключ — только глобальный админ (паритет с реестром/каталогом);
    * чатовый скоуп — действующая матрица (``can_view_param``/``can_edit_param``),
      ровно как значение в ``GET /api/config``;
    * глобальный скоуп — граница поверхности ТЕКСТА (``/api/speech/*``): не
      сужаем, кроме hidden-ключей. Значение в ``GET /api/config`` глобально
      решает ``global_resources.visible`` (ресурсная матрица без чатовых
      перекрытий); это разные поверхности одного ресурса.
    """
    if is_hidden_key(pg_key) and not _is_admin(cache, user_id, ctx):
        return Access(False, False, detail="нет доступа к этому промпту")
    if chat_id is None:
        return Access(True, True)
    res = await chat_resources(cache, user_id, chat_id, ctx=ctx)
    detail = f"нет права на {pg_key}" if pg_key else "нет доступа"
    return Access(res.visible(pg_key), res.editable(pg_key), detail=detail,
                  ctx=res.ctx)


async def decide(cache, user_id: int, pg_key: str | None,
                 chat_id: int | None) -> Access:
    """Полное правило истории промпта (``/api/prompts/*``).

    hidden → глобальный админ; global → админ или явное право на ключ;
    chat → доступ к чату + грант чата + действующая матрица.
    """
    if is_hidden_key(pg_key) and not user_is_global_admin(cache, user_id):
        return Access(False, False, detail="нет доступа к этому промпту")
    if chat_id is None:
        admin = bool(user_is_global_admin(cache, user_id))
        edit = bool(pg_key) and bool(can_edit_param(cache, user_id, pg_key))
        view = admin or edit
        return Access(view, edit,
                      detail="" if view else "нет права на историю промпта")
    res = await chat_resources(cache, user_id, chat_id)
    if not access_srv.can_access_chat(res.ctx, chat_id):
        return Access(False, False, detail="нет доступа к чату", ctx=res.ctx)
    # Изоляция чатов: глобальный модератор без гранта на ЭТОТ чат не читает
    # чужой override. Глобальный админ и владелец своих ЛС — могут.
    if (not res.ctx.is_global_admin and not res.ctx.is_dm_owner
            and res.ctx.role_chat not in (ROLE_LOCAL_ADMIN, ROLE_MODERATOR)):
        return Access(False, False, detail="нет доступа к чату", ctx=res.ctx)
    if not res.visible(pg_key):
        return Access(False, False, detail=f"нет права на {pg_key}",
                      ctx=res.ctx)
    return Access(True, res.editable(pg_key), ctx=res.ctx)
