import re
import logging
from aiogram.filters import BaseFilter
from aiogram.types import Message

logger = logging.getLogger(__name__)


def _build_patterns(words):
    """Compile regex patterns from word list with Cyrillic word boundaries."""
    patterns = []
    for word in words:
        try:
            patterns.append(
                re.compile(rf'(?<![а-яё]){re.escape(word)}(?![а-яё])', re.IGNORECASE)
            )
        except re.error:
            logger.warning(
                "WarWordFilter: failed to compile pattern for word %r", word
            )
    return patterns


class WarWordFilter(BaseFilter):
    """Matches messages containing military/drone/alert-related keywords.

    Checks BOTH message.text and message.caption to handle forwarded
    media messages where text is stored in caption (T-057 fix).
    """

    WAR_WORDS = [
        # ── Flight / arrival ──
        'летит', 'летает', 'прилетел', 'прилетает', 'летят', 'летел',
        'прилет', 'прилёт', 'прилетит',
        # ── Drone / UAV ──
        'дрон', 'дроны', 'дронов', 'дрону', 'дроном', 'дроне',
        'дронам', 'дронами', 'дронах',
        'беспилотник', 'беспилотники', 'беспилотника', 'беспилотнику',
        'беспилотником', 'беспилотнике', 'беспилотников', 'беспилотникам',
        'беспилотниками', 'беспилотниках',
        'бпла', 'БПЛА',
        # ── Rocket / missile ──
        'ракета', 'ракеты', 'ракет', 'ракете', 'ракету', 'ракетой',
        'ракетою', 'ракетам', 'ракетами', 'ракетах',
        'ракетная', 'ракетной', 'ракетную', 'ракетною',
        'ракетные', 'ракетных', 'ракетным', 'ракетными',
        'ракетный', 'ракетного', 'ракетному', 'ракетным',
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

    _PATTERNS = _build_patterns(WAR_WORDS)

    async def __call__(self, message: Message) -> bool:
        content = message.text or message.caption
        # Guard: ensure we have an actual string (not MagicMock, not None, not empty)
        if not content or not isinstance(content, str):
            return False

        for p in self._PATTERNS:
            match = p.search(content)
            if match:
                matched_word = match.group()
                logger.info(
                    "WarWordFilter matched | word=%r | msg_id=%s | chat_id=%s | "
                    "source=%s",
                    matched_word,
                    message.message_id,
                    message.chat.id,
                    "caption" if message.caption and not message.text else "text",
                )
                return True
        return False
