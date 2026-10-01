# review.md — `mca-05-episodes-stories` — Reviewer gate (независимое ревью + focused change-audit)

- **Feature-ID:** `mca-05-episodes-stories`
- **Risk-Level:** R2 (по spec §9; реальный diff расширенной поверхности не потребовал эскалации — primary-таблицы не тронуты, send-path отсутствует, legacy не удаляется)
- **Status: NEEDS FIXES** — 1 High (H-MCA05-1, необъявленное неисполнение требования §9.2 `:334` «поддерживает merge/split») + 1 Medium blocking (M-MCA05-1, продемонстрированное нарушение SC-14/§6: excluded-контент возвращается каналом через fallback-путь). *(Статус round 1; superseded round-2 вердиктом — см. секцию «Round 2» ниже: **APPROVED FOR RELEASE**.)*
- **Reviewed-Commit:** `0b1ae9cc831661cda319dbea40253295d251c662` (HEAD, совпадает с заявленным `0b1ae9c`) + незакоммиченный mca-05-скоуп (unstaged/untracked; staged = EMPTY, проверено).
- **Working-Tree-Hash:** `D98B3780CAEFD10AA7139F4F6F80083ED3C3BDC3194E77DDA08097F35773CCEA` (манифест: `plans/reports/mca05_wth_manifest_review.txt` — HEAD + SHA-256 `git diff HEAD` + per-file SHA-256 по 51 файлу скоупа (10 изменённых prod/доков + 4 новых + 26 тест-репинов + 4 JS-репина + 4 дока фичи) + явный список исключённого чужого WIP: `plans/docs/mca-round1027-arch-frames.md` (design-фаза), `plans/metrics.md`, `plans/workflow_state.md`, `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package*.json`).
- **Spec-Hash:** `8177CB0FF3FCEFE5168A82A52690DEB66B0DB8990DA2F047861E342EAE6E9EC0` (пересчитан Get-FileHash — совпал). ADR-1027-12: `2E7E110B1E2058366C6DD489DD02666988318227C6653F1251615DA0CBB4FC50` (совпал).
- **Git base и объём изменений:** base = HEAD `0b1ae9c` (= прод 2.58.41). Осмотрены: полный `git diff HEAD` по 10 изменённым файлам, 4 новых модуля целиком (mca_episodes.py 1981 строк, mca_episode_jobs.py 321, mca_episode_prompts.py 332, тест 1282 строки), диффы 26 py- и 4 JS-тест-репинов (все — только version-pin, кроме 3 семантических пинов mca-01/mca-04b/mca-17a, разобранных ниже). Чужой WIP вне скоупа не ревьюился и на вердикт не влияет (2 known bounds-failed воспроизведены и атрибутированы чужими путями — см. Counterexamples).

---

## 1. Checks performed (команда → факт → вывод)

| # | Обязательная проверка | Факт (независимо воспроизведено) | Вывод |
|---|---|---|---|
| 1 | Миграция v21 | `_migrate_episodes_stories_v21` (database.py:2276): 7 таблиц `IF NOT EXISTS` под `_table_exists`, 6 индексов, 5 override-колонок под `PRAGMA table_info`, `user_version=21`; реестр `migration_steps()` хвост = 21 (database.py:1662), **v22 свободна**; PG no-op (`pg_db.py`/`web/**`/`param_catalog.py` вне diff — Δ каталога = 0 подтверждён); тесты `test_v21_*` зелёные; rollback-compat: старый реестр (v20) на v21-БД не применяет шагов (version > current пусто) | ✅ PASS |
| 2 | Episode/Story модель | `state ∈ {open,closed,uncertain}` — закрытый набор (database.py:795), отдельное `task_status_ref` (`set_story_task_ref` не трогает state); две даты: `event_start/end` из `segment_times` (сообщения), `discovered_at` не перезаписывается ни `upsert_story` (UPDATE без discovered_at), ни `reextract_episode`; unknown → `EPISODE_UNKNOWN_OUTCOME` («исход неизвестен»)/`state='uncertain'` (assemble_stories:1884); origin uncertain есть в каноне промптов | ✅ PASS |
| 3 | Сегментация | `segment_messages`: сортировка `(timestamp, message_key)`, union-find reply-кластеров, гэпы 1800с/600с+участник; overlap-дедуп по стабильному ключу `chat:tg:<id>` + `segment_key` + 50%-overlap (`_find_overlap_duplicate`); A12-тесты (parallel topics / split clusters / continuation) зелёные | ✅ PASS (угол «те же участники без reply» — L4) |
| 4 | LLM-извлечение | Канон `episodes_extract-1`/`continuation_confirm-1`; офлайн-валидаторы (`validate_extract_payload`/`validate_confirm_payload`) — fixture-путь; claims без валидного ref → `unknown` + `dropped_claims`; unknown не становится фактом (тест `test_unknown_claim_not_becomes_fact`) | ✅ PASS |
| 5 | Продолжения | `is_continuation_candidate`: участники ∩ + сущность-токены ∩ + окно 1ч…90д; LLM-подтверждение до склейки, fail-closed (без LLM → только `candidate`); rejected остаётся раздельным (тесты A12 +/−) | ✅ PASS |
| 6 | Версии/merge/redirect/CAS | Версии монотонны (`expected_version`), снимки полные; CAS `StaleUpdateError` (тест); merge+redirect+скрытие источников в фасаде (тест); **split-операции НЕТ нигде** (grep: `story_split` только в словаре reason_code, эмиттеров 0) | ❌ **H-MCA05-1** |
| 7 | Legacy фасад | Ленивый `note_compiler_touch` (маппинг только по LLM-подтверждению), `mapping_status`, событие `story_legacy_unmapped`; `lore_stories` не тронуты — 0 удалённых строк в diff database.py, `get/list/upsert_lore_story` без изменений; `lore_stories`-данные не тронуты (тест) | ✅ PASS |
| 8 | Carry-over M-MCA07-2 | `build_local_context` в `_build_evidence_bundle` (direct_chat_service:3520+), гейт master, fail-open → `()`; инвариант пусто=`()` (тесты fill/off) | ✅ PASS |
| 9 | События витрины | Post-commit (emit только после успешного `write_transaction`; тест rollback→0 событий); payload несёт обе даты + episode_ids (тест); REASON_CODES +10 ровно по санкции (diff mca_events.py) | ✅ PASS |
| 10 | Kill-switches 4+2 | `KILL_SWITCHES` +4 записи default ON; гейты per-call env-only; под-гейты инертны при master OFF; OFF-паритет: master OFF → 0 записей/0 enqueue/канал на legacy (тесты); `MCA_EPISODES_BATCH_MAX_MESSAGES`<1→500 | ✅ PASS |
| 11 | Send-path | Независимый grep 3 новых модулей: `telegram_send|send_message|sendMessage|sendRichMessage|bot.send|api.telegram` → **0 совпадений**; telegram-импортов нет; тест-гейт зелёный | ✅ PASS |
| 12 | Прогоны | Полный pytest **10428 passed / 2 failed** (4:49) — анкер сойдётся; фича-набор **59 passed**; смежные (mca-01/03/04a/04b/07/13/14/17a + database + JS) **431 passed**; JS **36 passed**; F8-реестр **29 passed**; каталог Δ=0; `git diff --check` с `cr-at-eol` exit=0 (дефолтный флагует `\r` — до-существующее свойство смешанных CRLF/LF-файлов репо, см. L5) | ✅ PASS |
| 13 | 7 отклонений Builder | Оценены по одному — см. §4 | см. §4 |
| 14 | Staging-перечень | Составлен — см. §6 | ✅ |

## 2. Requirement/evidence coverage

- Цепочка `ТЗ §9.1/§9.2/§8.1/§11.2/§17/§18/§19(A11–A13)/§20 → spec (REQ/SC) → tasks T-4244…T-4272 → diff → тесты/evidence` сверена; трассировка spec §2 ↔ tasks §8 — 1:1 (спот-проверка REQ→SC→T на MCA05-R1/R2/R3).
- Первоисточник §9.1/§9.2/§8.1/A11–A13 прочитан дословно (строки 302–334, 892–894, 210–226) — расхождений трассировки не найдено.
- `current_task.md` не изменялся (отсутствует в `git status`).
- Память (OpenViking, 1 ограниченный запрос): конфликтов с артефактами нет; заметка «v21 зарезервирована» за mca-04b легитимно растворена санкцией ADR-1027-12 D2/рамка §1.2.6 (mca-04b финализирован на v20).
- Все `[x]` в tasks.md (T-4249…T-4270, T-4272) имеют реальную реализацию и/или evidence; гейты T-4271 (merge) и деплой корректно не отмечены.

## 3. Focused audit coverage / Counterexamples checked

- **Контрпример 1 (воспроизведён кодом, temp-БД):** excluded-история с mapped-legacy двойником → фасад возвращает 0 строк, но `_episode_candidates` возвращает 1 кандидата (preview='ремонт') через fallback `list_lore_stories` на пустом результате фасада → **M-MCA05-1**. Fallback на пустой ответ — не «fail-open» (он санкционирован только на ошибку/гейт-OFF), а дефект различения состояний.
- **Контрпример 2:** no-op rebuild — `test_rebuild_creates_new_version_once` зелёный; но unchanged-детектор сравнивает только title/summary/outcome/state/verification и состав эпизодов — **claims/participants/даты не сравниваются** → после recheck-ревизии утверждений карточка истории может остаться устаревшей до следующего изменения поля (**M-MCA05-2**, не blocking).
- **Контрпример 3:** LLM-сбой в backfill → `paused/model_unavailable` (никогда не completed — тест зелёный); но sanctioned-код `story_backfill_paused_budget` недостижим: `worker_budget` (lore-стиль) backfill'ом не потребляется, а llm_client схлопывает budget и timeout в `LLMTimeoutError` (**M-MCA05-3**, не blocking; латентно — прод-вызывателя enqueue нет).
- **2 known bounds-failed** воспроизведены и атрибутированы: нарушители `web/api/analytics.py`, `web/static/polygon-background.js`, `web/static/telegram-init.js` в `git diff pre-round1026-a1` — санкционированные более ранними раундами пути, mca-05 в diff-vs-теге отсутствует. Чужие, состав идентичен анкеру.
- **JS-дрейф** (отклонение №6) — факт подтверждён: в HEAD-блобах 4 JS-тестов пин `2\.58\.40` при APP_VERSION 2.58.41 → на baseline они падали. Ре-пин минимальный (по 2 строки).
- **Пин-тесты**: 23 py-файла — только version-строки; 3 семантических пина оправданы и минимальны (mca-01 allowlist commit-каунт 137→141 — пересчитано, ровно +4 `db.commit()` в v21; mca-04b `==20`→`>=20` — корректно при сдвиге хвоста реестра; mca-17a сканер дополнен паттерном `emit_story_event(` — инвариант «ни одно имя не выдумано» сохранён и усилен).
- Интеграционные рёбра: mca-07 канал (AMEND за гейтом, fail-open), компилятор (touch fail-open, инструмент жив), message_identity (queue_source_recheck аддитивно, fail-open), direct_chat (local_context за гейтом), single-writer coexistence (тест) — все аддитивные, без врезок в чужие контуры; ASAP-3 verbatim-граница тестом закрыта (`direct_context_composer.py`/`model_slots.py` не импортируют mca_episodes).
- Безопасность: участники — только ID; события через `build_event` → `sanitize()` + белые списки полей + reason_code по словарю; секретов в новых модулях нет; chat-scope изоляция тестом; R17-логи — только коды/числа.

## 4. Оценка 7 отклонений Builder

| # | Отклонение | Вердикт |
|---|---|---|
| 1 | multi-topic сплит по кластерам участников | **Принято** — D4-совместимо: LLM даёт только тематическое суждение (`multi_topic`), границы/порядок/время — детерминированы; без LLM сплит не выдумывается (fail-closed); негативы A12 зелёные |
| 2 | no-op rebuild не плодит версии | **Принято с оговоркой** — change-driven трактовка разумна и тестирована, но детектор изменения неполон (см. M-MCA05-2) |
| 3 | LLM-сбой → `paused/model_unavailable` | **Принято** — честная пауза, никогда не completed; reason-code-гэп учтён в M-MCA05-3 |
| 4 | claims без refs → unknown (+`dropped_claims`) | **Принято** — усиление §8.1, не сужает контракт |
| 5 | сканер mca-17a дополнен `emit_story_event(` | **Принято** — имена литеральные на call-site, инвариант усилен; mca-17a набор зелёный |
| 6 | ре-пин 4 JS-тестов | **Принято** — дрейф до-существующий (факт проверен по HEAD-блобам), изменение минимальное, release-механика |
| 7 | CRLF/`git diff --check` | **Принято с уточнением** — репо смешанный: HEAD-блобы settings/README/тестов уже CRLF, services/ — LF; дефолтный `--check` флагует `\r` на любом изменении CRLF-файла (до-существующее условие); с `cr-at-eol` exit=0 (воспроизведено). Конвенция де-факто есть, но в git config не закодирована (L5) |

**Недisclosed deviation (новое, найдено ревью):** отсутствие split-операции — см. H-MCA05-1.

## 5. Findings

### Blocking

- **[H-MCA05-1] [High] Не исполнено требование §9.2 `:334` «поддерживает merge/split и redirect старых ID» — split отсутствует.**
  - Где: `services/mca_episodes.py` (есть `merge_stories`, нет split-API; удалить связь эпизода из истории невозможно — links только `INSERT OR IGNORE`); `services/mca_events.py:133` — `story_split` в словаре, эмиттеров 0 (мёртвый sanctioned-код).
  - Требование/инвариант: ТЗ §9.2 `:334` дословно («Повторная сборка… поддерживает merge/split и redirect старых ID»); spec контракт (h)/D9; tasks T-4252 (MCA05-R1/R3); шапка tasks: «модель с операциями (merge/split/overrides), готовую к UI-обвязке mca-12». Отклонение в evidence §4 не задекларировано.
  - Impact: модель не готова к mca-12 в объёме контракта; разделение истории невозможно выразить даже вручную через репозиторий.
  - Исправление: реализовать `split_story(source_id, episode_ids, …)` (новая история из подмножества + новая версия/redirect-семантика у источника + событие/код `story_split`) либо получить у Architect явную санкцию переноса split в mca-12-амендмент с записью в spec/ADR. Плюс контрактный тест.
  - Verification: тест split (состав/версии/redirect/фасад после split) + исчезновение мёртвого `story_split` либо его легитимный эмиттер.

- **[M-MCA05-1] [Medium, requirement-blocking] Fallback `_episode_candidates` на пустой результат фасада возвращает excluded/rejected/redirected контент (нарушение SC-14 и spec §6 «excluded_from_retrieval уважается каналом mca-07»).**
  - Где: `services/mca_retrieval_context.py:583+` — `if not rows: rows = list_lore_stories(...)` срабатывает не только при OFF/ошибке (санкционированный fail-open), но и при легитимном пустом ответе фасада.
  - Evidence: контрпример воспроизведён на temp-БД (см. §3, Контрпример 1): фасад 0 строк, канал вернул кандидата excluded-истории через mapped-legacy двойника. Также путь актуален для redirect-источников (слияние скрывает их в фасаде, но legacy-двойник resurrect-ится).
  - Impact: обход пользовательского контроля excluded_from_retrieval и redirect-семантики в ограниченном, но реальном состоянии (все истории чата excluded/rejected/скрыты при живых mapped-legacy записях).
  - Исправление: fallback только при (a) гейте OFF или (b) исключении фасада; при успехе+пусто — возвращать пусто. Строго говоря — различить три состояния (OFF/ошибка/успех-пусто). Плюс регресс-тест «excluded story + mapped legacy → 0 кандидатов».
  - Verification: новый негатив-тест зелёный; фича-набор и канал-набор зелёные целиком.

### Non-blocking debt (регистрируется, не блокирует)

- **[M-MCA05-2] [Medium] Unchanged-детектор пересборки не сравнивает claims/participants/event-даты** (`mca_episodes.py:1909–1922`) — после recheck-ревизии утверждений карточка/версия могут остаться устаревшими до изменения другого поля. Противоречия не теряются (flip verification → rebuild), теряется только свежесть текстов утверждений. Fix: включить сигнатуру claims/участников/дат в сравнение. Зарегистрировать до mca-12.
- **[M-MCA05-3] [Medium] Backfill не потребляет `worker_budget` (lore-стиль) — контракт (e)/D6 «источник исчерпания — существующий worker-бюджет»; `story_backfill_paused_budget` недостижим (dead-константа `BACKFILL_REASON_BUDGET`); budget exhaustion неразличим с `model_unavailable` (llm_clientRaise → LLMTimeoutError).** Латентно: прод-вызывателя `enqueue_episodes_backfill` нет (только будущие контуры/ops). Обязательное условие: до любого прод-включения backfill — wired worker-budget или санкция Architect; иначе честный инвариант остаётся вакуумным.
- **[L1] [Low]** `redirect_target`: мёртвое условие `return current_id if current_kind == str(kind) else current_id` (обе ветки одинаковы) — почистить при следующем касании.
- **[L2] [Low]** `upsert_story` (existing-ветка): всем новым эпизодам проставляется одинаковый `order_no = len(existing_eps)` — порядок ссылок косметически деградирует (сортировка добивает по episode_id).
- **[L3] [Low]** Конфликт известных `outcome` двух эпизодов разрешается молча порядком сортировки (`known_outcomes[0]`) — событие противоречия на уровне outcome-полей не возникает (claims-уровень покрыт).
- **[L4] [Low]** Параллельные темы с одинаковым составом участников без reply-связей не сплитятся детерминированно (кластер один) — episode-уровень склеит; story-уровень защищён LLM-подтверждением (fail-closed). Приемлемо по D4 («ложный split приемлем, ложная склейка запрещена» — здесь ни того, ни другого).
- **[L5] [Low]** `cr-at-eol` не закодирован в git config (`core.whitespace` пуст) — дефолтный `git diff --check` будет флаговать любое изменение CRLF-файлов репо. Рекомендация: зафиксировать `git config core.whitespace blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol` отдельной санкционированной правкой (не в этой фиче).
- **[L6] [Low]** Производительность (bounded, но заметная): `_find_overlap_duplicate` — O(сегменты × 500 эпизодов) с JSON-парсом на батч; `build_local_context` сканирует до 400 эпизодов на каждое direct-сообщение (за гейтом, fail-open). Для R2 приемлемо; пересмотреть при росте `mca_episodes` (добавить индексный lookup по message_keys при потребности).

## 6. Staging-перечень для DevOps (после Fixes и повторного гейта)

1. Не деплоить до устранения H-MCA05-1 + M-MCA05-1 и повторного Reviewer-гейта (аппрув привязан к WTH; любое изменение = ребайндинг).
2. Deploy остаётся `DEFERRED_TO_RELEASE` (§20, агрегатный релиз); пер-фичевых тегов/bump нет (APP_VERSION 2.58.42 уже зафиксирован в скоупе).
3. Преддеплойные проверки: `python -m pytest tests -q` ожидание ≥10428 passed / 2 known failed (чужие bounds — web/analytics, polygon-background, telegram-init vs тег `pre-round1026-a1`); фича-набор 59/59; JS 36/36; F8 `--check` CHECK OK 488, Δ каталога = 0.
4. Миграция: SQLite v20→v21 (7 таблиц + 6 индексов + 5 ALTER под guard), идемпотентна, повтор no-op; backup-дисциплина mca-14 до миграции (учёт WAL); PG — no-op, проверять `user_version=21` и запись `episodes_stories` в `schema_migrations`.
5. Kill-switch: все 4 `MCA_EPISODES_*` default ON; откат hot — `MCA_EPISODES_ENABLED=false` (+рестарт) = паритет baseline; под-гейты инертны. Manifest-список релиза «26+1+4».
6. **Не включать/не запускать episodes backfill в проде** до исполнения M-MCA05-3 (worker-budget) — прод-вызывателя нет, enqueue только осознанным ops-действием.
7. Пост-деплойный smoke: `episodes.build`/`episodes.backfill` видны в реестре процессов; mca-07 канал отвечает (episode-кандидаты при наличии историй; при пустых — legacy-путь без утечек); компилятор `compile_lore_story` жив; `local_context` в EvidenceBundle заполняется/пусто=`not_available`.
8. Наблюдаемость: события `story_*` и `episodes_build` в `mca_events` (ретенция 14/90), reason_code +10 в словаре; WARN/ERROR — с cause-кодами (`parse_error`/`model_unavailable`/`provenance_unresolved`).

## 7. Unavailable checks

- Живой LLM-прогон канона извлечения (опция D5) — в среде нет провайдера; контракт закрыт офлайн-валидаторами на фикстурах (санкция «опциональный» — не блокер).
- Прод-верификация — `DEFERRED_TO_RELEASE` (вне этого гейта).
- `EXPLAIN QUERY PLAN` на прод-объёмах — выполнен неофициально; индексы v21 соответствуют фактическим запросам репозитория по построению (chat-scope списки, реверс-lookup, redirect PK); точная план-проверка возможна только на прод-данных релиза.

## 8. Binding

- Верdict действителен только для состояния: HEAD `0b1ae9c…662` + WTH `D98B3780…CCEA` (манифест `plans/reports/mca05_wth_manifest_review.txt`). Изменение любого файла скоупа/спека/чужого WIP, попадающего в цепочку сборки, инвалидирует binding — требуется повторное измерение.
- После фиксов: повторный прогон фича-набора + канала + полного pytest; новые failed = 0; ревьюфикс по H/M-пунктам — отдельным Builder-проходом, код Reviewer'ом не правился.

---

# Round 2 — дельта-ревалидация реворка (H-1/H-2) — 01.10.2026

- **Status: APPROVED FOR RELEASE** — blocking 0. Ядро round 1 не перепроверялось (одобрено); проверена только дельта реворка + plausible-регрессии. Round-1 блокеры H-MCA05-1 и M-MCA05-1 — **RESOLVED** (оба верифицированы независимо по коду и тестам).
- **Reviewed-Commit:** `0b1ae9cc831661cda319dbea40253295d251c662` (HEAD не изменился); staged = EMPTY (проверено); всё по-прежнему незакоммиченно, код Reviewer'ом не правился.
- **Working-Tree-Hash:** `BD1C0C4D68253F46C558B4438A4E3CC6E11CD007683528A2E90B1C0378CB55F3` — пересчитан независимо (SHA-256 манифеста `plans/reports/mca05_wth_manifest_rework1.txt`; совпал). Per-file SHA-256 пересчитаны по всем **50 скоуп-файлам — 50/50 byte-exact** с рабочим деревом; состав-дельта манифеста к round 1 ровно реворк-поверхность: +`tests/test_mca07_retrieval_context_round1027.py` (адаптация фейка), изменены `mca_episodes.py`/`mca_retrieval_context.py`/тест фичи/`evidence.md`. Round-1 WTH `D98B3780…CCEA` невалиден (заменён этим).
- **Spec-Hash:** `8177CB0FF3FCEFE5168A82A52690DEB66B0DB8990DA2F047861E342EAE6E9EC0` — подтверждён (per-file match); ADR-1027-12 `2E7E110B…4C50` — подтверждён. Spec/ADR/tasks не менялись с round 1.
- **Git base и объём:** base = HEAD `0b1ae9c`; inspected = дельта 4 файлов реворка (код + тесты) + манифест; чужой WIP (`arch-frames`/`metrics`/`workflow_state`) не тронут и не ревьюился (без изменений).

## R2.1. H-MCA05-1 (High) — split_story — RESOLVED ✅

| Проверка | Факт (независимо) | Вывод |
|---|---|---|
| Реализация | `EpisodeRepository.split_story` (`mca_episodes.py:971–1206`), рядом с `merge_stories`; под `write_transaction` (`op_name="mca05_story_split"`); guard'ы: нет источника / <2 эпизодов / пустой или чужой список эпизодов → no-op `("", False)`; dedup запроса | ✅ |
| Частичный сплит | эпизоды переносятся link'ами в новую историю; у источника `DELETE` отделяемых link'ов (`:1112`), карточка пересчитана детерминированно теми же правилами, что `assemble_stories` (`_card`: участники/claims-merge/обе даты min-max/outcome+state, unknown→`uncertain`); новая версия `expected_version+1` с полным снимком (override-состав в снимке); `discovered_at`/`excluded_from_retrieval`/`task_status_ref` НЕ трогаются (UPDATE `:1134–1149` их не содержит) | ✅ |
| All-split | источник не может остаться пустым (§9.1) → удаление источника + redirect `story→новая` в `mca_story_redirects` (spec (h)) + переезд mapped legacy-ссылок (`:1169–1172`); версии источника сохраняются (история не теряется) | ✅ |
| События | post-commit `story_discovered` (новая) + `story_rebuilt` (источник, частичный случай), оба `reason_code="story_split"` — мёртвый санкционированный код получил легитимных эмиттеров (было 0 → стало 2 call-site; имена из фиксированного набора §16.1, контракт mca-12 не расширялся) | ✅ |
| Тесты | `test_split_story_three_episodes` (`:608`): 3→**1+2**, обе `open`, redirect=0 и `resolve_story_id` — тождество, источник=v2 (снимок оставшихся: состав+даты), новая=v1, фасад видит обе, `story_split` в `mca_events` после flush. `test_split_single_episode_story_noop` (`:650`): single/пустой/чужой список — no-op без изменений (состав/версия/redirect/события). `test_split_all_episodes_redirects_source` (`:676`): all→источник удалён, redirect резолвится, фасад — только новая | ✅ ровно контракт ревью |

SQL-безопасность: `IN (%s)` интерполяция — только плейсхолдеры `?` (данные — параметрами); нет инъекций.

## R2.2. M-MCA05-1 (Medium, requirement-blocking) — трёхсостоянийная логика фасада — RESOLVED ✅

| Проверка | Факт (независимо) | Вывод |
|---|---|---|
| Три состояния | `mca_retrieval_context.py:581–612`: `facade_rows: list \| None`; (a) гейт OFF → `None` → legacy `list_lore_stories` (паритет); (b) исключение фасада → `None` → legacy (fail-open mca-07); (c) фасад ответил (`is not None`, включая **честно пусто**) → ответ и есть результат (`if not rows: return []`), legacy-фолбэк на успехе-пусто **запрещён** | ✅ ровно предписание ревью |
| `list_stories_for_retrieval` | всегда возвращает list (не None — сигнатура и код `:1447–1493`); excluded/rejected отфильтрованы, redirect-источники скрыты, legacy-unmapped видимы (`kind="legacy_story"`), chat-scope сохранён | ✅ |
| Регресс-тест | `test_channel_no_leak_of_excluded_via_legacy_fallback` (`:1281`): история + **mapped-legacy двойник** → до exclude канал отдаёт ровно `episode:<story_id>` (не двойника); exclude → фасад пуст → **канал пуст**; redirect-ветка: merge → виден только приёмник; exclude приёмника → пусто (двойник redirect-источника не воскресает). Контрпример round 1 (Контрпример 1) закрыт | ✅ |
| Адаптация фейка mca-07 | `_FakeFacadeShell` (`test_mca07…:310–330`): минимальный `db.db` — legacy теперь приходит через фасад (post-AMEND контракт), prod-код mca-07 сверх `_episode_candidates` не менялся; набор mca-07 зелёный | ✅ |
| Регрессии OFF/fail-open | `test_facade_gate_off_legacy_channel_path`, `test_master_off_no_pipeline_writes`, fail-open тест (`:1270–1278`) — на месте, зелёные | ✅ |

## R2.3. Прогоны (независимо воспроизведены @Reviewer)

| Прогон | Результат |
|---|---|
| Полный pytest | **10432 passed / 2 failed** в 301.5s — **анкер воспроизведён точно** (2 failed — те же чужие known bounds: `test_tool_coordinator…TestBounds`, `test_unified_image_request…TestBoundsA3` vs `web/` чужого WIP; новых failed = 0). Дополнительно конвергенция с deselect флейка: 10431 passed + 1 deselected + 2 failed — тот же состав |
| Фича-набор | **63 passed** (59 + 4 новых реворк-теста) |
| Смежные | mca-01/03/04b/07/13/14/17a — **263 passed** (196+67, сходится с evidence) |
| JS | **36 passed** |
| F8 `--check` | `CHECK OK: реестр 488 == REGISTRY…` exit=0 — Δ каталога = 0 |
| `git diff --check` | exit=0 (c `core.whitespace…cr-at-eol`; дефолтный по-прежнему флагует CRLF — L5 без изменений) |
| Коллекция | 10434 собрано = 10432 + 2 known — сходится |

**Флейк-инцидент (прозрачно):** 2 из 3 полных прогонов обрывались на `tests/test_summary_memory.py::TestSelfHeal::test_broken_extension_zero_probe_calls` — зависание в **teardown фикстуры `db`** (`test_summary_memory.py:39`, aiosqlite `close()` не возвращается; в дампе 0 кадров mca-05). Файл вне скоупа (не в манифесте, не изменён); в изоляции — зелёный (файл 79/79 за 6с); третий полный прогон — анкер воспроизведён. Атрибуция: транзиентный environment/load-флейк чужого кода, не регрессия реворка. → backlog-заметка (см. N3).

## R2.4. Findings round 2

### Blocking
- Нет. (H-MCA05-1, M-MCA05-1 — RESOLVED, см. R2.1/R2.2.)

### Non-blocking debt (регистрируется)
- **[N1] [Medium, binding-hygiene]** В манифесте `mca05_wth_manifest_rework1.txt` строка `DIFF_SHA256 A73871BF…` **устарела**: фактический SHA-256 `git diff HEAD` = `349F6A6F…E3F71` (пересчитан; гипотезы кодировки/скоуп-диффа исключены — значение из промежуточного состояния реворка). Оперативный биндинг не пострадал: per-file 50/50 byte-exact + HEAD + staged-empty проверены независимо, WTH воспроизводится; ни один prod-файл не может дрейфовать вне per-file покрытия. Fix при следующем касании: перегенерировать манифест (обновить строку). Настоящий аппрув биндингом: HEAD `0b1ae9c…662` + WTH `BD1C0C4D…B55F3` + per-file 50/50.
- **[N2] [Low]** `plans/reports/full_audit_results.md` (модифицирован — регистрация round-1 ревью) не объявлен в манифесте ни как FILE, ни как IGNORED. Артефакт ревью вне кодовой цепочки сборки — на биндинг не влияет; впредь объявлять явно.
- **[N3] [Low, вне скоупа]** Транзиентное зависание teardown `db`-фикстуры `test_summary_memory.py` под нагрузкой (см. R2.3) — recommend backlog: разобраться с aiosqlite-close в фикстуре (таймаут/диагностика), т.к. ломает воспроизводимость полного прогона.
- **Перенесено из round 1 (без изменений):** M-MCA05-2 (unchanged-детектор без claims/участников/дат — зарегистрировать до mca-12), M-MCA05-3 (**условие релиза: не включать/не запускать episodes backfill в проде** до wired worker-budget/санкции Architect), L1–L6.

## R2.5. Binding и Sanity

- Аппрув действителен только для состояния: HEAD `0b1ae9cc831661cda319dbea40253295d251c662` + WTH `BD1C0C4D68253F46C558B4438A4E3CC6E11CD007683528A2E90B1C0378CB55F3` (per-file 50/50 byte-exact; staged empty). Дрейф после замера: только эта round-2 секция `review.md` и допись в `full_audit_results.md` (артефакты ревью, вне манифеста и вне кодовой цепочки — прецедент mca-04b).
- Deploy остаётся `DEFERRED_TO_RELEASE` (§20); пер-фичевых тегов нет; APP_VERSION 2.58.42. Преддеплойные проверки §6 round 1 в силе с обновлением счётчиков: полный pytest ≥10432 passed / 2 known failed, фича 63/63, JS 36/36, F8 CHECK OK 488. Пункт 6 §6 (backfill) — обязателен (M-MCA05-3).
- Unavailable checks round 1 остаются: живой LLM-прогон (нет провайдера; офлайн-валидаторы — санкционированная замена), прод-верификация (DEFERRED_TO_RELEASE), EXPLAIN QUERY PLAN на прод-объёмах. Документ-верификация зависимостей: N/A для дельты (новых зависимостей/миграций/внешних контрактов реворк не добавляет).
