# ASAP3 Identity — повторное ревью после исправлений (LANE REV-ASAP3-IDENTITY-R2)

Дата: 23.10.2026. Кандидат кода: `bfc1236682e3e4e1b6f494c00d1cb5142b36a377`
(evidence-коммит `82b9737a40d1ac9cae2b8a2b11a56eb5848bc9bc` — только docs).
База сравнения: `f30feb30ed56649e27088acce78b354129a94242`; кандидат предыдущего
ревью (R1): `f398cb7199205ce5ee1579b6aa0a18c720e5fa6c`.
Файл — единственная запись этой полосы; код/карты/прод не изменялись.

## Вердикт: APPROVED (полоса identity) — в поезд можно

Оба блокера R1 закрыты фактически, а не переименованием статуса: имена в Direct L1,
инициативном L1/L2 и у адресата идут через действующий резолвер по uid; веб-досье
читает факты по устойчивому `subject_ref_id`. Скоуп исправления узкий, merge/порядок
имён и стилевые модули не менялись. Остаточные пункты ниже — тестовая прочность и
косметика, релиз не блокируют. A16-live остаётся postdeploy (DevOps), parent не DONE.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| Блокер 1: L1/инициатива/адресат по uid, а не `author_name` | **VERIFIED** | см. ниже, probe + A13 |
| Блокер 2: досье по `subject_ref_id` после переименования | **VERIFIED** | см. ниже, probe на реальной SQLite |
| Нет ослаблений (merge/порядок/скоуп) | **VERIFIED** | `summary_aliases.py` не менялся с R1; rework = 4 файла |
| Прогоны 22/52/25/40/51 | **VERIFIED** | все совпали с evidence |
| A13 действительно покрывает инициативу | **VERIFIED (с оговоркой)** | реальный `plan_initiative_decision`; L2 — через тот же рендер, не через сервисный метод |
| A4/A5: refresh проверен через `bind`, не `_handle_turn` | **NONBLOCKING** | код живёт в 3 местах, включая middleware; тест не ловит удаление проводки |
| A16 live | **READY_FOR_LIVE** | postdeploy DevOps, вне полосы |

## Блокер 1 — закрыт

Код:
- `services/direct_l1.py:797-845` — `render_window_lines(..., alias_resolver=None)`;
  имя строки резолвится по `row["user_id"]`, `author_name` остаётся только
  nickname-фолбэком, строки истории не переписываются; без резолвера — прежний
  формат (обратная совместимость).
- `services/direct_l1.py:648-683` — `build_l1_context` пробрасывает резолвер в окно.
- `services/direct_chat_service.py:4195` (Direct L1), `:8745-8751` (инициативный L1),
  `:8816-8817` (L2 `<Fresh_Chat_Window>`) — передают `self.aliases`.
- `services/direct_chat_service.py:8710-8728` — адресат инициативы: сначала
  `self.aliases.resolve(addressee_id, historical_name, None)`, исторический
  `author_name` — только фолбэк; при отсутствии имени метка без имени (id как имя
  не подставляется).
- Окно для этих путей реально содержит `user_id`: `services/database.py:7537`
  (`get_smart_window`) → `summary_memory.py:2698`. Интеграционное допущение держится.

Независимое воспроизведение (реальные `DirectChatService`/`build_l1_context`, alias
`1001=Гипербореец`, историческая строка `author_name="Игорь (из клиента)"`):

```
УЧАСТНИКИ (_build_alias_map): Гипербореец — 1001
окно:     [msg:5] [user:1001] Гипербореец: привет
без резолвера (до фикса): [msg:5] [user:1001] Игорь (из клиента): привет
Адресат:  участник Гипербореец [user:1001]
L1-промпт: "Гипербореец" есть, "Игорь (из клиента)" отсутствует
L2-окно:  [msg:5] [user:1001] Гипербореец: привет
```

Один uid даёт одно имя на всех пяти поверхностях. A13-initiative
(`tests/test_asap3_identity_aliases.py:380-409`) вызывает настоящий
`plan_initiative_decision` с fake-LLM и проверяет окно L1 + адресата + отсутствие
старого имени; RED на прежнем коде — `TypeError` по новому kwarg, поведенческий RED
зафиксирован в R1 (`[msg:5] [user:1001] Игорь (имя из клиента)`).

## Блокер 2 — закрыт

`web/api/chat_lore.py:865-866` — `get_persona_card(..., user_id=user_id)`.
`services/database.py:11003-11016, 11041-11084` уже умеет субъект-scope:
`subject_ref_id = ref` OR `(subject_ref_id IS NULL AND target_user = имя)`;
`mca_gates.fact_attribution_enabled()` — default ON (`services/mca_gates.py:742-751`),
т.е. в проде путь активен без флагов.

Независимое RED/GREEN на реальной `DatabaseService` (факт с `subject_ref_id`, старый
`target_user="Игорь"`, новый алиас «Гипербореец»; плюс legacy-строка без uid):

```
GREEN /dossier (uid-aware): ['Игорь любит кофе']
RED   name-only:            []
```

То есть после переименования факт не теряется, legacy без uid по-прежнему не
привязывается к uid (совпадение только по имени остаётся прежним поведением
`_person_scope_clause`).

## Нет ослаблений

- `git diff f398cb71..bfc12366`: только `services/direct_chat_service.py`,
  `services/direct_l1.py`, `tests/test_asap3_identity_aliases.py`, `web/api/chat_lore.py`.
  Merge по uid, каскад, `LiveAliasView`/contextvars, `bot.py` не тронуты с R1.
- `services/prompt_style_blocks.py` и `services/style_policy.py` в диапазоне
  `f30feb30..bfc12366` не изменялись.
- `web/**` в самом identity-rework не менялся кроме `chat_lore.py`; остальные
  web-файлы в диапазоне принадлежат отдельной ui-полосе (`02434414`).
- История не переписывается: изменения только в чтении/рендере.

## Прогоны (мои, на кандидате)

| Набор | Результат |
|---|---|
| `test_asap3_identity_aliases.py` | **22 passed** (3.85 s) |
| `test_summary_aliases` + `test_aliases_render_round1024` + `round1022` + `test_chat_params` | **52 passed** (5.12 s) |
| `test_mca03_message_identity_round1027` | **25 passed** (5.50 s) |
| `test_chat_lore_api` + `test_chat_lore_participant_names_round1024` | **40 passed** (8.22 s) |
| `test_direct_l1_l1d_contract` + `test_direct_l1_corrective_r1` + `test_asap2_clar_contract` | **51 passed** (3.05 s) |

Дополнительно прогнаны `test_chat_lore.py` + `test_chat_lore_store.py` +
`test_seed_chat_lore.py` — все зелёные (входят в 119 по пяти файлам). Числа в
`identity-phase.md` §6 совпадают с фактическими.

## Остаточное (не блокирует поезд)

1. **A4/A5 не проверяют проводку.** Тесты вызывают `bind_turn_aliases` вручную;
   удаление `_refresh_turn_aliases` из `_handle_turn`/middleware останется зелёным.
   Функционально риск низкий: refresh есть в middleware (`bot.py:959`), в
   `_handle_turn` (`:2176-2188`) и в Summary (`summary_generator.py:723`), т.е.
   потеря одной точки не отключает live-apply. Рекомендация на потом (backlog, не
   сейчас): один интеграционный тест «update → middleware → resolver обновился».
2. **Косметика рендера:** при пустом `author_name` и отсутствии алиаса строка
   получает uid в роли имени — `[msg:9] [user:4242] 4242: текст` (до фикса было
   `?:`). Противоречия имён нет, uid и так в скобках; однострочная правка:
   после resolve, если `str(author) == str(row_uid)` → `raw_author or "?"`.
3. **Док-неточность:** таблица A1–A16 в `identity-phase.md` §3 указывает для A13
   только `test_a13_direct_summary_tool_and_media_share_one_order`; новый
   инициативный A13 описан в §6. На выводы не влияет.
4. **A13-L2** проверяет `render_window_lines` напрямую, а не `_compose_l2_context`;
   проводка подтверждена чтением `direct_chat_service.py:8816-8817`.

## Итог для поезда

Полосу identity можно включать в релиз вместе с остальными принятыми полосами;
живая A16-проверка (`diag aliases --show-names` + реальный ход) — после деплоя у
DevOps. Повторное ревью при новом изменении кода identity-маршрутов обязательно.
