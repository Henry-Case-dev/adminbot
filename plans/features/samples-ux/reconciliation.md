# ADD-SAMPLES-UX — reconciliation и порядок работ (PM-SAMPLES-UX)

Дата: 20.10.2026 (вечер). Источник: `source-add-samples-ux-2026-10-20.md` (verbatim current_task L1794–1914, sha256 `e6153cf1…ad69`).
Код читался на фиксированном HEAD `9f37c15a` (дерево == HEAD по затронутым файлам; после `9f37c15a` менялись только CFG-06 фактчек-тесты). Карта: `requirements-map.json` (48 строк инвентаря + 28 требований из прозы = 76 строк, 64 required), граф: `slice-graph.json`. Plan-гейт: **EXIT 0** (`inventory=48 manual=28 errors=0`).

## (a) Что УЖЕ есть в коде — REUSED_EXISTING

| Существующее | Где (9f37c15a) | Что закрывает |
|---|---|---|
| Единая таблица `humor_samples`: seed_key, input/reply, technique (вкл. `expression_register`), tags, rudeness_level, source_kind, scope global/chat+chat_id, owner_approved, status active/archived, library_version, revision, sensitivity_flags, uses_count, approved_at, история (created/updated_by/at) | `services/mca_sample_library.py:62–103` (DDL v36), `:38–57` | Основа §1 «хранение в существующей таблице» и §6 (CRUD/архив/версии/A-B-ось уже есть); новых таблиц не нужно |
| CRUD с optimistic revision-conflict, approve, archive | `mca_sample_library.py:699–746` (`revision_conflict` 710–712), `:749–762` | §3 (редактирование/утверждение/архив) — серверная половина |
| Идемпотентные сиды: 18 юмор-черновиков + 12 регистра речи; повтор no-op по seed_key; владельческая правка строки не перетирается (без force) | `:185–320` (STARTER_SAMPLES), `:329–394` (EXPRESSION_STARTER_SAMPLES, теги `mode:*`), `:810–896` | Часть §3 семантики уже верна для **неправленых** сидов |
| Место вызова сидов — ровно одно: ручной админ-эндпоинт (автосида на старте/деплое/миграциях НЕТ) | `web/api/speech.py:2998–3029` (3017/3020) + тесты + `tools/ui_soul1_w4_dump_fixture.py:108` | §3 «проверить реальные места вызова» — ответ: 1 endpoint; риск неявного force на деплое отсутствует by design |
| Bounded детерминированный отбор юмора (1–3, ноль допустим, 0 LLM): diversity/recency/budget, честные причины `max_items/same_technique/not_diverse/budget_exceeded`, PII-скан, `expression_register` жёстко исключён из юмор-пути | `mca_sample_library.py:1105–1243`, `:1128–1132`, `:156–177`, `:979–1035` | §5 bounded/0 LLM/причины/PII — каркас готов |
| Отбор Expression по effective-режиму: ≤4, только owner-approved+active, причины `not_owner_approved / expression_examples_absent / expression_examples_disabled`, kill-switch | `mca_sample_library.py:899–968` | §5 «MAT только утверждённые effective-режима» — семантика уже есть (на тегах) |
| Маркированные блоки: `<Examples>` (юмор) и `<Expression_Examples mode="…">`; header P0 «вся пользовательская речь, без жанровых исключений; цитаты как есть; „без мата" на ответ переопределяет частоту» | `mca_sample_library.py:142–153,1263–1278`; `services/mca_expression.py:110–123,132+`; реестр `services/prompt_registry.py:846–860` | §5 блоки и §2-скоуп (все жанры) уже соответствуют; менять нужно только тексты режимов |
| API примеров: list/create/update/approve/archive/delete/seed/policy/**why** | `web/api/speech.py:2749,2861,2906,2934,2956,2978,2998,3032,3066–3099` | §4/§5 серверная база; `why` уже отдаёт selected/excluded с причинами |
| UI-каркас секции «Примеры» внутри «Речь и характер»: toolbar (фильтры приём/статус/поиск), меню с «Заводская подборка (18+12)», карточки, инструмент «Почему выбраны именно эти примеры», guard чат-scope | `web/index.html:8333–8560`, `web/app.js:20554–20683`, `speech.py:2889` | §4 точка входа и меню существуют; переделывается экран, не раздел |
| Миграционный механизм (MigrationStep-цепочка) — место для v37 | `services/database.py:1686–1696, 2823–2827, 4043–4059` | §1 миграция и §3 «существующие механизмы миграций» |
| Тесты библиотеки/Expression: 20 (w4) + 36 (add_exp), вкл. сид no-op, изоляцию, байт-пины | `tests/test_soul1_w4_sample_library.py`, `tests/test_add_exp_expression.py` | Регресс-база §7 |

## (b) Что сломано / отсутствует (против контракта)

1. **Нет категорий** (`category` / явного `expression_mode` в DDL). Мат определяется тегами `mode:*` + `technique='expression_register'` (`mca_sample_library.py:332–335,347`) — ровно то, что §1 запрещает («нельзя определять режим исключительно произвольными тегами»). Валидация/выдача/отбор/Inspector категорию не знают.
2. **Нет миграции категорий** и правила для неоднозначных legacy (`other`).
3. **Нет tombstone**: `delete_sample` — жёсткий `DELETE` (`mca_sample_library.py:765–781`); повторный сид после удаления **пересоздаёт** строку (`:833,839–845`: row=None → create) — прямое нарушение §3 «отсутствие строки ≠ разрешение пересоздать».
4. **`force` не guardирован**: перезаписывает текст сида поверх владельческой правки (`:833–843`); сейчас не вызывается с force нигде, но явного подтверждения/экрана сравнения/restore-операции не существует. Нет «Посмотреть исходный» / «Восстановить исходный».
5. **Нет метки «Изменено владельцем»** (нет diff-vs-seed baseline); после удаления/архива состояние видно, но заводское происхождение правки UI не показывает.
6. **UI ≠ §4**: редактор — inline-форма прямо под списком со сырыми полями (`source_kind`, `rudeness_level`, теги) — `web/index.html:8399–8440+`; нет трёх вкладок категорий; счётчики смешанные общие («эталонов/черновиков», `:8342–8344`); нет отдельного экрана редактора; «Назад с предупреждением» нет; «Добавить пример» в toolbar (не плавающее — допустимо по §4.1.6, проверить перекрытие safe area).
7. **Нет кнопки «Почему не используется?» на карточке** — есть общий инструмент по вводимому сообщению (`speech.py:3066`, `index.html:8525+`); причин последнего выбора из traces и честного «Нет данных о последнем выборе» нет.
8. **§2 тексты — прежние F3**: `services/mca_expression.py:72–83` (`PROFANITY_INSTRUCTIONS`) — владелец заменил формулировки (см. (d)).
9. Inspector/effective payload не маркирует категории блоков (после §1 — должен).

## (c) Пересечения с чужими картами (построчно)

**SOUL-1 `requirements-map.json`** (не модифицируется; ссылки):
- `SOUL-07.0/07.1` (строки карты ~2825/1229/1251: библиотека, таблица, сид-черновики) — **REUSE** механизма; **NEW**: поля категории/режима + миграция v37. Чужие acceptance не ломаются: сид остаётся черновиками, `humor_samples` остаётся единственной таблицей.
- `SOUL-07.2` (~1251–1273: отбор 1–3) — **REUSE** bounded-контракта; SU-FEWSHOT добавляет категорийность поверх, лимиты не трогает.
- `SOUL-07.3` (A/B, честные причины) — **REUSE**; по §6 технический A/B прячется в «Дополнительно» (UI-слой), ось не удаляется.
- `SOUL-10.1–10.6` (~3047–3192: каркас «Речь и характер») — **REUSE** секций/save-логики/scope; **NEW**: экраны списка/редактора примеров по §4. `SOUL-10.P3` (один Inspector) — **REUSE**, Inspector расширяется категориями блоков без второго Inspector.

**ADD-EXP `requirements-map.json`** (не модифицируется):
- `EXP-UI.OCC` (L00018) и `EXP-UI.FREQ` (L00019) — **конфликт текстов** (см. (d)). Остальные VERIFIED-строки остаются исторически верными на своего кандидата.
- `EXP-UI.MODES/INHERIT` — **REUSE** (названия «Эпизодически/Часто», inherit-семантика не меняются §2).
- `EXP-INSTR.FEWSHOT` (seed-механика, `not_owner_approved`) — **REUSE**; расширяется категорией «Мат» и persist-семантикой.
- `ADD-1.E7` (few-shot не хардкод, юмор-путь исключает expression_register) — **REUSE**, инвариант сохраняется (исключение переписывается на категорию, не на совпадение слов).
- `EXP-ACCEPT.CRITERION` (READY_FOR_LIVE, F4-матрица на 2.58.98) — **координация**: если SU-FEWSHOT меняет директивы до F4-прогона, матрица измеряет уже тексты §2 (пороги §4 те же). Порядок «F4-матрица → замена текстов» или наоборот решает Orchestrator в CFG-06-цепочке; в (e) отмечено как точка стыка.

**CFG** — пересечений по файлам с активной CFG-06 релизной цепочкой нет (см. (e)).

## (d) Конфликты §2 с байт-пинами F3 — что инвалидируется и как обновлять честно

Затрагивается при замене текстов occasional/frequent (off не меняется — «Не используй мат в собственной речи.» остаётся):

1. `services/mca_expression.py:72–83` — `PROFANITY_INSTRUCTIONS["occasional"|"frequent"]` → дословные тексты §2 (SU-TXT.EPISODIC/FREQUENT).
2. `tests/test_add_exp_expression.py:63–70` — константы-пины `OCC_LINE`/`FREQ_LINE`; `:216–227` — байт-ассерт словаря (t4a); `:245` — проверка запрещённых оборотов-единственных-правил (`BANNED_SOLE_RULE_PHRASES`, `mca_expression.py:127–130` — новые тексты чистые, прогнать); `:299` — рендер строки слоя. Все — обновить на §2, старые формулировки не должны остаться ни в одном пине.
3. `services/prompt_registry.py:1469` — `FACTORY_SET_SHA256_12 = "64ec1c60e278"`: директивы входят в factory-fingerprint (при прошлой F3-замене уже бампили, см. `plans/features/add-exp/evidence/unified-core/fix-r1.md:34`). После §2-замены — переутвердить штатной процедурой (`tools/_cfg02b_reissue_f8.py`), тесты `tests/test_soul1_registry_completeness.py:89–94` / `test_soul1_core_registry_api.py:277+` должны остаться зелёными. **Одновременный двойной bump недопустим** — согласовать с CFG-06 (e).
4. Леджер `plans/features/add-exp/evidence/directives-fix/` (green-exact, eval.json) — **исторический, не переписывать**: он честно фиксирует кандидата `1b23d4c9`. Честное обновление = новая evidence-запись samples-ux (байт-сверка §2 на новом кандидате); VERIFIED-статусы add-exp задним числом не разворачиваются — новые требования живут в samples-ux-карте (SU-TXT.*).
5. UI-подписи «Эпизодически / Часто» и `EXPRESSION_HEADER` (все жанры, «без мата» на ответ) — не трогаются: §2 меняет только формулировки двух режимов.

## (e) Порядок исполнения и параллельность с CFG-06

Граф (`slice-graph.json`, serial-цепочка — сознательно: общие файлы):

```
SU-MIGR → SU-SEED → SU-FEWSHOT → SU-UI → SU-ACCEPT
```

- **SU-MIGR** — категории+явный `expression_mode`, миграция v37, легаси-маппинг (требования SU-CAT.*, SU-0.AUDIT, SU-REG.NOSPRAWL).
- **SU-SEED** — tombstone, идемпотентность против seed/deploy/restart, force-подтверждение+экран сравнения, «Изменено владельцем», заводской просмотр/restore (SU-PERSIST.*, SU-FACT.*).
- **SU-FEWSHOT** — §2-тексты+байт-пины+F8-bump, категорийный отбор/блоки/Inspector, «Почему не используется?» (SU-TXT.*, SU-FS.*).
- **SU-UI** — экран списка §4.1, редактор §4.2, адаптивность §4.3 (SU-UI.*, SU-ED.*).
- **SU-ACCEPT** — сквозные offline-приёмки §7/§8, owner_live_checks-пункты, отчёт (SU-ACC.*, SU-7.*, SU-8.PLAN).

Присоединения серийные и честные: SU-MIGR/SU-SEED/SU-FEWSHOT вместе пишут `services/mca_sample_library.py` и `web/api/speech.py` — пересекающиеся write_scope закрыты dependency-рёбрами, `CAN_PARALLEL_WITH` между ними не заявляется. Внутри SU-FEWSHOT замена текстов технически независима от категорий, но выделение в отдельный слайс создало бы второго писателя в `mca_sample_library.py` — оставлено вместе.

**Параллельно с CFG-06**: write_scope CFG-06 (tests/test_factcheck_*, plans/features/cfg/**, релизные файлы) не пересекается ни с одним SU-слайсом → полосы могут идти параллельно. Две точки стыка для Orchestrator: (1) `services/prompt_registry.py` F8-bump — только один писатель за раз (не совмещать с любым CFG-bump в том же окне); (2) порядок «F4-матрица add-exp (2.58.98, старые тексты) ↔ SU-FEWSHOT-замена текстов» — определить до старта SU-FEWSHOT, чтобы леджер F4 остался сравнимым. Решение не PM-уровня — передано оркестратору, lanes не блокирует (SU-MIGR/SU-SEED можно начинать независимо).

## (f) Риски / вопросы владельцу

**Реальных Human Gate нет** — ожидаемо и по §7 (запрет новых гейтов), и по standing-правилу PET_PROJECT. Кандидатов в вопросы не выявлено: все развилки §1/§3 уже решены источником (хранение в существующей таблице; seed-семантика; force-модель).

Риски (не гейты):
- PG-путь миграции категорий: MigrationStep-цепочка исторически SQLite; §7 требует «по возможности» PostgreSQL-прогон — если PG-контур недоступен offline, честно зафиксировать в отчёте, не заявлять.
- Уже восстановленные после старых деплоев удаления (§3, строка 50) невосстановимы честно — только tombstone на будущее + управление текущими карточками; «исходные решения владельца» не выдумывать.
- Конфликт F4-матрицы и новых текстов — координационная, не продуктовая развилка (см. (e)).

## (g) Проверки

Все приёмки — **offline**: unit/integration на локальной БД, контрактные моки API, mock Telegram Bridge, browser E2E (portrait/landscape/desktop), offline effective payload/trace без отправок. Ноль live-отправок (SU-7.NOLIVE).

Кандидаты в `plans/owner_live_checks.md` (короткими пунктами, **не гейты**, `PENDING_OWNER_E2E`, пишутся в SU-ACCEPT):
1. MiniApp на реальном устройстве: три вкладки/редактор/заводские действия читаемы, клавиатура и safe area не перекрывают форму (техническая половина — browser E2E, живой клиент — владелец).
2. Живой цикл «правка/удаление заводской карточки → штатный деплой/рестарт → правка сохранилась» (техническая половина — интеграционные тесты edit→seed→persists / delete→seed→remains).

## План — брифы слайсов

| Слайс | Исход | Требования (req_id) | Приёмка (кратко) | Зависимости | Режим | Write scope | Риск | Next |
|---|---|---|---|---|---|---|---|---|
| SU-MIGR | §1 | SU-CAT.GENERAL/HUMOR/MAT/ENTRY/REAL/MIGRATE, SU-0.AUDIT, SU-REG.NOSPRAWL | v37-миграция категорий+режима: идемпотентна, обратима по данным, SQLite/PG; легаси `other` остаётся; снапшот без потерь; повтор no-op | — | writer | mca_sample_library.py, database.py, speech.py, tests/test_samples_categories.py | R1 | Reviewer |
| SU-SEED | §3 | SU-PERSIST.TOMB/IDEM/FORCE/STORE/TESTS/LEGACY, SU-FACT.EDIT/SEMANTICS, SU-0.NOAUTORESTORE | tombstone+идемпотентность подтверждены тестами edit→seed/delete→seed/restore/revision-conflict; force только явный; «Изменено владельцем»+ревизия; без нового конфиг-сервиса | SU-MIGR | writer | mca_sample_library.py, database.py, speech.py, tests/test_samples_factory_persist.py | R1 | Reviewer |
| SU-FEWSHOT | §2+§5 | SU-TXT.EPISODIC/FREQUENT/OFFINHERIT/REPLACE/SCOPE, SU-FS.BLOCKS/BOUNDED/WHY, SU-0.ONECORE, SU-6.WISHES | байт-равенство §2 (пины+F8-bump+ledger-сверка); блоки по категориям; MAT по effective-режиму; 0 доп. LLM; «Почему…» с честными причинами | SU-SEED | writer | mca_expression.py, mca_sample_library.py, prompt_registry.py, speech.py, tests/test_add_exp_expression.py, tests/test_samples_fewshot.py | R1 (байт-пины/F4-стык) | Reviewer |
| SU-UI | §4 | SU-UI.L1–L6/CARD/ENTRY/HIERARCHY/TOKENS/MOBILE/SELECTS/SCROLL/SAVECONF/DESKTOP/BOUNDS, SU-ED.1–6/SCREEN/FACTORY | DOM/e2e по иерархии §4.1, редактор-экран §4.2, адаптивность §4.3 без overflow/коллизий; навигация/фон других разделов не тронуты | SU-FEWSHOT | writer | web/app.js, web/index.html, web/static/app.css, tests/test_samples_ui_e2e.py | R2 (визуальные контракты) | Reviewer (Visual Preservation Map + Browser Use) |
| SU-ACCEPT | §7+§8 | SU-ACC.UNDERSTAND/PERSIST/NOLOSS/PROMPT/MOBILE/NOLIVE, SU-0.PRESERVE, SU-6.REGRESS, SU-7.NOLIVE/OFFLINE/OWNERLIVE/REPORT, SU-REG.DELTA, SU-8.PLAN | сквозной offline-прогон (SQLite/PG), ноль live-отправок, owner_live_checks-пункты внесены, отчёт: было/добавлено/offline/осталось + commit | SU-UI | writer | tests/test_samples_acceptance.py, plans/features/samples-ux/reconciliation.md, plans/owner_live_checks.md | R2 | Reviewer → DevOps (штатный деплой, очередь продолжается) |

Карта: `requirements-map.json` (strict_evidence=true, slice_graph_path=slice-graph.json). План-гейт EXIT 0. Билд не назначается (этап Orchestrator).
