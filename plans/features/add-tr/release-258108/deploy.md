# REL-258108 — деплой 2.58.108 и postdeploy-позитивы (DevOps, 22.10.2026)

Кандидат: `be60041f` (runtime-дельта `services/mca_vision.py` strip-fence +
version-токен, REV-REL-258108 **Approved**). Задеплоен `be60041f`
(origin/master, `git pull --ff-only`). ΔDDL=0. Планшет — `deploy.json`,
postdeploy-пробы — `postdeploy-probes.json`.

## Выкат

| Параметр | Значение |
|---|---|
| T0 | 2026-10-21T18:19:57Z (рестарт плановый, review-sanctioned) |
| healthz loopback:8000 | 200 `{"status":"ok","version":"2.58.108"}` |
| healthz публичный 443 | 200 `2.58.108` |
| Сервис | active/running, MainPID=285197, **NRestarts=0**, ExecMainStatus=0 |
| Journal с T0 | 2182 строк (на 19:13Z), **0 CRIT / 0 Traceback**; boot 18:20:19→18:20:40→18:20:42Z |
| Блобы сервера vs кандидат | `config/settings.py` `0b84f9afdf80`, `services/mca_vision.py` `8c1051d1a7dc` — **OK**; прод-байты mca_vision.py (SFTP) sha256 == кандидату |

Server-reported HEAD = `be60041fdae1fcf8d427cc10fc8dbd7559d9f266` — совпадает с
одобренным кандидатом (сверено независимо, не только локально).

## Postdeploy-позитивы (review-rel.md п.2–3; 12/12 assert)

Офлайн-harness на прод-байтах (FakeBot, реальные провайдеры apinet,
**0 сообщений в Telegram**); идентичность прод-байтов кандидату — blob+sha256.

- **(d) strip-fence**: fenced-валидный JSON → `ready` (описание распарсено);
  fenced-невалидный и обрывок → честный `failed/parse_error`; bare JSON →
  прежний путь. Строгая валидация не ослаблена.
- **(a) OFF**: генерация при `vision_enabled=false` — фото доставлена
  (470 890 B), postgen `off/vision_disabled`, блок `image_analysis status="off"`,
  **0 vision-вызовов**. Replay `maybe_handle_keyword`: new gen=1, `delivery="sent"`
  — **байт-в-байт прецедент w3** (is_already=false; PG-journal already-replay
  офлайн недостижим по дизайну, harness-r1-notes) — регресса нет.
- **(b) DEDUP**: replay того же update → `DIRECT_UPDATE_DEDUP_HIT`
  (0 llm / 0 vision / 0 отправок); postgen-анализ тех же bytes →
  **`cache_hit=true`, 0 повторных vision-вызовов**.
- **(c) S-кейсы**: S3 голое фото → UNHANDLED (0 llm, 0 отправок); S4
  «что на картинке?» → ответ без vision и recognize_image; S7 «как нарисовать
  кота?» → объяснение, 0 генераций.
- **S9 / POSTGEN-ON**: полный ход Vision ON — фото 480 826 B доставлена,
  postgen **`ready`**, описание фактического bitmap («A red square object
  centered on a plain white background.»), блок `image_analysis status="ready"
  source="final_bitmap"`, 2 vision-вызова, Writer-ответ по факту картинки.
- **P0V-06c heavy**: fixture 960×2600/1 114 350 B через штатный
  `validate_or_normalize`+`analyze_adaptive` на прод-байтах — **`ready`, GT 3/3**
  (ZEBRA77, QUARTZ88, LOTUS99), 1 vision-вызов (до фикса: failed/parse_error).

Бюджет провайдеров: 12 LLM + 3 vision + 3 gen + 0 embed.

## SSH/fail2ban-дисциплина

recon 18:18:00Z (~15с) → пауза 95с → основной прогон 18:19:57Z (pull →
blob-check → SFTP прод-байтов → рестарт → верификация, один коннект) →
финальная верификация 19:13:51Z. Итого 3 коннекта, auth-отказов 0, креды не
печатались. Сообщений в чаты: 0.

## Биндинг

`deployed_commit` add-tr карты → `be60041f`; ADTR-POSTGEN-OFF и
ADTR-POSTGEN-DEDUP → **VERIFIED** (postdeploy-пробы); S9/DOD3(2)/POSTGEN-ON и
P0V-06c (p0-vision карта, строка) — postdeploy-эвиденс добавлен.

## Release-гейт (`--stage release --candidate be60041f --deployed-commit be60041f`)

EXIT=1, scoped=59, errors=82 (полный вывод — `release-gate.txt`). Map-уровень
зелёный: candidate/deployed совпадают, источник не изменён, mandatory-статусы
VERIFIED. Остатки — два структурных класса, оба ожидаемы конвенцией
исторических биндингов:

1. `no evidence bound to reviewed candidate` (~50 строк: TOOLS/GRID/ENTRY/
   REG/POSTGEN-ветки, DoD1/2/4/5 и manual-строки) — каждая строка
   верифицирована против СВОЕГО кандидата (1b03c428/948c2004/113f3a62/
   1cf0f400/76b156e0) в своих лейнах. Поезд `3a178c6c..be60041f` меняет
   только `services/mca_vision.py` (парсер, единственный call-site VLM-анализ)
   + version-токены — код этих строк диффом не задет; blob-identity, pins24
   868/0, F8 --check 582==REGISTRY и офлайн-агрегат 17/17 покрывают
   «не сломалось». Повторное воспроизведение 20+ исторических проб против
   байт-идентичного кода новой информации не добавляет. Не структурная дыра.
2. `live requirement lacks evidence for stage release` (live-строки, включая
   обновлённые OFF/DEDUP/ON/DOD3) — гейт ждёт тип `live/production`,
   привязанный к кандидату релиза. Инженерные live-пробы выполнены на
   максимально достижимом агентом уровне: прод-байты (blob/sha256 == кандидату,
   server-reported HEAD, healthz 2.58.108) + реальные provider-вызовы +
   FakeBot-доставка (0 сообщений в реальные чаты — постоянный запрет).
   Тип честно `provider`, как весь harness-эвиденс проекта; живая
   наблюдаемость на реальном трафике — добровольные owner-наблюдения
   (решение 18.10.2026), агентом недостижимы без нарушения запрета.

p0-vision карта: строка P0V-PIPE-CONTEXT обновлена; map-level
candidate/deployed (113f3a62) не в write-scope лейна — гейт этой карты не
прогонялся (дал бы ожидаемый candidate-mismatch).

## Откат

Ветка `release/fix-2.58.107` = `3a178c6c` запушена в origin. Процедура:
`git checkout release/fix-2.58.107` + `sudo systemctl restart admin_bot`.
Миграций нет (ΔDDL=0), откат чистый.

## Замечания (не блокеры)

- В `.venv` нет Pillow: heavy-секция общего окна упала до записи
  (ModuleNotFoundError); изолированный прогон на прод-байтах глобальным
  `py -3` (Pillow 12.2.0, интерпретаторный прецедент w1–w5) — ready GT 3/3.
- Пустая loopback-проба в main-прогоне на +14с — сервис начал слушать в
  18:20:40Z (journal); финальные пробы 200 OK.
- OFF-ответ эхо-повторяет предмет промпта с явной пометкой «распознавание
  отключено» — известное наблюдение w3 (тюнинг Personality Core, не контура).
