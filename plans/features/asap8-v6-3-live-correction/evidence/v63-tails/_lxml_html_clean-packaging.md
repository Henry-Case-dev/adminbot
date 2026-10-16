# F2 — дефект formation-слоя: `trafilatura` не импортируется из чистого `requirements.txt`

Лейн FIX-TAILS-EV · 2026-10-16 · HEAD `9e63b3cf` + незакоммиченный бандл · без коммитов/деплоя.
Ревью-источник: `review-tails.md` F2 (+F5). Ниже — воспроизведение, механизм, выбранная правка.

## Что закрыто

`pip install -r requirements.txt` в чистом окружении **не даёт импортируемую `trafilatura`**:
`trafilatura` 2.x требует `justext>=3.0.2`, jusText 3.0.2 требует `lxml[html_clean]>=4.4.2`,
а lxml 6.x держит `lxml.html.clean` в отдельном пакете `lxml_html_clean`, который этот extra
на старом pip **не ставит**. Пакет ставился в канонический `.venv` вручную (в `pip list`
«Required-by» пуст) — канонический env из `requirements.txt` был невоспроизводим.

## Цепочка (метаданные, снято локально)

- `trafilatura 2.2.0` → `justext>=3.0.2`, `lxml>=6.1.1`;
- `justext`/`jusText 3.0.2` → `lxml[html_clean]>=4.4.2` (underscore);
- `lxml 6.1.1` → `lxml_html_clean; extra == "html-clean"` (hyphen, PEP 685-нормализованный);
- lxml 6.1.1 сам отдаёт только заглушку `lxml/html/clean.py` (backward-compat shim):
  `from lxml_html_clean import *` + понятный `ImportError`, если пакета нет.

## Наблюдения (первый конфиг с дефектом — системный интерпретатор)

`py -3` = CPython 3.12.0, `pip 23.2.1`:

```
trafilatura == 2.0.0
lxml == 6.1.1
lxml_html_clean == ABSENT
jusText == 3.0.2
$ py -3 -c "import trafilatura"
ImportError: lxml.html.clean module is now a separate project lxml_html_clean.
Install lxml[html-clean] or lxml_html_clean directly.
```

То есть `trafilatura` установлена, но не импортируется — `services/web_content_extractor.py`
(импорт с `except ImportError → trafilatura = None`) трактует её как отсутствующую.

Механизм (marker-эвалюация extra в vendored packaging того pip, что ставил окружение):

| pip | vendored packaging | `Marker('extra == "html-clean"').evaluate({"extra": "html_clean"})` |
|---|---|---|
| `.venv` pip 26.1.2 | 26.2 | **True** (PEP 685-нормализация обеих сторон) |
| `py -3` pip 23.2.1 | 21.3 | **False** → `lxml[html_clean]` ничего не доставляет |

Отсюда: с современным pip extra случайно разрешается, а с pip, который CPython 3.12.0
отдаёт вместе с `venv` (23.2.1), — нет. Канонический env не должен зависеть от версии pip.

## Изоляция «в Python, где разница только в этом пакете»

`.venv` (trafilatura 2.2.0 / lxml 6.1.1 / lxml_html_clean 0.4.5), пакеты не удалялись —
наличие `lxml_html_clean` переключалось meta-path-блокером:

```
MASKED  -> import trafilatura FAIL ImportError
   msg: lxml.html.clean module is now a separate project lxml_html_clean. | Install lxml[html-clean] or lxml_html_clean directly.
PRESENT -> import trafilatura OK 2.2.0
```

Вывод: единственная разница между рабочим и нерабочим состоянием — **наличие пакета
`lxml_html_clean`**, поэтому в `requirements.txt` называется пакет, а не extra `lxml[html_clean]`
(extra зависит от нормализации имён на стороне pip — именно тот слой, который и дал дефект).

## Правка

`requirements.txt` (+5 строк: комментарий + одна зависимость), sha256 `15157fb4f3317eda…`:

```
lxml_html_clean>=0.4.1
```

Почему такой пакет/порог: `0.4.1` — начало линии 0.4 (PyPI, 2024-11-15), резолвер берёт
текущую `0.4.5` (PyPI, 2026-05-20, заявляет `lxml>=6.1.1`) — та же версия, что проверена
в `.venv` с lxml 6.1.1 и trafilatura 2.2.0. Полный fresh-venv install не гонялся
(сеть/время); референс — наблюдение ревьюера в чистом venv 2026-10-16 и первый конфиг
выше, воспроизведённый здесь.

Документирующий комментарий — там же, в `requirements.txt` (стиль файла: русские
комментарии с причиной). `README.md:32` («Быстрый старт» → `pip install -r requirements.txt`)
этот лейн не правит — вне WRITE_SCOPE; сам фикс строки зависимости README-комментария не требует.

## Влияние

- На 6 node id ревью — влияния нет: `mca02` зелёный на обоих интерпретаторах после `9e63b3cf`
  (FIX-SSRF: чтение гарда до проверки уровня-1), `mca16` — после re-pin (см. матрицу).
- Прод-путь web-экстрактора: без `lxml_html_clean` уровень-1 выключен и экстракция уходит в
  облачные фолбеки (риск F5). **Прод не проверялся** (SSH запрещён) — состояние прод-venv
  остаётся за DevOps/Архитектором.
