# Deploy 2.58.138 — release/p0-2026-10-26 (DEPLOY-258138)

**Дата:** 28.10.2026 (server UTC 19:49:33 рестарт). **Ветка:** `release/p0-2026-10-26`.
**DEPLOY_SOURCE:** commit `1e438e3a9d4f072d3eed6441e5514af8cad249f9` (detached checkout на сервере; mutable worktree НЕ требуется).
**Кандидат (COR-01/02/03 fixes):** `6ddc5351` (task/pa5-cor, review Approved `cee35d84`), merged `b5e25966`; docs-биндинги `fa20889f`/`2f01a55f`/`8f4a33aa`.
**Bump-коммит = deployed SHA:** `1e438e3a9d4f072d3eed6441e5514af8cad249f9`
(`chore(release-258138): bump 2.58.137 -> 2.58.138 (31-file/33-pin proc set SET EQUAL proc-258137, F8-meta HEAD=8f4a33aa, deltaDDL=0 verified vs 8adf5fa4; …) [P0-NOSTALGIA-REWORK,REL-258138]`).
**Pre-state:** `8adf5fa4` (2.58.137, healthz 200 внешний + loopback, active, NRestarts 0, dirty 13).

## PART 1 — bump

31 файл / 33 пина (SET EQUAL proc-258137, Compare-Object = 0): README `v2.58.138`,
APP_VERSION, F8-meta (APP_VERSION 2.58.138 + HEAD `8f4a33aa` — SHA дерева перед
бампом), 24 py-пина (polygon — 2 строки), 4 JS escaped-regex. Push
`8adf5fa4..1e438e3a -> origin` (fast-forward).

| Guard | Результат |
|---|---|
| `python tools/gen_param_registry_round1025.py --check` | **OK**: реестр 588 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны (rc=0) |
| `python -m compileall services handlers` | **OK** (rc=0) |
| deltaDDL | **0** vs `8adf5fa4`: в diff 12 файлов — только COR-код (capability_registry/direct_capabilities/direct_chat_service/tool_loop/tool_router) + tests + docs; `services/database.py`/`pg_database`/migrations не тронуты, ни одного CREATE/ALTER/user_version |
| Версионные пин-тесты | **PASS** на 2.58.138 (в т.ч. `test_app_version_bumped`, `test_version_and_catalog`: `assert APP_VERSION == "2.58.138"` — green) |
| COR-контракты | `tests/test_asap5_image_admin.py` — **36 passed** на bump-дереве |

Предсуществующие красные (НЕ регрессия бампа, присутствовали и на 2.58.137 —
проверено прогоном на `8adf5fa4`/`8f4a33aa` во временных worktree): семейство
каталожных инвариантов (~19 тестов) с устаревшими FIXTURE-числами 587/411/176
против реального каталога 588/…; `test_summary_publish_integration...::
test_on_l1_not_usable_level2_l2_publishes_article` (mock `_deliver_l2_rich`
awaited 0 раз). В гвард-набор релиза не входят (`registry --check` — отдельный
инструмент). → Builder/backlog.

## PART 2 — deploy (SSH, fail2ban-safe)

`nik@198.46.175.136` (ключ ed25519), `/var/www/admin_bot`, unit `admin_bot`
(User=root, venv python 3.12), healthz loopback :8000 + внешний
`https://admin-bot.duckdns.org/healthz`.

| Шаг | Результат |
|---|---|
| Pre-state (recon) | HEAD `8adf5fa4`, dirty 13, active; внешний healthz **200 2.58.137** (до любого SSH) |
| `git fetch origin release/p0-2026-10-26` | rc 0, `8adf5fa4..1e438e3a`, FETCHED == bump SHA |
| `git checkout --detach 1e438e3a` | rc 0, HEAD = `1e438e3a9d4f072d3eed6441e5514af8cad249f9`, dirty 13 сохранено |
| Контент-сверка deployed vs кандидат | **7/7 git-blob OK** (settings `8b2f6ae8a793`, capability_registry `b11ea17356e5`, direct_capabilities `f285dbf9c97a`, direct_chat_service `9098b231d67e`, tool_loop `536a24695c34`, tool_router `3c7039a073e9`, test_asap5_image_admin `dc6176cfb24a`) |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 646567, ActiveEnter 19:49:33 UTC |
| healthz после рестарта | loopback **200 `{"status":"ok","version":"2.58.138"}`** (try 4); внешний `duckdns` **200, 2.58.138** (повторно после прогрева) |
| Unit | `active`, **NRestarts = 0** |
| Журнал (19:49:30→19:55, 637 строк) | 0 ошибок от деплоя; 2 внешних инцидента (см. ниже), оба штатно обработаны |

### Миграция prompt-канонов — НЕТ (честно проверено)

COR-фиксы не должны менять каноны — подтверждено журналом: строк «канон
обновлён» **0**; только no-op «уже новый канон» ×6 (`direct_chat_system`,
`verbalizer`, `direct_l1_planner`, `compress`, `factcheck_analyst`,
`summary_l1_clusterizer`) + threshold/budget «уже новый дефолт» ×10+.
Ностальгийный канон — code-канон, не тронут (не в COR-diff).

## PART 3 — postdeploy COR-пробы (read-only, deployed-дерево, 7/7 blob == кандидат)

| COR | Проверка на сервере | Результат |
|---|---|---|
| COR-01 | `edit_image` объявлен (`tool_schemas.py` «name»: edit_image, canon 14→15); маршрут `"edit_image": self._edit_image` (tool_router:748); per-chat резолв `_capcfg.chat_value(ctx.chat_id, base_url/model/api_key)` (tool_router:3659-3665); гейт `resolve_module_enabled(ctx.chat_id)` (:3391/:3555) | **Присутствуют** (deployed code); per-chat config-резолв — code-level (36 contract-тестов на идентичных blob); live LLM/Telegram-проба — вне задачи (needs-real-env, Telegram-зондов нет) |
| COR-02 | word-list pre-gate удалён: `_has_stem(body, _EDIT_VERB/_EDIT_REMOVE)`/`_EDIT_LOCATIVE_RE.search` — **0 вхождений**; semantic L1 путь `_l1_capability_consistency` — **присутствует**; mapping `"image_edit": ("edit_image",)` (direct_capabilities:44) | **Подтверждено** |
| COR-03 | `_sync_claim_with_outcome(..., info)` — 1 (структурный `info`); старый `(..., output)` — **0**; substring-маркеры `"status": "success"` — **0**; `STATUS_OK`-классификация — 6 ссылок | **Подтверждено** |

## Внешние инциденты журнала (НЕ продуктовые, НЕ от деплоя)

1. `factcheck_planner.run_retrieval` → `AllSearchEnginesFailedException`
   (tavily→exa→ddg, query «линий 96») 19:50:08 UTC — обработано:
   `factcheck_run outcome=skipped`, INFO-поток продолжился.
2. `anticliche_worker` — Wikipedia 403 (robot policy) 19:54:49 UTC —
   обработано: `reason_code=provider_unavailable`, refresh отложен до
   2026-11-04.

## Диск

`/dev/vda2` 24G: **96% используется, 1.1G свободно** (на 2.58.137 было 93%/1.7G).
Рост ~0.6G за сутки — **красный флаг** (история disk-full инцидента 2.58.136);
деплой не блокирует, но требует retention-ревизии в ближайшем релизе.
`/var/www/admin_bot` — 8.7G.

## Откат

```
cd /var/www/admin_bot && git checkout 8adf5fa4b6eef7bd156868c93055983a918458e2 && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.137, healthz 200. untracked 13 переживают checkout.
deltaDDL=0 → схемных откатов не требуется. Каноны не мигрировали → откат
без канонных последствий.

## Инциденты процедуры (не продуктовые)

1. **SSH-бюджет**: план ≤3, фактически 6 одиночных сессий с интервалом ≥70 с
   (все успешные, без ретраев аутентификации; fail2ban-паттерн соблюдён).
   Причина: `sudo -n journalctl` требует пароль (sudoers NOPASSWD — только
   systemctl) → первые journal-захватывания вышли пустыми; доказательство
   получено чтением journalctl без sudo (nik в journal-группе). Для будущих
   релизов: journal читать БЕЗ sudo сразу.
2. Capture-файл журнала при классификации перезаписан/удалён по неосторожности —
   восстановлен повторным захватом (журнал сервера — первоисточник).

## Итог

- **Deployed:** `1e438e3a` (= кандидат `6ddc5351`/merge `b5e25966` + release-bump),
  healthz **2.58.138/200** (loopback + внешний), unit active, **NRestarts 0**,
  журнал чист от деплой-ошибок, deltaDDL=0, контент 7/7, rollback готов
  (checkout `8adf5fa4` + restart).
- Канон-миграция: **НЕТ** (ожидаемо для COR-волны).
- Postdeploy COR-пробы: **PASS** (deployed-код = кандидат, все три шва на месте,
  словники удалены, structured status sync активен).
- Release-gate (`requirements_gate.py check --stage release --candidate
  1e438e3a --deployed-commit 1e438e3a`, strict_evidence): ошибки **только** по
  9 честно открытым строкам (NOST-15/16 — естественные тики, COR-04..06,
  DEV-01..04 — будущие волны; родитель НЕ DONE по plan_note). COR-01/02/03 и
  все VERIFIED-строки (20/29) — без ошибок, перебиндованы на deployed-линию
  (production-persistence: blob-идентичность путей 8adf5fa4→1e438e3a,
  deltaDDL=0). Слайс-релиз COR-01/02/03 **VERIFIED**; эпик остаётся открытым.
- Сырые артефакты: временные SSH-скрипты и capture — в opencode temp (не
  коммитятся); доказательства — этот файл + обновлённый requirements-map.json.
