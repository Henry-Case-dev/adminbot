# ASAP 3 Corrective — Style Policy, фаза 1 (без UI)

Lane: `ASAP3-STYLE` · 23.10.2026 · кодовый кандидат фазы 1.
Источник: `plans/features/asap3-corrective/source-2026-10-23.md` §1, §3, §8, §9.
Дизайн: `plans/features/asap3-corrective/arch-design.md` (три обязательные корректировки).

## 1. Root cause (до / после)

### 1.1 Скрытая подстановка заводских лимитов

**Было** (`services/prompt_style_blocks.py:431-432, 466-469` до правки):

```python
STYLE_POLICY_HINT_MAX_CHARS = 400
STYLE_POLICY_HINT_MAX_ITEMS = 5
limit_chars = int(max_chars) if int(max_chars or 0) > 0 else STYLE_POLICY_HINT_MAX_CHARS
limit_items = int(max_items) if int(max_items or 0) > 0 else STYLE_POLICY_HINT_MAX_ITEMS
```

`0` означал не «выключено», а «применить 400/5»: лимиты нельзя было отключить.

**Стало** (`services/prompt_style_blocks.py:438`): `HINT_LIMIT_OFF = 0`, `0`/отсутствие =
без ограничения; заводских значений больше нет.

### 1.2 Три независимые потери в рендере hint

**Было** (`prompt_style_blocks.py:494-500, 509-515` до правки):

* привычки резались счётчиком `len(soft_texts) >= limit_items` (5);
* `lines.pop()` выкидывал строки **с конца**, а soft-привычки идут последними —
  исчезали самые поздние инструкции владельца;
* если единственная оставшаяся строка >400 символов — возвращался `""`:
  модель не получала ни одной инструкции, а композер писал `style_policy_absent`
  при живых правилах.

**Стало** (`prompt_style_blocks.py:479-688`): `HintRender` (str-совместимый)
отдаёт блок + `total_items` / `included_items` / `included_keys` /
`excluded[{key, kind, reason}]` / `max_chars` / `max_items` / `limited_by` /
`truncated=false`. Инструкция — атомарная единица: входит целиком либо
исключается целиком с причиной `user_limit`/`budget_excluded`. Обрезки строки
посередине нет; пустой блок при живых правилах возможен только если лимит
владельца физически меньше обёртки блока — и это видно в `excluded`.

### 1.3 Второй сборщик hint в композере

**Было** (`services/prompt_composer.py:584-585, 842-848` до правки): собственные
`STYLE_HINT_MAX_ITEMS/CHARS = 5/400` и `"\n".join(lines)[:400]` — обрезка
посередине строки, независимая от W3.

**Стало** (`prompt_composer.py:840-853`): `_style_hint`, `STYLE_HINT_MAX_*` и
`STYLE_POLICY_KEY` удалены; снимок строится только `style_policy.resolve_style_policy_ref`.
При недоступности W3 снимок честно помечается `style_policy_unavailable`, а не
отдаёт частичный hint за полный. `StylePolicyRef` получил hint-метрики
(`hint_total/included/excluded/limits/limited_by/truncated`).

### 1.4 Молчаливый потолок привычек

**Было** (`services/style_policy.py:66, 628-639` до правки): `SOFT_INSTRUCTIONS_MAX = 12`,
13-я привычка отбрасывалась при `validate_document` с диагностикой
`soft_truncated`, которая не была блокирующей.

**Стало** (`style_policy.py:69, 756-761`): потолок 64 (как у правил);
`soft_truncated`/`rules_truncated` добавлены в fatal-диагностику — документ с
превышением не сохраняется, данные владельца не теряются молча. `validate_document`
round-trip сохраняет 13+ привычек без потерь.

## 2. Лимиты hint: хранение и семантика

* Хранение — **внутри существующего документа** `style.policy`:
  `hint_limits: {"max_chars": int, "max_items": int}`. Отдельных ключей каталога
  и второго save-потока нет (`style_policy.py:639-670, 734-741, 776-804`).
* `validate_document` делает обратный round-trip: `validate(validate(doc))` не
  меняет `hint_limits`; отсутствие поля сохраняется как отсутствие, явный `0` —
  как «выключено». Отрицательное/нечисловое значение — `hint_limit_negative:*` /
  `hint_limit_invalid:*` в fatal (save блокируется, не подменяется на 400/5).
* Merge **по полям** (`style_policy.py:931-949`): чатовое значение перекрывает
  только своё поле, остальное наследует global; слой-источник каждого значения
  виден в `hint_limit_sources` (global/chat/default). Удаление override
  возвращает глобальное значение.
* `EffectiveStylePolicy` получает `hint_limits`, `hint_limit_sources`,
  `hint_total`, `hint_included`, `hint_excluded`, `hint_limited_by`,
  `hint_truncated`; `style_policy_view` отдаёт `hint_limits` (лимит, источник,
  `off`, текущий размер) и `hint_render` (всего/включено/исключено/overflow) —
  Inspector и UI получают фактическую сборку, а не «желаемые» настройки.
* Если промпт объективно не влезает в бюджет композера, слой по-прежнему
  помечается `budget_excluded` (видимо в манифесте); per-line
  `budget_excluded` поддержан в рендере параметром `budget_chars`, но
  композерный бюджет остаётся слоевым решением (не подменяем его оценкой).

## 3. Правило «длинное тире»

* Новый kind `dash` (`style_policy.py:72-74, 122-131`), default ON без миграции:
  `dash.hard.factory` синтезируется в `effective_policy_sync`
  (`style_policy.py:951-984`), если ни global, ни chat не содержат строку с этим
  id. Выключение — явная запись того же id с `enabled=false` (merge по id уже
  работает), доступно per-chat.
* `RULE_ORDER` (`style_policy.py:1463-1467`): `dash` **первым**, до
  `forbidden_chars` — иначе «запрещённый символ» удалил бы тире вместо замены.
* `_apply_dash` (`style_policy.py:1548-1573`): U+2014 → `-` только в `plain`
  регионах существующего `segment()`/`protected_ranges`; URL, код, JSON,
  разметка, версии, многоточие и `verbatim`-цитаты (`extra_protected`) не
  трогаются. Пробелы и структура предложения сохраняются; повторный проход —
  no-op.
* Заводское правило не считается «owner-политикой»: локальная правка повторов
  SOUL-09 остаётся выключенной без владельческих правил (`owner_rules`,
  `style_policy.py:396-404`), иначе default-тире включало бы тихую потерю текста.
* `verify_outbound_payload` при активном правиле видит остаточное `—` в plain
  как `conflict`, а не `pass` (общий механизм, отдельного кода не потребовалось).

## 4. Тесты (durable, RED→GREEN)

Новый файл `tests/test_asap3_style_hint_limits.py` (16 тестов, все GREEN):

| ID | Что проверяет |
|---|---|
| S1 | hint > 400 символов при OFF — все инструкции в блоке, `truncated=false` |
| S2 | 9 мягких привычек — ни одна не исчезает (было 5) |
| S3 | `max_items`/`max_chars` включены → `included < total`, `excluded` с `user_limit`, витрина `overflow=true`, режутся только целые строки |
| S4 | лимит, сохранённый после первого резолва, применяется следующим резолвом (без рестарта) |
| S5 | лимит чата A не влияет на чат B |
| S6 | `—` → `-` в обычной речи (validator + `apply_style_policy`), идемпотентно |
| S7 | URL/код/JSON/дословная цитата сохраняют `—`, исход `exempted` |
| S8 | выключенное правило (global disable / chat disable по id) не меняет текст |
| S9 | структура отдаёт фактически включённые правила, выключенное не считается |
| S10 | 13 привычек сохраняются, >64 — `soft_truncated` + fatal; витрина показывает причину |
| — | round-trip `hint_limits`, merge по полям, отрицательный лимит блокирует save, второго сборщика hint нет |
| — | `save_policy_document` не стирает `hint_limits`, если редактор не прислал поле (правка правил в UI) |

Обновлены контрактные проверки `tests/test_soul1_style_policy.py`:
заводское `dash`-правило присутствует по умолчанию (политика «absent» относится
к документам владельца), hint больше не ограничен 400/5, исходы правил ищутся
по `kind` (dash идёт первым). Тест `forbidden_chars` переведён с `—` на `·`:
удаление тире больше не является его сценарием.

### Прогоны (полный pytest не запускался — рамка задачи)

```text
style/policy/payload/repetition/cover (9 файлов, вкл. новый): 263 passed
cover/asap8/summary style (12 файлов):                       253 passed
composer layers/parity/core/flags/direct-context/web:        113 passed
direct/prompts/migrations/lore/dossier/dream/factcheck:      216 passed
nostalgia/persona/smartsearch/summary/youtube/checkup:       152 passed
extent/telemetry/ADD-EXP:                                     72 passed
speech UI/persist-chat-scope/mobile-entry:                    42 passed
SOUL-1 W5 observer gates:                                     17 passed
```

## 5. Что осталось (вне фазы 1)

* **UI** (`web/**`): строка «Ограничения подсказки» в разделе «Стиль письма»
  (2 чекбокса + числовые поля, «Без ограничения», предупреждение со списком не
  вошедших и кнопкой отключения лимита), отображение `hint_limits`/`hint_render`
  в Effective Prompt Inspector. API уже отдаёт все нужные поля
  (`style_policy_view`), запись лимитов пройдёт существующим `POST /api/speech/style`
  (merge сохраняет незнакомые ключи документа).
* **MIGRATION / §9**: заводские значения обновлены в коде; отдельной записи в PG
  не требуется (`hint_limits` отсутствует = OFF, `dash` синтезируется). Проверка
  прод-конфигурации (read-only) и подтверждение, что эффективная конфигурация в
  PG показывает OFF-лимиты и активное dash-правило, — задача фазы MIGRATION/ACCEPT.

## 6. Риски и наблюдения

* R1: при снятых лимитах hint вырос (пример rich-политики: 948 символов). Если
  бюджет композера не позволяет — слой видимо уходит в `budget_excluded`, payload
  не ломается. Наблюдать в манифесте после деплоя.
* R2: `dash` первым в `RULE_ORDER` меняет индексацию `results`; порядок исходов
  не является публичным контрактом (потребители читают по `kind`/статусам),
  тесты переведены на поиск по `kind`.
* R3: заводское правило тире увеличивает `policy.rules` на один элемент в
  обычной речи; `hard_kinds` теперь содержит `dash`. Это видимая диагностика, а
  не скрытая подмена.
* R4: `hint_limits` в чат-документе — это отдельный документ `style.policy`;
  UI обязан сохранять его тем же merge-путём (иначе поле исчезнет). Механика
  `_write_document` уже сохраняет неизвестные ключи, а `save_policy_document`
  сохраняет прежний `hint_limits`, если присланный документ поля не содержит.
  UI-фаза должна присылать поле явно, чтобы менять лимит или сбрасывать его в OFF.
