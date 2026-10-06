# deployment.md — mca-20-temporal-factcheck (попытка 1, T-5150)

**Вердикт: FAILED** (прод-старт кандидата `968b049` не завершается: миграция v33 не применяется, веб-слой не поднимается). Прод **стабилизирован откатом** на `d298f1f` (2.58.63) — состояние T-5126b VERIFIED. **СТОП конвейера**, дельта → Builder+Reviewer.

## 1. Деплой-источник

- **feat `968b049`** (`968b04961840d8060389b0f143b09ba145f9a5cc`, 114 файлов, +15146/−9670): push ff `f78f6fe..968b049` в origin/master без force. Кандидат = review Approved (итер.2) + deploy-bump 2.58.63→2.58.64 (release-owned: README header, F8 meta-pin, 4 py-пина, 4 js-харнесса, `tools/_d2_mca20_release_bump.py` — прецедент `_t5126_release_bump.py`).
- Биндинг: манифест `plans/reports/mca20_wth_manifest_review.txt` (MANIFEST_SHA256 `ef76a16e…a21bb0c`, 107 файлов, HEAD `d298f1f`). Preflight DevOps: 104/107 байт-в-байт; 3 пост-манифестных дрейфа — `mca-19/deployment.md` (финал T-5126b, уже в origin), `tools/_t5126b_deploy.py` (мусор T-5126b, не коммичен), arch-frames §1.2.10 (mca-12 planning WIP, санкционирован брифом, [D-2]-disclosure в feat-коммите). Кандидатный код — без расхождений.
- Прогоны пре-деплоя: focused mca-20 **80 passed**; js **60/60**; полный pytest **12285/4** (все 4 документированные pre-existing: tool_loop/nav_disclosure/status_control/mca09-pollution).

## 2. Хронология (2026-10-06, UTC)

1. **Pull ff ок:** прод `d298f1f → 968b049`; identity-хеши на диске байт-в-байт с деревом: `mca_vision.py d6032dc0…` (фикс T-5126b цел), `temporal_factcheck.py 1905d61a…`, `database.py db4b4131…`, `settings.py e8afffab…`.
2. **KS:** 0 оверрайдов `MCA_TEMPORAL_*`, 0 `MCA_VISION_*` (env-only, default ON).
3. **Pre-счётчики (v32, book32×1):** bot_outputs 101, graph_facts 16331, random_draws 20, media_assets 92, media_analyses 0.
4. **Рестарт #1 (12:19:37, PID 4969):** backup-guard отработал — `pre_migration_20261006_121956.db` создан 12:19:56; prompt/config-миграции INFO прошли.
5. **ОТКАЗ:** healthz **502 ×8** (12:20:57–12:21:37) и в 12:26; **v33 не применена** (user_version 32, book33=0, новых таблиц 0, idx 0) при живом процессе (active/running, NRestarts=0, воркеры тикали, WATCHDOG_SWEEP success). Веб-слой не поднялся за 7+ минут. Счётчики post идентичны pre — **данные целы**.
6. **Стабилизация (12:28±):** cold rollback `git reset --hard d298f1f` + рестарт → healthz **200 `{"status":"ok","version":"2.58.63"}`** (RB_TRY3), ERROR/CRITICAL/Traceback = 0.
7. **Финальное состояние прода:** healthz 200 @2.58.63, api/health 200 (проверено извне после сессии).

## 3. Точный отказ (для Builder+Reviewer)

- Симптом: процесс стартует и живёт (воркеры/apscheduler тикают), но **v33 замирает между backup-guard'ом и применением DDL** (бэкап есть, book/user_version/DDL — нет) и **uvicorn/web не поднимается** (502 непрерывно). Не crash-loop (NRestarts=0).
- Локально невоспроизводим тестами: полный suite 12285/4, focused 80, миграционные тесты зелёные. Start-smoke реального прод-пути (прецедент T-5126b) на v33-путь не покрывает старт-очередь web vs миграция.
- Точный Traceback стартового окна 12:19:37–12:19:56 grep-срезом не захвачен (пойман только INFO-хвост); при retry — снять ПОЛНЫЙ стартовый лог юнита без фильтра, окно 0–3 мин.
- Рабочие гипотезы (проверять локально): блокировка/медленный read-back 1.3GB в backup-guard между копией и DDL; дедлок/порядок «миграция → web» в стартовой последовательности; средозависимое отличие прод-FS. Продуктовое поведение не менялось DevOps-лейном — возврат целиком Builder'у.

## 4. Rollback-состояние

- **Активирован cold:** прод-код = `d298f1f` (2.58.63), БД = v32 неповреждённая, v33-артефактов нет (кроме безвредного бэкап-файла guard'а). Soft-рубильники не потребовались (старт не дошёл до фичи).
- **Адреса:** soft — 3×`MCA_TEMPORAL_*_ENABLED=false` (OFF = бит-в-бит `d298f1f`/2.58.63); cold — `git revert 968b049` / reset на родителя.
- **Важно для retry:** прод сейчас позади origin/master (`d298f1f` vs `968b049`+docs). Перед следующим деплоем — `git reset --hard origin/master`, затем обычный runbook (миграция v33 применится заново с guard'ом, book (33,'factcheck_temporal') ×1, рестарт ×2, healthz ×2 @2.58.64, [vision] media worker started).

## 5. R17

Секреты не печатались и не коммитились; scrub в драйверах; вывод логов фильтрован. 0 нарушений.

---
*Попытка 1 (T-5150, 06.10.2026): FAILED, СТОП. Следующая попытка — после дельты Builder+Reviewer.*

---

## 6. Попытка 2 — T-5150r (старт-фикс, review iter.3 «к T-5150r ДА»)

**Дельта-биндинг:** манифест итер.3 `plans/reports/mca20_wth_manifest_review.txt` (MANIFEST_SHA256 `695dac58…a6fd09`, FILE_COUNT 18; preflight DevOps 18/18 байт-в-байт, recipe воспроизведён). Параллельные lane-пакеты (mca-12/17c/21, MEMORY, AGENTS) — fingerprint-only, не коммичены.

**Механизм фикса** (`services/database.py` `_run_migrations`): INFO-лог-след guard→DDL→book с таймингами; busy_timeout 5s→30s на DDL-окно; bounded retry ×3 на `database is locked`. Попутно `services/mca_self_model.py` — 7-строчный fail-soft фикс int(datetime) `:1891` (mca-18 legacy traits, ежечасный TypeError из incidental попытки 1-эпохи). NEW: `tests/test_t5150_startup_migrations_round1046.py`, `tests/test_mca18_legacy_ts_datetime_round1046.py`, сим-тул `tools/_t5150_startup_sim.py` + лог `startup_sim_t5150r.log` (bound explicitly). Прогоны пре-деплоя: новые+focused mca-20 = **88 passed**.

**Прод-фаза:** см. §7 (финал — VERIFIED/FAILED ниже).
