"""SOUL-1 / W4 — SOUL-AMD.2.6: авторские тексты (сны/ностальгия/лор/истории).

Уточнение владельца §2.1: сны, глубокий сон, рассказы о них, ностальгия, лор,
истории и воспоминания — это ПУБЛИЧНАЯ речь бота. Она получает Core и
жанровые правила, а не служебный нейтральный текст.

Модуль не вводит второго писателя и не меняет жанровые контракты: он
собирает system-строку ЧЕРЕЗ существующий композер (или возвращает прежний
канон байт-в-байт, когда композер выключен — паритет W2 сохраняется), а
жанровые правила живут в реестре промптов (`genre.*.rules`) как заводские
редакции.

Что покрыто в этом слайсе: жанровая рамка + проводка пути «Ностальгия»
(реальная публикация в чат). Сны/лор/истории получают зарегистрированные
жанровые редакции и готовый хелпер, но их публикующие пути проводятся
следующим слайсом — это честно отмечено в отчёте, а не выдано за готовое.
"""

from __future__ import annotations

import logging

from services import prompt_composer as pc

logger = logging.getLogger(__name__)

#: Жанры авторских текстов (закрытый набор).
GENRES: tuple[str, ...] = ("nostalgia", "dream", "lore", "story")

GENRE_NOSTALGIA_RULES = (
    "<Genre_Nostalgia>\n"
    "Воспоминание звучит твоим живым голосом, а не архивной справкой: "
    "по-свойски, с иронией и местным сленгом, будто вспомнил вслух. Реальные "
    "события, даты и реплики участников не выдумывай. Служебное слово "
    "отказа из канона канала остаётся неизменным.\n"
    "</Genre_Nostalgia>"
)

GENRE_DREAM_RULES = (
    "<Genre_Dream>\n"
    "Сон — это связная история твоим голосом, а не отчёт о данных: "
    "наблюдение, деталь, неожиданный поворот и вывод. Не выдавай сон за "
    "реальные события чата и не приписывай участникам того, чего не было.\n"
    "</Genre_Dream>"
)

GENRE_LORE_RULES = (
    "<Genre_Lore>\n"
    "Лор чата рассказывай как свою историю: имена, события и связи бери "
    "только из проверенных данных, не выдумывай подробностей, но и не "
    "пересказывай нейтрально — подача твоя, живая.\n"
    "</Genre_Lore>"
)

GENRE_STORY_RULES = (
    "<Genre_Story>\n"
    "История или творческий текст — твой жанр: держи внутреннюю логику, "
    "конкретные детали и развитие, но не подменяй факты чата вымыслом и не "
    "выдавай сочинённое за произошедшее.\n"
    "</Genre_Story>"
)

GENRE_RULES: dict[str, str] = {
    "nostalgia": GENRE_NOSTALGIA_RULES,
    "dream": GENRE_DREAM_RULES,
    "lore": GENRE_LORE_RULES,
    "story": GENRE_STORY_RULES,
}

#: Гиперссылки на блоки реестра (жанровая рамка = управляемая редакция).
GENRE_BLOCK_IDS: dict[str, str] = {
    "nostalgia": "genre.nostalgia.rules",
    "dream": "genre.dream.rules",
    "lore": "genre.lore.rules",
    "story": "genre.story.rules",
}


def genre_rules(genre: str) -> str:
    return str(GENRE_RULES.get(str(genre), ""))


def genre_base_prompt(genre: str, legacy_canon: str) -> str:
    """Жанровая рамка + прежний канон (канон не выбрасывается).

    Функциональные контракты канона (например служебное слово отказа)
    остаются на месте: жанровая рамка задаёт голос, а не подменяет формат.
    """
    rules = genre_rules(genre)
    canon = str(legacy_canon or "")
    if not rules:
        return canon
    return f"{rules}\n\n{canon}"


async def authorial_system(*, chat_id: int, writer: str, genre: str,
                           legacy_canon: str, channel: str = "plain",
                           html_safe: bool = False) -> tuple[str, object]:
    """System-строка авторского текста: композер ON → Core + жанр, OFF → канон.

    Возврат ``(system_text, manifest|None)``. Никогда не бросает: сбой сборки
    → прежний канон (честная деградация, беседа не блокируется).
    """
    if not str(genre_rules(genre)).strip():
        return str(legacy_canon or ""), None
    try:
        gates = await pc.resolve_gates(int(chat_id))
        if not pc.composer_enabled_now(gates):
            return str(legacy_canon or ""), None
        snapshot = await pc.turn_snapshot(int(chat_id), None)
        plan = pc.PromptPlan(
            profile=pc.PROFILE_SPEECH_PLAIN, writer=str(writer),
            chat_id=int(chat_id), channel=str(channel),
            html_safe=bool(html_safe),
            base_prompt=genre_base_prompt(genre, legacy_canon),
            base_source="default",
            include_mode_block=False,
            core=snapshot.core,
            style_policy=snapshot.style_policy,
            gates=gates)
        manifest = pc.compose_prompt(plan)
        return manifest.system, manifest
    except Exception:
        logger.warning("[authorial] composer build failed — прежний канон "
                       "| writer=%s | genre=%s", writer, genre, exc_info=True)
        return str(legacy_canon or ""), None
