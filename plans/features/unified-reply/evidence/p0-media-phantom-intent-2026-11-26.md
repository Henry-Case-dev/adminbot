# P0 — MEDIA BINDING F1: own/reply media = визуальный актив (C1)

Date: 2026-11-26. Lane: `fix/p0-media-phantom-intent` (unit `P0-MEDIA-F1`).
Contract: `plans/owner_inputs/2026-11-26-p0-direct-trigger-l1-media.md` (sha256
`528eac7f…2275b2`) §4; cause C1 из
`plans/features/unified-reply/evidence/p0-media-binding-diagnosis-2026-11-26.md`.
Base: `4e5374536e45bcf97e9aa8544d68493fa2cbe6e0` (tip `fix/p0-trigger-force` на
момент выдачи; ветка затем получила docs-only evidence-коммиты `a40880161`,
`c7a8931a8`, код в них не менялся).
Candidate (code + regression test): `e07fd5c3211f81376d392faf780121db7966a423`.

## 1. Изменение (единственный шов, cause-level)

`services/direct_chat_service.py::_prepare_turn_media_evidence` (`:15432-15442`):
`own_media`/`reply_media` больше не «транспортный токен есть» (`message_media_type`),
а наличие визуального актива тем же предикатом, что пишет канонический реестр
Vision (`mca_vision.extract_image_assets`, `services/mca_vision.py:1944-2028`;
intake — `register_intake_assets`, `:2107-2162`):

```python
own_media = bool(_mv.extract_image_assets(message))
reply_media = (bool(_mv.extract_image_assets(reply))
               if reply is not None else False)
```

Предикат вычисляется transport-side (по самому сообщению), без чтения реестра —
гонки с intake-хендлером нет. Фото, статический/анимированный стикер,
image-документ, animation и video/video_note-превью дают непустой список активов
(поведение паритетно базе); audio, voice и не-image документ — пустой список,
поэтому `is_media_dependent` (`services/media_readiness.py:864-894`) больше не
считает такой ход зависимым от изображения, ветка `:15518-15533` не создаёт
durable-намерение, и `_prepare_turn_media_evidence` возвращает `None` (все
потребители уже обрабатывают `None`: `:5962`, `:6914`).

Не тронуто: ветка «просьба текстом → фото позже» (`:15442-15487`), рендер
Direct-окна, `_render_current_question`, `_resolve_earlier_image_markers`,
reply-anchor, TTL/кулдауны/лимиты, инициатива/Observer. Пересланный материал
по-прежнему попадает в контекст/историю как обычное сообщение — исчезает только
фантомное намерение «жду изображение».

## 2. RED → GREEN (детерминированные тесты)

Новый файл: `tests/test_p0_media_phantom_intent.py` (12 тестов, без сети/LLM).

| Прогон | База `4e5374536` | Фикс `e07fd5c32` |
|---|---|---|
| `pytest tests/test_p0_media_phantom_intent.py` | **5 failed, 7 passed** | **12 passed** |

RED на базе (точные имена): `test_forwarded_audio_creates_no_phantom_intent`,
`test_forwarded_audio_is_not_answered_with_unrelated_photo`,
`test_voice_and_pdf_create_no_intent`,
`test_video_without_preview_has_no_visual_asset`,
`test_reply_to_audio_is_not_own_image_media`.

Покрытие по контракту:

- (a) 3 пересланных трека с рекламной подписью → `readiness is None` ×3, 0
  pending intent; позднее постороннее фото (intake + enqueue + ready-анализ +
  sweep) → **0 доставок** (на базе — ответы описанием фото на треки).
- (b) photo / sticker / image-document / animation / video-with-preview →
  `MediaReadiness`, `media_dependent=True`, `ASSOC_MISSING`, ровно 1 намерение —
  идентично базе; reply без текста на фото остаётся зависимым.
- (c) voice note и PDF-документ → `readiness is None`, 0 намерений.
- (d) текстовая просьба «разбери скрин, сейчас скину» → 1 намерение (trigger
  9800); фото 9801 приходит → привязка `tg=9801`, sweep даёт ровно 1 доставку
  `(9800, 9801)`, повторный sweep — 0.

## 3. Сквозное воспроизведение (реальные числа)

Одноразовый probe (тот же сценарий, что в диагнозе; удалён после прогона).

База `4e5374536`:

```
track 9101 readiness= ('missing', True)
track 9102 readiness= ('missing', True)
track 9103 readiness= ('missing', True)
pending intents: 3
intent triggers: [9101, 9102, 9103]
linked intents: [(9101, 9500), (9102, 9500), (9103, None)]
{'resumed': 2, 'terminal': 0, 'waiting': 0, 'failed': 0}
deliveries: [(9101, 9500), (9102, 9500)]
```

Фикс `e07fd5c32`:

```
track 9101 readiness= None
track 9102 readiness= None
track 9103 readiness= None
pending intents: 0
intent triggers: []
linked intents: []
{'resumed': 0, 'terminal': 0, 'waiting': 0, 'failed': 0}
deliveries: []
```

## 4. Смежные наборы: паритет база ↔ фикс

Одинаковые команды, один и тот же интерпретатор (`adminbot/.venv`,
`PYTHONPATH` = корень соответствующего worktree):

| Набор | База | Фикс |
|---|---|---|
| `test_evol_vision_sync_core` + `test_evol_vision_sync_wave2` + `test_native_reply_media_context_round1024` + `test_p1_semantic_routing_demotions` | 109 passed | 109 passed |
| `test_p0_vision_fix_core` + `test_rc_target_media_evidence` + `test_p0_meme_image_only` + `test_p0_goal_media_2026_11_25` | 142 passed | 142 passed |
| `test_direct_chat` | 161 passed | 161 passed |

Итого 412 passed на каждой стороне, 0 fail. Предупреждение
`WARNING: closed 1 leaked aiosqlite connection(s)` (группа 109) присутствует
одинаково на базе и на фиксе — не связано с изменением.

`py_compile` (direct_chat_service.py, новый тест) — OK; `git diff --check` — OK.

## 5. Остатки и ограничения

- C2 (одно фото связывается с двумя намерениями; чужой автор) — отдельная линия
  `fix/p0-media-bind-f2`, здесь не трогалась.
- Не-image медиа с подписью, буквально содержащей vision-intent фразу
  («что на фото»): после фикса такая подпись проходит через **нетронутую**
  текстовую ветку `:15442-15487` и создаёт намерение — как и на базе (там — через
  media-dependent путь). Поведение не ухудшилось; это тот же residual, что в
  диагнозе §4, и он вне согласованной границы F1.
- Видео **без** превью: актива нет → ход перестаёт быть медиа-зависимым
  (на базе — фантомное намерение). Это прямое следствие назначенного предиката,
  а не отдельное изменение; зафиксировано тестом-границей.
- Production-трасса не читалась (lane rule): точная последовательность инцидента
  и per-chat effective flags остаются неподтверждёнными; воспроизведение даёт
  тот же наблюдаемый эффект (описание одного фото в ответах на разные треки).
- Визуальный слой не менялся — Playwright/Browser Use не применимы.

## 6. Очистка

- Временный base-worktree для RED/паритета (`P0-MEDIA-F1-RED`) создан через
  `workflow_housekeeping.py worktree-path` + `register-worktree`, удалён через
  `git worktree remove` + `unit-close` после прогонов.
- Одноразовый probe-скрипт из обоих worktree удалён; новых файлов вне
  `services/direct_chat_service.py` и теста нет.
- Deploy/merge/map/queue не выполнялись.
