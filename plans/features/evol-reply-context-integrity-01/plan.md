# EVOL-REPLY-CONTEXT-INTEGRITY-01 FINAL v5 — размещение в очереди и план срезов

- Задача: `evol-reply-context-integrity-01` (реестр `plans/progress_scope.json`, вход `OI-2026-11-03-REPLY-CONTEXT-INTEGRITY-V5`).
- Источник: `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md` (дословный снимок `current_task.md` L5023-5531, 521 строка).
- Карта требований: `requirements-map.json` (285 обязательных строк, 120 сценариев §13 отдельными id `RC-S001..RC-S120`).
- Граф срезов: `slice-graph.json` (8 срезов, волны A-D).
- План-гейт: `check --stage plan` → `inventory=312 manual=43 errors=0`, EXIT 0.

## 1. Решение о месте в очереди

Пакет **не** ставится ни в начало, ни в самый конец очереди: он состоит из двух независимых по файлам веток, у которых разное окружение.

**После принятой FactCheck-цепочки (обязательное предусловие).**
`EVOL-FACTCHECK-CRITICAL`, `ASAP-FC-ADMISSION-01`, `ASAP-VISION-SYNC-01`, `ASAP-FC-EVIDENCE-STYLE-02` уже в `evol/impl` (проверено `git merge-base --is-ancestor`), их строки массово `VERIFIED`. Наш пакет меняет те же файлы (`factcheck_suitability`, `factcheck_service`, `factcheck_orchestrator`, `factcheck_renderer`, `handlers/factcheck`) и **переоткрывает часть их утверждений** (§11 против «честных технических статусов», §10 против media-ассоциации). Идти раньше значило бы строить на неактуальном HEAD и ревьюить дважды. Зависимость фактическая: наш срез обязан стартовать от их принятого состояния.

**До `asap-fc-voice-01` (P0 голос фактчека).** `FC-RENDERER`/`FC-WRITER-PATH` переписывают подачу того же ответа (`factcheck_renderer`, `factcheck_service`, `prompt_composer`, `direct_chat_service`, `direct_l1`). Если голос выйдет первым, он будет приниматься на заголовках, правдивость которых ещё не доказана (§11.2), а затем тот же файл переедет второй раз. Порядок: сначала честный статус и адресация, потом стиль.

**Параллельно с UI/мем-пакетами.** `epic-cm-visual-01` (`web/**`), `hotfix-meme-publication-initiative-ui` (`web/**`, `services/meme_initiative.py` для публикации), `meme-pipeline-refactor-01` P4/P9 (`web/**`, `services/initiative_diagnostics.py`) не пересекаются по файлам с RC-TARGET-ANCHOR / RC-CONTEXT-FIDELITY / RC-CONTEXT-CLAIM, поэтому UI-линии можно не останавливать.

**Не параллельно, а последовательно с общим писателем.** `asap-evol-anticliche-memory-admin-ux` (AC-P0/AC-COMPILER: `direct_chat_service.py`, `prompt_composer.py`, `factcheck_service.py`) и `epic-experience-learning-performance-help` (EP-E-DIALOGUE: `direct_chat_service.py`, `prompt_composer.py`, `handlers/direct_chat.py`) — тот же узел, что у RC-SPEECH-BOUNDARY и RC-DIRECT-SELFCORR. Правило: один писатель на `services/direct_chat_service.py` + `services/prompt_composer.py` в единицу времени; второй пакет входит после закрытия среза, либо срез отдаёт эти файлы ему и переносится.

**`meme-pipeline-refactor-01`** остаётся владельцем `services/meme_initiative.py` по своим пакетам; сценарий §13.69 (текст шутки не печатает технические ID) закреплён за RC-SPEECH-BOUNDARY, поэтому мем-пакет не правит этот файл, пока срез не принят.

**Experience.** `epic-experience-learning-performance-help` владеет долговременным обучением; здесь только локальная коррекция в диалоге (§12.2 п.8). Дублирования нет, зависимость обратная: наш срез не должен создавать свой lifecycle.

**Строго говоря о порядке волн:** A — RC-TARGET-ANCHOR + RC-CONTEXT-FIDELITY (2 писателя, файлы не пересекаются); B — RC-CONTEXT-CLAIM + RC-MEDIA-OPTIONAL + RC-SPEECH-BOUNDARY (3 писателя); C — RC-EVIDENCE-STATUS + RC-DIRECT-SELFCORR; D — RC-TRACE-ACCEPT. Ребра, поставленные намеренно (сериализация, а не логика): `RC-TARGET-ANCHOR → RC-MEDIA-OPTIONAL` (общий `handlers/factcheck.py`), `RC-MEDIA-OPTIONAL → RC-EVIDENCE-STATUS` (общая точка сборки уведомления и заголовка), `RC-CONTEXT-FIDELITY → RC-SPEECH-BOUNDARY → RC-DIRECT-SELFCORR` (общий `direct_chat_service.py`/`prompt_composer.py`), `RC-TARGET-ANCHOR → RC-CONTEXT-CLAIM` (Claim строится из зафиксированного Target).

## 2. Строки, которые дефект переоткрывает

| Строка | Карта / срез | Текущий статус | Чем именно переоткрыта |
| --- | --- | --- | --- |
| `REQ-DELTA-10-NO-INTERNAL-IDS` | `p0-delta-analysis` / DELTA-PROVENANCE | VERIFIED (076f7391) | §9.1 (наблюдаемая реплика с голыми `1194297/1194305/1194313`) + §9.3 п.1-7 + §13.53/68/70. Прежняя приёмка шла по 16 живым ответам и не покрыла путь `canonical_context.resolve_item_id → format_context_item → _context_row_line`. |
| `ASAP-FC-ES-STATUS` | `evol` / ASAP-FC-EVIDENCE-STYLE-02 | VERIFIED | §11.1-11.3 + §13.44-52: заголовок «Проверка не завершена: материалы не удалось разобрать» наблюдался вместе с содержательным разбором текстового тезиса, т.е. исход стадии и текст разошлись. Прежняя приёмка различала коды, но не проверяла заголовок против фактической стадии и против media-оговорки. |
| `FC-05A` | `p0-factcheck-post-release` / S5-SEARCH-DIAG | VERIFIED (2.58.139) | §11.3: reason-code обязан подтверждаться метрикой/событием стадии, а не отсутствием URL или релевантных результатов. Наблюдаемый ответ этому не соответствует; строку надо перепроверить на задеплоенном пути, а не считать закрытой. |
| `PA5-S7-AUTHORITY` | `post-asap5-corrective` / PA5-S7-AUTHORITY | VERIFIED | §12.2 п.4 + §12.1: «собственный предыдущий ответ не имеет приоритета» — наблюдаемое поведение (защита своего вывода вместо пересмотра) прямо противоречит утверждению строки. |
| `ASAP-VISION-SYNC-01` (агрегат) | `evol` / ASAP-VISION-SYNC-01 | VERIFIED | Не противоречит, но **не покрывает**: ни один его сценарий не утверждает media-уведомление для явной текстовой цели. Оставляем VERIFIED, добавление — новые строки §10; Reviewer при первом же прогоне обязан проверить, нет ли среди его 20 сценариев обратного утверждения. |

Не переоткрываются (проверено содержанием): `FC-07C` (недублирование технических сведений), `ASAP-FC-ES-CLAIM/SOURCES/ACCEPT`, `ALIAS-ROLE-SEPARATION`/`ALIAS-RT-REPLY-CONTEXT`/`ALIAS-T08-THIRD-PARTY` (различение ролей в ответе), `M-ADTR-ENTRY-EVENT`, `EVOL-015`. Их приёмка не противоречит новым сценариям; новые обязательства (уместность вмешательства, единица счёта, прагматика критики) идут отдельными строками §12.

## 3. Что пакет не делает (защита от дублей)

- Не создаёт новый движок Reply, второй граф диалога, LLM-классификатор, БД тем, отдельную БД опровержений (§2, §8, §12.2 п.8, §14).
- Не вводит regex-чистку готового текста, второй Writer, LLM-редактор, перегенерации (§9.3 п.6, §12.3).
- Не вводит новые токенные/временные/размерные бюджеты; существующие лимиты сохраняются (§5.2, §5.4, §8, §12.3).
- Не забирает у `p0-factcheck-media` целостность альбомов и caption: там остаются FC-ALBUM/FC-WHOLE/REQ-FC-09-*; здесь только «нужна ли проверке эта медиа-связь».
- Не заменяет Experience-эпик: локальная коррекция не публикует долговременный урок.

## 4. Архитектурная классификация

`ARCHITECT_REQUIRED`. Триггеры: меняется общий контракт представления контекста (`canonical_context`/`chat_context`/`context_middleware`) для Direct/Observer/Writer/FactCheck/Memory/GraphRAG; меняется порядок выбора цели и решения о медиа-зависимости в двух маршрутах фактчека; вводятся обязательные поля трассы (`target_resolution`, `claim_selection`). Владелец прямо поручил Architect доказать непрерывность `target_ref` на текущем HEAD и решать технические развилки без human gate (§14).

До заморозки контракта допустима разведка/подготовка (сбор фактов о текущем data-flow, чтение карт), но Builder не начинает RC-CONTEXT-CLAIM, RC-MEDIA-OPTIONAL, RC-SPEECH-BOUNDARY, RC-DIRECT-SELFCORR. RC-TARGET-ANCHOR и RC-CONTEXT-FIDELITY могут стартовать параллельно как первые две полосы, их интерфейсы фиксирует Architect.

## 5. Ожидаемые доказательства

- Каждый срез: candidate-bound `evidence` с `ref`, `observation`, `type`, `artifact_path` (реальный файл репозитория), при устойчивом отчёте — `artifact_sha256`.
- Сценарии §13 — собственный прогон Reviewer на фактическом payload и трассе; «зелёные unit с моками» и `assert 'tg:' not in text` недействительны (§9.4, §13.30/70/95, P0-критерий).
- RC-SPEECH-BOUNDARY: три границы одного сообщения (typed refs → payload Writer → публикация).
- RC-CONTEXT-FIDELITY: сравнение внутренних структур, payload L1/LLM (включая Composer OFF и fallback), выбора модели и публичного текста на одном входе.
- RC-TRACE-ACCEPT: одна трасса `trigger → target_resolution → thread_context → semantic_context → claim_selection → planner/search/verdict → delivery` плюс доказательство отсутствия запрещённых механизмов.
- Деплой: обычный путь, проверка по SHA, production-equivalent доказательства; при отсутствии журнала — воспроизводимый fixture, а не «непроверяемо» (§14).
