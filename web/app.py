"""Epic 85 (84.4/84.7/84.21.2, T-615/T-618/T-661) — FastAPI-приложение TMA-админки.

Фабрика create_app(cache) вызывается из bot.py (один event loop — R2/R3);
app.state.cache — ОБЩИЙ объект ConfigCache для aiogram и FastAPI.
Lifespan: cache.init() при старте (идемпотентно; R6 — PG down не блокирует
бот), на выходе — НИЧЕГО не закрывает (закрытие пула — в bot.py on_shutdown,
ровно один раз).

Статика (84.21.2): CacheControlStaticFiles — для index.html/app.js/.css
`Cache-Control: no-cache` (ре-валидация через ETag при каждом входе — обход
кэша Telegram WebView), остальное — public, max-age=86400. index.html
отдаётся через маршрут /web/ и /web/index.html с подстановкой
__APP_VERSION__ → актуальная версия (только в `?v=` у скриптов — версиони-
рование без хэш-имён). / → /web/.
"""
import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from config.settings import APP_VERSION, settings
from services.config_cache import ConfigCache
from services import media_share

logger = logging.getLogger(__name__)

_VERSION_TAG = "__APP_VERSION__"

# F4 10.16 (ADR-1016-2 §3, T-1653/ревью-итерация 1): CSP для HTML миниаппа.
# `script-src 'self' 'unsafe-eval'` — ВАРИАНТ A ревью: self-host использует
# FULL-сборку Vue (`vue.global.prod.min.js`), чей рантайм-компилятор вызывает
# `Function()` (compileToFunction) при компиляции in-DOM шаблонов (#app,
# `template: '#kv-editor-tpl'`). Без 'unsafe-eval' браузер бросает EvalError
# на монтировании → белый экран (прод-ломающий дефект, выявлен @Reviewer).
# ВАРИАНТ B (runtime-only сборка + предкомпилированные render-функции)
# требовал бы перевода всего in-DOM канона (`index.html` ~2900 строк) в
# `h(...)` — большой риск регрессии фронта; выбран минимально-рискованный A.
# Внешние скрипты по-прежнему запрещены ('self'); 'unsafe-inline' НЕТ —
# все скрипты вынесены в файлы (vendor/*, app.js, telegram-init.js).
# `style-src 'unsafe-inline'` необходим: Vue биндит `:style` (inline
# style-атрибуты) и есть динамические стили — полный отказ вне скоупа.
# `frame-ancestors` — чтобы Telegram Web/WebView мог встроить приложение.
# `connect-src 'self'` — API same-origin.
# CSP применяется только к HTML (web_index), НЕ к /api (initData не ломаем).
_CSP_HTML = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "form-action 'self'"
)

# Раунд 3 (T-687): MIME по расширению опубликованного файла (3.1).
_EXT_MEDIA_TYPES = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
}


class CacheControlStaticFiles(StaticFiles):
    """84.21.2: Cache-Control для веб-файлов (обход кэша WebView + ETag/304).
    Имя файла — из full_path (аргумент супер-метода): на 304 Starlette отдаёт
    NotModifiedResponse ПОСЛЕ супер-вызова с тем же path-аргументом, поэтому
    определяем суффикс ДО/через full_path, а не через resp.path — иначе
    Cache-Control теряется на 304-ответах (ревью-блокер)."""

    _NO_CACHE_SUFFIXES = (".html", ".js", ".css")

    def file_response(self, full_path, stat_result, scope,
                      status_code: int = 200):
        # Определяем суффикс ДО супер-вызова: 304-ответ (NotModifiedResponse)
        # НЕ несёт path — тогда header не попал бы на повторную валидацию.
        suffix = str(full_path).rsplit("/", 1)[-1].lower()
        no_cache = suffix.endswith(self._NO_CACHE_SUFFIXES)
        resp = super().file_response(full_path, stat_result, scope,
                                     status_code)
        resp.headers["Cache-Control"] = (
            "no-cache, no-store, must-revalidate" if no_cache
            else "public, max-age=86400"
        )
        return resp


def _render_index() -> str:
    """index.html с подстановкой __APP_VERSION__ (версионирование `?v=`)."""
    from pathlib import Path
    src = Path(__file__).resolve().parent / "index.html"
    text = src.read_text(encoding="utf-8")
    return text.replace(_VERSION_TAG, APP_VERSION)


def _render_app_css() -> str:
    """F4 10.16: CSS-канон вынесен из inline <style> в web/static/app.css,
    но внутри @font-face остался `?v=__APP_VERSION__` (R10.8-5 cache-bust
    субсета шрифта, max-age=86400). Статика не проходит подстановку — поэтому
    app.css отдаём выделенным маршрутом с той же заменой, что и index.html.

    Ревью-итерация 1 (Low): на чистом клоне без собранного `web/static/app.css`
    create_app НЕ должен падать (как и mount /static) — отдаём пустой CSS."""
    from pathlib import Path
    src = Path(__file__).resolve().parent / "static" / "app.css"
    try:
        text = src.read_text(encoding="utf-8")
    except OSError:
        logger.warning("[webapp] web/static/app.css отсутствует — отдаю пустой "
                       "CSS (сборка не выполнена)")
        return ""
    return text.replace(_VERSION_TAG, APP_VERSION)


def _startup_diag() -> None:
    """10.17 (F1 miniapp-mobile-dns-round1017, T-1670/T-1672): стартовая
    диагностика host/scheme/path для absolute-URL настроек. R17: логируем
    ТОЛЬКО host/scheme/path через `urlsplit` — полный URL и секреты (если
    появятся query/userinfo) в лог не попадают. Помогает при разборе
    `net::ERR_NAME_NOT_RESOLVED` (какой host реально отдаёт прод)."""
    for name in ("WEBAPP_URL", "MEDIA_PUBLIC_BASE_URL"):
        raw = str(getattr(settings, name, "") or "").strip()
        parts = urlsplit(raw)
        logger.info("[webapp] %s | scheme=%s | host=%s | path=%s",
                    name, parts.scheme or "-", parts.hostname or "-",
                    parts.path or "-")


def create_app(cache: ConfigCache, control=None) -> FastAPI:
    """FastAPI-фабрика (84.4): app.state.cache = cache — общий для aiogram+FastAPI.
    control — ControlService (84.15; из bot.py с request_shutdown-колбэком;
    None → дефолт без graceful-exit колбэка — для тестов/стендалон-режима)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not cache.is_initialized:
            await cache.init()
        logger.info("[webapp] lifespan started | pg_available=%s",
                    cache.pg_available)
        yield
        logger.info("[webapp] lifespan finished")

    app = FastAPI(title="AdminBot TMA Dashboard", lifespan=lifespan)
    app.state.cache = cache

    # R10.6-3 (R17): Pydantic v2 RequestValidationError по умолчанию кладёт
    # в `input`/`ctx` сырое значение поля — для /api/llm/test это api_key.
    # Санитизируем 422: отдаём только loc/msg/type, `input`/`ctx` НЕ включаем
    # и не логируем тело запроса.
    @app.exception_handler(RequestValidationError)
    async def _safe_validation_handler(request: Request,
                                       exc: RequestValidationError):
        safe = []
        for err in exc.errors():
            safe.append({
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg", "invalid value"),
                "type": err.get("type", "value_error"),
            })
        logger.warning("[webapp] 422 validation | path=%s | errors=%s",
                       request.url.path,
                       [(e["loc"], e["type"]) for e in safe])
        return JSONResponse(status_code=422, content={"detail": safe})

    if control is None:
        from services.control_service import ControlService
        control = ControlService()
    app.state.control = control

    from web.api.routes import api_router
    app.include_router(api_router, prefix="/api")
    # Раунд 7 (chat-lore-management-v2, T-779, E1): раздел «Лор чатов».
    # Отдельный APIRouter (spec §3.8) — включение рядом с api_router.
    from web.api.chat_lore import chat_lore_router
    app.include_router(chat_lore_router, prefix="/api")
    # Раунд 9 (AGI Memory, spec §3.6.2, T-829/F2): «Сон»/«Ностальгия» API —
    # ручной запуск воркеров + логи (только глобальный admin).
    from web.api.memory_agi import memory_router
    app.include_router(memory_router, prefix="/api")
    # UI-полировка TMA: прокси аватаров (GET /api/avatar/{kind}/{tid}) —
    # bot из services.web_runtime; отдельный router рядом с остальными.
    from web.api.avatars import avatar_router
    app.include_router(avatar_router, prefix="/api")
    # Раунд 10 (F-7 §6, E1): /api/access/* (доступы, гранты, per-param
    # права) — добавка рядом с остальными (существующие сигнатуры
    # web/api/deps.py не меняются).
    # ВАЖНО: включаем с СОБСТВЕННЫМИ префиксами (/api/access, /api/oversight,
    # /api/chat/.., /api/workers/..) — иначе пути перекрывают существующие
    # /api/me и /api/summary routes.py (порядок include после api_router).
    from web.api.access import access_router
    app.include_router(access_router, prefix="/api/access")
    # Раунд 10 (F-10 §7, D3): гейты + воркер-бюджет API (прецедент
    # chat_lore_router — рядом с api_router).
    from web.api.gates import budget_router, gates_router
    app.include_router(gates_router, prefix="/api")
    app.include_router(budget_router, prefix="/api")
    # Раунд 10 (F-12 §4, Q3): Oversight API (только global admin).
    from web.api.oversight import oversight_router
    app.include_router(oversight_router, prefix="/api/oversight")
    # Раунд 10.23 (F4, ADR-1023-4 D6): мониторинг/управление динамическим
    # анти-клише кэшем (только global admin) — рядом с остальными роутерами.
    from web.api.anticliche import anticliche_router
    app.include_router(anticliche_router, prefix="/api")
    # Раунд 10.23 (F7, ADR-1023-7 §2.7): дашборд аналитики токенов
    # (read-side PG; RBAC глобального админа).
    from web.api.analytics import analytics_router
    app.include_router(analytics_router, prefix="/api")

    rendered_index = _render_index()   # один раз at startup (84.21.2)
    rendered_css = _render_app_css()   # F4 10.16: подстановка ?v= в @font-face
    _startup_diag()                    # 10.17 (F1): host/scheme/path (R17)

    # Маршруты html ДО app.mount (mount перехватывает всё /web/*):
    # /web/ и /web/index.html — с подстановкой APP_VERSION в `?v=`.
    @app.get("/web/", include_in_schema=False)
    async def web_index():
        return _html_response(rendered_index)

    @app.get("/web/index.html", include_in_schema=False)
    async def web_index_html():
        return _html_response(rendered_index)

    # 10.17 (F1 miniapp-mobile-dns-round1017, T-1670/T-1672): явные HEAD-роуты
    # для детерминированной внешней диагностики (`curl -I`/проверки из
    # мобильной сети). Контракт: 200 + CSP + no-store, тело пустое (HEAD) —
    # отличаем маршрутизацию от сбоя DNS. Новых данных/секретов нет (R17).
    @app.head("/web/", include_in_schema=False)
    async def web_index_head():
        return _html_response(rendered_index)

    @app.head("/web/index.html", include_in_schema=False)
    async def web_index_html_head():
        return _html_response(rendered_index)

    # F4 10.16: app.css отдаём ДО /static-mount — с подстановкой версии
    # субсета шрифта (R10.8-5) и no-cache, как у прочей CSS-статики.
    from fastapi.responses import Response

    @app.get("/static/app.css", include_in_schema=False)
    async def static_app_css():
        return Response(
            content=rendered_css, media_type="text/css",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/web/")

    # 10.17 (F1 miniapp-mobile-dns-round1017, T-1670/T-1672): unauth health-
    # check — дешёвая точка для `curl -I https://<host>/healthz` из мобильной
    # сети (@DevOps): `Could not resolve host` = DNS-сбой, иначе — TLS/Caddy.
    # Отдаём только status/version (без секретов/персональных данных, R17),
    # no-store. GET и HEAD. В Caddy разрешить `/healthz` (@DevOps, вне репо).
    # L8 (ревью-итер.1): `version` — намеренное info-disclosure по спеке F1
    # (диагностический контракт; APP_VERSION публичен, ключей/PII в ответе нет).
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return JSONResponse({"status": "ok", "version": APP_VERSION},
                            headers={"Cache-Control": "no-store"})

    @app.head("/healthz", include_in_schema=False)
    async def healthz_head():
        # L4 (ревью-итер.1): HEAD повторяет GET-заголовки (в т.ч. content-type
        # application/json); тело Starlette отбрасывает по методу.
        return JSONResponse({"status": "ok", "version": APP_VERSION},
                            headers={"Cache-Control": "no-store"})

    # ── Раунд 3 (T-687): GET /media/{file_id}?e=&s= — подписанная отдача
    # временно опубликованных видео (3.1, FR-B2). БЕЗ TMA-авторизации:
    # безопасность — uuid-имя + HMAC-подпись + TTL (случайный id не
    # перебирается). 403 — битая подпись/просрочка; 404 — нет файла /
    # мусорный id (маска-404 как у /api — traversal невозможен структурно).
    @app.get("/media/{file_id}", include_in_schema=False)
    async def media_file(file_id: str, e: str = "", s: str = ""):
        if not media_share._SHARE_FILE_RE.match(file_id):
            return _media_404()
        try:
            expires = int(e)
        except (TypeError, ValueError):
            return _media_403()
        if int(time.time()) > expires:
            return _media_403()
        if not media_share.verify(file_id, expires, s):
            return _media_403()
        path = media_share._share_dir() / file_id
        if not path.exists():
            return _media_404()
        ext = file_id.rsplit(".", 1)[-1].lower()
        return FileResponse(
            path,
            media_type=_EXT_MEDIA_TYPES.get(ext, "application/octet-stream"),
            headers={"Content-Disposition": f'inline; filename="{file_id}"'},
        )

    app.mount("/web", CacheControlStaticFiles(directory="web"),
              name="web")
    # Редизайн 10.5 (T-1147/§15.4.3): self-host субсета Material Symbols.
    # CSP font-src 'self' — без внешних CDN (LOW-012). Если каталога нет
    # (чистый клон без сборки шрифта) — монтирование пропускается.
    try:
        app.mount("/static", CacheControlStaticFiles(directory="web/static"),
                  name="static")
    except RuntimeError:
        logger.warning("[webapp] web/static отсутствует — /static не смонтирован")

    return app


def _media_404():
    """Маска-404: не светим разницей «мусорный id / файла нет» (FR-B2)."""
    from fastapi.responses import Response
    return Response(status_code=404)


def _media_403():
    """Просрочка/битая подпись → 403 (не перебираем по времени)."""
    from fastapi.responses import Response
    return Response(status_code=403)


def _html_response(text: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=text,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            # F4 10.16 (T-1653): строгий CSP для HTML (см. _CSP_HTML).
            "Content-Security-Policy": _CSP_HTML,
        },
    )
