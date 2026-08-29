"""Epic 85 (84.4/84.7, T-615/T-618) — FastAPI-приложение TMA-админки.

Фабрика create_app(cache) вызывается из bot.py (один event loop — R2/R3);
app.state.cache — ОБЩИЙ объект ConfigCache для aiogram и FastAPI.
Lifespan: cache.init() при старте (идемпотентно; R6 — PG down не блокирует
бот), на выходе — НИЧЕГО не закрывает (закрытие пула — в bot.py on_shutdown,
ровно один раз). Статика: /web → StaticFiles(html=True), / → /web/.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from services.config_cache import ConfigCache

logger = logging.getLogger(__name__)


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

    app.mount("/web", StaticFiles(directory="web", html=True), name="web")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/web/")

    return app
