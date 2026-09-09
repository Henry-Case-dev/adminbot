# spec.md — frontend-limits-temperature-budgets (ТЗ 3 раунда 10.4, фича B)

Задачи: T-990…T-1005 (tasks.md). Стадия старта — PLANNED → ARCHITECTED (наст. файл).
База: HEAD `1410a68`. Порядок: после A (перенос групп), до F/H/G. **F-1 (T-648 атомарный POST /api/config, T-651/652 касты) — ДО этой фичи** (учит «атомарность POST» в AC; NaN-каст T-654 — учесть).

## 1. Контекст и проблема

Три независимых под-фичи ТЗ 3:
- **3a. Бюджеты «Прямой чат»** — гейт `flags.chat_context_budgets_enabled` читается как `settings.CHAT_CONTEXT_BUDGETS_ENABLED` в direct_chat_service.py:1011 (НЕ hot.get!) — нет per-chat настройки; для чата **-1002661910336** бюджеты нужно ВЫКЛЮЧИТЬ (нет BYOK-ключа; глобальный ключ 25 req/сутки — экономия токенов; F-15-диагностика).
- **3b. Температура** — `limits_temperature` (4 ключа: CHAT_TEMPERATURE_PRECISE/BALANCED/CHATTY float + CHAT_TEMPERATURE_PRESET_DEFAULT str) — текстовое поле; ТЗ: выпадающий список. Виджетов «select» в каталоге нет («» | «keyvalue»).
- **3c. Имена людей** — `limits_user_aliases` (SUMMARY_ALIASES, KV-редактор) на «Лимитах»; ТЗ: отдельный раздел + настраиваемость per-чат/ЛС.

## 2. Ключевые решения

### 2.1 Бюджеты (3a)

| ID | Решение | Обоснование |
|----|---------|-------------|
| **B-1** | Рендер-группа гейта меняется: `flags.chat_context_budgets_enabled` → `group=limits_chat_budgets` (только группа; pg-ключ `flags.chat_context_budgets_enabled`, тип bool, семантика — без изменений; каталог 383/71/359 без роста). | ТЗ: карточка «Бюджеты контекста direct_chat» должна быть ВМЕСТЕ с бюджетами (цельный блок «Прямой чат: бюджеты токенов»); per-chat=True остаётся (flags — per_chat категория). |
| **B-2** | Резолв гейта — **существующий** `get_chat_param(chat_id, key, default)` (chat_params.py:210-217: overrides → hot.get → default + каст). Точка замены: direct_chat_service.py:1011 (`settings.CHAT_CONTEXT_BUDGETS_ENABLED` → async `chat_param(chat_id, "flags.chat_context_budgets_enabled", settings.CHAT_CONTEXT_BUDGETS_ENABLED)`); для чатов без override — байт-в-байт текущее (hot.get/key default). | Хелпер уже существует (F-9/F-10) — новый НЕ создаём; async-контекст в generate присутствует. |
| **B-3** | Наследование для ЛС: **как обычный per_chat ключ** (override юзера → глобальное). НЕ создавать исключений «default off» (в отличие от саммари — R10.3-5-асимметрия здесь НЕ нужна: бюджеты экономят токены и на ЛС, но отключать ЛС по умолчанию нельзя — ТЗ не просит; «юзер правит свои ЛС» (F-14) — механизм уже единый через chat_params). | F-14: единственное исключение из наследования — саммари; бюджеты — не исключение. |
| **B-4** | **Override для -1002661910336 = false** — новый идемпотентный скрипт `scripts/backfill_104_chat_flags.py`: (1) `ensure_scope_profile(-1002661910336, dm=False, pg=cache.pg)`; (2) если `overrides["flags.chat_context_budgets_enabled"]` отсутствует → `set_chat_params(chat_id, {"overrides": {…, "flags.chat_context_budgets_enabled": False}, "meta": {…}}, changed_by=None)`. Повторный прогон — no-op (не перезаписывает существующие; обязателен `expected_updated_at=None` — последняя запись побеждает, но только для `flags.chat_context_budgets_enabled`). | Идемпотентность (AC-B3); канон write-path F-7 (единая точка с NOTIFY/409); никаких прямых SQL-UPDATE (канон DDL+Nутify). |
| **B-5** | Точки чтения B-бюджета (доп. к гейту): доли бюджета direct_chat_service.py:996-1014 (CHAT_BUDGET_*_RATIO) остаются глобальными (ТЗ просит ТОЛЬКО флаг вкл/выкл — не множители). | Скоуп ТЗ 3a: флаг; множители — кандидаты фичи G (per-chat overrides). |
| **B-6** | Read-пути для F-5: реестр в отчёте фичи (T-993): `direct_chat_service.py:1011` → `chat_params.get_chat_param`; + `scripts/backfill_104_chat_flags.py` → `ensure_scope_profile`/`set_chat_params`. | AC-B4. |

### 2.2 Температура (3b)

| ID | Решение | Обоснование |
|----|---------|-------------|
| **B-7** | **ParamSpec.widget** = "" | "keyvalue" | "select"; новое поле `select_options: tuple[str,...] | None` и `select_labels: tuple[str,...] | None` (len(options)==len(labels); по умолчанию None; сериализуется только при widget=="select"). | Расширение каталога БЕЗ роста записей (383/71/359); backwards-compat: старые записи — widget="" и options None (тесты прошлого поведения зелёные). |
| **B-8** | `CHAT_TEMPERATURE_PRESET_DEFAULT` (Settings `CHAT_TEMPERATURE_PRESET_DEFAULT`, тип str, группа limits_temperature) — widget="select", options=("precise","balanced","chatty"), labels=("Точный","Сбалансированный","Болтливый"); float-поля пресетов — без изменений (обычные поля, advanced по фиче D/разметке — оставить как сейчас: маркеры не совпадают → basic; решение: float-пресеты остаются basic-полями, выпадающий список — базовая карточка с дефолтом). | ТЗ: «выпадающий список» — пресет-дефолт; числовые калибровки остаются редактируемыми полями. |
| **B-9** | API: (1) GET /api/config items += `select_options`, `select_labels` (routes.py:293-317 рядом с widget) — только при наличии; (2) POST /api/config: проверка `spec.widget == 'select'` → value ∈ select_options (после `_coerce_value`; иначе **422** `"недопустимая опция"`); применяется в ОБЕИХ ветках (глобальная `_post_config_global` и per-chat routes.py:401-412 — инвариант «единая валидация»); T-651/652-касты: select-значение — str (каст не меняется; str пройдёт normalize_value как есть — ок). | 422-контракт (AC-B6); атомарность POST F-1: select-значение — валидный item в атомарном патче. |
| **B-10** | Рендер: в generic-шаблоне (index.html basic :591-666 и advanced :683-742) — новая ветка `v-else-if="item.widget === 'select'"`: `<select class="field" v-model="item.value" :disabled="!canEditConfig(item.key)" @change="saveConfigItem(item)">` + `<option v-for="(o, i) in item.select_options" :value="o">{{ (item.select_labels && item.select_labels[i]) || o }}</option>`; **автосейв на change** (паттерн bool-тумблера — дискретное действие). | AC-B7/B8; select — дискретный контрол: автосейв естественен; сохранение — существующий `saveConfigItem` (str-значение); reload — выбранное значение (GET отдаёт). |

### 2.3 Имена людей (3c)

| ID | Решение | Обоснование |
|----|---------|-------------|
| **B-11** | Новая config-вкладка `people_names` («Имена людей», menu `chat_profile`, type config, icon «🏷»): sources limits {limits_user_aliases}; TAB_LIMITS except limits += {limits_user_aliases}. | ТЗ: «отдельный раздел»; KV-редактор уже существует (widget keyvalue + kv-editor :610-615). |
| **B-12** | **Per-chat/ЛС резолв алиасов**: единый хелпер в `services/summary_aliases.py` (или chat_params.py — решение: summary_aliases.py, где живёт AliasResolver): `async def build_alias_resolver(chat_id) -> AliasResolver` — `raw = await get_chat_param(chat_id, "limits.summary_aliases", hot.get("limits.summary_aliases", settings.SUMMARY_ALIASES))` → `AliasResolver(raw)` (принимает dict/str; мусор → warnings-путь существующий). | Единый write/read-путь; группы — override → global; ЛС — override → global (наследование, НЕ summary-исключение); поведение других чатов без override — как сейчас. |
| **B-13** | Точки перевода (только с chat_id в скоупе): (1) web/api/chat_lore.py:555-556 (list_relations — резолв алиасов списка участников): `hot.get(...)` → `build_alias_resolver(chat_id)`; **НЕ зависить от summary_enabled** (Hotfix-R10-инвариант сохранён — резолв напрямую, не через RelationsService.aliases-гейт); (2) direct_chat_service инжект `<user_relations>` (bot.py:570-571-гейт `flags.summary_enabled` **НЕ трогать** — но при включённом: RelationsService-алиасы) → per-chat resolver для инжекта (передача aliases в `relations_service.get_relations_snapshot(..., aliases=resolver)` — аддитивный параметр); (3) user_relations.py-каскад `_display_name` — через переданный aliases; (4) bot.py:322-глобальный AliasResolver (media/config-каскады без chat_id: media_common/youtube/voice_transcription) — **БЕЗ изменений**. | AC-C2: (1) группа — override → глобальные; (2) ЛС — свои/глобальные; (3) суммация summary_enabled-гейт не регрессирует; (4) экзогенные пути без chat_id — глобальные (не в скоупе ТЗ). |
| **B-14** | KV-редактор в per-chat режиме: карточка «Имена людей» (вкладка people_names) показывает значение как обычный item (GET уже отдаёт override'ы с chat_source='chat' — /api/config per-chat ветка routes.py:286-292); сохранение через существующий POST /api/config X-Chat-Id → chat_params.overrides (`limits.summary_aliases` — json, per_chat=True — каталог ок); «↪ глобальное» — существующий resetChatOverride; права — canEditConfig (DM — is_dm_owner → True, ВНИМАНИЕ R10.3-1: `limits.summary_aliases` — per_chat=True — в DM-ветке canEditConfig уже True — конфликтов нет; models.*-проблема R10.3-1 НЕ решается этой фичей (вне скоупа — noted в §6). | AC-C3; нулевой новый механизм — переиспользуем override-флоу generic-рендера. |
| **B-15** | Каскад-тесты (F-6-наследие T-1001): alias-приоритет над nickname/username; «'id' никогда имя» (R16); username без «@»; per-chat override → каскад на этом чате; ЛС — свои алиасы; каталог без изменений. | AC-C4; тесты в `tests/test_summary_aliases.py`/`tests/test_relations_service.py` (расширения) + `tests/test_dm_access.py`-класс. |

## 3. Изменяемые файлы

- `services/param_catalog.py` — ParamSpec (B-7), запись температуры (B-8), группа гейта (B-1), новая вкладка (B-11).
- `services/chat_params.py` — без изменений (get_chat_param существующий; B-2 использует).
- `services/summary_aliases.py` — + build_alias_resolver (B-12).
- `services/user_relations.py` — get_relations_snapshot += aliases-параметр (B-13).
- `services/direct_chat_service.py` — :1011 B-2; инжект relations (B-13).
- `web/api/chat_lore.py` — :555-556 (B-13).
- `web/api/routes.py` — items += options (B-9), валидация 422 (B-9, обе ветки).
- `web/app.js` — TABS += people_names; (B-11).
- `web/index.html` — select-ветка (B-10), (мест).
- `scripts/backfill_104_chat_flags.py` — НОВЫЙ (B-4).
- Тесты — see §4/§5.

## 4. Критерии приёмки

| AC | Критерий | Проверка |
|----|----------|----------|
| AC-B1 | `get_by_pg_key('flags.chat_context_budgets_enabled').group == 'limits_chat_budgets'`; локация pg-ключа не изменена; каталог 383/71/359 | юнит (test_param_catalog зелёный) |
| AC-B2 | Юнит-тесты резолва: (1) без override — hot.get (как сейчас); (2) override true/false — из overrides; (3) ЛС — override/глобал (наследование); (4) мусор-значение → fallback-путь; direct_chat_service:1011 — чтение через chat_param | test_chat_params + test_direct_chat |
| AC-B3 | Скрипт идемпотентен; записывает только один override для -1002661910336; повторный прогон — no-op; другие чаты/глобальные дефолты — без изменений | test_scripts_backfill_104 + dry-run |
| AC-B4 | Реестр read-путей в отчёте фичи (для F-5) | отчёт @Builder (T-993) |
| AC-B5 | Спека ParamSpec: options/labels None по умолчанию; старые записи без widget — как раньше; `test_widget_keyvalue_on_summary_aliases` обновлён (допустимые: ""/keyvalue/select) | test_param_catalog-расширение |
| AC-B6 | GET /api/config отдаёт select_options/labels; POST валид → 200+персист; невалидная опция → 422 (обе ветки) | test_webapp_api + тест-контракт |
| AC-B7 | На «Лимитах» (группа «Температура ответов») — выпадающий список (маркер select в HTML); float-поля — обычные поля; `node --check` clean | test_webapp_nav_disclosure_ui-маркеры |
| AC-B8 | Смена пресета → POST → toast «Сохранено»; reload — выбранное значение | live/T-1005 + api-тест |
| AC-C1 | `tab_group_ids('people_names') == {limits_user_aliases}`; зеркало TABS; на «Лимитах» ключа нет (негатив); 383/71/359 | юнит + маркер (T-998) |
| AC-C2 | Каскад: группа → override чата → глобальные; ЛС → свои → глобальные; summary_enabled-гейт не задет (инжект/список) | тесты каскада (T-999) |
| AC-C3 | Переопределение для -1002661910336/ЛС уходит в overrides (X-Chat-Id); кнопка сброса → глобальное; видимость по canEditConfig (DM — is_dm_owner) | test_webapp_dm_ui/макеры + live |
| AC-C4 | Каскад-тесты (alias→nickname→username→''), R16, username-без-@ — зелёные | T-1001 |
| AC | Полный pytest 0 failed; node --check; git diff --check; live-акт алиаса (T-1005): алиас из админки → список участников/саммари/граф использует новое имя (новые записи; пров. /debug_config + живой чат; «ждёт человека») | T-1002…T-1005 |

## 5. Негативные тесты (что НЕ сломать)

- **REGISTRY 383 / 71 группа / Settings 359** — ноль новых ключей/групп (запись температуры — только widget-поля; MED-017).
- **SQLite v8, роутеры bot.py, каноны промптов (R9/PREV/R46-2)** — без дифов.
- **F-14-гейт `chat_summary_enabled`** — не изменён (саммари default-off для ЛС — остаётся; наши алиасы — НЕ зависят).
- **R10.3-5-асимметрия** — НЕ расширяем: алиасы/бюджеты — наследование (не fail-closed); только саммари остаётся исключением.
- **R10.3-1 (models.* DM)** — вне скоупа B (не усугублять; не чинить — отмечено).
- **R17** — алиасы не секреты; KV-редактор — без изменений маски.
- **F-1 T-650/651/652** — `can_edit_param`/касты — без дифов нами; T-651/652 унификация кастов — учтена (select str каста не требует).
- **BYOK/R16** — каскад имён без регресса («id никогда»).
- **test_param_catalog** — 383/71/359 — без изменений; **маркеры MED-022** — перечисленные обновлены.
- **Вкладка «Лимиты»** — после ухода limits_user_aliases — остаётся ≥1 basic (limits_temperature basic; AC-B1-тест D-фичи).

## 6. Границы (вне скоупа)

- Множители бюджетов (CHAT_BUDGET_*_RATIO, CHAT_CONTEXT_BUDGET_TOKENS) — НЕ делаем per-chat (фича G: overrides там получит полный набор; здесь — ТОЛЬКО флаг).
- R10.3-1-фикс (DM models.* read-only) — отложен (Scanner-minor; кандидат следующего раунда).
- «Реальный эффект»-верификация на историо-графике — вне (новые записи только).
- Новые RBAC-секции — не вводятся.
- Полный LLM-лог (HIGH-004) — вне.

## 7. Риски и блокеры

| Риск | Митигация |
|------|-----------|
| **Риск B-1 (главный)**: резолв алиасов строится per-call (async get_chat_param → кэш 120с) — в hot-путях инжекта (direct_chat_service) это +1 обращение к кэшу на ответ (не LLM) — приемлемо (кэш in-memory, TTL 120с); при отсутствии кэша/профиля — fail-open глобальные (существующий путь). | fail-open везде: build_alias_resolver никогда не бросает (try/except → global AliasResolver). |
| **Риск B-2**: ЛС-алиасы — `ensure_scope_profile` не вызван при чтении (кэш пуст → {} → глобальные) — ОК (наследование). | Наследование (не fail-closed) — профиль не нужен для чтения. |
| **Риск B-3**: бэкфил скрипта на проде — перезапишет существующий override при неаккуратной логике; конкурентная запись (другой админ). | Правило: запись ТОЛЬКО при отсутствии ключа в overrides (get_all_chat_params → check); expected_updated_at=None (последняя-побеждает, только для этого ключа) — идемпотентен; повторный прогон no-op. |
| **Риск B-4**: select-опции — уход от захардкоженных значений в каталоге (если опции поменяют, старые значения в пer-chat overrides станут недопустимыми? значения в bot_settings остаются как есть; при валидации 422 — НЕ регрессия: старые строки в overrides остаются; select-валидация только на записи). | опции стабильны; доп. guard: values не в наборе — 422 только на записи — задокументировано. |
| **Блокер**: F-1 ДО B (T-648 атомарный POST уже в master — порядок из backlog: F-1 реализуется ДО фич B/G; B-спека опирается на атомарный POST). | Проверка на старте: ветка per-chat POST умеет «частичный успех исключён» (routes.py:413-417). |

## 8. Зависимости

- До: F-1 (T-648/T-651/T-652/T-654), A (атомарность для new tab). После: F (relations-каскад — per-chat алиасы используются в каскаде участников), H (каскад имён — после B, двойные диффы web/api/chat_lore.py), G.
- F-5 (read-path audit) — ПОСЛЕ G+B (реестр B-6).
- F-6 → SUPERSEDED_BY(round10.4): аудит каскада → H; live-эффект → T-1005 (здесь); верификация владельцем — отчёт.
