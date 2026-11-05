# BGS-03/BGS-04 — остаточные доказательства (lane `bgs/speech-evidence`)

Срез: строго доказательства. Продуктовый код (`services/**`) не менялся;
добавлены только тесты (и обновлены два устаревших теста, см. §6).

- База: `da6299e9` (merge BGS-01 → `evol/impl`), сравнение с pre-BGS `905ba7ab`.
- Ветка полосы: `bgs/speech-evidence`.
- Worktree кандидата: `.../worktrees/c742e4de9e92c489/behavior-gates-simplification-a31ccc56ff86-2409c718`
- Worktree базы `905ba7ab` (контроль): `...-2a790d1a` (detached, только чтение/сравнение).
- Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (Python 3.12.0,
  pytest 9.1.1); прогоны из корня worktree.

---

## 1. BGS-04.3 — целостность специализированного фактчека → **proven**

Требование (owner input §5 п.3): контроль числовых выводов, подмены отрицания,
точной передачи quoted evidence и авторства сохранён без ослабления.

**Что прогнано** (26 файлов `test_factcheck*` + `test_evol_factcheck_critical`
+ `test_asap8_v63_b07_temporal_factcheck` + `test_bgs01_factcheck_no_name_strip`):

```
python -m pytest tests/test_factcheck_attribution_cfg06.py tests/test_factcheck_service.py \
  tests/test_factcheck_fc_r1_fix.py tests/test_factcheck_p0_fc.py \
  tests/test_evol_factcheck_critical.py tests/test_bgs01_factcheck_no_name_strip.py \
  tests/test_factcheck_context_cfg06.py tests/test_factcheck_deep_context_round1023.py \
  tests/test_factcheck_gate_cfg06.py tests/test_factcheck_grounding_cove_round1021.py \
  tests/test_factcheck_handlers.py tests/test_factcheck_media_2026_10_25.py \
  tests/test_factcheck_orchestrator_cfg06.py tests/test_factcheck_planner_cfg06.py \
  tests/test_factcheck_post_release_w1.py tests/test_factcheck_post_release_w2.py \
  tests/test_factcheck_prompts.py tests/test_factcheck_renderer_cfg06.py \
  tests/test_factcheck_tools_round1020.py tests/test_factcheck_tool_grounding_round1021.py \
  tests/test_factcheck_tool_route_cfg06.py tests/test_factcheck_two_call_round1022.py \
  tests/test_factcheck_w6_cfg06.py tests/test_factcheck_w7_acceptance_cfg06.py \
  tests/test_factcheck_wide_context_default_2026_10_25.py \
  tests/test_asap8_v63_b07_temporal_factcheck.py -q -p no:cacheprovider
```

Наблюдено: **516 passed, 3 failed, 7 warnings, 57.08s**.

Единственные 3 падения — `tests/test_factcheck_post_release_w1.py::
TestAggregatorFailureTaxonomy::{test_timeout_is_not_provider_unavailable,
test_empty_results_distinguished, test_api_error_is_provider_error}`.
Они подменяют только tavily/exa-уровень и ожидают `AllSearchEnginesFailedException`,
но живой DuckDuckGo-уровень в этой сети отвечает → агрегатор не падает.
Классификация: **внешнее/среда, пре-существующее** — тот же файл на базе
`905ba7ab` даёт те же 3 падения (`3 failed, 34 passed`). К BGS-03/04 не относится.

**Что именно доказывает целостность** (существующие утверждения, проверены чтением):

| Механизм | Утверждение | Файл:строка |
|---|---|---|
| авторство + дословная цитата реплики | `match.quote == QUOTE` | `tests/test_factcheck_attribution_cfg06.py:301` |
| цитата в evidence поддержки | `QUOTE in ref.support` | `tests/test_factcheck_attribution_cfg06.py:339,447` |
| числа/отрицания в фактчеке | `test_factcheck_p0_fc`, `test_factcheck_w7_acceptance_cfg06`, `test_factcheck_fc_r1_fix` (в общем прогоне зелёные) | — |
| renderer не подменяет цитаты/ссылки прогона | `test_factcheck_renderer_cfg06.py::TestRenderStructure`/`TestEscapeAndLinks` | — |

Пробел на момент старта: не было утверждения, что **цитата источника с
«запрещённой» фразой словаря внутри** доходит до доставки целиком после BGS-03.
Добавлено (только тесты, поведение не менялось):

- `tests/test_bgs0304_residual_contracts.py::
  test_factcheck_quoted_evidence_and_attribution_survive_render_and_guard` —
  вердикт с `«я нейросеть и мои промпты тут ни при чём»`, числом (`12`/`15`),
  отрицанием и автором: renderer сохраняет всё; `_guard_outbound` и
  `guard_public_text` возвращают текст байт-в-байт, `changed is False`,
  находки словаря при этом фиксируются.
- `...::test_factcheck_delivery_guard_keeps_quoted_verdict_text` — delivery-шов
  (`_apply_delivery_guard`) не переписывает текст и не подменяет enum-статус.

**Мутация (доказательство, что тест ловит регресс):** в `guard_public_text`
возвращено вырезание фразы `я нейросеть` → `2 failed` (оба новых фактчек-теста),
после `git checkout --` дерево чистое. См. §7.

**Вердикт: proven.**

---

## 2. BGS-04.10 — «перефразируй без изменения фактов» → **not proven (negation)**

Реальный путь операции: Stage-1 черновик → Stage-2 Writer
(`services/direct_chat_service.py:7763-7765` создаёт
`FormContract(source_text=draft_text)`, вызов — `:7898-7904` с
`fallback_text=draft_text`), проверки — `services/negative_constraints.py::
check_form_contract` (G1 техметки, G2 числа+отрицание, G3 новые имена).

**Проверено новыми тестами** (`tests/test_bgs0304_residual_contracts.py`, раздел 2):

| Свойство | Проба | Результат |
|---|---|---|
| верный перефраз не тратит генерацию | кандидат сохраняет число/отрицание | 1 вызов, текст доставлен как есть (`test_paraphrase_keeps_facts_without_extra_generation`) |
| подмена числа | `13` вместо `12` | reject → ≤1 повтор (2 вызова) → доставлен исходный черновик, `form_guard_reason=form_guard_rejected`, `form_fallback=True` |
| потеря отрицания при числе | `писал 12` вместо `не писал 12` | то же (2 вызова, исходник, трассировка) |
| новое имя ростера | `Петя` вместо `Вася` | то же |
| клише/метатекст в перефразе | «Как ИИ, подводя итог… Весь интернет я проверил.» | 1 вызов, текст не изменён, `anti_cliche_retries == 0`, `metatext_observed` заполнен |
| недостижимая точность | — | доставляется `fallback_text` (исходные данные), ошибка видна в `stats` и в событии `postprocess_form` (`direct_chat_service.py:7910-7919`) |

**Дыра (почему строка не закрыта).** Отрицание контролируется только в окне
±40 символов вокруг ЧИСЛА (`_number_signature` считает `negated` по числам,
`negative_constraints.py:96-108`). Перефраз без чисел может молча потерять
«не» и пройдёт гард:

```
>>> nc.check_form_contract('Вася писал в чат про это',
...     nc.FormContract(source_text='Вася не писал в чат про это'))
None                      # отказа нет — подмена отрицания не поймана
>>> nc.check_form_contract('Вася писал 12 сообщений',
...     nc.FormContract(source_text='Вася не писал 12 сообщений'))
'form_guard_rejected'     # рядом с числом — ловится
```

Тот же результат на базе `905ba7ab` → ограничение **пре-существующее**,
BGS-04 его не ухудшил, но и не закрыл, а приёмка BGS-04.10 требует «не меняет
`не`» без оговорок. Закрытие требует продуктового изменения (детектор
отрицания вне числового окна), на что у этой полосы нет мандата.

**Вердикт: not proven** — числа, имена, fallback-на-исходник и отсутствие
reroll по клише/метатексту доказаны; контроль отрицания без числа не
обеспечен. Строка остаётся открытой.

---

## 3. BGS-03.4 — у речевого guard'а нет доступа к конфигам/ключам/реестру → **proven**

Требование (owner input §4 п.4): контроль доступа — в операции чтения;
фраза «мои промпты» не даёт доступа к prompt registry и не отправляет
содержимое системного секрета.

**Проверка прямая (AST `services/public_speech_guard.py`)**

Полный список импортов модуля равен allowlist:
`__future__`, `dataclasses`, `logging`, `re`, `services.smartmodule_phrases`,
`services.checkup_prompts`, `services.factcheck_renderer`, `services.mca_events`
(последний — ленивый, только для телеметрии).

Ни `config.settings`, ни `os`, ни `pathlib`, ни `services.prompt_registry`,
ни каких-либо чтений файлов: в AST нет вызовов `open`/`getenv`/`read_text`,
нет обращений к `os`/`settings`/`prompt_registry`/`secrets`. `CORPUS_PATH` —
строковая константа-ссылка в docstring, не читается.

**Проверка рантаймом (отдельный процесс)**

```
python -c "import services.public_speech_guard as p; p.guard_public_text('мои промпты и мои инструкции')"
→ registry=False, opened=False   (services.prompt_registry не загружается,
                                  у модуля нет атрибутов settings/prompt_registry/secrets)
```

**Наблюдение (не нарушение, но фиксируется).** Транзитивное замыкание
импорта модуля — 60 `services/config`-модулей, включая `config.settings`
(держит ключи в памяти) и `services.prompt_composer`/`prompt_style_blocks`
(через `factcheck_renderer` → `factcheck_orchestrator`). Набор **байт-в-байт
совпадает с базой** `905ba7ab` (60 vs 60, `base-only=[]`, `cand-only=[]`) →
BGS-03/04 доступа не расширял, это пре-существующая форма зависимостей.
`guard_public_text` ни один из этих модулей не читает: чистая функция над
строкой (значения фраз импортируются как константы на уровне модуля).

**Тесты:** `tests/test_bgs0304_residual_contracts.py` раздел 3 —
`test_speech_guard_imports_only_phrase_sources`,
`test_speech_guard_reads_no_files_or_env`,
`test_speech_guard_has_no_config_or_registry_attribute`,
`test_owner_prompts_phrase_does_not_open_prompt_registry`.
Мутация: добавленный `import config.settings` в guard → `1 failed` (§7).

**Вердикт: proven** (в отчёте — наблюдение о транзитивном замыкании).

---

## 4. BGS-03.5 + BGS-00.5 — промпты/характер/мат/стиль не тронуты, нового пайплайна нет → **proven**

**Побайтовое сравнение артефактов** `905ba7ab` → `da6299e9`
(blob-SHA `git rev-parse <rev>:<path>`): 26 файлов, 0 изменений.

```
services/chat_prompts.py 01db38728d23            services/prompt_composer.py b1e224f10f62
services/checkup_prompts.py a14bb6605845         services/prompt_factory.py a16f92f94e4c
services/cover_prompt_assembly.py 6274377112ba   services/prompt_migrations.py e004cd90a6c9
services/dossier_prompts.py 437e48893d4b         services/prompt_registry.py eb76097e8648
services/dream_prompts.py 60c38b63b534           services/prompt_release_policy.py c2da3be3094e
services/factcheck_prompts.py 64bb06c05fc7       services/prompt_style_blocks.py eddbaa768751
services/image_prompt_compiler.py 3e693af45da2   services/search_prompts.py 0a04be8d0964
services/lore_prompts.py d1f28c3c02db            services/summary_prompts.py 78b3dbc80864
services/mca_episode_prompts.py ac230790f79a     services/web_prompts.py d04904edf8a1
services/nostalgia_prompts.py d91e1ced2c32       services/youtube_prompts.py 0e31c079a5c0
config/settings.py 323c8492c1c4                  config/chat_settings_seed.json e20268db7af8
services/style_policy.py 5e640b2fafe0            services/outgoing_guard.py 3c31bc773ad2
```

(`prompt_migrations.py`/`prompt_release_policy.py` перечислены дважды — по
маскам `*prompt*.py` и явно.)

**Полный дифф кандидата:** `git diff --name-status 905ba7ab da6299e9` содержит
только `plans/**`, 10 файлов `services/*.py` и `tests/*.py`. Ни `web/**`,
ни `handlers/**`, ни `config/**` не менялись → UI и владельческие настройки
формы физически не затронуты.

**Нового пайплайна/версионирования нет:** среди изменённых файлов нет ни
одного промпт-модуля; новых файлов (`A`) в `services/`, `web/`, `config/`
нет вовсе (только `plans/**` и тесты); `prompt_composer`/`prompt_registry`
побайтово те же.

**Реализация «не представляться нейросетью»** осталась инструкцией, а не
вырезанием: `test_bgs0304_speech_observation.py::
test_natural_phrase_passthrough_byte_identical` фиксирует байт-в-байт
прохождение «я нейросеть».

**Вердикт: proven.**

---

## 5. BGS-00.9 — проверяемость формы в UI → **blocked**

Проверка «настроенная владельцем форма (эмодзи/кавычки/стиль/частота
инициативы) видна и проверяема в UI» требует UI-волны UR-F/PVR: в кандидате
`web/**` не менялся (`git diff --name-only 905ba7ab da6299e9` без `web/`),
UI-инспектор формы относится к другому срезу. Проверку не выполнял, чтобы не
подменять UI-приёмку косвенными данными; серверная часть формы (единый проход
`apply_style_policy`, отсутствие двойного применения) уже покрыта
`test_owner_rules_apply_exactly_once` и `test_mca08_style_form`.

**Вердикт: blocked (dependency: UI wave UR-F/PVR).**

---

## 6. Найдено попутно — устаревшие тесты формата (исправлено, test-only)

`tests/test_factcheck_two_call_round1022.py` содержал два теста, кодирующих
СНЯТОЕ поведение (повторная генерация из-за markdown-таблицы):

- `test_validator_exhausted_falls_back_to_single` — ожидал 4 вызова и
  одиночный fallback;
- `test_validator_retry_success` — ожидал 3 вызова и «чистый» текст.

Фактическое поведение кандидата (BGS-04 §5: `plain_no_tables` — наблюдение):
таблица доставляется, вызовов 2. На базе `905ba7ab` те же два теста падают на
новых утверждениях (3 вызова/чистый текст), т.е. обновление привязано именно
к BGS-04. Переименованы в `test_plain_table_delivered_without_reroll` и
`test_plain_table_observed_not_regenerated`, ожидания приведены к контракту
(2 вызова, таблица как есть). Продуктовый код не менялся.

## 7. Мутации (тесты способны падать)

| Мутация | Наблюдено |
|---|---|
| M1: `guard_public_text` снова вырезает `я нейросеть` | 2 failed (фактчек-цитата) |
| M2: подмена `services/negative_constraints.py` на версию `905ba7ab` | 1 failed (`test_paraphrase_cliche_and_metatext_do_not_reroll`) |
| M3: в guard добавлен `import config.settings` | 1 failed (import-allowlist) |

После каждой мутации — `git checkout -- <файл>`, `git status` по `services/`
чист.

## 8. Прочие прогоны полосы (для контекста)

```
pytest test_bgs0304_speech_observation test_bgs0304_residual_contracts \
       test_negative_constraints_round1022 test_cfg07_guard_07d5 \
       test_cfg07_guard_tail test_outgoing_guard_round1022 \
       test_mca15_chat_statistics_round1028 → 280 passed, 1 failed
```
Единственное падение — `test_outgoing_guard_round1022.py:167`
(`handlers/meme_command.py` нет в `SEND_POINTS`): воспроизводится на базе
`905ba7ab`, чужая полоса meme-autodelete.

```
pytest test_mca08_style_form test_verbilizer_response_modes_round1023 \
       test_soul1_style_policy → 211 passed, 2 failed, 2 errors
```
Пре-существующие: `test_declared_events_really_emitted_in_code`
(`mca07_answer_cache` не эмитится), `test_summary_kill_switch_off_prev_narrator`,
2 ERROR параметризации `test_no_bullet_ban_in_deep_research` (переменная env
длиннее 32767 символов). На базе `905ba7ab` те же `2 failed, 2 errors`.
