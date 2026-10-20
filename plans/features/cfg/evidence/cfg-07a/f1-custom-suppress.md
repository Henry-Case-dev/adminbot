# FIX-CFG07A-F1 — корпусная чистка кастома 7 канонов на сборке payload

Дата: 21.10.2026. Лейн: FIX-CFG07A-F1 (leaf). Коммитов нет (запрещено лейном).

## Находка (deploy 2.58.101, `release/deploy.md` F1)

Прод-значения 7 ключей CFG07A в PG — кастом владельца: прежний канон
(PREV_*_CFG07A) + систематическая владельческая правка общего фразового
блока (len = PREV − 35; «В болтовне о»→«О», «я»→«й», «;»→«,», удалено
«если план требует полного разбора - …», «его»→«каждый пункт»). Защита
кастома по дизайну («suppress только known-canon») не пустила
анти-backstage чистку 07A-2 в effective-пейлоады: safety-bypass,
identity-предложение, tone-label, sneer/hostility/humiliation, метка
«"Архивная справка"» и «перегрелись серверы…» уходили в LLM-промпт.

RED-воспроизведение на точном prod-шве (`resolve_speech_value`, attested
provenance): все 7 кастомов проходили `changed=False` с маркерами
(до фикса).

## Решение (консервативное, data-safe)

ХРАНИМЫЙ текст владельца в PG не мутируется. Suppress-слой
(`services/prompt_registry.py`) расширен custom_clean-скоупом:

* `CFG07A_PAYLOAD_CLEAN_KEYS` — ровно 7 не-фактчек канонов CFG-07A-2
  (direct/summary/checkup/search/youtube ×2/webpage);
* `payload_custom_clean_scope(pg_key, source)` — persisted-слои
  (chat/global) этих 7 ключей; кодовый fallback (default) и ключи вне
  скоупа — никогда (фактчек W3-freeze не тронут);
* `suppress_legacy_speech(..., custom_clean=True)` — те же
  детерминированные правила применяются и к значению, не совпадающему
  байтами с известным каноном. Кастом-ветка: чистка на сборке payload,
  владелец видит/правит свой текст как раньше, в LLM уходит чистая версия.
* Правила 12/13 (новые, из корпуса 07A-1):
  * `direct.honest_concession_invented_causes` (SF-09): скобка
    «(перегрелись серверы, база покрылась пылью)» снимается; вместе с
    правилом 9 результат байт-равен активному канону («Признай косяк в
    саркастичной манере, но оставайся в рамках фактов.»);
  * `summary.archive_data_label` (SF-16/E3): «помечены как
    "Архивная справка"» → «содержат архивные факты» (байт-равно активному
    канону; метки в ДАННЫХ `canonical_context` не затрагиваются);
* известная ветка known-canon байт-неизменна (гейт и правила для known
  не тронуты; флаг на known-ветке — no-op, тест-регресс);
* лестницы/миграции (`prompt_migrations.py`) не тронуты — F1-чистка
  живёт только в payload-слое (`resolve_speech_value`, `effective_prompt`,
  `prompt_factory._inherit_view` — витрина наследования теперь честно
  считает sha чистого текста).

Про «35 FORBIDDEN-маркеров»: скан корпуса 07A-1 показал, что в БАЙТАХ
канонов нет ни одного FORBIDDEN-маркера как утечки — встречающиеся
паттерны (FA-09 `[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]`, FA-16 wrapper-теги, FA-18
`{max_symbols}`, MB-12 имена tools, MB-13 «языковая модель») — легитимные
инструкции АНТИ-БОТ/Writer, присутствующие и в чистых канонах (снятие их
сломало бы жанровые контракты и байт-паритет). Реальные legacy-сегменты
кастома — семейство SF-01..SF-13/SF-16, и гасятся они правилами 1-13.
Контрактный тест фиксирует это честно: `residual(чистый кастом) ⊆
residual(активный канон)` по всем FORBIDDEN+SOURCE_FIX паттернам корпуса.

## Файлы

* `services/prompt_registry.py` (sha256_12 `b28459d008a1`) — правила 12/13,
  `CFG07A_PAYLOAD_CLEAN_KEYS`, `payload_custom_clean_scope`,
  custom_clean в `suppress_legacy_speech`/`resolve_speech_value`/
  `effective_prompt`, docstring-инвариант 3, `__all__`;
* `services/prompt_factory.py` (`46cbcc0c0c8a`) — `_inherit_view` передаёт
  скоуп (UI-хэш наследования = чистый effective);
* `tests/test_cfg07a_f1_custom_suppress.py` (`c87b04784017`, НОВЫЙ,
  TEST-LIFECYCLE: CONTRACT owner=CFG-07A) — 51 кейс;
* `tests/test_soul1_registry_legacy_removal.py` (`a9a2e31a51aa`) — точечное
  обновление `test_direct_base_channel_resolved_through_registry`: старое
  утверждение «attested chat-override проходит байт-в-байт» кодировало
  ровно то поведение, которое снимает F1. Intent сохранён (override —
  действующий слой `source=chat`, владельческая правка цела, retention
  цел), добавлено: legacy-маркер гасится, текст == suppress(custom_clean).
  Байт-прозрачность attested-значений вне скоупа по-прежнему покрыта
  (`test_soul1_registry_completeness.py::test_effective_prompt_shows_attested_registry_value`,
  l2_writer — зелёный).

Канон-константы НЕ тронуты: `factory_set_fingerprint() == 037080375ac8`
== `FACTORY_SET_SHA256_12` (live-проверка).

## Прогоны (21.10.2026, py -3 -m pytest, локальный ворктри)

| Набор | Результат |
|---|---|
| `tests/test_cfg07a_f1_custom_suppress.py` | **51 passed** |
| suppress-семейство + контракт 07A + лестницы + route-coverage
  (`test_cfg07_backstage_contract`, `test_soul1_registry_legacy_removal`,
  `test_soul1_legacy_custom_preserved`, `test_soul1_registry_completeness`,
  `test_prompt_migrations`, `test_unified_core_route_coverage`,
  `test_cfg07a_f1_custom_suppress`) | **223 passed** |
| `test_unified_core_route_coverage.py` (route-coverage 18) | **18 passed** |
| Широкое семейство (44 файла, импортирующих
  prompt_registry/prompt_style_blocks/resolve_prompt/suppress): batch 1
  (16 файлов) | **555 passed** + 2 failed (пре-экзистинг, см. ниже) |
| batch 2 (24 файла: soul1_*, summary_*, web/youtube/verbilizer) | **560 passed** |
| Фингерпринт фабрики | `037080375ac8` == константе (MATCH) |

## Инцидентальные находки

* `unrelated/pre-existing`: 2 фейла
  `tests/test_outgoing_guard_round1022.py::TestTelegramSendWrappers`
  (`ImportError: cannot import name 'InputRichMessageMedia' from
  'aiogram.types'`, `services/telegram_send.py:181`) — версия aiogram в
  локальном окружении. Подтверждено git stash-прогоном: падает и без
  изменений лейна. К F1 отношения не имеет; в прод-кандидат не входит.
* `related-nonblocking, зафиксировано`: `suppress_legacy_speech(ACTIVE
  direct, source="global")` сегодня НЕ идемпотентен — правило 1 срезает
  identity-фразу активного канона Direct (существующая семантика W1
  «persisted known-canon чистится, кодовый fallback нет»; OFF-паритет
  цел). Изменено не было; если владелец захочет identity в persisted-
  каноне Direct — отдельное решение (вне скоупа F1).

## Остаточный риск / ограничения

* Фикстуры кастома — МОДЕЛЬ прод-диффа по описанию deploy.md F1 (точные
  байты PG не выгружались); механика чистки не зависит от точных байтов
  (правила — точные фразы legacy-сегментов).
* Постдеплой-речек на проде (фактические payload'ы 7 маршрутов после
  выката фикса) — за Reviewer/Orchestrator; строка CFG-07A.1 сознательно
  не тронута.
