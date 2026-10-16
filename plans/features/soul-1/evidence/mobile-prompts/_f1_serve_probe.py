# -*- coding: utf-8 -*-
"""Долгоживущий сервер для НЕзависимой проверки F1 браузерами через MCP
(Playwright MCP + Browser Use): те же реальные `web/**` и тот же реальный
payload, что у `_f1_empty_tab_probe.py`.

  * http://127.0.0.1:8871/web/index.html  — полный payload `REGISTRY`;
  * http://127.0.0.1:8872/web/index.html  — payload только `category=prompts`
    (сценарий пустой вкладки `#/ai/smart-cache`).

Запуск: .venv\\Scripts\\python.exe <этот файл>   (Ctrl+C — стоп)
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _f1_empty_tab_probe import (  # noqa: E402
    FULL, RESTRICTED, PORT_FULL, PORT_RESTRICTED, _serve)

_serve(PORT_FULL, FULL)
_serve(PORT_RESTRICTED, RESTRICTED)
print("[f1-serve] full=%d restricted=%d"
      % (PORT_FULL, PORT_RESTRICTED), flush=True)
try:
    while True:
        time.sleep(5)
except KeyboardInterrupt:  # pragma: no cover
    pass
