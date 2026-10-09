# F1 — Direct L1 Planner core (Wave 2, ASAP 7)

- Дата: 2026-10-09. База: master `e6670b0`. Параллельная F6 не тронута (cover-файлы/её блок settings — чужие регионы).
- Исполняемый контракт: `architecture.md` §1.1–§1.9, freeze §5.2 (region 1900–3100 + sandwich :347); audit-direct.md D-1/D-2/D-3; current_task §2/§3/§15/§22/§23.

## 1. Новый call graph (primary path, `flags.direct_l1_enabled=ON`)

```text
пре-гейты throttle/CB/lock/dedup/correction/style/stats/dig/image — БЕЗ изменений
  → Phase P (дет.): _resolve_direct_trigger :2049, demote-матрица :2107+, allowed-actions :2127 (новая ветка direct_l1_on)
  → evidence_bundle :2213
  → system_prompt/persona/style :2218-2269, lessons (capture `_lessons_block`) :2271-2296, speech (capture `_speech_block`) :2298-2316
  → lore/image флаги (подняты выше, :2325-2342 — чистые чтения конфига)
  → L1 PLANNER — 1 LLM call: typing_active → _plan_direct_l1 :2373 (svc :3398)
      контекст: _l1.build_l1_context (§1.5, кап limits.direct_l1_context_tokens=1600) — окно 20, reply, участники,
      bundle-срез, speech-коды, capability-список, force-факт, персона-кадр; sandwich НЕ получает
      ladder: dedicated slot (_l1.dedicated_generate) → main → parse; invalid JSON → ровно 1 repair → (None)
      usage-row step="l1_planner" (llm.generate автоматически; dedicated — usage_events.record вручную)
      agentic L1_PLAN (R17-whitelist) всегда; outage → WARNING + (None)
  → hard gates :2382-2489: force→reply (override), decision_off→reply, SILENT→allowed→🗿 (_execute_silent_ack:1712,
      конъюнкция неизменна)/тишина, low_confidence→demote в pre_action; REACT→reaction из ALLOWED_LLM_REACTIONS,
      invalid→det-реакция (demoted REACT) либо тишина (:2658-семантика)
  → ResponsePlan от L1 :2492-2496 (+ form override `explicit_form_override` ПОСЛЕ L1, §2.5); общий хвост:
      extent-блок/scrub/longform tokens/ExecutionGraph :2502-2524 — без правок
  → payload/temperature :2525-2531; tool_ctx :2546-2567
  → capability resolve: _l1_tool_subset :2674 (svc :3550) — CAPABILITY_TOOLS ∩ active_tools; reject →
      L1_CAPABILITY_REJECTED + честная пометка; needs_clarification → тула не запускаются
  → tool-фаза: _l1_tool_phase :2680 (svc :3576) — chat_with_tools с анонсом ТОЛЬКО resolved-подсета;
      дет. fast-path «2+ URL + сравнение» сохранён (build_tool_plan по подсету); resolved=∅ → None (без тула)
  → evidence packaging (дет., БЕЗ LLM): build_evidence_packet :3029 (direct_l1 — redact_secrets, статусы per tool, кап 4000)
  → L2 WRITER — 1 LLM call: _l2_write_answer :3044 (svc :3625) — Вербализатор-канал (compose_verbalizer_system +
      verbalize_validated + channel rules, переиспользование), user = plan-блок + speech/lessons + ПОЛНЫЙ
      Writer-контекст (user_blocks) + <Tool_Evidence>; media_delivered → Writer пропущен (media_writer_needed)
      L2 fail + clarification → ровно 1 fixed-фраза (fallback §1.9); L2 fail + tool final → финал tool-loop (fail-soft)
  → пост-обработка/numeric/freshness/delivery/ledger :3080+ — БЕЗ изменений
```

Топология reply-пути: **L1 (1) + [tools] + L2 (1) = ≤2 semantic LLM call** (§22 п.3).

## 2. Демонтировано из primary / сохранено в legacy (`DIRECT_L1_ENABLED=false` — байт-в-байт)

| Элемент | Было | Стало |
|---|---|---|
| Fused Decision Task | инжект :2480→(ныне ~2645), парсинг :2780+ | legacy-only: armed-ветки под `not direct_l1_on` (:2120/:2167/:2195/:2645), в L1-пути allowed-actions строит демо-матрица без армирования |
| Pre-tool REACT-вызов | :2415-2475 (ныне ~2573) | legacy-only (react_llm_pending не вооружается при L1 ON); роль забрал L1+§1.7-гейт |
| Гейт System2 | :2807-2818 (ныне ~2999) | `not direct_l1_on and ...` — демонтирован из primary; `_synthesize_direct_answer` (2 LLM) сохранён в legacy |
| Coordinator | :2773+ | `not direct_l1_on and coordinator_enabled()` |
| classify_request как semantic brain | :2315 | legacy/fallback-ветка (`_extent.fallback_plan` при L1 outage); `social_chat→compact` и «3 слова+?→micro» в primary не вызываются |
| 2-URL как primary multi-tool | :2529 | дет. fast-path по resolved-подсету; primary — capability-подсет |
| CLARIFY_MEDIA_TARGET как primary | :2489-2502 | legacy+fallback; primary — L1 needs_clarification → L2 формулирует один вопрос (≤1/turn конструктивно + флаг `_clarify_sent`) |
| `_SANDWICH_REMINDER` :355 | «отвечай коротко, по делу, …» | «отвечай на последний вопрос (<Current_Question>); людей называй именами…» — глобально (обе ветки), якорь и правила имён сохранены |

Новые файлы: `services/direct_l1.py` (L1Plan/нормализация/build_l1_context/ladder/evidence packet/fallback_plan/events),
`services/direct_capabilities.py` (таблица §1.4, resolve/schemas_for_notes/rejected-note).
Аддитивные регистры: `agentic_events.py` +2 события (33→35) c R17-whitelist; `chat_prompts.py` канон
`prompts.direct_l1_planner_system_prompt` (+PREV-слепок); `prompt_migrations.py` ступень нового ключа;
`config/settings.py` блок [F1-REGION]: env `DIRECT_L1_ENABLED` (default ON) + ClassVar дефолтов
context=1600/timeout=15/max_output=512 + **D-2 фикс**: объявлены `DIRECT_RESPONSE_PLAN_ENABLED`,
`DIRECT_TOOL_PLAN_ENABLED`, `DIRECT_RICH_DELIVERY_ENABLED`, `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS`
(аудит-проба `getattr → <ABSENT>` устранена, rollback-контракт жив). `response_extent.py`: +`explicit_form_override`
(«одним словом»→one_word/longform/compact), demote-докстринги; `direct_llm_react.py`: помечен legacy-only (не удалён).

## 3. Выход за WRITE_SCOPE (с обоснованием, всё аддитивное)

1. `services/agentic_events.py` — enum не расширишь из чужого файла; события §1.4/§1.5 обязаны жить в едином
   whitelist (иначе молча дропаются). +2 имени/поля, «capabilities» в _LIST_FIELDS, «input_chars/confidence» в _NUM_FIELDS.
2. Neighbor-тесты (7 файлов): `test_direct_chat.py`, `test_decision_making_round1026.py`,
   `test_tool_coordinator_round1026.py`, `test_direct_llm_decision_asap32.py`,
   `test_direct_decision_matrix_asap3.py`, `test_llm_react_asap31.py`, `test_tool_calling_round1015.py`,
   `test_outgoing_guard_round1022.py` — пин `DIRECT_L1_ENABLED=False` (autouse-фикстура/строка в _drive) +
   каталог-каунтеры (prompt_migrations/agentic/outgoing_guard) и 4 идентификатора sandwich-текста в
   test_direct_chat (позиционные ассерты, не cap-семантика). Их контракты = legacy-ветка; дефолт ON мандирован ТЗ.

## 4. Тесты

- NEW `tests/test_asap7_direct_l1.py` — 37 passed: Golden D1–D15 (D1 план из LLM по контексту, D2 one_word,
  D3 form-override, D4 hostile_rebuff semantic, D5 свобода L1, D6 banter, D7 web+history без 2 URL,
  D8 history-only, D9 media без clarification, D10 ровно 1 clarification и 0 тулов, D11 CONTRACT «коротко/по делу»
  отсутствуют в финальном промпте longform + L1 без sandwich, D12 max_output_tokens=4096, D13 outage→fallback
  без дубля + dedicated→main ladder, D14 invalid→1 repair→fallback + repair-success, D15 hallucinated→drop+event
  + statistics→∅/честная пометка); force→REPLY, SILENT→🗿/тишина/demote-off, react allowed/invalid, топология
  ровно 2 call, legacy-паритет (step="single", REACT-линия жива), юнит-нормализация/таблица tool-имён.
- REGRESSION(D-1): D11; REGRESSION(D-2): settings-проба; REGRESSION(D-3): pre-tool решение (D10/D9/D7 до тула).
- Соседи зелёные: 670 passed сводный прогон (direct_chat 161, decision_making+tool_coordinator 145,
  mca23-семейство, prompt_migrations, agentic_events, tool_calling, outgoing_guard, llm_react_asap31 и др.),
  плюс 695 passed по 19 периферийным файлам. `py_compile` всех затронутых — OK. Полный pytest не запускался (правило лейна).
- Smoke: L1_PLAN/L1_CAPABILITY_REJECTED реально эмитятся с whitelist-полями (structured-log проверен).

## 5. Остаточный риск / заметки

- L1-контекст делает второй `memory.get_window_messages` (лёгкий SELECT; рефактор `_build_user_content` за регионом
  freeze не делался). Silent/react-ходы в L1-режиме платят сборку system_prompt/персоны до LLM-вызова (read-only).
- Каталог-ключи `flags.direct_l1_*`/`limits.direct_l1_*`/`models.direct_l1_*` добавит F2 (код уже читает их
  hot-first с env-фолбэком; сейчас дефолты из ClassVar F1 — наследование main).
- LIVE_UNVERIFIED (owner gate, агентам недоступно): реальный прод-трафик L1 (качество планов, латентность 2 call) —
  после деплоя Wave 2/3; наблюдаемость готова (L1_PLAN + usage step="l1_planner").
