# ASAP 3 §2 — инвентаризация фактических ограничений приложения

Feature: `asap3-corrective` · Lane: `ASAP3-LIMITS-INVENTORY` · 24.10.2026
Источник: `plans/features/asap3-corrective/source-2026-10-23.md` §2 (аудит ограничений), §9,
§10 п.2. Дизайн: `arch-design.md` §3 (L1–L9).

Метод: чтение production-кода по путям применения (не по комментариям). Каждая строка таблицы
проверена в текущем коде; номера строк — на момент коммита полосы. Сеть/прод/LLM не использовались.

Классы:

- `USER_VISIBLE` — у владельца есть действующая настройка (каталог параметров / блок раздела).
- `TECHNICAL_VISIBLE` — защитный/технический лимит; остаётся, но его действие и причина
  деградации видны (манифест/Inspector/WARN с числами, закрытый код причины).
- `HIDDEN_LOSS` — может молча исключить настроенные/принадлежащие владельцу данные.
- `NOT_RELEVANT` — внутренний механизм, не затрагивающий пользовательские настройки (обоснование в строке).

## 1. Реестр ограничений

| # | Что ограничивает | Зачем | Где применяется (file:line) | Может менять владелец | Могло терять молча | Класс | Где показывать |
|---|---|---|---|---|---|---|---|
| 1 | Размер блока Style Policy hint (`max_chars`) | полнота инструкций | `services/prompt_style_blocks.py:630-682`; merge `services/style_policy.py:931-945,1023-1049` | да, 2 поля в «Стиль письма», OFF по умолчанию | **было да** (400) → исправлено в фазе STYLE | `USER_VISIBLE` | «Стиль письма» + Inspector (всего/включено, лимит, причина) |
| 2 | Количество инструкций hint (`max_items`) | то же | те же | да, OFF по умолчанию | **было да** (5) → исправлено | `USER_VISIBLE` | там же |
| 3 | Число мягких привычек при сохранении (12 → 64) | защита документа | `services/style_policy.py:69`, fatal `soft_truncated` `:711,758` | да (документ «Стиль письма») | **было да** → теперь блокирующая диагностика | `TECHNICAL_VISIBLE` | счётчик привычек + fatal в сохранении |
| 4 | Число правил в документе (64) | защита документа | `services/style_policy.py:70`, `rules_truncated` `:694,758` | да | **было да** → блокирующая диагностика | `TECHNICAL_VISIBLE` | там же |
| 5 | Аддитивный бюджет композера (токены) | размер payload модели | `services/prompt_composer.py:1100, 1486-1525`; `mca_gates.composer_additive_budget_tokens()` | да (env/каталог) | да, но честно: `budget_excluded` в манифесте/Inspector | `TECHNICAL_VISIBLE` | Inspector: слой исключён бюджетом, не лимитом владельца |
| 6 | Участники карты: cap 150, окно 24 ч | размер контекста | `services/direct_chat_service.py:8180-8231` (`limits.chat_map_participants_cap/hours`) | да (chat params) | да (менее активные не в карте) | `USER_VISIBLE` | существующий блок лимитов чата |
| 7 | Окно `<Global_Context>`: число сообщений / токены / символы | размер контекста | `:8484-8530` (`limits.chat_global_context_*`); WARN `direct: global context truncated` `:8525` | да (chat params) | да, с WARN и меткой объёма в самом блоке | `TECHNICAL_VISIBLE` | метка «фон: дословно последние N» + WARN |
| 8 | Глубина треда (`chat_thread_max_depth`) | размер контекста | `:8585-8610` | да | да (per-chat гарантия; композер идёт до корня) | `USER_VISIBLE` | блок лимитов чата |
| 9 | Бюджет треда (tokens/chars) | размер контекста | `:8610-8640` (`limits.chat_thread_*`) | да | да (в бюджете композера) | `TECHNICAL_VISIBLE` | Inspector (слой исключён бюджетом) |
| 10 | Широкий фон L2 в контексте (символы) | размер контекста | `:8440-8460` (`limits.chat_level2_max_chars`) + WARN `:8454` | да | да, но не молча (WARN) | `TECHNICAL_VISIBLE` | WARN + строка «широкий фон:» |
| 11 | **Текущий вопрос пользователя (cap 800, срез посередине)** | защита запроса | `:6660-6692` (`limits.chat_current_question_max_chars`) | да (chat params) | **было да и молча** → теперь WARN `current question truncated` с числами (`:6673,6683`) и WARN `current question dropped` при `room=0` (маркеры заняли весь cap, `:6678`) | `HIDDEN_LOSS` → исправлено | WARN + chat params |
| 12 | **Досье в карточке: 10 строк (досье — факты/мемы; flat — факты/связи) + 1200 символов** | размер блока памяти | `:445,448,8086-8175`; `services/dossier_prompts.py:584-646` (`stats`) | нет (константы модуля) | **было да и молча**: 10-элементная срезка применялась ДО форматтера, `stats` видел ≤10 и WARN не срабатывал, а flat-WARN считал только факты (`n>10`), поэтому связи резались без сигнала. Теперь totals считаются до срезки, flat-условие — по сумме строк (`facts+links`), мемы запрошены `cap+1` и при переполнении показываются как `10/>10`; счётчик в заголовке — настоящий (35, не 10) | `HIDDEN_LOSS` → исправлено | WARN (числа) + будущий счётчик в разделе памяти |
| 13 | **Примеры регистра речи: ≤4 строки / 140 токенов / 700 символов** | бюджет few-shot §3.2 | `services/mca_expression.py:160-164, 408-465, 474-505`; отбор `services/mca_sample_library.py:66-71, 1370-1440` | нет (бюджет контракта ADD-EXP) | **было да и молча** (дважды): (а) полная потеря выдавалась за `expression_examples_absent`; (б) резолвер обрывал отбор на 4, поэтому `total_items` никогда не был >4. Теперь резолвер считает ВСЕ подходящие одобренные строки (`stats.eligible/selected/dropped`), `ExampleRender.total_items` берётся из него, WARN `kept=4/20` | `HIDDEN_LOSS` → исправлено (`budget_excluded` + WARN `kept=X/Y`) | Inspector (причина слоя) + библиотека примеров |
| 14 | **Поля примера при сохранении: input 2000 / reply 4000 символов** | защита БД/rendering | `services/mca_sample_library.py:565-586` (`_clip_field`); API-потолок `web/api/speech.py:3466-3469` (`SampleWrite`) | нет (технический потолок) | через владельческий UI недостижимо (422), но не-UI писатели (tools/import) режутся — теперь WARN `field clipped` с числами (defense-in-depth) | `TECHNICAL_VISIBLE` (WARN) | WARN + счётчик длины в редакторе примеров (UI — отдельная полоса) |
| 15 | Legacy-саммари: число sendMessage-частей | Telegram/лимит отправки | `services/summary_generator.py:162-169, 223-231` (`limits.max_summary_parts`) | да | да, но WARN `LEGACY_CHUNKS_CAPPED` с числами | `TECHNICAL_VISIBLE` | WARN + chat params |
| 16 | L2-review вызовы (≤6) и writer-вызовы (≤2) | бюджет LLM | `services/summary_generator.py:184-202`; review-модуль | нет (технический) | нет (влияет на стоимость, не на данные владельца) | `NOT_RELEVANT` | метрики стадии в Inspector саммари |
| 17 | Активация GraphRAG: 5 фактов в горячий кэш, 12 узлов-кандидатов | анти-взрыв выборки | `services/summary_memory.py:73,75,4613-4642` | нет | нет: остальные факты остаются доступны обычной выборкой/KNN | `NOT_RELEVANT` | не требуется |
| 18 | Имена/связи GraphRAG: 100/200 символов; поля факта 100/200/400 | форма данных из LLM | `services/summary_memory.py:164-167,754-755` | нет | да, но это нормализация вывода экстрактора, а не настройка владельца | `NOT_RELEVANT` | не требуется |
| 19 | **Tail текста для экстрактора/графа: 8000 символов** | стоимость LLM | `services/summary_memory.py:164,288,753`; срезы `:1251-1262` (YouTube-сжатие), `:3314-3322` (memorize), `:5305-5313` (граф-батч) | нет | **было да и молча**: длинный текст владельца терял начало без сигнала; теперь WARN с числами на всех трёх срезах | `HIDDEN_LOSS` → исправлено (WARN) | WARN в журнале памяти |
| 20 | История редакций документа Style Policy (20) | bounded growth | `services/style_policy.py:65,732,2569` | нет | нет (старые ревизии — архив, текущий документ цел) | `NOT_RELEVANT` | история ревизий в разделе |
| 21 | Анти-залипание: окно 12 реплик, ban 50, архив 200 | защита от повторов | `services/style_policy.py:1990-1996` | нет | нет (внутренняя дедупликация n-грамм, текст владельца не режется) | `NOT_RELEVANT` | не требуется |
| 22 | Блоки контекста по каталогу: отношения 600, лор 3000, якорь стиля 400, RAG-память 2000 (символы) | размер контекста | `services/direct_chat_service.py:7189-7200, 7897-7910, 7807-7815, 8334-8345`; `services/param_catalog.py:1606,1732,1749,1876,1907` | да (каталог параметров) | да, с WARN и маркерами в блоках | `USER_VISIBLE` / `TECHNICAL_VISIBLE` | каталог параметров (`limits_*` группы) |
| 23 | Текст в редакторе промптов (200000 символов) | защита API | `web/api/speech.py:1963` | нет | нет: ошибка валидации видна владельцу (422), не молчаливая обрезка | `NOT_RELEVANT` | форма редактора (сообщение об ошибке) |

## 2. Итог

- Всего проверено ограничений: **23** (класс — по основному действию строки).
- `USER_VISIBLE`: **5** (№1, 2, 6, 8, 22).
- `TECHNICAL_VISIBLE`: **8** (№3, 4, 5, 7, 9, 10, 15, 14).
- `HIDDEN_LOSS` найдено: **4** (№11 текущий вопрос, №12 досье, №13 примеры регистра,
  №19 tail экстрактора). **Исправлено: 4/4.** №14 — defense-in-depth в
  `TECHNICAL_VISIBLE` (владельческий UI отдаёт 422), в HIDDEN_LOSS не входит и здесь
  не считается.
- `NOT_RELEVANT`: **6** с обоснованием (№16, 17, 18, 20, 21, 23).
- 5+8+4+6 = 23.

Правка после ревью `review-limits.md` (F1–F3, 24.10.2026): строка №19 переклассифицирована
`TECHNICAL_VISIBLE → HIDDEN_LOSS` (WARN экстрактора фактически отсутствовал), №14 — в
`TECHNICAL_VISIBLE` как defense-in-depth (владельческий UI отдаёт 422), №11/12/13 усилены
(см. §3).

Правка после ревью r2 (`review-limits-r2.md`, F1-R/F2-R/F3-R, 24.10.2026): плоская ветка
предупреждает о срезе связей по сумме строк, мемы считаются через `limit=cap+1`
(`10/>10`), итоговая арифметика §2 приведена к 5+8+4+6 = 23 без двойного счёта.

## 3. Что именно было скрытой потерей и чем исправлено

### 3.1 №11 — текущий вопрос обрезался посередине без сигнала

`_render_current_question` режет текст сообщения до `limits.chat_current_question_max_chars`
(default 800) через `stripped[:cap]`; при медиа-маркерах — до резерва под суффикс. Владелец мог
написать вопрос длиннее и модель получала начало без единого признака усечения (и без WARN).
Правка: WARN `direct: current question truncated | chars=N -> M | cap=K` (только числа; R17).
Уточнение после ревью: при `room == 0` (медиа-маркеры заняли весь cap) текст вопроса не входил
вовсе и раньше исчезал без сигнала — добавлен отдельный WARN
`direct: current question dropped | chars=N | cap=K | markers=M` (`direct_chat_service.py:6676-6684`).
Payload не менялся — поведение и байты промпта при коротком тексте прежние.

### 3.2 №12 — досье в карточке резало факты/мемы молча

`format_dossier_block` урезает мемы, затем факты до 1200 символов и возвращает только текст:
вызывающий код не мог понять, что часть фактов не попала в карточку. Правка: необязательный
out-параметр `stats` (`facts_total/facts_kept/memes_total/memes_kept/truncated`), существующие
вызовы без него не меняются (`services/tool_router.py:2158`); в `build_persona_card` при
`truncated` — WARN `direct: persona dossier capped` с числами. Семантика усечения не изменена.

**Исправление после ревью (F1, было нерабочим).** `_PERSONA_MAX_ITEMS = 10` применялся к
`facts/protected/lore` и `memes` ДО `format_dossier_block`, поэтому `stats` физически видел ≤10
строк и `truncated` всегда был `False`: WARN не срабатывал, а заголовок «знаю о тебе: 10 фактов»
показывал усечённое число как полное. Теперь в `direct_chat_service.build_persona_card:8086-8175`:

- `facts_total = len(lore + protected + facts)`, `memes_total` — наблюдённое число мемов
  (запрос `cap+1`, см. ниже) считаются ДО срезки;
- форматтеру по-прежнему уходят только 10 строк (бюджет и payload не менялись), но истинные
  totals возвращаются в `stats` после вызова, и `truncated` пересчитывается по ним;
- WARN один и тот же в обеих ветках: `mode=dossier` (`:8163`) и `mode=flat` (`:8116`, irony OFF
  тоже режет список до 10);
- счётчик в заголовке = настоящий total (как уже было в flat-ветке), а не число вошедших строк.

Замер первого ревью (30 фактов + 5 защищённых + 15 мемов, irony ON) — до правки r2:

```text
до:   знаю о тебе: 10 фактов, 0 связей; 10 строк фактов; WARN нет
после: WARNING direct: persona dossier capped | chat=1 | mode=dossier |
        facts_kept=10/35 | memes_kept=10/15 | cap_chars=1200
       знаю о тебе: 35 фактов, 0 связей
```

Число `memes_kept=10/15` в этой строке было **недостижимо в проде**: мемы запрашивались с
`limit=10`, SQL отдаёт ≤10 строк (прод-подобный фейк давал `10/10`), а flat-WARN не видел
потери связей. Это и есть F1-R/F2-R.

**Исправление после ревью r2 (F1-R, F2-R).** Те же числа: `memes_kept=10/15` было
недостижимо, а flat-WARN не видел потери связей.

- flat-ветка (irony OFF) режет `lines[:10]` по сумме «факты + связи», а WARN проверял
  только `n > 10`; при facts=10/links=5 и facts=5/links=10 связи исчезали без сигнала.
  Теперь условие по сумме строк (`n + m > 10`), числа честные:
  `facts_kept=min(n,10)/n`, `links_kept=max(0,min(m,10-n))/m`; тело карточки и заголовок
  не изменились (payload байт-в-байт), поле `memes_kept=0/0` заменено на `links_kept`;
  `services/direct_chat_service.py:8111-8122`;
- мемы запрашивались с `limit=10`, а SQL (`services/database.py:11237`) отдаёт уже
  урезанный список — «потеря 11..N» была неизмерима. Теперь `limit=cap+1` (детект
  переполнения без второго COUNT): при переполнении WARN пишет `memes_kept=10/>10`, без
  переполнения — точное `10/10`; `stats["memes_total"]` — наблюдённое число (≤11),
  `stats["memes_capped"]` — флаг (`direct_chat_service.py:8141-8144, 8157-8170`).

Замер на прод-подобном фейке (`list_chat_memes` соблюдает `LIMIT`, как SQL):

```text
dossier, facts=30+5, memes=15 (запрос limit=11):
  WARNING direct: persona dossier capped | chat=1 | mode=dossier |
          facts_kept=10/35 | memes_kept=10/>10 | cap_chars=1200
dossier, facts=20, memes=10 (без переполнения):
          facts_kept=10/20 | memes_kept=10/10
flat, facts=10, links=5:
  WARNING ... | mode=flat | facts_kept=10/10 | links_kept=0/5 | cap_items=10
  тело: 10 строк, из них 0 строк связей (заголовок «5 связей» — теперь с WARN)
flat, facts=5, links=10:
          facts_kept=5/5 | links_kept=5/10 | cap_items=10   (тело: 5 строк связей)
```

Тесты: `test_persona_card_counts_items_before_ten_item_cap` (обновлён: `memes_kept=10/>10`
+ проверка `limit=11`), `test_persona_card_meme_total_is_exact_without_overflow`,
`test_persona_card_flat_branch_logs_item_cap`, `test_persona_card_flat_branch_warns_when_facts_fill_cap`,
`test_persona_card_flat_branch_warns_when_links_are_cut`
(`tests/test_asap3_hidden_limits.py`). Фейк `_PersonaDB` соблюдает `limit`, как прод.

### 3.3 №13 — одобренные примеры речи исчезали как «набор отсутствует»

`render_expression_examples_block` молча отбрасывал строки по бюджету §3.2 и возвращал `""`;
`build_expression_examples_refs` в этом случае отдавал **пустой кортеж**, и композер писал
`expression_examples_absent` — потеря владельческого контента выглядела как пустая библиотека.
Правка:

- `render_expression_examples_block` → `ExampleRender` (`str`-совместимый) с фактическим составом
  `total_items/included_items/dropped/limited_by` (числа, без текста реплик);
- полная потеря при непустых одобренных строках → `SampleRef(enabled=False,
  skip_reason="budget_excluded")` — код из закрытого `prompt_composer.SKIP_REASONS`, виден в
  манифесте и Inspector как техническая причина, а не «набора нет»;
- частичная потеря → WARN `[expression] examples capped | kept=X/Y | by=items/tokens/chars`;
- бюджет ≤4/140/700 и контракт ADD-EXP §3.2 не изменены (это защитный лимит, а не настройка).

**Исправление после ревью (F2, было нерабочим).** Резолвер сам обрывал отбор на 4
(`mca_sample_library.py:1417-1418` старой версии), поэтому `render_expression_examples_block`
никогда не видел больше 4 строк: `total_items`/`dropped` описывали остаток после отбора, а не
набор владельца, и WARN `kept=X/Y` не мог сработать (20 одобренных → `total=4 kept=4 dropped=0`).
Теперь:

- `resolve_expression_examples_ex(..., stats=...)` НЕ обрывает счёт: `eligible` — все подходящие
  одобренные строки режима, `selected`/`dropped` — выдача и потеря (`mca_sample_library.py:66-71,
  1370-1440`); ранние выходы (OFF/absent) оставляют честные нули;
- `render_expression_examples_block(..., available_items=N)` берёт `total_items` из резолвера
  (`mca_expression.py:408-465`), `limited_by="items"` появляется и когда строки отбросил отбор;
- `build_expression_examples_refs` передаёт `stats["eligible"]` в рендер (`mca_expression.py:483-495`),
  поэтому WARN `kept=4/20 | by=items` отражает реальность.

Замер на пробе ревью (20 одобренных mat-строк, режим off):

```text
до:   resolver rows=4; ExampleRender total=4 included=4 dropped=0 limited_by=""; WARN нет
после: stats={'eligible': 20, 'selected': 4, 'dropped': 16}
       WARNING [expression] examples capped | mode=off | kept=4/20 | by=items
       ExampleRender total=20 included=4 dropped=16 limited_by="items"
```

Тест: `test_expression_resolver_counts_approved_rows_before_item_cap` (реальный сev резолвера, не
мок) в `tests/test_asap3_hidden_limits.py`.

### 3.4 №14 — поля примера резались при сохранении молча

`normalize_fields` резал `input_text` до 2000 и `reply_text` до 4000 символов без какого-либо
сигнала. Правка: `_clip_field` → WARN `[humor-samples] field clipped | field=… | chars=N -> M`.
Создание/обновление примера не изменилось по результату, но потеря больше не бесшумна.
Уточнение после ревью: владельческий UI этот потолок превысить не может — `SampleWrite`
(`web/api/speech.py:3466-3469`) отдаёт 422 с ошибкой валидации; WARN нужен как defense-in-depth
для не-UI писателей (tools/импорт) и сам по себе не является восстановлением потерянного поля,
поэтому строка переклассифицирована в `TECHNICAL_VISIBLE`. Тест на WARN:
`test_sample_field_clip_is_logged`.
Осталось (вне write-scope полосы, `web/**` запрещён): счётчик длины и предупреждение в редакторе
примеров — существующий UI-раздел библиотеки.

### 3.5 №19 (нашлась на ревью) — tail экстрактора 8000 резал текст владельца молча

`summary_memory.py:3308` делал `tail = text[-8000:]` без сравнения длины и без лога: длинное
сообщение владельца теряло начало при извлечении фактов, и это не было видно нигде. Та же схема —
YouTube-сжатие (`:1254`) и граф-батч (`:5293`). Строка инвентаризации утверждала «WARN
экстрактора», которого не существовало, поэтому переклассифицирована в `HIDDEN_LOSS`.
Правка (только видимость, бюджеты 8000 не менялись):

- `memorize`: WARN `graphrag memorize: extract input truncated | chat_id=… | source=… | chars=N -> 8000`
  (`:3314-3322`);
- YouTube: WARN `[graphrag hook] youtube transcript clipped for compress | chat_id=… | chars=N -> 8000`
  (`:1251-1262`);
- граф-батч: WARN `graph extract: batch tail clipped | chat_id=… | chars=N -> 8000` (`:5305-5313`).

R17: в лог идут только числа, текст владельца не логируется. Тест:
`test_extract_tail_truncation_is_logged` (проверяет и длину фактически отправленного хвоста, и
отсутствие текста в логе).

## 4. Сверка с уже сделанным (без дублей)

| Проверка | Подтверждение |
|---|---|
| `hint_limits` OFF по умолчанию, без подстановки 400/5 | `prompt_style_blocks.py:436-438,538-544,630-682`; `style_policy.py:931-945,1023-1049,2698-2726` |
| Дубль 400/5 в композере убран: единственный владелец рендера | `prompt_composer.py:1486-1525` использует `policy.hint`; `STYLE_HINT_MAX_*` в коде отсутствуют (`grep` пуст) |
| Потолок привычек 64 + fatal (не тихая потеря) | `style_policy.py:69,711,758`; тесты `test_asap3_acceptance.py::test_s10_*` |
| Второго пути обрезки инструкций нет | обрезка только в `render_style_policy_hint`; `budget_chars` — явный технический параметр (`budget_excluded`), не владельческий лимит |
| Бюджет композера не выдаётся за лимит владельца | `test_asap3_acceptance.py::test_s10_budget_exclusion_is_not_disguised_as_user_limit` |

## 5. Прогон

Правка F1-R/F2-R/F3-R поверх `64785490` (база ревью r2 — `e6c9b65b`); только
`direct_chat_service.py`, `tests/test_asap3_hidden_limits.py`, этот файл.

```text
tests/test_asap3_hidden_limits.py (13 + 3 новых)      16 passed
tests/test_add_exp_expression.py + test_samples_fewshot  52 passed
tests/test_dossier_irony.py + test_chat_lore.py +
  test_direct_chat.py                                   193 passed
tests/test_asap3_style_hint_limits.py + acceptance +
  identity_aliases                                       45 passed
tests/test_dossier_prompts.py + test_soul1_w4_sample_library  52 passed
tests/test_soul1_w4_examples_scope.py + categories +
  factory_persist                                        29 passed
tests/test_graphrag_memory.py + asap44_batch_breaker +
  asap8_v63_b03 + asap8_v6_p1_d09                       203 passed
```

Итого затронутые файлы: **590 passed, 0 failed** (16 hidden limits + 371 по досье/примерам/
direct/стилю/identity + 203 memory). Все прогоны — локальные, целевые файлы (рамка полосы:
≤3 мин на файл, без сети/прода).

Пробы ревью r2, перезапущенные на правке: `memes_kept=10/>10` при запросе `limit=11`;
flat facts=10/links=5 → `links_kept=0/5` + WARN; flat facts=5/links=10 → `links_kept=5/10`
+ WARN (`tests/test_asap3_hidden_limits.py`).

## 6. Что осталось и почему

1. №14 — предупреждение о длине в редакторе примеров (`web/**` — вне write-scope полосы; WARN уже
   делает потерю диагностируемой, UI-потолок отдаёт 422).
2. №12 — владельческая настройка бюджета досье (сейчас константа 1200) не вводилась: источник §2
   требует видимости деградации, а не новой универсальной системы лимитов; при необходимости это
   отдельный ключ каталога `limits.*` в разделе памяти, не в этой полосе.
3. №13 — «настраиваемость» бюджета примеров не вводилась: это защитный бюджет контракта ADD-EXP
   §3.2; сейчас потеря видна кодом `budget_excluded` и числами в WARN.
4. №12, связи: `get_persona_card` читает связи с SQL `LIMIT ?`
   (`services/database.py:11025-11038`), поэтому total связей вызывающему неизвестен:
   заголовок и числа показывают только полученные строки. В flat-ветке потеря уже
   полученного набора теперь видна (`links_kept=5/10` + WARN), но связи сверх SQL-лимита
   неотличимы от отсутствующих — для точного total нужен `COUNT` в `database.py`, файл
   вне write-scope полосы, отдельная микрозадача.
5. Прод-конфигурация (реальные значения chat params/каталога) в полосе не читалась — сеть/прод
   запрещены; проверка эффективных значений остаётся postdeploy (`migration.md` §5).
