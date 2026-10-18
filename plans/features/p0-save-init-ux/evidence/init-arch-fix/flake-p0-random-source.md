# Находка: pytest-сессионная утечка `mca_random_source` (singleton ↔ закрытая БД)

Класс: `related-nonblocking` — предсуществующая тест-изоляционная особенность
ПЛАТФОРМЫ (не дефект продукта), проявившаяся при добавлении нового тест-файла
в сессию; вклад нового файла устранён в этом лейне. Прод-код не менялся.

## Наблюдение (один провал в объединённом прогоне, 1 из 8 запусков)

Прогон 9 файлов: `1 failed / 134 passed`;
`tests/test_p0_initfix_initiative_observer.py::test_opportunity_carries_context_into_writer_and_sends`
— `payload["counters"]["sent"] == 0` при ожидании 1. Captured log:

```
WARNING services.mca_random_source ... [random_source] reserve read failed
ValueError: no active connection            (aiosqlite: БД уже закрыта)
WARNING services.mca_random_source ... [random_source] fallback state write failed
... random_fallback | outcome=silent | deferred ...   → инициатива отложена
```

## Механизм (предсуществующий)

1. `services/mca_random_source.get_service(db)` — **модульный singleton**:
   первый вызов с БД `bind`-ит его (`_service = RandomSourceService(db)`);
   повторные вызовы переиспользуют singleton (перепривязка только если
   `_service.db is None`).
2. Любой тест, дошедший до `handle_initiative(...)`, вызывает цепочку
   exploration → `get_service(db)` → singleton привязывается к БД ЭТОГО теста.
3. Тест закрывает свою БД в `finally` — singleton остаётся связанным с
   ЗАКРЫТОЙ БД и живёт до конца процесса pytest.
4. Следующие файлы сессии при probability-draw (`memory.random_exploration_probability`,
   дефолт 0.05) получают `no active connection` → fallback →
   `random_fallback` (initiative deferred) → ожидаемый `sent=1` не наступает.
   При 5% вероятности draw это редкий (~5–12% на прогон) флейк чужого теста.

## Проба (RED → GREEN, scratch)

`OPENCODE_WORKFLOW_SCRATCH/init-arch-fix/probe_random_bind.py`:

```
status: completed | sent: 1
singleton: создан; db is None: False
singleton db — это БД теста: True
после close(): singleton держит ЗАКРЫТУЮ БД: True
```

`OPENCODE_WORKFLOW_SCRATCH/init-arch-fix/probe_singleton_clean_test.py`
(проба сразу после нового файла):

* RED (до правки): `1 failed, 17 passed` — singleton оставлен связанным;
* GREEN (после правки): `18 passed`.

## Правка в лейне (минимальная, тест-гигиена)

`tests/test_p0_init_arch_fix_observer.py` — autouse-фикстура `_clean` теперь
делает `mca_random_source.reset_service()` до и после каждого теста
(штатный тестовый сброс, объявленный в самом сервисе). После файла singleton
чист → следующие файлы сессии привязывают его к своей ОТКРЫТОЙ БД.

## Остаток (вне объёма лейна, предсуществующий)

Внутри самого `test_p0_initfix_initiative_observer.py` первый send-тест
привязывает singleton к своей БД, а `test_pending_direct_request_stops_observer_initiative`
далее работает с закрытой (его ассерты `sent==0` это маскируют — падение
возможно только в чужих ожиданиях sent>0 при удачном draw). Это свойство
существовало до лейна; починка (reset в его фикстуре) не входит в объём
INIT-ARCH-FIX и оставлена для владельца шва.

Повторные прогоны после правки: набор 9 файлов — 3×135 passed, 0 failed;
новый файл отдельно — 17 passed.
