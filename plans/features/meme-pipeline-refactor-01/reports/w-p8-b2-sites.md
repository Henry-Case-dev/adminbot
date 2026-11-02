# B2 — координация на остальных точках отправки текста (Builder, 03.11.2026)

Основание: `arch/initiative-coordination.md` §3.5 (заморожено Architect, коммит
`7ab7c811`), находка ревью P8. База: `aa13e4b6`, ветка `feat/meme-init-coord`.

## 1. Находка

`handle_initiative` — единственный шов отправки текста инициативы, но координация
стояла у ОДНОГО вызывающего (наблюдатель-повод, `_act_on_opportunity`), а четыре
вызова шли мимо брони:

| Точка | Что было |
|---|---|
| делегированный кандидат nostalgia (`_delegate_initiative`) | ни ledger, ни бронь, ни `publish_guard` |
| legacy-отправка nostalgia (K1/K3 OFF, `bot.send_message`) | прямой `send_message`, невидим для мема |
| heartbeat намерений (`_run_initiative_candidate` из `_tick_intent_heartbeat`) | ни брони, ни guard-а; LLM-бюджет тратился ДО проверки |
| реальный прогон админской диагностики (`run_check`, publish-режим) | публикация мимо брони |

Обе стороны спам-пары были живыми: nostalgia/heartbeat не читали ни ledger, ни
строку брони и не забирали аренду.

## 2. Что сделано

1. **Общий шов `publication_coordination.TextPublication` + `open_text_publication`**
   — один порядок для всех sender'ов: `precheck → acquire → publish_guard →
   release`. Интервал — одна функция (`resolve_cross_type_interval`); последняя
   публикация другого типа берётся из строки брони (`last_publish_ts/kind`), а
   для путей без брони — из журнала выводов через `precheck` (§3.1, §3.5).
2. Сигнатура `handle_initiative` НЕ менялась (`publish_guard` уже существовал).
3. Heartbeat: координация **до** траты LLM-бюджета. Отказ → намерение остаётся
   `pending`/`deferred`, `worker_budget.consume` не вызывается.
4. Админская диагностика: реальный прогон занимает бронь (`claim=True`), dry-run —
   нет (`claim=False`): проверка ничего не публикует, поэтому и состояние чата не
   трогает, но `precheck` честно объясняет интервал, а `guard()` возвращает ту же
   причину отказа, какую увидел бы боевой путь.
5. Деградация без таблицы брони сохраняется: `coordination="degraded"`, текст
   публикуется (проверено T1-degraded).

Защита от двух реальных ловушек проигравшего: `guard()`/`close()` никогда не
работают с чужим `claim_id` (у проигравшего в решении лежит id ПОБЕДИТЕЛЯ —
`begin_sending`/`release` по нему перевели бы/освободили бы чужую аренду).

## 3. Структурная проверка (T5)

Тест `test_t5_every_text_send_site_passes_publish_guard` строит AST всего
продакшн-кода (кроме `tests/`, `plans/`, `docs/` и вендоров) и требует, чтобы
КАЖДЫЙ вызов шва передавал `publish_guard=`. Нарушение — падение сборки.

* ловятся оба имени: `handle_initiative` и DI-параметр `initiative_entry`
  (heartbeat получает шов параметром, иначе проверка его бы не видела);
* `**kwargs` в вызове — тоже нарушение (аргумент невозможно проверить);
* проверка самопроверяемая: тест требует ≥4 вызова в известных модулях, поэтому
  «проверка ничего не нашла» не может пройти молча;
* фальсифицируемость — вторая часть T5 пишет три временных модуля (без guard,
  с guard, со `**kwargs`) и убеждается, что проверка ловит ровно два.

Legacy-отправка nostalgia идёт мимо шва (`bot.send_message`) — её координирует
`TextPublication` напрямую, покрытие в T2.

## 4. Тесты T1–T5 (наблюдаемое поведение)

Файл: `tests/test_initiative_coordination.py` (раздел «6. остальные sender'ы»),
TEST-LIFECYCLE: CONTRACT, owner=OI-2026-11-03-INITIATIVE-INDEPENDENCE.

| Тест | Утверждает |
|---|---|
| T1 delegated | guard передан в шов; в момент «отправки» строка брони `sending`/`initiative_reply`; после — `released` + watermark |
| T1 delegated-отказ | чужая бронь `sending` → шов не вызван, статус `cancelled`, чужая бронь не тронута |
| T1 degraded | таблицы брони нет → `coordination=degraded`, отправка всё равно состоялась |
| T2 «мем после nostalgia» | legacy-отправка под бронью (`sending` в момент send), после — watermark строки; `acquire` мема через 60 с отказан с `cross_type_interval` |
| T2 «nostalgia после мема» | мем опубликовал → nostalgia legacy: `skipped`, `bot.calls == []`, причина `publication_conflict` в `nostalgia_log` |
| T3 heartbeat | отказ: `sent == []`, intent `pending`, `attempts == 0`, `worker_budget.consume` не вызван; после интервала — ровно одна отправка (`sending` в момент send) + `released` + watermark |
| T4 publish-режим | реальный прогон: одна отправка, в момент send бронь `sending`, после — `released`+watermark |
| T4 publish-конфликт | чужой `sending` → отправки нет, `status=cancelled/publication_conflict`, чужая бронь цела |
| T4 dry-run | `claim == None`, строка брони не появилась, mock-отправка работает |
| T5 structural | все вызовы шва с `publish_guard`; ≥4 известных точки на месте |
| T5 falsification | новомодный незащищённый вызов и `**kwargs` ловятся |

## 5. Мутации (каждая проверка умеет падать)

Проверено на этом кандидате (файлы восстановлены побайтово, sha256 сверен):

| Мутация | Наблюдаемый результат |
|---|---|
| убрать `publish_guard=` в `_delegate_initiative` | `test_t1_nostalgia_delegated_takes_claim_and_hands_guard` FAIL + `test_t5_every_text_send_site_passes_publish_guard` FAIL (указывает файл:строку) |
| заменить координацию в legacy-nostalgia заглушкой (нет брони) | оба T2 FAIL (нет `sending` в момент send, нет watermark, мем не отказан) |
| убрать `publish_guard=` в heartbeat (`memory_maintenance`) | T3 FAIL: `assert 'claimed' == 'sending'` |
| убрать `publish_guard=` в диагностике | T4 (реальный прогон) FAIL: `claimed != sending`; T4 (чужой `sending`) FAIL: отправка состоялась |
| добавить в `services/` новый модуль с вызовом `handle_initiative` без guard | T5 FAIL: `services/probe_unguarded_sender.py:8` (модуль удалён, T5 снова зелёный) |

## 6. Прогоны (этот кандидат, после восстановления мутаций)

- `tests/test_initiative_coordination.py` — 59 passed.
- initiative/heartbeat/observer/диагностика/телеметрия (`test_initiative_coordination`,
  `test_asap8_f6_initiative`, `test_asap8_v63_b01_initiative_observer`,
  `test_asap8_v6_c06a_heartbeat`, `test_initiative_delivery_telemetry`,
  `test_p0_initfix_initiative_observer`, `test_soul1_w5_initiative_vitality`,
  `test_soul1_w5_observer_gates`) — 157 passed.
- nostalgia (`test_nostalgia_worker`, `test_nostalgia_w2`,
  `test_p0_followup_nostalgia_ab`, `test_nostalgia_corrective_r1`,
  `test_nostalgia_layer_a`, `test_nostalgia_revamp_round1015`,
  `test_asap5_integration_w3`) — 170 passed (в одном прогоне из трёх падал
  pre-existing флак, см. §7).
- meme/webapp (`test_evol014_meme_initiative`, `test_meme_command_autodelete`,
  `test_meme_pipeline_api`, `test_meme_pipeline_stages`,
  `test_p0_meme_image_only`, `test_webapp_f6_round1025`) — 118 passed.

## 7. Остаточные риски и что НЕ доказано

- **Pre-existing флак в наборах nostalgia (не мой).** В смешанных прогонах
  `test_nostalgia_worker` / `test_asap5_integration_w3` иногда падает один тест
  (`test_legacy_free_text_still_content`, `test_year_back_candidate_sent`,
  `test_d02…`, `test_d05…`, `test_d13…`). Воспроизведено на базе `aa13e4b6`
  (чистое дерево, отдельный worktree): 1 падение из 6 прогонов того же набора,
  в том числе тот же `test_legacy_free_text_still_content`. Причина —
  «протёкшая» фоновая задача `mca_random_source` (`_schedule_refill` →
  `create_task`) пишет в уже закрытое in-memory соединение предыдущего теста,
  плюс реальные часы в гейтах `handle_initiative` (`status=silent`). К
  координации публикаций отношения не имеет: падение воспроизводится на коде
  без неё.
- Пять точек координации проверены на файловой SQLite; поведение на боевом объёме
  и при N процессах не проверялось (это свойство CAS уже покрыто R3 пакета).
- Ledger для legacy-nostalgia (`mca_bot_outputs`, kind `initiative_reply`) по-прежнему
  НЕ пишется: публикация видна другому механизму через строку брони, но не через
  журнал выводов. Из-за этого общий антифлуд (`ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS`)
  и `min_gap` текстовой инициативы не видят legacy-отправку nostalgia. Это
  существовавшее поведение, не входило в замороженное решение, не чинилось
  (записано как побочная находка).
- Живая приёмка (`/meme` в чате владельца + наблюдение интервала) остаётся за
  релизной проверкой; она не блокирует независимое ревью этого среза.
