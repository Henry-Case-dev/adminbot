# RELEASE-SOUL1-25886 — изолированный релиз SOUL-1 (2.58.86): отчёт

- **Лейн:** REL-SOUL (release engineer). Режим: release-ветка + штатный деплой.
- **Вход:** `soul-release-prep.md` (§3 способ (b), §4 исполнимая процедура включения,
  §5 precondition), `review-payload-verify.md` R2 (F1/F3 закрыты; остаток — релизный
  прогон: (ii), F5, F2/F4), `review-soul-prep.md` R3, директива владельца
  `source-release-correction-2026-10-18.md`, `evidence/soul-release/postfix/**`.
- **Прод до релиза:** `9552686391dfe69dd7cb08ba7cd800a8a6c5106e` (`release/win-glass-2.58.85`,
  APP_VERSION 2.58.85). Rollback-цель — эта же ветка.
- **PET_PROJECT:** все готовые оси включаются сразу во всех подключённых чатах; деплой
  «всё OFF» — изоляция релиза (не канарейка); rollback-механизмы сохранены.

## 1. Ветка и состав

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, worktree `OPENCODE_WORKFLOW_SCRATCH/soul1-release-25886/wt`, ветка `release/soul1-2.58.86` |
| База ветки | **`9552686391dfe69dd7cb08ba7cd800a8a6c5106e`** (2.58.85, задеплоенный WG-релиз) |
| Способ | (b) tree-port: `git checkout 915aa3c7 -- services web config tests tools plans README.md AGENTS.md` |
| Коммиты | `432edf80` (tree-port SOUL-1) + `e0756310` (bump 2.58.86, 31 файл) + `eafbe2e7` (runbook §4–§5 sync) |
| Дельта vs база | **628 файлов** (см. `evidence/release-soul-25886/delta-vs-base.txt`, `isolation-classification.txt`) |
| Runtime-эквивалентность | `git diff 72b91d6e HEAD -- services` = ПУСТО; `git diff 0ca661fe master -- web services` = ПУСТО; `git diff master HEAD -- services web` = ПУСТО |
| Бампа версии | 2.58.81→2.58.86: settings + README + F8-meta (HEAD `432edf80`) + 24 py-пина + 4 JS-пина = 31 файл |
| Изоляция | 0 неклассифицированных; CFG (`plans/features/cfg/**`) отсутствует; WG-артефакты байт-в-байт проду (`fullscreen-policy.js` `96db06425079`, `glass-refraction.js` `6a09d962d59d`, `glass-probe.js` `b2e6a1f987c6`, 2 JS-теста WG, `tools/ui_win_glass_refraction_e2e.py`); scratch/node_modules в дерево не входят |
| Секрет-скан дельты | 22 «срабатывания» — все тестовые дубли (`sk-SYNTHETIC-*`, `123456:TEST_TOKEN_*`, R17-маркеры); реальных секретов нет |

## 1-bis. Итог деплоя

| Поле | Значение |
|---|---|
| deployed_commit | **`eafbe2e7b792c74eeb91735e183b767c6b85d73c`** (ветка `release/soul1-2.58.86`, prototype; артефакт-коммиты идут после и runtime не меняют) |
| Прод до/после | 2.58.85 (`95526863`) → **2.58.86**, healthz ok (loopback + 443 + извне) |
| Push | `release/soul1-2.58.86` → origin (`ls-remote` = tip) |
| Миграции | SQLite v36 `humor_samples` — аддитивная, применена (backup-guard 153 с) |
| DDL PG | 0 (кроме штатных строк `flags.*`/`character.core`) |
| Rollback-цель | `release/win-glass-2.58.85` (`95526863`) — автоматический откат первого прогона отработал и подтверждён |
| SSH-дисциплина | 1 recon + 1 основной прогон (первый прогон — авто-откат) + короткие read-only диагностики (диагноз миграции/финальная фиксация), все одиночные, без ретраев; секретов в логах нет |


| Прогон | Результат | Артефакт |
|---|---|---|
| node `tests/js/*.js` (87 файлов) | **87 OK / 0 RED** (ожидание «84/85 + RED round1025_design_tokens» не подтвердилось — master-линия содержит исправленный тест+app.js) | `preflight-node-guards.txt` |
| `tests/test_soul1_*.py` (30 файлов) | **599 passed** | `preflight-soul1-set.txt` |
| parity OFF | **13 passed** | `preflight-parity.txt` |
| `tools/gen_param_registry_round1025.py --check` | **575 == REGISTRY** ok | `preflight-registry-check.txt` |
| Периметр `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` | **3917 passed / 0 failed** (10244 deselected; +2 к ожидаемым 3915 — новые F1/F3-тесты `72b91d6e`) | `preflight-perimeter.txt` |
| Embedding-sweep `-k "embedding or graphrag or quota or summary_memory or memory_maintenance"` | **534 passed / 0** | `preflight-embedding-sweep.txt` |
| Смежные (prompt_migrations + round1025_f8_registry) | **70 passed** | `preflight-adjacent-tests.txt` |
| FS-матрица `tools/ui_asap8_w2_fullscreen_e2e.py` | **12/12 PASS** | `preflight-ui-fs-matrix.txt` |
| W7 dev-API `tools/ui_soul1_w7_fullscreen_explain_e2e.py` | **5/5 PASS, 88 проверок** | `preflight-ui-w7-explain.txt` |
| W6 speech e2e `tools/ui_soul1_w6_speech_e2e.py` | **RED с закоммиченной фикстурой / 0 failures с пере-снятой** | `preflight-ui-w6-speech-stale-fixture.txt`, `preflight-ui-w6-speech-regenfixture.txt`, `w6-e2e-diagnosis.txt` |
| W2-SHELL e2e (U01/U02) | **RED — предсуществует на базе** (идентичная сигнатура на дереве `95526863`) | `preflight-ui-shell-e2e.txt`, `preflight-ui-shell-e2e-on-base95526863.txt`, `w2-shell-e2e-diagnosis.txt` |
| Frozen-check (адаптер к базе; upstream-инструмент не работает в worktree) | **RESULT: OK** (полигон/линзы/ассеты/LF/маркеры WG сохранены) | `preflight-frozen-check.txt` |

## 3. Капчуры до включения (директива п.2; критерии (i)(ii)(iii), F5, F2/F4)

Полный вывод — `evidence/release-soul-25886/capture-before.txt` (read-only, один
SSH-прогон, без записи в PG/репо; секретов нет).

**PG-backup (маркер W2 F1.2 `composer_flag_release_gate`, пункт (а)):** файл на
сервере `~/soul86_pg_backup_20261017T21…Z.json` — 122 строки `bot_settings`
(`prompts.*`, `flags.*`, `character.*`, `style.*`, `humor.*`, `message.*`,
`expression.*`, `guide*`) + `chat_profiles` (3 чата, включая overrides),
117 КБ, sha256_16 `5cc7de90e9132d05`. Значения не мутируются релизом (вычистка
legacy — только на сборке).

**(ii) кастомы — контент снят живым чтением, вердикт дан:**
- `prompts.summary_editor_system_prompt`: sha12 **`6a1f3432889c`**, len **2023** —
  совпало с ожиданием R2 (`6a1f3432889c`/2023 ⇒ значение с момента снапшота не
  менялось); маркеры: базовые **0**, расширенный набор (двач/характер бота/
  атмосфер/старый голос/persona/личность бота) — **0**; контент — редакторская
  роль саммари («СИСТЕМНАЯ РОЛЬ: Ты — редактор саммари…»), инструкций характера
  нет → **CLEAN** (не удерживается, остаётся действующим — как и решено prep §2).
- per-chat `prompts.summary_cover_style` (чат `-1002661910336`): sha12
  **`35013bd88081`**, len **110** — совпало с ожиданием R2; маркеры 0/0;
  контент — стиль обложки комикса («Comic-book style, set in modern Russia…»)
  → **CLEAN** (не удерживается; в effective не участвует как личность).
- критерий (ii) **закрыт**: контент захвачен, вердикт «характерных инструкций нет».

**F5 `personas`/`persona_traits` — вердикт: конфликта с Core нет (в смысле
инструкций личности), но отмечено фактическое состояние:**
`personas`: 2 строки (глобальная + чат `-1002661910336`) — `name`, `biography`,
`system_prompt_overrides` **пустые** (sha12 пустой строки), т.е. персонального
контента нет; `persona_traits`: 50 строк (deep-sleep наблюдения вида «Тон стал
более вольным и дерзким…»), маркеров старой личности **0**. Итог: скрытых
инструкций характера, конкурирующих с Core, нет → критерий F5 закрыт;
поведенческие черты (AMD.4.6(iii), вопрос открыт) остаются как есть.

**(i) удержание:** PG-ключи SOUL (`flags.*`) отсутствуют — **0**; документы
`character.core`/`style.policy`/`humor.craft` отсутствуют (`docs_present=[]`) —
это ожидаемое состояние «до включения».

**F2:** `SMART_VERBALIZER_MODES_ENABLED` в `.env` — отсутствует; процесс-environ
из-под `nik` не читается (PermissionError, ожидаемо). Действует код-дефолт
`True` (`config/settings.py:568`, `_env_bool(..., True)`) ⇒ «≠ 0» выполнено;
code-fallback (PG down) принят как OFF-паритет W2 (решение R2).

**F4:** env `NOSTALGIA_ENABLED` отсутствует (settings-дефолт `False`).
**Отклонение от ожидания R2:** PG-ключ `memory.nostalgia_enabled` на проде
**присутствует и равен `true`** (в снапшоте 17.10 его не было; релизом он не
создаётся и не меняется). Фактическое состояние зафиксировано, состояние
резолва — §5 (журнал/живой процесс).

**Состояние осей до включения (доказательство изоляции «всё OFF»):** все
env-оси в `.env` отсутствуют (`None` ×10), `soul_flags_present=0`,
`docs_present=[]`.


## 4. Деплой и включение осей (исполнимая процедура §4)

Прогоны: `recon.txt` (21:44:08Z), `deploy-run.txt` (основной, 21:51:07–21:57Z),
`first-attempt-health-miss.md` (первая попытка 21:46 и её диагноз).

**Деплой (всё OFF).** fetch origin → `checkout -B release/soul1-2.58.86`
(HEAD `eafbe2e7…`, `TRACKED_MOD_AFTER=0`, `DELTA_FILES=628`), sha256_12
артефактов **12/12** == расчётным, маркеры (`APP_VERSION="2.58.86"`,
`REFRACT_APPJS=6`, SOUL-файлы present, F3-фраза present).
Первый рестарт упёрся в 90-секундное health-окно: приложение не выходит на HTTP
до завершения миграционного раннера, а шаг v36 делает backup-guard
(`VACUUM INTO`) — на прод-объёме **153 с** (журнал: `migration backup-guard:
done in 153.0s`). Скрипт корректно откатился на базу (прод всё время был жив на
2.58.85, `.env`/PG не тронуты); после фикса окна ожидания (10 мин на миграцию +
5 мин health) второй прогон прошёл целиком. Миграция: `pending=[36]` →
`v36 applied in 0.1s | humor_samples_v36` → `user_version=36` (SQLite,
`BOOK [(36,'humor_samples_v36'), …]`) — аддитивно, как и планировалось.

**Enablement (один graceful-рестарт на весь набор).** `.env` (шаг 1):
`UNIFIED_COMPOSER_ENABLED=1`, `HUMOR_CRAFT_ENABLED=1`, `HUMOR_LIBRARY_ENABLED=1`,
`HUMOR_FEEDBACK_ENABLED=1`, `INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED=1`
(бэкап `.env` — `~/soul86_env_backup_20261017T215445Z`; `HUMOR_CANDIDATE_EVAL_ENABLED`
не включался). PG (jsonb-bool, не строки): `flags.unified_composer_enabled`,
`flags.humor_craft_enabled`, `flags.humor_library_enabled`,
`flags.humor_feedback_enabled` = `true` (тип `boolean`, подтверждено повторным
чтением); `flags.humor_candidate_eval_enabled` отсутствует (F5: оси нет эффекта).
Затем **один** graceful-рестарт (21:54:51) → healthz `2.58.86` (24 с).

**Документы (in-app, hot; штатным API, не SQL):**
- `character.core` — Factory Default = авторский SOUL-02: `POST
  /api/speech/block/core.personality` с фабричным текстом из реестра →
  `applied=true`, ревизия `act:040581a3b4b0`, `provenance owner_edit persisted`,
  в PG `character.core` (полный текст 2835 зн., sha12 `040581a3b4b0`);
  после записи Core: `source=global`, `origin=owner_edit`, `level=full`,
  `reason=owner_setting`, `differs_from_factory=false`.
- `style.policy` — `POST /api/speech/style` вернул `applied=true, revision=1`,
  но документ **не персистился** (дефект найден живым прогоном — см. §7.8 и
  `defect-style-policy-global-save.md`); поведенчески эквивалентно «политики
  нет» (пустая заводская политика), оси не мешает.
- Инициатива: `POST /api/config {"flags.initiative_diagnostics_publish_enabled":
  true}` → `200 {"updated": [...]}` (hot; журнал `[api] config updated | key=…
  | by=5885953495`); реальная отправка всё равно требует `confirm_publish`.

## 5. Пост-деплой проверки

| Проба | Результат |
|---|---|
| healthz (loopback, 443, извне) | `{"status":"ok","version":"2.58.86"}` ×3 |
| `GET /api/speech/overview` (админ) | 200; **gates: все 10 ON** (`unified_composer_enabled`, `character_core_enabled`, `speech_style_policy_enabled`, `humor_library_enabled`, `humor_feedback_enabled`, `persona_enabled`, `character_layers_enabled`, `experience_lessons_enabled`, `smart_verbalizer_modes_enabled`, `response_plan_enabled`); `registry.blocks=89`, `version=soul1-w3-1`, `factory_set=7422c0385f7d` |
| «Все инструкции» (`/api/speech/blocks`) | 89 блоков, **withheld=11** ровно те ключи класса удержания (factcheck/summary/search/checkup/direct/youtube/web…) — legacy-слой не активен, WARNING `persisted speech value withheld` в журнале (13 строк) |
| **Core в сборке речевых путей** (`POST /api/speech/try`, реальный композер, без LLM) | `layers_current=["channel_contract","channel_contract","core"]`; `layer_order=[…, core, identity, self_model_traits, context_lessons, response_plan, expression, humor_craft, few_shot, style_policy_hint, channel_output]`; `versions.core="r1.040581a3b4b0"`, `core_detail="full:owner_setting"`; `conflicts=[]` |
| Inspector | 200 (снимок хода пуст — реального хода после рестарта ещё не было; это ожидаемо) |
| Бот принимает сообщения | `Run polling for bot @PERMsoc_bot id=8802473181` (журнал), `[webapp] lifespan started | pg_available=True`, роутеры/воркеры зарегистрированы, `MEDIA_PUBLIC…` ок |
| Пробы HTTP (loopback) | `/healthz`,`/web/`,`/web/app.js`,`/web/static/app.css`,`/static/fullscreen-policy.js`,`/static/glass-refraction.js` → 200; `/api/speech/overview`, `/api/memory/initiative-vitality`, `/api/speech/blocks` → **401** (маршруты живы, не 404) |
| Страница `/web/` | `2.58.86` ×15, SOUL-маркеры ×4 |
| Журнал | **0 ERROR/CRITICAL/Traceback** (единственное совпадение — слово «traceback» внутри RuntimeWarning, см. §7.8); graceful-стопы базы и старт 2.58.86 чистые; `NRestarts=0`, `ExecMainStatus=0`, active/running |
| SQLite | `user_version=36`, таблица `humor_samples` есть, книга `schema_migrations` v36 |
| 29 READY_FOR_LIVE | см. `postdeploy-observations.md`: часть закрыта агентски (оси/удержание/Core-в-сборке/инициативная витрина), остальное — owner-сценарии (реальный клиент/чат/устройство); строки карт не менялись |


## 6. Откат

**По осям (без отката кода, исполнимая процедура §4):**
- инициатива: `POST /api/config {"items":[{"key":"flags.initiative_diagnostics_publish_enabled","value":false}]}` — hot, мгновенно;
- Core: «Вернуть заводской вариант» блока `core.personality` (hot) либо `CHARACTER_CORE_ENABLED=0` + graceful-рестарт (env-половина);
- Style: сброс документа `style.policy` (hot) либо `SPEECH_STYLE_POLICY_ENABLED=0` + graceful-рестарт;
- мастер/humor: удалить/обнулить строки в `.env` + graceful-рестарт (оси гаснут независимо от PG; формулировка «PG=false — hot» неверна);
- PG-ключи `flags.*`: `UPDATE … SET value='false'::jsonb` + graceful-рестарт (некаталоговые ключи не hot).

**Документы:** `character.core`/`style.policy` — сброс к фабрике (hot) либо оставить
(вред отсутствует: без документа действует заводская редакция).

**Полный откат кода:** `cd /var/www/admin_bot && git checkout release/win-glass-2.58.85
&& sudo systemctl restart admin_bot` → healthz 2.58.85. SQLite-миграция v36
(`humor_samples`) аддитивна, старая версия её игнорирует; байты `prompts.*` в PG
не мутировались, backup — `~/soul86_pg_backup_*.json`.

**Готовность:** rollback автоматизирован в деплой-скрипте (при недостижении
healthz 2.58.86 после любого рестарта: checkout базы + снятие env-осей +
PG-ключи `false` + рестарт + health 2.58.85). Потребовался/не потребовался — §4/§5.


## 7. Девиации и честные хвосты

1. **node-число** (ожидание «84/85 + предсуществующий RED `round1025_design_tokens`»):
   факт — **87/87 OK** (RED существовал только на прод-линии WG-релиза; master-линия
   содержит согласованные тест+`app.js`). Показываю фактическое число.
2. **Периметр** — 3917 (не 3915): +2 теста F1/F3 из `72b91d6e` (отревьюены в R2).
3. **W6 speech e2e**: RED на закоммиченной фикстуре (снята до слайса W4), GREEN
   (`failures=0`, 8 вьюпортов + interactions) на фикстуре, пере-снятой штатным
   генератором. Файл `evidence/w6/api-fixture.json` **не менялся** (W6-эвиденс —
   отдельный проход): `w6-e2e-diagnosis.txt` + `fixture-regenerated-by-dump-script.json`.
4. **W2-SHELL e2e**: RED, **предсуществует на базе** `95526863` (A/B — идентичная
   сигнатура): регрессия слоя стекла WIN-GLASS-P0 (мобильный «Раздел: …▾» в
   «Аналитике» перекрыт карточкой; `elementFromPoint` = карточка, скриншоты).
   К SOUL-1 не относится, релиз не блокирует; предложена минимальная правка
   stacking + повтор прогона (`w2-shell-e2e-diagnosis.txt`).
5. **F4-фиксация**: env `NOSTALGIA_ENABLED` отсутствует (settings-дефолт False),
   но PG-ключ `memory.nostalgia_enabled=true` **с 2026-09-06** (pre-existing, не
   релизом создан; рядом `memory.dream_enabled=true`). Живой процесс **поднимает
   NostalgiaWorker** (журнал: `NostalgiaWorker started (tick=60min, silence=45min,
   max_per_day=3, aggressiveness=0.3)`). Это фактическое состояние прода до/после
   релиза (не менялось), копия идёт через Core+жанровую рамку (AMD.2.6 проверен).
6. **F2-фиксация**: `SMART_VERBALIZER_MODES_ENABLED` в `.env` отсутствует →
   действует код-дефолт `True` (`config/settings.py:568`, `_env_bool(..., True)`)
   ⇒ «≠ 0» выполнено; proc-environ — dotenv-значения не видны в `/proc/<pid>/environ`
   (загружаются в процесс через `load_dotenv()`), фиксация по `.env` + код-дефолту.
7. **upstream `frozen_check.py`** падает в worktree (`_find_repo` требует каталог
   `.git`); применён адаптер к базе (`frozen_check_25886.py`), RESULT: OK.
8. **ДЕФЕКТ, найденный живым прогоном (follow-up №1):
   глобальное сохранение `style.policy` — молчаливый no-op.** `POST
   /api/speech/style` (scope=global) отвечает `applied=true`, но документ не
   персистится: `services/style_policy.py:2275` вызывает **асинхронный**
   `ConfigCache.set` без `await` (журнал: `RuntimeWarning: coroutine
   'ConfigCache.set' was never awaited`; в PG строки `style.policy` нет).
   Чат-ветка работает (там `await`). Видимое следствие: выбор «Глобально» в
   «Стиле письма» показывает «Правила сохранены», правила пропадают после
   перезагрузки. Правка — 1 строка + регресс-тест с async-кэшем; правку в дерево
   релиза **не вносил** (deployed tip == отревьюенный кандидат; правка продукта
   требует ревью). Детали: `defect-style-policy-global-save.md`.
9. **Первый прогон деплоя** (health-miss из-за 90-секундного окна и 153-секундного
   `VACUUM INTO` backup-guard миграции v36) — авто-откат на базу сработал,
   прод был жив; разбор и фикс окна: `first-attempt-health-miss.md`.
10. **Честные хвосты**: 29 READY_FOR_LIVE остаются owner-сценариями (реальный
    Telegram-клиент/устройство/живой чат) — карты не менялись, леджер отдельно;
    W8/W9 (метрики/A-B) не в поставке; OQ-4…OQ-8 (`plans/owner_questions.md`) —
    политика custom/Core для внекаталожных путей, не блокируют.

