# CFG-07D.5 — bounded retry смысловой метаречи + FA-*/MB-10/11/12-детекторы

- **Лейн:** CFG-07D5, 21.10.2026. База: HEAD `ce77b2c4` (прод 2.58.103).
  Коммитов НЕТ по брифу — биндинг оркестратора.
- **Закрывает хвост** `07cg-reuse-audit.md` §3 и `07cg-tail.md` §6:
  «bounded retry для смысловой метаречи, FA-*/MB-10/11/12-детекторы — 07D.5».
- **W3-фриз цел:** `factcheck_prompts.py`/`prompt_migrations.py`/каноны — вне
  диффа. `current_task.md`, git, прод, чаты — не тронуты.
- **Ремонт review-07d5 (F1–F4, один цикл):** kill-switch-тест патчит
  КЛАСС флага, не инстанс (тень-инстанс ломала комбинированный прогон
  с nc1022); negation-lookbehind «не» перед глаголом в смысловом слое
  (честное ограничение «весь интернет я не проверил» ≠ retry-код);
  REGRESSION-тест bracket-среза FA-08 (честные скобки целы); доки/тест
  delivery-шва приведены к факту — инверсная формула на шве РЕЖЕТСЯ
  defense-in-depth. Числа ниже — после ремонта.

## 1. Дифф (4 файла кода + 1 новый тест)

| Файл | Что |
|---|---|
| `services/public_speech_guard.py` (+240) | машинные артефакты (`_MACHINE_FAMILIES` с id корпуса), смысловой слой (инверсии overclaim), `metatext_retry_reason`, `strip_guard_findings`, интеграция в `guard_public_text`/`_strip_matches` |
| `services/negative_constraints.py` (+86) | metatext-контракт `verbalize_validated(metatext_reason=…)`: ≤1 повтор в существующем бюджете, honest-fallback |
| `services/factcheck_service.py` (+25) | `_metatext_retry_reason()` — тот же рубильник pipeline v2 (hot → env); контракт на Stage-2 (`_check_claim_two_call`) и temporal-вербализаторе |
| `services/prompt_style_blocks.py` (+14) | `METATEXT_RETRY_SYSTEM_PROMPT` (код причины; честные ограничения сохранять) |
| `tests/test_cfg07_guard_07d5.py` (новый, 41) | CONTRACT owner=CFG-07D5 |

Другие изменённые файлы в `git status` (plans/archive/mca-17c, asap8-карты,
owner_questions, workflow_state, …) — чужие лейны, этот лейн их не трогал.

## 2. Механизм

### 2.1 Машинные артефакты — детерминированный срез (не retry)

Источник каждой семьи — запись `07a1-corpus.json` (source of record), finding =
id корпуса (R17: коды, не приватные тексты); границы токенов
`(?<![0-9A-Za-zА-Яа-яёЁ_])…(?![…])` (вкл. `_` — `host_not_actively`/
`myunchanged` не ловятся). Расширение = осознанная правка с записью корпуса
(07A.7, не растущий black-list).

| id корпуса | Паттерны (pattern + alt) | kind |
|---|---|---|
| FA-06 | `UNCHANGED` (word_ci) | service_echo |
| FA-07 | `nostalgia_hint:` | service_echo |
| FA-08 | `[СИСТЕМНОЕ УВЕДОМЛЕНИЕ` (+ тело до `]`) | bracket |
| FA-01 | `"reason":` / `{"reason"` (срез плоского JSON-объекта целиком) | json_echo |
| FA-02 | `"response_mode"` | json_echo |
| SF-16 | метка «Архивная справка» (bracket-блок / кавычки / label-colon; E3-эхо MB-02, запрет в digest уже живёт в `system2_handoff`) | label |
| MB-10 | `период проверки`, `(unknown)`, `precision`, `as_of`, `uncertainty` | tech_field |
| MB-11 | `tool_not_active`, `capability_not_ready`, `no_tool`, `low_confidence` | reason_code |
| MB-12 | `execute_web_search`, `query_chat_memory`, `dig_into_lore`, `compile_lore_story`, `get_bot_health`, `fetch_article` | tool_name |

Срез — только найденная формула (+висячая запятая/двоеточие за ней): факты,
числа, ссылки, имена не меняются; вырожденный остаток → `text=""` → шов
подставляет честный класс (enum-статус/🗿/пул — семантика 07cg-tail).

**Попутно устранён дефект среза:** `_bracket_block_re` экранировал голову
вместе с `[` и `[1:]` превращал `\[` в открывающий char-class — FA-08-strip
резал бы произвольные скобочные блоки. Исправлено (тело экранируется без
ведущей скобки), найдено пробой среза до тестов.

### 2.2 Смысловой слой — bounded retry (не тихий срез)

Закрытые сеты 07D.2 ловят дословный прямой порядок («проверил всё в
интернете»). Инверсия («весь интернет я проверил», «всю сеть я перерыл») —
не дословная формула: безопасного точечного среза нет, поэтому:

- `find_semantic_metatext` — объект тотального охвата (формы закрытого сета:
  весь интернет / вся|всю|всей сеть|паутина / всё в интернете) + конечные
  формы глагола проверки в ОДНОМ предложении, в любом порядке; причастия
  («проверенных») и чужие объекты («интернет-магазин») границами отсечены;
  предложения, уже покрытые закрытым сетом, НЕ задваиваются (находки
  существующих тестов `findings == (…) не изменились`);
- `metatext_retry_reason` — причина retry ТОЛЬКО для смысловых находок:
  дословные формулы/метаречь/машинные артефакты → `None` (детерминированный
  ремонт существует, бюджет не тратится);
- bounded retry в `verbalize_validated` (переиспользование существующего
  retry-механизма, прецеденты form MCA-08 / numeric MCA-15):
  `metatext_reason` callable → ≤1 повтор с `METATEXT_RETRY_SYSTEM_PROMPT`
  (подставляется КОД причины) внутри ТОГО ЖЕ бюджета (≤2 всего, ≤1 на
  metatext); неудача/ошибка ретрая → `metatext_fallback=True` +
  `strip_guard_findings` (закрытые формулы + машинные артефакты +
  инверсная strip-грамматика «объект + местоимения* + глагол») — деградация
  честная, без фиктивно уверенных заявлений; приоритет повтора metatext →
  form → numeric → cliché;
- delivery-шов (без retry-бюджета) честно репортит находку
  `semantic:total_verification_variant` в telemetry (`egress_guard`) И
  режет инверсную формулу defense-in-depth (`_INVERSE_STRIP_RE` входит в
  `_strip_matches` → `guard_public_text` меняет текст: «Тезис
  подтверждается. Весь интернет я проверил.» → «Тезис подтверждается.
  .»; остаток « .» — существующий класс уборки среза, вне скоупа волны).
  Первичная формулировка «инверсию не режет» была неверной — исправлена
  по review-07d5 F4 (правилась документация, не код: срез согласуется с
  докстрингом `_INVERSE_STRIP_RE` «и на delivery-шве»).

### 2.3 Wiring — только в контуре v2 (OFF-паритет)

`factcheck_service._metatext_retry_reason()` — тот же рубильник
(`flags.factcheck_pipeline_v2` hot → `FACTCHECK_PIPELINE_V2_ENABLED` env →
False), что диспетчеризует handler/оркестратор; OFF → контракт `None`,
поведение байт-в-байт прежнее (проверено тестом на обоих швах Stage-2/
temporal). Прочие потребители `verbalize_validated` (direct ×2,
summary ×1) контракт не передают — их контур не менялся (вне скоупа
FACTCHECK_PIPELINE_V2_ENABLED).

## 3. OFF-паритет и POSITIVE-контроли

- **OFF (default):** `_metatext_retry_reason() is None`; на обоих швах
  Writer'а контракт не передаётся; `verbalize_validated` default — stats
  без новых ключей, байт-паритет (тесты
  `test_default_none_byte_parity`, `test_temporal_verbalizer_off_no_contract`,
  `test_stage2_verbalizer_off_no_contract`, `test_gate_helper_off_and_on`).
  Guard-швы и раньше были достижимы только в v2 (pinned 07cg-tail).
- **POSITIVE (0 ложных):** 202 текста владельческих пулов
  smartmodule_phrases + renderer/checkup-каноны + POSITIVE-примеры корпуса
  (PC-01..PC-12 из файла) + честные контекстные слова («логи сервера
  чистые», «анализ показывает…», «проверка заняла минуту») — 0 машинных
  находок, 0 смысловых, guard байт-в-байт
  (`test_owner_canon_pools_clean`, `test_honest_canon_texts_clean`,
  `test_positives_from_corpus_file`). Слепая зона честных отказов не
  тронута: PC-01 «проверил — не нашёл подтверждений» проходит байт-в-байт
  и в retry-детекторе, и на delivery-шве.

## 4. Проверки (все зелёные, EXIT=0; лог `07d5-tests.txt`)

| Набор | Результат |
|---|---|
| `test_cfg07_guard_07d5.py` (новый CONTRACT) | **41 passed** — детекторы/границы 14 (вкл. F2-bracket REGRESSION), corpus-parity 2, смысловой слой 6 (вкл. F3-negation REGRESSION), POSITIVE 3, bounded retry 6, wiring v2 ON/OFF 6, delivery-шов 4 (F4: ассерт фактического среза) |
| Сводный фокус (новый + словарь + хвост + route-coverage + фактчек-семья cfg06) | **234 passed / 0 failed, EXIT 0** |
| F1-комбо `test_cfg07_guard_07d5 + test_negative_constraints_round1022` | **74 passed, EXIT 0** (до ремонта: 1 failed — тень-инстанс kill-switch) |
| `test_cfg07_egress_dictionary.py` | **67 passed** (без регресса) |
| `test_cfg07_guard_tail.py` | **29 passed** (без регресса, телеметрия B1 на месте) |
| `test_unified_core_route_coverage.py` | **18 passed** (шов speech_owner_block не тронут) |
| Валидаторная семья (anticliche 79, form 83, nc1022 33, mca15 91, tool_router 45) | **331 passed** |
| Потребители verbalize (add_exp 36; temporal-семья mca20/b07/d10) | **36 + 68 passed, EXIT 0** |

## 5. Маппинг на план/карту

| Строка | Что доставлено этой волной | Остаток слайса |
|---|---|---|
| CFG-07D.5 (L00380) | детекторы FA-06/07/08 + FA-01/02 + SF-16 + MB-10/11/12; bounded retry смысловой метаречи (v2-контур); машинные артефакты срезаются на delivery-шве до Telegram; честная деградация | полный acceptance строки (mock-Writer: `fact:123`, сырой `<b>`, битая ссылка) — W3 egress-whitelist/renderer (CFG-06, уже построено) + швы Direct/summary и live preprod — слайс CFG-07C целиком; статус PENDING честно (биндинг оркестратора) |
| CFG-07C.2 (остаток из 07cg-tail §4) | FA-*/MB-10/11/12-детекторы в factcheck v2 — закрыто | роль-tag-утечки — W3/renderer; швы Direct/summary — полный слайс |
| CFG-07C.3 (остаток из 07cg-tail §4) | bounded retry для смысловой метаречи — закрыто (v2-контур фактчека) | распространение на швы Direct/summary — полный слайс |

Статусы карты НЕ переключались (слайс CFG-07C шире лейна; live preprod) —
в строку CFG-07D.5 добавлена evidence-ссылка на этот файл, биндинг за
оркестратором.

## 6. Честные остатки (зафиксированы)

- Смысловой слой покрывает семью тотальной проверки (07D.2-источник);
  варианты других семей (например, инверсии «справка моя говорит») —
  расширение только с записью корпуса (07A.7).
- Co-occurrence-грамматика сознательно закрытая: «всю сеть фастфудов я
  перерыл» (легитимный бизнес-контекст) детектором ловится → bounded retry
  (fail-soft: один повтор, дальше честная деградация); corpus-POSTITIVE
  при этом 0 ложных. Инверсный strip срезает только формулу
  «объект*(местоимения)*глагол», экзотический разнос внутри предложения
  остатком не срезается — телеметрируется.
- Retry живёт на Stage-2/temporal-вербализаторе фактчека (v2); швы
  Direct/summary — полный слайс CFG-07C; `persona_short_reply` — только
  детерминированный guard (без retry-бюджета).
- Инверсный overclaim на OFF-контуре — прежнее поведение (OFF-паритет).
