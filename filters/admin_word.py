import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class StrictAdminFilter(BaseFilter):
    """Matches messages where 'админ' appears as an exact standalone word."""
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        
        text = message.text.lower().strip()
        clean = re.sub(r'^[,\.!?\*_\-]+|[,\.!?\*_\-]+$', '', text)
        words = clean.split()
        return 'админ' in words
