# Release 2.58.129 — cover-style JSON fix (B1)

**Ветка:** `release/2.58.129` (lane `RELEASE-258129-COVER-JSON`).
**База:** `origin/master` tip `24ca634b` (APP 2.58.128 уже на проде).
**Фича:** `origin/task/cover-style-json-fix` = `16a0dbbf` (Reviewer Approved).
**Merge:** `62969444` (`--no-ff`, без конфликтов).
**Bump:** 2.58.128 → 2.58.129.

## Что меняется относительно прода

Ровно 5 файлов (`24ca634b..62969444`):

- `services/cover_style_edit.py` — `provider_meta` собирается из результата финальной попытки (bad_json-ретрай больше не подменяется метаданными первой попытки);
- `services/cover_style_jobs.py` — прокидывание финального результата в метаданные задачи;
- `tests/test_cover_style_edit_extract.py` (новый) — `_extract`/`_response_diag` + `test_cover12c_provider_meta_uses_final_retry_bad_json`;
- `tests/test_asap44_cover_final_closure.py` — +42 строки;
- `plans/features/cfg/evidence/cover-style-json-fix.md` — описание первопричины.

**Речь/SOUL/PEMsoc не тронуты:** в diff нет `speech_*`/`expression`/`style_policy`/`pemsoc_*`/`handlers/*`.

## Тесты (post-merge, до bump)

| Набор | Результат |
|---|---|
| `pytest test_cover_style_edit_extract.py test_asap44_cover_final_closure.py -q` | **31 passed** (10.3 s) |
| `pytest tests -k "cover_style or cover_prompt or extra_cover or asap4" -q` | **1154 passed**, 14512 deselected (175.7 s) — 1150 базовых + 4 новых |
| `pytest tests -k "speech or expression or prompt or checkup or factcheck or unified_core or cfg07" -q` | **1668 passed**, 13998 deselected (45.7 s) — совпадает с базой `24ca634b` (1668) |
| `pytest test_pemsoc_one_reaction.py test_common.py -q` | **181 passed** |
| `pytest test_round1025_f8_registry.py -q` | **29 passed** |
| `py_compile` `services/cover_style_edit.py`, `services/cover_style_jobs.py` | OK |

**Расхождения с заданием:**
- PEMsoc+common: в задании ожидалось 256, фактически **181** — ровно столько же на базе `24ca634b` и на `d4426a17` (2.58.128), то есть merge ничего не сдвигает; число в задании завышено.
- Speech-набор: первый прогон дал `test_asap_speech_i_matrix.py::test_i01_i04_i03_i09_plan_drives_form` FAILED (1 из 1668). Изолированный прогон — 4 passed; повторный полный прогон на том же коде — **1668 passed**. Флак по порядку выполнения, не регрессия merge (база тоже 1668 passed).

## Guard-проверки

| Проверка | Значение |
|---|---|
| `factory_set_fingerprint()` | **f12130fbccb1** (как на 2.58.128) |
| ΔDDL | **0** — в diff нет `*.sql`/schema/migration файлов |
| Bump-набор | **31 файл / 32 пина**: README, `config/settings.py`, F8-мета + 27 тестовых `.py` + 4 `tests/js/round1025_hotfix{7,8,9,10}_*.js` (escaped-пины `2\.58\.128`) |
| F8-мета HEAD | `62969444` (pre-bump HEAD) |
| Stale-пины `2.58.128` вне `plans/features` | 0 |

## Откат

- Холодный: `git checkout dcaca75b` (APP 2.58.128, cover-фикса нет) + `systemctl restart admin_bot`.
- Ветка отката: `release/fix-2.58.128` → `dcaca75b`.
- Тёплого флага нет: изменение — корректность метаданных cover-задачи, не переключаемая фича. Мягкий откат фичи на уровне продукта — `COVER_STYLES_ENABLED=false` (обложка остаётся базовой, публикация жива).
