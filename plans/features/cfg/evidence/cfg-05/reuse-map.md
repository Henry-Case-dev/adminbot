# Reuse-map — U08 / SOUL-17 / WIN-GLASS для CFG-05

CFG-05 **ничего не реализует и не переизмеряет**. Ниже — что именно переиспользуется, с какими статусами, и что остаётся чужим долгом.

| Источник (владелец) | Артефакты evidence | Статус в своём пакете | Что делает CFG-05 | Чего CFG-05 не делает |
|---|---|---|---|---|
| **SOUL-17 / TIERA-STRONG** | `soul-1/glass-tiera-hotfix.md`; `soul-1/review-tiera.md` (**Approved**); `soul-1/review-tiera-strengthened.md` (**Approved**); `soul-1/evidence/glass-tiera/_strong_verify.json` (**77 pass / 1 fail**, fail = `modal-card@1440:lens_center_static` — задокументированное ограничение замера, не дефект); `_strong_visibility.json`; `_strong_legibility.json`; `_strong_webview.json`; `_strong_*.png` | Код и материал — reviewed/Approved; **SOUL-17.4** (реальный перф Android/Windows, reduced-motion, overdraw) — `READY_FOR_LIVE` | Сверяет, что блок `#lg-lens` в проде 2.58.97 **побайтово тот же** (6298 б, `5367ec45…`, `scale=32`), что и в отревьюенном кандидате; ссылается на 77/1 и фото-метрики как на готовое доказательство | Не переделывать карту, не гонять повторный A/B/perf, не объявлять `SOUL-17.4` закрытой |
| **U08 / W2-GLASS** | `asap8-v6-3-live-correction/w2-reports/W2-GLASS.md`; `w2-evidence-glass/ui-acceptance.md`; исторический `_ui_round1025_raw.json`/`UI_AUDIT_REPORT.md` | Исторические reviewed-артефакты; **карта U08 привязана к `0b7a0aca` (2.58.84)** и содержит bookkeeping-остаток: `REQ-U08`, `U08.3e`, `U08.5.4`, `REQ-U08-DOD`, `B10-R19` = `READY_FOR_LIVE`; `U08.4d`, `U08.5.1`, `REQ-U08-4` = `PENDING` | Переиспользует как слой доказательств и как **исторический baseline 178 замечаний** для регрессионной сверки | Не пересобирает U08-карту, не переписывает её строки, не выдаёт `READY_FOR_LIVE` за `VERIFIED` |
| **WIN-GLASS-P0** | `win-glass-hotfix/**`; `win-glass-hotfix/review-wg.md` (**Approved**: реализация+evidence; 16 VERIFIED / 7 `READY_FOR_LIVE`; живые пункты `PENDING_OWNER_E2E`) | Android-рефракция через `.lg-refract` — reviewed; живой WebView — `PENDING_OWNER_E2E` | Учитывает как часть задеплоенного стекла; `glass-refraction.js` в проде = git-блоб `0c57cc25…` (не менялся CFG-04) | Не меняет `glass-refraction.js`, не «улучшает» слой, не закрывает живые WG-пункты |
| **FS-HOTFIX 18.10** | `review-*`/release-записи SOUL/FS | reviewed | Считает fullscreen без стеклянной подложки легитимной дельтой | Не возвращает стекло на fullscreen |
| **Наблюдение владельца 18.10.2026** | `source-cfg-addendum.md` L183 (immutable source) | `OWNER_VISUAL_CONFIRMED` (без нового вопроса) | Цитирует факт: усиленное искажение отчётливо видно на реальной карточке «Бот» страницы «Статус»; платформа не названа | Не подменяет скриншот своим кадром, не расширяет наблюдение на другие клиенты/перф |
| **CFG-04** | `plans/features/cfg/evidence/cfg-04/**` (before/after кадры, `visual-check.md`, `matrix.md`), `evidence/release-25897/**` | Reviewed/Approved, выкачен 2.58.97 | Потребляет как вход регрессии: 178/178, блоб-равенство линзы/фона, дифф-скан | Не чинит CFG-04-дефекты здесь; регрессия → возврат в CFG-04 |

## Честные остатки (не закрываются CFG-05)

1. `SOUL-17.4` — `READY_FOR_LIVE` (перф реальных устройств/reduced-motion/overdraw).
2. U08-карта — три `PENDING` + пять `READY_FOR_LIVE` (bookkeeping старой карты на `0b7a0aca`), не отсутствие кода.
3. WIN-GLASS — живые WebView-пункты `PENDING_OWNER_E2E`.
4. CFG-04 `D.4` — `PENDING_OWNER_E2E` (необязательная обратная связь владельца по PET, не блокер).
5. Оптическая рефракция в headless-пробе — Tier B (см. README §7); оптика подтверждена SOUL-17/U08, не этим пакетом.

## Почему это не «второй SOUL-1»

CFG-05 не добавляет ни строки CSS/JS/HTML и ни одного теста: единственный дифф слайса — `plans/features/cfg/evidence/cfg-05/**` (`diff-guard.txt`). Материал стекла в проде — тот же, что принят SOUL-17 (блоб-равенство), фон — тот же, что защищён ADD-1.C6.
