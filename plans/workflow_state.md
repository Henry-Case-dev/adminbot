# Workflow State

Task: Полная очередь `plans/current_task.md` + новая P0 `embed-identity-compat` (реестр `plans/progress_scope.json`: 13 задач)
Task source: current_task.md + `plans/features/embed-identity-compat/source-2026-10-23.md` (дословный снимок ТЗ владельца 23.10)
Status: in_progress — ДЕПЛОЙ 2.58.112 ПРИДЕРЖАН: рестарт запустил бы полную перевекторизацию, что запрещено новым ТЗ
Primary phase: build → review → delivery

Active lanes:
- W4-UI | Builder | writer web/ | asap-speech-arch W4 | bg:ses_e9bb38830ffeB8BTAG4JgtGXYA | U-01…U-09
- PM-EMBED-IDENTITY | PM | writer plans/ | embed-identity-compat | bg:ses_e9ac3f982ffeJoPCeR5Yx5c7YF | карта + реестр
- ARCH-EMBED-IDENTITY | Architect | read-only + design | embed-identity-compat | bg:ses_e9ac3f982ffdL6qbsCUyNrIC1i | разделение identity + canary

Поезд 2.58.112 (СОБРАН, НЕ ЗАДЕПЛОЕН):
- bump `678c0616` в origin/master (база `924b3b51`), версия 2.58.112, 57 файлов, ΔDDL=0, `FACTORY_SET=24ae494ac422`.
- Guard'ы: offline 18/18, pins24 868/0, F8 582==REGISTRY, help-sync 24, JS-unit 39, ASAP-2 155, summary 179, embed 74, B11 24; суммарно 1507 passed / 0 failed.
- Состав: asap2 Direct Chat, factview+B-1, embed-fallback slots, summary multi-paragraph revision + фикстура, B11 честная диагностика, embed-rebuild identity.
- Точка отката: `fbf9013d` (прод 2.58.111).

ПОЧЕМУ ПРИДЕРЖАН: текущий код (`5877810d`) при рестарте регистрирует поколение под новый fp и запускает полную перестройку ~15 819 фактов (~316 вызовов). Kill-switch OFF не спасает: OFF-путь «backfill-fill-missing» может писать новые векторы в старый индекс. Новое ТЗ запрещает перевекторизацию при смене только шлюза.

Прод-факты: 2.58.111 @ fbf9013d, healthz 200. Эмбеддинги apinet работают (200, dim 3072), квоты разведены (`apinet_paid`/`google_free_1`/`google_free_2`). Векторная память FTS-only: поколения `building` с 29.09 без активации; 4 048 фактов без векторов; 16 003 старых Google-векторов.

Одобрено и готово к поезду: asap2 (74 VERIFIED), factview B-1, embed-fallback, summary-revision, B11, SOUL-1 фикстуры, embed-rebuild B1/B2.
Итоги 23.10: прогресс 1113/1198 (92%); исправлены ложный «ok» диагностики, ревизия сводок по всем абзацам, per-slot адреса embedding, A→B→A и честный build_failed.

Next unlocks:
1. ARCH-EMBED-IDENTITY дизайн → Builder реализует canary/identity-split → Reviewer.
2. Затем объединённый поезд 2.58.113 (2.58.112 + compat) и ОДИН деплой с рестартом: canary решает «старый индекс / insufficient / миграция».
3. W4-UI → в тот же или следующий поезд после ревью.

Human gate: none
Progress scope: plans/progress_scope.json | fresh (13 задач после регистрации)
Updated: 2026-10-23 06:40 local (UTC+12)
