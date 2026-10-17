# SOUL-1 / W3-STYLE — Speech Style Policy, `one_word`/`micro`, антизалипание

- **Lane:** W3-STYLE (writer). **Кандидат:** рабочее дерево (без коммита, без deploy).
- **Слайс-строки:** `requirements-map.json` W3 (33) + `requirements-map-amendment.json`
  W3 (7). Покрытие по строкам — `evidence/w3/requirements-coverage.md`.
- **Флаги:** новые флаги не включались и не регистрировались. Нормализация формы
  и hint работают под существующей осью W2 `SPEECH_STYLE_POLICY_ENABLED`
  (env AND `flags.speech_style_policy_enabled`; код-дефолт оси — ON, как её и
  зарегистрировал W2). Композер `UNIFIED_COMPOSER_ENABLED` остаётся OFF →
  байт-паритет 13/13 зелёный. Без документа `style.policy` проход не меняет
  текст (кроме extent-проверки `one_word`, см. §2).

## 1. Что реализовано

| Что | Где |
|---|---|
| Типизированный реестр правил (kind/params/strictness/scope/enabled/owner/revision/created_at/updated_at/reason/conflict_strategy/exemptions/origin), 5 presets, мягкие привычки | `services/style_policy.py:70` (`RULE_KINDS`), `:174` (`PRESET_SPECS`), `:659` (`build_document`), `:620` (`validate_document`) |
| Документ `style.policy` на существующем PG-контуре (`bot_settings` + `chat_params.overrides`), без второго config service | `:893` (`effective_style_policy`), `:2088` (`save_policy_document`), `:2144` (`reset_chat_policy`) |
| Резолв `effective_style_policy` после scope/типа выхода и ДО Writer + короткий hint | `:797` (`effective_policy_sync`), `:928` (`resolve_style_policy_ref`), `services/prompt_composer.py:740` (единственная точка стыка — документированный hook слоя 10) |
| Короткий hint (только активные правила, ≤400 симв.) | `services/prompt_style_blocks.py:391`–`:419` (`HINT_*`, `render_style_policy_hint`) |
| Один `StylePolicyValidator`/formatter, объяснимый исход per-rule (`pass/repaired/exempted/conflict/failed/denied/not_applicable`) | `services/style_policy.py:1537`, порядок правил `:1175` |
| Семантические сегменты (защищённые спаны): code (fence/inline/вызов/путь), json, url, version_literal, ellipsis, markdown/Telegram-разметка, verbatim | `:1048` (`segment`), `:1108` (`protected_ranges`) |
| Единый проход: extent check → правила формы → один bounded ремонт → антизалипание | `:1922` (`apply_style_policy`) |
| Проверка ФАКТИЧЕСКИ доставляемого payload (без правок) | `:2049` (`verify_outbound_payload`) + `services/direct_chat_service.py:1556` (`_verify_style_payload`) |
| Единственная точка применения прохода: Direct (перед сериализацией/отправкой) и Initiative-writer | `services/direct_chat_service.py:3503` (Direct), `:3541` (проброс в доставку), `:7972` (инициатива), `:4513` (payload-проверка в `_send_direct_answer`) |
| Витрина реестра правил для UI/Inspector (W6): правила+источник, soft, presets, каталог kind, наследование, конфликты, hint | `services/style_policy.py:2197` (`style_policy_view`) + `services/prompt_registry.py:1369` (`STYLE_POLICY_BLOCK_ID`), `:1372` (`style_policy_view`), блок реестра `style.policy.hint` (`REGISTRY_VERSION="soul1-w3-1"`, `FACTORY_SET_SHA256_12="842a382c48f5"`) |
| Один необязательный `comic_strategy` L1 (совет, не приказ) | `services/direct_l1.py:66`, `:133`, `:280`, `:760`; `services/response_extent.py:98` |

### 1.1 Точка резолва эффективной политики

`effective_style_policy(chat_id, context=..., extent=...)` вызывается ПОСЛЕ
выбора scope и типа выхода: в композере — при сборке хода
(`resolve_style_policy_ref` → `versions.style_policy` + слой
`style_policy_hint`), в проходе формы — с конкретным `context`
(`regular`/`initiative`/`editorial`/`code_or_structured`) и extent плана.
Merge детерминированный: правило с тем же `id` в chat-документе заменяет
глобальное, новое `id` добавляется, `enabled=false` отключает; источник каждого
правила виден (`global|chat|preset`). Машинные стадии (`machine_json`,
`internal`) не получают правил вовсе (`skip_reason=machine_stage`).

### 1.2 `one_word` против `micro` (обязательный фикс)

- `direct_l1.L1Plan.to_response_plan()` (`:148`) переносит extent **значением**:
  схлопывание `one_word → micro` устранено; `one_word` добавлен в
  `response_extent.EXTENTS` (`:41`) со своим строгим блоком
  (`_EXTENT_BLOCKS["one_word"]`), текст `micro`-блока не изменён (байт-паритет
  OFF: дампы P2/P4 не двигаются — тест `test_one_word_and_micro_have_their_own_blocks`).
- Финальный валидатор: `check_extent` (`:650`) + `lexical_words` (`:570`):
  ровно одно лексическое слово (кириллица/латиница/составные `кто-то`/
  восклицания `Да!!!`), одна минимальная локальная правка (служебный/emoji-хвост,
  `_one_word_tail_trim:596`), при 2+ словах — честный `failed` без обрезки;
  защищённый контент → `conflict: one_word_vs_protected_content`.
- `micro` не имеет ограничения в одно слово: мягкий диапазон 2–8 слов,
  дальний выход (>16) — наблюдаемый `conflict` без обрезки.
- Явное ограничение длины пользователя старше комической экспансии:
  `resolve_extent_priority:633` (comic_strategy никогда не расширяет extent).

### 1.3 Защищённые спаны и честные исключения

Перед любой правкой текст сегментируется (`segment`): обычный текст, verbatim
(весь текст либо явно переданные фрагменты), URL, код (fence/inline/вызов/путь),
JSON, версии, многоточия, Markdown/Telegram-разметка. Байты защищённых
сегментов не изменяются никогда: нарушение показывается как
`exempted: protected_verbatim` либо `conflict`/`denied` по стратегии правила
(`exempt_protected`/`deny_incompatible`/`prefer_task`), с trace в исходе
(`detail`) и в `StyleOutcome.as_dict()` (R17-safe: коды/числа/хеши). Многословная
цитата без требования дословности НЕ срезается вслепую — это `conflict:
quotes_require_rephrase`, а не «успешный pass»; однозначно безопасный случай
(кавычки-ирония вокруг одного слова) правится с явной пометкой
`risk=irony_may_be_lost`.

### 1.4 Антизалипание (SOUL-09)

Существующие контуры (negative_constraints/anticliche_cache/freshness-guard)
не дублируются: добавлено наблюдаемое скользящее окно собственных фраз
(лексические 3-граммы, `REPEAT_WINDOW_MAX=12`, TTL 6 ч, изоляция по чату) и
capped/TTL/архивный динамический ban-list (50/24 ч/200) с отсечением
персональных имён, ссылок, упоминаний, длинных числовых рядов и
секретоподобных токенов. Классификация повторов: `critical` (целая реплика —
остаётся существующему duplicate-guard), `sticky` (целая фраза ≥4 слов),
`minor` (общий n-грамм, только наблюдение). Локальная замена снимает только
повторяющуюся финальную фразу вне защищённых сегментов и вне цитат; суть
ответа не переписывается; дорогая генерация не запускается. Без
владельческой политики (нет правил/привычек) повтор ТОЛЬКО наблюдается —
тихой потери текста нет.

### 1.5 Стоимость

`evidence/w3/cost-measurement.txt`: проход p50 ≈ 0.20 мс, p95 ≈ 0.38 мс
(n=50, детерминированно, 0 LLM-вызовов на нарушение); единственная добавка в
промпт — hint 321 симв. / 81 токен (при 3 hard-правилах). Смысловая
переформулировка возможна только по явному callback вызывающего и максимум
один раз на проход (по умолчанию не подключена ни в одном пути — 0
дополнительных LLM-вызовов на ответ).

## 2. Влияние на текущий прод-путь (важно для Reviewer)

Ось `SPEECH_STYLE_POLICY_ENABLED` зарегистрирована W2 с код-дефолтом **ON**
(env AND `flags.speech_style_policy_enabled`), поэтому проход формы на Direct
и Initiative выполняется уже сейчас. Без документа `style.policy` (в проде его
нет) проход:
1. делает extent-проверку `one_word` (это и есть обязательный фикс SOUL-05.2:
   «ровно одно лексическое слово»; текст меняется только у ответов с планом
   `one_word` и только на служебный/emoji-хвост, 2+ слова → честный `failed`
   без обрезки);
2. ведёт наблюдаемое окно повторов (bounded in-process, TTL 6 ч) и НЕ правит
   текст без владельческой политики;
3. не добавляет ни одного LLM-вызова, не меняет `message_id`, ссылки,
   разметку и структуру сообщений; hint в промпт не попадает (композер OFF).
С включённым документом `style.policy` дополнительно правятся правила формы —
это и есть целевое поведение слайса. Строка «styled=true при провале
hard-правила» невозможна: `StyleOutcome.styled` = False при
`conflict/failed/denied`, а payload-проверка подтверждает доставленный текст.

## 3. Тесты (новые файлы)

| Файл | Тестов | Что доказывает |
|---|---|---|
| `tests/test_soul1_style_policy.py` | 45 | модель правила/presets, hard vs soft, кавычки (Unicode-классы, апостроф, литералы), завершающая точка, спаны/exempted/conflict, стратегии, изоляция чатов, пакеты контекста, идемпотентность, 0 LLM, bounded ремонт, hint, витрина UI, R17, приоритеты, запрет подмены правил, `comic_strategy`, машинные данные |
| `tests/test_soul1_style_payload.py` | 8 | правило на реальном payload (Direct-контур с записывающим ботом), честный mismatch, extent на payload, safe-HTML/escape, OFF-пайплайн байт-в-байт, 12 разнородных входов, инициативный writer, 0 LLM |
| `tests/test_soul1_extent_one_word.py` | 25 | два extent, блоки, диапазоны, one_word-валидатор (+негативы/составные/восклицания), micro без cap, приоритет длины, старый cap, payload one_word, OFF |
| `tests/test_soul1_style_repetition.py` | 17 | окно/TTL/cap/изоляция, цитаты и короткие привычки, ban-list без имён/секретов, локальная замена, отсутствие лишней генерации, R17 |
| **Итого новых** | **96** | все зелёные |

Изменённые существующие тесты (причина — контракт изменился по требованию):
`tests/test_asap7_direct_l1.py` (D2/D3/form_override: `one_word` больше не
`micro`), `tests/test_soul1_composer_layers.py` (конфликт `one_word_not_supported`
снят после фикса W3 — так и было задокументировано в W2),
`tests/test_soul1_registry_legacy_removal.py` (версия реестра бампается слайсом).

## 4. Не выполнено в W3 (честно)

1. **Core-проводка публичных Factcheck/Summary** (`SOUL-AMD.2.4/2.5/2.9`,
   частично `2.7`) — это профили композера (`editorial_report`,
   `channel_text_only`), т.е. работа W2/следующего слайса; со стороны формы
   подготовлен пакет `editorial` и защита источников, но сам «голос Core» в
   этих публикациях этим diff не включается.
2. **Eligibility для финального Factcheck/редакционной Summary**
   (`SOUL-16.4.4`): проход к их текстам не подключён вовсе (правила не
   применяются — безопасно), явная eligibility-проводка остаётся за
   композером/W6-инспектором.
3. **UI «Стиль письма»** (`SOUL-16.1.5` в части редактора, `SOUL-16.2.1`
   «явно увидеть примеры», `SOUL-16.5.0-16.5.2`) — W6; движок отдаёт всё
   нужное через `style_policy_view()`.
4. **Ключ каталога `style.policy` + GroupSpec** — НЕ добавлялся: см.
   `evidence/w3/catalog-delta-decision.txt` (Δcatalog=0; ключ и редактор —
   W6, как уже зафиксировано в реестре для `character.core`).
5. **Live-часть** (`SOUL-16.5.3`, `SOUL-05.2/05.3/05.5/05.6/05.7`,
   `SOUL-AMD.1.6/1.7`, `SOUL-AMD.2.9`): реальная отправка в рабочий
   Telegram-чат не выполнялась (нет разрешения владельца, деплой запрещён
   заданием) → `LIVE_UNVERIFIED`; тестовый delivery-контур (записывающий бот
   на реальном коде доставки) — предел этой поставки.
6. `SOUL-05.7` (матрица «один характер, несколько манер») закрыт частично:
   one_word/micro/пара фраз/абзац/техника — тестами; SILENT/REACT и
   tool-result-путь проверяются W5/live.

## 5. Побочные находки

1. **`one_word_not_supported` в композере** оказался само-разрешающимся после
   добавления `one_word` в `EXTENTS`: конфликт снят без правки логики
   композера (обновлён только тест W2, который фиксировал промежуточное
   состояние «до фикса W3»).
2. **`_PATH_RE` съедал завершающую точку** предложения (`/example.org/other.`),
   из-за чего точка считалась защищённой и не снималась. Исправлено обрезкой
   хвостовой пунктуации у path-совпаданий (`style_policy.segment`) — найдено
   на 12-входовом контуре.
3. **`_QUOTE_CLASS_PAIRS` и символ `“`**: неоднозначный символ (закрывает
   `„“` и открывает `“”`) разрешается стеком открывающих — иначе `“…”`
   оставался «непарным» и правило кавычек ложно конфликтовало.
4. **Без владельческой политики повтор не правится** — сознательное решение
   (см. §1.4), иначе возможна тихая потеря законного повтора (например, когда
   пользователь прямо просит повторить ответ).

## 6. Артефакты

**Фингерпринт кандидата (sha256_12):** `style_policy.py=b25309213660`,
`response_extent.py=24628ba37455`, `direct_l1.py=94e0e8a9a532`,
`prompt_style_blocks.py=8c70462ad754`, `prompt_composer.py=be6518a0e523`,
`prompt_registry.py=4fe9ba7f95a2`, `direct_chat_service.py=3a3b4b3b0763`;
тесты `style_policy=5144143c1504`, `style_payload=04f91c636d06`,
`extent_one_word=4db65fb1ba3b`, `style_repetition=11dcb8f8873c`.

`plans/features/soul-1/evidence/w3/`: `style-payload-demo.txt`,
`style-contract-demo.txt`, `cost-measurement.txt`, `requirements-coverage.md`,
`parity-off.txt` (13/13), `focused-suites.txt` (96 новых W3 + [A] 146 вкл.
parity 13 + [B] 432 + [C] 200 + [D] 283 = 1157 passed, 0 failed), `full-suite.txt` (3 полных прогона:
прогон 2 — 13770 passed, 0 failed; прогоны 1 и 3 — по 1 падению с ОДНОЙ
первопричиной (утечка закрытой БД в глобальном `mca_random_source`,
`no active connection`), разными тестами, пути которых не исполняют код W3;
классификация `unrelated/pre-existing`), `catalog-delta-decision.txt`,
`_w3_probe.py`, `_w3_contract_demo.py` (воспроизводимые зонды, артефакты
перегенерированы на финальном кандидате).

## 7. Отклонения от буквы WRITE_SCOPE (для Reviewer)

1. **`services/prompt_composer.py`** — 1 функция (`resolve_style_policy_ref`,
   +14 строк): это документированный hook слоя 10 (design-composer-contract
   §3/§6: «W3 заменяет источник на `effective_style_policy`»), без него hint
   строился бы только из soft-привычек и жёсткие правила не доходили бы до
   Writer. Логика композера не изменена; при недоступности W3-модуля работает
   прежний fallback.
2. **Три существующих теста изменены** (не в WRITE_SCOPE, но контракт изменён
   требованием): `tests/test_asap7_direct_l1.py` (D2/D3/form_override ожидали
   схлопывание `one_word→micro` — это и был дефект SOUL-05.2),
   `tests/test_soul1_composer_layers.py` (фиксировал промежуточный конфликт
   `one_word_not_supported` «до фикса W3»),
   `tests/test_soul1_registry_legacy_removal.py` (жёсткая проверка префикса
   версии реестра `soul1-w1-` при бампе слайсом). Логика в них не ослаблена:
   новые ассерты строже (значение extent, отсутствие конфликта, поддержка
   обоих режимов).
3. **`services/param_catalog.py` и его артефакты не изменялись** — см.
   `evidence/w3/catalog-delta-decision.txt` (Δcatalog=0, обоснование и
   результат `--check`).

## Fix pass (review-w3 F1–F4)

Кандидат: рабочее дерево (без коммита). Отпечатки: `style_policy.py=8d26f9579472`,
`direct_chat_service.py=4d2a17cb362e`, тесты `style_policy=23600c14e3ff`,
`style_payload=c067d09aad5b`, `style_repetition=eca09420b542`,
`extent_one_word=4db65fb1ba3b` (не менялся). RED снят на реконструкции
до-фиксового кода (обратный патч в рабочем дереве, `_fix_capture_before.py`):
sha реконструкции совпал с отпечатками review-w3 байт-в-байт
(`b25309213660` / `3a3b4b3b0763`), затем оба файла восстановлены (sha сверен).

**F1 (blocker) — машинные данные защищены; сегменты сливаются в ОБЪЕДИНЕНИЕ.**
`_json_spans` распознаёт JSON в ЛЮБОМ месте сообщения (inline, середина фразы,
вложенные объекты, массивы, escape-кавычки, блок на строке), а не только в
начале строки; при неудачном `json.loads` запись с кавычками и `:`/`,` внутри
скобок всё равно защищается (`_json_like`), а незакрытая запись с явным
признаком данных (`{"k": "v`) — до конца текста (`_unterminated_json_like`).
`_merge_spans` при перекрытии хранит ОБЪЕДИНЕНИЕ диапазонов (kind — победитель
по `_SPAN_PRIORITY`): вложенный `code` больше не вытесняет широкий `json`.
Исход кавычек на защищённых машинных кавычках — честный
`exempted: protected_verbatim` (detail `span=json`), а не «pass»/«repaired»
(SOUL-16.2.3). Проверено (`evidence/w3/_fix_before-final.txt` →
`_fix_after-final.txt`, `_fix_before-f1f2.txt` → `_fix_after-f1f2.txt`):
до фикса 8 из 9 payload-примеров review испорчены (`{path: "/api/v1/x"}`,
`{note: ok}`, `{call: "print(x)"}`, вложенный объект, массив с URL,
escape-кавычки, inline `{"k": "v"}`, `{"note": "ok}`), после фикса машинный
фрагмент БАЙТ-в-БАЙТ (`sha_in == sha_out` по фрагменту в 9/9 случаев); меняется
только незащищённая завершающая точка — она и есть единственная незащищённая
часть смешанного payload (`Данные: {"note": "ok"} — вот.` → `… — вот`).
Затрагивать `one_word`/`micro`, работающие спаны (URL/версия/inline-код/
многословная цитата) и схему реестра не потребовалось.

**F2 (blocker) — снимается только фраза, в которой ЕСТЬ повтор.**
`_local_repetition_repair` сверяет n-граммы финальной фразы с ФАКТИЧЕСКИ
найденными повторами (`phrase_sha12` из `findings`) вместо тавтологического
`gram in tail_norm`; фраза без повтора не удаляется никогда. Проверено:
`Ну да, это классика жанра. И это важный нюанс.` → **не меняется** (до фикса
→ `Ну да, это классика жанра.`), повтор в середине — не меняется, повтор
ИМЕННО в хвосте (`Разбор простой. Ну да, это классика жанра.` → `Разбор
простой.`) снимается как раньше; цитаты/короткие привычки/защищённые спаны
не трогаются (повтор в JSON → текст без изменений + `exempted`).

**F3 (related) — проверяется payload ПОСЛЕ egress-guard.** Новый порядок:
проход формы → сериализация/escape ветки доставки → egress-guard
`sanitize_outgoing` → проверка БЕЗ правок именно доставляемых байтов
(`_delivered_payload`, `direct_chat_service.py:1556`) → отправка. До фикса
`Готово. fact:123` доезжало как `Готово.`, а проверка видела до-guard-строку и
рапортовала `payload_status=ok`; после фикса — `mismatch` (событие
`style_policy stage=direct_plain`, конфликт `trailing_period.hard.strip`).
Guard выключен → строка не меняется (паритет).

**F4 (related) — инициатива идёт через ТОТ ЖЕ проход в ЕДИНОЙ точке
отправки.** Решение: маршрутизировать (не исключать). Хук перенесён из
`generate_initiative_reply` в `handle_initiative` (`_style_initiative_text`,
`direct_chat_service.py:8228`, вызов перед `plan_logical_send`, контекст
`initiative`, `plan` из L1-решения когда оно есть): проходят его И
writer-текст, И `prepared_text` ностальгии; на один текст — ровно один проход
(SOUL-16.4.2), переоценка §18D, перегенерировавшая текст, получает новый
проход. Проверено: `Он сказал «база это сила». 😀` из nostalgia-пути доставляется
как `Он сказал «база это сила»` (до фикса — как есть, мимо прохода); счётчик
проходов на отправку = 1.

**Новые/обновлённые тесты (все зелёные):** `test_soul1_style_policy.py` 60
(+15: JSON в любом месте, вложенность/массив/URL/escape/строка-блок, «только
точка не защищена», несегментируемые машинные данные → exempted, объединение
перекрытий), `test_soul1_style_repetition.py` 23 (+6: повтор в первом
предложении/в середине/в хвосте/нет повтора/защищённый повтор),
`test_soul1_style_payload.py` 12 (+4 и 1 переписан: payload после guard,
guard-no-op, ностальгия через проход, ровно один проход на текст,
writer отдаёт сырой текст). Итого W3-файлы 120 passed (было 96), периметр
[A]+[B]+[C]+[D] = 146+432+200+283 = **1061 passed, 0 failed** (parity 13/13),
инициативные/ностальгические сюиты 68+79 passed, реестр `--check` CHECK OK
(572 == REGISTRY). Стоимость: p50=0.170 ms / p95=0.261 ms (n=600; база W3
0.207/0.294), LLM-вызовов на проход и отправку 0; bounded-стресс (800 пар
скобок) 5.9 ms. Полные артефакты — `evidence/w3/_fix_*`.

**Остаточные ограничения (честно, не блокеры).** 1) Распознавание машинных
данных ограничено ресурсами: ≤256 фрагментов на сообщение и ≤20000 символов на
фрагмент — за этими пределами защита деградирует к прежнему поведению
(bounded, как и исходный лимит 20000). 2) Для чанкованного ответа (>4096 симв.)
чанки формируются из проверенного текста и санитайзятся тем же guard'ом
по-чанково; проверка применяет guard к целому тексту — расхождение возможно
только если шаблон guard'а разрезан границей чанка (свойство существующего
delivery-пути, вне правки F3). 3) SQL-подобный фрагмент в обычной речи
(`SELECT "name" FROM …`) по-прежнему не считается машинными данными: правило
кавычек снимает там кавычки (машинные стадии `machine_json`/`internal` правила
не получают вовсе — VERIFIED review-w3 §4). Детектор SQL-в-речи в фикс-листе
review не значился и не добавлялся. 4) При объединении перекрытий kind берётся
у победителя по `_SPAN_PRIORITY`: регион `json` с вложенным `code` получает
kind `code`. Дефолтные исключения включают и `code`, и `json` (целевой случай
защищён); правило с КАСТОМНЫМ `content_type_exemptions` (только `json`) в таком
регионе защиту не получит — как и до фикса, где этот регион был ещё шире
открыт (узкий `code` вытеснял весь `json`).
