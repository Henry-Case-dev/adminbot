# REVIEW-W7-TAILS — проверка коммита `5c04dd85` (N1 refresh + N2 hot-over-env assert)

| Поле | Значение |
|---|---|
| Коммит | `5c04dd85ea60f8ad945b3e26fcb0d8d9cafa9cb0` (3 файла, +8) |
| Вердикт | **Approved** — состав точный, инвариант защищён, witness легитимен (воспроизведён), N1-эвиденс = 97 подтверждён |

## 1. Состав и diff

- Ровно 3 файла: `tests/test_soul1_w7_embedding_primary_slot.py` **(+8, один хаунк)**, новые/перегенерированные `evidence/w7/mutation-witness-embedding-n2.txt` (1216 B, UTF-16LE+BOM, CRLF) и `evidence/w7/pytest-embedding-suites.txt` (368 B, UTF-16LE+BOM, CRLF). Ничего больше не менялось; дрейфа рабочего дерева к коммиту нет (`git diff` по трём путям пуст).
- В тесте — **один** assert на инвариант: при непустом env (`_settings_value` → `SENTINEL-ENV-KEY`) и заданном hot `_keys(both_layers)["primary"] == "hot"`; конвенция соблюдена, маркер `TEST-LIFECYCLE: REGRESSION owner=W7/N2` на месте. Инвариант соответствует коду: `resolve_key_slot` (`services/embedding_control_plane.py`) проверяет hot **раньше** env.

## 2. Мутация (мой перепрогон в изолированном worktree на `5c04dd85`)

- Сделал ровно записанную мутацию (env-ветка перед hot-веткой в `resolve_key_slot`) → **1 failed, 6 passed**; падение ровно на новом assert (строка 86, `assert 'env' == 'hot'`) в `test_primary_from_hot_is_distinguished` — совпадает с witness дословно.
- Restore (`git checkout`) → **7 passed**; sha256 восстановленного `embedding_control_plane.py` = `4f892f766f5cf3e310bfbb413b9216566e02bfe88276ffd1f52871e4fd2e1f49` — **байт-в-байт** как в witness/коммите. Worktree удалён после проверки.
- Запись witness (`mutations=1 killed=1 bad=0 restored=True`) легитимна: RED именно по контракту, restore полный, GREEN на нём же.

## 3. N1-эвиденс и число

- `pytest-embedding-suites.txt`: 368 байт, UTF-16LE+BOM, CRLF; текст `97 passed in 18.77s` — конвенция семейства соблюдена (как `pytest-embedding-sweep.txt`).
- Мой прогон 4-файлового embedding-набора (`test_asap8_f8_embeddings` 10 + `test_embedding_control_plane_asap4` 69 + `test_asap44_graphrag_batch_breaker` 11 + `test_soul1_w7_embedding_primary_slot` 7) → **97 passed** ✓ (N1 закрыт: прежний stale «1 failed, 96 passed» перегенерирован).

## Итог

Микро-коммит закрывает ровно два хвоста review-w7 (N1 stale-артефакт; N2 тест-гэп) без побочных изменений. Замечаний нет.
