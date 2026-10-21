# REL-258108 pins24 — пробег 24 py пин-файлов

**868 passed / 0 failed, EXIT 0** — паритет с прецедентами 101–107.

Команда: `.venv/Scripts/python.exe -m pytest <24 py пин-файла> -q -p no:cacheprovider`
(полный лог — `pins24-full.txt`).

Интерпретатор — строго venv (requirements.txt: `aiogram>=3.31.0`). Первичный
прогон этого лейна глобальным `py -3` (aiogram 3.29.1,
`InputRichMessage.model_fields` без `media` → `_rich_media_supported()` = False)
давал обусловленный красный 1 failed / 867 passed на rich-publish тесте —
диагностировано и перезапущено в venv (см. README, «Замечания»).
