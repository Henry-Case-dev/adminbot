# ASAP 5 — Integration Evidence (T-5270, lane B4)

Барьер-отчёт свода трёх лейн (B1-summary / B2-cover / B3-graphrag+random),
пин-фиксы, финальная верификация, Δ-сверка с санкциями §1.2.14.

Дата: 07.10.2026 · Окружение: Windows/PowerShell, `.venv`, `PYTHONIOENCODING=utf-8`.
База: HEAD `e9d71c8` (mca-release 10.48, прод 2.58.67).

---

## 1. Свод лейн

| Лейн | Скоуп | Артефакты |
|------|-------|-----------|
| B1-summary | L1-семантика, L2-таксономия, gate/fingerprint, HYBRID_DEGRADED_PUBLISHED, Decision Trace | `summary_generator.py`, `summary_l2_review.py`, `pipeline_analytics.py`, `test_asap5_summary_domain.py`, `tests/js/asap5_decision_trace_test.js` |
| B2-cover | SERIALIZE-1 (cover_prompt_assembly + shim), CoverPromptManifest, STORY-minimum, minimal удалён, AST-пин | `cover_prompt_assembly.py` (new), `image_prompt_compiler.py`, cover-стили, `test_asap5_cover_prompt_manifest.py`, `test_asap44_cover_final_closure.py` |
| B3-graphrag+random | future-resume (тик 900с), identity+cosine-canary, generation-isolated storage, bootstrap configured=false, парадигмы gate≠last-attempt (классы A/B/C), semantic zoom | `graphrag_rebuild.py`, `embedding_control_plane.py`, `summary_memory.py`, `database.py`, `mca_random_source.py`, каталог +6, `test_asap5_embedding_identity.py`, `test_asap5_graphrag_recovery.py`, `test_asap5_paradigms_diagnostics.py`, `test_asap5_random_bootstrap_config.py` |

Снапшоты лейн: `b3_hashes.json` (конец B3), хеши B1 — в её evidence-секции.
Дрейф `b3_hashes.json` по `web/app.js`/`web/index.html` — ожидаемо: B2 менял
shell после B3-снапшота; `b3_hashes.json` — точечный снапшот, не инвариант.
Финальные хеши интегрированного кандидата — `t5270_candidate_hashes.json`
(143 файла, SHA256).

---

## 2. Census — Δ-сверка с санкциями §1.2.14

Все замеры импортом (`.venv`), независимо от тестов:

| Инвариант | Санкция §1.2.14 | Факт | Вердикт |
|-----------|-----------------|------|---------|
| DDL | 0 (v33) | `PRAGMA user_version` = 33 (свежая :memory: БД) | ✅ =0 |
| Каталог | 523→**529** (+6 embedding, B3) | `len(pc.REGISTRY)` = 529; F8 `--check` EXIT=0 (delta 118, meta актуален, test pins synced 0) | ✅ =529 |
| KS | 85 (=85) | `len(mca_gates.KILL_SWITCHES)` = 85 | ✅ =85 |
| reason | 280 (=280; +1 oversight — mca-17c, уже в проде) | `len(mca_events.REASON_CODES)` = 280 | ✅ =280 |
| Тулы | 14 (=14) | `len(TOOL_CALLING_TOOLS)` = 14 | ✅ =14 |
| Реестр/widget | 47 (=47) | `len(PROCESS_REGISTRY)` = 47, уникальных process_id = 47 | ✅ =47 |
| routes.py | byte-freeze пин цел | SHA256 = `8153b8bd…c7b45` = `ROUTES_SHA256_F11` (байт-в-байт) | ✅ цел |
| APP_VERSION | бамп 2.58.68 НЕ делать (DevOps) | 2.58.67 (=HEAD, прод; никто из лейн не бампал) | ✅ нет бампа |

NB: brief-упоминание «APP_VERSION 2.58.66» устарело после mca-release 10.48
(прод и HEAD = 2.58.67). Санкция «бамп не делать» соблюдена: 2.58.68 нет.

Сверка B1-утверждения «словарь reason не расширялся»: верно — 280 было уже
после mca-17c (`oversight_job_action` в проде), ASAP-5 новых кодов не добавил
(серийные коды L2 — stage-строки, не reason-коды, SERIALIZE-4 =0).

---

## 3. Пин-фикс mca01 write-points (единственный red-хвост интеграции)

**Симптом** (после свода B1+B2+B3): `test_mca01_tx_…::test_write_points_go_through_single_writer`
RED — дрейф allowlist.

**Замер** (тот же AST-алгоритм, что в тесте):

- `database.py`: found **191** vs allow 189 (+2 commit-вызова);
- `embedding_control_plane.py`: found **1**, в allowlist отсутствовал;
- `graphrag_rebuild.py` 3 / `summary_memory.py` 13 / остальные — без дрейфа
  (уже внесены B3 ранее);
- unguarded-сайты (2):
  - `database.py:5454` — `set_embedding_generation_status` (D12/13E
    transition-хелпер поколений);
  - `embedding_control_plane.py:2022` — `embedding_canary_check`
    (canary-эталоны в `embedding_cache`).

**Анализ** (почему пин-устаревание, а не дефект B3):
оба сайта — API миграционной машины embedding-поколений (ADR-1028-25), в
рантайме пока не вызываются ни одним прод-путём (только тесты B3);
оба fail-open (ошибка → False / stored=0); одиночные `execute+commit` без
rollback в сайте → риск «закоммитить полутранзакцию» теоретический
(миграционный воркер, тик 900с), целостность схем не нарушается.
Подпадает под прямую санкцию Orchestrator: «новые сайты B3-лейн в
миграционных/воркер-файлах — по прецеденту census-sweep [D-1]».

**Фикс** (в рамках WRITE_SCOPE, только тест):
1. allowlist: `"database.py": 189 → 191` (+2, коммент-санкция ADR-1028-25);
2. allowlist: + `"embedding_control_plane.py": 1` (коммент-санкция);
3. явный набор `sanctioned_b3` (file, function) для unguarded-проверки —
   по аналогии с `db_sanctioned`/`separate_connection`, с обоснованием;
   рост числа сайтов по-прежнему ловится сверкой `found == allow`.

**Результат:** `test_mca01_tx_task_supervisor_round1027.py` — **33/33 passed**.
Хеш пин-фикса: git `c10a151a740b1a9908da5f83b3a30c904cce3a92` (+22/−1).

**Advisory (related-nonblocking, не в этом slice):** при активации
future-resume воркера в рантайме — обернуть оба сайта в
`serialized()`/`write_transaction` (однострочные правки, прецедент
`activate_embedding_generation`). Кандидат в backlog.

---

## 4. Финальные прогоны

| Набор | Результат |
|-------|-----------|
| Фокус-пины: mca17c invariants + f8_registry + param_catalog | **71/71 passed** |
| mca01_tx (после пин-фикса) | **33/33 passed** |
| JS (node, все файлы tests/js) | **63/63** (62 базовых + `asap5_decision_trace_test` — базлайн B1) |
| `pytest --collect-only` | **12438 collected, 0 ошибок** |
| Полный pytest (foreground, venv, сегменты G1/G2/G3) | см. §4.1 |

### 4.1 Полный pytest

Полный набор: **12434 passed / 4 failed** (497 тест-файлов: сегменты
G1[a-e] 116 ф. / G2[f-m] 163 ф. / G3[n-z] 217 ф. + `test_104_backend_additions.py`
11 тестов; hang #121 не воспроизвёлся; лог: `full_pytest_t5270.log`).
Сходится с collect 12438 (12434+4).

Все 4 failed — поимённо документированные pre-existing identity:

1. `test_tool_loop.py::TestChatWithTools::test_query_chat_memory_count_reaches_model` (tool_loop)
2. `test_webapp_nav_disclosure_ui.py::…::test_memory_rag_and_sleep_tabs` (nav_disclosure)
3. `test_webapp_status_control.py::…::test_status_public_for_all_roles` (status_control)
4. `test_mca09_intents_block_e_round1040.py::test_registry_process_intent_initiative` (mca09-registry)

**Новых red от интеграции 3 лейн: 0.** mca01 write-points — зелёный после
пин-фикса (§3). mca09×2-средофлейки B1 (isolated re-run зелёные) сегодня в
полном прогоне не воспроизвелись отдельно от mca09-registry-identity.

---

## 5. R17 — скан секретов по дельте

- Скан: 129 файлов дельты (services/web/tests/tools), 7 паттернов
  (sk-/xox/ghp/AIza/TG-token/literal-assign/DB-URL) —
  `tools/_t5270_r17_scan.py`.
- Хиты: 28 — **все в `tests/`**, **все — синтетические фикстуры-ловушки**
  анти-лифик-тестов (`sk-SYNTHETIC-ABCD`, `СЕКРЕТ_R17_НЕ_ДОЛЖЕН_БЫТЬ_В_ЛОГАХ`,
  `sk-SUPER-SECRET-LEAK-123` — текст сам декларирует назначение).
- Сверка с HEAD: **0 секрет-строк реально добавлено дельтой**
  (единственный кандидат — перемещение идентичной `_SECRET`-строки в
  `test_summary_deploy_round1026.py`).
- Продуктовые файлы (services/web): **0 хитов**.

**Вердикт R17: SECRET_HITS (новые) = 0.**

---

## 6. Гигиена индекса

Ожидаемое содержимое коммита ASAP 5 (домен PM): код 3 лейн + их тесты/фикстуры
+ **пин-фикс T-5270** (`tests/test_mca01_tx_task_supervisor_round1027.py`)
+ evidence-пакет `plans/features/asap5-final-fixes/` (вкл. этот файл,
`t5270_candidate_hashes.json`, `full_pytest_t5270.log`).
Untracked-мусор (`.playwright-mcp/`, `node_modules/`, `package*.json`,
`AGENTS.md`, `tools/_d2_*/_mca17c_*/…`, `plans/verification_cache.json`,
`deploy_commands.txt`, `plans/current_task.md`) — НЕ включать (R17, прецедент
10.47/10.48). Правки `plans/workflow_state.md`/`plans/MEMORY.md`/backlog —
чужой WIP, вне кандидата.

---

## 7. Вердикт

**Интеграция целостна — барьер ASAP 5 пройден.**

- Δ-инварианты: все = санкциям §1.2.14 (DDL 0/v33; каталог 529 — санкция +6;
  KS 85; reason 280; тулы 14; реестр 47; routes-пин байт-в-байт; APP_VERSION
  без бампа — 2.58.68 не делали).
- Единственный интеграционный red (mca01 write-points) устранён
  санкционированным пин-фиксом (census-sweep D-1); тест 33/33.
- Полный pytest: 12434/4 — ровно 4 документированных pre-existing, новых
  red 0; JS 63/63; F8 EXIT=0; collect 12438/0 ошибок; R17: новых секретов 0.
- Гигиена индекса: изменения T-5270 — только пин-фикс теста mca01 +
  evidence-пакет + инструменты сверки (`tools/_t5270_*`); коды лейн не тронуты.

**Готов к независимым ревью/скану ASAP 5 (параллельным), затем деплой
2.58.68 (@DevOps).**

Incidental (related-nonblocking, backlog при активации future-resume
воркера): обернуть `set_embedding_generation_status` (database.py:5454) и
`embedding_canary_check` (embedding_control_plane.py:2022) в
`serialized()`/`write_transaction` — см. §3 Advisory.
