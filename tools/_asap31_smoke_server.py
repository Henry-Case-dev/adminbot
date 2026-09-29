# -*- coding: utf-8 -*-
"""ASAP-3.1 implementation-side browser smoke: локальный webapp (SQLite/
без Telegram polling; НЕ prod, PG не пишется). Запуск: uvicorn на 127.0.0.1.
Использование: .venv/Scripts/python.exe tools/_asap31_smoke_server.py [port]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings  # noqa: E402


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8031
    import uvicorn
    from services.config_cache import ConfigCache
    from web.app import create_app

    cache = ConfigCache()
    # Инициализация кэша: локальный SQLite/фолбэк (PG не пишется — dev-машина
    # без prod-секретов; cache.pg_available False → сид пропускается штатно).
    try:
        await cache.init()
    except Exception as exc:  # pragma: no cover - dev-сервер, fail-soft
        print("cache.init warn:", type(exc).__name__, exc)
    app = create_app(cache, control=None)
    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            loop="auto", log_level="warning")
    server = uvicorn.Server(config)
    print(f"SMOKE_SERVER_READY http://127.0.0.1:{port}/web/")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
