"""Smoke test for Better Stack monitoring integration.

Раунд 10.18 (F1, ADR-1018-1): библиотечный `logtail-python` в прод-пути НЕ
используется — лог отправляет собственный `BetterStackHandler` с явным
US-хостом (env `BETTERSTACK_HOST`). Без хоста/токена хендлер не создаётся
(fail-safe). Секреты не печатаем (R17).

Раунд 10.19 (F1, ADR-1019-1): ingest-контракт — `POST https://{host}` +
`Authorization: Bearer {token}` (токен НЕ в path).

Ручной запуск: `python tests/test_monitoring_smoke.py`.
"""
import os
import logging
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

# pytest: корневой conftest ставит ADMINBOT_SKIP_DOTENV=1 — не засорять
# os.environ боевым .env для остальных модулей сессии (порядок импорта
# модулей ≠ порядок тестов). Ручной запуск (python tests/test_monitoring_smoke.py)
# работает как раньше.
if os.getenv("ADMINBOT_SKIP_DOTENV") != "1":
    load_dotenv()

import sentry_sdk  # noqa: E402

from services.betterstack_handler import BetterStackHandler  # noqa: E402

logger = logging.getLogger("smoke_test")


def test_logging():
    """Test that log messages flow through BetterStackHandler."""
    print("--- Logging Smoke Test ---")
    logger.info("Test Better Stack Log - INFO level")
    logger.warning("Test Better Stack Log - WARNING level")
    print("[OK] Test log messages sent to Better Stack")
    assert True


def test_sentry_error():
    """Test that exceptions are captured by Sentry."""
    print("--- Sentry Smoke Test ---")
    try:
        raise Exception("Test Better Stack Sentry Error")
    except Exception as e:
        logger.error("Test error captured: %s", str(e))
        print(f"[OK] Test exception triggered: {e}")
    assert True


def main():
    sentry_dsn = os.getenv("SENTRY_DSN")
    token = os.getenv("LOGTAIL_SOURCE_TOKEN")
    host = (os.getenv("BETTERSTACK_HOST") or "").strip()

    print("=" * 50)
    print("Better Stack Monitoring Smoke Test")
    print("=" * 50)
    print(f"SENTRY_DSN configured: {bool(sentry_dsn)}")
    print(f"LOGTAIL_SOURCE_TOKEN configured: {bool(token)}")
    print(f"BETTERSTACK_HOST configured: {bool(host)}")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    handlers = [console_handler]
    if token and host:
        handlers.append(BetterStackHandler(source_token=token, host=host))
    else:
        print("[WARN] BETTERSTACK_HOST/LOGTAIL_SOURCE_TOKEN не заданы — "
              "лог-хендлер не создан (fail-safe)")

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)

    if sentry_dsn:
        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=1.0)
        print("[OK] Sentry SDK initialized")

    test_logging()
    test_sentry_error()

    print("\n" + "=" * 50)
    print("Smoke test completed. Check Better Stack dashboard for:")
    print("1. Log entries with 'Test Better Stack Log'")
    print("2. Error event with 'Test Better Stack Sentry Error'")
    print("=" * 50)


if __name__ == "__main__":
    main()
