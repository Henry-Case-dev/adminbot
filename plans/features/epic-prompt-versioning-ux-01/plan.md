# EPIC-PROMPT-VERSIONING-UX-01 — карта текущего состояния, размещение в очереди, план срезов

- Источник: `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md` (113 строк, sha 893621D8; фрагмент `plans/current_task.md:5535-5647`).
- Карта требований: `requirements-map.json` (63 инвентарные строки + 13 прозаических = 57 обязательных, все `PENDING`, доказательств нет).
- Граф срезов: `slice-graph.json` (8 срезов, волны W0–W6).
- База: ветка `evol/impl`, HEAD `bce5e781` (после merge релиза 2.58.153 / `e9d4b100`). Тексты промптов в этом пакете не меняются.
- План гейта: `check --stage plan` → `inventory=63 manual=13 errors=0`, EXIT 0.

---

## 1. Реальная карта: редактируемые поля промптов в админке (HEAD bce5e781)

### 1.1. Счётчики

| Категория | Значение |
|---|---|
| Блоков в `prompt_registry` | **112** |
| PG-управляемых блоков (`pg_key` есть) | **39** блоков / **38** уникальных `pg_key` (`character.core` общий для `core.personality` и `core.personality.compact`) |
| Редактируемых текстовых значений, показанных в UI | **38** |
| `code-only` блоков (без `pg_key`) | **73** — read-only в каталоге, кнопки включения запрещены |
| Заводских печатей | **111** (`FACTORY_REVISION_SEALS`), `seal_integrity()` пуст |

### 1.2. Где живут редактируемые поля

| # | Хост UI | Файл/маркер | Что редактируется |
|---|---|---|---|
| A | Раздел «Промпты» (общий редактор) | `web/index.html` ~4117–4340 (`data-prompt-editor`, `data-prompt-textarea`, `data-prompt-history`) + `web/app.js` `workspacePromptFocus` (4975), `loadPromptHistory` (19620), `activatePromptRevision` (19740) | 26 текстовых `prompts.*` из общего каталога `GET /api/config` (category `prompts`) |
| B | Карточки модулей | `web/index.html` ~4967 (`:data-cfg-key="item.key"`, textarea + опциональный preview) | те же `prompts.*`, показанные в контексте модуля (Summary/Direct/FactCheck/Memory/Web/YouTube/Search) |
| C | Раздел «Инициатива → Мемы» | `web/index.html` ~2131/2169 (`v-model="memeDraft.prompt_joke"/"prompt_image"`), `web/app.js` `initiativePromptReset` (12992), `saveMemeSettings` (~13159) | `prompts.meme_joke`, `prompts.meme_image` (те же блоки, что в A/B, но собственный экран и собственный endpoint) |
| D | Speech/Character → «Все инструкции» | `web/index.html` ~12449–12570 (`data-speech-block-detail`), `web/app.js` `saveSpeechBlock` (28736) | все 39 PG-блоков, включая `character.core` (`full_text`/`compact_text`), `style.policy.hint`, `content.image_failure.*` (8), `content.image_request_clarify`; 73 code-only показываются read-only |

### 1.3. Полный перечень 28 ключей категории `prompts` (UI-каталог)

| Семейство | `pg_key` (`block_id`) | Виджет/стадия | Показ |
|---|---|---|---|
| checkup | `prompts.checkup_system_prompt` (`checkup.base.system`) | text | A, B |
| memory | `prompts.compress_system_prompt` (`memory.compress`), `prompts.extract_system_prompt` (`memory.extract`) | text | A, B |
| direct | `prompts.direct_chat_system_prompt` (`direct.base.tool_phase`, global_chat), `prompts.direct_chat_synthesizer_system_prompt` (synthesizer), `prompts.direct_chat_verbalizer_system_prompt` (verbalizer), `prompts.direct_l1_planner_system_prompt` (synthesizer), `prompts.verbilizer_mode_casual`, `prompts.verbilizer_mode_deep_research`, `prompts.verbilizer_mode_serious` | text | A, B |
| direct | `prompts.verbilizer_default_mode` (`verbilizer.mode.default`) | **select** (имя режима, не текст) | A, B |
| factcheck | `prompts.factcheck_system_prompt`, `prompts.factcheck_analyst_system_prompt` (synthesizer), `prompts.factcheck_verbalizer_system_prompt` (verbalizer), `prompts.factcheck_critique_directive` (verbalizer; registry `scope=code`) | text | A, B |
| initiative | `prompts.meme_joke`, `prompts.meme_image` (registry `scope=code`, но `pg_key` есть) | text | A, B, **C** |
| search | `prompts.search_system_prompt` | text | A, B |
| summary | `prompts.summary_system_prompt`, `prompts.summary_editor_system_prompt` (synthesizer), `prompts.summary_l1_clusterizer_system_prompt`, `prompts.summary_l2_writer_system_prompt`, `prompts.summary_narrator_system_prompt` (verbalizer) | text | A, B |
| summary | `prompts.summary_cover_style` (`summary.cover.style`) | text + server preview | A, B |
| summary | `prompts.summary_cover_style_id` (`summary.cover.style_id`) | **hidden** (не приходит в `GET /api/config`; пишется `POST /api/cover/select`) | — |
| web / youtube | `prompts.webpage_system_prompt`, `prompts.youtube_system_prompt`, `prompts.youtube_video_system_prompt` | text | A, B |

### 1.4. Вне категории `prompts` (только хост D)

`core.personality` / `core.personality.compact` (`character.core` → `full_text` / `compact_text`, `global_chat`), `style.policy.hint` (`style`, `global_chat`), `content.image_failure.delivery_failed|disabled|freq_limited|not_configured|quota_exhausted|temporarily_unavailable|unknown|unsupported`, `content.image_request_clarify`. Эти ключи отсутствуют в `param_catalog.REGISTRY`, поэтому в `GET /api/config` их нет — их читает/пишет только Speech-раздел.

### 1.5. `code-only` блоки (read-only, 73)

Крупные группы: `internal.*` (17), `identity.*` (3), `style.*` (12, кроме `style.policy.hint`), `humor.*` (7 + техники), `response.extent.*` (6), `genre.*` (4), `memory.chat_rag_rerank|fact_extract|fact_retry|memorize_compress`, `temporal.*` (3), `search.rerank`, `summary.l1.anchors|l2.reviewer|l2.reviser`, `direct.history_segment`, `image.*`/`cover.scene_verify`, `initiative.meme.summary`, `message.image_generation_fallback`, `message.smartmodule.*`, `message.checkup_fallback_notice`, `message.clarify_media_target`, `experience.humor_window.system`, `internal.experience.semantic`.

---

## 2. Все точки записи значения промпта и статус журнала

| # | Точка | Код | Что пишет | Журнал `prompt_revisions`/`prompt_activations` | Вердикт для §3 |
|---|---|---|---|---|---|
| 1 | `POST /api/config` (global) | `routes.py:666` → `_post_config_global:1251` | `prompts.*`/`content.*` в `bot_settings` через `cache.set_many` | `_prompt_record_saved_snapshots:3320` → `record_manual_activation` | **⚠** значение коммитится ДО журнала; сбой журнала только логируется → «сохранено без версии» (§3.2 нарушен) |
| 2 | `POST /api/config` (chat, `X-Chat-Id`) | `routes.py:666` → `_write_chat_overrides_with_retry:609` | per-chat `overrides` (CAS + один ретрай) | тот же helper, `scope=chat` | **⚠** две транзакции; ретрай — last-writer-wins на пересекающихся ключах |
| 3 | `POST /api/initiative/meme-settings` | `routes.py:4155` | `prompts.meme_joke`, `prompts.meme_image` (+ настройки мемов) через `_write_chat_overrides_with_retry` | **вызова нет** | **✗** полный обход журнала; пустая строка = снятие override без события |
| 4 | `DELETE /api/config/chat/{key}` (reset-to-inherit) | `routes.py:1073` | удаление override из `chat_params` | **вызова нет** | **✗** нет события и нет предварительной ревизии последнего своего текста (§3.4) |
| 5 | `POST /api/speech/block/{id}` | `speech.py:2620` → `pf.write_speech_value:465` | global → `write_versioned_value` (**атомарно**); chat → `chat_params` + `record_manual_activation` (**best-effort**); при недоступном журнале — legacy-запись **без журнала** | частично | **⚠/✗** chat-ветка неатомарна; fallback без журнала запрещён §3.2 |
| 6 | `POST /api/speech/block/{id}/reset` `mode=factory` | `speech.py:2692` → `pf.apply_factory_reset:390` | значение пишется первым, затем `record_manual_activation` | best-effort | **✗** |
| 7 | `POST /api/speech/block/{id}/reset` `mode=chat` | `speech.py:2710` → `pf.reset_chat_override:693` | удаление override | **вызова нет** | **✗** как №4 |
| 8 | `POST /api/speech/block/{id}/rollback` | `speech.py:2754` → `pf.write_speech_value` | откат по `sha256_12` из **bounded legacy** `character.prompt_history` | как №5 | **⚠** откат идёт не по `revision_id` PG-журнала |
| 9 | `POST /api/speech/core/meta` | `speech.py:2822` | только doc-поля `detail_level`/`enabled`, не текст | не нужен | **OK** (не промпт-текст) |
| 10 | `POST /api/prompts/{key}/activate` | `routes.py:3569` → `activate_revision` | активный указатель + значение | **атомарно** | **⚠** для мемов `_prompt_list_scope` берёт `spec.scope=code` → история/активация ищутся в scope `code`, а записи идут в `global`/`chat` → рассинхрон |
| 11 | `POST /api/cover/select` | `cover_styles.py:629` | hidden `prompts.summary_cover_style_id` в `chat_params` | нет | **OK по смыслу** (селектор, не текст), но поле в реестре есть |
| 12 | Старт бота → `migrate_prompt_canons` | `bot.py:1388` → `prp.apply_release:932` | заводская ревизия поверх активного текста | атомарно | **✗ для §4**: нет owner pin, новая метка перекрывает ручной текст, а chat-override снимается (`remove_chat_override`) |
| 13 | `prompt_factory.restore_backup` (CLI) | `prompt_factory.py:829` | `cache.set` по каждой строке + `record_manual_activation` | best-effort | **⚠** технический путь |
| 14 | `prompt_migrations.normalize_legacy_speech` / `rollback_legacy_speech` | `prompt_migrations.py:1092/1184` | `cache.set_many` без журнала | нет | **✗ дормантный**: маршрутов/CLI нет, вызывается только тестами |

Итого: **14 точек**, из них журнал полностью обходят **4** (№3, №4, №7, №14), пишут значение раньше журнала/с best-effort — **5** (№1, №2, №5, №6, №13), атомарны — **3** (№10, №12, global-ветка №5). Ни одна точка не реализует owner pin (№12 его нарушает).

---

## 3. Расхождения `docs/prompt-versioning-contract.md` с кодом

1. §7 «`prompt_factory.py` — `list_versions`, `diff_revisions`, `get_revision_source`»: фактически это тонкие обёртки (`prompt_factory.py:1048-1069`), реализация — `prompt_release_policy.py`.
2. §3 таблица релиза: «деплой, метка новее → заводской текст активируется автоматически, **поверх ручных правок**» — прямо противоречит §4 пакета (owner baseline/pin). Требуется изменить и код (`_apply_scope_release`), и таблицу.
3. §3 «запись и активация — одной транзакцией под advisory-локом»: верно только для `write_versioned_value`/`activate_revision`/`apply_release`. Для `POST /api/config`, `meme-settings`, speech chat/reset — неверно (см. §2 выше). Документ описывает один корректный путь, а фактических путей записи несколько.
4. §5 аудит: `tests/test_evol018_prompt_audit.py` проверяет только модульные константы в `services/` и `handlers/`. Нет проверки `pg_key ↔ block_id ↔ UI-editor ↔ versioned write` и нет негативного теста на специализированный POST без журнала — это ровно то, что требует §5 пакета.
5. §7 свидетельство устарело: «99 блоков, 98 печатей, аудит 50/50»; сейчас **112** блоков, **111** печатей, **39** PG-управляемых, **73** code-only.
6. §4 «устаревший per-chat override снимается с эффективного пути» (`remove_chat_override`) — при owner pin это недопустимо: документ и код нужно согласовать с §4 пакета.
7. В контракте вообще нет owner baseline/pin, нет страниц истории и не отражён фактический лимит: `list_activations(..., limit=50)` (`prompt_release_policy.py:776`, `_LIST_ACTIVATIONS_SQL ... LIMIT $3`) — «полный список» сейчас физически обрезан 50 активациями.
8. Второй, отдельный и ограниченный UI истории: Speech-раздел показывает `prompt_factory.history_for` → `character.prompt_history` с `HISTORY_MAX_PER_BLOCK = 12` (`prompt_factory.py:71/278`), а не PG-журнал. Это одновременно нарушение §2 (один компонент) и §3.5 (без потолка).

Дополнительно (не в документе, но критично для реализации): у мемных блоков `block_id` объявлены со `scope="code"` при наличии `pg_key` (`initiative.meme.joke|image`), из-за чего `_prompt_list_scope` (`routes.py:3209`) открывает «историю» в scope `code`, а значения живут в `global`/`chat`.

---

## 4. Размещение в очереди (параллельность)

### 4.1. Файлы пакета vs активные лейны

| Лейн | Файлы в работе | Пересечение с пакетом |
|---|---|---|
| RC v5, lane A (`rc/context-seam`, worktree `rc-v5-316e33ec97ab-3d0f9e7d`) | `config/settings.py`, `services/canonical_context.py`, `services/media_marker.py`, `services/thread_chain.py`, `tests/test_evol_reply_context_integrity_seam.py` | **нет** |
| RC v5, lane B (`rc/factcheck`, worktree `evol-reply-context-integrity-0-84cd1fcc8bd6-fcfd5fc6`) | `handlers/factcheck.py`, `services/factcheck_service.py`, `factcheck_orchestrator.py`, `factcheck_planner.py`, `factcheck_renderer.py`, `factcheck_suitability.py`, `temporal_factcheck.py`, `tool_router.py` + тесты | **нет** |
| EPIC-PROMPT-VERSIONING-UX-01 | `services/prompt_release_policy.py`, `prompt_factory.py`, `prompt_registry.py`, `web/api/routes.py`, `web/api/speech.py`, `web/app.js`, `web/index.html`, `web/static/app.css`, `docs/prompt-versioning-contract.md`, `AGENTS.md`, `tests/test_prompt_*` | — |

Пересечений с обоими активными лейнами нет → **backend-волна (S1) может стартовать сейчас**.

### 4.2. Ограничения, которые нельзя игнорировать

1. **`services/prompt_composer.py`, `services/direct_chat_service.py`, `services/meme_initiative.py` принадлежат RC v5 волнам B/C** (`RC-SPEECH-BOUNDARY`, `RC-DIRECT-SELFCORR` — ещё не начаты). Наш пакет их **не трогает**: формулировка `{joke}` — только UI (`web/app.js`/`index.html`), текст мемов не меняется. Если для versioned-слоя понадобится правка `prompt_composer.py` — она откладывается до merge `RC-SPEECH-BOUNDARY`.
2. **`web/app.js` / `web/index.html` / `web/static/app.css` — один писатель.** Это файлы EPIC-CM-VISUAL-01 (CMV-A/B/D, `slice-graph.json` → `p1_barrier`, `applies_to: CMV-A-INTEGRATION, CMV-B-SCENE-PHYSICS, CMV-D-FULLSCREEN-INSPECTOR`). При этом `plans/features/epic-cm-visual-01/merge-barrier.md`, на который ссылается барьер, **в репозитории ещё отсутствует** — фиксация барьера открыта.
3. **P1 (`hotfix-meme-publication-initiative-ui`) уже выложен** (release/2.58.153, merge `e9d4b100`) и присутствует на нашей базе `bce5e781`. Поэтому пункт «P1 должен быть влит до UI-волны» выполнен, а наша UI-правка мемной страницы обязана строиться на существующей разметке P1 (`data-meme-settings`, `memeDraft`), а не перекомпоновывать её.
4. `config/settings.py` занят лейном A — пакет не вводит новых флагов, поэтому файл не нужен.

### 4.3. Рекомендация (жёстко)

- **Волна 0 + волна 1 — стартует немедленно, риск = 0 по файлам:** `PVR-S0-GUARD` (только `plans/.../evidence/baseline/`, read-only снимок значений и хешей) и сразу за ней `PVR-S1-WRITE` (backend-only: `prompt_release_policy.py`, `prompt_factory.py`, `web/api/routes.py`, `web/api/speech.py`, новый тест). UI, тексты промптов, `prompt_composer`, `meme_initiative` не затрагиваются.
- **Волна 2 — параллельно 2 лейна:** `PVR-S2-BASELINE` (backend, тот же файл политики) ∥ `PVR-S5-STD-DOC` (`docs/prompt-versioning-contract.md`, `AGENTS.md` — файлы, свободные от всех лейнов).
- **Волна 3:** `PVR-S3-HISTORY` — только после S2 (общий `services/prompt_release_policy.py`, осознанная последовательная стыковка).
- **Волна 4 — UI (`PVR-S4-UX`): ждёт S3 и освобождения UI-линии.** Правило сериализации: `web/app.js|index.html|static/app.css` правит одновременно только один агент; CMV-A/B/D не начинают, пока S4 не влит в `evol/impl`, либо S4 ждёт завершения CMV-A/B/D. Предпочтительный порядок — **S4 раньше CMV-A**: версия-UI является новым стандартом, и CMV пришлось бы переделывать те же карточки. Требуемое действие Orchestrator: записать это как дополнительное предусловие в `plans/features/epic-cm-visual-01/merge-barrier.md` (файл нужно создать — сейчас его нет).
- **Волна 5–6:** `PVR-S6-AUDIT` (после S4 и S5) → `PVR-S7-VERIFY` (Reviewer, после всех).

Одновременных писателей в пакете — максимум 2 (backend-лейн + docs-лейн); UI-волна всегда эксклюзивна.

---

## 5. Срезы и волны

| Срез | Волна | Зависит | Писатель | Смысл |
|---|---|---|---|---|
| `PVR-S0-GUARD` | W0 | — | Builder | Снимок-эталон значений/хешей, HEAD/deployed SHA, байтовая неизменность мемов |
| `PVR-S1-WRITE` | W1 | S0 | Builder | Атомарный `значение + ревизия + событие`, честный 503, закрытие 4 обходов, CAS/409, `skipped_same` |
| `PVR-S2-BASELINE` | W2 | S1 | Builder | Owner baseline как указатель, «Применить»/«Назначить»/«Восстановить»/«Снять», pin против factory-поставки, без автоназначения на миграции |
| `PVR-S5-STD-DOC` | W2 | S1 | Builder | Постоянное правило в `docs/prompt-versioning-contract.md` + `AGENTS.md`, область действия |
| `PVR-S3-HISTORY` | W3 | S2 | Builder | Без потолка и без `LIMIT 50`, страницы с курсором, полный текст по авторизованному запросу, RBAC, без тел в списках/логах |
| `PVR-S4-UX` | W4 | S1, S3 | Builder | Один компонент на все редакторы, панель истории, действия и честные причины, черновик, мемные карточки, режим `{joke}`, сохранение темы |
| `PVR-S6-AUDIT` | W5 | S4, S5 | Builder | pytest-аудит `pg_key ↔ block_id ↔ UI-editor ↔ versioned write` + негативный тест на обход |
| `PVR-S7-VERIFY` | W6 | все | Reviewer | §6: бэкенд, мемы, фронтенд (десктоп + 390 WebView), отрицательные случаи, отчёт |

---

## 6. Вход для Reviewer (в конце, не заранее)

- Кандидат: merge S0–S6 в `evol/impl`; карта `requirements-map.json` со статусами, привязанными к SHA кандидата.
- Обязательные артефакты: снимок до/после (S0), карта точек записи (S1), тесты `tests/test_prompt_versioned_write.py`, `test_prompt_owner_baseline.py`, `test_prompt_history_pagination.py`, `test_prompt_field_audit.py`, `test_prompt_journal_bypass.py`, `tests/js/prompt_version_ui_test.js`, скриншоты Playwright/Browser Use (десктоп + 390px).
- Спорные места, которые Reviewer обязан ломать самостоятельно: (а) сбой PG между записью значения и ревизией — значение не должно измениться, ответ 503; (б) запрос ревизии чужого чата — 403; (в) 1000+ ревизий — доступность и отзывчивость; (г) pinned scope + новая заводская метка — активный текст не меняется; (д) `{joke}:0` не возвращается в видимую мета-строку; (е) мемные тексты байт-в-байт равны снимку.

## 7. Открытые технические развилки (решает Architect/Builder, не human gate)

1. Где именно живёт baseline-событие: новая колонка в `prompt_activations` (`kind=baseline_set|baseline_clear`) или отдельная строка метаданных — при условии «без второго хранилища» и «без копирования текста».
2. Формат курсора страниц (`created_at, revision_id` vs `activation_id`) и совместимость со старым ответом `versions` (аддитивные поля).
3. Как выразить pin в `activation_plan`: отдельная ветка `PLAN_PINNED_NOOP` против расширения `apply_release` параметром `pinned_scopes`.
4. Нужно ли менять `scope` мемных блоков с `code` на `global_chat` в реестре (это метаданные, не текст) — либо чинить `_prompt_list_scope`.
