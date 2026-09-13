# Step 5 — STRICT REVIEW раунда 10.15 «Багфиксы графа памяти, воркера Сна и ностальгии»

> **Ревьюер:** @Reviewer (Senior Principal / Validator / Security). **Дата:** 14.09.2026.
> **Baseline:** HEAD `798e044`. **Объём:** все незакоммиченные изменения (`git diff` 45 файлов + 32 untracked) по 9 фичам (F1–F9).
> **Метод:** построчный аудит диффа/untracked + чтение `spec.md`/`tasks.md`/ADR-1015-1/2/3 + прогон Validator + сверка инвариантов + воспроизведение дефектов.

## ВЕРДИКТ (итерация 1): **Rejected** *(снят по итогам повторного ревью — см. §7)*

Реализация сильная и по объёму, и по тестам: все builder-задачи закрыты, `pytest` 5752/0, JS-гейты и `git diff --check` чистые, R17-дисциплина новых логов соблюдена, каталог Δ=0, порядок роутеров не тронут, PREV-слепки байт-идентичны. **Но код отклоняется**: воспроизведён логический дефект F5 — при выключенном сне (`memory.dream_enabled=false` / `flags.deep_sleep_enabled=false`) внутри часового окна API отдаёт `active=true`, и фронт показывает светящийся «🌙 Сон до …»/«🌌 Глубокий сон до …» вместо нейтрального «☀️ Сон выключен»/«🌅 Глубокий сон выключен». Состояние `enabled=false`, объявленное в F5-Q2 отдельным нейтральным, недостижимо в окне. Дополнительно у F6 (главный регресс-риск) нет границы триггера: «Бот, загуглика»/«Бот, транскриптер» молча консьюмятся функциональным путём вместо обычного ответа, а безусловный yield в `direct_chat` при выключенном модуле приводит к потере сообщения вообще без ответа.

---

## 1. Число задач: подтверждено/не подтверждено

Всего в 9 `tasks.md`: **76** задач. Закрыто `[x]`: **58**. Открыто `[ ]`: **18**.

**Подтверждение:** все 58 `@Builder`-задачи закрыты; **все 18 открытых — исключительно гейты `@Architect` и `@PM/@Reviewer` (по 2 на фичу)**. Ни одной незакрытой builder-задачи нет.

| Фича | Builder `[x]` | Открытые гейты `[ ]` |
|---|---|---|
| F1 graph-sampling-centrality | T-1550…T-1556 | **T-1549 (@Architect)**, T-1557 (@PM/@Reviewer) |
| F2 graph-frontend-physics-search | T-1559…T-1564 | **T-1558 (@Architect)**, T-1565 (@PM/@Reviewer) |
| F3 sleep-unblock-diagnostics | T-1567…T-1573 | **T-1566 (@Architect)**, T-1574 (@PM/@Reviewer) |
| F4 nostalgia-prompt-revamp | T-1576…T-1582 | **T-1575 (@Architect)**, T-1583 (@PM/@Reviewer) |
| F5 status-graph-ui-relocation | T-1585…T-1591 | **T-1584 (@Architect)**, T-1592 (@PM/@Reviewer) |
| F6 command-prefix-persona-routing | T-1593…T-1600 | T-1601 (@PM/@Reviewer), T-1602 (@PM/@DevOps) |
| F7 guide-rewrite-persona | T-1604…T-1608 | **T-1603 (@Architect/@Copywriter)**, T-1609 (@PM/@Reviewer) |
| F8 hybrid-tool-calling | T-1611…T-1617 | **T-1610 (@Architect)**, T-1618 (@PM/@Reviewer) |
| F9 recent-history-tool | T-1620…T-1623 | **T-1619 (@Architect)**, T-1624 (@PM/@Reviewer) |

> F6 — единственная фича, где architect-гейт T-1593 уже `[x]`. Остальные 8 architect-гейтов формально открыты, хотя спеки фактически написаны (проверить на этапе @PM).

---

## 2. Таблица по фичам (соответствие контракту)

| Фича | Вердикт | Подтверждено (доказательства) | Расхождения |
|---|---|---|---|
| **F1** graph-sampling-centrality | ✅ по коду | CTE-выборка `services/database.py:3637-3665`; оба конца рёбер `:3677-3690` (S10.13-14); сироты `:3698-3702`; `truncated` `:3704-3706`; `seed_nodes=50` `:3612`; API-константа/прокидка `web/api/memory_agi.py:62,558`; `degree` сохранён `:3669-3672`. EXPLAIN подтверждает `SEARCH edges USING INDEX idx_edges_chat_weight` без коррелированного `COUNT(*)` | нет |
| **F2** graph-frontend-physics-search | ✅ | `barnesHut` со всеми константами `web/app.js:5276-5290`; `reducedMotion → physics:false`; поиск/сброс `:5301-5355`; разметка+CSS `web/index.html:737-746,2987-3002`; race lazy-load (повтор рендера) `app.js:5303-5307`; JS-юниты `tests/js/routing_test.js:1612-1734` | нет |
| **F3** sleep-unblock-diagnostics | ✅ | Константы 3/2/8 `services/dream_worker.py:135-142`; детект один раз на тик `:457-461`; fail-safe `:256-269`; применение 2/8 `:525-529`; логи skipped(WARNING)/passed(INFO) ровно формата `:544-561`; старый `[dream] no qualifying` удалён; видимость в `ERROR+WARNING` тест `tests/test_sleep_fallback_round1015.py:261-278` | нет |
| **F4** nostalgia-prompt-revamp | ✅ | Окно 10 `config/settings.py:1174`; fallback `nostalgia_worker.py:546-550`; PREV байт-в-байт (проверено против `798e044`, `True`); канон ровно 1 `{max_words}`, есть `UNCHANGED`, нет `—`; секции «Лор чата»/«Локальные мемы» `nostalgia_prompts.py:141-172`; капы 600/10/120 `:38-40`; fail-open `nostalgia_worker.py:604-625`; `PROMPT_MIGRATIONS` не тронут (в файле отсутствует — подтверждено) | нет |
| **F5** status-graph-ui-relocation | ⚠️ с дефектом | API аддитивен `web/api/memory_agi.py:522-533`; `_in_hour_window` с wrap `:102-114`; релокация без дубля `index.html:1803-1817`; «пробуждение ~» удалён; `.intel-header`+media-столбик `index.html:700-707,2928-2934`; `loadCognitionStats` удалён `app.js` | **H1** `enabled=false` не гасит активность в окне |
| **F6** command-prefix-persona-routing | ⚠️ с дефектами | Флага `command_prefix_enabled` НЕТ (grep чист); префикс из `get_cached_global_name` `services/command_prefix.py:34-48`; реестр ровно 17 + bare `services/command_registry.py:19-32`; ботворды off при имени `handlers/direct_chat.py:151-162`; yield `:440-442`; download-yield `handlers/video_download.py:224-229`; порядок роутеров `bot.py:658-675,745` не изменён | **M1** нет границы триггера; **M2** потеря сообщения при выключенном модуле |
| **F7** guide-rewrite-persona | ✅ | Канон/байт-тест `services/info_service.py:20-134` + `info_text.md` (byte equal `True`); миграция по слепку `services/config_cache.py:235-267`; ручная правка не затирается + WARNING; идемпотентность (no-op) `:254-256`; 9×h2/h4-акценты; реестр F6 в тексте | нет |
| **F8** hybrid-tool-calling | ✅ | 7 тулов `services/tool_schemas.py:98-185`; `ToolDeps`/`ToolContext` аддитивно `tool_router.py:158-197`; `_download_media` — отправка MP4 + фиктивный success, error при сбое/снят гейт `:540-580`; `media_send.py` общий helper; DI `bot.py:428-432`; лимиты tool-loop не тронуты | нет |
| **F9** recent-history-tool | ✅ | `TOOL_GET_RECENT_HISTORY` 1..150/query `tool_schemas.py:157-180`; depth-путь `tool_router.py:644-652`; query-путь (FTS+окно+ASC) `:654-668`; формат `Имя: текст` `:670-684`; клампы `:121-132`; chat-скоуп; R17 только count/out_chars `:637-641`; fail-safe `:624-633` | нет |

---

## 3. Проблемы по severity

### [High] H1. F5: `enabled=false` не отключает активность бейджа внутри часового окна
- **Файлы/строки:** `web/api/memory_agi.py:479` (`dream_active = in_window or dream_running`), `:495` (`deep_active = deep_in or deep_running`); `web/app.js:1215` (`if (d.active)`), `:1222` (`if (d.enabled === false)`), `web/app.js:1233,1240` (то же для глубокого сна).
- **Проблема:** `active` вычисляется без оглядки на `enabled`. При выключенном сне (`memory.dream_enabled=false` / `flags.deep_sleep_enabled=false`) в интервале `[start,end)` API возвращает `active=true`, а `active_until != null`. Бейджи проверяют `d.active` РАНЬШЕ `d.enabled === false`, поэтому состояние «Сон выключен» недостижимо в окне.
- **Воспроизведение (локально):** при `now=2026-09-14 05:00 UTC`, окно 4–6, `memory.dream_enabled=false`:
  `enabled: False active: True active_until: 1789365600`; `deep enabled: False active: True`.
  Это ровно те часы (по умолчанию 4–6 локального времени), когда админ, выключивший сон, будет видеть ложное свечение.
- **Почему важно:** это прямое нарушение F5-Q2 («`enabled=false` и `limit_exhausted` — отдельные нейтральные состояния») и ТЗ §5 (вне/неактивная фаза — не светится). UI сообщает пользователю, что спящий воркер работает, хотя рубильник выключен.
- **Требуемый фикс:** занулять активность при выключенном воркере — на бэке `dream_active = enabled and in_window or dream_running` и `deep_active = deep_enabled and deep_in or deep_running` (с сохранением `active_until=None` вне окна), ЛИБО во фронте вынести проверку `enabled === false` выше `active`. Добавить регресс-тест: `dream_enabled=false` + время в окне → `active=false`, `active_until=null`; аналогично для deep.

### [Medium] M1. F6: у триггеров нет границы слова → ложные срабатывания («Бот, загуглика», «Бот, транскриптер»)
- **Файлы/строки:** `services/command_registry.py:36-50` (`_TRIGGER_RE = "|".join(...)`, `.match()` без `(?![0-9a-zа-яё_])`; `matches_group` через `startswith`), `handlers/search.py:109`, `handlers/youtube.py:171-176` (`_has_trigger` — substring), `handlers/web.py:67-70`.
- **Проблема:** проверена граница только у ПРЕФИКСА (`command_prefix.py:55`, `(?![0-9a-zа-яё_])`), но не у триггера. Воспроизведено: `_parse_search_query("Бот, загуглика") == ""` (уходит в консьюм фразой «уточни запрос»), `is_functional_command("Бот, загуглика") is True`, `youtube._triggered_body("Бот, транскриптер") is not None` (уходит в консьюм «нет цели»). До раунда `_SEARCH_PREFIX_RE` использовал `\b`, и «загуглика» была UNHANDLED.
- **Почему важно:** цель F6 — убрать ложные срабатывания обычного текста; новый матчер их, наоборот, добавляет в префиксном пути, и сообщения пользователя молча «съедаются» нейтральной отпиской вместо обычного ответа. Тест-план (§10 спеки) этот класс кейсов не покрывает.
- **Требуемый фикс:** в `command_registry.matches`/`matches_group` добавить проверку правой границы после триггера (`(?![0-9a-zа-яё_])`), а для триггеров, заканчивающихся на `?` (`живой?`) — корректно обработать знак; тесты: «Бот, загуглика», «Бот, транскриптер», «Бот, найдикто» → UNHANDLED/обычный путь.

### [Medium] M2. F6: безусловный yield в `direct_chat` теряет сообщение при выключенном модуле
- **Файлы/строки:** `handlers/direct_chat.py:440-442` (yield UNHANDLED при `is_functional_command`); выключатели: `handlers/web.py:124` (`flags.webpage_enabled`), `handlers/checkup.py:97`, `handlers/video_download.py:222` (нет downloader) и т.п.
- **Проблема:** если функциональный воркер выключен флагом/отсутствием DI, сообщение «Бот, выжимка …»/«Бот, чекни здоровье»/«Бот, скачай …» не перехватывается воркером (UNHANDLED) и в `direct_chat` тоже безусловно yield-ится — в итоге бот молчит вообще (ни команды, ни LLM-ответа).
- **Почему важно:** молчаливая потеря пользовательского сообщения — регресс относительно прежнего поведения (ботворд-ветка direct_chat дала бы обычный ответ). Особенно заметно при частично выключенных модулях.
- **Требуемый фикс:** yield только если соответствующий модуль реально активен (например, проверять `flags.webpage_enabled`/`flags.checkup_enabled`/наличие downloader перед yield), либо передавать состояние доступности воркеров; иначе — обычный путь LLM. Добавить тест «модуль выключен → сообщение не теряется».

### [Low] L1. Мёртвый код: `command_registry.is_bare_command`
- **Файл/строка:** `services/command_registry.py:53-55`. Функция не вызывается ни в одном продовом пути (grep: только определение и `BARE_COMMANDS` в тесте). Удалить либо подключить (например, в `direct_chat._parse_memory_command`), чтобы не накапливать техдолг.

### [Low] L2. Устаревшие статусы `spec.md`
- **Файлы:** `graph-sampling-centrality` / `graph-frontend-physics-search` / `sleep-unblock-diagnostics` / `status-graph-ui-relocation` / `hybrid-tool-calling` / `recent-history-tool` — шапки «🟣 SPEC_READY … Реализация не начата» при фактически реализованном коде (`tasks.md` — IMPLEMENTED). Приведение к единому статусу обязательно перед @PM-гейтом.

### [Low] L3. Противоречивый docstring + дублирование send-логики
- **Файл/строка:** `services/tool_router.py:23-24` («seam get_recent_history (полная реализация — F9)») при полностью реализованном методе `:602-684` — ввести в заблуждение. Кроме того, `services/media_send.py` не переиспользован в `handlers/video_download._send_file` (две независимые реализации отправки) — риск расхождения поведения.

### [Low] L4. Утечка aiosqlite-соединений в тестах
- **Наблюдение:** `pytest` завершается предупреждением `WARNING: closed 12 leaked aiosqlite connection(s)`. На прод не влияет, но ослабляет детерминизм и шумит; закрыть соединения в фикстурах новых SQLite-тестов (`test_webapp_round1015_graph.py`, `test_recent_history_tool_round1015.py`).

### [Info / вне объёма] Пароль и IP в `plans/current_task.md`
- **Файл:** `plans/current_task.md:62-65` содержит `ssh nik@198.46.175.136` и пароль. Файл на HEAD не менялся (вне диффа раунда), но это R17-долг репозитория: рекомендовано отозвать/сменить пароль и вычистить из истории.

---

## 4. Итоги Validator (точные результаты)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5752 passed**, 1 warning (`closed 12 leaked aiosqlite connection(s)`), 81.92s | **0** |
| `node --check web/app.js` | без вывода (clean) | **0** |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | **0** |
| `git diff --check` | чисто (только CRLF-предупреждения Git, не ошибки) | **0** |

Дополнительно: `pytest` по 9 целевым фичам + `test_param_catalog` — 185 passed; FULL `pytest` = 5752/0 (сверх baseline 5589 — +163 теста).

---

## 5. Инварианты

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/приватность в логах) | ✅ | diff-скан `logger.*(url|text|secret|token|password)` — новых утечек нет; `[tools]`-логи только `tool=<name>`/`out_chars`/`type(exc).__name__`; F9 — только `chat_id/count/out_chars` |
| R16 (id — ключ, label — entity_name, group — entity_type; `target_user` — лейбл) | ✅ | `database.py:3669-3672`; `nostalgia_prompts.py:143-147`; `tool_router.py:670-684` |
| Порядок роутеров `bot.py` (только DI-kwargs) | ✅ | `bot.py:658-675,745` не изменён; diff — только DI и локальные `youtube_service`/`checkup_service` |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | `REGISTRY == 435`; `len(fields) == 406`, `GROUPS == 90`, «19»-пины зелёные; `config/settings.py` и `param_catalog.py` — Δ0 (только текст описания окна «(10)») |
| `media/` и `.env` не тронуты | ✅ | `git status` — отсутствуют |
| Пин-тесты каталога не ослаблены | ✅ | удалены только неиспользуемые маркеры, счётчики синхронно обновлены |
| F6: нет флага `command_prefix_enabled` | ✅ | grep по коду — отсутствует |
| F6: реестр строго 17 + bare `чекап`/`фактчек` | ✅ | `command_registry.py:19-32`; `test_command_registry_round1015.py:63-88` |
| F6: дефолтные бот/ботик/ботяра отключаются при имени | ✅ | `direct_chat.py:151-162`; тест `test_name_set_disables_botword` |
| F6: функциональная команда не уходит в LLM | ✅ (with M2 caveat) | `direct_chat.py:440-442`; тест `TestPriority::test_search_consumes_llm_not_called` |
| F6: download-yield | ✅ | `video_download.py:224-229` + `direct_chat.py:440-442`; тест `test_functional_command_yields_unhandled` |
| F4: PREV байт-идентичен прежнему; `PROMPT_MIGRATIONS` не тронут | ✅ | проверено сравнением с `798e044` (`PREV == old: True`); файл миграций не менялся |
| F8: tool-set валиден (7), лимиты tool-loop не сломаны | ✅ | `tool_schemas.py:181-189`; `TOOL_MAX_ROUNDS`/`_TOOL_CALLS_PER_ROUND_MAX` вне diff; тесты `TestToolLoopLimits` |
| F8: успех скачивания только после реальной отправки | ✅ | `tool_router.py:558-580`; тест `test_download_failure_is_honest_error_no_send` |
| F9: depth≤150 / query / приватность | ✅ | `tool_router.py:121-132,602-684`; тесты `test_depth_clamped_to_max`, `TestR17` |
| F7: гайд соответствует реестру; идемпотентная миграция | ✅ | `test_guide_round1015.py`; байт-тест `DEFAULT_INFO_TEXT == info_text.md` |
| F1: SQL без full-scan | ✅ | EXPLAIN: `SEARCH edges USING INDEX idx_edges_chat_weight (chat_id=?)` в обоих UNION ALL-ветках |
| Безопасность (XSS/инъекции/гонки/границы) | ✅ (кроме M1/M2/H1) | новый HTML без `v-html` (self-host DOMPurify), SQL параметризован, `split_prefix` с `re.escape`, инъекций не выявлено |

---

## 6. Что исправить @Builder (до повторного ревью)

1. **H1 (F5):** погасить `dream.active`/`deep_sleep.active` (и `active_until`) при `enabled=false` — либо на бэке, либо приоритетом проверки `enabled` во фронте; добавить регресс-тест «выключено + в окне → active=false».
2. **M1 (F6):** добавить правую границу слова к триггерам в `command_registry.matches`/`matches_group`; покрыть тестами «Бот, загуглика»/«Бот, транскриптер»/«Бот, найдикто» → UNHANDLED.
3. **M2 (F6):** сделать yield в `direct_chat` условным (только при активном соответствующем модуле), чтобы не терять сообщения; тест «модуль выключен → сообщение не теряется».
4. **L1:** удалить (или задействовать) `command_registry.is_bare_command`.
5. **L2:** синхронизировать шапки `spec.md` с фактическим статусом IMPLEMENTED.
6. **L3:** поправить docstring `tool_router.py:23-24`; при желании — свести `_send_file`/`media_send.send_media` к одному пути.
7. **L4:** закрыть утекающие aiosqlite-соединения в новых тестах.

После правок — повторный полный `pytest`, `node --check web/app.js`, `node tests/js/routing_test.js`, `git diff --check`.

**Вердикт (итерация 1): `Rejected`.**

---

# 7. Повторное ревью (итерация 2)

> **Ревьюер:** @Reviewer. **Дата:** 14.09.2026. **Baseline:** HEAD `798e044` + незакоммиченные правки @Builder (итерация 2).
> **Метод:** построчный аудит правок по 4 пунктам отклонения + прогон Validator + проверка инвариантов + воспроизведение кейсов.

## 7.1. Итоговый вердикт (итерация 2): **Approved**

Все 4 пункта отклонения (H1, M1, M2, Low) закрыты фактически, с регресс-тестами. Полный `pytest` — **5761 passed / 0 failed**, утечка aiosqlite исчезла (в warnings остался только `StarletteDeprecationWarning`). JS-гейты и `git diff --check` чистые. Инварианты R16/R17, порядок роутеров, каталог (Δ=0), tool-сет (7), PREV (байт-в-байт), `PROMPT_MIGRATIONS`, `media/`/`.env` — подтверждены.

## 7.2. Статус пунктов отклонения

### H1 (F5: `enabled=false` не гасил активность) — ✅ ПОДТВЕРЖДЕНО
- **Бэкенд:** `web/api/memory_agi.py:482` `dream_in = bool(enabled and in_window)`; `:483` `dream_active = dream_in or dream_running`; `:484-485` `dream_active_until = ... if dream_in else None`. Для глубокого сна: `:492` (fixed) и `:497` (after_sleep) `deep_in = bool(deep_enabled and ...)`; `:499` `deep_active = deep_in or deep_running`. `running` уважается как fallback (вне окна → `active=true`, `active_until=null`).
- **Фронт:** `web/app.js:1216-1218` (сон) и `:1234-1236` (глубокий сон) проверяют `d.enabled === false` **раньше** `d.active` → «☀️ Сон выключен»/«🌅 Глубокий сон выключен» с `badge-muted`.
- **Регресс-тесты:** `tests/test_webapp_round1015_ui.py:126-134` (dream off + в окне → `active=false`, `active_until=None`), `:137-146` (deep off), `:149-160` (fixed-триггер off), `:174-190` (`running` вне окна → `active=true`, `active_until=null`); JS `tests/js/routing_test.js:1439-1453` (фронт-приоритет `enabled`).

### M1 (F6: нет правой границы триггеров) — ✅ ПОДТВЕРЖДЕНО
- `services/command_registry.py:39-41` введены `_CHAR_CLASS = "0-9a-zа-яё_"`, `_TAIL = (?![...])`, `_HEAD = (?<![...])`; `:44-51` `_compile` навешивает `^`/`_HEAD` + `_TAIL`; `:55-59` собраны `_TRIGGER_RE` (anchor), `_GROUP_START_RES` (anchor), `_GROUP_WORD_RES` (word-search). `matches`/`matches_group` (anchor) и `has_trigger_word` (границы с обеих сторон) используют эти регексы.
- Хендлеры переведены на реестр: `handlers/search.py:109` (`matches_group`), `handlers/youtube.py:169-172` (`has_trigger_word`), `handlers/web.py:65-68` (`has_trigger_word`).
- **Регресс-тесты:** `tests/test_command_registry_round1015.py:105-116` («загуглика/транскриптер/найдикто/поищите» → не матч; позитивы «загугли», «транскрипт видео» целы), `:171-175` (`_parse_search_query("Бот, загуглика"/"Бот, найдикто"/"Бот, поищите") is None`), `:215-220` (`_has_trigger("транскриптер")`/`"выжимкалка"` → False), `:222-231` (UNHANDLED). Позитивы не сломаны.

### M2 (F6: безусловный yield терял сообщение) — ✅ ПОДТВЕРЖДЕНО
- `handlers/direct_chat.py:102-108` `_FUNCTIONAL_FLAGS` (search/youtube/web/checkup/download → master-флаг + settings-фолбек); `:111-116` `_functional_module_active`; `:461-463` yield теперь только `if group is not None and _functional_module_active(group)`.
- Гейты совпадают с фактическими воркерами: `handlers/search.py:117`, `handlers/web.py:122`, `handlers/checkup.py:97`, youtube `handlers/youtube.py:1044`; download-модуль гейтится флагом и на этапе DI (`bot.py:171,739`), поэтому `flags.download_enabled=false` ⇔ отсутствие downloader.
- **Регресс-тесты:** `tests/test_command_registry_round1015.py:323-332` (модуль включён → UNHANDLED, `handle` не вызван), `:334-344` (download off → LLM, `handle` вызван), `:346-355` (search off → LLM). Плюс `tests/js/routing_test.js` и `TestPriority::test_search_consumes_llm_not_called` (позитив не сломан).

### Low — ✅ ПОДТВЕРЖДЕНО
- **L1:** `is_bare_command` отсутствует в продовом коде (`grep` по `*.py` — 0 совпадений). Остался канонический `BARE_COMMANDS` (используется тестом/реестром).
- **L2:** шапки всех 9 `spec.md` — `🟢 IMPLEMENTED` (строка 3 каждой): graph-sampling, graph-frontend-physics, sleep-unblock, status-graph-ui, hybrid-tool-calling, recent-history, command-prefix, nostalgia-revamp, guide-rewrite.
- **L3:** docstring `services/tool_router.py:20-31` исправлен (F8/F9 описаны корректно). Опциональное сведение `video_download._send_file` ↔ `media_send.send_media` не выполнено — по L1-классу это «при желании», не блокер.
- **L4:** соединения закрываются — `tests/test_webapp_round1015_graph.py:27-34` (`await d.close()` в фикстуре), `tests/test_recent_history_tool_round1015.py:89`; предупреждение `closed N leaked aiosqlite connection(s)` пропало.

## 7.3. Итоги Validator (итерация 2, точные результаты)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5761 passed**, 0 failed, 1 warning (`StarletteDeprecationWarning` — не наш код), 78.88s | **0** |
| `node --check web/app.js` | без вывода (clean) | **0** |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | **0** |
| `git diff --check` | чисто (только CRLF-предупреждения Git, не ошибки) | **0** |

Целевой прогон фиксов (`test_command_registry_round1015` + `test_webapp_round1015_ui` + `test_sleep_fallback_round1015` + `test_nostalgia_prompts` + `test_tool_calling_round1015`) — **139 passed / 0 failed**.

## 7.4. Инварианты (итерация 2)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/приватность в логах) | ✅ | правки итерации 2 — комментарии/условия, новых логов с URL/текстами нет |
| R16 (id/entity_name/entity_type) | ✅ | не затронуто правками итерации 2 |
| Порядок роутеров `bot.py` | ✅ | `bot.py:658` search, `:662` youtube, `:666` web, `:670` checkup, `:675` direct_chat, `:745` video_download — не изменён; `git diff bot.py` — только DI-kwargs |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | пины на месте (`test_settings_persistence_round1014.py:41,43,44,48`, `test_frontend_tab_mapping.py:84` и др.); FULL pytest зелёный |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| tool-сет = 7 | ✅ | `tests/test_tool_schemas.py:90`, `tests/test_tool_calling_round1015.py:541` — зелёные |
| PREV-слепок байт-идентичен | ✅ | собственная проверка: `NOSTALGIA_PROMPT@HEAD == PREV_NOSTALGIA_PROMPT@worktree` → `True` (451 байт) |
| `PROMPT_MIGRATIONS` не тронут | ✅ | `git diff --stat` по `services/prompt_migrations.py` — пусто |
| `is_bare_command` удалён | ✅ | grep по `*.py` — 0 |
| F6: нет флага `command_prefix_enabled` | ✅ | не введён |
| F6: реестр 17 + 2 bare | ✅ | `command_registry.py:23-32`; `test_command_registry_round1015.py:73-92` |

## 7.5. Остаточные замечания (не блокируют `Approved`)

1. **Косметика (info):** при `enabled(dream)=false`, но `deep_enabled=true` и внутри окна `deep_active=true` при `deep_active_until=null` (ветка after_sleep, `memory_agi.py:497-499`) → бейдж «🌌 Глубокий сон идёт» без времени окончания. Соответствует требованию H1 («`deep_active = deep_enabled and deep_in or deep_running`») и F5-семантике независимых рубильников; на отказ не влияет.
2. **Опционально (Low):** две реализации отправки медиа (`video_download._send_file` и `services/media_send.send_media`) сосуществуют — риск расхождения поведения сохраняется, но в объём фикса итерации 2 не входил.
3. **Repo-wide R17-долг (вне диффа раунда):** `plans/current_task.md:62-65` содержит SSH-доступ и пароль. Рекомендация прежняя — пароль сменить/отозвать и вычистить из истории. К данному раунду не относится.

## 7.6. Заключение

H1/M1/M2 и все Low-замечания закрыты фактически (file:line + регресс-тесты), регрессий не внесено, Validator чист, инварианты соблюдены. Блокеров нет.

**ИТОГОВЫЙ ВЕРДИКТ (итерация 2): Approved**

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
