"""DangerWordFilter — matches danger-related keywords via regex.

Borrows the exact same _build_patterns function from filters/war_word.py:
  - Cyrillic word boundaries: (?<![а-яё])...(?![а-яё])
  - Case-insensitive: re.IGNORECASE

Returns {"matched_word": match.group()} so the handler can quote
the matched word in the reply.
"""
import re
import logging
from aiogram.filters import BaseFilter
from aiogram.types import Message
from config.settings import settings

logger = logging.getLogger(__name__)

# Words synced from filters/war_word.py WarWordFilter.WAR_WORDS.
_DEFAULT_DANGER_WORDS: list[str] = [
    # ── Flight / arrival ──
    'летит', 'летает', 'прилетел', 'прилетает', 'летят', 'летел',
    'прилет', 'прилёт', 'прилетит',
    # ── Drone / UAV ──
    'дрон', 'дроны', 'дронов', 'дрону', 'дроном', 'дроне',
    'дронам', 'дронами', 'дронах',
    'беспилотник', 'беспилотники', 'беспилотника', 'беспилотнику',
    'беспилотником', 'беспилотнике', 'беспилотников', 'беспилотникам',
    'беспилотниками', 'беспилотниках',
    'бпла',
    # ── Rocket / missile ──
    'ракета', 'ракеты', 'ракет', 'ракете', 'ракету', 'ракетой',
    'ракетою', 'ракетам', 'ракетами', 'ракетах',
    'ракетная', 'ракетной', 'ракетную', 'ракетною',
    'ракетные', 'ракетных', 'ракетным', 'ракетными',
    'ракетный', 'ракетного', 'ракетному',
    # ── Shelter / bunker ──
    'укрытие', 'укрытия', 'укрытию', 'укрытием', 'укрытии',
    'укрытий', 'укрытиям', 'укрытиями', 'укрытиях',
    'убежище', 'убежища', 'убежищу', 'убежищем',
    'убежищ', 'убежищам', 'убежищами', 'убежищах',
    'бункер', 'бункера', 'бункеру', 'бункером', 'бункере',
    'бункеров', 'бункерам', 'бункерами', 'бункерах',
    # ── Flash / explosion ──
    'вспышка', 'вспышки', 'вспышке', 'вспышку', 'вспышкой',
    'вспышек', 'вспышкам', 'вспышками', 'вспышках',
    'взрыв', 'взрыва', 'взрыву', 'взрывом', 'взрыве',
    'взрывы', 'взрывов', 'взрывам', 'взрывами', 'взрывах',
    # ── Danger / alert ──
    'опасность', 'опасности', 'опасностью', 'опасностей',
    'опасен', 'опасна', 'опасно', 'опасны',
    'тревога', 'тревоги', 'тревоге', 'тревогу', 'тревогой',
    'внимание',
    'оповещение', 'оповещения', 'оповещению', 'оповещением',
    'оповещении', 'оповещений',
    # ── Сирена / воздушная тревога ──
    'сирена', 'сирены', 'сирену', 'сиреной', 'сирене',
    'сирен', 'сиренам', 'сиренами', 'сиренах',
    'воздушная', 'воздушной', 'воздушную',
    # ── Беспилотные (adjectives) ──
    'беспилотной', 'беспилотная', 'беспилотное', 'беспилотные',
    'беспилотного', 'беспилотному', 'беспилотным',
    'беспилотных',
    # ── Атака / угроза ──
    'атака', 'атаки', 'атаке', 'атаку', 'атакой',
    'атак', 'атакам', 'атаками', 'атаках',
    'угроза', 'угрозы', 'угрозе', 'угрозу', 'угрозой',
    'угроз', 'угрозам', 'угрозами', 'угрозах',
    'обстрел', 'обстрела', 'обстрелу', 'обстрелом', 'обстреле',
    'обстрелы', 'обстрелов', 'обстрелам', 'обстрелами', 'обстрелах',
    # ── Падение / сбитие ──
    'сбит', 'сбита', 'сбито', 'сбиты',
    'падение', 'падения', 'падению', 'падением', 'падении',
    'упал', 'упала', 'упало', 'упали',
    # ── Эвакуация ──
    'эвакуация', 'эвакуации', 'эвакуацию', 'эвакуацией',
    'эвакуироваться',
    # ── Отбой ──
    'отбой', 'отбоя', 'отбою', 'отбоем', 'отбое',
]


def _build_danger_patterns(words: list[str]) -> list[re.Pattern]:
    """Compile regex patterns with Cyrillic word boundaries.

    Borrows the exact same pattern as _build_patterns from filters/war_word.py.
    """
    patterns: list[re.Pattern] = []
    for word in words:
        try:
            patterns.append(
                re.compile(
                    rf"(?<![а-яё]){re.escape(word)}(?![а-яё])",
                    re.IGNORECASE,
                )
            )
        except re.error:
            logger.warning(
                "DangerWordFilter: failed to compile pattern for word %r", word
            )
    return patterns


def _parse_danger_words(raw: str) -> list[str]:
    """Parse comma-separated danger words from config.

    Falls back to _DEFAULT_DANGER_WORDS if config is empty or unset.
    """
    if not raw:
        return list(_DEFAULT_DANGER_WORDS)
    parts = [w.strip().lower() for w in raw.split(",") if w.strip()]
    return parts if parts else list(_DEFAULT_DANGER_WORDS)


class DangerWordFilter(BaseFilter):
    """Matches messages containing danger-related keywords.

    Checks BOTH message.text and message.caption.
    Returns {"matched_word": match.group()} to pass the matched word
    to the handler for quoting.

    Pattern borrowed from WarWordFilter (filters/war_word.py):
      - Cyrillic word boundaries: (?<![а-яё])...(?![а-яё])
      - Case-insensitive: re.IGNORECASE
    """

    def __init__(self, words: list[str] | None = None) -> None:
        if words is not None:
            self._words = words
        else:
            self._words = _parse_danger_words(settings.DANGER_WORDS)
        self._patterns = _build_danger_patterns(self._words)

    async def __call__(self, message: Message) -> dict[str, str] | bool:
        """Check message text/caption for danger keywords.

        Returns:
            {"matched_word": match.group()} if a danger word is found,
            False otherwise.
        """
        content = message.text or message.caption
        if not content or not isinstance(content, str):
            return False

        for p in self._patterns:
            match = p.search(content)
            if match:
                matched_word = match.group()
                logger.info(
                    "DangerWordFilter matched | word=%r | msg_id=%s | chat_id=%s",
                    matched_word,
                    message.message_id,
                    message.chat.id,
                )
                return {"matched_word": matched_word}
        return False
