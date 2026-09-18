"""Раунд 5 (T-740, spec 3.3.4, FR-D3): авто-миграция канонов промптов в PG.

Раунд 8 (T-790, Context-Layer X-Features): для prompts.direct_chat_system_prompt
добавлена третья ступень (PREV_R8_CHAT_SYSTEM_PROMPT → новый канон раунда 8);
существующие ступени (LEGACY→новый, PREV→новый) сохранены и указывают на новый
CHAT_SYSTEM_PROMPT автоматически.

Раунд 9 (AGI Memory, T-821, spec §3.2.2): четвёртая ступень direct_chat
(PREV_R9_CHAT_SYSTEM_PROMPT — слепок канона раунда 8, HEAD 84c4887 → канон
раунда 9); PREV_R8-ступень указывает на новый канон автоматически.

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
    PREV_CHAT_R2020_SYSTEM_PROMPT,
    PREV_CHAT_R1021_SYSTEM_PROMPT,
    PREV_CHAT_R1023_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
    PREV_R1022_CHAT_SYSTEM_PROMPT,
    PREV_R8_CHAT_SYSTEM_PROMPT,
    PREV_R9_CHAT_SYSTEM_PROMPT,
)
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_R1021_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
    PREV_R1022_CHECKUP_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_ANALYST_R1023,
    PREV_FACTCHECK_ANALYST_R1023_F2,
    PREV_FACTCHECK_ANALYST_R1023_F3,
    PREV_FACTCHECK_R1021_SYSTEM_PROMPT,
    PREV_FACTCHECK_R2020_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
    PREV_R1022_FACTCHECK_SYSTEM_PROMPT,
)
from services.search_prompts import (
    PREV_R1022_SEARCH_SYSTEM_PROMPT,
    PREV_SEARCH_R1021_SYSTEM_PROMPT,
    PREV_SEARCH_SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)
from services.summary_prompts import (
    COMPRESS_PROMPT,
    PREV_COMPRESS_PROMPT,
    PREV_R1021_SUMMARY_SYSTEM_PROMPT,
    PREV_R1022_SUMMARY_SYSTEM_PROMPT,
    PREV_R2020_SUMMARY_SYSTEM_PROMPT,
    PREV_SUMMARY_EDITOR_R1023,
    PREV_SUMMARY_EDITOR_R1023_F3,
    PREV_SUMMARY_SYSTEM_PROMPT,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.web_prompts import (
    PREV_R1022_WEBPAGE_SYSTEM_PROMPT,
    PREV_WEBPAGE_R1021_SYSTEM_PROMPT,
    PREV_WEBPAGE_SYSTEM_PROMPT,
    WEBPAGE_SYSTEM_PROMPT,
)
from services.youtube_prompts import (
    PREV_R1022_YOUTUBE_SYSTEM_PROMPT,
    PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    PREV_YOUTUBE_R1021_SYSTEM_PROMPT,
    PREV_YOUTUBE_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

PROMPT_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "prompts.direct_chat_system_prompt": [
        (LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R8_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R9_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R2020_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R1021_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R1022_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R1023_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)],
    "prompts.summary_system_prompt": [
        (PREV_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R2020_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R1021_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R1022_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT)],
    "prompts.compress_system_prompt": [(PREV_COMPRESS_PROMPT, COMPRESS_PROMPT)],
    "prompts.checkup_system_prompt": [
        (PREV_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        (PREV_CHECKUP_R1021_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        (PREV_R1022_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT)],
    "prompts.factcheck_system_prompt": [
        (PREV_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_FACTCHECK_R2020_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_FACTCHECK_R1021_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_R1022_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT)],
    "prompts.search_system_prompt": [
        (PREV_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT),
        (PREV_SEARCH_R1021_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT),
        (PREV_R1022_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT)],
    "prompts.youtube_system_prompt": [
        (PREV_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT),
        (PREV_YOUTUBE_R1021_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT),
        (PREV_R1022_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT)],
    "prompts.youtube_video_system_prompt": [
        (PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT),
        (PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT),
        (PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT)],
    "prompts.webpage_system_prompt": [
        (PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT),
        (PREV_WEBPAGE_R1021_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT),
        (PREV_R1022_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT)],
    # 10.23 (F1, ADR-1023-1): Stage-1 промпты (Редактор саммари/Аналитик
    # фактчека) получают правило маркировки; PG-ключи добавляет F8 — до сида
    # migrate/skip (отсутствующий ключ → INFO, сид поставит канон).
    "prompts.summary_editor_system_prompt": [
        (PREV_SUMMARY_EDITOR_R1023, SUMMARY_EDITOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_EDITOR_R1023_F3, SUMMARY_EDITOR_SYSTEM_PROMPT)],
    # 10.23 (F2, ADR-1023-2 §3.3): ступень Аналитика — правило обязательного
    # веб-поиска. Старые прод-значения (pre-F1 и F1) ведут на новый канон.
    # 10.23 (F3, ADR-1023-3): ступень F3 — поле response_mode в том же JSON.
    "prompts.factcheck_analyst_system_prompt": [
        (PREV_FACTCHECK_ANALYST_R1023, FACTCHECK_ANALYST_SYSTEM_PROMPT),
        (PREV_FACTCHECK_ANALYST_R1023_F2, FACTCHECK_ANALYST_SYSTEM_PROMPT),
        (PREV_FACTCHECK_ANALYST_R1023_F3, FACTCHECK_ANALYST_SYSTEM_PROMPT)],
}
# prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)

# Обратная канон-миграция раунда 10.21 (F3 Д9, ADR-1021-3 §5): key →
# (новый канон 10.21, прежний прод-канон R1021). Нужна потому, что `git revert`
# возвращает код-константы, но НЕ откатывает значение в PG. `COMPRESS_PROMPT`
# и `extract` не входят — в 10.21 не менялись.
ROLLBACK_MIGRATIONS: dict[str, tuple[str, str]] = {
    # F1 (10.23, R1023F1-07): откат чата ведёт на непосредственный прежний
    # канон PREV_CHAT_R1023 (снимает только F1, сохраняя блоки A/B 10.21/10.22).
    "prompts.direct_chat_system_prompt":
        (CHAT_SYSTEM_PROMPT, PREV_CHAT_R1023_SYSTEM_PROMPT),
    "prompts.summary_system_prompt":
        (SYSTEM_PROMPT, PREV_R1021_SUMMARY_SYSTEM_PROMPT),
    "prompts.checkup_system_prompt":
        (CHECKUP_SYSTEM_PROMPT, PREV_CHECKUP_R1021_SYSTEM_PROMPT),
    "prompts.factcheck_system_prompt":
        (FACTCHECK_SYSTEM_PROMPT, PREV_FACTCHECK_R1021_SYSTEM_PROMPT),
    "prompts.search_system_prompt":
        (SEARCH_SYSTEM_PROMPT, PREV_SEARCH_R1021_SYSTEM_PROMPT),
    "prompts.youtube_system_prompt":
        (YOUTUBE_SYSTEM_PROMPT, PREV_YOUTUBE_R1021_SYSTEM_PROMPT),
    "prompts.youtube_video_system_prompt":
        (YOUTUBE_VIDEO_SYSTEM_PROMPT, PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT),
    "prompts.webpage_system_prompt":
        (WEBPAGE_SYSTEM_PROMPT, PREV_WEBPAGE_R1021_SYSTEM_PROMPT),
    # 10.23 (F1, ADR-1023-1): обратный шаг для новых PG-ключей F8.
    # 10.23 (F2, ADR-1023-2): правило веб-поиска. После вливания F3 (ступень
    # F2→F3) откат Аналитика ведёт на непосредственный прежний канон —
    # PREV_FACTCHECK_ANALYST_R1023_F3 (F2-правило веб-поиска в нём СОХРАНЕНО);
    # снимается только ступень F3 (response_mode). Прямой откат сразу к F1
    # (PREV_..._F2) не выражается — стек ступеней F1→F2→F3, каждая снимает
    # ровно предыдущую.
    # 10.23 (F3, ADR-1023-3): откат снимает только ступень F3 — на слепок без
    # поля response_mode (PREV_SUMMARY_EDITOR_R1023_F3/PREV_..._F3).
    "prompts.summary_editor_system_prompt":
        (SUMMARY_EDITOR_SYSTEM_PROMPT, PREV_SUMMARY_EDITOR_R1023_F3),
    "prompts.factcheck_analyst_system_prompt":
        (FACTCHECK_ANALYST_SYSTEM_PROMPT, PREV_FACTCHECK_ANALYST_R1023_F3),
}


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


async def rollback_prompt_canons(cache) -> dict[str, str]:
    """Обратная канон-миграция раунда 10.21 (F3 Д9, ADR-1021-3 §5).

    Возвращает PG-значения `prompts.*` с нового канона 10.21 на прежний
    прод-канон (`PREV_*_R1021`). Идемпотентна: повторный прогон — no-op.
    Кастом юзера не трогаем (WARNING), ключ отсутствует / PG down — skip.
    Вызывается вручную (runbook @DevOps) при откате `git revert`."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_rollback] skip: PG недоступен")
        return report
    for key, (new, old) in ROLLBACK_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[prompt_rollback] ключ отсутствует | key=%s", key)
            continue
        if current == old:
            logger.info("[prompt_rollback] уже прежний канон | key=%s", key)
            continue
        if current != new:
            logger.warning("[prompt_rollback] кастом юзера — НЕ трогаем | "
                           "key=%s | chars=%d", key, len(current))
            continue
        await cache.set(key, old, "prompts")
        report[key] = "rolled_back"
        logger.info("[prompt_rollback] канон откачен | key=%s", key)
    return report
