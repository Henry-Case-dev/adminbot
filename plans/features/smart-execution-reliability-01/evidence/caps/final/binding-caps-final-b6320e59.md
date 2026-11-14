# SMART-EXECUTION-RELIABILITY-01 · финальная зачистка трёх caps — binding evidence

Финальный корректирующий слайс после независимого ре-аудита объединённого
train `8277d33c`: оставались ровно три искусственных ограничителя.
Изменения точечные, вне трёх мест поведение не менялось.

* База: `8277d33c2712a51962181c87b1e0288f4d067c77`.
* Ветка: `smart/caps-final`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-40cb482f`.
* Кодовые коммиты (candidate): `9b64f2c3` (FIX 1), `670b3329` (FIX 2),
  `b6320e59` (FIX 3) — итоговый CODE_SHA: **`b6320e59`**.
* Docs-коммит с этим файлом идёт поверх и ничего не меняет в коде; Reviewer
  проверяет CODE_SHA `b6320e59` (docs-дельту не считать кодом).
* Дельта: 3 файла `services/`/`handlers/`, 3 файла `tests/` (192+/23-).

## 1. Три исправления

| # | Было (file:line базы) | Стало | Почему это кап, а не окно |
|---|---|---|---|
| 1 | `services/mca_retrieval_context.py:431,1317,2045,2078,2207,2226,2264,2429,2489`: `_PREVIEW_MAX_CHARS=400` + `_truncate_preview()` рвали `RetrievalCandidate.preview` для ВСЕХ каналов | `_truncate_preview` удалён; все семь конструкторов кладут полный текст (`str(... or "")`, строки 2044/2077/2206/2225/2263/2428/2488). Константа `_PREVIEW_MAX_CHARS=400` оставлена как **UI-сниппет** `memory_contracts.preview_max_chars()`/`memory_search` (другой потребитель, не данные retrieval) — см. §4 | Фрагмент — не страница и не top-K. `get_user_context` читает `cand.preview` (`tool_router._memory_lookup_candidate_message_item`, `dig` expansion), поэтому память получала первые 400 символов без пометки об усечении |
| 2 | `services/tool_router.py:4815-4818`: `claim_truncated = len(reply_text) > 300; claim = reply_text[:300]` перед `tf.build_envelope` | `claim = reply_text` (полный тезис; строка 4818). `claim_truncated` больше не про фактчек: он отражает только бюджет отображения поля `claim` в ответе (`len(claim_text) > 400`, строка 4971) | Семантическая выборка (референтный вопрос → тезис из replied-сообщения) сохранена; срез 300 менял предмет проверки (проверялась обрезанная фраза) |
| 3 | `handlers/youtube.py:226,1296`: `_YT_TRANSCRIPT_CAP = 20000` → `fetch_transcript(video_id, 20000, ...)` | Константа удалена; `fetch_transcript(video_id, on_retry=None)` (строка 1296) = `max_symbols=None` → полный транскрипт. Telegram-чанкинг прежний: `_send_transcript_reply` → `split_transcript_first` + `send_chunked_reply` (4096) | 20000 — символьный вход в обработку, не лимит Telegram (4096 на сообщение). Доставка уже чанкуется, поэтому входной срез только терял хвост субтитров |

Явные (легитимные) лимиты сохранены: Telegram 4096-чанки, `max_symbols`
движка как ЯВНЫЙ параметр вызывающего (`None/0` = весь текст),
`max_items`/top-K выборка памяти, provider/transport/timeout/rate-limit,
`_REFERENTIAL_CLAIM_MAX_CHARS=80` (порог референтности вопроса, не тезис).

## 2. Тесты (что именно утверждают)

Новые durable-тесты (в существующих caps-файлах, без нового harness):

* `tests/test_caps_tool_results.py::test_user_context_message_fragment_over_400_not_sliced`
  — `get_user_context(purpose="speech_style")` через единый retrieval
  (`recent`-канал, реальный `retrieve`): фрагмент 930 символов приходит в
  `facts[].text` целиком, хвост `КОНЕЦ-ПЕРВОГО` присутствует.
* `tests/test_caps_tool_results.py::test_user_context_many_long_fragments_all_intact`
  — три фрагмента >400 символов: в payload все три дословно, `len(raw) > 1200`,
  все хвосты `ХВОСТ-1..3` на месте.
* `tests/test_caps_tool_results.py::test_youtube_transcript_handler_no_20000_cap`
  — реальный `_process_youtube_transcript` с провайдер-двойником, который
  уважает переданный лимит (как движок): 25k+ символов, вызов движка
  `("vid-sxr", None)`, доставка через настоящий `send_chunked_reply` >3 чанков,
  хвост за 20000 и все контрольные фразы доставлены, потерь нет.
* `tests/test_factcheck_tool_route_cfg06.py::test_reply_claim_over_300_reaches_factcheck_intact`
  — референтный вопрос «бот, это правда?» при replied-тексте >900 символов:
  `InputRef.claim_text` и `envelope.claim_text` равны полному тексту,
  хвост после 300-го символа доходит до `FactCheckService`, `status="ready"`,
  `claim_anchor_tg_message_id` = replied-сообщение.
* `tests/test_video_router.py::TestYoutubeTranscriptMode::test_subtitles_text_sent_html`
  — обновлён под контракт: ожидание `fetch_transcript(YT_ID, on_retry=None)`
  вместо `(YT_ID, 20000, ...)` (прежний тест закреплял удаляемый кап;
  поведение доставки HTML/памяти в нём проверяется по-прежнему).

## 3. RED / mutation proof (каждый кап возвращён → тест красный → восстановлено)

| Cap возвращён | Команда | Результат | Лог |
|---|---|---|---|
| `preview=...[:400]` в `_message_candidate` | `pytest tests/test_caps_tool_results.py -k "fragment_over_400 or many_long_fragments"` | **2 failed** | `raw/mutation-red-preview-400.txt` |
| `claim = reply_text[:300]` | `pytest tests/test_factcheck_tool_route_cfg06.py -k reply_claim_over_300` | **1 failed** | `raw/mutation-red-claim-300.txt` |
| `fetch_transcript(video_id, 20000, ...)` | `pytest tests/test_caps_tool_results.py -k youtube_transcript_handler` | **1 failed** (`[('vid-sxr', 20000)] != [('vid-sxr', None)]`) | `raw/mutation-red-yt-20000.txt` |

После каждого прогона кап снят, `git status` — только untracked evidence-каталог
(исходники идентичны `b6320e59`).

## 4. Прогоны (venv `C:\Code\Python\adminbot\.venv`)

| Набор | Итог | Лог |
|---|---|---|
| `test_caps_tool_results.py` + `test_caps_context.py` + `test_factcheck_tool_route_cfg06.py` + `test_video_router.py` | **80 passed** | `raw/pytest-caps-final.txt` |
| 27 затронутых файлов: caps, mca07/15/22/23, memory contracts/lookup/unified/communities, vmq-mem, smart_exec_evidence, factcheck cfg06/cfg07, reply-context, youtube/video/transcribe/unified-core | **940 passed, 1 failed** | `raw/affected-final.txt` |

`git diff --check 8277d33c HEAD -- services handlers tools tests` — **пусто**
(exit 0, политика `.gitattributes` `* whitespace=cr-at-eol` уже в репозитории);
`git diff -w` побайтно совпадает с обычным diff (whitespace-only изменений нет):
`raw/git-diff-check.txt`, `raw/git-diff-stat.txt`.

## 5. Остаточные риски / pre-existing (не от этого кандидата)

1. `raw/affected-final.txt`: `test_mca23_planned_vs_actual::test_routes_pin_untouched`
   — byte-freeze `web/api/routes.py` не совпадает. Файл не входит в дельту
   кандидата (`git diff 8277d33c HEAD -- web/` пуст); тот же провал
   зафиксирован в предыдущем evidence `caps/tool-results` §4 как pre-existing.
2. `test_mca20_rework1_f1_f2::test_evidence_injection_stays_data_not_instructions`
   — воспроизведён на чистой базе `8277d33c` в отдельном detached worktree:
   падает идентично (экранирование evidence). Pre-existing, вне scope; worktree
   удалён (`git worktree remove`, без force).
3. `test_youtube_multimodal_download_round1024.py` — 18 fixture-errors
   (`handlers.youtube` без `get_smart_cache`), атрибут отсутствует и на базе
   `8277d33c`; не связано с пачкой.
4. `_PREVIEW_MAX_CHARS=400` остаётся, но только как UI-сниппет поиска памяти
   (`memory_contracts.preview_max_chars`, `memory_search`), не как кап данных
   retrieval. Это осознанное разделение: UI-сниппет — отображение, память/инструмент
   получает полный фрагмент.
5. Поле ответа `claim` в `fact_check` по-прежнему отдаётся с бюджетом отображения
   400 (и `claim_truncated` теперь честно описывает именно его); проверенный
   тезис (`envelope.claim_text`) — полный. `excerpt[:300]`, `verdict_text[:2000]`
   — поля ответа инструмента, не входили в три назначенных капа и не менялись.
6. Post-deploy проверка effective config не требуется: флагов/настроек эти три
   места не читают (константы удалены, ветвление по env отсутствует).

## 6. Housekeeping

* Одноразовый `WorkspaceData/runs/.../temp-3a239f6ba2` (скрипт правки докстринга)
  закрыт `run-close --apply` после переноса результата в коммит.
* Worktree `...-40cb482f` сохранён для Reviewer/деплоя; в master/train не мержится.
