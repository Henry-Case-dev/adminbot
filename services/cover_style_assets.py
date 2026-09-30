"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D6; spec §3.6/§8/§12) —
durable asset-регистр для Cover Style.

В проекте НЕТ готового durable media/assets storage (есть лишь транзиентный
TTL-шаринг `media_share` и аудит `media_integrity`), поэтому вводится
**новый** регистр: PG-метаданные (`cover_style_assets`, см. `pg_db.DDL_STATEMENTS`)
+ файлы на durable диске (`var/cover_style_assets/`, env `COVER_STYLE_ASSETS_DIR`).

Контракт:
  * stable `asset_id` для seed — детерминированный (`sha256 → "cas_"+hex[:32]`);
  * хранение самого изображения — НЕ в PG (PG хранит метаданные, §12);
  * seed-файлы **копируются**; `extra_images/*` не изменяются/не удаляются
    (R18);
  * дедуп по `sha256 + scope` (partial unique index, `deleted_at IS NULL`).
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Изображения, допустимые к загрузке/импорту (spec §6/§12).
ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def assets_dir() -> Path:
    """Managed-каталог для durable-файлов ассетов (env override допустим)."""
    raw = os.getenv("COVER_STYLE_ASSETS_DIR", "").strip()
    path = Path(raw) if raw else (Path(__file__).resolve().parents[1]
                                  / "var" / "cover_style_assets")
    return path


def asset_id_for(sha256_hex: str) -> str:
    """Стабильный `asset_id` из sha256 (детерминированный для seed, §3.6)."""
    return "cas_" + str(sha256_hex or "").strip().lower()[:32]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for mime, ext in ALLOWED_MIME.items():
        if ext == suffix:
            return mime
    # `.jpeg` — тот же jpeg.
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    return ""


def store_file_bytes(data: bytes, *, filename: str, origin: str = "upload",
                     scope: str = "global", asset_id: str | None = None,
                     disk_path: str | None = None) -> dict | None:
    """Записать байты в managed-файл; вернуть metadata-словарь (без PG).

    None — если тип не поддержан или запись не удалась. Файл кладётся по
    имени `<asset_id><ext>`; существующий НЕ перезаписывается (идемпотентно).
    """
    suffix = Path(filename).suffix.lower()
    mime = _mime_for(Path(filename))
    if not mime or suffix not in set(ALLOWED_MIME.values()) | {".jpeg"}:
        return None
    digest = hashlib.sha256(data).hexdigest()
    aid = asset_id or asset_id_for(digest)
    target_dir = assets_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        resolved_disk_path = disk_path or str(target_dir / f"{aid}{suffix}")
        resolved = Path(resolved_disk_path)
        if not resolved.exists():
            resolved.write_bytes(data)
        else:
            resolved_disk_path = str(resolved)
    except Exception:
        logger.warning("[cover_style_assets] file write failed | id=%s", aid,
                       exc_info=True)
        return None
    return {
        "asset_id": aid,
        "scope": scope,
        "filename": Path(filename).name,
        "mime": mime,
        "size_bytes": len(data),
        "sha256": digest,
        "origin": origin,
        "disk_path": resolved_disk_path,
    }


def import_seed_file(src_path: str | Path, *, origin: str = "seed",
                     scope: str = "global") -> dict | None:
    """Импорт seed-файла: sha256 → asset_id, файл **копируется** (R18).

    `extra_images/*` (src) не изменяется/не удаляется; при повторном импорте
    существующий целевой файл не перезаписывается.
    """
    src = Path(src_path)
    try:
        data = src.read_bytes()
    except OSError:
        logger.warning("[cover_style_assets] seed read failed | %s", src)
        return None
    return store_file_bytes(
        data, filename=src.name, origin=origin, scope=scope)
