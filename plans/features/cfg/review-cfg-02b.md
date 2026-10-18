# REVIEW-CFG-02B — независимое ревью «Лимита частоты генерации» (burst + пауза)

| Поле | Значение |
|---|---|
| Кандидат | контент `7e5edd75` (86 файлов: 85 дельты CFG-02B + `slice-graph.json` PM) + пин-фикс `7db919df` (evidence README, +13) |
| Вердикт | **Approved** — фича подтверждена кодом, прогонами и скриншотами; NF-перечень — ниже (дефер-пара + биндинг) |

## 0. Процесс-факт (зафиксирован, контент не переписывался)

Сообщение `7e5edd75` («docs(cfg): slice-graph write_scope for CFG-02B») описывает только граф: индексированный набор лейна подхватил коммит PM во время гонки индекса. **Контент полный**: `git show --name-only` = 86 позиций (совпадает со списком README, `missing=0`), ключевые sha256_12: `services/image_generation.py` = `881f6e9ee4ec`, `tests/test_cfg02b_image_freq_limits.py` = `7a7d85a94b31` (и в коммите, и в рабочем дереве). Чужих продуктовых файлов в коммите нет; «посторонние» `plans/docs/param-registry-round1025.{tsv,meta.md}` и `screen-map-round1025.md` — собственные артефакты дельты (каталог/витрина). NF-3: зафиксировать атрибуцию 85 контент-файлов в леджере.

## 1. Фича по коду

* **Единственная точка**: `image_generation.generate_and_send` — все пользовательские пути (direct-пре-гейт `maybe_handle_keyword` → `run_image_request`, tool `tool_router._generate_image`, legacy) сходятся сюда; участник протянут (`ImageRequest.requester_id` → `generate_and_send(user_id=…)`, `ctx.user_id` → tool/direct) ✓.
* **Порядок гейтов**: read-only `image_freq_state` (активная пауза → отказ, ничего не пишется) → `_reserve_or_consume` (журнал/дневная квота, CFG-02A) → `already_ok` (replay — заряд не трогается) → атомарный `image_freq_consume` **перед** платным вызовом; отказ в гонке освобождает дневной резерв (`_commit_or_release(..., error_code="freq_limit")`) ✓.
* **Отказ до платного вызова** с фактическим остатком: `retry_after_seconds` в `GenerationResult`, `image_freq_remaining_note` через существующий `format_remaining_time` («через 10 мин 20 сек (для тебя|на весь чат)»); при обоих лимитах — обе строки + оговорка; `_IMAGE_REASON_TO_CODE["freq_limit"]="cooldown"` (существующий честный код, словарь §17.2 не расширялся) ✓.
* **Scope**: `image_freq_bucket_user` — per_user+известный → user_id; per_chat → 0; per_user+неизвестный → 0 (общий запас чата, «личного обхода» нет); режим — один select (`per_user|per_chat`), мусор → `per_user` ✓.
* **Заводской OFF** (`IMAGE_FREQ_LIMIT_ENABLED=False`), master-рубильник OFF снимает enforcement (состояние сохраняется), нет runtime-БД → fail-open + честный `no_db` в витрине; **обложки Summary не затронуты** (cover-путь идёт через `generate_image_verbose`, частотного гейта там нет — тест `test_summary_cover_path_is_not_charged`) ✓.
* **Витрина**: аддитивный блок `freq` в `GET /api/workers/budget` (активность/причина/режим/источник/остаток серии/следующая доступность; `viewer_user_id`); `web/api/gates.py` добавлен в allowlist bounds-тестов с NOTE; второй счётчик не создан (тот же `throttle_state` scope `image_freq`) ✓.

## 2. L87 (смена режима) — **подтверждено**

Формулировки строк (02B.4/AC7) — «никаких скрытых сбросов счётчиков при переключении scope или перезапуске, которые позволяют обойти лимит; состояние устойчиво между воркерами». Реализация: смена режима меняет применяемый счётчик (в этом и смысл настройки), **счётчики не сбрасываются**; возврат к прежнему режиму возвращает прежний запрет (тест `test_mode_switch_does_not_reset_counters`: per_user burst=1 → допуск; switch per_chat → свежий чатовый запас, исчерпывается и запрещает; возврат per_user → персональный запрет на месте). Это не пользовательский обход (меняет админ), и «скрытого подарка» нет → трактовка **соответствует L87**; отклонений не найдено, NF не требуется.

## 3. Прогоны (мои)

| Прогон | Результат |
|---|---|
| `pytest tests/test_cfg02b_image_freq_limits.py` | **37 passed** ✓ |
| Контракт+пины (мой набор из 8 файлов: cfg02b + cfg02a-quota + daily-limit + param_catalog + frontend_tab_mapping + f8-registry (рабочая копия) + asap7-registry + soul1-capabilities) | **234 passed**, 0 failed ✓ |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY** ✓ |
| JS-sweep `tests/js/*_test.js` (node) | **PASS=87 FAIL=0** ✓ |
| `tools/ui_cfg02b_image_freq_e2e.py` | **RESULT: PASS**, `console_errors=[]`; повторный прогон не изменил committed-скриншоты (0 изменений, детерминизм) ✓ |
| RED (лог) | `34 failed / 1 passed` — состав причин (нет ключей/резолвера/поля/витрины) соответствует фиче ✓ |

Скриншоты просмотрены: `ui/02-active-per-user.png` (ON/per-user: 4 поля, человеческий «≈ 10 мин 20 сек», один select, блок «Включено и действует», «Остаток серии: 0 из 2»), `ui/04-inactive-honest.png` (честное «Включено, но не действует: состояние счётчика недоступно» / fail-open).

## 4. Каталог/freeze

`+4 ParamSpec` в существующей группе `limits_images` (enabled=False / burst=3 / cooldown=300 с / mode=per_user, тип+widget+единицы задекларированы); REGISTRY **575→579**, Settings **454→458**, categorized **550→554**, delta **164→168** (спот-сверка по каталогу и `--check`); `PARAM_CATALOG_SHA256_FOLLOWUP` и `FACTORY_SET_SHA256_12` переутверждены `tools/_cfg02b_reissue_f8.py`; `GROUPS/TAB_RULES/routes` не менялись ✓.

## 5. Отложенная пара (NF-1)

`tests/fixtures/round1025/f8_baseline.json` + `tests/test_round1025_f8_registry.py` — **uncommitted** (смешаны с vision-лейном: их `ROUTES_SHA256_F11` re-pin + CRLF). Мой контроль: на **чистом HEAD** (`7db919df`) freeze-тест даёт **6 failed** (пины счётчиков старого каталога) при зелёном `--check` (579) — осознанный временный дисбаланс, **не замаскирован** (перечислен в README §R3/§0); в рабочей копии с парой — **29 passed** ✓. План (перепрогнать `tools/_cfg02b_reissue_f8.py` и закоммитить пару после приземления vision-лейна) — разумен; **NF-1: закрыть пару до биндинга/релиза CFG-02B**.

## 6. Гейт (verbatim) и rolling-кандидат

* Как есть: `stage=review inventory=246 manual=41 scoped=17 errors=18` — `candidate mismatch` (топ-левел карты = `83ecd202` от CFG-02A) + 17 `PENDING` строк (pre-binding) — EXIT 1.
* Row-level контроль (копия карты в scratch: `candidate_commit := 7db919df7961…` + скопированный `slice-graph.json`): **нет** candidate/graph-ошибок, `scoped=17 errors=17` — только пред-бинднговые `PENDING`. Rolling-конвенция та же, что у CFG-01/02A ✓.

## NF-перечень

* **NF-1** (обязательно до биндинга/релиза): закоммитить отложенную пару `f8_baseline.json` + `test_round1025_f8_registry.py` (через `tools/_cfg02b_reissue_f8.py`) после приземления vision-лейна; на HEAD сейчас 6 красных freeze-проверок — задокументировано, не маскируется.
* **NF-2** (рутина биндинга, как CFG-01/02A): `candidate_commit` + evidence на все 17 строк; live-строки (02B.1/.2/.2.3/.6/.8, AC2/AC3) — preprod→postdeploy+RFL по конвенции.
* **NF-3**: внести в леджер атрибуцию 85 контент-файлов к `7e5edd75` (сообщение коммита описывает только граф — гонка индекса; контент полный, `missing=0`).
* Примечания (не NF): R4 — env-легacy kill-switch `image_reserve_mode` не отключает частотный лимитер (осознанно, отдельный тумблер); `no_db` fail-open честно показывается.

## Итог

Лимитер реализован в заявленном объёме: единая точка перед платным вызовом, честный отказ с фактическим остатком до платной попытки, per-user/per-chat, заводской OFF, изоляция обложек, витрина с honest-полями; числа и RED/GREEN сходятся, каталог/реестр консистентны. **Approved** (NF-1 — до биндинга/релиза; NF-2/NF-3 — рутина).
