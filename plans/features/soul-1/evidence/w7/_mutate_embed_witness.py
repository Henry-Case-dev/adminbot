"""W7 / SOUL-13.4: falsification witness для primary-slot сторожей.

Мутирует services/embedding_control_plane.py, гоняет свой pytest-файл,
восстанавливает файл из бэкапа (sha до/после должен совпасть).

Запуск: .venv/Scripts/python.exe <scratch>/w7/mutate_embed.py
"""
import hashlib
import os
import subprocess
import sys

REPO = r"C:\Code\Python\adminbot"
SRC = os.path.join(REPO, "services", "embedding_control_plane.py")
TEST = "tests/test_soul1_w7_embedding_primary_slot.py"

MUT = [
    ("M1: primary_present всегда True (пустой слот не виден)",
     "            \"primary_present\": bool(primary),",
     "            \"primary_present\": True,"),
    ("M2: primary_source всегда 'hot' (env не различается)",
     "    primary_source = primary[0].key_source if primary else \"absent\"",
     "    primary_source = \"hot\""),
    ("M3: WARN о пустом primary отключён",
     "    if diagnosis.get(\"primary_present\"):\n        return False                      # слот есть (hot или env) — не дефект",
     "    return False"),
    ("M4: значение ключа утекает в credential_rows (R17)",
     "        \"key_source\": c.key_source,",
     "        \"key_source\": c.key_source,\n        \"api_key\": c.api_key,"),
    ("M5: env перекрывает hot (приоритет сломаn)",
     "    hot_val = _hot_get(hot_key, _ABSENT)",
     "    hot_val = _ABSENT"),
    ("M6: primary_warn всегда False (панель молчит о деградации)",
     "        \"primary_warn\": primary_state == \"primary_absent\",",
     "        \"primary_warn\": False,"),
    ("M7: rate-limit WARN снят (флуд вместо ≤1/10 мин)",
     "    now = time.monotonic()\n    if now - _last_primary_warn < _ROTATION_WARN_COOLDOWN_S:\n        return False\n    _last_primary_warn = now\n    logger.warning(\n        \"embedding pool primary=absent",
     "    logger.warning(\n        \"embedding pool primary=absent"),
    ("M8: hint без конкретной настройки (непонятное состояние)",
     "    \"primary_hint\": _PRIMARY_HINT_RU if primary_state == \"primary_absent\" else \"\",",
     "    \"primary_hint\": \"\",",),
]


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    before = sha(SRC)
    results = []
    for name, old, new in MUT:
        with open(SRC, "r", encoding="utf-8", newline="") as fh:
            src = fh.read()
        if old not in src:
            print("[mut] %-58s SKIP (anchor)" % name)
            results.append((name, "SKIP"))
            continue
        try:
            with open(SRC, "w", encoding="utf-8", newline="") as fh:
                fh.write(src.replace(old, new, 1))
            proc = subprocess.run(
                [os.path.join(REPO, ".venv", "Scripts", "python.exe"),
                 "-m", "pytest", TEST, "-q", "--timeout=120", "-x"],
                cwd=REPO, capture_output=True, text=True, timeout=300)
            killed = proc.returncode != 0
            print("[mut] %-58s %s" % (name, "KILLED" if killed else "SURVIVED"))
            results.append((name, "KILLED" if killed else "SURVIVED"))
        finally:
            with open(SRC, "w", encoding="utf-8", newline="") as fh:
                fh.write(src)
    after = sha(SRC)
    bad = [r for r in results if r[1] != "KILLED"]
    print("[mut] mutations=%d killed=%d bad=%d restored=%s"
          % (len(results), len(results) - len(bad), len(bad), before == after))
    for n, s in bad:
        print("      %s -> %s" % (n, s))
    return 0 if before == after and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
