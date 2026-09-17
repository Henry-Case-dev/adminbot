# Runbook отката канона раунда 10.21 (F2+F3)

> **Для @DevOps.** Канон промптов живёт в двух местах: код-константы (git) и
> значения PG `prompts.*` (ConfigCache читает их поверх констант). Поэтому
> `git revert` возвращает код, **но не** PG-значения. Ниже — обратный шаг
> миграции, обязательный при откате (решение владельца Д9, ADR-1021-3 §5).

## Когда применять

- Прод-ответы стали хуже/рваными после выката раунда 10.21 (F2 grounding/CoVe
  или F3 анти-бот), и принято решение откатить канон.
- Откат — **не** экстренный способ «выключить фичу» (флага нет), а полный
  возврат к канону до 10.21.

## Порядок отката

1. **Код:** `git revert <commit-раунда-10.21>` (одним коммитом F2+F3).
2. **PG:** вызвать обратную канон-миграцию:

   ```python
   from services.prompt_migrations import rollback_prompt_canons
   await rollback_prompt_canons(config_cache)
   ```

   Функция переводит каждый ключ с нового канона 10.21 на слепок прежнего
   прод-канона `PREV_*_R1021`. Идемпотентна: повторный прогон — no-op.
   Кастомные (отредактированные вручную) значения НЕ трогаются.

## Ключи, которые откатываются (8)

| PG-ключ | Новый канон → слепок |
|---|---|
| `prompts.direct_chat_system_prompt` | `CHAT_SYSTEM_PROMPT` → `PREV_CHAT_R1021_SYSTEM_PROMPT` |
| `prompts.factcheck_system_prompt` | `FACTCHECK_SYSTEM_PROMPT` → `PREV_FACTCHECK_R1021_SYSTEM_PROMPT` |
| `prompts.search_system_prompt` | `SEARCH_SYSTEM_PROMPT` → `PREV_SEARCH_R1021_SYSTEM_PROMPT` |
| `prompts.summary_system_prompt` | `SYSTEM_PROMPT` → `PREV_R1021_SUMMARY_SYSTEM_PROMPT` |
| `prompts.webpage_system_prompt` | `WEBPAGE_SYSTEM_PROMPT` → `PREV_WEBPAGE_R1021_SYSTEM_PROMPT` |
| `prompts.youtube_system_prompt` | `YOUTUBE_SYSTEM_PROMPT` → `PREV_YOUTUBE_R1021_SYSTEM_PROMPT` |
| `prompts.youtube_video_system_prompt` | `YOUTUBE_VIDEO_SYSTEM_PROMPT` → `PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT` |
| `prompts.checkup_system_prompt` | `CHECKUP_SYSTEM_PROMPT` → `PREV_CHECKUP_R1021_SYSTEM_PROMPT` |

`prompts.compress_system_prompt` и `prompts.extract_system_prompt` в 10.21
**не менялись** — в откате не участвуют.

## Проверка

- `rollback_prompt_canons` вернул отчёт по 8 ключам со значением
  `rolled_back` (или пусто при повторном прогоне).
- Ручной smoke: ответы снова без блоков A/B; `factcheck` снова без CoVe.
- Grounding-валидатор (`services/grounding_validator.py`) **аддитивен**:
  при откате канона он остаётся безопасным, но фантомные теги уже не
  появляются, потому что старый канон их и не требовал. Отдельного
  «выключения» валидатора не требуется.
