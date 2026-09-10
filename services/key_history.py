"""OD12/OD19 (tma-relume-redesign, T-1140/T-1148) — история доступности ключей.

Быстрый слой — in-memory ring (`deque(maxlen=288)`, 24ч по 5-мин слотам);
персистентный — атомарный JSON-снимок `var/status_key_history.json` (0 новых
PG-DDL, SQLite остаётся v8). Переживает рестарт (загрузка на старте).

🔒 LEAK-SAFETY (OD19) — обязательный верифицируемый контракт:
  * allowlist сэмпла: ``ts``, ``ok``, ``http_status``; провайдер:
    ``module_id``, ``provider``, ``model``; шапка: ``version``, ``generated_at``.
  * deny-list (никогда не пишем): сырые API-ключи/токены (`sk-…`/`gsk_…`/
    `Bearer …`), ``Authorization``, cookie/session, ``initData``, тела
    запросов/ответов LLM, ``base_url`` с credentials (``user:pass@``), ``last4``.
  * R17: по ключу хранится только факт доступности (``ok``/``http_status``).
  * права: файл 0o600 (POSIX) / каталог 0o700; на Windows — best-effort.
  * атомарность: tmp + ``os.replace``; повреждение/отсутствие → пусто + WARNING
    (fail-open, без падения).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_SAMPLES = 288                 # 24ч / 5 мин
SAMPLE_BUCKET_SECONDS = 300       # 5 мин
ENV_PATH = "STATUS_KEY_HISTORY_FILE"
DEFAULT_PATH = os.path.join("var", "status_key_history.json")

# Единственные поля, допустимые в файле/API (OD19 allowlist).
_ALLOWED_SAMPLE_KEYS = ("ts", "ok", "http_status")
_FORBIDDEN_SUBSTRINGS = (
    "sk-", "gsk_", "bearer", "authorization", "api_key", "apikey",
    "initdata", "cookie", "password", "secret", "token",
)


def history_path() -> Path:
    """Путь снимка (env-override для тестов: STATUS_KEY_HISTORY_FILE)."""
    return Path(os.getenv(ENV_PATH, DEFAULT_PATH))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_sample(sample: dict) -> dict:
    """Строгий allowlist сэмпла: ts/ok/http_status — и НИЧЕГО больше."""
    ts = sample.get("ts")
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        ts = int(datetime.now(timezone.utc).timestamp())
    http_status = sample.get("http_status")
    if http_status is not None:
        try:
            http_status = int(http_status)
        except (TypeError, ValueError):
            http_status = None
    return {"ts": ts, "ok": bool(sample.get("ok")),
            "http_status": http_status}


def _secure_file(path: Path) -> None:
    """Ограниченные права файла (0o600). Windows — best-effort (no-op)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _secure_dir(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


class KeyHistory:
    """Ring + атомарный снимок. Ленивая загрузка (без I/O на import)."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self._path = Path(path) if path is not None else history_path()
        self._ring: dict[str, deque] = {}
        self._meta: dict[str, dict] = {}   # module_id → {module_title, provider, model}
        self._loaded = False
        self._last_save = 0.0

    # ── загрузка ──────────────────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for prov in (raw.get("providers") or []):
                module_id = str(prov.get("module_id") or "")
                if not module_id:
                    continue
                self._meta[module_id] = {
                    "module_title": prov.get("module_title") or "",
                    "provider": prov.get("provider") or "",
                    "model": prov.get("model") or "",
                }
                ring: deque = deque(maxlen=MAX_SAMPLES)
                for s in (prov.get("samples") or []):
                    ring.append(_clean_sample(s))
                self._ring[module_id] = ring
        except Exception:
            logger.warning(
                "[key_history] snapshot unreadable — start empty (fail-open)",
                exc_info=True)
            self._ring = {}
            self._meta = {}

    # ── запись ────────────────────────────────────────────────────────────
    def record(self, module_id: str, provider: str, model: str, ok: bool,
               http_status: int | None, ts: int | None = None,
               module_title: str = "") -> None:
        """UPSERT сэмпла в 5-мин слот (редкая запись: 1/5 мин на модуль)."""
        self._ensure_loaded()
        module_id = str(module_id or "")
        if not module_id:
            return
        if ts is None:
            ts = int(datetime.now(timezone.utc).timestamp())
        ts = int(ts)
        slot = (ts // SAMPLE_BUCKET_SECONDS) * SAMPLE_BUCKET_SECONDS
        self._meta[module_id] = {
            "module_title": module_title or
            self._meta.get(module_id, {}).get("module_title", ""),
            "provider": str(provider or ""),
            "model": str(model or ""),
        }
        ring = self._ring.setdefault(module_id, deque(maxlen=MAX_SAMPLES))
        sample = {"ts": slot, "ok": bool(ok), "http_status": http_status}
        if ring and int(ring[-1]["ts"]) == slot:
            ring[-1] = _clean_sample(sample)   # upsert в тот же слот
        else:
            ring.append(_clean_sample(sample))

    def save(self) -> bool:
        """Атомарный снимок allowlist-полей. True — записан."""
        self._ensure_loaded()
        payload = self._file_payload()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _secure_dir(self._path.parent)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".keyhist-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False,
                              separators=(",", ":"))
                os.replace(tmp, self._path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            _secure_file(self._path)
            return True
        except Exception:
            logger.warning("[key_history] save failed (fail-open)",
                           exc_info=True)
            return False

    # ── выдача ────────────────────────────────────────────────────────────
    def _file_payload(self) -> dict:
        providers = []
        for module_id, ring in self._ring.items():
            meta = self._meta.get(module_id, {})
            providers.append({
                "module_id": module_id,
                "provider": meta.get("provider", ""),
                "model": meta.get("model", ""),
                "samples": [
                    {k: s.get(k) for k in _ALLOWED_SAMPLE_KEYS}
                    for s in ring
                ],
            })
        providers.sort(key=lambda p: p["module_id"])
        return {"version": SCHEMA_VERSION, "generated_at": _now_iso(),
                "providers": providers}

    def api_payload(self) -> dict:
        """Ответ эндпоинта: allowlist + module_title (публичное имя модуля)."""
        self._ensure_loaded()
        payload = self._file_payload()
        for prov in payload["providers"]:
            meta = self._meta.get(prov["module_id"], {})
            prov["module_title"] = meta.get("module_title", "") or prov["module_id"]
        return payload

    def reset(self) -> None:
        """Тесты/диагностика: очистить ring (файл не трогается)."""
        self._ring = {}
        self._meta = {}
        self._loaded = True

    def maybe_save(self, min_interval: float = SAMPLE_BUCKET_SECONDS) -> bool:
        """Снимок не чаще раза в 5 мин (редкая запись, атомарно)."""
        import time as _time
        now = _time.monotonic()
        if now - self._last_save < min_interval and self._last_save > 0:
            return False
        self._last_save = now
        return self.save()


def has_forbidden_content(blob: str) -> bool:
    """Маркер leak-safety (T-1148): True — найдено запрещённое содержимое.

    НЕ используется в runtime-записи (allowlist уже отсекает), а как
    верифицируемый guard для тестов/QA по содержимому файла.
    """
    low = (blob or "").lower()
    return any(pat in low for pat in _FORBIDDEN_SUBSTRINGS)
