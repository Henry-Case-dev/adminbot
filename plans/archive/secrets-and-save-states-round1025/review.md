# F9 `secrets-and-save-states-round1025` — REVIEW (T-3054 @Reviewer, Step 5, 23.09.2026)

**Feature-ID:** F9 / `secrets-and-save-states-round1025`
**Status:** **Approved** (итерация 2)
**Baseline:** HEAD `93432c0` (тег `pre-round1025-f9`), `APP_VERSION` 2.58.16, правки не закоммичены (focused diff-based).
**Итерация 1:** Needs Fixes — H-F9S-1 (High) + L-F9S-1..4. **Итерация 2:** все закрыты, новых блокеров нет.

## Итог итерации 2
| ID (итер.1) | Sev | Статус | Доказательство |
|---|---|---|---|
| H-F9S-1 | High | **FIXED** | `web/app.js:7998-7999` — image-ветка `DELETE /api/config/keys/own/{key}` теперь `{ method:'DELETE', global:true }` (паритет `saveProviderSecret:3864`, ADR-1025-22 D2). Legacy-POST тоже `global:true` (:8017); non-image → F0 `persistItems` global. Тест `round1025_f9_secret_field_test.js:238` ассертит `opts.global===true` (снятие флага → red). Проверено трассировкой `api():3295` → без `global` подставляется `X-Chat-Id`. |
| L-F9S-1 | Low | **FIXED** | Единый источник маски: `maskText` (`web/app.js:11466-11468`) → `secretDisplayOf(...)`; мёртвый `blockSecretText` удалён (grep по `web/**`, `tests/**` — 0 ссылок). |
| L-F9S-2 | Low | **FIXED** | `stateLabel` (`web/app.js:11397-11407`) — `saved` убран; после успеха F0 → `clean`, «Сохранено» — тост F0. Тест `round1025_f9_savebar_visual_test.js:184-185` теперь ассертит `saved → ''` (не мёртвая ветка). |
| L-F9S-3 | Low | **FIXED** | `tests/test_round1025_f8_registry.py:102-110` — строго `FIXTURE["app_version"]=="2.58.15"` **и** `APP_VERSION=="2.58.16"` (без `>=`). |
| L-F9S-4 | Low | **FIXED** | `evidence.md:25/53` — `f8_baseline.json` явно помечен «не менялся — исторический baseline 2.58.15». |

## Воспроизведённые проверки (итерация 2)
| Проверка | Результат |
|---|---|
| `node --check web/app.js`, `web/static/telegram-init.js` | OK |
| JS-тесты `tests/js/*.js` | **40 / 40 OK** |
| `pytest tests/test_webapp_f9_round1025.py tests/test_round1025_f8_registry.py` | **51 passed** (F9 22 + F8 29) |
| `pytest -q` (полный) | **8421 passed / 5 failed / 1 skipped** — те же env-`rich`/`ImportError` (`test_outgoing_guard_round1022`, `test_summary_cover_round1023`), `services/**` не тронут, воспроизводятся без F9 |
| Playwright-матрица `tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов) |
| `git diff --check` | exit 0 |
| R17-скан (`keyDrafts[...]=SECRET_MASK`, `value:SECRET_MASK`, raw key/DSN) | 0 находок |
| Guard'ы | целы: `dirtyKeyItems:2822`, `saveKeyItem:7947`, `saveBlock:6035`, `testBlock:5969`, `testField:6001` |
| F0-движок | не переписан: `persistItems:7641` ×1, `notify:7588` ×1 |
| Каталог / секреты | REGISTRY 459, GROUPS 98, секреты 28 = 20 `keys` + 8 `None`; `APP_VERSION` 2.58.16; Δ DDL=0, Δ каталога=0 |

## Сохранённые требования
- §50/R17: маска — display (`div`), `input` всегда пуст; маска/композит не уходит в API (JS-тест: 0 запросов); вставка маски → отказ; пустое поле не удаляет; «Заменить» → POST реального ключа; 28/28 покрытие (20 UI + 8 env-only).
- §69/§78: `visualViewport → --kb-offset + scrollIntoView`, safe-area ровно один раз, SaveBar вне `.modal-body`, notify/«Подробнее» — reuse F0.
- §51: только отображение состояний, «Сохранено» после сервера; 409/412 не дублируются.
- Маркер-тесты UPD3/R31/F8 обновлены атомарно без ослабления (итер.1 исправлена L-F9S-3).

## Новые находки
- **Блокирующих нет.** Info: `evidence.md:25` в списке маркер-правок упоминает `tests/test_webapp_ui_rework_round1020.py` (в рабочем дереве не изменён) — документационный нит, не код, вне scope F9.

## Недоступные проверки (PENDING OWNER VERIFICATION)
- Реальный TMA/WebView: клавиатура/`visualViewport`/safe-area — Playwright-эмуляция успешна, live-гейт не заявляю пройденным.
- 5 env-падений `pytest` — окружение (`rich`), не F9.

## Handoff
@Orchestrator: F9 **Approved** (итер.2). Далее по `tasks.md`: T-3056 @Architect (Merge), T-3057 @PM (архивация), T-3058/T-3059 @DevOps (deploy + live-гейт PENDING OWNER), T-3060 @Memory, T-3061/T-3062 @PM.
