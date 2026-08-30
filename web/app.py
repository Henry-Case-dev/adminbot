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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config.settings import APP_VERSION
from services.config_cache import ConfigCache

logger = logging.getLogger(__name__)

_VERSION_TAG = "__APP_VERSION__"


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
    if control is None:
        from services.control_service import ControlService
        control = ControlService()
    app.state.control = control

    from web.api.routes import api_router
    app.include_router(api_router, prefix="/api")

    rendered_index = _render_index()   # один раз at startup (84.21.2)

    # Маршруты html ДО app.mount (mount перехватывает всё /web/*):
    # /web/ и /web/index.html — с подстановкой APP_VERSION в `?v=`.
    @app.get("/web/", include_in_schema=False)
    async def web_index():
        return _html_response(rendered_index)

    @app.get("/web/index.html", include_in_schema=False)
    async def web_index_html():
        return _html_response(rendered_index)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/web/")

    app.mount("/web", CacheControlStaticFiles(directory="web"),
              name="web")

    return app


def _html_response(text: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=text,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
