# ASAP 3 Corrective → релиз 2.58.129 @ `79ec3726` — привязка доказательств

Дата снимка: **2026-10-25 08:56, UTC+12**. Lane: `ASAP3-BIND-RESIDUAL` (writer: карта ASAP3 + evidence).
Прод/SSH/Telegram не использовались; код не менялся; все проверки — read-only по локальным Git-объектам и локальный pytest.

Кандидат = деплой: **`79ec3726c0919e6ffeaeb235be4f8d6326c4e12a`** (2.58.129).
Факт деплоя (read-only из `plans/features/cfg/evidence/release-258129.md`, коммит `1b4e70a3`):
`/healthz` HTTP 200 `{"status":"ok","version":"2.58.129"}`, NRestarts 0, 0 ERROR/Traceback в журнале нового PID,
`factory_set_fingerprint()` = `f12130fbccb1` (как на 2.58.128), ΔDDL = 0.

## 1. На каком дереве получены прежние поведенческие доказательства и что это значит для 2.58.129

Поведенческие доказательства фичи (S1–S10, A1–A16, hidden-limits, UI) получены на `9ed68ee8` (прод 2.58.118).
Релиз 2.58.129 собран поверх `24ca634b` (2.58.128) + cover-style fix `16a0dbbf`; `merge-base(24ca634b, 79ec3726) = 24ca634b`.

Байтовое сравнение **всех 30 файлов, изменённых ASAP3-коммитами** (`673d142c`, `5ac005ab`, `d8af77c3`, `92056406`,
`81cdaa28`, `0d57ec24`, `667dc434`, `3d3a0777`, `562f8fe5`, `d47c2aab`, `ede5096a`, `47ed033e`) между `24ca634b` и `79ec3726`:

| Результат | Кол-во | Комментарий |
|---|---|---|
| IDENTICAL (те же байты) | **29 / 30** | включая `services/style_policy.py`, `services/prompt_style_blocks.py`, `services/prompt_composer.py`, `services/summary_aliases.py`, `services/chat_params.py`, `services/direct_chat_service.py`, `web/api/speech.py`, `web/app.js`, 4 файла `tests/test_asap3_*.py` |
| DIFFERENT | 1 / 30 | `tests/test_tool_coordinator_round1026.py` — побочный тест, доказательством ASAP3 не используется |

Манифест с sha256 по каждому файлу: `evidence/raw/carrier-sha-24ca634b-vs-79ec3726.txt` (`TOTAL=30 IDENTICAL=29 DIFFERENT=1`).
Следствие: поведение кода ASAP3 в 2.58.129 (`79ec3726`) идентично дереву, на котором выполнен свежий прогон ниже;
прежние доказательства не переписываются, а переносятся на текущий кандидат с указанным ограничением
(менялся только побочный тест, не входящий в доказательства).

## 2. Свежий прогон на текущем дереве (независимое подтверждение, не только перенос)

```
& .venv\Scripts\python.exe -m pytest tests/test_asap3_style_hint_limits.py tests/test_asap3_identity_aliases.py \
    tests/test_asap3_hidden_limits.py tests/test_asap3_acceptance.py -q
62 passed
```

Сырой лог: `evidence/raw/pytest-asap3-62-79ec3726-carrier.txt` (прогон 25.10.2026, 4.64 s).
Состав: style hint limits 16 + identity aliases 22 + hidden limits 16 + acceptance 8 = 62.

## 3. Решения по 13 строкам класса AGENT_CHECK

| Строка | Решение | Доказательство | Ограничение |
|---|---|---|---|
| GOV-NO-NEW-LLM | VERIFIED | Статический аудит диапазона ASAP3-коммитов: 2156 добавленных строк в 10 затронутых файлах, 1 совпадение по шаблону LLM-вызова — метка канала `"stream_chat_completion"` в тестовом списке покрытия, ни одного нового вызова LLM; SOUL-14.2 телеметрия extent фиксирует `0 LLM` | Живой счётчик вызовов на ответ не замерялся; вывод — из отсутствия новых точек вызова |
| GOV-KEEP-SAFETY-LIMITS | VERIFIED | `evidence/limits-inventory.md` §2 (технические лимиты не отключены), 16 hidden-limits тестов в прогоне §2: WARN с числами, `422`/fatal на save, `budget_excluded` | Поведение на живом проде не наблюдалось |
| HID-USER-SETTINGS | VERIFIED | `evidence/ui-phase.md` (строка «Ограничения подсказки» в разделе «Стиль письма», 2 независимых лимита, OFF по умолчанию) + скриншоты `evidence/shots/style_limited_390.png`, `inspector_limited_desktop.png` + тесты style-полосы | TMA на живом проде не проверялся |
| HID-NO-BULK-OFF | VERIFIED | `evidence/limits-inventory.md` §1–2: ни один защитный лимит не отключён; в диапазоне ASAP3-коммитов единственное изменение `config/settings.py` — строка `APP_VERSION` (заводские значения не тронуты) | Сравнение по репозиторию, не по живой PG |
| HID-NO-GLOBAL-EDITOR | VERIFIED | `evidence/ui-phase.md`: настройки в своих разделах, отдельного глобального редактора сотен параметров нет; `web/app.js` в 2.58.129 байт-идентичен проверенному (§1) | — |
| HID-NO-BUDGET-BREAK | VERIFIED | `evidence/limits-inventory.md` §2 (аддитивный бюджет композера не изменён, лимиты видны как `budget_excluded`), acceptance-тесты бюджета в прогоне §2 | Замер «не хуже baseline» по живым запросам не снимался |
| GOV-ROLES-BUILDER | VERIFIED | `plan.md` + `arch-design.md` §1 + фазовые отчёты `evidence/style-phase1.md`, `evidence/identity-phase.md`, `evidence/ui-phase.md`, `evidence/limits-inventory.md`: реализация соответствует согласованному набору, отклонений не заявлено | — |
| GOV-ROLES-REVIEWER | VERIFIED | `review-identity-r2.md`, `review-ui-r2.md`, `review-limits-r3.md` — независимые вердикты по трём срезам | — |
| GOV-ROLES-DEVOPS | VERIFIED | Факт штатного деплоя 2.58.129 = `79ec3726` с postdeploy-проверками (healthz 200/2.58.129, NRestarts 0, 0 ERROR/Traceback, ΔDDL=0) — `plans/features/cfg/evidence/release-258129.md` (коммит `1b4e70a3`) | — |
| REPORT-FORMAT | VERIFIED | `final-report.md` §9: русский язык, текущее время снимка, отдельный прогрессбар карты | — |
| AUD-PROD-VERIFY | **AGENT_CHECK** (PENDING) | `arch-design.md` §1 фиксирует фактический код и заводские значения; активные значения PostgreSQL не снимались | Нужен read-only SELECT (см. §4.1) |
| MIG-SCOPES | **AGENT_CHECK** (PENDING) | `migration.md` §5 — план, а не замер | Нужен read-only SELECT по трём уровням (см. §4.2) |
| ACC-09 | **READY_FOR_LIVE** | 62 регрессионных теста PASS (§2) | «Реально действующая конфигурация» 2.58.129 не проверялась (см. §4.3) |

## 4. Точные оставшиеся проверки (read-only, без отправки сообщений)

1. `AUD-PROD-VERIFY` — активные значения по трём дефектам из PG:
   `SELECT scope, key, value FROM chat_params WHERE key IN ('style.policy','limits.summary_aliases') ORDER BY scope, key;`
   плюс заводские значения из `services/style_policy.py` (defaults) — одной таблицей «факт/заводское/путь применения».
2. `MIG-SCOPES` — эффективное значение `style.policy` на трёх уровнях (factory → global → chat):
   `hint_limits.sources` из того же SELECT; уровень `default` — из кода, `global`/`chat` — из строк выше.
3. `ACC-09` — после снятия 1–2: прогнать acceptance-полосу на живом стенде 2.58.129 (без сообщений в чаты) и зафиксировать
   конфигурацию, на которой шли тесты.
4. `ACC-03`, `A16` — остаются `READY_FOR_LIVE`: нужно реальное исходящее сообщение / живой `diag aliases` (в этой полосе запрещено).

Ограничение полосы: прод/SSH/Telegram запрещены, поэтому пункты 1–4 не выполнялись и не помечены `VERIFIED`.
