# SELF-DIAG-01 semantic live run (candidate `76fcb829`)

- provider: `https://nano-gpt.com/api/v1` / `deepseek/deepseek-v4.1-flash`
- series: 2, cases: 9 (4 positive / 5 negative), temperature 0
- fixture commit: `ffd92ead5482bf8f9d1e111fd8e7f501e5ccc647`

| case | kind | user text | reply | needed | target | sources | tool | path | lines | final excerpt |
|---|---|---|---|---|---|---|---|---|---|---|
### Series 1
| case | kind | user text | reply | needed | target | sources | tool | path | lines | final excerpt |
|---|---|---|---|---|---|---|---|---|---|---|
| pos_short | positive | почему бот сегодня молчит после проверки? | false | true | self | runtime,journal,source_code,memory | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_conversational | positive | слушай, он опять тупит, разберись по-быстрому | false | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_typo | positive | почиму он не отвечает на сообщения? | false | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_reply | positive | ну и где там косяк, что в итоге? | true | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_id": null, "response_ |
| neg_similar_words | negative | код с прошлой недели нормально работает, ага | false | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_external | negative | в моём проекте на гитхабе вчера нашли ошибку в парсере, вот весело | false | false |  |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_quoted | negative | Костя писал: «разберись, почему падает», я просто передаю | false | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_ordinary | negative | спасибо, отчёт посмотрел, всё понятно | true | false | self |  | no |  |  | {"action": "react", "reaction": "👍", "delivery": null, "target_message_id": null, "target_user_id": null, "response_act" |
| neg_explain_received | negative | объясни, что в отчёте значит пустой ответ L1 | true | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_id": null, "response_ |

### Series 2
| case | kind | user text | reply | needed | target | sources | tool | path | lines | final excerpt |
|---|---|---|---|---|---|---|---|---|---|---|
| pos_short | positive | почему бот сегодня молчит после проверки? | false | true | self | runtime,journal,source_code,memory | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_conversational | positive | слушай, он опять тупит, разберись по-быстрому | false | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_typo | positive | почиму он не отвечает на сообщения? | false | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| pos_reply | positive | ну и где там косяк, что в итоге? | true | true | self | source_code,journal,runtime | yes | services/checkup_service.py | [150, 175] | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_id": null, "response_ |
| neg_similar_words | negative | код с прошлой недели нормально работает, ага | false | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_external | negative | в моём проекте на гитхабе вчера нашли ошибку в парсере, вот весело | false | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_quoted | negative | Костя писал: «разберись, почему падает», я просто передаю | false | false | unknown |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "chat", "target_message_id": null, "target_user_id": null, "response_a |
| neg_ordinary | negative | спасибо, отчёт посмотрел, всё понятно | true | false | self |  | no |  |  | {"action": "react", "reaction": "👍", "delivery": null, "target_message_id": null, "target_user_id": null, "response_act" |
| neg_explain_received | negative | объясни, что в отчёте значит пустой ответ L1 | true | false | self |  | no |  |  | {"action": "reply", "reaction": null, "delivery": "reply", "target_message_id": null, "target_user_id": null, "response_ |

Flips: [{"case_id": "neg_external", "series_1": [false, null, false], "series_2": [false, "unknown", false]}]
