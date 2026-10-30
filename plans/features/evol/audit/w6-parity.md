# W6 — паритет композера: 4 падающих теста `test_soul1_composer_parity_off.py`

Lane: Builder EVOL/parity, worktree `evol/impl`, ветка `evol/impl` @ `ccf15840`
+ рабочее дерево (без коммитов). Изменён ровно один файл:
`tests/test_soul1_composer_parity_off.py`.

Кандидат: `ccf15840` + рабочее дерево.
sha256[:16] изменённого файла: `51ff3c0664941705`.
Без изменений (сверено с HEAD): `services/prompt_composer.py`
`15f5705cc91ede08`, `services/prompt_style_blocks.py` `ebc5be8c44c39b8e`.

## 1. RED (воспроизведение)

```
python -m pytest tests/test_soul1_composer_parity_off.py -q
4 failed, 9 passed
```

Падали:
`test_tool_phase_on_equals_legacy_tail_without_new_layers`,
`test_tool_phase_on_and_off_scrub_identically_on_longform`,
`test_l2_on_keeps_block_set_and_applies_designed_order`,
`test_l2_on_without_plan_keeps_mode_block`.

Все четыре — сравнение ON-сборки `DirectChatService._compose_speech_system`
с легаси-склейкой (`prompt_style_blocks.compose_verbalizer_system`).
Точная дельта по блокам (offline-проба на стенде самого теста):

| кейс | ON len | legacy len | дельта |
|---|---|---|---|
| tool_phase | 1305 | 522 | ровно `\n\n` + `<Speech_Base>…</Speech_Base>` (781 симв.) |
| l2 + plan | 1305 | 522 + lessons + speech | те же 781 симв. в конце |
| l2 без plan | 1114 | 331 | те же 781 симв. в конце |
| scrub longform | 1193 | 410 | те же 781 симв. после скраба |

Арифметика точная: 522+2+781=1305, 331+2+781=1114, 410+2+781=1193.
Ни одного потерянного, переставленного или продублированного блока нет:
`only in legacy: []`, счётчики `<Speech_Base>` = 1, `scrub` снимает ровно 1
фрагмент на ON и на OFF.

## 2. Причина (проверка чужого утверждения)

Отчёт lane'а social утверждал «базовый дефект в `18baa36b`:
`_compose_speech_system` расходится с `compose_verbalizer_system`
(лишний `<Speech_Base>`)». Проверка:

* `git diff --stat 18baa36b -- tests/test_soul1_composer_parity_off.py
  services/prompt_style_blocks.py` → **пусто** (тест и рендерер байт-в-байт
  те же, что в baseline).
* `git diff 18baa36b -- services/prompt_composer.py` → единственная дельта
  это **добавленная** функция `speech_style_hint()` (её вызывает только
  `services/factcheck_service.py`; `compose_prompt` её не вызывает).
* `git diff 18baa36b -- services/direct_chat_service.py` → хунки на
  строках 2285/4230/4757/4809/10414+; `_compose_speech_system`
  (5663–5795) не тронут.

Вывод по классификации задания: **не (a) EVOL**, а **(b) уже было в
`18baa36b`**, и при этом корень ещё старше: слой добавлен P0
SPEECH-SIMPLIFY — `109bb770` (25.10.2026, блок появился в базе) и
`0a88c991` (25.10.2026, блок вынесен в отдельный слой 7 `speech_base`,
сразу после `response_plan`, перед Expression; см.
`plans/features/asap-speech-arch/evidence/speech-simplify/impl.md` §2).
Тест последний раз правился `3f0da7c8` (24.10.2026, «13 passed»), то есть
**до** появления слоя. `git merge-base --is-ancestor 0a88c991 3f0da7c8`
= 1 (не предок), `3f0da7c8` — предок `0a88c991` = 0.

Итог: рантайм корректен, устарел тест. Четыре ассерта пинили байты
*до* SPEECH-SIMPLIFY и потому падали на актуальной сборке.

## 3. Что исправлено (тест, не рантайм)

`tests/test_soul1_composer_parity_off.py`:

* добавлен хелпер `_speech_base_layer()` — единственный спроектированный
  слой ON-контура сверх легаси-хвоста, с обоснованием в docstring
  (P0 SPEECH-SIMPLIFY §2.1-2.3/§5, коммиты `109bb770` → `0a88c991`, ссылка
  на evidence и на OFF-дамп, где `<Speech_Base>` нет);
* 4 ассерта сравнивают строго **«легаси-хвост + ровно этот один слой»**,
  байт-в-байт: `== legacy + "\n\n" + _speech_base_layer()`;
* усилено, а не ослаблено: добавлены `startswith(legacy)` (легаси-порядок
  не переставлен), `count(SPEECH_BASE_OPEN) == 1` (нет дубля), проверка
  `scrub_for_plan(_speech_base_layer())[1] == 0` (нормализация не трогает
  слой); прежние проверки состава/порядка/слоёв сохранены;
* docstring модуля и трёх тестов обновлены: паритет ON = легаси-хвост +
  один спроектированный слой, «и ничего больше».

Рантайм **не менялся**: `services/prompt_composer.py` и
`services/prompt_style_blocks.py` идентичны HEAD (sha выше), легаси-путь
OFF остаётся байт-в-байт с дампом
`tests/fixtures/soul1/direct-runtime-assembly-asap2.txt`.

## 4. Доказательство, что тесты всё ещё ловят регресс (мутация)

Временно отключён аппенд слоя в `prompt_composer.py`
(`if False and speech_base_text …`), прогон:

```
4 failed, 9 passed
```

Те же четыре теста падают → контракт по-прежнему защищён. Мутация снята,
`git status services/prompt_composer.py` — пусто (файл вернулся к HEAD
байт-в-байт).

## 5. PASS

```
tests/test_soul1_composer_parity_off.py                         13 passed
4 целевых теста + test_evol_factcheck_critical + test_evol_social_frame
+ test_prompt_migrations + test_unified_core_route_coverage      86 passed
soul1/prompt/expression-набор (11 файлов)                 149 passed, 1 failed
```

## 6. Что осталось красным (не мой scope, не связано с паритетом)

Два устаревших пина заводского отпечатка, оба — следствие **закоммиченной**
работы чужого lane'а `d036707a` (EVOL FACTCHECK-CRITICAL: новый заводской
блок `factcheck.critique.directive`, `FACTORY_SET 519663a57eb6`):

* `tests/test_p0_prompts_core.py:109` — пин `03776db327b4`, фактический
  отпечаток `519663a57eb6`;
* `tests/test_expression_isolation_followup.py:179` — тот же пин
  `03776db327b4`.

`pr.FACTORY_SET_SHA256_12 == pr.factory_set_fingerprint()` сходится
(сам реестр согласован), устарел только литерал в тестах. Файлы вне моего
write-scope (`services/factcheck_*` и его пины — зона lane'а фактчека),
поэтому **не правил**: это его однострочная правка пина, и делать её
молча за другой lane нельзя. Требуется решение оркестратора: либо lane
фактчека обновляет оба пина, либо правка делегируется явно.

## 7. Побочное наблюдение (не блокер этого слайса)

`<Speech_Base>` доходит до Direct-Writer'а только через композер (слой 7).
OFF-путь Direct (`compose_verbalizer_system`) блока не содержит, и в
эталонном дампе его нет; функциональные Writer'ы (фактчек/саммари/чек-ап/
поиск/youtube/web) получают его через `speech_owner_block`. То есть при
`UNIFIED_COMPOSER_ENABLED=False` (код-дефолт) блок P0 SPEECH-SIMPLIFY в
Direct-ответ не попадает. Это существующее состояние дизайна (ON-контур
аддитивен), не регресс данного слайса, но при включении флага поведение
Direct изменится на один блок — это надо помнить при выкате флага.
