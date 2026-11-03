# -*- coding: utf-8 -*-
"""Осознанное переиздание F11-пина `ROUTES_SHA256_F11` для
MEME-PIPELINE-REFACTOR-01 P4 (`MEME-IIC-DIAG-UI`, 03.11.2026, L-F11S-1).

Почему переиздание вообще нужно (и почему оно МИНИМАЛЬНОе):

* P4 снимает совместимые алиасы `length_limit.value` / `prefix_chars` /
  `summary_target` в СУЩЕСТВУЮЩЕМ GET/POST `/api/initiative/meme-settings`
  (`_meme_settings_payload`) — карточка переведена на канонические имена
  `MemeBudget` (`ceiling`/`template_chars`/`joke_budget`). Это правка
  содержимого `web/api/routes.py`, поэтому sha256 файла обязан измениться:
  пинить старый байт-пин невозможно без отката принятого поведения
  (`tests/test_meme_pipeline_api.py` прямо проверяет отсутствие алиасов).
* Новый маршрут `GET /api/initiative/mechanism-diagnostics` в routes.py НЕ
  добавляется: он живёт в отдельном файле-зоне
  `web/api/mechanism_diagnostics.py` (конвенция зон: stories/oversight/
  speech; routes-инвентарь F8 — это tripwire против новых маршрутов в
  routes.py). Поэтому Δ routes = 0, набор путей `f8_baseline.json` НЕ
  меняется, и пин сохраняет свою ловящую силу.

Что делает инструмент (идемпотентно):

1. проставляет digest sha256(`web/api/routes.py`) в канонический пин
   `tests/test_round1025_f8_registry.py` и в синхронную копию в
   `tests/test_mca23_planned_vs_actual.py` (остальные пины импортируют
   канон — единый источник истины);
2. дописывает rationale-блок в оба пина (один раз);
3. обновляет provenance `sha256["web/api/routes.py"]` и `superseded_by` в
   `tests/fixtures/round1025/f8_baseline.json` (routes-список не меняется);
4. проверяет инвариант «Δ routes=0»: набор путей routes.py равен
   `f8_baseline.json`; иначе — FAIL (значит кто-то добавил маршрут в
   routes.py, это не наша санкция).

Запуск:
  python tools/_meme_p4_reissue_f8.py            # переиздать
  python tools/_meme_p4_reissue_f8.py --check    # только проверить (EXIT 0/1)
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANON_PIN = ROOT / "tests/test_round1025_f8_registry.py"
MIRROR_PIN = ROOT / "tests/test_mca23_planned_vs_actual.py"
FIXTURE = ROOT / "tests/fixtures/round1025/f8_baseline.json"

_ROUTES_REL = "web/api/routes.py"
_ROUTE_RE = r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"'
_DIGEST_LINE = re.compile(r'^\s*"([0-9a-f]{64})"\)\s*$')
_MARKER = "MEME-PIPELINE-REFactor-01 P4"

_NOTE_LINES = (
    "    # MEME-PIPELINE-REFactor-01 P4 (`MEME-IIC-DIAG-UI`, 03.11.2026,",
    "    # L-F11S-1 conscious requalification): контентная Δ в СУЩЕСТВУЮЩИХ",
    "    # GET/POST /api/initiative/meme-settings — сняты совместимые алиасы",
    "    # `length_limit.value`/`prefix_chars`/`summary_target` (карточка",
    "    # переведена на канонические имена MemeBudget: ceiling/template_chars/",
    "    # joke_budget; одно число — одно имя). Новый маршрут",
    "    # GET /api/initiative/mechanism-diagnostics добавлен НЕ здесь, а в",
    "    # отдельном файле-зоне web/api/mechanism_diagnostics.py, поэтому",
    "    # Δ routes=0 и routes-инвентарь f8_baseline не меняется. RBAC/",
    "    # маскировка/DDL не менялись. Хэш переутверждён осознанно (L-F11S-1).",
)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def routes_in_file() -> list:
    txt = (ROOT / _ROUTES_REL).read_text(encoding="utf-8")
    return sorted(set(re.findall(_ROUTE_RE, txt)))


def _reissue_pin(path: Path, digest: str) -> bool:
    """Проставить digest и rationale в один пин-файл. True — были изменения."""
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("ROUTES_SHA256_F11 = ("))
    stop = next(i for i in range(start, len(lines))
                if _DIGEST_LINE.match(lines[i].rstrip("\r\n")))
    changed = False
    if not any(_MARKER in ln for ln in lines[start:stop]):
        eol = "\r\n" if lines[stop].endswith("\r\n") else "\n"
        block = [ln + eol for ln in _NOTE_LINES]
        lines[stop:stop] = block
        stop += len(block)
        changed = True
    old = lines[stop].rstrip("\r\n")
    head, _, tail = old.partition('"')
    new = old.replace(_DIGEST_LINE.match(old).group(1), digest)
    if new != old:
        eol = "\r\n" if lines[stop].endswith("\r\n") else "\n"
        lines[stop] = new + eol
        changed = True
    if changed:
        path.write_bytes("".join(lines).encode("utf-8"))
    return changed


def _reissue_fixture(digest: str) -> bool:
    raw = FIXTURE.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    changed = False
    if data["sha256"].get(_ROUTES_REL) != digest:
        data["sha256"][_ROUTES_REL] = digest
        changed = True
    note = (
        "; MEME-PIPELINE-REFactor-01 P4 (03.11.2026): в СУЩЕСТВУЮЩИХ GET/POST "
        "/api/initiative/meme-settings сняты совместимые алиасы "
        "length_limit.value/prefix_chars/summary_target (одно число — одно "
        "имя), sha256 routes.py переиздан осознанно (L-F11S-1); новый "
        "маршрут /initiative/mechanism-diagnostics живёт в отдельном "
        "файле-зоне web/api/mechanism_diagnostics.py — Δ routes=0, набор "
        "путей не менялся."
    )
    if _MARKER not in (data.get("superseded_by") or ""):
        data["superseded_by"] = (data.get("superseded_by") or "") + note
        changed = True
    if changed:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if b"\r\n" in raw:
            text = text.replace("\n", "\r\n")
        FIXTURE.write_bytes(
            (text + ("\r\n" if b"\r\n" in raw else "\n")).encode("utf-8"))
    return changed


def _check_pin(path: Path, digest: str) -> str:
    lines = path.read_bytes().decode("utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("ROUTES_SHA256_F11 = ("))
    stop = next(i for i in range(start, len(lines))
                if _DIGEST_LINE.match(lines[i]))
    got = _DIGEST_LINE.match(lines[stop]).group(1)
    if got != digest:
        return f"PIN MISMATCH {path.relative_to(ROOT)}: {got[:12]} != {digest[:12]}"
    if not any(_MARKER in ln for ln in lines[start:stop]):
        return f"RATIONALE MISSING {path.relative_to(ROOT)}"
    return ""


def main(argv) -> int:
    check = "--check" in argv
    digest = sha(_ROUTES_REL)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    routes = routes_in_file()

    problems = []
    # Инвариант санкции: маршрутов в routes.py не прибавилось.
    if routes != fixture["routes"]:
        extra = sorted(set(routes) - set(fixture["routes"]))
        missing = sorted(set(fixture["routes"]) - set(routes))
        problems.append(f"Δ routes != 0 (лишние {extra}, пропали {missing})")

    if check:
        problems += [p for p in (_check_pin(CANON_PIN, digest),
                                 _check_pin(MIRROR_PIN, digest)) if p]
        if fixture["sha256"].get(_ROUTES_REL) != digest:
            problems.append("FIXTURE sha256 routes.py устарел")
        if _MARKER not in (fixture.get("superseded_by") or ""):
            problems.append("FIXTURE superseded_by без rationale P4")
        if problems:
            print("CHECK FAILED")
            for p in problems:
                print(" -", p)
            return 1
        print(f"CHECK OK: routes={len(routes)} (Δ=0), sha256={digest[:12]}")
        return 0

    if problems:
        for p in problems:
            print(" -", p)
        print("REISSUE ABORTED: санкция Δ routes=0 нарушена")
        return 1

    touched = []
    for path in (CANON_PIN, MIRROR_PIN):
        if _reissue_pin(path, digest):
            touched.append(path.relative_to(ROOT).as_posix())
    if _reissue_fixture(digest):
        touched.append(FIXTURE.relative_to(ROOT).as_posix())

    # Проверка, а не «должно было измениться».
    for path in (CANON_PIN, MIRROR_PIN):
        problem = _check_pin(path, digest)
        if problem:
            print("REISSUE FAILED:", problem)
            return 1
    print(f"sha256={digest}")
    print(f"routes={len(routes)} (Δ=0 против f8_baseline)")
    print("изменено:", touched or "ничего (идемпотентно)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
