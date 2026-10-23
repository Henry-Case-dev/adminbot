# ASAP3 Identity — независимое ревью (LANE REV-ASAP3-IDENTITY)

Дата: 23.10.2026. Кандидат кода: `f398cb71` (HEAD `b80cdb20` — только evidence).
База для RED: `f30feb30`. Scope: source §4–§6, §8 (A1–A16), §9; arch-design §6;
diff `f398cb71`, `services/summary_aliases.py`, `bot.py`,
`services/direct_chat_service.py`, `services/summary_generator.py`,
`tests/test_asap3_identity_aliases.py`, evidence `identity-phase.md`.

## Вердикт: NEEDS FIXES — в поезд пока нельзя

Merge и live-apply для основных речевых маршрутов подтверждены. Но два явных
требования не выполнены: (1) L1/инициатива всё ещё видят исторический
`author_name` вместо действующего алиаса; (2) досье теряет факты с устойчивым
`subject_ref_id` после смены алиаса. Оба воспроизведены, оба правятся точечно.

## Покрытие пунктов задания

| # | Пункт | Итог | Доказательство |
|---|---|---|---|
| 1 | Merge по user_id | **ВЫПОЛНЕНО** | RED на `f30feb30`: `Гипербореец / Игорь` (глобальный `Леха` потерян). Кандидат: `Гипербореец / Леха / Костя`, scope_report `merged=3, chat=1, inherited=2`. `services/summary_aliases.py:93-97, 329-393`; A2/A3/A7/A8 — PASS. |
| 2 | Порядок имён | **ВЫПОЛНЕНО в резолвере** | `resolve`: chat/global alias → nickname → username → memory_name → id (`summary_aliases.py:163-198`); chat побеждает только свой uid (`:372-384`). Пустая строка/None отбрасывается (`:77-83`), не глушит global; A-empty PASS. |
| 3 | Live-apply на маршрутах | **ЧАСТИЧНО** | Middleware на каждый update (`bot.py:959`, `summary_aliases.py:267-281`); Direct `_refresh_turn_aliases` (`direct_chat_service.py:2167-2176, 2188`); инициатива (`:8684, :8783`); Summary (`summary_generator.py:721-728`). contextvar-изоляция (`summary_aliases.py:237-264`; A12 PASS). Инвалидация: `chat_params.py:489-494`, `ConfigCache.set` обновляет RAM (`config_cache.py:732-734`). Но имена в L1/инициативе — см. BLOCKER-1. |
| 4 | История/GraphRAG/досье | **ЧАСТИЧНО** | Глобальной замены строк нет; старые записи не переписываются; uid-less строки не привязываются (`_participant_roster` пропускает None/0, `:8140-8157`). Но досье — см. BLOCKER-2. |
| 5 | UserResolutionMap: один uid — одно имя | **ВЫПОЛНЕНО для карты** | `_build_alias_map`/`_participant_roster` дедупят по uid (`direct_chat_service.py:8082-8175`); A9/A11 PASS. Противоречие в L1-промпте — отдельный BLOCKER-1. |
| 6 | Тесты A1–A16 | **PASS по числам, но A13 неполон** | 20/20 PASS. A3/A7/A8/A15/A16-harness реальны; A4/A5 проверяют `bind`+view, а не `_handle_turn`/middleware; A13 не вызывает инициативу. A16-live законно postdeploy. |
| 7 | Скоуп | **ВЫПОЛНЕНО** | Код: ровно 5 файлов + тест; `web/**` и STYLE не тронуты; новых сервисов/таблиц/DDL нет. `manage.py diag` read-only. |
| 8 | Прогон | **PASS** | `test_asap3_identity_aliases.py`: 20 passed, 3.72 s. `test_summary_aliases + test_aliases_render_round1024 + round1022 + test_chat_params`: 52 passed, 4.69 s. `test_mca03_message_identity_round1027`: 25 passed, 5.54 s. `py_compile` изменённых файлов — OK. |
| 9 | Остаточные риски автора | **Один из них блокирует** | Исторические имена — BLOCKER-1; пустая строка — корректно (не блокирует); дублирующая сборка merge в `build_alias_resolver` и `merge_alias_maps` — безвредна (не блокирует). |

## BLOCKER-1. L1/инициатива получают старый `author_name` вместо алиаса

Требование: §4.1/§4.2 (алиас при обращении/отображении), §10.8 (LLM не
получает противоречивые имена одного uid), A13/ID-ROUTES (инициатива).

Факты:
- `services/direct_l1.py:809` — `render_window_lines` берёт `row["author_name"]`
  напрямую; `:837` подставляет его в строку `[user:UID] имя: текст`.
- `services/direct_chat_service.py:4182-4194` — Direct L1 передаёт в
  `build_l1_context` сырой `window`; при этом `speaker=target_name` уже алиас.
- `services/direct_chat_service.py:8711-8719` — адресат инициативы собирается
  из сырого `wr["author_name"]`.
- `:8737-8743` — инициативный L1 получает сырой `window`.
- `:8808-8813` — инициативный L2 Writer получает `<Fresh_Chat_Window>` из
  сырого `render_window_lines`.

Воспроизведение (alias `1001 = Макс`, историческая строка `author_name = Игорь`):
```
[ПОСЛЕДНИЕ СООБЩЕНИЯ]
[msg:5] [user:1001] Игорь (имя из клиента): привет
[УЧАСТНИКИ]
Говорящий: Макс
```
Один и тот же uid передан модели двумя именами; в инициативе старый `author_name`
попадает и в `<Fresh_Chat_Window>`, и в «Адресат». Это ровно тот класс ошибки,
который описан в §5 (имя из клиента при наличии алиаса).

Минимальная правка: перед `build_l1_context`/`render_window_lines` заменять
`author_name` на `self.aliases.resolve(int(uid), author_name, None)` для
Direct L1 и обоих инициативных методов; адресата резолвить так же. Добавить
тест A13 на инициативу (L1-контекст/`Fresh_Chat_Window` + адресат), чтобы
старый `author_name` не появлялся при действующем алиасе. Проверка: целевой
тест + повторный ручной вывод контекста, полный прогон не нужен.

## BLOCKER-2. Досье теряет факты с устойчивым uid после смены алиаса

Требование: §6 («не разделять досье», «не терять факты»), §10.7,
ID-MEMORY-INTEGRITY.

`web/api/chat_lore.py:865` вызывает
`db.get_persona_card(chat_id, name, limit, now)` **без** `user_id`, хотя
`_dossier_payload` получает `user_id` и передаёт его в override (`:883`).
`get_persona_card` умеет читать по устойчивому `subject_ref_id`
(`services/database.py:11003-11016, 11060-11079`), но только при переданном
`user_id`.

Воспроизведение на реальной `DatabaseService` (SQLite, факт с
`subject_ref_id` для uid=1001, старый `target_user=Игорь`, новый алиас `Макс`):
```
web path (name only): []
uid-aware path: ['Игорь любит кофе']
```
То есть после переименования веб-досье показывает пустую карточку, хотя факт
жив и имеет достоверный uid. Это не «исторический текст», а потеря отображения
уже привязанного факта.

Минимальная правка: `get_persona_card(..., user_id=user_id)` в
`web/api/chat_lore.py:865` (additive kwarg уже существует). Добавить тест:
создать факт с `subject_ref_id`, сменить алиас, проверить, что `/dossier`
возвращает факт. Legacy-строки без uid по-прежнему не привязывать — это
соответствует §6. Это изменение `web/**`, которого в кандидате нет, но без
него §6 не закрыт; правка локальная, без нового сервиса/DDL.

## Тестовые пробелы (related, не отдельный блокер)

- `tests/test_asap3_identity_aliases.py:269` (A13) не вызывает инициативу,
  хотя A13 её прямо перечисляет. A4/A5 (`:175-194`) вызывают
  `bind_turn_aliases` вручную, а не `_handle_turn`/middleware; регрессия,
  удаляющая refresh из маршрута, останется зелёной.
- A16-harness (`:377`) — корректный harness, но не фактический Telegram-путь;
  A16-live оставлен postdeploy правомерно (plan.md, §10).
- A9/A11 проверяют только карту/ростер, не L1-промпт и не досье; BLOCKER-1/2
  этими тестами не покрыты.

## Остаточные риски (не блокируют отдельно)

- `memory_name` в `AliasResolver.resolve` реализован, но production-вызовов с
  `memory_name=` нет (`rg memory_name` — только тест A1). Исторические имена
  попадают в summary/direct как `nickname` (после alias), поэтому практический
  порядок сохраняется; отдельный «verified memory» tier не подключён.
- `_build_batch_text` (`services/summary_memory.py:921-936`) сжимает историю с
  сырыми `author_name`; это обработка исторических свидетельств, не обращение
  к участнику. Если трактовать §5 максимально строго — отдельный вопрос, не
  доказанный blocker в этом кандидате.
- Non-turn пути (LoreWorker, web relations) используют стартовый fallback и
  после смены глобального алиаса могут оставаться старыми до рестарта;
  речевые маршруты это не затрагивает. Для web-досье заголовок уже live
  (`web/api/chat_lore.py:835-846`), но факты — BLOCKER-2.
- `scope_report` при `cache is None` считает слой доступным (`ok=True`), т.е.
  отсутствие chat-кэша не диагностируется; в рабочем bot кэш ставится до
  polling, поэтому риск низкий.
- `build_alias_resolver` дублирует merge вместо вызова `merge_alias_maps`;
  семантика совпадает, тесты A3/A8 проходят — стилевой/поддерживаемостный
  остаток, не блокер.

## Итог

Merge по uid и live-apply для Direct/Summary/middleware/contextvar — **да**.
Фактические маршруты — **не все**: инициатива/L1 и досье нарушают §4/§6.
После двух минимальных правок и целевых проверок (A13-инициатива, dossier
uid) кандидат можно выпускать; текущий SHA в поезд не идёт.
