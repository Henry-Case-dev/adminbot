# D4-C A/B fix - независимое re-review SD1-D4-10 / SD1-D4-14

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `018e8d77ba76dc0afded0744820b4797417dd0a7`, docs `6474c570703bca5a814678564473257f47bd6285`.
База: `16fa04e77c56db44c23cb5c8a9386f6cfd756628`; предыдущий кандидат `f93bf6f7` (Needs Fixes A/B).
Diff `f93bf6f7..HEAD`: `deploy_identity.py`, `runtime_probes.py`, D4-C тест и evidence;
release-diff/undeployed/newest/path/shell/secret/probe/checkup код не менялись.

**Вердикт: Approved для D4-10/D4-14.** Блокеры A и B закрыты; остальные
подтверждённые D4-C-инварианты сохранены. D4/self-diag DONE не объявляется.

## 1. Блокер A - deployed сохраняется в excluded

`services/deploy_identity.py:1816-1860` теперь сохраняет исходный флаг
(`"deployed": bool(item.get("deployed"))`), а `excluded_undeployed_count`
считает только `deployed=false`; `excluded_count` остаётся полным. Probe
отдаёт `excluded_undeployed` из нового счётчика и `excluded_total`.

Независимый temp-repo, событие за 30 минут до релиза:

```text
VERDICT event_precedes_release
COUNTS candidate=0 excluded=3 excluded_undeployed=2
EXCLUDED [
  C  deployed=false reason=undeployed_commit,
  C  deployed=false reason=undeployed_commit,
  B  deployed=true  reason=event_precedes_release
 ]
DEPLOYED_SHA B, NEWEST_BLAMED False
```

Deployed SHA больше не маскируется под undeployed; `candidates=[]`,
`newest_blamed=false`. A снят.

## 2. Блокер B - internal deadline меньше probe-timeout

`_correlation_budget(probe_timeout) = min(3.0, max(0.2, probe_timeout - 0.4))`
используется для identity и correlation. Независимые значения:

```text
budget(1.0)=0.6, budget(5.0)=3.0, budget(0.6)=0.2
ProbeLimits(probe_timeout_seconds=1.0) + slow correlation
-> status=degraded, reason_code=correlation_timeout,
   not_checked = все 6 осей
```

Вместо `unavailable/probe_timeout` возвращается честный
`degraded/correlation_timeout`; формула и floor ≤0.6 соответствуют binding.
B снят.

## 3. Тесты и mutation

- `tests/test_deploy_identity_d4c.py` -> **22 passed**.
- Impacted set (10 файлов D4/D3/D6) -> **388 passed**, 1 warning.
- Прогон с `--noconftest`: project conftest в этом worktree зависает на SSL/
  сетевом fixture; D4-C тесты conftest-фикстуры не используют.
- **Independent mutation:** в отдельном worktree @ `018e8d77` возвращён
  `"deployed": False` для excluded; `test_event_before_release...` ->
  **1 failed** (deployed SHA снова false); restore -> **22 passed**.
- RED на `f93bf6f7` по binding: 3 failed; GREEN 22.

## 4. Строки D4

- `SD1-D4-10` и `SD1-D4-14`: **REVIEW**-кандидат; A/B независимо проверены.
- Остальные D4-строки (14 REVIEW/3 READY) не пересматривались и не менялись;
  diff их файлы не затрагивает. D4/self-diag DONE не объявляется.
- `.gitignore` risk - BACKLOG PM, не D4-код.
- `deployed_unverified -> degraded` и page 6880/9000 ранее приняты, не менялись.

## 5. Три опоры

- **Implementation:** прочитаны diff A/B, `excluded`/counters, probe facts,
  `_correlation_budget`, identity/correlation deadlines; release-diff,
  newest, path/shell/secret и checkup не менялись.
- **Test validity:** 22/388 запусканы; assertions A/B прочитаны; mutation
  hardcoded false red/restore green; independent event-before и low-timeout.
- **Independent challenge:** deployed SHA в excluded `deployed=true`; C только
  false; `excluded_undeployed=2`, total=3; probe_timeout=1.0 -> degraded/
  correlation_timeout; budgets 1.0->0.6, 5.0->3.0.

## 6. Итог

**Approved** для D4-10/D4-14 на `018e8d77` / `6474c570`. D4/self-diag DONE
не объявляется; остальные D4-строки и PM-синхронизация вне этого review.
Продуктовый код/настройки/прод не менялись; деплоя не было; mutation
worktree и probe-run закрыты.

