# A10 `agentic-verification-round1026` — Evidence (Builder, T-3710…T-3725)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 5 (продолжение) — A10 (ПОСЛЕДНЯЯ фича Эпика 3).
- **Тип:** verification (gate), **read-only**; product-код не пишется; A0–A9 не переписываются; тесты не дублируются.
- **Risk:** **R1** (финал предварительный; финал — Reviewer по фактическому diff). **`threat-failure-analysis.md` — `NOT_APPLICABLE`** (D8; read-only, без рантайма/DDL/каталога). Артефакт не создаётся.
- **Baseline anchor:** HEAD **`e8646af2bcaa79b55cadda756d0e8cc7789fe24f`** + UNCOMMITTED epic-release дерево A2–A9 (не трогалось/не коммитилось). A10 построен поверх; **0 коммитов, 0 тегов, без bump**.
- **Release policy:** **EPIC_ONLY** → deploy A10 **`epic deployment not applicable`** (D2); @DevOps внутри A10 не вызывается.
- **APP_VERSION:** **2.58.30** (без bump).
- **Feature dir:** `plans/features/agentic-verification-round1026/`.
- **Spec:** `spec.md` (Step 2 T-3708; 51 REQ → 54 SC, 12 инвариантов) · **ADR:** `adr-1026-23-verification-gate.md` (D1–D10, binding).
- **Приёмочный отчёт (D3):** `plans/reports/round1026_a10_acceptance.md`.

## Изменённые/созданные файлы A10 (read-only периметр, D9)

- `plans/features/agentic-verification-round1026/evidence.md` (**этот файл**, new).
- `plans/reports/round1026_a10_acceptance.md` (**new**, приёмочный отчёт D3).
- `plans/features/agentic-verification-round1026/tasks.md` — статусы T-3710…T-3725 → `[x]` (T-3726+ оставлены `[ ]`).

> **Product-код, DDL, каталог, `config/settings.py`, `web/**`, `services/**`, `bot.py`, `current_task.md`, машинный блок — не менялись** (см. «D5 confirmation»). A0–A9-артефакты — только чтение.

## T-3710…T-3725 — статус и evidence

- [x] **T-3710 [§52 п.1/2/8/18/23 — image-контур A3 (+A4)]** — evidence: `tests/test_unified_image_request_round1026.py` (`TestDirectPath`, `TestToolPath`, `TestAlreadyHandled::test_loop_double_trigger_is_one_generation` / `test_skipped_without_regeneration`, `TestRealErrorPropagation::test_generator_reason_is_surfaced`, `TestR17Logs`); §85; A3 archive `unified-image-request-round1026/{evidence.md,image-diagnostics.md}` (HY-01/02/06); A0 `#root-cause`. Вердикты: #1/#2/#18 PASS+PENDING OWNER; #8/#23 PASS. REQ-A10-01/-02/-08/-18/-23.
- [x] **T-3711 [§52 п.3/4/5/11/12 — память/досье/идентичность A4+A6]** — evidence: `tests/test_image_context_memory_round1026.py::TestCorroborationGateD13` (`test_person_marker_resolves_declension_samurai`, `test_g2_pass_then_two_same_name_ambiguous`, `test_g2_negative_unknown_person`, `test_cycle2_repros_no_person_intent`), `TestPromptAssembly`, `TestSection37`; `tests/test_memory_lookup_round1026.py` (`TestLazyRag`, `TestCaps`, purpose-routing); §87/§88; A4 archive `evidence.md` cycles 3/4. #3/#5/#11/#12 PASS; #4 PASS+PENDING OWNER. REQ-A10-03/-04/-05/-11/-12.
- [x] **T-3712 [§52 п.6/7/9/15 — лимиты/идемпотентность/параллельность A5 + A2]** — evidence: `tests/test_image_daily_limit_round1026.py` (`TestA1HappyPath::test_reserve_commit_once`, `TestA2Race::test_two_concurrent_reserves_exactly_one`, `TestA4Idempotency::test_same_key_no_double_spend`/`test_replay_denied_returns_prior_outcome`, `TestA3DenyRelease`, `TestA6Timezone`); `tests/test_tool_chains_round1026.py` лимиты (`test_total_call_cap_six`, `test_metered_call_limit_four`); §86 + §84 cap 6. #6/#7/#9/#15 PASS. REQ-A10-06/-07/-09/-15.
- [x] **T-3713 [§52 п.10/13/14 — URL/цепочки/аргументы A2 (+A6)]** — evidence: `tests/test_tool_chains_round1026.py::TestFetchArticle::*`, `test_resolve_context_url_*`, `test_uses_resolved_url_from_context`, `TestEnvelope::test_structured_error_does_not_kill_llm`/`test_structured_error_from_json_status`/`test_adversarial_mixed_errors`, `test_no_asyncio_gather_in_chain_sources`; `tests/test_memory_lookup_round1026.py` invalid-args; §84/§87; A2 archive `tool-chains-round1026/evidence.md` §1/§4. #13/#14 PASS; #10 PASS+PENDING OWNER (live URL). REQ-A10-10/-13/-14.
- [x] **T-3714 [§52 п.16/17/19/20/21 — реакция/молчание/адресация A7+A8]** — evidence: `tests/test_decision_making_round1026.py` (`test_laughter_reacts`, `test_short_real_question_replies`, `test_explicit_request_replies`, `test_not_addressed_silent`, `test_acknowledgement_silent`, `test_silence_never_eats_task`, `TestHandleOrder`); `tests/test_telegram_reactions_round1026.py` (`TestErrorTaxonomy`, `test_closed_enum_seven`, `TestCandidates::test_two_attempts_max`, `TestTargetCorrectness`, `TestReasonEmojiMap`); `tests/test_agentic_events_round1026.py::TestSilentNoVerbalizer`; §89/§90/§91. #16/#17/#19/#20/#21 PASS. REQ-A10-16/-17/-19/-20/-21.
- [x] **T-3715 [§52 п.22 — переключение глобальных/локальных настроек]** — evidence: `tests/test_image_daily_limit_round1026.py::TestA6Timezone::*` (chat TZ + limit change keeps used); `tests/test_decision_making_round1026.py` (`test_three_params_in_catalog`, `test_exactly_three_params_and_one_group`, `test_defaults_true`); scope-цепочка chat→global→env §86/§89 (A5/A7 тумблеры). #22 PASS + **PENDING OWNER VERIFICATION** (live toggle). REQ-A10-22.
- [x] **T-3716 [§53 п.1–9 — tool/image/досье/лимиты/цепочки]** — чек-лист §3 отчёта: критерии 1–9 все **YES** (evidence: A3 `image-diagnostics.md`/`TestRealErrorPropagation`; A3 единый runner; A6 43 теста; A4 D13; A3/A4 prompt-сборка; A5 server-side; A5 `TestA2Race`; A2 `result_for`; A1/A2 `test_tool_loop_is_tool_agnostic`). REQ-A10-25…-33; инвариант 2.
- [x] **T-3717 [§53 п.10–15 — честность фактчека/поведение/логи/регресс]** — чек-лист §3 отчёта: критерии 10–15 все **YES** (A2 honest failure; A7 laughter; A7 silent/Verbalizer + A9 `TestSilentNoVerbalizer`; A8 `TestTargetCorrectness`; A9 `TOOL_CALL_FAILED`+`review-T-3702`; полный pytest 9513/0 + `test_direct_chat` 159). REQ-A10-34…-39; инвариант 2.
- [x] **T-3718 [§54 п.1–6]** — регистр §4 отчёта: деливераблы 1–6 связаны с A0 `plans/docs/agentic-audit-round1026.md` (`#tool-map`) + `ARCHITECTURE.md` §82–§85 + §87/§88 + `tool_schemas.py`. Пробелов нет. REQ-A10-40…-45; инвариант 3.
- [x] **T-3719 [§54 п.7–12]** — регистр §4 отчёта: деливераблы 7–12 связаны с `ARCHITECTURE.md` §86–§91 + архивами A7/A8/A9 evidence + `test_direct_chat` 159/0. п.11 — примеры логов через A9 §91 + `review-T-3702`; п.12 — §54-12 (reuse T-3721). REQ-A10-46…-51; инвариант 3.
- [x] **T-3720 [эпик-wide прогон]** — см. «Harness numbers»: pytest 9513/0, JS 47/47, F8 --check 473, каталог 473/430/448/102/100/21, канон 12, SQLite v12, §104 AST-гейт 7, `git diff --check` 0, `APP_VERSION` 2.58.30. Инварианты 4, 8, 9.
- [x] **T-3721 [сохранность старых функций — §53 п.15 / §54 п.12]** — полный pytest **9513/0** (Δ 0 к baseline) + `tests/test_direct_chat.py` **159 passed** + A0–A9 регресс зелёный; явное сравнение с baseline. REQ-A10-39/-51; инварианты 2, 4, 8.
- [x] **T-3722 [регистр watch-items]** — §7 отчёта: 11 групп, CLOSE/PASS-THROUGH/PENDING без «тихого» закрытия. Инвариант 7.
- [x] **T-3723 [регистр owner-гейтов]** — §8 отчёта: 6 PENDING OWNER VERIFICATION, non-blocking, не закрыты. Инвариант 6.
- [x] **T-3724 [приёмочный отчёт A10]** — `plans/reports/round1026_a10_acceptance.md` (форма §7.1 D3): provenance, §52 23/23, §53 15/15, §54 12/12, epic-wide, дефекты, watch-register, owner-register, «НЕ принято», вердикт. REQ-A10-24; инварианты 5, 10, 11.
- [x] **T-3725 [честность авто vs live + «один тест ≠ подтверждение»]** — §2 (multi-source на каждую строку), §8/§9 («Chromium/headless ≠ Telegram WebView/прод»; 6 live-гейтов PENDING). Инварианты 6, 11.

## Harness numbers (T-3720, фактические, 25.09.2026)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9513 passed / 0 failed** (156.04s; 1 starlette-deprecation warning) |
| JS | `node tests/js/<each>.js` (47 файлов) | **PASS=47 / FAIL=0** |
| F8 registry | `python tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 473 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны** |
| Каталог | direct recompute | **REGISTRY 473 · Settings 430 · categorized 448 · GROUPS 102 · _TAB_BY_GROUP 100 · TAB_RULES 21** |
| Канон | `len(TOOL_CALLING_TOOLS)` | **12** |
| SQLite | `pytest tests/test_database.py -q` | **98 passed** (`user_version == 12`) |
| §104 AST-гейт | `pytest tests/test_unified_image_request_round1026.py::TestBoundsA3 -q` | **7 passed** |
| `git diff --check` | — | **exit 0** (LF→CRLF informational only) |
| `APP_VERSION` | `config/settings.py` | **2.58.30** (без bump) |
| Старые функции | `pytest tests/test_direct_chat.py -q` | **159 passed** |
| Spot A5 race | `test_two_concurrent_reserves_exactly_one` | PASSED |
| Spot A7 handle-order | `TestHandleOrder::test_await_count_two_on_tool_path` | PASSED |
| Spot A9 events | `TestAgenticGraphStages::test_nine_stage_kind_mapping` | PASSED |
| Spot A8 reactions | `TestCandidates::test_two_attempts_max` | PASSED |
| Комбинированный набор | 6 suites | **322 passed** |

> **Δ pytest = 0** (baseline 9513/0 → 9513/0): A10 **не добавляет** тестов (read-only, тесты не дублируются).
> Известный флейк `tests/test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener` в этом прогоне **не воспроизвёлся** (0 failed); watch-item группа 11, non-blocker.

## 12 приёмочных инвариантов — статус

1. 23 сценария §52 с evidence-ref, ни один не закрыт одним тестом — **OK** (23/23 multi-source; закрывающее правило `:5803–5804`).
2. 15 критериев §53 со статусом — **OK** (15/15 YES; эпик не объявлен завершённым).
3. 12 результатов §54 связаны с артефактами — **OK** (12/12; выдуманных нет).
4. Read-only по чужим артефактам — **OK** (A0–A9 не переписаны; правки A10 — только feature-папка + `plans/reports/**`).
5. Product-код в A10 не пишется — **OK** (D5; блокирующих дефектов нет; residual non-blocking задокументированы).
6. Внешние owner-гейты (1/2/4/10/18/22) — PENDING OWNER VERIFICATION, не закрыты — **OK**.
7. Watch-items (11 групп) трекаются — **OK** (CLOSE/PASS-THROUGH/PENDING; «тихого» закрытия нет).
8. Инварианты A0–A9 сохранены (Δ DDL=0, Δ каталога=0, канон 12, нет нового инструмента/3-го LLM, §104 no-go) — **OK**.
9. EPIC_ONLY (нет деплоя/тега/bump; @DevOps не вызван; вывод — вход агрегатного gate) — **OK**.
10. R17/R18 — **OK** (секреты/досье не в отчёте/логах; `current_task.md` immutable; теги/бэкапы/`stash` не тронуты).
11. Приёмка по живым артефактам — **OK** (реальные прогоны/числа/source-read; «Chromium ≠ Telegram WebView» зафиксировано).
12. A10 — последняя фича Эпика 3; handoff к агрегатному gate — **OK** (отчёт §10; T-3729).

## D5 confirmation (read-only)

- A10 не вносил изменений в `services/**`, `config/**`, `web/**`, `bot.py`, миграции/каталог. Единственные новые/изменённые пути A10 — под `plans/`:
  - `plans/features/agentic-verification-round1026/` (untracked; spec/tasks/adr/evidence);
  - `plans/reports/round1026_a10_acceptance.md` (new).
- Изменения product-кода, видимые в `git status`/`git diff --stat` (`services/**`, `config/settings.py`, `web/**`, `bot.py`; 18 файлов, 3694(+)/106(-)) относятся к **предсуществующему** незакоммиченному epic-release дереву A2–A9 (baseline) и A10 **не вносятся**.
- Проверки инвариантов: Δ DDL=0 (SQLite v12), Δ каталога=0 (`473/430/448/102/100/21`), канон 12, `APP_VERSION` 2.58.30, §104 AST-гейт 7 passed.
- `git diff --check` = 0.

## R17 / R18

- **R17:** отчёт/evidence содержат только id/enum/числа/имена инструментов/пути/`reason_code`; никаких секретов, ключей, приватного досье, сырых промптов/URL с секретами.
- **R18:** коммитов/тегов/веток не создавалось; `plans/current_task.md` и машинный блок `OPENCODE_WORKFLOW_STATE_V1` не изменялись; бэкапы/`stash@{0}` не удалялись.

## Границы (не scope-расширение)

A0–A9 — только чтение (архивы/spec/ADR/код не переписаны); фичевые тесты не дублированы (ссылки, не копии); новых библиотек/E2E-стендов нет; вторая система аналитики не создана; канон 12 без нового инструмента; нового LLM-вызова нет; §104 `generate_image` — no-go; Scanner не назначался; @DevOps не вызывался.

## Blockers

**Нет.** 2-attempt-rule не срабатывал. Готово к независимой проверке @Reviewer (T-3726).

## Статус готовности

**Ready for Reviewer T-3726: yes.** T-3710…T-3725 отмечены `[x]`; T-3726 (Reviewer) и T-3727…T-3729 (merge/handoff) оставлены `[ ]`. Эпик 3 **не** объявляется завершённым — вывод A10 = обязательный вход агрегатного Reviewer release gate.
