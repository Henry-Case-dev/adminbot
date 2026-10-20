# OWNER-OBS-RECON — сверка карт с правилом «инженерная приёмка vs добровольное наблюдение владельца»

Дата: 2026-10-20. Основание: `plans/owner_live_checks.md` (правило 20.10.2026), AGENTS.md §«Engineering acceptance vs optional owner observation».
Метод: только метаданные строк (`verification_tier: owner_optional` + `owner_policy_ref` + `owner_optional_reason` + `engineering_req_ids` + `live_required: false`); evidence и статусы VERIFIED не тронуты; `plans/current_task.md` не тронут; **cfg-карта не тронута (ЗАБЛОКИРОВАНА — RECHECK-CFG06-R1)**.

## Итог по картам

| Карта | → owner_optional | Добавлено owner-строк | Осталось engineering mandatory | Гейт |
|---|---|---|---|---|
| add-exp | 1 (конвертация) | 0 | 36 | review **EXIT 0** |
| p0-vision-universal | 0 | 1 (P0V-OWNER-VISUAL, §3–§4) | 37 | review EXIT 1 — 6 ошибок, все предсуществующие (=HEAD) |
| win-glass-hotfix | 0 | 2 (WG-OBS-WIN-DESKTOP §B, WG-OBS-ANDROID-WEBVIEW §C) | 30 | review EXIT 1 — 1 ошибка WG-P0-03, предсуществующая (=HEAD) |
| soul-1 amendment | 0 | 1 (SOUL-AMD.8.11.OWNEROBS, §6) | 94 | review EXIT 1 — 19 предсуществующих legacy-привязок (=HEAD) |
| p0-save-init-ux followup (B) | 0 | 1 (P0B-NOST-SCEN-B.OWNEROBS, §5) | 41 | plan **EXIT 0** |
| p0-save-init-ux (A) | 0 | 0 (не требуется — все live-строки инженерные VERIFIED с нотами «не owner-гейт») | 35 | гейт не перегонялся (правок нет) |
| samples-ux | 0 | 1 (SU-7.OWNER-OBS, §7) | 76 | plan **EXIT 0** |
| add-tr | 0 | 1 (M-ADTR-GRID-DEVICE-OBS) | 68 | review EXIT 1 — 23 предсуществующих честных PENDING/legacy (=HEAD) |
| asap8-v6-3-live-correction | 0 | 1 (U07-OWNER-REALDEV — реальные клиенты Windows/Android) | 222 | review EXIT 1 — 40 предсуществующих legacy-привязок (=HEAD) |

Всего: сконвертировано **1** строка, добавлено **8** owner_optional-строк; существующие VERIFIED/evidence не изменялись; READY_FOR_LIVE глобально никуда не исключался.

## Детали по строкам

1. **add-exp** — `EXP-ACCEPT.CRITERION` → owner_optional (по решению оркестратора: живую F4-матрицу 2.58.98 выполняет владелец, `owner_live_checks.md` §2). Связи: `EXP-RUNTIME.PAYLOAD`, `EXP-RUNTIME.WIRING`, `EXP-ACCEPT.LIVE-SET` (инженерная доставка VERIFIED). FAILED-история acceptance-96 и пороги §4 сохранены в `note`/`live_note`. Остальные live-строки (WIRING/PAYLOAD/ROUTES/LIVE-SET) — инженерные, live закрыт агентским harness.
2. **p0-vision** — все 11 postdeploy live-строк инженерные (canary/техсмоук/пробы; в `live_note` уже помечены «не owner-гейт»); владелец-хвост (качество распознавания на его фото/скриншотах, §3–§4) заведён отдельной строкой `P0V-OWNER-VISUAL` → `P0V-DOD`/`P0V-PIPE-CONTEXT`/`P0V-PIPE-E2E`.
3. **win-glass** — 6 live-строк owner-E2E оставлены engineering mandatory (их инженерные половины VERIFIED: релиз-байты, e2e, деплой), живые наблюдения выделены в 2 owner-строки со сценариями `owner-steps.md` §B/§C: `WG-OBS-WIN-DESKTOP` → `WG-VER-01/WG-WIN-02/03/05/WG-P0-05`; `WG-OBS-ANDROID-WEBVIEW` → `WG-VER-02/WG-ANDROID-02/03`.
4. **soul-1 amendment** — `SOUL-AMD.8.3`/`SOUL-AMD.8.11` (RFL) — агентские пробы, не тронуты; субъективная «единый характер» (§6) выделена в `SOUL-AMD.8.11.OWNEROBS` → обе инженерные строки.
5. **p0-save-init-ux** — карта A чиста (CURSOR/STATUS/TECHJUNK — инженерные, VERIFIED). Followup B: `P0B-NOST-SCEN-B` — смешанная, **разделена**: инженерная половина осталась mandatory RFL (WAITING_EXTERNAL — естественное затишье, проверяемо агентами по логам), наблюдение §5 выделено в `P0B-NOST-SCEN-B.OWNEROBS`.
6. **samples-ux** — live_required-строк нет; §7 (реальный MiniApp-клиент, живой цикл правка→деплой) заведён как `SU-7.OWNER-OBS` → `SU-7.OFFLINE`, `SU-6.REGRESS`, `SU-ACC.NOLIVE`, `SU-7.OWNERLIVE`.
7. **add-tr** — остаток «Android Telegram Portrait/Landscape на реальном клиенте» (в карте уже помечен owner-optional в note) формализован строкой `M-ADTR-GRID-DEVICE-OBS` → `M-ADTR-GRID-CHECKS`, `M-ADTR-VERIFY-NATIVE`, `ADTR-VERIFY-DOD4`. `M-ADTR-VERIFY-NATIVE` оставлен mandatory PENDING (его acceptance выполнима агентами — честная фиксация PENDING_OWNER_E2E).
8. **asap8-v6-3** — ~30 RFL-строк (повторные приёмки B10/V01–V07 и пр.) — агентские, не тронуты; реальные клиенты (Windows Telegram Desktop, Android portrait/landscape) выделены в `U07-OWNER-REALDEV` → `U07-SYM-DESKTOP`, `REQ-U07-HARD`, `REQ-U07-3`, `U07.3c`, `V06`.

## Ограничения и сомнительные случаи

- **cfg-карта не сверялась** (ЗАБЛОКИРОВАНА, RECHECK-CFG06-R1): §1 `owner_live_checks.md` (CFG-04 мобильные формы) останется без owner_optional-строки до вердикта речека; её 4 агентские канарейки/техсмоук трогать нельзя (не owner-only).
- **EXP-ACCEPT.CRITERION** сконвертирована целиком (без расщепления) — по явному решению оркестратора (join-barrier в workflow_state: матрицу выполняет владелец); техполовина и так VERIFIED в связанных инженерных строках, история FAILED сохранена.
- **asap8 U08/V07 (стекло)**: субъективная визуальная оценка «не мыло/не мерцает» на реальном устройстве не заведена в `owner_live_checks.md` — строка оставлена engineering по объективным метрикам (corr/px/FPS); заводить новую §-категорию не входило в объём.
- **win-glass/soul-1/asap8**: при первой вставке owner-строк в массив `items` гейт ругался («inventoried source item gone or edited») — строки перенесены в `additional_requirements`, после чего карты дают ровно те же ошибки, что и их HEAD-версии (проверено гейтом на HEAD-копиях).
- Предсуществующие EXIT≠0 — честные live-ожидания/легаси-леджер, зафиксированы как есть; ничего для «позеленения» не ослаблялось.
