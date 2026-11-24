# Релиз 2.58.243 — сборка (VMQ-MEM RC1–RC7)

- **Роль:** Builder (локальная сборка). **Без деплоя и SSH** — выкладка и
  post-deploy за DevOps.
- **База (фактический production):** `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`
  = 2.58.242, tree `b2205b58696b98e8a03fd6f2545fa35a3d9ce9d7`.
- **Ветка:** `release/vmq-rc-2.58.243` от `ff226ca0a`.
- **Замер/приёмка RC:** `plans/features/vmq-onto-01/evidence/vmq-mem/remeasure-2026-11-25.md`
  (commit `b47d6c9ac`, sha256 `853eb58f5158a7e4c8a3eccf865f8faf3b134d7ac9559d41e3de9c365696c261`;
  docs на master, в release-ветку не переносился).

## 1. Линия и интеграция

- **Источник RC:** combined-ветка `51f60a3c65a031bcc790309ca3db7e9aa51007db`
  (merge `7ded3e68a` + `a5fee8c7d`, собран на `3f42cfdd1` = 2.58.241).
- **Merge-base с базой:** `3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c`
  (2.58.241 — предок `ff226ca0a`). Веточные предки RC (`a5fee8c7d`,
  `7ded3e68a`) не являются предками `ff226ca0a`, поэтому переносится только
  дельта `3f42cfdd1..51f60a3c6`.
- **Пересечение путей:** дельта 2.58.242 (`3f42cfdd1..ff226ca0a`, 103 файла)
  и дельта RC (`3f42cfdd1..51f60a3c6`, 50 файлов) — **пересечение 0**;
  содержимое 2.58.242 (P5A/P5B, embedding, chat-clock) merge не затрагивает.
- **Предпроверка:** `git merge-tree --write-tree --merge-base=3f42cfdd1
  ff226ca0a 51f60a3c6` → tree `b7c9621630e6a3af57f30d9fa80ae0d6f643d2c2`,
  конфликтов 0.
- **Фактический merge:** `git merge --no-ff 51f60a3c6` — **конфликтов нет**,
  ручных разрешений нет; дерево результата **совпало** с предвычисленным
  `b7c962163…` (механическое доказательство отсутствия ручной правки).
- **Content tip:** `95336488d83f192900192cf55ae60f5e2d1dcd02`,
  tree `b7c9621630e6a3af57f30d9fa80ae0d6f643d2c2`; 12 коммитов (11 RC + merge).

```json
{
  "release": "2.58.243",
  "slice": "VMQ-MEM-RC1-RC7",
  "rows": ["VMQ-MEM-02", "VMQ-MEM-03", "VMQ-MEM-04"],
  "deployed_base": {"sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
                    "version": "2.58.242",
                    "tree": "b2205b58696b98e8a03fd6f2545fa35a3d9ce9d7"},
  "source_merge": {"sha": "51f60a3c65a031bcc790309ca3db7e9aa51007db",
                   "parents": ["7de1d5dcef846737687eb83dce4d1c7062b1ec42",
                                "a5fee8c7dfd70db92e402bb1ecb75f97679cf6ad"],
                   "built_on": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
                   "merge_base_with_base": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c"},
  "content_tip": {"sha": "95336488d83f192900192cf55ae60f5e2d1dcd02",
                  "tree": "b7c9621630e6a3af57f30d9fa80ae0d6f643d2c2",
                  "delta_vs_base": {"files": 50, "insertions": 6097, "deletions": 90}},
  "bump_tip": {"sha": "fc1d25242d20dc09d443bfcad5aea8a108f2324e",
               "tree": "31aeb4dbf4e10e80288bed89d8a39364b30bf272",
               "version": "2.58.243", "delta": {"files": 32, "insertions": 35, "deletions": 35}},
  "test_alignment_tip": {"sha": "250eb06536f16196e86412a902e1461ffe8871f1",
                         "tree": "d340bf473e9c7742ca00e019713114c33d56aa21"},
  "rollback": {"code_only_sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
               "ddl": 0, "migrations": 0, "flags": 0, "data_migration": false}
}
```

## 2. Границы дельты `ff226ca0a..95336488d`

| Проверка | Результат |
|---|---|
| Файлы дельты | **50**: 36 evidence (`plans/features/vmq-onto-01/evidence/vmq-mem/rc*`), 6 `services/*`, 8 `tests/*` |
| `migrations/` | **0** |
| `config/` (новые флаги/настройки) | **0** — `config/settings.py` дельтой не менялся |
| `web/` (UI/API) | **0** |
| `requirements.txt` / `tools/` | **0** |
| P5/embedding/chat-clock | **0 файлов**; `direct_chat_service.py` меняется только RC1 (legacy reserve) и RC7 (story→anchor bridge), ChatClock/embedding не затронуты |
| DDL (CREATE/ALTER/DROP/ADD COLUMN, `user_version`, `SCHEMA_VERSION`) в `services/database.py` | **0 вхождений**; изменения — только read-path SQL: новый `search_messages_fts_ranked_window()` и read-проекция `get_persona_card()` (`facts_meta`, alias-canon links) |
| Новые feature-флаги (`ClassVar[bool]`) | **0** |

Схема остаётся **v48/DDL 0**, миграций и изменений данных нет.

## 3. Bump 2.58.242 → 2.58.243

`fc1d25242` — **standard version wave**: тот же набор из 32 файлов и те же
**+35/−35**, что и bump 2.58.242 (`dfa5118fd`): `APP_VERSION = "2.58.243"`,
F8 meta `APP_VERSION`, 26 py-пинов и 4 JS-пина (в JS — escaped-форма
`2\.58\.243`). Проверено: во всех 31 прочих файлах diff — только замена
версии; в `config/settings.py` изменена ровно одна строка (новый clause
2.58.243 + прежний head → `Prior (25.11.2026): 2.58.242 - QRNG…`, как в
предыдущих bump). README не менялся (pre-existing дефект, §5).

## 4. Тесты на bumped tip (250eb0653)

| Команда | Результат |
|---|---|
| 7 focused RC-файлов (`test_vmq_mem_rc{1,2,3,4,5a,6a,7}_*.py`) | **31 passed** (25.52 s) |
| episodes+retrieval+period: `test_mca05_episodes_stories`, `test_evol021_episode_semantics`, `test_vmq_m1_episode_contract`, `test_mca07_retrieval_context`, `test_vmq_mem_retrieval_fixes`, `test_vmq_recent_window`, `test_memory_period_vector_leg`, `test_vmq_mem_period_intent` | **261 passed** (43.98 s) |
| `test_graphrag_memory`, `test_graphrag_database`, `test_summary_memory` | **316 passed** (46.40 s) |
| `test_vmq_mem_slice_d`, `test_round1025_f8_registry` | **70 passed** (8.31 s) |
| Version-pin guard: 13 файлов с `test_*app_version*`, `-k app_version` | **20 passed, 1 failed** — pre-existing README (§5) |
| `py_compile` по 6 изменённым модулям + `config/settings.py` + `tests/test_vmq_mem_period_intent.py` | **rc 0** |
| `git diff --check` (worktree и `ff226ca0a..HEAD`) | **rc 0** |

### 4.1. Обязательная правка теста (в scope RC4, не ослабление)

`tests/test_vmq_mem_period_intent.py::test_single_weak_row_does_not_assemble_block`
падал на 2.58.241+RC: прежний фикстур «шизы на конфе обсуждали» после RC4
(A2, one-normalization short-stem) даёт **2** общих стема (`шиз`, `конф`) и
**законно** проходит `PERIOD_MIN_SHARED_STEMS=2`; на базе — 1 стем («конф»).
Корень подтверждён пробой на обеих ветках (base: shared=1; tip: shared=2).
Правка `250eb0653` — **только фикстура** (1 файл, +4/−1): взят текст ровно с
одним общим стемом («обсуждали на конфе»), порог и assertions
`soft_fallback==0` / `dropped_subject==1` **не менялись**. Это тот же класс
обновления ожиданий, что документированный RC4 апдейт `test_vmq_mem_slice_d`.

## 5. Pre-existing (не относятся к слайсу; не правились)

1. `tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme`
   — README содержит `v2.57.0`, а не 2.58.243; **воспроизведено на базе
   `ff226ca0a`** (тот же failed), README релизом не менялся. `1 failed`.
2. Документированные в 2.58.242 падения `test_graphrag_rebuild_asap32` /
   `test_asap5_graphrag_recovery` (warning coalesce) в этом прогоне **не
   запускались** (файлы дельтой не затронуты); не заявляются как проверенные.

## 6. Приёмка RC1–RC7 по замеру 2026-11-25

| RC | Что принято | Замер (combined 2.58.241+RC1..RC7) | Вердикт |
|---|---|---|---|
| RC1 | legacy reserve перед episode facade; redirect исключён | 200/194 new/legacy 11–16 → **200/188/5–16**; rejected 3/4 нет | **PROVEN** |
| RC2 | explicit-year message rank внутри окна | target **позиция 2**, p50 **123.9 ms**, годы {2025}; service `_build_old_episodes` 1688.1 ms, target + 2 span 2025, `order=rank` | **PROVEN** (RFL-4 закрыт) |
| RC3 | explicit-year period slots + capacity | **12×2025**, out-of-year dropped **11/11**, cap 11, current **12×2026** | **PROVEN** |
| RC4 | short-stem + year-token filter | «шизах» **2→156**, shared≥2 **1→5** (32) / **1→8** (64), принят старый **2024:1**, `2025`/`году` убраны | **PROVEN** |
| RC5a | subject-ref факты не world (producer) | unit **3/3**; 36 423/9 179/9 079; Леха 649/**636**; non-world 13 без роста; `no_rewrite_path=true` | **PROVEN (unit)**; C-data = gap |
| RC6a | persona meta + alias-canon links | facts **7/meta 7**, years {2026:7}, refs 7, tg 6; alias `леха вдовин` — **links 20**; 4/5 (только exact-node) | **PROVEN (C2/E2)**; E = gap |
| RC7 | new-story → canonical anchors | 16 sampled → **6 stories / 8 anchors** (msg 8, tg 0), legacy_links 0; 263 stories/263 links/263 keys | **PROVEN (narrowed B2)**; legacy = gap |

## 7. Три честных gap (не закрываются этим релизом)

1. **RC5a / RC5b C-data** — read-path/backfill существующих персональных
   world-фактов (598/6810 в старом замере) не реализован; RC5a меняет только
   новые строки. Существующие строки не переписываются.
2. **RC6a E1 (E/Диана 2023–2025)** — alias-проба E2 пройдена, exact E1
   отложен; E-сценарий не заявляется.
3. **RC7 RFL-7 legacy anchors** — bridge работает только для новых
   stories/links; legacy 5–16 anchors (14 lore-историй без links) отсутствуют;
   narrowed B2 принят, legacy-часть — gap.

## 8. Rollback

- **Code-only:** `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e` (2.58.242),
  manifest `--effect rollback`.
- **DDL 0, миграций 0, флагов 0**, данные и настройки не мигрируют и не
  откатываются. Схема остаётся v48.

## 9. Manifest dry-run

Чистое дерево `250eb0653`; `.deploy/release.json` (gitignored) временно
содержал production-манифест `ff226ca0a / 2.58.242` для честного `previous`:

```json
{
  "deployed_at": "2026-11-24T14:50:10.567741Z",
  "deployed_sha": "250eb06536f16196e86412a902e1461ffe8871f1",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
  "previous_version": "2.58.242",
  "release_branch": "release/vmq-rc-2.58.243",
  "schema": 1,
  "version": "2.58.243"
}
```

`--dry-run` ничего не записал; seed удалён. Evidence-коммит меняет только
docs; DevOps повторяет manifest на **точном deployed SHA**.

## 10. Post-deploy (агенты; без owner QA)

- `/healthz`/`/api/health` 200, `version=2.58.243`, identity
  `verified_deployed`, schema 48/DDL 0, настройки/промпты не сброшены.
- **Episode windows:** explicit-year запрос → `_build_old_episodes` возвращает
  target-year anchors в окне, `<Old_Episode>` содержит target, порядок `rank`
  (не `time`).
- **Ranking positions:** target сообщение explicit-year в top-8/16 (ожидаемо
  позиция 2), декабрьские сообщения не вытесняют.
- **Year-scoped queries:** explicit-year fact block — только target year
  (out-of-year dropped), «2025:2 + 2026:10» не воспроизводится; current-state
  путь остаётся свежим (2026).
- **Reserve/fallback не тронуты:** дельта не меняет direct reserve/capacity и
  QRNG P5A/P5B; проверить `/api/status.random` reserve/fallback counters и
  отсутствие скрытого PRNG.
- UI не менялся (0 файлов `web/`): served assets 2.58.242 эквивалентны, кроме
  версии.
- 31 focused RC-тест на deployed SHA; `journalctl` без новых ERROR/Traceback;
  disk/retention по штатному пути.
