# ASAP 3 Corrective — итоговый отчёт (§11)

Источник: `source-2026-10-23.md` §11. Дата сборки: 25.10.2026.
Артефакты: `arch-design.md` (RCA §1), `evidence/style-phase1.md`, `evidence/identity-phase.md`,
`evidence/limits-inventory.md`, `evidence/ui-phase.md`, `evidence/acceptance.md`, `migration.md`.
Кодовый кандидат фичи: `9ed68ee8` (прод 2.58.118, 23.10.2026 17:51 UTC; carry-over в 2.58.125
не менял каноны/схему — ΔDDL=0). Свежий прогон отчёта: `675308b5`, 62 passed
(style 16 + identity 22 + acceptance 8 + hidden 16).

## 1. Первопричина каждой из трёх проблем

| # | Проблема из §0 | Первопричина (фактический код) | Доказательство |
|---|---|---|---|
| P1 | Действующие инструкции Style Policy молча исключаются | `render_style_policy_hint` подставлял заводские 400/5 при `0` (нельзя выключить); `lines.pop()` резал с конца (soft-привычки последние); единственная строка >400 → пустой блок и `style_policy_absent`; второй сборщик в `prompt_composer` резал `[:400]` посередине; хранение soft — 12 без диагностики. **Где:** `services/prompt_style_blocks.py:466-469,494-515`; `services/prompt_composer.py:584-585,842-848`; `services/style_policy.py:66` | `arch-design.md` §1 P1; S1–S3, S10 тесты |
| P2 | Алиасы не имеют гарантированного приоритета | `build_alias_resolver` читал чатовый override через `get_chat_param`, который отдавал **только** чатовый словарь: глобальные алиасы исчезали целиком, `resolve()` уходил на Telegram nickname; обратная карта `_by_name` оставалась старой; у части модулей были свои каскады. **Где:** `services/summary_aliases.py:78-102`; `services/chat_params.py:354-377`; `handlers/summary.py:351`; `direct_chat_service.py:8146` | `identity-phase.md` §1.1–1.3 (RED-проба: `uid1002` → «Лёша» вместо global «Леха»); A1–A3, A10, A13 |
| P3 | Изменения алиасов не применялись даже после перезапусков | резолвер создавался один раз на старте (`bot.py:463/697`) из глобального ключа и раздавался по DI; `_cache` жил в экземпляре; сохранённое значение не попадало в существующий объект, а кэш параметров имел TTL. **Где:** `bot.py:463,697`; `services/summary_aliases.py:23,74`; `services/chat_params.py:489-494` | `identity-phase.md` §1.2, §2.2 (`LiveAliasView`, `bind_turn_aliases`, middleware); A4–A6 |

Проблема «длинное тире» (§3) — отдельный дефект, не входивший в три: в `RULE_KINDS` не было
`dash`, постпрохода не было, `forbidden_chars` удалял символ без замены (`arch-design.md` §1 P3).

## 2. Какие существующие механизмы исправлены (без новых подсистем)

| Механизм | Что исправлено | Где |
|---|---|---|
| `Style Policy` рендер | один владелец `render_style_policy_hint`; `0` = без лимита; исключение только целыми строками с конца и с записью в `excluded`; второй сборщик удалён | `prompt_style_blocks.py`, `prompt_composer.py` |
| Сохранение/валидация `style.policy` | `hint_limits` в документе, merge по полям, `save` не стирает поле; `soft` 64 и `rules` 64 — блокирующая диагностика, не молчаливая резка | `style_policy.py` (`validate_document`, `save_policy_document`) |
| Движок правил | новый kind `dash` первым в `RULE_ORDER`, замена `—`→`-` только в `plain`-регионах существующего `segment()`; `verify_outbound_payload` помечает остаточное `—` как `conflict` | `style_policy.py` (`apply_style_policy`, `verify_outbound_payload`) |
| `AliasResolver` | merge global+chat по `user_id`; каскад chat → global → nickname → username → verified memory → uid; `scope_report` | `summary_aliases.py` |
| Live-apply | `LiveAliasView` + `bind_turn_aliases(chat_id)` в `ContextVar`; middleware `dp.update`; Direct/Summary обновляют резолвер в начале хода; стартовый снапшот — только fallback | `summary_aliases.py`, `bot.py`, `direct_chat_service.py`, `summary_generator.py` |
| Кэш параметров | существующая инвалидация `set_chat_params` (без TTL-ожидания) | `chat_params.py` |
| Inspector | preview собирает **оба** слоя style doc (global+chat) и показывает фактические включённые строки, источник, лимит, причину | `web/api/speech.py`, `web/app.js` |
| Диагностика | `manage.py diag aliases --show-names` (read-only, merged-вид, `display_collisions`) | `manage.py` |
| UI | строка «Ограничения подсказки» в разделе «Стиль письма» (2 независимых лимита, OFF по умолчанию); отдельного глобального редактора лимитов нет | `web/app.js`, `evidence/ui-phase.md` |

## 3. Найденные лимиты и способ управления

Инвентаризация: 23 ограничения, каждое проверено по пути применения
(`evidence/limits-inventory.md` §1–2).

| Класс | Кол-во | Как управляется |
|---|---|---|
| `USER_VISIBLE` | 5 (№1, 2, 6, 8, 22) | настройка в своём разделе: «Стиль письма» (2 лимита подсказки, OFF), блок лимитов чата, каталог параметров |
| `TECHNICAL_VISIBLE` | 8 (№3, 4, 5, 7, 9, 10, 14, 15) | остаются защитными; действие видно: счётчик, fatal при save, `budget_excluded`, WARN с числами |
| `HIDDEN_LOSS` | 4 найдено → 4 исправлено (№11 текущий вопрос, №12 досье, №13 примеры регистра, №19 tail экстрактора) | молчаливая потеря заменена на WARN с числами/`kept=X/Y`; лимит остаётся техническим |
| `NOT_RELEVANT` | 6 (№16–18, 20, 21, 23) | внутренние механизмы, пользовательские данные не теряют; обоснование в строке |

Управление: пользовательские лимиты — только в разделе, к которому относятся (документ
`style.policy` + `chat_params`), без отдельного «редактора сотен параметров»; технические —
не отключены и не скрыты, а показываются как причина деградации.

## 4. Разрешение глобальных и чатовых алиасов

Порядок (единственный владелец — `summary_aliases`):
`chat alias → global alias → Telegram nickname → username без @ → проверенное имя из памяти → user_id`.

- Merge по каждому Telegram ID: global, затем chat перекрывает **только свой** `user_id`;
  отсутствие ключа = наследование; удаление чатового = возврат глобального; удаление
  глобального = следующий источник. Пустое значение не переименовывает и не подавляет global.
- Слои настроек: `default` (заводское) → `global` → `chat` (override чата). Effective
  проверяется по слоям: `hint_limits.sources`, `layers.chat`, Inspector показывает источник.
- `memory_name`/GraphRAG принимаются только при достоверной привязке к тому же `uid`
  (правило единственности `provenance`); история и цитаты не переписываются, старые
  `author_name` остаются исходными данными, отображение идёт через алиас.
- Диагностика: `python manage.py diag aliases --chat-id <CHAT> [--show-names]`.

## 5. Доказательство применения изменённого алиаса без рестарта

| Шаг | Механизм | Тест |
|---|---|---|
| Сохранение | `set_chat_params` пишет значение и сразу чистит кэш (`chat_params.py:489-494`) | `test_s4_saved_limit_applies_next_resolve_without_restart` |
| Следующий ход | `bind_turn_aliases(chat_id)` собирает резолвер заново из merged global+chat в `ContextVar`; `LiveAliasView` — тот же DI-объект | `test_a4_global_change_applies_next_turn`, `test_a5_chat_change_applies_next_turn_without_restart` |
| Изоляция чатов | per-chat резолвер в контексте задачи, чужие override не видны | `test_a12_parallel_chats_do_not_leak_overrides` |
| После рестарта | сохранённые значения читаются из БД | `test_a6_after_restart_saved_aliases_apply` |

Граница: это доказательство уровня тестов на реальном коде путей (`chat_params`,
`effective_style_policy`, `build_alias_resolver`), **не** наблюдение живого сообщения на проде.

## 6. Что проверено тестами и что — на production

| Область | Тесты | Production |
|---|---|---|
| S1–S10 Style Policy (полнота, видимость лимитов, save, dash, protected segments) | PASS (16) | исходящее сообщение без `—` не наблюдалось |
| A1–A16 алиасы (приоритет, merge, live-apply, история) | PASS (22; A16 — harness) | A16 live не наблюдался |
| §10.1–10.10 критерии приёмки | PASS по тестам; 10.10 — проверка диффа | 10.3/10.9 прод-конфигурация не проверялась |
| Скрытые лимиты (4 HIDDEN_LOSS) | PASS (16) | WARN-строки в проде не снимались |
| UI (строка лимитов, Inspector, 390/desktop) | `ui_asap3_hint_speech_e2e.py` PASS + скриншоты | живой TMA не проверялся |
| Регрессия затронутых сценариев | 188 passed (полоса приёмки) | — |

Итог: кодовые и тестовые требования закрыты; живые эффекты (первое реальное сообщение,
A16 live, TMA на прод-конфигурации) остаются `READY_FOR_LIVE` до фактического замера.

## 7. Оставшиеся ограничения и почему они сохранены

1. **Технические лимиты** (аддитивный бюджет композера, окна контекста, потолки API 200000,
   tail экстрактора 8000, поля примеров 2000/4000) — сохранены как защита стоимости,
   стабильности и БД; теперь видны (WARN/`budget_excluded`/422), а не скрыты
   (`limits-inventory.md` §2).
2. **Молчаливая потеря устранена не отключением лимита, а диагностикой**: №11/12/13/19
   по-прежнему ограничивают объём, но с числами и причиной.
3. **A16 live / 10.3 live / 10.9 прод-конфигурация** — требуют живого сообщения и TMA на
   проде; read-only план — `migration.md` §5.
4. **MIG-SCOPES**: эффективное значение `style.policy` на трёх уровнях (factory/global/chat)
   не снималось SELECT-ом из PG; нужен read-only замер DevOps.
5. **HTML `<code>`**: тело кода не входит в защищённые сегменты; в текущих речевых маршрутах
   ответ уходит `parse_mode=None`, поэтому S7 не нарушен; отдельная проверка нужна только при
   реальном HTML-коде в payload (`acceptance.md` §8).
6. **Полный `pytest` всего репозитория** в полосе приёмки не запускался — целевые файлы;
   широкий прогон остаётся за Reviewer/DevOps.


## 8. Привязка к релизу 2.58.129 @ 79ec3726 (25.10.2026, 08:56 UTC+12)

Кандидат = деплой **79ec3726c0919e6ffeaeb235be4f8d6326c4e12a** (2.58.129; healthz 200, NRestarts 0, 0 ERROR/Traceback, ΔDDL=0).
Доказательства: evidence/release-258129-binding.md, манифест evidence/raw/carrier-sha-24ca634b-vs-79ec3726.txt,
свежий прогон evidence/raw/pytest-asap3-62-79ec3726-carrier.txt.

Что сделано в этой полосе: из 13 строк класса AGENT_CHECK **закрыто 10**, 3 остались с точной командой проверки;
136 ранее подтверждённых строк перепривязаны к 79ec3726 (артефакт не изменился с момента верификации, байт-идентичность
ASAP3-путей 29/30 — единственное отличие 	ests/test_tool_coordinator_round1026.py, доказательством не используется).

| Решение | Строки | Основание |
|---|---|---|
| VERIFIED (10) | GOV-NO-NEW-LLM, GOV-KEEP-SAFETY-LIMITS, HID-USER-SETTINGS, HID-NO-BULK-OFF, HID-NO-GLOBAL-EDITOR, HID-NO-BUDGET-BREAK, GOV-ROLES-BUILDER, GOV-ROLES-REVIEWER, GOV-ROLES-DEVOPS, REPORT-FORMAT | статический аудит, инвентаризация лимитов, UI-скриншоты, ревью-вердикты, факт деплоя 2.58.129, свежий прогон 62 тестов |
| PENDING / AGENT_CHECK_NOW (2) | AUD-PROD-VERIFY, MIG-SCOPES | нужен read-only SELECT из PG: активные значения и три уровня style.policy (
elease-258129-binding.md §4.1–4.2) |
| READY_FOR_LIVE (3) | ACC-09, ACC-03, A16 | регрессия пройдена (62 PASS), живая конфигурация 2.58.129 / реальное исходящее сообщение не проверялись |

Остаток по карте: 48 уникальных обязательств (83 строки с учётом дублей инвентаря) остаются без действующего
artifact-пина — их evidence-документы правились после верификации, поэтому нужна повторная сверка утверждений,
а не механический перепин. Это работа PM/Reviewer, не владельца.

Gate: check --stage release --candidate 79ec3726… --deployed-commit 79ec3726… → **EXIT 1**, 171 ошибка:
166 сообщений по 83 строкам (48 уникальных обязательств) без валидной связки кандидат↔артефакт, 3 строки
READY_FOR_LIVE (ACC-09, ACC-03, A16) и 2 PENDING (AUD-PROD-VERIFY, MIG-SCOPES). EXIT 0 недостижим без пунктов
выше; ложных VERIFIED не добавлено.

## 9. Формат отчёта

Отчёт составлен на русском языке; снимок состояния — **25.10.2026, 08:56 UTC+12**; прогресс карты ASAP3
(требования со связкой кандидат + существующий артефакт) — отдельным прогрессбаром:

`	ext
[############--------] 62% (146/234)
`

Число отражает только строки с валидной привязкой к 79ec3726; в карте помечено VERIFIED 229/234, но 83 строки
ждут повторной сверки артефактов (см. §8).
