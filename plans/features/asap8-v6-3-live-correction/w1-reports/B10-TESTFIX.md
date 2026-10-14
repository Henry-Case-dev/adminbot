# B10-TESTFIX — фикс устаревшего теста конкуренции direct_chat

Лейн: B10-TESTFIX · HEAD: bc91b90 · WRITE_SCOPE: только tests/test_direct_chat_concurrency.py · не закоммичено.

## Диф-суть (19 insertions, 1 файл)

1. **Фикстура `direct_l1_off`** (после `lock_wait_short`): пин `DIRECT_L1_ENABLED=False`, autouse-нет, повешена маркером `@pytest.mark.usefixtures("direct_l1_off")` на класс `TestDirectChatConcurrency` (все 4 теста). Ассерты не тронуты.
2. **FakeDB**: добавлены заглушки `get_active_participants -> []` и `get_running_summary -> None` (опциональный пункт): оба вызова в `direct_chat_service` обёрнуты try/except и сейчас падали AttributeError → `logger.warning(... exc_info=True)` на каждый handle. Заглушки возвращают те же эффективные данные (window-only / no summary), убирая warning-шум. Поведение/ассерты не изменены.

## Применённый паттерн патча settings

Бриф предлагал `monkeypatch.setattr("services.direct_l1.settings", Settings(...))`, но в коде `services/direct_l1.py:35` — `from config.settings import settings` (синглкет-инстанс, гейт `direct_l1_enabled()` читает `getattr(settings, "DIRECT_L1_ENABLED", True)`, ClassVar → инстанс видит класс-атрибут). По оговорке брифа («если класс-синглкет — используй существующий паттерн») применён **канонический паттерн F1** из test_direct_chat.py:50-58 (и ещё ~11 смежных файлов):

```python
from config.settings import Settings
monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
```

Identity-риск после `importlib.reload(config.settings)` нейтрализован autouse-фикстурой `_settings_module_identity_restore` (tests/conftest.py:22-44).

## pytest

- RED (stash-проба исходника, до фикса): `test_third_handle_waits_for_slot_at_n2` — **1 failed** (воспроизведён локально, RCA подтверждён: L1 default-ON давал 3 LLM-вызова на handle).
- GREEN после фикса: `py -3 -m pytest tests/test_direct_chat_concurrency.py -q` → **4 passed** in 3.10s (2 warnings — предсуществующие PytestConfigWarning про timeout-опции, не связаны).
- `git diff --stat`: 1 file changed, 19 insertions(+), 0 deletions.

## Фингерпринт кандидата

HEAD bc91b90 + uncommitted diff `tests/test_direct_chat_concurrency.py` (sha256 диффа: `b0702e57e0df…`).

## Инцидентальные находки

- В worktree есть чужие незакоммиченные изменения (services/disk_retention.py, plans/*, tools/*) — другие лейны, не тронуты.
- `related-nonblocking`: ни один из 4 тестов файла не проверяет L1-топологию — пин OFF не маскирует покрытие; L1-ветка покрыта tests/test_asap7_direct_l1.py (конвенция модуля соблюдена).
