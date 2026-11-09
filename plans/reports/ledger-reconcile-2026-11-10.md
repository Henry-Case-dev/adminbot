# Сверка леджера: master ↔ release/2.58.175 (2026-11-10)

Одна каноническая книга требований собрана из двух разошедшихся линий. Ни одна строка,
ни один статус с доказательством и ни один исходный документ не удалены. Выдуманных строк нет.

## 1. Правила слияния

**Идентичность строки** — `(req_id, source_id)`; если `req_id` пуст, то `("SRC:"+source_id, source_id)`.
Проверено: эта пара уникальна в каждом файле на обеих сторонах (0 коллизий), поэтому строки
сшивались по ней, а не по номеру строки. `slice` в идентичность не входит — он менялся между
линиями у одной и той же строки.

**Статус при конфликте:**

1. более продвинутый статус берётся только если у его стороны есть разрешимое доказательство;
2. иначе берётся сторона, у которой доказательство есть;
3. иначе — `PENDING` и запись конфликта.

Порядок продвижения: `PENDING` < `FAILED` < `BUILDING` < `REVIEW` < `READY_FOR_LIVE` < `VERIFIED`
(`FAILED` выше `PENDING`, потому что это зафиксированный результат, а не пустая строка).

**Что считается разрешимым доказательством** (по конвенции самих карт): запись `evidence[]`, у которой
`artifact_path` существует в рабочем дереве или в линии релиза, либо указана `artifact_branch`, либо
есть непустые `ref` + `observation`. Для строк `disposition: "duplicate"` доказательством считается
доказательство канонической строки того же `req_id` — иначе 374 легитимные дубликатные строки в `evol`
были бы ошибочно понижены до `PENDING`.

**Карты:** одинаковая по байтам карта — не трогалась; карта только на одной стороне — копировалась целиком;
если полная сторона действительно является надмножеством по идентификаторам и ни одна строка не регрессирует —
побеждает она; иначе построчный union. После union результат сравнивался с обеими сторонами, чтобы не
переформатировать файлы, содержимое которых не изменилось.

**Реестр (`plans/progress_scope.json`):** union задач по `id` и owner-входов по `id`; поля берутся из более
богатой записи, `maps[]` — объединение путей, `status` — более продвинутый, `source_path`/`source_sha256` —
та пара, которая реально совпадает с файлом на диске.

## 2. Было / стало

| Величина | master (2.58.111, рабочее дерево) | release/2.58.175 | Каноническая книга |
|---|---|---|---|
| Задачи в реестре | 35 | 44 | **49** |
| owner-входы | 45 | 55 | **66** |
| Файлы карт | 39 | 48 | **53** |
| Строк всего (все файлы карт) | 7540 | 10752 | **12304** |
| Карт в реестре `tasks[].maps` | 38 | 48 | **53** |
| Строк в зарегистрированных картах | 7465 | 10752 | **12304** |

Уникальных идентичностей строк: на линии релиза 9212, в каноне **10148**; канон содержит всё, что было
на обеих сторонах — для карт, оставленных байт в байт, это очевидно, а для четырёх слитых проверено
построчно (раздел 5: потерянных ключей 0). Разница между 12304 строками и 10148 идентичностями —
это дубликатные строки, которые в этих картах легитимно повторяют один `req_id` из разных исходных
пунктов (конвенция, а не дубли-ошибки), плюс 75 строк Track P, которые после разделения эпика лежат
и в своей карте, и в карте эпика.

Замеренные числа отличаются от цифр в задании (4245 / 7568): там, судя по всему, считался другой срез
(например только `disposition: required` или только `items`). Здесь приведены прямые замеры всех строк
(`items` + `additional_requirements`), `required`-строк в реестре сейчас 7059, `VERIFIED` — 5123.

## 3. По каждой карте: что взято откуда

| Карта | master | release | канон | действие | конфликты |
|---|---|---|---|---|---|
| `add-exp/requirements-map.json` | 37 | 37 | 37 | файлы идентичны — не тронуто | — |
| `add-tr/requirements-map.json` | 69 | 69 | 69 | файлы идентичны — не тронуто | — |
| `asap-evol-anticliche-memory-admin-ux/requirements-map.json` | — | 669 | 669 | была только на линии релиза — скопирована целиком | — |
| `asap-fc-voice-01/requirements-map.json` | — | 129 | 129 | была только на линии релиза — скопирована целиком | — |
| `asap-speech-arch/requirements-map-p0-corrective.json` | 131 | 131 | 131 | файлы идентичны — не тронуто | — |
| `asap-speech-arch/requirements-map-p0-hotfix.json` | 160 | 160 | 160 | файлы идентичны — не тронуто | — |
| `asap-speech-arch/requirements-map-speech-simplify.json` | 233 | 233 | 233 | файлы идентичны — не тронуто | — |
| `asap-speech-arch/requirements-map.json` | 161 | 161 | 161 | файлы идентичны — не тронуто | — |
| `asap2-direct-chat/requirements-map.json` | 146 | 146 | 146 | файлы идентичны — не тронуто | — |
| `asap3-corrective/requirements-map.json` | 281 | 281 | 281 | файлы идентичны — не тронуто | — |
| `asap5-multimodal/requirements-map.json` | 483 | 483 | 483 | файлы идентичны — не тронуто | — |
| `asap8-v6-3-live-correction/requirements-map.json` | 227 | 227 | 227 | файлы идентичны — не тронуто | — |
| `behavior-gates-simplification/requirements-map.json` | — | 184 | 184 | была только на линии релиза — скопирована целиком | — |
| `cfg/requirements-map.json` | 293 | 293 | 293 | файлы идентичны — не тронуто | — |
| `embed-identity-compat/requirements-map.json` | 72 | 72 | 72 | файлы идентичны — не тронуто | — |
| `epic-adminbot-corrective-ym-nost-20261108/requirements-map.json` | 436 | — | 436 | была только в master — оставлена как есть | — |
| `epic-cm-visual-01/requirements-map.json` | — | 253 | 253 | была только на линии релиза — скопирована целиком | — |
| `epic-experience-learning-performance-help/requirements-map-epic-parity.json` | — | — | 240 | два разных источника — две карты | — |
| `epic-experience-learning-performance-help/requirements-map.json` | 75 | 240 | 75 | два разных источника — две карты | — |
| `epic-prompt-versioning-ux-01/requirements-map.json` | — | 77 | 77 | была только на линии релиза — скопирована целиком | — |
| `evol-reply-context-integrity-01/requirements-map.json` | — | 355 | 355 | была только на линии релиза — скопирована целиком | — |
| `evol-reply-context-integrity/requirements-map.json` | 18 | 18 | 18 | построчный union | evidence 3, status 3 |
| `evol/requirements-map.json` | 540 | 2398 | 2398 | union ≡ линия релиза — взята она | status 345 |
| `factcheck-clean-publication/requirements-map.json` | 19 | 19 | 19 | файлы идентичны — не тронуто | — |
| `goodmorning-quantum-media/requirements-map.json` | — | 9 | 9 | была только на линии релиза — скопирована целиком | — |
| `hotfix-meme-publication-initiative-ui/requirements-map.json` | — | 92 | 92 | была только на линии релиза — скопирована целиком | — |
| `meme-pipeline-refactor-01/requirements-map.json` | — | 197 | 197 | была только на линии релиза — скопирована целиком | — |
| `memory-cognitive-02/requirements-map.json` | 300 | 299 | 300 | построчный union | acceptance 5, evidence 10, status 22 |
| `menu-01/requirements-map.json` | 13 | 13 | 13 | построчный union | evidence 10 |
| `mod-acl-ux-01/requirements-map.json` | 378 | — | 378 | была только в master — оставлена как есть | — |
| `p0-admin-cache-toggle-save/requirements-map.json` | 10 | 10 | 10 | файлы идентичны — не тронуто | — |
| `p0-corrective-factcheck-speech/requirements-map.json` | 707 | 707 | 707 | файлы идентичны — не тронуто | — |
| `p0-delta-analysis/requirements-map.json` | 151 | 151 | 151 | файлы идентичны — не тронуто | — |
| `p0-factcheck-media/requirements-map.json` | 175 | 175 | 175 | файлы идентичны — не тронуто | — |
| `p0-factcheck-post-release/requirements-map.json` | 255 | 255 | 255 | файлы идентичны — не тронуто | — |
| `p0-history-analysis/requirements-map.json` | 376 | 376 | 376 | файлы идентичны — не тронуто | — |
| `p0-meme-image-only/requirements-map.json` | — | 13 | 13 | была только на линии релиза — скопирована целиком | — |
| `p0-nostalgia-rework/requirements-map.json` | 269 | 269 | 269 | файлы идентичны — не тронуто | — |
| `p0-save-init-ux/requirements-map-followup.json` | 42 | 42 | 42 | файлы идентичны — не тронуто | — |
| `p0-save-init-ux/requirements-map.json` | 35 | 35 | 35 | файлы идентичны — не тронуто | — |
| `p0-vision-universal/requirements-map.json` | 38 | 38 | 38 | файлы идентичны — не тронуто | — |
| `pemsoc-one-reaction/requirements-map.json` | 4 | 4 | 4 | файлы идентичны — не тронуто | — |
| `post-asap5-corrective/requirements-map.json` | 251 | 251 | 251 | файлы идентичны — не тронуто | — |
| `pvr-fc-corrective-01/requirements-map.json` | — | 154 | 154 | была только на линии релиза — скопирована целиком | — |
| `release-then-migrate/requirements-map.json` | 91 | 91 | 91 | файлы идентичны — не тронуто | — |
| `remove-legacy-rephrasing/requirements-map.json` | — | 189 | 189 | была только на линии релиза — скопирована целиком | — |
| `samples-ux/requirements-map.json` | 77 | 77 | 77 | файлы идентичны — не тронуто | — |
| `self-diag-01/requirements-map.json` | 236 | — | 236 | была только в master — оставлена как есть | — |
| `soul-1/requirements-map-amendment.json` | 95 | 95 | 95 | файлы идентичны — не тронуто | — |
| `soul-1/requirements-map.json` | 198 | 198 | 198 | файлы идентичны — не тронуто | — |
| `unified-reply/requirements-map.json` | — | 345 | 345 | была только на линии релиза — скопирована целиком | — |
| `vmq-onto-01/requirements-map.json` | 426 | — | 426 | была только в master — оставлена как есть | — |
| `win-glass-hotfix/requirements-map.json` | 32 | 32 | 32 | union ≡ master — оставлен master | — |

Отдельно про `epic-experience-learning-performance-help`: на двух линиях это **две разные карты
одного эпика из двух разных снимков ТЗ**.

- master: `requirements-map.json` ← `source-track-p-2026-11-02.md` (только Track P, 75 строк);
- линия релиза: карта ← `source-2026-11-02-epic-and-parity.md` (весь эпик + parity, 240 строк, 176 строк инвентаря).

Слить их в один файл нельзя без подмены источника: строки ссылаются на `source_id`/`source_text_sha256`
того документа, из которого построены, и гейт плана сверяет их именно с `source_path` карты.
Поэтому master-карта оставлена без изменений, а карта линии релиза добавлена рядом как
`requirements-map-epic-parity.json` со своим `slice-graph-epic-parity.json` (в нём изменено ровно одно
поле `slice_graph_path`). Обе карты зарегистрированы в задаче эпика — ни один набор строк не потерян.

## 4. Конфликты

Всего записано **398** конфликтов: 370 по статусу, 23 по составу
доказательств, 5 по тексту приёмки. Ни один не разрешён молча.

| Карта | статус | доказательства | приёмка |
|---|---|---|---|
| `evol-reply-context-integrity/requirements-map.json` | 3 | 3 | 0 |
| `evol/requirements-map.json` | 345 | 0 | 0 |
| `memory-cognitive-02/requirements-map.json` | 22 | 10 | 5 |
| `menu-01/requirements-map.json` | 0 | 10 | 0 |

Правила, по которым разрешались конфликты, и их фактическое распределение:

- 363× — more advanced side (R) has resolvable evidence
- 7× — more advanced side (L) has resolvable evidence

Не было ни одного случая «доказательств нет ни у одной стороны»: понижать до `PENDING` ничего не пришлось.
Ни одна строка не помечена `VERIFIED` заново — только сохранялся уже существовавший статус со ссылкой.

### 4.1 Конфликты по тексту приёмки (полные тексты сохранены здесь)

**`MEM-07.6`** (`memory-cognitive-02/requirements-map.json`) — оставлен текст master,
текст линии релиза приведён ниже целиком.

- master: Связь из mca_associations остаётся классом cooccurrence 0.1 даже при подтверждённых концах и status='accepted': она не повышается до подтверждённой, учитывается отдельно и не превращается в «друзья/родственники/причинно вызвало».
- release: Приёмка: соблюдено требование источника «**MEM-07.6.** Ассоциативный поиск по связям допускает «похожие темы / общие эпизоды / shared sources» как гипотезу для поиска, но не перевод» — подтверждается целевым тестом/доказательством и независимым ревью.

**`MEM-07.4`** (`memory-cognitive-02/requirements-map.json`) — оставлен текст master,
текст линии релиза приведён ниже целиком.

- master: Подпись формируется из реально доминирующей сущности с источником либо нейтральная «Сообщество N» с основанием; LLM-наименования на горячем пути нет; метрики (узлы, подтверждённые и cooccurrence-связи, последняя активность, внутренние темы, плотность) — из настоящих данных, неизвестное = «Неизвестно».
- release: Приёмка: соблюдено требование источника «**MEM-07.4.** Подпись сообщества формировать из действительно известных топ-сущностей и тем с источниками. Название типа `«Обсуждение GregTe» — подтверждается целевым тестом/доказательством и независимым ревью.

**`MEM-07.5`** (`memory-cognitive-02/requirements-map.json`) — оставлен текст master,
текст линии релиза приведён ниже целиком.

- master: Повторная сборка без изменений сохраняет community_id (26 сообществ переиспользованы с теми же id) при новом build_id; split/merge описываются в change_summary_json с mapping и причинами; entity_id не меняется из-за смены раскладки; детерминизм: 3 независимых экземпляра с одинаковым посевом (80 узлов/200 рёбер) дают один sha256.
- release: Приёмка: соблюдено требование источника «**MEM-07.5.** Структура и идентификатор сообщества стабильны между обычными перезагрузками/незначительными изменениями, насколько это позвол» — подтверждается целевым тестом/доказательством и независимым ревью.

**`MEM-07.1`** (`memory-cognitive-02/requirements-map.json`) — оставлен текст master,
текст линии релиза приведён ниже целиком.

- master: Сообщество — связная группа реальных рёбер chat scope, а не топологическая компонента и не LOD-тайл: id `c<min nodes.id>`, состав, метрики и подпись не совпадают с render-тайлом; соседство точек на экране семантического отношения не создаёт.
- release: Приёмка: соблюдено требование источника «**MEM-07.1.** Разделить три вещи, которые ранее путались: **топологическая компонента**, **семантическое сообщество на основе подтверждённых» — подтверждается целевым тестом/доказательством и независимым ревью.

**`MEM-07.2`** (`memory-cognitive-02/requirements-map.json`) — оставлен текст master,
текст линии релиза приведён ниже целиком.

- master: Сборка идёт на backend по реальным узлам и рёбрам всего chat scope (вход не ограничен экранными 697) с весами confirmed 1.0 / tentative 0.5 / legacy 0.25 / cooccurrence 0.1; algorithm/version пишутся в mca_community_builds, новые рёбра не выдумываются.
- release: Приёмка: соблюдено требование источника «**MEM-07.2.** Сообщества вычислять **на backend по реальным узлам и рёбрам в пределах chat scope**, с весами, понижающими tentative/unverifi» — подтверждается целевым тестом/доказательством и независимым ревью.

### 4.2 Конфликты статусов в картах, которых это касается по существу

**`evol-reply-context-integrity/requirements-map.json`**

| req_id | master | release | выбран | правило |
|---|---|---|---|---|
| `RCI-04` | REVIEW | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `RCI-05` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `RCI-06` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |

**`memory-cognitive-02/requirements-map.json`**

| req_id | master | release | выбран | правило |
|---|---|---|---|---|
| `MEM-07.6` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-07.4` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-03.4` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-05.1` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-07.5` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-02.7` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-02.5` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-03.9` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEMORY-01` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-05.7` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-04.6` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-02.6` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-02.8` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-05.2` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-04.4` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-07.1` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-03.3` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-02.4` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-04.3` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-07.2` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `MEM-05.5` | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `MEM-08-S1` | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |

`evol`: 345 конфликтов статуса по одной схеме (master-копия была устаревшей и неполной,
строка на линии релиза несёт доказательство) — полный список в приложении B.

## 5. Сохранённые новые артефакты (до и после)

Список файлов, которые появились в рабочем дереве после сверки 2.58.175 и которые нельзя было
перезаписать. Их содержимое не изменялось; для карт это подтверждено совпадением sha256 до и после.

| Артефакт | Что это | Состояние |
|---|---|---|
| `plans/features/mod-acl-ux-01/**` (21 файл) | карта 2.58.175, M1 live-подтверждение, M2, M4A, M5A/M5C/M5L, deploy-заметки | не тронуто, sha256 карты `ea967a0a639d…` до и после |
| `plans/features/self-diag-01/**` (5 файлов) | карта, `plan.md`, `slice-graph.json` c D0–D7 и привязками D2 | не тронуто, sha256 карты `ebc3c27537c5…` до и после |
| `plans/features/vmq-onto-01/**` (4 файла) | карта VMQ-ONTO-01 | не тронуто, sha256 `0ea06bfa346e…` |
| `plans/features/epic-adminbot-corrective-ym-nost-20261108/**` (6 файлов) | карта эпика YM/NOST | не тронуто, sha256 `d8697b79dd02…` |
| `plans/features/memory-cognitive-02/evidence|reports|audit-a0.md` | MEM-07/MEM-08 доказательства | не тронуто (в HEAD не отслеживается) |
| `plans/features/win-glass-hotfix/requirements-map.json` | рабочая копия новее HEAD по форматированию | байты сохранены, `763e2d780e11…` |
| `plans/owner_inputs/2026-11-09-*.md` (7 файлов) | входы владельца 09.11 | не тронуто |
| `plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md` | вход 10.11 | не тронуто, `2eca66da1825…` |
| `plans/workflow_state.md`, `plans/current_task.md` | не мои файлы | не тронуто |

Доказательство отсутствия потерь в слитых картах (сверка с версией в HEAD):

| Карта | строк в HEAD | строк в каноне | потеряно ключей | потеряно evidence | регрессий статуса | не перенесено полей |
|---|---|---|---|---|---|---|
| `evol-reply-context-integrity` | 18 | 18 | 0 | 0 | 0 | 0 |
| `menu-01` | 13 | 13 | 0 | 0 | 0 | 0 |
| `memory-cognitive-02` | 298 | 300 | 0 | 0 | 0 | 5 (`acceptance` — см. 4.1, там оба текста) |
| `evol` | (в HEAD не отслеживается) | 2398 | 0 | 0 | 0 | 0 — union совпал с линией релиза байт в байт |

## 6. Валидация

- разбираются как JSON: все 53 карт;
- дубликатов идентичности строк внутри карты: 0;
- обязательные поля строк на месте; исключения — унаследованные: 5 строк `M-TOG-*` в
  `p0-admin-cache-toggle-save` и 1 строка `M00046-POSTGATE-TRANSITION` в `release-then-migrate`
  не имеют статуса и полей приёмки ровно так же, как и до слияния (это ручные проверки, а не требования);
- все пути `tasks[].maps` существуют: да, карт в реестре 53, незарегистрированных файлов карт нет;
- у всех 66 owner-входов `target_task_ids` разрешаются в существующие задачи либо есть `recorded_in`;
- исходные документы: у всех 66 входов `source_path` существует (19 недостающих файлов входов скопированы из линии релиза);
- блокирующих ошибок: 1 — `asap-speech-arch/requirements-map-p0-hotfix.json` ссылается
  на `slice-graph-p0-hotfix.json`, которого нет ни на одной линии (унаследованный битый указатель, не создавался мной);
- предупреждений (унаследованные конвенции): 20.

## 7. Гейты

### 7.1 План (`--stage plan`) для каждой карты

50 карт из 53 проходят без ошибок. Не проходят три — все три по причинам, которые были и до сверки:

| Карта | Ошибок | Причина |
|---|---|---|
| `asap-speech-arch/requirements-map-p0-hotfix.json` | 1 | нет `slice-graph-p0-hotfix.json` ни на одной линии (было 162 ошибки: не хватало ещё и исходного документа — документ восстановлен) |
| `evol/requirements-map.json` | 2618 | `source_path` = `plans/current_task.md`: файл принадлежит владельцу и меняется, зафиксированный хэш совпасть не может; поэтому все номера строк разъехались (до сверки было 4356 ошибок на урезанной карте в 540 строк) |
| `pemsoc-one-reaction/requirements-map.json` | 8 | в источнике нет пунктов инвентаря (`inventory=0`), карта состоит из 4 ручных строк — как и до сверки |

Остальные результаты построчно:

| Карта | inventory | manual | errors |
|---|---|---|---|
| `add-exp/requirements-map.json` | 20 | 17 | 0 |
| `add-tr/requirements-map.json` | 32 | 37 | 0 |
| `asap2-direct-chat/requirements-map.json` | 71 | 75 | 0 |
| `asap3-corrective/requirements-map.json` | 162 | 119 | 0 |
| `asap5-multimodal/requirements-map.json` | 317 | 166 | 0 |
| `asap8-v6-3-live-correction/requirements-map.json` | 148 | 79 | 0 |
| `asap-evol-anticliche-memory-admin-ux/requirements-map.json` | 521 | 148 | 0 |
| `asap-fc-voice-01/requirements-map.json` | 89 | 40 | 0 |
| `asap-speech-arch/requirements-map.json` | 120 | 41 | 0 |
| `asap-speech-arch/requirements-map-p0-corrective.json` | 69 | 62 | 0 |
| `asap-speech-arch/requirements-map-p0-hotfix.json` | 79 | 81 | 1 |
| `asap-speech-arch/requirements-map-speech-simplify.json` | 167 | 66 | 0 |
| `behavior-gates-simplification/requirements-map.json` | 143 | 41 | 0 |
| `cfg/requirements-map.json` | 246 | 47 | 0 |
| `embed-identity-compat/requirements-map.json` | 43 | 29 | 0 |
| `epic-adminbot-corrective-ym-nost-20261108/requirements-map.json` | 419 | 17 | 0 |
| `epic-cm-visual-01/requirements-map.json` | 226 | 27 | 0 |
| `epic-experience-learning-performance-help/requirements-map.json` | 43 | 32 | 0 |
| `epic-experience-learning-performance-help/requirements-map-epic-parity.json` | 176 | 64 | 0 |
| `epic-prompt-versioning-ux-01/requirements-map.json` | 63 | 14 | 0 |
| `evol/requirements-map.json` | 2052 | 346 | 2618 |
| `evol-reply-context-integrity/requirements-map.json` | 12 | 6 | 0 |
| `evol-reply-context-integrity-01/requirements-map.json` | 312 | 43 | 0 |
| `factcheck-clean-publication/requirements-map.json` | 12 | 7 | 0 |
| `goodmorning-quantum-media/requirements-map.json` | 3 | 6 | 0 |
| `hotfix-meme-publication-initiative-ui/requirements-map.json` | 84 | 8 | 0 |
| `meme-pipeline-refactor-01/requirements-map.json` | 116 | 81 | 0 |
| `memory-cognitive-02/requirements-map.json` | 153 | 147 | 0 |
| `menu-01/requirements-map.json` | 3 | 10 | 0 |
| `mod-acl-ux-01/requirements-map.json` | 279 | 99 | 0 |
| `p0-admin-cache-toggle-save/requirements-map.json` | 2 | 8 | 0 |
| `p0-corrective-factcheck-speech/requirements-map.json` | 401 | 306 | 0 |
| `p0-delta-analysis/requirements-map.json` | 14 | 137 | 0 |
| `p0-factcheck-media/requirements-map.json` | 54 | 121 | 0 |
| `p0-factcheck-post-release/requirements-map.json` | 222 | 33 | 0 |
| `p0-history-analysis/requirements-map.json` | 184 | 192 | 0 |
| `p0-meme-image-only/requirements-map.json` | 8 | 5 | 0 |
| `p0-nostalgia-rework/requirements-map.json` | 269 | 0 | 0 |
| `p0-save-init-ux/requirements-map.json` | 22 | 13 | 0 |
| `p0-save-init-ux/requirements-map-followup.json` | 26 | 16 | 0 |
| `p0-vision-universal/requirements-map.json` | 24 | 14 | 0 |
| `pemsoc-one-reaction/requirements-map.json` | 0 | 4 | 8 |
| `post-asap5-corrective/requirements-map.json` | 222 | 29 | 0 |
| `pvr-fc-corrective-01/requirements-map.json` | 97 | 57 | 0 |
| `release-then-migrate/requirements-map.json` | 37 | 54 | 0 |
| `remove-legacy-rephrasing/requirements-map.json` | 112 | 77 | 0 |
| `samples-ux/requirements-map.json` | 48 | 29 | 0 |
| `self-diag-01/requirements-map.json` | 183 | 53 | 0 |
| `soul-1/requirements-map.json` | 101 | 97 | 0 |
| `soul-1/requirements-map-amendment.json` | 66 | 29 | 0 |
| `unified-reply/requirements-map.json` | 206 | 139 | 0 |
| `vmq-onto-01/requirements-map.json` | 380 | 46 | 0 |
| `win-glass-hotfix/requirements-map.json` | 14 | 18 | 0 |

### 7.2 Ревью двух крупнейших срезов

| Срез | Карта | Требований в срезе | Ошибок | Что именно |
|---|---|---|---|---|
| `M2` | `mod-acl-ux-01` | 54 | 18 | 15 строк не `VERIFIED` (PENDING) + 3 live-строки без доказательства ⇒ **39/54 подтверждены**, что совпадает с записью леджера |
| `D2` | `self-diag-01` | 44 | 3 | 3 строки PENDING (`SD1-D2-23`, `SD1-D2-24`, `SD1-AMX-09`) ⇒ **41/44 подтверждены** |

Оба среза красные ожидаемо: это незакрытые срезы в работе, а не дефект слияния. Состояние строк
я не менял — карты этих задач пришли из master без правок.

## 8. Остаточные пробелы (честно, не блокируются этой задачей)

1. **Доказательства 13 фич линии релиза отсутствуют в этом чекауте.** Карты скопированы, но каталоги
   `evidence/` этих фич есть только на линии релиза: **1725 строк** ссылаются на артефакты, которых нет
   в master (из 5064 строк скопированных карт). Это унаследованное состояние ветки, а не следствие слияния:
   до сверки этих карт в master не было вовсе. Проверять их доказательства нужно на линии релиза или
   переносить каталоги целиком отдельной задачей.
2. **Два файла входов владельца лежат на диске и не зарегистрированы** ни на одной линии:
   `plans/owner_inputs/2026-11-10-vector-memory-no-settings.md` (`14054d9dc846…`) и
   `plans/owner_inputs/2026-11-10-video-commands-final-contract.md` (`456fe1cd4044…`).
   Из-за них `workflow_progress.py` не сертифицирует агрегат (`measurable: false`), хотя проценты уже считает.
   Регистрировать их я не стал: это приёмка входа владельца, которая идёт в параллельной сессии (там же, где
   Регистрировать их я не стал, но сами файлы сохранены в Git без изменений, чтобы исходный текст владельца не потерялся.
   `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING` с `reconciled: false`), и выдумывать им задачу-цель нельзя.
3. **`slice-graph-p0-hotfix.json` отсутствует на обеих линиях** — унаследованный битый указатель.
4. **`plans/features/evol/` не отслеживается в HEAD.** Локальная копия карты (540 строк) была
   неотслеживаемым огрызком; канон теперь 2398 строк из линии релиза.
5. `workflow_lineage.py --compare-ref release/2.58.175` после слияния показывает `only_reference_*` пустыми
   (ничего не потеряно) и оставшиеся расхождения: `source_sha256` у 4 задач и 5 входов — там линия релиза
   хранила устаревший хэш, а выжившее значение совпадает с файлом на диске (проверено); плюс намеренные
   различия по `epic-experience` (две карты) и `evol-reply-context-integrity-01` (`BUILDING` в master).

## 9. Что скопировано из линии релиза дополнительно

Чтобы скопированные карты были проверяемы, вместе с ними перенесены только текстовые спутники:

- `plans/features/asap-evol-anticliche-memory-admin-ux/slice-graph.json`
- `plans/features/asap-fc-voice-01/slice-graph.json`
- `plans/features/asap-speech-arch/source-owner-p0-hotfix-chained-2026-10-25.md`
- `plans/features/asap-speech-arch/source-owner-speech-simplify-2026-10-25.md`
- `plans/features/behavior-gates-simplification/slice-graph.json`
- `plans/features/epic-cm-visual-01/slice-graph.json`
- `plans/features/epic-experience-learning-performance-help/source-2026-11-02-epic-and-parity.md`
- `plans/features/epic-prompt-versioning-ux-01/slice-graph.json`
- `plans/features/evol-reply-context-integrity-01/slice-graph.json`
- `plans/features/goodmorning-quantum-media/slice-graph.json`
- `plans/features/hotfix-meme-publication-initiative-ui/slice-graph.json`
- `plans/features/meme-pipeline-refactor-01/slice-graph.json`
- `plans/features/pvr-fc-corrective-01/slice-graph.json`
- `plans/features/remove-legacy-rephrasing/slice-graph.json`
- `plans/features/unified-reply/slice-graph.json`
- `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md`
- `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md`
- `plans/owner_inputs/2026-11-02-experience-learning-performance-help.md`
- `plans/owner_inputs/2026-11-02-limits-economics-decision.md`
- `plans/owner_inputs/2026-11-02-meme-image-only-fix.md`
- `plans/owner_inputs/2026-11-02-narrow-viewport-decision.md`
- `plans/owner_inputs/2026-11-03-epic-cm-visual-01.md`
- `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md`
- `plans/owner_inputs/2026-11-03-hotfix-meme-publication-initiative-ui.md`
- `plans/owner_inputs/2026-11-03-initiative-independence-coordination.md`
- `plans/owner_inputs/2026-11-03-meme-command-autodelete.md`
- `plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md`
- `plans/owner_inputs/2026-11-03-meme-pipeline-refactor-01.md`
- `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md`
- `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md`
- `plans/owner_inputs/2026-11-05-goodmorning-quantum-media.md`
- `plans/owner_inputs/2026-11-05-pvr-fc-corrective-01.md`
- `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`
- `plans/owner_inputs/2026-11-05-unified-reply.md`

## 10. Дефект 1 — двойной владелец карты

`plans/features/evol-reply-context-integrity/requirements-map.json` числился сразу у двух задач
(`evol-reply-context-integrity-01` и `reply-context-integrity-rci`), из-за чего агрегат прогресса не считался.

Причина: объединение `maps[]` сложило две разные регистрации одной карты. По данным реестра владелец
однозначен — у карты `source_path` = `plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md`,
и это ровно `source_path` задачи `reply-context-integrity-rci`; её собственное примечание говорит, что срез
RCI-01..05 зарегистрирован отдельным id, потому что id `evol-reply-context-integrity-01` занят эпиком v5.

| Задача | Карта | Строк |
|---|---|---|
| `reply-context-integrity-rci` | `plans/features/evol-reply-context-integrity/requirements-map.json` | 18 (RCI-01..06) |
| `evol-reply-context-integrity-01` | `plans/features/evol-reply-context-integrity-01/requirements-map.json` | 355 (RC-*) |

Пересечения req_id между этими картами нет (0 общих), поэтому ни одна строка не потеряна и у каждой задачи
осталась своя карта. После правки карт с двумя владельцами — 0, и агрегат считается.

## 11. Дефект 2 — линия относительно выкаченного коммита 34213999

`2.58.175` выкачен с `34213999`; вершина ветки `release/2.58.175` — `e4fc5a8c`. Разница между ними в `plans/`:

```
plans/features/mod-acl-ux-01/evidence/m2/m2-deploy-2.58.175.md | 222 +++++++++++++++++++++
1 file changed, 222 insertions(+)
```

То есть реестр задач/входов на выкаченном коммите совпадает с вершиной ветки (44 задачи, 55 входов),
а единственное отличие — добавленная позже deploy-заметка. Объединение сделано из `e4fc5a8c`, значит
оно покрывает и `34213999`.

После объединения `workflow_lineage.py --compare-ref 34213999` показывает:

- `only_reference_task_ids`: **[]**, `only_reference_input_ids`: **[]** — с линии выката не потеряно ничего;
- `only_current_task_ids`: 5 задач, `only_current_input_ids`: 11 входов — это более новая работа master, она по определению отсутствует в выкате;
- `needs_reconciliation` остаётся `true`, и причины конкретны:
  - `source_sha256` у 4 задач и 5 входов: линия выката хранит устаревший хэш, а выжившее значение
    совпадает с файлом на диске (проверено побайтово) — то есть расхождение в пользу текущей книги;
  - `evol-reply-context-integrity-01`: `BUILDING` в master против `PENDING` в выкате (более новая работа master);
  - `epic-experience-learning-performance-help`: `maps` отличаются, потому что карта разделена на две
    (см. раздел 3) — номера строк выката теперь лежат в `requirements-map-epic-parity.json`;
  - 4 карты помечены `changed_req_ids`: это и есть точки union (`memory-cognitive-02`, `menu-01`,
    `evol-reply-context-integrity`, `epic-experience`), все решения по ним перечислены в разделе 4.

## 12. `source_inventory` — готовый фрагмент для слияния

Файл: `plans/reports/source-inventory-fragment-2026-11-10.json`. Это ровно значение ключа `source_inventory`
(`source_path` + `heading_level` + `sections[]`); идентификаторы и sha256 взяты из
`workflow_progress.py --inventory-template`, ничего не придумано.

Важно: у разделов валидатор `workflow_progress.py` принимает `coverage_refs` как **список путей карт**,
принадлежащих связанной задаче (для входов формат другой — объекты с `task_id`/`map`/`req_ids`).
Поэтому req_id переданы дополнительным полем `requirement_refs` в каждом разделе: их видно человеку
и они проверяемы, но схему инструмента не ломают.

Итог: 32 разделов, из них `mapped` — 31, `context` — 1, `unreviewed` — 0.

| # | Раздел | Строки | Режим | Задача | Карта | req_ids (реальные строки) |
|---|---|---|---|---|---|---|
| 1 | EVOL — Adminbot Evolution | 1–910 | mapped | evol | `evol/requirements-map.json` | EVOL-DoD, EVOL-045, EVOL-044, EVOL-043, EVOL-042, EVOL-041, EVOL-040, EVOL-039 |
| 2 | EVOL — дополнительная корректирующая директива: социальный контекст, в | 911–1157 | mapped | evol | `evol/requirements-map.json` | EVOL-VIDEO-INTENT, EVOL-SOCIAL-FRAME, EVOL-GLASS-SEAM, EVOL-FACTCHECK-CRITICAL |
| 3 | EVOL — дополнительное поручение: Source Code Reader и Когнитивная карт | 1158–1362 | mapped | evol | `evol/requirements-map.json` | EVOL-SRC-READER-S7, EVOL-SRC-READER-S6, EVOL-SRC-READER-S5, EVOL-SRC-READER-S4, EVOL-SRC-READER-S3, EVOL-SRC-READER-S2, EVOL-SRC-READER-S1, EVOL-SRC-READER-R2 |
| 4 | ASAP-FC-ADMISSION-01 — ложный отказ фактчека при наличии проверяемого  | 1363–1432 | mapped | evol | `evol/requirements-map.json` | ASAP-FC-ADMISSION-01, ASAP-VISION-SYNC-01, ASAP-VISION-SYNC-ADMIN-01 |
| 5 | ASAP-VISION-SYNC-01 — Глобальная синхронизация медиаанализа и потребит | 1433–1616 | mapped | evol | `evol/requirements-map.json` | ASAP-VISION-SYNC-ADMIN-01, ASAP-VISION-SYNC-01, EVOL-DoD |
| 6 | ASAP-FC-EVIDENCE-STYLE-02 — полнота поиска, релевантность доказательст | 1617–1750 | mapped | evol | `evol/requirements-map.json` | ASAP-FC-ES-TELEMETRY, ASAP-FC-ES-STYLE, ASAP-FC-ES-STATUS, ASAP-FC-ES-SOURCES, ASAP-FC-ES-PLANNER, ASAP-FC-ES-CLAIM, ASAP-FC-ES-BOUND, ASAP-FC-ES-ACCEPT |
| 7 | ASAP-UI-02 — единый дизайн-контракт, навигация и устранение неоднознач | 1751–2007 | mapped | evol | `evol/requirements-map.json` | ASAP-UI-02-DOD, ASAP-UI-02-18, ASAP-UI-02-17B, ASAP-UI-02-17, ASAP-UI-02-16T, ASAP-UI-02-16, ASAP-UI-02-15, ASAP-UI-02-14 |
| 8 | ASAP-EVIDENCE-ROUTING-01 v3 — Evidence-first без лишнего веб-поиска, д | 2008–2442 | mapped | evol | `evol/requirements-map.json` | ER-S46, ER-S45, ER-S44, ER-S43, ER-S42, ER-S41, ER-S40, ER-S39 |
| 9 | ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 — восстановление Summary/Cover, и | 2443–2731 | mapped | evol | `evol/requirements-map.json` | SC-44, SC-43, SC-42, SC-41, SC-40, SC-39, SC-38, SC-37 |
| 10 | ASAP-FC-VOICE-01 — восстановить аргументативный голос старого FactChec | 2732–2901 | mapped | evol | `evol/requirements-map.json` | ASAP-VISION-SYNC-01, ASAP-VISION-SYNC-ADMIN-01, EVOL-FACTCHECK-CRITICAL, EVOL-DoD, EVOL-COG-MAP, EVOL-034, EVOL-014, EVOL-016 |
| 11 | ASAP-EVOL-ANTICLICHE-MEMORY-ADMIN-UX-2026-11-02 — ЧИСТОВОЕ ТЗ НА РЕАЛИ | 2902–4029 | mapped | asap-evol-anticliche-memory-admin-ux | `asap-evol-anticliche-memory-admin-ux/requirements-map.json` | MEM-ACC-SEMANTIC, MEM-ACC-TOOLS, UI-MEME-GLOBAL, UI-MODULES-EXISTING-ASSETS, MEM-TRACE-FIELDS, MEM-ACC-RECONSTRUCTION, AC-GROUPING-RULES, AC-FINAL-REVIEWER |
| 12 | EPIC-EXPERIENCE-LEARNING-ADMIN-PERFORMANCE-HELP — FINAL IMPLEMENTATION | 4030–4077 | mapped | epic-experience-learning-performance-help | `epic-experience-learning-performance-help/requirements-map.json`<br>`epic-experience-learning-performance-help/requirements-map-epic-parity.json` | P-SPEC-PARITY, PAR-01, P-DELIV-04<br>EP-GUARD-ARCH, P-SPEC-PARITY, EP-H-HELP |
| 13 | E. Полноценное самообучение: опыт, саморефлексия, пересмотр и перенос  | 4078–4197 | mapped | epic-experience-learning-performance-help | `epic-experience-learning-performance-help/requirements-map.json`<br>`epic-experience-learning-performance-help/requirements-map-epic-parity.json` | P-BOOT-05, P-API-03, P-GATE-00, P-FE-01, P-BOOT-04, P-BOOT-01, P-MEAS-05, P-MEAS-04<br>EP-E7-6, EP-E5-1, EP-E4-1, EP-E3-4, EP-E4-3, EP-E3-1, EP-E8-DOD, EP-E7-5 |
| 14 | P. Ускорение загрузки и работы админки (Telegram Mini App + desktop) | 4198–4281 | mapped | epic-experience-learning-performance-help | `epic-experience-learning-performance-help/requirements-map.json`<br>`epic-experience-learning-performance-help/requirements-map-epic-parity.json` | P-GATE-00, P-GOAL-01, P-MEAS-02, P-DELIV-04, P-BOOT-01, P-MEAS-01, P-VER-15, P-DELIV-02<br>P-GENUINE, EP-P3-4-16, EP-P3-1-2, EP-P3-1-4, EP-P3-3-10, EP-P3-5-20, P-GATE-00, EP-P3-2-6 |
| 15 | H. ПОСЛЕДНЯЯ ОТДЕЛЬНАЯ ЗАДАЧА: актуализировать «Справку» целиком | 4282–4336 | mapped | epic-experience-learning-performance-help | `epic-experience-learning-performance-help/requirements-map.json`<br>`epic-experience-learning-performance-help/requirements-map-epic-parity.json` | P-DELIV-04, P-BOOT-04, P-BOOT-03<br>EP-H-HELP, EP-E7-5, EP-E3-5 |
| 16 | Финальная организация исполнения и доказательства готовности | 4337–4578 | context | — | — | — |
| 17 | HOTFIX-MEME-PUBLICATION-AND-INITIATIVE-UI — обязательное корректирующе | 4579–4707 | mapped | hotfix-meme-publication-initiative-ui | `hotfix-meme-publication-initiative-ui/requirements-map.json` | HMF-ACC-02, HMF-UI-07, HMF-ACC-03, HMF-UI-06, HMF-UI-05, HMF-UI-02, HMF-ACC-10, HMF-UI-04 |
| 18 | EPIC-CM-VISUAL-01 — Полный редизайн визуализации когнитивной карты Adm | 4708–5022 | mapped | epic-cm-visual-01 | `epic-cm-visual-01/requirements-map.json` | CMV-VIS-14, CMV-REP-02, CMV-NODE-01, CMV-HDR-02, CMV-INV-02, CMV-INT-01, CMV-PERF-04, CMV-HDR-01 |
| 19 | EVOL-REPLY-CONTEXT-INTEGRITY-01 — Цель, контекст, чистая речь и честны | 5023–5534 | mapped | evol-reply-context-integrity-01 | `evol-reply-context-integrity-01/requirements-map.json` | RC-FIN-DOD, RC-FIN-REVIEWER-DUTY, RC-CF-REVIEWER-MATCH, RC-GSB-KEYS-VS-RELATIONS, RC-S118, RC-MED-LINKED, RC-CF-RULE, RC-MED-TEXTONLY |
| 20 | EPIC-PROMPT-VERSIONING-UX-01 — единый контроль версий промптов и UX ре | 5535–5650 | mapped | epic-prompt-versioning-ux-01 | `epic-prompt-versioning-ux-01/requirements-map.json` | PVR-REV-01, PVR-EXEC-01, PVR-BASE-07, PVR-REV-04, PVR-REV-03, PVR-INV-02, PVR-GOAL-01, PVR-INV-01 |
| 21 | UNIFIED-REPLY — единый интеллект ответа, поиск, контекст и интерфейс | 5651–6156 | mapped | unified-reply | `unified-reply/requirements-map.json` | UR-RES-02, UR-30.2, UR-07.1, UR-28.5, UR-23.2, UR-28.2, UR-RES-04, UR-30.3 |
| 22 | Adminbot — PVR-FC-CORRECTIVE-01 | 6157–6202 | mapped | pvr-fc-corrective-01 | `pvr-fc-corrective-01/requirements-map.json` | A3.2, A3.5, A3.1, A3.4, FC-02.1, A3, FC-04.6, PVR-01.6 |
| 23 | Блок PVR. Версионирование и UI | 6203–6279 | mapped | pvr-fc-corrective-01 | `pvr-fc-corrective-01/requirements-map.json` | PVR-03.1, PVR-06.1, PVR-05.1, PVR-04.2.1, PVR-04.3.1, PVR-04.2.4, PVR-04.0, PVR-03.2 |
| 24 | Блок FC. Качество фактчека, источников и вывода | 6280–6347 | mapped | pvr-fc-corrective-01 | `pvr-fc-corrective-01/requirements-map.json` | FC-06.2, FC-07.1, FC-02.2, FC-02.3, FC-01.1, FC-04.6, FC-03.4, FC-04.7 |
| 25 | Совместимость, реализация и приёмка | 6348–6435 | mapped | pvr-fc-corrective-01 | `pvr-fc-corrective-01/requirements-map.json` | C5.4, C4.10, C5.3, C1.9, C1.1, FC-04.1, C4.14, C4.11 |
| 26 | Adminbot — BEHAVIOR-GATES-SIMPLIFICATION-01 | 6436–6701 | mapped | behavior-gates-simplification-01 | `behavior-gates-simplification/requirements-map.json` | BGS-03.4, BGS-04.10, BGS-04.3, BGS-00.6, BGS-00.5, BGS-00.3, BGS-00.2, BGS-06.3 |
| 27 | ADMINBOT — REMOVE-LEGACY-REPHRASING / FINAL CORRECTIVE v2.0 | 6702–6945 | mapped | remove-legacy-rephrasing-01 | `remove-legacy-rephrasing/requirements-map.json` | R-DEF.BAN, R-ADM.5, R-OPS.ALLOWED, R-06.1, R-01.2, R-02.3, R-FAIL.6, R-CONF.13 |
| 28 | EPIC-MEMORY-COGNITIVE-02 — Человекоподобная память, качественный Graph | 6946–7419 | mapped | epic-memory-cognitive-02 | `memory-cognitive-02/requirements-map.json` | MEM-04.6-RUNTIME, MEM-06-RUNTIME, SC-21, MEM-06.9, MEM-07.5, MEM-05.5, MEM-07.4, INV-04 |
| 29 | ADMINBOT — CLEAN FINAL OWNER SPEC: TIME / REPLY / VISION / RBAC / YOOM | 7420–8281 | mapped | EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108 | `epic-adminbot-corrective-ym-nost-20261108/requirements-map.json` | SRC-0384, PAY-YM-SIGNATURE, NOST-LIVE-QUALITY, SRC-0642, SRC-0790, SRC-0522, VISION-OWN-PROVENANCE, SRC-0460 |
| 30 | ADMINBOT — VMQ-ONTO-01: интеграция голосового контекста, продольной па | 8282–9483 | mapped | vmq-onto-01 | `vmq-onto-01/requirements-map.json` | QM-04, QM-01, QM-03, QM-08, QM-09, QM-07, Q-04, Q-03 |
| 31 | ADMINBOT — SELF-DIAG-01 | 9484–10015 | mapped | self-diag-01 | `self-diag-01/requirements-map.json` | SD1-D7-02, SD1-D5-12, SD1-AC-23, SD1-AC-11, SD1-GRAL-04, SD1-D6-07, SD1-AC-09, SD1-D2-31 |
| 32 | ADMINBOT — MOD-ACL-UX-01 | 10016–10747 | mapped | mod-acl-ux-01 | `mod-acl-ux-01/requirements-map.json` | MAC-LSN-10, MAC-LSN-04, MAC-LSN-02, MAC-LSN-01, MAC-LSN-11, MAC-LSN-07, MAC-LSN-03, MAC-LSN-06 |

Как выбирались req_ids: если карта построена из самого `current_task.md` (это карта `evol`), строки берутся
по точному попаданию `source_line` в диапазон раздела — это буквальное покрытие. Для остальных карт —
по совпадению текста раздела с полями `acceptance`/`source_excerpt`/`reason` строки, с порогом; все
указанные req_id существуют в указанной карте и имеют `disposition: required` (проверяется тем же инструментом).

## 13. `coverage_refs` для поручений владельца

Файл: `plans/reports/coverage-refs-fragment-2026-11-10.json` — словарь `id поручения -> [coverage_ref]`,
где каждый ref это `{task_id, map, req_ids}` с реальными обязательными строками.

Метод (по убыванию надёжности):

1. **req_id прямо названы** во входном документе или примечании — берутся буквально;
2. **якорь по слайсу** для двух корректировок 10.11: «нет настроек» = слайс `M4A`, «доступ закрыт» = слайс `M1` карты `mod-acl-ux-01`;
3. **карта построена из этого же документа** (`source_path` карты = `source_path` входа);
4. **совпадение текста** с приёмкой строк — самый слабый случай, помечен ниже.

| Поручение | Метод | refs |
|---|---|---|
| `OI-2026-10-25-P0-CORRECTIVE` | source-doc | 1 карт(ы) |
| `OI-2026-10-25-REPORT-FORMAT` | text | 2 карт(ы) |
| `OI-2026-10-25-P0-FACTCHECK` | source-doc | 1 карт(ы) |
| `OI-2026-10-25-FC-WHOLE-POST` | text | 1 карт(ы) |
| `OI-2026-10-25-FC-CONTEXT-WINDOW` | text | 1 карт(ы) |
| `OI-2026-10-25-FC-WIDE-DEFAULT` | text | 1 карт(ы) |
| `OI-2026-10-25-PLANS-RECONCILE` | skip | — |
| `OI-2026-10-25-UNIFIED-INTAKE` | text | 2 карт(ы) |
| `OI-2026-10-26-P0-DELTA` | text | 2 карт(ы) |
| `OI-2026-10-26-NO-META-SCOPE` | text | 2 карт(ы) |
| `OI-2026-10-26-ASAP5-QUEUED` | text | 1 карт(ы) |
| `OI-2026-10-27-POST-ASAP5` | text | 1 карт(ы) |
| `OI-2026-10-27-NOSTALGIA-REWORK` | named | 1 карт(ы) |
| `OI-2026-10-28-FACTCHECK-POST-RELEASE` | text | 1 карт(ы) |
| `OI-2026-10-28-ADMIN-CACHE-TOGGLE-SAVE` | source-doc | 1 карт(ы) |
| `OI-2026-10-28-LOCAL-WORKSPACE-CLEANUP` | skip | — |
| `OI-2026-10-28-WORKTREE-FINAL-CLEANUP` | skip | — |
| `OI-2026-10-29-HISTORY-ANALYSIS` | text | 1 карт(ы) |
| `OI-2026-10-29-RELEASE-THEN-MIGRATE` | source-doc | 2 карт(ы) |
| `OI-2026-10-29-FINAL-DECOMMISSION` | text | 1 карт(ы) |
| `OI-2026-10-29-EVOL-LAUNCH` | named | 1 карт(ы) |
| `OI-2026-10-31-EVOL-ADDENDUM` | named | 1 карт(ы) |
| `OI-2026-10-31-EVOL-SRC-COG` | text | 1 карт(ы) |
| `OI-2026-10-31-ASAP-FC-ADMISSION` | text | 1 карт(ы) |
| `OI-2026-10-31-ASAP-VISION-SYNC` | named | 1 карт(ы) |
| `OI-2026-10-31-ASAP-VISION-SYNC-WATCHDOG` | text | 1 карт(ы) |
| `OI-2026-10-31-ASAP-FC-EVIDENCE-STYLE` | named | 1 карт(ы) |
| `OI-2026-10-31-NAV-CONTRACT` | named | 1 карт(ы) |
| `OI-2026-10-31-ASAP-UI-02` | text | 1 карт(ы) |
| `OI-2026-11-01-ASAP-EVIDENCE-ROUTING` | text | 1 карт(ы) |
| `OI-2026-11-01-SUMMARY-COVER-INTEGRITY` | named | 1 карт(ы) |
| `OI-2026-11-07-MEMORY-COGNITIVE-02` | named | 2 карт(ы) |
| `OI-2026-11-07-CONTEXT-INTEGRITY-FACTCHECK` | source-doc | 2 карт(ы) |
| `OI-2026-11-08-EPIC-ADMINBOT-CORRECTIVE-YM-NOST` | named | 7 карт(ы) |
| `OI-2026-11-08-MEMORY-07-REVIEW-DISCIPLINE` | skip | — |
| `OI-2026-11-09-MEMORY-07-ENABLE-AND-QUALITY` | text | 1 карт(ы) |
| `OI-2026-11-09-VMQ-ONTO-01` | source-doc | 2 карт(ы) |
| `OI-2026-11-09-VMQ-QRNG-PROVIDER-MANAGEMENT` | text | 1 карт(ы) |
| `OI-2026-11-09-SELF-DIAG-01` | source-doc | 1 карт(ы) |
| `OI-2026-11-09-SELF-DIAG-ACCESS-MATRIX` | text | 1 карт(ы) |
| `OI-2026-11-09-MOD-ACL-UX-01` | source-doc | 1 карт(ы) |
| `OI-2026-11-09-LESSON-STRATEGY-HUMAN-GATE` | skip | — |
| `OI-2026-11-09-VECTOR-MEMORY-DENIED-LIVE` | slice | 1 карт(ы) |
| `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING` | skip | нет |
| `OI-2026-11-02-PERF-PARITY` | text | 1 карт(ы) |
| `OI-2026-11-02-LIMITS-DECISION` | named | 1 карт(ы) |
| `OI-2026-11-02-ASAP-FC-VOICE-01` | source-doc | 1 карт(ы) |
| `OI-2026-11-02-NARROW-VIEWPORT` | text | 1 карт(ы) |
| `OI-2026-11-02-ANTICLICHE-MEMORY-ADMIN-UX` | source-doc | 1 карт(ы) |
| `OI-2026-11-02-EXPERIENCE-LEARNING-PERFORMANCE-HELP` | named | 1 карт(ы) |
| `OI-2026-11-02-PERFORMANCE-PARITY` | named | 2 карт(ы) |
| `OI-2026-11-02-MEME-IMAGE-ONLY` | source-doc | 1 карт(ы) |
| `OI-2026-11-03-MEME-PIPELINE-REFACTOR` | source-doc | 1 карт(ы) |
| `OI-2026-11-03-MEME-CMD-AUTODELETE` | text | 1 карт(ы) |
| `OI-2026-11-03-MEME-JOKE-SPEECH-LAYERS` | text | 1 карт(ы) |
| `OI-2026-11-03-INITIATIVE-INDEPENDENCE` | text | 1 карт(ы) |
| `OI-2026-11-03-MEME-PUBLICATION-HOTFIX` | source-doc | 1 карт(ы) |
| `OI-2026-11-03-EPIC-CM-VISUAL-01` | source-doc | 1 карт(ы) |
| `OI-2026-11-03-REPLY-CONTEXT-INTEGRITY-V5` | source-doc | 1 карт(ы) |
| `OI-2026-11-04-PROMPT-VERSIONING-UX` | source-doc | 1 карт(ы) |
| `OI-2026-11-05-UNIFIED-REPLY` | named | 1 карт(ы) |
| `OI-2026-11-05-PVR-FC-CORRECTIVE-01` | named | 1 карт(ы) |
| `OI-2026-11-05-GOODMORNING-QUANTUM-MEDIA` | source-doc | 1 карт(ы) |
| `OI-2026-11-05-BEHAVIOR-GATES-SIMPLIFICATION` | named | 1 карт(ы) |
| `OI-2026-11-05-REMOVE-LEGACY-REPHRASING-V2` | source-doc | 1 карт(ы) |
| `OI-2026-11-01-CURRENT-TASK-SNAPSHOT-MISSING` | skip | — |
| `OI-2026-11-10-VECTOR-MEMORY-NO-SETTINGS` | extra | 1 карт(ы) |
| `OI-2026-11-10-VIDEO-COMMANDS-FINAL-CONTRACT` | extra | нет |
| `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING` | blocked | нет |

Блокеры, которые я не стал обходить выдумкой:

- `OI-2026-11-10-VIDEO-COMMANDS-FINAL-CONTRACT` и `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING`: у задачи
  `smart-module-semantic-routing-p0` **нет карты требований** (`maps: []`), поэтому указать реальные req_ids
  физически нельзя. Нужна карта (это работа PM/Builder), после неё refs появятся;
- оба файла `2026-11-10-*.md` не зарегистрированы в `owner_inputs` — регистрация за Orchestrator.

## 14. Состояние инструментов после объединения

`workflow_progress.py --scope-file plans/progress_scope.json --json`:

- отказ «одна карта привязана к двум разным поручениям» исчез, агрегат считается:
  задач 49, из них `VERIFIED` 13, `READY_FOR_LIVE` 6, `REVIEW` 1, `BUILDING` 17, `PENDING` 10, `WAITING_EXTERNAL` 2;
- `owner_inputs`: 66 зарегистрировано, 65 reconciled, в ожидании 1 (`OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING`);
- `measurable: false` остаётся, и причины уже не про карты: незакрытая приёмка входа 10.11,
  отсутствующий `source_inventory` (готовый фрагмент — раздел 12), отсутствующие `coverage_refs`
  (готовый фрагмент — раздел 13) и два незарегистрированных файла входов 10.11.

## 15. Финальный список id задач (49)

- `EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108`
- `add-exp-2026-10-19`
- `add-tr-2026-10-19`
- `asap-evol-anticliche-memory-admin-ux`
- `asap-fc-voice-01`
- `asap-speech-arch`
- `asap2-direct-chat`
- `asap3-corrective`
- `asap5-multimodal`
- `asap8-v6.3`
- `behavior-gates-simplification-01`
- `cfg-01-07`
- `embed-identity-compat`
- `epic-cm-visual-01`
- `epic-experience-learning-performance-help`
- `epic-memory-cognitive-02`
- `epic-prompt-versioning-ux-01`
- `evol`
- `evol-reply-context-integrity-01`
- `factcheck-clean-publication`
- `goodmorning-quantum-media`
- `hotfix-meme-publication-initiative-ui`
- `meme-pipeline-refactor-01`
- `menu-01`
- `mod-acl-ux-01`
- `p0-admin-cache-toggle-save`
- `p0-delta-analysis`
- `p0-factcheck-media`
- `p0-factcheck-post-release`
- `p0-factcheck-speech`
- `p0-followup-nostalgia`
- `p0-history-analysis`
- `p0-meme-image-only`
- `p0-nostalgia-rework`
- `p0-save-init-ux`
- `p0-vision-universal`
- `pemsoc-one-reaction`
- `post-asap5-corrective`
- `pvr-fc-corrective-01`
- `release-then-migrate`
- `remove-legacy-rephrasing-01`
- `reply-context-integrity-rci`
- `samples-ux`
- `self-diag-01`
- `smart-module-semantic-routing-p0`
- `soul-1`
- `unified-reply`
- `vmq-onto-01`
- `win-glass-hotfix`

## Приложение A — инвентарь обеих сторон (sha256 до слияния)

| Карта | master sha256 | release sha256 |
|---|---|---|
| `add-exp/requirements-map.json` | `d4c42db798b0afb8` | `d4c42db798b0afb8` |
| `add-tr/requirements-map.json` | `aea75a9455d34a09` | `aea75a9455d34a09` |
| `asap-evol-anticliche-memory-admin-ux/requirements-map.json` | `—` | `3b55d9fb411e9040` |
| `asap-fc-voice-01/requirements-map.json` | `—` | `d7a17478cb494855` |
| `asap-speech-arch/requirements-map-p0-corrective.json` | `dcfa7d878a479761` | `dcfa7d878a479761` |
| `asap-speech-arch/requirements-map-p0-hotfix.json` | `66c177734c160020` | `66c177734c160020` |
| `asap-speech-arch/requirements-map-speech-simplify.json` | `8d52417f033ecd45` | `8d52417f033ecd45` |
| `asap-speech-arch/requirements-map.json` | `4a8d6b1e276c1651` | `4a8d6b1e276c1651` |
| `asap2-direct-chat/requirements-map.json` | `b4b50d6420b02916` | `b4b50d6420b02916` |
| `asap3-corrective/requirements-map.json` | `7504ff47ef9dd8f4` | `7504ff47ef9dd8f4` |
| `asap5-multimodal/requirements-map.json` | `acc0954f312ccc19` | `acc0954f312ccc19` |
| `asap8-v6-3-live-correction/requirements-map.json` | `3d0b03215021a587` | `3d0b03215021a587` |
| `behavior-gates-simplification/requirements-map.json` | `—` | `61c7e6cb4698d517` |
| `cfg/requirements-map.json` | `3767d9bcbe5cd5ff` | `3767d9bcbe5cd5ff` |
| `embed-identity-compat/requirements-map.json` | `f5d7f354ebedbcd1` | `f5d7f354ebedbcd1` |
| `epic-adminbot-corrective-ym-nost-20261108/requirements-map.json` | `d8697b79dd02dde4` | `—` |
| `epic-cm-visual-01/requirements-map.json` | `—` | `4226de9c250a0342` |
| `epic-experience-learning-performance-help/requirements-map-epic-parity.json` | `—` | `—` |
| `epic-experience-learning-performance-help/requirements-map.json` | `ea043c1c58299bc4` | `7575c6d497ef48ae` |
| `epic-prompt-versioning-ux-01/requirements-map.json` | `—` | `c2a963be382cbf45` |
| `evol-reply-context-integrity-01/requirements-map.json` | `—` | `01efa190f1130fd0` |
| `evol-reply-context-integrity/requirements-map.json` | `276b725211a3a3e1` | `8b407b0d59db75f0` |
| `evol/requirements-map.json` | `84e59c655720f5e2` | `cdf9f0b2cea91f7b` |
| `factcheck-clean-publication/requirements-map.json` | `15a392a89f493200` | `15a392a89f493200` |
| `goodmorning-quantum-media/requirements-map.json` | `—` | `51ca518550582c17` |
| `hotfix-meme-publication-initiative-ui/requirements-map.json` | `—` | `dc6483d54cae91d4` |
| `meme-pipeline-refactor-01/requirements-map.json` | `—` | `0e7f1298031e7478` |
| `memory-cognitive-02/requirements-map.json` | `916ec1c1eb0b0392` | `628a403605f8099f` |
| `menu-01/requirements-map.json` | `dc4ae12ff01d52b1` | `a897bca7e562ed0a` |
| `mod-acl-ux-01/requirements-map.json` | `ea967a0a639d409a` | `—` |
| `p0-admin-cache-toggle-save/requirements-map.json` | `7853a219083e933d` | `7853a219083e933d` |
| `p0-corrective-factcheck-speech/requirements-map.json` | `3424a356f6f57e8b` | `3424a356f6f57e8b` |
| `p0-delta-analysis/requirements-map.json` | `1fc4f5d0f6e2c695` | `1fc4f5d0f6e2c695` |
| `p0-factcheck-media/requirements-map.json` | `dbdcd5fa9eba85bc` | `dbdcd5fa9eba85bc` |
| `p0-factcheck-post-release/requirements-map.json` | `420d888202b970b1` | `420d888202b970b1` |
| `p0-history-analysis/requirements-map.json` | `9b05ac4ae171582c` | `9b05ac4ae171582c` |
| `p0-meme-image-only/requirements-map.json` | `—` | `c0de1ef6b34e563c` |
| `p0-nostalgia-rework/requirements-map.json` | `091187b5abf6c18e` | `091187b5abf6c18e` |
| `p0-save-init-ux/requirements-map-followup.json` | `8cdbf92683e8270d` | `8cdbf92683e8270d` |
| `p0-save-init-ux/requirements-map.json` | `25aa41deb300953c` | `25aa41deb300953c` |
| `p0-vision-universal/requirements-map.json` | `6875c34eb0af48bc` | `6875c34eb0af48bc` |
| `pemsoc-one-reaction/requirements-map.json` | `d7ea203d7541b8ba` | `d7ea203d7541b8ba` |
| `post-asap5-corrective/requirements-map.json` | `7994af6709647314` | `7994af6709647314` |
| `pvr-fc-corrective-01/requirements-map.json` | `—` | `15c2964c9c903a89` |
| `release-then-migrate/requirements-map.json` | `bbebef304d767d38` | `bbebef304d767d38` |
| `remove-legacy-rephrasing/requirements-map.json` | `—` | `93d87dbe515da007` |
| `samples-ux/requirements-map.json` | `6b458282bb3c4d3a` | `6b458282bb3c4d3a` |
| `self-diag-01/requirements-map.json` | `ebc3c27537c53d54` | `—` |
| `soul-1/requirements-map-amendment.json` | `66acb4bf696db5c8` | `66acb4bf696db5c8` |
| `soul-1/requirements-map.json` | `85120b3b2e2ddc62` | `85120b3b2e2ddc62` |
| `unified-reply/requirements-map.json` | `—` | `1f1ee7a7044510c9` |
| `vmq-onto-01/requirements-map.json` | `0ea06bfa346e394a` | `—` |
| `win-glass-hotfix/requirements-map.json` | `763e2d780e112a60` | `8a6a326282c6956b` |

## Приложение B — все конфликты статусов (398 записей суммарно с приёмкой и evidence)

| Карта | req_id | source_id | master | release | выбран | правило |
|---|---|---|---|---|---|---|
| `evol-reply-context-integrity/requirements-map.json` | `RCI-04` | | REVIEW | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol-reply-context-integrity/requirements-map.json` | `RCI-05` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol-reply-context-integrity/requirements-map.json` | `RCI-06` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-001` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-001` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-001` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-002` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-002` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-002` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-003` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-003` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-003` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-004` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-004` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-004` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-005` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-005` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-006` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-007` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-007` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-008` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-008` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-009` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-009` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-010` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-011` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-011` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-012` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-012` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-012` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-012` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-013` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-013` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-014` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-015` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-016` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-017` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-018` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-019` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-020` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-020` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-020` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-020` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-021` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-022` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-023` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-024` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-024` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-024` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-024` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-025` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-026` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-027` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-028` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-028` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-028` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-028` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-028` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-029` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-029` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-029` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-029` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-030` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-030` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-030` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-030` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-030` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-031` | | PENDING | READY_FOR_LIVE | **READY_FOR_LIVE** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-032` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-033` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-034` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-035` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-036` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-037` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-038` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-039` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-040` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-040` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-042` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-042` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `evol/requirements-map.json` | `EVOL-042` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.4` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.5` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.6` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.7` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.8` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-03.3` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-03.4` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-03.9` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-04.3` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-04.4` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-04.6` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.1` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.2` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.5` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.7` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.1` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.2` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.4` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.5` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.6` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEM-08-S1` | | VERIFIED | PENDING | **VERIFIED** | more advanced side (L) has resolvable evidence |
| `memory-cognitive-02/requirements-map.json` | `MEMORY-01` | | PENDING | VERIFIED | **VERIFIED** | more advanced side (R) has resolvable evidence |

## Приложение C — конфликты состава доказательств

| Карта | req_id | master | release | решение |
|---|---|---|---|---|
| `evol-reply-context-integrity/requirements-map.json` | `RCI-01` | 1 entries | 1 entries | kept L evidence — same status: kept richer evidence list |
| `evol-reply-context-integrity/requirements-map.json` | `RCI-02` | 2 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `evol-reply-context-integrity/requirements-map.json` | `RCI-03` | 1 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.1` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.2` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-02.3` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.3` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.4` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-05.6` | 0 entries | 3 entries | kept R evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-06-RUNTIME` | 2 entries | 1 entries | kept L evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-07.3` | 3 entries | 0 entries | kept L evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEM-08-S2` | 1 entries | 0 entries | kept L evidence — same status: kept richer evidence list |
| `memory-cognitive-02/requirements-map.json` | `MEMORY-07` | 6 entries | 0 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.1` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.10` | 1 entries | 1 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.2` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.3` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.4` | 3 entries | 3 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.5` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.6` | 1 entries | 1 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.7` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.8` | 4 entries | 4 entries | kept L evidence — same status: kept richer evidence list |
| `menu-01/requirements-map.json` | `MENU-01.9` | 2 entries | 2 entries | kept L evidence — same status: kept richer evidence list |

