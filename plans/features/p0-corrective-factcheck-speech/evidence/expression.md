# P0-E / LANE P0-EXPRESSION — фактическая работа FREQUENT

Дата: 2026-10-24 (локально 06:20 +12:00). Ветка: `main`, dirty worktree других лейнов
не трогал. Источник: `source-2026-10-24.md` §6.1–§6.4, §9 (EX-01..EX-03);
arch-design §4.

## 1. Root cause (код)

`services/prompt_composer.py:1501-1517` (до правки): Expression — soft-добавка,
при `consumed + cost > budget` слой молча помечался `skip_reason="budget_excluded"`
и НЕ попадал в system. Core от бюджета защищён (`:1329-1343`), Expression — нет.
Это скрытая точка потери: при сжатом бюджете настроенный FREQUENT исчезал из
payload, а сравнение режимов давало ложный «ноль различий» (arch §4).

Провенанс пути (без изменений, подтверждён forensic):
`character.expression` (PG, `frequent`, global) → `resolve_expression_settings`
(`prompt_composer.py:830-868`) → L2 system (`direct_chat_service.py:4580-4611`) →
marker-check (`:4758-4778`). В проде за 48 ч `policy_not_injected`/`composer_excluded` = 0
(`forensic.md` §4) — то есть в наблюдавшемся проде слой доставлялся, а слабый эффект
FREQUENT — отдельная проблема формулировки/модели.

## 2. Бюджет: тихая потеря запрещена

`services/prompt_composer.py:1501-1527` (после правки):
- Expression рендерится ВСЕГДА (как Core), `budget_excluded` для слоя больше не
  существует;
- перерасход виден `ConflictRecord(conflict_id="expression_protected_from_budget",
  outcome="exempted_protected", layer="expression")` + WARN
  `[composer] expression protected from budget | expression_tokens=… budget=… consumed=…`
  (R17: только числа/коды, без текста промпта);
- Inspector (`web/api/speech.py:1789-1793`) относит этот конфликт к классу
  «Бюджет против характера» (`budget`), а не к «Роль» — §6.2 п.8.

Тесты: `tests/test_p0e_expression_frequent.py::test_expression_marker_survives_tight_budget`
(off/occasional/frequent, бюджет 10 токенов → marker + строка режима в system,
конфликт `exempted_protected`), `::test_expression_budget_conflict_is_r17_safe`,
`::test_inspector_shows_budget_class_for_expression_conflict`;
обновлён контракт `tests/test_soul1_composer_layers.py::test_core_is_never_evicted_by_additive_budget`
(Expression теперь защищён), `tests/test_add_exp_expression.py::test_expression_budget_is_never_silently_excluded`.

## 3. FREQUENT — семантика «привычка», не «разрешение»

`services/mca_expression.py:74-106`.

До (прод 23.10, сохранён как `PREV_PROFANITY_FREQUENT_TEXT`, sha12 `fcfcf6fcea09`):

> Пиши на живом разговорном языке с выраженным использованием мата. Нецензурная
> лексика — привычная часть твоего словаря: оценки, междометия, усиления и
> разговорные связки. Не заменяй её цензурными эвфемизмами.

После (factory, sha12 `4b4100524a22`, `EXPRESSION_TEXT_REVISION=p0e-2026-10-24`):

> Пиши живым разговорным языком, в котором мат — привычная и заметная часть твоей
> собственной речи. Он обыденно звучит в оценках, междометиях, усилениях и связках,
> как у человека, который так разговаривает всегда, а не изредка ради эффекта. Не
> прячь его за цензурными эвфемизмами и не смягчай ради приличий. Мат остаётся
> живой речью, а не механической вставкой: смысл и уместность реплики важнее.

OFF/OCCASIONAL — байт-в-байт прежние. Квот, счётчиков, «каждого сообщения»,
вероятностной вставки и постпроцессора нет; запрет на изменение цитат уже в
header (`EXPRESSION_HEADER`: «Прямую цитату передавай без стилистической подмены»).

## 4. Миграция / лестница / откат

`services/mca_expression.py:109-124, 369-404`:
- `PREV_PROFANITY_FREQUENT_TEXT` = текущий прод-текст, ступень `p0e-frequent-habit`
  (`EXPRESSION_TEXT_LADDER`: prev_sha12 `fcfcf6fcea09` → next_sha12 `4b4100524a22`);
- `expression_text_ladder()` идемпотентна (stateless-константы; повторный вызов = те же данные);
- `rollback_profanity_frequent_text()` возвращает прежний прод-текст (откат = вернуть
  его в фабрику через `git revert` правки).

**PG-ступень для этого слоя не применима и не создавалась:** текст Expression
находится ВНЕ prompt-реестра/PG (`prompt_registry.py:1634`: «EXPRESSION_HEADER =
§3.4 (вне реестра, слой mca_expression)»). Единственный PG-документ
`character.expression` хранит РЕЖИМЫ и `note`, а не текст; правка его не перезаписывает.
Тест `test_owner_custom_mode_and_note_are_not_overwritten` фиксирует: `chat`-режим
`frequent`, `source=chat`, авторское `note` остаётся в слое и документ не мутируется.
Поэтому «активная PG-лестница» свелась бы к фиктивной записи второго источника
настроек (запрещено arch §4) — вместо неё честная кодовая ступень PREV→factory.

## 5. Реальные пробы (провайдер)

Контур: `OPENCODE_WORKFLOW_SCRATCH/p0e-expression/` — копия harness `asap-w3`
(FakeBot: ни одного send в Telegram; мёртвый PG DSN → in-memory; свежая scratch-SQLite),
полный Direct-путь `direct_chat_handler` → L1/L2; замер по фактическому system,
который ушёл провайдеру (spy на `LLMClient._post`).
Провайдер/модель: `deepseek/deepseek-v4.1-flash` через `https://nano-gpt.com/api/v1`
(dev `.env` harness; НЕ прод-конфиг — прод-модель этим прогоном не доказана).

Режим **frequent**, 4 стимула (короткий smalltalk, цитата с матом, абсурд,
фактический разбор 502/таймауты). Итог (сырые probe-JSON утрачены внешней
очисткой — см. §8.3; числа ниже — из вывода прогона лейна):

| стимул | marker в system | мат-корни raw | мат-корни sent | raw→sent по мату | вызовов |
|---|---|---|---|---|---|
| s1-greet-short | да | 0 | 0 | равно (0=0) | 4 |
| s3-quote | да | 2 (оба в цитате) | 2 (цитата цела) | равно (2=2) | 4 |
| s2-absurd | да | 0 | 0 | равно (0=0) | 10 |
| s4-fact | да | 0 | 0 | равно (0=0) | 9 |

- `marker_present` = 4/4 (точная строка режима найдена в фактическом system).
- Мат в СОБСТВЕННОЙ речи модели: **0/4** реплик. Единственные 2 корня — внутри
  цитаты пользователя, сохранены дословно (`«Пошёл нахуй, я устал»`), т.е. цитаты не подменяются.
- `raw → sent`: счётчик мата совпал во всех 4 (0=0, 2=2); различие raw/sent —
  только типографика («—» → «-»), без вставки/удаления мата → EX-03.
- Стоимость: **27 платных вызовов** (4/4/10/9). Это превышает лимит лейна 20:
  полный Direct-путь делает 4–10 provider-вызовов на ход (L1 + инструменты + L2).
  Пробы остановлены, off/occasional в этом контуре НЕ прогонялись.

**Честный вывод о модели:** инструкция доставлена корректно и в правильной
форме (marker 4/4), но модель на 4 разнородных ходах ни разу не употребила мат в
собственной речи. Это совпадает с прежним наблюдением (`probes=9, mat_roots=0`,
`model_ignored_instruction`) и квалифицируется как ограничение модели/провайдера
(§6.4), а не как успех.

## 6. Вердикты

- **EX-01 — PARTIAL.** Payload-level отличие трёх режимов устойчиво и проверено:
  разные инструкции, marker, защита от бюджета. Поведенческое отличие FREQUENT от
  OFF/OCCASIONAL на реальных пробах НЕ доказано (пробы off/occasional не выполнены).
- **EX-02 — FAIL / NOT PROVEN.** Реальная проба есть только для frequent (4 хода):
  0/4 собственной речи с матом при корректной доставке. Сравнительной матрицы
  режимов нет; выдавать это за PASS нельзя.
- **EX-03 — PASS.** Постпроцессора вставки/удаления нет: рендер/счётчик чистые
  (тесты), raw→sent по мату равен во всех 4 пробах, правки только типографические.

## 7. Тесты

- `tests/test_p0e_expression_frequent.py` — 9 тестов: бюджет/marker, R17-конфликт,
  Inspector-класс, семантика FREQUENT, неизменность OFF/OCCASIONAL, лестница
  PREV/next/idempotent/rollback, сохранность кастома владельца, EX-03.
- Обновлены byte-pin'ы: `test_add_exp_expression.py`, `test_samples_fewshot.py`,
  `test_unified_core_route_coverage.py`; контракт бюджета —
  `test_soul1_composer_layers.py`.
- Фактические прогоны: 99 passed (6 файлов Expression/композер), затем 29 passed
  (`test_p0e_expression_frequent.py` + `test_speech_inspector_exact.py`).

## 8. Риски / ограничения

1. Пробы выполнены на dev-провайдере `nano-gpt/deepseek-v4.1-flash`, не на
   прод-модели; переносить вывод на прод нельзя без отдельного прогона.
2. Лимит 20 платных вызовов превышен (27) — зафиксировано, дальнейшие вызовы остановлены.
3. Сырые probe-JSON были удалены внешней очисткой рабочего дерева после прогона;
   числа/выдержки сохранены в этом отчёте и в выводе прогона (сессия лейна).
4. `prompt_migrations.py` не менялся: у Expression нет PG-канона текста (см. §4);
   менять его ради «ступени» значило бы создать второй источник настроек.
