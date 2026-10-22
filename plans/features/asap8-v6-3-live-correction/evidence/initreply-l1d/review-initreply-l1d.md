# REV-INITIATIVE-L1D — независимое ревью (22.10.2026, UTC+12)

Вердикт: **Needs Fixes — 1 блокер (метаданные гейта), код подтверждён.**

Кандидат: e67a58e7 + d87284c1 + 6196464d (HEAD = 6196464df9afdc9a37233a3d05d1a826b47471cd). Чужое незакоммиченное (tails) в коммиты не попало: 8+3+3 файла == заявленным.

## БЛОКЕР (поимённо)

- B1 (bookkeeping, не код): `requirements_gate.py check --stage review --slice INITREPLY-L1D --candidate d87284c1` → **FAIL**: map-level `candidate_commit` = 0b7a0aca416a… (протух, не бампался несколько поездов), не совпадает с кандидатом. plan-стейдж EXIT 0 подтверждён (inventory=148, manual=79, errors=0). Минимум: бамп `candidate_commit` в plans/features/asap8-v6-3-live-correction/requirements-map.json на актуальный кандидат поезда + повтор `--stage review` EXIT 0. Код при этом не менялся — после EXIT 0 лейн считается одобренным по настоящему ревью без повторного цикла.

## Проверено независимо (факты)

1. **Контракт**: L1Plan.delivery/target_message_id/target_user_id; `reply_binding_requested()` = единственный путь к reply (action=reply И delivery=reply И target>0), normalize не бросает, мусор/bool/≤0 → без reply; Direct-путь игнорирует delivery-поля (grep `.delivery` — только delivery_hint; with_ids=False по умолчанию; corrective_r1/asap7 route-тесты зелёные).
2. **Транспорт**: `_initiative_reply_target`/`_initiative_ref_ids`/24h-хардкод удалены (grep — только комментарии); `_validate_plan_target` = только техпроверки §6 (чат/существование/tg-id/свежесть/адресат), без перепривязки; провал: standalone → fail-soft plain send, semantic addressee → cancel + `_f6_plan_next_check` (SendRecheck-семантика, вкл. 400 gone); замена 24ч на `limits.summary_window_hours` обоснована — это тот же источник окна планера (summary_memory.get_window_messages), флор 1ч задокументирован.
3. **Канон**: блок «ФОРМА УЧАСТИЯ» без приоритетов/квот/пропорций; молчание — полноценный исход; target по смысловой связи, не по порядку; Observer-повод = «можешь отклонить» (INITIATIVE_LINE + текст задачи); ключевые слова стимулов в каноне отсутствуют (анти-подгонка).
4. **Хеши воспроизведены независимым путём** (отдельный worktree c96f0e45 + sha256): PREV_1022 = 3022 симв / 5fdc90b3f114 == прод-канон 2.58.109 (a1d8bd62) байт-в-байт; фабрика c19d35a1c093 (parent) → 3507bd6f92eb (HEAD) == константе и factory_set_fingerprint(); diff фабрик-карт: changed = ровно 1 блок direct.base.l1_planner (5fdc90b3f114→ace6246bd360), added/removed=0; лестница (PREV_1022→новый канон) в prompt_migrations — легитимный обязательный шаг канон-процедуры ADR-1013-3 (вне WRITE_SCOPE, но без неё прод-значение PG-ключа не ведётся на контракт); трасса бампов в prompt_registry полна (…c19d35a1c093→3507bd6f92eb, метка l1-planner-l1d); direct-runtime-assembly.txt: 4264/ace6246bd360 подтверждён моим хешем.
5. **Тесты** (venv): test_asap8_initreply_binding (14) + test_direct_l1_l1d_contract (15) = 29 passed; related-селект `-k "initiative or … samples_fewshot"`: 806 collected → **806 passed / 0 failed** (воспроизведено; в 1-м прогоне из 3 был разовый флэйк test_handle_initiative_cancelled_by_recheck — вне изменённого пути, дважды зелёный). Кейс «addressee=None + source_refs → обычное сообщение» покрыт комбинацией case1 (source_refs+адресат игнорируются) + case7a (addressee=None, refs, провал цели → plain send без перепривязки).
6. **Офлайн-пробы**: артефакты существуют (verify_l1d.py, result_l1d_run3+retry, contexts_l1d); распределение chat1/reply2/react2/silent3 без приоритетов; анти-дефект-кейс (общий спор, 7 msg-id) — в сыром ответе delivery=chat, цели null, НО raw обрезан по max_tokens (parsed=false) — слабее остальных, компенсируется транспортными тестами (источник-рефсы не порождают reply). Прод-эндпоинт apinet.cloud недоступен с дев-машины — воспроизвёл сам (ConnectTimeout), замена deepseek-v4.1-flash через OpenRouter задокументирована.
7. **Гигиена**: секрет-скан 3 диффов — 0 попаданий; react через существующий react_moai (сигнатура совпадает), анти-спам sent_stamps для reacted; ностальгия/heartbeat — тест байт-пути зелёный; force-Direct не задет.

## Неблокирующие замечания

- N1: kill-switch REACTION_MECHANICS_ENABLED=OFF → инициативная реакция уходит legacy-🗿 (reaction=None), а не честное молчание; совпадает с прецедентом Direct-пути, env-only, default ON. Зафиксировать в бэклоге.
- N2: дрейф счётчиков в документе: «12/17 тестов» фактически 14/15 (сумма 29 сходится); «manual=75» в evidence vs фактические 79 — поправить при следующей правке документа.
- N3: живое распределение форм после деплоя — owner-наблюдение (PET, не блокер).

Владелец evidence-артефактов: lane FIX-INITIATIVE-L1D. Проверки, использованные повторно: офлайн-пробы/артефакты (перепроверены содержимо), гейт plan (перепущен). Всё остальное — мои независимые прогоны.
