# Выкладка 2.58.160 — UNIFIED-REPLY волна

Дата: 06.11.2026 (прод-сервер `192.255.209.205`, каталог `/var/www/admin_bot`). Роль: DevOps.
Итог: **успешно, прод на 2.58.160 @ `309f69c2`**. Эпик UNIFIED-REPLY остаётся открытым (UR-G приёмка идёт отдельно).

## 1. Кандидат

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `309f69c2e7218fa83f2f4f58048c5318b244ad3f` (ветка `release/2.58.160`, запушена в `origin`; на сервере `FETCH_HEAD == HEAD == 309f69c2`) |
| База | прод `5e0cb201` (2.58.159) |
| Дельта | merge `01914902` (`94a6537a`) + bump `309f69c2` (31 файл / 32 вхождения) |
| Состав слияния | UR-C-CLOCK `7632fdb6`, UR-D `2ac2764d`, UR-E `b2738117`, UR-F `95e5815d`, BGS-05 `d3027ede`, search short-tokens `e70641f4`, CMV nav `92d7c9ab`, CMV AI/PHY `69e65607`, CMV wording `60333c85`, CMV evidence-батчи; каждый файл `services/web` трассируется к ревьюенному slice-коммиту |
| Конфликты мержа | 1 (`web/app.js`), разрешён UNION: хелперы CMV-NAV-04 (эпик) + reset-view split `7080fda6` и CMV-perf `bd02ac18` (релиз 2.58.156–.158) сохранены; `index.html`/`cog-visual.js` слились автоматически, обе стороны проверены маркерами и тестами |
| DDL | 0 (`user_version` 41 не менялся), PG no-op, миграций нет |
| `MUTABLE_WORKTREE_REQUIRED` | no — деплой из иммутабельного коммита |

## 2. Проверки кандидата

| Проверка | Результат |
|---|---|
| pytest обязательный набор (ur_c_clock, ur_d_writer, ur_e_speech, ur_ui_effective_config, bgs05_budgets, search_short_tokens, direct_chat ×6, ur_turn_engine, ur_b_live_wiring, rlr ×11) | **625 passed / 0 failed** |
| JS union-пробы | `evol_cmv_d_fullscreen` 119 OK (reset-view §11 + NAV-04), `ur_ui_settings` OK, `routing` OK, `evol_cognitive_map` 84 OK, `evol_cog_visual` 333 OK, 4 bump-пина (`round1025_hotfix7/8/9/10`) OK на `APP_VERSION 2.58.160` |

### 2.1 Классификация известных предсуществующих сбоев (на слитом дереве)

| Пункт известного списка | Статус |
|---|---|
| `TestMasterPriority` ×3 (stub `projection` kwarg) | RED — та же причина (`direct_chat_service.py:8462`) |
| `test_kill_switch_registry_73_and_defaults` (`assert 315 == 314`) | RED — **подтверждён на базовом `5e0cb201`** тем же тестом |
| `test_chat_settings_seed_round1019` (`['database.py']`) | RED — как в списке |
| 2 JS (`asap6_wave2_ux_tabs`, `round1025_ia_routing`) | RED — те же 2 |
| `test_initiative_coordination` ×4 | тесты **отсутствуют** и в базовом, и в слитом дереве (устаревшая запись списка) |
| context-partitioning ×2 (`tests/test_direct_chat.py`) | **GREEN** на слитом дереве (адаптированы UR-D) |
| aggregator taxonomy | **GREEN** на слитом дереве |
| `tests/js/evol_cog_scene_test.js` (не был в списке) | RED — **идентичная ошибка `_cogBlitLabel is not a function` воспроизведена на базовом `5e0cb201`**; унаследована с релизной линии, не артефакт мержа; эпик-покрытие сцены зелёное (`evol_cognitive_map`, `evol_cog_visual`). В backlog как предсуществующий дефект теста релизной линии |

## 3. Ход выкладки

- **recon** (одно короткое подключение): `HEAD=5e0cb201`, `release/2.58.159`, tracked-изменений нет (только untracked `.cache/`), сервис active; публичный `/healthz` 200 `2.58.159`.
- **основной прогон** (одно подключение, скрипт-гейты): снапшот БД sqlite backup API → `/tmp/predeploy-258160.db` (`user_version=41`, `quick_check=ok`, 124 таблицы) → `git fetch origin release/2.58.160` → `FETCH_HEAD == 309f69c2` (`SHA_MATCH=1`, ff-совместимо) → `git checkout -B release/2.58.160 309f69c2` → `systemctl restart admin_bot` → `/healthz` 200 `2.58.160` с первой попытки.
- Два начальных прогона того же скрипта **оборвались собственным гейтом в префлайте** (untracked `.cache/` не входил в белый список; парсинг `?? `-строк) — до fetch/checkout/restaрта ничего не менялось, прод не затронут; белый список расширен (untracked-кэши безопасны для checkout), третий прогон прошёл полностью.

## 4. Проверки после выкладки

| Проверка | Результат |
|---|---|
| `/healthz` локально и публично (`https://admin-bot.duckdns.org`) | 200 `{"status":"ok","version":"2.58.160"}` |
| Сервис | `active/running`, `MainPID=2273863`, **`NRestarts=0`**, `ExecMainStatus=0` |
| Журнал | `tracebacks_last120s=0` |
| Отдаваемый `/web/app.js` | 2 027 511 Б; sha256 `ef357837c0a6375923f66edda11d11b7d247f8498d602e7467456323aa186477` — **байт-в-байт равен локальному файлу кандидата** |
| `/api/config/timezones` без TMA | **401** (локально и публично) — permission-gate работает |
| Сообщения в чаты | не отправлялись (живых проб в Telegram нет) |
| Git на сервере | `309f69c2`, ветка `release/2.58.160`, из tracked — чисто |

## 5. Откат

- Cold: на сервере `git checkout -B release/2.58.159 5e0cb201` + `systemctl restart admin_bot` (ветка и объект присутствуют; снапшот БД `/tmp/predeploy-258160.db` на случай отката данных — данные в этой поставке не мигрировали).
- Soft-флагов у волны нет; SQLite DDL = 0.

## 6. Заметки

- На сервере остался untracked `.cache/` (рантайм-кэш, checkout не трогал) — не продукт, решения не требует.
- Эта запись закоммичена docs-only поверх `309f69c2`; **задеплоенный SHA ровно `309f69c2`** (docs-коммит продукт не меняет).
