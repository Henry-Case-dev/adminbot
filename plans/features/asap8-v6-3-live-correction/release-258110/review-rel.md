# REV-REL-258110 — независимое ревью релизного поезда (22.10.2026, UTC+12)

Вердикт: **Approved → DevOps** (готов к контролируемому деплою; parent не DONE до live-проверок).

Кандидат: **a8d2a45a1c4ee96b162c8b798b36b9b574d49ecd** (HEAD), deployed-база 2.58.109 = a1d8bd62.
Рабочее дерево: runtime (services/config/web/handlers) чист, 284 dirty — только plans/evidence чужих линз, в коммит a8d2a45a не входят (50 файлов = 31 bump + release-evidence; единственный runtime-файл в bump-коммите — config/settings.py, только APP_VERSION).

## 1. Состав — VERIFIED
- Runtime-дельта a1d8bd62..a8d2a45a: ровно 6 сервисов (direct_l1, chat_prompts, prompt_migrations, prompt_registry, direct_chat_service, initiative_observer) + settings (бамп 2.58.110) + README; web/handlers — НЕТ.
- ΔDDL=0: DDL-паттернов в services-диффе нет; services/database.py вне дельты (offline 18/18, ddl-check.txt); schema v37 не тронута; prompt_migrations = канон-лестница, не DDL.

## 2. Канонная безопасность — VERIFIED (независимое воспроизведение)
- FACTORY_SET **3507bd6f92eb** воспроизведён дважды независимо: (а) живой репо на кандидате через factory_set_fingerprint(); (б) чистые деревья a1d8bd62/a8d2a45a через git archive → base fp = **c19d35a1c093** == старой константе, cand fp = 3507bd6f92eb == константе; 89 блоков в обоих.
- Посимвольная сверка sha-карт: **changed = 1** (direct.base.l1_planner, 5fdc90b3f114 → ace6246bd360), added/removed = 0 — заявление «changed = 1» подтверждено.
- Лестница (изоляция констант обоих коммитов, exec без app-стека): base.SYSTEM_PROMPT == cand.PREV_DIRECT_L1_PLANNER_1022 **байт-в-байт**, 3022 симв / sha16 **5fdc90b3f1143abe** == прод-байты 2.58.109; cand.PREV_1021 == base.PREV_1021 (перевод на замороженную _DIRECT_L1_PLANNER_BASE_R1022 — byte-identical no-op, base == R1022 покадрово True); RULES-блок не менялся; новый канон реально эволюционировал (delivery/target_* присутствуют).
- Миграция exact-match: current==new → no-op (идемпотентно), current==prev → migrate, иначе «кастом юзера — НЕ трогаем» → 7 кастомных ключей владельца структурно защищены (плюс 108p custom/suppress/migration-суитов). Проверки цели §6: id+chat_id в одном запросе (чужой чат → target_missing), замена цели запрещена.

## 3. Ревью-артефакты — VERIFIED
- review-initreply-l1d.md: Needs Fixes по 1 книжному блокеру → db2b7044 нормализовал candidate_commit; гейт воспроизведён: `requirements_gate.py check --map plans/features/asap8-v6-3-live-correction/requirements-map.json --stage review --slice INITREPLY-L1D --candidate d87284c1dba6...` → **EXIT 0** (inventory=148, manual=79, scoped=4, errors=0).
- review-tails2.md: **Approved ×3** (81419cfd/c39c776e/20bc0dc3); коррекции deb8b31e/7a358c2c в поезде.

## 4. Гварды — VERIFIED (воспроизведено venv-ом, независимо)
F8 --check **582==REGISTRY EXIT 0**; initreply_binding **14p** + l1d_contract **15p** + F8-пины **29p** + help-sync **24p** (совместный прогон 82p); mca19 **33p**; write_points **1p/32d**; related-инициативные **129p** (f6 23 + p0-init-arch 17 + w5-vitality 18 + w5-gates 17 + p0-initfix 10 + smartmodule_utils 36 + nostalgia-ab 8); corrective_r1+expression_isolation **16p**; custom/suppress/legacy **108p**; JS-unit **39p**, node --check 4 изменённых js-файлов OK. pins24 PKG-110 868p/0f (venv aiogram 3.31.0) — принято по брифу (pins24-summary.md). Тесты ассертят контракт директивы §8 (кейсы 1–8), не реализацию.

## 5. Регресс-риски L1D — VERIFIED
- Direct/force маршруты: все дифф-ханки direct_chat_service — только зона инициативы (8654+); with_ids/include_delivery default-off и не передаются в Direct (grep); строка 2837 (_recent_bot_replies) была в базе.
- Ностальгия/heartbeat: standalone-отправка без reply сохранена (тест); резолвер 2.58.109 удалён — замена решения L1 эвристикой больше невозможна (case4).
- Антифлуд/cooldown: reacted учитывается в sent_stamps/окнах (initiative_observer); SendRecheck: semantic addressee + недоступная/протухшая/gone цель → cancel + bounded defer без отправки; standalone → fail-soft (кейсы 7/7b/7c/gone).

## 6. Гигиена — VERIFIED
Секрет-скан диффа a1d8bd62..a8d2a45a (36 109 строк, 10 паттернов): **0 попаданий**. Чужие dirty не в коммитах (см. выше). Evidence release-258110/ полна (19 артефактов, все гварды).

## 7. Postdeploy-план — присутствует, корректен
healthz 2.58.110; blob direct_chat_service/direct_l1/chat_prompts; fingerprint runtime==3507bd6f92eb; L1_PLAN телеметрия 48ч (формы участия — наблюдение); rollback = ветка release/fix-2.58.109 (=a1d8bd62, создать при деплое, прецедент deploy.json 258109); **плановый рестарт ОБЯЗАТЕЛЕН** (канонная константа + лестница стартовой миграции — задокументировано в README/frozen-fingerprint).

## Неблокирующие замечания
1. ROLLBACK_MIGRATIONS не покрывает prompts.direct_l1_planner_system_prompt (пре-существующий с 2.58.106 разрыв, поездом не усугублён): при код-откате PG останется на новом каноне — старый код сочтёт его кастомом (НЕ трогаем), деградация только functional (delivery-поля игнорируются старым нормализатором). При желании полного канон-отката — вручную вернуть PREV_1022 байты.
2. Рекомендация в postdeploy-чеклист DevOps: в логах рестарта проверить строку «[prompt_migration] канон обновлён | key=prompts.direct_l1_planner_system_prompt» и «кастом юзера — НЕ трогаем» для 7 кастомных ключей (fingerprint-проверка код не доказывает миграцию PG-значения).

## Вердикт
**Approved** (контролируемый деплой, parent не DONE): все обязательные преддеплойные позиции VERIFIED на точном кандидате a8d2a45a; live-позиции — по postdeploy-плану DevOps.
