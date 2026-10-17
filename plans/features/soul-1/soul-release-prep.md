# SOUL-1 — план релиза и включения (SOUL-PREP, 17.10.2026)

- **Лейн:** SOUL-PREP (read-only; ОДИН read-only SSH-снимок прода; код/`web`/`services`/карты не менялись; деплоя нет; `plans/features/cfg/**` не тронут).
- **Прод (снимок 17.10, 19:04:41 UTC):** `0b7a0aca` (2.58.84, ветка `release/fs-2.58.84`), TRACKED_MOD=0, healthz ok.
- **Релиз-источник:** текущий master HEAD `d98e55c6` (docs-коммит LEDGER поверх `a891b721`; **runtime-байты == последний ревью-commit `6094a2cf`** — проверено пустым диффом, `isolation-checks.txt`).
- **Evidence (этот лейн):** `evidence/soul-prep/` — `ev_live_snapshot_2026-10-17.txt`, `snapshot_summary.txt`, `prompts_classification.txt`, `delta-classification.txt`, `isolation-checks.txt`, `approach-decision.txt`, `release-runbook.txt`.
- **Рев. 18.10 (FIX-SOUL-PREP):** учтены блокеры и точность независимого ревью `review-soul-prep.md` (коммит `755c8a75`) и директива-коррекция владельца `source-release-correction-2026-10-18.md`: процедура включения/отката осей приведена к коду (F1), снята ложная атрибуция решения владельца и дополнен список открытых строк (F2), уточнены числа (F3).
- **Внешний вход релиза:** payload-верификация лейна SOUL-PAYLOAD-VERIFY — `plans/features/soul-1/evidence/soul-release/payload-verification.md` (лейн идёт; findings = гейт включения, §5).

## 1. Живой прод-снимок (без секретов)

| Слой | Факт |
|---|---|
| Оси SOUL-1 в env/`.env`/systemd | нет ни одной (все OFF); среди 97 ключей `flags.*` в PG SOUL-1-ключей **0** |
| `prompts.*` в PG (25 ключей) | **22 = байт-в-байт текущему код-канону** реестра (`soul1-w3-1`, factory_set `0fc99f73d646`); non-canon: `summary_editor` (custom 2023, маркеров нет), `verbilizer_default_mode` (7), `summary_cover_style_id` (пусто) |
| Документы | `character.core`, `style.policy`, `humor.craft`, `character.prompt_history`, `character.migration_snapshots` — **отсутствуют** (W1-миграции не выполнялись) |
| SQLite | `user_version=35`; таблицы `humor_samples` нет (v36 выполнится при первом старте релиза; аддитивная) |
| Чаты (3) | рабочая группа `-1002661910336`: 23 override; из `prompts.*`: `summary_system_prompt` (custom 3484, **класс удержания** → будет удержан), `summary_cover_style` (custom 110, не удерживается), `summary_cover_style_id`, `verbilizer_default_mode` |

**Ожидаемый эффект релиза (расчёт по коду-кандидату, `prompts_classification.txt`):** 12 канонов (11 класса удержания + ветка режима `deep_research`) теряют сегменты старой личности по 9 детерминированным правилам; контракты (JSON/АНТИ-БОТ/вердикт/инструменты) целы; ни одно владельческое значение не правится. **Директива 18.10 (п.1):** legacy-заводские речи — не активный слой; в effective runtime их нет (withheld, §2), байты byte-в-byte остаются в PG только как backup для аварийного отката (`rollback_legacy_speech`).

## 2. Withheld-классификация (числом)

- Класс удержания: **11 ключей** (direct tool-phase/l2-writer, factcheck×2, summary single/narrator, search, checkup, youtube×2, web).
- Сохранённые значения: **11/11 есть**; владельческих кастомов среди них — **0** (все 11 canon-equal); маркеры старой личности у 11/11 — потому что они часть самого канона ⇒ удержание и вычистка дают одинаковый effective = factory(suppressed).
- «4 невыводимых summary-кастома»: `l2_writer`/`l1_clusterizer` **сейчас canon-equal** (были custom на baseline 2.58.33); `editor` — единственный живой custom (2023, маркеров нет, **не удерживается** — остаётся действующим); `cover_style`: глобальный canon-equal, живой custom только per-chat (110, не удерживается).
- **Рекомендованный безопасный дефолт — НЕ «решение владельца» (F2 ревью):** открытые вопросы OQ-4…OQ-8 остаются `TO_ASK` (`plans/owner_questions.md`; варианты (a)–(e) и рекомендации — `owner-decisions.md`). До ответа владельца: **ничего не удалять и не переписывать**; withheld-слой (SOUL-AMD.1.2/4.6) уже даёт: persisted-значение 11 legacy-блоков без провенанса **не становится активным слоем** (`persisted_value_withheld` + WARNING R17-safe; витрина `withheld_values()`), действует заводская редакция, в PG ничего не пишется — в т.ч. per-chat custom `summary_system_prompt` 3484 («класс удержания», §1) остаётся только backup-слоем с видимым расхождением. Это и есть директива 18.10 (п.1): legacy-заводские речи — не активный слой, только backup для аварийного отката (`prompt_migrations.rollback_legacy_speech`). **Подлинные авторские настройки, не конкурирующие с Core, действуют:** `summary_editor` custom 2023 (маркеров нет, не удерживается), per-chat `summary_cover_style` 110. Режимы вербализаторов и прочие кастомы проверяются на скрытые инструкции характера лейном SOUL-PAYLOAD-VERIFY (`evidence/soul-release/payload-verification.md`, идёт); его findings — гейт включения (§5). JB-3 write-pass для включения **не обязателен** (effective тот же); судьба байтов (удалять/оставить) — решение владельца после релиза.

## 3. Способ релиза: **(b)** — tree-port отревьюенного master-набора в изолированной ветке от `0b7a0aca`

Цепочка (a) для сравнения: `3cc0b9c0→4c8405e7→c8cf77a5→a5902b15→c1cb6475→bc277a3d→d4c33c21→6094a2cf`. Испытано (scratch-worktree, `approach-decision.txt`):

- конфликт уже на 2-м коммите (`4c8405e7` → `services/prompt_registry.py`, 2 хунка);
- W6 (`a5902b15`) поверх прод-базы применяется **без** конфликтов, но даёт web-байты, не равные ни проду, ни релиз-цели `6094a2cf` (`bfec633a`/`aca59123`/`d0e232e5`): `app.js` `cc4f17d0` (vs W6-блоб `45f07428`), `index.html` `c95d3a8b` (vs W6-блоб `8b42cd96`), `app.css` `d0e232e5` (vs W6-блоб `3b616c1f` — но уже совпал с целью). Значения `45f07428`/`8b42cd96`/`3b616c1f` — блобы W6-коммита, не релиз-цели (F3 ревью); неотревьюенная комбинация (fs-порт уже на проде, а W6/W7 делались до fs); каждая такая развилка требовала бы повторного ревью UI;
- W7+FS пришлось бы расщеплять (fs уже портирован `a4fb04a9`).

**Выбор: (b).** Ветка `release/soul1-2.58.85` от `0b7a0aca` + `git checkout <master HEAD> -- services web config tests tools plans README.md AGENTS.md` + bump 2.58.81→2.58.85 (31 файл). Доказательство эквивалентности: `git diff <ветка> a891b721 -- services web` = **пусто** (и `git diff 6094a2cf <HEAD> -- services web` = пусто); дельта vs прод = **505 файлов** (services 38, web 6, config 1, tests 104, tools 14, plans 340, README.md, AGENTS.md).

Осознанные исключения: **CFG** (`plans/features/cfg/**` — untracked, в git не существует — не тащим); scratch/`node_modules`/`.playwright-mcp` (в git не входят by construction); W8/W9 (метрики/A-B/регистрация флагов в каталоге/§21-отчёт — не поставлены, в дереве отсутствуют); live-хвосты SOUL-13.2/13.3/13.4 (postdeploy).
Изоляция по шаблону fs-релиза (`isolation-checks.txt`): fs-`fullscreen-policy.js` байт-в-байт равна проду; fs-маркеры prod↔master совпадают; CFG-дерево пусто; дельта классифицирована.

## 4. Чек-лист включения (какие коды станут ON)

**F1-поправка (ревью):** у некаталоговых `flags.*` нет API-пути и нет hot-применения. `POST /api/config` на них вернёт **422 «неизвестный ключ»** — из SOUL-1-флагов в `param_catalog.REGISTRY` зарегистрирован только `flags.initiative_diagnostics_publish_enabled` (`services/param_catalog.py:2566`; валидация — `web/api/routes.py:1176–1178`). Прямая запись в PG **не hot**: `hot_config.get` читает in-memory `ConfigCache`; полный `reload()` выполняют только in-app операции админов/ролей (`services/config_cache.py:743–874`), а `set/set_many` обновляют лишь записанный ключ. Поэтому некаталоговые ключи пишутся в PG **до** graceful-рестарта (единственная альтернатива применить без рестарта — явный `ConfigCache.reload()`; штатно он не вызывается). Колонки ниже — по факту кода.

| Ось | Где читается | Как включить (исполнимо) | Hot? | Откат (точно) |
|---|---|---|---|---|
| `UNIFIED_COMPOSER_ENABLED` (мастер) | env (дефолт OFF) AND `flags.unified_composer_enabled` (`ConfigCache`) | PG-скрипт `flags.unified_composer_enabled=true` **до** рестарта (`POST /api/config` → 422) + `UNIFIED_COMPOSER_ENABLED=1` в `.env` + graceful-рестарт | **нет** — обе половины действуют после рестарта | `UNIFIED_COMPOSER_ENABLED=0` (или убрать строку) + graceful-рестарт → OFF независимо от PG; для PG=`false` — тот же порядок |
| `CHARACTER_CORE_ENABLED` | env-дефолт **ON** AND `flags.character_core_enabled` (ключ отсутствует → ON) | ось уже ON по дефолту; включение = создание документа `character.core` (Factory Default = авторский SOUL-02): «Характер» / `POST /api/speech/block/core.personality` | контент — да (in-app); env-половина — только рестартом | сброс блока к фабрике (hot); полный OFF оси — `CHARACTER_CORE_ENABLED=0` + рестарт (PG-ключ некаталоговый: скриптом, действует после рестарта) |
| `SPEECH_STYLE_POLICY_ENABLED` | env-дефолт **ON** AND `flags.speech_style_policy_enabled` (ключ отсутствует → ON) | ось уже ON по дефолту; включение = документ `style.policy` (`POST /api/speech/style`) | контент — да (in-app); env-половина — только рестартом | сброс документа (hot); полный OFF оси — `SPEECH_STYLE_POLICY_ENABLED=0` + рестарт |
| `HUMOR_CRAFT_ENABLED` / `HUMOR_LIBRARY_ENABLED` / `HUMOR_FEEDBACK_ENABLED` (**обязательный ON** — директива 18.10, п.4) | env (дефолт OFF) AND `flags.humor_*` | `.env`: `HUMOR_CRAFT_ENABLED=1`, `HUMOR_LIBRARY_ENABLED=1`, `HUMOR_FEEDBACK_ENABLED=1` + PG-скрипт `flags.humor_craft_enabled=true`, `flags.humor_library_enabled=true`, `flags.humor_feedback_enabled=true` **до** рестарта (`POST /api/config` → 422) + graceful-рестарт; примеры библиотеки — `/api/speech/examples/seed` + approve (следом, не блокер) | **нет** — после рестарта | env → `0`/убрать + graceful-рестарт → OFF независимо от PG |
| `HUMOR_CANDIDATE_EVAL_ENABLED` (**условно** — директива 18.10, п.4) | env (дефолт OFF) AND `flags.humor_candidate_eval_enabled` | включать, **только если** PAYLOAD-VERIFY подтвердил `IMPLEMENTED_AND_TESTED` (контекстная активация + существующие бюджеты ≤2 кандидата/≤1 вызов/таймаут; обычный ответ — 0 доп. вызовов); механика — как у humor-осей. Подтверждения нет → не включаем, релиз это **не блокирует** | **нет** | env → `0`/убрать + рестарт |
| `flags.initiative_diagnostics_publish_enabled` (в каталоге) | `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED` env (дефолт OFF) AND каталоговый `flags.*` (`W5_GATES`/`_w5_axis`, `services/mca_gates.py:2428–2458`) | (1) `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED=1` в `.env` + graceful-рестарт (без env-половины ось = OFF при любом PG — проверено запуском); (2) `POST /api/config` `{"items":[{"key":"flags.initiative_diagnostics_publish_enabled","value":true}]}` → 200, hot. Реальная отправка из «Проверить инициативу» дополнительно требует `confirm_publish=true` в самом запросе (`web/api/initiative_vitality.py`) | **да** — флаг-половина каталоговая (in-memory); env-половина — только рестартом | `POST /api/config` `value:false` — hot, мгновенно; глубже — снять env + рестарт |

**Последовательность включения (PET_PROJECT: все готовые оси сразу, во всех подключённых чатах; без канареек и искусственных OFF-периодов; деплой «всё OFF» — изоляция релиза, не канарейка; существующие rollback-механизмы сохраняются):**

0. PG-backup (read-only): `bot_settings.prompts.*` + `chat_profiles.overrides` + `flags.*` → файл-evidence (обязательный предварительный backup по маркеру W2 F1.2 `composer_flag_release_gate`; снятие legacy-слоя из effective даёт withheld-метод §2; повторная проверка F1 — репетиция ревьюера на ветке).
1. **До рестарта** — `.env`: `UNIFIED_COMPOSER_ENABLED=1`, `HUMOR_CRAFT_ENABLED=1`, `HUMOR_LIBRARY_ENABLED=1`, `HUMOR_FEEDBACK_ENABLED=1`, `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED=1` (+ `HUMOR_CANDIDATE_EVAL_ENABLED=1` только при `IMPLEMENTED_AND_TESTED` от PAYLOAD-VERIFY). PG-скриптом (SQL-шаблон: `INSERT INTO bot_settings(key,value,category) VALUES('flags.unified_composer_enabled','true'::jsonb,'flags') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now();` — повторить для `flags.humor_craft_enabled`, `flags.humor_library_enabled`, `flags.humor_feedback_enabled` (+`flags.humor_candidate_eval_enabled` условно); значение — jsonb-bool, не строкой).
2. **Graceful-рестарт** (один на весь набор): подхватятся env-половины и PG-ключи (`ConfigCache.init` → `_load_all`).
3. Verify: `GET /api/speech/overview` → `gates` — оси ON; манифест слоёв; в effective нет legacy-persona; ожидаемый WARNING `persisted speech value withheld` по 11 ключам (R17-safe).
4. Core: документ `character.core` (Factory Default = авторский SOUL-02) — «Характер» / `POST /api/speech/block/core.personality` (hot).
5. Style: документ `style.policy` — `POST /api/speech/style` (hot).
6. Initiative: `POST /api/config` `flags.initiative_diagnostics_publish_enabled=true` (hot; env — из шага 1).
7. Постдеплой-наблюдения 29 READY_FOR_LIVE (публикации/инициатива/логи) — штатный прожиг после включения; отдельного ожидания владельца нет (PET).

**Откат (исполнимо):** инициатива — `POST /api/config` `false` (hot, мгновенно); Core/Style — сброс блока/документа к фабрике (hot); мастер/humor — env-строки → `0`/убрать + graceful-рестарт (ось гаснет независимо от PG; «PG→`false` (hot)» неверно — рестарт нужен); полный откат кода — `git checkout release/fs-2.58.84` + рестарт (SQLite v36 аддитивна; PG-значения не мутировались; PG-ключи → `false`/удалить). Примечание: в `evidence/soul-prep/release-runbook.txt` §4–5 остались до-правовые формулировки («PG-ключ — hot», шаг (e) без env-половины) — исполнимая версия процедуры здесь; при следующей правке runbook синхронизировать.

Verify-команды каждого шага — `release-runbook.txt` §4 (с учётом этой поправки).

## 5. Проверки перед выкатом (на точном дереве ветки)

**Precondition релиза (директива 18.10, п.2): payload-верификация (лейн SOUL-PAYLOAD-VERIFY).** В реальных LLM payload Direct/Initiative/Factcheck/Summary/fallback единственный характер = новый Core; скрытых legacy-инструкций личности нет (включая кастомы и режимы вербализаторов — `summary_editor`, `verbilizer_default_mode`, per-chat cover). Evidence лейна: `plans/features/soul-1/evidence/soul-release/payload-verification.md` (идёт); findings = условие включения осей.

**Гигиена прогонов:** только изолированный worktree ветки (§3). В основном дереве — чужие незакоммиченные правки лейна WIN-GLASS-P0 (`web/*glass*`, `web/app.js`, `web/index.html`, `tests/js/glass_*`); у кандидата JS-тестов ровно 86, в основном дереве из-за них 87.

`release-runbook.txt` §2: node `tests/js/*.js` (86/86); `pytest tests/test_soul1_*.py`; parity OFF 13/13; `gen_param_registry_round1025.py --check` (**локально уже подтверждено: 575 == REGISTRY**); периметр `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` 3915/0; embedding-sweep 534/0; fs-матрица 12/12 + shell-e2e; W6 speech-e2e; W7 explain-e2e; frozen-check полигона. Плюс изоляционные проверки §3 и эквивалентность `git diff -- services web`. Обе карты на кандидате проходят `check --stage plan` (`errors=0`, локальный прогон).

## 6. Риски и честные хвосты

1. **ON мастера = реальная смена сборки промптов** (Direct + 6 писательских семейств; R3). Покрыто ревью (W2/W3/W6/W10), живая половина = 29 READY_FOR_LIVE строк → постдеплой-наблюдения; откат — env → OFF + graceful-рестарт (§4; PG-ключ не hot — прежняя формулировка «мгновенный откат (PG-ключ)» неверна, F1).
2. **WARNING-поток** `persisted speech value withheld` по 11 ключам на каждый резолв (R17-safe: key/block/reason/sha/chars). Не блокер; bounded-dedup — backlog.
3. **Карта отстала от поставки (устаревшие формулировки):** LEDGER-коммит `d98e55c6` уже выставил `deployed_commit=0b7a0aca` в обеих картах и закрыл `SOUL-13.2` по прод-наблюдению, но строки `SOUL-02.0–02.8`, `SOUL-AMD.1.1/1.3/3.2/3.4/4.1–4.5` по-прежнему несут «реестра нет / не создано», хотя реестр/фабрика/Core-блоки поставлены W1+CORE-DOC+W6 (SOUL-10.1/10.2 VERIFIED). **До release-прохода нужен переанкор/ре-верификация этих строк с evidence на релиз-кандидата** (задача parent/PM; молча закрывать нельзя). Реально открытые (не переанкорить; все PENDING): `SOUL-AMD.1.2/4.6/7.2` (убрать legacy из runtime / только backup / идемпотентная миграция — ждут JB-3-решения и/или прод-подтверждения withheld-потока; директива 18.10 фиксирует поведение «legacy — только backup», но строки остаются PENDING до переанкора с evidence на кандидата), `SOUL-AMD.1.5/2.2/2.4/2.5/2.7/2.9/7.3`, `SOUL-05.7`, `SOUL-16.4.4`, `SOUL-16.5.3`, `SOUL-09.3`, W8/W9-наборы, SOUL-13.4-провайдерский горизонт.
4. **Release-стадия гейта** останется красной: обе карты = **288 строк** — 268 обязательных (**127 VERIFIED / 29 READY_FOR_LIVE / 112 PENDING**) + 20 контекстных (`workflow_progress.py --json`; F3 ревью). PET-режим: выкатываем готовый набор; эпик не закрывается; `candidate/deployed_commit` и статусы — отдельный проход после выката.
5. SQLite v36 (`humor_samples`) — аддитивная, self-guarded; откат кода безвреден (старая версия таблицу игнорирует).
6. Внешние хвосты SOUL-13.3/13.4 (14 старых live-гейтов v6.3, provider reset horizon) остаются открытыми; code-стороны (13.0/13.1/13.5/13.6) готовы.

## 7. Блокирующих продуктовых выборов нет

Все оставшиеся решения — технические: у каждой оси включения есть исполнимый откат (§4); контент Core — прямая директива владельца (AMD.1.5: Factory Default = авторский SOUL-02; коррекция 18.10). Единственный кандидат («включать ли реальную отправку из “Проверить инициативу”») снят: ось безопасна (отправка требует per-click `confirm_publish`), откат — тумблером (hot).

Необязательные открытые вопросы, **не блокирующие релиз**: OQ-4…OQ-8 (`plans/owner_questions.md`, статус `TO_ASK`; варианты (a)–(e) — `owner-decisions.md`) — политика custom; Core для внекаталожных речевых путей; обязательность Core для инициативы; редакционная eligibility Summary/Factcheck; политика «заката» legacy. До ответов действуют рекомендованные безопасные дефолты (§2); ответы можно дать пакетом после релиза.

Единственный релиз-гейт — агентская payload-верификация (§5): её findings — условие включения, не продуктовый выбор владельца.
