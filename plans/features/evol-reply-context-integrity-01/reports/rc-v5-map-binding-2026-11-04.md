# RC v5 — привязка карты к принятому кандидату `fb761f73` (PM)

- Дата: 2026-11-04
- Кандидат: `fb761f73731dad6e2b793ff69d4647de37ed8a53` (ветка `rc/accept-fixes`, база `4baccb1d`), merge `00a98cae716b6ef60d081029cddff0a303ff4354` в `evol/impl`.
- Приёмочный артефакт: `plans/features/evol/reports/rc-v5-final-acceptance.md`
  (sha256 `f8ec1152ab256c342a2b489b13b2a1d778933292b06544251604e69d5910a8fe`; содержит раунд 1, Re-check 1 и Re-check 2).
- Трасса: `plans/features/evol-reply-context-integrity-01/evidence/trace-factcheck-target.txt`
  (sha256 `24b67a2597e75a0c1566122a51de4d16e4bfb34fc976c6248cbc426ed70fc588`, воспроизводится
  `scripts/evol_trace_factcheck_target.py`).
- Карта: `plans/features/evol-reply-context-integrity-01/requirements-map.json` (`candidate_commit` = `fb761f73`).

## Что сделано

1. `candidate_commit` карты переведён на принятый кандидат; добавлен блок
   `candidate_binding_final_acceptance` (кандидат, merge, база, предыдущий кандидат, артефакт и его sha256,
   итоги сценариев), исторические привязки `candidate_binding` и `wave_bindings` сохранены с пометкой.
2. Таблица 120 сценариев разобрана из артефакта приёмки, а не по пересказу:
   **PASS 97 / FAIL 0 / NOT PROVEN 23**. Все 97 строк `RC-S0xx` со статусом PASS переведены в `VERIFIED`
   с доказательством, привязанным к `fb761f73` (артефакт приёмки; для сценария 26 дополнительно файл трассы).
3. 23 строки NOT PROVEN (18, 21, 22, 25, 27, 34, 36, 37, 38, 41, 42, 47, 50, 51, 63, 65, 87, 89, 90,
   102, 107, 112, 119) оставлены `PENDING`; в `pending_note` — точная причина из таблицы и срез/роль,
   которые могут её закрыть.
4. 50 ранее VERIFIED строк вне таблицы сценариев (фактчек-срез `bfa26e60`, потребители `44364e83`)
   перепривязаны к `fb761f73` записью о переносе: диф Re-check 2 затрагивает только
   `chat_context.py`, `direct_chat_service.py`, `factcheck_orchestrator.py`, `factcheck_suitability.py`
   и `tests/test_evol_rc_accept_fixes.py`; на кандидате повторно прогнаны 179 и 390 тестов, пробы
   P-DIR1/P-DIR2/P-FC1/P-RST/P-MSC воспроизведены.
5. Закрыты: блокирующая заметка `N1-TRACE-MANUAL` (трасса перегенерирована реальным прогоном,
   `provider_attempts=2` при `provider_failures=2`, 7/7 стадий) и открытый пункт
   `B3-REPLY-CHAINS-SILENT-DROP` (пометка вытесненной цепочки, `omitted_chain=2`, сценарий 111 PASS).
   Остальные пункты (N2, N3, N4, N5, GAP-TOOL-ROUTE, B1, B2, B4, B5) остаются открытыми с владельцами.
6. Строки вне таблицы сценариев, у которых нет построчного доказательства на этом кандидате,
   оставлены `PENDING` (им добавлено явное `pending_note`); 6 строк с прежними частичными заметками
   сохранены как есть.

## Итог по обязательным строкам

- Всего обязательных: **285** (247 строк инвентаря + 38 ручных строк).
- `VERIFIED` **147**, `PENDING` **138**, `READY_FOR_LIVE` 0, `FAILED` 0.
- 147 = 137 строк инвентаря (57 прежних + 80 новых PASS-сценариев) и 10 ручных строк.

## Гейт `--stage review` на `fb761f73` (по срезам)

Структурных ошибок нет: источник и его sha256 совпадают, инвентарь полон, кандидат существует в
репозитории, все привязанные артефакты существуют и их sha256 совпадают, граф срезов валиден.
Все ошибки — одного класса: `mandatory not ['VERIFIED'] (got PENDING)`.

| Срез | scoped | errors | exit |
| --- | --- | --- | --- |
| RC-TARGET-ANCHOR | 41 | 10 | 1 |
| RC-MEDIA-OPTIONAL | 27 | 9 | 1 |
| RC-EVIDENCE-STATUS | 27 | 9 | 1 |
| RC-TRACE-ACCEPT | 28 | 24 | 1 |
| RC-SPEECH-BOUNDARY | 35 | 11 | 1 |
| RC-CONTEXT-FIDELITY | 49 | 27 | 1 |
| RC-CONTEXT-CLAIM | 31 | 24 | 1 |
| RC-DIRECT-SELFCORR | 47 | 24 | 1 |

Сумма ошибок = 138 = числу PENDING обязательных строк.

## Вывод

Пакет **не завершён и не выпускается** по стандарту гейта: 23 сценария NOT PROVEN и 115 строк вне
таблицы сценариев остаются без доказательства на принятом кандидате. Привязка карты (B2) закрыта в той
части, которую ставил Reviewer: кандидат, артефакт и трасса привязаны, структура карты проходит проверку.
