# Релиз 2.58.242 — сборка (QRNG IBM P5A+P5B)

- **Роль:** Builder (сборка релиза). **Без деплоя и SSH** — выкладка и post-deploy за DevOps.
- **База (фактический production):** `3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c` = 2.58.241,
  tree `853dd3b471034fb297753604d98367ed208dbf6f`.
- **Owner-источники:** `plans/owner_inputs/2026-11-24-qrng-ibm-p5-ui-correction.md`
  (sha256 `9386ecca7fa5259d8ad52d06699ccbe7d638f53cab7149721984dc016410b1cb`);
  `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §4
  (sha256 `6631186ccfbc3ba81c369f18bca6168a33ac20ad1e2f789cae3d34348ea8c73d`).
- **Строки:** `QAN-REC-IBM-01/02/03` — **REVIEW**, `live_required=true`,
  `live_when=postdeploy`; hardware VERIFIED этим релизом **не заявляется**.

## 1. Линия и решение

Production 2.58.241 **не содержит P5A**: в `3f42cfdd1` нет `qiskit`, нет
`tests/test_qrng_p5_ibm_adapter.py`, `services/mca_random_source.py` = 193 956 B
против 355 780 B на P5B-tip; P5A-коммиты живут только в
`fix/qrng-p5a-2026-11-24` и `feat/qrng-ibm-p5b-2026-11-24`. UI-06/07 действительно
в 2.58.239 (`8097c0b9e` — предок `6123a1469`). Поэтому 2.58.242 несёт **P5A+P5B
вместе**; релиз только трёх P5B-коммитов поверх 2.58.241 невозможен.

- **Ветка:** `release/qrng-ibm-p5b-2.58.242` от `3f42cfdd1`.
- **Источник слайса:** `feat/qrng-ibm-p5b-2026-11-24` tip
  `8ac5b927a16515f5d34779528ed2f2ae2c2905d8`; merge-base с базой `26aadf208`.
  Полная дельта: **34 коммита (1 merge) / 90 файлов / +8627−260**.
- **Replay:** `git rebase --onto 3f42cfdd1 26aadf208` → **33 non-merge коммита**
  легли линейно; merge `fa9e8b3f6` снят (UI-06/07 уже в базе, его содержимое
  дублировать не нужно).
- **Конфликты (2 файла, разрешены механически):**
  - `plans/docs/param-registry-round1025.meta.md` — оставлены базовые штампы
    `APP_VERSION 2.58.241` / `HEAD 61d54788f`; взяты P5-счётчики `659/258` и
    IBM-ключи (они — часть P5A).
  - `tests/test_round1025_f8_registry.py` — `PARAM_CATALOG_SHA256_FOLLOWUP`
    установлен в фактический sha256 объединённого `services/param_catalog.py`
    `c7cb2bdbd76879018df2e7e2595a8421ae102566a50ba939f312b421df0fb6ae`;
    счётчики `659/258`. Иных продуктовых конфликтов не было.
- **Content tip:** `10b34b03cd1c68af8cf96fed1f41b4d47b4669c4`,
  tree `01ce2726357e06bce91dfe2ee89abb7c7bb49396`.

```json
{
  "release": "2.58.242",
  "slice": "QRNG-IBM-P5A-P5B",
  "rows": ["QAN-REC-IBM-01", "QAN-REC-IBM-02", "QAN-REC-IBM-03"],
  "row_status": "REVIEW",
  "deployed_base": {"sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c", "version": "2.58.241",
                    "tree": "853dd3b471034fb297753604d98367ed208dbf6f"},
  "source_branch": {"name": "feat/qrng-ibm-p5b-2026-11-24",
                    "tip": "8ac5b927a16515f5d34779528ed2f2ae2c2905d8",
                    "merge_base": "26aadf208efdd6b2ca91081903e87ff8f74c084f",
                    "delta": {"commits": 34, "merges": 1, "files": 90,
                              "insertions": 8627, "deletions": 260}},
  "replayed": {"onto": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
               "commits": 33, "merge_commits_dropped": 1},
  "content_tip": {"sha": "10b34b03cd1c68af8cf96fed1f41b4d47b4669c4",
                  "tree": "01ce2726357e06bce91dfe2ee89abb7c7bb49396",
                  "delta_vs_base": {"files": 90, "insertions": 8626, "deletions": 259}},
  "bump_tip": {"sha": "dfa5118fd294c565e906ff6b78c75bf83427b4fc",
               "tree": "703e0651802b80a5d9da0929d8b6be6d0a830a8e",
               "version": "2.58.242"},
  "approvals": {
    "p5a_r8": {"artifact": "plans/features/vmq-onto-01/evidence/qrng-p5-ui/review-p5a-r8.md",
               "sha256": "cf0dbe2b7b45f6f4415ed2d391ea18e415bcfa4340bda610a1bf5cabdcde5fa",
               "verdict": "APPROVED_FOR_LIVE_PREP"},
    "p5b_r3": {"artifact": "plans/features/vmq-onto-01/evidence/qrng-p5-ui/p5b-review-r1.md",
               "sha256": "a37b5a94122c9b88f5a355c66eae4d2c67fc4b1caa70a6683b42a8af6a3fe79b",
               "verdict": "APPROVED_FOR_RELEASE_PREPARATION", "candidate": "8ac5b927a"}
  },
  "rollback": {"code_only_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
               "ddl": 0, "migrations": 0, "flags": 0, "data_migration": false}
}
```

## 2. Границы дельты

| Проверка | Результат |
|---|---|
| `git diff --name-only 3f42cfdd1..10b34b03c` vs исходная дельта `26aadf208..8ac5b927a` | **наборы идентичны, 90/90, расхождений 0** |
| `services/mca_random_source.py`: diff релиза vs исходная дельта | **байт-идентичен** |
| Рост `services/mca_random_source.py` | **+3381** строк (P5A+P5B), `qiskit` 19 вхождений |
| `requirements.txt` | **+5** строк: `qiskit-ibm-runtime==0.52.1` (ленивый импорт, `dependency_missing` без пакета) |
| `migrations/*`, `services/database.py`, `services/pg_db.py`, `services/mca_gates.py` | **не изменялись; DDL 0** |
| Новые feature-флаги | **0**; `config/settings.py` +11 — только env-fallback поля `RANDOM_IBM_*`, не флаги |
| `services/chat_clock.py`, `tool_router.py`, `embedding_control_plane.py`, `direct_chat_service.py`, `auto_budget.py` | **не изменялись** |
| `web/app.js` / `web/index.html` / `web/api/routes.py` | только P5-аддитивные блоки (IBM-карточка/поля/check/smoke/refill), без переписывания чужих секций |

Единственное отличие content-дельты от исходной (90 файлов, **+8626/−259** против
**+8627/−260**) — строка `HEAD (short)` в F8 meta: оставлен базовый `61d54788f`
вместо веточного `b81ec52aa`; продукт не затронут.

## 3. Bump 2.58.241 → 2.58.242

`dfa5118fd` — **standard version wave**, ровно тот же набор из 32 файлов и те же
**+35/−35**, что и bump 2.58.241 (`0d97fec12`): `APP_VERSION = "2.58.242"`,
F8 meta APP_VERSION, 26 py-пинов и 4 JS-пина. README не менялся (pre-existing
дефект, вне слайса). Полная дельта `3f42cfdd1..dfa5118fd`: **100 файлов,
+8661/−294** (90 файлов P5 + 32 bump − 22 пересечения; пересечения — те же
P5-файлы, где bump меняет только строку версии).

## 4. Тесты на bumped tip

| Команда | Результат |
|---|---|
| `py -m pytest tests/test_qrng_p5_ibm_adapter.py -q` | **77 passed** |
| `py -m pytest tests/test_qrng_p5b_ibm_admin.py -q` | **14 passed** |
| Комбинированный QRNG/F8/UI-mirror/route набор (P5, P5B, F8, param_catalog, P1/P2/P3, f01, asap5, webapp_js_unit, mca10a C/D/JS, mca10b D, mca19 E) | **411 passed, 1 deselected**; deselected F8 subprocess-тест отдельно — **1 passed** |
| `node tests/js/qrng_p5b_ibm_fields_test.js` | `QRNG-P5B-OK` |
| `node tests/js/qrng_ui07_provider_block_test.js` | `QRNG-UI07-OK` |
| `node tests/js/qrng_ui_state_test.js` | `QRNG-UI06-OK` |
| `node tests/js/qrng_p4_random_ui_test.js` | `QRNG-P4-UI-OK` |
| `node tests/js/round1037_random_source_test.js` | `MCA10A-RANDOM-OK` |
| `node tests/js/round1025_f5_workspace_route_test.js` | `MODULE-WORKSPACE-OK` |
| Version-pin guard: `py -m pytest <23 app_version-файла> -k app_version -q` | **20 passed, 1 failed** (pre-existing README, §5) |
| `py -m py_compile services/mca_random_source.py web/api/routes.py services/param_catalog.py config/settings.py services/output_projection.py services/status_service.py` | **rc 0** |
| `git diff --check` (рабочее дерево и `3f42cfdd1..HEAD`) | **rc 0** |
| `py tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 659 == REGISTRY** |

## 5. Pre-existing падения (не относятся к слайсу; не правились)

1. `tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced` — `assert 2 == 1`.
2. `tests/test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated` — та же причина;
   вместе **2 failed**.
3. `tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme` —
   README содержит последний пин `v2.57.0`, не `v2.58.242`; **1 failed**, README в релизе
   не менялся.
4. `SIMPL-R1-F2` (`assert ... <= 1` в `tests/test_p0_embed_admission_msi.py`) — файл
   **байт-идентичен базе** (`git diff` пуст); осознанно не менялся (backlog).

## 6. Manifest dry-run

Чистое дерево `dfa5118fd`; `.deploy/release.json` (gitignored) временно заполнен
production-манифестом `3f42cfdd1 / 2.58.241` для честного `previous`:

```json
{
  "schema": 1,
  "deployed_sha": "dfa5118fd294c565e906ff6b78c75bf83427b4fc",
  "version": "2.58.242",
  "effect": "deploy",
  "previous_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
  "previous_version": "2.58.241",
  "dirty_tracked": false,
  "release_branch": "release/qrng-ibm-p5b-2.58.242"
}
```

`--dry-run` ничего не записал; временный seed удалён. На хосте DevOps повторяет
manifest на **точном deployed SHA** (evidence-коммит меняет только docs).

## 7. Post-deploy (агенты проверяют; owner — только key+CRN)

- `GET /api/config` и UI: key/CRN только `{configured,last4}`/маска; raw key/CRN
  отсутствуют в DOM, network, логах, 422/ошибках.
- Состояния IBM: unconfigured → saved/unverified → stale при правке черновика →
  read-only check → отдельный hardware smoke; «сохранён» не выдаётся за «проверен».
- `/api/status.random`: reserve/fallback counters и фактические переходы
  IBM→ANU/LfDr; `max_inflight=1`, дневные лимиты; никакого скрытого PRNG.
- **Hardware VERIFIED не заявлять:** реальный QPU/IAM/queue/RU остаются live-only
  до фактического прогона на deployed SHA с реальными key/CRN.
- Owner-only шаг: админка → «Модули» → «Случайность» → IBM: API key + CRN,
  сохранить, read-only check; опционально ограниченный smoke (тратит квоту).
- Rollback: **`3f42cfdd1` code-only**; DDL/миграций/флагов нет, данные не мигрируют.
