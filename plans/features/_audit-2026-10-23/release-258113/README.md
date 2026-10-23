# REL-258113 — релизный поезд 2.58.112 → 2.58.113 (23.10.2026)

Лейн `RELEASE-258113`. База — `origin/master` (`678c0616`, bump 2.58.112).
Локальная линия `master` (`22cc3c14`) и `fix/embed-gaps` (`cf7e00e3`) сведены
в отдельный worktree `C:\Code\Python\adminbot-wt258113` черри-пиками.

## Точки

| Что | SHA |
|---|---|
| База (`origin/master` = 2.58.112) | `678c0616287c00e973fdae341354c773563f35a2` |
| pre-bump HEAD поезда (F8-meta HEAD-токен) | `e0f3bfbb163fa63a36a9c9d9990f9f724e50ad42` |
| Bump-коммит 2.58.113 | этот коммит; SHA — в отчёте лейна |
| Прод сейчас (2.58.111) — точка отката | `fbf9013d89b03e38473ce6824a460fdbb736fff8` |
| Предыдущая точка «код 2.58.112» | `678c0616` (в `origin/master`, не задеплоен) |

Версия: **2.58.113**. Байт-точный bump-набор: **31 файл / 33 пары строк**,
`SET EQUAL` процедурам 106–112 (`delta-vs-111.txt`).

## Черри-пики

| Диапазон | Коммитов | Конфликты |
|---|---|---|
| `924b3b51..22cc3c14` (W4 UI + embed identity compat + docs/привязки + resolver evidence) | 12 | **0** |
| `22cc3c14..cf7e00e3` (gaps-тесты, gaps-evidence, embed-meta-wire) | 3 | **0** |

Итого 15 черри-пиков без конфликтов; новых SHA — `0358b593..ddf139a1`
(полный список — `train-commits.txt`). Отдельный коммит `e0f3bfbb` обновляет
`plans/features/soul-1/evidence/w4/frozen-assets.txt` (HEAD==current после
коммита W4-ассетов), чтобы bump-набор остался ровно 31 файлом.

Метаданные релиза 112 (bump-коммит, `release-258112/`) не переносились.

## Состав поезда 2.58.113

| Функция | Коммиты (в 113) | Статус |
|---|---|---|
| W4 UI/UX §8 + rework U-02/U-07 | `0358b593`, `141333ed` | Approved (W4) |
| EMBED-IDENTITY-COMPAT: смена API-шлюза без полной перевекторизации | `4962ad48` | Approved |
| EMBED-IDENTITY-COMPAT B1/B3 (compat-пауза переживает рестарт, legacy-метаданные) | `67c1b509` | Approved |
| EMBED-IDENTITY-COMPAT gaps IDENT-02/CANARY-03/DEC-09 | `d62e9720` | Approved |
| EMBED-META-WIRE (probe читает фактическую модель из meta ответа) | `ddf139a1` | Approved |
| Evidence/привязки/карта embed-identity-compat + resolver-pre | `0eb61ff1`, `c2ce72d3`, `3d5442f2`, `bc52a0ca`, `528aee2f`, `4bcd108a`, `e4b7c595`, `244a9da4`, `128abcab` | docs |
| Frozen UI assets evidence refresh | `e0f3bfbb` | chore |

Уже в базе 2.58.112 (не переносилось): ASAP-2 Direct Chat, summary factview/B-1,
L2-ревизия, embed fallback slots, embed rebuild identity, B11 + job-патч, SOUL-1 фикстура.

## Каноны / fingerprint

Bump не меняет канонных файлов. Фактическая пара на кандидате:

- `FACTORY_SET_SHA256_12` = **`24ae494ac422`**
- `factory_set_fingerprint()` = **`24ae494ac422`** (constant == runtime, PASS)

Frozen UI-ассеты: `tools/soul1_w4_frozen_check.py` → **FROZEN-ASSETS-OK**,
HEAD sha == current для `web/index.html`, `web/app.js`, `web/static/app.css`
(после коммита W4 ассеты больше не «грязные», значение needles не изменилось).

## ΔDDL

**0** в прод-периметре (`services/`, `web/`, `config/`, `scripts/`, `tools/`):
из 3446 добавленных py-строк релизной дельты ни одна не является SQLite-DDL.
Единственные `CREATE TABLE` в дельте — в evidence-скрипте
`plans/features/embed-identity-compat/evidence/a0-probe/raw/runner.py`
(одноразовая проба на сервере, не прод-код). `_SCHEMA_VERSION_HUMOR_SAMPLES = 37`
не менялся. Подробности — `ddl-check.txt`.

## Guards (venv Python 3.12.0 / aiogram 3.31.0)

| Проверка | Результат | Артефакт |
|---|---|---|
| Offline-агрегат (версии, stale, F8-meta, bump set 31, ΔDDL, константа схемы, import, fingerprint) | **14/14 PASS, EXIT 0** | `bump-offline-check.txt` |
| Bump-verify | files=31, pairs=33 (+33/−33), non-token **NONE** | `bump-verify.txt` |
| SET EQUAL с bump-набором 112 | 31 == 31, only-in none | `delta-vs-111.txt` |
| F8-генератор `--check` | **582 == REGISTRY**, карта полна, R17-чисто | `gen-param-check.txt` |
| F8-пины | **29 passed** | `focused-f8-pins.txt` |
| pins24 (24 файла) | **868 passed / 0 failed** | `pins24-full.txt` |
| help-sync | **24 passed** | `focused-help-sync.txt` |
| JS-unit | **39 passed** | `focused-js-unit.txt` |
| node-пины + mini-lens | **5/5 rc=0** | `js-pins-node.txt` |
| JS-syntax sweep | **107 файлов / 0 bad** | `js-pins-node.txt` |
| py_compile изменённых py | **47 файлов / 0 bad** | — (консоль) |
| Frozen-пины канонов | **66 passed** | `frozen-pins.txt` |
| Frozen UI-ассеты | **FROZEN-ASSETS-OK** | `frozen-assets.txt` |
| write-points single-writer | **1 passed, 32 deselected** | `focused-write-points.txt` |
| ASAP-2 target set | **155 passed** | `focused-asap2.txt` |
| Summary target set (6 файлов) | **179 passed** | `focused-summary.txt` |
| Embed target set (7 файлов) | **115 passed** | `focused-embed.txt` |
| B11 target set | **24 passed** | `focused-b11.txt` |

Суммарно по прогонам — **1581 passed / 0 failed** (наборы намеренно пересекаются).
Целевые наборы embed расширены против 112 (+`test_embed_identity_compat`,
`test_embed_identity_compat_restart_legacy`, `test_embed_meta_wire`), поэтому 115,
а не 74; summary-набор совпал с базой (179).

Полный repository-wide suite в этом лейне **не запускался** (запрещено брифом).

## Изоляция

Основной чекаут (`C:\Code\Python\adminbot`, грязные планы/PNG) не изменялся.
Все работы — в `C:\Code\Python\adminbot-wt258113`. `git status` перед коммитом:
ровно 31 bump-файл (`final-diff-names.txt`) + этот каталог evidence.

## Честные примечания

- Документы embed-identity-compat пиновали SHA коммитов локальной ветки
  (`570e1eee`, `30a2f868`, `69da031c`, `cf7e00e3` и т.п.). После черри-пика
  SHA изменились; объекты исходных коммитов остаются в локальном репозитории,
  но в `origin/master` их нет. Это исторические evidence-привязки ветки,
  а не исполняемый контракт.
- Прод не трогался: деплой/рестарт — не в этом лейне. Для применения
  промпт-канонов ASAP-2 при деплое нужен плановый рестарт (наследие 2.58.112).
