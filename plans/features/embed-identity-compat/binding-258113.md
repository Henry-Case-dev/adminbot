# EMBED-IDENTITY-COMPAT — привязка карты к релизному коммиту 2.58.113

Дата: 23.10.2026. Лейн: `PM-BIND-258113` (writer: только карты/документы/реестр).
Кандидат: `e4ee54f3` (`chore(release-258113): bump 2.58.112 -> 2.58.113`, полный SHA
`e4ee54f3…`, база `678c0616`, поезд 15 коммитов).
Карта: `plans/features/embed-identity-compat/requirements-map.json`
(`candidate_commit` = `e4ee54f3`, `deployed_commit` = `""`, `strict_evidence: true`,
`slice_graph_path: slice-graph.json`).

Код в поезде: `30a2f868` (identity split) + `570e1eee` (B1/B3) + gap-фиксы
`69da031c` → черри-пик в master-линию `d62e9720` + повторный прогон `128abcab` +
`ddf139a1` (EMBED-META-WIRE) + `244a9da4`/`e4b7c595` (resolver-pre) + bump `e4ee54f3`.
Факты поезда: guards 1581 passed / 0 failed, ΔDDL = 0, `FACTORY_SET=24ae494ac422`.

## 1. Что изменилось в карте

| Строка | Было | Стало | Основание |
|---|---|---|---|
| `IDENT-02` | PENDING | **VERIFIED** | `test_ident_02_msi_changes_with_every_identity_field` (L861), `..._stable_...` (L882): все 7 полей identity по отдельности меняют `model_space_identity()`; 27 passed в `test_embed_identity_compat.py` + 9 restart-legacy на `69da031c` (`d62e9720`), повтор `128abcab` |
| `CANARY-03` | PENDING | **VERIFIED** | `test_canary_03_probe_records_actual_metadata` (L922), `..._explicit_model_mismatch_is_incompatible` (L960), `..._missing_revision_or_params_not_insufficient` (L987); мета эмбеддинга доезжает из ответа (`test_embed_meta_wire.py` 4 passed, `test_llm_client.py` 115, `test_embedding_control_plane_asap4.py` 69) |
| `DEC-09` | PENDING | **VERIFIED** | `test_dec_09_rollback_after_adopt_keeps_data_and_is_reversible` (L1025): adopt → откат → vec закрыт, факты/векторы целы, FTS работает, повторный adopt успешен |
| `ACC-10` | READY_FOR_LIVE | **VERIFIED** | Production-evidence 2.58.113: adopt + canary + реальный поиск (`deploy-frozen-b92226cf.md`, sha `11667c19…`) |
| `ACC-11` | READY_FOR_LIVE | **VERIFIED** | То же |
| остальные 54 required-строки | VERIFIED на `570e1eee` | VERIFIED + запись, привязанная к `e4ee54f3` | Агрегированный guards-прогон поезда (`release-258113/guards.txt`); код строк не менялся, кроме gap-фиксов/meta-wire |

**Счётчики карты (required-строки, 59):** VERIFIED — **59**, READY_FOR_LIVE — **0**,
PENDING — **0**. Всего строк инвентаря 72 (13 `context`).

## 2. Evidence, привязанный к `e4ee54f3`

| Артефакт (repo-relative) | SHA-256 | Для чего |
|---|---|---|
| `plans/features/embed-identity-compat/evidence/gaps-closure.md` | `3345a14df259d3dccdd4741a23f40cdf9582e30ff6fb047d9bb2eae64e715714` | §1 IDENT-02, §2 CANARY-03, §3 DEC-09, Дополнение 4 (master-версия с пином `60789cff`) |
| `tests/test_embed_identity_compat.py` | `b90c6f9afac617259d024592102eb646183bef8c9c489fd613ca0df1b7401e70` | тесты IDENT-02/CANARY-03/DEC-09 |
| `tests/test_embed_meta_wire.py` | `41e2f4ff4a6976842545f01e4f7580188571b29df195cd8ba5d381b7919448e7` | CANARY-03 (мета из ответа) |
| `plans/features/embed-identity-compat/evidence/resolver-pre/report.md` | `e90d85c2f9b1df873240d52995ef10821704ac63cdc010d47f1786948196449b` | ACC-10/ACC-11 pre-deploy |
| `plans/features/_audit-2026-10-23/release-258113/guards.txt` | `0f353cf3fadcd2a424fc97afceb3481bf2fe0cdc95b07e4fecbfca1171549c73` | агрегированный прогон поезда |

## 3. Гейт

`requirements_gate.py check --map plans/features/embed-identity-compat/requirements-map.json
--stage review --slice <slice> --candidate e4ee54f3 --repo .`
(запуск в временном worktree, закреплённом на `e4ee54f3`, — карта скопирована туда;
причина: `evidence/gaps-closure.md` живёт в релизной линии `e4ee54f3`, а не в текущем
master-чекауте).

| Слайс | Строк в scope | Ошибки | EXIT |
|---|---|---|---|
| `IDENT-SPLIT` | 7 | 0 | **0** |
| `CANARY` | 10 | 0 | **0** |
| `DECISION` | 15 | 0 | **0** |
| `ACCEPT` | 14 | 0 | **0** |

**Release-gate после деплоя (23.10.2026, PM-BIND-DEPLOYED-258113):**
`check --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3 --repo .`
→ `stage=release inventory=43 manual=29 scoped=59 errors=0`, **EXIT 0**.

## 4. Честные ограничения

- Строки, доказанные на `570e1eee`, сохраняют файловое доказательство того прогона;
  привязка к `e4ee54f3` для них — агрегированный guards-прогон поезда, а не новый
  пофайловый прогон. Полный repository-wide suite в brief поезда не входил.
- Production-evidence указывает на замороженный снимок `deploy-frozen-b92226cf.md`
  (sha `11667c19…`): живой `deploy.md` продолжает дописываться VERIFY-лейном.
- Агрегированный `compat` в API пуст из-за legacy `graphrag_rebuild.payload` без `index`;
  совместимость подтверждена блоком `generation` и журналом — отдельная находка панели.

## 5. Что осталось до DONE

Ничего: `ACC-10`/`ACC-11` закрыты production-evidence, release-gate EXIT 0.
Задача `embed-identity-compat` — **VERIFIED** (59/59).
