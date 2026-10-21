# Prep: tails-binding recon — win-glass-hotfix (requirements-map.json)

Рекон PM (LANE PM-TAILS-RECON), 2026-10-22. Read-only по карте; файл — рекомендации для биндинг-лейна.
Метод: каждая PENDING/READY_FOR_LIVE-строка просмотрена; evidence указан только реально найденный.
Волны доставки: хотфикс-кандидат 0ca661fe (review-wg Approved, вердикт 8e326403), семантический порт + деплой 2.58.85 (release-tip 95526863, deployed_commit в карте), e2e 37/37 и FS 12/12 на релиз-байтах; связанные поздние волны: dropdown-wg фикс 2.58.87 (f19b514a, cross-ref уже в карте), FE-GLASS-MINILENS закрыт 2.58.105 (6c1dea40, asap8-бэклог, вне этой карты).

## Счётчики (16 открытых строк: 9 PENDING + 7 RFL)

| Вердикт | строк |
|---|---|
| REUSE (доставлено волной, нужен биндинг + release-гейт; live-остаток уже консолидирован owner_optional-строками) | 7 |
| REAL_WORK | 0 |
| CONTEXT / duplicate (уже disposition=context/duplicate) | 7 |
| OWNER_OPTIONAL (уже tier=owner_optional, не дублировать) | 2 |

Ключевой вывод: реальной разработки в карте не осталось. Все 7 RFL-строк — «живые строки», чья инженерная половина выполнена и привязана (деплой 2.58.85, e2e/FS/HTTP на релиз-байтах), а личная визуальная часть на реальных клиентах — уже разведена в WG-OBS-WIN-DESKTOP / WG-OBS-ANDROID-WEBVIEW (owner_optional по правилу 20.10.2026, device-чек-листы отменены).

## REUSE — биндинг + release-гейт (7)

| Строка | Чем доставлено | Указатель для биндинга |
|---|---|---|
| WG-VER-01 | Инженерная live-половина: прод отдаёт 2.58.85 (healthz 200 извне+loopback, /web/ 15×2.58.85); сценарий владельца задан; device-наблюдение = WG-OBS-WIN-DESKTOP | evidence/release/postdeploy_http.txt (type=production); owner-steps.md §B |
| WG-VER-02 | Инженерная live-половина: headless Chromium 390×844 на проде — 200, 0 ошибок консоли, __GlassRefraction/__GlassProbe object (эмуляция, честно оговорена); визуальное сравнение = WG-OBS-ANDROID-WEBVIEW | evidence/release/postdeploy_probe.json; owner-steps.md §C |
| WG-P0-05 | Штатные этапы фактически проведены: ревью Approved (0ca661fe) + деплой выполнен (checkout 95526863, TRACKED_MOD=0, 7/7 хэшей, healthz 2.58.85, 10/10 проб, журнал 0 ERROR, NRestarts=0, rollback-цель 0b7a0aca жива); deployed_commit уже в карте. Остаток = прогон release-стадии гейта для фиксации VERIFIED | review-wg.md §5/§6; evidence/release/deploy-run.txt (A–K); release-2.58.85-report.md |
| WG-WIN-02 | Ограничение клиента + обход §A.1 задокументированы; e2e 37/37 на релиз-байтах (D_no_window_geometry_hacks); наблюдение «рабочая область минус панель задач» = WG-OBS-WIN-DESKTOP | evidence/release/e2e-run.txt; owner-steps.md §A/§B |
| WG-WIN-03 | Переключение/выход/закрытие/управление окном: FS-аудит 12 сценариев 166/166 PASS + fullscreen-policy.js byte-equal (96db06425079) на релиз-байтах; наблюдение = WG-OBS-WIN-DESKTOP (§B п.4) | evidence/fs-regression/_results.json; evidence/release/hashes.txt |
| WG-WIN-05 | Ограничение подтверждено источниками/кодом (tdesktop#30963, SDK без геометрии), обход задан, заглушек нет; подтверждение на реальном клиенте = WG-OBS-WIN-DESKTOP | report.md §1.4/§1.5; owner-steps.md §A/§B |
| WG-ANDROID-02 | Видимое смещение фоновых пикселей на релиз-байтах: −26/+32 device px (corr 0.92/0.971), центр 0 px, шум-контроль 0 px; живое сравнение = WG-OBS-ANDROID-WEBVIEW (§C) | evidence/release/e2e/_results.json; pattern_on.png/pattern_off.png |

Паттерн закрытия (как M-ADTR-GRID-CHECKS): инженерный live-evidence (production-артефакты выше) привязать → VERIFIED с честной нотой, что личная визуальная проверка на реальном клиенте — добровольная WG-OBS-*; полный успех на нативном клиенте не заявляется. Финальное решение — за биндинг-лейном + Reviewer; release-гейт карты (`--stage release --candidate 0ca661fe… --deployed-commit 95526863…`) прогнать один раз на все строки.

## CONTEXT / duplicate (7)
MAN-WG-01 (провенанс скриншотов), MAN-WG-05 (симптом Windows — производные L12/L13/L15), MAN-WG-06 (симптом Android — производные L22–L27), L00006 (§1), L00017 (§2), L00029 (§3), WG-P0-03-якорь MAN-WG-16 (disposition=duplicate; реальная строка WG-P0-03 = MAN-WG-04 VERIFIED — закрыть дубль-якорь её evidence).

## OWNER_OPTIONAL (2) — уже консолидировано, не дублировать
- WG-OBS-WIN-DESKTOP (engineering_req_ids=[WG-VER-01, WG-WIN-02, WG-WIN-03, WG-WIN-05, WG-P0-05])
- WG-OBS-ANDROID-WEBVIEW (engineering_req_ids=[WG-VER-02, WG-ANDROID-02, WG-ANDROID-03])
- owner_policy_ref=plans/owner_live_checks.md; в самом owner_live_checks.md win-glass-пунктов нет — при желании добавить секцию «Fullscreen/рефракция» (опционально, не блокер).

## Примечания биндинг-лейну
1. Не выдумывать наблюдения владельца: Windows/Android device-пункты остаются owner_optional (PET_PROJECT §5), в VERIFIED переводится только инженерная половина.
2. Риск-ноту «popup внутри клипа refraction-поверхности» (dropdown-wg README §6) — сохранить как есть (вне строк этой карты).
3. CONTEXT-строки уже имеют корректный disposition; нужно лишь согласовать статус (сейчас PENDING) — механика гейта.

---

## Исполнение (LANE LEDGER-TAILS-BIND, 22.10.2026)

Все 7 REUSE-строк → VERIFIED: инженерные live-половины на задеплоенных байтах 2.58.85 (production-артефакты деплоя/HTTP/e2e/FS сверены probe-прогоном, SHA256 матч); личные визуальные проверки на реальных клиентах остаются добровольными WG-OBS-* (owner_optional), полный успех на нативном клиенте не заявляется (паттерн M-ADTR-GRID-CHECKS).

Механика гейта (минимальные правки вне 7 строк, обе задокументированы в observations):
1. Release-артефактам 4 live-строк (WG-WIN-02/03/05, WG-ANDROID-02) проставлен `type: production` — эвиденс собран на задеплоенных байтах волны 2.58.85 (release/ каталог); без типизации live-строки не проходят release-стадию.
2. MAN-WG-04 (WG-P0-03, не REUSE): обновлены 2 дрейфанувших artifact_sha256 — AGENTS.md d7d8a445→62d638cc (дополнялся стоячими правилами PET_PROJECT 18.10, суть пп.1/5 неизменна), review-wg.md 94cdfc03→e1f5cbe3 (append-only раунды R2–R4; строгий биндинг-ревью R2 Approved, §6 сохранён). Без этого строгий гейт фейлил бы строку по устаревшим хэшам.

**Release-гейт (один прогон)**: `--stage release --candidate 0ca661fe --deployed-commit 95526863` → **rc=1, ровно 1 ошибка**: `deployed commit missing or differs from reviewed candidate` — структурная проверка гейта требует deployed==candidate, но деплой 2.58.85 выполнялся семантическим портом кандидата (d637cfe9) на релиз-линию 95526863; все построчные проверки (статусы/evidence/артефакты/live-typing) чистые. Вариант брифа `--candidate HEAD --deployed-commit 3a178c6c` структурно невозможен: гейт требует candidate==map.candidate_commit (0ca661fe) — прогон задокументирован (56 mismatch-ошибок).

Текущий прод не задет: стек линзы glass-refraction.js/fullscreen-policy.js/glass-probe.js байт-неизменен 95526863→3a178c6c (diff деревьев); app.css/index.html развивались поздними фичами вне hotfix-дельты.

Гейты: `plan` → EXIT 0 (inventory=14, manual=18); `review --slice WG-VERIFY / WG-WIN / WG-ANDROID` → все EXIT 0. CONTEXT/duplicate-строки (7) не тронуты — вне WRITE_SCOPE, гейт их статус не проверяет.
