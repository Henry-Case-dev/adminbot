# -*- coding: utf-8 -*-
"""Одноразовый скрипт переиздания F8-фикстур (ASAP-3.1, прецедент ASAP-3 §6)."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 484
fx["counts"]["delta"] = 73
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
fx_path.write_text(json.dumps(fx, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb_path.write_text(json.dumps(cb, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
print("catalog_baseline keys:", len(cb["registry_keys"]))

# Хэш routes.py для константы ROUTES_SHA256_F11 в тесте.
print("ROUTES_SHA256_F11 =", '"%s"' % sha("web/api/routes.py"))
