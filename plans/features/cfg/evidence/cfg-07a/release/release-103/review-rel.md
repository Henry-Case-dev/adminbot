# REV-REL-258103 — ревью релизного поезда **2.58.103** (bump + CFG-07CG словарь/хвост + B1 телеметрия + леджер)

**Вердикт: Approved** (push + deploy; постдеплой-обязательства → VERIFIED, затем `--stage release`; родитель CFG-07A не DONE до них).
**Кандидат:** `2a3e4fc94705cf5741a6755e6098bb9e52f3c096` (HEAD master) поверх прод-базиса 2.58.102 `a3535b68`.
**Гейт:** `check --stage review --slice CFG-07A --candidate 8cd2ca14…` → **EXIT 0** (inventory=246, scoped=12, errors=0).
**Дата:** 21.10.2026 (Asia/Magadan +12). Ревью read-only; тесты/пробы перегнаны ревьюером на HEAD.

## Состав поезда (факт, 6 коммитов)

| Коммит | Класс | Файлы |
|---|---|---|
| `4d79182a` | docs-only: evidence release-102 + карта (постдеплой-речек 07A.1 @ deployed a3535b68) | 15 |
| `7c3a1350` | CFG-07C-G словарь+гварды (public_speech_guard.py, 67 CONTRACT) | 6 |
| `f1e31d27` | CFG-07CG-TAIL хвост-гварды на швах + ресанкции ×4 (301→302) | 13 |
| `8cd2ca14` | B1: flagged→failed ×2 + 3 telemetry-теста + stale-комментарий | 3 |
| `79df9f5d` | леджер: карта (10 строк slice=CFG-07A VERIFIED; 07A.1 live postdeploy) | 1 |
| `2a3e4fc9` | бамп 31 файл | 31 |

Отклонения от брифа (не блокеры): поезд содержит **6-й** коммит `4d79182a` (docs-only, не упомянут); ожидание гейта «EXIT 1 × 5 честных» устарело — после леджера `79df9f5d` все scoped-строки VERIFIED → **EXIT 0** (совпадает с msg 79df9f5d). Foreign-файлов (samples-ux/mca_sample_library/database.py) в поезде **нет**; `services/factcheck_orchestrator.py` (+102) — это wiring гвардов CFG-07C-TAIL на outbound-швах (busy/search_error/llm_error/unexpected_error/no_claim/attribution_miss/short_reply/delivery), не foreign factcheck-attribution. Рабочее дерево грязное (M plans-доки, untracked-скретч) — в поезд не входит, пушится только HEAD.

## Проверено ревьюером (все на HEAD `2a3e4fc9`)

| Проверка | Результат |
|---|---|
| test_cfg07_guard_tail.py | 29 collected/passed (вкл. 3 × TestGuardTelemetry) |
| test_cfg07_egress_dictionary.py | 67 passed (суммарно 96) |
| test_unified_core_route_coverage.py | 18 passed |
| test_mca17c_invariants_round1047.py | 8 passed |
| OFF-parity выборочно (-k) | 9 passed (spy v2 dirty/clean/unrepairable + off-пины; гвард только в v2: tool_router внутри `if v2:`) |
| test_round1025_f8_registry.py | 29 passed |
| gen_param_registry_round1025.py --check | CHECK OK: 582 == REGISTRY |
| fingerprint | factory_set_fingerprint() == FACTORY_SET_SHA256_12 == `037080375ac8` |
| B1 runtime-проба | build_event(outcome='failed') → dict; build_event('flagged') → None (корень B1 подтверждён) |
| grep '"flagged"' services/ | 0 |
| Бамп | 31 файл = SET EQUAL proc-101/102; 30 версионных пар 2.58.102→2.58.103 (4 js — регэксп-пары) + meta (APP_VERSION 2.58.103, HEAD=79df9f5d); settings.py/README = 2.58.103 |
| Ресанкции ×4 | ровно 4 пина `REASON_CODES` 301→302 (mca10b/mca19/mca20×2), причина = +1 reason-code от гвардов |
| ΔDDL | 0 (нет схемных файлов/CREATE/ALTER в поезде; user_version=37) |
| Секрет-скан диффа | чисто (хиты = док-текст/имена тестов; deploy.json rollback-команды без креденшелов) |
| Леджер | slice CFG-07A = 10 строк, все VERIFIED; хвост 07A.3/.5/07D.1/.2 @8cd2ca14; .F = reuse-audit (07cg-reuse-audit.md, вне строк карты — не строка-требование); CFG-07A.1 = VERIFIED + live_required=True/live_when=postdeploy (честная READY_FOR_LIVE) |
| CFG-06 канарейки | 06G.1/06G.4 VERIFIED |
| PREV-лестницы | присутствуют (chat_prompts.py и др.) — откат канонов доступен без рестарта |

Вне скоупа CFG-07A (честно PENDING, не блокер поезда): CFG-07C.1–.6, CFG-07D.3–.7 (следующие волны CFG-07B/07C). Унаследованные постдеплой-RFL из cfg-06 (не этого поезда): 06F.6, 06G.8, 06J.6 — очередь живых E2E-приёмок, остаются в леджере cfg-06.

## Постдеплой-обязательства (после деплоя 2a3e4fc9)

1. `curl -s https://admin-bot.duckdns.org/healthz` → `2.58.103`.
2. 07C.6: на проде дождаться/проверить WARNING-лог `speech guard` + событие `egress_guard`/stage_event `failed` (телеметрия живая).
3. 07A-1: трасса effective payload (postdeploy recheck, live_when=postdeploy у строки CFG-07A.1).
4. `--stage release --candidate 2a3e4fc9… --deployed-commit <prod>` после 1–3; строки 07C.6/07A-1 → VERIFIED.

## Rollback

- Ветка `release/fix-2.58.102` = `a3535b68` создаётся при пушe; cold-откат `checkout -f a3535b68` + restart (ΔDDL=0, каноны не менялись — lossless; факт подтверждён release-102 процедурой).
- Каноны: PREV-лестницы (7/7 байт-сверка REV-CFG07A2), без рестарта.

## Команды

```bash
# локально: rollback-якорь + пуш
git branch release/fix-2.58.102 a3535b68
git push origin master release/fix-2.58.102
# прод: ОДИН ssh-коннект (fail2ban)
ssh nik@198.46.175.136   # внутри: cd /var/www/admin_bot && git pull && sudo systemctl restart admin_bot
curl -s https://admin-bot.duckdns.org/healthz   # expect 2.58.103
```

## Замечания (не блокеры)

- `w7-dispute-metrics.json` latency_ms_mock 6→5 — перегенерированная метрика при ресанкционном прогоне (безобидно).
- Бриф-число «EXIT 1 / 5 строк» и состав «5 коммитов» — устаревшие относительно HEAD; зафиксированы факты выше.
