# deployment.md — mca-asap-summary-hotfix (ASAP-деплой 2.58.32 на прод)

- **Feature-ID:** `mca-asap-summary-hotfix`
- **Дата деплоя:** 2026-09-27, окно ~08:04–08:08 UTC (локально Владивосток ~19:04–19:08, +12)
- **Статус: VERIFIED**
- **Разрешение:** @Reviewer `Approved` (`review.md`, «Разрешение деплоя 2.58.32 — ВЫДАНО (@DevOps)») + приказ владельца (ASAP-блок `plans/current_task.md`, строка 1882: «Саммари нужно срочно починить и сделать деплой на прод»).

## 1. Связка с ревью (binding)

- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa` — совпадает с локальным HEAD на момент старта деплоя; прод до pull: `89a1261` (родитель `05bc870`), т.е. прод был на базисе ревью.
- **Working-Tree-Hash (33 хотфикс-файла):** SHA-256 `c0f1634f47e2124a77801417f6fbfc1a5e32300016b4999fb1b8aacf7c2da928` — контент всех файлов коммита верифицирован против пер-файловых пинов `review.md` (пер-файловые SHA256: settings d4c18274…, l2_writer 22b9f689…, hotfix-тест e0ed624c…, l2-тест 96ace0bd…, coordinator 79a77b3d…, f8 c4edf4c4…, deploy a111745f…, publish c9e2fb0e…, README 8f70f84f…, meta 55994f1e…) — все совпали (учёт: пины ревью сняты в CRLF-форме, рабочие копии LF — контент идентичен с точностью до EOL, известная особенность `core.autocrlf=true`, задокументирована в review.md «Прозрачность процедуры»).
- **Spec-Hash:** tasks.md `c61f70b7…`, evidence.md `562178d6…` — совпали raw-байтами. owner-блок `# ASAP` в current_task.md присутствует (строка 1882).
- **Дрейф не обнаружен.** MCA-волна round1027 в коммит не вошла (см. §2).

## 2. Коммит (шаг 1)

- **Коммит:** `270c277bfcfbcd763d123481e23e60695468f6b0` —
  «fix(round1027): ASAP-хотфикс саммари — обрезка L2 вместо отбраковки (MAX_SUMMARY_PARTS legacy-семантика), kill-switch SUMMARY_L2_TRIM_ENABLED (APP_VERSION 2.58.32)»
- **Push:** `05bc870..270c277 master -> master` в `origin/master` (fast-forward, без force). origin/master после пуша = `270c277`.
- **Объём:** 37 файлов, +900/−69:
  - `config/settings.py` — ТОЛЬКО 2 хотфикс-хунка из 3 (ClassVar `SUMMARY_L2_TRIM_ENABLED` + APP_VERSION 2.58.32); блок kill-switch'ей mca-волны (MCA_*) разделён по хункам и в коммит НЕ вошёл (остался в рабочем дереве для отдельного релиза mca-волны);
  - `services/summary_l2_writer.py` целиком (trim-фикс + логи);
  - тесты: новый `tests/test_summary_asap_hotfix_round1027.py` (10), `tests/test_summary_l2_writer.py` (2 сценария), баунд-NOTE + версия-пин в `tests/test_tool_coordinator_round1026.py`, версия-пины 2.58.32 в 19 py-тестах и 4 JS-харнессах;
  - `README.md`, `plans/docs/param-registry-round1025.meta.md`, артефакты фичи (tasks/evidence/review.md), запись ревью в `plans/reports/full_audit_results.md` (только ASAP-запись; записи mca-волн отделены).
- **Отклонение от байт-точного соответствия рабочему дереву:** `config/settings.py` и `full_audit_results.md` закоммичены частично (по хункам) — санкционировано review.md п.5 («@Orchestrator должен отделить хотфикс от волны») и заданием; тестовый файл `tests/test_round1025_f8_registry.py` закоммичен БЕЗ mca-17a-хунка freeze-пина routes.py (иначе изолированное дерево ссылалось бы на некоммиченную mca-версию routes.py — проверено изолированным worktree-прогоном и исправлено до пуша).
- **Проверки перед пушем:** изолированный worktree коммита — сфокусированные 24 тест-файла: 900 passed / 0 failed (3 freeze-фейла при LF-чекнауте — pre-existing EOL-хрупкость фикстур F8, воспроизведены на baseline `05bc870` идентично — паритет, не регресс); полный pytest на рабочем дереве ревью: 9839/0-эквивалент (2 флейка вне диффа — betterstack real-network и CLI-help при нестандартной кодовой странице — зелёные изолированно); JS-харнесс 4/4 pinned; `git diff --cached --check` чисто; секрет-скан стейджа — 0 попаданий.

## 3. Прод-деплой (шаг 2, сервер `198.46.175.136`, `/var/www/admin_bot`, systemd `admin_bot`)

| Шаг | Результат |
|---|---|
| prod HEAD до | `89a126170f82b79d34dadaa74f23d81bca9e3c1b` (round1026 docs; прод-код = базис 2.58.31) |
| worktree-грязь | только untracked .bak-файлы/дампы — tracked-дерево чистое, pull безопасен |
| `git pull --ff-only` | успех; прод HEAD после: **`270c277bfcfbcd763d123481e23e60695468f6b0`** |
| APP_VERSION в файле | `APP_VERSION = "2.58.32"` (config/settings.py прод-копии) |
| .env | правки НЕ требовались (Δ env=0: kill-switch default ON; MAX_SUMMARY_PARTS в .env и в unit не задан) |
| рестарт #1 (08:05:06 UTC) | active (running), PID 1547088; при остановке сработал TimeoutStopSec — SIGTERM→SIGKILL через 30с (pre-existing долгая остановка, сервис поднялся штатно) |
| рестарт #2 (финальный, 08:07) | active, MainPID 1547594, NRestarts=0 — выполнен после выставления hot-ключа (значение загружено при старте) |
| health | `GET http://127.0.0.1:8000/api/health` → `{"status":"ok"}` **HTTP 200** (первые 3 пробы в окне старта 000 — uvicorn ещё поднимался; порт 8000 подтверждён `ss -tlnp`: python PID 1547594 LISTEN 127.0.0.1:8000; наружу — Caddy → admin-bot.duckdns.org) |
| runtime-версия | `venv/bin/python -c "from config.settings import APP_VERSION"` → **2.58.32** |
| логи старта | `[pg_db] starter bot_settings seeded: 423`, `[config_cache] initialized: settings=442 roles=4 admins=3`, `Start polling`, `[webapp] lifespan started | pg_available=True` |
| новые Traceback/ERROR (−3 мин) | **0** (фильтр известных LLM-таймаутов nano-gpt; сырой счётчик Traceback за окно — 0) |
| миграции/DDL/каталог | Δ DDL=0, Δ каталога=0, 0 новых зависимостей — не требовались |

## 4. Hot-ключ `limits.max_summary_parts` (шаг 2 п.8)

- Слой env: `MAX_SUMMARY_PARTS` НЕ задан ни в `.env`, ни в systemd-unit — действует глобальный слой БД.
- Прод-БД (PostgreSQL, `bot_settings`): текущее значение было **`1`** (совпало с аудит-прогнозом от 06.09) → выставлено **`6`** (совпадает с L2-промпт-хинтом serious; UPDATE перед финальным рестартом — значение загружено кэшем при старте, `[config_cache] initialized: settings=442`). Ключ каталога — hot: дальнейшие правки через POST /api/config применяются без рестарта.
- Примечание: внешняя SQL-правка НЕ подхватывается живым процессом (ConfigCache перечитывается только при own-write/reload/старте) — поэтому правка сделана ДО финального рестарта.

## 5. Откат (готовность)

- Soft: env `SUMMARY_L2_TRIM_ENABLED=false` + рестарт → байт-в-байт прежний fail-closed reject-путь (верифицировано ревью).
- Cold: revert коммита `270c277` на проде (прод-хэш до — `89a1261`).

## 6. Pending (вне сессии DevOps)

- Прод-верификация критерия владельца «следующее саммари публикуется» — по факту ближайшего саммари в `-1002661910336`: в логе должно НЕ быть `L2_ERROR | reason=too_many_paragraphs — не публикуем`; при обрезке ожидается `L2 trimmed_for_publication | paragraphs_before=N | paragraphs_kept=K | paragraphs_dropped=M` (evidence.md §6 п.4). Граф-таймауты nano-gpt могут продолжаться — на публикацию не влияют (batch kept, pipeline continues).
- Два Low из ревью (L-HOTFIX-1 README-счётчик, L-HOTFIX-2 константа-маркер) — остаются owned follow-up, на деплой не влияют.

## 7. Browser smoke

NOT_APPLICABLE — фича не меняет web-UI (routes.py/web/* вне диффа, Δ UI=0); затронут только Telegram-путь публикации саммари, верифицируемый лог-маркерами из §6.
