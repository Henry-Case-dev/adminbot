# Немедленное удаление тестовых сообщений — протокол для будущих прогонов

Проблема ACCEPTANCE-97: harness отправлял сообщения волнами и писал cleanup-spec
после каждого send, но удаление выполнялось только runner-ом **в конце** прогона
(20:19:39Z, спустя ~5.5 минут). Владелец видел тестовый мусор всё это время.

## Правило

После каждого проверенного хода/волны удалять **и prompt, и ответ(ы) бота**, как
только evidence (text/sha/mid) сохранён. End-of-run cleanup остаётся страховкой,
но не основным механизмом.

## Минимальная схема для harness

```python
# после do_turn(...) и сохранения turn в wave_rec:
mids = [anchor.message_id] + [s["message_id"] for s in turn["sends"]
                              if s.get("message_id")]
spec = {"chat_id": chat_id, "mids": mids,
        "bot_id": 8802473181, "synth_user": 990002001}
write_json("/tmp/accept97/check-now.json", spec)
subprocess.run(["/var/www/admin_bot/venv/bin/python",
                "/tmp/cleanup_now.py",
                "--spec", "/tmp/accept97/check-now.json",
                "--register", "/tmp/accept97/evidence/cleanup-now.json"],
               check=False)
```

`cleanup_now.py` (в этой папке) удаляет через Bot API и чистит синтетические
строки `smart_messages`/`bot_replies`/`bot_reply_parents`. Safety-gate: удаляется
только bot-ответ, у которого parent — bot/synth-сообщение; ответ реальному
пользователю пропускается.

## Обязательное изменение цепочки reply

Сейчас каждый следующий ход отвечает на **предыдущий ответ бота**. Если удалить
его сразу, `reply_to` станет недействительным. Поэтому в новой версии harness:

1. каждый ход отправляет новый prompt и отвечает на **этот prompt** (или на
   стабильный anchor, который не удаляется до конца волны);
2. после проверки удаляются prompt и ответ текущего хода;
3. `last_msg` больше не используется как reply-anchor для следующего хода.

Без пункта 1 немедленное удаление сломает цепочку и даст ошибки Telegram.

## Watchdog (опция)

Пока harness работает, раз в 30 с удалять из `SENT` всё, что старше 60 с и уже
попало в evidence. Это защищает от «зависших» сообщений при падении хода.
End-of-run spec-cleanup всё равно обязателен.

## Проверка

После каждого удаления helper пишет register и возвращает rc!=0 при residual.
Перед `RC=0` harness обязан проверить: spec-mid residual = 0, synthetic rows = 0.
