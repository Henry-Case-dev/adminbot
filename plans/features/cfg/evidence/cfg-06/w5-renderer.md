# CFG-06 W5 — Presentation/Telegram-renderer + доставка + починка утечки style_note

Дата: 20.10.2026. Лейн CFG-06-W5, параллельно с W4 (скоупы разведены; общий
файл `factcheck_orchestrator.py` — только зона Presentation/Delivery).
Базис: deployed 2.58.98 (`29cc49ba`), схемы — фриз W3
(`w3-schemas.md`), бриф — `cfg-06-build-plan.md` §W5 (06E, 06A.5/06A.8,
CFG-06.B/D.2-3).

## 1. Модули

| Файл | Статус | Содержание |
|---|---|---|
| `services/factcheck_renderer.py` | НОВЫЙ | детерминированный renderer: `FactcheckPresentation` (+`CheckedVerdict` для enum) → Telegram-HTML; `render_factcheck` / `render_plain` / `split_entity_safe` / `deliver_factcheck` / `visible_text` |
| `tests/test_factcheck_renderer_cfg06.py` | НОВЫЙ | CONTRACT owner=CFG-06: 36 тестов (структура/снапшоты, escape+whitelist URL, негатив служебных полей, entity-safe чанки, доставка, утечка style_note байт-защищено, интеграция v2, OFF-паритет) |
| `services/factcheck_service.py` | точечно | `_temporal_verbalize` (зона 06A.5): удалён `style_note`-блок L753–769 (байты HEAD == deployed `29cc49ba`), payload → человекочитаемый дайджест, `speech_owner_block` — штатный шов последним блоком system (как Stage-2/одиночный путь); хелперы `_human_factual_verdict`/`_human_temporal_status`/`_human_evaluated_period` на уровне модуля |
| `services/factcheck_orchestrator.py` | анкор | ТОЛЬКО стадия 6→7: `build_presentation` → `render_factcheck(presentation, verdict)` → `deliver_factcheck(...)`; cache-hit (`already_delivered`) renderer не трогает; импорты — ленивые отдельные строки |

## 2. Рендер-механика (детерминированная, без LLM)

1. **Вердикт**: enum `CheckedVerdict.factual_verdict` → человеческая фраза
   (`supported→«Подтверждается»`, `refuted→«Не подтверждается»`,
   `mixed→«Подтверждается частично»`,
   `insufficient_evidence→«Недостаточно данных для проверки»`) — bold
   заголовком, без маркеров/emoji. Enum отсутствует/неизвестен → заголовка
   НЕТ (renderer не выдумывает вердикт — инвариант W3 «Writer/Renderer не
   меняют факты»).
2. **2–4 пункта сути**: предложения текста вербализатора → ≤4 ПОДРЯД идущих
   групп (порядок и состав 1:1, ничего не выбрасывается); 1 предложение →
   один абзац без списка.
3. **Ссылки**: только `presentation.links` (= `EvidenceMap.links()` текущего
   прогона); scheme-whitelist http/https, дедуп, href экранируется,
   label = домен без www; в видимом тексте полного URL нет.
4. **Честное ограничение (CFG-06.B)**: evidence-refs есть, а URL нет →
   строка «Первоисточники в этот раз открыть не удалось…»; refs нет →
   ограничение не заявляется; `presentation.notice` → `<i>`-строка.
5. **Экранирование**: весь пользовательский текст `html.escape`; сырой тег
   из вердикта/URL в разметку не попадает (тест-инъекция).
6. **Доставка**: СУЩЕСТВУЮЩИЙ `send_chunked_reply(parse_mode="HTML")`
   (общая функция НЕ менялась); pre-split `split_entity_safe` — теги не
   пересекают границу части, каждая ≤ 4096, reply только у первой части;
   `TelegramBadRequest` парсинга → деградация ТОЛЬКО сломанного чанка в
   plain; без parse_mode — текст как есть (внутренний чанкер).

## 3. Утечка «период проверки (unknown)»: было/стало байтами

Был (HEAD `9f37c15a` → `29cc49ba`, user-payload вербализатора; совпадает с
w0-trace probe 06A.5):

```
ВЕРДИКТ (JSON):
{"verdict": "refuted", "temporal_status": "unknown", "evaluated_period": {"from": null, "to": null, "precision": "unknown"}, "assessment_mode": "contextual", "as_of": 1760900000, "uncertainty": {"dates_unresolved": "дата публикации оригинала не определена — временная оценка ограничена"}, "parts": [], "claim": "…", "style_note": "Обязательно сохрани в ответе: период проверки (unknown), …"}
```

Стал (тот же fixture-вердикт):

```
ВЕРДИКТ (JSON):
{"verdict": "доступные данные утверждение не подтверждают", "freshness": "свежесть данных определить не удалось", "caveats": ["дата публикации оригинала не определена — временная оценка ограничена"], "parts": [], "claim": "…"}
```

- `style_note`/«период проверки (unknown)»/`precision`/`as_of`/
  enum-статусы — мимо payload; unknown → человеческие слова; даты периода —
  по-человечески (`с 15.06.2025 по 16.06.2025`), дат нет → ключа нет.
- Раскладка остального текста сохранена: обёртка `ВЕРДИКТ (JSON):\n` +
  `json.dumps(..., ensure_ascii=False)`, порядок человекочитаемых ключей,
  байты `fallback_note` — байт-защита снапшот-тестом
  (`test_payload_layout_bytes_snapshot`, `test_fallback_note_bytes_preserved`).
- `speech_owner_block(env.chat_id)` добавлен временному вербализатору
  (P0 UNIFIED-CORE): блок пуст → system байт-в-байт прежний
  (`test_owner_block_empty_is_byte_parity`); непустой → последним блоком.
- Байты старого блока в исходнике отсутствуют
  (`test_old_bytes_absent_from_source` против w0-trace probe 06A.5).

## 4. Тесты (CONTRACT owner=CFG-06)

| Набор | Результат |
|---|---|
| `tests/test_factcheck_renderer_cfg06.py` (новый, 36) | 36 passed |
| `tests/test_factcheck_orchestrator_cfg06.py` (W3 фриз+маршруты) | 16 passed |
| `tests/test_unified_core_route_coverage.py` (route-coverage, швы speech_owner_block) | 18 passed |
| `tests/test_factcheck_planner_cfg06.py` (W4) | 11/12 — см. §6 join |
| `tests/test_factcheck_service.py`, `test_factcheck_handlers.py`, `test_factcheck_gate_cfg06.py`, `test_factcheck_context_cfg06.py`, `test_factcheck_two_call_round1022.py`, `test_factcheck_prompts.py`, grounding/tools-раунды | passed |
| `tests/test_outgoing_guard_round1022.py` | 2 FAIL — pre-existing: `ImportError: InputRichMessageMedia from aiogram.types` (дрейф окружения aiogram, вне скоупа W5; файлы send-точек W5 не трогал) |

Ключевые негативы: HTML-инъекция не проходит; служебные поля
(1760900000/fsg1/temporal_fallback_mode/refuted/…) в разметке отсутствуют;
URL только как href; javascript:/ftp: отброшены; теги не рвутся по чанкам;
OFF-паритет: `handlers/factcheck.py` renderer не импортирует (прод-путь
2.58.98 не меняется), renderer вызывается только внутри v2-оркестратора.

## 5. Обновлённый тест W3 (сознательно, 1 утверждение)

`test_factcheck_orchestrator_cfg06.py::test_envelope_branch_cache_and_links`
— старое `assert "example.org" not in bot.sent[0]["text"]` фиксировало
до-W5 plain-доставку (комментарий теста сам говорил «W5 рендерит ссылки»).
Заменено на W5-контракт: URL из EvidenceMap — ровно 1 раз, только как
`href="…"`, в видимом тексте (`visible_text`) полного URL нет. Интент
теста («URL не гуляет по тексту») сохранён и усилен.

## 6. Что осталось join/W6

1. **Join-конфликт W4 (единственный)**:
   `tests/test_factcheck_planner_cfg06.py::TestOrchestratorAnchor::`
   `test_legacy_branch_evidence_filled_args_parity`, строка ~316:
   `assert "example.org" not in bot.sent[0]["text"]` — фиксирует pre-W5
   plain-доставку. Их FakeAggregator отдаёт `https://example.org/meteo`,
   W4 сам наполняет EvidenceMap legacy-ветки → W5-renderer рендерит ссылку
   (корректное поведение §W5). Минимальный патч (у них же комментарий
   «ссылки не публикуются до renderer W5»):
   `assert 'href="https://example.org/meteo"' in bot.sent[0]["text"]`
   + проверка `visible_text` без URL (по образцу правки из §5).
   Файл W4 не трогал (дисциплина скоупа).
2. **W6-наблюдение**: envelope cache-hit ветка (`_run_envelope_branch`)
   отвечает plain `_reply` мимо renderer (уже ответившая ветка,
   `already_delivered=True` — рендер пропущен осознанно); унификация
   доставки кеш-хитов — на W6 (наблюдаемость/кеш).
3. `prompt_style_blocks` factcheck-канал («text-only plain» в каноне) не
   тронут — LLM по-прежнему не генерирует HTML, разметку добавляет только
   renderer; жанровый контракт канона — по плану §W5 отдельным шагом
   (`factcheck_prompts`/`negative_constraints`), в бриф лейна не входило.
4. Live-проверка 06E.4/06G.8 (жирный/список/кликабельные ссылки на
   мобильном+десктопе) — владельцу, опционально по правилу
   `owner_live_checks`; агентская часть (unit/интеграция с parse_mode)
   покрыта.

## 7. Артефакты

- Код: см. §1. Изменённые tracked-файлы: `services/factcheck_service.py`.
- Коммит НЕ выполнялся (по брифу), рабочее дерево — кандидат лейна.
- Пруф запусков: настоящая сводка; RED-этап для утечки — w0-audit §3.1
  (байты L753–758 на deployed) + `test_old_bytes_absent_from_source`.
