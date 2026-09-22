# evidence.md — S1 `summary-filter-round1026` (T-3129 @DevOps: baseline + точка отката)

> Статус: **DONE** · Дата: 2026-09-23 · HEAD `01f3c57` · ts `20260923-101108`
> Роль: @DevOps. Артефакты: annotated-тег + `git archive`-бэкап + `.env`-копия + baseline-прогоны. В git не коммитилось.

## 1. Точка отката (tag)

- `git rev-parse pre-round1026-s1` → **`10a5c74e577c5a2616e6387510ce68a753c85e6c`** (tag-object)
- `git rev-parse pre-round1026-s1^{commit}` → **`01f3c57ce69dd7566eaf2da8a2359bc5356fd015`**
- Push: `git push origin pre-round1026-s1` → `* [new tag] pre-round1026-s1 -> pre-round1026-s1`
- `git ls-remote --tags origin pre-round1026-s1` → `10a5c74e577c5a2616e6387510ce68a753c85e6c refs/tags/pre-round1026-s1` ✅

**Команда отката:**
```powershell
git fetch --tags origin
git reset --hard pre-round1026-s1     # -> 01f3c57
```

## 2. Бэкап из HEAD (`git archive`)

- Путь: **`var/backups/s1-round1026-20260923-101108/`**
- Состав (6 файлов + `BASELINE.md`): `config/settings.py`, `services/summary_generator.py`, `services/summary_memory.py`, `services/summary_xml.py`, `services/param_catalog.py`, `web/app.js`.
- Целостность: `git hash-object <файл>` == `git rev-parse HEAD:<path>` для всех 6 (blob-хеши в `BASELINE.md`). Расхождение SHA256 рабочего дерева — только `core.autocrlf=true` (CRLF), не контент.
- `.env.bak.round1026-s1`: размер **7131 = 7131**, SHA256 совпадает; содержимое не выводилось. Файл git-ignored (в `git status` не появляется).

## 3. Baseline

| Метрика | Значение |
|---|---|
| HEAD | `01f3c57` |
| APP_VERSION | `2.58.17` |
| pytest (`.venv\Scripts\python.exe`, **Python 3.12.0**) | **8463 passed / 0 failed** / 1 warning (105.14s) |
| JS (`node v24.16.0`) | **42/42** файлов `tests/js/*.js`; `node --check web/app.js` OK |
| `database is locked` (в прогоне pytest) | **0** |
| Δ DDL | **0** (diff — только `plans/*`; схема `user_version=12`) |
| Каталог | REGISTRY **459** / GROUPS **98** / `_TAB_BY_GROUP` **96** / TAB_RULES **21** / Settings **418** / categorized **434** |

## 4. R18 / гигиена

- Теги, бэкапы и `stash@{0}` (`On master: wip(f1): IA v2 round1025 …`) **не удалялись**.
- В git ничего не коммитилось; `deploy_commands.txt` не трогался.
- Секреты в отчётах/логах не публикуются (значения `.env`/хешей не раскрываются).

## Handoff
**RESULT: DONE (baseline + откат зафиксированы) @Orchestrator** — тег `pre-round1026-s1` (`10a5c74`→`01f3c57`) запушен; бэкап `var/backups/s1-round1026-20260923-101108/`; baseline pytest 8463/0, JS 42/42, lock=0, ΔDDL=0, каталог 459/98/96/21/418; `stash@{0}` сохранён. Деплой S1 — не в этой задаче (T-3157); точка отката готова для фаз A–G.

---

# evidence.md — S1 Step 4 @Builder (T-3132…T-3150)

> Статус: **DONE (реализация)** · Дата: 2026-09-23 · Базис: `01f3c57` (рабочее дерево) ·
> Решения: **ADR-1026-1 D1–D7**. Роль: @Builder. В git НЕ коммитилось.

## 1. Реализовано по блокам

- **A (ядро, T-3132…T-3136):** `services/summary_filter.py` — чистый модуль:
  `score_message` (0..4, ≤1 балл/критерий), `filter_window` (порог + индексы +
  всплеск + fail-open + forced-keep), `estimate_and_split` (§93).
  `children_by_tg` индексируется по **`tg_message_id`**; бот (`user_id==bot_id`) →
  score 0; детерминизм (сортировка по `(timestamp,id)`, без системных часов);
  `== порога` → сохранить; `min_weight>4` → клэмп до 4; `dropped` — полные строки.
- **B (каталог/UI, T-3137…T-3140):** `config/settings.py` +8 полей
  (`SUMMARY_FILTER_*`); `services/param_catalog.py` +8 записей, +2 группы
  (`flags_summary_filter`/`limits_summary_filter`) на вкладке `mod_summary`;
  `web/app.js` — группы на workspace-вкладке «Подготовка сообщений» (Δ каталога JS=0);
  `web/index.html` — prep рендерит generic-сетку, placeholder остаётся для
  clusterizer/writer.
- **C (§93, T-3141…T-3143):** токен/чаровая оценка по существующим потолкам,
  перекрывающиеся фрагменты (`overlap=1`, последний всегда заканчивается последним
  `kept`), дедуп/связи по `id`/`reply_to_id`/`tg_message_id`; контракт `fragments`
  для S3.
- **D (интеграция, T-3144…T-3146):** врезка `SummaryGenerator._apply_filter`
  строго между `get_window_messages` и `xml.build`; фильтруется **только XML-история**
  (`xml_rows`), RAG/память/graph/memorize — на исходных `rows`; 0 LLM-вызовов
  (2-вызовность System-2 сохранена); публикация не тронута; fail-open + OFF
  (байт-в-байт `xml.build(rows)`).
- **E (логи/run_id, T-3147…T-3148):** аддитивные `FILTER_START`/`FILTER_COMPLETE`/
  `FILTER_ERROR` (+`FILTER_EMPTY_FALLBACK`) с полями §109 и `run_id=correlation_id`;
  R17/R18 (только числа/коды/id); метрики в `self._filter_metrics` (для S8, без узлов
  ExecutionGraph).
- **F (тесты, T-3149…T-3150):** новый `tests/test_summary_filter.py` — **31 тест**
  (критерии, границы, бот, всплеск, детерминизм, fail-open, фрагменты).

## 2. Фактические числа каталога после Δ (санкция D1)

| Метрика | До | После | Ожидание D1 |
|---|---|---|---|
| REGISTRY | 459 | **467** | 467 ✅ |
| Settings (dataclass.fields) | 418 | **426** | 426 ✅ |
| categorized | 434 | **442** | 442 ✅ |
| GROUPS | 98 | **100** | 100 ✅ |
| `_TAB_BY_GROUP` | 96 | **98** | 98 ✅ |
| TAB_RULES | 21 | **21** | 21 (без изм.) ✅ |

Проверено импортом `services/param_catalog` (не только тестом). Категорийно:
flags 67→69, limits 192→198; порядки групп уникальны. `per_chat` — все 8 ключей.

## 3. Δ DDL / публикация / промпты

- **Δ DDL = 0:** diff по `services/database.py`, `services/pg_db.py`,
  `services/summary_memory.py` — пуст; новых таблиц/колонок нет.
- **Публикация не тронута:** diff по `services/image_generation.py`,
  `services/telegram_send.py`, `web/api/routes.py` — пуст; в diff
  `services/summary_generator.py` нет изменений `_deliver_rich/_deliver_plain/
  generate_image/build_cover_media/send_rich_message/send_text`.
- **Промпты не тронуты:** `services/summary_prompts.py` вне diff.

## 4. Прогоны

| Проверка | Команда | Результат |
|---|---|---|
| pytest (полный) | `.venv\Scripts\python.exe -m pytest -q` | **8494 passed / 0 failed** (было 8463; +31 новых) |
| JS-синтаксис | `node --check web/app.js` | OK |
| JS-тесты | `node tests/js/*.js` (42 файла) | **42/42** |
| git hygiene | `git diff --check` | exit 0 (только CRLF-предупреждения) |

## 5. Baseline-числа в тестах (атомарно)

Обновлены count/version-инварианты в 39 файлах `tests/**` (459→467, 418→426,
434→442, 98→100, 96→98, 2.58.17→2.58.18); состав вкладки `mod_summary` в
`test_frontend_tab_mapping`. Список — в `git diff --stat`.

## 6. ⚠️ Санкционированная суперсессия round1025 F8 (требует подтверждения @Architect)

Δ каталога структурно конфликтует с **замороженным аудитом round1025 F8**
(`tests/test_round1025_f8_registry.py`, `tests/test_ia_inventory_round1025.py`,
фикстуры `tests/fixtures/round1025/*.json`, артефакты `plans/docs/*-round1025.*`):
sha256-байтфриз `param_catalog.py`, TSV/screen-map, `delta=48`, counts 459/98/96/21.

Выполнено (минимальная суперсессия под санкцию D1, по образцу `ROUTES_SHA256_F11`):
- перегенерированы 3 артефакта (`tools/gen_param_registry_round1025.py`);
  зашитые «459» в генераторе заменены на динамические;
- обновлены фикстуры `catalog_baseline.json` (множества + counts) и
  `f8_baseline.json` (counts 467/100/98/21, delta 56, sha256 `param_catalog.py`,
  заметка `superseded_by`; `app_version` оставлен историческим 2.58.15);
- обновлены ассерты F8 (467/56, meta-provenance, APP_VERSION).
**Причина:** каталог-артефакты по определению — зеркало текущего каталога; оставить
их на 459 = исказить состояние. **Запрос:** подтвердить суперсессию (или вернуть
решение о переносе round1025 F8 в архив) на Step 5 @Reviewer / аудите @Scanner.

## 7. Не удалось / ограничения

- **T-3151 (браузерный UI/E2E)** не выполнен: нет запущенного стенда/Playwright в
  этой задаче. Покрыто статическими JS-тестами (F5 workspace/coverage — 42/42) и
  Python-инвариантами; сетевые перехваты — на этапе приёмки (см.
  `plans/reports/round1026_s1_ui.md`).
- Эвристика «адресного упоминания» — по тексту (`@token`), т.к. в строке окна нет
  поля `mentions`; `reply_to_id` — основной сигнал (ограничение зафиксировано в D4).
- Плотность всплеска считается по всем строкам окна; из членства `burst_ids`
  бот-сообщения исключены (литеральное чтение §7 + §91).

## Handoff
**RESULT: DONE (реализация T-3132…T-3150) @Orchestrator** — каталог 467/426/442/100/98/21;
pytest 8494/0, JS 42/42, Δ DDL=0, публикация/промпты вне diff; **требует независимой
верификации** (@Reviewer T-3152, @Scanner T-3153) и подтверждения суперсессии round1025 F8 (раздел 6).

---

# evidence.md — S1 Step 5b @Builder (rework по S1-ревью, T-3160 + Lows)

> Статус: **DONE (rework)** · Дата: 2026-09-23 · Базис: `01f3c57` (рабочее дерево) ·
> Решения: **review.md M-1/B-1**, **spec.md §6.1**, **ADR-1026-2**. Роль: @Builder.
> В git НЕ коммитилось/не деплоилось.

## R1. Что исправлено

- **T-3160 (M-1) — мастер-тумблер per-chat.** `services/summary_generator.py::_run`
  (`:342-350`): глобальное `hot.get("flags.summary_filter_enabled", …)` заменено на
  `bool(await _chat_limit(chat_id, "flags.summary_filter_enabled", hot.get(...)))` —
  симметрично `flags.summary_filter_reply_context_enabled` (`:507-510`). **spec/каталог
  не тронуты** (по §6.1). Следствие: OFF, выставленный per-chat, применяется; чат A ≠ чат B.
- **L-R1026S1-1 — sentinel-нормализация потолка токенов.** `_apply_filter` (`:512-521`):
  сырой `token_limit` прогоняется через `resolve_context_tokens(..., _SUMMARY_CONTEXT_TOKEN_DEFAULT)`
  (`0`/`None` → дефолт, `-1` → потолок «безлимита»); введена константа
  `_SUMMARY_CONTEXT_TOKEN_DEFAULT = 30000` (тем же значением заменён литерал в `_run`).
  Бюджет/нарезка §93 больше не вырождаются при per-chat override.
- **B-1 (High, governance) — код НЕ менялся.** Санкция ADR-1026-2 (AMEND ADR-1025-21 D6)
  уже оформлена @Architect; откат F8 не требуется.

## R2. Изменённые файлы

- `services/summary_generator.py` — per-chat тумблер + нормализация токенов (+импорт
  `resolve_context_tokens`, +константа).
- `tests/test_summary_filter_integration.py` — **новый** (7 тестов): T-3160 per-chat
  (A ON ≠ B OFF; OFF → исходный вход), L-1 (ON: XML=`kept`/RAG=`rows`, fail-open, ровно
  2 LLM-вызова), L-R1026S1-1 (`0`→дефолт, `-1`→безлимит).
- `plans/archive/summary-filter-round1026/tasks.md` (T-3160 `[x]`), `evidence.md`.
- **Не менялись:** `services/summary_filter.py`, `services/param_catalog.py`,
  `config/settings.py`, spec/ADR/каталог/JS/UI.

## R3. Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`, Py 3.12.0) | `.venv\Scripts\python.exe -m pytest -q` | **8501 passed / 0 failed** / 1 warning (108.34s) — было 8494; **+7** новых |
| Новый интеграционный набор | `pytest tests/test_summary_filter_integration.py` | **7 passed** |
| Юнит-матрица фильтра | `pytest tests/test_summary_filter.py` | **31 passed** |
| Саммари/хотфиксы/врезка | `pytest test_summary_generator test_hotfix3 test_hotfix4 test_summary_xml test_104_backend_additions` | **191 passed** |
| Каталог/F8/IA/tab | `pytest test_param_catalog test_round1025_f8_registry test_ia_inventory_round1025 test_frontend_tab_mapping` | **108 passed** |
| JS-синтаксис / JS-набор | `node --check web/app.js`; пофайлово `tests/js/*.js` | OK; **42/42** (exit 0 каждого) |
| `git diff --check` | — | exit 0 (только CRLF-предупреждения) |
| Каталог (импорт) | `len(REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES)` | **467 / 100 / 98 / 21** = санкция (Δ не менялся) |
| Δ DDL | `git diff --stat` по `database.py`/`pg_db.py`/`summary_memory.py` | **пусто** (Δ=0) |
| Публикация/промпты | `git diff --stat` по `image_generation.py`/`telegram_send.py`/`routes.py`/`summary_prompts.py` | **пусто**; в diff `summary_generator.py` нет `_deliver_*`/`generate_image`/`build_cover_media`/`send_rich_message`/`send_text` |

**Покрытые сценарии:** SC-02 (RAG на исходных `rows`), SC-03 (OFF байт-в-байт + hot),
SC-05 (чат A ≠ чат B), SC-11/SC-12 (бюджет/нарезка не вырождаются), инвариант §12.2
(ровно 2 LLM-вызова). Маркер-тесты не ослаблялись (только +1 новый файл).

## R4. Ограничения

- Live/браузерный E2E (T-3151) — по-прежнему вне окружения; **PENDING OWNER VERIFICATION (D4)**.
- Повторное независимое ревью (T-3152/T-3154) — **не выполнено** (запрошено через @Orchestrator).

## Handoff
**RESULT: DONE (rework M-1 + L-1/L-R1026S1-1) @Orchestrator** — per-chat тумблер
(`_chat_limit`) + нормализация токенов; +7 интеграционных тестов (per-chat/OFF-байт-в-байт/
RAG-на-исходных/fail-open/2 LLM); pytest **8501/0**, JS 42/42, `git diff --check`=0, Δ DDL=0,
каталог 467/100/98/21 (санкция, не тронут), публикация/промпты вне diff. B-1 закрыт ADR-1026-2
(код не менялся). **Требует повторной независимой верификации** (@Reviewer T-3152/T-3154).
