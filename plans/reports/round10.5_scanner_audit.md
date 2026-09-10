# Round 10.5 Scanner Audit (tma-relume-redesign: Relume TMA redesign)

> Аудит 2026-09-10. HEAD `0bdf272` (10.4) + рабочее дерево 10.5 (38 записей git:
> 24 modified + 14 untracked; +2391/−159 по отслеживаемым файлам, без учёта новых).
> Проверено: спеки `plans/features/tma-relume-redesign/` (spec v3, design-project v5,
> tasks, reference-analysis), диффы всех изменённых файлов, полные тексты
> `services/key_history.py`, `services/config_cache.py` (новые методы),
> `services/status_service.py` (`_resolve`/`llm_registry`/`_build_llm_card`),
> `services/param_catalog.py` (`_MODELS_PG_ONLY`), `web/api/access.py`
> (`param_permissions_list`), `web/api/routes.py` (roles rename/delete +
> key-history), `web/app.js` (hash-роутер, scope-switcher, матрица, key-avail),
> `web/index.html` (токены, градиенты, navbar/hub, scope-dropdown, матрица,
> key-avail, self-host ассеты), `scripts/build_font_subset.py`, новые `tests/*` и
> `tests/js/routing_test.js`.
>
> **pytest: 4959 passed, 1 warning** (55.6s; база 10.4 = 4860 → **+99**).
> **`node --check web/app.js` / `tests/js/routing_test.js` — clean.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Новый JS-unit (`tests/test_webapp_js_unit.py` → `tests/js/routing_test.js`) реально
> прогоняется node: hub-aware RBAC-гейт D1 + scopeEpoch-отбрасывание D2 подтверждены.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **387 / GROUPS 74 / Settings 359** | `len(REGISTRY)==387`; `len(GROUPS)==74`; `len(dataclasses.fields(Settings))==359` (не `dir()`) | ✅ |
| **TABS ↔ TAB_RULES** | `test_frontend_tab_mapping` + `test_webapp_parity_smoke::TestCatalogParity` зелёные; `matrix`-секции покрывают 359 категорийных | ✅ |
| **Ноль новых PG-DDL** | `services/database.py` НЕ изменён (SQLite v8); в диффе нет `CREATE/ALTER TABLE/ADD COLUMN/PRAGMA user_version`; `config_cache.rename_role/delete_role` — только DML | ✅ |
| **bot.py router order** | `bot.py` НЕ в git-диффе (не тронут) | ✅ |
| **media/ не трогать** | `git status -s media/` пусто; `.gitignore` содержит явный комментарий «media/ — НЕ трогать» | ✅ |
| **R17 (секреты)** | `key_history` allowlist (`module_id/provider/model/samples{ts,ok,http_status}`), `base_url`/`last4`/ключи НЕ пишутся/не отдаются; `/api/status` key={configured[,last4]} | ✅ |
| **R16 (ID не имя)** | `services/user_relations.py`, `web/api/chat_lore.py` НЕ изменены | ✅ |
| **Нет секретов в staged/untracked** | `git diff --cached` пуст; `.env` ignored; скан новых файлов (sk-/gsk_/AIza/bot-token) — чисто | ✅ |
| **Font subset / иконки** | Независимо: 26/26 PUA-кодов в `app.js ICONS` совпадают с код-каноном (`derive_pua_codepoints`) И присутствуют в `material-symbols-rounded.woff2` (26 записей cmap, лишних нет). Субсет 13 428 B, `wOF2`, LICENSE Apache-2.0, источник 5.36 МиБ gitignored | ✅ |
| **DOMPurify** | self-host `dompurify-3.4.15.min.js` (29 369 B, баннер 3.4.15, sha256 `f263b053…`), fail-CLOSED эскейп при отсутствии санитайзера | ✅ |
| **Hardcode-модели/URL** | Активных литералов нет: STT-модели/base_url читаются `hot.get(pg_key, <прежний литерал>)`; литералы остались только документированным дефолтом (safe migration, `model_source='code'`\|\|`'config'`). Совпадения в `tests/` и `plans/*` не runtime | ✅ |

## 2. Новые находки раунда 10.5

### [R10.5-1] severity: minor — BackButton не переинициализируется после позднего Telegram-контекста (`ready`)
**Файл**: `web/app.js:775` (`mounted` → `this.initBackButton()`), `:816-819`
(`onEvent('ready' → retryInitData)`), `:1767-1777` (`initBackButton`).
**Суть**: Комментарий в коде прямо допускает, что Telegram-контекст может появиться
ПОЗЖЕ готовности WebView (`ready`). `initBackButton()` вызывается один раз в `mounted`;
`retryInitData()` (по `ready`) дёргает `setTab`, но НЕ переинициализирует BackButton.
Если `Telegram.WebApp.BackButton` становится доступен только к `ready`, то
`backNative` остаётся `false` (рендерится in-app fallback «←», `routeDepth>0 &&
!backNative`), а `_backApi.onClick(goBack)` не регистрируется → нативная/системная
кнопка «назад» на вложенном экране не вызывает `goBack()`. В стандартном TMA
BackButton есть сразу, поэтому риск низкий, но дыра реальная.
**Ремедиация**: вызывать `self.initBackButton()` в `ready`-хендлере под guard'ом
повторной регистрации (флаг `_backOnClickBound`), т.к. `onClick` без guard'а
накопит второй колбэк (тест `test_backbutton_onclick_registered_once` этого не поймает,
он считает литералы в исходнике).

### [R10.5-2] severity: minor — DM: `per_chat=False` `models.*` редактируемы во фронте, но сервер даёт 422 (класс R10.3-1, расширен на 4 новых ключа)
**Файл**: `web/app.js` `canEditConfig` DM-ветка (`if (this.isDmCtx() && cat !== 'keys') return true;`) +
`web/api/routes.py` POST-валидация уровня чата;
`services/param_catalog.py:_MODELS_PG_ONLY` (`models.groq_base_url`,
`models.groq_transcribe_model`, `models.openrouter_base_url`,
`models.openrouter_transcribe_model` — подтверждено `per_chat=False`).
**Суть**: OD11/OD16 вводят эти 4 ключа как UI-редактируемые. В ЛС-скоупе DM-владелец
видит тумблеры/инпуты/«Сохранить» активными (`canEditConfig` DM → true для всего, кроме
`keys.*`), но POST `/api/config` с `X-Chat-Id=ЛС` на `per_chat=False`-ключ возвращает
422 «ключ нельзя переносить на уровень чата». Спека F-14 §6.2 требует `models.*`
**read-only** в DM. Сервер защищён (не security-дыра), но UX-шум и несоответствие спеке;
ранее R10.3-1 касалась 29 `models.*`-ключей, теперь их **33** (`+4`).
**Ремедиация**: в DM-ветке учитывать `item.per_chat` (передавать item, а не key) либо
скрывать/дизейблить `per_chat=False` в DM.

### [R10.5-3] severity: info — `/api/status/key-history` открыт любому авторизованному TMA-юзеру
**Файл**: `web/api/routes.py:1080-1092`.
**Суть**: Эндпоинт зависит только от `get_tma_user` (без `requires_permission`),
как и `/api/status` (RBAC-исключение 84.11) — то есть НЕ регрессия периметра.
Отдаёт `module_id/module_title/provider/model/samples{ts,ok,http_status}` для ВСЕХ
ключей (секретов нет, R17 соблюдён). Рядовой пользователь видит имена моделей/
провайдеров и коды доступности. Если это нежелательно — ограничить permission'ом
(напр. `section.status`). Зафиксировано для владельца.

### [R10.5-4] severity: info — мёртвый код и широкий deny-list в `services/key_history.py`
**Файл**: `services/key_history.py:38` (`_ALLOWED_PROVIDER_KEYS` не используется —
payload строится явно), `:40-43` (deny-list содержит общий `"token"`, что может
ложно срабатывать на безобидных строках; используется только в `has_forbidden_content`
для тестов/QA, не в runtime-записи). Косметика/гигиена.

### [R10.5-5] severity: info — `rename_role` без optimistic-защиты: гонка даёт 500, а не 409
**Файл**: `services/config_cache.py::rename_role` (INSERT…SELECT + UPDATE + DELETE в
одной транзакции) + `web/api/routes.py::rename_role_endpoint` (проверка
`new_name in cache.roles()` ДО записи).
**Суть**: При конкурентном создании роли с тем же именем между проверкой и `INSERT`
сработает unique violation → необработанное исключение → HTTP 500 вместо 409. Окно
микроскопическое, вероятность низкая; `delete_role` аналогично не идемпотентен по
состоянию гонки. Info.

### [R10.5-6] severity: info — `setMenu` — мёртвый код (pre-existing, НЕ регрессия 10.5)
**Файл**: `web/app.js:1982`. `setMenu` не вызывается нигде (`index.html` использует
`openTab`/`navTo`; проверено `git show HEAD:web/index.html` — и до 10.5 не вызывался).
Стоит удалить при случае; к 10.5 отношения не имеет.

### [R10.5-7] severity: info — синхронный файловый I/O в async-пути status
**Файл**: `services/status_service.py:316` (`key_history.maybe_save()`) +
`services/key_history.py:152-177`. Снимок маленький (≤288 сэмплов × ≤4 провайдера),
порог 5 мин, `os.replace` атомарен. Блокировка event loop пренебрежима. Info.

## 3. Проверенные области — вердикты (логических дыр не найдено)

1. **Hash-роутер (`route` — источник истины)**: `normalizeRoute` трактует маршрут
   ТОЛЬКО при `indexOf('#/')===0` (launch-hash `#tgWebAppData…` игнорируется);
   `getInitData()` кэширует initData ДО `initialRoute()`; `hashchange` — единственный
   «применитель»; `applyRoute` гейтит hub по `hubVisible` (≥1 видимая карточка), не-hub —
   по `canViewTab`; запрещённый раздел → `replaceState('#/')` (без лишней history);
   `goBack` идёт по `routeParent`, без `history.back()`/`popstate` (петель нет);
   `_backApi.onClick` регистрируется ровно 1 раз. RBAC-гейт серверный + фронтовый —
   UI не ослабляет проверки.
2. **Scope-switcher (OD7/T-1127) + R10.4-2**: `setActiveChat` инкрементит `scopeEpoch`,
   чистит `chatLoreProfile/SelectedId/History/409/gateInfo/chatAdmins/permPicker`,
   `chatRelations`, а на вкладке `relations` сразу перезагружает участников нового чата;
   все chat-scoped загрузчики (`loadConfig/loadKeyStatus/loadChatAdmins/loadGateInfo/
   loadLocalAdmins/loadProfile/loadRelations/loadStatus`) снимают epoch до `await` и
   сверяют в success/catch/finally (R1/R2/R3 — отбрасывание устаревших ответов и ошибок).
   Реальный JS-тест подтверждает.
3. **Матрица ролей (OD10)**: `param_permissions_list` обходит весь `REGISTRY`
   (пропускает `category is None`), добавляет `tab/tab_title/group/group_title/group_order/
   category/title/secret`; фронт группирует по config-вкладкам (`TAB_SECTION_ORDER`),
   read/write по `user/moderator/local_admin`, запись ⊃ чтение на сервере
   (`_normalize_perms` union). Только global admin (403 иначе).
4. **Rename/Delete ролей (OD15)**: superuser защищён (по имени `admin/global_admin/
   superuser` ИЛИ `role_type=='global_admin'`) → 403; встроенные (`role_type` задан) → 409;
   занятые (`role_usage>0`) → 409; последняя wildcard (`guard_last_wildcard`) → 409;
   каскад `rename_role`/`delete_role` чистит имя из `param_permissions` — висячих прав нет.
   UI: `canEditRole` disabled для superuser/builtin + hint.
5. **Key-availability (OD8/OD12/OD19)**: `llm_registry` data-driven
   (`hot.get(pg_key, <литерал>)`, `model_source`); `KeyHistory` — allowlist-снимок,
   атомарная запись (`tmp`+`os.replace`), права 0o600/0o700 (Windows best-effort),
   fail-open на битом/отсутствующем файле, ring ≤288, upsert 5-мин слота, персист через
   рестарт. `conftest` перенаправляет singleton в temp (нет загрязнения `var/`).
6. **Безопасность фронта**: DOMPurify self-host pinned + fail-CLOSED; `v-html` только
   для info; удалён hardcode `#8b5cf6/#3b82f6/#2b2b40`; `@property --grad-angle
   inherits:false` + `prefers-reduced-motion`/`prefers-contrast` выключают анимацию;
   текст/иконки на плотных подложках (WCAG-подслой).
7. **DM/RBAC**: hub-навигация фильтруется `canViewTab`; DM видит config-вкладки кроме
   `permsoc`; `#/access`-hub для DM скрыт; матрица — только global; key-history —
   только авторизация (см. R10.5-3).

## 4. Итог 10.5

- **Блокеров: 0. Major: 0.** Minor: **2** (R10.5-1 BackButton re-init; R10.5-2 DM
  `models.*` 422 — класс R10.3-1, расширен). Info: **5** (R10.5-3…R10.5-7).
- Все — UX/гигиена/edge-case; **для мержа не обязательны**, но R10.5-1 и R10.5-2 —
  точечные ремедиации, рекомендуются в follow-up.
- Инварианты соблюдены: каталог **387/74/359**; TABS↔TAB_RULES; **ноль PG-DDL**;
  SQLite **v8**; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся;
  R16/R17 держатся; иконки/шрифт и DOMPurify верифицированы.
- pytest **4959 passed / 0 failed** (1 pre-existing Starlette-deprecation warning +
  «WARNING: closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение, не регресс).
- `node --check` clean; `git diff --check` clean.

*Round 10.5 report generated by Scanner on 2026-09-10*
