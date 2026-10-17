Найдено живым прогоном 2.58.86 (21:55:18Z), подтверждено дважды.

# Дефект: глобальное сохранение `style.policy` — молчаливый no-op

## Симптом (живое доказательство)

1. `POST /api/speech/style {"document": <пустой валидный>, "scope": "global"}`
   → `200 {"ok": true, "result": {"applied": true, "scope": "global",
   "revision": 1, ...}}` — «сохранено».
2. Журнал процесса:
   `/var/www/admin_bot/services/style_policy.py:2275: RuntimeWarning: coroutine
   'ConfigCache.set' was never awaited`.
3. PG: строки `style.policy` в `bot_settings` **нет** (перечень ключей
   `character.core`/`character.prompt_history`/`flags.*` её не содержит);
   `GET /api/speech/style` отдаёт `source=default`, `global_present=false`.

## Корень

`services/style_policy.py:2275` — единственная запись глобального документа
вызывает **асинхронный** `ConfigCache.set` (`services/config_cache.py:681:
async def set(...)`) **без await**. Исключение не возникает (создаётся и
выбрасывается корутина), поэтому:
* функция возвращает `applied=True`, UI показывает «Правила сохранены (новая
  ревизия политики)» (web/app.js:19053),
* фактически ни PG, ни in-memory кэш не обновляются.

Чат-ветка того же метода работает (использует `await set_root(...)`), поэтому
per-chat правила сохраняются; ломается только scope «Глобально» (в UI это
явный выбор, по умолчанию — «чат», когда активен чат).

## Минимальная правка (1 строка)

```diff
--- a/services/style_policy.py
+++ b/services/style_policy.py
@@ -2273,7 +2273,7 @@ async def save_policy_document(document: Mapping[str, Any], *,
             await set_root(int(chat_id), patch)
             scope = "chat"
         else:
-            target.set(DOC_KEY, normalized, category=DOC_CATEGORY)
+            await target.set(DOC_KEY, normalized, category=DOC_CATEGORY)
             scope = "global"
```

Регресс-тест (RED на текущем коде, GREEN после правки; в
`tests/test_soul1_style_policy.py`):

```python
def test_global_save_persists_with_async_cache():
    """REGRESSION owner=SOUL-16.1.4 (live 2.58.86): ConfigCache.set — async;
    без await глобальный документ не персистится, а API отвечает applied=True."""
    import asyncio

    class AsyncCache:
        def __init__(self):
            self.data = {}

        async def set(self, key, value, category=None):
            self.data[key] = value

        def get(self, key, default=None):
            return self.data.get(key, default)

    cache = AsyncCache()
    res = asyncio.run(sp.save_policy_document(
        {"rules": [], "soft_instructions": []}, cache=cache))
    assert res["applied"] is True
    assert "style.policy" in cache.data          # RED до фикса
```

## Почему не пропущено ревью

Ни один тест не вызывал `save_policy_document` с асинхронным кэшем: в
`tests/test_soul1_style_policy.py` функция фигурирует только в AST-проверке
«единственный writer» (строка ~711). Продовый кэш — асинхронный, поэтому
дефект виден только в живом процессе. W6 e2e проверял POST-ответ, не
персистентность.

## Решение релизного лейна

В дерево релиза правка НЕ вносилась (deployed tip == eafbe2e7 == отревьюенный
кандидат + bump/runbook; несанкционированная правка продукта лейном релиза
недопустима). Дефект классифицирован как **current-blocker для пути «Сохранить
глобальные правила стиля»** и вынесен как №1 follow-up: правка 1 строка +
регресс-тест, затем штатный мини-релиз (2.58.87) с ревью. Эффективное
состояние прода от дефекта не страдает: без документа действует пустая
(заводская) политика — та же, что и при «сохранённом» пустом документе.
