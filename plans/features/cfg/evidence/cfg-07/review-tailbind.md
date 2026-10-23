# REV-CFG-TAILBIND — независимое ревью биндинг-коммитов CFG (21.10.2026)

**Вердикт: Approved** (биндинг-коммиты fff68d76 + 1c2fe2fa на HEAD e0c11306..1c2fe2fa; нового кода нет — проверялась честность привязки).

- Ревьюер: Reviewer (лейн REV-CFG-TAILBIND, read-only). Кандидат: коммиты fff68d76, 1c2fe2fa; карта `plans/features/cfg/requirements-map.json` @1c2fe2fa (candidate d860a529, deployed 8ea6ed4e / 2.58.104).

## 1. Выборочная реверификация биндинга (содержание, не описания)

| Строка | Заявка | Факт-проверка | Итог |
|---|---|---|---|
| CFG-07B.1 | Expression = переключатель мата | design-add-exp.md §1: режимы off/occasional/frequent, «CFG-07B добавляет параметром мат (factory ON, GLOBAL/CHAT, Inspector)» | OK |
| CFG-07B.2 | effective-правило, closed-set, миграция | test_add_exp_expression.py существует (36 тестов), артефакты sha-совпадают | OK |
| CFG-07B.3 | ON канон владельца / OFF 0 мата | 07cg-dictionary.md + off-трасса присутствуют | OK |
| CFG-07B.5 | внутренние процессы нейтральны | unified-core README §4 (16 трасс) + route-coverage | OK |
| CFG-07B.7 | честная оговорка: мехсчётчики отменены владельцем 20.10 | cfg-07b-reused README «Что остаётся» п.2 + build-plan:97 (директива «no counters/postprocessor/extra LLM») + ТЗ current_task.md:1591/1765 («не механическое встраивание», «не постпроцессор») | OK |
| CFG-07C.1/.2 | guard delivery-шов; словарь 14 семей/42 маркера | review-07cg-tail.md + 07cg-dictionary.md существуют, sha OK | OK |
| CFG-07C.6 | wiring 2.58.103 по прод-байтам | release-103/deploy.json + README @ce77b2c4 | OK |
| CFG-07D.7 | Initiative проверён честно | bind-tail:63 «отдельного runtime-теста нет — зафиксировано честно»; trace-initiative-writer.txt среди 16 трасс unified-core | OK |
| CFG-03.1/.2 | registry 582==REGISTRY, ui_missing=0, working=568/14, inconsistencies=3 | audit-summary.json: все числа совпадают дословно; F8-crosscheck строка в файле | OK |
| CFG-03.3/.5/.8 | roundtrips; честные no_consumer; изоляция | audit-summary + failures.md (F1 FIXED/F2 DEFERRED/F3-F5) + README §Design | OK |
| CFG-03 live 03.4/.6/.11/.12/R4 | production @113f3a62 (заморожено) | 10/10 артефактов существуют, sha256 совпадают; 113f3a62 — реальный commit | OK |

Тесты (прогон ревьюера на HEAD 21.10): `test_cfg03_param_audit` **16 passed**; `test_cfg07_guard_07d5` + `test_cfg07_guard_tail` + `test_unified_core_route_coverage` — **88 passed**. Арифметика «41 CONTRACT» для 07d5 (31 def + 2 parametrize-набора) правдоподобна, прогон зелёный.

sha256: ~30 артефактов всех типов (static/test/live/production/ui) пересчитаны — расхождений 0; отсутствующих artifact_path 0.

## 2. Честные остатки

- **CFG-07D.6 PENDING** — формулировка корректна и конкретна: не хватает маскированного дайджеста корпуса + привязки к deployed SHA (2.58.104=8ea6ed4e) и флагу v2; правило приватности подтверждено (build-plan:99, правило 06F.1). Не завышен.
- **CFG-07D.5 live-нога** — строка (VERIFIED, live_required=True) НЕ несёт live-элемента на deployed 2.58.104; но живое доказательство в репо есть и проверено ревьюером: release-104/deploy.json (feature=«CFG-07D.5 bounded metatext retry…», delta.runtime_set = factcheck_service/negative_constraints/prompt_style_blocks/public_speech_guard, healthz 2.58.104, T0 2026-10-20T21:00:23Z, ERR=0). Коммиты под ревью строку не трогали (последняя правка 912c79b8), остаток раскрыт в fff68d76 как «foreign». **Не блокер**; минимальная правка — один alias live-элемент @d860a529 (release-104/deploy.json) в строку CFG-07D.5 отдельным ledger- touches до закрытия CFG-FINAL (заодно проставить отсутствующий `type` у первого элемента).

## 3. Гейты (воспроизведены)

- `--stage plan` → **EXIT 0** (inventory=246 manual=42 errors=0).
- `--stage review --slice CFG-07B --candidate d860a529…` → **EXIT 0, errors=0**.
- `--stage review --slice CFG-07C --candidate d860a529…` → **2 ошибки** — ровно заявленные честные остатки (07D.5 live-нога + 07D.6 PENDING).
- `--stage review --slice CFG-03 --candidate 3022e6e8…(full SHA)` → **15 ошибок** — ровно как заявлено. Разложение: 1 map-level (candidate карты d860a529 ≠ срезовый 3022e6e8, конвенция dd6acf83) + 14 по замороженным live-строкам @113f3a62 (03.4/.6/.11/.12 ×3 + R4 ×2; перенавеска запрещена фризом ACCEPTANCE-95). С коротким SHA — 43 (артефакт вызова, не дыра).
- **Вердикт по residual-вопросу:** остатки CFG-03 — **структурные, не дыра**. Корректная форма приёмки — per-candidate срез с собственным кандидатом слайса (полный SHA) + неизменяемость замороженных live-строк; перереревеска всех строк на map-candidate d860a529 ослабила бы/фальсифицировала evidence и запрещена. Существование/sha/содержание/тесты за всеми 15 остатками проверены независимо — доказательная база реальна.

## 4. Гигиена

- fff68d76: только bind-tail.md (+81) + карта; ровно 23 строки слайсов CFG-07B/07C (07B.F, ADD-1.C4, 07B.1–.8, 07D.3/.4/.6/.7, ADD-1.T7, CFG-07.B, CFG-07C.F, 07C.1–.6) = 22 VERIFIED + 1 PENDING. Чужих строк/файлов нет.
- 1c2fe2fa: только prep-cfg-03.md + карта; ровно 14 строк CFG-03 (11 REUSE + frame ADD-1.T3/F/M в additional_requirements). Кода/тестов не трогали.
- Аlias-предки проверены `git merge-base --is-ancestor`: 1b23d4c9/7c3a1350/f1e31d27/8cd2ca14/ce77b2c4 ⊂ d860a529 ⊂ 8ea6ed4e (deployed). Статус-семантика не завышена: PENDING сохранён, owner_optional не тронут, VERIFIED везде опираются на существующие sha-сверенные артефакты.

## 5. G3-готовность (барьер CFG-FINAL)

Статусы: CFG-03 16/16 VERIFIED (+3 frame VERIFIED), CFG-06 81 VERIFIED + 3 READY_FOR_LIVE (06F.6/06G.8/06J.6) + 06.B, CFG-07A 10/10, CFG-07B 11/11, CFG-07C 8 VERIFIED + 1 PENDING.

Команда барьера из cfg-final-plan: **G3: BLOCKED — CFG-06F.6, CFG-06J.6, CFG-06.B, CFG-07D.6**.
- 06F.6/06J.6/06.B — санкционированные постдеплой-канарейки (READY_FOR_LIVE: live-часть после включения flags.factcheck_pipeline_v2; 06G.8 owner_optional — не блокирует по плану).
- **CFG-07D.6 — единственная реальная инженерная недостаёт** (скриншот-корпус: маскированный дайджест + deployed-SHA-привязка).

Барьер НЕ достигнут; после закрытия 07D.6 и фактических канареек G3 открывается. Вердикт по биндингу это не меняет: привязки честные.

## 6. Неблокирующие замечания

1. CFG-07D.5: добавить alias live-элемент @d860a529 (release-104/deploy.json) + проставить `type` первого элемента — одно касание карты до CFG-FINAL (см. §2).
2. prep-cfg-03 §2 (строка «working 565») — исторические цифры снапшота 579; карта корректно несёт 582/568. Действий нет.
