"""READ-ONLY проба P0 vision: поведение probe_connection/effective-состояния.

Никаких сетевых вызовов: transport подменяется фейком. Ничего не пишет в БД.
Прод-сценарий воспроизводится локально как (endpoint=main, model=vision).
"""
import asyncio
import time

from services import hot_config as hot

FAKE = {
    "models.llm_base_url": "https://nano-gpt.com/api/v1",
    "models.llm_model_name": "deepseek/deepseek-v4.1-flash",
    "keys.llm_api_key": "sk-main-KEY",
    "models.vision_api_base_url": "https://openrouter.ai/api/v1",
    "models.vision_api_type": "openai_compatible",
    "models.vision_model": "google/gemma-4-31b-it:free",
    "keys.vision_api_key": "sk-or-v1-VISIONKEY-73chars",
    "flags.vision_enabled": True,
}


class FakeCache:
    def get(self, key, default=None):
        return FAKE.get(key, default)


class FakeTransport:
    """Ответы по сценарию: [(status, body), ...]."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, url, *, payload, headers, timeout):
        self.calls.append({"url": url,
                           "model": payload.get("model"),
                           "has_image": any(
                               isinstance(c, dict) and c.get("type") == "image_url"
                               for c in (payload.get("messages") or [{}])[-1]
                               .get("content") or []) if isinstance(
                                   (payload.get("messages") or [{}])[-1]
                                   .get("content"), list) else False,
                           "auth_last6": str(headers.get("Authorization", ""))[-6:]})
        status, body = self.answers.pop(0) if self.answers else (200, {})
        return status, body


def show(title, verdict):
    print("%-46s capability=%-12s reason=%-24s image_input=%s detail=%s"
          % (title, verdict.capability, verdict.reason, verdict.image_input,
             verdict.detail))


async def main():
    hot.set_config_cache(FakeCache())
    from services import mca_vision as mv

    mv.reset_capability_cache()
    route = mv.resolve_route()
    print("=== effective-route (прод-конфигурация) ===")
    print("source=%s base_url=%s model=%s key_present=%s rev=%s"
          % (route.source, route.base_url, route.model, route.api_key_present,
             route.config_revision))

    print()
    print("=== 1. прод-цепочка: чужой endpoint не знает модели ===")
    t = FakeTransport([(404, {"error": {"message": "model not found"}}),
                       (404, {"error": {"message": "model not found"}})])
    v = await mv.probe_connection(route, transport=t)
    show("image 404 + text 404", v)
    print("   вызовы:", t.calls)

    print()
    print("=== 2. «текст OK + картинка 400» → no_vision (по 1x1 PNG) ===")
    mv.reset_capability_cache()
    t = FakeTransport([(400, {"error": {"message": "invalid image data"}}),
                       (200, {"choices": [{"message": {"content": "pong"}}]})])
    v = await mv.probe_connection(route, transport=t)
    show("image 400 + text 200", v)

    print()
    print("=== 3. 400 из-за размера 1x1 (картинка валидна, но мала) ===")
    mv.reset_capability_cache()
    t = FakeTransport([(400, {"error": {"message": "image too small"}}),
                       (200, {"choices": [{"message": {"content": "pong"}}]})])
    v = await mv.probe_connection(route, transport=t)
    show("image 400 (too small) + text 200", v)

    print()
    print("=== 4. 401 / 429 ===")
    for status in (401, 429):
        mv.reset_capability_cache()
        t = FakeTransport([(status, {})])
        v = await mv.probe_connection(route, transport=t)
        show("image %s" % status, v)

    print()
    print("=== 5. тестовое изображение пробы ===")
    mime, w, h = mv.sniff_image(mv._NEUTRAL_PNG) or ("?", 0, 0)
    print("_NEUTRAL_PNG: bytes=%d mime=%s size=%dx%d alpha-tRNS/прозрачный=%s"
          % (len(mv._NEUTRAL_PNG), mime, w, h,
             b"tRNS" in mv._NEUTRAL_PNG or True))

    print()
    print("=== 6. кеш: TTL временного сбоя ===")
    print("capability_ttl_hours =", mv.mca_gates.vision_capability_ttl_hours(),
          "часов → недоступность держится в кеше до",
          mv.mca_gates.vision_capability_ttl_hours(), "ч")
    mv.reset_capability_cache()
    t = FakeTransport([(503, {})])
    v = await mv.probe_connection(route, transport=t)
    show("image 503 → вердикт", v)
    state = await mv.resolve_effective_state()
    print("resolve_effective_state: enabled=%s reason=%s visible=%r model=%s"
          % (state.effective_enabled, state.reason, state.visible_reason,
             state.model))
    print("кеш-запись держится: checked_at(now)=%s | expired=%s"
          % (round(v.checked_at, 2), mv._capability_expired(v.checked_at)))

    print()
    print("=== 7. инвалидация по смене ЗНАЧЕНИЯ ключа ===")
    rev_a = mv.resolve_route().config_revision
    FAKE["keys.vision_api_key"] = "sk-or-v1-ROTATED-DIFFERENT-KEY"
    rev_b = mv.resolve_route().config_revision
    print("rev(ключ A)=%s rev(ключ B)=%s → одинаковы=%s"
          % (rev_a, rev_b, rev_a == rev_b))
    state2 = await mv.resolve_effective_state()
    print("после смены ключа effective: enabled=%s reason=%s"
          % (state2.effective_enabled, state2.reason))

    print()
    print("=== 8. loop-величина: URL при base_url с готовым путём ===")
    manual = mv.VisionRoute(source="dedicated",
                            base_url="https://openrouter.ai/api/v1/chat/completions",
                            model="m", api_type="openai_compatible",
                            api_key_present=True, config_revision="x")
    print("base_url=%s → POST %s" % (manual.base_url,
                                     manual.base_url.rstrip("/")
                                     + "/chat/completions"))


asyncio.run(main())
