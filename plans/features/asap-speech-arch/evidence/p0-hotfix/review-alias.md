# REVIEW-ALIAS-RUNTIME — независимая проверка алиасов (P0 corrective §2.1–§2.3)

- **Кандидат:** `f42e2257fb81f887c96f18ddb89161dd4d0c162b` (`task/speech-p0-hotfix`), родитель `52061e3f`.
- **База алиасного среза:** `d1a44592` (родитель `272170e3`); прод-база `534ac7dd` (2.58.130).
- **Worktree:** `C:\Code\Python\adminbot-wt-alias-rev` (detached, чистый; после прогонов восстановлен тестовый сайд-эффект `plans/features/cfg/evidence/cfg-06/w7-dispute-metrics.json`).
- **Источник требований:** `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md` §2.1–§2.3 (файл есть в `master`, в этой ветке отсутствует — читался из `C:\Code\Python\adminbot`).
- **Аудит/предложения:** `evidence/p0-hotfix/alias-audit.md` (D1–D8, F1–F7, 11 проверок §6).
- **Границы:** только локальный код/тесты/БД pytest; без SSH/прода/Telegram/LLM-вызовов. Прод-payload в этом лейне не запускался.

## 1. Вердикт

**Approved — для alias/identity-скоупа §2.1–§2.3.** Блокирующих дефектов по 11 обязательным проверкам не найдено;
все проверки подтверждены кодом + независимыми прогонами. Родительский DONE этим не заявляется (см. §8: карта требований §2
и полный suite — вне этого лейна).

## 2. Какой коммит что несёт (сверено по `git show --stat` / `git diff`)

| Коммит | Что содержит |
|---|---|
| `d1a44592` | **Весь runtime-фикс:** F1 (`_l1_reply_block` → инстанс-метод + alias по uid + `[user:id]`), F2 (Observer `_row_author` + optional resolver, eval/digest), F3 (`bind_turn_aliases` в lore/dream/relations/observer), F4 (строка-инструкция в `<UserResolutionMap>`), F5 (`protected_facts.subject_ref_id`, чтение/clear/forget по uid), F6 (docstring `memory_name`), **D7** (`_turn_usernames`, username в `_collision_suffix`), миграция БД, правки тестов-стабов. |
| `f42e2257` | **F7** (`summary_aliases.scope_report["by_uid"]` + R17-safe `_alias_diagnostics_payload` в существующем `/direct/context-diagnostics`), новые тесты a17–a25/f5×3/f7 + dossier-guard, удаление дубля `tests/test_p0_alias_runtime_2026_10_25.py`, re-pin `ROUTES_SHA256_F11`, `alias-fix.md`. **`services/direct_chat_service.py` этим коммитом не менялся** — D7 уже в `d1a44592`; §7 в `alias-fix.md` перечисляет его как файл «этого среза» неточно. |
| `87f621bb`/`1d919638`/`52061e3f` | Только evidence/probes/harness; продуктовый код не менялся. |

Проверено: `git diff --name-only d1a44592..f42e2257` по продуктовым каталогам даёт ровно `services/summary_aliases.py`, `web/api/routes.py`;
удалён только `tests/test_p0_alias_runtime_2026_10_25.py` (дубль, покрытие перенесено).

## 3. Обязательные независимые прогоны (реальный вывод)

1) Целевой набор:
```
py -3 -m pytest tests/test_asap3_identity_aliases.py tests/test_summary_aliases.py \
  tests/test_p0_initfix_initiative_observer.py tests/test_p0_init_arch_fix_observer.py -q
73 passed, 2 warnings in 9.21s
```
2) Расширенный P0-набор:
```
py -3 -m pytest tests -k "speech_p0 or direct_l1 or asap3_identity or summary_alias or protected or clear_forget or observer" -q
285 passed, 15465 deselected, 5 warnings in 21.35s   (PYTEST_EXIT=0)
```
3) Дополнительно (изменённые области, не входили в `-k`): `tests/test_direct_chat.py tests/test_direct_context_composer_asap3.py tests/test_direct_chat_prompts.py tests/test_asap_w1_semantics.py` → **264 passed**.
4) Byte-freeze/инварианты F8: `test_round1025_f8_registry`, `test_mca23_planned_vs_actual`, `test_mca17c_invariants_round1047`, `test_mca12_stories_round1046` → **83 passed**; фактический `sha256(web/api/routes.py) = a75a3333a2be82f0f5ac0f4cad3dd799d43cd6e6a456cd2a47add8fef9e8bf06` совпадает с перепином; новых endpoint'ов нет (только поле в существующем).
5) `py -3 -m py_compile` по всем изменённым продуктовым/тестовым файлам → **OK**.
6) Новый файл отдельно: `tests/test_asap3_identity_aliases.py` → **35 passed**.

## 4. RED на коде до среза (`272170e3`)

Скрэтч-worktree `%TEMP%\opencode\alias-red-272170e3` (detached `272170e3`), в него скопирован **только** новый тест-файл; продуктовый код — базовый.

```
py -3 -m pytest tests/test_asap3_identity_aliases.py -q \
  -k "a17 or a18 or a19 or a20 or a21 or a22 or a25 or f5 or f7"
→ 12 failed, 1 passed, 22 deselected
```
Причины падений соответствуют дефектам, а не форме теста:
- a17: `assert 'автор: Гипербореец [user:1001]' in 'автор: Игорь из клиента\n...'` (D1);
- a18: `build_eval_user_prompt() got an unexpected keyword argument 'alias_resolver'` (D2);
- a19: `assert 'Макс' == 'Первый'` (D3 — стартовый снапшот);
- a20-startup: `assert None == 'Гипербореец'` (F3-биндинг);
- a20-rag: нет строки-инструкции в `<UserResolutionMap>` (F4);
- a21: `_build_alias_map() got an unexpected keyword argument 'usernames'` (D7);
- a25: `assert 'автор: Леха-другой [user:1002]' in 'автор: Лёша\n...'` (D1/роли);
- f5×3/f7: нет `user_id`-scope и нет `by_uid` (F5/F7).
Единственный зелёный на базе — `test_a18_observer_without_resolver_keeps_author_name_bytes` (обязательный parity-guard F2).
Ослабления существующих тестов нет: правки в `test_direct_chat.py` (размер map-блока +1 строка), стабах `_participant_roster`/`_l1_reply_block` и re-pin F8 — адаптация к аддитивным изменениям, не снятие проверок.

## 5. Таблица 11 проверок §2.3

| № | Требование | Статус | Доказательство |
|---|---|---|---|
| 1 | Локальный алиас > глобального | VERIFIED | `merge_alias_maps`/`build_alias_resolver` (`chat` перекрывает uid), a2/a3/a7/a16; RED на базе |
| 2 | Глобальный алиас > никнейма | VERIFIED | `AliasResolver.resolve` порядок, a1, unit `test_summary_aliases` |
| 3 | Никнейм > username | VERIFIED | `resolve` порядок + `test_nickname_second`, `test_username_third_without_at` (прогнаны) |
| 4 | Изменение без рестарта | VERIFIED | resolver пересобирается в начале хода (`_refresh_turn_aliases`), `set_chat_params` инвалидирует кэш; a4/a5/a6/a17 (второй ход), a19 (фон) |
| 5 | Старый кэш не отдаёт устаревшее | VERIFIED | `_cache` живёт на инстансе, инстанс новый на ход; a19/a20-startup; стартовый снапшот — только fallback |
| 6 | История ищется по старым именам | VERIFIED | FTS не переписывалась, a22 (поиск находит текст, текст дословно); `author_name` в FTS не индексируется — как и до фикса |
| 7 | Ответ на reply — правильному человеку | VERIFIED | `_l1_reply_block` = alias по uid + `[user:id]`, адресат — автор текущей реплики; a17/a25; роль цитируемого не подменяет адресата |
| 8 | Третье лицо не подменяет адресата | VERIFIED | `speaker=target_name`, `addressee=bundle.addressee or "чат"`, `mentioned` не участвует в адресате; a25 (payload-сборка) + код |
| 9 | Два похожих имени не сливаются | VERIFIED | ключ — uid, `_by_name` отбрасывает неоднозначные, дискриминатор `(username)`/`#хвост`; a21 |
| 10 | Старое имя из RAG/Memory не вытесняет алиас | VERIFIED | F4-инструкция в `<UserResolutionMap>`, все identity-поля рендерятся по alias, тексты не переписываются; a20/a11/a22. Оговорка: это детерминированная часть контракта; отдельный LLM-прогон кейса «старое имя в свободном RAG-тексте» в лейне не выполнялся (LLM запрещён), т.е. гарантия — на уровне prompt-контракта, а не поведения модели |
| 11 | Все пути — одни правила | VERIFIED | Direct/L1/L2 (`_row_speaker`, `render_window_lines`, `_build_user_content`), reply (F1), Observer/Initiative (F2+F3), фон (F3), Summary (`_format_l2_quote`), tool/media (a13), dossier (uid), F7-диагностика; a13/a13-init/a18/a19 |

## 6. Что реально видел модель (payload), и источник «Гипербореец»

**Источник имени.** `handlers/summary.py:351-355` пишет в `smart_messages.author_name` результат `_aliases.resolve(...)` на момент записи (исторический снимок). Прод-read-only аудит `prod-worktree-alias.md` §2: uid `42115912`, `author_name = «Гипербореец»` (34342 сообщения), при этом глобальный и чатовый алиас = **«Макс»** (`source=chat`). Логика кандидата: `AliasResolver.resolve` сначала берёт алиас по uid, поэтому для `42115912` обязано вернуться «Макс»; это воспроизведено мной на кандидате:

```
resolve(current user) = Макс
resolve(row author_name history) = Макс
<UserResolutionMap>
инструкция: ... актуальное имя участника — по user_id из этой карты
Макс — 42115912
</UserResolutionMap>
L1 payload: [user:42115912] Макс: вчера обещал разобраться
            Говорящий: Макс / Адресат: Макс
alias changed without restart -> resolve = Новое Имя; map = Новое Имя — 42115912
```

**Payload, который ушёл модели.** В committed raw-пробах `probes_final/raw_new_*.json` (`payload.messages`, реальный L2-вызов на прод-БД в offline-harness, продуктовые модули запинены на `d1a44592`):
- `alias_probe = {uid:42115912, display:"Гипербореец", resolved:"Макс", source:"chat", chat_alias:"Макс", global_alias:"Макс"}`;
- в `messages[1].content` — `<Target_User>Макс</Target_User>`, строки окна «Макс: …», **0** вхождений «Гипербореец» (вне `alias_probe`);
- `messages[0]` (system) также без «Гипербореец».
Проверено по всем 5 файлам `raw_new_*` (A1/A2/B/forced A/B): `Гипербореец` в payload = 0, `<Target_User>Макс</Target_User>` = True.
Оговорка: это **сокращённый harness-payload** (`rag → global → target → current`), а не полный `_build_user_content`; полный Direct L1/L2 payload с картой в этом лейне не снимался. Для реального service-пути фактический `messages[1]["content"]` захвачен тестом `test_a13_initiative_l1_and_l2_use_alias_not_author_name` (initiative L1, тестовая карта, не прод-uid): `[user:1001] Гипербореец:` + `участник Гипербореец [user:1001]`, историческое имя `Игорь (имя из клиента)` отсутствует. Для нормального Direct сборка `messages[1]["content"] = build_l1_context(...)` — одна строка (`direct_chat_service.py:4322-4341`), а сам builder проверен `a25` (`автор: … [user:2]`, `Адресат: Макс`). Таким образом, имя в модель доходит; админ-UI тут ни при чём.

## 7. Дефекты

Блокирующих дефектов по §2.1–§2.3 нет.

### Non-blocking observations

1. **`_map_names` парсит новую строку-инструкцию как «упомянутого человека».** `services/direct_chat_service.py:535-542`: каждая непустая строка `<UserResolutionMap>` режется по `" - "`, но строки карты используют `—` (U+2014), а инструкция не содержит ни того, ни другого. В `EvidenceBundle.mentioned` (строка 6478-6480) попадает текст инструкции (и до фикса — строки «Имя — uid» целиком). Потребителей у `mentioned` нет (`mca_retrieval_context` только поле), пользовательского эффекта нет. Минимально: `if " — " in line`/regex, либо не считать первую строку. Не требую для приёмки.
2. **`initiative_diagnostics.run_check` не биндит per-chat резолвер.** `services/initiative_diagnostics.py:916-945`: runner создаётся с `alias_resolver=writer_service.aliases`, но `_evaluate_window` вызывается без `bind_turn_aliases(chat_id)`, поэтому dry-run «Проверить наблюдателя» может показать глобальный/стартовый слой вместо чатового override. Боевой `observe_tick` биндит (`initiative_observer.py:1363-1370`). Диагностика — не путь генерации, вне 11 проверок; локальный фикс: bind перед `_evaluate_window`.
3. **`/persona` по-прежнему scope-ит факты по имени, не по uid.** `services/direct_chat_service.py:8227-8240`: `get_persona_card(chat_id, canon, ...)` без `user_id`; досье использует uid (`web/api/chat_lore._dossier_payload`, тест `test_dossier_keeps_fact_with_stable_uid_after_rename`). Имя отображается актуальное (canon из live-резолвера), но после переименования старые факты карточки могут не найтись. Не входит в 11 проверок §2.3; фиксирую как остаток по «профилям».
4. **`protected_facts.subject_ref_id` — сырой Telegram uid, а `graph_facts.subject_ref_id` — `mca_source_refs.source_ref_id`.** Одинаковое имя колонки, разная семантика; writer'а per-user protected-фактов в коде нет (оба INSERT пишут `user_name IS NULL`), поэтому сейчас эффекта нет, но будущий writer может перепутать. Лучше явный комментарий/имя (`subject_user_id`).
5. **F5 forward-only.** Существующие per-user строки (если есть в проде) остаются `NULL` и читаются по старому имени; фикс помогает только новым записям, а writer'а нет. В `alias-fix.md` §6.2 это честно указано.
6. **`chat_context.py:135` (factcheck/search) рендерит `author_name` напрямую, без резолвера.** Эти команды не входят в перечень §2.2 и не менялись; если владелец понимает «весь путь обработки сообщений» буквально, это отдельный остаток.
7. **Атрибуция D7 в `alias-fix.md` §7:** `services/direct_chat_service.py` не менялся в `f42e2257` (D7 в `d1a44592`). Продуктового эффекта нет, но трассировка «коммит → файл» неточная.
8. **Полный suite не завершён в этом лейне.** Запуск `py -3 -m pytest tests -q` на чистом дереве остановлен на 75% после длительного отсутствия прогресса (в окружении не установлен `pytest-timeout`, `pytest.mark.timeout` — unknown; на машине параллельно шёл второй pytest-процесс). К моменту остановки (75%) в выводе было 32 `F`; имена узлов не собраны (запуск прерван), поэтому атрибутировать их нельзя. По составу выбранных файлов и заявлению Builder это пре-существующие падения (prompt-dump/soul1-пины, summary-двойные вызовы, миграционные lock-тесты, UI e2e без браузера), но независимо это не подтверждено. Это **не** обязательная проверка лейна; целевые наборы (73/285/264/83) зелёные. Заявление Builder «44 failed/15697 passed, все пре-существующие» независимо не воспроизведено. При релизе полный прогон/сравнение с базой остаётся за DevOps/CI.
9. **Тест-сила:** a25 собирает `addressee` вручную (`service._resolve_name(target)`), а не выводит его из `bundle`; wiring `InitiativeObserverRunner → build_eval_user_prompt(alias_resolver=...)` покрыт кодом, но не тестом; нормальный Direct `messages` (не builder) end-to-end не захвачен. Это не нарушает контракт, но следующая правка может тихо его сломать.

## 8. Что осталось за границей лейна (не влияет на вердикт по алиасам)

- **Карта требований:** `requirements-map-p0-hotfix.json` ссылается на `source-owner-p0-hotfix-chained-2026-10-25.md`; `req_id`/слайса ALIAS в ней нет, файл `source-owner-p0-corrective-2026-10-25.md` в этой ветке отсутствует. Для родительского DONE PM обязан завести §2.1–§2.3 в карту и прогнать `requirements_gate.py --stage review`.
- **Прод/payload:** живой прод-payload и отправки не выполнялись (запрет лейна). Reused evidence (`prod-worktree-alias.md`, `probes_final/*`) связано с `d1a44592` + harness `87f621bb`; `f42e2257` меняет только F7-диагностику и тесты, поэтому вывод по alias-путям переносится.
- **Следующий шаг:** alias-скоуп можно считать принятым; родительский релиз — только после карты §2 и полного suite/CI.

## 9. Итог

Alias/identity-фикс на `f42e2257` соответствует §2.1–§2.3: единый каскад по Telegram uid, chat→global→nickname→username→(memory)→id, live-применение без рестарта на Direct/L1/L2/Observer/Initiative/фон/reply/Writer, роли не смешаны, история не переписана, payload несёт актуальное имя, fallback/лимиты/контракты сохранены, новых квот инструкций нет, RED/пассы подтверждены.
**Вердикт: Approved (alias-scope).**