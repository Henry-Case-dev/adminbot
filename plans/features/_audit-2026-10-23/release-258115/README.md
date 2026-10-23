# REL-258115 — релизный поезд 2.58.114 → 2.58.115 (24.10.2026)

Лейн `RELEASE-258115`. База — `origin/master` (`49c1b151`, версия 2.58.114).
Работа — в отдельном worktree `C:\Code\Python\adminbot-wt258115`.
Основной чекаут не изменялся.

## Точки

| Что | SHA |
|---|---|
| База (`origin/master` = 2.58.114) | `49c1b151b1272352144c327ee1d79377a1322c07` |
| pre-bump HEAD поезда (F8-meta HEAD-токен) | `eb33363520d123194bb1e431600dfd10221c2f54` |
| Bump-коммит 2.58.115 | `d5e1904783771377a696756a131a2406c54f06df` |
| Точка отката (прод 2.58.114) | `e9f7595bad3f56145078ad599edf4b7182d2e1df` |
| Предыдущая точка (прод 2.58.113) | `e4ee54f3cc12c39492c60eb2a0865f5da429454c` |

Версия: **2.58.115**. Bump-набор: **31 файл / 33 пары строк**
(README + settings + F8-meta + 24 py-пина + 4 JS-пина), `SET EQUAL` процедуре 114.

## Черри-пики

| Оригинал | В поезде | Содержание |
|---|---|---|
| `7c3df396` | `d10ecacc` | inspector: exact provider payload, per-call trace, human skip reasons |
| `18030a8c` | `ede5096a` | inspector: wire body on fallback, mask hierarchy, tool/background channels |
| `b90049af` | `3d3a0777` | ASAP3 limits inventory §2: 4 silent losses made honest/visible |
| `e6c9b65b` | `562f8fe5` | ASAP3 limits: post-review honest numbers (dossier/expr/extractor tail) |
| `edda97ce` | `eb333635` | SOUL-1 OFF parity stand: ASAP2 boundary + ASAP3 alias stubs |

Черри-пиковались только код/тесты: `plans/**` из коммитов намеренно исключён
(при добавлениях — `reset + delete`, при modify/delete — `git rm`). Кодовых
конфликтов **0**; авто-мерж прошёл в `services/llm_client.py` и
`services/direct_chat_service.py` с сохранением базовых изменений 2.58.114.
Итог: 5 коммитов поезда + bump = 6 коммитов; 46 файлов (15 код/тесты + 31 bump).

## Состав поезда 2.58.115

| Функция | Коммиты | Статус |
|---|---|---|
| INS-EXACT/TRACE/SKIPREASON: точный payload провайдера, трасса вызовов, человеческие причины skip, иерархия/конфликты в Inspector | `d10ecacc`, `ede5096a` | отревьюжено в источнике |
| ASAP3 limits inventory: скрытые потери лимитов стали видимыми, честные числа | `3d3a0777`, `562f8fe5` | отревьюжено в источнике |
| SOUL-1 OFF parity: стенд знает ASAP2 boundary + ASAP3 alias-стабы | `eb333635` | **частично**: см. §«Конфликт parity» |

Каноны в поезде не менялись: `services/prompt_registry.py` отсутствует в дельте.
`factory_set_fingerprint() == FACTORY_SET_SHA256_12 == 0163a686c401`
(probe rc=0; см. `frozen-fingerprint.txt`). Bump fingerprint не меняет.

## ΔDDL

**0** в прод-периметре (`services/`, `web/`, `config/`, `scripts/`, `tools/`):
0 совпадений DDL-токенов в добавленных строках `49c1b151..d5e19047`,
`_SCHEMA_VERSION_HUMOR_SAMPLES = 37` не менялся, schema/migration-файлы не
затронуты. Подробности — `ddl-check.txt`.

## Guards

| Проверка | Результат | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token **NONE**, CHECK OK | `bump-verify.txt` |
| Offline-агрегат | **19/19 PASS, EXIT 0** | `bump-offline-check.txt` |
| F8 `--check` | **582 == REGISTRY**, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| F8-пины | **29 passed** | `focused-f8-pins.txt` |
| Frozen-пины канонов | **66 passed** | `frozen-pins.txt` |
| pins24 (24 файла) | **868 passed / 0 failed** (66.24s) | `pins24-full.txt` |
| help-sync | **24 passed** | `focused-help-sync.txt` |
| JS-unit | **39 passed** | `focused-js-unit.txt` |
| node-пины + mini-lens | **5/5 rc=0** | `js-pins-node.txt` |
| JS-syntax sweep | **107 файлов / 0 bad** | `js-pins-node.txt` |
| py_compile изменённых py | **37 файлов / 0 bad** | `py-compile.txt` |
| Frozen UI-ассеты | **FROZEN-ASSETS-OK** | `frozen-assets.txt` |
| `test_asap3_hidden_limits.py` | **13 passed** | `focused-asap3-limits.txt` |
| `test_speech_inspector_exact.py` | **12 passed** | `focused-inspector-exact.txt` |
| `test_llm_client.py` | **115 passed** | `focused-llm-client.txt` |
| `test_asap2_boundary_marker.py` | **8 passed** | `focused-asap2-boundary.txt` |
| `test_asap3_identity_aliases.py` | **22 passed** | `focused-asap3-identity-aliases.txt` |
| `test_soul1_composer_parity_off.py` | **8 passed / 5 failed** (13 collected) — **red уже на базе** | `parity-off-train.txt`, `parity-off-base-49c1b151.txt` |
| UI e2e Inspector | **checks=142 failures=0** | `e2e-inspector.txt` |
| W4 UI e2e | **failures=0**, POST=8, notes=163 | `e2e-w4.txt` |
| ASAP3 hint e2e | **PASS: 10 проверок** | `e2e-asap3-hint.txt` |

Суммарно по pytest-прогонам — **1175 passed / 5 failed** (наборы намеренно пересекаются).
Пять red — один и тот же stale baseline SOUL-1, унаследованный от базы.

## Конфликт parity (SOUL-1) — честно

`edda97ce` добавляет в стенд только стабы (`_history_partial`/`aliases`) и
**не перезаписывает** baseline (`tests/fixtures/soul1/direct-runtime-assembly-asap2.txt`).
Эталон снят на канонах ASAP2 (код `5ad73933`, fingerprint `24ae494ac422`), а
база 2.58.114 содержит каноны R3/R3B (`0163a686c401`). Поэтому 5
канон-зависимых тестов падают и на кандидате, и **на чистой базе**:

- `test_soul1_composer_parity_off.py` на `49c1b151`: **5 failed / 8 passed**;
- то же на `d5e19047`: **5 failed / 8 passed** (идентичные имена тестов);
- логи: `parity-off-base-49c1b151.txt`, `parity-off-train.txt`.

Это не регрессия поезда. Ожидаемое «13 passed» из брифа недостижимо на этой
базе без нового re-record эталона под каноны R3/R3B (процедура `4bd2f3c6`
делала это для ASAP2-канонов). Re-record в лейне **не выполнялся**: это
изменение семантики эталона, требующее решения Orchestrator; каноны не
менялись. Рекомендация: отдельный минимальный commit «re-record OFF baseline
for R3/R3B canons» до деплоя.

## Изоляция / примечания

- Основной чекаут (`C:\Code\Python\adminbot`) не изменялся.
- Для доказательства base-red создавался временный worktree
  `C:\Code\Python\adminbot-wt258115-base` на `49c1b151`; после снятия
  evidence он удалён.
- E2E-скрипты пишут PNG в `plans/features/asap-speech-arch/evidence/...`;
  после прогонов эти изменения откачены (`git checkout HEAD -- plans/`,
  untracked `inspector/` удалён). В коммит поезда plans-артефакты не входят.
- Полный repository-wide pytest в лейне не запускался (запрещено брифом).
- Деплой/SSH/e2e-на-проде не выполнялись: лейн заканчивается пушем в
  `origin/master`.
