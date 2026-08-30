"""Tests for Epic 77 — YouTube через локальный yt-dlp (T-575, Section 78).

Матрица is_youtube_url, гейт YTDLP_FOR_YOUTUBE (off → cobalt даже для
youtube), format-selector, полные opts, cleanup .part-артефактов,
post-merge расширение, TooBig через progress-hook, to_thread + таймаут 900с.
yt-dlp не импортируется по-настоящему — фейк в sys.modules.
"""
import asyncio
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tools import video_downloader as vdm
from tools.video_downloader import (
    DownloadError,
    DownloadTooBigError,
    VideoDownloader,
    is_youtube_url,
)

YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class FakeYoutubeDL:
    """Фейк yt_dlp.YoutubeDL: ловит opts, умеет падать/писать артефакты.

    Эмулирует КОНТРАКТ extract_info(download=True): итоговый post-merge
    путь — в result["requested_downloads"][-1]["filepath"] (review-fix
    Epic 77: progress_hooks "finished" несут только PRE-merge имена).
    """
    last_opts = None
    behavior = {"error": None, "write_part": False, "finalize": True,
                "hook_downloading_bytes": None}

    def __init__(self, opts):
        type(self).last_opts = opts
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=True):
        cls = type(self)
        base = self.opts["outtmpl"].replace("%(ext)s", "")
        hook = self.opts["progress_hooks"][0]
        if cls.behavior["hook_downloading_bytes"] is not None:
            hook({"status": "downloading",
                  "downloaded_bytes": cls.behavior["hook_downloading_bytes"]})
            return {}
        if cls.behavior["write_part"]:
            Path(base + "part").write_bytes(b"partial")
        final = Path(base + "mp4")           # post-merge итог
        if cls.behavior["error"]:
            raise cls.behavior["error"]
        if not cls.behavior["finalize"]:
            return {}
        final.write_bytes(b"merged")
        return {"requested_downloads": [{"filepath": str(final)}]}


def _install_fake_ytdlp(monkeypatch):
    import sys
    import types
    monkeypatch.setattr(FakeYoutubeDL, "last_opts", None)
    FakeYoutubeDL.behavior = {"error": None, "write_part": False,
                              "finalize": True,
                              "hook_downloading_bytes": None}
    fake = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)


@pytest.fixture
def dl(tmp_path):
    d = VideoDownloader("http://localhost:9000/",
                        str(tmp_path / "downloads"))
    d._download_dir.mkdir(parents=True, exist_ok=True)
    return d


# ── 78.2 #1/#2: матрица is_youtube_url ──────────────────────────────

class TestIsYoutubeUrl:
    @pytest.mark.parametrize("url", [
        "https://youtube.com/watch?v=x",
        "https://www.youtube.com/shorts/abc123",
        "https://m.youtube.com/watch?v=x",
        "https://youtu.be/dQw4w9WgXcQ",
        "http://music.youtube.com/watch?v=x",   # http тоже валиден
        "HTTPS://YOUTUBE.COM/WATCH?V=X",         # регистр хоста
        "https://youtube.com./watch?v=x",        # трейлинг точка
    ])
    def test_true_hosts(self, url):
        assert is_youtube_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://vimeo.com/12345",
        "https://vk.com/video-1_2",
        "https://example.com/watch?v=1",
        "not a url",
        "",
        "   ",
        "ftp://youtube.com/x",                   # scheme не http(s)
        "javascript:alert(1)",
        "https://evil-youtube.com/watch",        # подмена в поддомене
        "https://youtube.com.evil.com/watch",    # подмена в суффиксе
        "file:///C:/video.mp4",
    ])
    def test_false(self, url):
        assert is_youtube_url(url) is False


# ── 78.2 #3: гейт off → cobalt даже для youtube ────────────────────

class TestGateOff:
    @pytest.mark.asyncio
    async def test_gate_off_routes_youtube_to_cobalt(self, dl, tmp_path,
                                                     monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        monkeypatch.setattr(vdm, "settings",
                            types.SimpleNamespace(YTDLP_FOR_YOUTUBE=False))
        out = tmp_path / "downloads" / "out.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        dl._request_tunnel = AsyncMock(return_value=("http://tunnel/f.mp4",
                                                     None))
        dl.download_ytdlp = AsyncMock(return_value=tmp_path / "nope.mp4")
        dl._stream_to_file = AsyncMock(return_value=out)
        result = await dl.download(YT_URL, "720p")
        assert result == out
        dl._request_tunnel.assert_awaited_once_with(YT_URL, "720p")
        dl.download_ytdlp.assert_not_awaited()


# ── 78.2 #4: гейт on + youtube → ytdlp под глобальным локом ────────

class TestGateOn:
    @pytest.mark.asyncio
    async def test_gate_on_routes_youtube_to_ytdlp_under_lock(self, dl,
                                                              tmp_path,
                                                              monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        monkeypatch.setattr(vdm, "settings",
                            types.SimpleNamespace(YTDLP_FOR_YOUTUBE=True))
        seen_busy = []
        out = tmp_path / "downloads" / "done.mp4"

        async def fake_branch(url, quality):
            seen_busy.append(dl.busy)        # лок держится ВО время ветки
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"v")
            return out

        dl.download_ytdlp = fake_branch
        dl._request_tunnel = AsyncMock(
            side_effect=AssertionError("cobalt must not be called"))
        result = await dl.download(YT_URL, "720p")
        assert result == out
        assert seen_busy == [True]
        assert dl.busy is False              # лок отпущен после

    @pytest.mark.asyncio
    async def test_non_youtube_still_cobalt_when_gate_on(self, dl, tmp_path,
                                                         monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        monkeypatch.setattr(vdm, "settings",
                            types.SimpleNamespace(YTDLP_FOR_YOUTUBE=True))
        out = tmp_path / "out.mp4"
        out.write_bytes(b"x")
        dl._request_tunnel = AsyncMock(return_value=("http://tunnel/f.mp4",
                                                     None))
        dl.download_ytdlp = AsyncMock()
        dl._stream_to_file = AsyncMock(return_value=out)
        await dl.download("https://vimeo.com/42", "720p")
        dl._request_tunnel.assert_awaited_once()
        dl.download_ytdlp.assert_not_awaited()


# ── 78.2 #5: format-selector ────────────────────────────────────────

class TestFormatSelector:
    async def _run(self, dl, monkeypatch, quality):
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["finalize"] = True
        return await dl.download_ytdlp(YT_URL, quality)

    @pytest.mark.asyncio
    async def test_height_cap_and_mp4_priority(self, dl, tmp_path,
                                               monkeypatch):
        await self._run(dl, monkeypatch, "720p")
        fmt = FakeYoutubeDL.last_opts["format"]
        assert fmt == ("bv[ext=mp4][height<=720][protocol^=https]+ba[ext=m4a]"
                       "/bv[ext=mp4][height<=720]+ba[ext=m4a]"
                       "/bv[height<=720]+ba/b[height<=720]")
        assert fmt.startswith("bv[ext=mp4]")

    @pytest.mark.asyncio
    async def test_int_quality_normalized_via_d280(self, dl, tmp_path,
                                                   monkeypatch):
        await self._run(dl, monkeypatch, "1080p")
        assert "height<=1080" in FakeYoutubeDL.last_opts["format"]

    @pytest.mark.asyncio
    async def test_max_no_height_filter(self, dl, tmp_path, monkeypatch):
        await self._run(dl, monkeypatch, "max")
        fmt = FakeYoutubeDL.last_opts["format"]
        assert fmt == ("bv[ext=mp4][protocol^=https]+ba[ext=m4a]"
                       "/bv[ext=mp4]+ba[ext=m4a]/bv+ba/b")
        assert "height<=" not in fmt


# ── 78.2 #6: полные opts ────────────────────────────────────────────

class TestOpts:
    @pytest.mark.asyncio
    async def test_base_opts_merged_and_flags_set(self, dl, tmp_path,
                                                  monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        secret = "http://user:secret@127.0.0.1:10808"
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts",
                            lambda: {"proxy": secret})
        await dl.download_ytdlp(YT_URL, "720p")
        opts = FakeYoutubeDL.last_opts
        assert opts["noplaylist"] is True
        assert opts["quiet"] is True
        assert opts["noprogress"] is True
        assert opts["merge_output_format"] == "mp4"
        assert opts["proxy"] == secret       # из build_ytdlp_base_opts()
        assert len(opts["progress_hooks"]) == 1

    @pytest.mark.asyncio
    async def test_outtmpl_in_download_dir(self, dl, monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        await dl.download_ytdlp(YT_URL, "720p")
        outtmpl = FakeYoutubeDL.last_opts["outtmpl"]
        assert outtmpl.startswith(str(dl._download_dir))
        assert "%(ext)s" in outtmpl          # НЕ жёсткий .mp4 до merge
        assert "vd_" in outtmpl


# ── 78.2 #7: cleanup .part/.ytdl артефактов при исключении ──────────

class TestCleanupArtifacts:
    @pytest.mark.asyncio
    async def test_exception_removes_all_prefix_artifacts(self, dl,
                                                          monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["write_part"] = True
        FakeYoutubeDL.behavior["error"] = RuntimeError("boom mid-download")
        with pytest.raises(DownloadError, match="yt-dlp failed"):
            await dl.download_ytdlp(YT_URL, "720p")
        assert list(dl._download_dir.glob("vd_*")) == []

    @pytest.mark.asyncio
    async def test_success_keeps_final_file(self, dl, monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        path = await dl.download_ytdlp(YT_URL, "720p")
        assert path.exists()
        assert path.suffix == ".mp4"


# ── 78.2 #8: post-merge расширение / glob-fallback ──────────────────

class TestFinalPath:
    @pytest.mark.asyncio
    async def test_requested_downloads_path_returned(self, dl, monkeypatch):
        """Канонический путь: requested_downloads[-1]['filepath'] (mp4)."""
        _install_fake_ytdlp(monkeypatch)     # finalize=True → rd .mp4
        path = await dl.download_ytdlp(YT_URL, "max")
        assert path.suffix == ".mp4"         # НЕ pre-merge .webm/.m4a
        assert path.read_bytes() == b"merged"

    @pytest.mark.asyncio
    async def test_intermediates_not_matched_by_fallback(self, dl,
                                                         monkeypatch):
        """Review-fix: fallback игнорирует vd_*.f<id>.* промежуточные."""
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["finalize"] = False

        def extract_writes_merge_artifacts(self_ydl, url, download=True):
            base = self_ydl.opts["outtmpl"].replace("%(ext)s", "")[:-1]
            # как реальный yt-dlp: промежуточные + merged итог
            Path(base + ".f137.mp4").write_bytes(b"v")
            Path(base + ".f140.m4a").write_bytes(b"a")
            Path(base + ".f137.mp4.part").write_bytes(b"p")
            Path(base + ".mp4").write_bytes(b"merged")

        monkeypatch.setattr(FakeYoutubeDL, "extract_info",
                            extract_writes_merge_artifacts)
        path = await dl.download_ytdlp(YT_URL, "720p")
        assert not vdm._INTERMEDIATE_INFIX_RE.search(path.name)
        assert path.read_bytes() == b"merged"

    @pytest.mark.asyncio
    async def test_glob_fallback_single_file(self, dl, monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["finalize"] = False

        def download_writes_webm(self_ydl, urls=None, download=True):
            base = self_ydl.opts["outtmpl"].replace("%(ext)s", "")
            Path(base + "webm").write_bytes(b"w")

        monkeypatch.setattr(FakeYoutubeDL, "extract_info",
                            download_writes_webm)
        path = await dl.download_ytdlp(YT_URL, "720p")
        assert path.suffix == ".webm"
        assert path.exists()

    @pytest.mark.asyncio
    async def test_glob_fallback_zero_or_multiple_files_error(self, dl,
                                                              monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["finalize"] = False

        def download_writes_two(self_ydl, urls=None, download=True):
            base = self_ydl.opts["outtmpl"].replace("%(ext)s", "")
            Path(base + "webm").write_bytes(b"w")
            Path(base + "mkv").write_bytes(b"m")

        monkeypatch.setattr(FakeYoutubeDL, "extract_info",
                            download_writes_two)
        with pytest.raises(DownloadError,
                           match="output file not found"):
            await dl.download_ytdlp(YT_URL, "720p")
        # F1: при неоднозначности каталог чистится (edge-дыра M2)
        assert list(dl._download_dir.glob("vd_*")) == []

    @pytest.mark.asyncio
    async def test_glob_fallback_zero_files_error_purges(self, dl,
                                                         monkeypatch):
        """F1: zero-case — итоговый файл не записан → ошибка, каталог
        остаётся чистым (никаких .f*/мусора)."""
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["finalize"] = False

        def download_writes_nothing(self_ydl, urls=None, download=True):
            pass

        monkeypatch.setattr(FakeYoutubeDL, "extract_info",
                            download_writes_nothing)
        with pytest.raises(DownloadError,
                           match="output file not found"):
            await dl.download_ytdlp(YT_URL, "720p")
        assert list(dl._download_dir.glob("vd_*")) == []


# ── 78.2 #9: лимит размера через progress-hook ──────────────────────

class TestTooBig:
    @pytest.mark.asyncio
    async def test_downloading_over_limit_raises_too_big(self, dl,
                                                         monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        FakeYoutubeDL.behavior["hook_downloading_bytes"] = \
            vdm.VD_MAX_BYTES + 1
        with pytest.raises(DownloadTooBigError):
            await dl.download_ytdlp(YT_URL, "1080p")
        # артефакты не копим и тут
        assert list(dl._download_dir.glob("vd_*")) == []


# ── 78.2 #10: выполнение через to_thread + wait_for(900) ────────────

class TestThreadExecution:
    @pytest.mark.asyncio
    async def test_runs_in_to_thread_with_900s_timeout(self, dl,
                                                       monkeypatch):
        _install_fake_ytdlp(monkeypatch)
        threads, timeouts = [], []
        real_to_thread = asyncio.to_thread
        real_wait_for = asyncio.wait_for

        async def spy_wait_for(fut, timeout=None):
            timeouts.append(timeout)
            return await real_wait_for(fut, timeout=timeout)

        monkeypatch.setattr(
            vdm.asyncio, "to_thread",
            lambda fn, *a, **k: (threads.append(fn),
                                 real_to_thread(fn, *a, **k))[1])
        monkeypatch.setattr(vdm.asyncio, "wait_for", spy_wait_for)
        await dl.download_ytdlp(YT_URL, "720p")
        assert len(threads) == 1             # YoutubeDL.download в потоке
        assert timeouts == [900.0]

    @pytest.mark.asyncio
    async def test_timeout_wrapped_as_download_error(self, dl, monkeypatch):
        _install_fake_ytdlp(monkeypatch)

        async def timeout_only(fut, timeout=None):
            fut.close()                  # корутина не awaited — гасим warning
            raise asyncio.TimeoutError()

        monkeypatch.setattr(vdm.asyncio, "wait_for", timeout_only)
        with pytest.raises(DownloadError, match=r"timeout after 900s"):
            await dl.download_ytdlp(YT_URL, "720p")
