# S13-FC-REQUEST — binding: единый предмет проверки (FACTCHECK-REQUEST-INTEGRITY v2)

- **Slice:** `S13-FC-REQUEST` (SMART-EXECUTION-RELIABILITY-01, план §11, wave7)
- **Owner source:** `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md`
  (§0–§4, §11, §12; sha256 `767baf0a…dc7a`, 1401 строка)
- **Map:** `plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json`,
  строки `slice == S13-FC-REQUEST` (38 req_id, `strict_evidence: true`)
- **Base (RED):** `d20a7f730715ba9e9cba7673c0557794979be339` (release/2.58.199)
- **Branch:** `smart/fc-s13-request`
- **Candidate:** `bc2ac583` (код и тесты); evidence-коммит поверх — только `plans/**`

## 1. Что было и что стало по стадиям

| Стадия | Base `d20a7f73` | S13 (ветка) | Доказательство |
|---|---|---|---|
| handler: разбор команды | `user_hint` = текст после «фактчек»; материал → `target_text` | то же + **один** резолв предмета `_resolve_subject()`; автор материала и автор запроса раздельно | `TestProvenance::test_handler_wrapper_passes_full_hint_to_semantic_stage`; `raw/red-base.txt` O4 |
| смысловая стадия | нет: предмет = `target_text`; уточнение нигде не определяет предмет | `resolve_check_subject()`: без текста после команды **LLM не вызывается**, предмет = материал байт-в-байт; с текстом — существующий LLM-клиент (`module=factcheck, step=subject_resolve`) возвращает структуру `{subject, material_part, request_part, form_request}`, код её валидирует | `TestScenarioAOrdinary`, `TestNoLexicalRouting`; `raw/red-base.txt` O4 |
| suitability/admission | решение по `target_text` + `user_hint`; `ClaimItem` из hint помечался `source="literal"` c анкором материала | решение по-прежнему по **материалу** (`admission_text`), но `ClaimItem` пользователя = `source="user_request"` и анкор = сообщению запроса; срез контекста собирается под **предмет** (`subject_text`) | `TestGateAdmissionSeparation`; `TestProvenance::test_user_hint_claim_item_has_user_request_provenance` |
| temporal envelope | `claim_text` = материал; одно поле на всё; дата/автор материала приклеиваются к любому вопросу | `claim_text` = **предмет**; раздельно `request_text/request_author/material_claim_text/material_author/material_published_at`; для `origin=request` `original_published_at=None`, дата материала остаётся в `material_published_at`; `subject_fingerprint` = subject+mode+revision/content_hash | `TestScenarioAOrdinary::test_envelope_keeps_ordinary_claim_date_and_anchor`, `TestScenarioD/E`, `TestProvenance::test_forwarded_origin_date_not_mixed_with_message_date`; `raw/red-base.txt` O5 |
| декомпозиция | `decompose_claim(envelope.claim_text)` — материал | тот же вызов, но `envelope.claim_text` уже предмет | `TestStageConsistency` (envelope доходит до сервиса) |
| `_claim_units` | отбрасывала всё, чего нет дословно в `claim_text` (при material-плане — условие/вопрос пользователя терялись) | фильтр принадлежности привязан к **предмету**; остаток предмета (условие/вопрос) добавляется структурно, без лексических правил | `TestClaimUnits` (3), `raw/red-base.txt` O2 |
| retrieval plan | `build_retrieval_plan(decision, claim_text=external_claim)` — без происхождения; исходное сообщение могло снова стать приоритетным | план строится только от предмета; несутся `subject_origin/fingerprint/request_part/material_part`; части из запроса получают анкор сообщения запроса и автора-пользователя, части материала остаются материалом | `TestScenarioC/D/E/F`, `TestScenarioGForm`; `raw/red-base.txt` O3 |
| поисковые запросы | из частей материала | из частей предмета (вопрос → запрос по вопросу; сужение → запрос по части; условие сохраняется как часть) | `TestScenarioE::test_question_is_not_proven_as_original_quote`, `TestScenarioD` |
| attribution | `external_claim = claim_text` (материал); атрибуционный инструмент переписывал тезис | `external_claim = subject.text`; переписывание «X сказал» применяется ТОЛЬКО к material-предмету, вопрос/условие пользователя не переписывается | `TestScenarioF` (origin=user_request у частей), `raw/red-base.txt` O5 |
| analyst / validator / verbalizer / renderer | получают `env.claim_text` и `plan.claims` | те же входы, но теперь это предмет; правок в этих модулях нет (S15/S16) | косвенно: `TestStageConsistency` (envelope с предметом уходит в сервис) |
| cache/reuse | ключ среза контекста не содержал предмета → разные вопросы к одному сообщению делили срез | `slice_cache_components(subject=SHA256(normalized subject))`; одинаковый предмет переиспользует срез, другой — нет | `TestCacheIdentity`, `TestCacheRoundTrip` (write A → read B = miss, read A = hit); `raw/red-base.txt` O1 |
| durable media-путь | `question` обрезается до 400 символов → уточнение терялось при отложенном разборе | `defer_until_ready(context=...)` сохраняет полный запрос; `deliver_deferred_factcheck` берёт `context.request_text` | `TestDeferredMediaRequest::test_full_request_survives_durable_roundtrip` |

## 2. Вне исходного `write_scope`: `services/media_readiness.py`

Изменение — 4 аддитивных места (`defer_until_ready(context=...)`,
проброс `context` в `link_pending_intent_for_message` / `take_pending_intent` /
`resume_deferred_requests`). Необходимо: существующее поле `question`
исторически ограничено 400 символами (связка с медиа), а owner §3.2 требует
сохранять пользовательский запрос **без содержательной обрезки**; при
отложенном разборе медиа иначе терялся бы хвост уточнения.
Доказательство: `TestDeferredMediaRequest::test_full_request_survives_durable_roundtrip`
(1200+ символов: `question[:400]` + полный `context.request_text`).
`media_readiness` не входит в граф сериализации S13 → конфликт с S14/S15 не
создаётся; S14 меняет только настройки/бюджеты.

## 3. Требования S13, привязанные к доказательствам

| Req | Что проверено | Где |
|---|---|---|
| SFC-0-01…05 | только редакция 2026-11-14; новый эпик/второй фактчек не создан; правки в существующих структурах | diff (нет новых сервисов/команд); `FactcheckRequest`/`ClaimItem`/`TemporalClaimEnvelope` расширены аддитивно |
| SFC-1-01…04 | дефект воспроизведён на base: предмет терялся, дата/автор переносились | §4 RED |
| SFC-2-01…05 | обычный фактчек без уточнения: без LLM, материал байт-в-байт, дата/анкор прежние, многосоставность/контекст — прежними тестами | `TestScenarioAOrdinary` + 655 существующих тестов |
| SFC-3-01…09 | три сущности раздельно; A–G как реальные случаи; без лексических правил/классификатора | `TestScenarioA…G`, `TestNoLexicalRouting` |
| SFC-4-01…08 | один предмет на всех стадиях; `_claim_units`; temporal; авторство; кэш | `TestStageConsistency`, `TestClaimUnits`, `TestScenarioD/E`, `TestProvenance`, `TestCache*` |
| SFC-10-02, SFC-10-05 | совместимость: OFF-паритет v2 и прежние контракты | 655 существующих factcheck/vision тестов (0 падений) |
| SFC-11-01…05 | LLM определяет смысл, код исполняет; нет новых regex/словарей | `TestNoLexicalRouting` (в т.ч. инспекция исходников резолвера) |

## 4. RED на базе `d20a7f73` (временный worktree)

Команды (полные логи — `raw/`):

```
git worktree add <WorkspaceData>/worktrees/.../SMART-EXECUTION-RELIABILITY-01-…-0052ab9c d20a7f73 --detach
python raw/red_probe.py <base-worktree>            # → raw/red-base.txt
python -m pytest tests/test_factcheck_subject_contract.py -q  # тест скопирован в base → raw/tests-red-base-failures.txt
```

| Наблюдение (probe) | Base | S13 |
|---|---|---|
| O1 ключ среза различает предметы | **false** (один и тот же `3052f78d…` для материала и вопроса) | **true** |
| O2 полный предмет (материал + условие) выживает в `_claim_units` | **false** (`["…тысячи лет."]`, условие потеряно) | **true** (`[…, "Проверить только период 1990–2000 годов."]`) |
| O3 план принимает происхождение предмета | **false** (`TypeError: unexpected keyword 'subject_origin'`) | **true** (запрос по вопросу, `origin=user_request`, анкор запроса) |
| O4 резолвер предмета существует | **false** (`no attribute 'resolve_check_subject'`) | **true** (`origin=request`, запрос сохранён) |
| O5 envelope: вопрос как claim, раздельные поля, дата не перенесена, автор — пользователь, fingerprint | **false ×6** (`claim_text`=материал, `attribution.author`=«Автор поста») | **true ×6** (`claim_text`=вопрос, `author`=«Аня») |

Pytest на базе с тем же файлом тестов: **34 failed, 3 passed** (падения:
`AttributeError: resolve_check_subject`, `TypeError: subject_origin`,
отсутствующие поля envelope и т.д.).

## 5. Мутации (фальсификация)

`raw/mutate.py` применяет по одной смысловой мутации к реализации, гоняет
файл тестов, восстанавливает файл из git. Все мутации **KILLED**
(`raw/mutations.json`):

| Мутация | Ожидаемые группы | Наблюдаемые падения |
|---|---|---|
| M1 кэш среза не учитывает предмет | `TestCacheIdentity`, `TestCacheRoundTrip` | 3 |
| M2 `_claim_units` не добавляет остаток предмета | `TestClaimUnits`, `TestScenarioDCondition` | 3 |
| M3 envelope игнорирует текст предмета | `TestScenarioCNarrowing`, `TestScenarioE…`, `TestStageConsistency` | 1+ |
| M4 дата материала переносится на вопрос | `TestScenarioEStandaloneQuestion` | 1 |
| M5 вопрос подписывается автором материала | `TestScenarioEStandaloneQuestion` | 1 |

## 6. A–G: приёмочные случаи → тесты

| Сценарий (owner §3.3) | Тест-класс | Наблюдаемое |
|---|---|---|
| A. Уточнения нет | `TestScenarioAOrdinary` | нет LLM-вызова, предмет = материал байт-в-байт, дата/анкор прежние |
| B. Не изменяет предмет | `TestScenarioBNoChange` | материал байт-в-байт, разговорная фраза не становится тезисом/запросом |
| C. Сужает | `TestScenarioCNarrowing` | предмет = выбранная дословная часть, полный материал не подменяет |
| D. Добавляет условие | `TestScenarioDCondition` | предмет = материал + условие; условие = отдельная claim-часть; период из условия, дата материала отдельно |
| E. Самостоятельный вопрос | `TestScenarioEStandaloneQuestion` | предмет = вопрос; дата материала не перенесена; автор — пользователь; анкор — сообщение запроса; запрос по вопросу |
| F. Расширяет | `TestScenarioFExpansion` | сохранены и исходный тезис, и дополнительный факт; части запроса помечены `user_request` |
| G. Форма ответа | `TestScenarioGForm` | `form_request` отдельно, предмет/запросы не меняются |

## 7. Команды и счётчики (ветка)

```
python -m pytest tests/test_factcheck_subject_contract.py -v      # 39 passed
python -m pytest <31 файл: tests/*factcheck*.py + bgs01 + evol critical +
    rlr numeric + ur234 ledger + asap8 v63 b07 + vision sync core/wave2>
    --deselect tests/test_factcheck_fc_r1_fix.py::TestRelevanceCascade::test_all_irrelevant_is_honest_failure
                                                                   # 655 passed
python -m pytest tests/test_evol_reply_context_consumers.py tests/test_memory_attribution.py
    tests/test_p1_semantic_routing_demotions.py tests/test_rc_target_media_evidence.py
                                                                   # 137 passed
```

Логи: `raw/tests-branch-full.txt`, `raw/tests-affected-suite.txt`,
`raw/tests-media-consumers.txt`.

## 8. Чего эти доказательства НЕ доказывают (postdeploy / другие срезы)

- **SFC-12-02, SFC-12-08, SFC-12-09**: исходная production-регрессия (вопрос
  о странах) и обычный postdeploy-фактчек на реальном чате — только после
  выката; требует живого LLM+поиска. Статус: `PENDING`/`READY_FOR_LIVE`.
- **SFC-13-01**: поля наблюдаемости на контрольных прод-запусках (S13 пишет
  `subject_origin/resolved_by/fingerprint` в лог; полнота полей — S17).
- **SFC-12-05** (медиа: изображение/альбом/транскрипт): проверен durable-путь
  сохранения запроса; реальное распознавание/альбом — существующий media
  contract / VISION-CONTEXT-UNIFY-01 (не блокирует этот corrective).
- Качество смыслового решения LLM (B/C/D/E/F/G на живых формулировках
  владельца) — Reviewer обязан проверить своими формулировками; unit-тесты
  подменяют LLM scripted-решением.
- Бюджеты/объём/evidence/finalize — S14–S16.

## 9. Побочная находка (BACKLOG_ONLY, не S13)

`tests/test_factcheck_fc_r1_fix.py::TestRelevanceCascade::test_all_irrelevant_is_honest_failure`
падает нестабильно: после «провала» замоканных провайдеров агрегатор уходит в
живой DDGS и получает результаты. На base `d20a7f73` — 1 passed / 2 failed из
3 прогонов; на ветке — 2 failed / 1 passed. Не связано с S13 (search_aggregator
не менялся). Предложение: изолировать провайдеры в тесте (или помечать
network-зависимым маркером).


## 10. Дополнительная проверка финального кандидата (2026-11-14)

- Код кандидата: `bc2ac583`; evidence-коммит: `2237ffcb` (только `plans/**`).
- `python -m pytest -q tests/test_factcheck_subject_contract.py` — **39 passed**
  (три последовательных прогона: 39/39, стабильно).
- Широкий набор: 47 файлов `tests/test_*` по фильтру
  `factcheck|temporal|media|evol_fc|bgs01|rc_target` — **995 passed** (52.25 с).
  Один более ранний прогон дал 994 passed + pre-existing DDG-flake
  `test_all_irrelevant_is_honest_failure`; изолированно и на повторе — PASS
  (см. §9).
- Мутации на финальном кандидате (каждая — временная правка + `git checkout --`):
  M1 убрать остаток предмета в `_claim_units` → 4 failed;
  M2 не обнулять `original_published_at` для request-origin → 2 failed;
  M3 `_claim_digest` пустой → 3 failed;
  M4 `resolve_check_subject` игнорирует уточнение → 14 failed.
- `py_compile` изменённых модулей — exit 0.
- RED на базе `d20a7f73` — **34 failed, 3 passed** (см. §4).

Эти прогоны подтверждают тот же контракт на финальном SHA; они не заменяют
живые LLM/provider проверки из §8.
