# Релиз 2.58.244 — сборка (QRNG UX UI-08..10)

- **Роль:** Builder (локальная сборка). **Без деплоя и SSH** — выкладка и
  post-deploy за DevOps.
- **База (production 2.58.243):** `10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6`.
- **Ветка:** `release/qrng-ux-2.58.244` от `10f7c0f5e`.
- **Рекомендация независимого ревью:**
  `plans/features/vmq-onto-01/evidence/qrng-p5-ui/ui08-10-review-r1.md`,
  r5 close: **APPROVED_FOR_RELEASE_PREPARATION** для product `9c6d74023`,
  evidence `eecfdd148`; sha256 файла
  `9bb0aaf527661b29a14f1d04f9838166e9fd3a5acc19a17864a937e4657126d2`.
  Файл ревью — untracked-артефакт ревьюера, в release-ветку не переносился
  (как и в 2.58.243).
- **Builder evidence:** `plans/features/vmq-onto-01/evidence/qrng-p5-ui/ui08-10-2026-11-25.md`.
- **Строки:** `QAN-REC-UI-08`, `QAN-REC-UI-09`, `QAN-REC-UI-10`.

## 1. Линия и интеграция

- `10f7c0f5e` — предок `eecfdd148` (merge-base совпадает с базой), поэтому
  `git rebase --onto 10f7c0f5e 10f7c0f5e eecfdd148` — **no-op**: 10
  UX-коммитов уже линейны над production-базой, конфликтов и ручных
  разрешений нет.
- Release-ветка создана от `10f7c0f5e` и fast-forward до `eecfdd148`;
  деревья совпадают с проверенным кандидатом.
- **Content tip:** `eecfdd14842973d9dbea346bd3e3e230af91f5c0`
  (tree `60f37124d214edff875833e2721bd412ab0d2033`).
- **Product tip (проверенный ревью):** `9c6d74023cf13439f9b106d611271b2b6dd2a545`.

```json
{
  "release": "2.58.244",
  "slice": "QRNG-UX-UI08-10",
  "rows": ["QAN-REC-UI-08", "QAN-REC-UI-09", "QAN-REC-UI-10"],
  "base": {"sha": "10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6",
           "version": "2.58.243"},
  "source_branch": "feat/qrng-ux-2026-11-25",
  "source_product_tip": "9c6d74023cf13439f9b106d611271b2b6dd2a545",
  "source_evidence_tip": "eecfdd14842973d9dbea346bd3e3e230af91f5c0",
  "content_tip": {"sha": "eecfdd14842973d9dbea346bd3e3e230af91f5c0",
                  "tree": "60f37124d214edff875833e2721bd412ab0d2033",
                  "commits": 10,
                  "delta_vs_base": {"files": 16, "insertions": 3192,
                                    "deletions": 376}},
  "bump_tip": {"sha": "93102d860f447ef261a4842b6721ae0c56f90af1",
               "tree": "fba88b4ae941c0593efbda2cf4a7bd4b5cc85bc7",
               "version": "2.58.244",
               "delta": {"files": 32, "insertions": 35, "deletions": 35}},
  "rollback": {"code_only_sha": "10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6",
               "ddl": 0, "migrations": 0, "flags": 0,
               "data_migration": false}
}
```

## 2. Границы дельты `10f7c0f5e..93102d860`

| Проверка | Результат |
|---|---|
| Всего файлов | **48**: 16 UX-слайс + 32 bump; `+3227/−411` |
| UX-слайс | `web/app.js` (+250/−22), `web/index.html` (+303/−325), `services/mca_random_source.py` (+15/−10), `tests/test_qrng_p3_selector.py` (+37), `tests/js/qrng_ui08_main_screen_test.js` (новый, 756), `tests/js/qrng_ui_state_test.js` (+28/−19), `tools/ui_qrng_ux0810_e2e.py` (новый, 773), evidence (9 файлов) |
| Bump | ровно 32 файла, `+35/−35` — только `APP_VERSION`/version pins (см. §3) |
| `migrations/` | **0** |
| `config/` | только `config/settings.py` (строка `APP_VERSION`) |
| Новые флаги (`ClassVar[bool]`) | **0** |
| Backend/API/DB | меняется только `services/mca_random_source.py` (семантика порядка, §4); API/DTO/ParamSpec/схема/DDL — **0** |
| Прочее | `web/api/`, `services/database.py`, `requirements.txt`, `prompts/`, планировщики — **0** |

Схема остаётся **v48/DDL 0**, миграций и изменений данных нет.

## 3. Bump 2.58.243 → 2.58.244

`93102d860` — **standard version wave**: 32 файла, `+35/−35`, тот же набор,
что bump 2.58.243 (`fc1d25242`): `APP_VERSION = "2.58.244"`, F8 meta
`APP_VERSION`, 26 py-пинов и 4 JS-пина (escaped-форма `2\.58\.244`).
Проверено: во всех 31 прочих файлах diff — только замена версии; в
`config/settings.py` изменена ровно одна строка (новый clause 2.58.244 +
прежний head → `Prior (25.11.2026): 2.58.243 - VMQ-MEM RC1-RC7`).
`git diff --check` — rc 0.

## 4. Что теперь на главном экране «Случайность»

Одна рабочая поверхность вместо прежних параллельных представлений:

- шапка модуля: название/описание, GLOBAL/чатовый переключатель,
  effective badge и «Проверено» для `mod_random`;
- карточка «Случайность»: **один** select основного источника с подсказкой
  «Выбрано вручную / По умолчанию / Требует разрешения» и provenance;
- **один** тумблер авторезервирования с provenance («наследуется по
  умолчанию (включена)» / «включено» / «выключено»);
- **одна** последовательность резервных источников с ↑/↓ и явным chip
  «сохранено вручную / сохранено пусто / сохранено / не сохранено»;
- «Сейчас используется»: фактический effective-провайдер, честная причина
  (`переключение с IBM Quantum: источник не настроен`) и время;
- таблица провайдеров: `используется`, статус (`проверено / не проверено /
  недоступен / выключен / нет данных`), счётчик запаса;
- строка последнего успешного получения.

**Убрано в collapsibles (закрыты по умолчанию):** «Провайдеры» (ключи,
save/check/smoke по каждому провайдеру, masked-поля, IBM instance/CRN),
«Диагностика» (canonical/сохранённый/эффективный порядок, raw-значения,
слои источников, последняя причина), «Использования» (`memory.random_uses_*`)
и «Дополнительно» (режим `memory.random_source`, псевдослучайный fallback,
батчи/refill/IBM-очередь). Секреты и служебные raw-значения на главном
экране не отображаются; открытие details не делает сетевых запросов.

## 5. Backend-семантика (важное для delta-ревью)

`services/mca_random_source.py` меняет только расчёт действующего порядка
(`build_effective_order` / `resolve_selection`), **без** новых API/DTO:

- `primary is None` (строка `random.primary_provider` не сохранена =
  наследование заводского IBM): сохранённый `fallback_order` **теперь
  действует** — голова = заводской primary, хвост = явный пользовательский
  порядок. Ранее сохранённый порядок игнорировался и подставлялась вся
  заводская цепочка IBM→ANU→LfDR (F-UI0810-R1-01).
- Явный **пустой** сохранённый порядок = «**без резерва**»:
  `build_effective_order(None, [], True) == ('ibm_quantum',)`, а не заводская
  цепочка.
- `order is None` (строки нет) = наследование заводского хвоста ANU→LfDR.
- Недействительный сохранённый primary (`requires_resolution`) передаётся
  вызывающим как `None` + заводской хвост: порядок под снятое значение
  **не применяется** (arch P3/EXC-03).
- Дубли и сам primary из хвоста исключаются; при `fallback_enabled=false`
  остаётся только primary.

Тесты этой семантики (на bumped tip):

| Тест | Результат |
|---|---|
| `test_qrng_p3_selector.py::…::test_inherited_primary_honours_saved_fallback_order` | passed (в составе 53) |
| `test_qrng_p3_selector.py::…::test_inherited_primary_explicit_empty_reserve_has_no_fallback` | passed (в составе 53) |
| `pytest tests/test_qrng_p3_selector.py -q` | **53 passed** (11.75 s) |

UI дополнительно различает saved-mismatch и absent-mismatch (truthful
labels), не заявляет «сохранено» без реальной сохранённой строки и не
скрывает заводскую цепочку при absent-mismatch; positive «Сохранённые
настройки не будут изменены» — только при `saved == effective`.

## 6. Тесты на bumped tip `93102d860`

| Команда | Результат |
|---|---|
| QRNG pytest set: `test_webapp_js_unit`, `test_mca10a_random_source_js_round1037`, `test_qrng_p5b_ibm_admin`, `test_qrng_p5_ibm_adapter`, `test_qrng_p3_selector`, `test_qrng_p2_lfdr`, `test_qrng_p1_isolation` | **285 passed** (38.31 s, 3 warnings) |
| `test_qrng_p3_selector.py -q` | **53 passed** (11.75 s) |
| block A..E + JS: `test_mca10a_random_source_block_{a,b,c,d,e}_round1037.py`, `test_mca10a_random_source_js_round1037.py` | **80 passed, 1 failed** — pre-existing, §7 |
| `tests/js` полностью (`node --test "tests/js/*_test.js"`) | **135 pass, 3 fail** — те же pre-existing, §7 |
| 4 JS version-pin теста `round1025_hotfix{7,8,9,10}_*` | **4 pass, 0 fail** |
| Version-pin guard: 20 файлов `def test_*app_version*`, `-k app_version` | **20 passed, 1 failed** — pre-existing README, §7 |
| `py -m py_compile` по всем 30 изменённым `.py` дельты | rc 0 |
| `node --check web/app.js` | rc 0 |
| `git diff --check` (worktree и `10f7c0f5e..HEAD`) | rc 0 |

## 7. Pre-existing (воспроизведено на базе `10f7c0f5e`, не правились)

1. `tests/test_mca10a_random_source_block_e_round1037.py::test_reason_codes_additive_only`
   — падает одинаково на базе и на bumped tip (**1 failed**).
2. `tests/js/evol_cog_scene_test.js`, `tests/js/round1025_ia_routing_test.js`,
   `tests/js/ur_ui_settings_test.js` — те же 3 падения на базе
   (**135 pass / 3 fail**), к QRNG не относятся.
3. `tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme`
   — README содержит `v2.57.0`; воспроизведено на базе (**1 failed**).

## 8. Playwright + Browser Use (bumped tip)

- **Playwright visual/behavior gate**
  `py tools/ui_qrng_ux0810_e2e.py --out <run>/playwright`:
  **144 checks, 0 fail**; viewports 1440×900 / 1280×800 / 390×844 / 320×700;
  page/console errors 0; no overflow; один primary/тумблер/порядок; все
  4 details закрыты; 3 строки провайдеров; min font 11.52; секретов на
  главном экране нет; draft save/cancel, explicit fallback off, keys
  expand/collapse с нулевой сетевой дельтой, diagnostics raw — PASS.
- **Browser Use** (headless Chrome/CDP против того же mock-DTO):
  - normal 1440×900 и 390×844: 0 errors, no overflow, один primary/тумблер/
    последовательность, 4 details закрыты, 3 провайдера, min font 11.52,
    секретов/legacy-подписей на главном нет; effective ANU, reason
    атрибутирован IBM;
  - inherited saved (primary не сохранён, порядок LfDR→ANU): select
    `ibm_quantum`, hint «По умолчанию», chip «сохранено вручную», effective
    **LfDR**, note «Сохранён ваш порядок резерва.», reason атрибутирован
    IBM — 1440×900 и 390×844; overflow/errors 0.
- Обе проверки — mock-DTO, **не live `/api/status`**; live-проверка
  остаётся preprod/post-deploy шагом DevOps.

## 9. Остаточный backlog (не блокирует)

Absent-mismatch chip «Заводской источник выбран» остаётся положительным,
хотя тот же note может говорить «Доступность источников: 0»; note прямо
называет это расхождение. Это wording/polish в mixed/old-DTO состоянии, не
заявление о сохранённой настройке и не сокрытие заводской цепочки —
**BACKLOG**, не release-блокер (зафиксировано в r5 review).

## 10. Rollback

- **Code-only:** `10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6` (2.58.243),
  manifest `--effect rollback`.
- **DDL 0, миграций 0, флагов 0**, данные и настройки не мигрируют и не
  откатываются. Схема остаётся v48. `requirements.txt` не менялся.

## 11. Manifest dry-run

Чистое tracked-дерево `93102d860`; `.deploy/release.json` (gitignored)
временно содержал production-манифест `10f7c0f5e / 2.58.243` для честного
`previous`:

```json
{
  "deployed_at": "2026-11-24T19:24:30.709554Z",
  "deployed_sha": "93102d860f447ef261a4842b6721ae0c56f90af1",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6",
  "previous_version": "2.58.243",
  "release_branch": "release/qrng-ux-2.58.244",
  "schema": 1,
  "version": "2.58.244"
}
```

`--dry-run` ничего не записал; seed удалён. Evidence-коммит меняет только
docs; DevOps повторяет manifest на **точном deployed SHA**.

## 12. Post-deploy

См. `deploy-checklist-2.58.244.md`: структура главного экрана, один порядок,
состояния провайдеров, отсутствие дублей, неизменность reserve-счётчиков,
inherited-saved семантика, health/version/schema и логи.
