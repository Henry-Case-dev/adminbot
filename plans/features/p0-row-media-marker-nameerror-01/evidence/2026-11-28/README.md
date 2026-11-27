# P0-ROW-MEDIA-MARKER-01 — evidence 2026-11-28

- Задача: `p0-row-media-marker-nameerror-01` (P1).
- Ветка: `fix/row-media-marker`.
- База: `f0dc7d87841a6f3089fb4153474768f34c567e22` (production 2.58.261, `APP_VERSION = "2.58.261"`).
- Кандидат: `449e9ee34cd51b6c5162c765d1d371445dbde342`, tree `716b4a0ecfd1307c524c244bf79cfbb6a2d2208c`.
- Base является предком кандидата; изменены только `services/direct_chat_service.py` и новый тест.

## Симптом (production 2.58.261)

`services/direct_chat_service.py` в live-ветке выбора медиа бросал
`NameError: row_media_marker`; исключение перехватывалось fail-open'ом
(`direct: live selection failed — legacy fail-open`), ответ уходил, но весь
ход деградировал на legacy-контекст. Источник: журнал 2.58.261, запись в
`plans/features/p0-fts-index-integrity-01/evidence/release-2.58.261/postdeploy-2.58.261.md`
(2 traceback за окно 15 минут).

## Причина и точное место

В модуле отсутствовал импорт имени:

- база `f0dc7d87`, `services/direct_chat_service.py:167-168`:
  `from services.media_marker import (MEDIA_MARKER_RE, media_context_enabled, media_marker, message_media_type)` — `row_media_marker` не импортирован;
- база `services/direct_chat_service.py:19329` (`DirectChatService._context_row_line`,
  ветка `projection is not None and speech_projection_enabled()`):
  `text = row_media_marker(row, item_id=item_id, projection=projection)`.

Строка вызывается только для медиа-строки окна без подписи (`text == ""`),
когда включена речевая проекция (`flags.context_speech_projection`, заводское
значение ON). Дефект предсуществующий: та же строка есть в `7b68bd25`
(строка 19319).

## Исправление (минимальное)

Импорт уже существующей функции из её единственного дома
(`services/media_marker.py:126`), без изменения алгоритма маркера и выбора:

```
 from services.media_marker import (
-    MEDIA_MARKER_RE, media_context_enabled, media_marker, message_media_type)
+    MEDIA_MARKER_RE, media_context_enabled, media_marker, message_media_type,
+    row_media_marker)
```

Проверка `static-check.txt`: в кандидате `row_media_marker` в модуле — только
импорт (строка 169) и вызов (19330); локального определения нет; другие
потребители (`services/chat_context.py`, `services/thread_chain.py`) уже
импортировали функцию. Fail-open fallback не тронут.

## RED → GREEN

Новый тест `tests/test_p0_row_media_marker_live_selection.py` (2 теста)
проходит реальный live-вход `_compose_user_content(..., live_selection=True)`
на фикстурах/реальной temp-SQLite, без сети и LLM.

1. `test_live_selection_renders_media_row_marker_without_fail_open`:
   - строка окна без текста с `media_type="photo"`, речевая проекция ON;
   - оракул из внешнего контракта `services/media_marker.py`: в payload
     присутствует `[медиа: photo M<n>]`;
   - доказательство исполнения live-ветки: `direct_context_composer.allocate_selection`
     вызван ровно 1 раз (spy), и в журнале нет
     `live selection failed — legacy fail-open`.
2. `test_genuine_live_failure_still_falls_back` — негативный контроль:
   настоящая ошибка allocator'а по-прежнему уходит в legacy fail-open
   (warning присутствует, ход не потерян). Файл падает RED на базе именно
   на первом тесте; второй проходит и на базе (страховка не менялась).

- RED (база `f0dc7d87`, тест подложен как untracked в checkout базы):
  `raw/red-base-f0dc7d87.txt` — 1 failed, 1 passed; полный production-стек
  `_context_row_line` (`.../direct_chat_service.py:19329`) → `NameError:
  name 'row_media_marker' is not defined` → перехват в
  `_compose_user_content` (`:14044`).
- GREEN (кандидат `449e9ee`): `raw/green-candidate-449e9ee.txt` — 2 passed.

## Regression-прогоны (фактические)

| Набор | База `f0dc7d87` | Кандидат `449e9ee` | Файл |
|---|---|---|---|
| новый тест + `test_direct_chat*` (6 файлов) + `test_ur_c_3_real_fts` + `test_ur_c_final_a` | 324 passed (без нового файла) | 326 passed | `raw/base-direct-live-selection.txt`, `raw/candidate-direct-live-selection.txt` |
| unified/retrieval + VMQ oldrow (`test_memory_unified_retrieval`, `..._06`, `test_unified_core_route_coverage`, `test_unified_reply_ur_b_*` ×3, `test_mca07_retrieval_context_round1027`, `test_vmq_oldrow_person_delivery`, `test_vmq_mem07_oldrow_reservation`) | 294 passed | 294 passed | `raw/base-unified-retrieval-vmq.txt`, `raw/candidate-unified-retrieval-vmq.txt` |

Предсуществующих red-ов в этих наборах нет ни на базе, ни на кандидате —
сверка по фактическим прогонам, не по памяти.

## Конфигурация

- `flags.context_speech_projection`: в тесте включён через живой hot-config
  cache (как в `tests/test_evol_reply_context_consumers.py`); заводское
  значение `CONTEXT_SPEECH_PROJECTION_ENABLED=True`.
- `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` (заводское ON) в direct-рендере
  `_context_row_line` не участвует: там маркер включается речевой проекцией;
  значения флага на дефект не влияет.
- Никаких изменений флагов, DDL, промптов, версии, карт в кандидате нет.

## Ограничения

- Проверка на живом Telegram не выполнялась (задача — детерминированный
  Python-путь; live-деплой и postdeploy-наблюдение вне этой ветки).
- Прод не изменялся (read-only); деплой кандидата — отдельный шаг.
