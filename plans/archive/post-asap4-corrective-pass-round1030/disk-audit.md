# T-4505 — Disk audit прода (read-only) — 02.10.2026

Feature: `post-asap4-corrective-pass` · Задача: **T-4505 [@DevOps]** · Критерий: R5-B-001 — таблица «каталог → размер → тип → класс → вклад в рост» + воспроизводимые команды.
Исполнитель: DevOps · Дата: 2026-10-02 (снимок 10:05–11:15 UTC) · Хост: `racknerd-f4e3456` (198.46.175.136), Ubuntu, ядро 6.8.0-134.
Метод: **только чтение** (df/du/ls/find -printf/stat/journalctl --disk-usage/docker system df/dpkg -l). Ничего не удалено и не изменено. R17-safe: секреты не читались, в отчёте только имена файлов.

## 0. Воспроизводимые команды (evidence)

```bash
df -h
du -xh --max-depth=1 / | sort -rh
du -xh --max-depth=2 /var/www/admin_bot | sort -rh
ls -lahS /var/www/admin_bot/
find /var/www/admin_bot -maxdepth 2 \( -name '*.db' -o -name '*.db-wal' \) -type f -exec ls -lh {} \;
find / -xdev -type f -size +50M -printf '%s|%TY-%Tm-%Td %TH:%TM|%p\n' | sort -rn | head -25
journalctl --disk-usage; docker system df; dpkg -l | grep linux-image
stat -c '%s|%y|%n' <ключевые файлы>
```
Ограничения: `sudo` недоступен без пароля (владелец знает); `/root` не читаем (не читался — read-only контракт), docker-слой виден только через `docker system df` (du как nik его не проходит).

## 1. Общая картина (df -h)

| Маунт | Размер | Занято | Свободно | Use% |
|---|---|---|---|---|
| `/dev/vda2` (корень, единственный реальный FS) | 24G | **18G** | 4.4G | **81%** |
| tmpfs (/run, /dev/shm, /run/lock, /run/user) | ~1G суммарно | <2M | — | 2% |

Рост подтверждён: занято 18G из 24G. Свободный остаток 4.4G — этого мало для комфортного деплоя + суточного бэкапа (очередной daily-бэкап добавит +1.2G).

## 2. Верхний уровень (du -x --max-depth=1 /)

| Каталог | Размер | Комментарий |
|---|---|---|
| /var | 7.0G | из них /var/www/admin_bot 6.3G |
| /usr | 4.0G | системный софт (libLLVM ×2, deno, dockerd, buildx) |
| /home/nik | 2.0G | два каталога DB-бэкапов |
| **/swapfile** | 2.0G | в du корня; swap, mem всего 961MB — swap критичен |
| /opt/headroom | 790M | venv-обвязка (litellm/transformers) + ротир. логи 56M |
| /boot | 200M | 2 ядра (134 running, 142 installed) |
| /tmp | 153M | pytest-артефакты 88M |
| /var/lib/docker | ~1.45G | **не виден du без root**; из `docker system df`: images 1.39GB (4 шт, все active, 0B reclaimable) + volumes 69MB |

## 3. Приложение /var/www/admin_bot (6.3G)

| Каталог/файл | Размер | Тип | Класс | Действие |
|---|---|---|---|---|
| `local_database.db` (+WAL 17M, shm 64K) | **1.30G** | рабочая БД (SQLite, live: mtime 11:10) | **PROTECTED** | не трогать |
| `backups/local_database_20261002.db` | 1.20G | суточный авто-бэкап (сегодня 00:00) | **PROTECTED** | хранить (ретеншн: 1 шт — старые daily уже вычищены) |
| `pre_migration_20261002_101544.db` | 1.20G | pre-migration копия, создана сегодня 10:16 | **PROTECTED** | якорь текущего corrective pass — держать до T-4509 |
| `local_database.db.bak.2026-09-15-0744` | **0.71G** | старый ad-hoc бэкап БД от 15.09 | **DISPOSABLE** | удалить; перекрыт v19/v21/pre_migration/daily |
| `migrate_history/` (4 JSON: 2026.json 458M, «желтая до 10.2024» 256M, 10.08.2025 169M, 10.2024 152M) | **1.01G** | сырые экспорты истории (источник миграции от 04.09) | **DISPOSABLE (условно)** | данные уже импортированы в БД; сначала выгрузить за пределы сервера (off-site архив), затем удалить. Требует подтверждения owner |
| `venv/` | 404M | runtime-окружение | PROTECTED | не трогать (deploy-зависимость) |
| `.git/` (pack 163M) | 268M | репозиторий (deploy ff-only) | PROTECTED | не трогать в ходе pass'а; после — опционально `git gc` (~0.05–0.15G) |
| `media/` (leha_greeting 50M, common 23M, olya 22M, slavik 2M) | 96M | пользовательские медиа | **PROTECTED** | не трогать |
| `plans/` | 32M | доки процесса | PROTECTED | не трогать |
| `chrome-profile/` | 5M | профиль браузера | PROTECTED (рабочий) | не трогать |
| `.env` + ~40 шт `.env.bak.*` | ~0.3M | конфиг + копии (epic26…epic85, round*, inc-*) | PROTECTED (текущий) / гигиена | `.env` не трогать; `.env.bak.*` содержат секреты (perms 600 ок) — сократить количество до 1–2 последних вне дискового контекста (размер несущественен) |
| код, тесты, web, tools, прочее | ~50M | исходники | PROTECTED | не трогать |

Примечание: каталогов `data/` и `var/` (cover_style_assets) в приложении **нет** — рабочая БД и бэкапы лежат в корне приложения и `backups/` (см. выше); `var/` пуст (4K).

## 4. Вне приложения

| Позиция | Размер | Дата | Тип | Класс | Действие |
|---|---|---|---|---|---|
| `/home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db` | **1.19G** | 01.10 | версионный rollback-якорь pre_v21 | **PROTECTED** | хранить (последний именованный якорь; см. §7 — пересмотр после T-4509) |
| `/home/nik/backups/pre_mca_v19_20260929_052904.db` | **0.79G** | 29.09 | устаревший якорь v19 | **DISPOSABLE** | удалить; перекрыт pre_v21 (01.10) и pre_migration (02.10) — правило «1–2 последних» |
| `/swapfile` | 2.00G | 11.09 | swap (RAM 961MB, swap used 1.0/3.0G) | **PROTECTED** | не трогать |
| `/opt/headroom/venv` | 719M | 11.09 | runtime сервиса-headroom (guard диска) | PROTECTED | не трогать в ходе pass'а |
| `/opt/headroom/home/.headroom/logs/proxy.log.1–.5` | 50M | 17–21.09 | ротированные логи | **DISPOSABLE** | удалить ротир. копии, активный `proxy.log` (5.2M) оставить |
| `/var/lib/docker` (images 1.39GB, volumes 69MB) | ~1.45G | — | 4 активных контейнера: telegram-bot-api, postgres:16, bgutil-pot, cobalt | **PROTECTED** | 0B reclaimable — чистить нечего |
| `/var/log/journal` | 196M | — | systemd journal (кап SystemMaxUse=200M уже установлен) | PROTECTED (кап) | опционально `journalctl --vacuum-size=100M` → ~+0.09G |
| `/var/lib/apt/lists` + `/var/cache/apt/*.bin` + archives | 319M | 02.10 | apt-кэши (регенерируемые) | **DISPOSABLE** | `apt-get clean` + `rm -rf /var/lib/apt/lists` → восстановятся при первом `apt update` |
| `/tmp/pytest-of-nik` | 88M | сегодня | тестовые артефакты | **DISPOSABLE** | удалить (регенерируется прогоном тестов) |
| `/boot` (vmlinuz+initrd 134 и 142) | 200M | — | 2 ядра: 134 running, 142 installed | PROTECTED | удалять нельзя (142 — следующий boot); rc-записи 136–139 — только конфиги, ~0 |
| старые ядра (rc: 6.8.0-31/-136/-137/-138/-139) | ~0 | — | остатки конфигов | DISPOSABLE (~0) | `dpkg -l`-мусор, эффекта нет |
| `/usr` (libLLVM×2 267M, deno 95M, dockerd 108M, buildx 72M, прочее) | 4.0G | — | системные пакеты | PROTECTED | не трогать |

## 5. ТОП файлов >50MB (find / -xdev, топ-15 из 25)

| Размер | Дата | Файл | Класс |
|---|---|---|---|
| 2.00G | 11.09 | /swapfile | PROTECTED |
| 1.28G | 02.10 11:10 | /var/www/admin_bot/local_database.db | PROTECTED (рабочая БД) |
| 1.20G | 02.10 10:16 | /var/www/admin_bot/pre_migration_20261002_101544.db | PROTECTED (якорь pass'а) |
| 1.20G | 02.10 00:00 | /var/www/admin_bot/backups/local_database_20261002.db | PROTECTED (daily) |
| 1.19G | 01.10 | /home/nik/backups_adminbot/…_pre_v21.db | PROTECTED (якорь) |
| 0.79G | 29.09 | /home/nik/backups/pre_mca_v19_20260929_052904.db | **DISPOSABLE** |
| 0.71G | 15.09 | /var/www/admin_bot/local_database.db.bak.2026-09-15-0744 | **DISPOSABLE** |
| 448M | 04.09 | migrate_history/2026.json | DISPOSABLE (условно) |
| 249M | 04.09 | migrate_history/желтая до 10.2024.json | DISPOSABLE (условно) |
| 164M | 04.09 | migrate_history/10.08.2025.json | DISPOSABLE (условно) |
| 148M | 04.09 | migrate_history/10.2024.json | DISPOSABLE (условно) |
| 134M | 21.04 | /usr/lib/…/libLLVM.so.20.1 | PROTECTED (система) |
| 115M | 26.08 | venv/…/playwright/driver/node | PROTECTED (runtime) |
| 98M | 30.08 | .git/objects/pack/pack-390efa02….pack | PROTECTED (deploy) |
| 56M+56M | 02.10 | /var/cache/apt/pkgcache.bin + srcpkgcache.bin | **DISPOSABLE** (регенерируемый) |

Полный топ-25 в evidence-логе; позиции 16–25 — системные библиотеки/списки apt (класс PROTECTED/DISPOSABLE-apt аналогично).

## 6. Итоги классификации

| Категория | Сумма | Детали |
|---|---|---|
| **PROTECTED (защищено)** | **≈14.4G** | рабочая БД+WAL 1.30 · якоря pre_v21 1.19 · pre_migration 1.20 · daily 1.20 · media 0.09 · venv 0.39 · .git 0.26 · система /usr+/boot 4.2 · swap 2.0 · docker ~1.45 · headroom-runtime 0.68 · journal/логи 0.20 · код/конфиг/прочее ~0.6 |
| **DISPOSABLE — безопасно сейчас (whitelist для T-4506/T-4507)** | **≈1.9G** | bak.2026-09-15 0.71 · pre_mca_v19 0.79 · apt-кэши 0.30 · pytest /tmp 0.086 · headroom ротир. логи 0.05 |
| **DISPOSABLE — условно (owner-confirm, off-site архив первым шагом)** | **+1.01G** | migrate_history/ (история уже в БД) |
| **Опционально** | +0.09G | journal vacuum 200→100M (кап и так 200M) |
| **Итого потенциал** | **1.9G сразу / ~2.9G полный** | после чистки: занято ~16.1G (75%), свободно ~6.3G |
| **Позже (вне текущего pass'а)** | +1.19G | pre_v21 — пересмотреть после успешного T-4509 (появятся новые якоря) |

## 7. Что выросло 10 → 18 GB (реконструкция по датам)

1. **Бэкапы-якоря БД, последние 4 дня (главный вклад, +4.4G):** pre_mca_v19 29.09 (+0.79) → pre_v21 01.10 (+1.19) → daily 02.10 (+1.20) → pre_migration 02.10 (+1.20). Каждый следующий якорь не вытеснял предыдущий — ретеншена «1–2 последних» не было.
2. **Рост самой БД (+0.57G):** 725M (15.09) → 1.28G (02.10); суточные бэкапы масштабируются вместе с ней.
3. **Начало сентября (+3.7G):** migrate_history 04.09 (+1.01), swapfile 11.09 (+2.0), headroom venv 11.09 (+0.67).
4. Прочее: apt-кэши (~0.3), journal до капа (0.2), docker-слой (~1.45, был всегда), pytest-tmp.
Сходится: ≈8.3G суммарно ≈ наблюдаемый рост 10→18G.

## 8. Находки-расхождения (для PM/Orchestrator)

- **Якорей с именами pre_v22/pre_v23 на диске НЕТ** (find по `*pre_v2*` по /var/www, /home, /opt). Фактические свежайшие якоря: `pre_v21` (01.10) и `pre_migration_20261002_101544.db` (сегодня 10:16, root) — последний и есть якорь текущего pass'а. Если pre_v22/pre_v23 ожидались — они не создавались либо названы иначе.
- **Суточный auto-бэкап жив** (backups/local_database_20261002.db, 00:00), retention фактически = 1 шт — старые daily отсутствуют, это ок.
- **Docker не пустой, но не disposable**: 4 образа, 4 контейнера активны (telegram-bot-api, postgres:16, bgutil-pot, cobalt), 0B reclaimable.
- **journald уже ограничен** (SystemMaxUse=200M, занято 195M) — роста дальше не будет.
- `sudo` на сервере требует пароль — аудит выполнен из-под nik, `/root` не проверен (по ls-косвенным данным незначим); docker-слой оценён через `docker system df`.

## 9. Рекомендуемый whitelist для T-4506/T-4507 (явные пути, без масок)

```
/var/www/admin_bot/local_database.db.bak.2026-09-15-0744        # 0.71G
/home/nik/backups/pre_mca_v19_20260929_052904.db                # 0.79G
/tmp/pytest-of-nik                                              # 88M
/opt/headroom/home/.headroom/logs/proxy.log.[1-5]               # 50M
apt-get clean + rm -rf /var/lib/apt/lists/*                     # ~0.30G (регенерируемое)
# после owner-confirm и off-site архивации:
/var/www/admin_bot/migrate_history/                             # 1.01G
# НЕ включать: pre_v21, pre_migration_20261002, daily 20261002, media/, .env*, chrome-profile/
```
Ожидаемый результат T-4507: занято 18G → ~16.1G (−1.9G), свободно 4.4G → ~6.3G; при подтверждении owner по migrate_history — до ~15.1G (−2.9G).
