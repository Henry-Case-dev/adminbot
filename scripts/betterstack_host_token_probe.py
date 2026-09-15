"""F1/T-1779 (ADR-1019-1 D6, AMEND ADR-1018-1 D8) — диагностический
«curl-матрикс» контракта ingest BetterStack.

Раунд 10.19: проверяется КОНТРАКТ запроса, а не «верность» токена. Матрикс:
    {US, EU} × {токен-в-пути, Bearer}
Ожидание: 202 (успех) только на (US × Bearer). Прежний path-token
(`POST https://{host}/{token}`) на unified US даёт 401 — это и есть root cause.

R17: вывод МАСКИРОВАННЫЙ — печатаются только HTTP-код и маскированные
идентификаторы (host keep=6, token keep=0). Полные секреты не выводятся.
Запросы идут через opener с `_NoRedirectHandler` (D-09): 3xx НЕ фоллоуится —
токен не форвардится на чужой Location.

Запуск (bash, репо-корень):
    BETTERSTACK_HOST=... LOGTAIL_SOURCE_TOKEN=... \
        python scripts/betterstack_host_token_probe.py
Флаг --dry-run печатает матрицу без сети (используется тестами).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

EU_HOST = "in.logs.betterstack.com"

PATH_TOKEN = "path"
BEARER = "bearer"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """D-09 (ревью Батча A, R17-консистентность с D-01): редиректы запрещены.

    Дефолтный `urlopen` на 3xx повторил бы запрос на произвольный `Location`,
    форвардя `Authorization: Bearer` (утечка токена) и превращая POST в GET.
    Возврат `None` → базовый обработчик поднимает `HTTPError` 3xx (код виден
    в отчёте, токен никуда не уходит)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Единственный opener probe: те же дефолтные обработчики, но без follow
# редиректов (D-09). Собирается один раз, сети на импорте нет.
_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _urlopen(request, timeout):
    """Точка сетевого вызова (`_OPENER.open`); отдельная обёртка ради
    подмены в тестах (R17: 3xx не фоллоуится — токен не форвардится)."""
    return _OPENER.open(request, timeout=timeout)


def mask(value: str, keep: int = 0) -> str:
    """Маска секрета: оставляем не более `keep` первых символов, остальное *.
    Пусто → '<empty>'. keep=0 → видны только `*`; их КОЛИЧЕСТВО равно длине
    секрета (длина раскрывается как число `*`, само значение — нет)."""
    text = "" if value is None else str(value)
    if not text:
        return "<empty>"
    keep = max(0, min(int(keep), max(0, len(text) - 1)))
    return text[:keep] + "*" * (len(text) - keep)


def mask_host(host: str) -> str:
    """Хост не секрет, но для отчёта маскируем середину (первые 6 символов)."""
    return mask(host, keep=6)


def build_matrix(us_host: str, source_token: str) -> list[dict]:
    """4 комбинации {US, EU} × {path-token, Bearer} (ADR-1019-1 D6)."""
    rows = [
        ("US × path-token", us_host, source_token, PATH_TOKEN),
        ("US × Bearer", us_host, source_token, BEARER),
        ("EU × path-token", EU_HOST, source_token, PATH_TOKEN),
        ("EU × Bearer", EU_HOST, source_token, BEARER),
    ]
    return [{"label": label, "host": host, "token": token, "mode": mode}
            for label, host, token, mode in rows]


def probe(host: str, token: str, mode: str = BEARER,
          timeout: float = 10.0) -> int:
    """POST одного пробного фрейма; возвращает HTTP-код (сеть → -1).

    mode='bearer' → POST https://{host} + Authorization: Bearer {token};
    mode='path'   → POST https://{host}/{token} (для сравнения/диагностики)."""
    payload = json.dumps([{
        "dt": "2026-09-15T00:00:00+00:00",
        "level": "info", "severity": 2, "message": "betterstack probe",
    }]).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "User-Agent": "adminbot/probe-v1"}
    if mode == PATH_TOKEN:
        url = f"https://{host}/{token}"
    else:
        url = f"https://{host}"
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=payload, method="POST", headers=headers)
    try:
        with _urlopen(request, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return -1


def format_row(row: dict, code: int) -> str:
    """R17-safe строка отчёта (без полного токена/URL)."""
    return (f"{row['label']:<18} | host={mask_host(row['host'])} | "
            f"token={mask(row['token'])} | http={code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BetterStack ingest-contract probe")
    parser.add_argument("--dry-run", action="store_true",
                        help="напечатать матрицу без сетевых запросов")
    args = parser.parse_args()

    us_host = (os.getenv("BETTERSTACK_HOST") or "").strip()
    token = os.getenv("LOGTAIL_SOURCE_TOKEN")
    if not us_host or not token:
        print("[probe] skip: BETTERSTACK_HOST/LOGTAIL_SOURCE_TOKEN не заданы")
        return 2
    rows = build_matrix(us_host, token)
    for row in rows:
        if not row["token"]:
            print(format_row(row, -2))          # нет токена — пропуск
            continue
        if args.dry_run:
            print(format_row(row, -3))
            continue
        print(format_row(row, probe(row["host"], row["token"], row["mode"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
