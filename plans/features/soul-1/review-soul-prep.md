# SOUL-PREP — независимая проверка подготовки релиза SOUL-1 (review-soul-prep, 18.10.2026)

## Привязка проверки (exact candidate)

| Поле | Значение |
|---|---|
| Артефакт | `plans/features/soul-1/soul-release-prep.md` (68 строк) + `evidence/soul-prep/**` (7 файлов) |
| Прод | `0b7a0aca` (2.58.84), APP_VERSION сверен: `config/settings.py:3290 = "2.58.84"` |
| Кандидат релиза | master `d98e55c6` (runtime == ревью-commit `6094a2cf`; HEAD `db6a3d0a` — доки); мой прогон: `git diff 6094a2cf d98e55c6 -- services web` = пусто, то же vs `db6a3d0a` |
| Ветка tree-port (мой прогон) | worktree от `0b7a0aca` + checkout master-путей → tree `6d51bdb8`; `git diff <tree> 6094a2cf -- services web` = пусто; дельта = 505 файлов |
| Изоляция | прогоны в `OPENCODE_WORKFLOW_SCRATCH/soulprep-review`, `.../soulprep-trial-a` (после проверки удалены); рабочее дерево не менялось |

## Итог: **Needs Fixes** (2 блокера документационных + 1 точность; кода менять не нужно)

## Что проверено моим исполнением (не переиспользовано)

1. **Якоря.** Диффы (3×) пусты; tree-port даёт web-байты, равные ревью-коммиту; sha256-12 содержимого совпали с таблицей review-fs.md §2 (13/13-блоб-отпечатки): policy `96db06425079`, app.css `b17fddf4d4f8`, index.html `d2c91f46314b`, app.js `2eea2e452449`. Дельта 505 = заявленной (services 38, web 6, config 1, tests 104, tools 14, plans 340, README.md, AGENTS.md). `plans/features/cfg` в коммите отсутствует; scratch/node_modules в дереве нет.
2. **Способ (b).** Воспроизведено: cherry-pick W1→W3 от прода даёт конфликт ровно в `services/prompt_registry.py`; cherry-pick W6 (`a5902b15`, `-n`) — без конфликтов, 115 файлов, блобы `cc4f17d0`/`c95d3a8b`/`d0e232e5` (значения evidence совпали поштучно). Отказ от (a) обоснован; в документе неточность: цитируемые «master»-значения — это блобы W6-коммита, а финальный target-app.css (`d0e232e5`) совпал с trial-байтами (см. F3).
3. **Withheld-классификация** (пересчёт кодом кандидата, `services/prompt_registry.py`): класс удержания — 11 ключей (совпадают с evidence); **11/11 canon-equal** (`sha12(live) == sha12(factory_text)`), владельческих кастомов 0; маркеров 11/11; правила `LEGACY_PERSONA_RULES` = 9; вычистка срабатывает ровно на 12 канонах (11 удержания + `verbilizer_mode_deep_research`); `factory_set_fingerprint()` = `0fc99f73d646`. Non-canon: `summary_editor_system_prompt`, `verbilizer_default_mode` (+ `summary_cover_style_id` = пустой селектор, «factory=n/a», для строки байт-эквивалент кодового дефолта). Рекомендация «не удалять/не переписывать» не противоречит директивам и скрытого удаления не содержит (данные не мутируются; `rollback_legacy_speech` есть).
4. **Снимок прода внутренне согласован:** HEAD/healthz 2.58.84; `flags.*` = **97**; `prompts.*` = 25; SOUL-ключей среди флагов нет; чат `-1002661910336` — 23 override, 4 `prompts.*` с заявленными длинами (3484/110/12/6); SQLite `user_version=35`, `humor_samples` отсутствует; v36 аддитивна и self-guarded (`_table_exists` + PRAGMA, PG no-op); в дереве прода нет `prompt_registry/style_policy/speech.py`.
5. **Карта/гейт:** `check --stage plan` обеих карт = `errors=0` (мой прогон). Release-стадия красная — воспроизведено: main `errors=214`, amendment `errors=88` (asap8 `errors=242`).
6. **Runbook исполнимо:** все файлы существуют; JS-тестов у кандидата ровно **86** (87-й — незакоммиченный чужой файл, см. F3); `pytest tests/test_soul1_composer_parity_off.py` = **13 passed**; `gen_param_registry_round1025.py --check` = **575 == REGISTRY**; WARNING R17-safe (`key/block/reason/stored_sha/stored_chars`, без текста); `character_layers_enabled`/`experience_lessons_enabled` = ON по дефолту, W5-лимиты = 0 (паритет) → лишних осей нет.
7. **Re-anchor-список** подтверждён: строки SOUL-02.0–02.8, AMD.1.1/1.3/3.2/3.4/4.1–4.5 существуют, несут устаревшие «реестра нет/не создано» при поставленных registry/factory/Core/W6-редакторе; переанкор поручён parent с evidence на кандидата — молчаливого закрытия нет. Реально открытые строки из перечня существуют (AMD.1.5/2.2/2.4/2.5/2.7/2.9/7.3, SOUL-05.7/09.3/16.4.4/16.5.3).

## Блокеры

**F1 (блокер, Medium) — инструкции включения/отката осей не соответствуют коду.**
- `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED` = env AND каталоговый флаг (`W5_GATES`, `_w5_axis`), env-дефолт OFF. Мой прогон кандидата: PG=true при не заданном env → **False**; env=1 → True. В таблице §4 и шаге (e) указан только `POST /api/config` → реальная отправка останется mock, «откат тумблером» недостоверен.
- `flags.unified_composer_enabled` / `flags.humor_*` (а также `flags.character_core_enabled`, `flags.speech_style_policy_enabled`) **не зарегистрированы в каталоге** (`param_catalog.py`: из SOUL-1 флагов есть только `flags.initiative_diagnostics_publish_enabled`) → `POST /api/config` вернёт 422 («неизвестный ключ»), запись возможна только напрямую в PG.
- Прямая запись в PG **не hot**: `hot_config.get` читает in-memory `ConfigCache`; `reload()` вызывается только in-app admin/role-путями, `set/set_many` обновляют лишь записанные ключи. Значит скрипт/SQL-запись действует лишь после graceful-рестарта. Как записано в шаге (a) («restart → потом PG (скрипт, hot)») мастер-ось композера останется OFF; обещанный «мгновенный откат PG→false (hot)» для мастера/юмора не мгновенный (откат = снять env + graceful restart; для инициативы PG-тумблер hot только после заданного env).
- **Минимальная правка (docs):** (1) для инициативы добавить env-половину + рестарт перед тумблером; (2) для некаталоговых флагов указать «запись в PG ДО graceful-рестарта (или явный `ConfigCache.reload()` через in-app путь)»; (3) исправить колонки Hot?/«мгновенный откат» по факту. **Recheck:** репетиция включения на ветке + `/api/speech/overview` axes после каждого шага.

**F2 (блокер, Low-Medium) — ложная атрибуция решения владельца и неполный список открытых строк.**
- §2: «Рекомендация (= решение владельца (a) «Core-over-custom»)» — владелец этого не решал: `owner-decisions.md` (a)–(e) — это варианты+рекомендации, а `plans/owner_questions.md` (18.10) держит OQ-4…OQ-8 (политика custom, «закат» legacy, внекаталожные пути, Initiative, редакционная eligibility) в статусе **TO_ASK**. §7 «Неразрешимых продуктовых выборов нет» неверен; стоячее правило PET снимает запрет на включение готового, но не заменяет сам выбор.
- §6.3 «Реально открытые (не переанкорить)» не включает `SOUL-AMD.1.2`, `SOUL-AMD.4.6`, `SOUL-AMD.7.2` — все три PENDING и прямо ждут решения (JB-3) и/или живого снимка.
- **Минимальная правка:** §2/§7 — назвать это рекомендованным безопасным дефолтом (не удалять, Core-over-custom, JB-3 опционален) до ответа владельца; в §6.3 добавить AMD.1.2/4.6/7.2. **Recheck:** сверка §6.3 с фактическими PENDING обеих карт.

## Неблокирующая точность (в ту же правку)

**F3.** (i) §1: «среди 100 ключей flags.*» — по evidence и моему пересчёту **97** (SOUL-ключей 0 — верно). (ii) §6.4: «292 строки → 127/29/116/20» — фактически у двух карт **268 обязательных (127 VERIFIED / 29 READY_FOR_LIVE / 112 PENDING) + 20 контекстных = 288** (`workflow_progress.py --json` — воспроизведено); вывод «release-стадия красная» верен. (iii) §3: значения «master 45f07428/8b42cd96/3b616c1f» — это W6-коммит, а не релиз-цель (app.css цели совпал). (iv) Гигиена: в основном рабочем дереве лежат чужие незакоммиченные правки (`web/app.js`, `web/index.html`, `web/static/glass-probe.js`, `tests/js/glass_probe_test.js` + untracked `tests/js/glass_refraction_test.js` — отсюда 87 JS-файлов вместо 86) — в runbook стоит явно требовать прогон только в изолированном worktree ветки.

## Ledger

| Пункт задания | Статус |
|---|---|
| 1. Якоря (диффы, дельта 505, снимок) | VERIFIED |
| 2. Список ON-осей (полнота/корректность/откат) | FAILED (F1); набор осей полон, лишних нет |
| 3. Withheld-классификация и отсутствие скрытого удаления | VERIFIED (F2 — атрибуция, не данные) |
| 4. Способ (b) / отказ (a) | VERIFIED |
| 5. Re-anchor-список | VERIFIED (F2 — неполный open-список) |
| 6. Runbook: исполнимость и честность рисков | Частично FAILED (F1, F3) |
| 7. Вердикт | этот файл |

Переиспользовано (без повторного прогона): прогоны W7+FS и review-fs (13/13 отпечатков — совпали с моими), perimetr/embedding/e2e-матрицы заявлены в runbook как обязательные к прогону на ветке. Недоступно локально: живые Telegram-наблюдения (после выката) — не входят в SOUL-PREP.
