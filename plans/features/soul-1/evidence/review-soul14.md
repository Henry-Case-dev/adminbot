# REV-SOUL14 — ревью лейнов SOUL-14.1/14.2 перед поездом 2.58.106 (21.10.2026)

Биндинг: 14.2 = a8d049f3+6f8710a8; 14.1 = 2f1a49ad+20252faa; base bf17a972. Ревью коммитов, не dirty-дерева.

## Запущено независимо
- tests/test_soul14_telemetry_extent.py + test_soul1_extent_one_word.py + test_soul1_style_policy.py: 97 passed (11 CONTRACT, метка TEST-LIFECYCLE на месте).
- tests/test_soul14_layers_payload.py: 6 passed. tests/ui_soul14_layers_e2e.py (venv playwright): failures=0 x2 прогона, свежие скриншоты 360/390/no-layers/unknown/desktop.
- Гварды: p0a-compact failures=0 POST=22; mobile-entry failures=0; js-unit+design-tokens+speech-ui+font 112+1 env-skip (fontTools нет в sys-python; в .venv font 11/11 => 113 эквивалент).
- Визуальная проба: layers_360.png + layers_no-layers-390.png осмотрены ревьюером — 7 узлов, коннекторы, честные «—» без данных, overflow=0, тап>=44, тёмное стекло по конвенции таба.
- Код-аудит: payload только счётчики/коды (reason — enum-коды response_extent:686-730), исходы строго ALL_OUTCOMES (build_event валидирует, mca_events:545), OFF/без-плана => extent None => нет события (style_policy:2155/2160-2168), kill-switch в emit_mca_event (mca_events:630,642), verify_outbound_payload событий не эмитит (нет дублей), оба прод-вызова emit_events=True (direct_chat_service:3799,9015), 0 LLM (mca_self_model без llm-вызовов), 0 новых таблиц/сервисов.

## Честность строк
- 14.1 READY_FOR_LIVE (live_when=preprod, кандидат 2f1a49ad) — корректно: live закрывается на выкате поезда (standing PET_PROJECT-согласие, откат готов).
- 14.2 VERIFIED при live_required=true/live_when=preprod без живого прода — НЕ обосновано: собственный прецедент проекта (SOUL-21.3, AMD.8.11, U08.4d; строки 2.58.105 перевёрнуты в VERIFIED только постдеплоем @a6246e33) и несимметричность с 14.1 в том же поезде. Инженерная часть полная (контракт-тесты + эмуляция durable-буфера), блокер только в ярлыке строки карты.

## Состав поезда (снимок на момент ревью)
bf17a972..HEAD: a8d049f3, 6f8710a8, 2f1a49ad, 20252faa (мои — чужих runtime-правок в них нет: только style_policy.py+tests / web/*+tests) + чужие 4f0ae438 (asap8: только tests+evidence+docs, runtime=0) и cdb0492f (asap8 B12.6, runtime services/chat_migration.py — появился в окне ПОСЛЕ брифинга, этим лейном НЕ ревьюился). Dirty-файлы (glass-tiera PNG, backlog.md, SOUL-14.4 строка карты) в коммиты не захвачены.

## Риски (не блокеры)
- mca_events: +1 строка на каждый проход с extent-check (per-message); существующий prune_events с ретеншеном ограничивает рост; при 1-2 чатах объём приемлем — факт зафиксирован.
- Пре-существующие 2 FAIL w6 expression-preview / glass-tiera lens — на bf17a972 до лейнов, вне скоупа.

## Вердикт
14.1: Approved (READY_FOR_LIVE, live на поезде). 14.2: Needs Fixes — один docs-блокер: строка SOUL-14.2 VERIFIED -> READY_FOR_LIVE до живой пробы на выкате (перевернуть с deployed-evidence по прецеденту 2.58.105). Код 14.2 замечаний не имеет.