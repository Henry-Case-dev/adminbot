import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class KuchaWordFilter(BaseFilter):
    """Matches messages containing the word stem 'куч-' (КУЧА and all declensions).
    
    Valid forms: куча, кучи, куче, кучу, кучей, кучею, куч, кучам, кучами, кучах.
    Excludes: кучка/кучки/кучек (diminutive), кучерявый, кучковаться, etc.
    """
    
    _PATTERN = re.compile(
        r'(?<![а-яё])куч(?:а|и|е|у|ей|ею|ам|ами|ах)?(?![а-яё])',
        re.IGNORECASE
    )
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return bool(self._PATTERN.search(message.text))
