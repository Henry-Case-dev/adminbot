# SOUL-1 — REV-PAYLOAD-VERIFY: независимая проверка payload-верификации (18.10.2026)

**Статус (R2, RECHECK-FIX3, 18.10.2026, кандидат `72b91d6e`): F1 и F3 — ЗАКРЫТЫ (проверено исполнением, §R2). Precondition — OPEN с остатком только релизного прогона: (ii) read-only захват кастомов, F5 (`personas`), F2/F4 env-фиксации. Код-блокеров не осталось.**

**Вердикт R1 (директива 18.10 п.2; критерии (i)(ii)(iii) — `soul-release-prep.md` §5 @ `e424f0b8`): OPEN (с остатком)** — исторический статус до правок F1/F3: (i) — закрыт; открыты были (ii), мини-блокеры F1/F3 (исполнены в `72b91d6e`), фиксации F2/F4/F5. Решения по F1–F5 — §2; список «до включения» R1 — §3 (актуальная версия остатка — §R2).

## R2 — RECHECK-FIX3 (18.10.2026, кандидат `72b91d6e`): F1/F3 закрыты

**Привязка R2.** Коммит `72b91d6e` («fix(soul-1): F1 summary_l2_writer legacy-voice cleanup + F3 /persona phrase»); `git diff 6094a2cf HEAD -- services` = только `prompt_registry.py` и `smartmodule_phrases.py` (37+/8−); `handlers/web/config` — пусто (services не менялись и в последующих win-glass-коммитах). Прогоны — изолированный worktree `<scratch>/payload-verify-recheck2` @ `72b91d6e`; postfix-evidence лейна (`evidence/soul-release/postfix/`) сверено с моими прогонами; отревьюенные артефакты `payload-verification/` не перезаписаны (дельта — отдельным каталогом, осознанно).

**1) F1 — закрыт (проверено исполнением).** Гейт-маркер `_legacy_persona_marker_re` += `|двач`; два узких правила: «сохраняй характер бота и атмосферу конфы» → «держи голос Core» (`summary.l2_legacy_voice_reference`) и «Сарказм, интернет-сленг, двачерские обороты и мат разрешены» → «Сарказм, интернет-сленг и мат разрешены» (`summary.l2_dvach_vocabulary`). На реальном resolve-пути (`resolve_prompt_with_source` с PG-значением = канон, hybrid-ON): effective `cd3ecdfa7441` (8344), `removed=2`, labels — оба правила, маркеров `{}`, стабильно; канон-байты не мутируются; OFF-паритет (нет PG / `source=default`) — байт-в-байт; идемпотентно; кастом с «двач» (unknown bytes) не тронут; 8 контракт-секций канона целы. Сравнение двух стендов (pre/post): изменился ровно **1 из 25** ключей (`summary_l2_writer_system_prompt`: `f832fb8cb5e4`→`cd3ecdfa7441`, removed 0→2), остальные 24 строки — byte-equal по всем полям; `customs`/`withheld`/`reconstruction` — MATCH; суммарно **39 сегментов / 13 ключей**; маркер-скан активных 5 путей чист (остались только F2-ветки); `suppression_labels` прочих блоков не изменились; `message.smartmodule.chat_persona`/`message.smartmodule.phrases` больше не маркерные; код-строка старой фразы ушла из sweep (файлов 21→20). Симуляция «узкого правила мало» — теперь GREEN.

**2) F3 — закрыт.** `CHAT_PERSONA_PHRASE` = «я живой участник чата: остроумие, абсурд и язвительность, но не агрессия. тон: {tone}. настроение подстраиваю сам»; `{tone}` сохранён; рендер `handlers/direct_chat.py:253` не менялся (handlers diff пуст; handler-тесты в focused — зелёные); реестр: `legacy_persona=False`, метка `chat-persona-core-voice`, note/purpose обновлены; `FACTORY_SET_SHA256_12 = 7422c0385f7d` == `factory_set_fingerprint()` (guard зелёный); старая фраза по-прежнему ловится маркером (негативный guard — тихая регрессия невозможна). Новые тесты (3): F1-регрессия, F3 позитив, F3 негатив — прогнаны отдельно, passed. **Обновление 2 моих тестов — обосновано, не ослаблено:** инвертированные по смыслу утверждения заменены более строгими (block `legacy_persona=False`, отсутствие маркеров, семейный текст содержит новую константу и не содержит старую фразу, `ui == "catalog_pending"`), а проверка «старое снова поймается» выделена отдельным негативным тестом.

**3) Прогоны (мой повтор — все совпали с лейном):** focused 12-файловый набор — **283 passed**; `tests/test_soul1_*.py` (30 файлов) — **599 passed**; parity — **13/13**; `gen_param_registry_round1025.py --check` — **575 == REGISTRY** ok; node `tests/js` — **86/86**; смежные (`test_prompt_migrations.py` + `test_round1025_f8_registry.py`) — **70 passed**; новые тесты — 3 passed; completeness — 12 passed.

**4) Граница — заголовок «СТИЛЬ (характер бота)»: решение — достаточно, третье правило не требуется.** Это метка раздела, а не инструкция/определение: оценочных/идентичностных слов нет; оперативная строка под меткой теперь прямо назначает голос — Core («держи голос Core»); старый голос и «двачерские обороты» сняты; функциональные контракты целы. Метка не несёт поведения и не конкурирует с Core; её переименование («СТИЛЬ (голос Core)») — необязательная косметика при следующем касании канона (backlog), не блокер.

**Итог R2: код-блокеров нет; precondition — OPEN, остаток только релизного прогона:**
1. **(ii)** read-only захват кастомов: `summary_editor` (сверить sha12 `6a1f3432889c`/len 2023) + per-chat `summary_cover_style` (`35013bd88081`/110) + расширенный маркер-скан + вердикт;
2. **F5** — read `personas`/`persona_traits` + вердикт конфликта с Core;
3. **F2-фиксация** — `SMART_VERBALIZER_MODES_ENABLED` ≠ 0 (env);
4. **F4-фиксация** — `NOSTALGIA_ENABLED`/`memory.nostalgia_enabled` absent/0.

| R2 | Статус |
|---|---|
| F1 (`summary_l2_writer`) | **CLOSED** (eff `cd3ecdfa7441`, removed=2, 0 маркеров, OFF-паритет, 24/25 byte-equal, 39/13) |
| F3 (`/persona`) | **CLOSED** (Core-голос, `{tone}`, guard `7422c0385f7d`; тесты обновлены без ослабления) |
| Прогоны | focused 283 / soul1 599 / parity 13 / param 575 / node 86 / смежные 70 — совпали |
| Precondition | **OPEN** (остаток: (ii), F5, F2/F4-фиксации — всё релизный прогон) |

## Привязка (exact candidate)

| Поле | Значение |
|---|---|
| Проверяемый объект | `evidence/soul-release/payload-verification.md` (§0–§6) + артефакты каталога `payload-verification/` |
| Runtime-байты | `git diff 6094a2cf -- services` = пусто (проверено на рабочем дереве и в worktree) |
| Worktree прогона | `<scratch>/payload-verify-recheck` @ `e424f0b8` («docs: fix release prep R2 (F4/F5)»; services == 6094a2cf) |
| Реестр | `soul1-w3-1`, factory_set `0fc99f73d646` |
| Данные | снапшот SOUL-PREP 17.10.2026 19:04:41 UTC (prod `0b7a0aca`, 2.58.84); живой прод не читался |
| Ниточка (non-blocking) | шапка отчёта лейна цитирует head `755c8a75`, стенд-JSON meta = `b4ea6779`; оба — docs-коммиты, runtime-байты идентичны; привязка — по `services == 6094a2cf` |

## 1. Проверено исполнением (изолированный worktree)

**1.1. Стенд.** Полный повтор `stand.py` на восстановленном снапшоте: секции `keys_effective`, `withheld_values_view`, `customs`, `sweep_registry`, `sweep_python`, `paths`, `humor` — **совпали с эталонными по всем полям** (`json.dumps(sort) = MATCH`). Контрольные хэши: Direct-L2 casual `a396369fd5cc` (3874, mk `{}`), Summary single `5d991ee57a74` (mk `{}`), fallback fail-open `45b531879b50` (mk `{}`); сверх задания: tool-phase `f2fac054425b`, narrator `33f1ea2438a5`, factcheck single `2f61c20e3eaa`, humor-craft `adecd3938d4f`, Initiative L1 `99a207313889` — совпали.

**1.2. «0 legacy-маркеров».** В активных системах всех 5 путей маркеров нет (расширенный набор). Объекты с маркерами в выводе: `summary.l2_writer` (F1) и две **неактивные** ветки — `modes_off_prev_branch` и `code_default_path` (обе F2).

**1.3. Удержание.** 11/11 ключей: `withheld=True`, `source=default`, `provenance_missing`, маркеров 0. Для direct tool-phase / summary single / factcheck single доказано отдельно: `effective sha == sha12(suppress_legacy_speech(factory, source="global"))` — удержание отдаёт именно заводскую вычищенную редакцию.

**1.4. «37 сегментов в 12 ключах» (§2 отчёта).** Сумма `removed` из свежего JSON = **37 по 12 ключам** (checkup 5, direct 2, direct-L2 1, factcheck 4+2, summary 4+1, deep_research 1, search 5, webpage 4, youtube 4+4). Verbatim-пробы правил на реальных канонах: `identity_sentence` (direct/search/checkup/summary), `safety_circumvention`, `tone_label`, `bot_knowledge_hostility`, `search_sneer`, `checkup_humiliation`, `checkup_language`, `direct_style_label`, `mode_deep_research` — фразы удалены/заменены; повторный проход `removed=0` (идемпотентно); маркеров не осталось. Контракты целы (probe = true: ИНСТРУМЕНТЫ/ПРИОРИТЕТЫ/АНТИ-ГАЛЛЮЦИНАЦИИ/ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ/query_chat_memory/execute_web_search/АНТИ-БОТ/АСИММЕТРИЯ/вердикт/`<chat_history>`/ГРАММАТИКА/АКЦЕНТЫ/ФОРМАТ; deep_research: «Пиши по делу…» есть, «Интегрируй токсичный стиль…» нет). Нитка: `l2_base.НЕСТЫКОВКЕ=false` — не контракт L2 (шум пробы); контракт подтверждён в tool-phase.

**1.5. Кастомы.** `verbilizer_default_mode` = `serious` (7, маркеров нет; per-chat `casual` рантаймом не потребляется — `_resolve_default_mode()` читает глобальный слой). Честность «unknown» по `summary_editor`/`summary_cover_style` **подтверждена и обоснована**: снапшот хранит только sha12/len (mk=0 — узкая regex `токсичн|бот-абьюзер|унизить|унизив`; для per-chat маркеров нет вовсе), W1-backup собран при `pg_status=down` (`pg_value_at_backup=null`) — сырых текстов нет; `6a1f3432889c`/`35013bd88081` отсутствуют в `known_canon_hashes` (142) и в лестнице миграций editor-ключа (832/1162/1596/1921→2211). **Доказательство слабости mk:** l2_writer имеет mk=0, но содержит «двачерские обороты» — mk=0 не доказывает отсутствие старого голоса; закрыть (ii) из имеющегося evidence нельзя (способ — §3.2).

**1.6. Humor.** `evaluate_candidates`: **0 рантайм-потребителей** (grep по services/handlers/web/tools — определение `mca_humor_craft.py:444`, тесты, стенд; стендовый `callers_scan=[]`); юнит-тесты на месте (`test_soul1_w4_humor_craft.py:300`, `:332`). Craft: гейт `humor_craft_enabled` → `resolve_ref`, без доп. LLM (слой 735 симв., `layer_calls=0`; serious→`humor_serious_context`, без стратегии→`humor_no_strategy`). Feedback: `capture_send` — только при реальной отправке (`sent_id`) и оси ON (`direct_chat_service.py:3631-3653`, R17-поля); окно — часть существующего experience-tick (`mca_experience_jobs.py:929`; `memory_maintenance.py:284-291/409-422`); OFF → `humor_skipped_disabled=1`. Прогоны: focused 5 файлов = **96 passed**; дополнительно `completeness`+`parity_off` = 25 passed; `gen_param_registry_round1025.py --check` = «575 == REGISTRY, карта полна» ok.

## 2. Решения по F1–F5 + incidental

**F1 — БЛОКЕР до включения (мини-правка).** Достижимость: `flags.summary_hybrid_l2_enabled=true` (прод-снапшот) → hybrid-L2 Summary активен; это не SOUL-ось, релиз её не переключает — фраза достижима и сегодня, и после включения (Summary — один из 5 путей директивы). Канон `summary.base.l2_writer` (canon-equal `f832fb8cb5e4`) содержит «сохраняй **характер бота** и атмосферу конфы… **двачерские обороты** и мат разрешены» — инструкция сохранять старый голос; Core в этот промпт не подаётся. Правка: узкого правила мало — гейт `_legacy_persona_marker_re` на каноне не срабатывает (проба: marker=False, removed=0); нужны (а) расширение гейт-маркера (напр. `|двач`) и (б) **два** узких правила: оборот «сохраняй характер бота и атмосферу конфы» → голос Core и «двачерские обороты» → убрать/заменить (симуляция: одно правило даёт removed=1, но «двачерские» остаются — фикс неполный). Условие known-canon сохраняется (кастом не тронет); идемпотентно. Blast radius: только `services/prompt_registry.py`; не ломает registry 575 / parity OFF / frozen (web); после — refresh evidence (eff-hash, счётчики 37→39) + повтор focused/completeness. Канон-бамп не выбран: он не очищает живой PG-байт без write-pass.

**F2 — ДОКУМЕНТИРОВАННО-ПРИЕМЛЕМО (2 остатка).** Кодовый fallback (нет PG) и `SMART_VERBALIZER_MODES_ENABLED=0` отдают сырые код-каноны/PREV-слепки (`resolve_speech_value(..., source='default')` не вычищает; PREV chat-вербализатор содержит «токсичн/бот-абьюзер»). Это задокументированный OFF-паритет W2 (`prompt_style_blocks.py:193-199`); на проде триггеры не активны (все речевые ключи непусты; пустой `prompts.summary_cover_style_id` — не речевой селектор; kill-switch default ON). Остатки: (1) в релизном прогоне зафиксировать `SMART_VERBALIZER_MODES_ENABLED` ≠ 0 (снапшотом env не снят); (2) backlog: решение о вычистке кодового дефолта меняет OFF-паритет — отдельно, вне релиза.

**F3 — БЛОКЕР до включения (мини-правка).** `/persona` отвечает «я тот самый токсичный бот-абьюзер…» (`smartmodule_phrases.py:161` → `handlers/direct_chat.py:253`). В реестре: `message.smartmodule.chat_persona`, `legacy_persona=True`, owner W3, `catalog_pending`, note «требует замены на голос Core»; AMD.4.6(в) числит «замена W3/W10» — не выполнена. По букве AMD.1.2 («включая "токсичный, саркастичный бот" из Direct») и prep §5(iii) — закрыть до включения. Правка: 1 строка константы (сохранить `{tone}` — handler-тесты строят ожидание из константы) + реестровая реклассификация (`legacy_persona`, лейбл/note) + bump `FACTORY_SET_SHA256_12` (family `message.smartmodule.phrases` меняет отпечаток) + осознанно обновить 2 теста (`completeness` legacy-список, `legacy-removal:260`). registry 575 / parity / frozen — не трогает.

**F4 — ДОКУМЕНТИРОВАННО-ПРИЕМЛЕМО (вне 5 путей + фиксация).** `internal.lore.story`/`internal.nostalgia.candidate` зарегистрированы; AMD.2.6: composer ON → Core + жанровая рамка + канон как функциональная база (`lore_compiler_service.py:190-206`, `nostalgia_worker.py:780-794`); nostalgia по дефолту OFF (`memory.nostalgia_enabled=false`, в снапшоте ключа нет). Остаток: зафиксировать в релизном прогоне `NOSTALGIA_ENABLED`/`memory.nostalgia_enabled` (absent/0). Backlog: при следующем касании модулей почистить тональные слова.

**F5 — ОСТАТОК (проверка до включения, LIVE).** Содержимое `personas`/`persona_traits` («Характер: {overrides}») в снапшот не снималось; дедуп композера снимает только дословное совпадение с Core (`prompt_composer._duplicate_character_segment:1482`). Шаг: read-only чтение таблиц рабочего чата + вердикт конфликта; при конфликте — минимальная правка/запись решения.

**Incidental — BACKLOG.** `mca_humor_feedback.py`: 4 функции продублированы (606-649/660-703), тела идентичны (AST-хэши совпали), первая пара затенена — dead code, поведение не меняет; `summary_memory._MEMORIZE_COMPRESS_PROMPT` — негативная инструкция, не персона.

## 3. Вердикт и что должно произойти до включения

**OPEN с остатком.** (i) закрыт. Для CLOSED:

1. **Код-правки F1+F3** (микро-пакет, один размер правки): `prompt_registry.py` (F1: гейт-маркер + 2 правила) + `smartmodule_phrases.py`/registry-мета/tests (F3) + refresh evidence (эффективные хэши, количество сегментов) + повтор focused/completeness/parity.
2. **(ii) read-only захват в релизном прогоне — до шага «включение осей»:** (а) `SELECT value FROM bot_settings WHERE key='prompts.summary_editor_system_prompt'` → сверить sha12 `6a1f3432889c`/len 2023 (иначе значение менялось → пересмотр) + расширенный маркер-скан (набор стенда + «характер бота»/«атмосферу конфы»); (б) per-chat override чата `-1002661910336` `prompts.summary_cover_style` → sha12 `35013bd88081`/len 110 + скан; записать вердикт (нет маркеров → критерий закрыт; есть → фикс/запись решения).
3. **F2-фиксация:** `SMART_VERBALIZER_MODES_ENABLED` ≠ 0 (журнал релизного прогона); запись «code-fallback принят (OFF-паритет W2)».
4. **F4-фиксация:** `NOSTALGIA_ENABLED`/`memory.nostalgia_enabled` absent/0 (журнал).
5. **F5:** read `personas`/`persona_traits` + вердикт конфликта с Core (журнал).

Шаги 2–5 — read-only, выполняются в релизном прогоне **до** включения осей; правка 1 — до деплоя/в деплой-ветке. Канареечные гейты не вводятся (PET_PROJECT). Решения выше снимают неоднозначность R3: F1/F3 — блокеры, остальное — фиксации; метка «related-nonblocking» отчёта лейна эти решения не отменяет.

## Ledger

| Пункт задания | Статус |
|---|---|
| 1. Стенд-повтор: хэши (3+5), «0 маркеров», удержание 11/11, withheld→factory | VERIFIED |
| 2. «37 сегментов / 12 ключей», verbatim правил, контракты | VERIFIED |
| 3. Кастомы: `verbilizer_default_mode` | VERIFIED; `summary_editor`/`summary_cover_style` — UNVERIFIED офлайн (способ закрытия дан, §3.2) |
| 4. Humor: 0 вызовов + тесты; Craft/Feedback проводка | VERIFIED |
| 5. F1–F5 решения | даны: F1/F3 — мини-блокеры; F2/F4 — документированно-приемлемо; F5 — LIVE-остаток |
| 6. Вердикт precondition | **OPEN с остатком** (§3) |

**Использовано/переиспользовано:** стенд лейна (мой полный повтор совпал), focused 96 (мой повтор), completeness+parity 25 (мой прогон), param-check 575 (мой прогон), R2/R3-прогоны prep (eff-хеши совпали), W1-backup, snapshot-классификация. **Недоступно здесь:** живой прод (SSH/наблюдения), таблицы `personas`, точные байты 2 кастомов — отдельные шаги релизного прогона (§3).
