# W5 — EVOL social context: SocialTurnFrame (доп. директива §§1–3)

Lane: Builder EVOL/social, worktree `evol/impl`, ветка `evol/impl` @ `18baa36b`
+ рабочее дерево (без коммитов). Requirement source: `plans/current_task.md`
§§1–3 (EVOL — дополнительная корректирующая директива, строки 911–1035).

Кандидат: ветка `evol/impl` @ `18baa36b` + рабочее дерево. Fingerprint кода
дельты (`direct_l1.py` + `direct_chat_service.py` + `social_turn_frame.py` +
`test_evol_social_frame.py`, sha256[:16]): `8aee1f8dbab3e2df`.

## 1. Что сделано (файлы)

| Файл | Δ | Смысл |
|---|---|---|
| `services/social_turn_frame.py` | **новый**, 0 LLM | `SocialTurnFrame` (frozen) + `build_social_turn_frame` + рендеры строки L1 и подсказки Writer'у + kill-switch `SOCIAL_TURN_FRAME_ENABLED` |
| `services/direct_l1.py` | +25/−11 | `build_l1_context(social_frame=…)` — кадр в защищённом блоке `УЧАСТНИКИ`; `build_l2_plan_block(social_hint=…)` — строка кадра в существующем plan-блоке Writer'а |
| `services/direct_chat_service.py` | +99/−11 | модульный адаптер `_social_frame_for_turn` (fail-open), вызов в существующем `_plan_direct_l1`, передача подсказки в существующий `build_l2_plan_block`; инициатива: `rationale` доезжает до L1-решения и Writer'а |
| `tests/test_evol_social_frame.py` | **новый** | 15 offline-тестов (10 сценариев §3 + структурные) |

Не тронуто (нулевой diff): `handlers/**`, `web/**`, `services/factcheck_*`,
`prompt_composer.py`, `prompt_style_blocks.py`, схема БД, стекло,
`services/direct_context_composer.py` (изменения там не потребовались),
`services/user_relations.py` (данные только читаются), `services/quote_resolver.py`,
`services/message_identity.py`, `services/canonical_context.py`,
`services/initiative_observer.py` (там уже есть addressee/rationale —
адаптер подключён только к контексту Writer'а).

Никаких новых таблиц/DDL, новых агентов (`SocialObserver/Writer/Rater`
отсутствуют), второго L1 JSON, фоновых задач и новых полей `L1Plan`.
Одна необязательная подсказка в существующем plan-блоке — данные, не инструкция.

## 2. Данные до / после

### Direct L1 (существующий вызов, `_plan_direct_l1`)

До: блок `УЧАСТНИКИ` = `Говорящий: {name}` / `Адресат: {bundle.addressee}`;
reply/цитата только текстом в `ОТВЕТ НА`; id ветки — только внутри строк окна.

После (только при наличии адресации): третья строка того же защищённого блока
`УЧАСТНИКИ`:

```
кадр хода: адресат [user:42]; reply на [msg:555]; автор цитаты [user:50];
цитата: «фрагмент»; ветка: [msg:501], [msg:502]
```

Обычная реплика без reply/цитаты → строка не добавляется (байт-паритет).

### Direct Writer (существующий `_l2_write_answer`)

До: `<Response_Plan>` = действие/акт/тон/приоритеты; адресат — только через
`<Target_User>` (кто спросил) и `include_delivery` (в Direct выключен).

После: в тот же `<Response_Plan>` добавляется одна строка `кадр хода: …`
(адресат/reply/цитата/ветка + `адресация неоднозначна` при ambiguity).
Действие/тон по-прежнему выбирает L1 — кадр их не дублирует.

### Инициатива

До: `rationale` терялся — L1-решение видело `goal/kind/origin`, Writer —
`goal/kind/origin`.
После: `rationale` (≤200 симв., существующий канон) идёт в текст L1-задачи
(«Причина повода: …») и в `<Initiative_Context>` Writer'а; адресат повода и
реальные ID окна — строкой кадра в plan-блоке инициативного Writer'а.
Пустые значения → прежние байты.

### Frame (контракт §2.1)

`chat_id`, `trigger_message_id`, `speaker_user_id`, `addressed_user_id`,
`addressed_message_id`, `quote_author_user_id` (технически необходим: §2.1 п.2
и сценарий 3 требуют НЕ смешивать три роли), `quote_span` (только выделенный
фрагмент), `context_refs` (реальные Telegram ID ветки/окна), `relation_ref`
(allowlist стажа/активности/ручных пометок, **без** `activity_score`),
`attribution_status` (`resolved|ambiguous|unknown`).

Приоритет: native reply → канонический reply-адресат → автор цитаты →
`opportunity.addressee_user_id` (инициатива); иначе `None` + честный статус.
Имена/алиасы не используются как ключ идентичности; адресат не выбирается
«самым частым собеседником».

## 3. Подтверждённый маршрут до Writer (не мёртвый объект)

```
_plan_direct_l1  ── _social_frame_for_turn()  → SocialTurnFrame (0 LLM)
      ├── build_l1_context(social_frame=render_context_lines(frame))
      │        → [УЧАСТНИКИ] (protected в _cap_context)
      │        → messages[1]["content"] → llm.generate(step="l1_planner")
      └── meta["social_hint"] = render_writer_hint(frame)
                 ↓ (тот же turn)
      build_l2_plan_block(..., social_hint=…)  → <Response_Plan>…</Response_Plan>
                 ↓
      _l2_write_answer(plan_block=…) → parts → user_content
                 → messages[1]["content"] → llm.generate(step="l2_writer")
                 → composer manifest.user_parts (строка 5917) = то, что видит
                   Effective Prompt Inspector
```

Доказательство — на фактических payload'ах: `test_08` проверяет
`кадр хода: адресат [user:42]; reply на [msg:555]` одновременно в
`last_messages("l1_planner")` и `last_messages("l2_writer")`, а также
`тон: playful` / `смысловой акт ответа: answer` в payload Writer'а.
`test_07` показывает, что кадр доезжает до L1, но `silent` всё равно
отменяет Writer и публикацию.

Отдельного «бюджета на социальность» нет: в L1 кадр — часть защищённого блока
`УЧАСТНИКИ`, в Writer'е — часть обычного plan-блока (та же судьба, что у
строк «тон»/«смысловой акт»); при переполнении окна fallback-модели plan-блок
перепаковывается общим адаптером (`build_l2_fallback_adapter`), а не отдельным
правилом.

### Фактический payload (offline-проба, синтетика)

```
[УЧАСТНИКИ]
Говорящий: Вася
Адресат: участник Аня [user:42]
кадр хода: адресат [user:42]; reply на [msg:555]

<Response_Plan>
действие: reply
смысловой акт ответа: answer
тон: playful
кадр хода: адресат [user:42]; reply на [msg:555]
…
</Response_Plan>
```

Пустая подсказка → `PARITY_L1: True`, `PARITY_L2: True` (байт-паритет прежней
сборки).

## 4. Ноль дополнительных LLM-вызовов

* `services/social_turn_frame.py` не импортирует LLM/провайдеров и не делает
  сетевых вызовов — только чтение уже загруженных объектов.
* В тестах 8/9 набор шагов строго `["l1_planner", "l2_writer"]`.
* Единственный дополнительный ввод-вывод — необязательное чтение **одной**
  карточки RelationsService (`get_user_relation`, RAM-кэш 60 c) и только когда
  адресат ≠ запросивший (карточка запросившего уже подана `<user_relations>`).
  В группах при выключенном `flags.relations_tone_enabled` чтения нет вообще.

## 5. Промпты / версии

Новых фабричных LLM-инструкций нет: `declare_prompt`/seal не требуются.
`build_l2_plan_block` — код-путь (см. комментарий в `prompt_registry.py:2443`:
изменения plan-блока фиксируются отдельно от «фабричных текстов»), новых
system-промптов и новых полей схемы L1 нет. Кадр — данные хода, не директива.

## 6. Тесты

Перепроверка 31.10.2026 (после сообщения о потере файлов; код оказался цел —
см. §9): те же файлы, тот же комбинированный sha256[:16] `8aee1f8dbab3e2df`,
тесты прогнаны заново.

```
python -m pytest tests/test_evol_social_frame.py -q                    → 15 passed
  tests/test_asap7_direct_l1.py tests/test_direct_l1_l1d_contract.py
  tests/test_direct_l1_corrective_r1.py tests/test_evol015_quote_pipeline.py
  tests/test_quotes_modes.py                                           → 138 passed
  tests/test_direct_context_composer_asap3.py tests/test_soul1_composer_layers.py
  tests/test_soul1_composer_parity_off.py tests/test_soul1_core_composer_integration.py
  tests/test_direct_chat_relations_inject.py tests/test_quota_removal_composer.py
                                                                       → 87 passed, 4 failed*
  tests/test_asap8_f6_initiative.py tests/test_asap8_v63_b01_initiative_observer.py
  tests/test_p0_initfix_initiative_observer.py tests/test_initiative_delivery_telemetry.py
  tests/test_speech_p0_l1_canonical.py                                 → 91 passed
  tests/test_direct_chat.py tests/test_direct_chat_handlers.py
  tests/test_direct_chat_prompts.py tests/test_soul1_w5_initiative_vitality.py
  tests/test_direct_chat_lore_inject.py                                → 312 passed
  tests/test_evol016_prompt_activation.py                              → 21 passed
```

Сценарии §3 (все PASS, offline, моковый L1/Writer, без живых отправок):

| # | Сценарий | Тест |
|---|---|---|
| 1 | native reply → правильные `addressed_message_id`/`addressed_user_id`, не случайный участник окна | `test_01_native_reply_targets` |
| 2 | partial quote → только выделенный фрагмент (+ фрагмент не может закрыть `</Response_Plan>`) | `test_02…`, `test_02b…` |
| 3 | третий участник цитируется → говорящий/адресат/автор цитаты раздельно | `test_03_third_party_quote_keeps_three_people` |
| 4 | коллизия имён → ключ только Telegram ID | `test_04_alias_collision_uses_telegram_ids` |
| 5 | две переплетённые ветки → reply-связи, не соседство по времени | `test_05_interleaved_branches_use_reply_links` |
| 6 | неизвестный/неоднозначный адресат → нет выдуманной адресации; `relation_ref` без рейтинга | `test_06…`, `test_06b…` |
| 7 | L1 `silent` → Writer/публикация не вызываются (кадр при этом доехал до L1) | `test_07_silent_skips_writer_and_publication` |
| 8 | спор/дружеская реакция → существующий Writer получает `tone`/`response_act`/адресата, ровно L1+Writer | `test_08_tone_act_addressee_reach_existing_writer` |
| 9 | два чата + флаг OFF → нет кросс-чата, старый путь без блока, без лишних LLM | `test_09a…`, `test_09b_flag_off_gives_old_path_without_social_block` |
| 10 | инициатива: addressee/rationale → Decision/Writer; отказ адаптера fail-open; recheck/доставка не обойдены | `test_10…`, `test_10b…`, `test_10c…` |

`*` 4 падения `test_soul1_composer_parity_off.py` — **baseline дефект самого
HEAD**, не от этой дельты и не от чужих незакоммиченных правок. Доказательство
(31.10.2026): снимок `git archive HEAD` распакован в
`WorkspaceData/runs/…/evol-social-w5-*/temp-20ce680cf5/head` (там нет ни
`social_turn_frame.py`, ни правок `direct_l1.py`/`direct_chat_service.py`) и
`pytest tests/test_soul1_composer_parity_off.py` даёт те же 4 падения / 9
passed. Причина — расхождение `_compose_speech_system` с
`prompt_style_blocks.compose_verbalizer_system` (лишний `<Speech_Base>`),
существующее в коммите `18baa36b`.

## 7. Остаточный риск / NOT_OBSERVED

* `NOT_OBSERVED`: живые Telegram-ситуации (реальные reply/цитаты в боевых
  чатах) — по директиве §3 не блокируют закрытие; offline-структура доказана.
* Поведенческий риск «LLM решит иначе» остаётся у существующего L1/Decision —
  адаптер только поставляет факты, семантику не подменяет.
* В группах с включённым `relations_tone_enabled` — одно дополнительное
  кэшируемое чтение карточки адресата на ход (bounded, без обхода участников).

## 8. Побочные наблюдения

* Рабочее дерево содержит чужие незакоммиченные изменения параллельных
  слайсов (`config/settings.py`, `handlers/youtube.py`,
  `handlers/video_download.py`, `services/factcheck_*`,
  `services/prompt_composer.py`, `services/prompt_registry.py`,
  `services/video_intent.py`, `web/**`, `tests/js/**`). Мой diff их не
  касается; коммитов не делал.
* `services/direct_context_composer.py` не менялся: кадр идёт в защищённом
  блоке `УЧАСТНИКИ` и в plan-блоке, приоритеты композера не затронуты.

## 9. Перепроверка 31.10.2026 (сообщение о потере файлов)

Пришло сообщение, что файлы слайса уничтожены случайным `git reset --hard`.
Фактическое состояние: **восстанавливать было нечего** — все четыре файла
слайса на месте и байт-в-байт совпадают с версией, по которой писался этот
отчёт:

```
services/direct_l1.py          282020d78b990f0b   86842 B
services/direct_chat_service.py 203618b6b45314e6  710338 B
services/social_turn_frame.py   73267b907c06f867   19386 B
tests/test_evol_social_frame.py 08ff362bc8f21374   20018 B
COMBO (sha256 файлов по порядку выше, [:16]) = 8aee1f8dbab3e2df
```

`8aee1f8dbab3e2df` совпадает с fingerprint'ом в шапке отчёта. Ничего не
переписывалось; выполнена только независимая перепроверка контракта и
прогон тестов (см. §6). Отчёт поправлен в одном месте: атрибуция 4 падений
`test_soul1_composer_parity_off.py` (§6 `*`) — это baseline HEAD, а не чужие
незакоммиченные правки.

Фактический payload на реальном пути (offline-проба через тестовые двойники,
синтетика, живых отправок нет):

```
L1 | [УЧАСТНИКИ]
L1 | Говорящий: Вася Пупкин
L1 | Адресат: bot
L1 | кадр хода: адресат [user:42]; reply на [msg:555]
L2 | смысловой акт ответа: answer
L2 | тон: playful
L2 | кадр хода: адресат [user:42]; reply на [msg:555]
STEPS ['l1_planner', 'l2_writer']
```

То есть кадр попадает в оба реально используемых канала (L1-контекст и
plan-блок Writer'а), набор шагов остаётся `l1_planner + l2_writer` —
дополнительных LLM-вызовов нет. В `services/social_turn_frame.py` нет
импортов LLM/провайдеров и сетевых вызовов (проверено grep по
`llm|generate|openai|provider|requests|httpx` — только текст docstring).

Kill-switch `SOCIAL_TURN_FRAME_ENABLED` читается per-call через существующий
`mca_gates.w2_env_axis(name, default=True)`: `settings` → env → default ON;
OFF даёт пустой кадр и прежний payload (`test_09b`).

