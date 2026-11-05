# PVR-S0 + PVR-S1 — единый слой записи и страж обхода журнала

Срез: `EPIC-PROMPT-VERSIONING-UX-01`, PVR-S0 (рантайм-страж) и PVR-S1
(атомарный версионированный слой записи). База: `2841a6ef` (ветка `evol/impl`),
ветка среза `pv/write-layer`.

Нормативная база: `plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md`
§1 (десять обходящих путей), §3 (единая запись и отказы), §3.7 (первый захват),
§5 (три слоя аудита), §7 (тесты/риски); `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md`
§0, §1, §3, §4, §5.

## 1. Жёсткое ограничение пакета: тексты промптов не изменены

Байт-эталон снят ДО первой правки: `prompt-bytes-baseline.json`
(39 PG-блоков, `aggregate_sha256_over_all_block_sha256 =
51425b07d299e0beefd0510b7cdadd9049100b5de9a615fbe859263cd3d2e2ad`,
`FACTORY_SET_SHA256_12 = 54ac2b8ac34b`). Повторный прогон
`capture_prompt_bytes.py` после всех правок дал ПОЛНОЕ совпадение (агрегат,
все 39 блоков, набор печатей): `diff blocks: []`.

Мемные промпты (текст владельца из админки):

| блок | pg_key | sha256 | байт |
|---|---|---|---|
| `initiative.meme.joke` | `prompts.meme_joke` | `2f30ca1f9a6b…452d58` | 95 |
| `initiative.meme.image` | `prompts.meme_image` | `f81fe7e4b505…86276c` | 51 |

Действующий (эффективный) текст этих блоков живёт в production PG
(`bot_settings` / `chat_profiles.overrides`) и снимается тем же скриптом на
деплое; в этом пакете запись байтов владельца не выполняется.

## 2. Что реализовано

Единая запись `services.prompt_release_policy.write_prompt_values`:
ревизия (идемпотентно по `revision_id`) + событие активации + значение одной
PG-транзакцией под `APPLY_LOCK_SQL` с `SET LOCAL lock_timeout='5s'`. Все
решения (`skipped_same`, `read_applied`, полный набор overrides чата) читаются
ВНУТРИ транзакции на её коннекте; чат пишется одним
`chat_params.set_chat_params(conn=<tx-conn>, expected_updated_at=…)`.

Отказы: журнал недоступен / лок занят → `JournalUnavailable` → HTTP 503 и
значение не записано; `ChatParamsConflict` → 409; устаревший global-токен →
`FactoryConflict` → 409; гейты значения → 422. Возврата
`journal_recorded=False` как успеха больше нет.

Страж §5.3: `ConfigCache.set/set_many` и `chat_params.set_chat_params`
отказывают (`PromptJournalBypass`) при записи ТЕКСТА промпта без журнального
токена. Токен ставится только журнальными писателями.

Удалено: `record_manual_activation` (best-effort журнал), ветка
`prompt_factory` «журнал недоступен → пишем значение без журнала»,
`_prompt_record_saved_snapshots` (best-effort после записи).

## 3. Проверка

Новый постоянный тест `tests/test_prompt_versioning_enforcement.py`
(27 проверок): слой 1 (реестр ↔ UI-доступность), слой 2 (матрица по точкам
записи §3.4: ревизия + событие + значение + `skipped_same` без дубля + 503 без
записи), слой 3 (страж и две мутации), §3.2/§3.3 (сбой вставки ревизии, CAS,
чужой чат), байт-эталон мемов.

Прогоны (этот worktree против эталонного worktree на `2841a6ef`):

| набор | этот срез | эталон `2841a6ef` |
|---|---|---|
| `-k "prompt or speech or config or meme or cover or core or soul1 or evol or webapp or admin or summary or migrat"` | 7129 passed / 31 failed | 7102 passed / 31 failed |
| `-k "factcheck or direct or gates or keys or hot or bot or pg or db or roles or perm or lore or memory or voice or cover or speech"` | 5684 passed / 31 failed | 5678 passed / 31 failed |

Разница множеств падений после повторного прогона — пустая по существу:
остаются те же предсуществующие падения плюс нестабильные `subprocess`-тесты
(`node`/e2e), которые падают и на неизменённом эталоне (проверено тремя
последовательными прогонами: один и тот же тест проходит/падает случайно,
`OSError [WinError 6]/[WinError 50]` в `subprocess` под pytest-capture).

Ключевые наборы отдельно: `test_evol017_prompt_history_ui.py` и
`test_evol018_prompt_audit.py` не изменялись и зелёные;
`test_evol016_prompt_activation.py`, `test_meme_pipeline_api.py`,
`test_webapp_api.py`, `test_soul1_factory_defaults.py`,
`test_soul1_w6_speech_ui.py` — зелёные.

## 4. Осознанно изменённые тесты (клауза контракта)

| тест | что закреплял | клауза |
|---|---|---|
| `test_meme_pipeline_api.py` | ответ спец-эндпоинта без журнала | §7.1, §3.1–3.2 |
| `test_soul1_factory_defaults.py` | сбросы без ревизии; `cache.writes[-1]` как «последнее действие» | §7.1, §3.4 |
| `test_soul1_w6_speech_ui.py` | writer промпта = `prompt_factory` | §7.1, §3.1 |
| `test_webapp_api.py` | точная форма ответа `/api/config` | §3.8 (аддитивное `prompt_snapshots`) |
| `test_hotfix4_cover_nav_shell_round1025.py` | прямая `cache.set` промпта | §5.3 |
| `test_round1025_f8_registry.py` | sha-пин `routes.py` | L-F11S-1 (переутверждение) |
| `test_evol016_prompt_journal_v39.py` | двойник PG знал только старый SQL | §2.3 (`SET LOCAL`, detail_code) |
| `test_evol014_ui.py`, `test_hot_config.py`, `test_mca23_response_plan.py`, `test_p0_*`, `test_soul1_*`, `test_summary_*`, `test_ui_verbilizer_tabs_round1023.py` | промпт писался без журнала | §3 (тестовый стор через conftest-фикстуру) |

## 5. Найденные расхождения (для Reviewer)

1. Контракт §5.1 предполагает, что все 39 PG-блоков видны в каталоге
   «Промпты». Фактически в каталоге 28 ключей; вне каталога —
   `character.core` (экран «Характер») и 9 управляемых сообщений
   `content.image_failure.*` / `content.image_request_clarify`
   (read-only в истории). Это зафиксировано явным реестром
   `NON_CATALOG_SURFACES` в тесте слоя 1; новый PG-блок без поверхности
   редактирования валит тест.
2. `services/prompt_migrations.normalize_legacy_speech` /
   `rollback_legacy_speech` пишут текст промпта в обход журнала и НЕ входят в
   перечень §1.4. Оставлены рабочими через явную, логируемую декларацию
   `legacy_migration_write(...)` (код-поставленная миграция со своим
   неизменяемым снимком `character.migration_snapshots` и откатом). Кандидат
   на отдельный слайс: перевести её на `write_prompt_values`.
3. `POST /api/cover/select` пишет `prompts.summary_cover_style_id` — это слот
   выбора, не текст; внесён в `NON_TEXT_VALUE_KEYS`.
