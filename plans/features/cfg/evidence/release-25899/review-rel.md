# REV-REL-25899 — независимое ревью релизного кандидата 2.58.99

Дата: 20.10.2026. Роль: independent Reviewer (read-only + этот файл; прод/чаты не тронуты).
Вердикт: **Approved for controlled deployment, parent not DONE** (см. «Постдеплой»).

## Биндинг

- Кандидат: `46303ecd3ea145811edbfc79fbaba4d3d8f966d6` (= Approved-линия `8f220b60` CFG-06 v4 + bump/ресанкции/каталог/docs).
- База сравнения: `git diff 8f220b60..46303ecd`; родитель прода: 2.58.98 = `29cc49ba` (подтверждено rel-25898 evidence-коммитом `9f37c15a`). Рубеж отката `release/fix-2.58.98` — создаётся при push.
- Прогоны — во временном detached-worktree @ 46303ecd (samples-ux грязное дерево исключено); worktree удалён после проверки.

## Состав диффа (воспроизведено, 100 файлов)

- 31 bump (settings/README/F8-meta/24 py-пина/4 js-пина) — только токены `2.58.98→2.58.99`, `1b23d4c→8f220b60` + санкционированные 15 ресанкций/36 каталог-пар (offline-агрегат, pair-анализ).
- 34 tests-ресанкции: ровно 34 файла с инвариантом `== 461`, ВСЕ с маркером провенанса `CFG-06 v2 (5af56d8b)`; stale `== 458` — 0.
- 5 catalog: `services/param_catalog.py` (+3 ParamSpec `flags.factcheck_*` в существующую группу `flags_module_factcheck`, вкладка mod_factcheck in-place), tsv/screen-map/2 fixtures переизданы.
- 30 docs/evidence/maps. Класс «other» = 0. samples-ux/factcheck-runtime файлов в диффе НЕТ; секретов НЕТ (скан: только JS `token(name)` и provenance-проза).

## Runtime-дельта (п.4 брифа)

`git diff 8f220b60..46303ecd -- services/factcheck* services/tool_router.py services/chat_prompts.py` → ПУСТО. `services/factcheck_service.py` (`_temporal_verbalize`) — blob-идентичен `8f220b60` (`6ebe560b…`). Прод-поведение при OFF = Approved-кандидат.

## Стык каталог↔runtime

Все 3 pg_id совпадают с hot-ключами рантайма: `flags.factcheck_wide_context` (factcheck_context.py), `flags.factcheck_suitability_gate` (factcheck_suitability.py), `flags.factcheck_pipeline_v2` (factcheck_orchestrator.py/factcheck_planner.py); Settings-атрибуты существуют, все `default False`; fallback False, никогда не бросают. Round109-словарь: 3 новых описания — 0 нарушений (прямой чек + `test_webapp_round109_ui` 21p, тест покрывает весь реестр).

## Воспроизведённые прогоны (числа)

| Проверка | Результат |
|---|---|
| Offline-агрегат `verify_25899.py` (адаптация: `git diff 8f220b60` в чистом worktree = байт-эквивалент исходной процедуры) | **EXIT 0, 16/16 PASS** (84 пары = 33 версия + 15 ресанкций + 36 каталог; ΔDDL=0; дизъюнкция с samples-ux/factcheck) |
| `gen_param_registry_round1025.py --check` | **CHECK OK: 582 == REGISTRY**, EXIT 0 |
| `test_param_catalog.py` / `test_round1025_f8_registry.py` / help-sync / mca17c / webapp_hotfix8 | **34p / 29p / 24p / 8p / 20p** (батч 115 passed, 0 failed) |
| mca17c в чистом дереве | 8/8 — подтверждает foreign-объяснение 1f (samples-ux v37) из pins-fix.md |
| JS-syntax sweep `node --check` (web + tests/js) | **106 файлов, 0 bad** |
| 4 изменённых js-пина (node) | **4/4 OK** |
| settings import | APP_VERSION `2.58.99`; `fields(Settings)==461`; 3 флага = False |
| round109 UI-copy тест | 21p |

Fingerprint-биндинг: `config/settings.py` и `README.md` sha256 совпадают с `frozen-fingerprint.txt` байт-в-байт; worktree-файл == блоб коммита (hash-object) для meta.md.

## Гейт (п.6) и owner-optional

`requirements_gate.py check --stage review --slice CFG-06 --candidate 5af56d8b…` → **EXIT 1, ровно 5 ошибок**: E.4/F.1/G.1/G.4 (preprod RFL — канарейки, закрываются на `--stage release` после выката+флага) + G.3 (PENDING, post-release). F.6/J.6/06.B — корректные postdeploy RFL (гейтом на review разрешены); G.8 — owner_optional. Леджер CFG-06: 93 = 84 VERIFIED + 8 RFL + 1 PENDING — совпадает с фактом. Owner-optional: 11 строк (9 карт + CFG-04D.4/CFG-06G.8), у всех `owner_policy_ref` + reason 146–250 симв. + непустые `engineering_req_ids` + `live_required=false`, статусы не FAILED; смешанных строк нет.

## Находки

- NONBLOCKING-1: `frozen-fingerprint.txt` — строка `meta.md` (sha256 `d7c6e574…`) не соответствует кандидату (факт `3e6f7f581cb1…`; settings/README совпадают). Промежуточное состояние фикс-лейна каталога до переиздания meta.md; кандидат верифицирован независимо. Исправление: перезакрепить строку @ 46303ecd в том же коммите, что и этот файл.
- NONBLOCKING-2: README release-25899, guards-таблица — «CHECK OK (579 == REGISTRY)» — устаревшая цифра повествования; артефакт `gen-param-check.txt` и независимый прогон: 582.

## Постдеплой (обязательства до `--stage release`; PET_PROJECT, без сообщений в реальные чаты)

1. Деплой 46303ecd; healthz 200, ERR-лог чистый, смоук.
2. Hot-включение `flags.factcheck_pipeline_v2=true` (wide context/suitability gate подразумеваются); откат — `false` без рестарта; cold — revert к `release/fix-2.58.98` = `29cc49ba`.
3. Канарейки 06G.1/06G.4 — тестовый контур; 06G.3 — post-release; E.4/F.1/F.6/J.6/06.B — по картам; строки → VERIFIED с evidence @ фактический SHA.
4. `requirements_gate.py check --stage release --candidate 46303ecd… --deployed-commit <фактический SHA>`; deployed_commit карты → фактический.

## Команды (DevOps)

```
git branch release/fix-2.58.98 29cc49ba          # рубеж отката
git push origin 46303ecd3ea145811edbfc79fbaba4d3d8f966d6 release/fix-2.58.98
# далее штатный деплой-процикедур (deploy_commands.txt, один recon + один основной прогон)
```