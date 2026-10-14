# ASAP 8 v6 — Forensic (claim vs HEAD/prod)

Дата: 13.10.2026. Baseline: `1e980275ce5c857b825860b50a34a2486c790359` (2.58.77) — сверён git log, совпадает с v6.

## Установленные факты

1. **Deploy evidence**: кандидат 1e98027 доставлен на прод paramiko-сеансом (git pull → NEW=1e98027, systemctl restart RC=0), healthz 200 @ 2.58.77 (дважды: волна 2 и волна 3). Целевые функциональные prod-пробы (живой Summary, styled cover, инициатива, embeddings rotation, proxy health) НЕ выполнялись — это LIVE-зазор, зафиксированный в ledger.
2. **F1–F9 в lineage подтверждены**: 7fdeaaf (F1), fcbbf12 (F2), cbda23b (F6), dc9ca1c (F9), a12e6bf (F3), 781e9b3 (F8), 2e145a4 (F5), 02b38cb (F4), df1aac4 (F7). Кодовые контракты существуют; прод-поведение не доказано (C01–C09 = CODE_PRESENT_LIVE_UNVERIFIED, кроме оговорок PARTIAL).
3. **C10 ABSENT**: f10-report не существует; были только test-pin коммиты (3f5b912, 855a3e5) — re-pin ≠ финальная reconciliation.
4. **workflow_state/runtime_task drift**: на момент v6-старта workflow_state описывал финал round-1 без v6; runtime_task оставался на F1-стадии. Исправляется в agent-owned файлах (v6 §A.4).

## Найденные root causes (код, не догадки)

- **D08** (Random toggle «Параметр недоступен»): `config_cache.get_all()` (config_cache.py:495-523) возвращает bot_settings rows + синтетику только keys_random → PG-only ParamSpec `memory.random_enabled` (Settings-поля нет, строки БД нет до первой записи) отсутствует в `/api/config` → `_moduleConfigItem` null → toast (app.js:9645). Прецедент решения: ANU bootstrap (configured=false placeholder в metadata).
- **D02** (supergroup migration): `add_link` (chat_lifecycle.py:243) вызывается до `migrate_profile`; миграция резолвит link и выходит `moved=False, merged=False` (chat_lore_store.py:754-756) → пустой новый профиль, старые данные сиротеют. Тесты — FakeStore/in-memory, real-storage нет.
- **D06** (chat isolation): `_search_archive_knn` (summary_memory.py:2752) — комментарий признаёт «KNN top-k отдельно, фильтр chat_id в Python»; float-путь k=limit ровно; `_dedup_knn` k=3 глобально. §18F.4-механизм не закрыт.
- **D09** (Deep Sleep 00:00): `int(... or 7)` (dream_worker.py:1682) — валидный 0 заменяется на 7.
- **C03A** (styled не появляется/не восстанавливается): finish_cover_job маппит RESULT_BASE → completed (cover_style_jobs.py:636-637) — retry нет; style инлайн в публикации (summary_generator.py:3202) — job не mark_running, watchdog/recover_stale не видят, рестарт = зомби; `semantic_preservation_failed`/`UNVERIFIED_SEMANTIC` в коде отсутствуют.
- **C06A** (Initiative «не запускалось»): heartbeat-джоба регистрируется один раз в start() (memory_maintenance.py:185) — hot-ON без рестарта тиков не даёт; funnel не подключён к UI (grep подтверждён); `_heartbeat_last_tick` in-memory (memory_maintenance.py:42); тик молчит при пустых due/expired.

## Dropped/rca items → owner

Полные цепочки стадий и лог-планы прод-наблюдения — в rca-c03a-styled-cover.md и rca-c06a-initiative.md. Ничего не классифицировано backlog без owner exclusion (v6 §E).
