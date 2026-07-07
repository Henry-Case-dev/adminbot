import pytest
import tempfile
from pathlib import Path
from services.media_picker import MediaService


class TestMediaService:
    @pytest.mark.asyncio
    async def test_pick_random_returns_photo_and_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "test.jpg").write_text("fake jpg", encoding="utf-8")
            (base / "test.txt").write_text("fake text content", encoding="utf-8")
            
            service = MediaService(media_base=str(base))
            photo_path, text = await service.pick_random()
            
            assert photo_path.endswith(".jpg")
            assert "fake text content" in text

    @pytest.mark.asyncio
    async def test_pick_random_no_photos_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "test.txt").write_text("text", encoding="utf-8")
            
            service = MediaService(media_base=str(base))
            with pytest.raises(FileNotFoundError, match="No .jpg files"):
                await service.pick_random()

    @pytest.mark.asyncio
    async def test_pick_random_no_texts_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "test.jpg").write_text("fake jpg", encoding="utf-8")
            
            service = MediaService(media_base=str(base))
            with pytest.raises(FileNotFoundError, match="No .txt files"):
                await service.pick_random()

    @pytest.mark.asyncio
    async def test_pick_random_handles_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "1.jpg").write_text("1", encoding="utf-8")
            (base / "2.jpg").write_text("2", encoding="utf-8")
            (base / "a.txt").write_text("text A", encoding="utf-8")
            (base / "b.txt").write_text("text B", encoding="utf-8")
            
            service = MediaService(media_base=str(base))
            
            for _ in range(10):
                photo_path, text = await service.pick_random()
                assert photo_path.endswith(".jpg")
                assert len(text) > 0
