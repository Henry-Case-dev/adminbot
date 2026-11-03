# PVR-S3 - независимое ревью (полная история версий + N1/N2)

**Вердикт: Needs Fixes.** Одна блокирующая находка (B1) с точечной правкой в одном файле:
статус и доступность действия у строк-событий в `entries[]` противоречат статусу ревизии,
на которую событие ссылается. Всё остальное по S3 доказано (см. таблицу). После правки
S4 может стартовать немедленно - повторная проверка сводится к одному тесту и одной пробе.

- Кандидат: ветка `pv/history`, HEAD `33b62f6a` (`33b62f6a127b85fccf8cd65540662a2d863e1c9b`),
  база `44e1e589`; дерево чистое (`git status` пуст), все пробы выполнены на этом дереве.
- Контракт: `arch/versioning-ux-contract.md` §3, §5, §2.4 п.9, §6.3.
  ТЗ владельца: `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md` §2.2 п.3-5, §3.5, §3.7.
  Закрываемые замечания: мои N1/N2 из `reports/pv-s2-review.md`.
- Дифф: `services/prompt_release_policy.py` (+845), `services/prompt_registry.py` (+23/-8),
  `services/prompt_factory.py` (+21/-11), `web/api/routes.py` (+22/-3), `web/api/speech.py` (+199/-16),
  новый `tests/test_prompt_history_pagination.py` (+626), отчёт и мутационный скрипт лейна.
  Файлов `web/*` (HTML/JS/CSS) в диффе нет.

## Три опоры приёмки

- **Implementation.** Прочитаны: страничный слой обоих сторов (`MemoryPromptJournal` и
  `PgPromptJournal`: `list_history_page`, `list_revisions_page`, `list_activations_page`,
  `find_revision_by_sha`), `_history_page_of` (k-way merge + keyset), `encode/decode_history_cursor`,
  `_norm_ts`, `history_status`/`history_reason_text`/`history_source`, переписанный `list_versions`,
  `_status_of_row` для двух видов записей, RBAC-резолв `/revisions/{id}/source` →
  `_prompt_require_revision_view` → `_prompt_require_view` (`web/api/routes.py:3542-3563`),
  `_prompt_history_view`/`_legacy_history_rows`/откат по `sha256_12` (`web/api/speech.py`),
  изменённый порядок ветвей `activation_plan` и снимок в pinned-ветке
  (`prompt_registry.py:775-806`, `prompt_release_policy.py:2246-2286`).
- **Test validity.** Прочитаны тела 18 тестов `tests/test_prompt_history_pagination.py`: проверяются
  реальные результаты (число записей, уникальность, независимо вычисленный порядок, непрерывные
  `order`, отсутствие тел поиском по `json.dumps`, статусы с `reason_text` и `actionable`, отказ
  сервера на retired/несовместимой, N1/N2 по состоянию стора, Speech 50/13/55). Тавтологий
  (`assert True`), моков вместо предмета проверки и пустых тел нет; стор - тот же контракт, что в
  проде (Memory-двойник), HTTP-слой - реальный `create_app` + `TestClient`. Чего тесты не
  покрывают: статус/`actionable`/`reason_text` у строк-событий (B1) и реальный PostgreSQL-рантайм.
- **Independent challenge.** Свои сценарии, не из набора Builder: обход 1500 записей через
  эндпоинт с независимым оракулом порядка (0.52-0.61 с, 15 страниц, ~35-41 мс/страница);
  вставка 5 более новых записей между чтениями страниц; матрица RBAC по телу (свой ЛС, чужой ЛС,
  групповой чат, global, неизвестная ревизия, diff через чужой чат); `PgPromptJournal` на фейковом
  коннекте, который возвращает колонку `body` (тело не всплывает, `chars` считается); откат Speech
  на версии, которой нет в bounded-журнале (в т.ч. retired → 422, чужой чат → 404);
  строка-событие, ссылающаяся на retired-ревизию (B1).
## Поклаузно

| # | Требование (ТЗ/контракт/review) | Итог | Наблюдаемые факты |
|---|---|---|---|
| 1 | **N1**: pinned scope + нет значения + нет маркера импорта - первый размеченный релиз не пишет заводской текст, указатель baseline цел, второй прогон - истинный no-op | **PROVEN** | `activate_pinned` / `factory_superseded_pinned`; `cache.get(PG_KEY)` пуст, `store.read_global` пуст; ревизия `fac:sha12(narrator-b)` в истории; `read_applied.factory_revision_applied=fac:4bd2b4354665`; baseline остаётся `rev:129fa0859623`; повторный `apply_release` - dAct=0, dRev=0, план `no_op/restart_same_revision`. Снимок не потерян: при ручном тексте вне журнала pinned-ветка пишет `legacy`-ревизию и `legacy_import/legacy_snapshot`, значение остаётся прежним. |
| 1а | Нормальный (не pinned) cutover не сломан | **PROVEN** | Первый прогон: `legacy_cutover`, снимок `legacy` прежнего текста, `legacy_import/legacy_snapshot` + `deploy_activate/applied/factory_activate`, значение = заводской текст; повтор с той же меткой - `no_op` (0 строк); новая метка - `activate/applied/factory_activate`, значение заменено. **Намеренное изменение поведения:** рестарт с той же меткой больше не перезапускает cutover. Достижимо только при `applied == code_revision` и отсутствии маркера импорта; в этом состоянии значение scope уже записано журналом (или это восстановленный вручную текст, который теперь сохраняется, а не перетирается). Соответствует §2.4 п.1 / §7.1 и замечанию N1; потери данных нет. |
| 2 | **N2**: `copy-to-global` отдаёт `reason` СОХРАНЁННОЙ ревизии | **PROVEN** | Копия из чата A: `created=true`, `copied_from_chat:rev:6eb0e40440b0`. Копия тех же байтов из чата B: `created=false`, ответ `copied_from_chat:rev:6eb0e40440b0` равен `store.get_revision(...).reason`; исходные чатовые ревизии не изменены. |
| 3 | **Нет потолка истории**: 1000+ ревизий, страницы, уникальность, без пропусков, детерминированный порядок, размер страницы, стабильный курсор, замер времени | **PROVEN** | 1200 ревизий + 300 событий через `GET /api/prompts/{key}/versions?page_size=100`: **15 страниц, 1500 записей, 0.52-0.61 с всего, ~35-41 мс/страница**; размер страницы не более 100; 1500 уникальных ключей; `order` = 1..1500 без пропусков; порядок совпал с независимым оракулом (desc по `(created_at, вторичный ключ)`), первое расхождение - нет; 1200 уникальных `revision_id`, 300 уникальных событий. Курсор: страница 1 = снимок `[0:10]`; после вставки 5 более новых записей страница 2 = `[10:20]` исходного снимка, без пересечения, `order` продолжается с 11. `page_size=0` даёт 50, `page_size=1000` даёт 200 записей и `has_more=true`. |
| 4 | **Список без тел**: ни в SQL, ни в ответе; тело - только авторизованным запросом | **PROVEN** | SQL: `_PAGE_REVISIONS_DESC_SQL` содержит ровно одно упоминание `body` - `length(body) AS char_count`; в `_PAGE_ACTIVATIONS_DESC_SQL` колонки `body` нет; OFFSET отсутствует; keyset строгий (`<`). `PgPromptJournal.list_history_page` на фейковом коннекте, который ВОЗВРАЩАЕТ колонку `body`, отдаёт строки без тела (сентинел в дампе отсутствует, `chars=54`). Рантайм: ни один из 15 ответов обхода не содержит сентинела тел. |
| 5 | **RBAC тела**: ревизия - блок - (scope, chat); чужой чат - 403 | **PROVEN** | Свой ЛС владельца - 200 с дословным телом; чужой ЛС - **403** (в т.ч. глобальному админу: это действующее правило F-14 «ДМ только владельцу», не регрессия S3); групповой чат - админ 200, обычный пользователь 403; global - админ 200, обычный 403; неизвестная ревизия - 404; diff между своей и чужой чатовой ревизией - 403. `_prompt_require_revision_view` резолвит `row.scope/chat_id` и вызывает `_prompt_require_view`. |
| 6 | **Статусы**: active/baseline/inactive/incompatible/retired, честный `reason_text`, читаемость и diff, запрет действия | **NOT PROVEN (B1)** | Для строк-ревизий всё верно: `active`, `baseline`, `retired` (`actionable=false`, «Версия снята с регистрации...»), `incompatible` (`schema-from-the-future`, `actionable=false`), тело retired читается, diff работает с `actionable=false`, активация и назначение базовой отклоняются сервером (`revision_retired`, `schema_incompatible`, `assign_baseline - applied=false`). **Но у строк-событий** статус считается только по самому событию: событие, ссылающееся на retired-ревизию, показывает `status=active`, `actionable=true`, `reason_text` пустой, тогда как строка той же ревизии - `retired/actionable=false` с причиной. Подробно - B1. |
| 7 | **Изоляция чатов истории** | **PROVEN** | Store: чат A видит 3 свои записи, чат B - 2 свои, пересечения нет, в global чатовых записей нет. HTTP: A - 4, B - 3, global - 0 записей. |
| 8 | **Speech-история из журнала**, старый bound 12 больше не лимит, fallback только при недоступном журнале | **PROVEN** | `_prompt_history_view`: `source=journal`, 50 строк на первой странице (не 12), `has_more=true`, `page_size=13` даёт 13, `page_size=200` даёт все 55; прежние ключи строки (`revision/kind/scope/sha256_12/chars/updated_at/actor/reason`) на месте. `default_journal - None` даёт `available=false` (честная граница), `_legacy_history_rows` помечает `legacy_bounded`. Старые доступные записи не теряются: `apply_release` переносит ВСЕ записи `character.prompt_history` в журнал (`_import_provenance_history`, идемпотентно по `revision_id`). Откат: версия, которой нет в bounded-журнале, применяется из журнала (200, значение записано, событие в журнале); retired - 422 с причиной; несовместимая - 422; неизвестный sha - 404; чатовая версия применяется в своём чате; версия чужого чата недостижима (404). |
| 9 | **Тексты промптов не менялись**, нет DDL/второго журнала/LLM/бюджетов, ничего не удалено | **PROVEN** | `git diff 44e1e589..33b62f6a`: удалённых файлов нет; `CREATE/ALTER/DROP TABLE|INDEX` - 0 строк; `prompt_versions_v2`, `max_tokens`, `token_budget`, `llm_client`, `budget` - 0 вхождений в диффе; `JOURNAL_DDL` не изменён; `tests/test_evol018_prompt_audit.py` не в диффе и зелёный; в `prompt_registry.py` единственное содержательное изменение - порядок ветвей (тела литералов идентичны). |
| 10 | **Индекса под ключ страниц нет - приемлемо ли для заявленного масштаба** | **PROVEN (с оговоркой)** | Существующих индексов достаточно на заявленном масштабе: `idx_prompt_revisions_block (block_id, scope, created_at)` и `idx_prompt_activations_latest (block_id, scope, activation_id DESC)` покрывают фильтр `block_id`; запрос страницы читает `page_size+1` строк на поток. Замер на 1500 записях: 15 страниц за 0.52-0.61 с. Стоимость постраничного чтения строго меньше прежней (раньше на каждый запрос читались ВСЕ ревизии без LIMIT). Оговорка отчёта лейна верна: при десятках тысяч активаций одного блока нужен аддитивный индекс `(block_id, created_at DESC)` - отдельное решение, DDL в S3 запрещён. |
## Мутации (проверялись независимо; файлы восстановлены побайтово)

Набор Builder (`evidence/pvr-s3/mutations.py`), прогон на этом кандидате:

| Мутация | Результат |
|---|---|
| N1: pinned-проверка снова ПОСЛЕ cutover | **CAUGHT** (1 failed) |
| N2: отдавать запрошенный `reason` вместо сохранённого | **CAUGHT** (1 failed) |
| Потолок истории: `page_size` урезается до 50 | **CAUGHT** (1 failed) |
| Тело ревизии попадает в список (стор - поле - ответ) | **CAUGHT** (1 failed) |
| Статус игнорирует `retired` | **CAUGHT** (1 failed) |
| Курсор включительный (`<=`) | **CAUGHT** (1 failed) |
| Чат-фильтр отключён (утечка истории чата) | **CAUGHT** (1 failed) |
| Speech-история снова ограничена 12 | **CAUGHT** (1 failed) |

`restored byte-identical: True`, контрольный прогон после восстановления - `18 passed`.

Мои дополнительные мутации (не из набора Builder; тот же приём, sha256 файла до и после совпал):

| Мутация | Результат |
|---|---|
| `has_more=False` в объединённой странице (обход обрывается) | **CAUGHT** (1 failed) |
| `history_status` игнорирует owner baseline | **CAUGHT** (1 failed) |
| pinned-ветка не снимает legacy-снимок (половина N1) | **CAUGHT** (1 failed) |

## Находки

**B1 (блокирует, точечная правка).** Строка-событие в `entries[]` получает статус и признак
действия только по самому событию, а не по ревизии, на которую ссылается.
`_activation_history_row` (`services/prompt_release_policy.py:1537-1547`) не заполняет
`retired`/`schema_compat`, а `_entry` (`:3685-3740`) и `_status_of_row` (`:650-656`) на их основе
считают `status`/`actionable`/`reason_text`.
Воспроизведение: стор с `manual_edit` и `baseline_assign`, ссылающимися на ревизию R; затем
`R.retired=True`. Наблюдение: две строки-события `status=active, actionable=true,
reason_text=''`; строка самой ревизии - `retired, actionable=false` с причиной.
Требование: ТЗ §2.2 п.3 и п.8, контракт §2.4 п.9 и §6.3 - статус честный, а действие не
показывается там, где оно запрещено. Влияние: S4 строит единственный список на `entries[]` и
берёт оттуда `status`/`actionable`/`reason_text` для подписей и кнопок (так прямо написано в
отчёте лейна §8) - получит кнопку «Применить» для снятой с регистрации версии и противоречивый
статус в одном списке. Запись при этом отклоняется сервером (`revision_retired`), то есть риск
не в данных, а в честности состояния и UX.
Минимальная правка: при сборке строк-событий резолвить связанную ревизию (тот же стор или джойн
по `revision_id`) и передавать её `retired`/`schema_compat` в `_status_of_row`; плюс один
CONTRACT-тест «событие, ссылающееся на retired/несовместимую ревизию».
Мелкая перепроверка: этот тест и повтор моей пробы сценария B1. Больше ничего перепроверять не нужно.

**N-1 (не блокирует, но важно для порядка работ).** Ключ `revisions` в ответе теперь страница
(по умолчанию 50, внутри - исторический порядок), раньше отдавались ВСЕ ревизии. Существующая
панель «История версий» читает `data.revisions` и кнопки «показать дальше» не имеет: до S4 она
покажет 50 самых новых ревизий. Данные не потеряны (`revisions_page.next_cursor`, `entries[]`),
но S3 нельзя выпускать отдельным релизом, пока в каком-либо блоке больше 50 ревизий.
Требование к S4: листание по `entries[]` + `page.next_cursor` (и/или `revisions_page.next_cursor`).

**N-2.** Отчёт лейна (§2, §5) говорит «3 запроса на страницу» - фактически 4 обращения к стору
(2 в `list_history_page` + `list_revisions_page` + `list_activations_page`) плюс `ensure_journal`;
на замер это не влияет, но цифру в отчёте стоит поправить.

**N-3.** Для событий источник считается по `kind`: `baseline_assign` даёт `restored`
(«восстановлена»). Для назначения базовой слово неверно; S4 стоит подписывать такие события
отдельно, не вводя новый токен источника (токены - часть контракта §2.2 п.3).

**N-4.** `read_baseline_event` теперь читается внутри общего `try`, и его сбой поднимает 503
(`JournalUnavailable`), тогда как раньше это был только warning. Поведение строже и fail-closed,
на той же таблице журнала; принимается.

## Прогоны

| Набор | Итог |
|---|---|
| `tests/test_prompt_history_pagination.py` (новый) | **18 passed** |
| baseline, migrations, enforcement, evol016 activation, evol016 journal v39, evol017 history ui, evol018 audit, asap history integrity | **150 passed, 2 skipped** |
| webapp api, soul1 w6 speech ui, soul1 factory defaults, soul1 core registry, meme pipeline, evol014 meme, speech chat scope, initiative speech layers, meme joke speech, meme init diagnostics, p0 prompts core, prompts round1024, p0 meme publication, p0 meme image only | **396 passed** |

## Гейт карты требований (для PM)

`requirements_gate.py check --map plans/features/epic-prompt-versioning-ux-01/requirements-map.json
--stage review --slice PVR-S3-HISTORY --candidate 33b62f6a --repo .` - **FAIL**:
`candidate mismatch` (в карте `candidate_commit` пуст) и 5 PENDING-строк слайса
(`PVR-INV-03`, `PVR-HIST-01`, `PVR-HIST-02`, `PVR-HIST-03`, `PVR-HISTUI-04`).
Это дефект учёта, не поведения: карта заполнена (63 записи), но доказательства не привязаны к SHA.
После правки B1 PM обязан проставить `candidate_commit`, статусы и ссылки на артефакты - без
этого parent DONE и релиз эпика закрывать нельзя. На старт S4 это не влияет.

## Что не проверено

- **Реальный PostgreSQL.** В окружении нет живой БД (тесты и прод-БД на VPS). PG-путь проверен
  статически (текст SQL: `length(body) AS char_count`, отсутствие `body`, отсутствие OFFSET,
  строгий keyset) и прогоном `PgPromptJournal` на фейковом коннекте; серверное поведение
  индексов и сортировки на реальных данных не наблюдалось. Это не блокирует S3 (SQL детерминирован
  и не меняет схему), но при первом релизе стоит посмотреть план запроса и время страницы в логах.
- **Визуальный слой.** В диффе нет ни одного файла `web/*`; привязки существующей панели
  (`web/index.html:4229-4345`, `web/app.js` `promptHistory`) сверены по полям - все используемые
  ключи в новом ответе есть, новые ключи аддитивны. Отрендеренная проверка относится к PVR-S4
  (единственный UI-компонент), поэтому Playwright и Browser Use на этом срезе не применялись
  осознанно, а не пропущены.

## Слияние и старт S4

- Кандидат пригоден к слиянию после правки **B1** (один файл, один тест). N1 и N2 закрыты.
- S4 может начинать сразу после B1: `entries[]` + `page.next_cursor`/`has_more`, `body_available`
  и существующий `/source`, `page_size` для ширины панели, Speech - прежние ключи + `history_source`.
  Контракт статусов и действий для S4 фиксируется только после B1.
- Не выпускать S3 отдельным релизом без S4 при наличии блоков с более чем 50 ревизиями (N-1).﻿## Re-review 2 - только B1/N-3

**Вердикт: Approved.** B1 закрыт: строка-событие наследует состояние СВОЕЙ ревизии.
Кандидат пригоден к слиянию, PVR-S4 может стартовать.

- Кандидат: ветка `pv/history`, HEAD `254f5242`, база `44e1e589`; дифф к предыдущей
  проверке `33b62f6a..254f5242` - 4 файла (`prompt_release_policy.py` +76/-27, новый
  тест +86, отчёт и мутационный скрипт лейна). Дерево после проверки чистое
  (`services/prompt_release_policy.py` восстановлен `git checkout`, совпадает с HEAD).
- Исправлено: `_PAGE_ACTIVATIONS_DESC_SQL` джойнит `prompt_revisions` по ПЕРВИЧНОМУ
  КЛЮЧУ `revision_id` и отдаёт `COALESCE(r.retired,false)` и
  `COALESCE(r.schema_compat,"")`; `MemoryPromptJournal._history_rows` берёт те же поля
  из `self.revisions`; `_activation_history_row` прокидывает их в `HistoryRow`.
  Оба места сборки строк-событий (1125 и 1573) закрыты, других нет.

### Моя проба B1 (не набор Builder): снятие через ПРОДОВЫЙ путь

Сценарий: `apply_release`, `write_versioned_value` (R1), `assign_baseline(R1)`,
`write_versioned_value` (R2, schema_compat=schema-from-the-future), затем
`store.mark_retired([BLOCK])` - то же, что `_MARK_RETIRED_SQL` в проде; 4 ревизии
помечены снятыми.

| Строка | До снятия | После снятия |
|---|---|---|
| ревизия R1 (active+baseline) | `active` / `actionable=true` | `retired` / `false` / «снята с регистрации» |
| событие `manual_edit` на R1 | `baseline` / `true` | `retired` / `false` / та же причина, что у ревизии |
| событие `baseline_assign` на R1 | `baseline` / `true`, `source=restored`, «назначена базовая» | `retired` / `false`, подпись сохранена |
| ревизия R2 (несовместимая) | `incompatible` / `false` | `retired` / `false` |
| событие `manual_edit` на R2 | `incompatible` / `false` / «Несовместима...» | `retired` / `false` |
| `deploy_activate`, `legacy_import` | `inactive` / `true`, `from_release`/`imported` | `retired` / `false`, токены не изменились |

`status`/`actionable` каждой строки-события совпали со строкой её ревизии в том же
ответе, и в `entries[]`, и в `activations[]` (попарная сверка до и после снятия).
У `retired`/`incompatible` признак действия всегда `false`.

### Стоимость и форма ответа

- Обращений к стору на запрос: `list_history_page`, `list_revisions_page` и
  `list_activations_page` после `ensure_journal` - **4**, как и до правки; замер до и
  после снятия одинаковый (`ensure_journal, list_history_page, list_revisions_page,
  list_activations_page, read_applied, read_baseline_event, read_applied`). Джойн живёт
  внутри существующего страничного запроса; запроса на строку нет. Джойн 1:1
  (`revision_id TEXT PRIMARY KEY`), дублей и сдвига страниц не даёт.
- Тел в ответе нет (сентинелы текстов отсутствуют в `json.dumps`); в SQL активаций
  колонки `body` нет, в SQL ревизий только `length(body) AS char_count`; `OFFSET` нет,
  keyset строгий (`<`).
- Независимый обход 90 записей (60 ревизий + 30 событий, `page_size=10`): 9 страниц,
  90 уникальных, `order` = 1..90 без пропусков, порядок совпал с независимым оракулом
  desc по паре (created_at, вторичный ключ).

### PG-путь

`PgPromptJournal` на фейковом коннекте, отдающем `retired`/`schema_compat` и лишнюю
колонку `body`: строки-события приходят с `retired=True` и `schema_compat`, тела нет.
SQL по тексту: `LEFT JOIN prompt_revisions r ON r.revision_id = a.revision_id`, колонки
активаций квалифицированы `a.`, неоднозначных имён нет, параметры `$3/$4/$5` не
сдвинулись. Живого PostgreSQL в окружении нет, серверная семантика джойна не
исполнялась; DDL и схема не менялись.

### N-3 и подписи

`history_source_label(token, *, kind="")`: `baseline_assign` -> «назначена базовая»,
`baseline_clear` -> «назначение базовой снято»; `baseline_restore`/`factory_restore`
остаются «восстановлена» (текст там действительно восстанавливается);
`manual_edit`/`manual_rollback` -> «ручная», `deploy_activate` -> «из релиза»,
`legacy_import` -> «импортирована». Токены `source` не расширялись, статусы те же пять.
Сигнатура keyword-only, других вызывающих в репозитории нет; `get_revision_source`
вызывает без `kind`, для ревизии подпись по источнику как раньше. Speech читает
`entries[]`, поэтому B1 и N-3 приезжают туда автоматически.

### Мутации (мои; файл восстановлен `git checkout`, `git status` чист)

| Мутация | Результат |
|---|---|
| B1-Memory: `linked = None` | **CAUGHT** - `test_event_rows_agree_with_their_revision_state` падает |
| B1-PG: `_activation_history_row` снова пишет retired=False, schema_compat пустой | **NOT CAUGHT** - тест зелёный |

Второе - граница покрытия, не дефект поведения: тест работает на Memory-двойнике, а
PG-потребитель проверен фейковым коннектом и текстом SQL. Тест на джойн требует живой
БД. Некритично.

### Прогоны

| Набор | Итог |
|---|---|
| `test_prompt_history_pagination.py` | **19 passed** (18 + новый CONTRACT) |
| `test_prompt_history_pagination, test_prompt_baseline, test_prompt_versioning_enforcement` | **73 passed** |
| `test_prompt_migrations, evol016 activation, evol016 journal_v39, evol017 history_ui, evol018 audit, asap history integrity` | **96 passed, 2 skipped** |
| `test_webapp_api, soul1_w6_speech_ui, soul1_factory_defaults, soul1_core_registry_api, meme_pipeline_api, p0_prompts_core, prompts_round1024` | **252 passed** |

N1/N2, потолок 1000+, изоляция чатов, Speech из журнала - те же тесты, что в первом
круге, все зелёные. Полный дифф `44e1e589..254f5242`: удалённых файлов нет, вхождений
`CREATE/ALTER/DROP TABLE|INDEX`, `max_tokens`, `token_budget`, `llm_client` - 0;
`prompt_registry.py` новым коммитом не тронут (тексты промптов не менялись).

### Некритичные замечания

- **PG-джойн без durable-теста** (см. мутацию выше). При первом релизе посмотреть
  план/время страницы в логах прода.
- **Событие без ревизии** (`baseline_clear`, пустой `revision_id`): status=inactive,
  actionable=true, body_available=false; поведение не изменилось. Требование к S4:
  «Применить» показывать только при непустом `revision_id`/`body_available`.
- **N-1 в силе:** `revisions` - страница по 50; S3 не выпускать отдельным релизом без S4
  при блоках с более чем 50 ревизиями.
- **Учёт у PM:** `candidate_commit` в карте требований пуст, строки слайса PENDING. На
  слияние и старт S4 не влияет; parent DONE без привязки к `254f5242` закрывать нельзя.

