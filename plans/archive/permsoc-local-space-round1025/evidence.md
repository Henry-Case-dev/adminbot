# F7 `permsoc-local-space-round1025` — evidence.md (Step 4 @Builder)

> **Baseline:** HEAD `551847d` (== `origin/master`), `APP_VERSION` **2.58.14**,
> pytest **8334 passed / 1 skip / 5 env**, JS **37/37**, каталог
> **459/98/96/21/418**, SQLite **v12** (Δ DDL=0).
> **После F7:** `APP_VERSION` **2.58.15**; pytest **8369 passed / 0 failed**;
> JS **38/38**; Δ каталога=0; Playwright матрица `failures: 0`.
> **Fix-итерация (Needs Fixes: H-F7-1/M-F7-2 + L-F7-3/L-F7-5):** pytest
> **8372 passed / 0 failed**; JS **38/38**; матрица `failures: 0` (включая
> реальный no-chat сценарий и проверки подгрупп/list-виджета); Δ каталога=0;
> Δ DDL=0.
> **Fix-итерация 2 (Needs Fixes: H-F7-7/L-F7-8/L-F7-9):** pytest
> **8374 passed / 0 failed**; JS **38/38** (включая round-trip типа ID-списков);
> матрица `failures: 0`; Δ каталога=0; Δ DDL=0.
> **ADR:** `adr-1025-20-permsoc-local-space-and-server-gates.md` (D1–D7).
> **ТЗ:** `plans/current_task.md` §60–§67 (+ §70/§71/§73/§74) — untracked, не
> изменялся, не коммитится (R17/R18).

## Изменённые / новые файлы

**Backend:**
- `services/feature_gates.py` — `ALL_GATED_FEATURES` += `permsoc_reactions`,
  `permsoc_schedule`; `DEFAULT_BY_FEATURE` = True (baseline), `FLAG_KEYS` пусто,
  `HEAVY`/`MASTER_FALLBACK_KEYS` не тронуты.
- `services/permsoc.py` — `BLOCK_FEATURES`, `block_enabled(chat_id, block)`
  (kill-switch → True; иначе `gates_enabled`; исключение → False), новый
  `PermsocBlockGate(BaseFilter)`; существующий `PermsocGateFilter` не изменён.
- `services/goodmorning_scheduler.py` — `_tick`: per-chat проверка
  `block_enabled(chat_id, "schedule")` перед отправкой (OFF → `continue`).
- `handlers/{war_alert,common,vasya,slavik,alan,alan_greeting}.py` — добавочный
  `PermsocBlockGate("reactions")` (у alan — рядом с master `PermsocGateFilter`).
- `web/api/gates.py` — все `permsoc*` → `who_can_toggle="global"`, PUT только
  global admin (`startswith("permsoc")`).
- `web/api/routes.py` — `ui_flags["PERMSOC_BLOCK_GATES_ENABLED"]` (bool).
- `config/settings.py` — env-only `ClassVar PERMSOC_BLOCK_GATES_ENABLED` (default
  ON, вне каталога) + `APP_VERSION` 2.58.14 → **2.58.15**.
- `README.md` — строка версии `v2.58.15`.

**Frontend (zero-build, CSP-safe, без новых библиотек):**
- `web/app.js` — `PERMSOC_OWNER_BLOCKS` 5→6 (`slavik/kostik/olya/mimic/reactions/
  schedule`; «Общее/Мастер» убран), key-level `keys` §62–§67; `PERMSOC_BLOCK_SUBGROUPS`;
  `PERMSOC_LOCAL_KEYS`; guard в `persistItems` и `saveConfigItem` («PERMsoc-ключ
  не пишется в global», reason `permsoc-global`); `_permsocOwnerGroups` — без чата
  `[]`, незнакомый ключ вне блоков (нет «свалки»); `permsocBlockGateOn`,
  `canToggleMaster`, `permsocOwnerSubgroups`; `permsocOwnerOn/canToggleOwner/
  toggleOwner` — gate-ветка + одна мутация (только `toggleKey`/`gate`);
  `permsocProbToPercent/permsocPercentToProb/saveKostikProbability` (§63).
- `web/index.html` — scope-заголовок «PERMsoc · Только этот чат» + `.scope-tech`
  (`chat_id`); empty-state «PERMsoc работает только для конкретного чата…»;
  мастер-уровень §61 (тумблер + read-only сводка 5 модулей, `permsocModuleBadge`);
  удалён дефектный текст `:1294-1298` и owner-блок `common`; %-ветка виджета
  вероятности Костика; **fix H-F7-1:** витринные подгруппы owner-блока
  (`div.permsoc-subgroup` через `permsocRenderItems(grp)`); **fix M-F7-2:**
  `list-editor` с `variant='ids'` для списков ID Оли.
- `tools/ui_round1025_matrix.py` — маршрут `#/permsoc` + `PERMSOC_PROBE_JS`/
  `_permsoc_failures` (6 блоков, заголовок, мастер, тумблеры ≥44px, нет overflow).

**Тесты (атомарно с кодом):**
- new `tests/js/round1025_f7_permsoc_local_test.js` + регистрация в
  `tests/test_webapp_js_unit.py`.
- new `tests/test_permsoc_f7_round1025.py` (16 тестов).
- new `tests/test_webapp_f7_round1025.py` (12 маркеров/инвариантов).
- маркеры версии 2.58.14→2.58.15: `test_webapp_{hotfix6..10}_round1025.py`,
  `test_webapp_f6_round1025.py`, `test_scope_selector_round1025.py`,
  `test_webapp_design_tokens_round1025.py`, 4× `tests/js/round1025_hotfix{7,8,9,10}*`.
- `tests/test_webapp_round109_ui.py` — owner-блок `common` → мастер-уровень
  §61 (marker-обновление).

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис JS | `node --check web/app.js` | OK |
| JS-юниты (real node) | все `tests/js/*.js` (38 файлов) | **38/38 OK** |
| pytest (полный) | `.venv\Scripts\python.exe -m pytest -q --timeout=120` | **8369 passed, 0 failed** |
| Playwright матрица §71 | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов × маршруты, включая `#/permsoc` chat-scope: 6 блоков, заголовок, мастер, тумблеры, нет overflow) |
| `git diff --check` | `git diff --check` | 0 (только LF/CRLF warning) |
| Δ каталога | `tests/test_webapp_f7_round1025.py::test_catalog_delta_zero` | 459/98/96/21/418 — **0** |
| Δ DDL | `git status services/` | миграции/схема не тронуты → SQLite v12, **0** |

## Покрытые сценарии (D6)

- **«Локальные не перезаписываются глобальными»** / «нет записи PERMsoc в
  global»: `test_webapp_f7_round1025` (маркеры) + JS `persistItems`/`saveConfigItem`
  guard (2 прямых вызова: запроса нет, reason `permsoc-global`).
- **«Без чата блоков нет»**: JS `blocksOf(false) === []`.
- **«Ключ ровно в одном блоке»** (partition 60 ключей §62–§67): JS-тест.
- **«OFF блока сохраняет дочерние»**: JS `toggleOwner` — ровно 1 мутация,
  дочерний `reactions.slavik_user_id` не изменён.
- **«Фон прекращается»** (goodmorning no-send): `test_goodmorning_tick_skips_disabled_chat`
  (relay вызван только для ON-чата) + baseline all-sent.
- **block_enabled**: gate OFF/ON, kill-switch OFF→baseline, fail-open OFF, фильтр
  без чата.
- **Единицы §63**: round-trip 0/0.5/1 ↔ 0/50/100 %, клип границ; `saveKostikProbability`
  пишет серверный формат.
- **Deprecated** `reactions.slavic_photo_path` — в блоке Славика (JS-тест).
- **RBAC** `permsoc*` = global: маркеры + `test_who_can_toggle_permsoc_family_global`.
- **CSP/zero-build**: правки только `web/app.js`/`web/index.html`; новых CDN/
  inline/eval/библиотек нет.

## Ограничения / честные пометки

1. **Δ каталога=0 → §65-названия отдельных ключей** не переименовывались
   (`services/param_catalog.py` НЕ менялся по ограничению). Витринные русские
   названия подгрупп §62–§67 — в JS-константе `PERMSOC_BLOCK_SUBGROUPS`;
   подписи ключей берутся из существующих `title_ru` каталога (семантически
   совпадают с §65: «Кого передразнивать», «Мимикрия Лёхи» и т.д.).
2. **Playwright «нет чата»** (L-F7-3, fix): штатный прогон маршрутов в матрице
   авто-выбирает первый чат (особенность харнесса) → прежняя проба
   `permsoc_global` вакуумна. Добавлен **отдельный контекст** с
   `/api/access/chats = []` (`permsoc_nochat`, вьюпорт 390×844): подтверждено
   `ownerCount=0`, `hasNoChatBanner=true`, подгрупп/мастера нет. Дополнительно
   JS-юнит `blocksOf(false) === []`.
3. **dead-page join** (`services/scheduler.py`, `flags.dead_page_post_on_join`) —
   процессный планировщик без per-chat хендлера; в объём `PermsocBlockGate` не
   включён. **L-F7-4/L-F7S-2 — owned follow-up**: решение о расширении охвата
   (gate) или сохранении as-is — за @Architect (не блокер F7; раскрыто, не
   скрытый дефект).
4. `plans/current_task.md` не изменялся и не коммитится (R17/R18); теги/бэкапы/
   `stash@{0}` не трогались.
5. **L-F7S-1 — осознанный долг (не блокер).** Серверный global-путь
   `POST /api/config` не отклоняет PERMsoc-per-chat-ключи: запрет записи
   PERMsoc-ключа в global реализован **на клиенте** (`persistItems`/
   `saveConfigItem`), как и зафиксировано в **ADR-1025-20 D1** («guard записи:
   попытка записать PERMsoc-ключ в global отклоняется»). Серверного denylist
   в ADR-1025-20 D1 **нет** — это осознанный follow-up (hardening), требует
   global admin; не регрессия F7.

## Fix-итерация (Step 5→4, после `review.md` Needs Fixes)

- **H-F7-1 (High) — подгруппы §62/§64/§66 теперь РЕНДЕРЯТСЯ.**
  `PERMSOC_BLOCK_SUBGROUPS` больше не мёртвый код: `{title, keys}` по блокам;
  новый метод `permsocRenderItems(grp)` вставляет псевдо-заголовки
  `{__subheader}` и раскладывает `basicItems` owner-блока по §-подгруппам;
  шаблон `web/index.html` рендерит `div.permsoc-subgroup` с русскими
  заголовками (Основное/Контент/Мимикрия/…, Источники, Приветствия/…, Рассылка/…).
  Для не-owner вкладок — прежний плоский список (регресс исключён).
- **M-F7-2 (Medium) — списки ID Оли структурированы.** Presentation-оверрайд
  `PERMSOC_LIST_WIDGET_KEYS` + `_normalizeConfigItems` → `widget='list'` для
  `reactions.olya_saveasbot_channel_ids`/`_user_ids` (Δ каталога=0); компонент
  `list-editor` получил `variant='ids'` (подписи «ID», не «фразы»; дефолт
  Костика сохранён в шаблоне). `listEditorProps(item)` в обеих ветках шаблона.
- **L-F7-3** — добавлен no-chat сценарий в матрицу (см. пометку 2).
- **L-F7-5** — `test_all_four_owner_blocks_always_render` →
  `test_all_six_owner_blocks_always_render` (+ коммент «6»).
- **Харнесс:** `tools/ui_round1025_matrix.py::_config_stub` теперь отдаёт
  `key = spec.pg_key` (как реальный `/api/config`), иначе витринные подгруппы
  не матчатся по pg_key; проба `PERMSOC_PROBE_JS` проверяет `subgroups` и
  `olyaListStructured` (list-editor/без textarea).

**Прогоны fix-итерации (факт):** `node --check web/app.js` OK; все
`tests/js/*.js` **38/38 OK** (F7-юнит → `F7-PERMSOC-LOCAL-UNIT-OK`, добавлены
пробы подгрупп §62/§64/§66/§67 и list-виджета Оли); `.venv\Scripts\python.exe -m
pytest -q --timeout=120` → **8372 passed / 0 failed**; `tools/ui_round1025_matrix.py`
→ **failures: 0** (chat-scope: 24 подгруппы, Оля `{hasListBtn:true,hasTextarea:false}`;
`permsoc_nochat`: ownerCount 0, banner true); `git diff --check` → 0 (только
LF/CRLF warning); Δ каталога=0 (`param_catalog.py` вне диффа); Δ DDL=0
(миграции/схема не тронуты).

## Fix-итерация 2 (Step 5→4, после `review.md` итерации 2: H-F7-7/L-F7-8/L-F7-9)

- **H-F7-7 (High) — регрессия типов от M-F7-2 устранена.** `list-editor.save`
  коэрцировал всё в `String(...)`, поэтому сохранение списков ID Оли писало
  `["-100123","523131145"]` (строки), а сервер сравнивает
  `origin.chat.id`/`sender_user.id` (**int**) `in [...]` → `-100123 in
  ["-100123"]` = `False` → Оля-SaveAsBot молча перестаёт определяться.
  Добавлены `list-editor._numericList()` и `toStoredValue(s)`: для ключей из
  `PERMSOC_LIST_WIDGET_KEYS` чисто-числовые строки (`/^-?\d+$/`,
  `Number.isSafeInteger`) → `Number` (целое), нечисловые — строкой; `save`
  использует `toStoredValue` (fallback identity для «минимального» контекста
  юнит-тестов). Фразы Костика (`reactions.kostik_replies`) **не затронуты** —
  остаются строками. Серверные единицы/сравнение не менялись (правка только
  на границе записи).
- **L-F7-8 (Low) — текст лимита variant-зависим.**
  `web/index.html` (`#list-editor-tpl`): «Лимит {{ maxRows }} фраз» →
  `Лимит {{ maxRows }} {{ variant === 'ids' ? 'ID' : 'фраз' }}`; для списков
  ID — «Лимит 100 ID», дефолт Костика («фраз») сохранён.
- **L-F7-9 (Low) — точная атрибуция в §5.** Убрана формулировка «сервер-scope —
  клиентский» (в ADR-1025-20 D1 её нет); указано, что D1 фиксирует **клиентский
  guard записи** («попытка записать PERMsoc-ключ в global отклоняется»), а
  серверный denylist — **осознанный follow-up L-F7S-1**, не требование D1.

**Тесты (атомарно с кодом):**
- JS `tests/js/round1025_f7_permsoc_local_test.js` (H-F7-7): round-trip типа —
  `value=[-100123, 523131145]` → `sync` даёт строки для полей → `save` кладёт
  **числа** в `item.value` и на сервер; `saved.includes(-100123) === true`,
  `saved.includes('-100123') === false`; смешанный список (`'not-an-id'`,
  `' 42 '`) → `[523131145,'not-an-id',42]`; фразы Костика (`['привет','42']`)
  остаются строками.
- Python `tests/test_permsoc_f7_round1025.py::test_olya_saveasbot_list_type_comparison`
  (эмуляция серверного сравнения через реальный `OlyaVideoFilter`): при
  `hot.get(...) = [-100123, 523131145]` (после фикса) → `is_saveasbot=True`;
  при `["-100123","523131145"]` (старая строка-регрессия) → фильтр не
  срабатывает (`False`) — доказывает, что числовой тип обязателен.
- Маркер-усиление `tests/test_webapp_f7_round1025.py::TestOlyaIdLists`:
  `toStoredValue: function`/`Number.isSafeInteger` в JS и
  `{{ variant === 'ids' ? 'ID' : 'фраз' }}` в HTML.

**Прогоны fix-итерации 2 (факт):** `node --check web/app.js` OK; все
`tests/js/*.js` **38/38 OK** (`F7-PERMSOC-LOCAL-UNIT-OK`; маркер
`routing_test.js` сохранён — сигнатура `save` и порядок методов не менялись);
`.venv\Scripts\python.exe -m pytest -q --timeout=120` → **8374 passed / 0 failed**
(+2 серверных теста типа); `tools/ui_round1025_matrix.py` → **failures: 0**
(chat-scope: `ownerCount=6`, header/master true, 24 подгруппы, Оля
`{hasListBtn:true,hasTextarea:false}`; `390x844 permsoc_nochat`: `ownerCount=0`,
`banner=true`); `git diff --check` → 0 (только LF/CRLF warning); Δ каталога=0
(`test_catalog_delta_zero` зелёный, `param_catalog.py` вне диффа); Δ DDL=0
(`git status services/` — только `feature_gates.py`/`goodmorning_scheduler.py`/
`permsoc.py`, миграции/схема не тронуты).

## Handoff

- Реализация блоков **A–F (T-2924…T-2955)** завершена; чекбоксы обновлены.
- **Fix-итерация по `review.md` (H-F7-1 H, M-F7-2 M, L-F7-3, L-F7-5) выполнена**
  и провалидирована: pytest 8372/0, JS 38/38, Playwright failures:0, Δ DDL=0,
  Δ каталога=0.
- **Fix-итерация 2 по `review.md` итерации 2 (H-F7-7 H, L-F7-8, L-F7-9)
  выполнена:** тип-регрессия ID-списков Оли устранена (round-trip числа,
  серверное сравнение воспроизведено юнитом), тексты лимита и атрибуция ADR
  уточнены. Требуется **свежее независимое ревью** @Reviewer (T-2956).
- Не проверено: живой Telegram WebView/TMA (PENDING OWNER VERIFICATION,
  T-2961); Chromium ≠ WebView.
- `RESULT: F7 fix-итерация 2 (H-F7-7/L-F7-8/L-F7-9) — pytest 8374/0, JS 38/38 (round-trip типа), Playwright failures:0, Δ DDL=0, Δ каталога=0 @Orchestrator`.
