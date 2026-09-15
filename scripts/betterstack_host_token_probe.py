"""F1/T-1704 (ADR-1018-1 D8) — диагностический «curl-матрикс» BetterStack
host × token. Запускается ВРУЧНУЮ до/после правки; в тестах реальные сетевые
запросы НЕ выполняются (мок).

Матрикс разводит две причины 401:
    {US, EU} × {Source Token, public key из SENTRY_DSN}
Ожидание: 200 только на (US × Source Token).

R17: вывод МАСКИРОВАННЫЙ — печатаются только HTTP-код и маскированные
идентификаторы (host keep=6, token keep=0/len). Полные секреты не выводятся.

Запуск (bash, репо-корень):
    BETTERSTACK_HOST=... LOGTAIL_SOURCE_TOKEN=... SENTRY_DSN=... \
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

from services.betterstack_handler import extract_sentry_public_key  # noqa: E402

EU_HOST = "in.logs.betterstack.com"


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


def build_matrix(us_host: str, source_token: str,
                 sentry_dsn: str | None) -> list[dict]:
    """4 комбинации {US, EU} × {Source Token, Sentry public key}."""
    pubkey = extract_sentry_public_key(sentry_dsn)
    rows = [
        ("US × Source Token", us_host, source_token),
        ("US × Sentry public key", us_host, pubkey),
        ("EU × Source Token", EU_HOST, source_token),
        ("EU × Sentry public key", EU_HOST, pubkey),
    ]
    return [{"label": label, "host": host, "token": token}
            for label, host, token in rows]


def probe(url: str, timeout: float = 10.0) -> int:
    """POST одного пробного фрейма; возвращает HTTP-код (сеть → -1)."""
    payload = json.dumps([{
        "dt": "2026-09-15T00:00:00+00:00",
        "level": "info", "severity": 2, "message": "betterstack probe",
    }]).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "adminbot/probe-v1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return -1


def format_row(row: dict, code: int) -> str:
    """R17-safe строка отчёта (без полного токена/URL)."""
    return (f"{row['label']:<26} | host={mask_host(row['host'])} | "
            f"token={mask(row['token'])} | http={code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BetterStack host×token probe")
    parser.add_argument("--dry-run", action="store_true",
                        help="напечатать матрицу без сетевых запросов")
    args = parser.parse_args()

    us_host = (os.getenv("BETTERSTACK_HOST") or "").strip()
    token = os.getenv("LOGTAIL_SOURCE_TOKEN")
    dsn = os.getenv("SENTRY_DSN")
    if not us_host or not token:
        print("[probe] skip: BETTERSTACK_HOST/LOGTAIL_SOURCE_TOKEN не заданы")
        return 2
    rows = build_matrix(us_host, token, dsn)
    for row in rows:
        if not row["token"]:
            print(format_row(row, -2))          # нет токена/ключа — пропуск
            continue
        if args.dry_run:
            print(format_row(row, -3))
            continue
        url = f"https://{row['host']}/{row['token']}"
        print(format_row(row, probe(url)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
