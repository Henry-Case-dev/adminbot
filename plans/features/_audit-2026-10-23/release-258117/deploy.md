# DEPLOY-258117 — выкат 2.58.117 на прод (24.10.2026)

## Итог

**PASS.** Прод работает на **2.58.117** (код `724b77ac`), healthz 200, сервис `active`,
каноны L1/L2 и fingerprint не изменились, повторной миграции канонов нет, embedding
adopt/build не запускался, B11 не зелёный при `attention`/`unknown`, путь отката проверен.

## Источник деплоя

| Параметр | Значение |
|---|---|
| **DEPLOY_SOURCE (код)** | commit `724b77acb8953d1dc5c159b0fac3817a3860dace` (bump-коммит 2.58.117) |
| Tip поезда (docs/evidence) | `9dfd6db6f94b604f65bb5f3e70903c09f55e8e4c` — **не выкатывался**, деплой строго на `724b77ac` |
| Финальный HEAD на сервере | `724b77ac` (detached HEAD), tracked-дерево чистое (`TRACKED_DIRTY=0`), untracked 13 (`.env` и пр. не тронуты) |
| Предыдущее состояние | HEAD `4f64d9c7` (docs-коммит поверх кода `e9f7595b`), healthz `2.58.114`, `active`, MainPID `812309`, NRestarts `0` |
| Версия приложения | `2.58.117` (healthz + `APP_VERSION` в `config/settings.py`) |
| Зависимости | `REL_DELTA=0` (delta `requirements.txt`/`requirements-dev.txt`/`pyproject.toml`) → `pip install` не требовался |
| ΔDDL | **0** (schema/migration-файлы и DDL-токены в периметре отсутствуют — совпадает с `ddl-check.txt` поезда) |
| **MUTABLE_WORKTREE_REQUIRED** | **нет** — прод разворачивается из неизменяемого commit в серверном чекауте, локальное дерево для деплоя не используется |

## Деплой

1. `git fetch origin master --prune` → `origin/master` `845d40eb..9dfd6db6`; `724b77ac` доступен (`TYPE=commit`).
2. `git checkout -fq 724b77ac` → `HEAD_POST=724b77ac`, `TRACKED_DIRTY=0`, `APPVER="2.58.117"`.
3. `systemctl restart admin_bot` (rc 0, T0 `2026-10-23T16:59:54Z`).
4. Healthz: `TRY1=502`, `TRY2=502`, `TRY3=200` → `{"status":"ok","version":"2.58.117"}`.
5. PID после старта: **MainPID `847992`**, `NRestarts=0`, `ExecMainStatus=0` (подтверждено в конце прогона: те же значения, healthz снова 200/2.58.117 в `17:01:00Z`).

## Пост-проверки

| # | Пункт | Факт | Вердикт |
|---|---|---|---|
| 1 | healthz 200, версия 2.58.117, active | `{"status":"ok","version":"2.58.117"}`, `SVC=active`, MainPID 847992, NRestarts 0, ExecMainStatus 0 | **PASS** |
| 2 | Каноны L1/L2 прежние, повторной миграции нет, fingerprint | Журнал: `PROMPT_MIG=17` = 7× `[prompt_migration] уже новый канон` + 10× `кастом юзера — НЕ трогаем`; строк `канон обновлён` — **0**. Read-only PG до и после рестарта идентично: **L1 `6c2ddc17c998`** (`prompts.direct_l1_planner_system_prompt`, 8261, `known_canon=True`), **L2 `83ff62bbee40`** (`prompts.direct_chat_verbalizer_system_prompt`, 3081, `known=True`), `factory_set_fingerprint()` = **`0163a686c401`** (до и после). `CRITICAL=0`, `ERROR=0`, `Traceback=0`, `database is locked=0`, `PROMPT_RB=0`, `withheld=0` | **PASS** |
| 3 | Embedding: adopt не повторён, BUILD_START=0, generation active, serviceable | `ADOPTED=0`, `BUILD_START=0`; журнал `SmartModule: embedding index serviceable \| index=graph_facts_vec \| class=ADMITTED_COMPATIBLE`. SQLite: `graph_facts_vec` gen1 `status=active`, `activated_at=1792734815` (прежний adopt от 2.58.113 — **новая генерация не создавалась**), fp `96f80838f683e1cb`, `config_revision=adopt1:e540d4ad…` (тот же). `graph_facts=20 205`, `graph_facts_vec=20 318`, eligible `15 943`, `user_version=37` | **PASS** |
| 4 | Style: `hint_limits` отсутствует, `dash` активен | PG `style.policy` rev 12: `STYLE_HINT_LIMITS_PRESENT=False` → скрытой обрезки нет; `rules` = `emoji.hard.off`, `quotation_marks.hard.no_graphic`, `trailing_period.hard.strip` (`enabled=True`). Правила `dash` в документе нет → по коду кандидата (`services/style_policy.py:951,957` — `DASH_FACTORY_ID="dash.hard.factory"`, hard/global) синтезируется заводское правило → **dash активен**. `style_policy.py` в дельте `e9f7595b..724b77ac` отсутствует (не менялся) | **PASS** (basis: PG + код кандидата) |
| 5 | B11: Summary не зелёный при проблемах, backlog числом | `B11_RC=0`, `diagnoses: ok=7, attention=2, unknown=1`, `not_green_rule: never_run/producer_off/no_input/unknown/degraded/attention никогда не считаются зелёными (REQ-B11-E2E)`. `attention` — `graph_memory`, `embeddings` (`job cancelled — не успешный терминал`); `unknown` — `experience` (pre-existing). Backlog: `backlog_status="ok"`, `backlog_missing_embedding=-113`, `backlog_reason=null` (отрицательное = пропущенных вложений нет; следствие истёкших фактов в vec — pre-existing) | **PASS** |
| 6 | Откат готов | `git cat-file -t e9f7595b` = `commit`; `git worktree add /tmp/rb258117 e9f7595b` → `RB_HEAD=e9f7595b`, `RB_APPVER="2.58.114"` (дерево материализуется), worktree удалён; runbook канонов `plans/features/asap-speech-arch/evidence/r3b/rollback.md` на месте; ветка **`release/fix-2.58.114` = `e9f7595b` создана и запушена в origin** (`git ls-remote` подтвердил). Фактический откат **не исполнялся** — иначе прод остался бы на 2.58.114 и потребовался бы второй рестарт; проверена именно готовность пути | **PASS (readiness)** |

### Команда отката (если понадобится)

```
cd /var/www/admin_bot && git checkout e9f7595b && sudo systemctl restart admin_bot
# затем: curl -s https://admin-bot.duckdns.org/healthz  -> 2.58.114
```

БД: `backups/pre_deploy_258114_20261023.db` (1 490 964 KB, integrity ok при создании, `user_version=37`) — остаётся
схемно-совместимой точкой восстановления, т.к. ΔDDL=0 и поезд не меняет формат данных. Новый бэкап в этом
прогоне **не делался сознательно**: изменений схемы/данных нет, свободного места 4 161 MB, а `VACUUM INTO`
1.5 GB-базы съел бы основную часть 15-минутного окна без выигрыша в безопасности.

## Отклонения и находки

1. **MEDIUM (инфраструктура, устранено):** в рабочем дереве на сервере остаются root-owned файлы, из-за которых
   `git checkout` падает с `Permission denied` и **оставляет частично обновлённое дерево**. В 258114 это был
   `plans/`, в 258117 — `tests/fixtures/soul1/direct-runtime-assembly-asap2.txt` (файл **и** каталог root-owned:
   `unlink` требует прав на каталог). Лечение: `chown -R nik:nik /var/www/admin_bot/tests`, затем
   `git checkout -fq 724b77ac` → `TRACKED_DIRTY=0`. Рестарт до починки **не выполнялся**, сервис всё это время
   работал на 2.58.114 из памяти. Остаётся ~390 root-owned файлов в `var/` (вне git, рантайм-каталог) —
   pre-existing, на деплой не влияет. Рекомендация: не выполнять git-операции и тесты в репозитории под root.
2. **LOW (pre-existing, не от 2.58.117):** `smart_archive` gen1/gen2 — `building`, durable-джобы нет;
   в журнале `embedding generation not serviceable | index=smart_archive … build pending — durable job missing`.
   `graph_facts_vec` штатно `serviceable`. B11 корректно помечает это как `attention`.
3. **LOW (pre-existing):** `backlog_missing_embedding=-113` — знак отрицательный из-за того, что `graph_facts_vec`
   хранит строки для истёкших фактов (20 318 против 15 943 eligible); retention `graph_facts_vec` не чистит.
4. **INFO (мой сбой инструмента, не прода):** первые две попытки деплоя прервались до рестарта из-за ошибок в
   моём скрипте (в первом случае `sudo` применялся только к первой команде составной строки, во втором —
   опечатка `git checkout -f q`), третья упала на root-owned каталоге. Прод ни разу не был оставлен в
   несогласованном состоянии: HEAD/дерево выправлены до рестарта, сервис всё время отвечал 200/2.58.114.

## Проверки, которые остаются наблюдением (не блокируют релиз)

- **Функциональный live-smoke инспектора (журналирование КАЖДОЙ HTTP-попытки `generate_chat`)** требует сессии
  Inspector/TMA и реального чата — без отдельной авторизации live-пробы в реальные чаты не отправлялись.
  Код-путь подтверждён в кандидате и покрыт e2e поезда (`e2e-inspector.txt`, 17 тестов; `llm_client` 115).
- `GET /api/speech/style` напрямую не вызывался (нет TMA initData) — вывод о style сделан по PG + коду кандидата.

## Соединения SSH

**4 подключения** (план был 2–3), один логин `nik`, без неудачных auth, без ретраев и поллеров,
интервалы 91 / 106 / 87 с:

| # | UTC | Назначение | Итог |
|---|---|---|---|
| 1 | 16:55:10 | recon + pre-state + BEFORE-снимок (PG/SQLite) + fetch/checkout | abort: root-owned файл блокировал checkout, рестарта не было |
| 2 | 16:56:41 | resume: починка + checkout | abort: опечатка в моей команде checkout, рестарта не было |
| 3 | 16:58:27 | resume: починка прав каталога + checkout | abort: каталог тоже root-owned, рестарта не было |
| 4 | 16:59:54 | выкат: checkout → restart → healthz → журнал → PG/SQLite/B11 → откат-readiness | **успех**, 2.58.117 |

Отдельного 5-го «верификационного» коннекта не делал, чтобы не раздувать канал: все обязательные наблюдения
(каноны/fingerprint, embedding, style, B11, PID) сняты уже **после** рестарта отдельными read-only прогонами.

## Артефакты прогона

- Логи: `OPENCODE_WORKFLOW_SCRATCH/deploy-258117/{main.log,run2.log,run3.log,run4.log}`;
  на сервере `/tmp/d258117_boot.log`, `/tmp/b11_258117.json` (скопирован локально).
- Скрипт: `tools/_dep258117.py` (main/resume/verify, read-only пробы PG/SQLite/B11).
