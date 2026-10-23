# REL-258119 — точка откага и цепочки Core/Checkup/Expression

## Прод

* Действующий прод перед этим поездом: `9ed68ee8` (2.58.118), healthz 200.
* Общая точка отката поездов 115–119: `e9f7595b` (2.58.114).
* Откат поезда: `git checkout -fq 9ed68ee8 && systemctl restart admin_bot` → 2.58.118.

## Код

Поезд — Fast-forward поверх `81431843`. Обратный ход:

* `git revert 90915aec` — bump (только токены версии/F8-метапин);
* `git revert c0cfba4d 6613c883` — фикстуры/швы (тесты, evidence);
* `git revert a985af19 c3ed71a3 ce376934 c43d0363 0d98ea29 022ec0a1 466d4dfb`
  — содержательные коммиты (порядок обратный).

## Core (Personality Core)

Core хранится в PG (`character.core`) как **владельческий** текст.

* Поезд меняет только **заводскую** редакцию: `core.personality`
  `2ab417d11404 → 5597c09dd5f8`, `core.personality.compact`
  `9e6a4ec8b1ea → 8dbb8c10ddc6` (+ абзац «Как говорить о реальных событиях»,
  идемпотентный owner-preserving патч `owner_preserve_core_full_patch`).
* Кастом владельца не перезаписывается: патч вставляет абзац только при
  отсутствии смысла (якорь/пара маркеров), повторный прогон — no-op.
* Откат: `git revert` + Factory Default для Core (вернёт заводскую редакцию
  предыдущего поезда). Владельческий текст при откате не теряется — он и не
  переписывался.

## Checkup

Лестница `ROLLBACK_MIGRATIONS["prompts.checkup_system_prompt"]` (2 ступени):

| Шаг | from sha12 | to sha12 | Смысл |
|---|---|---|---|
| 1 | `0f5fb7b8d25c` | `38d63d86b54d` | снять только ступень P0 → прод-канон 2.58.118 |
| 2 | `38d63d86b54d` | `0ce06cb149f8` | историческая ступень CFG-07A (2.58.100) |

`rollback_prompt_canons()` снимает ровно одну ступень за вызов; на последней —
no-op. Кастом владельца (не точное совпадение байт) не трогается (WARNING).
Идемпотентность и сохранение кастома закреплены
`tests/test_p0_checkup_core_contract.py::test_checkup_migration_is_idempotent_and_keeps_owner_custom`.

## Expression (FREQUENT)

* Новая редакция `PROFANITY_INSTRUCTIONS["frequent"]` (P0-E §6.3): «мат —
  привычная и заметная часть твоей собственной речи».
* Прежний прод-текст сохранён байт-в-байт: `PREV_PROFANITY_FREQUENT_TEXT`,
  ступень `expression_text_ladder` (`prev_sha12`/`next_sha12`).
* Откат: `git revert` + `rollback_profanity_frequent_text()` (возвращает
  прежнюю формулировку). `off`/`occasional` не менялись.

## Данные

ΔDDL = 0, миграций схемы нет. Бэкап БД не требуется для отката кода; прежняя
точка восстановления 2.58.114 остаётся схема-совместимой.
