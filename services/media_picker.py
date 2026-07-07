import glob
import random
from pathlib import Path


class MediaService:
    """Picks random media files from media/dead_page/ directory. Stateless."""
    
    def __init__(self, media_base: str = "media/dead_page"):
        self.base = Path(media_base)
        self._photos: list[Path] | None = None
        self._texts: list[Path] | None = None
    
    def _refresh(self) -> None:
        """Scan directory for .jpg and .txt files."""
        self._photos = sorted(
            Path(p) for p in glob.glob(str(self.base / "*.jpg"))
        )
        self._texts = sorted(
            Path(p) for p in glob.glob(str(self.base / "*.txt"))
        )
    
    async def pick_random(self) -> tuple[str, str]:
        """
        Returns (photo_path, text_content).
        Raises FileNotFoundError if no photos or no texts found.
        """
        if self._photos is None or self._texts is None:
            self._refresh()
        
        if not self._photos:
            raise FileNotFoundError(f"No .jpg files in {self.base}")
        if not self._texts:
            raise FileNotFoundError(f"No .txt files in {self.base}")
        
        photo_path = str(random.choice(self._photos))
        text_path = random.choice(self._texts)
        text_content = text_path.read_text(encoding='utf-8')
        
        return photo_path, text_content
