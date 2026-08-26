"""Epic 79 (T-584, Section 80, D293/D294) — экспорт Netscape-cookies
для yt-dlp / transcript-api через существующий env YOUTUBE_COOKIES_FILE.

Основной режим B (--mode playwright): Playwright persistent_context
(headless Chromium) заходит на лёгкую страницу youtube.com/robots.txt,
собирает context.cookies() и конвертирует их в Netscape-формат.
Вспомогательный режим A (--mode browser): best-effort через yt-dlp
--cookies-from-browser; ненадёжен на Chrome 127+ (App-Bound Encryption).

Запуск:
    python -m tools.cookies_export --mode playwright \
        --profile chrome-profile --out media/srv_cookies.txt

R17: значения кукис НИКОГДА не логируются (имена — можно).
"""
import argparse
import logging
import os
import subprocess
import sys

logger = logging.getLogger("tools.cookies_export")

NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
YOUTUBE_ROBOTS_URL = "https://www.youtube.com/robots.txt"
_PAGE_TIMEOUT_MS = 60_000
_MODE_A_TIMEOUT_SECONDS = 180.0

# D294: валидация результата режима A — хотя бы одна не-комментарийная
# строка с доменом .youtube.com/.google.com
_VALID_DOMAIN_MARKERS = (".youtube.com", ".google.com")


def cookie_to_netscape(cookie: dict) -> str:
    """Playwright-cookie dict → строка Netscape-формата (7 таб-полей):
    domain<TAB>include_subdomains<TAB>path<TAB>secure<TAB>expires<TAB>name<TAB>value.
    Session-cookie (expires == -1) → expires=0."""
    domain = cookie.get("domain", "")
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    path = cookie.get("path", "/")
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    expires = cookie.get("expires", -1)
    expires_field = "0" if expires == -1 or expires is None else str(int(expires))
    return "\t".join([
        domain, include_subdomains, path, secure,
        expires_field, str(cookie.get("name", "")), str(cookie.get("value", "")),
    ])


def convert_cookies(cookies) -> list[str]:
    """Список Playwright-кукис → строки файла (заголовок + по строке на кукису)."""
    lines = [NETSCAPE_HEADER]
    for cookie in cookies:
        lines.append(cookie_to_netscape(cookie))
    return lines


def _write_out(out: str, cookies) -> None:
    # Секреты (auth Google) внутри → файл создаётся СРАЗУ с 0o600
    # (os.open mode), чтобы не было окна «umask-права + содержимое» до chmod.
    # Финальный os.chmod — страховка на платформах, где mode у os.open
    # аппроксимируется (Windows).
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for line in convert_cookies(cookies):
            f.write(line + "\n")
    os.chmod(out, 0o600)


def export_playwright(profile: str, out: str) -> int:
    """Режим B (основной, D293). Возвращает exit code (0 — успех)."""
    from playwright.sync_api import sync_playwright

    logger.info("playwright export started | profile=%r | out=%r",
                os.path.basename(profile), out)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile, headless=True)
            try:
                page = context.new_page()
                page.goto(YOUTUBE_ROBOTS_URL, timeout=_PAGE_TIMEOUT_MS)
                cookies = context.cookies()
            finally:
                context.close()
    except Exception as exc:
        logger.error("playwright export failed | error=%s", exc)
        return 1
    _write_out(out, cookies)
    # R17: имена кукис можно, значения НЕТ
    logger.info("playwright export done | count=%d | names=%s",
                len(cookies), sorted(c["name"] for c in cookies))
    return 0


def build_mode_a_command(profile: str, out: str) -> list[str]:
    """D294: команда экспорта режима A (yt-dlp пишет merge browser-jar в out)."""
    return [
        sys.executable, "-m", "yt_dlp",
        "--cookies-from-browser", f"chrome:{profile}",
        "--cookies", out,
        "--skip-download", YOUTUBE_ROBOTS_URL,
    ]


def _validate_netscape_file(out: str) -> bool:
    """Файл существует и содержит ≥1 не-комментарийную строку с
    .youtube.com/.google.com (D294)."""
    if not os.path.isfile(out):
        return False
    try:
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                low = stripped.lower()
                if any(marker in low for marker in _VALID_DOMAIN_MARKERS):
                    return True
    except OSError:
        return False
    return False


def export_browser(profile: str, out: str) -> int:
    """Режим A (вспомогательный best-effort, D294). Возвращает exit code."""
    cmd = build_mode_a_command(profile, out)
    logger.info("browser-mode export started (yt-dlp subprocess)")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_MODE_A_TIMEOUT_SECONDS)
    except FileNotFoundError:
        logger.error("yt_dlp is not available in this environment "
                     "(python -m yt_dlp failed to start)")
        return 2
    except subprocess.TimeoutExpired:
        logger.error("browser-mode export timed out after %.0fs",
                     _MODE_A_TIMEOUT_SECONDS)
        return 3
    if proc.returncode != 0 or not _validate_netscape_file(out):
        logger.error("browser-mode export failed (rc=%s, valid_file=%s) — "
                     "use --mode playwright instead",
                     proc.returncode, _validate_netscape_file(out))
        return 4
    logger.info("browser-mode export done")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.cookies_export",
        description="Экспорт Netscape-cookies YouTube для "
                    "YOUTUBE_COOKIES_FILE (Epic 79, Section 80).",
    )
    parser.add_argument(
        "--mode", choices=("playwright", "browser"), default="playwright",
        help="playwright = основной режим B (D293); "
             "browser = вспомогательный режим A через yt-dlp (best-effort, D294)")
    parser.add_argument("--profile", required=True,
                        help="путь к chrome-profile (user_data_dir)")
    parser.add_argument("--out", required=True,
                        help="путь выходного Netscape cookies-файла")
    args = parser.parse_args(argv)

    profile = os.path.abspath(args.profile)
    if not os.path.isdir(profile):
        print(f"error: profile directory not found: {profile}",
              file=sys.stderr)
        return 2

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if args.mode == "browser":
        return export_browser(profile, args.out)
    return export_playwright(profile, args.out)


if __name__ == "__main__":
    sys.exit(main())
