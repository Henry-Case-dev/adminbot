# Release 2.58.216 — VOICE-TRANSCRIPTION-RECOVERY-01, сборка REVIEW

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-18 |
| Ветка | `release/p0-2.58.216` |
| База (предыдущий релиз / откат) | `f20645f13bbd742aae380596dd9ead52b5888a84` (2.58.215, deployed) |
| Approved voice | `fix/voice-transcription-recovery` tip `6a3e7ba2f` (Reviewer: Approved for voice release preparation) |
| Merge commit | `a19e03ff6` |
| Bump commit | `faa2125c79c811d68ac8635be9f7e8532d477f70` (2.58.215 → 2.58.216) |
| Content tip | `faa2125c79c811d68ac8635be9f7e8532d477f70` |
| Версия | 2.58.216 |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |
| Requirement ID | VOICE-TRANSCRIPTION-RECOVERY-01 |

## 1. Слияние и конфликты

`git merge --no-ff 6a3e7ba2f` от базы `f20645f13` — **без конфликтов**, 0 unmerged
paths, `git status` чист после слияния. Merge-base — `642fa3cde`; база отличается
от него одним docs-коммитом `f20645f13` (runbook/rollback 2.58.215), с voice-веткой
не пересекается.

Пересечение с Vision-слайсом из базы проверено отдельно: `services/media_download.py`
после слияния содержит **оба** контракта — Vision `download_api_file_bytes` (без
изменений по смыслу) и voice-адаптер `download_api_file_to_path` + локальный путь.
`services/mca_vision.py`, `services/task_supervisor.py`, `services/dream_worker.py`
и прочие Vision/Scheduler/L1-файлы voice-ветка не трогает.

Побайтовая сверка: для всех **21** файла, изменённых voice-веткой относительно
`642fa3cde`, blob в `HEAD` совпал с blob `6a3e7ba2f` (`git rev-parse`) — **0
расхождений**. Дополнительно сверены изменённые базой файлы 2.58.215 — сохранены.

## 2. Состав

| Блок | Коммиты | Файлов | Строк |
|---|---|---|---|
| Voice (`6a3e7ba2f`) | 10 коммитов (`2edb31599` … `6a3e7ba2f`) | 21 (18 продуктовых/тестовых + 3 evidence) | +3310 / −461 |
| Bump 2.58.216 | `faa2125c7` | 30 | +32 / −32 |
| **Итого от базы до content tip** | 1 merge + 1 bump | **51** | **+3342 / −493** |

Продуктовые файлы (вне `plans/`), 18 шт.:

- Voice: `handlers/voice_transcription.py` (терминальный lifecycle, replay),
  `handlers/youtube.py` (единый источник режима Bot API),
  `services/local_bot_api.py` (+`telegram_local_mode_enabled`/`session_local_mode`/
  `bot_api_mode`/`log_bot_api_mode`), `services/media_download.py`
  (`download_api_file_to_path`, общий классификатор класса/стадии, empty-cloud
  retry), `services/runtime_probes.py` (`stale_pending` только по доказанной
  протухшести), `services/status_service.py` (`local_api` = фактический режим +
  отдельное `download_enabled`), `services/voice_transcripts.py`
  (`derive_transcript_state`: stale pending → `unavailable/stale_pending`), `bot.py`.
- Тесты: `tests/test_p0_voice_transcription_recovery.py` (новый, 16),
  `tests/test_voice_transcription.py`, `tests/test_media_download.py`,
  `tests/test_video_download.py`, `tests/test_media_transcribe_tool_round1024.py`,
  `tests/test_native_media_tools_round1024.py`,
  `tests/test_p0_vision_download_transport.py`, `tests/test_vmq_v_voice_writer.py`,
  `tests/test_status_service.py`, `tests/test_diagnostic_probes.py`.

Не менялись: `config/settings.py` (кроме строки `APP_VERSION` bump-коммита),
`services/database.py` (DDL 0), `web/*`, `web/api/*`, composer, prompt registry,
`services/param_catalog.py`, `deploy_v2.9.2.py`.

## 3. Bump 2.58.215 → 2.58.216

Тот же набор, что 2.58.215: `config/settings.py` (APP_VERSION + changelog
«Prior 2.58.215»), `plans/docs/param-registry-round1025.meta.md`, 24 py-файла и
4 JS-пина в escaped-виде `2\.58\.216` — **30 файлов / 33 замены**, polygon — 2.
BOM/CRLF сохранены (байтовые правки; `git diff --stat` 32/32, без перезаписи
целых файлов). `tools/gen_param_registry_round1025.py --check` → OK (реестр 645,
TSV/map идемпотентны). Мета: `HEAD (short)` обновлён на content tip в
evidence-коммите.

## 4. Инварианты на content tip (измерено)

| Инвариант | Значение |
|---|---|
| `APP_VERSION` | 2.58.216 |
| Каталог | REGISTRY **645**, GROUPS **121**, `_TAB_BY_GROUP` **119**, TAB_RULES **22** |
| Settings | **472** поля |
| Миграции | MigrationStep **47**, max **47**, уникальные/непрерывные/сортированные |
| Схема | target `user_version` **47**, DDL **0** (`services/database.py` не изменён) |
| Новые флаги/миграции/endpoint'ы/composer/промпты/модели | нет |

## 5. Проверки

Полный набор и фактические числа — `tests-2.58.216.json`. Кратко: voice-профиль
**43 файла / 1340 passed / 0 failed** (ячейка 10 ключевых файлов — 436 passed),
mandatory **386/0**, JS **121 файл: 117 passed / 4 pre-existing** (те же 4, что на
2.58.214/215), `node --check web/app.js` OK, `git diff --check` OK,
`gen_param_registry --check` OK, `py_compile` изменённых модулей OK, сквозной
smoke без сети/Telegram (local path materialised, empty-cloud typed error,
lifecycle `pending/failed/stale_pending/ready`, mode mismatch) — зелёный.
4 устаревших теста вне профиля (8 failed/18 errors) дают те же результаты на базе
`f20645f13` — pre-existing, к сборке отношения не имеют (`limitations.md`).

## 6. Манифест и откат

- `manifest-dry-run.json`: `version=2.58.216`, `deployed_sha=faa2125c7…`
  (content tip), `previous_sha=f20645f13…`, `previous_version=2.58.215`,
  `release_branch=release/p0-2.58.216`, `dirty_tracked=false`. Вход
  `.deploy/release.json` (реконструкция документированного состояния 2.58.215)
  удалён после прогона; в дереве не осталось untracked-файлов.
- `rollback.json`: цель `f20645f13` (2.58.215), schema 47, DDL 0, данные не
  сбрасываются.

## 7. Honest boundaries

Replay трёх сохранённых объектов уже выполнен на production на кандидате
(`replay-run3.json`); 3 из 4 продуктовых blob'ов совпадают побайтово, отличие
`media_download.py` — только поздний empty-cloud retry, в local-path прогоне не
участвовавший. Новый входящий Telegram Update до деплоя не проверялся — это
postdeploy-пункт runbook. Non-blocking находки Reviewer F1–F5 зафиксированы в
`limitations.md` дословно; код под них не менялся.
