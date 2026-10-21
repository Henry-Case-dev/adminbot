# Prep: legacy-binding recon — soul-1 (requirements-map.json + requirements-map-amendment.json)

> **ИСПОЛНЕНИЕ (LEDGER-LEGACY-BIND, 21.10.2026, HEAD fff68d76):** биндинг выполнен по этому реконy.
> Итог (items+manual): main 104→126 VERIFIED (22 REUSE), context 5→9, owner_optional 0→2 (SOUL-12.0, SOUL-17.4);
> amend 49→66 VERIFIED (17 REUSE), context 15 (без изменений — уже классифицированы), AMD.8.3 RFL→PENDING (AGENT_CHECK).
> Гейты plan: обе карты EXIT 0. Указатели, не совпавшие с фактом:
> 1) `speech-mobile-fix/_r3_*` — фактическое расположение раундов `evidence/mobile-prompts/_r3_*` (включая `_r3_bu-390-mode-tabs.png`); speech-mobile-fix содержит before/after/green entry-E2E — оба каталога использованы;
> 2) SOUL-16.4.4 — отдельная eligibility подтверждена в коде: `style_policy.py:80–96` (MACHINE_CONTEXTS + rule_applies с ссылкой на SOUL-16.4.4), `prompt_composer.py:109/165` (`profile:editorial_eligibility`, compose_machine_system для L1/Stage-1/factcheck), `prompt_registry.py:347` (`speech_plain|editorial_report/summary_legacy`) → закрыт VERIFIED;
> 3) SOUL-AMD.8.3 — по решению оркестратора не биндился (AGENT_CHECK при следующем окне), статус READY_FOR_LIVE→PENDING.

Рекон PM, 2026-10-21. Read-only по картам; этот файл — только рекомендации для биндинг-лейна.
Метод: каждая PENDING/READY_FOR_LIVE-строка просмотрена; evidence указан только реально найденный (файлы/коммиты не выдумывались).

## Счётчики (обе карты soul-1, 79 открытых строк)

| Вердикт | main | amend | всего |
|---|---|---|---|
| REUSE (доставлено волной, нужен только биндинг evidence) | 22 | 18 | 40 |
| REAL_WORK (есть остаток работы) | 11 | 2 | 13 |
| CONTEXT (заголовок/roll-up — предложить disposition=context) | 9 | 15 | 24 |
| OWNER_OPTIONAL (живое личное наблюдение, plans/owner_live_checks.md) | 2 | 0 | 2 |

## requirements-map.json (main, 44 строки)

### REUSE — доставлено, биндинг evidence
| Строка | Чем доставлено | Указатель для биндинга |
|---|---|---|
| SOUL-BOUND.0 | Единый канон, legacy off | evidence/release-soul-25886/verify-after.txt, final-verification.txt (2.58.86, eafbe2e7); agent-checks-window2 (2.58.89, d59fab94) |
| SOUL-01.5 | Один путь к Core, нет silent-fallback | evidence/release-soul-25886/verify-after.txt (layers_current/versions.core/conflicts) + review-release-25886.md §4 |
| SOUL-03.0 | Модуль личности/SelfModel сохранён | services/mca_self_model.py; w1-registry-report.md; test_soul1_composer_layers.py |
| SOUL-04.0 | Единый Composer, effective layers API | UNIFIED-CORE 2.58.98: services/prompt_composer.py, prompt_registry.py; w2-composer-report.md; tests/test_soul1_composer_layers.py |
| SOUL-05.0 | L1/one_word/авто-объём/Initiative | services/direct_l1.py; tests/test_soul1_extent_one_word.py; w3-style-report.md; w5-initiative-report.md |
| SOUL-10.4 | Примеры шуток: карточки/фильтр/предпросмотр/badges | W4: w4-humor-feedback-report.md (§ web/api/speech.py — разделы Примеры/Обучение), evidence/w4/*; категория Юмор: samples-ux 2.58.100 SU-CAT.HUMOR (VERIFIED) |
| SOUL-10.6 | Обучение: принятое/неудачное, контролы pause/approve/reject/reset | W4: w4-humor-feedback-report.md + evidence/w4/ui-report.json, shots/; review-w6.md line 29 (отложено на W4 → W4 закрыл) |
| SOUL-11.0 | Mobile direct prompts 320–430, список-edit-save-reopen, E2E | evidence/mobile-prompts/ (chain-320..430-reopen.png, run-green.txt, mobile_prompts_e2e.py) + evidence/speech-mobile-fix/ (_r3_* rounds) |
| SOUL-15.2 | Единая схема источников (inventory PG-ключей) | w1-registry-report.md (25 PG-ключей prompts.*, 6 hard-custom, 65 объектов, Factory/Global/Chat/Inherited) |
| SOUL-15.4 | Права/RBAC | w6 RBAC: review-w6.md (SOUL-16.4.3 RBAC-точка VERIFIED); 403-guard F1: w4-humor-feedback-report.md §F1 |
| SOUL-15.5 | Hot apply, immutable snapshot | w2-composer-report.md; evidence/release-soul-25886/verify-after.txt (active_revision/source/origin); agent-checks-window2 (атомарные ревизии) |
| SOUL-15.6 | Раздельные флаги | Флаги в коде: prompt_composer.py:378, style_policy.py:935, mca_humor_feedback.py:111, mca_sample_library.py:1859, mca_gates.py:504 и др.; cfg evidence (2.58.100–104) |
| SOUL-15.7 | No silent degradation, диагностика downgrade | w2-composer-report.md; evidence/release-soul-25886/verify-after.txt; style_policy.py (MACHINE_CONTEXTS, DEFAULT_EXEMPTIONS) |
| SOUL-15.8 | Объём/latency/стоимость | evidence/w3/cost-measurement.txt (p50 0.20s / p95 0.38s); w3-style-report.md:89,286 (p50=0.170ms/p95=0.261ms resolve, n=600) |
| SOUL-16.4.4 | Правила не применяются к SQL/JSON/L1/машинным | style_policy.py:80–87 (MACHINE_CONTEXTS, DEFAULT_EXEMPTIONS: verbatim_quote/url/code/json), VERIFIED-сиблинги 16.2.1–16.2.4; genre-слои в prompt_composer.py. Биндинг-лейну: подтвердить отдельную eligibility Factcheck/ред. Summary в composer-жанрах |
| SOUL-19.0 | Test plan + release gate | gates в релизах 2.58.84/86/87/89: release-2.58.89-report.md, release-reconciliation (asap8), evidence/release-25889/ |
| SOUL-18.0 | Воронка + диагностика инициативы | w5-initiative-report.md; evidence/w5/*; verify-after.txt (gates 10/10, initiative ON) |
| SOUL-18.2 | Реальные счётчики 24–48ч | evidence/w5/perimeter.txt; evidence/agent-checks-window2/ (реальные счётчики: 3 фоновые инициативные попытки, state-pre-post-25889.txt); tick-наблюдения в asap8 |
| SOUL-18.3 | Возможности не задушены | review-w5.md §3 (BLOCKER-1 закрыт); tests/test_soul1_w5_observer_gates.py; agent-checks-window2 probe-run2-closing-raw.txt |
| SOUL-18.4 | Мягкие цели, кнопка «Проверить инициативу» | review-w5.md §1/§5; evidence/w5/parity-off.json; tests/test_soul1_w5_observer_gates.py |
| SOUL-18.6 | MiniApp-воронка, одно место отображения | review-w5.md §2; tests/js/soul1_w5_initiative_panel_test.js; evidence/w5/js-guards.txt |
| SOUL-18.7 | Live acceptance (естественные контексты) | evidence/w5/live-acceptance-plan.md; agent-checks-window2 (реальные тест-чаты A/B, initiative ON, mock-send guard); postdeploy-observations.md |

### REAL_WORK — остаток работы
| Строка | Что осталось | Объём |
|---|---|---|
| SOUL-14.0 | Telemetry/флаги/rollback есть (mca_events.py, флаги в коде); отсутствует A/B-инфраструктура («A/B-helper» — в plans/backlog.md) | Средний: A/B-механика + диаграмма влияния слоёв как артефакт |
| SOUL-21.1 | Отчёт: Prompt/Writer matrix старая/новая | Сборка финального отчёта эпика §21 — материалы существуют (w1/w2/w3 отчёты, release-отчёты); нужна компоновка |
| SOUL-21.2 | Схема источников + приоритеты + runtime manifest | −«− |
| SOUL-21.3 | Реальные примеры (one_word vs micro, кавычки/точка, абсурд, technical, Initiative, Summary, zero-feedback) | live_required=preprod: нужны свежие реальные прогоны (частично покрывается agent-checks, требует биндинга/допробы) |
| SOUL-21.4 | Снимки 320/390/1440 + исходные E2E артефакты | Артефакты есть (w6 shots, mobile-prompts) — компоновка в отчёт |
| SOUL-21.5 | A/B оценка (методика, стоимость, откат) | Зависит от SOUL-14.0 (A/B); без A/B — честная фиксация «не проводилось» |
| SOUL-21.6 | Evidence observed→lesson→application→outcome + chat isolation | Данные есть (experience/humor feedback) — компоновка |
| SOUL-21.7 | Полный разбор Fullscreen по platform/client + диагностика отсутствующих SEND | Материалы: w7-v63-baseline-report.md, release-fs-25884, agent-checks — компоновка |
| SOUL-21.8 | Ведомость legacy v6.3 gates, стенда, embedding quota, git-артефактов | Материалы в asap8 evidence — компоновка |
| SOUL-21.9 | Версия/SHA/тесты/reviewer/ограничения | Компоновка из release-отчётов |
| SOUL-21.10 | Человеческий отчёт владельцу | Финальная компоновка (Оркестратор) |

Итого REAL_WORK кластер: «финальный отчёт эпика SOUL-21» = 10 строк компоновки + SOUL-14.0 (A/B).

### CONTEXT — предложить disposition=context
| Строка | Причина |
|---|---|
| SOUL-EXEC.1 | Процессная мета-строка (§0); гарантии обеспечиваются существующими гейтами/снапшотами, отдельного runtime-поведения нет |
| SOUL-01.0 | Заголовок-зонтик §2; дети 01.1–01.4 VERIFIED + 01.5 отдельной строкой |
| (без id) «Речь, юмор и мышление» | Заголовок источника, нет acceptance |
| (без id) «16.1 Типы правил…» | Заголовок; дети 16.1.x VERIFIED |
| (без id) «16.2 Не пиши кавычки…» | Заголовок; дети 16.2.x VERIFIED |
| (без id) «16.3 Не ставь точку…» | Заголовок; дети 16.3.x VERIFIED |
| (без id) «16.4 Исполнение…» | Заголовок; дети 16.4.x VERIFIED (кроме 16.4.4 — своей строкой) |
| SOUL-15.0 | Зонтик §15; дети 15.2–15.8 своими строками (REUSE) |
| SOUL-21.0 | Зонтик §21; дети 21.1–21.10 своими строками (REAL_WORK) |

### OWNER_OPTIONAL — живое личное наблюдение
| Строка | Engineering-часть | Ссылка на политику |
|---|---|---|
| SOUL-12.0 | Доставлено: fullscreen-policy.js (prod 200), release-fs-25884, deploy-run 2.58.86; осталось «живой enter/exit на поддерживаемом клиенте» — наблюдение владельца | plans/owner_live_checks.md; device-чек-листы отменены 18.10.2026 |
| SOUL-17.4 | Доставлено: review-tiera.md (ledger 4/6, p50/p95 16.7/16.9ms), glass-and-ui-suites.txt 7/7, hashes 2.58.86; осталось визуал/perf на реальных Android/Windows | plans/owner_live_checks.md |

## requirements-map-amendment.json (35 строк)

### REUSE — доставлено, биндинг evidence (18)
| Строка | Чем доставлено | Указатель |
|---|---|---|
| SOUL-AMD.1.2 | Удаление старых канонов | evidence/release-soul-25886/final-verification.txt, deploy-run.txt (withheld=11, legacy не активен) |
| SOUL-AMD.1.6 | one_word ≠ micro | tests/test_soul1_extent_one_word.py, test_soul1_style_payload.py; UI: evidence/speech-mobile-fix/_r3_bu-390-mode-tabs.png; L1-пробы agent-checks-window1/2. Биндинг-лейну: зафиксировать живую пробу различия (мелочь) |
| SOUL-AMD.2.3 | Direct/Initiative/реакции через Core | UNIFIED-CORE 2.58.98; tests/test_soul1_composer_layers.py; verify-after 2.58.86 |
| SOUL-AMD.2.4 | Factcheck через Core + жанровый слой | prompt_composer.py/prompt_registry.py (genre-слои); release-25889 evidence |
| SOUL-AMD.2.5 | Summary через Core | −«− |
| SOUL-AMD.2.7 | Инструментальные ответы через Core | −«− |
| SOUL-AMD.2.8 | Будущие Writer-выходы через Core | w2-composer-report.md (единая регистрация) |
| SOUL-AMD.3.4 | Управляемые сообщения/отмазки | services/prompt_registry.py (managed messages/fallback templates), prompt_factory.py |
| SOUL-AMD.3.6 | Нет тихой подмены | evidence/release-soul-25886/verify-after.txt (active_revision/source/origin) |
| SOUL-AMD.4.1 | Версионированные заводские редакции | prompt_factory.py; w1-registry-report.md (Factory/Global/Chat/Inherited) |
| SOUL-AMD.4.6 | Legacy только в backup | evidence/release-soul-25886/capture-before.txt (backup sha256_16 5cc7de90e9132d05); evidence/release-25887/post-check.txt |
| SOUL-AMD.7.2 | Backup + идемпотентная миграция + обратимость | evidence/release-soul-25886/first-attempt-health-miss.md (авто-откат подтвердил обратимость) |
| SOUL-AMD.7.3 | Дубли личности устранены | final-verification 2.58.86; w2-composer-report.md |
| SOUL-AMD.7.4 | Ревью проверяет сборку промпта/доставку | review-release-25887.md §1 (независимая живая проверка прод-байтов) — процессная строка, биндинг на существующие ревью |
| SOUL-AMD.8.1 | Один effective Core по путям, реальными прогонами | agent-checks-window2 (S0–S9, реальные прогоны); verify-after 2.58.86 |
| SOUL-AMD.8.3 | Редактирование меняет следующую генерацию | evidence/agent-checks-window2/probe-run2-closing-raw.txt + review-agent-checks-window2.md §3; release-25887 post-check; 2.58.87 (68cd05b2 fix). Residual: генерация в окне не проверялась — AGENT_CHECK при следующем окне, не owner |
| SOUL-AMD.8.4 | Factory Default/diff/история/откат/inheritance | evidence/release-soul-25886/final-verification.txt |
| SOUL-AMD.8.12 | Unit/integration/e2e + реальный trace | evidence/agent-checks-window1+2 (hash-bind, journal, tracebacks); release-отчёты |

### REAL_WORK (2)
| Строка | Что осталось |
|---|---|
| SOUL-AMD.8.2 | Сравнение полной/компактной редакций Core на реальных обезличенных сценах (мат/острота/абсурд/несоевость) — прямой сравнительной пробы в evidence не найдено; малая сессия прогонов |
| SOUL-AMD.8.11 | Живые сценарии поиска/фактчека/видео: window2 — провайдер not_configured (cobalt_absent). Search/factcheck — агентские пробы; video — WAITING_EXTERNAL (провайдер не настроен, owner в бэклоге) |

### CONTEXT (15)
Заголовочные строки без req_id/acceptance: §1 «Единственный канон», §2 «Граница речи…», §2.1, §2.2, §2.3, §3 «No Hidden Behavioral Prompts», §4 «Factory Defaults», §5 «Фактические возможности…», §5.1–§5.4, §6 «MiniApp…», §7 «Интеграция и миграция…», §8 «Приёмка…» — все имеют VERIFIED-детей (AMD.31 VERIFIED в карте) или обязательства покрыты дочерними строками. Предложить disposition=context каждой.
