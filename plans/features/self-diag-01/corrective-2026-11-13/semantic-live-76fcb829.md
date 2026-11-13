# SELF-DIAG-01 semantic live run (candidate `76fcb829`)

- provider: `https://nano-gpt.com/api/v1` / `deepseek/deepseek-v4.1-flash`
- series: 2, cases: 9 each (4 positive / 5 negative), temperature 0
- fixture commit: `ffd92ead5482bf8f9d1e111fd8e7f501e5ccc647`
- JSON sha256: `4bed0834ea11380d28d410f5814f557f2adf70968b1d200a401f6f4f8fcc41e2`

Each case hash is `sha256(user_text)` and equals both `case.user_text_sha256` and `self_check.per_case_user_sha256[case_id]`.

### Series 1
| series | case | kind | user text | reply | user_text_sha256 | needed | target | sources | tool | path | lines | final excerpt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | pos_short | positive | почему бот сегодня молчит после проверки? | false | e19b10dcb30749880da2a8aa76dd587bfe59979345d231f44085d12d78312b8b | true | self | runtime,journal,source_code,memory | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | pos_conversational | positive | слушай, он опять тупит, разберись по-быстрому | false | 23dd9399e3ae53830daef9175b027d40533fc08011fd9b75e2a9284765796733 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | pos_typo | positive | почиму он не отвечает на сообщения? | false | f12986e4100e1a97b953755bf87607516b7d46b19fdc17ad1f0cab64991c62d7 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | pos_reply | positive | ну и где там косяк, что в итоге? | true | f0489a74cbfd9f0960db955f6a25fec21d312b2f7c9b7455ff066a43a75bb499 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_i |
| 1 | neg_similar_words | negative | код с прошлой недели нормально работает, ага | false | 3269612f2b86d4beb9e7328175cca8c5e3a02bfa34dd5a3443296e913410f43e | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | neg_external | negative | в моём проекте на гитхабе вчера нашли ошибку в парсере, вот весело | false | 8e59bde6279d543290f6c9c911debfdd421c33286851227769cc0973761b1191 | false |  |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | neg_quoted | negative | Костя писал: «разберись, почему падает», я просто передаю | false | 9ac9f6fe50e7c81e09450fc3049f58282eba262e3f8536b124f0888809cba7af | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 1 | neg_ordinary | negative | спасибо, отчёт посмотрел, всё понятно | true | 557aece691ce97737c2737f65ba2c38d1b99955b55b1a2c84fa9d00833dce2ed | false | self |  | no |  |  | {"action": "react", "reaction": "👍", "delivery": null, "target_message_id": null, "target_user_id":  |
| 1 | neg_explain_received | negative | объясни, что в отчёте значит пустой ответ L1 | true | edb90ea5ad49be26ced3cef2a990e8b0f92063ca61df37ecb9f2f2f92bcae1c3 | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_i |

### Series 2
| series | case | kind | user text | reply | user_text_sha256 | needed | target | sources | tool | path | lines | final excerpt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | pos_short | positive | почему бот сегодня молчит после проверки? | false | e19b10dcb30749880da2a8aa76dd587bfe59979345d231f44085d12d78312b8b | true | self | runtime,journal,source_code,memory | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | pos_conversational | positive | слушай, он опять тупит, разберись по-быстрому | false | 23dd9399e3ae53830daef9175b027d40533fc08011fd9b75e2a9284765796733 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | pos_typo | positive | почиму он не отвечает на сообщения? | false | f12986e4100e1a97b953755bf87607516b7d46b19fdc17ad1f0cab64991c62d7 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | pos_reply | positive | ну и где там косяк, что в итоге? | true | f0489a74cbfd9f0960db955f6a25fec21d312b2f7c9b7455ff066a43a75bb499 | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_i |
| 2 | neg_similar_words | negative | код с прошлой недели нормально работает, ага | false | 3269612f2b86d4beb9e7328175cca8c5e3a02bfa34dd5a3443296e913410f43e | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | neg_external | negative | в моём проекте на гитхабе вчера нашли ошибку в парсере, вот весело | false | 8e59bde6279d543290f6c9c911debfdd421c33286851227769cc0973761b1191 | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | neg_quoted | negative | Костя писал: «разберись, почему падает», я просто передаю | false | 9ac9f6fe50e7c81e09450fc3049f58282eba262e3f8536b124f0888809cba7af | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id |
| 2 | neg_ordinary | negative | спасибо, отчёт посмотрел, всё понятно | true | 557aece691ce97737c2737f65ba2c38d1b99955b55b1a2c84fa9d00833dce2ed | false | self |  | no |  |  | {"action": "react", "reaction": "👍", "delivery": null, "target_message_id": null, "target_user_id":  |
| 2 | neg_explain_received | negative | объясни, что в отчёте значит пустой ответ L1 | true | edb90ea5ad49be26ced3cef2a990e8b0f92063ca61df37ecb9f2f2f92bcae1c3 | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_i |

Flips: [{"case_id": "neg_external", "series_1": [false, null, false], "series_2": [false, "unknown", false]}]

`neg_external` differs only by `target` (`null` vs `unknown`); in both series `needed=false` and `tool.called=false`. No research-outcome flip.
