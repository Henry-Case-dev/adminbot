# REL-258124 — деплой 2.58.124 и пост-проверки

Дата: 24.10.2026, 08:19–08:22 UTC. Лейн: DEPLOY-258124. Сервер: `198.46.175.136`, сервис `admin_bot`.

## DEPLOY_SOURCE

- **Кандидат (reviewed):** `39a06b880bdd894b68063686cf4ed0921ffe5d10` = 2.58.124 (`c6290ca1` — docs-tip, не деплоился).
- База: `6e587696` (2.58.123, был live), merge-base с `3dfdf9cb` = `3dfdf9cb`.
- Состав: `f00050a5` (кавычки A/B) → `42657294` (снятие квот A1–A6) → `4df74a81` (UI-cleanup) → `58b1bcca` (A7/F2) → `39a06b88` (bump).
- **MUTABLE_WORKTREE_REQUIRED: no** — деплой иммyтабельным коммитом (`git checkout -fq` в `/var/www/admin_bot`), рабочее дерево разработки не участвовало.
- Write scope деплоя: `release/fix-2.58.123` (ветка отката) в origin; на сервере менялся только checkout + рестарт. Код приложения не правился.

## Результат

- `git rev-parse HEAD` до: `3dfdf9cb…` → после: `39a06b88…`; tracked dirty `0` до и после; untracked `13` (не менялись).
- `systemctl restart admin_bot` → OK; `active`; **MainPID 1030683**; **NRestarts 0** (было 1014187/0).
- `http://127.0.0.1:8000/healthz` → **HTTP 200** `{"status":"ok","version":"2.58.124"}`.
- Публичный `https://198.46.175.136/healthz` с локальной машины недоступен (сбой schannel на Windows-хосте), с самого сервера `000` — публичный HTTPS-канал не подтверждён; доказательство живости — loopback-ответ самого процесса. Внешний TLS-канал — отдельная сетевая тема, к релизу не относится.
- Журнал с момента рестарта: CRITICAL 0, ERROR 0, Traceback 0, `database is locked` 0, ADOPTED 0, BUILD_START 0, prompt_rollback 0.

## Каноны / Core / adopt

- `FACTORY_SET 47f0d1eb8de4` — **без изменений**.
- Ключи `prompts.*` (checkup, direct_l1_planner, direct_chat_verbalizer, direct_chat, summary, factcheck): `unchanged_vs_pre = True` для всех; пользовательские кастомы не тронуты (`кастом юзера — НЕ трогаем`).
- Core patch идемпотентен: `[prompt_migration] core patch: абзацы уже есть, авторские байты целы | sha=ead77b2ab509`; `PATCH_CHANGES_ON_PRE []`, `PATCH_IDEMPOTENT True`, `CORE_UNCHANGED_AFTER_RESTART True`, `CORE_POST_LEN 3294`, `detail_level=full`, `revision 8`, оба авторских абзаца на месте.
- `withheld_values(pg_get=…)` → **11 строк**, 8 уникальных блоков (factcheck, search, summary, checkup, direct.tool_phase, youtube.system, youtube.video, web); каноны не потеряны, значения прежние.
- adopt не повторён: `ADOPTED 0`, `BUILD_START 0`.
- Embed: `user_version 37`; `graph_facts_vec` gen 1 `active`, `smart_archive` gen 1+2 `building` (фоновое построение, без ошибок).

## Кавычки (read-only проба `apply_style_policy`, `record=False`)

Вход: `Он сказал «текст» и добавил "ещё" — это пример.`

| Режим | Выход | Итог |
|---|---|---|
| A — default (factory `normalize`) | `Он сказал "текст" и добавил "ещё" - это пример.` | **OK**: «» → `"` |
| B — пресет «Без кавычек» (`strip`) | `Он сказал текст и добавил ещё - это пример.` | **OK**: «», » и `"` удалены, слова целы |
| OFF — правило `enabled=false` | текст не меняется правилом кавычек | **OK** |
| OFF — политика выключена целиком | `equal=True` (байт-в-байт, sha `ce8e5afe0b03`) | **OK** |
| A + тот же пресет в глобальном и в чате | 1 активное правило (`B_BOTH_QRULES n=1`, mode strip) | **OK**, сворачивание работает |

Защищённые регионы (A и B): код в backticks и JSON **целы** (`print("«y»")`, `{"k": "«v»"}` не менялись), блок кода в ```…``` — байт-в-байт (`equal=True`).

**Отклонение (узкое, by design):** литеральные `«»` **внутри URL** не защищаются — `https://ex.com/a?q=«x»` → A: `…?q="x"`, B: `…?q=x`. Причина в самом детекторе: `_URL_RE` (`services/style_policy.py`) исключает `«»` из набора символов URL, чтобы кавычки после ссылки не «съедались» ссылкой. Процент-кодированные и обычные URL не меняются (`%C2%ABx%C2%BB` и `?a=1&b=2` — `equal=True`). Практический риск близок к нулю (в реальных ссылках кавычки кодируются), но обещание «URL не повреждается» для этого края не выполняется. Не откат, решение — Builder/Reviewer.

## Квоты / payload

Живой путь композера (`resolve_gates` + Core из PG + `style_policy` из PG + `resolve_expression_settings`), три прогона с `COMPOSER_LAYER_BUDGET_TOKENS=1 / 0 / -1`:

- `SYSTEM_CHARS 8980`, `SYSTEM_SHA256_12 67c69fd1373f`, `TOKENS_TOTAL 2245` — **идентичны во всех трёх** (инвариантность: env-квота игнорируется).
- `settings.COMPOSER_LAYER_BUDGET_TOKENS` отсутствует; в `.env` переменной нет; `composer_additive_budget_tokens` нет ни в `prompt_composer`, ни в `mca_gates`; в `mca_gates` остались только `adaptive_context_budget_enabled`/`vision_reocr_budget`.
- Слои: `core` rendered 3294, `style_policy_hint` rendered 638, `channel_contract` 5044; **ни у одного слоя нет `budget_excluded`**; в system нет строк `budget_excluded` и `context_budget`.
- Core: `versions.core_detail = full:owner_setting`, полный текст 3294 симв. присутствует в system (`CORE_FULL_IN_SYSTEM True`), причины `context_budget` нет.
- Hint: 8 инструкций из 8 включены (`HINT_TOTAL 8 / INCLUDED 8 / EXCLUDED 0 / LIMITED_BY -`), 638 симв. в system — квоты инструкций не режут.
- Expression: блока `<Expression_Settings>` в system **нет**, причина от самого кода — `skip_reason=expression_absent`, `mode=''`, `text_len 0` (в PG нет текста выражения). Это состояние конфигурации владельца, не регресс релиза (ключи `bot_settings` не менялись) и согласуется с принятым «FREQUENT честный PARTIAL». Пункт «Expression присутствует» **не подтверждён** — не выдаю за выполненный.

## B11 / журнал

- `tools/v63_b11_mechanisms_report.py` → `B11_RC=0`; правило честности на месте: `not_green_rule: never_run/producer_off/no_input/unknown/degraded/attention никогда не считаются зелёными (REQ-B11-E2E)`.
- Отчёт честный, не всё зелёное: graph memory — «последняя попытка не завершилась успешно», incremental embedding — то же, experience — «статус не распознан», summary scheduler — «деградирован (резервный контур)»; dream/deep sleep/belief revision/paradigms/self-model/initiative — ok. Ничего не перекрашено в зелёный.

## Откат

- Ветка `release/fix-2.58.123` создана и запушена: `6e587696dc48606edc5caa9057a655d89e40502e` (2.58.123 — тот же код, что был live до релиза, + docs).
- Процедура: `git checkout 6e587696 && sudo systemctl restart admin_bot` (+ повторная проверка healthz 2.58.123). `ΔDDL=0`, миграций нет, FACTORY_SET тот же, бэкап `bot_settings` — `/home/nik/deploy-258124/bot_settings_pre.json` (537 строк).
- Второй уровень: `c128675a` (2.58.122).

## Вердикт

**Деплой: VERIFIED** — точный ревью-кандидат `39a06b88` живёт как 2.58.124, сервис healthy, NRestarts 0, каноны/Core/FACTORY_SET/embed не пострадали, квоты инструкций не вернулись.

**Релиз в целом: не закрыт (BLOCKED на привязке карты, зона PM).**
- `requirements_gate.py check --stage release --candidate 39a06b88… --deployed-commit 39a06b88… --map plans/features/p0-corrective-factcheck-speech/requirements-map.json` → **EXIT 1**, `errors=890`: карта привязана к `c128675a`, ни одна строка не имеет evidence к текущему кандидату. Само по себе это не дефект кода и не повод откатывать; это работа PM (привязка) + Reviewer (перепроверка).
- Не подтверждено по этому релизу: (1) кавычки внутри литерального URL (by design, см. выше); (2) блок Expression в system (`expression_absent` — состояние конфига); (3) публичный HTTPS-healthz (сетевой TLS с рабочей машины).

Откат остаётся готовым; при жалобе на кавычки/поведение — `6e587696`.
