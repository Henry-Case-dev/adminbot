import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class VasyaFilter(BaseFilter):
    """Matches messages containing any variation of "Vasya" (Вася) including transliterated input."""
    
    _TRANSLIT = str.maketrans({
        'v': 'в', 'V': 'в',
        'a': 'а', 'A': 'а',
        's': 'с', 'S': 'с',
        'y': 'я', 'Y': 'я',
        'i': 'и', 'I': 'и',
        'h': 'ш', 'H': 'ш',
        'l': 'л',
    })
    
    _STEM_PATTERN = re.compile(r'вас[иеёяю]')
    _CLEAN_PATTERN = re.compile(r'[^а-яё]')
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        
        text = message.text.lower()
        text = text.replace("sh", "ш").replace("ya", "я").replace("iy", "ий")
        text = text.replace("ch", "ч").replace("kh", "х")
        text = text.translate(self._TRANSLIT)
        clean = self._CLEAN_PATTERN.sub('', text)
        
        return bool(self._STEM_PATTERN.search(clean))
