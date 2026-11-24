# VMQ-MEM-RC7 (B2 narrowed) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED. `VMQ-MEM-02/03/04`
остаются REVIEW. RC7 — read-path only; legacy 5–16 mapping остаётся RFL-7.

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `2982fd7dc860cc4966549996168c16b10924ae21` (RC6a approved) |
| Branch | `fix/vmq-mem-rc7` |
| Contract | `08851280e` — `corrective-contract-2026-11-23.md` |
| Product files | `services/direct_chat_service.py`, `services/mca_episodes.py` |
| Test | `tests/test_vmq_mem_rc7_story_bridge.py` |
| Probe | `evidence/vmq-mem/rc7/rc7_probe.py` + `rc7-snapshot.json` |
| Test log | `evidence/vmq-mem/rc7/tests.txt`, RED — `red.txt` |
| Diff | `evidence/vmq-mem/rc7/candidate.diff` |

Не менялись: DDL/migrations, `mca_story_legacy_links`, legacy 5–16 mapping,
`lore_stories`, RC1 facade (`list_stories_for_retrieval` read-contract),
E1/subject-threshold, ACL/UI/embedding/store/quotas, map/status,
`progress_scope.json`/`workflow_state.md`.

## 2. Bridge (narrowed)

`services/mca_episodes.story_message_anchors(db, chat_id, story_ids,
per_story=2, limit=8)`:

- читает ТОЛЬКО существующие `mca_story_episode_links` →
  `mca_episodes.message_keys_json` (join по `episode_id`, chat scope);
- каждый ключ `chat:tg:<id>`/`chat:db:<id>` валидируется по
  `smart_messages` (`_message_exists`); несуществующая строка не становится
  якорем;
- возвращает канонические `tg:<id>`/`msg:<id>`; per-story и общий лимит
  ограничены; отсутствие links/keys → `{}`.
- Read-only, `db.db.execute`, без DDL/backfill/mapping.

`DirectChatService._build_old_episodes`:

- основной retrieval по-прежнему `channels=("exact","lexical")` (TIME-03):
  порядок/состав `result.candidates` НЕ меняется;
- если в результате есть episode-кандидаты — используются они, иначе
  отдельная bounded-нога через существующий `_mca_rc._episode_candidates`
  (тот же mca-05 read-contract/фасад, второй движок не создаётся);
- найденные story→message якоря входят в существующий `_add_anchor`/
  `_episode_anchor_of_ref` как `entity_type="episode"`, priority=1,
  и далее идут прежним путём `get_messages_around`/`compute_episode_span`;
- `stats["story_anchor_candidates"]` — число историй с якорями;
- ошибка чтения моста → warning + пусто (fail-open, без выдумки).

## 3. RED / GREEN

RED (снята только обвязка `direct_chat_service.py`; helper присутствует):

```
1 failed, 4 passed
test_story_bridge_returns_message_anchors
assert ''.startswith('<Old_Episode>')   # пул: 0 message/graph_fact
```

GREEN: focused `5 passed`.

Покрытие теста:

1. story с links/keys → `tg:201`,`tg:202`; `<Old_Episode>` содержит тексты
   строк, которых нет в exact/lexical (единственный путь — мост);
2. ключ на несуществующее сообщение отбрасывается, живой остаётся;
3. story без keys и story без links → `{}`; блок пуст, `count=0`;
4. legacy `lore_stories` (RFL-7) → пусто; `mca_story_legacy_links` = 0,
   новый mapping не создан;
5. фасад возвращает новый story; `PERIOD_MIN_SHARED_STEMS == 2` (E1 не
   менялся).

## 4. Snapshot read-only

`snapshot-2.58.225.db`, `mode=ro&immutable=1`, SHA-256 до/после совпадает
(`b907…06e7`):

| Метрика | Значение |
|---|---:|
| stories (chat) | 212 |
| episode links (chat) | 212 |
| episodes with keys | 212 |
| legacy links | 0 |
| sample stories | 16 |
| stories with anchors | 5 |
| anchors total | 8 |
| `tg` / `msg` anchors | 0 / 8 |
| per-story max | 2 |
| absent story anchors | false |
| snapshot unchanged | true |

## 5. Tests / checks

```
python -m pytest -q --disable-warnings <affected set>
681 passed, 1 warning
pytest_exit=0
```

Затронутый набор: RC7, mca-05/12/asap8 stories, mca-07 retrieval,
memory-unified retrieval, mem-time policy/natural, history isolation,
context composer/policy, UR context/inspector, VMQ retrieval fixes,
RC2/RC3/RC4/RC5a/RC6a, direct chat, evidence grounds, mca16.

`tests/test_nostalgia_w2.py` даёт те же 4 падения
(`provider_reserve: no active connection`, `sent == 0`) на базах
`4828f30a9` (RC5a) и `2982fd7dc` (RC6a) — pre-existing и не связаны с RC7,
поэтому исключены из затронутого набора; RC7 их не меняет.

`py_compile` — exit 0; `git diff --check` — exit 0; snapshot probe — exit 0.

## 6. Remaining / RFL

- Legacy 5–16 mapping/message-refs — RFL-7: не воссоздаётся; пустой мост
  остаётся пустым.
- Нет новых store/DDL/backfill; существующие story/links/keys только читаются.
- E1 subject-threshold не менялся; current-state/facade пути не затронуты.
- `VMQ-MEM-02/03/04` остаются REVIEW; VERIFIED не заявлен.
- Нет deploy/SSH/LLM; map/status/progress/workflow не менялись.

## 7. Hygiene

`red.txt`/`tests.txt` — UTF-8 без BOM, trailing whitespace вычищен.
JSON-проба содержит только счётчики/типы якорей, без текстов сообщений.
