"""Раунд 5 (T-740, spec 3.3.4, FR-D3): авто-миграция канонов промптов в PG.

Заменяет migrate_direct_chat_prompt_if_legacy (удалена из chat_prompts.py):
для каждого PG-ключа prompts.* текущее значение == одному из предыдущих
канонов (PREV_*-слепки / LEGACY) → upsert новым каноном; == новому канону →
no-op; отсутствующий ключ → skip (сид ConfigCache поставит канон); иначе —
кастом юзера → skip + WARNING. PG down → skip (R6: бот работает на дефолтах
констант — они уже новые). Итерация — в фиксированном порядке объявления
словаря (детерминированные логи/тесты). Возврат отчёта dict[key, "updated"].

prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT — ETL-экстрактор,
не user-facing; не правится).
"""
import logging

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
)
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
)
from services.search_prompts import (
    PREV_SEARCH_SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)
from services.summary_prompts import (
    COMPRESS_PROMPT,
    PREV_COMPRESS_PROMPT,
    PREV_SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.web_prompts import (
    PREV_WEBPAGE_SYSTEM_PROMPT,
    WEBPAGE_SYSTEM_PROMPT,
)
from services.youtube_prompts import (
    PREV_YOUTUBE_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

PROMPT_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "prompts.direct_chat_system_prompt": [
        (LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)],
    "prompts.summary_system_prompt": [(PREV_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT)],
    "prompts.compress_system_prompt": [(PREV_COMPRESS_PROMPT, COMPRESS_PROMPT)],
    "prompts.checkup_system_prompt": [
        (PREV_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT)],
    "prompts.factcheck_system_prompt": [
        (PREV_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT)],
    "prompts.search_system_prompt": [(PREV_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT)],
    "prompts.youtube_system_prompt": [
        (PREV_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT)],
    "prompts.youtube_video_system_prompt": [
        (PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT)],
    "prompts.webpage_system_prompt": [
        (PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT)],
}
# prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)


async def migrate_prompt_canons(cache) -> dict[str, str]:
    """Авто-миграция канонов промптов (раунд 5): канон → новый канон;
    кастом юзера НЕ трогаем; PG down / ключ отсутствует → skip с логом
    [prompt_migration]. Возврат: dict обновлённых ключей (пусто — ничего
    не обновлено). Вызывается из bot.py main() сразу после cache.init()."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_migration] skip: PG недоступен")
        return report
    for key, steps in PROMPT_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[prompt_migration] ключ отсутствует — сид сделает "
                        "своё | key=%s", key)
            continue
        matched = None
        for prev, new in steps:
            if current == new:
                matched = ("new", new)
                break
            if current == prev:
                matched = ("prev", prev, new)
                break
        if matched is None:
            logger.warning("[prompt_migration] кастом юзера — НЕ трогаем | "
                           "key=%s | chars=%d", key, len(current))
            continue
        if matched[0] == "new":
            logger.info("[prompt_migration] уже новый канон | key=%s", key)
            continue
        new = matched[2]
        await cache.set(key, new, "prompts")
        report[key] = "updated"
        logger.info("[prompt_migration] канон обновлён | key=%s", key)
    return report
