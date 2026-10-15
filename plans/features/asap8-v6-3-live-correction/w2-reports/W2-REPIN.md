# W2-REPIN — санкционированный re-pin 23 UI canon-pytest после Wave 2

Лейн: W2-REPIN · HEAD 4b64b38 + незакоммиченное дерево Wave 2 · write-scope: только `tests/**` · коммит НЕ выполнялся.

U01/U07/U08 реализованы по ТЗ владельца; старые контракты (D13-era «more-sheet удалён / mobile-topnav scroll-thin», U07-legacy «инверсия флага в app.js», U08-legacy «--glass-displace на ::before, css.supports-детект») легитимно заменены владельцем. Пины переписаны под новую каноническую реализацию, живые интенты сохранены, ни один ассерт не ослаблен «для зелени»: требования, переехавшие в другой файл, проверяются там (fullscreen-policy.js, glass-probe.js).

## Таблица пин → изменено → REQ

| # | Пин (tests/**) | Что изменено | REQ |
|---|---|---|---|
| 1 | `test_asap42_step2c2_miniapp_seeds.py::TestMoreSheetClosedContract::test_more_sheet_is_unmounted_when_closed` | Маркер `mobile-topnav scroll-thin` → `class="mobile-topnav"` (+ запрет scroll-thin); добавлен unmount-контракт popover: `v-if="iaV2 && isMobileShell && moreMenuOpen"` + `.more-menu-root`. Отсутствие `.more-sheet`/`moreOpen`/bottom-nav/transition-CSS сохранено | REQ-U01-3, REQ-U01-4 |
| 2 | `test_frontend_tab_mapping.py::TestJsMirror::test_ia_v2_shell_markers` | Маркер → `class="mobile-topnav"` без scroll-thin + `.more-menu-root` присутствует; запреты MENU_ORDER/MENU_LABELS/sidebarOpen/bottom-nav/☰ сохранены | REQ-U01-3 |
| 3 | `test_hotfix4_cover_nav_shell_round1025.py::TestBottomNavOrder::test_bottom_nav_starts_status_how_and_priority_admin` | Интент «фиксированный порядок навигации» перенесён на U01-канон: `mobileTopnavItems` деривируется из канонического `navItems` (`this.navItems.forEach`) с фиксированным порядком `['status', 'oversight', 'modules']`; маркер topnav без scroll-thin | REQ-U01-1, REQ-U01-3 |
| 4 | `…::TestBottomNavOrder::test_more_items_no_duplicate_how` | `mobileMoreItems` снова существует (popover «Ещё»), но проверена СТРОГАЯ дополненность: фикс-набор строится из `mobileTopnavItems`, «Ещё» = `navItems` минус `!fixed[n.id]` → дублей row B нет | REQ-U01-1 |
| 5 | `test_ia_shell_round1025.py::TestShellMarkers::test_sidebar_drawer_bottom_nav` | Маркер → `class="mobile-topnav"` без scroll-thin; sidebar/drawer ≥1200, отсутствие bottom-nav/more-sheet сохранены | REQ-U01-3 |
| 6 | `…::TestShellMarkers::test_mobile_shell_and_breakpoints` | `mobileMoreItems` из «удалён» → «присутствует + деривация `!fixed[n.id]`»; `bottomNavItems` по-прежнему запрещён; isMobileShell/isCompactShell, touch ≥44, safe-area сохранены | REQ-U01-1 |
| 7 | `test_round106_ia_smoke.py::TestNavShell::test_no_legacy_sidebar_dead_menu` | Маркер → `class="mobile-topnav"` без scroll-thin; dead-menu-запреты сохранены | REQ-U01-3 |
| 8 | `test_webapp_avatars_ui.py::TestAvatarFrontAudit::test_toggle_fullscreen_method` | U07: тело `toggleFullscreen` — делегирование `__FullscreenPolicy` (`policy.request()/policy.exit()`), defensive-путь `wa.requestFullscreen/wa.exitFullscreen` сохранён; инверсия `this.isFullscreen = !…` и синхронная проверка `typeof wa.isFullscreen !== 'boolean'` теперь ЗАПРЕЩЕНЫ (not-in) | REQ-U07-1, U07.1c |
| 9 | `…::test_close_and_fullscreen_buttons` | Глиф `>⛶</button>` → inline SVG-иконки: `class="fs-ic"` ×2 (вход/выход), gate `v-if="me && fsSlot !== 'hidden'"` (tdesktop → hidden), `fs-slot-…` класс, `:aria-pressed="fsAriaPressed"`; ✕-модалки (5 шт.) и запрет closeApp() сохранены | REQ-U07-2 |
| 10 | `…::test_sticky_header_class` | Запрет `z-index: 45` уточнён: header z-40 без изменений; z-45 разрешён ТОЛЬКО у `.oversight-tabs.oversight-dd-open` (U02.2 mobile-dropdown); правило с `.app-sidebar` и z-45 запрещено | REQ-U01-2 (контекст U02.2) |
| 11 | `test_webapp_design_tokens_round1025.py::TestInventory::test_expected_tokens_present` | `--glass-displace` убран из эталона (мёртвый); добавлены presence-маркеры `--lg-frost`, `--lg-frost-hero` | REQ-U08-2 |
| 12 | `…::TestInventory::test_inventory_symmetric_difference` | Префикс `--lg-` добавлен в инвентарь + 13 точных токенов (`--lg-frost`, `--lg-frost-hero`, `--lg-tint-hero/soft`, `--lg-rim`, `--lg-ring-mask`, `--lg-specular-arc/soft`, `--lg-fringe`, `--lg-radius*`, `--lg-shadow`); `--glass-displace` удалён. Симметрия стала СИЛЬНЕЕ (ловит дрейф нового семейства) | REQ-U08-2 |
| 13 | `…::TestLiquidGlassV2::test_single_inline_svg_filter` | Фильтр по-прежнему РОВНО ОДИН `id="lg-lens"`; перестроен: `feImage id="lg-lens-map"` c `href="data:image/png"` + `feDisplacementMap`; `feGaussianBlur` запрещён (старый turbulence-вариант удалён); CSP-инварианты (без внешних href) сохранены | REQ-U08-3, U08.3a, U08.1 |
| 14 | `…::TestLiquidGlassV2::test_level_a_opt_in_only` | Tier A = opt-in только на probe-гейте: `[data-glass="a"][data-glass-tier="a"]` → `var(--lg-frost-hero) url(#lg-lens)`; `[data-glass="a"]:not([data-glass-tier="a"])` → честный Tier B `var(--lg-frost-hero)`; ни одно голое правило A без url(); `::before` = tint-слой (radial-gradient + `--lg-tint-hero`, z-index -1, БЕЗ filter); `--glass-displace` запрещён во всём CSS | REQ-U08-2, U08.1, U08.3a |
| 15 | `test_webapp_hubs_matrix_ui.py::TestNavbarAndHubs::test_six_nav_items` | Маркер → `class="mobile-topnav"` без scroll-thin; канон NAV_ITEMS/NAV_ITEMS_V2, labels, shellNavTo сохранены | REQ-U01-3 |
| 16 | `test_webapp_js_unit.py::test_js_unit_round1025_hotfix6_lens_heartbeat_shell` | Обёртка: docstring приведён к U08-канону (probe-гейт вместо feature-detect; зеркало fullscreen → policy). Причина падения — сам node-тест: в `tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` остался устаревший assert `--glass-displace → url(#lg-lens)` (строка 95) — заменён на запрет `--glass-displace` (мёртвый токен); docstring секции A обновлён | REQ-U08-2 |
| 17 | `test_webapp_nav_disclosure_ui.py::TestMenu::test_no_sidebar_dead_menu` | Маркер → `class="mobile-topnav"` без scroll-thin; dead-menu-запреты сохранены | REQ-U01-3 |
| 18 | `test_webapp_round1024_providers.py::TestFullscreenSync::test_methods_present` | Зеркало методов в app.js сохранено; `Telegram.WebApp.isFullscreen` проверяется теперь в `web/static/fullscreen-policy.js` (там живёт чтение SDK-факта); в app.js — legacy re-read `typeof wa.isFullscreen === 'boolean'` | REQ-U07-1 |
| 19 | `…::TestFullscreenSync::test_toggle_fullscreen_defers_state` | Отложенность состояния перенесена на владельца: в политике `requestPending` + ack-таймер (`_ackTimer`/`DEFAULT_ACK_TIMEOUT_MS`); app.js — делегирование `policy.request/exit`, зеркало синхронизируется из факта (`_fsPolicySync`, `s.actualFullscreen === true`); инверсия/синхронный фикс флага запрещены; defensive `wa.request/exitFullscreen` сохранён | REQ-U07-1, U07.1c |
| 20 | `test_webapp_ui_rework_round1020.py::TestLiquidGlass::test_each_glass_selector_carries_glass` | Blur-токен: принимается каноническое frost-семейство `var(--lg-frost*)` ИЛИ legacy `var(--glass-blur)`; фон `var(--glass-bg)` — без изменений; каскадный резолвер не тронут | REQ-U08-2 |
| 21 | `…::TestLiquidGlass::test_cascade_modal_card_chain` | Аналогично #20 для цепочки `modal-card card` | REQ-U08-2 |
| — | `tests/js/round1025_design_tokens_test.js` (node,-dependency пинов hotfix-семейства) | Устаревшие места: presence-список и инвентарь (`--glass-displace` удалён, `--lg-*` добавлены в prefixes+эталон), assert `--glass-displace → url(#lg-lens)` → запрет токена + presence `--lg-frost-hero`; docstring (§4/§5) обновлён. EXIT 0 | REQ-U08-2 |

Прецедентные файлы `tests/test_webapp_hotfix6/7/8_round1025.py`, `tests/js/asap8_w2_*_test.js`, `tests/js/glass_probe_test.js` — не тронуты (уже в каноне Wave 2).

## 6 предсуществующих падений — не тронуты

Подтверждено полным свиптом: падают ровно те же 6, мои правки их не касаются (0 обращений):

1. `tests/test_mca02_safe_fetch_round1027.py::TestOffParityAndTrusted::test_web_extractor_blocks_destination_without_fallback`
2. `tests/test_mca16_experience_block_d_round1039.py::test_no_per_message_llm_reflection_module_is_llm_free`
3. `tests/test_outgoing_guard_round1022.py::TestTelegramSendWrappers::test_send_rich_message_sanitizes_and_uses_html_mode`
4. `tests/test_outgoing_guard_round1022.py::TestTelegramSendWrappers::test_send_rich_message_markdown_cover_uses_markdown_link`
5. `tests/test_summary_asap2_failsoft_round1027.py::test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback`
6. `tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`

## Финальные числа

- 23/23 пинов — PASS (фокус-прогон: `72 passed` по затронутым файлам/классам).
- node-сьют: 81/81 файлов `tests/js/*.js` — exit 0.
- Полный свипт `py -3 -m pytest tests -q --tb=no`: **13493 passed, 6 failed (ровно предсуществующие), 1 skipped**, ~9:45.

## Границы изменений

Модифицированы только файлы в `tests/**` (12 py + 2 js-теста). Product-файлы (`web/`, `services/`, `tools/`, `config/`) — не менялись этим лейном (их M-статус в git — незакоммиченное дерево Wave 2 других лейнов). НЕ коммитить.
