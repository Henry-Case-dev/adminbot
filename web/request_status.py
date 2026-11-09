"""R17-safe наблюдаемость: ОДНА строка на каждый non-2xx ответ под `/api/*`.

Зачем (реальный инцидент): uvicorn в проде запускается с
`log_level="warning"` (bot.py), а Caddy не пишет access-log. Поэтому отказ
(4xx) на запрос Mini App невозможно привязать к пути/статусу/пользователю:
в журнале были только успешные `[tma-auth]`-трейсы и 401, ни одного 403 и ни
одного пути. Диагноз «какой именно запрос получил отказ» был недоказуем.

Контракт (минимальный патч, без включения полного access-log uvicorn):
  * логируются ТОЛЬКО пути под `/api` и ТОЛЬКО не-2xx ответы;
  * 2xx — ноль работы: ни строки, ни форматирования, ни сериализации;
  * поля ровно такие: method, path (шаблон маршрута — без query string),
    status, user (telegram_id, если запрос был аутентифицирован, иначе `-`),
    reason (короткий код из allowlist) либо exc (только имя класса для 5xx);
  * НИКОГДА не логируются: initData, заголовки, cookie, тела запросов,
    токены, полные payload'ы пользователя и query string (жёсткое
    требование проекта — секреты не утекают ни в журнал, ни владельцу);
  * middleware не зависит от того, отработала ли auth-зависимость: если её
    не было, `user=-`.

ГРАНИЦА НАБЛЮДАЕМОСТИ (важно для чтения журнала, а не для кода):
  * middleware видит ТОЛЬКО ASGI-запросы: только HTTP-запросы под `/api/*`,
    которые дошли до приложения;
  * отказ, целиком произведённый на клиенте (до любого запроса — например,
    UI-гейт маршрута в браузере, скрытая кнопка, локальная проверка прав),
    НЕ порождает строки, потому что запроса не было;
  * поэтому ОТСУТСТВИЕ строки НЕ доказывает отсутствие отказа. Отсутствие
    строки означает только, что этот запрос не дошёл до данного ASGI
    middleware/приложения: он мог не быть отправлен, быть остановлен
    клиентом или завершиться на прокси/серверном слое до middleware.
    Обратное верно всегда: строка есть ⇒ middleware видел запрос и ответил
    указанным статусом;
  * в строку попадают только allowlisted-поля (method, шаблон path, status,
    user, reason либо exc); текст `HTTPException.detail` и сообщение
    исключения НИКОГДА не пишутся — только имя класса для 5xx.

Префикс прокси: Mini App вызывает `/api/...` от корня; Starlette кладёт
внешний путь в `scope["path"]` (root_path выносится отдельно), поэтому
матчинг по `scope["path"]` работает и без префикса, и при `root_path`.
"""
import logging
import re

logger = logging.getLogger("web.request_status")

_API_PREFIX = "/api"
_MAX_PATH_LEN = 200

# Deterministic allowlist коротких reason-кодов (ставятся в web/api/deps.py).
# Всё, чего нет в allowlist, в строку не попадает — защита от случайной
# утечки текста detail (в проекте есть HTTPException(detail={...})).
_REASON_ALLOWLIST = frozenset({
    "missing_init_data",
    "invalid_init_data",
    "no_user_in_init_data",
    "init_data_expired",
    "permission_denied",
    "not_global_admin",
})

# Path: только безопасный алфавит (шаблоны маршрутов — ASCII; цифры/буквы
# сохраняются). Символы вне алфавита вырезаются — это исключает log-injection
# (переводы строк) и попадание `?query`/`#fragment` в строку.
_SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9/._~{}<>:-]+")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _is_api_path(path: str) -> bool:
    """`/api` или `/api/...` (без учёта root_path — он вне scope['path'])."""
    return path == _API_PREFIX or path.startswith(_API_PREFIX + "/")


def _route_template(scope) -> str | None:
    """Полный шаблон маршрута (с префиксом include_router), иначе None.

    FastAPI 0.141 включает вложенные роутеры лениво (`_IncludedRouter`):
    `scope["route"].path` у совпавшей APIRoute — БЕЗ префикса include
    (`/avatar/{kind}/{tid}` вместо `/api/avatar/{kind}/{tid}`). Префикс
    восстанавливаем детерминированно по числу сегментов реального пути —
    без обращения к приватным внутренностям FastAPI и без эвристик по
    значениям (конкретные id в строку не попадают).
    """
    route = scope.get("route")
    template = getattr(route, "path", None) if route is not None else None
    if not template:
        return None
    t_parts = [p for p in str(template).split("/") if p]
    a_parts = [p for p in str(scope.get("path") or "").split("/") if p]
    if not t_parts or len(a_parts) < len(t_parts):
        return None
    extra = len(a_parts) - len(t_parts)
    prefix = "".join(f"/{p}" for p in a_parts[:extra])
    return prefix + str(template)


def _safe_path(scope) -> str:
    """Шаблон маршрута (нормализованный путь), иначе — сырой path без query.

    Шаблон (`/api/avatar/{kind}/{tid}`) выбран приоритетно: он стабилен и не
    содержит конкретных id пользователя/чата (нормализация без эвристик).
    """
    raw = _route_template(scope) or scope.get("path") or ""
    cleaned = _SAFE_PATH_RE.sub("", str(raw))[:_MAX_PATH_LEN]
    return cleaned or "-"


def _telegram_id(state) -> str:
    """telegram_id авторизованного запроса; `-` если auth не проходил."""
    value = (state or {}).get("telegram_id")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    return "-"


def _reason(state) -> str:
    value = (state or {}).get("tma_deny_reason")
    if isinstance(value, str) and value in _REASON_ALLOWLIST:
        return value
    return "-"


def _safe_exc_name(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if _SAFE_TOKEN_RE.match(name) else "Exception"


def _emit(scope, status: int, exc: BaseException | None = None) -> None:
    """Единственная точка форматирования строки (никаких секретов)."""
    state = scope.get("state") or {}
    method = str(scope.get("method") or "-")
    path = _safe_path(scope)
    user = _telegram_id(state)
    log = logger.warning if status >= 500 else logger.info
    if exc is not None:
        # 5xx: только тип исключения — трейсбек уже логируется uvicorn'ом,
        # текст исключения может содержать данные/PII (не дублируем).
        log("[api-status] method=%s path=%s status=%s user=%s exc=%s",
            method, path, status, user, _safe_exc_name(exc))
        return
    log("[api-status] method=%s path=%s status=%s user=%s reason=%s",
        method, path, status, user, _reason(state))


class ApiStatusLogMiddleware:
    """ASGI-middleware: одна строка на non-2xx под `/api/*`, ноль на 2xx.

    Чистый ASGI (не BaseHTTPMiddleware) — на здоровом пути стоимость сводится
    к проверке префикса пути и обёртке `send`; логирование/форматирование не
    выполняется вовсе. Исключение логируется типом и пробрасывается дальше
    (поведение приложения не меняется).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not _is_api_path(
                scope.get("path") or ""):
            await self.app(scope, receive, send)
            return
        status: int | None = None

        async def _send(message):
            nonlocal status
            if message.get("type") == "http.response.start":
                status = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:  # noqa: BLE001 — фиксируем 5xx и re-raise
            _emit(scope, 500, exc=exc)
            raise
        if status is None or 200 <= status < 300:
            # Здоровый путь: ни строки, ни дополнительной работы.
            return
        _emit(scope, status)
