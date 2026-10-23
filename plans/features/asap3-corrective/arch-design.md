# ASAP 3 Corrective — архитектурный разбор и минимальный дизайн

Feature: `asap3-corrective` · Lane: ARCH-ASAP3 · 23.10.2026 · только дизайн, код не менялся.
Planning label: **ARCHITECT_REQUIRED**. Verdict: **ARCHITECT_ADJUSTMENT_REQUIRED** (несовместимости в §2).
Внешние источники не нужны: все решения repo-local. Живой рендер Mini App в этой полосе не проверялся (§12).

## 1. RCA (по фактическому коду)

**P1. Инструкции Style Policy теряются.** `render_style_policy_hint` при `max_chars<=0`/`max_items<=0` подставляет
заводские 400/5 (`prompt_style_blocks.py:466-469`) — выключить лимиты нельзя. Три независимые потери: soft-привычки
режутся счётчиком до 5 (`:494-500`); `lines.pop()` выкидывает строки с конца, а soft идут последними — исчезают
поздние инструкции (`:509-513`); если одна оставшаяся строка >400 — возвращается `""`, модель не получает ни одной
инструкции, а композер пишет `style_policy_absent` при живых правилах (`:514-515` → `prompt_composer.py:1541-1550`).
Второй сборщик hint с теми же 400/5 и обрезкой **посередине строки** `[:400]` (`prompt_composer.py:584-585, 842-848`).
Хранилище режет молча: `SOFT_INSTRUCTIONS_MAX=12` (`style_policy.py:66, 628-639`).

**P2. Скрытые лимиты.** Инвентаризация §3: технические (бюджет, окна контекста) должны остаться; скрытность — в отсутствии витрины и молчаливой обрезке.

**P3. Длинное тире не заменяется.** В `RULE_KINDS` тире нет (`style_policy.py:70-71`), `TYPOGRAPHY_BLOCK` — только просьба к модели (`prompt_style_blocks.py:137-142`), постпрохода нет; `forbidden_chars` удаляет символ без замены (`:1386-1398`) — не подходит.

**P4. Имя без гарантированного приоритета.** Порядок есть только в `AliasResolver.resolve` (alias → nickname →
username → id, `summary_aliases.py:50-75`), но: резолвер создаётся один раз на старте из **глобального** ключа
(`bot.py:463, 697`) и раздаётся по DI — чатовые алиасы в Direct/Summary/handlers не видны; `_cache` живёт в
экземпляре (`:23, 74`); `build_alias_resolver` читает чат через `get_chat_param`, который при override отдаёт
**только** чатовый словарь (`chat_params.py:354-377`) — глобальные заменяются целиком, а не по `user_id`; обратная
карта `_by_name` остаётся старой. Свои каскады: `handlers/summary.py:351`, `summary_xml.py:113-116`,
`direct_chat_service.py:8146, 8462, 8605`, `tool_router.py:1778-1788, 3391`, `image_context_memory.py:286, 295`,
`memory_rebuild.py:361`, `chat_lore.py:580, 835`, `stories.py:140`, `oversight.py:62`.

**P5. Память/GraphRAG конкурируют именем.** Привязка к человеку уже есть — `graph_facts.subject_ref_id`
(`database.py:8827, 445-455`); резолв честный: имя → ID только при единственном совпавшем `user_id`, иначе
`unresolved` (`provenance.py:544-587`). Угадывать по строке нельзя: менять надо отображение и канон, не историю.

## 2. Точка → текущее → требуемое

| Точка | Сейчас | Требуется | file:line |
|---|---|---|---|
| hint лимиты | 400/5 зашиты, OFF недоступен | 0 = без лимита, 2 независимых лимита из документа | prompt_style_blocks.py:431-432, 466-469 |
| soft count / длина hint | 6-я привычка и хвост строк не в блоке | все, целыми строками, отчёт об исключённых | :494-515 |
| дубль сборщика | свои 400/5 + `[:400]` | один владелец рендера | prompt_composer.py:584-585, 842-848 |
| хранение soft | 12, молча | ≥64 и блокирующая диагностика | style_policy.py:66, 628-639 |
| validate_document | новые поля выбрасывает | сохранять `hint_limits` (иначе исчезнет при save) | style_policy.py:654-665 |
| Inspector preview | читает **один** слой style doc | global+chat, как рантайм | web/api/speech.py:1525-1531 |
| тире | нет правила | kind `dash`, default ON, plain-only | style_policy.py:70-71, 1280-1281 |
| алиасы merge / live / каскад | словарь целиком; снапшот на старте; 4 шага | merge по uid; per-turn; 5 шагов | summary_aliases.py:50-102, bot.py:463,697 |

Три несовместимости, требующие корректировки: (1) hint-лимиты нельзя вынести в пару ключей каталога без второго save-потока в том же разделе → храним в документе `style.policy`; (2) `0` сейчас означает «применить 400/5» — сентинел обязан стать «без лимита»; (3) Inspector preview собирает один слой и при любом лимите покажет не то, что уйдёт модели.

## 3. Инвентаризация лимитов (§2) — без «универсальной системы»

| # | Что | Зачем | Где | Управляемо | Теряет молча? | Показать |
|---|---|---|---|---|---|---|
| L1 | hint 400 симв. / 5 пунктов | «короткий hint» | prompt_style_blocks.py:431-432 | станет 2 поля OFF/значение | **да** | «Стиль письма» + Inspector |
| L2 | soft 12 / rules 64 | защита документа | style_policy.py:66-67 | да (документ) | **да** (save) | счётчик + блокирующая ошибка |
| L3 | бюджет композера | размер payload | prompt_composer.py:1143, 1226-1236, 1448-1559 | env/гейт | да, `budget_excluded` | «исключён бюджетом» |
| L4 | участники 150 / 24 ч | контекст | direct_chat_service.py:8092-8101, 8120-8121 | каталог | да | «участники 37, cap 150» |
| L5 | thread depth/tokens/chars | контекст | direct_chat_service.py:8499-8533, 8564-8572 | каталог | да | факт обрезки |
| L6 | global context tokens | контекст | direct_chat_service.py:8433-8453 | каталог | да | «фон усечён» |
| L7 | L2 chars | длина ответа | direct_chat_service.py:5505-5507, 8358-8360 | каталог | нет (явный) | уже виден |
| L8 | summary parts / context | стоимость | summary_generator.py:162-168, 223-231, 1646-1661 | каталог | да (WARN в лог) | раздел «Саммари» |
| L9 | graph names 100; окно 12/50 | защита/шум | summary_memory.py:754; style_policy.py:1777-1785 | нет | нет | не показываем |

L1/L2 — пользовательские (OFF по умолчанию), L3–L8 — технические/каталожные (остаются, но видимы там, где настраиваются), L9 — внутренние. «Глобального редактора лимитов» не создаём.

## 4. Дизайн Style Policy (§1)

**Хранение.** `hint_limits: {"max_chars": 0, "max_items": 0}` внутри существующего документа `style.policy`;
`0`/отсутствие = без ограничения. Не ключи каталога: раздел уже сохраняется одним `POST /api/speech/style` с
optimistic-токеном и уже per-chat (`chat_params.overrides`); каталог дал бы второй store и второй save-поток.
Merge **по полям**: отсутствующее в chat поле наследует global, явный `0` в чате = OFF для чата, удаление override
возвращает глобальное; отрицательные значения → блокирующая ошибка.

**Один владелец рендера.** `render_style_policy_hint(policy, *, limits=None)` → `HintRender(block, total_items,
included_items, excluded:[{kind,id}], chars, limited_by)`; `<=0` = без лимита. Исключение — только целыми строками
с конца, детерминированно, с записью в `excluded`; «частичной» строки и «пустого блока при живых правилах» нет.
`prompt_composer._style_hint` теряет свои 400/5 и вызывает этот же рендер (fallback — только при недоступности W3).
`EffectiveStylePolicy` получает `hint_limits`, `hint_chars`, `hint_excluded` (R17: id/kind/числа; тексты — только в
ответе API владельцу).

**UI/Inspector.** В блоке «Стиль письма» (`web/app.js:20332-20510`, рендер из draft) — строка «Ограничения
подсказки»: 2 чекбокса с числовыми полями, текущий размер, «Без ограничения»; при превышении — предупреждение со
списком не вошедших и «Отключить лимит». Inspector показывает всего/включено, источник global|chat, активный лимит
либо «Без ограничения», причину (лимит владельца | `budget_excluded`) и точную редакцию включённых строк. Preview
обязан собирать **оба** слоя style doc, иначе S9 невыполним.

## 5. Дизайн правила «тире» (§3)

Новый kind `dash` («Типографика: длинное тире»): `U+2014` → `-` **только** в `plain`-регионах существующего `segment()`/`plain_regions()`; URL, код, JSON, разметка, версии, многоточие и `verbatim`-цитаты защищены тем же `content_type_exemptions`. Пробелы не меняем, повторный проход — no-op. `dash` — **первым** в `RULE_ORDER` (раньше `forbidden_chars`), иначе «запрещённый символ» удалит тире вместо замены.

Default ON без миграции: `dash.hard.factory` синтезируется в `effective_policy_sync`, если в global/chat нет строки с этим id. Выключение в чате = явная запись того же id с `enabled=false` (merge по id уже работает, `style_policy.py:768-795`); UI показывает «заводское, включено». `verify_outbound_payload` в plain при активном правиле не должен находить `—` (иначе `conflict`, не `pass`). Глобальной regex-замены по payload нет: правило идёт в единственном проходе `apply_style_policy` до сериализации (`style_policy.py:2113-2235`; direct `direct_chat_service.py:3829, 9110`; verify `:1731`).

## 6. Дизайн идентичности (§4–§6)

**Порядок (один владелец — `summary_aliases`):** `chat alias → global alias → Telegram nickname → username без @ →
достоверное имя из памяти → user_id`. `AliasResolver.resolve(user_id, nickname, username, memory_name=None)` —
аддитивно, старые вызовы не меняются. `memory_name` — только при достоверной привязке к тому же `user_id` (ростер
`MAX(author_name)` по uid, `summary_memory.py:3646-3668`, либо `graph_facts.subject_ref_id`); правило единственности
— как в `provenance.resolve_subject_ref` (`provenance.py:574-587`), по сходству строк не угадываем.

**Merge.** `parse_alias_map` (пустые значения отбрасываются — пустая строка не переименовывает; `@` снимается) +
`merge_alias_maps(global_raw, chat_raw)`: global, затем chat по каждому `user_id`. Чатовое значение перекрывает
только свой id; отсутствие ключа = наследование; удаление чатового = возврат глобального; удаление глобального =
следующий источник. `build_alias_resolver(chat_id)` (сигнатура сохраняется — 7 вызовов) строит резолвер из merge и
кладёт `scope_report` (`ok`, `scope`, counts, `invalid_json`) для A15. `canon_name(name, user_id=None)`: при
известном uid — действующий алиас; обратная карта из merged-значений; при двух uid с одним display маппинга нет.

**Live-apply.** Стартовый снапшот перестаёт быть источником для речевых ходов: в начале обработки хода (где
`chat_id` известен) Direct/Summary/handlers/media/tool делают `await build_alias_resolver(chat_id)` и присваивают
в существующий атрибут; `MemoryManager.aliases` обновляется тем же объектом в том же ходе. `bot.py:463/697` —
только fallback нечатовых путей. Инвалидация существующая: `set_chat_params` чистит кэш сразу
(`chat_params.py:489-494`), `ConfigCache` обновляется при сохранении; TTL 120 с не участвует. Ошибка чтения →
прежний резолвер + WARNING + `scope_report.ok=false`.

**Изоляция.** Резолвер per-turn/per-chat, без модульного кэша по имени; чужие overrides не читаются — A12
выполняется конструктивно.

**Память/досье/GraphRAG.** Не переписываем: канон хранения остаётся, старые имена — исходные данные истории; при
отображении участника с известным uid используем действующий алиас; записи только с текстовым именем не привязываем.
`UserResolutionMap` уже строится из резолвера (`direct_chat_service.py:8077-8158`) — после merge перестаёт выдавать
модели противоречивые имена. `manage.py diag aliases` (read-only, `manage.py:1852`) расширяется merged-видом и
списком «один uid — разные имена»; новый сервис не создаётся.

## 7. Пересечения с существующими ASAP

- **SOUL-1 W3/W6**: `style.policy`, hint, слой 10, Inspector — используем, не дублируем; каноны (`ANTI_BOT`, `PREV_*`, `TYPOGRAPHY_BLOCK`) и контракт `apply_style_policy`/`verify_outbound_payload` не трогаем.
- **CFG-07/CFG-01**: `style_policy_view`, `get_chat_param_sourced`, каталог — как есть; новых ключей каталога для hint-лимитов нет (§4), для L3–L8 используем существующие.
- **ASAP-2 (Direct/composer)**: точечно `_preview_manifest` и `resolve_style_policy_ref`; **ASAP-8/ADTR**: следы `author_name` не переписываем.

## 8. Изменяемые функции (минимальный дифф)

1. `services/prompt_style_blocks.py`: `render_style_policy_hint` (+`HintRender`, `limits`, 0=OFF).
2. `services/style_policy.py`: `validate_document` (round-trip `hint_limits`, L2), `EffectiveStylePolicy`, `effective_policy_sync` (лимиты, factory `dash`, отчёт), `build_hint`, `RULE_KINDS`, `RULE_KIND_SPECS`, `RULE_ORDER`, `_apply_dash`, `_RULE_HANDLERS`, `style_policy_view`.
3. `services/prompt_composer.py`: убрать `STYLE_HINT_MAX_*`/обрезку `_style_hint` → делегировать; `StylePolicyRef` получает hint-метрики.
4. `services/summary_aliases.py`: `parse_alias_map`, `merge_alias_maps`, `build_alias_resolver`, `resolve(..., memory_name)`, `canon_name(name, user_id=None)`, `scope_report`.
5. `bot.py` (463/697) и потребители: per-turn refresh (Direct/Summary/handlers/media/tool), без новых сервисов.
6. `web/api/speech.py`: `_style_payload`, `_preview_manifest` (оба слоя), payload лимитов; `web/app.js`/`index.html` — только блок «Стиль письма» и витрина Inspector; `manage.py diag aliases` — merged.

**НЕ трогать:** канонические тексты промптов и `PREV_*`-миграции, `chat_params`-механику merge/optimistic lock, схему БД и историю сообщений, `_merge_spans`/`segment`, `one_word`/`response_extent`, `plans/current_task.md`.

## 9. Порядок, параллельность, риски

`AUDIT (read-only diag) → STYLE+HIDDEN+INSPECTOR → DASH → IDENTITY → MIGRATION/ACCEPT`. STYLE/HIDDEN/Inspector — `SERIALIZE` (общий `style_policy.py` + один API-файл); DASH — `SERIALIZE` после STYLE (тот же файл, `RULE_ORDER`); IDENTITY — `PARALLEL_SAFE` после заморозки контракта `summary_aliases`; UI — `BLOCKED_BY:STYLE`; MIGRATION/ACCEPT — после всех. Заморозка: `render_style_policy_hint`, `build_alias_resolver`, поля `hint_limits`/`scope_report`.

Риски: R1 hint без лимита упирается в бюджет композера → видимый `budget_excluded` (payload не ломается); R2 merge «оживляет» глобальные имена в чатах с полным override → это требуемое A3, проверяем diag до/после; R3 забытый refresh в маршруте → A13 перечисляет маршруты; R4 `forbidden_chars` с `—` → порядок правил + тест; R5 два uid с одним display → без обратного маппинга; R6 preview стал двухслойным → это исправление S9.

## 10. Тест-план (durable)

| ID | Проверка | Класс |
|---|---|---|
| S1/S2 | >400 симв. и >5 привычек при OFF — всё в блоке, порядок детерминирован | CONTRACT |
| S3/S9 | превышение и список не вошедших видны; Inspector = фактическая сборка | CONTRACT/INTEGRATION |
| S4/S5 | смена лимита без рестарта; чаты изолированы | REGRESSION/CONTRACT |
| S6–S8 | `—`→`-` в plain; URL/код/JSON/цитата целы; OFF — текст не меняется | CONTRACT/REGRESSION |
| S10 | L2/L4–L8 не теряют данные молча (issue/флаг виден) | CONTRACT |
| A1–A3, A7, A8 | приоритет и наследование по uid | CONTRACT |
| A4–A6 | hot-change в следующем ходе; после рестарта — сохранённое | REGRESSION/INTEGRATION |
| A9–A11, A14 | старая история/цитаты целы, uid не раздваивается | CONTRACT |
| A12/A13 | параллельные чаты без утечки; Direct/Summary/tool/media — один порядок | CONTRACT/INTEGRATION |
| A15/A16 | сбой конфигурации диагностируется; живой путь uid→алиас→контекст→ответ | REGRESSION/live |

Мокать нельзя: `segment`/защиту (S6–S8 — реальный сегментер), путь `build_alias_resolver` + `chat_params`-кэш (A4/A5 — реальный код), Inspector (реальный FastAPI-клиент и `_preview_manifest`), A16 (манифест `last_run_present=true`; живые сообщения в рабочие чаты не шлём). Live — production-evidence через `diag aliases` и манифест; device-проверки владельца остаются необязательными (политика проекта).

## 11. Миграция (§9)

Factory: `dash.hard.factory` в коде (PG не пишем), `hint_limits` отсутствует = OFF. Existing docs не перезаписываются, кастомные правила/привычки/алиасы сохраняются. Идемпотентность: повторный save не плодит `hint_limits`/dash-строку. Обратимость: откат кода возвращает прежнее поведение, данные не менялись. Проверка прод-конфигурации (read-only): `limits.summary_aliases` в `bot_settings`, число per-chat overrides, ревизии `style.policy`; после деплоя — merged `diag aliases` и Inspector на реальном чате. «Миграция завершена» — не по изменённому дефолту: критерий — эффективная конфигурация в PG показывает OFF-лимиты и активное dash-правило.

## 12. Визуальный контракт (без редизайна)

| Блок | Действие | Сохранить | Разрешено |
|---|---|---|---|
| «Стиль письма» (app.js:20332-20510) | REFINE | порядок, draft-модель, save/reset, пресеты | строка «Ограничения подсказки» (2 чекбокса+числа), предупреждение со списком не вошедших, «Без ограничения» |
| Inspector: слои и skipped (speech.py:1371-1470) | REFINE | таблица слоёв, маскирование, `last_run_note` | для `style_policy_hint`: всего/включено, источник, лимит, причина |
| «Имена и алиасы» (config, keyvalue) | KEEP | KV-редактор, ID→имя | подпись «чатовое значение перекрывает глобальное по ID» |

Новых страниц/дашбордов нет. Живой браузерный рендер Mini App не проверялся (нужен запущенный webapp + TMA-сессия) — это ограничение проверки, а не повод менять структуру раздела.

## 13. Открытые пункты (не Human Gate)

1. L2: поднять `SOFT_INSTRUCTIONS_MAX` до 64 (как `RULES_MAX`), превышение — блокирующее; PM подтверждает по diag, что владелец не хранит >64 привычек.
2. Пустая строка в алиасах = нет алиаса (не переименование); «достоверное имя из памяти» — только uid-привязка (ростер/`subject_ref_id`), иначе fallback на user_id.
