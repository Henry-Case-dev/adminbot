# Deploy 2.58.135 — release/p0-2026-10-26 (DEPLOY-258135)

**Дата:** 27.10.2026 (server UTC 04:19–04:22). **Ветка:** `release/p0-2026-10-26`.
**Одобренный код-коммит (candidate):** `00a20622` (merge asap5-w3-integration, Reviewer Approved).
**Bump-коммит = deployed SHA:** `05c408f6f974670193588da795bdbc66dfa26a2b` (`chore(release-258135): bump 2.58.134 -> 2.58.135 (31-file/33-pin proc set, F8-meta HEAD=00a20622, deltaDDL=0)`; файл-сет побайтно совпадает с эталоном `076f7391`/`b5716022`: README `v2.58.135`, APP_VERSION, F8-meta (APP_VERSION 2.58.135 + HEAD `00a20622` — родитель бампа), 24 py-теста (polygon — 2 пина), 4 JS escaped-regex).
**Предыдущий прод:** `076f7391` (2.58.134, healthz 200, active, NRestarts 0, dirty 13).
**DeltaDDL:** **0** — bump-дифф только версии-пины; дифф релиза `076f7391..00a20622` не содержит CREATE/ALTER/ADD COLUMN/user_version (хиты «schema» — чтение существующей колонки `analysis_schema_version` и кодовая константа; `database.py` — только добавления колонок в SELECT: `media_group_id`, `is_forward`, `forward_source`). Живой журнал нового процесса: `[database] migrations: start | current user_version=37 | pending=[]` → `complete | user_version=37 | total 0.0s`.

## Guard'ы (post-bump, worktree `adminbot-wt-rel-p0`)

| Guard | Результат |
|---|---|
| `py tools/gen_param_registry_round1025.py --check` | **OK**: реестр 587 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны (rc=0) |
| `py -m compileall services handlers` | **OK** (rc=0) |
| Push | `1b93c6db..05c408f6 release/p0-2026-10-26 -> origin` (fast-forward) |

## Деплой (SSH, 2 сеанса: recon + main, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`. Одиночные логины (paramiko, password-only по правилам repo), интервал 86 c между сеансами (04:19:13Z → 04:20:39Z), без ретраев и поллеров. Пароль sudo передавался stdin'ом, в транскрипт/логи не попадал.

| Шаг | Результат |
|---|---|
| Внешний healthz до | **200** `{"status":"ok","version":"2.58.134"}` |
| Recon (04:19:13Z) | HEAD `076f7391`, dirty 13, unit active/running, **NRestarts 0**, MainPID 308006, loopback healthz 2.58.134 |
| Pre-state (04:20:39Z) | HEAD `076f7391`, dirty 13, T0 epoch `1793074840` |
| `git fetch origin release/p0-2026-10-26` | rc 0, `076f7391..05c408f6` (attempt 1, askpass не понадобился) |
| `git checkout --detach 05c408f6` | rc 0, HEAD = `05c408f6f974670193588da795bdbc66dfa26a2b`, dirty 13 сохранены |
| Артефакт-пины (sha256_12, deployed vs локальный `05c408f6`) | **12/12 совпали**: `settings.py 04a0b627852b`, `README.md 085e09ed1a73`, `param-registry…meta.md 68191f938df1`, `web/app.js 9422b6de1467`, `mca_vision.py 3d4e7302991f`, `nostalgia_worker.py c8e74ad1d503`, `nostalgia_prompts.py e6e1ba7cd551`, `direct_capabilities.py be933618c6f9`, `capability_registry.py 08ca36979585`, `database.py 3d56d3f93951`, `prompt_registry.py a606ef54c15e`, `tool_schemas.py edc3e940302f` |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID **462068** |
| Post (settle ~20 c) | loopback healthz **200** `{"status":"ok","version":"2.58.135"}` (try 4); unit `active/running`, **NRestarts = 0** |
| Журнал (T0-якорь, окно рестарта) | **0 ERROR / CRITICAL / Traceback**; migrations `user_version=37, pending=[], 0.0s`; polling @PERMsoc_bot запущен 04:21:15Z; `VisionMediaWorker._tick` выполняется (04:21:18Z, executed successfully) |
| Внешний healthz после | `https://admin-bot.duckdns.org/healthz` → **200** `2.58.135` |
| WARNING (12, не новые) | 11× `[prompt_migration] уже кастомный — не перезаписан` (штатное сохранение genuinely-custom промптов) + 1× `SmartModule: embedding generation not serviceable | index=smart_archive` (предсуществующая операционная заметка старта) |

## Postdeploy ASAP5 (read-only)

| Проверка | Результат |
|---|---|
| **Vision** — admin/API snapshot per-chat attribution live | `GET /api/vision/state` (внешний HTTPS, без auth) → **401** — роут задеплоен и RBAC-защищён; роуты `vision/test|vision/state` в deployed `web/api/routes.py` — 6 маркеров |
| **Vision** — no_text/failed состояния (structure-level) | deployed `services/mca_vision.py`: `no_text` ×27 (включая reuse-запросы no_text-анализов по asset_id/content_hash), `failed` ×92; контракт статусов `ready|no_text|failed|unreadable` (:1597) |
| **Image-gen** — capability claim vs route (config read-only) | deployed `services/direct_capabilities.py`: `image_generation→generate_image` (:40), `image_edit→edit_image` (:44, маршрут Direct Chat), intent-маппинг `INTENT_CREATE/EDIT_IMAGE` (:200–201); файл байт-пин совпадает с кандидатом |
| **Image-gen** — admin «Типы медиа» в served-ассетах | served `web/app.js?v=2.58.135` sha256 `9422b6de1467d70e57737713fcd8cb07a7b22ea7cf7eb8796fd9f76e74244a83` == локальному билду `05c408f6` (**байт-в-байт**); «Типы медиа» в served-байтах: есть (в билде — 2 маркера, `app.js:3570` push `media_types`) |
| **Nostalgia** — provenance label в deployed-коде | `services/nostalgia_prompts.py`: «Переслано» ×8, `format_year_back_line` (:254) — year_back-строки репостов уходят в LLM/рендер с меткой источника |
| **Nostalgia** — self-decline guard в deployed-коде | `nostalgia_prompts.py is_self_declining_text` ×2; `nostalgia_worker.py`: `self_decline` ×2 (skip до публикации, log `skipped/reason=self_decline`); guard-тест в `tests/test_nostalgia_worker.py` ×4 (`test_incident_shape_declined_not_posted`) |
| Миграции | deltaDDL=0 подтверждён живым процессом (`user_version=37, pending=[]`) |
| Telegram-сообщения | деплой/пробы не отправляли сообщений; журнал — только штатный старт polling |

## Откат (задокументирован, не выполнялся)

```
cd /var/www/admin_bot && git checkout 076f7391a01157bad106372d405d109085a78dbc && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.134, healthz 200. Примечание: untracked 13 файлов переживают checkout (проверено при прямом деплое — dirty 13 сохранены на `05c408f6`).

## Итог (closure-данные REQ-CLOSE-DEPLOY)

- **Deployed:** `05c408f6` (= candidate `00a20622` + release-bump), healthz **2.58.135/200** (loopback + внешний), unit active, **NRestarts 0**, журнал чист, deltaDDL=0 подтверждён живым процессом, артефакт-пины 12/12.
- Технические деплой-проверки — **VERIFIED** (версия/healthz/unit/journal/DDL=0/артефакт-пины/rollback-readiness).
- Postdeploy ASAP5 (vision / image-gen / nostalgia, read-only) — **выполнены**, см. таблицу выше; карта `requirements-map.json` ждёт `candidate_commit=00a20622`, `deployed_commit=05c408f6` (биндинг — @PM).
- Инцидентных находок нет; 2 предсуществующие WARNING-заметки (prompt_migration custom-preserve, SmartModule embedding serviceability) — вне дельты релиза.
