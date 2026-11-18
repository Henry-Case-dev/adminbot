"""One end-to-end smoke for release 2.58.216 — no network, no Telegram sends.

1) Voice transport `download_api_file_to_path`: local Bot API file path ->
   destination materialised byte-exact (real code, isolated temp files dir).
2) Empty cloud-fallback: typed provider_error (correct class), observed diag
   recorded as-is (release limitation F2).
3) Transcript lifecycle: derive_transcript_state — fresh pending vs expired
   pending (stale_pending) vs terminal failed vs ready text, same deadline the
   Writer uses.
4) Bot API mode: session/infra mismatch is reported, not guessed from a
   functional flag.

Run: python smoke-2.58.216.py <release-worktree>
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
TMP = Path(tempfile.mkdtemp(prefix="smoke-258216-"))
os.environ.setdefault("ADMINBOT_SKIP_DOTENV", "1")
os.environ["TELEGRAM_API_FILES_DIR"] = str(TMP / "files")
os.environ["MEDIA_DOWNLOAD_CLOUD_FALLBACK"] = "1"
os.environ.pop("TELEGRAM_LOCAL", None)
sys.path.insert(0, str(ROOT))

from services import local_bot_api as lba          # noqa: E402
from services import media_download as md          # noqa: E402
from services import voice_transcripts as vt       # noqa: E402

BOT_ID = 123
TOKEN = "123:smoke-token"
RESULT = {}


class _Api:
    def __init__(self, is_local):
        self.is_local = is_local


class _Session:
    def __init__(self, is_local):
        self.api = _Api(is_local)


class _TGFile:
    def __init__(self, file_path):
        self.file_path = file_path


class _Bot:
    def __init__(self, *, is_local, file_path, get_file_error=None):
        self.id = BOT_ID
        self.token = TOKEN
        self.session = _Session(is_local)
        self._file_path = file_path
        self._get_file_error = get_file_error

    async def get_file(self, file_id):
        if self._get_file_error is not None:
            raise self._get_file_error
        return _TGFile(self._file_path)

    async def download_file(self, *a, **kw):        # must never run here
        raise AssertionError("aiogram transport used in local smoke")

    async def download(self, *a, **kw):             # must never run here
        raise AssertionError("aiogram download used in local smoke")


# 1. Local file path -> destination (real transport code).
async def local_path_smoke():
    # Windows cannot create the real '<bot_id>:<token>' subdir (colon); the
    # host-absolute form of normalize_api_file_path is the same guarded path.
    src = TMP / "files" / "voice" / "file_7.oga"
    src.parent.mkdir(parents=True, exist_ok=True)
    payload = b"OggS-smoke-voice-payload" * 64
    src.write_bytes(payload)
    dst = TMP / "out" / "voice_7.oga"
    dst.parent.mkdir(parents=True, exist_ok=True)
    diag = {}
    await md.download_api_file_to_path(
        _Bot(is_local=True, file_path=str(src)),
        "AgAD-smoke", dst, site="transcribe", attempts=1, sleep=0.0,
        diagnostics=diag)
    assert dst.read_bytes() == payload, "destination differs from source"
    assert diag.get("outcome") == "local_read", diag
    RESULT["local_path"] = {
        "bytes": len(payload),
        "outcome": diag.get("outcome"),
        "stage": diag.get("stage"),
    }


# 2. Empty cloud fallback: typed error, diag observed honestly.
class _BadRequest(Exception):
    status_code = 400


async def empty_cloud_smoke():
    def _fetcher(*a, **kw):
        async def _inner():
            return b""
        return _inner()

    dst = TMP / "out" / "empty.oga"
    diag = {}
    raised = None
    try:
        await md.download_api_file_to_path(
            _Bot(is_local=True, file_path="voice/gone.oga",
                 get_file_error=_BadRequest("wrong file_id")),
            "AgAD-empty", dst, site="transcribe", attempts=1, sleep=0.0,
            cloud_fetcher=_fetcher, diagnostics=diag)
    except md.MediaDownloadError as exc:
        raised = exc
    assert raised is not None, "empty cloud answer was treated as success"
    assert raised.error_class == md.ERROR_PROVIDER_ERROR, (
        raised.error_class, raised.stage, raised.retryable)
    assert raised.retryable is True, raised.retryable
    RESULT["empty_cloud"] = {
        "error_class": raised.error_class,
        "stage": raised.stage,
        "retryable": raised.retryable,
        "diag_observed": dict(diag),
        "note": "diag keeps the pre-fallback stage/class and has no "
                "outcome=failed (release limitation F2); no false success",
    }


# 3. Transcript lifecycle via the Writer's own derivation.
def lifecycle_smoke():
    now = 1_800_000_000
    stale = 3600 + 60
    cases = {
        "fresh_pending": (
            {"media_type": "voice", "transcript_status": "pending",
             "transcript_updated_at": now - 5}, "pending", ""),
        "expired_pending": (
            {"media_type": "voice", "transcript_status": "pending",
             "transcript_updated_at": now - stale},
            "unavailable", "stale_pending"),
        "failed": (
            {"media_type": "voice", "transcript_status": "failed",
             "transcript_reason": "download_get_file_local_read_failed"},
            "failed", "download_get_file_local_read_failed"),
        "ready": (
            {"media_type": "voice", "transcript_status": "ready",
             "text": "текст расшифровки"}, "ready", ""),
        "legacy_pending_with_text": (
            {"media_type": "video", "transcript_status": "pending",
             "text": "старый текст"}, "ready", ""),
    }
    out = {}
    for name, (row, want_status, want_reason) in cases.items():
        status, reason, text = vt.derive_transcript_state(row, now=now)
        assert status == want_status, (name, status, want_status)
        assert reason == want_reason, (name, reason, want_reason)
        out[name] = {"status": status, "reason": reason,
                     "chars": len(text)}
    RESULT["lifecycle"] = out


# 4. Bot API mode is the session/infrastructure fact, not a functional flag.
def bot_api_mode_smoke():
    os.environ["TELEGRAM_LOCAL"] = "1"
    try:
        mismatch = lba.bot_api_mode(_Bot(is_local=False, file_path="x"))
        aligned = lba.bot_api_mode(_Bot(is_local=True, file_path="x"))
    finally:
        os.environ.pop("TELEGRAM_LOCAL", None)
    assert mismatch == {"mode": "cloud", "session": False, "infra": True,
                        "mismatch": True,
                        "reason": "session_vs_infra"}, mismatch
    assert aligned["mode"] == "local" and aligned["mismatch"] is False, aligned
    RESULT["bot_api_mode"] = {"mismatch": mismatch, "aligned": aligned}


async def main():
    await local_path_smoke()
    await empty_cloud_smoke()
    lifecycle_smoke()
    bot_api_mode_smoke()
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))


try:
    asyncio.run(main())
finally:
    for path in sorted(TMP.rglob("*"), reverse=True):
        try:
            path.unlink() if path.is_file() else path.rmdir()
        except OSError:
            pass
