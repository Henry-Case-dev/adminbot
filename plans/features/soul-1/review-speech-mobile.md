# SOUL-1 — REV-SPEECH-MOBILE: независимое ревью фикса «Речь и характер» на мобильном (18.10.2026)

**Вердикт: Approved** — фикс минимален, воспроизведён (RED→GREEN) и пригоден к упаковке; блокирующих находок нет. Родитель не закрывается: живая доступность на проде — после деплоя (READY_FOR_LIVE, §4). Условия упаковки — §4, незакрытые ниточки (не блокеры) — §5.

## Привязка

| Поле | Значение |
|---|---|
| База / HEAD на момент ревью | master `10c15cf5` (web-дерево байт-идентично `669debfa`: после CFG-02A — только docs-коммиты; мой RED-архив снят через `git archive HEAD web` и эквивалентен) |
| Кандидат | HEAD + uncommitted: `web/app.js` sha256 `4078B1997AA2210F023DD5423375CF64D71FC3A08D5DE4460CB04B54B992A522`, `web/index.html` `F79F9AD5845782C4833F63F102ABD371D1FB48C6F660C65A3E587CABAC825125`, `web/static/app.css` `D6B848CDECD0A162B786CD76D3CC99C6EB66397A699A635C69918987AC0D779D` |
| Дифф | `git diff --numstat` = **+16/+15/+34, −0**; `git diff --check` чисто (exit 0) |
| Новые тесты (untracked) | `tests/ui_speech_mobile_entry_e2e.py` `ECCF7509C0A78109…`, `tests/test_speech_mobile_entry_contract.py` `3E444435D9E7D2AF…` |
| Эвиденс лейна | `plans/features/soul-1/evidence/speech-mobile-fix/**` (README §0–§7; before/after/green/dom, red/green логи) |

Апрув привязан к хэшам выше: любая последующая правка этих файлов аннулирует его.

## 1. Дифф/минимальность — VERIFIED (мой осмотр + прогоны)

- `web/app.js` (+16): computed `hubSpeechEntry` (стр. 2944) = `route === '#/ai' && !!hubCards && canViewTab('speech')` — та же функция прав, что у persona-двери (new прав нет). Условие зеркально шаблону хаба (`v-if="hubCards"`) — расхождения не даёт.
- `web/index.html` (+15): кнопка `[data-speech-hub-entry]` (стр. 455–469) первой строкой `.hub-grid`, `navigateTo('#/ai/speech')`. **HUBS_V2 не тронут** (в diff отсутствует): 5 карточек, порядок и состав совпали (e2e + мои прогоны). Persona-дверь `[data-speech-entry]` (стр. 10030) жива.
- `web/static/app.css` (+34, стр. 4485–4516): `.speech-hub-entry`; `min-height: 56px`; **не стекло** — класс отсутствует в glass-селекторах (`glass-refraction.js::SURFACE_SELECTOR`, `app.js::_lgGlassSelector`, glass-set app.css); в DOM нет `data-glass*`; computed `backdrop-filter: none`, фон `rgba(56,189,248,.1)` на существующих токенах.
- Мои замеры (реальный Chromium, интегрированное дерево): высота входа **155/134/71 px** при 320/390/1280 (≥56); page overflow **0** на всех ширинах; `entry.scrollWidth == clientWidth` (внутреннего клипа нет); `right ≤ vw`; CTA «Открыть →» видим; глиф `0xE745` отрисован (22px).

## 2. Воспроизведение — VERIFIED (мои прогоны)

- **RED (дерево без фикса):** независимый webroot `git archive HEAD web` → `ui_speech_mobile_entry_e2e.py --webroot …` → **3/3 FAIL** «НЕТ явного входа [data-speech-hub-entry] на хабе „ИИ“» (320/390/1280).
- **GREEN (кандидат):** тот же e2e на рабочем дереве → **failures=0**; тап по входу → `#/ai/speech`; `.speech-screen` + секции (≥3); персона-дверь видима; 5 карточек хаба и их порядок сохранены; overflow 0.
- **W6 deep e2e (мой повтор, свежая фикстура `w6-fixture-current.json` из реального `web/api/speech.py`):** `failures=0, POST=16, shots=94` (8 вьюпортов + interactions) — совпадает с заявленным.
- **Реальные Chrome-кадры:** BEFORE `before/bu_hub_no_entry_390.png` (5 карточек, двери нет), AFTER `after/bu_hub_entry_390.png` — открыты и оценены; совпадают с моими Playwright-скринами (`shots_mine/hub_{320,390,1280}.png`, `speech_{390,1280}`, `persona_390`). BEFORE соответствует жалобе владельца, AFTER — строка-вход первой на первом экране.

## 3. Глиф (REFINE) — VERIFIED

- `record_voice_over` в `ICONS` никогда не было (а `edit_note: '\ue745'`, app.js:377, есть); на пре-REFINE базе `2bc13f44` глиф двери — **0×0** (мой замер), после фикса — виден (22/24px).
- Все три двери «Речи и характера» — `edit_note`: шапка экрана (index.html:7474), persona-карточка (10018), новая хаб-дверь (463). `record_voice_over` в `web/` — **0 вхождений** (остался только в тест-комментарии/фикстуре теста и workflow-нотах).
- **Интеграционный нюанс подтверждён:** строки 7474 и 10018 уже в HEAD под чужим коммитом `669debfa` (CFG-02A; blame подтверждён). В uncommitted-дифе их нет → при коммите фикса дублей/конфликта с CFG-02A не будет.

## 4. Наборы (мой повтор) — VERIFIED

| Проверка | Результат |
|---|---|
| `test_speech_mobile_entry_contract.py` | **6 passed** |
| + `test_soul1_w6_speech_ui.py` + `test_ia_inventory_round1025.py` | **35 passed** (6+22+7) |
| node `tests/js/*` (87 файлов) на интегрированном дереве | **87/87 OK** |
| `ui_asap8_w2_shell_e2e.py` | **W2-SHELL-E2E-OK**, `failed_checks {}`, `console_errors []` |
| `ui_win_glass_refraction_e2e.py` | **37/37** (21+4+10+2), WG-REFRACT-E2E-OK |
| Tier A/B (`refraction-tiera-verify-BASE/CANDIDATE`) | 45 FAIL-наборов **идентичны** (дельта 0; спот — сравнение файлов) |
| W6 deep e2e | §2 (мой прогон 0/16/94) |

Уточнение к README лейна §7: `round1024_image_module_test.js` на интегрированном дереве **зелёный** (CFG-02A обновил тест в `669debfa`) — тезис о RED устарел (nit, не блокер).

### Условия упаковки (обязательные, фикс не меняют)

1. Commit set = diff vs HEAD, **pathspec**: `web/app.js web/index.html web/static/app.css tests/ui_speech_mobile_entry_e2e.py tests/test_speech_mobile_entry_contract.py plans/features/soul-1/evidence/speech-mobile-fix` (эвиденс-каталог — прецедент соседних лейнов; минимум README + red/green логи + before/after-скрины).
2. Не включать: `AGENTS.md`, `plans/archive/**`, `plans/features/asap8-*/**`-эвиденсы, `owner_questions/runtime_task/workflow_state`, scratch/node_modules/`tools/_*` (шум параллельных лейнов и прогонов).
3. Перед коммитом: `git diff --cached --numstat` = **16/15/34** строго по web-файлам и проверка, что строки 7474/10018 **не** всплывают в диффе (они уже в HEAD — дублей быть не должно).
4. Порядок относительно CFG-02A: его переработка идёт (`10c15cf5`, Needs Fixes) и коснётся тех же web-файлов в других регионах (квоты). Текстуального пересечения нет; во избежание долгоживущего uncommitted-диффа на общих файлах — коммитить фикс отдельным pathspec-коммитом сразу, не дожидаясь CFG-02A.
5. Релиз (PET-режим, без канареек): включить в следующий релиз; после деплоя — живой мобильный чек (READY_FOR_LIVE): «Ещё» → «ИИ» → тап по строке → редакторы открываются и сохраняются на 320/390; откат — штатный (revert коммита/предыдущий релиз).

## 5. Ниточки (не блокеры)

1. **Леджер:** строка `SOUL-AMD.6.3` (L00105, slice W6) в `requirements-map-amendment.json` уже стоит `VERIFIED` на W6-эвиденсе — живой репорт владельца 18.10 это опроверг (дверь в persona-табе не закрывала путь «Ещё→ИИ»). После коммита фикса PM: добавить evidence-запись к L00105 (candidate = коммит фикса; ref на этот review + RED/GREEN). План-гейт карты сейчас: `inventory=66 manual=28 scoped=0 errors=0`, EXIT 0.
2. **Предсуществующее, вне мандата:** 8 из 10 иконок секций витрины (`tune, format_quote, theater_comedy, library_books, science, school, list_alt, fact_check` из `web/api/speech.py`) отсутствуют в `ICONS` → пустые глифы секций. На реальной фикстуре «сломанных квадратов» нет (проверено визуально); устранение = регенерация шрифт-сабсета/маппинг → backlog.
3. Nit: формулировка README лейна §7 про RED round1024 (см. §4).

## Ledger

| Пункт | Статус |
|---|---|
| 1. Дифф/минимальность: 16/15/34; HUBS_V2 не тронут; persona-дверь жива; не-стекло; ≥56px; overflow 0 | VERIFIED (мой осмотр, DOM и замеры) |
| 2. Воспроизведение: RED 3/3 на дереве без фикса; GREEN 0; клик→#/ai/speech; витрина; 5 карточек; persona | VERIFIED (мои прогоны; W6 deep 0/16/94) |
| 3. Глиф: ICONS без record_voice_over; три двери edit_note; 0 иных вхождений | VERIFIED |
| 4. Наборы: 6+35, node 87/87, shell OK, refraction 37/37, tier delta 0 | VERIFIED |
| 5. Упаковка: 2 строки в HEAD под `669debfa`, дублей нет, pathspec-план | VERIFIED (§4) |
| Живая доступность на проде (мобильный путь владельца) | READY_FOR_LIVE (post-deploy) |

**Итог:** Approved к упаковке и включению в следующий релиз; блокирующих находок нет; parent не DONE (живой мобильный чек — после деплоя).
