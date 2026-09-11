# ADR-002 — Паритет Material-иконок (`ICONS`) и субсета шрифта

- **Статус:** принято (@Architect, раунд 10.8)
- **Контекст:** иконки адресуются PUA-кодпоинтами (`ICONS` в `web/app.js:207-228`),
  субсет собирается оффлайн `scripts/build_font_subset.py` из GSUB-лигатур исходного шрифта.
  Раунд 10.8 добавляет 17 новых иконок (emoji→Material) → нужен паритет «JS-карта ↔ список
  билд-скрипта ↔ cmap`. Scanner R10.7-4 показал, что `test_font_subset` проверял наличие
  кода в JS, а не глиф в cmap — потенциальный tofu-риск.

## Решение

1. **Единый набор имён:** множество ключей `ICONS` == множество `ICON_NAMES`
   (`build_font_subset.py`) — точное равенство, без мёртвых и без пропущенных.
2. **Коды — из шрифта, не «на глаз»:** `derive_pua_codepoints` (GSUB reverse-cmap) — источник
   PUA; билд-скрипт экспортирует `build/icon_codepoints.json` (`{name: U+XXXX}`) для переноса
   в `ICONS`.
3. **Идемпотентность с учётом списка иконок:** маркер `build/font_source.sha256` должен
   зависеть и от `ICON_NAMES` (иначе правка списка молча пропускает пересборку).
4. **Тест-паритет (R10.7-4):** `test_font_subset` парсит `ICONS` из `app.js` и `ICON_NAMES`
   из билд-скрипта (равенство), плюс `fontTools`-проверка каждого PUA-кода в cmap WOFF2.
5. **Сборка оффлайн, build-time only:** `fontTools`/`brotli` — из `scripts/requirements-font.txt`,
   в runtime `requirements.txt` не входят. Субсет `< 60 КБ`; исходник 5.11 МиБ gitignored.

## Последствия

- Добавление/удаление иконки требует синхронной правки трёх мест: `ICONS`, `ICON_NAMES`, пересборка.
- Тест ловит drift и tofu до деплоя; `build/icon_codepoints.json` — вспомогательный (gitignored).
- В `ICON_NAMES` удаляются 6 мёртвых имён 10.7 (account_balance_wallet, speed, stop_circle,
  theater_comedy, toggle_off, toggle_on); итог 37 имён.
