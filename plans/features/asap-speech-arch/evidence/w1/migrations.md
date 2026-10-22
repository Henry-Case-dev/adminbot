# W1 Миграции канонов (фабрика + подготовка активной миграции W2)

**Процедура** (ADR-1013-3: правка канона = бамп + слепок; FACTORY_SET-эволюция — одна консолидированная, финальное значение зафиксировано):

## 1. FACTORY_SET

`553a281fe2fd` → **`fd4e88754749`** (changed = 6: core.personality, core.personality.compact, direct.base.tool_phase, direct.base.l2_writer, direct.base.l1_planner, factcheck.base.verbalizer). Запись бампа — в `services/prompt_registry.py` (SOUL-AMD.3.2); метки ревизий: `asap-core-full-v3`, `asap-core-compact-v3`, `direct-toolphase-w1`, `l2-writer-w1`, `l1-planner-w1`, `factcheck-verbalizer-w1`.

## 2. Лестницы PROMPT_MIGRATIONS (активные PG ведутся на новые каноны при рестарте)

| Ключ | Новая ступень (известные прежние байты → новый канон) |
|---|---|
| prompts.direct_chat_system_prompt | + `(PREV_CHAT_W1_SYSTEM_PROMPT → CHAT_SYSTEM_PROMPT)` — 11-я ступень (прод-байты 2.58.110, 0fe9680ba280) |
| prompts.direct_chat_verbalizer_system_prompt | + `(PREV_CHAT_VERBALIZER_W1 → DIRECT_VERBALIZER_SYSTEM_PROMPT)` — 3-я ступень (d0ef0d376fc3) |
| prompts.direct_l1_planner_system_prompt | + `(PREV_DIRECT_L1_PLANNER_L1D → DIRECT_L1_PLANNER_SYSTEM_PROMPT)` — 4-я ступень (ace6246bd360; W0: active на проде уже ace6246bd360 → уедет ступенью на рестарте) |
| prompts.factcheck_verbalizer_system_prompt | НОВАЯ лестница: `[(PREV_FACTCHECK_VERBALIZER_W1 → FACTCHECK_VERBALIZER_SYSTEM_PROMPT)]` |
| character.core (документ) | НЕ скаляр prompts.*: известные прежние заводские байты v1 (040581a3b4b0) и v2 (d98e72ec7926 / e0529832ba7c) гасит **гвард superseded-core** (`pr.core_selection`, теперь множество из двух прежних редакций на поле); active = заводская v3; **кастом владельца не подменяется никогда** |

Идемпотентность: значение == новому канону → no-op; кастом (не совпал ни с одной ступенью) → skip + WARNING. Оффлайн-пруфы: миграция всех 4 прод-ключей на новые каноны; кастом не тронут (`TestPromptMigrationsCatalog`, `test_prompt_migrations.py`).

## 3. ROLLBACK_MIGRATIONS (откат — на НЕПОСРЕДСТВЕННЫЙ прежний прод-канон; стек ступеней цел)

| Ключ | Откат |
|---|---|
| prompts.direct_chat_system_prompt | CHAT_SYSTEM_PROMPT → PREV_CHAT_W1_SYSTEM_PROMPT |
| prompts.direct_chat_verbalizer_system_prompt | DIRECT_VERBALIZER_SYSTEM_PROMPT → PREV_CHAT_VERBALIZER_W1 |
| prompts.direct_l1_planner_system_prompt | DIRECT_L1_PLANNER_SYSTEM_PROMPT → PREV_DIRECT_L1_PLANNER_L1D |
| prompts.factcheck_verbalizer_system_prompt | FACTCHECK_VERBALIZER_SYSTEM_PROMPT → PREV_FACTCHECK_VERBALIZER_W1 |

known-canon-граница подавления расширяется автоматически (factory_texts + все ступени): прежние прод-байты остаются опознаваемыми (`test_soul1_registry_legacy_removal` — подавление проверяется на PREV_*_W1-байтах).

## 4. W2-протокол для активных значений (то, что W1 офлайн сделать не может)

| Активное значение (W0) | Действие W2 |
|---|---|
| core full_text `f59ba0f42a48` (owner_edit rev 6, 2327c; SOUL-16 ЕСТЬ, мата НЕТ) | `pm.owner_preserve_core_full_patch(text)` → снимает ТОЛЬКО SOUL-16-ремарку/ссылки «см. SOUL-NN»; запись `write_speech_value` с провенансом owner_edit + history; **diff до/после — в отчёт**; v1/v2-байты (если где-то остались) ведёт superseded-гвард |
| core compact_text | пусто на проде → замены фабрики достаточно |
| verbalizer кастом `091115cadc28` (unprovenanced-withheld, подавлял фабрику) | перезапись на фабрику §3.1 через `write_speech_value` (провенанс!), прежние байты → history; diff честный (приватные куски маскировать) |
| tool_phase кастом `cf404931f84c` (unprovenanced-withheld → cleaned 7923178337b4) | та же схема: upsert на фабрику §3.6 + провенанс |
| narrator кастом `43160d5f9c2c` | вне W1: гасить на LEGFIX-канон 5086ba935081 (приедет релизом 2.58.111) |
| per-chat overrides / чат -1002661910336 (expression frequent/sharp/wit=high) | НЕ сбрасывать (W0 §5.7); снапшот до правок — бэкап-протокол §5.3 |
| verbilizer_mode_* (PG-кастомы 19.09) | снять/переаттестовать; при плане в payload не подтягиваются (W1-тест) |

Кеши: после записи — инвалидация по revision (`NOTIFY chat_params_updated` + hot-слой), сверка inspector == provider payload; рестарт не возвращает старые каноны (лестницы; reset-to-factory = НОВАЯ фабрика — тест §9.1).
