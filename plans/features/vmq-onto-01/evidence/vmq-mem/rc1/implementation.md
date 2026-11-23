# VMQ-MEM-RC1 (B1) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED и не product-code
approval. VMQ-MEM-02/03/04 остаются REVIEW. Продуктовый код вне RC1, DDL, ACL/UI,
embeddings, deploy, SSH, Telegram, LLM и `progress_scope.json`/`workflow_state.md`
не менялись.

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `b81ec52aa4834896c8e901269e69058612ae81bf` (2.58.238) |
| Branch | `fix/vmq-mem-rc1-facade` |
| Worktree | `WorkspaceData/worktrees/.../vmq-mem-rc1-a13843763f4d-daea29ec` (from base, clean start) |
| Contract | `08851280e` — `evidence/vmq-mem/corrective-contract-2026-11-23.md`, RC1 |
| Product file | `services/mca_episodes.py :: list_stories_for_retrieval` only |
| Test | `tests/test_vmq_mem_rc1_episode_facade.py` |
| Probe | `evidence/vmq-mem/rc1/snapshot_probe.py` + `snapshot-before-after.json` |
| Diff | `evidence/vmq-mem/rc1/candidate.diff` |
| Test log | `evidence/vmq-mem/rc1/tests.txt` |
| RED log | `evidence/vmq-mem/rc1/red.txt` (RC1-R1-01 before fix) |

Изменение — только facade-пул: active legacy резервируется **до**
`updated_at`-среза; новые истории занимают оставшуюся ёмкость; `limit`
остаётся жёстким верхним пределом. Фильтры (`excluded_from_retrieval`,
`verification='rejected'`, redirect, mapped legacy) и scoring
`_episode_candidates` не менялись. Facade OFF (`MCA_EPISODES_COMPILER_FACADE_ENABLED=False`)
по-прежнему идёт через `list_lore_stories` и RC1 не затрагивает.

Алгоритм:

1. Прочитать до `limit` active legacy (`LORE_STORIES_RETRIEVAL_PREDICATE`,
   `chat_id`, `COALESCE(mapping_status,'unmapped') != 'mapped'`,
   `NOT EXISTS` redirect по `old_id`, `ORDER BY updated_at DESC, id DESC`).
   Redirect исключается **в SQL до LIMIT**, иначе redirect-источник
   занимает слот и следующая active legacy теряется.
2. Если active legacy ≥ `limit` — вернуть самые новые legacy, новые не читать.
3. Иначе прочитать новые `repo.list_stories(limit=limit)`, применить прежние
   фильтры/redirect, удалить id-дубли с legacy.
4. Взять `limit - len(legacy)` новых, объединить с legacy, отсортировать
   `updated_at DESC` с детерминированным tie-break `id ASC`, вернуть `limit`.

## 2. Snapshot probe (read-only)

Snapshot: `snapshot-2.58.225.db`, SHA-256 проверен заново:
`b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7`,
4 721 844 224 B. Открытие: `file:...?mode=ro&immutable=1` +
`PRAGMA query_only=ON`; записей нет.

| Метрика | Before (base algorithm) | After (RC1) |
|---|---:|---:|
| total | 200 | 200 |
| new stories | 192 | 188 |
| legacy IDs | `{9,10,11,12,13,14,15,16}` | `{5,6,7,8,9,10,11,12,13,14,15,16}` |
| legacy 5–8 | отсутствуют | присутствуют |
| rejected 3/4 | отсутствуют | отсутствуют |

`pass`: `before_dropped_5_8=true`, `after_all_5_16=true`,
`rejected_absent=true`, `total_200=true`.

Это facade-срез, **не** episode-канал: downstream `_episode_candidates`
(top_k/scoring) не менялся, поэтому историческая метрика 3/14 может
сохраняться. RC1 чинит пул, не top_k и не production `<Old_Episode>` (для
этого нужен RC7).

### 2.1. RC1-R1-01 corrective (redirect capacity edge)

Reviewer blocker: legacy-запрос делал `LIMIT limit` **до** redirect-фильтра.
Если active legacy > `limit` и redirect-источник новее active legacy, redirect
занимал слот; после post-filter оставалось `limit-1` legacy, код добирал
новую историю и терял следующую active legacy.

- **Repro:** 205 active legacy `1000..1204`; ID 1000 — redirect-источник с
  `updated_at=5000` (новее остальных); 50 new; `limit=200`.
- **Before:** 199 legacy `1006..1204` + 1 new; missing `1005`.
- **After:** 200 legacy `1005..1204`; new = 0.
- **Fix:** `NOT EXISTS (SELECT 1 FROM mca_story_redirects r WHERE
  r.old_kind='story' AND r.old_id=CAST(l.id AS TEXT))` в legacy SQL **до**
  `ORDER BY/LIMIT`; post-filter оставлен как defensive no-op.
- RED/GREEN: `red.txt` — падение на старом SQL; после fix focused 10/10.
- Дополнительно: id-dupe тест — новый story id, совпадающий с legacy id,
  не дублируется; legacy имеет приоритет.

## 3. Tests

Focused:

```
python -m pytest -q tests/test_vmq_mem_rc1_episode_facade.py
10 passed
```

Affected:

```
python -m pytest -q \
  tests/test_vmq_mem_rc1_episode_facade.py \
  tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mca07_retrieval_context_round1027.py \
  tests/test_p0_old_lore_quarantine.py \
  tests/test_vmq_m1_episode_contract.py
162 passed
```

Focused coverage: before-cut reproduction `{9..16}` / dropped `{5..8}`;
after all active `{5..16}`; rejected 3/4 absent; total 200; new 188;
repo-honors-limit 200; mapped legacy excluded; excluded legacy excluded;
redirected legacy and new stories excluded; `>limit + redirect` keeps
`1005..1204` with new 0; id-dupe legacy wins; legacy > limit returns newest
legacy only; no-new-stories returns legacy; deterministic ordering.

`py_compile` — exit 0. `git diff --check` — exit 0. Snapshot probe — exit 0.

## 4. Remaining / RFL

- **RC1 не закрывает B row.** Production `<Old_Episode>` по-прежнему не
  использует episode-канал; legacy 5–16 не имеют message-refs. Это RC7 /
  RFL-7, не RC1.
- **3/14 не переоценивается.** Facade теперь отдаёт все 12 active legacy,
  но `_episode_candidates` top_k/scoring не менялся; нужен downstream
  замер/Reviewer.
- **RFL-1/RFL-2/RFL-3:** vector leg, L1/Writer и snapshot 2.58.225 vs
  deployed 2.58.238 остаются ограничениями; RC1 — pool-level acceptance,
  не полная сертификация памяти.
- **RFL-6:** facade исполнен на fixture и snapshot, не только SQL-симуляция.
- **RFL-8:** latency rank-плана не относится к RC1; не измерялась.
- Независимый Reviewer должен проверить diff, тесты и negative controls;
  PM может привязать RC1 как инкремент. VERIFIED не заявляется.

## 5. Hygiene

- Временные probe-скрипты/логи вне evidence удалены; в evidence остаются
  только воспроизводимый `snapshot_probe.py`, JSON, test log и diff.
- Секретов, текстов историй и production-доступа в evidence нет.
- `progress_scope.json`, `workflow_state.md`, requirements map, plan и
  backlog не изменялись.

Candidate SHA: HEAD ветки `fix/vmq-mem-rc1-facade` на момент handoff;
product diff — `candidate.diff` против `b81ec52aa`.
