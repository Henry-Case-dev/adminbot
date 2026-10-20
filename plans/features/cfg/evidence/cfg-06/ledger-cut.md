# CFG-06 — леджер-резка карты требований (lane LEDGER-CFG-06)

Дата: 20.10.2026. Кандидат: `5af56d8b1dc5f9497176585ac77d95038af7eaa7` (HEAD).
Прод: `29cc49ba` (2.58.98) — v2-контур и флаг `FACTCHECK_PIPELINE_V2_ENABLED`
на проде отсутствуют (кандидат не задеплоен; поле `deployed_commit` карты
не менялось по брифу). Режим: writer только над
`plans/features/cfg/requirements-map.json` (статусы/evidence/note) + один
микро-тест; сервисный код и git не тронуты.

## 1. Итог по 93 scoped-строкам (slice CFG-06)

| Статус | Строк | Состав |
|---|---|---|
| VERIFIED | 84 | T1–T3, 06A.1–A.10, 06B.1–B.7, 06C.1–C.9, 06D.1–D.9, 06E.1–E.3/E.5–E.7, 06F.2–F.5, 06G.2/G.5–G.7, 06H.1–H.7, 06I.1–I.9, 06J.1–J.5, ADD-1.C1–C3 + агрегаты ADD-1.T6, CFG-06.CON, CFG-06E.CON, CFG-06H.0, CFG-06H.ARCH, CFG-06I.KEY, CFG-06.J-PRIOR, CFG-06.B-HIJ |
| READY_FOR_LIVE | 8 | 06E.4, 06F.1, 06F.6, 06G.1, 06G.4, 06G.8, 06J.6 (scoped) + CFG-06.B (агрегат, postdeploy) |
| PENDING | 1 | 06G.3 (честный гап, см. §4) |

Каждой строке — evidence, привязанный к кандидату (`candidate_commit=5af56d8b…`,
repo-relative `artifact_path` + пересчитанный `artifact_sha256`), observation —
по факту именной acceptance строки (W0→w0-audit/trace, W2→gate-тесты/корпус,
W3→фриз схем, W4→planner, W5→renderer, W6→интеграция/бюджеты, W7→композит S1–S8).

## 2. Микро-гапы

- **06G.1 Saccharomyces — ЗАКРЫТ.** В существующий
  `tests/test_factcheck_planner_cfg06.py` добавлен офлайн-класс
  `TestSaccharomycesBiologicalCase` (2 теста, ~50 строк с докстрингом):
  биологический спор «дрожжи — грибы, а не бактерии» → тезис checkable у гейта,
  биномен `Saccharomyces boulardii` сохранён в entity_check-запросе (не сырой
  слайс), структурный evidence с URL отдельно от текста.
  TEST-LIFECYCLE: REGRESSION owner=CFG-06. Прогон файла: 17 passed.
- **06G.3 tool «кто сказал» — ОСТАЛСЯ (PENDING).** Атрибуция/цитата/privacy
  доказаны (corpus в: автор Петя, dropped_privacy, tg-якорь), но выделенный
  локальный chat-history tool с обязательной цитатой/датой/автором не
  реализован (w7-acceptance §4, w7-review-package §3.3). Тестом не закрывается —
  нужна сервисная работа. **В списке гапов для оркестратора.**

## 3. Гейт requirements (stage review)

```
py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage review
  --slice CFG-06 --candidate 5af56d8b… --map plans/features/cfg/requirements-map.json
→ stage=review inventory=246 manual=41 scoped=93 errors=5, EXIT=1
```

5 ошибок — честные и неустранимые до релиза/канарейки:

1. `CFG-06E.4` (live preprod) — READY_FOR_LIVE: живой рендер в Telegram —
   канарейка при включении флага; осмотр на устройствах — владельцу опционально.
2. `CFG-06F.1` (live preprod) — READY_FOR_LIVE: трасса/админ-наблюдаемость на
   живом прогоне — канарейка.
3. `CFG-06G.1` (live preprod) — READY_FOR_LIVE: агентская часть полная (вкл.
   Saccharomyces), живой биологический спор — канарейка.
4. `CFG-06G.4` (live preprod) — READY_FOR_LIVE: реальный платный веб-вызов —
   при включении флага (недоступность веба покрыта S3).
5. `CFG-06G.3` — PENDING: нереализованный локальный tool (§2).

Гейт-словарь разрешает READY_FOR_LIVE на review только postdeploy-строкам, а
VERIFIED требует live-эвиденс для preprod-live строк; ставить VERIFIED без
живого прогона v2 (кандидат не задеплоен) — выдумка, не делалось.
Postdeploy-строки 06H.1 (аудит доказан на deployed-байтах 29cc49ba), 06F.6,
06G.8, 06J.6 и агрегат CFG-06.B легально VERIFIED/READY_FOR_LIVE на review.
JSON валиден; вне slice CFG-06 не изменено ни одной строки (сверено с HEAD).

## 4. Проверка 9 агрегатных строк (перерезаны оркестратором)

- **Баг:** во всех 9 evidence-записях поля `artifact_path`/`artifact_sha256`
  были свапнуты (path = sha256-хекс, sha = путь). Исправлено на
  `w7-acceptance.md`/`w3-schemas.md`/`w5-renderer.md`/`w2-corpus.md` с реальными
  хэшами; observation «static»/«test» заменены на фактические наблюдения.
- **Статус:** `CFG-06.CON` был READY_FOR_LIVE при `live_required=false` —
  исправлен на VERIFIED (сквозной контракт доказан фризом W3 + композитом S1–S8;
  канарейка — вне обязательств строки). Остальные 8 статусов подтверждены.

## 5. Ключевые артефакты (sha256, 20.10.2026)

| Артефакт | sha256 |
|---|---|
| w0-audit.md | a480dcec14367195686e4208c4ce59682751daa1e35b6e711310e3568193b3f9 |
| w0-trace.json | 875144f534df65ed41d6be590e9b04b7c6503618bf8ad6b5578c04942f8e1e20 |
| w1-notes.md | 9da592df5365f2fa08c71b3ac44e308857e8c1ea2fe7c517b0a78f7d786783b6 |
| w2-notes.md | a725449ca92d9c0184361a29ae543c57be830e16d48b7e7990b2e92e23c786e8 |
| w2-corpus.md | 8c98461fd3bd14d6835e7e438f77b66f97aa06f9934ba07fbefc0fcdeacb69e6 |
| w2-corpus.json | 1e8135819b380b98eecab48a4e0226507f470276f9e85b1da7a2524dd69bf888 |
| w3-schemas.md | 69c9405d7a4363e98bb1d07f7ea897bd7337a6115322c4b9a559cfc27105b0fe |
| w4-notes.md | 6312a08c28d765fee10280e0f60f92b11291c647b35397d7bfe353e376de0dc0 |
| w5-renderer.md | 740971e46571e49ecd31fe51c33b1242c84e2b32a04b96d966eff554fc088b76 |
| w6-integration.md | 14a8035636469395ed53327e3be1be39be4e3aa9596c4ca60e4fe8e6cb047d17 |
| w7-acceptance.md | 9a91b54c900ba351d8ff08a2e836d8bf9602e5e46cbda30a0a43f1ce8e27995a |
| w7-acceptance.json | 75a667e926a7c601e0ede405ab959b53f1654d7a8369cb332c79261bfd806a7a |
| w7-review-package.md | 5bb4a8b43409a09726b0fc4cd5b211c5a6b1836f1dcaab57a498feaa70e00bf1 |
| w7-dispute-metrics.json | cf14b0b816502e49c9557be928a4231455454fb3cbf6aaf31d7ab27407e56747 |
| tests/test_factcheck_gate_cfg06.py | 12850dce33e2ae06906c82994e9f88ca3a0f1791fe68aa45bc1cf02b0caa9906 |
| tests/test_factcheck_planner_cfg06.py | 478c8935951f56cc8c289389dba88c7284d7ee16b615f054f6ee85d33b3e429a (после микро-теста) |
| tests/test_factcheck_renderer_cfg06.py | 010a5db803f0635340a7f28b0de862a97321021267103db397db06d4708952d4 |
| tests/test_factcheck_w7_acceptance_cfg06.py | 3f8661a164af2f953cb98cff3f8d93b7d6e703ce564fabb6d34c4b88a7743f3b |
| tests/test_factcheck_orchestrator_cfg06.py | fd93e0bb95cd3c4021331654634ef6b73215d326c56e1510e39ab06ab2d89202 |
| tests/test_factcheck_w6_cfg06.py | cc5f99edf6fd196b43e45c2c04ac249edf8ee9e6d44c5cf8990da381a41554c9 |

## 6. Верификация лейна

- Фокусированный прогон CFG-06-сьютов после микро-теста: planner+gate+renderer+
  orchestrator+context+W6+W7+route-coverage = **130 passed / 0 failed** (exit 0).
- Известные вне диффа (не тронуты): 2 FAIL outgoing_guard (aiogram-дрейф),
  2 FAIL asap7_direct_settings (v35).
- Коммит не создавался (git не тронут) — изменения в рабочем дереве:
  `plans/features/cfg/requirements-map.json`,
  `tests/test_factcheck_planner_cfg06.py`, этот файл.
