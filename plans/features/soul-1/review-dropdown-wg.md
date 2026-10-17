# SOUL-1 — REV-DROPDOWN-WG: независимое ревью фикса мобильного dropdown «Аналитики» (18.10.2026)

**Вердикт: Approved.** Кандидат — незакоммиченное состояние master `dcea204b` + **ровно 2 файла** (`web/static/app.css`, `tests/js/asap8_w2_shell_mobile_nav_test.js`); правка минимальна, A/B reproduced end-to-end (RED-сигнатура точь-в-точь → GREEN с реальным тапом), зуб теста доказан, полосы зелёные, риск-нота записана. Условия только по дисциплине коммита (§4).

## Привязка

| Поле | Значение |
|---|---|
| База | master `dcea204b` (и та же база у worktrees `dropdown-wg-before`, `dropdown-wg-fix`) |
| Кандидат | base + `web/static/app.css` sha256 `D700DF753D6D897FC3BD51334BD57489507674E8348C057AF77B7FAAF4E2DD2B` + тест `62F7C2C4B167AAD8F242D9C83E02F8E752D53A2765161E09FFD41264477A3BBC` (идентичны в главном дереве и fix-worktree — no-index diff пуст) |
| Переносимость | базовые версии обоих файлов байт-идентичны релиз-линии `d5191450` (`git diff` пусто) ⇒ правка переносима 1:1 |
| Пробы/evidence | мои: `dropdown-wg/ev/probe_rev2-{before-390,fix-390,fix-667}.json` + прогоны тулов; лейна: `plans/features/soul-1/evidence/dropdown-wg-fix-25886/**` |

## 1. Дифф — ровно 2 файла, минимально

- `web/static/app.css`: **+1 функциональная строка** `.oversight-tabs.oversight-dd-open { overflow: visible !important; }` (стр. 1430) + расширенный комментарий (итог 9+/1−). Размещена рядом с существующим `.oversight-tabs.oversight-dd-open { position: relative; z-index: 45; }` в том же (внешнем) контексте; класс ставится только мобильным тогглом (`web/index.html:4293` `:class="{ 'oversight-dd-open': oversightMobileOpen }"` на карточке `.oversight-tabs`), других состояний/селекторов не задевает; при закрытии правило не действует (inline-клип возвращается сам).
- `tests/js/asap8_w2_shell_mobile_nav_test.js`: +U02.4-ассерт (8 строк) + `TEST-LIFECYCLE: …; REGRESSION owner=DROPDOWN-WG` — по конвенции; ассерт статический (наличие правила), поведение покрыто функциональным e2e (двухслойно).
- «Лишнее» в worktree (PNG/JSON `w2-evidence-shell`, `fs-hotfix/e2e-w2`, `win-glass e2e`) — **шум e2e-прогонов** (тулы пишут артефакты в дерево), не часть фикса; см. §4.

## 2. A/B-репро (мои прогоны, независимо)

- **BEFORE** (`dropdown-wg-before`, без CSS): `ui_asap8_w2_shell_e2e.py` → exit 1 с сигнатурой `<div … data-refract-layer="on" data-glass-reason="refract-layer" class="card glass-panel p-4 col-span-full">… intercepts pointer events` — точное совпадение с заявленной. Probe 390×844: hit = `DIV.card glass-panel p-4 col-span-full`, тап НЕ переходит (`#/oversight`).
- **FIX**: shell-e2e → **W2-SHELL-E2E-OK**, `failed_checks {}`, `console_errors []`; в артефакте — `u02:hashTabMemory=True`, `u02:триггерОбновился=True`, `u02:панельЗакрылась=True` и др. Probe 390×844 → hit = `BUTTON.oversight-mobile-option`, тап → `#/oversight?tab=memory`; probe 667×375 → то же. Мои скриншоты: панель отрисована поверх карточек (before — панель не видна).
- Causal-подтверждение лейна (in-situ CSS-инъекция `overflow: visible !important` на прод-байтах, `css_injected=true`): hit=опция, тап=`tab=memory` ⇒ блокировал именно клип, не z-order (JSON перепроверен). Реаль-Chrome кадр (лейн, Browser Use): панель поверх карточек, 390×844.

## 3. Наборы (мой повтор на fix-worktree)

| Проверка | Результат |
|---|---|
| node `tests/js/*` (87 файлов) | **87/87 OK** |
| Зуб U02.4 | before-worktree: `AssertionError: U02.4: открытый dropdown не обрезается поверхностью рефракции`; fix: `W2-SHELL-UNIT-OK` |
| `ui_win_glass_refraction_e2e.py` | **37/37** (A21/C4/B10/D2), WG-REFRACT-E2E-OK |
| `ui_asap8_w2_fullscreen_e2e.py` | **12/12 PASS** |
| frozen-адаптер (base dcea204b) | **RESULT OK**: изменён ровно `web/static/app.css`; ассеты/polygon-блобы/якоря/LF/WG-маркеры сохранены |

Дополнительно: `web/app.js`, `web/static/glass-refraction.js`, `web/index.html`, `web/static/fullscreen-policy.js` в диффе отсутствуют (Tier/бюджеты/probe-логика не тронуты).

## 4. Риск-нота и пакетинг коммита

- Риск-нота **записана** (README §6 + комментарии в css/тесте): фикс точечный, действует только в открытом состоянии; общий класс «popup внутри клипа refraction-поверхности» остаётся риском для будущих списков внутри glass-карточек; полигон/Tier/бюджеты не тронуты (frozen OK + refraction 37/37).
- Обязательные условия коммита (не меняют фикс): включать **только 2 файла** + новый untracked-каталог `plans/features/soul-1/evidence/dropdown-wg-fix-25886/`; артефакт-шум e2e-прогонов не коммитить (вернуть `git checkout --`); апрув привязан к sha256 файлов из «Привязки» (любая правка после — новое ревью).
- Дальше: после коммита фикс можно включать в мини-релиз **2.58.87** (по плану оркестратора; условия остальных пунктов того релиза — из REV-REL-SOUL), либо отдельным релизом; PET — без канареек.

## Ledger

| Пункт | Статус |
|---|---|
| 1. Дифф: ровно 2 файла, минимальность, только `oversight-dd-open`, конвенция маркера | VERIFIED (мой осмотр + sha) |
| 2. A/B: RED-сигнатура / GREEN + тапы (390×844, 667×375) | VERIFIED (мои прогоны; сигнатура точная) |
| 3. Наборы: node 87/87 (зуб), refraction 37/37, FS 12/12, frozen OK | VERIFIED (мой повтор) |
| 4. Риск-нота и неприкосновенность полигона/Tier/бюджетов | VERIFIED (README §6; frozen; дифф без слоя) |

**Итог:** Approved; регрессия WIN-GLASS-P0 (2.58.85) устранена точечно, подтверждено независимыми A/B-прогонами и всеми полосами; блокирующих находок нет.
