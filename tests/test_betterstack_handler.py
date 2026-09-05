"""Раунд 4 (T-708, spec AC-B1..B7) — тесты собственного BetterStackHandler.

Покрытие: фрейм-совместимость с logtail (dt ISO-UTC/level/severity/message/
context.runtime+system); emit→буфер→flush с моком urllib.request.urlopen —
ровно 1 POST JSON-массивом; 4xx/5xx/сеть → failed + WARNING-журнал с rate-gate
≤1/60с; восстановление → INFO «send ok | recovered»; дроп при полном буфере →
счётчик dropped + rate-limited WARNING; sanitize (R17) в message; анти-рекурсия
(записи модульного логгера не эхосируются); close() досылает остаток; стартовые
маркеры attached/skipped + aiogram.event=WARNING (bot.py-импорт, AC-B4/B6).

Токен читается строго из LOGTAIL_SOURCE_TOKEN (общий для Errors и Logs;
BETTERSTACK_SOURCE_TOKEN игнорируется; содержимое токена не проверяется —
никаких эвристик/Sentry-сравнений). 401 → WARNING с нейтральной подсказкой
(проверьте source token; значение токена НЕ в логе; rate-gate ≤1/60с жив).
"""
import json
import logging
import sys
from unittest.mock import patch

import pytest

from services.betterstack_handler import (
    BetterStackHandler,
    make_betterstack_frame,
)
from services.log_ring import sanitize


def _make_record(name="tests.bsh", level=logging.INFO, msg=None,
                 args=None, pathname=__file__, lineno=1):
    if msg is None:
        msg, args = "hello %s", ("world",)
    return logging.LogRecord(name, level, pathname, lineno, msg, args,
                             exc_info=None)


class _OkResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StatusResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def handler():
    # flush_interval большой: фоновый флашер спит — тесты флашат явно (flush),
    # детерминированно (батч не уходит в сеть между emit и flush сам собой).
    h = BetterStackHandler(source_token="t" * 32, buffer_size=50,
                           flush_interval=10.0)
    yield h
    try:
        h.close()
    except Exception:
        pass


# ── AC-B1: фрейм-совместимость с logtail (frame.py) ────────────────────────

class TestFrameCompat:
    def test_info_frame_fields(self):
        frame = make_betterstack_frame(
            _make_record(level=logging.INFO, msg="текст %s", args=("x",)),
            "текст x")
        assert set(frame) == {"dt", "level", "severity", "message", "context"}
        # dt — ISO-8601 UTC из record.created
        assert frame["dt"].endswith("+00:00")
        assert "T" in frame["dt"]
        assert frame["level"] == "info"
        # severity = levelno//10 (logtail/frame.py + spec 3.1.2): INFO 20 → 2
        assert frame["severity"] == 2
        assert frame["message"] == "текст x"
        ctx = frame["context"]
        assert set(ctx) == {"runtime", "system"}
        runtime = ctx["runtime"]
        assert set(runtime) == {"function", "file", "line", "thread_id",
                                "thread_name", "logger_name"}
        assert runtime["logger_name"] == "tests.bsh"
        assert runtime["line"] == 1
        assert runtime["file"]
        system = ctx["system"]
        assert set(system) == {"pid", "process_name"}
        assert isinstance(system["pid"], int)

    def test_warning_level_and_severity(self):
        frame = make_betterstack_frame(_make_record(level=logging.WARNING),
                                       "warn")
        assert frame["level"] == "warning"
        assert frame["severity"] == 3

    def test_error_severity(self):
        frame = make_betterstack_frame(_make_record(level=logging.ERROR), "e")
        assert frame["level"] == "error"
        assert frame["severity"] == 4


# ── AC-B2/B7: отправка, счётчики, sanitize, rate-gate ───────────────────────

class TestPosting:
    def test_emit_flush_sends_single_post_json_array(self, handler, monkeypatch):
        """(а): emit+flush → ровно 1 POST с JSON-массивом фреймов."""
        posts = []

        class _Capture:
            def __call__(self, request, timeout=None):
                posts.append(request)
                return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", _Capture())
        for i in range(3):
            handler.emit(_make_record(msg="событие %d", args=(i,)))
        handler.flush()
        assert len(posts) == 1
        req = posts[0]
        assert req.full_url == f"https://in.logs.betterstack.com/{'t' * 32}"
        assert req.method == "POST"
        headers = {k.lower(): v for k, v in req.headers.items()}
        assert headers["content-type"] == "application/json"
        body = json.loads(req.data.decode("utf-8"))
        assert isinstance(body, list) and len(body) == 3
        assert all(b["message"].startswith("событие ") for b in body)
        assert all(b["level"] == "info" and b["severity"] == 2 for b in body)
        assert handler.get_stats() == {"sent": 3, "failed": 0, "dropped": 0}
        # буфер после flush пуст (AC-B3)
        assert handler._drain(100) == []

    def test_success_after_failure_logs_recovery(self, handler, caplog,
                                                 monkeypatch):
        """Сбой → failed; затем успех → INFO «recovered | streak=N»."""
        calls = {"n": 0}

        def flaky(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _StatusResponse(400)
            return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", flaky)
        with caplog.at_level(logging.INFO, logger="services.betterstack_handler"):
            handler.emit(_make_record(msg="m1"))
            handler.flush()                       # 1-й — сбой (400, без ретрая)
            assert handler.failed == 1
            handler.emit(_make_record(msg="m2"))
            handler.flush()                       # 2-й — успех
        assert handler.sent == 1
        assert any("[betterstack] send failed | reason=status=400 | failed=1"
                   in r.message for r in caplog.records)
        assert any("[betterstack] send ok | recovered | streak=1"
                   in r.message for r in caplog.records)

    def test_5xx_retried_once_then_failed(self, handler, monkeypatch):
        monkeypatch.setattr(
            "services.betterstack_handler._RETRY_PAUSE_SECONDS", 0.01)
        calls = {"n": 0}

        def fail500(request, timeout=None):
            calls["n"] += 1
            return _StatusResponse(500)

        monkeypatch.setattr("urllib.request.urlopen", fail500)
        handler.emit(_make_record(msg="m"))
        handler.flush()
        assert calls["n"] == 2                    # старт + 1 повтор
        assert handler.failed == 1
        assert handler.sent == 0

    def test_network_error_rate_limited_to_one_warning(self, handler, caplog,
                                                       monkeypatch):
        """(б): два сбоя подряд (<60с) → ОДНА WARNING-строка в журнале."""
        # пауза перед повтором батча (_stop.wait) — реально 1.0s на каждый
        # flush; здесь важны счётчики WARNING, не время.
        monkeypatch.setattr("services.betterstack_handler._RETRY_PAUSE_SECONDS", 0.01)

        def boom(request, timeout=None):
            raise TimeoutError("deadline")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        with caplog.at_level(logging.WARNING,
                             logger="services.betterstack_handler"):
            handler.emit(_make_record(msg="m1"))
            handler.flush()
            handler.emit(_make_record(msg="m2"))
            handler.flush()
        warns = [r for r in caplog.records
                 if r.message.startswith("[betterstack] send failed")]
        assert len(warns) == 1
        assert handler.failed == 2
        # интервал >60с → вторая WARNING появляется
        with caplog.at_level(logging.WARNING,
                             logger="services.betterstack_handler"):
            handler._last_warn_ts = 0.0
            handler.emit(_make_record(msg="m3"))
            handler.flush()
        warns2 = [r for r in caplog.records
                  if r.message.startswith("[betterstack] send failed")]
        assert len(warns2) == 2

    def test_sanitize_applied_to_network_message(self, handler, monkeypatch):
        """(AC-B7): R17 — секрет в message уходит в фрейме как ***."""
        posts = []

        class _Capture:
            def __call__(self, request, timeout=None):
                posts.append(request)
                return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", _Capture())
        handler.emit(_make_record(
            msg="Authorization: Bearer sk-or-test1234567890"))
        handler.flush()
        assert len(posts) == 1
        body = json.loads(posts[0].data.decode("utf-8"))
        sent = body[0]["message"]
        assert "***" in sent
        assert "sk-or-test1234567890" not in sent
        # контроль: sanitize действительно маскирует (не прошёл как есть)
        assert sanitize("Authorization: Bearer sk-or-test1234567890") == \
            "Authorization: Bearer ***"

    def test_dropped_when_buffer_full_rate_limited(self, caplog, monkeypatch):
        """(AC-B3): полный буфер → dropped растёт, WARNING есть (не тихо)."""
        posts = []

        class _Capture:
            def __call__(self, request, timeout=None):
                posts.append(request)
                return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", _Capture())
        h = BetterStackHandler(source_token="t" * 8, buffer_size=3,
                               flush_interval=10.0)   # флашер спит
        try:
            with caplog.at_level(logging.WARNING,
                                 logger="services.betterstack_handler"):
                for i in range(7):
                    h.emit(_make_record(msg="msg %d", args=(i,)))
            assert h.dropped == 4
            assert h._drain(100)                     # в буфере только 3
            assert len(h._drain(100)) == 0
            assert any("[betterstack] buffer full" in r.message
                       for r in caplog.records)
            # rate-gate: следующая дроп-волна в том же интервале не логируется
            before = len([r for r in caplog.records
                          if "[betterstack] buffer full" in r.message])
            h.emit(_make_record(msg="ещё"))
            after = len([r for r in caplog.records
                         if "[betterstack] buffer full" in r.message])
            assert after == before
        finally:
            h.close()


# ── AC-B5: анти-рекурсия и close() ─────────────────────────────────────────

class TestLifecycle:
    def test_module_logger_records_not_echoed(self, handler, monkeypatch):
        """(е): запись модульного логгера не порождает отправку в сеть."""
        calls = {"n": 0}

        def capture(request, timeout=None):
            calls["n"] += 1
            return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", capture)
        handler.emit(_make_record(name="services.betterstack_handler",
                                  level=logging.WARNING,
                                  msg="[betterstack] send failed | x"))
        handler.emit(_make_record(name="services.betterstack_handler.sub",
                                  msg="child"))
        handler.flush()
        assert calls["n"] == 0
        assert handler.sent == 0
        assert handler.get_stats() == {"sent": 0, "failed": 0, "dropped": 0}

    def test_close_flushes_remaining_and_is_idempotent(self, monkeypatch):
        posts = []

        class _Capture:
            def __call__(self, request, timeout=None):
                posts.append(request)
                return _OkResponse()

        monkeypatch.setattr("urllib.request.urlopen", _Capture())
        h = BetterStackHandler(source_token="t" * 8, buffer_size=50,
                               flush_interval=10.0)
        h.emit(_make_record(msg="перед закрытием"))
        h.close()                                    # досыл остатка
        assert len(posts) == 1
        assert h.get_stats()["sent"] == 1
        h.close()                                    # повторный — безвреден
        h.close()
        assert not h._thread.is_alive()

    def test_emit_never_raises(self, handler):
        # битый record (format падает) — emit не бросает
        class _BrokenRecord:
            name = "tests.bsh"
            created = "не-число"

        with patch.object(handler, "handleError", return_value=None) as he:
            handler.emit(_BrokenRecord())   # type: ignore[arg-type]
        assert he.called


# ── Раунд 5 (T-729, spec 5.1.4/5.1.5): 401 → нейтральная подсказка ────────

class TestHttp401Hint:
    def test_401_warning_contains_hint_not_token(self, caplog, monkeypatch):
        """401 → WARNING с нейтральной подсказкой (проверьте source token);
        значение токена в журнал НЕ попадает (R17)."""
        def fail401(request, timeout=None):
            return _StatusResponse(401)

        monkeypatch.setattr("urllib.request.urlopen", fail401)
        h = BetterStackHandler(source_token="т" * 32, flush_interval=10.0)
        try:
            with caplog.at_level(logging.WARNING,
                                 logger="services.betterstack_handler"):
                h.emit(_make_record(msg="m1"))
                h.flush()
            warns = [r.message for r in caplog.records
                     if r.message.startswith("[betterstack] send failed")]
            assert len(warns) == 1
            assert "reason=status=401" in warns[0]
            assert "подсказка: проверьте LOGTAIL_SOURCE_TOKEN/.env" in warns[0]
            assert "Source Token" in warns[0]
            assert "Sentry" not in warns[0]
            assert "т" * 32 not in warns[0]            # R17: токена нет
            assert "failed=1" in warns[0]
            assert h.failed == 1
        finally:
            h.close()

    def test_series_of_401_rate_limited_to_one_warning(self, caplog,
                                                      monkeypatch):
        """Серия 401 (<60с) → ОДНО WARNING в окне (rate-gate _rate_warn)."""
        def fail401(request, timeout=None):
            return _StatusResponse(401)

        monkeypatch.setattr("urllib.request.urlopen", fail401)
        h = BetterStackHandler(source_token="t" * 32, flush_interval=10.0)
        try:
            with caplog.at_level(logging.WARNING,
                                 logger="services.betterstack_handler"):
                h.emit(_make_record(msg="m1"))
                h.flush()
                h.emit(_make_record(msg="m2"))
                h.flush()
                h.emit(_make_record(msg="m3"))
                h.flush()
            warns = [r for r in caplog.records
                     if r.message.startswith("[betterstack] send failed")]
            assert len(warns) == 1                      # одна в окне 60с
            assert h.failed == 3
            assert "подсказка" in warns[0].message
        finally:
            h.close()

    def test_http_error_path_reason_401_gets_hint(self, handler, caplog):
        """_reason(HTTPError code=401) → reason='status=401' → подсказка
        добавляется (путь _reason из _post тоже покрыт)."""
        import urllib.error

        from services.betterstack_handler import _reason

        err = urllib.error.HTTPError(
            "https://in.logs.betterstack.com/tok", 401, "Unauthorized",
            {}, None)
        assert _reason(err) == "status=401"
        with caplog.at_level(logging.WARNING,
                             logger="services.betterstack_handler"):
            handler._mark_failed(_reason(err), 2)
        warns = [r.message for r in caplog.records
                 if r.message.startswith("[betterstack] send failed")]
        assert warns and "подсказка" in warns[-1]
        assert "LOGTAIL_SOURCE_TOKEN" in warns[-1]
        assert "Sentry" not in warns[-1]


# ── AC-B4/B6: маркеры бота и aiogram.event (импорт bot.py) ─────────────────

class TestBotMarkers:
    """AC-B4/B6: маркеры attached/skipped + aiogram.event=WARNING через
    импорт bot.py. ВАЖНО: config.settings загружает .env (load_dotenv без
    override) — чтобы прод-токен из .env не вмешался, LOGTAIL_SOURCE_TOKEN
    ЯВНО выставляется ДО импорта (пустая строка = «токена нет»), а
    BETTERSTACK_SOURCE_TOKEN не задаётся вовсе — код читает только
    LOGTAIL_SOURCE_TOKEN."""

    def _import_bot(self, monkeypatch, env):
        import importlib
        import config.settings as settings_mod
        import sentry_sdk

        monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_BSH")
        if "BETTERSTACK_SOURCE_TOKEN" in env:
            monkeypatch.setenv("BETTERSTACK_SOURCE_TOKEN",
                               env["BETTERSTACK_SOURCE_TOKEN"])
        else:
            monkeypatch.delenv("BETTERSTACK_SOURCE_TOKEN", raising=False)
        monkeypatch.setenv("LOGTAIL_SOURCE_TOKEN",
                           env.get("LOGTAIL_SOURCE_TOKEN", ""))
        monkeypatch.setenv("SENTRY_DSN", env.get("SENTRY_DSN", ""))
        # SENTRY_DSN в тесте — фейковый: sentry_sdk.init НЕ запускаем (иначе
        # при выходе из pytest процесс пытается флашить события в Sentry).
        monkeypatch.setattr("sentry_sdk.init", lambda *a, **kw: None)
        sys.modules.pop("bot", None)
        importlib.reload(settings_mod)
        import bot as bot_mod  # noqa: F401
        return bot_mod

    def test_attached_marker_with_token(self, monkeypatch, caplog):
        """Токен из LOGTAIL_SOURCE_TOKEN → attached-маркер БЕЗ from=."""
        try:
            with caplog.at_level(logging.INFO, logger="bot"):
                self._import_bot(monkeypatch, {"LOGTAIL_SOURCE_TOKEN": "x" * 32})
            messages = [r.message for r in caplog.records]
            marker = "[betterstack] attached | token_len=32 | handler=own-v1"
            assert any(m == marker for m in messages)   # байт-эталон спеки
            assert "x" * 32 not in " ".join(messages)      # токена нет
            assert not any("| from=" in m for m in messages)
        finally:
            self._close_betterstack_handlers()

    def test_betterstack_env_ignored_strictly_logtail(self, monkeypatch,
                                                      caplog):
        """BETTERSTACK_SOURCE_TOKEN игнорируется: заданы обе переменные →
        attached c token_len строго по LOGTAIL_SOURCE_TOKEN."""
        try:
            with caplog.at_level(logging.INFO, logger="bot"):
                self._import_bot(monkeypatch, {
                    "BETTERSTACK_SOURCE_TOKEN": "b" * 8,
                    "LOGTAIL_SOURCE_TOKEN": "z" * 32,
                })
            messages = [r.message for r in caplog.records]
            marker = "[betterstack] attached | token_len=32 | handler=own-v1"
            assert any(m == marker for m in messages)
            assert "z" * 32 not in " ".join(messages)      # R17
        finally:
            self._close_betterstack_handlers()

    def test_betterstack_env_only_no_attach(self, monkeypatch, caplog):
        """Только BETTERSTACK_SOURCE_TOKEN (LOGTAIL пуст) → токена нет:
        skipped-маркер, attached отсутствует."""
        try:
            with caplog.at_level(logging.WARNING, logger="bot"):
                self._import_bot(monkeypatch,
                                 {"BETTERSTACK_SOURCE_TOKEN": "a" * 32})
            messages = [r.message for r in caplog.records]
            assert any(
                m == "[betterstack] skipped (no LOGTAIL_SOURCE_TOKEN)"
                for m in messages)
            assert not any("attached" in m for m in messages)
        finally:
            self._close_betterstack_handlers()

    def test_token_coinciding_with_sentry_dsn_pubkey_is_ok(self, monkeypatch,
                                                           caplog):
        """Совпадение токена логов с public key из SENTRY_DSN — НОРМА:
        attached-маркер, НИКАКИХ WARNING-эвристик."""
        token = "SyNtHtIcK3y9v0000000000"
        try:
            with caplog.at_level(logging.INFO, logger="bot"):
                self._import_bot(monkeypatch, {
                    "LOGTAIL_SOURCE_TOKEN": token,
                    "SENTRY_DSN": f"https://{token}@o450000.ingest.sentry.io/1",
                })
            records = caplog.records
            warns = [r for r in records if r.levelno >= logging.WARNING]
            assert not any("Sentry" in m or "похож" in m
                           for m in (r.message for r in warns))
            assert any(
                r.levelno == logging.INFO
                and r.message == ("[betterstack] attached | token_len=%d "
                                  "| handler=own-v1" % len(token))
                for r in records)
            assert token not in " ".join(r.message for r in records)  # R17
        finally:
            self._close_betterstack_handlers()

    def test_skipped_marker_without_token(self, monkeypatch, caplog):
        try:
            with caplog.at_level(logging.WARNING, logger="bot"):
                self._import_bot(monkeypatch, {})
            messages = [r.message for r in caplog.records]
            assert any(
                m == "[betterstack] skipped (no LOGTAIL_SOURCE_TOKEN)"
                for m in messages)
            # FR-B4/AC-B6: aiogram.event = WARNING, root INFO не тронут
            assert logging.getLogger("aiogram.event").level == logging.WARNING
        finally:
            self._close_betterstack_handlers()

    @staticmethod
    def _close_betterstack_handlers():
        root = logging.getLogger()
        for h in list(root.handlers):
            if isinstance(h, BetterStackHandler):
                try:
                    h.close()
                except Exception:
                    pass
        # ring-хендлер/console остаются — на других тестов не влияют
