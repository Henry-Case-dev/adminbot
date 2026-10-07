# `mca-release` — §21-отчёт финального раунда программы MCA (T-5231/T-5232)

**Дата:** 07.10.2026 · **Раунд:** 10.48-RELEASE (план `plans/docs/mca-round1027-plan.md:215`) · **Отчёт по:** §21 `plans/current_task.md:1046–1060` (п.1–9).
**Источники (только артефакты раунда, без домыслов):** `effective_state_table.md` (Лейн A, T-5222–T-5224), `evidence_lane_b.md` (Лейн B, T-5225–T-5226), `deployment.md` (окно DevOps, VERIFIED 06.10.2026), `stub_money_evidence.md`, `startup_prod_t5216.log`, `tasks.md`/`spec.md`/ADR-1028-24, `plans/backlog.md` (раунды 10.27–10.47), `plans/metrics.md`.
**Прод:** **2.58.67** (`6f062fa` / docs `fbdc95c`), SQLite **v33**, каталог **523**, KS **85**, reason_code **280**, тулы **14**, реестр процессов **47**. **R17:** секретов/живых chat-ID в отчёте нет; чаты маскированы (`chat#O`/`chat#G` — как в effective_state_table.md).

---

## п.1 — Commit/PR и список реализованных MCA-01…MCA-22 (§21 `:1050`)

Программа доставлена **per-feature** (CA-11): каждая фича — отдельное деплой-окно с пер-фичевым бампом; «пустые» бампы запрещены (прецедент 2.58.56–2.58.67). Раунды **10.27–10.47 закрыты** (RELEASED + VERIFIED + reconciled + archived), финальное окно 10.48-RELEASE — VERIFIED.

| Раунд | Фича(ы) | Версия | Коммит (feat/док) | Статус |
|---|---|---|---|---|
| 10.26-EPIC3 | (база) агрегатный релиз Эпика 3 | 2.58.31 | `89a1261`/`e5bd73d` | VERIFIED (metrics §10.26) |
| 10.27 (W0–W3, REL) | mca-14 schema-реестр, mca-13 event-contract, mca-01 tx/task supervisor, mca-03, mca-02, mca-04a, mca-07, mca-17a — агрегатный релиз волны | 2.58.36 | `6285dd7`/`c5cb5a9` | VERIFIED; DDL v12→v19 (v16 identity-backfill 1,98 млн) |
| 10.28–10.29 | ASAP-2/2.1/3/3.1/3.2; **mca-04b** dossier rebuild (v20), **mca-05** episodes/stories (v21), hotfix cover-style | 2.58.33…2.58.43 | `3e8594b`, `219a55c`, `4cb267a`, `cf33e6d`, `6888d20`, `9906c9d` | VERIFIED |
| 10.30–10.34 | ASAP-4 (embedding/cover/summary/writer/analytics, v23), corrective (2.58.46), ASAP-4.1 (v24), 4.2, 4.3, ASAP-4.4 closure | 2.58.45…2.58.54 | `9930fc6`, `ddc24ff`, `09fd5a8`…`615857c` | VERIFIED (три релиза 52/53/54 за день) |
| 10.35 | **mca-08** character/speech (v26) | 2.58.55 | — | VERIFIED (metrics 10.35-MCA08) |
| 10.36 | **mca-15** chat statistics (+11 reason) | 2.58.56 | `35c1c71` | VERIFIED; live-гейт T-4940 |
| 10.37 | **mca-11** tools costs / ToolResult | 2.58.57 | — | VERIFIED; live-гейт T-4961 |
| 10.38 | **mca-10a** RandomSource/ANU (v27) | 2.58.58 | — | VERIFIED; live-гейт T-4986 |
| 10.39 | **mca-16** experience lessons | 2.58.59 | `62357c8` reconcile | VERIFIED; live-гейт T-5015 |
| 10.40 | **mca-09** intents/initiative (v29) | 2.58.60 | — | VERIFIED; live-гейт T-5045 |
| 10.41 | **mca-10b** random applications (v30) | 2.58.61 | — | VERIFIED; live-гейт T-5065 |
| 10.42 | **mca-18** self-model (v31, reason 247→257) | 2.58.62 | `4c70477`/`2d4e3ad` | VERIFIED; live-гейт T-5095 |
| (волна 4) | **mca-19** image understanding; **mca-20** temporal factcheck (v33; попутно datetime-фикс legacy-парсера mca-18) | 2.58.63 / 2.58.64 | `0db30a2`/`e12a94d` | VERIFIED (workflow_state); live-гейты T-5127/T-5151 |
| 10.45–10.47 | **mca-21** guides — контент-фаза; доставка **DEFERRED_TO_RELEASE** | → 2.58.67 | `6f062fa` | VERIFIED (окно релиза, T-5216) |
| 10.46 | **mca-12** miniapp stories (KS +2, routes +5) | 2.58.65 | `3dfc892`/`844ad15` | VERIFIED; live-гейт T-5175 |
| 10.47 | **mca-17c** analytics matrix (reason +1 `oversight_job_action`, routes +3) | 2.58.66 | `e16be7e`/`0b46c84` | VERIFIED; live-гейт T-5199 |
| **10.48-RELEASE** | **mca-release** + канон-доставка mca-21 | **2.58.67** | `6f062fa`/docs `fbdc95c` | **VERIFIED** (`deployment.md`) |

Плюс вне-волновые: **mca-10c** game stub — код в проде, намеренно не активен (см. п.6), **mca-17b** — в составе процессного реестра волны, **mca-22** — ledger анти-самоусиления (расширен mca-18, капы 0.1/цикл + 0.2/24ч — metrics 10.42). Привязка к файлам: финальное окно — единственная код-Δ `services/info_service.py` + 4 identity-файла (`deployment.md` §1–2, биндинг ревью 14 файлов); пер-фичевые манифесты — в архивах `plans/archive/mca-*-round10XX/` и release-manifest окна (T-5228).

## п.2 — Карта контрактов и добавлений схемы (§21 `:1050`)

- **SQLite v33** — книга миграций `schema_migrations` (реестр mca-14), 33 записи, **0 pending** (startup-лог `migrations: current user_version=33 | pending=[]`); в окне релиза миграции не вызывались (Δ DDL = 0). Ключевые добавления программы: v19 базовая волна (task_jobs, события, provenance), v20 dossier, v21 episodes/stories (7 таблиц), v23 embedding quota, v24 `summary_source_windows`, v25 `mca_pipeline_runs.report_json`, v26 `mca_style_requests`, v27 random-запас (4 таблицы), v29 intents, v30 associations/coverage, v31 self-identity, v33 factcheck temporal (аддитивная, «ни одного UPDATE/DELETE» — `services/database.py:3830`, Лейн B).
- **Контракты фич:** `ToolResult` 7 статусов + envelope (mca-11); `MetricResult`/`NumericClaim` `cs:<sha1-12>` + единый numeric-гард (mca-15); `RandomSourceService` + durable-журнал `mca_random_draws` + rejection sampling без modulo bias (mca-10a); Exploration lifecycle `candidate→…→used_in_reply|stored_only|not_used` (mca-10b); `IntentStore`/`SendRecheck` (mca-09); `SelfModelSnapshot`/`BehaviorFrame` во все пути ответа (mca-18); `write_transaction`/TaskSupervisor single-writer (mca-01); reason_code-контракт событий (mca-13); версионные каноны гайдов `INFO_CANON_VERSION 5→6` / `GUIDE_CANON_VERSION 2→3` (mca-21, доставлено в окне).
- **Состояние конфига (прод-runtime):** PG `bot_settings` **476** ключей (seed 434 + runtime), env-оверрайды `MCA_*` = **0**; канон тулов **14**; каталог **523**; реестр процессов mca-17a **47**.

## п.3 — Реальные результаты проверок, включая failed/skipped с причинами (§21 `:1052`)

**Замороженный HEAD (Лейн B, `evidence_lane_b.md`):**
- Полный pytest: **12359 passed / 5 failed / 12364 collected** (449 с) — arithmetic: skipped = 0.
  - **4 failed — pre-existing identity, совпадают с базлайном поимённо** (backlog §121): `test_tool_loop` (формат строки поиска), `test_webapp_nav_disclosure_ui` (memory-вкладки 5≠3), `test_webapp_status_control` (множества ключей статуса), `test_mca09_intents_block_e` (`'implemented' != 'disabled'`).
  - **5-й failed:** `test_dream_worker::test_cluster_distilled_to_belief` — pollution-флейк семьи #121: в полном прогоне каскад `connection unrecoverable` от соседнего теста; изолированный перепрогон **1 passed in 2.86s**. Честно классифицирован как флейк нового имени (не входил в бриф-список), вынесен на Reviewer.
- js **62/62**; F8 `--check` **OK 523**; collect **12364/0 errors**; frontier **v33, 0 pending**; census: KS **85** / reason **280** / тулы **14** / каталог **523** / реестр **47** — все Δ-инварианты = 0 (санкции ADR-1028-24 D6).
- R17-скан диффа: SECRET_HITS=0, CHAT_ID_HITS=0.
- Окно (deployment.md §6): venv-прогоны сегментами G1 4305/1 + G2 3748/1 + G3 4306/3 (те же 4 pre-existing + betterstack real_302 средофлейк, изолированно зелёный); фокус mca-21 **335 passed**; пин-набор **326 passed**. Замечание: глобальный py (aiogram 3.29 < 3.31) даёт 8 артефакт-падений — лейнам предписан `.venv`.

**Прод (deployment.md §3/§5):** pull ff `e16be7e→6f062fa`, identity **4/4** байт-в-байт; gate D9 — чистая доставка обоих канонов (SNAPSHOT→CANON v6/v3, GATE_DRIFT=0, ручных правок нет); TH-5 — прод-БД читает новый канон (текст байт-равен коду, повтор после рестарта идентичен); `/healthz` 200 ×3, `/api/health` 200, unauth 401 ×2 (RBAC жив); журнал 414 строк: **ERR=0, CRIT=0, Traceback=0, locked=0**, `NRestarts=0`.
**Фон (Лейн A):** ERR-24h = 0; ERR-96h = 6 (LLM-клиент, до рестарта); Traceback-96h = 467 — повторяющиеся embed-ветки (`knn_source_empty`/`EmbeddingGroupCoolingDown`, job `paused_rate_limit`) — штатная пауза квоты graphrag, не падение фичи.

## п.4 — Архив: числа, прогресс, скорость, остаток (§21 `:1054`, источник — прод-метрики, D10)

Снапшот на 06–07.10.2026, процесс продолжается; полный проход ~2 млн **не требуется** для закрытия разработки (`:1060`).
- **Восстановление при чтении (работает):** `message_source_records` = **17837**, `mca_source_refs` = **16480**, `mca_provenance_status` = **16245**, `message_revisions` = **18082** (свежие записи сегодня), `mca_evidence_links` = **1039** (Лейн A №1/№2/№4).
- **Архивный проход (archive_sample): ещё не стартовал.** Контур доступен (`random_uses_background … available=[archive_sample, belief_review]` каждый сон-тик), но вероятностный выбор (p=0.05/тик) не выпал за 28 тиков наблюдения (`exploration_not_used`=28/28; биномиально правдоподобно, ожидание ≈1.4) — `mca_archive_coverage` = 0 строк, exploration-jobs в `task_jobs` отсутствуют. Это 🟡 ON-с-оговоркой, не молчаливое расхождение (Лейн A №2).
- **Производные данные ждут прохода:** `mca_episodes` = 0, `mca_stories` = 0 (таблицы созданы — №3/№14).
- **Скорость/оценка остатка:** неприменимы — проход ещё не выбирался; прогресс/ошибки видны (`mca_events` 13921, top-причина `exploration_not_used`), задания рестарт-устойчивы (2 чистых рестарта окна, идемпотентные миграции no-op — deployment.md §3/§5).

## п.5 — Витрина: что где смотреть (свод по матрице; §21 `:1054`)

- **«Статус»:** лента «Опыт» (mca-16), снапшот намерений §16.3 (mca-09), блок «Истории чата» + счётчики/лента/прогресс (mca-12), карточка «Источник случайности» — живая лента = журналу `mca_random_draws` (mca-10a/10b).
- **«Память»:** таблица историй (фильтры/поиск/пагинация, mca-12), таблица/карточка lessons (mca-16), SelfModel/behavior-rules (mca-18).
- **«Аналитика»:** карта процессов 47/47, детализация запуска, зависания/инциденты (mca-17c, единственный write `POST /api/oversight/jobs/{id}/action`), Run Inspector (coverage/L1/final, ASAP-4.x), execution-graph (A9).
- **Справка:** «Гайд по возможностям» (Г1, канон v3, 27590 зн.) и «Гайд по фичам бота» (Г2, канон v6, 9685 зн.) — доставлены 2.58.67, прод-БД читает новые каноны (TH-5); версии справки/матрица — T-5204 (27 строк), handoff T-5218.
- **Матрица покрытия наблюдаемостью:** база — реестр **47/47** процессов mca-17a + handoff mca-17c (`backlog:335`) + матрица T-5204 mca-21; сводка переиспользует их (вторая матрица с нуля не строилась — D14). Полные `mca_events` (13921) + агрегаты + `mca_incidents` (1) — Лейн A №15.
- **Скриншоты desktop/mobile и живые сценарии витрины** — материал live-приёмки владельца (T-5236/T-5199-чек-лист); раундом не имитировались (no-false-acceptance, `:1038`).

## п.6 — Trace/наблюдаемость (mca-17a/17c) + неактивность stub (§21 `:1055`)

- **Инфраструктура подтверждена прод-фактом:** единый журнал `mca_events` (13921, R17-маскирование), агрегаты, `mca_pipeline_runs` = 34 (`random.uses` 28× succeeded, `sleep.deep` succeeded), `mca_random_draws` = 28, incidents = 1; reason_code **280**; реестр процессов **47**; события с `pipeline_run_id` текут (Лейн A №10/№15/№16).
- **Примеры для trace-набора (привязка к реальным event ID — на live-приёмке T-5236):** удачная инициатива/закрытое намерение (гейт T-5045), корректное молчание (T-5045 silent-семантика), восстановление источника (T-5199), история (T-5175), ошибка инструмента (T-4961), **QRNG fallback — факт уже в журнале**: 28/28 draws `pseudorandom/python-random` c `random_fallback`-событиями и `last_fallback_reason='provider_unconfigured'` (Лейн A №12).
- **Применения 14.6–14.11:** единые координатор/очередь/RandomSource — 28× `random.uses` через единый вход; ровно одно решение на `package_run_id` (Q4-честность). Примеры выбора/результата — живой домен T-5065/T-4940.
- **Игровой stub mca-10c — неактивен (артефакт):** пробный вызов → `STUB_OUTCOME: not_implemented | game_stub_inactive | mca10c-v1`, без сетевых запросов и side effects; grep `mca_game_stub` — 0 регистраций (`stub_money_evidence.md`).
- **Деньги OFF (артефакт):** `MCA_MONEY_LIMITS_ENABLED` default False, в PG ключей money/spend нет, env 0 → effective OFF; учёт расходов (`llm_usage_events`) работает при отключённых лимитах (`stub_money_evidence.md`, Лейн A №17).

## п.7 — Cookies/profile и упаковка (§21 `:1056`)

В артефактах релизного раунда отдельный cookies/profile-отчёт **отсутствует**: окно не меняло упаковку/зависимости (единственная код-Δ `services/info_service.py` + docs/тесты — `deployment.md` §1–2), исключения из упаковки и намеренно не удалённое — не пересматривались. **Video paths: не проверялись** в этом окне (пункт набора §20.3/T-5229 — live-домен, имитация запрещена). Честный статус: «не проверялось в раунде» — без заявления о работоспособности.

## п.8 — Production manifest (§21 `:1057`; `deployment.md`)

- **Commit/время:** immutable `6f062fa` (push ff `3e3bdb7..6f062fa`), прод pull ff `e16be7e→6f062fa`, **2.58.66→2.58.67**, окно 06.10.2026 (~23:27 UTC VERIFIED), рестарты ×2.
- **Применённая схема:** SQLite **v33** — без изменений (миграции не вызывались, повтор no-op); PG DDL — нет; доставлен DML-канон гайдов v6/v3 (идемпотентные миграции `config_cache.py`).
- **Effective flags (свод Лейн A, 21/21 по живому runtime):** **14 🟢 ON** подтверждено; **4 🟡 ON-с-оговоркой** (№2 archive-проход не выпал за 28 тиков, №3 episodes 0, №6 intents 0, №14 stories 0 — материал появится с проходом); **3 🔴 RED** — №5 deep sleep, №12 quantum, №20 vision (детали в п.9). Деньги OFF, stub неактивен.
- **Provider availability:** базовая LLM — работает (summary 21 прогонов, factcheck 2 сегодня, ERR-24h=0); ANU — **blocked, `provider_unconfigured`** (ключей `keys.random_quantum_*` в PG нет, активации не было); vision-provider — **не настроен** (пустые model/url, ключа нет). Несуществующие credentials не включались.
- **Первые проверки:** healthz 200 ×3 (502→200 systemd-интервал — известный прецедент), api/health 200, unauth 401 ×2, TH-5 канон-сверка, GATE_DRIFT=0, журнал ERR=0/locked=0. **Ошибок при старте нет.**
- **Бэкап/откат:** `backups/pre_t5216_20261006_232333.db` — **1.32 GB, integrity_check ok, user_version=33, tables=120** (read-back из копии); soft — `POST /api/info/reset-canon` (prev-слепки в БД); cold — `git revert 6f062fa` → 2.58.66, БД совместима в обе стороны (DDL=0).
- **Инцидентальные замечания (Info, не блокёры):** прод-worktree DIRTY=13 (pre-existing, владельцу сверить `git status`), `backups/` root-owned (бэкап через /tmp + sudo mv), интерпретатор прода `/var/www/admin_bot/venv/bin/python` (deployment.md §7).

## п.9 — Оставшиеся ограничения — без «всё работает» (§21 `:1058`)

**3 🔴 RED effective-state (owner-gate, решения запрошены; раундом ничего не переключалось — CA-REL-4):**
1. **№5 Глубокий сон:** PG-global `flags.deep_sleep_enabled=false` (дефолт сида) при env `DEEP_SLEEP_ENABLED=true`; `chat#O` effective OFF (`deep_disabled`), `chat#G` — deep-контур работает (6×`sleep.deep` succeeded). Механизм здоров; нужно решение владельца: per-chat включение или санкция текущего состояния.
2. **№12 Квантовый источник (ANU):** `memory.random_source="quantum"` выбран, но **не активирован** — `activated_at=None`, `key_fingerprint=None`, `provider_unconfigured`; **28/28 draws = pseudorandom fallback**. Формулировка «квантовый режим работает» запрещена — состояние «интеграция не завершена/деградирована»; функции живут по явной fallback-политике. Требуется реальный ключ ANU + активация (гейт-прецедент T-4986).
3. **№20 Vision (MCA-19):** effective **OFF** по конфигурации — `flags.vision_enabled=false`, пустые `models.vision_*`, ключа нет; `mca_media_assets`=189, `mca_media_analyses`=0; воркер жив. «Запрошено ON» фактически не настроено — включение/настройка = санкция владельца.

**4 🟡 ON-с-оговоркой:** archive-проход/episodes/stories/intents — контуры активны, прикладных записей 0 (материал появится с проходом; intents — честный unknown, прецедент T-5045).

**Live-гейты PENDING OWNER — 9 + 1 (консолидированы, НЕ закрыты; закрытие — живая проверка владельцем):** T-4940 (mca-15, статистика/шутка≠отчёт, Round 10.36), T-5015 (mca-16, уроки, 10.39), T-5045 (mca-09, намерения, 10.40), T-5065 (mca-10b, применения случайности, 10.41), T-5095 (mca-18, черты, 10.42), T-5127 (mca-19, фото/OCR/auto-деактивация; в проде assets 83→189 / analyses 0), T-5151 (mca-20, фактчек дат), T-5175 (mca-12, витрина историй/правки CAS/409, 10.46), T-5199 (mca-17c, матрица/oversight-действия, 10.47) + **T-5217** (mca-21, live-TMA-приёмка гайдов — после доставки 2.58.67). Инструкции — `plans/backlog.md` Round 10.36–10.47 + чек-листы фич; раунд свёл их в один чек-лист (T-5236), имитации запрещены.

**Прочее честно:**
- §20.3-сценарии (direct reply, retrieval, video path, cookies/profile) — в раунде не исполнялись как живые пробы; health/smoke окна и runtime-сверка Лейн A выполнены, остальное — live-домен владельца (no-false-acceptance).
- **mca-18 TypeError legacy-парсера** — datetime-фикс вошёл попутно в пакет **2.58.64 `0db30a2`** (workflow_state); в свежем boot-логе 2.58.67 (`startup_prod_t5216.log`, 415 строк) TypeError/mca-18 записей **нет** (grep 0) — статус «мониторится на живом фоне».
- Traceback-96h = 467 — embed-rate-limit-контур graphrag (штатные паузы квоты, job `paused_rate_limit`); фоновый контур жив.
- Техдолг непрерывен в backlog (п.7-структура): 4 pre-existing identity (§121), pollution-семья флейков #121 (nostalgia, summary env-hang, mca09-cancelled, betterstack L-ASAP41-5, новый член — dream_worker, изолированно зелёный), L-A/L-B mca-20 (кешированные insufficient-вердикты; cache-hit без reason/as_of) и mca-17c (`_derive_status` cancelled; fail-open чтения), N-1…N-7 mca-17c (idempotency_key, ExecutionGraph-адаптер, ack read-only, cancel-докстринг, trigger-фильтр, опечатка spec, counts/keyset) — всё non-blocking, с диспозициями.

---

## Вердикт

**Программа MCA (MCA-01…MCA-22) реализована и задеплоена: прод 2.58.67 (`6f062fa`), v33/523/85/280/14/47, Δ-инварианты релиза = 0, финальное окно VERIFIED.** Все раунды 10.27–10.47 закрыты; effective-состояние 21/21 сверено по живому прод-runtime: 14 ON / 4 ON-с-оговоркой / 3 RED (deep sleep, ANU, vision — ждут решений владельца, ничего раундом не переключалось). **Живая приёмка — за владельцем** (9+1 консолидированный live-чек-лист T-5236). **Следующая фаза — ASAP 5** (директива владельца 07.10: сразу после закрытия всех MCA, без human gate; `current_task.md:27151+` — Summary Reliability / Cover Prompt Transparency / GraphRAG Recovery / Random source; read-only planning разрешён заранее).

Пройдено и закрыто: Review (T-5233 — **Approved**, `review.md`) → Scanner (T-5234 — **«к деплою ДА»**, C0/H0, `plans/reports/mcarelease_scanner_audit.md`) → release-маркер (T-5235, `deployment.md` VERIFIED 2.58.67) → **PM-close (T-5237 @PM 07.10.2026)**: merge §125, ADR-1028-24 → Accepted, metrics 10.48-RELEASE, backlog Round 10.48 (единый live-чек-лист), README, коммит/пуш, архивация `plans/archive/mca-release-round1048/`, handoff **ASAP 5**. По N-1 review: SHA `2d4e3ad` в п.1 верен, опечатки `2d4e9ad` в файле и в git-истории нет. **Программа MCA закрыта.**
