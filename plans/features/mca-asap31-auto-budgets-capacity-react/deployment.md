# deployment.md — mca-asap31-auto-budgets-capacity-react (ASAP-3.1, инцидент-фикс)

- **Статус доставки: `VERIFIED`**
- **Feature-ID:** `mca-asap31-auto-budgets-capacity-react` (R3)
- **Окружение:** прод `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu 24.04)
- **Дата/время деплоя:** 2026-09-30, ~03:40–03:43 UTC
- **Deployed version:** **2.58.38** (`/healthz` = `{"status":"ok","version":"2.58.38"}`)
- **Deployed commit:** `6c5f9b9` (docs HEAD; код фикса — `5ff1eac`)

---

## 1. Binding: ревью → кандидат на релиз

| Параметр | Значение | Проверка |
|---|---|---|
| Reviewed-Commit | `df0387dff8038a07f66bf89800add619dc061074` | совпал (прод-базис до pull) |
| Spec-Hash | `CC419781A8553FF2C2EB9183868863168AEFF0028BA0DC0D63C41F64523D33ED` | пересчитан, совпал |
| Reviewed Working-Tree-Hash (гейт) | `c8982d630fb1604ba85421288018c1b67af22f72cb35bd7383988511f6d80762` | пересчитан по манифесту `plans/reports/asap31_wth_manifest_incident.txt` (122 пути): **0 расхождений** |
| Commit-time Working-Tree-Hash (re-measure) | `67846e1c8349f537a3dc19ca59a3bd5b2145e749f5e24655484f3a495b23f5de` | манифест `plans/reports/asap31_wth_manifest_incident_25838.txt` (122 пути, идемпотентен) |

**Почему WTH изменился (зафиксировано):** ревью-гейт `c8982d63…` описывал worktree до бампа версии.
Оркестратор санкционировал bump `APP_VERSION` 2.58.37→2.58.38 (Reviewer L-ASAP31-5, прецедент
хотфикса 2.58.31→2.58.32) и предписал пересчитать binding. Дрейф — **ровно 31 путь** и **только
служебный/версионный**:

- `config/settings.py` — `APP_VERSION` 2.58.37→2.58.38 (+ краткая метка раунда);
- `README.md` — версия + строка хотфикса;
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION` в провенансе F8;
- 27 версионных пинов тестов (23 `.py` + 4 `.js`) — механическое следствие bump;
- `plans/reports/full_audit_results.md` — запись раунда round-3 (docs-коммит).

**Функциональный код фикса — байт-идентичен ревью-манифесту** (проверено sha256):

| Файл | sha256 (совпадает с манифестом ревью) |
|---|---|
| `services/summary_generator.py` | `93b2c5de4badb14549b4f496067a449f4ef6b3e643bea9738222426df34ad76c` |
| `services/summary_fact_package.py` | `f5dd72b04864a29e00be7249c09d5b7e475afd2c7713b5e7aa4bc893b268d47e` |
| `tests/test_summary_incident_empty_package_asap31.py` | `723190838329e78edb6d879bff389a8dce100f4adc37778f1ad31f9c17e5086f` |

Логика Reviewer-approval (класс закрыт: все 4 call-site несут resolver-бюджет, dry-run не публикует,
`run_l2` принимает только ok/truncated, два независимых слоя защиты) сохраняется — дрейф её не касается.

## 2. Коммиты

- **FEAT `5ff1eac`** — `fix(round1028): summary empty-package incident — budget passthrough on
  L1-unusable branch, last-topic guard, fallback delivery gate to Legacy (APP_VERSION 2.58.38)`
  (33 файла: 3 файла фикса + bump + README + F8-meta + 27 версионных пинов; чужой WIP не включён).
- **DOCS `6c5f9b9`** — `docs(round1028): ASAP-3.1 incident fix — review round 3 APPROVED
  (ready-to-redeploy) + evidence + WTH manifest incident/commit-time (binding c8982d63->67846e1c)
  + full_audit_results round-3 entry` (5 файлов).
- **DEPLOY-DOC** — этот файл (docs-коммит после доставки).
- Push: `origin/master` `df0387d..6c5f9b9` (без force).

## 3. Что задеплоено (суть фикса)

Прод-инцидент 2.58.37 (крон 19:00 UTC, окно 1089): L1 `unknown_field` → correction retry timeout
обоих провайдеров → ветка «L1 непригоден» вызывала `build_fallback_package` **без бюджета** →
статический потолок `18661` вытеснил единственную тему целиком → пакет `threads=[]` (deliverable) →
L2 опубликовал мета-текст «пакет пуст».

Фикс (3 части): (1) ветка L1-непригоден передаёт `budget=l2_budget`; (2) EMPTY-PACKAGE GUARD —
последняя тема не вытесняется (`len(threads)>1`), режется только содержимое; 5-й возврат
`skipped_chronology`; fail-closed `STATUS_EMPTY`; событие `SUMMARY_COVERAGE_DEGRADED
reason=near_empty_package`; (3) delivery-гейт `_package_content_empty` → LEVEL-3 Legacy вместо L2.

## 4. Готовность релиза (проверки ДО деплоя)

| Проверка | Результат |
|---|---|
| Импорт `services.summary_generator` + `summary_fact_package` | OK (`APP_VERSION 2.58.38`) |
| Полный pytest (devOps-среда) | **10060 passed / 2 deselected** (якорные `test_forbidden_paths_out_of_diff`) — == baseline Reviewer |
| JS (`node` по всем `tests/js/*.js`) | **51/51** exit 0; `node --check` app.js/polygon/telegram-init OK |
| F8 `gen_param_registry_round1025.py --check` | **CHECK OK: реестр 484** |
| Секреты (R17) | pattern-скан диффа `df0387d..HEAD` — чисто; `.env` в коммиты не попадал |

## 5. Деплой (шаги)

1. `cd /var/www/admin_bot && git pull --ff-only` → fast-forward `df0387d..6c5f9b9` (38 файлов).
2. `sudo -n systemctl restart admin_bot` (NOPASSWD-правило sudoers для `systemctl restart admin_bot`).
3. Проверка: `systemctl is-active admin_bot` → **active** (MainPID 2356873,
   ActiveEnterTimestamp 2026-09-30 03:42:20 UTC).
4. Δ DDL = **0**; миграции не запускались; сиды не требовались (нет новых env-ключей/таблиц/строк).
5. Ошибок/Traceback/ImportError в логах старта — **0**; `pg_available=True`; polling `@PERMsoc_bot`;
   `SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)`.

## 6. Пост-деплой верификация

- **Health:** `/api/health` = **200** `{"status":"ok"}`; `/healthz` = **200**
  `{"status":"ok","version":"2.58.38"}`.
- **Регрессия инцидента на проде** (тем же задеплоенным артефактом): `./venv/bin/python -m pytest
  tests/test_summary_incident_empty_package_asap31.py tests/test_summary_coverage_asap31.py
  tests/test_l2_budget_asap31.py -q` → **27 passed**.
- **Реплей инцидента (по логам прод, до фикса):** run `d1062dcd` 2026-09-29 19:00–19:10 UTC:
  окно `1089`, L1 timeout → `L1_FALLBACK_PACKAGE … fragments=0 chronology=0` → `L2_START` (на пустом
  пакете) → `PUBLISH_RICH_COMPLETE message_id=1120810`. Подтверждает класс до фикса.

### Политика флага `SUMMARY_COVERAGE_CHUNKING_ENABLED`

- На момент начала деплоя флаг был **OFF** (стабилизация 2026-09-29 19:32 UTC,
  бэкап `.env.bak.inc-20260929T193204Z`); строка `SUMMARY_COVERAGE_CHUNKING_ENABLED=false` в `.env`.
- Прогон **01:00 UTC (30.09)** при OFF: нормальный — L1 ok → L2 `invalid` → `LEGACY_FALLBACK
  reason=l2_unusable` → публикация реального саммари `msg 1121343`; **пустого мета-текста нет**.
- Политика владельца — «все функции включены». Override удалён из `.env`
  (бэкап `.env.bak.inc-20260930T0341Z.restore` сохранён), рестарт выполнен.
  Эффективное значение = дефолт кода **`True` (ON)** (`SUMMARY_COVERAGE_CHUNKING_ENABLED` ClassVar,
  проверено `config.settings.settings.SUMMARY_COVERAGE_CHUNKING_ENABLED == True`).

### Наблюдение прогонов саммари (крон 4 ч)

- Расписание (in-process APScheduler, `SUMMARY_TIMEZONE=Asia/Yekaterinburg`): **01:00 / 07:00 / 13:00 /
  19:00 UTC**.
- Следующий прогон — **2026-09-30 07:00 UTC** (вне окна сессии DevOps). Что проверить на этом и
  последующих прогонах (при провайдерском таймауте):
  - **ожидание:** `L1_FALLBACK_PACKAGE` c `fragments>0` и/или `chronology>0` **ЛИБО** `LEGACY_FALLBACK`,
    но **НИКОГДА** пустой пакет в `L2_START` и **НИКОГДА** мета-текст в публикации;
  - при деградации — наличие `SUMMARY_COVERAGE_DEGRADED reason=near_empty_package` / WARN
    `PACKAGE_NEAR_EMPTY` (новые маркеры фикса);
  - отсутствие `L1_FALLBACK_PACKAGE … fragments=0 chronology=0` без последующего `LEGACY_FALLBACK`.
  - Команда:
    `journalctl -u admin_bot --since '<окно>' --no-pager | grep -E 'SUMMARY_START|L1_FALLBACK_PACKAGE|PACKAGE_NEAR_EMPTY|COVERAGE_DEGRADED|L2_START|L2_COMPLETE|LEGACY_FALLBACK|PUBLISH_(RICH|TEXT)_COMPLETE'`
  - Лучшее доказательство — прогон с большим окном (1000+ сообщений): пакет должен остаться непустым
    или уйти в LEVEL-3, публикация — реальное саммари.
  - Bei наличии прав: штатный dry-run «Тестирование» (`#/modules/summary/testing`) — **не публикует**;
    помнить L-ASAP31-4 (dry-run без resolver-бюджета → не показатель точности, но класс инцидента не
    проявит: пустой материал fail-closed).

### Мониторинг по логам (окно 60 ч, до фикса)

- `SUMMARY_START` = 11, `SUMMARY_COMPLETE` = 11 (11 прогонов, без `SUMMARY_FAILED`).
- `FACT_PACKAGE_TRUNCATED` = **6** (владелец отметил как отдельную проблему):
  1. `0355e760…` — skipped_fragments=223, limit=19135, estimated=19099;
  2. `180581b6…` — skipped_fragments=93,  limit=19135, estimated=19093;
  3. `dc053e89…` — skipped_fragments=311, limit=18661, estimated=18616;
  4. `f9133ba6…` — skipped_fragments=354, limit=18661, estimated=18600;
  5. `8120c190…` — skipped_fragments=267, limit=18661, estimated=18629;
  6. `f2a676e9…` — skipped_fragments=136, limit=106550, estimated=28269 (30.09 01:00, OFF-прогон).
  Замечание: событие эмитится при `skipped_fragments>0` (в т.ч. от per-topic cap), поэтому «truncated»
  при `estimated << limit` — семантика кап, не бюджетный потолок. Кандидат на отдельную задачу (не этот релиз).
- `L1_FALLBACK_PACKAGE` = 5, `LEGACY_FALLBACK` = 3, `PUBLISH_RICH_COMPLETE` = 18, `PUBLISH_TEXT` = 0.
- Новых пустых публикаций/мета-текста после стабилизации — **нет**.
- **Пустая публикация `msg 1120810`** (крон 19:00 UTC, 2026-09-29 19:10:41): **доложить владельцу как
  кандидата на удаление; НЕ удалять без указания.**

## 7. Откат

- **Soft (стабилизационный рычаг):** вернуть `SUMMARY_COVERAGE_CHUNKING_ENABLED=false` в `.env` +
  `systemctl restart admin_bot` (прежний OFF-путь байт-в-байт). Бэкап `.env` —
  `.env.bak.inc-20260930T0341Z.restore`.
- **Cold revert:** `git revert` коммитов `5ff1eac` (+ при необходимости `6c5f9b9`) либо `git checkout`
  прод-базиса `df0387d` / тега `pre-2.58.37`; `APP_VERSION` вернётся к **2.58.37**. DDL откат не нужен
  (Δ DDL=0).
- Условие отката: появление на крон-прогонах пустого/мета-текстового саммари либо деградации класса
  инцидента.

## 8. Открытые хвосты (не блокирующие)

- L-ASAP31-4 (dry-run без resolver-бюджета), L-ASAP31-6 (косметика телеметрии), carry-over
  M-ASAP31-2 + L-ASAP31-1/2/3; отдельно — семантика `FACT_PACKAGE_TRUNCATED` (per-topic cap vs budget).
- Наблюдение крон-прогона 07:00 UTC и далее (см. §6) — передать Оркестратору/владельцу.

**Секреты:** в этот документ не переносились (только имена флагов/путей/кодов). Значения ключей/токенов
в логах и отчёте не фиксировались.
