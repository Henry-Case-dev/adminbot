# D4-C — corrective binding evidence A/B: traceback ↔ deployed SHA

**Слайс:** `self-diag-01` / D4-C (`SD1-D4-10`, `SD1-D4-14`).
**База:** `16fa04e77c56db44c23cb5c8a9386f6cfd756628`.
**Ветка:** `self-diag/d4-trace`.
**Код-кандидат:** `018e8d77ba76dc0afded0744820b4797417dd0a7`.
**Предыдущий кандидат:** `f93bf6f746a31de6ad6f88654cf5e920f088965d`
(его binding — `binding-d4-trace-f93bf6f7...md`; verdict Reviewer:
**Needs Fixes** по блокерам A/B, `review-d4-trace-f93bf6f7.md`).
**Этот файл** заменяет binding для текущего кандидата; исторический файл
`f93bf6f7` не изменялся.
**Docs-коммит:** этот файл; SHA фиксируется в handoff.

Артефакты на `018e8d77`:

| Файл | sha256 |
|---|---|
| `services/deploy_identity.py` | `91ee6c7d5f851072fc456f2eeedfbadeb104d5a4626c09407e318d0f7b094378` |
| `services/runtime_probes.py` | `9c9e0745a7f92ca28594a55f3061b500708203c9e6620b8fb2c932a99686126e` |
| `tests/test_deploy_identity_d4c.py` | `893e42ce7e1433672b5c00bddb0935e5bb25475aa60c5b46385111b74f8647b7` |

## 1. Блокер A — `event_before_release` больше не подменяет `deployed`

**Причина:** релизный коммит, перенесённый из `candidates` в `excluded`
(событие раньше установки релиза), получал жёсткий `"deployed": False`,
хотя он входит в `previous..deployed` и реально исполняется. Внешне это
выглядело как неразвёрнутый коммит, а `excluded_undeployed` в probe-фактах
считал его как undeployed.

**Исправление (минимальное):**

* `result["excluded"]` сохраняет исходный флаг:
  `"deployed": bool(item.get("deployed"))` вместо константы `False`;
* `blame.excluded_count` — полное число исключённых (как раньше, включая
  релизное изменение при событии до релиза);
* новый `blame.excluded_undeployed_count` — только записи с `deployed=false`;
* probe-факт `excluded_undeployed` теперь берётся из
  `excluded_undeployed_count`, а полное число видно как `excluded_total`
  (`blame.excluded_count`);
* `candidates` по-прежнему пуст, вердикт `event_precedes_release`,
  `newest_blamed=false` — семантика «не виновен» не менялась.

Инвариант теперь честный: **`deployed=false` только у коммитов вне
`deployed_sha`**.

Наблюдаемое на temp-repo (событие за 30 минут до релиза), после фикса:

```text
VERDICT event_precedes_release
CANDIDATES []
EXCLUDED 3 записи:
  C services/router.py  deployed=false reason=undeployed_commit
  C services/voice.py   deployed=false reason=undeployed_commit
  B services/voice.py   deployed=true  reason=event_precedes_release   # deployed SHA
BLAME candidate_count=0 excluded_count=3 excluded_undeployed_count=2
```

## 2. Блокер B — внутренний дедлайн всегда меньше probe-timeout

**Причина:** `budget = max(1.5, probe_timeout - 0.4)`; при
`ProbeLimits(probe_timeout_seconds=1.0)` бюджет 1.5 c > внешних 1.0 c,
поэтому collector возвращал `unavailable/probe_timeout` и терял честную
причину `correlation_timeout`. `_identity_for_correlation` использовал
`max(1.5, probe_timeout)` и имел ту же проблему.

**Исправление:** один helper

```python
def _correlation_budget(probe_timeout) -> float:
    return min(3.0, max(0.2, float(probe_timeout) - 0.4))
```

используется и для identity-сбора, и для самой корреляции. Верхняя граница
3 c удерживает git-бюджет существующего identity-контракта; нижняя 0.2 c
не даёт мгновенному таймауту. При внутреннем таймауте по-прежнему
возвращается `degraded/correlation_timeout` со всеми осями в `not_checked`
(причина не подменяется на `probe_timeout`).

Граница честности: при `probe_timeout <= 0.6` формула даёт нижний пол 0.2 c,
т.е. бюджет может совпасть с внешним лимитом — это осознанный предел
формулы, а не скрытая подмена; для реальных значений (`>= 1.0`) бюджет
строго меньше.

## 3. RED → GREEN (регрессии на текущих тестах)

RED на `f93bf6f7` (тесты новые, код сервисов возвращён к `f93bf6f7`
через `git stash`; восстановление — `git stash pop`):

```
$ pytest tests/test_deploy_identity_d4c.py -q \
    -k "event_before_release or low_probe_timeout or counts_only_truly"
FAILED test_event_before_release_does_not_blame_release_change
  E  assert False
  E   +  where False = all(<genexpr> ...)            # deployed SHA помечен deployed=false
FAILED test_low_probe_timeout_keeps_correlation_timeout_reason
  E  AttributeError: module 'services.runtime_probes' has no attribute '_correlation_budget'
FAILED test_probe_counts_only_truly_undeployed_commits
  E  assert 3 == 2                                   # excluded_undeployed считал deployed SHA
3 failed, 19 deselected in 5.44s
```

GREEN на `018e8d77`:

```
$ pytest tests/test_deploy_identity_d4c.py -q
22 passed in 19.38s
```

## 4. Тесты

Изменены/добавлены (полный файл — 22 теста):

| # | Тест | Что проверяет |
|---|---|---|
| 11 | `test_event_before_release_does_not_blame_release_change` (расширен) | `before["excluded"]`: релизный SHA остаётся `deployed=true` с причиной `event_precedes_release`; неразвёрнутый C — только `deployed=false`/`undeployed_commit`; `candidate_count=0`, `excluded_count=3`, `excluded_undeployed_count=2`, newest не обвинён |
| 21 | `test_low_probe_timeout_keeps_correlation_timeout_reason` (новый) | `_correlation_budget(1.0) <= 0.6 < 1.0`, `_correlation_budget(5.0) <= 3.0`; `ProbeLimits(probe_timeout_seconds=1.0)` + медленная корреляция → `degraded/correlation_timeout`, **не** `unavailable/probe_timeout`, все оси в `not_checked` |
| 22 | `test_probe_counts_only_truly_undeployed_commits` (новый) | probe-факты при событии до релиза: `blame_verdict=event_precedes_release`, `excluded_undeployed=2`, `excluded_total=3`, релизный SHA в `facts.correlation.excluded` с `deployed=true`, C — `deployed=false` |

Неизменённые поведения подтверждены прежними тестами того же файла:
release diff `previous..deployed` (1, 6), undeployed-исключение (1),
newest не обвиняется (1, 2), path safety/`--`/`shell=False` (8), secrets (8),
timeout/нет git/нет кадров (9, 10), чекап/инцидент (16, 20), закрытые наборы
и never-raise (17).

## 5. Прогоны

```
pytest tests/test_deploy_identity_d4c.py -q
  → 22 passed

pytest tests/test_deploy_identity.py tests/test_deploy_identity_d4b.py
       tests/test_evidence_bundle.py tests/test_diagnostic_probes.py
       tests/test_checkup_contract.py tests/test_checkup_service.py
       tests/test_checkup_handlers.py tests/test_p0_checkup_core_contract.py
       tests/test_diagnostic_policy.py -q
  → 366 passed, 1 warning

Итого на 018e8d77: 22 + 366 = 388 passed (1 warning).
```

Полный suite не запускался. Прод/настройки/промпты/БД/DDL/зависимости не
затрагивались; деплоя не было.

## 6. Границы

* Прежние ограничения D4-C в силе (preprod, локальные refs, только `.py/.pyi`,
  каппы и `truncated`, паттерновый sanitizer, один последний traceback,
  `source_ref external/commit:<sha>`, отсутствие UI/флагов).
* Блокер A: исправлена только семантика флага/счётчиков; состав `candidates`,
  вердикты, release-diff, newest и path/shell/secret-поведение не менялись.
* Блокер B: формула ровно из ревью; при `probe_timeout <= 0.6` нижний пол
  0.2 c может совпасть с внешним лимитом (зафиксировано выше).
* Диф против `f93bf6f7`: 3 файла, +114/−6 (services/deploy_identity.py +4/−2
  содержательных, services/runtime_probes.py +20/−3,
  tests/test_deploy_identity_d4c.py +88). Диф против `16fa04e7`: 6 файлов,
  +2009/−12.
* `deployed_unverified → degraded` и `+1 источник в чекапе` (страница
  6880/9000) остаются принятыми Reviewer, не менялись.

## 7. Итог для Reviewer

Требуется focused recheck блокеров A и B; остальные подтверждённые пункты
ревью не затрагивались. Статусы строк в карте Builder не меняет, approval не
заявляет. `SD1-D4-10`/`SD1-D4-14` остаются `PENDING` до решения Reviewer.
