# Raw read-only extract — chat -1002661910336, 2026-11-06 (UTC)

Источник: прод `/var/www/admin_bot/local_database.db`, `mode=ro&query_only=1`, ревизия `2.58.161` @ `a563ee31`.
Оставлены только строки, нужные для цепочки кейса. Тексты сокращены до смыслового фрагмента;
посторонняя переписка не выгружалась. Секретов, токенов, путей к кредам в выборке нет.

## A. smart_messages (окно темы)

```
1201549 16:04:36 Вася    photo  "зацените хуйню построил"
1201550 16:06:51 Даня    text   "Хуйня 👍"                    reply_to=1201549
1201552 16:07:14 Даня    text   "Так ты хуйню и строил"
1201553 16:07:55 Папаха  photo  -                             reply_to=1201549
1201554 16:08:21 Вася    voice  "15 на 15 на 15, и там чистое." reply_to=1201553
1201650 16:27:43 Папаха  text   "построил говоришь"           reply_to=1201549
1201651 16:28:22 Папаха  video  -
1201652 16:28:53 Папаха  text   "бля сшакалилось"
1201653 16:28:54 Папаха  text   "https://youtube.com/shorts/Jl-KVNhnMjo?si=..."   (Shorts, lowkiMC)
1201661 16:44:31 Вася    text   "а не вордедит ли ты часом"   reply_to=1201651
1201662 16:45:25 Папаха  text   "да тоже подумал хули он ебался если в вордедите можно ctrl+c Ctrl+v делать" reply_to=1201661
1201663 16:45:38 Папаха  text   "возможно... ФЕЙК"             <-- TARGET
1201664 16:45:46 Вася    text   "фактчек"                      <-- TRIGGER, reply_to=1201663
1201666 16:46:05 Вася    text   "окак"
```

`1201665` в `smart_messages` отсутствует (удалено/не доставлено).

## B. mca_events (16:45:46–16:45:49)

```
id 206455  16:45:46  factcheck_target     factcheck.target    success
  entity_ids = {"target_source":"explicit_reply","target_kind":"unresolved",
   "target_tg_message_id":1201663,"claim_origin":"target_text",
   "text_claim_resolved":false,"media_expected":true,
   "media_dependency_source":"adjacent_media_candidate","association_attempted":true,
   "association_status":"ambiguous","association_reason":"adjacent_before",
   "association_candidates":2,"linked_media_ids":[],"media_notice_emitted":true,
   "media_notice_reason":"ambiguous_no_text_claim","route":"orchestrator_v2",
   "trigger_tg_message_id":1201664,"delivery_reply_to":1201663,"contextual_target":false}

id 206456  16:45:49  factcheck_temporal   stage=deliver  outcome=skipped
  reason_code = null          <-- код передаёт "ambiguous_needs_clarification",
                                  значение обнулено whitelist'ом REASON_CODES
  pipeline_type = temporal.factcheck, pipeline_version = tf3

id 206457  16:45:49  factcheck_admission  stage=v2_gate:ambiguous  success
  entity_ids = {"target_resolved":true,"explicit_request":true,"claim_items_count":0,
   "admission_decision":"ambiguous_target","reason_code":"multiple_dispute_candidates",
   "pipeline_path":"v2_gate:ambiguous","verdict_stage":"","cooldown_outcome":"refund:ambiguous"}

id 206458  16:45:49  factcheck_cooldown
  entity_ids = {"cooldown_outcome":"refund:ambiguous","run_outcome":"ambiguous"}
```

## C. Отсутствующие записи (важно)

```
select … from mca_factcheck_runs where trigger_tg_message_id = 1201664
  -> 0 rows            (Analyst/Verbalizer не запускались, вердикта нет)

select … from mca_bot_outputs where chat_id=-1002661910336
  and sent_at between 1793983500 and 1793983720
  -> 0 rows            (текст короткой реплики не персистится)

select … from bot_replies … (то же окно) -> 0 rows
select … from smart_messages where author_name like '%PERM%' … (то же окно) -> 0 rows
```

## D. Дискриминация по остальным триггерам

Триггеры «фактчек» с 2026-10-29 в чате `-1002661910336` / `-1004482340693`:
`1184677, 1186270, 1186794, 8233, 8287, 1191050, 1191144, 1194078, 1194108, 1197782, 1201664, 1201759`.
Для всех, кроме `1201664`, существует строка `mca_factcheck_runs` (обычный вердикт-путь).
`1201664` — единственный с `pipeline_path = v2_gate:ambiguous` и без прогона.

## E. Внешняя проверка публикации

YouTube oEmbed (публичный HTTP, без прод-доступа):
`https://www.youtube.com/oembed?url=https://www.youtube.com/shorts/Jl-KVNhnMjo&format=json`
→ `{"title": "This feels like a scene from interstellar 🥹", "author_name": "lowkiMC", …}`.
