# ASAP3 Corrective — Identity phase (lane ASAP3-IDENTITY)

Дата: 23.10.2026. Источник: `source-2026-10-23.md` §4–§6, §8 (A1–A16), §9;
архитектура: `arch-design.md` §6. Продакшен/сеть/живые сообщения не
использовались (ограничение полосы).

## 1. Первопричина

1. **Словари заменяли друг друга целиком.** `build_alias_resolver` читал
   чатовый override через `chat_params.get_chat_param`, который при наличии
   override возвращает **только** чатовое значение
   (`services/chat_params.py:354-377`, HEAD-версия
   `services/summary_aliases.py:78-102`). Пример до фикса (RED-проба на
   HEAD-коде, `old_aliases.py` + подмена `get_chat_param`):

   ```
   OLD uid1001: Гипербореец
   OLD uid1002: Лёша  (global 'Леха' потерян)
   NEW uid1002: Леха
   ```

   То есть при частичном чатовом словаре глобальные алиасы пропадали, и
   `resolve()` уходил на Telegram nickname — это и есть наблюдаемое
   «имя из клиента владельца вместо алиаса Adminbot».
2. **Снапшот на старте.** `bot.py:463/697` (HEAD) создавал `AliasResolver`
   один раз и раздавал его по DI. Сохранённый алиас не попадал в уже
   созданный экземпляр; обратная карта `_by_name` тоже оставалась старой.
3. **Разные каскады.** Часть модулей имела собственные обходы
   (`handlers/summary.py`, `media_common.py`, `tool_router.py` и др.);
   единого владельца порядка не было.

## 2. Что изменено

### 2.1 Merge по каждому Telegram ID — `services/summary_aliases.py`

- `parse_alias_map(raw)` (`:88`): JSON-строка/dict, в т.ч. **двойное
  кодирование**; ключи нормализуются к `str(int(user_id))`; пустые/`None`/
  нечисловые ключи отбрасываются (пустая строка не переименовывает и не
  подавляет глобальный алиас).
- `merge_alias_maps(global_raw, chat_raw)` (`:93`): global, затем chat
  перекрывает **только свой** user_id. Отсутствие ключа = наследование;
  удаление чатового = возврат глобального; удаление глобального = следующий
  источник.
- `build_alias_resolver(chat_id)` (`:329`) сохраняет сигнатуру и строит
  резолвер из merge. `scope_report` (`ok`, `scope`, `global`, `chat`,
  `inherited`, `merged`, `dropped`, `invalid_json`) — для A15/диагностики.
  Сбой чтения chat-слоя больше не маскируется: `ok=false` + WARNING, при
  этом используется доступный глобальный слой.
- `AliasResolver.resolve(user_id, nickname, username, memory_name=None)`
  (`:163`): единый каскад **chat alias → global alias → nickname →
  username → verified memory_name → user_id**. `memory_name` принимается
  только как уже проверенная привязка к этому uid; поиска по сходству строк
  нет.
- `canon_name(name, user_id=None)` (`:145`): при известном uid возвращает
  действующий алиас; обратная карта строится только по уникальным
  display-именам (два uid с одинаковым именем не сливаются).

### 2.2 Live-apply без рестарта

- `LiveAliasView` (`:201`) — стабильный DI-объект; `resolve`/`canon_name`
  делегируют резолверу текущего asyncio-контекста, стартовый снапшот —
  только fallback для путей без chat_id.
- `bind_turn_aliases(chat_id)` (`:256`) собирает per-chat резолвер заново и
  кладёт его в `ContextVar`: параллельные задачи чатов не видят чужие
  overrides (A12).
- `bot.py`: DI получает `LiveAliasView` (`:472`), зарегистрирован
  `alias_scope_middleware` на `dp.update` (`:959`) — handlers/media/tool
  видят сохранённое значение уже в следующем update.
- Direct: `_refresh_turn_aliases` в начале `_handle_turn` (`:2167/2188`) и
  в инициативе (`:8684/8783`). Summary: перед `_run` в
  `generate_and_send` (`services/summary_generator.py:723`).
- Инвалидация — существующая: `set_chat_params` чистит кэш
  (`services/chat_params.py:489-494`), `ConfigCache` обновляется при
  сохранении; TTL 120 с не является единственным путём.

### 2.3 Память/GraphRAG/досье

История не переписывается, глобальной замены строк нет. Старые
`author_name` остаются исходными данными; при известном uid отображение
идёт через действующий алиас (`_participant_roster`, `UserResolutionMap`,
Summary quotes). `MemoryManager.aliases` получает тот же live-view, поэтому
канонизация **новых** фактов идёт по текущему алиасу, старые факты не
перепривязываются. Записи без достоверного uid автоматически не
привязываются (правило единственности `provenance` не менялось).

### 2.4 Диагностика

`python manage.py diag aliases --chat-id <id> --show-names` — read-only:
global/chat/effective/source по каждому user_id, плюс
`display_collisions` («один display — разные uid», без слияния). Без
`--show-names` вывод прежний R17-safe (только форма/число ключей),
существующий контракт `tests/test_aliases_render_round1024.py` сохранён.

## 3. Тесты A1–A16

Новый durable-файл `tests/test_asap3_identity_aliases.py` (20 тестов,
CONTRACT/REGRESSION/INTEGRATION). Все — PASS.

| ID | Тест | Результат |
|---|---|---|
| A1 | `test_a1_global_alias_beats_nickname_username_memory` | PASS |
| A2 | `test_a2_chat_alias_wins_only_in_its_chat` | PASS |
| A3 | `test_a3_partial_chat_map_inherits_global_aliases` | PASS |
| A4 | `test_a4_global_change_applies_next_turn` | PASS |
| A5 | `test_a5_chat_change_applies_next_turn_without_restart` | PASS |
| A6 | `test_a6_after_restart_saved_aliases_apply` | PASS |
| A7 | `test_a7_delete_chat_override_returns_global` | PASS |
| A8 | `test_a8_delete_global_alias_returns_next_source` | PASS |
| A9 | `test_a9_one_uid_many_historical_names_is_one_person` | PASS |
| A10 | `test_a10_old_author_name_does_not_override_alias` | PASS |
| A11 | `test_a11_old_graphrag_name_does_not_override_in_resolution_map` | PASS |
| A12 | `test_a12_parallel_chats_do_not_leak_overrides` | PASS |
| A13 | `test_a13_direct_summary_tool_and_media_share_one_order` | PASS |
| A14 | `test_a14_quotes_and_history_text_untouched` | PASS |
| A15 | `test_a15_unavailable_config_is_diagnosed_not_silent`, `test_a15_invalid_json_is_diagnosed` | PASS |
| A16 | `test_a16_harness_telegram_id_to_context_and_result` | PASS (harness) |

Дополнительно: `test_empty_alias_value_does_not_rename_or_hide_global`,
`test_double_encoded_global_json_still_merges`,
`test_diag_aliases_merged_view_only_with_show_names`.

A16 harness — реальный путь без Telegram-сети: fake PG-участники →
`_active_participants` → `_build_alias_map` (`UserResolutionMap`) →
`_resolve_name`. Живая production-проверка A16 остаётся postdeploy (DevOps):
полоса запрещает прод/SSH/живые сообщения.

## 4. Прогон (числа)

Команда (`.venv\Scripts\python.exe -m pytest ... -q`):

```
tests/test_asap3_identity_aliases.py
tests/test_summary_aliases.py
tests/test_104_backend_additions.py
tests/test_aliases_render_round1024.py
tests/test_aliases_render_round1022.py
tests/test_chat_params.py
tests/test_direct_chat.py
tests/test_summary_handlers.py
tests/test_summary_generator.py
tests/test_graphrag_memory.py::TestMemorizeParticipantCanonMap
tests/test_dossier_feed_round1024.py
tests/test_hot_migration.py
tests/test_asap8_f5_module_truth.py
tests/test_asap8_f7_stories.py
tests/test_asap8_v63_b06_summary_scope.py
tests/test_soul1_w5_initiative_vitality.py
tests/test_soul1_direct_prompt_reads.py
tests/test_direct_chat_concurrency.py
tests/test_direct_context_composer_asap3.py
```

Результат: **530 passed, 1 warning** (Starlette/httpx deprecation), 25.21 s.
Отдельно: `test_mca03_message_identity_round1027.py` — 25 passed;
`test_cfg03_param_audit.py` — 17 passed; `test_aliases_render_round1022.py`
— 8 passed.

## 5. Что осталось / риски

- **A16 live** и production-диагностика merged-вида — после штатного
  деплоя DevOps (`diag aliases --show-names`), не в этой полосе.
- Память: старые факты/досье остаются под историческими канон-именами
  (запрет глобальной замены). Новые факты канонизируются по действующему
  алиасу; факты не теряются и не перепривязываются. Это осознанное
  ограничение §6, не дефект.
- Пустая строка в чатовом словаре трактуется как отсутствие значения →
  наследование глобального. Явного «удалить глобальный алиас в этом чате
  пустой строкой» нет — удаление делается удалением ключа/слоя (так же
  трактует `parse_alias_map` и архитектура §6).
- Дублирующая сборка резолвера (middleware + Direct turn) оставлена
  намеренно: `chat_params`/`hot` читаются из кэша, стоимость мала, зато
  прямой вызов сервиса в тестах/фоновых путях не зависит от middleware.

## 6. Rework после review-identity (Needs Fixes)

### BLOCKER-1 — L1/инициатива получали старый `author_name`

- Было: `services/direct_l1.py:809` брал `row["author_name"]` напрямую, а
  `direct_chat_service.py:4182-4194/8737-8743/8808-8813` передавали окно
  без резолвера; адресат инициативы (`:8711-8719`) — тоже сырой
  `author_name`. RED: один uid 1001 → `[user:1001] Игорь (имя из клиента)`
  в окне и `Говорящий: Макс` в «УЧАСТНИКИ».
- Стало: `render_window_lines(..., alias_resolver=...)` и
  `build_l1_context(..., alias_resolver=...)` (`direct_l1.py:795,648-656,678`)
  резолвят имя по известному `user_id` перед рендером. Direct L1
  (`direct_chat_service.py:4182`), инициативный L1 (`:8737`), адресат
  (`:8709-8724`) и L2 `<Fresh_Chat_Window>` (`:8808`) получают
  `self.aliases`. История/`author_name` не переписываются.
- GREEN: `test_a13_initiative_l1_and_l2_use_alias_not_author_name` — один
  uid даёт `Гипербореец` в «УЧАСТНИКИ», адресате, окне L1 и L2; старого
  имени в промпте нет.

### BLOCKER-2 — веб-досье теряло факты с устойчивым uid

- Было: `web/api/chat_lore.py:865` вызывал `get_persona_card(chat_id, name,
  limit, now)` без `user_id`; после переименования `target_user=Игорь`
  факт с `subject_ref_id=1` не находился по новому имени → пустая карточка.
- Стало: `get_persona_card(..., user_id=user_id)` (`:865-866`);
  additивный kwarg уже читает `subject_ref_id`. Legacy-строки без uid
  по-прежнему не привязываются автоматически.
- GREEN: `test_dossier_keeps_fact_with_stable_uid_after_rename` на реальной
  `DatabaseService`: uid-aware досье содержит «Игорь любит кофе», legacy
  без uid — нет; отдельная RED-проверка подтверждает, что name-only путь
  этот факт не находит.

### Целевые числа rework

- `tests/test_asap3_identity_aliases.py` — **22 passed** (было 20).
- `test_summary_aliases + test_aliases_render_round1024 + round1022 +
  test_chat_params` — **52 passed** (без нового identity-файла).
- `test_mca03_message_identity_round1027` — **25 passed**.
- `test_chat_lore_api + test_chat_lore_participant_names_round1024` —
  **40 passed**.
- `test_direct_l1_l1d_contract + test_direct_l1_corrective_r1 +
  test_asap2_clar_contract` — **51 passed**.
- Полный прогон не запускался (рамки полосы).

Rework code commit: `bfc1236682e3e4e1b6f494c00d1cb5142b36a377`.

## 7. Кандидат

Code commit: `f398cb7199205ce5ee1579b6aa0a18c720e5fa6c`
(ASAP3 identity: merge aliases by user_id, live per-turn resolver, merged
diag). Evidence-файл коммитится отдельным docs-коммитом поверх него.
Rework-коммит: `bfc1236682e3e4e1b6f494c00d1cb5142b36a377`.
