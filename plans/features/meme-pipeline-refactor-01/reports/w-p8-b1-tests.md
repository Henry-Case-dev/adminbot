# P8 / B1 — три теста регресса (Builder, 03.11.2026)

Кандидат: ff35a53f (ветка feat/meme-init-coord), работа поверх него без правок
продуктового кода.
Основание: plans/features/meme-pipeline-refactor-01/reports/w-p8-review.md, блокер B1
(мутации M4/M5/M6 выживали: 45/45).

Добавлено ровно три теста в tests/test_initiative_coordination.py; изменений
product-кода нет (git diff — только тестовый файл и этот отчёт).

## 1. Тесты

1. `test_automatic_path_cannot_begin_sending_after_manual_priority`
   (раздел 7 «`/meme`: приоритет без гонки»).
   Сценарий владельца «автоматический пост откладывается или отменяется»:
   `acquire(auto) → claim_manual_priority() → begin_sending(claim_id)` даёт
   `granted=False`, `reason=publication_conflict`, `detail=manual_priority`,
   строка остаётся `claimed` с прежним `claim_id`; ручной `acquire(manual=True)`
   забирает бронь и проходит в `sending`, а авто-бронь отправить уже не может.
   Гард: предикат `manual_priority_until` в `_BEGIN_SENDING_SQL`
   (services/publication_coordination.py:192-193) — единственное разрешение
   звать sender.

2. `test_meme_phase_roster_comes_from_own_source` (раздел 1, V1).
   `_meme_phase` спрашивает `meme.meme_chat_roster` (подменён на `[CHAT]`) при
   `payload["chats"]={"-200": …}` и передаёт в `on_initiative_cycle` именно
   `[CHAT]`; в payload пишется `roster=[CHAT]`, `roster_source="roster"`,
   `separate_from_initiative=True`. Чат текстового скана в ростер не попадает.

3. `test_meme_phase_passes_chat_gate_to_meme` (раздел 1, V4 / SET-CHAT-TOGGLE).
   `_meme_phase` передаёт `chat_enabled` внутрь; для выключенного чата (-777)
   гейт даёт `False`, и реальный `on_initiative_cycle`→`consider_chat` возвращает
   `initiative_disabled`, `published=False`, что видно и в `payload["meme_chats"]`.

Подменяются только внешние швы (ростер, `chat_observer_enabled`, загрузчик
настроек); предмет проверки — реальный `_meme_phase`, реальный
`on_initiative_cycle`/`consider_chat` и реальный файл SQLite брони.

## 2. Мутации (каждая — RED, затем восстановление — GREEN)

Скрипт мутаций (байт-в-байт, LF сохранён, обратимая правка):
`C:\Users\main\.config\opencode\WorkspaceData\runs\662f20193e817541\meme-pipeline-refactor-01-b412c6be39fc\temp-ed91199ed8\mutate.py`
(временный артефакт, удалить при закрытии эпика).

Команды (из корня worktree, python = C:\Code\Python\adminbot\.venv\Scripts\python.exe):

```
$py mutate.py M4 apply
$py -m pytest tests/test_initiative_coordination.py -q -k "automatic_path_cannot_begin_sending"
$py mutate.py M4 revert
```

- M4 «убрать предикат `manual_priority_until` из `claimed → sending`»
  (services/publication_coordination.py: предикат заменён на `AND 1 = 1`):
  RED — `FAILED test_automatic_path_cannot_begin_sending_after_manual_priority`,
  `assert denied.granted is False` → получено `granted=True, state='sending'`.
  После revert: GREEN, `git status` чист по продуктовым файлам.
- M5 «вернуть ростер мем-фазы к `payload["chats"]`»
  (services/initiative_observer.py:1458): RED —
  `FAILED test_meme_phase_roster_comes_from_own_source`,
  `assert len(roster_calls) == 1` → 0 (свой источник не спрошен).
- M6 «перестать передавать `chat_enabled` из фазы»
  (services/initiative_observer.py:1468 закомментирована): RED —
  `FAILED test_meme_phase_passes_chat_gate_to_meme`,
  `assert callable(seen["chat_enabled"])` → `False` (`None`).

Все три revert'а проверены `git status --porcelain`: продуктовые файлы
возвращаются к байтам HEAD (`git diff` пуст), изменён только тестовый файл.

## 3. Прогоны (кандидат — этот worktree после revert'ов)

- tests/test_initiative_coordination.py — 48 passed (было 45, +3).
- Тот же набор из 13 файлов, что в отчёте ревью (без coordination: 275) — 275 passed.
  Итого 323 passed, 0 failed.
- Широкий прогон `-k "initiative or meme or publication or claim or direct_chat or direct_output"`
  — 839 passed, 17046 deselected (было 836; +3 новых), 90 с.
- Внешняя сеть/LLM в новых тестах не нужны: всё на реальном SQLite-файле и
  подменённых швах.

## 4. Что эти тесты НЕ доказывают

1. Тест 1 проверяет предикат брони, а не весь путь `/meme` в Telegram
   (RBAC, удаление команды, отправку фото) — это покрыто
   test_command_marks_priority_before_generation и живыми пробами P1/P2 ревью.
2. Тест 2 подменяет `meme.meme_chat_roster`, поэтому проверяет проводку, а не
   содержимое ростера (фильтры «групповой/включён/мемы вкл») — оно проверено в
   test_meme_roster_is_independent_of_text_scan.
3. Тест 3 проверяет, что гейт передан и что выключенный чат останавливается на
   нём. Он не доказывает, что включённый чат дальше доходит до публикации —
   это делают живые пробы P3.a-d ревью и test_chat_scope_stops_memes.
4. Флейк N5 и наблюдение N1 (блокирующие записи SQLite) не затронуты.
