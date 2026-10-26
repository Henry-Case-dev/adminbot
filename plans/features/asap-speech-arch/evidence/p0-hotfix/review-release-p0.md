# REVIEW-RELEASE-P0 — финальное релизное ревью кандидата 86ef2a64 (26.10.2026)

**Вердикт: Approved for controlled deployment, parent not DONE.**
Блокеров нет. Постдеплойные проверки (READY_FOR_LIVE) — после выката, затем `--stage release` для закрытия.

- **Кандидат:** `86ef2a64d1a8ebba4b7738c7594e30ba3391c8a8` (merge release/p0-2026-10-26) + биндинг-коммит `c358f202` (карты/evidence).
- **Ревью:** ограниченное (bounded), работа в worktree `adminbot-wt-rel-p0`, без кода/SSH/прода/Telegram/LLM.

## 1. Тесты (один прогон на слитой ветке)

| Проверка | Результат |
|---|---|
| `pytest -k "speech_p0 or direct_l1 or factcheck or media_group or prompt_registry or round1025_f8" --ignore=test_p0_vision_ui_e2e` | **734 passed**, 15140 deselected — новых падений против премерж-прогонов нет |
| `pytest tests/test_round1025_f8_registry.py` | **29 passed** |
| `tools/gen_param_registry_round1025.py --check` | **OK**: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| `compileall services` | OK |
| `git grep` маркеров конфликта (`<<<<<<<`/`=======`/`>>>>>>>`) | 0 |

`test_param_catalog_unchanged` сверяет SHA256 объединённого каталога с `PARAM_CATALOG_SHA256_FOLLOWUP` = `f23cd0c7…` — тест проходит, хеш соответствует слитому каталогу.

## 2. Инспекция слияния 86ef2a64 (parents 0068a246 + 3d365069, base 534ac7dda)

Автослияние воспроизведено `git merge-tree --write-tree`; результат побайтово сравнён с фактическим merge-деревом.

| Файл | Разрешение | Проверка |
|---|---|---|
| services/database.py | auto | **bit-identical** автослиянию git: изменения обеих сторон (+400 speech, +61 factcheck) сохранены, ручных правок нет |
| services/param_catalog.py | auto | **bit-identical** автослиянию (+3 speech, +14 factcheck) |
| plans/docs/param-registry-round1025.tsv | auto | **bit-identical** автослиянию; `--check` подтверждает консистентность с объединённым каталогом |
| tests/test_round1025_f8_registry.py | ручное (content) | объединены оба провенанс-комментария (SPEECH-P0-A1 + P0-FACTCHECK), хеш пересчитан по объединённому каталогу; тест 29 passed |
| plans/features/asap-speech-arch/requirements-map-p0-hotfix.json | ручное (add/add) | сохранена версия стороны 1 (factcheck-ветка); обе версии содержат **одинаковые 81 source_id** — строки не потеряны; версия стороны 2 была старым состоянием (пустой candidate_commit, все PENDING) |

Полный diff «merge-результат vs чистое автослияние» = ровно 3 файла: два ручных разрешения выше + `param-registry-round1025.meta.md` (±1 строка: провенанс-штамп «HEAD (short)» = `0068a246`; косметика, на контракт реестра не влияет — см. п.5.2).

**Потерянных изменений ни с одной стороны не найдено; случайных поведенческих правок сверх разрешения конфликтов нет.**

## 3. Биндинги карт и evidence

- `requirements-map-p0-corrective.json`: candidate_commit = **86ef2a64d1a8…** (62 строки: 41 VERIFIED / 20 PENDING / 1 READY_FOR_LIVE; items: 41 VERIFIED / 27 PENDING / **1 FAILED**).
- `p0-factcheck-media/requirements-map.json`: candidate_commit = **86ef2a64d1a8…** (121 строка: 88 VERIFIED / 30 PENDING / 3 READY_FOR_LIVE).
- Проверены все пути evidence в VERIFIED-строках: **195 ссылок, все существуют** (2 ложных срабатывания скрипта: `plans/current_task.md` лежит untracked в основном репо и существует; `tools/_s41_precheck.py` — упоминание untracked-файла прода в аудите `prod-worktree-alias.md`, не ссылка на артефакт).
- VERIFIED-строки без артефакта не обнаружены; live-строки привязаны к кандидату.

## 4. Честные остатки (задокументированы, не скрыты)

| Остаток | Где зафиксирован | Статус |
|---|---|---|
| meta 1/8 на hostile_rebuff-ответе | CORR-карта: `CORE-META-INTRO-REMOVE` = **FAILED**, live-evidence `probes_release.md` критерий 1 (candidate-bound); правка — P0 DELTA | честный FAILED, не замаскирован |
| FREQUENT (статистическая остаточная вариативность) | 5 FAILED в `requirements-map-p0-hotfix.json` + 4 FAILED в `p0-corrective-factcheck-speech`; `frequent-decision.md`: причины, новые условия приёмки, «в VERIFIED не переводятся, релиз не блокируется» | честный FAILED |
| L1-B honest report | `probes_release.md` критерий 2: B = `hostile_rebuff` (не research), анализ честно выключен (0×0); tone/material routing — P0 DELTA по решению владельца | задокументирован |
| Postdeploy-only | CORR `DEPLOY-STANDARD` = READY_FOR_LIVE; FACT: FC-REPORT-06 (версия прода после выката), FC-WIDE-02 (видимость тумблера в живой админке) | READY_FOR_LIVE, корректно postdeploy-only |
| PENDING без артефакта | `REV-NO-UNSUPPORTED-DATES`, `MEMORY-L2-NOT-EVIDENCE` — открыто названы в candidate_note | честный PENDING |

## 5. Ревью-гейты (requirements_gate.py, stage=review, --candidate 86ef2a64d1a8…)

Команда из брифа без `--slice/--candidate` у инструмента невозможна (он требует их) — выполнен семантически эквивалентный поглавный прогон.

**CORR (p0-corrective):** ALIASES/HARNESS/L1/PROBES/PROD — **0 errors**. DEPLOY(1)/MEMORY(1)/REPORT(9)/REVIEW(3) — все ошибки одного типа «mandatory not VERIFIED (got PENDING)» на пост-деплойных/процессных/финально-отчётных строках (деплой ещё не выполнен; отчёт владельцу пишется после выката).

**FACT (p0-factcheck-media):** 11/14 срезов — **0 errors** (FC-ALBUM/AUDIT/CLAIM/CTX/EMPTY/REVIEW/SHARED/SINGLE/VISION/WHOLE/WIDE). FC-QUEUE(14)/FC-RELEASE(4)/FC-REPORT(13) — тот же тип: процессные/деплойные/отчётные обязательства PENDING до релиза.

Ошибок привязки evidence, несоответствия кандидата, FAILED-строк в гейтах нет. Состояние карт соответствует pathway «Approved for controlled deployment, parent not DONE»: преддеплойные проверки пройдены, постдеплойные проверки и откат определены.

## 6. Сопутствующие наблюдения (не блокируют)

1. `probes_release.md` §6 ссылается на каталог raw-артефактов `probes_release/` (31 файл) — каталог существует на диске в основном репо (32 файла), но **ещё не закоммичен**. VERIFIED-строки карт ссылаются на сам `probes_release.md` (закоммичен в c358f202), биндинг не нарушен. Рекомендация: приложить raw-каталог следующим evidence-коммитом.
2. Штамп провенанса meta.md (`0068a246`) отличается от чистого автослияния (`643cf393`) — косметика, контракт реестра (TSV==REGISTRY + SHA в тесте) проверен и выполняется.
3. `frequent-decision.md` называет 11 FAILED-строк; в картах сейчас 9 (4+5) — 2 старые PROBES-* перепривязаны при финальном биндинге, как и предписывает §«Статус строк» самого документа. Учётная заметка.
4. В worktree незакоммиченное изменение `plans/features/cfg/evidence/cfg-06/w7-dispute-metrics.json` (latency_ms_mock 5→8) — артефакт локального тест-прогона, в кандидат не входит.

## 7. Итог

Кандидат `86ef2a64` (+биндинг c358f202): слияние чистое (побайтово = автослиянию git по кодовым файлам), тесты 734+29 passed, реестр консистентен, карты привязаны, evidence существует, остатки честны. **Разрешаю контролируемый деплой 86ef2a64** (стоячее правило PET_PROJECT), далее постдеплойные проверки DEPLOY-STANDARD/FC-REPORT-06/FC-WIDE-02, актуализация READY_FOR_LIVE → VERIFIED и `--stage release` при закрытии задачи.
