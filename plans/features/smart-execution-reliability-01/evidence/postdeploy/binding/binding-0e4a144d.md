# Binding 0e4a144d — ребиндинг карт SMART-EXECUTION-RELIABILITY-01 на выкаченный кандидат 2.58.200

Дата: 2026-11-14. Автор: PM (single writer двух карт). Статус: выполнено; release/delivery gate —
шаг Orchestrator, здесь не заявляется.

Карты:

| Карта | sha256 после ребиндинга |
|---|---|
| `plans/features/smart-execution-reliability-01/requirements-map.json` | `5a6a6d67d498e421cd6e51e25861e5bf067caae1fdb5a94811b908d6f90e02d8` |
| `plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json` | `c68601e8ebd1408eadb1f84eecfb2e25728fae47731acfedc1e7b09a6a7884d2` |

## 1. Выкаченная идентичность (проверено git)

```
$ git cat-file -t 0e4a144db476a1535ae3a2b79a7cce30354ad866
commit
$ git log --oneline -1 0e4a144db476a1535ae3a2b79a7cce30354ad866
0e4a144d chore(release): 2.58.200 - bump APP_VERSION и всех пинов версии
$ git branch -a --contains 0e4a144db476a1535ae3a2b79a7cce30354ad866
  release/2.58.200
  remotes/origin/release/2.58.200
```

Рабочий checkout: `master` @ `ce83dbe6`; выкаченный SHA присутствует локально и является вершиной
`release/2.58.200`. База/цель откатa: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199).
Production-факты (healthz, identity, manifest, schema, журнал, effective config) — в
`release-evidence/2.58.200/`; в этом документе они не пересматриваются.

## 2. Проверка предков (ancestry)

Каждый `candidate_commit`, который реально встречается в `evidence[]` обеих карт, проверен на
принадлежность выкаченному дереву:

```
$ git merge-base --is-ancestor <candidate> 0e4a144db476a1535ae3a2b79a7cce30354ad866
# exit 0 => ANCESTOR
```

Проверено 20 различных значений из доказательств (19 lane-кандидатов + база `d20a7f73`); результат —
**все ANCESTOR**, ни одного отсутствующего объекта:

| Кандидат (полный SHA) | Встречается в доказательствах | Результат |
|---|---|---|
| `1d9cf251f30e2f0c5243a0a23aab3a43cdfc3029` (reviewed train tip) | 796 + 672 | ANCESTOR |
| `8fc8b534ebb993fca29fc2f86b7aef2d95796660` (A+B) | 318 | ANCESTOR |
| `b204c66cf92b4b8e530bcdad756ad1d4d6b1a33c` (S12 код) | 210 | ANCESTOR |
| `f55fdc6ea525dc8771e6e2100e4da5f609c2b637` (D) | 194 | ANCESTOR |
| `d238f808d221f5d5c9e2e1fe8b2da8ae668d97c4` (H) | 171 | ANCESTOR |
| `d43fa1fd17aebd03f94654b0476483c2c68f5e8c` | 149 | ANCESTOR |
| `2382cc92666031ed43f231ab2a27619b089c302f` (F) | 117 | ANCESTOR |
| `cffc9fb29bf7817bcf6658d0a758332f5b1021bb` (G) | 94 | ANCESTOR |
| `18fa4d593591b8438b2e3832fd7aa8e6af478064` (E) | 90 | ANCESTOR |
| `76d6067893238cb71e66cca73470e82c32762737` (I1) | 69 | ANCESTOR |
| `5e87ed486e05c15f12a4ea2b6860f42b1d132947` (C2/C3) | 63 | ANCESTOR |
| `d20a7f730715ba9e9cba7673c0557794979be339` (база 2.58.199) | 50 | ANCESTOR |
| `d471309a7a2ba9ac21ab380064accf771bc02751` | 40 | ANCESTOR |
| `9be4227eb12faa2c59a0a2ca4d1ee7384ec171d6` (I2) | 34 | ANCESTOR |
| `36dd6b232bf2705cc470764a7ab71451c5c49fdf` (C1) | 32 | ANCESTOR |
| `4bf114007e1e9549609b2259403c89282e04b5aa` (I4) | 22 | ANCESTOR |
| `ffe417d0333ba15446db0c4de7b66c302f4fe2fe` (S13) | 756 (FC) | ANCESTOR |
| `80c83d24ed7c08b6087dc6268676d1f41e09159d` (S14) | 483 (FC) | ANCESTOR |
| `9a89e3daf12cd55bba0ebbaf532f332810748a14` (S15) | 243 (FC) | ANCESTOR |
| `6953f1a6a81a7a1d9ae8a5beb4ff6111cc575cc0` (S16) | 172 (FC) | ANCESTOR |

Примечание к полноте: список Orchestrator содержал 18 lane-кандидатов; PM дополнительно нашёл в
`evidence[]` пять кандидатов, которых в том списке не было (`8fc8b534`, `d43fa1fd`, `d471309a`,
`ffe417d0`, `6953f1a6`), и проверил их тем же способом. Ни один кандидат из доказательств не остался
непроверенным.

## 3. Что именно сделано с доказательствами

Правило: каждая запись `evidence[]`, у которой `candidate_commit != 0e4a144d…`, получает
`candidate_commit = 0e4a144db476a1535ae3a2b79a7cce30354ad866`, а исходный кандидат сохраняется в
`bound_from_candidate` (если поле уже было — прежнее значение не перезаписывается: это исходный
lane-кандидат, а не промежуточный хоп). Остальные поля (`type`, `ref`, `observation`,
`artifact_path`, `artifact_sha256`, `verdict`, `reviewer_role`, `approved_postrelease_wait`)
не изменялись ни в одной записи; ни одна запись не удалена и не добавлена, кроме S0 (см. §5).

| Карта | Записей перебинжено | `bound_from_candidate` добавлено | прежнее `bound_from_candidate` сохранено | всего записей после |
|---|---|---|---|---|
| `requirements-map.json` | 2449 | 1874 | 575 | 2457 |
| `requirements-map-fc-amendment.json` | 2326 | 1658 | 668 | 2326 |

Разбивка по исходному кандидату (immediate candidate → deployed):

`requirements-map.json`: `1d9cf251` 796, `8fc8b534` 318, `b204c66c` 210, `f55fdc6e` 194,
`d238f808` 171, `d43fa1fd` 149, `2382cc92` 117, `cffc9fb2` 94, `18fa4d59` 90, `76d60678` 69,
`5e87ed48` 63, `d20a7f73` 50, `d471309a` 40, `9be4227e` 34, `36dd6b23` 32, `4bf11400` 22.

`requirements-map-fc-amendment.json`: `ffe417d0` 756, `1d9cf251` 672, `80c83d24` 483,
`9a89e3da` 243, `6953f1a6` 172.

## 4. Талли до/после

### `requirements-map.json` (828 обязательных строк, 99 уникальных req_id)

| | до | после |
|---|---|---|
| VERIFIED (строк) | 22 | 652 |
| REVIEW (строк) | 630 | 0 |
| READY_FOR_LIVE (строк) | 176 | 176 |
| VERIFIED (уникальных id) | 6 | 83 |
| REVIEW (уникальных id) | 77 | 0 |
| READY_FOR_LIVE (уникальных id) | 16 | 16 |

### `requirements-map-fc-amendment.json` (705 обязательных строк, 87 уникальных req_id)

| | до | после |
|---|---|---|
| VERIFIED (строк) | 0 | 606 |
| REVIEW (строк) | 606 | 0 |
| READY_FOR_LIVE (строк) | 99 | 99 |
| VERIFIED (уникальных id) | 0 | 79 |
| READY_FOR_LIVE (уникальных id) | 8 | 8 |

Каждая строка, переведённая в VERIFIED, получила поле
`verified_via: "deployed 0e4a144d (2.58.200); evidence rebound from <исходные кандидаты> (ancestor|ancestors)"`.
Статусы live-строк не менялись; `live_required`/`live_when`/`postrelease_wait` не менялись.

## 5. Baseline S0: implementation evidence

Deploy stage требует implementation evidence для каждой обязательной строки, а 8 baseline-строк
(`SXR-0-01..04`, source ids `MAN-SXR-0-01-14/16/18`, `MAN-SXR-0-02-22/1568`,
`MAN-SXR-0-03-24/26`, `MAN-SXR-0-04-28`) несли только review-запись.

Добавлена одна запись типа `inspection` на строку (8 записей), `candidate_commit = 0e4a144d`,
`bound_from_candidate = d20a7f73`, артефакт
`plans/features/smart-execution-reliability-01/evidence/review-s0-d20a7f73.md`
(sha256 `cd93c602f99e60e66621e100870697568398c71c7b678020b828b685b6451f2a`). Наблюдение в каждой
записи дословно соответствует содержимому артефакта: секции `SXR-0-0X VERIFIED`, `Implementation`,
`Test validity`, `Independent challenge` (54 задачи/13 закрытых без позиций/40 из 40 открытых,
`execution_queue.complete=true, issues=[]`, единственный SMART-эпик на позиции 1, отсутствие
checkup_tools_budget и второго tool-loop, отсутствие новых архитектур/Human Gate). Никаких новых
наблюдений не выдумано: это read-only inspection, выполненный при ревью базы.

## 6. Map-level изменения (обе карты)

- `candidate_commit` = `0e4a144db476a1535ae3a2b79a7cce30354ad866` (в FC-карте было `""`;
  в основной — `d20a7f73`).
- `deployed_commit` = `0e4a144db476a1535ae3a2b79a7cce30354ad866`.
- `deployment_state`: `epic_deployed=true`, `deployed_version="2.58.200"`, `note` переписана под
  новое состояние (реброунд, предки, что осталось live); прежняя до-деплойная формулировка
  сохранена в git-истории (`ce83dbe6`).
- `status_note` переписана (в FC-карте прежний текст «All rows PENDING…» был устаревшим).
- Добавлен `delivery_evidence` — 4 записи `type: "production"`, `candidate_commit =
  deployed_commit = 0e4a144d`:

| Артефакт | sha256 | Наблюдение (кратко) |
|---|---|---|
| `plans/features/smart-execution-reliability-01/release-evidence/2.58.200/postdeploy-health.txt` | `d13edb452a5142d3ecf0490d59a232e38cb0e8a6a7278e5cfe17a55857826da4` | healthz 200 `{"status":"ok","version":"2.58.200"}`; unit active (pid 709883, start 2026-11-14 05:18:59 UTC); schema `user_version=47`, `pending=[]`; журнал с момента старта: tracebacks 0, errors 0, warnings 1 (pre-existing summary_memory FTS-only) |
| `…/identity.txt` | `8e91665c181f50762417f8cf802172e4ac13b695b7b531092fd730131d34f452` | `manifest.deployed_sha == HEAD == 0e4a144d…`; `manifest.version == healthz version == APP_VERSION == 2.58.200`; `previous_sha = d20a7f73…` (2.58.199); `release_branch=release/2.58.200`; `dirty_tracked=false` |
| `…/effective-config.txt` | `5e83a7cafda29785798cf34eddae6ab5808bbc6823d0b795a4c7530a88712ed1` | factory/env: окно 1000000, `MCA_TOOL_MAX_*`=0, timeout 0.0, `BUDGETS_ENABLED` только factory; persisted `flags.budgets_enabled=false` + overrides (false/false/absent) ⇒ effective budgets OFF во всех трёх чатах; capacity чат-модели: catalog 1048576/32768 verified; `bot_settings` 547→548 (одна factory-строка), пользовательские значения не перезаписаны |
| `…/deploy.md` | `2f224b4c2b1f723e5f7548b975fba5a76fdc4072db4ca0c2c91fcdb94ece166f` | кандидат = reviewed train tip `1d9cf251` + version-pin bump (30 файлов/31 строка); pre-deploy наборы 362/276/856+4 pre-existing/1037+12 pre-existing; post-deploy сверка HEAD/branch/APP_VERSION/manifest/health/schema/журнал; откат на `d20a7f73` |

## 7. Гейты (полный stdout сохранён)

Команды (глобальный инструмент `C:\Users\main\.config\opencode\tools\requirements_gate.py`, не
untracked копия в корне репозитория):

```
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check \
  --map plans/features/smart-execution-reliability-01/requirements-map.json \
  --stage review --candidate 0e4a144db476a1535ae3a2b79a7cce30354ad866 --repo C:\Code\Python\adminbot
py -3 ... --stage deploy --candidate 0e4a144d… --repo C:\Code\Python\adminbot
# те же две команды для requirements-map-fc-amendment.json
```

| Файл stdout | exit | Итоговая строка |
|---|---|---|
| `evidence/postdeploy/binding/gate-review-requirements-map.txt` | 1 | `stage=review inventory=509 manual=359 scoped=828 errors=1` — единственная ошибка `FAIL: review stage requires --slice` (структурное требование CLI) |
| `evidence/postdeploy/binding/gate-deploy-requirements-map.txt` | 0 | `stage=deploy inventory=509 manual=359 scoped=828 errors=0` |
| `evidence/postdeploy/binding/gate-review-requirements-map-fc-amendment.txt` | 1 | `stage=review inventory=396 manual=380 scoped=705 errors=1` — та же структурная ошибка `--slice` |
| `evidence/postdeploy/binding/gate-deploy-requirements-map-fc-amendment.txt` | 0 | `stage=deploy inventory=396 manual=380 scoped=705 errors=0` |

Про review-stage: команда без `--slice` структурно отвергается гейтом, но `scoped` при этом равен
всем 828/705 строкам, поэтому построчные проверки (bound evidence, существование артефактов и их
SHA, Reviewer-approval, implementation evidence) фактически выполнялись — и дали **ноль**
построчных ошибок. Отдельный per-slice прогон на выкаченном кандидате невозможен без правки
`slice_candidate_bindings` (гейт берёт кандидата слайса оттуда), поэтому канонический путь для этого
релиза — whole-map прогоны.

Информационно (не является релизным вердиктом, шаг Orchestrator): PM выполнил scratch-прогон
`--stage delivery --candidate 0e4a144d… --deployed-commit 0e4a144d…`; обе карты вернули
`engineering_delivery=PASS`, `acceptance=PENDING_FUTURE_EVIDENCE`, `errors=0`, deferred =
16 SMART-id и 8 FC-id. Официальный delivery/release gate должен выполнить и записать Orchestrator.

## 8. Независимая проверка PM

1. **Семантический дифф с HEAD-версией карт** (скрипт PM, scratch): 828 и 705 строк сопоставлены
   построчно; проверено, что вне `evidence`/`status`/`verified_via` не изменилось ни одно поле; ни
   одна запись evidence не удалена; в каждой записи изменились только `candidate_commit` и
   `bound_from_candidate`; ни одна live-строка не сменила статус; отсутствие `verified_via` у
   не-VERIFIED строк. Результат: **0 проблем** в обеих картах.
2. **Аудит артефактов**: все 2457 (SMART) и 2326 (FC) записей указывают на существующий
   repo-relative путь, `artifact_sha256` совпадает с фактическим файлом. Плохих: 0.
3. **Аудит статусов**: 0 id без Reviewer-approval, 0 id без implementation evidence, 0 live-строк с
   неполным/несовпадающим `approved_postrelease_wait`, 0 противоречий статуса внутри одного req_id.
4. JSON обеих карт валиден, UTF-8, 2-space indent, CRLF как в исходных файлах (roundtrip-проверка
   дала байт-в-байт совпадение до правок).

## 9. Что осталось НЕ-VERIFIED (ровно 24 id, все live/postdeploy)

Ни одной обязательной строки в состоянии `PENDING`, `FAILED`, `BLOCKED_REAL_HUMAN_GATE` или
`REVIEW` не осталось. Не VERIFIED — только live-строки, у которых `live_required=true`,
`live_when=postdeploy`, статус `READY_FOR_LIVE` и уже одобренный Reviewer `postrelease_wait`
(причина: нужны реальные production-наблюдения; план — `evidence/postdeploy/live-canary-plan.md`):

SMART (16): `SXR-A1-04`, `SXR-F2-01`, `SXR-F4-01`, `SXR-H3-01`, `SXR-H4-01`, `SXR-I1-01`,
`SXR-I2-01`, `SXR-K3-01`, `SXR-L1-01`, `SXR-L2-01`, `SXR-L3-01`, `SXR-L4-01`, `SXR-L5-01`,
`SXR-L6-01`, `SXR-L7-01`, `SXR-L8-01`.

FC (8): `SFC-5-10`, `SFC-7-06`, `SFC-12-02`, `SFC-12-07`, `SFC-12-09`, `SFC-13-01`, `SFC-13-03`,
`SFC-14-03`.

## 10. Semantic caveats (не скрывать от Orchestrator/Reviewer)

Ребиндинг выполнен по механическому правилу (Reviewer-approval + implementation evidence +
существующий артефакт). Три id заслуживают отдельного решения, потому что их acceptance называет
артефакты/наблюдения, которых пока физически нет, хотя формальные условия (a)–(c) выполнены:

| id | строк | что в acceptance | что реально в доказательствах | рекомендация |
|---|---|---|---|---|
| `SXR-M3-01` | 14 | приложенные trace с request/correlation ID, effective settings, provider/model, capacity, числом раундов/вызовов, финальным payload, deployed SHA | Reviewer approval + inspection + pytest-логи; trace-артефакта нет. Reviewer в `binding-s12-final-b204c66c.md` прямо относил «journal/final traces» к postdeploy | после live-canary приложить реальные trace (diagnostics-канал даст их) либо вернуть строку в READY_FOR_LIVE с одобренным wait |
| `SXR-M4-01` | 6 | эпик закрывается после дефектов/ревью/интеграции/релиза и доступного production smoke | production smoke действительно наблюдён (delivery_evidence), но «закрытие эпика» — решение Orchestrator после 24 live id | не трактовать VERIFIED этой строки как закрытие эпика |
| `SXR-M4-02` | 3 | отложенные owner_live_checks зарегистрированы отдельно и не блокируют DONE; агентские проверки не переклассифицированы | инвариант выполним документно (24 live-строки — агентские, owner-задач нет), Reviewer относил M4 к postdeploy | подтвердить при closure-аудите |

Ещё 11 строк с «production»-словом в acceptance (`SXR-A3-02`, `SXR-E3-01`, `SXR-E4-01`,
`SXR-M1-01`, `SXR-M2-04`, `SXR-0-02`, `SXR-I1-02`, `SFC-1-02`, `SFC-1-04`, `SFC-5-01`, `SFC-8-01`,
`SFC-10-07`) — это процессные/исследовательские требования (порядок работ, аудит очереди, фиксация
текущих значений, причина production-инцидента), они удовлетворяются inspection/review-артефактами и
не требуют новых production-наблюдений; их VERIFIED опирается на эти артефакты.

## 11. Честные ограничения

- 28 записей типа `production` в SMART-карте (`SXR-1-01`, `SXR-1-02`) — это baseline-recon на
  **2.58.199** (`d20a7f73`): их `observation` прямо говорит про 2.58.199. Они перебинжены по общему
  правилу, происхождение сохранено в `bound_from_candidate`; доказательством работы **2.58.200** они
  не являются — за это отвечает `delivery_evidence` (2.58.200) и будущие live-canary.
- `slice_candidate_bindings` в обеих картах **не менялись**: там остаются lane-кандидаты уровня
  review. Поэтому scoped-прогоны `--slice` на `0e4a144d` получат `candidate mismatch`; для этого
  релизного поезда каноничны whole-map гейты. Если Orchestrator захочет scoped release, bindings
  нужно обновлять отдельным решением, а не молчаливой правкой.
- Ни одна live-строка не переведена в VERIFIED; ни одно `approved_postrelease_wait` не создано и не
  изменено PM (это право Reviewer).
- Release/delivery gate не заявляются выполненными этой работой.

## 12. Файлы

- `plans/features/smart-execution-reliability-01/requirements-map.json` (обновлена)
- `plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json` (обновлена)
- `plans/features/smart-execution-reliability-01/evidence/postdeploy/binding/gate-{review,deploy}-{requirements-map,requirements-map-fc-amendment}.txt`
- `plans/features/smart-execution-reliability-01/evidence/postdeploy/binding/binding-0e4a144d.md` (этот файл)
- `plans/features/smart-execution-reliability-01/evidence/postdeploy/live-canary-plan.md`
