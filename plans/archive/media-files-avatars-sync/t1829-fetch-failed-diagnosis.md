# T-1829 — разбор `fetch failed` для пользователя `525660918` (artifact)

> **D-2.7 (ревью итерации 4):** ранее формулировка «разобрать `fetch failed`»
> в `tasks.md` не имела приложенного артефакта разбора. Ниже — диагностика,
> привязанная к коду и тестам, без секретов (R17).

## 1. Симптом (чекап UPD2 п.6)

```
[avatar] fetch failed | kind=user tid=525660918
```

— аватар пользователя не отдавался TMA-прокси `GET /api/avatar/user/525660918`
(фронт показывал пустую заглушку через `onerror`).

## 2. Корневая причина

`web/api/avatars.py::fetch_avatar_bytes` (до F6) разрешал `file_id` через
`bot.get_user_profile_photos(tid, limit=1)`, затем скачивал файл
`bot.get_file(file_id)` → `bot.download_file(path, …)`. В режиме **локального
Bot API** `file_path` относительный, а файл лежит на диске под
`TELEGRAM_API_FILES_DIR/<bot_id>:<token>/photos/…`; облачный `download_file`
для такого пути падал (`TelegramBadRequest`/сеть) → `fetch failed`, а негатив
кэшировался на час (повторно не восстанавливался).

Разбор по коду:

* `web/api/avatars.py:111-120` — `_avatar_file_id` (фото есть/нет);
* `web/api/avatars.py:137-152` — путь: `read_local_file_bytes` → fallback
  `get_file`/`download_file`;
* `services/media_download.py::read_local_file_bytes` — 3 ретрая чтения
  локального файла (тот же хелпер, что и у медиа).

## 3. Фикс (F6, ADR-1019-5 D2/D6)

1. Для относительного `file_path` сначала читается **локальный** файл
   (`read_local_file_bytes`), и только при его отсутствии — прежний
   `bot.download_file` (`avatars.py:139-152`).
2. Транзиентные ошибки (`TelegramRetryAfter`/`TelegramNetworkError`) **не**
   кэшируются — следующий запрос (ленивый догруз/ре-рендер) попробует снова
   (`avatars.py:153-159`, BUG-4).
3. Дефинитивные негативы (нет фото/прав/чата) кэшируются как `None`, чтобы
   фронт с `onerror` не долбил Bot API (`avatars.py:160-171`).

## 4. Доказательство

* `tests/test_avatars_round1019.py::test_local_fallback_reads_disk` — файл
  пользователя `525660918` (`photos/file_1.jpg`) читается с диска;
  `bot.download_file` НЕ вызывается.
* `tests/test_avatars_round1019.py::test_missing_local_falls_back_to_download` —
  при отсутствии локального файла работает облачный путь.
* `tests/test_avatars_round1019.py::test_transient_not_cached` — негатив при
  сетевом сбое не пишется в кэш.
* `tests/test_avatars_round1019.py::test_r17_secret_absent_from_logs` — строка
  `<bot_id>:<token>` не попадает в логи.

## 5. Остаточное ограничение (обоснование)

Если файла нет ни на диске, ни в Bot API (фото удалено/приватность), аватар
не восстанавливается — это корректный 404 (не регресс). Отдельного
`path→file_id`-маппинга в схеме нет, поэтому автоматическое
«восстановление» (T-1828-производное) вынесено в backlog.
