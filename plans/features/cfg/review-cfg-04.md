# REVIEW-CFG-04 — независимое ревью мобильных форм MiniApp

| Поле | Значение |
|---|---|
| Кандидат | uncommitted поверх `7a3c1f92`: `web/app.js` `8850944597…`, `web/index.html` `528f358a65…`, `web/static/app.css` `6b5ca0cc1d…`, `tests/test_cfg04_forms_contract.py` `7cf6681c25…`, `tests/js/cfg04_forms_contract_test.js` `b2cd731dcc…`, `tools/ui_cfg04_forms_e2e.py` `ed66da5b30…` — все sha256_12 совпали; `git log 7a3c1f92..HEAD -- web/ tests/js` пуст |
| Вердикт | **Approved** — оба save-CTA сведены к одному, safe-area/клавиатура/последнее поле/44px/tech-key/поворот подтверждены собственными прогонами; live-строки → RFL, D.4 — PENDING_OWNER_E2E (PET) |

## 1. B.1 — один сценарий сохранения
* Чип шапки — `<div role="status" aria-live="polite" data-save-indicator>`, без `@click`; computed `headerSaveChip` → `actionable:false`, подпись «не сохранено», title со счётчиком. Единственная CTA — `<sticky-save>` (`@click="save"` → `saveModalEdits`); в разметке `@click="saveModalEdits()"` нет. Контрактные тесты `TestOneSaveFlow` (4) + JS §1; e2e CTA **2→1** на всех 7 viewport; мой Browser Use: чип DIV/role=status, ровно одна кнопка «Сохранить изменения» (44 px).
* `_dirtyLeaveGuard` жив: мой независимый Playwright-прогон — native confirm «Есть несохранённые изменения (1) для «Audit Chat». Уйти со страницы и потерять их? (Изменения можно сохранить кнопкой «Сохранить изменения»)»; отказ → маршрут `#/memory/rag` остаётся, согласие → `#/oversight`. Сохранение ждёт ack, baseline сдвигается только при отсутствии провалов, «Отмена» возвращает только текущую форму — проверено тестами `TestDirtySaveContract` (читал утверждения, не тавтологии).

## 2. B.2 — safe-area/клавиатура
* `padding-bottom: calc(.45rem + max(env(safe-area-inset-bottom), var(--tg-safe-area-inset-bottom), var(--tg-content-safe-area-inset-bottom)))` — safe-area учтена **ровно один раз** (тест `count('env(...') == 1`); `.modal-actions` safe-area не добавляет (align-items:flex-end + min-height:44); `.modal-card` вычитает только `--kb-offset`; `bottom: var(--kb-offset, 0px)`; `_syncKeyboardOffset` всегда пересчитывает offset от visualViewport (0 при закрытой клавиатуре — стейл невозможен). Числа: pad 7.2→63.2 (портрет)/31.2 (ландшафт); kb panel bottom 288/388/492… в видимой области.

## 3. B.3 — последнее поле
* `_syncPanelHeight` (+`_watchPanel`/ResizeObserver) пишет `--sticky-save-h` = max фактической высоты видимых панелей; `scroll-padding-bottom` и `.field` scroll-margin = `--sticky-save-h + --kb-offset + 4px`; M-1 (`padding-bottom:0`) сохранён (тест). 320: panel h **100→168.4** (перенос), кнопки целиком 44 px, фикс. высоты нет; overlap **−28.2→−161.9**. Мой Browser Use 320: «Отмена» строка 1, «Сохранить изменения» строка 2 целиком; `scrollWidth==innerWidth`.

## 4. C.2/C.3/A.1
* Toggle 44×24→44×44, «Сохранить»/«Отмена» 37.6/38→44 (e2e, все viewport).
* `<tech-key>`: **18** тегов, `font-mono truncate` = 0; компонент с `:title`, `aria-expanded`, copy (Clipboard API + execCommand-фолбэк через скрытую textarea, `data-copied`, сброс 1.5 с); русские title/description/value не заменены.
* A.1: `_captureEditViewport`/`_restoreEditViewport`/`_preserveOnViewportChange` (вызов из `_onResize`); снимается фактический скроллер, активный `data-cfg-key`, выделение; фокус — best effort без фейка; конфиг на resize не перезагружается (тест). E2E: scroll **220→220**, active key сохранён, dirty/hash сохранены; `data-cfg-key` ×29.

## 5. Не тронуто / пере-пины
* CSS-хунки только в зонах sticky-save/modal/chip/toggle/tech-key; навигация, fullscreen, логотип, glass-токены не менялись (тесты `TestProtectedSurfaces`; в диффе glass — только существующий `--glass-border-color` в hover); `services/`, `web/api/`, `param_catalog.py` — статус пуст (Δ каталога 0, DDL 0).
* Пере-пины (3 файла): asap8_d1213 (роль чипа L157), round1020 (bottom=kb L158), round1021 (scroll-padding от токена L159) — осознанные, со ссылкой на источник; старые утверждения сохранены, ослабления нет.

## 6. Evidence — мои перепроверки
* RED: **13 failed / 16 passed** + JS AssertionError (лог); GREEN: `test_cfg04_forms_contract.py` — **29 passed**, JS — `CFG04-FORMS-OK`; профильный набор (8 файлов) — **202 passed**; round1020 — 28; ASAP8/JS-UNIT — OK.
* E2E after — **failures=0, console_errors=0**, повторный прогон evidence не изменил (0 файлов); e2e-log sha `after.json`/`baseline.json`/tool совпадают; скрины before/after (390, 320) и Browser Use-рендер осмотрел: до — две save-CTA и голые ключи; после — нейтральный индикатор, одна CTA, ключи с «копировать», перенос панели на 320.
* Числа matrix сверены (≥5): CTA 2→1; pad 7.2→63.2/31.2; panel h 100→168.4 / 54.4→84.4 / 116.4; overlap −28.2→−161.9; key False→True; поворот 220→0 стало 220; failures 85→0; console 0.

## 7. Бласт
* Профильные 202; широкий `webapp/ui/speech/soul1` — мой прогон **2695 passed / 0 failed** (в лейне 2688 — дрейф счёта коллекции, падений нет); JS-свип `test_webapp_js_unit` — 38; speech-savebar e2e — **failures=0, POST=22**.
* Широкая матрица shell/glass — **свежие прогоны на точном кандидате и на base `7a3c1f92`**: 178/178, `main-only=0`, `base-only=0`; спот 4 имён совпал (bottom-nav 76/76, touch 40px 79/79, glass tier 10/10, `--glass-displace` 10/10). Артефакты лейна восстановлены после прогона.

## 8. Дисциплина и замечания
* Дельта == заявленные 6 файлов + 3 новых + evidence; чужой WIP не смешан; «VERIFIED» лейн не объявлял; D.4 — честный `PENDING_OWNER_E2E` (PET: необязательная обратная связь, не блокер).
* **N1 (note, не блокер):** поворот при открытой модалке модуля: value/dirty/hash/active сохраняются, но `modal-body.scrollTop` после поворота уходит к сфокусированному полю (120→1272), а не держит пиксель; на config-странице скролл сохраняется ровно (220→220). Живой сценарий D.5 — postdeploy, там и наблюдать.
* **N2 (note):** в `coverage.md` строка D.5 описывает e2e как «dirty `limits.chat_burst_limit` в модалке» — фактически e2e-фолбэк дёртил `limits.chat_branch_context_hops` (ключа `chat_burst_limit` в модалке нет; так же и в baseline). D.5 остаётся PENDING_POSTDEPLOY; в postdeploy-сценарии целиться в реальный путь/ключ.

## Леджер (20 строк CFG-04; гейт: `scoped=20 errors=21` — 20 PENDING + rolling-candidate, pre-binding)
* **Код/review → VERIFIED (8):** `ADD-1.C5`, `CFG-04B.4`, `CFG-04B.5`, `CFG-04C.3`, `CFG-04D.2`, `CFG-04D.3`, `ADD-1.T4`, `CFG-04.F`.
* **Live (preprod/postdeploy) → READY_FOR_LIVE (11):** `CFG-04B.1`, `CFG-04B.2`, `CFG-04B.3`, `CFG-04C.1`, `CFG-04C.2`, `CFG-04C.4`, `CFG-04C.5`, `CFG-04D.1`, `CFG-04D.5`, `CFG-04A.1`, `CFG-04.B`.
* **PENDING_OWNER_E2E (1):** `CFG-04D.4` (реальный Telegram Android/Desktop; PET — не блокирующий gate, автоматические проверки выполнены).

## Итог
Мобильные формы получили один понятный save-сценарий, честный индикатор, корректные safe-area/клавиатуру/последнее поле, читаемый и копируемый технический ключ, 44 px зоны и сохранение контекста при повороте — без изменения дизайна, каталога и backend. Блокеров нет. **Approved**; live-строки закрываются на preprod/postdeploy, D.4 — по желанию владельца.
