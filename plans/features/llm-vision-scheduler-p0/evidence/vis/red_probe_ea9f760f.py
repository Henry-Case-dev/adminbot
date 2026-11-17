"""RED-проба P0 Vision download на базовом коде (ea9f760f).

Проверяет ровно три дефекта брифа:
  1. отсутствующий локальный файл → НЕклассифицированное исключение
     (generic OSError), а не MediaDownloadError(stage,class);
  2. `process_asset_job` пишет `vision_unavailable` БЕЗ `error_json`
     (класс/стадия не доходят до события/очереди/чекапа);
  3. `_note_breaker` на ошибке скачивания СБРАСЫВАЕТ streak (вместо ++).

Запуск: python <этот файл> (в рабочем дереве базового коммита).
Печатает JSON-факты; ничего не пишет в БД проекта (tmp-файл).
"""
import asyncio
import datetime as dt
import json
import os
import tempfile
import time
import types

os.environ.setdefault("ADMINBOT_SKIP_DOTENV", "1")

from aiogram.types import Chat, File, Message, PhotoSize, User  # noqa: E402

from config.settings import settings  # noqa: E402
from services import media_download  # noqa: E402
from services import mca_events, mca_vision  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.task_supervisor import TaskJobStore  # noqa: E402

CHAT = -1005550777
TOKEN = "4242:red-probe-token"


class _Session:
    api = types.SimpleNamespace(is_local=True)


class _Bot:
    id = 4242
    token = TOKEN
    session = _Session()
    get_file_calls = 0

    async def get_file(self, file_id):
        type(self).get_file_calls += 1
        return File(file_id=str(file_id), file_unique_id="u",
                    file_path="photos/gone.png")

    async def download_file(self, file_path, destination=None, timeout=30):
        raise FileNotFoundError(str(file_path))

    async def download(self, file, destination=None):
        raise FileNotFoundError("photos/gone.png")


def _photo_message(tg_id: int) -> Message:
    return Message(
        message_id=tg_id,
        date=dt.datetime(2026, 11, 17, 9, 0, 0, tzinfo=dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="V"),
        photo=[PhotoSize(file_id=f"fid_{tg_id}", file_unique_id=f"uniq_{tg_id}",
                         width=800, height=600, file_size=1234)])


async def main() -> dict:
    for key, value in (("VISION_ENABLED", True), ("LLM_API_KEY", "k"),
                       ("VISION_API_KEY", ""), ("VISION_API_BASE_URL", ""),
                       ("VISION_MODEL", ""),
                       ("VISION_API_TYPE", "openai_compatible")):
        object.__setattr__(settings, key, value)
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    mca_vision._RUNTIME  # noqa: B018

    facts: dict = {}

    # 1) Транспорт/загрузка: класс исключения при отсутствии локального файла.
    bot = _Bot()
    try:
        await mca_vision.download_telegram_file(bot, "fid")
        facts["download"] = {"raised": None}
    except Exception as exc:                                  # noqa: BLE001
        facts["download"] = {
            "raised": type(exc).__name__,
            "is_classified": bool(getattr(exc, "error_class", None)),
            "stage": getattr(exc, "stage", None),
            "message": str(exc)[:120],
        }

    # 2) Пайплайн: что доходит до события/очереди/чекапа.
    events: list[dict] = []

    def _emit(name, **fields):
        events.append({"name": name, **fields})
        return None

    real_emit = mca_events.emit_mca_event
    mca_events.emit_mca_event = _emit
    mca_vision.pipeline_stage_event.__globals__["mca_events"].emit_mca_event = _emit

    db_path = os.path.join(tempfile.mkdtemp(prefix="p0vis-red-"), "red.db")
    db = DatabaseService(db_path)
    await db.initialize()
    try:
        mca_vision.bind_runtime(db)
        mca_vision.store_capability(
            mca_vision.resolve_route(),
            mca_vision.CapabilityVerdict("ok", "", True, time.monotonic()))
        msg = _photo_message(501)
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        store = TaskJobStore(db)
        queued = [j for j in await store.active()
                  if j.get("status") == "queued"
                  and str(json.loads(j.get("payload") or "{}").get("asset_id"))
                  == str(assets[0])]
        job_id = queued[0]["job_id"]
        await store.mark_running(job_id)
        job = await store.get(job_id) or {}
        facts["breaker_before"] = mca_vision._RUNTIME.get("breaker_streak")
        job["attempt"] = 1
        await mca_vision.process_asset_job(job, db=db, bot=_Bot(),
                                           transport=_no_transport)
        row = await store.get(job_id) or {}
        dl = [e for e in events if e.get("stage") == "download"
              and e.get("name") == "vision_media"]
        facts["retry_event"] = {
            "outcome": dl[-1].get("outcome") if dl else None,
            "reason_code": dl[-1].get("reason_code") if dl else None,
            "error_json": dl[-1].get("error_json") if dl else None,
            "has_job_id": bool(dl and dl[-1].get("job_id")),
            "has_attempt": bool(dl and "attempt" in dl[-1]),
        }
        facts["queue_retry"] = {"status": row.get("status"),
                                "reason_code": row.get("reason_code"),
                                "error_code": row.get("error_code")}
        facts["breaker_after_failure"] = mca_vision._RUNTIME.get(
            "breaker_streak")
        # Терминальная попытка.
        job2 = dict(row)
        job2["attempt"] = mca_vision.JOB_MAX_ATTEMPTS - 1
        await mca_vision.process_asset_job(job2, db=db, bot=_Bot(),
                                          transport=_no_transport)
        row2 = await store.get(job_id) or {}
        dl2 = [e for e in events if e.get("stage") == "download"
               and e.get("name") == "vision_media"]
        facts["terminal_event"] = {
            "outcome": dl2[-1].get("outcome") if dl2 else None,
            "reason_code": dl2[-1].get("reason_code") if dl2 else None,
            "error_json": dl2[-1].get("error_json") if dl2 else None,
        }
        facts["queue_terminal"] = {"status": row2.get("status"),
                                   "reason_code": row2.get("reason_code"),
                                   "error_code": row2.get("error_code")}
        snapshot = await mca_vision.runtime_snapshot(db=db, chat_id=CHAT)
        facts["checkup_last_error"] = snapshot.get("last_error")
        cur = await db.db.execute(
            "SELECT COUNT(*) AS n FROM mca_media_analyses")
        facts["analyses"] = int(dict(await cur.fetchone())["n"])
    finally:
        await db.close()
        try:
            mca_vision.pipeline_stage_event.__globals__[
                "mca_events"].emit_mca_event = real_emit
        except Exception:                                     # noqa: BLE001
            pass
    facts["has_media_download_error"] = hasattr(
        media_download, "MediaDownloadError")
    facts["has_bytes_helper"] = hasattr(
        media_download, "download_api_file_bytes")
    return facts


async def _no_transport(url, *, payload, headers, timeout):
    return 400, {}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
