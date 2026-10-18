"""ADTR-ENTRY: поведенческий RED→GREEN-пробник (19.10.2026).

Сравнивает committed-байты (git show HEAD:...) с рабочим деревом на одном и
том же Telegram-событии «photo + caption "бот, что на этой картинке?"».

Запуск (из корня репозитория):
    py -3 plans/features/add-tr/evidence/entry-fix/probe_red_vs_green.py

Вывод — текстом в stdout. Модули из git показываются в изоляции (importlib,
отдельные имена) — рабочие файлы не изменяются.
"""
import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

REPO = Path(__file__).resolve().parents[5]

sys.path.insert(0, str(REPO))


def _scratch_dir() -> Path:
    """Managed scratch, если задан; иначе системный temp (fail-open)."""
    base = os.environ.get("OPENCODE_WORKFLOW_SCRATCH")
    base = Path(base) if base else Path(tempfile.gettempdir())
    return base / "adtr-entry-probe"


def _load_from_git(rel_path: str, module_name: str):
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{rel_path}"], cwd=REPO).decode("utf-8")
    tmp_dir = _scratch_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / (module_name + ".py")
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _photo_caption_message():
    m = MagicMock()
    m.text = None
    m.caption = "бот, что на этой картинке?"
    m.entities = None
    m.caption_entities = None
    m.reply_to_message = None
    m.message_id = 777
    m.chat = MagicMock()
    m.chat.id = -1001234567890
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = 10
    m.photo = [MagicMock()]
    m.document = None
    m.video = None
    m.video_note = None
    m.voice = None
    m.audio = None
    m.animation = None
    m.sticker = None
    m.media_group_id = None
    m.forward_origin = None
    return m


def main() -> None:
    from aiogram.dispatcher.event.bases import UNHANDLED

    # ── RED (committed-байты) ────────────────────────────────────────────
    old = _load_from_git("handlers/direct_chat.py", "adtr_red_direct_chat")
    svc = MagicMock()
    svc.handle = AsyncMock()
    old.setup_direct_chat(svc, 12345, "test_bot")
    res = asyncio.run(old.direct_chat_handler(
        _photo_caption_message(), bot=MagicMock()))
    print("RED  handlers.direct_chat (committed): "
          f"result={'UNHANDLED' if res is UNHANDLED else res!r} "
          f"handle_calls={svc.handle.await_count}")
    old.setup_direct_chat(None, None, None)

    old_dcs = _load_from_git("services/direct_chat_service.py",
                             "adtr_red_dcs")
    old_service = old_dcs.DirectChatService.__new__(
        old_dcs.DirectChatService)
    q_old = old_service._render_current_question(_photo_caption_message())
    print("RED  DirectChatService._render_current_question (committed): "
          f"{q_old!r}")

    # ── GREEN (рабочее дерево) ───────────────────────────────────────────
    import handlers.direct_chat as dc_mod
    from services.direct_chat_service import DirectChatService

    svc2 = MagicMock()
    svc2.handle = AsyncMock()
    dc_mod.setup_direct_chat(svc2, 12345, "test_bot")
    res2 = asyncio.run(dc_mod.direct_chat_handler(
        _photo_caption_message(), bot=MagicMock()))
    print("GREEN handlers.direct_chat (worktree): "
          f"result={'UNHANDLED' if res2 is UNHANDLED else res2!r} "
          f"handle_calls={svc2.handle.await_count}")
    dc_mod.setup_direct_chat(None, None, None)

    service = DirectChatService.__new__(DirectChatService)
    q_new = service._render_current_question(_photo_caption_message())
    print("GREEN DirectChatService._render_current_question (worktree): "
          f"{q_new!r}")


if __name__ == "__main__":
    main()
