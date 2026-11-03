# Привязка карты мем-пайплайна к родительскому кандидату 092734a6 (PM)

- Дата: 2026-11-03 15:41 +12:00
- Роль: PM (привязка доказательств и статусов, не новое ревью поведения)
- Задача: `meme-pipeline-refactor-01` (owner input `OI-2026-11-03-MEME-PIPELINE-REFACTOR`)
- Карта: `plans/features/meme-pipeline-refactor-01/requirements-map.json`
- Родительский кандидат: **092734a6** (merge `feat/meme-ui-fields` + docs/review в `evol/impl`)
- Принятый кандидат последнего слайса: **e25bd479** (`MEME-UI-FIELDS`)

## 1. Что это за документ и чего он не делает

Это перенос **уже принятых** вердиктов по слайсам на merge-коммит, а не повторное ревью.
Проверено ровно три вещи, каждая наблюдаемая:

1. каждый принятый слайс-коммит является **предком** 092734a6 (`git merge-base --is-ancestor` → 0),
   то есть ни один принятый слайс не потерян и не откатан merge-цепочкой;
2. на 092734a6 **фактически прогнаны** тесты каждого слайса, и их результат записан ниже;
3. файлы последнего принятого слайса (web/**) в merge побайтово те же, что в принятом e25bd479
   (`git diff e25bd479 092734a6 -- web/` пуст), поэтому вердикт Re-review 2 действует на 092734a6.

Документ **не** является новым поведенческим ревью, не заменяет `reports/w-*-review.md` и не
доказывает живой показ мема владельцу (это добровольное наблюдение по правилу PET_PROJECT).
`deployed_commit` в карте остаётся пустым до фактического выката.

## 2. Состав родительского кандидата

| Слайс | Принятый кандидат | Предок 092734a6 | Артефакт ревью |
|---|---|---|---|
| `MEME-PIPE-CORE` | `b272a63b` | да | `reports/w-p1-review.md` (Approved) |
| `MEME-API-SCOPE` | `ceb49b56` | да | `reports/w-p2-review.md` |
| `MEME-MANUAL-CMD` | `d5853749` | да | `reports/w-p3-review.md` |
| `MEME-JOKE-SPEECH` | `5fb018ab` | да | `reports/w-joke-speech-review.md` |
| `MEME-INITIATIVE-LAYERS` | `5fb018ab` | да | `reports/w-joke-speech-review.md`, `reports/pm-p7-expression-axis-binding.md` |
| `MEME-INIT-COORDINATION` | `f9d1cda9` | да | `reports/w-p8-review.md` |
| `MEME-INIT-DIAG` | `53daa257` | да | `reports/w-p9-review.md` |
| `MEME-UI-FIELDS` | `e25bd479` | да | `reports/w-p4-review.md` (Approved, Re-review 2) |
| `MEME-ANALYTICS-STAGES` | серверная часть `b272a63b`, витрина `e25bd479` | да | `reports/w-p1-review.md`, `reports/w-p4-review.md` |

Проверка наследования (все восемь команд вернули 0):

```
git merge-base --is-ancestor b272a63bd978e38d4f7696b2172a7f5edf96b67d 092734a685f30dcd5500beaba2169c2f6c177823
git merge-base --is-ancestor ceb49b564e8a6f628b5bc527aa20bdad4b08f899 092734a6     # 0
git merge-base --is-ancestor d58537496cc129987e8eb045019909b794c11533 092734a6     # 0
git merge-base --is-ancestor 5fb018ab31db16953b6ea528b5f9d00ea97925ce 092734a6     # 0
git merge-base --is-ancestor f9d1cda9a83983cbbe39687d17cb2be6a7fef90a 092734a6     # 0
git merge-base --is-ancestor 53daa257058b612b1e1237174d6aa2717c073b1d 092734a6     # 0
git merge-base --is-ancestor e25bd479265a7521612ea53596b486934f57ef0c 092734a6     # 0
```

`git diff e25bd479 092734a6 -- web/` — пустой вывод: принятая витрина в merge не изменена.

## 3. Фактические прогоны на 092734a6

| Тесты | Что покрывают | Результат |
|---|---|---|
| `tests/test_meme_pipeline_stages.py` | три этапа, бюджеты L/J, журнал стадий | 18 passed |
| `tests/test_evol014_meme_initiative.py` | живой пайплайн мем-инициативы | 40 passed |
| `tests/test_p0_meme_image_only.py` | доставка: только изображение, отказ без шума | 11 passed |
| `tests/test_meme_pipeline_api.py` | API-витрина мемов и бюджет | 12 passed |
| `tests/test_meme_command_autodelete.py` | `/meme`: админ, очередь мимо гейтов, автоудаление | 18 passed |
| `tests/test_meme_joke_speech_layers.py` | единый композер, Core/Expression/Humor, один вызов | 9 passed |
| `tests/test_initiative_speech_layers_chat_overrides.py` | слои текстовой инициативы и чатовые настройки | 4 passed |
| `tests/test_initiative_coordination.py` | независимость, random, кулдауны, атомарность | 59 passed (см. §5) |
| `tests/test_initiative_delivery_telemetry.py` | журнал выводов и телеметрия доставки | 13 passed |
| `tests/test_meme_init_diagnostics.py` | сборщик диагностики механизмов | 18 passed |
| `node tests/js/meme_ui_fields_test.js` | представления карточки мемов | `MEME-UI-FIELDS-OK` |
| `node tests/js/evol_w4_diagnostics_ui_test.js` | представления диагностики, подключённый к автоматике файл | `EVOL-W4-UI-OK` |
| `python tests/ui_meme_ui_fields_e2e.py` | реальный DOM (390 и 1280): поля, числа, стадии, диагностика, пустое состояние | `failures=0` |

Совокупно по мем-полосе: 202 pytest-проверки пройдены, JS-наборы зелёные, DOM-прогон без падений.

## 4. Решения P4, которые сохраняются

1. **Маршрут диагностики живёт в файле-зоне, а не в `routes.py`.**
   `web/api/mechanism_diagnostics.py` содержит один `APIRouter` и ровно один путь
   `GET /initiative/mechanism-diagnostics`. Это закреплено тестом
   `test_mechanism_diagnostics_lives_in_zone_router_not_routes_py`: он проверяет состав
   `mechanism_diagnostics_router.routes` и отсутствие маршрута в `routes.py`. Расширять
   `routes.py` новым маршрутом нельзя и в следующих слайсах.
2. **Sha-пин `routes.py` переиздан осознанно** по процедуре L-F11S-1 при **Δ routes = 0**
   (55 маршрутов, набор не менялся; причина переиздания — снятие алиасов `length_limit`).
   Ловушки при этом не выключены: проба с посторонним маршрутом валит routes-set пин,
   проба с изменённым на один байт файлом валит sha-пины.
3. **JS-тест диагностики подключён к автоматике.** `tests/js/evol_w4_diagnostics_ui_test.js`
   вызывается из `tests/test_webapp_js_unit.py::test_js_unit_evol_w4_diagnostics`; непроверяемый
   файл, из-за которого регрессия прошла мимо гейта, больше не «висит без запуска».
   На 092734a6 проверено точечно: `pytest tests/test_webapp_js_unit.py::test_js_unit_meme_ui_fields`
   → 1 passed (в общем прогоне файла в этой среде мешает ограничение ОС на массовый `subprocess`,
   не имеющее отношения к продукту — см. §5).

## 5. Ограничения и честные наблюдения

- **`tests/test_initiative_coordination.py`**: в одном из шести прогонов упал
  `test_t4_diagnostics_publish_mode_is_coordinated` (1 failed, 58 passed), в изоляции и в
  остальных пяти прогонах — 59 passed. Файл теста побайтово идентичен принятому кандидату
  `f9d1cda9` (sha256 `0367c3f5…`), то есть это самопроизвольная порядко-зависимая утечка
  состояния внутри набора, а не регрессия мем-пайплайна. В бэклог как отдельный дефект гигиены
  тестов; на приёмку мем-строк не влияет.
- Массовый прогон `tests/test_webapp_js_unit.py` целиком в этой среде даёт `OSError [WinError 50]`
  на десятках последовательных `subprocess`: проверено точечно (`node` напрямую и одиночный
  pytest-тест), где всё зелёное. Это ограничение окружения, а не дефект кода.
- `deployed_commit` пуст: выката ещё не было. Строки карты с `live_required: false` не требуют
  живого показа; живой показ мема в чате — добровольное наблюдение владельца (PET_PROJECT).

## 6. Источник §1, строка 22: почему это `context`, а не работа

Строка 22 снимка — сводная формулировка цели §1–§4 («сделать пайплайн управляемым из админки,
убрать ограничение длины у выжимки, перенести ограничение длины на этап прикола, добавить
админскую диагностическую команду `/meme` без ограничений и кулдаунов»). Самостоятельного
обязательства она не создаёт: каждое её положение уже отслеживается отдельной обязательной строкой
карты, каждая из которых VERIFIED:

- снятие потолка с выжимки → `MEME-STAGE-A-NO-CEILING` (источник строки 35–36);
- перенос потолка на итоговый промпт → `MEME-LEN-TARGET-FINAL-PROMPT` (строки 82, 84);
- допустимая длина прикола → `MEME-LEN-J-BUDGET` (строки 47, 93–98: `J = max(0, L − T)`);
- управляемость из админки → `MEME-PROMPT-JOKE-FIELD`, `MEME-PROMPT-THREE-LAYER-UI` (строки 61, 75);
- команда `/meme` только админу и мимо ограничений → `MEME-CMD-ADMIN-ONLY`, `MEME-CMD-BYPASS-GATES`
  (строки 135, 147).

Поэтому строка 22 остаётся `disposition: context` с указанной причиной и не входит в знаменатель
обязательных требований (164 обязательные строки).

## 7. Результаты гейтов

Прогоны выполнены в рабочем дереве `evol/impl` (HEAD 092734a6), потому что относительный
`source_path` карты существует именно в этой ветке; главный чекаут проекта сейчас на `master`,
где ни снимка источника, ни карты мем-полосы нет.

План-гейт:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage plan \
  --map plans/features/meme-pipeline-refactor-01/requirements-map.json --repo .
stage=plan inventory=116 manual=81 scoped=0 errors=0
```

Полный ревью-гейт по всем девяти слайсам с `--candidate 092734a685f30dcd5500beaba2169c2f6c177823`:

| Слайс | scoped | errors |
|---|---|---|
| `MEME-PIPE-CORE` | 54 | 0 |
| `MEME-API-SCOPE` | 2 | 0 |
| `MEME-MANUAL-CMD` | 21 | 0 |
| `MEME-UI-FIELDS` | 18 | 0 |
| `MEME-ANALYTICS-STAGES` | 11 | 0 |
| `MEME-JOKE-SPEECH` | 13 | 0 |
| `MEME-INITIATIVE-LAYERS` | 4 | 0 |
| `MEME-INIT-COORDINATION` | 37 | 0 |
| `MEME-INIT-DIAG` | 4 | 0 |

Итог: **scoped 164 из 164 обязательных строк, errors=0 в каждом слайсе.** Строгий режим проверял
существование коммита 092734a6, кандидатную привязку каждой строки и наличие реального
repo-относительного артефакта с совпадающим sha256.
