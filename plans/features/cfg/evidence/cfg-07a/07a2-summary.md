# CFG-07A-2 — анти-backstage контракт НЕ-фактчек маршрутов (выполнение)

- **Лейн:** CFG-07A-2, режим writer. База: HEAD-линия 29b91004 (прод 2.58.100 = `acc285d7`, деплой VERIFIED, миграция v37 штатно).
- **Дата:** 21.10.2026. **Коммитов нет** (по брифу) — кандидат в рабочем дереве; биндинг strict-evidence (candidate_commit) выполняет оркестратор после коммита, статусы строк карты остаются PENDING до ревью.
- **Протокол:** ADR-1013-3 по прецеденту C14/C13 (`37097f7c`/`5af56d8b`): FROZEN-байты прежнего прод-канона + ступень миграции + ROLLBACK на непосредственный канон + байт-тесты; НЕ один растущий black-list (07A.7).
- **Корпус/аудит:** `07a1-corpus.{md,json}` (35 FORBIDDEN + 17 SOURCE_FIX + 12 POSITIVE), `07a1-audit.md` (находки на deployed SHA `29cc49ba`; байты прод-канонов сверены с `acc285d7` — см. `07a2-bytecheck.txt`).

## 1. Каноны: было → стало (7 маршрутов)

Все правки — по семантике suppress-правил (`prompt_registry.LEGACY_PERSONA_RULES`), чтобы вычищенная фабрика совпадала с тем, что подавление делает с persisted-значениями.

| Маршрут | Источник-файл | Было (маркеры) | Стало | Ступень/откат |
|---|---|---|---|---|
| Search | `search_prompts.py` | safety-bypass, identity «бот-абьюзер/двача», sneer «обоссав автора», hostility R46-4 | «Твоя задача — провести исследование…выжимку сути.», «ВАЖНО: Разрешен мат и сленг.», хвост `BOT_KNOWLEDGE_INSTRUCTION_NEUTRAL` | `PREV_SEARCH_CFG07A_SYSTEM_PROMPT` |
| YouTube (субтитры) | `youtube_prompts.py` | safety-bypass, identity, hostility | аналогично | `PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT` |
| YouTube (мультимодал) | `youtube_prompts.py` | те же | аналогично | `PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT` |
| Web | `web_prompts.py` | те же | аналогично | `PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT` |
| Checkup | `checkup_prompts.py` | safety-bypass, identity «DevOps-инженер…», hostility «унизив разработчика…», «человеческо-токсичный»; `CHECKUP_FALLBACK_NOTICE` с bracket-маркером `[СИСТЕМНОЕ УВЕДОМЛЕНИЕ` | «Твоя задача — …выдать отчет о здоровье системы.», «ВАЖНО: Разрешен мат и сленг.», «…на человеческий язык»; notice без bracket-синтаксиса (честный факт фолбэка + жанр админ-контекста сохранены, D2/FA-08) | `PREV_CHECKUP_CFG07A_SYSTEM_PROMPT` |
| Summary legacy single | `summary_prompts.py` | safety-bypass, identity, метка данных «"Архивная справка"» (SF-16, источник семьи «в моей справке»), hostility | «Твоя задача — сделать саммари…», «ВАЖНО: Разрешен мат и сленг.», архивная строка нейтральна («блоки … содержат архивные факты»); метки в данных (`canonical_context.ARCHIVE_MARKER`) НЕ тронуты | `PREV_SUMMARY_CFG07A_SYSTEM_PROMPT` |
| Direct (chat) | `chat_prompts.py` | «ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ: …(перегрелись серверы, база покрылась пылью)… саркастично-токсичной манере» (SF-09/SF-13) | честный слив «Признай косяк в саркастичной манере, но оставайся в рамках фактов.» + новый блок «СЛУЖЕБНЫЕ ПОМЕТКИ (НЕ ДЛЯ ОТВЕТА)» (F2/F3/F4/G2) | `PREV_CHAT_CFG07A_SYSTEM_PROMPT` (MCA23-композиция прод-байтов; прецедент `PREV_FACTCHECK_UNIFIED_CORE_AB`) |

Identity Direct («бот-абьюзер» в СИСТЕМНОЙ РОЛИ) — вне скоупа SF-07 (корпус перечисляет 6 канонов; аудит F-строк Direct флагует только :238) — не тронут.

## 2. Общие блоки и механика

- `prompt_style_blocks.py`: добавлена `BOT_KNOWLEDGE_INSTRUCTION_NEUTRAL` (семантика suppress-правила 5, «используй её в ответе»). `BOT_KNOWLEDGE_INSTRUCTION` (hostile) НЕ менялась — входит в фактчек-канон (фриз CFG-06 W3) и слепки `PREV_*_R1022`/`PREV_*_CFG07A`.
- `prompt_migrations.py`: +7 ступеней `PREV_*_CFG07A → <новый канон>`; `ROLLBACK_MIGRATIONS` для 7 ключей ведёт на НЕПОСРЕДСТВЕННЫЙ прежний прод-канон 2.58.100. Все прежние ступени сохранены и байт-стабильны (пересобраны из FROZEN-баз).
- `direct_capabilities.py` (SF-15): `rejected_note` — человеческие имена capability и reason-формулировки (`REASON_LABELS`/`CAPABILITY_LABELS`); неизвестный код → «сейчас недоступно»; сырое имя остаётся только в agentic-event (R17-диагностика). Машинные пейлоады (`build_l2_plan_block` `<Response_Plan>`, evidence-пакет «СТАТУС ИНСТРУМЕНТОВ/[ИСТОЧНИК/обрезано») НЕ тронуты — контракт «не упоминать служебные пометки» добавлен в канон Writer'а (как W5-egress фактчека).
- `nostalgia_prompts.py` + `nostalgia_worker.py` (FA-06/G1): `contains_unchanged_token` — не-точное эхо «UNCHANGED …» бракуется до отправки (skip, reason=`unchanged_echo`); точный детектор `is_unchanged_response` не менялся (spec §3.5.4). `nostalgia_hint:` (G2/FA-07) остаётся payload-меткой — закрыт контрактом канона Direct.
- `prompt_registry.py`: осознанная регистрация (SOUL-AMD.3.2) — метки ревизий 7 блоков бампнуты (`*-cfg07a`), `FACTORY_SET_SHA256_12` `64ec1c60e278` → `037080375ac8` с полной трассой в комментарии.

## 3. Стык Summary-L2 × Expression OFF (SF-14, план §6.7) — правка НЕ потребовалась

Тест `test_summary_l2_profanity_seam_closed_by_p0_priority`: жанровое «мат разрешены и уместны» в L2-каноне не спорит с OFF — P0-заголовок `<Expression_Settings>` объявляет «эти настройки важнее общего разрешения канона». По условию брифа («правка только если тест покажет противоречие») канон L2 не правил: противоречие закрыто контрактной приоритетной строкой; suppress-правила 10/11 чистят persisted-значения (тесты `test_soul1_registry_legacy_removal` зелёные).

## 4. Верификация

- **Байт-сверка с продом** (`07a2-bytecheck.txt`): 25/25 OK — все 8 «непосредственно прежних» композиций (7 канонов + pre-MCA23 chat) байт-в-байт равны `git show acc285d7`; все старые ступени (PREV_R1021/R1022/R2020, PREV_SUMMARY_SYSTEM_R1028 и др.) байт-стабильны; фактчек не тронут; FORBIDDEN-маркеров в 7 активных канонах — 0.
- **Фокус-прогоны** (`07a2-tests.txt`): 529 passed — новый контрактный файл + suppress/реестр + лестницы миграций + де-роботизация + route-coverage 18 (швы UNIFIED-CORE) + prompt-тесты всех маршрутов + memory_core + nostalgia (unit+worker) + direct L1 + fingerprint-гварды реестра.
- **Новые тесты**: `tests/test_cfg07_backstage_contract.py` (CONTRACT owner=CFG-07A: маркеры-после, лестница/откаты/известность, байт-паритет suppress(persisted)==канон, OFF-паритет, миграция PG на фейк-кэше, человеческая пометка, nostalgia-гард, стык SF-14, POSITIVE-контроли 12) + REGRESSION `test_unchanged_echo_braked_not_sent` (worker).
- **Обновлённые пины** (эталон = код, один коммит код+эталон+тесты, прецедент R4-D-003): `architecture.md` (CHECKUP/SEARCH/YOUTUBE/YOUTUBE_VIDEO/WEBPAGE/CHAT), `backlog.md` (R11-блок summary, R42-6), тесты `test_smartsearch/youtube/web/checkup/direct_chat_prompts`, `test_summary_prompts`, `test_summary_asap21_prompt_migrations`, `test_memory_core_round1020`, `test_de_robotization_round1021`, `test_prompt_migrations`, `test_soul1_registry_legacy_removal` (persisted-байты), `test_soul1_registry_completeness` (премисса вычищенных фабрик), `test_asap7_direct_l1` (D15: пометка человеческая, событие — сырое).
- **Полная суита**: 14877 passed / 1 skipped; 17 failed + 8 errors — ВСЕ вне диффа, классифицированы сравнением с HEAD-бейслайном (git stash): t5150-startup-migrations ×5 + asap7_direct_settings ×2 + mca01_tx + mca10b + mca19/20 reason-codes ×3 + summary failsoft/publish ×2 — падают на чистом HEAD (DB-среда); outgoing_guard ×2 — aiogram 3.29.1 без `InputRichMessageMedia` (среда, `telegram_send.py` не в диффе); mca09 transport — флак в полном прогоне, изолированно зелёный; 8 errors — UI e2e требуют браузерного стенда.

## 5. POSITIVE-контроли (12/12 живы)

PC-03 «не смог сделать саммари», PC-04 🗿, PC-05 пулы 5.x («интернет сдох», «llm откинулась», «беттерстак»), PC-06 CHAT-пулы, PC-07 «UPD (Свежак):», PC-08 «кстати…», PC-12 жанр checkup («жестко разъеби их», «поиздевайся») — `test_positive_controls_alive`; PC-01/02/09/10/11 — словарные, уходят в 07C-G guard (не задеты: гварда в этом слайсе нет).

## 6. Что осталось (честно)

1. **Коммит-биндинг**: по брифу коммитить нельзя — strict-gate (review/release) выполнит оркестратор после коммита; evidence-файлы готовы (`07a2-summary.md`, `07a2-bytecheck.txt`, `07a2-tests.txt`).
2. **07A.1 (postdeploy live)**: effective-payload трассы на проде — после релиза (владелец-опциональная часть по `plans/owner_live_checks.md`; техпроверки — 07A-1.final).
3. **07C-G public_speech_guard**: FORBIDDEN-словарь корпуса + honesty-классы готовы как вход; egress-гард — следующий слайс (вне этого лейна).
4. **Residual вне лейна**: hostility-хвост в фактчек-каноне (W3-фриз CFG-06; suppress-правило 5 чистит persisted) и identity Direct — зафиксированы, не тронуты сознательно.
