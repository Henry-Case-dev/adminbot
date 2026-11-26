"""MOD-ACL-UX-01 / MAC-S4-172 (egress) — секрет не покидает процесс
ни текстом в чат, ни телеметрией.

Закрывается вторая половина строки MAC-S4-172 (первая — лог/`/api/status/logs`
и маскировка API-ответов — заперта M1-B/M1-C). Решение по каждому каналу
ровно одно и переиспользует существующий механизм продукта:

* чат — единый chokepoint `services/telegram_send` (все ответы/модули/отчёты
  идут через `send_text`/`edit_text_safe`/`send_rich_message`) дополнительно
  прогоняет текст через тот же R17-санитайзер журнала `services.log_ring.
  sanitize` — тот же, которым `handlers/youtube.py` уже чистит текст ошибки
  провайдера перед показом в чате. Второго санитайзера нет;
* телеметрия — durable-sink `services.mca_events` уже безопасен и правки не
  требует: `build_event` пропускает значения через общий whitelist
  `agentic_events._safe_value` (id/code-поля — только идентификатор ≤64
  символов, свободный текст недостижим) и маскирует `_sanitize_str`/JSON до
  записи; длинный секрет не обрезается «наполовину», а отбрасывается целиком.
  Тесты ниже фиксируют это как инвариант (положительный контроль +
  не-перередактирование), а не как новую правку.

Что НЕ трогаем (уже безопасно либо недостижимо — см. evidence):

* `/debug_config` (`services/debug_config`): значение секрета никогда не
  рендерится, только `configured••••last4` по каноническому
  `ParamSpec.is_secret_value`;
* факты чекапа/`inspect_runtime` (`services/diagnostic_collector._redact`):
  `output_projection.sanitize` с `known_secret_values` (fail-closed);
* ошибка провайдера в чате (`handlers/youtube.py`): уже `log_ring.sanitize`;
* `services/external_log.py` и `services/betterstack_handler.py`: `sanitize`;
* структурированный лог (journald): `SecretMaskFilter` на консольном
  обработчике в `bot.py`.

Контроли в каждом тесте: позитивный (посаженный секрет обязан быть найден),
чувствительность (похожее, но не секретное значение не трогаем) и
не-перередактирование (обычный текст байт-в-байт).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import log_ring as log_ring_mod
from services import mca_events
from services.log_ring import sanitize as log_sanitize
from services.telegram_send import (
    build_cover_article_html,
    edit_text_safe,
    send_rich_message,
    send_text,
)

# Egress-предохранитель проверяется на ПРОД-дефолтах (ON): маркер снимает
# conftest-изоляцию `TELEGRAM_SEND_GUARD_ENABLED=False` (прецедент
# `tests/test_outgoing_guard_round1022.py`).
pytestmark = pytest.mark.system2

#: Посаженный «секрет каталога» (значение из settings/env).
PLANTED_SECRET = "123456:CHAT_EGRESS_REAL_BOT_TOKEN_9f3c"
#: Секрет длиннее лимита короткого поля mca_events (120) — проверяет порядок
#: «маска, затем обрезка».
LONG_SECRET = ("K" * 130) + "LONGTAIL_SECRET_7731"
#: Провайдерская ошибка в том виде, в котором её реально печатает llm_client.
PROVIDER_ERROR = (
    "LLM transport error after 3 attempts: ReadTimeout: "
    "key=sk-proj-ABCDEF0123456789REALSECRET "
    "Authorization: Bearer gsk_live_abcdef123456789 "
    "dsn=postgresql://adminbot:pass_proxy_123@127.0.0.1:5432/adminbot")

#: Обычный текст бота: id, чат, таймзона, URL, путь. Ничего секретного.
ORDINARY = (
    "Готово: чат -1001234567890, user 42, Europe/Moscow 21:40. "
    "Источник: https://example.com/page?id=7&lang=ru. "
    "Файл: media/common/goodmorning/goodmorning_07.jpg. Всего 12 строк.")


@pytest.fixture(autouse=True)
def _planted_secrets(monkeypatch):
    """Фиксированный набор секретов: settings — frozen, подменяем собранный
    кэш так же, как это делает `tests/test_log_ring.py`."""
    monkeypatch.setattr(log_ring_mod, "_SECRETS",
                        (PLANTED_SECRET, LONG_SECRET))


class TestChatEgress:
    """Чат-канал: chokepoint обязан снять секрет из уходящего текста."""

    @pytest.mark.asyncio
    async def test_send_text_masks_planted_secret(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        text = f"Диагностика: токен бота {PLANTED_SECRET}, остальное в норме."
        await send_text(bot, 10, text)
        sent = bot.send_message.await_args.args[1]
        assert PLANTED_SECRET not in sent          # позитивный контроль
        assert "***" in sent
        assert "Диагностика: токен бота" in sent    # текст не уничтожен
        assert "остальное в норме." in sent

    @pytest.mark.asyncio
    async def test_send_text_masks_provider_error_shapes(self):
        """Секрет может прийти не из каталога, а из текста ошибки провайдера:
        Bearer-токен, префиксный ключ, креды в URI.DSN (паттерны R17)."""
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        await send_text(bot, 10, PROVIDER_ERROR)
        sent = bot.send_message.await_args.args[1]
        assert "sk-proj-ABCDEF0123456789REALSECRET" not in sent
        assert "gsk_live_abcdef123456789" not in sent
        assert "pass_proxy_123" not in sent
        assert sent.startswith("LLM transport error after 3 attempts")

    @pytest.mark.asyncio
    async def test_edit_text_safe_masks_planted_secret(self):
        message = MagicMock()
        message.edit_text = AsyncMock(return_value="edited")
        await edit_text_safe(message, f"шаг 2: {PLANTED_SECRET} принят")
        edited = message.edit_text.await_args.args[0]
        assert PLANTED_SECRET not in edited
        assert "шаг 2:" in edited and "принят" in edited

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fmt", ["auto", "markdown", "html"])
    async def test_send_rich_message_masks_planted_secret(self, fmt):
        """rich-канал (отчёт чекапа, саммари) — та же граница egress."""
        bot = MagicMock()
        bot.send_rich_message = AsyncMock(return_value="sent")
        await send_rich_message(bot, 10, f"Отчёт: {PLANTED_SECRET}",
                                content_format=fmt)
        rich = bot.send_rich_message.await_args.args[1]
        body = (rich.html or "") + (rich.markdown or "")
        assert PLANTED_SECRET not in body
        assert "Отчёт: ***" in body

    def test_build_cover_article_html_masks_planted_secret(self):
        html = build_cover_article_html(f"Текст {PLANTED_SECRET} и обложка")
        assert PLANTED_SECRET not in html
        assert "Текст ***" in html

    @pytest.mark.asyncio
    async def test_ordinary_message_passes_through_unchanged(self):
        """Не-перередактирование: обычный ответ бота не меняется ни на байт."""
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        await send_text(bot, 10, ORDINARY)
        assert bot.send_message.await_args.args[1] == ORDINARY

    @pytest.mark.asyncio
    async def test_near_miss_tokens_are_not_masked(self):
        """Чувствительность: похожие на ключ, но не ключи — не трогаем."""
        near = ("префикс sk- и sk-abc, слово bearer, bearer без токена, "
                "параметр key= без значения, user:pass@ без схемы")
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        await send_text(bot, 10, near)
        assert bot.send_message.await_args.args[1] == near

    def test_chat_egress_reuses_log_channel_sanitizer(self):
        """Второго санитайзера нет: чат использует тот же `log_ring.sanitize`."""
        from services import telegram_send

        assert telegram_send._sanitize_secrets is log_sanitize

    @pytest.mark.asyncio
    async def test_guard_off_keeps_documented_passthrough(self, monkeypatch):
        """Существующий рубильник сохраняет задокументированную семантику
        «OFF = прямой вызов» (env-only, дефолт ON) — контракт не переписан."""
        monkeypatch.setattr(Settings, "TELEGRAM_SEND_GUARD_ENABLED", False)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="sent")
        await send_text(bot, 10, PLANTED_SECRET)
        assert bot.send_message.await_args.args[1] == PLANTED_SECRET


class TestChatDiagnosticsAlreadySafe:
    """Диагностика, которую владелец запрашивает в чате.

    `/debug_config` — единственная allowlist-точка, печатающая значения
    настроек. Она не использует egress-chokepoint (админ-канон), но и не
    отдаёт секрет: значение маскируется ДО рендера по каноническому
    ``ParamSpec.is_secret_value``. Это доказательство «уже безопасно», а не
    новая правка.
    """

    class _FakeCache:
        is_initialized = True
        pg_available = True
        loaded_at = None

        def __init__(self, values):
            self._values = values

        def get_all(self):
            return dict(self._values)

        def get(self, key):
            return self._values.get(key)

        def get_updated_at(self, key):
            return None

    def test_secret_value_never_rendered(self):
        from services import debug_config

        spec = debug_config.get_by_pg_key("keys.llm_api_key")
        assert spec is not None and spec.is_secret_value
        cache = self._FakeCache({"keys.llm_api_key": PLANTED_SECRET})
        item = debug_config._dump_item(cache, "keys.llm_api_key")
        assert item["secret"] is True
        assert item["value"] == {"configured": True,
                                 "last4": PLANTED_SECRET[-4:]}
        line = debug_config.format_line(spec, "keys.llm_api_key", item)
        assert PLANTED_SECRET not in line
        assert line.endswith("configured••••" + PLANTED_SECRET[-4:])

    def test_build_lines_never_renders_secret(self):
        from services import debug_config

        cache = self._FakeCache({
            "keys.llm_api_key": PLANTED_SECRET,
            "keys.tavily_api_key": "tvly-" + PLANTED_SECRET,
        })
        text = "\n".join(debug_config.build_lines(cache))
        assert PLANTED_SECRET not in text
        assert "configured" in text


class TestTelemetryEgress:
    """Телеметрия: durable-событие `mca_events` не содержит значения секрета.

    Канал уже безопасен (правки не требует): значение принимается только в
    id/code-поле идентификаторной формы (≤64 символа) либо в JSON-поле, и в
    обоих случаях маскируется существующим R17-санитайзером ДО записи.
    """

    def test_code_field_masks_planted_secret(self):
        """Позитивный контроль: короткий секрет каталога в code-поле → `***`."""
        short = PLANTED_SECRET[:60]
        ev = mca_events.build_event("llm_call", outcome="failed", level="ERROR",
                                    stage=short)
        assert ev is not None
        assert ev["stage"] == "***"
        assert short not in json.dumps(ev, ensure_ascii=False)

    def test_long_secret_is_dropped_not_truncated(self):
        """Секрет длиннее лимита поля не попадает в событие даже префиксом:
        whitelist отбрасывает неидентификаторное значение целиком (обрезка
        «до маски» не оставляет первые N символов секрета)."""
        ev = mca_events.build_event("llm_call", outcome="failed", level="ERROR",
                                    stage=LONG_SECRET, status=LONG_SECRET)
        assert ev is not None
        blob = json.dumps(ev, ensure_ascii=False)
        assert LONG_SECRET not in blob
        assert LONG_SECRET[:60] not in blob
        assert "stage" not in ev and "status" not in ev

    def test_json_payload_masks_planted_secret(self):
        """JSON-поля (`usage_json`/`error_json`) — маскировка до сериализации
        в строку события (регрессия B-MCA13-1)."""
        ev = mca_events.build_event(
            "llm_call", outcome="failed", level="ERROR",
            usage_json={"note": PROVIDER_ERROR},
            error_json={"type": "LLMTransportError", "stack": PROVIDER_ERROR})
        assert ev is not None
        blob = json.dumps(ev, ensure_ascii=False)
        assert "sk-proj-ABCDEF0123456789REALSECRET" not in blob
        assert "gsk_live_abcdef123456789" not in blob
        assert "pass_proxy_123" not in blob
        assert "LLMTransportError" in blob           # структура сохранена

    def test_ordinary_fields_unchanged(self):
        """Не-перередактирование: обычные id/enum/имена не искажаются."""
        ev = mca_events.build_event(
            "llm_call", outcome="success", level="INFO",
            stage="llm:plan", status="ok", model="deepseek-chat",
            provider="deepseek", chat_id=42, attempt=2, duration_ms=120)
        assert ev is not None
        assert ev["stage"] == "llm:plan"
        assert ev["status"] == "ok"
        assert ev["model"] == "deepseek-chat"
        assert ev["provider"] == "deepseek"
        assert ev["chat_id"] == "42"
        assert ev["attempt"] == 2
        assert ev["duration_ms"] == 120

    def test_unmapped_reason_code_still_bounded(self):
        """Контракт кодов не сломан правкой порядка: неизвестный код
        по-прежнему заменяется стабильным маркером, а не сырым значением."""
        ev = mca_events.build_event("llm_call", outcome="failed",
                                    reason_code=LONG_SECRET)
        assert ev is not None
        assert ev["reason_code"] != LONG_SECRET
        assert LONG_SECRET[:40] not in json.dumps(ev, ensure_ascii=False)
