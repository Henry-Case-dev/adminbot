# -*- coding: utf-8 -*-
"""Persistent local server for Browser Use visual inspection of the MiniApp
prompt library (SOUL-1 lane B-MOBILE). Serves the REAL web/index.html +
REAL `/api/config` payload built from `services.param_catalog.REGISTRY`.

Usage:  .venv\\Scripts\\python <this>.py [port]
Stop:   Ctrl+C (or just close the process; the run is disposable).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import importlib.util  # noqa: E402


def _load_matrix():
    spec = importlib.util.spec_from_file_location(
        "ui_round1025_matrix", os.path.join(REPO, "tools",
                                            "ui_round1025_matrix.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_matrix()
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else (M.PORT + 79)


def build_payload():
    from services import param_catalog as pc
    from services.pg_db import resolve_code_source
    items = []
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        secret = bool(getattr(spec, "secret", False))
        widget = getattr(spec, "widget", "") or ""
        stype = getattr(spec, "type", "str") or "str"
        if secret:
            value = {"configured": True, "last4": "0000"}
        elif spec.code_source:
            value = resolve_code_source(spec.code_source)
        elif widget == "keyvalue":
            value = {}
        elif stype == "bool":
            value = False
        elif stype in ("int", "float"):
            value = 1
        elif widget == "select" and getattr(spec, "select_options", None):
            value = list(spec.select_options)[0]
        else:
            value = ""
        items.append({
            "key": spec.pg_key, "value": value, "category": spec.category,
            "secret": secret, "chat_source": "", "global_value": None,
            "title": getattr(spec, "title_ru", key) or key, "type": stype,
            "updated_at": None, "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "widget": widget,
            "select_options": list(spec.select_options)
            if widget == "select" and getattr(spec, "select_options", None)
            else None,
            "select_labels": list(spec.select_labels)
            if widget == "select" and getattr(spec, "select_labels", None)
            else None,
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": pc.resolve_progressive_level(spec),
            "stage": getattr(spec, "stage", None),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    return {"items": items, "groups": groups}


PAYLOAD = build_payload()
ITEMS = {it["key"]: it for it in PAYLOAD["items"]}


class Handler(M._Handler if hasattr(M, "_Handler") else object):
    pass


class _Api(ThreadingHTTPServer):
    pass


def serve():
    from http.server import BaseHTTPRequestHandler

    class H(M._Handler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0].endswith("/api/config"):
                body = json.dumps({"items": [ITEMS[k] for k in sorted(ITEMS)],
                                   "groups": PAYLOAD["groups"]})
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.path.split("?")[0].endswith("/api/me"):
                data = json.dumps(M.ME_JSON).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            M._Handler.do_GET(self)

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0].endswith("/api/config"):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    body = {}
                n = 0
                for i in (body or {}).get("items") or []:
                    k = i.get("key")
                    if k in ITEMS:
                        ITEMS[k]["value"] = i.get("value")
                        n += 1
                data = json.dumps({"ok": True, "saved": n}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            M._Handler.do_POST(self)

    return H


print("[server] http://127.0.0.1:%d/web/index.html#/ai/prompts" % PORT)
print("[server] payload items=%d" % len(PAYLOAD["items"]))
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), serve())
httpd.serve_forever()
