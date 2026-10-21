# REL-258109 — релизный бамп 2.58.108 → 2.58.109 (PKG-109, 22.10.2026)

Лейн PKG-109. Процедура — бамп-прецедент 106–108 (31-файловый SET EQUAL набор).
Дельта — только версия/HEAD-токены + release evidence (жёсткий pathspec); чужой
dirty-worktree (181 tracked-модификация других лейнов) не захвачен.

## Состав релизной дельты (2.58.108 → 2.58.109, review Approved REV-INITREPLY)

| Коммиты | Суть |
|---|---|
| `77985666` | FIX-INITREPLY — `services/direct_chat_service.py`: reply_to_message_id binding для адресатных инициативных ответов (owner-obs diag 21.10.2026 §4: все 24/24 инициативных отправки за 7д уходили standalone). Резолвер «адресат → сообщение»: `source_refs` (`msg:<smart_messages.id>` → `tg_message_id`, ≤4, порядок сохранён) с фолбэком на последний `tg_message_id` адресата в чате; best-effort fail-open, 0 миграций. Reply ТОЛЬКО на первом чанке (прецедент `smartmodule_utils.send_chunked_reply`). Защита: цель старше 24 ч → без reply; 400 «message to be replied not found» → ровно один повтор без reply (reuse `_is_reply_target_gone`). Ностальгия/heartbeat (без адресата) — байт-в-бит прежний путь; R17: в логах только id. +5 CONTRACT/REGRESSION `tests/test_asap8_initreply_binding.py` (mock send, 0 provider-вызовов) |
| `1e3e5949` | docs-биндинги — «ФИКС ПРИМЕНЁН @77985666» в `plans/owner-obs-diagnostics-2026-10-21.md` §4 + evidence `initreply-fix.md` |

F8-meta HEAD-токен = **`1e3e5949`** — голова релизной дельты PKG-109; git HEAD на
пребампе = `1e3e5949`, расхождений нет.

## Bump-набор (31 файл = SET EQUAL процедурам 106–108)

| Роль | Файл(ы) | Замена |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.108"` → `"2.58.109"` (только версия, комментарий без изменений) |
| Версия | `README.md` | `v2.58.108` → `v2.58.109` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.108`→`2.58.109`; HEAD (short) `06b7ef4d`→`1e3e5949` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.108`→`2.58.109` (polygon — 2 вхождения) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.108` → `2\.58\.109` (regex) |

`git diff` по bump-набору = **31 файл, 33 пары строк, только version/HEAD-токены**
(bump-verify: non-token deltas NONE). Каталог не тронут (REGISTRY 582, Δ=0; F8
`--check`: **582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны).

Канонные счётчики каталога (582/171) не пересанкционировались — в поезде 109
нет изменений канонов/каталога; fingerprint остаётся **`c19d35a1c093`**
(константа corrective-волны `44a4827a`), офлайн-гвард: runtime
`factory_set_fingerprint()` == константа == `c19d35a1c093` — PASS (канонов в
поезде нет — не изменился, как и требовал бриф).

## Guards

| Проверка | Результат | Статус | Артефакт |
|---|---|---|---|
| Pre-bump (HEAD=1e3e5949, dirty∩bump=0, SET EQUAL proc-108, токены 32 вхождения в 31 файле, train be60041f..HEAD не трогал bump-набор) | PASS | VERIFIED | scratch `pkg-109/` (семантика вошла в bump-offline-check) |
| Offline-агрегат (17 проверок: settings/README/meta/токены/SET EQUAL/foreign-guard/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release, schema v37/fingerprint c19d35a1c093 live+import) | **EXIT 0, 17/17 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33, non-token deltas NONE, CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 106–108 | ref(108) 31 == bump(109) 31; ONLY IN 108: none; ONLY IN 109: none | VERIFIED | `delta-vs-108.txt` |
| ΔDDL (bump-scope + release-to-release; ≠ 0 → STOP) | **0 файлов** bump-набора в DDL-периметре; schema v37 не менялась; в release-дельте `be60041f..HEAD` из периметра — пусто (только `services/direct_chat_service.py` send-path best-effort без миграций + новый тест + docs/evidence) | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла | **868 passed / 0 failed, EXIT 0** — паритет 101–108 | VERIFIED | `pins24-summary.md`, `pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (набор не менялся — новых JS в поезде нет) | VERIFIED | `focused-js-unit.txt` |
| Node пин-регрессы | **5/5 OK** (4 js-пина + mini-lens) | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad**, EXIT 0 (= база 106–108) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `--check` | **CHECK OK: реестр 582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Write-points single-writer (`test_mca01_...` `-k write_points`) | **1 passed**, 32 deselected, EXIT 0 | VERIFIED | `focused-write-points.txt` |
| Цель: initreply-биндинг `test_asap8_initreply_binding.py` (3 CONTRACT + 2 REGRESSION) | **5 passed**, EXIT 0 | VERIFIED | `focused-initreply-binding.txt` |
| Цель: related инициативные сьюты (f6 23 + p0-init-arch 17 + w5-vitality 18 + w5-gates 17 + p0-initfix 10 + smartmodule_utils 36 + nostalgia-ab 8) | **129 passed**, EXIT 0 | VERIFIED | `focused-initiative-related.txt` |
| Цель: mca09 block_e/off_parity + mca10b a/c | **58 passed**, EXIT 0 | VERIFIED | `focused-mca09-mca10b.txt` |

## Изоляция

Полный снимок `git status --porcelain` — `final-diff-names.txt` (212 tracked
модификаций, из них 181 чужой dirty/untracked-хвост других лейнов не входит в
пакет). Коммит — только 31 файл + `plans/features/asap8-v6-3-live-correction/release-258109/`
(этот каталог) по явному pathspec. Review-evidence других лейнов в pathspec не
входят (foreign-guard PASS).

Не в скоупе лейна: пуш и деплой (по брифу PKG-109).

## Замечания (честные)

- **Интерпретатор гвардов.** Все pytest-прогоны через `.venv/Scripts/python.exe`
  (venv: aiogram 3.31.0, требование `requirements.txt aiogram>=3.31.0,<4.0.0`).
  Глобальный `py -3` (aiogram 3.29.1) даёт известный ложный красный на
  rich-publish тестах — диагностика в README REL-258108; в этом лейне глобальный
  интерпретатор для гвардов не использовался.
- **aiosqlite-ворнинги в related-сьютах.** `focused-initiative-related.txt` /
  `focused-mca09-mca10b.txt`: «closed 22/7 leaked aiosqlite connection(s)» при
  rc=0 и полных счётчиках (129/58 passed). Pre-existing наблюдение тест-инфы
  ( asyncio-таски тестов закрываются после LOOP teardown), на вердикт не влияет;
  зафиксировано как related-nonblocking.
- Комментарий `APP_VERSION` в settings.py остался от волны asap8-v6 (прецедент
  105–108: при бампе комментарий не переписывается, описание релиза живёт в
  commit message и этом README).
- Исторические ссылки «прод 2.58.108 = ровно эти байты» — провенанс
  прод-байтов 2.58.108, не пины версии; намеренно не менялись (после деплоя
  109 факт «прод 108» остаётся исторически верным для зафиксированных байтов).
