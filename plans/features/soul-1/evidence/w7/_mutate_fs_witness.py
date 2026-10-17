"""W7 / SOUL-12: falsification witness для новых сторожей.

Мутирует ИСХОДНИК, прогоняет node-сторож и откатывает файл из бэкапа.
Ничего в репозитории не остаётся изменённым (проверяется sha до/после).

Запуск: .venv/Scripts/python.exe <scratch>/w7/mutate_fs.py
"""
import hashlib
import os
import subprocess
import sys

REPO = r"C:\Code\Python\adminbot"
TEST = "tests/js/asap8_w2_fullscreen_policy_test.js"

MUTATIONS = [
    ("M1: reasonText не отдаётся в state() (SOUL-12.1)",
     "web/static/fullscreen-policy.js",
     "      reason: _state.reason,\n      reasonText: _state.reasonText,",
     "      reason: _state.reason,"),
    ("M2: explain() без человеческого текста (голый код)",
     "web/static/fullscreen-policy.js",
     "      text: REASON_TEXT[code] || ('Полноэкранный режим недоступен (' + code + ').'),",
     "      text: '',"),
    ("M3: nextStep выброшен (нет пути запуска)",
     "web/static/fullscreen-policy.js",
     "      nextStep: REASON_NEXT_STEP[code] || ''",
     "      nextStep: ''"),
    ("M4: стрип объяснения в UI безусловный (вне TG навязывается)",
     "web/index.html",
     "v-if=\"me && fsSlot === 'hidden' && fsReason && fsReason !== 'no_telegram_context'\"",
     "v-if=\"true\""),
    ("M5: стрип диагностики удалён из UI",
     "web/index.html",
     "class=\"text-xs px-3 py-1\" data-fs-diagnostics",
     "class=\"text-xs px-3 py-1\""),
    ("M6: initData утекает в diagnostics()",
     "web/static/fullscreen-policy.js",
     "      hasInitData: hasInitData,",
     "      hasInitData: hasInitData,\n      initDataLeak: (wa && wa.initData) || null,"),
    ("M7: clickResult не отражает действия (всегда 'never')",
     "web/static/fullscreen-policy.js",
     "    _clickResult = 'request_sent';",
     "    _clickResult = 'never';"),
    ("M8: DOUBLE_INIT не фиксируется",
     "web/static/fullscreen-policy.js",
     "    if (_initCount > 1) _pushWarning('DOUBLE_INIT');",
     "    if (false) _pushWarning('DOUBLE_INIT');"),
    ("M9: tdesktop снова без инструкции BotFather",
     "web/static/fullscreen-policy.js",
     "      'или «Compact» вместо «Fullscreen». Бот не может переключить Launch '",
     "      'Варианты уточняются. Бот не может переключить Launch '"),
    ("M10: app.js шлёт стрип-тост и вне Telegram (навязчиво)",
     "web/app.js",
     "              this.fsReason !== 'no_telegram_context') {",
     "              true) {"),
]


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    before = {}
    for rel in ("web/static/fullscreen-policy.js", "web/index.html", TEST):
        before[rel] = sha(os.path.join(REPO, rel))
    results = []
    for name, rel, old, new in MUTATIONS:
        path = os.path.join(REPO, rel)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            src = fh.read()
        if old not in src:
            results.append((name, "SKIP (anchor not found)"))
            print("[mut] %-60s SKIP" % name)
            continue
        backup = src
        mutated = src.replace(old, new, 1)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(mutated)
        try:
            proc = subprocess.run(["node", TEST], cwd=REPO,
                                  capture_output=True, text=True, timeout=180)
            killed = proc.returncode != 0
            results.append((name, "KILLED" if killed else "SURVIVED"))
            print("[mut] %-60s %s" % (name, "KILLED" if killed else "SURVIVED"))
            if not killed:
                print("      stdout tail: %s" % (proc.stdout or "")[-300:])
        finally:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(backup)
    after = {}
    for rel in before:
        after[rel] = sha(os.path.join(REPO, rel))
    restored = all(before[k] == after[k] for k in before)
    survivors = [r for r in results if r[1] != "KILLED"]
    print("[mut] mutations=%d killed=%d survived_or_skipped=%d restored=%s"
          % (len(results), len(results) - len(survivors), len(survivors), restored))
    for n, s in survivors:
        print("      %s -> %s" % (n, s))
    return 0 if restored and not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
