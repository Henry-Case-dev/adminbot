# REL-258108 — релизный бамп 2.58.107 → 2.58.108 (PKG-108, 22.10.2026)

Лейн PKG-108. Процедура — бамп-прецедент 106/107 (31-файловый SET EQUAL набор).
Дельта — только версия/HEAD-токены + release evidence (жёсткий pathspec); чужой
dirty-worktree (181 tracked-модификация других лейнов) не захвачен.

## Состав релизной дельты (2.58.107 → 2.58.108, review Approved)

| Коммиты | Суть |
|---|---|
| `1cf0f400` | FIX-VISION-FENCE — `services/mca_vision.py` `parse_analysis_payload`: strip markdown-fence перед строгим `json.loads` (модели стабильно заворачивают КОРРЕКТНЫЙ JSON в fence; строгий парсер честно parse_errored валидный JSON). Раскрывается ТОЛЬКО fence, строгая валидация не ослаблена (битый JSON остаётся parse_error). +2 REGRESSION-теста в `tests/test_mca19_block_b_round1043.py` (fence parsed; fence — unwrap, не repair), RED до фикса / 33 passed после. Снимает блокер POSTGEN-ready + P0V heavy frames (harness w5: real providers, POSTGEN-ON ready, P0V heavy GT 3/3) |
| `06b7ef4d` | docs-биндинги — S9/DOD3(2)/ADTR-POSTGEN-ON/P0V-PIPE-CONTEXT VERIFIED (review-harness-fence.md: обе волны Approved) |

F8-meta HEAD-токен = **`06b7ef4d`** — голова релизной дельты PKG-108; git HEAD на
пребампе = `06b7ef4d`, расхождений нет.

## Bump-набор (31 файл = SET EQUAL процедурам 106/107)

| Роль | Файл(ы) | Замена |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.107"` → `"2.58.108"` (только версия, комментарий без изменений) |
| Версия | `README.md` | `v2.58.107` → `v2.58.108` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.107`→`2.58.108`; HEAD (short) `bbcafef5`→`06b7ef4d` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.107`→`2.58.108` (polygon — 2 вхождения) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.107` → `2\.58\.108` (regex) |

`git diff` по bump-набору = **31 файл, 33 пары строк, только version/HEAD-токены**
(bump-verify: non-token deltas NONE). Каталог не тронут (REGISTRY 582, Δ=0; F8
`--check`: **582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны).

Канонные счётчики каталога (582/171) не пересанкционировались — в поезде 108
нет изменений канонов/каталога; fingerprint остаётся **`c19d35a1c093`**
(константа corrective-волны `44a4827a`), офлайн-гвард: runtime
`factory_set_fingerprint()` == константа == `c19d35a1c093` — PASS (канонов в
поезде нет — не изменился, как и требовал бриф).

## Guards

| Проверка | Результат | Статус | Артефакт |
|---|---|---|---|
| Pre-bump (HEAD=06b7ef4d, dirty∩bump=0, SET EQUAL proc-107, токены 32 вхождения в 31 файле, train 3a178c6c..HEAD не трогал bump-набор) | PASS | VERIFIED | scratch `pkg-108/` (семантика вошла в bump-offline-check) |
| Offline-агрегат (17 проверок: settings/README/meta/токены/SET EQUAL/foreign-guard/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release, schema v37/fingerprint c19d35a1c093 live+import) | **EXIT 0, 17/17 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33, non-token deltas NONE, CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 106/107 | ref(107) 31 == bump(108) 31; ONLY IN 107: none; ONLY IN 108: none | VERIFIED | `delta-vs-107.txt` |
| ΔDDL (bump-scope + release-to-release; ≠ 0 → STOP) | **0 файлов** bump-набора в DDL-периметре; schema v37 не менялась; в release-дельте `3a178c6c..HEAD` из периметра — пусто (только `services/mca_vision.py` parser-only + docs/tests) | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла | **868 passed / 0 failed, EXIT 0** — паритет 101–107 | VERIFIED | `pins24-summary.md`, `pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (набор не менялся — новых JS в поезде нет) | VERIFIED | `focused-js-unit.txt` |
| Node пин-регрессы | **5/5 OK** (4 js-пина + mini-lens) | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad**, EXIT 0 (= база 106/107) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `--check` | **CHECK OK: реестр 582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Write-points single-writer (`test_mca01_...` `-k write_points`) | **1 passed**, 32 deselected, EXIT 0 | VERIFIED | `focused-write-points.txt` |
| Цель: `test_mca19_block_b_round1043.py` (вкл. 2 новых REGRESSION fence-фикса) | **33 passed**, EXIT 0 | VERIFIED | `focused-mca19-regression.txt` |
| Цель: фактчек `test_factcheck_fc_r1_fix.py` | **22 passed**, EXIT 0 | VERIFIED | `focused-factcheck-fc-r1.txt` |
| Цель: corrective выборка (L1 `test_direct_l1_corrective_r1` + expression `test_expression_isolation_followup` + nostalgia `test_nostalgia_corrective_r1`) | **25 passed**, EXIT 0 | VERIFIED | `focused-corrective.txt` |

## Изоляция

Полный снимок `git status --porcelain` — `final-diff-names.txt` (212 tracked
модификаций, из них 181 чужой dirty/untracked-хвост других лейнов не входит в
пакет). Коммит — только 31 файл + `plans/features/add-tr/release-258108/` (этот
каталог) по явному pathspec. Review-evidence других лейнов в pathspec не входят
(foreign-guard PASS).

Не в скоупе лейна: пуш и деплой (по брифу PKG-108).

## Замечания (честные)

- **Интерпретатор гвардов.** Первый прогон pins24 этого лейна глобальным
  `py -3` дал красный 1 failed / 867 passed
  (`test_on_l1_not_usable_level2_l2_publishes_article`: `_deliver_l2_rich`
  awaited 0 раз, публикация ушла в plain). Диагностика: `_rich_media_supported()`
  (lru_cache-гвард `aiogram.types.InputRichMessage.model_fields`) при aiogram
  **3.29.1** глобального Python возвращает False (`media` отсутствует в
  `model_fields`) → rich-путь честно отключён. Требование репозитория —
  `requirements.txt: aiogram>=3.31.0,<4.0.0`; PKG-107 гнал гварды через
  `.venv/Scripts/python.exe` (venv: aiogram 3.31.0). Воспроизведение в чистом
  worktree подтвердило: красный не зависит от бампа (падает и на `bbcafef5`, и
  на `06b7ef4d` без правок лейна). Все гварды перезапущены через venv —
  868/0. Код не менялся; это env-артефакт прогона, не дефект релиза. (Класс
  «2× summary-publish на старом aiogram» уже помечен предсуществующим в
  `1e24eca4`.)
- Комментарий `APP_VERSION` в settings.py остался от волны asap8-v6 (прецедент
  105–107: при бампе комментарий не переписывается, описание релиза живёт в
  commit message и этом README).
- Исторические ссылки «прод 2.58.107 = ровно эти байты» — провенанс
  прод-байтов 2.58.107, не пины версии; намеренно не менялись (после деплоя
  108 факт «прод 107» остаётся исторически верным для зафиксированных байтов).
