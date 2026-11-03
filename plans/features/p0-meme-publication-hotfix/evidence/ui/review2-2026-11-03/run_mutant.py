# -*- coding: utf-8 -*-
"""Reviewer driver: run ONLY run_chat_switch from a (possibly mutated) e2e copy."""
import importlib.util, sys, os
NAME = sys.argv[1]
PORT = int(sys.argv[2])
spec = importlib.util.spec_from_file_location(NAME, os.path.join(os.path.dirname(os.path.abspath(__file__)), NAME + ".py"))
mod = importlib.util.module_from_spec(spec)
sys.modules[NAME] = mod
spec.loader.exec_module(mod)
mod.PORT = PORT
mod.BASE = "http://127.0.0.1:%d" % PORT
httpd = mod.serve_static(PORT, os.path.join(mod.REPO, "web"))
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            mod.run_chat_switch(browser, 1536, 960, "rev", "")
        finally:
            browser.close()
finally:
    httpd.shutdown()
print("FAILURES=%d" % len(mod.failures))
for f in mod.failures:
    print("  - " + f)
sys.exit(0)
