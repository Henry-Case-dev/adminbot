# SELF-DIAG-01 — D0 discovery

Источник требований: `plans/owner_inputs/2026-11-09-self-diag-01.md` (FINAL v2.0, в рабочем worktree отсутствует; проверен канонический файл `C:\Code\Python\adminbot\plans\owner_inputs\2026-11-09-self-diag-01.md`) и amendment `2026-11-09-self-diag-access-matrix.md`.

## 1. Checkup path today

- Единственный bare-триггер — regex `чекап`; кроме него сохранён prefixed путь через `command_registry.matches_group("checkup", body)` (`handlers/checkup.py:55-78`). Это расходится с FINAL-правилом «не расширять новые ключевые слова»: исторический prefixed путь надо сохранить/инвентаризировать до изменения.
- Handler проверяет DI/бот, master flag, извлекает `from_user.id`, обновляет cooldown и проверяет per-chat slot (`handlers/checkup.py:92-113`). При cooldown отвечает reply на исходное сообщение (`:107-111`); при недоступности логов отвечает dead-фразой (`:114-121`); при fallback сначала отправляет fallback-фразу (`:122-125`).
- Затем берёт per-chat concurrency permit; timeout отвечает busy-фразой (`handlers/checkup.py:126-137`). В permit выполняется typing context, затем `CheckupService.checkup(logs, used_fallback, chat_id=message.chat.id)` (`:139-145`), результат отправляется chunked reply (`:145`). Пустой LLM-ответ даёт reaction без текста, LLM error — error reply, прочая ошибка — logged exception + error reply (`:147-161`); permit освобождается в `finally` (`:162-163`).
- Prompt key/versioning: `resolve_prompt("prompts.checkup_system_prompt", CHECKUP_SYSTEM_PROMPT)` (`services/checkup_service.py:55-65`); fallback factory — `CHECKUP_SYSTEM_PROMPT` (`:12`, `:57`). `speech_owner_block(chat_id)` добавляется перед fallback notice (`:66-72`). Фактический prompt registry resolver имеет precedence `chat_value -> pg_value -> default/code`, effective text, source, revision и factory revision (`services/prompt_registry.py:3075-3103`, `:3138-3156`).
- LLM вызов находится в `CheckupService.checkup`: `self.llm.generate([system,user])` (`services/checkup_service.py:101-107`), после чего cleanup и outbound style policy для пользовательского пути (`:112-125`).

## 2. Log source today / Better Stack inventory

- `CheckupLogsFetcher` сейчас реализует каскад Better Stack SQL API → journalctl (`services/system_logs_fetcher.py:1-9`, `:94-111`). SQL credentials/config берутся из `settings` и hot config (`:50-75`), HTTP POST — `_fetch_sql()` (`:113-131`), SQL query body — configured query либо `SELECT dt, raw FROM remote({table}_logs) UNION ALL SELECT dt, raw FROM s3Cluster(primary, {table}_s3) WHERE _row_type = 1 ORDER BY dt DESC LIMIT {limit} FORMAT JSONEachRow` (`:24-29`, `:115-124`).
- Local fallback использует `asyncio.create_subprocess_shell(self._journalctl_cmd)` (`services/system_logs_fetcher.py:196-210`), то есть shell действительно используется. Точный default command задаётся `settings.CHECKUP_JOURNALCTL_CMD`; owner input фиксирует проверенное значение `journalctl -u admin_bot -n 300 --no-pager` (`plans/owner_inputs/2026-11-09-self-diag-01.md:187-189`). Fetcher фильтрует ERROR/WARNING/Traceback и берёт максимум 300 строк (`:228-238`).
- `CheckupLogsFetcher.fetch()` вызывается bare checkup (`handlers/checkup.py:114`) и get_bot_health (`services/tool_router.py:4743-4760`).
- Better Stack occurrences, классификация: `services/system_logs_fetcher.py:3-9,50-75,94-131` — **checkup-only** SQL reader; `config/settings.py:2246-2260` — **checkup-only** settings; `bot.py:567-576` — **checkup-only** DI/config wiring; `.env.example:375-383`, web catalog/UI refs `web/app.js:92,193` and related settings forms/tests — **checkup-only** configuration surface. `services/checkup_prompts.py:43,64,121,166` — **checkup-only** prompt text/notice, not transport. `bot.py:15-16,168-240,1494,1591-1594` and `services/betterstack_handler.py` — **used-elsewhere** global logging/observability transport; `LOGTAIL_SOURCE_TOKEN`/`BETTERSTACK_HOST` in `.env.example:56-69` and `requirements.txt:15` likewise **used-elsewhere**. `scripts/betterstack_host_token_probe.py` and `tests/test_betterstack_handler.py` are **used-elsewhere** probe/tests for global ingest. Поэтому D1 должен удалять только checkup SQL/config/UI, не global handler/ingest.

## 3. Tool surface

- `ToolRouter.dispatch()` создаёт фиксированную registry table и dispatches only known names, returning string error rather than raising (`services/tool_router.py:1361-1404`); current entries include `get_bot_health` and `read_source_code` (`:1377`, `:1391`).
- `get_bot_health` повторяет fetcher → CheckupService, без cooldown, с checkup flag and service availability guards (`services/tool_router.py:4743-4767`). It does not pass `chat_id` into `checkup` (`:4758-4759`), so it takes the neutral/internal prompt path documented in `services/checkup_service.py:51-54`.
- Tool schemas register `get_bot_health` (`services/tool_schemas.py:361`) and `read_source_code` at the end (`:849-857`); source read has enabled gate (`:1002-1029`, `:1119-1145`).
- Tool loop lifecycle is bounded: max rounds 4, total calls 6, same call 2, metered calls 4 (`services/tool_loop.py:44-53`), plan max steps 6/replans 2 (`:110-111`), and actual dispatch occurs through router (`:705`, `:1057`).
- Capability registry `CapabilityState` carries status/reason/source, declared/tryable, last result and checked time (`services/capability_registry.py:96-142`); `get_bot_health` state is built from canonical schema presence and runtime gates (`:697-707`, broader resolver `:800-917`). Status vocabulary includes ready/unsupported/disabled/not_configured/temporarily_unavailable/quota_exhausted/unknown (`services/capability_registry.py:18-45`).

## 4. ACL / identity

- Existing role context is `roles.access_for(telegram_id, chat_id)`, combining global role slice and `chat_admins(chat_id, telegram_id)` DB grant (`services/roles.py:9-16`, `:140-220`). Role hierarchy is global_admin > local_admin > moderator > user (`:27-42`); chat grants are local_admin/moderator only for that chat (`:180-193`). DM owner is inferred by `chat_id == telegram_id` and DM scope (`:169-179`), not a Telegram API admin check.
- Existing permission layer already supports section/action/param/key permissions (`services/roles.py:44-64`, `:223-231`; `services/access.py:1-24`). Param matrix is `view_roles`/`edit_roles`, DB overrides plus chat overrides (`services/access.py:169-247`), with role domain user/moderator/local_admin and implicit global admin (`:135-153`). This can hold diagnostic categories as catalog keys/sections; no parallel ACL is needed.
- Numeric owner identity is consumed from authenticated Telegram `user.id` at API entry (`web/api/routes.py:346-374`, `web/api/access.py:159-184`), while the inspected settings search did not expose a dedicated owner-ID declaration. The existing global admin mapping is the role/cache source (`services/roles.py:159-166`), so D2 must locate and document the configured numeric owner source before protected readback.
- No `getChatMember` call was found in the repository search. Existing `ChatMemberUpdated` handlers observe join/leave/member events (`bot.py:949-956`, `handlers/chat_lifecycle.py:77-105,170-199`) but do not verify an arbitrary requester’s current Telegram admin status. Thus owner amendment’s online `getChatMember(chat_id,user_id)` requirement is not currently met.
- Web access matrix is already real and persistent: `/api/access` manages chat roles and `/api/access/param_permissions` manages global matrices, with PUT/DELETE and chat-scoped overrides (`web/api/access.py:319-456`). Config routes use `access_for`, `can_access_chat`, effective matrix, and `can_view_param`/`can_edit_param` (`web/api/routes.py:477-540`, `:713-804`). Diagnostic categories can be added to this surface, but tool/API/Telegram enforcement is currently not unified by these routes.

## 5. Prompt readback feasibility

- Effective prompt is returned by `prompt_registry.effective_prompt()` with chat layer first, then global, then factory/code fallback; it returns effective text, source and revisions (`services/prompt_registry.py:3075-3103`, `:3138-3156`). Existing checkup caller obtains the prompt through `resolve_prompt` (`services/checkup_service.py:55-65`), while `capability_registry` also resolves prompt values through registry with hot/chat inputs (`services/capability_registry.py:1017-1032`).
- Inheritance is explicit: absent chat/global value selects default/code; document fields fall back to factory field (`services/prompt_registry.py:3095-3114`). This is sufficient to distinguish chat override/global inherited/factory metadata without a second store.
- Existing delivery sender is available: checkup sends via `_reply` and `send_chunked_reply` (`handlers/checkup.py:38-42,107-110,145-146`). A protected readback can bypass LLM by resolving/authorizing server-side and using the same sender, but current code has no such endpoint/resource and no Telegram getChatMember gate.

## 6. Observability reuse

- Checkup already logs trigger, fallback, busy, LLM success/latency, empty/error and report sent (`handlers/checkup.py:103,117-159`; `services/checkup_service.py:108-110`). Tool loop has trace/degraded lifecycle and tool-call start/dispatch points (`services/tool_loop.py:1049-1060`, `:1126-1127`).
- Existing `memory_health.collect_metrics` supplies DB/memory/disk/WAL/RSS counters and returns empty on failure (`services/memory_health.py:44-57`, `:159-190`, `:192-195`); CheckupService inserts it into `<memory_health>` (`services/checkup_service.py:79-100`). This is reusable, not a new counter store.
- `APP_VERSION` is available at `config/settings.py:3530`; `/healthz` exposes it (`web/app.py:345-355`), and status/debug use it (`services/status_service.py:32,78`, `services/debug_config.py:26,245`). A deployed SHA is not exposed by the inspected core settings/status paths; it must be added/located in D4 from deployment metadata. Existing event/provenance plumbing is referenced by owner requirements but no single diagnostic bundle currently exists.

## 7. Conflicts and independent stages

- MEMORY-08 is represented by `plans/features/memory-cognitive-02/contracts.md`, `search-read-model.md`, `audit-head.md` and requirements map. Its changed memory/read-model surface can overlap `services/memory_health.py` and evidence/analytics contracts; D0/D1 must not rewrite memory counters or its files. D3 memory probes should be serialized after MEMORY-08 integration where they touch the same metrics contract.
- VMQ-ONTO-01 exists as `plans/features/vmq-onto-01/` and is queue/ontology work. No direct code dependency was found in the requested diagnostic files; it does not block D1, but shared tool/evidence/analytics files must not be co-owned.
- Independent now: D0 audit (read-only), and the narrowly scoped D1 portable local log backend + checkup-only Better Stack removal. D2 policy depends on D0 identity findings; D3/D4 can parallelize after evidence contracts, with D3 serialized around memory_health; D5 depends on D2; D6 depends on D2/D3/D4 contracts; D7 follows all.

## 8. D1 verdict

**D1 is an independent P0 corrective runnable now.** Exact initial write scope: `services/system_logs_fetcher.py` (replace SQL-first and `create_subprocess_shell` with portable local backend and fixed argv/API), `config/settings.py` checkup-only fields, `bot.py` checkup DI wiring only, checkup config catalog/API/UI files discovered from the inventory (`web/app.js`, relevant `web/api/routes.py` config metadata), and focused checkup fetcher/handler tests. Do not modify `services/betterstack_handler.py`, global logging wiring (`bot.py:15-240,1494,1591-1594`), or unrelated Better Stack probes.

Risk: R1 portability/false-log source and R1 regression of bare checkup; R2 if settings/catalog/UI removal overlaps shared config files. Acceptance evidence: direct test with `create_subprocess_exec`/adapter and wrong old unit rejected; systemd/container/standalone or honest unavailable cases; checkup handler preserves cooldown/reply/reaction/busy; grep/config inventory proves zero checkup Better Stack references; runtime network trace proves zero checkup requests to Better Stack while global logging remains intact; real-vps log provenance evidence. Rollback: revert D1 candidate; preserve existing checkup until local backend is proven.

## 9. D0–D7 stage plan / ownership / serialization

| Stage | Owner | Scope | Serialized files / join condition |
|---|---|---|---|
| D0 | Architect/PM | this discovery, HEAD/current task/VPS/ACL/prompt/log inventory | read-only; no product writes |
| D1 | Builder + Reviewer | portable local logs, checkup-only Better Stack removal | serialize `services/system_logs_fetcher.py`, checkup settings/catalog/UI wiring; Reviewer after tests |
| D2 | Architect/Builder | resource classes, chat scope, backend/tool/output ACL | serialize `services/roles.py`, `services/access.py`, `web/api/access.py`, shared policy files |
| D3 | Builder | typed runtime probes and common evidence collector | serialize `services/memory_health.py` and collector/registry contracts; join MEMORY-08 |
| D4 | Builder | deployed identity, SHA, source correlation | serialize `services/source_reader.py` and deployment identity/status files |
| D5 | Builder + Security Reviewer | prompt_readback, getChatMember, direct delivery/redaction | serialize prompt registry/readback, Telegram auth and sender path; requires D2 |
| D6 | Builder/UI + Reviewer | dual-path output, status/analytics/admin matrix | serialize `services/checkup_service.py`, `tool_router.py`, `tool_schemas.py`, `tool_loop.py`, web status/config/access files |
| D7 | Reviewer/DevOps | AC-01..24, golden set, live checks, default-ON release | candidate-wide serialization; no release before D7 evidence |

Queue position: SELF-DIAG-01 is queued after the currently active MEMORY-08 and VMQ-ONTO-01 work; only the explicitly independent D1 corrective may run without interrupting those lanes.

SELF-DIAG READY FOR PM LEDGER
1. D0 подтвердил существующий путь «чекап»: cooldown, reply, reaction, busy и LLM сохранены.
2. Текущий CheckupService резолвит prompt через единый registry, без второго промпта.
3. Логи сейчас идут сначала через Better Stack SQL, затем через shell journalctl.
4. `create_subprocess_shell` и старый unit создают подтверждённый portability-риск.
5. Better Stack разделён на checkup-only и глобальный observability; глобальный handler трогать нельзя.
6. `get_bot_health` использует тот же fetcher и сервис, но ACL инструмента пока не един.
7. Матрица ролей/параметров уже поддерживает view/edit и chat overrides.
8. Онлайн-проверки Telegram `getChatMember` в коде не обнаружено; это обязательный пробел D2/D5.
9. D1 можно запускать независимо, а D2–D7 должны идти по зависимостям и сериализации файлов.
10. Следующее действие PM: занести артефакт и назначить D1 как отдельную корректирующую работу.

## D0 closure addendum (2026-11-13)

Назначение: закрыть reviewer-замечания к `SD1-D0-01`, `SD1-D0-04`, `SD1-D0-05` без изменения исходного текста discovery и без нового аудита. Это дополнение к существующему D0-артефакту; D0 approval не заявляется, повторная проверка — за Reviewer.

### A. `SD1-D0-01` — HEAD, production mapping и D6-кандидат

**Что было верно на момент исходного D0 (2026-11-09).** Discovery писался по тогдашнему дереву; коммит, впервые зафиксировавший этот артефакт, — `5e0fbc280929b96ddbc730f1f9e1382998531cc5` (2026-11-09). Ориентиром production в owner-входе §20 был `release/2.58.168`, а не сегодняшний релиз. На тот момент в коде не было `getChatMember`, а checkup-транспорт был Better Stack SQL-first (см. §2/§4 выше).

**Текущее состояние на момент этой записи.**

- `git rev-parse HEAD` = `1e22fa17adedd35943d04c603a53e49680cbf82e` — это docs/PM-линия (коммиты привязки карты и state). Она **не содержит** production-коммит `25876167` (проверено `git merge-base --is-ancestor 25876167 HEAD` → not ancestor). Поэтому HEAD не используется как источник кода/прода: факты кода берутся с production- и train-коммитов.
- **Production mapping:** `2587616759de31283585ffc105c91e7193c2e89e` = **2.58.197** (D1 evidence и `deployment_2_58_197` карты).
- **D6 release candidate:** `16fa04e77c56db44c23cb5c8a9386f6cfd756628`, база `722ccfc5`, ветка `self-diag/d6`; `25876167` является его предком (проверено `git merge-base --is-ancestor`). То есть D6-трейн содержит production-код 2.58.197, а не заменяет его другой базой.

**Карта зависимостей (актуальная, с различением D0-time и current):**

| Компонент | Факт на D0 (2026-11-09, `5e0fbc28`) | Текущий факт (production `25876167` / D6 `16fa04e7`) | Где подтверждено |
|---|---|---|---|
| MEMORY-08 / `memory-cognitive-02` | Отдельный feature-пакет; общий `memory_health`/read-model; D0/D1 не переписывают его файлы | `epic-memory-cognitive-02` — `PENDING`, queue 20, P2 (`progress_scope`); D6-трейн добавляет `services/memory_health.py` (+121) как diagnostic probe | `plans/features/memory-cognitive-02/*`, `plans/progress_scope.json`, `git diff 722ccfc5..16fa04e7 -- services/memory_health.py` |
| VMQ-ONTO-01 | Отдельный queue/ontology-пакет; прямой зависимости в diagnostic-файлах не найдено | `vmq-onto-01` — `PENDING`, queue 4, P0; `fc-trust-01` заблокирован `["vmq-onto-01","self-diag-01"]` | `plans/progress_scope.json`, §7 выше |
| Observability | Существующий `mca_events`; чек-ап уже писал trigger/fallback/busy/LLM | Тот же `mca_events`; D6-аналитика читает его, второго стора нет | `services/mca_events*`, D6 binding §1.4 |
| Capability registry | `services/capability_registry.py`, статусы/причины | Не менялся в D6-трейне (diff пуст); используется D4/D6 как единственный реестр | `git diff 722ccfc5..16fa04e7 -- services/capability_registry.py` |
| Prompt versioning | `prompt_registry` + `prompt_factory` (label/seal, история) | Не менялся в D6-трейне (diff пуст); D5 readback/D6 читают тот же registry | `git diff 722ccfc5..16fa04e7 -- services/prompt_registry.py` |

**Явное различие:** на D0 production-ориентиром был `release/2.58.168` (owner §20), `getChatMember` отсутствовал, Better Stack был SQL-first, factory prompt имел другой hash (см. B). Сейчас production — 2.58.197 (`25876167`), `getChatMember` реализован, Better Stack удалён из checkup-транспорта, factory prompt зафиксирован на `b0c70f97…`, а D6-кандидат `16fa04e7` содержит production-код и является релизным трейном.

### B. `SD1-D0-04` — immutable checkup prompt baseline и инвентарь

**Метод.** Текст `CHECKUP_SYSTEM_PROMPT` собран точным импортом `services/checkup_prompts.py` соответствующего коммита вместе с `services/prompt_style_blocks.py` того же коммита; hash — sha256 по UTF-8 байтам. Формула текста: `_CHECKUP_P0_TARGET_BASE + STYLE_BLOCKS_SUFFIX` (`services/checkup_prompts.py`).

| Baseline | Commit | Blob `checkup_prompts.py` | Длина (символы / UTF-8 байты) | sha256 текста | Factory label / seal |
|---|---|---|---|---|---|
| D0 discovery (2026-11-09) | `5e0fbc280929b96ddbc730f1f9e1382998531cc5` | `cf74dd036cc3` | 3210 / 5736 | `0f5fb7b8d25c941993a22551475e776a08f5b3594fd63f32741ab4d4367ad5df` | label `checkup-p0-24-10`; словаря seals в этом коммите ещё не было |
| Production 2.58.197 | `2587616759de31283585ffc105c91e7193c2e89e` | `bb3c2c79545b` | 3030 / 5406 | `b0c70f974e0e7a78da3cb3f9c907a85673431de169d0e25c607d954858b4dfdf` | label `checkup-p0-24-10`; seal `b0c70f974e0e` = sha12(factory text) |
| D6 train | `16fa04e77c56db44c23cb5c8a9386f6cfd756628` | `bb3c2c79545b` | 3030 / 5406 | `b0c70f974e0e7a78da3cb3f9c907a85673431de169d0e25c607d954858b4dfdf` | label `checkup-p0-24-10`; seal `b0c70f974e0e`; `git diff 25876167..16fa04e7` по prompt-файлам пуст |

**Revision/history source.** Активная ревизия — `act:<sha12>` в `prompt_registry` (PG); история/откат ведутся `prompt_factory` и журналом провенанса `character.prompt_history` (`PROVENANCE_DOC_KEY`). Фабричная ревизия выводится из метки `checkup-p0-24-10` (`sealed_factory_revision` → `fac:<sha12(label)>`). Точная активная ревизия и возможные chat/global overrides в production по репозиторию не восстанавливаются — prod DB в этом обновлении не читалась (честная граница, не «проверено»).

**Что менялось между D0 и production.** Файлы `checkup_prompts.py`/`prompt_style_blocks.py` менялись в диапазоне `5e0fbc28..25876167` (в т.ч. `f71dfb56` — D1, честная fallback-приписка; и изменения style blocks). Поэтому D0-time hash `0f5fb7b8…` отличается от production `b0c70f97…`. При этом **production и D6-трейн байт-идентичны** (`b0c70f97…`), то есть сам релизный поезд промпт не менял. По-байтовая атрибуция каждого изменения по коммитам не восстанавливалась.

**Инвентарь Better Stack / Bot API / ACL (explicit):**

| Область | D0 time (2026-11-09) | Current (production `25876167` / train `16fa04e7`) | Где |
|---|---|---|---|
| Better Stack — checkup transport | SQL-first `services/system_logs_fetcher.py`; настройки/UI checkup | Better Stack в `services/system_logs_fetcher.py` и `config/settings.py` отсутствует (grep 0); локальный journald backend | `git grep -i betterstack 25876167 -- services/system_logs_fetcher.py config/settings.py`; D1 evidence |
| Better Stack — global logging | `services/betterstack_handler.py`, `bot.py` — used elsewhere | Остаётся used elsewhere; не checkup | `git grep -l -i betterstack 25876167 -- "*.py"` |
| Упоминание Better Stack в тексте промпта | `services/checkup_prompts.py` содержит слово «Betterstack» | Остаётся текстом промпта, не транспортом; D1 inventory помечает keep | `d1-inventory-25876167.md` (L51/L72) |
| Bot API `getChatMember` | В коде отсутствовал | `services/telegram_role_check.py` — единственный источник истины `chat_admin`; используется `diagnostic_policy` | `git grep getChatMember 25876167 -- services/telegram_role_check.py` |
| ACL | `roles.py`, `access.py`, param matrix, `web/api/access.py` | То же + `diagnostic_policy` data classes/capabilities + D6 admin UI; chat overrides | §4 выше; D2/D6 evidence |

### C. `SD1-D0-05` — §19 applied-rules matrix

| Правило §19 | Applied | Evidence / where | Exception |
|---|---|---|---|
| Better Stack полностью удаляется **только из checkup**; работающий direct local backend остаётся | **Applied** | D1 removal; на `25876167`/`16fa04e7` в checkup fetcher/settings Better Stack нет; journald backend | Глобальный logging (`bot.py`, `services/betterstack_handler.py`) остаётся used-elsewhere; слово «Betterstack» в тексте промпта — не транспорт |
| Публична техническая диагностика; защищены prompt contents, secret values, чужие chat data | **Applied** | `services/diagnostic_policy.py` (PUBLIC_TECH), `/api/status/self-diagnosis` RBAC; D2 2.58.188 | Prompt contents/secret values/other-chat data защищены |
| Подтверждённый admin/owner по своему запросу может раскрыть prompt **прямо в группе**; креды нельзя нигде | **Applied** | D5 `prompt_readback`, D6 регистрация + `TOOL_ACTIONS prompt_readback=view`, group delivery без DM, только свой chat; `TestPromptReadbackAllowedDispatch` | Credential values не выдаются; живая AC-12/AC-13 — postdeploy |
| Единственный новый explicit keyword — `«чекап»`; без расширения ручных триггеров | **Applied** | `handlers/checkup.py` / `command_registry`; SEM-01/AC-05; новых синонимов нет | Исторически зарегистрированные алиасы только инвентаризуются (SEM-12), новых не добавляется |
| Заводские промпты в публичном GitHub уже публичны; не давать ложных гарантий | **Applied** | D2-16 `factory_public` vs `active_value`, D5 классификация prompt readback; factory text в репозитории | Эффективные/chat prompts защищаются; «100% секретности» не заявляется |
| Админ читает prompt в своём scope; не становится владельцем других чатов/системы | **Applied** | `diagnostic_policy` scope=current_chat; D2/D5 tests | Только свой chat; credential values запрещены |
| Всегда попытка git metadata и фактическая ревизия; глубокий source/diff — при evidence или явном запросе | **Applied (unit)** | D4-B `recent_commits`/identity; D6 checkup reads identity+commit metadata; D6-08 | Живая попытка на VPS — D4-09 postdeploy |
| Только typed probes/наблюдаемые данные; без arbitrary shell/SSH/SQL и мутаций | **Applied** | D3 `runtime_probes` (typed probes, fixed argv, `DENIED_ARGUMENT_KEYS`); D3 review | Нет |

### D. Честные границы этого дополнения

1. Production DB/SSH не читались: активная prompt-ревизия, фактические chat/global overrides и история в PG по репозиторию не восстанавливаются; подтверждён только factory baseline.
2. Точная по-байтовая атрибуция изменений prompt между `5e0fbc28` и `25876167` не восстанавливалась; зафиксировано только, что production и D6-трейн байт-идентичны.
3. `HEAD` `1e22fa17` — docs/PM-линия, не содержащая `25876167`; все code/prod-факты выше взяты с `25876167`/`16fa04e7`, а не с HEAD.
4. D0 approval не заявляется; `SD1-D0-01/04/05` остаются на повторную проверку Reviewer.
