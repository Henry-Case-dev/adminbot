"""Runner зондов: пишет вывод зонда в UTF-8 файл (без PowerShell-перекодировки).

Запуск: python _fix_run.py <probe.py> <out.txt>
"""
from __future__ import annotations

import contextlib
import io
import runpy
import sys

target, out_path = sys.argv[1], sys.argv[2]
buf = io.StringIO()
code = 0
with contextlib.redirect_stdout(buf):
    sys.argv = [target]
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:      # probes завершаются sys.exit(...)
        code = int(exc.code or 0)
text = buf.getvalue()
with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
sys.stdout.buffer.write(text.encode("utf-8", "replace"))
sys.stdout.buffer.flush()
sys.exit(code)
