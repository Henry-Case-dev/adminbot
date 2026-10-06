# mca-release — окно доставки deferred-пакета mca-21 (T-5216) — 06.10.2026

**Статус:** ✅ **VERIFIED** (06.10.2026, 23:27 UTC) · **Версия:** 2.58.66 → **2.58.67** · **Кандидат:** `6f062fa`

## 1. Что доставлено

Deferred-пакет **mca-21-guides** (review Approved итер.1, scanner n/a docs): финальная актуализация справки MCA-релиза — «Гайд по возможностям» (Г1, Markdown-канон `content.intelligence_guide`, **GUIDE_CANON_VERSION 2→3**) + «Гайд по фичам бота» (Г2, HTML-канон `content.info_how_it_works`, **INFO_CANON_VERSION 5→6**), слепки v5/v2 в реестрах, единственная код-Δ `services/info_service.py`. Доставка — через существующие версионные идемпотентные миграции `config_cache.py` (DML-only): **Δ DDL = 0 (v33, МИГРАЦИЙ НЕТ — не вызывались)**, Δ каталога = 0 (523), Δ KS = 0 (85), Δ reason = 0 (280), Δ тулов = 0 (14), routes Δ = 0 (6 эндпоинтов `/api/info*`, `ROUTES_SHA256_F11` re-pin не требуется). Биндинг ревью: 14 файлов (review.md §9, git hash-object) — верифицирован 14/14 до коммита. Release-owned свип: APP_VERSION `settings.py:3209`, README header, F8 meta-pin, 24 py-пина тестов, 4 js-regex-пина (hotfix7/8/9/10).

## 2. Деплой-факт

- **DEPLOY_SOURCE:** immutable commit `6f062fa` (feat: пакет mca-21 + bump; push ff `3e3bdb7..6f062fa`). **MUTABLE_WORKTREE_REQUIRED: no** (деплой из immutable-коммита; локальный worktree использовался только до push).
- **Прод:** один recon-коннект (~15 с: `e16be7e`, healthz 200) + основные прогоны одним SSH-соединением (AGENTS.md, fail2ban-дисциплина; паузы ≥75 с между коннектами). Secret-free: paramiko-хелпер `tools/_d2_t5216_deploy.py` (не коммитится), scrub секретов, значения не в командах/логах.
- **Pull:** `git pull --ff-only` `e16be7e → 6f062fa`; identity **4/4 sha256** байт-в-байт (`info_service.py`, `info_text.md`, `intelligence_user_guide.md`, `settings.py`).

## 3. T-5216 prod-gate D9 (merge-drift) — ЧИСТАЯ ДОСТАВКА

Pre-deploy чтение прод-PG `bot_settings` (read-only, asyncpg из прод-venv):

| Ключ | До | Класс | После |
|---|---|---|---|
| `content.info_how_it_works` | sha `048e06c1…` = **слепок v5**, ver=5, delivered=5, 6915 зн. | SNAPSHOT, drift=0 | **CANON v6** (`1df850a6…`), ver=6, delivered=6, 9685 зн., маркер v6 на месте |
| `content.intelligence_guide` | sha `45d6d4e8…` = **слепок v2**, ver=2, delivered=2, 17367 зн. | SNAPSHOT, drift=0 | **CANON v3** (`149ae469…`), ver=3, delivered=3, 27590 зн., маркер v3 на месте |

Ручных правок нет (GATE_DRIFT=0) → вливание не требовалось, конфликтов нет. Журнал: `[config_cache] guide canon migrated | v=2→3`, `[config_cache] info canon migrated | v=5→6` (чистый snapshot-путь, force-delivery не срабатывал). TH-5 post-delivery: прод-БД читает **новый канон** (текст обоих ключей байт-равен код-канону v6/v3, не только маркеры), повтор после рестарта #2 — идентично. Идемпотентность: повторный прогон миграций при рестарте #2 — no-op.

## 4. Бэкап и откат

- **Бэкап окна (прецедент T-5226):** `VACUUM INTO` → `backups/pre_t5216_20261006_232333.db`, **integrity_check: ok, user_version=33, tables=120, 1.32 GB** (read-back из копии; копия перенесена sudo mv — `backups/` root-owned, замечание см. §7).
- **Soft (контент):** каноны читаются через версионирование; возврат текста — `POST /api/info/reset-canon` (prev_html/prev-слепки внутри значений БД), функции не зависят от текстов.
- **Cold (код):** `git revert 6f062fa` → 2.58.66; БД совместима в обе стороны (DDL=0); тексты v6/v3 при старом коде останутся (версии канонов только растут), возврат текстов — тем же reset-API. Restore-якорь: `backups/pre_t5216_20261006_232333.db`.
- Канон-откаты тестами покрыты (t5150/mca21-откаты зелёные — прецедент Лейн B).

## 5. Health и смоук (после каждого рестарта)

- `/healthz` **200 @2.58.67**: рестарт #1 — TRY1=502→TRY2=200 (systemd-интервал, прецедент mca-12); рестарт #2 — 502→200, далее 200 ×2 (`HZ_A`/`HZ_B`).
- `/api/health` **200**; `/api/info` и `/api/info/guide` unauth **401 ×2** (маршруты смонтированы, TMA-RBAC жив — контентный путь под TMA покрыт фокус-набором 335 passed; live-TMA-приёмка — T-5217, no-false-acceptance).
- Журнал (414 строк с boot): **ERR=0, CRIT=0, Traceback=0, NameError=0, locked=0**; vision-воркер жив (`media worker started` ×2); `NRestarts=0, ExecMainStatus=0`.
- Boot-лог: `plans/features/mca-release/startup_prod_t5216.log` (415 строк, R17 SECRET_HITS=0 — 6 паттернов).

## 6. Прогоны окна

Полный pytest (.venv, **сегментами** — hang #121 teardown `test_summary_memory` на глобальном py, известный; в venv сегменты без hang): G1 4305/1 + G2 3748/1 + G3 4306/3 = **12359 passed / 5 failed** — ровно 4 документированных pre-existing (tool_loop/nav_disclosure/status_control/mca09-registry) + betterstack real_302 средофлейк (изолированно 1 passed). Фокус mca-21 (8 файлов): **335 passed**. JS: **62/62**. Пин-набор: 326 passed. Замечание: глобальный py (3.12, aiogram 3.29 < required 3.31) даёт 8 артефакт-падений rich/cover-кластера — в venv их нет; lanes использовать `.venv`.

## 7. Инцидентальные замечания (Info, не блокёры)

- Прод-worktree **DIRTY=13** (untracked/локальное на сервере, pre-existing; identity 4/4 ключевых файлов чистые, ff-pull без конфликтов) — происхождение не инспектировалось, владелец может сверить `git status` на проде.
- `backups/` root-owned: юзер nik не пишет напрямую → бэкап создан в /tmp и перенесён sudo mv (файл на месте).
- Интерпретатор бота на проде — `/var/www/admin_bot/venv/bin/python` (не `.venv`); deploys-тулинг детектит по ExecStart.
- Планирование `plans/features/mca-release/` (spec/ADR/tasks) остаётся untracked до PM-close T-5237 — deployment.md ссылается на них по имени.

## 8. Вне окна — 3 красные строки §20.2 (owner-gate, идёт параллельно)

**Deep sleep / квантовый источник (ANU) / vision** — верификация effective-state §20.2 по живому прод-runtime в ЭТО окно НЕ входит: домен параллельного owner-gate. Конфиги и env этого окна их не касались (Δ KS = 0, env-переключений не было). Статусы этих строк — не из этого деплоя и этим VERIFIED не покрываются.

## 9. Итог

**VERIFIED.** Кандидат `6f062fa` (2.58.67) задеплоен на прод ff-пулом, identity 4/4, gate D9 — чистая доставка обоих канонов (v5→6, v2→3, drift=0), health/smoke зелёные ×2 рестарта, бэкап и rollback-пути готовы, R17 чист. 3 красные строки §20.2 — вне окна (owner-gate). Прод-базлайн: `6f062fa` / 2.58.67 / v33 / каталог 523 / KS 85 / reason 280 / тулы 14.
