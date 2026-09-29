# -*- coding: utf-8 -*-
"""ASAP-3 browser-verification launcher (локальный dev-контур §8 spec).

Поднимает ТОЛЬКО webapp (uvicorn) на 127.0.0.1:8765 c ConfigCache из .env
(PG/seeded-контур, без Telegram polling). Запуск вручную Builder'ом для
Playwright-прогона; в прод не деплоится.
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import uvicorn  # noqa: E402

from config.settings import settings  # noqa: E402
from services.config_cache import ConfigCache  # noqa: E402
from web.app import create_app  # noqa: E402


async def main() -> None:
    cache = ConfigCache()
    app = create_app(cache)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
