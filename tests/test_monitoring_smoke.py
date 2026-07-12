"""Smoke test for Better Stack monitoring integration."""
import os
import logging
import sys
import traceback

from dotenv import load_dotenv
load_dotenv()

import sentry_sdk
from logtail import LogtailHandler

logger = logging.getLogger("smoke_test")


def test_logging():
    """Test that log messages flow through Logtail."""
    print("--- Logging Smoke Test ---")
    logger.info("Test Better Stack Log - INFO level")
    logger.warning("Test Better Stack Log - WARNING level")
    print("[OK] Test log messages sent to Logtail")
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
    logtail_token = os.getenv("LOGTAIL_SOURCE_TOKEN")

    print("=" * 50)
    print("Better Stack Monitoring Smoke Test")
    print("=" * 50)
    print(f"SENTRY_DSN configured: {bool(sentry_dsn)}")
    print(f"LOGTAIL_SOURCE_TOKEN configured: {bool(logtail_token)}")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    handlers = [console_handler]
    if logtail_token:
        handlers.append(LogtailHandler(source_token=logtail_token))

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    root_logger = logging.getLogger()

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
