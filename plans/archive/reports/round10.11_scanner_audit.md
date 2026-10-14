# Round 10.11 Scanner Audit (llm-providers-refactor-round1011: saved-key probe, LLM Провайдеры refactor, key-history chart, память-отчёт)

> Аудит 2026-09-12 (Step 6). HEAD `ec5dd1f` (10.10) + рабочее дерево 10.11.
> `git status -s`: **13 modified + 3 untracked** (`plans/docs/memory_sleep_nostalgia_lore_report.md`,
> `plans/features/llm-providers-refactor-round1011/`, `tests/test_webapp_round1011_ui.py`).
> `git diff --stat`: **+747/−137** по 13 путям.
> Изменённые исходники: `services/{param_catalog,llm_probe,llm_client,status_service}.py`,
> `web/{app.js,index.html}` + 5 тест-файлов + `.gitignore`/`plans/backlog.md`.
> Пункт 4 (прозаичный отчёт о памяти/сне/ностальгии) — docs-only, кода не касается.
>
> **pytest: 5168 passed, 0 failed, 1 warning** (61.66s; база 10.10 = 5144/0 → +24).
> **`node --check web/app.js` — clean.** **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, полные тексты новых зон шаблона, независимый
> расчёт инвариантов каталога, R17-резолв сохранённого ключа, конфиг графика, RBAC/DM,
> секреты/PG-DDL/SSRF/Headroom. Headroom — вне репозитория.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19 / CONFIG_TAB_TITLES 19** | Независимо: `len(REGISTRY)==400`, `len(GROUPS)==90`, `len(_TAB_BY_GROUP)==88`, `len(TAB_RULES)==19`, `len(CONFIG_TAB_TITLES)==19`, `fields(Settings)==372` | ✅ |
| **Sanctioned Δ категорий (ADR-1011-2)** | `categorized` 372→**376** (models 40→42, keys 13→15), `infra` 28→**24**; REGISTRY/Settings не изменились (перенос 4 записей, не добавление); тесты `test_param_catalog.py` (42/15) и `test_webapp_api.py:1198` (376) отражают Δ | ✅ |
| **Ноль новых PG-DDL** | `services/database.py`/`services/pg_db.py` не в диффе; `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN\|DROP TABLE\|CREATE INDEX"` — пусто; миграция `migrate_env_to_pg` — DML (`ON CONFLICT DO NOTHING`) | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY == 8`; `services/database.py` не менялся | ✅ |
| **`bot.py` router order не тронут** | нет в `git diff`/`git status` | ✅ |
| **`media/` не тронут** | нет в диффе/`git status` | ✅ |
| **`.env` не тронут** | нет в диффе | ✅ |
| **Нет секретов** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` и по untracked (вкл. `memory_sleep_nostalgia_lore_report.md`) — пусто | ✅ |
| **Нет Headroom-ссылок в коде** | repo-wide grep `services/ web/ tests/ config/` — 0 | ✅ |
| **Существующие пин-тесты не ослаблены** | полный pytest 5168/0 + маркеры 10.6–10.10 зелёные | ✅ |

## 2. Верификация пунктов раунда

| # | Пункт | Проверка | Вердикт |
|---|---|---|---|
| 1 | Ключ: «Проверить» без повторного ввода (ADR-1011-1) | `services/llm_probe.py:51-65` карта `_BLOCK_SAVED_KEY` (все сетевые блоки + media_share); `_saved_api_key` (`:70-91`) — `hot.get(pg_key, settings_default)`, ошибка → `""`; в `probe_block` (`:247-250`) резолв **только при пустом/пробельном** `api_key`; явный draft приоритетнее (UI `web/app.js:2125` шлёт `api_key` только если truthy). Резолв внутренний: ключ не попадает в результат (`_result` — ok/status/latency/model/error) и не логируется; тело ошибки — `sanitize_error` (R17). UI: поле остаётся пустым (`:value="blockFieldValue(f)"`), hint «Ключ сохранён (••••last4)» через маску `{configured,last4}` (`blockFieldConfigured`/`last4ByKey`, `web/app.js:2104-2115`). Сырой секрет в DOM/сеть не уходит | ✅ |
| 2.1 | Nav/профиль/сетка | `nav-icon 22px`, `gap .15rem`, `min-width 60px`; профиль `shrink-0` + `whitespace-nowrap`; `.hub-head`/`.hub-grid` `max-width:64rem` + `justify-self:center` (mobile 1 колонка) | ✅ |
| 2.2 | Две зоны | `providerConnectionBlocks`/`providerAdvancedBlocks` — **computed** (не methods) в секции `computed:` (`web/app.js:957-966`); шаблон — bare-ref (`web/index.html:807,947`); зона «Подключения» сверху, «Расширенные настройки» — `<component :is=details/div>` + `<summary>`; на прочих вкладках `div` (поведение не меняется). reviewer-CRITICAL (метод→`[]`) закрыт жёстким тестом | ✅ |
| 2.3 | Эмбеддинги 3 подблока | `embeddings.subBlocks = [main, f1, f2]`, у каждого Base URL+Модель+Ключ+«Проверить»; `providerCoveredKeys` рекурсивно покрывает `subBlocks` (нет дублей в generic); 4 записи перенесены в каталог (ADR-1011-2), `llm_client`/`status_service` читают через `hot.get`; shared base/model у Ф1↔Ф2 помечен подсказкой | ✅ |
| 2.4 | Видео-фоллбэк | `video_fallback` строго после `video_summary_openrouter`; поля display/base/model/key; хардкод `VIDEO_FALLBACK_MODEL` остаётся только code-default в settings, значение каталожное; `probe_block` kind=chat | ✅ |
| 2.5 | Media-share вниз + human-subtext | `media_share` → `zone:'advanced'` + `note`; `search_keys`/`llm_guard` тоже advanced внизу; теххаос ниже зоны «Подключения» | ✅ |
| 3 | График key-history (ADR-1011-3) | Точки `{x: ts*1000, y: lane|null}` (`web/app.js:3587-3593`), `spanGaps:true` (`:3602`), `stepped:true`; X — `type:'linear'` + `min/max` из `xMin/xMax` + `ticks.callback` HH:MM (`:3649-3661`), `parsing:false`; **`type:'time'` отсутствует** (без date-adapter); серверный контракт `GET /api/status/key-history` (`api_payload`, `services/key_history.py`) **не изменён** (файл не в диффе) | ✅ |

## 3. Находки раунда 10.11

Critical/High/Medium — **нет**. Ниже Low/Info (не блокируют мерж).

### [R10.11-1] severity: low — вложенные `<details>` делят один localStorage-ключ `adminbot.expand:llm_providers`
**Файл**: `web/index.html:934-937` (новый внешний `<details>` «Расширенные настройки») vs `web/index.html:1188-1190` (внутренние `<details class="advanced mt-4">` каждой generic-группы); `web/app.js:2510-2519` (`expandOpen`/`toggleExpand`).
**Суть**: и внешний, и внутренние details биндят `:open="expandOpen(activeTab)"` + `@toggle="toggleExpand(activeTab)"` — один и тот же персистентный ключ. `localStorage` не реактивен, но `:open` пере-применяется на каждом рендере Vue; при смене флага внутренние details открываются/закрываются, каждое их `toggle` снова флипает флаг, и на следующем рендере внешний блок может самопроизвольно закрыться/открыться (эффект зависит от чётности числа групп с advanced-полями). Класс проблемы был и до 10.11 (несколько внутренних details), но внешний `<details>` — новый участник того же ключа. Функциональной потери данных нет (persist только UI-состояние).
**Ремендация**: отдельный ключ для внешней зоны (напр. `adminbot.expand:llm_providers:advanced`) и/или ручной `@toggle`-синк без шаринга ключа.

### [R10.11-2] severity: low — расхождение `embedding_fallback_model` между рантаймом и карточкой статуса при явной очистке
**Файл**: `services/llm_client.py:305-308` vs `services/status_service.py:261-263`.
**Суть**: `llm_client` при пустом значении в БД → `or self._embed_model` (основная embed-модель — как заявлено в описании каталога «пусто — берётся основная»). `status_service` при пустом значении → `… or settings.EMBEDDING_FALLBACK_MODEL or emb_model`, т.е. при заданном env-значении карточка покажет env-модель, тогда как рантайм факта использует основную. Возникает только если модель явно очищена в UI (БД `''`), а `EMBEDDING_FALLBACK_MODEL` в env непуст. Диагностический дисплей, не влияет на боевой вызов.
**Ремендация**: сделать `fb_model` в `status_service` симметричным (`or emb_model`, без промежуточного settings-фолбэка) либо задокументировать расхождение.

### [R10.11-3] severity: low — устаревшие подсказки «править в .env» для embed-фоллбэк-ключей
**Файл**: `services/llm_client.py:170-172` (`humanize_embed_error`, 401: «…проверьте LLM_API_KEY и запасные ключи эмбеддинга (EMBEDDING_FALLBACK_API_KEY(_2)) в .env»), `config/settings.py:341-343` (комментарий «R17: ключ — только в .env»).
**Суть**: после ADR-1011-2 ключи стали first-class каталогом (админка → «LLM Провайдеры → Эмбеддинги») и читаются `hot.get` из PG; при наличии строки в `bot_settings` правка `.env` уже не авторитетна. Тексты вводят оператора в заблуждение. На поведение/безопасность не влияют.
**Ремендация**: переформулировать на «проверьте ключ в админке (LLM Провайдеры → Эмбеддинги)» и обновить комментарий settings.

### [R10.11-4] severity: info — probe прикрепляет сохранённый секрет к произвольному (caller-supplied) `base_url`
**Файл**: `services/llm_probe.py:247-250` + `_safe_base` (`:109-131`).
**Суть**: `POST /api/llm/test` (`requires_global_admin`) принимает `base_url` от клиента и при пустом `api_key` подставляет сохранённый секрет блока → заголовок `Authorization` уйдёт на указанный https-хост. Это не новая привилегия: глобальный админ и так может перенастроить `models.llm_base_url` и вызвать отправку ключа в бою; к тому же запрос требует глобального админа. Но стоит зафиксировать как hardening: при желании резолвить `base_url` из конфига блока, игнорируя caller-значение (или вести allowlist хостов).
**Impact**: информационный (R17-инвариант «наружу не эхо» формально не задет; сырой ключ не возвращается клиенту).

### [R10.11-5] severity: info — мёртвая ветка `destroy()` в `renderKeyHistoryChart`
**Файл**: `web/app.js:3670` (`if (self.keyHistoryChart) { self.keyHistoryChart.destroy(); }`).
**Суть**: функция уже уничтожает инстанс в начале (`:3617-3620`) и между этими точками ничего чарт не создаёт → `self.keyHistoryChart` здесь всегда `null`; строка недостижима. R10.10-3 (ранний return без destroy) закрыт корректно — подтверждено. Стилевой рудимент.

### [R10.11-6] severity: info — отсутствие headless-теста фактического рендера `spanGaps:true`/`parsing:false`
**Файл**: `web/app.js:3587-3610`, `:3643-3661`; тесты — статические маркеры (`tests/test_webapp_round1011_ui.py`, `tests/js/routing_test.js`).
**Суть**: JS-юниты проверяют модель/конфиг (точки `{x,y}`, `xMin/xMax`, `spanGaps:true`, `parsing:false`, `type:'linear'`, callback HH:MM), но не реальное поведение Chart.js 4 с `y:null` при `parsing:false`. ADR-1011-3 §5 даёт fallback (emit только присутствующих точек), если живой QA покажет, что разрыв не тянется. Фиксируется как непокрытый runtime-риск, не дефект.

## 4. Проверенные области — вердикты (логических дыр не найдено)

1. **R17 сохранённого ключа**: сырой секрет циркулирует только внутри `probe_block`; `_saved_api_key` не логирует значение (`exc_info` — без locals); `sanitize_error` вычищает ключ из тела ошибки; `_result` не содержит ключ; UI получает только `{configured,last4}` (`_mask_secret`, `web/api/routes.py:194-203`). Тесты `test_blank_key_resolves_saved`, `test_explicit_key_wins_over_saved`, `test_webapp_api.test_blank_api_key_resolves_saved_key` — ок.
2. **Empty-draft vs explicit-clear**: отсутствие черновика и `draft===''` для секрета оба дают `v=''` → probe резолвит сохранённый ключ; это ADR-1011-1 §3 (by design). `saveBlock` секретов пишет только truthy draft (`''` не очищает секрет) — поведение MINOR-3 не менялось. Регресса нет.
3. **4 embed-фоллбэк-записи**: `models.embedding_fallback_base_url`/`_model` → category `models`/group `models_embeddings`; `keys.embedding_fallback_api_key`/`_2` → `keys`/`keys_llm`, `secret=True`; `get_by_pg_key` возвращает `settings_field`, `_saved_api_key` берёт settings-дефолт; `llm_client`/`status_service` читают `hot.get` с прежними дефолтами (паритет без кэша). `_INFRA` оставил только тайминги.
4. **Chart-конфиг**: `parsing:false` + `{x,y}`; линейная ось с `xMin/xMax` (ms), callback HH:MM; `spanGaps:true`+`stepped:true`; `api_payload`/`key_history.py` не тронуты; окно от конца (`MAX_HISTORY_POINTS`/`MIN_BUCKETS`) не менялось; `maintainAspectRatio:false`/`keyHistoryChartHeight`/`ref="keyHistoryCanvas"` целы.
5. **Баланс Vue-шаблона**: независимый stack-парсер тегов (с исключением `<style>/<script>` и void) — **0 несбалансированных** в рабочем `web/index.html` и в HEAD-версии; `v-if`-цепочка config-ветки и перенос `</template>`/`</component>` корректны. Рекурсивный `providerCoveredKeys` скрывает все subBlock-ключи из generic-рендера.
6. **RBAC/DM**: `/api/llm/test` — без изменений `requires_global_admin`; DM-пути не затронуты; `providerConnectionBlocks`/`providerAdvancedBlocks` — только UI-фильтр, серверные гейты не менялись. Секреты 10.11 — `secret=True`, маскируются.
7. **Отсутствие функциональной потери**: удалённый `sections` у вкладки `llm_providers` (TABS) используется только `sectionTitle` (`web/app.js:2876`); `groupedForTab` работает по `sources` — набор групп/пунктов не изменился. Прочие вкладки не затронуты (обёртка `<component :is>` = `div`).
8. **Тест-качество**: полный pytest 5168/0 (+24 к базе), obновлены каталог-счётчики (42/15/376), миграция keys 13→15; JS-юниты — точки/ось/зоны/computed/R17-draft; новый `tests/test_webapp_round1011_ui.py` — функциональные проверки каталога и маркеры.

## 5. Итог 10.11

- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **3** (R10.11-1 nested details, R10.11-2 model-divergence, R10.11-3 `.env`-подсказки), Info: **3** (R10.11-4 probe base_url, R10.11-5 мёртвый destroy, R10.11-6 непокрытый render Chart.js). Для мержа не обязательны.
- Инварианты соблюдены: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19 / CONFIG_TAB_TITLES 19**; sanctioned Δ категорий (376 categorized, infra 28→24) без роста REGISTRY/Settings; **ноль PG-DDL**; SQLite **v8**; `bot.py`/`media/`/`.env` не тронуты; секреты не коммитятся; **Headroom-ссылок в коде нет** (out of scope).
- pytest **5168 passed / 0 failed** (61.66s); `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

*Round 10.11 report generated by Scanner on 2026-09-12*
