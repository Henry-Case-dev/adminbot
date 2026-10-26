# Deploy 2.58.131 — release/p0-2026-10-26 (DEPLOY-258131)

**Дата:** 26.10.2026. **Ветер:** `release/p0-2026-10-26`.
**Кандидат ревью:** `86ef2a64d1a8ebba4b7738c7594e30ba3391c8a8` (review `Approved for controlled deployment`, review-release-p0.md; binding-коммиты `c358f202`/`405f7f70` — plans-only).
**Bump-коммит = deployed SHA:** `fa74ecf8e1ee69a59483a34cef3de3702be5d7a4` (`chore(release-258131): bump 2.58.130 -> 2.58.131`, 32 файла; код идентичен кандидату, отличия — только version-пины/README/F8-meta/probe-артефакт).
**Прод-база до деплоя:** `534ac7dd` (2.58.130, healthz 200, unit active, NRestarts 0).
**DeltaDDL:** **0** — в дельте релиза нет поднятия `user_version`/константы схемы; только идемпотентные аддитивные runtime-ALTER (`protected_facts.subject_ref_id`, nullable-колонки provenance `lore_stories`) с PRAGMA-guard. Bump-набор — 0 файлов DDL-периметра. `requirements*.txt` дельта пуста (0 строк).

## Bump (fa74ecf8)

Набор = паттерн 2.58.130 (`git show --stat 534ac7dd`, 31-file/32-pin) + probe-артефакт W7:

- `config/settings.py` APP_VERSION → **2.58.131**;
- `README.md` «Версия» → v2.58.131;
- `plans/docs/param-registry-round1025.meta.md`: APP_VERSION 2.58.131, **HEAD (short) = `86ef2a64`** (top non-docs коммит релиза);
- 24 py-пина (`2.58.130`→`2.58.131`, polygon — 2 строки) + 4 JS-пина (escaped-regex `2\.58\.130`);
- `plans/features/cfg/evidence/cfg-06/w7-dispute-metrics.json` (latency_ms_mock 5→7, артефакт W7-пробы релиза; 6 прочих файлов с литералом «2.58.130» — данные/моки/провенанс канон-ступеней, НЕ пины, не тронуты).

## Guard'ы (post-bump, worktree `adminbot-wt-rel-p0`)

| Guard | Результат |
|---|---|
| `py -3 tools/gen_param_registry_round1025.py --check` | **OK**: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| `py -3 -m compileall services` | **OK** (rc=0) |
| pins24 (24 py-пин-файла, venv 3.12.0) | **868 passed / 0 failed** (74.7 s) — совпадает с pins24 REL-258111 |
| 4 JS-харнесса (node v24.16.0) | HOTFIX7/8/9/10 **OK** (rc=0 все) |
| Свежие factcheck-тесты на бампнутом дереве | `test_factcheck_wide_context_default_2026_10_25.py` + `test_factcheck_media_2026_10_25.py`: **64 passed** |
| Внешний импорт `config.settings` | APP_VERSION == 2.58.131 |

## Деплой (прод)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`. **SSH: 2 подключения** (деплой 08:29:15Z, финальная сверка 08:32:07Z), без ретраев и параллельных коннектов, секреты не печатались.

| Шаг | Результат |
|---|---|
| Pre: HEAD / версия | `534ac7dd` / healthz `{"status":"ok","version":"2.58.130"}`, active, NRestarts 0 |
| Pre: untracked | **13** (info_text.bak.*, pre_migration_backup/, pre_migration .db-journal, test_subs.ru.json3, tools/_s41_precheck.py) — сохранены, без reset/clean/stash |
| `git fetch origin release/p0-2026-10-26` | rc 0, FETCH_HEAD = `fa74ecf8` |
| `git checkout fa74ecf8` (detached) | rc 0, HEAD = `fa74ecf8`, untracked 13 сохранены |
| `git diff --stat 534ac7dd HEAD -- requirements*.txt` | 0 строк (зависимости не менялись) |
| `sudo systemctl restart admin_bot` | 08:29:25Z, новый MainPID **224410** (start 08:29:34Z) |

## Post-deploy проверки (закрытие DEPLOY-STANDARD / FC-RELEASE-04 / FC-WIDE-02)

| Проверка | Результат |
|---|---|
| unit (settle 38 c, потом +2.5 мин) | `active/running`, MainPID 224410 (без перезапусков), **NRestarts = 0**, crash-loop нет |
| `/healthz` loopback (127.0.0.1:8000) | HTTP **200** `{"status":"ok","version":"2.58.131"}` |
| `/healthz` внешний (`https://admin-bot.duckdns.org/healthz`) | HTTP **200** `{"status":"ok","version":"2.58.131"}` |
| Журнал с момента старта (два среза: +38 c и +2.5 мин) | **0** ERROR / CRITICAL / Traceback; воркеры (vision/apscheduler) тикают штатно |
| L1 канон-миграция (`migrate_prompt_canons`) | **`канон обновлён | key=prompts.direct_l1_planner_system_prompt`** — ступень `PREV_DIRECT_L1_PLANNER_R3` (прод-байты 2.58.130) → активный канон `DIRECT_L1_PLANNER_SYSTEM_PROMPT` (2.58.131), провенанс аттестован; 3 ключа уже на новом каноне (no-op); **10 owner-кастомных ключей НЕ тронуты** («кастом юзера — НЕ трогаем»); core-patch: авторские байты целы (`sha=ead77b2ab509`) |
| `flags.factcheck_wide_context` | Разовая миграция применена: **«false (прежний дефолт) → true»**, маркер записан, ручное выключение после маркера сохраняется; в коде дефолт ON (решение владельца 25.10.2026) |
| `protected_facts.subject_ref_id` | Колонка **добавлена** («аддитивно, user_version не менялся») |
| Lore quarantine | **id=4 (lcp=1071) и id=3 (lcp=2186)** помечены (`origin=bot_self_echo`, status=rejected, исключены из извлечения, записи сохранены в БД); массовых удалений нет |
| Каталог-ключ wide-context на проде | `grep -c 'flags.factcheck_wide_context' services/param_catalog.py` на деплой-SHA = **1** (спек в REGISTRY, группа `flags_module_factcheck`, не hidden → отдаётся `/api/config/params-meta`); UI-тумблер «По умолчанию включён» + описание 200–500 закреплены тестом `test_catalog_spec_visible_in_modules_factcheck` (свежий PASS 64 на бампнутом дереве; playwright-приёмка — preprod review R2) |
| Админ-статика | Вне 31-файлового bump-набора (web-статика в дельте релиза не менялась в части версионирования статики — N/A) |

## Откат (задокументирован, НЕ выполнялся)

```
cd /var/www/admin_bot && git checkout 534ac7dd && sudo systemctl restart admin_bot
```

Состояние после отката: 2.58.130, healthz 200. Замечания честно: (1) канон L1 останется на байтах 2.58.131 — старый код считает его «кастом юзера» (no-op с WARNING); возврат — ROLLBACK-ступенью на новом коде; (2) `flags.factcheck_wide_context=true` старым кодом игнорируется (ключ новый); (3) колонка `subject_ref_id` и пометки quarantine (id=3/4) остаются в БД — аддитивно, старый код не ломают (self-echo-строки вернутся в извлечение; обратимость — `UPDATE … SET status=NULL, excluded_from_retrieval=0`); (4) untracked 13 файлов не затрагиваются ни деплоем, ни откатом.

## Итог

- **Deployed:** `fa74ecf8` (= кандидат `86ef2a64` + docs-binding + release-bump), версия на проде **2.58.131**, healthz 200 (loopback + внешний), NRestarts 0, журнал чист.
- Обязательные postdeploy-пункты: DEPLOY-STANDARD (CORR), FC-RELEASE-04 (FACT), FC-WIDE-02 (FACT) — **закрыты VERIFIED** с deployed-привязкой в картах.
- FC-REPORT-06 (production-версия/здоровье в отчёте реального чата) — вне скоупа лейна, остаётся postdeploy-only; TG-пробы в реальные чаты запрещены без отдельной авторизации.
- Инцидентов нет; откат готов, но не потребовался.
