# P0 HOTFIX — full production-context probe (LANE FULL-PRODUCTION-PROBE)

Статус: **частично выполнено, НЕ VERIFIED.** Время лейна (≤75 мин) закончилось на
этапе, когда read-only сбор контекста и staging нового кода на сервере уже
доказаны, а прогоны L1/L2 (12 LLM-вызовов) и 9 проверок §5 ещё не выполнены.

- Read-only. Сообщений в Telegram нет, deploy не выполнялся, INSERT/UPDATE/DELETE нет.
- PG открывался с `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`;
  сервер подтвердил `SHOW transaction_read_only = on`.
- SSH: **2 коннекта** (оба — успешная аутентификация с первой попытки, без
  перебора; после неуспешного auth повторов не было).
- Кандидат кода: **9650e099** (`task/speech-p0-hotfix`), прод: **534ac7dd** (2.58.130).

## 1. Что доказано фактически

| Проверка | Результат | Доказательство |
|---|---|---|
| Новый код развёрнут рядом с продом без изменения прода | `/tmp/p0-full-new` (tar, py-only, 11.5 MB) | `harness_stage_dump.py`, лог `stage` |
| Новый код импортируется штатным venv прода | `IMPORT_OK /tmp/p0-full-new/services/direct_l1.py` | те же логи |
| В staging действительно новый код, а не прод | `_renders_extent_block`: new **2**, prod **0** | лог `stage` |
| Прод не изменён | `git -C /var/www/admin_bot rev-parse --short HEAD` = `534ac7dd` до и после | лог `stage` |
| PG читается только на чтение | `read_only: "on"` | `context_structure.json` |
| Окно чата реальное | 70 сообщений [-1002661910336], `timestamp` ∈ [A−5400, B+600], авторы Ринтаро/Костя/Славик/Никита/Гоша/Макс/Кировский/Aleksey | `p0_sqlite_dump.json` (локально, не в git) |

## 2. Что выяснилось про источники (важно для следующего прогона)

1. **PG не содержит** `graph_facts`, `lore_stories`, `chat_running_summary`,
   `summary_runs`, `smart_messages` — запросы вернули
   `relation ... does not exist`. Эти слои живут в **SQLite**
   `/var/www/admin_bot/local_database.db`. Прошлое evidence (`probes_prod.md` §3)
   формулировало Core как «PG `character.core`» — таблицы документов персонажа в
   `public` по моему обходу `information_schema` не нашлось; перед следующим
   прогоном источник Core нужно переустановить по факту (SQLite-док-стор или
   отдельная схема), а не по прошлой формулировке.
2. **`bot_settings` хранит живые ключи провайдеров в открытом виде**. Дамп этой
   таблицы нельзя ни коммитить, ни складывать в scratch. Локальная копия дампа
   удалена сразу после извлечения структуры; в git попал только структурный
   файл без значений (`context_structure.json`).
3. **`/tmp` на проде заполнен на 96%** (1.1 GB свободно). Полный `rsync` дерева
   падает на `backups/pre_deploy_*.db`. Рабочий вариант — staging только `.py`
   (tar 11.5 MB) + копия `.env` из прода; именно он использован.
4. Персональные слои доступны и читаются: `personas` (1 строка, пустые
   `biography`/`system_prompt_overrides`), `persona_traits` (50, `source=deep_sleep`),
   `chat_profiles.manual_lore`/`auto_lore` (длинные реальные тексты),
   `persona_state` (`last_extract_status=ok`, 2026-10-24T20:26Z).

## 3. Что НЕ выполнено (и почему это блокирует §5)

Не сделано: реальный L1 Planner old/new, реальный L2 Writer с его планом
(2 повтора на кейс), финальные system/user длины, 9 проверок §5 цитатами,
повтор self-echo на `graph_facts.id=21255` / `lore_stories.id=4`.

Причина: окончился бюджет лейна; подготовлены все входы (реальные тексты, окно,
staging нового кода, read-only доступ) и инструмент дампа. Оставшаяся работа —
механическая, но требует ещё одного SSH-сеанса (SQLite-слои: graph/lore/summary/
lessons) и 12 LLM-вызовов.

**Ни один пункт §5 не помечен VERIFIED. Deploy не выполнялся и не разрешён этим
документом.**

## 4. Подготовленный инструмент

- `probes_full/harness_stage_dump.py` — один SSH-сеанс: staging только `.py` в
  `/tmp/p0-full-new`, проверка импорта штатным venv, read-only дамп PG + окна
  SQLite, выгрузка JSON. Проверен фактическим запуском (2 коннекта, 67.7 s).
- `probes_full/harness_dump_context.py` — серверный дамп: PG в режиме
  `transaction_read_only=on`, SQLite `mode=ro`.

Следующий прогон обязан: исключить `bot_settings` из дампа, добавить SQLite-слои
(`graph_facts`, `lore_stories`, `chat_running_summary`, `summary_runs`,
`mca_lessons`), затем выполнить L1/L2 по 2 повтора и закрыть §5 цитатами.
