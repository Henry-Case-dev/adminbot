# P1 @ 2.58.177 (1a4a9b1b) — привязка доказательств выклада (PM)

Запись PM. Основание — артефакт DevOps
`plans/features/smart-module-semantic-routing/evidence/p1-release-2.58.177.md`
(sha256 `a31aebd8cbd242769db511b8f58d6bbe4741c06f976210ab25488385b96f5460`) и
независимая перепроверка Git-объектов на локальном клоне.

## 1. Что зафиксировано в карте

| Поле карты | Значение |
|---|---|
| `candidate_commit` | `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` |
| `deployed_commit` | `1a4a9b1b1ba7429d54f8ca651ce9629efcda7f8e` |
| Версия | `2.58.177` (предыдущая — `2.58.176` @ `2b7e9c7f`) |
| Схема | `user_version=46`, `schema_migrations=35`, DDL = 0 |
| Артефакт выклада | `evidence/p1-release-2.58.177.md` |
| Эта запись | `evidence/p1-binding-2.58.177.md` |

## 2. Независимая проверка PM (не пересказ отчёта DevOps)

Снято напрямую с локальных Git-объектов, без доверия отчёту:

- `git diff --name-only 2b7e9c7f 1a4a9b1b` — **41 путь**, `654 insertions(+), 233 deletions(-)`.
  Состав: 10 продуктовых файлов (`config/settings.py` + 9 `services/*`), 6 тестовых файлов P1
  с содержательными правками и 25 однострочных version-пинов (24 теста + `plans/docs/param-registry-round1025.meta.md`).
- В дельте **нет** `web/`, `handlers/`, `services/info_service.py`, `info_text.md`, промптов
  и файлов линии D2/ACL (`access.py`, `diagnostic_policy.py`, `output_projection.py`,
  `telegram_role_check.py`, `web/api/access.py`).
- `services/database.py`: blob `5ba74e1e64b68bcf241a54f32edf0c22caa8d772` одинаков в
  `2b7e9c7f` и `1a4a9b1b` — файл не менялся.
- `config/settings.py` на `1a4a9b1b` содержит `APP_VERSION = "2.58.177"` и P1-описание
  снятия pre-gate.

## 3. Строки P1, привязанные фактами выклада

Все записи ниже имеют `candidate_commit = 1a4a9b1b…`, `type = production` или `test`,
и `artifact_path = evidence/p1-release-2.58.177.md`.

| Строка | Статус | Чем доказана |
|---|---|---|
| `SMR-P1-02` | VERIFIED | `DIG_PRE_GATE_ENABLED` — 0 читателей в `services/`, effective `False`; `_dig_pre_gate_block`/`_NOSTALGIA_MARKERS_RE` отсутствуют; dispatch `dig_into_lore` из ностальгической фразы = 0 |
| `SMR-P1-03` | VERIFIED | `CAPABILITY_TOOLS['historical_search'] = ('dig_into_lore','compile_lore_story')` жив на выкате |
| `SMR-P1-05` | VERIFIED | явная команда «Бот, найди …» → `search=True` и шаг `execute_web_search`; 437 тестов на релизном дереве, набор падений широкого прогона идентичен базе |
| `SMR-P1-06` | VERIFIED | текст про картинку без вложения → `is_media_dependent=False`, `vision_intent=True` сам по себе ничего не решает; реальный ход даёт `reason_code='no_target'` |
| `SMR-P1-08` | VERIFIED | грубая коррекция → `correction/medium`, `suspect='aggression'`; брань без содержательной формы → `{'skip':'aggression'}` |
| `SMR-P1-09` | VERIFIED | различие «быстрый детектор пропустил» и «потеря» видно в выводе: `skip` против `suspect` при сохранённой классификации |
| `SMR-P1-13` | VERIFIED | дельта 41 файла не содержит промптов и Personality Core |
| `SMR-SCEN-D2` | READY_FOR_LIVE | in-process: принудительного запуска исторического поиска нет; наблюдение в живом чате — за владельцем |
| `SMR-SCEN-D3` | READY_FOR_LIVE | in-process: содержательная коррекция с бранью не теряется; живость в чате — за владельцем |
| `SMR-SCEN-D4` | READY_FOR_LIVE | in-process: цитата «отвечай короче» → `None`, без кавычек → `short`; живой чат — за владельцем |

## 4. Что осталось PENDING и что именно требуется

Пять строк не закрываются этими фактами — по каждой нужна одна узкая проверка на
выкаченном дереве, без нового ревью всего P1:

| Строка | Почему PENDING |
|---|---|
| `SMR-P1-01` | `services/response_extent.py` не входит в дельту 2.58.177; нужен один статический разбор, что там нет лексического авторитета |
| `SMR-P1-04` | `factcheck_suitability.py`/`temporal_factcheck.py` в дельте отсутствуют и в чек-листе не пробовались |
| `SMR-P1-07` | реестр медиа, разрешение цели через Telegram ID и обработка нескольких изображений пробами не проверялись (позитив есть только для `own_media`/`reply_media`) |
| `SMR-P1-11` | проба покрывает `mca_style_scope`; `mca_self_model`, `mca_humor_feedback`, `public_speech_guard` не проверялись |
| `SMR-P1-12` | права, TTL и области применимости стиля не пробовались; проверена только цитата vs прямая просьба |
| `SMR-P1-10` | архитектура смысловых уроков: в дельте нет её модулей, но отдельного доказательства «не переписана» нет |

## 5. Граница lineage: доказательства P0 остаются на `2b7e9c7f`

`candidate_commit` карты теперь указывает на выкат P1. Доказательства P0-A/P0-B,
SMR-COMMANDS и SMR-HELP сняты на `2b7e9c7f` и **не переиздаются**: P1 изменил
`services/direct_chat_service.py` и `services/direct_capabilities.py`, поэтому байтовую
идентичность этих строк на `1a4a9b1b` утверждать нельзя. Следствие для гейтов:
scoped release по P0-срезам вернёт `no evidence bound to reviewed candidate` — это
lineage предыдущего выклада, а не регрессия и не отзыв прежней приёмки. Повторное
доказательство P0 на P1-кандидате не требуется, пока не появится отдельная причина.

## 6. Гейты

См. раздел отчёта PM за тот же прогон; карта остаётся `strict_evidence: true`, граф
срезов не менялся, кроме добавления среза корректировки владельца `NOST-PROACTIVE`
(отдельная карта `requirements-map-nostalgia-correction.json`).

## 7. Наблюдения владельца — необязательные

Четыре пункта из §10 артефакта DevOps (живой разговор про прошлое, вопрос про картинку
без картинки, кавычки в просьбе о стиле, «Бот, найди …» против «я в интернете видел…»)
остаются добровольным наблюдением владельца: они не блокируют инженерное DONE и не
создают Human Gate.
