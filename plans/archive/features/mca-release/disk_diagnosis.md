# disk_diagnosis.md — диагностика роста диска прода (D1-disk-diag)

Дата: 2026-10-07 08:23–08:26 UTC (время сервера). Метод: SSH `nik@198.46.175.136`,
строго read-only (df/du/ls/find/stat/systemctl show/git rev-parse). Бюджет
соединений по AGENTS.md: 1 recon + 1 основной батч, без ретраев. Ничего не
удалялось и не менялось. Результат сырых данных: Temp-лог `disk_diag_results.json`
(локально, вне репо).

## 1. df — было/стало

| Метрика | Было (контекст задачи) | Стало (07.10 08:24 UTC) |
|---|---|---|
| ФС | /dev/vda2 | /dev/vda2 |
| Размер | 24G | 24G |
| Used | ~14–18G | **21G** |
| Avail | ~5.7G (75%) | **2.0G (92%)** |
| Inodes | — | 16% (ок) |

Дельта ~40ч ≈ **+6.6 GB** — объясняется ниже, почти целиком копиями БД.
Других ФС роста нет (tmpfs пустые). Docker/snap/coredump отсутствуют
(4K/8K/4K). Inode-раздувания нет.

Сервис: `admin_bot` active/running, MainPID 238141; деплой 2.58.69,
commit `42f8963` (P0-хотфикс miniapp). Live-БД пишется (wal mtime = момент
проверки), load 0.05, uptime 91d. Прод жив.

## 2. Топ-рост за 48ч (find / -xdev -mtime -2 -size +50M)

| Файл | Размер | mtime (сервер) |
|---|---|---|
| /var/www/admin_bot/backups/pre_t5216_20261006_232333.db | 1.3G | Oct 6 23:24 |
| /var/www/admin_bot/pre_migration_20261006_121956.db | 1.3G | Oct 6 12:20 |
| /var/www/admin_bot/backups/local_database_20261007.db | 1.3G | Oct 7 00:00 |
| /var/www/admin_bot/backups/pre_t5273_20261007_045424.db | 1.3G | Oct 7 04:55 |
| /var/www/admin_bot/backups/pre_t5274_20261007_055326.db | 1.3G | Oct 7 05:53 |
| /boot/initrd.img-6.8.0-142-generic (apt-обновление) | 73M | Oct 7 06:11 |
| /var/cache/apt/pkgcache.bin + srcpkgcache.bin | 112M | Oct 7 05:26–06:11 |

Итого новых крупных файлов ≈ **6.6 GB за ~18 часов** (Oct 6 12:20 → Oct 7 05:53).
Остальной рост (apt/initrd ~185M) — фоновый шум от обновлений пакетов.

## 3. Классификация

### [backups] — главный виновник: 5.0G в backups/ + 1.3G в корне сервиса
| Путь | Размер | Дата | Рекомендация |
|---|---|---|---|
| backups/pre_t5216_20261006_232333.db | 1.3G | Oct 6 23:24 | Удалить (третья по старшинству копия, superseded двумя новее) |
| backups/pre_t5273_20261007_045424.db | 1.3G | Oct 7 04:55 | Оставить (2 новыхей) |
| backups/pre_t5274_20261007_055326.db | 1.3G | Oct 7 05:53 | Оставить (новейшая) |
| backups/local_database_20261007.db | 1.3G | Oct 7 00:00, root | Удалить (тройное покрытие одного дня: 23:23/00:00/04:54); либо оставить — ротация itself подхватит при след. дневном бэкапе |
| pre_migration_20261006_121956.db (корень сервиса) | 1.3G | Oct 6 12:20, root | Удалить/архивировать: миграции v32/v33 проверены 7 деплоями поверх; файл вне скан-зоны retention |
| /home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db | 1.2G | Oct 1 | Удалить (pre_v21, актуальная версия 2.58.69) |

### [root cause] — почему копии копятся
`services/disk_retention.py`: `DB_BACKUP_PATTERNS = ("local_database_*.db",
"memory_rebuild_*.db")`, `MIGRATION_BACKUP_PATTERNS = ("pre_migration_*.db")`.
Имена деплой-бэкапов **`pre_t*.db` в паттерны не входят** → каждая копия
(≈1.3G за деплой-тур) остаётся навсегда. Сегодня было ~7 деплоев → 3 копии
pre_t* + pre_migration. При таком темпе диск кончится за 1–2 дня.
Дополнительно: pre_migration-копия от 06.10 легла в корень сервиса, а не в
backups/ — вне скан-директорий retention.

### [git]
`/var/www/admin_bot/.git` = 335M (objects 334M, pack 199M). Рост от 7 pull'ов
есть, но это не драйвер дельты. Оставить; gc не требуется.

### [logs/journal]
/var/log = 343M (syslog 27M+34M, ротация работает); journal = 200M
(journalctl --disk-usage: 199.7M, лимитирован). Норма; опционально
`journalctl --vacuum-size=100M` даст ~100M.

### [прочее]
- migrate_history/ = 1.1G (2026.json 458M, «желтая до 10.2024» 256M,
  10.08.2025 169M, 10.2024 152M; mtime Sep 4) — исторические данные, НЕ
  новый рост; трогать без владельца нельзя (похоже на прод-данные).
- venv 404M, media 96M, plans 41M — норма.
- /tmp 189M (80M pytest-of-nik, деплой-скрипты p0_/t5274_) — опционально
  почистить, мело.

## 4. Верификация гипотезы

Суммарный вес копий БД, созданных в сегодняшних деплой/миграционных окнах:

| # | Файл | Размер | Окно |
|---|---|---|---|
| 1 | pre_migration_20261006_121956.db | 1.3G | pre-migration 06.10 12:19 |
| 2 | backups/pre_t5216_20261006_232333.db | 1.3G | деплой 2.58.64 |
| 3 | backups/local_database_20261007.db | 1.3G | ночной автобэкап 00:00 |
| 4 | backups/pre_t5273_20261007_045424.db | 1.3G | деплой t5273 |
| 5 | backups/pre_t5274_20261007_055326.db | 1.3G | деплой t5274 |

**Итого ≈ 6.5–6.6 GB** — совпадает с дельтой df (14→21G за ~40ч) в пределах
погрешности. Гипотеза подтверждена: рост диска = неротируемые копии БД
деплой-окон.

## 5. Рекомендации владельцу (НЕ исполнялось)

### A. Немедленная чистка — освободит до ~5.2 GB (92% → ~70%)
```bash
# выполнить ВРУЧНУЮ после проверки имён (read-only диагностика, команды не запускались)
rm -i /var/www/admin_bot/backups/pre_t5216_20261006_232333.db            # 1.3G
sudo rm -i /var/www/admin_bot/backups/local_database_20261007.db         # 1.3G, root
sudo rm -i /var/www/admin_bot/pre_migration_20261006_121956.db           # 1.3G, root
rm -i /home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db # 1.2G
# минимум: только pre_t5216 → +1.3G (до ~3.3G free)
```
Оставить как минимум 2 новейших полных копии (pre_t5273, pre_t5274) —
roll-back readiness сохраняется.

### B. Retention-фикс (задача для Builder, продукт-поведение не меняет)
1. Добавить деплой-бэкапы в ротацию: `DB_BACKUP_PATTERNS += ("pre_t*.db",)`
   (или отдельный `prune_deploy_backups(keep=2)`), т.к. `pre_t*` сейчас не
   матчится ни одним паттерном — это и есть утечка.
2. Ротация `pre_migration_*`: заставить миграционные скрипты писать копии в
   backups/ (скан-зону retention), либо добавить корень сервиса в scan-dirs.
3. дефолт keep=2 для pre_t* и pre_migration_* (сейчас keep=1 + не все пути).

### C. Малое (опционально, ~300M суммарно)
- `sudo journalctl --vacuum-size=100M` (~100M);
- `sudo apt-get clean` (архивы в /var/cache/apt);
- /tmp: p0_*/t5274_* артефакты и /tmp/pytest-of-nik (80M).

## 6. Инцидентальные находки (не блокер релиза)

1. **[medium, monitoring] healthz по IP недоступен снаружи**: `https://198.46.175.136/healthz`
   — TLS handshake не проходит (curl code 000), `http://.../healthz` → 308 на
   https (Caddy жив). Канал «проверка прода по HTTP 443» из AGENTS.md по
   голому IP не работает (вероятно, нужен SNI/домен). Сервис при этом жив
   (systemctl + свежий wal). Pre-existing, к текущему релизу отношения не имеет.
2. **[low] stale journal**: `/var/www/admin_bot/pre_migration_20261001_161834.db-journal`
   (1KB, Oct 1) — остаток прерванного миграционного окна 01.10; кандидат на
   удаление вместе с pre_migration-копиями.
3. **[info] риск следующего деплоя**: при 2.0G free следующий деплой-тур с
   полным бэкапом (1.3G) упрётся в диск — чистку/ротацию стоит сделать до
   следующего релизного окна.

## Чистка исполнена (D2-disk-clean, 07.10.2026 08:37 UTC)

Одобренный владельцем список исполнен целиком, 4/4; каждая позиция прошла двойную
верификацию перед rm (ls -lh + stat: точный путь/размер/дата совпали с диагнозом).

| Удалено | Размер (байт) | Дата |
|---|---|---|
| backups/pre_t5216_20261006_232333.db | 1 322 758 144 | 2026-10-06 23:24 |
| pre_migration_20261006_121956.db (корень) | 1 321 435 136 | 2026-10-06 12:20 |
| backups/local_database_20261007.db | 1 322 766 336 | 2026-10-07 00:00 |
| /home/nik/backups_adminbot/...pre_v21.db | 1 281 642 496 | 2026-10-01 08:02 |

- df после: **24G / used 16G / avail 6.9G (70%)** — было 21G / 2.0G (92%); освобождено ≈ 4.9G.
- Rollback-якоря целы: pre_t5273_20261007_045424.db (1 323 368 448 B) и
  pre_t5274_20261007_055326.db (1 324 044 288 B) — size/mtime до и после идентичны.
  В backups/ из *.db остались только эти два.
- Сервис: не перезапускался, admin_bot active, healthz 200 `{"status":"ok","version":"2.58.69"}`
  (проверен с сервера и снаружи по домену). Git/конфиги не тронуты (HEAD 42f8963).
- Соединения по AGENTS.md: 1 recon + 1 основной батч. Протокол/лог: Temp-лог
  `d2_disk_clean_log.txt` (вне репо); скрипт `tools/_d2_disk_clean.py`.
- Расхождений с диагнозом нет (гейт-пропусков 0). Замечание: pre_t5216 и
  local_database_20261007 принадлежали root — сработал sudo-fallback на тот же
  одобренный путь.

## Итог

- Причина роста: 5 копий БД × ~1.3G ≈ 6.6 GB за 40ч; корень — паттерн `pre_t*.db`
  вне retention-ротации disk_retention.py.
- Free сейчас: 2.0G (92%). Без действий диск закончится за 1–2 деплой-тура.
- Статус диагностики: VERIFIED (read-only, цифры du/df, без изменений на проде).

## Фикс ротации (Builder, 2026-10-07)

- `services/disk_retention.py`: `pre_t*.db` → отдельный пул `DEPLOY_BACKUP_PATTERNS` + `prune_deploy_backups(keep=2)` (не `DB_BACKUP_PATTERNS` — там call-site держат «ровно 1»; не `MIGRATION_BACKUP_PATTERNS` — call-site миграций передаёт keep=1, смешанный пул снёс бы rollback-копии до 1); вариант «отдельный `prune_deploy_backups(keep=2)`» из §5B.1.
- Тест `tests/test_disk_retention_deploy_backups.py` (tmp_path): 4 фиктивных pre_t*.db → остаются 2 новейших; daily/pre_migration/history/facts не тронуты; прогон 87 passed (включая существующие disk_retention/memory_backup).
- Прод не тронут: ротация подхватит `pre_t*` только в будущих прогонах retention; ручная чистка текущих копий — решение владельца (§5A).
