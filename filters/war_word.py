import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class WarWordFilter(BaseFilter):
    """Matches messages containing military/drone-related words."""
    
    WAR_WORDS = [
        'летит', 'летает', 'прилетел', 'прилетает', 'летят', 'летел',
        'дрон', 'дроны', 'дронов', 'беспилотник', 'беспилотники',
        'вспышка', 'вспышки', 'вспышке',
        'прилет', 'прилёт', 'прилетел', 'прилетит',
        'укрытие', 'укрытия', 'укрытии',
        'бункер', 'бункера', 'бункере',
        'ракета', 'ракеты', 'ракет', 'ракете',
    ]
    
    _PATTERNS = [
        re.compile(rf'(?<![а-яё]){re.escape(word)}(?![а-яё])', re.IGNORECASE)
        for word in WAR_WORDS
    ]
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return any(p.search(message.text) for p in self._PATTERNS)
