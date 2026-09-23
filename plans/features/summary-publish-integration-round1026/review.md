# Review — S6 `summary-publish-integration-round1026` (единый Reviewer gate T-3454/T-3455; **повторный gate после rework T-3456**)

- **Feature-ID:** `summary-publish-integration-round1026` (Эпик 2, §100–§106; P0)
- **Risk-Level:** **R2** (подтверждён фактическим diff: §104-контур, OFF-генерация, DDL, каталог, секреты, зависимости и стриминг не затронуты; rework T-3456 — только публикационный контур S6; повышение до R3 не требуется)
- **Status: Approved** — блокеры round 1 (**B-R1026S6-1**, **B-R1026S6-2**) закрыты и перепроверены независимо; Critical/High/блокирующих Medium = 0; обе линзы (requirements/correctness + focused change audit) пройдены. Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Reviewed-Commit:** `197891fdb643a914f771b818d9f84c385dc0706b` (HEAD == `origin/master`, closing-docs S8; annotated-тег `pre-round1026-s6`, tag-obj `6fd4a9d6` → `197891f`; правки S6 **НЕ закоммичены** — `git status`: 49 M + 3 ??-записи = 7 untracked-файлов; манифест Working-Tree-Hash — 6, кроме `review.md`)
- **Working-Tree-Hash:** `4c7b2917205e14a682f495adfadb13bbfc1f949f8dc56deda1960b83c97f59c4`
  - Рецепт (детерминированный, как в S7/S8): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) = строка `git-diff 197891f sha256=7096e17eca7ed1cf4d8633634c4f899913a70c7891d61d38d1eee5151ba172c0` (SHA-256 **сырых байт** stdout `git diff 197891f`, **уже с записью в `plans/reports/audit_backlog.md`**) + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), **кроме** `plans/features/summary-publish-integration-round1026/review.md` (сам отчёт).
  - Per-file (SHA-256, lowercase): adr `026e883c0bdfef7a75d02c0320906882373345514b02be07c794b893eb3afa57`, evidence `861cb4ec94e856266f9a453cf3af38b9ae260c88d57fb79f7470db9fa6209a7c`, spec `77c1777558e5e842aa0bc01f84b21dd31deaa2fcbab51b2b5df06b47ea3bf11a`, tasks `2f5dfd3f91db3a499302a5b47e8d38172df9578097ae76a6edf3d471b214addb`, `tests/test_summary_publish_integration_round1026.py` `3808e324d3d18cc7f777f685b70309249163b6d257418027171b4c5823e80a1f`, `tests/js/round1026_s6_publish_test.js` `9e8c3b51c4a0dc25c07d8e8783d8763d18d5d0968a611971b3e2bd9f9127cff3`.
- **Spec-Hash:** `77c1777558e5e842aa0bc01f84b21dd31deaa2fcbab51b2b5df06b47ea3bf11a` (не менялся; ожидание `77C17775…` подтверждено)
- **Binding связан с текущим состоянием worktree:** любая правка product code / untracked-кода / `spec.md` после этой фиксации делает approval устаревшим и требует пересчёта.

## 1. Git base и фактический объём изменений (линза 2)

- **База:** `197891f` (== `origin/master`; tag `pre-round1026-s6` → `197891f`, проверено `git cat-file -p`). Коммитов S6 нет; `git status --porcelain` — 49 M + 3 ??-записи (7 untracked-файлов: 5 документов фичи + 2 тестовых; манифест Working-Tree-Hash — 6, кроме `review.md`).
- **Rework T-3456 затронул ровно 4 файла** — подтверждено независимо по mtime (ревью round 1 — 08:44): `services/summary_article_formatter.py` 08:50, `services/summary_generator.py` 08:50, `tests/test_summary_article_formatter.py` 08:51, `tests/test_summary_publish_integration_round1026.py` 08:53; все прочие файлы фичи — ≤ 08:24. Соответствует заявлению @Builder; покрытие round 1 для остальных файлов сохраняется.
- **Product code в diff:** `services/summary_generator.py`, `services/summary_article_formatter.py`, `services/summary_run_log.py`, `services/summary_l2_writer.py` (только L-R1026S5-6), `services/execution_graph_source.py`, `web/static/execution_graph.js`, `web/app.js`, `web/api/analytics.py` (**только docstring**), `config/settings.py` (APP_VERSION), `README.md`, `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп), тесты.
- **Вне diff (проверено пустым `git diff --name-only 197891f -- …`):** `services/telegram_send.py`, `services/image_generation.py`, `services/summary_prompts.py`, `services/summary_test_run.py`, `web/api/routes.py`, `db/**`, `services/param_catalog.py`, `bot.py`, манифесты зависимостей.
- **`web/api/analytics.py` — только docstring:** независимое AST-сравнение с `git show pre-round1026-s6:web/api/analytics.py` без докстрингов — идентично (`AST_EQUAL_NO_DOCSTRINGS: True`).
- **Стриминг/чанки/генерация не тронуты:** `_send_streaming`, `_send_chunked`, `_send_one_chunk`, `_chunk_by_whitespace`, `_llm_generate`, `_ensure_shiz_postfix`, `_resolve_cover_prompt`, `_compose_user_content`, `_apply_filter` — AST-идентичны baseline. `_generate_two_call` изменён только аддитивным `title=extract_title_from_markdown(digest)` (D2/§5.3).
- **R18 цел:** annotated-тег `pre-round1026-s6` → `197891f`; бэкап `var/backups/s6-round1026-20260924-070835/`; `.env.bak.round1026-s6`; `stash@{0}` (round1025) на месте.

## 2. Выполненные проверки (независимо воспроизведено @Reviewer, round 2)

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9000 passed, 0 failed**, 1 warning (153.86 с) — заявленное Builder 9000/0 подтверждено |
| S6-файл | `pytest tests/test_summary_publish_integration_round1026.py -q` | **69 passed** (58 → 69, +11) |
| Форматтер | `pytest tests/test_summary_article_formatter.py -q` | **16 passed** (S5-пин перепрофилирован в no-loss, не ослаблен) |
| JS | цикл `node tests/js/*.js` (47 файлов) | **OK=47, FAIL=0** |
| `git diff --check` | — | exit **0** |
| Каталог / версия | импорт `param_catalog`/`settings` | **469/426/444/100/98/21**; `APP_VERSION` **2.58.28**; README v2.58.28 |
| Δ DDL | `db/**` вне diff + regex `CREATE/ALTER/CREATE INDEX` по изменённым модулям | **0** |
| Зависимости | diff манифестов/локов | **0 новых** |
| 2-вызовность | `pytest … -k two_calls` (L1/test-run) | **3 passed**; `await_count==2` (ON/OFF-интеграции S6 в полном прогоне) |
| Хэши evidence | пересчёт SHA-256 всех 16 заявленных файлов | **все MATCH** (хэши Builder достоверны, включая обновлённые после rework) |
| R17 | пробы: WARN переполнения — только числа/причины; `FORMAT_ERROR`/`PUBLISH_*` — без сырого текста | подтверждено |
| R18 | tag/бэкап/`.env.bak`/`stash@{0}` | целы |

## 3. Независимые пробы rework (39/39 PASS) — реплика findings round 1

| Проба | Метод | Результат |
|---|---|---|
| **a** plain 600 абз. | `_deliver_plain` (мок `send_text`) | chunks=11, **missing=0**, `PUBLISH_TEXT_COMPLETE message_id=101` (первый чанк), `ctx.publish_channel=text/status=ok`; WARN о потере нет |
| **b** rich char-overflow | `_publish_rich_document`, 45×~810 симв. | `send_rich_message` **await_count=0** (rich не отправлялся); WARN `reason=rich_char_limit html_len=36947`; `FORMAT_ERROR channel=rich reason=rich_char_limit`; `PUBLISH_RICH_START` отсутствует; plain-фолбэк **45/45** абзацев, `PUBLISH_TEXT_COMPLETE reason=rich_overflow message_id=101` |
| **c** rich paragraph-overflow | `_publish_rich_document`, 600 абз. | `reason=rich_paragraph_limit`; rich не отправлялся; plain **600/600** (missing=0); `PUBLISH_TEXT_COMPLETE reason=rich_overflow` |
| **d** emphasis в доставке | `chunk_plain_blocks` vs `format_plain_html` | `chunks == [format_plain_html(doc)]` байт-в-байт; `<b>дождь</b>` есть; ≤1 `<b>`/абзац; emphasis `<b>&</b>` → `&lt;b&gt;&amp;&lt;/b&gt;` (экранирование сохранено) |
| **e** границы rich-лимитов | `rich_document_limits` | 498 абз. → fits; 499 → `rich_paragraph_limit`; ровно 32000 симв. → fits; 32001 → `rich_char_limit`; `format_rich_html` отдаёт 45/45 `<p>`, len 40375 > 32000 (усечения нет) |
| **f** экранирование/whitelist | `format_rich_html`/`format_plain_html` | теги ⊆ `{img,h1,p,b}`; `<script>` не проходит; `&amp; &lt; &gt; &quot; &#x27;`; эмодзи/Unicode целы; `img` → `h1` → `p`; в plain нет `<h1>`/`<img>` |

## 4. Линза 1 — требования/correctness (REQ-S6-01…-10 / SC-01…SC-20)

- **REQ-S6-01/SC-01 (§100) — OK:** rich-путь идёт через существующий `send_rich_message` (`content_format="html"`, `cover_id`, `media`); второго rich-механизма нет; `telegram_send.py` вне diff.
- **REQ-S6-02/SC-02 (§101) — OK:** `<img>` → настоящий `<h1>` → `<p>`; H1 не жирный; в plain H1 нет; заголовок детерминирован (digest → короткая первая строка → первое предложение → нет заголовка).
- **REQ-S6-03/SC-03 (§102) — OK:** `<p>`/≤1 `<b>`; whitelist `img/h1/p/b`; экранирование `& < > " '`, Unicode/эмодзи/ссылки; L-R1026S5-5/-6 закрыты.
- **REQ-S6-04/SC-04 (§103) — OK:** утверждения §8/лимиты (32 768/500/16/50/20; `RICH_MAX_CHARS=32000 ≤ 32768`; plain-чанк 4096); копии документации в промптах нет.
- **REQ-S6-05/SC-05 (§104) — OK:** diff `image_generation.py`/`compose_cover_image_prompt`/`_resolve_cover_style_text`/`build_cover_media`/порядок/прикрепление — пуст; обложка — часть статьи.
- **REQ-S6-06/SC-06/SC-20 (§105) — OK (блокеры закрыты):** `<b>title</b>`+абзацы+совместимые `<b>`-акценты в фактической доставке (единый канон `_plain_html_blocks`); чанки ≤4096 по границам абзацев; финальный даунгрейд `format_plain_text`+`chunk_plain_text`; ни один абзац не теряется/не дублируется (пробы a/c); `message_id` первого чанка — в `PUBLISH_TEXT_COMPLETE`; переполнение rich не срезается молча — plain-фолбэк с полным текстом.
- **REQ-S6-07/SC-07 (§106) — OK:** 4 кода различимы; fail-closed L1/L2 (публикации нет); retry ≤1 на отправку; «текст без обложки публикуется».
- **REQ-S6-08/SC-14/SC-15/SC-16 — OK:** R17/R18; Δ DDL=0; Δ каталога=0; 0 зависимостей; CSP/zero-build; bump 2.58.28 + README + cache-bust.
- **REQ-S6-09/SC-10…SC-13/SC-17 — OK:** `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` + publish-узел только из реальных данных; `publication_status` реальный (нет данных → `None`); dry-run S9 — 0 публикаций/0 `PUBLISH_*`; viewer не переписан; S10-остаток не реализован.
- **REQ-S6-10/SC-18/SC-19 — OK:** L-R1026S5-3 подтверждён; -4 закрыт; -5/-6 исправлены; S-R1026S5-7 исправлен (ON: `memorize_facts` ровно 1 раз); детерминизм/отсутствие мутации входа.

## 5. Линза 2 — focused change audit

- **Границы diff:** подтверждены фактом (§1); `param_catalog.py` вне diff; F8 не переиздавался.
- **R17:** новые WARN/FORMAT_ERROR/PUBLISH_* — только числа/коды/причины/id; `_mid` обрезает не-int; сырой текст в пробах не течёт.
- **Интеграционные швы:** `web/app.js`/`execution_graph.js` — маркеры/подписи/статусы аддитивны; `publicationStatus` без `gated`; вторая визуализация не создана.
- **Поведение при ошибках:** cover failure/unavailable → `COVER_*` + plain; rich-send failure → `RICH_MESSAGE_SEND_FAILED` → plain; rich-overflow → WARN + `FORMAT_ERROR` + plain (без `PUBLISH_RICH_START`); финальный текстовый провал → `TEXT_FALLBACK_FAILED` + `SUMMARY_FAILED`; `fallback_done` исключает двойной фолбэк; временный файл обложки удаляется в `finally`.
- **GATED-тесты S7/S8:** перепрофилированы без удаления/ослабления — `test_publish_events_only_on_real_publication`, `TestPublishNode`, `test_publish_row_not_llm_node`; JS-S8: publish-узел рендерится, `gated` отсутствует; dry-run — `PUBLISH_` не эмитится; новых skip/xfail нет.
- **Δ DDL:** `db/**` вне diff; 0 DDL-хитов в изменённых модулях.

## 6. Оценка семантики `format_rich_html` (без усечения) — **корректная реализация no-loss, не дефект**

- **Лимиты Telegram соблюдены:** rich отправляется только при `rich_document_limits["fits"]` (≤ `RICH_MAX_CHARS=32000` < Bot API 32 768; ≤498 абзацев + h1/img = ≤500 блоков). Сверхлимитный rich **не отправляется** — пробы b/c: `send_rich_message` await_count=0, `PUBLISH_RICH_START` не эмитится.
- **Переполнение → plain-фолбэк с полным текстом:** WARN с числами (R17-safe) + `FORMAT_ERROR channel=rich` + `PUBLISH_TEXT_COMPLETE reason=rich_overflow`; SC-20 (каждый абзац ровно один раз, `message_id` первого чанка) выполнен.
- **Защита от расхождения счётчика:** если Telegram всё же отклонит rich (например, UTF-16-счётчик эмодзи), срабатывает `RICH_MESSAGE_SEND_FAILED` → plain-фолбэк с полным текстом (без потери).
- **Вывод:** снятие усечения в чистом форматтере — правильная реализация §105/SC-20 (предписание round 1: «не срезать молча»); лимиты канала перенесены на уровень решения о доставке (`rich_document_limits`), а не отменены. Требование «fix @Builder» **не требуется**.
- **Doc-drift (non-blocking):** spec §7 («`format_rich_html` — без изменений контракта») и ARCHITECTURE §76.1/S5-spec описывают лимиты как свойство форматтера — @Architect фиксирует перенос проверки лимитов из форматтера в доставку на merge **T-3457 (§80)**.

## 7. Counterexamples (проверено, не гипотезы)

1. **>498 абзацев / >32000 симв. (plain и rich)** — пробы a/b/c: потерь нет, явные WARN/события, plain-фолбэк с полным текстом. OK.
2. **Ровно на границе лимита** — 498 абз. fits / 499 overflow; 32000 fits / 32001 overflow (строгое `>`). OK.
3. **Экранирование/adversarial-текст** — только `img/h1/p/b`, всё экранировано, эмодзи/ссылки целы. OK.
4. **Длинный один абзац >4096** — `_split_safe` режет без потерь, не рвёт HTML-сущности. OK.
5. **«Вечно RetryAfter»** — rich ≤2, plain HTML ≤2 + финал ≤2, затем `TEXT_FALLBACK_FAILED`; циклов нет. OK.
6. **Rich-overflow: обложка** — сгенерированная обложка не прикрепляется (plain не поддерживает статью-обложку), файл удаляется; текст сохранён — принятый trade-off (§105). OK.
7. **Стриминг ON (Q1)** — `_deliver_plain` уходит в `_send_streaming`, `PUBLISH_*`/`publish_*` не заполняются; вне §105-контура (spec §5.4), default OFF; функции AST-идентичны baseline. Допустимо.
8. **DB-сбой (Q2)** — `ctx.fail(stage="db", reason="db_error", error_type="DatabaseError")`, кода §106 нет; не входит в 4 класса D5. Допустимо.
9. **Пустой документ** — `chunk_plain_blocks` → `[]` → публикация без сообщений с `status=ok`; в живом пути недостижимо (OFF проверяет непустой текст, ON валидирует L2); pre-existing, не регресс.

## 8. Блокирующие findings — **нет**; закрытие round 1

### [B-R1026S6-1] [medium, requirement gap §105/SC-20] — **CLOSED** (rework T-3456; перепроверено независимо)

- **Локации:** `services/summary_article_formatter.py:81-98` (`_iter_paragraphs` — срез `[:MAX_PARAGRAPHS_HARD]` снят), `:137-159` (`format_rich_html` — trim по `RICH_MAX_CHARS` снят), `:162-190` (`rich_document_limits` — новый), `:367-379` (`chunk_plain_blocks`); `services/summary_generator.py:1056-1078` (overflow → WARN + `FORMAT_ERROR` + plain-фолбэк).
- **Воспроизведение (пробы a/b/c/e):** см. §3 — missing=0; rich не отправлялся; WARN/`FORMAT_ERROR`/`reason=rich_overflow`; границы лимитов корректны.
- **Вывод:** ни один путь не теряет текст молча; SC-06/SC-20 выполнены. **Проверка:** пробы + новые тесты + полный pytest/JS (зелёные).

### [B-R1026S6-2] [medium, requirement gap §105/SC-06] — **CLOSED** (rework T-3456; перепроверено независимо)

- **Локации:** `services/summary_article_formatter.py:195-214` (`_plain_html_blocks` — единый канон), `:217-224` (`format_plain_html`), `:367-379` (`chunk_plain_blocks`).
- **Воспроизведение (проба d):** `chunk_plain_blocks(doc) == [format_plain_html(doc)]`; `<b>дождь</b>` в фактической доставке; ≤1 `<b>`/абзац; экранирование сохранено; тесты уровня доставки (`test_plain_delivery_renders_paragraph_emphasis`).
- **Вывод:** SC-06 выполнен. **Проверка:** проба + тесты + полный прогон (зелёные).

## 9. Non-blocking debt

- **[L-R1026S6-D1] [low, docs] — OPEN (non-blocking):** spec §7 и ARCHITECTURE §76.1/S5-spec описывают лимиты rich как свойство `format_rich_html`; фактически их проверяет `rich_document_limits` на уровне доставки. **Fix:** зафиксировать на merge T-3457 (§80, @Architect) — код-фикс не требуется.
- **Q1 (стриминг) — ДОПУСТИМО, актуально:** rework не затронул стриминг (`_send_streaming`/`_send_chunked` AST-идентичны baseline); spec §5.4/D9; default OFF; точка роста — возврат `message_id` из `_send_streaming` отдельным решением.
- **Q2 (DB-сбои без §106-кода) — ДОПУСТИМО, актуально:** `SUMMARY_FAILED stage=db/reason=db_error/error_type=DatabaseError` наблюдаем, R17-safe; при желании — аддитивный `code=DB_ERROR` отдельным решением.
- **[L-R1026S6-4] [info, интерпретация] — актуально:** `extract_title_from_markdown` берёт первую заголовочную строку digest (не обязательно первую строку) — соответствует spec §5.3 п.1.
- **[L-R1026S6-1/-2] (round 1) — сняты фиксами B-R1026S6-1** (cap 498 в форматтере и rich-trim удалены).
- **[L-R1026S6-3] (round 1) — снят:** тихое усечение отсутствует; переполнение наблюдаемо (WARN с числами + `FORMAT_ERROR`).
- **[L-R1026S6-D2] [low, optimization] — OPEN (non-blocking, рекомендация):** проверку `rich_document_limits` можно выполнять до `generate_image_verbose`, чтобы не генерировать обложку при заведомом overflow (сейчас обложка генерируется и отбрасывается) — изменение вне scope rework, §104 не затрагивается.
- **Info:** счёт `html_len` — в code points (`len()`), Telegram считает иначе для не-BMP (UTF-16); маржа 768 симв. + фолбэк на ошибку отправки делают путь безопасным (без потери текста).

## 10. Недоступные проверки (Unavailable checks)

- **Live-приёмка на проде** — не выполнялась (PENDING OWNER VERIFICATION; вне этого gate).
- **Реальная отправка в Telegram** (Rich Message с H1/обложкой, plain-фолбэк, §114-чек-лист) — не выполнялась: сеть/прод-ключи не использовались; проверено на моках/юнит-интеграции. Должно быть закрыто @DevOps на T-3459.
- **Полная построчная независимая сверка всех утверждений spec §8** — не выполнялась (выборочная веб-сверка round 1 + пин-тесты; снимок @Architect).
- **Реальные прод-значения `.env`** (например, `MAX_SUMMARY_PARTS`) — намеренно не читались; после rework потеря текста исключена независимо от значений.

## 11. Handoff

- **@Orchestrator → APPROVED** (единый gate: линза 1 + линза 2 пройдены; блокеров нет). Далее: **T-3457** merge (`plans/ARCHITECTURE.md` §80, ADR-1026-11 Accepted; @Architect — зафиксировать перенос проверки rich-лимитов из форматтера в доставку) → **T-3458** archive → **T-3459** deploy (2.58.28) → **T-3460** handoff; live — PENDING OWNER VERIFICATION.
- Binding: Reviewed-Commit `197891f`, Working-Tree-Hash `4c7b2917…`, Spec-Hash `77c17775…`; любая последующая правка кода/untracked-файлов/spec делает approval устаревшим.
- Отдельный Scanner-отчёт/approval не создаётся (Scanner удалён намеренно; обязанности — в линзе 2 этого gate).

---

## Приложение: round 1 (Needs Fixes, 24.09.2026, до rework T-3456) — сохранено для трассируемости

- Вердикт round 1: **Needs Fixes** — B-R1026S6-1 (тихая потеря текста: plain >498 абзацев — потеря 101; rich >32000 — молча срезано ~4.9k) и B-R1026S6-2 (plain-доставка без абзацных `<b>`); Critical/High = 0; остальные REQ/SC подтверждены. Полные формулировки и доказательства — `plans/reports/audit_backlog.md` (запись round 1) и `plans/features/summary-publish-integration-round1026/evidence.md` §«Rework (T-3456)».
- Round-1 трактовки Q1/Q2 признаны допустимыми и подтверждены в round 2; round-1 подтверждения по REQ-S6-01…-10 (кроме затронутых фиксами) остаются в силе (файлы вне 4 изменённых rework — mtime-подтверждение §1).
