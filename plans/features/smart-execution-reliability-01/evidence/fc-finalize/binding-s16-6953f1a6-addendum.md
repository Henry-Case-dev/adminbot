# S16-FC-FINALIZE — review addendum: контейнеры удаляются с содержимым

| Параметр | Значение |
|---|---|
| Срез | `S16-FC-FINALIZE` |
| Блокер ревью | SFC-10-06: `strip_service_tokens()` срезал теги, но оставлял содержимое сырых контейнеров (`<chat_context>` OCR-текст) в пользовательском ответе |
| Исправленный кандидат | **`6953f1a6`** (код); ветка `smart/fc-s16-finalize` |
| Предыдущий кандидат | `8624ae4b` (SFC-9-01..04 VERIFIED, не менялись) |
| Затронуто | `services/factcheck_service.py`, `tests/test_factcheck_finalization.py` |
| Не менялось | `services/factcheck_renderer.py` — он уже вызывает общий `strip_service_tokens`; поведение renderer'а теперь покрыто отдельным тестом |
| Требования | SFC-10-06 (SFC-9-01..04 не переоткрывались) |

## 1. Причина

`_SERVICE_BLOCK_RE` вырезал только ЗАКРЫТЫЕ контейнеры из фиксированного списка
имён. Всё остальное попадало в `_SERVICE_TAG_RE`, который удалял лишь теги:

- незакрытый `<chat_context …>сырой OCR-текст` (обрезанный close-tag) → текст
  оставался;
- `<raw>`, `<ocr>`, `<Chat_Time_Context>` (имён не было в списке блоков) →
  теги срезались частично/не срезались, содержимое оставалось.

Тесты проверяли отсутствие токенов (`insufficient_evidence`, `OCR`), но не
отсутствие самого содержимого контейнера — поэтому дефект прошёл.

Фактическое поведение ДО (probe `raw/sanitizer-probe-6953f1a6.txt`):

```
<chat_context note="OCR">сырой OCR-текст с картинки</chat_context>  -> сырой OCR-текст с картинки
<chat_context>сырой текст без закрытия                              -> сырой текст без закрытия
<raw>внутренние данные</raw>                                        -> внутренние данные
<ocr>распознанный текст</ocr>                                       -> распознанный текст
<Chat_Time_Context>local: 14.11.2026</Chat_Time_Context>            -> local: 14.11.2026
```

## 2. Исправление

`services/factcheck_service.py`:

- единый список служебных/сырых контейнеров (`_SERVICE_CONTAINER_NAMES`):
  прежние служебные блоки + `raw`, `ocr`, `ocr_text`, `vision`,
  `image_context`, `media_context`, `tool_context`, `service_context`,
  `internal`, `debug`, `trace`, `diagnostics`, `payload`, `schema`,
  `chat_time_context`;
- `_SERVICE_BLOCK_RE` вырезает закрытый контейнер ВМЕСТЕ с содержимым и
  закрывается тем же именем тега (backreference, без кросс-теговых совпадений);
- `_drop_unclosed_service_containers()` удаляет незакрытый служебный контейнер
  вместе с содержимым — до конца абзаца/текста; вызывается после удаления
  закрытых блоков;
- `_SERVICE_TAG_RE` расширен тем же списком (страховка от одиночных тегов);
- обычная речь, где имя тега упомянуто без `<…>` (например, «тег
  chat_context как пример разметки»), не затрагивается — проверено тестом.

Renderer и legacy-финализация используют тот же `strip_service_tokens`, поэтому
получают исправление без отдельной копии логики; оба пути закрыты тестами.

Поведение ПОСЛЕ:

```
normal + closed <chat_context>OCR</chat_context> + normal -> normal + normal
normal + unclosed <chat_context>OCR                   -> normal
only <chat_context>OCR</chat_context>                 -> "" -> честный partial
<raw>/<ocr>/<Chat_Time_Context>                        -> содержимое удалено
mention без тега                                       -> без изменений
```

## 3. Тесты

`tests/test_factcheck_finalization.py` — **17 passed** (было 12; +5):

- `test_service_enums_ids_and_ocr_context_never_reach_the_user` — усилен:
  проверяет отсутствие содержимого контейнера («текст с картинки»), не только
  токенов; плюс renderer-граница;
- `test_service_container_content_removed_but_tag_mention_kept` — mixed-кейс:
  нормальный текст до и после контейнера сохраняется, контейнер с содержимым
  удалён, упоминание имени тега без `<…>` не трогается;
- `test_unclosed_service_container_content_removed` — адверсариальный кейс
  ревьюера: незакрытый контейнер не оставляет сырой текст;
- `test_service_container_only_is_not_published_as_the_answer` — только
  контейнер → честный частичный результат, без утечки;
- `test_renderer_removes_service_container_content` — renderer-граница;
- `test_legacy_single_path_removes_container_content` — legacy-финализация.

Прогоны:

| Проверка | Результат |
|---|---|
| `pytest tests/test_factcheck_finalization.py -q` | **17 passed** |
| Фокус (10 файлов: finalization + renderer/service/evidence/subject/prompts/numeric/p0/orchestrator/w1) | **245 passed** |
| `git diff --check 8624ae4b HEAD -- services tests` | пусто, exit 0 |
| `git diff -w 8624ae4b HEAD` | совпадает с обычным diff (68/3), скрытых правок нет |
| Probe контейнеров | `raw/sanitizer-probe-6953f1a6.txt` |

## 4. Мутационное доказательство

Мутация: отключено удаление закрытых блоков и незакрытых контейнеров
(остаётся только удаление тегов) — `raw/mutation-container-content-6953f1a6.diff`.

Результат: **5 failed, 12 deselected** (`raw/mutation-container-content-6953f1a6.txt`):

- `test_service_container_content_removed_but_tag_mention_kept`;
- `test_unclosed_service_container_content_removed`;
- `test_service_container_only_is_not_published_as_the_answer`;
- `test_renderer_removes_service_container_content`;
- `test_legacy_single_path_removes_container_content`.

После проверки файл восстановлен из коммита; рабочее дерево чистое.

## 5. Остаточное

- Незакрытый контейнер удаляется до конца абзаца: если модель продолжила
  нормальный текст в том же абзаце после потерянного close-tag, этот фрагмент
  тоже не публикуется. Это осознанный компромисс в пользу SFC-10-06
  (внутренние данные не выходят); обычное упоминание тега без `<…>` сохраняется.
- SFC-9-01..04 не менялись; повторная проверка фокуса — 245 passed.
- Production/effective-config проверки остаются за S17, как и прежде.
