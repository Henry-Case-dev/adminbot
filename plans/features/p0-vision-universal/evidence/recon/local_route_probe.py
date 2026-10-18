"""READ-ONLY recon-проба (P0 vision): что фактически читает resolve_route().

Ничего не пишет в repo/БД; hot-кеш подменяется фейком (in-process).
Секреты не печатаются: только булевы/хеш-маркеры.
"""
import hashlib

from services import hot_config as hot
from services import param_catalog as pc

FAKE = {
    "models.llm_base_url": "https://api.main.example/v1",
    "models.llm_model_name": "main-model",
    "keys.llm_api_key": "sk-main-KEY",
    "models.vision_api_base_url": "https://openrouter.ai/api/v1",
    "models.vision_api_type": "openai_compatible",
    "models.vision_model": "google/gemma-4-31b-it:free",
    "keys.vision_api_key": "sk-or-v1-VISIONKEY",
}


class FakeCache:
    def get(self, key, default=None):
        return FAKE.get(key, default)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()[:8] if value else ""


def main():
    keys = {s.pg_key for s in pc.REGISTRY.values()}
    print("[catalog] 'models.vision_api_base_url' registered:",
          "models.vision_api_base_url" in keys)
    print("[catalog] 'models.vision_base_url' registered:",
          "models.vision_base_url" in keys)
    print("[key mca_vision uses] VISION_BASE_URL_KEY =",
          __import__("services.mca_vision", fromlist=["x"]).VISION_BASE_URL_KEY)

    hot.set_config_cache(FakeCache())
    from services import mca_vision
    route = mca_vision.resolve_route()
    print("[route] source          =", route.source)
    print("[route] base_url        =", route.base_url)
    print("[route] model           =", route.model)
    print("[route] api_type        =", route.api_type)
    print("[route] api_key_present =", route.api_key_present)
    key = mca_vision._api_key_for(route)
    print("[key] sent key == VISION key:", h(key) == h(FAKE["keys.vision_api_key"]))
    print("[key] sent key == MAIN key  :", h(key) == h(FAKE["keys.llm_api_key"]))
    print("[url] probe url      =",
          route.base_url.rstrip("/") + "/chat/completions")

    print("--- сценарий: base_url сохранён как полный путь ---")
    FAKE["models.vision_api_base_url"] = \
        "https://openrouter.ai/api/v1/chat/completions"
    r2 = mca_vision.resolve_route()
    print("[url2] ->", r2.base_url.rstrip("/") + "/chat/completions")

    print("--- сценарий: dedicated endpoint БЕЗ vision-ключа ---")
    FAKE["models.vision_api_base_url"] = "https://third.party/v1"
    FAKE["keys.vision_api_key"] = ""
    r3 = mca_vision.resolve_route()
    k3 = mca_vision._api_key_for(r3)
    print("[route3] source =", r3.source, "| key_present =", r3.api_key_present)
    print("[key3] fallback на MAIN ключ:", h(k3) == h(FAKE["keys.llm_api_key"]))
    print("[scenario] analyze_image_bytes пустит запрос на",
          "https://third.party/v1" if k3 else "ошибка конфигурации")


if __name__ == "__main__":
    main()
